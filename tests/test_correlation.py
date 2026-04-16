"""Tests for signal correlation logic."""

from __future__ import annotations

from correlation.signal_correlator import SignalCorrelator
from detectors.base import DetectionResult
from models.incident import Evidence


def make_detection(incident_type: str, severity: str = "high") -> DetectionResult:
    """Create a minimal DetectionResult for testing."""
    return DetectionResult(
        detected=True,
        incident_type=incident_type,
        severity=severity,
        reason=f"Detected {incident_type}",
        evidence=[Evidence(source="detector", content=f"Test evidence for {incident_type}")],
        affected_resource="production/test-pod",
        namespace="production",
        workload="test-workload",
    )


class TestSignalCorrelator:
    """Tests for the SignalCorrelator."""

    def test_oomkill_causes_crashloop(self):
        """OOMKill + CrashLoop: OOMKill should be root cause, CrashLoop symptom."""
        correlator = SignalCorrelator()
        detections = [
            make_detection("OOMKilled"),
            make_detection("CrashLoopBackOff"),
        ]
        result = correlator.correlate(detections, {"events": [], "pods": []})
        rc_types = {d.incident_type for d in result.root_causes}
        sym_types = {d.incident_type for d in result.symptoms}
        assert "OOMKilled" in rc_types
        assert "CrashLoopBackOff" in sym_types

    def test_missing_secret_causes_crashloop(self):
        """CrashLoop + secret error in events: CrashLoop should be symptom."""
        correlator = SignalCorrelator()
        detections = [make_detection("CrashLoopBackOff")]
        cluster_state = {
            "events": [
                {
                    "reason": "Failed",
                    "message": 'Error: secret "db-credentials" not found',
                    "type": "Warning",
                }
            ],
            "pods": [],
        }
        result = correlator.correlate(detections, cluster_state)
        # CrashLoop should be classified as symptom
        sym_types = {d.incident_type for d in result.symptoms}
        assert "CrashLoopBackOff" in sym_types

    def test_imagepull_causes_crashloop(self):
        """ImagePull + CrashLoop: ImagePull should be root cause."""
        correlator = SignalCorrelator()
        detections = [
            make_detection("ImagePullBackOff"),
            make_detection("CrashLoopBackOff"),
        ]
        result = correlator.correlate(detections, {"events": [], "pods": []})
        rc_types = {d.incident_type for d in result.root_causes}
        assert "ImagePullBackOff" in rc_types

    def test_pvc_causes_pending(self):
        """PVCFailure + PodPending: PVC should be root cause."""
        correlator = SignalCorrelator()
        detections = [
            make_detection("PVCFailure"),
            make_detection("PodPending"),
        ]
        result = correlator.correlate(detections, {"events": [], "pods": []})
        rc_types = {d.incident_type for d in result.root_causes}
        sym_types = {d.incident_type for d in result.symptoms}
        assert "PVCFailure" in rc_types
        assert "PodPending" in sym_types

    def test_service_causes_ingress_failure(self):
        """ServiceMismatch + IngressFailure: Service should be root cause."""
        correlator = SignalCorrelator()
        detections = [
            make_detection("ServiceMismatch"),
            make_detection("IngressFailure"),
        ]
        result = correlator.correlate(detections, {"events": [], "pods": []})
        rc_types = {d.incident_type for d in result.root_causes}
        sym_types = {d.incident_type for d in result.symptoms}
        assert "ServiceMismatch" in rc_types
        assert "IngressFailure" in sym_types

    def test_single_detection_is_root_cause(self):
        """A single detection with no other signals should be classified as root cause."""
        correlator = SignalCorrelator()
        detections = [make_detection("HPAMisconfigured")]
        result = correlator.correlate(detections, {"events": [], "pods": []})
        assert len(result.root_causes) == 1
        assert result.root_causes[0].incident_type == "HPAMisconfigured"

    def test_empty_detections(self):
        """Empty detection list should return empty correlation result."""
        correlator = SignalCorrelator()
        result = correlator.correlate([], {"events": [], "pods": []})
        assert result.root_causes == []
        assert result.symptoms == []
        assert result.contributing_factors == []

    def test_confidence_is_positive(self):
        """Correlation result should have a positive confidence score."""
        correlator = SignalCorrelator()
        detections = [make_detection("CrashLoopBackOff")]
        result = correlator.correlate(detections, {"events": [], "pods": []})
        assert 0 < result.confidence <= 1.0
