"""Offline regression tests for the BI web/LLM integration.

These tests deliberately mock the provider stream. They validate conversion,
failure handling and persistence without making any Qwen/Anthropic request.
"""

from __future__ import annotations

import json
import os
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from fastapi import HTTPException
from fastapi.testclient import TestClient

from bi_agent.llm import provider, provider_qwen, provider_team
from bi_agent.llm.provider_deepseek import _convert_messages as convert_deepseek
from bi_agent.llm.provider_qwen import _convert_messages as convert_qwen
from bi_agent.ontology.store import OntologyStore
from bi_agent.report.parser import ParseResult
from bi_agent.report.store import ReportStore
from bi_agent.tools.sql_tools import (
    DorisHttpConn,
    DorisApiError,
    _doris_query,
    _format_rows,
    _validate_sql,
)
from bi_agent.tools.chart_tools import (
    _echarts_option,
    _make_chart_generate,
    _write_standalone_html,
)
from bi_agent.web.app import (
    STATE, _cwd_file, _history_ontology_entities, _render_history_ontology_cards,
    app, get_sources_endpoint,
)
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

    def test_standalone_chart_html_escapes_script_context_and_avoids_collision(self) -> None:
        option = _echarts_option({
            "chart_type": "bar",
            "title": "</script><script>alert(1)</script>",
            "x_axis": ["一月"],
            "series": [{"name": "金额", "data": [1]}],
        })
        with tempfile.TemporaryDirectory() as temp_dir, patch(
            "bi_agent.tools.chart_tools.time.strftime", return_value="20260804-120000"
        ):
            out = Path(temp_dir) / "chart.html"
            _write_standalone_html(option, out, "</title><script>alert(1)</script>")
            html = out.read_text(encoding="utf-8")
            self.assertNotIn("</script><script>", html)
            self.assertIn("&lt;/title&gt;", html)

            execute = _make_chart_generate()
            params = {
                "chart_type": "bar",
                "title": "同名图",
                "x_axis": ["一月"],
                "series": [{"name": "金额", "data": [1]}],
            }
            first = execute(params, temp_dir)
            second = execute(params, temp_dir)
            self.assertIn("chart-20260804-120000-同名图.html", first)
            self.assertIn("chart-20260804-120000-同名图-2.html", second)

    def test_doris_database_identifier_and_result_limit_are_bounded(self) -> None:
        with self.assertRaises(ValueError):
            DorisHttpConn("http://doris.test/query", "ontology; DROP TABLE users")
        rendered = _format_rows(["value"], [(1,), (2,)], -1)
        self.assertIn("1", rendered)
        self.assertIn("2", rendered)

    def test_doris_http_error_code_and_auth_header_are_normalized(self) -> None:
        class FakeResponse:
            def __init__(self, body: dict) -> None:
                self.body = body

            def __enter__(self):
                return self

            def __exit__(self, *_args):
                return False

            def read(self):
                return json.dumps(self.body).encode("utf-8")

        requests = []

        def fake_urlopen(request, timeout):
            requests.append(request)
            return FakeResponse({"code": 500, "msg": "query failed"})

        with patch.dict(os.environ, {"ONTOLOGY_AUTH_TOKEN": "token"}), patch(
            "bi_agent.tools.sql_tools.urlopen", fake_urlopen
        ):
            with self.assertRaises(DorisApiError):
                _doris_query(DorisHttpConn("http://doris.test/query"), "SELECT 1")
        self.assertEqual(requests[0].get_header("Authorization"), "Bearer token")

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

    def test_team_provider_dispatch_and_quota_fallback_are_mock_only(self) -> None:
        calls: list[str] = []

        def fake_stream(**kwargs):
            calls.append(kwargs["model_id"])
            if len(calls) == 1:
                yield {"type": "error", "error": "429 team quota exceeded"}
            else:
                yield {"type": "text_delta", "text": "team-ok"}
                yield {"type": "message_end", "stop_reason": "end_turn", "usage": {}}

        models = {
            "team-configured": {"provider": "team", "model_id": "direct-deepseek-v4-flash"},
            "team-fallback": {"provider": "team", "model_id": "direct-deepseek-v4-pro"},
        }
        with patch.object(provider_team, "stream", fake_stream), \
             patch.object(provider, "get_model", side_effect=lambda key: models.get(key)), \
             patch.object(provider, "fallback_model_keys", return_value=["team-fallback"]):
            events = list(provider.stream_message(
                [], "system", None, "team-configured", 256, 0.1
            ))
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

    def test_ontology_entity_extraction_supports_all_source_code_prefixes(self) -> None:
        store = OntologyStore()
        store.metrics["M0001"] = SimpleNamespace(
            name="本地指标", to_prompt=lambda: "指标 [M0001] 本地指标"
        )
        store.dimensions["D001"] = SimpleNamespace(
            name="时间", to_prompt=lambda: "维度 [D001] 时间"
        )
        session = WebSession("/tmp", AgentDef("test", tools=[]), store)

        # MET/TERM/MREL are common in the remote MetaERP repository, while
        # M/D are used by the local workbook.  Remote-only codes must remain
        # visible even when the local fallback workbook has no matching row.
        text = "\n".join([
            "[MET001] 净销售收入 (Indicator)",
            "[TERM001] 净销售收入 (Term)",
            "[MREL000003] 业务对象包含逻辑实体 (MetaRelation)",
            "[M0001] 本地指标 (Indicator)",
            "[D001] 时间 (Dimension)",
        ])
        entities = session._extract_entities(text)
        by_code = {item["code"]: item for item in entities}
        self.assertEqual(set(by_code), {"D001", "M0001", "MET001", "MREL000003", "TERM001"})
        self.assertEqual(by_code["MET001"]["kind"], "metric")
        self.assertEqual(by_code["TERM001"]["kind"], "term")
        self.assertEqual(by_code["MREL000003"]["kind"], "meta_relation")
        self.assertEqual(by_code["D001"]["display"], "维度 [D001] 时间")

    def test_remote_ontology_wins_over_same_code_in_local_fallback(self) -> None:
        store = OntologyStore()
        store.business_objects["BO0005"] = SimpleNamespace(
            name="本地元数据字段映射",
            to_prompt=lambda: "业务对象 [BO0005] 本地元数据字段映射",
        )
        session = WebSession(
            "/tmp", AgentDef("test", tools=[]), store,
            ontology_backend="production", ontology_repository_id="4",
        )
        entities = session._extract_entities(
            "[BO0005] 采购订单 (BusinessObject)\n"
            "  name: Purchase Order\n"
            "[PT0006] po_header_t (TableNode)",
            "OntologyQuery",
        )
        by_code = {item["code"]: item for item in entities}
        self.assertEqual(by_code["BO0005"]["name"], "采购订单")
        self.assertEqual(by_code["BO0005"]["source"], "remote")
        self.assertEqual(by_code["BO0005"]["repository_id"], "4")
        self.assertEqual(by_code["PT0006"]["kind"], "table_node")

    def test_non_ontology_tool_references_do_not_become_entity_hits(self) -> None:
        store = OntologyStore()
        store.metrics["M0001"] = SimpleNamespace(
            name="本地指标", to_prompt=lambda: "指标 [M0001] 本地指标"
        )
        session = WebSession("/tmp", AgentDef("test", tools=[]), store)
        self.assertEqual(
            session._extract_entities("Source: M0001 · orders", "SQLRun"),
            [],
        )

    def test_history_ontology_snapshot_migrates_from_persisted_remote_tools(self) -> None:
        store = OntologyStore()
        session = WebSession(
            "/tmp", AgentDef("test", tools=[]), store,
            ontology_backend="production", ontology_repository_id="4",
        )
        messages = [
            {"role": "assistant", "content": [{
                "type": "tool_use", "id": "t1", "name": "OntologyQuery", "input": {},
            }]},
            {"role": "user", "content": [{
                "type": "tool_result", "tool_use_id": "t1",
                "content": "# Remote OntologyQuery\n[BO0005] 采购订单 (BusinessObject)",
            }]},
        ]
        entities = _history_ontology_entities(session, messages)
        html = _render_history_ontology_cards(entities)
        self.assertIn('data-entity-key="remote:4:business_object:BO0005"', html)
        self.assertIn('采购订单', html)
        self.assertNotIn("本地", html)

    def test_ontology_all_includes_extended_collections(self) -> None:
        previous = (STATE.ontology_store,)
        try:
            store = OntologyStore()
            store.dimensions["D001"] = SimpleNamespace(code="D001", name="时间")
            store.processes["SSP0001"] = SimpleNamespace(code="SSP0001", name="采购")
            store.meta_relations["MREL000003"] = SimpleNamespace(code="MREL000003", name="包含")
            STATE.ontology_store = store
            payload = json.loads(TestClient(app).get("/api/ontology/all").content)
            self.assertEqual(payload["dimensions"][0]["code"], "D001")
            self.assertEqual(payload["processes"][0]["code"], "SSP0001")
            self.assertEqual(payload["meta_relations"][0]["code"], "MREL000003")
        finally:
            STATE.ontology_store = previous[0]

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
        self.assertIsNone(_validate_sql("PRAGMA table_info('orders')"))
        self.assertIsNotNone(_validate_sql("PRAGMA journal_mode=WAL"))

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
