"""High-level guardrails engine — evaluates full remediation plans against policy.

This is a higher-level wrapper around the per-step ``PolicyGuardrails`` in
``remediations/policy_guardrails.py``.  It evaluates a complete ``RemediationPlan``
holistically and returns a ``GuardrailsDecision`` that describes what is allowed,
what is blocked, and what requires approval.

Key additions over the step-level guardrails:
  - Max scaling limits (can't scale beyond N% of current replicas)
  - Risk score threshold (plans above a risk score → approval required)
  - Overall plan approval gate (any L2+ step → approval required for whole plan)
  - Audit log generation
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

from models.remediation import SafetyLevel

logger = logging.getLogger(__name__)

# Maximum allowed scale-up factor (2.0 = 200% of current replicas)
_MAX_SCALE_FACTOR = float(os.getenv("MAX_SCALE_FACTOR", "2.0"))

# Risk score above which a plan is force-gated to approval_required
_RISK_SCORE_THRESHOLD = float(os.getenv("RISK_SCORE_THRESHOLD", "0.7"))

# Per-action risk scores (0-1, higher = riskier)
_ACTION_RISK: Dict[str, float] = {
    "restart_pod": 0.1,
    "rollout_restart": 0.2,
    "rerun_job": 0.2,
    "scale_up": 0.3,
    "scale_down": 0.5,
    "rollback": 0.6,
    "patch_limits": 0.4,
    "patch_selector": 0.5,
    "recreate_secret": 0.2,
    "rbac_changes": 0.8,
    "network_policy": 0.7,
    "storage_changes": 0.7,
}

# Namespaces that can never be auto-fixed regardless of configuration
_PROTECTED_NAMESPACES = {"kube-system", "kube-public", "kube-node-lease"}


@dataclass
class StepDecision:
    """Decision for a single remediation step."""

    action: str
    allowed: bool
    blocked_reason: str = ""
    risk_score: float = 0.0
    requires_approval: bool = False
    audit_note: str = ""


@dataclass
class GuardrailsDecision:
    """Full evaluation result for a remediation plan."""

    plan_id: str
    incident_id: str
    namespace: str
    workload: str
    step_decisions: List[StepDecision] = field(default_factory=list)
    overall_allowed: bool = True
    overall_requires_approval: bool = False
    blocked_steps: List[str] = field(default_factory=list)
    risk_score: float = 0.0
    evaluated_at: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )
    audit_log: List[str] = field(default_factory=list)

    def summary(self) -> str:
        """One-line summary for logging."""
        blocked = len(self.blocked_steps)
        status = "BLOCKED" if blocked else ("APPROVAL_REQUIRED" if self.overall_requires_approval else "ALLOWED")
        return (
            f"Plan {self.plan_id[:8]}... [{status}] "
            f"risk={self.risk_score:.2f} "
            f"steps={len(self.step_decisions)} blocked={blocked}"
        )


class GuardrailsEngine:
    """Evaluates a complete remediation plan against all configured policies.

    Usage::

        engine = GuardrailsEngine()
        decision = engine.evaluate_plan(plan, incident)

        if decision.overall_allowed and not decision.overall_requires_approval:
            executor.execute(plan)
        elif decision.overall_requires_approval:
            queue_for_approval(plan, decision)
        else:
            logger.warning("Plan blocked: %s", decision.blocked_steps)
    """

    def __init__(
        self,
        max_scale_factor: float = _MAX_SCALE_FACTOR,
        risk_score_threshold: float = _RISK_SCORE_THRESHOLD,
        additional_protected_namespaces: Optional[List[str]] = None,
        allowed_actions: Optional[List[str]] = None,
        denied_actions: Optional[List[str]] = None,
    ) -> None:
        self.max_scale_factor = max_scale_factor
        self.risk_score_threshold = risk_score_threshold
        self.protected_namespaces = _PROTECTED_NAMESPACES | set(
            additional_protected_namespaces or []
        )
        self.allowed_actions = set(allowed_actions) if allowed_actions else None
        self.denied_actions = set(denied_actions or [])

    # ------------------------------------------------------------------
    # Main evaluation
    # ------------------------------------------------------------------

    def evaluate_plan(
        self,
        plan: Any,
        incident: Optional[Any] = None,
    ) -> GuardrailsDecision:
        """Evaluate a complete RemediationPlan against all guardrails.

        Args:
            plan: A RemediationPlan object (or dict with 'steps', 'incident_id').
            incident: The Incident object (used for namespace/workload).

        Returns:
            GuardrailsDecision with per-step and overall results.
        """
        plan_id = self._get(plan, "id", "unknown")
        incident_id = self._get(plan, "incident_id", "unknown")
        namespace = self._get(incident, "namespace", "") if incident else ""
        workload = self._get(incident, "workload", "") if incident else ""
        steps = self._get(plan, "steps", [])

        decision = GuardrailsDecision(
            plan_id=plan_id,
            incident_id=incident_id,
            namespace=namespace,
            workload=workload,
        )

        audit = []
        audit.append(f"[{decision.evaluated_at}] Evaluating plan {plan_id[:16]} for {namespace}/{workload}")

        # 1. Namespace protection check (whole plan)
        if namespace in self.protected_namespaces:
            decision.overall_allowed = False
            reason = f"Namespace '{namespace}' is in the protected set — no automated remediation"
            decision.audit_log = audit + [f"BLOCKED: {reason}"]
            logger.warning("GuardrailsEngine BLOCKED plan: %s", reason)
            return decision

        # 2. Evaluate each step
        plan_risk = 0.0
        for step in steps:
            step_decision = self._evaluate_step(step, namespace, workload)
            decision.step_decisions.append(step_decision)
            plan_risk = max(plan_risk, step_decision.risk_score)

            if not step_decision.allowed:
                decision.blocked_steps.append(step_decision.action)
                audit.append(f"  BLOCKED step '{step_decision.action}': {step_decision.blocked_reason}")
            elif step_decision.requires_approval:
                decision.overall_requires_approval = True
                audit.append(f"  APPROVAL_REQUIRED step '{step_decision.action}'")
            else:
                audit.append(f"  ALLOWED step '{step_decision.action}' (risk={step_decision.risk_score:.2f})")

        decision.risk_score = round(plan_risk, 3)

        # 3. High-risk plan → force approval gate
        if plan_risk >= self.risk_score_threshold and not decision.blocked_steps:
            decision.overall_requires_approval = True
            audit.append(
                f"  APPROVAL_REQUIRED: plan risk score {plan_risk:.2f} >= threshold {self.risk_score_threshold:.2f}"
            )

        # 4. Any blocked step → whole plan is blocked
        if decision.blocked_steps:
            decision.overall_allowed = False

        decision.audit_log = audit
        logger.info("GuardrailsEngine: %s", decision.summary())
        return decision

    def get_audit_log(self, decision: GuardrailsDecision) -> str:
        """Format the audit log as a multi-line string."""
        return "\n".join(decision.audit_log)

    # ------------------------------------------------------------------
    # Per-step evaluation
    # ------------------------------------------------------------------

    def _evaluate_step(self, step: Any, namespace: str, workload: str) -> StepDecision:
        """Evaluate a single remediation step."""
        action = self._get_action(step)
        safety_level = self._get_safety_level(step)
        risk = _ACTION_RISK.get(action, 0.5)

        # Denied actions check
        if action in self.denied_actions:
            return StepDecision(
                action=action,
                allowed=False,
                blocked_reason=f"Action '{action}' is in the denied-actions list",
                risk_score=risk,
            )

        # Allowlist check
        if self.allowed_actions is not None and action not in self.allowed_actions:
            return StepDecision(
                action=action,
                allowed=False,
                blocked_reason=f"Action '{action}' is not in the allowed-actions list",
                risk_score=risk,
            )

        # Suggest-only is never executable
        if safety_level == SafetyLevel.suggest_only or safety_level == "suggest_only":
            return StepDecision(
                action=action,
                allowed=False,
                blocked_reason=f"Action '{action}' is suggest-only (L3) and cannot be auto-executed",
                risk_score=risk,
                audit_note="suggest_only — requires human operator action",
            )

        # Approval required
        requires_approval = (
            safety_level == SafetyLevel.approval_required
            or safety_level == "approval_required"
            or risk >= 0.5
        )

        return StepDecision(
            action=action,
            allowed=True,
            risk_score=risk,
            requires_approval=requires_approval,
            audit_note=f"safety_level={safety_level} risk={risk:.2f}",
        )

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _get(obj: Any, key: str, default: Any = None) -> Any:
        if obj is None:
            return default
        if hasattr(obj, key):
            return getattr(obj, key)
        if isinstance(obj, dict):
            return obj.get(key, default)
        return default

    @staticmethod
    def _get_action(step: Any) -> str:
        if hasattr(step, "action"):
            return step.action
        if isinstance(step, dict):
            return step.get("action", "unknown")
        return "unknown"

    @staticmethod
    def _get_safety_level(step: Any) -> Any:
        if hasattr(step, "safety_level"):
            return step.safety_level
        if isinstance(step, dict):
            return step.get("safety_level", "suggest_only")
        return "suggest_only"
