# AI K8s SRE Operator

An in-cluster AI SRE platform for Kubernetes. Detects failures, explains root cause, suggests remediation, and learns from operator feedback.

Works across EKS, AKS, GKE, and self-hosted clusters. Runs fully offline in demo mode — no API key required.

![Python](https://img.shields.io/badge/Python-3.9+-blue?logo=python)
![FastAPI](https://img.shields.io/badge/FastAPI-0.111-green?logo=fastapi)
![Kubernetes](https://img.shields.io/badge/Kubernetes-1.28+-326CE5?logo=kubernetes)
![Tests](https://img.shields.io/badge/Tests-202%20passing-brightgreen)
![Detectors](https://img.shields.io/badge/Detectors-18-orange)
![KB Patterns](https://img.shields.io/badge/Knowledge%20Base-45%20patterns-cyan)
![License](https://img.shields.io/badge/License-MIT-yellow)

---

## Quick Start

```bash
git clone https://github.com/anil-114912/ai-k8s-sre-operator
cd ai-k8s-sre-operator
pip install -r requirements.txt
cp .env.example .env
```

### Running the API + Dashboard

The system has two services that must run together:

- **API server** (FastAPI) — the backend that runs detectors, AI analysis, stores incidents, handles feedback
- **Dashboard** (Streamlit) — the frontend UI that calls the API for everything

The dashboard does not work without the API. Start them in order:

```bash
# Terminal 1 — Start the API first
make run-api
# Wait until you see: Uvicorn running on http://0.0.0.0:8000

# Terminal 2 — Then start the dashboard
make run-ui
# Opens at http://localhost:8501
```

- API + Swagger docs: http://localhost:8000/docs
- Dashboard: http://localhost:8501

If you see `API error: Connection refused` in the dashboard, the API server is not running.

### Simulate an incident

```bash
# Terminal 3 — requires API running
make simulate
```

### Offline mode (no API server needed)

Runs the full pipeline locally — detection, correlation, AI analysis, remediation — without the API or dashboard:

```bash
DEMO_MODE=1 python3 -m cli.main simulate --type crashloop --demo
```

### With AI (optional)

The system works fully without any LLM API key (rule-based fallback). To enable AI-powered analysis:

```bash
# Edit .env and set ANTHROPIC_API_KEY or OPENAI_API_KEY
# Then:
DEMO_MODE=0 make run-api
```

---

## What It Does

```
Cluster → 18 Detectors → Signal Correlation → Knowledge Base (45 patterns)
  → Incident Memory → AI Reasoning → Remediation Plan → Feedback → Learning
```

1. Watches the cluster every 30 seconds
2. Runs 18 detectors to find failures
3. Correlates signals into root cause / symptom / contributing factor
4. Searches 45 failure patterns across EKS, AKS, GKE, networking, security, storage
5. Retrieves similar past incidents with feedback-boosted scoring
6. AI generates root cause analysis grounded in evidence
7. Produces a remediation plan with 3-tier safety levels
8. Operator feedback improves future analysis

---

## Documentation

| Document | Description |
|---|---|
| [Architecture](docs/architecture.md) | System design, pipeline layers, project structure |
| [Detectors](docs/detectors.md) | All 18 detectors with what they detect |
| [Knowledge Base](docs/knowledge-base.md) | 45 failure patterns, YAML format, search engine |
| [Learning and Feedback](docs/learning.md) | How the system learns: error capture, refit, promotion, confidence |
| [Safety Model](docs/safety.md) | 3-tier safety levels, guardrails, namespace policies |
| [API Reference](docs/api.md) | All REST endpoints with examples |
| [CLI Reference](docs/cli.md) | All CLI commands |
| [Dashboard](docs/dashboard.md) | 7 UI tabs and how to use them |
| [Configuration](docs/configuration.md) | Environment variables and settings |
| [Deployment](docs/deployment.md) | Docker, Helm, production setup |
| [Testing](docs/testing.md) | 202 tests, how to run, coverage by area |
| [Supported Platforms](docs/platforms.md) | EKS, AKS, GKE, Cilium, Istio, CSI |

---

## At a Glance

| Component | Count |
|---|---|
| Detectors | 18 |
| Knowledge base patterns | 45 |
| Incident types | 19 |
| Safety action mappings | 25 |
| API endpoints | 30+ |
| Dashboard tabs | 7 |
| Tests | 202 |

---

## License

MIT — Copyright 2025 Anil Thotakura. See [LICENSE](LICENSE).
