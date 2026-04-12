"""Similarity-based retrieval of past incidents for RAG context."""
from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from knowledge.embeddings import TFIDFEmbedder
from knowledge.incident_store import IncidentStore

logger = logging.getLogger(__name__)

_RECENCY_DECAY_DAYS = 30
_RECENCY_PENALTY = 0.1
_NAMESPACE_BOOST = 0.15
_CLUSTER_BOOST = 0.1
_DEFAULT_FEEDBACK_BOOST = 0.3


@dataclass
class RetrievedIncident:
    """A past incident retrieved by similarity search with scoring metadata."""

    incident_id: str
    title: str
    incident_type: str
    root_cause: str
    suggested_fix: str
    similarity: float
    feedback_boost: float
    resolution_outcome: Optional[str]
    namespace: str
    created_at: str


class SimilarityRetriever:
    """Retrieves the K most similar past incidents using TF-IDF cosine similarity.

    Applies feedback boosts, recency decay, namespace/cluster proximity boosts.
    """

    def __init__(
        self,
        store: IncidentStore,
        top_k: int = 3,
        feedback_boost: float = _DEFAULT_FEEDBACK_BOOST,
    ) -> None:
        """Initialise the retriever.

        Args:
            store: IncidentStore instance providing past incident data.
            top_k: Number of similar incidents to return.
            feedback_boost: Multiplier boost applied to incidents with positive feedback.
        """
        self._store = store
        self._top_k = top_k
        self._feedback_boost = feedback_boost
        self._embedder = TFIDFEmbedder()

    def find_similar(self, query_text: str) -> List[Dict[str, Any]]:
        """Find the K most similar past incidents to the query text.

        Returns plain dicts for backward compatibility.

        Args:
            query_text: Text description of the new incident.

        Returns:
            List of up to top_k similar incident dicts, sorted by adjusted score.
        """
        retrieved = self.retrieve(
            query_text=query_text,
            namespace=None,
            cluster_name=None,
        )
        results = []
        for r in retrieved:
            results.append({
                "id": r.incident_id,
                "type": r.incident_type,
                "namespace": r.namespace,
                "root_cause": r.root_cause,
                "suggested_fix": r.suggested_fix,
                "similarity": round(r.similarity, 4),
                "resolved": r.resolution_outcome == "resolved",
                "feedback_boost": r.feedback_boost,
                "resolution_outcome": r.resolution_outcome,
                "created_at": r.created_at,
                "title": r.title,
            })
        return results

    def retrieve(
        self,
        query_text: str,
        namespace: Optional[str] = None,
        cluster_name: Optional[str] = None,
    ) -> List[RetrievedIncident]:
        """Find the K most similar past incidents with rich scoring.

        Scoring pipeline:
        1. Base cosine similarity from TF-IDF embeddings
        2. Feedback boost: success=True adds +feedback_boost fraction
        3. Recency decay: incidents older than 30 days lose 0.1 points
        4. Namespace boost: same namespace adds +0.15
        5. Cluster boost: same cluster adds +0.1

        Args:
            query_text: Text description of the new incident.
            namespace: Optional current incident namespace for proximity boost.
            cluster_name: Optional cluster name for cluster proximity boost.

        Returns:
            List of RetrievedIncident objects sorted by adjusted score descending.
        """
        all_incidents = self._store.get_all_embeddings()
        if not all_incidents:
            logger.debug("No past incidents in store for similarity search")
            return []

        # Fit TF-IDF on corpus
        corpus_texts = []
        for inc in all_incidents:
            corpus_texts.append(
                f"{inc.get('type', '')} {inc.get('namespace', '')} "
                f"{inc.get('root_cause', '')} {inc.get('title', '')}"
            )
        if corpus_texts:
            self._embedder.fit(corpus_texts)

        query_vec = self._embedder.transform(query_text)

        now = datetime.now(timezone.utc)
        scored: List[tuple] = []

        for inc in all_incidents:
            stored_vec = inc.get("embedding", [])
            if not stored_vec:
                continue

            base_sim = TFIDFEmbedder.cosine_similarity(query_vec, stored_vec)

            # 1. Feedback boost
            feedback_score = float(inc.get("feedback_score") or 0.0)
            applied_boost = 0.0
            if feedback_score > 0:
                applied_boost = self._feedback_boost
                base_sim = base_sim * (1.0 + applied_boost)

            # 2. Recency decay
            created_at_str = inc.get("created_at")
            if created_at_str:
                try:
                    created_at = datetime.fromisoformat(created_at_str)
                    if created_at.tzinfo is None:
                        created_at = created_at.replace(tzinfo=timezone.utc)
                    age_days = (now - created_at).days
                    if age_days > _RECENCY_DECAY_DAYS:
                        base_sim = max(0.0, base_sim - _RECENCY_PENALTY)
                except (ValueError, TypeError):
                    pass

            # 3. Namespace boost
            if namespace and inc.get("namespace") == namespace:
                base_sim += _NAMESPACE_BOOST

            # 4. Cluster boost
            if cluster_name and inc.get("cluster_name") == cluster_name:
                base_sim += _CLUSTER_BOOST

            final_score = round(base_sim, 4)
            scored.append((final_score, applied_boost, inc))

        scored.sort(key=lambda x: x[0], reverse=True)

        results: List[RetrievedIncident] = []
        for final_score, boost, inc in scored[: self._top_k]:
            results.append(
                RetrievedIncident(
                    incident_id=inc.get("id", ""),
                    title=inc.get("title", ""),
                    incident_type=inc.get("type", ""),
                    root_cause=inc.get("root_cause") or "",
                    suggested_fix=inc.get("suggested_fix") or "",
                    similarity=final_score,
                    feedback_boost=boost,
                    resolution_outcome=inc.get("resolution_outcome"),
                    namespace=inc.get("namespace", ""),
                    created_at=inc.get("created_at") or "",
                )
            )

        logger.info(
            "SimilarityRetriever: found %d similar incidents (top_k=%d)",
            len(results), self._top_k,
        )
        return results
