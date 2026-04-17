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

    def format_relative_timeline(
        self,
        timeline: List[TimelineEvent],
        reference_ts: Optional[str] = None,
        max_entries: int = 20,
    ) -> str:
        """Format timeline with relative times (T-5m, T-4m format) for readability.

        Uses the last event as T=0 (the incident detection point) unless a
        reference_ts is provided.

        Args:
            timeline: Sorted list of TimelineEvent objects.
            reference_ts: ISO-8601 reference timestamp (T=0). Defaults to last event.
            max_entries: Maximum number of events to include.

        Returns:
            Formatted string like:
              T-5m: deployment updated
              T-4m: pod restarted (restart_count=1)
              T-3m: readiness probe failing
              T-0:  incident detected
        """
        if not timeline:
            return "No timeline data available."

        entries = timeline[-max_entries:]
        ref_ts = reference_ts or (entries[-1].timestamp if entries else None)
        ref_dt = self._parse_iso(ref_ts)

        lines = ["=== Incident Timeline (relative) ==="]
        for ev in entries:
            ev_dt = self._parse_iso(ev.timestamp)
            rel_label = self._relative_label(ev_dt, ref_dt)
            severity_marker = "⚠️" if ev.severity == "error" else "ℹ️"
            resource_part = f" [{ev.resource}]" if ev.resource else ""
            lines.append(f"{rel_label}{resource_part}: {severity_marker} {ev.message}")

        return "\n".join(lines)

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _parse_iso(ts: Optional[str]):
        """Parse an ISO-8601 timestamp string into a datetime, or return None."""
        if not ts:
            return None
        try:
            from datetime import datetime

            # Handle both with and without timezone
            ts_clean = ts.rstrip("Z")
            if "T" in ts_clean:
                return datetime.fromisoformat(ts_clean)
            return None
        except Exception:
            return None

    @staticmethod
    def _relative_label(ev_dt, ref_dt) -> str:
        """Produce a T-Xm label relative to ref_dt.

        Returns 'T-Xm', 'T-Xs', or 'T-0' if the two datetimes are within 5s.
        Falls back to the raw timestamp string if parsing failed.
        """
        if ev_dt is None or ref_dt is None:
            return "T-??"
        diff_secs = (ref_dt - ev_dt).total_seconds()
        if abs(diff_secs) < 5:
            return "T-0 "
        if diff_secs < 0:
            # Event is after the reference — shouldn't normally happen
            return f"T+{int(abs(diff_secs) // 60)}m"
        mins = int(diff_secs // 60)
        secs = int(diff_secs % 60)
        if mins >= 1:
            return f"T-{mins}m "
        return f"T-{secs}s "
