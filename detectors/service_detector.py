"""Detector for Service selector mismatches and missing endpoints."""
from __future__ import annotations

import logging
from typing import Any, Dict, List, Set

from detectors.base import BaseDetector, DetectionResult
from models.incident import Evidence

logger = logging.getLogger(__name__)


class ServiceDetector(BaseDetector):
    """Detects services with no matching pods or missing endpoints."""

    name = "service_detector"
    description = "Detects service selector mismatches and absent endpoints"

    def detect(self, cluster_state: Dict[str, Any]) -> List[DetectionResult]:
        """Check each service selector against running pod labels.

        Args:
            cluster_state: Full cluster state dict.

        Returns:
            List of DetectionResult for mismatched services.
        """
        results: List[DetectionResult] = []
        services = cluster_state.get("services", [])
        pods = cluster_state.get("pods", [])
        endpoints = cluster_state.get("endpoints", [])

        # Build endpoints map: service name -> endpoint addresses count
        ep_map: Dict[str, int] = {}
        for ep in endpoints:
            svc_name = ep.get("name", "")
            subsets = ep.get("subsets", [])
            addr_count = sum(len(s.get("addresses", [])) for s in subsets)
            ep_map[svc_name] = ep_map.get(svc_name, 0) + addr_count

        # Build running pod label index: namespace -> list of label dicts
        running_pod_labels: Dict[str, List[Dict[str, str]]] = {}
        for pod in pods:
            if pod.get("phase") not in ("Running", "Pending"):
                continue
            ns = pod.get("namespace", "default")
            labels = pod.get("labels", {})
            if ns not in running_pod_labels:
                running_pod_labels[ns] = []
            running_pod_labels[ns].append(labels)

        for svc in services:
            svc_name = svc.get("name", "")
            namespace = svc.get("namespace", "default")
            svc_type = svc.get("type", "ClusterIP")

            # Skip headless and ExternalName
            if svc_type in ("ExternalName",):
                continue

            selector = svc.get("selector", {})
            if not selector:
                continue  # Selector-less services are intentional

            # Check if any running pod matches selector
            ns_pod_labels = running_pod_labels.get(namespace, [])
            matching_pods = 0
            for pod_labels in ns_pod_labels:
                if all(pod_labels.get(k) == v for k, v in selector.items()):
                    matching_pods += 1

            ep_count = ep_map.get(svc_name, -1)
            has_endpoints = ep_count > 0 if ep_count >= 0 else matching_pods > 0

            if not has_endpoints:
                evidence: List[Evidence] = []
                evidence.append(
                    self._make_evidence(
                        source="detector",
                        content=(
                            f"Service '{svc_name}' selector {selector} "
                            f"matches {matching_pods} running pods"
                        ),
                        relevance=1.0,
                    )
                )
                if ep_count == 0:
                    evidence.append(
                        self._make_evidence(
                            source="k8s_events",
                            content=f"EndpointSlice for '{svc_name}' has 0 ready addresses",
                            relevance=0.9,
                        )
                    )

                results.append(
                    DetectionResult(
                        detected=True,
                        incident_type="ServiceMismatch",
                        severity="high",
                        reason=f"Service '{svc_name}' has no matching pods for selector {selector}",
                        evidence=evidence,
                        affected_resource=f"{namespace}/{svc_name}",
                        namespace=namespace,
                        workload=svc_name,
                        raw_signals={
                            "selector": selector,
                            "matching_pods": matching_pods,
                            "endpoint_count": ep_count,
                        },
                    )
                )
                logger.info(
                    "Service mismatch detected: service=%s/%s selector=%s",
                    namespace,
                    svc_name,
                    selector,
                )

        return results
