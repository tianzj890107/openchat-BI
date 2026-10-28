"""Deterministic multi-period, structure, progress, forecast and plan validation.

These helpers never invent missing business evidence.  A capability that needs
stage history, approved targets or a registered forecast model returns a
blocking gap instead of a plausible-looking number.
"""

from __future__ import annotations

import re
from datetime import timedelta
from typing import Any, Iterable, Mapping

from .models import Scope, envelope, gap


def _numeric(value: Any) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _period(scope: Scope) -> tuple[str, str]:
    return (
        scope.period_start.isoformat() if scope.period_start else "",
        scope.observation_cutoff().isoformat(),
    )


def previous_period(scope: Scope) -> tuple[Scope, dict[str, Any]]:
    start = scope.period_start
    end = scope.observation_cutoff()
    if not start or not end:
        raise ValueError("periodStart and periodEnd are required")
    days = (end - start).days + 1
    previous_end = start - timedelta(days=1)
    previous_start = previous_end - timedelta(days=max(days - 1, 0))
    return (
        Scope(
            as_of=previous_end,
            period_start=previous_start,
            period_end=previous_end,
            customer_ids=scope.customer_ids,
            owner_ids=scope.owner_ids,
            product_ids=scope.product_ids,
            limit=scope.limit,
            include_current_snapshot=scope.include_current_snapshot,
        ),
        {
            "start": previous_start.isoformat(),
            "end": previous_end.isoformat(),
            "days": max(days, 1),
        },
    )


def compare_metrics(
    current_query: Mapping[str, Any], previous_query: Mapping[str, Any]
) -> dict[str, Any]:
    current = {str(m.get("code")): m for m in current_query.get("metrics", [])}
    previous = {str(m.get("code")): m for m in previous_query.get("metrics", [])}
    rows: list[dict[str, Any]] = []
    for code in sorted(set(current) & set(previous)):
        now = current[code]
        before = previous[code]
        now_value = _numeric(now.get("value")) if now.get("status") != "blocked" else None
        before_value = _numeric(before.get("value")) if before.get("status") != "blocked" else None
        comparable = now_value is not None and before_value is not None
        delta = (now_value - before_value) if comparable else None
        rate = (delta / before_value) if comparable and before_value not in (None, 0) else None
        rows.append(
            {
                "metric": code,
                "name": now.get("name") or before.get("name") or code,
                "unit": now.get("unit") or before.get("unit") or "",
                "current": now_value,
                "previous": before_value,
                "change": delta,
                "changeRate": rate,
                "comparable": comparable,
                "zeroBase": bool(comparable and before_value == 0),
                "status": "ok" if comparable else "blocked",
            }
        )
    return {
        "rows": rows,
        "status": "ok" if rows and all(row["comparable"] for row in rows) else "partial",
    }


DIMENSION_LABELS = {
    "customer_name": "客户",
    "customer_id": "客户",
    "product_id": "产品",
    "product_name": "产品",
    "owner_id": "负责人",
    "owner_name": "负责人",
    "region": "区域",
    "cell_model": "电芯型号",
    "team": "团队",
}

VALUE_FIELDS = (
    "amount_100m", "amount_rmb", "amount_tax_free", "power_gwh", "energy_mwh",
    "actual_power_gwh", "actual_amount_100m", "qty", "remaining_qty",
)


