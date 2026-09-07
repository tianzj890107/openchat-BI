"""RED tests for the lightweight analysis recovery state machine.

All providers, tools and history stores are local fakes in temporary memory or
directories. No real user history, LLM, Doris or ontology service is touched.
"""

from __future__ import annotations

import tempfile
import threading
import unittest
from unittest.mock import patch

from bi_agent.concurrency import SessionSlot
from bi_agent.ontology.store import OntologyStore
from bi_agent.web.conversations import ConversationStore
from bi_agent.web.session import TurnContext, WebSession
from open_claude.agent_def import AgentDef


TOOL = "Ontology-FactQuery"


def scripted_provider(responses):
    items = iter(responses)

    def provider(*_args, **_kwargs):
        return iter(next(items))

    return provider


def final_response(text="分析完成"):
    return [
        {"type": "text_delta", "text": text},
        {"type": "message_end", "stop_reason": "end_turn", "usage": {}},
    ]


def tool_response(tool_id="query-1", params=None):
    return [
        {"type": "tool_use_start", "id": tool_id, "name": TOOL},
        {
            "type": "tool_use_end",
            "id": tool_id,
            "name": TOOL,
            "input": dict(params or {"sql": "select 1"}),
        },
        {"type": "message_end", "stop_reason": "tool_use", "usage": {}},
    ]


def ask_response(tool_id="ask-1"):
    return [
        {"type": "tool_use_start", "id": tool_id, "name": "AskUser"},
        {
            "type": "tool_use_end",
            "id": tool_id,
            "name": "AskUser",
            "input": {
                "question": "请选择统计口径",
                "options": [
                    {"id": "paid", "label": "已付款"},
                    {"id": "all", "label": "全部订单"},
                ],
            },
        },
        {"type": "message_end", "stop_reason": "tool_use", "usage": {}},
    ]


