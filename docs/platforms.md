# Supported Platforms

## Cloud Providers

| Platform | Detection | KB Patterns | Provider Boost |
|---|---|---|---|
| Generic Kubernetes | All 18 detectors | 12 generic patterns | Default scoring |
| AWS EKS | All 18 + ENI/IRSA awareness | 4 EKS-specific patterns | provider=aws boosts EKS patterns |
| Azure AKS | All 18 + Managed Identity awareness | 3 AKS-specific patterns | provider=azure boosts AKS patterns |
| GCP GKE | All 18 + Workload Identity awareness | 3 GKE-specific patterns | provider=gcp boosts GKE patterns |
| Self-hosted | All 18 detectors | All generic patterns | Default scoring |

## EKS-Specific Patterns

| ID | Pattern |
|---|---|
| eks-001 | Node group capacity — EC2 InsufficientInstanceCapacity |
| eks-002 | IAM IRSA (pod identity) missing or misconfigured |
| eks-003 | ENI IP address exhaustion (VPC CNI) |
| eks-004 | EKS add-on version incompatible after upgrade |

## AKS-Specific Patterns

| ID | Pattern |
|---|---|
| aks-001 | Node pool capacity — Azure VM quota exceeded |
| aks-002 | Managed Identity missing permissions |
| aks-003 | Azure Disk volume attach failure (ReadWriteOnce cross-node) |

## GKE-Specific Patterns

| ID | Pattern |
|---|---|
| gke-001 | Workload Identity missing or misconfigured |
| gke-002 | Autopilot resource quota exceeded |
| gke-003 | Filestore (NFS) mount failure |

## Networking

| Technology | Detection | KB Patterns |
|---|---|---|
| CoreDNS | DNSDetector checks pod health + log errors | net-001 (DNS resolution failure) |
| Calico / Cilium / Flannel | CNIDetector checks NetworkPluginNotReady + IP exhaustion | net-005 (CNI IP exhaustion) |
| Istio | ServiceMeshDetector checks mTLS, circuit breaker, sidecar | net-006 (mTLS mismatch), net-007 (circuit breaker) |
| Linkerd | ServiceMeshDetector checks proxy errors | net-006, net-007 |
| NetworkPolicy | NetworkPolicyDetector checks connection timeouts + policy objects | net-002 (NetworkPolicy blocking) |
| Gateway API | IngressDetector covers gateway backends | net-004 (backend unavailable) |

## Storage

| Technology | Detection | KB Patterns |
|---|---|---|
| CSI drivers (any) | StorageDetector checks FailedMount, FailedAttachVolume, missing driver | stor-003 (CSI driver missing) |
| AWS EBS | PVCDetector + StorageDetector | stor-001, stor-002, stor-006 |
| Azure Disk | PVCDetector + StorageDetector | aks-003 (attach failure), stor-002 |
| GCP Persistent Disk | PVCDetector + StorageDetector | stor-001, stor-002 |
| NFS / Filestore | PVCDetector | gke-003 (Filestore mount) |
| StorageClass | StorageDetector checks missing StorageClass | stor-004 (StorageClass missing) |

## Security

| Area | Detection | KB Patterns |
|---|---|---|
| RBAC | RBACDetector checks Forbidden events + log patterns | sec-001 (forbidden verb), sec-002 (missing SA) |
| Pod Security Admission | Detected via events | sec-003 (PSA violation) |
| Seccomp | Detected via events | sec-004 (seccomp profile missing) |
| Image Signing | Detected via admission webhook events | sec-005 (signature verification) |
