from __future__ import annotations

import json
from pathlib import Path

from bi_agent.process360.catalog import Process360Catalog
from bi_agent.process360.service import Process360Service
from bi_agent.process360.store import Process360Store
from bi_agent.integrations.fuxi_todo import FuxiTodoError
from tests.test_process360_engine import FakeDB

ROOT = Path(__file__).resolve().parents[1]
PRINCIPAL = {
    "tenantId": "tenant-1",
    "userId": "user-1",
    "grantKind": "all",
    "authorizationVersion": "test-auth-v1",
    "canDispatch": True,
    "source": "host",
}


class Client:
    def __init__(self) -> None:
        self.calls = []

    def create_todo(self, **kwargs):
        self.calls.append(kwargs)
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


def draft(tmp_path: Path):
    return service(tmp_path).draft(
        scenario="SC01",
        principal=PRINCIPAL,
        owner_ref="u1",
        owner_name="张真",
    )


def test_draft_is_server_trusted_and_click_ready(tmp_path: Path) -> None:
    result = draft(tmp_path)
    assert result["status"] == "ok"
    assert result["draftId"] and result["draftHash"] and result["runId"]
    assert result["approvalStatus"] == "host_click_authorized"
    for action in result["canvasActions"]:
        assert action["draftId"] == result["draftId"]
        assert action["draftHash"] == result["draftHash"]
        assert action["actionId"] == action["id"]
        assert action["approvalStatus"] == "host_click_authorized"
        assert action["dispatchTool"] == "TaskOrderCreate"
    assert "18837823993" not in json.dumps(result, ensure_ascii=False)


def test_button_click_creates_one_fuxi_todo_per_action_and_is_idempotent(tmp_path: Path) -> None:
    bundle = draft(tmp_path)
    svc = service(tmp_path)
    client = Client()
    first_action = bundle["canvasActions"][0]
    first = svc.execute_draft(
        draft_id=bundle["draftId"],
        draft_hash=bundle["draftHash"],
        action_id=first_action["id"],
        recipients=["18837823993"],
        principal=PRINCIPAL,
        client=client,
    )
    replay = svc.execute_draft(
        draft_id=bundle["draftId"],
        draft_hash=bundle["draftHash"],
        action_id=first_action["id"],
        recipients=["18837823993"],
        principal=PRINCIPAL,
        client=client,
    )
    second_action = bundle["canvasActions"][1]
    second = svc.execute_draft(
        draft_id=bundle["draftId"],
        draft_hash=bundle["draftHash"],
        action_id=second_action["id"],
        recipients=["18837823993"],
        principal=PRINCIPAL,
        client=client,
    )
    assert first["status"] == "ok" and second["status"] == "ok"
    assert replay["idempotentReplay"] is True
    assert len(client.calls) == 2
    assert client.calls[0]["title"] == first_action["title"]
    assert client.calls[0]["recipients_raw"] == ["18837823993"]
    exported = svc.store.export()
    assert "18837823993" not in json.dumps(exported, ensure_ascii=False)


def test_draft_cannot_be_dispatched_by_another_user_or_with_tampered_hash(tmp_path: Path) -> None:
    bundle = draft(tmp_path)
    svc = service(tmp_path)
    other = {**PRINCIPAL, "userId": "user-2"}
    action = bundle["canvasActions"][0]
    denied = svc.execute_draft(
        draft_id=bundle["draftId"], draft_hash=bundle["draftHash"], action_id=action["id"],
        recipients=["18837823993"], principal=other, client=Client(),
    )
    assert denied["status"] == "blocked"
    tampered = svc.execute_draft(
        draft_id=bundle["draftId"], draft_hash="bad", action_id=action["id"],
        recipients=["18837823993"], principal=PRINCIPAL, client=Client(),
    )
    assert tampered["status"] == "blocked"


def test_progress_reads_only_current_users_execution_receipts(tmp_path: Path) -> None:
    bundle = draft(tmp_path)
    svc = service(tmp_path)
    action = bundle["canvasActions"][0]
    svc.execute_draft(
        draft_id=bundle["draftId"], draft_hash=bundle["draftHash"], action_id=action["id"],
        recipients=["18837823993"], principal=PRINCIPAL, client=Client(),
    )
    own = svc.progress(principal=PRINCIPAL)
    other = svc.progress(principal={**PRINCIPAL, "userId": "user-2"})
    assert own["status"] == "partial" and own["tasks"]
    assert other["status"] == "not_applicable" and not other["tasks"]


