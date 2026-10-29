"""Read-only PostgreSQL fallback for registered cockpit metrics.

The dashboard may fail to load one query while the rest of the page succeeds.
Rather than leaving the AI slot without evidence, the main service may re-run
*the same* metric, dimension and filter contract against the registered
PostgreSQL source.  Only reviewed registry entries are executable: anything
unmapped returns a reason code instead of a guessed number, this module never
replays the failing AP SQL and never substitutes another metric.
"""
from __future__ import annotations

import json
import re
import threading
from datetime import date, timedelta
from pathlib import Path
from typing import Any

REGISTRY_PATH = Path(__file__).parents[2] / "dataset/process360/ywln-v3.1/pg-fallback.json"
_CACHE: dict[str, Any] = {}
_LOCK = threading.RLock()
_DATE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


class FallbackUnavailable(RuntimeError):
    """The failed query cannot be answered from the registered fallback."""

    def __init__(self, code: str, detail: str = ""):
        self.code = code
        self.detail = detail
        super().__init__(f"{code}:{detail}" if detail else code)


def registry() -> dict:
    stamp = REGISTRY_PATH.stat().st_mtime_ns
    with _LOCK:
        if _CACHE.get("stamp") != stamp:
            value = json.loads(REGISTRY_PATH.read_text(encoding="utf-8"))
            _CACHE.clear()
            _CACHE.update(stamp=stamp, value=value)
        return _CACHE["value"]


def version() -> str:
    return str(registry().get("version") or "")


def enabled_metrics() -> list[str]:
    return sorted(code for code, value in (registry().get("metrics") or {}).items()
                  if value.get("status") == "enabled")


def _items(payload: dict) -> tuple[list[dict], list[dict], list[dict]]:
    config = (payload or {}).get("analysisConfig") or {}
    indicators = [item for item in config.get("indicators") or [] if isinstance(item, dict)]
    dimensions = [item for item in config.get("dimensions") or [] if isinstance(item, dict)]
    filters = ((payload or {}).get("commonConfig") or {}).get("filters") or {}
    children = filters.get("children") if isinstance(filters, dict) else None
    if children is None:
        children = [filters] if filters else []
    return indicators, dimensions, [item for item in children if isinstance(item, dict)]


def _metric(code: str) -> dict:
    value = (registry().get("metrics") or {}).get(code)
    if not value:
        raise FallbackUnavailable("METRIC_UNMAPPED", code)
    if value.get("status") != "enabled":
        raise FallbackUnavailable(str(value.get("reason") or "METRIC_DISABLED"), code)
    return value


def _bind_date(filters: list[dict], metric: dict, params: list[Any], where: list[str]) -> None:
    allowed = registry().get("timeFilters") or {}
    for item in filters:
        code = str(item.get("identifierCode") or "")
        if code not in allowed:
            raise FallbackUnavailable("FILTER_UNMAPPED", code or "unknown")
        if code == "YWLN_D044":
            values = item.get("value")
            if (not isinstance(values, list) or len(values) != 2
                    or not all(isinstance(v, str) and _DATE.match(v) for v in values)):
                raise FallbackUnavailable("FILTER_INVALID", code)
            try:
                start, end = (date.fromisoformat(v) for v in values)
            except ValueError:
                raise FallbackUnavailable("FILTER_INVALID", code) from None
            if end < start:
                raise FallbackUnavailable("FILTER_INVALID", f"{code}:range")
            column = metric.get("time")
            if not column:
                raise FallbackUnavailable("TIME_UNMAPPED", metric.get("catalog", ""))
            # Timestamps are stored as ISO text; compare prefixes so a stray
            # malformed row can never abort the whole aggregate with a cast
            # error, and keep the dashboard's inclusive day range.
            where.append(f"{column} >= %s AND {column} < %s")
            params.extend([start.isoformat(), (end + timedelta(days=1)).isoformat()])
            continue
        raise FallbackUnavailable("FILTER_UNSUPPORTED", code)


