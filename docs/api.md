# API Reference

FastAPI REST API running on port 8000. Interactive Swagger docs available at `http://localhost:8000/docs`.

All endpoints return JSON. Errors follow RFC 7807 (`detail` field with a human-readable message).

---

## Endpoint Summary

| Category | Method | Path | Description |
|---|---|---|---|
| Health | GET | /health | System health and mode |
| Incidents | POST | /api/v1/incidents | Create incident |
| Incidents | GET | /api/v1/incidents | List incidents |
| Incidents | GET | /api/v1/incidents/{id} | Get incident details |
| Incidents | POST | /api/v1/incidents/{id}/analyze | Run AI RCA pipeline |
| Incidents | GET | /api/v1/incidents/{id}/similar | Find similar past incidents |
| Remediation | GET | /api/v1/incidents/{id}/remediation | Get or generate plan |
| Remediation | POST | /api/v1/incidents/{id}/remediation/execute | Execute plan |
| Remediation | POST | /api/v1/incidents/{id}/remediation/approve | Approve L2 plan |
| Cluster | POST | /api/v1/scan | Trigger cluster scan |
| Cluster | GET | /api/v1/cluster/summary | Cluster health overview |
| Cluster | GET | /api/v1/cluster/patterns | Recurring failure types |
| Knowledge | GET | /api/v1/knowledge/failures | List KB patterns |
| Knowledge | GET | /api/v1/knowledge/failures/{id} | Get pattern by ID |
| Knowledge | GET | /api/v1/knowledge/search | Search KB |
| Feedback | POST | /api/v1/feedback | Basic feedback |
| Feedback | POST | /api/v1/feedback/structured | Structured feedback |
| Stats | GET | /api/v1/stats/accuracy | RCA accuracy stats |
| Stats | GET | /api/v1/stats/learning | Learning system stats |
| APM | POST | /api/v1/apm/ingest | Receive agent report |
| APM | GET | /api/v1/apm/services | List APM services |
| APM | GET | /api/v1/apm/services/{name} | Per-service APM detail |
| APM | GET | /api/v1/apm/errors | Aggregated error patterns |
| APM | POST | /api/v1/apm/learn | Submit novel error lines |
| Debug | GET | /api/v1/debug/provider | K8s provider info |
| Debug | GET | /api/v1/debug/llm | LLM provider status |

---

## Health

### `GET /health`

Returns system status, version, and operating mode.

**Request:**

```bash
curl http://localhost:8000/health
```

**Response:**

```json
{
  "status": "ok",
  "version": "0.2.0",
  "demo_mode": true,
  "cluster_provider": "generic",
  "llm_provider": "rule-based",
  "db": "sqlite",
  "uptime_seconds": 347
}
```

**Field notes:**
- `demo_mode: true` means the system is using a simulated cluster — no real K8s connection
- `llm_provider` is `rule-based` when no API key is configured (still fully functional, uses deterministic rules)
- `cluster_provider` is `aws`, `azure`, `gcp`, or `generic`

---

## Incidents

### `POST /api/v1/incidents`

Create an incident manually (also used by the scan loop to ingest detected incidents).

**Request:**

```bash
curl -X POST http://localhost:8000/api/v1/incidents \
  -H "Content-Type: application/json" \
  -d @examples/crashloop_missing_secret.json
```

```json
{
  "title": "CrashLoopBackOff: payment-api (missing secret)",
  "incident_type": "CrashLoopBackOff",
  "severity": "critical",
  "namespace": "production",
  "workload": "payment-api",
  "pod_name": "payment-api-7d9f8b-xk2p9",
  "raw_signals": {
    "restart_count": 18,
    "events": [
      { "reason": "Failed", "message": "Error: secret \"db-credentials\" not found" }
    ],
    "recent_logs": [
      "ERROR Failed to load config: secret 'db-credentials' not found"
    ]
  }
}
```

**Response:**

```json
{
  "id": "inc-a3f9b1c2",
  "title": "CrashLoopBackOff: payment-api (missing secret)",
  "incident_type": "CrashLoopBackOff",
  "severity": "critical",
  "status": "open",
  "namespace": "production",
  "workload": "payment-api",
  "detected_at": "2024-01-15T09:24:00Z",
  "root_cause": null,
  "confidence": null
}
```

---

### `GET /api/v1/incidents`

List incidents with optional filters.

**Query parameters:**

