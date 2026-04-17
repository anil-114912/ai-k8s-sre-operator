# Screenshots

UI screenshots used in the README and documentation. All screenshots are captured from the live Streamlit dashboard running against demo data.

---

## How to Capture Screenshots

### Step 1 — Start the full demo stack

```bash
# Terminal 1 — Start the API with demo mode
DEMO_MODE=1 make run-api

# Wait for: INFO:     Uvicorn running on http://0.0.0.0:8000

# Terminal 2 — Start the Streamlit dashboard
make run-ui

# Terminal 3 — Populate with realistic incidents
make simulate
```

### Step 2 — Open the dashboard

Navigate to http://localhost:8501. You should see a dark-themed dashboard with incident cards, severity badges, and health scores.

### Step 3 — Run AI analysis on a few incidents

In the **Incidents** tab, click **Analyze** on 2–3 critical incidents. Wait for the root cause analysis to complete — this gives you the best screenshot state.

### Step 4 — Capture each tab

Work through the tabs in order. Use `Cmd+Shift+4` (macOS) or the browser's screenshot tool. Save at `1440 × 900` or wider.

---

## Required Screenshots

Capture these 7 screenshots to complete the README gallery:

| Filename | Tab to open | Key elements to show |
|---|---|---|
| `dashboard-overview.png` | Live Incidents (default) | Health score card, active incident list with severity badges, namespace filter, cluster health summary at top |
| `incident-rca.png` | Incidents → click any critical incident | Root cause text in blue highlight, confidence percentage bar, KB pattern matched ("k8s-001"), similar incidents panel |
| `remediation-plan.png` | Incidents → Remediation tab | Step list with action names, safety level badges (🟢 auto / 🟡 approval / 🔴 suggest), Approve button for L2, Dry Run toggle |
| `apm-overview.png` | APM Services tab | Service health score table, error rate column, latency P99 column, at least one service showing errors |
| `knowledge-base.png` | Knowledge Base tab | Search box with a query like "crashloop secret", results list with pattern IDs, expanded pattern showing remediation steps |
| `learning-stats.png` | Learning & Feedback tab | RCA accuracy percentage, fix success rate, top accurate patterns table, novel patterns captured counter |
| `cluster-summary.png` | Cluster Scan tab | Trigger scan button, scan results showing incidents detected, node count, pod health breakdown |

---

## Screenshot Guidelines

- **Resolution:** 1440 × 900 minimum. 2880 × 1800 (2x retina) is ideal.
- **Format:** PNG only
- **Theme:** Use the default dark theme. Do not switch to light mode.
- **Incident state:** Run `make simulate` before capturing — screenshots with populated incidents are significantly more useful than empty dashboards.
- **No annotations:** Do not add arrows, callouts, or text overlays. Keep screenshots clean.
- **Filenames:** Exact lowercase-with-hyphens as listed above. The README references these exact paths.
- **Privacy:** If capturing from a real cluster, redact namespace names, workload names, and any internal hostnames before submitting.

---

## Demo Video / GIF

A short screen recording (30–60 seconds) showing the end-to-end flow is more compelling than static screenshots.

### Recommended recording flow

```
1. Open dashboard — show incident list (3–4 incidents visible)
2. Click "Analyze" on a critical incident — show AI reasoning loading
3. Show the root cause explanation scrolling into view
4. Click "Remediation" — show the step-by-step plan with safety badges
5. Submit feedback — show confidence score updating
6. Switch to Knowledge Base tab — run a search, show pattern detail
```

### Recommended tools

| Tool | Platform | Notes |
|---|---|---|
| [Gifox](https://gifox.app) | macOS | Clean GIF recording, 60fps |
| [Kap](https://getkap.co) | macOS | Free, exports GIF or MP4 |
| [ShareX](https://getsharex.com) | Windows | Free, GIF and MP4 |
| [Peek](https://github.com/phw/peek) | Linux | Simple GIF recorder |

Save the recording as `Screenshots/demo.gif` (max 10MB) or link to a hosted version. Update the README image at the top of the screenshots section to point to the GIF.

---

## Currently Captured

Check the `Screenshots/` directory for files matching these names:

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

If you are running this against a real cluster (EKS, AKS, GKE, or on-prem) and want to contribute screenshots:

1. Redact any sensitive data — namespace names, cluster names, internal URLs, hostnames
2. Include in the PR description: what cluster type you used, what Kubernetes version
3. Prefer screenshots with realistic incident data (more useful than empty dashboards)
4. GIFs showing the AI analysis workflow are especially welcome
