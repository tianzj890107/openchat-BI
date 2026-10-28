"""Per-request step trail for Process360.

Every tool call writes one step row, even when the answer is a pure fact query
that never reaches S04.  The trail is what makes "did the SOP actually run"
answerable without inferring from the model's prose.

The request id is the MCP session (one Fuxi conversation).  Runs, queries and
baselines are attached as references when they exist, so a request, a query and
an analysis run stay distinguishable.
"""

from __future__ import annotations

import contextvars
import json
from typing import Any, Mapping

from .store import Process360Store, digest

_REQUEST_ID: contextvars.ContextVar[str] = contextvars.ContextVar(
    "process360_request_id", default=""
)
_STORE: Process360Store | None = None


def set_request_id(value: str):
    return _REQUEST_ID.set(str(value or ""))


def reset_request_id(token: Any) -> None:
    _REQUEST_ID.reset(token)


def current_request_id() -> str:
    return _REQUEST_ID.get()


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
    request_id = current_request_id() or "unscoped"
    try:
        from .identity import active_principal_payload

        principal = active_principal_payload() or {}
        store().ensure_request(
            request_id,
            surface=surface,
            tenant=str(principal.get("tenantId") or ""),
            principal=str(principal.get("userId") or ""),
        )
    except Exception:  # noqa: BLE001
        pass
    return request_id
