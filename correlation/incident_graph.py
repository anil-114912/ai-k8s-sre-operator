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

        Args:
            incident_type: The detected incident type string.
            namespace: Kubernetes namespace of the incident.
            workload: Primary affected workload name.
            pod_name: Name of the affected pod (if any).
            cluster_state: Full cluster state dict.

        Returns:
            Self (populated graph).
        """
        # Primary pod node
        if pod_name:
            pod_node = ResourceNode("Pod", pod_name, namespace, "symptom")
            self.add_node(pod_node)

        # Parent deployment
        deployments = cluster_state.get("deployments", [])
        for dep in deployments:
            if dep.get("name") == workload and dep.get("namespace") == namespace:
                dep_node = ResourceNode("Deployment", workload, namespace, "related")
                self.add_node(dep_node)
                if pod_name:
                    self.add_edge(dep_node.key, pod_node.key, "owns")
                break

        # Related services
        services = cluster_state.get("services", [])
        for svc in services:
            if svc.get("namespace") != namespace:
                continue
            selector = svc.get("selector", {})
            # Check if service could select this workload
            if any(workload in str(v) for v in selector.values()):
                svc_node = ResourceNode("Service", svc.get("name", ""), namespace, "related")
                self.add_node(svc_node)
                if pod_name:
                    self.add_edge(svc_node.key, pod_node.key, "selects")

        # Related PVCs
        if incident_type in ("PVCFailure", "PodPending"):
            pvcs = cluster_state.get("pvcs", [])
            for pvc in pvcs:
                if pvc.get("namespace") != namespace:
                    continue
                pvc_node = ResourceNode(
                    "PVC",
                    pvc.get("name", ""),
                    namespace,
                    "root_cause" if incident_type == "PVCFailure" else "contributing_factor",
                )
                self.add_node(pvc_node)
                if pod_name:
                    self.add_edge(pod_node.key, pvc_node.key, "mounts")

        logger.debug(
            "Built incident graph: %d nodes, %d edges for %s/%s",
            len(self.nodes),
            len(self.edges),
            namespace,
            workload,
        )
        return self

    def to_summary(self) -> str:
        """Produce a human-readable summary of the graph for LLM context."""
        lines = [f"Resource graph: {len(self.nodes)} nodes, {len(self.edges)} edges"]
        for node in self.nodes.values():
            lines.append(f"  [{node.role}] {node.kind}/{node.name} ({node.namespace})")
        for frm, to, rel in self.edges:
            lines.append(f"  {frm} --[{rel}]--> {to}")
        return "\n".join(lines)
