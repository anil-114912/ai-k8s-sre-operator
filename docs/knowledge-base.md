# Knowledge Base

45 structured failure patterns in `knowledge/failures/`, covering generic Kubernetes, cloud providers, networking, security, storage, and cluster-level failures.

## Pattern Files

| File | Patterns | Scope |
|---|---|---|
| generic_k8s.yaml | 12 | CrashLoop (secret, configmap, OOM, probe, entrypoint), ImagePull (tag, auth), Pending (CPU, memory, selector), Service mismatch, Ingress 404 |
| eks.yaml | 4 | Node group capacity, IRSA misconfigured, ENI IP exhaustion, add-on version incompatible |
| aks.yaml | 3 | VM quota exceeded, Managed Identity permissions, Azure Disk attach failure |
| gke.yaml | 3 | Workload Identity misconfigured, Autopilot quota, Filestore NFS mount failure |
| networking.yaml | 8 | DNS resolution, NetworkPolicy blocking, no endpoints, ingress backend unavailable, CNI IP exhaustion, mTLS mismatch, circuit breaker, LB pending |
| security.yaml | 5 | RBAC forbidden verb, missing ServiceAccount, Pod Security Admission, seccomp profile, image signing |
| storage.yaml | 6 | PVC provisioner failure, FailedMount, CSI driver missing, StorageClass missing, capacity/access mode, volume node affinity |
| cluster.yaml | 4 | ResourceQuota exceeded, LimitRange violation, Node NotReady, etcd slow writes |

## Pattern Format

Each pattern is a YAML entry with these fields:

```yaml
- id: k8s-001
  title: "CrashLoopBackOff — missing secret"
  scope: pod                          # pod / service / ingress / pvc / namespace / cluster
  symptoms:
    - "Pod status: CrashLoopBackOff"
    - "restart_count > 5"
  event_patterns:                     # regex matched against K8s events
    - "secret.*not found"
    - "secretKeyRef"
  log_patterns:                       # regex matched against pod logs
    - "secret.*not found"
    - "failed to load config"
  metric_patterns:                    # Prometheus metric conditions
    - "container_memory_usage_bytes > limits"
  root_cause: "Application references a Secret that does not exist"
  remediation_steps:
    - "Verify secret exists: kubectl get secret <name> -n <namespace>"
    - "Create missing secret: kubectl create secret generic ..."
    - "Restart deployment: kubectl rollout restart deployment/..."
  confidence_hints:
    - pattern: "secret.*not found"
      boost: 0.3                      # adds to match score when pattern found
  safe_auto_fix: false
  safety_level: suggest_only          # auto_fix / approval_required / suggest_only
  tags: [crashloop, secret, config]
  provider: aws                       # optional — boosts score for matching provider
```

## Search Engine

The KB search engine in `knowledge/failure_kb.py` scores each pattern against incident text:

| Signal | Weight |
|---|---|
| event_patterns regex match | +0.25 per match |
| log_patterns regex match | +0.20 per match |
| Symptom keyword overlap | +0.10 scaled by word match ratio |
| Provider match (aws/azure/gcp) | +0.15 boost (or -0.10 penalty for wrong provider) |
| confidence_hints pattern match | +boost value from hint |
| Title word overlap | +0.08 per matching word |
| Root cause keyword overlap | +0.04 per matching word |
| Tag match | +0.05 per matching tag |

Results are sorted by score descending and returned as top-K.

## Adding New Patterns

Create a new YAML file in `knowledge/failures/` or add entries to an existing file. The KB loader reads all `.yaml` files in that directory on startup.

Learned patterns from operator feedback are automatically saved to `knowledge/failures/learned.yaml`.
