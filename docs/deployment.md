# Deployment

Three deployment modes are supported depending on your environment and requirements.

---

## Mode 1 — Demo Mode

**Use case:** Evaluate the system without a real Kubernetes cluster or API key. All data is simulated. Safe for CI pipelines, presentations, and local exploration.

### What demo mode provides

- A simulated Kubernetes cluster with pre-configured workloads
- A set of injected incidents covering CrashLoopBackOff, OOMKill, pending pods, and service misconfigurations
- Fully functional AI analysis (rule-based, no LLM key required)
- All API endpoints respond with realistic data
- The Streamlit dashboard shows live-updating incident cards

### Start demo mode

```bash
git clone https://github.com/anil-114912/ai-k8s-sre-operator
cd ai-k8s-sre-operator
pip install -r requirements.txt
cp .env.example .env

# Terminal 1 — API
DEMO_MODE=1 make run-api

# Terminal 2 — Dashboard
make run-ui

# Terminal 3 — Inject demo incidents
make simulate
```

Open http://localhost:8501 — you will see a populated dashboard with incidents, RCA results, and remediation plans.

### With AI analysis in demo mode

```bash
# Edit .env and set your API key
ANTHROPIC_API_KEY=sk-ant-...
# or
OPENAI_API_KEY=sk-...

DEMO_MODE=1 make run-api
```

---

## Mode 2 — Real Cluster

**Use case:** Connect to an existing Kubernetes cluster (local Kind/Minikube or remote EKS/AKS/GKE). Reads live cluster state. Does not require an LLM key (falls back to rule-based analysis).

### Prerequisites

- `kubectl` configured with a valid context (`kubectl cluster-info` should succeed)
- Python 3.9+ and `pip install -r requirements.txt`
- Read access to pods, events, services, deployments, nodes (see RBAC section below)

### Start with real cluster

```bash
cp .env.example .env
# Set KUBECONFIG if not using default ~/.kube/config

make run-api    # Terminal 1 — connects to current kubectl context
make run-ui     # Terminal 2 — http://localhost:8501
```

### Trigger a scan

```bash
# Scan all namespaces
curl -X POST http://localhost:8000/api/v1/scan

# Scan specific namespace
curl -X POST "http://localhost:8000/api/v1/scan?namespace=production"
```

### With Prometheus

Edit `.env`:

```env
PROMETHEUS_URL=http://localhost:9090
```

Or port-forward Prometheus first:

```bash
kubectl port-forward svc/prometheus-server 9090:80 -n monitoring
```

---

## Mode 3 — Production (Helm in Kubernetes)

**Use case:** Run the operator inside your cluster where it can watch resources continuously without manual intervention.

### Prerequisites

- Helm 3.8+
- kubectl with cluster-admin or equivalent RBAC
- A storage class for the SQLite PVC (or PostgreSQL for production scale)
- An LLM API key (optional but recommended)

### Install

```bash
# Using the default values (safe, dry-run, demo mode off)
helm install ai-sre-operator ./helm/ai-k8s-sre-operator \
  --namespace ai-sre \
  --create-namespace

# EKS with AI analysis
helm install ai-sre-operator ./helm/ai-k8s-sre-operator \
  --namespace ai-sre \
  --create-namespace \
  --set cluster.provider=aws \
  --set llm.apiKey=$ANTHROPIC_API_KEY \
  --set persistence.storageClass=gp3 \
  --set operator.dryRun=true \
  --set operator.autoFixEnabled=false

# Using pre-built values files
helm install ai-sre-operator ./helm/ai-k8s-sre-operator \
  --namespace ai-sre \
  --create-namespace \
  --values helm/values-production.yaml \
  --set llm.apiKey=$ANTHROPIC_API_KEY
```

### Upgrade

```bash
helm upgrade ai-sre-operator ./helm/ai-k8s-sre-operator \
  --namespace ai-sre \
  --values helm/values-production.yaml \
  --set llm.apiKey=$ANTHROPIC_API_KEY
```

