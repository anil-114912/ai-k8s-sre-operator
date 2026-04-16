# Sidecar Agent

The AI SRE sidecar agent (`agent/`) runs as an additional container in your application pods. It monitors your application's logs in real time, detects error patterns, and reports to the operator API — enabling application-level observability without any changes to your application code.

---

## Architecture

```
Pod
├── app-container          Your application (unchanged)
│     └── stdout/stderr ──▶ shared log volume
└── ai-sre-agent           Sidecar
      ├── log_tailer.py     Reads new lines every 5s
      ├── error_detector.py Matches against 20+ patterns
      ├── metrics_reporter.py Aggregates + sends to API every 30s
      └── pattern_learner.py Captures novel error signatures
```

The sidecar reads logs via:
1. **Shared EmptyDir volume** — application writes to a file, sidecar reads it (preferred for structured log files)
2. **`/proc/{pid}/fd/1`** — attach to stdout of the app process directly (requires `shareProcessNamespace: true`)
3. **Kubernetes log path** — reads from `/var/log/pods/<namespace>_<pod>_<uid>/<container>/` (requires a hostPath volume)

---

## Quick Start

### 1. Add the sidecar to your deployment

```yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: payment-api
  namespace: production
spec:
  template:
    spec:
      # Option: share process namespace to allow log file access
      shareProcessNamespace: false

      containers:
        - name: payment-api
          image: myregistry/payment-api:v1.5.2
          # Redirect logs to a shared volume file:
          command: ["/bin/sh", "-c", "python app.py 2>&1 | tee /var/log/app/app.log"]
          volumeMounts:
            - name: app-logs
              mountPath: /var/log/app

        - name: ai-sre-agent
          image: ghcr.io/anil-114912/ai-k8s-sre-agent:latest
          env:
            - name: OPERATOR_API_URL
              value: "http://ai-sre-operator.ai-sre.svc:8000"
            - name: SERVICE_NAME
              value: "payment-api"
            - name: LOG_PATH
              value: "/var/log/app/app.log"
            - name: REPORT_INTERVAL_SECS
              value: "30"
            - name: POD_NAME
              valueFrom:
                fieldRef:
                  fieldPath: metadata.name
            - name: POD_NAMESPACE
              valueFrom:
                fieldRef:
                  fieldPath: metadata.namespace
          resources:
            requests:
              cpu: 10m
              memory: 32Mi
            limits:
              cpu: 50m
              memory: 64Mi
          volumeMounts:
            - name: app-logs
              mountPath: /var/log/app
              readOnly: true

      volumes:
        - name: app-logs
          emptyDir: {}
```

### 2. Verify the agent is running

```bash
kubectl logs -n production deployment/payment-api -c ai-sre-agent --tail=20
```

Expected output:
```
INFO  AI SRE Agent v0.2.0 starting
INFO  Service: payment-api | Namespace: production | Pod: payment-api-7d9f8b-xk2p9
INFO  Tailing log file: /var/log/app/app.log
INFO  Operator API: http://ai-sre-operator.ai-sre.svc:8000
INFO  Report interval: 30s
INFO  First report sent: 0 errors, 0 patterns, health=100
```

### 3. View APM data

```bash
# All services
curl http://localhost:8000/api/v1/apm/services | jq

# Specific service
curl "http://localhost:8000/api/v1/apm/services/payment-api?namespace=production" | jq

# Recent APM incidents
curl "http://localhost:8000/api/v1/incidents?incident_type=APM_HTTP_ERROR" | jq
```

---

## Configuration

All configuration is via environment variables on the sidecar container:

| Variable | Default | Description |
|---|---|---|
| `OPERATOR_API_URL` | `http://localhost:8000` | URL of the operator API |
| `SERVICE_NAME` | pod name | Logical service name for grouping |
| `LOG_PATH` | `/var/log/app/app.log` | Path to the application log file to tail |
| `LOG_PATHS` | — | Comma-separated list of log paths (for multi-file) |
| `REPORT_INTERVAL_SECS` | `30` | How often to send reports to the operator |
| `TAIL_LINES` | `1000` | How many recent lines to read on first start |
| `ERROR_THRESHOLD` | `5` | Error count per window to trigger an APM incident |
| `LATENCY_THRESHOLD_MS` | `1000` | Latency value (ms) in logs that counts as "slow" |
| `POD_NAME` | (from fieldRef) | Current pod name — use fieldRef |
| `POD_NAMESPACE` | (from fieldRef) | Current namespace — use fieldRef |
| `CUSTOM_PATTERNS_PATH` | — | Path to a custom patterns YAML file |
| `BUFFER_DIR` | `/tmp/apm_buffer` | Local buffer directory when API is unreachable |
| `MAX_BUFFER_REPORTS` | `20` | Max buffered reports before oldest are dropped |
| `LOG_LEVEL` | `INFO` | Agent log verbosity (DEBUG/INFO/WARNING) |

---

## Built-in Error Patterns

The agent ships with 20+ patterns in `agent/patterns/builtin.yaml`. They cover:

### Exceptions
```yaml
- id: python_traceback
  pattern: "Traceback \\(most recent call last\\)"
  languages: [python]
  severity: high

- id: java_exception
  pattern: "(java|javax|org|com)\\.[a-zA-Z.]+Exception"
  languages: [java, kotlin, scala]
  severity: high

- id: go_panic
  pattern: "panic: |goroutine \\d+ \\[running\\]"
  languages: [go]
  severity: critical

- id: nodejs_uncaught
  pattern: "UnhandledPromiseRejection|uncaughtException"
  languages: [nodejs, javascript, typescript]
  severity: high

- id: generic_fatal
  pattern: "FATAL|fatal error|panic:|segmentation fault"
  languages: [all]
  severity: critical
```

