"""All prompt templates for AI-powered analysis."""

from __future__ import annotations

# ---------------------------------------------------------------------------
# RCA (Root Cause Analysis) prompts
# ---------------------------------------------------------------------------

RCA_SYSTEM_PROMPT = """You are an expert Site Reliability Engineer (SRE) with deep knowledge of Kubernetes operations.
Your task is to perform root cause analysis on Kubernetes incidents.

You reason in a structured, evidence-based manner. You:
1. Examine all available signals (events, logs, metrics, manifests)
2. Classify each signal as: root_cause | contributing_factor | symptom
3. Identify the most likely root cause with a confidence percentage
4. Provide a clear, actionable explanation in plain English
5. List 1-3 alternative hypotheses if the root cause is uncertain

Always format your response as structured JSON."""

RCA_USER_TEMPLATE = """
## Incident Summary
- **Title**: {title}
- **Type**: {incident_type}
- **Severity**: {severity}
- **Namespace**: {namespace}
- **Workload**: {workload}
- **Pod**: {pod_name}
- **Detected At**: {detected_at}

## Detected Signals (pre-classified by rule-based correlator)
### Root Cause Signals:
{root_cause_signals}

### Symptom Signals:
{symptom_signals}

### Contributing Factors:
{contributing_factor_signals}

## Evidence
{evidence_text}

## POD LOGS (last crash output)
{pod_logs}

## LOG ANALYSIS
{log_analysis}

## Chronological Timeline
{timeline_text}

## Similar Past Incidents
{similar_incidents_text}

---
Please provide a JSON response with this exact structure:
{{
  "root_cause": "One clear sentence describing the root cause",
  "confidence": 0.XX,  // float 0-1
  "explanation": "2-3 paragraph plain English explanation of what happened and why",
  "contributing_factors": ["factor1", "factor2"],
  "alternative_hypotheses": ["hypothesis1", "hypothesis2"],
  "suggested_fix": "Specific actionable fix recommendation",
  "severity_justification": "Why this severity level is appropriate"
}}
"""

# ---------------------------------------------------------------------------
# Remediation prompts
# ---------------------------------------------------------------------------

REMEDIATION_SYSTEM_PROMPT = """You are an expert Kubernetes SRE generating safe remediation plans.

You produce structured remediation plans with:
1. Ordered steps, each with a safety level (auto_fix / approval_required / suggest_only)
2. A rollback plan for each destructive action
3. Estimated downtime impact
4. Only safe, proven Kubernetes operations

Safety levels:
- auto_fix: restart_pod, rollout_restart, rerun_job, scale_up (within bounds)
- approval_required: rollback, scale_down, patch_limits, patch_selector, patch_probes
- suggest_only: recreate_secret, rbac_changes, network_policy, storage_changes

Always respond with valid JSON."""

REMEDIATION_USER_TEMPLATE = """
## Incident
- **Type**: {incident_type}
- **Root Cause**: {root_cause}
- **Workload**: {namespace}/{workload}
- **Pod**: {pod_name}

## Analysis
{explanation}

## Contributing Factors
{contributing_factors}

---
Generate a remediation plan as JSON:
{{
  "summary": "One sentence plan summary",
  "steps": [
    {{
      "order": 1,
      "action": "action_name",
      "command": "kubectl ... (optional)",
      "description": "What this step does and why",
      "safety_level": "auto_fix|approval_required|suggest_only",
      "reversible": true|false,
      "estimated_duration_secs": 30
    }}
  ],
  "overall_safety_level": "auto_fix|approval_required|suggest_only",
  "requires_approval": true|false,
  "estimated_downtime_secs": 0,
  "rollback_plan": "Description of how to undo these changes"
}}
"""

# ---------------------------------------------------------------------------
# Enhanced RCA prompt with KB + memory context
# ---------------------------------------------------------------------------

RCA_KB_MEMORY_SYSTEM_PROMPT = """You are an expert Kubernetes SRE with deep knowledge of cloud-native failure patterns.
Analyze incidents using ALL provided evidence: detector results, knowledge base matches, and past incident memory.

Your analysis must be:
1. Grounded in the detector evidence — do not invent signals that are not present
2. Informed by knowledge base patterns — prefer patterns that match the observed signals
3. Enriched by past incident memory — note if similar incidents had successful fixes
4. Precise about confidence — lower confidence when signals are ambiguous

Always respond with valid JSON."""

