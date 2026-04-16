"""Remediation: rolling restart of a deployment."""

from __future__ import annotations

import logging
import time
from typing import Any, Dict

from models.remediation import RemediationResult
from remediations.base import BaseRemediation

logger = logging.getLogger(__name__)


class RolloutRestartRemediation(BaseRemediation):
    """Performs a rolling restart of a Kubernetes deployment."""

    name = "rollout_restart"
    description = "Trigger a rolling restart of the deployment (zero-downtime)"

    def execute(
        self,
        incident_id: str,
        plan_id: str,
        params: Dict[str, Any],
        dry_run: bool = True,
    ) -> RemediationResult:
        """Perform a rollout restart of the specified deployment.

        Args:
            incident_id: Parent incident ID.
            plan_id: Remediation plan ID.
            params: Must include 'namespace' and 'workload'.
            dry_run: If True, simulate only.

        Returns:
            RemediationResult.
        """
        namespace = params.get("namespace", "default")
        workload = params.get("workload", "")
        command = f"kubectl rollout restart deployment/{workload} -n {namespace}"

        if dry_run:
            return self._dry_run_result(incident_id, plan_id, self.name, command)

        start = time.time()
        try:
            from providers.kubernetes import get_k8s_client

            client = get_k8s_client()
            client.rollout_restart(namespace=namespace, deployment=workload)
            duration = time.time() - start
            logger.info("Rollout restart triggered: %s/%s", namespace, workload)
            return RemediationResult(
                plan_id=plan_id,
                incident_id=incident_id,
                executed_steps=[self.name],
                success=True,
                output=f"Rolling restart initiated for deployment '{workload}' in '{namespace}'.",
                duration_secs=duration,
            )
        except Exception as exc:
            logger.error("RolloutRestart failed: %s", exc)
            return RemediationResult(
                plan_id=plan_id,
                incident_id=incident_id,
                executed_steps=[self.name],
                success=False,
                output=f"Failed to restart deployment '{workload}': {exc}",
                duration_secs=time.time() - start,
            )
