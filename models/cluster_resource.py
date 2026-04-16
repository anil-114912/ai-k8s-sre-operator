"""Pydantic models for Kubernetes cluster resources."""

from __future__ import annotations

from enum import Enum
from typing import Any, Dict, List, Optional

from pydantic import BaseModel


class NodeConditionType(str, Enum):
    """Standard Kubernetes node condition types."""

    ready = "Ready"
    memory_pressure = "MemoryPressure"
    disk_pressure = "DiskPressure"
    pid_pressure = "PIDPressure"
    network_unavailable = "NetworkUnavailable"


class NodeStatus(BaseModel):
    """Status snapshot of a Kubernetes node."""

    name: str
    ready: bool = True
    memory_pressure: bool = False
    disk_pressure: bool = False
    pid_pressure: bool = False
    allocatable_cpu: Optional[str] = None
    allocatable_memory: Optional[str] = None
    capacity_cpu: Optional[str] = None
    capacity_memory: Optional[str] = None
    labels: Optional[Dict[str, str]] = None
    taints: Optional[List[Dict[str, str]]] = None


class PodStatus(BaseModel):
    """Status snapshot of a Kubernetes pod."""

    name: str
    namespace: str
    phase: str  # Pending, Running, Succeeded, Failed, Unknown
    ready: bool = False
    restart_count: int = 0
    container_name: Optional[str] = None
    image: Optional[str] = None
    node_name: Optional[str] = None
    labels: Optional[Dict[str, str]] = None
    conditions: Optional[List[Dict[str, Any]]] = None
    container_statuses: Optional[List[Dict[str, Any]]] = None


class ClusterResource(BaseModel):
    """Generic cluster resource reference."""

    kind: str
    name: str
    namespace: Optional[str] = None
    api_version: str = "v1"
    labels: Optional[Dict[str, str]] = None
    annotations: Optional[Dict[str, str]] = None
    spec: Optional[Dict[str, Any]] = None
    status: Optional[Dict[str, Any]] = None


class ClusterHealthSummary(BaseModel):
    """High-level cluster health overview."""

    total_nodes: int = 0
    ready_nodes: int = 0
    total_pods: int = 0
    running_pods: int = 0
    pending_pods: int = 0
    failed_pods: int = 0
    crashloop_pods: int = 0
    total_deployments: int = 0
    available_deployments: int = 0
    total_pvcs: int = 0
    bound_pvcs: int = 0
    active_incidents: int = 0
    health_score: float = 100.0  # 0-100
    summary: str = "Cluster health unknown"
