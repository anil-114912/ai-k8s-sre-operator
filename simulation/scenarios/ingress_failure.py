"""Ingress failure simulation scenario — service selector mismatch."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List


def _ts(offset_minutes: float = 0.0) -> str:
    t = datetime.now(timezone.utc) - timedelta(minutes=offset_minutes)
    return t.strftime("%Y-%m-%dT%H:%M:%SZ")


class IngressFailureScenario:
    """Generates a realistic Ingress 502 cluster state.

    Scenario: A recent deployment renamed the app label from 'frontend'
    to 'frontend-v2', but the Service selector still points to 'frontend'.
    The Service has no endpoints, causing the Ingress to return 502.

    Generated data:
      - 1 Ingress routing to the service
      - 1 Service with empty endpoints (selector mismatch)
      - 1 pod with correct labels (app: frontend-v2)
      - Events: FailedToReconcile, no endpoint warning
    """

    def __init__(
        self,
        namespace: str = "simulation",
        workload: str = "frontend",
        ingress_host: str = "app.example.com",
    ) -> None:
        self.namespace = namespace
        self.workload = workload
        self.ingress_host = ingress_host
        self.pod_name = f"{workload}-v2-9a8b7c-def45"

    def generate(self) -> Dict[str, Any]:
        return {
            "pods": self._pods(),
            "events": self._events(),
            "services": self._services(),
            "deployments": self._deployments(),
            "replicasets": [],
            "nodes": self._nodes(),
            "pvcs": [],
            "hpas": [],
            "ingresses": self._ingresses(),
            "namespaces": [{"name": self.namespace}],
            "recent_changes": self._recent_changes(),
            "pod_logs": {},
            "metrics": {},
        }

    def _pods(self) -> List[Dict[str, Any]]:
        return [
            {
                "name": self.pod_name,
                "namespace": self.namespace,
                "phase": "Running",
                "conditions": [
                    {"type": "Ready", "status": "True"},
                    {"type": "ContainersReady", "status": "True"},
                ],
                "container_statuses": [
                    {
                        "name": self.workload,
                        "ready": True,
                        "restart_count": 0,
                        "state": {"running": {"startedAt": _ts(10)}},
                    }
                ],
                # Label is v2 but Service still selects original label
                "labels": {"app": f"{self.workload}-v2", "version": "v2.0.0"},
                "node_name": "worker-node-1",
            }
        ]

    def _events(self) -> List[Dict[str, Any]]:
        return [
            {
                "reason": "FailedToReconcile",
                "message": (
                    f"No endpoints found for service {self.workload}: "
                    f"selector app={self.workload} matches no pods"
                ),
                "type": "Warning",
                "count": 12,
                "involvedObject": {
                    "kind": "Service",
                    "name": self.workload,
                    "namespace": self.namespace,
                },
                "firstTimestamp": _ts(8),
                "lastTimestamp": _ts(1),
            },
            {
                "reason": "Sync",
                "message": f"Ingress {self.namespace}/{self.workload}-ingress: controller reported error: upstream not available",
                "type": "Warning",
                "count": 24,
                "involvedObject": {
                    "kind": "Ingress",
                    "name": f"{self.workload}-ingress",
                    "namespace": self.namespace,
                },
                "firstTimestamp": _ts(8),
                "lastTimestamp": _ts(0.5),
            },
        ]

    def _services(self) -> List[Dict[str, Any]]:
        return [
            {
                "name": self.workload,
                "namespace": self.namespace,
                # Old selector — doesn't match the new pod labels
                "selector": {"app": self.workload},
                "ports": [{"port": 80, "targetPort": 8080, "protocol": "TCP"}],
                "clusterIP": "10.100.0.200",
                # Endpoints will be empty because no pod matches selector
                "endpoints": [],
            }
        ]

    def _deployments(self) -> List[Dict[str, Any]]:
        return [
            {
                "name": self.workload,
                "namespace": self.namespace,
                "replicas": 1,
                "ready_replicas": 1,  # Pod is ready...
                "unavailable_replicas": 0,  # ...but unreachable via service
                "labels": {"app": f"{self.workload}-v2"},
            }
        ]

    def _nodes(self) -> List[Dict[str, Any]]:
        return [
            {
                "name": "worker-node-1",
                "conditions": [{"type": "Ready", "status": "True"}],
                "allocatable": {"cpu": "4", "memory": "8Gi"},
            }
        ]

    def _ingresses(self) -> List[Dict[str, Any]]:
        return [
            {
                "name": f"{self.workload}-ingress",
                "namespace": self.namespace,
                "rules": [
                    {
                        "host": self.ingress_host,
                        "http": {
                            "paths": [
                                {
                                    "path": "/",
                                    "backend": {
                                        "service": {
                                            "name": self.workload,
                                            "port": {"number": 80},
                                        }
                                    },
                                }
                            ]
                        },
                    }
                ],
            }
        ]

    def _recent_changes(self) -> List[Dict[str, Any]]:
        return [
            {
                "type": "DeploymentUpdate",
                "resource": f"Deployment/{self.workload}",
                "namespace": self.namespace,
                "message": (
                    f"Deployment labels updated: app label changed from '{self.workload}' "
                    f"to '{self.workload}-v2' in pod template"
                ),
                "timestamp": _ts(10),
                "user": "kubectl-apply",
            }
        ]