RCA_KB_MEMORY_USER_TEMPLATE = """
You are an expert Kubernetes SRE. Analyze this incident using ALL provided evidence.

## INCIDENT
Type: {incident_type} | Severity: {severity}
Namespace: {namespace} | Workload: {workload}
Pod: {pod_name} | Detected: {detected_at}

## DETECTOR RESULTS
### Root Cause Signals:
{root_cause_signals}

### Symptom Signals:
{symptom_signals}

### Contributing Factors:
{contributing_factor_signals}

## EVIDENCE
{evidence_text}

## POD LOGS (last crash output)
{pod_logs}

## LOG ANALYSIS
{log_analysis}

## KNOWLEDGE BASE MATCHES
{kb_context}

## SIMILAR PAST INCIDENTS
{memory_context}

## CLUSTER-SPECIFIC PATTERNS
Top recurring failures in this cluster: {cluster_patterns}

## TASK
Provide:
1. Root cause (grounded in detector results and knowledge base — do not guess)
2. Confidence (0.0-1.0) with justification
3. Alternative hypotheses (if any)
4. Exact remediation steps with kubectl commands
5. Whether auto-fix is safe (yes/no with reason)
6. What evidence would confirm or disprove this root cause

Respond as structured JSON:
{{
  "root_cause": "One clear sentence describing the root cause",
  "confidence": 0.XX,
  "explanation": "2-3 paragraph explanation referencing specific evidence",
  "contributing_factors": ["factor1", "factor2"],
  "alternative_hypotheses": ["hypothesis1"],
  "suggested_fix": "Specific actionable fix with kubectl commands",
  "auto_fix_safe": false,
  "auto_fix_reason": "Why auto-fix is or is not safe",
  "confirming_evidence": ["what would confirm this root cause"],
  "severity_justification": "Why this severity level is appropriate"
}}
"""


def rca_with_kb_and_memory(
    incident_type: str,
    severity: str,
    namespace: str,
    workload: str,
    pod_name: str,
    detected_at: str,
    root_cause_signals: str,
    symptom_signals: str,
    contributing_factor_signals: str,
    evidence_text: str,
    kb_context: str,
    memory_context: str,
    cluster_patterns: str,
    pod_logs: str = "",
    log_analysis: str = "",
) -> str:
    """Build the rich KB + memory RCA prompt.

    Args:
        incident_type: Incident type string.
        severity: Severity level string.
        namespace: Kubernetes namespace.
        workload: Workload name.
        pod_name: Pod name or 'N/A'.
        detected_at: ISO timestamp.
        root_cause_signals: Formatted detector root cause signals.
        symptom_signals: Formatted detector symptom signals.
        contributing_factor_signals: Formatted contributing factor signals.
        evidence_text: Formatted evidence.
        kb_context: Knowledge base matches context string.
        memory_context: Similar past incidents context string.
        cluster_patterns: Cluster-specific failure pattern summary.
        pod_logs: Raw log lines from the last container crash.
        log_analysis: Structured log analysis summary string.

    Returns:
        Formatted user prompt string.
    """
    return RCA_KB_MEMORY_USER_TEMPLATE.format(
        incident_type=incident_type,
        severity=severity,
        namespace=namespace,
        workload=workload,
        pod_name=pod_name,
        detected_at=detected_at,
        root_cause_signals=root_cause_signals,
        symptom_signals=symptom_signals,
        contributing_factor_signals=contributing_factor_signals,
        evidence_text=evidence_text,
        kb_context=kb_context or "No knowledge base matches found.",
        memory_context=memory_context or "No similar past incidents found.",
        cluster_patterns=cluster_patterns or "No cluster-specific patterns available.",
        pod_logs=pod_logs or "No logs available",
        log_analysis=log_analysis or "No log analysis available",
    )


# ---------------------------------------------------------------------------
# Incident ranking prompt
# ---------------------------------------------------------------------------

RANKING_SYSTEM_PROMPT = (
    """You are a Kubernetes SRE triage specialist. Rank incidents by business impact and urgency."""
)

RANKING_USER_TEMPLATE = """
Rank these incidents by severity and urgency. Consider: customer impact, blast radius, ease of fix.

Incidents:
{incidents_json}

Return JSON array of incident IDs in priority order with urgency scores (0-1):
[{{"id": "...", "urgency": 0.9, "reason": "..."}}]
"""
