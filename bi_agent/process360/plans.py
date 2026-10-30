"""S05 solution and task-order drafts.

Drafts are not executions.  They contain the scenario, solution, template,
required evidence, owner role and acceptance; recipient phones are deliberately
absent because the Fuxi host supplies them at click time.
"""

from __future__ import annotations

import re
from typing import Any, Mapping

from .catalog import Process360Catalog, _codes
from .models import envelope, gap
from .execute import _assert_no_phone
import json


SEVERITY_MAP = {
    "CRITICAL": "CRITICAL",
    "HIGH": "HIGH",
    "MEDIUM": "MEDIUM",
    "LOW": "LOW",
    "UNVERIFIABLE": "MEDIUM",
}


def _role_name(catalog: Process360Catalog, code: str) -> str:
    row = catalog.get("roles", code) or {}
    return str(row.get("name") or code)


def _task_for_solution(
    catalog: Process360Catalog, solution: Mapping[str, Any], tasks: list[Mapping[str, Any]]
) -> Mapping[str, Any] | None:
    wanted = _codes(solution.get("任务模板编码"))
    for task in tasks:
        if str(task.get("code")) in wanted:
            return task
    return None


def _content(
    scenario: Mapping[str, Any],
    problem: Mapping[str, Any],
    solution: Mapping[str, Any],
    task: Mapping[str, Any],
    analysis: Mapping[str, Any],
) -> str:
    observation = analysis.get("observation") or {}
    causes = [row.get("name") for row in analysis.get("candidateCauses", []) if row.get("name")]
    lines = [
        f"**场景**：{scenario.get('场景编码')} {scenario.get('场景名称')}",
        f"**问题**：{problem.get('问题名称') or problem.get('name') or scenario.get('业务问题')}",
        f"**已观察**：{observation.get('headline') or '见分析证据'}",
        f"**建议动作**：{solution.get('预期效果') or solution.get('方案名称')}",
    ]
    if causes:
        lines.append(
            "**待核查原因（候选，未确认）**：" + "、".join(str(item) for item in causes[:5])
        )
    if task.get("目标与验收"):
        lines.append(f"**目标与验收**：{task.get('目标与验收')}")
    if solution.get("适用约束"):
        lines.append(f"**约束**：{solution.get('适用约束')}")
    evidence = task.get("下发必填")
    if evidence:
        lines.append(f"**下发前必须补齐**：{evidence}")
    lines.append(
        "**说明**：本任务令由分析结论生成，执行由 Fuxi 待办承接；未确认的原因不得当作既定事实。"
    )
    return "\n".join(lines)


def _impact_text(observation: Mapping[str, Any]) -> str:
    impact = observation.get("impact") if isinstance(observation.get("impact"), dict) else {}
    parts: list[str] = []
    amount = impact.get("amount100m")
    power = impact.get("powerGwh")
    if isinstance(amount, (int, float)):
        parts.append(f"涉及金额 {float(amount):.2f} 亿元")
    if isinstance(power, (int, float)):
        parts.append(f"涉及电量 {float(power):.2f} GWh")
    objects = observation.get("objects")
    if isinstance(objects, int) and objects > 0:
        parts.append(f"涉及 {objects} 个业务对象")
    return "；".join(parts) or "影响范围见本次查询证据"


def _scope_text(scope: Any) -> str:
    if not isinstance(scope, Mapping):
        return "未单独指定业务范围"
    labels = {
        "periodStart": "期间开始",
        "periodEnd": "期间结束",
        "asOf": "观察截止日",
        "customerIds": "客户",
        "ownerIds": "负责人",
        "productIds": "产品",
    }
    parts = [
        f"{label} {scope.get(key)}"
        for key, label in labels.items()
        if scope.get(key) not in (None, "", [], ())
    ]
    return "；".join(parts) or "本次查询全部授权范围"


def _evidence_text(evidence: Any) -> str:
    values = evidence if isinstance(evidence, list) else ([evidence] if evidence else [])
    names: list[str] = []
    for item in values[:8]:
        if isinstance(item, Mapping):
            text = str(
                item.get("name")
                or item.get("title")
                or item.get("template")
                or item.get("code")
                or item.get("metricCode")
                or ""
            ).strip()
        else:
            text = str(item or "").strip()
        if text:
            names.append(text)
    return "；".join(names)


def _risk_content(
    record: Mapping[str, Any],
    analysis: Mapping[str, Any],
    risk: Mapping[str, Any],
) -> str:
    observation = analysis.get("observation") or {}
    causes = [str(row.get("name") or "").strip() for row in analysis.get("candidateCauses", [])]
    causes = [name for name in causes if name]
    lines = [
        f"**场景**：{record.get('场景编码') or analysis.get('scenario')} "
        f"{record.get('场景名称') or ''}".strip(),
        f"**已观察事实**：{observation.get('headline') or '见本轮查询证据'}",
        f"**影响**：{_impact_text(observation)}",
        f"**风险等级**：{risk.get('severity') or observation.get('severity') or 'MEDIUM'}"
        f"（{risk.get('severityBasis') or observation.get('severityBasis') or '运营分诊，不是客户批准的风险矩阵等级'}）",
        f"**业务范围**：{_scope_text(analysis.get('scope'))}",
    ]
    if risk.get("dataBoundary"):
        lines.append(f"**数据边界**：{risk.get('dataBoundary')}")
    if causes:
        lines.append(
            "**候选原因（待验证，不是已确认根因）**：" + "、".join(causes[:5])
        )
    evidence = _evidence_text(analysis.get("evidence"))
    if evidence:
        lines.append(f"**证据**：{evidence}")
    lines.append(
        "**说明**：本卡只推送有证据支持的已观察风险；推送成功只表示 Fuxi 已接收，"
        "不代表风险已解除。风险解除仍需后续证据与复验。"
    )
    return "\n".join(lines)


