from __future__ import annotations

import json

import pytest

from bi_agent.process360 import dispatch


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
