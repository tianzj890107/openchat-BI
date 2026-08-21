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
from urllib.error import HTTPError, URLError
from unittest.mock import patch

from fastapi import HTTPException
from fastapi.testclient import TestClient

from bi_agent.llm import provider, provider_qwen, provider_team
from bi_agent.llm.provider_deepseek import _convert_messages as convert_deepseek
from bi_agent.llm.provider_qwen import _convert_messages as convert_qwen
from bi_agent.ontology.store import OntologyStore
from bi_agent.paths import CONVERSATIONS_DIR, SPREADSHEETS_DIR, UPLOADED_REPORTS_DIR
from bi_agent.report.parser import ParseResult
from bi_agent.report.store import ReportStore
from bi_agent.tools.sql_tools import (
    DorisHttpConn,
    DorisApiError,
    SqlBackend,
    _doris_query,
    _format_rows,
    _make_sql_run,
    _validate_sql,
)
from bi_agent.tools.chart_tools import (
    _echarts_option,
    _make_chart_generate,
    _write_standalone_html,
)
from bi_agent.tools.chart_policy import (
    chart_skip_reason,
    has_constant_chart_values,
    is_list_like_intent,
)
from bi_agent.tools.analysis_policy import (
    classify_intent,
    has_effective_action,
    has_action_section,
    has_root_cause_section,
    wants_action,
    wants_root_cause,
)
from bi_agent.tools.remote_ontology_tools import (
    _make_graph_context,
    _make_graph_expand,
    _make_related,
    _make_metric_data_query,
    _metric_adapter,
    _rank_row,
)
from bi_agent.web import app as web_app_module
from bi_agent.ontology.remote import OntologyApiError, RemoteOntologyClient
from bi_agent.web.app import (
    STATE, _cwd_file, _history_ontology_entities, _infer_history_source_config,
    _render_history_ontology_cards, ConversationSaveRequest, RolesRequest, SourcesUpdate,
    app, get_roles, get_sources_endpoint, put_roles, put_sources_endpoint,
    save_conversation,
)
from bi_agent.web.conversations import ConversationStore, conversation_title, first_user_question, first_visible_user_question
from bi_agent.web.session import WebSession
from open_claude.agent_def import AgentDef