| Parameter | Type | Default | Description |
|---|---|---|---|
| `severity` | string | — | Filter: `critical`, `high`, `medium`, `low` |
| `status` | string | — | Filter: `open`, `analyzing`, `resolved`, `closed` |
| `namespace` | string | — | Filter by namespace |
| `limit` | int | 20 | Max results (max 100) |

**Request:**

```bash
curl "http://localhost:8000/api/v1/incidents?severity=critical&status=open&limit=5"
```

**Response:**

```json
[
  {
    "id": "inc-a3f9b1c2",
    "title": "CrashLoopBackOff: payment-api (missing secret)",
    "severity": "critical",
    "status": "open",
    "namespace": "production",
    "workload": "payment-api",
    "detected_at": "2024-01-15T09:24:00Z",
    "confidence": 0.97,
    "root_cause": "Pod references Secret 'db-credentials' which does not exist in namespace 'production'."
  }
]
```

---

### `POST /api/v1/incidents/{id}/analyze`

Run the full AI analysis pipeline on an incident. This is the core operation — it runs KB search, incident memory retrieval, and LLM reasoning.

**Request:**

```bash
curl -X POST http://localhost:8000/api/v1/incidents/inc-a3f9b1c2/analyze
```

**Response:**

```json
{
  "incident_id": "inc-a3f9b1c2",
  "root_cause": "The payment-api deployment references a Kubernetes Secret named 'db-credentials' in the 'production' namespace that does not exist. The deployment was updated 4 minutes ago to add this secretRef. Every pod crashes immediately on startup and enters CrashLoopBackOff.",
  "confidence": 0.97,
  "analysis_method": "llm",
  "kb_patterns_matched": [
    {
      "id": "k8s-001",
      "title": "CrashLoopBackOff — missing Secret",
      "match_score": 0.94,
      "provider": "generic"
    }
  ],
  "similar_incidents": [
    {
      "id": "inc-prev-023",
      "title": "CrashLoopBackOff: auth-service (missing secret)",
      "namespace": "staging",
      "resolved_at": "2024-01-10T14:22:00Z",
      "fix_worked": true
    }
  ],
  "remediation_hint": "Create the missing secret: kubectl create secret generic db-credentials -n production",
  "analyzed_at": "2024-01-15T09:24:30Z"
}
```

**Notes:**
- `analysis_method` is `llm` (Anthropic/OpenAI), `rule-based` (offline fallback), or `kb-only` (no LLM configured, using KB patterns only)
- Analysis is cached — subsequent calls return the cached result unless the incident was updated

---

### `GET /api/v1/incidents/{id}/similar`

Find semantically similar past incidents using TF-IDF + sentence-transformer embeddings.

**Request:**

```bash
curl "http://localhost:8000/api/v1/incidents/inc-a3f9b1c2/similar?top_k=3"
```

**Response:**

```json
[
  {
    "id": "inc-prev-023",
    "title": "CrashLoopBackOff: auth-service (missing secret)",
    "similarity_score": 0.91,
    "namespace": "staging",
    "workload": "auth-service",
    "root_cause": "Secret 'jwt-signing-key' not found in staging namespace",
    "fix_worked": true,
    "feedback_boost": 0.1
  },
  {
    "id": "inc-prev-047",
    "title": "CrashLoopBackOff: notification-api (missing configmap)",
    "similarity_score": 0.72,
    "namespace": "production",
    "workload": "notification-api",
    "root_cause": "ConfigMap 'smtp-config' deleted during namespace cleanup",
    "fix_worked": true,
    "feedback_boost": 0.1
  }
]
```

---

## Remediation

### `GET /api/v1/incidents/{id}/remediation`

Get the remediation plan for an incident. If no plan exists, one is generated.

**Request:**

```bash
curl http://localhost:8000/api/v1/incidents/inc-a3f9b1c2/remediation
```

**Response:**

```json
{
  "plan_id": "plan-7c2d4e8f",
  "incident_id": "inc-a3f9b1c2",
  "safety_level": "suggest_only",
  "requires_approval": false,
  "dry_run": true,
  "status": "pending",
  "steps": [
    {
      "order": 1,
      "action": "verify_secret_missing",
      "description": "Confirm the secret does not exist",
      "command": "kubectl get secret db-credentials -n production",
      "safety_level": "auto_fix",
      "expected_output": "Error from server (NotFound)"
    },
    {
      "order": 2,
      "action": "recreate_secret",
      "description": "Create the missing secret with required keys",
      "command": "kubectl create secret generic db-credentials --from-literal=KEY=value -n production",
      "safety_level": "suggest_only",
      "note": "Replace KEY=value with actual credential values — this step cannot be automated"
    },
    {
      "order": 3,
      "action": "verify_recovery",
      "description": "Confirm the deployment recovers",
      "command": "kubectl rollout status deployment/payment-api -n production",
      "safety_level": "auto_fix"
    }
  ],
  "generated_at": "2024-01-15T09:24:35Z"
}
```

