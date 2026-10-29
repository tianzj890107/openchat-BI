"""AP-backed DataTable queries with validated per-row AI annotations.

The delivered ProUI components own table layout, pagination and rendering.
This module only validates the fixed AP fields for the three order tables and
merges structured analysis fields from the published stage card.  It never
turns arbitrary page text into a cause or an action.
"""
from __future__ import annotations

import json
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class TableQuery(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    id: int = Field(ge=1, le=2)
    analysis_config: dict = Field(alias="analysisConfig")
    common_config: dict = Field(alias="commonConfig")


def _field(code: str, label: str, kind: str, *, name: str = "") -> dict:
    value = {
        "fieldType": kind,
        "identifierCode": code,
        "isTree": False,
        "label": label,
        "valueType": "NUMBER" if kind == "Indicator" else "STRING",
    }
    if name:
        value["name"] = name
    return value


STAR_PRODUCT_FIELDS = [
    _field("YWLN_D046", "明星产品系列", "Dimension"),
    _field("YWLN_M_STAR_PRODUCT_SHIPMENT_2025", "2025年明星产品出货参考电量", "Indicator"),
    _field("YWLN_M0032", "订单接收电量", "Indicator", name="Signed_Opportunity_Forecast_Energy"),
    _field("YWLN_M_STAR_PRODUCT_ORDER_SHARE", "明星产品订单电量占比", "Indicator"),
]

ORDER_LIST_FIELDS = [
    _field("YWLN_D049", "销售订单编号", "Dimension"),
    _field("YWLN_D006", "具体客户", "Dimension"),
    _field("YWLN_D005", "客户等级", "Dimension"),
    _field("YWLN_D004", "产品团队", "Dimension"),
]

OVERDUE_FIELDS = [
    *ORDER_LIST_FIELDS,
    _field("YWLN_D050", "承诺发货日", "Dimension"),
    _field("M0143", "超期订未发金额", "Indicator", name="Overdue_Unshipped_Amount"),
    _field("YWLN_M_ORDER_OVERDUE_DAYS", "超期天数", "Indicator", name="Order_Overdue_Days"),
]

AFFECTED_FIELDS = [
    _field("YWLN_D049", "销售订单编号", "Dimension"),
    _field("YWLN_D006", "具体客户", "Dimension"),
    _field("YWLN_D005", "客户等级", "Dimension"),
    _field("YWLN_D003", "产品类型", "Dimension"),
    _field("YWLN_D004", "产品团队", "Dimension"),
    _field("YWLN_M_ORDER_CANCEL_CHANGE", "取消/变更订单电量", "Indicator"),
]

TABLE_SPECS = {
    "star-product-order-list": {
        "page": "operations",
        "stage": "order",
        "identity": "YWLN_D046",
        "title": "明星产品订单电量及占比",
        "fields": STAR_PRODUCT_FIELDS,
        "custom": ("口径",),
    },
    "affected-order-list": {
        "page": "analysis",
        "stage": "order",
        "identity": "YWLN_D049",
        "title": "受影响订单清单",
        "fields": AFFECTED_FIELDS,
        "custom": ("原因", "责任动作"),
    },
    "overdue-order-list": {
        "page": "analysis",
        "stage": "shipment",
        "identity": "YWLN_D049",
        "title": "客户与超期订单",
        "fields": OVERDUE_FIELDS,
        "custom": ("主因和根因分析",),
    },
}

STAR_PRODUCT_SCOPES = {
    "MB31": "含系统；电芯 / 模组口径 21.126 GWh",
    "LF100L": "2025 全年出货参考",
    "MB56": "2025 全年出货参考",
    "明星产品合计": "三款产品，不重复计量",
    "其他产品": "其余型号",
    "全部产品": "有效已签订单",
}

MISSING_CAUSE = "证据不足，未确认根因"
MISSING_ACTION = "待核实原因后明确责任动作"


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
    }
    common = request.common_config or {}
    filters = common.get("filters")
    _filter_codes(filters, allowed_filters)
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
    status = "待验证" if cause.get("status") == "hypothesis" else "证据支持"
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
            action,
            f"责任角色：{owner}" if owner else "",
            f"期限：{days} 个工作日" if isinstance(days, int) and days > 0 else "",
            f"验收：{acceptance}" if acceptance else "",
        ) if part)
        if detail:
            values.append(detail)
    return "；".join(dict.fromkeys(values))


def _star_scope(series: str) -> str:
    if series in STAR_PRODUCT_SCOPES:
        return STAR_PRODUCT_SCOPES[series]
    for name, value in STAR_PRODUCT_SCOPES.items():
        if name != "全部产品" and name in series:
            return value
    return "未登记口径，待业务确认"


def annotate_rows(table_key: str, rows: list[dict], card: dict | None) -> tuple[list[dict], dict]:
    spec = TABLE_SPECS[table_key]
    causes, recommendations, records = _analysis_index(card)
    annotated = []
    matched_count = 0
    for row in rows:
        value = dict(row)
        row_key = _text(value.get(spec["identity"]))
        if table_key == "star-product-order-list":
            value["口径"] = _star_scope(row_key)
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
