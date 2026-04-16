"""Prometheus HTTP API client."""
from __future__ import annotations

import logging
import os
from typing import Any, Dict, List, Optional

import requests

logger = logging.getLogger(__name__)

PROMETHEUS_URL = os.getenv("PROMETHEUS_URL", "http://localhost:9090")


def _is_demo_mode() -> bool:
    return os.getenv("DEMO_MODE", "0").lower() in {"1", "true", "yes"}


class PrometheusClient:
    """Client for querying the Prometheus HTTP API."""

    def __init__(self, base_url: Optional[str] = None) -> None:
        """Initialise the Prometheus client.

        Args:
            base_url: Prometheus base URL. Defaults to PROMETHEUS_URL env var.
        """
        self.base_url = (base_url or PROMETHEUS_URL).rstrip("/")
        logger.info("PrometheusClient: base_url=%s", self.base_url)

    def query(self, promql: str) -> Dict[str, Any]:
        """Execute an instant PromQL query.

        Args:
            promql: PromQL query string.

        Returns:
            Prometheus API response dict.
        """
        if _is_demo_mode():
            return self._simulated_query(promql)

        try:
            resp = requests.get(
                f"{self.base_url}/api/v1/query",
                params={"query": promql},
                timeout=10,
            )
            resp.raise_for_status()
            return resp.json()
        except Exception as exc:
            logger.warning("Prometheus query failed (%s): %s", promql, exc)
            return self._simulated_query(promql)

    def query_range(
        self,
        promql: str,
        start: str,
        end: str,
        step: str = "1m",
    ) -> Dict[str, Any]:
        """Execute a range PromQL query.

        Args:
            promql: PromQL query string.
            start: Start timestamp (RFC3339 or Unix).
            end: End timestamp (RFC3339 or Unix).
            step: Step resolution.

        Returns:
            Prometheus range query response dict.
        """
        if _is_demo_mode():
            return {"status": "success", "data": {"resultType": "matrix", "result": []}}

        try:
            resp = requests.get(
                f"{self.base_url}/api/v1/query_range",
                params={"query": promql, "start": start, "end": end, "step": step},
                timeout=30,
            )
            resp.raise_for_status()
            return resp.json()
        except Exception as exc:
            logger.warning("Prometheus range query failed: %s", exc)
            return {"status": "error", "error": str(exc)}

    def get_pod_cpu_usage(self, namespace: str, pod: str) -> Optional[float]:
        """Get the current CPU usage for a specific pod.

        Args:
            namespace: Kubernetes namespace.
            pod: Pod name.

        Returns:
            CPU usage in millicores, or None.
        """
        promql = f'rate(container_cpu_usage_seconds_total{{namespace="{namespace}",pod="{pod}"}}[5m]) * 1000'
        result = self.query(promql)
        return self._extract_scalar(result)

    def get_pod_memory_usage(self, namespace: str, pod: str) -> Optional[float]:
        """Get the current memory usage for a specific pod in bytes.

        Args:
            namespace: Kubernetes namespace.
            pod: Pod name.

        Returns:
            Memory usage in bytes, or None.
        """
        promql = f'container_memory_usage_bytes{{namespace="{namespace}",pod="{pod}"}}'
        result = self.query(promql)
        return self._extract_scalar(result)

    @staticmethod
    def _extract_scalar(result: Dict[str, Any]) -> Optional[float]:
        """Extract a single float value from a Prometheus instant query result.

        Args:
            result: Prometheus API response dict.

        Returns:
            Float value or None.
        """
        try:
            data = result.get("data", {}).get("result", [])
            if data:
                return float(data[0]["value"][1])
        except (KeyError, IndexError, TypeError, ValueError):
            pass
        return None

    @staticmethod
    def _simulated_query(promql: str) -> Dict[str, Any]:
        """Return simulated Prometheus query results.

        Args:
            promql: PromQL query string (used to infer response content).

        Returns:
            Simulated response dict.
        """
        return {
            "status": "success",
            "data": {
                "resultType": "vector",
                "result": [
                    {
                        "metric": {"__name__": "simulated", "namespace": "production"},
                        "value": [1705312800, "42.5"],
                    }
                ],
            },
        }
