"""Structured audit logger for all remediation and guardrails decisions.

Every action — approved, blocked, or auto-executed — is written as a
JSON-L record to the audit log file *and* emitted via the standard
logging system so it can be captured by any log aggregator (ELK, Loki, etc.).

Usage::

    from audit.logger import get_audit_logger

    audit = get_audit_logger()
    audit.log_remediation_approved(incident, step, actor="api-user")
    audit.log_remediation_blocked(incident, step, reason="protected namespace")
    audit.log_guardrails_decision(incident, decision)
"""

from __future__ import annotations

import json
import logging
import threading
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

_AUDIT_LOG_PATH = Path("/tmp/sre-operator-audit.jsonl")


@dataclass
class AuditEvent:
    """A single immutable audit record."""

    event_type: str                    # remediation_approved | remediation_blocked | guardrails_decision | auto_executed
    timestamp: str
    incident_id: str
    namespace: str
    workload: str
    incident_type: str
    actor: str                         # "api-user" | "auto" | "operator-loop"
    action: Optional[str] = None       # remediation action name
    outcome: Optional[str] = None      # approved | blocked | executed | failed
    reason: Optional[str] = None       # why blocked / approved
    risk_score: Optional[float] = None
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {k: v for k, v in asdict(self).items() if v is not None}

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), default=str)


class AuditLogger:
    """Thread-safe structured audit logger.

    Writes JSON-L records to a file *and* emits structured log records
    at INFO level so they flow through any existing log shipping pipeline.
    """

    def __init__(self, log_path: Optional[Path] = None) -> None:
        self._path = log_path or _AUDIT_LOG_PATH
        self._lock = threading.Lock()
        self._events: List[AuditEvent] = []
        self._max_in_memory = 500      # rolling in-memory buffer for API queries

    # ------------------------------------------------------------------
    # High-level helpers
    # ------------------------------------------------------------------

    def log_remediation_approved(
        self,
        incident: Any,
        action: str,
        actor: str = "api-user",
        risk_score: float = 0.0,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> AuditEvent:
        return self._write(AuditEvent(
            event_type="remediation_approved",
            timestamp=_now(),
            incident_id=getattr(incident, "id", ""),
            namespace=getattr(incident, "namespace", ""),
            workload=getattr(incident, "workload", ""),
            incident_type=getattr(incident, "incident_type", ""),
            actor=actor,
            action=action,
            outcome="approved",
            risk_score=risk_score,
            metadata=metadata or {},
        ))

    def log_remediation_blocked(
        self,
        incident: Any,
        action: str,
        reason: str,
        actor: str = "guardrails",
        risk_score: float = 0.0,
    ) -> AuditEvent:
        return self._write(AuditEvent(
            event_type="remediation_blocked",
            timestamp=_now(),
            incident_id=getattr(incident, "id", ""),
            namespace=getattr(incident, "namespace", ""),
            workload=getattr(incident, "workload", ""),
            incident_type=getattr(incident, "incident_type", ""),
            actor=actor,
            action=action,
            outcome="blocked",
            reason=reason,
            risk_score=risk_score,
        ))

    def log_auto_executed(
        self,
        incident: Any,
        action: str,
        success: bool,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> AuditEvent:
        return self._write(AuditEvent(
            event_type="auto_executed",
            timestamp=_now(),
            incident_id=getattr(incident, "id", ""),
            namespace=getattr(incident, "namespace", ""),
            workload=getattr(incident, "workload", ""),
            incident_type=getattr(incident, "incident_type", ""),
            actor="operator-loop",
            action=action,
            outcome="executed" if success else "failed",
            metadata=metadata or {},
        ))

    def log_guardrails_decision(
        self,
        incident: Any,
        decision: Any,
        actor: str = "guardrails",
    ) -> AuditEvent:
        """Log a full GuardrailsDecision object."""
        blocked = getattr(decision, "blocked_steps", [])
        return self._write(AuditEvent(
            event_type="guardrails_decision",
            timestamp=_now(),
            incident_id=getattr(incident, "id", ""),
            namespace=getattr(incident, "namespace", ""),
            workload=getattr(incident, "workload", ""),
            incident_type=getattr(incident, "incident_type", ""),
            actor=actor,
            outcome="blocked" if blocked else "allowed",
            risk_score=getattr(decision, "risk_score", None),
            reason=f"blocked_steps={blocked}" if blocked else "all_allowed",
            metadata={
                "overall_allowed": getattr(decision, "overall_allowed", True),
                "requires_approval": getattr(decision, "overall_requires_approval", False),
                "audit_log": getattr(decision, "audit_log", []),
            },
        ))

    def log_operator_cycle(
        self,
        cycle_id: str,
        incidents_found: int,
        remediations_attempted: int,
        duration_secs: float,
    ) -> AuditEvent:
        return self._write(AuditEvent(
            event_type="operator_cycle",
            timestamp=_now(),
            incident_id="",
            namespace="",
            workload="",
            incident_type="",
            actor="operator-loop",
            metadata={
                "cycle_id": cycle_id,
                "incidents_found": incidents_found,
                "remediations_attempted": remediations_attempted,
                "duration_secs": round(duration_secs, 2),
            },
        ))

    # ------------------------------------------------------------------
    # Query helpers
    # ------------------------------------------------------------------

    def get_recent(self, limit: int = 100) -> List[Dict[str, Any]]:
        """Return the most recent audit events as dicts."""
        with self._lock:
            return [e.to_dict() for e in self._events[-limit:]]

    def get_by_incident(self, incident_id: str) -> List[Dict[str, Any]]:
        """Return all audit events for a specific incident."""
        with self._lock:
            return [e.to_dict() for e in self._events if e.incident_id == incident_id]

    def get_stats(self) -> Dict[str, Any]:
        """Return aggregate counts by event_type and outcome."""
        with self._lock:
            events = list(self._events)

        type_counts: Dict[str, int] = {}
        outcome_counts: Dict[str, int] = {}
        for ev in events:
            type_counts[ev.event_type] = type_counts.get(ev.event_type, 0) + 1
            if ev.outcome:
                outcome_counts[ev.outcome] = outcome_counts.get(ev.outcome, 0) + 1

        return {
            "total_events": len(events),
            "by_type": type_counts,
            "by_outcome": outcome_counts,
        }

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _write(self, event: AuditEvent) -> AuditEvent:
        line = event.to_json()
        logger.info("AUDIT %s", line)

        with self._lock:
            self._events.append(event)
            if len(self._events) > self._max_in_memory:
                self._events = self._events[-self._max_in_memory:]

        try:
            with self._path.open("a", encoding="utf-8") as fh:
                fh.write(line + "\n")
        except OSError as exc:
            logger.warning("Could not write audit log to %s: %s", self._path, exc)

        return event


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


# Module-level singleton
_default_logger: Optional[AuditLogger] = None
_default_lock = threading.Lock()


def get_audit_logger() -> AuditLogger:
    """Return the module-level singleton AuditLogger."""
    global _default_logger
    if _default_logger is None:
        with _default_lock:
            if _default_logger is None:
                _default_logger = AuditLogger()
    return _default_logger
