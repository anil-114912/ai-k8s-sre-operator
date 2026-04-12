# Deployment

## Local Development

```bash
pip install -r requirements.txt
cp .env.example .env
make run-api    # Terminal 1
make run-ui     # Terminal 2
```

## Docker

```bash
docker build -t ai-k8s-sre-operator .
docker-compose up -d
```

The docker-compose setup starts the API server and Streamlit dashboard.

## Helm (Kubernetes)

### Install

```bash
helm install ai-sre helm/ai-k8s-sre-operator \
  --namespace ai-sre --create-namespace
```

### With custom values

```bash
helm install ai-sre helm/ai-k8s-sre-operator \
  --namespace ai-sre --create-namespace \
  --set llm.provider=anthropic \
  --set llm.apiKey=$ANTHROPIC_API_KEY \
  --set operator.dryRun=false \
  --set operator.autoFixEnabled=true \
  --set prometheus.url=http://prometheus-server.monitoring.svc:9090 \
  --set persistence.size=10Gi
```

### What the chart includes

| Resource | Purpose |
|---|---|
| ServiceAccount | Identity for the operator pods |
| ClusterRole | Read access to pods, events, deployments, services, nodes, HPAs, PVCs, ingresses |
| ClusterRoleBinding | Binds ClusterRole to ServiceAccount |
| ConfigMap | Operator configuration |
| Secret | LLM API key storage |
| Deployment (api) | FastAPI server |
| Deployment (watcher) | K8s watch loop |
| Deployment (worker) | Background analysis worker |
| Service | Exposes API on port 8000 |
| PVC | Persistent storage for SQLite database |
| Ingress | Optional external access |
| ServiceMonitor | Prometheus scraping (if monitoring stack present) |

### Lint

```bash
make helm-lint
```
