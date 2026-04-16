"""Detector for ResourceQuota exceeded events."""

from __future__ import annotations

import logging
import re
from typing import Any, Dict, List

from detectors.base import BaseDetector, DetectionResult
from models.incident import Evidence

logger = logging.getLogger(__name__)


class QuotaDetector(BaseDetector):
    """Detects ResourceQuota exceeded events in Kubernetes namespaces."""

    name = "quota_detector"
    description = "Detects ResourceQuota exceeded events causing pod creation failures"

    def detect(self, cluster_state: Dict[str, Any]) -> List[DetectionResult]:
        """Check events for FailedCreate reason with quota exceeded messages.

        Args:
            cluster_state: Full cluster state dict.

        Returns:
            List of DetectionResult objects for quota violations.
        """
        results: List[DetectionResult] = []
        events = cluster_state.get("events", [])

        seen: Dict[str, bool] = {}

        for event in events:
            reason = event.get("reason", "")
            message = event.get("message", "")
            namespace = event.get("namespace", "default")

            if reason != "FailedCreate":
                continue

            msg_lower = message.lower()
            if "exceeded quota" not in msg_lower and "quota" not in msg_lower:
                continue

            # Deduplicate by namespace
            if seen.get(namespace):
                continue
            seen[namespace] = True

            # Extract quota name and resource type
            quota_name = "unknown"
            resource_type = "unknown"

            quota_match = re.search(r'quota\s+"?([^\s,"]+)"?', message, re.IGNORECASE)
            if quota_match:
                quota_name = quota_match.group(1)

            for res in (
                "cpu",
                "memory",
                "pods",
                "services",
                "persistentvolumeclaims",
                "requests.cpu",
                "requests.memory",
                "limits.cpu",
                "limits.memory",
            ):
                if res in msg_lower:
                    resource_type = res
                    break

            evidence: List[Evidence] = [
                self._make_evidence(
                    source="k8s_events",
                    content=f"FailedCreate event in namespace '{namespace}': {message}",
                    relevance=1.0,
                ),
                self._make_evidence(
                    source="detector",
                    content=f"ResourceQuota '{quota_name}' exceeded for resource '{resource_type}' in namespace '{namespace}'",
                    relevance=0.9,
                ),
            ]

            results.append(
                DetectionResult(
                    detected=True,
                    incident_type="QuotaExceeded",
                    severity="high",
                    reason=f"ResourceQuota exceeded in namespace '{namespace}': resource={resource_type}",
                    evidence=evidence,
                    affected_resource=f"{namespace}/{quota_name}",
                    namespace=namespace,
                    workload=event.get("involvedObject", {}).get("name", ""),
                    raw_signals={
                        "quota_name": quota_name,
                        "resource_type": resource_type,
                        "message": message,
                    },
                )
            )
            logger.info(
                "QuotaExceeded detected: namespace=%s quota=%s resource=%s",
                namespace,
                quota_name,
                resource_type,
            )

        return results