def compile_payload(payload: dict) -> dict:
    """Return a parameterised single-table aggregate or raise FallbackUnavailable."""
    indicators, dimensions, filters = _items(payload)
    if not indicators:
        raise FallbackUnavailable("METRIC_MISSING", "empty analysisConfig")
    if len(indicators) > 4:
        raise FallbackUnavailable("METRIC_LIMIT", str(len(indicators)))
    if dimensions:
        raise FallbackUnavailable("DIMENSION_UNMAPPED", str(dimensions[0].get("identifierCode") or ""))
    metrics = [_metric(str(item.get("identifierCode") or "")) for item in indicators]
    tables = {(value.get("table"), value.get("time")) for value in metrics}
    if len(tables) != 1:
        raise FallbackUnavailable("MULTI_TABLE", "indicators span more than one source")
    table, _time = next(iter(tables))
    schema = registry().get("schema") or "ywln_crm"
    where = [condition for value in metrics for condition in value.get("where") or []]
    params: list[Any] = []
    _bind_date(filters, metrics[0], params, where)
    select, columns = [], []
    for item, value in zip(indicators, metrics):
        code = str(item.get("identifierCode"))
        if value.get("catalog") and code != f"YWLN_{value['catalog']}" and code != value["catalog"]:
            raise FallbackUnavailable("METRIC_CODE_MISMATCH", code)
        select.append(f"{value['expression']} AS \"{code}\"")
        unit = value.get("unit") or ""
        label = value.get("name") or code
        columns.append(dict(identifierCode=code, label=f"{label}（{unit}）" if unit else label,
                            type="METRIC", unit=unit, decimals=int(value.get("decimals") or 0)))
    sql = f'SELECT {", ".join(select)} FROM "{schema}"."{table}"'
    if where:
        sql += " WHERE (" + ") AND (".join(dict.fromkeys(where)) + ")"
    return dict(sql=sql, params=params, columns=columns, metrics=metrics)


def query(payload: dict) -> dict:
    """Execute the compiled fallback and return an AP-shaped result payload."""
    plan = compile_payload(payload)
    from ..process360.db import DatabaseUnavailable, DatabaseQueryError, PostgresDatabase
    database = PostgresDatabase()
    if not database.available:
        raise FallbackUnavailable("PG_UNAVAILABLE", database.unavailable_reason())
    try:
        with database.snapshot() as reader:
            result = reader.run(plan["sql"], plan["params"], timeout_ms=15000, max_rows=1)
    except DatabaseUnavailable as exc:
        raise FallbackUnavailable("PG_UNAVAILABLE", str(exc)) from None
    except DatabaseQueryError as exc:
        raise FallbackUnavailable("PG_QUERY_FAILED", str(exc)) from None
    row = result.rows[0] if result.rows else {}
    values = {}
    for column in plan["columns"]:
        code = column["identifierCode"]
        raw = row.get(code)
        if raw is None:
            # Never turn an empty aggregate into a business zero.
            values[code] = {"value": None}
        elif column.get("type") == "METRIC" and column.get("decimals", 0) == 0:
            values[code] = {"value": int(round(float(raw))), "render": {"unit": column.get("unit") or ""}}
        else:
            values[code] = {"value": round(float(raw), int(column.get("decimals") or 0)),
                            "render": {"unit": column.get("unit") or ""}}
    return dict(resultType="TABLE", result=dict(columns=plan["columns"], rows=[values]),
                pagination=dict(pageNum=1, pageSize=20, total=1))


def receipt(payload: dict, result: dict, store, identity: int, ttl: int = 900) -> dict:
    # authScope carries the mapping version so a reviewed metric change
    # invalidates receipts taken with the previous definition.
    value = store.save_ap_result(identity, "pg", payload, result, ttl,
                                 f"pg:{registry().get('schema')}", version(), "postgres")
    return value


def supplement(context: dict, store, *, query_fn=None, limit: int = 4) -> tuple[dict, list[dict]]:
    """Resolve failed dashboard queries from PostgreSQL, one reviewed metric set at a time.

    At most ``limit`` queries are attempted so a page with many failures cannot
    turn one analysis request into a long serial scan of the database.
    """
    entries: dict[str, dict] = {}
    notes: list[dict] = []
    seen: set[str] = set()
    attempted = 0
    for raw in context.get("unavailableQueries") or []:
        if not isinstance(raw, str) or raw in seen:
            continue
        seen.add(raw)
        if attempted >= limit:
            notes.append(dict(query=raw, code="FALLBACK_LIMIT"))
            continue
        attempted += 1
        try:
            payload = json.loads(raw)
        except ValueError:
            notes.append(dict(query=raw, code="QUERY_INVALID"))
            continue
        if not isinstance(payload, dict):
            notes.append(dict(query=raw, code="QUERY_INVALID"))
            continue
        try:
            result = (query_fn or query)(payload)
            item = receipt(payload, result, store, int(context.get("id") or 0))
        except FallbackUnavailable as exc:
            notes.append(dict(query=raw, code=exc.code, detail=str(exc.detail)[:200]))
            continue
        key = "pg:" + str(item["id"])
        entries[key] = dict(request=payload, response=item["response"], receivedAt=item["createdAt"],
                            source="pg", receiptId=item["id"], connectionId=item.get("connectionId", ""),
                            transport="postgres")
    return entries, notes
