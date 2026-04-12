"""Detector for HorizontalPodAutoscaler misconfigurations."""
from __future__ import annotations

import logging
from typing import Any, Dict, List

from detectors.base import BaseDetector, DetectionResult
from models.incident import Evidence

logger = logging.getLogger(__name__)

HPA_CPU_SATURATION_THRESHOLD = 80


class HPADetector(BaseDetector):
    """Detects HPA misconfigurations including static ranges and capacity saturation."""

    name = "hpa_detector"
    description = "Detects HPA misconfigurations: locked ranges, maxed out, missing metrics"

    def detect(self, cluster_state: Dict[str, Any]) -> List[DetectionResult]:
        """Analyse all HPAs for scaling misconfiguration.

        Args:
            cluster_state: Full cluster state dict.

        Returns:
            List of DetectionResult for misconfigured HPAs.
        """
        results: List[DetectionResult] = []
        hpas = cluster_state.get("hpas", [])

        for hpa in hpas:
            hpa_name = hpa.get("name", "")
            namespace = hpa.get("namespace", "default")
            min_replicas = hpa.get("minReplicas", 1)
            max_replicas = hpa.get("maxReplicas", 1)
            current_replicas = hpa.get("currentReplicas", 0)
            current_cpu = hpa.get("currentCPUUtilizationPercentage")
            target_cpu = hpa.get("targetCPUUtilizationPercentage")
            metrics = hpa.get("metrics", [])
            conditions = hpa.get("conditions", [])
            target_ref = hpa.get("scaleTargetRef", {})
            workload = target_ref.get("name", hpa_name)

            issues: List[str] = []
            evidence: List[Evidence] = []

            # 1. Locked scaling range (min == max)
            if min_replicas == max_replicas:
                issues.append(f"minReplicas ({min_replicas}) == maxReplicas ({max_replicas}) — HPA cannot scale")
                evidence.append(
                    self._make_evidence(
                        source="manifest",
                        content=f"HPA '{hpa_name}': minReplicas={min_replicas}, maxReplicas={max_replicas} (no scaling range)",
                        relevance=1.0,
                    )
                )

            # 2. At max replicas with high CPU
            if (
                current_replicas == max_replicas
                and current_cpu is not None
                and current_cpu > HPA_CPU_SATURATION_THRESHOLD
            ):
                issues.append(
                    f"HPA at maxReplicas={max_replicas} with CPU={current_cpu}% — cannot scale further"
                )
                evidence.append(
                    self._make_evidence(
                        source="metrics",
                        content=(
                            f"HPA '{hpa_name}': currentReplicas={current_replicas} (at max), "
                            f"CPU={current_cpu}% (target={target_cpu}%)"
                        ),
                        relevance=0.95,
                    )
                )

            # 3. Missing metrics (AbleToScale condition False, or no metrics reported)
            for cond in conditions:
                if cond.get("type") == "ScalingActive" and cond.get("status") == "False":
                    reason = cond.get("reason", "")
                    message = cond.get("message", "")
                    issues.append(f"HPA scaling inactive: {reason} — {message}")
                    evidence.append(
                        self._make_evidence(
                            source="k8s_events",
                            content=f"HPA condition ScalingActive=False: {message}",
                            relevance=1.0,
                        )
                    )

            if not issues:
                continue

            results.append(
                DetectionResult(
                    detected=True,
                    incident_type="HPAMisconfigured",
                    severity="medium",
                    reason="; ".join(issues),
                    evidence=evidence,
                    affected_resource=f"{namespace}/{hpa_name}",
                    namespace=namespace,
                    workload=workload,
                    raw_signals={
                        "min_replicas": min_replicas,
                        "max_replicas": max_replicas,
                        "current_replicas": current_replicas,
                        "current_cpu": current_cpu,
                        "issues": issues,
                    },
                )
            )
            logger.info(
                "HPA misconfiguration detected: hpa=%s/%s issues=%s",
                namespace,
                hpa_name,
                issues,
            )

        return results
