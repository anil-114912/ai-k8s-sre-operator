"""Aggregates APM metrics and sends reports to the operator API."""

from __future__ import annotations

import json
import logging
import os
import re
import time
from collections import deque
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

# Regex to extract latency values from log lines, e.g.:
#   "GET /api 200 345ms"  "duration=1.23s"  "took 456 ms"
_LATENCY_RE = re.compile(
    r"(?:duration|latency|took|elapsed|response[_\s]?time)[=:\s]+([0-9]+(?:\.[0-9]+)?)\s*(ms|s|µs)\b",
    re.IGNORECASE,
)

_THROUGHPUT_RE = re.compile(
    r"(?:rps|req(?:uests)?[_/]s(?:ec)?|throughput)[=:\s]+([0-9]+(?:\.[0-9]+)?)",
    re.IGNORECASE,
)


def _to_ms(value: float, unit: str) -> float:
    unit = unit.lower()
    if unit == "s":
        return value * 1000
    if unit in ("µs", "us"):
        return value / 1000
    return value  # ms


@dataclass
class APMReport:
    """A single APM report sent to the operator every report_interval_secs."""

    pod_name: str
    namespace: str
    service_name: str
    report_window_secs: int
    timestamp: float
    error_count: int
    warning_count: int
    total_lines: int
    error_rate: float
    patterns_detected: List[Dict[str, Any]]
    metrics: Dict[str, Any]
    novel_errors: List[str]
    agent_version: str

    def to_dict(self) -> Dict[str, Any]:
        d = asdict(self)
        d["timestamp"] = self.timestamp
        return d


@dataclass
class _LatencyBucket:
    _samples: deque = field(default_factory=lambda: deque(maxlen=10_000))

    def record(self, ms: float) -> None:
        self._samples.append(ms)

    def percentile(self, pct: float) -> Optional[float]:
        if not self._samples:
            return None
        sorted_samples = sorted(self._samples)
        idx = max(0, int(len(sorted_samples) * pct / 100) - 1)
        return round(sorted_samples[idx], 2)

    def flush(self) -> Dict[str, Any]:
        if not self._samples:
            return {}
        result = {
            "latency_p50_ms": self.percentile(50),
            "latency_p95_ms": self.percentile(95),
            "latency_p99_ms": self.percentile(99),
            "latency_count": len(self._samples),
        }
        self._samples.clear()
        return result


