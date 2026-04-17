"""Slack integration — posts rich incident blocks to a configured channel.

Configuration (passed as dict or env vars)::

    SLACK_WEBHOOK_URL   — Incoming Webhook URL  (required)
    SLACK_CHANNEL       — Override channel      (optional; webhook default used otherwise)
    SLACK_ENABLED       — "true" / "false"      (default false)

Config dict keys: webhook_url, channel, enabled, mention_on_critical (user/group ID).
"""

from __future__ import annotations

import json
import logging
import os
import urllib.request
from typing import Any, Dict, Optional

from integrations.base import BaseIntegration, IntegrationResult

logger = logging.getLogger(__name__)

# Severity → Slack colour sidebar
_COLOUR = {
    "critical": "#E01E5A",
    "high": "#ECB22E",
    "medium": "#2EB67D",
    "low": "#36C5F0",
}


class SlackIntegration(BaseIntegration):
    """Posts incident and remediation notifications to Slack via Incoming Webhooks."""

    name = "slack"

    def __init__(self, config: Optional[Dict[str, Any]] = None) -> None:
        cfg = config or {}
        # Fall back to env vars
        cfg.setdefault("webhook_url", os.getenv("SLACK_WEBHOOK_URL", ""))
        cfg.setdefault("channel", os.getenv("SLACK_CHANNEL", ""))
        cfg.setdefault("enabled", os.getenv("SLACK_ENABLED", "false").lower() == "true")
        super().__init__(cfg)
        self._webhook_url: str = cfg["webhook_url"]
        self._channel: str = cfg.get("channel", "")
        self._mention: str = cfg.get("mention_on_critical", "")

    def validate_config(self) -> bool:
        if not super().validate_config():
            return False
        if not self._webhook_url:
            logger.warning("Slack integration enabled but SLACK_WEBHOOK_URL not set")
            return False
        return True

    # ------------------------------------------------------------------
    # BaseIntegration interface
    # ------------------------------------------------------------------

    def notify_incident(self, incident: Any) -> IntegrationResult:
        return self._safe_call(self._post_incident, incident)

    def notify_remediation(self, incident: Any, action: str, outcome: str) -> IntegrationResult:
        return self._safe_call(self._post_remediation, incident, action, outcome)

    def notify_resolved(self, incident: Any) -> IntegrationResult:
        return self._safe_call(self._post_resolved, incident)

    # ------------------------------------------------------------------
    # Block builders
    # ------------------------------------------------------------------

    def _post_incident(self, incident: Any) -> IntegrationResult:
        severity = getattr(incident, "severity", "medium")
        colour = _COLOUR.get(severity, "#AAAAAA")
        ns = getattr(incident, "namespace", "?")
        wl = getattr(incident, "workload", "?")
        itype = getattr(incident, "incident_type", "?")
        iid = getattr(incident, "id", "")
        confidence = getattr(incident, "confidence", 0.0)
        root_cause = getattr(incident, "root_cause", "") or ""

        mention = f"{self._mention} " if self._mention and severity == "critical" else ""

        text = f"{mention}*New {severity.upper()} incident detected* — `{ns}/{wl}`"
        attachments = [
            {
                "color": colour,
                "blocks": [
                    {
                        "type": "section",
                        "fields": [
                            {"type": "mrkdwn", "text": f"*Type:*\n{itype}"},
                            {"type": "mrkdwn", "text": f"*Confidence:*\n{confidence:.0%}"},
                            {"type": "mrkdwn", "text": f"*Namespace:*\n{ns}"},
                            {"type": "mrkdwn", "text": f"*Workload:*\n{wl}"},
                        ],
                    }
                ],
            }
        ]
        if root_cause:
            attachments[0]["blocks"].append(
                {
                    "type": "section",
                    "text": {"type": "mrkdwn", "text": f"*Root Cause:*\n{root_cause[:300]}"},
                }
            )

        payload: Dict[str, Any] = {"text": text, "attachments": attachments}
        if self._channel:
            payload["channel"] = self._channel

        return self._post(payload)

    def _post_remediation(self, incident: Any, action: str, outcome: str) -> IntegrationResult:
        icon = {"success": ":white_check_mark:", "failure": ":x:", "skipped": ":fast_forward:"}.get(
            outcome, ":grey_question:"
        )
        ns = getattr(incident, "namespace", "?")
        wl = getattr(incident, "workload", "?")
        text = f"{icon} Remediation *{outcome}* for `{ns}/{wl}`: `{action}`"
        payload: Dict[str, Any] = {"text": text}
        if self._channel:
            payload["channel"] = self._channel
        return self._post(payload)

    def _post_resolved(self, incident: Any) -> IntegrationResult:
        ns = getattr(incident, "namespace", "?")
        wl = getattr(incident, "workload", "?")
        text = f":green_circle: Incident resolved: `{ns}/{wl}`"
        payload: Dict[str, Any] = {"text": text}
        if self._channel:
            payload["channel"] = self._channel
        return self._post(payload)

    # ------------------------------------------------------------------
    # HTTP
    # ------------------------------------------------------------------

    def _post(self, payload: Dict[str, Any]) -> IntegrationResult:
        body = json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(
            self._webhook_url,
            data=body,
            headers={"Content-Type": "application/json"},
        )
        with urllib.request.urlopen(req, timeout=10) as resp:  # noqa: S310
            response_body = resp.read().decode("utf-8", errors="replace")
            if resp.status == 200 and response_body.strip() == "ok":
                return IntegrationResult(integration=self.name, success=True)
            return IntegrationResult(
                integration=self.name,
                success=False,
                error=f"HTTP {resp.status}: {response_body[:200]}",
            )
