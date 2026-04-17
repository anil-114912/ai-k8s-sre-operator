"""Proactive anomaly detection — CPU, memory, and error-rate spike analysis.

The MetricsAnalyzer watches a rolling window of APM metrics pushed by
sidecar agents and fires early-warning alerts *before* a pod crashes or
an incident is formally detected.

Alert types:
  - cpu_spike        — sudden CPU usage jump (>= threshold within window)
  - memory_growth    — steady upward trend in memory (likely leak)
  - error_rate_spike — error rate exceeds baseline by factor
  - latency_spike    — p95 latency exceeds threshold
  - pod_restart_rate — restart count growing faster than expected

Usage::

    analyzer = MetricsAnalyzer()

    # Feed in APM reports as they arrive
    analyzer.record(service="payment-api", namespace="production", metrics={
        "cpu_usage_percent": 85.0,
        "memory_mb": 420.0,
        "error_rate": 0.12,
        "latency_p95_ms": 980.0,
        "restart_count": 3,
    })

    alerts = analyzer.analyze("payment-api", "production")
"""

from __future__ import annotations

import logging
import statistics
from collections import defaultdict, deque
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Deque, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)

# --- Thresholds -------------------------------------------------------
_CPU_SPIKE_THRESHOLD = 80.0        # % — single reading above this triggers alert
_CPU_SPIKE_DELTA = 30.0            # % — increase from rolling mean to trigger
_MEMORY_TREND_SAMPLES = 5          # minimum samples for trend analysis
_MEMORY_GROWTH_RATE = 0.15         # 15% growth per sample window → alert
_ERROR_RATE_BASELINE_SAMPLES = 10  # samples used to compute baseline
_ERROR_RATE_SPIKE_FACTOR = 3.0     # current > 3× baseline → alert
_ERROR_RATE_ABSOLUTE_MIN = 0.05    # ignore spikes if baseline < 5%
_LATENCY_P95_THRESHOLD_MS = 1000.0 # p95 > 1 second → alert
_LATENCY_SPIKE_FACTOR = 2.5        # current > 2.5× baseline → alert
_RESTART_RATE_WINDOW = 5           # look at last N samples for restart growth
_RESTART_RATE_DELTA = 3            # restart_count increased by >=3 in window → alert
_WINDOW_SIZE = 60                  # max data points to keep per service


@dataclass
class AnomalyAlert:
    """A proactive anomaly detected before a formal incident fires."""

    alert_type: str                        # cpu_spike | memory_growth | error_rate_spike | …
    severity: str                          # warning | critical
    service: str
    namespace: str
    message: str
    current_value: float
    baseline_value: float
    timestamp: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "alert_type": self.alert_type,
            "severity": self.severity,
            "service": self.service,
            "namespace": self.namespace,
            "message": self.message,
            "current_value": self.current_value,
            "baseline_value": self.baseline_value,
            "timestamp": self.timestamp,
            "metadata": self.metadata,
        }


@dataclass
class _MetricPoint:
    ts: str
    cpu_usage_percent: float = 0.0
    memory_mb: float = 0.0
    error_rate: float = 0.0
    latency_p95_ms: float = 0.0
    restart_count: int = 0


