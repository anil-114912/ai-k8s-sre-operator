# Incident Examples

Six end-to-end walkthroughs of real failure patterns the system detects, analyzes, and remediates. Each example follows the same structure: what you see → what the system finds → what it recommends.

---

## 1. CrashLoopBackOff — Missing Secret

### Situation

A developer updates the `payment-api` deployment to read database credentials from a Kubernetes Secret. The Secret was created in the `staging` namespace but not in `production`. The deployment rolls out and the pods immediately begin crashing.

### What you observe

```bash
$ kubectl get pods -n production
NAME                          READY   STATUS             RESTARTS   AGE
payment-api-7d9f8b-xk2p9     0/1     CrashLoopBackOff   18         23m
```

### Kubernetes events

```
Warning  BackOff  18x  kubelet   Back-off restarting failed container payment-api
Warning  Failed    1x  kubelet   Error: secret "db-credentials" not found
```

### Container logs (last 6 lines)

```
2024-01-15T09:23:35Z INFO  Starting payment-api v1.5.2
2024-01-15T09:23:36Z INFO  Loading configuration from environment
2024-01-15T09:23:36Z ERROR Failed to load config: secret 'db-credentials' not found in namespace 'production'
2024-01-15T09:23:36Z ERROR Database connection pool initialization failed: host=<nil>
2024-01-15T09:23:37Z FATAL Application startup failed — cannot continue without database configuration
2024-01-15T09:23:38Z ERROR panic: runtime error: invalid memory address or nil pointer dereference
```

### Recent changes detected by the system

```
2024-01-15T08:39:00Z  ConfigChange  Deployment payment-api updated — env secretRef db-credentials added
2024-01-15T08:40:00Z  Deployment    Scaled up replica set payment-api-7d9f8b to 3
```

### AI root cause

> **Root cause:** The `payment-api` deployment references a Kubernetes Secret named `db-credentials` in the `production` namespace. This Secret does not exist. The deployment was updated 4 minutes before the first crash to add `envFrom.secretRef.name: db-credentials`. Every pod restarts, fails immediately on startup, and enters backoff. This is not a code bug — the application is functioning as expected by refusing to start without required configuration.
>
> **KB pattern matched:** k8s-001 (CrashLoopBackOff — missing Secret)
> **Confidence:** 0.97
> **Evidence signals:** (1) k8s event "secret not found", (2) log line matching `secret .* not found`, (3) deployment change 4m before first crash

### Remediation plan (L3 — suggest only)

Safety level is L3 because creating a Secret is always suggest-only — the system has no way to know the correct credential values.

```bash
# Step 1: Confirm the secret is absent
kubectl get secret db-credentials -n production
# Expected: Error from server (NotFound)

# Step 2: Create the secret with correct values
kubectl create secret generic db-credentials \
  --from-literal=DB_HOST=postgres.production.svc.cluster.local \
  --from-literal=DB_PORT=5432 \
  --from-literal=DB_NAME=payments \
  --from-literal=DB_USER=payment_svc \
  --from-literal=DB_PASSWORD=<your-password> \
  -n production

# Step 3: Confirm pods recover
kubectl rollout status deployment/payment-api -n production
```

### Expected outcome

Within 60 seconds of Secret creation, the backoff timer clears, the pods start successfully, and the deployment reaches `3/3 READY`.

### API call

```bash
# Get the full RCA and plan in one call
curl http://localhost:8000/api/v1/incidents/inc-001/analyze | jq '{root_cause, confidence, remediation_hint}'
```

---

## 2. Service Selector Mismatch — 503 on All Requests

### Situation

A team renames the label `app: frontend` to `app: frontend-v2` in a new deployment rollout. They forget to update the Service selector. All traffic to the Service now returns 503 because it has no matching Endpoints.

### What you observe

```bash
$ kubectl get endpoints frontend-svc -n production
NAME            ENDPOINTS   AGE
frontend-svc    <none>      45s
```

```bash
# All requests to the service return 503
curl -v http://frontend-svc.production.svc/api/health
# 503 Service Unavailable
```

### Kubernetes events

```
Warning  FailedMount   pod/frontend-v2-abc123   No endpoints available for service "frontend-svc"
```

### Detector output

The `ServiceMismatchDetector` runs on every scan. It compares:
- Service selector: `{ app: frontend }`
- Pods in namespace with that label: **0 pods found**
- Pods in namespace with `app: frontend-v2`: **3 pods found**

### AI root cause

