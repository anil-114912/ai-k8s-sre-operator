"""Remediation: restart a single pod by deleting it."""
from __future__ import annotations

import logging
import time
from typing import Any, Dict

from models.remediation import RemediationResult
from remediations.base import BaseRemediation

logger = logging.getLogger(__name__)


class RestartPodRemediation(BaseRemediation):
    """Deletes a pod to trigger a fresh restart by the ReplicaSet controller."""

    name = "restart_pod"
    description = "Delete a single pod to force an immediate restart"

    def execute(
        self,
        incident_id: str,
        plan_id: str,
        params: Dict[str, Any],
        dry_run: bool = True,
    ) -> RemediationResult:
        """Delete the specified pod.

        Args:
            incident_id: Parent incident ID.
            plan_id: Remediation plan ID.
            params: Must include 'namespace' and 'pod_name'.
            dry_run: If True, simulate only.

        Returns:
            RemediationResult.
        """
        namespace = params.get("namespace", "default")
        pod_name = params.get("pod_name", "")
        command = f"kubectl delete pod {pod_name} -n {namespace}"

        if dry_run:
            return self._dry_run_result(incident_id, plan_id, self.name, command)

        start = time.time()
        try:
            from providers.kubernetes import get_k8s_client
            client = get_k8s_client()
            result = client.delete_pod(namespace=namespace, pod_name=pod_name)
            duration = time.time() - start
            logger.info("Pod deleted: %s/%s", namespace, pod_name)
            return RemediationResult(
                plan_id=plan_id,
                incident_id=incident_id,
                executed_steps=[self.name],
                success=True,
                output=f"Pod '{pod_name}' deleted successfully. Controller will restart it.",
                duration_secs=duration,
            )
        except Exception as exc:
            logger.error("RestartPod failed: %s", exc)
            return RemediationResult(
                plan_id=plan_id,
                incident_id=incident_id,
                executed_steps=[self.name],
                success=False,
                output=f"Failed to delete pod '{pod_name}': {exc}",
                duration_secs=time.time() - start,
            )
