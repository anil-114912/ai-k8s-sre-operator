"""Tests for the 9 new incident detectors added in the Hybrid Learning Architecture."""

from __future__ import annotations

from detectors import ALL_DETECTORS, run_all_detectors
from detectors.cni_detector import CNIDetector
from detectors.dns_detector import DNSDetector
from detectors.network_policy_detector import NetworkPolicyDetector
from detectors.node_pressure_detector import NodePressureDetector
from detectors.quota_detector import QuotaDetector
from detectors.rbac_detector import RBACDetector
from detectors.rollout_detector import RolloutDetector
from detectors.service_mesh_detector import ServiceMeshDetector
from detectors.storage_detector import StorageDetector

# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------


def empty_cluster_state():
    """Return a fully empty cluster state for negative test cases."""
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
        "network_policies": [],
        "storage_classes": [],
    }


def make_event(
    reason,
    message,
    namespace="default",
    involved_name="test-pod",
    involved_kind="Pod",
    event_type="Warning",
):
    """Build a minimal K8s event dict."""
    return {
        "reason": reason,
        "message": message,
        "type": event_type,
        "namespace": namespace,
        "involvedObject": {"name": involved_name, "kind": involved_kind, "namespace": namespace},
        "count": 1,
    }


def make_node(
    name="node-1",
    ready=True,
    memory_pressure=False,
    disk_pressure=False,
    pid_pressure=False,
    conditions=None,
):
    """Build a minimal node dict."""
    return {
        "name": name,
        "ready": ready,
        "memory_pressure": memory_pressure,
        "disk_pressure": disk_pressure,
        "pid_pressure": pid_pressure,
        "conditions": conditions or [],
    }


def make_deployment(
    name,
    namespace="default",
    available_false=False,
    progress_deadline_exceeded=False,
    desired=2,
    available=0,
    unavailable=2,
):
    """Build a minimal deployment dict."""
    conditions = []
    if available_false:
        conditions.append(
            {"type": "Available", "status": "False", "reason": "MinimumReplicasUnavailable"}
        )
    if progress_deadline_exceeded:
        conditions.append(
            {"type": "Progressing", "status": "False", "reason": "ProgressDeadlineExceeded"}
        )
    return {
        "name": name,
        "namespace": namespace,
        "conditions": conditions,
        "replicas": desired,
        "desiredReplicas": desired,
        "availableReplicas": available,
        "unavailableReplicas": unavailable,
    }


# ---------------------------------------------------------------------------
# QuotaDetector
# ---------------------------------------------------------------------------


class TestQuotaDetector:
    """Tests for QuotaDetector."""

    def test_detects_exceeded_quota_event(self):
        """Should detect FailedCreate event with exceeded quota message."""
        state = empty_cluster_state()
        state["events"] = [
            make_event(
                reason="FailedCreate",
                message="exceeded quota: compute-resources, requested: requests.cpu=500m, "
                "used: requests.cpu=9500m, limited: requests.cpu=10000m",
                namespace="production",
            )
        ]
        detector = QuotaDetector()
        results = detector.detect(state)
        assert len(results) == 1
        assert results[0].detected is True
        assert results[0].incident_type == "QuotaExceeded"
        assert results[0].namespace == "production"

    def test_no_detection_for_normal_create(self):
        """Should not fire on non-FailedCreate events."""
        state = empty_cluster_state()
        state["events"] = [
            make_event(reason="Scheduled", message="Successfully assigned pod to node")
        ]
        detector = QuotaDetector()
        results = detector.detect(state)
        assert results == []

    def test_extracts_resource_type_cpu(self):
        """Should extract 'cpu' as resource type from quota message."""
        state = empty_cluster_state()
        state["events"] = [
            make_event(
                reason="FailedCreate",
                message="exceeded quota: my-quota, requested: requests.cpu=1, limited: requests.cpu=5",
                namespace="test",
            )
        ]
        detector = QuotaDetector()
        results = detector.detect(state)
        assert len(results) == 1
        assert "cpu" in results[0].raw_signals.get("resource_type", "")