class MetricsAnalyzer:
    """Proactive anomaly detection over a rolling window of APM metrics.

    Thread-safe for concurrent writes from multiple sidecar reporters.
    """

    def __init__(self, window_size: int = _WINDOW_SIZE) -> None:
        self._window_size = window_size
        # (namespace, service) → deque of _MetricPoint
        self._windows: Dict[Tuple[str, str], Deque[_MetricPoint]] = defaultdict(
            lambda: deque(maxlen=self._window_size)
        )
        self._alert_history: List[AnomalyAlert] = []

    # ------------------------------------------------------------------
    # Ingestion
    # ------------------------------------------------------------------

    def record(
        self,
        service: str,
        namespace: str,
        metrics: Dict[str, Any],
        timestamp: Optional[str] = None,
    ) -> None:
        """Record a new metrics snapshot for (namespace, service).

        Args:
            service: Service / workload name.
            namespace: Kubernetes namespace.
            metrics: Dict with optional keys: cpu_usage_percent, memory_mb,
                     error_rate, latency_p95_ms, restart_count.
            timestamp: ISO-8601 timestamp (defaults to now).
        """
        ts = timestamp or datetime.now(timezone.utc).isoformat()
        point = _MetricPoint(
            ts=ts,
            cpu_usage_percent=float(metrics.get("cpu_usage_percent", 0.0)),
            memory_mb=float(metrics.get("memory_mb", 0.0)),
            error_rate=float(metrics.get("error_rate", 0.0)),
            latency_p95_ms=float(metrics.get("latency_p95_ms", 0.0)),
            restart_count=int(metrics.get("restart_count", 0)),
        )
        key = (namespace, service)
        self._windows[key].append(point)

    def record_from_apm_report(self, report: Any) -> None:
        """Convenience wrapper for APMReport objects from agent/metrics_reporter.py."""
        service = getattr(report, "service_name", "")
        namespace = getattr(report, "namespace", "")
        if not service:
            return
        metrics = {
            "cpu_usage_percent": getattr(report, "cpu_usage_percent", 0.0),
            "memory_mb": getattr(report, "memory_mb", 0.0),
            "error_rate": getattr(report, "error_rate", 0.0),
            "latency_p95_ms": getattr(report, "latency_p95_ms", 0.0),
            "restart_count": getattr(report, "restart_count", 0),
        }
        self.record(service=service, namespace=namespace, metrics=metrics,
                    timestamp=getattr(report, "timestamp", None))

    # ------------------------------------------------------------------
    # Analysis
    # ------------------------------------------------------------------

    def analyze(self, service: str, namespace: str) -> List[AnomalyAlert]:
        """Run all anomaly checks for (namespace, service) and return alerts.

        Returns:
            List of AnomalyAlert — may be empty if everything looks normal.
        """
        key = (namespace, service)
        window = list(self._windows.get(key, []))
        if len(window) < 2:
            return []

        alerts: List[AnomalyAlert] = []
        alerts.extend(self._check_cpu_spike(service, namespace, window))
        alerts.extend(self._check_memory_growth(service, namespace, window))
        alerts.extend(self._check_error_rate_spike(service, namespace, window))
        alerts.extend(self._check_latency_spike(service, namespace, window))
        alerts.extend(self._check_restart_rate(service, namespace, window))

        for alert in alerts:
            self._alert_history.append(alert)
            logger.warning(
                "ANOMALY [%s/%s] %s: %s", namespace, service, alert.alert_type, alert.message
            )

        # Trim history
        if len(self._alert_history) > 1000:
            self._alert_history = self._alert_history[-1000:]

        return alerts

    def analyze_all(self) -> List[AnomalyAlert]:
        """Analyze every tracked (namespace, service) and return all alerts."""
        all_alerts: List[AnomalyAlert] = []
        for (namespace, service) in list(self._windows.keys()):
            all_alerts.extend(self.analyze(service, namespace))
        return all_alerts

    # ------------------------------------------------------------------
    # Individual checks
    # ------------------------------------------------------------------

    def _check_cpu_spike(
        self, service: str, namespace: str, window: List[_MetricPoint]
    ) -> List[AnomalyAlert]:
        latest = window[-1].cpu_usage_percent
        if latest <= 0:
            return []

        prior = [p.cpu_usage_percent for p in window[:-1] if p.cpu_usage_percent > 0]
        if not prior:
            return []
        mean_prior = statistics.mean(prior)

        alerts = []
        if latest >= _CPU_SPIKE_THRESHOLD and (latest - mean_prior) >= _CPU_SPIKE_DELTA:
            sev = "critical" if latest >= 95 else "warning"
            alerts.append(AnomalyAlert(
                alert_type="cpu_spike",
                severity=sev,
                service=service,
                namespace=namespace,
                message=f"CPU spiked to {latest:.1f}% (baseline {mean_prior:.1f}%)",
                current_value=latest,
                baseline_value=mean_prior,
                metadata={"window_size": len(window)},
            ))
        return alerts

    def _check_memory_growth(
        self, service: str, namespace: str, window: List[_MetricPoint]
    ) -> List[AnomalyAlert]:
        if len(window) < _MEMORY_TREND_SAMPLES:
            return []

        recent = [p.memory_mb for p in window[-_MEMORY_TREND_SAMPLES:] if p.memory_mb > 0]
        if len(recent) < 3:
            return []

        # Simple linear trend: check if each value >= previous
        increases = sum(1 for i in range(1, len(recent)) if recent[i] > recent[i - 1])
        growth_fraction = (recent[-1] - recent[0]) / max(recent[0], 1.0)

        alerts = []
        if increases >= len(recent) - 1 and growth_fraction >= _MEMORY_GROWTH_RATE:
            sev = "critical" if growth_fraction >= 0.40 else "warning"
            alerts.append(AnomalyAlert(
                alert_type="memory_growth",
                severity=sev,
                service=service,
                namespace=namespace,
                message=(
                    f"Memory growing steadily: {recent[0]:.0f}Mi → {recent[-1]:.0f}Mi "
                    f"({growth_fraction:.0%} increase over {len(recent)} samples)"
                ),
                current_value=recent[-1],
                baseline_value=recent[0],
                metadata={"samples": recent},
            ))
        return alerts

    def _check_error_rate_spike(
        self, service: str, namespace: str, window: List[_MetricPoint]
    ) -> List[AnomalyAlert]:
        current = window[-1].error_rate
        prior = [p.error_rate for p in window[:-_ERROR_RATE_BASELINE_SAMPLES:-1] if p.error_rate >= 0]
        if not prior:
            return []
        baseline = statistics.mean(prior)

        alerts = []
        if baseline < _ERROR_RATE_ABSOLUTE_MIN:
            # Absolute threshold when baseline is near zero
            if current >= _ERROR_RATE_ABSOLUTE_MIN * _ERROR_RATE_SPIKE_FACTOR:
                alerts.append(AnomalyAlert(
                    alert_type="error_rate_spike",
                    severity="warning",
                    service=service,
                    namespace=namespace,
                    message=f"Error rate {current:.1%} exceeds expected near-zero baseline",
                    current_value=current,
                    baseline_value=baseline,
                ))
        elif current >= baseline * _ERROR_RATE_SPIKE_FACTOR:
            sev = "critical" if current >= 0.25 else "warning"
            alerts.append(AnomalyAlert(
                alert_type="error_rate_spike",
                severity=sev,
                service=service,
                namespace=namespace,
                message=(
                    f"Error rate {current:.1%} is {current/baseline:.1f}× above "
                    f"baseline {baseline:.1%}"
                ),
                current_value=current,
                baseline_value=baseline,
            ))
        return alerts

    def _check_latency_spike(
        self, service: str, namespace: str, window: List[_MetricPoint]
    ) -> List[AnomalyAlert]:
        current = window[-1].latency_p95_ms
        if current <= 0:
            return []

        prior = [p.latency_p95_ms for p in window[:-1] if p.latency_p95_ms > 0]
        if not prior:
            # No baseline yet; check absolute threshold only
            if current >= _LATENCY_P95_THRESHOLD_MS:
                return [AnomalyAlert(
                    alert_type="latency_spike",
                    severity="warning",
                    service=service,
                    namespace=namespace,
                    message=f"p95 latency {current:.0f}ms exceeds threshold {_LATENCY_P95_THRESHOLD_MS:.0f}ms",
                    current_value=current,
                    baseline_value=0.0,
                )]
            return []

        baseline = statistics.mean(prior)
        alerts = []
        if current >= _LATENCY_P95_THRESHOLD_MS or (baseline > 0 and current >= baseline * _LATENCY_SPIKE_FACTOR):
            sev = "critical" if current >= _LATENCY_P95_THRESHOLD_MS * 2 else "warning"
            alerts.append(AnomalyAlert(
                alert_type="latency_spike",
                severity=sev,
                service=service,
                namespace=namespace,
                message=(
                    f"p95 latency {current:.0f}ms (baseline {baseline:.0f}ms, "
                    f"{current/max(baseline,1):.1f}×)"
                ),
                current_value=current,
                baseline_value=baseline,
            ))
        return alerts

    def _check_restart_rate(
        self, service: str, namespace: str, window: List[_MetricPoint]
    ) -> List[AnomalyAlert]:
        if len(window) < _RESTART_RATE_WINDOW:
            return []

        recent = [p.restart_count for p in window[-_RESTART_RATE_WINDOW:]]
        growth = recent[-1] - recent[0]

        alerts = []
        if growth >= _RESTART_RATE_DELTA:
            alerts.append(AnomalyAlert(
                alert_type="pod_restart_rate",
                severity="warning" if growth < 10 else "critical",
                service=service,
                namespace=namespace,
                message=(
                    f"Pod restart count grew by {growth} in last {_RESTART_RATE_WINDOW} samples "
                    f"({recent[0]} → {recent[-1]})"
                ),
                current_value=float(recent[-1]),
                baseline_value=float(recent[0]),
                metadata={"restart_delta": growth},
            ))
        return alerts

    # ------------------------------------------------------------------
    # Query helpers
    # ------------------------------------------------------------------

    def get_recent_alerts(
        self,
        service: Optional[str] = None,
        namespace: Optional[str] = None,
        limit: int = 50,
    ) -> List[Dict[str, Any]]:
        """Return recent anomaly alerts, optionally filtered by service/namespace."""
        alerts = self._alert_history[-limit:]
        if service:
            alerts = [a for a in alerts if a.service == service]
        if namespace:
            alerts = [a for a in alerts if a.namespace == namespace]
        return [a.to_dict() for a in alerts[-limit:]]

    def get_tracked_services(self) -> List[Dict[str, Any]]:
        """Return all (namespace, service) pairs currently being tracked."""
        return [
            {"namespace": ns, "service": svc, "samples": len(self._windows[(ns, svc)])}
            for (ns, svc) in self._windows.keys()
        ]

    def summary(self) -> Dict[str, Any]:
        return {
            "tracked_services": len(self._windows),
            "total_alerts_lifetime": len(self._alert_history),
            "recent_alerts": len(self.get_recent_alerts(limit=100)),
        }
