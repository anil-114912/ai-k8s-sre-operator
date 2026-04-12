"""Detector for RBAC authorization denials in Kubernetes."""
from __future__ import annotations

import logging
import re
from typing import Any, Dict, List

from detectors.base import BaseDetector, DetectionResult
from models.incident import Evidence

logger = logging.getLogger(__name__)

RBAC_EVENT_REASONS = {"Forbidden", "FailedCreate"}
RBAC_LOG_PATTERNS = [
    "forbidden",
    "is not allowed",
    "rbac",
    "cannot get",
    "cannot list",
    "cannot create",
    "cannot delete",
    "cannot update",
    "cannot watch",
    "cannot patch",
    "user does not have",
    "permissiondenied",
    "403",
]


class RBACDetector(BaseDetector):
    """Detects RBAC authorization denial events and log entries."""

    name = "rbac_detector"
    description = "Detects RBAC forbidden events and authorization failures"

    def detect(self, cluster_state: Dict[str, Any]) -> List[DetectionResult]:
        """Check events and logs for RBAC denial patterns.

        Args:
            cluster_state: Full cluster state dict.

        Returns:
            List of DetectionResult objects for RBAC denials.
        """
        results: List[DetectionResult] = []
        events = cluster_state.get("events", [])
        recent_logs = cluster_state.get("recent_logs", {})

        seen_namespaces: Dict[str, bool] = {}

        # Check events for Forbidden reason
        for event in events:
            reason = event.get("reason", "")
            message = event.get("message", "").lower()
            namespace = event.get("namespace", "default")

            if reason not in RBAC_EVENT_REASONS:
                continue
            if not any(kw in message for kw in ("forbidden", "rbac", "not allowed", "cannot")):
                continue

            if seen_namespaces.get(namespace):
                continue
            seen_namespaces[namespace] = True

            # Extract service account
            sa_match = re.search(r'serviceaccount[s]?[:/]\s*"?([^\s"]+)"?', message, re.IGNORECASE)
            service_account = sa_match.group(1) if sa_match else "unknown"

            # Extract denied verb/resource
            verb_match = re.search(r'cannot\s+(\w+)\s+resource\s+"?([^\s"]+)"?', message, re.IGNORECASE)
            denied_verb = verb_match.group(1) if verb_match else "unknown"
            denied_resource = verb_match.group(2) if verb_match else "unknown"

            involved = event.get("involvedObject", {})
            workload = involved.get("name", "")

            evidence: List[Evidence] = [
                self._make_evidence(
                    source="k8s_events",
                    content=f"RBAC denial event in '{namespace}': {event.get('message', '')}",
                    relevance=1.0,
                ),
                self._make_evidence(
                    source="detector",
                    content=f"ServiceAccount: {service_account} | Denied verb: {denied_verb} | Resource: {denied_resource}",
                    relevance=0.9,
                ),
            ]

            results.append(
                DetectionResult(
                    detected=True,
                    incident_type="RBACDenied",
                    severity="high",
                    reason=f"RBAC denial in namespace '{namespace}': ServiceAccount={service_account} cannot {denied_verb} {denied_resource}",
                    evidence=evidence,
                    affected_resource=f"{namespace}/{workload}",
                    namespace=namespace,
                    workload=workload,
                    raw_signals={
                        "service_account": service_account,
                        "denied_verb": denied_verb,
                        "denied_resource": denied_resource,
                    },
                )
            )
            logger.info(
                "RBACDenied detected: namespace=%s sa=%s verb=%s resource=%s",
                namespace, service_account, denied_verb, denied_resource,
            )

        # Check logs for RBAC patterns
        for log_key, log_lines in recent_logs.items():
            matched_lines = []
            for line in log_lines:
                line_lower = line.lower()
                if any(pattern in line_lower for pattern in RBAC_LOG_PATTERNS):
                    matched_lines.append(line)
            if not matched_lines:
                continue

            parts = log_key.split("/")
            namespace = parts[0] if len(parts) > 0 else "default"
            pod_name = parts[1] if len(parts) > 1 else ""
            container_name = parts[2] if len(parts) > 2 else ""
            workload = pod_name.rsplit("-", 2)[0] if "-" in pod_name else pod_name

            if seen_namespaces.get(f"log:{namespace}/{pod_name}"):
                continue
            seen_namespaces[f"log:{namespace}/{pod_name}"] = True

            evidence = [
                self._make_evidence(
                    source="pod_logs",
                    content=f"RBAC error in logs {log_key}:\n" + "\n".join(matched_lines[:5]),
                    relevance=0.9,
                ),
            ]

            results.append(
                DetectionResult(
                    detected=True,
                    incident_type="RBACDenied",
                    severity="medium",
                    reason=f"RBAC authorization errors in pod logs: {log_key}",
                    evidence=evidence,
                    affected_resource=f"{namespace}/{pod_name}",
                    namespace=namespace,
                    workload=workload,
                    pod_name=pod_name,
                    container_name=container_name,
                    raw_signals={"rbac_log_lines": matched_lines[:10]},
                )
            )
            logger.info("RBAC log errors detected: %s", log_key)

        return results
