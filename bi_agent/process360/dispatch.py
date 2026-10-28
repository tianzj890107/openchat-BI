"""Page-initiated task-order dispatch.

The standalone Canvas page only sends opaque draft references.  The server
resolves the identity (POC principal or host header), the recipients (from a
server-side mapping) and the task body (from the stored draft).  A caller can
never widen the draft, invent a phone number or claim success without a Fuxi
receipt.

The unified receipt contract is::

    {"schema": "process360.dispatch.v1", "status": "ok|blocked|unconfirmed",
     "accepted": bool, "message": str, "receipt": {...} | null,
     "draftId": str, "actionId": str, "requestId": str}

``status=ok`` is only possible when Fuxi returned a receipt that proves the
todo was applied (or idempotently skipped).
"""

from __future__ import annotations

import json
import os
import time
from typing import Any, Mapping

from ..integrations.fuxi_todo import (
    FuxiTodoClient,
    make_source_todo_id,
    normalize_recipients,
)
from .execute import _assert_no_phone
from .identity import PrincipalScope
from .request_context import active_request_context
from .store import digest


RECEIPT_SCHEMA = "process360.dispatch.v1"
_RECIPIENT_ENV = "PROCESS360_RECIPIENT_MAP"
_ENABLED_ENV = "PROCESS360_PAGE_DISPATCH"
_RECIPIENT_VERSION_ENV = "PROCESS360_RECIPIENT_MAP_VERSION"
_CANVAS_MODE_ENV = "PROCESS360_CANVAS_DISPATCH_MODE"
_CANVAS_RECIPIENT_ENV = "PROCESS360_CANVAS_RECIPIENT"
_TRUSTED_APPROVAL_STATES = {"approved", "host_click_authorized"}


def page_dispatch_enabled() -> bool:
    raw = (os.environ.get(_ENABLED_ENV) or "1").strip().lower()
    return raw not in {"0", "false", "no", "off"}


def all_canvas_actions_dispatchable() -> bool:
    """Temporary POC mode: render every recommendation card as sendable.

    ``trusted`` restores the strict draft-backed behaviour.  The default is
    ``all`` only while the current POC is demonstrating card dispatch; the
    server still creates a draft and validates identity, content and recipient
    before calling Fuxi.
    """

    raw = (os.environ.get(_CANVAS_MODE_ENV) or "all").strip().lower()
    return raw not in {"trusted", "draft", "0", "false", "no", "off"}


def recipient_map() -> dict[str, Any]:
    raw = (os.environ.get(_RECIPIENT_ENV) or "").strip()
    if not raw:
        return {}
    try:
        parsed = json.loads(raw)
    except ValueError as exc:
        raise ValueError(
            "PROCESS360_RECIPIENT_MAP 必须是 JSON 对象，例如 "
            '{"__default__":["18800000000"]}'
        ) from exc
    if not isinstance(parsed, dict):
        raise ValueError("PROCESS360_RECIPIENT_MAP 必须是 JSON 对象")
    return parsed


def resolve_canvas_recipients() -> list[str]:
    """Resolve the single configured POC recipient without page input."""

    mapping = recipient_map()
    key = (os.environ.get(_CANVAS_RECIPIENT_ENV) or "").strip()
    candidates = [key, "__default__"] if key else ["__default__"]
    for candidate in candidates:
        if candidate and candidate in mapping:
            return normalize_recipients(mapping[candidate])
    unique: list[list[str]] = []
    seen: set[tuple[str, ...]] = set()
    for value in mapping.values():
        try:
            normalized = list(normalize_recipients(value))
        except (TypeError, ValueError):
            continue
        fingerprint = tuple(sorted(normalized))
        if fingerprint and fingerprint not in seen:
            seen.add(fingerprint)
            unique.append(normalized)
    if len(unique) == 1:
        return unique[0]
    raise ValueError(
        "临时直发需要唯一的服务端接收人映射；请配置 "
        "PROCESS360_CANVAS_RECIPIENT 指向 PROCESS360_RECIPIENT_MAP 中的键"
    )


def resolve_recipients(draft: Mapping[str, Any], action: Mapping[str, Any]) -> list[str]:
    """Server-side recipient resolution; the page never supplies phones."""
    mapping = recipient_map()
    candidates = [
        action.get("owner_ref"),
        action.get("ownerRef"),
        action.get("id"),
        draft.get("scenario"),
        "__default__",
    ]
    for key in candidates:
        text = str(key or "").strip()
        if text and text in mapping:
            return normalize_recipients(mapping[text])
    raise ValueError(
        "未配置接收人映射（PROCESS360_RECIPIENT_MAP）；任务令未发送，"
        "手机号只能由服务端配置提供"
    )


