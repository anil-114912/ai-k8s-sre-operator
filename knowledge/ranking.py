"""Remediation ranker — orders remediation steps by historical success probability."""

from __future__ import annotations

import logging
from typing import Any, Dict, List

from knowledge.outcomes import OutcomeStore

logger = logging.getLogger(__name__)

# Default prior success rate when no history is available
_DEFAULT_PRIOR = 0.5

# Minimum number of observations before the outcome rate is trusted over the prior
_MIN_OBSERVATIONS = 3

# Weight for outcome-based success rate vs safety-level default
_OUTCOME_WEIGHT = 0.6
_SAFETY_WEIGHT = 0.4

# Base scores by safety level (lower safety level = less risky = preferred)
_SAFETY_BASE_SCORE: Dict[str, float] = {
    "auto_fix": 0.9,
    "approval_required": 0.6,
    "suggest_only": 0.3,
}


class RemediationRanker:
    """Ranks a list of remediation steps using historical outcome success rates.

    The ranking score for each step combines:
      - Historical success rate for (action, incident_type) from OutcomeStore
      - Safety level base score (auto_fix > approval_required > suggest_only)

    Steps with more successful history are promoted; steps with many failures
    are demoted. Steps with no history use a neutral prior.

    Usage::

        ranker = RemediationRanker(outcome_store)
        ranked_steps = ranker.rank(steps, incident_type="CrashLoopBackOff")
    """

    def __init__(self, outcome_store: OutcomeStore) -> None:
        self._store = outcome_store

    def rank(
        self,
        steps: List[Any],
        incident_type: str = "Unknown",
        namespace: str = "",
    ) -> List[Any]:
        """Rank remediation steps by predicted success probability.

        Steps that have historically worked well for this incident type are
        moved earlier; steps with many failures are pushed later.

        Args:
            steps: List of RemediationStep (or dict) objects.
            incident_type: The detected incident type for type-specific rates.
            namespace: Namespace context (reserved for future per-namespace rates).

        Returns:
            A new list with the same steps, reordered by ranking score.
            Original step ``order`` field is NOT mutated — only list position changes.
        """
        scored: List[Dict[str, Any]] = []
        for step in steps:
            action = self._get_action(step)
            safety_level = self._get_safety_level(step)
            score = self._compute_score(action, incident_type, safety_level)
            scored.append({"step": step, "score": score, "action": action})
            logger.debug(
                "Ranking step action=%s incident_type=%s safety=%s score=%.3f",
                action,
                incident_type,
                safety_level,
                score,
            )

        scored.sort(key=lambda x: x["score"], reverse=True)
        ranked = [item["step"] for item in scored]
        logger.info(
            "Ranked %d steps for incident_type=%s: %s",
            len(ranked),
            incident_type,
            " > ".join(item["action"] for item in scored),
        )
        return ranked

    def boost_action(self, action: str, incident_type: str) -> None:
        """Record a synthetic success for an action (used after positive feedback).

        This is a lightweight way to boost an action's ranking without going
        through the full outcome recording flow.
        """
        self._store.record(
            incident_id="feedback_boost",
            action=action,
            incident_type=incident_type,
            namespace="",
            workload="",
            success=True,
            feedback_notes="positive_feedback_boost",
        )
        logger.info("Boosted action=%s incident_type=%s via feedback", action, incident_type)

    def penalize_action(self, action: str, incident_type: str) -> None:
        """Record a synthetic failure for an action (used after negative feedback)."""
        self._store.record(
            incident_id="feedback_penalty",
            action=action,
            incident_type=incident_type,
            namespace="",
            workload="",
            success=False,
            feedback_notes="negative_feedback_penalty",
        )
        logger.info("Penalized action=%s incident_type=%s via feedback", action, incident_type)

    def get_action_insights(self, incident_type: str = "") -> List[Dict[str, Any]]:
        """Return all recorded action success rates, optionally filtered by type.

        Returns:
            List of {action, success_rate, observation_count, recommended} dicts.
        """
        all_rates = self._store.get_all_action_rates()
        insights = []
        for action, rate in sorted(all_rates.items(), key=lambda kv: kv[1], reverse=True):
            type_rate = (
                self._store.get_success_rate_for_type(action, incident_type)
                if incident_type
                else rate
            )
            insights.append(
                {
                    "action": action,
                    "global_success_rate": round(rate, 3),
                    "type_success_rate": round(type_rate, 3),
                    "recommended": type_rate >= 0.7,
                }
            )
        return insights

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _compute_score(self, action: str, incident_type: str, safety_level: str) -> float:
        """Compute a 0.0–1.0 ranking score for a step."""
        # Type-specific success rate
        type_rate = self._store.get_success_rate_for_type(action, incident_type)
        # Safety base score
        safety_score = _SAFETY_BASE_SCORE.get(safety_level, 0.5)
        # Weighted combination
        score = (_OUTCOME_WEIGHT * type_rate) + (_SAFETY_WEIGHT * safety_score)
        return min(1.0, max(0.0, score))

    @staticmethod
    def _get_action(step: Any) -> str:
        """Extract the action string from a step (Pydantic model or dict)."""
        if hasattr(step, "action"):
            return step.action
        if isinstance(step, dict):
            return step.get("action", "unknown")
        return "unknown"

    @staticmethod
    def _get_safety_level(step: Any) -> str:
        """Extract the safety_level string from a step."""
        if hasattr(step, "safety_level"):
            sl = step.safety_level
            return sl.value if hasattr(sl, "value") else str(sl)
        if isinstance(step, dict):
            return step.get("safety_level", "suggest_only")
        return "suggest_only"
