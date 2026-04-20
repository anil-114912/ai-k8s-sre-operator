"""Operator controller — the continuous observe-detect-correlate-analyze-remediate loop."""

from __future__ import annotations

import logging
import os
import time
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

DEMO_MODE = os.getenv("DEMO_MODE", "0") == "1"
AUTO_FIX_ENABLED = os.getenv("AUTO_FIX_ENABLED", "false").lower() == "true"


class CycleResult:
    """Result from a single controller cycle."""

    def __init__(
        self,
        cycle_number: int,
        detections: int,
        incidents_created: int,
        incidents_analyzed: int,
        remediations_triggered: int,
        duration_secs: float,
        errors: List[str],
        timestamp: str,
    ) -> None:
        self.cycle_number = cycle_number
        self.detections = detections
        self.incidents_created = incidents_created
        self.incidents_analyzed = incidents_analyzed
        self.remediations_triggered = remediations_triggered
        self.duration_secs = duration_secs
        self.errors = errors
        self.timestamp = timestamp

    def to_dict(self) -> Dict[str, Any]:
        return {
            "cycle_number": self.cycle_number,
            "detections": self.detections,
            "incidents_created": self.incidents_created,
            "incidents_analyzed": self.incidents_analyzed,
            "remediations_triggered": self.remediations_triggered,
            "duration_secs": round(self.duration_secs, 2),
            "errors": self.errors,
            "timestamp": self.timestamp,
        }


