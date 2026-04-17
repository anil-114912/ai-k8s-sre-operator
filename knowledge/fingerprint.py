"""Incident fingerprinting — deduplication and similarity clustering.

A fingerprint is a stable hash of (incident type, resource, primary error message).
Identical fingerprints mean the same failure is recurring on the same resource.

Uses a two-level approach:
  1. Exact fingerprint: identical type + resource + normalised error → same hash
  2. Fuzzy fingerprint: Jaccard similarity on error token sets → near-duplicate detection
"""

from __future__ import annotations

import hashlib
import logging
import re
from typing import Any, Dict, List, Optional, Set

logger = logging.getLogger(__name__)

# Jaccard similarity threshold for near-duplicate detection
_FUZZY_THRESHOLD = 0.75

# Tokens to strip from error messages before fingerprinting (noise words)
_STRIP_PATTERNS = [
    r"\b[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}\b",  # UUID
    r"\b\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}[Z\+\-\d:]*\b",                 # ISO timestamp
    r"\b[0-9]+\b",                                                              # bare numbers
    r"\s+",                                                                     # extra whitespace
]


class IncidentFingerprinter:
    """Computes and compares incident fingerprints.

    Usage::

        fp = IncidentFingerprinter()

        # Compute a fingerprint
        hash1 = fp.compute(events, resource="payment-api/pod-xyz", error_messages=["secret not found"])
        hash2 = fp.compute(events, resource="payment-api/pod-abc", error_messages=["secret not found"])

        # Exact match (same error, different pod — same fingerprint)
        assert hash1 == hash2

        # Fuzzy match
        assert fp.are_similar(hash1, hash2, threshold=0.75)
    """

    def compute(
        self,
        events: Optional[List[Dict[str, Any]]] = None,
        resource: str = "",
        error_messages: Optional[List[str]] = None,
        incident_type: str = "",
        namespace: str = "",
    ) -> str:
        """Compute a stable fingerprint string for an incident.

        The fingerprint is deterministic: the same failure on the same resource
        always produces the same hash regardless of pod name, timestamp, or replica.

        Args:
            events: List of K8s event dicts (uses reason + message).
            resource: Primary affected resource name (workload, not specific pod).
            error_messages: List of error strings from logs or events.
            incident_type: Incident type string (e.g. "CrashLoopBackOff").
            namespace: Kubernetes namespace.

        Returns:
            A 32-character hex fingerprint string.
        """
        components: List[str] = []

        # Namespace + workload (normalised — strip pod hash suffix)
        normalised_resource = self._normalise_resource(resource)
        if namespace:
            components.append(f"ns:{namespace}")
        if normalised_resource:
            components.append(f"res:{normalised_resource}")
        if incident_type:
            components.append(f"type:{incident_type}")

        # Error message fingerprint — normalised
        all_errors = list(error_messages or [])
        if events:
            for ev in events[:10]:
                reason = ev.get("reason", "")
                msg = ev.get("message", "")
                if ev.get("type") == "Warning" and msg:
                    all_errors.append(f"{reason}: {msg}")

        if all_errors:
            normalised_errors = [self._normalise_error(e) for e in all_errors if e.strip()]
            # Sort for stability (order of events shouldn't matter)
            normalised_errors.sort()
            error_key = "|".join(normalised_errors[:5])  # Top 5 unique errors
            components.append(f"err:{error_key[:300]}")

        fingerprint_text = "::".join(components)
        digest = hashlib.md5(fingerprint_text.encode("utf-8")).hexdigest()  # noqa: S324

        logger.debug("Fingerprint for %s/%s: %s (from: %s)", namespace, resource, digest[:16], fingerprint_text[:100])
        return digest

    def compute_token_set(self, error_messages: List[str]) -> Set[str]:
        """Compute the normalised token set for fuzzy comparison."""
        tokens: Set[str] = set()
        for msg in error_messages:
            normalised = self._normalise_error(msg)
            tokens.update(normalised.split())
        return tokens

    def are_duplicates(
        self,
        fp1: str,
        fp2: str,
    ) -> bool:
        """Return True if two fingerprints are identical (exact duplicate)."""
        return fp1 == fp2

    def jaccard_similarity(
        self,
        errors1: List[str],
        errors2: List[str],
    ) -> float:
        """Compute Jaccard similarity between two error token sets.

        Args:
            errors1: Error message list from incident 1.
            errors2: Error message list from incident 2.

        Returns:
            Float in [0.0, 1.0] — 1.0 means identical token sets.
        """
        set1 = self.compute_token_set(errors1)
        set2 = self.compute_token_set(errors2)
        if not set1 and not set2:
            return 1.0
        if not set1 or not set2:
            return 0.0
        intersection = len(set1 & set2)
        union = len(set1 | set2)
        return intersection / union

    def are_similar(
        self,
        errors1: List[str],
        errors2: List[str],
        threshold: float = _FUZZY_THRESHOLD,
    ) -> bool:
        """Return True if two error sets are similar above the threshold."""
        return self.jaccard_similarity(errors1, errors2) >= threshold

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _normalise_resource(resource: str) -> str:
        """Strip pod-specific hash suffixes to get a stable workload identity.

        Kubernetes pods have names like: payment-api-6d7f9b-abc12
        We want to normalise to: payment-api
        """
        if not resource:
            return ""
        # Strip trailing hash segments (5-10 char alphanumeric)
        normalised = re.sub(r"-[a-z0-9]{5,10}(-[a-z0-9]{5})?$", "", resource)
        return normalised.lower().strip()

    @staticmethod
    def _normalise_error(error: str) -> str:
        """Remove noise tokens from an error message for stable comparison."""
        result = error.lower()
        for pattern in _STRIP_PATTERNS:
            result = re.sub(pattern, " ", result)
        # Collapse whitespace
        result = " ".join(result.split())
        return result.strip()
