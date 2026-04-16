"""Pydantic models for remediation plans and execution results."""

from __future__ import annotations

import uuid
from datetime import datetime
from enum import Enum
from typing import List, Optional

from pydantic import BaseModel, Field


class SafetyLevel(str, Enum):
    """Three-tier safety classification for remediation actions."""

    auto_fix = "auto_fix"  # Level 1: execute automatically
    approval_required = "approval_required"  # Level 2: generate + wait for approval
    suggest_only = "suggest_only"  # Level 3: never auto-execute


class RemediationStatus(str, Enum):
    """Lifecycle states for a remediation plan."""

    pending = "pending"
    approved = "approved"
    executing = "executing"
    completed = "completed"
    failed = "failed"
    rejected = "rejected"


class RemediationStep(BaseModel):
    """A single actionable step in a remediation plan."""

    order: int
    action: str
    command: Optional[str] = None
    description: str
    safety_level: SafetyLevel
    reversible: bool = True
    estimated_duration_secs: int = 30


class RemediationPlan(BaseModel):
    """A complete remediation plan for an incident."""

    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    incident_id: str
    summary: str
    steps: List[RemediationStep]
    overall_safety_level: SafetyLevel
    requires_approval: bool
    auto_executable: bool
    estimated_downtime_secs: int = 0
    rollback_plan: Optional[str] = None
    status: RemediationStatus = RemediationStatus.pending
    created_at: str = Field(default_factory=lambda: datetime.utcnow().isoformat())
    executed_at: Optional[str] = None
    outcome: Optional[str] = None


class RemediationResult(BaseModel):
    """Result of executing a remediation plan."""

    plan_id: str
    incident_id: str
    executed_steps: List[str]
    success: bool
    output: str
    duration_secs: float
    timestamp: str = Field(default_factory=lambda: datetime.utcnow().isoformat())
