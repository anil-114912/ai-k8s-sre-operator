"""Pod/container log fetcher."""
from __future__ import annotations

import logging
import os
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


def _is_demo_mode() -> bool:
    return os.getenv("DEMO_MODE", "0").lower() in {"1", "true", "yes"}


class LogsCollector:
    """Fetches recent log lines from pods and containers."""

    def __init__(self) -> None:
        """Initialise the logs collector."""
        logger.info("LogsCollector initialised (demo_mode=%s)", _is_demo_mode())

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
        if _is_demo_mode():
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
    def analyze_logs(lines: List[str]) -> Dict[str, Any]:
        """Analyze log lines and return structured diagnostic information.

        Args:
            lines: List of log line strings from a crashed container.

        Returns:
            Dict with error_category, key_lines, has_stack_trace,
            suggested_cause, and confidence_boost.
        """
        # Keyword sets per category — checked in priority order
        _CATEGORIES = [
            ("oom", [
                "out of memory", "oom", "killed", "cannot allocate memory",
                "memory limit", "oomkilled",
            ]),
            ("panic", [
                "panic:", "sigsegv", "segmentation fault", "fatal error",
                "runtime error", "goroutine", "exception in thread",
                "traceback (most recent",
            ]),
            ("db_connection", [
                "connection refused", "dial tcp", "timeout", "econnrefused",
                "connect: connection refused", "database", "postgres", "mysql",
                "redis", "mongo", "unable to connect",
            ]),
            ("missing_config", [
                "secret", "configmap", "env", "environment variable",
                "not found", "no such file", "missing", "credentials",
                "token", "password", "connection string", "database url",
                "enoent", "keyerror", "undefined",
            ]),
            ("permission", [
                "permission denied", "eacces", "forbidden", "unauthorized",
                "access denied", "not permitted",
            ]),
            ("port_conflict", [
                "address already in use", "eaddrinuse", "bind: address",
            ]),
            ("image_error", [
                "exec format error", "no such file or directory",
                "not found", "executable file not found",
            ]),
            ("startup_failure", [
                "failed to start", "startup failed", "initialization failed",
                "failed to initialize",
            ]),
        ]

        _SUGGESTED_CAUSES = {
            "missing_config": "Application cannot find required secret, configmap, or environment variable",
            "db_connection": "Application cannot connect to its database or backing service",
            "oom": "Container exceeded its memory limit and was killed by the OS",
            "panic": "Application panicked or crashed with a fatal exception",
            "permission": "Application lacks required filesystem or API permissions",
            "port_conflict": "Application cannot bind to its port because it is already in use",
            "image_error": "Container image has an incompatible binary or missing executable",
            "startup_failure": "Application failed during its initialization or startup sequence",
            "unknown": "Root cause could not be determined from log output alone",
        }

        combined_lower = "\n".join(lines).lower()

        # Determine category
        error_category = "unknown"
        for cat, keywords in _CATEGORIES:
            if any(kw in combined_lower for kw in keywords):
                error_category = cat
                break

        # Extract key lines (ERROR/FATAL prioritized, then WARN etc.)
        priority_keywords = {"error", "fatal", "panic", "exception", "traceback", "killed"}
        secondary_keywords = {"warn", "failed"}
        priority_lines: List[str] = []
        secondary_lines: List[str] = []
        for line in lines:
            ll = line.lower()
            if any(kw in ll for kw in priority_keywords):
                priority_lines.append(line)
            elif any(kw in ll for kw in secondary_keywords):
                secondary_lines.append(line)
        key_lines = (priority_lines + secondary_lines)[:10]

        # Detect stack traces
        has_stack_trace = False
        for line in lines:
            stripped = line.lstrip()
            if (
                stripped.startswith("at ")
                or stripped.startswith("File ")
                or "goroutine " in line
                or "Traceback" in line
            ):
                has_stack_trace = True
                break

        # Compute confidence boost
        if error_category == "unknown":
            confidence_boost = 0.0
        elif error_category == "startup_failure":
            confidence_boost = 0.05
        else:
            confidence_boost = 0.15
        if has_stack_trace:
            confidence_boost = min(0.2, confidence_boost + 0.05)

        return {
            "error_category": error_category,
            "key_lines": key_lines,
            "has_stack_trace": has_stack_trace,
            "suggested_cause": _SUGGESTED_CAUSES.get(error_category, _SUGGESTED_CAUSES["unknown"]),
            "confidence_boost": confidence_boost,
        }

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
