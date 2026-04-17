# Architecture

## Design Principles

The system is built around four principles:

1. **Determinism first** — pattern matching and rule-based logic runs before any LLM call. The system is fully functional without an API key.
2. **Evidence-based reasoning** — every root cause is backed by specific Kubernetes events, log lines, or metric thresholds — never a guess
3. **Safe by default** — dry-run mode is the default, auto-fix requires explicit opt-in, and critical namespaces are unconditionally protected
4. **Observable and debuggable** — all KB patterns are human-readable YAML, all incidents are persisted to SQLite, and the learning loop's decisions are traceable

---

## The Seven-Layer Pipeline

Every incident flows through these layers in sequence:

```
┌─────────────────────────────────────────────────────────┐
│  Layer 1 — Signal Collection                             │
│                                                          │
│  K8s Watch Loop (30s)                                    │
│  pods · events · deployments · services · nodes         │
│  HPAs · PVCs · ingresses · logs · metrics               │
│                                                          │
│  APM Ingest (sidecar agent → HTTP POST every 30s)       │
│  error_rate · latency p50/p95/p99 · exception patterns  │
└────────────────────────┬────────────────────────────────┘
                         ▼
┌─────────────────────────────────────────────────────────┐
│  Layer 2 — Deterministic Detection (18 detectors)        │
│                                                          │
│  Each detector returns:                                  │
│    type · resource name · namespace                      │
│    evidence (events, logs, metrics)                      │
│    severity (critical / high / medium / low)             │
│                                                          │
│  CrashLoop · OOM · ImagePull · Pending · Probe          │
│  Service · Ingress · PVC · HPA · DNS · RBAC             │
│  NetworkPolicy · CNI · ServiceMesh · NodePressure        │
│  Quota · Rollout · Storage                               │
└────────────────────────┬────────────────────────────────┘
                         ▼
┌─────────────────────────────────────────────────────────┐
│  Layer 3 — Signal Correlation                            │
│                                                          │
│  Classifies each signal:                                 │
│    root_cause     — the originating failure              │
│    symptom        — a downstream effect of root cause   │
│    contributing   — related but not causal              │
│                                                          │
│  Timeline Builder — chronological ordering of events    │
│  Incident Graph   — resource dependency graph           │
│                                                          │
│  Example: PVC pending (root) → pod pending (symptom)    │
│           → service no endpoints (contributing)         │
└────────────────────────┬────────────────────────────────┘
                         ▼
┌─────────────────────────────────────────────────────────┐
│  Layer 4 — Knowledge Base Search (54 patterns)           │
│                                                          │
│  Scores each pattern against detector evidence:          │
│    keyword overlap with events and log lines            │
│    log regex matching                                   │
│    metric threshold matches                             │
│    cloud provider boost (+0.15 for matching provider)   │
│                                                          │
│  Returns: top-N patterns with match scores              │
└────────────────────────┬────────────────────────────────┘
                         ▼
┌─────────────────────────────────────────────────────────┐
│  Layer 5 — Incident Memory Retrieval                     │
│                                                          │
│  Finds semantically similar past incidents:              │
│    TF-IDF vectors — fast lexical similarity             │
│    sentence-transformers (all-MiniLM-L6-v2) — semantic  │
│                                                          │
│  Similarity boosted by:                                  │
│    operator feedback (fix worked → boost)               │
│    recency (recent incidents weighted higher)           │
│    namespace proximity (same namespace = stronger hint) │
│                                                          │
│  Returns: top-K past incidents with similarity scores   │
└────────────────────────┬────────────────────────────────┘
                         ▼
┌─────────────────────────────────────────────────────────┐
│  Layer 6 — AI Reasoning Engine                           │
│                                                          │
│  Input to LLM:                                          │
│    detector results + correlated signals                │
│    top KB pattern matches with scores                   │
│    similar past incidents (with resolutions)            │
│    cluster context (provider, namespace, recent changes)│
│                                                          │
│  Output:                                                │
│    root_cause (structured natural language)             │
│    confidence (0.0–1.0)                                 │
│    recommended remediation steps                        │
│                                                          │
│  Providers: Anthropic Claude 3 · OpenAI GPT-4o          │
│  Fallback: rule-based (deterministic, no API key needed)│
└────────────────────────┬────────────────────────────────┘
                         ▼
┌─────────────────────────────────────────────────────────┐
│  Layer 7 — Remediation Controller + Feedback Loop        │
│                                                          │
│  Remediation Controller:                                │
│    classifies each step: L1 / L2 / L3                  │
│    checks: namespace policy · cooldown · dry-run flag   │
│    executes L1 (if enabled) · queues L2 for approval   │
│    presents L3 as commands for human action             │
│                                                          │
│  Feedback Loop (triggered by operator input):           │
│    RCA correct? → boost matched KB pattern confidence   │
│    Fix worked? → mark pattern as successful             │
│    Novel error → capture in learning store              │
│    Refit embeddings periodically                        │
└─────────────────────────────────────────────────────────┘
```

