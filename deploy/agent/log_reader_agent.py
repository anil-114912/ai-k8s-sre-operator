"""Standalone K8s log-reader agent.

Reads pod logs via the Kubernetes API (no shared volume needed) and
forwards APM reports to the SRE operator. Works with any pod that
logs to stdout/stderr — which is the standard K8s pattern.

Deploy as a single pod in the ai-sre namespace. It watches all target
namespaces and tails logs from running pods.

Usage:
    python deploy/agent/log_reader_agent.py

Env vars:
    OPERATOR_API_URL   — e.g. http://ai-sre-operator-api:8000
    TARGET_NAMESPACES  — comma-separated, e.g. "dev,qa,default"
    TAIL_LINES         — initial lines to read (default 100)
    REPORT_INTERVAL    — seconds between APM reports (default 30)
    LOG_LEVEL          — DEBUG, INFO, WARNING (default INFO)
"""

from __future__ import annotations

import json
import logging
import os
import re
import signal
import sys
import threading
import time
import urllib.request
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

logging.basicConfig(
    level=getattr(logging, os.getenv("LOG_LEVEL", "INFO").upper(), logging.INFO),
    format="%(asctime)s %(levelname)-7s %(name)s: %(message)s",
    datefmt="%Y-%m-%dT%H:%M:%S",
    stream=sys.stdout,
)
logger = logging.getLogger("sre-log-reader")

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

OPERATOR_API_URL = os.getenv("OPERATOR_API_URL", "http://localhost:8000").rstrip("/")
TARGET_NAMESPACES = [
    ns.strip()
    for ns in os.getenv("TARGET_NAMESPACES", "dev,qa,default").split(",")
    if ns.strip()
]
TAIL_LINES = int(os.getenv("TAIL_LINES", "100"))
REPORT_INTERVAL = int(os.getenv("REPORT_INTERVAL", "30"))
EXCLUDE_PODS = set(
    p.strip()
    for p in os.getenv("EXCLUDE_PODS", "").split(",")
    if p.strip()
)

_ERROR_KW = {"error", "exception", "fatal", "panic", "traceback", "critical", "fail"}
_WARN_KW = {"warn", "warning"}
_TRACEBACK_START = {"traceback", "caused by", "exception in", "at ", "  file "}
_LATENCY_RE = re.compile(
    r"(?:duration|latency|took|elapsed|response[_\s]?time)[=:\s]+([0-9]+(?:\.[0-9]+)?)\s*(ms|s|µs)\b",
    re.IGNORECASE,
)
_HTTP_STATUS_RE = re.compile(r'"\s*(GET|POST|PUT|DELETE|PATCH|HEAD|OPTIONS)\s+\S+.*?"\s+(\d{3})', re.IGNORECASE)

_stop = threading.Event()


# ---------------------------------------------------------------------------
# K8s API helpers (uses in-cluster or kubeconfig service account token)
# ---------------------------------------------------------------------------

def _k8s_headers() -> Dict[str, str]:
    token_path = "/var/run/secrets/kubernetes.io/serviceaccount/token"
    if os.path.exists(token_path):
        with open(token_path) as f:
            token = f.read().strip()
        return {"Authorization": f"Bearer {token}"}
    # Fallback: use kubectl proxy or kubeconfig (for local dev)
    return {}


def _k8s_base() -> str:
    if os.path.exists("/var/run/secrets/kubernetes.io/serviceaccount/token"):
        return "https://kubernetes.default.svc"
    return os.getenv("KUBERNETES_API_URL", "http://localhost:8001")


def _k8s_get(path: str) -> Optional[Any]:
    import ssl
    url = f"{_k8s_base()}{path}"
    headers = _k8s_headers()
    req = urllib.request.Request(url, headers=headers)
    ctx = ssl.create_default_context()
    ca_path = "/var/run/secrets/kubernetes.io/serviceaccount/ca.crt"
    if os.path.exists(ca_path):
        ctx.load_verify_locations(ca_path)
    else:
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE
    try:
        with urllib.request.urlopen(req, timeout=10, context=ctx) as resp:
            return json.loads(resp.read())
    except Exception as exc:
        logger.warning("K8s API error: %s %s", path, exc)
        return None


def list_pods(namespace: str) -> List[Dict[str, Any]]:
    data = _k8s_get(f"/api/v1/namespaces/{namespace}/pods")
    if not data:
        return []
    pods = []
    for item in data.get("items", []):
        phase = item.get("status", {}).get("phase", "")
        name = item.get("metadata", {}).get("name", "")
        if phase == "Running" and name not in EXCLUDE_PODS:
            containers = [
                c["name"] for c in item.get("spec", {}).get("containers", [])
            ]
            pods.append({
                "name": name,
                "namespace": namespace,
                "containers": containers,
                "labels": item.get("metadata", {}).get("labels", {}),
            })
    return pods


