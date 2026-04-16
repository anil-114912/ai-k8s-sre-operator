"""Detector for pods stuck in Pending state."""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any, Dict, List

from detectors.base import BaseDetector, DetectionResult
from models.incident import Evidence

logger = logging.getLogger(__name__)

PENDING_THRESHOLD_SECONDS = 120  # 2 minutes


class PendingPodsDetector(BaseDetector):
    """Detects pods that have been in Pending state longer than the threshold."""

    name = "pending_pods_detector"
    description = "Detects pods stuck in Pending state due to scheduling failures"

    def detect(self, cluster_state: Dict[str, Any]) -> List[DetectionResult]:
        """Find pods pending beyond the threshold and diagnose scheduling reason.

        Args:
            cluster_state: Full cluster state dict.

        Returns:
            List of DetectionResult for stuck pending pods.
        """
        results: List[DetectionResult] = []
        pods = cluster_state.get("pods", [])
        events = cluster_state.get("events", [])
        nodes = cluster_state.get("nodes", [])

        now = datetime.now(timezone.utc)

        for pod in pods:
            if pod.get("phase") != "Pending":
                continue

            pod_name = pod.get("name", "")
            namespace = pod.get("namespace", "default")
            workload = pod.get(
                "workload", pod_name.rsplit("-", 2)[0] if "-" in pod_name else pod_name
            )

            # Check pending duration
            creation_ts = pod.get("creationTimestamp", "")
            pending_secs = PENDING_THRESHOLD_SECONDS + 1  # default: assume over threshold
            if creation_ts:
                try:
                    ts = datetime.fromisoformat(creation_ts.replace("Z", "+00:00"))
                    pending_secs = (now - ts).total_seconds()
                except ValueError:
                    pass

            if pending_secs < PENDING_THRESHOLD_SECONDS:
                continue

            evidence: List[Evidence] = []
            pending_minutes = int(pending_secs // 60)

            evidence.append(
                self._make_evidence(
                    source="detector",
                    content=f"Pod '{pod_name}' has been Pending for {pending_minutes} minutes",
                    relevance=1.0,
                )
            )

            # Analyse events for scheduling failure reasons
            scheduling_reasons = []
            for ev in events:
                involved = ev.get("involvedObject", {})
                if involved.get("name") == pod_name and ev.get("reason") == "FailedScheduling":
                    msg = ev.get("message", "")
                    scheduling_reasons.append(msg)
                    evidence.append(
                        self._make_evidence(
                            source="k8s_events",
                            content=f"FailedScheduling: {msg}",
                            relevance=1.0,
                        )
                    )

            # Check node capacity
            insufficient_resources = any(
                "Insufficient" in r or "insufficient" in r for r in scheduling_reasons
            )
            node_selector_mismatch = any(
                "node selector" in r.lower() or "nodeselector" in r.lower()
                for r in scheduling_reasons
            )
            taint_toleration = any(
                "taint" in r.lower() or "toleration" in r.lower() for r in scheduling_reasons
            )
            pvc_not_bound = any(
                "pvc" in r.lower() or "persistentvolumeclaim" in r.lower()
                for r in scheduling_reasons
            )

            # Determine sub-reason
            if insufficient_resources:
                sub_reason = "Insufficient CPU or memory on available nodes"
            elif node_selector_mismatch:
                sub_reason = "No node matches pod nodeSelector or affinity rules"
            elif taint_toleration:
                sub_reason = "Pod tolerations do not match node taints"
            elif pvc_not_bound:
                sub_reason = "Required PersistentVolumeClaim is not bound"
            else:
                sub_reason = "Scheduling failure — unknown reason"

            # Node resource context
            node_info = []
            for node in nodes:
                allocatable = node.get("allocatable", {})
                node_info.append(
                    f"{node.get('name', '?')}: cpu={allocatable.get('cpu', '?')} mem={allocatable.get('memory', '?')}"
                )
            if node_info:
                evidence.append(
                    self._make_evidence(
                        source="detector",
                        content="Available node resources:\n" + "\n".join(node_info),
                        relevance=0.7,
                    )
                )

            results.append(
                DetectionResult(
                    detected=True,
                    incident_type="PodPending",
                    severity="high",
                    reason=f"Pod '{pod_name}' stuck Pending — {sub_reason}",
                    evidence=evidence,
                    affected_resource=f"{namespace}/{pod_name}",
                    namespace=namespace,
                    workload=workload,
                    pod_name=pod_name,
                    raw_signals={
                        "phase": "Pending",
                        "pending_seconds": int(pending_secs),
                        "scheduling_reasons": scheduling_reasons,
                    },
                )
            )
            logger.info("Pending pod detected: pod=%s pending_secs=%d", pod_name, int(pending_secs))

        return results
