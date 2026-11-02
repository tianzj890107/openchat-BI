"""Experimental, opt-in analysis runtimes.

Nothing in this package is imported by the production startup path.  Use
``bi_agent.experimental.factory.resolve_session_class`` to select an engine.
"""

from .factory import ENGINE_ENV, engine_name, resolve_session_class

__all__ = ["ENGINE_ENV", "engine_name", "resolve_session_class"]