def get_pod_logs(namespace: str, pod: str, container: str, tail: int = 100) -> List[str]:
    data = _k8s_get(
        f"/api/v1/namespaces/{namespace}/pods/{pod}/log"
        f"?container={container}&tailLines={tail}&timestamps=false"
    )
    if isinstance(data, dict):
        # Sometimes the API returns JSON error
        return []
    # Logs come as raw text, not JSON
    url = f"{_k8s_base()}/api/v1/namespaces/{namespace}/pods/{pod}/log?container={container}&tailLines={tail}"
    headers = _k8s_headers()
    req = urllib.request.Request(url, headers=headers)
    import ssl
    ctx = ssl.create_default_context()
    ca_path = "/var/run/secrets/kubernetes.io/serviceaccount/ca.crt"
    if os.path.exists(ca_path):
        ctx.load_verify_locations(ca_path)
    else:
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE
    try:
        with urllib.request.urlopen(req, timeout=15, context=ctx) as resp:
            text = resp.read().decode("utf-8", errors="replace")
            return [line for line in text.splitlines() if line.strip()]
    except Exception as exc:
        logger.debug("Failed to get logs for %s/%s/%s: %s", namespace, pod, container, exc)
        return []


# ---------------------------------------------------------------------------
# Metrics per service
# ---------------------------------------------------------------------------

