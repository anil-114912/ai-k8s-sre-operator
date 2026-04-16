"""Action allowlist — which remediation actions are permitted."""

from __future__ import annotations

import logging
from typing import List, Set

from models.remediation import SafetyLevel
from policies.safety_levels import SAFETY_RULES

logger = logging.getLogger(__name__)

# Default set of all known actions (all are in safety_levels)
ALL_KNOWN_ACTIONS: Set[str] = set(SAFETY_RULES.keys())

# Actions that can never be executed automatically regardless of policy
ALWAYS_SUGGEST_ONLY: Set[str] = {
    "rbac_changes",
    "network_policy",
    "storage_changes",
    "recreate_secret",
}


class ActionAllowlist:
    """Controls which actions are permitted and at what safety level."""

    def __init__(
        self,
        allowed_actions: List[str] = None,
        override_levels: dict = None,
    ) -> None:
        """Initialise the allowlist.

        Args:
            allowed_actions: Explicit list of permitted actions. None = all known.
            override_levels: Optional dict to override default safety levels.
        """
        self._allowed: Set[str] = (
            set(allowed_actions) if allowed_actions is not None else ALL_KNOWN_ACTIONS
        )
        self._overrides: dict = override_levels or {}

    def is_permitted(self, action: str) -> bool:
        """Check if an action is on the allowlist.

        Args:
            action: Action name string.

        Returns:
            True if the action is permitted.
        """
        permitted = action in self._allowed
        if not permitted:
            logger.warning("Action '%s' is not in the allowlist", action)
        return permitted

    def get_safety_level(self, action: str) -> SafetyLevel:
        """Get the effective safety level for an action (with overrides applied).

        Args:
            action: Action name string.

        Returns:
            SafetyLevel for the action.
        """
        if action in self._overrides:
            return self._overrides[action]
        return SAFETY_RULES.get(action, SafetyLevel.suggest_only)

    @property
    def allowed_actions(self) -> List[str]:
        """Return the list of all allowed action names."""
        return sorted(self._allowed)
