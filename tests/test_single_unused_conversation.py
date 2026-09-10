"""Contract tests for collapsing unused "新会话" drafts.

RED group B of `docs/specs/ontology-repository-allowlist-and-single-draft-conversation.md`.

Clicking 新会话 repeatedly must not accumulate empty sidebar entries: the
persistence layer may create at most one unused draft per mode, and the history
list may surface at most one. Real conversations and legacy records must never
be deleted or hidden.
"""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient

from bi_agent.web.app import STATE, app as web_app
from bi_agent.web.conversations import ConversationStore


def _record_files(store: ConversationStore) -> list[Path]:
    return [p for p in store.root.glob("*.json") if p.name != "history_index.json"]


def _empty_draft(store: ConversationStore, cid: str | None = None) -> dict:
    """Simulate one 新会话 click: an empty snapshot for a fresh client id."""
    return store.save(mode="data", title="未命名对话", messages=[], chat_html="", cid=cid)


class SingleUnusedConversationTests(unittest.TestCase):
    def test_repeated_new_chat_clicks_keep_one_sidebar_draft(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            store = ConversationStore(temp_dir)
            ids = [_empty_draft(store, cid=f"aaaa000{i}")["id"] for i in range(5)]
            self.assertEqual(len(set(ids)), 1, "every click must converge on one draft id")
            self.assertEqual(len(store.list("data")), 1)
            self.assertEqual(len(_record_files(store)), 1, "no extra draft files may be created")

    def test_empty_save_reuses_the_existing_draft_id(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            store = ConversationStore(temp_dir)
            first = _empty_draft(store, cid="aaaa0001")
            second = _empty_draft(store, cid="bbbb0002")
            self.assertEqual(second["id"], first["id"])
            self.assertEqual(store.list("data")[0]["id"], first["id"])
            self.assertEqual(first["title"], "未命名对话")

    def test_used_draft_is_not_reused_by_the_next_new_chat(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            store = ConversationStore(temp_dir)
            draft = _empty_draft(store, cid="aaaa0001")
            store.save(
                mode="data",
                title="采购金额是多少",
                messages=[
                    {"role": "user", "content": "采购金额是多少"},
                    {"role": "assistant", "content": "采购金额为 100"},
                ],
                cid=draft["id"],
            )
            next_draft = _empty_draft(store, cid="bbbb0002")
            self.assertNotEqual(next_draft["id"], draft["id"])
            listed = store.list("data")
            self.assertEqual(len(listed), 2)
            self.assertEqual({item["id"] for item in listed}, {draft["id"], next_draft["id"]})
            self.assertEqual(len(_record_files(store)), 2)

    def test_drafts_are_scoped_per_mode(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            store = ConversationStore(temp_dir)
            data_draft = _empty_draft(store, cid="aaaa0001")
            report_draft = store.save(mode="report", title="未命名对话", messages=[], cid="bbbb0002")
            self.assertEqual(len(store.list("data")), 1)
            self.assertEqual(len(store.list("report")), 1)
            self.assertNotEqual(data_draft["id"], report_draft["id"])
            self.assertEqual(len(store.list()), 2)

    def test_snapshot_with_any_content_is_never_treated_as_a_draft(self) -> None:
        """A rendered chat with no user question is still user-visible content."""
        with tempfile.TemporaryDirectory() as temp_dir:
            store = ConversationStore(temp_dir)
            saved = store.save(
                mode="data",
                title="未命名对话",
                messages=[],
                chat_html="<div class='msg msg-user'><div class='msg-body'>采购金额是多少</div></div>",
                cid="aaaa0001",
            )
            self.assertEqual(len(store.list("data")), 1)
            next_draft = _empty_draft(store, cid="bbbb0002")
            self.assertNotEqual(next_draft["id"], saved["id"])
            self.assertEqual(len(store.list("data")), 2)

    def test_real_conversations_are_never_collapsed(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            store = ConversationStore(temp_dir)
            first = store.save(
                mode="data", title="问题一",
                messages=[{"role": "user", "content": "问题一"}], cid="aaaa0001",
            )
            second = store.save(
                mode="data", title="问题二",
                messages=[{"role": "user", "content": "问题二"}], cid="bbbb0002",
            )
            listed = store.list("data")
            self.assertEqual({item["id"] for item in listed}, {first["id"], second["id"]})
            self.assertEqual(len(_record_files(store)), 2)

    def test_legacy_empty_drafts_are_hidden_but_not_deleted(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            store = ConversationStore(temp_dir)
            for index, cid in enumerate(("aaaa0001", "aaaa0002", "aaaa0003")):
                (store.root / f"{cid}.json").write_text(
                    json.dumps({
                        "id": cid,
                        "mode": "data",
                        "schema_version": 2,
                        "title": "未命名对话",
                        "first_user_question": "",
                        "messages": [],
                        "created_at": f"2026-09-0{index + 1}T10:00:00+08:00",
                        "updated_at": f"2026-09-0{index + 1}T10:00:00+08:00",
                    }),
                    encoding="utf-8",
                )
            reopened = ConversationStore(temp_dir)
            listed = reopened.list("data")
            self.assertEqual(len(listed), 1, "only the newest unused draft is surfaced")
            self.assertEqual(listed[0]["id"], "aaaa0003")
            self.assertEqual(len(_record_files(reopened)), 3, "legacy drafts stay on disk")
            self.assertIsNotNone(reopened.get("aaaa0001"), "hidden drafts remain restorable")

    def test_legacy_index_without_the_draft_flag_is_backfilled(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            store = ConversationStore(temp_dir)
            for index, cid in enumerate(("aaaa0001", "aaaa0002")):
                (store.root / f"{cid}.json").write_text(
                    json.dumps({
                        "id": cid,
                        "mode": "data",
                        "schema_version": 2,
                        "title": "未命名对话",
                        "first_user_question": "",
                        "messages": [],
                        "created_at": f"2026-09-0{index + 1}T10:00:00+08:00",
                        "updated_at": f"2026-09-0{index + 1}T10:00:00+08:00",
                    }),
                    encoding="utf-8",
                )
            store.list("data")
            index_path = store.root / "history_index.json"
            payload = json.loads(index_path.read_text(encoding="utf-8"))
            for entry in payload["conversations"].values():
                entry.pop("is_draft", None)
            index_path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")

            reopened = ConversationStore(temp_dir)
            listed = reopened.list("data")
            self.assertEqual([item["id"] for item in listed], ["aaaa0002"])
            backfilled = json.loads(index_path.read_text(encoding="utf-8"))
            self.assertTrue(
                all("is_draft" in entry for entry in backfilled["conversations"].values()),
                "the legacy index must be backfilled with the draft flag",
            )
            self.assertEqual(len(_record_files(reopened)), 2)

    def test_conversations_api_returns_single_unused_draft(self) -> None:
        previous = STATE.conversation_store
        try:
            with tempfile.TemporaryDirectory() as temp_dir, patch(
                "bi_agent.web.app._session_for_mode", return_value=None
            ):
                STATE.conversation_store = ConversationStore(temp_dir)
                client = TestClient(web_app)
                for cid in ("aaaa0001", "bbbb0002", "cccc0003"):
                    response = client.post("/api/conversations/save", json={
                        "mode": "data", "title": "未命名对话", "cid": cid,
                        "chat_html": "", "source_config": {},
                    })
                    self.assertEqual(response.status_code, 200)
                listed = client.get("/api/conversations?mode=data").json()["conversations"]
                self.assertEqual(len(listed), 1)
                self.assertEqual(listed[0]["title"], "未命名对话")
        finally:
            STATE.conversation_store = previous


if __name__ == "__main__":
    unittest.main()
