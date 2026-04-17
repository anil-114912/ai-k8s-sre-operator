# Evaluation

How the system measures its own performance, what the numbers mean, and how accuracy improves over time.

---

## What Is Being Measured

The system has two primary outputs that can be evaluated:

1. **Root cause analysis accuracy** — did the AI correctly identify why something failed?
2. **Remediation fix rate** — did the recommended fix actually resolve the incident?

Both metrics rely on **operator feedback** submitted via the API after an incident is resolved. The system cannot self-evaluate — it needs humans to confirm whether its reasoning was correct.

---

## Current Baseline (Demo Data)

These baselines are based on the pattern types in the knowledge base. Real numbers will depend on your specific cluster behaviour and failure mix.

| Metric | Estimated Baseline | Notes |
|---|---|---|
| KB pattern match rate | ~85% | % of incidents matched to ≥1 KB pattern |
| RCA correct (when confident ≥0.8) | ~82% | Mean across known failure types |
| RCA correct (when confident <0.5) | ~40% | System correctly reflects low confidence |
| Fix success rate | ~74% | % of executed remediations confirmed working |
| Novel error capture | ~40% | % of unmatched error lines captured for learning |

**Interpretation:** The system is deliberately conservative. When confidence is low (< 0.5), it says so — and the accuracy data confirms this calibration is roughly correct. Do not execute auto-remediation on low-confidence RCA.

---

## How Feedback Drives Improvement

### The feedback loop in detail

```
Operator resolves incident
    │
    ▼
POST /api/v1/feedback/structured
  {
    "incident_id": "inc-a3f9b1c2",
    "correct_root_cause": true,    # Was the AI correct?
    "fix_worked": true,            # Did the fix resolve the problem?
    "operator_notes": "...",       # Optional: what actually happened
    "better_remediation": "..."    # Optional: what you actually ran
  }
    │
    ▼
FeedbackStore records the outcome
    │
    ├─ correct_root_cause=true  → KB pattern confidence + 0.10
    ├─ correct_root_cause=false → KB pattern confidence - 0.15
    ├─ fix_worked=true          → pattern marked "successful_fix"
    ├─ fix_worked=false         → pattern marked "fix_failed"
    └─ better_remediation set   → stored as alternative, surfaces next match
    │
    ▼
LearningLoop.refit() (periodic)
    │
    ├─ Rebuilds TF-IDF matrix with new incident data
    ├─ Refits sentence-transformer index
    └─ Adjusts confidence tiers based on accumulated feedback
```

### Confidence tier system

Patterns start at a base confidence derived from KB evidence strength. After repeated operator feedback, patterns move between tiers:

| Tier | Confidence Range | Behaviour |
|---|---|---|
| Unvalidated | 0.0–0.5 | KB match only; no historical validation |
| Validated | 0.5–0.75 | 1+ successful fixes confirmed by operators |
| High confidence | 0.75–0.9 | 5+ successful fixes, consistent RCA accuracy |
| Authoritative | 0.9–1.0 | 10+ successful fixes, zero incorrect RCA |

A pattern drops a tier if a fix fails or the RCA is marked incorrect. This prevents patterns from staying at high confidence through inertia.

---

## Pattern Promotion Pipeline

Novel errors observed by the sidecar agent or during KB search misses flow through a promotion pipeline:

```
Sidecar agent: unmatched error line
    │
    ├── PatternLearner.observe(line)
    │     Normalises: strips timestamps, UUIDs, numbers
    │     Tracks frequency counter
    │     Buffers up to 200 lines
    │
    ▼
POST /api/v1/apm/learn (every N cycles)
    Top-20 most frequent novel lines submitted
    │
    ▼
LearningLoop.capture_unknown_errors()
    Scores novelty: does this line cluster with existing patterns?
    If sufficiently novel: adds to learned.yaml as candidate
    │
    ▼
Candidate pattern (in learned.yaml)
    Title: auto-generated from normalised line
    Scope: pod
    Status: candidate (not yet used in KB search)
    │
    ▼ After N operator confirmations
Promoted to active KB pattern
    Added to appropriate knowledge/failures/*.yaml
    Confidence starts at Validated tier
```

