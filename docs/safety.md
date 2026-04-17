# Safety Model

The system is designed so that a misconfiguration or unexpected AI reasoning error cannot cause unintended damage to a production cluster. Safety is enforced through multiple independent layers.

---

## Three-Tier Safety Classification

Every remediation action is classified into one of three levels. This classification is determined at system startup based on the action type — it cannot be overridden at runtime.

| Level | Name | Behavior | Examples |
|---|---|---|---|
| **L1** | `auto_fix` | Executes automatically when `AUTO_FIX_ENABLED=true` | Restart crashed pod, rerun failed job, collect diagnostics |
| **L2** | `approval_required` | Generates plan, enters `pending` state, waits for human approval via API | Scale down, rollback deployment, patch resource limits |
| **L3** | `suggest_only` | Never auto-executes — presents commands for human to run | Create/recreate Secret, RBAC changes, network policy, drain node |

**The overall safety level of a plan is determined by its most restrictive step.**

If a plan has 4 steps — three L1 and one L3 — the entire plan is classified as L3 and cannot auto-execute. This prevents partial execution of a plan where the safe steps run but the dangerous step is blocked.

---

## Action Mapping

25 actions mapped to safety levels in `policies/safety_levels.py`:

### L1 — Auto Fix (safe, reversible, low blast radius)

| Action | Description | Reversibility |
|---|---|---|
| `restart_pod` | Delete pod to trigger kubelet restart | Fully reversible |
| `rollout_restart` | Rolling restart of deployment (zero-downtime) | Fully reversible |
| `rerun_job` | Delete and recreate a failed Job | Reversible if job is idempotent |
| `scale_up` | Increase replica count (within HPA bounds) | Reversible |
| `collect_diagnostics` | `kubectl describe` + log collection only | Read-only, no risk |
| `verify_recovery` | Check rollout status | Read-only, no risk |
| `verify_secret_missing` | Confirm secret absence with `kubectl get` | Read-only, no risk |

### L2 — Approval Required (potentially destructive, requires human review)

| Action | Description | Risk |
|---|---|---|
| `rollback` | Roll deployment back to previous image | May revert intentional changes |
| `rollback_deployment` | Same as rollback (explicit alias) | May revert intentional changes |
| `scale_down` | Decrease replica count | Reduces availability |
| `patch_limits` | Update CPU/memory requests and limits | May destabilise workload |
| `patch_selector` | Update Service selector labels | Misdirects traffic if wrong |
| `patch_probes` | Update liveness/readiness probe config | Affects health monitoring |
| `patch_hpa` | Update HPA min/max replica bounds | Affects scaling behaviour |
| `restart_coredns` | Restart CoreDNS deployment | Brief DNS disruption |

### L3 — Suggest Only (high-impact, requires credentials or context the system cannot verify)

| Action | Description | Why L3 |
|---|---|---|
| `recreate_secret` | Create or recreate a Kubernetes Secret | System cannot generate correct credential values |
| `rbac_changes` | Modify Roles or ClusterRoles | Security-critical; must be human-reviewed |
| `create_role` | Create a new RBAC Role | Security-critical |
| `create_rolebinding` | Create a new RoleBinding | Security-critical |
| `network_policy` | Create or modify NetworkPolicy | Changing network policy can block legitimate traffic |
| `storage_changes` | Modify PVC, PV, or StorageClass | Risk of data loss |
| `fix_cni` | Modify CNI plugin configuration | Cluster-wide network impact |
| `fix_service_mesh` | Modify Istio/Linkerd configuration | mTLS policy affects all services in mesh |
| `node_drain` | Drain a node | Disrupts all pods on that node |
| `increase_quota` | Increase ResourceQuota | Resource planning decision; needs human sign-off |

---

## Guardrail Stack

Before any action executes, it passes through five independent checks in `remediations/policy_guardrails.py`:

