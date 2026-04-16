"""Builds chronological timelines from K8s events, rollouts, and logs."""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


class TimelineEvent:
    """A single chronological event entry in the incident timeline."""

    def __init__(
        self,
        timestamp: str,
        kind: str,
        source: str,
        message: str,
        resource: str = "",
        severity: str = "info",
    ) -> None:
        """Initialise a TimelineEvent."""
        self.timestamp = timestamp
        self.kind = kind
        self.source = source
        self.message = message
        self.resource = resource
        self.severity = severity

    def to_dict(self) -> Dict[str, str]:
        """Serialise to a plain dict."""
        return {
            "timestamp": self.timestamp,
            "kind": self.kind,
            "source": self.source,
            "message": self.message,
            "resource": self.resource,
            "severity": self.severity,
        }

    def __lt__(self, other: "TimelineEvent") -> bool:
        """Enable sorting by timestamp."""
        return self.timestamp < other.timestamp


class TimelineBuilder:
    """Assembles a chronological timeline from disparate Kubernetes signals."""

    def build(
        self,
        events: List[Dict[str, Any]],
        recent_changes: List[Dict[str, Any]] = None,
        log_entries: List[str] = None,
        pod_name: str = "",
    ) -> List[TimelineEvent]:
        """Build a sorted timeline from all available signals.

        Args:
            events: List of Kubernetes event dicts.
            recent_changes: Deployment/rollout change records.
            log_entries: Raw log lines with timestamps.
            pod_name: Optional pod name for filtering events.

        Returns:
            Chronologically sorted list of TimelineEvent objects.
        """
        timeline: List[TimelineEvent] = []

        # Process K8s events
        for ev in events or []:
            ts = ev.get("lastTimestamp") or ev.get("firstTimestamp") or ""
            if not ts:
                continue

            involved = ev.get("involvedObject", {})
            resource = f"{involved.get('kind', '')} {involved.get('name', '')}".strip()
            reason = ev.get("reason", "")
            msg = ev.get("message", "")
            ev_type = ev.get("type", "Normal")

            severity = "error" if ev_type == "Warning" else "info"

            timeline.append(
                TimelineEvent(
                    timestamp=ts,
                    kind=f"K8sEvent/{reason}",
                    source="k8s_events",
                    message=f"[{reason}] {msg}",
                    resource=resource,
                    severity=severity,
                )
            )

        # Process recent changes (deployments, rollouts, config changes)
        for change in recent_changes or []:
            ts = change.get("timestamp", change.get("time", ""))
            if not ts:
                continue

            change_type = change.get("type", "Change")
            msg = change.get("message", change.get("description", ""))

            timeline.append(
                TimelineEvent(
                    timestamp=ts,
                    kind=f"Change/{change_type}",
                    source="change_log",
                    message=msg,
                    resource=change.get("resource", ""),
                    severity="warning",
                )
            )

        # Process log lines (extract timestamp prefix)
        for line in log_entries or []:
            ts = self._extract_log_timestamp(line)
            if not ts:
                continue

            severity = (
                "error" if any(w in line.upper() for w in ("ERROR", "FATAL", "PANIC")) else "info"
            )

            timeline.append(
                TimelineEvent(
                    timestamp=ts,
                    kind="LogEntry",
                    source="pod_logs",
                    message=line.strip(),
                    resource=pod_name,
                    severity=severity,
                )
            )

        timeline.sort()
        logger.debug("Built timeline with %d events", len(timeline))
        return timeline

    def _extract_log_timestamp(self, line: str) -> Optional[str]:
        """Attempt to extract an ISO-8601 timestamp from the start of a log line."""
        if not line:
            return None
        parts = line.strip().split(" ", 1)
        if parts:
            candidate = parts[0].rstrip(",")
            # Try basic ISO format check
            if len(candidate) >= 10 and candidate[4] == "-" and candidate[7] == "-":
                return candidate
        return None

    def format_timeline(self, timeline: List[TimelineEvent], max_entries: int = 20) -> str:
        """Format timeline as a human-readable string for LLM prompt injection.

        Args:
            timeline: Sorted list of TimelineEvent objects.
            max_entries: Maximum number of events to include.

        Returns:
            Formatted string representation of the timeline.
        """
        if not timeline:
            return "No timeline data available."

        lines = ["=== Incident Timeline (chronological) ==="]
        for ev in timeline[-max_entries:]:
            severity_marker = "⚠️" if ev.severity == "error" else "ℹ️"
            lines.append(f"{ev.timestamp} [{ev.source}] {severity_marker} {ev.message}")
        return "\n".join(lines)
