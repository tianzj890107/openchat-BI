"""Agent tools backed by the production ontology and MAL HTTP APIs."""

from __future__ import annotations

import json
import re
import time
from typing import Any, Callable, Iterable

from ..ontology.remote import OntologyApiError, RemoteOntologyClient
from ..reliability import normalize_query_result, Provenance
from ..ontology.remote_retriever import RemoteGraphRetriever
from ..display_names import pick_display_name, is_valid_name, unique_aliases
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
    "Dimension", "Indicator", "Rule", "Activity", "Process", "EntityRelation",
    "MetaRelation", "TableNode", "Column",
]

METRIC_DATA_QUERY_SCHEMA: dict[str, Any] = {
    "name": "Ontology-MetricQuery",
    "description": (
        "通过远程 analysis/data/query 按本体指标和维度进行聚合计算。"
        "远程模式下应优先于手写 SQL；只有接口不支持或失败时才回退 Ontology-FactQuery。"
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


# ---------------------------------------------------------------------------
# 分页元数据树查询（Spec §4.1 / §4.2）
#
# `API/本体元数据查询API-WIP.md` 把"按名字检索指标/维度"与"逻辑实体关联的业务
# 属性"定义为 `POST /api/v1/analysis/meta/query` 的分页树查询。全量下拉
# （`SELECT FROM <Type> LIMIT n`）一旦超过单次上限就与"对象不存在"无法区分，因此
# 这两条检索必须走树查询；查询本身不可用时才回退到既有兜底，并如实说明。
# ---------------------------------------------------------------------------

#: 文档 `pagination.pageSize` 必须落在 1..500；取上限附近以减少往返。
TREE_PAGE_SIZE = 200
#: 有限翻页：命中即停，翻页次数设硬上限，禁止无界循环。
TREE_MAX_PAGES = 20

TREE_DEGRADE_NOTE = "（元数据树查询不可用，已回退到本地全量检索）"
ATTRIBUTE_DEGRADE_NOTE = "（业务属性查询不可用，已回退到图邻域）"

#: 文档已给出树查询、且数量可能超过单次全量上限的两个检索类型。
_TREE_SEARCH_TYPES = ("Indicator", "Dimension")

_TREE_PROPERTY_NAMES = {
    "Indicator": (("code", "指标编码"), ("label", "指标名称"), ("name", "英文名")),
    "Dimension": (("code", "维度编码"), ("label", "维度名称"), ("name", "英文名")),
}
_ATTRIBUTE_PROPERTY_NAMES = (("code", "属性编码"), ("name", "属性名称"), ("label", "属性标签"))


def _vertex_config(type_name: str, properties: Iterable[tuple[str, str]]) -> dict[str, Any]:
    """Documented ``analysisConfig``: a single returned vertex with its properties."""
    return {"vertex": [{
        "type": type_name,
        "label": type_name,
        "properties": [{"name": name, "label": label} for name, label in properties],
    }]}


def _page_rows(client: RemoteOntologyClient, analysis: dict[str, Any], common: dict[str, Any]) -> list[dict[str, Any]]:
    """Rows of one documented metadata page (TABLE). Raises ``OntologyApiError``."""
    data = client.metadata_query(analysis, common)
    return [row for row in _walk_rows(data) if isinstance(row, dict)]


def _tree_name_search(
    client: RemoteOntologyClient,
    type_name: str,
    needle: str,
    *,
    limit: int = 20,
    page_size: int = TREE_PAGE_SIZE,
    max_pages: int = TREE_MAX_PAGES,
) -> list[dict[str, Any]]:
    """Ranked ``type_name`` rows from the documented paginated tree query.

    Continues to the next page while a page comes back full and nothing has
    matched yet, so a single-page truncation is never read as "no such object"
    (Spec §4.1 第 3 条).  Raises ``OntologyApiError`` when the tree endpoint
    itself is unavailable, so the caller can degrade explicitly.
    """
    properties = _TREE_PROPERTY_NAMES.get(type_name, (("code", "编码"), ("label", "名称")))
    analysis = _vertex_config(type_name, properties)
    collected: list[dict[str, Any]] = []
    for page_num in range(1, max_pages + 1):
        common = {
            "filters": {
                "type": type_name,
                "property": "label",
                "operator": {"code": "LIKE", "type": "STRING"},
                "value": f"%{needle}%",
            },
            "sorts": [{"type": type_name, "property": "code", "order": "ASC"}],
            "pagination": {"pageNum": page_num, "pageSize": page_size},
        }
        rows = _page_rows(client, analysis, common)
        collected.extend(rows)
        eligible = sorted(
            ((_rank_row(row, needle), row) for row in collected if _rank_row(row, needle)[0] < 99),
            key=lambda pair: pair[0],
        )
        if eligible:
            best_tier = eligible[0][0][0]
            return [row for rank, row in eligible if rank[0] == best_tier][:limit]
        if len(rows) < page_size:
            break
    return []


def _tree_attribute_search(
    client: RemoteOntologyClient,
    entity_code: str,
    *,
    page_size: int = TREE_PAGE_SIZE,
    max_pages: int = TREE_MAX_PAGES,
) -> list[dict[str, Any]]:
    """Rows of the documented ``LEContainATT`` attribute query (Spec §4.2).

    Pages until a short/empty page, so attributes beyond the first page are
    never silently dropped.  Raises ``OntologyApiError`` when the query itself
    is unavailable.
    """
    analysis = _vertex_config("BusinessAttribute", _ATTRIBUTE_PROPERTY_NAMES)
    collected: list[dict[str, Any]] = []
    seen: set[str] = set()
    for page_num in range(1, max_pages + 1):
        common = {
            "filters": {"logic": "AND", "children": [
                {"type": "LogicalEntity", "property": "code",
                 "operator": {"code": "EQ", "type": "STRING"}, "value": entity_code},
                {"type": "LEContainATT", "sourceType": "LogicalEntity",
                 "targetType": "BusinessAttribute"},
            ]},
            "sorts": [{"type": "BusinessAttribute", "property": "code", "order": "ASC"}],
            "pagination": {"pageNum": page_num, "pageSize": page_size},
        }
        rows = _page_rows(client, analysis, common)
        for row in rows:
            key = _text(_ci_get(row, "code", "identifierCode")) or json.dumps(
                row, sort_keys=True, ensure_ascii=False)
            if key not in seen:
                seen.add(key)
                collected.append(row)
        if len(rows) < page_size:
            break
    return collected


def _metric_search(
    client: RemoteOntologyClient, query: str, limit: int = 20,
) -> tuple[list[dict[str, Any]], bool]:
    """Indicator-only search: documented tree first, local full pull on failure.

    Returns ``(rows, degraded)`` where ``degraded`` marks a fallback that must
    be disclosed in the answer.
    """
    try:
        return _tree_name_search(client, "Indicator", query, limit=limit), False
    except OntologyApiError:
        return _search_type(client, "Indicator", query, limit=limit), True


def _candidate_results(
    client: RemoteOntologyClient, query: str,
) -> tuple[list[tuple[str, dict[str, Any]]], bool]:
    """Search the candidate types; ``Indicator`` / ``Dimension`` use the tree.

    Returns ``(found, degraded)``; ``degraded`` is True when a tree query failed
    and the local full pull was used instead (Spec §4.3).
    """
    found: list[tuple[str, dict[str, Any]]] = []
    degraded = False
    for type_name in _CANDIDATE_TYPES:
        try:
            if type_name in _TREE_SEARCH_TYPES:
                try:
                    rows = _tree_name_search(client, type_name, query, limit=10)
                except OntologyApiError:
                    degraded = True
                    rows = _search_type(client, type_name, query, limit=10)
            else:
                rows = _search_type(client, type_name, query, limit=10)
        except OntologyApiError:
            continue
        found.extend((type_name, row) for row in rows)
    found.sort(key=lambda pair: _rank_row(pair[1], query))
    return found, degraded


# ---------------------------------------------------------------------------
# 权威确认层（Spec §4.2）
#
# 确权口径必须来自本体服务：`resolve-ontology-object` 原生支持
# `candidateTypes` 顺序优先匹配，命中时把 `properties` 展开到行根级。
# 本地 `_candidate_results` / `_rank_row` 只在确认层"跳过"或"不可用"时兜底。
# ---------------------------------------------------------------------------

#: 每个工具的权威类型（Spec §4.2 第 3 条）：必须是 `candidateTypes` 首项。
_AUTHORITATIVE_TYPES = {
    "Ontology-TermDisambiguate": "Term",
    "MetricCalculation": "Indicator",
    "Ontology-EntityDescribe": "BusinessObject",
    "Ontology-SemanticQuery": "BusinessObject",
}

#: 确认接口只接受"单个对象名/编码"；带这些标记的是查询意图，必须走既有搜索路径。
_QUERY_MARKER_RE = re.compile(
    r"[\s?？!！。，,;；、/\\|<>()（）\[\]【】\"'“”‘’=+*%]"
    r"|下降|上升|上涨|增长|减少|原因|为什么|怎么|如何|多少|哪些|什么|趋势"
    r"|对比|比较|环比|同比|占比|排名|变化|影响|差异|异常|是否",
)

#: 确认层未命中/不可用时，答案里必须如实说明，不能把回退写成权威结论。
CONFIRMATION_UNAVAILABLE_NOTE = "（本体确认接口不可用，已回退到本地候选）"

MAX_CONFIRMABLE_NAME_LENGTH = 64


def _confirmable_name(value: Any) -> str:
    """Return the name worth confirming, or ``""`` for free-text queries."""
    name = str(value or "").strip()
    if not name or len(name) > MAX_CONFIRMABLE_NAME_LENGTH:
        return ""
    if _QUERY_MARKER_RE.search(name):
        return ""
    return name


def confirmation_candidates(tool_name: str) -> list[str]:
    """`candidateTypes`: 权威类型优先 + 文档枚举回退项（顺序稳定、无重复）。"""
    authoritative = _AUTHORITATIVE_TYPES.get(tool_name, "BusinessObject")
    return [authoritative] + [item for item in _CANDIDATE_TYPES if item != authoritative]


def confirm_object(
    client: RemoteOntologyClient, *, name: Any, candidate_types: list[str]
) -> dict[str, Any]:
    """按本体服务的权威结论确认对象（Spec §4.2）。

    返回 ``status`` ∈ ``hit`` / ``miss`` / ``unavailable`` / ``skipped``；命中时
    携带接口给出的 ``typeName`` 与展开后的 ``properties``。确认层抛错**不向上传播**：
    调用方必须在 ``unavailable`` 时降级到本地候选并附上降级说明。
    """
    requested = _confirmable_name(name)
    result: dict[str, Any] = {
        "status": "skipped",
        "name": requested,
        "typeName": "",
        "code": "",
        "properties": {},
        "error": "",
    }
    if not requested or not candidate_types:
        return result
    try:
        confirmed = client.ensure_object(requested, list(candidate_types))
    except OntologyApiError as exc:
        result["status"] = "unavailable"
        result["error"] = str(exc)
        return result
    info = confirmed.get("objectInfo") if isinstance(confirmed, dict) else None
    properties = info.get("properties") if isinstance(info, dict) else None
    if not confirmed.get("found") or not isinstance(properties, dict):
        result["status"] = "miss"
        return result
    result["status"] = "hit"
    result["typeName"] = str(info.get("typeName") or "Unknown")
    result["properties"] = properties
    result["code"] = _text(_ci_get(properties, "code", "identifierCode"))
    return result


def _confirmed_block(confirmed: dict[str, Any]) -> str:
    """Render a confirmed hit strictly from the authority's own fields."""
    return _format_object(
        str(confirmed.get("typeName") or "Unknown"),
        dict(confirmed.get("properties") or {}),
    )


def _confirmed_name_for_miss(name: str) -> str:
    return f"本体库中没有名为 {name!r} 的对象/术语（已由本体服务确认）。"


def _with_degraded_note(text: str, confirmed: dict[str, Any]) -> str:
    if confirmed.get("status") != "unavailable":
        return text
    return f"{text}\n\n{CONFIRMATION_UNAVAILABLE_NOTE}"


def _code_type(value: str) -> str:
    code = value.upper()
    if code.startswith("MREL"):
        return "MetaRelation"
    if code.startswith("BO"):
        return "BusinessObject"
    if code.startswith("LE"):
        return "LogicalEntity"
    if code.startswith(("ATT", "AT")):
        return "BusinessAttribute"
    if code.startswith(("MET", "M")):
        return "Indicator"
    if code.startswith(("DIM", "D")):
        return "Dimension"
    if code.startswith(("RULE", "R")):
        return "Rule"
    if code.startswith(("TERM", "T")):
        return "Term"
    if code.startswith(("ACT", "A")):
        return "Activity"
    if code.startswith(("PROC", "SSP")):
        return "Process"
    if code.startswith("PT"):
        return "TableNode"
    if code.startswith("COL"):
        return "Column"
    if code.startswith("ER"):
        return "EntityRelation"
    return "BusinessObject"


def _graph_anchor_candidates(
    client: RemoteOntologyClient, query: str,
) -> list[tuple[str, dict[str, Any]]]:
    """Resolve graph anchors exactly like local mode: BO or Indicator only."""

    found: list[tuple[str, dict[str, Any]]] = []
    for type_name in ("BusinessObject", "Indicator"):
        try:
            found.extend((type_name, row) for row in _search_type(client, type_name, query, limit=12))
        except OntologyApiError:
            continue
    found.sort(key=lambda pair: _rank_row(pair[1], query))
    return found


def _related_objects(data: dict[str, Any]) -> list[dict[str, Any]]:
    """Extract related objects from either MAL dialect.

    Legacy replies put them under ``objects`` / ``relatedObjects``; the new
    ``QueryResponse`` returns one related object per row under ``result.rows``
    with ``typeName`` at the row root.
    """
    if not isinstance(data, dict):
        return []
    objects = data.get("objects") or data.get("relatedObjects")
    if not isinstance(objects, list):
        result = data.get("result")
        raw_rows = result.get("rows") if isinstance(result, dict) else None
        objects = raw_rows if isinstance(raw_rows, list) else []
    normalised: list[dict[str, Any]] = []
    for item in objects:
        if not isinstance(item, dict):
            continue
        if isinstance(item.get("properties"), dict) or "typeName" in item or "type" in item:
            properties = item.get("properties")
            if not isinstance(properties, dict):
                properties = {
                    key: value for key, value in item.items() if key not in ("typeName", "type")
                }
            normalised.append({
                "typeName": str(item.get("typeName") or item.get("type") or "Unknown"),
                "properties": properties,
            })
        else:
            normalised.append(item)
    return normalised


def _render_related_objects(objects: list[dict[str, Any]], title: str) -> str:
    lines = [f"# {title} ({len(objects)})"]
    for item in objects:
        obj_type = str(item.get("typeName") or item.get("type") or "Unknown")
        lines.append(_format_object(obj_type, item.get("properties") or item))
    return "\n\n".join(lines) if objects else f"{title}: no related objects."


def _related_text(data: dict[str, Any], title: str = "关联本体") -> str:
    return _render_related_objects(_related_objects(data), title)


def _attribute_and_relation_text(
    client: RemoteOntologyClient, kind: str, code: str,
) -> tuple[str, list[str]]:
    """属性（文档查询）+ 关系（图邻域）双来源渲染，返回 ``(文本, 降级说明)``。

    属性必须来自文档的 ``LEContainATT`` 查询；关系仍由既有 ``find_related`` 负责，
    两者不得互相顶替。属性查询失败时降级到图邻域并如实说明（Spec §4.3）。
    """
    notes: list[str] = []
    attributes: list[dict[str, Any]] = []
    try:
        attributes = [
            {"typeName": "BusinessAttribute", "properties": row}
            for row in _tree_attribute_search(client, code)
        ]
    except OntologyApiError:
        notes.append(ATTRIBUTE_DEGRADE_NOTE)
    relations: list[dict[str, Any]] = []
    try:
        relations = _related_objects(client.find_related(kind, code, depth=1))
    except OntologyApiError:
        pass
    text = _render_related_objects(attributes + relations, "Attributes and relations")
    return text, notes


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


def _resolve_display_names(
    client: RemoteOntologyClient,
    codes: list[str],
    type_name: str,
) -> dict[str, str]:
    """Best-effort ``{code: display_name}`` for metric/dimension codes.

    Already-obtained ontology info is reused first (client-level caches); only
    unresolved codes trigger a bounded, cached ``metadata_query`` lookup.  Any
    lookup failure degrades to the original code — a missing name never blocks
    the data query and never fabricates a name.
    """
    cache = getattr(client, "_display_name_cache", {})
    now = time.monotonic()
    ttl = float(getattr(client, "cache_ttl", 30.0))
    result: dict[str, str] = {}
    unresolved: list[str] = []
    for code in codes:
        entry = cache.get(code)
        if entry and now - entry[0] <= ttl:
            result[code] = entry[1]
        else:
            unresolved.append(code)

    metadata_query = getattr(client, "metadata_query", None)
    if unresolved and callable(metadata_query):
        property_sets = (("code", "label", "name"), ("label", "name"))
        for code in list(unresolved):
            display = ""
            for property_names in property_sets:
                if display:
                    break
                analysis = {
                    "vertex": [{
                        "type": type_name,
                        "label": type_name,
                        "properties": [{"name": name, "label": name} for name in property_names],
                    }],
                }
                common = {
                    "filters": {"logic": "AND", "children": [
                        {"type": type_name, "property": "code",
                         "operator": {"code": "EQ", "type": "STRING"}, "value": code},
                    ]},
                    "pagination": {"pageNum": 1, "pageSize": 20},
                }
                try:
                    meta_data = metadata_query(analysis, common)
                except Exception:
                    continue
                for row in _walk_rows(meta_data):
                    row_code = _text(_ci_get(row, "code", "identifierCode"))
                    if row_code == code:
                        candidate = pick_display_name(row)
                        if candidate and candidate != code:
                            display = candidate
                            break
            result[code] = display or code
            cache[code] = (now, result[code])
    client._display_name_cache = cache
    return result

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
            return "Ontology-SemanticQuery: empty query."
        limit = max(1, min(int(params.get("limit") or 10), 100))
        confirmed = confirm_object(
            client, name=query,
            candidate_types=confirmation_candidates("Ontology-SemanticQuery"),
        )
        if confirmed["status"] == "hit":
            return "# Remote Ontology-SemanticQuery\n\n" + _confirmed_block(confirmed)
        if confirmed["status"] == "miss":
            return f"Ontology-SemanticQuery: {_confirmed_name_for_miss(query)}"
        try:
            matches, tree_degraded = _candidate_results(client, query)
            if not matches:
                return f"Ontology-SemanticQuery: no remote matches for {query!r}."
            body = "# Remote Ontology-SemanticQuery\n\n" + "\n\n".join(
                _format_object(kind, props) for kind, props in matches[:limit]
            )
            if tree_degraded:
                body = f"{body}\n\n{TREE_DEGRADE_NOTE}"
            return _with_degraded_note(body, confirmed)
        except OntologyApiError as exc:
            return f"Ontology-SemanticQuery remote error: {exc}"
    return run


def _make_term(client: RemoteOntologyClient) -> Executor:
    def run(params: dict[str, Any], cwd: str) -> str:
        term = str(params.get("term") or "").strip()
        if not term:
            return "Ontology-TermDisambiguate: empty term."
        confirmed = confirm_object(
            client, name=term,
            candidate_types=confirmation_candidates("Ontology-TermDisambiguate"),
        )
        if confirmed["status"] == "hit":
            return _confirmed_block(confirmed)
        if confirmed["status"] == "miss":
            return f"Ontology-TermDisambiguate: {_confirmed_name_for_miss(term)}"
        try:
            rows = _search_type(client, "Term", term, limit=20)
            body = "\n\n".join(
                _format_object("Term", row) for row in rows
            ) or f"No term matches {term!r}."
            return _with_degraded_note(body, confirmed)
        except OntologyApiError as exc:
            return f"Ontology-TermDisambiguate remote error: {exc}"
    return run


def _make_metric(client: RemoteOntologyClient) -> Executor:
    def run(params: dict[str, Any], cwd: str) -> str:
        query = str(params.get("metric") or "").strip()
        if not query:
            return "MetricCalculation: empty metric."
        confirmed = confirm_object(
            client, name=query,
            candidate_types=confirmation_candidates("MetricCalculation"),
        )
        if confirmed["status"] in {"hit", "miss"} and not confirmed["code"]:
            return f"No metric matches {query!r}."
        try:
            tree_degraded = False
            if confirmed["status"] == "hit":
                # 指标身份由权威接口先确认；下面只补指标的维度上下文。
                rows = [dict(confirmed["properties"])]
            else:
                # Indicator-only by design. Do not let unrelated object types
                # win simply because they share the same label or code fragment.
                rows, tree_degraded = _metric_search(client, query)
                if not rows:
                    return f"No metric matches {query!r}."
            rendered: list[str] = []
            for row in rows:
                metric = _metric_adapter(row)
                dimensions, source = _metric_dimensions(client, metric["code"])
                rendered.append(_format_metric(metric, dimensions, source))
            body = "\n\n".join(rendered)
            if tree_degraded:
                body = f"{body}\n\n{TREE_DEGRADE_NOTE}"
            return _with_degraded_note(body, confirmed)
        except OntologyApiError as exc:
            return f"MetricCalculation remote error: {exc}"
    return run


def _make_related(client: RemoteOntologyClient) -> Executor:
    retriever = RemoteGraphRetriever(client)

    def run(params: dict[str, Any], cwd: str) -> str:
        entity = str(params.get("entity") or "").strip()
        if not entity:
            return "Ontology-RelationQuery: empty entity."
        try:
            return retriever.relation_bundle(_code_type(entity), entity, depth=2)
        except (OntologyApiError, ValueError) as exc:
            return f"Ontology-RelationQuery remote error: {exc}"
    return run


def _make_describe(client: RemoteOntologyClient) -> Executor:
    def run(params: dict[str, Any], cwd: str) -> str:
        entity = str(params.get("entity") or "").strip()
        if not entity:
            return "Ontology-EntityDescribe: empty entity."
        confirmed = confirm_object(
            client, name=entity,
            candidate_types=confirmation_candidates("Ontology-EntityDescribe"),
        )
        if confirmed["status"] == "hit":
            # 展开上下文必须使用权威接口给出的 typeName/code，而不是本地排序结果。
            kind = str(confirmed["typeName"] or "Unknown")
            code = str(confirmed["code"] or entity)
            text, notes = _attribute_and_relation_text(client, kind, code)
            body = _confirmed_block(confirmed) + "\n\n" + text
            if notes:
                body = f"{body}\n\n{' '.join(notes)}"
            return body
        if confirmed["status"] == "miss":
            return f"Ontology-EntityDescribe: {_confirmed_name_for_miss(entity)}"
        try:
            matches, tree_degraded = _candidate_results(client, entity)
            if not matches:
                return f"Ontology-EntityDescribe: no remote match for {entity!r}."
            kind, props = matches[0]
            code = _text(_ci_get(props, "code", "identifierCode", default=entity))
            text, notes = _attribute_and_relation_text(client, kind, code)
            body = _format_object(kind, props) + "\n\n" + text
            if notes:
                body = f"{body}\n\n{' '.join(notes)}"
            if tree_degraded:
                body = f"{body}\n\n{TREE_DEGRADE_NOTE}"
            return _with_degraded_note(body, confirmed)
        except OntologyApiError as exc:
            return f"Ontology-EntityDescribe remote error: {exc}"
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
    retriever = RemoteGraphRetriever(client)

    def run(params: dict[str, Any], cwd: str) -> str:
        anchor = str(params.get("anchor") or "").strip()
        query = str(params.get("query") or "").strip()
        try:
            if not anchor:
                if not query:
                    return "Ontology-GraphContext: provide query or anchor."
                matches = _graph_anchor_candidates(client, query)
                if not matches:
                    return f"Ontology-GraphContext: no remote anchor for {query!r}."
                if len(matches) > 1:
                    return "Ontology-GraphContext: multiple candidates; specify anchor:\n" + "\n".join(
                        _format_object(kind, props).splitlines()[0] for kind, props in matches
                    )
                type_name, props = matches[0]
                anchor = _text(_ci_get(props, "code", "identifierCode"))
            else:
                type_name = _code_type(anchor)
                props = None
            if type_name not in {"BusinessObject", "Indicator"}:
                return f"Ontology-GraphContext: anchor [{anchor}] must be a BusinessObject or Indicator."
            return retriever.context_bundle(type_name, anchor, root_properties=props, depth=4)
        except (OntologyApiError, ValueError) as exc:
            return f"Ontology-GraphContext remote error: {exc}"
    return run


def _make_graph_expand(client: RemoteOntologyClient) -> Executor:
    retriever = RemoteGraphRetriever(client)

    def run(params: dict[str, Any], cwd: str) -> str:
        anchor = str(params.get("anchor") or "").strip()
        if not anchor:
            return "Ontology-GraphExpand: empty anchor."
        try:
            type_name = _code_type(anchor)
            if type_name not in {"BusinessObject", "Indicator"}:
                return f"Ontology-GraphExpand: anchor [{anchor}] must be a BusinessObject or Indicator."
            return retriever.expand(type_name, anchor, depth=5)
        except (OntologyApiError, ValueError) as exc:
            return f"Ontology-GraphExpand remote error: {exc}"
    return run


def _make_metric_data_query(client: RemoteOntologyClient) -> Executor:
    def run(params: dict[str, Any], cwd: str) -> str:
        raw_codes = params.get("metric_codes") or []
        raw_dimensions = params.get("dimensions") or []
        if not isinstance(raw_codes, list) or not isinstance(raw_dimensions, list):
            return "Ontology-MetricQuery: metric_codes and dimensions must be arrays."
        codes = [str(code).strip() for code in raw_codes if str(code).strip()]
        if not codes:
            return "Ontology-MetricQuery: metric_codes is empty."
        dimensions = [str(code).strip() for code in raw_dimensions if str(code).strip()]
        try:
            page_num = max(1, int(params.get("page_num") or 1))
            page_size = max(1, min(int(params.get("page_size") or 100), 500))
        except (TypeError, ValueError):
            return "Ontology-MetricQuery: page_num and page_size must be integers."

        # Resolve display names BEFORE building the analysis request so the
        # remote alias uses a stable business name instead of the bare code.
        metric_names = _resolve_display_names(client, codes, "Indicator")
        dimension_names = _resolve_display_names(client, dimensions, "Dimension")
        metric_aliases = unique_aliases(metric_names)
        dimension_aliases = unique_aliases(dimension_names)
        metrics_meta = [
            {
                "code": code,
                "display_name": metric_names.get(code, code),
                "alias": metric_aliases.get(code, code),
                "kind": "metric",
            }
            for code in codes
        ]
        dimensions_meta = [
            {
                "code": code,
                "display_name": dimension_names.get(code, code),
                "alias": dimension_aliases.get(code, code),
                "kind": "dimension",
            }
            for code in dimensions
        ]
        analysis = {
            "indicators": [
                {"identifierCode": code, "alias": metric_aliases.get(code, code)}
                for code in codes
            ],
            "dimensions": [
                {"identifierCode": code, "alias": dimension_aliases.get(code, code)}
                for code in dimensions
            ],
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
                "Ontology-MetricQuery remote error (recent endpoint failure): "
                + cached_failure[1]
                + "\n请直接回退 Ontology-FactQuery，稍后再重试语义查询。"
            )
        try:
            data = client.data_query(analysis, common)
            client._data_query_failure = None
            normalized = normalize_query_result(
                data=data,
                scope={
                    "metric_codes": codes,
                    "metrics": metrics_meta,
                    "dimensions": dimensions,
                    "dimension_names": dimension_names,
                    "dimensions_meta": dimensions_meta,
                    "filters": common.get("filters", {}),
                },
                semantic={
                    "metrics": codes,
                    "dimensions": dimensions,
                    "metric_names": metric_names,
                    "dimension_names": dimension_names,
                },
                provenance=Provenance(source="remote", api="analysis/data/query",
                                      metric_code=",".join(codes)),
            )
            return "# Ontology-MetricQuery (analysis/data/query)\n\n" + json.dumps(
                normalized.to_dict(), ensure_ascii=False, indent=2)
        except OntologyApiError as exc:
            message = str(exc)
            # A repository-wide server failure should not be retried for every
            # drill-down in the same agent turn. Cache it briefly, while leaving
            # 4xx/validation errors metric-specific and immediately retryable.
            if re.search(r"\bHTTP 5\d\d\b", message):
                client._data_query_failure = (now, message)
            return (
                "Ontology-MetricQuery remote error: " + message
                + "\n可在确认指标口径与物理映射后回退 Ontology-FactQuery。"
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
