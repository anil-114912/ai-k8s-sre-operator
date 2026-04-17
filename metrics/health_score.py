"""Cluster health score — a single 0–100 metric representing overall cluster state.

The score is derived from:
  - Active incident count and severity
  - Recurrence of the same failure types
  - Fraction of workloads in a failing state
  - Recent failure velocity (incidents per last 30 minutes)

A score of 100 means no active incidents. Score drops for open incidents,
with larger drops for critical and high severity.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

# Points deducted per incident by severity
_SEVERITY_DEDUCTION: Dict[str, float] = {
    "critical": 15.0,
    "high": 8.0,
    "medium": 4.0,
    "low": 1.5,
    "info": 0.5,
}

# Additional deduction if an incident type is recurring (seen 3+ times recently)
_RECURRING_EXTRA = 3.0

# Deduction per incident in the last 30 minutes (velocity signal)
_VELOCITY_DEDUCTION = 2.0

# Maximum deduction from velocity alone
_VELOCITY_CAP = 20.0


@dataclass
class HealthScore:
    """Full cluster health evaluation result."""

    score: int                          # 0–100
    grade: str                          # A, B, C, D, F
    severity_deduction: float = 0.0
    recurrence_deduction: float = 0.0
    velocity_deduction: float = 0.0
    active_incidents: int = 0
    critical_count: int = 0
    high_count: int = 0
    medium_count: int = 0
    low_count: int = 0
    recurring_types: List[str] = field(default_factory=list)
    velocity_30m: int = 0               # incidents in last 30 min
    evaluated_at: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )

    def to_dict(self) -> Dict[str, Any]:
        return {
            "score": self.score,
            "grade": self.grade,
            "active_incidents": self.active_incidents,
            "breakdown": {
                "severity_deduction": round(self.severity_deduction, 1),
                "recurrence_deduction": round(self.recurrence_deduction, 1),
                "velocity_deduction": round(self.velocity_deduction, 1),
            },
            "severity_counts": {
                "critical": self.critical_count,
                "high": self.high_count,
                "medium": self.medium_count,
                "low": self.low_count,
            },
            "recurring_types": self.recurring_types,
            "velocity_30m": self.velocity_30m,
            "evaluated_at": self.evaluated_at,
        }

    def summary(self) -> str:
        return (
            f"Cluster Health: {self.score}/100 ({self.grade}) — "
            f"{self.active_incidents} active incidents "
            f"[{self.critical_count} critical, {self.high_count} high]"
        )


def _grade(score: int) -> str:
    """Convert a numeric score to a letter grade."""
    if score >= 90:
        return "A"
    if score >= 75:
        return "B"
    if score >= 55:
        return "C"
    if score >= 35:
        return "D"
    return "F"


class ClusterHealthScorer:
    """Computes the cluster health score from an incident list.

    Usage::

        scorer = ClusterHealthScorer()
        health = scorer.compute(incidents=list_of_incidents)
        print(health.summary())
        # → "Cluster Health: 72/100 (B) — 3 active incidents [1 critical, 1 high]"
    """

    def compute(
        self,
        incidents: List[Any],
        cluster_state: Optional[Dict[str, Any]] = None,
        recurrence_threshold: int = 3,
        velocity_window_mins: int = 30,
    ) -> HealthScore:
        """Compute the cluster health score.

        Args:
            incidents: List of Incident objects (or dicts with 'severity', 'detected_at').
            cluster_state: Optional cluster state for pod/node counts.
            recurrence_threshold: How many occurrences of the same type = recurring.
            velocity_window_mins: Window for velocity calculation.

        Returns:
            A HealthScore with the numeric score and breakdown.
        """
        # Filter to open/analyzing incidents only
        open_incidents = [
            inc for inc in incidents
            if self._get(inc, "status", "open") not in ("resolved", "closed")
        ]

        score = HealthScore(active_incidents=len(open_incidents))

        # 1. Severity deduction
        severity_map: Dict[str, int] = {}
        for inc in open_incidents:
            sev = self._get_severity(inc)
            severity_map[sev] = severity_map.get(sev, 0) + 1
            score.severity_deduction += _SEVERITY_DEDUCTION.get(sev, 1.0)

        score.critical_count = severity_map.get("critical", 0)
        score.high_count = severity_map.get("high", 0)
        score.medium_count = severity_map.get("medium", 0)
        score.low_count = severity_map.get("low", 0)

        # Cap total severity deduction at 70 (leaves room for velocity and recurrence)
        score.severity_deduction = min(70.0, score.severity_deduction)

        # 2. Recurrence deduction
        type_counts: Dict[str, int] = {}
        for inc in open_incidents:
            t = self._get(inc, "incident_type", "Unknown")
            t_str = t.value if hasattr(t, "value") else str(t)
            type_counts[t_str] = type_counts.get(t_str, 0) + 1

        recurring = [t for t, c in type_counts.items() if c >= recurrence_threshold]
        score.recurring_types = recurring
        score.recurrence_deduction = min(15.0, len(recurring) * _RECURRING_EXTRA)

        # 3. Velocity deduction (incidents in last N minutes)
        now = datetime.now(timezone.utc)
        window = timedelta(minutes=velocity_window_mins)
        recent = []
        for inc in open_incidents:
            ts_str = self._get(inc, "detected_at", "")
            if not ts_str:
                continue
            try:
                ts = datetime.fromisoformat(ts_str.rstrip("Z"))
                if ts.tzinfo is None:
                    ts = ts.replace(tzinfo=timezone.utc)
                if now - ts <= window:
                    recent.append(inc)
            except Exception:
                pass

        score.velocity_30m = len(recent)
        score.velocity_deduction = min(_VELOCITY_CAP, len(recent) * _VELOCITY_DEDUCTION)

        # 4. Final score
        total_deduction = (
            score.severity_deduction + score.recurrence_deduction + score.velocity_deduction
        )
        raw_score = max(0, 100 - total_deduction)
        score.score = int(round(raw_score))
        score.grade = _grade(score.score)

        logger.info(
            "Health score computed: %d (%s) — sev=%.1f rec=%.1f vel=%.1f incidents=%d",
            score.score,
            score.grade,
            score.severity_deduction,
            score.recurrence_deduction,
            score.velocity_deduction,
            len(open_incidents),
        )
        return score

    @staticmethod
    def _get(obj: Any, key: str, default: Any = "") -> Any:
        if hasattr(obj, key):
            return getattr(obj, key)
        if isinstance(obj, dict):
            return obj.get(key, default)
        return default

    @staticmethod
    def _get_severity(inc: Any) -> str:
        sev = ClusterHealthScorer._get(inc, "severity", "info")
        return sev.value if hasattr(sev, "value") else str(sev).lower()
