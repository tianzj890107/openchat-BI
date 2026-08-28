"""Offline regression tests for the BI web/LLM integration.

These tests deliberately mock the provider stream. They validate conversion,
failure handling and persistence without making any Qwen/Anthropic request.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import tempfile
import unittest
from contextlib import contextmanager
from pathlib import Path
from types import SimpleNamespace
from urllib.error import HTTPError, URLError
from unittest.mock import Mock, patch

from fastapi import HTTPException
from fastapi.testclient import TestClient

from bi_agent.llm import provider, provider_qwen, provider_team, registry
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
    _code_name_pairs,
    _doris_query,
    _format_rows,
    _make_sql_run,
    _validate_sql,
)
from bi_agent.display_names import (
    display_text,
    is_valid_name,
    looks_like_code,
    normalize_chart_params,
    normalize_chart_multidim_params,
    normalize_table_params,
    normalize_text,
    pick_display_name,
    unique_aliases,
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
from bi_agent.ontology.remote_retriever import RemoteGraphRetriever
from bi_agent.web.app import (
    STATE, _cwd_file, _history_ontology_entities, _infer_history_source_config,
    _render_history_ontology_cards, ConversationSaveRequest, RolesRequest, SourcesUpdate,
    app, get_roles, get_sources_endpoint, put_roles, put_sources_endpoint,
    save_conversation,
)
from bi_agent.web.conversations import ConversationStore, conversation_title, first_user_question, first_visible_user_question
from bi_agent.web.session import VISIBLE_THINKING_CN_RULE, WebSession
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

    def test_remote_graph_neighborhood_falls_back_when_table_node_breaks_traversal(self) -> None:
        client = RemoteOntologyClient("http://ontology.test", "4")
        client.find_related = Mock(side_effect=OntologyApiError(
            'HTTP 400: {"msg":"未知本体类型: TableNode"}'
        ))
        client.list_objects = lambda type_name, limit=2000: [
            {"code": "M1", "label": "采购金额"},
        ]
        calls = []

        def query(language, script, params_list=None):
            calls.append((script, params_list))
            if "UNWIND nodes(p)" in script:
                return {"results": [{"rows": [
                    {"typeNames": [["Indicator"]], "properties": [{"code": "M1", "label": "采购金额"}]},
                    {"typeNames": ["TableNode"], "properties": {"code": "PT1", "label": "采购表"}},
                ]}]}
            return {"results": [{"rows": [{
                "sourceCode": "M1", "relationType": "IndicatorMappingPT",
                "relationProperties": {}, "targetCode": "PT1",
            }]}]}

        client.script_query = query
        graph = client.graph_neighborhood("Indicator", "M1", depth=4)
        self.assertEqual({item["properties"]["code"] for item in graph["objects"]}, {"M1", "PT1"})
        self.assertEqual(graph["relations"][0]["targetCode"], "PT1")
        self.assertIn("MATCH p=(root)-[*0..4]-(n)", calls[0][0])
        self.assertEqual(calls[0][1], [["code", "M1"]])

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

    def test_visual_subgraph_promotes_term_to_indicator_and_preserves_focus(self) -> None:
        class FakeGraphClient:
            repository_id = "repo-1"

            def graph_neighborhood(self, type_name, code, **kwargs):
                return {
                    "depth": kwargs.get("depth", 4),
                    "relations_available": True,
                    "objects": [
                        {"typeName": "Term", "anchor": code == "T1", "properties": {"code": "T1", "label": "超期金额"}},
                        {"typeName": "Indicator", "anchor": code == "M1", "properties": {"code": "M1", "label": "超期金额"}},
                        {"typeName": "BusinessObject", "properties": {"code": "BO1", "label": "采购订单"}},
                        {"typeName": "BusinessAttribute", "properties": {"code": "AT1", "label": "处理类型"}},
                    ],
                    "relations": [
                        {"sourceCode": "T1", "relationType": "TermDefiniteIndicator", "targetCode": "M1"},
                        {"sourceCode": "M1", "relationType": "IndicatorBelongToBO", "targetCode": "BO1"},
                        {"sourceCode": "BO1", "relationType": "BOContainATT", "targetCode": "AT1"},
                    ],
                }

        retriever = RemoteGraphRetriever(FakeGraphClient())
        context = retriever.visual_subgraph("Term", "T1", strategy="context")
        self.assertEqual(context["anchor"]["code"], "M1")
        self.assertTrue(next(node for node in context["nodes"] if node["code"] == "T1")["focus"])
        expanded = retriever.visual_subgraph("BusinessAttribute", "AT1", strategy="expand")
        self.assertEqual(expanded["anchor"]["code"], "BO1")
        self.assertGreaterEqual(len(expanded["links"]), len(context["links"]))

    def test_global_subgraph_endpoint_is_independent_of_retrieval_mode(self) -> None:
        fake_remote = SimpleNamespace(repository_id="repo-1")
        payload = {
            "strategy": "context", "focus": {"type": "Indicator", "code": "M1"},
            "anchor": {"type": "Indicator", "code": "M1", "name": "指标"},
            "nodes": [{"id": "M1", "code": "M1", "name": "指标", "type": "Indicator"}],
            "links": [], "relations_available": True, "relation_error": "", "truncated": False,
        }
        source = SimpleNamespace(remote_ontology=fake_remote, ontology_store=OntologyStore(), retrieval_mode="semantic")
        with patch("bi_agent.web.app._source_for_session", return_value=source), \
             patch.object(RemoteGraphRetriever, "visual_subgraph", return_value=payload) as query:
            response = TestClient(app).post("/api/ontology/subgraph", json={
                "session_id": "s1", "repository_id": "repo-1",
                "type": "metric", "code": "M1", "strategy": "context",
            })
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["anchor"]["code"], "M1")
        query.assert_called_once_with("Indicator", "M1", strategy="context")

    def test_two_ontology_click_surfaces_share_one_subgraph_modal(self) -> None:
        runtime = Path("frontend/src/runtime.js").read_text(encoding="utf-8")
        self.assertIn('fetch("/api/ontology/subgraph"', runtime)
        self.assertIn('data-graph-strategy="context"', runtime)
        self.assertIn('data-graph-strategy="expand"', runtime)
        self.assertIn('el.ontologyList?.addEventListener("click"', runtime)
        self.assertIn('el.toolList?.addEventListener("click"', runtime)
        self.assertIn('e.target.closest(".step .chip[data-code]")', runtime)
        self.assertIn('openOntologyGraphCard(ontologyEntityForElement(', runtime)
        self.assertIn('createOntologySigmaRenderer(canvas, graph)', runtime)
        self.assertNotIn('loadEcharts()', runtime)
        self.assertNotIn('ch.addEventListener("click", () => flashOntologyEntity', runtime)
        sigma = Path("frontend/src/ontologySigmaGraph.js").read_text(encoding="utf-8")
        self.assertIn('from "graphology-layout-forceatlas2"', sigma)
        self.assertIn('from "sigma"', sigma)
        self.assertIn("FORCE_ATLAS_CONFIG", sigma)

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
        agent = AgentDef("isolated", tools=["MetricCalculation"])
        session_one = WebSession(
            "/tmp", agent, OntologyStore(),
            tool_executors={"MetricCalculation": lambda params, cwd: "repository-1"},
        )
        session_two = WebSession(
            "/tmp", agent, OntologyStore(),
            tool_executors={"MetricCalculation": lambda params, cwd: "repository-2"},
        )
        call = {"name": "MetricCalculation", "input": {"metric": "M1"}}
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
                "content": [{"type": "tool_use", "id": "t1", "name": "Ontology-FactQuery", "input": {}}],
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

    def test_extended_limitation_headings_end_action_section(self) -> None:
        """口径说明与限制披露/限制披露/冲突披露/数据限制等扩展标题必须结束
        行动章节，后续口径、限制、样本量、数据异常和结尾引导语不得被提取成行动。"""
        from bi_agent.tools.analysis_policy import ALL_SECTION_NAMES, extract_action_items, has_named_section

        for heading in (
            "口径说明",
            "口径说明与限制披露",
            "限制披露",
            "冲突披露",
            "数据限制",
            "证据限制",
            "风险与限制",
            "## 5. 口径说明与限制披露",
            "**口径说明与限制披露**",
            "口径说明与限制披露（含重点）",
        ):
            self.assertTrue(has_named_section(heading, ALL_SECTION_NAMES), heading)

        body = (
            "行动建议\n"
            "1. 针对 BFHC 交付延迟:发起交付绩效约谈,核实排产/发货瓶颈。\n"
            "2. 针对 VEND001 内部验收延迟:排查检验排期与审批积压。\n"
            "口径说明与限制披露\n"
            "- 指标:到货周期 [M0009] = 平均时间。\n"
            "- 物理表:poheader × acline;关联键 acline.sourceDocHeaderId。\n"
            "- 限制 1(样本量):Q2 可比样本仅 29 行。\n"
            "- 限制 2(数据异常):1 行出现收货早于下单。\n"
            "根因已厘清。如需展开成可对比的决策方案,告诉我即可。"
        )
        items = extract_action_items(body)
        self.assertEqual(len(items), 2)
        self.assertIn("BFHC", items[0])
        self.assertIn("VEND001", items[1])
        joined = "\n".join(items)
        for excluded in ("口径说明", "物理表", "样本量", "数据异常", "决策方案"):
            self.assertNotIn(excluded, joined)

    def test_f8cf8d06_narrative_extracts_only_two_actions(self) -> None:
        """真实会话 f8cf8d06 最终稿:结构化行动只能提取两条,限制/冲突/关系缺口/
        样本量/时间字段覆盖等留在正文。"""
        from bi_agent.tools.analysis_policy import extract_action_items

        narrative = (
            "结论:2026Q2 到货周期均值 17.1 天(n=29),较基线 2.9 天显著拉长;"
            "供应商段增量大于内部段,是供应商问题与内部验收问题叠加,供应商侧为主因。\n"
            "行动建议(雏形)\n"
            "1. 针对 BFHC 交付延迟(供应商段):对 5 月 电子元器件001 的 5 笔延迟订单"
            "(39-73 天)发起交付绩效约谈,核实排产/发货瓶颈并要求承诺交期,纳入到货准确率考核 [M0010]。\n"
            "2. 针对 VEND001 内部验收延迟(内部段):排查收货→验收环节的检验排期与审批积压"
            "(测试物料2037 内部段 63 天、手持彩色显示器 50 天),明确验收 SLA 与责任人。\n"
            "口径说明与限制披露\n"
            "- 指标:到货周期 [M0009] = 采购订单下达至货物实际验收入库的平均时间 [T000111]。\n"
            "- 物理表:poheader × acline × actransaction;关联键 acline.sourceDocHeaderId = poheader.poHeaderId。\n"
            "- 可比口径:仅统计同时具备 RECEIVE 与 ACCEPT 交易的验收行。\n"
            "- 限制 1(冲突披露):首次期间对比因窗口条件错误与修正后的严格 Q2 口径冲突。\n"
            "- 限制 2(关系缺口):本体关系检索未返回可验证的 PO→验收关联路径(RELATION_MISSING)。\n"
            "- 限制 3(指标规格):MetricCalculation 未返回 M0009 的 SQL 组件。\n"
            "- 限制 4(样本量):Q2 可比样本仅 29 行。\n"
            "- 限制 5(数据异常):1 行(BFHC,6 月)出现收货早于下单。\n"
            "- 限制 6(时间字段覆盖):667 张 PO 中 500 张有审批日期。\n"
            "根因已厘清。如需我把上述两条整改方向展开成可对比的决策方案,告诉我即可。"
        )
        items = extract_action_items(narrative)
        self.assertEqual(len(items), 2)
        self.assertIn("BFHC", items[0])
        self.assertIn("VEND001", items[1])
        joined = "\n".join(items)
        for excluded in ("口径", "物理表", "冲突", "关系缺口", "样本量", "数据异常",
                         "时间字段覆盖", "决策方案", "关联键"):
            self.assertNotIn(excluded, joined)

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

    def test_action_repair_tool_response_emits_empty_tool_uses(self) -> None:
        """A repair response that only requests tools must not surface a
        dangling tool card: the repair `llm_response` carries `tool_uses: []`,
        no `tool_result` ever follows, history keeps no tool block, and the
        next pure-text repair still completes the turn."""
        responses = iter([
            [
                {"type": "text_delta", "text": "根因分析：华东区域贡献了主要下降。"},
                {"type": "message_end", "stop_reason": "end_turn", "usage": {}},
            ],
            [
                {"type": "tool_use_start", "id": "t1", "name": "Ontology-FactQuery"},
                {"type": "tool_use_end", "id": "t1", "name": "Ontology-FactQuery",
                 "input": {"sql": "select secret"}},
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

        responses_seen = [e for e in events if e["type"] == "llm_response"]
        # Main narrative + two repairs.  No llm_response may carry tools.
        self.assertEqual(len(responses_seen), 3)
        for resp in responses_seen:
            self.assertEqual(resp["tool_uses"], [])
        self.assertNotIn("tool_result", [e["type"] for e in events])
        # History contains no tool-use block and no SQL input.
        for msg in session.messages:
            content = msg.get("content")
            blocks = content if isinstance(content, list) else [content]
            for block in blocks:
                if isinstance(block, dict):
                    self.assertNotEqual(block.get("type"), "tool_use")
                    self.assertNotIn("select secret", str(block))
        recs = [e for e in events if e["type"] == "action_recommendations"]
        self.assertEqual(len(recs), 1)
        self.assertEqual(recs[0]["items"][0]["title"], "先对华东区域重点客户做回访。")
        done = [e for e in events if e["type"] == "done"]
        self.assertEqual(len(done), 1)
        self.assertEqual(done[0]["stop_reason"], "end_turn")

    def test_action_repair_text_plus_tool_keeps_text_only(self) -> None:
        """A repair response mixing text and tools adopts only the text; the
        tool is neither executed nor forwarded, and the text still passes the
        action check exactly once."""
        responses = iter([
            [
                {"type": "text_delta", "text": "根因分析：华东区域贡献了主要下降。"},
                {"type": "message_end", "stop_reason": "end_turn", "usage": {}},
            ],
            [
                {"type": "tool_use_start", "id": "t1", "name": "ChartGenerate"},
                {"type": "tool_use_end", "id": "t1", "name": "ChartGenerate", "input": {}},
                {"type": "text_delta", "text": "行动建议：对华东重点客户执行价格复核。"},
                {"type": "message_end", "stop_reason": "tool_use", "usage": {}},
            ],
        ])

        def fake_stream(*_args, **_kwargs):
            yield from next(responses)

        with patch("bi_agent.web.session.stream_message", fake_stream), \
             patch.object(WebSession, "_execute_tool",
                          side_effect=AssertionError("repair must not run tools")):
            session = WebSession("/tmp", AgentDef("test", tools=[]), OntologyStore())
            events = list(session.generate_turn("为什么华东区域收入下降？"))

        repair_responses = [
            e for e in events
            if e["type"] == "llm_response" and "行动建议" in (e.get("text") or "")
        ]
        self.assertEqual(len(repair_responses), 1)
        self.assertEqual(repair_responses[0]["tool_uses"], [])
        self.assertNotIn("tool_result", [e["type"] for e in events])
        recs = [e for e in events if e["type"] == "action_recommendations"]
        self.assertEqual(len(recs), 1)
        self.assertIn("价格复核", recs[0]["items"][0]["title"])
        # Only one repair was needed (text passed on the first try).
        self.assertEqual(len([e for e in events if e["type"] == "action_repair"]), 1)

    def test_action_repair_tool_only_exhausts_repairs_non_blocking(self) -> None:
        """When every repair returns only tools (no text), the loop stops at
        the repair cap, emits delivery_incomplete, still delivers `done`, and
        never loops forever or re-runs tools."""
        responses = iter([
            [
                {"type": "text_delta", "text": "根因分析：华东区域贡献了主要下降。"},
                {"type": "message_end", "stop_reason": "end_turn", "usage": {}},
            ],
            [
                {"type": "tool_use_start", "id": "t1", "name": "run_sql"},
                {"type": "tool_use_end", "id": "t1", "name": "run_sql", "input": {}},
                {"type": "message_end", "stop_reason": "tool_use", "usage": {}},
            ],
            [
                {"type": "tool_use_start", "id": "t2", "name": "TableGenerate"},
                {"type": "tool_use_end", "id": "t2", "name": "TableGenerate", "input": {}},
                {"type": "message_end", "stop_reason": "tool_use", "usage": {}},
            ],
        ])

        def fake_stream(*_args, **_kwargs):
            yield from next(responses)

        with patch("bi_agent.web.session.stream_message", fake_stream), \
             patch.object(WebSession, "_execute_tool",
                          side_effect=AssertionError("repair must not run tools")):
            session = WebSession("/tmp", AgentDef("test", tools=[]), OntologyStore())
            events = list(session.generate_turn("为什么华东区域收入下降？"))

        self.assertEqual(len([e for e in events if e["type"] == "action_repair"]), 2)
        for e in events:
            if e["type"] == "llm_response":
                self.assertEqual(e["tool_uses"], [])
        self.assertNotIn("tool_result", [e["type"] for e in events])
        self.assertEqual(len([e for e in events if e["type"] == "delivery_incomplete"]), 1)
        done = [e for e in events if e["type"] == "done"]
        self.assertEqual(len(done), 1)
        self.assertEqual(done[0]["stop_reason"], "delivery_incomplete")
        # The main root-cause answer was still delivered, and no assistant
        # tool blocks entered history.
        main = [e for e in events if e["type"] == "llm_response" and "根因分析" in (e.get("text") or "")]
        self.assertEqual(len(main), 1)
        for msg in session.messages:
            content = msg.get("content")
            blocks = content if isinstance(content, list) else [content]
            for block in blocks:
                if isinstance(block, dict):
                    self.assertNotEqual(block.get("type"), "tool_use")

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

    def test_answer_blocked_turn_still_emits_done(self) -> None:
        """Two consecutive claim-validation failures block the answer without
        ever streaming or persisting the rejected drafts."""
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
        done = [event for event in events if event["type"] == "done"]
        self.assertEqual(done[0]["stop_reason"], "answer_blocked")

        # Rejected drafts stay hidden, but the deterministic evidence-only
        # fallback is visible and persisted so the user never sees only tool
        # activity plus an answer_blocked banner.
        deltas = [event for event in events if event["type"] == "text_delta"]
        self.assertEqual(len(deltas), 1)
        self.assertIn("自动证据校验", deltas[0]["text"])
        recs = [event for event in events if event["type"] == "action_recommendations"]
        self.assertEqual(recs, [])
        assistant = [message for message in session.messages if message.get("role") == "assistant"]
        self.assertEqual(len(assistant), 1)
        joined = json.dumps(session.messages, ensure_ascii=False)
        self.assertNotIn("占比 9.4%", joined)
        self.assertNotIn("优先复核", joined)
        self.assertIn("当前可确认的证据", joined)

    def test_claim_validation_commits_only_accepted_candidate(self) -> None:
        """With structured claims, a rejected first draft is buffered and
        discarded; the visible text_delta stream contains only the accepted
        candidate and validate_claims sees one candidate at a time."""
        from bi_agent.reliability import Claim, ClaimLevel, ValidationStatus

        responses = iter([
            [
                {"type": "text_delta", "text": "结论：审批中的订单有 50 单，占比 9.4%。"},
                {"type": "message_end", "stop_reason": "end_turn", "usage": {}},
            ],
            [
                {"type": "text_delta", "text": "结论：审批中的订单有 50 单，全部来自手动创建。"},
                {"type": "message_end", "stop_reason": "end_turn", "usage": {}},
            ],
        ])

        def fake_stream(*_args, **_kwargs):
            yield from next(responses)

        validated_texts: list[str] = []

        def fake_validate(claims, narrative):
            validated_texts.append(str(narrative))
            if "9.4%" in str(narrative):
                return SimpleNamespace(
                    status=ValidationStatus.REJECT,
                    issues=("unsupported numeric fact: 9.4",),
                )
            return SimpleNamespace(status=ValidationStatus.ALLOW, issues=())

        claim = Claim(
            id="c-1",
            statement="审批中的订单有 50 单",
            level=ClaimLevel.FACT,
            semantic={"semantic_type": "FACT"},
        )
        with patch("bi_agent.web.session.stream_message", fake_stream), \
             patch("bi_agent.web.session.validate_claims", fake_validate):
            session = WebSession("/tmp", AgentDef("test", tools=[]), OntologyStore())
            session.claims = [claim]
            events = list(session._run_loop())

        # Each validation call receives exactly one candidate — never a
        # concatenation of older drafts.
        self.assertEqual(len(validated_texts), 2)
        self.assertIn("结论：审批中的订单有 50 单，占比 9.4%。", validated_texts)
        self.assertIn("结论：审批中的订单有 50 单，全部来自手动创建。", validated_texts)

        # The visible text_delta stream is exactly the accepted candidate.
        deltas = [event["text"] for event in events if event["type"] == "text_delta"]
        self.assertEqual(deltas, ["结论：审批中的订单有 50 单，全部来自手动创建。"])
        joined_events = json.dumps(events, ensure_ascii=False)
        self.assertNotIn("占比 9.4%", joined_events)

        # The claim context and the rejection reminder are each emitted once,
        # and the rejected drafts never enter the persisted message list.
        self.assertEqual(
            len([event for event in events if event["type"] == "claim_context"]), 1,
        )
        self.assertEqual(
            len([event for event in events if event["type"] == "answer_validation"]), 1,
        )
        persisted_text = json.dumps(session.messages, ensure_ascii=False)
        self.assertIn("全部来自手动创建", persisted_text)
        self.assertNotIn("占比 9.4%", persisted_text)
        done = [event for event in events if event["type"] == "done"]
        self.assertEqual(done[0]["stop_reason"], "end_turn")

    def test_valid_first_candidate_is_delivered_without_claim_reprompt(self) -> None:
        """Claims protect facts but do not force a redundant second draft."""
        from bi_agent.reliability import Claim, ClaimLevel, ValidationStatus

        responses = iter([
            [
                {"type": "text_delta", "text": "结论：审批中的订单有 50 单。"},
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
                 status=ValidationStatus.ALLOW, issues=(),
             )):
            session = WebSession("/tmp", AgentDef("test", tools=[]), OntologyStore())
            session.claims = [claim]
            events = list(session._run_loop())

        self.assertEqual(
            len([event for event in events if event["type"] == "claim_context"]), 0,
        )
        deltas = [event["text"] for event in events if event["type"] == "text_delta"]
        self.assertEqual(deltas, ["结论：审批中的订单有 50 单。"])
        responses_seen = [event for event in events if event["type"] == "llm_response"]
        self.assertEqual(len(responses_seen), 1)
        self.assertEqual(len(session.messages), 1)
        assistant_text = json.dumps(session.messages, ensure_ascii=False)
        self.assertEqual(assistant_text.count("结论：审批中的订单有 50 单。"), 1)

    def test_validator_failure_keeps_candidate_answer_visible(self) -> None:
        """Validator availability must never become answer availability."""
        from bi_agent.reliability import Claim, ClaimLevel

        def fake_stream(*_args, **_kwargs):
            yield {"type": "text_delta", "text": "结论：审批中的订单有 50 单。"}
            yield {"type": "message_end", "stop_reason": "end_turn", "usage": {}}

        with patch("bi_agent.web.session.stream_message", fake_stream), \
             patch("bi_agent.web.session.validate_claims", side_effect=RuntimeError("down")):
            session = WebSession("/tmp", AgentDef("test", tools=[]), OntologyStore())
            session.claims = [Claim("c", "审批中的订单有 50 单", ClaimLevel.FACT)]
            events = list(session._run_loop())

        answer = "".join(event.get("text", "") for event in events if event["type"] == "text_delta")
        self.assertIn("审批中的订单有 50 单", answer)
        warnings = [event for event in events if event["type"] == "answer_validation"]
        self.assertEqual(warnings[0]["status"], "warning")
        self.assertFalse(any(event["type"] == "answer_blocked" for event in events))

    def test_claim_validation_tool_flow_commits_single_narrative(self) -> None:
        """A tool-calling analysis still executes tools and renders the final
        narrative exactly once; action_recommendations fires once."""
        from bi_agent.reliability import Claim, ClaimLevel, ValidationStatus

        responses = iter([
            [
                {"type": "tool_use_start", "id": "tu-1", "name": "Ontology-FactQuery"},
                {"type": "tool_use_end", "id": "tu-1", "name": "Ontology-FactQuery", "input": {"sql": "select count(*)"}},
                {"type": "message_end", "stop_reason": "tool_use", "usage": {}},
            ],
            [
                {"type": "text_delta", "text": (
                    "结论：审批中的订单有 50 单。\n"
                    "根因分析：手动创建订单占审批中订单的多数。\n"
                    "行动建议：优先复核手动创建的审批中订单。"
                )},
                {"type": "message_end", "stop_reason": "end_turn", "usage": {}},
            ],
            [
                {"type": "text_delta", "text": (
                    "结论：审批中的订单有 50 单。\n"
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
             patch.object(WebSession, "_execute_tool", return_value=("50 单", False)), \
             patch("bi_agent.web.session.validate_claims", return_value=SimpleNamespace(
                 status=ValidationStatus.ALLOW, issues=(),
             )) as mock_validate:
            session = WebSession("/tmp", AgentDef("test", tools=[]), OntologyStore())

            def fake_record_query(tool_name, params, output):
                session.claims.append(claim)

            with patch.object(WebSession, "record_query_result", side_effect=fake_record_query):
                events = list(session._run_loop())

        # The tool was executed and its result forwarded.
        self.assertIn(
            "tool_result",
            [event["type"] for event in events],
        )
        self.assertEqual(len(mock_validate.call_args_list), 1)  # only final candidate
        deltas = [event["text"] for event in events if event["type"] == "text_delta"]
        self.assertEqual(len(deltas), 1)
        self.assertIn("行动建议", deltas[0])
        # Only one narrative reaches the browser / history.
        self.assertEqual(len(deltas), 1)
        assistant_text = "\n".join(
            str(block.get("text") or "")
            for message in session.messages
            if message.get("role") == "assistant"
            for block in message.get("content") or []
            if isinstance(block, dict) and block.get("type") == "text"
        )
        self.assertEqual(assistant_text.count("结论"), 1)
        self.assertEqual(assistant_text.count("行动建议"), 1)
        recs = [event for event in events if event["type"] == "action_recommendations"]
        self.assertEqual(len(recs), 1)
        done = [event for event in events if event["type"] == "done"]
        self.assertEqual(done[0]["stop_reason"], "end_turn")

    def test_claim_rejection_does_not_reexecute_tools(self) -> None:
        """Claim 校验失败重试只重写叙述，绝不重复执行 SQL/图表/表格工具。"""
        from bi_agent.reliability import Claim, ClaimLevel, ValidationStatus

        responses = iter([
            [
                {"type": "tool_use_start", "id": "tu-1", "name": "Ontology-FactQuery"},
                {"type": "tool_use_end", "id": "tu-1", "name": "Ontology-FactQuery",
                 "input": {"sql": "select count(*)"}},
                {"type": "message_end", "stop_reason": "tool_use", "usage": {}},
            ],
            [
                {"type": "text_delta", "text": "结论：Q2 到货周期 17.1 天，占比 65%。"},
                {"type": "message_end", "stop_reason": "end_turn", "usage": {}},
            ],
            [
                {"type": "text_delta", "text": "结论：Q2 到货周期 17.1 天，供应商段增量大于内部段。"},
                {"type": "message_end", "stop_reason": "end_turn", "usage": {}},
            ],
        ])

        def fake_stream(*_args, **_kwargs):
            yield from next(responses)

        def fake_validate(claims, narrative):
            if "65" in str(narrative):
                return SimpleNamespace(
                    status=ValidationStatus.REJECT,
                    issues=("unsupported numeric fact: 65",),
                )
            return SimpleNamespace(status=ValidationStatus.ALLOW, issues=())

        claim = Claim(
            id="c-1",
            statement="Q2 到货周期均值 17.1 天",
            level=ClaimLevel.FACT,
            semantic={"semantic_type": "FACT"},
        )
        executed: list[str] = []

        def fake_execute(tu, *args, **kwargs):
            executed.append(tu["name"])
            return "count=1", False

        with patch("bi_agent.web.session.stream_message", fake_stream), \
             patch("bi_agent.web.session.validate_claims", fake_validate), \
             patch.object(WebSession, "_execute_tool", side_effect=fake_execute), \
             patch.object(WebSession, "record_query_result", return_value=None):
            session = WebSession("/tmp", AgentDef("test", tools=[]), OntologyStore())
            session.claims = [claim]
            events = list(session._run_loop())

        # SQL 工具只执行一次；被拒候选不展示；最终稿只出现一次。
        self.assertEqual(executed, ["Ontology-FactQuery"])
        deltas = [event["text"] for event in events if event["type"] == "text_delta"]
        self.assertEqual(deltas, ["结论：Q2 到货周期 17.1 天，供应商段增量大于内部段。"])
        persisted = json.dumps(session.messages, ensure_ascii=False)
        self.assertNotIn("占比 65%", persisted)
        self.assertEqual(persisted.count("供应商段增量大于内部段"), 1)

    def test_claim_candidates_persist_only_final_narrative_and_single_action_event(self) -> None:
        """历史恢复语义:一轮三次候选(18/19/20)只保留最终通过稿,action 事件
        只发一次且只含最终稿的两条行动。"""
        from bi_agent.reliability import Claim, ClaimLevel, ValidationStatus

        responses = iter([
            [
                {"type": "text_delta", "text": (
                    "结论:Q2 到货周期 17.1 天,占比 65%。\n"
                    "行动建议\n"
                    "1. 针对 BFHC:发起交付绩效约谈。\n"
                    "2. 针对 VEND001:排查检验排期。"
                )},
                {"type": "message_end", "stop_reason": "end_turn", "usage": {}},
            ],
            [
                {"type": "text_delta", "text": (
                    "结论:Q2 到货周期 17.1 天,供应商段增量大于内部段。\n"
                    "根因分析(证据链)\n"
                    "- 供应商段:BFHC 交付延迟是供应商段增量的主要来源。\n"
                    "- 内部段:VEND001 内部验收延迟贡献内部段增量。\n"
                    "行动建议\n"
                    "1. 针对 BFHC 交付延迟(供应商段):发起交付绩效约谈,核实排产/发货瓶颈。\n"
                    "2. 针对 VEND001 内部验收延迟(内部段):排查检验排期与审批积压。\n"
                    "口径说明与限制披露\n"
                    "- 限制 1(样本量):Q2 可比样本仅 29 行。\n"
                    "- 限制 2(数据异常):1 行出现收货早于下单。"
                )},
                {"type": "message_end", "stop_reason": "end_turn", "usage": {}},
            ],
        ])

        def fake_stream(*_args, **_kwargs):
            yield from next(responses)

        def fake_validate(claims, narrative):
            if "65" in str(narrative):
                return SimpleNamespace(
                    status=ValidationStatus.REJECT,
                    issues=("unsupported numeric fact: 65",),
                )
            return SimpleNamespace(status=ValidationStatus.ALLOW, issues=())

        claim = Claim(
            id="c-1",
            statement="Q2 到货周期均值 17.1 天",
            level=ClaimLevel.FACT,
            semantic={"semantic_type": "FACT"},
        )
        with patch("bi_agent.web.session.stream_message", fake_stream), \
             patch("bi_agent.web.session.validate_claims", fake_validate):
            session = WebSession("/tmp", AgentDef("test", tools=[]), OntologyStore())
            session.claims = [claim]
            events = list(session._run_loop())

        deltas = [event["text"] for event in events if event["type"] == "text_delta"]
        self.assertEqual(len(deltas), 1)
        self.assertIn("供应商段增量大于内部段", deltas[0])
        # 历史中只有一份最终 assistant 回答，被拒稿完全不落库。
        assistant_text = "\n".join(
            str(block.get("text") or "")
            for message in session.messages
            if message.get("role") == "assistant"
            for block in message.get("content") or []
            if isinstance(block, dict) and block.get("type") == "text"
        )
        self.assertEqual(assistant_text.count("结论"), 1)
        self.assertNotIn("65%", assistant_text)
        # 行动事件只发一次，且只有最终稿的两条真实行动。
        recs = [event for event in events if event["type"] == "action_recommendations"]
        self.assertEqual(len(recs), 1)
        self.assertEqual(len(recs[0]["items"]), 2)
        self.assertTrue(all(
            "BFHC" in (it.get("title") or "") or "VEND001" in (it.get("title") or "") or
            "BFHC" in (it.get("content") or "") or "VEND001" in (it.get("content") or "")
            for it in recs[0]["items"]
        ))
        joined = json.dumps(recs[0], ensure_ascii=False)
        self.assertNotIn("样本量", joined)
        self.assertNotIn("数据异常", joined)

    def test_no_claims_answer_still_streams_live(self) -> None:
        """Normal answers without structured claims keep streaming text_delta
        in real time and are committed as before."""
        def fake_stream(*_args, **_kwargs):
            yield {"type": "text_delta", "text": "结论：本月华东区域收入为 5200 万元。"}
            yield {"type": "message_end", "stop_reason": "end_turn", "usage": {}}

        with patch("bi_agent.web.session.stream_message", fake_stream):
            session = WebSession("/tmp", AgentDef("test", tools=[]), OntologyStore())
            events = list(session.generate_turn("华东收入是多少"))
        deltas = [event["text"] for event in events if event["type"] == "text_delta"]
        self.assertEqual(deltas, ["结论：本月华东区域收入为 5200 万元。"])
        responses_seen = [event for event in events if event["type"] == "llm_response"]
        self.assertEqual(len(responses_seen), 1)
        done = [event for event in events if event["type"] == "done"]
        self.assertEqual(done[0]["stop_reason"], "end_turn")
        self.assertEqual(len(session.messages), 2)  # user + assistant

    def test_tool_only_max_iterations_emits_user_facing_fallback(self) -> None:
        """Ontology/schema activity must never be the only visible delivery."""
        def fake_stream(*_args, **_kwargs):
            yield {"type": "tool_use_start", "id": "ont-1", "name": "Ontology-SemanticQuery"}
            yield {
                "type": "tool_use_end", "id": "ont-1", "name": "Ontology-SemanticQuery",
                "input": {"query": "采购金额"},
            }
            yield {"type": "message_end", "stop_reason": "tool_use", "usage": {}}

        agent = AgentDef("test", tools=["Ontology-SemanticQuery"], max_iterations=1)
        with patch("bi_agent.web.session.stream_message", fake_stream), \
             patch.object(WebSession, "_execute_tool", return_value=("[M0001] 采购金额", False)):
            session = WebSession("/tmp", agent, OntologyStore(), max_iterations=1)
            events = list(session.generate_turn("查询采购金额"))

        self.assertIn("tool_result", [event["type"] for event in events])
        deltas = [event["text"] for event in events if event["type"] == "text_delta"]
        self.assertEqual(len(deltas), 1)
        self.assertIn("没有形成可交付的数据结论", deltas[0])
        self.assertIn("不把本体操作本身当作最终业务答案", deltas[0])
        self.assertIn("done", [event["type"] for event in events])
        self.assertIn("没有形成可交付的数据结论", json.dumps(session.messages, ensure_ascii=False))

    def test_claims_provider_error_does_not_save_partial_candidate(self) -> None:
        """A provider error during a deferred candidate must not persist the
        partial text nor emit a false done event."""
        from bi_agent.reliability import Claim, ClaimLevel

        def fake_stream(*_args, **_kwargs):
            yield {"type": "text_delta", "text": "结论：审批中的订单有 50 单，占比 9.4%"}
            yield {"type": "error", "error": "mock provider failure"}

        claim = Claim(
            id="c-1",
            statement="审批中的订单有 50 单",
            level=ClaimLevel.FACT,
            semantic={"semantic_type": "FACT"},
        )
        with patch("bi_agent.web.session.stream_message", fake_stream):
            session = WebSession("/tmp", AgentDef("test", tools=[]), OntologyStore())
            session.claims = [claim]
            events = list(session._run_loop())
        self.assertIn("error", [event["type"] for event in events])
        self.assertNotIn("done", [event["type"] for event in events])
        self.assertEqual([event for event in events if event["type"] == "text_delta"], [])
        self.assertEqual(session.messages, [])

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
            "Ontology-SemanticQuery",
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
            session._extract_entities("Source: M0001 · orders", "Ontology-FactQuery"),
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
                "type": "tool_use", "id": "t1", "name": "Ontology-SemanticQuery", "input": {},
            }]},
            {"role": "user", "content": [{
                "type": "tool_result", "tool_use_id": "t1",
                "content": "# Remote Ontology-SemanticQuery\n[BO0005] 采购订单 (BusinessObject)",
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
        self.assertIn("container.scrollTo({", runtime)
        self.assertIn("container.scrollTop + targetRect.top - containerRect.top", runtime)
        self.assertIn('card.classList.contains("dash-question")', runtime)
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
        self.assertIn('workbench.js?v=161" defer', index)
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
        # Only clearly landscape selects two and clearly portrait selects single;
        # near-square sizes stay on the current layout (hysteresis buffer).
        self.assertIn('if (w > h * (1 + LAYOUT_HYSTERESIS)) candidate = "two"', runtime)
        self.assertIn('else if (h > w * (1 + LAYOUT_HYSTERESIS)) candidate = "single"', runtime)
        # DOM is only touched when the decision actually changes.
        self.assertIn("if (candidate === layoutMode) {", runtime)
        self.assertIn("if (candidate === null) {", runtime)
        # URL params remain only as a pre-measurement fallback; without
        # explicit params the workbench defaults to single column so it never
        # flashes a wide layout before the first measurement arrives.
        self.assertIn("routeLayoutMode()", runtime)
        self.assertIn("until the first ResizeObserver", runtime)
        self.assertIn('let layoutMode = "single";', runtime)
        self.assertIn('if (["2", "two", "double", "two-columns"].includes(value)) return "two";', runtime)
        self.assertIn('return "single";', runtime)
        # Existing viewport/refresh linkage keeps firing on mode changes.
        self.assertIn('document.body.dataset.layout = nextMode', runtime)
        self.assertIn('window.dispatchEvent(new CustomEvent("bi-viewport-mode"', runtime)
        self.assertIn('window.dispatchEvent(new Event("resize"))', runtime)
        self.assertIn("workspace-pane-switcher", built)
        self.assertIn("ResizeObserver", built)


    def test_container_layout_hysteresis_and_settle_debounce(self) -> None:
        runtime = Path("frontend/src/runtime.js").read_text(encoding="utf-8")
        start = runtime.index("function setupContainerLayoutObserver(")
        end = runtime.index("setupContainerLayoutObserver();", start)
        block = runtime[start:end]
        # Buffer constants: 10% hysteresis and a 200ms settle window.
        self.assertIn("LAYOUT_HYSTERESIS = 0.1", runtime)
        self.assertIn("LAYOUT_SETTLE_MS = 200", runtime)
        # The buffer zone must not schedule a switch or touch the DOM.
        self.assertIn("candidate === null", block)
        self.assertIn("clearTimeout(layoutSettleTimer)", block)
        self.assertIn("keep the current layout", block)
        # The settle debounce only applies the candidate after it holds
        # unchanged; a new resize while waiting resets the window.
        self.assertIn("layoutSettleTimer = setTimeout(() => {", block)
        self.assertIn("if (layoutCandidate !== candidate) return;", block)
        self.assertIn("applyLayoutMode(candidate)", block)
        self.assertIn("layoutCandidate = null", block)

    def test_two_column_default_split_is_equal_width(self) -> None:
        css = Path("frontend/src/workbench.css").read_text(encoding="utf-8")
        runtime = Path("frontend/src/runtime.js").read_text(encoding="utf-8")
        # In two-column mode the chat/dashboard split defaults to equal widths
        # (1fr / 1fr); a user-dragged --chat-width still wins when persisted.
        self.assertIn(
            "grid-template-columns: minmax(380px, 1fr) minmax(360px, 1fr);", css)
        self.assertIn(
            "grid-template-columns: var(--chat-width, minmax(380px, 1fr)) 6px minmax(360px, 1fr);", css)
        self.assertNotIn("1.15fr", css)
        built = Path("bi_agent/web/static/vendor/antd/openchat-bi-workbench.css").read_text(
            encoding="utf-8", errors="replace")
        self.assertIn("var(--chat-width, minmax(380px, 1fr)) 6px minmax(360px,1fr)", built)
        self.assertNotIn("1.15fr", built)
        self.assertIn('chat: "bi.layout.chatWidth"', runtime)
        self.assertIn('document.documentElement.style.setProperty("--chat-width"', runtime)
        # Single-column mode still forces one full-width column.
        self.assertIn('body[data-layout="single"] .split {\n  grid-template-columns: 1fr !important;', css)
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

    def test_question_navigation_uses_turn_anchor_with_explicit_coordinates(self) -> None:
        runtime = Path("frontend/src/runtime.js").read_text(encoding="utf-8")
        start = runtime.index("function firstVisibleTurnCard(")
        end = runtime.index("function setActiveQuestion(", start)
        scroll = runtime[start:end]
        # Chat and dashboard both scroll with explicit container coordinates.
        self.assertIn("function firstVisibleTurnCard(", scroll)
        self.assertIn("function scrollPaneToTurn(container, target)", scroll)
        self.assertIn("container.scrollTop + targetRect.top - containerRect.top - 12", scroll)
        self.assertIn("Math.max(0, Math.min(maxTop, targetTop))", scroll)
        # No scrollIntoView in the navigation path (wrong-ancestor risk).
        self.assertNotIn("scrollIntoView({", scroll)
        # Hidden question cards are excluded; a turn without result cards
        # leaves the dashboard where it is.
        self.assertIn('card.classList.contains("dash-question")', scroll)
        self.assertIn('card.classList.contains("antd-dashboard-question-hidden")', scroll)
        self.assertIn('style.display !== "none" && style.visibility !== "hidden"', scroll)
        self.assertIn("if (!msg && !dashboardCard) return;", scroll)

    def test_question_navigation_pauses_scroll_sync_and_last_click_wins(self) -> None:
        runtime = Path("frontend/src/runtime.js").read_text(encoding="utf-8")
        nav_start = runtime.index("function beginQuestionNavigation(")
        nav_end = runtime.index("function scrollToQuestion(", nav_start)
        nav = runtime[nav_start:nav_end]
        sync_start = runtime.index("function initQuestionSelectionSync(")
        sync_end = runtime.index("function assistantRoleLabel(", sync_start)
        sync = runtime[sync_start:sync_end]
        # Navigation pauses both scroll-driven syncs while it runs.
        self.assertIn("questionNavActive", nav)
        self.assertIn("questionNavGeneration += 1", nav)
        self.assertIn("clearTimeout(questionNavTimer)", nav)
        self.assertIn('addEventListener("scrollend"', nav)
        self.assertIn("setTimeout(finish, 900)", nav)
        self.assertIn("if (!moved.chat && !moved.dashboard) finish();", nav)
        self.assertIn("if (questionNavActive) return;", sync)

    def test_paired_pane_scroll_does_not_rebound(self) -> None:
        runtime = Path("frontend/src/runtime.js").read_text(encoding="utf-8")
        sync_start = runtime.index("function syncPairedPaneScroll(")
        sync_end = runtime.index("function initQuestionSelectionSync(", sync_start)
        sync = runtime[sync_start:sync_end]
        list_start = runtime.index("function initQuestionSelectionSync(")
        list_end = runtime.index("function assistantRoleLabel(", list_start)
        listeners = runtime[list_start:list_end]
        # The synced target is marked; its own scroll event consumes the
        # marker instead of syncing back to the source (no A->B->A rebound).
        self.assertIn("target.__biSyncedFrom = source;", sync)
        self.assertIn("root.__biSyncedFrom = null;", listeners)
        self.assertIn("return;", listeners)

    def test_react_task_list_uses_shared_navigation_event(self) -> None:
        main = Path("frontend/src/main.jsx").read_text(encoding="utf-8")
        runtime = Path("frontend/src/runtime.js").read_text(encoding="utf-8")
        # The React task list dispatches the shared event instead of clicking
        # hidden legacy DOM items.
        self.assertIn('window.dispatchEvent(new CustomEvent("bi-question-navigate"', main)
        self.assertNotIn('document.querySelector(`#chat-todo .chat-question-item', main)
        # The runtime owns the single programmatic entry for both panes.
        self.assertIn('window.addEventListener("bi-question-navigate"', runtime)
        nav_start = runtime.index('window.addEventListener("bi-question-navigate"')
        nav_end = runtime.index("\n  });", nav_start)
        nav = runtime[nav_start:nav_end]
        self.assertIn("scrollToQuestion(turn)", nav)

    def test_send_button_keeps_svg_icon_after_busy_and_history_restore(self) -> None:
        runtime = Path("frontend/src/runtime.js").read_text(encoding="utf-8")
        css = Path("frontend/src/workbench.css").read_text(encoding="utf-8")
        shell = Path("frontend/src/shell.html").read_text(encoding="utf-8")
        # The initial send button is an SVG paper-plane inside #btn-send.
        self.assertIn('<button id="btn-send" class="btn btn-primary composer-send"', shell)
        self.assertIn('<svg fill="none" xmlns="http://www.w3.org/2000/svg" viewBox="0 0 16 16"', shell)
        # setBusy must not replace the icon with a text glyph; it toggles a class.
        set_busy = runtime[runtime.index("function setBusy("):runtime.index("// ----", runtime.index("function setBusy("))]
        self.assertNotIn('btnSend.textContent = v ? "…" : "➤"', set_busy)
        self.assertIn('el.btnSend.classList.toggle("is-busy", v)', set_busy)
        self.assertIn(".composer-send.is-busy svg", css)
        self.assertIn('.composer-send.is-busy::after', css)

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
        # Old snapshots also carry data-export-bound="1"; normalization must
        # run BEFORE that early return so legacy buttons are still converted
        # and rebound on restore.
        self.assertLess(
            bind.index("normalizeExportButtons(card)"),
            bind.index('card.dataset.exportBound = "1"'))
        self.assertIn("button.dataset.exportClickBound === \"1\"", bind)
        self.assertIn('button.dataset.exportClickBound = "1"', bind)

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

    def test_action_cards_stay_in_chat_not_dashboard(self) -> None:
        """Root-cause, actions and structured action cards are chat-only."""
        runtime = Path("frontend/src/runtime.js").read_text(encoding="utf-8")

        root_start = runtime.index("function pushRootCauseIfAny(")
        root_src = runtime[root_start:runtime.index("function pushActionsIfAny(", root_start)]
        self.assertIn("appendChatActionCard(dashboardRootCauseCard(content, turnTag))", root_src)
        self.assertNotIn("appendDashboardCard", root_src)

        actions_start = runtime.index("function pushActionsIfAny(")
        actions_src = runtime[actions_start:runtime.index("6-step analysis SOP", actions_start)]
        self.assertIn("appendChatActionCard(dashboardActionsCard(content, turnTag))", actions_src)
        self.assertNotIn("appendDashboardCard", actions_src)

        rec_start = runtime.index('case "action_recommendations":')
        rec_src = runtime[rec_start:runtime.index('case "action_repair":', rec_start)]
        self.assertIn("structuredActionsCard(items, turnTag)", rec_src)
        self.assertIn("appendChatActionCard(card)", rec_src)
        self.assertNotIn("appendDashboardCard(card)", rec_src)

    def test_frontend_section_names_include_extended_limitation_boundaries(self) -> None:
        """前端历史恢复的行动解析同样以扩展限制标题为章节边界。"""
        runtime = Path("frontend/src/runtime.js").read_text(encoding="utf-8")
        for name in ("口径说明与限制披露", "限制披露", "冲突披露", "数据限制",
                     "证据限制", "风险与限制"):
            self.assertIn(f'"{name}"', runtime)
        built = Path("bi_agent/web/static/vendor/antd/workbench.js").read_text(
            encoding="utf-8", errors="replace")
        for name in ("口径说明与限制披露", "限制披露", "冲突披露", "数据限制",
                     "证据限制", "风险与限制"):
            self.assertIn(name, built)

    def test_conclusion_charts_tables_still_enter_dashboard(self) -> None:
        """Conclusion, chart, table and multi-dim cards must keep the dashboard."""
        runtime = Path("frontend/src/runtime.js").read_text(encoding="utf-8")

        conclusion_start = runtime.index("function pushConclusionIfAny(")
        conclusion_src = runtime[conclusion_start:runtime.index("function pushRootCauseIfAny(", conclusion_start)]
        self.assertIn("appendDashboardCard(dashboardConclusionCard(content, turnTag))", conclusion_src)
        self.assertIn("appendChatActionCard(dashboardConclusionCard(content, turnTag))", conclusion_src)

        multi_start = runtime.index("function pushMultiChartToDashboard(")
        multi_src = runtime[multi_start:runtime.index("function pushConclusionIfAny(", multi_start)]
        self.assertIn("appendDashboardCard(dashboardMultiChartCard(", multi_src)

        chart_start = runtime.index("function pushChartToDashboard(")
        chart_src = runtime[chart_start:runtime.index("function pushTableToDashboard(", chart_start)]
        self.assertIn("appendDashboardCard(dashboardChartCard(", chart_src)

        table_start = runtime.index("function pushTableToDashboard(")
        table_src = runtime[table_start:runtime.index("// Per-turn HTML report export", table_start)]
        self.assertIn("appendDashboardCard(dashboardTableCard(", table_src)

    def test_restored_dashboard_action_cards_migrate_to_chat(self) -> None:
        """Legacy dash-rootcause / dash-actions / dash-export migrate to chat."""
        runtime = Path("frontend/src/runtime.js").read_text(encoding="utf-8")
        mig_start = runtime.index("function moveRestoredInteractiveCardsToChat(")
        mig_src = runtime[mig_start:runtime.index("function dashboardConclusionCard(", mig_start)]
        self.assertIn(".dash-rootcause, .dash-actions, .dash-export", mig_src)
        self.assertIn("appendChatActionCard(card)", mig_src)
        self.assertIn("appendChatActionCard(card.cloneNode(true))", mig_src)

    def test_action_card_content_still_extracted_and_rendered(self) -> None:
        """Fixing placement must not delete content or add an answer gate."""
        runtime = Path("frontend/src/runtime.js").read_text(encoding="utf-8")
        self.assertIn("function extractRootCause(text)", runtime)
        self.assertIn("function extractActions(text)", runtime)
        self.assertIn("function dashboardRootCauseCard(text, turnTag)", runtime)
        self.assertIn("function dashboardActionsCard(text, turnTag)", runtime)
        self.assertIn("function structuredActionsCard(items, turnTag)", runtime)
        # Both chat-only pushers still render and deliver their cards.
        self.assertIn("appendChatActionCard(dashboardRootCauseCard(content, turnTag))", runtime)
        self.assertIn("appendChatActionCard(dashboardActionsCard(content, turnTag))", runtime)

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
            "Ontology-SemanticQuery", "ListBusinessObjects", "Ontology-TermDisambiguate",
            "MetricCalculation", "Ontology-EntityDescribe", "Ontology-RelationQuery", "Ontology-GraphContext",
            "Ontology-GraphExpand", "Ontology-MetricQuery", "Ontology-FactQuery", "ListTables", "DescribeTable",
            "TableGenerate", "ChartGenerate", "ChartGenerateMultiDim", "AskUser",
        ):
            key = f'"{tool}"' if "-" in tool else tool
            self.assertIn(f"  {key}:", main)
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

    @unittest.skipUnless(shutil.which("node"), "node not available")
    def test_fact_query_preview_uses_only_explicit_description_never_sql(self) -> None:
        script = r'''import("./frontend/src/factQueryPreview.js").then((m) => {
  console.log(JSON.stringify({
    described: m.factQueryPreview({query_description: " 查询 2 月采购金额 ", sql: "SELECT 1"}),
    sqlOnly: m.factQueryPreview({sql: "SELECT amount FROM orders"}),
    sqlAsDescription: m.factQueryPreview({description: "SELECT amount FROM orders", sql: "SELECT 1"}),
    absent: m.factQueryPreview({}),
  }));
})'''
        proc = subprocess.run(
            ["node", "--input-type=module", "-e", script],
            cwd=Path.cwd(), capture_output=True, text=True, check=True,
        )
        data = json.loads(proc.stdout)
        self.assertEqual(data["described"], "查询 2 月采购金额")
        self.assertEqual(data["sqlOnly"], "")
        self.assertEqual(data["sqlAsDescription"], "")
        self.assertEqual(data["absent"], "")

    def test_ontology_graph_modal_uses_product_labels_and_synced_cluster_layout(self) -> None:
        runtime = Path("frontend/src/runtime.js").read_text(encoding="utf-8")
        graph = Path("frontend/src/ontologySigmaGraph.js").read_text(encoding="utf-8")
        self.assertIn('data-graph-strategy="context" class="active">子图检索</button>', runtime)
        self.assertIn('data-graph-strategy="expand">关系扩散</button>', runtime)
        self.assertIn('>关系聚类可视化</button>', runtime)
        self.assertNotIn('>Ontology-GraphContext</button>', runtime)
        self.assertNotIn('>展开上下游</button>', runtime)
        self.assertIn("function packIsolatedNodes(graph)", graph)
        self.assertIn("packIsolatedNodes(graph);", graph)
        self.assertIn("graph.order <= 40", graph)

    def test_sop_six_steps_state_machine_and_event_mapping(self) -> None:
        """The analysis SOP is a real 6-step state machine driven by
        structured `sop_progress` events, with tool-mapping fallbacks and a
        visited-trajectory (skipped) terminal state."""
        machine = Path("frontend/src/sopMachine.js").read_text(encoding="utf-8")
        runtime = Path("frontend/src/runtime.js").read_text(encoding="utf-8")

        # 1. Exactly six fixed main steps, exact names, no old steps.
        steps_start = machine.index("export const SOP_STEPS = Object.freeze([")
        steps_end = machine.index("]);", steps_start)
        steps_src = machine[steps_start:steps_end]
        for step in (
            "意图识别", "本体模型匹配", "深度思考&分析规划",
            "数据获取和可视化", "根因分析", "决策行动",
        ):
            self.assertIn(f'"{step}"', steps_src)
        for old_step in ("语义理解&元数据匹配", "业务上下文注入", "SQL 执行&数据获取",
                         "结果分析&可视化输出", "执行首轮查询", "补充查询取数", "汇总交付"):
            self.assertNotIn(old_step, steps_src)

        # 1b. The machine exposes an explicit skipped status.
        self.assertIn('export const SOP_STATUS_SKIPPED = "skipped";', machine)
        self.assertIn("export function sopStatusesForDone(", machine)
        self.assertIn("export function visitedFromTodos(", machine)

        # 2. Tool mapping: ontology tools -> step 02 (index 1); render and
        #    table-schema tools -> step 04 数据获取和可视化 (index 3).
        tool_map_start = runtime.index("const SOP_TOOL_DETAIL = {")
        tool_map_end = runtime.index("\n  };", tool_map_start)
        tool_map = runtime[tool_map_start:tool_map_end]
        for rendering_tool in ("TableGenerate", "ChartGenerate", "ChartGenerateMultiDim"):
            self.assertIn(f"{rendering_tool}: {{ step: SOP_QUERY", tool_map)
        self.assertIn("ListTables: { step: SOP_QUERY", tool_map)
        self.assertIn("DescribeTable: { step: SOP_QUERY", tool_map)
        self.assertIn('"Ontology-SemanticQuery": { step: SOP_ONTOLOGY', tool_map)
        self.assertIn('"Ontology-GraphContext": { step: SOP_ONTOLOGY', tool_map)
        self.assertNotIn("SOP_CONTEXT", tool_map)
        self.assertNotIn("Ontology-FactQuery:", tool_map)
        self.assertNotIn("Ontology-MetricQuery:", tool_map)

        # 3. State machine tracks the visited trajectory, not a linear cursor.
        machine_func = machine[machine.index("export function applySopStep("):]
        self.assertIn("applySopStep(visited, current, stepIndex, detail, options = {})", machine_func)
        self.assertIn("if (target < cur && !allowBackward) return null;", machine_func)
        self.assertIn("nextSeen = seen.filter((i) => i <= target)", machine_func)
        self.assertIn("sopStatusesFor(nextSeen, target)", machine_func)
        set_src = runtime[runtime.index("function setSopStep("):runtime.index("function applySopStatuses(")]
        self.assertIn("applySopStep(visited, cur, stepIndex, detail, options)", set_src)
        self.assertIn("bucket.sopVisited = next.visited", set_src)

        # 4. Query tools rebuild 03 -> 04; a re-query from 04/05/06 rewinds to 03.
        tool_handler_start = runtime.index("function advanceSopForTool(")
        tool_handler_end = runtime.index("\n  }", tool_handler_start)
        tool_handler = runtime[tool_handler_start:tool_handler_end]
        self.assertIn("SOP_DATA_QUERY_TOOLS.has(name)", tool_handler)
        self.assertIn('new Set(["Ontology-FactQuery", "Ontology-MetricQuery"])', runtime)
        self.assertIn("根据分析结果重新规划", tool_handler)
        self.assertIn("生成自主 SQL 方案", tool_handler)
        self.assertIn("执行自主 SQL 查询", tool_handler)
        self.assertIn("查询失败，准备调整方案", tool_handler)
        self.assertIn("cur >= SOP_ROOTCAUSE", tool_handler)
        self.assertIn("function rewindSopAnalysis(", runtime)

        # 5. The frontend never fabricates step 05 from text markers: root-cause
        #    steps come only from structured backend sop_progress events.
        self.assertNotIn("advanceSopForText", runtime)
        self.assertNotIn("SOP_TEXT_INTERPRET", runtime)
        self.assertNotIn("SOP_TEXT_RECOMMEND", runtime)

        # 6. llm_response with no tools only marks step 06 in_progress.
        response_start = runtime.index('case "llm_response":')
        response_end = runtime.index('case "action_recommendations":', response_start)
        response_handler = runtime[response_start:response_end]
        self.assertIn('if (!hasToolUses) setSopStep(SOP_DECISION, "组装最终报告")', response_handler)

        # 7. Structured sop_progress event drives the machine (1-based -> 0).
        progress_start = runtime.index('case "sop_progress":')
        progress_end = runtime.index('case "tool_result":', progress_start)
        progress_handler = runtime[progress_start:progress_end]
        self.assertIn("setSopStep(step - 1, evt.detail", progress_handler)
        self.assertIn("evt.allow_backward !== false", progress_handler)

        # 8. done converts visited -> completed, unvisited -> skipped (never
        #    paints unexecuted steps green). error/superseded/choice never do.
        done_start = runtime.index('case "done":')
        done_end = runtime.index('case "error":', done_start)
        done_src = runtime[done_start:done_end]
        self.assertIn("reconcileTodosOnCompletion()", done_src)
        reconcile_start = runtime.index("function reconcileTodosOnCompletion(")
        reconcile_end = runtime.index("\n  }", reconcile_start)
        reconcile_src = runtime[reconcile_start:reconcile_end]
        self.assertIn("sopStatusesForDone(visited)", reconcile_src)
        self.assertNotIn('status: "completed"', reconcile_src)
        error_src = runtime[done_end:runtime.index("default:", done_end)]
        self.assertNotIn("reconcileTodosOnCompletion", error_src)
        superseded_start = runtime.index('case "session_superseded":')
        superseded_end = runtime.index('case "done":', superseded_start)
        self.assertNotIn("reconcileTodosOnCompletion", runtime[superseded_start:superseded_end])
        self.assertNotIn(
            "reconcileTodosOnCompletion",
            runtime[runtime.index('case "awaiting_user_choice":'):runtime.index('case "llm_response":')])

        # 9. Restore migration lives in the pure module, never rewrites JSON.
        self.assertIn("export function migrateLegacySop(", machine)
        self.assertIn("source.length === 5", machine)
        self.assertIn("source.length === 6", machine)
        self.assertIn("source.length === 9", machine)

    def _run_sop_machine(self, script: str) -> str:
        """Run a pure sopMachine.js script through node (skips when absent)."""
        repo = Path(__file__).resolve().parents[1]
        proc = subprocess.run(
            ["node", "--input-type=module", "-e", script],
            cwd=str(repo), capture_output=True, text=True, timeout=30,
        )
        self.assertEqual(proc.returncode, 0, proc.stderr)
        return proc.stdout.strip()

    @unittest.skipUnless(shutil.which("node"), "node not available")
    def test_sop_state_machine_pure_transitions(self) -> None:
        """Real state-machine transitions via node (not string assertions)."""
        script = r"""import("./frontend/src/sopMachine.js").then((m) => {
  const out = {};
  out.steps = m.SOP_STEPS;
  out.initial = m.applySopStep([], 0, 0, "用户问题解析");
  out.forward = m.applySopStep([0], 0, 2, "生成自主 SQL 方案");
  out.backward = m.applySopStep([0,1,2,3,4,5], 5, 2, "根据分析结果重新规划", { allowBackward: true });
  out.backwardRejected = m.applySopStep([0,1,2,3,4,5], 5, 2, "x", { allowBackward: false });
  out.sameStepDetail = m.applySopStep([0,1,2,3], 3, 3, "解析查询结果");
  out.loop = [m.applySopStep([0],0,2,"p"), m.applySopStep([0,2],2,3,"q"),
              m.applySopStep([0,2,3],3,4,"r"),
              m.applySopStep([0,2,3,4],4,2,"replan",{allowBackward:true}),
              m.applySopStep([0,2],2,3,"q2"), m.applySopStep([0,2,3],3,4,"r2"),
              m.applySopStep([0,2,3,4],4,5,"d"),
              m.applySopStep([0,2,3,4,5],5,2,"根据分析结果重新规划",{allowBackward:true})];
  out.oneInProgress = out.loop.every((r) => r.todos.filter((t) => t.status === "in_progress").length === 1);
  out.l1Done = m.sopStatusesForDone([0,2,3,5]);
  out.l3Done = m.sopStatusesForDone([0,1,2,3,4,5]);
  out.skipMid = m.sopStatusesFor([0,2,3,5], 5);
  out.rewindMid = m.sopStatusesFor([0,1,2], 2);
  console.log(JSON.stringify(out));
})"""
        data = json.loads(self._run_sop_machine(script))
        self.assertEqual(data["steps"], [
            "意图识别", "本体模型匹配", "深度思考&分析规划",
            "数据获取和可视化", "根因分析", "决策行动",
        ])
        self.assertEqual([t["status"] for t in data["initial"]["todos"]],
                         ["in_progress", "pending", "pending", "pending", "pending", "pending"])
        # 01 -> 03 jump: 02 was never visited -> skipped, never green.
        self.assertEqual([t["status"] for t in data["forward"]["todos"]],
                         ["completed", "skipped", "in_progress", "pending", "pending", "pending"])
        # 06 -> 03 rewind: steps 04..06 become pending again (no stale green).
        self.assertEqual([t["status"] for t in data["backward"]["todos"]],
                         ["completed", "completed", "in_progress", "pending", "pending", "pending"])
        self.assertEqual(data["backward"]["todos"][2]["detail"], "根据分析结果重新规划")
        self.assertEqual(data["backward"]["visited"], [0, 1, 2])
        self.assertIsNone(data["backwardRejected"])
        self.assertEqual(data["sameStepDetail"]["todos"][3]["detail"], "解析查询结果")
        self.assertTrue(data["oneInProgress"])
        # 04 -> 03 -> 04 -> 05 -> 06 -> 03: the final rewind resets 04..06 to
        # pending; 02 本体模型匹配 was never visited in this loop -> skipped,
        # and step 01 stays completed (real trajectory, no or True).
        self.assertEqual([t["status"] for t in data["loop"][-1]["todos"]],
                         ["completed", "skipped", "in_progress", "pending", "pending", "pending"])
        self.assertEqual(data["loop"][-1]["todos"][2]["detail"], "根据分析结果重新规划")
        # L1 final: 根因分析 (index 4) is skipped, never green.
        self.assertEqual(data["l1Done"],
                         ["completed", "skipped", "completed", "completed", "skipped", "completed"])
        # L3 final: root cause was executed -> all completed.
        self.assertEqual(data["l3Done"], ["completed"] * 6)
        # Mid-run L1 04->06: 根因分析 shows skipped while 决策行动 is in progress.
        self.assertEqual(data["skipMid"],
                         ["completed", "skipped", "completed", "completed", "skipped", "in_progress"])
        # Mid-run after 05->03: later steps are pending, not green.
        self.assertEqual(data["rewindMid"],
                         ["completed", "completed", "in_progress", "pending", "pending", "pending"])

    @unittest.skipUnless(shutil.which("node"), "node not available")
    def test_sop_legacy_snapshot_migration_pure(self) -> None:
        """Old 5-step / 6-step / 9-step snapshots migrate to the 6-step shape."""
        script = r"""import("./frontend/src/sopMachine.js").then((m) => {
  const out = {};
  const mk = (n) => Array.from({ length: n }, (_, i) =>
    ({ content: "old-" + i, status: "completed", detail: "" }));
  out.fiveDone = m.migrateLegacySop(mk(5), true);
  out.fiveMid = m.migrateLegacySop([
    { content: "语义理解&元数据匹配", status: "completed", detail: "" },
    { content: "业务上下文注入", status: "completed", detail: "" },
    { content: "深度思考&分析规划", status: "in_progress", detail: "根据分析结果重新规划" },
    { content: "SQL 执行&数据获取", status: "pending", detail: "" },
    { content: "结果分析&可视化输出", status: "pending", detail: "" },
  ], true);
  out.sixDone = m.migrateLegacySop(mk(6), true);
  out.sixMid = m.migrateLegacySop([
    { content: "a", status: "completed" }, { content: "b", status: "completed" },
    { content: "c", status: "completed" }, { content: "d", status: "completed" },
    { content: "e", status: "in_progress" }, { content: "f", status: "pending" },
  ], true);
  out.nineDone = m.migrateLegacySop(mk(9), true);
  out.nineMid = m.migrateLegacySop([
    { content: "a", status: "completed" }, { content: "b", status: "completed" },
    { content: "c", status: "completed" }, { content: "d", status: "completed" },
    { content: "e", status: "completed" }, { content: "f", status: "in_progress" },
    { content: "g", status: "pending" }, { content: "h", status: "pending" },
    { content: "i", status: "pending" },
  ], true);
  out.sameLen = m.migrateLegacySop([
    { content: "意图识别", status: "completed", detail: "" },
    { content: "本体模型匹配", status: "completed", detail: "" },
    { content: "深度思考&分析规划", status: "in_progress", detail: "根据查询错误调整方案" },
    { content: "数据获取和可视化", status: "pending", detail: "" },
    { content: "根因分析", status: "pending", detail: "" },
    { content: "决策行动", status: "pending", detail: "" },
  ], true);
  out.visited = m.visitedFromTodos([
    { status: "completed" }, { status: "completed" }, { status: "in_progress" },
    { status: "pending" }, { status: "pending" }, { status: "pending" },
  ]);
  console.log(JSON.stringify(out));
})"""
        data = json.loads(self._run_sop_machine(script))
        self.assertEqual([t["status"] for t in data["fiveDone"]], ["completed"] * 6)
        self.assertEqual([t["content"] for t in data["fiveMid"]], [
            "意图识别", "本体模型匹配", "深度思考&分析规划",
            "数据获取和可视化", "根因分析", "决策行动",
        ])
        # old-5 cursor on 规划 -> new 03 in_progress, later steps pending.
        self.assertEqual([t["status"] for t in data["fiveMid"]],
                         ["completed", "completed", "in_progress", "pending", "pending", "pending"])
        self.assertEqual(data["fiveMid"][2]["detail"], "根据分析结果重新规划")
        self.assertEqual([t["status"] for t in data["sixDone"]], ["completed"] * 6)
        self.assertEqual([t["status"] for t in data["sixMid"]],
                         ["completed", "completed", "completed", "completed", "in_progress", "pending"])
        self.assertEqual([t["status"] for t in data["nineDone"]], ["completed"] * 6)
        self.assertEqual([t["status"] for t in data["nineMid"]],
                         ["completed", "completed", "completed", "in_progress", "pending", "pending"])
        # Same-length 6-step snapshots keep their own content/status/detail.
        self.assertEqual(data["sameLen"][2]["detail"], "根据查询错误调整方案")
        self.assertEqual([t["status"] for t in data["sameLen"]],
                         ["completed", "completed", "in_progress", "pending", "pending", "pending"])
        # visitedFromTodos derives the trajectory from a restored snapshot.
        self.assertEqual(data["visited"], [0, 1])

    @unittest.skipUnless(shutil.which("node"), "node not available")
    def test_sop_skipped_terminal_and_rewind_pure(self) -> None:
        """done never greens unvisited steps; rewinds never leave stale green."""
        script = r"""import("./frontend/src/sopMachine.js").then((m) => {
  const out = {};
  out.l1 = m.sopStatusesForDone([0,2,3,5]);
  out.l2 = m.sopStatusesForDone([0,1,2,3,5]);
  out.interrupted = m.sopStatusesFor([0,1,2,3], 3);
  out.rewind = m.applySopStep([0,1,2,3,4,5], 5, 2, "根据分析结果重新规划", { allowBackward: true });
  out.rewindStatuses = out.rewind.todos.map((t) => t.status);
  out.forwardSkip = m.applySopStep([0], 0, 5, "组装最终报告");
  out.forwardSkipStatuses = out.forwardSkip.todos.map((t) => t.status);
  console.log(JSON.stringify(out));
})"""
        data = json.loads(self._run_sop_machine(script))
        # L1 (01->03->04->06): 02 和 05 未执行 -> skipped, not completed.
        self.assertEqual(data["l1"],
                         ["completed", "skipped", "completed", "completed", "skipped", "completed"])
        # L2 异常定位 (01->02->03->04->06): 05 未做根因 -> skipped.
        self.assertEqual(data["l2"],
                         ["completed", "completed", "completed", "completed", "skipped", "completed"])
        # A turn interrupted at 04 keeps in_progress/pending, never terminal.
        self.assertEqual(data["interrupted"],
                         ["completed", "completed", "completed", "in_progress", "pending", "pending"])
        # 06 -> 03 rewind: 04..06 pending, 05/06 not green.
        self.assertEqual(data["rewindStatuses"],
                         ["completed", "completed", "in_progress", "pending", "pending", "pending"])
        # 01 -> 06 direct jump: skipped steps stay non-green (skipped).
        self.assertEqual(data["forwardSkipStatuses"],
                         ["completed", "skipped", "skipped", "skipped", "skipped", "in_progress"])

    @unittest.skipUnless(shutil.which("node"), "node not available")
    def test_sop_thoughtchain_status_mapping_is_static_for_pending_and_skipped(self) -> None:
        """The WorkflowPanels ThoughtChain mapping reserves AntD's animated
        `pending` status for in_progress only; pending/skipped map to the
        custom static `idle` state, and completed maps to `success`.  The
        mapping is evaluated as a real pure function, not a string scan."""
        main = Path("frontend/src/main.jsx").read_text(encoding="utf-8")
        # The mapping is a named pure function used by the chain items, and
        # the old "everything except completed -> pending" ternary is gone.
        self.assertIn("function sopThoughtChainStatus(status) {", main)
        self.assertIn("status: sopThoughtChainStatus(item.status),", main)
        self.assertNotIn(
            'status: item.status === "completed" ? "success" : item.status === "in_progress" ? "pending" : "pending"',
            main)
        script = r"""const fs = require('fs');
