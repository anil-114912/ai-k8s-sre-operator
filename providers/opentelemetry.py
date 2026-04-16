"""OpenTelemetry trace provider stub."""

from __future__ import annotations

import logging
import os
from typing import Any, Dict

logger = logging.getLogger(__name__)

OTEL_ENDPOINT = os.getenv("OTEL_EXPORTER_OTLP_ENDPOINT", "")


class OtelTraceProvider:
    """Stub OpenTelemetry trace provider for future distributed tracing integration."""

    def __init__(self) -> None:
        """Initialise the OTEL provider."""
        self.enabled = bool(OTEL_ENDPOINT)
        if self.enabled:
            logger.info("OtelTraceProvider: endpoint=%s", OTEL_ENDPOINT)
        else:
            logger.info("OtelTraceProvider: disabled (no OTEL_EXPORTER_OTLP_ENDPOINT set)")

    def get_traces(
        self,
        service: str,
        start_time: str,
        end_time: str,
        limit: int = 20,
    ) -> Dict[str, Any]:
        """Retrieve traces for a service within a time range.

        Args:
            service: Service name.
            start_time: Start timestamp.
            end_time: End timestamp.
            limit: Maximum number of traces.

        Returns:
            Dict with trace data (stub returns empty).
        """
        if not self.enabled:
            return {"traces": [], "source": "stub"}
        # Future: integrate with Tempo or Jaeger API
        logger.warning("OtelTraceProvider.get_traces: not yet implemented")
        return {"traces": [], "source": "stub"}

    def get_error_traces(self, service: str, time_range_minutes: int = 30) -> Dict[str, Any]:
        """Get error traces for a service in the recent time window.

        Args:
            service: Service name.
            time_range_minutes: How far back to look.

        Returns:
            Dict with error traces.
        """
        return {"traces": [], "error_count": 0, "source": "stub"}
