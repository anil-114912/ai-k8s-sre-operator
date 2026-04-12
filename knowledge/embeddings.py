"""TF-IDF and optional sentence-transformer embeddings for incident similarity search."""
from __future__ import annotations

import json
import logging
import math
import re
from collections import Counter
from typing import Dict, List

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Sentence-transformers optional backend
# ---------------------------------------------------------------------------

_sentence_transformer_model = None
_sentence_transformer_available = False

try:
    from sentence_transformers import SentenceTransformer as _ST  # type: ignore
    _sentence_transformer_available = True
    logger.debug("sentence-transformers is available")
except ImportError:
    logger.debug("sentence-transformers not installed — using TF-IDF fallback")


def _tokenize(text: str) -> List[str]:
    """Lowercase and tokenize text into words.

    Args:
        text: Input text string.

    Returns:
        List of lowercase tokens.
    """
    return re.findall(r"[a-z0-9]+", text.lower())


def _tf(tokens: List[str]) -> Dict[str, float]:
    """Compute term frequency for a list of tokens.

    Args:
        tokens: List of tokens.

    Returns:
        Dict mapping token to TF score.
    """
    if not tokens:
        return {}
    counts = Counter(tokens)
    total = len(tokens)
    return {term: count / total for term, count in counts.items()}


class TFIDFEmbedder:
    """Lightweight TF-IDF vectoriser for incident text similarity."""

    def __init__(self) -> None:
        """Initialise an empty embedder (no pre-fitted corpus required)."""
        self._idf: Dict[str, float] = {}
        self._vocabulary: Dict[str, int] = {}
        self._fitted = False

    def fit(self, documents: List[str]) -> None:
        """Fit IDF scores on a corpus of documents.

        Args:
            documents: List of text documents to fit on.
        """
        if not documents:
            return

        n = len(documents)
        df: Counter = Counter()
        for doc in documents:
            tokens = set(_tokenize(doc))
            df.update(tokens)

        self._idf = {}
        for term, count in df.items():
            self._idf[term] = math.log((n + 1) / (count + 1)) + 1.0

        # Build vocabulary from IDF keys
        self._vocabulary = {term: i for i, term in enumerate(sorted(self._idf.keys()))}
        self._fitted = True
        logger.debug("TFIDFEmbedder fitted on %d documents, vocab size=%d", n, len(self._vocabulary))

    def transform(self, text: str) -> List[float]:
        """Transform text into a TF-IDF vector.

        Args:
            text: Text to embed.

        Returns:
            Dense float vector (zero-padded to vocabulary size).
        """
        if not self._fitted:
            # Degenerate case: fit on the single document
            self.fit([text])

        tokens = _tokenize(text)
        tf_scores = _tf(tokens)
        vec_size = len(self._vocabulary)

        if vec_size == 0:
            return []

        vec = [0.0] * vec_size
        for term, tf_val in tf_scores.items():
            if term in self._vocabulary:
                idx = self._vocabulary[term]
                idf = self._idf.get(term, 1.0)
                vec[idx] = tf_val * idf

        # L2 normalise
        norm = math.sqrt(sum(v * v for v in vec))
        if norm > 0:
            vec = [v / norm for v in vec]

        return vec

    def embed_incident(self, incident_text: str) -> List[float]:
        """Embed a single incident description.

        Args:
            incident_text: Concatenated incident text for embedding.

        Returns:
            TF-IDF embedding vector.
        """
        return self.transform(incident_text)

    @staticmethod
    def cosine_similarity(vec_a: List[float], vec_b: List[float]) -> float:
        """Compute cosine similarity between two vectors.

        Args:
            vec_a: First vector.
            vec_b: Second vector.

        Returns:
            Cosine similarity in [0, 1].
        """
        if not vec_a or not vec_b:
            return 0.0

        min_len = min(len(vec_a), len(vec_b))
        dot = sum(vec_a[i] * vec_b[i] for i in range(min_len))
        # Vectors are pre-normalised so dot = cosine similarity
        return max(0.0, min(1.0, dot))

    @staticmethod
    def to_json(vec: List[float]) -> str:
        """Serialise a vector to a JSON string for storage.

        Args:
            vec: Float vector.

        Returns:
            JSON string.
        """
        return json.dumps(vec)

    @staticmethod
    def from_json(s: str) -> List[float]:
        """Deserialise a vector from a JSON string.

        Args:
            s: JSON string.

        Returns:
            Float vector.
        """
        if not s:
            return []
        try:
            return json.loads(s)
        except json.JSONDecodeError:
            return []


# ---------------------------------------------------------------------------
# IncidentEmbedder — enhanced embedder with sentence-transformers fallback
# ---------------------------------------------------------------------------

class IncidentEmbedder:
    """Embeds incident descriptions using sentence-transformers if available, else TF-IDF."""

    _ST_MODEL_NAME = "all-MiniLM-L6-v2"

    def __init__(self) -> None:
        """Initialise the embedder."""
        self._tfidf = TFIDFEmbedder()
        self._st_model = None
        self._use_st = False

        if _sentence_transformer_available:
            try:
                self._st_model = _ST(self._ST_MODEL_NAME)  # type: ignore
                self._use_st = True
                logger.info("IncidentEmbedder: using sentence-transformers (%s)", self._ST_MODEL_NAME)
            except Exception as exc:
                logger.warning("Failed to load sentence-transformers model: %s — using TF-IDF", exc)
        else:
            logger.info("IncidentEmbedder: using TF-IDF (sentence-transformers not installed)")

    def embed(self, text: str) -> List[float]:
        """Embed a text string to a float vector.

        Args:
            text: Text to embed.

        Returns:
            Float vector representation.
        """
        if self._use_st and self._st_model is not None:
            try:
                vec = self._st_model.encode(text, convert_to_numpy=True)
                return [float(v) for v in vec]
            except Exception as exc:
                logger.warning("sentence-transformers encode failed: %s — falling back to TF-IDF", exc)
        return self._tfidf.transform(text)

    def refit(self, texts: List[str]) -> None:
        """Retrain the TF-IDF vectoriser on all stored incident texts.

        Called after new incidents are added to keep the vocabulary current.
        For sentence-transformers this is a no-op (model is pre-trained).

        Args:
            texts: List of incident text strings to fit on.
        """
        if not self._use_st:
            self._tfidf.fit(texts)
            logger.info("IncidentEmbedder: TF-IDF refitted on %d texts", len(texts))

    @staticmethod
    def similarity(a: List[float], b: List[float]) -> float:
        """Compute cosine similarity between two embedding vectors.

        Args:
            a: First vector.
            b: Second vector.

        Returns:
            Cosine similarity in [0.0, 1.0].
        """
        return TFIDFEmbedder.cosine_similarity(a, b)

    def embed_incident(self, incident_text: str) -> List[float]:
        """Embed a single incident description (alias for embed).

        Args:
            incident_text: Concatenated incident text.

        Returns:
            Embedding vector.
        """
        return self.embed(incident_text)

    @staticmethod
    def to_json(vec: List[float]) -> str:
        """Serialise a vector to JSON for storage."""
        return TFIDFEmbedder.to_json(vec)

    @staticmethod
    def from_json(s: str) -> List[float]:
        """Deserialise a vector from a JSON string."""
        return TFIDFEmbedder.from_json(s)
