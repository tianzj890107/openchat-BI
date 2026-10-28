from __future__ import annotations

import json
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from bi_agent.integrations.fuxi_todo import FuxiTodoError
from bi_agent.process360 import dispatch
from bi_agent.process360.catalog import Process360Catalog
from bi_agent.process360.request_context import resolve_request_context, set_request_context, reset_request_context
from bi_agent.process360.service import Process360Service
from bi_agent.process360.store import Process360Store
from tests.test_process360_engine import FakeDB

ROOT = Path(__file__).resolve().parents[1]
PRINCIPAL = {
    "tenantId": "t1",
    "userId": "u1",
    "grantKind": "all",
    "authorizationVersion": "auth-v1",
    "canDispatch": True,
}


class ReceiptClient:
    def __init__(self, *, error: Exception | None = None):
        self.calls = []
        self.error = error

    def create_todo(self, **kwargs):
        self.calls.append(kwargs)
        if self.error is not None:
            raise self.error
        return {
            "ok": True,
            "sourceTodoId": kwargs["source_todo_id"],
            "batchRef": "batch-1",
            "applied": 1,
            "skipped": 0,
            "errors": [],
        }


def service(tmp_path: Path) -> Process360Service:
    return Process360Service(
        catalog=Process360Catalog.from_project(ROOT),
        db=FakeDB(),
        store=Process360Store(tmp_path / "runtime.sqlite3"),
        cwd=ROOT,
    )


def draft(svc: Process360Service) -> dict:
    return svc.draft(
        scenario="SC01",
        principal=PRINCIPAL,
        owner_ref="u1",
        owner_name="张真",
    )


def test_page_and_mcp_share_one_idempotent_execution(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setenv("PROCESS360_RECIPIENT_MAP", json.dumps({"u1": ["18800000001"]}))
    svc = service(tmp_path)
    bundle = draft(svc)
    action = bundle["canvasActions"][0]
    client = ReceiptClient()
    context = resolve_request_context(
        principal=PRINCIPAL,
        conversation_id="conv-1",
        request_id="click-page",
        surface="canvas",
    )
    tokens = set_request_context(context)
    try:
        first = dispatch.dispatch_draft(
            svc,
            draft_id=bundle["draftId"],
            draft_hash=bundle["draftHash"],
            action_id=action["id"],
            request_id="click-page",
            client=client,
        )
        second = dispatch.dispatch_action(
            svc,
            draft_id=bundle["draftId"],
            draft_hash=bundle["draftHash"],
            action_id=action["id"],
            request_id="click-mcp",
            recipients=["18800000001"],
            client=client,
        )
    finally:
        reset_request_context(tokens)
    assert first["status"] == "ok" and first["accepted"] is True
    assert second["status"] == "ok" and second.get("idempotentReplay") is True
    assert len(client.calls) == 1
    key = dispatch.execution_key("t1", bundle["draftId"], action["id"])
    execution = svc.store.get_execution(key)
    assert execution is not None
    assert client.calls[0]["source_todo_id"] == f"analytics-{bundle['draftId']}-{action['id']}"


def test_atomic_claim_prevents_two_concurrent_senders(tmp_path: Path) -> None:
    svc = service(tmp_path)
    bundle = draft(svc)
    action = bundle["canvasActions"][0]
    key = dispatch.execution_key("t1", bundle["draftId"], action["id"])

    def claim(_index: int):
        return svc.store.claim_execution(
            draft_id=bundle["draftId"],
            action_id=action["id"],
            idempotency_key=key,
            source_todo_id=f"analytics-{bundle['draftId']}-{action['id']}",
            consumed_by="t1:u1",
        )[0]

    with ThreadPoolExecutor(max_workers=8) as pool:
        outcomes = list(pool.map(claim, range(8)))
    assert outcomes.count("created") == 1
    assert svc.store.get_action_consumption(bundle["draftId"], action["id"]) is not None


def test_ambiguous_network_result_is_unknown_and_retry_reuses_the_same_identity(tmp_path: Path) -> None:
    svc = service(tmp_path)
    bundle = draft(svc)
    action = bundle["canvasActions"][0]
    client = ReceiptClient(error=FuxiTodoError("connection reset after request write"))

    first = dispatch.dispatch_action(
        svc,
        draft_id=bundle["draftId"],
        draft_hash=bundle["draftHash"],
        action_id=action["id"],
        request_id="req-1",
        recipients=["18800000001"],
        principal=PRINCIPAL,
        client=client,
    )
    assert first["status"] == "unknown"
    assert first["accepted"] is False

    client.error = None
    retried = dispatch.dispatch_action(
        svc,
        draft_id=bundle["draftId"],
        draft_hash=bundle["draftHash"],
        action_id=action["id"],
        request_id="req-2",
        recipients=["18800000001"],
        principal=PRINCIPAL,
        retry=True,
        client=client,
    )
    assert retried["status"] == "ok"
    assert len(client.calls) == 2
    assert client.calls[0]["source_todo_id"] == client.calls[1]["source_todo_id"]


def test_retry_with_changed_recipient_mapping_is_blocked(tmp_path: Path) -> None:
    svc = service(tmp_path)
    bundle = draft(svc)
    action = bundle["canvasActions"][0]
    first_client = ReceiptClient(error=FuxiTodoError("timeout"))
    first = dispatch.dispatch_action(
        svc,
        draft_id=bundle["draftId"],
        draft_hash=bundle["draftHash"],
        action_id=action["id"],
        request_id="req-1",
        recipients=["18800000001"],
        principal=PRINCIPAL,
        client=first_client,
    )
    assert first["status"] == "unknown"

    second_client = ReceiptClient()
    blocked = dispatch.dispatch_action(
        svc,
        draft_id=bundle["draftId"],
        draft_hash=bundle["draftHash"],
        action_id=action["id"],
        request_id="req-2",
        recipients=["18800000002"],
        principal=PRINCIPAL,
        retry=True,
        client=second_client,
    )
    assert blocked["status"] == "blocked"
    assert "RECIPIENT_MAPPING_CHANGED" in {item["code"] for item in blocked["gaps"]}
    assert second_client.calls == []


def test_request_id_never_changes_the_business_idempotency_key(tmp_path: Path) -> None:
    svc = service(tmp_path)
    bundle = draft(svc)
    action = bundle["canvasActions"][0]
    client = ReceiptClient()
    for request_id in ("r1", "r2", "r3"):
        dispatch.dispatch_action(
            svc,
            draft_id=bundle["draftId"],
            draft_hash=bundle["draftHash"],
            action_id=action["id"],
            request_id=request_id,
            recipients=["18800000001"],
            principal=PRINCIPAL,
            client=client,
        )
    assert len(client.calls) == 1
    executions = svc.store.list_executions(draft_id=bundle["draftId"])
    assert len(executions) == 1
