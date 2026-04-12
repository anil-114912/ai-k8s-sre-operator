"""SQLite-backed incident history store using SQLAlchemy."""
from __future__ import annotations

import json
import logging
import os
from datetime import datetime
from typing import Any, Dict, List, Optional

from sqlalchemy import Column, DateTime, Float, String, Text, Boolean, create_engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from knowledge.embeddings import TFIDFEmbedder
from models.incident import Incident

logger = logging.getLogger(__name__)

DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///./sre_operator.db")


class Base(DeclarativeBase):
    """SQLAlchemy declarative base."""

    pass


class IncidentRecord(Base):
    """SQLAlchemy ORM model for the incidents table."""

    __tablename__ = "incidents"

    id = Column(String(64), primary_key=True)
    title = Column(String(512), nullable=False)
    incident_type = Column(String(64), nullable=False)
    severity = Column(String(32), nullable=False)
    namespace = Column(String(128), nullable=False)
    workload = Column(String(128), nullable=False)
    root_cause = Column(Text, nullable=True)
    confidence = Column(Float, nullable=True)
    suggested_fix = Column(Text, nullable=True)
    ai_explanation = Column(Text, nullable=True)
    resolved = Column(Boolean, default=False)
    created_at = Column(DateTime, default=datetime.utcnow)
    embedding = Column(Text, nullable=True)  # JSON blob of float list
    # Extended columns for Hybrid Learning Architecture
    cluster_name = Column(String(128), nullable=True)
    feedback_score = Column(Float, default=0.0)  # +1.0 success, -0.5 failed
    resolution_outcome = Column(String(32), nullable=True)  # "resolved", "failed", "partial"


class RemediationOutcomeRecord(Base):
    """SQLAlchemy ORM model for the remediation_outcomes table."""

    __tablename__ = "remediation_outcomes"

    id = Column(String(64), primary_key=True)
    incident_id = Column(String(64), nullable=False)
    plan_summary = Column(Text, nullable=True)
    success = Column(Boolean, default=False)
    feedback_notes = Column(Text, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)


