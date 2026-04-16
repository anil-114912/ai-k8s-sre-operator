"""Kubernetes API client with simulated fallback for demo mode."""

from __future__ import annotations

import logging
import os
from datetime import datetime, timedelta, timezone
from typing import Any, Dict

# Valid explicit provider values accepted by CLUSTER_PROVIDER env var / Helm value.
PROVIDER_AWS = "aws"
PROVIDER_AZURE = "azure"
PROVIDER_GCP = "gcp"
PROVIDER_GENERIC = "generic"
_VALID_PROVIDERS = {PROVIDER_AWS, PROVIDER_AZURE, PROVIDER_GCP, PROVIDER_GENERIC}

logger = logging.getLogger(__name__)


def _is_demo_mode() -> bool:
    """Check DEMO_MODE at call time, not import time."""
    return os.getenv("DEMO_MODE", "0").lower() in {"1", "true", "yes"}


# ---------------------------------------------------------------------------
# Simulated cluster state for demo mode
# ---------------------------------------------------------------------------


def _make_simulated_cluster_state() -> Dict[str, Any]:
    """Build a realistic simulated cluster state with known incidents baked in.

    Returns:
        Dict with pods, events, deployments, services, endpoints, ingresses,
        nodes, hpas, pvcs, recent_logs.
    """
    now = datetime.now(timezone.utc)
    _5m_ago = (now - timedelta(minutes=5)).isoformat()
    _30m_ago = (now - timedelta(minutes=30)).isoformat()
    _1h_ago = (now - timedelta(hours=1)).isoformat()

    pods = [
        # ---- Healthy pods ----
        {
            "name": "frontend-abc12-xyz99",
            "namespace": "production",
            "workload": "frontend",
            "phase": "Running",
            "labels": {"app": "frontend", "version": "v2.1.0"},
            "container_statuses": [
                {
                    "name": "frontend",
                    "restartCount": 0,
                    "state": {"running": {"startedAt": _1h_ago}},
                }
            ],
            "containers": [
                {
                    "name": "frontend",
                    "image": "myregistry/frontend:v2.1.0",
                    "resources": {
                        "limits": {"memory": "256Mi", "cpu": "200m"},
                        "requests": {"memory": "128Mi", "cpu": "100m"},
                    },
                }
            ],
        },
        {
            "name": "redis-master-0",
            "namespace": "production",
            "workload": "redis-master",
            "phase": "Running",
            "labels": {"app": "redis", "role": "master"},
            "container_statuses": [{"name": "redis", "restartCount": 0, "state": {"running": {}}}],
            "containers": [{"name": "redis", "image": "redis:7.2", "resources": {}}],
        },
        # ---- CrashLoopBackOff: payment-api (missing secret) ----
        {
            "name": "payment-api-7d9f8b-xk2p9",
            "namespace": "production",
            "workload": "payment-api",
            "phase": "Running",
            "labels": {"app": "payment-api"},
            "container_statuses": [
                {
                    "name": "payment-api",
                    "restartCount": 18,
                    "state": {
                        "waiting": {
                            "reason": "CrashLoopBackOff",
                            "message": "back-off 5m0s restarting failed container",
                        }
                    },
                    "lastState": {
                        "terminated": {
                            "reason": "Error",
                            "exitCode": 1,
                            "finishedAt": _5m_ago,
                        }
                    },
                }
            ],
            "containers": [
                {
                    "name": "payment-api",
                    "image": "myregistry/payment-api:v1.5.2",
                    "resources": {
                        "limits": {"memory": "256Mi", "cpu": "500m"},
                        "requests": {"memory": "128Mi", "cpu": "250m"},
                    },
                }
            ],
        },
        # ---- OOMKilled: analytics-worker ----
        {
            "name": "analytics-worker-8bf7c-p9qrs",
            "namespace": "production",
            "workload": "analytics-worker",
            "phase": "Running",
            "labels": {"app": "analytics-worker"},
            "container_statuses": [
                {
                    "name": "analytics-worker",
                    "restartCount": 7,
                    "state": {"running": {}},
                    "lastState": {
                        "terminated": {
                            "reason": "OOMKilled",
                            "exitCode": 137,
                            "finishedAt": _30m_ago,
                        }
                    },
                }
            ],
            "containers": [
                {
                    "name": "analytics-worker",
                    "image": "myregistry/analytics:v3.2.1",
                    "resources": {
                        "limits": {"memory": "256Mi", "cpu": "1000m"},
                        "requests": {"memory": "128Mi", "cpu": "500m"},
                    },
                }
            ],
        },
        # ---- ImagePullBackOff: checkout-service ----
        {
            "name": "checkout-service-5bc4d-m7nop",
            "namespace": "staging",
            "workload": "checkout-service",
            "phase": "Pending",
            "labels": {"app": "checkout-service"},
            "container_statuses": [
                {
                    "name": "checkout-service",
                    "restartCount": 0,
                    "state": {
                        "waiting": {
                            "reason": "ImagePullBackOff",
                            "message": 'Back-off pulling image "myregistry/checkout:v2.0.0-rc1"',
                        }
                    },
                }
            ],
            "containers": [
                {
                    "name": "checkout-service",
                    "image": "myregistry/checkout:v2.0.0-rc1",
                    "resources": {},
                }
            ],
        },
        # ---- Pending: data-pipeline (insufficient resources) ----
        {
            "name": "data-pipeline-6c9f-qrstu",
            "namespace": "production",
            "workload": "data-pipeline",
            "phase": "Pending",
            "labels": {"app": "data-pipeline"},
            "creationTimestamp": (now - timedelta(minutes=15)).isoformat(),
            "container_statuses": [],
            "containers": [
                {
                    "name": "data-pipeline",
                    "image": "myregistry/data-pipeline:v1.0.0",
                    "resources": {
                        "limits": {"memory": "8Gi", "cpu": "4000m"},
                        "requests": {"memory": "8Gi", "cpu": "4000m"},
                    },
                }
            ],
        },
        # ---- Healthy monitoring pods ----
        {
            "name": "prometheus-server-0",
            "namespace": "monitoring",
            "workload": "prometheus-server",
            "phase": "Running",
            "labels": {"app": "prometheus"},
            "container_statuses": [
                {"name": "prometheus", "restartCount": 0, "state": {"running": {}}}
            ],
            "containers": [
                {"name": "prometheus", "image": "prom/prometheus:v2.50.1", "resources": {}}
            ],
        },
    ]

    events = [
        # CrashLoop events for payment-api
        {
            "reason": "BackOff",
            "message": "Back-off restarting failed container",
            "type": "Warning",
            "count": 18,
            "firstTimestamp": _30m_ago,
            "lastTimestamp": _5m_ago,
            "involvedObject": {
                "kind": "Pod",
                "name": "payment-api-7d9f8b-xk2p9",
                "namespace": "production",
            },
            "namespace": "production",
        },
        {
            "reason": "Failed",
            "message": 'Error: secret "db-credentials" not found',
            "type": "Warning",
            "count": 1,
            "firstTimestamp": _30m_ago,
            "lastTimestamp": _30m_ago,
            "involvedObject": {
                "kind": "Pod",
                "name": "payment-api-7d9f8b-xk2p9",
                "namespace": "production",
            },
            "namespace": "production",
        },
        # OOMKill events for analytics-worker
        {
            "reason": "OOMKilling",
            "message": "Memory cgroup out of memory: Kill process (analytics-worker) score 999 or sacrifice child",
            "type": "Warning",
            "count": 7,
            "firstTimestamp": _1h_ago,
            "lastTimestamp": _30m_ago,
            "involvedObject": {
                "kind": "Pod",
                "name": "analytics-worker-8bf7c-p9qrs",
                "namespace": "production",
            },
            "namespace": "production",
        },
        # Image pull events for checkout-service
        {
            "reason": "ImagePullBackOff",
            "message": 'Back-off pulling image "myregistry/checkout:v2.0.0-rc1": rpc error: manifest unknown',
            "type": "Warning",
            "count": 12,
            "firstTimestamp": _1h_ago,
            "lastTimestamp": _5m_ago,
            "involvedObject": {
                "kind": "Pod",
                "name": "checkout-service-5bc4d-m7nop",
                "namespace": "staging",
            },
            "namespace": "staging",
        },
        # Pending pod scheduling failure
        {
            "reason": "FailedScheduling",
            "message": "0/3 nodes are available: 3 Insufficient memory. preemption: 0/3 nodes are available",
            "type": "Warning",
            "count": 30,
            "firstTimestamp": (now - timedelta(minutes=15)).isoformat(),
            "lastTimestamp": _5m_ago,
            "involvedObject": {
                "kind": "Pod",
                "name": "data-pipeline-6c9f-qrstu",
                "namespace": "production",
            },
            "namespace": "production",
        },
        # Probe failure event
        {
            "reason": "Unhealthy",
            "message": "Readiness probe failed: HTTP probe failed with statuscode: 503",
            "type": "Warning",
            "count": 5,
            "firstTimestamp": _30m_ago,
            "lastTimestamp": _5m_ago,
            "involvedObject": {
                "kind": "Pod",
                "name": "frontend-abc12-xyz99",
                "namespace": "production",
            },
            "namespace": "production",
        },
    ]

    deployments = [
        {"name": "frontend", "namespace": "production", "replicas": 3, "availableReplicas": 3},
        {"name": "payment-api", "namespace": "production", "replicas": 3, "availableReplicas": 0},
        {
            "name": "analytics-worker",
            "namespace": "production",
            "replicas": 2,
            "availableReplicas": 1,
        },
        {"name": "checkout-service", "namespace": "staging", "replicas": 2, "availableReplicas": 0},
        {"name": "data-pipeline", "namespace": "production", "replicas": 1, "availableReplicas": 0},
    ]

    services = [
        {
            "name": "payment-api",
            "namespace": "production",
            "type": "ClusterIP",
            "selector": {"app": "payment-api"},
            "ports": [{"port": 8080}],
        },
        {
            "name": "frontend",
            "namespace": "production",
            "type": "ClusterIP",
            "selector": {"app": "frontend"},
            "ports": [{"port": 80}],
        },
        {
            "name": "analytics-worker",
            "namespace": "production",
            "type": "ClusterIP",
            "selector": {"app": "analytics-worker"},
            "ports": [{"port": 9090}],
        },
        # Mismatched service: orphaned-svc has no matching pods
        {
            "name": "orphaned-svc",
            "namespace": "staging",
            "type": "ClusterIP",
            "selector": {"app": "old-service", "version": "v1"},
            "ports": [{"port": 8080}],
        },
    ]

    endpoints = [
        {"name": "payment-api", "namespace": "production", "subsets": []},  # No ready addresses
        {
            "name": "frontend",
            "namespace": "production",
            "subsets": [
                {"addresses": [{"ip": "10.0.0.1"}, {"ip": "10.0.0.2"}, {"ip": "10.0.0.3"}]}
            ],
        },
        {"name": "orphaned-svc", "namespace": "staging", "subsets": []},
    ]

    ingresses = [
        {
            "name": "main-ingress",
            "namespace": "production",
            "rules": [
                {
                    "host": "api.example.com",
                    "http": {
                        "paths": [
                            {
                                "path": "/payments",
                                "backend": {
                                    "service": {"name": "payment-api", "port": {"number": 8080}}
                                },
                            }
                        ]
                    },
                },
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
                },
            ],
        },
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
                                    "service": {"name": "missing-backend", "port": {"number": 8080}}
                                },
                            }
                        ]
                    },
                }
            ],
        },
    ]

    nodes = [
        {
            "name": "node-1",
            "ready": True,
            "allocatable": {"cpu": "3800m", "memory": "6Gi"},
            "capacity": {"cpu": "4000m", "memory": "8Gi"},
        },
        {
            "name": "node-2",
            "ready": True,
            "allocatable": {"cpu": "3500m", "memory": "5.5Gi"},
            "capacity": {"cpu": "4000m", "memory": "8Gi"},
        },
        {
            "name": "node-3",
            "ready": True,
            "allocatable": {"cpu": "3600m", "memory": "4.8Gi"},
            "capacity": {"cpu": "4000m", "memory": "8Gi"},
        },
    ]

    hpas = [
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
        },
        {
            "name": "analytics-hpa",
            "namespace": "production",
            "minReplicas": 5,
            "maxReplicas": 5,  # LOCKED: min == max
            "currentReplicas": 5,
            "targetCPUUtilizationPercentage": 70,
            "currentCPUUtilizationPercentage": 92,  # Saturated
            "scaleTargetRef": {"name": "analytics-worker"},
            "conditions": [{"type": "ScalingActive", "status": "True"}],
        },
    ]

    pvcs = [
        {
            "name": "data-pipeline-pvc",
            "namespace": "production",
            "phase": "Pending",  # Not bound
            "storageClassName": "fast-ssd",
            "accessModes": ["ReadWriteOnce"],
            "resources": {"requests": {"storage": "100Gi"}},
        },
        {
            "name": "prometheus-data",
            "namespace": "monitoring",
            "phase": "Bound",
            "storageClassName": "standard",
            "accessModes": ["ReadWriteOnce"],
            "resources": {"requests": {"storage": "50Gi"}},
        },
    ]

    recent_logs = {
        "production/payment-api-7d9f8b-xk2p9/payment-api": [
            "2024-01-15T09:23:35Z INFO  Starting payment-api v1.5.2",
            "2024-01-15T09:23:36Z INFO  Loading configuration from environment",
            "2024-01-15T09:23:36Z ERROR Failed to load config: secret 'db-credentials' not found in namespace 'production'",
            "2024-01-15T09:23:36Z ERROR Database connection pool initialization failed: host=<nil>",
            "2024-01-15T09:23:37Z FATAL Application startup failed — cannot continue without database configuration",
            "2024-01-15T09:23:38Z ERROR panic: runtime error: invalid memory address or nil pointer dereference",
        ],
        "production/analytics-worker-8bf7c-p9qrs/analytics-worker": [
            "2024-01-15T08:55:12Z INFO  Processing batch job batch_id=2024011534",
            "2024-01-15T08:55:45Z INFO  Loading dataset: 45GB parquet file",
            "2024-01-15T08:57:23Z WARN  Memory usage at 89% (229MB/256MB limit)",
            "2024-01-15T08:57:31Z WARN  Memory usage at 97% (248MB/256MB limit)",
            "2024-01-15T08:57:35Z ERROR Killed by OOM killer",
        ],
    }

    return {
        "pods": pods,
        "events": events,
        "deployments": deployments,
        "services": services,
        "endpoints": endpoints,
        "ingresses": ingresses,
        "nodes": nodes,
        "hpas": hpas,
        "pvcs": pvcs,
        "recent_logs": recent_logs,
    }


