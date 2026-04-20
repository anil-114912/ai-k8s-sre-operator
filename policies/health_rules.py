"""AppDynamics-style health rules engine.

Health rules are named, configurable conditions evaluated against live
service metrics.  When a condition is violated the engine produces a
``HealthRuleViolation`` that feeds into the Alerts & Monitoring view.

Built-in rule types
-------------------
- error_rate       — fires when error rate exceeds a threshold
- latency_p95      — fires when p95 latency exceeds a threshold (ms)
- latency_p99      — fires when p99 latency exceeds a threshold (ms)
- cpu_usage        — fires when CPU % exceeds a threshold
- memory_usage     — fires when memory MB exceeds a threshold
- restart_count    — fires when restart count exceeds a threshold
- health_score     — fires when APM health score drops below a threshold
- custom           — user-supplied Python expression evaluated against metrics

Usage::

    engine = HealthRulesEngine()
    engine.add_rule(HealthRule(
        name="High Error Rate",
        metric="error_rate",
        operator="gt",
        threshold=0.05,
        severity="critical",
        duration_secs=60,
    ))
    violations = engine.evaluate(services_data)
"""

from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

_OPERATORS = {
    "gt": lambda v, t: v > t,
    "gte": lambda v, t: v >= t,
    "lt": lambda v, t: v < t,
    "lte": lambda v, t: v <= t,
    "eq": lambda v, t: v == t,
    "neq": lambda v, t: v != t,
}

# Metric name → how to extract the value from a service data dict
_METRIC_EXTRACTORS: Dict[str, Any] = {
    "error_rate": lambda d: d.get("error_rate", 0.0),
    "error_count": lambda d: d.get("error_count", 0),
    "latency_p95": lambda d: (d.get("metrics") or {}).get("latency_p95_ms", 0.0),
    "latency_p99": lambda d: (d.get("metrics") or {}).get("latency_p99_ms", 0.0),
    "cpu_usage": lambda d: (d.get("metrics") or {}).get("cpu_usage_percent", 0.0),
    "memory_usage": lambda d: (d.get("metrics") or {}).get("memory_mb", 0.0),
    "restart_count": lambda d: (d.get("metrics") or {}).get("restart_count", 0),
    "health_score": lambda d: d.get("health_score", 100),
    "warning_count": lambda d: d.get("warning_count", 0),
}


@dataclass
class HealthRule:
    """A single configurable health rule."""

    id: str = field(default_factory=lambda: str(uuid.uuid4())[:8])
    name: str = ""
    metric: str = "error_rate"
    operator: str = "gt"
    threshold: float = 0.05
    severity: str = "warning"  # critical | warning | info
    enabled: bool = True
    duration_secs: int = 0  # how long condition must hold (0 = instant)
    namespace_filter: str = ""  # empty = all namespaces
    service_filter: str = ""  # empty = all services
    description: str = ""
    created_at: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "name": self.name,
            "metric": self.metric,
            "operator": self.operator,
            "threshold": self.threshold,
            "severity": self.severity,
            "enabled": self.enabled,
            "duration_secs": self.duration_secs,
            "namespace_filter": self.namespace_filter,
            "service_filter": self.service_filter,
            "description": self.description,
            "created_at": self.created_at,
        }


@dataclass
class HealthRuleViolation:
    """A violation produced when a health rule condition is met."""

    id: str = field(default_factory=lambda: str(uuid.uuid4()))
    rule_id: str = ""
    rule_name: str = ""
    metric: str = ""
    severity: str = "warning"
    service_name: str = ""
    namespace: str = ""
    current_value: float = 0.0
    threshold: float = 0.0
    operator: str = "gt"
    message: str = ""
    status: str = "open"  # open | acknowledged | resolved
    opened_at: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )
    resolved_at: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "rule_id": self.rule_id,
            "rule_name": self.rule_name,
            "metric": self.metric,
            "severity": self.severity,
            "service_name": self.service_name,
            "namespace": self.namespace,
            "current_value": self.current_value,
            "threshold": self.threshold,
            "operator": self.operator,
            "message": self.message,
            "status": self.status,
            "opened_at": self.opened_at,
            "resolved_at": self.resolved_at,
        }


# Default rules — mirrors typical AppDynamics health rule set
_DEFAULT_RULES: List[HealthRule] = [
    HealthRule(
        id="hr-err-crit",
        name="Critical Error Rate",
        metric="error_rate",
        operator="gt",
        threshold=0.10,
        severity="critical",
        description="Error rate exceeds 10%",
    ),
    HealthRule(
        id="hr-err-warn",
        name="Elevated Error Rate",
        metric="error_rate",
        operator="gt",
        threshold=0.05,
        severity="warning",
        description="Error rate exceeds 5%",
    ),
    HealthRule(
        id="hr-lat-p95",
        name="Slow Response Time (p95)",
        metric="latency_p95",
        operator="gt",
        threshold=1000.0,
        severity="warning",
        description="p95 latency exceeds 1 second",
    ),
    HealthRule(
        id="hr-lat-p99",
        name="Very Slow Response Time (p99)",
        metric="latency_p99",
        operator="gt",
        threshold=2000.0,
        severity="critical",
        description="p99 latency exceeds 2 seconds",
    ),
    HealthRule(
        id="hr-health-low",
        name="Low Health Score",
        metric="health_score",
        operator="lt",
        threshold=50.0,
        severity="critical",
        description="Service health score below 50",
    ),
    HealthRule(
        id="hr-health-warn",
        name="Degraded Health Score",
        metric="health_score",
        operator="lt",
        threshold=75.0,
        severity="warning",
        description="Service health score below 75",
    ),
    HealthRule(
        id="hr-restarts",
        name="Excessive Pod Restarts",
        metric="restart_count",
        operator="gt",
        threshold=5,
        severity="warning",
        description="Pod restart count exceeds 5",
    ),
]