def _build_risk_actions(
    code: str,
    record: Mapping[str, Any],
    analysis: Mapping[str, Any],
    *,
    owner_ref: str = "",
    owner_name: str = "",
    severity: str | None = None,
) -> list[dict[str, Any]]:
    observation = analysis.get("observation") or {}
    level = SEVERITY_MAP.get(
        str(severity or observation.get("severity") or "MEDIUM"), "MEDIUM"
    )
    if not observation.get("observed") or observation.get("severity") == "UNVERIFIABLE":
        return []
    rows = list(analysis.get("risks") or [])
    if not rows:
        return []
    evidence_text = _evidence_text(analysis.get("evidence")) or str(
        observation.get("headline") or ""
    )
    actions: list[dict[str, Any]] = []
    for index, risk in enumerate(rows, start=1):
        risk_code = str(risk.get("code") or f"R{index:02d}").strip()
        safe_code = re.sub(r"[^A-Za-z0-9_.:-]+", "-", risk_code).strip("-") or f"R{index:02d}"
        name = str(risk.get("name") or risk.get("riskName") or "经营风险").strip()
        actions.append({
            "id": f"{code}-RISK-{safe_code}",
            "kind": "risk",
            "item_type": "RISK",
            "scenario": code,
            "title": f"{record.get('场景名称') or code}：{name}",
            "content": _risk_content(record, analysis, risk),
            "evidence": evidence_text,
            "severity": level,
            "severityBasis": risk.get("severityBasis")
            or observation.get("severityBasis")
            or "运营分诊级别；不是客户批准的风险矩阵等级",
            "due_at": "",
            "owner_ref": str(owner_ref or ""),
            "owner_name": str(owner_name or ""),
            "source": "boulderai-anaylize-todo",
            "category": "智能分析风险",
            "dispatchTool": "RiskItemCreate",
            "metadata": {
                "riskCode": risk_code,
                "riskName": name,
                "dataBoundary": risk.get("dataBoundary"),
                "candidateCauses": [
                    str(row.get("code") or "")
                    for row in analysis.get("candidateCauses", [])
                    if row.get("code")
                ],
                "candidateCausesUnverified": True,
                "dispatchTool": "RiskItemCreate",
            },
            "dispatch": {
                "tool": "RiskItemCreate",
                "source": "boulderai-anaylize-todo",
                "idempotency": "由独立的 analytics-risk sourceTodoId 保证重复点击幂等",
                "executionBoundary": "只推送风险条目；风险解除由后续证据与复验驱动",
            },
        })
    return actions


