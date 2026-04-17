"""CrashLoopBackOff simulation scenario — missing secret root cause."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List


def _ts(offset_minutes: float = 0.0) -> str:
    """Return an ISO-8601 timestamp relative to now."""
    t = datetime.now(timezone.utc) - timedelta(minutes=offset_minutes)
    return t.strftime("%Y-%m-%dT%H:%M:%SZ")


class CrashLoopScenario:
    """Generates a realistic CrashLoopBackOff cluster state.

    Scenario: A deployment was updated 5 minutes ago to add a new
    envFrom.secretRef pointing to 'db-credentials', but the Secret
    was never created.  The pod crashes immediately on startup.

    Generated data:
      - 1 pod in CrashLoopBackOff state (restart_count=18)
      - K8s Warning events: BackOff, Failed, CrashLoopBackOff
      - Container log: "Error: secret 'db-credentials' not found"
      - 1 service with matching selector
      - 1 deployment object
      - Recent change: deployment updated 5 minutes ago
    """

    def __init__(
        self,
        namespace: str = "simulation",
        workload: str = "payment-api",
        secret_name: str = "db-credentials",
        restart_count: int = 18,
    ) -> None:
        self.namespace = namespace
        self.workload = workload
        self.secret_name = secret_name
        self.restart_count = restart_count
        self.pod_name = f"{workload}-6d7f9b-abc12"

    def generate(self) -> Dict[str, Any]:
        """Generate and return the full cluster state dict."""
        return {
            "pods": self._pods(),
            "events": self._events(),
            "services": self._services(),
            "deployments": self._deployments(),
            "replicasets": [],
            "nodes": self._nodes(),
            "pvcs": [],
            "hpas": [],
            "ingresses": [],
            "namespaces": [{"name": self.namespace}],
            "recent_changes": self._recent_changes(),
            "pod_logs": {self.pod_name: self._logs()},
            "metrics": {},
        }

    def _pods(self) -> List[Dict[str, Any]]:
        return [
            {
                "name": self.pod_name,
                "namespace": self.namespace,
                "phase": "Running",
                "conditions": [
                    {"type": "Ready", "status": "False"},
                    {"type": "ContainersReady", "status": "False"},
                ],
                "container_statuses": [
                    {
                        "name": self.workload,
                        "ready": False,
                        "restart_count": self.restart_count,
                        "state": {
                            "waiting": {
                                "reason": "CrashLoopBackOff",
                                "message": f"back-off 5m0s restarting failed container={self.workload}",
                            }
                        },
                        "last_state": {
                            "terminated": {
                                "reason": "Error",
                                "exit_code": 1,
                                "finished_at": _ts(0.5),
                                "message": f"Error: secret '{self.secret_name}' not found in namespace '{self.namespace}'",
                            }
                        },
                    }
                ],
                "labels": {"app": self.workload, "version": "v1.2.0"},
                "owner_references": [{"kind": "ReplicaSet", "name": f"{self.workload}-rs"}],
                "node_name": "worker-node-1",
            }
        ]

    def _events(self) -> List[Dict[str, Any]]:
        return [
            {
                "reason": "BackOff",
                "message": f"Back-off restarting failed container {self.workload} in pod {self.pod_name}",
                "type": "Warning",
                "count": self.restart_count,
                "involvedObject": {"kind": "Pod", "name": self.pod_name, "namespace": self.namespace},
                "firstTimestamp": _ts(12),
                "lastTimestamp": _ts(0.5),
            },
            {
                "reason": "Failed",
                "message": f"Error: secret \"{self.secret_name}\" not found",
                "type": "Warning",
                "count": 1,
                "involvedObject": {"kind": "Pod", "name": self.pod_name, "namespace": self.namespace},
                "firstTimestamp": _ts(4.5),
                "lastTimestamp": _ts(4.5),
            },
            {
                "reason": "Pulled",
                "message": f"Successfully pulled image for {self.workload}",
                "type": "Normal",
                "count": 1,
                "involvedObject": {"kind": "Pod", "name": self.pod_name, "namespace": self.namespace},
                "firstTimestamp": _ts(5),
                "lastTimestamp": _ts(5),
            },
        ]

    def _services(self) -> List[Dict[str, Any]]:
        return [
            {
                "name": self.workload,
                "namespace": self.namespace,
                "selector": {"app": self.workload},
                "ports": [{"port": 8080, "targetPort": 8080, "protocol": "TCP"}],
                "clusterIP": "10.100.0.100",
            }
        ]

    def _deployments(self) -> List[Dict[str, Any]]:
        return [
            {
                "name": self.workload,
                "namespace": self.namespace,
                "replicas": 1,
                "ready_replicas": 0,
                "unavailable_replicas": 1,
                "labels": {"app": self.workload},
                "annotations": {
                    "deployment.kubernetes.io/revision": "2",
                    "kubectl.kubernetes.io/last-applied-configuration": "{}",
                },
            }
        ]

    def _nodes(self) -> List[Dict[str, Any]]:
        return [
            {
                "name": "worker-node-1",
                "conditions": [{"type": "Ready", "status": "True"}],
                "allocatable": {"cpu": "4", "memory": "8Gi"},
                "capacity": {"cpu": "4", "memory": "8Gi"},
            }
        ]

    def _recent_changes(self) -> List[Dict[str, Any]]:
        return [
            {
                "type": "DeploymentUpdate",
                "resource": f"Deployment/{self.workload}",
                "namespace": self.namespace,
                "message": (
                    f"Deployment {self.workload} updated: added envFrom.secretRef.name={self.secret_name}"
                ),
                "timestamp": _ts(5),
                "user": "ci-pipeline",
            }
        ]

    def _logs(self) -> List[str]:
        return [
            f"{_ts(0.6)} INFO  Starting {self.workload} v1.2.0",
            f"{_ts(0.6)} INFO  Loading configuration from environment",
            f"{_ts(0.5)} ERROR Failed to resolve secret ref: secret '{self.secret_name}' not found in namespace '{self.namespace}'",
            f"{_ts(0.5)} ERROR Application startup failed — exiting with code 1",
        ]
