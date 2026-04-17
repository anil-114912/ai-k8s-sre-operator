"""Sidecar auto-injection webhook server.

This implements a Kubernetes MutatingWebhookConfiguration handler that
injects the SRE sidecar container into pods annotated with:

    ai-sre/enabled: "true"

The server is a lightweight FastAPI app that:
1. Receives AdmissionReview requests from the K8s API server
2. Checks whether the pod has the opt-in annotation
3. Patches the pod spec with the sidecar container and shared volume
4. Returns the patch as a JSON Patch base64-encoded AdmissionResponse

Kubernetes MutatingWebhookConfiguration (install separately)::

    apiVersion: admissionregistration.k8s.io/v1
    kind: MutatingWebhookConfiguration
    metadata:
      name: ai-sre-sidecar-injector
    webhooks:
      - name: sidecar.ai-sre.io
        admissionReviewVersions: ["v1"]
        sideEffects: None
        failurePolicy: Ignore    # Don't block pod creation if webhook is down
        clientConfig:
          service:
            name: ai-sre-webhook
            namespace: ai-sre-system
            path: /inject
          caBundle: <base64-ca-cert>
        rules:
          - apiGroups:   [""]
            apiVersions: ["v1"]
            operations:  ["CREATE"]
            resources:   ["pods"]
        namespaceSelector:
          matchExpressions:
            - key: ai-sre/enabled
              operator: In
              values: ["true"]

Usage (standalone)::

    uvicorn webhook.injection:app --host 0.0.0.0 --port 8443 --ssl-keyfile tls.key --ssl-certfile tls.crt
"""

from __future__ import annotations

import base64
import json
import logging
import os
from typing import Any, Dict, List, Optional

from fastapi import FastAPI, HTTPException, Request, Response

logger = logging.getLogger(__name__)

# --- Sidecar configuration -----------------------------------------------
SIDECAR_IMAGE = os.getenv(
    "SIDECAR_IMAGE",
    "ghcr.io/anil-114912/ai-k8s-sre-operator/sidecar:latest",
)
SIDECAR_CONTAINER_NAME = "ai-sre-agent"
SIDECAR_API_URL = os.getenv("SRE_API_URL", "http://ai-sre-operator-api:8000")
SHARED_LOGS_VOLUME = "ai-sre-logs"
OPT_IN_ANNOTATION = "ai-sre/enabled"
INJECT_ANNOTATION = "ai-sre/injected"

app = FastAPI(title="AI SRE Sidecar Injector", version="0.1.0")


# ---------------------------------------------------------------------------
# Health
# ---------------------------------------------------------------------------


@app.get("/health")
async def health() -> Dict[str, Any]:
    return {"status": "ok", "service": "ai-sre-sidecar-injector"}


# ---------------------------------------------------------------------------
# Admission handler
# ---------------------------------------------------------------------------


@app.post("/inject")
async def inject(request: Request) -> Response:
    """Handle a MutatingAdmissionWebhook AdmissionReview request.

    Injects the SRE sidecar into pods that have the opt-in annotation.
    Pods without the annotation are passed through unchanged.
    """
    try:
        body = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid JSON in request body")

    uid = body.get("request", {}).get("uid", "")
    if not uid:
        raise HTTPException(status_code=400, detail="Missing request.uid in AdmissionReview")

    try:
        response = _handle_admission(body["request"])
        response["uid"] = uid
    except Exception as exc:
        logger.exception("Error processing admission request uid=%s: %s", uid, exc)
        # On error, allow the pod through (failsafe)
        response = {
            "uid": uid,
            "allowed": True,
        }

    admission_review = {
        "apiVersion": "admission.k8s.io/v1",
        "kind": "AdmissionReview",
        "response": response,
    }
    return Response(
        content=json.dumps(admission_review),
        media_type="application/json",
    )


# ---------------------------------------------------------------------------
# Core injection logic
# ---------------------------------------------------------------------------


def _handle_admission(req: Dict[str, Any]) -> Dict[str, Any]:
    """Process a single AdmissionRequest and return an AdmissionResponse dict."""
    obj = req.get("object", {})
    metadata = obj.get("metadata", {})
    annotations = metadata.get("annotations") or {}

    # Check opt-in annotation
    if annotations.get(OPT_IN_ANNOTATION, "").lower() != "true":
        logger.debug("Skipping pod %s — missing opt-in annotation", metadata.get("name", "<unnamed>"))
        return {"allowed": True}

    # Skip if already injected (e.g. rolling restart)
    if annotations.get(INJECT_ANNOTATION) == "true":
        logger.debug("Skipping pod %s — already injected", metadata.get("name", "<unnamed>"))
        return {"allowed": True}

    namespace = req.get("namespace", metadata.get("namespace", "default"))
    pod_name = metadata.get("name") or metadata.get("generateName", "unknown")
    logger.info("Injecting sidecar into pod %s/%s", namespace, pod_name)

    patch = _build_patch(obj, namespace)
    patch_bytes = json.dumps(patch).encode("utf-8")
    patch_b64 = base64.b64encode(patch_bytes).decode("utf-8")

    return {
        "allowed": True,
        "patchType": "JSONPatch",
        "patch": patch_b64,
    }


