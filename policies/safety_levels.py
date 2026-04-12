"""Safety level definitions and default policy configuration."""
from __future__ import annotations

from models.remediation import SafetyLevel

# ---------------------------------------------------------------------------
# Action → safety level mapping
# ---------------------------------------------------------------------------

SAFETY_RULES = {
    "restart_pod": SafetyLevel.auto_fix,
    "rollout_restart": SafetyLevel.auto_fix,
    "rerun_job": SafetyLevel.auto_fix,
    "scale_up": SafetyLevel.auto_fix,  # within max_scale_up_pct
    "collect_diagnostics": SafetyLevel.auto_fix,
    "verify_recovery": SafetyLevel.auto_fix,
    "verify_secret_missing": SafetyLevel.auto_fix,
    "scale_down": SafetyLevel.approval_required,
    "rollback": SafetyLevel.approval_required,
    "rollback_deployment": SafetyLevel.approval_required,
    "patch_limits": SafetyLevel.approval_required,
    "patch_selector": SafetyLevel.approval_required,
    "patch_probes": SafetyLevel.approval_required,
    "patch_hpa": SafetyLevel.approval_required,
    "restart_coredns": SafetyLevel.approval_required,
    "recreate_secret": SafetyLevel.suggest_only,
    "rbac_changes": SafetyLevel.suggest_only,
    "create_role": SafetyLevel.suggest_only,
    "create_rolebinding": SafetyLevel.suggest_only,
    "network_policy": SafetyLevel.suggest_only,
    "storage_changes": SafetyLevel.suggest_only,
    "fix_cni": SafetyLevel.suggest_only,
    "fix_service_mesh": SafetyLevel.suggest_only,
    "node_drain": SafetyLevel.suggest_only,
    "increase_quota": SafetyLevel.suggest_only,
}

# ---------------------------------------------------------------------------
# Default operator policy settings
# ---------------------------------------------------------------------------

POLICY_DEFAULTS = {
    "max_scale_up_pct": 200,  # max 2x current replicas
    "max_scale_down_pct": 50,  # min 50% of current replicas
    "cooldown_secs": 300,
    "dry_run": True,
    "auto_fix_enabled": False,  # must explicitly enable
    "allowed_namespaces": [],  # empty = all
    "denied_namespaces": ["kube-system", "kube-public"],
}


def get_action_safety_level(action: str) -> SafetyLevel:
    """Look up the safety level for a given action name.

    Args:
        action: Action name string.

    Returns:
        SafetyLevel for the action (defaults to suggest_only for unknown actions).
    """
    return SAFETY_RULES.get(action, SafetyLevel.suggest_only)


def is_auto_fixable(action: str) -> bool:
    """Check if an action can be executed automatically.

    Args:
        action: Action name string.

    Returns:
        True if action is Level 1 (auto_fix).
    """
    return get_action_safety_level(action) == SafetyLevel.auto_fix


def requires_approval(action: str) -> bool:
    """Check if an action requires human approval before execution.

    Args:
        action: Action name string.

    Returns:
        True if action is Level 2 (approval_required) or Level 3 (suggest_only).
    """
    level = get_action_safety_level(action)
    return level in (SafetyLevel.approval_required, SafetyLevel.suggest_only)
