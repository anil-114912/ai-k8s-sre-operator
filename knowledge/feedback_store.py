"""Remediation outcome feedback tracker with extended analytics."""
from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Dict, Optional

from knowledge.incident_store import IncidentStore

logger = logging.getLogger(__name__)


@dataclass
class FeedbackRecord:
    """A structured feedback record for an incident analysis and remediation."""

    incident_id: str
    correct_root_cause: bool
    fix_worked: bool
    operator_notes: str
    better_remediation: Optional[str]
    feedback_at: str


class FeedbackStore:
    """Stores and retrieves operator feedback on remediation outcomes."""

    def __init__(self, store: IncidentStore) -> None:
        """Initialise with a shared IncidentStore.

        Args:
            store: The backing IncidentStore instance.
        """
        self._store = store
        # In-memory cache of structured feedback records (keyed by incident_id)
        self._feedback_cache: Dict[str, FeedbackRecord] = {}

    def record_feedback(
        self,
        incident_id: str,
        plan_summary: str,
        success: bool,
        feedback_notes: str = "",
    ) -> None:
        """Record operator feedback for a remediation execution.

        Args:
            incident_id: The incident ID.
            plan_summary: Short description of the plan executed.
            success: True if the remediation resolved the incident.
            feedback_notes: Any operator comments.
        """
        self._store.save_remediation_outcome(
            incident_id=incident_id,
            plan_summary=plan_summary,
            success=success,
            feedback_notes=feedback_notes,
        )
        # Also update the incident's feedback_score in the store
        self._store.update_feedback(incident_id, success, feedback_notes)
        logger.info(
            "Feedback recorded: incident=%s success=%s", incident_id, success
        )

    def submit_feedback(
        self,
        incident_id: str,
        correct_root_cause: bool,
        fix_worked: bool,
        operator_notes: str = "",
        better_remediation: Optional[str] = None,
    ) -> FeedbackRecord:
        """Submit structured feedback on incident RCA and remediation quality.

        Args:
            incident_id: The incident UUID.
            correct_root_cause: Whether the AI-generated root cause was correct.
            fix_worked: Whether the suggested fix resolved the incident.
            operator_notes: Free-text operator comments.
            better_remediation: Optional improved remediation text from the operator.

        Returns:
            The created FeedbackRecord.
        """
        record = FeedbackRecord(
            incident_id=incident_id,
            correct_root_cause=correct_root_cause,
            fix_worked=fix_worked,
            operator_notes=operator_notes,
            better_remediation=better_remediation,
            feedback_at=datetime.utcnow().isoformat(),
        )
        self._feedback_cache[incident_id] = record

        # Persist success/failure into the incident store
        self._store.update_feedback(incident_id, fix_worked, operator_notes)

        # Also save as a remediation outcome for backward compatibility
        self._store.save_remediation_outcome(
            incident_id=incident_id,
            plan_summary=operator_notes or "operator feedback",
            success=fix_worked,
            feedback_notes=operator_notes,
        )

        logger.info(
            "Structured feedback submitted: incident=%s correct_rca=%s fix_worked=%s",
            incident_id, correct_root_cause, fix_worked,
        )
        return record

    def get_feedback_for_incident(self, incident_id: str) -> Optional[FeedbackRecord]:
        """Retrieve structured feedback for a specific incident.

        Args:
            incident_id: The incident UUID.

        Returns:
            FeedbackRecord if available, else None.
        """
        return self._feedback_cache.get(incident_id)

    def get_success_rate(self) -> Dict[str, Any]:
        """Compute overall remediation success rate from stored outcomes.

        Returns:
            Dict with total, success_count, and success_rate fields.
        """
        incidents = self._store.list_incidents(limit=1000)
        resolved = sum(1 for inc in incidents if inc.get("resolved"))
        total = len(incidents)
        rate = resolved / total if total > 0 else 0.0
        return {
            "total_incidents": total,
            "resolved_incidents": resolved,
            "success_rate": round(rate, 3),
        }

    def get_accuracy_stats(self) -> Dict[str, Any]:
        """Compute RCA accuracy and fix success statistics from feedback.

        Returns:
            Dict with: total_analyzed, correct_rca_pct, fix_success_pct, top_failure_types.
        """
        incidents = self._store.list_incidents(limit=1000)
        total = len(incidents)

        if total == 0:
            return {
                "total_analyzed": 0,
                "correct_rca_pct": 0.0,
                "fix_success_pct": 0.0,
                "top_failure_types": [],
            }

        # Count resolved (positive feedback_score) vs failed
        with_positive_feedback = sum(
            1 for inc in incidents
            if (inc.get("feedback_score") or 0.0) > 0
        )
        with_negative_feedback = sum(
            1 for inc in incidents
            if (inc.get("feedback_score") or 0.0) < 0
        )
        feedback_total = with_positive_feedback + with_negative_feedback

        fix_success_pct = (
            with_positive_feedback / feedback_total * 100
            if feedback_total > 0 else 0.0
        )

        # Use structured feedback cache for RCA accuracy
        correct_rca_count = sum(
            1 for rec in self._feedback_cache.values()
            if rec.correct_root_cause
        )
        cache_total = len(self._feedback_cache)
        correct_rca_pct = (
            correct_rca_count / cache_total * 100 if cache_total > 0 else 0.0
        )

        # Compute top failure types
        type_counts: Dict[str, int] = {}
        for inc in incidents:
            inc_type = inc.get("type", "Unknown")
            type_counts[inc_type] = type_counts.get(inc_type, 0) + 1
        top_failure_types = sorted(
            [{"type": t, "count": c} for t, c in type_counts.items()],
            key=lambda x: x["count"],
            reverse=True,
        )[:5]

        return {
            "total_analyzed": total,
            "correct_rca_pct": round(correct_rca_pct, 1),
            "fix_success_pct": round(fix_success_pct, 1),
            "top_failure_types": top_failure_types,
        }
