"""Base class and result type for all external integrations."""

from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)


@dataclass
class IntegrationResult:
    """Outcome of dispatching a notification to an external system."""

    integration: str
    success: bool
    external_id: Optional[str] = None   # e.g. Slack ts, PD incident id, Jira key
    url: Optional[str] = None           # direct link to the created object
    error: Optional[str] = None
    metadata: Dict[str, Any] = field(default_factory=dict)

    def __repr__(self) -> str:
        if self.success:
            return f"<IntegrationResult {self.integration} ok id={self.external_id}>"
        return f"<IntegrationResult {self.integration} FAILED: {self.error}>"


class BaseIntegration(ABC):
    """Abstract base for notification / ticketing integrations."""

    name: str = "base"

    def __init__(self, config: Dict[str, Any]) -> None:
        self.config = config
        self._enabled = bool(config.get("enabled", False))

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    @property
    def enabled(self) -> bool:
        return self._enabled

    def validate_config(self) -> bool:
        """Return True if the integration is properly configured.

        Subclasses should call super() first, then check required keys.
        """
        return self._enabled

    # ------------------------------------------------------------------
    # Core interface
    # ------------------------------------------------------------------

    @abstractmethod
    def notify_incident(self, incident: Any) -> IntegrationResult:
        """Send a new-incident notification.

        Args:
            incident: An Incident model object.

        Returns:
            IntegrationResult describing success/failure.
        """

    @abstractmethod
    def notify_remediation(self, incident: Any, action: str, outcome: str) -> IntegrationResult:
        """Notify that a remediation was attempted.

        Args:
            incident: The associated Incident.
            action: Human-readable action description.
            outcome: "success" | "failure" | "skipped"
        """

    # ------------------------------------------------------------------
    # Optional hooks (no-ops by default)
    # ------------------------------------------------------------------

    def notify_resolved(self, incident: Any) -> IntegrationResult:
        """Called when an incident is marked resolved (optional)."""
        return IntegrationResult(integration=self.name, success=True)

    def _safe_call(self, fn, *args, **kwargs) -> IntegrationResult:
        """Wrap a call so network errors never crash the operator."""
        try:
            return fn(*args, **kwargs)
        except Exception as exc:
            logger.warning("%s integration error: %s", self.name, exc)
            return IntegrationResult(integration=self.name, success=False, error=str(exc))
