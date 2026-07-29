"""
SQL tools — safe read-only execution against the customer data source.

Two backends are supported, selected per-registration via `SqlBackend`:

  * SQLite  — local `.db` file (default).
  * Doris   — the team's read-only HTTP query endpoint (see `DorisHttpConn`).

Only SELECT / WITH / PRAGMA / EXPLAIN statements are allowed. A single call
executes exactly one statement. Results are truncated to a row cap so the
LLM context stays manageable.
"""

from __future__ import annotations

import re
import sqlite3
import json
import os
from urllib.request import Request, urlopen
from typing import Callable

Executor = Callable[[dict, str], str]


# ---------------------------------------------------------------------------
# Doris connection (MySQL wire protocol)
# ---------------------------------------------------------------------------

# Doris defaults; the HTTP endpoint is used by the active web application.
DEFAULT_DORIS_JDBC_URL = (
    "jdbc:mysql://172.16.6.163:9030/ontology_demometaerp_scm_po"
    "?useSSL=false&allowPublicKeyRetrieval=true&serverTimezone=UTC"
)
DEFAULT_DORIS_DRIVER = "com.mysql.cj.jdbc.Driver"
DEFAULT_DORIS_USERNAME = "admin"
DEFAULT_DORIS_PASSWORD = ""
# Active Doris database (schema). Tables are referenced db-qualified in SQL,
# e.g. `ontology_demometaerp_scm_po.poheader`. Overridable via the 数据源设置 UI or
# the DORIS_DATABASE env var; falls back to the schema in the JDBC URL.
DEFAULT_DORIS_DATABASE = "ontology_demometaerp_scm_po"
DEFAULT_DORIS_API_URL = "http://172.16.5.181:30834/agent/doris/query"


class DorisApiError(Exception):
    """Raised when a Doris connection or query fails."""


def _parse_jdbc_mysql(jdbc_url: str) -> tuple[str, int, str]:
    """Extract (host, port, database) from a `jdbc:mysql://host:port/db?...` URL."""
    m = re.match(
        r"^jdbc:mysql://(?P<host>[^:/?]+)(?::(?P<port>\d+))?/(?P<db>[^?/]+)",
        (jdbc_url or "").strip(),
        re.IGNORECASE,
    )
    if not m:
        raise ValueError(
            "需形如 jdbc:mysql://HOST:PORT/DATABASE?params 的 JDBC 地址"
        )
    return m.group("host"), int(m.group("port") or 3306), m.group("db")


class DorisConn:
    """A Doris (MySQL-protocol) connection spec parsed from a JDBC URL."""

    def __init__(
        self,
        jdbc_url: str,
        username: str = DEFAULT_DORIS_USERNAME,
        password: str = DEFAULT_DORIS_PASSWORD,
        driver: str = DEFAULT_DORIS_DRIVER,
        database: str | None = None,
    ) -> None:
        self.jdbc_url = (jdbc_url or "").strip()
        self.username = username or ""
        self.password = password or ""
        self.driver = driver or DEFAULT_DORIS_DRIVER
        self.host, self.port, url_db = _parse_jdbc_mysql(self.jdbc_url)
        # An explicit `database` overrides the schema baked into the JDBC URL,
        # so the UI can switch databases without rewriting the connection URL.
        self.database = (database or "").strip() or url_db

    def __repr__(self) -> str:  # pragma: no cover - debug aid
        return f"DorisConn({self.host}:{self.port}/{self.database}, user={self.username!r})"


class DorisHttpConn:
    """Doris query endpoint exposed by the team ontology service."""

    def __init__(self, api_url: str, database: str = DEFAULT_DORIS_DATABASE) -> None:
        self.api_url = (api_url or "").strip()
        if not self.api_url:
            raise ValueError("需填写 Doris HTTP API 地址")
        self.database = (database or DEFAULT_DORIS_DATABASE).strip()
        self.host = "HTTP API"
        self.port = 0

    def __repr__(self) -> str:  # pragma: no cover
        return f"DorisHttpConn({self.api_url}, database={self.database})"


# ---------------------------------------------------------------------------
# Backend descriptor
# ---------------------------------------------------------------------------

class SqlBackend:
    """Where the SQL tools run their queries.

    Pass a `DorisConn` to query Apache Doris over the MySQL protocol; otherwise
    queries hit the local SQLite `db_path`.
    """

    def __init__(self, db_path: str = "", doris: "DorisConn | None" = None) -> None:
        self.db_path = str(db_path or "")
        self.doris = doris

    @property
    def is_doris(self) -> bool:
        return self.doris is not None

    @property
    def label(self) -> str:
        if self.doris is not None:
            return f"Doris {self.doris.host}:{self.doris.port}/{self.doris.database}"
        return self.db_path