def _build_patch(pod: Dict[str, Any], namespace: str) -> List[Dict[str, Any]]:
    """Build the JSON Patch operations to inject the sidecar."""
    spec = pod.get("spec", {})
    existing_containers = spec.get("containers", [])
    existing_volumes = spec.get("volumes", [])
    existing_annotations = (pod.get("metadata", {}).get("annotations") or {})

    # Determine log path from existing container (first container)
    log_path = "/var/log/app"
    if existing_containers:
        for vm in existing_containers[0].get("volumeMounts", []):
            if "log" in vm.get("name", "").lower():
                log_path = vm.get("mountPath", log_path)
                break

    patch: List[Dict[str, Any]] = []

    # 1. Add shared logs volume (if not present)
    volume_names = {v.get("name") for v in existing_volumes}
    if SHARED_LOGS_VOLUME not in volume_names:
        if not existing_volumes:
            patch.append({"op": "add", "path": "/spec/volumes", "value": []})
        patch.append({
            "op": "add",
            "path": "/spec/volumes/-",
            "value": {
                "name": SHARED_LOGS_VOLUME,
                "emptyDir": {"medium": "Memory", "sizeLimit": "64Mi"},
            },
        })

    # 2. Add volumeMount to main container (first container)
    if existing_containers:
        first_mounts = existing_containers[0].get("volumeMounts", [])
        mount_names = {m.get("name") for m in first_mounts}
        if SHARED_LOGS_VOLUME not in mount_names:
            patch.append({
                "op": "add",
                "path": "/spec/containers/0/volumeMounts/-",
                "value": {
                    "name": SHARED_LOGS_VOLUME,
                    "mountPath": log_path,
                },
            })

    # 3. Inject the sidecar container
    container_names = {c.get("name") for c in existing_containers}
    if SIDECAR_CONTAINER_NAME not in container_names:
        if not existing_containers:
            patch.append({"op": "add", "path": "/spec/containers", "value": []})
        patch.append({
            "op": "add",
            "path": "/spec/containers/-",
            "value": _sidecar_container_spec(log_path, namespace),
        })

    # 4. Mark as injected via annotation
    if not existing_annotations:
        patch.append({
            "op": "add",
            "path": "/metadata/annotations",
            "value": {INJECT_ANNOTATION: "true"},
        })
    else:
        patch.append({
            "op": "add",
            "path": f"/metadata/annotations/{INJECT_ANNOTATION.replace('/', '~1')}",
            "value": "true",
        })

    return patch


def _sidecar_container_spec(log_path: str, namespace: str) -> Dict[str, Any]:
    """Build the sidecar container spec dict."""
    return {
        "name": SIDECAR_CONTAINER_NAME,
        "image": SIDECAR_IMAGE,
        "imagePullPolicy": "IfNotPresent",
        "env": [
            {"name": "LOG_PATH", "value": log_path},
            {"name": "API_URL", "value": SIDECAR_API_URL},
            {"name": "NAMESPACE", "valueFrom": {"fieldRef": {"fieldPath": "metadata.namespace"}}},
            {"name": "POD_NAME", "valueFrom": {"fieldRef": {"fieldPath": "metadata.name"}}},
            {
                "name": "SERVICE_NAME",
                "valueFrom": {"fieldRef": {"fieldPath": "metadata.labels['app']"}},
            },
        ],
        "resources": {
            "requests": {"cpu": "10m", "memory": "32Mi"},
            "limits": {"cpu": "50m", "memory": "64Mi"},
        },
        "volumeMounts": [
            {"name": SHARED_LOGS_VOLUME, "mountPath": log_path, "readOnly": True},
        ],
        "securityContext": {
            "allowPrivilegeEscalation": False,
            "capabilities": {"drop": ["ALL"]},
            "readOnlyRootFilesystem": True,
            "runAsNonRoot": True,
        },
        "livenessProbe": {
            "exec": {"command": ["cat", "/tmp/healthy"]},
            "initialDelaySeconds": 30,
            "periodSeconds": 30,
        },
    }
