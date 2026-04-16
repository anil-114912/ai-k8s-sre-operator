# Application Performance Monitoring (APM)

The AI K8s SRE Operator extends beyond infrastructure monitoring to provide application-level observability through a lightweight **sidecar agent** that runs alongside your application containers.

This gives you capabilities similar to AppDynamics or Dynatrace — error rate tracking, latency analysis, exception detection, log pattern learning — without requiring any changes to your application code.

---

## How It Works

```
Your App Container (stdout/stderr)
         │
         ▼  shared /var/log volume
AI SRE Sidecar Agent
    ├── log_tailer.py      Reads new log lines in real time
    ├── error_detector.py  Matches lines against 20+ error patterns
    ├── metrics_reporter.py Aggregates and sends reports to operator
    └── pattern_learner.py  Captures novel patterns for the learning store
         │
         ▼  HTTP POST /api/v1/apm/ingest (every 30s)
Operator API
    ├── APM aggregator   Stores service health + error trends
    ├── Signal correlator Links app errors to K8s events
    └── AI RCA engine    Unified infrastructure + application root cause
```

The sidecar agent:
- Reads logs from stdout/stderr via a shared volume or the container log path
- Runs a 30-second report cycle (configurable)
- Buffers reports locally if the operator API is temporarily unavailable
- Uses < 50m CPU and < 64Mi memory
- Works with any language or framework (pattern-based, no SDK required)

---

## Detected Application Patterns

### Exceptions and Crashes

| Pattern | Languages | Example |
|---|---|---|
| Python traceback | Python | `Traceback (most recent call last):` |
| Java exception | Java | `java.lang.NullPointerException` |
| Go panic | Go | `panic: runtime error:` |
| Node.js uncaught | Node.js | `UnhandledPromiseRejectionWarning` |
| Ruby exception | Ruby | `RuntimeError (undefined method)` |
| Rust panic | Rust | `thread 'main' panicked at` |

### HTTP Errors

| Pattern | Trigger | Action |
|---|---|---|
| HTTP 5xx spike | > 5 errors in 30s | `APM_HTTP_ERROR` incident |
| HTTP 429 rate limit | > 10 errors in 30s | `APM_RATE_LIMITED` incident |
| Response timeout | `connection timed out` in logs | `APM_TIMEOUT` incident |
| Circuit breaker open | `circuit breaker open` in logs | `APM_CIRCUIT_OPEN` incident |

### Database Issues

| Pattern | Example Log Fragment | Incident Type |
|---|---|---|
| Connection pool exhausted | `connection pool exhausted`, `too many connections` | `APM_DB_POOL` |
| Slow query | `query took 3.2s`, `slow query` | `APM_SLOW_QUERY` |
| DB connection refused | `ECONNREFUSED`, `could not connect to server` | `APM_DB_CONNECT` |
| Deadlock | `deadlock detected`, `lock wait timeout` | `APM_DEADLOCK` |

### Memory and Resources

| Pattern | Example | Incident Type |
|---|---|---|
| Memory growing | Heap increasing monotonically over 10 reports | `APM_MEMORY_LEAK` |
| Out of memory | `java.lang.OutOfMemoryError`, `MemoryError` | `APM_OOM_APP` |
| File descriptor leak | `too many open files` | `APM_FD_LEAK` |
| Thread pool exhausted | `thread pool exhausted`, `executor rejected` | `APM_THREAD_POOL` |

### Auth and Config

| Pattern | Example | Incident Type |
|---|---|---|
| Auth failure | `401 Unauthorized`, `403 Forbidden` (repeated) | `APM_AUTH_FAIL` |
| Missing config | `env var not set`, `config key not found` | `APM_CONFIG_MISS` |
| Secret missing | `secret not found`, `key does not exist` | `APM_SECRET_MISS` |

---

## Service Health Score

Each service monitored by the sidecar gets a real-time health score (0–100):

```
Health Score = 100
  - (error_rate_pct × 2)          # error rate penalty
  - (p99_latency_over_threshold)   # latency penalty
  - (crash_count × 10)            # crash penalty
  + (fix_feedback_boost)          # positive feedback reward
```

| Score | Status | Colour |
|---|---|---|
| 90–100 | Healthy | Green |
| 70–89 | Degraded | Yellow |
| 50–69 | Warning | Orange |
| 0–49 | Critical | Red |

---

## APM API Endpoints

### Ingest (called by sidecar agent)

```
POST /api/v1/apm/ingest
Content-Type: application/json

{
  "pod_name": "payment-api-7d9f8b-xk2p9",
  "namespace": "production",
  "service_name": "payment-api",
  "report_window_secs": 30,
  "error_count": 12,
  "warning_count": 3,
  "total_lines": 450,
  "error_rate": 0.0267,
  "patterns_detected": [
    {
      "pattern_id": "http_5xx",
      "pattern_name": "HTTP 5xx errors",
      "count": 8,
      "sample": "ERROR 2026-04-16 POST /api/payment → 503 Service Unavailable",
      "severity": "high"
    }
  ],
  "metrics": {
    "latency_p50_ms": 45,
    "latency_p95_ms": 340,
    "latency_p99_ms": 1200,
    "requests_per_sec": 42.3,
    "active_connections": 18
  },
  "agent_version": "0.2.0"
}
```

