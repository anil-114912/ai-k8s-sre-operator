# Multi-Cluster Design

This document describes the planned architecture for federating the AI K8s SRE Operator across multiple Kubernetes clusters. This is a Phase 4 planned feature — not yet implemented.

---

## Problem Statement

In a production environment, workloads typically span multiple clusters:

- A primary region cluster (`us-east-1`) and a failover cluster (`eu-west-1`)
- Separate clusters for production, staging, and development
- Dedicated clusters for different business units or teams
- Service mesh federations where a single service spans two clusters

A single-cluster SRE operator cannot:
- Correlate incidents across cluster boundaries (e.g. a dependency failure in one cluster causing failures in another)
- Provide a unified view of cluster health across the fleet
- Share learned failure patterns between clusters
- Apply consistent remediation policies organization-wide

---

## Architecture

```
┌────────────────────────────────────────────────────────────────────────┐
│  Control Plane (Central Aggregator)                                     │
│                                                                         │
│  ┌─────────────────┐   ┌─────────────────┐   ┌──────────────────────┐  │
│  │  Cluster Registry│   │ Unified KB       │   │  Cross-cluster       │  │
│  │  (cluster → URL) │   │ (shared patterns)│   │  Incident Correlator │  │
│  └─────────────────┘   └─────────────────┘   └──────────────────────┘  │
│                                                                         │
│  ┌─────────────────────────────────────────────────────────────────┐   │
│  │  Aggregated Dashboard  (unified incident timeline, health fleet) │   │
│  └─────────────────────────────────────────────────────────────────┘   │
└────────────────────────────────────────────────────────────────────────┘
        │                      │                       │
        ▼                      ▼                       ▼
┌──────────────┐     ┌──────────────┐       ┌──────────────┐
│ Cluster Agent│     │ Cluster Agent│       │ Cluster Agent│
│  us-east-1   │     │  eu-west-1   │       │  staging     │
│              │     │              │       │              │
│ 18 detectors │     │ 18 detectors │       │ 18 detectors │
│ Local RCA    │     │ Local RCA    │       │ Local RCA    │
│ Local store  │     │ Local store  │       │ Local store  │
└──────────────┘     └──────────────┘       └──────────────┘
```

---

## Components

### Cluster Registry

A registry mapping cluster identifiers to their API endpoints and metadata.

```yaml
# cluster_registry.yaml
clusters:
  - id: us-east-1-prod
    name: "US East Production"
    api_url: https://sre-operator.us-east-1.internal:8000
    provider: aws
    region: us-east-1
    environment: production
    tags:
      - critical
      - public-facing

  - id: eu-west-1-prod
    name: "EU West Production"
    api_url: https://sre-operator.eu-west-1.internal:8000
    provider: aws
    region: eu-west-1
    environment: production
    tags:
      - critical
      - gdpr-scope

  - id: staging
    name: "Shared Staging"
    api_url: https://sre-operator.staging.internal:8000
    provider: aws
    region: us-east-1
    environment: staging
```

**Proposed API endpoint:**
```
GET  /api/v1/clusters                     # List registered clusters
POST /api/v1/clusters                     # Register a new cluster
GET  /api/v1/clusters/{id}/health         # Health score for one cluster
GET  /api/v1/clusters/{id}/incidents      # Incidents from one cluster
```

### Per-Cluster Agent

Each cluster runs its own `OperatorController` instance that:
1. Observes local cluster state (pods, events, services, nodes)
2. Runs all 18 detectors locally
3. Performs local RCA using the shared KB + local incident memory
4. Pushes incident summaries to the control plane
5. Pulls updated KB patterns from the control plane periodically

The local agent is autonomous — it continues working even if the control plane is unreachable. It queues outbound events and replays them when connectivity is restored.

### Aggregation Layer

The central control plane exposes aggregated views:

```
GET /api/v1/fleet/health          # Health scores across all clusters
GET /api/v1/fleet/incidents       # All incidents across all clusters
GET /api/v1/fleet/patterns        # Most common failure patterns fleet-wide
```

---

## Cross-Cluster Incident Correlation

When the same workload or service appears to fail across multiple clusters simultaneously, the correlator checks for:

1. **Shared dependency failure** — e.g. a shared database or external API is down
2. **Cascading failures** — Cluster A's payment-api calls Cluster B's fraud-service; fraud-service fails → payment-api fails
3. **Config rollout** — A global config change was applied to all clusters at once
4. **Cloud provider event** — AWS us-east-1 has an availability zone issue affecting both clusters