@dataclass
class ServiceMetrics:
    namespace: str = ""
    service_name: str = ""
    pod_name: str = ""
    total_lines: int = 0
    error_count: int = 0
    warning_count: int = 0
    http_5xx_count: int = 0
    http_4xx_count: int = 0
    latencies: List[float] = field(default_factory=list)
    novel_errors: List[str] = field(default_factory=list)
    error_lines: List[str] = field(default_factory=list)
    patterns_detected: List[Dict[str, Any]] = field(default_factory=list)
    _traceback_buffer: List[str] = field(default_factory=list)
    _in_traceback: bool = False

    def process_line(self, line: str) -> None:
        self.total_lines += 1
        low = line.lower().strip()

        # Detect traceback blocks
        if any(low.startswith(t) for t in _TRACEBACK_START) or self._in_traceback:
            self._traceback_buffer.append(line)
            # End of traceback: line that doesn't start with whitespace and isn't a "Caused by"
            if self._in_traceback and line and not line[0].isspace() and not low.startswith("caused by"):
                self._flush_traceback()
            else:
                self._in_traceback = True
            return

        if low.startswith("traceback"):
            self._in_traceback = True
            self._traceback_buffer = [line]
            return

        # HTTP status codes
        m_http = _HTTP_STATUS_RE.search(line)
        if m_http:
            status = int(m_http.group(2))
            if 500 <= status <= 599:
                self.http_5xx_count += 1
                self.error_count += 1
                self._add_error_line(line, f"HTTP {status}")
            elif 400 <= status <= 499:
                self.http_4xx_count += 1
                if status not in (401, 404):  # skip common auth/not-found
                    self.warning_count += 1

        # Error keywords
        elif any(kw in low for kw in _ERROR_KW):
            self.error_count += 1
            self._add_error_line(line, "error_keyword")
        elif any(kw in low for kw in _WARN_KW):
            self.warning_count += 1

        # Latency extraction
        m = _LATENCY_RE.search(line)
        if m:
            val = float(m.group(1))
            unit = m.group(2).lower()
            if unit == "s":
                val *= 1000
            elif unit in ("µs", "us"):
                val /= 1000
            self.latencies.append(val)

    def _add_error_line(self, line: str, category: str) -> None:
        """Store the error line and build a pattern entry."""
        trimmed = line.strip()[:500]
        if len(self.error_lines) < 50:
            self.error_lines.append(trimmed)
        if len(self.novel_errors) < 20:
            self.novel_errors.append(trimmed)
        # Group into a simple pattern
        self._add_pattern(trimmed, category)

    def _flush_traceback(self) -> None:
        """Flush a collected traceback block as a single error."""
        if not self._traceback_buffer:
            return
        tb_text = "\n".join(self._traceback_buffer[-30:])  # last 30 lines max
        self.error_count += 1
        if len(self.error_lines) < 50:
            self.error_lines.append(tb_text[:1000])
        if len(self.novel_errors) < 20:
            self.novel_errors.append(tb_text[:1000])
        # Use the last line (usually the exception message) as pattern name
        last_line = self._traceback_buffer[-1].strip() if self._traceback_buffer else "Unknown"
        self._add_pattern(last_line, "traceback", sample=tb_text[:500])
        self._traceback_buffer.clear()
        self._in_traceback = False

    def _add_pattern(self, line: str, category: str, sample: str = "") -> None:
        """Add or increment a detected pattern."""
        # Simple dedup: use first 80 chars as pattern key
        pattern_key = line[:80]
        for p in self.patterns_detected:
            if p.get("pattern_id") == pattern_key:
                p["count"] = p.get("count", 1) + 1
                return
        severity = "high" if category in ("traceback", "HTTP 500", "HTTP 502", "HTTP 503") else "medium"
        self.patterns_detected.append({
            "pattern_id": pattern_key,
            "pattern_name": f"{category}: {line[:120]}",
            "count": 1,
            "severity": severity,
            "incident_type": f"APM_{category.upper()}",
            "sample": sample or line[:500],
        })

    def build_report(self) -> Dict[str, Any]:
        # Flush any pending traceback
        if self._traceback_buffer:
            self._flush_traceback()

        error_rate = self.error_count / max(self.total_lines, 1)
        metrics: Dict[str, Any] = {
            "http_5xx_count": self.http_5xx_count,
            "http_4xx_count": self.http_4xx_count,
        }
        if self.latencies:
            s = sorted(self.latencies)
            metrics["latency_p50_ms"] = round(s[len(s) // 2], 2)
            metrics["latency_p95_ms"] = round(s[int(len(s) * 0.95)], 2)
            metrics["latency_p99_ms"] = round(s[int(len(s) * 0.99)], 2)
        return {
            "pod_name": self.pod_name,
            "namespace": self.namespace,
            "service_name": self.service_name,
            "report_window_secs": REPORT_INTERVAL,
            "error_count": self.error_count,
            "warning_count": self.warning_count,
            "total_lines": self.total_lines,
            "error_rate": round(error_rate, 6),
            "patterns_detected": self.patterns_detected,
            "metrics": metrics,
            "novel_errors": self.novel_errors[:20],
            "agent_version": "0.3.0-logreader",
        }

    def reset(self) -> None:
        self.total_lines = 0
        self.error_count = 0
        self.warning_count = 0
        self.http_5xx_count = 0
        self.http_4xx_count = 0
        self.latencies.clear()
        self.novel_errors.clear()
        self.error_lines.clear()
        self.patterns_detected.clear()
        self._traceback_buffer.clear()
        self._in_traceback = False


# ---------------------------------------------------------------------------
# Report sender
# ---------------------------------------------------------------------------

def send_report(report: Dict[str, Any]) -> bool:
    url = f"{OPERATOR_API_URL}/api/v1/apm/ingest"
    try:
        data = json.dumps(report).encode("utf-8")
        req = urllib.request.Request(
            url, data=data,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=10) as resp:
            return resp.status in (200, 201, 202)
    except Exception as exc:
        logger.warning("Failed to send report: %s", exc)
        return False


# ---------------------------------------------------------------------------
# Main loop
# ---------------------------------------------------------------------------

def _service_name_from_pod(pod: Dict[str, Any]) -> str:
    labels = pod.get("labels", {})
    for key in ("app", "app.kubernetes.io/name", "app.kubernetes.io/instance"):
        if labels.get(key):
            return labels[key]
    # Fallback: strip the replicaset hash from pod name
    name = pod.get("name", "unknown")
    parts = name.rsplit("-", 2)
    return "-".join(parts[:-2]) if len(parts) > 2 else name


def run() -> None:
    logger.info("SRE Log Reader Agent starting")
    logger.info("Operator API: %s", OPERATOR_API_URL)
    logger.info("Target namespaces: %s", TARGET_NAMESPACES)
    logger.info("Report interval: %ds", REPORT_INTERVAL)

    signal.signal(signal.SIGTERM, lambda *_: _stop.set())
    signal.signal(signal.SIGINT, lambda *_: _stop.set())

    # Track last-seen line count per pod to only read new lines
    _last_seen: Dict[str, int] = defaultdict(int)

    while not _stop.is_set():
        cycle_start = time.time()
        all_metrics: Dict[str, ServiceMetrics] = {}

        for ns in TARGET_NAMESPACES:
            pods = list_pods(ns)
            for pod in pods:
                svc_name = _service_name_from_pod(pod)
                pod_name = pod["name"]
                key = f"{ns}/{pod_name}"

                if key not in all_metrics:
                    all_metrics[key] = ServiceMetrics(
                        namespace=ns,
                        service_name=svc_name,
                        pod_name=pod_name,
                    )

                for container in pod["containers"]:
                    lines = get_pod_logs(ns, pod_name, container, tail=TAIL_LINES)
                    # Only process lines we haven't seen
                    prev_count = _last_seen.get(f"{key}/{container}", 0)
                    new_lines = lines[prev_count:] if prev_count < len(lines) else lines[-20:]
                    _last_seen[f"{key}/{container}"] = len(lines)

                    for line in new_lines:
                        all_metrics[key].process_line(line)

        # Send reports
        sent = 0
        for key, metrics in all_metrics.items():
            if metrics.total_lines == 0:
                continue
            report = metrics.build_report()
            if send_report(report):
                sent += 1
                logger.debug(
                    "Report sent: %s/%s errors=%d lines=%d",
                    metrics.namespace, metrics.service_name,
                    metrics.error_count, metrics.total_lines,
                )
            metrics.reset()

        if sent:
            logger.info("Cycle complete: %d reports sent from %d pods", sent, len(all_metrics))

        # Sleep until next interval
        elapsed = time.time() - cycle_start
        sleep_time = max(1, REPORT_INTERVAL - elapsed)
        _stop.wait(timeout=sleep_time)

    logger.info("Agent stopped")


if __name__ == "__main__":
    run()
