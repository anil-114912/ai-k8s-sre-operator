"""Tests for all incident detectors."""

from __future__ import annotations

from detectors.crashloop_detector import CrashLoopDetector
from detectors.hpa_detector import HPADetector
from detectors.imagepull_detector import ImagePullDetector
from detectors.ingress_detector import IngressDetector
from detectors.oomkill_detector import OOMKillDetector
from detectors.pending_pods_detector import PendingPodsDetector
from detectors.probe_failure_detector import ProbeFailureDetector
from detectors.pvc_detector import PVCDetector
from detectors.service_detector import ServiceDetector

# ---------------------------------------------------------------------------
# Shared fixtures
# ---------------------------------------------------------------------------


def empty_cluster_state():
    """Return an empty cluster state dict for negative test cases."""
    return {
        "pods": [],
        "events": [],
        "deployments": [],
        "services": [],
        "endpoints": [],
        "ingresses": [],
        "nodes": [],
        "hpas": [],
        "pvcs": [],
        "recent_logs": {},
    }


def make_pod(
    name="test-pod",
    namespace="default",
    phase="Running",
    container_name="app",
    restart_count=0,
    waiting_reason="",
    waiting_message="",
    last_terminated_reason="",
    last_terminated_exit_code=0,
    image="myapp:latest",
    memory_limit="256Mi",
):
    """Build a minimal pod dict for testing."""
    state = {}
    if waiting_reason:
        state["waiting"] = {"reason": waiting_reason, "message": waiting_message}
    else:
        state["running"] = {}

    last_state = {}
    if last_terminated_reason:
        last_state["terminated"] = {
            "reason": last_terminated_reason,
            "exitCode": last_terminated_exit_code,
            "finishedAt": "2024-01-15T09:00:00Z",
        }

    return {
        "name": name,
        "namespace": namespace,
        "workload": name.rsplit("-", 2)[0] if "-" in name else name,
        "phase": phase,
        "labels": {"app": name.rsplit("-", 2)[0] if "-" in name else name},
        "container_statuses": [
            {
                "name": container_name,
                "restartCount": restart_count,
                "state": state,
                "lastState": last_state,
            }
        ],
        "containers": [
            {
                "name": container_name,
                "image": image,
                "resources": {
                    "limits": {"memory": memory_limit, "cpu": "500m"},
                    "requests": {"memory": "128Mi", "cpu": "250m"},
                },
            }
        ],
    }


# ---------------------------------------------------------------------------
# CrashLoop detector tests
# ---------------------------------------------------------------------------


class TestCrashLoopDetector:
    """Tests for CrashLoopDetector."""

    def test_detects_crashloopbackoff(self):
        """Should detect a pod in CrashLoopBackOff state."""
        state = empty_cluster_state()
        state["pods"] = [
            make_pod(
                name="payment-api-abc-xyz",
                namespace="production",
                waiting_reason="CrashLoopBackOff",
                waiting_message="back-off 5m0s",
                restart_count=10,
            )
        ]
        detector = CrashLoopDetector()
        results = detector.detect(state)
        assert len(results) == 1
        assert results[0].detected is True
        assert results[0].incident_type == "CrashLoopBackOff"
        assert results[0].severity == "critical"

    def test_detects_high_restart_count(self):
        """Should detect a pod with restart count > threshold even without CrashLoop state."""
        state = empty_cluster_state()
        state["pods"] = [make_pod(name="worker-abc-xyz", restart_count=8)]
        detector = CrashLoopDetector()
        results = detector.detect(state)
        assert len(results) == 1
        assert results[0].detected is True

    def test_no_detection_for_healthy_pod(self):
        """Should not detect anything for a healthy, non-restarting pod."""
        state = empty_cluster_state()
        state["pods"] = [make_pod(name="healthy-abc-xyz", restart_count=0)]
        detector = CrashLoopDetector()
        results = detector.detect(state)
        assert results == []

    def test_evidence_contains_restart_count(self):
        """Evidence should mention the restart count."""
        state = empty_cluster_state()
        state["pods"] = [
            make_pod(
                name="api-abc-xyz",
                waiting_reason="CrashLoopBackOff",
                restart_count=15,
            )
        ]
        detector = CrashLoopDetector()
        results = detector.detect(state)
        assert any("15" in ev.content for ev in results[0].evidence)


# ---------------------------------------------------------------------------
# OOMKill detector tests
# ---------------------------------------------------------------------------


