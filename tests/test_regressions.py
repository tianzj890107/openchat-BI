"""Offline regression tests for the BI web/LLM integration.

These tests deliberately mock the provider stream. They validate conversion,
failure handling and persistence without making any Qwen/Anthropic request.
"""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi import HTTPException
from fastapi.testclient import TestClient

from bi_agent.llm import provider, provider_qwen
from bi_agent.llm.provider_deepseek import _convert_messages as convert_deepseek
from bi_agent.llm.provider_qwen import _convert_messages as convert_qwen
from bi_agent.ontology.store import OntologyStore
from bi_agent.report.parser import ParseResult
from bi_agent.report.store import ReportStore
from bi_agent.tools.sql_tools import _format_rows, _validate_sql
from bi_agent.tools.chart_tools import _echarts_option, _write_standalone_html
from bi_agent.web.app import STATE, _cwd_file, app, get_sources_endpoint
from bi_agent.web.conversations import ConversationStore
from bi_agent.web.session import WebSession
from open_claude.agent_def import AgentDef


class OfflineRegressionTests(unittest.TestCase):
    def test_chart_theme_follows_ui_spec(self) -> None:
        option = _echarts_option({
            "chart_type": "bar",
            "title": "收入",
            "x_axis": ["一月"],
            "series": [{"name": "金额", "data": [1]}],
            "source_note": "M001",
        })
        self.assertEqual(option["color"][:4], ["#0B7FF3", "#E8B339", "#28C79D", "#F05A5A"])
        self.assertIn("PingFang SC", option["textStyle"]["fontFamily"])
        self.assertEqual(option["tooltip"]["backgroundColor"], "#FFFFFF")
        self.assertEqual(option["xAxis"]["axisLine"]["lineStyle"]["color"], "#D9D9E3")
        self.assertNotIn("graphic", option)

        with tempfile.TemporaryDirectory() as temp_dir:
            out = Path(temp_dir) / "chart.html"
            _write_standalone_html(option, out, "收入")
            html = out.read_text(encoding="utf-8")
            self.assertIn("background: #F7F7F8", html)
            self.assertIn('"PingFang SC", "SF Pro Display"', html)

    def test_openai_compatible_conversion_preserves_images_and_tools(self) -> None:
        messages = [
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": "看这张图"},
                    {
                        "type": "image",
                        "source": {
                            "type": "base64",
                            "media_type": "image/png",
                            "data": "AAAA",
                        },
                    },
                ],
            },
            {
                "role": "assistant",
                "content": [{"type": "tool_use", "id": "t1", "name": "SQLRun", "input": {}}],
            },
            {
                "role": "user",
                "content": [{"type": "tool_result", "tool_use_id": "t1", "content": "ok"}],
            },
        ]
        for converter in (convert_qwen, convert_deepseek):
            converted = converter(messages, "system")
            self.assertEqual(converted[1]["content"][1]["type"], "image_url")
            self.assertEqual(converted[2]["role"], "assistant")
            self.assertEqual(converted[3]["role"], "tool")

    def test_quota_fallback_is_provider_mock_only(self) -> None:
        calls: list[str] = []

        def fake_stream(**kwargs):
            calls.append(kwargs["model_id"])
            if len(calls) == 1:
                yield {"type": "error", "error": "429 quota exceeded"}
            else:
                yield {"type": "text_delta", "text": "ok"}
                yield {"type": "message_end", "stop_reason": "end_turn", "usage": {}}

        with patch.object(provider_qwen, "stream", fake_stream):
            events = list(provider.stream_message([], "system", None, "qwen-configured", 256, 0.1))
        self.assertTrue(any(event.get("type") == "model_fallback" for event in events))
        self.assertEqual(events[-1]["type"], "message_end")
        self.assertGreaterEqual(len(calls), 2)

    def test_provider_error_does_not_emit_false_done_or_save_partial_assistant(self) -> None:
        def fake_stream(*_args, **_kwargs):
            yield {"type": "error", "error": "mock provider failure"}

        with patch("bi_agent.web.session.stream_message", fake_stream):
            session = WebSession("/tmp", AgentDef("test", tools=[]), OntologyStore())
            events = list(session.generate_turn("test"))
        self.assertIn("error", [event["type"] for event in events])
        self.assertNotIn("done", [event["type"] for event in events])
        self.assertEqual(len(session.messages), 1)

    def test_persistence_and_file_ids_reject_traversal(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            conversations = ConversationStore(temp_dir)
            record = conversations.save(
                mode="data",
                title="test",
                messages=[{"role": "user", "content": "test"}],
                chat_html="",
                dashboard_html="",
            )
            self.assertIsNotNone(conversations.get(record["id"]))
            self.assertIsNone(conversations.get("../outside"))
            self.assertFalse(conversations.delete("../outside"))

            reports = ReportStore(temp_dir)
            self.assertIsNone(reports.get("../outside"))
            self.assertFalse(reports.delete("../outside"))
            (Path(temp_dir) / "uploaded_reports" / "deadbeef.json").write_text(
                '{"id":"deadbeef","ext":"../../outside"}', encoding="utf-8"
            )
            self.assertIsNone(reports.get("deadbeef"))
            self.assertEqual(reports.list(), [])
            self.assertTrue(reports.delete("deadbeef"))

    def test_conversation_title_and_snapshot_are_stable_across_follow_up(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            conversations = ConversationStore(temp_dir)
            first = conversations.save(
                mode="data",
                title="临时标题",
                messages=[{"role": "user", "content": "第一个问题\n补充说明"}],
                chat_html="first",
                dashboard_html="first",
            )
            conversations.save(
                mode="data",
                title="不应覆盖标题",
                messages=[
                    {"role": "user", "content": "第一个问题\n补充说明"},
                    {"role": "assistant", "content": "结论"},
                    {"role": "user", "content": "追加问题"},
                ],
                chat_html="second",
                dashboard_html="second",
                cid=first["id"],
            )
            loaded = conversations.get(first["id"])
            self.assertEqual(loaded["title"], "第一个问题")
            self.assertEqual(loaded["chat_html"], "second")
            self.assertEqual(list(Path(temp_dir, "bi_conversations").glob(".*.tmp")), [])

    def test_new_conversation_id_does_not_overwrite_collision(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            conversations = ConversationStore(temp_dir)
            existing = Path(temp_dir, "bi_conversations", "deadbeef.json")
            existing.write_text(
                json.dumps({"id": "deadbeef", "title": "保留"}), encoding="utf-8"
            )
            with patch(
                "bi_agent.web.conversations.secrets.token_hex",
                side_effect=["deadbeef", "cafebabe"],
            ):
                record = conversations.save(
                    mode="data",
                    title="新会话",
                    messages=[{"role": "user", "content": "新问题"}],
                    chat_html="",
                    dashboard_html="",
                )
            self.assertEqual(record["id"], "cafebabe")
            self.assertEqual(json.loads(existing.read_text(encoding="utf-8"))["title"], "保留")

    def test_report_id_collision_and_metadata_failure_cleanup(self) -> None:
        parsed = ParseResult(ext=".pdf", page_count=1, text="示例")
        with tempfile.TemporaryDirectory() as temp_dir:
            reports = ReportStore(temp_dir)
            root = Path(temp_dir, "uploaded_reports")
            (root / "deadbeef.pdf").write_bytes(b"old")
            with patch("bi_agent.report.store.parse_report", return_value=parsed), patch(
                "bi_agent.report.store.secrets.token_hex",
                side_effect=["deadbeef", "cafebabe"],
            ):
                record = reports.save(filename="sample.pdf", data=b"new")
            self.assertEqual(record.id, "cafebabe")
            self.assertEqual((root / "deadbeef.pdf").read_bytes(), b"old")

            with patch("bi_agent.report.store.parse_report", return_value=parsed), patch(
                "bi_agent.report.store.secrets.token_hex", return_value="feedface"
            ), patch("bi_agent.report.store.os.replace", side_effect=OSError("disk full")):
                with self.assertRaises(OSError):
                    reports.save(filename="failed.pdf", data=b"failed")
            self.assertFalse((root / "feedface.pdf").exists())
            self.assertEqual(list(root.glob(".feedface.*.tmp")), [])

    def test_sql_formatter_handles_missing_column_metadata(self) -> None:
        rendered = _format_rows([], [("a", "b")], 10)
        self.assertIn("column_1", rendered)
        self.assertIn("column_2", rendered)

    def test_source_path_and_sql_guards(self) -> None:
        previous = STATE.cwd
        try:
            with tempfile.TemporaryDirectory() as temp_dir:
                STATE.cwd = temp_dir
                self.assertEqual(_cwd_file("data.xlsx", label="文件"), (Path(temp_dir) / "data.xlsx").resolve())
                with self.assertRaises(HTTPException):
                    _cwd_file("../outside.xlsx", label="文件")
        finally:
            STATE.cwd = previous
        self.assertIsNone(_validate_sql("SELECT 1"))
        self.assertIsNotNone(_validate_sql("SELECT 1; DROP TABLE t"))

    def test_healthz_never_requires_a_model_call(self) -> None:
        previous = (STATE.agent_def, STATE.ontology_store, STATE.conversation_store)
        try:
            STATE.agent_def = None
            STATE.ontology_store = None
            STATE.conversation_store = None
            response = TestClient(app).get("/healthz")
            # Force the not-ready branch; it must remain model-free.
            self.assertEqual(response.status_code, 503)
            self.assertFalse(response.json()["llm_call"])
        finally:
            STATE.agent_def, STATE.ontology_store, STATE.conversation_store = previous

    def test_repository_catalog_follows_pagination_contract(self) -> None:
        class FakeRemote:
            base_url = "http://ontology.test"
            repository_id = "1"
            calls: list[int] = []

            def list_repositories(self, *, page: int, size: int):
                self.calls.append(page)
                if page == 1:
                    return {"items": [{"id": 1, "name": "库一"}], "total": 2}
                return {"items": [{"id": 2, "name": "库二"}], "total": 2}

        previous = (STATE.cwd, STATE.remote_ontology, STATE.ontology_backend)
        try:
            with tempfile.TemporaryDirectory() as temp_dir:
                STATE.cwd = temp_dir
                STATE.remote_ontology = FakeRemote()
                STATE.ontology_backend = "production"
                payload = json.loads(get_sources_endpoint().body)
                repos = payload["ontology"]["remote_repositories"]
                self.assertEqual([repo["id"] for repo in repos], ["1", "2"])
                self.assertEqual(STATE.remote_ontology.calls, [1, 2])
        finally:
            STATE.cwd, STATE.remote_ontology, STATE.ontology_backend = previous


if __name__ == "__main__":
    unittest.main()
