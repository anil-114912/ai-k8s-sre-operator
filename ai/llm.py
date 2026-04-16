"""LLM client supporting Anthropic, OpenAI, and rule-based demo fallback."""

from __future__ import annotations

import json
import logging
import os
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)


def _is_demo_mode() -> bool:
    """Check DEMO_MODE at call time, not import time."""
    return os.getenv("DEMO_MODE", "0").lower() in {"1", "true", "yes"}


DEFAULT_ANTHROPIC_MODEL = "claude-3-5-sonnet-20241022"
DEFAULT_OPENAI_MODEL = "gpt-4o"

# ---------------------------------------------------------------------------
# Rule-based fallback responses (realistic, incident-type-specific)
# ---------------------------------------------------------------------------

FALLBACK_RCA_RESPONSES: Dict[str, Dict[str, Any]] = {
    "CrashLoopBackOff": {
        "root_cause": "The application container is repeatedly crashing because it cannot find a required Kubernetes Secret containing database credentials.",
        "confidence": 0.91,
        "explanation": (
            "The pod enters CrashLoopBackOff because the application process exits with a non-zero code immediately on startup. "
            "Analysis of the pod logs shows the application is failing to load its configuration, specifically reporting that "
            "the Secret 'db-credentials' does not exist in the 'production' namespace.\n\n"
            "The root cause is a missing Kubernetes Secret that was referenced in the pod spec via `envFrom.secretRef` "
            "or `env.valueFrom.secretKeyRef`. The Secret was never created, or was deleted, or was created in the wrong namespace. "
            "Without this Secret, the application cannot initialise its database connection pool and terminates.\n\n"
            "The exponential back-off timer (5m0s) indicates the pod has been failing for an extended period. "
            "A recent deployment change (08:39 UTC) added the Secret reference to the pod spec, but the Secret itself "
            "was never provisioned — this is a configuration-as-code gap where application code changes outpaced infrastructure setup."
        ),
        "contributing_factors": [
            "Recent deployment update added secretRef without creating the Secret first",
            "No pre-deployment Secret existence validation in CI/CD pipeline",
            "Missing readiness gate to prevent rollout until dependencies are ready",
        ],
        "alternative_hypotheses": [
            "Secret exists but is in wrong namespace (production vs default)",
            "Secret exists but is missing the required key (e.g., DATABASE_URL vs DB_URL)",
        ],
        "suggested_fix": "Create the missing Secret 'db-credentials' in the 'production' namespace with the required database credentials keys, then restart the deployment.",
        "severity_justification": "Critical because the payment-api service is completely unavailable, directly impacting revenue-generating payment processing.",
    },
    "OOMKilled": {
        "root_cause": "The application container is consuming memory beyond its configured limit, causing the Linux kernel OOM killer to terminate the process.",
        "confidence": 0.95,
        "explanation": (
            "The container was killed by the Linux kernel Out-Of-Memory (OOM) killer, evidenced by exit code 137 "
            "and the 'OOMKilled' termination reason in the container status. This means the container's memory "
            "usage exceeded the `resources.limits.memory` value configured in the pod spec.\n\n"
            "The OOM kill triggers a container restart, which then enters CrashLoopBackOff if the memory issue "
            "persists across restarts. The application likely has a memory leak, is processing unexpectedly large "
            "payloads, or the memory limit was set too conservatively for the actual workload.\n\n"
            "To resolve this, either increase the memory limit to accommodate peak usage, or investigate the "
            "application code for memory leaks. The safe short-term fix is to increase the limit; "
            "the long-term fix is to profile memory usage and optimise the application."
        ),
        "contributing_factors": [
            "Memory limit set lower than actual peak application memory usage",
            "No memory usage alerting before hitting the hard limit",
            "Possible memory leak in application code causing gradual growth",
        ],
        "alternative_hypotheses": [
            "Sudden spike in request volume caused legitimate memory spike",
            "Memory limit was recently reduced via a misconfigured deployment update",
        ],
        "suggested_fix": "Increase the container memory limit by 50% as immediate relief, then enable memory profiling to identify leaks.",
        "severity_justification": "High severity — application is repeatedly crashing and restarting, causing intermittent service unavailability.",
    },
    "ImagePullBackOff": {
        "root_cause": "Kubernetes cannot pull the container image because the image tag does not exist in the registry, or registry authentication has failed.",
        "confidence": 0.93,
        "explanation": (
            "The container is stuck in ImagePullBackOff because the Kubernetes node cannot pull the specified "
            "container image from the registry. This is typically caused by one of three issues: "
            "the image tag does not exist (e.g., a bad git SHA or typo), the image registry requires authentication "
            "that is not configured (missing imagePullSecret), or the registry is temporarily unavailable.\n\n"
            "The most common cause in production is a failed CI/CD build where the image was never pushed to the "
            "registry, but the deployment was updated to reference the new tag. This results in a '404 Not Found' "
            "response from the registry API, which Kubernetes reports as ErrImagePull before backing off.\n\n"
            "Verify the image exists in the registry using `docker manifest inspect <image>:<tag>`. "
            "If the image is missing, either push it or rollback the deployment to the previous image tag."
        ),
        "contributing_factors": [
            "CI pipeline may have failed after updating the deployment but before pushing the image",
            "Registry authentication credentials may have expired",
        ],
        "alternative_hypotheses": [
            "Image exists but registry credentials (imagePullSecret) are missing or expired",
            "Private registry is temporarily unreachable due to network policy or firewall change",
        ],
        "suggested_fix": "Rollback the deployment to the previous image tag immediately, then investigate why the new image was not pushed to the registry.",
        "severity_justification": "High — the pod is completely unable to start, causing service downtime until the image issue is resolved.",
    },
    "PodPending": {
        "root_cause": "The pod cannot be scheduled because there are insufficient CPU or memory resources available on any node in the cluster.",
        "confidence": 0.87,
        "explanation": (
            "The pod has been stuck in Pending state because the Kubernetes scheduler cannot find a node that "
            "satisfies the pod's resource requests. The FailedScheduling events confirm that all nodes in the cluster "
            "have insufficient allocatable CPU or memory to accommodate this pod's requests.\n\n"
            "The scheduler evaluates every node against the pod's resource requirements and node affinity/taint rules. "
            "If no node passes all predicates, the pod remains Pending indefinitely. This is different from a node "
            "being 'full' — the allocatable capacity accounts for all other pods' requests, not actual usage.\n\n"
            "Resolution options: add more nodes to the cluster (scale out), reduce the pod's resource requests "
            "if they are over-estimated, or remove other low-priority pods to free capacity. "
            "For immediate relief, check if the cluster autoscaler is configured and why it has not triggered."
        ),
        "contributing_factors": [
            "Cluster autoscaler may be configured but has not triggered (check cooldown or max-nodes limit)",
            "Other pods may have unnecessarily large resource requests consuming allocatable capacity",
        ],
        "alternative_hypotheses": [
            "Node selector or affinity rules exclude all available nodes",
            "Pod tolerations do not match node taints, preventing scheduling on specialized nodes",
        ],
        "suggested_fix": "Scale the node group up by adding 1-2 nodes, or enable cluster autoscaler. Verify no node selector/affinity is preventing scheduling.",
        "severity_justification": "High — the pod cannot start at all until a schedulable node is available.",
    },
    "PVCFailure": {
        "root_cause": "The PersistentVolumeClaim cannot be bound because no PersistentVolume matches its storage class, access mode, or capacity requirements.",
        "confidence": 0.89,
        "explanation": (
            "The PVC is stuck in Pending state because the Kubernetes storage subsystem cannot provision or "
            "find a matching PersistentVolume. For dynamic provisioning, this means the StorageClass provisioner "
            "has failed or the requested storage configuration is invalid.\n\n"
            "Common causes: the StorageClass does not exist, the storage provisioner pod is not running, "
            "the cloud provider storage quota is exhausted, or the access mode (e.g., ReadWriteMany) is not "
            "supported by the storage backend. For static provisioning, no pre-provisioned PV matches the PVC's "
            "requirements (size, access mode, storage class).\n\n"
            "Pods mounting this PVC will remain in Pending state until the PVC is Bound. "
            "Check the StorageClass provisioner logs for the specific error."
        ),
        "contributing_factors": [
            "StorageClass provisioner pod may be unhealthy or misconfigured",
            "Cloud provider storage quota may be exhausted",
        ],
        "alternative_hypotheses": [
            "Requested storage capacity exceeds available PV sizes",
            "Access mode ReadWriteMany not supported by the configured storage backend",
        ],
        "suggested_fix": "Check StorageClass exists and provisioner is running. Review cloud storage quotas. If static PV: create a matching PV manually.",
        "severity_justification": "High — any pods mounting this PVC are stuck in Pending, causing service unavailability.",
    },
    "ServiceMismatch": {
        "root_cause": "The Service selector labels do not match any running pod labels, causing the service to have no endpoints and all traffic to fail.",
        "confidence": 0.92,
        "explanation": (
            "The Kubernetes Service has a label selector that does not match any currently running pods. "
            "This means the Service's endpoint list is empty, and all traffic routed to this Service will "
            "receive connection refused or timeout errors.\n\n"
            "This typically happens after a deployment where the pod template labels were changed but the "
            "Service selector was not updated to match, or after a rollback where label versions diverged. "
            "It can also happen if pods are in a non-Running phase (Pending, Crashed) even if the labels match.\n\n"
            "To diagnose: run `kubectl get endpoints <service-name>` to confirm empty endpoints, "
            "then compare `kubectl get svc <name> -o yaml` selector with `kubectl get pods --show-labels`."
        ),
        "contributing_factors": [
            "Recent deployment may have changed pod template labels without updating the Service selector",
            "All pods may be in CrashLoop or Pending state even though labels match",
        ],
        "alternative_hypotheses": [
            "Service was created with incorrect selector labels (typo or wrong key)",
            "Pods were scaled to 0 replicas, so no pods exist to match",
        ],
        "suggested_fix": "Update the Service selector to match the current pod labels, or fix the pod labels to match the Service selector.",
        "severity_justification": "High — all traffic to this service is failing, causing complete service unavailability.",
    },
    "IngressFailure": {
        "root_cause": "The Ingress rule references a backend Service that does not exist or has no ready endpoints.",
        "confidence": 0.90,
        "explanation": (
            "The Kubernetes Ingress controller is unable to route traffic because the backend Service "
            "referenced in the Ingress rules either does not exist in the namespace or has no healthy endpoints.\n\n"
            "When an Ingress rule points to a non-existent Service, the Ingress controller cannot configure "
            "the upstream, and all HTTP requests to that hostname/path return 503 Service Unavailable. "
            "This is a configuration mismatch — the Ingress was created or updated to point to a Service "
            "name that does not match what is actually deployed.\n\n"
            "Check: `kubectl get ingress <name> -o yaml` to see the backend service name, "
            "then `kubectl get svc <backend-name>` to verify it exists."
        ),
        "contributing_factors": [
            "Service name typo in Ingress backend spec",
            "Service was renamed or deleted without updating the Ingress rule",
        ],
        "alternative_hypotheses": [
            "Ingress class annotation missing, causing ingress controller to ignore the rule",
            "TLS certificate misconfiguration preventing the ingress from being active",
        ],
        "suggested_fix": "Fix the Ingress backend service name to match the actual Service, or create the missing Service.",
        "severity_justification": "High — external traffic cannot reach the application at all.",
    },
    "HPAMisconfigured": {
        "root_cause": "The HorizontalPodAutoscaler is misconfigured with equal min and max replicas, preventing any auto-scaling from occurring.",
        "confidence": 0.88,
        "explanation": (
            "The HPA has `minReplicas` set equal to `maxReplicas`, which effectively disables auto-scaling. "
            "The HPA controller will still report metrics but will never change the replica count because "
            "the target is already within the allowed range.\n\n"
            "This misconfiguration often happens when operators pin the replica count for testing or manual "
            "control by setting both min and max to the same value, then forget to restore the scaling range. "
            "The application will not scale up under load, leading to performance degradation or outages.\n\n"
            "Additionally, if the current replicas are already at maxReplicas and CPU utilization is high, "
            "this indicates the service is resource-saturated and cannot handle additional load."
        ),
        "contributing_factors": [
            "HPA was manually pinned during an incident response and not restored",
            "Deployment was scaled via kubectl scale which may conflict with HPA target",
        ],
        "alternative_hypotheses": [
            "Metrics server is not running, preventing the HPA from reading CPU metrics",
            "Custom metrics adapter is misconfigured, causing HPA to use incorrect targets",
        ],
        "suggested_fix": "Set maxReplicas to at least 2x minReplicas to allow meaningful auto-scaling. Review current load and adjust accordingly.",
        "severity_justification": "Medium — service is running but cannot scale to handle load spikes, risking performance degradation.",
    },
    "ProbeFailure": {
        "root_cause": "The application's readiness or liveness probe is failing because the health check endpoint is not responding correctly.",
        "confidence": 0.85,
        "explanation": (
            "The Kubernetes probe is reporting failures because the configured health check endpoint "
            "is returning a non-2xx HTTP status code, timing out, or the TCP connection is being refused. "
            "For readiness probes, this causes the pod to be removed from Service endpoints, "
            "stopping traffic until the probe passes. For liveness probes, Kubernetes will restart the container.\n\n"
            "Common causes: the application is not yet fully initialised (startup time exceeds initialDelaySeconds), "
            "the health endpoint has a dependency check (e.g., database connection) that is failing, "
            "or the probe configuration uses the wrong path or port after a code change.\n\n"
            "Check the probe configuration matches the application's actual health endpoint. "
            "Look at the application logs at probe failure time to see what the health endpoint is returning."
        ),
        "contributing_factors": [
            "Application startup time may exceed probe initialDelaySeconds",
            "Health endpoint checks dependencies (database) that may be slow or unavailable",
        ],
        "alternative_hypotheses": [
            "Application port changed in code but not in probe configuration",
            "Health endpoint was removed or renamed in latest deployment",
        ],
        "suggested_fix": "Increase initialDelaySeconds and timeoutSeconds in the probe config, or fix the health endpoint to return 200 OK reliably.",
        "severity_justification": "Medium — traffic is being interrupted but the pod may still be running and serving some requests.",
    },
}

