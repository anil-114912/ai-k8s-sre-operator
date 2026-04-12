"""Pod/container log fetcher."""
from __future__ import annotations

import logging
import os
from typing import Dict, List, Optional

logger = logging.getLogger(__name__)

DEMO_MODE = os.getenv("DEMO_MODE", "1") == "1"


class LogsCollector:
    """Fetches recent log lines from pods and containers."""

    def __init__(self) -> None:
        """Initialise the logs collector."""
        logger.info("LogsCollector initialised (demo_mode=%s)", DEMO_MODE)

    def get_pod_logs(
        self,
        namespace: str,
        pod_name: str,
        container_name: str = "",
        tail_lines: int = 50,
        previous: bool = False,
    ) -> List[str]:
        """Fetch recent log lines from a pod container.

        Args:
            namespace: Kubernetes namespace.
            pod_name: Pod name.
            container_name: Container name (optional).
            tail_lines: Number of lines to fetch from the end.
            previous: If True, fetch logs from the previous (crashed) container.

        Returns:
            List of log line strings.
        """
        if DEMO_MODE:
            return self._simulated_logs(namespace, pod_name, container_name, previous)

        try:
            from providers.kubernetes import get_k8s_client
            client = get_k8s_client()
            # If real client, use core API
            import kubernetes
            core = kubernetes.client.CoreV1Api()
            kwargs: Dict = {
                "name": pod_name,
                "namespace": namespace,
                "tail_lines": tail_lines,
                "previous": previous,
            }
            if container_name:
                kwargs["container"] = container_name
            logs = core.read_namespaced_pod_log(**kwargs)
            return logs.splitlines()
        except Exception as exc:
            logger.warning("LogsCollector fetch failed: %s", exc)
            return []

    def get_logs_from_cluster_state(
        self,
        cluster_state: Dict,
        namespace: str,
        pod_name: str,
        container_name: str = "",
    ) -> List[str]:
        """Retrieve logs from the cluster state dict (used in simulation).

        Args:
            cluster_state: Full cluster state dict.
            namespace: Kubernetes namespace.
            pod_name: Pod name.
            container_name: Container name.

        Returns:
            List of log line strings.
        """
        recent_logs = cluster_state.get("recent_logs", {})
        key = f"{namespace}/{pod_name}/{container_name}"
        logs = recent_logs.get(key, [])
        if not logs:
            # Try without container
            key2 = f"{namespace}/{pod_name}"
            for k, v in recent_logs.items():
                if k.startswith(key2):
                    return v
        return logs

    @staticmethod
    def _simulated_logs(
        namespace: str,
        pod_name: str,
        container_name: str = "",
        previous: bool = False,
    ) -> List[str]:
        """Return simulated log lines for demo mode."""
        if "payment-api" in pod_name:
            return [
                f"2024-01-15T09:23:35Z INFO  Starting payment-api v1.5.2",
                f"2024-01-15T09:23:36Z ERROR Failed to load config: secret 'db-credentials' not found",
                f"2024-01-15T09:23:37Z FATAL Application startup failed",
            ]
        if "analytics" in pod_name:
            return [
                f"2024-01-15T08:55:12Z INFO  Processing batch job",
                f"2024-01-15T08:57:31Z WARN  Memory usage at 97%",
                f"2024-01-15T08:57:35Z ERROR Killed by OOM killer",
            ]
        return [
            f"2024-01-15T09:00:00Z INFO  {pod_name} starting",
            f"2024-01-15T09:00:01Z INFO  Ready",
        ]