class TestOOMKillDetector:
    """Tests for OOMKillDetector."""

    def test_detects_oom_in_last_state(self):
        """Should detect OOMKill from lastState.terminated.reason."""
        state = empty_cluster_state()
        state["pods"] = [
            make_pod(
                name="worker-abc-xyz",
                last_terminated_reason="OOMKilled",
                last_terminated_exit_code=137,
            )
        ]
        detector = OOMKillDetector()
        results = detector.detect(state)
        assert len(results) == 1
        assert results[0].incident_type == "OOMKilled"

    def test_detects_oom_in_current_state(self):
        """Should detect OOMKill from current state.terminated.reason."""
        pod = make_pod(name="worker-abc-xyz")
        pod["container_statuses"][0]["state"] = {
            "terminated": {"reason": "OOMKilled", "exitCode": 137}
        }
        state = empty_cluster_state()
        state["pods"] = [pod]
        detector = OOMKillDetector()
        results = detector.detect(state)
        assert len(results) == 1

    def test_no_detection_for_normal_exit(self):
        """Should not detect OOM for a pod with normal termination."""
        state = empty_cluster_state()
        state["pods"] = [make_pod(name="worker-abc-xyz", last_terminated_reason="Completed")]
        detector = OOMKillDetector()
        results = detector.detect(state)
        assert results == []

    def test_evidence_contains_limits(self):
        """Evidence should include memory limits information."""
        state = empty_cluster_state()
        state["pods"] = [
            make_pod(
                name="worker-abc-xyz",
                last_terminated_reason="OOMKilled",
                memory_limit="256Mi",
            )
        ]
        detector = OOMKillDetector()
        results = detector.detect(state)
        assert any("256Mi" in ev.content for ev in results[0].evidence)


# ---------------------------------------------------------------------------
# ImagePull detector tests
# ---------------------------------------------------------------------------


class TestImagePullDetector:
    """Tests for ImagePullDetector."""

    def test_detects_imagepullbackoff(self):
        """Should detect ImagePullBackOff waiting state."""
        state = empty_cluster_state()
        state["pods"] = [
            make_pod(
                name="app-abc-xyz",
                namespace="staging",
                waiting_reason="ImagePullBackOff",
                waiting_message='Back-off pulling image "badimage:notfound"',
                image="badimage:notfound",
            )
        ]
        detector = ImagePullDetector()
        results = detector.detect(state)
        assert len(results) == 1
        assert results[0].incident_type == "ImagePullBackOff"

    def test_detects_errimagepull(self):
        """Should detect ErrImagePull reason."""
        state = empty_cluster_state()
        state["pods"] = [
            make_pod(
                name="app-abc-xyz",
                waiting_reason="ErrImagePull",
                image="registry.io/app:bad-tag",
            )
        ]
        detector = ImagePullDetector()
        results = detector.detect(state)
        assert len(results) == 1

    def test_no_detection_for_running_pod(self):
        """Should not detect image pull errors for a running pod."""
        state = empty_cluster_state()
        state["pods"] = [make_pod(name="app-abc-xyz")]
        detector = ImagePullDetector()
        results = detector.detect(state)
        assert results == []


# ---------------------------------------------------------------------------
# Pending pods detector tests
# ---------------------------------------------------------------------------


class TestPendingPodsDetector:
    """Tests for PendingPodsDetector."""

    def test_detects_long_pending_pod(self):
        """Should detect pods pending beyond the threshold."""
        from datetime import datetime, timedelta, timezone

        old_ts = (datetime.now(timezone.utc) - timedelta(minutes=10)).isoformat()
        state = empty_cluster_state()
        pod = make_pod(name="data-abc-xyz", phase="Pending")
        pod["creationTimestamp"] = old_ts
        pod["container_statuses"] = []
        state["pods"] = [pod]
        state["events"] = [
            {
                "reason": "FailedScheduling",
                "message": "Insufficient memory",
                "type": "Warning",
                "involvedObject": {"name": "data-abc-xyz", "kind": "Pod"},
                "namespace": "default",
            }
        ]
        detector = PendingPodsDetector()
        results = detector.detect(state)
        assert len(results) == 1
        assert results[0].incident_type == "PodPending"

    def test_no_detection_for_recently_pending_pod(self):
        """Should not flag pods that just recently entered Pending state."""
        from datetime import datetime, timedelta, timezone

        recent_ts = (datetime.now(timezone.utc) - timedelta(seconds=30)).isoformat()
        state = empty_cluster_state()
        pod = make_pod(name="data-abc-xyz", phase="Pending")
        pod["creationTimestamp"] = recent_ts
        pod["container_statuses"] = []
        state["pods"] = [pod]
        detector = PendingPodsDetector()
        results = detector.detect(state)
        assert results == []

    def test_no_detection_for_running_pod(self):
        """Should not detect running pods as pending."""
        state = empty_cluster_state()
        state["pods"] = [make_pod(name="app-abc-xyz", phase="Running")]
        detector = PendingPodsDetector()
        results = detector.detect(state)
        assert results == []


