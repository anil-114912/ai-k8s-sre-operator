"""Kubernetes events aggregator — filters and enriches K8s event streams."""
from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

WARNING_REASONS = {
    "BackOff", "Failed", "FailedScheduling", "FailedMount", "Unhealthy",
    "OOMKilling", "ImagePullBackOff", "ErrImagePull", "NodeNotReady",
    "Evicted", "FailedCreate", "FailedBinding",
}


class EventsCollector:
    """Collects and filters Kubernetes warning events from cluster state."""

    def __init__(self) -> None:
        """Initialise the events collector."""
        logger.info("EventsCollector initialised")

    def collect_warning_events(
        self,
        cluster_state: Dict[str, Any],
        namespace: Optional[str] = None,
        resource_name: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """Extract Warning-type events, optionally filtered by namespace/resource.

        Args:
            cluster_state: Full cluster state dict.
            namespace: Optional namespace filter.
            resource_name: Optional resource name filter.

        Returns:
            Filtered list of warning event dicts.
        """
        events = cluster_state.get("events", [])
        result = []
        for ev in events:
            if ev.get("type") != "Warning":
                continue
            if namespace and ev.get("namespace") != namespace:
                continue
            if resource_name:
                involved = ev.get("involvedObject", {})
                if involved.get("name") != resource_name:
                    continue
            result.append(ev)
        logger.debug(
            "EventsCollector: %d warning events (namespace=%s, resource=%s)",
            len(result),
            namespace,
            resource_name,
        )
        return result

    def events_for_pod(
        self,
        cluster_state: Dict[str, Any],
        pod_name: str,
        namespace: str = "",
    ) -> List[Dict[str, Any]]:
        """Get all events for a specific pod.

        Args:
            cluster_state: Full cluster state dict.
            pod_name: Pod name.
            namespace: Optional namespace for tighter filtering.

        Returns:
            List of events related to the pod.
        """
        events = cluster_state.get("events", [])
        result = []
        for ev in events:
            involved = ev.get("involvedObject", {})
            if involved.get("name") == pod_name and involved.get("kind") == "Pod":
                if not namespace or ev.get("namespace") == namespace:
                    result.append(ev)
        return result

    def summarise_events(self, events: List[Dict[str, Any]]) -> str:
        """Produce a human-readable summary of a list of events.

        Args:
            events: List of event dicts.

        Returns:
            Formatted summary string.
        """
        if not events:
            return "No events."
        lines = []
        for ev in events[:10]:  # Show at most 10 events
            resource = ev.get("involvedObject", {}).get("name", "?")
            reason = ev.get("reason", "?")
            msg = ev.get("message", "")[:120]
            count = ev.get("count", 1)
            lines.append(f"  [{reason}] ({count}x) {resource}: {msg}")
        return "\n".join(lines)
