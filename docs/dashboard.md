# Dashboard

Streamlit dashboard at http://localhost:8501 with 8 tabs.

## Prerequisites

The dashboard requires the API server running. Start them in order:

```bash
# Terminal 1 — API must be running first
make run-api
# Wait for: Uvicorn running on http://0.0.0.0:8000

# Terminal 2 — Then start the dashboard
make run-ui
```

If you see `API error: [Errno 61] Connection refused`, the API server is not running. Start it first.

## Start

```bash
make run-ui
# or
DEMO_MODE=1 API_BASE_URL=http://localhost:8000 streamlit run ui/streamlit_app.py
```

## Tabs

### ⚡ Live Incidents

- Filter by severity and namespace
- Expand any incident to see details
- Click **Analyze** to run the full AI pipeline
- Click **Get Plan** to generate a remediation plan
- Click **Similar** to find past incidents
- After analysis, an inline **Operator Feedback** form appears with:
  - Did the fix work? (Yes/No)
  - Was root cause correct? (Yes/No)
  - Better remediation (optional text)
  - Notes
  - Submit button

### 🧠 RCA Analysis

- Paste an incident ID
- Click **Run Full AI Analysis**
- Shows: root cause, confidence bar, AI explanation, contributing factors, evidence
- **Knowledge Base Matches** section with scored patterns from the KB
- **Similar Past Incidents** section with feedback status (✅ resolved / ❌ failed)

### 🔧 Remediation

- Paste an incident ID
- Toggle dry-run mode
- Click **Get Remediation Plan**
- Shows: plan summary, overall safety level, each step with safety badge and kubectl command
- Approve button for L2 plans
- Execute button

### 📚 Incident History

- Accuracy stats: total analyzed, RCA accuracy %, fix success rate %
- Cluster recurring failure patterns bar chart
- Incident history table with ID, title, type, severity, namespace, status, timestamp

### 🔍 Cluster Scan

- Optional namespace filter
- Click **Run Cluster Scan** to trigger all 18 detectors
- Shows created incident IDs
- Cluster health summary: health score, nodes, deployments, PVCs

### 📖 Knowledge Base

- Total pattern count and accuracy stats
- Search box with provider context selector (generic/aws/azure/gcp)
- Tag filter dropdown
- Each pattern expandable with: root cause, safety level, remediation steps, tags

### 🧪 Learning & Feedback

- **Learning System Status**: 5 metrics (learned patterns, promoted, captured errors, feedback events, successful fixes)
- **Embedder refit** progress counter
- **Accuracy Over Time**: total analyzed, RCA accuracy %, fix success rate %
- **Top Failure Types** bar chart
- **Submit Feedback** form: paste incident ID, see AI's analysis, rate correctness, provide better fix
- **How does the learning loop work?** explainer
- **Learned Patterns** list showing captured (🔍) and promoted (🎓) patterns

## Testing the Feedback Loop via UI

1. Go to **Cluster Scan** → Run scan
2. Go to **Live Incidents** → Expand an incident → Click **Analyze**
3. Fill in the feedback form below the incident → Click **Submit Feedback**
4. Go to **Learning & Feedback** → See updated stats
5. Run another scan → Analyze a similar incident → Observe higher confidence
