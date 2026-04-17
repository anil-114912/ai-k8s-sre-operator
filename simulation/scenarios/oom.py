"""OOMKill simulation scenario — container exceeds memory limit."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List


def _ts(offset_minutes: float = 0.0) -> str:
    t = datetime.now(timezone.utc) - timedelta(minutes=offset_minutes)
    return t.strftime("%Y-%m-%dT%H:%M:%SZ")


class OOMScenario:
    """Generates a realistic OOMKill cluster state.

    Scenario: An order processing service has been steadily consuming more
    memory over the last hour (likely a memory leak). The container was
    killed by the OOM killer when it hit the 512Mi limit.

    Generated data:
      - 1 pod in CrashLoopBackOff state (OOMKilled last state)
      - OOMKilling event
      - Container exit code 137 (SIGKILL from OOM killer)
      - Pod logs showing memory growth
      - Resource metrics showing high memory usage
    """

    def __init__(
        self,
        namespace: str = "simulation",
        workload: str = "order-processor",
        memory_limit: str = "512Mi",
        restart_count: int = 3,
    ) -> None:
        self.namespace = namespace
        self.workload = workload
        self.memory_limit = memory_limit
        self.restart_count = restart_count
        self.pod_name = f"{workload}-7c8d9e-xyz99"

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
            "ingresses": [],
            "namespaces": [{"name": self.namespace}],
            "recent_changes": [],
            "pod_logs": {self.pod_name: self._logs()},
            "metrics": self._metrics(),
        }

    def _pods(self) -> List[Dict[str, Any]]:
        return [
            {
                "name": self.pod_name,
                "namespace": self.namespace,
                "phase": "Running",
                "conditions": [
                    {"type": "Ready", "status": "False"},
                ],
                "container_statuses": [
                    {
                        "name": self.workload,
                        "ready": False,
                        "restart_count": self.restart_count,
                        "state": {
                            "waiting": {
                                "reason": "CrashLoopBackOff",
                            }
                        },
                        "last_state": {
                            "terminated": {
                                "reason": "OOMKilled",
                                "exit_code": 137,
                                "finished_at": _ts(2),
                                "message": f"Container exceeded memory limit {self.memory_limit}",
                            }
                        },
                    }
                ],
                "labels": {"app": self.workload},
                "node_name": "worker-node-2",
                "resources": {
                    "limits": {"memory": self.memory_limit, "cpu": "500m"},
                    "requests": {"memory": "256Mi", "cpu": "100m"},
                },
            }
        ]

    def _events(self) -> List[Dict[str, Any]]:
        return [
            {
                "reason": "OOMKilling",
                "message": (
                    f"Memory cgroup out of memory: Kill process in container {self.workload}; "
                    f"MemoryRequest:{self.memory_limit}"
                ),
                "type": "Warning",
                "count": self.restart_count,
                "involvedObject": {"kind": "Pod", "name": self.pod_name, "namespace": self.namespace},
                "firstTimestamp": _ts(65),
                "lastTimestamp": _ts(2),
            },
            {
                "reason": "BackOff",
                "message": f"Back-off restarting failed container {self.workload}",
                "type": "Warning",
                "count": self.restart_count,
                "involvedObject": {"kind": "Pod", "name": self.pod_name, "namespace": self.namespace},
                "firstTimestamp": _ts(60),
                "lastTimestamp": _ts(1),
            },
        ]

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
                "replicas": 1,
                "ready_replicas": 0,
                "unavailable_replicas": 1,
            }
        ]

    def _nodes(self) -> List[Dict[str, Any]]:
        return [
            {
                "name": "worker-node-2",
                "conditions": [{"type": "Ready", "status": "True"}],
                "allocatable": {"cpu": "8", "memory": "16Gi"},
                "capacity": {"cpu": "8", "memory": "16Gi"},
            }
        ]

    def _logs(self) -> List[str]:
        return [
            f"{_ts(65)} INFO  {self.workload} starting, processing order queue",
            f"{_ts(30)} INFO  Processed 10,000 orders, memory usage: 280Mi",
            f"{_ts(20)} WARN  Memory usage elevated: 380Mi / 512Mi limit",
            f"{_ts(10)} WARN  Memory usage critical: 490Mi / 512Mi limit — GC pressure",
            f"{_ts(2)} ERROR Java heap space — java.lang.OutOfMemoryError",
            f"{_ts(2)} ERROR  Container killed by OOM killer",
        ]

    def _metrics(self) -> Dict[str, Any]:
        return {
            "container_memory_working_set_bytes": {
                f"{self.namespace}/{self.pod_name}/{self.workload}": 536870912  # 512Mi in bytes
            }
        }