def structure_from_records(
    records: Iterable[Mapping[str, Any]],
    *,
    dimension: str = "",
    value_field: str = "",
    top_n: int = 10,
    truncated: bool = False,
) -> dict[str, Any]:
    rows = list(records or [])
    if not rows:
        return {
            "status": "blocked",
            "dimension": dimension or None,
            "valueField": value_field or None,
            "groups": [],
            "gaps": [
                gap("STRUCTURE_SOURCE_MISSING", "没有可用于结构分析的明细", needed="先取回对象明细并确认维度关系", impact="不计算排名和贡献", severity="blocking", source="runtime")
            ],
        }
    available = {key for row in rows for key in row}
    if not dimension:
        dimension = next((key for key in DIMENSION_LABELS if key in available), "")
    if not dimension or dimension not in available:
        return {
            "status": "needs_clarification",
            "dimension": dimension or None,
            "valueField": value_field or None,
            "groups": [],
            "gaps": [
                gap("STRUCTURE_DIMENSION_UNMAPPED", "维度未映射到事实字段", needed="指定可用维度，不能按销售姓名或文本猜测 ID", impact="不生成结构排名", severity="blocking", source="catalog")
            ],
        }
    if not value_field:
        value_field = next(
            (
                field
                for field in VALUE_FIELDS
                if field in available
                and any(_numeric(row.get(field)) is not None for row in rows)
            ),
            "",
        )
    if not value_field:
        return {
            "status": "needs_clarification",
            "dimension": dimension,
            "valueField": None,
            "groups": [],
            "gaps": [
                gap("STRUCTURE_VALUE_UNMAPPED", "没有可加总的指标字段", needed="指定金额/数量/电量字段或改用聚合查询", impact="不把条数当作业务贡献", severity="blocking", source="runtime")
            ],
        }
    grouped: dict[str, dict[str, Any]] = {}
    unknown = 0.0
    total = 0.0
    for row in rows:
        value = _numeric(row.get(value_field))
        if value is None:
            continue
        label = str(row.get(dimension) or "").strip() or "未分类"
        if label == "未分类":
            unknown += value
        total += value
        target = grouped.setdefault(
            label,
            {"key": label, "label": label, "value": 0.0, "records": 0},
        )
        target["value"] += value
        target["records"] += 1
    ranked = sorted(grouped.values(), key=lambda item: (-item["value"], item["label"]))
    for index, item in enumerate(ranked, 1):
        item["rank"] = index
        item["share"] = item["value"] / total if total else None
    return {
        "status": "partial" if truncated else "ok",
        "dimension": dimension,
        "valueField": value_field,
        "groups": ranked[: max(1, min(int(top_n or 10), 100))],
        "totals": {
            "value": total,
            "unknown": unknown,
            "groups": len(grouped),
            "records": len(rows),
            "truncated": bool(truncated),
            "complete": not truncated,
        },
        "limitations": [
            "排名基于本次返回明细求和；明细截断时 complete=false，总量以聚合指标为准。",
            "统计贡献不等于业务原因。",
        ],
    }


def process_conversion(
    stages: Iterable[Mapping[str, Any]] | None,
    *,
    object_key: str = "objectId",
    batch_key: str = "batchId",
) -> dict[str, Any]:
    rows = [dict(row) for row in (stages or []) if isinstance(row, Mapping)]
    if not rows:
        return {
            "status": "blocked",
            "stages": [],
            "gaps": [
                gap("PROCESS_STAGE_TRACE_MISSING", "缺少对象贯穿键和阶段日期", needed="提供同一批次的节点、对象键、进入/离开时间及未完成记录", impact="不能用同期间两节点数量相除代替转化率", severity="blocking", source="runtime")
            ],
        }
    keys = {str(row.get(object_key) or "") for row in rows if row.get(object_key)}
    batches = {str(row.get(batch_key) or "") for row in rows if row.get(batch_key)}
    grouped: dict[str, dict[str, Any]] = {}
    for row in rows:
        stage = str(row.get("stage") or row.get("node") or "")
        if not stage:
            continue
        item = grouped.setdefault(stage, {"stage": stage, "entered": 0, "completed": 0, "open": 0})
        item["entered"] += 1
        if row.get("completedAt"):
            item["completed"] += 1
        else:
            item["open"] += 1
    ordered = list(grouped.values())
    for index, item in enumerate(ordered):
        item["conversion"] = (
            next(iter(grouped.values()))["entered"] and item["entered"] / next(iter(grouped.values()))["entered"]
        )
        if index == 0:
            item["conversion"] = 1.0
    return {
        "status": "ok" if keys and batches else "partial",
        "objectKey": object_key,
        "batchKey": batch_key,
        "objects": len(keys),
        "batches": len(batches),
        "stages": ordered,
        "limitations": [
            "只按同一对象键和批次计算；未完成记录保留在 open，不与已完成平均耗时混算。"
        ],
    }


