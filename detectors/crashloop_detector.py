"""Detector for CrashLoopBackOff incidents."""

from __future__ import annotations

import logging
from typing import Any, Dict, List

from detectors.base import BaseDetector, DetectionResult
from models.incident import Evidence

logger = logging.getLogger(__name__)

CRASHLOOP_RESTART_THRESHOLD = 5


class CrashLoopDetector(BaseDetector):
    """Detects pods stuck in CrashLoopBackOff or with excessive restart counts."""

    name = "crashloop_detector"
    description = "Detects CrashLoopBackOff and excessive container restarts"

    def detect(self, cluster_state: Dict[str, Any]) -> List[DetectionResult]:
        """Check all pods for CrashLoopBackOff or high restart counts.

        Args:
            cluster_state: Full cluster state dict.

        Returns:
            List of DetectionResult objects for affected pods.
        """
        results: List[DetectionResult] = []
        pods = cluster_state.get("pods", [])
        recent_logs = cluster_state.get("recent_logs", {})

        for pod in pods:
            pod_name = pod.get("name", "")
            namespace = pod.get("namespace", "default")
            workload = pod.get(
                "workload", pod_name.rsplit("-", 2)[0] if "-" in pod_name else pod_name
            )

            container_statuses = pod.get("container_statuses", [])
            for cs in container_statuses:
                container_name = cs.get("name", "")
                restart_count = cs.get("restartCount", 0)
                state = cs.get("state", {})
                waiting = state.get("waiting", {})
                reason = waiting.get("reason", "")

                is_crashloop = reason == "CrashLoopBackOff"
                high_restarts = restart_count > CRASHLOOP_RESTART_THRESHOLD

                if not (is_crashloop or high_restarts):
                    continue

                evidence: List[Evidence] = []

                # Restart count evidence
                evidence.append(
                    self._make_evidence(
                        source="detector",
                        content=f"Container '{container_name}' has restarted {restart_count} times",
                        relevance=0.9,
                    )
                )

                # Container state evidence
                if is_crashloop:
                    msg = waiting.get("message", "container is crashing repeatedly")
                    evidence.append(
                        self._make_evidence(
                            source="k8s_events",
                            content=f"Container state: CrashLoopBackOff — {msg}",
                            relevance=1.0,
                        )
                    )

                # Last terminated state evidence
                last_state = cs.get("lastState", {})
                terminated = last_state.get("terminated", {})
                if terminated:
                    exit_code = terminated.get("exitCode", "unknown")
                    term_reason = terminated.get("reason", "")
                    evidence.append(
                        self._make_evidence(
                            source="detector",
                            content=f"Last termination: exitCode={exit_code}, reason={term_reason}",
                            relevance=0.85,
                        )
                    )

                # Log evidence
                log_key = f"{namespace}/{pod_name}/{container_name}"
                logs = recent_logs.get(log_key, [])
                if logs:
                    last_lines = logs[-5:] if len(logs) >= 5 else logs
                    evidence.append(
                        self._make_evidence(
                            source="pod_logs",
                            content="Last log lines:\n" + "\n".join(last_lines),
                            relevance=0.95,
                        )
                    )

                severity = "critical" if restart_count > 10 or is_crashloop else "high"

                results.append(
                    DetectionResult(
                        detected=True,
                        incident_type="CrashLoopBackOff",
                        severity=severity,
                        reason=f"Container '{container_name}' is CrashLooping (restarts={restart_count})",
                        evidence=evidence,
                        affected_resource=f"{namespace}/{pod_name}",
                        namespace=namespace,
                        workload=workload,
                        pod_name=pod_name,
                        container_name=container_name,
                        raw_signals={
                            "restart_count": restart_count,
                            "phase": pod.get("phase", "Running"),
                            "container_state": state,
                            "last_state": last_state,
                            "exit_code": terminated.get("exitCode") if terminated else None,
                        },
                    )
                )
                logger.info(
                    "CrashLoop detected: pod=%s container=%s restarts=%d",
                    pod_name,
                    container_name,
                    restart_count,
                )

        return results
