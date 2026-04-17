"""Captures novel application error patterns and sends them to the operator learning store."""

from __future__ import annotations

import logging
import re
from collections import Counter
from typing import Any, Dict, List

logger = logging.getLogger(__name__)

# Lines that look like errors but match no known pattern
_ERROR_SIGNAL_RE = re.compile(
    r"\b(error|exception|fail(ed|ure)?|fatal|panic|critical|traceback|abort|crash)\b",
    re.IGNORECASE,
)

# Lines to ignore even if they contain error keywords
_NOISE_RE = re.compile(
    r"(error_rate|error_count|no error|without error|successfully|OK|200)",
    re.IGNORECASE,
)

# Minimum length for a line to be worth capturing
_MIN_LINE_LEN = 20


class PatternLearner:
    """Accumulates unrecognised error lines and periodically submits them
    to the operator API's learning store endpoint.

    The operator will:
    1. Store the raw line in the learned pattern buffer
    2. Use TF-IDF / embedding to cluster similar lines across services
    3. Eventually promote repeated patterns to knowledge/failures/learned.yaml
    """

    def __init__(self, config: Any, max_buffer: int = 200) -> None:
        self._cfg = config
        self._max_buffer = max_buffer
        self._buffer: List[str] = []
        self._freq: Counter = Counter()

    def observe(self, line: str) -> bool:
        """Check if a line looks like a novel error. Buffer it if so.

        Returns True if the line was considered a novel error signal.
        """
        if len(line) < _MIN_LINE_LEN:
            return False
        if not _ERROR_SIGNAL_RE.search(line):
            return False
        if _NOISE_RE.search(line):
            return False

        # Normalise: strip timestamps, hex addresses, UUIDs, numbers
        normalised = re.sub(r"\b[0-9a-f]{8}-[0-9a-f-]{27}\b", "<uuid>", line, flags=re.IGNORECASE)
        normalised = re.sub(r"\b0x[0-9a-f]+\b", "<addr>", normalised, flags=re.IGNORECASE)
        normalised = re.sub(r"\b\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}:\d{2}", "<ts>", normalised)
        normalised = re.sub(r"\b\d+\b", "<n>", normalised)

        self._freq[normalised] += 1

        if len(self._buffer) < self._max_buffer:
            self._buffer.append(line[:400])

        return True

    def flush_to_api(self) -> bool:
        """Send buffered novel lines to operator learning endpoint. Returns True on success."""
        if not self._buffer:
            return True

        try:
            import json
            import urllib.request

            # Only send the top-N most frequent novel lines to reduce noise
            top_lines = [line for line, _ in self._freq.most_common(20)]

            payload = {
                "pod_name": self._cfg.pod_name,
                "namespace": self._cfg.pod_namespace,
                "service_name": self._cfg.service_name,
                "novel_error_lines": top_lines,
                "total_novel_count": len(self._buffer),
                "agent_version": self._cfg.agent_version,
            }
            data = json.dumps(payload).encode("utf-8")
            url = f"{self._cfg.operator_api_url}/api/v1/apm/learn"
            req = urllib.request.Request(
                url,
                data=data,
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            with urllib.request.urlopen(req, timeout=self._cfg.api_timeout_secs) as resp:
                if resp.status in (200, 201, 202, 204):
                    logger.info(
                        "Submitted %d novel error lines to operator learning store",
                        len(top_lines),
                    )
                    self._reset()
                    return True
                logger.warning("Learning endpoint returned %d", resp.status)
                return False
        except Exception as exc:
            logger.debug("Failed to submit novel patterns: %s", exc)
            return False

    def _reset(self) -> None:
        self._buffer.clear()
        self._freq.clear()

    def summary(self) -> Dict[str, Any]:
        return {
            "buffered_novel_lines": len(self._buffer),
            "top_patterns": [
                {"line": line[:100], "count": count} for line, count in self._freq.most_common(5)
            ],
        }
