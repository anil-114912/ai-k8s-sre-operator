"""Remediation outcome feedback tracker with DB-backed structured feedback."""
from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Dict, List, Optional

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
    """Stores and retrieves operator feedback on remediation outcomes.

    All structured feedback is persisted to the `structured_feedback` table
    in the database via IncidentStore. No data is lost on restart.
    """

    def __init__(self, store: IncidentStore) -> None:
        self._store = store

    def record_feedback(
        self,
        incident_id: str,
        plan_summary: str,
        success: bool,
        feedback_notes: str = "",
    ) -> None:
        """Record basic operator feedback for a remediation execution.

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
        self._store.update_feedback(incident_id, success, feedback_notes)
        logger.info("Feedback recorded: incident=%s success=%s", incident_id, success)

    def submit_feedback(
        self,
        incident_id: str,
        correct_root_cause: bool,
        fix_worked: bool,
        operator_notes: str = "",
        better_remediation: Optional[str] = None,
    ) -> FeedbackRecord:
        """Submit structured feedback — persisted to the structured_feedback table.

        Args:
            incident_id: The incident UUID.
            correct_root_cause: Whether the AI-generated root cause was correct.
            fix_worked: Whether the suggested fix resolved the incident.
            operator_notes: Free-text operator comments.
            better_remediation: Optional improved remediation text from the operator.

        Returns:
            The created FeedbackRecord.
        """
        # Persist to structured_feedback table
        self._store.save_structured_feedback(
            incident_id=incident_id,
            correct_root_cause=correct_root_cause,
            fix_worked=fix_worked,
            operator_notes=operator_notes,
            better_remediation=better_remediation,
        )

        # Also update the incident's feedback_score
        self._store.update_feedback(incident_id, fix_worked, operator_notes)

        # Also save as a remediation outcome for backward compatibility
        self._store.save_remediation_outcome(
            incident_id=incident_id,
            plan_summary=operator_notes or "operator feedback",
            success=fix_worked,
            feedback_notes=operator_notes,
        )

        record = FeedbackRecord(
            incident_id=incident_id,
            correct_root_cause=correct_root_cause,
            fix_worked=fix_worked,
            operator_notes=operator_notes,
            better_remediation=better_remediation,
            feedback_at=datetime.utcnow().isoformat(),
        )

        logger.info(
            "Structured feedback submitted: incident=%s correct_rca=%s fix_worked=%s",
            incident_id, correct_root_cause, fix_worked,
        )
        return record

    def get_feedback_for_incident(self, incident_id: str) -> Optional[FeedbackRecord]:
        """Retrieve structured feedback for a specific incident from the DB.

        Args:
            incident_id: The incident UUID.

        Returns:
            FeedbackRecord if available, else None.
        """
        row = self._store.get_structured_feedback(incident_id)
        if not row:
            return None
        return FeedbackRecord(
            incident_id=row["incident_id"],
            correct_root_cause=row["correct_root_cause"],
            fix_worked=row["fix_worked"],
            operator_notes=row.get("operator_notes", ""),
            better_remediation=row.get("better_remediation"),
            feedback_at=row.get("created_at", ""),
        )

    def list_feedback(self, limit: int = 100) -> List[FeedbackRecord]:
        """List all structured feedback records from the DB.

        Args:
            limit: Maximum number of records.

        Returns:
            List of FeedbackRecord objects, most recent first.
        """
        rows = self._store.list_structured_feedback(limit=limit)
        return [
            FeedbackRecord(
                incident_id=r["incident_id"],
                correct_root_cause=r["correct_root_cause"],
                fix_worked=r["fix_worked"],
                operator_notes=r.get("operator_notes", ""),
                better_remediation=r.get("better_remediation"),
                feedback_at=r.get("created_at", ""),
            )
            for r in rows
        ]

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
        """Compute RCA accuracy and fix success statistics from the DB.

        Uses the structured_feedback table for RCA accuracy (survives restarts),
        and the incidents table feedback_score for fix success rate.

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

        # Fix success rate from incidents table (feedback_score column)
        with_positive_feedback = sum(
            1 for inc in incidents if (inc.get("feedback_score") or 0.0) > 0
        )
        with_negative_feedback = sum(
            1 for inc in incidents if (inc.get("feedback_score") or 0.0) < 0
        )
        feedback_total = with_positive_feedback + with_negative_feedback
        fix_success_pct = (
            with_positive_feedback / feedback_total * 100
            if feedback_total > 0 else 0.0
        )

        # RCA accuracy from structured_feedback table (persisted)
        db_stats = self._store.get_feedback_accuracy_from_db()
        correct_rca_pct = db_stats.get("correct_rca_pct", 0.0)

        # Top failure types
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
