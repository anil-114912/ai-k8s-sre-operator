"""Remediation: scale a deployment up or down."""
from __future__ import annotations

import logging
import time
from typing import Any, Dict

from models.remediation import RemediationResult
from remediations.base import BaseRemediation

logger = logging.getLogger(__name__)


class ScaleDeploymentRemediation(BaseRemediation):
    """Scales a deployment to a specified replica count."""

    name = "scale_deployment"
    description = "Scale a deployment to the target replica count"

    def execute(
        self,
        incident_id: str,
        plan_id: str,
        params: Dict[str, Any],
        dry_run: bool = True,
    ) -> RemediationResult:
        """Scale the deployment to the desired replica count.

        Args:
            incident_id: Parent incident ID.
            plan_id: Remediation plan ID.
            params: Must include 'namespace', 'workload', and 'replicas'.
            dry_run: If True, simulate only.

        Returns:
            RemediationResult.
        """
        namespace = params.get("namespace", "default")
        workload = params.get("workload", "")
        replicas = int(params.get("replicas", 1))
        command = f"kubectl scale deployment/{workload} --replicas={replicas} -n {namespace}"

        if dry_run:
            return self._dry_run_result(incident_id, plan_id, self.name, command)

        start = time.time()
        try:
            from providers.kubernetes import get_k8s_client
            client = get_k8s_client()
            client.scale_deployment(namespace=namespace, deployment=workload, replicas=replicas)
            duration = time.time() - start
            logger.info("Deployment scaled: %s/%s -> %d replicas", namespace, workload, replicas)
            return RemediationResult(
                plan_id=plan_id,
                incident_id=incident_id,
                executed_steps=[self.name],
                success=True,
                output=f"Deployment '{workload}' scaled to {replicas} replicas.",
                duration_secs=duration,
            )
        except Exception as exc:
            logger.error("ScaleDeployment failed: %s", exc)
            return RemediationResult(
                plan_id=plan_id,
                incident_id=incident_id,
                executed_steps=[self.name],
                success=False,
                output=f"Scaling failed for '{workload}': {exc}",
                duration_secs=time.time() - start,
            )
