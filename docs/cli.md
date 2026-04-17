# CLI Reference

The `ai-sre` CLI provides terminal access to all operator functions with Rich-formatted output: coloured panels, tables, spinners, and severity badges.

## Installation

```bash
pip install -r requirements.txt

# Verify the CLI is available
ai-sre --help
# or
python3 -m cli.main --help
```

## Global Options

```bash
ai-sre --api-url http://custom:8000 <command>   # Override API base URL
```

The CLI reads `API_BASE_URL` from the environment and `.env` at startup. Default: `http://localhost:8000`.

---

## cluster scan

Scan the cluster for all active failure conditions using all 18 detectors.

```bash
ai-sre cluster scan                           # all namespaces
ai-sre cluster scan --namespace production    # single namespace
ai-sre cluster scan -n staging
```

**Output:**

```
╭──────────────── 🔍 Cluster Scan ─────────────────╮
│ Running cluster scan...                           │
╰───────────────────────────────────────────────────╯
╭──────────────── ✅ Scan Results ──────────────────╮
│ Scan complete                                     │
│   Total detections:  4                            │
│   Incidents created: 3                            │
│   Scanned at:        2026-04-16T09:14:22Z         │
╰───────────────────────────────────────────────────╯
             Created Incidents
╭────────────────────────────────────╮
│ Incident ID                        │
├────────────────────────────────────┤
│ inc-a3f9b2c1...                    │
│ inc-d7e4f801...                    │
│ inc-9c2b5a3e...                    │
╰────────────────────────────────────╯
```

---

## cluster patterns

Show the most frequent recurring failure types for a cluster.

```bash
ai-sre cluster patterns
ai-sre cluster patterns --cluster-name production --limit 5
```

**Output:**

```
      Cluster Patterns: production
╭────────────────────────────┬───────╮
│ Failure Type               │ Count │
├────────────────────────────┼───────┤
│ CrashLoopBackOff           │ 12    │
│ OOMKill                    │  5    │
│ ServiceSelectorMismatch    │  3    │
│ PVCPending                 │  2    │
│ ImagePullBackOff           │  1    │
╰────────────────────────────┴───────╯
```

---

## incidents list

List all active incidents with severity, type, namespace, and root cause.

```bash
ai-sre incidents list                          # all incidents
ai-sre incidents list --severity critical      # filter by severity
ai-sre incidents list --namespace production   # filter by namespace
ai-sre incidents list -n staging --severity high
```

**Output:**

```
                              Active Incidents
╭──────────────┬──────────┬──────────────────────┬─────────────┬──────────────────────┬──────────────┬──────────────────────────────────────────╮
│ ID           │ Severity │ Type                 │ Namespace   │ Workload             │ Status       │ Root Cause                               │
├──────────────┼──────────┼──────────────────────┼─────────────┼──────────────────────┼──────────────┼──────────────────────────────────────────┤
│ inc-a3f9b2..│ CRITICAL │ CrashLoopBackOff     │ production  │ payment-api          │ open         │ Secret "db-credentials" not found in ...  │
│ inc-d7e4f8..│ HIGH     │ OOMKill              │ production  │ order-processor      │ analyzing    │ Container exceeded 512Mi memory limit ... │
│ inc-9c2b5a..│ MEDIUM   │ ServiceSelectorMi... │ staging     │ frontend-svc         │ open         │ Not yet analyzed                          │
╰──────────────┴──────────┴──────────────────────┴─────────────┴──────────────────────┴──────────────┴──────────────────────────────────────────╯
```

Severity colours: `CRITICAL` in red, `HIGH` in orange, `MEDIUM` in yellow, `LOW` in green.

---

## incident analyze

Run the full 7-step AI analysis pipeline on an incident.

```bash
ai-sre incident analyze inc-a3f9b2c1-...                          # by incident ID
ai-sre incident analyze examples/crashloop_missing_secret.json    # from JSON file
```

**Output:**