```
Action requested
    │
    ▼
1. NAMESPACE CHECK
   Is the target namespace in the deny list?
   Default deny: kube-system, kube-public
   Configurable: DENIED_NAMESPACES env var or Helm deniedNamespaces value
   → BLOCKED if namespace is denied (regardless of all other flags)
    │
    ▼
2. ACTION ALLOWLIST CHECK
   Is this action in the permitted actions list for this namespace?
   Default: all L1 actions permitted in non-denied namespaces
   → BLOCKED if action not in allowlist
    │
    ▼
3. SAFETY LEVEL CHECK
   Is this action classified as L3 (suggest_only)?
   → ALWAYS BLOCKED from auto-execution (even if AUTO_FIX_ENABLED=true)
   Is this action L2 and no approval has been granted?
   → BLOCKED until POST /api/v1/incidents/{id}/remediation/approve is called
    │
    ▼
4. COOLDOWN CHECK
   Has this workload been remediated within the last COOLDOWN_SECS seconds?
   Default cooldown: 300 seconds (5 minutes)
   Tracks: namespace + workload name as composite key
   → BLOCKED if cooldown active (returns time remaining)
    │
    ▼
5. DRY-RUN FLAG
   Is OPERATOR_DRY_RUN=true?
   → SIMULATES action without executing any kubectl commands
   → Logs what would have been done
   → Returns simulated output
    │
    ▼
EXECUTE (real or simulated)
```

---

## Default Configuration

The system ships with maximum safety defaults:

```env
OPERATOR_DRY_RUN=true       # All actions simulate — no real mutations
AUTO_FIX_ENABLED=false      # No automatic execution, even for L1
COOLDOWN_SECS=300           # 5 minutes between remediations per workload
DENIED_NAMESPACES=kube-system,kube-public
```

To enable live execution with L1 auto-fix:

```env
OPERATOR_DRY_RUN=false
AUTO_FIX_ENABLED=true
```

The recommendation for production: **keep dry-run on initially**. Review the plans the system generates for one to two weeks, verify the recommendations are correct, then selectively enable live execution for specific actions using the allowlist.

---

## Blast Radius Analysis

| Scenario | Maximum blast radius | Mitigations |
|---|---|---|
| `restart_pod` on wrong pod | One pod restarted unexpectedly | Cooldown prevents rapid loops |
| `rollout_restart` on wrong deployment | Rolling restart of one deployment | Zero-downtime rolling update; L1 |
| `scale_down` misfire | Reduced availability for one deployment | Requires L2 approval before execution |
| `rollback` on wrong deployment | Previous image version deployed | Requires L2 approval; can be re-rolled |
| `patch_selector` incorrect | Service temporarily misdirects traffic | Requires L2 approval; patch is reversible |
| `drain_node` unexpected | All pods on one node evicted | L3 only — cannot auto-execute |
| `rbac_changes` | Security posture change | L3 only — cannot auto-execute |
| namespace deny list not set | Potential kube-system action | Default deny list covers kube-system and kube-public |

**The worst case for auto-execution (L1 with all restrictions removed) is a pod restart loop on a non-system deployment, prevented by the 5-minute cooldown.**

---

## Audit Logging

Every remediation decision is logged to the API server's stdout with the following fields:

```
2024-01-15T09:24:35Z INFO remediation: plan=plan-7c2d4e8f incident=inc-a3f9b1c2
  action=verify_secret_missing safety_level=auto_fix dry_run=true
  namespace=production workload=payment-api result=simulated

2024-01-15T09:24:35Z INFO remediation: plan=plan-7c2d4e8f incident=inc-a3f9b1c2
  action=recreate_secret safety_level=suggest_only
  status=BLOCKED reason="suggest_only actions are never auto-executed"

2024-01-15T09:35:12Z INFO remediation: plan=plan-7c2d4e8f
  approval granted by=ops-engineer@company.com note="Verified credentials"
```

All incident and remediation records are persisted in SQLite (or PostgreSQL) and queryable via the API. This provides a full audit trail of what the system detected, what it recommended, who approved, and what the outcome was.

---

## Responsible Use

This system is a decision-support tool. The AI reasoning layer can make mistakes, especially for novel failure patterns not represented in the knowledge base. Before enabling live execution:

1. Run in demo mode and validate that the RCA and remediation recommendations are reasonable for your environment
2. Enable `AUTO_FIX_ENABLED=true` only after reviewing a week of dry-run plans
3. Start with L1 actions only (pod restarts, job reruns) — these are safe in all contexts
4. Only enable L2 approval flow (rather than direct approval bypass) once you trust the system's recommendations
5. Submit feedback for every incident — this directly improves future recommendations

The system is not a replacement for human SREs. It is a first-responder that handles the 80% of incidents that are well-understood, so human attention can focus on the 20% that are novel.
