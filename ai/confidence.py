"""Multi-dimensional confidence breakdown for AI root cause analysis.

Instead of a single opaque confidence score, this module produces a
``ConfidenceBreakdown`` that explains *why* the system is confident or not:

    detector_confidence      — how strongly the detector fired
    kb_match_strength        — how well a KB pattern matched
    similar_incident_match   — whether past incidents with known outcomes match
    log_evidence_strength    — how clear the log evidence is
    overall                  — weighted combination of the above
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

# Weights for the overall score (must sum to 1.0)
_W_DETECTOR = 0.25
_W_KB = 0.30
_W_SIMILAR = 0.20
_W_LOG = 0.25


@dataclass
class ConfidenceBreakdown:
    """Detailed breakdown of how the overall RCA confidence was computed."""

    detector_confidence: float = 0.5
    """How strongly the deterministic detector fired (0 = weak signal, 1 = certain)."""

    kb_match_strength: float = 0.0
    """Top KB pattern match score (0 = no match, 1 = exact match)."""

    similar_incident_match: float = 0.0
    """Match quality against past incidents with known outcomes (0-1)."""

    log_evidence_strength: float = 0.0
    """Clarity of log evidence — stack trace present, error keyword matched (0-1)."""

    overall: float = 0.5
    """Weighted composite score (0-1). Displayed as confidence % in UI."""

    contributing_factors: List[str] = field(default_factory=list)
    """Human-readable bullets explaining what drove the score up or down."""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "detector_confidence": round(self.detector_confidence, 3),
            "kb_match_strength": round(self.kb_match_strength, 3),
            "similar_incident_match": round(self.similar_incident_match, 3),
            "log_evidence_strength": round(self.log_evidence_strength, 3),
            "overall": round(self.overall, 3),
            "contributing_factors": self.contributing_factors,
        }

    def summary(self) -> str:
        """One-line human-readable summary of the breakdown."""
        return (
            f"Overall {self.overall:.0%} — "
            f"detector={self.detector_confidence:.0%} "
            f"KB={self.kb_match_strength:.0%} "
            f"similar={self.similar_incident_match:.0%} "
            f"logs={self.log_evidence_strength:.0%}"
        )


class ConfidenceCalculator:
    """Computes a ``ConfidenceBreakdown`` from available evidence sources.

    Usage::

        calc = ConfidenceCalculator()
        breakdown = calc.compute(
            incident=incident,
            kb_results=[{"score": 0.94, "id": "k8s-001", ...}],
            similar_incidents=[{"resolved": True, ...}],
        )
        incident.confidence = breakdown.overall
    """

    def compute(
        self,
        incident: Any,
        kb_results: Optional[List[Dict[str, Any]]] = None,
        similar_incidents: Optional[List[Dict[str, Any]]] = None,
    ) -> ConfidenceBreakdown:
        """Compute confidence breakdown from all available signals.

        Args:
            incident: The Incident object (uses raw_signals, evidence).
            kb_results: List of KB pattern match dicts with 'score' field.
            similar_incidents: List of past incident dicts with 'resolved' field.

        Returns:
            Populated ConfidenceBreakdown.
        """
        breakdown = ConfidenceBreakdown()
        factors: List[str] = []

        # 1. Detector confidence — derived from evidence relevance
        breakdown.detector_confidence = self._compute_detector_confidence(incident, factors)

        # 2. KB match strength — top pattern score
        breakdown.kb_match_strength = self._compute_kb_strength(kb_results or [], factors)

        # 3. Similar incident match — resolved past incidents
        breakdown.similar_incident_match = self._compute_similar_match(
            similar_incidents or [], factors
        )

        # 4. Log evidence strength
        breakdown.log_evidence_strength = self._compute_log_strength(incident, factors)

        # 5. Weighted overall
        overall = (
            _W_DETECTOR * breakdown.detector_confidence
            + _W_KB * breakdown.kb_match_strength
            + _W_SIMILAR * breakdown.similar_incident_match
            + _W_LOG * breakdown.log_evidence_strength
        )
        breakdown.overall = min(0.99, max(0.1, round(overall, 3)))
        breakdown.contributing_factors = factors

        logger.debug("ConfidenceBreakdown: %s", breakdown.summary())
        return breakdown

    # ------------------------------------------------------------------
    # Per-dimension helpers
    # ------------------------------------------------------------------

    def _compute_detector_confidence(self, incident: Any, factors: List[str]) -> float:
        """Score based on evidence count and relevance."""
        evidence = getattr(incident, "evidence", None) or []
        if not evidence:
            factors.append("No direct evidence collected — detector confidence low")
            return 0.3

        high_relevance = [e for e in evidence if getattr(e, "relevance", 0) >= 0.8]
        score = min(1.0, 0.4 + len(high_relevance) * 0.15)

        if high_relevance:
            factors.append(
                f"{len(high_relevance)} high-relevance evidence item(s) boost detector confidence"
            )
        return round(score, 3)

    def _compute_kb_strength(
        self, kb_results: List[Dict[str, Any]], factors: List[str]
    ) -> float:
        """Score based on top KB pattern match."""
        if not kb_results:
            factors.append("No KB pattern matched — using heuristic analysis")
            return 0.0

        top_score = max(r.get("score", 0.0) for r in kb_results)
        top_id = next(
            (r.get("id", "?") for r in kb_results if r.get("score", 0) == top_score), "?"
        )

        if top_score >= 0.8:
            factors.append(f"Strong KB match: {top_id} (score={top_score:.2f})")
        elif top_score >= 0.5:
            factors.append(f"Moderate KB match: {top_id} (score={top_score:.2f})")
        else:
            factors.append(f"Weak KB match: {top_id} (score={top_score:.2f})")

        return round(min(1.0, top_score), 3)

    def _compute_similar_match(
        self, similar_incidents: List[Dict[str, Any]], factors: List[str]
    ) -> float:
        """Score based on resolved similar past incidents."""
        if not similar_incidents:
            factors.append("No similar past incidents found")
            return 0.0

        resolved = [s for s in similar_incidents if s.get("resolved") or s.get("success")]
        total = len(similar_incidents)

        if resolved:
            rate = len(resolved) / total
            factors.append(
                f"{len(resolved)}/{total} similar past incidents were resolved — "
                f"confirmed pattern"
            )
            return round(min(1.0, 0.5 + rate * 0.5), 3)

        factors.append(f"{total} similar incident(s) found but none confirmed resolved")
        return 0.3

    def _compute_log_strength(self, incident: Any, factors: List[str]) -> float:
        """Score based on log evidence clarity."""
        raw = getattr(incident, "raw_signals", None) or {}
        log_analysis = raw.get("log_analysis", {})

        if not log_analysis or not isinstance(log_analysis, dict):
            # Fall back to checking raw logs for keywords
            logs = raw.get("recent_logs", [])
            if not logs:
                factors.append("No pod logs available")
                return 0.1
            error_lines = [
                l for l in logs if any(w in l.upper() for w in ("ERROR", "FATAL", "EXCEPTION"))
            ]
            if error_lines:
                factors.append(f"{len(error_lines)} error line(s) found in pod logs")
                return 0.5
            factors.append("Logs available but no explicit error keywords found")
            return 0.3

        has_stack = log_analysis.get("has_stack_trace", False)
        category = log_analysis.get("error_category", "")
        boost = log_analysis.get("confidence_boost", 0.0)

        score = 0.4
        if has_stack:
            score += 0.3
            factors.append("Stack trace present in logs — strong error evidence")
        if category and category != "unknown":
            score += 0.2
            factors.append(f"Log error category identified: {category}")
        if boost > 0:
            score += boost
            factors.append(f"Log analysis confidence boost: +{boost:.0%}")

        return round(min(1.0, score), 3)
