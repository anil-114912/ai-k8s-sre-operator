"""Tests for safety policies and guardrails."""
from __future__ import annotations

import os
import time
import pytest

from models.remediation import RemediationStep, SafetyLevel
from policies.namespace_policies import NamespacePolicy
from policies.action_allowlist import ActionAllowlist
from policies.safety_levels import SAFETY_RULES, get_action_safety_level, is_auto_fixable
from remediations.policy_guardrails import PolicyGuardrails


def make_step(
    action: str = "rollout_restart",
    safety_level: SafetyLevel = SafetyLevel.auto_fix,
    order: int = 1,
) -> RemediationStep:
    """Create a test RemediationStep."""
    return RemediationStep(
        order=order,
        action=action,
        description=f"Test step for {action}",
        safety_level=safety_level,
    )


class TestNamespacePolicy:
    """Tests for NamespacePolicy."""

    def test_denied_namespace_is_rejected(self):
        """kube-system should be denied."""
        policy = NamespacePolicy(denied_namespaces=["kube-system", "kube-public"])
        assert policy.is_allowed("kube-system") is False

    def test_allowed_namespace_passes(self):
        """production should be allowed by default."""
        policy = NamespacePolicy(denied_namespaces=["kube-system"])
        assert policy.is_allowed("production") is True

    def test_allowlist_restricts_namespaces(self):
        """When allowlist is set, only those namespaces should pass."""
        policy = NamespacePolicy(
            denied_namespaces=[],
            allowed_namespaces=["production", "staging"],
        )
        assert policy.is_allowed("production") is True
        assert policy.is_allowed("staging") is True
        assert policy.is_allowed("monitoring") is False

    def test_deny_reason_is_descriptive(self):
        """deny_reason should return a non-empty string for denied namespaces."""
        policy = NamespacePolicy(denied_namespaces=["kube-system"])
        reason = policy.deny_reason("kube-system")
        assert len(reason) > 0
        assert "kube-system" in reason


class TestActionAllowlist:
    """Tests for ActionAllowlist."""

    def test_known_action_is_permitted(self):
        """Standard actions should be in the allowlist."""
        allowlist = ActionAllowlist()
        assert allowlist.is_permitted("rollout_restart") is True
        assert allowlist.is_permitted("restart_pod") is True

    def test_unknown_action_is_denied(self):
        """Actions not in the allowlist should be denied."""
        allowlist = ActionAllowlist(allowed_actions=["rollout_restart"])
        assert allowlist.is_permitted("mystery_action") is False

    def test_custom_allowlist(self):
        """Custom allowlist should restrict to only listed actions."""
        allowlist = ActionAllowlist(allowed_actions=["rollout_restart", "scale_up"])
        assert allowlist.is_permitted("rollout_restart") is True
        assert allowlist.is_permitted("rollback") is False


class TestSafetyLevels:
    """Tests for safety level classification."""

    def test_restart_pod_is_auto_fix(self):
        """restart_pod should be Level 1 auto_fix."""
        assert get_action_safety_level("restart_pod") == SafetyLevel.auto_fix

    def test_rollback_requires_approval(self):
        """rollback should require approval."""
        assert get_action_safety_level("rollback") == SafetyLevel.approval_required

    def test_rbac_changes_is_suggest_only(self):
        """rbac_changes should be suggest_only."""
        assert get_action_safety_level("rbac_changes") == SafetyLevel.suggest_only

    def test_unknown_action_defaults_to_suggest_only(self):
        """Unknown actions should default to suggest_only for safety."""
        assert get_action_safety_level("unknown_dangerous_action") == SafetyLevel.suggest_only

    def test_is_auto_fixable(self):
        """is_auto_fixable should correctly identify Level 1 actions."""
        assert is_auto_fixable("rollout_restart") is True
        assert is_auto_fixable("rollback") is False
        assert is_auto_fixable("rbac_changes") is False


class TestPolicyGuardrails:
    """Tests for PolicyGuardrails."""

    def test_rejects_denied_namespace(self):
        """Guardrails should block actions in denied namespaces."""
        guardrails = PolicyGuardrails(
            namespace_policy=NamespacePolicy(denied_namespaces=["kube-system"]),
            dry_run=True,
        )
        step = make_step("rollout_restart", SafetyLevel.auto_fix)
        allowed, reason = guardrails.validate(step, "kube-system", "some-deployment")
        assert allowed is False
        assert "denied" in reason.lower() or "kube-system" in reason

    def test_allows_valid_namespace_and_action(self):
        """Guardrails should allow valid namespace + auto_fix action."""
        guardrails = PolicyGuardrails(
            namespace_policy=NamespacePolicy(denied_namespaces=["kube-system"]),
            dry_run=True,
            cooldown_secs=0,
        )
        step = make_step("rollout_restart", SafetyLevel.auto_fix)
        allowed, reason = guardrails.validate(step, "production", "payment-api")
        assert allowed is True

    def test_rejects_suggest_only_actions(self):
        """Guardrails should block suggest_only actions from execution."""
        guardrails = PolicyGuardrails(dry_run=False, cooldown_secs=0)
        step = make_step("rbac_changes", SafetyLevel.suggest_only)
        allowed, reason = guardrails.validate(step, "production", "app")
        assert allowed is False
        assert "suggest-only" in reason.lower() or "Level 3" in reason or "suggest_only" in reason.lower() or "cannot be auto-executed" in reason.lower()

    def test_cooldown_blocks_repeated_execution(self):
        """Guardrails should enforce cooldown between executions on the same workload."""
        guardrails = PolicyGuardrails(
            cooldown_secs=3600,  # 1 hour cooldown
            dry_run=False,
        )
        # Record a recent execution
        import remediations.policy_guardrails as pg
        pg._cooldown_tracker["production/payment-api"] = time.time()

        step = make_step("rollout_restart", SafetyLevel.auto_fix)
        allowed, reason = guardrails.validate(step, "production", "payment-api")
        assert allowed is False
        assert "cooldown" in reason.lower()

    def test_dry_run_mode_always_simulates(self):
        """In dry_run mode, execution should return a DRY RUN message."""
        guardrails = PolicyGuardrails(dry_run=True, cooldown_secs=0)
        step = make_step("rollout_restart", SafetyLevel.auto_fix)
        result = guardrails.execute_with_guardrails(
            step,
            "production",
            "payment-api",
            lambda: "real_execution",
        )
        assert result["dry_run"] is True
        assert "DRY RUN" in result["output"]

    def test_unknown_action_blocked_by_suggest_only(self):
        """An action not in the allowlist defaults to suggest_only and should be blocked."""
        guardrails = PolicyGuardrails(
            action_allowlist=ActionAllowlist(allowed_actions=["rollout_restart"]),
            dry_run=False,
            cooldown_secs=0,
        )
        step = make_step("mystery_action", SafetyLevel.auto_fix)
        allowed, reason = guardrails.validate(step, "production", "app")
        assert allowed is False
