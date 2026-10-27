"""Read-only PostgreSQL adapter for Process360 business facts.

Only this module knows how to reach the customer database.  MCP callers never
provide SQL, a DSN, or credentials: ``queries.py`` selects a named, parameterised
statement and this adapter executes it in a read-only transaction with a hard
statement timeout.
"""

from __future__ import annotations

import os
import re
import time
from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal
from typing import Any, Mapping, Sequence
from uuid import UUID


class DatabaseUnavailable(RuntimeError):
    """The database is not configured or its driver is unavailable."""


class DatabaseQueryError(RuntimeError):
    """A controlled statement failed; the message is safe to return."""


@dataclass(frozen=True)
class DatabaseConfig:
    host: str = ""
    port: int = 5432
    database: str = ""
    user: str = ""
    password: str = field(default="", repr=False)
    schema: str = "ywln_crm"
    dsn: str = field(default="", repr=False)
    connect_timeout: int = 5
    statement_timeout_ms: int = 15000
    enabled: bool = True

    @classmethod
    def from_env(cls) -> "DatabaseConfig":
        def integer(name: str, default: int) -> int:
            try:
                return int(os.environ.get(name, str(default)))
            except ValueError:
                return default

        enabled_raw = (os.environ.get("PROCESS360_PG_ENABLED") or "1").strip().lower()
        return cls(
            host=(os.environ.get("PROCESS360_PG_HOST") or "").strip(),
            port=integer("PROCESS360_PG_PORT", 5432),
            database=(os.environ.get("PROCESS360_PG_DATABASE") or "").strip(),
            user=(os.environ.get("PROCESS360_PG_USER") or "").strip(),
            password=os.environ.get("PROCESS360_PG_PASSWORD") or "",
            schema=(os.environ.get("PROCESS360_PG_SCHEMA") or "ywln_crm").strip() or "ywln_crm",
            dsn=(os.environ.get("PROCESS360_PG_DSN") or "").strip(),
            connect_timeout=max(1, min(integer("PROCESS360_PG_CONNECT_TIMEOUT", 5), 30)),
            statement_timeout_ms=max(1000, min(integer("PROCESS360_PG_STATEMENT_TIMEOUT_MS", 15000), 120000)),
            enabled=enabled_raw not in {"0", "false", "no", "off"},
        )

    def ready(self) -> tuple[bool, str]:
        if not self.enabled:
            return False, "PROCESS360_PG_ENABLED=0"
        if self.dsn:
            return True, ""
        missing = [
            name for name, value in (
                ("PROCESS360_PG_HOST", self.host),
                ("PROCESS360_PG_DATABASE", self.database),
                ("PROCESS360_PG_USER", self.user),
            ) if not value
        ]
        if missing:
            return False, "缺少只读数据库配置：" + "、".join(missing)
        return True, ""

    def public_dict(self) -> dict[str, Any]:
        return {
            "host": self.host,
            "port": self.port,
            "database": self.database,
            "schema": self.schema,
            "user": self.user,
            "configured": self.ready()[0],
            "readOnly": True,
        }


@dataclass
class QueryResult:
    columns: list[str]
    rows: list[dict[str, Any]]
    duration_ms: int
    truncated: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "columns": list(self.columns),
            "rows": [dict(row) for row in self.rows],
            "durationMs": self.duration_ms,
            "truncated": self.truncated,
        }


_READ_ONLY_START = re.compile(r"^\s*(select|with)\b", re.IGNORECASE)
_FORBIDDEN = re.compile(
    r"\b(insert|update|delete|merge|drop|alter|create|truncate|grant|revoke|copy|call|do)\b",
    re.IGNORECASE,
)


def ensure_read_only(sql: str) -> None:
    text = str(sql or "").strip()
    if not _READ_ONLY_START.match(text):
        raise DatabaseQueryError("Process360 只允许 SELECT/CTE 查询")
    if _FORBIDDEN.search(text):
        raise DatabaseQueryError("Process360 查询包含非只读语句")
    if ";" in text.rstrip("; \n\t"):
        raise DatabaseQueryError("Process360 查询不允许包含多条语句")