> **Root cause:** The `frontend-svc` Service in `production` selects pods with label `app: frontend`, but no pods currently carry that label. The deployment `frontend-v2` carries label `app: frontend-v2`. This is a label mismatch introduced during the deployment rename — the Service selector was not updated to match the new pod labels. The Service has been routing to 0 endpoints for 45 seconds.
>
> **KB pattern matched:** k8s-011 (Service — selector mismatch, no endpoints)
> **Confidence:** 0.94
> **Evidence signals:** (1) Endpoints resource shows `<none>`, (2) 3 pods exist with close label match, (3) deployment change 47 seconds ago

### Remediation plan (L2 — approval required)

Patching a Service selector is L2 because an incorrect patch could misdirect traffic cluster-wide.

```bash
# Step 1: Verify the label mismatch
kubectl get svc frontend-svc -n production -o jsonpath='{.spec.selector}'
# {"app":"frontend"}

kubectl get pods -n production -l app=frontend-v2
# 3 running pods

# Step 2: Patch the service selector (requires approval in the UI)
kubectl patch service frontend-svc -n production \
  -p '{"spec":{"selector":{"app":"frontend-v2"}}}'

# Step 3: Confirm endpoints are populated
kubectl get endpoints frontend-svc -n production
# NAME            ENDPOINTS                         AGE
# frontend-svc    10.0.1.4:8080,10.0.1.5:8080,...  12s
```

### Expected outcome

Endpoints are populated immediately after the selector patch. Traffic resumes within seconds.

---

## 3. Pending Pods — Node Resource Exhaustion

### Situation

The `batch-processor` deployment is scaled from 2 to 20 replicas by an HPA responding to a queue backlog. The cluster nodes are running at 87% CPU allocation. Kubernetes cannot schedule 15 of the 20 new pods.

### What you observe

```bash
$ kubectl get pods -n batch -l app=batch-processor | grep Pending
batch-processor-6b8f4d-bj9kl   0/1   Pending   0   8m
batch-processor-6b8f4d-cx3mp   0/1   Pending   0   8m
# (13 more Pending)
```

### Kubernetes events on pending pod

```
Warning  FailedScheduling  8m   default-scheduler
  0/6 nodes are available:
  2 nodes have insufficient cpu,
  4 nodes had taint {node.kubernetes.io/not-ready:NoSchedule}
  preemption: 0/6 nodes are available
```

### Signals correlated by the system

1. **PendingPodDetector** — 15 pods stuck Pending for > 2 minutes
2. **NodePressureDetector** — 2 of 6 nodes above 85% CPU allocation
3. **HPADetector** — HPA for `batch-processor` is saturated (current = max)
4. **QuotaDetector** — namespace CPU quota at 94% utilization

### AI root cause

> **Root cause:** The `batch-processor` HPA scaled to 20 replicas in response to a queue spike. The cluster has 6 nodes but 2 are unavailable (NotReady after a recent rolling node update), and the remaining 4 are running at 87–92% CPU allocation. The scheduler cannot satisfy the CPU requests of 15 pending pods. The HPA correctly scaled, but the cluster lacks capacity headroom to absorb the surge. This is a cluster sizing issue compounded by the timing of the node update.
>
> **KB pattern matched:** k8s-008 (Pod Pending — insufficient CPU), clust-001 (ResourceQuota exceeded contributing factor)
> **Confidence:** 0.88

### Remediation plan (L1/L2 mixed → overall L2)

```bash
# Step 1 (diagnostic — L1 auto-fix eligible):
kubectl describe nodes | grep -A5 "Allocated resources"

# Step 2 (scale HPA max down temporarily — L2 requires approval):
kubectl patch hpa batch-processor-hpa -n batch \
  --type=merge -p '{"spec":{"maxReplicas":8}}'

# Step 3 (long-term — suggest only L3):
# Add a new node group or increase node pool size
# EKS: aws eks update-nodegroup-config --cluster-name <> --nodegroup-name <> --scaling-config minSize=3,maxSize=15,desiredSize=10
# AKS: az aks nodepool scale --resource-group <> --cluster-name <> --name <> --node-count 10
# GKE: gcloud container clusters resize <> --node-pool <> --num-nodes 10
```

---

## 4. Ingress 502 — Backend Has No Endpoints

### Situation

The `checkout-api` Service exists, its Ingress rule is correctly configured, but all requests via the Ingress return 502 Bad Gateway. The root cause is that the Service's label selector does not match any running pods — a different but related failure to example 2.

### What you observe

```bash
# External requests return 502
curl -I https://api.example.com/checkout
# HTTP/1.1 502 Bad Gateway
# Via: nginx/1.25.3

# But the pods are running
kubectl get pods -n production -l app=checkout-api
# checkout-api-5d7c9f-lm4pk   1/1   Running   0   2h
```