FALLBACK_REMEDIATION_RESPONSES: Dict[str, Any] = {
    "CrashLoopBackOff_missing_secret": {
        "summary": "Create the missing Secret and restart the deployment to restore service",
        "steps": [
            {
                "order": 1,
                "action": "verify_secret_missing",
                "command": "kubectl get secret db-credentials -n production",
                "description": "Confirm the Secret is missing before taking action",
                "safety_level": "auto_fix",
                "reversible": True,
                "estimated_duration_secs": 5,
            },
            {
                "order": 2,
                "action": "recreate_secret",
                "command": "kubectl create secret generic db-credentials -n production --from-literal=DATABASE_URL=<value>",
                "description": "Create the missing Secret with the required database credentials",
                "safety_level": "suggest_only",
                "reversible": True,
                "estimated_duration_secs": 60,
            },
            {
                "order": 3,
                "action": "rollout_restart",
                "command": "kubectl rollout restart deployment/payment-api -n production",
                "description": "Restart the deployment to pick up the newly created Secret",
                "safety_level": "auto_fix",
                "reversible": True,
                "estimated_duration_secs": 120,
            },
            {
                "order": 4,
                "action": "verify_recovery",
                "command": "kubectl rollout status deployment/payment-api -n production",
                "description": "Verify the deployment has successfully rolled out with the new Secret",
                "safety_level": "auto_fix",
                "reversible": True,
                "estimated_duration_secs": 30,
            },
        ],
        "overall_safety_level": "suggest_only",
        "requires_approval": True,
        "estimated_downtime_secs": 0,
        "rollback_plan": "Delete the created Secret and rollback the deployment: kubectl rollout undo deployment/payment-api -n production",
    },
    "default": {
        "summary": "Restart the affected workload to recover from the detected failure",
        "steps": [
            {
                "order": 1,
                "action": "rollout_restart",
                "command": "kubectl rollout restart deployment/{workload} -n {namespace}",
                "description": "Perform a rolling restart of the deployment to clear the failed state",
                "safety_level": "auto_fix",
                "reversible": True,
                "estimated_duration_secs": 120,
            }
        ],
        "overall_safety_level": "auto_fix",
        "requires_approval": False,
        "estimated_downtime_secs": 0,
        "rollback_plan": "kubectl rollout undo deployment/{workload} -n {namespace}",
    },
}


