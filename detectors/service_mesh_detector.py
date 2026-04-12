"""Detector for service mesh failures (Istio/Linkerd)."""
from __future__ import annotations

import logging
from typing import Any, Dict, List

from detectors.base import BaseDetector, DetectionResult
from models.incident import Evidence

logger = logging.getLogger(__name__)

SIDECAR_INJECTION_PATTERNS = [
    "sidecar injection failed",
    "failed to inject sidecar",
    "istio-proxy",
    "linkerd-proxy",
    "webhook.istio.io",
]

MESH_LOG_PATTERNS = [
    "upstream connect error",
    "503 service unavailable",
    "upstream connection failure",
    "circuit breaker",
    "no healthy upstream",
    "connection reset by peer",
    "upstream request timeout",
    "envoy proxy",
    "no healthy endpoint",
    "mtls handshake failed",
    "tls handshake error",
    "peer certificate",
    "certificate verify failed",
]

CIRCUIT_BREAKER_PATTERNS = [
    "circuit breaker",
    "consecutive errors",
    "ejected from load balancer",
]


class ServiceMeshDetector(BaseDetector):
    """Detects service mesh (Istio/Linkerd) configuration and runtime failures."""

    name = "service_mesh_detector"
    description = "Detects Istio/Linkerd sidecar injection failures, mTLS mismatches, and circuit breaker events"

    def detect(self, cluster_state: Dict[str, Any]) -> List[DetectionResult]:
        """Check events and logs for service mesh failure patterns.

        Args:
            cluster_state: Full cluster state dict.

        Returns:
            List of DetectionResult objects for service mesh issues.
        """
        results: List[DetectionResult] = []
        events = cluster_state.get("events", [])
        recent_logs = cluster_state.get("recent_logs", {})
        pods = cluster_state.get("pods", [])

        seen: Dict[str, bool] = {}

        # Check events for sidecar injection failures
        for event in events:
            message = event.get("message", "")
            message_lower = message.lower()
            namespace = event.get("namespace", "default")
            involved = event.get("involvedObject", {})
            pod_name = involved.get("name", "")

            is_mesh_event = any(p in message_lower for p in [
                "sidecar", "istio", "linkerd", "envoy", "mtls", "circuit"
            ])
            if not is_mesh_event:
                continue

            key = f"event:{namespace}/{pod_name}"
            if seen.get(key):
                continue
            seen[key] = True

            evidence: List[Evidence] = [
                self._make_evidence(
                    source="k8s_events",
                    content=f"Service mesh event in '{namespace}': {message}",
                    relevance=1.0,
                ),
            ]

            results.append(
                DetectionResult(
                    detected=True,
                    incident_type="ServiceMeshFailure",
                    severity="high",
                    reason=f"Service mesh failure in '{namespace}/{pod_name}': {message[:100]}",
                    evidence=evidence,
                    affected_resource=f"{namespace}/{pod_name}",
                    namespace=namespace,
                    workload=pod_name.rsplit("-", 2)[0] if "-" in pod_name else pod_name,
                    pod_name=pod_name,
                    raw_signals={"mesh_event_message": message},
                )
            )
            logger.info("ServiceMesh event detected: %s/%s", namespace, pod_name)

        # Check logs for mesh failure patterns
        for log_key, log_lines in recent_logs.items():
            mesh_errors = []
            circuit_breaker_hits = []
            mtls_errors = []

            for line in log_lines:
                line_lower = line.lower()
                if any(p in line_lower for p in CIRCUIT_BREAKER_PATTERNS):
                    circuit_breaker_hits.append(line)
                elif any(p in line_lower for p in ["mtls", "tls handshake", "certificate"]):
                    mtls_errors.append(line)
                elif any(p in line_lower for p in MESH_LOG_PATTERNS):
                    mesh_errors.append(line)

            if not mesh_errors and not circuit_breaker_hits and not mtls_errors:
                continue

            parts = log_key.split("/")
            namespace = parts[0] if len(parts) > 0 else "default"
            pod_name = parts[1] if len(parts) > 1 else ""
            container_name = parts[2] if len(parts) > 2 else ""
            workload = pod_name.rsplit("-", 2)[0] if "-" in pod_name else pod_name

            key = f"log:{log_key}"
            if seen.get(key):
                continue
            seen[key] = True

            evidence = []
            severity = "medium"

            if circuit_breaker_hits:
                severity = "high"
                evidence.append(
                    self._make_evidence(
                        source="pod_logs",
                        content=f"Circuit breaker events in {log_key}:\n" + "\n".join(circuit_breaker_hits[:3]),
                        relevance=1.0,
                    )
                )

            if mtls_errors:
                severity = "high"
                evidence.append(
                    self._make_evidence(
                        source="pod_logs",
                        content=f"mTLS errors in {log_key}:\n" + "\n".join(mtls_errors[:3]),
                        relevance=0.95,
                    )
                )

            if mesh_errors:
                evidence.append(
                    self._make_evidence(
                        source="pod_logs",
                        content=f"Service mesh errors in {log_key}:\n" + "\n".join(mesh_errors[:5]),
                        relevance=0.9,
                    )
                )

            issue_type = "circuit_breaker" if circuit_breaker_hits else ("mtls_mismatch" if mtls_errors else "upstream_error")

            results.append(
                DetectionResult(
                    detected=True,
                    incident_type="ServiceMeshFailure",
                    severity=severity,
                    reason=f"Service mesh failure ({issue_type}) in {log_key}",
                    evidence=evidence,
                    affected_resource=f"{namespace}/{pod_name}",
                    namespace=namespace,
                    workload=workload,
                    pod_name=pod_name,
                    container_name=container_name,
                    raw_signals={
                        "issue_type": issue_type,
                        "circuit_breaker_hits": len(circuit_breaker_hits),
                        "mtls_errors": len(mtls_errors),
                        "mesh_errors": len(mesh_errors),
                    },
                )
            )
            logger.info("ServiceMeshFailure detected: %s type=%s", log_key, issue_type)

        return results