# ---------------------------------------------------------------------------
# DNSDetector
# ---------------------------------------------------------------------------


class TestDNSDetector:
    """Tests for DNSDetector."""

    def test_detects_dns_failure_in_logs(self):
        """Should detect 'no such host' in pod logs."""
        state = empty_cluster_state()
        state["recent_logs"] = {
            "production/api-abc-xyz/app": [
                "2024-01-15T10:00:00Z ERROR dial tcp: lookup db-service.production: no such host",
                "2024-01-15T10:00:01Z ERROR failed to connect to database",
            ]
        }
        detector = DNSDetector()
        results = detector.detect(state)
        assert len(results) >= 1
        assert results[0].incident_type == "DNSFailure"
        assert results[0].namespace == "production"

    def test_detects_coredns_crashloop(self):
        """Should detect unhealthy CoreDNS pod as a DNS failure."""
        state = empty_cluster_state()
        state["pods"] = [
            {
                "name": "coredns-abc-xyz",
                "namespace": "kube-system",
                "phase": "Running",
                "labels": {"k8s-app": "kube-dns"},
                "container_statuses": [
                    {
                        "name": "coredns",
                        "restartCount": 5,
                        "state": {"waiting": {"reason": "CrashLoopBackOff"}},
                    }
                ],
            }
        ]
        detector = DNSDetector()
        results = detector.detect(state)
        assert len(results) >= 1
        assert results[0].incident_type == "DNSFailure"
        assert results[0].severity == "critical"

    def test_no_detection_clean_state(self):
        """Should not fire when no DNS errors are present."""
        state = empty_cluster_state()
        state["recent_logs"] = {
            "default/app-abc-xyz/app": ["INFO Connected to db-service successfully"]
        }
        detector = DNSDetector()
        results = detector.detect(state)
        assert results == []


# ---------------------------------------------------------------------------
# RBACDetector
# ---------------------------------------------------------------------------


class TestRBACDetector:
    """Tests for RBACDetector."""

    def test_detects_forbidden_event(self):
        """Should detect Forbidden reason events."""
        state = empty_cluster_state()
        state["events"] = [
            make_event(
                reason="Forbidden",
                message="serviceaccounts 'default' cannot get resource 'secrets' in namespace 'production': RBAC denied",
                namespace="production",
            )
        ]
        detector = RBACDetector()
        results = detector.detect(state)
        assert len(results) >= 1
        assert results[0].incident_type == "RBACDenied"

    def test_detects_rbac_in_pod_logs(self):
        """Should detect 'is not allowed' RBAC error in pod logs."""
        state = empty_cluster_state()
        state["recent_logs"] = {
            "production/operator-abc-xyz/operator": [
                "ERROR: User 'system:serviceaccount:production:operator' is not allowed to list pods",
            ]
        }
        detector = RBACDetector()
        results = detector.detect(state)
        assert len(results) >= 1
        assert results[0].incident_type == "RBACDenied"

    def test_no_detection_clean_events(self):
        """Should not fire on normal events."""
        state = empty_cluster_state()
        state["events"] = [make_event(reason="Scheduled", message="Successfully assigned pod")]
        detector = RBACDetector()
        results = detector.detect(state)
        assert results == []


# ---------------------------------------------------------------------------
# NetworkPolicyDetector
# ---------------------------------------------------------------------------


class TestNetworkPolicyDetector:
    """Tests for NetworkPolicyDetector."""

    def test_detects_connection_timeout_in_logs(self):
        """Should detect connection timeout errors in pod logs."""
        state = empty_cluster_state()
        state["recent_logs"] = {
            "production/frontend-abc-xyz/app": [
                "ERROR: dial tcp 10.0.0.5:8080: connect: connection timed out after 30s",
            ]
        }
        detector = NetworkPolicyDetector()
        results = detector.detect(state)
        assert len(results) >= 1
        assert results[0].incident_type == "NetworkPolicyBlock"

    def test_higher_severity_with_network_policy_present(self):
        """Severity should be 'high' when NetworkPolicy objects exist in the namespace."""
        state = empty_cluster_state()
        state["recent_logs"] = {
            "production/frontend-abc/app": [
                "ERROR connection timed out to backend",
            ]
        }
        state["network_policies"] = [{"name": "deny-all", "namespace": "production"}]
        detector = NetworkPolicyDetector()
        results = detector.detect(state)
        assert len(results) >= 1
        assert results[0].severity == "high"

    def test_no_detection_clean_logs(self):
        """Should not fire on clean logs."""
        state = empty_cluster_state()
        state["recent_logs"] = {
            "default/app-abc/app": ["INFO: Request processed successfully in 12ms"]
        }
        detector = NetworkPolicyDetector()
        results = detector.detect(state)
        assert results == []


