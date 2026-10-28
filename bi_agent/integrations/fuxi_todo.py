"""Fuxi risk/todo source integration.

The Fuxi control service exposes a source-owned todo mirror.  This module is the
single translation layer from an accepted analysis action to the API contract in
``API/risk-todo-source-api.md``.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Iterable, Mapping
from urllib.error import HTTPError, URLError
from urllib.request import ProxyHandler, Request, build_opener


DEFAULT_CONTROL_BASE_URL = "http://172.16.5.69:8080"
DEFAULT_SOURCE_CODE = "boulderai-anaylize-todo"
DEFAULT_CATEGORY = "智能分析任务令"
DEFAULT_RISK_CATEGORY = "智能分析风险"
VALID_ITEM_TYPES = ("RISK", "TODO")
VALID_SEVERITIES = ("CRITICAL", "HIGH", "MEDIUM", "LOW")
LEVEL_TO_SEVERITY = {
    "ALERT": "HIGH",
    "WARNING": "MEDIUM",
    "CRITICAL": "CRITICAL",
    "HIGH": "HIGH",
    "MEDIUM": "MEDIUM",
    "LOW": "LOW",
}


class FuxiTodoError(RuntimeError):
    """Raised when Fuxi cannot accept a todo request."""

    def __init__(self, message: str, *, status: int | None = None,
                 payload: Mapping[str, Any] | None = None) -> None:
        super().__init__(message)
        self.status = status
        self.payload = dict(payload or {})


@dataclass(frozen=True)
class FuxiTodoConfig:
    base_url: str = DEFAULT_CONTROL_BASE_URL
    source_code: str = DEFAULT_SOURCE_CODE
    category: str = DEFAULT_CATEGORY
    timeout_seconds: float = 10.0
    enabled: bool = True

    @classmethod
    def from_env(cls) -> "FuxiTodoConfig":
        raw_enabled = os.environ.get("FUXI_TODO_ENABLED")
        enabled = True
        if raw_enabled is not None:
            enabled = raw_enabled.strip().lower() not in {"0", "false", "no", "off"}
        try:
            timeout = float(os.environ.get("FUXI_TODO_TIMEOUT_SECONDS", "10"))
        except ValueError:
            timeout = 10.0
        return cls(
            base_url=(os.environ.get("FUXI_CONTROL_BASE_URL") or DEFAULT_CONTROL_BASE_URL).strip().rstrip("/"),
            source_code=(os.environ.get("FUXI_SOURCE_CODE") or DEFAULT_SOURCE_CODE).strip(),
            category=(os.environ.get("FUXI_TODO_CATEGORY") or DEFAULT_CATEGORY).strip(),
            timeout_seconds=max(0.5, min(timeout, 120.0)),
            enabled=enabled,
        )


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _utc_iso(value: str | datetime | None, *, field: str, required: bool = False) -> str | None:
    if value is None or (isinstance(value, str) and not value.strip()):
        if required:
            raise ValueError(f"{field} is required")
        return None
    if isinstance(value, datetime):
        parsed = value
    else:
        text = str(value).strip()
        try:
            parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
        except ValueError as exc:
            raise ValueError(f"{field} must be ISO 8601") from exc
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    parsed = parsed.astimezone(timezone.utc).replace(microsecond=0)
    if not 2000 <= parsed.year < 2100:
        raise ValueError(f"{field} is outside the supported range")
    return parsed.strftime("%Y-%m-%dT%H:%M:%SZ")


def normalize_recipient(value: str) -> str:
    text = re.sub(r"[^0-9+]", "", str(value or "").strip())
    if text.startswith("+86"):
        text = text[3:]
    elif text.startswith("86") and len(text) > 11:
        text = text[2:]
    if not re.fullmatch(r"\d{5,20}", text):
        raise ValueError("invalid recipient phone")
    return text


def normalize_recipients(values: Iterable[str] | str) -> list[str]:
    if isinstance(values, str):
        values = [values]
    result: list[str] = []
    seen: set[str] = set()
    for value in values:
        phone = normalize_recipient(value)
        if phone not in seen:
            seen.add(phone)
            result.append(phone)
    if not result:
        raise ValueError("recipients_raw must contain at least one phone number")
    return result


def normalize_severity(value: str | None) -> str:
    text = str(value or "MEDIUM").strip().upper()
    severity = LEVEL_TO_SEVERITY.get(text, text)
    if severity not in VALID_SEVERITIES:
        raise ValueError(f"severity must be one of {list(VALID_SEVERITIES)}")
    return severity


def normalize_item_type(value: str | None) -> str:
    item_type = str(value or "TODO").strip().upper()
    if item_type not in VALID_ITEM_TYPES:
        raise ValueError(f"item_type must be one of {list(VALID_ITEM_TYPES)}")
    return item_type


def make_source_todo_id(
    action_id: str, canvas_id: str = "", item_type: str = "TODO"
) -> str:
    action = str(action_id or "").strip()
    if not action:
        raise ValueError("action_id is required")
    canvas = str(canvas_id or "").strip() or "analysis"
    kind = normalize_item_type(item_type)
    prefix = "analytics-risk" if kind == "RISK" else "analytics"
    raw = f"{prefix}-{canvas}-{action}"
    stable = re.sub(r"[^A-Za-z0-9_.:-]+", "-", raw).strip("-")
    if stable != raw or len(stable) > 200:
        digest = hashlib.sha256(raw.encode("utf-8")).hexdigest()[:20]
        return stable[:179] + "-" + digest
    return stable


def _evidence(value: Any) -> list[Any]:
    if value is None:
        return []
    if isinstance(value, list):
        return value
    if isinstance(value, dict):
        return [value]
    return [{"type": "text", "text": str(value)}]


_PHONE_LIKE = re.compile(r"(?<!\d)(?:\+?86[- ]?)?1[3-9]\d{9}(?!\d)")


def _public_error(value: Any) -> Any:
    if isinstance(value, str):
        return _PHONE_LIKE.sub("[redacted]", value)
    if isinstance(value, list):
        return [_public_error(item) for item in value]
    if isinstance(value, dict):
        return {str(key): ("[redacted]" if str(key).lower() in {"recipientsraw", "phone", "mobile"}
                           else _public_error(item)) for key, item in value.items()}
    return value


class FuxiTodoClient:
    def __init__(self, config: FuxiTodoConfig | None = None) -> None:
        self.config = config or FuxiTodoConfig.from_env()

    def _post(self, path: str, payload: Mapping[str, Any]) -> dict[str, Any]:
        if not self.config.enabled:
            raise FuxiTodoError("Fuxi todo integration is disabled")
        if not self.config.base_url:
            raise FuxiTodoError("FUXI_CONTROL_BASE_URL is not configured")
        request = Request(
            f"{self.config.base_url}{path}",
            data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
            headers={
                "Content-Type": "application/json; charset=utf-8",
                "Accept": "application/json",
                "x-fuxi-source": self.config.source_code,
            },
            method="POST",
        )
        opener = build_opener(ProxyHandler({}))
        try:
            with opener.open(request, timeout=self.config.timeout_seconds) as response:
                raw = response.read().decode("utf-8", errors="replace")
        except HTTPError as exc:
            raw = exc.read().decode("utf-8", errors="replace")
            parsed: dict[str, Any] = {}
            try:
                candidate = json.loads(raw)
                if isinstance(candidate, dict):
                    parsed = candidate
            except json.JSONDecodeError:
                parsed = {"raw": raw}
            raise FuxiTodoError(
                f"Fuxi todo request failed with HTTP {exc.code}",
                status=exc.code,
                payload=parsed,
            ) from exc
        except URLError as exc:
            raise FuxiTodoError(f"Fuxi todo service unavailable: {exc.reason}") from exc
        try:
            parsed = json.loads(raw or "{}")
        except json.JSONDecodeError as exc:
            raise FuxiTodoError("Fuxi todo service returned invalid JSON") from exc
        if not isinstance(parsed, dict):
            raise FuxiTodoError("Fuxi todo service returned a non-object response")
        return parsed

    def create_item(
        self,
        *,
        title: str,
        content: str,
        recipients_raw: Iterable[str] | str,
        action_id: str,
        source_todo_id: str | None = None,
        canvas_id: str = "",
        severity: str | None = None,
        category: str | None = None,
        due_at: str | datetime | None = None,
        owner_ref: str | None = None,
        owner_name: str | None = None,
        impact_text: str | None = None,
        evidence: Any = None,
        caliber_meta: Mapping[str, Any] | None = None,
        source_updated_at: str | datetime | None = None,
        item_type: str = "TODO",
    ) -> dict[str, Any]:
        title = str(title or "").strip()
        content = str(content or "").strip()
        if not title:
            raise ValueError("title is required")
        if len(title) > 200:
            raise ValueError("title must be at most 200 characters")
        if not content:
            raise ValueError("content is required")
        recipients = normalize_recipients(recipients_raw)
        severity_value = normalize_severity(severity)
        item_type_value = normalize_item_type(item_type)
        default_category = (
            DEFAULT_RISK_CATEGORY if item_type_value == "RISK" else self.config.category
        )
        category_value = str(category or default_category).strip()
        if not category_value:
            raise ValueError("category is required")
        todo_id = source_todo_id or make_source_todo_id(
            action_id, canvas_id, item_type_value
        )
        updated_at = _utc_iso(source_updated_at, field="sourceUpdatedAt") or utc_now()
        due_value = _utc_iso(due_at, field="dueAt")
        metadata = dict(caliber_meta or {})
        metadata.setdefault("actionId", str(action_id))
        if canvas_id:
            metadata.setdefault("canvasId", str(canvas_id))
        item: dict[str, Any] = {
            "sourceTodoId": todo_id,
            "title": title,
            "severity": severity_value,
            "itemType": item_type_value,
            "category": category_value,
            "sourceStatus": "OPEN",
            "sourceUpdatedAt": updated_at,
            "recipientsRaw": recipients,
            "dueAt": due_value,
            "description": content,
            "impactText": str(impact_text or "").strip() or None,
            "ownerRef": str(owner_ref or "").strip() or None,
            "ownerName": str(owner_name or "").strip() or None,
            "evidence": _evidence(evidence),
            "activity": [{
                "at": updated_at,
                "text": "智能分析生成风险条目"
                if item_type_value == "RISK"
                else "智能分析生成任务令",
            }],
            "caliberMeta": metadata or None,
        }
        batch_prefix = "analytics-risk" if item_type_value == "RISK" else "analytics"
        batch_ref = f"{batch_prefix}-{todo_id}-{uuid.uuid4().hex[:12]}"
        result = self._post("/source/todo-batches", {
            "batchRef": batch_ref[:200],
            "items": [item],
        })
        errors = result.get("errors") if isinstance(result.get("errors"), list) else []
        return {
            "ok": not errors and (int(result.get("applied") or 0) + int(result.get("skipped") or 0) > 0),
            "source": "fuxi",
            "sourceTodoId": todo_id,
            "batchRef": batch_ref,
            "applied": int(result.get("applied") or 0),
            "skipped": int(result.get("skipped") or 0),
            "errors": _public_error(errors),
        }

    def create_todo(self, **kwargs: Any) -> dict[str, Any]:
        """Backward-compatible TODO entry point."""
        kwargs["item_type"] = "TODO"
        return self.create_item(**kwargs)

    def create_risk(self, **kwargs: Any) -> dict[str, Any]:
        """Create a Fuxi RISK item through the same source-owned mirror."""
        kwargs["item_type"] = "RISK"
        return self.create_item(**kwargs)

    def update_status(
        self,
        *,
        source_todo_id: str,
        source_status: str,
        source_updated_at: str | datetime | None = None,
        event_type: str = "STATUS_CHANGED",
    ) -> dict[str, Any]:
        todo_id = str(source_todo_id or "").strip()
        if not todo_id:
            raise ValueError("source_todo_id is required")
        status = str(source_status or "").strip().upper()
        if status not in {"OPEN", "DONE", "ARCHIVED"}:
            raise ValueError("source_status must be OPEN, DONE or ARCHIVED")
        event = str(event_type or "STATUS_CHANGED").strip().upper()
        if event not in {"STATUS_CHANGED", "DELETED"}:
            raise ValueError("event_type must be STATUS_CHANGED or DELETED")
        updated_at = _utc_iso(source_updated_at, field="sourceUpdatedAt", required=True)
        result = self._post("/source/todo-status-events", {
            "events": [{
                "sourceTodoId": todo_id,
                "eventType": event,
                "sourceStatus": status,
                "sourceUpdatedAt": updated_at,
            }]
        })
        errors = result.get("errors") if isinstance(result.get("errors"), list) else []
        return {
            "ok": not errors and (int(result.get("applied") or 0) + int(result.get("skipped") or 0) > 0),
            "source": "fuxi",
            "sourceTodoId": todo_id,
            "applied": int(result.get("applied") or 0),
            "skipped": int(result.get("skipped") or 0),
            "errors": _public_error(errors),
        }
