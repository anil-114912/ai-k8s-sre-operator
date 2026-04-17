"""Multi-cluster registry — tracks cluster endpoints, health, and metadata.

This implements the Cluster Registry component described in docs/multi_cluster.md.
Each cluster agent registers here; the control plane uses this registry to fan
out queries and aggregate results.

Usage::

    registry = ClusterRegistry()
    registry.register(ClusterInfo(
        cluster_id="us-east-1-prod",
        name="US East Production",
        api_url="https://sre-operator.us-east-1.internal:8000",
        provider="aws",
        region="us-east-1",
        environment="production",
        tags=["critical", "public-facing"],
    ))

    cluster = registry.get("us-east-1-prod")
    registry.update_health("us-east-1-prod", score=92, grade="A")
"""

from __future__ import annotations

import logging
import threading
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


@dataclass
class ClusterHealth:
    """Most-recent health snapshot for a cluster."""

    score: float = 100.0        # 0–100
    grade: str = "A"
    incident_count: int = 0
    last_updated: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    status: str = "unknown"     # healthy | degraded | critical | unknown

    @classmethod
    def from_score(cls, score: float, incident_count: int = 0) -> "ClusterHealth":
        if score >= 90:
            grade, status = "A", "healthy"
        elif score >= 75:
            grade, status = "B", "healthy"
        elif score >= 55:
            grade, status = "C", "degraded"
        elif score >= 35:
            grade, status = "D", "degraded"
        else:
            grade, status = "F", "critical"
        return cls(score=score, grade=grade, incident_count=incident_count, status=status)


@dataclass
class ClusterInfo:
    """Registration record for a single cluster."""

    cluster_id: str
    name: str
    api_url: str
    provider: str = "unknown"        # aws | gcp | azure | on-prem
    region: str = ""
    environment: str = "unknown"     # production | staging | development
    tags: List[str] = field(default_factory=list)
    registered_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    last_seen: Optional[str] = None
    health: ClusterHealth = field(default_factory=ClusterHealth)
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        d = asdict(self)
        return d

    def is_reachable(self) -> bool:
        return self.last_seen is not None

    def mark_seen(self) -> None:
        self.last_seen = datetime.now(timezone.utc).isoformat()


class ClusterRegistry:
    """Thread-safe registry of all clusters in the fleet.

    The registry is the source of truth for:
    - Which clusters exist
    - Their API endpoints
    - Their current health scores
    - Their last-seen heartbeat timestamps
    """

    def __init__(self) -> None:
        self._clusters: Dict[str, ClusterInfo] = {}
        self._lock = threading.RLock()

    # ------------------------------------------------------------------
    # CRUD
    # ------------------------------------------------------------------

    def register(self, cluster: ClusterInfo) -> None:
        """Register or update a cluster."""
        with self._lock:
            existing = self._clusters.get(cluster.cluster_id)
            if existing:
                # Preserve health data on re-register
                cluster.health = existing.health
                logger.info("Cluster re-registered: %s", cluster.cluster_id)
            else:
                logger.info("Cluster registered: %s (%s)", cluster.cluster_id, cluster.api_url)
            self._clusters[cluster.cluster_id] = cluster

    def deregister(self, cluster_id: str) -> bool:
        """Remove a cluster from the registry. Returns True if it existed."""
        with self._lock:
            if cluster_id in self._clusters:
                del self._clusters[cluster_id]
                logger.info("Cluster deregistered: %s", cluster_id)
                return True
            return False

    def get(self, cluster_id: str) -> Optional[ClusterInfo]:
        """Return a cluster by ID, or None if not found."""
        with self._lock:
            return self._clusters.get(cluster_id)

    def list_all(
        self,
        environment: Optional[str] = None,
        provider: Optional[str] = None,
        tag: Optional[str] = None,
    ) -> List[ClusterInfo]:
        """Return all clusters, optionally filtered."""
        with self._lock:
            clusters = list(self._clusters.values())

        if environment:
            clusters = [c for c in clusters if c.environment == environment]
        if provider:
            clusters = [c for c in clusters if c.provider == provider]
        if tag:
            clusters = [c for c in clusters if tag in c.tags]

        return clusters

    # ------------------------------------------------------------------
    # Health management
    # ------------------------------------------------------------------

    def update_health(
        self,
        cluster_id: str,
        score: float,
        incident_count: int = 0,
    ) -> bool:
        """Update health score for a cluster. Returns False if cluster not found."""
        with self._lock:
            cluster = self._clusters.get(cluster_id)
            if not cluster:
                return False
            cluster.health = ClusterHealth.from_score(score, incident_count)
            cluster.mark_seen()
            logger.debug(
                "Health updated: %s score=%.1f grade=%s",
                cluster_id,
                score,
                cluster.health.grade,
            )
            return True

    def heartbeat(self, cluster_id: str) -> bool:
        """Record that an agent checked in (no health change). Returns False if unknown."""
        with self._lock:
            cluster = self._clusters.get(cluster_id)
            if cluster:
                cluster.mark_seen()
                return True
            return False

    # ------------------------------------------------------------------
    # Fleet aggregation
    # ------------------------------------------------------------------

    def fleet_health_summary(self) -> Dict[str, Any]:
        """Return an aggregated health view across all registered clusters."""
        with self._lock:
            clusters = list(self._clusters.values())

        if not clusters:
            return {"total_clusters": 0, "healthy": 0, "degraded": 0, "critical": 0, "unknown": 0}

        statuses: Dict[str, int] = {"healthy": 0, "degraded": 0, "critical": 0, "unknown": 0}
        scores = []
        for c in clusters:
            s = c.health.status
            statuses[s] = statuses.get(s, 0) + 1
            if c.health.score > 0:
                scores.append(c.health.score)

        avg_score = sum(scores) / len(scores) if scores else 0.0

        return {
            "total_clusters": len(clusters),
            **statuses,
            "average_health_score": round(avg_score, 1),
            "clusters": [
                {
                    "cluster_id": c.cluster_id,
                    "name": c.name,
                    "environment": c.environment,
                    "score": c.health.score,
                    "grade": c.health.grade,
                    "status": c.health.status,
                    "last_seen": c.last_seen,
                }
                for c in sorted(clusters, key=lambda x: x.health.score)
            ],
        }

    def get_critical_clusters(self) -> List[ClusterInfo]:
        """Return clusters with F grade or 'critical' status."""
        with self._lock:
            return [
                c for c in self._clusters.values()
                if c.health.status == "critical" or c.health.grade == "F"
            ]

    def get_by_environment(self, environment: str) -> List[ClusterInfo]:
        return self.list_all(environment=environment)

    # ------------------------------------------------------------------
    # Serialisation helpers
    # ------------------------------------------------------------------

    def to_dict(self) -> Dict[str, Any]:
        with self._lock:
            return {
                "total": len(self._clusters),
                "clusters": [c.to_dict() for c in self._clusters.values()],
            }

    def __len__(self) -> int:
        return len(self._clusters)

    def __contains__(self, cluster_id: str) -> bool:
        with self._lock:
            return cluster_id in self._clusters


# Module-level singleton
_default_registry: Optional[ClusterRegistry] = None
_registry_lock = threading.Lock()


def get_cluster_registry() -> ClusterRegistry:
    """Return the module-level singleton ClusterRegistry."""
    global _default_registry
    if _default_registry is None:
        with _registry_lock:
            if _default_registry is None:
                _default_registry = ClusterRegistry()
    return _default_registry