def _coerce_backend(source: "SqlBackend | str") -> SqlBackend:
    """Accept either a SqlBackend or a bare db_path string (back-compat)."""
    return source if isinstance(source, SqlBackend) else SqlBackend(db_path=str(source))


ExecutorFactory = Callable[["SqlBackend | str"], Executor]


# ---------------------------------------------------------------------------
# Doris query execution (pymysql, imported lazily so the module loads without it)
# ---------------------------------------------------------------------------

def _doris_query(conn: DorisConn | DorisHttpConn, sql: str) -> tuple[list[str], list[tuple]]:
    """Run a read-only statement through the configured Doris transport."""
    if isinstance(conn, DorisHttpConn):
        headers = {"Accept": "application/json", "Content-Type": "application/json"}
        for name, env_name in (
            ("X-Ontology-Repository-Id", "ONTOLOGY_REPOSITORY_ID"),
            ("X-App-Id", "ONTOLOGY_APP_ID"),
            ("Authorization", "ONTOLOGY_AUTH_TOKEN"),
        ):
            value = os.environ.get(env_name, "").strip()
            if value:
                headers[name] = value
        try:
            request = Request(
                conn.api_url,
                data=json.dumps({"sql": sql}, ensure_ascii=False).encode("utf-8"),
                headers=headers,
                method="POST",
            )
            with urlopen(request, timeout=60) as response:
                payload = json.loads(response.read().decode("utf-8", errors="replace"))
        except Exception as e:
            raise DorisApiError(f"Doris HTTP API 请求失败 ({conn.api_url}): {e}") from e
        if isinstance(payload, dict) and payload.get("success") is False:
            raise DorisApiError(str(payload.get("msg") or "Doris HTTP API 返回失败"))
        data = payload.get("data", payload) if isinstance(payload, dict) else {}
        raw_rows = data.get("rows", []) if isinstance(data, dict) else []
        if not raw_rows:
            return [], []
        if isinstance(raw_rows[0], dict):
            columns: list[str] = []
            for row in raw_rows:
                for key in row:
                    if key not in columns:
                        columns.append(key)
            return columns, [tuple(row.get(c) for c in columns) for row in raw_rows]
        columns = data.get("columns", []) if isinstance(data, dict) else []
        return list(columns), [tuple(row) for row in raw_rows]
    try:
        import pymysql  # lazy: only required when the Doris source is active
    except ImportError as e:  # pragma: no cover - environment dependent
        raise DorisApiError(
            "未安装 pymysql,无法连接 Doris。请先 `pip install pymysql`。"
        ) from e
    try:
        cx = pymysql.connect(
            host=conn.host,
            port=conn.port,
            user=conn.username,
            password=conn.password,
            database=conn.database,
            charset="utf8mb4",
            connect_timeout=10,
            read_timeout=60,
        )
    except Exception as e:  # pymysql.err.OperationalError etc.
        raise DorisApiError(
            f"无法连接 Doris ({conn.host}:{conn.port}/{conn.database}): {e}"
        ) from e
    try:
        cur = cx.cursor()
        cur.execute(sql)
        columns = [d[0] for d in cur.description] if cur.description else []
        rows = list(cur.fetchall())
    except Exception as e:
        raise DorisApiError(f"{e}") from e
    finally:
        cx.close()
    return columns, rows


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
        # A few HTTP SQL gateways omit or under-report column metadata for
        # empty/heterogeneous result sets. Keep formatting diagnostic output
        # useful instead of raising IndexError on a wider row.
        if len(cells) > len(widths):
            widths.extend([0] * (len(cells) - len(widths)))
        for i, c in enumerate(cells):
            widths[i] = min(max(widths[i], len(c)), 60)

    if len(columns) < len(widths):
        columns = list(columns) + [f"column_{i + 1}" for i in range(len(columns), len(widths))]
    for i, column in enumerate(columns):
        if i < len(widths):
            widths[i] = min(max(widths[i], len(str(column))), 60)

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
        "Execute a single read-only SQL statement against the customer "
        "database. The active source is either a local SQLite DB or Apache "
        "Doris (MySQL protocol), selected in 数据源设置. Writes, DDL, and "
        "multi-statement scripts are rejected. When Doris is active, use "
        "standard MySQL/ANSI SQL (PRAGMA is SQLite-only). Use this after "
        "you've resolved the metric spec and relations from the ontology. "
        "When Doris is active, table names MUST be database-qualified "
        "(e.g. ontology_demo_scm_po.poheader) — run ListTables first to get "
        "the exact db.table prefixes."
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


