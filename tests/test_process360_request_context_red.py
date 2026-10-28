from __future__ import annotations

from pathlib import Path

import pytest

from bi_agent.process360.identity import (
    PrincipalScope,
    active_principal_payload,
    reset_active_principal,
    set_active_principal,
)
from bi_agent.process360.request_context import (
    active_request_context,
    reset_request_context,
    resolve_request_context,
    set_request_context,
)


PRINCIPAL = {
    "tenantId": "t1",
    "userId": "u1",
    "grantKind": "all",
    "authorizationVersion": "auth-v1",
}


def test_request_context_is_the_single_source_for_identity_and_trace_ids() -> None:
    context = resolve_request_context(
        principal=PRINCIPAL,
        conversation_id="conv-1",
        request_id="req-1",
        surface="mcp",
    )
    assert context.principal_id == "u1"
    assert context.tenant_id == "t1"
    assert context.grant_kind == "all"
    assert context.authorization_version == "auth-v1"
    assert context.conversation_id == "conv-1"
    assert context.request_id == "req-1"
    assert context.surface == "mcp"

    token = set_request_context(context)
    principal_token = set_active_principal(PRINCIPAL)
    try:
        assert active_request_context() == context
        assert active_principal_payload()["userId"] == "u1"
    finally:
        reset_active_principal(principal_token)
        reset_request_context(token)


def test_request_context_rejects_unknown_surface_and_missing_request_id() -> None:
    with pytest.raises(ValueError, match="surface"):
        resolve_request_context(principal=PRINCIPAL, request_id="req", surface="browser")
    with pytest.raises(ValueError, match="requestId"):
        resolve_request_context(principal=PRINCIPAL, request_id="", surface="web")


def test_http_dispatch_uses_the_resolved_canvas_context(monkeypatch) -> None:
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from bi_agent.web import mcp_endpoint

    captured = {}

    def fake_dispatch(service, **kwargs):
        context = active_request_context()
        captured.update(
            {
                "principal": context.principal.to_dict() if context else None,
                "conversationId": context.conversation_id if context else None,
                "requestId": context.request_id if context else None,
                "surface": context.surface if context else None,
                "kwargs": kwargs,
            }
        )
        return {
            "schema": "process360.dispatch.v1",
            "status": "blocked",
            "accepted": False,
            "message": "captured",
            "receipt": None,
            "draftId": kwargs["draft_id"],
            "actionId": kwargs["action_id"],
            "requestId": kwargs["request_id"],
        }

    monkeypatch.setattr(mcp_endpoint, "dispatch_draft", fake_dispatch)
    app = FastAPI()
    app.include_router(
        mcp_endpoint.build_mcp_router(
            get_source=lambda: None,
            build_doris=lambda *args, **kwargs: None,
            get_cwd=lambda: ".",
            executor_factory=lambda source: {},
            request_principal=lambda request: PRINCIPAL,
        )
    )

    response = TestClient(app).post(
        "/api/process360/task-orders",
        headers={"x-fuxi-conversation-id": "conv-1"},
        json={
            "draftId": "draft-1",
            "draftHash": "hash-1",
            "actionId": "action-1",
            "requestId": "click-1",
        },
    )
    assert response.status_code == 200
    assert captured["principal"]["userId"] == "u1"
    assert captured["conversationId"] == "conv-1"
    assert captured["requestId"] == "click-1"
    assert captured["surface"] == "canvas"


@pytest.mark.parametrize(
    "forbidden",
    [
        {"principal": PRINCIPAL},
        {"tenantId": "t1"},
        {"userId": "u1"},
        {"grantKind": "all"},
        {"authorizationVersion": "forged"},
        {"canDispatch": True},
    ],
)
def test_http_dispatch_rejects_identity_or_permission_fields_from_the_page(forbidden) -> None:
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from bi_agent.web import mcp_endpoint

    app = FastAPI()
    app.include_router(
        mcp_endpoint.build_mcp_router(
            get_source=lambda: None,
            build_doris=lambda *args, **kwargs: None,
            get_cwd=lambda: ".",
            executor_factory=lambda source: {},
            request_principal=lambda request: PRINCIPAL,
        )
    )
    response = TestClient(app).post(
        "/api/process360/task-orders",
        json={
            "draftId": "draft-1",
            "draftHash": "hash-1",
            "actionId": "action-1",
            "requestId": "click-1",
            **forbidden,
        },
    )
    assert response.status_code == 400


def test_audit_trail_lookup_is_scoped_to_the_current_principal(tmp_path: Path) -> None:
    from bi_agent.process360 import audit
    from bi_agent.process360.store import Process360Store

    store = Process360Store(tmp_path / "runtime.sqlite3")
    store.ensure_request(
        "req-1",
        surface="mcp",
        tenant="t1",
        principal="u1",
        conversation_id="conv-1",
        authorization_version="auth-v1",
    )
    assert store.get_request("req-1", tenant="t1", principal="u1")["id"] == "req-1"
    assert store.get_request("req-1", tenant="t1", principal="u2") is None
    assert store.get_request("missing", tenant="t1", principal="u1") is None
    assert audit is not None
