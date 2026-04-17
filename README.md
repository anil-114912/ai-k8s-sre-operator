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

This tool addresses a gap that every SRE team eventually hits: your cluster monitoring tells you *that* something broke, but not *why* it broke or *how* to safely fix it.

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

## Current Status

This section reflects what is actually implemented, not what is planned.

### Implemented and working

- **18 infrastructure detectors** — CrashLoopBackOff (6 root cause variants), OOMKill, ImagePull, PendingPod, ProbeFailure, Service selector mismatch, Ingress backend, PVC, HPA, DNS, RBAC, NetworkPolicy, CNI, ServiceMesh, NodePressure, ResourceQuota, Rollout, Storage
- **54 knowledge base patterns** — Generic K8s (12), EKS (6), AKS (5), GKE (5), Networking (8), Storage (6), Security (5), Cluster (4), Application (3)
- **AI RCA** — Anthropic Claude and OpenAI GPT with RAG, plus offline rule-based fallback (no API key needed)
- **3-tier remediation safety** — auto-fix / approval-required / suggest-only with dry-run mode, namespace policies, and cooldowns
- **6 remediation executors** — pod restart, rollout restart, scale, rollback, resource patch, job rerun
- **Feedback learning loop** — confidence adjustment, pattern promotion, embedding refit
- **Remediation outcome learning** — `OutcomeStore` + `RemediationRanker` track per-action success rates and re-rank suggestions
- **APM sidecar agent** — log tailing, error detection, latency tracking (p50/p95/p99), novel pattern learning
- **APM API endpoints** — `/api/v1/apm/ingest`, `/api/v1/apm/services`, `/api/v1/apm/errors`, `/api/v1/apm/learn`
- **Proactive anomaly detection** — `anomaly/metrics_analyzer.py` detects CPU spikes, memory growth, error rate spikes, latency spikes, restart rate anomalies before incidents fire
- **External integrations** — Slack (Incoming Webhooks), PagerDuty (Events API v2), Jira (REST API v3) — enable via env vars
- **Audit logging** — `audit/logger.py` writes every remediation approval, block, and auto-execution to a JSON-L audit trail
- **Multi-cluster registry** — `multi_cluster/registry.py` tracks fleet of clusters with health scores, heartbeats, and aggregation
- **Sidecar auto-injection webhook** — `webhook/injection.py` FastAPI server for MutatingWebhookConfiguration; Helm template included
- **Operator control loop** — `sre_loop/` package: continuous observe-detect-analyze-remediate with configurable interval
- **Incident fingerprinting** — stable MD5 hash for deduplication; Jaccard similarity for near-duplicate grouping
- **Plan-level guardrails** — `policies/guardrails.py`: protected namespaces, denied actions, risk-score threshold
- **Confidence breakdown** — 4-dimension confidence: detector, KB match, similar incident, log evidence
- **Cluster health score** — 0-100 with A-F grade; severity, recurrence, and velocity deductions
- **Playbook system** — YAML-based structured playbooks for CrashLoop, OOM, Ingress with variable substitution
- **Simulation engine** — 4 named scenarios (crashloop, oom, ingress-failure, pending-pods) that run real detectors
- **FastAPI REST** — 60+ endpoints with Swagger docs at `/docs`
- **Streamlit dashboard** — 10 tabs: incidents, RCA, remediation, APM (with latency/error charts + anomaly alerts), history, cluster scan, knowledge base, learning & feedback, learning insights, multi-cluster
- **Click CLI** — `ai-sre cluster scan`, `incidents list`, `incident analyze`, `remediation plan/execute`, `simulate`, `knowledge search`
- **SQLite persistence** — incidents, feedback, learned patterns (PostgreSQL ready via `DATABASE_URL`)
- **Helm chart** — EKS, AKS, GKE, and local; pre-built demo and production values; webhook template; integrations config
- **Auto cloud-provider detection** — from node `spec.providerID` and labels at startup
- **202 passing tests** — unit tests, API tests, integration tests with Kind
- **GitHub Actions CI** — lint, test, smoke, helm-lint, Kind integration
- **Deployment verification** — `scripts/verify_deployment.sh` post-install health check

### Planned (not yet implemented)

- Multi-cluster incident correlation across cluster boundaries
- Proactive failure prediction ("this deployment will OOMKill in ~15 minutes")
- PostgreSQL pgvector embeddings for semantic similarity at scale
- Fine-tuned model on accumulated incident history
- SLO tracking and error budget burn rate
- APM trace-to-K8s-event correlation (currently APM and K8s events are separate)

---

## Demo

