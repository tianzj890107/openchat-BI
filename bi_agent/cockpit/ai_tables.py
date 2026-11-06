"""AP-backed DataTable queries with validated per-row AI annotations.

The delivered ProUI components own table layout, pagination and rendering.
This module only validates the fixed AP fields for the three order tables and
merges structured analysis fields from the published stage card.  It never
turns arbitrary page text into a cause or an action.
"""
from __future__ import annotations

import calendar
import json
import hashlib
import re
import time
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from .delivery import KIND_LABELS, ensure_checkable
from . import periods


class TableQuery(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    id: int = Field(ge=1, le=2)
    ui_scope: str = Field(default="default", alias="uiScope", max_length=16000)
    period: str = Field(default="", max_length=32)
    cache_only: bool = Field(default=False, alias="cacheOnly")
    analysis_config: dict = Field(alias="analysisConfig")
    common_config: dict = Field(alias="commonConfig")


def _field(code: str, label: str, kind: str, *, name: str = "", value_type: str = "") -> dict:
    value = {
        "fieldType": kind,
        "identifierCode": code,
        "isTree": False,
        "label": label,
        "valueType": value_type or ("NUMBER" if kind == "Indicator" else "STRING"),
    }
    if name:
        value["name"] = name
    return value


STAR_PRODUCT_FIELDS = [
    _field("YWLN_D046", "明星产品系列", "Dimension"),
    _field("YWLN_M_STAR_PRODUCT_SHIPMENT_2025", "去年参考电量", "Indicator"),
    _field("YWLN_M0032", "订单接收电量", "Indicator", name="Signed_Opportunity_Forecast_Energy"),
    _field("YWLN_M_ORDER_RECEIPT_ENERGY_PCT", "占全部订单电量", "Indicator",
           name="Order_Receipt_Energy_Percentage"),
]

ORDER_LIST_FIELDS = [
    _field("YWLN_D049", "销售订单编号", "Dimension"),
    _field("YWLN_D006", "具体客户", "Dimension"),
    _field("YWLN_D005", "客户等级", "Dimension"),
    _field("YWLN_D004", "产品团队", "Dimension"),
]

OVERDUE_FIELDS = [
    *ORDER_LIST_FIELDS,
    _field("M0143", "超期订未发金额", "Indicator", name="Overdue_Unshipped_Amount"),
    _field("YWLN_M_ORDER_OVERDUE_DAYS", "超期天数", "Indicator", name="Order_Overdue_Days"),
    _field("YWLN_D050", "承诺发货日", "Dimension", value_type="DATE"),
]

AFFECTED_FIELDS = [
    _field("YWLN_D049", "销售订单编号", "Dimension"),
    _field("YWLN_D006", "具体客户", "Dimension"),
    _field("YWLN_D005", "客户等级", "Dimension"),
    _field("YWLN_D003", "产品类型", "Dimension"),
    _field("YWLN_D004", "产品团队", "Dimension"),
    _field("YWLN_D016", "变更类型", "Dimension"),
    _field("YWLN_M0032", "减少电量（GWh）", "Indicator"),
    _field("YWLN_M0033", "影响金额（亿元）", "Indicator"),
]

AFFECTED_PRE_FILTERS = [{
    "alias": "订单状态",
    "identifierCode": "YWLN_D016",
    "operator": {"code": "IN", "type": "STRING"},
    "type": "Dimension",
    "value": ["order_change", "order_cancel"],
    "valueType": "ABSOLUTE",
}]

OVERDUE_PRE_FILTERS = [{
    "alias": "超期天数",
    "identifierCode": "YWLN_M_ORDER_OVERDUE_DAYS",
    "operator": {"code": "GT", "type": "NUMBER"},
    "type": "Indicator",
    "value": 0,
    "valueType": "ABSOLUTE",
}]

TABLE_SPECS = {
    "star-product-order-list": {
        "page": "operations",
        "stage": "order",
        "identity": "YWLN_D046",
        "title": "明星产品订单电量及占比",
        "fields": STAR_PRODUCT_FIELDS,
        "pre_filters": [],
        "custom": ("口径",),
    },
    "affected-order-list": {
        "page": "analysis",
        "stage": "order",
        "identity": "YWLN_D049",
        "title": "受影响订单清单",
        "fields": AFFECTED_FIELDS,
        "pre_filters": AFFECTED_PRE_FILTERS,
        "custom": ("原因", "责任动作"),
    },
    "overdue-order-list": {
        "page": "analysis",
        "stage": "shipment",
        "identity": "YWLN_D049",
        "title": "客户与超期订单",
        "fields": OVERDUE_FIELDS,
        "pre_filters": OVERDUE_PRE_FILTERS,
        "custom": ("主因和根因分析",),
    },
}

MISSING_CAUSE = "证据不足，未确认根因"
MISSING_ACTION = "待核实原因后明确责任动作"
DATE_SCOPE_DIMENSION = "YWLN_D044"
TABLE_MAPPING_VERSION = "ai-tables-v3"


def table_scope_key(ui_scope: str) -> str:
    return str(ui_scope or "default").strip() or "default"


def table_cache_key(identity: int, table_key: str, ui_scope: str, ap_payload: dict) -> str:
    material = json.dumps({
        "id": identity,
        "table": table_key,
        "mapping": TABLE_MAPPING_VERSION,
        "scope": table_scope_key(ui_scope),
        "query": ap_payload,
    }, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(material.encode("utf-8")).hexdigest()


def _scope_changes(ui_scope: str) -> list | None:
    raw = str(ui_scope or "").strip()
    if not raw or raw in {"default", "[]"}:
        return []
    try:
        value = json.loads(raw)
    except (TypeError, ValueError):
        return None
    return value if isinstance(value, list) else None


def _date_values(node, values: list[str]) -> None:
    """Collect only date-like scalar values from a delivered filter payload."""
    if isinstance(node, dict):
        for key in ("value", "values", "selected", "selectedValues", "range", "conditionValues"):
            if key in node:
                _date_values(node[key], values)
        for key in ("start", "end", "from", "to"):
            if key in node:
                _date_values(node[key], values)
        return
    if isinstance(node, list):
        for item in node:
            _date_values(item, values)
        return
    if isinstance(node, (int, float)) and not isinstance(node, bool):
        text = str(node)
    elif isinstance(node, str):
        text = node.strip()
    else:
        return
    if re.fullmatch(r"\d{4}(?:-\d{2}(?:-\d{2})?)?", text) and text not in values:
        values.append(text)


def _is_date_filter(node) -> bool:
    if not isinstance(node, dict):
        return False
    code = str(node.get("identifierCode") or node.get("code") or node.get("field") or "").strip()
    if code == DATE_SCOPE_DIMENSION:
        return True
    label = " ".join(str(node.get(key) or "") for key in ("label", "labelName", "alias", "title", "name"))
    return any(word in label for word in ("时间", "日期", "期间"))


def _looks_like_business_filter(node: dict) -> bool:
    code = str(node.get("identifierCode") or node.get("code") or node.get("field") or "").strip()
    if code and code != DATE_SCOPE_DIMENSION and re.match(r"^[A-Za-z]{1,8}\d", code):
        return True
    label = " ".join(str(node.get(key) or "") for key in ("label", "labelName", "alias", "title", "name"))
    return any(word in label for word in ("客户", "产品", "状态", "团队", "等级", "区域", "部门", "类型", "行业"))


def _collect_scope_dates(node, dates: list[str], *, date_scope: bool = False,
                         unsupported: list[str] | None = None) -> None:
    if isinstance(node, list):
        for child in node:
            _collect_scope_dates(child, dates, date_scope=date_scope, unsupported=unsupported)
        return
    if not isinstance(node, dict):
        return
    current = date_scope or _is_date_filter(node)
    if current:
        _date_values(node, dates)
    elif unsupported is not None and _looks_like_business_filter(node) and any(
            key in node for key in ("value", "values", "selected", "selectedValues", "range", "conditionValues")):
        label = str(node.get("identifierCode") or node.get("code") or node.get("label") or "未识别筛选")
        unsupported.append(label)
    for key, child in node.items():
        if key in {"value", "values", "selected", "selectedValues", "range", "conditionValues",
                   "start", "end", "from", "to"}:
            continue
        if isinstance(child, (dict, list)):
            _collect_scope_dates(child, dates, date_scope=current, unsupported=unsupported)


def _date_range(value: str) -> tuple[str, str]:
    value = value.strip()
    if re.fullmatch(r"\d{4}", value):
        return f"{value}-01-01", f"{value}-12-31"
    if re.fullmatch(r"\d{4}-\d{2}", value):
        year, month = (int(part) for part in value.split("-"))
        return f"{value}-01", f"{value}-{calendar.monthrange(year, month)[1]:02d}"
    if re.fullmatch(r"\d{4}-\d{2}-\d{2}", value):
        return value, value
    raise ValueError("页面日期筛选格式不受支持")


def page_scope_date_filter(ui_scope: str, fallback_period: str = "") -> dict | None:
    """Translate the delivered page date scope into one AP date filter.

    The host scope is a serialized list of committed runtime calls.  Only the
    date dimension used by these tables is mapped here.  A custom scope with no
    translatable date condition must be rejected by the caller: querying the
    full table would silently answer a different business question.
    """
    changes = _scope_changes(ui_scope)
    if changes is None:
        raise ValueError("页面筛选范围格式无效，已阻止无口径查询")
    if not changes:
        # The delivered cockpit is on its empty default filter without emitting
        # a custom date change.  Use the explicitly supplied page period so the
        # table facts stay aligned with the visible header instead of silently
        # querying all time.
        fallback = str(fallback_period or "").strip()
        if not fallback:
            return None
        start, end = _date_range(fallback)
        return {
            "identifierCode": DATE_SCOPE_DIMENSION,
            "operator": {"code": "BETWEEN", "type": "DATE"},
            "value": [start, end],
            "valueType": "ABSOLUTE",
        }
    grain = ""
    dates: list[str] = []
    unsupported: list[str] = []
    real_filters = 0
    for change in changes:
        if not isinstance(change, list) or len(change) != 2 or not isinstance(change[0], str):
            continue
        try:
            value = json.loads(change[1]) if isinstance(change[1], str) else change[1]
        except (TypeError, ValueError):
            continue
        method = change[0].split(":", 1)[0]
        if method == "setButtonGrainSelection":
            if isinstance(value, str):
                grain = value.strip().upper()
            elif isinstance(value, dict):
                grain = str(value.get("grain") or "").strip().upper()
            continue
        real_filters += 1
        _collect_scope_dates(value, dates, unsupported=unsupported)
    if unsupported:
        names = "、".join(dict.fromkeys(unsupported))
        raise ValueError(f"页面筛选包含尚未映射到AI表格的字段：{names}，已阻止只按部分条件查询")
    if not dates:
        # The delivered default emits a MONTH grain call before the first user
        # action.  It deliberately represents the preheated default scope.
        if grain == "MONTH" and not real_filters:
            fallback = str(fallback_period or "").strip()
            if not fallback:
                return None
            start, end = _date_range(fallback)
            return {
                "identifierCode": DATE_SCOPE_DIMENSION,
                "operator": {"code": "BETWEEN", "type": "DATE"},
                "value": [start, end],
                "valueType": "ABSOLUTE",
            }
        raise ValueError("当前页面筛选尚未映射到AI表格，已阻止无口径查询")
    start, end = _date_range(dates[0])
    if len(dates) > 1:
        start, _ = _date_range(dates[0])
        _, end = _date_range(dates[-1])
    return {
        "identifierCode": DATE_SCOPE_DIMENSION,
        "operator": {"code": "BETWEEN", "type": "DATE"},
        "value": [start, end],
        "valueType": "ABSOLUTE",
    }


def _contains_filter_code(node, code: str) -> bool:
    if isinstance(node, list):
        return any(_contains_filter_code(item, code) for item in node)
    if not isinstance(node, dict):
        return False
    current = str(node.get("identifierCode") or node.get("code") or node.get("field") or "").strip()
    if current == code:
        return True
    return any(_contains_filter_code(value, code) for value in node.values())


def _merge_scope_filter(filters, scope_filter: dict | None):
    if scope_filter is None or _contains_filter_code(filters, DATE_SCOPE_DIMENSION):
        return filters
    if filters in (None, {}, []):
        return scope_filter
    return {"logic": "AND", "children": [filters, scope_filter]}


def _merge_filter_parts(*parts):
    """Combine filter trees with AND while removing identical pre-filters."""
    children = []
    seen = set()
    for part in parts:
        if part in (None, {}, []):
            continue
        if isinstance(part, list):
            values = part
        elif isinstance(part, dict) and (
            str(part.get("logic") or "").upper() == "AND" or "children" in part
        ):
            values = part.get("children") or []
        else:
            values = [part]
        for value in values:
            signature = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
            if signature in seen:
                continue
            seen.add(signature)
            children.append(value)
    if not children:
        return None
    if len(children) == 1:
        return children[0]
    return {"logic": "AND", "children": children}


def _text(value) -> str:
    if value is None:
        return ""
    if isinstance(value, dict) and "value" in value:
        return _text(value.get("value"))
    return str(value).strip()


def _cell(value):
    """Keep the ProDataTable cell envelope while stripping AP-only wrappers."""
    if not isinstance(value, dict) or "value" not in value:
        return value
    raw = value.get("value")
    unit = ((value.get("render") or {}).get("unit"))
    if isinstance(raw, (int, float)) and not isinstance(raw, bool):
        return {"unit": unit, "value": raw} if unit else {"value": raw}
    identifier = value.get("identifierNumber")
    if raw is None:
        return None
    if identifier not in (None, ""):
        return {"identifierNumber": str(identifier), "value": raw}
    return raw


def _filter_codes(node, allowed: set[str]) -> None:
    if node in (None, {}, []):
        return
    if isinstance(node, list):
        if len(node) > 20:
            raise ValueError("筛选条件过多")
        for child in node:
            _filter_codes(child, allowed)
        return
    if not isinstance(node, dict):
        raise ValueError("筛选条件格式无效")
    if "logic" in node or "children" in node:
        if str(node.get("logic") or "AND").upper() != "AND":
            raise ValueError("表格筛选只允许 AND 组合")
        children = node.get("children") or []
        if not isinstance(children, list) or len(children) > 20:
            raise ValueError("筛选条件格式无效")
        for child in children:
            _filter_codes(child, allowed)
        return
    code = str(node.get("identifierCode") or "")
    if code not in allowed:
        raise ValueError("筛选字段不属于当前表格")
    operator = node.get("operator")
    if not isinstance(operator, dict) or not str(operator.get("code") or "").strip():
        raise ValueError("筛选操作符无效")
    if len(json.dumps(node, ensure_ascii=False)) > 4000:
        raise ValueError("筛选条件过大")


def build_ap_query(table_key: str, request: TableQuery) -> dict:
    spec = TABLE_SPECS.get(table_key)
    if spec is None:
        raise KeyError(table_key)
    expected = [item["identifierCode"] for item in spec["fields"]]
    config = request.analysis_config or {}
    dimensions = config.get("dimensions") or []
    indicators = config.get("indicators") or []
    supplied = [str(item.get("identifierCode") or "") for item in dimensions + indicators
                if isinstance(item, dict)]
    if len(supplied) != len(expected) or set(supplied) != set(expected):
        raise ValueError("表格字段与交付配置不一致")
    allowed_filters = {"YWLN_D044"} | {
        item["identifierCode"] for item in spec["fields"] if item["fieldType"] == "Dimension"
    } | {item["identifierCode"] for item in spec.get("pre_filters", [])}
    common = request.common_config or {}
    filters = common.get("filters")
    scope_filter = page_scope_date_filter(request.ui_scope, request.period)
    filters = _merge_scope_filter(filters, scope_filter)
    _filter_codes(filters, allowed_filters)
    filters = _merge_filter_parts(filters, spec.get("pre_filters"))
    pagination = common.get("pagination") or {}
    try:
        page_num = max(1, int(pagination.get("pageNum") or 1))
        page_size = min(50, max(1, int(pagination.get("pageSize") or 10)))
    except (TypeError, ValueError):
        raise ValueError("分页参数无效") from None
    payload = {
        "analysisConfig": {
            "dimensions": [item for item in spec["fields"] if item["fieldType"] == "Dimension"],
            "indicators": [{**item, "valueConfig": {"numericScale": 2}}
                           for item in spec["fields"] if item["fieldType"] == "Indicator"],
        },
        "commonConfig": {"pagination": {"pageNum": page_num, "pageSize": page_size}},
    }
    if filters not in (None, {}, []):
        payload["commonConfig"]["filters"] = filters
    return payload


def preheat_table(store, identity: int, table_key: str, query_receipt,
                  period: str = "") -> str:
    """Persist the exact default table query the browser will request.

    ``query_receipt(identity, kind, payload)`` is the router's shared AP read
    path, so table preheat participates in request coalescing and stores the
    same receipt-backed facts as an interactive query.
    """
    spec = TABLE_SPECS[table_key]
    period = period or periods.default_period()
    request = TableQuery(
        id=identity, uiScope="default", period=period,
        analysisConfig={
            "dimensions": [item for item in spec["fields"]
                           if item["fieldType"] == "Dimension"],
            "indicators": [item for item in spec["fields"]
                           if item["fieldType"] == "Indicator"],
        },
        commonConfig={"pagination": {"pageNum": 1, "pageSize": 10}},
    )
    payload = build_ap_query(table_key, request)
    scope_key = table_scope_key(request.ui_scope)
    cache_key = table_cache_key(request.id, table_key, scope_key, payload)
    if store.get_ai_table_snapshot(cache_key, request.id, table_key, scope_key) is not None:
        return "cached"
    receipt = query_receipt(request.id, "analysis", payload)
    rows, total = result_rows(receipt["response"])
    store.save_ai_table_snapshot(
        cache_key, request.id, table_key, scope_key,
        dict(rows=rows, total=total, createdAt=time.time(), query=payload))
    return "published"


def result_rows(data: Any) -> tuple[list[dict], int | None]:
    result = data.get("result") if isinstance(data, dict) else None
    rows = (result or {}).get("rows") if isinstance(result, dict) else None
    if not isinstance(rows, list):
        rows = data.get("rows") if isinstance(data, dict) else None
    if not isinstance(rows, list):
        raise ValueError("AP表格响应缺少 rows")
    normalised = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        normalised.append({key: _cell(value) for key, value in row.items()})
    pagination = data.get("pagination") if isinstance(data, dict) else None
    total = (pagination or {}).get("total") if isinstance(pagination, dict) else None
    return normalised, int(total) if isinstance(total, (int, float)) else None


def _record_contains(record, key: str, *, seen=None) -> bool:
    if key in ("", None):
        return False
    seen = seen or set()
    if isinstance(record, dict):
        marker = id(record)
        if marker in seen:
            return False
        seen.add(marker)
        return any(_record_contains(value, key, seen=seen) for value in record.values())
    if isinstance(record, list):
        return any(_record_contains(value, key, seen=seen) for value in record)
    return str(record).strip() == key


def _analysis_index(card: dict | None) -> tuple[list[dict], list[dict], dict[str, dict]]:
    card = card or {}
    result = card.get("result") or {}
    evidence = card.get("evidence") or {}
    records = {
        str(item.get("id")): item
        for item in evidence.get("records") or []
        if isinstance(item, dict) and item.get("id")
    }
    for item in evidence.get("evidence") or []:
        if isinstance(item, dict) and item.get("id") and isinstance(item.get("record"), dict):
            records[str(item["id"])] = item["record"]
    return result.get("causes") or [], result.get("recommendations") or [], records


def _matched_causes(row_key: str, causes: list[dict], records: dict[str, dict]) -> list[dict]:
    matched = []
    for cause in causes:
        if not isinstance(cause, dict):
            continue
        if any(_record_contains(records.get(str(evidence_id)), row_key)
               for evidence_id in cause.get("evidenceIds") or []):
            matched.append(cause)
    return matched


def _cause_text(cause: dict) -> str:
    title = _text(cause.get("title"))
    description = _text(cause.get("description"))
    kind = _text(cause.get("kind"))
    if kind:
        status = "证据支持" if kind == "verified" else KIND_LABELS.get(kind, "待验证")
    else:
        status = "证据支持" if cause.get("status") == "supported" else "待验证"
    value = "；".join(part for part in (title, description) if part)
    return f"{status}：{value}" if value else ""


def _action_text(cause_ids: set[str], recommendations: list[dict]) -> str:
    values = []
    for item in recommendations:
        if not isinstance(item, dict) or not cause_ids.intersection(item.get("causeIds") or []):
            continue
        action = _text(item.get("action"))
        owner = _text(item.get("ownerRole"))
        days = item.get("deadlineDays")
        acceptance = _text(item.get("acceptance"))
        detail = "；".join(part for part in (
            f"建议措施：{action}" if action else "",
            f"建议责任角色：{owner}（待确认）" if owner else "",
            f"建议期限：{days} 个工作日（待确认）" if isinstance(days, int) and days > 0 else "",
            f"验收：{ensure_checkable(acceptance)}" if acceptance else "",
        ) if part)
        if detail:
            values.append(detail)
    return "；".join(dict.fromkeys(values))


def _star_scope(series: str, card: dict | None) -> str:
    """Read a versioned scope note from the current analysis, never fixed copy."""
    card = card or {}
    result = card.get("result") or {}
    evidence = card.get("evidence") or {}
    for source in (result.get("scopeNotes"), evidence.get("scopeNotes")):
        if not isinstance(source, dict):
            continue
        value = source.get(series) or source.get("*")
        if isinstance(value, str) and value.strip():
            return value.strip()
    candidates = [*(evidence.get("facts") or []), *(evidence.get("evidence") or [])]
    for item in candidates:
        if not isinstance(item, dict):
            continue
        text = " ".join(_text(item.get(key)) for key in ("label", "name", "definition", "claim"))
        if series and series in text:
            definition = _text(item.get("definition")) or _text(item.get("claim"))
            if definition:
                return definition
    return "当前筛选范围的业务口径未在已发布分析中提供，未沿用固定参考文案。"


def annotate_rows(table_key: str, rows: list[dict], card: dict | None) -> tuple[list[dict], dict]:
    spec = TABLE_SPECS[table_key]
    causes, recommendations, records = _analysis_index(card)
    annotated = []
    matched_count = 0
    for row in rows:
        value = dict(row)
        row_key = _text(value.get(spec["identity"]))
        if table_key == "star-product-order-list":
            value["口径"] = _star_scope(row_key, card)
        else:
            matched = _matched_causes(row_key, causes, records) if row_key else []
            if matched:
                matched_count += 1
            cause_ids = {str(item.get("id")) for item in matched if item.get("id")}
            if table_key == "overdue-order-list":
                value["主因和根因分析"] = "；".join(
                    detail for detail in (_cause_text(item) for item in matched) if detail
                ) or MISSING_CAUSE
            else:
                value["原因"] = "；".join(
                    detail for detail in (_cause_text(item) for item in matched) if detail
                ) or MISSING_CAUSE
                value["责任动作"] = _action_text(cause_ids, recommendations) or MISSING_ACTION
        annotated.append(value)
    meta = {
        "tableKey": table_key,
        "analysisCardId": (card or {}).get("id", ""),
        "analysisStatus": "merged" if matched_count else ("card_loaded" if card else "missing"),
        "matchedRows": matched_count,
        "source": "ap+structured-analysis",
    }
    return annotated, meta