---

## Full System Diagram

```
┌─────────────────────────────────────────────────────────────────────────────────┐
│                              Kubernetes Cluster                                  │
│                                                                                  │
│  ┌────────────────────────────────────────────────────────────────────────────┐  │
│  │  APPLICATION PODS (optional sidecar)                                        │  │
│  │                                                                             │  │
│  │   ┌──────────────────┐    ┌────────────────────────────────────────────┐   │  │
│  │   │   App Container  │───▶│   AI SRE Sidecar Agent                     │   │  │
│  │   │   (any language) │    │   log_tailer · error_detector              │   │  │
│  │   └──────────────────┘    │   metrics_reporter · pattern_learner       │   │  │
│  │                           └────────────────┬───────────────────────────┘   │  │
│  └────────────────────────────────────────────┼───────────────────────────────┘  │
│                                               │ HTTP POST /api/v1/apm/ingest      │
│  ┌────────────────────────────────────────────▼───────────────────────────────┐  │
│  │  OPERATOR CORE                                                              │  │
│  │                                                                             │  │
│  │  ┌────────────────┐    ┌──────────────────────────────────────────────┐   │  │
│  │  │  K8s Watch     │───▶│  Detectors (18)                               │   │  │
│  │  │  Loop (30s)    │    │  CrashLoop · OOM · ImagePull · Pending · Probe│  │  │
│  │  └────────────────┘    │  Service · Ingress · PVC · HPA · DNS · RBAC  │   │  │
│  │                        │  NetPolicy · CNI · Mesh · NodePressure        │   │  │
│  │  ┌────────────────┐    │  Quota · Rollout · Storage                    │   │  │
│  │  │  Collectors    │───▶└──────────────────┬───────────────────────────┘   │  │
│  │  │  logs/events   │                       │                               │  │
│  │  │  metrics/APM   │                       ▼                               │  │
│  │  └────────────────┘    ┌──────────────────────────────────────────────┐   │  │
│  │                        │  Signal Correlator                             │   │  │
│  │                        │  root_cause · symptom · contributing_factor   │   │  │
│  │                        │  Timeline Builder · Incident Graph            │   │  │
│  │                        └──────────────────┬───────────────────────────┘   │  │
│  │                                           │                               │  │
│  │  ┌────────────────┐                       ▼                               │  │
│  │  │  Knowledge     │    ┌──────────────────────────────────────────────┐   │  │
│  │  │  Base (54)     │───▶│  AI RCA Engine                                │   │  │
│  │  │  Incident      │    │  KB matches + similar incidents + context     │   │  │
│  │  │  Memory        │    │  Anthropic / OpenAI / offline fallback        │   │  │
│  │  │  Feedback      │    └──────────────────┬───────────────────────────┘   │  │
│  │  └────────────────┘                       │                               │  │
│  │                                           ▼                               │  │
│  │                        ┌──────────────────────────────────────────────┐   │  │
│  │                        │  Remediation Controller                       │   │  │
│  │                        │  L1: auto-fix  L2: approval  L3: suggest     │   │  │
│  │                        │  Policy guardrails · Cooldown · Dry-run      │   │  │
│  │                        └──────────────────┬───────────────────────────┘   │  │
│  │                                           │                               │  │
│  │                        ┌──────────────────▼───────────────────────────┐   │  │
│  │                        │  Learning Store                                │   │  │
│  │                        │  Error capture · Embedding refit               │   │  │
│  │                        │  Pattern promotion · Confidence adjustment     │   │  │
│  │                        └──────────────────────────────────────────────┘   │  │
│  └────────────────────────────────────────────────────────────────────────────┘  │
└─────────────────────────────────────────────────────────────────────────────────┘
               ▲                       ▲                        ▲
          FastAPI REST             Streamlit UI             Click CLI
          (port 8000)              (port 8501)            (ai-sre ...)
         /docs Swagger
```

---

## APM Signal Flow

