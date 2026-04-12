"""Detector for liveness and readiness probe failures."""
from __future__ import annotations

import logging
from typing import Any, Dict, List

from detectors.base import BaseDetector, DetectionResult
from models.incident import Evidence

logger = logging.getLogger(__name__)


class ProbeFailureDetector(BaseDetector):
    """Detects containers with failing liveness or readiness probes."""

    name = "probe_failure_detector"
    description = "Detects liveness and readiness probe failures from Kubernetes events"

    def detect(self, cluster_state: Dict[str, Any]) -> List[DetectionResult]:
        """Scan events for Unhealthy events indicating probe failures.

        Args:
            cluster_state: Full cluster state dict.

        Returns:
            List of DetectionResult for probe failures.
        """
        results: List[DetectionResult] = []
        events = cluster_state.get("events", [])
        pods = cluster_state.get("pods", [])

        # Build pod lookup
        pod_map: Dict[str, Dict[str, Any]] = {}
        for pod in pods:
            pod_map[pod.get("name", "")] = pod

        seen_pods: set = set()

        for ev in events:
            if ev.get("reason") != "Unhealthy":
                continue

            msg = ev.get("message", "")
            is_readiness = "Readiness probe failed" in msg
            is_liveness = "Liveness probe failed" in msg
            is_startup = "Startup probe failed" in msg

            if not (is_readiness or is_liveness or is_startup):
                continue

            involved = ev.get("involvedObject", {})
            pod_name = involved.get("name", "")
            namespace = ev.get("namespace", involved.get("namespace", "default"))

            # Deduplicate per pod
            key = f"{namespace}/{pod_name}"
            if key in seen_pods:
                continue
            seen_pods.add(key)

            pod = pod_map.get(pod_name, {})
            workload = pod.get(
                "workload",
                pod_name.rsplit("-", 2)[0] if "-" in pod_name else pod_name,
            )

            probe_type = (
                "Readiness" if is_readiness else ("Startup" if is_startup else "Liveness")
            )

            evidence: List[Evidence] = []
            evidence.append(
                self._make_evidence(
                    source="k8s_events",
                    content=f"{probe_type} probe failure: {msg}",
                    relevance=1.0,
                    timestamp=ev.get("lastTimestamp", ev.get("firstTimestamp")),
                )
            )

            # Count probe events
            count = ev.get("count", 1)
            evidence.append(
                self._make_evidence(
                    source="k8s_events",
                    content=f"Probe failure event count: {count}",
                    relevance=0.7,
                )
            )

            # Check container spec for probe config
            containers = pod.get("containers", [])
            for c in containers:
                probe_key = (
                    "readinessProbe" if is_readiness else ("startupProbe" if is_startup else "livenessProbe")
                )
                probe_spec = c.get(probe_key, {})
                if probe_spec:
                    evidence.append(
                        self._make_evidence(
                            source="manifest",
                            content=f"Probe config: {probe_spec}",
                            relevance=0.8,
                        )
                    )

            severity = "high" if is_liveness else "medium"

            results.append(
                DetectionResult(
                    detected=True,
                    incident_type="ProbeFailure",
                    severity=severity,
                    reason=f"{probe_type} probe failing for pod '{pod_name}'",
                    evidence=evidence,
                    affected_resource=f"{namespace}/{pod_name}",
                    namespace=namespace,
                    workload=workload,
                    pod_name=pod_name,
                    raw_signals={"probe_type": probe_type, "message": msg, "count": count},
                )
            )
            logger.info(
                "Probe failure detected: pod=%s probe_type=%s", pod_name, probe_type
            )

        return results
