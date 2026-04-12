# Architecture

## Pipeline

Every incident flows through seven layers:

```
┌─────────────────────────────────────────────────────────┐
│  Layer 1 — Signal Collection                            │
│  K8s events · pod status · deployments · services       │
│  ingress · nodes · HPAs · PVCs · logs · metrics         │
└────────────────────────┬────────────────────────────────┘
                         ▼
┌─────────────────────────────────────────────────────────┐
│  Layer 2 — Deterministic Detection (18 detectors)       │
│  Each returns: type, resource, evidence, severity       │
└────────────────────────┬────────────────────────────────┘
                         ▼
┌─────────────────────────────────────────────────────────┐
│  Layer 3 — Signal Correlation                           │
│  root_cause · symptom · contributing_factor             │
│  Timeline builder · incident graph                      │
└────────────────────────┬────────────────────────────────┘
                         ▼
┌─────────────────────────────────────────────────────────┐
│  Layer 4 — Knowledge Base Search (45 patterns)          │
│  Regex + keyword scoring · provider-aware boost         │
└────────────────────────┬────────────────────────────────┘
                         ▼
┌─────────────────────────────────────────────────────────┐
│  Layer 5 — Incident Memory + Similarity Retrieval       │
│  TF-IDF / sentence-transformer embeddings               │
│  Feedback boost · recency decay · namespace proximity   │
└────────────────────────┬────────────────────────────────┘
                         ▼
┌─────────────────────────────────────────────────────────┐
│  Layer 6 — AI Reasoning Engine                          │
│  Detector results + KB matches + past incidents         │
│  Anthropic / OpenAI / rule-based fallback               │
│  Confidence adjusted by historical feedback             │
└────────────────────────┬────────────────────────────────┘
                         ▼
┌─────────────────────────────────────────────────────────┐
│  Layer 7 — Remediation + Feedback Loop                  │
│  3-tier safety · dry-run · namespace policy · cooldown  │
│  Operator feedback → learning loop → improved next time │
└─────────────────────────────────────────────────────────┘
```

## System Diagram

```
┌─────────────────────────────────────────────────────────────────────────┐
│                        Kubernetes Cluster                               │
│                                                                         │
│  ┌──────────────┐    ┌─────────────────────────────────────────────┐   │
│  │  K8s Watch   │───▶│           Detectors (18)                    │   │
│  │  Loop (30s)  │    │  CrashLoop · OOM · ImagePull · Pending     │   │
│  │              │    │  Probe · Service · Ingress · PVC · HPA     │   │
│  │              │    │  DNS · RBAC · NetPolicy · CNI · Mesh       │   │
│  │              │    │  NodePressure · Quota · Rollout · Storage   │   │
│  └──────────────┘    └──────────────────┬──────────────────────────┘   │
│                                         │                               │
│  ┌──────────────┐                       ▼                               │
│  │  Collectors  │    ┌─────────────────────────────────────────────┐   │
│  │  Logs        │───▶│         Signal Correlator                   │   │
│  │  Metrics     │    │  root_cause · symptom · contributing_factor │   │
│  │  Events      │    │  + Timeline Builder + Incident Graph        │   │
│  │  Changes     │    └──────────────────┬──────────────────────────┘   │
│  └──────────────┘                       │                               │
│                                         ▼                               │
│  ┌──────────────┐    ┌─────────────────────────────────────────────┐   │
│  │  Knowledge   │───▶│          AI RCA Engine                      │   │
│  │  Base (45)   │    │  KB matches + past incidents + cluster      │   │
│  │  + Incident  │    │  patterns → structured LLM reasoning        │   │
│  │  Memory      │    │  + rule-based fallback (demo mode)          │   │
│  │  + Feedback  │    └──────────────────┬──────────────────────────┘   │
│  └──────────────┘                       │                               │
│                                         ▼                               │
│                      ┌─────────────────────────────────────────────┐   │
│                      │      Remediation Controller                  │   │
│                      │  L1: auto_fix · L2: approval · L3: suggest  │   │
│                      │  Namespace policy · Cooldown · Dry-run      │   │
│                      └──────────────────┬──────────────────────────┘   │
│                                         │                               │
│                      ┌──────────────────▼──────────────────────────┐   │
│                      │       Feedback Loop + Learning Store         │   │
│                      │  Error capture · Refit · Promote · Adjust   │   │
│                      └─────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────────────────────────┘
         ▲                    ▲                      ▲
    FastAPI REST           Streamlit UI           Click CLI
    (port 8000)          (port 8501)           (ai-sre ...)
```

## Project Structure

```
ai-k8s-sre-operator/
├── ai/                     # AI reasoning engines
│   ├── llm.py                  # Anthropic/OpenAI + rule-based fallback
│   ├── rca_engine.py           # Root cause analysis orchestrator
│   ├── remediation_engine.py   # Remediation plan generator
│   ├── incident_ranker.py      # Urgency-based ranking
│   └── prompts.py              # All LLM prompt templates
├── collectors/             # Signal collection
│   ├── k8s_watcher.py          # Cluster polling loop
│   ├── logs_collector.py       # Pod log fetcher
│   ├── metrics_collector.py    # Prometheus metrics
│   ├── events_collector.py     # K8s event aggregator
│   └── change_collector.py     # Rollout change tracker
├── correlation/            # Signal classification
│   ├── signal_correlator.py    # Root cause / symptom / factor
│   ├── timeline_builder.py     # Chronological ordering
│   └── incident_graph.py       # Resource dependency graph
├── detectors/              # 18 failure detectors
├── knowledge/              # Knowledge base + learning
│   ├── failures/               # 45 YAML failure patterns
│   ├── failure_kb.py           # KB loader + search engine
│   ├── embeddings.py           # TF-IDF + sentence-transformer
│   ├── incident_store.py       # SQLite history (SQLAlchemy)
│   ├── retrieval.py            # Feedback-boosted similarity
│   ├── learning.py             # RAG context builder
│   ├── feedback_store.py       # Structured feedback + stats
│   └── feedback_loop.py        # Learning loop
├── models/                 # Pydantic data models
├── policies/               # Safety guardrails
├── providers/              # K8s, Prometheus, Loki, OTEL
├── remediations/           # 6 remediation executors
├── api/main.py             # FastAPI (30+ endpoints)
├── cli/main.py             # Click CLI
├── ui/streamlit_app.py     # Streamlit dashboard (7 tabs)
├── tests/                  # 202 tests
└── helm/                   # Helm chart
```