class MetricsReporter:
    """Collects line-level metrics and sends periodic reports to the operator API.

    Usage::

        reporter = MetricsReporter(config)
        reporter.record_line(line)
        reporter.record_patterns(detector.flush())
        # Called in background thread by agent.main:
        reporter.report_loop()
    """

    def __init__(self, config: Any) -> None:
        self._cfg = config
        self._latency = _LatencyBucket()
        self._total_lines = 0
        self._error_count = 0
        self._warning_count = 0
        self._throughput_samples: deque = deque(maxlen=100)
        self._patterns: List[Dict] = []
        self._novel_errors: List[str] = []
        self._start_ts = time.time()
        self._buffer_dir = Path(config.buffer_dir)
        self._buffer_dir.mkdir(parents=True, exist_ok=True)

    def record_line(self, line: str) -> None:
        """Update per-line metrics from a raw log line."""
        self._total_lines += 1
        low = line.lower()

        # Count errors / warnings
        if any(kw in low for kw in ("error", "exception", "fatal", "panic", "critical")):
            self._error_count += 1
        elif any(kw in low for kw in ("warn", "warning")):
            self._warning_count += 1

        # Extract latency
        m = _LATENCY_RE.search(line)
        if m:
            ms = _to_ms(float(m.group(1)), m.group(2))
            self._latency.record(ms)

        # Extract throughput
        m2 = _THROUGHPUT_RE.search(line)
        if m2:
            self._throughput_samples.append(float(m2.group(1)))

    def record_patterns(self, detected: List[Any]) -> None:
        """Accept flush() results from ErrorDetector."""
        for d in detected:
            self._patterns.append(d.to_dict() if hasattr(d, "to_dict") else d)

    def record_novel(self, lines: List[str]) -> None:
        """Accept novel (unrecognised) error lines from ErrorDetector."""
        self._novel_errors.extend(lines[:20])  # cap at 20 per window

    def _build_report(self) -> APMReport:
        window = time.time() - self._start_ts
        error_rate = self._error_count / max(self._total_lines, 1)
        metrics: Dict[str, Any] = {**self._latency.flush()}
        if self._throughput_samples:
            metrics["requests_per_sec"] = round(
                sum(self._throughput_samples) / len(self._throughput_samples), 2
            )
        return APMReport(
            pod_name=self._cfg.pod_name,
            namespace=self._cfg.pod_namespace,
            service_name=self._cfg.service_name,
            report_window_secs=int(window),
            timestamp=time.time(),
            error_count=self._error_count,
            warning_count=self._warning_count,
            total_lines=self._total_lines,
            error_rate=round(error_rate, 6),
            patterns_detected=list(self._patterns),
            metrics=metrics,
            novel_errors=list(self._novel_errors[:10]),
            agent_version=self._cfg.agent_version,
        )

    def _reset(self) -> None:
        self._total_lines = 0
        self._error_count = 0
        self._warning_count = 0
        self._throughput_samples.clear()
        self._patterns.clear()
        self._novel_errors.clear()
        self._start_ts = time.time()

    def _send(self, report: APMReport) -> bool:
        """POST the report to the operator API. Returns True on success."""
        try:
            import urllib.request

            url = f"{self._cfg.operator_api_url}/api/v1/apm/ingest"
            data = json.dumps(report.to_dict()).encode("utf-8")
            req = urllib.request.Request(
                url,
                data=data,
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            with urllib.request.urlopen(req, timeout=self._cfg.api_timeout_secs) as resp:
                if resp.status in (200, 201, 202):
                    logger.debug(
                        "Report sent: %d errors, %d patterns, %d lines",
                        report.error_count,
                        len(report.patterns_detected),
                        report.total_lines,
                    )
                    return True
                logger.warning("Operator API returned %d", resp.status)
                return False
        except Exception as exc:
            logger.warning("Failed to send report to operator API: %s", exc)
            return False

    def _buffer(self, report: APMReport) -> None:
        """Write report to local buffer for later replay."""
        ts = int(report.timestamp)
        path = self._buffer_dir / f"report_{ts}.json"
        try:
            path.write_text(json.dumps(report.to_dict()), encoding="utf-8")
            # Drop oldest if over limit
            buffered = sorted(self._buffer_dir.glob("report_*.json"))
            while len(buffered) > self._cfg.max_buffer_reports:
                buffered.pop(0).unlink(missing_ok=True)
        except OSError as exc:
            logger.warning("Failed to buffer report: %s", exc)

    def _flush_buffer(self) -> None:
        """Replay buffered reports to operator API."""
        buffered = sorted(self._buffer_dir.glob("report_*.json"))
        for path in buffered:
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
                if self._send_raw(data):
                    path.unlink(missing_ok=True)
                    logger.info("Replayed buffered report: %s", path.name)
            except Exception as exc:
                logger.warning("Failed to replay %s: %s", path.name, exc)

    def _send_raw(self, payload: Dict) -> bool:
        try:
            import urllib.request

            url = f"{self._cfg.operator_api_url}/api/v1/apm/ingest"
            data = json.dumps(payload).encode("utf-8")
            req = urllib.request.Request(
                url,
                data=data,
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            with urllib.request.urlopen(req, timeout=self._cfg.api_timeout_secs) as resp:
                return resp.status in (200, 201, 202)
        except Exception:
            return False

    def report_loop(self) -> None:
        """Main report loop — runs in background thread, sends every interval_secs."""
        logger.info(
            "Reporter started: service=%s interval=%ds api=%s",
            self._cfg.service_name,
            self._cfg.report_interval_secs,
            self._cfg.operator_api_url,
        )
        while True:
            time.sleep(self._cfg.report_interval_secs)
            report = self._build_report()
            self._reset()

            # Try to flush any buffered reports first
            self._flush_buffer()

            if not self._send(report):
                self._buffer(report)
                logger.warning(
                    "Report buffered (API unreachable): %d errors in window",
                    report.error_count,
                )
            else:
                logger.info(
                    "Report sent: errors=%d patterns=%d lines=%d error_rate=%.4f",
                    report.error_count,
                    len(report.patterns_detected),
                    report.total_lines,
                    report.error_rate,
                )
