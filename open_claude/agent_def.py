"""
Agent Definition — the "class" layer between the base agent and instances.

An AgentDef = base agent + configuration.  Launching an AgentDef creates an
AgentInstance (a running conversation session).

Definition files live in:
  ~/.claude/agents/          (user-level)
  .claude/agents/            (project-level)

File format — Markdown with YAML frontmatter:

    ---
    name: code-reviewer
    description: "Code review specialist"
    model: claude-sonnet-4-6
    tools:
      - Read
      - Glob
      - Grep
    skills:
      - review
      - explain
    permission_mode: default
    max_iterations: 30
    ---

    You are a senior code reviewer. Focus on ...
    (additional system prompt instructions)
"""

import os
from pathlib import Path
from typing import Any, Optional

from .skills.frontmatter import parse_frontmatter, normalize_metadata


# ---------------------------------------------------------------------------
# AgentDef — one "class" of agent
# ---------------------------------------------------------------------------

class AgentDef:
    """
    A configured agent type.  Think of it as a class:
    AgentDef + runtime state = AgentInstance.
    """

    # The sentinel that represents "use the base agent as-is"
    BASE_NAME = "__base__"

    def __init__(
        self,
        name: str,
        description: str = "",
        model: Optional[str] = None,
        tools: Optional[list[str]] = None,
        skills: Optional[list[str]] = None,
        permission_mode: Optional[str] = None,
        max_iterations: int = 30,
        system_prompt_extra: str = "",
        source: str = "builtin",
        source_path: Optional[str] = None,
        welcome_message: str = "",
        tags: Optional[list[str]] = None,
    ):
        self.name = name
        self.description = description
        self.model = model                          # None → inherit from config
        self.tools = tools                          # None → all tools available
        self.skills = skills                        # None → all skills available
        self.permission_mode = permission_mode      # None → "default"
        self.max_iterations = max_iterations
        self.system_prompt_extra = system_prompt_extra
        self.source = source                        # "builtin" | "user" | "project"
        self.source_path = source_path
        self.welcome_message = welcome_message
        self.tags = tags or []

    @property
    def is_base(self) -> bool:
        return self.name == self.BASE_NAME

    def to_dict(self) -> dict[str, Any]:
        d: dict[str, Any] = {
            "name": self.name,
            "description": self.description,
        }
        if self.model:
            d["model"] = self.model
        if self.tools is not None:
            d["tools"] = self.tools
        if self.skills is not None:
            d["skills"] = self.skills
        if self.permission_mode:
            d["permission_mode"] = self.permission_mode
        if self.max_iterations != 30:
            d["max_iterations"] = self.max_iterations
        if self.tags:
            d["tags"] = self.tags
        d["source"] = self.source
        return d

    def summary(self) -> str:
        model_hint = f" ({self.model})" if self.model else ""
        return f"{self.name}{model_hint} — {self.description}" if self.description else self.name


# ---------------------------------------------------------------------------
# The base (unconfigured) agent definition — always available
# ---------------------------------------------------------------------------

BASE_AGENT_DEF = AgentDef(
    name=AgentDef.BASE_NAME,
    description="Standard Open Claude agent (no role specialization)",
    source="builtin",
)


# ---------------------------------------------------------------------------
# Loading definitions from disk
# ---------------------------------------------------------------------------

def _parse_list_field(value: Any) -> Optional[list[str]]:
    """Parse a list field that might be a string, list, or None."""
    if value is None:
        return None
    if isinstance(value, list):
        return [str(v).strip() for v in value if str(v).strip()]
    if isinstance(value, str):
        # "Read, Glob, Grep" or "Read\n- Glob\n- Grep"
        items = [
            item.strip().lstrip("- ").strip()
            for item in value.replace(",", "\n").split("\n")
            if item.strip().lstrip("- ").strip()
        ]
        return items if items else None
    return None


