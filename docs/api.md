# API Reference

FastAPI REST API running on port 8000. Swagger docs at http://localhost:8000/docs.

## Core

| Method | Path | Description |
|---|---|---|
| GET | /health | Health check |

## Incidents

| Method | Path | Description |
|---|---|---|
| POST | /api/v1/incidents | Create/ingest an incident |
| GET | /api/v1/incidents | List incidents (query: severity, status, namespace, limit) |
| GET | /api/v1/incidents/{id} | Get incident details |
| POST | /api/v1/incidents/{id}/analyze | Run full AI analysis pipeline |
| GET | /api/v1/incidents/{id}/similar | Find similar past incidents |

## Remediation

| Method | Path | Description |
|---|---|---|
| GET | /api/v1/incidents/{id}/remediation | Get or generate remediation plan |
| POST | /api/v1/incidents/{id}/remediation/execute | Execute plan (query: dry_run=true) |
| POST | /api/v1/incidents/{id}/remediation/approve | Approve L2 plan for execution |

## Cluster

| Method | Path | Description |
|---|---|---|
| POST | /api/v1/scan | Trigger cluster scan with all 18 detectors (query: namespace) |
| GET | /api/v1/cluster/summary | Cluster health summary |
| GET | /api/v1/cluster/patterns | Recurring failure types (query: cluster_name, limit) |

## Knowledge Base

| Method | Path | Description |
|---|---|---|
| GET | /api/v1/knowledge/failures | List all KB patterns (query: tag) |
| GET | /api/v1/knowledge/failures/{id} | Get specific pattern by ID |
| GET | /api/v1/knowledge/search | Search KB (query: q, provider, top_k) |

## Feedback and Learning

| Method | Path | Description |
|---|---|---|
| POST | /api/v1/feedback | Basic feedback (success/failure + notes) |
| POST | /api/v1/feedback/structured | Structured feedback (RCA correctness, fix success, better remediation) |
| GET | /api/v1/stats/accuracy | RCA accuracy and fix success rates |
| GET | /api/v1/stats/learning | Learning system stats |

## Examples

### Scan cluster

```bash
curl -X POST http://localhost:8000/api/v1/scan
```

### Analyze incident

```bash
curl -X POST http://localhost:8000/api/v1/incidents/{id}/analyze
```

### Submit structured feedback

```bash
curl -X POST http://localhost:8000/api/v1/feedback/structured \
  -H "Content-Type: application/json" \
  -d '{
    "incident_id": "abc-123",
    "correct_root_cause": true,
    "fix_worked": true,
    "operator_notes": "Created the missing secret",
    "better_remediation": "kubectl create secret generic db-creds -n production"
  }'
```

### Search knowledge base

```bash
curl "http://localhost:8000/api/v1/knowledge/search?q=secret+not+found+crashloop&provider=aws&top_k=5"
```