### Uninstall

```bash
helm uninstall ai-sre-operator --namespace ai-sre

# Delete the PVC (data will be lost — confirm before running)
kubectl delete pvc -n ai-sre -l app.kubernetes.io/instance=ai-sre-operator
```

### Verify deployment

```bash
# Check pods are running
kubectl get pods -n ai-sre

# Expected output:
# ai-sre-operator-api-6d7f9b-abc12    1/1   Running   0   2m
# ai-sre-operator-worker-5c8d7e-def34  1/1   Running   0   2m
# ai-sre-operator-watcher-4b9c6f-ghi56 1/1   Running   0   2m

# Check API is healthy
kubectl port-forward svc/ai-sre-operator 8000:8000 -n ai-sre &
curl http://localhost:8000/health

# Check logs for startup issues
kubectl logs -n ai-sre -l app.kubernetes.io/name=ai-sre-operator --tail=50

# Check the Streamlit dashboard
kubectl port-forward svc/ai-sre-operator-ui 8501:8501 -n ai-sre &
open http://localhost:8501
```

### Storage class guidance

The chart requires a PVC for SQLite persistence. Specify the correct storage class for your cluster:

| Cloud | StorageClass | Notes |
|---|---|---|
| EKS | `gp3` | AWS EBS gp3, recommended |
| AKS | `default` | Azure Disk, managed |
| GKE | `standard-rwo` | Google Persistent Disk |
| Kind/Minikube | `standard` | Local hostpath |
| Custom | your class name | `kubectl get storageclass` |

```bash
# Find available storage classes
kubectl get storageclass

# Set during install
--set persistence.storageClass=gp3
```

---

## RBAC

The Helm chart creates a `ClusterRole` and `ClusterRoleBinding` for the operator's `ServiceAccount`. All permissions are read-only by default. Write permissions are only used for executing approved remediations.

### Read permissions (always required)

| Resource | Verbs | Purpose |
|---|---|---|
| `pods`, `pods/log` | `get`, `list`, `watch` | Detect failures, collect evidence logs |
| `events` | `get`, `list`, `watch` | CrashLoop, scheduling, and probe failure evidence |
| `deployments`, `replicasets` | `get`, `list`, `watch` | Rollout failure detection, change tracking |
| `services`, `endpoints` | `get`, `list`, `watch` | Service selector mismatch detection |
| `nodes` | `get`, `list`, `watch` | Node pressure detection |
| `persistentvolumeclaims` | `get`, `list`, `watch` | PVC pending and mount failure detection |
| `namespaces`, `resourcequotas` | `get`, `list`, `watch` | Quota enforcement detection |
| `ingresses` | `get`, `list`, `watch` | Ingress backend detection |
| `horizontalpodautoscalers` | `get`, `list`, `watch` | HPA saturation detection |

### Write permissions (only used with AUTO_FIX_ENABLED=true)

| Resource | Verbs | Action | Safety Level |
|---|---|---|---|
| `pods` | `delete` | Pod restart | L1 auto-fix |
| `deployments` | `patch` | Rollout restart, resource patch | L1 or L2 |
| `deployments` | `patch` | Rollback (set image) | L2 approval-required |
| `services` | `patch` | Selector patch | L2 approval-required |
| `horizontalpodautoscalers` | `patch` | HPA bounds patch | L2 approval-required |
| `jobs` | `delete`, `create` | Job rerun | L1 auto-fix |

**The operator will never touch resources in `kube-system` or `kube-public` regardless of configuration.**

### Restricting to specific namespaces

To limit the operator to specific namespaces (e.g., `production` and `staging` only), use a `Role` + `RoleBinding` instead of `ClusterRole`. This is supported via Helm:

```bash
helm install ai-sre-operator ./helm/ai-k8s-sre-operator \
  --set rbac.clusterScoped=false \
  --set rbac.namespaces="{production,staging}"
```

---

## Configuration Reference

### Environment variables

