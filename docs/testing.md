# Testing

202 pytest tests covering all components.

## Run Tests

```bash
# All tests
make test

# With coverage report
make test-cov

# Specific file
DEMO_MODE=1 python3 -m pytest tests/test_feedback_loop.py -v

# Specific class
DEMO_MODE=1 python3 -m pytest tests/test_feedback_loop.py::TestEndToEndLearningFlow -v

# Specific test
DEMO_MODE=1 python3 -m pytest tests/test_feedback_loop.py::TestCaptureUnknownErrors::test_captures_novel_error_from_logs -v
```

## Test Files

| File | Tests | What It Covers |
|---|---|---|
| test_ai.py | 18 | LLM client rule-based fallback, RCA engine analysis, remediation plan generation, safety level assignment |
| test_api.py | 20 | All FastAPI endpoints: health, incidents CRUD, analyze, remediation, scan, feedback, cluster summary |
| test_correlation.py | 8 | Signal correlator cause-effect rules, OOM→CrashLoop, secret→CrashLoop, confidence scoring |
| test_detectors.py | 26 | Original 9 detectors: CrashLoop, OOMKill, ImagePull, Pending, Probe, Service, Ingress, PVC, HPA |
| test_new_detectors.py | 36 | 9 new detectors: DNS, RBAC, NetworkPolicy, CNI, ServiceMesh, NodePressure, Quota, Rollout, Storage |
| test_knowledge_base.py | 39 | KB load (45 patterns), search scoring, provider boost, context builder, similarity retrieval, feedback boost, incident store methods |
| test_feedback_loop.py | 26 | Error capture (Java/Python/Go), deduplication, embedder refit, feedback scoring, pattern promotion, confidence adjustment, end-to-end learning, API integration |
| test_policies.py | 18 | Namespace allow/deny, action allowlist, safety levels, guardrails validation, cooldown enforcement, dry-run mode |
| test_remediations.py | 11 | All 6 remediation executors in dry-run: restart_pod, rollout_restart, rollback, scale, patch_resources, rerun_job |

## Feedback Loop Tests (test_feedback_loop.py)

26 tests organized into 6 classes:

### TestCaptureUnknownErrors (7 tests)

- Captures novel Java/Python/Go error patterns from logs
- Ignores logs without errors
- Deduplicates already-captured signatures
- Creates patterns with remediation steps
- Updates learning stats

### TestEmbedderRefit (3 tests)

- Refit triggers after threshold (5 incidents)
- Handles empty store
- Works with populated store

### TestFeedbackProcessing (5 tests)

- Positive feedback sets score +1.0
- Negative feedback sets score -0.5
- Operator's better remediation injected into learned patterns
- Pattern promoted after 2+ recurring successes
- Stats reflect feedback events

### TestConfidenceAdjustment (5 tests)

- No history returns base confidence unchanged
- Positive history boosts confidence
- Negative history reduces confidence
- Result clamped to [0.1, 0.99]
- Mixed history produces moderate adjustment

### TestEndToEndLearningFlow (3 tests)

- Full lifecycle: incident → error capture → feedback → confidence boost
- Repeated failures reduce confidence over time
- Stats reflect all learning activity

### TestFeedbackAPIIntegration (3 tests)

- POST /api/v1/feedback/structured triggers learning and returns stats
- POST /api/v1/feedback updates incident score
- GET /api/v1/stats/learning returns learning system stats