# ---------------------------------------------------------------------------
# Probe failure detector tests
# ---------------------------------------------------------------------------


class TestProbeFailureDetector:
    """Tests for ProbeFailureDetector."""

    def test_detects_readiness_probe_failure(self):
        """Should detect readiness probe failures from events."""
        state = empty_cluster_state()
        state["events"] = [
            {
                "reason": "Unhealthy",
                "message": "Readiness probe failed: HTTP probe failed with statuscode: 503",
                "type": "Warning",
                "count": 5,
                "involvedObject": {
                    "name": "frontend-abc-xyz",
                    "kind": "Pod",
                    "namespace": "production",
                },
                "namespace": "production",
            }
        ]
        detector = ProbeFailureDetector()
        results = detector.detect(state)
        assert len(results) == 1
        assert results[0].incident_type == "ProbeFailure"

    def test_no_detection_for_non_unhealthy_events(self):
        """Should not trigger on normal events."""
        state = empty_cluster_state()
        state["events"] = [
            {
                "reason": "Scheduled",
                "message": "Successfully assigned pod to node",
                "type": "Normal",
                "count": 1,
                "involvedObject": {"name": "frontend-abc-xyz", "kind": "Pod"},
                "namespace": "production",
            }
        ]
        detector = ProbeFailureDetector()
        results = detector.detect(state)
        assert results == []


# ---------------------------------------------------------------------------
# Service detector tests
# ---------------------------------------------------------------------------


class TestServiceDetector:
    """Tests for ServiceDetector."""

    def test_detects_service_with_no_matching_pods(self):
        """Should detect a service whose selector matches no running pods."""
        state = empty_cluster_state()
        state["services"] = [
            {
                "name": "orphaned-svc",
                "namespace": "staging",
                "type": "ClusterIP",
                "selector": {"app": "old-service", "version": "v1"},
            }
        ]
        state["pods"] = [make_pod(name="new-service-abc-xyz", namespace="staging")]
        detector = ServiceDetector()
        results = detector.detect(state)
        assert len(results) == 1
        assert results[0].incident_type == "ServiceMismatch"

    def test_no_detection_for_matched_service(self):
        """Should not detect a service that has matching pods."""
        state = empty_cluster_state()
        state["services"] = [
            {
                "name": "frontend-svc",
                "namespace": "production",
                "type": "ClusterIP",
                "selector": {"app": "frontend"},
            }
        ]
        state["pods"] = [
            {
                "name": "frontend-abc-xyz",
                "namespace": "production",
                "workload": "frontend",
                "phase": "Running",
                "labels": {"app": "frontend"},
                "container_statuses": [],
                "containers": [],
            }
        ]
        detector = ServiceDetector()
        results = detector.detect(state)
        assert results == []


# ---------------------------------------------------------------------------
# Ingress detector tests
# ---------------------------------------------------------------------------


class TestIngressDetector:
    """Tests for IngressDetector."""

    def test_detects_missing_backend_service(self):
        """Should detect an ingress pointing to a non-existent service."""
        state = empty_cluster_state()
        state["ingresses"] = [
            {
                "name": "staging-ingress",
                "namespace": "staging",
                "rules": [
                    {
                        "host": "staging.example.com",
                        "http": {
                            "paths": [
                                {
                                    "path": "/",
                                    "backend": {
                                        "service": {
                                            "name": "missing-backend",
                                            "port": {"number": 8080},
                                        }
                                    },
                                }
                            ]
                        },
                    }
                ],
            }
        ]
        state["services"] = []
        detector = IngressDetector()
        results = detector.detect(state)
        assert len(results) == 1
        assert results[0].incident_type == "IngressFailure"

    def test_no_detection_for_valid_ingress(self):
        """Should not detect issues for an ingress with a valid backend."""
        state = empty_cluster_state()
        state["ingresses"] = [
            {
                "name": "prod-ingress",
                "namespace": "production",
                "rules": [
                    {
                        "host": "app.example.com",
                        "http": {
                            "paths": [
                                {
                                    "path": "/",
                                    "backend": {
                                        "service": {"name": "frontend", "port": {"number": 80}}
                                    },
                                }
                            ]
                        },
                    }
                ],
            }
        ]
        state["services"] = [
            {
                "name": "frontend",
                "namespace": "production",
                "type": "ClusterIP",
                "selector": {"app": "frontend"},
            }
        ]
        state["endpoints"] = [
            {
                "name": "frontend",
                "namespace": "production",
                "subsets": [{"addresses": [{"ip": "10.0.0.1"}]}],
            }
        ]
        detector = IngressDetector()
        results = detector.detect(state)
        assert results == []