You can inspect the current candidate patterns:

```bash
cat knowledge/failures/learned.yaml

# Or via API:
curl http://localhost:8000/api/v1/stats/learning
```

---

## Accuracy Stats API

The `/api/v1/stats/accuracy` endpoint returns live accuracy metrics based on all feedback submitted:

```json
{
  "total_incidents": 47,
  "with_feedback": 31,
  "feedback_coverage": 0.66,
  "rca_correct_rate": 0.81,
  "fix_success_rate": 0.74,
  "mean_confidence_when_correct": 0.84,
  "mean_confidence_when_incorrect": 0.49,
  "confidence_calibration": "well-calibrated",
  "top_accurate_patterns": [
    { "id": "k8s-001", "accuracy": 0.92, "sample_size": 13 },
    { "id": "k8s-003", "accuracy": 0.80, "sample_size": 10 }
  ],
  "patterns_needing_improvement": [
    { "id": "net-006", "accuracy": 0.40, "sample_size": 5 }
  ],
  "novel_patterns_captured": 8,
  "patterns_promoted": 1
}
```

**`confidence_calibration`** is set to `well-calibrated` when `mean_confidence_when_correct - mean_confidence_when_incorrect > 0.25`. This gap indicates the confidence score is meaningful — high confidence genuinely predicts correct RCA.

---

## KB Pattern Quality

Each KB pattern has `confidence_hints` that define how specific evidence boosts the pattern's score for a given incident:

```yaml
- id: k8s-001
  title: "CrashLoopBackOff — missing Secret"
  confidence_hints:
    - pattern: "secret .* not found"
      boost: 0.5    # +0.5 to base score if this regex matches logs
    - pattern: "envFrom.*secretRef"
      boost: 0.4    # +0.4 if manifest references a secretRef
    - pattern: "CrashLoopBackOff"
      boost: 0.3    # +0.3 for the basic state match
```

Patterns with high boost sums and low base variability are more reliable. The accuracy stats surface which patterns have low accuracy despite high confidence — these are candidates for confidence hint refinement.

---

## Limitations

**What the system does well:**

- High-confidence detection of well-documented, common failure patterns (the top 20 failure types in the KB)
- Signal correlation when the causal chain is clear (deploy change → crash onset)
- Cloud-specific patterns where evidence is unambiguous (IRSA token mismatch, Fargate profile missing)

**Where it falls short:**

- **Novel failures** — if a failure type has no KB pattern and no historical similar incidents, accuracy drops significantly. The system will say so via low confidence.
- **Multi-cause failures** — when multiple independent issues coincide (e.g., DNS failure + deployment rollout happening simultaneously), the correlator may attribute the wrong root cause.
- **Application-layer failures without the sidecar** — without the APM agent, the system cannot see inside the container and must rely only on K8s events and logs.
- **Very fast crashes** — if a container crashes and the logs are truncated before the error line, log pattern matching fails.

---

## Future Evaluation Plan

Phase 3 of the roadmap targets several improvements to evaluation quality:

- **Offline evaluation dataset**: Export 6 months of incidents with confirmed resolutions from production to an evaluation set; measure precision/recall
- **Confidence calibration metrics**: Expected Calibration Error (ECE) and reliability diagrams
- **A/B testing**: Compare rule-based vs LLM RCA on the same incident set; measure where LLM adds value
- **Latency tracking**: Measure time from incident detection to resolution; track improvement over time as feedback accumulates
- **Fine-tuning readiness**: Once >500 validated incidents are available, export a training set for fine-tuning a small model (Phi-3-mini or Llama-3.2-3B) on the specific incident reasoning task
