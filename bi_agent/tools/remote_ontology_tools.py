"""Agent tools backed by the production ontology and MAL HTTP APIs."""

from __future__ import annotations

import json
import re
import time
from typing import Any, Callable, Iterable

from ..ontology.remote import OntologyApiError, RemoteOntologyClient
from .graph_tools import GRAPH_CONTEXT_SCHEMA, GRAPH_EXPAND_SCHEMA
from .ontology_tools import (
    ENTITY_DESCRIBE_SCHEMA,
    LIST_BUSINESS_OBJECTS_SCHEMA,
    METRIC_LOOKUP_SCHEMA,
    ONTOLOGY_QUERY_SCHEMA,
    RELATION_LOOKUP_SCHEMA,
    TERM_DISAMBIGUATE_SCHEMA,
)

Executor = Callable[[dict[str, Any], str], str]

_CANDIDATE_TYPES = [
    "BusinessObject", "LogicalEntity", "BusinessAttribute", "Term",
    "Dimension", "Indicator", "Rule", "TableNode", "Column",
]

METRIC_DATA_QUERY_SCHEMA: dict[str, Any] = {
    "name": "MetricDataQuery",
    "description": (
        "通过远程 analysis/data/query 按本体指标和维度进行聚合计算。"
        "远程模式下应优先于手写 SQL；只有接口不支持或失败时才回退 SQLRun。"
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "metric_codes": {
                "type": "array", "items": {"type": "string"},
                "description": "指标编码列表，例如 ['M0001']。",
            },
            "dimensions": {
                "type": "array", "items": {"type": "string"},
                "description": "维度编码列表；标量查询可为空。",
            },
            "filters": {
                "type": "object",
                "description": "MAL commonConfig.filters 过滤树。",
            },
            "sorts": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "identifierCode": {"type": "string"},
                        "order": {"type": "string", "enum": ["ASC", "DESC"]},
                    },
                    "required": ["identifierCode", "order"],
                },
            },
            "page_num": {"type": "integer", "minimum": 1, "default": 1},
            "page_size": {"type": "integer", "minimum": 1, "maximum": 500, "default": 100},
        },
        "required": ["metric_codes"],
    },
}


def _scalar(value: Any) -> Any:
    """Collapse wrapper/list values emitted by different ArcadeDB adapters."""
    if isinstance(value, list) and len(value) == 1:
        return _scalar(value[0])
    if isinstance(value, dict) and set(value) == {"value"}:
        return _scalar(value["value"])
    return value


def _ci_get(props: dict[str, Any], *names: str, default: Any = "") -> Any:
    values = {str(k).lower(): _scalar(v) for k, v in props.items()}
    for name in names:
        value = values.get(name.lower())
        if value not in (None, "", []):
            return value
    return default


def _text(value: Any) -> str:
    value = _scalar(value)
    if isinstance(value, (dict, list)):
        return json.dumps(value, ensure_ascii=False, sort_keys=True)
    return str(value or "").strip()


def _props(data: dict[str, Any]) -> dict[str, Any]:
    obj = data.get("objectInfo") or data.get("object") or {}
    return obj.get("properties") or {}


def _format_object(type_name: str, props: dict[str, Any]) -> str:
    code = _text(_ci_get(props, "code", "identifierCode", default="?"))
    label = _text(_ci_get(props, "label", "name", default=code))
    lines = [f"[{code}] {label} ({type_name})"]
    emitted: set[str] = {code, label}
    for key in ("name", "description", "alias", "physicalTable", "tableName", "columnName"):
        value = _text(_ci_get(props, key))
        if value and value not in emitted:
            lines.append(f"  {key}: {value}")
            emitted.add(value)
    return "\n".join(lines)


def _aliases(props: dict[str, Any]) -> list[str]:
    raw = _ci_get(props, "alias", "aliases")
    if isinstance(raw, list):
        return [_text(item) for item in raw if _text(item)]
    return [item.strip() for item in re.split(r"[,，;；|]", _text(raw)) if item.strip()]


def _rank_row(props: dict[str, Any], query: str) -> tuple[int, str, str]:
    """Canonical lookup order: code, label, name, alias, then fuzzy."""
    needle = query.casefold().strip()
    code = _text(_ci_get(props, "code", "identifierCode"))
    label = _text(_ci_get(props, "label"))
    name = _text(_ci_get(props, "name"))
    aliases = _aliases(props)
    if code.casefold() == needle:
        rank = 0
    elif label.casefold() == needle:
        rank = 1
    elif name.casefold() == needle:
        rank = 2
    elif needle in {item.casefold() for item in aliases}:
        rank = 3
    elif any(needle in value.casefold() for value in [code, label, name, *aliases, _text(_ci_get(props, "description"))]):
        rank = 4
    else:
        rank = 99
    return rank, code.casefold(), label.casefold()


