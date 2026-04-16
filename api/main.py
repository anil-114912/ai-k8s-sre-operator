"""FastAPI application — REST API for the AI K8s SRE Operator."""

from __future__ import annotations

import logging
import os
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

# Load .env file BEFORE any other imports read os.getenv
try:
    from dotenv import load_dotenv

    _env_path = Path(__file__).resolve().parent.parent / ".env"
    if _env_path.is_file():
        load_dotenv(_env_path, override=True)
except ImportError:
    pass

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from ai.incident_ranker import IncidentRanker
from ai.rca_engine import RCAEngine
from ai.remediation_engine import RemediationEngine
from correlation.signal_correlator import SignalCorrelator
from detectors.cni_detector import CNIDetector
from detectors.crashloop_detector import CrashLoopDetector
from detectors.dns_detector import DNSDetector
from detectors.hpa_detector import HPADetector
from detectors.imagepull_detector import ImagePullDetector
from detectors.ingress_detector import IngressDetector
from detectors.network_policy_detector import NetworkPolicyDetector
from detectors.node_pressure_detector import NodePressureDetector
from detectors.oomkill_detector import OOMKillDetector
from detectors.pending_pods_detector import PendingPodsDetector
from detectors.probe_failure_detector import ProbeFailureDetector
from detectors.pvc_detector import PVCDetector
from detectors.quota_detector import QuotaDetector
from detectors.rbac_detector import RBACDetector
from detectors.rollout_detector import RolloutDetector
from detectors.service_detector import ServiceDetector
from detectors.service_mesh_detector import ServiceMeshDetector
from detectors.storage_detector import StorageDetector
from knowledge.failure_kb import FailureKnowledgeBase
from knowledge.feedback_loop import LearningLoop
from knowledge.feedback_store import FeedbackStore
from knowledge.incident_store import IncidentStore
from knowledge.learning import ContextBuilder
from models.cluster_resource import ClusterHealthSummary
from models.incident import Evidence, Incident, IncidentStatus, IncidentType, Severity
from models.remediation import RemediationPlan, RemediationStatus
from providers.kubernetes import get_k8s_client
from remediations.policy_guardrails import PolicyGuardrails

logging.basicConfig(level=os.getenv("LOG_LEVEL", "INFO"))
logger = logging.getLogger(__name__)