### Kubernetes events

```
Warning  BackendNotFound   ingress/checkout-ingress
  Service "checkout-api" port 8080 has no endpoints
```

### Detector findings

- `IngressDetector` — Ingress `checkout-ingress` rule points to `checkout-api:8080`
- `ServiceMismatchDetector` — `checkout-api` Service has 0 endpoints
- Service selector: `{ app: checkout-api, version: stable }` — no pods with `version: stable` label found
- Running pods have label: `{ app: checkout-api, version: v2.1.0 }`

### AI root cause

> **Root cause:** The `checkout-api` Service selector requires both `app: checkout-api` AND `version: stable`. The running pods have `version: v2.1.0`, not `version: stable`. The `stable` label was previously maintained via a manual `kubectl label` step that was missed during this deployment. The Ingress is correctly configured — the backend failure is at the Service-to-Pod level.
>
> **Confidence:** 0.92

### Remediation plan (L2 — approval required)

```bash
# Option A: Fix the service selector to match current pods
kubectl patch service checkout-api -n production \
  -p '{"spec":{"selector":{"app":"checkout-api","version":"v2.1.0"}}}'

# Option B: Add the missing label to the running pods
kubectl label pods -n production -l app=checkout-api version=stable

# Verify endpoints appear
kubectl get endpoints checkout-api -n production

# Verify Ingress resolves
curl -I https://api.example.com/checkout
```

---

## 5. OOMKilled — Memory Limit Under-provisioned for Load

### Situation

The `report-generator` service processes large PDF exports. A marketing campaign generates 10x normal report load. The pods are OOMKilled repeatedly, each restart taking 30+ seconds, causing reports to fail and pile up.

### What you observe

```bash
$ kubectl get pods -n production
NAME                           READY   STATUS      RESTARTS   AGE
report-generator-9c4b7e-rk8mn  0/1     OOMKilled   5          18m
```

### Kubernetes events

```
Warning  OOMKilling  node/ip-10-0-2-11
  Memory cgroup out of memory: Kill process 28471 (python3) score 999 or sacrifice child
  Killed process 28471 (python3) total-vm:982604kB, anon-rss:511908kB
```

### Memory profile (from metrics)

```
container_memory_working_set_bytes{pod="report-generator-*"} growing
Time 14:00 → 156Mi
Time 14:10 → 234Mi
Time 14:18 → 511Mi  ← OOMKill (limit: 512Mi)
```

### Signals correlated

1. **OOMKillDetector** — pod killed 5 times, reason OOMKill
2. **HPADetector** — HPA scaled from 1 to 3 replicas 20 minutes ago (queue growing)
3. **MetricsCollector** — memory growing linearly with request count, no plateau — this is not a leak

### AI root cause

> **Root cause:** The `report-generator` container has a `512Mi` memory limit, which was sized for baseline load. Under 10x load, generating a single large PDF report requires approximately 400–500Mi of working memory (PDF rendering, image processing, font loading). At current concurrency, the container exceeds the limit. The memory growth is proportional to request volume, not continuous (not a leak) — this is a resource sizing problem, not a code problem.
>
> **KB pattern matched:** k8s-003 (CrashLoopBackOff — OOMKill)
> **Confidence:** 0.86
> **Evidence:** OOMKill event + memory working set trend + concurrent HPA scale event

### Remediation plan (L2 — approval required)

```bash
# Step 1: Check what the container is actually using at peak
kubectl top pod -l app=report-generator -n production --containers

# Step 2: Increase memory limit (requires approval)
kubectl set resources deployment/report-generator \
  --limits=memory=1Gi --requests=memory=512Mi \
  -n production

# Step 3: Monitor for stability
kubectl rollout status deployment/report-generator -n production
kubectl top pod -l app=report-generator -n production --containers

# Step 4 (longer term — L3 suggest):
# Add a queue depth limit to cap concurrency per pod
# Or add Vertical Pod Autoscaler (VPA) to adjust limits automatically
```

### Expected outcome

After the limit increase, the rolling restart completes. Memory peaks at ~700Mi under load and stabilises. Backlogged reports process successfully.

---

## 6. EKS — IRSA Misconfiguration Blocking AWS API Calls

### Situation

A new microservice `s3-exporter` is deployed to EKS. It needs to write to an S3 bucket. The IAM role is correctly defined in AWS, but the pods cannot authenticate. All S3 API calls return `InvalidClientTokenId`.

### What you observe

