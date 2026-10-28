"""Deterministic multi-goal plan construction and server-side exploration budgets."""

from __future__ import annotations

import re
import time
from typing import Any, Iterable, Mapping

from .models import Scope, envelope, gap


GOAL_RULES: tuple[tuple[str, str, str], ...] = (
    (r"多少|当前|本月|本周|今年|列出|清单|明细|查询", "P03", "当前事实与对象清单"),
    (r"趋势|环比|同比|比上月|比去年|变化", "P04", "多期变化与可比性"),
    (r"排名|top\s*\d*|占比|分布|按.*(拆|看)|下钻|集中", "P05", "结构、排名与贡献"),
    (r"异常|预警|风险|哪些.*(超期|未发)", "P06", "异常与风险对象"),
    (r"节点.*卡|卡在哪|转化率|流程堵点|立项.*投标", "P07", "流程节点与转化"),
    (r"为什么|原因|根因|导致", "P09", "候选原因与反证"),
    (r"怎么办|建议|方案|优先|处置", "P10", "候选方案与取舍"),
    (r"拆.*任务|任务令|整改计划|行动计划", "P11", "任务草稿与依赖"),
    (r"任务.*(进度|到哪|状态|超期)|催办", "P14", "任务进度与回执"),
    (r"预测|预计|能完成多少|情景|模拟", "P17", "目标差距与条件预测"),
)

TOOL_FOR_SOP = {
    "P03": "Process360Query",
    "P04": "Process360Compare",
    "P05": "Process360Structure",
    "P06": "Process360Query",
    "P07": "Process360ProcessFlow",
    "P09": "Process360Analyze",
    "P10": "Process360Solutions",
    "P11": "Process360Draft",
    "P14": "Process360Progress",
    "P15": "Process360Verify",
    "P17": "Process360Forecast",
    "P18": "Process360Plan",
}


def _goal_rows(question: str, primary_sop: str) -> list[tuple[str, str]]:
    text = str(question or "")
    matched: list[tuple[str, str]] = []
    for pattern, sop, title in GOAL_RULES:
        if re.search(pattern, text, flags=re.IGNORECASE) and sop not in {row[0] for row in matched}:
            matched.append((sop, title))
    if not matched:
        matched.append((primary_sop, TOOL_FOR_SOP.get(primary_sop, primary_sop)))
    if primary_sop == "P18":
        # P18 is a composite overview, not a single opaque call.  These are the
        # independent read-only branches explicitly required by the SOP.
        for sop, title in (
            ("P03", "当前事实"),
            ("P04", "期间变化"),
            ("P05", "结构与贡献"),
            ("P06", "异常与风险"),
        ):
            if sop not in {row[0] for row in matched}:
                matched.append((sop, title))
    elif primary_sop not in {row[0] for row in matched}:
        matched.insert(0, (primary_sop, TOOL_FOR_SOP.get(primary_sop, primary_sop)))
    return matched


