"""Detectors package — deterministic failure detection for Kubernetes resources."""
from __future__ import annotations

from typing import Any, Dict, List

from detectors.base import BaseDetector, DetectionResult

# Original 9 detectors
from detectors.crashloop_detector import CrashLoopDetector
from detectors.oomkill_detector import OOMKillDetector
from detectors.imagepull_detector import ImagePullDetector
from detectors.pending_pods_detector import PendingPodsDetector
from detectors.probe_failure_detector import ProbeFailureDetector
from detectors.service_detector import ServiceDetector
from detectors.ingress_detector import IngressDetector
from detectors.pvc_detector import PVCDetector
from detectors.hpa_detector import HPADetector

# New 9 detectors
from detectors.quota_detector import QuotaDetector
from detectors.dns_detector import DNSDetector
from detectors.rbac_detector import RBACDetector
from detectors.network_policy_detector import NetworkPolicyDetector
from detectors.cni_detector import CNIDetector
from detectors.service_mesh_detector import ServiceMeshDetector
from detectors.node_pressure_detector import NodePressureDetector
from detectors.storage_detector import StorageDetector
from detectors.rollout_detector import RolloutDetector

import logging

logger = logging.getLogger(__name__)

# All 18 detectors
ALL_DETECTORS: List[BaseDetector] = [
    CrashLoopDetector(),
    OOMKillDetector(),
    ImagePullDetector(),
    PendingPodsDetector(),
    ProbeFailureDetector(),
    ServiceDetector(),
    IngressDetector(),
    PVCDetector(),
    HPADetector(),
    QuotaDetector(),
    DNSDetector(),
    RBACDetector(),
    NetworkPolicyDetector(),
    CNIDetector(),
    ServiceMeshDetector(),
    NodePressureDetector(),
    StorageDetector(),
    RolloutDetector(),
]


def run_all_detectors(cluster_state: Dict[str, Any]) -> List[DetectionResult]:
    """Run all 18 detectors against cluster state and return combined results.

    Args:
        cluster_state: Full cluster state dict with pods, events, nodes, etc.

    Returns:
        Combined list of DetectionResult objects from all detectors.
    """
    all_results: List[DetectionResult] = []
    for detector in ALL_DETECTORS:
        try:
            results = detector.detect(cluster_state)
            all_results.extend(results)
        except Exception as exc:
            logger.error("Detector '%s' failed: %s", detector.name, exc)
    logger.info(
        "run_all_detectors: %d detectors ran, %d total detections",
        len(ALL_DETECTORS),
        len(all_results),
    )
    return all_results


__all__ = [
    "BaseDetector",
    "DetectionResult",
    "CrashLoopDetector",
    "OOMKillDetector",
    "ImagePullDetector",
    "PendingPodsDetector",
    "ProbeFailureDetector",
    "ServiceDetector",
    "IngressDetector",
    "PVCDetector",
    "HPADetector",
    "QuotaDetector",
    "DNSDetector",
    "RBACDetector",
    "NetworkPolicyDetector",
    "CNIDetector",
    "ServiceMeshDetector",
    "NodePressureDetector",
    "StorageDetector",
    "RolloutDetector",
    "ALL_DETECTORS",
    "run_all_detectors",
]
