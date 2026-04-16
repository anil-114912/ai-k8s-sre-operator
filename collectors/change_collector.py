"""Recent rollout/deployment change collector."""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


class ChangeCollector:
    """Collects recent deployment and configuration change events from cluster state."""

    def get_recent_changes(
        self,
        cluster_state: Dict[str, Any],
        namespace: Optional[str] = None,
        hours: int = 24,
    ) -> List[Dict[str, Any]]:
        """Extract recent change events from deployments and events.

        Args:
            cluster_state: Full cluster state dict.
            namespace: Optional namespace filter.
            hours: Look back window in hours.

        Returns:
            List of change record dicts with type, message, timestamp fields.
        """
        changes = []
        cutoff = datetime.now(timezone.utc) - timedelta(hours=hours)

        # Extract deployment rollout events
        events = cluster_state.get("events", [])
        for ev in events:
            reason = ev.get("reason", "")
            if reason not in ("ScalingReplicaSet", "Killing", "Created", "Started"):
                continue
            if namespace and ev.get("namespace") != namespace:
                continue
            ts = ev.get("lastTimestamp") or ev.get("firstTimestamp")
            if ts:
                try:
                    ev_time = datetime.fromisoformat(ts.replace("Z", "+00:00"))
                    if ev_time < cutoff:
                        continue
                except ValueError:
                    pass

            changes.append(
                {
                    "type": "K8sEvent",
                    "message": ev.get("message", ""),
                    "timestamp": ts or "",
                    "resource": ev.get("involvedObject", {}).get("name", ""),
                    "namespace": ev.get("namespace", ""),
                }
            )

        # Include any annotated recent changes from raw_signals
        # This allows incident JSON examples to inject change timeline
        logger.debug(
            "ChangeCollector: found %d recent changes (namespace=%s, hours=%d)",
            len(changes),
            namespace,
            hours,
        )
        return changes
