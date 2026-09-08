"""RED contract tests for the analysis-agent tool execution boundary.

These tests are deliberately written against user-visible/session-observable
behaviour.  They use only fake providers and fake executors: no real LLM,
Doris, ontology service, conversation store, or user data is touched.
"""

from __future__ import annotations

import threading
import time
import unittest
from unittest.mock import patch

from bi_agent.concurrency import SessionSlot
from bi_agent.ontology.store import OntologyStore
from bi_agent.tool_runtime import ToolExecutionLedger, ToolTurnScope, _DaemonToolPool
from bi_agent.web.session import TurnContext, WebSession
from open_claude.agent_def import AgentDef


TOOL_NAME = "Ontology-FactQuery"


def _tool_turn(tool_uses: list[dict], final_text: str = "分析完成"):
    """Return a deterministic two-response provider for one tool iteration."""

    responses = [
        [
            *[
                event
                for tool in tool_uses
                for event in (
                    {"type": "tool_use_start", "id": tool["id"], "name": tool["name"]},
                    {
                        "type": "tool_use_end",
                        "id": tool["id"],
                        "name": tool["name"],
                        "input": dict(tool.get("input") or {}),
                    },
                )
            ],
            {"type": "message_end", "stop_reason": "tool_use", "usage": {}},
        ],
        [
            {"type": "text_delta", "text": final_text},
            {"type": "message_end", "stop_reason": "end_turn", "usage": {}},
        ],
    ]
    lock = threading.Lock()
    calls = 0

    def provider(*_args, **_kwargs):
        nonlocal calls
        with lock:
            index = calls
            calls += 1
        return iter(responses[min(index, len(responses) - 1)])

    return provider


