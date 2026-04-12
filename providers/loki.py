"""Loki HTTP API client (optional log aggregation)."""
from __future__ import annotations

import logging
import os
from typing import Any, Dict, List, Optional

import requests

logger = logging.getLogger(__name__)

LOKI_URL = os.getenv("LOKI_URL", "")
DEMO_MODE = os.getenv("DEMO_MODE", "1") == "1"


class LokiClient:
    """Client for querying Grafana Loki's HTTP API."""

    def __init__(self, base_url: Optional[str] = None) -> None:
        """Initialise the Loki client.

        Args:
            base_url: Loki base URL. Defaults to LOKI_URL env var.
        """
        self.base_url = (base_url or LOKI_URL or "http://loki.monitoring.svc:3100").rstrip("/")
        self.available = bool(LOKI_URL) and not DEMO_MODE
        logger.info("LokiClient: base_url=%s available=%s", self.base_url, self.available)

    def query_logs(
        self,
        logql: str,
        start: Optional[str] = None,
        end: Optional[str] = None,
        limit: int = 100,
    ) -> List[str]:
        """Query Loki for log lines matching the LogQL expression.

        Args:
            logql: LogQL query string.
            start: Start timestamp (nanosecond or RFC3339).
            end: End timestamp.
            limit: Maximum number of log lines.

        Returns:
            List of log line strings.
        """
        if not self.available:
            return self._simulated_logs(logql)

        try:
            params: Dict[str, Any] = {"query": logql, "limit": limit}
            if start:
                params["start"] = start
            if end:
                params["end"] = end

            resp = requests.get(
                f"{self.base_url}/loki/api/v1/query_range",
                params=params,
                timeout=15,
            )
            resp.raise_for_status()
            data = resp.json()
            lines = []
            for stream in data.get("data", {}).get("result", []):
                for ts, msg in stream.get("values", []):
                    lines.append(msg)
            return lines
        except Exception as exc:
            logger.warning("Loki query failed: %s", exc)
            return []

    def get_pod_logs(self, namespace: str, pod: str, container: str = "", lines: int = 50) -> List[str]:
        """Retrieve recent logs for a specific pod from Loki.

        Args:
            namespace: Kubernetes namespace.
            pod: Pod name.
            container: Container name (optional).
            lines: Maximum number of log lines.

        Returns:
            List of log line strings.
        """
        logql = f'{{namespace="{namespace}",pod="{pod}"}}'
        if container:
            logql = f'{{namespace="{namespace}",pod="{pod}",container="{container}"}}'
        return self.query_logs(logql, limit=lines)

    @staticmethod
    def _simulated_logs(logql: str) -> List[str]:
        """Return simulated log lines for demo mode.

        Args:
            logql: LogQL query (used for context).

        Returns:
            Simulated log line list.
        """
        return [
            "2024-01-15T09:00:01Z INFO  Application starting...",
            "2024-01-15T09:00:02Z INFO  Loading configuration",
            "2024-01-15T09:00:03Z ERROR Configuration error: missing required value",
        ]