```
Application Container (any language)
    │  stdout/stderr → shared volume
    ▼
Sidecar Agent
    │
    ├── log_tailer.py
    │     Reads new lines from log file
    │     Detects file rotation (inode change / size decrease)
    │     Emits one line at a time to error_detector
    │
    ├── error_detector.py
    │     Matches line against 20+ compiled regex patterns
    │     Tracks per-pattern count in a 30s rolling window
    │     Returns DetectedPattern when threshold exceeded
    │
    ├── metrics_reporter.py
    │     Extracts latency from log lines (regex on "ms" / "seconds")
    │     Tracks P50/P95/P99 using bucketing algorithm
    │     Builds APMIngestReport every 30s
    │     HTTP POST to /api/v1/apm/ingest
    │     Buffers to /tmp/apm_buffer/*.json if API unreachable
    │
    └── pattern_learner.py
          Collects lines that contain error keywords but match no pattern
          Normalises: strips timestamps, UUIDs, numbers
          Tracks frequency counter
          HTTP POST top-20 to /api/v1/apm/learn every N cycles

Operator API — APM Ingest Handler
    │
    ├── Aggregates per-service state (error_rate, health_score, patterns)
    ├── Auto-creates Incident for critical/high severity patterns
    ├── Feeds novel errors to LearningLoop.capture_unknown_errors()
    └── Stores service health in _apm_reports (in-memory, survives restarts via SQLite)
```

---

## Data Flow — Single Incident Lifecycle

```
[Scan triggered, 09:00:00]
  K8s Watch Loop polls API server
  CrashLoopDetector: restart_count=18, state=CrashLoopBackOff
    → signals: [raw_signal(pod_restart), raw_signal(event_failed)]
    → severity: critical

[Correlation, 09:00:01]
  SignalCorrelator: classifies restart as root_cause
  TimelineBuilder: orders events chronologically
  ChangeCollector: finds deployment update 4m ago (added secretRef)
    → causal hint: configuration change before crash onset

[KB Search, 09:00:01]
  Scores k8s-001 (missing Secret): score=0.94
    → keyword match: "not found" in events + logs
    → log pattern match: "secret .* not found"
    → cloud provider: generic (no additional boost)

[Memory Retrieval, 09:00:02]
  TF-IDF nearest: inc-prev-023 (auth-service missing secret), similarity=0.91
  Feedback boost: +0.10 (fix_worked=true on previous)

[AI Analysis, 09:00:03]
  Method: anthropic claude-3-haiku
  Context: detector output + k8s-001 + inc-prev-023
  → root_cause: "Secret 'db-credentials' not found in 'production'..."
  → confidence: 0.97
  → remediation: [verify_secret, recreate_secret, verify_recovery]

[Remediation Plan, 09:00:03]
  verify_secret_missing → L1 (auto-fix eligible)
  recreate_secret       → L3 (suggest-only: cannot guess credential values)
  verify_recovery       → L1
  → overall plan: L3 (most restrictive step)

[Operator resolves at 09:08:00]
  Creates secret, pods recover
  Submits feedback: correct_root_cause=true, fix_worked=true
  → k8s-001 confidence boosted +0.10
  → incident stored in SQLite for future similarity retrieval
```

---

## Project Structure