def _canvas_action(action: Mapping[str, Any]) -> dict[str, Any]:
    """Validate the display-only action sent by a Canvas page."""

    if not isinstance(action, Mapping):
        raise ValueError("action must be an object")
    forbidden = set(action) & {
        "recipients", "recipientsRaw", "recipients_raw", "phone", "mobile",
        "principal", "tenantId", "userId", "grantKind", "canDispatch",
    }
    if forbidden:
        raise ValueError(
            "action must not contain recipient, identity or permission fields: "
            + ", ".join(sorted(forbidden))
        )
    action_id = str(action.get("id") or action.get("actionId") or "").strip()
    title = str(action.get("title") or "").strip()
    content = str(action.get("content") or action.get("markdown") or "").strip()
    if not action_id or len(action_id) > 160:
        raise ValueError("action.id is required and must be at most 160 characters")
    if not title or len(title) > 200:
        raise ValueError("action.title is required and must be at most 200 characters")
    if not content or len(content) > 12000:
        raise ValueError("action.content is required and must be at most 12000 characters")
    evidence = str(action.get("evidence") or "").strip()
    if len(evidence) > 4000:
        raise ValueError("action.evidence must be at most 4000 characters")
    owner_ref = str(action.get("ownerRef") or action.get("owner_ref") or "").strip()
    owner_name = str(action.get("ownerName") or action.get("owner_name") or "").strip()[:200]
    scenario = str(action.get("scenario") or "CANVAS").strip().upper()[:40] or "CANVAS"
    severity = str(action.get("severity") or "MEDIUM").strip().upper()
    if severity not in {"CRITICAL", "HIGH", "MEDIUM", "LOW"}:
        severity = "MEDIUM"
    due_at = str(action.get("dueAt") or action.get("due_at") or "").strip()[:64]
    _assert_no_phone(
        json.dumps(
            [action_id, title, content, evidence, owner_ref, owner_name, scenario, due_at],
            ensure_ascii=False,
        )
    )
    return {
        "id": action_id,
        "title": title,
        "content": content,
        "evidence": evidence,
        "severity": severity,
        "due_at": due_at,
        "owner_ref": owner_ref,
        "owner_name": owner_name,
        "scenario": scenario,
        "source": "boulderai-anaylize-todo",
        "category": str(action.get("category") or "智能分析任务令").strip()[:80],
        "task_template": str(action.get("taskTemplate") or action.get("task_template") or "").strip()[:80],
        "metadata": {"temporaryCanvasDispatch": True},
    }


def _temporary_draft_id(identity: PrincipalScope, action: Mapping[str, Any]) -> str:
    material = {
        "tenant": identity.tenant_id,
        "principal": identity.user_id,
        "action": {
            key: action.get(key)
            for key in ("id", "title", "content", "evidence", "scenario", "owner_ref", "due_at")
        },
    }
    return "canvas-" + digest(material)[:32]


def execution_key(tenant_id: str, draft_id: str, action_id: str) -> str:
    """Stable business idempotency key; requestId is tracing only."""
    tenant = str(tenant_id or "").strip()
    draft = str(draft_id or "").strip()
    action = str(action_id or "").strip()
    if not tenant or not draft or not action:
        raise ValueError("tenantId, draftId and actionId are required for dispatch")
    return f"{tenant}:{draft}:{action}"


def recipient_fingerprint(recipients: list[str]) -> str:
    return digest(
        {
            "recipients": sorted(normalize_recipients(recipients)),
            "mappingVersion": (os.environ.get(_RECIPIENT_VERSION_ENV) or "").strip(),
        }
    )


def _message(gaps: list[Mapping[str, Any]], fallback: str) -> str:
    names = [str(item.get("name") or item.get("impact") or "").strip() for item in gaps or []]
    names = [name for name in names if name]
    return "；".join(names) if names else fallback


def envelope(
    status: str,
    *,
    message: str,
    accepted: bool,
    receipt: Mapping[str, Any] | None = None,
    draft_id: str = "",
    action_id: str = "",
    request_id: str = "",
    gaps: list[Mapping[str, Any]] | None = None,
) -> dict[str, Any]:
    return {
        "schema": RECEIPT_SCHEMA,
        "status": status,
        "accepted": accepted,
        "message": message,
        "receipt": dict(receipt) if receipt else None,
        "draftId": draft_id,
        "actionId": action_id,
        "requestId": request_id,
        "gaps": [dict(item) for item in (gaps or [])],
    }