def build_draft(
    catalog: Process360Catalog,
    scenario: str,
    context: Mapping[str, Any],
    analysis: Mapping[str, Any],
    *,
    owner_ref: str = "",
    owner_name: str = "",
    due_at: str = "",
    severity: str | None = None,
    selected_solutions: list[str] | None = None,
) -> dict[str, Any]:
    code = str(scenario).upper()
    rejected_status = analysis.get("status") in {"blocked", "needs_clarification", "not_applicable"}
    try:
        _assert_no_phone(json.dumps([analysis, owner_ref, owner_name, due_at], ensure_ascii=False))
    except ValueError:
        return envelope(
            "S05",
            "needs_clarification",
            catalog_id=catalog.catalog_id,
            catalog_version=catalog.version,
            scenario=code,
            tasks=[],
            canvasActions=[],
            gaps=[
                gap(
                    "PRIVATE_DATA_IN_DRAFT",
                    "草稿输入包含手机号",
                    needed="移除手机号；由宿主点击时提供",
                    impact="未生成可展示草稿",
                )
            ],
        )
    if rejected_status:
        return envelope(
            "S05",
            str(analysis["status"]),
            catalog_id=catalog.catalog_id,
            catalog_version=catalog.version,
            scenario=code,
            tasks=[],
            canvasActions=[],
            gaps=analysis.get("gaps", []),
            limitations=analysis.get("limitations", []),
        )
    record = context.get("scenarioRecord") or (catalog.scenario(code) or {})
    problem = (context.get("problems") or [{}])[0]
    tasks = list(context.get("taskTemplates") or [])
    solutions = list(context.get("solutions") or [])
    wanted = {str(item).strip().upper() for item in (selected_solutions or []) if str(item).strip()}
    if wanted - {str(row.get("code")).upper() for row in solutions}:
        return envelope(
            "S05",
            "needs_clarification",
            catalog_id=catalog.catalog_id,
            catalog_version=catalog.version,
            scenario=code,
            tasks=[],
            canvasActions=[],
            gaps=[
                gap(
                    "UNKNOWN_SOLUTION",
                    "所选方案不属于本场景",
                    needed="从当前场景方案中选择",
                    impact="未生成任务令",
                )
            ],
        )
    if wanted:
        solutions = [row for row in solutions if str(row.get("code")).upper() in wanted]
    bundle_causes = {str(row.get("code")): row for row in context.get("causes", [])}
    candidate_codes = [str(row.get("code")) for row in analysis.get("candidateCauses", [])]
    top_severity = SEVERITY_MAP.get(
        str(severity or (analysis.get("observation") or {}).get("severity") or "MEDIUM"), "MEDIUM"
    )
    risk_actions = _build_risk_actions(
        code,
        record,
        analysis,
        owner_ref=owner_ref,
        owner_name=owner_name,
        severity=severity,
    )
    items: list[dict[str, Any]] = []
    for solution in solutions:
        task = _task_for_solution(catalog, solution, tasks)
        if task is None:
            continue
        task_code = str(task.get("code"))
        cause_names = [
            str(bundle_causes.get(cause, {}).get("name") or cause)
            for cause in _codes(solution.get("针对原因编码集合"))
        ]
        recommended = (
            bool(set(_codes(solution.get("针对原因编码集合"))) & set(candidate_codes)) or not items
        )
        items.append(
            {
                "id": f"{code}-{task_code}",
                "kind": "task_order",
                "item_type": "TODO",
                "scenario": code,
                "solution": solution.get("code"),
                "solutionName": solution.get("name") or solution.get("方案名称"),
                "taskTemplate": task_code,
                "title": f"{record.get('场景名称') or code}：{task.get('name') or task.get('任务名称')}",
                "content": _content(record, problem, solution, task, analysis),
                "evidence": "；".join(cause_names)
                if cause_names
                else str(solution.get("方案名称") or ""),
                "severity": top_severity,
                "severityBasis": "运营分诊级别；不是客户批准的风险矩阵等级",
                "dueAt": str(due_at or ""),
                "ownerRole": task.get("牵头角色编码") or solution.get("牵头角色编码"),
                "ownerRoleName": _role_name(
                    catalog, str(task.get("牵头角色编码") or solution.get("牵头角色编码") or "")
                ),
                "ownerRef": str(owner_ref or ""),
                "ownerName": str(owner_name or ""),
                "coRoles": _codes(task.get("协同角色编码集合")),
                "acceptance": task.get("目标与验收"),
                "requiredBeforeDispatch": task.get("下发必填"),
                "verification": task.get("复验模板编码") or solution.get("复验模板编码"),
                "recommended": recommended,
                "requires": {
                    "recipientsRaw": "由 Fuxi 宿主在用户点击时提供，禁止写入 HTML/日志/模型参数",
                    "ownerRef": "唯一牵头人 ID（可空，由宿主补全）",
                    "approval": "任务下发审批",
                },
                "dispatch": {
                    "tool": "TaskOrderCreate",
                    "source": "boulderai-anaylize-todo",
                    "idempotency": "由 sourceTodoId 保证重复点击幂等",
                    "executionBoundary": "只创建 Fuxi 待办；发运/签单/排产等业务动作由 Fuxi 待办侧承接",
                },
            }
        )
    canvas_actions = [
        {
            "id": item["id"],
            "title": item["title"],
            "content": item["content"],
            "evidence": item["evidence"],
            "severity": item["severity"],
            "due_at": item.get("dueAt") or "",
            "owner_ref": item.get("ownerRef") or "",
            "owner_name": item.get("ownerName") or "",
            "source": "boulderai-anaylize-todo",
            "scenario": code,
            "item_type": "TODO",
            "task_template": item.get("taskTemplate") or "",
            "category": "智能分析任务令",
            "metadata": {
                "solution": item.get("solution"),
                "verification": item.get("verification"),
                "dispatchTool": "TaskOrderCreate",
            },
        }
        for item in items
    ]
    status = "ok" if items or risk_actions else "blocked"
    return envelope(
        "S05",
        status,
        catalog_id=catalog.catalog_id,
        catalog_version=catalog.version,
        scenario=code,
        question=analysis.get("question"),
        scope=analysis.get("scope"),
        metrics=analysis.get("metrics", []),
        evidence_items=analysis.get("evidence", []),
        gaps=analysis.get("gaps", []),
        limitations=[
            "任务令是草稿，未发送；发送必须由用户在 Fuxi 页面点击并携带宿主提供的手机号。",
            "任务内容不包含手机号、密钥或数据库连接信息。",
            *analysis.get("limitations", []),
        ],
        next_steps=[
            "选择一条建议，确认责任人/期限/审批后由 Fuxi 宿主调用 TaskOrderCreate",
            "发送回执成功后进入 S07 复验计划",
        ],
        tasks=items,
        canvasActions=canvas_actions,
        riskActions=risk_actions,
        recommendedTask=next((item["id"] for item in items if item["recommended"]), None),
    )
