"""Remediation plan generator — produces safe, ordered remediation plans from RCA output."""
from __future__ import annotations

import json
import logging
from typing import Any, Dict, List, Optional

from ai.llm import get_llm_client
from ai.prompts import REMEDIATION_SYSTEM_PROMPT, REMEDIATION_USER_TEMPLATE
from models.incident import Incident
from models.remediation import RemediationPlan, RemediationStep, SafetyLevel

logger = logging.getLogger(__name__)

# Incident type → default remediation strategy
DEFAULT_REMEDIATIONS: Dict[str, List[Dict[str, Any]]] = {
    "CrashLoopBackOff": [
        {
            "order": 1,
            "action": "collect_diagnostics",
            "command": "kubectl describe pod {pod} -n {ns} && kubectl logs {pod} -n {ns} --previous",
            "description": "Collect pod description and previous container logs for diagnostics",
            "safety_level": "auto_fix",
            "reversible": True,
            "estimated_duration_secs": 10,
        },
        {
            "order": 2,
            "action": "rollout_restart",
            "command": "kubectl rollout restart deployment/{workload} -n {ns}",
            "description": "Rolling restart the deployment to clear the failed state",
            "safety_level": "auto_fix",
            "reversible": True,
            "estimated_duration_secs": 120,
        },
    ],
    "OOMKilled": [
        {
            "order": 1,
            "action": "patch_limits",
            "command": "kubectl patch deployment {workload} -n {ns} -p PATCH_JSON",
            "description": "Increase memory limit to prevent future OOMKill (requires approval)",
            "safety_level": "approval_required",
            "reversible": True,
            "estimated_duration_secs": 60,
        },
        {
            "order": 2,
            "action": "rollout_restart",
            "command": "kubectl rollout restart deployment/{workload} -n {ns}",
            "description": "Restart the deployment to apply the new memory limits",
            "safety_level": "auto_fix",
            "reversible": True,
            "estimated_duration_secs": 120,
        },
    ],
    "ImagePullBackOff": [
        {
            "order": 1,
            "action": "rollback_deployment",
            "command": "kubectl rollout undo deployment/{workload} -n {ns}",
            "description": "Rollback to the previous working image version",
            "safety_level": "approval_required",
            "reversible": True,
            "estimated_duration_secs": 90,
        },
        {
            "order": 2,
            "action": "verify_recovery",
            "command": "kubectl rollout status deployment/{workload} -n {ns}",
            "description": "Verify rollback succeeded and pods are running",
            "safety_level": "auto_fix",
            "reversible": True,
            "estimated_duration_secs": 30,
        },
    ],
    "PodPending": [
        {
            "order": 1,
            "action": "scale_up",
            "command": "kubectl scale deployment {workload} -n {ns} --replicas=1",
            "description": "Ensure minimum 1 replica is requested (may already be set)",
            "safety_level": "auto_fix",
            "reversible": True,
            "estimated_duration_secs": 30,
        },
    ],
    "PVCFailure": [
        {
            "order": 1,
            "action": "storage_changes",
            "command": "kubectl describe pvc -n {ns} && kubectl get storageclass",
            "description": "Diagnose PVC binding failure — check StorageClass and provisioner",
            "safety_level": "suggest_only",
            "reversible": True,
            "estimated_duration_secs": 10,
        },
    ],
    "ServiceMismatch": [
        {
            "order": 1,
            "action": "patch_selector",
            "command": "kubectl patch svc {workload} -n {ns} -p '{{\"spec\":{{\"selector\":{{<correct_labels>}}}}}}'",
            "description": "Patch Service selector to match current pod labels (requires approval)",
            "safety_level": "approval_required",
            "reversible": True,
            "estimated_duration_secs": 30,
        },
    ],
    "IngressFailure": [
        {
            "order": 1,
            "action": "patch_selector",
            "command": "kubectl patch ingress {workload} -n {ns} -p '...'",
            "description": "Fix Ingress backend service reference to point to the correct service",
            "safety_level": "approval_required",
            "reversible": True,
            "estimated_duration_secs": 30,
        },
    ],
    "ProbeFailure": [
        {
            "order": 1,
            "action": "patch_probes",
            "command": "kubectl patch deployment {workload} -n {ns} -p '{{\"spec\":{{\"template\":{{\"spec\":{{\"containers\":[{{\"name\":\"{workload}\",\"readinessProbe\":{{\"initialDelaySeconds\":30}}}}]}}}}}}}'",
            "description": "Increase probe initialDelaySeconds to give app more startup time",
            "safety_level": "approval_required",
            "reversible": True,
            "estimated_duration_secs": 60,
        },
    ],
    "HPAMisconfigured": [
        {
            "order": 1,
            "action": "patch_selector",
            "command": "kubectl patch hpa {workload} -n {ns} -p '{{\"spec\":{{\"maxReplicas\":10}}}}'",
            "description": "Update HPA maxReplicas to allow auto-scaling",
            "safety_level": "approval_required",
            "reversible": True,
            "estimated_duration_secs": 10,
        },
    ],
}

SAFETY_LEVEL_MAP: Dict[str, SafetyLevel] = {
    "auto_fix": SafetyLevel.auto_fix,
    "approval_required": SafetyLevel.approval_required,
    "suggest_only": SafetyLevel.suggest_only,
}