def dispatch_draft(
    service: Any,
    *,
    draft_id: str,
    draft_hash: str,
    action_id: str,
    request_id: str = "",
    retry: bool = False,
    client: FuxiTodoClient | None = None,
) -> dict[str, Any]:
    if not page_dispatch_enabled():
        return envelope(
            "blocked",
            message="本服务未启用在页面直接下发任务令（PROCESS360_PAGE_DISPATCH=0）",
            accepted=False,
            draft_id=draft_id,
            action_id=action_id,
            request_id=request_id,
        )
    return dispatch_action(
        service,
        draft_id=draft_id,
        draft_hash=draft_hash,
        action_id=action_id,
        request_id=request_id,
        recipients=None,
        retry=retry,
        client=client,
    )


def dispatch_action(
    service: Any,
    *,
    draft_id: str,
    draft_hash: str,
    action_id: str,
    request_id: str = "",
    recipients: list[str] | tuple[str, ...] | None = None,
    principal: Mapping[str, Any] | None = None,
    retry: bool = False,
    client: FuxiTodoClient | None = None,
) -> dict[str, Any]:
    """Single execution path used by Canvas HTTP and MCP TaskOrderCreate."""
    context = active_request_context()
    identity = context.principal if context is not None else None
    if principal is not None:
        supplied = PrincipalScope.from_payload(principal, required=True)
        if identity is not None and supplied.key != identity.key:
            raise ValueError("principal conflicts with the active request context")
        identity = supplied
    if identity is None:
        resolver = getattr(service, "_principal", None)
        identity = resolver(None) if callable(resolver) else PrincipalScope.local()

    if not identity.can_dispatch:
        return envelope(
            "blocked",
            message="当前用户无任务下发权限",
            accepted=False,
            draft_id=draft_id,
            action_id=action_id,
            request_id=request_id,
            gaps=[{
                "code": "DISPATCH_NOT_AUTHORIZED",
                "name": "当前用户无任务下发权限",
                "needed": "宿主授予 canDispatch 或交由有权限人员点击",
                "impact": "未创建待办",
                "severity": "blocking",
                "source": "host",
            }],
        )

    draft = service.store.get_draft(str(draft_id or ""))
    if not draft:
        return envelope(
            "blocked",
            message="任务草稿不存在或已过期，请重新生成建议",
            accepted=False,
            draft_id=draft_id,
            action_id=action_id,
            request_id=request_id,
        )
    action = (draft.get("actions") or {}).get(str(action_id or ""))
    if not action:
        return envelope(
            "blocked",
            message="该建议不属于当前草稿，请重新生成",
            accepted=False,
            draft_id=draft_id,
            action_id=action_id,
            request_id=request_id,
        )
    try:
        resolved_recipients = (
            normalize_recipients(list(recipients))
            if recipients is not None
            else resolve_recipients(draft, action)
        )
    except ValueError as exc:
        return envelope(
            "blocked",
            message=str(exc),
            accepted=False,
            draft_id=draft_id,
            action_id=action_id,
            request_id=request_id,
        )
    result = service.execute_draft(
        draft_id=draft_id,
        draft_hash=draft_hash,
        action_id=action_id,
        recipients=resolved_recipients,
        principal=identity.to_dict(),
        idempotency_key=execution_key(identity.tenant_id, draft_id, action_id),
        recipient_hash=recipient_fingerprint(resolved_recipients),
        retry=retry,
        client=client,
    )
    status = str(result.get("status") or "").lower()
    receipt = result.get("receipt") if isinstance(result.get("receipt"), dict) else None
    applied = receipt and (receipt.get("ok") is True) and (
        int(receipt.get("applied") or 0) + int(receipt.get("skipped") or 0) > 0
    )
    if status in {"ok", "succeeded"} and applied:
        response = envelope(
            "ok",
            message="任务令已创建",
            accepted=True,
            receipt=receipt,
            draft_id=draft_id,
            action_id=action_id,
            request_id=request_id,
        )
    elif status in {"ok", "succeeded"}:
        response = envelope(
            "unconfirmed",
            message="Fuxi 未返回可验证的执行回执，结果待确认",
            accepted=False,
            receipt=receipt,
            draft_id=draft_id,
            action_id=action_id,
            request_id=request_id,
        )
    else:
        gaps = list(result.get("gaps") or [])
        gap_codes = {str(item.get("code") or "") for item in gaps}
        if status == "unknown" or "FUXI_TODO_UNKNOWN" in gap_codes:
            state = "unknown"
            message = "请求可能已送达 Fuxi，执行结果待确认"
        elif status == "rejected" or "FUXI_TODO_REJECTED" in gap_codes:
            state = "rejected"
            message = _message(gaps, "Fuxi 明确拒绝任务令")
        else:
            state = "blocked"
            message = _message(gaps, "任务令未创建")
        response = envelope(
            state,
            message=message,
            accepted=False,
            receipt=receipt,
            draft_id=draft_id,
            action_id=action_id,
            request_id=request_id,
            gaps=gaps,
        )
    if result.get("idempotentReplay"):
        response["idempotentReplay"] = True
    if result.get("executionId"):
        response["executionId"] = result.get("executionId")
    response["sourceTodoId"] = (
        (receipt or {}).get("sourceTodoId")
        or result.get("sourceTodoId")
        or make_source_todo_id(action_id, draft_id)
    )
    return response