class ToolExecutionBoundaryRedTests(unittest.TestCase):
    def _session(self, executor, **kwargs) -> WebSession:
        return WebSession(
            "/tmp",
            AgentDef("test", tools=[TOOL_NAME]),
            OntologyStore(),
            tool_executors={TOOL_NAME: executor},
            **kwargs,
        )

    @staticmethod
    def _record_dict(record):
        if isinstance(record, dict):
            return record
        if hasattr(record, "to_dict"):
            return record.to_dict()
        return vars(record)

    def _records(self, session: WebSession) -> list[dict]:
        self.assertTrue(
            hasattr(session, "tool_execution_records"),
            "RED: WebSession 尚未暴露只读 tool_execution_records 执行审计快照",
        )
        return [self._record_dict(item) for item in session.tool_execution_records]

    def test_success_event_and_audit_carry_execution_identity(self) -> None:
        tool = {"id": "tu-success", "name": TOOL_NAME, "input": {"sql": "select 1"}}
        session = self._session(lambda _params, _cwd: "value\n1")

        with patch("bi_agent.web.session.stream_message", side_effect=_tool_turn([tool])):
            events = list(session.generate_turn("查询数据"))

        result = next(event for event in events if event.get("type") == "tool_result")
        self.assertTrue(result.get("execution_id"))
        self.assertNotEqual(result["execution_id"], tool["id"])
        self.assertEqual(result.get("execution_status"), "SUCCEEDED")
        self.assertEqual(result.get("attempt"), 1)

        records = self._records(session)
        self.assertEqual(len(records), 1)
        record = records[0]
        self.assertEqual(record["execution_id"], result["execution_id"])
        self.assertEqual(record["status"], "SUCCEEDED")
        self.assertEqual(record["attempt"], 1)
        self.assertTrue(record["started_at"])
        self.assertTrue(record["finished_at"])
        self.assertGreaterEqual(record["duration_ms"], 0)

    def test_duplicate_logical_call_executes_underlying_tool_once(self) -> None:
        calls = 0

        def executor(_params, _cwd):
            nonlocal calls
            calls += 1
            return "value\n1"

        duplicate = {"id": "tu-duplicate", "name": TOOL_NAME, "input": {"sql": "select 1"}}
        session = self._session(executor)
        with patch(
            "bi_agent.web.session.stream_message",
            side_effect=_tool_turn([duplicate, dict(duplicate)]),
        ):
            list(session.generate_turn("查询数据"))

        self.assertEqual(calls, 1, "RED: 相同逻辑 tool_use 仍被底层执行了两次")
        records = self._records(session)
        self.assertEqual(len(records), 1)
        self.assertEqual(records[0]["attempt"], 1)

    def test_timeout_finishes_before_executor_and_late_result_is_not_committed(self) -> None:
        entered = threading.Event()
        release = threading.Event()
        finished = threading.Event()
        events: list[dict] = []

        def executor(_params, _cwd):
            entered.set()
            release.wait(2)
            return "value\nlate-success"

        # GREEN is expected to accept this test-only constructor override; it
        # is intentionally absent before implementation, making this a RED
        # contract rather than a real 60-second network wait.
        try:
            session = self._session(executor, tool_timeouts={TOOL_NAME: 0.05})
        except TypeError as exc:
            self.fail(f"RED: WebSession 尚不支持可注入的单工具超时配置: {exc}")

        tool = {"id": "tu-timeout", "name": TOOL_NAME, "input": {"sql": "select sleep"}}

        def run_turn():
            try:
                with patch("bi_agent.web.session.stream_message", side_effect=_tool_turn([tool])):
                    events.extend(session.generate_turn("执行慢查询"))
            finally:
                finished.set()

        worker = threading.Thread(target=run_turn, daemon=True)
        worker.start()
        self.assertTrue(entered.wait(1), "fake executor 没有启动")
        try:
            self.assertTrue(
                finished.wait(0.5),
                "RED: 工具边界没有在单工具 timeout 后结束等待",
            )
        finally:
            release.set()
            worker.join(2)

        records = self._records(session)
        self.assertEqual(records[0]["status"], "TIMED_OUT")
        self.assertEqual(records[0]["error_code"], "TOOL_TIMEOUT")
        self.assertTrue(records[0]["retryable"])
        self.assertEqual(session.query_results, [])
        self.assertEqual(session.claims, [])
        self.assertFalse(
            any(e.get("type") == "tool_result" and e.get("execution_status") == "SUCCEEDED" for e in events)
        )

    def test_superseded_turn_rejects_late_tool_result_before_state_commit(self) -> None:
        entered = threading.Event()
        release = threading.Event()
        events: list[dict] = []

        def executor(_params, _cwd):
            entered.set()
            release.wait(2)
            return "value\nlate-old-turn"

        session = self._session(executor)
        slot = SessionSlot()
        cancel = threading.Event()
        lease = slot.try_acquire(cancel_event=cancel)
        self.assertIsNotNone(lease)
        session._turn_ctx = TurnContext(slot, lease, cancel)
        tool = {"id": "tu-stale", "name": TOOL_NAME, "input": {"sql": "select old"}}

        def run_turn():
            with patch("bi_agent.web.session.stream_message", side_effect=_tool_turn([tool])):
                events.extend(session.generate_turn("旧轮次查询"))

        worker = threading.Thread(target=run_turn, daemon=True)
        worker.start()
        self.assertTrue(entered.wait(1), "fake executor 没有启动")
        slot.bump_generation(cancel_active=True)
        release.set()
        worker.join(2)
        self.assertFalse(worker.is_alive(), "测试线程未退出")

        self.assertEqual(session.query_results, [], "RED: stale 查询仍写入 query_results")
        self.assertEqual(session.claims, [], "RED: stale 查询仍生成 Claim")
        self.assertFalse(any(e.get("type") == "tool_result" for e in events))
        records = self._records(session)
        self.assertEqual(records[0]["status"], "CANCELLED")
        self.assertEqual(records[0]["error_code"], "STALE_TOOL_RESULT")

    def test_executor_exception_has_stable_failed_audit(self) -> None:
        def executor(_params, _cwd):
            raise RuntimeError("database password=do-not-record traceback-detail")

        tool = {
            "id": "tu-error",
            "name": TOOL_NAME,
            "input": {"sql": "select 1", "token": "secret-token"},
        }
        session = self._session(executor)
        with patch("bi_agent.web.session.stream_message", side_effect=_tool_turn([tool])):
            list(session.generate_turn("查询数据"))

        records = self._records(session)
        self.assertEqual(len(records), 1)
        record = records[0]
        self.assertEqual(record["status"], "FAILED")
        self.assertEqual(record["error_code"], "TOOL_EXECUTION_ERROR")
        self.assertNotIn("secret-token", repr(record))
        self.assertNotIn("do-not-record", repr(record))
        self.assertNotIn("Traceback", repr(record))
        self.assertEqual(session.query_results, [])

    def test_audit_is_bounded_and_returned_as_defensive_snapshot(self) -> None:
        large_result = "x" * 100_000
        tool = {
            "id": "tu-large",
            "name": TOOL_NAME,
            "input": {"sql": "select payload", "authorization": "Bearer private"},
        }
        session = self._session(lambda _params, _cwd: large_result)
        with patch("bi_agent.web.session.stream_message", side_effect=_tool_turn([tool])):
            list(session.generate_turn("查询大结果"))

        records = self._records(session)
        serialized = repr(records[0])
        self.assertLess(len(serialized), 10_000)
        self.assertNotIn("Bearer private", serialized)
        self.assertNotIn(large_result, serialized)

        records[0]["status"] = "CORRUPTED_BY_CALLER"
        fresh = self._records(session)
        self.assertEqual(fresh[0]["status"], "SUCCEEDED")

    def test_audit_bounding_does_not_truncate_successful_business_result(self) -> None:
        """Audit may retain a digest, but WebSession/LLM receives the complete result."""
        large_result = "payload:" + ("业务数据" * 260_000)
        tool = {
            "id": "tu-full-result",
            "name": TOOL_NAME,
            "input": {"sql": "select large_payload"},
        }
        session = self._session(lambda _params, _cwd: large_result)
        with patch("bi_agent.web.session.stream_message", side_effect=_tool_turn([tool])):
            events = list(session.generate_turn("查询完整大结果"))

        result = next(event for event in events if event.get("type") == "tool_result")
        self.assertEqual(
            result["output"],
            large_result,
            "RED: Tool Runtime 为限制审计大小而截断了真实业务结果",
        )
        self.assertEqual(session.query_results[0].data, large_result)
        self.assertLess(len(repr(self._records(session)[0])), 10_000)

    def test_queued_execution_that_times_out_never_starts_later(self) -> None:
        """An expired queued call must be discarded before invoking its executor."""
        pool = _DaemonToolPool(max_workers=1)
        first_entered = threading.Event()
        release_first = threading.Event()
        second_invoked = threading.Event()
        first_ledger = ToolExecutionLedger(
            "queue-test-first", tool_timeouts={"BlockingTool": 1.0}, pool=pool,
        )
        second_ledger = ToolExecutionLedger(
            "queue-test-second", tool_timeouts={"QueuedTool": 0.05}, pool=pool,
        )

        def first_invoke():
            first_entered.set()
            release_first.wait(2)
            return "first-ok"

        def run_first():
            first_ledger.execute(
                scope=ToolTurnScope("turn-first"),
                tool_use_id="first",
                tool_name="BlockingTool",
                params={},
                invoke=first_invoke,
            )

        first_thread = threading.Thread(target=run_first, daemon=True)
        first_thread.start()
        self.assertTrue(first_entered.wait(1), "占位 executor 没有启动")
        outcome = second_ledger.execute(
            scope=ToolTurnScope("turn-second"),
            tool_use_id="second",
            tool_name="QueuedTool",
            params={},
            invoke=lambda: second_invoked.set() or "late-queued-result",
        )
        self.assertEqual(outcome.status, "TIMED_OUT")

        release_first.set()
        first_thread.join(2)
        self.assertFalse(first_thread.is_alive(), "占位 executor 没有退出")
        # This sentinel sits behind the expired task. Once it runs, the worker
        # has definitely dequeued and considered that task.
        drained = threading.Event()
        pool.submit(drained.set)
        self.assertTrue(drained.wait(1), "测试线程池没有排空")
        self.assertFalse(
            second_invoked.is_set(),
            "RED: 已在队列中超时的工具仍在 worker 空闲后迟到执行",
        )

    def test_timeout_between_preflight_and_invoke_cannot_start_executor(self) -> None:
        """Deterministically cover the preflight-check/invoke TOCTOU window."""
        ledger = ToolExecutionLedger(
            "preflight-race", tool_timeouts={"RaceTool": 0.05},
        )
        preflight_passed = threading.Event()
        release_worker = threading.Event()
        executor_invoked = threading.Event()

        def pause_after_preflight(_cancel):
            # Current implementation calls set_current_cancel immediately
            # after releasing the preflight lock and immediately before
            # invoke(). Holding it here lets the caller finalize TIMED_OUT in
            # that exact window without relying on scheduler luck.
            preflight_passed.set()
            release_worker.wait(2)

        with patch("bi_agent.tool_runtime.set_current_cancel", side_effect=pause_after_preflight):
            outcome = ledger.execute(
                scope=ToolTurnScope("race-turn"),
                tool_use_id="race-call",
                tool_name="RaceTool",
                params={},
                invoke=lambda: executor_invoked.set() or "must-not-run",
            )
            self.assertTrue(preflight_passed.is_set(), "worker 未到达前置检查后的竞态点")
            self.assertEqual(outcome.status, "TIMED_OUT")
            release_worker.set()

            drained = threading.Event()
            ledger._pool.submit(drained.set)
            self.assertTrue(drained.wait(1), "测试线程池没有排空")

        self.assertFalse(
            executor_invoked.is_set(),
            "RED: timeout 在前置检查后发生，已终态任务仍然启动了 executor",
        )


if __name__ == "__main__":
    unittest.main()
