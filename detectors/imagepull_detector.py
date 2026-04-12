"""Detector for ImagePullBackOff and ErrImagePull incidents."""
from __future__ import annotations

import logging
from typing import Any, Dict, List

from detectors.base import BaseDetector, DetectionResult
from models.incident import Evidence

logger = logging.getLogger(__name__)

IMAGE_PULL_REASONS = {"ImagePullBackOff", "ErrImagePull", "InvalidImageName"}


class ImagePullDetector(BaseDetector):
    """Detects containers that cannot pull their specified image."""

    name = "imagepull_detector"
    description = "Detects ImagePullBackOff and ErrImagePull container failures"

    def detect(self, cluster_state: Dict[str, Any]) -> List[DetectionResult]:
        """Check for image pull failures across all pods.

        Args:
            cluster_state: Full cluster state dict.

        Returns:
            List of DetectionResult for pods with image pull issues.
        """
        results: List[DetectionResult] = []
        pods = cluster_state.get("pods", [])

        for pod in pods:
            pod_name = pod.get("name", "")
            namespace = pod.get("namespace", "default")
            workload = pod.get("workload", pod_name.rsplit("-", 2)[0] if "-" in pod_name else pod_name)

            container_statuses = pod.get("container_statuses", [])
            containers = pod.get("containers", [])

            for cs in container_statuses:
                container_name = cs.get("name", "")
                state = cs.get("state", {})
                waiting = state.get("waiting", {})
                reason = waiting.get("reason", "")

                if reason not in IMAGE_PULL_REASONS:
                    continue

                evidence: List[Evidence] = []

                # Find image name from spec
                image = "unknown"
                for c in containers:
                    if c.get("name") == container_name:
                        image = c.get("image", "unknown")
                        break

                evidence.append(
                    self._make_evidence(
                        source="detector",
                        content=(
                            f"Container '{container_name}' cannot pull image '{image}' "
                            f"— reason: {reason}"
                        ),
                        relevance=1.0,
                    )
                )

                # Waiting message detail
                msg = waiting.get("message", "")
                if msg:
                    evidence.append(
                        self._make_evidence(
                            source="k8s_events",
                            content=f"Kubernetes message: {msg}",
                            relevance=0.9,
                        )
                    )

                # Check events for more detail
                events = cluster_state.get("events", [])
                for ev in events:
                    if (
                        ev.get("involvedObject", {}).get("name") == pod_name
                        and ev.get("reason") in IMAGE_PULL_REASONS
                    ):
                        evidence.append(
                            self._make_evidence(
                                source="k8s_events",
                                content=f"Event: {ev.get('message', '')}",
                                relevance=0.85,
                            )
                        )

                results.append(
                    DetectionResult(
                        detected=True,
                        incident_type="ImagePullBackOff",
                        severity="high",
                        reason=f"Container '{container_name}' cannot pull image '{image}'",
                        evidence=evidence,
                        affected_resource=f"{namespace}/{pod_name}",
                        namespace=namespace,
                        workload=workload,
                        pod_name=pod_name,
                        container_name=container_name,
                        raw_signals={"image": image, "reason": reason, "message": msg},
                    )
                )
                logger.info(
                    "ImagePull failure detected: pod=%s image=%s reason=%s",
                    pod_name,
                    image,
                    reason,
                )

        return results
