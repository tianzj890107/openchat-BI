#!/usr/bin/env python3
"""High-level metric query helpers used by the ontology MCP server.

The low-level ``Ontology-MetricQuery`` tool is intentionally close to the
remote MAL contract.  Agents repeatedly paid several model/tool round trips to
resolve a metric, construct a filter tree, split a date range by month, and
drill into dimensions.  ``MetricFactQuery`` packages those deterministic steps
into one tool call while still using the same underlying executor and payload.
"""

from __future__ import annotations

import calendar
import json
import os
import re
import threading
import time
from collections import OrderedDict
from datetime import date, datetime, timedelta
from decimal import Decimal, InvalidOperation
from typing import Any, Callable


Executor = Callable[[dict[str, Any], str], str]
METRIC_CODE_RE = re.compile(r"\bM\d{3,}\b")
METRIC_LINE_RE = re.compile(
    r"^\s*\[(?P<code>M\d{3,})\]\s+(?P<name>.+?)\s+\((?:Indicator|指标)\)\s*$",
    re.MULTILINE,
)
DEFAULT_TIME_DIMENSION = "D001"
DEFAULT_APPROVAL_ATTRIBUTE = os.environ.get(
    "ONTOLOGY_APPROVAL_ATTRIBUTE_CODE", "AT0000211"
).strip() or "AT0000211"
DEFAULT_APPROVAL_VALUE = os.environ.get(
    "ONTOLOGY_APPROVAL_VALUE", "APPROVED"
).strip() or "APPROVED"
DEFAULT_MANAGEMENT_UNIT_ATTRIBUTE = os.environ.get(
    "ONTOLOGY_MANAGEMENT_UNIT_ATTRIBUTE_CODE", "AT0000190"
).strip() or "AT0000190"


SCHEMA: dict[str, Any] = {
    "name": "MetricFactQuery",
    "description": (
        "高层单次取数：按指标名称/编码、时间范围、管理单元和已审批口径一次完成"
        "指标解析、过滤树构造、月度拆分与维度下钻。普通事实查询优先使用本工具，"
        "不要先连续调用 SemanticQuery + MetricCalculation + 多次 MetricQuery。"
        "已给 M 编码和维度编码时，本工具就是第一笔业务调用；无需预查口径或维度名称，"
        "返回值会带回 metric_names / dimension_names。"
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "metric": {
                "type": "string",
                "description": "指标编码或业务名称，例如 M0001 或 采购金额。",
            },
            "metric_codes": {
                "type": "array",
                "items": {"type": "string"},
                "description": "可选的指标编码列表；提供后不再按名称解析。",
            },
            "start": {
                "type": "string",
                "description": "起始日期，支持 YYYY-MM 或 YYYY-MM-DD。",
            },
            "end": {
                "type": "string",
                "description": "结束日期（含），支持 YYYY-MM 或 YYYY-MM-DD。",
            },
            "monthly": {
                "type": "boolean",
                "description": "是否按自然月拆分返回；默认 false。",
            },
            "periods": {
                "type": "array",
                "description": "显式周期列表；元素为 {label,start,end}。提供后优先于 monthly。",
                "items": {"type": "object"},
            },
            "time_dimension": {
                "type": "string",
                "description": "时间维度编码，默认 D001。",
            },
            "dimensions": {
                "type": "array",
                "items": {"type": "string"},
                "description": "维度编码列表；配合 breakdown_period 做一次下钻。",
            },
            "breakdown_period": {
                "type": "object",
                "description": "维度下钻周期，例如 {start: 2026-02-01, end: 2026-02-28}。",
            },
            "management_unit": {
                "type": "string",
                "description": "管理单元编码；自动添加 unitCode 过滤条件。",
            },
            "approved_only": {
                "type": "boolean",
                "description": "是否只统计已审批采购订单；默认 false。",
            },
            "filters": {
                "type": "array",
                "items": {"type": "object"},
                "description": (
                    "额外过滤条件，元素示例："
                    "{identifierCode: AT0000190, operator: EQ, value: 2800, type: STRING}。"
                ),
            },
            "page_size": {
                "type": "integer",
                "minimum": 1,
                "maximum": 500,
                "default": 100,
            },
        },
        "anyOf": [{"required": ["metric"]}, {"required": ["metric_codes"]}],
    },
}


