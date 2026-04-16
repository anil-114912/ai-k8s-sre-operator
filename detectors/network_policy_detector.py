"""Detector for NetworkPolicy blocks causing connectivity failures."""

from __future__ import annotations

import logging
from typing import Any, Dict, List

from detectors.base import BaseDetector, DetectionResult
from models.incident import Evidence

logger = logging.getLogger(__name__)

NETWORK_BLOCK_LOG_PATTERNS = [
    "connection timed out",
    "connection refused",
    "no route to host",
    "network is unreachable",
    "dial tcp",
    "connect: connection refused",
    "i/o timeout",
    "upstream connect error",
    "tcp dial",
]


class NetworkPolicyDetector(BaseDetector):
    """Detects NetworkPolicy blocks causing pod-to-pod connectivity failures."""

    name = "network_policy_detector"
    description = "Detects NetworkPolicy blocks and pod connectivity failures"

    def detect(self, cluster_state: Dict[str, Any]) -> List[DetectionResult]:
        """Check logs for connection failures and NetworkPolicy objects for overly restrictive rules.

        Args:
            cluster_state: Full cluster state dict.

        Returns:
            List of DetectionResult objects for network policy blocks.
        """
        results: List[DetectionResult] = []
        recent_logs = cluster_state.get("recent_logs", {})
        network_policies = cluster_state.get("network_policies", [])
        cluster_state.get("pods", [])

        # Check pod logs for connection timeout patterns
        for log_key, log_lines in recent_logs.items():
            matched_lines = []
            for line in log_lines:
                line_lower = line.lower()
                if any(pattern in line_lower for pattern in NETWORK_BLOCK_LOG_PATTERNS):
                    matched_lines.append(line)
            if not matched_lines:
                continue

            parts = log_key.split("/")
            namespace = parts[0] if len(parts) > 0 else "default"
            pod_name = parts[1] if len(parts) > 1 else ""
            container_name = parts[2] if len(parts) > 2 else ""
            workload = pod_name.rsplit("-", 2)[0] if "-" in pod_name else pod_name

            # Check if there are NetworkPolicies in this namespace
            ns_policies = [np for np in network_policies if np.get("namespace") == namespace]
            has_policies = len(ns_policies) > 0

            severity = "high" if has_policies else "medium"

            evidence: List[Evidence] = [
                self._make_evidence(
                    source="pod_logs",
                    content=f"Network connection failures in {log_key}:\n"
                    + "\n".join(matched_lines[:5]),
                    relevance=1.0,
                ),
            ]

            if has_policies:
                policy_names = [np.get("name", "unknown") for np in ns_policies]
                evidence.append(
                    self._make_evidence(
                        source="detector",
                        content=f"NetworkPolicy objects present in namespace '{namespace}': {', '.join(policy_names)}. "
                        "A policy may be blocking traffic to/from this pod.",
                        relevance=0.9,
                    )
                )

            results.append(
                DetectionResult(
                    detected=True,
                    incident_type="NetworkPolicyBlock",
                    severity=severity,
                    reason=f"Network connectivity failures in {log_key}"
                    + (" (NetworkPolicies present)" if has_policies else ""),
                    evidence=evidence,
                    affected_resource=f"{namespace}/{pod_name}",
                    namespace=namespace,
                    workload=workload,
                    pod_name=pod_name,
                    container_name=container_name,
                    raw_signals={
                        "connection_error_lines": matched_lines[:10],
                        "has_network_policies": has_policies,
                        "policy_count": len(ns_policies),
                    },
                )
            )
            logger.info("NetworkPolicyBlock detected: %s has_policies=%s", log_key, has_policies)

        return results
