"""
BI-specific tools — ontology lookup + SQL execution.

Call `register_all(store, db_path)` to plug these into open_claude's tool
registry. The AgentDef for bi-analyst whitelists them by name.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Callable

from open_claude.tools import register_tool

from ..concurrency import get_current_cancel, get_doris_limiter, get_ontology_limiter
from ..ontology.store import OntologyStore
from ..ontology.remote import RemoteOntologyClient
from .remote_ontology_tools import remote_specs
from . import (
    ask_user,
    chart_multidim_tools,
    chart_tools,
    graph_tools,
    ontology_tools,
    sql_tools,
    table_tools,
    todo_tools,
)

Executor = Callable[[dict[str, Any], str], str]


def _limited_executor(executor: Executor, limiter) -> Executor:
    """Wrap an executor so every network-facing call is gated by the shared
    downstream concurrency budget.  The slot is always released in finally."""
    def wrapped(params: dict[str, Any], cwd: str) -> str:
        # The wait is cooperative: the session layer stamps the turn's cancel
        # event on the current thread right before invoking gated executors,
        # so a reset/restore/disconnect aborts the wait promptly.
        token = limiter.acquire(cancel_event=get_current_cancel())
        try:
            return executor(params, cwd)
        finally:
            token.release()
    return wrapped


def build_source_executors(
    store: OntologyStore,
    db_path: str | Path,
    *,
    doris: "sql_tools.DorisConn | None" = None,
    remote_ontology: RemoteOntologyClient | None = None,
) -> dict[str, Executor]:
    """Build source-bound executors without mutating the process registry.

    Web sessions keep this mapping for their lifetime, so one browser changing
    repository/database cannot redirect another browser's active tools.
    """
    backend = sql_tools.SqlBackend(db_path=str(db_path), doris=doris)
    executors: dict[str, Executor] = {
        schema["name"]: make_executor(store)
        for schema, make_executor in ontology_tools.SPECS
    }
    executors.update({
        schema["name"]: make_executor(store)
        for schema, make_executor in graph_tools.SPECS
    })
    executors.update({
        schema["name"]: _limited_executor(make_executor(backend), get_doris_limiter())
        for schema, make_executor in sql_tools.SPECS
    })
    if remote_ontology is not None:
        executors.update({
            schema["name"]: _limited_executor(executor, get_ontology_limiter())
            for schema, executor in remote_specs(remote_ontology)
        })
    return executors


def register_all(
    store: OntologyStore,
    db_path: str | Path,
    *,
    doris: "sql_tools.DorisConn | None" = None,
    remote_ontology: RemoteOntologyClient | None = None,
) -> list[str]:
    """Register all BI tools with open_claude. Returns the list of tool names.

    When `doris` is a DorisConn the SQL tools query Apache Doris over the MySQL
    protocol instead of the local SQLite `db_path`.
    """
    db_path = str(db_path)
    sql_backend = sql_tools.SqlBackend(db_path=db_path, doris=doris)
    registered: list[str] = []
    for schema, make_executor in ontology_tools.SPECS:
        register_tool(schema, make_executor(store))
        registered.append(schema["name"])
    # Graph-mode retrieval tools (whitelisted for the agent only in 图库检索 mode).
    for schema, make_executor in graph_tools.SPECS:
        register_tool(schema, make_executor(store))
        registered.append(schema["name"])
    for schema, make_executor in sql_tools.SPECS:
        register_tool(schema, _limited_executor(make_executor(sql_backend), get_doris_limiter()))
        registered.append(schema["name"])
    for schema, make_executor in chart_tools.SPECS:
        register_tool(schema, make_executor())
        registered.append(schema["name"])
    for schema, make_executor in chart_multidim_tools.SPECS:
        register_tool(schema, make_executor())
        registered.append(schema["name"])
    for schema, make_executor in table_tools.SPECS:
        register_tool(schema, make_executor())
        registered.append(schema["name"])
    for schema, make_executor in todo_tools.SPECS:
        register_tool(schema, make_executor())
        registered.append(schema["name"])
    for schema, make_executor in ask_user.SPECS:
        register_tool(schema, make_executor())
        registered.append(schema["name"])
    # In remote mode, replace only ontology-facing executors. SQL, charts,
    # reports and the local Excel fallback remain available unchanged.
    if remote_ontology is not None:
        for schema, executor in remote_specs(remote_ontology):
            register_tool(schema, _limited_executor(executor, get_ontology_limiter()))
    return registered
