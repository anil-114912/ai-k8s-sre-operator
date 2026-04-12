"""Per-namespace allowlist and denylist policies."""
from __future__ import annotations

import logging
import os
from typing import List, Optional

logger = logging.getLogger(__name__)

# Load from environment for runtime configuration
_RAW_DENIED = os.getenv("DENIED_NAMESPACES", "kube-system,kube-public")
DEFAULT_DENIED_NAMESPACES: List[str] = [
    ns.strip() for ns in _RAW_DENIED.split(",") if ns.strip()
]

_RAW_ALLOWED = os.getenv("ALLOWED_NAMESPACES", "")
DEFAULT_ALLOWED_NAMESPACES: List[str] = [
    ns.strip() for ns in _RAW_ALLOWED.split(",") if ns.strip()
]


class NamespacePolicy:
    """Enforces namespace-level access controls for remediation actions."""

    def __init__(
        self,
        denied_namespaces: Optional[List[str]] = None,
        allowed_namespaces: Optional[List[str]] = None,
    ) -> None:
        """Initialise namespace policy.

        Args:
            denied_namespaces: Namespaces that are never allowed. If None, uses env defaults.
            allowed_namespaces: If non-empty, only these namespaces are allowed.
        """
        self.denied = set(
            denied_namespaces if denied_namespaces is not None else DEFAULT_DENIED_NAMESPACES
        )
        self.allowed = set(
            allowed_namespaces if allowed_namespaces is not None else DEFAULT_ALLOWED_NAMESPACES
        )
        logger.info(
            "NamespacePolicy: denied=%s allowed=%s",
            self.denied,
            self.allowed if self.allowed else "ALL",
        )

    def is_allowed(self, namespace: str) -> bool:
        """Check whether a namespace is allowed for remediation.

        Args:
            namespace: Kubernetes namespace name.

        Returns:
            True if operations are permitted in this namespace.
        """
        if namespace in self.denied:
            logger.warning("Namespace '%s' is in the denied list", namespace)
            return False

        if self.allowed and namespace not in self.allowed:
            logger.warning(
                "Namespace '%s' not in allowed list: %s", namespace, self.allowed
            )
            return False

        return True

    def deny_reason(self, namespace: str) -> str:
        """Return the reason a namespace is denied.

        Args:
            namespace: Kubernetes namespace name.

        Returns:
            Human-readable denial reason string.
        """
        if namespace in self.denied:
            return f"Namespace '{namespace}' is in the denied list (system/protected namespace)"
        if self.allowed and namespace not in self.allowed:
            return f"Namespace '{namespace}' is not in the allowed list: {sorted(self.allowed)}"
        return ""
