"""Detector for failed Deployment rollouts."""
from __future__ import annotations

import logging
from typing import Any, Dict, List

from detectors.base import BaseDetector, DetectionResult
from models.incident import Evidence

logger = logging.getLogger(__name__)


class RolloutDetector(BaseDetector):
    """Detects failed or stalled Kubernetes Deployment rollouts."""

    name = "rollout_detector"
    description = "Detects ProgressDeadlineExceeded and unavailable-replica rollout failures"

    def detect(self, cluster_state: Dict[str, Any]) -> List[DetectionResult]:
        """Check Deployments and ReplicaSets for failed rollout conditions.

        Args:
            cluster_state: Full cluster state dict.

        Returns:
            List of DetectionResult objects for failed rollouts.
        """
        results: List[DetectionResult] = []
        deployments = cluster_state.get("deployments", [])
        events = cluster_state.get("events", [])

        for dep in deployments:
            dep_name = dep.get("name", "")
            namespace = dep.get("namespace", "default")
            conditions = dep.get("conditions", [])

            # Check for Available=False or ProgressDeadlineExceeded
            available = True
            progressing = True
            progress_deadline_exceeded = False
            available_false = False

            for cond in conditions:
                cond_type = cond.get("type", "")
                cond_status = cond.get("status", "True")
                reason = cond.get("reason", "")

                if cond_type == "Available" and cond_status == "False":
                    available = False
                    available_false = True

                if cond_type == "Progressing":
                    if cond_status == "False":
                        progressing = False
                    if reason == "ProgressDeadlineExceeded":
                        progress_deadline_exceeded = True

            if not available_false and not progress_deadline_exceeded:
                continue

            # Check replica counts
            desired = dep.get("desiredReplicas", dep.get("replicas", 0))
            available_replicas = dep.get("availableReplicas", 0)
            unavailable_replicas = dep.get("unavailableReplicas", desired - available_replicas if desired else 0)

            # Collect relevant events
            dep_events = [
                e for e in events
                if e.get("involvedObject", {}).get("name", "").startswith(dep_name)
                and e.get("namespace") == namespace
            ]

            severity = "critical" if progress_deadline_exceeded else "high"

            evidence: List[Evidence] = []

            if progress_deadline_exceeded:
                evidence.append(
                    self._make_evidence(
                        source="detector",
                        content=f"Deployment '{dep_name}' rollout has exceeded progress deadline. "
                                f"Desired={desired}, Available={available_replicas}, Unavailable={unavailable_replicas}",
                        relevance=1.0,
                    )
                )
            if available_false:
                evidence.append(
                    self._make_evidence(
                        source="detector",
                        content=f"Deployment '{dep_name}' condition Available=False. "
                                f"{unavailable_replicas} replicas unavailable.",
                        relevance=0.95,
                    )
                )

            for ev in dep_events[:3]:
                evidence.append(
                    self._make_evidence(
                        source="k8s_events",
                        content=f"Rollout event: reason={ev.get('reason','?')}, message={ev.get('message','?')}",
                        relevance=0.8,
                    )
                )

            reason_str = "ProgressDeadlineExceeded" if progress_deadline_exceeded else "Available=False"

            results.append(
                DetectionResult(
                    detected=True,
                    incident_type="FailedRollout",
                    severity=severity,
                    reason=f"Deployment '{dep_name}' rollout failed: {reason_str}",
                    evidence=evidence,
                    affected_resource=f"{namespace}/{dep_name}",
                    namespace=namespace,
                    workload=dep_name,
                    raw_signals={
                        "progress_deadline_exceeded": progress_deadline_exceeded,
                        "available_false": available_false,
                        "desired_replicas": desired,
                        "available_replicas": available_replicas,
                        "unavailable_replicas": unavailable_replicas,
                    },
                )
            )
            logger.info(
                "FailedRollout detected: %s/%s reason=%s",
                namespace, dep_name, reason_str,
            )

        return results