class LLMClient:
    """Unified LLM client with Anthropic, OpenAI, and rule-based fallback support."""

    def __init__(self) -> None:
        """Initialise the LLM client based on environment configuration."""
        # Read at init time (not import time) so .env is already loaded
        self.provider = os.getenv("LLM_PROVIDER", "anthropic")
        self.demo_mode = _is_demo_mode()
        self._anthropic_client = None
        self._openai_client = None

        if not self.demo_mode:
            self._init_provider()

        logger.info(
            "LLMClient initialised: provider=%s demo_mode=%s has_anthropic=%s",
            self.provider,
            self.demo_mode,
            self._anthropic_client is not None,
        )

    def _init_provider(self) -> None:
        """Initialise the appropriate LLM provider client."""
        # Read keys at call time so they reflect the loaded .env
        anthropic_key = os.getenv("ANTHROPIC_API_KEY", "")
        openai_key = os.getenv("OPENAI_API_KEY", "")

        if self.provider == "anthropic" and anthropic_key:
            try:
                import anthropic

                self._anthropic_client = anthropic.Anthropic(api_key=anthropic_key)
                logger.info("Anthropic client initialised (model=%s)", DEFAULT_ANTHROPIC_MODEL)
            except ImportError:
                logger.warning("anthropic package not installed — pip install anthropic")
                self.demo_mode = True
        elif self.provider == "openai" and openai_key:
            try:
                import openai

                self._openai_client = openai.OpenAI(api_key=openai_key)
                logger.info("OpenAI client initialised (model=%s)", DEFAULT_OPENAI_MODEL)
            except ImportError:
                logger.warning("openai package not installed — pip install openai")
                self.demo_mode = True
        else:
            logger.info(
                "No API key set for provider '%s' — using rule-based fallback. "
                "Set ANTHROPIC_API_KEY in .env to enable AI analysis.",
                self.provider,
            )
            self.demo_mode = True

    def chat(self, system: str, user: str, model: Optional[str] = None) -> str:
        """Send a chat request and return the response text.

        Args:
            system: System prompt establishing the AI's role.
            user: User message with the actual request.
            model: Optional model override.

        Returns:
            Response text from the LLM or rule-based fallback.
        """
        if self.demo_mode:
            return self._rule_based_response(system, user)

        if self.provider == "anthropic" and self._anthropic_client:
            return self._call_anthropic(system, user, model or DEFAULT_ANTHROPIC_MODEL)
        elif self.provider == "openai" and self._openai_client:
            return self._call_openai(system, user, model or DEFAULT_OPENAI_MODEL)
        else:
            return self._rule_based_response(system, user)

    def _call_anthropic(self, system: str, user: str, model: str) -> str:
        """Call the Anthropic API.

        Args:
            system: System prompt.
            user: User message.
            model: Model identifier.

        Returns:
            Response text.
        """
        try:
            response = self._anthropic_client.messages.create(
                model=model,
                max_tokens=2048,
                system=system,
                messages=[{"role": "user", "content": user}],
            )
            return response.content[0].text
        except Exception as exc:
            logger.error("Anthropic API error: %s", exc)
            return self._rule_based_response(system, user)

    def _call_openai(self, system: str, user: str, model: str) -> str:
        """Call the OpenAI API.

        Args:
            system: System prompt.
            user: User message.
            model: Model identifier.

        Returns:
            Response text.
        """
        try:
            response = self._openai_client.chat.completions.create(
                model=model,
                messages=[
                    {"role": "system", "content": system},
                    {"role": "user", "content": user},
                ],
                max_tokens=2048,
            )
            return response.choices[0].message.content
        except Exception as exc:
            logger.error("OpenAI API error: %s", exc)
            return self._rule_based_response(system, user)

    def _rule_based_response(self, system: str, user: str) -> str:
        """Generate a realistic rule-based response without calling any LLM API.

        Args:
            system: System prompt (used to determine response type).
            user: User message (used to detect incident type).

        Returns:
            JSON string with a realistic analysis response.
        """
        # Detect incident type from user message context
        incident_type = self._detect_incident_type_from_text(user)
        logger.info("Rule-based fallback: detected incident_type=%s", incident_type)

        if "remediation" in system.lower() or "remediation" in user.lower():
            return self._get_remediation_response(user, incident_type)

        return self._get_rca_response(incident_type)

    def _detect_incident_type_from_text(self, text: str) -> str:
        """Detect incident type from text content.

        Args:
            text: Text to analyse for incident type indicators.

        Returns:
            Detected incident type string.
        """
        text_lower = text.lower()

        if "crashloopbackoff" in text_lower or "crash_loop" in text_lower:
            return "CrashLoopBackOff"
        elif "oomkilled" in text_lower or "out of memory" in text_lower or "oom" in text_lower:
            return "OOMKilled"
        elif "imagepullbackoff" in text_lower or "errimagepull" in text_lower:
            return "ImagePullBackOff"
        elif "podpending" in text_lower or "pod_pending" in text_lower or "pending" in text_lower:
            return "PodPending"
        elif (
            "pvcfailure" in text_lower
            or "pvc" in text_lower
            or "persistentvolumeclaim" in text_lower
        ):
            return "PVCFailure"
        elif "servicemismatch" in text_lower or "service_mismatch" in text_lower:
            return "ServiceMismatch"
        elif "ingressfailure" in text_lower or "ingress" in text_lower:
            return "IngressFailure"
        elif "hpamisconfigured" in text_lower or "hpa" in text_lower:
            return "HPAMisconfigured"
        elif "probefailure" in text_lower or "probe failed" in text_lower:
            return "ProbeFailure"
        else:
            return "CrashLoopBackOff"  # Most common default

    def _get_rca_response(self, incident_type: str) -> str:
        """Return a realistic RCA JSON response for the given incident type.

        Args:
            incident_type: Incident type string.

        Returns:
            JSON string with RCA analysis.
        """
        response = FALLBACK_RCA_RESPONSES.get(
            incident_type, FALLBACK_RCA_RESPONSES["CrashLoopBackOff"]
        )
        return json.dumps(response, indent=2)

    def _get_remediation_response(self, user: str, incident_type: str) -> str:
        """Return a realistic remediation JSON response.

        Args:
            user: User message for context extraction.
            incident_type: Detected incident type.

        Returns:
            JSON string with remediation plan.
        """
        # Extract namespace/workload from user text for command templating
        user_lower = user.lower()
        namespace = "default"
        workload = "app"
        for part in user.split():
            if "/" in part and len(part.split("/")) == 2:
                ns, wl = part.split("/", 1)
                if ns and wl:
                    namespace, workload = ns, wl
                    break

        # Route to incident-type-specific response
        if "secret" in user_lower and incident_type == "CrashLoopBackOff":
            resp = FALLBACK_REMEDIATION_RESPONSES["CrashLoopBackOff_missing_secret"]
            return json.dumps(resp, indent=2)

        # OOMKilled: include patch_limits step
        if incident_type == "OOMKilled":
            patch_cmd = (
                f"kubectl patch deployment {workload} -n {namespace} -p "
                f'\'{{"spec":{{"template":{{"spec":{{"containers":'
                f'[{{"name":"{workload}","resources":{{"limits":{{"memory":"512Mi"}}}}}}]'
                f"}}}}}}}}}}'"
            )
            resp = {
                "summary": "Increase memory limits and restart {}/{} to prevent OOMKill".format(
                    namespace, workload
                ),
                "steps": [
                    {
                        "order": 1,
                        "action": "patch_limits",
                        "command": patch_cmd,
                        "description": "Increase memory limit by 2x to prevent OOMKill (requires approval)",
                        "safety_level": "approval_required",
                        "reversible": True,
                        "estimated_duration_secs": 60,
                    },
                    {
                        "order": 2,
                        "action": "rollout_restart",
                        "command": "kubectl rollout restart deployment/{} -n {}".format(
                            workload, namespace
                        ),
                        "description": "Rolling restart to apply new memory limits",
                        "safety_level": "auto_fix",
                        "reversible": True,
                        "estimated_duration_secs": 120,
                    },
                ],
                "overall_safety_level": "approval_required",
                "requires_approval": True,
                "estimated_downtime_secs": 0,
                "rollback_plan": "kubectl rollout undo deployment/{} -n {}".format(
                    workload, namespace
                ),
            }
            return json.dumps(resp, indent=2)

        # Default: rolling restart
        resp = dict(FALLBACK_REMEDIATION_RESPONSES["default"])
        steps = []
        for step in resp.get("steps", []):
            step = dict(step)
            if step.get("command"):
                step["command"] = step["command"].format(workload=workload, namespace=namespace)
            steps.append(step)
        resp["steps"] = steps
        return json.dumps(resp, indent=2)


# Module-level singleton
_client: Optional[LLMClient] = None


def get_llm_client() -> LLMClient:
    """Get or create the module-level LLM client singleton.

    Returns:
        LLMClient instance.
    """
    global _client
    if _client is None:
        _client = LLMClient()
    return _client


def reset_llm_client() -> LLMClient:
    """Force-recreate the LLM client singleton (e.g. after updating API key).

    Returns:
        New LLMClient instance.
    """
    global _client
    _client = LLMClient()
    return _client