# ---------------------------------------------------------------------------
# CNIDetector
# ---------------------------------------------------------------------------


class TestCNIDetector:
    """Tests for CNIDetector."""

    def test_detects_cni_event(self):
        """Should detect NetworkPluginNotReady event."""
        state = empty_cluster_state()
        state["events"] = [
            make_event(
                reason="NetworkPluginNotReady",
                message="network plugin is not ready: cni plugin not initialized",
                namespace="default",
                involved_name="node-1",
                involved_kind="Node",
            )
        ]
        detector = CNIDetector()
        results = detector.detect(state)
        assert len(results) >= 1
        assert results[0].incident_type == "CNIFailure"

    def test_detects_ip_exhaustion_event(self):
        """Should detect IP exhaustion from CIDR exhausted message."""
        state = empty_cluster_state()
        state["events"] = [
            make_event(
                reason="FailedCreatePodSandBox",
                message="Failed to create pod sandbox: failed to allocate IP: CIDR exhausted",
                namespace="default",
            )
        ]
        detector = CNIDetector()
        results = detector.detect(state)
        assert len(results) >= 1
        assert results[0].severity in ("critical", "high")

    def test_no_detection_clean_state(self):
        """Should not fire when no CNI errors are present."""
        state = empty_cluster_state()
        state["events"] = [
            make_event(reason="Pulled", message="Successfully pulled image 'nginx:latest'")
        ]
        detector = CNIDetector()
        results = detector.detect(state)
        assert results == []


# ---------------------------------------------------------------------------
# ServiceMeshDetector
# ---------------------------------------------------------------------------


class TestServiceMeshDetector:
    """Tests for ServiceMeshDetector."""

    def test_detects_upstream_connect_error_in_logs(self):
        """Should detect 'upstream connect error' in Envoy proxy logs."""
        state = empty_cluster_state()
        state["recent_logs"] = {
            "production/api-abc-xyz/istio-proxy": [
                "[2024-01-15T10:00:00.000Z] 'GET /api/v1/health' upstream connect error or disconnect/reset before headers",
                "503 Service Unavailable upstream connect error",
            ]
        }
        detector = ServiceMeshDetector()
        results = detector.detect(state)
        assert len(results) >= 1
        assert results[0].incident_type == "ServiceMeshFailure"

    def test_detects_circuit_breaker_in_logs(self):
        """Should detect circuit breaker events in Envoy logs."""
        state = empty_cluster_state()
        state["recent_logs"] = {
            "production/svc-abc-xyz/envoy": [
                "upstream: circuit breaker opened for cluster payment-service",
                "pending_failure_eject: consecutive errors exceeded threshold",
            ]
        }
        detector = ServiceMeshDetector()
        results = detector.detect(state)
        assert len(results) >= 1
        assert results[0].incident_type == "ServiceMeshFailure"
        assert results[0].severity == "high"

    def test_detects_mtls_error_in_logs(self):
        """Should detect mTLS handshake errors."""
        state = empty_cluster_state()
        state["recent_logs"] = {
            "production/app-abc/app": [
                "TLS handshake error: certificate verify failed",
                "peer certificate not trusted",
            ]
        }
        detector = ServiceMeshDetector()
        results = detector.detect(state)
        assert len(results) >= 1

    def test_no_detection_clean_state(self):
        """Should not fire on clean pod logs."""
        state = empty_cluster_state()
        state["recent_logs"] = {"default/app-abc/app": ["INFO: Serving request successfully"]}
        detector = ServiceMeshDetector()
        results = detector.detect(state)
        assert results == []