```
╭──────────────────────── 🧠 AI RCA ──────────────────────────────╮
│ Analyzing incident: inc-a3f9b2c1-4b8d-11ef-9e2a-0242ac130003   │
╰─────────────────────────────────────────────────────────────────╯
╭──────────────────────── 📋 Incident Summary ────────────────────╮
│ Title:     payment-api CrashLoopBackOff in production           │
│ Type:      CrashLoopBackOff                                     │
│ Namespace: production/payment-api                               │
│ Severity:  CRITICAL                                             │
│ Confidence: 97%                                                 │
╰─────────────────────────────────────────────────────────────────╯
╭───────────────────────── 🎯 Root Cause ─────────────────────────╮
│ Missing Secret: payment-api cannot start because Secret         │
│ "db-credentials" does not exist in namespace "production".      │
╰─────────────────────────────────────────────────────────────────╯
╭───────────────────────── 📖 AI Explanation ─────────────────────╮
│ The payment-api pod is in CrashLoopBackOff with 18 restarts.    │
│ The crash log contains "secret 'db-credentials' not found in    │
│ namespace production". A deployment change 4 minutes ago added  │
│ envFrom.secretRef.name: db-credentials, but the Secret was      │
│ never created. The pod exits immediately on startup before       │
│ becoming ready. This matches KB pattern k8s-001 (score 0.94).   │
│ A similar incident was resolved in auth-service 3 days ago by   │
│ creating the missing secret.                                     │
╰─────────────────────────────────────────────────────────────────╯

Contributing Factors:
  • Deployment updated 4 minutes ago (change correlation)
  • 18 restarts in 12 minutes (restart velocity)
  • envFrom.secretRef.name references non-existent Secret

╭──────────────────────── 💡 Suggested Fix ──────────────────────╮
│ kubectl create secret generic db-credentials \                  │
│   --from-literal=DB_PASSWORD=<value> \                          │
│   -n production                                                 │
╰────────────────────────────────────────────────────────────────╯
```

---

## remediation plan

Show the remediation plan for an incident without executing it.

```bash
ai-sre remediation plan inc-a3f9b2c1-...
```

**Output:**

```
╭──────────────────────── 🔧 Remediation Plan ───────────────────╮
│ Summary: Create missing Secret and restart deployment           │
│ Safety Level: APPROVAL_REQUIRED                                 │
│ Requires Approval: Yes                                          │
│ Est. Downtime: 30s                                              │
╰────────────────────────────────────────────────────────────────╯
                     Remediation Steps
 #    Action               Safety              Rev  Description
 ─────────────────────────────────────────────────────────────────
 1    patch_resources      APPROVAL_REQUIRED   ✅   Create Secret db-credentials in ns production
 2    rollout_restart      AUTO_FIX            ✅   kubectl rollout restart deployment/payment-api -n production
```

Safety level colours: `AUTO_FIX` in green, `APPROVAL_REQUIRED` in yellow, `SUGGEST_ONLY` in magenta.

---

## remediation execute

Execute the remediation plan. Dry-run is the default.

```bash
ai-sre remediation execute inc-a3f9b2c1-...              # dry-run (safe, no changes)
ai-sre remediation execute inc-a3f9b2c1-... --no-dry-run  # live execution
```

---

## remediation approve

Approve a queued L2 (approval-required) remediation plan.

```bash
ai-sre remediation approve inc-a3f9b2c1-...
# ✅ Remediation plan approved. Ready to execute.
```

---

## simulate

Simulate a specific incident type and run the full analysis pipeline. Use `--demo` to run entirely offline without an API server.

```bash
ai-sre simulate --type crashloop    # CrashLoopBackOff — missing secret
ai-sre simulate --type oomkilled    # OOMKill — memory limit exceeded
ai-sre simulate --type pending      # Pod Pending — node resource exhaustion
ai-sre simulate --type ingress      # Ingress 502 — backend service mismatch
ai-sre simulate --type pvc          # PVC mount failure — storage class missing

# Fully offline — no API server required
ai-sre simulate --type crashloop --demo
```

**Output (`--demo` mode):**

```
╭──────────────────────── 🎮 Simulation Mode ─────────────────────╮
│ Simulating CRASHLOOP incident                                    │
│ Loading from: examples/crashloop_missing_secret.json            │
╰──────────────────────────────────────────────────────────────────╯
╭──────────────────────── 📋 payment-api CrashLoopBackOff ────────╮
│ ● CRITICAL — CrashLoopBackOff                                   │
│ Namespace/Workload: production/payment-api                      │
│ Root Cause: Missing Secret "db-credentials" in production       │
│ Confidence: 97%                                                 │
╰──────────────────────────────────────────────────────────────────╯
╭──────────────────────── 📖 AI Explanation ──────────────────────╮
│ The payment-api is crashing because it cannot find the secret   │
│ "db-credentials". Create the secret and redeploy.               │
╰──────────────────────────────────────────────────────────────────╯

Generating remediation plan...
╭──────────────────────── 🔧 Remediation Plan ────────────────────╮
│ Summary: Create missing Secret and restart deployment           │
│ Safety Level: APPROVAL_REQUIRED                                 │
│ Requires Approval: Yes ⚠️                                       │
│ Steps: 2                                                        │
╰──────────────────────────────────────────────────────────────────╯
```

---

## knowledge search

Search the failure pattern knowledge base.

```bash
ai-sre knowledge search "crashloop secret"
ai-sre knowledge search "oom memory" --provider aws    # EKS context
ai-sre knowledge search "ingress 502" --top-k 3
```