### HTTP Errors
```yaml
- id: http_5xx
  pattern: "(500|502|503|504|505) (Internal|Bad|Service|Gateway)"
  severity: high
  count_threshold: 5
  window_secs: 30

- id: http_429
  pattern: "429 Too Many Requests|rate limit exceeded"
  severity: medium
  count_threshold: 10

- id: connection_refused
  pattern: "ECONNREFUSED|connection refused|Connection refused"
  severity: high
```

### Database
```yaml
- id: db_pool_exhausted
  pattern: "connection pool exhausted|too many connections|max_connections"
  severity: critical

- id: db_slow_query
  pattern: "slow query|query took [0-9]+\\.[0-9]+s|execution time: [0-9]+"
  latency_threshold_ms: 1000
  severity: medium

- id: db_deadlock
  pattern: "deadlock detected|lock wait timeout exceeded|Deadlock found"
  severity: high

- id: db_connection_failed
  pattern: "could not connect to server|FATAL.*database|OperationalError.*connect"
  severity: critical
```

### Memory
```yaml
- id: oom_error
  pattern: "OutOfMemoryError|MemoryError|cannot allocate memory"
  severity: critical

- id: memory_leak_signal
  pattern: "heap growing|memory usage.*[89][0-9]%|GC overhead limit"
  severity: medium
  track_trend: true
```

---

## Custom Patterns

Create a YAML file and mount it via ConfigMap:

```yaml
# my-app-patterns.yaml
patterns:
  - id: payment_gateway_timeout
    name: "Payment gateway timeout"
    pattern: "stripe.*timeout|payment.*connection.*refused"
    severity: high
    incident_type: APM_PAYMENT_TIMEOUT
    remediation_hint: "Check Stripe API status page and outbound egress rules"

  - id: auth_token_expired
    name: "Auth token expiry spike"
    pattern: "token.*expired|JWT.*invalid|401.*token"
    severity: medium
    count_threshold: 10
    window_secs: 60
    incident_type: APM_AUTH_EXPIRE
    remediation_hint: "Check token refresh logic and clock skew between services"

  - id: queue_backlog
    name: "Message queue consumer backlog"
    pattern: "consumer lag.*[0-9]{4,}|queue depth.*[0-9]{4,}"
    severity: medium
    incident_type: APM_QUEUE_BACKLOG
    remediation_hint: "Scale up consumer deployment or check for slow message processing"
```

Apply via ConfigMap:

```bash
kubectl create configmap apm-custom-patterns \
  --from-file=custom.yaml=my-app-patterns.yaml \
  -n production
```

Mount in the sidecar:
```yaml
env:
  - name: CUSTOM_PATTERNS_PATH
    value: /config/custom.yaml
volumeMounts:
  - name: custom-patterns
    mountPath: /config
volumes:
  - name: custom-patterns
    configMap:
      name: apm-custom-patterns
```

---

## Building the Agent Image

```bash
# Build
docker build -f agent/Dockerfile -t ghcr.io/anil-114912/ai-k8s-sre-agent:latest .

# Test locally against a log file
docker run --rm \
  -e OPERATOR_API_URL=http://host.docker.internal:8000 \
  -e SERVICE_NAME=test-service \
  -e LOG_PATH=/logs/app.log \
  -v /path/to/logs:/logs:ro \
  ghcr.io/anil-114912/ai-k8s-sre-agent:latest
```

---

## Agent Resource Usage

The agent is designed to be minimal:

| Resource | Idle | Under load (100 errors/s) |
|---|---|---|
| CPU | ~2m | ~30m |
| Memory | ~28Mi | ~50Mi |
| Network | ~1 KB/30s | ~5 KB/30s |
| Disk | ~2 MB (buffer) | ~10 MB (buffer) |

These are well within the default limits (`50m` CPU / `64Mi` memory).

---

## Offline Buffer

If the operator API is unreachable, reports are buffered locally:

```
/tmp/apm_buffer/
├── report_1713282000.json
├── report_1713282030.json
└── report_1713282060.json
```

When the API comes back online, buffered reports are flushed in order. Old reports beyond `MAX_BUFFER_REPORTS` (default 20) are dropped.

---

## Troubleshooting

**Agent not sending reports:**
```bash
kubectl logs <pod> -c ai-sre-agent | grep -E "ERROR|WARNING|report"
```

**Log file not found:**
- Verify the log path matches what your app writes to
- Check that both containers mount the same volume at the same path
- Try `kubectl exec <pod> -c ai-sre-agent -- ls -la /var/log/app/`

**Operator API unreachable:**
```bash
kubectl exec <pod> -c ai-sre-agent -- curl -sf $OPERATOR_API_URL/health
```

**Too many false-positive incidents:**
- Increase `ERROR_THRESHOLD` (default 5) for noisy services
- Add the noisy pattern to an ignore list via `IGNORE_PATTERNS=pattern1,pattern2`
- Adjust `REPORT_INTERVAL_SECS` to a longer window

**Agent using too much CPU:**
- Increase `REPORT_INTERVAL_SECS` (e.g., 60)
- Reduce `TAIL_LINES` for very high-volume log files
- Disable `track_trend: true` patterns for busy services