class AnalysisRecoveryRedTests(unittest.TestCase):
    def _session(self, executor=None, **kwargs):
        executors = {TOOL: executor} if executor is not None else {}
        return WebSession(
            "/tmp",
            AgentDef("test", tools=[TOOL, "AskUser"]),
            OntologyStore(),
            tool_executors=executors,
            **kwargs,
        )

    def _state(self, session):
        self.assertTrue(
            hasattr(session, "recovery_state"),
            "RED: WebSession 尚未提供轻量 recovery_state",
        )
        return session.recovery_state

    def test_new_session_is_planned_and_snapshot_is_defensive(self):
        session = self._session()
        state = self._state(session)
        self.assertEqual(state["recovery_version"], 1)
        self.assertEqual(state["status"], "PLANNED")
        self.assertIsNone(state["last_checkpoint"])
        state["status"] = "CORRUPTED"
        self.assertEqual(self._state(session)["status"], "PLANNED")

    def test_plain_turn_emits_running_then_succeeds_at_deliver_checkpoint(self):
        session = self._session()
        with patch(
            "bi_agent.web.session.stream_message",
            side_effect=scripted_provider([final_response()]),
        ):
            events = list(session.generate_turn("汇总本月情况"))

        recovery_events = [e for e in events if e.get("type") == "recovery_state"]
        self.assertIn("RUNNING", [e.get("status") for e in recovery_events])
        self.assertEqual(recovery_events[-1]["status"], "SUCCEEDED")
        state = self._state(session)
        self.assertEqual(state["status"], "SUCCEEDED")
        self.assertEqual(state["current_step"], "DELIVER")
        self.assertEqual(state["last_checkpoint"]["step"], "DELIVER")

    def test_ask_user_waits_and_choice_resumes_same_recovery_turn(self):
        session = self._session()
        with patch(
            "bi_agent.web.session.stream_message",
            side_effect=scripted_provider([ask_response()]),
        ):
            events = list(session.generate_turn("查询订单"))
        self.assertIn("awaiting_user_choice", [e.get("type") for e in events])
        waiting = self._state(session)
        self.assertEqual(waiting["status"], "WAITING_USER")
        self.assertEqual(waiting["current_step"], "WAIT_USER")
        self.assertEqual(waiting["pending_user"]["tool_use_id"], "ask-1")
        turn_ref = waiting["turn_ref"]

        with patch(
            "bi_agent.web.session.stream_message",
            side_effect=scripted_provider([final_response("已按已付款口径分析")]),
        ):
            resumed = list(session.continue_with_choice(["paid"], ["已付款"]))
        self.assertIn("SUCCEEDED", [e.get("status") for e in resumed if e.get("type") == "recovery_state"])
        final = self._state(session)
        self.assertEqual(final["turn_ref"], turn_ref)
        self.assertEqual(final["status"], "SUCCEEDED")
        self.assertIsNone(final["pending_user"])

    def test_timeout_stops_turn_as_failed_retryable_without_second_llm_call(self):
        entered = threading.Event()
        release = threading.Event()
        provider_calls = 0

        def executor(_params, _cwd):
            entered.set()
            release.wait(2)
            return "late"

        responses = iter([tool_response(), final_response("不应继续")])

        def provider(*_args, **_kwargs):
            nonlocal provider_calls
            provider_calls += 1
            return iter(next(responses))

        session = self._session(executor, tool_timeouts={TOOL: 0.05})
        try:
            with patch("bi_agent.web.session.stream_message", side_effect=provider):
                events = list(session.generate_turn("慢查询"))
        finally:
            release.set()
        self.assertTrue(entered.is_set())
        self.assertEqual(provider_calls, 1, "RED: 可重试工具失败后仍继续请求 LLM")
        state = self._state(session)
        self.assertEqual(state["status"], "FAILED_RETRYABLE")
        self.assertEqual(state["current_step"], "QUERY")
        self.assertEqual(state["error_code"], "TOOL_TIMEOUT")
        self.assertTrue(state["retryable"])
        self.assertTrue(state["last_checkpoint"]["execution_id"])
        self.assertFalse(any(e.get("type") == "done" for e in events))

    def test_non_retryable_tool_error_becomes_failed_final(self):
        def executor(_params, _cwd):
            raise ValueError("invalid query")

        session = self._session(executor)
        with patch(
            "bi_agent.web.session.stream_message",
            side_effect=scripted_provider([tool_response(), final_response("不应继续")]),
        ):
            list(session.generate_turn("错误查询"))
        state = self._state(session)
        self.assertEqual(state["status"], "FAILED_FINAL")
        self.assertEqual(state["error_code"], "TOOL_EXECUTION_ERROR")
        self.assertFalse(state["retryable"])

    def test_explicit_retry_only_from_retryable_checkpoint_increments_attempt(self):
        session = self._session(lambda _params, _cwd: "ok")
        self.assertTrue(
            hasattr(session, "retry_from_checkpoint"),
            "RED: WebSession 尚未提供显式 checkpoint retry 接口",
        )
        rejected = list(session.retry_from_checkpoint())
        self.assertEqual(rejected[0]["error_code"], "RECOVERY_NOT_RETRYABLE")

    def test_explicit_retry_resumes_failed_step_without_replaying_prior_success(self):
        release = threading.Event()
        calls = 0

        def first_executor(_params, _cwd):
            nonlocal calls
            calls += 1
            release.wait(2)
            return "late"

        session = self._session(first_executor, tool_timeouts={TOOL: 0.05})
        try:
            with patch(
                "bi_agent.web.session.stream_message",
                # The second response keeps the pre-Recovery implementation
                # deterministic (it currently continues after timeout). A
                # conforming implementation stops before consuming it.
                side_effect=scripted_provider([tool_response(), final_response("不应继续")]),
            ):
                list(session.generate_turn("需要重试的查询"))
        finally:
            release.set()
        failed = self._state(session)
        self.assertEqual(failed["status"], "FAILED_RETRYABLE")
        turn_ref = failed["turn_ref"]

        def retry_executor(_params, _cwd):
            nonlocal calls
            calls += 1
            return "value\n1"

        session._tool_executors[TOOL] = retry_executor
        with patch(
            "bi_agent.web.session.stream_message",
            side_effect=scripted_provider([final_response("重试成功")]),
        ):
            events = list(session.retry_from_checkpoint())

        state = self._state(session)
        self.assertEqual(calls, 2)
        self.assertEqual(state["turn_ref"], turn_ref)
        self.assertEqual(state["status"], "SUCCEEDED")
        self.assertEqual(state["attempt"], 2)
        self.assertTrue(any(e.get("type") == "done" for e in events))

    def test_superseded_running_turn_finishes_cancelled_and_cannot_be_overwritten(self):
        entered = threading.Event()
        release = threading.Event()
        events = []

        def executor(_params, _cwd):
            entered.set()
            release.wait(2)
            return "late-old-result"

        session = self._session(executor)
        slot = SessionSlot()
        cancel = threading.Event()
        lease = slot.try_acquire(cancel_event=cancel)
        self.assertIsNotNone(lease)
        session._turn_ctx = TurnContext(slot, lease, cancel)

        def run():
            with patch(
                "bi_agent.web.session.stream_message",
                side_effect=scripted_provider([tool_response()]),
            ):
                events.extend(session.generate_turn("将被取消的查询"))

        worker = threading.Thread(target=run, daemon=True)
        worker.start()
        self.assertTrue(entered.wait(1))
        slot.bump_generation(cancel_active=True)
        release.set()
        worker.join(2)
        self.assertFalse(worker.is_alive())
        state = self._state(session)
        self.assertEqual(state["status"], "CANCELLED")
        self.assertIn(state["error_code"], {"TOOL_CANCELLED", "STALE_TOOL_RESULT"})
        self.assertEqual(session.query_results, [])
        self.assertFalse(any(e.get("type") == "done" for e in events))

    def test_conversation_store_round_trips_recovery_state_and_old_record_is_compatible(self):
        recovery = {
            "recovery_version": 1,
            "turn_ref": "turn-waiting",
            "status": "WAITING_USER",
            "current_step": "WAIT_USER",
            "attempt": 1,
            "retryable": False,
            "error_code": "",
            "last_checkpoint": None,
            "pending_user": {"tool_use_id": "ask-1", "question": "请选择", "options": []},
            "updated_at": "2026-09-07T00:00:00+00:00",
        }
        with tempfile.TemporaryDirectory() as tmp:
            store = ConversationStore(tmp)
            try:
                saved = store.save(
                    mode="data",
                    title="恢复测试",
                    messages=[],
                    recovery_state=recovery,
                )
            except TypeError as exc:
                self.fail(f"RED: ConversationStore.save 尚不接受 recovery_state: {exc}")
            record = store.get(saved["id"])
            self.assertEqual(record["recovery_state"]["status"], "WAITING_USER")

            # A legacy snapshot without the optional field must normalize to a
            # safe PLANNED state through the public recovery normalizer.
            self.assertTrue(
                hasattr(WebSession, "normalize_recovery_state"),
                "RED: 缺少旧快照 recovery 兼容入口",
            )
            legacy = WebSession.normalize_recovery_state(None)
            self.assertEqual(legacy["status"], "PLANNED")
            interrupted = WebSession.normalize_recovery_state({
                **recovery,
                "status": "RUNNING",
                "current_step": "QUERY",
            })
            self.assertEqual(interrupted["status"], "FAILED_RETRYABLE")
            self.assertEqual(interrupted["error_code"], "INTERRUPTED_DURING_EXECUTION")

    def test_restored_retryable_state_rehydrates_tool_input_before_transitioning(self):
        """A persisted FAILED_RETRYABLE state must still be truly retryable
        after process/session restoration, not merely retain the enum value."""
        calls = 0

        def executor(params, _cwd):
            nonlocal calls
            calls += 1
            self.assertEqual(params["sql"], "select restored_retry")
            return "value\n1"

        session = self._session(executor)
        session.messages = [{
            "role": "assistant",
            "content": [{
                "type": "tool_use",
                "id": "restored-tool-1",
                "name": TOOL,
                "input": {"sql": "select restored_retry"},
            }],
        }]
        persisted = {
            "recovery_version": 1,
            "turn_ref": "restored-turn",
            "status": "FAILED_RETRYABLE",
            "current_step": "QUERY",
            "attempt": 1,
            "retryable": True,
            "error_code": "TOOL_TIMEOUT",
            "last_checkpoint": {
                "checkpoint_id": "cp-restored",
                "turn_ref": "restored-turn",
                "step": "QUERY",
                "tool_use_id": "restored-tool-1",
                "input_digest": "digest",
                "execution_id": "execution-old",
                "attempt": 1,
                "result_ref": "",
                "retryable": True,
                "created_at": "2026-09-07T00:00:00+00:00",
            },
            "pending_user": None,
            "updated_at": "2026-09-07T00:00:00+00:00",
        }
        self.assertTrue(
            hasattr(session, "restore_recovery_state"),
            "RED: restore 只恢复枚举，尚无重建 retry 输入的领域入口",
        )
        restored = session.restore_recovery_state(persisted)
        self.assertEqual(restored["status"], "FAILED_RETRYABLE")

        with patch(
            "bi_agent.web.session.stream_message",
            side_effect=scripted_provider([final_response("恢复后重试成功")]),
        ):
            events = list(session.retry_from_checkpoint())
        self.assertEqual(calls, 1)
        self.assertEqual(self._state(session)["status"], "SUCCEEDED")
        self.assertEqual(self._state(session)["attempt"], 2)
        self.assertTrue(any(e.get("type") == "done" for e in events))

    def test_unrecoverable_retry_snapshot_fails_final_without_stuck_running(self):
        session = self._session(lambda _params, _cwd: "must-not-run")
        persisted = {
            "recovery_version": 1,
            "turn_ref": "missing-input-turn",
            "status": "FAILED_RETRYABLE",
            "current_step": "QUERY",
            "attempt": 1,
            "retryable": True,
            "error_code": "TOOL_TIMEOUT",
            "last_checkpoint": {
                "checkpoint_id": "cp-missing",
                "turn_ref": "missing-input-turn",
                "step": "QUERY",
                "tool_use_id": "not-in-this-conversation",
                "input_digest": "digest",
                "execution_id": "execution-old",
                "attempt": 1,
                "result_ref": "",
                "retryable": True,
                "created_at": "2026-09-07T00:00:00+00:00",
            },
            "pending_user": None,
            "updated_at": "2026-09-07T00:00:00+00:00",
        }
        self.assertTrue(hasattr(session, "restore_recovery_state"))
        state = session.restore_recovery_state(persisted)
        self.assertEqual(state["status"], "FAILED_FINAL")
        self.assertEqual(state["error_code"], "RECOVERY_INPUT_MISSING")
        events = list(session.retry_from_checkpoint())
        self.assertEqual(events[0]["error_code"], "RECOVERY_NOT_RETRYABLE")
        self.assertNotEqual(self._state(session)["status"], "RUNNING")


if __name__ == "__main__":
    unittest.main()
