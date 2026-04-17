"""Cluster context learning — tracks per-namespace and per-service failure patterns.

The ClusterContext builds up a picture of what *normally* fails in each part of
the cluster.  This context is injected into the RCA pipeline to:

  - Boost confidence when the current failure matches a recurring pattern
  - Prioritise the most likely root cause for a given namespace/workload
  - Surface actionable insights ("payment-api has had 8 OOMKills this month")
"""

from __future__ import annotations

import logging
from collections import Counter, defaultdict
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)

# Minimum occurrences before a pattern is considered "recurring"
_RECURRING_THRESHOLD = 3

# Confidence boost applied when current incident type matches a recurring pattern
_RECURRING_BOOST = 0.08


class ClusterContext:
    """Tracks failure frequency patterns per namespace and workload.

    Usage::

        ctx = ClusterContext()
        ctx.record("production", "payment-api", "OOMKilled")
        ctx.record("production", "payment-api", "OOMKilled")
        ctx.record("production", "payment-api", "OOMKilled")

        top = ctx.get_most_likely_causes("production", "payment-api")
        # → [("OOMKilled", 3, True)]   # (type, count, recurring)

        boost = ctx.confidence_boost("production", "payment-api", "OOMKilled")
        # → 0.08
    """

    def __init__(self) -> None:
        # namespace → Counter of incident_type
        self._ns_counts: Dict[str, Counter] = defaultdict(Counter)
        # (namespace, workload) → Counter of incident_type
        self._workload_counts: Dict[Tuple[str, str], Counter] = defaultdict(Counter)
        # (namespace, workload) → list of recent timestamps per type
        self._workload_timeline: Dict[Tuple[str, str], List[Dict[str, str]]] = defaultdict(list)

    # ------------------------------------------------------------------
    # Recording
    # ------------------------------------------------------------------

    def record(
        self,
        namespace: str,
        workload: str,
        incident_type: str,
        timestamp: Optional[str] = None,
    ) -> None:
        """Record a new failure occurrence.

        Args:
            namespace: Kubernetes namespace.
            workload: Workload / service name.
            incident_type: Detected incident type string.
            timestamp: ISO-8601 timestamp (defaults to now).
        """
        ts = timestamp or datetime.now(timezone.utc).isoformat()
        self._ns_counts[namespace][incident_type] += 1
        self._workload_counts[(namespace, workload)][incident_type] += 1
        self._workload_timeline[(namespace, workload)].append(
            {"type": incident_type, "at": ts}
        )
        # Keep timeline bounded (last 100 events per workload)
        if len(self._workload_timeline[(namespace, workload)]) > 100:
            self._workload_timeline[(namespace, workload)] = (
                self._workload_timeline[(namespace, workload)][-100:]
            )

    def record_from_incident(self, incident: Any) -> None:
        """Convenience wrapper: record from an Incident model object."""
        self.record(
            namespace=getattr(incident, "namespace", ""),
            workload=getattr(incident, "workload", ""),
            incident_type=getattr(incident, "incident_type", "Unknown"),
            timestamp=getattr(incident, "detected_at", None),
        )

    # ------------------------------------------------------------------
    # Queries
    # ------------------------------------------------------------------

    def get_namespace_context(self, namespace: str) -> Dict[str, Any]:
        """Return failure pattern summary for a namespace.

        Returns:
            Dict with total_incidents, top_types list, and recurring list.
        """
        counts = self._ns_counts.get(namespace, Counter())
        total = sum(counts.values())
        top = [
            {"type": t, "count": c, "recurring": c >= _RECURRING_THRESHOLD}
            for t, c in counts.most_common(10)
        ]
        return {
            "namespace": namespace,
            "total_incidents": total,
            "top_types": top,
            "recurring": [t for t, c in counts.items() if c >= _RECURRING_THRESHOLD],
        }

    def get_workload_context(self, namespace: str, workload: str) -> Dict[str, Any]:
        """Return failure history for a specific workload.

        Returns:
            Dict with total_incidents, top_types, recurring, and recent_timeline.
        """
        key = (namespace, workload)
        counts = self._workload_counts.get(key, Counter())
        total = sum(counts.values())
        top = [
            {"type": t, "count": c, "recurring": c >= _RECURRING_THRESHOLD}
            for t, c in counts.most_common(5)
        ]
        recent = self._workload_timeline.get(key, [])[-10:]

        return {
            "namespace": namespace,
            "workload": workload,
            "total_incidents": total,
            "top_types": top,
            "recurring": [t for t, c in counts.items() if c >= _RECURRING_THRESHOLD],
            "recent_timeline": recent,
        }

    def get_most_likely_causes(
        self, namespace: str, workload: str
    ) -> List[Tuple[str, int, bool]]:
        """Return incident types ranked by frequency for (namespace, workload).

        Returns:
            List of (incident_type, count, is_recurring) tuples, most frequent first.
        """
        key = (namespace, workload)
        counts = self._workload_counts.get(key, Counter())
        return [
            (t, c, c >= _RECURRING_THRESHOLD) for t, c in counts.most_common(5)
        ]

    def confidence_boost(
        self, namespace: str, workload: str, incident_type: str
    ) -> float:
        """Return a confidence boost if this incident type is a recurring pattern.

        Args:
            namespace: Kubernetes namespace.
            workload: Workload name.
            incident_type: Current incident type to check.

        Returns:
            Float confidence boost (0.0 if not recurring, _RECURRING_BOOST if it is).
        """
        key = (namespace, workload)
        count = self._workload_counts.get(key, Counter()).get(incident_type, 0)
        if count >= _RECURRING_THRESHOLD:
            logger.debug(
                "Recurring pattern boost: %s/%s type=%s (count=%d)",
                namespace,
                workload,
                incident_type,
                count,
            )
            return _RECURRING_BOOST
        return 0.0

    def format_for_llm(self, namespace: str, workload: str) -> str:
        """Format cluster context as a string for LLM prompt injection.

        Returns:
            Multi-line string summarising recent failure patterns.
        """
        ctx = self.get_workload_context(namespace, workload)
        if ctx["total_incidents"] == 0:
            return f"No prior incident history for {namespace}/{workload}."

        lines = [
            f"Cluster context for {namespace}/{workload} ({ctx['total_incidents']} total incidents):"
        ]
        for item in ctx["top_types"][:5]:
            marker = "🔁" if item["recurring"] else "  "
            lines.append(f"  {marker} {item['type']}: {item['count']}x")

        if ctx["recurring"]:
            lines.append(
                f"  Recurring patterns (≥{_RECURRING_THRESHOLD}x): "
                + ", ".join(ctx["recurring"])
            )

        return "\n".join(lines)

    def get_stats(self) -> Dict[str, Any]:
        """Return aggregate stats for all tracked namespaces and workloads."""
        ns_total = {ns: sum(c.values()) for ns, c in self._ns_counts.items()}
        top_ns = sorted(ns_total.items(), key=lambda kv: kv[1], reverse=True)[:5]
        total_workloads = len(self._workload_counts)
        recurring_workloads = sum(
            1
            for counts in self._workload_counts.values()
            if any(c >= _RECURRING_THRESHOLD for c in counts.values())
        )
        return {
            "tracked_namespaces": len(self._ns_counts),
            "tracked_workloads": total_workloads,
            "recurring_workloads": recurring_workloads,
            "top_namespaces_by_incidents": [{"ns": k, "count": v} for k, v in top_ns],
        }


# Module-level singleton for convenience
_default_context: Optional[ClusterContext] = None


def get_cluster_context() -> ClusterContext:
    """Return the module-level singleton ClusterContext."""
    global _default_context
    if _default_context is None:
        _default_context = ClusterContext()
    return _default_context
