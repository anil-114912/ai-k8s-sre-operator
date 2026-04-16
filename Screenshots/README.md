# Screenshots

This directory contains UI screenshots used in the main README and documentation.

---

## How to Capture Screenshots

### 1. Start the full stack

```bash
# Terminal 1 — API (demo mode with simulated incidents)
DEMO_MODE=1 make run-api

# Terminal 2 — Dashboard
make run-ui
# Opens at http://localhost:8501

# Terminal 3 — Populate with incidents
make simulate
```

### 2. Navigate each tab and capture

Open `http://localhost:8501` in your browser and screenshot each tab at `1440 × 900` or wider.

---

## Required Screenshots

| Filename | Tab / View | What to Show |
|---|---|---|
| `dashboard-overview.png` | **Dashboard tab** | Health score, active incidents list, severity badges, cluster summary cards |
| `incident-rca.png` | **Incidents tab → click any incident** | Root cause analysis output, evidence list, confidence score, AI explanation |
| `remediation-plan.png` | **Incidents tab → Remediation** | Step-by-step plan, safety level badges (auto/approval/suggest), approve button |
| `apm-overview.png` | **APM tab** | Service health heatmap, error rate chart, latency graph, top errors |
| `knowledge-base.png` | **Knowledge Base tab** | Pattern search results, pattern detail (root cause + remediation steps) |
| `learning-stats.png` | **Learning tab** | Accuracy stats, top failure types, feedback history, learned patterns |
| `cluster-summary.png` | **Cluster tab** | Node count, pod health breakdown, active incidents, health score gauge |

---

## Screenshot Guidelines

- **Resolution:** 1440 × 900 minimum, 2x retina preferred
- **Format:** PNG
- **Theme:** Default dark theme (the UI ships with a dark futuristic theme)
- **State:** Capture with incidents visible — run `make simulate` before screenshotting the incident views
- **Annotations:** Avoid adding annotations or callouts to screenshots — keep them clean
- **Filenames:** Use lowercase with hyphens as listed in the table above

---

## Current Screenshots

The following properly-named screenshots are available:

```
Screenshots/dashboard-overview.png
Screenshots/incident-rca.png
Screenshots/remediation-plan.png
Screenshots/apm-overview.png
Screenshots/knowledge-base.png
Screenshots/learning-stats.png
Screenshots/cluster-summary.png
```

---

## Placeholder References

The README references these filenames:

```
Screenshots/dashboard-overview.png
Screenshots/incident-rca.png
Screenshots/remediation-plan.png
Screenshots/apm-overview.png
Screenshots/knowledge-base.png
Screenshots/learning-stats.png
Screenshots/cluster-summary.png
```

---

## Contributing Screenshots

If you're running this against a real cluster and want to contribute screenshots:

1. Ensure no sensitive data (namespace names, workload names, cluster names) is visible
2. Blur or redact any internal URLs or hostnames
3. Submit via PR with a short note on what cluster type you used (Kind, EKS, etc.)