```bash
$ kubectl logs s3-exporter-8d7c6b-mn2pk -n production | tail -5
2024-01-15T11:30:15Z ERROR aws: operation error S3: PutObject
  https response error StatusCode: 403
  api error InvalidClientTokenId: The security token included in the request is invalid
2024-01-15T11:30:15Z ERROR Export failed: s3://company-exports/reports/jan-15.csv
```

### Kubernetes events

```
Warning  FailedMount  pod/s3-exporter-8d7c6b-mn2pk
  Unable to mount volumes: token "aws-iam-token" expired or invalid
```

### Detector findings (EKS-specific)

The `RBACDetector` and cloud-provider context combine:

```yaml
# Pod service account annotation
annotations:
  eks.amazonaws.com/role-arn: "arn:aws:iam::123456789012:role/s3-exporter-role"

# Trust policy on the IAM role (fetched via debug):
# Condition: StringEquals:
#   sts.amazonaws.com/aud: sts.amazonaws.com
#   sts.amazonaws.com/sub: system:serviceaccount:staging:s3-exporter  ← WRONG NAMESPACE
```

### AI root cause

> **Root cause:** IAM Roles for Service Accounts (IRSA) on EKS uses an OIDC-based trust relationship. The IAM role `s3-exporter-role` has a trust policy scoped to `system:serviceaccount:staging:s3-exporter`, but the pod is running in the `production` namespace. The OIDC token presented by the pod (`system:serviceaccount:production:s3-exporter`) does not match the trust policy condition, so AWS STS rejects the token and returns `InvalidClientTokenId`. This is a namespace mismatch in the IAM trust policy — not an AWS permissions issue.
>
> **KB pattern matched:** eks-002 (EKS IAM IRSA — pod identity misconfigured)
> **Confidence:** 0.91
> **Cloud provider boost:** +0.15 (EKS detected from node labels)

### Remediation plan (L3 — suggest only)

IAM policy changes are always suggest-only as they require AWS console or CLI access.

```bash
# Step 1: Confirm the namespace mismatch in the trust policy
aws iam get-role --role-name s3-exporter-role \
  --query 'Role.AssumeRolePolicyDocument' | jq .

# Step 2: Update the trust policy to include the production namespace
# Edit the trust policy to change:
#   "system:serviceaccount:staging:s3-exporter"
# to:
#   "system:serviceaccount:production:s3-exporter"

aws iam update-assume-role-policy \
  --role-name s3-exporter-role \
  --policy-document file://trust-policy-updated.json

# Step 3: Restart the pod to acquire a fresh OIDC token
kubectl rollout restart deployment/s3-exporter -n production

# Step 4: Verify token injection and AWS call
kubectl exec s3-exporter-<new-pod> -n production -- \
  aws sts get-caller-identity
```

### Expected outcome

After the trust policy update and pod restart, the pod receives a valid OIDC token scoped to the correct namespace, AWS STS returns a valid session, and S3 writes succeed.

### Why IRSA fails silently

IRSA failures often look like generic auth errors (`InvalidClientTokenId`, `ExpiredTokenException`) because AWS does not distinguish between "wrong namespace in trust policy" and "wrong credentials." The system detects this pattern by cross-referencing: (1) the pod's ServiceAccount annotation for an IRSA ARN, (2) AWS credential errors in logs, and (3) the EKS cloud provider context.

---

## Running These Examples Locally

All examples have corresponding JSON fixtures in `examples/`:

```bash
# Load a specific example incident into the demo system
DEMO_MODE=1 make run-api

# In another terminal — inject the example
curl -X POST http://localhost:8000/api/v1/incidents \
  -H "Content-Type: application/json" \
  -d @examples/crashloop_missing_secret.json

# Run analysis
INCIDENT_ID=$(curl -s http://localhost:8000/api/v1/incidents | jq -r '.[0].id')
curl -X POST http://localhost:8000/api/v1/incidents/$INCIDENT_ID/analyze | jq .

# Get remediation plan
curl http://localhost:8000/api/v1/incidents/$INCIDENT_ID/remediation | jq .
```

Available example fixtures:

| File | Scenario |
|---|---|
| `examples/crashloop_missing_secret.json` | Example 1 — CrashLoop, missing Secret |
| `examples/ingress_service_mismatch.json` | Example 4 — Ingress 502, no endpoints |
| `examples/oomkilled_app.json` | Example 5 — OOMKill, limit too low |
| `examples/pending_due_to_capacity.json` | Example 3 — Pending pods, node exhaustion |
| `examples/pvc_mount_failure.json` | PVC FailedMount scenario |
