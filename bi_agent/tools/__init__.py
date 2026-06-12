"""
BI-specific tools — ontology lookup + SQL execution.

Call `register_all(store, db_path)` to plug these into open_claude's tool
registry. The AgentDef for bi-analyst whitelists them by name.
"""

from __future__ import annotations

from pathlib import Path

from open_claude.tools import register_tool

from ..ontology.store import OntologyStore
from . import (
    ask_user,
    chart_multidim_tools,
    chart_tools,
    ontology_tools,
    sql_tools,
    table_tools,
    todo_tools,
)


def register_all(
    store: OntologyStore,
    db_path: str | Path,
    *,
    doris: "sql_tools.DorisConn | None" = None,
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
    for schema, make_executor in sql_tools.SPECS:
        register_tool(schema, make_executor(sql_backend))
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
    return registered