```
ai-k8s-sre-operator/
│
├── ai/                         # AI reasoning engines
│   ├── llm.py                  # Anthropic/OpenAI client + rule-based fallback
│   ├── rca_engine.py           # Root cause analysis orchestrator
│   ├── remediation_engine.py   # Remediation plan generator
│   ├── incident_ranker.py      # Urgency-based incident ranking
│   └── prompts.py              # All LLM prompt templates
│
├── agent/                      # APM sidecar agent
│   ├── main.py                 # Entry point: log tail + detect + report loops
│   ├── config.py               # AgentConfig (all env vars)
│   ├── log_tailer.py           # File-based log tailing with rotation detection
│   ├── error_detector.py       # YAML-driven pattern matching engine
│   ├── metrics_reporter.py     # Latency tracking, APM report builder, buffer
│   ├── pattern_learner.py      # Novel error capture and normalisation
│   ├── Dockerfile              # Alpine Python 3.11, non-root, < 64Mi
│   └── patterns/
│       └── builtin.yaml        # 20+ built-in error patterns
│
├── api/
│   └── main.py                 # FastAPI: 29+ endpoints
│
├── collectors/                 # Signal collection
│   ├── k8s_watcher.py          # Cluster polling loop (30s default)
│   ├── logs_collector.py       # Pod log fetcher
│   ├── metrics_collector.py    # Prometheus query client
│   ├── events_collector.py     # K8s event aggregator
│   └── change_collector.py     # Deployment change tracker
│
├── correlation/                # Signal classification
│   ├── signal_correlator.py    # root_cause / symptom / contributing_factor
│   ├── timeline_builder.py     # Chronological event ordering
│   └── incident_graph.py       # Resource dependency graph
│
├── detectors/                  # 18 failure detectors
│   ├── base.py                 # BaseDetector interface
│   ├── crashloop_detector.py   # restart_count + CrashLoopBackOff state
│   ├── oomkill_detector.py     # OOMKilling events + memory metrics
│   ├── imagepull_detector.py   # ImagePullBackOff + ErrImagePull
│   ├── pending_pods_detector.py# FailedScheduling events
│   ├── probe_failure_detector.py # Liveness/readiness failures
│   ├── service_detector.py     # Selector mismatch + no endpoints
│   ├── ingress_detector.py     # Backend not found + 5xx from ingress
│   ├── pvc_detector.py         # PVC Pending + FailedMount
│   ├── hpa_detector.py         # HPA saturated / locked
│   ├── dns_detector.py         # CoreDNS NXDOMAIN + resolution failures
│   ├── rbac_detector.py        # Forbidden events + SA missing
│   ├── network_policy_detector.py # Blocked traffic patterns
│   ├── cni_detector.py         # IP exhaustion + CNI plugin failures
│   ├── service_mesh_detector.py # Istio/Linkerd mTLS + circuit breaker
│   ├── node_pressure_detector.py # Memory/CPU/disk pressure conditions
│   ├── quota_detector.py       # ResourceQuota exceeded
│   ├── rollout_detector.py     # ProgressDeadlineExceeded + stuck rollouts
│   └── storage_detector.py     # StorageClass missing + CSI errors
│
├── knowledge/                  # Knowledge base + learning
│   ├── failure_kb.py           # YAML loader + scoring + search engine
│   ├── embeddings.py           # TF-IDF + sentence-transformers
│   ├── retrieval.py            # Feedback-boosted similarity search
│   ├── incident_store.py       # SQLite persistence (SQLAlchemy)
│   ├── feedback_store.py       # Structured feedback + accuracy stats
│   ├── feedback_loop.py        # Learning loop orchestrator
│   ├── learning.py             # RAG context builder for LLM
│   └── failures/               # 54 YAML failure patterns
│       ├── generic_k8s.yaml    # 12 patterns
│       ├── eks.yaml            # 6 patterns
│       ├── aks.yaml            # 5 patterns
│       ├── gke.yaml            # 5 patterns
│       ├── networking.yaml     # 8 patterns
│       ├── storage.yaml        # 6 patterns
│       ├── security.yaml       # 5 patterns
│       ├── cluster.yaml        # 4 patterns
│       ├── application.yaml    # 3 patterns
│       └── learned.yaml        # Auto-promoted patterns (initially empty)
│
├── models/                     # Pydantic data models
│   ├── incident.py             # Incident, IncidentType, Severity, Evidence
│   ├── remediation.py          # RemediationPlan, RemediationStep
│   └── cluster_resource.py     # ClusterHealthSummary
│
├── policies/                   # Safety guardrails
│   ├── safety_levels.py        # 25 action → L1/L2/L3 mappings
│   ├── action_allowlist.py     # Permitted actions per namespace
│   └── namespace_policies.py  # Deny list enforcement
│
├── providers/                  # External system clients
│   ├── kubernetes.py           # Real K8s client + SimulatedK8s (demo mode)
│   │                           # Auto-detects cloud provider from node labels
│   ├── prometheus.py           # Prometheus HTTP query client
│   ├── loki.py                 # Loki LogQL client
│   └── opentelemetry.py        # OTEL metrics integration
│
├── remediations/               # 6 remediation executors
│   ├── policy_guardrails.py    # Pre-execution safety checks
│   ├── restart_pod.py          # kubectl delete pod
│   ├── rollout_restart.py      # kubectl rollout restart
│   ├── scale_deployment.py     # kubectl scale
│   ├── rollback_deployment.py  # kubectl rollout undo
│   ├── patch_resources.py      # kubectl patch (limits, selectors, probes)
│   └── rerun_job.py            # Delete + recreate Job
│
├── cli/
│   └── main.py                 # Click CLI
│
├── ui/
│   └── streamlit_app.py        # 8-tab Streamlit dashboard
│
├── tests/                      # 202 passing tests
├── helm/                       # Helm chart (14 templates)
├── examples/                   # Example incident JSON fixtures
├── docs/                       # 17 documentation files
└── agent/patterns/builtin.yaml # 20+ sidecar error patterns
```

---

## Component Counts

| Component | Count |
|---|---|
| Infrastructure detectors | 18 |
| Knowledge base patterns | 54 |
| Agent error patterns (builtin) | 20+ |
| API endpoints | 29 |
| Remediation executors | 6 |
| Safety action mappings | 25 |
| Helm chart templates | 14 |
| Dashboard tabs | 8 |
| Passing tests | 202 |
| Supported cloud providers | 4 (EKS, AKS, GKE, generic) |
