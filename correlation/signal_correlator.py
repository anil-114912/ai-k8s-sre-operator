"""Signal correlator — classifies detection signals as root cause, contributing factor, or symptom."""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from detectors.base import DetectionResult

logger = logging.getLogger(__name__)


@dataclass
class CorrelationResult:
    """Output of signal correlation for a group of related detections."""

    root_causes: List[DetectionResult] = field(default_factory=list)
    contributing_factors: List[DetectionResult] = field(default_factory=list)
    symptoms: List[DetectionResult] = field(default_factory=list)
    summary: str = ""
    confidence: float = 0.7


# Correlation rules: (cause_type, effect_type) -> True means cause is root cause, effect is symptom
CAUSE_EFFECT_RULES: Dict[str, Dict[str, str]] = {
    # If OOMKill AND CrashLoop → OOMKill is root cause, CrashLoop is symptom
    "OOMKilled": {"CrashLoopBackOff": "root_cause_of"},
    # If missing secret events AND CrashLoop → secret is root cause
    "missing_secret": {"CrashLoopBackOff": "root_cause_of"},
    # Bad image AND CrashLoop/ImagePull → image is root cause
    "ImagePullBackOff": {"CrashLoopBackOff": "root_cause_of"},
    # PVC failure AND pod pending → PVC is root cause
    "PVCFailure": {"PodPending": "root_cause_of"},
    # Node pressure AND pod pending → node is root cause
    "NodePressure": {"PodPending": "root_cause_of"},
    # Service mismatch AND ingress failure → service is root cause
    "ServiceMismatch": {"IngressFailure": "root_cause_of"},
    # Probe failure is a symptom of app issues
    "ProbeFailure": {"CrashLoopBackOff": "symptom_of"},
}

SIGNAL_KEYWORDS = {
    "missing_secret": [
        "secret",
        "not found",
        "secretKeyRef",
        "secretRef",
        "no such file",
        "failed to load config",
        "environment variable",
    ],
    "missing_configmap": [
        "configmap",
        "configmapkeyref",
        "config not found",
    ],
    "oom": ["oomkilled", "out of memory", "memory limit", "exit code 137"],
    "image_issue": [
        "imagepullbackoff",
        "errimagepull",
        "not found in registry",
        "manifest unknown",
        "invalid reference format",
    ],
    "probe_failure": ["readiness probe", "liveness probe", "probe failed"],
    "resource_quota": ["exceeded quota", "insufficient", "resource quota"],
    "node_pressure": ["node pressure", "memory pressure", "disk pressure"],
    "rollout": ["scaled up replica set", "rollout", "updated deployment", "new replicaset"],
}


class SignalCorrelator:
    """Correlates detected signals and classifies each as root cause, contributing factor, or symptom."""

    def correlate(
        self,
        detections: List[DetectionResult],
        cluster_state: Dict[str, Any],
        raw_signals: Optional[Dict[str, Any]] = None,
    ) -> CorrelationResult:
        """Analyse all detections and classify signals by causal role.

        Args:
            detections: List of DetectionResult from all detectors.
            cluster_state: Full cluster state dict.
            raw_signals: Optional raw incident signals for text analysis.

        Returns:
            CorrelationResult with classified signals.
        """
        result = CorrelationResult()

        if not detections:
            result.summary = "No detections to correlate."
            return result

        detected_types = {d.incident_type for d in detections}

        # Analyse events and raw signals for additional context
        events = cluster_state.get("events", [])
        event_texts = " ".join(
            ev.get("message", "") + " " + ev.get("reason", "") for ev in events
        ).lower()

        raw_text = ""
        if raw_signals:
            logs = raw_signals.get("recent_logs", [])
            raw_text = " ".join(str(x) for x in logs).lower()
            changes = raw_signals.get("recent_changes", [])
            for ch in changes:
                raw_text += " " + ch.get("message", "").lower()

        combined_text = event_texts + " " + raw_text

        # Detect hidden signals from text analysis
        detected_hidden = set()
        for signal, keywords in SIGNAL_KEYWORDS.items():
            if any(kw in combined_text for kw in keywords):
                detected_hidden.add(signal)

        logger.debug("Hidden signals detected from text: %s", detected_hidden)

        # Apply correlation rules
        classified: Dict[str, str] = {}  # incident_type -> role

        for det in detections:
            classified[det.incident_type] = "root_cause"  # default assumption

        # OOMKill causes CrashLoop
        if "OOMKilled" in detected_types and "CrashLoopBackOff" in detected_types:
            classified["OOMKilled"] = "root_cause"
            classified["CrashLoopBackOff"] = "symptom"

        # Missing secret causes CrashLoop
        if "missing_secret" in detected_hidden and "CrashLoopBackOff" in detected_types:
            classified["CrashLoopBackOff"] = "symptom"
            # Add a synthetic root cause
            result.summary = (
                "Root cause is a missing Kubernetes Secret referenced by the pod. "
                "The application cannot start without the required credentials, causing the CrashLoop."
            )

        # ImagePull causes CrashLoop (if both present)
        if "ImagePullBackOff" in detected_types and "CrashLoopBackOff" in detected_types:
            classified["ImagePullBackOff"] = "root_cause"
            classified["CrashLoopBackOff"] = "symptom"

        # PVC failure causes pod pending
        if "PVCFailure" in detected_types and "PodPending" in detected_types:
            classified["PVCFailure"] = "root_cause"
            classified["PodPending"] = "symptom"

        # Service mismatch contributes to ingress failure
        if "ServiceMismatch" in detected_types and "IngressFailure" in detected_types:
            classified["ServiceMismatch"] = "root_cause"
            classified["IngressFailure"] = "symptom"

        # Probe failures are symptoms of the underlying app crash
        if "ProbeFailure" in detected_types and "CrashLoopBackOff" in detected_types:
            classified["ProbeFailure"] = "symptom"

        # Recent rollout as contributing factor
        if "rollout" in detected_hidden:
            for det in detections:
                if classified.get(det.incident_type) == "root_cause":
                    # Rollout is a contributing factor that triggered the root cause
                    pass  # We'll note it in the summary

        # Distribute detections into categories
        for det in detections:
            role = classified.get(det.incident_type, "root_cause")
            if role == "root_cause":
                result.root_causes.append(det)
            elif role == "symptom":
                result.symptoms.append(det)
            else:
                result.contributing_factors.append(det)

        # Build summary if not already set
        if not result.summary:
            if result.root_causes:
                rc_types = [d.incident_type for d in result.root_causes]
                sym_types = [d.incident_type for d in result.symptoms]
                factors = list(
                    detected_hidden.intersection(
                        {"missing_secret", "missing_configmap", "rollout", "resource_quota"}
                    )
                )
                parts = [f"Root cause(s): {', '.join(rc_types)}"]
                if sym_types:
                    parts.append(f"symptoms: {', '.join(sym_types)}")
                if factors:
                    parts.append(f"contributing factors: {', '.join(factors)}")
                result.summary = "; ".join(parts)
            else:
                result.summary = "Could not determine clear root cause from available signals."

        # Adjust confidence based on how many signals were found
        evidence_count = sum(len(d.evidence) for d in detections)
        result.confidence = min(0.95, 0.5 + evidence_count * 0.05)

        # Boost confidence if missing_secret or oom clearly detected
        if "missing_secret" in detected_hidden or "oom" in detected_hidden:
            result.confidence = min(0.95, result.confidence + 0.15)

        logger.info(
            "Correlation complete: %d root causes, %d symptoms, %d contributing factors",
            len(result.root_causes),
            len(result.symptoms),
            len(result.contributing_factors),
        )
        return result
