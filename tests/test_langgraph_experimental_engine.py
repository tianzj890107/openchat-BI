"""RED contract tests for the opt-in LangGraph analysis engine.

The production WebSession remains the default.  These tests describe the
minimum parity contract for a LangGraph-backed turn loop: the same SSE event
shapes, the same session state, the same AskUser resume path and the same
claim-repair behavior.  They are intentionally written before the engine.
"""

from __future__ import annotations

import threading
import time
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from bi_agent.ontology.store import OntologyStore
from bi_agent.web.session import WebSession
from open_claude.agent_def import AgentDef


TOOL_NAME = "Ontology-FactQuery"


def _provider_turns(*turns):
    """Return a fake provider that yields one recorded turn per call."""

    lock = threading.Lock()
    state = {"index": 0}

    def provider(*_args, **_kwargs):
        with lock:
            index = state["index"]
            state["index"] += 1
        turn = turns[min(index, len(turns) - 1)]
        return iter(turn)

    return provider


def _tool_turn(tool_id="tu-1", name=TOOL_NAME, params=None):
    return [
        {"type": "tool_use_start", "id": tool_id, "name": name},
        {"type": "tool_use_end", "id": tool_id, "name": name, "input": params or {}},
        {"type": "message_end", "stop_reason": "tool_use", "usage": {}},
    ]


def _text_turn(text):
    return [
        {"type": "text_delta", "text": text},
        {"type": "message_end", "stop_reason": "end_turn", "usage": {}},
    ]


def _multi_tool_turn(tools):
    events = []
    for tool in tools:
        events.extend([
            {"type": "tool_use_start", "id": tool["id"], "name": tool["name"]},
            {
                "type": "tool_use_end",
                "id": tool["id"],
                "name": tool["name"],
                "input": dict(tool.get("input") or {}),
            },
        ])
    events.append({"type": "message_end", "stop_reason": "tool_use", "usage": {}})
    return events


class LangGraphExperimentalEngineTests(unittest.TestCase):
    def _session(self, tools, executor=None, **kwargs):
        from bi_agent.experimental.langgraph_session import LangGraphWebSession

        executors = {TOOL_NAME: executor} if executor is not None else {}
        return LangGraphWebSession(
            "/tmp",
            AgentDef("test", tools=list(tools)),
            OntologyStore(),
            tool_executors=executors,
            **kwargs,
        )

    def test_engine_is_opt_in_and_legacy_remains_default(self):
        from bi_agent.experimental.factory import resolve_session_class

        self.assertIs(resolve_session_class(""), WebSession)
        self.assertIs(resolve_session_class("legacy"), WebSession)
        self.assertIsNot(resolve_session_class("langgraph"), WebSession)
        self.assertEqual(resolve_session_class("langgraph").__name__, "LangGraphWebSession")

    def test_tool_turn_emits_same_protocol_and_persists_messages(self):
        calls = []

        def executor(params, _cwd):
            calls.append(dict(params))
            return "value\n1"

        with patch(
            "bi_agent.web.session.stream_message",
            side_effect=_provider_turns(
                _tool_turn(params={"sql": "select 1"}),
                _text_turn("分析完成"),
            ),
        ):
            session = self._session([TOOL_NAME], executor=executor)
            events = list(session.generate_turn("查询数据"))

        kinds = [event["type"] for event in events]
        self.assertIn("iteration_start", kinds)
        self.assertIn("tool_result", kinds)
        self.assertIn("llm_response", kinds)
        self.assertEqual(kinds[-1], "done")
        self.assertEqual(events[-1]["stop_reason"], "end_turn")
        self.assertEqual(calls, [{"sql": "select 1"}])
        self.assertEqual(session.messages[0]["role"], "user")
        self.assertEqual(session.messages[-1]["content"][0]["text"], "分析完成")
        tool_result = next(e for e in events if e["type"] == "tool_result")
        self.assertEqual(tool_result["execution_status"], "SUCCEEDED")

    def test_claim_rejection_reprompts_and_only_valid_candidate_is_visible(self):
        from bi_agent.reliability import Claim, ClaimLevel, ValidationStatus

        responses = _provider_turns(
            _text_turn("结论：金额是 999999 元。"),
            _text_turn("结论：金额是 50 元。"),
        )
        validations = iter([
            SimpleNamespace(status=ValidationStatus.REJECT, issues=("unsupported_number",), findings=()),
            SimpleNamespace(status=ValidationStatus.ALLOW, issues=(), findings=()),
        ])

        with patch("bi_agent.web.session.stream_message", side_effect=responses), \
             patch("bi_agent.web.session.validate_claims", side_effect=lambda *_a, **_k: next(validations)):
            session = self._session([])
            session.claims = [Claim("c-1", "金额是 50 元", ClaimLevel.FACT)]
            events = list(session._run_loop())

        visible = "".join(e.get("text", "") for e in events if e["type"] == "text_delta")
        self.assertIn("50 元", visible)
        self.assertNotIn("999999", visible)
        self.assertEqual(len([e for e in events if e["type"] == "answer_validation"]), 1)
        self.assertEqual(len([e for e in events if e["type"] == "llm_response"]), 1)
        persisted = repr(session.messages)
        self.assertIn("50 元", persisted)
        self.assertNotIn("999999", persisted)

    def test_ask_user_pauses_and_choice_resumes_the_graph(self):
        with patch(
            "bi_agent.web.session.stream_message",
            side_effect=_provider_turns(
                _tool_turn(tool_id="ask-1", name="AskUser", params={
                    "question": "请选择口径",
                    "options": [{"id": "a", "label": "口径 A"}],
                }),
                _text_turn("已按口径 A 分析"),
            ),
        ):
            session = self._session(["AskUser"])
            first = list(session.generate_turn("请分析"))
            self.assertTrue(any(e["type"] == "awaiting_user_choice" for e in first))
            self.assertEqual(session.pending_tool_use_id, "ask-1")
            second = list(session.continue_with_choice(["a"], ["口径 A"]))

        kinds = [e["type"] for e in second]
        self.assertIn("user_choice_resolved", kinds)
        self.assertIn("llm_response", kinds)
        self.assertEqual(kinds[-1], "done")

    def test_events_are_sse_json_serializable(self):
        import json

        with patch(
            "bi_agent.web.session.stream_message",
            side_effect=_provider_turns(_text_turn("直接回答")),
        ):
            session = self._session([])
            events = list(session.generate_turn("你好"))

        for event in events:
            json.dumps(event, ensure_ascii=False)