def build_plan(
    catalog: Any,
    *,
    question: str,
    scenario: str | None,
    scope: Scope,
    principal: Mapping[str, Any],
    budget: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    from .router import route

    primary = route(question, catalog, scenario=scenario)
    code = primary.scenario
    goals = _goal_rows(question, primary.sop_id)
    query_steps = [sop for sop, _title in goals if sop in {"P03", "P04", "P05", "P06", "P07"}]
    steps: list[dict[str, Any]] = []
    for index, (sop, title) in enumerate(goals, 1):
        depends: list[str] = []
        if sop in {"P09", "P10", "P11", "P14", "P17"} and query_steps:
            first_query = next(
                (f"step-{i}" for i, (item, _) in enumerate(goals, 1) if item == query_steps[0]),
                "",
            )
            if first_query:
                depends.append(first_query)
        if sop in {"P10", "P11"} and "P09" in {row[0] for row in goals}:
            depends.append(f"step-{next(i for i, row in enumerate(goals, 1) if row[0] == 'P09')}")
        steps.append(
            {
                "id": f"step-{index}",
                "sop": sop,
                "title": title,
                "tool": TOOL_FOR_SOP.get(sop, sop),
                "dependsOn": list(dict.fromkeys(depends)),
                "status": "pending",
                "recoverable": True,
                "stopOn": ["blocked", "needs_clarification"],
            }
        )
    raw_budget = dict(budget or {})
    limits = {
        "calls": max(1, min(int(raw_budget.get("calls") or 12), 50)),
        "elapsedMs": max(500, min(int(raw_budget.get("elapsedMs") or 60000), 600000)),
        "rows": max(1, min(int(raw_budget.get("rows") or 5000), 100000)),
    }
    return envelope(
        "S00",
        "ok" if code else "needs_clarification",
        catalog_id=catalog.catalog_id,
        catalog_version=catalog.version,
        scenario=code,
        question=question,
        scope=scope,
        route=primary.to_dict(),
        goals=[{"id": f"goal-{i}", "sop": sop, "title": title} for i, (sop, title) in enumerate(goals, 1)],
        steps=steps,
        planVersion=1,
        status_policy="independent branches may complete; dependent steps stop when prerequisites are blocked",
        budget={"limit": limits, "used": {"calls": 0, "elapsedMs": 0, "rows": 0}},
        allowedTools=[
            "Process360Search", "Process360Context", "Process360Query", "Process360Analyze",
            "Process360Compare", "Process360Structure", "Process360ProcessFlow",
            "Process360Progress", "Process360Forecast",
        ],
        principalScope=dict(principal),
        nextSteps=[step["id"] + " " + step["title"] for step in steps],
    )


class PlanExecutionError(RuntimeError):
    pass


def run_exploration_step(
    *,
    plan: Mapping[str, Any],
    step_id: str,
    tool: str,
    request_hash: str,
    executor: Any,
    store: Any,
    principal: Mapping[str, Any],
) -> dict[str, Any]:
    plan_principal = plan.get("principalScope") or {}
    if (
        str(plan_principal.get("tenantId") or "") != str(principal.get("tenantId") or "")
        or str(plan_principal.get("userId") or "") != str(principal.get("userId") or "")
    ):
        raise PlanExecutionError("plan belongs to a different principal")
    allowed = set(plan.get("allowedTools") or [])
    if tool not in allowed:
        raise PlanExecutionError("tool is outside the server-side exploration allowlist")
    step = next((row for row in plan.get("steps", []) if row.get("id") == step_id), None)
    if not step:
        raise PlanExecutionError("step_id is not part of this plan")
    calls = store.list_exploration(plan["id"])
    cached = next(
        (
            row
            for row in calls
            if str(row.get("step_id") or "") == step_id
            and str(row.get("request_hash") or "") == request_hash
        ),
        None,
    )
    if cached:
        return {
            "created": False,
            "record": cached,
            "result": cached.get("output") or {},
            "budget": {"limit": (plan.get("budget") or {}).get("limit") or {}, "used": {
                "calls": len(calls),
                "elapsedMs": sum(int(row.get("elapsed_ms") or 0) for row in calls),
                "rows": sum(int(row.get("rows_returned") or 0) for row in calls),
            }},
            "pathGap": cached.get("status") == "path_gap",
            "returnStep": step_id if cached.get("status") == "path_gap" else None,
            "stopReason": "path_gap" if cached.get("status") == "path_gap" else "",
        }
    if str(step.get("tool") or "") != tool:
        raise PlanExecutionError("tool does not match the planned step")
    used = {
        "calls": len(calls),
        "elapsedMs": sum(int(row.get("elapsed_ms") or 0) for row in calls),
        "rows": sum(int(row.get("rows_returned") or 0) for row in calls),
    }
    limits = (plan.get("budget") or {}).get("limit") or {}
    if used["calls"] >= int(limits.get("calls") or 0):
        raise PlanExecutionError("shared call budget exhausted")
    if used["elapsedMs"] >= int(limits.get("elapsedMs") or 0):
        raise PlanExecutionError("shared elapsed-time budget exhausted")
    if used["rows"] >= int(limits.get("rows") or 0):
        raise PlanExecutionError("shared row budget exhausted")
    started = time.monotonic()
    result = executor()
    elapsed = int((time.monotonic() - started) * 1000)
    rows = len(result.get("records") or []) + len(result.get("metrics") or [])
    status = "ok" if result.get("status") in {"ok", "partial"} else "path_gap"
    created, record = store.record_exploration(
        plan_id=plan["id"],
        step_id=step_id,
        tool=tool,
        request_hash=request_hash,
        status=status,
        output=result,
        rows_returned=rows,
        elapsed_ms=elapsed,
    )
    return {
        "created": created,
        "record": record,
        "result": result,
        "budget": {
            "limit": limits,
            "used": {
                "calls": used["calls"] + (1 if created else 0),
                "elapsedMs": used["elapsedMs"] + (elapsed if created else 0),
                "rows": used["rows"] + (rows if created else 0),
            },
        },
        "pathGap": status == "path_gap",
        "returnStep": step_id if status == "path_gap" else None,
        "stopReason": "path_gap" if status == "path_gap" else "",
    }
