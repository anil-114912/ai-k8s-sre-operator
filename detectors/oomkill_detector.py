"""Detector for OOMKilled (Out-Of-Memory killed) container incidents."""
from __future__ import annotations

import logging
from typing import Any, Dict, List

from detectors.base import BaseDetector, DetectionResult
from models.incident import Evidence

logger = logging.getLogger(__name__)


class OOMKillDetector(BaseDetector):
    """Detects containers that have been killed due to memory limit violations."""

    name = "oomkill_detector"
    description = "Detects OOMKilled container terminations"

    def detect(self, cluster_state: Dict[str, Any]) -> List[DetectionResult]:
        """Scan pods for OOMKilled terminations in current or last state.

        Args:
            cluster_state: Full cluster state dict.

        Returns:
            List of DetectionResult objects for OOMKilled containers.
        """
        results: List[DetectionResult] = []
        pods = cluster_state.get("pods", [])

        for pod in pods:
            pod_name = pod.get("name", "")
            namespace = pod.get("namespace", "default")
            workload = pod.get("workload", pod_name.rsplit("-", 2)[0] if "-" in pod_name else pod_name)

            container_statuses = pod.get("container_statuses", [])
            for cs in container_statuses:
                container_name = cs.get("name", "")
                state = cs.get("state", {})
                last_state = cs.get("lastState", {})

                # Check current state terminated
                current_term = state.get("terminated", {})
                last_term = last_state.get("terminated", {})

                is_oom = (
                    current_term.get("reason") == "OOMKilled"
                    or last_term.get("reason") == "OOMKilled"
                )

                if not is_oom:
                    continue

                evidence: List[Evidence] = []

                # Termination evidence
                term = current_term if current_term.get("reason") == "OOMKilled" else last_term
                evidence.append(
                    self._make_evidence(
                        source="detector",
                        content=(
                            f"Container '{container_name}' was OOMKilled — "
                            f"exitCode={term.get('exitCode', 137)}, "
                            f"finishedAt={term.get('finishedAt', 'unknown')}"
                        ),
                        relevance=1.0,
                    )
                )

                # Memory limits evidence from container spec
                containers = pod.get("containers", [])
                for c in containers:
                    if c.get("name") == container_name:
                        resources = c.get("resources", {})
                        limits = resources.get("limits", {})
                        requests = resources.get("requests", {})
                        if limits or requests:
                            evidence.append(
                                self._make_evidence(
                                    source="manifest",
                                    content=(
                                        f"Memory limits: {limits.get('memory', 'not set')}, "
                                        f"requests: {requests.get('memory', 'not set')}"
                                    ),
                                    relevance=0.95,
                                )
                            )
                        break

                restart_count = cs.get("restartCount", 0)
                evidence.append(
                    self._make_evidence(
                        source="detector",
                        content=f"Restart count after OOMKill events: {restart_count}",
                        relevance=0.7,
                    )
                )

                results.append(
                    DetectionResult(
                        detected=True,
                        incident_type="OOMKilled",
                        severity="high",
                        reason=f"Container '{container_name}' OOMKilled (exitCode=137)",
                        evidence=evidence,
                        affected_resource=f"{namespace}/{pod_name}",
                        namespace=namespace,
                        workload=workload,
                        pod_name=pod_name,
                        container_name=container_name,
                        raw_signals={
                            "restart_count": restart_count,
                            "last_terminated": last_term,
                            "current_terminated": current_term,
                        },
                    )
                )
                logger.info(
                    "OOMKill detected: pod=%s container=%s", pod_name, container_name
                )

        return results
