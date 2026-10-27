"""S05 solution and task-order drafts.

Drafts are not executions.  They contain the scenario, solution, template,
required evidence, owner role and acceptance; recipient phones are deliberately
absent because the Fuxi host supplies them at click time.
"""

from __future__ import annotations

from typing import Any, Mapping

from .catalog import Process360Catalog, _codes
from .models import envelope


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


def _task_for_solution(catalog: Process360Catalog, solution: Mapping[str, Any],
                       tasks: list[Mapping[str, Any]]) -> Mapping[str, Any] | None:
    wanted = _codes(solution.get("任务模板编码"))
    for task in tasks:
        if str(task.get("code")) in wanted:
            return task
    return tasks[0] if tasks else None


def _content(scenario: Mapping[str, Any], problem: Mapping[str, Any], solution: Mapping[str, Any],
             task: Mapping[str, Any], analysis: Mapping[str, Any]) -> str:
    observation = analysis.get("observation") or {}
    causes = [row.get("name") for row in analysis.get("candidateCauses", []) if row.get("name")]
    lines = [
        f"**场景**：{scenario.get('场景编码')} {scenario.get('场景名称')}",
        f"**问题**：{problem.get('问题名称') or problem.get('name') or scenario.get('业务问题')}",
        f"**已观察**：{observation.get('headline') or '见分析证据'}",
        f"**建议动作**：{solution.get('预期效果') or solution.get('方案名称')}",
    ]
    if causes:
        lines.append("**待核查原因（候选，未确认）**：" + "、".join(str(item) for item in causes[:5]))
    if task.get("目标与验收"):
        lines.append(f"**目标与验收**：{task.get('目标与验收')}")
    if solution.get("适用约束"):
        lines.append(f"**约束**：{solution.get('适用约束')}")
    evidence = task.get("下发必填")
    if evidence:
        lines.append(f"**下发前必须补齐**：{evidence}")
    lines.append("**说明**：本任务令由分析结论生成，执行由 Fuxi 待办承接；未确认的原因不得当作既定事实。")
    return "\n".join(lines)


def build_draft(catalog: Process360Catalog, scenario: str, context: Mapping[str, Any],
                analysis: Mapping[str, Any], *, owner_ref: str = "", owner_name: str = "",
                due_at: str = "", severity: str | None = None,
                selected_solutions: list[str] | None = None) -> dict[str, Any]:
    code = str(scenario).upper()
    record = context.get("scenarioRecord") or (catalog.scenario(code) or {})
    problem = (context.get("problems") or [{}])[0]
    tasks = list(context.get("taskTemplates") or [])
    solutions = list(context.get("solutions") or [])
    wanted = {str(item).strip().upper() for item in (selected_solutions or []) if str(item).strip()}
    if wanted:
        solutions = [row for row in solutions if str(row.get("code")).upper() in wanted]
    bundle_causes = {str(row.get("code")): row for row in context.get("causes", [])}
    candidate_codes = [str(row.get("code")) for row in analysis.get("candidateCauses", [])]
    top_severity = SEVERITY_MAP.get(str(severity or (analysis.get("observation") or {}).get("severity") or "MEDIUM"), "MEDIUM")
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
        recommended = bool(set(_codes(solution.get("针对原因编码集合"))) & set(candidate_codes)) or not items
        items.append({
            "id": f"{code}-{task_code}",
            "kind": "task_order",
            "scenario": code,
            "solution": solution.get("code"),
            "solutionName": solution.get("name") or solution.get("方案名称"),
            "taskTemplate": task_code,
            "title": f"{record.get('场景名称') or code}：{task.get('name') or task.get('任务名称')}",
            "content": _content(record, problem, solution, task, analysis),
            "evidence": "；".join(cause_names) if cause_names else str(solution.get("方案名称") or ""),
            "severity": top_severity,
            "severityBasis": "运营分诊级别；不是客户批准的风险矩阵等级",
            "dueAt": str(due_at or ""),
            "ownerRole": task.get("牵头角色编码") or solution.get("牵头角色编码"),
            "ownerRoleName": _role_name(catalog, str(task.get("牵头角色编码") or solution.get("牵头角色编码") or "")),
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
        })
    canvas_actions = [{
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
        "task_template": item.get("taskTemplate") or "",
        "category": "智能分析任务令",
        "metadata": {
            "solution": item.get("solution"),
            "verification": item.get("verification"),
            "dispatchTool": "TaskOrderCreate",
        },
    } for item in items]
    status = "ok" if items else "blocked"
    return envelope(
        "S05", status, catalog_id=catalog.catalog_id, catalog_version=catalog.version,
        scenario=code, question=analysis.get("question"), scope=analysis.get("scope"),
        metrics=analysis.get("metrics", []), evidence_items=analysis.get("evidence", []),
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
        recommendedTask=next((item["id"] for item in items if item["recommended"]), None),
    )