---

### `POST /api/v1/incidents/{id}/remediation/execute`

Execute the remediation plan. Dry-run by default.

**Query parameters:**

| Parameter | Type | Default | Description |
|---|---|---|---|
| `dry_run` | bool | `true` | If false, executes real kubectl commands |

**Request (dry run):**

```bash
curl -X POST "http://localhost:8000/api/v1/incidents/inc-a3f9b1c2/remediation/execute?dry_run=true"
```

**Response:**

```json
{
  "plan_id": "plan-7c2d4e8f",
  "dry_run": true,
  "executed_steps": [
    "verify_secret_missing",
    "verify_recovery"
  ],
  "skipped_steps": [
    { "action": "recreate_secret", "reason": "safety_level=suggest_only — cannot auto-execute" }
  ],
  "outcome": "[DRY RUN] Would verify secret absence in production namespace\n[SKIPPED] recreate_secret — suggest_only\n[DRY RUN] Would check rollout status for payment-api"
}
```

**Request (live execution — requires AUTO_FIX_ENABLED=true and dry_run=false):**

```bash
curl -X POST "http://localhost:8000/api/v1/incidents/inc-a3f9b1c2/remediation/execute?dry_run=false"
```

**Response:**

```json
{
  "plan_id": "plan-7c2d4e8f",
  "dry_run": false,
  "executed_steps": ["verify_secret_missing"],
  "skipped_steps": [
    { "action": "recreate_secret", "reason": "safety_level=suggest_only" }
  ],
  "blocked_steps": [],
  "outcome": "Step 1: kubectl get secret db-credentials -n production\nError from server (NotFound): secrets \"db-credentials\" not found\nStep 3: Skipped — prerequisite step 2 not completed"
}
```

---

### `POST /api/v1/incidents/{id}/remediation/approve`

Approve a Level 2 (approval-required) plan for execution.

**Request:**

```bash
curl -X POST http://localhost:8000/api/v1/incidents/inc-b8c4d2/remediation/approve \
  -H "Content-Type: application/json" \
  -d '{"approved_by": "ops-engineer@company.com", "note": "Verified memory metrics — safe to increase limit"}'
```

**Response:**

```json
{
  "plan_id": "plan-9d3e5f",
  "status": "approved",
  "approved_by": "ops-engineer@company.com",
  "approved_at": "2024-01-15T09:35:00Z"
}
```

---

## Cluster

### `POST /api/v1/scan`

Trigger an on-demand cluster scan using all 18 detectors.

**Query parameters:**

| Parameter | Type | Default | Description |
|---|---|---|---|
| `namespace` | string | — | Scan specific namespace only |

**Request:**

```bash
curl -X POST "http://localhost:8000/api/v1/scan?namespace=production"
```

**Response:**

```json
{
  "scan_id": "scan-20240115-092500",
  "namespace": "production",
  "duration_ms": 1234,
  "incidents_detected": 2,
  "incidents": [
    {
      "id": "inc-a3f9b1c2",
      "title": "CrashLoopBackOff: payment-api (missing secret)",
      "severity": "critical",
      "detector": "CrashLoopDetector",
      "namespace": "production",
      "workload": "payment-api"
    },
    {
      "id": "inc-c7e2d4f1",
      "title": "Service has no endpoints: checkout-api",
      "severity": "high",
      "detector": "ServiceMismatchDetector",
      "namespace": "production",
      "workload": "checkout-api"
    }
  ],
  "detectors_run": 18,
  "detectors_with_findings": 2
}
```

---

### `GET /api/v1/cluster/summary`

Overall cluster health with key metrics.

**Request:**

```bash
curl http://localhost:8000/api/v1/cluster/summary
```

**Response:**

```json
{
  "health_score": 74,
  "provider": "aws",
  "node_count": 6,
  "nodes_ready": 4,
  "pod_count": 87,
  "pods_running": 79,
  "pods_pending": 6,
  "pods_failed": 2,
  "open_incidents": 3,
  "critical_incidents": 1,
  "namespaces_affected": ["production", "staging"],
  "top_incident_types": [
    { "type": "CrashLoopBackOff", "count": 2 },
    { "type": "PodPending", "count": 6 }
  ],
  "last_scan": "2024-01-15T09:25:00Z"
}
```

