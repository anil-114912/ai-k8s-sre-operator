# Configuration

All settings are controlled via environment variables. Copy `.env.example` to `.env` and edit as needed.

## Environment Variables

| Variable | Default | Description |
|---|---|---|
| DEMO_MODE | 1 | 1 = simulated cluster + rule-based AI. 0 = real cluster + LLM |
| LLM_PROVIDER | anthropic | LLM provider: `anthropic` or `openai` |
| ANTHROPIC_API_KEY | | Anthropic API key. Leave empty for demo mode |
| OPENAI_API_KEY | | OpenAI API key. Leave empty for demo mode |
| DATABASE_URL | sqlite:///./sre_operator.db | SQLAlchemy database URL |
| PROMETHEUS_URL | http://localhost:9090 | Prometheus server URL |
| LOKI_URL | | Grafana Loki URL. Leave empty to disable |
| OTEL_EXPORTER_OTLP_ENDPOINT | | OpenTelemetry endpoint. Leave empty to disable |
| OPERATOR_DRY_RUN | true | true = simulate remediations. false = real execution |
| AUTO_FIX_ENABLED | false | true = allow L1 actions to auto-execute |
| DENIED_NAMESPACES | kube-system,kube-public | Comma-separated namespaces blocked from remediation |
| ALLOWED_NAMESPACES | | Comma-separated allowlist. Empty = all allowed |
| COOLDOWN_SECS | 300 | Seconds between remediations on same workload |
| WATCH_INTERVAL_SECS | 30 | Cluster polling interval in seconds |
| LOG_LEVEL | INFO | Python logging level |
| API_BASE_URL | http://localhost:8000 | API URL used by CLI and UI |
| KUBECONFIG | ~/.kube/config | Path to kubeconfig file |
| K8S_NAMESPACE | default | Default namespace for operations |

## Modes

### Demo mode (default)

No cluster connection, no API key. Uses simulated cluster state with baked-in incidents and rule-based AI responses.

```bash
DEMO_MODE=1 make run-api
```

### Real cluster + rule-based AI

Connects to a real cluster via kubeconfig but uses rule-based analysis (no LLM cost).

```bash
DEMO_MODE=0 make run-api
```

### Real cluster + LLM

Full pipeline with real cluster and AI-powered analysis.

```bash
DEMO_MODE=0 ANTHROPIC_API_KEY=sk-ant-... make run-api
```

### Production

```bash
DEMO_MODE=0
OPERATOR_DRY_RUN=false
AUTO_FIX_ENABLED=true
ANTHROPIC_API_KEY=sk-ant-...
DATABASE_URL=postgresql://user:pass@host:5432/sre_operator
PROMETHEUS_URL=http://prometheus-server.monitoring.svc:9090
```