def _search_type(client: RemoteOntologyClient, type_name: str, query: str, limit: int = 20) -> list[dict[str, Any]]:
    rows = client.list_objects(type_name)
    ranked = sorted(((_rank_row(row, query), row) for row in rows), key=lambda pair: pair[0])
    eligible = [(rank, row) for rank, row in ranked if rank[0] < 99]
    if not eligible:
        return []
    best_tier = eligible[0][0][0]
    # Priority means short-circuiting: a code exact hit must not be padded
    # with weaker label/name/alias/fuzzy candidates.
    return [row for rank, row in eligible if rank[0] == best_tier][:limit]


def _candidate_results(client: RemoteOntologyClient, query: str) -> list[tuple[str, dict[str, Any]]]:
    found: list[tuple[str, dict[str, Any]]] = []
    for type_name in _CANDIDATE_TYPES:
        try:
            rows = _search_type(client, type_name, query, limit=10)
        except OntologyApiError:
            continue
        found.extend((type_name, row) for row in rows)
    found.sort(key=lambda pair: _rank_row(pair[1], query))
    return found


def _code_type(value: str) -> str:
    code = value.upper()
    if code.startswith("BO"):
        return "BusinessObject"
    if code.startswith("LE"):
        return "LogicalEntity"
    if code.startswith("AT"):
        return "BusinessAttribute"
    if code.startswith("M"):
        return "Indicator"
    if code.startswith("D"):
        return "Dimension"
    if code.startswith("R"):
        return "Rule"
    if code.startswith("T"):
        return "Term"
    return "BusinessObject"


def _related_objects(data: dict[str, Any]) -> list[dict[str, Any]]:
    objects = data.get("objects") or data.get("relatedObjects") or []
    return [item for item in objects if isinstance(item, dict)]


def _related_text(data: dict[str, Any], title: str = "关联本体") -> str:
    objects = _related_objects(data)
    lines = [f"# {title} ({len(objects)})"]
    for item in objects:
        obj_type = str(item.get("typeName") or item.get("type") or "Unknown")
        lines.append(_format_object(obj_type, item.get("properties") or item))
    return "\n\n".join(lines) if objects else f"{title}: no related objects."


def _walk_rows(value: Any) -> Iterable[dict[str, Any]]:
    """Yield row-like maps from TABLE/TREE/GRAPH MAL response variants."""
    if isinstance(value, dict):
        rows = value.get("rows")
        if isinstance(rows, list):
            for row in rows:
                if isinstance(row, dict):
                    yield row
        for key, child in value.items():
            if key != "rows" and isinstance(child, (dict, list)):
                yield from _walk_rows(child)
    elif isinstance(value, list):
        for child in value:
            yield from _walk_rows(child)


def _dimension_rows_from_meta(data: dict[str, Any]) -> list[dict[str, Any]]:
    dimensions: list[dict[str, Any]] = []
    seen: set[str] = set()
    for row in _walk_rows(data):
        candidates: list[dict[str, Any]] = [row]
        nested = row.get("IndicatorIsDrilledByDimension")
        if isinstance(nested, list):
            candidates.extend(item for item in nested if isinstance(item, dict))
        for item in candidates:
            code = _text(_ci_get(item, "code", "identifierCode"))
            if code and code.upper().startswith("D") and code not in seen:
                seen.add(code)
                dimensions.append(item)
    return dimensions


