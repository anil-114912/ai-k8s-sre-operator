"""Structured failure pattern knowledge base loader and search engine."""
from __future__ import annotations

import logging
import os
import re
from dataclasses import dataclass
from typing import Any, Dict, List, Optional

import yaml

logger = logging.getLogger(__name__)

# Directory containing YAML failure pattern files
_KB_DIR = os.path.join(os.path.dirname(__file__), "failures")


@dataclass
class FailurePattern:
    """A single failure pattern entry from the knowledge base."""

    id: str
    title: str
    scope: str
    symptoms: List[str]
    event_patterns: List[str]
    log_patterns: List[str]
    metric_patterns: List[str]
    root_cause: str
    remediation_steps: List[str]
    confidence_hints: List[Dict[str, Any]]
    safe_auto_fix: bool
    safety_level: str
    tags: List[str]
    score: float = 0.0  # filled by search()
    provider: Optional[str] = None  # "aws", "azure", "gcp", or None for generic


class FailureKnowledgeBase:
    """Loads and queries the structured failure pattern catalog."""

    def __init__(self, kb_dir: Optional[str] = None) -> None:
        """Initialise the knowledge base.

        Args:
            kb_dir: Optional path override to the YAML failures directory.
        """
        self._kb_dir = kb_dir or _KB_DIR
        self._patterns: List[FailurePattern] = []
        self._index: Dict[str, FailurePattern] = {}

    def load(self) -> None:
        """Load all YAML files from the knowledge/failures/ directory."""
        self._patterns = []
        self._index = {}

        if not os.path.isdir(self._kb_dir):
            logger.warning("Knowledge base directory not found: %s", self._kb_dir)
            return

        yaml_files = [
            f for f in os.listdir(self._kb_dir)
            if f.endswith(".yaml") or f.endswith(".yml")
        ]

        for filename in sorted(yaml_files):
            filepath = os.path.join(self._kb_dir, filename)
            try:
                with open(filepath, "r") as fh:
                    entries = yaml.safe_load(fh)
                if not isinstance(entries, list):
                    logger.warning("Skipping %s: expected a YAML list", filename)
                    continue
                for entry in entries:
                    pattern = self._parse_entry(entry)
                    if pattern:
                        self._patterns.append(pattern)
                        self._index[pattern.id] = pattern
                logger.debug("Loaded %d patterns from %s", len(entries), filename)
            except Exception as exc:
                logger.error("Failed to load %s: %s", filepath, exc)

        logger.info(
            "FailureKnowledgeBase loaded: %d patterns from %d files",
            len(self._patterns),
            len(yaml_files),
        )

    def search(
        self,
        incident_text: str,
        provider: str = "generic",
        top_k: int = 5,
    ) -> List[FailurePattern]:
        """Find matching failure patterns using keyword and regex matching.

        Scores each pattern by:
        1. event_patterns regex matches in incident text
        2. log_patterns regex matches in incident text
        3. symptom keyword matches
        4. provider match (aws/azure/gcp boosts)
        5. confidence_hints boosts

        Args:
            incident_text: Combined text from incident signals (events + logs).
            provider: Cloud provider ("aws", "azure", "gcp", or "generic").
            top_k: Number of top patterns to return.

        Returns:
            Top-k FailurePattern objects sorted by score descending.
        """
        if not self._patterns:
            return []

        text_lower = incident_text.lower()
        scored: List[FailurePattern] = []

        for pattern in self._patterns:
            score = 0.0

            # Score event_patterns regex matches
            for ep in pattern.event_patterns:
                try:
                    if re.search(ep, text_lower, re.IGNORECASE):
                        score += 0.25
                except re.error:
                    if ep.lower() in text_lower:
                        score += 0.25

            # Score log_patterns regex matches
            for lp in pattern.log_patterns:
                try:
                    if re.search(lp, text_lower, re.IGNORECASE):
                        score += 0.2
                except re.error:
                    if lp.lower() in text_lower:
                        score += 0.2

            # Score symptom keyword matches
            for symptom in pattern.symptoms:
                symptom_words = symptom.lower().split()
                matches = sum(1 for w in symptom_words if w in text_lower)
                if matches > 0:
                    score += 0.1 * (matches / max(len(symptom_words), 1))

            # Provider match boost
            pat_provider = (pattern.provider or "generic").lower()
            if pat_provider != "generic":
                if provider.lower() in ("aws", "eks") and pat_provider == "aws":
                    score += 0.15
                elif provider.lower() in ("azure", "aks") and pat_provider == "azure":
                    score += 0.15
                elif provider.lower() in ("gcp", "gke") and pat_provider == "gcp":
                    score += 0.15
                else:
                    # Penalise provider-specific patterns for wrong provider
                    score -= 0.1

            # Apply confidence_hints boosts
            for hint in pattern.confidence_hints:
                hint_pattern = hint.get("pattern", "")
                boost = float(hint.get("boost", 0.0))
                if not hint_pattern:
                    continue
                try:
                    if re.search(hint_pattern, text_lower, re.IGNORECASE):
                        score += boost
                except re.error:
                    if hint_pattern.lower() in text_lower:
                        score += boost

            # Score title words match
            title_words = pattern.title.lower().split()
            title_matches = sum(1 for w in title_words if len(w) > 3 and w in text_lower)
            if title_matches > 0:
                score += 0.08 * title_matches

            # Score root_cause keywords match
            rc_words = pattern.root_cause.lower().split()
            rc_matches = sum(1 for w in rc_words if len(w) > 4 and w in text_lower)
            if rc_matches > 0:
                score += 0.04 * rc_matches

            # Score tags match
            for tag in pattern.tags:
                if isinstance(tag, str) and tag in text_lower:
                    score += 0.05

            if score > 0:
                import copy
                p = copy.copy(pattern)
                p.score = round(score, 4)
                scored.append(p)

        # Sort by score descending, then by id for stability
        scored.sort(key=lambda p: (-p.score, p.id))
        return scored[:top_k]

    def get_by_id(self, pattern_id: str) -> Optional[FailurePattern]:
        """Retrieve a specific pattern by ID.

        Args:
            pattern_id: The pattern ID (e.g., "k8s-001").

        Returns:
            FailurePattern or None if not found.
        """
        return self._index.get(pattern_id)

    def list_all(self) -> List[FailurePattern]:
        """Return all loaded failure patterns.

        Returns:
            List of all FailurePattern objects.
        """
        return list(self._patterns)

    def list_by_tag(self, tag: str) -> List[FailurePattern]:
        """Return all patterns that have the given tag.

        Args:
            tag: Tag string to filter by.

        Returns:
            List of matching FailurePattern objects.
        """
        return [p for p in self._patterns if tag in p.tags]

    def list_by_provider(self, provider: str) -> List[FailurePattern]:
        """Return all patterns for a specific cloud provider.

        Args:
            provider: "aws", "azure", "gcp", or "generic".

        Returns:
            List of matching FailurePattern objects.
        """
        if provider == "generic":
            return [p for p in self._patterns if not p.provider]
        return [p for p in self._patterns if p.provider == provider]

    @staticmethod
    def _parse_entry(entry: Dict[str, Any]) -> Optional[FailurePattern]:
        """Parse a raw YAML dict into a FailurePattern.

        Args:
            entry: Raw dict from YAML.

        Returns:
            FailurePattern or None if parsing fails.
        """
        try:
            return FailurePattern(
                id=str(entry.get("id", "")),
                title=str(entry.get("title", "")),
                scope=str(entry.get("scope", "pod")),
                symptoms=list(entry.get("symptoms", [])),
                event_patterns=list(entry.get("event_patterns", [])),
                log_patterns=list(entry.get("log_patterns", [])),
                metric_patterns=list(entry.get("metric_patterns", [])),
                root_cause=str(entry.get("root_cause", "")),
                remediation_steps=list(entry.get("remediation_steps", [])),
                confidence_hints=list(entry.get("confidence_hints", [])),
                safe_auto_fix=bool(entry.get("safe_auto_fix", False)),
                safety_level=str(entry.get("safety_level", "suggest_only")),
                tags=list(entry.get("tags", [])),
                provider=entry.get("provider"),
            )
        except Exception as exc:
            logger.error("Failed to parse knowledge base entry %s: %s", entry.get("id"), exc)
            return None
