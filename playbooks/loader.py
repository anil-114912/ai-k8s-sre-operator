"""Playbook loader — reads structured YAML remediation playbooks from disk."""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

try:
    import yaml
except ImportError:
    yaml = None  # type: ignore[assignment]

logger = logging.getLogger(__name__)

_PLAYBOOKS_DIR = Path(__file__).parent


@dataclass
class PlaybookStep:
    """A single step within a playbook."""

    id: str
    name: str
    command: str = ""
    check: str = ""
    notes: str = ""
    safety_level: str = "suggest_only"
    reversible: bool = True
    on_failure: str = "stop"        # "stop" | "continue" | "rollback"


@dataclass
class Playbook:
    """A structured remediation playbook for a specific failure type."""

    id: str
    name: str
    trigger_types: List[str]        # e.g. ["CrashLoopBackOff"]
    description: str = ""
    conditions: List[str] = field(default_factory=list)  # text conditions for applicability
    steps: List[PlaybookStep] = field(default_factory=list)
    rollback_steps: List[PlaybookStep] = field(default_factory=list)
    tags: List[str] = field(default_factory=list)
    safety_level: str = "approval_required"
    estimated_duration_secs: int = 120

    def applies_to(self, incident_type: str, root_cause: str = "") -> bool:
        """Check if this playbook applies to the given incident type / root cause."""
        if incident_type in self.trigger_types:
            return True
        # Fuzzy match on root cause keywords from conditions
        if root_cause:
            root_lower = root_cause.lower()
            for cond in self.conditions:
                if cond.lower() in root_lower:
                    return True
        return False

    def render_commands(self, variables: Optional[Dict[str, str]] = None) -> List[str]:
        """Render step commands with variable substitution.

        Args:
            variables: Dict of {name: value} for placeholder substitution.
                Common keys: namespace, workload, pod_name, container_name.

        Returns:
            List of rendered command strings (one per step).
        """
        vars_ = variables or {}
        commands = []
        for step in self.steps:
            cmd = step.command
            for key, val in vars_.items():
                cmd = cmd.replace(f"{{{key}}}", val)
            commands.append(cmd)
        return commands

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "name": self.name,
            "trigger_types": self.trigger_types,
            "description": self.description,
            "conditions": self.conditions,
            "safety_level": self.safety_level,
            "estimated_duration_secs": self.estimated_duration_secs,
            "tags": self.tags,
            "steps": [
                {
                    "id": s.id,
                    "name": s.name,
                    "command": s.command,
                    "check": s.check,
                    "notes": s.notes,
                    "safety_level": s.safety_level,
                    "reversible": s.reversible,
                }
                for s in self.steps
            ],
        }


class PlaybookLoader:
    """Loads playbooks from YAML files and provides lookup by incident type.

    Usage::

        loader = PlaybookLoader()
        loader.load()

        playbooks = loader.get_for_type("CrashLoopBackOff", root_cause="missing secret")
        # → [Playbook(id="crashloop-missing-secret", ...)]
    """

    def __init__(self, playbooks_dir: Optional[Path] = None) -> None:
        self._dir = playbooks_dir or _PLAYBOOKS_DIR
        self._playbooks: Dict[str, Playbook] = {}

    def load(self) -> int:
        """Load all YAML playbooks from the playbooks directory.

        Returns:
            Number of playbooks loaded.
        """
        if yaml is None:
            logger.warning("PyYAML not installed — playbooks unavailable")
            return 0

        count = 0
        for path in sorted(self._dir.glob("*.yaml")):
            if path.name.startswith("_"):
                continue
            try:
                with open(path) as f:
                    data = yaml.safe_load(f)
                if isinstance(data, list):
                    for entry in data:
                        pb = self._parse(entry)
                        if pb:
                            self._playbooks[pb.id] = pb
                            count += 1
                elif isinstance(data, dict):
                    pb = self._parse(data)
                    if pb:
                        self._playbooks[pb.id] = pb
                        count += 1
            except Exception as exc:
                logger.warning("Failed to load playbook %s: %s", path.name, exc)

        logger.info("PlaybookLoader: loaded %d playbooks from %s", count, self._dir)
        return count

    def get_for_type(
        self, incident_type: str, root_cause: str = ""
    ) -> List[Playbook]:
        """Return all playbooks that apply to an incident type / root cause."""
        return [pb for pb in self._playbooks.values() if pb.applies_to(incident_type, root_cause)]

    def get_by_id(self, playbook_id: str) -> Optional[Playbook]:
        """Return a specific playbook by ID."""
        return self._playbooks.get(playbook_id)

    def list_all(self) -> List[Playbook]:
        """Return all loaded playbooks."""
        return list(self._playbooks.values())

    def list_types(self) -> List[str]:
        """Return all unique incident types covered by loaded playbooks."""
        types: set = set()
        for pb in self._playbooks.values():
            types.update(pb.trigger_types)
        return sorted(types)

    # ------------------------------------------------------------------
    # Internal parsing
    # ------------------------------------------------------------------

    @staticmethod
    def _parse(data: Dict[str, Any]) -> Optional[Playbook]:
        """Parse a YAML dict into a Playbook."""
        if not isinstance(data, dict):
            return None
        pb_id = data.get("id", "")
        if not pb_id:
            return None

        steps = [
            PlaybookStep(
                id=s.get("id", f"step-{i}"),
                name=s.get("name", ""),
                command=s.get("command", ""),
                check=s.get("check", ""),
                notes=s.get("notes", ""),
                safety_level=s.get("safety_level", "suggest_only"),
                reversible=s.get("reversible", True),
                on_failure=s.get("on_failure", "stop"),
            )
            for i, s in enumerate(data.get("steps", []))
        ]

        rollback_steps = [
            PlaybookStep(
                id=s.get("id", f"rollback-{i}"),
                name=s.get("name", ""),
                command=s.get("command", ""),
                safety_level=s.get("safety_level", "approval_required"),
            )
            for i, s in enumerate(data.get("rollback_steps", []))
        ]

        return Playbook(
            id=pb_id,
            name=data.get("name", pb_id),
            trigger_types=data.get("trigger_types", []),
            description=data.get("description", ""),
            conditions=data.get("conditions", []),
            steps=steps,
            rollback_steps=rollback_steps,
            tags=data.get("tags", []),
            safety_level=data.get("safety_level", "approval_required"),
            estimated_duration_secs=data.get("estimated_duration_secs", 120),
        )