# ---------------------------------------------------------------------------
# NodePressureDetector
# ---------------------------------------------------------------------------


class TestNodePressureDetector:
    """Tests for NodePressureDetector."""

    def test_detects_memory_pressure(self):
        """Should detect MemoryPressure=True on a node."""
        state = empty_cluster_state()
        state["nodes"] = [make_node(name="node-1", memory_pressure=True)]
        detector = NodePressureDetector()
        results = detector.detect(state)
        assert len(results) == 1
        assert results[0].incident_type == "NodePressure"
        assert "MemoryPressure" in results[0].raw_signals["pressure_conditions"]

    def test_detects_disk_pressure(self):
        """Should detect DiskPressure=True on a node."""
        state = empty_cluster_state()
        state["nodes"] = [make_node(name="node-2", disk_pressure=True)]
        detector = NodePressureDetector()
        results = detector.detect(state)
        assert len(results) == 1
        assert "DiskPressure" in results[0].raw_signals["pressure_conditions"]

    def test_detects_not_ready_node(self):
        """Should detect a NotReady node with critical severity."""
        state = empty_cluster_state()
        state["nodes"] = [make_node(name="node-3", ready=False)]
        detector = NodePressureDetector()
        results = detector.detect(state)
        assert len(results) == 1
        assert results[0].severity == "critical"

    def test_detects_pressure_from_conditions_array(self):
        """Should detect pressure from the conditions array too."""
        state = empty_cluster_state()
        state["nodes"] = [
            make_node(
                name="node-4",
                conditions=[{"type": "PIDPressure", "status": "True", "reason": "PIDPressure"}],
            )
        ]
        detector = NodePressureDetector()
        results = detector.detect(state)
        assert len(results) == 1
        assert "PIDPressure" in results[0].raw_signals["pressure_conditions"]

    def test_no_detection_healthy_node(self):
        """Should not fire on a healthy node."""
        state = empty_cluster_state()
        state["nodes"] = [make_node(name="node-5", ready=True)]
        detector = NodePressureDetector()
        results = detector.detect(state)
        assert results == []


# ---------------------------------------------------------------------------
# StorageDetector
# ---------------------------------------------------------------------------


class TestStorageDetector:
    """Tests for StorageDetector."""

    def test_detects_failed_mount_event(self):
        """Should detect FailedMount events."""
        state = empty_cluster_state()
        state["events"] = [
            make_event(
                reason="FailedMount",
                message="Unable to attach or mount volumes: timed out waiting for the condition",
                namespace="production",
                involved_name="data-pipeline-abc-xyz",
            )
        ]
        detector = StorageDetector()
        results = detector.detect(state)
        assert len(results) == 1
        assert results[0].incident_type == "StorageFailure"

    def test_detects_failed_attach_volume_event(self):
        """Should detect FailedAttachVolume events with high severity."""
        state = empty_cluster_state()
        state["events"] = [
            make_event(
                reason="FailedAttachVolume",
                message="AttachVolume.Attach failed for volume 'pvc-abc': VolumeNotFound",
                namespace="production",
            )
        ]
        detector = StorageDetector()
        results = detector.detect(state)
        assert len(results) == 1
        assert results[0].severity == "high"

    def test_detects_missing_storage_class(self):
        """Should detect PVCs that reference non-existent StorageClass."""
        state = empty_cluster_state()
        state["pvcs"] = [
            {
                "name": "data-pvc",
                "namespace": "production",
                "phase": "Pending",
                "storageClassName": "fast-ssd-nonexistent",
            }
        ]
        state["storage_classes"] = [
            {"name": "standard"},
            {"name": "gp2"},
        ]
        detector = StorageDetector()
        results = detector.detect(state)
        assert len(results) == 1
        assert results[0].raw_signals["issue_type"] == "storageclass_missing"

    def test_no_detection_clean_state(self):
        """Should not fire when no storage errors are present."""
        state = empty_cluster_state()
        state["events"] = [make_event(reason="Pulled", message="Successfully pulled image")]
        state["pvcs"] = [{"name": "data-pvc", "namespace": "prod", "phase": "Bound"}]
        detector = StorageDetector()
        results = detector.detect(state)
        assert results == []


