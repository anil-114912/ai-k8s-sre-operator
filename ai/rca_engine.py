"""Root Cause Analysis engine — structured AI-powered incident analysis."""

from __future__ import annotations

import json
import logging
from typing import Any, Dict, List, Optional

from ai.llm import get_llm_client
from ai.prompts import (
    RCA_KB_MEMORY_SYSTEM_PROMPT,
    RCA_SYSTEM_PROMPT,
    RCA_USER_TEMPLATE,
    rca_with_kb_and_memory,
)
from correlation.signal_correlator import CorrelationResult
from correlation.timeline_builder import TimelineBuilder
from models.incident import Evidence, Incident, IncidentStatus

logger = logging.getLogger(__name__)

# Refit embedder after this many new incidents
_REFIT_INTERVAL = 10
_incidents_since_refit = 0


class RCAEngine:
    """Orchestrates the full root cause analysis pipeline for an incident."""

    def __init__(self) -> None:
        """Initialise the RCA engine with LLM client and timeline builder."""
        self.llm = get_llm_client()
        self.timeline_builder = TimelineBuilder()

    def analyze(
        self,
        incident: Incident,
        correlation: Optional[CorrelationResult] = None,
        cluster_state: Optional[Dict[str, Any]] = None,
        similar_incidents: Optional[List[Dict[str, Any]]] = None,
        kb_context: Optional[str] = None,
        memory_context: Optional[str] = None,
        cluster_patterns: Optional[List[Dict[str, Any]]] = None,
    ) -> Incident:
        """Run full RCA on an incident and return the enriched incident.

        Args:
            incident: The incident to analyse.
            correlation: Pre-computed correlation result from SignalCorrelator.
            cluster_state: Current cluster state for timeline building.
            similar_incidents: List of similar past incidents for context (plain dicts).
            kb_context: Pre-formatted knowledge base context string.
            memory_context: Pre-formatted past incidents memory context string.
            cluster_patterns: List of cluster-specific pattern dicts from IncidentStore.

        Returns:
            Enriched Incident with root_cause, confidence, ai_explanation populated.
        """
        global _incidents_since_refit

        logger.info("Starting RCA for incident: %s (%s)", incident.id, incident.title)
        incident.status = IncidentStatus.analyzing

        # Format correlation signals
        root_cause_signals = self._format_detections(correlation.root_causes if correlation else [])
        symptom_signals = self._format_detections(correlation.symptoms if correlation else [])
        contributing_signals = self._format_detections(
            correlation.contributing_factors if correlation else []
        )

        # Format evidence
        evidence_text = self._format_evidence(incident.evidence or [])

        # Format cluster patterns
        cluster_patterns_str = "None"
        if cluster_patterns:
            cluster_patterns_str = ", ".join(
                f"{p['incident_type']} ({p['count']}x)" for p in cluster_patterns[:5]
            )

        # Extract log content from raw signals for LLM
        raw = incident.raw_signals or {}
        log_lines = raw.get("recent_logs", [])
        pod_logs_str = "\n".join(log_lines[:50]) if log_lines else "No logs available"
        log_analysis_dict = raw.get("log_analysis", {})
        if log_analysis_dict and isinstance(log_analysis_dict, dict):
            log_analysis_str = (
                f"Category: {log_analysis_dict.get('error_category', 'unknown')}\n"
                f"Suggested cause: {log_analysis_dict.get('suggested_cause', '')}\n"
                f"Has stack trace: {log_analysis_dict.get('has_stack_trace', False)}"
            )
        else:
            log_analysis_str = "No log analysis available"

        # Choose prompt: enhanced KB+memory if context provided, else legacy
        if kb_context is not None or memory_context is not None:
            system_prompt = RCA_KB_MEMORY_SYSTEM_PROMPT
            user_prompt = rca_with_kb_and_memory(
                incident_type=incident.incident_type.value,
                severity=incident.severity.value,
                namespace=incident.namespace,
                workload=incident.workload,
                pod_name=incident.pod_name or "N/A",
                detected_at=incident.detected_at,
                root_cause_signals=root_cause_signals,
                symptom_signals=symptom_signals,
                contributing_factor_signals=contributing_signals,
                evidence_text=evidence_text,
                kb_context=kb_context or "",
                memory_context=memory_context
                or self._format_similar_incidents(similar_incidents or []),
                cluster_patterns=cluster_patterns_str,
                pod_logs=pod_logs_str,
                log_analysis=log_analysis_str,
            )
        else:
            # Legacy prompt path — preserves backward compatibility
            timeline_text = self._build_timeline_text(incident, cluster_state or {})
            similar_text = self._format_similar_incidents(similar_incidents or [])
            system_prompt = RCA_SYSTEM_PROMPT
            user_prompt = RCA_USER_TEMPLATE.format(
                title=incident.title,
                incident_type=incident.incident_type.value,
                severity=incident.severity.value,
                namespace=incident.namespace,
                workload=incident.workload,
                pod_name=incident.pod_name or "N/A",
                detected_at=incident.detected_at,
                root_cause_signals=root_cause_signals,
                symptom_signals=symptom_signals,
                contributing_factor_signals=contributing_signals,
                evidence_text=evidence_text,
                pod_logs=pod_logs_str,
                log_analysis=log_analysis_str,
                timeline_text=timeline_text,
                similar_incidents_text=similar_text,
            )

        # Call LLM
        try:
            raw_response = self.llm.chat(system=system_prompt, user=user_prompt)
            analysis = self._parse_rca_response(raw_response)
        except Exception as exc:
            logger.error("RCA LLM call failed: %s", exc)
            analysis = self._fallback_analysis(incident)

        # Track incidents for embedder refit
        _incidents_since_refit += 1

        # Enrich incident
        incident.root_cause = analysis.get("root_cause", "Root cause undetermined")
        incident.confidence = float(analysis.get("confidence", 0.5))

        # Store explainable "Why Not X" alternatives in raw_signals for API/UI access
        alternatives_rejected = analysis.get("alternatives_rejected", [])
        if alternatives_rejected and isinstance(alternatives_rejected, list):
            if incident.raw_signals is None:
                incident.raw_signals = {}
            incident.raw_signals["alternatives_rejected"] = alternatives_rejected
            logger.debug(
                "Explainable RCA: %d alternatives rejected for incident %s",
                len(alternatives_rejected),
                incident.id,
            )

        # Adjust confidence based on feedback history for this pattern
        try:
            from knowledge.feedback_loop import LearningLoop
            from knowledge.incident_store import IncidentStore

            _loop = LearningLoop(IncidentStore())
            incident.confidence = _loop.adjust_confidence(
                incident.confidence,
                incident.incident_type.value,
                incident.namespace,
            )
        except Exception:
            pass  # Non-critical — use raw confidence if learning loop unavailable

        # Apply confidence boost from log analysis clarity
        confidence_boost = (incident.raw_signals or {}).get("log_analysis", {})
        if isinstance(confidence_boost, dict):
            confidence_boost = confidence_boost.get("confidence_boost", 0.0)
        else:
            confidence_boost = 0.0
        if confidence_boost > 0:
            incident.confidence = min(1.0, incident.confidence + confidence_boost)

        incident.ai_explanation = analysis.get("explanation", "")
        incident.contributing_factors = analysis.get("contributing_factors", [])
        incident.suggested_fix = analysis.get("suggested_fix", "")
        incident.status = IncidentStatus.analyzed

        # Add AI analysis as evidence
        if incident.evidence is None:
            incident.evidence = []
        incident.evidence.append(
            Evidence(
                source="ai_rca",
                content=f"Root cause: {incident.root_cause} (confidence={incident.confidence:.0%})",
                relevance=incident.confidence,
            )
        )

        logger.info(
            "RCA complete: incident=%s root_cause=%s confidence=%.2f",
            incident.id,
            incident.root_cause[:80] if incident.root_cause else "N/A",
            incident.confidence or 0,
        )
        return incident

    def _build_timeline_text(self, incident: Incident, cluster_state: Dict[str, Any]) -> str:
        """Build a formatted timeline from incident signals.

        Args:
            incident: The incident object.
            cluster_state: Current cluster state.

        Returns:
            Formatted timeline string.
        """
        events = cluster_state.get("events", [])
        raw_signals = incident.raw_signals or {}
        recent_changes = raw_signals.get("recent_changes", [])
        recent_logs = raw_signals.get("recent_logs", [])

        timeline = self.timeline_builder.build(
            events=events,
            recent_changes=recent_changes,
            log_entries=recent_logs,
            pod_name=incident.pod_name or "",
        )
        return self.timeline_builder.format_timeline(timeline)

    def _format_detections(self, detections: list) -> str:
        """Format a list of DetectionResult objects as text.

        Args:
            detections: List of DetectionResult objects.

        Returns:
            Formatted string or 'None' if empty.
        """
        if not detections:
            return "None"
        lines = []
        for det in detections:
            lines.append(f"- [{det.incident_type}] {det.reason}")
            for ev in det.evidence[:3]:  # Top 3 evidence items
                lines.append(f"  * ({ev.source}) {ev.content[:200]}")
        return "\n".join(lines)

    def _format_evidence(self, evidence: List[Evidence]) -> str:
        """Format evidence list as text for LLM prompt.

        Args:
            evidence: List of Evidence objects.

        Returns:
            Formatted evidence string.
        """
        if not evidence:
            return "No direct evidence collected."
        lines = []
        for ev in sorted(evidence, key=lambda e: e.relevance, reverse=True):
            lines.append(f"[{ev.source}] (relevance={ev.relevance:.0%}) {ev.content}")
        return "\n".join(lines)

    def _format_similar_incidents(self, similar: List[Dict[str, Any]]) -> str:
        """Format similar past incidents for context injection.

        Args:
            similar: List of similar incident summary dicts.

        Returns:
            Formatted string for LLM prompt.
        """
        if not similar:
            return "No similar past incidents found."
        lines = []
        for s in similar[:3]:
            lines.append(
                f"- Past incident (type={s.get('type', '?')}, "
                f"namespace={s.get('namespace', '?')}): "
                f"root_cause={s.get('root_cause', 'unknown')}. "
                f"Fix: {s.get('suggested_fix', 'unknown')}. "
                f"Success: {s.get('resolved', False)}"
            )
        return "\n".join(lines)

    def _parse_rca_response(self, raw_response: str) -> Dict[str, Any]:
        """Parse the LLM JSON response, with fallback for malformed output.

        Args:
            raw_response: Raw string from LLM.

        Returns:
            Parsed dict with RCA fields.
        """
        # Try direct JSON parse
        try:
            return json.loads(raw_response)
        except json.JSONDecodeError:
            pass

        # Try extracting JSON block from markdown
        try:
            start = raw_response.index("{")
            end = raw_response.rindex("}") + 1
            return json.loads(raw_response[start:end])
        except (ValueError, json.JSONDecodeError):
            pass

        logger.warning("Could not parse LLM response as JSON, using text extraction")
        return {
            "root_cause": raw_response[:500],
            "confidence": 0.5,
            "explanation": raw_response,
            "contributing_factors": [],
            "suggested_fix": "Manual investigation required",
        }

    def _fallback_analysis(self, incident: Incident) -> Dict[str, Any]:
        """Provide a deterministic fallback analysis when LLM is unavailable.

        Args:
            incident: The incident to analyse.

        Returns:
            Dict with RCA fields.
        """
        return {
            "root_cause": f"Detected {incident.incident_type.value} in {incident.namespace}/{incident.workload}",
            "confidence": 0.6,
            "explanation": (
                f"The {incident.incident_type.value} was detected by the rule-based detectors. "
                "Manual investigation is required to determine the precise root cause."
            ),
            "contributing_factors": [],
            "suggested_fix": "Review pod logs and events for more details.",
        }
