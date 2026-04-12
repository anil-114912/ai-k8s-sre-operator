"""Detector for Ingress configuration failures and missing backends."""
from __future__ import annotations

import logging
from typing import Any, Dict, List

from detectors.base import BaseDetector, DetectionResult
from models.incident import Evidence

logger = logging.getLogger(__name__)


class IngressDetector(BaseDetector):
    """Detects ingresses pointing to non-existent or endpoint-less services."""

    name = "ingress_detector"
    description = "Detects broken Ingress rules — missing backend services or empty endpoints"

    def detect(self, cluster_state: Dict[str, Any]) -> List[DetectionResult]:
        """Verify each Ingress rule resolves to a service with live endpoints.

        Args:
            cluster_state: Full cluster state dict.

        Returns:
            List of DetectionResult for broken ingress rules.
        """
        results: List[DetectionResult] = []
        ingresses = cluster_state.get("ingresses", [])
        services = cluster_state.get("services", [])
        endpoints = cluster_state.get("endpoints", [])

        # Build service existence set: namespace/name
        svc_set: set = set()
        for svc in services:
            ns = svc.get("namespace", "default")
            name = svc.get("name", "")
            svc_set.add(f"{ns}/{name}")

        # Build endpoints map: namespace/name -> address count
        ep_map: Dict[str, int] = {}
        for ep in endpoints:
            ns = ep.get("namespace", "default")
            name = ep.get("name", "")
            subsets = ep.get("subsets", [])
            addr_count = sum(len(s.get("addresses", [])) for s in subsets)
            ep_map[f"{ns}/{name}"] = ep_map.get(f"{ns}/{name}", 0) + addr_count

        for ingress in ingresses:
            ingress_name = ingress.get("name", "")
            namespace = ingress.get("namespace", "default")
            rules = ingress.get("rules", [])

            for rule in rules:
                host = rule.get("host", "*")
                paths = rule.get("http", {}).get("paths", [])

                for path_entry in paths:
                    backend = path_entry.get("backend", {})
                    svc_info = backend.get("service", backend)
                    svc_name = svc_info.get("name", "")
                    svc_port = svc_info.get("port", {})
                    if isinstance(svc_port, dict):
                        svc_port = svc_port.get("number", svc_port.get("name", ""))

                    if not svc_name:
                        continue

                    key = f"{namespace}/{svc_name}"
                    svc_exists = key in svc_set
                    ep_count = ep_map.get(key, -1)
                    has_endpoints = ep_count > 0 if ep_count >= 0 else svc_exists

                    if not svc_exists:
                        evidence: List[Evidence] = [
                            self._make_evidence(
                                source="detector",
                                content=(
                                    f"Ingress '{ingress_name}' rule for host '{host}' "
                                    f"references service '{svc_name}' which does not exist "
                                    f"in namespace '{namespace}'"
                                ),
                                relevance=1.0,
                            )
                        ]
                        results.append(
                            DetectionResult(
                                detected=True,
                                incident_type="IngressFailure",
                                severity="high",
                                reason=f"Ingress '{ingress_name}' backend service '{svc_name}' not found",
                                evidence=evidence,
                                affected_resource=f"{namespace}/{ingress_name}",
                                namespace=namespace,
                                workload=ingress_name,
                                raw_signals={
                                    "host": host,
                                    "service": svc_name,
                                    "port": svc_port,
                                    "error": "service_not_found",
                                },
                            )
                        )
                        logger.info(
                            "Ingress broken: ingress=%s/%s backend_svc=%s not found",
                            namespace,
                            ingress_name,
                            svc_name,
                        )
                    elif not has_endpoints:
                        evidence = [
                            self._make_evidence(
                                source="detector",
                                content=(
                                    f"Ingress '{ingress_name}' backend service '{svc_name}' "
                                    f"exists but has 0 ready endpoints"
                                ),
                                relevance=0.95,
                            )
                        ]
                        results.append(
                            DetectionResult(
                                detected=True,
                                incident_type="IngressFailure",
                                severity="medium",
                                reason=f"Ingress '{ingress_name}' backend '{svc_name}' has no ready endpoints",
                                evidence=evidence,
                                affected_resource=f"{namespace}/{ingress_name}",
                                namespace=namespace,
                                workload=ingress_name,
                                raw_signals={
                                    "host": host,
                                    "service": svc_name,
                                    "port": svc_port,
                                    "error": "no_endpoints",
                                },
                            )
                        )

        return results
