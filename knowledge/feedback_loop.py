"""Feedback learning loop — retrains embeddings, promotes successful patterns, captures unknown errors."""
from __future__ import annotations

import json
import logging
import os
import re
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

import yaml

from knowledge.embeddings import IncidentEmbedder, TFIDFEmbedder
from knowledge.incident_store import IncidentStore

logger = logging.getLogger(__name__)

_KB_DIR = os.path.join(os.path.dirname(__file__), "failures")
_LEARNED_FILE = os.path.join(_KB_DIR, "learned.yaml")
_REFIT_THRESHOLD = 5  # refit embedder after this many new incidents


class LearningLoop:
    """Closes the feedback loop: captures new errors, retrains embeddings, promotes patterns.

    Responsibilities:
    1. Capture unknown application errors from logs and create new KB entries
    2. Refit TF-IDF embedder periodically as new incidents accumulate
    3. Promote successful remediations into the learned knowledge base
    4. Adjust confidence scoring based on feedback history
    5. Track cluster-specific recurring patterns
    """

    def __init__(self, store: IncidentStore) -> None:
        self._store = store
        self._embedder = IncidentEmbedder()
        self._incidents_since_refit = 0
        self._learned_patterns: List[Dict[str, Any]] = []
        self._load_learned_patterns()

    def _load_learned_patterns(self) -> None:
        """Load previously learned patterns from disk."""
        if os.path.isfile(_LEARNED_FILE):
            try:
                with open(_LEARNED_FILE) as f:
                    data = yaml.safe_load(f)
                if isinstance(data, list):
                    self._learned_patterns = data
                    logger.info("Loaded %d learned patterns from %s", len(data), _LEARNED_FILE)
            except Exception as exc:
                logger.warning("Failed to load learned patterns: %s", exc)

    def _save_learned_patterns(self) -> None:
        """Persist learned patterns to disk."""
        try:
            os.makedirs(os.path.dirname(_LEARNED_FILE), exist_ok=True)
            with open(_LEARNED_FILE, "w") as f:
                yaml.dump(self._learned_patterns, f, default_flow_style=False, sort_keys=False)
            logger.info("Saved %d learned patterns to %s", len(self._learned_patterns), _LEARNED_FILE)
        except Exception as exc:
            logger.error("Failed to save learned patterns: %s", exc)

    # ------------------------------------------------------------------
    # 1. Capture unknown application errors from logs
    # ------------------------------------------------------------------

    def capture_unknown_errors(
        self,
        log_lines: List[str],
        namespace: str,
        workload: str,
        incident_type: str = "Unknown",
    ) -> Optional[Dict[str, Any]]:
        """Scan log lines for error patterns not covered by existing detectors.

        If novel error patterns are found, create a candidate learned pattern entry.

        Args:
            log_lines: Raw application log lines.
            namespace: Kubernetes namespace.
            workload: Workload name.
            incident_type: Detected incident type (may be 'Unknown').

        Returns:
            A candidate pattern dict if novel errors found, else None.
        """
        error_lines = []
        for line in log_lines:
            line_lower = line.lower()
            if any(kw in line_lower for kw in (
                "error", "fatal", "panic", "exception", "traceback",
                "failed", "critical", "segfault", "killed",
            )):
                error_lines.append(line.strip())

        if not error_lines:
            return None

        # Extract unique error signatures (first meaningful token after ERROR/FATAL/etc.)
        signatures = set()
        for line in error_lines:
            # Strip timestamp prefix
            cleaned = re.sub(r"^\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}:\d{2}[^\s]*\s*", "", line)
            # Strip log level
            cleaned = re.sub(r"^(ERROR|FATAL|PANIC|WARN|INFO)\s+", "", cleaned, flags=re.IGNORECASE)
            if len(cleaned) > 10:
                signatures.add(cleaned[:200])

        if not signatures:
            return None

        # Check if these signatures are already in learned patterns
        existing_sigs = set()
        for p in self._learned_patterns:
            for lp in p.get("log_patterns", []):
                existing_sigs.add(lp.lower())

        novel_sigs = [s for s in signatures if s.lower() not in existing_sigs]
        if not novel_sigs:
            return None

        # Create candidate pattern
        pattern_id = f"learned-{datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S')}-{len(self._learned_patterns) + 1}"
        candidate = {
            "id": pattern_id,
            "title": f"Learned: {incident_type} in {namespace}/{workload}",
            "scope": "pod",
            "symptoms": [f"Application error in {workload}"],
            "event_patterns": [],
            "log_patterns": novel_sigs[:5],
            "metric_patterns": [],
            "root_cause": f"Application error detected in {namespace}/{workload}: {novel_sigs[0][:100]}",
            "remediation_steps": [
                f"Check application logs: kubectl logs -n {namespace} -l app={workload}",
                f"Describe pod: kubectl describe pod -n {namespace} -l app={workload}",
                "Review recent deployments for code changes that may have introduced the error",
            ],
            "confidence_hints": [],
            "safe_auto_fix": False,
            "safety_level": "suggest_only",
            "tags": ["learned", incident_type.lower(), namespace],
            "learned_from_namespace": namespace,
            "learned_from_workload": workload,
            "learned_at": datetime.now(timezone.utc).isoformat(),
            "feedback_count": 0,
            "success_count": 0,
        }

        self._learned_patterns.append(candidate)
        self._save_learned_patterns()
        logger.info(
            "Captured new error pattern: id=%s signatures=%d namespace=%s",
            pattern_id, len(novel_sigs), namespace,
        )
        return candidate

    # ------------------------------------------------------------------
    # 2. Refit embedder after new incidents
    # ------------------------------------------------------------------

    def on_incident_saved(self, incident_text: str) -> None:
        """Called after each incident is saved. Triggers embedder refit when threshold reached.

        Args:
            incident_text: The text representation of the saved incident.
        """
        self._incidents_since_refit += 1
        if self._incidents_since_refit >= _REFIT_THRESHOLD:
            self.refit_embedder()
            self._incidents_since_refit = 0

    def refit_embedder(self) -> None:
        """Refit the TF-IDF embedder on all stored incident texts."""
        all_incidents = self._store.get_all_embeddings()
        if not all_incidents:
            return

        texts = []
        for inc in all_incidents:
            text = f"{inc.get('type', '')} {inc.get('namespace', '')} {inc.get('root_cause', '')} {inc.get('title', '')}"
            texts.append(text)

        self._embedder.refit(texts)
        logger.info("Embedder refitted on %d incidents", len(texts))

    # ------------------------------------------------------------------
    # 3. Promote successful remediations into learned KB
    # ------------------------------------------------------------------

    def on_feedback(
        self,
        incident_id: str,
        success: bool,
        correct_root_cause: bool = True,
        better_remediation: Optional[str] = None,
        operator_notes: str = "",
    ) -> None:
        """Process operator feedback to improve future analysis.

        Actions taken:
        - If fix worked: boost the incident's feedback_score, promote pattern if recurring
        - If fix failed: penalize the pattern, record the better_remediation if provided
        - If root cause was wrong: log for future prompt improvement

        Args:
            incident_id: The incident UUID.
            success: Whether the fix worked.
            correct_root_cause: Whether the AI-identified root cause was correct.
            better_remediation: Operator-provided better fix (if any).
            operator_notes: Free-text notes.
        """
        # Update store
        self._store.update_feedback(incident_id, success, operator_notes)

        # Get incident details for pattern promotion
        inc = self._store.get_incident(incident_id)
        if not inc:
            return

        # Update learned patterns that match this incident
        inc_type = inc.get("type", "")
        namespace = inc.get("namespace", "")
        for pattern in self._learned_patterns:
            if (pattern.get("learned_from_namespace") == namespace
                    and inc_type.lower() in [t.lower() for t in pattern.get("tags", [])]):
                pattern["feedback_count"] = pattern.get("feedback_count", 0) + 1
                if success:
                    pattern["success_count"] = pattern.get("success_count", 0) + 1
                if better_remediation:
                    steps = pattern.get("remediation_steps", [])
                    if better_remediation not in steps:
                        steps.insert(0, f"[Operator fix] {better_remediation}")
                        pattern["remediation_steps"] = steps

        # Promote to learned KB if this is a recurring successful pattern
        if success and inc.get("root_cause"):
            self._maybe_promote_pattern(inc)

        self._save_learned_patterns()
        logger.info(
            "Feedback processed: incident=%s success=%s correct_rca=%s",
            incident_id, success, correct_root_cause,
        )

    def _maybe_promote_pattern(self, incident: Dict[str, Any]) -> None:
        """Promote a successful incident fix as a learned pattern if it recurs.

        Only promotes if we've seen 2+ similar incidents in the same namespace
        with the same incident type.

        Args:
            incident: Incident dict from the store.
        """
        inc_type = incident.get("type", "")
        namespace = incident.get("namespace", "")

        # Check if we already have a learned pattern for this
        for p in self._learned_patterns:
            if (p.get("learned_from_namespace") == namespace
                    and p.get("title", "").endswith(f"{inc_type} in {namespace}/{incident.get('workload', '')}")):
                # Already tracked — update success count
                return

        # Check recurrence: how many resolved incidents of this type in this namespace?
        ns_incidents = self._store.get_by_namespace(namespace)
        same_type_resolved = [
            i for i in ns_incidents
            if i.get("type") == inc_type and i.get("resolved")
        ]

        if len(same_type_resolved) < 2:
            return

        # Promote: create a learned pattern from the successful fix
        pattern_id = f"promoted-{namespace}-{inc_type.lower()}-{len(self._learned_patterns) + 1}"
        root_cause = incident.get("root_cause", "")
        suggested_fix = incident.get("suggested_fix", "")

        promoted = {
            "id": pattern_id,
            "title": f"Promoted: {inc_type} in {namespace}/{incident.get('workload', '')}",
            "scope": "pod",
            "symptoms": [f"{inc_type} detected in {namespace}"],
            "event_patterns": [],
            "log_patterns": [],
            "metric_patterns": [],
            "root_cause": root_cause,
            "remediation_steps": [suggested_fix] if suggested_fix else [],
            "confidence_hints": [
                {"pattern": namespace, "boost": 0.2},
                {"pattern": inc_type.lower(), "boost": 0.15},
            ],
            "safe_auto_fix": False,
            "safety_level": "suggest_only",
            "tags": ["promoted", inc_type.lower(), namespace],
            "learned_from_namespace": namespace,
            "learned_from_workload": incident.get("workload", ""),
            "learned_at": datetime.now(timezone.utc).isoformat(),
            "feedback_count": len(same_type_resolved),
            "success_count": len(same_type_resolved),
        }

        self._learned_patterns.append(promoted)
        logger.info(
            "Promoted pattern: id=%s type=%s namespace=%s occurrences=%d",
            pattern_id, inc_type, namespace, len(same_type_resolved),
        )

    # ------------------------------------------------------------------
    # 4. Confidence adjustment based on feedback history
    # ------------------------------------------------------------------

    def adjust_confidence(
        self,
        base_confidence: float,
        incident_type: str,
        namespace: str,
    ) -> float:
        """Adjust AI confidence based on historical feedback for this pattern.

        If past incidents of this type in this namespace were mostly successful,
        boost confidence. If mostly failed, reduce it.

        Args:
            base_confidence: The AI-generated confidence score.
            incident_type: Incident type string.
            namespace: Kubernetes namespace.

        Returns:
            Adjusted confidence score clamped to [0.1, 0.99].
        """
        ns_incidents = self._store.get_by_namespace(namespace)
        same_type = [i for i in ns_incidents if i.get("type") == incident_type]

        if not same_type:
            return base_confidence

        positive = sum(1 for i in same_type if (i.get("feedback_score") or 0) > 0)
        negative = sum(1 for i in same_type if (i.get("feedback_score") or 0) < 0)
        total_feedback = positive + negative

        if total_feedback == 0:
            return base_confidence

        success_rate = positive / total_feedback
        # Boost up to +0.15 for high success rate, penalize up to -0.15 for low
        adjustment = (success_rate - 0.5) * 0.3
        adjusted = base_confidence + adjustment

        return max(0.1, min(0.99, adjusted))

    # ------------------------------------------------------------------
    # 5. Get learning stats
    # ------------------------------------------------------------------

    def get_learning_stats(self) -> Dict[str, Any]:
        """Return statistics about the learning system.

        Returns:
            Dict with learned pattern count, promotion count, refit status.
        """
        total_learned = len(self._learned_patterns)
        promoted = sum(1 for p in self._learned_patterns if p.get("id", "").startswith("promoted-"))
        captured = sum(1 for p in self._learned_patterns if p.get("id", "").startswith("learned-"))

        total_feedback = sum(p.get("feedback_count", 0) for p in self._learned_patterns)
        total_success = sum(p.get("success_count", 0) for p in self._learned_patterns)

        return {
            "total_learned_patterns": total_learned,
            "promoted_patterns": promoted,
            "captured_error_patterns": captured,
            "total_feedback_events": total_feedback,
            "total_successful_fixes": total_success,
            "incidents_since_last_refit": self._incidents_since_refit,
            "refit_threshold": _REFIT_THRESHOLD,
        }