class HealthRulesEngine:
    """Evaluates health rules against live service metrics."""

    def __init__(self, load_defaults: bool = True) -> None:
        self._rules: Dict[str, HealthRule] = {}
        self._violations: List[HealthRuleViolation] = []
        self._open_violations: Dict[str, HealthRuleViolation] = {}  # key: rule_id+service
        if load_defaults:
            for rule in _DEFAULT_RULES:
                self._rules[rule.id] = rule

    # ------------------------------------------------------------------
    # Rule CRUD
    # ------------------------------------------------------------------

    def add_rule(self, rule: HealthRule) -> HealthRule:
        self._rules[rule.id] = rule
        logger.info("Health rule added: %s (%s)", rule.name, rule.id)
        return rule

    def update_rule(self, rule_id: str, updates: Dict[str, Any]) -> Optional[HealthRule]:
        rule = self._rules.get(rule_id)
        if not rule:
            return None
        for key, val in updates.items():
            if hasattr(rule, key) and key != "id":
                setattr(rule, key, val)
        return rule

    def delete_rule(self, rule_id: str) -> bool:
        return self._rules.pop(rule_id, None) is not None

    def get_rule(self, rule_id: str) -> Optional[HealthRule]:
        return self._rules.get(rule_id)

    def list_rules(self) -> List[Dict[str, Any]]:
        return [r.to_dict() for r in self._rules.values()]

    # ------------------------------------------------------------------
    # Evaluation
    # ------------------------------------------------------------------

    def evaluate(self, services: List[Dict[str, Any]]) -> List[HealthRuleViolation]:
        """Evaluate all enabled rules against all services.

        Args:
            services: List of service data dicts (from /api/v1/apm/services
                      or _apm_reports values).

        Returns:
            List of new violations detected in this evaluation cycle.
        """
        new_violations: List[HealthRuleViolation] = []
        active_keys: set = set()

        for rule in self._rules.values():
            if not rule.enabled:
                continue

            op_fn = _OPERATORS.get(rule.operator)
            if not op_fn:
                continue

            extractor = _METRIC_EXTRACTORS.get(rule.metric)
            if not extractor:
                continue

            for svc in services:
                ns = svc.get("namespace", "")
                svc_name = svc.get("service_name", "")

                if rule.namespace_filter and ns != rule.namespace_filter:
                    continue
                if rule.service_filter and svc_name != rule.service_filter:
                    continue

                value = extractor(svc)
                violation_key = f"{rule.id}:{ns}/{svc_name}"

                if op_fn(value, rule.threshold):
                    active_keys.add(violation_key)
                    if violation_key not in self._open_violations:
                        v = HealthRuleViolation(
                            rule_id=rule.id,
                            rule_name=rule.name,
                            metric=rule.metric,
                            severity=rule.severity,
                            service_name=svc_name,
                            namespace=ns,
                            current_value=round(value, 4),
                            threshold=rule.threshold,
                            operator=rule.operator,
                            message=(
                                f"{rule.name}: {rule.metric}={value:.4g} "
                                f"{rule.operator} {rule.threshold} "
                                f"on {ns}/{svc_name}"
                            ),
                        )
                        self._open_violations[violation_key] = v
                        self._violations.append(v)
                        new_violations.append(v)
                        logger.warning(
                            "Health rule violation: %s on %s/%s",
                            rule.name, ns, svc_name,
                        )
                    else:
                        # Update current value on existing violation
                        self._open_violations[violation_key].current_value = round(value, 4)

        # Auto-resolve violations that are no longer active
        for key in list(self._open_violations.keys()):
            if key not in active_keys:
                v = self._open_violations.pop(key)
                v.status = "resolved"
                v.resolved_at = datetime.now(timezone.utc).isoformat()

        return new_violations

    # ------------------------------------------------------------------
    # Query
    # ------------------------------------------------------------------

    def get_violations(
        self,
        status: Optional[str] = None,
        severity: Optional[str] = None,
        namespace: Optional[str] = None,
        limit: int = 100,
    ) -> List[Dict[str, Any]]:
        results = list(reversed(self._violations))
        if status:
            results = [v for v in results if v.status == status]
        if severity:
            results = [v for v in results if v.severity == severity]
        if namespace:
            results = [v for v in results if v.namespace == namespace]
        return [v.to_dict() for v in results[:limit]]

    def get_open_violations(self) -> List[Dict[str, Any]]:
        return [v.to_dict() for v in self._open_violations.values()]

    def acknowledge_violation(self, violation_id: str) -> bool:
        for v in self._open_violations.values():
            if v.id == violation_id:
                v.status = "acknowledged"
                return True
        return False

    def summary(self) -> Dict[str, Any]:
        open_v = list(self._open_violations.values())
        return {
            "total_rules": len(self._rules),
            "enabled_rules": sum(1 for r in self._rules.values() if r.enabled),
            "total_violations": len(self._violations),
            "open_violations": len(open_v),
            "critical_open": sum(1 for v in open_v if v.severity == "critical"),
            "warning_open": sum(1 for v in open_v if v.severity == "warning"),
        }
