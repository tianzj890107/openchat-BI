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
    todo_id = source_todo_id or make_source_todo_id(action, canvas_id)
    normalized_recipients = normalize_recipients(recipients)
    severity = normalize_severity(str(task.get("severity") or "MEDIUM"))
    client = client or FuxiTodoClient()
    try:
        result = client.create_todo(
            title=title,
            content=content,
            recipients_raw=normalized_recipients,
            action_id=action,
            source_todo_id=todo_id,
            canvas_id=canvas_id,
            severity=severity,
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
        return envelope(
            "S06",
            "blocked",
            catalog_id=catalog.catalog_id,
            catalog_version=catalog.version,
            scenario=str(task.get("scenario") or "") or None,
            gaps=[
                gap(
                    "FUXI_TODO_FAILED",
                    "Fuxi 待办提交失败",
                    needed="检查 Fuxi 服务与回执后用同一幂等键重试",
                    impact="任务令未创建；业务动作未执行",
                    severity="blocking",
                    source="runtime",
                )
            ],
            limitations=[str(exc)],
            next_steps=["保留草稿并使用相同 sourceTodoId 重试，避免重复待办"],
            receipt=None,
            task=dict(task),
        )
    ok = bool(result.get("ok"))
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
                "Fuxi 待办被拒绝",
                needed="核对回执错误",
                impact="任务令未创建",
                source="runtime",
            )
        ],
        limitations=["只创建 Fuxi 待办；不发送 IM，不执行发运/签单等业务动作。"],
        next_steps=["在 Fuxi 待办查看回执与执行状态", "按复验计划在 S07 验收"],
        receipt=result,
        task=dict(task),
        recipientsProvidedByHost=len(normalized_recipients),
    )