class OperatorController:
    """Runs the continuous SRE operator loop.

    Each cycle:
      1. Collect cluster signals via the K8s provider
      2. Run all 18 detectors against the collected state
      3. Correlate signals (root_cause / symptom / contributing_factor)
      4. Run AI RCA with KB context and incident memory
      5. Persist incidents to the store
      6. Optionally trigger L1 auto-fix remediations
      7. Sleep until next interval

    Usage::

        controller = OperatorController(interval_secs=30)
        controller.start()          # blocking
        # or
        result = controller.run_once()
    """

    def __init__(
        self,
        interval_secs: int = 30,
        demo_mode: Optional[bool] = None,
        auto_remediate: Optional[bool] = None,
        namespace_filter: str = "",
    ) -> None:
        self.interval_secs = interval_secs
        self.demo_mode = demo_mode if demo_mode is not None else DEMO_MODE
        self.auto_remediate = auto_remediate if auto_remediate is not None else AUTO_FIX_ENABLED
        self.namespace_filter = namespace_filter

        self._running = False
        self._cycle_count = 0
        self._last_cycle: Optional[CycleResult] = None
        self._started_at: Optional[str] = None
        self._total_incidents = 0
        self._total_remediations = 0

        # Lazy-load heavy dependencies to keep import time fast
        self._k8s = None
        self._detectors = None
        self._correlator = None
        self._rca_engine = None
        self._rem_engine = None
        self._store = None
        self._kb = None
        self._context_builder = None
        self._guardrails = None

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def start(self) -> None:
        """Start the continuous operator loop (blocking — runs until stop() is called)."""
        self._running = True
        self._started_at = datetime.now(timezone.utc).isoformat()
        logger.info(
            "OperatorController starting: interval=%ds demo_mode=%s auto_remediate=%s",
            self.interval_secs,
            self.demo_mode,
            self.auto_remediate,
        )
        self._ensure_dependencies()

        while self._running:
            cycle_start = time.monotonic()
            try:
                result = self.run_once()
                self._last_cycle = result
                logger.info(
                    "Cycle %d complete: detections=%d incidents=%d analyzed=%d remediations=%d duration=%.1fs",
                    result.cycle_number,
                    result.detections,
                    result.incidents_created,
                    result.incidents_analyzed,
                    result.remediations_triggered,
                    result.duration_secs,
                )
            except Exception as exc:
                logger.error("Cycle %d failed: %s", self._cycle_count, exc, exc_info=True)

            elapsed = time.monotonic() - cycle_start
            sleep_time = max(0, self.interval_secs - elapsed)
            if self._running and sleep_time > 0:
                logger.debug("Sleeping %.1fs until next cycle", sleep_time)
                time.sleep(sleep_time)

        logger.info("OperatorController stopped after %d cycles", self._cycle_count)

    def stop(self) -> None:
        """Signal the loop to stop after the current cycle completes."""
        logger.info("OperatorController stop requested")
        self._running = False

    # ------------------------------------------------------------------
    # Single cycle
    # ------------------------------------------------------------------

    def run_once(self) -> CycleResult:
        """Execute one complete observe-detect-correlate-analyze cycle.

        Returns:
            CycleResult summarising what happened.
        """
        self._ensure_dependencies()
        self._cycle_count += 1
        cycle_start = time.monotonic()
        errors: List[str] = []
        incidents_created = 0
        incidents_analyzed = 0
        remediations_triggered = 0

        # 1. Collect cluster state
        try:
            cluster_state = self._collect_cluster_state()
        except Exception as exc:
            logger.error("Signal collection failed: %s", exc)
            errors.append(f"collection: {exc}")
            cluster_state = {}

        # 2. Run detectors
        detections: list = []
        try:
            from detectors import run_all_detectors

            detections = run_all_detectors(cluster_state)
            logger.debug("Cycle %d: %d detections", self._cycle_count, len(detections))
        except Exception as exc:
            logger.error("Detection failed: %s", exc)
            errors.append(f"detection: {exc}")

        # 3. Correlate signals
        correlation = None
        try:
            raw_signals_dict = {"events_text": str(cluster_state.get("events", []))[:2000]}
            correlation = self._correlator.correlate(
                detections=detections,
                cluster_state=cluster_state,
                raw_signals=raw_signals_dict,
            )
        except Exception as exc:
            logger.error("Correlation failed: %s", exc)
            errors.append(f"correlation: {exc}")

        # 4. Convert detections to incidents and persist
        from knowledge.fingerprint import IncidentFingerprinter

        fingerprinter = IncidentFingerprinter()

        for det in detections:
            if not det.detected:
                continue
            try:
                incident = self._detection_to_incident(det)

                # Deduplication via fingerprint
                fp = fingerprinter.compute(
                    events=cluster_state.get("events", []),
                    resource=det.affected_resource or det.workload or "",
                    error_messages=[ev.content for ev in det.evidence[:3]],
                )
                incident.raw_signals["fingerprint"] = fp

                # Skip if duplicate already open
                if self._is_duplicate(fp):
                    logger.debug("Skipping duplicate incident (fp=%s)", fp[:16])
                    continue

                self._store.save_incident(incident)
                self._register_fingerprint(fp, incident.id)
                incidents_created += 1
                self._total_incidents += 1

            except Exception as exc:
                logger.error("Failed to create incident from detection: %s", exc)
                errors.append(f"incident_create: {exc}")

        # 5. Run RCA on newly created incidents
        recent_incidents = self._get_recent_unanalyzed()
        for incident in recent_incidents[:5]:  # Process up to 5 per cycle
            try:
                kb_context, memory_context, similar, cluster_patterns = (
                    self._build_analysis_context(incident)
                )
                analyzed = self._rca_engine.analyze(
                    incident=incident,
                    correlation=correlation,
                    cluster_state=cluster_state,
                    similar_incidents=similar,
                    kb_context=kb_context,
                    memory_context=memory_context,
                    cluster_patterns=cluster_patterns,
                )
                self._store.save_incident(analyzed)
                incidents_analyzed += 1
            except Exception as exc:
                logger.error("RCA failed for incident %s: %s", incident.id, exc)
                errors.append(f"rca: {exc}")

        # 6. Optionally trigger L1 auto-fix remediations
        if self.auto_remediate:
            remediations_triggered = self._trigger_auto_remediations(recent_incidents[:5])
            self._total_remediations += remediations_triggered

        duration = time.monotonic() - cycle_start
        return CycleResult(
            cycle_number=self._cycle_count,
            detections=len(detections),
            incidents_created=incidents_created,
            incidents_analyzed=incidents_analyzed,
            remediations_triggered=remediations_triggered,
            duration_secs=duration,
            errors=errors,
            timestamp=datetime.now(timezone.utc).isoformat(),
        )

    # ------------------------------------------------------------------
    # Status
    # ------------------------------------------------------------------

    def get_status(self) -> Dict[str, Any]:
        """Return the current operator status as a plain dict."""
        return {
            "running": self._running,
            "demo_mode": self.demo_mode,
            "auto_remediate": self.auto_remediate,
            "interval_secs": self.interval_secs,
            "started_at": self._started_at,
            "cycle_count": self._cycle_count,
            "total_incidents_created": self._total_incidents,
            "total_remediations_triggered": self._total_remediations,
            "last_cycle": self._last_cycle.to_dict() if self._last_cycle else None,
        }

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _ensure_dependencies(self) -> None:
        """Lazily initialise all heavy dependencies."""
        if self._k8s is not None:
            return

        from ai.rca_engine import RCAEngine
        from ai.remediation_engine import RemediationEngine
        from correlation.signal_correlator import SignalCorrelator
        from knowledge.failure_kb import FailureKnowledgeBase
        from knowledge.incident_store import IncidentStore
        from knowledge.learning import ContextBuilder
        from providers.kubernetes import get_k8s_client
        from remediations.policy_guardrails import PolicyGuardrails

        self._k8s = get_k8s_client()
        self._correlator = SignalCorrelator()
        self._rca_engine = RCAEngine()
        self._rem_engine = RemediationEngine()
        self._store = IncidentStore()
        self._kb = FailureKnowledgeBase()
        self._kb.load()
        self._context_builder = ContextBuilder(self._store)
        self._guardrails = PolicyGuardrails()
        self._fingerprint_cache: Dict[str, str] = {}  # fp -> incident_id

    def _collect_cluster_state(self) -> Dict[str, Any]:
        """Collect the full cluster state from the K8s provider."""
        state = self._k8s.get_cluster_state()
        if self.namespace_filter:
            # Filter to requested namespace where possible
            for key in ("pods", "deployments", "services", "pvcs"):
                if key in state and isinstance(state[key], list):
                    state[key] = [
                        r for r in state[key] if r.get("namespace") == self.namespace_filter
                    ]
        return state

    def _detection_to_incident(self, det: Any) -> Any:
        """Convert a DetectionResult to a persisted Incident."""
        from models.incident import Incident, IncidentStatus, IncidentType, Severity

        # Map incident type string to enum, fallback to unknown
        try:
            inc_type = IncidentType(det.incident_type)
        except ValueError:
            inc_type = IncidentType.unknown

        try:
            severity = Severity(det.severity.lower())
        except ValueError:
            severity = Severity.medium

        return Incident(
            title=f"{det.incident_type}: {det.workload or det.affected_resource or 'unknown'} in {det.namespace}",
            incident_type=inc_type,
            severity=severity,
            namespace=det.namespace or "default",
            workload=det.workload or det.affected_resource or "",
            pod_name=det.pod_name or "",
            container_name=det.container_name or "",
            status=IncidentStatus.detected,
            raw_signals=det.raw_signals or {},
            evidence=det.evidence or [],
            detected_at=datetime.now(timezone.utc).isoformat(),
        )

    def _is_duplicate(self, fingerprint: str) -> bool:
        """Check if an identical fingerprint already has an open incident."""
        return fingerprint in self._fingerprint_cache

    def _register_fingerprint(self, fingerprint: str, incident_id: str) -> None:
        """Register a fingerprint → incident mapping."""
        # Keep cache bounded to 500 entries
        if len(self._fingerprint_cache) >= 500:
            oldest = next(iter(self._fingerprint_cache))
            del self._fingerprint_cache[oldest]
        self._fingerprint_cache[fingerprint] = incident_id

    def _get_recent_unanalyzed(self) -> list:
        """Fetch recently created incidents not yet analyzed."""
        from models.incident import Incident, IncidentType, Severity

        try:
            all_dicts = self._store.list_incidents(limit=20)
            results = []
            for d in all_dicts:
                if d.get("root_cause"):
                    continue
                try:
                    inc = Incident(**d)
                except Exception:
                    try:
                        inc_type = IncidentType(d.get("incident_type", "Unknown"))
                    except ValueError:
                        inc_type = IncidentType.unknown
                    try:
                        sev = Severity(d.get("severity", "medium"))
                    except ValueError:
                        sev = Severity.medium
                    inc = Incident(
                        id=d.get("id", ""),
                        title=d.get("title", ""),
                        incident_type=inc_type,
                        severity=sev,
                        namespace=d.get("namespace", "default"),
                        workload=d.get("workload", ""),
                        pod_name=d.get("pod_name"),
                        detected_at=d.get("detected_at", ""),
                        raw_signals=d.get("raw_signals") or {},
                        evidence=d.get("evidence") or [],
                    )
                results.append(inc)
                if len(results) >= 5:
                    break
            return results
        except Exception:
            return []

    def _build_analysis_context(self, incident: Any):
        """Build KB + memory context for RCA."""
        try:
            kb_context = self._context_builder.build_kb_context(
                incident_type=incident.incident_type.value,
                namespace=incident.namespace,
                evidence_text=str(incident.evidence),
                provider=incident.provider_used or "generic",
            )
            memory_context = self._context_builder.build_memory_context(
                incident_type=incident.incident_type.value,
                namespace=incident.namespace,
            )
            similar = self._context_builder.find_similar(incident)
            cluster_patterns = self._store.get_cluster_patterns(
                cluster_name="default", limit=5
            )
            return kb_context, memory_context, similar, cluster_patterns
        except Exception as exc:
            logger.warning("Context build failed: %s", exc)
            return None, None, [], []

    def _trigger_auto_remediations(self, incidents: list) -> int:
        """Trigger L1 auto-fix remediations for analyzed incidents."""
        count = 0
        for incident in incidents:
            if incident.root_cause is None:
                continue
            try:
                plan = self._rem_engine.generate_plan(incident)
                from models.remediation import SafetyLevel

                if plan.overall_safety_level == SafetyLevel.auto_fix:
                    # Validate against guardrails
                    for step in plan.steps:
                        allowed, reason = self._guardrails.validate(
                            step, incident.namespace, incident.workload
                        )
                        if allowed:
                            logger.info(
                                "Auto-fix triggered: action=%s incident=%s",
                                step.action,
                                incident.id,
                            )
                            count += 1
                        else:
                            logger.info("Auto-fix blocked by guardrails: %s", reason)
            except Exception as exc:
                logger.error("Auto-remediation failed: %s", exc)
        return count