| Variable | Default | Description |
|---|---|---|
| `DEMO_MODE` | `0` | Set to `1` for simulated cluster |
| `KUBECONFIG` | `~/.kube/config` | Path to kubeconfig |
| `ANTHROPIC_API_KEY` | — | Anthropic Claude API key |
| `OPENAI_API_KEY` | — | OpenAI API key |
| `OPERATOR_DRY_RUN` | `true` | Never mutate cluster without setting to `false` |
| `AUTO_FIX_ENABLED` | `false` | Enable L1 auto-fix remediations |
| `CLUSTER_PROVIDER` | auto-detect | Override: `aws`, `azure`, `gcp`, `generic` |
| `PROMETHEUS_URL` | — | Prometheus server URL for metrics |
| `WATCH_INTERVAL_SECS` | `30` | Cluster poll interval |
| `COOLDOWN_SECS` | `300` | Seconds between remediations of the same workload |
| `DB_URL` | `sqlite:///sre_operator.db` | SQLite or PostgreSQL URL |
| `LOG_LEVEL` | `INFO` | `DEBUG`, `INFO`, `WARNING`, `ERROR` |
| `DENIED_NAMESPACES` | `kube-system,kube-public` | Comma-separated namespace deny list |

### Pre-built Helm values files

| File | Use case |
|---|---|
| `helm/values-demo.yaml` | Demo mode: no cluster, simulated data, offline analysis |
| `helm/values-production.yaml` | Production: dry-run on, auto-fix off, LLM enabled, resource limits set |

---

## Production Hardening

### Use PostgreSQL instead of SQLite

For production deployments with more than one API replica, replace SQLite with PostgreSQL:

```bash
# Create the database
kubectl create secret generic sre-db-creds \
  --from-literal=url=postgresql://user:pass@postgres.production.svc:5432/sre \
  -n ai-sre

helm install ai-sre-operator ./helm/ai-k8s-sre-operator \
  --set database.type=postgres \
  --set database.existingSecret=sre-db-creds \
  --set persistence.enabled=false
```

### Store the LLM API key in a Secret

Never pass the API key directly on the command line in production:

```bash
kubectl create secret generic sre-llm-key \
  --from-literal=LLM_API_KEY=$ANTHROPIC_API_KEY \
  -n ai-sre

helm install ai-sre-operator ./helm/ai-k8s-sre-operator \
  --set llm.existingSecret=sre-llm-key
```

### Enable Prometheus monitoring

```bash
helm install ai-sre-operator ./helm/ai-k8s-sre-operator \
  --set serviceMonitor.enabled=true \
  --set prometheus.url=http://prometheus-server.monitoring.svc:9090
```

### Resource sizing

| Component | Minimum | Recommended |
|---|---|---|
| API | 100m CPU / 256Mi | 200m CPU / 512Mi |
| Worker | 200m CPU / 512Mi | 500m CPU / 1Gi |
| Watcher | 50m CPU / 128Mi | 100m CPU / 256Mi |

---

## Docker Compose (Local Stack)

```bash
docker-compose up -d
# API on :8000
# Dashboard on :8501
```

The compose file starts both the API server and Streamlit UI. Edit `docker-compose.yml` to add environment variables.

```bash
# Build the API image locally
docker build -t ai-k8s-sre-operator:local .

# Build the sidecar agent
docker build -t ai-k8s-sre-agent:local -f agent/Dockerfile .
```

---

## Observability Integration

### Prometheus

```env
PROMETHEUS_URL=http://prometheus-server.monitoring.svc:9090
```

When configured, the operator queries Prometheus for resource utilisation metrics that complement K8s event data (e.g., memory trend before OOMKill, CPU saturation before pending pods).

### Loki

```env
LOKI_URL=http://loki.monitoring.svc:3100
```

When configured, log queries use Loki's LogQL for richer pattern matching across pod log history.

### OpenTelemetry

The API emits traces and metrics when `OTEL_EXPORTER_OTLP_ENDPOINT` is set. Compatible with Grafana Tempo, Jaeger, and any OTLP-compatible collector.
