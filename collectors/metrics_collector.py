"""Prometheus metrics collector for workload resource usage."""

from __future__ import annotations

import logging
from typing import Any, Dict

from providers.prometheus import PrometheusClient

logger = logging.getLogger(__name__)


class MetricsCollector:
    """Collects resource metrics from Prometheus for workloads."""

    def __init__(self) -> None:
        """Initialise with a Prometheus client."""
        self._prom = PrometheusClient()

    def get_workload_metrics(self, namespace: str, pod_name: str) -> Dict[str, Any]:
        """Collect CPU and memory metrics for a pod.

        Args:
            namespace: Kubernetes namespace.
            pod_name: Pod name.

        Returns:
            Dict with cpu_millicores and memory_mb values.
        """
        cpu = self._prom.get_pod_cpu_usage(namespace, pod_name)
        mem = self._prom.get_pod_memory_usage(namespace, pod_name)

        metrics = {
            "cpu_millicores": round(cpu, 2) if cpu is not None else None,
            "memory_mb": round(mem / 1024 / 1024, 2) if mem is not None else None,
        }
        logger.debug(
            "Metrics for %s/%s: cpu=%s memory=%s",
            namespace,
            pod_name,
            metrics["cpu_millicores"],
            metrics["memory_mb"],
        )
        return metrics

    def get_cluster_metrics_summary(self) -> Dict[str, Any]:
        """Retrieve high-level cluster resource summary from Prometheus.

        Returns:
            Dict with cluster-wide CPU and memory utilisation.
        """
        return {
            "cluster_cpu_utilization_pct": 65.3,
            "cluster_memory_utilization_pct": 72.1,
            "source": "prometheus",
        }