class RemediationEngine:
    """Generates structured remediation plans from incident RCA output."""

    def __init__(self) -> None:
        """Initialise the remediation engine."""
        self.llm = get_llm_client()

    def generate_plan(
        self,
        incident: Incident,
        correlation_summary: str = "",
    ) -> RemediationPlan:
        """Generate a RemediationPlan for the given incident.

        Args:
            incident: Incident with populated root_cause and ai_explanation.
            correlation_summary: Optional correlation context string.

        Returns:
            A fully-populated RemediationPlan.
        """
        logger.info(
            "Generating remediation plan for incident: %s", incident.id
        )

        # Try LLM-based plan generation
        plan_data = self._generate_via_llm(incident)

        # Fall back to rule-based if LLM fails
        if not plan_data:
            plan_data = self._generate_rule_based(incident)

        steps = self._build_steps(plan_data.get("steps", []))
        overall_safety = self._determine_overall_safety(steps)
        requires_approval = overall_safety != SafetyLevel.auto_fix

        plan = RemediationPlan(
            incident_id=incident.id,
            summary=plan_data.get("summary", f"Remediate {incident.incident_type.value}"),
            steps=steps,
            overall_safety_level=overall_safety,
            requires_approval=requires_approval,
            auto_executable=not requires_approval,
            estimated_downtime_secs=int(plan_data.get("estimated_downtime_secs", 0)),
            rollback_plan=plan_data.get("rollback_plan", "kubectl rollout undo deployment"),
        )

        logger.info(
            "Remediation plan generated: %s steps, safety=%s, approval_required=%s",
            len(steps),
            overall_safety.value,
            requires_approval,
        )
        return plan

    def _generate_via_llm(self, incident: Incident) -> Optional[Dict[str, Any]]:
        """Attempt to generate a remediation plan via the LLM.

        Args:
            incident: The incident to remediate.

        Returns:
            Parsed dict or None on failure.
        """
        try:
            user_prompt = REMEDIATION_USER_TEMPLATE.format(
                incident_type=incident.incident_type.value,
                root_cause=incident.root_cause or "Unknown",
                namespace=incident.namespace,
                workload=incident.workload,
                pod_name=incident.pod_name or "N/A",
                explanation=incident.ai_explanation or "",
                contributing_factors="\n".join(incident.contributing_factors or []),
            )
            raw = self.llm.chat(system=REMEDIATION_SYSTEM_PROMPT, user=user_prompt)
            return self._parse_plan_response(raw)
        except Exception as exc:
            logger.error("LLM remediation generation failed: %s", exc)
            return None

    def _generate_rule_based(self, incident: Incident) -> Dict[str, Any]:
        """Generate a rule-based remediation plan.

        Args:
            incident: The incident to remediate.

        Returns:
            Dict with remediation plan data.
        """
        incident_type = incident.incident_type.value
        raw_steps = DEFAULT_REMEDIATIONS.get(
            incident_type,
            DEFAULT_REMEDIATIONS["CrashLoopBackOff"],
        )

        # Substitute template variables
        steps = []
        for step in raw_steps:
            step = dict(step)
            if step.get("command"):
                step["command"] = step["command"].format(
                    workload=incident.workload,
                    ns=incident.namespace,
                    pod=incident.pod_name or incident.workload,
                )
            steps.append(step)

        return {
            "summary": f"Rule-based remediation for {incident_type} in {incident.namespace}/{incident.workload}",
            "steps": steps,
            "estimated_downtime_secs": 0,
            "rollback_plan": f"kubectl rollout undo deployment/{incident.workload} -n {incident.namespace}",
        }

    def _build_steps(self, raw_steps: List[Dict[str, Any]]) -> List[RemediationStep]:
        """Convert raw step dicts to RemediationStep objects.

        Args:
            raw_steps: List of step dictionaries.

        Returns:
            List of RemediationStep objects.
        """
        steps = []
        for i, s in enumerate(raw_steps):
            safety_raw = s.get("safety_level", "auto_fix")
            safety = SAFETY_LEVEL_MAP.get(safety_raw, SafetyLevel.auto_fix)
            steps.append(
                RemediationStep(
                    order=s.get("order", i + 1),
                    action=s.get("action", "unknown"),
                    command=s.get("command"),
                    description=s.get("description", ""),
                    safety_level=safety,
                    reversible=bool(s.get("reversible", True)),
                    estimated_duration_secs=int(s.get("estimated_duration_secs", 30)),
                )
            )
        return steps

    def _determine_overall_safety(self, steps: List[RemediationStep]) -> SafetyLevel:
        """Determine the most restrictive safety level across all steps.

        Args:
            steps: List of RemediationStep objects.

        Returns:
            The most restrictive SafetyLevel.
        """
        if not steps:
            return SafetyLevel.suggest_only

        has_suggest_only = any(s.safety_level == SafetyLevel.suggest_only for s in steps)
        has_approval = any(s.safety_level == SafetyLevel.approval_required for s in steps)

        if has_suggest_only:
            return SafetyLevel.suggest_only
        if has_approval:
            return SafetyLevel.approval_required
        return SafetyLevel.auto_fix

    def _parse_plan_response(self, raw: str) -> Optional[Dict[str, Any]]:
        """Parse LLM response as a remediation plan dict.

        Args:
            raw: Raw LLM response string.

        Returns:
            Parsed dict or None.
        """
        try:
            return json.loads(raw)
        except json.JSONDecodeError:
            pass
        try:
            start = raw.index("{")
            end = raw.rindex("}") + 1
            return json.loads(raw[start:end])
        except (ValueError, json.JSONDecodeError):
            return None
