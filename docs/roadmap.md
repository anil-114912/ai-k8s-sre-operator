# Roadmap

This document tracks planned features across four phases. Items marked ✅ are complete, 🔄 are in progress, and 📋 are planned.

---

## Phase 1 — SRE Foundation ✅ Complete

Core infrastructure monitoring and AI-driven incident management.

### Infrastructure Detection
- ✅ 18 deterministic failure detectors
- ✅ CrashLoopBackOff (6 root cause variants)
- ✅ OOMKill with memory limit evidence
- ✅ ImagePullBackOff / ErrImagePull
- ✅ Pending pod scheduling analysis
- ✅ Readiness / liveness probe failures
- ✅ Service selector mismatch
- ✅ Ingress backend missing
- ✅ PVC pending / FailedMount
- ✅ HPA locked or saturated
- ✅ CoreDNS / DNS resolution failures
- ✅ RBAC forbidden events
- ✅ NetworkPolicy blocking traffic
- ✅ CNI plugin failures
- ✅ Service mesh (Istio/Linkerd) errors
- ✅ Node pressure (CPU/memory/disk)
- ✅ ResourceQuota exceeded
- ✅ Rollout stuck / ProgressDeadlineExceeded
- ✅ Storage class missing / CSI driver errors

### Knowledge Base
- ✅ 53 failure patterns in human-readable YAML
- ✅ Generic K8s patterns (12)
- ✅ EKS-specific patterns (6): node group, IRSA, ENI, add-ons, Fargate, API throttling
- ✅ AKS-specific patterns (5): VM quota, Managed Identity, disk attach, VMSS, WI webhook
- ✅ GKE-specific patterns (5): Workload Identity, Autopilot, Filestore, NAP, Binary Auth
- ✅ Networking, Storage, Security, Cluster patterns
- ✅ Provider-aware scoring boost (+0.15 for matching cloud)

### AI & Learning
- ✅ Anthropic Claude + OpenAI support
- ✅ Rule-based offline fallback (works without API key)
- ✅ RAG: KB patterns + incident memory as LLM context
- ✅ TF-IDF + sentence-transformer embeddings
- ✅ Feedback loop with confidence adjustment
- ✅ Novel error capture → learned patterns
- ✅ Pattern promotion after repeated successes
- ✅ Embedder refit on new incident data

### Remediation
- ✅ 6 remediations: restart pod, rollout restart, scale, rollback, patch, rerun job
- ✅ 3-tier safety: auto_fix / approval_required / suggest_only
- ✅ Dry-run mode (default)
- ✅ Namespace deny/allow policies
- ✅ Per-workload cooldown (5 min default)

### Infrastructure
- ✅ FastAPI REST (35+ endpoints)
- ✅ Streamlit dashboard (7 tabs)
- ✅ Click CLI
- ✅ SQLite persistence (SQLAlchemy)
- ✅ Helm chart (EKS/AKS/GKE/local)
- ✅ GitHub Actions CI (lint, test, smoke, helm lint, Kind integration)
- ✅ Auto cloud-provider detection from node labels
- ✅ DEMO_MODE — fully simulated cluster

---

## Phase 2 — Application Performance Monitoring 🔄 In Progress

Extend from K8s-level to application-level observability.

### Sidecar Agent
- 🔄 Lightweight Python sidecar agent (`agent/`)
- 🔄 Log tailer: tails pod stdout/stderr via shared volume
- 🔄 Error detector: Python/Java/Go/Node.js stacktraces, HTTP 5xx, slow ops
- 🔄 Metrics reporter: reports to operator API every 30s
- 🔄 Pattern learner: builds app-specific error signatures over time
- 🔄 Agent Dockerfile (< 64Mi image)
- 📋 MutatingWebhookConfiguration for auto-injection (annotation: `ai-sre-operator/inject-agent: "true"`)
- 📋 Agent configuration via ConfigMap per namespace

### APM Endpoints
- 🔄 `POST /api/v1/apm/ingest` — receive metrics from agents
- 🔄 `GET /api/v1/apm/services` — service health overview
- 🔄 `GET /api/v1/apm/services/{name}` — per-service details
- 🔄 `GET /api/v1/apm/errors` — error pattern aggregation
- 📋 `GET /api/v1/apm/traces` — basic distributed trace correlation
- 📋 `GET /api/v1/apm/topology` — service dependency map

