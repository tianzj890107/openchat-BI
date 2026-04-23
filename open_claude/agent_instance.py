"""
Agent Instance — a running session created from an AgentDef.

    AgentDef  (class)   →  configured template
    AgentInstance (obj)  →  live conversation with state

Each instance has:
- A unique ID
- A reference to its parent AgentDef
- Its own message history, cost tracker, permissions
- Lifecycle states: created → running → paused → stopped
"""

import threading
import time
from typing import Any, Optional

from .agent_def import AgentDef, BASE_AGENT_DEF


# ---------------------------------------------------------------------------
# Instance lifecycle
# ---------------------------------------------------------------------------

class InstanceState:
    CREATED = "created"
    RUNNING = "running"
    PAUSED = "paused"
    STOPPED = "stopped"


class AgentInstance:
    """One live conversation session backed by an AgentDef."""

    def __init__(self, instance_id: int, agent_def: AgentDef, cwd: str):
        self.id = instance_id
        self.agent_def = agent_def
        self.cwd = cwd
        self.state = InstanceState.CREATED
        self.created_at = time.time()
        self.metadata: dict[str, Any] = {}

    @property
    def agent_name(self) -> str:
        return self.agent_def.name

    def start(self):
        self.state = InstanceState.RUNNING

    def pause(self):
        if self.state == InstanceState.RUNNING:
            self.state = InstanceState.PAUSED

    def resume(self):
        if self.state == InstanceState.PAUSED:
            self.state = InstanceState.RUNNING

    def stop(self):
        self.state = InstanceState.STOPPED

    def summary(self) -> str:
        icon = {
            InstanceState.CREATED: "o",
            InstanceState.RUNNING: "*",
            InstanceState.PAUSED: "-",
            InstanceState.STOPPED: "x",
        }.get(self.state, "?")
        elapsed = time.time() - self.created_at
        mins = int(elapsed // 60)
        desc = self.agent_def.description or self.agent_name
        return f"#{self.id} [{icon} {self.state}] {desc} ({mins}m)"

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "agent": self.agent_name,
            "state": self.state,
            "cwd": self.cwd,
            "created_at": self.created_at,
        }


# ---------------------------------------------------------------------------
# Instance Store — manages all live instances in a session
# ---------------------------------------------------------------------------

class InstanceStore:
    """Thread-safe store for agent instances within a process."""

    def __init__(self):
        self._instances: dict[int, AgentInstance] = {}
        self._next_id = 1
        self._lock = threading.Lock()

    def create(self, agent_def: AgentDef, cwd: str) -> AgentInstance:
        with self._lock:
            inst = AgentInstance(self._next_id, agent_def, cwd)
            self._instances[self._next_id] = inst
            self._next_id += 1
            return inst

    def get(self, instance_id: int) -> Optional[AgentInstance]:
        with self._lock:
            return self._instances.get(instance_id)

    def get_running(self) -> list[AgentInstance]:
        with self._lock:
            return [i for i in self._instances.values()
                    if i.state in (InstanceState.RUNNING, InstanceState.PAUSED)]

    def list_all(self) -> list[AgentInstance]:
        with self._lock:
            return list(self._instances.values())

    def stop_all(self):
        with self._lock:
            for inst in self._instances.values():
                inst.stop()


# Global singleton
_store: Optional[InstanceStore] = None


def get_instance_store() -> InstanceStore:
    global _store
    if _store is None:
        _store = InstanceStore()
    return _store