---

## Knowledge Base

### `GET /api/v1/knowledge/search`

Full-text search over the 54 KB patterns. Boosts results matching the detected cloud provider.

**Query parameters:**

| Parameter | Type | Default | Description |
|---|---|---|---|
| `q` | string | required | Search query |
| `provider` | string | — | Boost provider patterns: `aws`, `azure`, `gcp` |
| `top_k` | int | 5 | Number of results |

**Request:**

```bash
curl "http://localhost:8000/api/v1/knowledge/search?q=connection+pool+exhausted+database&provider=aws&top_k=3"
```

**Response:**

```json
[
  {
    "id": "app-001",
    "title": "Application — database connection pool exhausted",
    "score": 0.89,
    "scope": "pod",
    "tags": ["application", "database", "connection-pool"],
    "root_cause": "The application's database connection pool is fully saturated...",
    "remediation_steps": [
      "Check current connection count: SELECT count(*) FROM pg_stat_activity WHERE datname='<db>'",
      "Identify long-running queries: SELECT pid, query, query_start FROM pg_stat_activity ORDER BY query_start",
      "Kill blocking queries if safe: SELECT pg_terminate_backend(<pid>)"
    ],
    "safe_auto_fix": false,
    "safety_level": "suggest_only"
  },
  {
    "id": "k8s-003",
    "title": "CrashLoopBackOff — OOMKill",
    "score": 0.54,
    "scope": "pod",
    "tags": ["crashloop", "memory", "oom"],
    "root_cause": "The container exceeds its memory limit and is killed by the OOM killer..."
  }
]
```

---

### `GET /api/v1/knowledge/failures/{id}`

Get a single KB pattern by ID.

**Request:**

```bash
curl http://localhost:8000/api/v1/knowledge/failures/eks-002
```

**Response:**

```json
{
  "id": "eks-002",
  "title": "EKS — IAM IRSA pod identity missing or misconfigured",
  "scope": "pod",
  "provider": "aws",
  "symptoms": [
    "Pod logs contain AWS credential errors",
    "Error: InvalidClientTokenId or ExpiredTokenException",
    "403 Forbidden from any AWS API endpoint"
  ],
  "log_patterns": [
    "InvalidClientTokenId",
    "ExpiredTokenException",
    "NoCredentialProviders"
  ],
  "root_cause": "The pod's ServiceAccount has an IRSA annotation pointing to an IAM role, but the trust policy on that role does not match the pod's namespace and ServiceAccount name...",
  "remediation_steps": [
    "Check the trust policy: aws iam get-role --role-name <name> --query 'Role.AssumeRolePolicyDocument'",
    "Verify the condition matches: sts.amazonaws.com/sub: system:serviceaccount:<namespace>:<serviceaccount>",
    "Update the trust policy if the namespace or SA name is wrong",
    "Restart the pod to acquire a fresh OIDC token"
  ],
  "confidence_hints": [
    { "pattern": "InvalidClientTokenId", "boost": 0.4 },
    { "pattern": "IRSA", "boost": 0.5 }
  ],
  "safe_auto_fix": false,
  "safety_level": "suggest_only",
  "tags": ["eks", "iam", "irsa", "aws", "identity", "credentials"]
}
```

---

## Feedback and Learning

### `POST /api/v1/feedback/structured`

Submit structured feedback after resolving an incident. This is the primary signal for the learning loop.

**Request:**

```bash
curl -X POST http://localhost:8000/api/v1/feedback/structured \
  -H "Content-Type: application/json" \
  -d '{
    "incident_id": "inc-a3f9b1c2",
    "correct_root_cause": true,
    "fix_worked": true,
    "operator_notes": "Created the missing secret — pods recovered in under 60 seconds",
    "better_remediation": null,
    "time_to_resolve_minutes": 8
  }'
```

**Response:**

```json
{
  "accepted": true,
  "patterns_updated": ["k8s-001"],
  "confidence_delta": +0.1,
  "message": "Feedback recorded. Pattern k8s-001 confidence boosted."
}
```

**What happens internally:**
1. The matched KB pattern (`k8s-001`) receives a `+0.1` confidence boost
2. The incident is marked resolved with the outcome stored
3. If `fix_worked=false`, the pattern receives a `-0.15` penalty
4. If `better_remediation` is provided, it is stored and surfaced next time this pattern is matched

### `GET /api/v1/stats/accuracy`

**Request:**

```bash
curl http://localhost:8000/api/v1/stats/accuracy
```

**Response:**

