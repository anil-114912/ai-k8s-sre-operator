"""Builds a graph of related resources for a detected incident."""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Tuple

logger = logging.getLogger(__name__)


class ResourceNode:
    """A node in the incident resource graph."""

    def __init__(self, kind: str, name: str, namespace: str = "", role: str = "unknown") -> None:
        """Initialise a resource node.

        Args:
            kind: Kubernetes resource kind (Pod, Deployment, Service, etc.)
            name: Resource name.
            namespace: Kubernetes namespace.
            role: Signal role: root_cause, contributing_factor, symptom, related.
        """
        self.kind = kind
        self.name = name
        self.namespace = namespace
        self.role = role
        self.metadata: Dict[str, Any] = {}

    @property
    def key(self) -> str:
        """Unique identifier for this node."""
        return f"{self.kind}/{self.namespace}/{self.name}"

    def __repr__(self) -> str:
        """String representation."""
        return f"ResourceNode({self.kind}/{self.name}, role={self.role})"


class IncidentGraph:
    """Directed graph of resources involved in an incident."""

    def __init__(self) -> None:
        """Initialise an empty incident graph."""
        self.nodes: Dict[str, ResourceNode] = {}
        self.edges: List[Tuple[str, str, str]] = []  # (from_key, to_key, relationship)

    def add_node(self, node: ResourceNode) -> None:
        """Add or update a resource node in the graph."""
        self.nodes[node.key] = node

    def add_edge(self, from_key: str, to_key: str, relationship: str) -> None:
        """Add a directional edge between two resource nodes."""
        self.edges.append((from_key, to_key, relationship))

    def build_from_incident(
        self,
        incident_type: str,
        namespace: str,
        workload: str,
        pod_name: str,
        cluster_state: Dict[str, Any],
    ) -> "IncidentGraph":
        """Construct the resource graph for a detected incident.

        Builds the full causal chain based on incident type:
          - CrashLoop / OOM / Probe: Deployment → ReplicaSet → Pod
          - ServiceMismatch / IngressFailure: Ingress → Service → Endpoints → Pod
          - PVCFailure / PodPending: Pod → PVC → StorageClass → Node
          - HPAMisconfigured: HPA → Deployment → Pod
          - NodePressure: Node → Pod (eviction)

        Args:
            incident_type: The detected incident type string.
            namespace: Kubernetes namespace of the incident.
            workload: Primary affected workload name.
            pod_name: Name of the affected pod (if any).
            cluster_state: Full cluster state dict.

        Returns:
            Self (populated graph).
        """
        pod_node = None

        # Primary pod node — always the observable symptom
        if pod_name:
            pod_node = ResourceNode("Pod", pod_name, namespace, "symptom")
            self.add_node(pod_node)

        # ------------------------------------------------------------------
        # Deployment → ReplicaSet → Pod chain
        # ------------------------------------------------------------------
        dep_node = None
        deployments = cluster_state.get("deployments", [])
        for dep in deployments:
            if dep.get("name") == workload and dep.get("namespace") == namespace:
                role = self._classify_deployment_role(incident_type)
                dep_node = ResourceNode("Deployment", workload, namespace, role)
                self.add_node(dep_node)
                if pod_node:
                    self.add_edge(dep_node.key, pod_node.key, "owns_pod")
                break

        # ReplicaSet (intermediate owner)
        replica_sets = cluster_state.get("replicasets", [])
        for rs in replica_sets:
            if rs.get("namespace") != namespace:
                continue
            owner_refs = rs.get("ownerReferences", [])
            if any(ref.get("name") == workload for ref in owner_refs):
                rs_node = ResourceNode("ReplicaSet", rs.get("name", ""), namespace, "related")
                self.add_node(rs_node)
                if dep_node:
                    self.add_edge(dep_node.key, rs_node.key, "owns_replicaset")
                if pod_node:
                    self.add_edge(rs_node.key, pod_node.key, "owns_pod")
                break

        # ------------------------------------------------------------------
        # HPA → Deployment chain
        # ------------------------------------------------------------------
        hpas = cluster_state.get("hpas", [])
        for hpa in hpas:
            if hpa.get("namespace") != namespace:
                continue
            target = hpa.get("scaleTargetRef", {})
            if target.get("name") == workload:
                hpa_role = "root_cause" if incident_type == "HPAMisconfigured" else "related"
                hpa_node = ResourceNode("HPA", hpa.get("name", ""), namespace, hpa_role)
                self.add_node(hpa_node)
                if dep_node:
                    self.add_edge(hpa_node.key, dep_node.key, "scales")
                break

        # ------------------------------------------------------------------
        # Service → Endpoints → Pod chain
        # ------------------------------------------------------------------
        services = cluster_state.get("services", [])
        for svc in services:
            if svc.get("namespace") != namespace:
                continue
            selector = svc.get("selector", {})
            if not any(workload in str(v) for v in selector.values()):
                continue

            svc_role = "root_cause" if incident_type == "ServiceMismatch" else "related"
            svc_node = ResourceNode("Service", svc.get("name", ""), namespace, svc_role)
            self.add_node(svc_node)
            if pod_node:
                self.add_edge(svc_node.key, pod_node.key, "selects")

            # Ingress → Service chain
            if incident_type in ("IngressFailure", "ServiceMismatch"):
                ingresses = cluster_state.get("ingresses", [])
                for ing in ingresses:
                    if ing.get("namespace") != namespace:
                        continue
                    # Check if any rule backend points to this service
                    rules = ing.get("rules", []) or ing.get("spec", {}).get("rules", [])
                    for rule in rules:
                        for path in rule.get("http", {}).get("paths", []):
                            backend = path.get("backend", {})
                            backend_svc = backend.get("service", {}).get("name") or backend.get(
                                "serviceName"
                            )
                            if backend_svc == svc.get("name"):
                                ing_role = (
                                    "root_cause" if incident_type == "IngressFailure" else "related"
                                )
                                ing_node = ResourceNode(
                                    "Ingress", ing.get("name", ""), namespace, ing_role
                                )
                                self.add_node(ing_node)
                                self.add_edge(ing_node.key, svc_node.key, "routes_to")

        # ------------------------------------------------------------------
        # PVC → StorageClass → Node chain
        # ------------------------------------------------------------------
        if incident_type in ("PVCFailure", "PodPending", "StorageFailure"):
            pvcs = cluster_state.get("pvcs", [])
            for pvc in pvcs:
                if pvc.get("namespace") != namespace:
                    continue
                pvc_role = "root_cause" if incident_type == "PVCFailure" else "contributing_factor"
                pvc_node = ResourceNode("PVC", pvc.get("name", ""), namespace, pvc_role)
                self.add_node(pvc_node)
                if pod_node:
                    self.add_edge(pod_node.key, pvc_node.key, "mounts")

                # StorageClass link
                sc_name = pvc.get("storageClassName")
                if sc_name:
                    sc_node = ResourceNode(
                        "StorageClass",
                        sc_name,
                        "",
                        "root_cause" if incident_type == "StorageFailure" else "related",
                    )
                    self.add_node(sc_node)
                    self.add_edge(pvc_node.key, sc_node.key, "uses_storageclass")

        # ------------------------------------------------------------------
        # Node → Pod (node pressure / eviction)
        # ------------------------------------------------------------------
        if incident_type in ("NodePressure",):
            nodes = cluster_state.get("nodes", [])
            for node in nodes:
                conditions = node.get("conditions", [])
                pressure = [
                    c
                    for c in conditions
                    if c.get("type") in ("MemoryPressure", "DiskPressure", "PIDPressure")
                    and c.get("status") == "True"
                ]
                if pressure:
                    node_obj = ResourceNode(
                        "Node", node.get("name", ""), "", "root_cause"
                    )
                    self.add_node(node_obj)
                    if pod_node:
                        self.add_edge(node_obj.key, pod_node.key, "hosts")

        logger.debug(
            "Built incident graph: %d nodes, %d edges for %s/%s (type=%s)",
            len(self.nodes),
            len(self.edges),
            namespace,
            workload,
            incident_type,
        )
        return self

    def get_root_causes(self) -> List["ResourceNode"]:
        """Return all nodes classified as root_cause."""
        return [n for n in self.nodes.values() if n.role == "root_cause"]

    def get_symptoms(self) -> List["ResourceNode"]:
        """Return all nodes classified as symptom."""
        return [n for n in self.nodes.values() if n.role == "symptom"]

    def to_summary(self) -> str:
        """Produce a human-readable summary of the graph for LLM context."""
        lines = [f"Resource graph: {len(self.nodes)} nodes, {len(self.edges)} edges"]
        # Root causes first
        for node in self.nodes.values():
            marker = "🔴" if node.role == "root_cause" else ("🟡" if node.role == "symptom" else "⚪")
            lines.append(f"  {marker} [{node.role}] {node.kind}/{node.name} ({node.namespace})")
        for frm, to, rel in self.edges:
            lines.append(f"  {frm} --[{rel}]--> {to}")
        return "\n".join(lines)

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _classify_deployment_role(incident_type: str) -> str:
        """Map incident type to the deployment node's role in the graph."""
        root_cause_types = {
            "FailedRollout",
            "OOMKilled",
            "ImagePullBackOff",
        }
        if incident_type in root_cause_types:
            return "root_cause"
        return "related"