def _metric_dimensions(client: RemoteOntologyClient, code: str) -> tuple[list[dict[str, Any]], str]:
    now = time.monotonic()
    cache = getattr(client, "_metric_dimension_cache", {})
    cached = cache.get(code)
    ttl = float(getattr(client, "cache_ttl", 30.0))
    if cached and now - cached[0] <= ttl:
        return cached[1], cached[2]

    def remember(rows: list[dict[str, Any]], source: str) -> tuple[list[dict[str, Any]], str]:
        cache[code] = (now, rows, source)
        client._metric_dimension_cache = cache
        return rows, source

    common = {
        "filters": {"logic": "AND", "children": [
            {"type": "Indicator", "property": "code", "operator": {"code": "EQ", "type": "STRING"}, "value": code},
            {"type": "IndicatorIsDrilledByDimension", "sourceType": "Indicator", "targetType": "Dimension"},
        ]},
        "pagination": {"pageNum": 1, "pageSize": 200},
    }
    meta_error = ""
    meta_rows: list[dict[str, Any]] = []
    # Repository metadata models do not all declare the same Dimension
    # properties. Try the canonical dialect first, then the label/name dialect
    # used by repository 4. Repository 3 rejects every declared Dimension
    # property and therefore intentionally falls through to findRelated.
    dialect_cache = getattr(client, "_dimension_meta_dialect", None)
    known_dialect = (
        dialect_cache.get("value")
        if isinstance(dialect_cache, dict) and now - dialect_cache.get("at", 0) <= ttl
        else None
    )
    property_sets = (
        [] if known_dialect is False
        else [known_dialect] if isinstance(known_dialect, tuple)
        else [("code", "label"), ("label", "name")]
    )
    for property_names in property_sets:
        analysis = {
            "vertex": [{
                "type": "Dimension", "label": "维度",
                "properties": [{"name": name, "label": name} for name in property_names],
            }],
        }
        try:
            meta_data = client.metadata_query(analysis, common)
            client._dimension_meta_dialect = {"value": tuple(property_names), "at": now}
            rows = _dimension_rows_from_meta(meta_data)
            if rows:
                return remember(rows, "analysis/meta/query")
            meta_rows = [
                row for row in _walk_rows(meta_data)
                if _text(_ci_get(row, "code", "identifierCode", "label", "name"))
            ]
            if meta_rows:
                break
            # The metadata query succeeded and returned no associated
            # dimensions. Do not call the broader graph endpoint needlessly.
            return remember([], "analysis/meta/query")
        except OntologyApiError as exc:
            meta_error = str(exc)
    if property_sets and not meta_rows and meta_error:
        client._dimension_meta_dialect = {"value": False, "at": now}

    # Repository 3 currently has a server-side Indicator property-model
    # mismatch. Keep remote feature parity through the documented neighborhood
    # API while making the primary MAL path active for healthy repositories.
    related = client.find_related("Indicator", code, depth=2)
    rows = []
    seen: set[str] = set()
    for item in _related_objects(related):
        if str(item.get("typeName") or item.get("type") or "").lower() != "dimension":
            continue
        props = item.get("properties") or item
        dim_code = _text(_ci_get(props, "code", "identifierCode"))
        if dim_code and dim_code not in seen:
            seen.add(dim_code)
            rows.append(props)
    source = "analysis/meta/query + findRelated enrichment" if meta_rows else "findRelated fallback"
    if meta_error and not meta_rows:
        source += " (analysis/meta/query unavailable for this repository)"
    return remember(rows, source)


def _metric_adapter(props: dict[str, Any]) -> dict[str, Any]:
    """Normalize all three observed remote Indicator property dialects."""
    return {
        "code": _text(_ci_get(props, "code", "identifierCode")),
        "label": _text(_ci_get(props, "label")),
        "name": _text(_ci_get(props, "name")),
        "aliases": _aliases(props),
        "definition": _text(_ci_get(props, "description", "definition")),
        "formula": _text(_ci_get(props, "businessFormula", "bizFormula", "formulaBusiness", "formula")),
        "caliber": _text(_ci_get(props, "statisticalCaliber", "statCaliber", "scope", "statisticalScope")),
        "calculation_rule": _text(_ci_get(props, "attributeCalculationRule", "calculationRule", "formulaTechnical", "technicalFormula", "filterCondition")),
        "source_tables": _text(_ci_get(props, "sourceTables", "physicalTable", "tableName", "sourceTable")),
        "aggregate_columns": _text(_ci_get(props, "aggregateColumns", "aggregateColumn", "aggColumn")),
        "aggregate_type": _text(_ci_get(props, "aggregateType", "aggType", "aggregationType")),
        "indicator_type": _text(_ci_get(props, "indicatorType", "metricType")),
        "stat_period": _text(_ci_get(props, "statPeriod", "statisticalPeriod")),
    }


def _format_metric(metric: dict[str, Any], dimensions: list[dict[str, Any]], dimension_source: str) -> str:
    label = metric["label"] or metric["name"] or metric["code"]
    lines = [f"[{metric['code'] or '?'}] {label} (Indicator)"]
    fields = [
        ("英文名", metric["name"]), ("别名", "、".join(metric["aliases"])),
        ("定义", metric["definition"]), ("业务公式", metric["formula"]),
        ("统计口径", metric["caliber"]), ("计算规则", metric["calculation_rule"]),
        ("来源表", metric["source_tables"]), ("聚合字段", metric["aggregate_columns"]),
        ("聚合方式", metric["aggregate_type"]), ("指标类型", metric["indicator_type"]),
        ("统计周期", metric["stat_period"]),
    ]
    lines.extend(f"  {label_name}: {value or '未配置'}" for label_name, value in fields)
    lines.append(f"  适用维度 ({dimension_source}):")
    if not dimensions:
        lines.append("    - 未配置")
    for row in dimensions:
        code = _text(_ci_get(row, "code", "identifierCode", default="?"))
        name = _text(_ci_get(row, "label", "name", default=code))
        dim_type = _text(_ci_get(row, "type"))
        value = _text(_ci_get(row, "value"))
        suffix = " / ".join(part for part in (dim_type, value) if part)
        lines.append(f"    - [{code}] {name}" + (f" ({suffix})" if suffix else ""))
    return "\n".join(lines)