def test_network_failure_retry_reuses_the_same_execution_key(tmp_path: Path) -> None:
    class FlakyClient(Client):
        def create_todo(self, **kwargs):
            self.calls.append(kwargs)
            if len(self.calls) == 1:
                raise FuxiTodoError("temporary network failure")
            return {
                "ok": True,
                "sourceTodoId": kwargs["source_todo_id"],
                "batchRef": "batch-2",
                "applied": 1,
                "skipped": 0,
                "errors": [],
            }

    bundle = draft(tmp_path)
    svc = service(tmp_path)
    action = bundle["canvasActions"][0]
    client = FlakyClient()
    failed = svc.execute_draft(
        draft_id=bundle["draftId"], draft_hash=bundle["draftHash"], action_id=action["id"],
        recipients=["18837823993"], principal=PRINCIPAL, client=client,
    )
    retried = svc.execute_draft(
        draft_id=bundle["draftId"], draft_hash=bundle["draftHash"], action_id=action["id"],
        recipients=["18837823993"], principal=PRINCIPAL, client=client, retry=True,
    )
    assert failed["status"] == "unknown"
    assert retried["status"] == "ok" and retried["idempotentReplay"] is False
    assert len(client.calls) == 2
    assert client.calls[0]["source_todo_id"] == client.calls[1]["source_todo_id"]


def test_in_progress_dispatch_is_not_sent_twice_without_explicit_retry(tmp_path: Path) -> None:
    bundle = draft(tmp_path)
    svc = service(tmp_path)
    action = bundle["canvasActions"][0]
    key = "draft-action-key"
    created, execution = svc.store.begin_execution(
        draft_id=bundle["draftId"],
        action_id=action["id"],
        idempotency_key=key,
        source_todo_id="analytics-in-progress",
    )
    assert created is True
    assert svc.store.consume_action(
        bundle["draftId"], action["id"], consumed_by="tenant-1:user-1"
    ) is True
    client = Client()
    blocked = svc.execute_draft(
        draft_id=bundle["draftId"],
        draft_hash=bundle["draftHash"],
        action_id=action["id"],
        recipients=["18837823993"],
        principal=PRINCIPAL,
        idempotency_key=key,
        client=client,
    )
    assert blocked["status"] == "blocked"
    assert blocked["gaps"][0]["code"] == "DISPATCH_IN_PROGRESS"
    assert client.calls == []
    retried = svc.execute_draft(
        draft_id=bundle["draftId"],
        draft_hash=bundle["draftHash"],
        action_id=action["id"],
        recipients=["18837823993"],
        principal=PRINCIPAL,
        idempotency_key=key,
        retry=True,
        client=client,
    )
    assert retried["status"] == "ok"
    assert len(client.calls) == 1
    assert svc.store.get_execution(key)["id"] == execution["id"]
    assert svc.store.get_action_consumption(bundle["draftId"], action["id"]) is not None


def test_retry_before_consumption_claims_the_action(tmp_path: Path) -> None:
    bundle = draft(tmp_path)
    svc = service(tmp_path)
    action = bundle["canvasActions"][0]
    key = "crash-before-consume"
    created, _execution = svc.store.begin_execution(
        draft_id=bundle["draftId"],
        action_id=action["id"],
        idempotency_key=key,
        source_todo_id="analytics-before-consume",
    )
    assert created is True
    client = Client()
    result = svc.execute_draft(
        draft_id=bundle["draftId"],
        draft_hash=bundle["draftHash"],
        action_id=action["id"],
        recipients=["18837823993"],
        principal=PRINCIPAL,
        idempotency_key=key,
        retry=True,
        client=client,
    )
    assert result["status"] == "ok"
    assert len(client.calls) == 1
    assert svc.store.get_action_consumption(bundle["draftId"], action["id"]) is not None


def test_opaque_refs_do_not_trigger_phone_guard(tmp_path: Path) -> None:
    svc = service(tmp_path)
    client = Client()
    result = svc.execute(
        task={
            "id": "a1",
            "title": "核查排产",
            "content": "复核排产证据。",
            "evidence": "候选原因，未确认",
            "draftId": "13912345678",
            "runId": "1793760363",
            "expiresAt": 1793760363.726253,
        },
        recipients=["18837823993"],
        canvas_id="run-1",
        client=client,
    )
    assert result["status"] == "ok"
    assert len(client.calls) == 1
    assert client.calls[0]["content"] == "复核排产证据。"
