"""Remediation: rollback a deployment to its previous revision."""
from __future__ import annotations

import logging
import time
from typing import Any, Dict

from models.remediation import RemediationResult
from remediations.base import BaseRemediation

logger = logging.getLogger(__name__)


class RollbackDeploymentRemediation(BaseRemediation):
    """Rolls back a Kubernetes deployment to its previous revision."""

    name = "rollback_deployment"
    description = "Rollback a deployment to the previous working revision (requires approval)"

    def execute(
        self,
        incident_id: str,
        plan_id: str,
        params: Dict[str, Any],
        dry_run: bool = True,
    ) -> RemediationResult:
        """Execute a deployment rollback.

        Args:
            incident_id: Parent incident ID.
            plan_id: Remediation plan ID.
            params: Must include 'namespace' and 'workload'. Optional 'revision' int.
            dry_run: If True, simulate only.

        Returns:
            RemediationResult.
        """
        namespace = params.get("namespace", "default")
        workload = params.get("workload", "")
        revision = params.get("revision", "")
        rev_str = f" --to-revision={revision}" if revision else ""
        command = f"kubectl rollout undo deployment/{workload}{rev_str} -n {namespace}"

        if dry_run:
            return self._dry_run_result(incident_id, plan_id, self.name, command)

        start = time.time()
        try:
            from providers.kubernetes import get_k8s_client
            client = get_k8s_client()
            client.rollback_deployment(namespace=namespace, deployment=workload, revision=revision)
            duration = time.time() - start
            logger.info("Deployment rolled back: %s/%s", namespace, workload)
            return RemediationResult(
                plan_id=plan_id,
                incident_id=incident_id,
                executed_steps=[self.name],
                success=True,
                output=f"Deployment '{workload}' rolled back to previous revision.",
                duration_secs=duration,
            )
        except Exception as exc:
            logger.error("RollbackDeployment failed: %s", exc)
            return RemediationResult(
                plan_id=plan_id,
                incident_id=incident_id,
                executed_steps=[self.name],
                success=False,
                output=f"Rollback failed for '{workload}': {exc}",
                duration_secs=time.time() - start,
            )
