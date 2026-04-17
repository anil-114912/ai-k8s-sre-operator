# AI K8s SRE Operator

> **AI-powered Kubernetes SRE and Application Performance Monitoring platform.**
> Detects infrastructure failures, monitors application health, explains root cause, suggests remediation, and learns from every incident — all in one self-hostable tool.

[![Python](https://img.shields.io/badge/Python-3.9+-blue?logo=python&logoColor=white)](https://python.org)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.111-009688?logo=fastapi&logoColor=white)](https://fastapi.tiangolo.com)
[![Kubernetes](https://img.shields.io/badge/Kubernetes-1.28+-326CE5?logo=kubernetes&logoColor=white)](https://kubernetes.io)
[![Tests](https://img.shields.io/badge/Tests-202%20passing-brightgreen?logo=pytest&logoColor=white)](#testing)
[![Detectors](https://img.shields.io/badge/Detectors-18-orange)](#infrastructure-monitoring)
[![KB Patterns](https://img.shields.io/badge/Knowledge%20Base-54%20patterns-06b6d4)](#knowledge-base)
[![License](https://img.shields.io/badge/License-MIT-yellow)](LICENSE)
[![EKS](https://img.shields.io/badge/EKS-supported-FF9900?logo=amazon-aws&logoColor=white)](docs/platforms.md)
[![AKS](https://img.shields.io/badge/AKS-supported-0078D4?logo=microsoft-azure&logoColor=white)](docs/platforms.md)
[![GKE](https://img.shields.io/badge/GKE-supported-4285F4?logo=google-cloud&logoColor=white)](docs/platforms.md)

---

## Overview

This tool addresses a gap that every SRE team eventually encounters: your cluster monitoring tells you *that* something broke, but not *why* it broke or *how* to safely fix it.

**AI K8s SRE Operator** combines infrastructure-level SRE automation with application-level performance monitoring into a single platform. It watches your cluster continuously, detects known failure patterns, explains root cause using an AI reasoning engine backed by a curated knowledge base, and proposes — or executes — safe remediations.

| Capability | What it does |
|---|---|
| **Infrastructure SRE** | 18 deterministic detectors catch CrashLoops, OOMKills, PVC failures, DNS issues, RBAC errors, service misconfigurations, node pressure, and more |
| **Application APM** | A lightweight sidecar agent tails pod logs and reports error rates, latency, and exception patterns — no SDK or code changes required |
| **AI Root Cause Analysis** | LLM (Claude/GPT) + RAG over 54 knowledge base patterns + incident history explains the actual root cause, not just symptoms |
| **Safe Automated Remediation** | 3-tier safety system (auto-fix / approval-required / suggest-only) with dry-run mode, namespace guardrails, and per-workload cooldowns |
| **Self-Learning** | The system learns from operator feedback, adjusts confidence scores, and promotes successful patterns to the knowledge base |

Runs fully **offline in demo mode** — no API key, no cluster required. Ready to deploy on **EKS, AKS, GKE, or self-hosted** clusters via Helm.

---

## Screenshots

| Dashboard | Incident Analysis | APM Overview |
|---|---|---|
| ![Dashboard](Screenshots/dashboard-overview.png) | ![RCA](Screenshots/incident-rca.png) | ![APM](Screenshots/apm-overview.png) |

| Remediation Plan | Knowledge Base | Learning Stats |
|---|---|---|
| ![Remediation](Screenshots/remediation-plan.png) | ![KB](Screenshots/knowledge-base.png) | ![Learning](Screenshots/learning-stats.png) |

> Run `make run-ui && make simulate` to generate live demo data, then capture screenshots. See [Screenshots/README.md](Screenshots/README.md) for the capture guide.

---

## Quick Start

```bash
git clone https://github.com/anil-114912/ai-k8s-sre-operator
cd ai-k8s-sre-operator
pip install -r requirements.txt
cp .env.example .env
```

### Demo mode — no cluster, no API key required

```bash
DEMO_MODE=1 make run-api    # Terminal 1 — API on http://localhost:8000
make run-ui                  # Terminal 2 — Dashboard on http://localhost:8501
make simulate                # Terminal 3 — Inject demo incidents
```

Open http://localhost:8501 — you will see a live dashboard with simulated incidents, RCA analysis, and remediation plans.

### Real cluster — reads from your current kubectl context

```bash
make run-api    # Uses ~/.kube/config automatically
make run-ui
```

### Real cluster + AI analysis

```bash
# Edit .env: set ANTHROPIC_API_KEY=sk-ant-... or OPENAI_API_KEY=sk-...
make run-api
make run-ui
```

### In-cluster via Helm

```bash
helm install ai-sre-operator ./helm/ai-k8s-sre-operator \
  --namespace ai-sre --create-namespace \
  --set cluster.provider=aws \
  --set llm.apiKey=$ANTHROPIC_API_KEY \
  --set persistence.storageClass=gp3
```

---

## Why This Project Exists

Most Kubernetes monitoring tools answer one question: "Is something broken right now?" They alert on symptoms — a pod is crashing, a container is OOMKilled, a node is under pressure.

What they don't tell you:

- **Why** is the pod crashing? Is it a missing secret? A bad health check config? A nil pointer after a recent deploy?
- **What changed** right before the failure?
- **What exactly should you do** to fix it, in order, without making things worse?
- **Has this happened before** in this namespace or a similar service?

This project was built to answer those questions. Not with dashboards and alerts — but with an AI reasoning layer that has read every Kubernetes post-mortem, knows the patterns, and can explain in plain language what happened and what to do.

The secondary motivation was observability coverage below the Kubernetes layer. Most SRE tools are blind to what is happening *inside* the application container. The sidecar agent closes that gap without requiring any changes to your application code.

---

## What Makes It Different

Unlike commercial APM tools (AppDynamics, Datadog, New Relic), this system:

1. **Explains reasoning** — not just "anomaly detected" but "the database connection pool is exhausted because you have 3 slow queries holding connections indefinitely — here is the query to find them"
2. **Is cloud-aware** — EKS, AKS, and GKE each have different failure modes (IRSA, Workload Identity, Fargate profiles, Binary Authorization). The knowledge base has provider-specific patterns that are automatically prioritized based on your cluster
3. **Learns from feedback** — every time an operator says "that RCA was correct" or "that fix worked," the system adjusts its confidence scoring. Patterns that are consistently wrong get demoted; patterns that consistently lead to successful fixes get promoted
4. **Is transparent** — all knowledge base patterns are human-readable YAML files you can read, modify, and extend. No black box
5. **Is safe by design** — dry-run mode is the default. Auto-fix is opt-in. Critical namespace (kube-system) actions are blocked entirely
6. **Has no vendor lock-in** — works with Anthropic, OpenAI, or a completely offline rule-based fallback

| Feature | This Tool | AppDynamics | Datadog | PagerDuty |
|---|---|---|---|---|
| Kubernetes SRE automation | ✅ 18 detectors | ⚠️ basic | ⚠️ basic | ❌ |
| Application performance monitoring | ✅ sidecar | ✅ agent | ✅ agent | ❌ |
| AI root cause analysis | ✅ LLM + RAG | ✅ ML | ✅ ML | ⚠️ basic |
| Automated remediation | ✅ 3-tier safe | ❌ | ⚠️ limited | ❌ |
| Self-learning from feedback | ✅ | ❌ | ❌ | ❌ |
| Cloud-specific failure KB | ✅ EKS/AKS/GKE | ❌ | ⚠️ | ❌ |
| Custom failure patterns (no code) | ✅ YAML | ❌ | ❌ | ❌ |
| Zero-code APM instrumentation | ✅ sidecar | ❌ SDK required | ❌ SDK required | ❌ |
| Runs fully offline | ✅ demo mode | ❌ | ❌ | ❌ |
| Open source | ✅ MIT | ❌ | ❌ | ❌ |

---

## How It Works

### Infrastructure SRE — Step by Step

```
1. Cluster Watch Loop (every 30s)
   │  Polls K8s API for pods, events, services, nodes, HPAs, PVCs, ingresses
   │
2. Deterministic Detection (18 detectors)
   │  Each detector returns: type, resource name, namespace, evidence, severity
   │  Example: CrashLoopDetector finds pod with restart_count > 5 and reason="Error"
   │
3. Signal Correlation
   │  Classifies signals: root_cause vs symptom vs contributing_factor
   │  Builds a timeline and causal graph across related resources
   │
4. Knowledge Base Search
   │  Scores 54 patterns by keyword overlap, log match, and cloud provider
   │  Returns top-N candidates with confidence scores
   │
5. Incident Memory Retrieval
   │  Finds semantically similar past incidents using TF-IDF + embeddings
   │  Past feedback boosts patterns that previously led to successful fixes
   │
6. AI Reasoning (Layer 6)
   │  Sends: detector results + KB matches + similar incidents + cluster context
   │  Receives: structured root cause, confidence, recommended remediation steps
   │  Falls back to rule-based reasoning if no LLM key is configured
   │
7. Remediation Controller
   │  Classifies each step: L1 auto-fix, L2 approval-required, L3 suggest-only
   │  Checks namespace policy, cooldown, and dry-run flag
   └─ Executes or presents the plan via API / UI / CLI
```

### Application APM — Step by Step

```
1. Sidecar Agent starts in your pod (alongside your application container)
   │  Tails shared log volume or stdout via /proc/PID/fd/1
   │
2. Error Detector scans each log line against 20+ built-in patterns
   │  Matches: Python tracebacks, Java exceptions, Go panics, HTTP 5xx, slow queries
   │
3. Metrics Reporter aggregates every 30 seconds
   │  Computes: error_rate, latency P50/P95/P99, throughput, pattern counts
   │  Sends HTTP POST to /api/v1/apm/ingest
   │
4. Pattern Learner captures unmatched error lines
   │  Normalises (strips timestamps, UUIDs, numbers)
   │  Sends novel patterns to /api/v1/apm/learn for KB promotion
   │
5. APM Aggregator in the Operator API
   │  Builds per-service health score (0–100)
   │  Correlates application errors with infrastructure events
   └─ Auto-creates incidents for critical/high severity patterns
```

---

## Architecture

```
┌─────────────────────────────────────────────────────────────────────────────────┐
│                              Kubernetes Cluster                                  │
│                                                                                  │
│  ┌────────────────────────────────────────────────────────────────────────────┐  │
│  │  APPLICATION PODS                                                           │  │
│  │                                                                             │  │
│  │   ┌──────────────────┐    ┌────────────────────────────────────────────┐   │  │
│  │   │   Your App       │    │   AI SRE Sidecar Agent (optional)          │   │  │
│  │   │   Container      │───▶│   • Tails log file via shared volume       │   │  │
│  │   │   (any language) │    │   • 20+ error/exception pattern matchers   │   │  │
│  │   │                  │    │   • Reports latency P50/P95/P99, error     │   │  │
│  │   │                  │    │     rate, throughput every 30s             │   │  │
│  │   └──────────────────┘    │   • Learns app-specific patterns over time │   │  │
│  │                           └────────────────┬───────────────────────────┘   │  │
│  └────────────────────────────────────────────┼───────────────────────────────┘  │
│                                               │ HTTP POST                         │
│  ┌────────────────────────────────────────────▼───────────────────────────────┐  │
│  │  OPERATOR CORE                                                              │  │
│  │                                                                             │  │
│  │  ┌──────────────────┐    ┌────────────────────────────────────────────┐   │  │
│  │  │  K8s Watch Loop  │───▶│  Infrastructure Detectors (18)             │   │  │
│  │  │  (every 30s)     │    │  CrashLoop · OOM · ImagePull · Pending     │   │  │
│  │  └──────────────────┘    │  Probe · Service · Ingress · PVC · HPA    │   │  │
│  │                          │  DNS · RBAC · NetPolicy · CNI · Mesh       │   │  │
│  │  ┌──────────────────┐    │  NodePressure · Quota · Rollout · Storage  │   │  │
│  │  │  APM Ingest      │───▶└──────────────────┬─────────────────────────┘   │  │
│  │  │  (from agent)    │                       │                              │  │
│  │  └──────────────────┘                       ▼                              │  │
│  │                          ┌────────────────────────────────────────────┐   │  │
│  │  ┌──────────────────┐    │  Signal Correlator                          │   │  │
│  │  │  Collectors      │───▶│  root_cause · symptom · contributing       │   │  │
│  │  │  Logs / Events   │    │  Timeline Builder · Causal Graph           │   │  │
│  │  │  Metrics / APM   │    └──────────────────┬─────────────────────────┘   │  │
│  │  └──────────────────┘                       │                              │  │
│  │                                             ▼                              │  │
│  │  ┌──────────────────┐    ┌────────────────────────────────────────────┐   │  │
│  │  │  Knowledge Base  │───▶│  AI RCA Engine                              │   │  │
│  │  │  54 patterns     │    │  KB matches + similar incidents + context   │   │  │
│  │  │  Incident Memory │    │  Anthropic / OpenAI / offline rule-based   │   │  │
│  │  │  Feedback Store  │    └──────────────────┬─────────────────────────┘   │  │
│  │  └──────────────────┘                       │                              │  │
│  │                                             ▼                              │  │
│  │                          ┌────────────────────────────────────────────┐   │  │
│  │                          │  Remediation Controller                     │   │  │
│  │                          │  L1: auto-fix  L2: approval  L3: suggest   │   │  │
│  │                          │  Namespace policy · Cooldown · Dry-run     │   │  │
│  │                          └──────────────────┬─────────────────────────┘   │  │
│  │                                             │                              │  │
│  │                          ┌──────────────────▼─────────────────────────┐   │  │
│  │                          │  Learning Store                              │   │  │
│  │                          │  Capture → Cluster → Promote → Refit       │   │  │
│  │                          │  Feedback boost · Confidence adjustment     │   │  │
│  │                          └────────────────────────────────────────────┘   │  │
│  └────────────────────────────────────────────────────────────────────────────┘  │
└─────────────────────────────────────────────────────────────────────────────────┘
               ▲                          ▲                       ▲
          FastAPI REST              Streamlit UI             Click CLI
          (port 8000)               (port 8501)           (ai-sre ...)
         /docs for Swagger
```

See [docs/architecture.md](docs/architecture.md) for the full layer-by-layer breakdown and project structure.

---

## Features

### Infrastructure Monitoring

| Component | Details |
|---|---|
| **18 failure detectors** | CrashLoopBackOff, OOMKill, ImagePull, PendingPod, ProbeFailure, ServiceMismatch, IngressBackend, PVC, HPA, DNS, RBAC, NetworkPolicy, CNI, ServiceMesh, NodePressure, Quota, Rollout, Storage |
| **54 KB patterns** | Generic K8s (12), EKS (6), AKS (5), GKE (5), Networking (8), Storage (6), Security (5), Cluster (4), Application (3) |
| **Cloud provider awareness** | Auto-detects EKS/AKS/GKE from node `spec.providerID` and node labels; boosts relevant cloud-specific patterns |
| **Signal correlation** | Classifies every signal as root_cause, symptom, or contributing_factor; builds causal graph |
| **Multi-cloud patterns** | EKS: Fargate, IRSA, ENI, add-ons · AKS: VMSS, Workload Identity, Managed Identity · GKE: NAP, Binary Auth, Workload Identity |

### Application Performance Monitoring

| Component | Details |
|---|---|
| **Sidecar agent** | Lightweight Python agent (< 64Mi) — zero code changes, zero SDK, any language |
| **Log intelligence** | Tails stdout/stderr, detects Python/Java/Go/Node.js exceptions, HTTP 5xx, slow queries, connection failures |
| **Metrics** | Error rate, request throughput, latency P50/P95/P99 per service |
| **Service health score** | 0–100 score combining error rate, P99 latency, and crash frequency |
| **Error trend tracking** | Pattern frequency over time; spike detection |
| **APM + SRE correlation** | Links app-level errors to K8s events (e.g., DB pool exhaustion ↔ network policy change) |

### AI and Learning

| Component | Details |
|---|---|
| **LLM providers** | Anthropic Claude 3, OpenAI GPT-4o, or offline rule-based fallback |
| **RAG-powered RCA** | KB patterns + past incidents as LLM context; structured output with confidence score |
| **Feedback loop** | Operator feedback adjusts per-pattern confidence; successful patterns are promoted |
| **Novel pattern learning** | Sidecar captures unmatched error signatures; feeds into KB promotion pipeline |
| **Embeddings** | TF-IDF + sentence-transformers (all-MiniLM-L6-v2) for semantic incident similarity |

### Remediation and Safety

| Component | Details |
|---|---|
| **3-tier safety model** | L1 auto-fix (safe, reversible) · L2 approval-required (destructive) · L3 suggest-only (manual) |
| **6 remediations** | Pod restart, rollout restart, scale up/down, rollback, resource patch, job rerun |
| **Dry-run default** | All actions simulate by default; real execution requires explicit `dry_run=false` |
| **Namespace guardrails** | kube-system and kube-public blocked; configurable deny and allow lists |
| **Cooldown tracking** | 300-second default between remediations of the same workload |
| **Audit logging** | All remediation decisions are logged with reasoning and safety level |

---

## Example Incidents

### CrashLoopBackOff — Missing Secret

**Symptoms observed:**

```
payment-api-7d9f8b-xk2p9   0/1   CrashLoopBackOff   18   23m
```

**K8s events:**

```
Warning  BackOff  18x  kubelet  Back-off restarting failed container
Warning  Failed    1x  kubelet  Error: secret "db-credentials" not found
```

**Container logs:**

```
2024-01-15T09:23:36Z ERROR Failed to load config: secret 'db-credentials' not found
2024-01-15T09:23:36Z ERROR Database connection pool initialization failed: host=<nil>
2024-01-15T09:23:37Z FATAL Application startup failed — cannot continue without database configuration
```

**AI root cause:**

> The `payment-api` deployment references a Kubernetes Secret named `db-credentials` that does not exist in the `production` namespace. This was introduced 4 minutes ago when the deployment was updated to add `envFrom.secretRef.name: db-credentials`. The pod crashes immediately on startup because it cannot initialise the database connection pool without this configuration. **Confidence: 0.97** (KB pattern k8s-001, matched by 3 evidence signals)

**Remediation plan (L3 — suggest only):**

```bash
# 1. Confirm the secret is missing
kubectl get secret db-credentials -n production

# 2. Create the secret with the required keys
kubectl create secret generic db-credentials \
  --from-literal=DB_HOST=postgres.production.svc \
  --from-literal=DB_PORT=5432 \
  --from-literal=DB_NAME=payments \
  --from-literal=DB_PASSWORD=<password> \
  -n production

# 3. Verify the pod recovers
kubectl rollout status deployment/payment-api -n production
```

**Expected outcome:** Pod restarts and enters Running state within 60 seconds of secret creation.

---

### OOMKilled Container — Memory Limit Too Low

**Symptoms observed:**

```
order-processor-6f8d9c-m4n7p   0/1   OOMKilled   3   12m
```

**K8s events:**

```
Warning  OOMKilling   node/ip-10-0-1-45   Memory limit exceeded; killing container order-processor
```

**AI root cause:**

> The `order-processor` container has a memory limit of `256Mi` but is consuming up to `410Mi` under current load. The spike correlates with a 3x increase in order volume detected by the HPA at 14:32. The container is not leaking memory — it is legitimately under-resourced for peak load. **Confidence: 0.89** (KB pattern k8s-003, OOMKill detector + HPA saturation signal correlated)

**Remediation plan (L2 — approval required):**

```bash
# 1. Check current memory usage trend
kubectl top pod -l app=order-processor -n production

# 2. Patch memory limit (requires approval)
kubectl set resources deployment/order-processor \
  --limits=memory=768Mi --requests=memory=384Mi \
  -n production

# 3. Monitor for stability
kubectl rollout status deployment/order-processor -n production
```

See [docs/examples.md](docs/examples.md) for 6 complete incident walkthroughs including:
- Service selector mismatch causing 502s
- Pending pods due to node resource exhaustion
- Ingress backend unavailable (no endpoints)
- EKS IRSA misconfiguration blocking AWS API calls

---

## Safety Model

The system has three safety tiers that determine how any remediation action is handled:

| Level | Name | Trigger | Examples |
|---|---|---|---|
| **L1** | auto-fix | Executes automatically (if `AUTO_FIX_ENABLED=true`) | Restart crashed pod, rerun failed job, collect diagnostics |
| **L2** | approval-required | Generates plan, waits for human approval | Scale down, rollback deployment, patch resource limits |
| **L3** | suggest-only | Never executes — displays command for human to run | Create secret, RBAC changes, network policy, drain node |

**Multiple guardrails enforce these levels before any action runs:**

1. Namespace check — kube-system and kube-public are unconditionally blocked
2. Action allowlist — only explicitly permitted actions can execute
3. Safety level check — L3 actions are blocked regardless of other flags
4. Cooldown check — same workload cannot be remediated within 5 minutes
5. Dry-run flag — if `OPERATOR_DRY_RUN=true` (default), all actions simulate

**The overall safety level of a plan is the most restrictive level across all steps.** A plan containing one L3 step is classified as L3 entirely.

By default: `OPERATOR_DRY_RUN=true`, `AUTO_FIX_ENABLED=false`. Both must be explicitly set to enable live execution.

See [docs/safety.md](docs/safety.md) for the full action mapping, namespace policy configuration, and audit logging.

---

## Knowledge Base

54 failure patterns across 9 categories, all in human-readable YAML. Add custom patterns without touching Python.

| Category | Patterns | Example Failures |
|---|---|---|
| Generic K8s | 12 | CrashLoop (6 root causes), OOMKill, ImagePull, PVC mount, DNS |
| EKS (AWS) | 6 | ENI exhaustion, IRSA missing, node group capacity, Fargate profile, API throttling |
| AKS (Azure) | 5 | VM quota exceeded, Managed Identity missing, disk attach failure, VMSS degraded, WI webhook |
| GKE (Google) | 5 | Workload Identity, Autopilot quota, Filestore mount, NAP provisioning, Binary Authorization |
| Networking | 8 | CoreDNS NXDOMAIN, NetworkPolicy blocking, CNI IP exhaustion, Istio mTLS mismatch |
| Storage | 6 | PVC not binding, CSI driver missing, StorageClass deleted, ReadWriteOnce conflict |
| Security | 5 | RBAC forbidden, ServiceAccount missing, Pod Security Admission, seccomp, image signing |
| Cluster | 4 | ResourceQuota exceeded, LimitRange violation, Node NotReady, etcd latency |
| Application | 3 | DB connection pool exhausted, HTTP 5xx spike, memory leak / OOM |

Each pattern includes: symptoms, event patterns, log patterns, metric patterns, root cause explanation, step-by-step remediation, confidence boosts, and safety level.

**Sample pattern:**

```yaml
- id: k8s-001
  title: "CrashLoopBackOff — missing Secret"
  scope: pod
  symptoms:
    - "Container exits immediately on startup"
    - "Event: Error: secret \"<name>\" not found"
  log_patterns:
    - "secret .* not found"
    - "environment variable .* not set"
    - "config.*missing.*required"
  root_cause: "The pod references a Secret that does not exist in its namespace.
    This is usually caused by deploying an application before creating the Secret
    it depends on, or by referencing a Secret from the wrong namespace."
  remediation_steps:
    - "Confirm: kubectl get secret <name> -n <namespace>"
    - "Create: kubectl create secret generic <name> --from-literal=KEY=value -n <namespace>"
    - "Verify: kubectl rollout status deployment/<name> -n <namespace>"
  safe_auto_fix: false
  safety_level: suggest_only
  tags: [crashloop, secret, startup, configuration]
```

All patterns live in [knowledge/failures/](knowledge/failures/). See [docs/knowledge-base.md](docs/knowledge-base.md) for the full schema and search API.

---

## APM Sidecar Agent

Add the sidecar to any pod — no code changes to your application:

```yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: my-app
spec:
  template:
    spec:
      containers:
        - name: my-app
          image: my-app:latest
          volumeMounts:
            - name: app-logs
              mountPath: /var/log/app

        # Add this sidecar:
        - name: ai-sre-agent
          image: ghcr.io/anil-114912/ai-k8s-sre-agent:0.2.0
          env:
            - name: OPERATOR_API_URL
              value: http://ai-sre-operator.ai-sre.svc:8000
            - name: SERVICE_NAME
              value: my-app
            - name: LOG_PATH
              value: /var/log/app/app.log
            - name: POD_NAME
              valueFrom: { fieldRef: { fieldPath: metadata.name } }
            - name: POD_NAMESPACE
              valueFrom: { fieldRef: { fieldPath: metadata.namespace } }
          resources:
            requests: { cpu: 10m, memory: 32Mi }
            limits: { cpu: 50m, memory: 64Mi }
          volumeMounts:
            - name: app-logs
              mountPath: /var/log/app
              readOnly: true

      volumes:
        - name: app-logs
          emptyDir: {}
```

The agent automatically detects:

- Python exceptions and tracebacks
- Java stack traces (Spring, Hibernate, JPA)
- Go panics and fatal errors
- Node.js/Express unhandled errors
- HTTP 4xx/5xx error patterns
- Slow database queries (configurable threshold, default 1s)
- Connection pool exhaustion
- Memory pressure signatures

See [docs/sidecar-agent.md](docs/sidecar-agent.md) for configuration reference, custom patterns, and resource tuning.

---

## API Usage

Full Swagger docs at `http://localhost:8000/docs`. Key endpoints:

### Trigger a cluster scan

```bash
curl -X POST http://localhost:8000/api/v1/scan | jq .
```

```json
{
  "incidents_detected": 2,
  "duration_ms": 847,
  "incidents": [
    {
      "id": "inc-a3f9b1",
      "title": "CrashLoopBackOff: payment-api (missing secret)",
      "severity": "critical",
      "namespace": "production",
      "workload": "payment-api"
    }
  ]
}
```

### Analyze an incident

```bash
curl -X POST http://localhost:8000/api/v1/incidents/inc-a3f9b1/analyze | jq .
```

```json
{
  "root_cause": "The payment-api pod cannot start because it references Secret 'db-credentials' which does not exist in namespace 'production'. The deployment was updated 4 minutes ago to reference this secret.",
  "confidence": 0.97,
  "kb_patterns_matched": ["k8s-001"],
  "similar_incidents": 2,
  "remediation_hint": "Create the missing secret: kubectl create secret generic db-credentials -n production"
}
```

### Get remediation plan

```bash
curl http://localhost:8000/api/v1/incidents/inc-a3f9b1/remediation | jq .
```

```json
{
  "plan_id": "plan-7c2d4e",
  "safety_level": "suggest_only",
  "requires_approval": false,
  "steps": [
    { "order": 1, "action": "verify_secret_missing", "command": "kubectl get secret db-credentials -n production" },
    { "order": 2, "action": "recreate_secret",       "command": "kubectl create secret generic db-credentials --from-literal=KEY=value -n production", "safety_level": "suggest_only" },
    { "order": 3, "action": "verify_recovery",       "command": "kubectl rollout status deployment/payment-api -n production" }
  ]
}
```

### Search the knowledge base

```bash
curl "http://localhost:8000/api/v1/knowledge/search?q=connection+pool+exhausted&provider=aws&top_k=3"
```

See [docs/api.md](docs/api.md) for complete request/response examples for all 29 endpoints.

---

## Deployment

### Local (development)

```bash
make run-api     # FastAPI on :8000
make run-ui      # Streamlit on :8501
make simulate    # Inject demo incidents
```

### Docker Compose

```bash
docker-compose up -d
# API on :8000, UI on :8501
```

### Helm (Kubernetes)

```bash
# Install
helm install ai-sre-operator ./helm/ai-k8s-sre-operator \
  --namespace ai-sre --create-namespace \
  --values helm/values-production.yaml

# Upgrade
helm upgrade ai-sre-operator ./helm/ai-k8s-sre-operator \
  --namespace ai-sre \
  --values helm/values-production.yaml

# Uninstall
helm uninstall ai-sre-operator --namespace ai-sre

# Access API
kubectl port-forward svc/ai-sre-operator 8000:8000 -n ai-sre

# Verify deployment
kubectl get pods -n ai-sre
kubectl logs -n ai-sre -l app=ai-sre-operator --tail=50
```

Pre-built values files:
- [helm/values-demo.yaml](helm/values-demo.yaml) — no cluster required, demo mode
- [helm/values-production.yaml](helm/values-production.yaml) — production hardened config

RBAC permissions used:

| Resource | Verbs | Purpose |
|---|---|---|
| pods, pods/log | get, list, watch | Detect failures, collect evidence |
| events | get, list, watch | CrashLoop, OOMKill, scheduling evidence |
| deployments, replicasets | get, list, watch, patch | Detect rollout failures, execute rollout restart |
| services, endpoints | get, list, watch, patch | Detect service misconfigurations |
| nodes | get, list, watch | Node pressure detection |
| persistentvolumeclaims | get, list, watch | PVC failure detection |
| namespaces, resourcequotas | get, list, watch | Quota enforcement |
| ingresses | get, list, watch | Ingress backend detection |

The operator **never** modifies kube-system or kube-public resources regardless of configuration.

See [docs/deployment.md](docs/deployment.md) for full production hardening, RBAC configuration, and observability integration.

---

## Roadmap

### Phase 1 — SRE Foundation (complete)

Infrastructure monitoring, AI RCA, safe remediation, multi-cloud KB, feedback learning, CI/CD, Helm.

### Phase 2 — Application Performance Monitoring (in progress)

Sidecar agent, APM ingest API, application log intelligence, service health scores, APM + SRE correlation.

### Phase 3 — Advanced AI (planned)

Time-series anomaly detection, proactive failure prediction, natural language incident queries, automated post-mortem generation, fine-tuned models on incident history.

### Phase 4 — Enterprise (planned)

Multi-cluster federation, RBAC for the operator, SSO/OIDC, Slack/PagerDuty/Jira integrations, SLO tracking, PostgreSQL backend.

See [docs/roadmap.md](docs/roadmap.md) for the detailed backlog with implementation status.

---

## Evaluation

**How the system measures its own accuracy:**

| Metric | Measurement | Current Baseline |
|---|---|---|
| KB pattern match rate | % of incidents matched to at least one KB pattern | ~85% on known failure types |
| RCA confidence calibration | Mean confidence when operator marks RCA as "correct" vs "incorrect" | Correct: 0.83 avg · Incorrect: 0.51 avg |
| Fix success rate | % of executed remediations where operator confirmed fix worked | Tracked per pattern |
| Novel error capture rate | % of unmatched errors captured and submitted to learning store | ~40% of unmatched lines |

**How feedback improves the system over time:**

1. Operator marks an incident: "RCA correct" / "fix worked" / "better remediation was: ..."
2. The matched KB pattern's confidence is boosted (+0.1) or reduced (-0.15)
3. After N successful fixes, a pattern is promoted to higher confidence tier
4. Novel patterns that appear repeatedly get proposed for KB inclusion
5. The embedding model is refit periodically to include new incident data

See [docs/evaluation.md](docs/evaluation.md) for the full evaluation methodology.

---

## Testing

```bash
# Run all tests
make test

# With coverage report
DEMO_MODE=1 python3 -m pytest tests/ -v --cov=. --cov-report=html

# Integration test (requires Kind)
kind create cluster --name sre-test
python3 -m pytest tests/integration/ -v
```

202 passing tests covering detectors, knowledge base, AI engine, API endpoints, correlation, policies, remediations, and the feedback loop.

---

## Documentation

| Document | Description |
|---|---|
| [Architecture](docs/architecture.md) | System design, 7-layer pipeline, full project structure |
| [Example Incidents](docs/examples.md) | 6 complete end-to-end incident walkthroughs |
| [Application Monitoring](docs/application-monitoring.md) | APM guide — service health, error tracking, sidecar setup |
| [Sidecar Agent](docs/sidecar-agent.md) | Agent installation, configuration, custom patterns |
| [Detectors](docs/detectors.md) | All 18 infrastructure detectors |
| [Knowledge Base](docs/knowledge-base.md) | 54 failure patterns, YAML format, search engine |
| [Learning and Feedback](docs/learning.md) | Feedback loop, error capture, pattern promotion |
| [Safety Model](docs/safety.md) | 3-tier safety levels, guardrails, namespace policies, audit log |
| [Evaluation](docs/evaluation.md) | Accuracy metrics, confidence calibration, feedback model |
| [API Reference](docs/api.md) | All 29 REST endpoints with request/response examples |
| [CLI Reference](docs/cli.md) | CLI commands |
| [Dashboard](docs/dashboard.md) | 8 UI tabs |
| [Configuration](docs/configuration.md) | Environment variables, Helm values, agent config |
| [Deployment](docs/deployment.md) | Docker, Helm, production hardening, RBAC |
| [Testing](docs/testing.md) | 202 tests, coverage, integration tests |
| [Supported Platforms](docs/platforms.md) | EKS, AKS, GKE, Cilium, Istio, CSI drivers |
| [Roadmap](docs/roadmap.md) | Feature backlog across 4 phases |

---

## Contributing

1. Fork and create a feature branch
2. Add tests for any new detector or KB pattern
3. Run `make lint && make test` before pushing
4. Submit a PR — describe the failure scenario your change handles

**To add a custom failure pattern:** create a YAML file in `knowledge/failures/` — no Python required. See [docs/knowledge-base.md](docs/knowledge-base.md) for the pattern schema.

**To add a new detector:** implement the `BaseDetector` interface in `detectors/`, add tests in `tests/test_detectors.py`, and register it in `collectors/k8s_watcher.py`.

---

## License

MIT — Copyright 2025 Anil Thotakura. See [LICENSE](LICENSE).
