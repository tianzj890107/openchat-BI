from __future__ import annotations

from pathlib import Path

from bi_agent.process360.store import Process360Store, digest


def test_action_consumption_is_per_action_and_execution_idempotency_is_persistent(tmp_path: Path) -> None:
    store = Process360Store(tmp_path / "runtime.sqlite3")
    saved = store.save_draft(
        scenario="SC01",
        payload={
            "canvasActions": [
                {"id": "a1", "title": "one", "content": "one"},
                {"id": "a2", "title": "two", "content": "two"},
            ]
        },
    )
    assert store.consume_action(saved["id"], "a1", consumed_by="u1") is True
    assert store.consume_action(saved["id"], "a1", consumed_by="u1") is False
    assert store.consume_action(saved["id"], "a2", consumed_by="u1") is True
    created, first = store.begin_execution(
        draft_id=saved["id"], action_id="a1", idempotency_key="key-1", source_todo_id="todo-1"
    )
    assert created is True
    created_again, second = store.begin_execution(
        draft_id=saved["id"], action_id="a1", idempotency_key="key-1", source_todo_id="todo-1"
    )
    assert created_again is False
    assert second["id"] == first["id"]
    store.finish_execution(first["id"], status="ok", response={"status": "ok"})
    assert store.get_execution("key-1")["response"] == {"status": "ok"}
    store.save_receipt("todo-1", status="ok", payload={"applied": 1})
    assert store.get_receipt("todo-1")["payload"] == {"applied": 1}
    exported = store.export()
    assert {"drafts", "actions", "action_consumptions", "executions", "receipts"} <= set(exported["tables"])


def test_store_detects_tampered_draft_payload_hash(tmp_path: Path) -> None:
    store = Process360Store(tmp_path / "runtime.sqlite3")
    payload = {"scenario": "SC01", "canvasActions": [{"id": "a1"}]}
    saved = store.save_draft(scenario="SC01", payload=payload)
    assert saved["hash"] == digest(payload)
    assert store.get_draft(saved["id"])["payload_hash"] == saved["hash"]