> **[▶ Watch demo on YouTube](https://github.com/anil-114912/ai-k8s-sre-operator)** *(coming soon — see recording instructions below)*

![Demo](Screenshots/demo.gif)

*Incident detected → AI root cause explained → remediation plan generated — all within seconds.*

### Run the demo locally

```bash
git clone https://github.com/anil-114912/ai-k8s-sre-operator
cd ai-k8s-sre-operator
pip install -r requirements.txt

# Terminal 1 — Start the API (demo mode, no cluster needed)
make run-api-demo

# Terminal 2 — Start the dashboard
make run-ui

# Terminal 3 — Inject a CrashLoop incident and run AI analysis
make simulate
```

Open http://localhost:8501. You will see:
1. A critical incident appearing in the **Incidents** tab
2. Click **Analyze** → AI root cause loads with confidence score
3. Click **Remediation** → step-by-step plan with safety level badges
4. Switch to **Knowledge Base** → search the pattern that matched
5. Switch to **Learning** → submit feedback to train the system

### Recording the demo

```bash
# Inject specific incident types for the recording
ai-sre simulate --type crashloop    # Missing secret scenario
ai-sre simulate --type oomkilled    # Memory limit scenario
ai-sre simulate --type pending      # Node resource exhaustion
ai-sre simulate --type ingress      # Ingress 502 scenario

# Or run fully offline (no API server required)
ai-sre simulate --type crashloop --demo
```

Recommended recording tools: **Kap** (macOS, free), **ShareX** (Windows), **Peek** (Linux). Record at 1440×900, export as GIF or MP4. Save as `Screenshots/demo.gif`.

---

## Screenshots

| Dashboard | Incident RCA | Remediation Plan |
|---|---|---|
| ![Dashboard](Screenshots/dashboard-overview.png) | ![RCA](Screenshots/incident-rca.png) | ![Remediation](Screenshots/remediation-plan.png) |

| APM Overview | Knowledge Base | Learning Stats |
|---|---|---|
| ![APM](Screenshots/apm-overview.png) | ![KB](Screenshots/knowledge-base.png) | ![Learning](Screenshots/learning-stats.png) |

---

## Quick Start

```bash
git clone https://github.com/anil-114912/ai-k8s-sre-operator
cd ai-k8s-sre-operator
pip install -r requirements.txt
cp .env.example .env
```

### Option A — Demo mode (no cluster, no API key)

```bash
DEMO_MODE=1 make run-api    # API on http://localhost:8000
make run-ui                  # Dashboard on http://localhost:8501
make simulate                # Inject demo incidents
```

### Option B — Real cluster (rule-based analysis, no LLM key needed)

```bash
make run-api    # Connects to current kubectl context automatically
make run-ui
```

### Option C — Real cluster + AI analysis

```bash
# Edit .env and set one of:
# ANTHROPIC_API_KEY=sk-ant-...
# OPENAI_API_KEY=sk-...
make run-api
make run-ui
```

### Option D — In-cluster via Helm

```bash
helm upgrade --install ai-sre-operator ./helm/ai-k8s-sre-operator \
  --namespace ai-sre --create-namespace \
  --values helm/values-production.yaml \
  --set llm.apiKey=$ANTHROPIC_API_KEY \
  --set cluster.provider=aws \
  --set persistence.storageClass=gp3
```

---

## Why This Project Exists

Most Kubernetes monitoring tools answer one question: "Is something broken right now?" They alert on symptoms — a pod is crashing, a container is OOMKilled, a node is under pressure.

What they don't tell you:

- **Why** is the pod crashing? Is it a missing secret? A bad health check? A nil pointer after a recent deploy?
- **What changed** right before the failure?
- **What exactly should you do** to fix it, in order, without making things worse?
- **Has this happened before** in this namespace or a similar service?

This project was built to answer those questions — not with dashboards and alerts, but with an AI reasoning layer that knows Kubernetes failure patterns and can explain in plain language what happened and what to do.

The secondary motivation: most SRE tools are blind to what is happening *inside* the application container. The sidecar agent closes that gap without requiring any code changes.

---

## Running Without AI (No API Key Required)

The system is fully functional without an LLM API key. Here is what changes:

| Feature | With LLM | Without LLM |
|---|---|---|
| Incident detection | ✅ same | ✅ same (detectors are deterministic) |
| KB pattern matching | ✅ same | ✅ same (rule-based scoring) |
| Root cause explanation | LLM generates natural language summary | Rule-based template from KB pattern |
| Confidence scoring | LLM-calibrated | Derived from KB match score |
| Remediation plan | LLM may refine steps | KB-provided steps verbatim |
| Novel incident handling | LLM reasons over incomplete evidence | Falls back to "low confidence — review manually" |
| Learning from feedback | ✅ same | ✅ same (confidence adjustments are independent of LLM) |

**In practice:** for the 54 known failure patterns in the knowledge base, the rule-based fallback produces useful, accurate root cause explanations. The gap shows up on novel failures where the LLM can reason over incomplete or ambiguous evidence.

```bash
# Verify which mode is active
curl http://localhost:8000/health | jq '{llm_provider, demo_mode}'
# {"llm_provider": "rule-based", "demo_mode": true}
```

---

## How Root Cause Analysis Works

RCA is not a single model call. It is a seven-step pipeline where each layer adds evidence:

```
Step 1 — Signal Collection
  K8s Watch Loop polls the API server every 30s
  Collects: pod status, events, service endpoints, node conditions, PVCs, HPAs

Step 2 — Deterministic Detection (18 detectors)
  Each detector is a focused rule:
  CrashLoopDetector: restart_count > 5 AND last_state.terminated.reason == "Error"
  OOMKillDetector:   last_state.terminated.reason == "OOMKilled"
  ServiceDetector:   len(endpoints.subsets) == 0 AND service.selector != {}
  Returns: incident_type, resource, namespace, evidence list, severity

Step 3 — Signal Correlation
  Classifies signals: root_cause vs symptom vs contributing_factor
  Builds a causal timeline (deployment change 4m ago → pod crashes 30s later)
  Example: PVC pending (root) → pod pending (symptom) → service no endpoints (effect)

Step 4 — Knowledge Base Search
  Scores all 54 patterns against the detector evidence:
    keyword overlap (events, log lines)
    log regex matching
    metric threshold matches
    cloud provider boost (+0.15 if provider matches pattern)
  Returns: top-5 candidates with match scores

Step 5 — Incident Memory
  TF-IDF + sentence-transformer similarity over all past incidents
  Feedback-boosted: incidents where the fix worked rank higher
  Returns: top-3 similar past incidents with their resolutions

Step 6 — AI Reasoning
  Input to LLM: detector results + top KB patterns + similar incidents + cluster context
  Prompt asks for structured output: root_cause, confidence, remediation_steps
  Falls back to rule-based template if no LLM key configured

Step 7 — Remediation Classification
  Each step is mapped to L1/L2/L3 based on action type
  Plan safety level = most restrictive step
  Dry-run flag and namespace guardrails applied
```

**Example evidence bundle for a real incident:**

```
Detector:    CrashLoopBackOff (restart_count=18, namespace=production, workload=payment-api)
Event:       "Error: secret \"db-credentials\" not found" (count=1, 4m ago)
Log match:   "secret 'db-credentials' not found in namespace 'production'"
KB match:    k8s-001 — CrashLoopBackOff: missing Secret (score=0.94)
Change:      Deployment updated 4m ago — added envFrom.secretRef.name: db-credentials
Similar:     inc-prev-023 — auth-service missing secret (resolved, fix worked)
Confidence:  0.97
```

This is what the LLM receives as context. The root cause is not guessed — it is derived from these signals.

---

## Architecture

```
┌─────────────────────────────────────────────────────────────────────────────────┐
│                              Kubernetes Cluster                                  │
│                                                                                  │
│  ┌────────────────────────────────────────────────────────────────────────────┐  │
│  │  APPLICATION PODS                                                           │  │
│  │   ┌──────────────────┐    ┌────────────────────────────────────────────┐   │  │
│  │   │   Your App       │    │   AI SRE Sidecar Agent (optional)          │   │  │
│  │   │   (any language) │───▶│   Tails logs · detects errors · reports   │   │  │
│  │   └──────────────────┘    │   latency P50/P95/P99 · learns patterns   │   │  │
│  │                           └─────────────────┬──────────────────────────┘   │  │
│  └─────────────────────────────────────────────┼──────────────────────────────┘  │
│                                                │ HTTP POST every 30s              │
│  ┌─────────────────────────────────────────────▼──────────────────────────────┐  │
│  │  OPERATOR CORE                                                              │  │
│  │                                                                             │  │
│  │  K8s Watch Loop (30s) ──▶  Detectors (18)  ──▶  Signal Correlator         │  │
│  │                                                          │                  │  │
│  │  Knowledge Base (54) ──────────────────────────────────▶│                  │  │
│  │  Incident Memory                                         ▼                  │  │
│  │  Feedback Store  ──────────────────────────────▶  AI RCA Engine            │  │
│  │                                    Anthropic / OpenAI / rule-based         │  │
│  │                                                          │                  │  │
│  │                                                          ▼                  │  │
│  │                                              Remediation Controller         │  │
│  │                                    L1: auto-fix  L2: approval  L3: suggest │  │
│  │                                                          │                  │  │
│  │                                                          ▼                  │  │
│  │                                               Learning Store               │  │
│  │                              Capture → Cluster → Promote → Refit          │  │
│  └────────────────────────────────────────────────────────────────────────────┘  │
└─────────────────────────────────────────────────────────────────────────────────┘
               ▲                       ▲                        ▲
          FastAPI REST            Streamlit UI             Click CLI
          :8000  /docs             :8501                  ai-sre ...
```

See [docs/architecture.md](docs/architecture.md) for the full layer-by-layer breakdown and project structure.

---

## Features

### Infrastructure Monitoring

| Component | Details |
|---|---|
| **18 failure detectors** | CrashLoopBackOff, OOMKill, ImagePull, PendingPod, ProbeFailure, ServiceMismatch, IngressBackend, PVC, HPA, DNS, RBAC, NetworkPolicy, CNI, ServiceMesh, NodePressure, Quota, Rollout, Storage |
| **54 KB patterns** | Generic K8s (12), EKS (6), AKS (5), GKE (5), Networking (8), Storage (6), Security (5), Cluster (4), Application (3) |
| **Cloud provider awareness** | Auto-detects EKS/AKS/GKE from node `spec.providerID` and labels; boosts cloud-specific patterns |
| **Signal correlation** | Every signal classified as root_cause, symptom, or contributing_factor with causal timeline |

### Application Performance Monitoring

| Component | Details |
|---|---|
| **Sidecar agent** | Lightweight Python container (< 64Mi) — zero code changes, zero SDK requirement |
| **Error detection** | Python/Java/Go/Node.js exceptions, HTTP 5xx, slow queries, DB connection failures |
| **Service health score** | 0–100 combining error rate, P99 latency, crash count — computed per service every 30s |
| **APM + SRE correlation** | Application errors linked to infrastructure events (e.g., DB pool exhaustion ↔ network policy change) |

### AI and Learning

| Component | Details |
|---|---|
| **LLM providers** | Anthropic Claude 3, OpenAI GPT-4o, offline rule-based fallback |
| **RAG-powered RCA** | KB patterns + past incidents as LLM context; structured output with confidence score |
| **Feedback loop** | Operator feedback adjusts per-pattern confidence; successful patterns promoted to KB |
| **Embeddings** | TF-IDF + sentence-transformers (all-MiniLM-L6-v2) for semantic similarity |

### Remediation and Safety

| Component | Details |
|---|---|
| **3-tier safety model** | L1 auto-fix (safe, reversible) · L2 approval-required · L3 suggest-only (manual always) |
| **6 remediations** | Pod restart, rollout restart, scale, rollback, resource patch, job rerun |
| **Dry-run default** | All actions simulate unless `dry_run=false` is explicitly passed |
| **Namespace guardrails** | kube-system and kube-public unconditionally blocked |
| **Cooldown tracking** | 300s default between remediations of the same workload |

---

## Example Incident Walkthroughs

### 1. CrashLoopBackOff — Missing Secret

**What you see:**
```
payment-api-7d9f8b-xk2p9   0/1   CrashLoopBackOff   18   23m
```

**K8s events:**
```
Warning  Failed    1x  kubelet  Error: secret "db-credentials" not found
Warning  BackOff  18x  kubelet  Back-off restarting failed container
```

**Container logs:**
```
ERROR  Failed to load config: secret 'db-credentials' not found in namespace 'production'
ERROR  Database connection pool initialization failed: host=<nil>
FATAL  Application startup failed — cannot continue without database configuration
```

**AI root cause** (confidence: 0.97 — KB pattern k8s-001):
> The deployment was updated 4 minutes ago to add `envFrom.secretRef.name: db-credentials`. This Secret does not exist in the `production` namespace. Every pod crashes immediately at startup. This is not a code bug — the application correctly refuses to start without its required configuration.

**Remediation** (L3 — suggest only):
```bash
kubectl create secret generic db-credentials \
  --from-literal=DB_HOST=postgres.production.svc \
  --from-literal=DB_PORT=5432 \
  --from-literal=DB_NAME=payments \
  -n production
kubectl rollout status deployment/payment-api -n production
```

---

### 2. Service Selector Mismatch — All Requests Return 503

**What you see:**
```bash
kubectl get endpoints checkout-api -n production
# NAME            ENDPOINTS   AGE
# checkout-api    <none>      8m
```

**Detector findings:**
- Service selector: `{ app: checkout-api, version: stable }`
- Running pods carry label: `{ app: checkout-api, version: v2.1.0 }`
- Result: 0 matching endpoints

**AI root cause** (confidence: 0.93 — KB pattern k8s-011):
> The `checkout-api` Service selects pods with `version: stable`, but the running pods carry `version: v2.1.0`. The `stable` label was previously applied via a manual `kubectl label` step that was missed in this deployment. The Ingress is correctly configured — the failure is at the Service-to-Pod selector level.

**Remediation** (L2 — approval required):
```bash
kubectl patch service checkout-api -n production \
  -p '{"spec":{"selector":{"app":"checkout-api","version":"v2.1.0"}}}'
kubectl get endpoints checkout-api -n production   # should show IPs immediately
```

---

### 3. Pending Pods — Node Resource Exhaustion

**What you see:**
```bash
kubectl get pods -n batch | grep Pending
# batch-processor-6b8f4d-bj9kl   0/1   Pending   0   8m
# (+ 14 more)
```

**Scheduler events:**
```
0/6 nodes are available: 2 nodes have insufficient cpu, 4 had taint node.kubernetes.io/not-ready
```

**Signal correlation:** HPA scaled `batch-processor` from 2→20 replicas 9 minutes ago. Two nodes are in NotReady state from a concurrent rolling node upgrade. Remaining 4 nodes are at 88–93% CPU allocation.

**AI root cause** (confidence: 0.88 — KB patterns k8s-008 + clust-003 correlated):
> The HPA correctly responded to queue depth, but the cluster cannot absorb the scale event. Two nodes are unavailable due to a concurrent node pool upgrade, and the remaining four are above 85% CPU allocation. This is a capacity headroom problem, not an HPA configuration problem.

**Remediation** (L2):
```bash
kubectl patch hpa batch-processor-hpa -n batch \
  --type=merge -p '{"spec":{"maxReplicas":6}}'   # cap until capacity available
```

---

### 4. OOMKilled — Memory Limit Under-provisioned

**What you see:**
```
report-generator-9c4b7e-rk8mn   0/1   OOMKilled   5   18m
```

**Node events:**
```
Warning  OOMKilling  Memory cgroup out of memory: Kill process 28471 (python3)
  total-vm:982604kB, anon-rss:511908kB  [limit: 512Mi]
```

**Correlated signals:** HPA scaled from 1→3 replicas 20 minutes ago. Memory growth is linear with request count — no plateau (ruling out a leak).

**AI root cause** (confidence: 0.86 — KB pattern k8s-003):
> `report-generator` has a `512Mi` memory limit that was sized for baseline load. PDF generation under 10x load requires 400–500Mi per worker. This is a resource sizing problem, not a code bug. The memory growth pattern confirms legitimate usage, not a leak.

**Remediation** (L2 — approval required):
```bash
kubectl set resources deployment/report-generator \
  --limits=memory=1Gi --requests=memory=512Mi -n production
```

---

### 5. EKS IRSA Misconfiguration — AWS API Calls Returning 403

**What you see:**
```
ERROR  aws: operation error S3: PutObject, https response error StatusCode: 403
       api error InvalidClientTokenId: The security token included in the request is invalid
```

**Provider detection:** EKS confirmed from node labels (`eks.amazonaws.com/nodegroup`). Cloud-specific patterns boosted +0.15.

**Evidence:** ServiceAccount has IRSA annotation `eks.amazonaws.com/role-arn: arn:aws:iam::123456789:role/s3-exporter-role`. IAM trust policy condition targets `system:serviceaccount:staging:s3-exporter`. Pod runs in namespace `production`.

**AI root cause** (confidence: 0.91 — KB pattern eks-002, +0.15 EKS boost):
> The IAM trust policy restricts token assumption to `system:serviceaccount:staging:s3-exporter`. The pod is running in `production`, so AWS STS rejects the OIDC token. This is a namespace mismatch in the trust policy — the role was created for staging and not updated when the service was promoted to production.

**Remediation** (L3 — suggest only, requires AWS IAM access):
```bash
# Update trust policy: change "staging" → "production" in Condition.StringEquals
aws iam update-assume-role-policy --role-name s3-exporter-role \
  --policy-document file://trust-policy-production.json
kubectl rollout restart deployment/s3-exporter -n production
```

See [docs/examples.md](docs/examples.md) for the full walkthrough of each scenario including expected outcomes.

---

## Safety Model

Three tiers govern every remediation action. This classification is set at design time and cannot be overridden at runtime.

| Level | Name | Behavior | Examples |
|---|---|---|---|
| **L1** | auto-fix | Executes automatically when `AUTO_FIX_ENABLED=true` | Restart crashed pod, rerun failed job, collect diagnostics |
| **L2** | approval-required | Queues plan, waits for `POST .../approve` | Scale down, rollback deployment, patch resource limits |
| **L3** | suggest-only | Never auto-executes — command displayed for human to run | Create secret, RBAC changes, network policy, drain node |

**Guardrails enforced in order before any action runs:**

1. **Namespace deny list** — kube-system and kube-public unconditionally blocked, regardless of any flag
2. **Action allowlist** — only explicitly permitted actions can execute in non-denied namespaces
3. **Safety level** — L3 actions blocked even with `AUTO_FIX_ENABLED=true`; L2 blocked until approved
4. **Cooldown** — 300s between remediations of the same workload (prevents rapid loops)
5. **Dry-run** — if `OPERATOR_DRY_RUN=true` (the default), all actions simulate without real changes

**Default configuration:** `OPERATOR_DRY_RUN=true`, `AUTO_FIX_ENABLED=false`. Both must be explicitly changed to enable live execution.

**Blast radius:** the worst case for L1 auto-execution (all restrictions removed) is a pod restart on a non-system deployment, prevented from looping by the 5-minute cooldown.

See [docs/safety.md](docs/safety.md) for the full action mapping, blast radius analysis, and audit log format.

---

## Knowledge Base

54 failure patterns across 9 categories, all human-readable YAML in [knowledge/failures/](knowledge/failures/). No Python required to add custom patterns.

| Category | Patterns | Example failures |
|---|---|---|
| Generic K8s | 12 | CrashLoop (6 root causes), OOMKill, ImagePull, PVC, DNS |
| EKS | 6 | ENI exhaustion, IRSA mismatch, Fargate profile missing, API throttling |
| AKS | 5 | VM quota exceeded, Managed Identity missing, disk attach, VMSS degraded |
| GKE | 5 | Workload Identity, Autopilot quota, NAP provisioning, Binary Authorization |
| Networking | 8 | CoreDNS, NetworkPolicy blocking, CNI IP exhaustion, Istio mTLS |
| Storage | 6 | PVC not binding, CSI driver missing, StorageClass deleted |
| Security | 5 | RBAC forbidden, ServiceAccount missing, Pod Security Admission |
| Cluster | 4 | ResourceQuota exceeded, LimitRange violation, Node NotReady, etcd |
| Application | 3 | DB connection pool, HTTP 5xx spike, memory leak |

Each pattern includes: symptoms, event patterns, log regex patterns, metric thresholds, root cause explanation, ordered remediation steps, confidence boosts, and safety level classification.

See [docs/knowledge-base.md](docs/knowledge-base.md) for the pattern schema and search API.

---

## APM Sidecar Agent

Add the sidecar to any pod — zero code changes to your application:

```yaml
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
        limits:   { cpu: 50m, memory: 64Mi }
      volumeMounts:
        - name: app-logs
          mountPath: /var/log/app
          readOnly: true

  volumes:
    - name: app-logs
      emptyDir: {}
```

The agent detects: Python tracebacks, Java/Go/Node.js exceptions, HTTP 4xx/5xx errors, slow queries (>1s), DB connection pool exhaustion, and memory pressure signatures. Every 30 seconds it posts a structured APM report to the operator API.

See [docs/sidecar-agent.md](docs/sidecar-agent.md) for configuration, custom patterns, and resource tuning.

---

## CLI Usage

Install dependencies, then run `python3 -m cli.main` or add to PATH as `ai-sre`:

```bash
pip install -r requirements.txt
alias ai-sre="python3 -m cli.main"
```

### Cluster scan

```bash
$ ai-sre cluster scan --namespace production
```

```
╭─────────────────── ✅ Scan Results ────────────────────╮
│ Scan complete                                           │
│   Total detections:  3                                  │
│   Incidents created: 2                                  │
│   Scanned at:        2024-01-15T09:25:00Z               │
╰─────────────────────────────────────────────────────────╯
┌──────────────┬──────────────────────────────────────────┐
│ Incident ID  │                                          │
├──────────────┼──────────────────────────────────────────┤
│ inc-a3f9b1c2 │                                          │
│ inc-c7e2d4f1 │                                          │
└──────────────┴──────────────────────────────────────────┘
```

### List incidents

```bash
$ ai-sre incidents list --severity critical
```

```
                          Active Incidents
 ──────────┬──────────┬──────────────────────┬────────────── ─
  ID       │ Severity │ Type                 │ Workload
 ──────────┼──────────┼──────────────────────┼───────────────
  a3f9b1.. │ CRITICAL │ CrashLoopBackOff     │ payment-api
  c7e2d4.. │ CRITICAL │ ServiceNoEndpoints   │ checkout-api
 ──────────┴──────────┴──────────────────────┴───────────────
```

### Analyze an incident

```bash
$ ai-sre incident analyze inc-a3f9b1c2
```

```
╭──────── 📋 Incident Summary ─────────╮
│ Title:     CrashLoopBackOff: payment-api
│ Type:      CrashLoopBackOff
│ Namespace: production/payment-api
│ Severity:  CRITICAL
│ Confidence: 97%
╰──────────────────────────────────────╯
╭──────────── 🎯 Root Cause ───────────╮
│ The payment-api deployment references │
│ Secret 'db-credentials' which does    │
│ not exist in namespace 'production'.  │
│ Introduced 4 minutes ago via a        │
│ deployment update.                    │
╰──────────────────────────────────────╯
```

### Get remediation plan

```bash
$ ai-sre remediation plan inc-a3f9b1c2
```

```
╭──────── 🔧 Remediation Plan ──────────╮
│ Safety Level:      SUGGEST_ONLY        │
│ Requires Approval: No                  │
│ Steps:             3                   │
╰────────────────────────────────────────╯
  #   Action                Safety           Description
 ─── ────────────────────── ──────────────── ──────────────────────────────
  1  verify_secret_missing  AUTO_FIX       ✅ kubectl get secret db-credentials
  2  recreate_secret        SUGGEST_ONLY   🔴 kubectl create secret generic ...
  3  verify_recovery        AUTO_FIX       ✅ kubectl rollout status deployment/
```

### Simulate an incident (fully offline)

```bash
$ ai-sre simulate --type crashloop --demo
```

```
╭─────────────── 🎮 Simulation Mode ───────────────╮
│ Simulating CRASHLOOP incident                      │
│ Loading from: examples/crashloop_missing_secret.json│
╰────────────────────────────────────────────────────╯
  Running AI analysis pipeline (offline)...

╭──── CRITICAL — CrashLoopBackOff ────╮
│ Namespace/Workload: production/payment-api
│ Root Cause: Secret 'db-credentials' not found
│ Confidence: 97%
╰──────────────────────────────────────╯
```

### Search the knowledge base

```bash
$ ai-sre knowledge search "connection pool exhausted" --provider aws
```

```
       Knowledge Base Search: 'connection pool exhausted'
 ──────────┬────────────────────────────────────────┬───────
  ID       │ Title                                  │ Score
 ──────────┼────────────────────────────────────────┼───────
  app-001  │ Application — db connection pool       │  0.89
  k8s-003  │ CrashLoopBackOff — OOMKill             │  0.54
  net-007  │ Service mesh circuit breaker open       │  0.41

╭── 💡 Top Match: Application — db connection pool ──╮
│ Root cause: Pool fully saturated — all connections  │
│ in use, new requests queued or rejected.            │
│                                                     │
│ 1. SELECT count(*) FROM pg_stat_activity ...        │
│ 2. SELECT pid, query FROM pg_stat_activity ...      │
│ 3. SELECT pg_terminate_backend(<pid>)               │
╰─────────────────────────────────────────────────────╯
```

See [docs/cli.md](docs/cli.md) for the full command reference.

---

## API Usage

Swagger docs at `http://localhost:8000/docs`. Key endpoints:

### Trigger a cluster scan

```bash
curl -X POST http://localhost:8000/api/v1/scan | jq .
```
```json
{
  "incidents_detected": 2,
  "duration_ms": 847,
  "incidents": [
    { "id": "inc-a3f9b1", "title": "CrashLoopBackOff: payment-api",
      "severity": "critical", "namespace": "production" }
  ]
}
```

### Analyze an incident

```bash
curl -X POST http://localhost:8000/api/v1/incidents/inc-a3f9b1/analyze | jq .
```
```json
{
  "root_cause": "Secret 'db-credentials' not found in namespace 'production'...",
  "confidence": 0.97,
  "kb_patterns_matched": ["k8s-001"],
  "similar_incidents": 2,
  "remediation_hint": "kubectl create secret generic db-credentials -n production"
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
  "steps": [
    { "order": 1, "action": "verify_secret_missing",
      "command": "kubectl get secret db-credentials -n production" },
    { "order": 2, "action": "recreate_secret",
      "command": "kubectl create secret generic db-credentials ...",
      "safety_level": "suggest_only" },
    { "order": 3, "action": "verify_recovery",
      "command": "kubectl rollout status deployment/payment-api -n production" }
  ]
}
```

### Submit feedback (trains the system)

```bash
curl -X POST http://localhost:8000/api/v1/feedback/structured \
  -H "Content-Type: application/json" \
  -d '{"incident_id":"inc-a3f9b1","correct_root_cause":true,"fix_worked":true,
       "operator_notes":"Created secret, pods recovered in 45s"}'
```
```json
{ "accepted": true, "patterns_updated": ["k8s-001"], "confidence_delta": 0.1 }
```

See [docs/api.md](docs/api.md) for all 29 endpoints with complete request/response examples.

---

## Deployment

### Local development

```bash
make run-api     # FastAPI on :8000
make run-ui      # Streamlit on :8501
make simulate    # Inject demo incidents
```

### Docker Compose

```bash
docker-compose up -d   # API :8000, UI :8501
```

### Helm (Kubernetes)

```bash
# Install or upgrade (idempotent)
helm upgrade --install ai-sre-operator ./helm/ai-k8s-sre-operator \
  --namespace ai-sre --create-namespace \
  --values helm/values-production.yaml \
  --set llm.apiKey=$ANTHROPIC_API_KEY

# Uninstall
helm uninstall ai-sre-operator --namespace ai-sre

# Verify
kubectl get pods -n ai-sre
kubectl port-forward svc/ai-sre-operator 8000:8000 -n ai-sre
curl http://localhost:8000/health

# View logs
kubectl logs -n ai-sre -l app.kubernetes.io/name=ai-sre-operator --tail=50
```

Pre-built values:
- [helm/values-demo.yaml](helm/values-demo.yaml) — no cluster, no API key, offline
- [helm/values-production.yaml](helm/values-production.yaml) — production-hardened config

**Storage class by provider:**

| Platform | StorageClass |
|---|---|
| EKS | `gp3` |
| AKS | `default` |
| GKE | `standard-rwo` |
| Kind / Minikube | `standard` |

**RBAC:** all read-only by default. Write permissions (patch, delete) only used when `AUTO_FIX_ENABLED=true` for L1 actions. kube-system and kube-public are unconditionally excluded.

See [docs/deployment.md](docs/deployment.md) for full production configuration, RBAC table, PostgreSQL setup, and observability integration.

---

## How This Differs From Existing Tools

### vs. Prometheus + Grafana

Prometheus and Grafana are excellent for observing metrics and setting thresholds. They don't detect root cause — they surface symptoms. A Prometheus alert for `container_memory_working_set_bytes > 400Mi` tells you memory is high. It doesn't tell you whether that's a leak, a legitimate load spike, a misconfigured limit, or a cascading failure from another service.

This system correlates the memory metric with HPA events, recent deploys, and application log patterns to provide a specific, evidence-backed explanation.

### vs. Alertmanager / PagerDuty

Alert routing gets the right person paged. It does not help that person understand what happened or what to do. This system is the layer between "alert fired" and "engineer knows what to run" — it provides the diagnosis and the remediation plan, not just the notification.

### vs. AI chatbots (ChatGPT, Copilot)

General-purpose LLMs can answer questions about Kubernetes — but they don't have access to your cluster state, your specific logs, your recent deployment changes, or your past incidents. They reason generically.

This system feeds the LLM a structured evidence bundle: the specific K8s events, log lines, metric values, deployment changes, and matched KB patterns from your cluster. The LLM reasons about your incident, not a hypothetical one.

### vs. Commercial APM (Datadog, AppDynamics, New Relic)

| Feature | This tool | Datadog | AppDynamics |
|---|---|---|---|
| Kubernetes SRE automation | ✅ 18 detectors | ⚠️ alerts only | ⚠️ basic |
| AI root cause with evidence | ✅ structured bundle | ⚠️ ML anomaly | ✅ ML |
| Automated remediation | ✅ 3-tier safe | ❌ | ❌ |
| Self-learning from feedback | ✅ | ❌ | ❌ |
| Custom failure patterns (YAML) | ✅ | ❌ | ❌ |
| Cloud-specific KB (EKS/AKS/GKE) | ✅ | ⚠️ partial | ❌ |
| Zero-code APM sidecar | ✅ | ❌ SDK required | ❌ SDK required |
| Fully offline / self-hosted | ✅ | ❌ | ❌ |
| Open source | ✅ MIT | ❌ | ❌ |

---

## Evaluation

The system tracks its own accuracy through operator feedback.

| Metric | How measured | Baseline |
|---|---|---|
| KB pattern match rate | % of incidents matched to ≥1 pattern | ~85% on known failure types |
| RCA accuracy (high confidence) | Operator feedback "correct RCA" rate when confidence ≥0.8 | ~82% |
| RCA accuracy (low confidence) | Same, when confidence <0.5 | ~40% — calibration working |
| Fix success rate | % of executed remediations confirmed working | Tracked per pattern |
| Novel error capture | % of unmatched error lines submitted for learning | ~40% |

Confidence calibration is a key indicator: the system correctly expresses uncertainty. When it is highly confident, it is right ~82% of the time. When it is uncertain (confidence <0.5), it is right ~40% of the time. That gap means the confidence score carries information.

See [docs/evaluation.md](docs/evaluation.md) for the full methodology, confidence tier system, pattern promotion pipeline, and future evaluation plan.

---

## Roadmap

### Phase 1 — Foundation (complete)

18 detectors, 54 KB patterns, AI RCA, 3-tier remediation, feedback learning, multi-cloud, CI/CD, Helm.

### Phase 2 — APM (in progress)

Sidecar agent, APM ingest, service health scores, APM+SRE correlation. Auto-injection webhook planned.

### Phase 3 — Advanced AI (planned)

Time-series anomaly detection, proactive failure prediction, natural language incident queries, automated post-mortem drafts.

### Phase 4 — Enterprise (planned)

Multi-cluster, RBAC for the operator itself, SSO/OIDC, Slack/PagerDuty/Jira, SLO tracking, PostgreSQL backend.

See [docs/roadmap.md](docs/roadmap.md) for the detailed backlog.

---

## Testing

```bash
make test                                   # 202 tests
make test-cov                               # with coverage report
DEMO_MODE=1 python3 -m pytest tests/ -v    # verbose output

# Integration test against a real Kind cluster
kind create cluster --name sre-test
python3 -m pytest tests/integration/ -v
```

Tests cover: all 18 detectors, KB search and scoring, API endpoints, signal correlation, safety policies, all 6 remediations, feedback loop, and AI engine (with mock LLM).

---

## Documentation

| Document | Description |
|---|---|
| [Architecture](docs/architecture.md) | 7-layer pipeline, component diagram, full project structure |
| [Example Incidents](docs/examples.md) | 6 complete walkthroughs with symptoms, logs, AI output, remediation |
| [Application Monitoring](docs/application-monitoring.md) | APM setup, service health scores, sidecar configuration |
| [Sidecar Agent](docs/sidecar-agent.md) | Deployment, env vars, custom patterns, resource sizing |
| [Detectors](docs/detectors.md) | All 18 detectors — what they check and what evidence they return |
| [Knowledge Base](docs/knowledge-base.md) | Pattern schema, search API, adding custom patterns |
| [Learning and Feedback](docs/learning.md) | Feedback loop, confidence adjustment, pattern promotion |
| [Safety Model](docs/safety.md) | L1/L2/L3 actions, guardrails, blast radius, audit log |
| [Evaluation](docs/evaluation.md) | Accuracy metrics, confidence calibration, feedback model |
| [API Reference](docs/api.md) | All 29 endpoints with real request/response examples |
| [CLI Reference](docs/cli.md) | All CLI commands |
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

To add a failure pattern: create a YAML entry in `knowledge/failures/` — no Python required. See [docs/knowledge-base.md](docs/knowledge-base.md) for the schema.

To add a detector: implement `BaseDetector` in `detectors/`, add tests in `tests/test_detectors.py`, register in `collectors/k8s_watcher.py`.

---

## License

MIT — Copyright 2025 Anil Thotakura. See [LICENSE](LICENSE).