# ---------------------------------------------------------------------------
# PVC detector tests
# ---------------------------------------------------------------------------


class TestPVCDetector:
    """Tests for PVCDetector."""

    def test_detects_pending_pvc(self):
        """Should detect a PVC in Pending state."""
        state = empty_cluster_state()
        state["pvcs"] = [
            {
                "name": "data-pvc",
                "namespace": "production",
                "phase": "Pending",
                "storageClassName": "fast-ssd",
                "accessModes": ["ReadWriteOnce"],
                "resources": {"requests": {"storage": "100Gi"}},
            }
        ]
        detector = PVCDetector()
        results = detector.detect(state)
        assert len(results) == 1
        assert results[0].incident_type == "PVCFailure"

    def test_detects_failedmount_event(self):
        """Should detect FailedMount events for pods."""
        state = empty_cluster_state()
        state["events"] = [
            {
                "reason": "FailedMount",
                "message": "Unable to attach or mount volumes: timed out waiting for the condition",
                "type": "Warning",
                "involvedObject": {
                    "name": "data-pipeline-abc-xyz",
                    "kind": "Pod",
                    "namespace": "production",
                },
                "namespace": "production",
            }
        ]
        detector = PVCDetector()
        results = detector.detect(state)
        assert len(results) == 1

    def test_no_detection_for_bound_pvc(self):
        """Should not detect a Bound PVC as an issue."""
        state = empty_cluster_state()
        state["pvcs"] = [{"name": "healthy-pvc", "namespace": "production", "phase": "Bound"}]
        detector = PVCDetector()
        results = detector.detect(state)
        assert results == []


# ---------------------------------------------------------------------------
# HPA detector tests
# ---------------------------------------------------------------------------


class TestHPADetector:
    """Tests for HPADetector."""

    def test_detects_locked_hpa(self):
        """Should detect an HPA where min == max replicas."""
        state = empty_cluster_state()
        state["hpas"] = [
            {
                "name": "analytics-hpa",
                "namespace": "production",
                "minReplicas": 5,
                "maxReplicas": 5,
                "currentReplicas": 5,
                "targetCPUUtilizationPercentage": 70,
                "currentCPUUtilizationPercentage": 92,
                "scaleTargetRef": {"name": "analytics-worker"},
                "conditions": [],
            }
        ]
        detector = HPADetector()
        results = detector.detect(state)
        assert len(results) == 1
        assert results[0].incident_type == "HPAMisconfigured"

    def test_detects_saturated_hpa(self):
        """Should detect an HPA at max replicas with high CPU."""
        state = empty_cluster_state()
        state["hpas"] = [
            {
                "name": "api-hpa",
                "namespace": "production",
                "minReplicas": 2,
                "maxReplicas": 10,
                "currentReplicas": 10,
                "targetCPUUtilizationPercentage": 70,
                "currentCPUUtilizationPercentage": 95,
                "scaleTargetRef": {"name": "api"},
                "conditions": [],
            }
        ]
        detector = HPADetector()
        results = detector.detect(state)
        assert len(results) == 1

    def test_no_detection_for_healthy_hpa(self):
        """Should not detect issues for a well-configured HPA with room to scale."""
        state = empty_cluster_state()
        state["hpas"] = [
            {
                "name": "frontend-hpa",
                "namespace": "production",
                "minReplicas": 2,
                "maxReplicas": 10,
                "currentReplicas": 3,
                "targetCPUUtilizationPercentage": 70,
                "currentCPUUtilizationPercentage": 45,
                "scaleTargetRef": {"name": "frontend"},
                "conditions": [{"type": "ScalingActive", "status": "True"}],
            }
        ]
        detector = HPADetector()
        results = detector.detect(state)
        assert results == []