### APM Intelligence
- 🔄 Application-level KB patterns (DB connection pool, HTTP error spike, memory leak)
- 🔄 APM + SRE signal correlation (app error ↔ K8s event)
- 📋 Error rate baseline learning (normal vs anomaly)
- 📋 Latency percentile trending (P50/P95/P99 history)
- 📋 Throughput anomaly detection
- 📋 Dependency failure propagation tracking

### Dashboard
- 📋 APM tab: service health heatmap, error rate charts, latency graphs
- 📋 Service topology graph
- 📋 Log stream viewer (filtered by error patterns)
- 📋 Unified timeline: K8s events + application errors on one axis

---

## Phase 3 — Advanced AI 📋 Planned

Proactive intelligence: predict failures before they happen.

### Model Training
- 📋 Fine-tune a small model (Phi-3-mini / Llama-3.2-3B) on accumulated incident history
- 📋 Export training dataset from SQLite incident store
- 📋 Confidence calibration using historical accuracy metrics
- 📋 Provider-specific model adapters (EKS, AKS, GKE fine-tuning)

### Anomaly Detection
- 📋 Time-series anomaly detection on cluster metrics (CPU, memory, error rate)
- 📋 Seasonal baseline modeling (weekday vs weekend patterns)
- 📋 Leading indicator detection (resource climbing → predict OOMKill)
- 📋 Application-level anomaly scoring from APM data

### Proactive Remediation
- 📋 Predictive scaling: detect resource pressure early, scale before OOM
- 📋 Pre-failure alert: "this deployment will likely OOMKill in 15 minutes"
- 📋 Automated rollback trigger on error rate regression after deploy
- 📋 Canary analysis: compare error rates between old/new version

### Natural Language Interface
- 📋 `/api/v1/query` — "Why did the payment service go down last Tuesday?"
- 📋 Incident timeline narrative generation
- 📋 Root cause summarisation for non-technical stakeholders
- 📋 Automated post-mortem draft generation

---

## Phase 4 — Enterprise 📋 Planned

Scale to multi-cluster, multi-team production environments.

### Multi-cluster
- 📋 Central control plane aggregates from N cluster agents
- 📋 Cross-cluster incident correlation
- 📋 Unified KB shared across clusters
- 📋 Per-cluster policy isolation

### Access Control
- 📋 RBAC for the operator API (viewer / responder / admin roles)
- 📋 SSO / OIDC integration (Okta, Azure AD, Google)
- 📋 Audit trail: who approved / executed what remediation
- 📋 Namespace-scoped access tokens for sidecar agents

### Integrations
- 📋 Slack: post incident + remediation plan with approve/reject buttons
- 📋 PagerDuty: escalate critical incidents, auto-resolve on fix
- 📋 Jira: create incident tickets, link to KB patterns, close on resolution
- 📋 GitHub: auto-create issues for recurring failures
- 📋 Grafana: datasource plugin for incident overlay on dashboards
- 📋 OpsGenie / VictorOps alerting

### SLO & Reliability
- 📋 SLO definition and tracking (availability, latency, error rate targets)
- 📋 Error budget calculation and burn rate alerting
- 📋 Reliability score per service over rolling windows
- 📋 SLO breach prediction from trend data

### Storage & Scale
- 📋 PostgreSQL backend option (replace SQLite for production)
- 📋 Time-series database integration (InfluxDB / TimescaleDB) for APM metrics
- 📋 Incident archiving and retention policies
- 📋 Horizontal scaling of the operator API

---

## Changelog

### v0.2.0 (April 2026) — Cloud-provider hardening
- Added auto cloud-provider detection (EKS/AKS/GKE) from node labels
- Expanded EKS KB: Fargate profile missing, API server throttling
- Expanded AKS KB: VMSS degraded, Workload Identity webhook
- Expanded GKE KB: NAP provisioning, Binary Authorization
- Added `cluster.provider` Helm value + `CLUSTER_PROVIDER` env var
- Added Kind-based integration test to CI
- Fixed ruff F521 format string bug in llm.py
- Added Helm NOTES.txt with storage class guidance

### v0.1.0 (2025) — Initial release
- 18 detectors, 45 KB patterns, AI RCA, 3-tier remediation
- Feedback loop, learning store, RAG context
- FastAPI + Streamlit + Click CLI
- Helm chart for EKS/AKS/GKE/local
