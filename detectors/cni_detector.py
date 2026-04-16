"""Detector for CNI plugin failures and IP exhaustion."""

from __future__ import annotations

import logging
from typing import Any, Dict, List

from detectors.base import BaseDetector, DetectionResult
from models.incident import Evidence

logger = logging.getLogger(__name__)

CNI_EVENT_PATTERNS = [
    "NetworkPluginNotReady",
    "NetworkPlugin",
    "failed to allocate",
    "CIDR exhausted",
    "ip exhausted",
    "no available ip",
    "insufficient ips",
    "cni plugin",
    "failed to set up pod",
]

CNI_LOG_PATTERNS = [
    "networkpluginnotready",
    "failed to allocate ip",
    "cidr exhausted",
    "ip exhausted",
    "no available ip",
    "cni plugin not initialized",
    "failed to set up pod network",
]


class CNIDetector(BaseDetector):
    """Detects CNI plugin failures and IP address exhaustion on nodes."""

    name = "cni_detector"
    description = "Detects CNI plugin failures, IP exhaustion, and CIDR exhaustion"

    def detect(self, cluster_state: Dict[str, Any]) -> List[DetectionResult]:
        """Check node events for CNI failures and IP exhaustion.

        Args:
            cluster_state: Full cluster state dict.

        Returns:
            List of DetectionResult objects for CNI issues.
        """
        results: List[DetectionResult] = []
        events = cluster_state.get("events", [])
        cluster_state.get("nodes", [])
        recent_logs = cluster_state.get("recent_logs", {})

        seen: Dict[str, bool] = {}

        # Check events for CNI-related failures
        for event in events:
            message = event.get("message", "")
            message_lower = message.lower()
            reason = event.get("reason", "")
            involved = event.get("involvedObject", {})
            node_name = involved.get("name", event.get("name", "unknown"))
            namespace = event.get("namespace", "default")

            is_cni = "networkpluginnotready" in reason.lower() or any(
                p.lower() in message_lower for p in CNI_EVENT_PATTERNS
            )
            if not is_cni:
                continue

            key = f"node:{node_name}"
            if seen.get(key):
                continue
            seen[key] = True

            severity = (
                "critical"
                if "exhausted" in message_lower or "no available ip" in message_lower
                else "high"
            )

            evidence: List[Evidence] = [
                self._make_evidence(
                    source="k8s_events",
                    content=f"CNI event on node '{node_name}': reason={reason}, message={message}",
                    relevance=1.0,
                ),
                self._make_evidence(
                    source="detector",
                    content=f"CNI/IP issue detected on node '{node_name}'. Pods scheduled on this node may fail to start.",
                    relevance=0.9,
                ),
            ]

            results.append(
                DetectionResult(
                    detected=True,
                    incident_type="CNIFailure",
                    severity=severity,
                    reason=f"CNI failure on node '{node_name}': {reason}",
                    evidence=evidence,
                    affected_resource=f"node/{node_name}",
                    namespace=namespace,
                    workload=node_name,
                    raw_signals={
                        "node_name": node_name,
                        "cni_reason": reason,
                        "message": message,
                    },
                )
            )
            logger.info("CNIFailure detected: node=%s reason=%s", node_name, reason)

        # Check logs for CNI patterns
        for log_key, log_lines in recent_logs.items():
            matched = []
            for line in log_lines:
                if any(p in line.lower() for p in CNI_LOG_PATTERNS):
                    matched.append(line)
            if not matched:
                continue

            parts = log_key.split("/")
            namespace = parts[0] if len(parts) > 0 else "kube-system"
            pod_name = parts[1] if len(parts) > 1 else ""

            key = f"log:{log_key}"
            if seen.get(key):
                continue
            seen[key] = True

            evidence = [
                self._make_evidence(
                    source="pod_logs",
                    content=f"CNI error in logs {log_key}:\n" + "\n".join(matched[:5]),
                    relevance=0.9,
                )
            ]
            results.append(
                DetectionResult(
                    detected=True,
                    incident_type="CNIFailure",
                    severity="high",
                    reason=f"CNI errors in pod logs: {log_key}",
                    evidence=evidence,
                    affected_resource=f"{namespace}/{pod_name}",
                    namespace=namespace,
                    workload=pod_name.rsplit("-", 2)[0] if "-" in pod_name else pod_name,
                    pod_name=pod_name,
                    raw_signals={"cni_log_lines": matched[:10]},
                )
            )
            logger.info("CNI log errors detected: %s", log_key)

        return results