def _make_query(client: RemoteOntologyClient) -> Executor:
    def run(params: dict[str, Any], cwd: str) -> str:
        query = str(params.get("query") or "").strip()
        if not query:
            return "OntologyQuery: empty query."
        try:
            matches = _candidate_results(client, query)
            if not matches:
                return f"OntologyQuery: no remote matches for {query!r}."
            limit = max(1, min(int(params.get("limit") or 10), 100))
            return "# Remote OntologyQuery\n\n" + "\n\n".join(
                _format_object(kind, props) for kind, props in matches[:limit]
            )
        except OntologyApiError as exc:
            return f"OntologyQuery remote error: {exc}"
    return run


def _make_term(client: RemoteOntologyClient) -> Executor:
    def run(params: dict[str, Any], cwd: str) -> str:
        term = str(params.get("term") or "").strip()
        if not term:
            return "TermDisambiguate: empty term."
        try:
            rows = _search_type(client, "Term", term, limit=20)
            return "\n\n".join(_format_object("Term", row) for row in rows) or f"No term matches {term!r}."
        except OntologyApiError as exc:
            return f"TermDisambiguate remote error: {exc}"
    return run


def _make_metric(client: RemoteOntologyClient) -> Executor:
    def run(params: dict[str, Any], cwd: str) -> str:
        query = str(params.get("metric") or "").strip()
        if not query:
            return "MetricLookup: empty metric."
        try:
            # Indicator-only by design. Do not let unrelated object types win
            # simply because they share the same label or code fragment.
            rows = _search_type(client, "Indicator", query, limit=20)
            if not rows:
                return f"No metric matches {query!r}."
            rendered: list[str] = []
            for row in rows:
                metric = _metric_adapter(row)
                dimensions, source = _metric_dimensions(client, metric["code"])
                rendered.append(_format_metric(metric, dimensions, source))
            return "\n\n".join(rendered)
        except OntologyApiError as exc:
            return f"MetricLookup remote error: {exc}"
    return run


def _make_related(client: RemoteOntologyClient) -> Executor:
    def run(params: dict[str, Any], cwd: str) -> str:
        entity = str(params.get("entity") or "").strip()
        if not entity:
            return "RelationLookup: empty entity."
        try:
            return _related_text(client.find_related(_code_type(entity), entity, depth=2), f"Remote relations for {entity}")
        except OntologyApiError as exc:
            return f"RelationLookup remote error: {exc}"
    return run


def _make_describe(client: RemoteOntologyClient) -> Executor:
    def run(params: dict[str, Any], cwd: str) -> str:
        entity = str(params.get("entity") or "").strip()
        if not entity:
            return "EntityDescribe: empty entity."
        try:
            matches = _candidate_results(client, entity)
            if not matches:
                return f"EntityDescribe: no remote match for {entity!r}."
            kind, props = matches[0]
            code = _text(_ci_get(props, "code", "identifierCode", default=entity))
            related = client.find_related(kind, code, depth=1)
            return _format_object(kind, props) + "\n\n" + _related_text(related, "Attributes and relations")
        except OntologyApiError as exc:
            return f"EntityDescribe remote error: {exc}"
    return run


def _make_list_bos(client: RemoteOntologyClient) -> Executor:
    def run(params: dict[str, Any], cwd: str) -> str:
        try:
            limit = max(1, min(int(params.get("limit") or 100), 500))
            rows = client.list_objects("BusinessObject", limit)
            if not rows:
                return "ListBusinessObjects: remote ontology is empty."
            return "# Remote BusinessObjects\n" + "\n".join(
                _format_object("BusinessObject", row).splitlines()[0] for row in rows
            )
        except OntologyApiError as exc:
            return f"ListBusinessObjects remote error: {exc}"
    return run