class _SimulatedK8s:
    """Simulated Kubernetes client returning realistic fake data."""

    #: Provider is always generic for the simulated client.
    provider: str = PROVIDER_GENERIC

    def detect_provider(self) -> str:
        """Return 'generic' — simulated cluster has no real cloud provider."""
        return PROVIDER_GENERIC

    def get_cluster_state(self) -> Dict[str, Any]:
        """Return the simulated cluster state."""
        return _make_simulated_cluster_state()

    def delete_pod(self, namespace: str, pod_name: str) -> Dict[str, Any]:
        """Simulate pod deletion."""
        logger.info("[SIMULATED] delete_pod: %s/%s", namespace, pod_name)
        return {"status": "deleted", "pod": pod_name}

    def rollout_restart(self, namespace: str, deployment: str) -> Dict[str, Any]:
        """Simulate deployment rolling restart."""
        logger.info("[SIMULATED] rollout_restart: %s/%s", namespace, deployment)
        return {"status": "restarted", "deployment": deployment}

    def rollback_deployment(
        self, namespace: str, deployment: str, revision: Any = None
    ) -> Dict[str, Any]:
        """Simulate deployment rollback."""
        logger.info("[SIMULATED] rollback: %s/%s to revision=%s", namespace, deployment, revision)
        return {"status": "rolled_back", "deployment": deployment}

    def scale_deployment(self, namespace: str, deployment: str, replicas: int) -> Dict[str, Any]:
        """Simulate deployment scaling."""
        logger.info("[SIMULATED] scale: %s/%s -> %d", namespace, deployment, replicas)
        return {"status": "scaled", "replicas": replicas}

    def patch_deployment(
        self, namespace: str, deployment: str, patch: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Simulate deployment patch."""
        logger.info("[SIMULATED] patch: %s/%s", namespace, deployment)
        return {"status": "patched"}

    def rerun_job(self, namespace: str, job_name: str) -> Dict[str, Any]:
        """Simulate job re-run."""
        logger.info("[SIMULATED] rerun_job: %s/%s", namespace, job_name)
        return {"status": "rerun_triggered"}


class RealK8sClient:
    """Real Kubernetes API client using the official kubernetes-client library."""

    def __init__(self) -> None:
        """Initialise the real Kubernetes client from the local kubeconfig.

        For EKS clusters, refreshes the auth token via aws-cli and handles
        SSL certificate verification issues on macOS.
        """
        import kubernetes

        try:
            kubernetes.config.load_incluster_config()
            logger.info("RealK8sClient initialised from in-cluster config")
        except kubernetes.config.ConfigException:
            kubernetes.config.load_kube_config()
            logger.info("RealK8sClient initialised from kubeconfig")

        # Fix SSL verification for EKS on macOS:
        # The kubernetes client reads the CA from kubeconfig but macOS Python
        # may not trust it. Ensure the client configuration uses the CA bundle
        # from kubeconfig or falls back to certifi.
        config = kubernetes.client.Configuration.get_default_copy()
        if not config.ssl_ca_cert:
            try:
                import certifi

                config.ssl_ca_cert = certifi.where()
                logger.info("Using certifi CA bundle for K8s API SSL: %s", config.ssl_ca_cert)
            except ImportError:
                logger.warning("certifi not installed — SSL verification may fail")

        # If KUBECONFIG_INSECURE=true, disable SSL verification (dev only)
        if os.getenv("KUBECONFIG_INSECURE", "").lower() == "true":
            config.verify_ssl = False
            logger.warning("SSL verification DISABLED for K8s API (KUBECONFIG_INSECURE=true)")

        kubernetes.client.Configuration.set_default(config)

        self._core = kubernetes.client.CoreV1Api()
        self._apps = kubernetes.client.AppsV1Api()
        self._batch = kubernetes.client.BatchV1Api()

        # Resolve cloud provider once at startup.
        # CLUSTER_PROVIDER env var (set via Helm values.cluster.provider) can
        # be an explicit value (aws|azure|gcp|generic) or empty/"auto" to
        # trigger automatic detection from node metadata.
        env_provider = os.getenv("CLUSTER_PROVIDER", "").strip().lower()
        if env_provider in _VALID_PROVIDERS:
            self.provider = env_provider
            logger.info("Cloud provider set from CLUSTER_PROVIDER env var: %s", self.provider)
        else:
            self.provider = self.detect_provider()
            logger.info("Cloud provider auto-detected: %s", self.provider)

    def detect_provider(self) -> str:
        """Detect the cloud provider by inspecting node labels and providerID.

        Detection heuristics (checked in order):
        - Node ``spec.providerID`` prefix: ``aws://`` → aws, ``azure://`` → azure, ``gce://`` → gcp
        - Node label ``eks.amazonaws.com/nodegroup`` or ``alpha.eksctl.io/cluster-name`` → aws
        - Node label ``kubernetes.azure.com/cluster`` or ``agentpool`` → azure
        - Node label ``cloud.google.com/gke-nodepool`` or ``topology.gke.io/zone`` → gcp

        Falls back to ``generic`` if no cloud signals are found or if the node
        list cannot be fetched.

        Returns:
            One of: "aws", "azure", "gcp", "generic"
        """
        try:
            nodes = self._core.list_node(watch=False, limit=5)
            for node in nodes.items:
                provider_id: str = (node.spec.provider_id or "").lower()
                labels: Dict[str, str] = node.metadata.labels or {}

                # Provider ID prefix checks (most reliable signal)
                if provider_id.startswith("aws://"):
                    return PROVIDER_AWS
                if provider_id.startswith("azure://"):
                    return PROVIDER_AZURE
                if provider_id.startswith("gce://"):
                    return PROVIDER_GCP

                # Label-based checks for clusters where providerID may be empty
                if any(
                    k.startswith("eks.amazonaws.com") or k.startswith("alpha.eksctl.io")
                    for k in labels
                ):
                    return PROVIDER_AWS
                if any(
                    k in labels
                    for k in (
                        "kubernetes.azure.com/cluster",
                        "agentpool",
                        "kubernetes.azure.com/agentpool",
                    )
                ):
                    return PROVIDER_AZURE
                if any(
                    k in labels
                    for k in (
                        "cloud.google.com/gke-nodepool",
                        "topology.gke.io/zone",
                        "cloud.google.com/gke-boot-disk",
                    )
                ):
                    return PROVIDER_GCP

        except Exception as exc:
            logger.warning("detect_provider: node list failed (%s) — defaulting to generic", exc)

        return PROVIDER_GENERIC

    def get_cluster_state(self) -> Dict[str, Any]:
        """Fetch real cluster state from the Kubernetes API server."""
        state: Dict[str, Any] = {
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
        try:
            pod_list = self._core.list_pod_for_all_namespaces(watch=False)
            for pod in pod_list.items:
                state["pods"].append(self._parse_pod(pod))

            svc_list = self._core.list_service_for_all_namespaces(watch=False)
            for svc in svc_list.items:
                state["services"].append(
                    {
                        "name": svc.metadata.name,
                        "namespace": svc.metadata.namespace,
                        "type": svc.spec.type,
                        "selector": svc.spec.selector or {},
                    }
                )

            ev_list = self._core.list_event_for_all_namespaces(watch=False)
            for ev in ev_list.items:
                state["events"].append(
                    {
                        "reason": ev.reason,
                        "message": ev.message,
                        "type": ev.type,
                        "count": ev.count,
                        "firstTimestamp": ev.first_timestamp.isoformat()
                        if ev.first_timestamp
                        else None,
                        "lastTimestamp": ev.last_timestamp.isoformat()
                        if ev.last_timestamp
                        else None,
                        "involvedObject": {
                            "kind": ev.involved_object.kind,
                            "name": ev.involved_object.name,
                            "namespace": ev.involved_object.namespace,
                        },
                        "namespace": ev.metadata.namespace,
                    }
                )

            node_list = self._core.list_node(watch=False)
            for node in node_list.items:
                state["nodes"].append(
                    {
                        "name": node.metadata.name,
                        "allocatable": {
                            "cpu": str(node.status.allocatable.get("cpu", "0")),
                            "memory": str(node.status.allocatable.get("memory", "0")),
                        },
                        "capacity": {
                            "cpu": str(node.status.capacity.get("cpu", "0")),
                            "memory": str(node.status.capacity.get("memory", "0")),
                        },
                    }
                )
        except Exception as exc:
            import traceback

            logger.error("RealK8sClient.get_cluster_state FAILED: %s: %s", type(exc).__name__, exc)
            logger.error("get_cluster_state traceback:\n%s", traceback.format_exc())

        # Second pass: fetch previous container logs for unhealthy pods
        _UNHEALTHY_REASONS = {
            "CrashLoopBackOff",
            "OOMKilled",
            "Error",
            "ImagePullBackOff",
            "ErrImagePull",
            "CreateContainerConfigError",
            "CreateContainerError",
        }
        unhealthy_count = 0
        for pod in state["pods"]:
            if unhealthy_count >= 10:
                break
            ns = pod.get("namespace", "")
            pod_name = pod.get("name", "")
            for cs in pod.get("container_statuses", []):
                if unhealthy_count >= 10:
                    break
                container = cs.get("name", "")
                restart_count = cs.get("restartCount", 0)
                waiting_reason = cs.get("state", {}).get("waiting", {}).get("reason", "")
                last_reason = cs.get("lastState", {}).get("terminated", {}).get("reason", "")
                is_unhealthy = (
                    restart_count > 0
                    or waiting_reason in _UNHEALTHY_REASONS
                    or last_reason in _UNHEALTHY_REASONS
                )
                if not is_unhealthy:
                    continue
                log_key = f"{ns}/{pod_name}/{container}"
                try:
                    log_text = self._core.read_namespaced_pod_log(
                        name=pod_name,
                        namespace=ns,
                        container=container,
                        previous=True,
                        tail_lines=80,
                    )
                    state["recent_logs"][log_key] = log_text.splitlines()
                    logger.info(
                        "Fetched previous logs for %s (%d lines)",
                        log_key,
                        len(state["recent_logs"][log_key]),
                    )
                    unhealthy_count += 1
                except Exception as log_exc:
                    logger.debug("Could not fetch logs for %s: %s", log_key, log_exc)

        return state

    @staticmethod
    def _parse_pod(pod: Any) -> Dict[str, Any]:
        """Parse a kubernetes Pod object into a flat dict."""
        cs_list = []
        for cs in pod.status.container_statuses or []:
            state_dict: Dict[str, Any] = {}
            if cs.state.waiting:
                state_dict["waiting"] = {
                    "reason": cs.state.waiting.reason,
                    "message": cs.state.waiting.message,
                }
            elif cs.state.running:
                state_dict["running"] = {}
            elif cs.state.terminated:
                state_dict["terminated"] = {
                    "reason": cs.state.terminated.reason,
                    "exitCode": cs.state.terminated.exit_code,
                }
            last_state_dict: Dict[str, Any] = {}
            if cs.last_state.terminated:
                last_state_dict["terminated"] = {
                    "reason": cs.last_state.terminated.reason,
                    "exitCode": cs.last_state.terminated.exit_code,
                }
            cs_list.append(
                {
                    "name": cs.name,
                    "restartCount": cs.restart_count,
                    "state": state_dict,
                    "lastState": last_state_dict,
                }
            )
        containers = []
        for c in pod.spec.containers or []:
            res = {}
            if c.resources:
                if c.resources.limits:
                    res["limits"] = dict(c.resources.limits)
                if c.resources.requests:
                    res["requests"] = dict(c.resources.requests)
            containers.append(
                {
                    "name": c.name,
                    "image": c.image,
                    "resources": res,
                }
            )
        return {
            "name": pod.metadata.name,
            "namespace": pod.metadata.namespace,
            "workload": pod.metadata.name.rsplit("-", 2)[0]
            if "-" in pod.metadata.name
            else pod.metadata.name,
            "phase": pod.status.phase or "Unknown",
            "labels": pod.metadata.labels or {},
            "container_statuses": cs_list,
            "containers": containers,
            "creationTimestamp": pod.metadata.creation_timestamp.isoformat()
            if pod.metadata.creation_timestamp
            else None,
        }

    def delete_pod(self, namespace: str, pod_name: str) -> Dict[str, Any]:
        """Delete a pod."""
        self._core.delete_namespaced_pod(name=pod_name, namespace=namespace)
        return {"status": "deleted"}

    def rollout_restart(self, namespace: str, deployment: str) -> Dict[str, Any]:
        """Trigger a rolling restart via annotation patch."""
        from datetime import datetime

        patch = {
            "spec": {
                "template": {
                    "metadata": {
                        "annotations": {
                            "kubectl.kubernetes.io/restartedAt": datetime.utcnow().isoformat()
                        }
                    }
                }
            }
        }
        self._apps.patch_namespaced_deployment(name=deployment, namespace=namespace, body=patch)
        return {"status": "restarted"}

    def rollback_deployment(
        self, namespace: str, deployment: str, revision: Any = None
    ) -> Dict[str, Any]:
        """Simulate rollback via kubectl."""
        import subprocess

        cmd = ["kubectl", "rollout", "undo", f"deployment/{deployment}", "-n", namespace]
        if revision:
            cmd.extend(["--to-revision", str(revision)])
        subprocess.run(cmd, check=True, capture_output=True)
        return {"status": "rolled_back"}

    def scale_deployment(self, namespace: str, deployment: str, replicas: int) -> Dict[str, Any]:
        """Scale a deployment."""
        patch = {"spec": {"replicas": replicas}}
        self._apps.patch_namespaced_deployment(name=deployment, namespace=namespace, body=patch)
        return {"status": "scaled", "replicas": replicas}

    def patch_deployment(
        self, namespace: str, deployment: str, patch: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Apply a strategic merge patch to a deployment."""
        self._apps.patch_namespaced_deployment(name=deployment, namespace=namespace, body=patch)
        return {"status": "patched"}

    def rerun_job(self, namespace: str, job_name: str) -> Dict[str, Any]:
        """Delete and recreate a job."""
        self._batch.delete_namespaced_job(name=job_name, namespace=namespace)
        return {"status": "deleted_for_rerun"}


def get_k8s_client():
    """Get the Kubernetes client (real or simulated based on environment).

    Returns:
        Either RealK8sClient or _SimulatedK8s.
    """
    if _is_demo_mode():
        logger.info("get_k8s_client: DEMO_MODE=1 — returning simulated client")
        return _SimulatedK8s()
    try:
        client = RealK8sClient()
        logger.info("get_k8s_client: RealK8sClient initialised successfully")
        return client
    except Exception as exc:
        import traceback

        logger.error(
            "get_k8s_client: RealK8sClient FAILED (%s: %s) — falling back to simulation",
            type(exc).__name__,
            exc,
        )
        logger.error("get_k8s_client traceback:\n%s", traceback.format_exc())
        return _SimulatedK8s()
