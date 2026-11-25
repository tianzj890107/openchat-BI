"""TDD RED: history save/restore for the AgentKit workbench.

A restored conversation must resume the server-side session it was activated
with, and the AgentKit page needs its structured turns (boards, evidence,
ontology hits) back — stored messages alone only carry text (spec §6.1).
"""

from __future__ import annotations

from pathlib import Path
import sys
import tempfile
import unittest
from unittest import mock

from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from bi_agent.web import app as web_app  # noqa: E402
from bi_agent.web.conversations import ConversationStore  # noqa: E402


AGENTKIT_SNAPSHOT = {
    "version": 1,
    "turns": [
        {
            "id": "turn-1",
            "user": "PACK 未签单商机主要涉及哪些客户？",
            "status": "done",
            "assistant": {
                "text": "共 12 家客户。",
                "thinking": "",
                "tools": [
                    {
                        "id": "tool-1",
                        "name": "TableGenerate",
                        "status": "done",
                        "input": '{"title":"明细"}',
                        "output": None,
                        "entities": [{"code": "BO_PACK_OPP_002", "kind": "business_object", "name": "PACK 商机"}],
                        "table": {"title": "明细", "columns": [{"key": "customer", "label": "客户"}], "rows": [["宁德时代"]]},
                        "chart": None,
                        "multiChart": None,
                        "durationMs": 87,
                        "errorCode": "",
                    }
                ],
            },
        }
    ],
}


class StoreSnapshotTests(unittest.TestCase):
    def test_save_persists_the_agentkit_snapshot_and_updates_keep_it(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            store = ConversationStore(tmp)
            summary = store.save(
                mode="data",
                title="PACK 未签单商机",
                messages=[{"role": "user", "content": "hi"}],
                agentkit=AGENTKIT_SNAPSHOT,
            )
            cid = summary["id"]
            record = store.get(cid)
            self.assertEqual(record["agentkit"]["turns"][0]["user"], "PACK 未签单商机主要涉及哪些客户？")

            # A later save without the field (e.g. legacy client) must not drop it.
            store.save(mode="data", title="PACK 未签单商机", messages=[{"role": "user", "content": "hi2"}], cid=cid)
            self.assertEqual(store.get(cid)["agentkit"]["turns"][0]["id"], "turn-1")


class FakeSession:
    def __init__(self) -> None:
        self.messages = []
        self.first_user_question = ""
        self.pending_tool_use_id = None
        self.pending_choice_spec = None
        self._pending_sibling_results = []


class ActivateTests(unittest.TestCase):
    def test_activate_restores_into_the_requested_session_and_returns_it(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            store = ConversationStore(tmp)
            summary = store.save(
                mode="data",
                title="PACK 未签单商机",
                messages=[{"role": "user", "content": [{"type": "text", "text": "hi"}]}],
                agentkit=AGENTKIT_SNAPSHOT,
            )
            cid = summary["id"]
            session = FakeSession()
            client = TestClient(web_app.app)
            with mock.patch.object(web_app, "_require_conversation_store", return_value=store), \
                 mock.patch.object(web_app, "_session_for_mode", return_value=session), \
                 mock.patch.object(web_app, "_ensure_session", return_value=session), \
                 mock.patch.object(web_app, "_history_ontology_entities", return_value=[]):
                response = client.post(f"/api/conversations/{cid}/activate?session_id=agentkit-restore-1")
            self.assertEqual(response.status_code, 200)
            payload = response.json()
            self.assertEqual(payload.get("session_id"), "agentkit-restore-1")
            self.assertTrue(session.messages, "stored messages restored into that session")
            self.assertTrue(payload.get("messages"), "activate returns the stored messages")
            self.assertEqual(payload["agentkit"]["turns"][0]["id"], "turn-1")

            record = store.get(cid)
            self.assertEqual(record["agentkit"]["turns"][0]["id"], "turn-1")


if __name__ == "__main__":
    unittest.main()


class SavePreservesLegacyTests(unittest.TestCase):
    """An AgentKit save must not blank the Pro UI snapshots of the same record."""

    def test_agentkit_save_keeps_messages_html_and_sop(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            store = ConversationStore(tmp)
            session = FakeSession()
            session.messages = [{"role": "user", "content": [{"type": "text", "text": "旧问题"}]}]
            summary = store.save(
                mode="data",
                title="旧会话",
                messages=session.messages,
                chat_html="<div id='chat'/>",
                dashboard_html="<div id='dash'/>",
                ontology_html="<div id='onto'/>",
                tools_html="<div id='tools'/>",
                llm_html="<div id='llm'/>",
                sop_steps=[{"content": "旧步骤", "status": "done"}],
            )
            cid = summary["id"]
            client = TestClient(web_app.app)
            with mock.patch.object(web_app, "_require_conversation_store", return_value=store), \
                 mock.patch.object(web_app, "_session_for_mode", return_value=session):
                response = client.post("/api/conversations/save", json={
                    "mode": "data",
                    "title": "旧会话",
                    "cid": cid,
                    "session_id": "agentkit-legacy-1",
                    "agentkit": AGENTKIT_SNAPSHOT,
                })
            self.assertEqual(response.status_code, 200)
            record = store.get(cid)
            self.assertEqual(record["chat_html"], "<div id='chat'/>")
            self.assertEqual(record["dashboard_html"], "<div id='dash'/>")
            self.assertEqual(record["ontology_html"], "<div id='onto'/>")
            self.assertEqual(record["tools_html"], "<div id='tools'/>")
            self.assertEqual(record["llm_html"], "<div id='llm'/>")
            self.assertEqual(record["sop_steps"][0]["content"], "旧步骤")
            self.assertTrue(record["messages"], "stored messages are not blanked")
            self.assertEqual(record["agentkit"]["turns"][0]["id"], "turn-1")
