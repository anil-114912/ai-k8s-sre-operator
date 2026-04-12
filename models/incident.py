"""Pydantic models for incidents and evidence."""
from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any, Dict, List, Optional
import uuid

from pydantic import BaseModel, Field


class Severity(str, Enum):
    """Incident severity levels."""

    critical = "critical"
    high = "high"
    medium = "medium"
    low = "low"
    info = "info"


class IncidentType(str, Enum):
    """Supported incident type classifications."""

    crash_loop = "CrashLoopBackOff"
    oom_killed = "OOMKilled"
    image_pull = "ImagePullBackOff"
    pending = "PodPending"
    probe_failure = "ProbeFailure"
    service_mismatch = "ServiceMismatch"
    ingress_failure = "IngressFailure"
    pvc_failure = "PVCFailure"
    hpa_misconfigured = "HPAMisconfigured"
    node_pressure = "NodePressure"
    failed_rollout = "FailedRollout"
    quota_exceeded = "QuotaExceeded"
    dns_failure = "DNSFailure"
    rbac_denied = "RBACDenied"
    network_policy_block = "NetworkPolicyBlock"
    cni_failure = "CNIFailure"
    service_mesh_failure = "ServiceMeshFailure"
    storage_failure = "StorageFailure"
    unknown = "Unknown"


class IncidentStatus(str, Enum):
    """Lifecycle states of an incident."""

    detected = "detected"
    analyzing = "analyzing"
    analyzed = "analyzed"
    remediating = "remediating"
    resolved = "resolved"
    closed = "closed"
    failed = "failed"


class Evidence(BaseModel):
    """A piece of evidence collected during incident analysis."""

    source: str  # "k8s_events", "pod_logs", "metrics", "manifest", "detector"
    content: str
    timestamp: Optional[str] = None
    relevance: float = 1.0  # 0-1 how relevant to root cause


class Incident(BaseModel):
    """Full incident representation including detected signals and AI analysis."""

    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    title: str
    incident_type: IncidentType
    severity: Severity
    namespace: str
    workload: str
    pod_name: Optional[str] = None
    container_name: Optional[str] = None
    detected_at: str = Field(default_factory=lambda: datetime.utcnow().isoformat())
    status: IncidentStatus = IncidentStatus.detected
    raw_signals: Optional[Dict[str, Any]] = None  # raw detector output
    evidence: Optional[List[Evidence]] = None
    # filled after analysis
    root_cause: Optional[str] = None
    contributing_factors: Optional[List[str]] = None
    confidence: Optional[float] = None
    suggested_fix: Optional[str] = None
    similar_past_incidents: Optional[List[str]] = None  # IDs
    ai_explanation: Optional[str] = None
    # metadata
    cluster_context: Optional[str] = None
    provider_used: str = "simulation"
