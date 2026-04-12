"""Remediation: re-create a failed Kubernetes Job."""
from __future__ import annotations

import logging
import time
from typing import Any, Dict

from models.remediation import RemediationResult
from remediations.base import BaseRemediation

logger = logging.getLogger(__name__)


class RerunJobRemediation(BaseRemediation):
    """Deletes and re-creates a failed Kubernetes Job."""

    name = "rerun_job"
    description = "Delete and recreate a failed Kubernetes Job"

    def execute(
        self,
        incident_id: str,
        plan_id: str,
        params: Dict[str, Any],
        dry_run: bool = True,
    ) -> RemediationResult:
        """Re-run the specified failed job.

        Args:
            incident_id: Parent incident ID.
            plan_id: Remediation plan ID.
            params: Must include 'namespace' and 'job_name'.
            dry_run: If True, simulate only.

        Returns:
            RemediationResult.
        """
        namespace = params.get("namespace", "default")
        job_name = params.get("job_name", params.get("workload", ""))
        command = (
            f"kubectl delete job {job_name} -n {namespace} && "
            f"kubectl create job {job_name}-retry -n {namespace} --from=cronjob/{job_name}"
        )

        if dry_run:
            return self._dry_run_result(incident_id, plan_id, self.name, command)

        start = time.time()
        try:
            from providers.kubernetes import get_k8s_client
            client = get_k8s_client()
            client.rerun_job(namespace=namespace, job_name=job_name)
            duration = time.time() - start
            logger.info("Job rerun triggered: %s/%s", namespace, job_name)
            return RemediationResult(
                plan_id=plan_id,
                incident_id=incident_id,
                executed_steps=[self.name],
                success=True,
                output=f"Job '{job_name}' deleted and recreated successfully.",
                duration_secs=duration,
            )
        except Exception as exc:
            logger.error("RerunJob failed: %s", exc)
            return RemediationResult(
                plan_id=plan_id,
                incident_id=incident_id,
                executed_steps=[self.name],
                success=False,
                output=f"Job rerun failed: {exc}",
                duration_secs=time.time() - start,
            )