def dispatch_canvas_action(
    service: Any,
    *,
    action: Mapping[str, Any],
    draft_id: str = "",
    draft_hash: str = "",
    action_id: str = "",
    request_id: str = "",
    retry: bool = False,
    client: FuxiTodoClient | None = None,
) -> dict[str, Any]:
    """Temporary POC path for every Canvas action card.

    A full, unexpired trusted draft is used as-is.  Cards without one are
    converted server-side into a small draft and are sent through the exact
    same idempotent execution path.  The page never supplies a recipient, and
    the configured single POC recipient is used for every card.
    """

    if not page_dispatch_enabled():
        return envelope(
            "blocked",
            message="本服务未启用在页面直接下发任务令（PROCESS360_PAGE_DISPATCH=0）",
            accepted=False,
            draft_id=draft_id,
            action_id=action_id,
            request_id=request_id,
        )
    if not all_canvas_actions_dispatchable():
        return envelope(
            "blocked",
            message="当前为可信草稿模式；该建议需要重新生成任务草稿",
            accepted=False,
            draft_id=draft_id,
            action_id=action_id,
            request_id=request_id,
        )
    try:
        normalized = _canvas_action(action)
    except ValueError as exc:
        return envelope(
            "blocked",
            message=str(exc),
            accepted=False,
            draft_id=draft_id,
            action_id=action_id,
            request_id=request_id,
        )

    context = active_request_context()
    identity = context.principal if context is not None else None
    if identity is None:
        resolver = getattr(service, "_principal", None)
        identity = resolver(None) if callable(resolver) else PrincipalScope.local()
    if not identity.can_dispatch:
        return envelope(
            "blocked",
            message="当前用户无任务下发权限",
            accepted=False,
            draft_id=draft_id,
            action_id=action_id,
            request_id=request_id,
            gaps=[{
                "code": "DISPATCH_NOT_AUTHORIZED",
                "name": "当前用户无任务下发权限",
                "needed": "宿主授予 canDispatch 或交由有权限人员点击",
                "impact": "未创建待办",
                "severity": "blocking",
                "source": "host",
            }],
        )
    try:
        recipients = resolve_canvas_recipients()
    except ValueError as exc:
        return envelope(
            "blocked",
            message=str(exc),
            accepted=False,
            draft_id=draft_id,
            action_id=action_id,
            request_id=request_id,
        )

    requested_action_id = str(action_id or normalized["id"]).strip()
    existing = service.store.get_draft(str(draft_id or "")) if draft_id else None
    existing_action = bool(existing and requested_action_id in (existing.get("actions") or {}))
    existing_ready = bool(
        existing
        and existing_action
        and not existing.get("expired")
        and str(existing.get("approval_status") or "").lower() in _TRUSTED_APPROVAL_STATES
        and str(existing.get("payload_hash") or "") == str(draft_hash or "")
    )
    if existing_ready:
        return dispatch_action(
            service,
            draft_id=draft_id,
            draft_hash=draft_hash,
            action_id=requested_action_id,
            request_id=request_id,
            recipients=recipients,
            retry=retry,
            client=client,
        )

    temporary_id = _temporary_draft_id(identity, normalized)
    temporary_action_id = str(normalized["id"])
    temporary = service.store.get_draft(temporary_id)
    if temporary and (
        temporary.get("expired")
        or temporary_action_id not in (temporary.get("actions") or {})
    ):
        temporary_id = f"{temporary_id}-{int(time.time() // 3600)}"
        temporary = service.store.get_draft(temporary_id)
    temporary_hash = str((temporary or {}).get("payload_hash") or "")
    if not temporary or temporary_action_id not in (temporary.get("actions") or {}):
        payload = {
            "status": "ok",
            "temporaryCanvasDispatch": True,
            "canvasActions": [normalized],
        }
        saved = service.store.save_draft(
            payload=payload,
            scenario=str(normalized.get("scenario") or "CANVAS"),
            tenant=identity.tenant_id,
            principal=identity.user_id,
            approval_status="host_click_authorized",
            draft_id=temporary_id,
        )
        temporary_hash = str(saved.get("hash") or "")
    result = dispatch_action(
        service,
        draft_id=temporary_id,
        draft_hash=temporary_hash,
        action_id=temporary_action_id,
        request_id=request_id,
        recipients=recipients,
        retry=retry,
        client=client,
    )
    result["temporaryDraft"] = True
    return result
