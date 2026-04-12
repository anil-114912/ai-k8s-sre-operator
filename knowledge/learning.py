"""Retrieval-augmented context builder combining KB matches and past incident memory."""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any, Dict, List

from knowledge.failure_kb import FailureKnowledgeBase
from knowledge.incident_store import IncidentStore
from knowledge.retrieval import RetrievedIncident, SimilarityRetriever
from models.incident import Incident

logger = logging.getLogger(__name__)

# Shared KB singleton — loaded once
_kb_instance = None  # type: FailureKnowledgeBase


def _get_kb() -> FailureKnowledgeBase:
    """Return the shared FailureKnowledgeBase instance, loading it on first call."""
    global _kb_instance
    if _kb_instance is None:
        _kb_instance = FailureKnowledgeBase()
        _kb_instance.load()
    return _kb_instance


def _age_label(created_at_str: str) -> str:
    """Return a human-readable age label like '3 days ago'."""
    if not created_at_str:
        return "unknown time ago"
    try:
        dt = datetime.fromisoformat(created_at_str)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        delta = datetime.now(timezone.utc) - dt
        days = delta.days
        if days == 0:
            return "today"
        elif days == 1:
            return "1 day ago"
        else:
            return f"{days} days ago"
    except (ValueError, TypeError):
        return "unknown time ago"


class ContextBuilder:
    """Builds retrieval-augmented context strings from KB matches and past incidents."""

    def __init__(
        self,
        store: IncidentStore,
        top_k: int = 3,
        kb_top_k: int = 3,
    ) -> None:
        """Initialise the context builder.

        Args:
            store: IncidentStore with past incident history.
            top_k: Number of similar past incidents to retrieve.
            kb_top_k: Number of KB patterns to include in context.
        """
        self._retriever = SimilarityRetriever(store=store, top_k=top_k)
        self._kb_top_k = kb_top_k

    def build_context(self, incident: Incident) -> str:
        """Build a combined context string from KB matches and past incidents.

        Args:
            incident: The new incident to build context for.

        Returns:
            Formatted context string for injection into the RCA prompt.
        """
        query_text = (
            f"{incident.incident_type.value} "
            f"{incident.namespace} "
            f"{incident.workload} "
            f"{incident.title}"
        )

        # Get KB matches
        kb = _get_kb()
        provider = incident.cluster_context or "generic"
        kb_matches = kb.search(query_text, provider=provider, top_k=self._kb_top_k)

        # Get similar past incidents
        similar = self._retriever.retrieve(
            query_text=query_text,
            namespace=incident.namespace,
        )

        return self._format_combined_context(kb_matches, similar)

    def build_kb_context(self, incident: Incident) -> str:
        """Build KB-only context string.

        Args:
            incident: The new incident.

        Returns:
            Formatted KB context string.
        """
        query_text = (
            f"{incident.incident_type.value} "
            f"{incident.namespace} "
            f"{incident.workload} "
            f"{incident.title}"
        )
        kb = _get_kb()
        provider = incident.cluster_context or "generic"
        kb_matches = kb.search(query_text, provider=provider, top_k=self._kb_top_k)
        return self._format_kb_context(kb_matches)

    def retrieve_similar(self, incident: Incident) -> List[Dict[str, Any]]:
        """Retrieve similar past incidents as a list of plain dicts.

        Args:
            incident: The new incident.

        Returns:
            List of similar incident dicts.
        """
        query_text = (
            f"{incident.incident_type.value} "
            f"{incident.namespace} "
            f"{incident.workload} "
            f"{incident.title}"
        )
        return self._retriever.find_similar(query_text)

    def retrieve_similar_structured(self, incident: Incident) -> List[RetrievedIncident]:
        """Retrieve similar past incidents as structured RetrievedIncident objects.

        Args:
            incident: The new incident.

        Returns:
            List of RetrievedIncident objects.
        """
        query_text = (
            f"{incident.incident_type.value} "
            f"{incident.namespace} "
            f"{incident.workload} "
            f"{incident.title}"
        )
        return self._retriever.retrieve(
            query_text=query_text,
            namespace=incident.namespace,
        )

    @staticmethod
    def _format_combined_context(
        kb_matches: list,
        similar_incidents: List[RetrievedIncident],
    ) -> str:
        """Format combined KB and memory context as a readable string.

        Args:
            kb_matches: List of FailurePattern objects from KB search.
            similar_incidents: List of RetrievedIncident objects from memory.

        Returns:
            Formatted multi-section context string.
        """
        sections = []

        if kb_matches:
            sections.append(ContextBuilder._format_kb_context(kb_matches))

        if similar_incidents:
            sections.append(ContextBuilder._format_memory_context(similar_incidents))

        if not sections:
            return "No relevant context found in knowledge base or past incidents."

        return "\n\n".join(sections)

    @staticmethod
    def _format_kb_context(kb_matches: list) -> str:
        """Format KB patterns as a readable context block.

        Args:
            kb_matches: List of FailurePattern objects.

        Returns:
            Formatted string.
        """
        if not kb_matches:
            return ""

        lines = ["=== KNOWLEDGE BASE MATCHES ==="]
        for pattern in kb_matches:
            lines.append(
                f"\n[Pattern {pattern.id} (score={pattern.score:.2f})] {pattern.title}"
            )
            lines.append(f"Root cause: {pattern.root_cause}")
            steps = pattern.remediation_steps[:3]
            if steps:
                step_str = " ".join(
                    f"[{i+1}] {s}" for i, s in enumerate(steps)
                )
                lines.append(f"Remediation: {step_str}")
            if pattern.safety_level:
                lines.append(f"Safety level: {pattern.safety_level}")
        return "\n".join(lines)

    @staticmethod
    def _format_memory_context(similar_incidents: List[RetrievedIncident]) -> str:
        """Format past incident memory as a readable context block.

        Args:
            similar_incidents: List of RetrievedIncident objects.

        Returns:
            Formatted string.
        """
        if not similar_incidents:
            return ""

        lines = ["=== SIMILAR PAST INCIDENTS ==="]
        for inc in similar_incidents:
            age = _age_label(inc.created_at)
            feedback_icon = ""
            if inc.resolution_outcome == "resolved":
                feedback_icon = " | fix worked"
            elif inc.resolution_outcome == "failed":
                feedback_icon = " | fix failed"

            lines.append(
                f"\n[INC-{inc.incident_id[:8]} | {age} | similarity={inc.similarity:.2f}{feedback_icon}]"
            )
            lines.append(f"Namespace: {inc.namespace} | Workload: {inc.incident_type}")
            if inc.root_cause:
                lines.append(f"Root cause: {inc.root_cause}")
            if inc.suggested_fix:
                lines.append(f"Fix: {inc.suggested_fix}")

        return "\n".join(lines)
