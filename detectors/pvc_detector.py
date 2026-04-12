"""Detector for PersistentVolumeClaim binding failures."""
from __future__ import annotations

import logging
from typing import Any, Dict, List

from detectors.base import BaseDetector, DetectionResult
from models.incident import Evidence

logger = logging.getLogger(__name__)


class PVCDetector(BaseDetector):
    """Detects PVCs stuck in Pending state or causing FailedMount errors."""

    name = "pvc_detector"
    description = "Detects unbound PVCs and pod volume mount failures"

    def detect(self, cluster_state: Dict[str, Any]) -> List[DetectionResult]:
        """Find pending PVCs and pods reporting FailedMount events.

        Args:
            cluster_state: Full cluster state dict.

        Returns:
            List of DetectionResult for PVC-related failures.
        """
        results: List[DetectionResult] = []
        pvcs = cluster_state.get("pvcs", [])
        events = cluster_state.get("events", [])

        # Detect unbound PVCs
        for pvc in pvcs:
            pvc_name = pvc.get("name", "")
            namespace = pvc.get("namespace", "default")
            phase = pvc.get("phase", "")

            if phase == "Bound":
                continue

            if phase in ("Pending", "Lost"):
                evidence: List[Evidence] = []
                evidence.append(
                    self._make_evidence(
                        source="detector",
                        content=f"PVC '{pvc_name}' is in '{phase}' state (not Bound)",
                        relevance=1.0,
                    )
                )

                # Storage class and request info
                storage_class = pvc.get("storageClassName", "default")
                requested = pvc.get("resources", {}).get("requests", {}).get("storage", "unknown")
                access_modes = pvc.get("accessModes", [])
                evidence.append(
                    self._make_evidence(
                        source="manifest",
                        content=(
                            f"PVC spec: storageClass={storage_class}, "
                            f"request={requested}, accessModes={access_modes}"
                        ),
                        relevance=0.85,
                    )
                )

                # Related events
                for ev in events:
                    involved = ev.get("involvedObject", {})
                    if involved.get("name") == pvc_name and involved.get("kind") == "PersistentVolumeClaim":
                        evidence.append(
                            self._make_evidence(
                                source="k8s_events",
                                content=f"PVC event [{ev.get('reason')}]: {ev.get('message', '')}",
                                relevance=0.9,
                            )
                        )

                results.append(
                    DetectionResult(
                        detected=True,
                        incident_type="PVCFailure",
                        severity="high" if phase == "Pending" else "critical",
                        reason=f"PVC '{pvc_name}' is {phase} — storage not provisioned",
                        evidence=evidence,
                        affected_resource=f"{namespace}/{pvc_name}",
                        namespace=namespace,
                        workload=pvc_name,
                        raw_signals={
                            "phase": phase,
                            "storageClass": storage_class,
                            "requested": requested,
                        },
                    )
                )
                logger.info("PVC failure detected: pvc=%s/%s phase=%s", namespace, pvc_name, phase)

        # Detect FailedMount events for pods
        seen_pods: set = set()
        for ev in events:
            if ev.get("reason") != "FailedMount":
                continue

            involved = ev.get("involvedObject", {})
            if involved.get("kind") != "Pod":
                continue

            pod_name = involved.get("name", "")
            namespace = ev.get("namespace", involved.get("namespace", "default"))
            key = f"{namespace}/{pod_name}"
            if key in seen_pods:
                continue
            seen_pods.add(key)

            msg = ev.get("message", "")
            evidence = [
                self._make_evidence(
                    source="k8s_events",
                    content=f"FailedMount for pod '{pod_name}': {msg}",
                    relevance=1.0,
                )
            ]

            results.append(
                DetectionResult(
                    detected=True,
                    incident_type="PVCFailure",
                    severity="high",
                    reason=f"Pod '{pod_name}' cannot mount volume — {msg[:80]}",
                    evidence=evidence,
                    affected_resource=f"{namespace}/{pod_name}",
                    namespace=namespace,
                    workload=pod_name.rsplit("-", 2)[0] if "-" in pod_name else pod_name,
                    pod_name=pod_name,
                    raw_signals={"message": msg, "event_reason": "FailedMount"},
                )
            )
            logger.info("FailedMount detected: pod=%s/%s", namespace, pod_name)

        return results
