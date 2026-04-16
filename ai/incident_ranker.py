"""Incident ranker — sorts incidents by severity, urgency, and business impact."""

from __future__ import annotations

import json
import logging
from typing import Dict, List

from ai.llm import get_llm_client
from ai.prompts import RANKING_SYSTEM_PROMPT, RANKING_USER_TEMPLATE
from models.incident import Incident

logger = logging.getLogger(__name__)

SEVERITY_SCORES: Dict[str, float] = {
    "critical": 1.0,
    "high": 0.8,
    "medium": 0.5,
    "low": 0.3,
    "info": 0.1,
}

INCIDENT_TYPE_URGENCY: Dict[str, float] = {
    "CrashLoopBackOff": 0.9,
    "OOMKilled": 0.85,
    "ImagePullBackOff": 0.8,
    "ServiceMismatch": 0.85,
    "IngressFailure": 0.8,
    "PodPending": 0.7,
    "PVCFailure": 0.75,
    "ProbeFailure": 0.6,
    "HPAMisconfigured": 0.4,
    "NodePressure": 0.7,
    "FailedRollout": 0.75,
    "QuotaExceeded": 0.65,
    "DNSFailure": 0.9,
    "RBACDenied": 0.6,
    "NetworkPolicyBlock": 0.65,
    "CNIFailure": 0.85,
    "ServiceMeshFailure": 0.7,
    "StorageFailure": 0.75,
    "Unknown": 0.5,
}


class IncidentRanker:
    """Ranks incidents by urgency and business impact."""

    def __init__(self) -> None:
        """Initialise the incident ranker."""
        self.llm = get_llm_client()

    def rank(self, incidents: List[Incident]) -> List[Incident]:
        """Sort incidents by urgency, highest first.

        Args:
            incidents: List of Incident objects to rank.

        Returns:
            Incidents sorted by urgency score descending.
        """
        if not incidents:
            return incidents

        # Try AI ranking for small batches
        if len(incidents) <= 10:
            try:
                return self._rank_via_llm(incidents)
            except Exception as exc:
                logger.warning("AI ranking failed, falling back to rule-based: %s", exc)

        return self._rank_rule_based(incidents)

    def _rank_rule_based(self, incidents: List[Incident]) -> List[Incident]:
        """Sort incidents using deterministic scoring rules.

        Args:
            incidents: List of incidents to rank.

        Returns:
            Sorted list of incidents.
        """

        def score(incident: Incident) -> float:
            """Compute urgency score for a single incident."""
            severity_score = SEVERITY_SCORES.get(incident.severity.value, 0.5)
            type_score = INCIDENT_TYPE_URGENCY.get(incident.incident_type.value, 0.5)
            # Production namespace gets higher weight
            ns_multiplier = 1.2 if incident.namespace in ("production", "prod") else 1.0
            return (severity_score * 0.6 + type_score * 0.4) * ns_multiplier

        return sorted(incidents, key=score, reverse=True)

    def _rank_via_llm(self, incidents: List[Incident]) -> List[Incident]:
        """Use the LLM to rank incidents by business impact.

        Args:
            incidents: List of incidents to rank.

        Returns:
            LLM-ranked list of incidents.
        """
        incidents_json = json.dumps(
            [
                {
                    "id": inc.id,
                    "title": inc.title,
                    "type": inc.incident_type.value,
                    "severity": inc.severity.value,
                    "namespace": inc.namespace,
                    "workload": inc.workload,
                    "status": inc.status.value,
                }
                for inc in incidents
            ],
            indent=2,
        )

        raw = self.llm.chat(
            system=RANKING_SYSTEM_PROMPT,
            user=RANKING_USER_TEMPLATE.format(incidents_json=incidents_json),
        )

        try:
            ranked_data = json.loads(raw)
            id_to_incident = {inc.id: inc for inc in incidents}
            ranked = []
            for item in ranked_data:
                inc = id_to_incident.get(item.get("id"))
                if inc:
                    ranked.append(inc)
            # Add any missing incidents at the end
            ranked_ids = {inc.id for inc in ranked}
            for inc in incidents:
                if inc.id not in ranked_ids:
                    ranked.append(inc)
            return ranked
        except (json.JSONDecodeError, KeyError, TypeError):
            return self._rank_rule_based(incidents)

    def compute_urgency_score(self, incident: Incident) -> float:
        """Compute a 0-1 urgency score for a single incident.

        Args:
            incident: The incident to score.

        Returns:
            Float urgency score between 0 and 1.
        """
        severity_score = SEVERITY_SCORES.get(incident.severity.value, 0.5)
        type_score = INCIDENT_TYPE_URGENCY.get(incident.incident_type.value, 0.5)
        ns_multiplier = 1.2 if incident.namespace in ("production", "prod") else 1.0
        raw = (severity_score * 0.6 + type_score * 0.4) * ns_multiplier
        return min(1.0, raw)