if __name__ == "__main__":
    unittest.main()


class LangGraphParityTests(LangGraphExperimentalEngineTests):
    def _both(self, tools, provider_factory, executor=None):
        from bi_agent.experimental.langgraph_session import LangGraphWebSession

        executors = {TOOL_NAME: executor} if executor is not None else {}
        legacy = WebSession(
            "/tmp",
            AgentDef("test", tools=list(tools)),
            OntologyStore(),
            tool_executors=executors,
        )
        graph = LangGraphWebSession(
            "/tmp",
            AgentDef("test", tools=list(tools)),
            OntologyStore(),
            tool_executors=executors,
        )
        return legacy, graph

    def test_direct_answer_event_sequence_matches_legacy(self):
        with patch("bi_agent.web.session.stream_message", side_effect=_provider_turns(_text_turn("直接回答"))):
            legacy, graph = self._both([], lambda: None)
            legacy_events = list(legacy.generate_turn("你好"))
        with patch("bi_agent.web.session.stream_message", side_effect=_provider_turns(_text_turn("直接回答"))):
            graph_events = list(graph.generate_turn("你好"))

        self.assertEqual(
            [e["type"] for e in graph_events],
            [e["type"] for e in legacy_events],
        )
        self.assertEqual(
            "".join(e.get("text", "") for e in graph_events if e["type"] == "text_delta"),
            "直接回答",
        )

    def test_tool_turn_event_sequence_matches_legacy(self):
        def executor(_params, _cwd):
            return "value\n1"

        provider_turns = (
            _tool_turn(params={"sql": "select 1"}),
            _text_turn("分析完成"),
        )
        with patch("bi_agent.web.session.stream_message", side_effect=_provider_turns(*provider_turns)):
            legacy, graph = self._both([TOOL_NAME], lambda: None, executor=executor)
            legacy_events = list(legacy.generate_turn("查询数据"))
        with patch("bi_agent.web.session.stream_message", side_effect=_provider_turns(*provider_turns)):
            graph_events = list(graph.generate_turn("查询数据"))

        self.assertEqual(
            [e["type"] for e in graph_events],
            [e["type"] for e in legacy_events],
        )
        self.assertEqual(
            [e.get("name") for e in graph_events if e["type"] == "tool_result"],
            [e.get("name") for e in legacy_events if e["type"] == "tool_result"],
        )
        self.assertEqual(graph.messages, legacy.messages)

    def test_render_enforcement_matches_legacy(self):
        def executor(params, _cwd):
            if params.get("sql") == "select 1":
                return "value\n1"
            return "table rendered"

        provider_turns = (
            _tool_turn(params={"sql": "select 1"}),
            [
                {"type": "text_delta", "text": "结论：金额为 1。"},
                {"type": "message_end", "stop_reason": "end_turn", "usage": {}},
            ],
            _tool_turn(tool_id="tu-2", name="TableGenerate", params={
                "title": "金额",
                "columns": [{"key": "value", "label": "金额"}],
                "rows": [{"value": "1"}],
                "source_note": "test",
            }),
            _text_turn("结论：金额为 1。"),
        )
        with patch("bi_agent.web.session.stream_message", side_effect=_provider_turns(*provider_turns)):
            legacy, graph = self._both([TOOL_NAME, "TableGenerate"], lambda: None, executor=executor)
            legacy_events = list(legacy.generate_turn("查询数据"))
        with patch("bi_agent.web.session.stream_message", side_effect=_provider_turns(*provider_turns)):
            graph_events = list(graph.generate_turn("查询数据"))

        self.assertTrue(any(e["type"] == "render_enforce" for e in legacy_events))
        self.assertTrue(any(e["type"] == "render_enforce" for e in graph_events))
        self.assertEqual(
            [e["type"] for e in graph_events],
            [e["type"] for e in legacy_events],
        )
        self.assertIn("TableGenerate", [e.get("name") for e in graph_events if e["type"] == "tool_result"])

    def test_action_repair_and_recommendations_match_legacy(self):
        provider_turns = (
            _text_turn("结论：华东区域回款下降。"),
            _text_turn("行动建议\n\n- 对华东区域逾期客户逐户安排回款催收。"),
        )
        with patch("bi_agent.web.session.stream_message", side_effect=_provider_turns(*provider_turns)):
            legacy, graph = self._both([], lambda: None)
            legacy_events = list(legacy.generate_turn("回款下降怎么办"))
        with patch("bi_agent.web.session.stream_message", side_effect=_provider_turns(*provider_turns)):
            graph_events = list(graph.generate_turn("回款下降怎么办"))

        self.assertTrue(any(e["type"] == "action_repair" for e in graph_events))
        self.assertTrue(any(e["type"] == "action_recommendations" for e in graph_events))
        self.assertEqual(graph_events[-1]["type"], "done")
        self.assertEqual(graph_events[-1]["stop_reason"], "end_turn")
        self.assertEqual(
            [e["type"] for e in graph_events],
            [e["type"] for e in legacy_events],
        )

    def test_cancelled_turn_emits_session_superseded_without_done(self):
        from bi_agent.concurrency import SessionSlot
        from bi_agent.web.session import TurnContext

        slot = SessionSlot()
        cancel = threading.Event()
        cancel.set()
        lease = slot.try_acquire(cancel_event=cancel)
        graph = self._session([])
        graph._turn_ctx = TurnContext(slot, lease, cancel)
        events = list(graph._run_loop())

        self.assertEqual(events, [{"type": "session_superseded"}])


