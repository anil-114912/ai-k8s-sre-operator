"""Remediation: patch resource limits/requests on a deployment."""

from __future__ import annotations

import json
import logging
import time
from typing import Any, Dict

from models.remediation import RemediationResult
from remediations.base import BaseRemediation

logger = logging.getLogger(__name__)


class PatchResourcesRemediation(BaseRemediation):
    """Patches container resource limits or requests on a deployment."""

    name = "patch_limits"
    description = "Patch container resource limits (requires approval)"

    def execute(
        self,
        incident_id: str,
        plan_id: str,
        params: Dict[str, Any],
        dry_run: bool = True,
    ) -> RemediationResult:
        """Apply resource limit/request patches to a deployment.

        Args:
            incident_id: Parent incident ID.
            plan_id: Remediation plan ID.
            params: Must include 'namespace', 'workload', 'container_name',
                    and optionally 'memory_limit', 'cpu_limit'.
            dry_run: If True, simulate only.

        Returns:
            RemediationResult.
        """
        namespace = params.get("namespace", "default")
        workload = params.get("workload", "")
        container = params.get("container_name", workload)
        memory_limit = params.get("memory_limit", "512Mi")
        cpu_limit = params.get("cpu_limit", "500m")

        patch = {
            "spec": {
                "template": {
                    "spec": {
                        "containers": [
                            {
                                "name": container,
                                "resources": {
                                    "limits": {
                                        "memory": memory_limit,
                                        "cpu": cpu_limit,
                                    }
                                },
                            }
                        ]
                    }
                }
            }
        }
        patch_json = json.dumps(patch)
        command = f"kubectl patch deployment {workload} -n {namespace} -p '{patch_json}'"

        if dry_run:
            return self._dry_run_result(incident_id, plan_id, self.name, command)

        start = time.time()
        try:
            from providers.kubernetes import get_k8s_client

            client = get_k8s_client()
            client.patch_deployment(namespace=namespace, deployment=workload, patch=patch)
            duration = time.time() - start
            logger.info(
                "Resource limits patched: %s/%s memory=%s cpu=%s",
                namespace,
                workload,
                memory_limit,
                cpu_limit,
            )
            return RemediationResult(
                plan_id=plan_id,
                incident_id=incident_id,
                executed_steps=[self.name],
                success=True,
                output=f"Resource limits updated: memory={memory_limit}, cpu={cpu_limit}",
                duration_secs=duration,
            )
        except Exception as exc:
            logger.error("PatchResources failed: %s", exc)
            return RemediationResult(
                plan_id=plan_id,
                incident_id=incident_id,
                executed_steps=[self.name],
                success=False,
                output=f"Patch failed: {exc}",
                duration_secs=time.time() - start,
            )