def _make_graph_context(client: RemoteOntologyClient) -> Executor:
    def run(params: dict[str, Any], cwd: str) -> str:
        anchor = str(params.get("anchor") or "").strip()
        query = str(params.get("query") or "").strip()
        try:
            if not anchor:
                matches = _candidate_results(client, query)
                if not matches:
                    return f"GraphContext: no remote anchor for {query!r}."
                if len(matches) > 1:
                    return "GraphContext: multiple candidates; specify anchor:\n" + "\n".join(
                        _format_object(kind, props).splitlines()[0] for kind, props in matches
                    )
                type_name, props = matches[0]
                anchor = _text(_ci_get(props, "code", "identifierCode"))
            else:
                type_name = _code_type(anchor)
            return _related_text(client.find_related(type_name, anchor, depth=2), f"Remote GraphContext [{anchor}]")
        except OntologyApiError as exc:
            return f"GraphContext remote error: {exc}"
    return run


def _make_graph_expand(client: RemoteOntologyClient) -> Executor:
    def run(params: dict[str, Any], cwd: str) -> str:
        anchor = str(params.get("anchor") or "").strip()
        if not anchor:
            return "GraphExpand: empty anchor."
        try:
            return _related_text(client.find_related(_code_type(anchor), anchor, depth=3), f"Remote GraphExpand [{anchor}]")
        except OntologyApiError as exc:
            return f"GraphExpand remote error: {exc}"
    return run


def _make_metric_data_query(client: RemoteOntologyClient) -> Executor:
    def run(params: dict[str, Any], cwd: str) -> str:
        raw_codes = params.get("metric_codes") or []
        raw_dimensions = params.get("dimensions") or []
        if not isinstance(raw_codes, list) or not isinstance(raw_dimensions, list):
            return "MetricDataQuery: metric_codes and dimensions must be arrays."
        codes = [str(code).strip() for code in raw_codes if str(code).strip()]
        if not codes:
            return "MetricDataQuery: metric_codes is empty."
        dimensions = [str(code).strip() for code in raw_dimensions if str(code).strip()]
        try:
            page_num = max(1, int(params.get("page_num") or 1))
            page_size = max(1, min(int(params.get("page_size") or 100), 500))
        except (TypeError, ValueError):
            return "MetricDataQuery: page_num and page_size must be integers."
        analysis = {
            "indicators": [{"identifierCode": code, "alias": code} for code in codes],
            "dimensions": [{"identifierCode": code, "alias": code} for code in dimensions],
        }
        common: dict[str, Any] = {
            "pagination": {
                "pageNum": page_num,
                "pageSize": page_size,
            },
        }
        if isinstance(params.get("filters"), dict) and params["filters"]:
            common["filters"] = params["filters"]
        if isinstance(params.get("sorts"), list) and params["sorts"]:
            common["sorts"] = params["sorts"]
        now = time.monotonic()
        ttl = float(getattr(client, "cache_ttl", 30.0))
        cached_failure = getattr(client, "_data_query_failure", None)
        if cached_failure and now - cached_failure[0] <= ttl:
            return (
                "MetricDataQuery remote error (recent endpoint failure): "
                + cached_failure[1]
                + "\n请直接回退 SQLRun，稍后再重试语义查询。"
            )
        try:
            data = client.data_query(analysis, common)
            client._data_query_failure = None
            return "# MetricDataQuery (analysis/data/query)\n\n" + json.dumps(data, ensure_ascii=False, indent=2)
        except OntologyApiError as exc:
            message = str(exc)
            # A repository-wide server failure should not be retried for every
            # drill-down in the same agent turn. Cache it briefly, while leaving
            # 4xx/validation errors metric-specific and immediately retryable.
            if re.search(r"\bHTTP 5\d\d\b", message):
                client._data_query_failure = (now, message)
            return (
                "MetricDataQuery remote error: " + message
                + "\n可在确认指标口径与物理映射后回退 SQLRun。"
            )
    return run


def remote_specs(client: RemoteOntologyClient) -> list[tuple[dict[str, Any], Executor]]:
    """Return complete remote ontology/semantic-query tool bindings."""
    factories = [
        (ONTOLOGY_QUERY_SCHEMA, _make_query),
        (TERM_DISAMBIGUATE_SCHEMA, _make_term),
        (METRIC_LOOKUP_SCHEMA, _make_metric),
        (RELATION_LOOKUP_SCHEMA, _make_related),
        (ENTITY_DESCRIBE_SCHEMA, _make_describe),
        (LIST_BUSINESS_OBJECTS_SCHEMA, _make_list_bos),
        (GRAPH_CONTEXT_SCHEMA, _make_graph_context),
        (GRAPH_EXPAND_SCHEMA, _make_graph_expand),
        (METRIC_DATA_QUERY_SCHEMA, _make_metric_data_query),
    ]
    return [(schema, factory(client)) for schema, factory in factories]