class OfflineRegressionTests(unittest.TestCase):
    def test_root_redirects_to_workbench(self) -> None:
        response = TestClient(app).get("/", follow_redirects=False)
        self.assertEqual(response.status_code, 307)
        self.assertEqual(response.headers.get("location"), "/workbench")

    def test_remote_metric_priority_and_three_dialect_adapter(self) -> None:
        query = "target"
        ranked = [
            ({"alias": "target", "code": "M4"}, 3),
            ({"name": "target", "code": "M3"}, 2),
            ({"label": "target", "code": "M2"}, 1),
            ({"code": "target", "label": "x"}, 0),
            ({"label": "target fuzzy suffix", "code": "M5"}, 4),
        ]
        self.assertEqual([_rank_row(row, query)[0] for row, _ in ranked], [expected for _, expected in ranked])
        canonical = _metric_adapter({
            "code": "M1", "bizFormula": "a/b", "statCaliber": "已审核",
            "calculationRule": "SUM(a)", "sourceTables": ["orders"],
            "aggregateType": "SUM",
        })
        self.assertEqual(canonical["formula"], "a/b")
        self.assertEqual(canonical["caliber"], "已审核")
        self.assertEqual(canonical["calculation_rule"], "SUM(a)")
        self.assertIn("orders", canonical["source_tables"])

    def test_remote_analysis_clients_use_analysis_config_contract(self) -> None:
        client = RemoteOntologyClient("http://ontology.test", "1")
        calls = []
        client._request = lambda method, path, **kwargs: calls.append((path, kwargs["body"])) or {"data": {"ok": True}}
        self.assertTrue(client.metadata_query({"vertex": [{"type": "Indicator"}]})["ok"])
        self.assertTrue(client.data_query({"indicators": [], "dimensions": []})["ok"])
        self.assertEqual(calls[0][1]["analysisConfig"]["vertex"][0]["type"], "Indicator")
        self.assertNotIn("queryConfig", calls[0][1])
        self.assertEqual(calls[1][0], "/api/v1/analysis/data/query")

    def test_remote_object_listing_uses_short_lived_complete_cache(self) -> None:
        client = RemoteOntologyClient("http://ontology.test", "1")
        calls = []
        client.script_query = lambda language, script: calls.append(script) or {
            "results": [{"rows": [{"code": "M1"}, {"code": "M2"}]}],
        }
        self.assertEqual(len(client.list_objects("Indicator", 1000)), 2)
        self.assertEqual(len(client.list_objects("Indicator", 1000)), 2)
        self.assertEqual(len(calls), 1)

    def test_remote_graph_neighborhood_recovers_directed_edge_evidence(self) -> None:
        client = RemoteOntologyClient("http://ontology.test", "4")
        client.find_related = lambda type_name, code, depth=2: {
            "objects": [
                {"typeName": "LogicalEntity", "properties": {"code": "LE1", "label": "订单"}},
                {"typeName": "BusinessAttribute", "properties": {"code": "ATT1", "label": "金额"}},
            ],
        }
        client.list_objects = lambda type_name, limit=2000: [
            {"code": "BO1", "label": "采购订单"},
        ]
        calls = []
        client.script_query = lambda language, script, params_list=None: calls.append(
            (language, script, params_list)
        ) or {
            "results": [{"rows": [
                {
                    "sourceCode": ["BO1"],
                    "relationType": ["BOContainLE"],
                    "relationProperties": [{"cardinality": "1:N"}],
                    "targetCode": ["LE1"],
                },
                {
                    "sourceCode": "LE1",
                    "relationType": "LEContainATT",
                    "relationProperties": {},
                    "targetCode": "ATT1",
                },
            ]}],
        }

        graph = client.graph_neighborhood("BusinessObject", "BO1", depth=4)
        self.assertEqual(len(graph["objects"]), 3)
        self.assertEqual(len(graph["relations"]), 2)
        self.assertTrue(graph["relations_available"])
        self.assertEqual(calls[0][0], "opencypher")
        self.assertEqual(calls[0][2][0][0], "codes")
        self.assertIn("BO1", calls[0][2][0][1])

    def test_remote_graph_neighborhood_keeps_vertices_when_edge_query_fails(self) -> None:
        client = RemoteOntologyClient("http://ontology.test", "4")
        client.find_related = lambda type_name, code, depth=2: {
            "objects": [
                {"typeName": "LogicalEntity", "properties": {"code": "LE1", "label": "订单"}},
            ],
        }
        client.list_objects = lambda type_name, limit=2000: [
            {"code": "BO1", "label": "采购订单"},
        ]

        def unavailable_edges(language, script, params_list=None):
            raise OntologyApiError("OpenCypher is unavailable")

        client.script_query = unavailable_edges
        graph = client.graph_neighborhood("BusinessObject", "BO1", depth=3)
        self.assertEqual(len(graph["objects"]), 2)
        self.assertEqual(graph["relations"], [])
        self.assertFalse(graph["relations_available"])
        output = _make_graph_context(client)({"anchor": "BO1"}, ".")
        self.assertIn("降级说明", output)
        self.assertIn("[LE1] 订单 (LogicalEntity)", output)
        self.assertIn("方向/关系类型未由当前仓库返回", output)

    def test_remote_graph_context_matches_local_subtree_and_adds_paths(self) -> None:
        class FakeGraphClient:
            repository_id = "4"

            def graph_neighborhood(self, type_name, code, **kwargs):
                return {
                    "depth": kwargs.get("depth", 4),
                    "relations_available": True,
                    "objects": [
                        {"typeName": "BusinessObject", "anchor": code == "BO1", "properties": {"code": "BO1", "label": "采购订单"}},
                        {"typeName": "LogicalEntity", "properties": {"code": "LE1", "label": "采购订单头", "physicalTable": "po_header"}},
                        {"typeName": "BusinessAttribute", "properties": {"code": "ATT1", "label": "订单金额", "columnName": "amount"}},
                        {"typeName": "Indicator", "anchor": code == "M1", "properties": {"code": "M1", "label": "采购金额", "businessFormula": "SUM(amount)"}},
                        {"typeName": "Dimension", "properties": {"code": "D1", "label": "时间维度"}},
                    ],
                    "relations": [
                        {"sourceCode": "BO1", "relationType": "BOContainLE", "relationProperties": {}, "targetCode": "LE1"},
                        {"sourceCode": "LE1", "relationType": "LEContainATT", "relationProperties": {}, "targetCode": "ATT1"},
                        {"sourceCode": "M1", "relationType": "IndicatorIsCalculatedFromATT", "relationProperties": {"expression": "SUM"}, "targetCode": "ATT1"},
                        {"sourceCode": "M1", "relationType": "IndicatorIsDrilledByDimension", "relationProperties": {}, "targetCode": "D1"},
                    ],
                }

            def list_objects(self, type_name, limit=2000):
                return []

        output = _make_graph_context(FakeGraphClient())({"anchor": "M1"}, ".")
        self.assertIn("Remote GraphContext", output)
        self.assertIn("[M1] 采购金额 (Indicator)", output)
        self.assertIn("[BO1] 采购订单 (BusinessObject)", output)
        self.assertIn("[LE1] 采购订单头 (LogicalEntity)", output)
        self.assertIn("[ATT1] 订单金额 (BusinessAttribute)", output)
        self.assertIn("[D1] 时间维度 (Dimension)", output)
        self.assertIn("IndicatorIsCalculatedFromATT", output)
        self.assertIn("关键路径", output)

    def test_remote_graph_expand_uses_activity_and_entity_paths_then_drills_subtrees(self) -> None:
        class FakeGraphClient:
            repository_id = "4"

            def graph_neighborhood(self, type_name, code, **kwargs):
                objects = [
                    {"typeName": "BusinessObject", "anchor": code == "BO1", "properties": {"code": "BO1", "label": "采购订单"}},
                    {"typeName": "Indicator", "anchor": code == "M1", "properties": {"code": "M1", "label": "采购金额"}},
                    {"typeName": "Activity", "properties": {"code": "ACT1", "label": "下达订单"}},
                    {"typeName": "Process", "properties": {"code": "PROC1", "label": "采购流程"}},
                    {"typeName": "Activity", "properties": {"code": "ACT2", "label": "收货"}},
                    {"typeName": "BusinessObject", "anchor": code == "BO2", "properties": {"code": "BO2", "label": "采购收货"}},
                    {"typeName": "LogicalEntity", "properties": {"code": "LE2", "label": "收货单"}},
                    {"typeName": "BusinessAttribute", "properties": {"code": "ATT2", "label": "收货金额"}},
                ]
                relations = [
                    {"sourceCode": "M1", "relationType": "IndicatorBelongToBO", "relationProperties": {}, "targetCode": "BO1"},
                    {"sourceCode": "ACT1", "relationType": "ActivityOperateBO", "relationProperties": {}, "targetCode": "BO1"},
                    {"sourceCode": "ACT1", "relationType": "ActivityBelongsToProcess", "relationProperties": {}, "targetCode": "PROC1"},
                    {"sourceCode": "ACT1", "relationType": "ActivityFlowsTo", "relationProperties": {"sequence": 2}, "targetCode": "ACT2"},
                    {"sourceCode": "ACT2", "relationType": "ActivityOperateBO", "relationProperties": {}, "targetCode": "BO2"},
                    {"sourceCode": "BO2", "relationType": "BOContainLE", "relationProperties": {}, "targetCode": "LE2"},
                    {"sourceCode": "LE2", "relationType": "LEContainATT", "relationProperties": {}, "targetCode": "ATT2"},
                ]
                return {
                    "depth": kwargs.get("depth", 5), "relations_available": True,
                    "objects": objects, "relations": relations,
                }

            def list_objects(self, type_name, limit=2000):
                return []

        client = FakeGraphClient()
        output = _make_graph_expand(client)({"anchor": "BO1"}, ".")
        self.assertIn("Remote GraphExpand", output)
        self.assertIn("活动/流程链", output)
        self.assertIn("ActivityFlowsTo", output)
        self.assertIn("[BO2] 采购收货 (BusinessObject)", output)
        self.assertIn("[LE2] 收货单 (LogicalEntity)", output)
        self.assertIn("[ATT2] 收货金额 (BusinessAttribute)", output)
        self.assertIn("扩散关系证据", output)

        indicator_output = _make_graph_expand(client)({"anchor": "M1"}, ".")
        self.assertIn("指标回挂业务对象", indicator_output)
        self.assertIn("[BO2] 采购收货 (BusinessObject)", indicator_output)

        relation_output = _make_related(client)({"entity": "BO1"}, ".")
        self.assertIn("关系证据", relation_output)
        self.assertIn("ActivityOperateBO", relation_output)

    def test_metric_data_query_builds_semantic_payload(self) -> None:
        class FakeClient:
            def data_query(self, analysis, common):
                self.analysis = analysis
                self.common = common
                return {"resultType": "TABLE", "result": {"rows": [{"D1": "A", "M1": 2}]}}

        client = FakeClient()
        output = _make_metric_data_query(client)({
            "metric_codes": ["M1"], "dimensions": ["D1"], "page_size": 20,
        }, ".")
        self.assertEqual(client.analysis["indicators"][0]["identifierCode"], "M1")
        self.assertEqual(client.analysis["dimensions"][0]["identifierCode"], "D1")
        self.assertEqual(client.common["pagination"]["pageSize"], 20)
        self.assertIn("analysis/data/query", output)
        invalid = _make_metric_data_query(client)({
            "metric_codes": "M1", "page_size": "many",
        }, ".")
        self.assertIn("must be arrays", invalid)

        class FailingClient:
            cache_ttl = 30
            calls = 0

            def data_query(self, analysis, common):
                self.calls += 1
                raise OntologyApiError("HTTP 500 from /analysis/data/query")

        failing = FailingClient()
        execute = _make_metric_data_query(failing)
        params = {"metric_codes": ["M1"], "dimensions": []}
        self.assertIn("remote error", execute(params, "."))
        self.assertIn("recent endpoint failure", execute(params, "."))
        self.assertEqual(failing.calls, 1)

    def test_web_sessions_keep_source_bound_executors_isolated(self) -> None:
        agent = AgentDef("isolated", tools=["MetricLookup"])
        session_one = WebSession(
            "/tmp", agent, OntologyStore(),
            tool_executors={"MetricLookup": lambda params, cwd: "repository-1"},
        )
        session_two = WebSession(
            "/tmp", agent, OntologyStore(),
            tool_executors={"MetricLookup": lambda params, cwd: "repository-2"},
        )
        call = {"name": "MetricLookup", "input": {"metric": "M1"}}
        self.assertEqual(session_one._execute_tool(call)[0], "repository-1")
        self.assertEqual(session_two._execute_tool(call)[0], "repository-2")

    def test_legacy_history_source_is_inferred_from_sql_schema(self) -> None:
        source = _infer_history_source_config([
            {"role": "assistant", "content": "SQL: SELECT * FROM ontology_guangfeng.t_stk_slowmoving"},
        ])
        self.assertEqual(source["database"], "__doris_api__")
        self.assertEqual(source["doris_database"], "ontology_guangfeng")
        self.assertEqual(source["ontology"], "__metaerp_repository__:4")

    def test_list_intent_skips_constant_chart_without_calling_executor(self) -> None:
        chart = {
            "chart_type": "bar",
            "title": "可分析业务对象",
            "x_axis": ["采购订单", "供应商", "物料"],
            "series": [{"name": "数量", "data": [1, 1, 1]}],
        }
        self.assertTrue(is_list_like_intent("列出本体里所有业务对象"))
        self.assertFalse(is_list_like_intent("列出各基地采购金额分布"))
        self.assertTrue(has_constant_chart_values(chart))
        self.assertIsNotNone(
            chart_skip_reason("列出本体里所有业务对象", "ChartGenerate", chart)
        )

        session = WebSession("/tmp", AgentDef("test", tools=[]), OntologyStore())
        session._active_user_text = "列出本体里所有业务对象"
        with patch("bi_agent.web.session.execute_tool") as execute:
            output, suppressed = session._execute_tool({"name": "ChartGenerate", "input": chart})
        execute.assert_not_called()
        self.assertTrue(suppressed)
        self.assertIn("ChartGenerate skipped", output)
        self.assertIn("TableGenerate", output)

    def test_analytical_constant_chart_is_not_suppressed(self) -> None:
        chart = {
            "chart_type": "bar",
            "title": "各基地采购金额分布",
            "x_axis": ["基地A", "基地B"],
            "series": [{"name": "金额", "data": [1, 1]}],
        }
        self.assertIsNone(
            chart_skip_reason("列出各基地采购金额分布", "ChartGenerate", chart)
        )

    def test_root_cause_intent_is_question_driven_not_emoji_driven(self) -> None:
        self.assertTrue(wants_root_cause("为什么应收账款持续上升？"))
        self.assertFalse(wants_root_cause("给出改善方案和行动建议"))
        self.assertTrue(wants_action("给出改善方案和行动建议"))
        self.assertTrue(wants_action("只给我行动建议，不要根因分析"))
        self.assertFalse(wants_root_cause("只查一下本月应收账款金额，不需要原因分析"))
        self.assertFalse(wants_root_cause("列出所有业务对象"))

    def test_five_level_intent_classification_keeps_root_and_action_separate(self) -> None:
        cases = {
            "采购金额是多少": ("L1", False, False),
            "采购金额哪里异常": ("L2", False, False),
            "为什么采购成本上涨": ("L3", True, False),
            "给我改善采购成本的方案": ("L4", False, True),
            "帮我制定执行计划和复盘机制": ("L5", False, True),
        }
        for question, expected in cases.items():
            intent = classify_intent(question)
            self.assertEqual(
                (intent.level, intent.wants_root_cause, intent.wants_action),
                expected,
                question,
            )
        self.assertFalse(wants_root_cause("只查数据，不分析原因"))

    def test_root_cause_requires_action_section(self) -> None:
        root = "根因分析：华东区域贡献了主要下降。"
        action = "行动建议：先对华东区域重点客户做回访。"
        self.assertTrue(has_root_cause_section(root))
        self.assertFalse(has_action_section(root))
        self.assertTrue(has_action_section(action))
        self.assertTrue(has_root_cause_section("🔍 根因分析\n💡 行动建议"))
        for title in ("根因证据链", "根因", "建议雏形", "执行建议", "建议"):
            self.assertTrue(has_root_cause_section(title) or has_action_section(title), title)

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
        run = _make_sql_run(SqlBackend(doris=DorisHttpConn("http://doris.test/query")))
        self.assertIn("PRAGMA is SQLite-only", run({"sql": "PRAGMA table_info('orders')"}, "."))

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

    def test_doris_http_uses_current_repository_over_environment_default(self) -> None:
        class FakeResponse:
            def __enter__(self):
                return self

            def __exit__(self, *_args):
                return False

            def read(self):
                return json.dumps({"data": {"rows": [{"value": 1}]}}).encode("utf-8")

        requests = []

        def fake_urlopen(request, timeout):
            requests.append(request)
            return FakeResponse()

        conn = DorisHttpConn(
            "http://doris.test/query",
            repository_id="4",
            app_id="current-app",
        )
        with patch.dict(os.environ, {
            "ONTOLOGY_REPOSITORY_ID": "3",
            "ONTOLOGY_APP_ID": "old-app",
        }), patch("bi_agent.tools.sql_tools.urlopen", fake_urlopen):
            _doris_query(conn, "SELECT 1")
        self.assertEqual(requests[0].get_header("X-ontology-repository-id"), "4")
        self.assertEqual(requests[0].get_header("X-app-id"), "current-app")

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

    def test_root_cause_turn_is_reprompted_until_action_section_exists(self) -> None:
        responses = iter([
            [
                {"type": "text_delta", "text": "根因分析：华东区域贡献了主要下降。"},
                {"type": "message_end", "stop_reason": "end_turn", "usage": {}},
            ],
            [
                {"type": "text_delta", "text": "行动建议：先对华东区域重点客户做回访。"},
                {"type": "message_end", "stop_reason": "end_turn", "usage": {}},
            ],
        ])

        def fake_stream(*_args, **_kwargs):
            yield from next(responses)

        with patch("bi_agent.web.session.stream_message", fake_stream):
            session = WebSession("/tmp", AgentDef("test", tools=[]), OntologyStore())
            events = list(session.generate_turn("为什么华东区域收入下降？"))

        responses_seen = [event for event in events if event["type"] == "llm_response"]
        self.assertEqual(len(responses_seen), 2)
        self.assertEqual(len(session.messages), 4)  # user + root + reminder + action
        self.assertIn("行动建议", responses_seen[-1]["text"])

    def test_root_cause_is_reprompted_even_when_user_did_not_request_it(self) -> None:
        responses = iter([
            [
                {"type": "text_delta", "text": "根因分析：模型误加的段落。"},
                {"type": "message_end", "stop_reason": "end_turn", "usage": {}},
            ],
            [
                {"type": "text_delta", "text": "建议雏形：针对该证据对应的异常采购批次复核供应商报价。"},
                {"type": "message_end", "stop_reason": "end_turn", "usage": {}},
            ],
        ])

        def fake_stream(*_args, **_kwargs):
            yield from next(responses)

        with patch("bi_agent.web.session.stream_message", fake_stream):
            session = WebSession("/tmp", AgentDef("test", tools=[]), OntologyStore())
            events = list(session.generate_turn("采购金额是多少"))

        self.assertEqual(
            len([event for event in events if event["type"] == "llm_response"]),
            2,
        )

    def test_root_cause_with_suggestion_is_not_reprompted(self) -> None:
        def fake_stream(*_args, **_kwargs):
            yield {"type": "text_delta", "text": "根因分析：华东区域贡献了主要下降。\n建议雏形：优先复核华东区域重点客户报价。"}
            yield {"type": "message_end", "stop_reason": "end_turn", "usage": {}}

        with patch("bi_agent.web.session.stream_message", fake_stream):
            session = WebSession("/tmp", AgentDef("test", tools=[]), OntologyStore())
            events = list(session.generate_turn("为什么华东区域收入下降？"))

        self.assertEqual(
            len([event for event in events if event["type"] == "llm_response"]),
            1,
        )
        recs = [event for event in events if event["type"] == "action_recommendations"]
        self.assertEqual(len(recs), 1)
        self.assertEqual(recs[0]["items"][0]["title"], "优先复核华东区域重点客户报价。")

    # ------------------------------------------------------------------
    # Action delivery gate: root cause ⇒ structured action_recommendations
    # ------------------------------------------------------------------
    def _root_action_events(self, responses, question="为什么华东区域收入下降？",
                            max_iterations=None):
        responses_iter = iter(responses)

        def fake_stream(*_args, **_kwargs):
            yield from next(responses_iter)

        with patch("bi_agent.web.session.stream_message", fake_stream):
            session = WebSession(
                "/tmp", AgentDef("test", tools=[]), OntologyStore(),
                max_iterations=max_iterations,
            )
            events = list(session.generate_turn(question))
        return events, session

    def test_root_cause_standard_action_title_emits_structured_event(self) -> None:
        events, _ = self._root_action_events([[
            {"type": "text_delta", "text": (
                "根因分析：华东区域贡献了主要下降。\n"
                "行动建议：\n"
                "1. **重点客户价格复核**：对华东重点客户重新确认折扣权限和利润底线"
                "（依据：华东区域利润下降132万元）。"
            )},
            {"type": "message_end", "stop_reason": "end_turn", "usage": {}},
        ]])
        recs = [event for event in events if event["type"] == "action_recommendations"]
        self.assertEqual(len(recs), 1)
        item = recs[0]["items"][0]
        self.assertEqual(item["title"], "重点客户价格复核")
        self.assertIn("重新确认折扣权限", item["content"])
        self.assertEqual(item["evidence"], "华东区域利润下降132万元")
        self.assertEqual(recs[0]["turn"], 1)

    def test_root_cause_decision_and_next_step_titles_emit_structured_event(self) -> None:
        for title in ("决策与建议", "下一步行动", "行动方案"):
            events, _ = self._root_action_events([[
                {"type": "text_delta", "text": (
                    f"根因分析：华东区域贡献了主要下降。\n{title}：\n"
                    "1. 优先复核华东区域重点客户报价。"
                )},
                {"type": "message_end", "stop_reason": "end_turn", "usage": {}},
            ]])
            recs = [event for event in events if event["type"] == "action_recommendations"]
            self.assertEqual(len(recs), 1, title)
            self.assertEqual(recs[0]["items"][0]["title"], "优先复核华东区域重点客户报价。")

    def test_root_cause_first_missing_action_then_repair_succeeds(self) -> None:
        events, session = self._root_action_events([
            [
                {"type": "text_delta", "text": "根因分析：华东区域贡献了主要下降。"},
                {"type": "message_end", "stop_reason": "end_turn", "usage": {}},
            ],
            [
                {"type": "text_delta", "text": "行动建议：先对华东区域重点客户做回访。"},
                {"type": "message_end", "stop_reason": "end_turn", "usage": {}},
            ],
        ])
        repairs = [event for event in events if event["type"] == "action_repair"]
        self.assertEqual(len(repairs), 1)
        self.assertEqual(repairs[0]["attempt"], 1)
        self.assertEqual(
            len([event for event in events if event["type"] == "llm_response"]),
            2,
        )
        recs = [event for event in events if event["type"] == "action_recommendations"]
        self.assertEqual(len(recs), 1)
        self.assertEqual(len(session.messages), 4)  # user + root + reminder + action

    def test_root_cause_two_missing_actions_blocks_delivery(self) -> None:
        events, _ = self._root_action_events([
            [
                {"type": "text_delta", "text": "根因分析：华东区域贡献了主要下降。"},
                {"type": "message_end", "stop_reason": "end_turn", "usage": {}},
            ],
            [
                {"type": "text_delta", "text": "行动建议：\n1. 加强管理"},
                {"type": "message_end", "stop_reason": "end_turn", "usage": {}},
            ],
            [
                {"type": "text_delta", "text": "行动建议：持续关注。"},
                {"type": "message_end", "stop_reason": "end_turn", "usage": {}},
            ],
        ])
        blocked = [event for event in events if event["type"] == "delivery_incomplete"]
        self.assertEqual(len(blocked), 1)
        self.assertEqual(blocked[0]["reason"], "action_missing")
        self.assertEqual(blocked[0]["attempts"], 2)
        self.assertNotIn(
            "action_recommendations", [event["type"] for event in events],
        )
        done = [event for event in events if event["type"] == "done"]
        self.assertEqual(done[0]["stop_reason"], "delivery_incomplete")

    def test_root_cause_in_last_main_iteration_still_repairs(self) -> None:
        events, _ = self._root_action_events([
            [
                {"type": "text_delta", "text": "根因分析：华东区域贡献了主要下降。"},
                {"type": "message_end", "stop_reason": "end_turn", "usage": {}},
            ],
            [
                {"type": "text_delta", "text": "行动建议：先对华东区域重点客户做回访。"},
                {"type": "message_end", "stop_reason": "end_turn", "usage": {}},
            ],
        ], max_iterations=1)
        repairs = [event for event in events if event["type"] == "action_repair"]
        self.assertEqual(len(repairs), 1)
        recs = [event for event in events if event["type"] == "action_recommendations"]
        self.assertEqual(len(recs), 1)

    def test_vague_action_does_not_pass_effective_validation(self) -> None:
        self.assertFalse(has_effective_action("行动建议：加强管理"))
        self.assertFalse(has_effective_action("根因分析：x。\n行动建议：\n1. 持续关注"))
        self.assertFalse(has_effective_action("根因分析：x。\n行动建议：\n1. 已完成对华东客户的复核"))
        self.assertTrue(has_effective_action("根因分析：x。\n行动建议：\n1. 优先复核华东区域重点客户报价"))

    def test_l1_l2_turns_are_not_forced_to_actions(self) -> None:
        events, _ = self._root_action_events([
            [
                {"type": "text_delta", "text": "结论：本月华东区域收入为 5200 万元。"},
                {"type": "message_end", "stop_reason": "end_turn", "usage": {}},
            ],
        ], question="本月华东区域收入是多少？")
        self.assertNotIn("action_repair", [event["type"] for event in events])
        self.assertNotIn("action_recommendations", [event["type"] for event in events])
        self.assertNotIn("delivery_incomplete", [event["type"] for event in events])
        done = [event for event in events if event["type"] == "done"]
        self.assertEqual(done[0]["stop_reason"], "end_turn")

    def test_action_repair_never_executes_tools(self) -> None:
        responses = iter([
            [
                {"type": "text_delta", "text": "根因分析：华东区域贡献了主要下降。"},
                {"type": "message_end", "stop_reason": "end_turn", "usage": {}},
            ],
            [
                {"type": "tool_use_start", "id": "t1", "name": "run_sql"},
                {"type": "tool_use_end", "id": "t1", "name": "run_sql",
                 "input": {"query": "select 1"}},
                {"type": "message_end", "stop_reason": "tool_use", "usage": {}},
            ],
            [
                {"type": "text_delta", "text": "行动建议：先对华东区域重点客户做回访。"},
                {"type": "message_end", "stop_reason": "end_turn", "usage": {}},
            ],
        ])

        def fake_stream(*_args, **_kwargs):
            yield from next(responses)

        with patch("bi_agent.web.session.stream_message", fake_stream), \
             patch.object(WebSession, "_execute_tool",
                          side_effect=AssertionError("repair must not run tools")):
            session = WebSession("/tmp", AgentDef("test", tools=[]), OntologyStore())
            events = list(session.generate_turn("为什么华东区域收入下降？"))
        recs = [event for event in events if event["type"] == "action_recommendations"]
        self.assertEqual(len(recs), 1)
        # The tool-use-only repair response was dropped from history (no
        # text content, so no assistant message is appended for it).
        self.assertEqual(len(session.messages), 5)  # user+root + 2 reminders + action

    def test_frontend_structured_action_event_rendering(self) -> None:
        runtime = Path("frontend/src/runtime.js").read_text(encoding="utf-8")
        built = Path("bi_agent/web/static/vendor/antd/workbench.js").read_text(
            encoding="utf-8", errors="replace")
        self.assertIn('case "action_recommendations"', runtime)
        self.assertIn("structuredActionsCard", runtime)
        self.assertIn("case \"delivery_incomplete\"", runtime)
        self.assertIn("case \"answer_blocked\"", runtime)
        self.assertIn("action_repair", runtime)
        self.assertIn("决策与建议", runtime)
        self.assertIn("下一步行动", runtime)
        self.assertIn("行动方案", runtime)
        self.assertIn("bucket.actionsSeen", runtime)
        self.assertIn("action_recommendations", built)
        self.assertIn("delivery_incomplete", built)

    def test_answer_blocked_turn_still_emits_done_and_action_gate(self) -> None:
        from bi_agent.reliability import Claim, ClaimLevel, ValidationStatus

        responses = iter([
            [
                {"type": "text_delta", "text": "结论：审批中的订单有 50 单。"},
                {"type": "message_end", "stop_reason": "end_turn", "usage": {}},
            ],
            [
                {"type": "text_delta", "text": "结论：审批中的订单有 50 单，占比 9.4%。"},
                {"type": "message_end", "stop_reason": "end_turn", "usage": {}},
            ],
            [
                {"type": "text_delta", "text": (
                    "根因分析：手动创建订单占审批中订单的多数。\n"
                    "行动建议：优先复核手动创建的审批中订单。"
                )},
                {"type": "message_end", "stop_reason": "end_turn", "usage": {}},
            ],
        ])

        def fake_stream(*_args, **_kwargs):
            yield from next(responses)

        claim = Claim(
            id="c-1",
            statement="审批中的订单有 50 单",
            level=ClaimLevel.FACT,
            semantic={"semantic_type": "FACT"},
        )
        with patch("bi_agent.web.session.stream_message", fake_stream), \
             patch("bi_agent.web.session.validate_claims", return_value=SimpleNamespace(
                 status=ValidationStatus.REJECT, issues=("unsupported numeric fact: 9.4",),
             )):
            session = WebSession("/tmp", AgentDef("test", tools=[]), OntologyStore())
            session.claims = [claim]
            events = list(session._run_loop())
        blocked = [event for event in events if event["type"] == "answer_blocked"]
        self.assertEqual(len(blocked), 1)
        recs = [event for event in events if event["type"] == "action_recommendations"]
        self.assertEqual(len(recs), 1)
        done = [event for event in events if event["type"] == "done"]
        self.assertEqual(done[0]["stop_reason"], "answer_blocked")

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
                sop_steps=[
                    {"content": "识别意图", "status": "completed"},
                    {"content": "执行查询取数", "status": "in_progress"},
                ],
                source_config={
                    "ontology": "__metaerp_repository__:4",
                    "database": "__doris_api__",
                    "doris_database": "ontology_demo",
                    "doris_password": "must-not-persist",
                },
            )
            loaded = conversations.get(record["id"])
            self.assertIsNotNone(loaded)
            self.assertEqual(loaded["sop_steps"][0]["status"], "completed")
            self.assertEqual(loaded["sop_steps"][1]["status"], "in_progress")
            self.assertEqual(loaded["source_config"]["ontology"], "__metaerp_repository__:4")
            self.assertNotIn("doris_password", loaded["source_config"])
            legacy = Path(temp_dir) / CONVERSATIONS_DIR / "cafebabe.json"
            legacy.write_text(
                json.dumps({
                    "id": "cafebabe",
                    "mode": "data",
                    "source_config": {"doris_password": "legacy-secret"},
                }),
                encoding="utf-8",
            )
            legacy_loaded = conversations.get("cafebabe")
            self.assertEqual(legacy_loaded["source_config"], {})
            self.assertIsNone(conversations.get("../outside"))
            self.assertFalse(conversations.delete("../outside"))

            reports = ReportStore(temp_dir)
            self.assertIsNone(reports.get("../outside"))
            self.assertFalse(reports.delete("../outside"))
            (Path(temp_dir) / UPLOADED_REPORTS_DIR / "deadbeef.json").write_text(
                '{"id":"deadbeef","ext":"../../outside"}', encoding="utf-8"
            )
            self.assertIsNone(reports.get("deadbeef"))
            self.assertEqual(reports.list(), [])
            self.assertTrue(reports.delete("deadbeef"))

    def test_conversation_sync_payload_filters_secret_source_fields(self) -> None:
        previous_store = STATE.conversation_store
        try:
            with tempfile.TemporaryDirectory() as temp_dir, patch(
                "bi_agent.web.app._conversation_sync", return_value=None
            ) as sync:
                STATE.conversation_store = ConversationStore(temp_dir)
                save_conversation(
                    ConversationSaveRequest(
                        mode="data",
                        title="敏感字段测试",
                        source_config={
                            "ontology": "__metaerp_repository__:4",
                            "doris_database": "ontology_demo",
                            "doris_password": "should-not-sync",
                            "api_key": "should-not-sync",
                        },
                    )
                )
                # Local history is authoritative; a configured mirror must
                # not participate in the save response or title generation.
                sync.assert_not_called()

                first = json.loads(
                    save_conversation(
                        ConversationSaveRequest(
                            mode="data",
                            title="保留已有源配置",
                            source_config={"database": "__doris_api__"},
                        )
                    ).body
                )
                sync.reset_mock()
                save_conversation(
                    ConversationSaveRequest(
                        mode="data",
                        title="追加内容但客户端未拿到源配置",
                        cid=first["id"],
                        source_config={"doris_password": "should-not-clear"},
                    )
                )
                self.assertEqual(
                    ConversationStore(temp_dir).get(first["id"])["source_config"],
                    {"database": "__doris_api__"},
                )
                sync.assert_not_called()
        finally:
            STATE.conversation_store = previous_store

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
            self.assertEqual(loaded["title"], "第一个问题 补充说明")
            self.assertEqual(loaded["first_user_question"], "第一个问题 补充说明")
            self.assertEqual(loaded["chat_html"], "second")
            self.assertEqual(list((Path(temp_dir) / CONVERSATIONS_DIR).glob(".*.tmp")), [])

            conversations.save(
                mode="data",
                title="不应覆盖标题",
                messages=[
                    {"role": "user", "content": "第一个问题\n补充说明"},
                    {"role": "assistant", "content": "结论"},
                    {"role": "user", "content": "第三轮问题"},
                ],
                chat_html="third",
                dashboard_html="third",
                cid=first["id"],
            )
            self.assertEqual(conversations.get(first["id"])["title"], "第一个问题 补充说明")
            self.assertEqual(len(conversations.list("data")), 1)

    def test_conversation_title_uses_first_real_user_question(self) -> None:
        messages = [
            {"role": "system", "content": "内部提示"},
            {"role": "user", "content": [{"type": "tool_result", "content": "工具结果"}]},
            {"role": "user", "content": "  分析\n供应商账期  "},
            {"role": "assistant", "content": "结论"},
            {"role": "user", "content": "供应商账期异常的原因是什么"},
        ]
        self.assertEqual(first_user_question(messages), "分析 供应商账期")
        self.assertEqual(conversation_title(messages), "分析 供应商账期")
        self.assertEqual(len(conversation_title([{"role": "user", "content": "x" * 100} ])), 60)
        self.assertEqual(conversation_title([]), "未命名对话")

    def test_title_algorithm_skips_internal_messages_and_index_version(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            store = ConversationStore(temp_dir)
            saved = store.save(
                mode="data", title="错误标题",
                messages=[
                    {"role": "user", "content": "真实首问", "internal": False},
                    {"role": "user", "content": "内部提醒", "internal": True},
                    {"role": "user", "content": [{"type": "tool_result", "content": "工具结果"}]},
                    {"role": "user", "content": "第二轮问题"},
                ], chat_html="", dashboard_html="",
            )
            self.assertEqual(saved["title"], "真实首问")
            self.assertEqual(saved["first_user_question"], "真实首问")
            self.assertEqual(saved["title_version"], 3)
            index = json.loads((Path(temp_dir) / CONVERSATIONS_DIR / "history_index.json").read_text())
            self.assertEqual(index["version"], 3)
            self.assertEqual(index["title_version"], 3)

    def test_stale_index_version_rebuilds_without_changing_id(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            store = ConversationStore(temp_dir)
            saved = store.save(
                mode="data", title="错误标题",
                messages=[{"role": "user", "content": "第一条问题"}],
                chat_html="", dashboard_html="",
            )
            path = Path(temp_dir) / CONVERSATIONS_DIR / "history_index.json"
            payload = json.loads(path.read_text())
            payload["version"] = 2
            payload["conversations"][saved["id"]]["title"] = "旧标题"
            path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
            reopened = ConversationStore(temp_dir)
            summary = reopened.list("data")[0]
            self.assertEqual(summary["id"], saved["id"])
            self.assertEqual(summary["title"], "第一条问题")
            rebuilt = json.loads(path.read_text())
            self.assertEqual(rebuilt["version"], 3)

    def test_visible_user_text_is_the_stable_title_anchor(self) -> None:
        from bi_agent.web.session import WebSession
        session = object.__new__(WebSession)
        session.first_user_question = ""
        session.messages = []
        # The actual LLM payload may contain an invisible quadrant prefix;
        # the explicit visible text must remain the title source.
        visible = "分析供应商账期"
        session.first_user_question = visible
        self.assertEqual(session.first_user_question, "分析供应商账期")

    def test_rendered_chat_is_authoritative_when_messages_are_stale(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            store = ConversationStore(temp_dir)
            saved = store.save(
                mode="data",
                title="不可信标题",
                messages=[{"role": "user", "content": "那咋办"}],
                chat_html='<div class="msg msg-user"><div class="msg-body">分析供应商账期</div></div>',
                dashboard_html="",
            )
            self.assertEqual(saved["title"], "分析供应商账期")
            self.assertEqual(store.get(saved["id"])["first_user_question"], "分析供应商账期")
            self.assertEqual(first_visible_user_question('<div class="msg msg-user"><div class="msg-body">分析供应商账期</div></div>'), "分析供应商账期")

    def test_explicit_first_user_question_wins_over_stale_messages(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            store = ConversationStore(temp_dir)
            saved = store.save(
                mode="data", title="x", first_user_question_override="分析供应商账期",
                messages=[{"role": "user", "content": "那咋办"}], chat_html="", dashboard_html="",
            )
            self.assertEqual(saved["title"], "分析供应商账期")

    def test_title_migration_repairs_record_and_index_without_changing_content(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir) / CONVERSATIONS_DIR
            root.mkdir(parents=True)
            record = {
                "id": "deadbeef",
                "mode": "data",
                "title": "集团呆滞库存",
                "created_at": "2026-01-01T00:00:00+08:00",
                "updated_at": "2026-01-02T00:00:00+08:00",
                "messages": [{"role": "user", "content": "分析供应商账期"}],
                "chat_html": "chat",
                "dashboard_html": "dashboard",
                "ontology_html": "ontology",
                "tools_html": "tools",
                "llm_html": "llm",
                "source_config": {"database": "doris"},
            }
            path = root / "deadbeef.json"
            path.write_text(json.dumps(record, ensure_ascii=False), encoding="utf-8")
            (root / "history_index.json").write_text(
                json.dumps({"version": 1, "conversations": {
                    "deadbeef": {"id": "deadbeef", "title": "集团呆滞库存"}
                }}, ensure_ascii=False),
                encoding="utf-8",
            )
            store = ConversationStore(temp_dir)
            self.assertEqual(store.last_title_migrations, 1)
            self.assertEqual(store.get("deadbeef")["title"], "分析供应商账期")
            saved = json.loads(path.read_text(encoding="utf-8"))
            for field in ("messages", "chat_html", "dashboard_html", "ontology_html", "tools_html", "llm_html", "source_config"):
                self.assertEqual(saved[field], record[field], field)
            summary = store.list("data")[0]
            self.assertEqual(summary["title"], "分析供应商账期")
            index = json.loads((root / "history_index.json").read_text(encoding="utf-8"))
            self.assertEqual(index["conversations"]["deadbeef"]["title"], "分析供应商账期")
            self.assertEqual(ConversationStore(temp_dir).last_title_migrations, 0)

    def test_data_and_report_titles_are_isolated_and_follow_first_turn(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            store = ConversationStore(temp_dir)
            data = store.save(
                mode="data", title="错误标题", messages=[{"role": "user", "content": "看一下今年采购金额"}],
                chat_html="", dashboard_html="",
            )
            report = store.save(
                mode="report", title="错误标题", messages=[{"role": "user", "content": "集团呆滞库存是什么情况"}],
                chat_html="", dashboard_html="",
            )
            store.save(
                mode="data", title="后续问题", cid=data["id"], messages=[
                    {"role": "user", "content": "看一下今年采购金额"},
                    {"role": "user", "content": "采购金额为什么变化"},
                ], chat_html="", dashboard_html="",
            )
            summaries = {item["id"]: item for item in store.list()}
            self.assertEqual(summaries[data["id"]]["title"], "看一下今年采购金额")
            self.assertEqual(summaries[report["id"]]["title"], "集团呆滞库存是什么情况")

    def test_history_list_is_summary_only_and_indexed(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            conversations = ConversationStore(temp_dir)
            record = conversations.save(
                mode="data",
                title="采购金额是多少",
                messages=[
                    {"role": "user", "content": "采购金额是多少"},
                    {"role": "assistant", "content": "采购金额为 100"},
                ],
                chat_html="<div class='msg'>full chat</div>",
                dashboard_html="<div class='dash-card'>full dashboard</div>",
                ontology_html="<div>ontology</div>",
                tools_html="<div>tools</div>",
                llm_html="<div>llm</div>",
            )
            summary = conversations.list("data")[0]
            self.assertEqual(
                set(summary), {"id", "mode", "title", "first_user_question", "updated_at", "created_at", "turn_count", "message_count", "schema_version", "title_version"}
            )
            self.assertEqual(summary["turn_count"], 1)
            index = json.loads(
                (Path(temp_dir) / CONVERSATIONS_DIR / "history_index.json").read_text(encoding="utf-8")
            )
            index_text = json.dumps(index, ensure_ascii=False)
            self.assertNotIn("full chat", index_text)
            self.assertNotIn("full dashboard", index_text)
            self.assertNotIn("messages", index_text)
            self.assertEqual(index["conversations"][record["id"]]["title"], "采购金额是多少")

    def test_legacy_history_is_indexed_and_keeps_title_and_turn_count(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir) / CONVERSATIONS_DIR
            root.mkdir(parents=True)
            (root / "deadbeef.json").write_text(
                json.dumps({
                    "id": "deadbeef",
                    "mode": "report",
                    "created_at": "2026-01-01T00:00:00+08:00",
                    "updated_at": "2026-01-02T00:00:00+08:00",
                    "messages": [
                        {"role": "user", "content": "旧格式问题"},
                        {"role": "assistant", "content": "旧格式回答"},
                    ],
                    "chat_html": "legacy",
                }),
                encoding="utf-8",
            )
            conversations = ConversationStore(temp_dir)
            summary = conversations.list("report")[0]
            self.assertEqual(summary["title"], "旧格式问题")
            self.assertEqual(summary["turn_count"], 1)
            self.assertTrue((root / "history_index.json").exists())
            self.assertEqual(conversations.get("deadbeef")["chat_html"], "legacy")

    def test_local_history_list_never_waits_for_remote_sync(self) -> None:
        previous_store = STATE.conversation_store
        try:
            with tempfile.TemporaryDirectory() as temp_dir, patch(
                "bi_agent.web.app._conversation_sync"
            ) as sync:
                STATE.conversation_store = ConversationStore(temp_dir)
                response = TestClient(app).get("/api/conversations?mode=data")
                self.assertEqual(response.status_code, 200)
                sync.assert_not_called()
        finally:
            STATE.conversation_store = previous_store

    def test_preview_and_assets_are_separate(self) -> None:
        previous_store = STATE.conversation_store
        try:
            with tempfile.TemporaryDirectory() as temp_dir:
                store = ConversationStore(temp_dir)
                record = store.save(
                    mode="data",
                    title="轻量预览",
                    messages=[
                        {"role": "user", "content": "问题"},
                        {"role": "assistant", "content": "回答"},
                    ],
                    chat_html="<div class='full-chat'>chat</div>",
                    dashboard_html="<div class='dash-card'>dashboard</div>",
                    ontology_html="<div>ontology</div>",
                    tools_html="<div>tools</div>",
                    llm_html="<div>llm</div>",
                )
                STATE.conversation_store = store
                client = TestClient(app)
                preview = client.get(f"/api/conversations/{record['id']}/preview")
                self.assertEqual(preview.status_code, 200)
                preview_payload = preview.json()
                self.assertEqual(preview_payload["preview"][0]["text"], "问题")
                self.assertNotIn("messages", preview_payload)
                self.assertNotIn("dashboard_html", preview_payload)
                self.assertNotIn("ontology_html", preview_payload)
                self.assertEqual(preview_payload["chat_html_preview"], "")

                assets = client.get(f"/api/conversations/{record['id']}/assets")
                self.assertEqual(assets.status_code, 200)
                assets_payload = assets.json()
                self.assertEqual(assets_payload["dashboard_html"], "<div class='dash-card'>dashboard</div>")
                self.assertNotIn("messages", assets_payload)
        finally:
            STATE.conversation_store = previous_store

    def test_same_source_activation_skips_source_reload_and_ontology_migration(self) -> None:
        previous = {
            key: getattr(STATE, key)
            for key in (
                "conversation_store", "session", "agent_def", "ontology_store", "cwd",
                "ontology_path", "db_path", "use_doris", "retrieval_mode", "graph_path",
                "remote_ontology", "doris_api_url", "doris_jdbc_url", "doris_driver",
                "doris_username", "doris_database",
            )
        }
        try:
            with tempfile.TemporaryDirectory() as temp_dir, patch(
                "bi_agent.web.app._ensure_session"
            ) as ensure, patch("bi_agent.web.app.put_sources_endpoint") as put_sources, patch(
                "bi_agent.web.app._history_ontology_entities"
            ) as history_scan:
                store = ConversationStore(temp_dir)
                record = store.save(
                    mode="data",
                    title="同源恢复",
                    messages=[{"role": "user", "content": "问题"}],
                    chat_html="chat",
                    dashboard_html="dashboard",
                    ontology_html="already rendered",
                    source_config={
                        "ontology": "ontology.xlsx",
                        "database": "data.db",
                        "retrieval_mode": "semantic",
                    },
                )
                session = SimpleNamespace(
                    messages=[], pending_tool_use_id="old", pending_choice_spec={},
                    _pending_sibling_results=["old"],
                )
                STATE.conversation_store = store
                STATE.session = session
                STATE.agent_def = object()
                STATE.ontology_store = object()
                STATE.cwd = temp_dir
                STATE.ontology_path = "ontology.xlsx"
                STATE.db_path = "data.db"
                STATE.use_doris = False
                STATE.retrieval_mode = "semantic"
                STATE.graph_path = ""
                STATE.remote_ontology = None
                STATE.doris_api_url = ""
                STATE.doris_jdbc_url = ""
                STATE.doris_driver = ""
                STATE.doris_username = ""
                STATE.doris_database = ""
                response = TestClient(app).post(f"/api/conversations/{record['id']}/activate")
                self.assertEqual(response.status_code, 200)
                ensure.assert_not_called()
                put_sources.assert_not_called()
                history_scan.assert_not_called()
                self.assertEqual(session.messages[0]["content"], "问题")
                self.assertTrue(response.json()["context_restored"])
        finally:
            for key, value in previous.items():
                setattr(STATE, key, value)

    def test_missing_ontology_html_uses_legacy_migration_once(self) -> None:
        previous = {
            key: getattr(STATE, key)
            for key in (
                "conversation_store", "session", "agent_def", "ontology_store", "cwd",
                "ontology_path", "db_path", "use_doris", "retrieval_mode", "graph_path",
                "remote_ontology", "doris_api_url", "doris_jdbc_url", "doris_driver",
                "doris_username", "doris_database",
            )
        }
        try:
            with tempfile.TemporaryDirectory() as temp_dir, patch(
                "bi_agent.web.app._ensure_session"
            ), patch("bi_agent.web.app._history_ontology_entities", return_value=[] ) as history_scan:
                store = ConversationStore(temp_dir)
                record = store.save(
                    mode="data", title="旧本体", messages=[{"role": "user", "content": "问题"}],
                    chat_html="", dashboard_html="", ontology_html="",
                )
                STATE.conversation_store = store
                STATE.session = SimpleNamespace(
                    messages=[], pending_tool_use_id=None, pending_choice_spec=None,
                    _pending_sibling_results=[],
                )
                STATE.agent_def = object()
                STATE.ontology_store = object()
                STATE.cwd = temp_dir
                STATE.ontology_path = ""
                STATE.db_path = ""
                STATE.use_doris = False
                STATE.retrieval_mode = "semantic"
                STATE.graph_path = ""
                STATE.remote_ontology = None
                STATE.doris_api_url = STATE.doris_jdbc_url = STATE.doris_driver = ""
                STATE.doris_username = STATE.doris_database = ""
                response = TestClient(app).post(f"/api/conversations/{record['id']}/activate")
                self.assertEqual(response.status_code, 200)
                history_scan.assert_called_once()
        finally:
            for key, value in previous.items():
                setattr(STATE, key, value)

    def test_frontend_history_requests_have_one_owner_and_activation_gate(self) -> None:
        runtime = Path("frontend/src/runtime.js").read_text(encoding="utf-8")
        main = Path("frontend/src/main.jsx").read_text(encoding="utf-8")
        css = Path("frontend/src/workbench.css").read_text(encoding="utf-8")
        shell = Path("frontend/src/shell.html").read_text(encoding="utf-8")
        self.assertEqual(runtime.count("/api/conversations?mode="), 1)
        self.assertNotIn("/api/conversations?mode=", main)
        self.assertIn("conversationSummaryRequests", runtime)
        self.assertIn("event.detail?.conversations", main)
        self.assertIn("const eventMode = event.detail?.mode || \"data\"", main)
        self.assertIn("eventMode !== (document.body.dataset.mode || \"data\")", main)
        self.assertIn('window.addEventListener("bi-mode-changed", onMode)', main)
        self.assertIn("/preview", runtime)
        self.assertIn("/assets", runtime)
        self.assertIn("/activate", runtime)
        self.assertIn("restoreActivation", runtime)
        self.assertIn("Promise.allSettled", runtime)
        send_start = runtime.index("async function sendMessage")
        send_source = runtime[send_start:]
        self.assertLess(send_source.index("await (B().restoreActivation"), send_source.index("const url ="))
        self.assertLess(runtime.index("/preview"), runtime.index("/assets"))
        self.assertLess(runtime.index("/assets"), runtime.index("/activate"))
        self.assertIn("详情加载失败", runtime)
        self.assertIn("正在加载最近会话…", runtime)
        self.assertIn("recent-skeleton-row", runtime)
        self.assertIn("加载失败，点击重试", runtime)
        self.assertNotIn("history-restore-status", runtime)
        self.assertNotIn("会话已就绪", runtime)
        self.assertNotIn("history-restore-status", css)
        self.assertIn("history-chat-skeleton", runtime)
        self.assertIn("state.historyRestoring", runtime)
        self.assertIn("antd-recent-skeleton", main)
        self.assertNotIn("item.node?.click() ||", main)
        self.assertIn('recentStatus === "loading"', main)
        self.assertIn('recentStatus === "error"', main)
        self.assertIn("bi-conversations-retry", main)
        self.assertIn("正在加载最近会话…", shell)
        self.assertIn("background: #ffffff", css)
        self.assertIn("background-color: #ffffff", css)
        self.assertIn(".msg-user", css)
        self.assertIn(".antd-dashboard-bubble .ant-bubble-content", css)
        self.assertIn(".antd-result-card", css)
        self.assertIn(".antd-workflow-sop", css)
        self.assertIn("15.84px", css)
        self.assertIn("background: #1677ff !important", css)
        self.assertIn("color: #fff !important", css)
        self.assertIn("--thought-step-row-gap: 4px", css)
        self.assertIn("height: auto !important", css)
        self.assertIn("border-radius: 50% !important", css)
        self.assertIn('ToolStepIcon name={name} tone={tone}', main)
        self.assertIn("assistant-execution-block", runtime)
        self.assertIn("currentExecutionBlock", runtime)
        self.assertIn("#F7F9FC", css)
        self.assertIn("#2563EB", css)
        self.assertIn("#1E40AF", css)
        self.assertIn("#DBE4EC", css)
        self.assertIn("#DBEAFE", css)
        self.assertIn("#CCFBF1", css)
        self.assertIn("#FFEDD5", css)
        self.assertIn("#DCFCE7", css)
        self.assertIn("#FEF3C7", css)
        self.assertIn("#EDE9FE", css)
        self.assertIn("#FEE2E2", css)
        self.assertIn("pane.scrollTo({", runtime)
        self.assertIn("pane.scrollTop + cardRect.top - paneRect.top", runtime)
        self.assertIn("dashboardCards.find((card) => !card.classList.contains(\"dash-question\"))", runtime)
        self.assertIn("clearAssistantThinkingPlaceholder", runtime)
        choice_case = runtime[runtime.index('case "user_choice_requested"'):]
        self.assertLess(choice_case.index("clearAssistantThinkingPlaceholder()"), choice_case.index("attachChoiceCard(evt)"))
        self.assertIn("saveCurrentConversation({ allowEmpty: true })", runtime)
        self.assertIn("if (state.busy) return;", runtime[runtime.index("async function restoreConversation"):])
        restore_start = runtime.index("async function restoreConversation")
        restore_source = runtime[restore_start:runtime.index("// ------------------------------------------------------------------", restore_start + 1)]
        self.assertNotIn("activeRequestController.abort()", restore_source)
        self.assertIn("Persist the visible question before opening the SSE request", runtime)
        self.assertIn("assistant-execution-block", css)
        self.assertIn("--thinking-chain-row-width: 80%", css)
        self.assertIn("flex: 0 0 var(--thinking-chain-row-width)", css)
        self.assertIn("step.querySelectorAll(\":scope > .thinking-step\")", main)
        self.assertIn("--thinking-chain-block-gap: 8px", css)
        self.assertIn("TOOL_STEP_ICON_BY_NAME_COLORED", main)
        self.assertIn("inheritToolIconColor", main)
        self.assertIn("syncThoughtChainRail", main)
        self.assertIn("ResizeObserver", main)
        self.assertIn("--thought-step-rail-width", css)
        self.assertIn("--thought-step-rail-center-x", css)
        self.assertIn("z-index: 3 !important", css)
        self.assertIn("z-index: 4", css)
        self.assertIn("background: var(--thinking-color-soft", css)
        self.assertIn("thinking-step-body-shell", css)
        self.assertIn("transition: height", css)
        self.assertIn("collapsible={false}", main)
        self.assertIn("shell.style.height = next ?", main)

    def test_first_paint_defers_echarts_and_compresses_large_assets(self) -> None:
        index = Path("bi_agent/web/static/index.html").read_text(encoding="utf-8")
        runtime = Path("frontend/src/runtime.js").read_text(encoding="utf-8")
        self.assertNotIn('<script src="/static/vendor/echarts.min.js"></script>', index)
        self.assertIn('data-bi-echarts-loader', runtime)
        self.assertIn('src = "/static/vendor/echarts.min.js"', runtime)
        self.assertIn('id="initial-shell-skeleton"', index)
        self.assertIn('workbench.js?v=154" defer', index)
        self.assertIn('GZipMiddleware', Path("bi_agent/web/app.py").read_text(encoding="utf-8"))

        response = TestClient(app).get(
            "/static/vendor/antd/workbench.js?v=70",
            headers={"Accept-Encoding": "gzip"},
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.headers.get("content-encoding"), "gzip")

    def test_workspace_layout_follows_container_size(self) -> None:
        runtime = Path("frontend/src/runtime.js").read_text(encoding="utf-8")
        built = Path("bi_agent/web/static/vendor/antd/workbench.js").read_text(
            encoding="utf-8", errors="replace")
        # The layout is decided by the real .split container size, observed
        # through ResizeObserver — width > height means two columns.
        self.assertIn('const split = document.querySelector(".split")', runtime)
        self.assertIn("new ResizeObserver(", runtime)
        self.assertIn("observer.observe(split)", runtime)
        self.assertIn("entry.contentRect", runtime)
        self.assertIn('const nextMode = rect.width > rect.height ? "two" : "single"', runtime)
        # DOM is only touched when the decision actually changes.
        self.assertIn("if (nextMode === layoutMode) continue", runtime)
        # URL params remain only as a pre-measurement fallback.
        self.assertIn("routeLayoutMode()", runtime)
        self.assertIn("until the first ResizeObserver", runtime)
        # Existing viewport/refresh linkage keeps firing on mode changes.
        self.assertIn('document.body.dataset.layout = nextMode', runtime)
        self.assertIn('window.dispatchEvent(new CustomEvent("bi-viewport-mode"', runtime)
        self.assertIn('window.dispatchEvent(new Event("resize"))', runtime)
        self.assertIn("workspace-pane-switcher", built)
        self.assertIn("ResizeObserver", built)

    def test_single_column_switcher_centered_and_accessible(self) -> None:
        shell = Path("frontend/src/shell.html").read_text(encoding="utf-8")
        runtime = Path("frontend/src/runtime.js").read_text(encoding="utf-8")
        css = Path("frontend/src/workbench.css").read_text(encoding="utf-8")
        # The per-pane title-bar buttons were removed.
        self.assertNotIn("mobile-pane-switch", shell)
        self.assertNotIn("mobile-show-dashboard", shell)
        self.assertNotIn("mobile-show-chat", shell)
        # One unified switcher sits at the top of the workspace, before .split.
        switcher_index = shell.index('id="workspace-pane-switcher"')
        split_index = shell.index('class="split"')
        self.assertLess(switcher_index, split_index)
        # Real buttons with a pure separator; 会话 first, 看板 second.
        self.assertIn(
            '<button type="button" class="workspace-pane-tab" data-pane="chat" role="tab" aria-selected="true" aria-pressed="true">会话</button>',
            shell)
        self.assertIn(
            '<button type="button" class="workspace-pane-tab" data-pane="dashboard" role="tab" aria-selected="false" aria-pressed="false">看板</button>',
            shell)
        self.assertIn('<span class="workspace-pane-sep" aria-hidden="true">｜</span>', shell)
        self.assertIn('role="tablist"', shell)
        # Runtime wiring: click switches the pane and syncs aria/selected state.
        self.assertIn('tab.addEventListener("click", () => showMobilePane(tab.dataset.pane))', runtime)
        self.assertIn('tab.setAttribute("aria-selected"', runtime)
        self.assertIn('tab.setAttribute("aria-pressed"', runtime)
        self.assertIn("bi.layout.mobilePane", runtime)
        # Centered and only visible in single-column mode.
        self.assertIn(".workspace-pane-switcher {\n  display: none;", css)
        self.assertIn("justify-content: center", css)
        self.assertIn('body[data-layout="single"] .workspace-pane-switcher {\n  display: flex;', css)
        self.assertNotIn(".mobile-pane-switch", css)

    def test_dashboard_header_buttons_follow_layout_mode(self) -> None:
        css = Path("frontend/src/workbench.css").read_text(encoding="utf-8")
        # Two columns: the dashboard header drops its two right-side action
        # buttons (清空 / 折叠); the label row stays.
        self.assertIn('body[data-layout="two"] .dashboard-pane #dashboard-clear', css)
        self.assertIn('body[data-layout="two"] .dashboard-pane #dashboard-collapse', css)
        # Single column: pane title rows are replaced by the top switcher.
        self.assertIn('body[data-layout="single"] .chat-pane .pane-header', css)
        self.assertIn('body[data-layout="single"] .dashboard-pane .pane-header', css)
        self.assertIn("display: none !important", css)

    def test_share_button_is_dingtalk(self) -> None:
        runtime = Path("frontend/src/runtime.js").read_text(encoding="utf-8")
        css = Path("frontend/src/workbench.css").read_text(encoding="utf-8")
        built = Path("bi_agent/web/static/vendor/antd/workbench.js").read_text(
            encoding="utf-8", errors="replace")
        self.assertIn('class="dash-export-btn dash-dingtalk-btn"', runtime)
        self.assertIn("分享到钉钉", runtime)
        self.assertIn("shareTurnReportToDingTalk", runtime)
        self.assertIn("「分享到钉钉」为占位入口,暂未接入钉钉开放平台", runtime)
        self.assertNotIn("分享到飞书", runtime)
        self.assertIn("EXPORT_ACTION_ICONS.dingtalk", runtime)
        self.assertIn(".dash-dingtalk-btn", css)
        self.assertIn("dash-dingtalk-btn", built)

    def test_legacy_feishu_snapshot_normalized_to_dingtalk(self) -> None:
        runtime = Path("frontend/src/runtime.js").read_text(encoding="utf-8")
        start = runtime.index("function normalizeExportButtons(")
        end = runtime.index("function appendTurnExportButton(", start)
        normalize = runtime[start:end]
        # Old snapshot buttons are detected, converted and relabeled.
        self.assertIn('button.classList.contains("dash-feishu-btn")', normalize)
        self.assertIn('button.classList.remove("dash-feishu-btn")', normalize)
        self.assertIn('button.classList.add("dash-dingtalk-btn")', normalize)
        self.assertIn('"分享到钉钉"', normalize)
        # Restored cards bind their click to the canonical DingTalk button.
        bind_start = runtime.index("function bindExportCard(")
        bind_end = runtime.index("function renderTextCardForExport(", bind_start)
        bind = runtime[bind_start:bind_end]
        self.assertIn('card.querySelector(".dash-dingtalk-btn")', bind)
        self.assertIn("shareTurnReportToDingTalk(turnTag, card)", bind)

    def test_only_semantic_card_badges_remain_and_align_left(self) -> None:
        runtime = Path("frontend/src/runtime.js").read_text(encoding="utf-8")
        main = Path("frontend/src/main.jsx").read_text(encoding="utf-8")
        css = Path("frontend/src/workbench.css").read_text(encoding="utf-8")

        for obsolete_badge in (
            '<span class="chart-type">',
            '<span class="table-tag">',
            '<span class="multidim-tag">',
            '<span class="dash-tag chart">',
            '<span class="dash-tag table">',
        ):
            self.assertNotIn(obsolete_badge, runtime)
        for semantic_badge in (
            '<span class="dash-tag conclusion">',
            '<span class="dash-tag rootcause">',
            '<span class="dash-tag actions">',
        ):
            self.assertIn(semantic_badge, runtime)

        self.assertIn('.dash-tag:not(.conclusion):not(.rootcause):not(.actions)', css)
        self.assertIn(".antd-dashboard-result-head.antd-dashboard-action-head", css)
        self.assertIn("justify-content: flex-start", css)
        self.assertIn("head.prepend(semantic)", main)
        self.assertIn('head.querySelectorAll(":scope > .dash-tag:not(.conclusion):not(.rootcause):not(.actions)")', main)
        action_start = runtime.index("function appendChatActionCard")
        action_source = runtime[action_start:runtime.index("function dedupeTurnResultCards", action_start)]
        self.assertIn("window.antdDashboardCardMount(card)", action_source)
        self.assertIn('container.querySelectorAll(".dash-card:not(.antd-dashboard-question-hidden)")', main)

    def test_expanded_thought_card_uses_symmetric_inline_spacing(self) -> None:
        css = Path("frontend/src/workbench.css").read_text(encoding="utf-8")
        self.assertIn("--thought-step-content-inset: 25px", css)
        self.assertIn("padding: 4px var(--thought-step-content-inset) 7px", css)
        self.assertIn("padding: 4px var(--thought-step-content-inset) 0", css)
        self.assertIn(".thinking-step-body-shell", css)
        self.assertIn("box-sizing: border-box", css)

    def test_execution_steps_share_icon_map_and_history_timeline(self) -> None:
        main = Path("frontend/src/main.jsx").read_text(encoding="utf-8")
        runtime = Path("frontend/src/runtime.js").read_text(encoding="utf-8")
        css = Path("frontend/src/workbench.css").read_text(encoding="utf-8")
        step_source = main[main.index("function AntdStep"):main.index("function normalizeStepTimelineTree")]
        self.assertNotIn(">✓<", step_source)
        self.assertIn("TOOL_STEP_ICON_BY_NAME", main)
        for tool in (
            "OntologyQuery", "ListBusinessObjects", "TermDisambiguate",
            "MetricLookup", "EntityDescribe", "RelationLookup", "GraphContext",
            "GraphExpand", "SQLRun", "ListTables", "DescribeTable",
            "TableGenerate", "ChartGenerate", "ChartGenerateMultiDim", "AskUser",
        ):
            self.assertIn(f"  {tool}:", main)
        self.assertIn("window.antdNormalizeStepTimelines = normalizeStepTimelineTree", main)
        self.assertIn("window.antdNormalizeStepTimelines(el.chatScroll)", runtime)
        self.assertIn('container.classList.toggle("has-multiple-steps"', runtime)
        self.assertIn(".antd-step-timeline::before", css)
        self.assertIn(".antd-step-timeline:not(.has-multiple-steps)::before", css)
        self.assertIn(".antd-step-timeline > .step::before", css)
        self.assertIn(".antd-step-enhanced::before", css)
        self.assertIn(".antd-step-enhanced::after", css)
        self.assertIn(".antd-step-host .ant-thought-chain-item-content::before", css)
        self.assertIn(".antd-step-host .ant-thought-chain-item-header::before", css)
        self.assertIn(".antd-step-tool-icon", css)
        # The SOP check remains a separate component; only execution steps
        # lose the literal check glyph.
        self.assertIn("antd-sop-status-check", main)

    def test_new_conversation_id_does_not_overwrite_collision(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            conversations = ConversationStore(temp_dir)
            existing = Path(temp_dir) / CONVERSATIONS_DIR / "deadbeef.json"
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

    def test_same_client_id_concurrent_first_saves_remain_one_record(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            store = ConversationStore(temp_dir)
            from concurrent.futures import ThreadPoolExecutor
            def save(text: str) -> dict:
                return store.save(
                    mode="data", title="不可信标题", cid="cafebabe",
                    messages=[{"role": "user", "content": text}],
                    chat_html=text, dashboard_html="",
                )
            with ThreadPoolExecutor(max_workers=2) as pool:
                results = list(pool.map(save, ["第一问", "第二问"]))
            self.assertEqual({item["id"] for item in results}, {"cafebabe"})
            self.assertEqual(len(store.list("data")), 1)

    def test_exact_duplicate_migration_keeps_mapping_and_hides_duplicate(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            store = ConversationStore(temp_dir)
            messages = [{"role": "user", "content": "相同问题"}]
            first = store.save(mode="data", title="x", messages=messages, chat_html="short", dashboard_html="")
            second = store.save(mode="data", title="y", messages=messages, chat_html="longer result", dashboard_html="")
            # Force two physical records with distinct IDs to model legacy duplication.
            second_path = Path(temp_dir) / CONVERSATIONS_DIR / f"{second['id']}.json"
            second_data = json.loads(second_path.read_text(encoding="utf-8"))
            second_data["id"] = "deadbeef"
            (Path(temp_dir) / CONVERSATIONS_DIR / "deadbeef.json").write_text(json.dumps(second_data, ensure_ascii=False), encoding="utf-8")
            mappings = store.migrate_exact_duplicates()
            self.assertTrue(mappings)
            self.assertEqual(len(store.list("data")), 1)
            duplicate_id = mappings[0]["duplicate_id"]
            self.assertEqual(store.get(duplicate_id)["duplicate_of"], mappings[0]["duplicate_of"])

    def test_report_id_collision_and_metadata_failure_cleanup(self) -> None:
        parsed = ParseResult(ext=".pdf", page_count=1, text="示例")
        with tempfile.TemporaryDirectory() as temp_dir:
            reports = ReportStore(temp_dir)
            root = Path(temp_dir) / UPLOADED_REPORTS_DIR
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
                migrated = Path(temp_dir) / SPREADSHEETS_DIR / "data.xlsx"
                migrated.parent.mkdir(parents=True)
                migrated.touch()
                self.assertEqual(_cwd_file("data.xlsx", label="文件"), migrated.resolve())
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
                self.assertEqual(
                    [repo["databaseValue"] for repo in repos],
                    ["", ""],
                )
                self.assertIn("graph", payload["retrieval"])
                self.assertEqual(STATE.remote_ontology.calls, [1, 2])
        finally:
            STATE.cwd, STATE.remote_ontology, STATE.ontology_backend = previous

    def test_sources_api_does_not_expose_doris_password(self) -> None:
        previous = (STATE.cwd, STATE.doris_password)
        try:
            with tempfile.TemporaryDirectory() as temp_dir:
                STATE.cwd = temp_dir
                STATE.doris_password = "secret-that-must-not-leak"
                payload = json.loads(get_sources_endpoint().body)
                self.assertEqual(payload["doris"]["password"], "")
                self.assertNotIn("secret-that-must-not-leak", json.dumps(payload))
        finally:
            STATE.cwd, STATE.doris_password = previous

    def test_ontology_adapt_switch_is_visible_in_data_source_for_same_session(self) -> None:
        class FakeRemote:
            base_url = "http://ontology.test"
            repository_id = "1"
            namespace = "dev"
            app_id = "app"
            auth_token = "token"
            timeout = 10

        catalog = [
            {"id": "1", "name": "库一", "description": "", "namespace": "dev",
             "dorisDatabase": "ontology_one", "value": "__metaerp_repository__:1",
             "databaseValue": "__doris_repository__:1"},
            {"id": "2", "name": "库二", "description": "", "namespace": "test",
             "dorisDatabase": "ontology_two", "value": "__metaerp_repository__:2",
             "databaseValue": "__doris_repository__:2"},
        ]
        session_id = "ontology-adapt-ui-test"
        previous = {
            name: getattr(STATE, name) for name in (
                "cwd", "ontology_store", "remote_ontology", "ontology_backend",
                "ontology_namespace", "doris_database", "doris_api_url", "use_doris",
            )
        }
        old_context = STATE.source_contexts.pop(session_id, None)
        try:
            with tempfile.TemporaryDirectory() as temp_dir, patch(
                "bi_agent.web.app._remote_repository_catalog", return_value=catalog,
            ) as catalog_mock:
                STATE.cwd = temp_dir
                STATE.ontology_store = OntologyStore()
                STATE.remote_ontology = FakeRemote()
                STATE.ontology_backend = "production"
                STATE.ontology_namespace = "dev"
                STATE.doris_database = "ontology_one"
                STATE.doris_api_url = "http://doris.test/query"
                STATE.use_doris = True
                put_sources_endpoint(SourcesUpdate(
                    ontology="__metaerp_repository__:2", session_id=session_id,
                ))
                response = get_sources_endpoint(session_id)
                payload = json.loads(response.body)
                self.assertEqual(payload["ontology"]["active"], "__metaerp_repository__:2")
                self.assertEqual(payload["database"]["active"], "__doris_repository__:2")
                self.assertEqual(payload["doris"]["database"], "ontology_two")
                self.assertIn("no-store", response.headers["cache-control"])
                # The switch is session-local and must not change another user's source.
                self.assertEqual(STATE.doris_database, "ontology_one")
                marker = object()
                STATE.sessions[session_id] = marker
                # The already validated current pair can be re-saved even when
                # the manager catalog is temporarily unavailable.
                catalog_mock.reset_mock()
                catalog_mock.side_effect = RuntimeError("catalog should not be called")
                unchanged = json.loads(put_sources_endpoint(SourcesUpdate(
                    ontology="__metaerp_repository__:2",
                    database="__doris_repository__:2",
                    session_id=session_id,
                )).body)
                self.assertEqual(unchanged["changed"], [])
                self.assertIs(STATE.sessions[session_id], marker)
        finally:
            STATE.sessions.pop(session_id, None)
            STATE.source_contexts.pop(session_id, None)
            if old_context is not None:
                STATE.source_contexts[session_id] = old_context
            for name, value in previous.items():
                setattr(STATE, name, value)

    def test_roles_are_isolated_and_applied_to_named_session(self) -> None:
        class FakeSession:
            role_block = None

            def set_role_block(self, block):
                self.role_block = block

        first = "role-session-one"
        second = "role-session-two"
        old_first = STATE.sessions.get(first)
        old_roles = dict(STATE.roles_by_session)
        fake = FakeSession()
        try:
            STATE.sessions[first] = fake
            put_roles(RolesRequest(
                user_role="finance", agent_pref="audit", session_id=first,
            ))
            first_payload = json.loads(get_roles(first).body)
            second_payload = json.loads(get_roles(second).body)
            self.assertEqual(first_payload["user_role"], "finance")
            self.assertNotEqual(second_payload["user_role"], "finance")
            self.assertIn("财务分析师", fake.role_block)
            self.assertIn("严谨审计型", fake.role_block)
        finally:
            STATE.roles_by_session.clear()
            STATE.roles_by_session.update(old_roles)
            if old_first is None:
                STATE.sessions.pop(first, None)
            else:
                STATE.sessions[first] = old_first

    def test_detaching_reports_clears_only_the_current_browser_context(self) -> None:
        first = "report-detach-one"
        second = "report-detach-two"
        maps = (
            STATE.report_sessions,
            STATE.report_ids_by_session,
            STATE.report_db_by_session,
        )
        snapshots = [dict(mapping) for mapping in maps]
        try:
            STATE.report_sessions[first] = object()
            STATE.report_sessions[second] = object()
            STATE.report_ids_by_session[first] = ["report-a"]
            STATE.report_ids_by_session[second] = ["report-b"]
            STATE.report_db_by_session[first] = True
            STATE.report_db_by_session[second] = False
            response = TestClient(app).post(
                "/api/report/session/reset",
                params={"session_id": first, "clear_reports": "true"},
            )
            self.assertEqual(response.status_code, 200)
            self.assertNotIn(first, STATE.report_sessions)
            self.assertEqual(STATE.report_ids_by_session[first], [])
            self.assertEqual(STATE.report_ids_by_session[second], ["report-b"])
            self.assertIn(second, STATE.report_sessions)
        finally:
            for mapping, snapshot in zip(maps, snapshots):
                mapping.clear()
                mapping.update(snapshot)

    def test_source_switch_rolls_back_when_later_validation_fails(self) -> None:
        marker = object()
        fields = (
            "cwd", "ontology_store", "remote_ontology", "ontology_backend",
            "ontology_path", "db_path", "use_doris", "session",
            "report_session", "active_report_ids",
        )
        previous = {name: getattr(STATE, name) for name in fields}
        try:
            with tempfile.TemporaryDirectory() as temp_dir, patch(
                "bi_agent.web.app.OntologyStore.from_xlsx", return_value=marker
            ):
                STATE.cwd = temp_dir
                STATE.ontology_store = marker
                STATE.ontology_backend = "local"
                STATE.ontology_path = str(Path(temp_dir) / "old.xlsx")
                with self.assertRaises(HTTPException):
                    put_sources_endpoint(SourcesUpdate(ontology="new.xlsx", database="missing.db"))
                self.assertIs(STATE.ontology_store, marker)
                self.assertEqual(STATE.ontology_backend, "local")
                self.assertEqual(STATE.ontology_path, str(Path(temp_dir) / "old.xlsx"))
        finally:
            for name, value in previous.items():
                setattr(STATE, name, value)

    def test_selecting_remote_ontology_atomically_switches_its_doris_database(self) -> None:
        class FakeRemote:
            base_url = "http://ontology.test"
            repository_id = "1"
            app_id = "app"
            auth_token = "token"
            timeout = 10

            def list_repositories(self, *, page: int, size: int):
                return {
                    "items": [
                        {"id": 1, "name": "库一", "namespaceCode": "one", "dorisDatabase": "ontology_one"},
                        {"id": 2, "name": "库二", "namespaceCode": "two", "dorisDatabase": "ontology_two"},
                    ],
                    "total": 2,
                }

        fields = (
            "cwd", "ontology_store", "remote_ontology", "ontology_backend",
            "db_path", "use_doris", "doris_database", "doris_api_url",
            "session", "report_session", "active_report_ids",
        )
        previous = {name: getattr(STATE, name) for name in fields}
        try:
            with tempfile.TemporaryDirectory() as temp_dir, patch(
                "bi_agent.web.app.register_all"
            ):
                STATE.cwd = temp_dir
                STATE.ontology_store = OntologyStore()
                STATE.remote_ontology = FakeRemote()
                STATE.ontology_backend = "production"
                STATE.doris_api_url = "http://doris.test/query"
                response = put_sources_endpoint(SourcesUpdate(
                    ontology="__metaerp_repository__:2",
                ))
                payload = json.loads(response.body)
                self.assertEqual(STATE.remote_ontology.repository_id, "2")
                self.assertEqual(STATE.doris_database, "ontology_two")
                self.assertTrue(STATE.use_doris)
                self.assertEqual(payload["ontology"], "__metaerp_repository__:2")
                self.assertEqual(payload["database"], "__doris_repository__:2")
        finally:
            for name, value in previous.items():
                setattr(STATE, name, value)

    def test_selecting_remote_database_atomically_switches_its_ontology(self) -> None:
        class FakeRemote:
            base_url = "http://ontology.test"
            repository_id = "1"
            app_id = "app"
            auth_token = "token"
            timeout = 10

            def list_repositories(self, *, page: int, size: int):
                return {
                    "items": [
                        {"id": 1, "name": "库一", "namespaceCode": "one", "dorisDatabase": "ontology_one"},
                        {"id": 2, "name": "库二", "namespaceCode": "two", "dorisDatabase": "ontology_two"},
                    ],
                    "total": 2,
                }

        fields = (
            "cwd", "ontology_store", "remote_ontology", "ontology_backend",
            "db_path", "use_doris", "doris_database", "doris_api_url",
            "session", "report_session", "active_report_ids",
        )
        previous = {name: getattr(STATE, name) for name in fields}
        try:
            with tempfile.TemporaryDirectory() as temp_dir, patch(
                "bi_agent.web.app.register_all"
            ):
                STATE.cwd = temp_dir
                STATE.ontology_store = OntologyStore()
                STATE.remote_ontology = FakeRemote()
                STATE.ontology_backend = "production"
                STATE.doris_api_url = "http://doris.test/query"
                response = put_sources_endpoint(SourcesUpdate(
                    database="__doris_repository__:2",
                ))
                payload = json.loads(response.body)
                self.assertEqual(STATE.remote_ontology.repository_id, "2")
                self.assertEqual(STATE.doris_database, "ontology_two")
                self.assertTrue(STATE.use_doris)
                self.assertEqual(payload["ontology"], "__metaerp_repository__:2")
                self.assertEqual(payload["database"], "__doris_repository__:2")
        finally:
            for name, value in previous.items():
                setattr(STATE, name, value)


if __name__ == "__main__":
    unittest.main()


class _FakeTeamCompletions:
    def __init__(self, client):
        self._client = client

    def create(self, **kwargs):
        return self._client._create(**kwargs)


class _FakeTeamChat:
    def __init__(self, client):
        self.completions = _FakeTeamCompletions(client)


class _FakeTeamClient:
    """Minimal OpenAI-compatible stub that records every create() kwargs."""

    def __init__(self, *, error=None, text="ok"):
        self._error = error
        self._text = text
        self.requests: list[dict[str, Any]] = []

    @property
    def chat(self):
        return _FakeTeamChat(self)

    def _create(self, **kwargs):
        self.requests.append(kwargs)
        if self._error is not None:
            raise self._error
        yield SimpleNamespace(
            usage=SimpleNamespace(prompt_tokens=1, completion_tokens=2),
            choices=[SimpleNamespace(
                delta=SimpleNamespace(
                    content=self._text, reasoning_content=None, tool_calls=None
                ),
                finish_reason="stop",
            )],
        )


class TeamThinkingRoutingTests(unittest.TestCase):
    """Team gateway must route the DeepSeek-only ``thinking`` payload only
    to DeepSeek models.

    Regression for the Qwen 400: ``litellm.UnsupportedParamsError: openai
    does not support parameters: ['thinking']``.  These tests inspect the
    complete request kwargs handed to the OpenAI SDK, not just helper return
    values.
    """

    def _stream_request(self, model_id, *, thinking=False, deepseek_env=None,
                        legacy_env=None, qwen_env=None) -> dict[str, Any]:
        env = {}
        if deepseek_env is not None:
            env["TEAM_DEEPSEEK_ENABLE_THINKING"] = deepseek_env
        if legacy_env is not None:
            env["TEAM_ENABLE_THINKING"] = legacy_env
        if qwen_env is not None:
            env["TEAM_QWEN_ENABLE_THINKING"] = qwen_env
        for name in (
            "TEAM_DEEPSEEK_ENABLE_THINKING", "TEAM_ENABLE_THINKING",
            "TEAM_QWEN_ENABLE_THINKING",
        ):
            env.setdefault(name, "")
        client = _FakeTeamClient()
        with patch.dict(os.environ, env), \
             patch.object(provider_team, "_get_api_key", return_value="test-key"), \
             patch.object(provider_team, "OpenAI", return_value=client):
            events = list(provider_team.stream(
                model_id=model_id,
                messages=[],
                system_prompt="sys",
                allowed_tools=None,
                max_tokens=256,
                temperature=0.1,
                thinking=thinking,
            ))
        self.assertEqual(events[-1]["type"], "message_end")
        self.assertEqual(len(client.requests), 1)
        return client.requests[0]

    def test_deepseek_thinking_true_sends_enabled(self) -> None:
        request = self._stream_request("deepseek-v4-flash", thinking=True, deepseek_env="true")
        self.assertEqual(request["extra_body"], {"thinking": {"type": "enabled"}})

    def test_deepseek_thinking_false_sends_disabled(self) -> None:
        request = self._stream_request("deepseek-v4-flash", thinking=True, deepseek_env="false")
        self.assertEqual(request["extra_body"], {"thinking": {"type": "disabled"}})

    def test_deepseek_legacy_global_env_still_controls_deepseek(self) -> None:
        request = self._stream_request("deepseek-v4-pro", thinking=False, legacy_env="true")
        self.assertEqual(request["extra_body"], {"thinking": {"type": "enabled"}})

    def test_deepseek_without_env_uses_runtime_toggle(self) -> None:
        enabled = self._stream_request("deepseek-v4-flash", thinking=True)
        self.assertEqual(enabled["extra_body"], {"thinking": {"type": "enabled"}})
        disabled = self._stream_request("deepseek-v4-flash", thinking=False)
        self.assertEqual(disabled["extra_body"], {"thinking": {"type": "disabled"}})

    def test_qwen_never_receives_thinking_when_legacy_env_true(self) -> None:
        request = self._stream_request("Qwen/Qwen3-80B-AWQ", thinking=True, legacy_env="true")
        self.assertNotIn("extra_body", request)

    def test_qwen_never_receives_thinking_when_legacy_env_false(self) -> None:
        request = self._stream_request("Qwen/Qwen3-80B-AWQ", thinking=False, legacy_env="false")
        self.assertNotIn("extra_body", request)

    def test_qwen_runtime_thinking_true_sends_no_deepseek_field(self) -> None:
        request = self._stream_request("Qwen/Qwen3-80B-AWQ", thinking=True)
        self.assertNotIn("extra_body", request)

    def test_qwen37_plus_sends_no_deepseek_thinking(self) -> None:
        request = self._stream_request("qwen3.7-plus", thinking=True, legacy_env="true")
        self.assertNotIn("extra_body", request)

    def test_qwen37_plus_enable_thinking_requires_explicit_config(self) -> None:
        request = self._stream_request("qwen3.7-plus", thinking=True, qwen_env="true")
        self.assertEqual(request["extra_body"], {"enable_thinking": True})
        default = self._stream_request("qwen3.7-plus", thinking=True)
        self.assertNotIn("extra_body", default)

    def test_glm_never_receives_deepseek_thinking(self) -> None:
        request = self._stream_request("glm-5.1", thinking=True, legacy_env="true")
        self.assertNotIn("extra_body", request)

    def test_kimi_never_receives_deepseek_thinking(self) -> None:
        request = self._stream_request("kimi-k2.6", thinking=True, legacy_env="true")
        self.assertNotIn("extra_body", request)

    def test_moonshot_alias_and_glm_are_classified_as_own_family(self) -> None:
        self.assertEqual(provider_team._model_family("moonshot-v1-8k"), "kimi")
        self.assertEqual(provider_team._model_family("GLM-4.7"), "glm")
        self.assertEqual(provider_team._model_family("Qwen/Qwen3-80B-AWQ"), "qwen")

    def test_unknown_model_never_receives_deepseek_thinking(self) -> None:
        request = self._stream_request("some-other-model", thinking=True, legacy_env="true")
        self.assertNotIn("extra_body", request)

    def test_switch_from_deepseek_to_qwen_drops_thinking_payload(self) -> None:
        first = self._stream_request("deepseek-v4-flash", thinking=True, deepseek_env="true")
        second = self._stream_request("Qwen/Qwen3-80B-AWQ", thinking=True, legacy_env="true")
        self.assertEqual(first["extra_body"], {"thinking": {"type": "enabled"}})
        self.assertNotIn("extra_body", second)

    def test_switch_from_qwen_to_deepseek_regenerates_thinking_payload(self) -> None:
        first = self._stream_request("Qwen/Qwen3-80B-AWQ", thinking=True)
        second = self._stream_request("deepseek-v4-pro", thinking=True, deepseek_env="true")
        self.assertNotIn("extra_body", first)
        self.assertEqual(second["extra_body"], {"thinking": {"type": "enabled"}})

    def test_missing_env_variables_raise_no_exception(self) -> None:
        request = self._stream_request("Qwen/Qwen3-80B-AWQ", thinking=True)
        self.assertNotIn("extra_body", request)


class TeamThinkingRetryTests(unittest.TestCase):
    """A 400 ``UnsupportedParamsError(['thinking'])`` retries the current
    LLM request once with thinking disabled; other errors are surfaced
    unchanged and never retried."""

    def _session_events(self, fake_stream):
        cfg = SimpleNamespace(
            model_key="team-configured",
            max_tokens=256,
            temperature=0.1,
            effective_thinking=True,
        )
        with patch("bi_agent.web.session.get_llm_config", return_value=cfg), \
             patch("bi_agent.web.session.stream_message", fake_stream), \
             patch("bi_agent.web.session.get_model_id", return_value="Qwen/Qwen3-80B-AWQ"):
            session = WebSession("/tmp", AgentDef("test", tools=[]), OntologyStore())
            return list(session.generate_turn("test")), session

    def test_thinking_400_retries_once_with_thinking_disabled(self) -> None:
        calls: list[tuple[tuple, dict]] = []

        def fake_stream(*args, **kwargs):
            calls.append((args, dict(kwargs)))
            if len(calls) == 1:
                yield {"type": "error", "error": (
                    "Team API request failed: Error code: 400 - "
                    "{'error': {'message': \"litellm.UnsupportedParamsError: openai "
                    "does not support parameters: ['thinking'], for "
                    "model=Qwen/Qwen3-80B-AWQ\"}}"
                )}
            else:
                yield {"type": "text_delta", "text": "recovered"}
                yield {"type": "message_end", "stop_reason": "end_turn", "usage": {}}

        events, _ = self._session_events(fake_stream)
        self.assertEqual(len(calls), 2)
        self.assertTrue(calls[0][1]["thinking"])
        self.assertFalse(calls[1][1]["thinking"])
        # The retry reuses the exact same message list: no tool re-execution,
        # no restart from the beginning of the turn.
        self.assertEqual(calls[0][0], calls[1][0])
        self.assertEqual(
            "recovered",
            [e.get("text") for e in events if e.get("type") == "text_delta"][-1],
        )
        self.assertIn("llm_response", [e["type"] for e in events])
        self.assertNotIn("error", [e["type"] for e in events])

    def test_thinking_400_does_not_duplicate_tool_events(self) -> None:
        calls: list[dict] = []

        def fake_stream(*args, **kwargs):
            calls.append(dict(kwargs))
            if len(calls) == 1:
                yield {"type": "error", "error": (
                    "litellm.UnsupportedParamsError: openai does not support "
                    "parameters: ['thinking']"
                )}
            else:
                yield {"type": "tool_use_start", "id": "t1", "name": "run_sql"}
                yield {"type": "tool_use_end", "id": "t1", "name": "run_sql",
                       "input": {"query": "select 1"}}
                yield {"type": "message_end", "stop_reason": "end_turn", "usage": {}}

        events, _ = self._session_events(fake_stream)
        self.assertEqual(len(calls), 2)
        tool_inputs = [e for e in events if e["type"] == "tool_input"]
        self.assertEqual(len(tool_inputs), 1)

    def test_ordinary_400_is_not_retried(self) -> None:
        calls: list[dict] = []

        def fake_stream(*args, **kwargs):
            calls.append(dict(kwargs))
            yield {"type": "error", "error": "Team API request failed: Error code: 400 - bad request"}

        events, _ = self._session_events(fake_stream)
        self.assertEqual(len(calls), 1)
        self.assertTrue(any(e["type"] == "error" for e in events))

    def test_quota_429_is_not_retried_by_session_retry(self) -> None:
        calls: list[dict] = []

        def fake_stream(*args, **kwargs):
            calls.append(dict(kwargs))
            yield {"type": "error", "error": "Team API request failed: Error code: 429 - quota exceeded"}

        events, _ = self._session_events(fake_stream)
        self.assertEqual(len(calls), 1)
        self.assertTrue(any(e["type"] == "error" for e in events))

    def test_effective_thinking_false_never_triggers_retry(self) -> None:
        calls: list[dict] = []

        def fake_stream(*args, **kwargs):
            calls.append(dict(kwargs))
            yield {"type": "error", "error": (
                "litellm.UnsupportedParamsError: openai does not support "
                "parameters: ['thinking']"
            )}

        cfg = SimpleNamespace(
            model_key="team-configured",
            max_tokens=256,
            temperature=0.1,
            effective_thinking=False,
        )
        with patch("bi_agent.web.session.get_llm_config", return_value=cfg), \
             patch("bi_agent.web.session.stream_message", fake_stream), \
             patch("bi_agent.web.session.get_model_id", return_value="Qwen/Qwen3-80B-AWQ"):
            session = WebSession("/tmp", AgentDef("test", tools=[]), OntologyStore())
            events = list(session.generate_turn("test"))
        self.assertEqual(len(calls), 1)
        self.assertFalse(calls[0]["thinking"])
        self.assertTrue(any(e["type"] == "error" for e in events))


class _FakeUpstreamResponse:
    """Minimal urllib response double: context-manager body reader."""

    def __init__(self, body: bytes, status: int = 200):
        self.body = body
        self.status = status

    def read(self) -> bytes:
        return self.body

    def __enter__(self) -> "_FakeUpstreamResponse":
        return self

    def __exit__(self, *exc) -> bool:
        return False


class TaskAlertProxyTests(unittest.TestCase):
    """行动 → 转督办 proxy: real upstream integration, idempotency,
    validation and the frontend must not fake success."""

    def setUp(self) -> None:
        self.client = TestClient(app)
        with web_app_module._task_alert_lock:
            web_app_module._task_alert_successes.clear()
            web_app_module._task_alert_inflight.clear()

    def tearDown(self) -> None:
        with web_app_module._task_alert_lock:
            web_app_module._task_alert_successes.clear()
            web_app_module._task_alert_inflight.clear()

    def _env(self, **overrides) -> dict:
        values = {
            "TASK_ALERT_API_ENABLED": "true",
            "TASK_ALERT_API_URL": "http://upstream.example/manual-create",
            "TASK_ALERT_DEFAULT_ASSIGNEE": "400",
            "TASK_ALERT_DEFAULT_LEVEL": "WARNING",
            "TASK_ALERT_DEFAULT_BP_DEFINITION_ID": "",
            "TASK_ALERT_TIMEOUT_SECONDS": "10",
        }
        values.update(overrides)
        return values

    def _post(self, body, *, status_override=None):
        calls: list = []

        def fake_urlopen(request, timeout=None):
            calls.append({"request": request, "timeout": timeout})
            if status_override == "http-error":
                raise HTTPError(request.full_url, 400, "bad", {}, None)
            if status_override == "connection-error":
                raise URLError("network down")
            if status_override == "timeout":
                raise TimeoutError("timed out")
            return _FakeUpstreamResponse(
                '{"success":true,"code":200,"message":"操作成功","data":"T-10086"}'.encode("utf-8")
            )

        with patch("bi_agent.web.app.urlopen", side_effect=fake_urlopen), \
             patch.dict(os.environ, self._env(), clear=False):
            response = self.client.post("/api/task-alert/manual-create", json=body)
        return response, calls

    def test_upstream_request_field_mapping_and_defaults(self) -> None:
        response, calls = self._post({
            "title": " 大屏延迟 ", "content": "建议排查 SQL 耗时",
            "clientRequestId": "c-1",
        })
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json()["ok"])
        self.assertEqual(response.json()["taskId"], "T-10086")
        self.assertEqual(len(calls), 1)
        request = calls[0]["request"]
        self.assertEqual(request.full_url, "http://upstream.example/manual-create")
        self.assertEqual(request.method, "POST")
        self.assertIn("application/json", request.get_header("Content-type"))
        payload = json.loads(request.data)
        self.assertEqual(payload["title"], "大屏延迟")
        self.assertEqual(payload["content"], "建议排查 SQL 耗时")
        self.assertEqual(payload["assignee"], "400")
        self.assertEqual(payload["level"], "WARNING")
        self.assertNotIn("bpDefinitionId", payload)
        self.assertEqual(calls[0]["timeout"], 10.0)

    def test_bp_definition_matched_by_content_keyword(self) -> None:
        response, calls = self._post({
            "title": "回款异常督办", "content": "行动建议:跟进回款流程",
        })
        self.assertEqual(response.status_code, 200)
        payload = json.loads(calls[0]["request"].data)
        self.assertEqual(payload["bpDefinitionId"], 2081949636213985282)

    def test_bp_definition_sales_project_keyword(self) -> None:
        response, calls = self._post({
            "title": "销售项目跟进", "content": "建议推进投标事项",
        })
        self.assertEqual(response.status_code, 200)
        payload = json.loads(calls[0]["request"].data)
        self.assertEqual(payload["bpDefinitionId"], 2081949636117516289)

    def test_bp_definition_explicit_overrides_keyword(self) -> None:
        response, calls = self._post({
            "title": "回款异常督办", "content": "跟进回款", "bpDefinitionId": "55",
        })
        self.assertEqual(response.status_code, 200)
        payload = json.loads(calls[0]["request"].data)
        self.assertEqual(payload["bpDefinitionId"], 55)

    def test_explicit_fields_override_env_defaults(self) -> None:
        response, calls = self._post({
            "title": "t", "content": "c",
            "assignee": "99", "level": "ALERT", "bpDefinitionId": "55",
        })
        self.assertEqual(response.status_code, 200)
        payload = json.loads(calls[0]["request"].data)
        self.assertEqual(payload["assignee"], "99")
        self.assertEqual(payload["level"], "ALERT")
        self.assertEqual(payload["bpDefinitionId"], 55)

    def test_task_id_extracted_from_data_string(self) -> None:
        calls: list = []

        def fake_urlopen(request, timeout=None):
            calls.append(request)
            return _FakeUpstreamResponse(
                '{"success":true,"code":200,"message":"操作成功","data":"T-7788"}'.encode("utf-8")
            )

        with patch("bi_agent.web.app.urlopen", side_effect=fake_urlopen), \
             patch.dict(os.environ, self._env(), clear=False):
            response = self.client.post("/api/task-alert/manual-create",
                                        json={"title": "t", "content": "c"})
        self.assertEqual(response.json()["taskId"], "T-7788")

    def test_task_id_extracted_from_nested_dict_fallback(self) -> None:
        calls: list = []

        def fake_urlopen(request, timeout=None):
            calls.append(request)
            return _FakeUpstreamResponse(
                b'{"success":true,"code":200,"data":{"task_id":"T-NESTED"}}'
            )

        with patch("bi_agent.web.app.urlopen", side_effect=fake_urlopen), \
             patch.dict(os.environ, self._env(), clear=False):
            response = self.client.post("/api/task-alert/manual-create",
                                        json={"title": "t", "content": "c"})
        self.assertEqual(response.json()["taskId"], "T-NESTED")

    def test_missing_title_or_content_rejected(self) -> None:
        response, _ = self._post({"content": "c"})
        self.assertEqual(response.status_code, 422)
        response, _ = self._post({"title": "t"})
        self.assertEqual(response.status_code, 422)

    def test_level_must_be_alert_or_warning(self) -> None:
        response, _ = self._post({"title": "t", "content": "c", "level": "CRITICAL"})
        self.assertEqual(response.status_code, 422)

    def test_bp_definition_id_must_be_numeric(self) -> None:
        response, _ = self._post({"title": "t", "content": "c", "bpDefinitionId": "xxx"})
        self.assertEqual(response.status_code, 422)

    def test_missing_assignee_uses_env_defaults(self) -> None:
        calls: list = []

        def fake_urlopen(request, timeout=None):
            calls.append(request)
            return _FakeUpstreamResponse(
                '{"success":true,"code":200,"message":"操作成功","data":"T-ASGN"}'.encode("utf-8")
            )

        with patch("bi_agent.web.app.urlopen", side_effect=fake_urlopen), \
             patch.dict(os.environ, self._env(TASK_ALERT_DEFAULT_ASSIGNEE=""), clear=False):
            response = self.client.post("/api/task-alert/manual-create",
                                        json={"title": "t", "content": "c"})
        self.assertEqual(response.status_code, 200)
        payload = json.loads(calls[0].data)
        self.assertEqual(payload["assignee"], "400")

    def test_feature_flag_off_returns_403(self) -> None:
        with patch.dict(os.environ, self._env(TASK_ALERT_API_ENABLED="false"), clear=False):
            response = self.client.post("/api/task-alert/manual-create",
                                        json={"title": "t", "content": "c"})
        self.assertEqual(response.status_code, 403)

    def test_missing_api_url_returns_500(self) -> None:
        with patch.dict(os.environ, self._env(TASK_ALERT_API_URL=""), clear=False):
            response = self.client.post("/api/task-alert/manual-create",
                                        json={"title": "t", "content": "c"})
        self.assertEqual(response.status_code, 500)

    def test_upstream_http_error_is_not_success(self) -> None:
        response, calls = self._post(
            {"title": "t", "content": "c", "clientRequestId": "c-2"},
            status_override="http-error",
        )
        self.assertEqual(response.status_code, 502)
        self.assertIn("HTTP 400", response.json()["detail"])
        self.assertEqual(len(calls), 1)

    def test_upstream_business_failure_is_not_success(self) -> None:
        calls: list = []

        def failing_urlopen(request, timeout=None):
            calls.append(request)
            return _FakeUpstreamResponse(
                '{"success":false,"code":500,"message":"JSON parse error","data":null}'.encode("utf-8")
            )

        with patch("bi_agent.web.app.urlopen", side_effect=failing_urlopen), \
             patch.dict(os.environ, self._env(), clear=False):
            response = self.client.post("/api/task-alert/manual-create",
                                        json={"title": "t", "content": "c",
                                              "clientRequestId": "biz-fail-1"})
        self.assertEqual(response.status_code, 502)
        self.assertIn("JSON parse error", response.json()["detail"])
        self.assertEqual(len(calls), 1)
        # Business failure is not cached: a corrected retry may still succeed.
        with patch("bi_agent.web.app.urlopen", side_effect=failing_urlopen), \
             patch.dict(os.environ, self._env(), clear=False):
            retry = self.client.post("/api/task-alert/manual-create",
                                     json={"title": "t", "content": "c",
                                           "clientRequestId": "biz-fail-1"})
        self.assertEqual(retry.status_code, 502)
        self.assertEqual(len(calls), 2)

    def test_upstream_connection_failure_is_not_success(self) -> None:
        response, _ = self._post({"title": "t", "content": "c"},
                                 status_override="connection-error")
        self.assertEqual(response.status_code, 502)
        self.assertIn("连接失败", response.json()["detail"])

    def test_upstream_timeout_is_not_success(self) -> None:
        response, _ = self._post({"title": "t", "content": "c"},
                                 status_override="timeout")
        self.assertEqual(response.status_code, 504)
        self.assertIn("超时", response.json()["detail"])

    def test_duplicate_client_request_id_creates_only_once(self) -> None:
        body = {"title": "t", "content": "c", "clientRequestId": "dup-1"}
        first, calls = self._post(body)
        second, calls_after = self._post(body)
        self.assertEqual(first.status_code, 200)
        self.assertEqual(second.status_code, 200)
        self.assertEqual(second.json()["taskId"], first.json()["taskId"])
        self.assertEqual(len(calls), 1)
        self.assertEqual(len(calls_after), 0)

    def test_failed_submission_can_be_retried(self) -> None:
        attempts: list = []

        def flaky_urlopen(request, timeout=None):
            attempts.append(request)
            if len(attempts) == 1:
                raise HTTPError(request.full_url, 500, "boom", {}, None)
            return _FakeUpstreamResponse(b'{"taskId":"T-RETRY"}')

        body = {"title": "t", "content": "c", "clientRequestId": "retry-1"}
        with patch("bi_agent.web.app.urlopen", side_effect=flaky_urlopen), \
             patch.dict(os.environ, self._env(), clear=False):
            first = self.client.post("/api/task-alert/manual-create", json=body)
            second = self.client.post("/api/task-alert/manual-create", json=body)
        self.assertEqual(first.status_code, 502)
        self.assertEqual(second.status_code, 200)
        self.assertEqual(second.json()["taskId"], "T-RETRY")
        self.assertEqual(len(attempts), 2)

    def test_frontend_no_fake_success_logic(self) -> None:
        runtime = Path("frontend/src/runtime.js").read_text(encoding="utf-8")
        start = runtime.index("function dispatchSupervise(")
        end = runtime.index("function clauseText(", start)
        supervise = runtime[start:end]
        self.assertNotIn("localTaskSeq", runtime)
        self.assertNotIn("wbTaskOrderSeq", runtime)
        self.assertNotIn("cockpit-task-order", runtime)
        self.assertNotIn("setTimeout", supervise)
        self.assertNotIn("localStorage", supervise)
        self.assertNotIn("postMessage", supervise)
        self.assertIn('fetch("/api/task-alert/manual-create"', runtime)
        self.assertIn("clientRequestId", runtime)
        self.assertIn("data.ok", runtime)
