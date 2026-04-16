"""Base detector abstraction for all incident detectors."""

from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from typing import Any, Dict, List

from models.incident import Evidence

logger = logging.getLogger(__name__)


class DetectionResult:
    """Result of a single detector run."""

    def __init__(
        self,
        detected: bool,
        incident_type: str,
        severity: str,
        reason: str,
        evidence: List[Evidence],
        affected_resource: str,
        namespace: str = "default",
        workload: str = "",
        pod_name: str = "",
        container_name: str = "",
        raw_signals: Dict[str, Any] = None,
    ) -> None:
        """Initialise a DetectionResult."""
        self.detected = detected
        self.incident_type = incident_type
        self.severity = severity
        self.reason = reason
        self.evidence = evidence
        self.affected_resource = affected_resource
        self.namespace = namespace
        self.workload = workload
        self.pod_name = pod_name
        self.container_name = container_name
        self.raw_signals = raw_signals or {}

    def __repr__(self) -> str:
        """String representation for debugging."""
        return (
            f"DetectionResult(detected={self.detected}, type={self.incident_type}, "
            f"resource={self.affected_resource}, severity={self.severity})"
        )


class BaseDetector(ABC):
    """Abstract base class for all incident detectors."""

    name: str = "base"
    description: str = "Base detector"

    @abstractmethod
    def detect(self, cluster_state: Dict[str, Any]) -> List[DetectionResult]:
        """Analyse cluster state and return any detected issues.

        Args:
            cluster_state: Dict with keys pods, events, deployments, services,
                endpoints, ingresses, nodes, hpas, pvcs, recent_logs.

        Returns:
            List of DetectionResult objects, one per detected issue.
        """
        ...

    def _make_evidence(
        self, source: str, content: str, relevance: float = 1.0, timestamp: str = None
    ) -> Evidence:
        """Helper to construct an Evidence object."""
        return Evidence(source=source, content=content, relevance=relevance, timestamp=timestamp)

    def _get_container_state(self, container_status: Dict[str, Any]) -> Dict[str, Any]:
        """Extract the current state from a container status dict."""
        return container_status.get("state", {})

    def _get_last_state(self, container_status: Dict[str, Any]) -> Dict[str, Any]:
        """Extract the last terminated state from a container status dict."""
        return container_status.get("lastState", {})
