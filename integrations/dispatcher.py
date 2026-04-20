"""Integration dispatcher — fan-out notifications to all enabled integrations.

Usage::

    from integrations.dispatcher import IntegrationDispatcher

    dispatcher = IntegrationDispatcher.from_env()
    dispatcher.dispatch_incident(incident)
    dispatcher.dispatch_remediation(incident, "restart_pod", "success")
"""

from __future__ import annotations

import logging
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any, Dict, List, Optional

from integrations.base import BaseIntegration, IntegrationResult
from integrations.jira import JiraIntegration
from integrations.pagerduty import PagerDutyIntegration
from integrations.slack import SlackIntegration

logger = logging.getLogger(__name__)


class IntegrationDispatcher:
    """Fan-out notifications to all registered + enabled integrations.

    Each integration is called in a thread pool so a slow integration
    (e.g. Jira timeout) doesn't block the operator loop.
    """

    def __init__(
        self,
        integrations: Optional[List[BaseIntegration]] = None,
        max_workers: int = 4,
    ) -> None:
        self._integrations: List[BaseIntegration] = integrations or []
        self._executor = ThreadPoolExecutor(max_workers=max_workers, thread_name_prefix="sre-notif")

    # ------------------------------------------------------------------
    # Factory
    # ------------------------------------------------------------------

    @classmethod
    def from_env(cls) -> "IntegrationDispatcher":
        """Build a dispatcher from environment variables."""
        integrations: List[BaseIntegration] = [
            SlackIntegration(),
            PagerDutyIntegration(),
            JiraIntegration(),
        ]
        active = [i for i in integrations if i.validate_config()]
        logger.info(
            "IntegrationDispatcher: %d/%d integrations enabled (%s)",
            len(active),
            len(integrations),
            [i.name for i in active],
        )
        return cls(integrations=active)

    @classmethod
    def from_config(cls, config: Dict[str, Any]) -> "IntegrationDispatcher":
        """Build from a structured config dict.

        Expected format::

            {
                "slack":      {"enabled": true, "webhook_url": "...", ...},
                "pagerduty":  {"enabled": true, "routing_key": "...", ...},
                "jira":       {"enabled": false, ...},
            }
        """
        integrations: List[BaseIntegration] = []
        mapping = {
            "slack": SlackIntegration,
            "pagerduty": PagerDutyIntegration,
            "jira": JiraIntegration,
        }
        for key, cls_ in mapping.items():
            if key in config:
                integrations.append(cls_(config[key]))

        active = [i for i in integrations if i.validate_config()]
        return cls(integrations=active)

    # ------------------------------------------------------------------
    # Dispatch methods
    # ------------------------------------------------------------------

    def dispatch_incident(self, incident: Any) -> List[IntegrationResult]:
        """Notify all integrations of a new incident (non-blocking fan-out)."""
        return self._fanout("notify_incident", incident)

    def dispatch_remediation(
        self, incident: Any, action: str, outcome: str
    ) -> List[IntegrationResult]:
        """Notify all integrations of a remediation attempt."""
        return self._fanout("notify_remediation", incident, action, outcome)

    def dispatch_resolved(self, incident: Any) -> List[IntegrationResult]:
        """Notify all integrations that an incident was resolved."""
        return self._fanout("notify_resolved", incident)

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _fanout(self, method: str, *args) -> List[IntegrationResult]:
        if not self._integrations:
            return []

        futures = {
            self._executor.submit(getattr(integration, method), *args): integration
            for integration in self._integrations
        }
        results: List[IntegrationResult] = []
        for future in as_completed(futures, timeout=30):
            integration = futures[future]
            try:
                result = future.result()
                results.append(result)
                if not result.success:
                    logger.warning("%s dispatch failed: %s", integration.name, result.error)
                else:
                    logger.debug("%s dispatch ok id=%s", integration.name, result.external_id)
            except Exception as exc:
                logger.warning("%s dispatch exception: %s", integration.name, exc)
                results.append(
                    IntegrationResult(integration=integration.name, success=False, error=str(exc))
                )
        return results

    def add_integration(self, integration: BaseIntegration) -> None:
        """Register an additional integration at runtime."""
        if integration.validate_config():
            self._integrations.append(integration)

    def status(self) -> List[Dict[str, Any]]:
        """Return enabled-status for each registered integration."""
        return [
            {"name": i.name, "enabled": i.enabled}
            for i in self._integrations
        ]

    def __len__(self) -> int:
        return len(self._integrations)