class MetricFactError(RuntimeError):
    """A deterministic, user-readable MetricFactQuery failure."""


def _parse_date(value: str, *, end: bool = False) -> date:
    text = str(value or "").strip()
    if not text:
        raise ValueError("empty date")
    if re.fullmatch(r"\d{4}-\d{2}", text):
        year, month = (int(part) for part in text.split("-"))
        day = calendar.monthrange(year, month)[1] if end else 1
        return date(year, month, day)
    return datetime.strptime(text, "%Y-%m-%d").date()


def _iso(value: date) -> str:
    return value.isoformat()


def _month_periods(start: date, end: date) -> list[dict[str, str]]:
    if start > end:
        raise ValueError("start must be before end")
    result: list[dict[str, str]] = []
    cursor = start
    while cursor <= end:
        last_day = calendar.monthrange(cursor.year, cursor.month)[1]
        month_end = date(cursor.year, cursor.month, last_day)
        result.append({
            "label": f"{cursor.year:04d}-{cursor.month:02d}",
            "start": _iso(cursor),
            "end": _iso(min(month_end, end)),
        })
        cursor = month_end + timedelta(days=1)
    return result


def _condition(item: dict[str, Any]) -> dict[str, Any]:
    identifier = str(
        item.get("identifierCode") or item.get("code") or item.get("property") or ""
    ).strip()
    if not identifier:
        raise ValueError("filter condition is missing identifierCode/code")
    operator = item.get("operator")
    if isinstance(operator, str):
        operator = {"code": operator, "type": item.get("type") or "STRING"}
    elif not isinstance(operator, dict):
        operator = {"code": "EQ", "type": item.get("type") or "STRING"}
    else:
        operator = dict(operator)
        operator.setdefault("code", "EQ")
        operator.setdefault("type", item.get("type") or "STRING")
    return {
        "identifierCode": identifier,
        "operator": {
            "code": str(operator.get("code") or "EQ").upper(),
            "type": str(operator.get("type") or "STRING").upper(),
        },
        "value": item.get("value"),
        "valueType": str(item.get("valueType") or "ABSOLUTE").upper(),
    }


def _normalise_filter_tree(raw: Any) -> dict[str, Any] | None:
    if raw is None:
        return None
    if isinstance(raw, list):
        children = [_normalise_condition_or_tree(item) for item in raw]
        children = [item for item in children if item]
        return {"logic": "AND", "children": children} if children else None
    if not isinstance(raw, dict):
        raise ValueError("filters must be an object or array")
    if raw.get("children") is not None:
        children = [_normalise_condition_or_tree(item) for item in raw.get("children") or []]
        children = [item for item in children if item]
        if not children:
            return None
        return {"logic": str(raw.get("logic") or "AND").upper(), "children": children}
    return _condition(raw)


def _normalise_condition_or_tree(raw: Any) -> dict[str, Any] | None:
    if not isinstance(raw, dict):
        raise ValueError("filter item must be an object")
    if raw.get("children") is not None:
        return _normalise_filter_tree(raw)
    return _condition(raw)


def _date_condition(time_dimension: str, start: str, end: str) -> dict[str, Any]:
    return {
        "identifierCode": time_dimension,
        "operator": {"code": "BETWEEN", "type": "DATE"},
        "value": [start, end],
        "valueType": "ABSOLUTE",
    }


