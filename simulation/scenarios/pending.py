"""PodPending simulation scenario — insufficient node resources."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List


def _ts(offset_minutes: float = 0.0) -> str:
    t = datetime.now(timezone.utc) - timedelta(minutes=offset_minutes)
    return t.strftime("%Y-%m-%dT%H:%M:%SZ")


class PendingPodsScenario:
    """Generates a realistic PodPending cluster state.

    Scenario: A batch processing job was scaled up to 10 replicas for a
    high-load event. 7 pods are running but 3 are stuck Pending because
    all worker nodes are at CPU capacity.

    Generated data:
      - 3 pods stuck in Pending (insufficient CPU)
      - Kubernetes scheduler events: FailedScheduling
      - 2 worker nodes at 90%+ CPU
      - HPA scale-up in recent changes
    """

    def __init__(
        self,
        namespace: str = "simulation",
        workload: str = "batch-processor",
        pending_count: int = 3,
        running_count: int = 7,
    ) -> None:
        self.namespace = namespace
        self.workload = workload
        self.pending_count = pending_count
        self.running_count = running_count

    def generate(self) -> Dict[str, Any]:
        return {
            "pods": self._pods(),
            "events": self._events(),
            "services": self._services(),
            "deployments": self._deployments(),
            "replicasets": [],
            "nodes": self._nodes(),
            "pvcs": [],
            "hpas": self._hpas(),
            "ingresses": [],
            "namespaces": [{"name": self.namespace}],
            "recent_changes": self._recent_changes(),
            "pod_logs": {},
            "metrics": self._metrics(),
        }

    def _pods(self) -> List[Dict[str, Any]]:
        pods = []
        # Running pods
        for i in range(self.running_count):
            pods.append(
                {
                    "name": f"{self.workload}-{i:03d}-abc12",
                    "namespace": self.namespace,
                    "phase": "Running",
                    "conditions": [{"type": "Ready", "status": "True"}],
                    "container_statuses": [
                        {
                            "name": self.workload,
                            "ready": True,
                            "restart_count": 0,
                            "state": {"running": {"startedAt": _ts(15)}},
                        }
                    ],
                    "labels": {"app": self.workload},
                    "node_name": f"worker-node-{(i % 2) + 1}",
                    "resources": {
                        "requests": {"cpu": "500m", "memory": "512Mi"},
                        "limits": {"cpu": "1000m", "memory": "1Gi"},
                    },
                }
            )
        # Pending pods
        for i in range(self.pending_count):
            pods.append(
                {
                    "name": f"{self.workload}-pending-{i:03d}",
                    "namespace": self.namespace,
                    "phase": "Pending",
                    "conditions": [
                        {
                            "type": "PodScheduled",
                            "status": "False",
                            "reason": "Unschedulable",
                            "message": (
                                "0/2 nodes are available: "
                                "2 Insufficient cpu. "
                                "preemption: 0/2 nodes are available: 2 No preemption victims found."
                            ),
                        }
                    ],
                    "container_statuses": [],
                    "labels": {"app": self.workload},
                    "node_name": None,
                    "resources": {
                        "requests": {"cpu": "500m", "memory": "512Mi"},
                        "limits": {"cpu": "1000m", "memory": "1Gi"},
                    },
                }
            )
        return pods

    def _events(self) -> List[Dict[str, Any]]:
        events = []
        for i in range(self.pending_count):
            events.append(
                {
                    "reason": "FailedScheduling",
                    "message": (
                        "0/2 nodes are available: "
                        "2 Insufficient cpu. "
                        "preemption: 0/2 nodes are available: "
                        "2 No preemption victims found for incoming pod."
                    ),
                    "type": "Warning",
                    "count": 5,
                    "involvedObject": {
                        "kind": "Pod",
                        "name": f"{self.workload}-pending-{i:03d}",
                        "namespace": self.namespace,
                    },
                    "firstTimestamp": _ts(5),
                    "lastTimestamp": _ts(0.5),
                }
            )
        return events

    def _services(self) -> List[Dict[str, Any]]:
        return [
            {
                "name": self.workload,
                "namespace": self.namespace,
                "selector": {"app": self.workload},
                "ports": [{"port": 8080, "targetPort": 8080}],
            }
        ]

    def _deployments(self) -> List[Dict[str, Any]]:
        return [
            {
                "name": self.workload,
                "namespace": self.namespace,
                "replicas": self.running_count + self.pending_count,
                "ready_replicas": self.running_count,
                "unavailable_replicas": self.pending_count,
            }
        ]

    def _nodes(self) -> List[Dict[str, Any]]:
        return [
            {
                "name": "worker-node-1",
                "conditions": [{"type": "Ready", "status": "True"}],
                "allocatable": {"cpu": "4000m", "memory": "8Gi"},
                "capacity": {"cpu": "4000m", "memory": "8Gi"},
                # CPU at 90% — only 400m available, need 500m per pod
                "allocated": {"cpu": "3600m", "memory": "4Gi"},
            },
            {
                "name": "worker-node-2",
                "conditions": [{"type": "Ready", "status": "True"}],
                "allocatable": {"cpu": "4000m", "memory": "8Gi"},
                "capacity": {"cpu": "4000m", "memory": "8Gi"},
                # Also at 90%
                "allocated": {"cpu": "3600m", "memory": "4.5Gi"},
            },
        ]

    def _hpas(self) -> List[Dict[str, Any]]:
        return [
            {
                "name": f"{self.workload}-hpa",
                "namespace": self.namespace,
                "scaleTargetRef": {"name": self.workload, "kind": "Deployment"},
                "minReplicas": 2,
                "maxReplicas": self.running_count + self.pending_count,
                "currentReplicas": self.running_count + self.pending_count,
                "desiredReplicas": self.running_count + self.pending_count,
                "currentMetrics": [
                    {"type": "Resource", "resource": {"name": "cpu", "current": {"averageUtilization": 92}}}
                ],
            }
        ]

    def _recent_changes(self) -> List[Dict[str, Any]]:
        return [
            {
                "type": "HPAScaleUp",
                "resource": f"HPA/{self.workload}-hpa",
                "namespace": self.namespace,
                "message": (
                    f"HPA scaled {self.workload} from {self.running_count} to "
                    f"{self.running_count + self.pending_count} replicas (CPU utilization: 92%)"
                ),
                "timestamp": _ts(6),
                "user": "system:hpa-controller",
            }
        ]

    def _metrics(self) -> Dict[str, Any]:
        return {
            "node_cpu_utilization": {
                "worker-node-1": 0.90,
                "worker-node-2": 0.90,
            }
        }
