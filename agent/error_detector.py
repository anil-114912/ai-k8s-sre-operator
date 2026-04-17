"""Matches log lines against error patterns and tracks per-window counts."""

from __future__ import annotations

import logging
import re
import time
from collections import defaultdict, deque
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

import yaml

logger = logging.getLogger(__name__)

_DEFAULT_WINDOW_SECS = 30
_DEFAULT_COUNT_THRESHOLD = 1


@dataclass
class Pattern:
    """A compiled error pattern."""

    id: str
    name: str
    regex: re.Pattern
    severity: str
    incident_type: str
    count_threshold: int = _DEFAULT_COUNT_THRESHOLD
    window_secs: int = _DEFAULT_WINDOW_SECS
    track_trend: bool = False
    remediation_hint: str = ""


@dataclass
class PatternMatch:
    """A single pattern match result."""

    pattern_id: str
    pattern_name: str
    severity: str
    incident_type: str
    line: str
    timestamp: float
    remediation_hint: str = ""


@dataclass
class DetectionWindow:
    """Rolling window of matches for threshold checking."""

    pattern_id: str
    window_secs: int
    threshold: int
    _hits: deque = field(default_factory=deque)

    def record(self, ts: float) -> None:
        self._hits.append(ts)
        cutoff = ts - self.window_secs
        while self._hits and self._hits[0] < cutoff:
            self._hits.popleft()

    def count(self) -> int:
        return len(self._hits)

    def threshold_exceeded(self) -> bool:
        return self.count() >= self.threshold


@dataclass
class DetectedPattern:
    """Aggregated detection result for the current report window."""

    pattern_id: str
    pattern_name: str
    count: int
    severity: str
    incident_type: str
    sample: str
    remediation_hint: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "pattern_id": self.pattern_id,
            "pattern_name": self.pattern_name,
            "count": self.count,
            "severity": self.severity,
            "incident_type": self.incident_type,
            "sample": self.sample,
            "remediation_hint": self.remediation_hint,
        }


class ErrorDetector:
    """Matches log lines against compiled patterns and aggregates results.

    Usage::

        detector = ErrorDetector.from_yaml(builtin_path, custom_path)
        for line in log_tailer.lines():
            detector.process_line(line)
        report = detector.flush()  # get + reset counts for this window
    """

    def __init__(self, patterns: List[Pattern], ignore_patterns: List[str] | None = None) -> None:
        self._patterns = patterns
        self._windows: Dict[str, DetectionWindow] = {
            p.id: DetectionWindow(p.id, p.window_secs, p.count_threshold) for p in patterns
        }
        self._counts: Dict[str, int] = defaultdict(int)
        self._samples: Dict[str, str] = {}
        self._trend_history: Dict[str, List[int]] = defaultdict(list)

        # Compile ignore patterns
        self._ignores: List[re.Pattern] = []
        for pat in ignore_patterns or []:
            try:
                self._ignores.append(re.compile(pat, re.IGNORECASE))
            except re.error as exc:
                logger.warning("Invalid ignore pattern '%s': %s", pat, exc)

        logger.info("ErrorDetector loaded %d patterns", len(self._patterns))

    @classmethod
    def from_yaml(
        cls,
        builtin_path: Path,
        custom_path: Optional[str] = None,
        ignore_patterns: Optional[List[str]] = None,
    ) -> "ErrorDetector":
        """Load patterns from one or two YAML files."""
        raw: List[Dict] = []
        for path in filter(None, [str(builtin_path), custom_path]):
            p = Path(path)
            if not p.exists():
                logger.warning("Pattern file not found: %s", path)
                continue
            try:
                data = yaml.safe_load(p.read_text(encoding="utf-8"))
                # Support top-level list or {patterns: [...]}
                if isinstance(data, list):
                    raw.extend(data)
                elif isinstance(data, dict) and "patterns" in data:
                    raw.extend(data["patterns"])
                logger.info("Loaded %d patterns from %s", len(raw), path)
            except Exception as exc:
                logger.error("Failed to load patterns from %s: %s", path, exc)

        patterns = []
        for item in raw:
            try:
                patterns.append(
                    Pattern(
                        id=item["id"],
                        name=item["name"],
                        regex=re.compile(item["pattern"], re.IGNORECASE | re.MULTILINE),
                        severity=item.get("severity", "medium"),
                        incident_type=item.get("incident_type", "APM_GENERIC"),
                        count_threshold=int(item.get("count_threshold", _DEFAULT_COUNT_THRESHOLD)),
                        window_secs=int(item.get("window_secs", _DEFAULT_WINDOW_SECS)),
                        track_trend=bool(item.get("track_trend", False)),
                        remediation_hint=item.get("remediation_hint", ""),
                    )
                )
            except Exception as exc:
                logger.warning("Skipping malformed pattern %s: %s", item.get("id", "?"), exc)

        return cls(patterns, ignore_patterns)

    def process_line(self, line: str) -> List[PatternMatch]:
        """Match a single log line against all patterns. Returns matches (may be empty)."""
        if not line.strip():
            return []

        # Check ignore list first
        for ignore in self._ignores:
            if ignore.search(line):
                return []

        ts = time.time()
        matches = []
        for p in self._patterns:
            if p.regex.search(line):
                self._windows[p.id].record(ts)
                self._counts[p.id] += 1
                if p.id not in self._samples:
                    self._samples[p.id] = line[:300]
                matches.append(
                    PatternMatch(
                        pattern_id=p.id,
                        pattern_name=p.name,
                        severity=p.severity,
                        incident_type=p.incident_type,
                        line=line[:300],
                        timestamp=ts,
                        remediation_hint=p.remediation_hint,
                    )
                )

        return matches

    def flush(self) -> List[DetectedPattern]:
        """Return aggregated detections since last flush and reset counters.

        Only returns patterns that exceeded their count_threshold.
        """
        results = []
        for p in self._patterns:
            count = self._counts.get(p.id, 0)
            if count == 0:
                if p.track_trend:
                    self._trend_history[p.id].append(0)
                continue

            if p.track_trend:
                self._trend_history[p.id].append(count)

            # Only include in report if threshold met
            if count >= p.count_threshold:
                results.append(
                    DetectedPattern(
                        pattern_id=p.id,
                        pattern_name=p.name,
                        count=count,
                        severity=p.severity,
                        incident_type=p.incident_type,
                        sample=self._samples.get(p.id, ""),
                        remediation_hint=p.remediation_hint,
                    )
                )

        # Reset window
        self._counts.clear()
        self._samples.clear()
        return results

    def trend(self, pattern_id: str) -> List[int]:
        """Return the count history for a trend-tracked pattern."""
        return list(self._trend_history.get(pattern_id, []))

    def novel_lines(self) -> List[str]:
        """Return log lines that matched no known patterns (potential novel errors).

        These are passed to the pattern_learner for learning store insertion.
        Call after flush() — novel lines are cleared on each flush.
        """
        return list(self._novel_buffer)

    def record_novel(self, line: str) -> None:
        """Record a line that looks like an error but matches no pattern."""
        if not hasattr(self, "_novel_buffer"):
            self._novel_buffer: deque = deque(maxlen=50)
        self._novel_buffer.append(line)
