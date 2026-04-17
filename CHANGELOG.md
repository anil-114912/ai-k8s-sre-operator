# Changelog

All notable changes to this project are documented here.

Format follows [Keep a Changelog](https://keepachangelog.com/en/1.0.0/). Versions follow [Semantic Versioning](https://semver.org/).

---

## [0.2.0] — 2026-04-16

### Added

**Cloud-provider detection and hardening**

- Auto-detects cluster provider (EKS / AKS / GKE) from node `spec.providerID` prefix (`aws://`, `azure://`, `gce://`) and node labels at startup — no manual configuration required
- `CLUSTER_PROVIDER` environment variable and `cluster.provider` Helm value to override detection
- Provider-aware KB scoring: patterns tagged for a matching cloud provider receive a +0.15 relevance boost

**EKS knowledge base expansion**

- `eks-005` — Fargate profile missing: pods targeting a Fargate namespace with no matching profile remain Pending indefinitely
- `eks-006` — API server throttling: `kubectl` and operators receive 429s when IAM calls or admission webhooks exceed the per-account throttle limit
- Both patterns include provider-specific remediation steps

**AKS knowledge base expansion**

- `aks-004` — VMSS node group degraded: nodes in a VM Scale Set fail to join when the VMSS quota is exhausted or a zone is unavailable
- `aks-005` — Workload Identity webhook unavailable: pod startup blocked when the Azure Workload Identity mutating webhook is not ready

**GKE knowledge base expansion**

- `gke-004` — Node Auto-Provisioning (NAP) timeout: cluster autoscaler requests a new node pool but provisioning times out due to quota or zone constraint
- `gke-005` — Binary Authorization policy violation: pod rejected by Binary Authorization when the container image is not attested for the target namespace

**Helm chart**

- `helm/values-demo.yaml` — pre-built values for demo mode: simulated cluster, offline analysis, no PVC required
- `helm/values-production.yaml` — pre-built values for production: dry-run on, auto-fix off, resource limits set, LLM key from Secret
- `helm/NOTES.txt` — post-install guidance including storage class selection by cloud provider

**CI**

- Kind-based integration test: spins up a real K8s cluster in CI, runs all detectors, verifies API health
- Added `helm lint` job to catch chart template errors before merge

**Bug fixes**

- Fixed `ruff F521` format string bug in `llm.py` — f-string with no interpolation placeholders now a plain string
- Fixed `capture_unknown_error()` call in `api/main.py` — correct plural method `capture_unknown_errors()` with batch signature
- Fixed ad-hoc `type("E", (), {...})()` Evidence construction — now uses proper `Evidence(...)` Pydantic model
- Fixed unused imports flagged by ruff: `MultiLogTailer` in `agent/main.py`, `os` in `agent/metrics_reporter.py`
- Fixed trailing whitespace in `ui/streamlit_app.py`

### Changed

- Helm `Chart.yaml`: removed placeholder maintainer email, added repository URL

---

## [0.1.0] — 2025-12-01

Initial release.

### Added

**Infrastructure monitoring — 18 deterministic detectors**

| Detector | What it catches |
|---|---|
| `CrashLoopDetector` | CrashLoopBackOff with 6 root cause variants: missing secret, bad health check, config error, OOM, image entrypoint, dependency |
| `OOMKillDetector` | OOMKilled containers with memory limit evidence |
| `ImagePullDetector` | ImagePullBackOff and ErrImagePull — bad tag, private registry, rate limit |
| `PendingPodDetector` | Pod stuck Pending — insufficient CPU/memory, node selector, taints/tolerations |
| `ProbeFailureDetector` | Readiness and liveness probe failures with evidence from events |
| `ServiceDetector` | Service selector mismatch — endpoints are empty when selector doesn't match pod labels |
| `IngressDetector` | Ingress backend service missing or port mismatch |
| `PVCDetector` | PVC stuck Pending and FailedMount events |
| `HPADetector` | HPA unable to scale — maxReplicas reached, metrics unavailable |
| `DNSDetector` | CoreDNS failures and DNS resolution errors from pod events |
| `RBACDetector` | Forbidden events from RBAC misconfiguration |
| `NetworkPolicyDetector` | NetworkPolicy blocking traffic — connection refused with policy present |
| `CNIDetector` | CNI plugin failures — pod network attachment errors |
| `ServiceMeshDetector` | Istio and Linkerd sidecar injection failures and proxy errors |
| `NodePressureDetector` | Node pressure conditions: MemoryPressure, DiskPressure, PIDPressure |
| `ResourceQuotaDetector` | ResourceQuota exceeded — pods rejected at admission |
| `RolloutDetector` | Deployment rollout stuck — ProgressDeadlineExceeded |
| `StorageDetector` | StorageClass missing and CSI driver errors |

**Knowledge base — 54 failure patterns**

- Generic K8s patterns (12): CrashLoop variants, OOMKill, ImagePull, Pending, Probe, Service, Ingress, PVC, HPA, Rollout
- EKS patterns (4): node group IAM, IRSA trust policy, ENI exhaustion, EKS add-on conflict
- AKS patterns (3): VM quota, Managed Identity, Azure Disk attach failure
- GKE patterns (3): Workload Identity binding, Autopilot resource class, Filestore CSI
- Networking patterns (8): DNS, NetworkPolicy, CNI, Ingress
- Storage patterns (6): PVC, CSI, StorageClass
- Security patterns (5): RBAC, Secret, ServiceAccount
- Cluster patterns (4): node pressure, quota, service mesh

**AI root cause analysis**

- Anthropic Claude (claude-3-5-sonnet-20241022) and OpenAI GPT-4o support
- Rule-based offline fallback — works without any API key for all 54 KB patterns
- RAG: KB patterns + incident memory retrieved and injected as context
- TF-IDF + sentence-transformer embeddings (all-MiniLM-L6-v2) for semantic incident similarity
- 7-step pipeline: signal collection → detection → correlation → KB search → incident memory → AI reasoning → remediation controller

**Remediation — 6 executors**

| Executor | Action | Default Safety |
|---|---|---|
| `restart_pod` | Delete pod, allow controller to recreate | L1 auto-fix |
| `rollout_restart` | `kubectl rollout restart deployment` | L1 auto-fix |
| `scale` | Adjust HPA bounds or replica count | L2 approval-required |
| `rollback` | Set deployment image to previous revision | L2 approval-required |
| `patch_resources` | Patch CPU/memory limits on a container | L2 approval-required |
| `rerun_job` | Delete failed job, recreate from spec | L1 auto-fix |

3-tier safety system:
- **L1 auto-fix** — executes immediately when `AUTO_FIX_ENABLED=true`
- **L2 approval-required** — queued until operator approves via API or dashboard
- **L3 suggest-only** — never executes; plan presented for manual review

All remediations default to dry-run mode. Namespace deny list (`kube-system`, `kube-public`) is always enforced. Per-workload cooldown (5 minutes default) prevents repeated automated actions.

**Feedback learning loop**

- Captures novel error patterns from pod logs (Python, Java, Go, Node.js stacktraces)
- Deduplicates signatures to avoid noise
- Positive feedback → confidence boost; negative feedback → confidence reduction
- Pattern promotion: patterns with 2+ confirmed successful fixes promoted to KB
- Embedder refit triggered after every 5 new incidents

**Application Performance Monitoring (APM) — sidecar agent**

- Lightweight Python agent (`agent/`) tails pod stdout/stderr via shared EmptyDir volume
- Detects: HTTP 5xx responses, slow operations, Python/Java/Go/Node.js exception stacktraces
- Reports metrics to operator API every 30 seconds
- APM API endpoints: `/api/v1/apm/ingest`, `/api/v1/apm/services`, `/api/v1/apm/errors`, `/api/v1/apm/learn`
- Correlates application errors with K8s events for unified incident context

**API and UI**

- FastAPI REST with 29 endpoints, automatic Swagger docs at `/docs` and `/redoc`
- Streamlit dashboard with 8 tabs: Live Incidents, RCA Analysis, Remediation, APM, Incident History, Cluster Scan, Knowledge Base, Learning & Feedback
- Click CLI (`ai-sre`) with Rich terminal output: panels, tables, spinners

**Infrastructure**

- SQLite persistence via SQLAlchemy — incidents, feedback events, learned patterns (PostgreSQL-ready)
- Helm chart: EKS, AKS, GKE, and local Kind/Minikube support
- `DEMO_MODE=1` — fully simulated cluster for evaluation without a real K8s cluster
- Auto cloud-provider detection from node labels and `spec.providerID`
- GitHub Actions CI: lint (ruff), type check, unit tests (202 tests), smoke test, Helm lint

---

## Upgrade Guide

### 0.1.0 → 0.2.0

No breaking changes to the API or database schema.

**Helm upgrade**

```bash
helm upgrade --install ai-sre-operator ./helm/ai-k8s-sre-operator \
  --namespace ai-sre \
  --values helm/values-production.yaml \
  --set llm.apiKey=$ANTHROPIC_API_KEY
```

**Python upgrade**

```bash
pip install -r requirements.txt   # no new dependencies in 0.2.0
```

The new KB patterns (eks-005, eks-006, aks-004, aks-005, gke-004, gke-005) are loaded from YAML automatically on startup — no database migration needed.

---

## Roadmap

See [docs/roadmap.md](docs/roadmap.md) for the full phase plan.

| Phase | Focus | Status |
|---|---|---|
| Phase 1 | SRE Foundation: detectors, KB, AI RCA, remediation, feedback loop | ✅ Complete |
| Phase 2 | Application Performance Monitoring: sidecar agent, APM API, APM dashboard | 🔄 In Progress |
| Phase 3 | Advanced AI: anomaly detection, proactive prediction, fine-tuned model | 📋 Planned |
| Phase 4 | Enterprise: multi-cluster, Slack/PagerDuty/Jira, SLOs, PostgreSQL | 📋 Planned |
