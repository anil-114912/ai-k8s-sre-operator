# Detectors

18 deterministic detectors scan cluster state for specific failure patterns. Each returns a DetectionResult with: incident type, affected resource, evidence list, severity, and confidence.

## Detector List

| # | Detector | Incident Type | What It Detects |
|---|---|---|---|
| 1 | CrashLoopDetector | CrashLoopBackOff | Pods with restart count > 5 or CrashLoopBackOff waiting state |
| 2 | OOMKillDetector | OOMKilled | Containers terminated with exit code 137 (OOMKilled reason) |
| 3 | ImagePullDetector | ImagePullBackOff | Failed image pulls — bad tag, auth failure, registry unreachable |
| 4 | PendingPodsDetector | PodPending | Pods stuck Pending > 2 min — insufficient CPU/memory, node selector, taints |
| 5 | ProbeFailureDetector | ProbeFailure | Liveness/readiness/startup probe failures from Unhealthy events |
| 6 | ServiceDetector | ServiceMismatch | Services with selector not matching any running pod labels |
| 7 | IngressDetector | IngressFailure | Ingress rules pointing to missing or endpoint-less backend services |
| 8 | PVCDetector | PVCFailure | Unbound PVCs (Pending/Lost) and FailedMount events |
| 9 | HPADetector | HPAMisconfigured | Locked scaling (min=max), saturated at max replicas with high CPU |
| 10 | DNSDetector | DNSFailure | DNS resolution errors in pod logs + unhealthy CoreDNS pods |
| 11 | RBACDetector | RBACDenied | Forbidden events and RBAC denial patterns in logs |
| 12 | NetworkPolicyDetector | NetworkPolicyBlock | Connection timeouts with NetworkPolicy objects present in namespace |
| 13 | CNIDetector | CNIFailure | NetworkPluginNotReady, IP/CIDR exhaustion on nodes |
| 14 | ServiceMeshDetector | ServiceMeshFailure | Istio/Linkerd mTLS errors, circuit breaker trips, sidecar failures |
| 15 | NodePressureDetector | NodePressure | MemoryPressure, DiskPressure, PIDPressure, NotReady nodes |
| 16 | QuotaDetector | QuotaExceeded | FailedCreate events with exceeded ResourceQuota messages |
| 17 | RolloutDetector | FailedRollout | ProgressDeadlineExceeded, Available=False deployment conditions |
| 18 | StorageDetector | StorageFailure | CSI driver errors, FailedAttachVolume, missing StorageClass |

## Detection Output

Every detector returns a list of DetectionResult objects:

```python
DetectionResult(
    detected=True,
    incident_type="CrashLoopBackOff",
    severity="critical",                    # critical / high / medium / low
    reason="Container 'app' is CrashLooping (restarts=18)",
    evidence=[Evidence(source="detector", content="...", relevance=0.9)],
    affected_resource="production/payment-api-abc-xyz",
    namespace="production",
    workload="payment-api",
    pod_name="payment-api-abc-xyz",
    raw_signals={"restart_count": 18, "phase": "Running"},
)
```

## Signal Sources

Detectors consume different parts of the cluster state:

| Source | Used By |
|---|---|
| Pod status + container statuses | CrashLoop, OOMKill, ImagePull, PendingPods |
| K8s events | ProbeFailure, RBAC, Quota, CNI, Rollout, Storage |
| Pod logs (recent_logs) | DNS, RBAC, NetworkPolicy, CNI, ServiceMesh |
| Services + endpoints | Service, Ingress |
| PVCs | PVC, Storage |
| HPAs | HPA |
| Nodes | NodePressure, CNI |
| Deployments | Rollout |
| NetworkPolicies | NetworkPolicy |