### Correlation rules

```python
# Proposed cross-cluster correlation rule
class CrossClusterCorrelator:
    def correlate(self, incidents_by_cluster: Dict[str, List[Incident]]) -> List[CrossClusterEvent]:
        # Rule 1: same incident type in 2+ clusters within 5 minutes → cloud event
        # Rule 2: shared service name failing in 2+ clusters → shared dependency
        # Rule 3: incident cascade matches known service topology → propagation
        ...
```

---

## Unified Knowledge Base

The unified KB is a superset of all cluster-specific and generic patterns:

```
knowledge/failures/
  generic_k8s.yaml      # Used by all clusters
  eks.yaml              # Used by aws clusters
  aks.yaml              # Used by azure clusters
  gke.yaml              # Used by gcp clusters
  learned_fleet.yaml    # Promoted patterns from fleet-wide learning
  learned_us_east_1.yaml  # Cluster-specific learned patterns
```

**Promotion pipeline:**
1. A pattern is learned in one cluster (local `learned.yaml`)
2. If it recurs in 2+ clusters → promoted to `learned_fleet.yaml`
3. If it passes quality threshold → merged into appropriate provider YAML

---

## Per-Cluster Policy Isolation

Each cluster can override global remediation policies:

```yaml
# cluster_policies.yaml
global:
  dry_run: true
  auto_fix_enabled: false
  denied_namespaces: ["kube-system", "kube-public"]

clusters:
  us-east-1-prod:
    auto_fix_enabled: false        # Production: never auto-fix
    approval_required_always: true

  staging:
    auto_fix_enabled: true         # Staging: allow auto-fix
    denied_namespaces: []          # No namespace restrictions in staging
```

---

## Access Control

In a multi-cluster deployment, the control plane API requires authentication and authorisation:

| Role | Permissions |
|---|---|
| Viewer | Read incidents, health scores, KB patterns across all clusters |
| Cluster Responder | Approve and execute remediations for a specific cluster |
| Fleet Responder | Approve and execute remediations across all clusters |
| Admin | Full access including cluster registration, policy management |

RBAC is enforced via JWT tokens with cluster-scoped claims:

```json
{
  "sub": "alice@example.com",
  "roles": ["cluster_responder"],
  "cluster_scope": ["us-east-1-prod", "staging"],
  "exp": 1735689600
}
```

---

## Implementation Plan

| Phase | Work | Status |
|---|---|---|
| 4.1 | Cluster registry (API + storage) | Planned |
| 4.2 | Per-cluster agent push protocol (incident sync) | Planned |
| 4.3 | Aggregated incident API (`/api/v1/fleet/`) | Planned |
| 4.4 | Cross-cluster incident correlator | Planned |
| 4.5 | Unified KB sync and fleet-wide pattern promotion | Planned |
| 4.6 | Per-cluster policy isolation | Planned |
| 4.7 | RBAC / OIDC integration | Planned |
| 4.8 | Fleet health dashboard tab | Planned |

---

## Deployment Topology

```bash
# Control plane (central aggregator)
helm install sre-control-plane ./helm/ai-k8s-sre-operator \
  --set mode=control-plane \
  --set database.type=postgres \
  --set auth.oidc.enabled=true

# Per-cluster agent (one per cluster)
helm install sre-agent ./helm/ai-k8s-sre-operator \
  --set mode=cluster-agent \
  --set agent.controlPlaneUrl=https://sre-control-plane.internal \
  --set agent.clusterId=us-east-1-prod \
  --set cluster.provider=aws
```

---

## Data Flow

```
Cluster Agent (us-east-1)           Control Plane
       │                                  │
       │  detect CrashLoop in prod/api    │
       │  run local RCA → confidence 0.94 │
       │─────────── POST /fleet/incidents ─▶│
       │                                  │  store incident
       │                                  │  check cross-cluster correlation
       │                                  │  update fleet health score
       │                                  │
       │  (5 min later)                   │
       │◀─────── GET /fleet/kb/updates ───│
       │  pull new learned_fleet.yaml     │
       │  reload KB                       │
```

---

## See Also

- [docs/deployment.md](deployment.md) — Single-cluster deployment
- [docs/architecture.md](architecture.md) — Single-cluster architecture
- [docs/safety.md](safety.md) — Remediation safety guardrails
