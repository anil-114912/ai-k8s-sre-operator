"""Detector for DNS failures in Kubernetes clusters."""
from __future__ import annotations

import logging
from typing import Any, Dict, List

from detectors.base import BaseDetector, DetectionResult
from models.incident import Evidence

logger = logging.getLogger(__name__)

DNS_LOG_PATTERNS = [
    "dial tcp: lookup",
    "no such host",
    "i/o timeout",
    "connection refused",
    "dns resolution failed",
    "failed to resolve",
    "getaddrinfow",
    "nodename nor servname provided",
]

COREDNS_LABELS = {"k8s-app": "kube-dns", "app": "coredns"}


class DNSDetector(BaseDetector):
    """Detects DNS resolution failures and CoreDNS health issues."""

    name = "dns_detector"
    description = "Detects DNS failures from pod logs and CoreDNS pod health"

    def detect(self, cluster_state: Dict[str, Any]) -> List[DetectionResult]:
        """Check logs for DNS failure patterns and CoreDNS pod health.

        Args:
            cluster_state: Full cluster state dict.

        Returns:
            List of DetectionResult objects for DNS failures.
        """
        results: List[DetectionResult] = []
        recent_logs = cluster_state.get("recent_logs", {})
        pods = cluster_state.get("pods", [])

        # Check for DNS errors in pod logs
        dns_failures: Dict[str, List[str]] = {}
        for log_key, log_lines in recent_logs.items():
            matched_patterns = []
            for line in log_lines:
                line_lower = line.lower()
                for pattern in DNS_LOG_PATTERNS:
                    if pattern in line_lower:
                        matched_patterns.append(line)
                        break
            if matched_patterns:
                dns_failures[log_key] = matched_patterns

        # Check CoreDNS pod health
        coredns_unhealthy = []
        for pod in pods:
            labels = pod.get("labels", {})
            is_coredns = (
                labels.get("k8s-app") == "kube-dns"
                or labels.get("app") in ("coredns", "kube-dns")
                or "coredns" in pod.get("name", "").lower()
            )
            if not is_coredns:
                continue
            phase = pod.get("phase", "")
            cs_list = pod.get("container_statuses", [])
            for cs in cs_list:
                state = cs.get("state", {})
                waiting = state.get("waiting", {})
                if phase != "Running" or waiting.get("reason") in (
                    "CrashLoopBackOff", "ErrImagePull", "ImagePullBackOff"
                ):
                    coredns_unhealthy.append(pod.get("name", "coredns"))

        if not dns_failures and not coredns_unhealthy:
            return results

        # Build results for affected workloads
        for log_key, matched_lines in dns_failures.items():
            parts = log_key.split("/")
            namespace = parts[0] if len(parts) > 0 else "default"
            pod_name = parts[1] if len(parts) > 1 else ""
            container_name = parts[2] if len(parts) > 2 else ""
            workload = pod_name.rsplit("-", 2)[0] if "-" in pod_name else pod_name

            evidence: List[Evidence] = [
                self._make_evidence(
                    source="pod_logs",
                    content=f"DNS failure log lines in {log_key}:\n" + "\n".join(matched_lines[:5]),
                    relevance=1.0,
                ),
            ]

            if coredns_unhealthy:
                evidence.append(
                    self._make_evidence(
                        source="detector",
                        content=f"CoreDNS pods unhealthy: {', '.join(coredns_unhealthy)}",
                        relevance=0.95,
                    )
                )

            results.append(
                DetectionResult(
                    detected=True,
                    incident_type="DNSFailure",
                    severity="high",
                    reason=f"DNS resolution failures detected in {log_key}",
                    evidence=evidence,
                    affected_resource=f"{namespace}/{pod_name}",
                    namespace=namespace,
                    workload=workload,
                    pod_name=pod_name,
                    container_name=container_name,
                    raw_signals={
                        "dns_error_lines": matched_lines[:10],
                        "coredns_unhealthy": coredns_unhealthy,
                    },
                )
            )
            logger.info("DNSFailure detected: %s", log_key)

        # CoreDNS unhealthy but no specific pod logs
        if coredns_unhealthy and not dns_failures:
            evidence = [
                self._make_evidence(
                    source="detector",
                    content=f"CoreDNS pods are unhealthy: {', '.join(coredns_unhealthy)}. DNS resolution may be impaired cluster-wide.",
                    relevance=1.0,
                )
            ]
            results.append(
                DetectionResult(
                    detected=True,
                    incident_type="DNSFailure",
                    severity="critical",
                    reason=f"CoreDNS pods unhealthy: {', '.join(coredns_unhealthy)}",
                    evidence=evidence,
                    affected_resource="kube-system/coredns",
                    namespace="kube-system",
                    workload="coredns",
                    raw_signals={"coredns_unhealthy": coredns_unhealthy},
                )
            )
            logger.info("CoreDNS unhealthy pods detected: %s", coredns_unhealthy)

        return results