def _build_filters(params: dict[str, Any], *, start: str = "", end: str = "") -> dict[str, Any] | None:
    children: list[dict[str, Any]] = []
    if params.get("management_unit"):
        children.append({
            "identifierCode": DEFAULT_MANAGEMENT_UNIT_ATTRIBUTE,
            "operator": {"code": "EQ", "type": "STRING"},
            "value": str(params["management_unit"]).strip(),
            "valueType": "ABSOLUTE",
        })
    if params.get("approved_only"):
        children.append({
            "identifierCode": DEFAULT_APPROVAL_ATTRIBUTE,
            "operator": {"code": "EQ", "type": "STRING"},
            "value": DEFAULT_APPROVAL_VALUE,
            "valueType": "ABSOLUTE",
        })
    extra = _normalise_filter_tree(params.get("filters"))
    if extra:
        if extra.get("children") is not None:
            children.extend(extra["children"])
        else:
            children.append(extra)
    if start and end:
        children.append(_date_condition(
            str(params.get("time_dimension") or DEFAULT_TIME_DIMENSION), start, end
        ))
    if not children:
        return None
    return {"logic": "AND", "children": children}


def _extract_json(text: str) -> dict[str, Any]:
    original = str(text or "").strip()
    if not original:
        raise MetricFactError("metric query returned an empty response")
    marker = "[RESULT_METADATA]"
    if marker in original:
        candidate = original.split(marker, 1)[1].strip()
    else:
        first_line = next((line.strip() for line in original.splitlines() if line.strip()), "")
        if (
            re.match(r"^(?:Ontology-MetricQuery|MetricFactQuery)\b", first_line)
            and not original.startswith("{")
        ):
            raise MetricFactError(first_line[:500])
        start = original.find("{")
        if start < 0:
            raise MetricFactError(first_line[:500] or "metric query returned no JSON")
        candidate = original[start:]
    try:
        value = json.loads(candidate)
    except json.JSONDecodeError as exc:
        first_line = next((line.strip() for line in original.splitlines() if line.strip()), "")
        raise MetricFactError(first_line[:500] or f"invalid metric JSON: {exc}") from exc
    if not isinstance(value, dict):
        raise MetricFactError("metric query result is not a JSON object")
    return value


def _metric_candidates(text: str) -> list[tuple[str, str]]:
    seen: set[str] = set()
    result: list[tuple[str, str]] = []
    for match in METRIC_LINE_RE.finditer(text or ""):
        code = match.group("code")
        if code in seen:
            continue
        seen.add(code)
        result.append((code, match.group("name").strip()))
    return result


def _metric_code_from_semantic(text: str, requested: str) -> str:
    lowered = str(text or "").lower()
    if "remote error" in lowered or "timed out" in lowered or "http 5" in lowered:
        first_line = next((line.strip() for line in str(text).splitlines() if line.strip()), "")
        raise MetricFactError(first_line[:500] or "semantic metric lookup failed")
    candidates = _metric_candidates(text)
    if not candidates:
        raise MetricFactError(
            f"metric name {requested!r} could not be resolved to an Indicator code"
        )
    exact = [code for code, name in candidates if name == requested]
    if len(exact) == 1:
        return exact[0]
    if len(candidates) == 1:
        return candidates[0][0]
    options = ", ".join(f"{code}={name}" for code, name in candidates)
    raise MetricFactError(
        f"metric name {requested!r} is ambiguous ({options}); pass metric_codes explicitly"
    )


def _numeric(value: Any) -> Decimal:
    if isinstance(value, dict):
        value = value.get("value")
    if isinstance(value, (int, float)):
        return Decimal(str(value))
    try:
        return Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError) as exc:
        raise ValueError(f"non-numeric metric value: {value!r}") from exc


def _scalar_from_rows(rows: list[dict[str, Any]], code: str) -> Decimal | None:
    if not rows:
        return None
    value = rows[0].get(code)
    if value is None:
        return None
    return _numeric(value)


def _metric_values_from_rows(
    rows: list[dict[str, Any]], metric_codes: list[str]
) -> dict[str, Decimal | None]:
    if not rows:
        return {code: None for code in metric_codes}
    result: dict[str, Decimal | None] = {}
    for code in metric_codes:
        value = rows[0].get(code)
        if value is None:
            result[code] = None
            continue
        try:
            result[code] = _numeric(value)
        except ValueError:
            result[code] = None
    return result


def _decimal_to_float(value: Decimal | None) -> float | None:
    return float(value) if value is not None else None


