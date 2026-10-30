from __future__ import annotations

import json

import pytest

from bi_agent.process360 import dispatch
from bi_agent.process360.request_context import (
    reset_request_context,
    resolve_request_context,
    set_request_context,
)
from bi_agent.process360.store import Process360Store


DRAFT = {
    "scenario": "SC01",
    "actions": {"SC01-TK01": {"id": "SC01-TK01", "owner_ref": "u1"}},
}


class FakeStore:
    def __init__(self, draft):
        self.draft = draft
        self.executions = {}

    def get_draft(self, draft_id):
        return self.draft if draft_id == "draft-1" else None

    def get_execution(self, key):
        return self.executions.get(key)


class FakeService:
    def __init__(self, result):
        self.store = FakeStore(DRAFT)
        self.result = result
        self.calls = []

    def execute_draft(self, **kwargs):
        self.calls.append(kwargs)
        return self.result


def call(service):
    return dispatch.dispatch_draft(
        service,
        draft_id="draft-1",
        draft_hash="hash-1",
        action_id="SC01-TK01",
        request_id="req-1",
    )


def test_success_requires_a_verifiable_receipt(monkeypatch) -> None:
    monkeypatch.setenv("PROCESS360_RECIPIENT_MAP", json.dumps({"u1": ["18800000001"]}))
    service = FakeService({"status": "ok", "receipt": {}})
    result = call(service)
    assert result["status"] == "unconfirmed"
    assert result["accepted"] is False
    assert service.calls[0]["recipients"] == ["18800000001"]


def test_receipt_proves_creation_only_when_applied(monkeypatch) -> None:
    monkeypatch.setenv("PROCESS360_RECIPIENT_MAP", json.dumps({"u1": ["18800000001"]}))
    receipt = {"ok": True, "applied": 1, "skipped": 0, "sourceTodoId": "analytics-x"}
    result = call(FakeService({"status": "ok", "receipt": receipt}))
    assert result["status"] == "ok"
    assert result["accepted"] is True
    assert result["receipt"]["sourceTodoId"] == "analytics-x"


def test_blocked_dispatch_reports_the_server_gap(monkeypatch) -> None:
    monkeypatch.setenv("PROCESS360_RECIPIENT_MAP", json.dumps({"u1": ["18800000001"]}))
    gap = {"code": "DISPATCH_NOT_AUTHORIZED", "name": "当前用户无任务下发权限"}
    result = call(FakeService({"status": "blocked", "gaps": [gap], "receipt": None}))
    assert result["status"] == "blocked"
    assert result["accepted"] is False
    assert "无任务下发权限" in result["message"]


def test_recipients_come_from_server_config_only(monkeypatch) -> None:
    monkeypatch.delenv("PROCESS360_RECIPIENT_MAP", raising=False)
    service = FakeService({"status": "ok", "receipt": {}})
    result = call(service)
    assert result["status"] == "blocked"
    assert "PROCESS360_RECIPIENT_MAP" in result["message"]
    assert service.calls == []


def test_dispatch_can_be_switched_off(monkeypatch) -> None:
    monkeypatch.setenv("PROCESS360_PAGE_DISPATCH", "0")
    monkeypatch.setenv("PROCESS360_RECIPIENT_MAP", json.dumps({"u1": ["18800000001"]}))
    service = FakeService({"status": "ok", "receipt": {}})
    result = call(service)
    assert result["status"] == "blocked"
    assert service.calls == []


def test_page_dispatch_uses_the_server_principal(monkeypatch) -> None:
    monkeypatch.setenv("PROCESS360_RECIPIENT_MAP", json.dumps({"__default__": ["18800000002"]}))
    receipt = {"ok": True, "applied": 1, "skipped": 0, "sourceTodoId": "analytics-y"}
    service = FakeService({"status": "ok", "receipt": receipt})
    call(service)
    assert service.calls[0]["principal"]["userId"] == "local"
    assert service.calls[0]["idempotency_key"] == "local:draft-1:SC01-TK01"


def test_dispatch_action_blocks_permission_before_calling_the_service() -> None:
    service = FakeService({"status": "ok", "receipt": {}})
    result = dispatch.dispatch_action(
        service,
        draft_id="draft-1",
        draft_hash="hash-1",
        action_id="SC01-TK01",
        request_id="req-denied",
        recipients=["18800000001"],
        principal={
            "tenantId": "t1",
            "userId": "u1",
            "grantKind": "all",
            "authorizationVersion": "auth-v1",
            "canDispatch": False,
        },
    )
    assert result["status"] == "blocked"
    assert result["accepted"] is False
    assert "DISPATCH_NOT_AUTHORIZED" in {item["code"] for item in result["gaps"]}
    assert service.calls == []


def test_canvas_recipient_uses_the_single_configured_identity(monkeypatch) -> None:
    monkeypatch.setenv(
        "PROCESS360_RECIPIENT_MAP",
        json.dumps({"owner-a": ["18800000003"]}),
    )
    assert dispatch.resolve_canvas_recipients() == ["18800000003"]


