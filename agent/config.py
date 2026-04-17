"""Agent configuration from environment variables."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import List


@dataclass
class AgentConfig:
    """All agent settings resolved from environment variables at startup."""

    # Identity
    service_name: str = field(
        default_factory=lambda: os.getenv("SERVICE_NAME", os.getenv("POD_NAME", "unknown-service"))
    )
    pod_name: str = field(default_factory=lambda: os.getenv("POD_NAME", "unknown-pod"))
    pod_namespace: str = field(default_factory=lambda: os.getenv("POD_NAMESPACE", "default"))

    # Operator API
    operator_api_url: str = field(
        default_factory=lambda: os.getenv("OPERATOR_API_URL", "http://localhost:8000").rstrip("/")
    )
    api_timeout_secs: int = field(default_factory=lambda: int(os.getenv("API_TIMEOUT_SECS", "10")))

    # Log tailing
    log_path: str = field(default_factory=lambda: os.getenv("LOG_PATH", "/var/log/app/app.log"))
    log_paths: List[str] = field(
        default_factory=lambda: [
            p.strip() for p in os.getenv("LOG_PATHS", "").split(",") if p.strip()
        ]
    )
    tail_lines: int = field(default_factory=lambda: int(os.getenv("TAIL_LINES", "1000")))

    # Reporting
    report_interval_secs: int = field(
        default_factory=lambda: int(os.getenv("REPORT_INTERVAL_SECS", "30"))
    )
    error_threshold: int = field(default_factory=lambda: int(os.getenv("ERROR_THRESHOLD", "5")))
    latency_threshold_ms: int = field(
        default_factory=lambda: int(os.getenv("LATENCY_THRESHOLD_MS", "1000"))
    )

    # Patterns
    custom_patterns_path: str = field(default_factory=lambda: os.getenv("CUSTOM_PATTERNS_PATH", ""))
    ignore_patterns: List[str] = field(
        default_factory=lambda: [
            p.strip() for p in os.getenv("IGNORE_PATTERNS", "").split(",") if p.strip()
        ]
    )

    # Buffering
    buffer_dir: str = field(default_factory=lambda: os.getenv("BUFFER_DIR", "/tmp/apm_buffer"))
    max_buffer_reports: int = field(
        default_factory=lambda: int(os.getenv("MAX_BUFFER_REPORTS", "20"))
    )

    # Misc
    log_level: str = field(default_factory=lambda: os.getenv("LOG_LEVEL", "INFO").upper())
    agent_version: str = "0.2.0"

    def effective_log_paths(self) -> List[str]:
        """Return all log paths to tail, combining LOG_PATH and LOG_PATHS."""
        paths: List[str] = []
        if self.log_path and self.log_path not in paths:
            paths.append(self.log_path)
        for p in self.log_paths:
            if p not in paths:
                paths.append(p)
        return paths

    def builtin_patterns_path(self) -> Path:
        return Path(__file__).parent / "patterns" / "builtin.yaml"
