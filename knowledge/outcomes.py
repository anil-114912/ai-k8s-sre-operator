"""Remediation outcome store — records what was executed and whether it worked."""

from __future__ import annotations

import logging
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Dict, List, Optional

logger = logging.getLogger(__name__)


@dataclass
class RemediationOutcome:
    """A single recorded remediation outcome."""

    incident_id: str
    action: str                      # e.g. "restart_pod", "rollback"
    incident_type: str               # e.g. "CrashLoopBackOff"
    namespace: str
    workload: str
    success: bool
    partial: bool = False            # True when partially worked
    feedback_notes: str = ""
    executed_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    confidence_at_time: float = 0.0  # RCA confidence when remediation ran


class OutcomeStore:
    """In-memory outcome store with optional SQLite persistence via IncidentStore.

    This class is intentionally lightweight — it aggregates outcomes and
    provides success-rate queries used by RemediationRanker.  The full
    persistence of remediation records lives in IncidentStore's
    ``RemediationOutcomeRecord`` table; OutcomeStore is a fast read-through
    cache on top of it.
    """

    def __init__(self) -> None:
        # action → list of outcomes
        self._by_action: Dict[str, List[RemediationOutcome]] = defaultdict(list)
        # incident_type → action → list of outcomes
        self._by_type_action: Dict[str, Dict[str, List[RemediationOutcome]]] = defaultdict(
            lambda: defaultdict(list)
        )
        # incident_id → list of outcomes
        self._by_incident: Dict[str, List[RemediationOutcome]] = defaultdict(list)

    # ------------------------------------------------------------------
    # Write
    # ------------------------------------------------------------------

    def record(
        self,
        incident_id: str,
        action: str,
        incident_type: str,
        namespace: str,
        workload: str,
        success: bool,
        partial: bool = False,
        feedback_notes: str = "",
        confidence_at_time: float = 0.0,
    ) -> RemediationOutcome:
        """Record a remediation outcome.

        Args:
            incident_id: The incident this remediation was for.
            action: The action that was executed (e.g. "restart_pod").
            incident_type: The incident type (e.g. "CrashLoopBackOff").
            namespace: Kubernetes namespace.
            workload: Workload name.
            success: True if the remediation resolved the incident.
            partial: True if the remediation partially helped.
            feedback_notes: Operator notes.
            confidence_at_time: RCA confidence score when remediation ran.

        Returns:
            The created RemediationOutcome.
        """
        outcome = RemediationOutcome(
            incident_id=incident_id,
            action=action,
            incident_type=incident_type,
            namespace=namespace,
            workload=workload,
            success=success,
            partial=partial,
            feedback_notes=feedback_notes,
            confidence_at_time=confidence_at_time,
        )

        self._by_action[action].append(outcome)
        self._by_type_action[incident_type][action].append(outcome)
        self._by_incident[incident_id].append(outcome)

        logger.info(
            "Outcome recorded: action=%s incident_type=%s success=%s namespace=%s/%s",
            action,
            incident_type,
            success,
            namespace,
            workload,
        )
        return outcome

    # ------------------------------------------------------------------
    # Read
    # ------------------------------------------------------------------

    def get_for_incident(self, incident_id: str) -> List[RemediationOutcome]:
        """Return all outcomes recorded for a specific incident."""
        return list(self._by_incident.get(incident_id, []))

    def get_success_rate(self, action: str) -> float:
        """Return the historical success rate (0.0–1.0) for an action.

        Returns 0.5 (neutral) if there is no history for this action.
        """
        outcomes = self._by_action.get(action, [])
        if not outcomes:
            return 0.5  # No data — use neutral prior
        successes = sum(1 for o in outcomes if o.success)
        return successes / len(outcomes)

    def get_success_rate_for_type(self, action: str, incident_type: str) -> float:
        """Return the success rate for an action specifically for this incident type.

        Falls back to the global action success rate if no type-specific data.
        """
        type_outcomes = self._by_type_action.get(incident_type, {}).get(action, [])
        if not type_outcomes:
            return self.get_success_rate(action)
        successes = sum(1 for o in type_outcomes if o.success)
        return successes / len(type_outcomes)

    def get_all_action_rates(self) -> Dict[str, float]:
        """Return a dict of {action: success_rate} for all observed actions."""
        return {action: self.get_success_rate(action) for action in self._by_action}

    def total_recorded(self) -> int:
        """Return the total number of outcome records."""
        return sum(len(v) for v in self._by_action.values())

    def get_all_stats(self) -> Dict[str, Any]:
        """Return stats for all actions and incident types.

        Returns:
            Dict mapping action names to their success rates and counts.
        """
        stats: Dict[str, Any] = {}
        for action, outcomes in self._by_action.items():
            successes = sum(1 for o in outcomes if o.success)
            stats[action] = {
                "action": action,
                "total": len(outcomes),
                "successes": successes,
                "success_rate": round(successes / len(outcomes), 3) if outcomes else 0.5,
            }
        return stats

    def load_from_store(self, incident_store: Optional[object] = None) -> int:
        """Populate the cache from the persistent IncidentStore.

        Args:
            incident_store: An IncidentStore instance to load from.

        Returns:
            Number of outcomes loaded.
        """
        if incident_store is None:
            return 0
        loaded = 0
        try:
            records = incident_store.list_remediation_outcomes()
            for rec in records:
                self._by_action[rec.get("action", "unknown")].append(
                    RemediationOutcome(
                        incident_id=rec.get("incident_id", ""),
                        action=rec.get("action", "unknown"),
                        incident_type=rec.get("incident_type", "Unknown"),
                        namespace=rec.get("namespace", ""),
                        workload=rec.get("workload", ""),
                        success=rec.get("success", False),
                    )
                )
                loaded += 1
        except Exception as exc:
            logger.warning("Failed to load outcomes from store: %s", exc)
        logger.info("OutcomeStore loaded %d outcome records", loaded)
        return loaded