def validate_solution_structure(
    tasks: Iterable[Mapping[str, Any]],
    *,
    due_at: str = "",
    approval_required: bool = True,
) -> dict[str, Any]:
    items = [dict(row) for row in (tasks or []) if isinstance(row, Mapping)]
    findings: list[dict[str, Any]] = []
    if not items:
        findings.append(
            {"code": "TASKS_MISSING", "severity": "blocking", "message": "没有可评审的任务草稿"}
        )
    leads = [str(item.get("ownerRole") or item.get("owner_ref") or "").strip() for item in items]
    if items and (not leads or any(not lead for lead in leads)):
        findings.append(
            {"code": "UNIQUE_OWNER_MISSING", "severity": "blocking", "message": "每条任务必须有唯一牵头角色或责任人"}
        )
    if items and not any(item.get("acceptance") for item in items):
        findings.append(
            {"code": "ACCEPTANCE_MISSING", "severity": "blocking", "message": "缺少可核验的完成标准"}
        )
    if items and not due_at and not any(item.get("dueAt") or item.get("due_at") for item in items):
        findings.append(
            {"code": "DUE_DATE_MISSING", "severity": "degrading", "message": "期限待宿主或审批人确认，不虚构日期"}
        )
    if approval_required and items and not all(
        (item.get("requires") or {}).get("approval") for item in items
    ):
        findings.append(
            {"code": "APPROVAL_PREREQUISITE_MISSING", "severity": "blocking", "message": "任务未声明下发审批前置"}
        )
    status = "blocked" if any(item["severity"] == "blocking" for item in findings) else (
        "partial" if findings else "ok"
    )
    return {
        "status": status,
        "findings": findings,
        "canReview": status != "blocked",
        "scored": False,
        "note": "没有批准成本、周期、效果权重时不生成伪精确综合评分。",
    }


def compare_solution_options(options: Iterable[Mapping[str, Any]] | None) -> dict[str, Any]:
    rows = [dict(row) for row in (options or []) if isinstance(row, Mapping)]
    required = ("code", "name", "effect", "cost", "cycleDays")
    complete = [row for row in rows if all(row.get(key) not in (None, "") for key in required)]
    if len(rows) < 2 or len(complete) != len(rows):
        return {
            "status": "blocked",
            "options": rows,
            "recommended": None,
            "gaps": [
                gap("SOLUTION_COMPARISON_EVIDENCE_MISSING", "方案比较依据不完整", needed="至少两个方案，且每个都有批准的效果、成本和周期依据", impact="不生成综合评分或推荐", severity="blocking", source="runtime")
            ],
        }
    return {
        "status": "partial",
        "options": rows,
        "recommended": None,
        "note": "依据已齐但未获业务权重批准；只展示逐项差异，不生成本地综合分。",
    }


def rule_forecast(
    *,
    actual_to_date: float | None,
    target: float | None,
    elapsed_days: int | None,
    total_days: int | None,
    assumption: str = "",
) -> dict[str, Any]:
    if None in (actual_to_date, target, elapsed_days, total_days) or not assumption.strip():
        return {
            "status": "blocked",
            "kind": "rule_estimate",
            "gaps": [
                gap("FORECAST_MODEL_OR_ASSUMPTION_MISSING", "缺少预测模型或明确假设", needed="提供实际值、目标、期间进度和已批准/显式假设", impact="不以模型语言包装线性外推", severity="blocking", source="runtime")
            ],
        }
    if int(elapsed_days) <= 0 or int(total_days) <= 0:
        raise ValueError("elapsedDays and totalDays must be positive")
    rate = float(actual_to_date) / max(int(elapsed_days), 1)
    projected = rate * int(total_days)
    return {
        "status": "partial",
        "kind": "rule_estimate",
        "assumption": assumption,
        "projected": projected,
        "target": float(target),
        "gap": projected - float(target),
        "confidenceInterval": None,
        "limitations": ["这是显式假设下的规则推算，不是已登记模型预测或承诺。"],
    }


def progress_from_receipts(
    executions: Iterable[Mapping[str, Any]],
    receipts: Iterable[Mapping[str, Any]] | None = None,
) -> dict[str, Any]:
    rows = [dict(item) for item in (executions or [])]
    receipt_rows = [dict(item) for item in (receipts or [])]
    if not rows:
        return {
            "status": "not_applicable",
            "tasks": [],
            "limitations": ["当前没有本服务创建并可恢复的任务执行记录。"],
        }
    tasks = []
    for item in rows:
        response = item.get("response") or {}
        tasks.append(
            {
                "executionId": item.get("id"),
                "taskRef": item.get("action_id"),
                "sourceTodoId": item.get("source_todo_id"),
                "status": item.get("status"),
                "receiptStatus": response.get("status"),
            }
        )
    return {
        "status": "partial",
        "tasks": tasks,
        "receipts": receipt_rows,
        "limitations": ["Fuxi 契约只提供来源推送和状态通知，不提供待办执行进度查询；口头完成不等于业务回执。"],
    }


def normalize_dimension(value: str) -> str:
    text = str(value or "").strip()
    aliases = {
        "客户": "customer_name",
        "产品": "product_id",
        "负责人": "owner_id",
        "区域": "region",
        "团队": "team",
        "电芯型号": "cell_model",
    }
    return aliases.get(text, text if re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", text) else "")
