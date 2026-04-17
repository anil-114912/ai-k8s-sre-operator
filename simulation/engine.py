"""Simulation engine — generates realistic K8s failure scenarios for testing.

Each scenario produces a complete cluster state dict that the existing 18
detectors can process, plus structured events, logs, and metrics.  This
makes the simulation system first-class: the same detection pipeline that
runs against a real cluster runs against simulated data.

Usage::

    engine = SimulationEngine()
    state = engine.run("crashloop")
    # → full cluster state dict with pods, events, services, logs

    # Or run from CLI
    ai-sre simulate crashloop
    ai-sre simulate oom
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional, Type

from simulation.scenarios.crashloop import CrashLoopScenario
from simulation.scenarios.ingress_failure import IngressFailureScenario
from simulation.scenarios.oom import OOMScenario
from simulation.scenarios.pending import PendingPodsScenario

logger = logging.getLogger(__name__)

# Registry of scenario name → scenario class
_SCENARIO_REGISTRY: Dict[str, type] = {
    "crashloop": CrashLoopScenario,
    "crash_loop": CrashLoopScenario,
    "oom": OOMScenario,
    "oomkilled": OOMScenario,
    "pending": PendingPodsScenario,
    "pending_pods": PendingPodsScenario,
    "ingress": IngressFailureScenario,
    "ingress_failure": IngressFailureScenario,
}


class SimulationEngine:
    """Runs named failure scenarios and returns cluster state dicts.

    Usage::

        engine = SimulationEngine()
        cluster_state = engine.run("crashloop", namespace="production", workload="payment-api")
        # Pass to detectors:
        from detectors import run_all_detectors
        detections = run_all_detectors(cluster_state)
    """

    def run(
        self,
        scenario_name: str,
        namespace: str = "simulation",
        workload: str = "demo-app",
        **kwargs: Any,
    ) -> Dict[str, Any]:
        """Run a named scenario and return the generated cluster state.

        Args:
            scenario_name: Name of the scenario (e.g. "crashloop", "oom").
            namespace: Kubernetes namespace to use in generated data.
            workload: Workload name to use in generated data.
            **kwargs: Additional keyword arguments passed to the scenario.

        Returns:
            Cluster state dict with pods, events, services, logs, metrics, etc.

        Raises:
            ValueError: If the scenario name is not registered.
        """
        scenario_cls = _SCENARIO_REGISTRY.get(scenario_name.lower())
        if scenario_cls is None:
            available = ", ".join(sorted(_SCENARIO_REGISTRY.keys()))
            raise ValueError(
                f"Unknown scenario '{scenario_name}'. Available: {available}"
            )

        scenario = scenario_cls(namespace=namespace, workload=workload, **kwargs)
        logger.info(
            "SimulationEngine: running scenario='%s' namespace=%s workload=%s",
            scenario_name,
            namespace,
            workload,
        )
        state = scenario.generate()
        logger.info(
            "SimulationEngine: generated state with %d pods, %d events",
            len(state.get("pods", [])),
            len(state.get("events", [])),
        )
        return state

    def list_scenarios(self) -> List[str]:
        """Return a sorted list of unique registered scenario names."""
        unique = sorted({v.__name__ for v in _SCENARIO_REGISTRY.values()})
        return unique

    def run_all(
        self, namespace: str = "simulation"
    ) -> Dict[str, Dict[str, Any]]:
        """Run all scenarios and return a dict of {scenario_name: cluster_state}."""
        results: Dict[str, Dict[str, Any]] = {}
        for name, cls in _SCENARIO_REGISTRY.items():
            if name in results:
                continue  # Skip aliases
            try:
                scenario = cls(namespace=namespace, workload="demo-app")
                results[name] = scenario.generate()
                logger.info("SimulationEngine: completed scenario '%s'", name)
            except Exception as exc:
                logger.error("SimulationEngine: scenario '%s' failed: %s", name, exc)
        return results