class LangGraphRecoveryAndGateParityTests(unittest.TestCase):
    def _pair(self, tools, executors=None, **kwargs):
        from bi_agent.experimental.langgraph_session import LangGraphWebSession

        common = {
            "cwd": "/tmp",
            "agent_def": AgentDef("test", tools=list(tools)),
            "ontology_store": OntologyStore(),
            "tool_executors": dict(executors or {}),
        }
        common.update(kwargs)
        return WebSession(**common), LangGraphWebSession(**common)

    def assert_event_types_match(self, legacy: list[dict], graph: list[dict]) -> None:
        self.assertEqual(
            [event["type"] for event in graph],
            [event["type"] for event in legacy],
        )

    def test_tool_timeout_recovery_terminal_matches_legacy(self) -> None:
        def executor(_params, _cwd):
            time.sleep(0.2)
            return "value\nlate"

        tool = {"id": "tu-timeout", "name": TOOL_NAME, "input": {"sql": "select sleep"}}
        turns = (_multi_tool_turn([tool]),)
        with patch(
            "bi_agent.web.session.stream_message",
            side_effect=_provider_turns(*turns),
        ):
            legacy, graph = self._pair(
                [TOOL_NAME], {TOOL_NAME: executor}, tool_timeouts={TOOL_NAME: 0.02},
            )
            legacy_events = list(legacy.generate_turn("执行慢查询"))
        with patch(
            "bi_agent.web.session.stream_message",
            side_effect=_provider_turns(*turns),
        ):
            graph_events = list(graph.generate_turn("执行慢查询"))

        self.assert_event_types_match(legacy_events, graph_events)
        self.assertEqual(graph.recovery.status(), "FAILED_RETRYABLE")
        self.assertEqual(legacy.recovery.status(), "FAILED_RETRYABLE")
        self.assertFalse(any(event["type"] == "done" for event in graph_events))
        self.assertEqual(graph.messages, legacy.messages)

    def test_explicit_retry_replays_the_tool_and_finishes_on_the_graph(self) -> None:
        attempts = {"count": 0}

        def executor(_params, _cwd):
            attempts["count"] += 1
            if attempts["count"] == 1:
                time.sleep(0.2)
            return "value\n1"

        tool = {"id": "tu-retry", "name": TOOL_NAME, "input": {"sql": "select 1"}}
        turns = (_multi_tool_turn([tool]), _text_turn("重试后完成"))
        with patch(
            "bi_agent.web.session.stream_message",
            side_effect=_provider_turns(*turns),
        ):
            graph = self._pair(
                [TOOL_NAME], {TOOL_NAME: executor}, tool_timeouts={TOOL_NAME: 0.02},
            )[1]
            first = list(graph.generate_turn("查询数据"))
            self.assertEqual(graph.recovery.status(), "FAILED_RETRYABLE")
            second = list(graph.retry_from_checkpoint())

        self.assertTrue(any(event["type"] == "recovery_state" for event in first))
        self.assertEqual(attempts["count"], 2)
        self.assertEqual(second[-1]["type"], "done")
        self.assertEqual(graph.recovery.status(), "SUCCEEDED")
        tool_results = [event for event in second if event["type"] == "tool_result"]
        self.assertEqual(tool_results[0]["attempt"], 2)
        self.assertEqual(tool_results[0]["execution_status"], "SUCCEEDED")

    def test_ask_user_sibling_results_precede_the_choice_and_match_legacy(self) -> None:
        def executor(_params, _cwd):
            return "value\n1"

        turns = (
            _multi_tool_turn([
                {"id": "sibling-1", "name": TOOL_NAME, "input": {"sql": "select 1"}},
                {
                    "id": "ask-1",
                    "name": "AskUser",
                    "input": {
                        "question": "请选择口径",
                        "options": [{"id": "a", "label": "口径 A"}],
                    },
                },
            ]),
            _text_turn("按口径 A 完成"),
        )
        with patch(
            "bi_agent.web.session.stream_message",
            side_effect=_provider_turns(*turns),
        ):
            legacy, graph = self._pair(
                [TOOL_NAME, "AskUser"], {TOOL_NAME: executor},
            )
            legacy_first = list(legacy.generate_turn("请分析"))
            legacy_second = list(legacy.continue_with_choice(["a"], ["口径 A"]))
        with patch(
            "bi_agent.web.session.stream_message",
            side_effect=_provider_turns(*turns),
        ):
            graph_first = list(graph.generate_turn("请分析"))
            graph_second = list(graph.continue_with_choice(["a"], ["口径 A"]))

        self.assert_event_types_match(legacy_first, graph_first)
        self.assert_event_types_match(legacy_second, graph_second)
        self.assertEqual(graph.messages, legacy.messages)
        resumed_user = next(
            message for message in reversed(graph.messages)
            if message.get("role") == "user" and isinstance(message.get("content"), list)
        )
        self.assertEqual(
            [block["tool_use_id"] for block in resumed_user["content"]],
            ["sibling-1", "ask-1"],
        )

    def test_second_claim_rejection_uses_the_same_blocked_fallback_as_legacy(self) -> None:
        from bi_agent.reliability import Claim, ClaimLevel, ValidationStatus

        turns = (
            _text_turn("结论：金额是 999999 元。"),
            _text_turn("结论：金额仍是 888888 元。"),
        )
        reject = SimpleNamespace(
            status=ValidationStatus.REJECT,
            issues=("unsupported_number",),
            findings=(),
        )
        with patch(
            "bi_agent.web.session.stream_message",
            side_effect=_provider_turns(*turns),
        ), patch("bi_agent.web.session.validate_claims", return_value=reject):
            legacy, graph = self._pair([])
            legacy.claims = [Claim("c-1", "金额是 50 元", ClaimLevel.FACT)]
            graph.claims = [Claim("c-1", "金额是 50 元", ClaimLevel.FACT)]
            legacy_events = list(legacy._run_loop())
            graph_events = list(graph._run_loop())

        self.assert_event_types_match(legacy_events, graph_events)
        self.assertTrue(any(event["type"] == "answer_blocked" for event in graph_events))
        self.assertEqual(graph_events[-1]["stop_reason"], "answer_blocked")
        visible = "".join(
            event.get("text", "") for event in graph_events
            if event["type"] == "text_delta"
        )
        self.assertNotIn("999999", visible)
        self.assertNotIn("888888", visible)

    def test_forecast_capability_limitation_matches_legacy(self) -> None:
        from bi_agent.tools.analysis_policy import FORECAST_KIND_PREDICTIVE

        turns = (_text_turn("预计下季度收入增长。"),)
        with patch(
            "bi_agent.web.session.stream_message",
            side_effect=_provider_turns(*turns),
        ):
            legacy, graph = self._pair([])
            for session in (legacy, graph):
                session._turn_wants_forecast = True
                session._turn_forecast_kind = FORECAST_KIND_PREDICTIVE
                session._cognitive_policy_decision = {"mode": "CAPABILITY_LIMITATION"}
            legacy_events = list(legacy._run_loop())
            graph_events = list(graph._run_loop())

        self.assert_event_types_match(legacy_events, graph_events)
        self.assertTrue(any(e["type"] == "forecast_limitation" for e in graph_events))
        self.assertIn(
            "当前系统不具备统计预测能力",
            "".join(e.get("text", "") for e in graph_events if e["type"] == "text_delta"),
        )

    def test_forecast_missing_disclosure_parity(self) -> None:
        from bi_agent.tools.analysis_policy import FORECAST_KIND_PREDICTIVE

        turns = (_text_turn("明年收入会明显增长。"),)
        with patch(
            "bi_agent.web.session.stream_message",
            side_effect=_provider_turns(*turns),
        ):
            legacy, graph = self._pair([])
            for session in (legacy, graph):
                session._turn_wants_forecast = True
                session._turn_forecast_kind = FORECAST_KIND_PREDICTIVE
                session._cognitive_policy_decision = {"mode": "GENERAL_RESPONSE"}
            legacy_events = list(legacy._run_loop())
            graph_events = list(graph._run_loop())

        self.assert_event_types_match(legacy_events, graph_events)
        self.assertTrue(
            any(e["type"] == "forecast_disclosure_missing" for e in graph_events)
        )

    def test_max_iteration_fallback_matches_legacy(self) -> None:
        state = {"index": 0}

        def provider(*_args, **_kwargs):
            index = state["index"]
            state["index"] += 1
            return iter(_tool_turn(
                tool_id=f"tool-{index}",
                params={"sql": f"select {index}"},
            ))

        def executor(params, _cwd):
            return f"value\n{params.get('sql')}"

        with patch("bi_agent.web.session.stream_message", side_effect=provider):
            legacy, graph = self._pair(
                [TOOL_NAME], {TOOL_NAME: executor}, max_iterations=2,
            )
            legacy_events = list(legacy.generate_turn("一直查询"))
        state["index"] = 0
        with patch("bi_agent.web.session.stream_message", side_effect=provider):
            graph_events = list(graph.generate_turn("一直查询"))

        self.assert_event_types_match(legacy_events, graph_events)
        self.assertEqual(graph_events[-1]["type"], "done")
        self.assertEqual(graph_events[-1]["stop_reason"], legacy_events[-1]["stop_reason"])
        self.assertIn(
            "没有形成可交付的数据结论",
            "".join(e.get("text", "") for e in graph_events if e["type"] == "text_delta"),
        )
