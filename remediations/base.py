"""Base remediation abstraction."""

from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from typing import Any, Dict

from models.remediation import RemediationResult

logger = logging.getLogger(__name__)


class BaseRemediation(ABC):
    """Abstract base class for all remediation executors."""

    name: str = "base"
    description: str = "Base remediation"

    @abstractmethod
    def execute(
        self,
        incident_id: str,
        plan_id: str,
        params: Dict[str, Any],
        dry_run: bool = True,
    ) -> RemediationResult:
        """Execute the remediation action.

        Args:
            incident_id: The incident this remediation belongs to.
            plan_id: The remediation plan ID.
            params: Action-specific parameters (namespace, workload, etc.).
            dry_run: If True, simulate the action without making real changes.

        Returns:
            RemediationResult with success status and output.
        """
        ...

    def _dry_run_result(
        self,
        incident_id: str,
        plan_id: str,
        action: str,
        command: str,
    ) -> RemediationResult:
        """Return a dry-run simulation result.

        Args:
            incident_id: Parent incident ID.
            plan_id: Remediation plan ID.
            action: Action name.
            command: The command that would be executed.

        Returns:
            RemediationResult indicating a dry-run simulation.
        """
        return RemediationResult(
            plan_id=plan_id,
            incident_id=incident_id,
            executed_steps=[action],
            success=True,
            output=f"DRY RUN: would execute `{command}`",
            duration_secs=0.0,
        )
