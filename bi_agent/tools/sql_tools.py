"""
SQL tools — safe read-only execution against the customer SQLite DB.

Only SELECT / WITH / PRAGMA / EXPLAIN statements are allowed. A single call
executes exactly one statement. Results are truncated to a row cap so the
LLM context stays manageable.
"""

from __future__ import annotations

import re
import sqlite3
from typing import Callable

Executor = Callable[[dict, str], str]
ExecutorFactory = Callable[[str], Executor]


_ALLOWED_LEAD = re.compile(r"^\s*(select|with|pragma|explain)\b", re.IGNORECASE)
_FORBIDDEN = re.compile(
    r"\b(insert|update|delete|drop|alter|create|replace|truncate|attach|detach|vacuum|reindex)\b",
    re.IGNORECASE,
)


def _validate_sql(sql: str) -> str | None:
    """Return an error message if SQL is not safe-read, else None."""
    s = sql.strip().rstrip(";").strip()
    if not s:
        return "empty SQL"
    if ";" in s:
        return "multi-statement SQL is not allowed"
    if not _ALLOWED_LEAD.match(s):
        return "only SELECT / WITH / PRAGMA / EXPLAIN are permitted"
    if _FORBIDDEN.search(s):
        return "SQL contains a forbidden keyword (write/DDL)"
    return None


def _format_rows(columns: list[str], rows: list[tuple], max_rows: int) -> str:
    if not rows:
        return "(0 rows)"
    shown = rows[:max_rows]
    widths = [len(c) for c in columns]
    str_rows: list[list[str]] = []
    for r in shown:
        cells = ["" if v is None else str(v) for v in r]
        str_rows.append(cells)
        for i, c in enumerate(cells):
            if i < len(widths):
                widths[i] = min(max(widths[i], len(c)), 60)

    def _fmt(cells: list[str]) -> str:
        return " | ".join(c.ljust(widths[i])[: widths[i]] for i, c in enumerate(cells))

    lines = [_fmt(columns), "-+-".join("-" * w for w in widths)]
    for cells in str_rows:
        lines.append(_fmt(cells))
    if len(rows) > max_rows:
        lines.append(f"... ({len(rows) - max_rows} more rows truncated)")
    lines.append(f"\n[{len(rows)} row(s), showing {len(shown)}]")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# SQLRun
# ---------------------------------------------------------------------------

SQL_RUN_SCHEMA = {
    "name": "SQLRun",
    "description": (
        "Execute a single read-only SQL statement (SELECT / WITH / PRAGMA / "
        "EXPLAIN) against the customer SQLite database. Writes, DDL, and "
        "multi-statement scripts are rejected. Use this after you've resolved "
        "the metric spec and relations from the ontology."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "sql": {"type": "string", "description": "A single read-only statement."},
            "limit": {
                "type": "integer",
                "description": "Max rows to return in output (default 100).",
            },
        },
        "required": ["sql"],
    },
}


def _make_sql_run(db_path: str) -> Executor:
    def run(params: dict, cwd: str) -> str:
        sql = (params.get("sql") or "").strip()
        limit = int(params.get("limit") or 100)
        err = _validate_sql(sql)
        if err:
            return f"SQLRun rejected: {err}\nSQL: {sql}"
        try:
            conn = sqlite3.connect(db_path)
            conn.row_factory = None
            cur = conn.cursor()
            cur.execute(sql)
            if cur.description is None:
                conn.close()
                return "SQLRun: statement returned no result set."
            columns = [d[0] for d in cur.description]
            rows = cur.fetchall()
            conn.close()
        except sqlite3.Error as e:
            return f"SQLRun error: {e}\nSQL: {sql}"
        header = f"SQL: {sql}"
        return header + "\n\n" + _format_rows(columns, rows, limit)
    return run


# ---------------------------------------------------------------------------
# ListTables
# ---------------------------------------------------------------------------

LIST_TABLES_SCHEMA = {
    "name": "ListTables",
    "description": (
        "List all tables in the customer database with row counts. Useful "
        "when you need to confirm a physical table exists before querying."
    ),
    "input_schema": {"type": "object", "properties": {}},
}


def _make_list_tables(db_path: str) -> Executor:
    def run(params: dict, cwd: str) -> str:
        try:
            conn = sqlite3.connect(db_path)
            cur = conn.cursor()
            cur.execute(
                "SELECT name FROM sqlite_master "
                "WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name"
            )
            names = [r[0] for r in cur.fetchall()]
            out = [f"# Tables in {db_path} ({len(names)})"]
            for n in names:
                try:
                    cur.execute(f'SELECT COUNT(*) FROM "{n}"')
                    cnt = cur.fetchone()[0]
                    out.append(f"  {n}  ({cnt} rows)")
                except sqlite3.Error:
                    out.append(f"  {n}  (count failed)")
            conn.close()
            return "\n".join(out)
        except sqlite3.Error as e:
            return f"ListTables error: {e}"
    return run


# ---------------------------------------------------------------------------
# DescribeTable
# ---------------------------------------------------------------------------

DESCRIBE_TABLE_SCHEMA = {
    "name": "DescribeTable",
    "description": (
        "Show the physical column list of a table (name, type, primary key, "
        "nullable). Use this to cross-check ontology attributes against the "
        "actual DB schema before writing SQL."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "table": {"type": "string", "description": "Physical table name."},
        },
        "required": ["table"],
    },
}


def _make_describe_table(db_path: str) -> Executor:
    def run(params: dict, cwd: str) -> str:
        table = (params.get("table") or "").strip()
        if not table:
            return "DescribeTable: empty table."
        if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", table):
            return f"DescribeTable: invalid table name {table!r}."
        try:
            conn = sqlite3.connect(db_path)
            cur = conn.cursor()
            cur.execute(f'PRAGMA table_info("{table}")')
            rows = cur.fetchall()
            conn.close()
        except sqlite3.Error as e:
            return f"DescribeTable error: {e}"
        if not rows:
            return f"DescribeTable: table {table!r} not found or has no columns."
        lines = [f"# {table} — {len(rows)} columns"]
        for _, name, type_, notnull, dflt, pk in rows:
            marker = " [PK]" if pk else ""
            null_s = "NOT NULL" if notnull else "NULL"
            dflt_s = f" DEFAULT {dflt}" if dflt is not None else ""
            lines.append(f"  {name}  {type_}  {null_s}{dflt_s}{marker}")
        return "\n".join(lines)
    return run


# ---------------------------------------------------------------------------
# Registry
# ---------------------------------------------------------------------------

SPECS: list[tuple[dict, ExecutorFactory]] = [
    (SQL_RUN_SCHEMA, _make_sql_run),
    (LIST_TABLES_SCHEMA, _make_list_tables),
    (DESCRIBE_TABLE_SCHEMA, _make_describe_table),
]
