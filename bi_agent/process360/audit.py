"""Per-request step trail for Process360.

Every tool call writes one step row, even when the answer is a pure fact query
that never reaches S04.  The trail is what makes "did the SOP actually run"
answerable without inferring from the model's prose.

The context is one user request inside a Fuxi conversation.  A conversation may
contain several requests, and every request has its own step trail.  Runs,
queries and baselines are attached as references when they exist, so a request,
a query and an analysis run stay distinguishable.
"""

from __future__ import annotations

import json
from typing import Any, Mapping

from .request_context import active_request_context
from .store import Process360Store, digest
_STORE: Process360Store | None = None


def current_request_id() -> str:
    context = active_request_context()
    return context.request_id if context else ""


def store() -> Process360Store:
    global _STORE
    if _STORE is None:
        _STORE = Process360Store()
    return _STORE


def _payload(text: Any) -> dict[str, Any]:
    if not isinstance(text, str):
        return {}
    body = text.strip()
    if not body.startswith("{"):
        return {}
    try:
        parsed = json.loads(body)
    except ValueError:
        return {}
    return parsed if isinstance(parsed, dict) else {}


def _refs(payload: Mapping[str, Any]) -> dict[str, Any]:
    refs = {
        key: payload.get(key)
        for key in ("queryId", "runId", "planId", "draftId", "baselineId", "actionId")
        if payload.get(key)
    }
    info = payload.get("recordsRef")
    if isinstance(info, dict):
        refs["rowCount"] = info.get("rowCount")
        refs["totalRows"] = info.get("totalRows")
        refs["sampleSize"] = info.get("sampleSize")
    baseline = payload.get("dataSnapshot")
    if isinstance(baseline, dict):
        refs["complete"] = baseline.get("complete")
        refs["fullObjectCount"] = baseline.get("fullObjectCount")
    return refs


def record_step(
    tool: str,
    params: Mapping[str, Any],
    output: Any,
    *,
    duration_ms: int = 0,
) -> None:
    """Best-effort audit write; never break a tool call because of logging."""
    try:
        payload = _payload(output)
        redacted = {
            key: value
            for key, value in dict(params or {}).items()
            if key not in {"principal", "principalScope", "__principal"}
        }
        store().save_step(
            request_id=current_request_id() or "unscoped",
            tool=str(tool),
            status=str(payload.get("status") or ""),
            scenario=str(payload.get("scenario") or redacted.get("scenario") or ""),
            input_hash=digest(redacted),
            duration_ms=int(duration_ms),
            rows_returned=int(
                (payload.get("recordsRef") or {}).get("rowCount")
                or len(payload.get("records") or [])
            ),
            refs=_refs(payload),
        )
    except Exception:  # noqa: BLE001 - audit must not mask the real result
        return


def ensure_request(surface: str = "mcp") -> str:
    context = active_request_context()
    request_id = current_request_id() or "unscoped"
    if context is None:
        return request_id
    try:
        store().ensure_request(
            request_id,
            surface=context.surface or surface,
            tenant=context.tenant_id,
            principal=context.principal_id,
            conversation_id=context.conversation_id,
            authorization_version=context.authorization_version,
        )
    except Exception:  # noqa: BLE001
        pass
    return request_id


def request_trail(request_id: str) -> dict[str, Any] | None:
    context = active_request_context()
    if context is None:
        return None
    return store().get_request(
        request_id, tenant=context.tenant_id, principal=context.principal_id
    )
