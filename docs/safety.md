# Safety Model

All remediation actions are classified into three safety levels. Multiple guardrails enforce these levels before any action executes.

## Safety Levels

| Level | Name | Behavior |
|---|---|---|
| L1 | auto_fix | Executes automatically when AUTO_FIX_ENABLED=true |
| L2 | approval_required | Generates plan, waits for human approval via API |
| L3 | suggest_only | Never auto-executes — human action only |

## Action Mappings

25 actions mapped to safety levels in `policies/safety_levels.py`:

### L1 — Auto Fix

| Action | Description |
|---|---|
| restart_pod | Delete pod to trigger restart |
| rollout_restart | Rolling restart of deployment |
| rerun_job | Delete and recreate failed job |
| scale_up | Increase replica count (within bounds) |
| collect_diagnostics | Gather pod describe + logs |
| verify_recovery | Check rollout status |
| verify_secret_missing | Confirm secret absence |

### L2 — Approval Required

| Action | Description |
|---|---|
| rollback | Rollback deployment to previous revision |
| rollback_deployment | Same as rollback |
| scale_down | Decrease replica count |
| patch_limits | Update resource limits/requests |
| patch_selector | Update service selector labels |
| patch_probes | Update probe configuration |
| patch_hpa | Update HPA min/max replicas |
| restart_coredns | Restart CoreDNS deployment |

### L3 — Suggest Only

| Action | Description |
|---|---|
| recreate_secret | Create or recreate a Kubernetes Secret |
| rbac_changes | Modify RBAC roles or bindings |
| create_role | Create a new Role |
| create_rolebinding | Create a new RoleBinding |
| network_policy | Create or modify NetworkPolicy |
| storage_changes | Modify PVC, PV, or StorageClass |
| fix_cni | Fix CNI plugin configuration |
| fix_service_mesh | Fix Istio/Linkerd configuration |
| node_drain | Drain a node |
| increase_quota | Increase ResourceQuota |

## Guardrails

Before any action executes, it passes through these checks in `remediations/policy_guardrails.py`:

1. **Namespace check** — Is the namespace in the denied list? (kube-system, kube-public denied by default)
2. **Action allowlist** — Is this action in the permitted actions list?
3. **Safety level check** — L3 actions are always blocked from auto-execution
4. **Cooldown check** — Has this workload been remediated in the last 300 seconds?
5. **Dry-run mode** — If OPERATOR_DRY_RUN=true (default), simulate without real changes

## Defaults

All remediations default to dry-run mode. Auto-fix is disabled by default. Both must be explicitly enabled:

```bash
OPERATOR_DRY_RUN=false
AUTO_FIX_ENABLED=true
```

## Overall Plan Safety

A remediation plan's overall safety level is the most restrictive level across all its steps. If any step is L3, the entire plan is L3. If any step is L2 (and none are L3), the plan is L2.