def _make_sql_run(source: "SqlBackend | str") -> Executor:
    backend = _coerce_backend(source)

    def run(params: dict, cwd: str) -> str:
        sql = (params.get("sql") or "").strip()
        limit = int(params.get("limit") or 100)
        err = _validate_sql(sql)
        if err:
            return f"SQLRun rejected: {err}\nSQL: {sql}"
        header = f"SQL: {sql}"
        if backend.is_doris:
            clean = sql.strip().rstrip(";").strip()
            try:
                columns, rows = _doris_query(backend.doris, clean)
            except DorisApiError as e:
                return f"SQLRun (Doris) error: {e}\nSQL: {sql}"
            return header + "\n\n" + _format_rows(columns, rows, limit)
        try:
            conn = sqlite3.connect(backend.db_path)
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


def _list_tables_doris(backend: SqlBackend) -> str:
    # Scope to the connected database. table_rows is an estimate maintained by
    # Doris (good enough for an existence / scale check, and far cheaper than
    # COUNT(*) over large columnar tables).
    conn = backend.doris
    sql = (
        "SELECT table_name, table_rows FROM information_schema.tables "
        f"WHERE table_schema = '{conn.database}' ORDER BY table_name"
    )
    try:
        _cols, rows = _doris_query(conn, sql)
    except DorisApiError as e:
        return f"ListTables (Doris) error: {e}"
    out = [
        f"# Tables in Doris {conn.host}:{conn.port}/{conn.database} ({len(rows)})",
        f"# 注意: 写 SQL 时表名必须带库前缀 `{conn.database}.<表名>`(例如 "
        f"`{conn.database}.poheader`)。",
    ]
    for name, cnt in rows:
        cnt_s = "?" if cnt is None else cnt
        out.append(f"  {conn.database}.{name}  ({cnt_s} rows est.)")
    return "\n".join(out)


def _make_list_tables(source: "SqlBackend | str") -> Executor:
    backend = _coerce_backend(source)

    def run(params: dict, cwd: str) -> str:
        if backend.is_doris:
            return _list_tables_doris(backend)
        try:
            conn = sqlite3.connect(backend.db_path)
            cur = conn.cursor()
            cur.execute(
                "SELECT name FROM sqlite_master "
                "WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name"
            )
            names = [r[0] for r in cur.fetchall()]
            out = [f"# Tables in {backend.db_path} ({len(names)})"]
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
            "table": {
                "type": "string",
                "description": (
                    "Physical table name. For Doris you may pass it "
                    "db-qualified as `database.table` (e.g. "
                    "ontology_demo_scm_po.poheader); a bare name uses the "
                    "active Doris database."
                ),
            },
        },
        "required": ["table"],
    },
}


def _describe_table_doris(backend: SqlBackend, schema: str, table: str) -> str:
    conn = backend.doris
    sql = (
        "SELECT column_name, data_type, is_nullable, column_key "
        "FROM information_schema.columns "
        f"WHERE table_schema = '{schema}' AND table_name = '{table}' "
        "ORDER BY ordinal_position"
    )
    try:
        _cols, rows = _doris_query(conn, sql)
    except DorisApiError as e:
        return f"DescribeTable (Doris) error: {e}"
    if not rows:
        return f"DescribeTable: table {table!r} not found or has no columns."
    lines = [f"# {table} — {len(rows)} columns"]
    for name, type_, is_nullable, key in rows:
        marker = " [PK]" if str(key).upper() in ("PRI", "PRIMARY") else ""
        null_s = "NULL" if str(is_nullable).upper() in ("YES", "1", "TRUE") else "NOT NULL"
        lines.append(f"  {name}  {type_}  {null_s}{marker}")
    return "\n".join(lines)


def _make_describe_table(source: "SqlBackend | str") -> Executor:
    backend = _coerce_backend(source)

    def run(params: dict, cwd: str) -> str:
        table = (params.get("table") or "").strip()
        if not table:
            return "DescribeTable: empty table."
        if backend.is_doris:
            # Accept either a bare name or a db-qualified `schema.table`; the
            # schema defaults to the active Doris database when omitted.
            m = re.fullmatch(
                r"(?:([A-Za-z_][A-Za-z0-9_]*)\.)?([A-Za-z_][A-Za-z0-9_]*)", table
            )
            if not m:
                return f"DescribeTable: invalid table name {table!r}."
            schema = m.group(1) or backend.doris.database
            return _describe_table_doris(backend, schema, m.group(2))
        if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", table):
            return f"DescribeTable: invalid table name {table!r}."
        try:
            conn = sqlite3.connect(backend.db_path)
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
