"""Detector for node pressure conditions (Memory, Disk, PID pressure)."""
from __future__ import annotations

import logging
from typing import Any, Dict, List

from detectors.base import BaseDetector, DetectionResult
from models.incident import Evidence

logger = logging.getLogger(__name__)


class NodePressureDetector(BaseDetector):
    """Detects nodes with MemoryPressure, DiskPressure, PIDPressure, or NotReady conditions."""

    name = "node_pressure_detector"
    description = "Detects node pressure conditions and NotReady nodes"

    def detect(self, cluster_state: Dict[str, Any]) -> List[DetectionResult]:
        """Check nodes for pressure conditions and NotReady state.

        Args:
            cluster_state: Full cluster state dict.

        Returns:
            List of DetectionResult objects for node pressure conditions.
        """
        results: List[DetectionResult] = []
        nodes = cluster_state.get("nodes", [])
        events = cluster_state.get("events", [])

        for node in nodes:
            node_name = node.get("name", "unknown")
            conditions = node.get("conditions", [])
            ready = node.get("ready", True)
            memory_pressure = node.get("memory_pressure", False)
            disk_pressure = node.get("disk_pressure", False)
            pid_pressure = node.get("pid_pressure", False)

            # Check for pressure conditions from node fields
            pressure_conditions = []
            if memory_pressure:
                pressure_conditions.append("MemoryPressure")
            if disk_pressure:
                pressure_conditions.append("DiskPressure")
            if pid_pressure:
                pressure_conditions.append("PIDPressure")

            # Also check conditions array if present
            for cond in conditions:
                cond_type = cond.get("type", "")
                cond_status = cond.get("status", "False")
                if cond_type in ("MemoryPressure", "DiskPressure", "PIDPressure") and cond_status == "True":
                    if cond_type not in pressure_conditions:
                        pressure_conditions.append(cond_type)
                if cond_type == "Ready" and cond_status != "True":
                    ready = False

            if not pressure_conditions and ready:
                continue

            # Gather relevant events for this node
            node_events = [
                e for e in events
                if e.get("involvedObject", {}).get("name") == node_name
                or e.get("name") == node_name
            ]

            evidence: List[Evidence] = []

            if pressure_conditions:
                evidence.append(
                    self._make_evidence(
                        source="detector",
                        content=f"Node '{node_name}' has active pressure conditions: {', '.join(pressure_conditions)}. "
                                "Pods may be evicted or fail to schedule on this node.",
                        relevance=1.0,
                    )
                )

            if not ready:
                # Find NotReady reason from conditions
                not_ready_reason = "Unknown"
                for cond in conditions:
                    if cond.get("type") == "Ready" and cond.get("status") != "True":
                        not_ready_reason = cond.get("reason", "Unknown")
                        break
                evidence.append(
                    self._make_evidence(
                        source="detector",
                        content=f"Node '{node_name}' is NotReady: reason={not_ready_reason}",
                        relevance=1.0,
                    )
                )

            for event in node_events[:3]:
                evidence.append(
                    self._make_evidence(
                        source="k8s_events",
                        content=f"Node event: reason={event.get('reason','?')}, message={event.get('message','?')}",
                        relevance=0.8,
                    )
                )

            # Determine severity
            if not ready:
                severity = "critical"
            elif "MemoryPressure" in pressure_conditions:
                severity = "high"
            else:
                severity = "medium"

            conditions_str = ", ".join(pressure_conditions) if pressure_conditions else ""
            not_ready_str = "NotReady" if not ready else ""
            issue_str = ", ".join(filter(None, [conditions_str, not_ready_str]))

            results.append(
                DetectionResult(
                    detected=True,
                    incident_type="NodePressure",
                    severity=severity,
                    reason=f"Node '{node_name}' has conditions: {issue_str}",
                    evidence=evidence,
                    affected_resource=f"node/{node_name}",
                    namespace="default",
                    workload=node_name,
                    raw_signals={
                        "node_name": node_name,
                        "pressure_conditions": pressure_conditions,
                        "ready": ready,
                    },
                )
            )
            logger.info(
                "NodePressure detected: node=%s conditions=%s ready=%s",
                node_name, pressure_conditions, ready,
            )

        return results
