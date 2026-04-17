"""External notification and ticketing integrations — Slack, PagerDuty, Jira."""

from integrations.base import BaseIntegration, IntegrationResult
from integrations.dispatcher import IntegrationDispatcher

__all__ = ["BaseIntegration", "IntegrationResult", "IntegrationDispatcher"]
