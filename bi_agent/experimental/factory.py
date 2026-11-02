"""Factory for opt-in analysis engines.

The legacy engine is the default.  Importing this module must not import
LangGraph or any experimental dependency; the LangGraph module is imported only
after an explicit engine selection.
"""

from __future__ import annotations

import os
from typing import Optional, Type

from bi_agent.web.session import WebSession


ENGINE_ENV = "CHATBI_AGENT_ENGINE"
LEGACY_ENGINES = frozenset({"", "legacy", "default", "web", "classic"})
LANGGRAPH_ENGINES = frozenset({"langgraph", "graph", "lg"})


def engine_name(value: Optional[str] = None) -> str:
    raw = value if value is not None else os.environ.get(ENGINE_ENV, "")
    return str(raw or "").strip().lower()


def resolve_session_class(value: Optional[str] = None) -> Type[WebSession]:
    engine = engine_name(value)
    if engine in LEGACY_ENGINES:
        return WebSession
    if engine in LANGGRAPH_ENGINES:
        from .langgraph_session import LangGraphWebSession

        return LangGraphWebSession
    raise ValueError(
        f"unknown analysis engine {engine!r}; "
        f"expected one of legacy, {', '.join(sorted(LANGGRAPH_ENGINES))}"
    )


def resolve_session_class_from_env() -> Type[WebSession]:
    return resolve_session_class()