# ---------------------------------------------------------------------------
# RolloutDetector
# ---------------------------------------------------------------------------


class TestRolloutDetector:
    """Tests for RolloutDetector."""

    def test_detects_progress_deadline_exceeded(self):
        """Should detect ProgressDeadlineExceeded deployment condition."""
        state = empty_cluster_state()
        state["deployments"] = [
            make_deployment(
                name="payment-api",
                namespace="production",
                progress_deadline_exceeded=True,
            )
        ]
        detector = RolloutDetector()
        results = detector.detect(state)
        assert len(results) == 1
        assert results[0].incident_type == "FailedRollout"
        assert results[0].severity == "critical"

    def test_detects_available_false(self):
        """Should detect Available=False deployment condition."""
        state = empty_cluster_state()
        state["deployments"] = [
            make_deployment(
                name="frontend",
                namespace="staging",
                available_false=True,
            )
        ]
        detector = RolloutDetector()
        results = detector.detect(state)
        assert len(results) == 1
        assert results[0].incident_type == "FailedRollout"

    def test_no_detection_healthy_deployment(self):
        """Should not fire on a healthy deployment."""
        state = empty_cluster_state()
        state["deployments"] = [
            {
                "name": "api",
                "namespace": "prod",
                "conditions": [
                    {"type": "Available", "status": "True"},
                    {"type": "Progressing", "status": "True", "reason": "NewReplicaSetAvailable"},
                ],
                "replicas": 3,
                "desiredReplicas": 3,
                "availableReplicas": 3,
                "unavailableReplicas": 0,
            }
        ]
        detector = RolloutDetector()
        results = detector.detect(state)
        assert results == []

    def test_raw_signals_contain_replica_counts(self):
        """Raw signals should include desired, available, and unavailable counts."""
        state = empty_cluster_state()
        state["deployments"] = [
            make_deployment(
                name="api",
                namespace="prod",
                available_false=True,
                desired=5,
                available=2,
                unavailable=3,
            )
        ]
        detector = RolloutDetector()
        results = detector.detect(state)
        assert len(results) == 1
        signals = results[0].raw_signals
        assert signals["desired_replicas"] == 5
        assert signals["available_replicas"] == 2
        assert signals["unavailable_replicas"] == 3


# ---------------------------------------------------------------------------
# All detectors — run_all_detectors integration test
# ---------------------------------------------------------------------------


class TestRunAllDetectors:
    """Tests for the run_all_detectors() function and ALL_DETECTORS list."""

    def test_all_detectors_count_is_18(self):
        """ALL_DETECTORS should contain exactly 18 detectors."""
        assert len(ALL_DETECTORS) == 18

    def test_run_all_detectors_empty_state_no_crash(self):
        """run_all_detectors with empty state should return empty list without crashing."""
        state = empty_cluster_state()
        results = run_all_detectors(state)
        assert isinstance(results, list)
        assert results == []

    def test_run_all_detectors_returns_combined_results(self):
        """run_all_detectors should aggregate results from all detectors."""
        state = empty_cluster_state()
        # Trigger multiple detectors
        state["events"] = [
            make_event(
                reason="FailedCreate",
                message="exceeded quota: compute-resources, requests.cpu=500m limited: 10",
                namespace="production",
            ),
            make_event(
                reason="FailedMount",
                message="Unable to attach or mount volumes: timed out",
                namespace="production",
            ),
        ]
        state["nodes"] = [make_node(name="node-1", memory_pressure=True)]
        results = run_all_detectors(state)
        assert len(results) >= 3

    def test_run_all_detectors_all_have_names(self):
        """Every detector in ALL_DETECTORS should have a non-empty name."""
        for d in ALL_DETECTORS:
            assert d.name, f"Detector {type(d).__name__} has no name"
            assert d.description, f"Detector {type(d).__name__} has no description"
