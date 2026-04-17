"""Built-in failure simulation scenarios."""

from simulation.scenarios.crashloop import CrashLoopScenario
from simulation.scenarios.ingress_failure import IngressFailureScenario
from simulation.scenarios.oom import OOMScenario
from simulation.scenarios.pending import PendingPodsScenario

__all__ = [
    "CrashLoopScenario",
    "IngressFailureScenario",
    "OOMScenario",
    "PendingPodsScenario",
]
