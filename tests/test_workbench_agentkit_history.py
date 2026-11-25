"""TDD RED: history save/restore for the AgentKit workbench.

A restored conversation must resume the server-side session it was activated
with, and the AgentKit page needs its structured turns (boards, evidence,
ontology hits) back — stored messages alone only carry text (spec §6.1).
"""

from __future__ import annotations

from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
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

    def test_new_agentkit_record_saves_the_server_session_source(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            store = ConversationStore(tmp)
            session = FakeSession()
            session.messages = [{"role": "user", "content": "来源验证"}]
            session_source = SimpleNamespace(
                remote_ontology=SimpleNamespace(repository_id="test-repo"),
                use_doris=True, db_path="", retrieval_mode="graph", graph_path="",
                doris_api_url="http://fixture.invalid", doris_jdbc_url="", doris_driver="", doris_username="fixture-user",
                doris_database="test_schema",
            )
            with mock.patch.object(web_app, "_require_conversation_store", return_value=store), \
                 mock.patch.object(web_app, "_session_for_mode", return_value=session), \
                 mock.patch.object(web_app, "_source_for_session", return_value=session_source) as source:
                response = TestClient(web_app.app).post("/api/conversations/save", json={
                    "session_id": "agentkit-source-binding", "agentkit": AGENTKIT_SNAPSHOT,
                })
            self.assertEqual(response.status_code, 200)
            record = store.get(response.json()["id"])
            self.assertEqual(record["source_config"]["ontology"], "__metaerp_repository__:test-repo")
            self.assertEqual(record["source_config"]["database"], "__doris_repository__:test-repo")
            self.assertEqual(record["source_config"]["retrieval_mode"], "graph")
            self.assertNotIn("doris_api_url", record["source_config"])
            self.assertNotIn("doris_username", record["source_config"])
            source.assert_called_once_with("agentkit-source-binding")

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


def test_agentkit_history_preserves_all_structured_turns():
    from bi_agent.web.conversations import bounded_agentkit

    turns = [{"id": f"turn-{index}", "user": "经营问题", "assistant": {"tools": []}} for index in range(1, 46)]
    assert bounded_agentkit({"version": 1, "turns": turns})["turns"] == turns


def test_report_save_and_activate_restore_attachments_and_follow_up_context(tmp_path, monkeypatch):
    store = ConversationStore(tmp_path)
    session = FakeSession()
    session.messages = [{"role": "user", "content": "核对报表"}]
    sessions = {"report-original": (session, ["r1", "r2"], False)}
    records = {rid: {"id": rid, "filename": f"{rid}.pdf"} for rid in ("r1", "r2")}
    source = SimpleNamespace(
        remote_ontology=None, ontology_path="", use_doris=False, db_path="",
        retrieval_mode="semantic", graph_path="", doris_api_url="", doris_jdbc_url="",
        doris_driver="", doris_username="", doris_database="",
    )
    monkeypatch.setattr(web_app, "_require_conversation_store", lambda: store)
    monkeypatch.setattr(web_app, "_require_report_store", lambda: records)
    monkeypatch.setattr(web_app, "_build_report_session", lambda *_: FakeSession())
    monkeypatch.setattr(web_app, "_ensure_session", lambda _: FakeSession())
    monkeypatch.setattr(web_app, "_source_for_session", lambda _: source)
    monkeypatch.setattr(web_app, "_history_ontology_entities", lambda *_: [])
    monkeypatch.setattr(web_app, "_set_report_context", lambda key, session, ids, with_db: sessions.update({
        key: (session, ids, with_db),
    }))
    monkeypatch.setattr(web_app, "_report_context_state", lambda key: sessions.get(key, (None, [], True)))
    monkeypatch.setattr(web_app, "_session_for_mode", lambda mode, key: sessions.get(key, (None,))[0])
    client = TestClient(web_app.app)
    saved = client.post("/api/conversations/save", json={
        "mode": "report", "session_id": "report-original", "agentkit": AGENTKIT_SNAPSHOT,
    })
    assert saved.status_code == 200
    cid = saved.json()["id"]
    assert store.get(cid)["agentkit"]["reportContext"] == {"reportIds": ["r1", "r2"], "withDb": False, "generated": False}
    opened = client.post(f"/api/conversations/{cid}/activate?session_id=report-reopened")
    assert opened.status_code == 200
    assert opened.json()["report_restore_error"] == ""
    restored, ids, with_db = sessions["report-reopened"]
    assert restored.messages == session.messages
    assert ids == ["r1", "r2"]
    assert with_db is False


def test_report_upload_parses_pdf_and_word_into_the_recent_list(tmp_path, monkeypatch):
    from io import BytesIO
    import pytest

    pymupdf = pytest.importorskip("pymupdf")
    docx = pytest.importorskip("docx")
    from bi_agent.report.store import ReportStore

    with pymupdf.open() as pdf:
        pdf.new_page().insert_text((30, 45), "Operating revenue 100")
        pdf_data = pdf.tobytes()
    word_data = BytesIO()
    word = docx.Document()
    word.add_paragraph("Operating revenue 120")
    word.save(word_data)

    store = ReportStore(str(tmp_path))
    monkeypatch.setattr(web_app, "_require_report_store", lambda: store)
    client = TestClient(web_app.app)
    for filename, payload in (("summary.pdf", pdf_data), ("detail.docx", word_data.getvalue())):
        upload = client.post("/api/report/upload", files={"file": (filename, payload)})
        assert upload.status_code == 200, upload.text
        assert upload.json()["text_length"] > 0
    files = client.get("/api/report/list").json()["items"]
    assert {item["filename"] for item in files} == {"summary.pdf", "detail.docx"}


def test_unified_attachments_keep_conversation_identity_and_engine_messages(tmp_path, monkeypatch):
    store = ConversationStore(tmp_path)
    key = "unified-attachment-test"
    initial = FakeSession()
    original_messages = [{"role": "user", "content": "先看经营数据"}]
    initial.messages = list(original_messages)
    initial.first_user_question = "先看经营数据"
    ordinary = {key: initial}
    reports = {}
    records = {"r1": {"id": "r1", "filename": "经营简报.pdf"}}
    monkeypatch.setattr(web_app.STATE, "report_store", records)
    source = SimpleNamespace(
        remote_ontology=None, ontology_path="", use_doris=False, db_path="",
        retrieval_mode="semantic", graph_path="", doris_api_url="", doris_jdbc_url="",
        doris_driver="", doris_username="", doris_database="",
    )
    monkeypatch.setattr(web_app, "_require_conversation_store", lambda: store)
    monkeypatch.setattr(web_app, "_require_report_store", lambda: records)
    monkeypatch.setattr(web_app, "_build_report_session", lambda *_: FakeSession())
    monkeypatch.setattr(web_app, "_ensure_session", lambda key: ordinary.setdefault(key, FakeSession()))
    monkeypatch.setattr(web_app, "_source_for_session", lambda _: source)
    monkeypatch.setattr(web_app, "_history_ontology_entities", lambda *_: [])
    monkeypatch.setattr(web_app, "_set_report_context", lambda key, session, ids, with_db: reports.update({
        key: (session, ids, with_db),
    }))
    monkeypatch.setattr(web_app, "_report_context_state", lambda key: reports.get(key, (None, [], True)))
    monkeypatch.setattr(web_app, "_session_for_mode", lambda mode, key:
        reports.get(key, (None,))[0] if mode == "report" else ordinary.get(key))
    client = TestClient(web_app.app)
    saved = client.post("/api/conversations/save", json={"session_id": key, "agentkit": AGENTKIT_SNAPSHOT})
    assert saved.status_code == 200
    cid = saved.json()["id"]
    attach = client.put("/api/report/attachments", json={
        "session_id": key, "report_ids": ["r1"], "with_db": False, "from_mode": "data",
    })
    assert attach.status_code == 200, attach.text
    assert attach.json()["has_session"]
    report_session, ids, with_db = reports[key]
    assert report_session.messages == original_messages
    assert (ids, with_db) == (["r1"], False)
    stale = client.put("/api/report/attachments", json={
        "session_id": key, "report_ids": [], "with_db": True, "from_mode": "data",
    })
    assert stale.status_code == 409
    assert reports[key] == (report_session, ["r1"], False)
    report_session.messages.append({"role": "assistant", "content": "报表核对结果"})
    saved = client.post("/api/conversations/save", json={
        "session_id": key, "cid": cid, "mode": "data", "runtime_mode": "report", "agentkit": AGENTKIT_SNAPSHOT,
    })
    assert saved.json()["id"] == cid
    assert store.get(cid)["messages"] == report_session.messages
    assert store.get(cid)["agentkit"]["runtimeMode"] == "report"
    opened = client.post(f"/api/conversations/{cid}/activate?session_id=attachment-restore&unified=true")
    assert opened.status_code == 200
    assert opened.json()["runtime_mode"] == "report"
    assert opened.json()["report_context"]["active_reports"][0]["filename"] == "经营简报.pdf"
    assert reports["attachment-restore"][1:] == (["r1"], False)
    detach = client.put("/api/report/attachments", json={
        "session_id": key, "report_ids": [], "with_db": False, "from_mode": "report",
    })
    assert detach.status_code == 200
    assert not detach.json()["has_session"]
    assert ordinary[key].messages == report_session.messages
    saved_again = client.post("/api/conversations/save", json={
        "session_id": key, "cid": cid, "mode": "data", "runtime_mode": "data", "agentkit": AGENTKIT_SNAPSHOT,
    })
    assert saved_again.json()["id"] == cid
    assert "reportContext" not in store.get(cid)["agentkit"]
    assert len(client.get("/api/conversations").json()["conversations"]) == 1
