"""Detector for CSI/storage failures including mount failures and driver issues."""
from __future__ import annotations

import logging
from typing import Any, Dict, List

from detectors.base import BaseDetector, DetectionResult
from models.incident import Evidence

logger = logging.getLogger(__name__)

STORAGE_EVENT_REASONS = {
    "FailedMount",
    "FailedAttachVolume",
    "FailedDetachVolume",
    "VolumeNotFound",
    "FailedMapVolume",
    "WarningFSResizeFailed",
}

CSI_LOG_PATTERNS = [
    "csi driver",
    "failed to mount",
    "failed to attach",
    "volume not found",
    "no such file or directory",
    "mount failed",
    "attach failed",
    "storageclass",
    "provisioner",
    "failed to provision",
]


class StorageDetector(BaseDetector):
    """Detects CSI/storage issues including mount failures and missing storage classes."""

    name = "storage_detector"
    description = "Detects CSI driver failures, FailedMount events, StorageClass issues"

    def detect(self, cluster_state: Dict[str, Any]) -> List[DetectionResult]:
        """Check events and state for storage failures.

        Args:
            cluster_state: Full cluster state dict.

        Returns:
            List of DetectionResult objects for storage failures.
        """
        results: List[DetectionResult] = []
        events = cluster_state.get("events", [])
        pvcs = cluster_state.get("pvcs", [])
        storage_classes = cluster_state.get("storage_classes", [])
        pods = cluster_state.get("pods", [])

        seen: Dict[str, bool] = {}

        # Check events for storage failure reasons
        for event in events:
            reason = event.get("reason", "")
            if reason not in STORAGE_EVENT_REASONS:
                continue

            message = event.get("message", "")
            message_lower = message.lower()
            namespace = event.get("namespace", "default")
            involved = event.get("involvedObject", {})
            pod_name = involved.get("name", "")
            workload = pod_name.rsplit("-", 2)[0] if "-" in pod_name else pod_name

            key = f"{namespace}/{pod_name}/{reason}"
            if seen.get(key):
                continue
            seen[key] = True

            # Classify storage issue type
            if "not found" in message_lower or "volume not found" in message_lower:
                issue_type = "pv_not_found"
            elif "storageclass" in message_lower and ("not found" in message_lower or "missing" in message_lower):
                issue_type = "storageclass_missing"
            elif "csi" in message_lower:
                issue_type = "csi_driver_error"
            else:
                issue_type = "mount_failure"

            severity = "high" if reason in ("FailedAttachVolume", "VolumeNotFound") else "medium"

            evidence: List[Evidence] = [
                self._make_evidence(
                    source="k8s_events",
                    content=f"Storage event '{reason}' for pod '{pod_name}' in '{namespace}': {message}",
                    relevance=1.0,
                ),
                self._make_evidence(
                    source="detector",
                    content=f"Storage issue type: {issue_type}. Pod '{workload}' cannot mount required volumes.",
                    relevance=0.9,
                ),
            ]

            results.append(
                DetectionResult(
                    detected=True,
                    incident_type="StorageFailure",
                    severity=severity,
                    reason=f"Storage {reason} for '{namespace}/{workload}': {issue_type}",
                    evidence=evidence,
                    affected_resource=f"{namespace}/{pod_name}",
                    namespace=namespace,
                    workload=workload,
                    pod_name=pod_name,
                    raw_signals={
                        "event_reason": reason,
                        "issue_type": issue_type,
                        "message": message,
                    },
                )
            )
            logger.info("StorageFailure detected: %s/%s reason=%s", namespace, pod_name, reason)

        # Check for PVCs stuck in Pending state (complement to PVCDetector — looks at CSI specifically)
        sc_names = {sc.get("name") for sc in storage_classes}
        for pvc in pvcs:
            if pvc.get("phase") != "Pending":
                continue

            pvc_name = pvc.get("name", "")
            namespace = pvc.get("namespace", "default")
            storage_class = pvc.get("storageClassName", "")

            key = f"pvc:{namespace}/{pvc_name}"
            if seen.get(key):
                continue
            seen[key] = True

            # Check if StorageClass is missing
            if storage_class and sc_names and storage_class not in sc_names:
                evidence = [
                    self._make_evidence(
                        source="detector",
                        content=f"PVC '{pvc_name}' references StorageClass '{storage_class}' which does not exist in the cluster.",
                        relevance=1.0,
                    ),
                ]
                results.append(
                    DetectionResult(
                        detected=True,
                        incident_type="StorageFailure",
                        severity="high",
                        reason=f"PVC '{pvc_name}' references missing StorageClass '{storage_class}'",
                        evidence=evidence,
                        affected_resource=f"{namespace}/{pvc_name}",
                        namespace=namespace,
                        workload=pvc_name,
                        raw_signals={
                            "issue_type": "storageclass_missing",
                            "storage_class": storage_class,
                            "pvc_name": pvc_name,
                        },
                    )
                )
                logger.info("Missing StorageClass detected: pvc=%s sc=%s", pvc_name, storage_class)

        return results