def load_agent_def_from_file(path: str, source: str = "project") -> Optional[AgentDef]:
    """Load a single AgentDef from a Markdown file with YAML frontmatter."""
    try:
        content = Path(path).read_text(encoding="utf-8")
    except Exception:
        return None

    raw_meta, body = parse_frontmatter(content)
    meta = normalize_metadata(raw_meta)

    # Determine name: frontmatter > directory name > filename stem
    parent_dir = os.path.basename(os.path.dirname(path))
    file_stem = Path(path).stem
    if file_stem.upper() in ("AGENT", "INDEX"):
        default_name = parent_dir
    else:
        default_name = file_stem

    name = meta.get("name", default_name)

    return AgentDef(
        name=name,
        description=meta.get("description", ""),
        model=meta.get("model"),
        tools=_parse_list_field(meta.get("tools")),
        skills=_parse_list_field(meta.get("skills")),
        permission_mode=meta.get("permission_mode"),
        max_iterations=int(meta.get("max_iterations", 30)),
        system_prompt_extra=body,
        source=source,
        source_path=path,
        welcome_message=meta.get("welcome_message", ""),
        tags=_parse_list_field(meta.get("tags")),
    )


# ---------------------------------------------------------------------------
# Agent Definition Registry
# ---------------------------------------------------------------------------

class AgentDefRegistry:
    """Discovers and manages all available agent definitions."""

    def __init__(self):
        self._defs: dict[str, AgentDef] = {}
        # Always register the base agent
        self._defs[BASE_AGENT_DEF.name] = BASE_AGENT_DEF

    def register(self, agent_def: AgentDef):
        self._defs[agent_def.name] = agent_def

    def get(self, name: str) -> Optional[AgentDef]:
        return self._defs.get(name)

    def get_all(self) -> list[AgentDef]:
        """All definitions excluding the base."""
        return [d for d in self._defs.values() if not d.is_base]

    def list_names(self) -> list[str]:
        """Names of all non-base definitions."""
        return [d.name for d in self._defs.values() if not d.is_base]


# Global singleton
_registry: Optional[AgentDefRegistry] = None


def get_agent_def_registry() -> AgentDefRegistry:
    global _registry
    if _registry is None:
        _registry = AgentDefRegistry()
    return _registry


def load_agent_defs(cwd: str):
    """
    Discover and load agent definitions from all sources:
      1. User-level:    ~/.claude/agents/
      2. Project-level: .claude/agents/  (walk up from cwd)
    """
    registry = get_agent_def_registry()

    # 1. User-level
    user_dir = os.path.join(Path.home(), ".claude", "agents")
    _scan_agents_dir(user_dir, "user", registry)

    # 2. Project-level: walk up
    current = os.path.abspath(cwd)
    home = str(Path.home())
    seen: set[str] = set()

    while True:
        agents_dir = os.path.join(current, ".claude", "agents")
        norm = os.path.normcase(agents_dir)
        if norm not in seen and os.path.isdir(agents_dir):
            seen.add(norm)
            _scan_agents_dir(agents_dir, "project", registry)

        parent = os.path.dirname(current)
        if parent == current:
            break
        if not current.startswith(home) or current == home:
            break
        current = parent


def _scan_agents_dir(directory: str, source: str, registry: AgentDefRegistry):
    """Scan a directory for agent definition files."""
    if not os.path.isdir(directory):
        return

    for entry in os.listdir(directory):
        entry_path = os.path.join(directory, entry)

        # Directory format: agent-name/AGENT.md
        if os.path.isdir(entry_path):
            for candidate in ("AGENT.md", "agent.md", "index.md"):
                agent_file = os.path.join(entry_path, candidate)
                if os.path.isfile(agent_file):
                    agent_def = load_agent_def_from_file(agent_file, source)
                    if agent_def and not registry.get(agent_def.name):
                        registry.register(agent_def)
                    break
            continue

        # Flat file format: agent-name.md
        if entry.endswith(".md") and not entry.startswith("."):
            agent_def = load_agent_def_from_file(entry_path, source)
            if agent_def and not registry.get(agent_def.name):
                registry.register(agent_def)