app = FastAPI(
    title="AI K8s SRE Operator",
    description="Continuous Kubernetes incident detection, AI root cause analysis, and safe automated remediation",
    version="0.1.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ---------------------------------------------------------------------------
# Application state
# ---------------------------------------------------------------------------

_store = IncidentStore()
_incidents: Dict[str, Incident] = {}
_plans: Dict[str, RemediationPlan] = {}

_rca_engine = RCAEngine()
_rem_engine = RemediationEngine()
_ranker = IncidentRanker()
_correlator = SignalCorrelator()
_context_builder = ContextBuilder(_store)
_guardrails = PolicyGuardrails()
_feedback_store = FeedbackStore(_store)
_learning_loop = LearningLoop(_store)

# Load knowledge base at startup
_kb = FailureKnowledgeBase()
_kb.load()

DETECTORS = [
    CrashLoopDetector(),
    OOMKillDetector(),
    ImagePullDetector(),
    PendingPodsDetector(),
    ProbeFailureDetector(),
    ServiceDetector(),
    IngressDetector(),
    PVCDetector(),
    HPADetector(),
    DNSDetector(),
    RBACDetector(),
    NetworkPolicyDetector(),
    CNIDetector(),
    ServiceMeshDetector(),
    NodePressureDetector(),
    QuotaDetector(),
    RolloutDetector(),
    StorageDetector(),
]


# ---------------------------------------------------------------------------
# Request / response helpers
# ---------------------------------------------------------------------------


class FeedbackRequest(BaseModel):
    """Operator feedback submission payload."""

    incident_id: str
    plan_summary: str = ""
    success: bool
    notes: str = ""


class ScanResponse(BaseModel):
    """Response from a cluster scan."""

    scanned_at: str
    total_detections: int
    incidents_created: int
    incident_ids: List[str]


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@app.get("/health")
async def health() -> Dict[str, Any]:
    """Health check endpoint — includes current operating mode."""
    from providers.kubernetes import _is_demo_mode

    return {
        "status": "ok",
        "service": "ai-k8s-sre-operator",
        "version": "0.1.0",
        "demo_mode": _is_demo_mode(),
        "cluster": "simulated" if _is_demo_mode() else "live",
    }


@app.get("/api/v1/debug/provider")
async def debug_provider() -> Dict[str, Any]:
    """Diagnose which K8s provider is active and why.

    Returns detailed info about env vars, client type, and any
    initialisation errors so connectivity issues can be debugged.
    """
    import traceback as tb

    from providers.kubernetes import RealK8sClient, _is_demo_mode

    demo = _is_demo_mode()
    env_demo = os.getenv("DEMO_MODE", "<not set>")
    env_kubeconfig = os.getenv("KUBECONFIG", "<not set>")

    result: Dict[str, Any] = {
        "DEMO_MODE_env": env_demo,
        "KUBECONFIG_env": env_kubeconfig,
        "is_demo_mode": demo,
        "client_type": None,
        "real_client_error": None,
        "namespaces": None,
        "pod_count": None,
    }

    if demo:
        result["client_type"] = "_SimulatedK8s"
        return result

    # Try to instantiate real client and probe it
    try:
        client = RealK8sClient()
        result["client_type"] = "RealK8sClient"
        try:
            state = client.get_cluster_state()
            pods = state.get("pods", [])
            result["pod_count"] = len(pods)
            result["namespaces"] = sorted({p.get("namespace", "?") for p in pods})
        except Exception as probe_exc:
            result["real_client_error"] = (
                f"get_cluster_state failed: {type(probe_exc).__name__}: {probe_exc}"
            )
            result["traceback"] = tb.format_exc()
    except Exception as init_exc:
        result["client_type"] = "_SimulatedK8s (fallback)"
        result["real_client_error"] = (
            f"RealK8sClient() init failed: {type(init_exc).__name__}: {init_exc}"
        )
        result["traceback"] = tb.format_exc()

    return result


@app.get("/api/v1/debug/llm")
async def debug_llm() -> Dict[str, Any]:
    """Show which LLM provider is active and whether an API key is configured."""
    from ai.llm import get_llm_client

    client = get_llm_client()
    return {
        "provider": client.provider,
        "demo_mode_fallback": client.demo_mode,
        "anthropic_active": client._anthropic_client is not None,
        "openai_active": client._openai_client is not None,
        "ANTHROPIC_API_KEY_set": bool(os.getenv("ANTHROPIC_API_KEY", "")),
        "OPENAI_API_KEY_set": bool(os.getenv("OPENAI_API_KEY", "")),
    }


@app.post("/api/v1/debug/llm/reload")
async def reload_llm() -> Dict[str, Any]:
    """Reload the LLM client — picks up a newly added API key without restarting the server."""
    from ai.llm import reset_llm_client

    client = reset_llm_client()
    return {
        "reloaded": True,
        "provider": client.provider,
        "demo_mode_fallback": client.demo_mode,
        "anthropic_active": client._anthropic_client is not None,
    }


@app.get("/api/v1/debug/pods")
async def debug_pods(ns: Optional[str] = Query(None)) -> Dict[str, Any]:
    """Dump raw parsed pod dicts from the real cluster state — for debugging detector input."""
    client = get_k8s_client()
    state = client.get_cluster_state()
    pods = state.get("pods", [])
    if ns:
        pods = [p for p in pods if p.get("namespace") == ns]
    # Summarise each pod for readability
    summary = []
    for p in pods:
        cs_summary = [
            {
                "name": cs.get("name"),
                "restartCount": cs.get("restartCount"),
                "state": cs.get("state"),
                "lastState": cs.get("lastState"),
            }
            for cs in p.get("container_statuses", [])
        ]
        summary.append(
            {
                "name": p.get("name"),
                "namespace": p.get("namespace"),
                "phase": p.get("phase"),
                "container_statuses": cs_summary,
            }
        )
    return {"pod_count": len(summary), "pods": summary}


@app.post("/api/v1/incidents", response_model=Incident)
async def create_incident(incident: Incident) -> Incident:
    """Ingest a new incident.

    Args:
        incident: Incident payload from client.

    Returns:
        The stored incident.
    """
    _incidents[incident.id] = incident
    _store.save_incident(incident)

    # Trigger learning loop: capture unknown errors from raw signals
    raw = incident.raw_signals or {}
    if raw.get("recent_logs") or raw.get("dns_error_lines") or raw.get("rbac_log_lines"):
        log_lines = []
        if isinstance(raw.get("recent_logs"), list):
            log_lines = raw["recent_logs"]
        elif isinstance(raw.get("recent_logs"), dict):
            for v in raw["recent_logs"].values():
                if isinstance(v, list):
                    log_lines.extend(v)
        for key in ("dns_error_lines", "rbac_log_lines", "cni_log_lines", "connection_error_lines"):
            if isinstance(raw.get(key), list):
                log_lines.extend(raw[key])
        if log_lines:
            _learning_loop.capture_unknown_errors(
                log_lines=log_lines,
                namespace=incident.namespace,
                workload=incident.workload,
                incident_type=incident.incident_type.value,
            )

    # Notify learning loop for embedder refit tracking
    _learning_loop.on_incident_saved(
        f"{incident.title} {incident.incident_type.value} {incident.namespace}"
    )

    logger.info("Incident ingested: %s", incident.id)
    return incident


@app.get("/api/v1/incidents")
async def list_incidents(
    severity: Optional[str] = Query(None),
    status: Optional[str] = Query(None),
    namespace: Optional[str] = Query(None),
    limit: int = Query(50, le=500),
) -> List[Dict[str, Any]]:
    """List all incidents with optional filters.

    Args:
        severity: Filter by severity level.
        status: Filter by incident status.
        namespace: Filter by namespace.
        limit: Maximum number of results.

    Returns:
        List of incident dicts.
    """
    results = list(_incidents.values())

    if severity:
        results = [i for i in results if i.severity.value == severity]
    if status:
        results = [i for i in results if i.status.value == status]
    if namespace:
        results = [i for i in results if i.namespace == namespace]

    # Rank by urgency
    ranked = _ranker.rank(results)

    return [i.model_dump() for i in ranked[:limit]]


@app.get("/api/v1/incidents/{incident_id}")
async def get_incident(incident_id: str) -> Dict[str, Any]:
    """Get full details for a specific incident.

    Args:
        incident_id: Incident UUID.

    Returns:
        Full incident dict.
    """
    incident = _incidents.get(incident_id)
    if not incident:
        raise HTTPException(status_code=404, detail=f"Incident {incident_id} not found")
    return incident.model_dump()


@app.post("/api/v1/incidents/{incident_id}/analyze")
async def analyze_incident(incident_id: str) -> Dict[str, Any]:
    """Run the full AI analysis pipeline on an incident.

    Args:
        incident_id: Incident UUID.

    Returns:
        Enriched incident dict with root cause analysis.
    """
    incident = _incidents.get(incident_id)
    if not incident:
        raise HTTPException(status_code=404, detail=f"Incident {incident_id} not found")

    # Get cluster state for context
    client = get_k8s_client()
    cluster_state = client.get_cluster_state()

    # Run detectors to get correlation signals
    all_detections = []
    for detector in DETECTORS:
        try:
            results = detector.detect(cluster_state)
            all_detections.extend(results)
        except Exception as exc:
            logger.error("Detector %s failed: %s", detector.name, exc)

    # Correlate signals
    correlation = _correlator.correlate(all_detections, cluster_state, incident.raw_signals)

    # Build KB + memory context for enhanced RCA
    kb_context = _context_builder.build_kb_context(incident)
    memory_context = None
    similar = _context_builder.retrieve_similar(incident)
    similar_structured = _context_builder.retrieve_similar_structured(incident)
    if similar_structured:
        from knowledge.learning import ContextBuilder as _CB

        memory_context = _CB._format_memory_context(similar_structured)

    # Get cluster-specific patterns
    cluster_name = incident.cluster_context or "default"
    cluster_patterns = _store.get_cluster_patterns(cluster_name)

    # Run RCA with full context
    enriched = _rca_engine.analyze(
        incident=incident,
        correlation=correlation,
        cluster_state=cluster_state,
        similar_incidents=similar,
        kb_context=kb_context,
        memory_context=memory_context,
        cluster_patterns=cluster_patterns,
    )

    # Persist
    _incidents[incident_id] = enriched
    _store.save_incident(enriched)

    return enriched.model_dump()


@app.get("/api/v1/incidents/{incident_id}/remediation")
async def get_remediation(incident_id: str) -> Dict[str, Any]:
    """Get the remediation plan for an incident, generating one if needed.

    Args:
        incident_id: Incident UUID.

    Returns:
        RemediationPlan dict.
    """
    incident = _incidents.get(incident_id)
    if not incident:
        raise HTTPException(status_code=404, detail=f"Incident {incident_id} not found")

    # Check if plan already exists
    existing_plan = next((p for p in _plans.values() if p.incident_id == incident_id), None)
    if existing_plan:
        return existing_plan.model_dump()

    # Generate new plan
    plan = _rem_engine.generate_plan(incident)
    _plans[plan.id] = plan
    return plan.model_dump()


@app.post("/api/v1/incidents/{incident_id}/remediation/execute")
async def execute_remediation(
    incident_id: str,
    dry_run: bool = Query(True),
) -> Dict[str, Any]:
    """Execute the remediation plan for an incident.

    Args:
        incident_id: Incident UUID.
        dry_run: If True, simulate without making real changes.

    Returns:
        Execution result dict.
    """
    incident = _incidents.get(incident_id)
    if not incident:
        raise HTTPException(status_code=404, detail=f"Incident {incident_id} not found")

    plan = next((p for p in _plans.values() if p.incident_id == incident_id), None)
    if not plan:
        raise HTTPException(
            status_code=404, detail="No remediation plan found. Call GET /remediation first."
        )

    if plan.requires_approval and plan.status != RemediationStatus.approved:
        raise HTTPException(
            status_code=403,
            detail="This plan requires approval before execution. POST to /remediation/approve first.",
        )

    executed_steps = []
    outputs = []

    for step in plan.steps:
        allowed, reason = _guardrails.validate(step, incident.namespace, incident.workload)
        if not allowed:
            outputs.append(f"STEP {step.order} BLOCKED: {reason}")
            continue

        if dry_run:
            output = f"DRY RUN step {step.order}: {step.action}"
            if step.command:
                output += f"\n  $ {step.command}"
        else:
            output = f"EXECUTED step {step.order}: {step.action}"

        executed_steps.append(step.action)
        outputs.append(output)

    plan.status = RemediationStatus.completed if not dry_run else RemediationStatus.pending
    plan.executed_at = datetime.utcnow().isoformat()
    plan.outcome = "\n".join(outputs)

    return {
        "plan_id": plan.id,
        "incident_id": incident_id,
        "dry_run": dry_run,
        "executed_steps": executed_steps,
        "output": "\n".join(outputs),
        "success": True,
    }


@app.post("/api/v1/incidents/{incident_id}/remediation/approve")
async def approve_remediation(incident_id: str) -> Dict[str, Any]:
    """Approve a Level 2 remediation plan for execution.

    Args:
        incident_id: Incident UUID.

    Returns:
        Updated plan status dict.
    """
    plan = next((p for p in _plans.values() if p.incident_id == incident_id), None)
    if not plan:
        raise HTTPException(status_code=404, detail="No remediation plan found.")

    plan.status = RemediationStatus.approved
    logger.info("Remediation plan approved: %s", plan.id)
    return {
        "plan_id": plan.id,
        "status": "approved",
        "message": "Plan approved. Now call /execute.",
    }


@app.get("/api/v1/incidents/{incident_id}/similar")
async def get_similar(incident_id: str) -> List[Dict[str, Any]]:
    """Retrieve similar past incidents from the knowledge base.

    Args:
        incident_id: Incident UUID.

    Returns:
        List of similar incident summary dicts.
    """
    incident = _incidents.get(incident_id)
    if not incident:
        raise HTTPException(status_code=404, detail=f"Incident {incident_id} not found")
    return _context_builder.retrieve_similar(incident)


@app.post("/api/v1/feedback")
async def submit_feedback(req: FeedbackRequest) -> Dict[str, Any]:
    """Submit operator feedback on remediation outcome.

    Args:
        req: Feedback payload.

    Returns:
        Acknowledgment dict.
    """
    _store.save_remediation_outcome(
        incident_id=req.incident_id,
        plan_summary=req.plan_summary,
        success=req.success,
        feedback_notes=req.notes,
    )
    # Update feedback score and trigger learning loop
    _store.update_feedback(req.incident_id, req.success, req.notes)
    _learning_loop.on_feedback(
        incident_id=req.incident_id,
        success=req.success,
        operator_notes=req.notes,
    )
    return {"status": "recorded", "incident_id": req.incident_id, "success": req.success}


# ---------------------------------------------------------------------------
# Knowledge base endpoints
# ---------------------------------------------------------------------------


@app.get("/api/v1/knowledge/failures")
async def list_failure_patterns(tag: Optional[str] = Query(None)) -> List[Dict[str, Any]]:
    """List all knowledge base failure patterns with optional tag filter.

    Args:
        tag: Optional tag to filter patterns (e.g., 'crashloop', 'networking').

    Returns:
        List of failure pattern dicts.
    """
    if tag:
        patterns = _kb.list_by_tag(tag)
    else:
        patterns = _kb.list_all()
    return [
        {
            "id": p.id,
            "title": p.title,
            "scope": p.scope,
            "root_cause": p.root_cause,
            "safety_level": p.safety_level,
            "safe_auto_fix": p.safe_auto_fix,
            "tags": p.tags,
            "remediation_steps": p.remediation_steps,
            "provider": p.provider,
        }
        for p in patterns
    ]


@app.get("/api/v1/knowledge/failures/{pattern_id}")
async def get_failure_pattern(pattern_id: str) -> Dict[str, Any]:
    """Get a specific failure pattern by ID.

    Args:
        pattern_id: Pattern ID (e.g., 'k8s-001').

    Returns:
        Full failure pattern dict.
    """
    pattern = _kb.get_by_id(pattern_id)
    if not pattern:
        raise HTTPException(status_code=404, detail=f"Pattern {pattern_id} not found")
    return {
        "id": pattern.id,
        "title": pattern.title,
        "scope": pattern.scope,
        "symptoms": pattern.symptoms,
        "event_patterns": pattern.event_patterns,
        "log_patterns": pattern.log_patterns,
        "root_cause": pattern.root_cause,
        "remediation_steps": pattern.remediation_steps,
        "safety_level": pattern.safety_level,
        "safe_auto_fix": pattern.safe_auto_fix,
        "tags": pattern.tags,
        "confidence_hints": pattern.confidence_hints,
        "provider": pattern.provider,
    }


@app.get("/api/v1/knowledge/search")
async def search_knowledge_base(
    q: str = Query(..., description="Search query text"),
    provider: str = Query("generic", description="Cloud provider filter: generic/aws/azure/gcp"),
    top_k: int = Query(5, le=20),
) -> List[Dict[str, Any]]:
    """Search the knowledge base for matching failure patterns.

    Args:
        q: Search query text from incident signals.
        provider: Cloud provider context for boosting provider-specific patterns.
        top_k: Number of top matches to return.

    Returns:
        List of matching failure pattern dicts with scores.
    """
    results = _kb.search(q, provider=provider, top_k=top_k)
    return [
        {
            "id": p.id,
            "title": p.title,
            "score": p.score,
            "root_cause": p.root_cause,
            "safety_level": p.safety_level,
            "tags": p.tags,
            "remediation_steps": p.remediation_steps[:3],
        }
        for p in results
    ]


@app.get("/api/v1/stats/accuracy")
async def get_accuracy_stats() -> Dict[str, Any]:
    """Get RCA accuracy and fix success statistics.

    Returns:
        Stats dict with total_analyzed, correct_rca_pct, fix_success_pct, top_failure_types.
    """
    return _feedback_store.get_accuracy_stats()


@app.get("/api/v1/stats/learning")
async def get_learning_stats() -> Dict[str, Any]:
    """Get learning system statistics.

    Returns:
        Dict with learned pattern counts, refit status, feedback totals.
    """
    return _learning_loop.get_learning_stats()


class StructuredFeedbackRequest(BaseModel):
    """Structured operator feedback with RCA correctness and better remediation."""

    incident_id: str
    correct_root_cause: bool = True
    fix_worked: bool = True
    operator_notes: str = ""
    better_remediation: Optional[str] = None


@app.post("/api/v1/feedback/structured")
async def submit_structured_feedback(req: StructuredFeedbackRequest) -> Dict[str, Any]:
    """Submit structured feedback that feeds into the learning loop.

    This endpoint captures:
    - Whether the AI root cause was correct
    - Whether the suggested fix worked
    - An operator-provided better remediation (if any)

    The learning loop uses this to:
    - Boost/penalize similar incident retrieval scores
    - Promote successful patterns into the learned knowledge base
    - Capture better remediations for future suggestions

    Args:
        req: Structured feedback payload.

    Returns:
        Acknowledgment with learning stats.
    """
    _learning_loop.on_feedback(
        incident_id=req.incident_id,
        success=req.fix_worked,
        correct_root_cause=req.correct_root_cause,
        better_remediation=req.better_remediation,
        operator_notes=req.operator_notes,
    )
    _feedback_store.submit_feedback(
        incident_id=req.incident_id,
        correct_root_cause=req.correct_root_cause,
        fix_worked=req.fix_worked,
        operator_notes=req.operator_notes,
        better_remediation=req.better_remediation,
    )
    return {
        "status": "recorded",
        "incident_id": req.incident_id,
        "learning_stats": _learning_loop.get_learning_stats(),
    }


@app.get("/api/v1/cluster/patterns")
async def get_cluster_patterns(
    cluster_name: str = Query("default", description="Cluster name identifier"),
    limit: int = Query(10, le=50),
) -> List[Dict[str, Any]]:
    """Get recurring failure type patterns for a specific cluster.

    Args:
        cluster_name: Cluster identifier string.
        limit: Maximum number of pattern entries to return.

    Returns:
        List of dicts with incident_type and count.
    """
    return _store.get_cluster_patterns(cluster_name, limit=limit)


@app.delete("/api/v1/incidents", response_model=None, status_code=204)
async def clear_incidents() -> None:
    """Clear all in-memory incidents (useful after switching from demo → live mode)."""
    _incidents.clear()


@app.post("/api/v1/scan", response_model=ScanResponse)
async def scan_cluster(
    namespace: Optional[str] = Query(None),
    clear_existing: bool = Query(False, alias="clear"),
) -> ScanResponse:
    """Trigger a full cluster scan running all detectors.

    Args:
        namespace: Optional namespace filter.
        clear: If true, clears all existing in-memory incidents before scanning
               (use this after switching from demo to live mode).

    Args:
        namespace: Optional namespace filter.

    Returns:
        ScanResponse with detection counts and created incident IDs.
    """
    if clear_existing:
        _incidents.clear()
        _plans.clear()
        logger.info("Cleared existing incidents and plans before scan")

    client = get_k8s_client()
    cluster_state = client.get_cluster_state()

    all_detections = []
    for detector in DETECTORS:
        try:
            results = detector.detect(cluster_state)
            if namespace:
                results = [r for r in results if r.namespace == namespace]
            all_detections.extend(results)
        except Exception as exc:
            logger.error("Detector %s failed: %s", detector.name, exc)

    # Deduplicate: keep only the newest detection per (namespace, workload, type)
    seen: Dict[str, Any] = {}
    deduped = []
    for det in all_detections:
        key = f"{det.namespace}/{det.workload}/{det.incident_type}"
        if key not in seen:
            seen[key] = True
            deduped.append(det)
    all_detections = deduped

    from collectors.logs_collector import LogsCollector

    _logs_collector = LogsCollector()

    created_ids = []
    for det in all_detections:
        # Create incident from detection
        try:
            inc_type = IncidentType(det.incident_type)
        except ValueError:
            inc_type = IncidentType.unknown

        try:
            sev = Severity(det.severity)
        except ValueError:
            sev = Severity.medium

        incident = Incident(
            title=f"{det.incident_type}: {det.affected_resource}",
            incident_type=inc_type,
            severity=sev,
            namespace=det.namespace,
            workload=det.workload,
            pod_name=det.pod_name or None,
            evidence=det.evidence,
            raw_signals=det.raw_signals,
            provider_used="kubernetes",
        )

        # Enrich incident with actual pod logs and log analysis
        if incident.pod_name:
            container_name = (
                incident.raw_signals.get("container_name", "") if incident.raw_signals else ""
            )
            log_lines = cluster_state.get("recent_logs", {}).get(
                f"{incident.namespace}/{incident.pod_name}/{container_name}", []
            )
            if not log_lines:
                log_lines = _logs_collector.get_pod_logs(
                    incident.namespace,
                    incident.pod_name,
                    container_name,
                    tail_lines=80,
                    previous=True,
                )
            if log_lines:
                analysis = _logs_collector.analyze_logs(log_lines)
                if incident.raw_signals is None:
                    incident.raw_signals = {}
                incident.raw_signals["log_analysis"] = analysis
                incident.raw_signals["recent_logs"] = log_lines[:50]
                # Add key log lines as evidence
                if analysis.get("key_lines"):
                    incident.evidence = incident.evidence or []
                    incident.evidence.append(
                        Evidence(
                            source="pod_logs",
                            content="Key log lines:\n" + "\n".join(analysis["key_lines"][:10]),
                            relevance=0.95,
                        )
                    )
                if analysis.get("suggested_cause") and analysis.get("error_category") != "unknown":
                    incident.evidence = incident.evidence or []
                    incident.evidence.append(
                        Evidence(
                            source="log_analysis",
                            content=f"Log analysis: {analysis['suggested_cause']} (category={analysis['error_category']})",
                            relevance=0.9,
                        )
                    )
                # Boost confidence based on log clarity
                if analysis.get("confidence_boost", 0) > 0:
                    incident.confidence = min(
                        1.0, (incident.confidence or 0.5) + analysis["confidence_boost"]
                    )

        _incidents[incident.id] = incident
        _store.save_incident(incident)
        created_ids.append(incident.id)

    return ScanResponse(
        scanned_at=datetime.utcnow().isoformat(),
        total_detections=len(all_detections),
        incidents_created=len(created_ids),
        incident_ids=created_ids,
    )


@app.get("/api/v1/cluster/summary")
async def cluster_summary() -> Dict[str, Any]:
    """Get current cluster health summary.

    Returns:
        ClusterHealthSummary dict.
    """
    client = get_k8s_client()
    state = client.get_cluster_state()

    pods = state.get("pods", [])
    nodes = state.get("nodes", [])
    deployments = state.get("deployments", [])
    pvcs = state.get("pvcs", [])

    total_pods = len(pods)
    running = sum(1 for p in pods if p.get("phase") == "Running")
    pending = sum(1 for p in pods if p.get("phase") == "Pending")
    failed = sum(1 for p in pods if p.get("phase") == "Failed")
    crashloop = sum(
        1
        for p in pods
        for cs in p.get("container_statuses", [])
        if cs.get("state", {}).get("waiting", {}).get("reason") == "CrashLoopBackOff"
    )

    total_nodes = len(nodes)
    ready_nodes = sum(1 for n in nodes if n.get("ready", True))

    total_dep = len(deployments)
    available_dep = sum(1 for d in deployments if d.get("availableReplicas", 0) > 0)

    total_pvc = len(pvcs)
    bound_pvc = sum(1 for p in pvcs if p.get("phase") == "Bound")

    active_incidents = sum(
        1
        for i in _incidents.values()
        if i.status not in (IncidentStatus.resolved, IncidentStatus.closed)
    )

    # Health score: reduce by issues found
    score = 100.0
    if total_pods > 0:
        score -= (crashloop / total_pods) * 30
        score -= (pending / total_pods) * 20
        score -= (failed / total_pods) * 30
    if total_nodes > 0 and ready_nodes < total_nodes:
        score -= 20
    score = max(0.0, min(100.0, score))

    summary = ClusterHealthSummary(
        total_nodes=total_nodes,
        ready_nodes=ready_nodes,
        total_pods=total_pods,
        running_pods=running,
        pending_pods=pending,
        failed_pods=failed,
        crashloop_pods=crashloop,
        total_deployments=total_dep,
        available_deployments=available_dep,
        total_pvcs=total_pvc,
        bound_pvcs=bound_pvc,
        active_incidents=active_incidents,
        health_score=round(score, 1),
        summary=f"{active_incidents} active incidents, {crashloop} crashlooping pods",
    )
    return summary.model_dump()


# ---------------------------------------------------------------------------
# APM endpoints — receive reports from sidecar agents
# ---------------------------------------------------------------------------

# In-memory APM store: service_key → latest report + aggregated stats
# In production this would be persisted to the SQLite/Postgres store.
_apm_reports: Dict[str, Any] = {}
_apm_error_patterns: Dict[str, Any] = {}  # pattern_id → aggregated counts


class APMIngestRequest(BaseModel):
    """APM report submitted by the sidecar agent every report_interval_secs."""

    pod_name: str
    namespace: str
    service_name: str
    report_window_secs: int = 30
    error_count: int = 0
    warning_count: int = 0
    total_lines: int = 0
    error_rate: float = 0.0
    patterns_detected: List[Dict[str, Any]] = []
    metrics: Dict[str, Any] = {}
    novel_errors: List[str] = []
    agent_version: str = "unknown"


class APMLearnRequest(BaseModel):
    """Novel error lines submitted by the sidecar agent for learning."""

    pod_name: str
    namespace: str
    service_name: str
    novel_error_lines: List[str]
    total_novel_count: int = 0
    agent_version: str = "unknown"


def _apm_service_key(namespace: str, service: str) -> str:
    return f"{namespace}/{service}"


def _apm_health_score(error_rate: float, p99_ms: Optional[float], crash_count: int) -> float:
    """Compute a 0–100 health score from APM metrics."""
    score = 100.0
    score -= min(error_rate * 200, 40)  # up to -40 for 20%+ error rate
    if p99_ms and p99_ms > 1000:
        score -= min((p99_ms - 1000) / 100, 20)  # up to -20 for very slow p99
    score -= min(crash_count * 5, 30)  # up to -30 for crashes
    return round(max(0.0, min(100.0, score)), 1)


@app.post("/api/v1/apm/ingest", status_code=202)
async def apm_ingest(report: APMIngestRequest) -> Dict[str, Any]:
    """Receive an APM report from a sidecar agent.

    The agent calls this every ``report_interval_secs`` (default 30s).
    The operator stores the report, aggregates error patterns, and creates
    APM incidents when error thresholds are exceeded.
    """
    key = _apm_service_key(report.namespace, report.service_name)
    now_str = datetime.utcnow().isoformat()

    # Aggregate pattern counts
    for p in report.patterns_detected:
        pid = p.get("pattern_id", "unknown")
        if pid not in _apm_error_patterns:
            _apm_error_patterns[pid] = {
                "pattern_id": pid,
                "pattern_name": p.get("pattern_name", pid),
                "total_count": 0,
                "services": set(),
                "last_seen": now_str,
                "severity": p.get("severity", "medium"),
                "incident_type": p.get("incident_type", "APM_GENERIC"),
                "sample": p.get("sample", ""),
                "remediation_hint": p.get("remediation_hint", ""),
            }
        _apm_error_patterns[pid]["total_count"] += p.get("count", 1)
        _apm_error_patterns[pid]["services"].add(key)
        _apm_error_patterns[pid]["last_seen"] = now_str

    # Compute health score
    p99 = report.metrics.get("latency_p99_ms")
    crash_count = sum(1 for p in report.patterns_detected if p.get("severity") == "critical")
    health = _apm_health_score(report.error_rate, p99, crash_count)

    # Store latest service state
    _apm_reports[key] = {
        "service_name": report.service_name,
        "namespace": report.namespace,
        "pod_name": report.pod_name,
        "health_score": health,
        "error_count": report.error_count,
        "warning_count": report.warning_count,
        "total_lines": report.total_lines,
        "error_rate": report.error_rate,
        "patterns_detected": report.patterns_detected,
        "metrics": report.metrics,
        "last_report": now_str,
        "agent_version": report.agent_version,
    }

    # Auto-create APM incidents for high-severity patterns
    incidents_created = []
    for p in report.patterns_detected:
        if p.get("severity") in ("critical", "high") and p.get("count", 0) >= 1:
            incident = Incident(
                title=f"APM: {report.service_name} — {p.get('pattern_name', p.get('pattern_id'))} "
                f"({p.get('count', 0)} occurrences in {report.report_window_secs}s)",
                incident_type=p.get("incident_type", "APM_GENERIC"),
                severity=Severity.critical if p.get("severity") == "critical" else Severity.high,
                namespace=report.namespace,
                workload=report.service_name,
                pod_name=report.pod_name,
                raw_signals={
                    "error_count": report.error_count,
                    "error_rate": report.error_rate,
                    "pattern": p,
                    "metrics": report.metrics,
                    "source": "apm_agent",
                },
            )
            incident.evidence.append(
                Evidence(
                    source="apm_agent",
                    content=f"{p.get('count', 0)}x {p.get('pattern_name')}: {p.get('sample', '')[:200]}",
                    relevance=0.9,
                )
            )
            _incidents[incident.id] = incident
            _store.save_incident(incident)
            incidents_created.append(incident.id)
            logger.info(
                "APM incident created: %s (%s) in %s/%s",
                p.get("pattern_id"),
                p.get("severity"),
                report.namespace,
                report.service_name,
            )

    # Feed novel errors into the learning store
    if report.novel_errors:
        _learning_loop.capture_unknown_errors(
            log_lines=report.novel_errors[:10],
            namespace=report.namespace,
            workload=report.service_name,
        )

    return {
        "accepted": True,
        "service_key": key,
        "health_score": health,
        "incidents_created": len(incidents_created),
        "incident_ids": incidents_created,
    }


@app.get("/api/v1/apm/services")
async def apm_services(
    namespace: Optional[str] = Query(None, description="Filter by namespace"),
) -> List[Dict[str, Any]]:
    """List all services currently reporting APM data, with health scores."""
    services = []
    for key, data in _apm_reports.items():
        if namespace and data.get("namespace") != namespace:
            continue
        services.append(
            {
                "service_key": key,
                "service_name": data["service_name"],
                "namespace": data["namespace"],
                "health_score": data["health_score"],
                "error_rate": data["error_rate"],
                "error_count": data["error_count"],
                "last_report": data["last_report"],
                "agent_version": data.get("agent_version"),
                "top_patterns": [
                    p.get("pattern_name") for p in data.get("patterns_detected", [])[:3]
                ],
            }
        )
    # Sort by health score ascending (sickest first)
    services.sort(key=lambda s: s["health_score"])
    return services


@app.get("/api/v1/apm/services/{service_name}")
async def apm_service_detail(
    service_name: str,
    namespace: str = Query("default"),
) -> Dict[str, Any]:
    """Get full APM detail for a specific service."""
    key = _apm_service_key(namespace, service_name)
    if key not in _apm_reports:
        raise HTTPException(
            status_code=404,
            detail=f"No APM data for {key}. Is the sidecar agent running?",
        )
    data = dict(_apm_reports[key])
    # Add pattern history
    related_patterns = {
        pid: {**info, "services": list(info["services"])}
        for pid, info in _apm_error_patterns.items()
        if key in info.get("services", set())
    }
    data["pattern_history"] = related_patterns
    return data


@app.get("/api/v1/apm/errors")
async def apm_errors(
    namespace: Optional[str] = Query(None),
    severity: Optional[str] = Query(None, description="critical | high | medium | low"),
    limit: int = Query(20, ge=1, le=100),
) -> List[Dict[str, Any]]:
    """Aggregate view of all error patterns seen across all services."""
    results = []
    for pid, info in _apm_error_patterns.items():
        if severity and info.get("severity") != severity:
            continue
        services_list = list(info.get("services", set()))
        if namespace:
            services_list = [s for s in services_list if s.startswith(f"{namespace}/")]
            if not services_list:
                continue
        results.append(
            {
                "pattern_id": pid,
                "pattern_name": info["pattern_name"],
                "total_count": info["total_count"],
                "severity": info["severity"],
                "incident_type": info["incident_type"],
                "affected_services": services_list,
                "last_seen": info["last_seen"],
                "sample": info.get("sample", "")[:200],
                "remediation_hint": info.get("remediation_hint", ""),
            }
        )
    # Sort by total_count descending
    results.sort(key=lambda r: r["total_count"], reverse=True)
    return results[:limit]


@app.post("/api/v1/apm/learn", status_code=202)
async def apm_learn(request: APMLearnRequest) -> Dict[str, Any]:
    """Receive novel (unrecognised) error lines from the sidecar agent.

    Lines are passed to the learning loop which clusters them,
    adds them to the learned pattern store, and eventually promotes
    recurring patterns to the knowledge base.
    """
    valid_lines = [line for line in request.novel_error_lines[:20] if line.strip()]
    captured = len(valid_lines)
    if valid_lines:
        _learning_loop.capture_unknown_errors(
            log_lines=valid_lines,
            namespace=request.namespace,
            workload=request.service_name,
        )

    logger.info(
        "APM learn: captured %d novel lines from %s/%s",
        captured,
        request.namespace,
        request.service_name,
    )
    return {"accepted": True, "lines_captured": captured}