class IncidentStore:
    """Persistent storage for incidents and remediation outcomes."""

    def __init__(self, database_url: Optional[str] = None) -> None:
        """Initialise the incident store and create tables if needed.

        Args:
            database_url: SQLAlchemy database URL. Defaults to DATABASE_URL env var.
        """
        url = database_url or DATABASE_URL
        self._engine = create_engine(url, connect_args={"check_same_thread": False} if "sqlite" in url else {})
        Base.metadata.create_all(self._engine)
        self._migrate_schema()
        self._Session = sessionmaker(bind=self._engine)
        self._embedder = TFIDFEmbedder()
        logger.info("IncidentStore initialised: %s", url)

    def _migrate_schema(self) -> None:
        """Add any missing columns to the incidents table (SQLite-safe migration)."""
        new_columns = [
            ("cluster_name", "VARCHAR(128)"),
            ("feedback_score", "FLOAT DEFAULT 0.0"),
            ("resolution_outcome", "VARCHAR(32)"),
        ]
        with self._engine.connect() as conn:
            for col_name, col_def in new_columns:
                try:
                    conn.execute(
                        __import__("sqlalchemy").text(
                            f"ALTER TABLE incidents ADD COLUMN {col_name} {col_def}"
                        )
                    )
                    conn.commit()
                    logger.info("Schema migration: added column incidents.%s", col_name)
                except Exception:
                    # Column already exists — this is expected for existing databases
                    pass

    def save_incident(self, incident: Incident, cluster_name: Optional[str] = None) -> None:
        """Persist an incident to the store.

        Args:
            incident: Incident object to save.
            cluster_name: Optional cluster identifier for cluster-level pattern tracking.
        """
        text = self._incident_to_text(incident)
        embedding = self._embedder.embed_incident(text)

        with Session(self._engine) as session:
            existing = session.get(IncidentRecord, incident.id)
            if existing:
                existing.root_cause = incident.root_cause
                existing.confidence = incident.confidence
                existing.suggested_fix = incident.suggested_fix
                existing.ai_explanation = incident.ai_explanation
                existing.embedding = TFIDFEmbedder.to_json(embedding)
                if cluster_name:
                    existing.cluster_name = cluster_name
            else:
                record = IncidentRecord(
                    id=incident.id,
                    title=incident.title,
                    incident_type=incident.incident_type.value,
                    severity=incident.severity.value,
                    namespace=incident.namespace,
                    workload=incident.workload,
                    root_cause=incident.root_cause,
                    confidence=incident.confidence,
                    suggested_fix=incident.suggested_fix,
                    ai_explanation=incident.ai_explanation,
                    embedding=TFIDFEmbedder.to_json(embedding),
                    cluster_name=cluster_name,
                )
                session.add(record)
            session.commit()
        logger.info("Saved incident: %s", incident.id)

    def get_incident(self, incident_id: str) -> Optional[Dict[str, Any]]:
        """Retrieve an incident by ID.

        Args:
            incident_id: The incident UUID.

        Returns:
            Dict of incident fields or None if not found.
        """
        with Session(self._engine) as session:
            record = session.get(IncidentRecord, incident_id)
            if not record:
                return None
            return self._record_to_dict(record)

    def list_incidents(self, limit: int = 50) -> List[Dict[str, Any]]:
        """List most recent incidents.

        Args:
            limit: Maximum number of incidents to return.

        Returns:
            List of incident dicts.
        """
        with Session(self._engine) as session:
            records = (
                session.query(IncidentRecord)
                .order_by(IncidentRecord.created_at.desc())
                .limit(limit)
                .all()
            )
            return [self._record_to_dict(r) for r in records]

    def get_all_embeddings(self) -> List[Dict[str, Any]]:
        """Retrieve all incidents with their embeddings for similarity search.

        Returns:
            List of dicts with id, embedding, and metadata fields.
        """
        with Session(self._engine) as session:
            records = session.query(IncidentRecord).all()
            results = []
            for r in records:
                vec = TFIDFEmbedder.from_json(r.embedding or "[]")
                results.append({
                    "id": r.id,
                    "embedding": vec,
                    "type": r.incident_type,
                    "namespace": r.namespace,
                    "workload": r.workload,
                    "root_cause": r.root_cause,
                    "suggested_fix": r.suggested_fix,
                    "resolved": r.resolved,
                    "cluster_name": getattr(r, "cluster_name", None),
                    "feedback_score": getattr(r, "feedback_score", 0.0) or 0.0,
                    "resolution_outcome": getattr(r, "resolution_outcome", None),
                    "created_at": r.created_at.isoformat() if r.created_at else None,
                    "title": r.title,
                })
            return results

    def get_by_namespace(self, namespace: str) -> List[Dict[str, Any]]:
        """Retrieve incidents for a specific namespace.

        Args:
            namespace: Kubernetes namespace string.

        Returns:
            List of incident dicts.
        """
        with Session(self._engine) as session:
            records = (
                session.query(IncidentRecord)
                .filter(IncidentRecord.namespace == namespace)
                .order_by(IncidentRecord.created_at.desc())
                .all()
            )
            return [self._record_to_dict(r) for r in records]

    def get_by_type(self, incident_type: str) -> List[Dict[str, Any]]:
        """Retrieve incidents of a specific type.

        Args:
            incident_type: Incident type string (e.g., "CrashLoopBackOff").

        Returns:
            List of incident dicts.
        """
        with Session(self._engine) as session:
            records = (
                session.query(IncidentRecord)
                .filter(IncidentRecord.incident_type == incident_type)
                .order_by(IncidentRecord.created_at.desc())
                .all()
            )
            return [self._record_to_dict(r) for r in records]

    def get_recent(self, limit: int = 20) -> List[Dict[str, Any]]:
        """Return the most recent incidents.

        Args:
            limit: Maximum number of incidents to return.

        Returns:
            List of incident dicts sorted by created_at descending.
        """
        with Session(self._engine) as session:
            records = (
                session.query(IncidentRecord)
                .order_by(IncidentRecord.created_at.desc())
                .limit(limit)
                .all()
            )
            return [self._record_to_dict(r) for r in records]

    def update_feedback(self, incident_id: str, success: bool, notes: str = "") -> None:
        """Update the feedback score and resolution outcome for an incident.

        Args:
            incident_id: The incident UUID.
            success: True if remediation succeeded (+1.0 score), False if failed (-0.5 score).
            notes: Operator notes (currently stored in remediation_outcomes table).
        """
        with Session(self._engine) as session:
            record = session.get(IncidentRecord, incident_id)
            if record:
                record.feedback_score = 1.0 if success else -0.5
                record.resolution_outcome = "resolved" if success else "failed"
                if success:
                    record.resolved = True
                session.commit()
                logger.info(
                    "Updated feedback: incident=%s success=%s score=%.1f",
                    incident_id, success, record.feedback_score,
                )
            else:
                logger.warning("update_feedback: incident %s not found", incident_id)

    def get_cluster_patterns(
        self, cluster_name: str, limit: int = 10
    ) -> List[Dict[str, Any]]:
        """Return the most frequent failure types for a specific cluster.

        Args:
            cluster_name: Cluster identifier string.
            limit: Maximum number of pattern entries to return.

        Returns:
            List of dicts with incident_type and count, sorted by count descending.
        """
        with Session(self._engine) as session:
            from sqlalchemy import func
            results = (
                session.query(
                    IncidentRecord.incident_type,
                    func.count(IncidentRecord.id).label("count"),
                )
                .filter(IncidentRecord.cluster_name == cluster_name)
                .group_by(IncidentRecord.incident_type)
                .order_by(func.count(IncidentRecord.id).desc())
                .limit(limit)
                .all()
            )
            return [{"incident_type": r.incident_type, "count": r.count} for r in results]

    def save_remediation_outcome(
        self,
        incident_id: str,
        plan_summary: str,
        success: bool,
        feedback_notes: str = "",
    ) -> None:
        """Save the outcome of a remediation execution.

        Args:
            incident_id: Parent incident ID.
            plan_summary: Summary of the remediation plan executed.
            success: Whether the remediation succeeded.
            feedback_notes: Operator feedback notes.
        """
        import uuid
        with Session(self._engine) as session:
            record = RemediationOutcomeRecord(
                id=str(uuid.uuid4()),
                incident_id=incident_id,
                plan_summary=plan_summary,
                success=success,
                feedback_notes=feedback_notes,
            )
            session.add(record)
            # Mark parent incident as resolved if successful
            if success:
                parent = session.get(IncidentRecord, incident_id)
                if parent:
                    parent.resolved = True
            session.commit()
        logger.info(
            "Saved remediation outcome: incident=%s success=%s", incident_id, success
        )

    @staticmethod
    def _incident_to_text(incident: Incident) -> str:
        """Convert incident fields to a flat string for embedding.

        Args:
            incident: Incident object.

        Returns:
            Concatenated text string.
        """
        parts = [
            incident.title,
            incident.incident_type.value,
            incident.severity.value,
            incident.namespace,
            incident.workload,
            incident.root_cause or "",
            incident.suggested_fix or "",
            incident.ai_explanation or "",
        ]
        return " ".join(p for p in parts if p)

    @staticmethod
    def _record_to_dict(record: IncidentRecord) -> Dict[str, Any]:
        """Convert an ORM record to a plain dict.

        Args:
            record: IncidentRecord ORM object.

        Returns:
            Plain dictionary.
        """
        return {
            "id": record.id,
            "title": record.title,
            "type": record.incident_type,
            "severity": record.severity,
            "namespace": record.namespace,
            "workload": record.workload,
            "root_cause": record.root_cause,
            "confidence": record.confidence,
            "suggested_fix": record.suggested_fix,
            "ai_explanation": record.ai_explanation,
            "resolved": record.resolved,
            "created_at": record.created_at.isoformat() if record.created_at else None,
            "cluster_name": getattr(record, "cluster_name", None),
            "feedback_score": getattr(record, "feedback_score", 0.0) or 0.0,
            "resolution_outcome": getattr(record, "resolution_outcome", None),
        }
