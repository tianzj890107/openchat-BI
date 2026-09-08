"""RED tests for lightweight structured Cognitive Policy decisions.

The suite uses only deterministic inputs and local fakes.  It must not call an
LLM, Doris, a remote ontology service, or a real conversation store.
"""

from __future__ import annotations

import unittest
from unittest.mock import patch

from bi_agent.ontology.store import OntologyStore
from bi_agent.tools import analysis_policy
from bi_agent.web.session import WebSession
from open_claude.agent_def import AgentDef


FACT = "Ontology-FactQuery"
METRIC = "Ontology-MetricQuery"
SEMANTIC = "Ontology-SemanticQuery"
ASK = "AskUser"


def final_response(text="分析完成"):
    return iter([
        {"type": "text_delta", "text": text},
        {"type": "message_end", "stop_reason": "end_turn", "usage": {}},
    ])


class CognitivePolicyRedTests(unittest.TestCase):
    def _build(self, question, tools):
        builder = getattr(analysis_policy, "build_cognitive_policy_decision", None)
        if not callable(builder):
            self.fail("RED: 缺少 build_cognitive_policy_decision 纯函数")
        decision = builder(question, tools)
        self.assertIsInstance(decision, dict)
        return decision

    def _assert_contract(self, decision):
        required = {
            "policy_version", "mode", "reason_code", "next_step",
            "required_tools", "evidence_required", "needs_human",
            "input_digest",
        }
        self.assertTrue(required.issubset(decision), required - set(decision))
        self.assertEqual(decision["policy_version"], 1)
        self.assertIsInstance(decision["required_tools"], list)
        self.assertIsInstance(decision["evidence_required"], bool)
        self.assertIsInstance(decision["needs_human"], bool)
        self.assertRegex(decision["input_digest"], r"^sha256:[0-9a-f]{64}$")

    def test_fact_query_uses_available_fact_fallback(self):
        decision = self._build("查询本月采购金额是多少", [FACT, ASK])
        self._assert_contract(decision)
        self.assertEqual(decision["mode"], "FACT_QUERY")
        self.assertEqual(decision["reason_code"], "FACT_REQUEST_RESOLVED")
        self.assertEqual(decision["next_step"], "QUERY_DORIS")
        self.assertEqual(decision["required_tools"], [FACT])
        self.assertTrue(decision["evidence_required"])
        self.assertFalse(decision["needs_human"])

    def test_metric_query_is_preferred_and_allowed_tool_order_is_irrelevant(self):
        first = self._build("按月份查看采购金额趋势", [FACT, METRIC, ASK])
        second = self._build("按月份查看采购金额趋势", [ASK, METRIC, FACT, METRIC])
        self.assertEqual(first, second)
        self.assertEqual(first["required_tools"], [METRIC])

    def test_diagnostic_route_reuses_existing_analysis_intent(self):
        decision = self._build("采购金额为什么下降？分析根因并给出建议", [FACT, ASK])
        self.assertEqual(decision["mode"], "DIAGNOSTIC_ANALYSIS")
        self.assertEqual(decision["reason_code"], "DIAGNOSTIC_REQUEST")
        self.assertEqual(decision["next_step"], "QUERY_DORIS")
        self.assertEqual(decision["required_tools"], [FACT])
        self.assertTrue(decision["evidence_required"])

    def test_l2_anomaly_or_problem_intent_is_diagnostic_without_root_cause_words(self):
        """Existing classify_intent L2 must not be flattened into FACT_QUERY."""
        for question in ("采购金额是否异常", "销售额最近有问题吗", "库存波动情况"):
            with self.subTest(question=question):
                decision = self._build(question, [FACT, ASK])
                self.assertEqual(decision["mode"], "DIAGNOSTIC_ANALYSIS")
                self.assertEqual(decision["reason_code"], "DIAGNOSTIC_REQUEST")
                self.assertEqual(decision["next_step"], "QUERY_DORIS")
                self.assertEqual(decision["required_tools"], [FACT])
                self.assertTrue(decision["evidence_required"])

    def test_ontology_definition_routes_to_semantic_query_not_doris(self):
        decision = self._build("采购订单这个业务对象的定义是什么", [FACT, SEMANTIC, ASK])
        self.assertEqual(decision["mode"], "ONTOLOGY_LOOKUP")
        self.assertEqual(decision["reason_code"], "ONTOLOGY_LOOKUP_REQUEST")
        self.assertEqual(decision["next_step"], "QUERY_ONTOLOGY")
        self.assertEqual(decision["required_tools"], [SEMANTIC])
        self.assertNotIn(FACT, decision["required_tools"])

    def test_ambiguous_request_asks_user_only_when_ask_user_is_allowed(self):
        decision = self._build("帮我分析一下", [FACT, ASK])
        self.assertEqual(decision["mode"], "CLARIFICATION")
        self.assertEqual(decision["reason_code"], "AMBIGUOUS_REQUEST")
        self.assertEqual(decision["next_step"], "ASK_USER")
        self.assertEqual(decision["required_tools"], [ASK])
        self.assertFalse(decision["evidence_required"])
        self.assertTrue(decision["needs_human"])

    def test_missing_query_capability_never_recommends_forbidden_tool(self):
        decision = self._build("查询本月采购金额是多少", [ASK])
        self.assertEqual(decision["mode"], "CAPABILITY_LIMITATION")
        self.assertEqual(decision["reason_code"], "QUERY_CAPABILITY_UNAVAILABLE")
        self.assertEqual(decision["next_step"], "DELIVER_LIMITATION")
        self.assertEqual(decision["required_tools"], [])
        self.assertFalse(decision["needs_human"])
        self.assertTrue(set(decision["required_tools"]).issubset({ASK}))

    def test_snapshot_contains_digest_not_raw_question_or_sensitive_payload(self):
        question = "查询采购金额，token=super-secret，SQL=select * from orders"
        decision = self._build(question, [FACT])
        self._assert_contract(decision)
        serialized = repr(decision).lower()
        for forbidden in ("super-secret", "select *", "orders", question.lower()):
            self.assertNotIn(forbidden, serialized)
        self.assertFalse(any(key in decision for key in ("question", "user_text", "sql", "messages")))

    def test_normalized_input_and_duplicate_tools_are_deterministic(self):
        first = self._build(" 查询  本月采购金额是多少 ", [FACT, ASK, FACT])
        second = self._build("查询 本月采购金额是多少", [ASK, FACT])
        self.assertEqual(first, second)
        self.assertEqual(len(first["required_tools"]), len(set(first["required_tools"])))

    def test_web_session_emits_one_policy_before_first_llm_request_and_snapshot_is_defensive(self):
        session = WebSession(
            "/tmp",
            AgentDef("test", tools=[FACT, ASK]),
            OntologyStore(),
        )
        with patch("bi_agent.web.session.stream_message", return_value=final_response()):
            events = list(session.generate_turn("查询本月采购金额是多少"))

        policies = [event for event in events if event.get("type") == "cognitive_policy"]
        self.assertEqual(len(policies), 1)
        policy_index = next(i for i, event in enumerate(events) if event.get("type") == "cognitive_policy")
        request_index = next(i for i, event in enumerate(events) if event.get("type") == "llm_request")
        self.assertLess(policy_index, request_index)
        self.assertNotIn("question", policies[0])
        self.assertNotIn("查询本月采购金额是多少", repr(policies[0]))

        self.assertTrue(hasattr(session, "cognitive_policy_decision"))
        snapshot = session.cognitive_policy_decision
        self.assertEqual(snapshot["mode"], "FACT_QUERY")
        snapshot["mode"] = "CORRUPTED"
        self.assertEqual(session.cognitive_policy_decision["mode"], "FACT_QUERY")

    def test_policy_event_is_registered_for_turn_id_annotation(self):
        from bi_agent.web.app import _TURN_EVENT_TYPES

        self.assertIn(
            "cognitive_policy",
            _TURN_EVENT_TYPES,
            "RED: cognitive_policy SSE 事件尚未加入 turn_id 注解集合",
        )


if __name__ == "__main__":
    unittest.main()
