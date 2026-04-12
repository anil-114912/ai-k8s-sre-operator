# Learning and Feedback Loop

The system improves over time through five mechanisms, all implemented in `knowledge/feedback_loop.py`.

## 1. Unknown Error Capture

When a new incident arrives, the system scans its log lines for ERROR, FATAL, PANIC, exception, and traceback patterns. If the error signatures are not already in the knowledge base, they are saved as new entries in `knowledge/failures/learned.yaml`.

This means the system automatically expands its knowledge when it encounters application errors it has never seen before — Java OutOfMemoryError, Python tracebacks, Go panics, database connection failures, etc.

## 2. Embedder Refit

Every 5 new incidents, the TF-IDF similarity engine is retrained on all stored incident texts. This keeps the vocabulary current as new failure types and workload names appear. For sentence-transformer embeddings (if installed), this is a no-op since the model is pre-trained.

## 3. Feedback Scoring

When an operator submits feedback:

| Outcome | Score | Effect on Future Retrieval |
|---|---|---|
| Fix worked | +1.0 | Boosted in similarity search (+30% by default) |
| Fix failed | -0.5 | Penalized in similarity search |

The score is stored on the incident record and used by the similarity retriever to rank past incidents.

## 4. Pattern Promotion

When 2+ similar incidents in the same namespace are resolved successfully, the system promotes the root cause and fix into a permanent learned pattern. Promoted patterns appear in `learned.yaml` with the tag `promoted` and include confidence hints for the namespace and incident type.

## 5. Confidence Adjustment

The AI confidence score is adjusted based on historical feedback:

```
adjusted = base_confidence + (success_rate - 0.5) × 0.3
```

If past fixes for CrashLoopBackOff in the "payments" namespace were 90% successful, the next CrashLoopBackOff there gets +0.12 confidence boost. If they were 20% successful, it gets -0.09 penalty. Result is clamped to [0.1, 0.99].

## Example Flow

```
Incident #1: CrashLoop in payments/order-svc
  → AI: "missing secret" (confidence: 75%)
  → Operator: "Correct! Fixed by creating the secret" ✅

Incident #2: CrashLoop in payments/order-svc
  → AI: "missing secret" (confidence: 82%)     ← boosted by feedback
  → Past fix shown in Similar Incidents
  → Operator: "Same issue" ✅

Incident #3: CrashLoop in payments/order-svc
  → AI: "missing secret" (confidence: 88%)     ← boosted again
  → Pattern promoted to permanent KB
  → Remediation suggested immediately
```

## Feedback API

Basic feedback:

```bash
curl -X POST http://localhost:8000/api/v1/feedback \
  -H "Content-Type: application/json" \
  -d '{"incident_id": "...", "success": true, "notes": "Created the secret"}'
```

Structured feedback (feeds into learning loop):

```bash
curl -X POST http://localhost:8000/api/v1/feedback/structured \
  -H "Content-Type: application/json" \
  -d '{
    "incident_id": "...",
    "correct_root_cause": true,
    "fix_worked": true,
    "operator_notes": "Created the missing secret",
    "better_remediation": "kubectl create secret generic db-creds -n production"
  }'
```

Learning stats:

```bash
curl http://localhost:8000/api/v1/stats/learning
```

Response:

```json
{
  "total_learned_patterns": 3,
  "promoted_patterns": 1,
  "captured_error_patterns": 2,
  "total_feedback_events": 5,
  "total_successful_fixes": 4,
  "incidents_since_last_refit": 2,
  "refit_threshold": 5
}
```

## Testing the Feedback Loop

See [Testing](testing.md) for the 26 dedicated feedback loop tests covering error capture, refit, promotion, confidence adjustment, and API integration.

### Via UI

1. **Cluster Scan** tab → Run scan
2. **Live Incidents** tab → Expand incident → Analyze → Fill feedback form → Submit
3. **Learning & Feedback** tab → See updated stats, learned patterns, accuracy chart
4. Scan again → Analyze similar incident → Observe higher confidence