**Output:**

```
     Knowledge Base Search: 'crashloop secret'
╭──────────┬──────────────────────────────────────────┬───────┬──────────────────┬──────────────────────────────╮
│ ID       │ Title                                    │ Score │ Safety           │ Tags                         │
├──────────┼──────────────────────────────────────────┼───────┼──────────────────┼──────────────────────────────┤
│ k8s-001  │ CrashLoopBackOff: Missing Secret or C... │  0.94 │ approval_required│ crashloop, secret, config    │
│ k8s-002  │ CrashLoopBackOff: Bad Liveness Probe     │  0.61 │ approval_required│ crashloop, probe, health     │
│ k8s-003  │ CrashLoopBackOff: OOMKilled              │  0.44 │ auto_fix         │ crashloop, oom, memory       │
╰──────────┴──────────────────────────────────────────┴───────┴──────────────────┴──────────────────────────────╯

╭──────────── 💡 Top Match: CrashLoopBackOff: Missing Secret or ConfigMap ─────────────╮
│ Root cause: Pod exits immediately because a referenced Secret or ConfigMap does not   │
│ exist in the namespace. envFrom or env[].valueFrom causes a fatal startup error.      │
│                                                                                       │
│ 1. Identify the missing resource from the crash log                                   │
│ 2. kubectl create secret generic <name> --from-literal=key=value -n <namespace>      │
│ 3. kubectl rollout restart deployment/<name> -n <namespace>                           │
╰───────────────────────────────────────────────────────────────────────────────────────╯
```

---

## knowledge list

List all knowledge base patterns, optionally filtered by tag.

```bash
ai-sre knowledge list
ai-sre knowledge list --tag networking
ai-sre knowledge list --tag storage
ai-sre knowledge list --tag eks
```

---

## learn feedback

Record operator feedback for a remediation outcome. This adjusts confidence scoring for the matched KB pattern.

```bash
ai-sre learn feedback inc-a3f9b2c1-... --success --notes "Fixed by adding secret"
ai-sre learn feedback inc-d7e4f801-... --failure --notes "Fix did not work, rolled back"
```

---

## feedback submit

Submit structured feedback covering both RCA correctness and fix outcome.

```bash
ai-sre feedback submit inc-a3f9b2c1-... --correct --fix-worked --notes "Exact fix"
ai-sre feedback submit inc-d7e4f801-... --incorrect --fix-failed --notes "Wrong root cause"
```

**Output:**

```
╭──────────────────── 📊 Feedback Submitted ─────────────────────╮
│ Incident: inc-a3f9b2c1-4b8d-11ef-9e2a-0242ac130003            │
│ ✅ Correct RCA                                                  │
│ ✅ Fix worked                                                   │
│ Notes: Exact fix                                                │
╰────────────────────────────────────────────────────────────────╯
```

---

## feedback stats

Show overall RCA accuracy and fix success rates.

```bash
ai-sre feedback stats
```

**Output:**

```
         Learning Statistics
╭─────────────────────────────┬────────────╮
│ Metric                      │ Value      │
├─────────────────────────────┼────────────┤
│ Total Incidents Analyzed    │ 47         │
│ RCA Accuracy                │ 83.0%      │
│ Fix Success Rate            │ 78.7%      │
│ Top Failure Types           │ CrashLoop (12), OOMKill (5), Service (3) │
╰─────────────────────────────┴────────────╯
```

---

## Example workflows

### Full demo — no cluster, no API key

```bash
# Start the API in demo mode (Terminal 1)
make run-api-demo

# Simulate a CrashLoop and run full analysis offline
ai-sre simulate --type crashloop --demo
```

### Investigate a live cluster incident

```bash
# 1. Scan the cluster
ai-sre cluster scan --namespace production

# 2. List what was found
ai-sre incidents list --severity critical

# 3. Run AI analysis on a specific incident
ai-sre incident analyze inc-a3f9b2c1-...

# 4. See the remediation plan
ai-sre remediation plan inc-a3f9b2c1-...

# 5. Execute in dry-run first
ai-sre remediation execute inc-a3f9b2c1-...

# 6. Approve and execute live
ai-sre remediation approve inc-a3f9b2c1-...
ai-sre remediation execute inc-a3f9b2c1-... --no-dry-run

# 7. Record outcome for learning
ai-sre learn feedback inc-a3f9b2c1-... --success --notes "Secret was missing"
```

### Search the knowledge base before a manual fix

```bash
ai-sre knowledge search "pending pod insufficient cpu" --provider aws
ai-sre knowledge search "irsa oidc token" --provider aws
ai-sre knowledge search "workload identity" --provider azure
```