def _periods_cover_range(
    periods: list[dict[str, str]], range_start: str, range_end: str
) -> bool:
    if not periods or not range_start or not range_end:
        return False
    cursor = date.fromisoformat(range_start)
    final = date.fromisoformat(range_end)
    if cursor > final:
        return False
    for period in sorted(periods, key=lambda item: item["start"]):
        period_start = date.fromisoformat(period["start"])
        period_end = date.fromisoformat(period["end"])
        if period_end < cursor:
            continue
        if period_start > cursor:
            return False
        cursor = max(cursor, period_end + timedelta(days=1))
        if cursor > final:
            return True
    return False


def _normalized_envelope(payload: dict[str, Any]) -> dict[str, Any]:
    data = payload.get("data") if isinstance(payload, dict) else None
    if not isinstance(data, dict):
        raise ValueError("metric query response is missing data")
    return {
        "data": data,
        "scope": payload.get("scope") or {},
        "semantic": payload.get("semantic") or {},
        "provenance": payload.get("provenance") or {},
    }


def make_executor(
    metric_query: Executor,
    semantic_query: Executor | None = None,
) -> Executor:
    cache: OrderedDict[str, tuple[float, dict[str, Any]]] = OrderedDict()
    cache_lock = threading.Lock()

    def run(params: dict[str, Any], cwd: str) -> str:
        try:
            return _run(params, cwd)
        except MetricFactError as exc:
            return f"MetricFactQuery error: {exc}"
        except (TypeError, ValueError) as exc:
            return f"MetricFactQuery error: {exc}"
        except Exception as exc:  # noqa: BLE001
            return f"MetricFactQuery error: {type(exc).__name__}: {exc}"

    def _run(params: dict[str, Any], cwd: str) -> str:
        started = time.monotonic()
        raw_codes = params.get("metric_codes") or []
        if not isinstance(raw_codes, list):
            raise MetricFactError("metric_codes must be an array")
        metric_codes = list(dict.fromkeys(
            str(code).strip() for code in raw_codes if str(code).strip()
        ))
        metric_name = str(params.get("metric") or "").strip()
        if not metric_codes:
            if not metric_name:
                raise MetricFactError("metric or metric_codes is required")
            if METRIC_CODE_RE.fullmatch(metric_name):
                metric_codes = [metric_name]
            elif semantic_query is not None:
                resolved = semantic_query({"query": metric_name, "limit": 20}, cwd)
                metric_codes = [_metric_code_from_semantic(str(resolved), metric_name)]
            else:
                raise MetricFactError(
                    "metric name cannot be resolved without Ontology-SemanticQuery"
                )

        start_raw = str(params.get("start") or "").strip()
        end_raw = str(params.get("end") or "").strip()
        if bool(start_raw) != bool(end_raw):
            raise MetricFactError("start and end must be provided together")
        start = _parse_date(start_raw) if start_raw else None
        end = _parse_date(end_raw, end=True) if end_raw else None
        explicit_periods = params.get("periods") or []
        if not isinstance(explicit_periods, list):
            raise MetricFactError("periods must be an array")
        if not explicit_periods and (start is None or end is None):
            raise MetricFactError(
                "a bounded time range is required: provide start/end or periods"
            )
        periods: list[dict[str, str]] = []
        if explicit_periods:
            for item in explicit_periods:
                if not isinstance(item, dict):
                    raise MetricFactError("each period must be an object")
                period_start = _parse_date(str(item.get("start") or ""))
                period_end = _parse_date(str(item.get("end") or ""), end=True)
                if period_start > period_end:
                    raise MetricFactError("period start must be before period end")
                periods.append({
                    "label": str(item.get("label") or period_start.strftime("%Y-%m")),
                    "start": _iso(period_start),
                    "end": _iso(period_end),
                })
        elif params.get("monthly") and start and end:
            periods = _month_periods(start, end)

        try:
            page_size = max(1, min(int(params.get("page_size") or 100), 500))
        except (TypeError, ValueError) as exc:
            raise MetricFactError("page_size must be an integer") from exc
        raw_dimensions = params.get("dimensions") or []
        if not isinstance(raw_dimensions, list):
            raise MetricFactError("dimensions must be an array")
        dimensions = list(dict.fromkeys(
            str(item).strip() for item in raw_dimensions if str(item).strip()
        ))
        period_results: list[dict[str, Any]] = []
        queries = 0
        cache_hits = 0
        first_payload: dict[str, Any] | None = None
        try:
            cache_ttl = max(
                0.0, float(os.environ.get("ONTOLOGY_METRIC_FACT_CACHE_TTL", "30"))
            )
        except ValueError:
            cache_ttl = 30.0
        try:
            cache_limit = max(
                1, int(os.environ.get("ONTOLOGY_METRIC_FACT_CACHE_SIZE", "128"))
            )
        except ValueError:
            cache_limit = 128
        def query_once(range_start: str, range_end: str, query_dimensions: list[str]) -> dict[str, Any]:
            nonlocal queries, cache_hits, first_payload
            request: dict[str, Any] = {
                "metric_codes": metric_codes,
                "dimensions": query_dimensions,
                "page_size": page_size,
            }
            filters = _build_filters(params, start=range_start, end=range_end)
            if filters:
                request["filters"] = filters
            cache_key = json.dumps(request, ensure_ascii=False, sort_keys=True, default=str)
            now = time.monotonic()
            if cache_ttl:
                with cache_lock:
                    expired = [
                        key for key, (expires_at, _) in cache.items()
                        if expires_at <= now
                    ]
                    for key in expired:
                        cache.pop(key, None)
                    cached = cache.get(cache_key)
                    if cached is not None:
                        cache.move_to_end(cache_key)
                        cache_hits += 1
                        payload = cached[1]
                        if first_payload is None:
                            first_payload = payload
                        return payload
            text = metric_query(request, cwd)
            if not isinstance(text, str):
                text = json.dumps(text, ensure_ascii=False)
            payload = _extract_json(text)
            queries += 1
            if first_payload is None:
                first_payload = payload
            if cache_ttl:
                with cache_lock:
                    cache[cache_key] = (time.monotonic() + cache_ttl, payload)
                    cache.move_to_end(cache_key)
                    while len(cache) > cache_limit:
                        cache.popitem(last=False)
            return payload

        if periods:
            for period in periods:
                payload = query_once(period["start"], period["end"], [])
                rows = ((payload.get("data") or {}).get("result") or {}).get("rows") or []
                values = _metric_values_from_rows(rows, metric_codes)
                period_results.append({
                    "period": period["label"],
                    "start": period["start"],
                    "end": period["end"],
                    "value": _decimal_to_float(values.get(metric_codes[0])),
                    "values": {
                        code: _decimal_to_float(value) for code, value in values.items()
                    },
                })
            if start and end:
                range_start, range_end = _iso(start), _iso(end)
            else:
                range_start, range_end = periods[0]["start"], periods[-1]["end"]
            totals = {
                code: sum(
                    (
                        _numeric(item["values"][code])
                        for item in period_results
                        if item["values"].get(code) is not None
                    ),
                    Decimal("0"),
                )
                for code in metric_codes
            }
            total_values = {
                code: _decimal_to_float(value) for code, value in totals.items()
            }
        else:
            range_start = _iso(start) if start else ""
            range_end = _iso(end) if end else ""
            payload = query_once(range_start, range_end, [])
            rows = ((payload.get("data") or {}).get("result") or {}).get("rows") or []
            values = _metric_values_from_rows(rows, metric_codes)
            total_values = {
                code: _decimal_to_float(value) for code, value in values.items()
            }

        # If explicit periods do not cover the requested range, fetch the true
        # range total instead of silently presenting a partial sum as the total.
        if periods and start and end and not _periods_cover_range(
            periods, _iso(start), _iso(end)
        ):
            payload = query_once(_iso(start), _iso(end), [])
            rows = ((payload.get("data") or {}).get("result") or {}).get("rows") or []
            values = _metric_values_from_rows(rows, metric_codes)
            total_values = {
                code: _decimal_to_float(value) for code, value in values.items()
            }
        total_value = total_values.get(metric_codes[0])

        breakdown: dict[str, Any] = {}
        breakdown_meta: dict[str, Any] = {}
        breakdown_period = params.get("breakdown_period") or {}
        if dimensions:
            if breakdown_period:
                if not isinstance(breakdown_period, dict):
                    raise MetricFactError("breakdown_period must be an object")
                b_start = _iso(_parse_date(str(breakdown_period.get("start") or "")))
                b_end = _iso(_parse_date(str(breakdown_period.get("end") or ""), end=True))
            else:
                b_start, b_end = range_start, range_end
            parent_total: Decimal | None = None
            if b_start == range_start and b_end == range_end and total_value is not None:
                parent_total = _numeric(total_value)
            else:
                for item in period_results:
                    if item["start"] == b_start and item["end"] == b_end:
                        if item["values"].get(metric_codes[0]) is not None:
                            parent_total = _numeric(item["values"][metric_codes[0]])
                        break
            for dimension in dimensions:
                payload = query_once(b_start, b_end, [dimension])
                rows = ((payload.get("data") or {}).get("result") or {}).get("rows") or []
                breakdown[dimension] = rows
                dimension_names = (payload.get("scope") or {}).get("dimension_names") or {}
                metric_sum = sum(
                    (
                        _numeric(row[metric_codes[0]])
                        for row in rows
                        if row.get(metric_codes[0]) is not None
                    ),
                    Decimal("0"),
                )
                reconciles = None
                if parent_total is not None:
                    difference = abs(parent_total - metric_sum)
                    reconciles = difference <= max(Decimal("1e-9"), abs(parent_total) * Decimal("1e-9"))
                breakdown_meta[dimension] = {
                    "dimension_name": dimension_names.get(dimension, dimension),
                    "period": {"start": b_start, "end": b_end},
                    "total": _decimal_to_float(metric_sum),
                    "parent_total": _decimal_to_float(parent_total),
                    "reconciles": reconciles,
                }

        filters = _build_filters(params, start=range_start, end=range_end) or {}
        envelope = _normalized_envelope(first_payload or {})
        data = envelope.get("data") or {}
        result = data.get("result") if isinstance(data, dict) else {}
        if not isinstance(result, dict):
            result = {}
        if periods:
            columns = [
                {"identifierCode": "period", "label": "周期", "type": "DIMENSION"},
                *[{"identifierCode": code, "label": code, "type": "METRIC"} for code in metric_codes],
            ]
            rows = [
                {
                    "period": item["period"],
                    **{
                        code: {"value": item["values"].get(code)}
                        for code in metric_codes
                    },
                }
                for item in period_results
            ]
            result = {"columns": columns, "rows": rows}
            data = {"resultType": "TABLE", "result": result, "pagination": {"pageNum": 1, "pageSize": len(rows), "total": len(rows)}}
            envelope["data"] = data
        scope = dict(envelope.get("scope") or {})
        scope.update({
            "metric_codes": metric_codes,
            "dimensions": dimensions if dimensions else [],
            "filters": filters,
            "time_range": {"start": range_start, "end": range_end} if range_start or range_end else {},
            "drilldowns": breakdown_meta,
        })
        envelope["scope"] = scope

        answer = {
            "tool": "MetricFactQuery",
            "metric_codes": metric_codes,
            "time_range": {"start": range_start, "end": range_end} if range_start or range_end else {},
            "filters": filters,
            "total": total_value,
            "totals": total_values,
            "periods": period_results,
            "breakdown": breakdown,
            "breakdown_meta": breakdown_meta,
            "queries": queries,
            "cache_hits": cache_hits,
            "elapsed_ms": round((time.monotonic() - started) * 1000, 1),
            "source": "analysis/data/query",
        }
        return (
            "# MetricFactQuery\n\n"
            + json.dumps(answer, ensure_ascii=False, indent=2)
            + "\n\n[RESULT_METADATA]\n"
            + json.dumps(envelope, ensure_ascii=False)
        )

    return run
