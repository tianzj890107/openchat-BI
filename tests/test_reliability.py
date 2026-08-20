from __future__ import annotations

import unittest
import json
from unittest.mock import patch

from bi_agent.reliability import (
    AnalysisContext, Claim, ClaimLevel, LimitationType, Measure, SemanticType,
    ValidationStatus, compare_measures, reconcile, render_claim, validate_claims,
    Provenance, QueryResult, claims_from_query_result, normalize_query_result,
)
from bi_agent.web.session import WebSession
from bi_agent.ontology.store import OntologyStore
from open_claude.agent_def import AgentDef
from bi_agent.tools.chart_tools import _make_chart_generate


class ReliabilityTests(unittest.TestCase):
    def test_context_inheritance_and_partial_scope_change(self):
        context = AnalysisContext(subject="Entity1", goal="trend", metrics=("Metric1",),
                                  dimensions=("Dimension1",), filters=("Filter1",), time_scope="T1")
        inherited = context.merge({"dimensions": ("Dimension2",)})
        self.assertEqual(inherited.subject, "Entity1")
        self.assertEqual(inherited.metrics, ("Metric1",))
        self.assertEqual(inherited.filters, ("Filter1",))
        self.assertEqual(inherited.dimensions, ("Dimension2",))

    def test_aggregation_reconciliation(self):
        self.assertEqual(reconcile(100, [40, 60]).status, ValidationStatus.ALLOW)
        conflict = reconcile(100, [40, 70])
        self.assertEqual(conflict.status, ValidationStatus.REJECT)
        self.assertIn(LimitationType.CONFLICTING_EVIDENCE, conflict.limitations)

    def test_claim_levels_do_not_upgrade_association_or_inference(self):
        association = Claim("c1", "A 与 B 存在关联", ClaimLevel.ASSOCIATION)
        self.assertIn("发现关联", render_claim(association))
        result = validate_claims([association], "A 导致 B")
        self.assertEqual(result.status, ValidationStatus.REJECT)
        inference = Claim("c2", "A 可能是一个排查方向", ClaimLevel.INFERENCE)
        self.assertEqual(validate_claims([inference], "可能需要进一步验证").status, ValidationStatus.ALLOW)
        self.assertEqual(validate_claims([inference], "A 已确认导致 B").status, ValidationStatus.REJECT)

    def test_proxy_and_missing_measure_are_explicit(self):
        proxy = Measure("MeasureProxy", 12, semantic_type=SemanticType.PROXY)
        self.assertEqual(proxy.semantic_type, SemanticType.PROXY)
        limitation = Claim("c", "Requested Measure 当前无法直接计算", ClaimLevel.FACT,
                            limitations=(LimitationType.DATA_MISSING,))
        self.assertIn("DATA_MISSING", render_claim(limitation))

    def test_semantic_and_scope_comparison(self):
        left = Measure("Metric1", 1, unit="u", scope={"T": "1"})
        estimated = Measure("Metric1", 1, unit="u", semantic_type=SemanticType.ESTIMATED,
                            scope={"T": "1"})
        different_scope = Measure("Metric1", 1, unit="u", scope={"T": "2"})
        self.assertEqual(compare_measures(left, estimated).status, ValidationStatus.REJECT)
        self.assertEqual(compare_measures(left, different_scope).status, ValidationStatus.REJECT)

    def test_unsupported_narrative_number_is_rejected(self):
        claim = Claim("c", "查询结果为 100", ClaimLevel.FACT)
        self.assertEqual(validate_claims([claim], "查询结果为 100").status, ValidationStatus.ALLOW)
        self.assertEqual(validate_claims([claim], "查询结果为 999").status, ValidationStatus.REJECT)

    def test_query_metadata_builds_claims_and_session_propagates_scope(self):
        envelope = normalize_query_result(
            {"columns": ["M1"], "rows": [{"M1": 100}]},
            scope={"metric_codes": ["M1"], "time_scope": "T1", "entity_scope": ["E1"]},
            semantic={"metric": "M1", "unit": "u", "semantic_type": "OBSERVED"},
            provenance=Provenance(source="SQLite", query="select 100"),
        )
        claims = claims_from_query_result(envelope)
        self.assertEqual(claims[0].level, ClaimLevel.FACT)
        self.assertEqual(claims[0].scope["time_scope"], "T1")

        session = WebSession("/tmp", AgentDef("test", tools=[]), OntologyStore())
        session.record_query_result("SQLRun", {
            "metric_codes": ["M1"], "time_scope": "T1", "entity_scope": ["E1"]
        }, "[RESULT_METADATA]\n" + json.dumps(envelope.to_dict(), ensure_ascii=False))
        session.record_query_result("MetricDataQuery", {"dimensions": ["D1"]}, "rows unavailable")
        self.assertEqual(session.analysis_context.metrics, ("M1",))
        self.assertEqual(session.analysis_context.time_scope, "T1")
        self.assertEqual(session.analysis_context.entity_scope, ("E1",))
        self.assertEqual(session.analysis_context.dimensions, ("D1",))
        self.assertTrue(session.claims)

        session.record_query_result("MetricDataQuery", {"time_scope": "T2"}, "rows unavailable")
        self.assertEqual(session.analysis_context.time_scope, "T2")
        self.assertEqual(session.analysis_context.metrics, ("M1",))
        self.assertEqual(session.analysis_context.dimensions, ("D1",))

    def test_session_reconciliation_marks_claims_conflicting(self):
        session = WebSession("/tmp", AgentDef("test", tools=[]), OntologyStore())
        session.record_query_result("MetricDataQuery", {
            "metric": "M1", "parent_value": 100,
        }, "parent")
        session.record_query_result("MetricDataQuery", {
            "metric": "M1", "dimensions": ["D1"], "child_values": [40, 70],
        }, "children")
        self.assertTrue(session.reconciliation_conflicts)
        self.assertTrue(all(LimitationType.CONFLICTING_EVIDENCE in c.limitations for c in session.claims))

    def test_chart_gets_metadata_from_latest_query_result(self):
        captured = {}
        session = WebSession("/tmp", AgentDef("test", tools=[]), OntologyStore(),
                             tool_executors={"ChartGenerate": lambda params, cwd: captured.update(params) or "ok"})
        session.record_query_result("SQLRun", {"semantic_type": "ESTIMATED", "unit": "u"}, "rows unavailable")
        session._execute_tool({"name": "ChartGenerate", "input": {
            "chart_type": "bar", "title": "x", "x_axis": ["A"],
            "series": [{"name": "S", "data": [1]}],
        }})
        self.assertEqual(captured["series"][0]["semantic_type"], "ESTIMATED")
        self.assertEqual(captured["series"][0]["scope"], session.query_results[-1].scope)

    def test_chart_rejects_same_unit_incompatible_semantics(self):
        output = _make_chart_generate()({
            "chart_type": "bar", "title": "comparison", "x_axis": ["A"],
            "series": [
                {"name": "observed", "data": [1], "unit": "u", "semantic_type": "OBSERVED"},
                {"name": "forecast", "data": [1], "unit": "u", "semantic_type": "FORECAST"},
            ],
        }, ".")
        self.assertIn("comparison rejected", output)

    def test_answer_generation_blocks_unsupported_association_conclusion(self):
        responses = iter([
            [{"type": "text_delta", "text": "A 导致 B。"}, {"type": "message_end", "stop_reason": "end_turn", "usage": {}}],
            [{"type": "text_delta", "text": "A 导致 B。"}, {"type": "message_end", "stop_reason": "end_turn", "usage": {}}],
            [{"type": "text_delta", "text": "A 导致 B。"}, {"type": "message_end", "stop_reason": "end_turn", "usage": {}}],
        ])
        def fake_stream(*_args, **_kwargs):
            yield from next(responses)
        with patch("bi_agent.web.session.stream_message", fake_stream):
            session = WebSession("/tmp", AgentDef("test", tools=[]), OntologyStore())
            session.claims = [Claim("a", "A 与 B 存在关联", ClaimLevel.ASSOCIATION)]
            session.messages.append({"role": "user", "content": "为什么"})
            events = list(session._run_loop())
        self.assertTrue(any(e["type"] == "answer_blocked" for e in events))
        self.assertNotIn("done", [e["type"] for e in events])

    def test_proxy_narrative_must_state_unavailability_and_proxy(self):
        proxy = Claim("p", "可使用代理指标 P，但不等价于原指标", ClaimLevel.INFERENCE,
                      semantic={"semantic_type": "PROXY"})
        self.assertEqual(validate_claims([proxy], "原指标无法直接计算；以下为代理分析。").status,
                         ValidationStatus.ALLOW)
        self.assertEqual(validate_claims([proxy], "P 的结果为 12。").status,
                         ValidationStatus.REJECT)

    def test_proxy_constraint_is_used_by_real_session_answer_loop(self):
        responses = iter([
            [{"type": "text_delta", "text": "原指标无法直接计算；以下为代理分析。"}, {"type": "message_end", "stop_reason": "end_turn", "usage": {}}],
            [{"type": "text_delta", "text": "原指标无法直接计算；以下为代理分析。"}, {"type": "message_end", "stop_reason": "end_turn", "usage": {}}],
        ])
        def fake_stream(*_args, **_kwargs):
            yield from next(responses)
        with patch("bi_agent.web.session.stream_message", fake_stream):
            session = WebSession("/tmp", AgentDef("test", tools=[]), OntologyStore())
            session.record_query_result("MetricLookup", {
                "requested_measure": "RequestedMetric", "available": False, "proxy": "ProxyMetric",
            }, "no direct result")
            session.messages.append({"role": "user", "content": "RequestedMetric"})
            events = list(session._run_loop())
        self.assertIn("代理分析", [e.get("text", "") for e in events if e["type"] == "llm_response"][-1])
        self.assertNotIn("answer_blocked", [e["type"] for e in events])

    def test_unsupported_number_is_blocked_by_real_session_answer_loop(self):
        responses = iter([
            [{"type": "text_delta", "text": "查询结果为 999。"}, {"type": "message_end", "stop_reason": "end_turn", "usage": {}}],
            [{"type": "text_delta", "text": "查询结果为 999。"}, {"type": "message_end", "stop_reason": "end_turn", "usage": {}}],
            [{"type": "text_delta", "text": "查询结果为 999。"}, {"type": "message_end", "stop_reason": "end_turn", "usage": {}}],
        ])
        def fake_stream(*_args, **_kwargs):
            yield from next(responses)
        with patch("bi_agent.web.session.stream_message", fake_stream):
            session = WebSession("/tmp", AgentDef("test", tools=[]), OntologyStore())
            session.record_query_result("SQLRun", {}, "[RESULT_METADATA]\n" + json.dumps(
                normalize_query_result({"rows": [{"M1": 100}]}).to_dict()
            ))
            session.messages.append({"role": "user", "content": "M1"})
            events = list(session._run_loop())
        self.assertTrue(any(e["type"] == "answer_blocked" for e in events))

    def test_display_tools_do_not_become_query_results_or_claims(self):
        session = WebSession("/tmp", AgentDef("test", tools=[]), OntologyStore())
        session.record_query_result(
            "SQLRun", {"metric_codes": ["M1"]},
            "[RESULT_METADATA]\n" + json.dumps(normalize_query_result(
                {"columns": ["M1"], "rows": [{"M1": 100}]}).to_dict()),
        )
        session.record_query_result(
            "TableGenerate", {"title": "t"},
            '<TABLE_SPEC>{"columns":["M1"],"rows":[{"M1":100}]}</TABLE_SPEC>',
        )
        session.record_query_result(
            "ChartGenerate", {"series": [{"name": "S", "data": [100]}]},
            '{"series":[{"name":"S","data":[100]}]}',
        )
        self.assertEqual(len(session.query_results), 1)
        self.assertEqual(len(session._turn_results), 1)
        self.assertEqual(len(session.claims), 1)
        self.assertEqual(session.query_results[-1].semantic.get("metric_codes"), ["M1"])

    def test_reconciliation_skips_parent_child_with_different_metrics(self):
        session = WebSession("/tmp", AgentDef("test", tools=[]), OntologyStore())
        session.record_query_result("SQLRun", {"metric": "M1", "parent_value": 100}, "parent")
        session.record_query_result("SQLRun", {"metric": "M2", "child_values": [40, 70]}, "children")
        self.assertEqual(session.reconciliation_conflicts, [])

    def test_reconciliation_finds_explicit_pair_across_interleaved_results(self):
        session = WebSession("/tmp", AgentDef("test", tools=[]), OntologyStore())
        session.record_query_result("SQLRun", {"metric": "M1", "parent_value": 100}, "parent")
        session.record_query_result("SQLRun", {"metric": "M1"}, "unrelated row")
        session.record_query_result("SQLRun", {"metric": "M1", "child_values": [40, 70]}, "children")
        self.assertTrue(session.reconciliation_conflicts)

    def test_empty_and_degraded_relation_outputs_do_not_create_association_claims(self):
        cases = [
            ("RelationLookup", {"entity": "E1"},
             "# Remote relations · E1\n## 关联对象 (0)\n## 关系证据 (0)"),
            ("RelationLookup", {"entity": "E1"}, "RelationLookup: empty entity."),
            ("RelationLookup", {"entity": "E1"},
             "降级说明: 当前仓库只返回关联顶点，方向和关系类型不可用。\n## 关联对象 (3)\n## 关系证据 (0)"),
            ("GraphContext", {"query": "X"},
             "降级说明: 当前仓库未返回边明细，方向和关系类型不作为证据。\n## 关系证据 (0)"),
            ("GraphExpand", {"anchor": "BO1"}, "未发现可关联的上下游业务对象。"),
            ("GraphExpand", {"anchor": "BO1"},
             "GraphExpand: [BO1] 无法通过远程关系图定位所属业务对象。"),
        ]
        for tool, params, output in cases:
            with self.subTest(tool=tool, output=output[:24]):
                session = WebSession("/tmp", AgentDef("test", tools=[]), OntologyStore())
                session.record_query_result(tool, params, output)
                self.assertFalse(any(c.level == ClaimLevel.ASSOCIATION for c in session.claims))

    def test_relation_output_with_edge_evidence_creates_association_claim(self):
        session = WebSession("/tmp", AgentDef("test", tools=[]), OntologyStore())
        session.record_query_result(
            "RelationLookup", {"entity": "E1"},
            "# Remote relations · E1\n## 关联对象 (2)\n- O2\n## 关系证据 (3)\n- E1 -> O2 [r1]",
        )
        self.assertTrue(any(c.level == ClaimLevel.ASSOCIATION for c in session.claims))
        session2 = WebSession("/tmp", AgentDef("test", tools=[]), OntologyStore())
        session2.record_query_result(
            "GraphExpand", {"anchor": "BO1"},
            "# Remote GraphExpand · 锚点 BO1\n## 关联业务对象与路径证据 (1)\n- 本体关系链: BO1 -> BO2",
        )
        self.assertTrue(any(c.level == ClaimLevel.ASSOCIATION for c in session2.claims))

    def test_validate_claims_allows_formatting_ordinal_range_and_percentage(self):
        fact = Claim("c", "查询结果为 100", ClaimLevel.FACT)
        self.assertEqual(validate_claims([fact], "查询结果为 100.0").status, ValidationStatus.ALLOW)
        self.assertEqual(validate_claims([fact], "查询结果为 100.00 元").status, ValidationStatus.ALLOW)
        rate = Claim("r", "比例为 0.25", ClaimLevel.FACT)
        self.assertEqual(validate_claims([rate], "比例为 25%").status, ValidationStatus.ALLOW)
        self.assertEqual(validate_claims([rate], "比例是 25.0%").status, ValidationStatus.ALLOW)
        self.assertEqual(validate_claims([fact], "这是第 2 步的结论，查询结果为 100。").status, ValidationStatus.ALLOW)
        self.assertEqual(validate_claims([fact], "第3季度查询结果为 100。").status, ValidationStatus.ALLOW)
        self.assertEqual(validate_claims([fact], "建议给出 1–2 条措施。").status, ValidationStatus.ALLOW)
        self.assertEqual(validate_claims([fact], "1、先核对数据；2、再下结论。结果为 100。").status, ValidationStatus.ALLOW)
        self.assertEqual(validate_claims([fact], "查询结果为 100（2024 年）。").status, ValidationStatus.ALLOW)
        self.assertEqual(validate_claims([fact], "查询结果为 999。").status, ValidationStatus.REJECT)


if __name__ == "__main__":
    unittest.main()