def _json_safe(value: Any) -> Any:
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, UUID):
        return str(value)
    if isinstance(value, (list, tuple)):
        return [_json_safe(item) for item in value]
    if isinstance(value, Mapping):
        return {str(key): _json_safe(item) for key, item in value.items()}
    return value


class PostgresDatabase:
    """One short-lived, read-only connection per controlled query."""

    def __init__(self, config: DatabaseConfig | None = None, *, max_rows: int = 5000) -> None:
        self.config = config or DatabaseConfig.from_env()
        self.max_rows = max(1, min(int(max_rows), 20000))

    @property
    def available(self) -> bool:
        return self.config.ready()[0]

    def unavailable_reason(self) -> str:
        return self.config.ready()[1]

    def _connect(self) -> Any:
        try:
            import psycopg  # type: ignore[import-not-found]
            from psycopg.rows import dict_row  # type: ignore[import-not-found]
        except ImportError as exc:
            raise DatabaseUnavailable(
                "未安装 psycopg；安装 web 依赖后再启用 Process360 数据库取数"
            ) from exc
        ready, reason = self.config.ready()
        if not ready:
            raise DatabaseUnavailable(reason)
        kwargs: dict[str, Any] = {
            "connect_timeout": self.config.connect_timeout,
            "row_factory": dict_row,
            "application_name": "process360-readonly",
        }
        try:
            if self.config.dsn:
                connection = psycopg.connect(self.config.dsn, **kwargs)
            else:
                connection = psycopg.connect(
                    host=self.config.host,
                    port=self.config.port,
                    dbname=self.config.database,
                    user=self.config.user,
                    password=self.config.password,
                    **kwargs,
                )
        except Exception as exc:  # noqa: BLE001 - safe, credential-free message
            raise DatabaseUnavailable(f"只读数据库连接失败：{type(exc).__name__}") from exc
        connection.read_only = True
        return connection

    def run(self, sql: str, params: Sequence[Any] | Mapping[str, Any] | None = None,
            *, timeout_ms: int | None = None, max_rows: int | None = None) -> QueryResult:
        ensure_read_only(sql)
        started = time.monotonic()
        connection = self._connect()
        limit = max(1, min(int(max_rows or self.max_rows), self.max_rows))
        try:
            with connection.cursor() as cursor:
                cursor.execute(
                    "select set_config('statement_timeout', %s, true)",
                    (str(int(timeout_ms or self.config.statement_timeout_ms)),),
                )
                cursor.execute(sql, params or ())
                columns = [str(item.name) for item in (cursor.description or ())]
                rows = cursor.fetchmany(limit + 1)
                truncated = len(rows) > limit
                rows = rows[:limit]
            connection.rollback()
        except (DatabaseUnavailable, DatabaseQueryError):
            raise
        except Exception as exc:  # noqa: BLE001 - no DSN/password in message
            try:
                connection.rollback()
            except Exception:
                pass
            raise DatabaseQueryError(f"只读查询失败：{type(exc).__name__}: {str(exc)[:300]}") from exc
        finally:
            try:
                connection.close()
            except Exception:
                pass
        duration = int((time.monotonic() - started) * 1000)
        return QueryResult(columns, [_json_safe(dict(row)) for row in rows], duration, truncated)


def schema_table(schema: str, table: str) -> str:
    """Quote a trusted logical-entity table name (e.g. LE000013)."""
    if not re.fullmatch(r"[A-Za-z0-9_]+", schema or ""):
        raise DatabaseQueryError("invalid schema name")
    if not re.fullmatch(r"[A-Za-z0-9_]+", table or ""):
        raise DatabaseQueryError("invalid table name")
    return f'"{schema}"."{table}"'
