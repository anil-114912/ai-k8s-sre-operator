"""PagerDuty integration — creates and resolves incidents via Events API v2.

Configuration::

    PAGERDUTY_ROUTING_KEY   — Integration key (required)
    PAGERDUTY_ENABLED       — "true" / "false"

Config dict keys: routing_key, enabled, source (defaults to "ai-k8s-sre-operator").
"""

from __future__ import annotations

import json
import logging
import os
import urllib.request
from typing import Any, Dict, Optional

from integrations.base import BaseIntegration, IntegrationResult

logger = logging.getLogger(__name__)

_EVENTS_API = "https://events.pagerduty.com/v2/enqueue"

# Incident severity → PD severity
_PD_SEVERITY = {
    "critical": "critical",
    "high": "error",
    "medium": "warning",
    "low": "info",
}


class PagerDutyIntegration(BaseIntegration):
    """Triggers and resolves PagerDuty alerts via Events API v2."""

    name = "pagerduty"

    def __init__(self, config: Optional[Dict[str, Any]] = None) -> None:
        cfg = config or {}
        cfg.setdefault("routing_key", os.getenv("PAGERDUTY_ROUTING_KEY", ""))
        cfg.setdefault("enabled", os.getenv("PAGERDUTY_ENABLED", "false").lower() == "true")
        cfg.setdefault("source", "ai-k8s-sre-operator")
        super().__init__(cfg)
        self._routing_key: str = cfg["routing_key"]
        self._source: str = cfg["source"]

    def validate_config(self) -> bool:
        if not super().validate_config():
            return False
        if not self._routing_key:
            logger.warning("PagerDuty integration enabled but PAGERDUTY_ROUTING_KEY not set")
            return False
        return True

    # ------------------------------------------------------------------
    # BaseIntegration interface
    # ------------------------------------------------------------------

    def notify_incident(self, incident: Any) -> IntegrationResult:
        return self._safe_call(self._trigger, incident)

    def notify_remediation(self, incident: Any, action: str, outcome: str) -> IntegrationResult:
        # PagerDuty doesn't get a separate remediation event — acknowledge on success
        if outcome == "success":
            return self._safe_call(self._acknowledge, incident)
        return IntegrationResult(integration=self.name, success=True)

    def notify_resolved(self, incident: Any) -> IntegrationResult:
        return self._safe_call(self._resolve, incident)

    # ------------------------------------------------------------------
    # Event builders
    # ------------------------------------------------------------------

    def _dedup_key(self, incident: Any) -> str:
        """Stable dedup key so repeated fires don't create duplicate PD incidents."""
        iid = getattr(incident, "id", "")
        ns = getattr(incident, "namespace", "")
        wl = getattr(incident, "workload", "")
        return f"sre-operator-{ns}-{wl}-{iid}"[:255]

    def _trigger(self, incident: Any) -> IntegrationResult:
        severity = getattr(incident, "severity", "medium")
        ns = getattr(incident, "namespace", "?")
        wl = getattr(incident, "workload", "?")
        itype = getattr(incident, "incident_type", "?")
        confidence = getattr(incident, "confidence", 0.0)
        root_cause = getattr(incident, "root_cause", "") or ""

        payload = {
            "routing_key": self._routing_key,
            "event_action": "trigger",
            "dedup_key": self._dedup_key(incident),
            "payload": {
                "summary": f"[{severity.upper()}] {itype} in {ns}/{wl}",
                "source": self._source,
                "severity": _PD_SEVERITY.get(severity, "warning"),
                "custom_details": {
                    "namespace": ns,
                    "workload": wl,
                    "incident_type": itype,
                    "confidence": f"{confidence:.0%}",
                    "root_cause": root_cause[:500],
                    "incident_id": getattr(incident, "id", ""),
                },
            },
        }
        return self._post(payload)

    def _acknowledge(self, incident: Any) -> IntegrationResult:
        payload = {
            "routing_key": self._routing_key,
            "event_action": "acknowledge",
            "dedup_key": self._dedup_key(incident),
        }
        return self._post(payload)

    def _resolve(self, incident: Any) -> IntegrationResult:
        payload = {
            "routing_key": self._routing_key,
            "event_action": "resolve",
            "dedup_key": self._dedup_key(incident),
        }
        return self._post(payload)

    # ------------------------------------------------------------------
    # HTTP
    # ------------------------------------------------------------------

    def _post(self, payload: Dict[str, Any]) -> IntegrationResult:
        body = json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(
            _EVENTS_API,
            data=body,
            headers={"Content-Type": "application/json"},
        )
        with urllib.request.urlopen(req, timeout=10) as resp:  # noqa: S310
            response_body = resp.read().decode("utf-8", errors="replace")
            try:
                data = json.loads(response_body)
            except json.JSONDecodeError:
                data = {}

            if resp.status in (200, 202):
                return IntegrationResult(
                    integration=self.name,
                    success=True,
                    external_id=data.get("dedup_key") or data.get("incident_key"),
                )
            return IntegrationResult(
                integration=self.name,
                success=False,
                error=f"HTTP {resp.status}: {response_body[:200]}",
            )
