# vendored from bi_agent/tools/sql_tools.py (c94d430) — 只读 SQL 守卫原样摘录。
# 只依赖标准库。任何取数都必须先过 validate_sql，不得放宽。
from __future__ import annotations

import re

_ALLOWED_LEAD = re.compile(r"^\s*(select|with|pragma|explain)\b", re.IGNORECASE)
#: The remote analysis gateway's own validator only accepts statements that
#: lead with ``SELECT`` or ``MATCH`` (``WITH`` / ``EXPLAIN`` / ``PRAGMA`` are
#: rejected with a generic 400).  Local validation must not forward a statement
#: the gateway is known to refuse (Spec R11).
_GATEWAY_LEAD = re.compile(r"^\s*(select|match)\b", re.IGNORECASE)
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
    # PRAGMA is retained for schema inspection (for example
    # ``PRAGMA table_info('orders')``), but assignment forms can change SQLite
    # connection/database state and violate Ontology-FactQuery's read-only contract.
    if re.match(r"^\s*pragma\b", s, re.IGNORECASE) and "=" in s:
        return "PRAGMA assignment is not permitted"
    if _FORBIDDEN.search(s):
        return "SQL contains a forbidden keyword (write/DDL)"
    return None
