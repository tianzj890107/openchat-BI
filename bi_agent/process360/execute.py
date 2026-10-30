"""S06 — the only Process360 write path.

Execution is Fuxi-todo-only.  Recipient phones are supplied by the Fuxi host at
click time; they are never read from the page, catalog, environment or model
output.  This module does not call any business write API.
"""

from __future__ import annotations

import re
from typing import Any, Iterable, Mapping
import json

from ..integrations.fuxi_todo import (
    DEFAULT_SOURCE_CODE,
    FuxiTodoClient,
    FuxiTodoError,
    make_source_todo_id,
    normalize_item_type,
    normalize_recipients,
    normalize_severity,
)
from .catalog import Process360Catalog
from .models import envelope, gap


_PHONE_LIKE = re.compile(r"(?<!\d)(?:\+?86[- ]?)?1[3-9]\d{9}(?!\d)")


_TASK_TEXT_FIELDS = (
    "title", "content", "evidence", "ownerRef", "ownerName", "solution",
    "taskTemplate", "verification", "severityBasis", "scenario",
)


def _assert_no_phone(text: str) -> None:
    if _PHONE_LIKE.search(text or ""):
        raise ValueError("任务令内容不得包含手机号；接收人由 Fuxi 宿主在点击时提供")


def _assert_task_no_phone(task: Mapping[str, Any]) -> None:
    _assert_no_phone(json.dumps(
        {key: task.get(key) for key in _TASK_TEXT_FIELDS}, ensure_ascii=False
    ))


def send_task_order(
    catalog: Process360Catalog,
    task: Mapping[str, Any],
    recipients: Iterable[str] | str,
    *,
    action_id: str = "",
    canvas_id: str = "",
    source_todo_id: str | None = None,
    client: FuxiTodoClient | None = None,
    source_updated_at: str | None = None,
) -> dict[str, Any]:
    dispatch = dict(task.get("dispatch") or {})
    source = str(dispatch.get("source") or DEFAULT_SOURCE_CODE)
    if source != DEFAULT_SOURCE_CODE:
        raise ValueError(f"Process360 只允许来源 {DEFAULT_SOURCE_CODE}")
    title = str(task.get("title") or "").strip()
    content = str(task.get("content") or "").strip()
    if not title or not content:
        raise ValueError("task title/content are required")
    _assert_task_no_phone(task)
    action = str(action_id or task.get("id") or "").strip()
    if not action:
        raise ValueError("action_id is required")
    if not str(canvas_id or "").strip() and not str(source_todo_id or "").strip():
        raise ValueError("canvas_id or an explicitly scoped source_todo_id is required")
    item_type = normalize_item_type(task.get("item_type") or task.get("itemType"))
    todo_id = source_todo_id or make_source_todo_id(action, canvas_id, item_type)
    normalized_recipients = normalize_recipients(recipients)
    severity = normalize_severity(str(task.get("severity") or "MEDIUM"))
    client = client or FuxiTodoClient()
    create = client.create_risk if item_type == "RISK" else client.create_todo
    try:
        result = create(
            title=title,
            content=content,
            recipients_raw=normalized_recipients,
            action_id=action,
            source_todo_id=todo_id,
            canvas_id=canvas_id,
            severity=severity,
            category=task.get("category") or None,
            due_at=task.get("dueAt") or None,
            owner_ref=task.get("ownerRef") or None,
            owner_name=task.get("ownerName") or None,
            impact_text=str((task.get("evidence") or ""))[:2000] or None,
            evidence=task.get("evidence") or None,
            caliber_meta={
                "scenario": task.get("scenario"),
                "solution": task.get("solution"),
                "taskTemplate": task.get("taskTemplate"),
                "verification": task.get("verification"),
                "severityBasis": task.get("severityBasis"),
                "executionBoundary": dispatch.get("executionBoundary"),
            },
            source_updated_at=source_updated_at,
        )
    except FuxiTodoError as exc:
        message = str(exc)
        status_code = getattr(exc, "status", None)
        definitive_rejection = bool(
            isinstance(status_code, int)
            and 400 <= status_code < 500
            and status_code not in {408, 409, 425, 429}
        )
        configuration_block = not status_code and any(
            marker in message.lower()
            for marker in ("disabled", "not configured", "requires", "must")
        )
        outcome = "blocked" if definitive_rejection or configuration_block else "unknown"
        code = "FUXI_TODO_REJECTED" if definitive_rejection else (
            "FUXI_TODO_CONFIG_BLOCKED" if configuration_block else "FUXI_TODO_UNKNOWN"
        )
        return envelope(
            "S06",
            outcome,
            catalog_id=catalog.catalog_id,
            catalog_version=catalog.version,
            scenario=str(task.get("scenario") or "") or None,
            gaps=[
                gap(
                    code,
                    "Fuxi 明确拒绝" if definitive_rejection else (
                        "Fuxi 配置未就绪" if configuration_block else "Fuxi 执行结果不确定"
                    ),
                    needed="检查 Fuxi 回执；结果不确定时用同一幂等身份安全重试",
                    impact="可能已送达，也可能未创建；不得直接视为失败或另换幂等键",
                    severity="blocking",
                    source="runtime",
                )
            ],
            limitations=[message],
            next_steps=["保留草稿并使用相同 sourceTodoId 与接收人版本重试"],
            receipt=None,
            task=dict(task),
        )
    ok = bool(result.get("ok"))
    subject = "风险条目" if item_type == "RISK" else "待办"
    return envelope(
        "S06",
        "ok" if ok else "blocked",
        catalog_id=catalog.catalog_id,
        catalog_version=catalog.version,
        scenario=str(task.get("scenario") or "") or None,
        gaps=[]
        if ok
        else [
            gap(
                "FUXI_TODO_REJECTED",
                f"Fuxi {subject}被拒绝",
                needed="核对 Fuxi 回执错误",
                impact=f"本次{subject}未创建",
                source="runtime",
            )
        ],
        limitations=[
            "只创建 Fuxi 风险/待办条目；不发送 IM，不执行发运/签单等业务动作。",
            "推送成功只表示 Fuxi 已接收，不代表风险已解除或任务已完成。",
        ],
        next_steps=[
            "在 Fuxi 查看回执与执行状态",
            "风险解除仍需后续证据和复验；任务完成需执行回执",
        ],
        receipt=result,
        task=dict(task),
        itemType=item_type,
        recipientsProvidedByHost=len(normalized_recipients),
    )