### Query APM Data

```bash
# All services health overview
GET /api/v1/apm/services

# Single service details
GET /api/v1/apm/services/payment-api?namespace=production&window_mins=60

# Error pattern aggregation
GET /api/v1/apm/errors?namespace=production&severity=high

# APM incidents (created from application errors)
GET /api/v1/incidents?incident_type=APM_HTTP_ERROR
```

---

## Unified Incident View

When the sidecar detects a significant error pattern, it creates an incident in the operator's incident store — the same store used by the 18 infrastructure detectors. This means:

- **Unified dashboard**: see K8s and application incidents in the same list
- **Correlated RCA**: "Payment API is throwing 503s AND the underlying MySQL pod restarted 3 minutes ago"
- **Combined remediation plan**: restart the DB pod (K8s action) + suggest reviewing connection retry logic (application suggestion)
- **Single feedback loop**: operator feedback on APM incidents trains the same model

Example unified incident:

```json
{
  "title": "APM: payment-api — HTTP 5xx spike (8 errors in 30s)",
  "incident_type": "APM_HTTP_ERROR",
  "severity": "high",
  "namespace": "production",
  "workload": "payment-api",
  "evidence": [
    {"source": "apm_agent", "content": "8 HTTP 503 errors in last 30s"},
    {"source": "k8s_events", "content": "mysql-0 restarted 3m ago (CrashLoopBackOff)"},
    {"source": "knowledge_base", "content": "Pattern: DB connection pool exhausted"}
  ],
  "root_cause": "MySQL pod restarted causing connection pool to exhaust — application is not handling DB unavailability gracefully",
  "suggested_fix": "1. Fix MySQL CrashLoop (see k8s-001 pattern)  2. Add DB retry logic with exponential backoff in payment-api"
}
```

---

## Enabling APM

### Step 1: Deploy the operator

```bash
helm install ai-sre-operator ./helm/ai-k8s-sre-operator \
  --set cluster.provider=aws
```

### Step 2: Add the sidecar to your deployment

Option A — Manual sidecar:
```yaml
# Add to your deployment spec.template.spec.containers:
- name: ai-sre-agent
  image: ghcr.io/anil-114912/ai-k8s-sre-agent:latest
  env:
    - name: OPERATOR_API_URL
      value: http://ai-sre-operator.ai-sre.svc:8000
    - name: SERVICE_NAME
      value: my-app
    - name: POD_NAME
      valueFrom:
        fieldRef:
          fieldPath: metadata.name
    - name: POD_NAMESPACE
      valueFrom:
        fieldRef:
          fieldPath: metadata.namespace
```

Option B — Namespace-wide injection (add annotation to your deployment):
```yaml
metadata:
  annotations:
    ai-sre-operator/inject-agent: "true"
    ai-sre-operator/service-name: "my-app"
```

> **Note:** MutatingWebhookConfiguration auto-injection is on the [Phase 2 roadmap](roadmap.md). Manual sidecar is available now.

### Step 3: View APM data

```bash
# Port-forward the dashboard
kubectl port-forward svc/ai-sre-operator 8501:8501 -n ai-sre

# Open http://localhost:8501 → APM tab
```

---

## Customising Application Patterns

Add your application's specific error signatures to the agent's pattern config:

```yaml
# agent/patterns/custom.yaml
patterns:
  - id: myapp_payment_timeout
    name: "Payment gateway timeout"
    pattern: "payment gateway.*timeout|stripe.*connection refused"
    severity: high
    incident_type: APM_PAYMENT_TIMEOUT
    remediation_hint: "Check Stripe API status and network egress rules"

  - id: myapp_cache_miss_storm
    name: "Redis cache miss storm"
    pattern: "cache miss rate.*[89][0-9]%|MISS.*MISS.*MISS"
    severity: medium
    incident_type: APM_CACHE_STORM
    remediation_hint: "Review cache TTL and Redis eviction policy"
```

Mount this file via a ConfigMap and set `AGENT_CUSTOM_PATTERNS_PATH=/config/custom.yaml` on the sidecar container.

---

## Learning From Application Logs

The sidecar agent feeds novel error signatures back to the operator's learning store. Over time, the system builds a profile of your application's normal vs abnormal behaviour:

1. **Error capture**: agent detects a new error pattern not in the pre-built list
2. **Auto-record**: pattern is written to the `learned.yaml` KB file with low initial confidence
3. **Frequency tracking**: each recurrence increases confidence
4. **AI labelling**: if an LLM key is configured, the AI names and describes the pattern
5. **Promotion**: after N confirmed fixes, the pattern is promoted to the application KB
6. **Cross-service learning**: similar patterns across services are merged

See [Learning and Feedback](learning.md) for how the feedback loop works end-to-end.