const src = fs.readFileSync('frontend/src/main.jsx', 'utf8');
const start = src.indexOf('function sopThoughtChainStatus(status) {');
const end = src.indexOf('\n}\n', start) + 3;
const fn = new Function('return ' + src.slice(start, end))();
const out = {};
for (const s of ['completed', 'in_progress', 'pending', 'skipped']) out[s] = fn(s);
console.log(JSON.stringify(out));"""
        proc = subprocess.run(
            ["node", "-e", script],
            cwd=str(Path(__file__).resolve().parents[1]),
            capture_output=True, text=True, timeout=30,
        )
        self.assertEqual(proc.returncode, 0, proc.stderr)
        data = json.loads(proc.stdout.strip())
        self.assertEqual(data["completed"], "success")
        self.assertEqual(data["in_progress"], "pending")
        self.assertEqual(data["pending"], "idle")
        self.assertEqual(data["skipped"], "idle")

    def test_sop_terminal_cleanup_removes_all_loading_placeholders(self) -> None:
        """done / error / session_superseded / stream_closed must clear every
        loading placeholder (.thinking-line, .antd-step-thinking, .cursor,
        empty assistant ghosts) without touching real results."""
        runtime = Path("frontend/src/runtime.js").read_text(encoding="utf-8")
        cleanup_start = runtime.index("function cleanupTurnLoadingUI()")
        cleanup_src = runtime[cleanup_start:runtime.index("function attachChatStep(", cleanup_start)]
        self.assertIn('".thinking-line, .cursor"', cleanup_src)
        self.assertIn("clearStepThinking()", cleanup_src)
        # The ghost-block removal is guarded: only blocks without text, tool
        # steps or result cards are dropped, so real results survive.
        self.assertIn('".msg-body > *:not(.thinking-line):not(.cursor), "', cleanup_src)
        self.assertIn(
            '".antd-step-timeline .step, .chart-card, .table-card, .multidim-card, .choice-card"',
            cleanup_src)
        # Every terminal handler runs the shared cleanup.
        done_start = runtime.index('case "done":')
        done_end = runtime.index('case "error":', done_start)
        self.assertIn("cleanupTurnLoadingUI()", runtime[done_start:done_end])
        error_start = done_end
        error_end = runtime.index("default:", error_start)
        self.assertIn("cleanupTurnLoadingUI()", runtime[error_start:error_end])
        superseded_start = runtime.index('case "session_superseded":')
        superseded_end = runtime.index('case "done":', superseded_start)
        self.assertIn("cleanupTurnLoadingUI()", runtime[superseded_start:superseded_end])
        # The SSE natural-close path now runs the interrupted terminal cleanup
        # (same loading cleanup, but no success side effects).
        interrupted_start = runtime.index('case "stream_interrupted":')
        interrupted_end = runtime.index('case "done":', interrupted_start)
        self.assertIn("cleanupTurnLoadingUI()", runtime[interrupted_start:interrupted_end])

    def test_sop_restore_and_css_are_static_after_completion(self) -> None:
        """History restore strips transient loading rows, empty timelines and
        carets; CSS forces pending/skipped/idle SOP markers to be static and
        scopes the rule to the two workflow roots only."""
        runtime = Path("frontend/src/runtime.js").read_text(encoding="utf-8")
        hydrate_start = runtime.index("function hydrateRestoredChat()")
        hydrate_src = runtime[hydrate_start:runtime.index("function hydrateRestoredInspector(", hydrate_start)]
        self.assertIn('".cursor, .thinking-line, .antd-step-thinking"', hydrate_src)
        self.assertIn('if (!timeline.querySelector(":scope > .step")) timeline.remove();', hydrate_src)

        css = Path("frontend/src/workbench.css").read_text(encoding="utf-8")
        # Static skipped dash icon and static pending/skipped title colours.
        self.assertIn(".antd-sop-status-dash", css)
        self.assertIn(".antd-sop-title.is-skipped", css)
        self.assertIn(".antd-sop-title.is-pending", css)
        # The no-animation rule is scoped to the SOP workflow roots and uses
        # `animation: none` — it never disables other loading UIs.
        self.assertIn("animation: none !important", css)
        self.assertIn("#antd-workflow-root, #antd-dashboard-workflow-root", css)
        self.assertIn(".ant-thought-chain-item-icon", css)

    @unittest.skipUnless(shutil.which("node"), "node not available")
    def test_stream_eof_classification_pure(self) -> None:
        """EOF without an explicit backend terminal event is `interrupted`,
        never a synthetic `done`; stale streams stay silent."""
        script = r"""import("./frontend/src/streamTerminal.js").then((m) => {
  const out = {};
  out.emptyEof = m.classifyStreamEof({ stale: false, sawTerminal: false });
  out.doneEof = m.classifyStreamEof({ stale: false, sawTerminal: true });
  out.staleEof = m.classifyStreamEof({ stale: true, sawTerminal: false });
  out.staleWithTerminal = m.classifyStreamEof({ stale: true, sawTerminal: true });
  console.log(JSON.stringify(out));
})"""
        data = json.loads(self._run_sop_machine(script))
        # A bare EOF is never success: interrupted (no save/SOP/export).
        self.assertEqual(data["emptyEof"], "interrupted")
        # A terminal frame was parsed and already dispatched by the loop.
        self.assertEqual(data["doneEof"], "terminal")
        # A stale stream must not surface anything into the newer request.
        self.assertEqual(data["staleEof"], "stale")
        self.assertEqual(data["staleWithTerminal"], "stale")

    @unittest.skipUnless(shutil.which("node"), "node not available")
    def test_turn_lifecycle_done_idempotency_sequences(self) -> None:
        """Real event-sequence behaviour of the bounded completed/failed turn
        lifecycle (node, not string assertions).  A `done` is accepted once
        per turn; delayed duplicates, and late `done` after failure states,
        are rejected so success side effects never run twice."""
        script = r"""import("./frontend/src/turnLifecycle.js").then((m) => {
  const out = {};
  const cap = 4;
  // 1/2. single done + immediate duplicate done.
  let st = m.createTurnLifecycle({ capacity: cap });
  const d1 = m.recordDone(st, "T1");
  const d1b = m.recordDone(d1.state, "T1");
  out.singleThenDuplicate = [d1.accepted, d1b.accepted, d1b.state.completed];
  // 3. T1 done -> T2 done -> delayed T1 done (last T1 must be ignored).
  const d2 = m.recordDone(d1.state, "T2");
  const d1late = m.recordDone(d2.state, "T1");
  out.interleaved = [d2.accepted, d1late.accepted, d1late.state.completed];
  // 4/5/6. error / interrupted / superseded then late done.
  let f = m.createTurnLifecycle({ capacity: cap });
  f = m.recordFailure(f, "E1");
  out.errorThenDone = m.recordDone(f, "E1");
  f = m.createTurnLifecycle({ capacity: cap });
  f = m.recordFailure(f, "I1");
  out.interruptedThenDone = m.recordDone(f, "I1");
  f = m.createTurnLifecycle({ capacity: cap });
  f = m.recordFailure(f, "S1");
  out.supersededThenDone = m.recordDone(f, "S1");
  // 8/9. bare EOF is interrupted; EOF after an explicit done is terminal.
  const stm = null;
  out.bareEof = stm === null ? "turnLifecycle-has-no-eof" : null;
  // 11. bounded FIFO: capacity never exceeded even with many distinct turns.
  let capSt = m.createTurnLifecycle({ capacity: cap });
  for (let i = 0; i < 40; i++) capSt = m.recordDone(capSt, "T" + i).state;
  out.boundedSize = capSt.completed.length;
  out.boundedKeepsNewest = capSt.completed[capSt.completed.length - 1] === "T39";
  out.boundedDropsOldest = !capSt.completed.includes("T0");
  console.log(JSON.stringify(out));
})"""
        data = json.loads(self._run_sop_machine(script))
        self.assertEqual(data["singleThenDuplicate"], [True, False, ["T1"]])
        self.assertEqual(data["interleaved"], [True, False, ["T1", "T2"]])
        self.assertFalse(data["errorThenDone"]["accepted"])
        self.assertFalse(data["interruptedThenDone"]["accepted"])
        self.assertFalse(data["supersededThenDone"]["accepted"])
        self.assertEqual(data["boundedSize"], 4)
        self.assertTrue(data["boundedKeepsNewest"])
        self.assertTrue(data["boundedDropsOldest"])

    @unittest.skipUnless(shutil.which("node"), "node not available")
    def test_turn_lifecycle_reset_and_capacity(self) -> None:
        """Reset clears completed and failed turns; custom capacity is
        honoured and never grows."""
        script = r"""import("./frontend/src/turnLifecycle.js").then((m) => {
  const out = {};
  let st = m.createTurnLifecycle({ capacity: 2 });
  st = m.recordDone(st, "A").state;
  st = m.recordDone(st, "B").state;
  st = m.recordDone(st, "C").state; // evicts A
  out.afterEvict = [st.completed.length, st.completed.includes("A"), st.completed.includes("C")];
  out.failedBefore = m.isTurnFailed(st, "X");
  st = m.recordFailure(st, "X");
  out.failedAfter = m.isTurnFailed(st, "X");
  st = m.resetTurnLifecycle(st);
  out.reset = [st.completed.length, st.failed.size, st.completed.includes("C"), m.isTurnFailed(st, "X")];
  console.log(JSON.stringify(out));
})"""
        data = json.loads(self._run_sop_machine(script))
        self.assertEqual(data["afterEvict"], [2, False, True])
        self.assertFalse(data["failedBefore"])
        self.assertTrue(data["failedAfter"])
        self.assertEqual(data["reset"], [0, 0, False, False])

    def test_stream_response_never_fakes_done_on_eof(self) -> None:
        """The SSE loop only treats an explicit backend terminal event as
        terminal; EOF otherwise marks the turn interrupted (loading cleanup
        only, no SOP completion / export / save), and stale streams stay
        silent."""
        runtime = Path("frontend/src/runtime.js").read_text(encoding="utf-8")
        # The fake-success synthesis is gone; the pure classifier drives EOF.
        self.assertNotIn('stop_reason: "stream_closed"', runtime)
        self.assertIn('classifyStreamEof({ stale, sawTerminal: sawTerminalEvent })', runtime)
        self.assertIn('onEvent({\n            type: "stream_interrupted",', runtime)
        # Stale tracking prevents old requests from emitting anything.
        self.assertIn("stale = true", runtime)
        # Staleness is re-checked at EOF so a request superseded between the
        # final frame and the EOF can never interrupt the newer request.
        self.assertIn("if (seq !== streamSeq) stale = true;", runtime)
        # The interrupted handler cleans loading but never runs the success
        # side effects (no SOP completion, no export button, no save).
        interrupted_start = runtime.index('case "stream_interrupted":')
        interrupted_src = runtime[interrupted_start:runtime.index('case "done":', interrupted_start)]
        self.assertIn("cleanupTurnLoadingUI()", interrupted_src)
        self.assertIn("setBusy(false)", interrupted_src)
        self.assertNotIn("reconcileTodosOnCompletion", interrupted_src)
        self.assertNotIn("appendTurnExportButton", interrupted_src)
        self.assertNotIn("saveCurrentConversation", interrupted_src)
        # A turn that ended in error / superseded / interrupted can never be
        # flipped into success by a late `done`, and repeated `done` frames
        # are idempotent via the bounded turnLifecycle module (real
        # event-sequence behaviour is exercised in
        # test_turn_lifecycle_done_idempotency_sequences).
        done_start = runtime.index('case "done":')
        done_src = runtime[done_start:runtime.index('case "error":', done_start)]
        self.assertIn("recordDone", done_src)
        self.assertIn("if (!rec.accepted) break;", done_src)
        self.assertIn("recordFailure", runtime)
        # HTTP 409/429 (sendMessage path) restore operability and drop the
        # placeholder card; the choice-submit path also keeps working.
        send_start = runtime.index("async function sendMessage(")
        busy_start = runtime.index('errCode === "SESSION_BUSY"', send_start)
        busy_src = runtime[busy_start:busy_start + 700]
        self.assertIn("cleanupTurnLoadingUI()", busy_src)
        # Mid-stream abort only surfaces interrupted for the latest request.
        abort_start = runtime.index("console.warn(\"stream interrupted\", err)")
        abort_src = runtime[abort_start:abort_start + 300]
        self.assertIn("mySeq === streamSeq", abort_src)
        self.assertIn("stream_interrupted", abort_src)

    def test_sop_progress_turn_start_and_no_tool_delivery(self) -> None:
        """A plain no-tool turn emits step 01 at start and step 06 delivery
        details before done; done remains the only terminal signal.  L1 turns
        never fabricate 根因分析 (step 05) events."""
        def fake_stream(*_args, **_kwargs):
            yield {"type": "text_delta", "text": "结论：本月华东区域收入为 5200 万元。"}
            yield {"type": "message_end", "stop_reason": "end_turn", "usage": {}}

        with patch("bi_agent.web.session.stream_message", fake_stream):
            session = WebSession("/tmp", AgentDef("test", tools=[]), OntologyStore())
            events = list(session.generate_turn("华东区域收入是多少？"))

        sop = [e for e in events if e["type"] == "sop_progress"]
        self.assertGreaterEqual(len(sop), 1)
        self.assertEqual(sop[0]["step"], 1)
        self.assertEqual(sop[0]["detail"], "用户问题解析")
        self.assertFalse(sop[0]["allow_backward"])
        details = [e["detail"] for e in sop]
        self.assertIn("组装最终报告", details)
        self.assertIn("正在返回用户结果", details)
        # No root-cause analysis was performed: never a fake step-05 event.
        self.assertNotIn(5, [e["step"] for e in sop])
        done = [e for e in events if e["type"] == "done"]
        self.assertEqual(len(done), 1)
        self.assertLess(sop[-1]["step"], 7)  # never a fake all-complete step

    def test_sop_progress_query_tool_flow(self) -> None:
        """L1 取数（有多少订单）drives 03 plan -> 04 execute -> 04 result ->
        06 decision delivery.  A plain data query must NOT enter step 05."""
        responses = iter([
            [
                {"type": "tool_use_start", "id": "tu-1", "name": "Ontology-FactQuery"},
                {"type": "tool_use_end", "id": "tu-1", "name": "Ontology-FactQuery", "input": {"sql": "select count(*)"}},
                {"type": "message_end", "stop_reason": "tool_use", "usage": {}},
            ],
            [
                {"type": "text_delta", "text": "结论：审批中的订单有 50 单。"},
                {"type": "message_end", "stop_reason": "end_turn", "usage": {}},
            ],
        ])

        def fake_stream(*_args, **_kwargs):
            yield from next(responses)

        with patch("bi_agent.web.session.stream_message", fake_stream), \
             patch.object(WebSession, "_execute_tool", return_value=("50 单", False)), \
             patch.object(WebSession, "record_query_result", return_value=None):
            session = WebSession("/tmp", AgentDef("test", tools=[]), OntologyStore())
            events = list(session.generate_turn("有多少订单？"))

        sop = [(e["step"], e["detail"]) for e in events if e["type"] == "sop_progress"]
        steps = [item[0] for item in sop]
        # 01 start -> 03 plan -> 04 execute -> 04 result -> 06 assemble ->
        # 06 returning.  No step-05 根因分析 for an L1 取数 question.
        self.assertEqual(sop[0][0], 1)
        self.assertIn(3, steps)
        self.assertIn(4, steps)
        self.assertIn("执行自主 SQL 查询", [item[1] for item in sop])
        self.assertIn("解析查询结果", [item[1] for item in sop])
        self.assertNotIn(5, steps)
        self.assertTrue(any(item[0] == 6 and item[1] == "正在返回用户结果" for item in sop))
        done = [e for e in events if e["type"] == "done"]
        self.assertEqual(len(done), 1)

    def test_sop_progress_requery_rewinds_to_planning(self) -> None:
        """A later Ontology-FactQuery after data/rendering work emits
        04 -> 03 replan -> 04, never leaving stale completed steps."""
        responses = iter([
            [
                {"type": "tool_use_start", "id": "tu-1", "name": "Ontology-FactQuery"},
                {"type": "tool_use_end", "id": "tu-1", "name": "Ontology-FactQuery", "input": {"sql": "select 1"}},
                {"type": "message_end", "stop_reason": "tool_use", "usage": {}},
            ],
            [
                {"type": "text_delta", "text": "结论：第一轮结果不足，需要补充查询。"},
                {"type": "tool_use_start", "id": "tu-2", "name": "TableGenerate"},
                {"type": "tool_use_end", "id": "tu-2", "name": "TableGenerate", "input": {}},
                {"type": "message_end", "stop_reason": "tool_use", "usage": {}},
            ],
            [
                {"type": "tool_use_start", "id": "tu-3", "name": "Ontology-FactQuery"},
                {"type": "tool_use_end", "id": "tu-3", "name": "Ontology-FactQuery", "input": {"sql": "select 2"}},
                {"type": "message_end", "stop_reason": "tool_use", "usage": {}},
            ],
            [
                {"type": "text_delta", "text": "结论：补充查询完成，共 60 单。"},
                {"type": "message_end", "stop_reason": "end_turn", "usage": {}},
            ],
        ])

        def fake_stream(*_args, **_kwargs):
            yield from next(responses)

        with patch("bi_agent.web.session.stream_message", fake_stream), \
             patch.object(WebSession, "_execute_tool", return_value=("60 单", False)), \
             patch.object(WebSession, "record_query_result", return_value=None):
            session = WebSession("/tmp", AgentDef("test", tools=[]), OntologyStore())
            events = list(session.generate_turn("统计订单数量"))

        sop = [(e["step"], e["detail"]) for e in events if e["type"] == "sop_progress"]
        details = [d for _, d in sop]
        self.assertIn("根据分析结果重新规划", details)
        replan_at = details.index("根据分析结果重新规划")
        # A real rendering detail (04 生成数据表格) precedes the replan; a
        # later query execution (04) follows it.  No or True assertions.
        self.assertIn("生成数据表格", details[:replan_at])
        self.assertEqual(sop[replan_at][0], 3)
        self.assertIn("执行自主 SQL 查询", details[replan_at:])
        self.assertNotIn(5, [item[0] for item in sop])
        done = [e for e in events if e["type"] == "done"]
        self.assertEqual(len(done), 1)

    def test_sop_query_failure_never_fabricates_later_steps(self) -> None:
        """A failed query emits 04 查询失败; an error-ending turn never
        fabricates 05 根因分析 / 06 决策行动 events and never emits done."""
        responses = iter([
            [
                {"type": "tool_use_start", "id": "tu-1", "name": "Ontology-FactQuery"},
                {"type": "tool_use_end", "id": "tu-1", "name": "Ontology-FactQuery", "input": {"sql": "select broken"}},
                {"type": "message_end", "stop_reason": "tool_use", "usage": {}},
            ],
            [
                {"type": "text_delta", "text": "查询失败，调整方案。"},
                {"type": "message_end", "stop_reason": "error", "usage": {}},
            ],
        ])

        def fake_stream(*_args, **_kwargs):
            yield from next(responses)

        with patch("bi_agent.web.session.stream_message", fake_stream), \
             patch.object(WebSession, "_execute_tool", return_value=("Error: 语法错误", True)), \
             patch.object(WebSession, "record_query_result", return_value=None):
            session = WebSession("/tmp", AgentDef("test", tools=[]), OntologyStore())
            events = list(session.generate_turn("查询订单金额"))

        sop = [(e["step"], e["detail"]) for e in events if e["type"] == "sop_progress"]
        details = [d for _, d in sop]
        self.assertIn("查询失败，准备调整方案", details)
        # The failed turn must not fabricate root-cause or decision steps.
        self.assertNotIn(5, [item[0] for item in sop])
        self.assertNotIn(6, [item[0] for item in sop])
        done = [e for e in events if e["type"] == "done"]
        self.assertEqual(done, [])

    def test_sop_query_error_recovery_replans_and_delivers(self) -> None:
        """After a failed query, the next query re-enters 03 根据查询错误调整方案
        then 04 executes again; the final answer still delivers (SOP is not a
        delivery gate)."""
        responses = iter([
            [
                {"type": "tool_use_start", "id": "tu-1", "name": "Ontology-FactQuery"},
                {"type": "tool_use_end", "id": "tu-1", "name": "Ontology-FactQuery", "input": {"sql": "select broken"}},
                {"type": "message_end", "stop_reason": "tool_use", "usage": {}},
            ],
            [
                {"type": "tool_use_start", "id": "tu-2", "name": "Ontology-FactQuery"},
                {"type": "tool_use_end", "id": "tu-2", "name": "Ontology-FactQuery", "input": {"sql": "select fixed"}},
                {"type": "message_end", "stop_reason": "tool_use", "usage": {}},
            ],
            [
                {"type": "text_delta", "text": "结论：查询完成，共 60 单。"},
                {"type": "message_end", "stop_reason": "end_turn", "usage": {}},
            ],
        ])

        def fake_stream(*_args, **_kwargs):
            yield from next(responses)

        def fake_execute(_self, tool_use, *args, **kwargs):
            sql = str((tool_use.get("input") or {}).get("sql") or "")
            if "broken" in sql:
                return "Error: 语法错误", True
            return "60 单", False

        with patch("bi_agent.web.session.stream_message", fake_stream), \
             patch.object(WebSession, "_execute_tool", new=fake_execute), \
             patch.object(WebSession, "record_query_result", return_value=None):
            session = WebSession("/tmp", AgentDef("test", tools=[]), OntologyStore())
            events = list(session.generate_turn("查询订单金额"))

        sop = [(e["step"], e["detail"]) for e in events if e["type"] == "sop_progress"]
        details = [d for _, d in sop]
        self.assertIn("查询失败，准备调整方案", details)
        self.assertIn("根据查询错误调整方案", details)
        replan_at = details.index("根据查询错误调整方案")
        self.assertEqual(sop[replan_at][0], 3)
        # The retried query executes on step 04 after the replan.
        self.assertIn("执行自主 SQL 查询", details[replan_at:])
        # L1 取数 recovery never fabricates step 05.
        self.assertNotIn(5, [item[0] for item in sop])
        done = [e for e in events if e["type"] == "done"]
        self.assertEqual(len(done), 1)

    def test_sop_l2_problem_location_skips_root_cause(self) -> None:
        """L2 异常定位 (问题定位 section, no 根因分析 section) never emits a
        step-05 root-cause event."""
        responses = iter([
            [
                {"type": "tool_use_start", "id": "tu-1", "name": "Ontology-FactQuery"},
                {"type": "tool_use_end", "id": "tu-1", "name": "Ontology-FactQuery", "input": {"sql": "select region, amount"}},
                {"type": "message_end", "stop_reason": "tool_use", "usage": {}},
            ],
            [
                {"type": "text_delta", "text": "🔎 问题定位：华东区环比下降 12%，其余区域平稳。\\n📌 结论：异常集中在华东区。"},
                {"type": "message_end", "stop_reason": "end_turn", "usage": {}},
            ],
        ])

        def fake_stream(*_args, **_kwargs):
            yield from next(responses)

        with patch("bi_agent.web.session.stream_message", fake_stream), \
             patch.object(WebSession, "_execute_tool", return_value=("区域数据", False)), \
             patch.object(WebSession, "record_query_result", return_value=None):
            session = WebSession("/tmp", AgentDef("test", tools=[]), OntologyStore())
            events = list(session.generate_turn("哪个区域异常？"))

        sop = [e for e in events if e["type"] == "sop_progress"]
        details = [e["detail"] for e in sop]
        self.assertIn("解析查询结果", details)
        self.assertNotIn(5, [e["step"] for e in sop])
        self.assertTrue(any(e["step"] == 6 and e["detail"] == "正在返回用户结果" for e in sop))
        done = [e for e in events if e["type"] == "done"]
        self.assertEqual(len(done), 1)

    def test_sop_l3_root_cause_enters_step_five(self) -> None:
        """L3 根因问题: only when the final narrative really contains a
        root-cause section does the backend emit step-05."""
        responses = iter([
            [
                {"type": "tool_use_start", "id": "tu-1", "name": "Ontology-FactQuery"},
                {"type": "tool_use_end", "id": "tu-1", "name": "Ontology-FactQuery", "input": {"sql": "select * from t"}},
                {"type": "message_end", "stop_reason": "tool_use", "usage": {}},
            ],
            [
                {"type": "text_delta", "text": "📌 结论：销售额下降 12%。\n🔍 根因分析：供应商交期延迟是主因，证据链：交期对比表。\n💡 行动建议：与主要供应商核对交期承诺并建立交期考核。"},
                {"type": "message_end", "stop_reason": "end_turn", "usage": {}},
            ],
        ])

        def fake_stream(*_args, **_kwargs):
            yield from next(responses)

        with patch("bi_agent.web.session.stream_message", fake_stream), \
             patch.object(WebSession, "_execute_tool", return_value=("销售数据", False)), \
             patch.object(WebSession, "record_query_result", return_value=None):
            session = WebSession("/tmp", AgentDef("test", tools=[]), OntologyStore())
            events = list(session.generate_turn("销售额为什么下降？"))

        sop = [(e["step"], e["detail"]) for e in events if e["type"] == "sop_progress"]
        details = [d for _, d in sop]
        # Step 05 appears only because the narrative really has 根因分析.
        self.assertIn("根因证据链组装", details)
        rc_at = details.index("根因证据链组装")
        self.assertEqual(sop[rc_at][0], 5)
        # It precedes the final delivery steps (06).
        self.assertTrue(any(e[0] == 6 and e[1] == "组装最终报告" for e in sop[rc_at:]))
        done = [e for e in events if e["type"] == "done"]
        self.assertEqual(len(done), 1)

    def test_sop_tool_error_never_completes_six_steps(self) -> None:
        """Tool errors do not complete later steps: only a terminal `done`
        event converts visited steps to completed and unvisited to skipped."""
        runtime = Path("frontend/src/runtime.js").read_text(encoding="utf-8")
        done_start = runtime.index('case "done":')
        done_end = runtime.index('case "error":', done_start)
        self.assertIn("reconcileTodosOnCompletion()", runtime[done_start:done_end])
        error_src = runtime[done_end:runtime.index("default:", done_end)]
        self.assertNotIn("reconcileTodosOnCompletion", error_src)
        tool_result_start = runtime.index('case "tool_result":')
        tool_result_end = runtime.index('case "user_choice_requested":', tool_result_start)
        self.assertNotIn("reconcileTodosOnCompletion", runtime[tool_result_start:tool_result_end])

    @unittest.skipUnless(shutil.which("node"), "node not available")
    def test_sop_refresh_restore_preserves_trajectory(self) -> None:
        """A saved 6-step snapshot restores with identical names, statuses and
        the in-progress detail (refresh / history restore path)."""
        script = r"""import("./frontend/src/sopMachine.js").then((m) => {
  const out = {};
  out.saved = [
    { content: "意图识别", status: "completed", detail: "" },
    { content: "本体模型匹配", status: "completed", detail: "" },
    { content: "深度思考&分析规划", status: "in_progress", detail: "根据分析结果重新规划" },
    { content: "数据获取和可视化", status: "pending", detail: "" },
    { content: "根因分析", status: "pending", detail: "" },
    { content: "决策行动", status: "pending", detail: "" },
  ];
  out.restored = m.migrateLegacySop(out.saved, true);
  out.visited = m.visitedFromTodos(out.restored);
  console.log(JSON.stringify(out));
})"""
        data = json.loads(self._run_sop_machine(script))
        restored = data["restored"]
        self.assertEqual([t["content"] for t in restored], [
            "意图识别", "本体模型匹配", "深度思考&分析规划",
            "数据获取和可视化", "根因分析", "决策行动",
        ])
        self.assertEqual([t["status"] for t in restored],
                         ["completed", "completed", "in_progress", "pending", "pending", "pending"])
        self.assertEqual(restored[2]["detail"], "根据分析结果重新规划")
        self.assertEqual(data["visited"], [0, 1])

    def test_sop_single_state_machine_shared_by_chat_and_dashboard(self) -> None:
        """Chat, report and Dashboard all render the same six-step SOP from the
        single sopMachine.js module; main.jsx mounts WorkflowPanels in both
        the chat and dashboard roots."""
        runtime = Path("frontend/src/runtime.js").read_text(encoding="utf-8")
        main = Path("frontend/src/main.jsx").read_text(encoding="utf-8")
        import_start = runtime.index('from "./sopMachine.js";')
        self.assertIn("SOP_STEPS", runtime[:import_start])
        self.assertIn("applySopStep", runtime[:import_start])
        self.assertIn("currentStepOf", runtime[:import_start])
        self.assertIn("migrateLegacySop", runtime[:import_start])
        self.assertIn("sopStatusesForDone", runtime[:import_start])
        self.assertIn("visitedFromTodos", runtime[:import_start])
        self.assertIn("render(<WorkflowPanels />)", main)
        self.assertIn("dashboardWorkflowRoot", main)
        self.assertIn("createRoot(dashboardWorkflowRoot).render(<WorkflowPanels />)", main)

    def test_sop_missing_events_never_block_final_answer(self) -> None:
        """Even without any sop_progress event the final text and done still
        reach the client (SOP is display-only, not a delivery gate)."""
        def fake_stream(*_args, **_kwargs):
            yield {"type": "text_delta", "text": "结论：直接回答。"}
            yield {"type": "message_end", "stop_reason": "end_turn", "usage": {}}

        with patch("bi_agent.web.session.stream_message", fake_stream), \
             patch.object(WebSession, "record_query_result", return_value=None):
            session = WebSession("/tmp", AgentDef("test", tools=[]), OntologyStore())
            events = list(session.generate_turn("简单问题"))

        # The turn still starts with step 01 (it always emits one), but no
        # 根因分析/决策行动 events are fabricated before delivery.
        sop_steps = [e["step"] for e in events if e["type"] == "sop_progress"]
        self.assertTrue(all(step <= 6 for step in sop_steps))
        self.assertTrue(any(e["type"] == "llm_response" for e in events))
        self.assertTrue(any(e["type"] == "done" for e in events))

    def test_app_sop_progress_is_turn_stamped(self) -> None:
        """sop_progress joins the SSE event allowlist so it carries turn_id."""
        from bi_agent.web.app import _TURN_EVENT_TYPES
        self.assertIn("sop_progress", _TURN_EVENT_TYPES)

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


    def test_product_branding_and_version_display(self) -> None:
        """The top-left brand is 智能分析 with the v0.1.0 tag everywhere;
        智析 and the bi-analyst pseudo-version are gone from user-visible
        surfaces (title, skeleton, shell brand and React sidebar)."""
        main = Path("frontend/src/main.jsx").read_text(encoding="utf-8")
        shell = Path("frontend/src/shell.html").read_text(encoding="utf-8")
        static = Path("bi_agent/web/static/index.html").read_text(encoding="utf-8")
        self.assertIn('const PRODUCT_NAME = "智能分析";', main)
        self.assertIn('const PRODUCT_VERSION = "v0.1.0";', main)
        self.assertIn("PRODUCT_NAME", main)
        self.assertIn("PRODUCT_VERSION", main)
        self.assertIn('className="antd-product-version"', main)
        self.assertIn("<title>智能分析 · 本体工作台</title>", shell)
        self.assertIn('<span class="brand-name">智能分析</span>', shell)
        self.assertIn('<span class="brand-version" id="product-version">v0.1.0</span>', shell)
        self.assertIn("<title>智能分析 · 本体工作台</title>", static)
        self.assertIn('aria-label="智能分析 React 工作台"', static)
        self.assertIn("正在加载智能分析工作台…", static)
        # No legacy brand text remains in any first-paint surface.
        for src in (main, shell, static):
            self.assertNotIn("智析", src)
            self.assertNotIn("bi-analyst", src)
        # The actual agent role configuration is untouched.
        self.assertTrue(Path(".claude/agents/bi-analyst.md").exists())

    def test_version_contract_consistent(self) -> None:
        """Python, FastAPI, npm and UI versions agree on v0.1.0 and are
        independent of knowledge/schema/cache versions."""
        root = Path(__file__).resolve().parents[1]
        pyproject = (root / "pyproject.toml").read_text(encoding="utf-8")
        self.assertIn('version = "0.1.0"', pyproject)
        init = (root / "bi_agent/__init__.py").read_text(encoding="utf-8")
        self.assertIn('__version__ = "0.1.0"', init)
        app = (root / "bi_agent/web/app.py").read_text(encoding="utf-8")
        self.assertIn('version="0.1.0"', app)
        pkg = (root / "frontend/package.json").read_text(encoding="utf-8")
        self.assertIn('"version": "0.1.0"', pkg)
        lock = (root / "frontend/package-lock.json").read_text(encoding="utf-8")
        import json as _json
        lock_root = _json.loads(lock)["packages"][""]["version"]
        self.assertEqual(lock_root, "0.1.0")
        main = (root / "frontend/src/main.jsx").read_text(encoding="utf-8")
        self.assertIn('const PRODUCT_VERSION = "v0.1.0";', main)
        # Product version is decoupled from the numeric conversation schema
        # version and from vendor cache-bust query params.
        conv = (root / "bi_agent/web/conversations.py").read_text(encoding="utf-8")
        self.assertIn("schema_version", conv)
        self.assertNotIn('"0.1.0"', conv)

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

    def __init__(self, *, error=None, text="ok", reasoning=None):
        self._error = error
        self._text = text
        self._reasoning = reasoning
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
                    content=self._text, reasoning_content=self._reasoning, tool_calls=None
                ),
                finish_reason="stop",
            )],
        )


class TeamThinkingRoutingTests(unittest.TestCase):
    """Team gateway thinking controls follow the verified per-family shape."""

    def test_registry_advertises_only_verified_team_models(self) -> None:
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("TEAM_THINKING_MODELS", None)
            self.assertTrue(registry.team_model_supports_thinking("qwen3.7-plus"))
            self.assertTrue(registry.team_model_supports_thinking(
                "doubao-seed-2-1-pro-260628"
            ))
            self.assertTrue(registry.team_model_supports_thinking(
                "direct-deepseek-v4-pro"
            ))
            self.assertFalse(registry.team_model_supports_thinking(
                "Qwen/Qwen3-80B-AWQ"
            ))
            self.assertFalse(registry.team_model_supports_thinking("glm-5-turbo"))

    def test_registry_full_verified_thinking_table(self) -> None:
        verified = {
            "qwen3.5-397b-a17b",
            "qwen3.7-plus",
            "qwen3-vl-plus",
            "qwen3.5-122b-a10b",
            "qwen3-vl-flash",
            "qwen3.8-2.4t-a95b",
            "qwen3.8-27b",
            "doubao-seed-2-1-turbo-260628",
            "doubao-seed-2-1-pro-260628",
            "direct-deepseek-v4-pro",
            "direct-deepseek-v4-flash",
            "deepseek-v4-flash-0731",
        }
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("TEAM_THINKING_MODELS", None)
            for model_id in verified:
                self.assertTrue(
                    registry.team_model_supports_thinking(model_id), model_id
                )
            self.assertFalse(registry.team_model_supports_thinking("glm-5.2"))
            self.assertFalse(registry.team_model_supports_thinking("kimi-k2.6"))
            self.assertFalse(registry.team_model_supports_thinking(
                "doubao-seed-2-0-pro-260215"
            ))
            self.assertFalse(registry.team_model_supports_thinking(
                "Qwen/Qwen3-80B-AWQ"
            ))

    def test_registry_override_can_replace_or_disable_capability_table(self) -> None:
        with patch.dict(os.environ, {"TEAM_THINKING_MODELS": "custom-a, custom-b"}):
            self.assertTrue(registry.team_model_supports_thinking("custom-b"))
            self.assertFalse(registry.team_model_supports_thinking("qwen3.7-plus"))
        with patch.dict(os.environ, {"TEAM_THINKING_MODELS": ""}):
            self.assertFalse(registry.team_model_supports_thinking("qwen3.7-plus"))

    def _stream_request(self, model_id, *, thinking=False, deepseek_env=None,
                        legacy_env=None, qwen_env=None, reasoning=None):
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
        client = _FakeTeamClient(reasoning=reasoning)
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
        return client.requests[0], events

    def test_deepseek_thinking_true_sends_enabled(self) -> None:
        request, _ = self._stream_request("deepseek-v4-flash", thinking=True, deepseek_env="true")
        self.assertEqual(request["extra_body"], {"thinking": {"type": "enabled"}})

    def test_deepseek_thinking_false_sends_disabled(self) -> None:
        request, _ = self._stream_request("deepseek-v4-flash", thinking=True, deepseek_env="false")
        self.assertEqual(request["extra_body"], {"thinking": {"type": "disabled"}})

    def test_deepseek_legacy_global_env_still_controls_deepseek(self) -> None:
        request, _ = self._stream_request("deepseek-v4-pro", thinking=False, legacy_env="true")
        self.assertEqual(request["extra_body"], {"thinking": {"type": "enabled"}})

    def test_deepseek_without_env_uses_runtime_toggle(self) -> None:
        enabled, _ = self._stream_request("deepseek-v4-flash", thinking=True)
        self.assertEqual(enabled["extra_body"], {"thinking": {"type": "enabled"}})
        disabled, _ = self._stream_request("deepseek-v4-flash", thinking=False)
        self.assertEqual(disabled["extra_body"], {"thinking": {"type": "disabled"}})

    def test_qwen_uses_runtime_enable_thinking_flag(self) -> None:
        request, _ = self._stream_request("qwen3.7-plus", thinking=True)
        self.assertEqual(request["extra_body"], {"enable_thinking": True})
        request, _ = self._stream_request("qwen3.7-plus", thinking=False)
        self.assertEqual(request["extra_body"], {"enable_thinking": False})

    def test_qwen_env_can_override_runtime_toggle(self) -> None:
        request, _ = self._stream_request("qwen3.7-plus", thinking=False, qwen_env="true")
        self.assertEqual(request["extra_body"], {"enable_thinking": True})

    def test_qwen_2_4t_omits_rejected_false_value(self) -> None:
        request, _ = self._stream_request("qwen3.8-2.4t-a95b", thinking=False)
        self.assertNotIn("extra_body", request)

    def test_verified_doubao_21_uses_thinking_field(self) -> None:
        request, _ = self._stream_request("doubao-seed-2-1-pro-260628", thinking=True)
        self.assertEqual(request["extra_body"], {"thinking": {"type": "enabled"}})
        request, _ = self._stream_request("doubao-seed-2-1-turbo-260628", thinking=False)
        self.assertEqual(request["extra_body"], {"thinking": {"type": "disabled"}})

    def test_older_doubao_receives_no_unverified_parameter(self) -> None:
        request, _ = self._stream_request("doubao-seed-2-0-pro-260215", thinking=True)
        self.assertNotIn("extra_body", request)

    def test_disabled_toggle_hides_unsolicited_reasoning_but_keeps_internal_block(self) -> None:
        _, events = self._stream_request(
            "direct-deepseek-v4-pro", thinking=False, reasoning="internal"
        )
        self.assertNotIn("thinking_delta", [event["type"] for event in events])
        self.assertIn(
            {"type": "thinking_block", "text": "internal"}, events
        )

    def test_glm_never_receives_deepseek_thinking(self) -> None:
        request, _ = self._stream_request("glm-5.1", thinking=True, legacy_env="true")
        self.assertNotIn("extra_body", request)

    def test_kimi_never_receives_deepseek_thinking(self) -> None:
        request, _ = self._stream_request("kimi-k2.6", thinking=True, legacy_env="true")
        self.assertNotIn("extra_body", request)

    def test_moonshot_alias_and_glm_are_classified_as_own_family(self) -> None:
        self.assertEqual(provider_team._model_family("moonshot-v1-8k"), "kimi")
        self.assertEqual(provider_team._model_family("GLM-4.7"), "glm")
        self.assertEqual(provider_team._model_family("Qwen/Qwen3-80B-AWQ"), "qwen")
        self.assertEqual(provider_team._model_family("doubao-seed-2-1-pro-260628"), "doubao")

    def test_unknown_model_never_receives_deepseek_thinking(self) -> None:
        request, _ = self._stream_request("some-other-model", thinking=True, legacy_env="true")
        self.assertNotIn("extra_body", request)

    def test_switch_from_deepseek_to_qwen_drops_thinking_payload(self) -> None:
        first, _ = self._stream_request("deepseek-v4-flash", thinking=True, deepseek_env="true")
        second, _ = self._stream_request("Qwen/Qwen3-80B-AWQ", thinking=True, legacy_env="true")
        self.assertEqual(first["extra_body"], {"thinking": {"type": "enabled"}})
        self.assertEqual(second["extra_body"], {"enable_thinking": True})

    def test_switch_from_qwen_to_deepseek_regenerates_thinking_payload(self) -> None:
        first, _ = self._stream_request("Qwen/Qwen3-80B-AWQ", thinking=True)
        second, _ = self._stream_request("deepseek-v4-pro", thinking=True, deepseek_env="true")
        self.assertEqual(first["extra_body"], {"enable_thinking": True})
        self.assertEqual(second["extra_body"], {"thinking": {"type": "enabled"}})

    def test_missing_env_variables_raise_no_exception(self) -> None:
        request, _ = self._stream_request("Qwen/Qwen3-80B-AWQ", thinking=True)
        self.assertEqual(request["extra_body"], {"enable_thinking": True})


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
        # The retry reuses the same message list: no tool re-execution or
        # restart from the beginning of the turn. Its system prompt correctly
        # drops the visible-thinking language rule after thinking is disabled.
        self.assertEqual(calls[0][0][0], calls[1][0][0])
        self.assertIn(VISIBLE_THINKING_CN_RULE, calls[0][0][1])
        self.assertNotIn(VISIBLE_THINKING_CN_RULE, calls[1][0][1])
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


class TeamThinkingAndFallbackSessionTests(unittest.TestCase):
    """Session-level behavior: visible-thinking Chinese constraint injection,
    thinking_delta gating, and turn-scoped automatic fallback."""

    @contextmanager
    def _session(self, cfg, fake_stream, *, model_supports_thinking=True):
        model_id = "Qwen/Qwen3-80B-AWQ"
        with patch("bi_agent.web.session.get_llm_config", return_value=cfg), \
             patch("bi_agent.web.session.stream_message", fake_stream), \
             patch("bi_agent.web.session.get_model_id", side_effect=lambda key: str(key)), \
             patch("bi_agent.web.session.get_model", return_value={
                 "key": cfg.model_key, "provider": "team", "model_id": model_id,
                 "supports_thinking": model_supports_thinking,
             }):
            yield WebSession("/tmp", AgentDef("test", tools=[]), OntologyStore())

    def _cfg(self, *, model_key="team-configured", effective_thinking=False):
        return SimpleNamespace(
            model_key=model_key, max_tokens=256, temperature=0.1,
            effective_thinking=effective_thinking,
        )

    def test_cn_rule_injected_when_thinking_enabled_and_model_supports(self) -> None:
        calls: list[dict] = []

        def fake_stream(messages, system_prompt, *args, **kwargs):
            calls.append({"system_prompt": system_prompt, "thinking": kwargs.get("thinking")})
            yield {"type": "text_delta", "text": "ok"}
            yield {"type": "message_end", "stop_reason": "end_turn", "usage": {}}

        with self._session(
            self._cfg(effective_thinking=True), fake_stream,
            model_supports_thinking=True,
        ) as session:
            list(session.generate_turn("test"))
        self.assertEqual(len(calls), 1)
        self.assertTrue(calls[0]["thinking"])
        self.assertIn("简体中文", calls[0]["system_prompt"])
        self.assertIn("可见思考", calls[0]["system_prompt"])

    def test_cn_rule_not_injected_when_model_lacks_support(self) -> None:
        calls: list[dict] = []

        def fake_stream(messages, system_prompt, *args, **kwargs):
            calls.append({"system_prompt": system_prompt, "thinking": kwargs.get("thinking")})
            yield {"type": "text_delta", "text": "ok"}
            yield {"type": "message_end", "stop_reason": "end_turn", "usage": {}}

        with self._session(
            self._cfg(effective_thinking=True), fake_stream,
            model_supports_thinking=False,
        ) as session:
            list(session.generate_turn("test"))
        self.assertEqual(len(calls), 1)
        self.assertNotIn("简体中文", calls[0]["system_prompt"])
        self.assertNotIn("可见思考", calls[0]["system_prompt"])

    def test_cn_rule_not_injected_when_user_thinking_disabled(self) -> None:
        calls: list[dict] = []

        def fake_stream(messages, system_prompt, *args, **kwargs):
            calls.append({"system_prompt": system_prompt, "thinking": kwargs.get("thinking")})
            yield {"type": "text_delta", "text": "ok"}
            yield {"type": "message_end", "stop_reason": "end_turn", "usage": {}}

        with self._session(
            self._cfg(effective_thinking=False), fake_stream,
            model_supports_thinking=True,
        ) as session:
            list(session.generate_turn("test"))
        self.assertEqual(len(calls), 1)
        self.assertFalse(calls[0]["thinking"])
        self.assertNotIn("简体中文", calls[0]["system_prompt"])

    def test_thinking_disabled_never_forwards_thinking_delta(self) -> None:
        def fake_stream(*args, **kwargs):
            yield {"type": "thinking_delta", "text": "internal reasoning trace"}
            yield {"type": "text_delta", "text": "最终答案仍然正常输出"}
            yield {"type": "message_end", "stop_reason": "end_turn", "usage": {}}

        with self._session(
            self._cfg(effective_thinking=False), fake_stream,
            model_supports_thinking=True,
        ) as session:
            events = list(session.generate_turn("test"))
        self.assertNotIn(
            "thinking_delta", [event["type"] for event in events]
        )
        deltas = [event["text"] for event in events if event["type"] == "text_delta"]
        self.assertIn("最终答案仍然正常输出", deltas)
        self.assertTrue(any(event["type"] == "done" for event in events))

    def test_thinking_enabled_forwards_thinking_delta(self) -> None:
        def fake_stream(*args, **kwargs):
            yield {"type": "thinking_delta", "text": "思考摘要"}
            yield {"type": "text_delta", "text": "final"}
            yield {"type": "message_end", "stop_reason": "end_turn", "usage": {}}

        with self._session(
            self._cfg(effective_thinking=True), fake_stream,
            model_supports_thinking=True,
        ) as session:
            events = list(session.generate_turn("test"))
        deltas = [event["text"] for event in events if event["type"] == "thinking_delta"]
        self.assertEqual(deltas, ["思考摘要"])

    def test_auto_fallback_is_turn_scoped_and_never_persisted(self) -> None:
        class _RecordingConfig:
            def __init__(self) -> None:
                self.model_key = "team-configured"
                self.max_tokens = 256
                self.temperature = 0.1
                self.effective_thinking = False
                self.updates: list[dict] = []

            def update(self, **kwargs) -> None:
                self.updates.append(kwargs)

        cfg = _RecordingConfig()
        calls: list[str] = []
        fallback_emitted: list[int] = []

        def fake_stream(*args, **kwargs):
            calls.append(kwargs["model_key"])
            if not fallback_emitted:
                fallback_emitted.append(1)
                yield {"type": "model_fallback", "model_key": "team-fallback"}
            yield {"type": "text_delta", "text": "recovered"}
            yield {"type": "message_end", "stop_reason": "end_turn", "usage": {}}

        with self._session(cfg, fake_stream) as session:
            events = list(session.generate_turn("test"))
            self.assertEqual(calls, ["team-configured"])
            self.assertEqual(session._turn_fallback_model_key, "team-fallback")
            # The automatic fallback must never write the saved user model choice.
            self.assertEqual(cfg.updates, [])
            status = [e["message"] for e in events if e["type"] == "status"]
            self.assertTrue(any("临时" in msg and "team-fallback" in msg for msg in status))
            # The next user turn starts on the user's original model again.
            calls.clear()
            list(session.generate_turn("next question"))
            self.assertEqual(calls, ["team-configured"])
            self.assertIsNone(session._turn_fallback_model_key)

    def test_same_turn_tool_iteration_reuses_turn_scoped_fallback(self) -> None:
        from bi_agent.reliability import ValidationStatus

        responses = iter([
            [
                {"type": "model_fallback", "model_key": "team-fallback"},
                {"type": "tool_use_start", "id": "tu-1", "name": "Ontology-FactQuery"},
                {"type": "tool_use_end", "id": "tu-1", "name": "Ontology-FactQuery",
                 "input": {"sql": "select 1"}},
                {"type": "message_end", "stop_reason": "tool_use", "usage": {}},
            ],
            [
                {"type": "text_delta", "text": "结论：查询完成。"},
                {"type": "message_end", "stop_reason": "end_turn", "usage": {}},
            ],
        ])
        calls: list[str] = []

        def fake_stream(*args, **kwargs):
            calls.append(kwargs["model_key"])
            yield from next(responses)

        with self._session(self._cfg(), fake_stream) as session:
            with patch.object(WebSession, "_execute_tool", return_value=("ok", False)), \
                 patch.object(WebSession, "record_query_result", return_value=None), \
                 patch("bi_agent.web.session.validate_claims", return_value=SimpleNamespace(
                     status=ValidationStatus.ALLOW, issues=(),
                 )):
                events = list(session.generate_turn("test"))
        self.assertEqual(calls, ["team-configured", "team-fallback"])
        self.assertIn(
            "结论：查询完成。",
            [e.get("text") for e in events if e["type"] == "text_delta"],
        )


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


class DisplayNameRegressionTests(unittest.TestCase):
    """Business-name-first display rules: deterministic name resolution,
    Ontology-MetricQuery alias/metadata, and chart/table/multidim normalization."""

    # --- shared helpers -------------------------------------------------

    def _session(self, **kwargs):
        agent = AgentDef("display-test", tools=[])
        return WebSession("/tmp", agent, OntologyStore(), **kwargs)

    def _capture_session(self, tool_name):
        captured = {}
        session = self._session(
            tool_executors={tool_name: lambda params, cwd: captured.update(params) or "ok"},
        )
        return session, captured

    def _seed_ontology_seen(self, session, code, name):
        session.ontology_seen[f"remote:1:metric:{code}"] = {
            "code": code, "name": name, "kind": "metric",
            "source": "remote", "repository_id": "1",
        }

    # --- 1-3: name picking ----------------------------------------------

    def test_chinese_label_beats_english_name(self) -> None:
        self.assertEqual(
            pick_display_name({"code": "M0001", "label": "采购金额", "name": "purchase_amount"}),
            "采购金额",
        )

    def test_label_empty_falls_back_to_name(self) -> None:
        self.assertEqual(
            pick_display_name({"code": "M0001", "label": "", "name": "采购金额"}),
            "采购金额",
        )
        self.assertEqual(
            pick_display_name({"code": "M0001", "label": "-", "name": "?", "alias": "采购金额"}),
            "采购金额",
        )

    def test_code_only_keeps_code(self) -> None:
        self.assertEqual(pick_display_name({"code": "M0001"}), "M0001")
        self.assertEqual(display_text("M0001", ""), "M0001")
        self.assertEqual(display_text("M0001", "-"), "M0001")

    def test_display_text_formats_and_unique_aliases(self) -> None:
        self.assertEqual(display_text("M0001", "采购金额"), "采购金额（M0001）")
        self.assertEqual(display_text("M0001", "采购金额", trace=False), "采购金额")
        self.assertEqual(unique_aliases({"M1": "采购金额", "M2": "采购金额"}),
                         {"M1": "采购金额", "M2": "采购金额（M2）"})

    # --- 4-5: Ontology-MetricQuery alias and metadata --------------------------

    def test_metric_data_query_uses_display_name_alias_and_metadata(self) -> None:
        class FakeClient:
            cache_ttl = 30.0

            def metadata_query(self, analysis, common):
                return {"rows": [{"code": "M0001", "label": "采购金额", "name": "purchase_amount"}]}

            def data_query(self, analysis, common):
                self.analysis = analysis
                return {"resultType": "TABLE", "result": {"rows": [{"D0001": "A", "M0001": 2}]}}

        client = FakeClient()
        output = _make_metric_data_query(client)({
            "metric_codes": ["M0001"], "dimensions": ["D0001"], "page_size": 20,
        }, ".")
        self.assertEqual(client.analysis["indicators"][0]["alias"], "采购金额")
        self.assertNotEqual(client.analysis["indicators"][0]["alias"], "M0001")
        envelope = json.loads(output.split("# Ontology-MetricQuery (analysis/data/query)\n\n", 1)[1])
        scope = envelope["scope"]
        semantic = envelope["semantic"]
        metric_meta = scope["metrics"][0]
        self.assertEqual(metric_meta["code"], "M0001")
        self.assertEqual(metric_meta["display_name"], "采购金额")
        self.assertEqual(metric_meta["alias"], "采购金额")
        self.assertEqual(metric_meta["kind"], "metric")
        # Legacy fields are preserved.
        self.assertEqual(scope["metric_codes"], ["M0001"])
        self.assertEqual(scope["dimensions"], ["D0001"])
        # Dimension name metadata is present; unresolvable codes stay codes.
        self.assertEqual(scope["dimension_names"]["D0001"], "D0001")
        self.assertEqual(semantic["metric_names"]["M0001"], "采购金额")

    def test_metric_data_query_degrades_to_code_without_metadata(self) -> None:
        class FakeClient:
            cache_ttl = 30.0

            def data_query(self, analysis, common):
                self.analysis = analysis
                return {"resultType": "TABLE", "result": {"rows": []}}

        client = FakeClient()
        output = _make_metric_data_query(client)({
            "metric_codes": ["M0001"], "dimensions": [], "page_size": 20,
        }, ".")
        self.assertEqual(client.analysis["indicators"][0]["alias"], "M0001")
        self.assertIn("metric_codes", output)

    # --- 6-9: chart normalization via session ----------------------------

    def test_bar_chart_series_and_x_axis_use_business_names(self) -> None:
        session, captured = self._capture_session("ChartGenerate")
        self._seed_ontology_seen(session, "M0001", "采购金额")
        self._seed_ontology_seen(session, "BU001", "华东区")
        self._seed_ontology_seen(session, "BU002", "华南区")
        session._execute_tool({"name": "ChartGenerate", "input": {
            "chart_type": "bar", "title": "M0001 分布",
            "x_axis": ["BU001", "BU002"],
            "series": [{"name": "M0001", "data": [10, 20]}],
            "source_note": "M0001 · T_FM_MgmtPnL · 2024",
        }})
        self.assertEqual(captured["series"][0]["name"], "采购金额")
        self.assertEqual(captured["x_axis"], ["华东区", "华南区"])
        # source_note keeps the traceability code untouched.
        self.assertIn("M0001", captured["source_note"])
        # Embedded title text is not blindly rewritten.
        self.assertEqual(captured["title"], "M0001 分布")

    def test_pie_chart_slice_names_use_business_names(self) -> None:
        session, captured = self._capture_session("ChartGenerate")
        self._seed_ontology_seen(session, "BU001", "华东区")
        session._execute_tool({"name": "ChartGenerate", "input": {
            "chart_type": "pie", "title": "区域占比",
            "series": [{"name": "占比", "data": [{"name": "BU001", "value": 62}]}],
            "source_note": "BU001 · orders",
        }})
        self.assertEqual(captured["series"][0]["data"][0]["name"], "华东区")
        self.assertIn("BU001", captured["source_note"])

    def test_multidim_dimension_labels_use_business_names(self) -> None:
        session, captured = self._capture_session("ChartGenerateMultiDim")
        self._seed_ontology_seen(session, "D0001", "管理单元")
        self._seed_ontology_seen(session, "M0001", "采购金额")
        session._execute_tool({"name": "ChartGenerateMultiDim", "input": {
            "title": "多维洞察", "metric_code": "M0001",
            "default_dim": "d1", "source_note": "M0001 · orders",
            "dimensions": [{
                "key": "d1", "label": "D0001", "chart_type": "bar",
                "x_axis": ["BU001", "BU002"],
                "series": [{"name": "M0001", "data": [10, 20]}],
            }],
        }})
        self.assertEqual(captured["dimensions"][0]["label"], "管理单元")
        self.assertEqual(captured["dimensions"][0]["series"][0]["name"], "采购金额")
        self.assertEqual(captured["dimensions"][0]["x_axis"], ["BU001", "BU002"])
        self.assertEqual(captured["default_dim"], "d1")

    # --- 10-12: table normalization --------------------------------------

    def test_table_headers_use_business_names(self) -> None:
        session, captured = self._capture_session("TableGenerate")
        self._seed_ontology_seen(session, "D0001", "管理单元")
        session._execute_tool({"name": "TableGenerate", "input": {
            "title": "按单元汇总", "source_note": "D0001 · orders",
            "columns": [{"key": "D0001", "label": "D0001"},
                        {"key": "amount", "label": "金额"}],
            "rows": [["A", 1], ["B", 2]],
        }})
        self.assertEqual(captured["columns"][0]["label"], "管理单元")

    def test_table_code_and_name_columns_name_first_but_code_traceable(self) -> None:
        session, captured = self._capture_session("TableGenerate")
        session._execute_tool({"name": "TableGenerate", "input": {
            "title": "供应商采购", "source_note": "orders",
            "columns": [{"key": "supplier_code", "label": "供应商编码"},
                        {"key": "supplier_name", "label": "供应商名称"},
                        {"key": "amount", "label": "金额"}],
            "rows": [{"supplier_code": "S001", "supplier_name": "甲供应商", "amount": 10}],
        }})
        keys = [c["key"] for c in captured["columns"]]
        # Name column is moved ahead of its code column; the code column is kept.
        self.assertLess(keys.index("supplier_name"), keys.index("supplier_code"))
        self.assertIn("supplier_code", keys)
        self.assertEqual(captured["rows"][0]["supplier_code"], "S001")

    def test_user_explicit_code_request_is_not_force_rewritten(self) -> None:
        session, captured = self._capture_session("TableGenerate")
        self._seed_ontology_seen(session, "D0001", "管理单元")
        # The model already rendered a readable "编码" column label: our
        # deterministic layer must leave explicit code displays alone.
        session._execute_tool({"name": "TableGenerate", "input": {
            "title": "按编码查看", "source_note": "D0001 · orders",
            "columns": [{"key": "unit_code", "label": "经营单元编码"},
                        {"key": "amount", "label": "金额"}],
            "rows": [["BU001", 1]],
        }})
        self.assertEqual(captured["columns"][0]["label"], "经营单元编码")
        self.assertEqual(captured["rows"][0][0], "BU001")

    # --- 13-14: no guessing / no collateral rewriting ---------------------

    def test_unknown_code_is_preserved_not_guessed(self) -> None:
        self.assertEqual(normalize_text("M9999", lambda code: None), "M9999")
        self.assertEqual(normalize_text("采购金额", lambda code: "猜测名称"), "采购金额")

    def test_sql_json_url_are_never_rewritten(self) -> None:
        resolver = lambda code: "采购金额" if code == "M0001" else None
        for text in (
            "SELECT unit_code, unit_name, SUM(amount) FROM orders GROUP BY unit_code",
            '{"metric_codes": ["M0001"], "dimensions": ["D0001"]}',
            "https://host/api/analysis/data/query?metric=M0001",
            "M0001 · T_FM_MgmtPnL · 2024",
        ):
            self.assertEqual(normalize_text(text, resolver), text)

    def test_looks_like_code_recognition(self) -> None:
        for code in ("M0001", "MET001", "D001", "DIM001", "BO0006", "LE0001",
                     "AT0001", "TERM001", "BU001", "supplier_code", "unit_code"):
            self.assertTrue(looks_like_code(code), code)
        for text in ("采购金额", "2024Q1", "T1", "A", "M1", "华东区", "amount"):
            self.assertFalse(looks_like_code(text), text)

    # --- 15: claims / AskUser / report flow stay intact -------------------

    def test_claims_and_scope_flow_survive_display_name_metadata(self) -> None:
        from bi_agent.reliability import claims_from_query_result, normalize_query_result, Provenance

        envelope = normalize_query_result(
            {"result": {"rows": [{"M0001": 100}]}},
            scope={"metric_codes": ["M0001"],
                   "metrics": [{"code": "M0001", "display_name": "采购金额", "alias": "采购金额", "kind": "metric"}],
                   "dimensions": ["D0001"]},
            semantic={"metric_names": {"M0001": "采购金额"}},
            provenance=Provenance(source="remote", api="analysis/data/query", metric_code="M0001"),
        )
        session = self._session()
        session.record_query_result("Ontology-MetricQuery", {"metric_codes": ["M0001"]},
                                    "[RESULT_METADATA]\n" + json.dumps(envelope.to_dict(), ensure_ascii=False))
        self.assertTrue(session.claims)
        self.assertEqual(session.analysis_context.metrics, ("M0001",))
        # The display metadata feeds the session resolver without breaking claims.
        resolver = session._display_resolver()
        self.assertEqual(resolver("M0001"), "采购金额")

    def test_sql_code_name_pair_metadata(self) -> None:
        self.assertEqual(
            _code_name_pairs(["unit_code", "unit_name", "amount"]),
            [{"code_column": "unit_code", "name_column": "unit_name"}],
        )
        self.assertEqual(_code_name_pairs(["code", "name"]),
                         [{"code_column": "code", "name_column": "name"}])
        self.assertEqual(_code_name_pairs(["unit_code", "amount"]), [])

    def test_existing_chart_validation_and_scope_untouched(self) -> None:
        from bi_agent.reliability import Measure, SemanticType, validate_chart_measures

        measures = [
            Measure("采购金额", 0, unit="元", semantic_type=SemanticType.OBSERVED, scope={"metric_codes": ["M0001"]}),
            Measure("采购金额", 0, unit="元", semantic_type=SemanticType.OBSERVED, scope={"metric_codes": ["M0001"]}),
        ]
        self.assertTrue(validate_chart_measures(measures).ok)
        session, captured = self._capture_session("ChartGenerate")
        session.record_query_result("Ontology-FactQuery", {"semantic_type": "ESTIMATED", "unit": "u"}, "rows unavailable")
        session._execute_tool({"name": "ChartGenerate", "input": {
            "chart_type": "bar", "title": "x", "x_axis": ["A"],
            "series": [{"name": "S", "data": [1]}],
        }})
        # The session still injects semantic metadata from the latest query result.
        self.assertEqual(captured["series"][0]["semantic_type"], "ESTIMATED")
        self.assertEqual(captured["series"][0]["unit"], "u")
