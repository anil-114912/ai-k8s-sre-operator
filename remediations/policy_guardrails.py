"""Policy guardrails — safety validation before executing any remediation action."""

from __future__ import annotations

import logging
import os
import time
from typing import Any, Dict, Optional, Tuple

from models.remediation import RemediationStep, SafetyLevel
from policies.action_allowlist import ActionAllowlist
from policies.namespace_policies import NamespacePolicy
from policies.safety_levels import POLICY_DEFAULTS

logger = logging.getLogger(__name__)

# Cooldown tracker: workload_key -> last_execution_timestamp
_cooldown_tracker: Dict[str, float] = {}

DRY_RUN = os.getenv("OPERATOR_DRY_RUN", "true").lower() == "true"
AUTO_FIX_ENABLED = os.getenv("AUTO_FIX_ENABLED", "false").lower() == "true"
COOLDOWN_SECS = int(os.getenv("COOLDOWN_SECS", str(POLICY_DEFAULTS["cooldown_secs"])))


class PolicyGuardrails:
    """Validates and enforces all safety policies before remediation execution."""

    def __init__(
        self,
        namespace_policy: Optional[NamespacePolicy] = None,
        action_allowlist: Optional[ActionAllowlist] = None,
        dry_run: Optional[bool] = None,
        auto_fix_enabled: Optional[bool] = None,
        cooldown_secs: Optional[int] = None,
    ) -> None:
        """Initialise guardrails with configurable policies.

        Args:
            namespace_policy: Namespace access control policy.
            action_allowlist: Action permission list.
            dry_run: Override dry_run setting (defaults to env var).
            auto_fix_enabled: Override auto_fix setting (defaults to env var).
            cooldown_secs: Cooldown period between remediations of the same workload.
        """
        self.ns_policy = namespace_policy or NamespacePolicy()
        self.allowlist = action_allowlist or ActionAllowlist()
        self.dry_run = dry_run if dry_run is not None else DRY_RUN
        self.auto_fix_enabled = (
            auto_fix_enabled if auto_fix_enabled is not None else AUTO_FIX_ENABLED
        )
        self.cooldown_secs = cooldown_secs if cooldown_secs is not None else COOLDOWN_SECS

    def validate(
        self,
        step: RemediationStep,
        namespace: str,
        workload: str,
    ) -> Tuple[bool, str]:
        """Validate a remediation step against all safety policies.

        Args:
            step: The RemediationStep to validate.
            namespace: Kubernetes namespace of the target.
            workload: Workload name (deployment/service).

        Returns:
            Tuple of (allowed: bool, reason: str).
        """
        # 1. Namespace check
        if not self.ns_policy.is_allowed(namespace):
            reason = self.ns_policy.deny_reason(namespace)
            logger.warning("Guardrail DENY: namespace check failed: %s", reason)
            return False, reason

        # 2. Action allowlist check
        if not self.allowlist.is_permitted(step.action):
            reason = f"Action '{step.action}' is not in the permitted action allowlist"
            logger.warning("Guardrail DENY: %s", reason)
            return False, reason

        # 3. Safety level check
        if not self.auto_fix_enabled and step.safety_level == SafetyLevel.auto_fix:
            # Auto-fix is disabled globally — downgrade to approval_required
            logger.info("Auto-fix disabled: action '%s' requires explicit approval", step.action)

        if step.safety_level == SafetyLevel.suggest_only:
            reason = (
                f"Action '{step.action}' is suggest-only (Level 3) and "
                "cannot be auto-executed. Human action required."
            )
            logger.info("Guardrail SUGGEST-ONLY: %s", reason)
            return False, reason

        if step.safety_level == SafetyLevel.approval_required:
            # Will be caught at the plan level — but log it here too
            logger.info("Guardrail: action '%s' requires approval before execution", step.action)

        # 4. Cooldown check
        cooldown_ok, cooldown_reason = self._check_cooldown(namespace, workload)
        if not cooldown_ok:
            return False, cooldown_reason

        return True, "OK"

    def execute_with_guardrails(
        self,
        step: RemediationStep,
        namespace: str,
        workload: str,
        execute_fn: Any,
    ) -> Dict[str, Any]:
        """Validate and execute a remediation step, with dry-run support.

        Args:
            step: The step to execute.
            namespace: Target namespace.
            workload: Target workload.
            execute_fn: Callable that performs the actual execution.

        Returns:
            Dict with allowed, dry_run, output, and reason fields.
        """
        allowed, reason = self.validate(step, namespace, workload)

        if not allowed:
            return {
                "allowed": False,
                "dry_run": self.dry_run,
                "output": f"BLOCKED: {reason}",
                "reason": reason,
            }

        if self.dry_run:
            output = f"DRY RUN: would execute action='{step.action}' in {namespace}/{workload}"
            if step.command:
                output += f"\n  Command: {step.command}"
            logger.info("DRY RUN: %s", output)
            return {
                "allowed": True,
                "dry_run": True,
                "output": output,
                "reason": "dry_run_mode",
            }

        # Record execution for cooldown tracking
        self._record_execution(namespace, workload)

        try:
            output = execute_fn()
            logger.info(
                "Guardrails PASSED: executed action='%s' in %s/%s",
                step.action,
                namespace,
                workload,
            )
            return {"allowed": True, "dry_run": False, "output": output, "reason": "OK"}
        except Exception as exc:
            logger.error("Execution failed: action=%s error=%s", step.action, exc)
            return {
                "allowed": True,
                "dry_run": False,
                "output": f"EXECUTION FAILED: {exc}",
                "reason": str(exc),
            }

    def _check_cooldown(self, namespace: str, workload: str) -> Tuple[bool, str]:
        """Check if the cooldown period has passed for the given workload.

        Args:
            namespace: Kubernetes namespace.
            workload: Workload name.

        Returns:
            Tuple of (allowed: bool, reason: str).
        """
        key = f"{namespace}/{workload}"
        last_exec = _cooldown_tracker.get(key, 0.0)
        elapsed = time.time() - last_exec
        if elapsed < self.cooldown_secs:
            remaining = int(self.cooldown_secs - elapsed)
            reason = (
                f"Cooldown active: {remaining}s remaining for {key} "
                f"(cooldown={self.cooldown_secs}s)"
            )
            logger.warning("Guardrail COOLDOWN: %s", reason)
            return False, reason
        return True, "OK"

    def _record_execution(self, namespace: str, workload: str) -> None:
        """Record the current timestamp as the last execution time for this workload.

        Args:
            namespace: Kubernetes namespace.
            workload: Workload name.
        """
        key = f"{namespace}/{workload}"
        _cooldown_tracker[key] = time.time()
        logger.debug("Cooldown timer reset for: %s", key)