def test_canvas_recipient_requires_an_explicit_key_when_mapping_has_multiple_people(
    monkeypatch,
) -> None:
    monkeypatch.setenv(
        "PROCESS360_RECIPIENT_MAP",
        json.dumps({"u1": ["18800000001"], "u2": ["18800000002"]}),
    )
    with pytest.raises(ValueError, match="PROCESS360_CANVAS_RECIPIENT"):
        dispatch.resolve_canvas_recipients()


def test_canvas_recommendation_creates_one_temporary_draft_and_reuses_it(
    tmp_path, monkeypatch
) -> None:
    monkeypatch.setenv(
        "PROCESS360_RECIPIENT_MAP",
        json.dumps({"owner-a": ["18800000003"]}),
    )
    monkeypatch.setenv("PROCESS360_CANVAS_DISPATCH_MODE", "all")

    class Service:
        def __init__(self) -> None:
            self.store = Process360Store(tmp_path / "runtime.sqlite3")
            self.calls = []

        def execute_draft(self, **kwargs):
            self.calls.append(kwargs)
            return {
                "status": "ok",
                "receipt": {
                    "ok": True,
                    "applied": 1,
                    "skipped": 0,
                    "sourceTodoId": "analytics-temp",
                },
            }

    service = Service()
    context = resolve_request_context(
        principal={
            "tenantId": "t1",
            "userId": "u1",
            "grantKind": "all",
            "canDispatch": True,
        },
        request_id="click-temp",
        surface="canvas",
    )
    token = set_request_context(context)
    action = {
        "id": "a1",
        "title": "核实回款",
        "content": "由财务复核逾期账户。",
        "evidence": "应收明细",
        "severity": "HIGH",
        "verificationStatus": "unverified",
        "metadata": {"verified": True, "verificationStatus": "verified", "keep": "ok"},
    }
    try:
        first = dispatch.dispatch_canvas_action(
            service,
            action=action,
            action_id="a1",
            request_id="click-temp",
        )
        second = dispatch.dispatch_canvas_action(
            service,
            action=action,
            action_id="a1",
            request_id="click-temp-2",
        )
    finally:
        reset_request_context(token)
    assert first["status"] == "ok" and first["accepted"] is True
    assert first["temporaryDraft"] is True
    assert first["verificationStatus"] == "unverified"
    assert first["sourceKind"] == "page_direct"
    assert first["draftId"].startswith("canvas-")
    assert second["draftId"] == first["draftId"]
    assert service.calls[0]["recipients"] == ["18800000003"]
    draft = service.store.get_draft(first["draftId"])
    assert draft and "a1" in draft["actions"]
    assert draft["approval_status"] == "host_click_authorized"
    assert "未经过服务端证据校验" in draft["actions"]["a1"]["content"]
    assert draft["actions"]["a1"]["verification_status"] == "unverified"
    assert draft["actions"]["a1"]["metadata"]["verificationStatus"] == "unverified"
    assert "verified" not in draft["actions"]["a1"]["metadata"]
    assert draft["actions"]["a1"]["metadata"]["keep"] == "ok"


def test_canvas_recommendation_rejects_phone_content(monkeypatch) -> None:
    monkeypatch.setenv(
        "PROCESS360_RECIPIENT_MAP",
        json.dumps({"owner-a": ["18800000003"]}),
    )
    service = FakeService({"status": "ok", "receipt": {}})
    result = dispatch.dispatch_canvas_action(
        service,
        action={"id": "a1", "title": "联系", "content": "拨打 18800000001"},
        action_id="a1",
    )
    assert result["status"] == "blocked"
    assert "手机号" in result["message"]
    assert service.calls == []


def test_canvas_direct_send_cannot_claim_verified_root_cause(monkeypatch) -> None:
    monkeypatch.setenv("PROCESS360_RECIPIENT_MAP", json.dumps({"shenkang": ["18800000003"]}))
    service = FakeService({"status": "ok", "receipt": {}})
    result = dispatch.dispatch_canvas_action(
        service,
        action={"id": "a1", "title": "风险", "content": "已确认根因", "verificationStatus": "verified"},
        action_id="a1",
    )
    assert result["status"] == "blocked"
    assert "已验证" in result["message"]
    assert service.calls == []


def test_canvas_direct_send_rejects_item_type_mismatch(monkeypatch) -> None:
    monkeypatch.setenv("PROCESS360_RECIPIENT_MAP", json.dumps({"shenkang": ["18800000003"]}))
    service = FakeService({"status": "ok", "receipt": {}})
    result = dispatch.dispatch_canvas_action(
        service,
        action={"id": "a1", "title": "处置", "content": "跟进", "item_type": "TODO"},
        action_id="a1",
        expected_item_type="RISK",
    )
    assert result["status"] == "blocked"
    assert "类型不一致" in result["message"]
    assert service.calls == []