```json
{
  "total_incidents": 47,
  "with_feedback": 31,
  "rca_correct_rate": 0.81,
  "fix_success_rate": 0.74,
  "mean_confidence_when_correct": 0.84,
  "mean_confidence_when_incorrect": 0.49,
  "top_accurate_patterns": [
    { "id": "k8s-001", "rca_correct": 12, "rca_incorrect": 1, "accuracy": 0.92 },
    { "id": "k8s-003", "rca_correct": 8, "rca_incorrect": 2, "accuracy": 0.80 }
  ],
  "patterns_needing_improvement": [
    { "id": "net-006", "rca_correct": 2, "rca_incorrect": 3, "accuracy": 0.40 }
  ]
}
```

---

## APM Endpoints

### `POST /api/v1/apm/ingest`

Receive APM reports from sidecar agents. Called automatically by the agent every 30 seconds.

**Request:**

```bash
curl -X POST http://localhost:8000/api/v1/apm/ingest \
  -H "Content-Type: application/json" \
  -d '{
    "service_name": "checkout-api",
    "namespace": "production",
    "pod_name": "checkout-api-5d7c9f-lm4pk",
    "report_window_secs": 30,
    "total_lines": 1842,
    "error_count": 47,
    "warning_count": 12,
    "error_rate": 0.025,
    "patterns_detected": [
      {
        "pattern_id": "http-5xx",
        "pattern_name": "HTTP 5xx error spike",
        "count": 47,
        "severity": "high",
        "incident_type": "APM_HTTP_ERROR",
        "sample": "ERROR 503 Service Unavailable from payment-svc after 30001ms",
        "remediation_hint": "Check payment-svc health and add retry logic"
      }
    ],
    "metrics": {
      "latency_p50_ms": 145,
      "latency_p95_ms": 892,
      "latency_p99_ms": 2340,
      "throughput_rps": 61.3
    },
    "novel_errors": [
      "ERROR Stripe API rate limit exceeded: 429 Too Many Requests — retry after 30s"
    ],
    "agent_version": "0.2.0"
  }'
```

**Response:**

```json
{
  "accepted": true,
  "service_key": "production/checkout-api",
  "health_score": 71,
  "incidents_created": 1,
  "incident_ids": ["inc-apm-d4e5f6"]
}
```

---

### `GET /api/v1/apm/services`

List all services currently reporting APM data, sorted by health score (sickest first).

**Request:**

```bash
curl "http://localhost:8000/api/v1/apm/services?namespace=production"
```

**Response:**

```json
[
  {
    "service_key": "production/checkout-api",
    "service_name": "checkout-api",
    "namespace": "production",
    "health_score": 71,
    "error_rate": 0.025,
    "error_count": 47,
    "last_report": "2024-01-15T09:25:00Z",
    "top_patterns": ["HTTP 5xx error spike", "Slow downstream response"]
  },
  {
    "service_key": "production/payment-api",
    "service_name": "payment-api",
    "namespace": "production",
    "health_score": 98,
    "error_rate": 0.001,
    "error_count": 2,
    "last_report": "2024-01-15T09:25:01Z",
    "top_patterns": []
  }
]
```

---

## Debug Endpoints

These are diagnostic endpoints useful during setup and troubleshooting.

### `GET /api/v1/debug/provider`

```bash
curl http://localhost:8000/api/v1/debug/provider
```

```json
{
  "detected_provider": "aws",
  "detection_method": "node_labels",
  "evidence": {
    "node_labels_found": ["eks.amazonaws.com/nodegroup", "eks.amazonaws.com/capacityType"],
    "provider_id_prefix": "aws://"
  },
  "env_override": null
}
```

### `GET /api/v1/debug/llm`

```bash
curl http://localhost:8000/api/v1/debug/llm
```

```json
{
  "provider": "anthropic",
  "model": "claude-3-haiku-20240307",
  "api_key_set": true,
  "status": "ok",
  "fallback_available": true
}
```

---

## Common Error Responses

| HTTP Status | When it occurs |
|---|---|
| `400 Bad Request` | Invalid request body or missing required field |
| `404 Not Found` | Incident ID or pattern ID does not exist |
| `409 Conflict` | Remediation plan already exists for this incident |
| `422 Unprocessable Entity` | Request validation failed (Pydantic) |
| `503 Service Unavailable` | K8s API unreachable (real cluster mode only) |

**Example 404:**

```json
{
  "detail": "Incident 'inc-xyz' not found. Use GET /api/v1/incidents to list available incidents."
}
```
