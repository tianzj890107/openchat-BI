"""Phase-1 concurrency governance tests for ChatBI.

Every test is offline: the LLM provider is faked (or its unbounded body is
stubbed), the ontology is an empty store, and history lives in a fresh
TemporaryDirectory.  No real LLM / Doris / ontology service is contacted and
no real conversation data is read or modified.
"""

from __future__ import annotations

import json
import os
import tempfile
import threading
import time
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from fastapi.testclient import TestClient

from bi_agent.concurrency import (
    AdmissionController,
    SessionSlotRegistry,
    get_limits,
    reset_limits,
    reset_resources,
)
from bi_agent.ontology.store import OntologyStore
from bi_agent.web import app as web_app_module
from bi_agent.web.app import (
    STATE,
    app,
    _ensure_session,
    _session_key,
    _slot_key,
)
from bi_agent.web.session import WebSession
from open_claude.agent_def import AgentDef, get_agent_def_registry


def text_script(text: str = "普通答复", gate: threading.Event | None = None):
    def gen():
        yield {"type": "text_delta", "text": text}
        if gate is not None:
            gate.wait(5)
        yield {"type": "message_end", "stop_reason": "end_turn", "usage": {"input_tokens": 3, "output_tokens": 2}}
    return gen


def ask_user_script():
    def gen():
        yield {"type": "tool_use_start", "id": "call_ask", "name": "AskUser"}
        yield {
            "type": "tool_use_end",
            "id": "call_ask",
            "name": "AskUser",
            "input": {
                "question": "请选择口径",
                "options": [{"id": "a", "label": "口径A"}, {"id": "b", "label": "口径B"}],
            },
        }
        yield {"type": "message_end", "stop_reason": "tool_use", "usage": {}}
    return gen


class FakeProvider:
    """Scripted ``stream_message``.  Call i uses ``scripts[i]`` (last repeats)."""

    def __init__(self, scripts):
        self.scripts = list(scripts)
        self.lock = threading.Lock()
        self.calls = 0

    def __call__(self, messages, system_prompt, allowed_tools=None, **kwargs):
        with self.lock:
            idx = self.calls
            self.calls += 1
        script = self.scripts[min(idx, len(self.scripts) - 1)]
        return iter(script())


class ConcurrencyTestBase(unittest.TestCase):
    def setUp(self) -> None:
        reset_limits()
        reset_resources()
        self.tmp = tempfile.mkdtemp()
        reg = get_agent_def_registry()
        reg._defs["bi-analyst"] = AgentDef("bi-analyst", tools=[])
        with patch("bi_agent.web.app.OntologyStore.from_xlsx", return_value=OntologyStore()):
            web_app_module.configure(self.tmp, self.tmp, self.tmp, agent_name="bi-analyst")
        self.client = TestClient(app)

    def tearDown(self) -> None:
        for key in list(os.environ):
            if key.startswith("CHATBI_"):
                os.environ.pop(key, None)
        reset_limits()
        reset_resources()
        # Detach any slots/tickets created by this test so the next test starts
        # from a clean registry (threads from failed tests release into the
        # OLD controller/slot objects, never these).
        STATE.admission = AdmissionController(get_limits())
        STATE.session_slots = SessionSlotRegistry()

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------
    def set_limits(self, **kwargs) -> None:
        for key, value in kwargs.items():
            os.environ[key] = str(value)
        reset_limits()
        reset_resources()
        STATE.admission = AdmissionController(get_limits())

    def wait_busy(self, mode: str, sid: str, timeout: float = 5.0) -> bool:
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            slot = STATE.session_slots.get(_slot_key(mode, sid))
            if slot is not None and slot.busy:
                return True
            time.sleep(0.01)
        return False

    def post_chat(self, sid: str, message: str = "你好", url: str = "/api/chat"):
        """Non-blocking chat; returns parsed SSE events from a completed body."""
        with patch("bi_agent.web.session.stream_message", side_effect=FakeProvider([text_script()])):
            resp = self.client.post(url, json={"message": message, "session_id": sid})
        self.assertEqual(resp.status_code, 200)
        events = [
            json.loads(line[5:].strip())
            for line in resp.text.splitlines()
            if line.startswith("data:")
        ]
        return events

    def stream_chat(self, sid: str, provider, message: str = "你好", url: str = "/api/chat"):
        """Run one SSE chat in a background thread.  Returns (thread, events, errors).

        The provider patch is started on the main thread and stopped in
        cleanup.  Patching from inside each worker thread would nest
        ``unittest.mock.patch`` contexts whose lifetimes overlap across
        threads; the first exiting thread would restore the real provider
        while the other turn is still running (visible as a spurious
        "No DashScope API key" error).  Holding the patch in the test thread
        for the whole test keeps every concurrent stream on the mock.

        A fresh TestClient is created inside the thread so concurrent streams
        never share a portal."""
        events: list[dict] = []
        errors: list[BaseException] = []
        mp = patch("bi_agent.web.session.stream_message", side_effect=provider)
        mp.start()
        self.addCleanup(mp.stop)

        def run():
            client = TestClient(app)
            try:
                with client.stream("POST", url, json={"message": message, "session_id": sid}) as resp:
                    for line in resp.iter_lines():
                        if line.startswith("data:"):
                            events.append(json.loads(line[5:].strip()))
            except BaseException as exc:  # pragma: no cover - failure surface
                errors.append(exc)

        thread = threading.Thread(target=run)
        thread.start()
        return thread, events, errors

    def join_threads(self, threads, timeout: float = 10.0) -> None:
        for thread in threads:
            thread.join(timeout=timeout)
            self.assertFalse(thread.is_alive(), f"thread {thread.name} did not finish")


# ---------------------------------------------------------------------------
# Session registry / turn guard
# ---------------------------------------------------------------------------
class SessionRegistryTests(ConcurrencyTestBase):
    def test_ensure_session_concurrent_creation_returns_single_instance(self) -> None:
        results: dict[int, WebSession] = {}
        barrier = threading.Barrier(2)

        def work() -> None:
            barrier.wait()
            results[threading.get_ident()] = _ensure_session("dup-key")

        threads = [threading.Thread(target=work) for _ in range(2)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        first, second = results.values()
        self.assertIs(first, second)
        self.assertIs(STATE.sessions["dup-key"], first)

    def test_same_session_second_chat_returns_409(self) -> None:
        gate = threading.Event()
        self.addCleanup(gate.set)
        provider = FakeProvider([text_script(gate=gate)])
        thread, events, errors = self.stream_chat("s409", provider)
        self.assertTrue(self.wait_busy("data", "s409"))
        resp = self.client.post("/api/chat", json={"message": "再问", "session_id": "s409"})
        self.assertEqual(resp.status_code, 409)
        body = resp.json()
        self.assertEqual(body["code"], "SESSION_BUSY")
        self.assertEqual(body["error"]["code"], "SESSION_BUSY")
        self.assertEqual(body["session_id"], "s409")
        self.assertTrue(body["retryable"])
        gate.set()
        self.join_threads([thread])
        self.assertFalse(errors)
        self.assertIn("done", [e["type"] for e in events])
        session = STATE.sessions["s409"]
        visible_users = [m for m in session.messages if m["role"] == "user" and not m.get("internal")]
        self.assertEqual(len(visible_users), 1)

    def test_different_sessions_run_in_parallel(self) -> None:
        provider = FakeProvider([text_script()])
        t1, e1, err1 = self.stream_chat("par-a", provider)
        t2, e2, err2 = self.stream_chat("par-b", provider)
        self.join_threads([t1, t2])
        self.assertFalse(err1)
        self.assertFalse(err2)
        self.assertIn("done", [e["type"] for e in e1])
        self.assertIn("done", [e["type"] for e in e2])
        self.assertNotEqual(e1[0].get("turn_id"), e2[0].get("turn_id"))
        for evt in e1 + e2:
            self.assertTrue(evt.get("turn_id"))

    def test_chat_choice_overlap_rejected(self) -> None:
        session = _ensure_session("s-choice")
        session.pending_tool_use_id = "call_ask"
        session.pending_choice_spec = {"question": "q", "options": []}
        gate = threading.Event()
        self.addCleanup(gate.set)
        provider = FakeProvider([text_script(gate=gate)])
        thread, events, errors = self.stream_chat("s-choice", provider)
        self.assertTrue(self.wait_busy("data", "s-choice"))
        resp = self.client.post(
            "/api/choice",
            json={"choice_ids": ["a"], "choice_labels": ["A"], "session_id": "s-choice"},
        )
        self.assertEqual(resp.status_code, 409)
        self.assertEqual(resp.json()["code"], "SESSION_BUSY")
        gate.set()
        self.join_threads([thread])
        self.assertFalse(errors)

    def test_empty_session_id_legacy_path_still_guarded(self) -> None:
        gate = threading.Event()
        self.addCleanup(gate.set)
        provider = FakeProvider([text_script(gate=gate)])
        thread, events, errors = self.stream_chat("", provider)
        self.assertTrue(self.wait_busy("data", ""))
        resp = self.client.post("/api/chat", json={"message": "再问", "session_id": ""})
        self.assertEqual(resp.status_code, 409)
        self.assertEqual(resp.json()["code"], "SESSION_BUSY")
        gate.set()
        self.join_threads([thread])
        self.assertFalse(errors)


# ---------------------------------------------------------------------------
# Generation / cancellation / supersession
# ---------------------------------------------------------------------------
class SupersessionTests(ConcurrencyTestBase):
    def test_reset_during_chat_bumps_generation_and_supersedes(self) -> None:
        _ensure_session("s-reset")
        old_session = STATE.sessions["s-reset"]
        gate = threading.Event()
        self.addCleanup(gate.set)
        provider = FakeProvider([text_script(gate=gate)])
        thread, events, errors = self.stream_chat("s-reset", provider)
        self.assertTrue(self.wait_busy("data", "s-reset"))
        slot = STATE.session_slots.get(_slot_key("data", "s-reset"))
        generation_before = slot.generation
        resp = self.client.post("/api/session/reset", params={"session_id": "s-reset"})
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(slot.generation, generation_before + 1)
        self.assertNotIn("s-reset", STATE.sessions)
        gate.set()
        self.join_threads([thread])
        self.assertFalse(errors)
        types = [e["type"] for e in events]
        self.assertIn("session_superseded", types)
        self.assertNotIn("done", types)
        # The old (now detached) session never received the assistant answer.
        assistant = [m for m in old_session.messages if m["role"] == "assistant"]
        self.assertEqual(assistant, [])

    def test_restore_during_chat_cannot_pollute_restored_history(self) -> None:
        store = STATE.conversation_store
        record = store.save(
            mode="data",
            title="历史会话",
            messages=[{"role": "user", "content": "被恢复的问题"}],
            chat_html="<p>history</p>",
            dashboard_html="",
        )
        _ensure_session("s-restore")
        gate = threading.Event()
        self.addCleanup(gate.set)
        provider = FakeProvider([text_script(gate=gate)])
        thread, events, errors = self.stream_chat("s-restore", provider)
        self.assertTrue(self.wait_busy("data", "s-restore"))
        resp = self.client.post(
            f"/api/conversations/{record['id']}/activate",
            params={"session_id": "s-restore"},
        )
        self.assertEqual(resp.status_code, 200)
        gate.set()
        self.join_threads([thread])
        self.assertFalse(errors)
        types = [e["type"] for e in events]
        self.assertIn("session_superseded", types)
        restored = STATE.sessions["s-restore"]
        visible = [m for m in restored.messages if not m.get("internal")]
        self.assertEqual(visible, [{"role": "user", "content": "被恢复的问题"}])

    def test_old_turn_id_events_are_stamped_and_isolated(self) -> None:
        gate = threading.Event()
        self.addCleanup(gate.set)
        provider = FakeProvider([text_script(gate=gate)])
        t1, e1, err1 = self.stream_chat("iso-a", provider)
        self.assertTrue(self.wait_busy("data", "iso-a"))
        resp = self.client.post("/api/session/reset", params={"session_id": "iso-a"})
        self.assertEqual(resp.status_code, 200)
        gate.set()
        self.join_threads([t1])
        self.assertFalse(err1)
        t2, e2, err2 = self.stream_chat("iso-a", FakeProvider([text_script(text="第二版")]))
        self.join_threads([t2])
        self.assertFalse(err2)
        turn_ids_1 = {e.get("turn_id") for e in e1 if e.get("turn_id")}
        turn_ids_2 = {e.get("turn_id") for e in e2 if e.get("turn_id")}
        self.assertTrue(turn_ids_1.isdisjoint(turn_ids_2))
        done2 = [e for e in e2 if e["type"] == "done"][0]
        self.assertIn("generation", done2)


# ---------------------------------------------------------------------------
# Turn lease / ownership (reset must let a new turn start immediately)
# ---------------------------------------------------------------------------
class TurnLeaseTests(ConcurrencyTestBase):
    def test_stale_lease_cannot_release_new_turn(self) -> None:
        slot = STATE.session_slots.ensure(_slot_key("data", "lease"))
        lease1 = slot.try_acquire()
        self.assertIsNotNone(lease1)
        # Supersede: generation bumps AND the slot frees immediately.
        gen2 = slot.bump_generation()
        self.assertGreater(gen2, lease1.generation)
        self.assertFalse(slot.busy)
        # The new turn acquires right away, even though lease1 never released.
        lease2 = slot.try_acquire()
        self.assertIsNotNone(lease2)
        self.assertNotEqual(lease1.owner, lease2.owner)
        # The old turn's finally must not release the new turn.
        slot.release_turn(lease1)
        self.assertTrue(slot.busy)
        self.assertEqual(slot.owner, lease2.owner)
        self.assertTrue(slot.is_superseded(lease1, None))
        self.assertFalse(slot.is_superseded(lease2, None))
        slot.release_turn(lease2)
        self.assertFalse(slot.busy)

    def test_reset_new_turn_starts_while_old_llm_still_running(self) -> None:
        gate1 = threading.Event()
        gate2 = threading.Event()
        self.addCleanup(gate1.set)
        self.addCleanup(gate2.set)
        provider1 = FakeProvider([text_script(gate=gate1)])
        t1, e1, err1 = self.stream_chat("reset-live", provider1)
        self.assertTrue(self.wait_busy("data", "reset-live"))
        old_session = STATE.sessions["reset-live"]
        resp = self.client.post("/api/session/reset", params={"session_id": "reset-live"})
        self.assertEqual(resp.status_code, 200)
        # The old LLM call is STILL in flight (gate1 held) — a new turn must
        # start immediately without 409 SESSION_BUSY.
        provider2 = FakeProvider([text_script(text="第二版", gate=gate2)])
        t2, e2, err2 = self.stream_chat("reset-live", provider2, message="再问")
        self.assertTrue(self.wait_busy("data", "reset-live"))
        slot = STATE.session_slots.get(_slot_key("data", "reset-live"))
        self.assertIsNotNone(slot)
        # Let the OLD turn finish first: its finally must not release the new
        # turn's busy/lease state.
        gate1.set()
        self.join_threads([t1])
        self.assertFalse(err1)
        self.assertTrue(slot.busy)
        new_session = STATE.sessions["reset-live"]
        self.assertIsNot(new_session, old_session)
        visible = [m for m in new_session.messages if not m.get("internal")]
        self.assertEqual(len([m for m in visible if m["role"] == "assistant"]), 0)
        old_assistant = [m for m in old_session.messages if m["role"] == "assistant"]
        self.assertEqual(old_assistant, [])
        # The old turn emitted session_superseded, never done.
        old_types = [e["type"] for e in e1]
        self.assertIn("session_superseded", old_types)
        self.assertNotIn("done", old_types)
        # The new turn completes normally and frees the slot.
        gate2.set()
        self.join_threads([t2])
        self.assertFalse(err2)
        self.assertIn("done", [e["type"] for e in e2])
        self.assertFalse(slot.busy)

    def test_restore_new_turn_starts_while_old_turn_in_flight(self) -> None:
        store = STATE.conversation_store
        record = store.save(
            mode="data",
            title="历史会话2",
            messages=[{"role": "user", "content": "被恢复的问题2"}],
            chat_html="<p>history2</p>",
            dashboard_html="",
        )
        _ensure_session("restore-live")
        gate1 = threading.Event()
        gate2 = threading.Event()
        self.addCleanup(gate1.set)
        self.addCleanup(gate2.set)
        provider1 = FakeProvider([text_script(gate=gate1)])
        t1, e1, err1 = self.stream_chat("restore-live", provider1)
        self.assertTrue(self.wait_busy("data", "restore-live"))
        resp = self.client.post(
            f"/api/conversations/{record['id']}/activate",
            params={"session_id": "restore-live"},
        )
        self.assertEqual(resp.status_code, 200)
        # Old LLM call still gated — a new turn on the restored session must
        # not 409.
        provider2 = FakeProvider([text_script(text="恢复后回答", gate=gate2)])
        t2, e2, err2 = self.stream_chat("restore-live", provider2, message="继续")
        self.assertTrue(self.wait_busy("data", "restore-live"))
        slot = STATE.session_slots.get(_slot_key("data", "restore-live"))
        gate1.set()
        self.join_threads([t1])
        self.assertFalse(err1)
        self.assertTrue(slot.busy)
        restored = STATE.sessions["restore-live"]
        # The restored history is intact and the new turn's user message
        # appears once it starts; the OLD turn must never add anything
        # (no stale user message, no assistant answer).
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline and not any(
            m.get("role") == "user" and m.get("content") == "继续"
            for m in restored.messages
        ):
            time.sleep(0.01)
        visible = [m for m in restored.messages if not m.get("internal")]
        self.assertEqual(visible, [
            {"role": "user", "content": "被恢复的问题2"},
            {"role": "user", "content": "继续"},
        ])
        self.assertFalse(
            any(m["role"] == "assistant" for m in restored.messages),
            "old turn must not commit into the restored session",
        )
        gate2.set()
        self.join_threads([t2])
        self.assertFalse(err2)
        self.assertIn("done", [e["type"] for e in e2])
        self.assertFalse(slot.busy)

    def test_interleaved_finally_old_turn_cannot_clear_new_turn(self) -> None:
        # Slot-level simulation of the finally-order race: the new turn
        # finishes and releases FIRST, then the stale old turn's finally runs
        # — the slot must stay free and the next turn must acquire cleanly.
        slot = STATE.session_slots.ensure(_slot_key("data", "interleave"))
        lease_old = slot.try_acquire()
        self.assertIsNotNone(lease_old)
        slot.bump_generation()
        lease_new = slot.try_acquire()
        self.assertIsNotNone(lease_new)
        slot.release_turn(lease_new)  # new turn finishes first
        self.assertFalse(slot.busy)
        slot.release_turn(lease_old)  # old finally runs afterwards
        self.assertFalse(slot.busy)   # must not resurrect busy
        lease_again = slot.try_acquire()
        self.assertIsNotNone(lease_again)
        self.assertNotEqual(lease_again.owner, lease_old.owner)
        slot.release_turn(lease_again)


# ---------------------------------------------------------------------------
# Cancellation / error release
# ---------------------------------------------------------------------------
class ReleaseTests(ConcurrencyTestBase):
    def test_client_disconnect_releases_slot_admission_and_llm_slot(self) -> None:
        import asyncio

        from bi_agent.concurrency import RequestPrincipal, get_llm_limiter
        from bi_agent.web.app import _run_turn_stream

        llm_budget = get_limits().llm_concurrency

        def paused_unbounded(messages, system_prompt, allowed_tools, model_key, max_tokens, temperature, thinking=False):
            # Suspend at a yield (never block inside a call) so GeneratorExit
            # from a client disconnect can be delivered mid-flight.
            yield {"type": "text_delta", "text": "x"}
            while True:
                yield {"type": "thinking_delta", "text": ""}

        session = _ensure_session("s-disc")
        slot = STATE.session_slots.ensure(_slot_key("data", "s-disc"))
        lease = slot.try_acquire()
        self.assertIsNotNone(lease)
        ticket = STATE.admission.acquire(RequestPrincipal(session_id="s-disc"))
        self.assertEqual(STATE.admission.snapshot()["active"], 1)

        with patch("bi_agent.llm.provider._stream_message_unbounded", side_effect=paused_unbounded):
            resp = _run_turn_stream(
                session, session.generate_turn("hi"), slot, lease, "t-disc", ticket
            )
            cancel_evt = slot.cancel
            self.assertIsNotNone(cancel_evt)

            async def disconnect_mid_flight():
                seen: list[str] = []
                async for chunk in resp.body_iterator:
                    line = chunk.split("\n", 1)[0]
                    if line.startswith("data:"):
                        evt = json.loads(line[5:].strip())
                        seen.append(evt["type"])
                        if evt["type"] == "text_delta":
                            break
                self.assertIn("text_delta", seen)
                # The LLM budget slot is held while the response is in flight.
                self.assertLess(get_llm_limiter().available, llm_budget)
                # Client disconnect: closing the response generator raises
                # GeneratorExit, which must cancel the turn and release the
                # slot, the admission ticket and the LLM token.
                await resp.body_iterator.aclose()
                self.assertTrue(cancel_evt.is_set())
                self.assertFalse(slot.busy)
                self.assertEqual(STATE.admission.snapshot()["active"], 0)
                self.assertEqual(get_llm_limiter().available, llm_budget)
                return seen

            seen = asyncio.run(disconnect_mid_flight())

        self.assertIn("text_delta", seen)
        session = STATE.sessions["s-disc"]
        self.assertFalse(any(m["role"] == "assistant" for m in session.messages))

    def test_provider_error_releases_all_slots(self) -> None:
        def error_script():
            def gen():
                yield {"type": "error", "error": "boom"}
            return gen

        with patch("bi_agent.web.session.stream_message", side_effect=FakeProvider([error_script()])):
            resp = self.client.post("/api/chat", json={"message": "hi", "session_id": "s-err"})
        events = [
            json.loads(line[5:].strip())
            for line in resp.text.splitlines()
            if line.startswith("data:")
        ]
        self.assertIn("error", [e["type"] for e in events])
        self.assertNotIn("done", [e["type"] for e in events])
        slot = STATE.session_slots.get(_slot_key("data", "s-err"))
        self.assertFalse(slot.busy)
        self.assertEqual(STATE.admission.snapshot()["active"], 0)
        session = STATE.sessions["s-err"]
        self.assertFalse(any(m["role"] == "assistant" for m in session.messages))

# ---------------------------------------------------------------------------
# Admission controller (409 / 429 contract)
# ---------------------------------------------------------------------------
class AdmissionTests(ConcurrencyTestBase):
    def test_global_queue_full_returns_429(self) -> None:
        self.set_limits(
            CHATBI_MAX_ACTIVE_TURNS=1,
            CHATBI_MAX_WAITING_TURNS=1,
            CHATBI_ADMISSION_WAIT_SECONDS=2,
            CHATBI_MAX_ACTIVE_PER_PRINCIPAL=1,
        )
        gate = threading.Event()
        self.addCleanup(gate.set)
        provider = FakeProvider([text_script(gate=gate)])
        t1, e1, err1 = self.stream_chat("q1", provider)
        self.assertTrue(self.wait_busy("data", "q1"))
        t2, e2, err2 = self.stream_chat("q2", provider)
        deadline = time.monotonic() + 3
        while time.monotonic() < deadline and STATE.admission.snapshot()["waiting"] < 1:
            time.sleep(0.01)
        self.assertEqual(STATE.admission.snapshot()["waiting"], 1)
        resp = self.client.post("/api/chat", json={"message": "挤不进", "session_id": "q3"})
        self.assertEqual(resp.status_code, 429)
        body = resp.json()
        self.assertEqual(body["code"], "GLOBAL_QUEUE_FULL")
        self.assertEqual(body["error"]["code"], "GLOBAL_QUEUE_FULL")
        self.assertEqual(resp.headers.get("Retry-After"), "2")
        gate.set()
        self.join_threads([t1, t2])
        self.assertFalse(err1)
        self.assertFalse(err2)
        self.assertIn("done", [e["type"] for e in e2])

    def test_admission_wait_timeout_returns_429(self) -> None:
        self.set_limits(
            CHATBI_MAX_ACTIVE_TURNS=1,
            CHATBI_MAX_WAITING_TURNS=5,
            CHATBI_ADMISSION_WAIT_SECONDS=0.2,
        )
        gate = threading.Event()
        self.addCleanup(gate.set)
        provider = FakeProvider([text_script(gate=gate)])
        t1, e1, err1 = self.stream_chat("t1", provider)
        self.assertTrue(self.wait_busy("data", "t1"))
        resp = self.client.post("/api/chat", json={"message": "等超时", "session_id": "t2"})
        self.assertEqual(resp.status_code, 429)
        body = resp.json()
        self.assertEqual(body["code"], "ADMISSION_TIMEOUT")
        self.assertEqual(resp.headers.get("Retry-After"), "1")
        gate.set()
        self.join_threads([t1])
        self.assertFalse(err1)

    def test_principal_concurrency_limit_returns_429(self) -> None:
        self.set_limits(
            CHATBI_MAX_ACTIVE_TURNS=8,
            CHATBI_MAX_ACTIVE_PER_PRINCIPAL=1,
        )
        gate = threading.Event()
        self.addCleanup(gate.set)
        provider = FakeProvider([text_script(gate=gate)])
        t1, e1, err1 = self.stream_chat("one", provider)
        self.assertTrue(self.wait_busy("data", "one"))
        # Same session_id, report mode → different slot, same quota key.
        STATE.report_sessions["one"] = _ensure_session("one")
        resp = self.client.post("/api/report/chat", json={"message": "报表", "session_id": "one"})
        self.assertEqual(resp.status_code, 429)
        body = resp.json()
        self.assertEqual(body["code"], "PRINCIPAL_CONCURRENCY_LIMIT")
        gate.set()
        self.join_threads([t1])
        self.assertFalse(err1)

    def test_different_principals_are_not_blocked(self) -> None:
        gate = threading.Event()
        self.addCleanup(gate.set)
        provider = FakeProvider([text_script(gate=gate)])
        t1, e1, err1 = self.stream_chat("fair-a", provider)
        self.assertTrue(self.wait_busy("data", "fair-a"))
        resp = self.client.post("/api/chat", json={"message": "再来", "session_id": "fair-a"})
        self.assertEqual(resp.status_code, 409)
        events_b = self.post_chat("fair-b", message="独立会话")
        self.assertIn("done", [e["type"] for e in events_b])
        gate.set()
        self.join_threads([t1])
        self.assertFalse(err1)

    def test_admission_fifo_order(self) -> None:
        from bi_agent.concurrency import RequestPrincipal

        self.set_limits(
            CHATBI_MAX_ACTIVE_TURNS=1,
            CHATBI_MAX_WAITING_TURNS=10,
            CHATBI_ADMISSION_WAIT_SECONDS=3,
        )
        controller = STATE.admission
        holder = controller.acquire(RequestPrincipal(session_id="fifo-a"))
        order: list[str] = []
        lock = threading.Lock()

        def waiter(name: str) -> None:
            ticket = controller.acquire(RequestPrincipal(session_id=name))
            with lock:
                order.append(name)
            time.sleep(0.15)  # hold the slot so the next waiter really queues
            controller.release(ticket)

        tb = threading.Thread(target=waiter, args=("fifo-b",))
        tb.start()
        time.sleep(0.05)
        tc = threading.Thread(target=waiter, args=("fifo-c",))
        tc.start()
        time.sleep(0.05)
        td = threading.Thread(target=waiter, args=("fifo-d",))
        td.start()
        deadline = time.monotonic() + 3
        while time.monotonic() < deadline and controller.snapshot()["waiting"] < 3:
            time.sleep(0.01)
        self.assertEqual(controller.snapshot()["waiting"], 3)
        # Free the slot: B (first in queue) must run before C before D; a
        # newcomer could never jump the queue.
        controller.release(holder)
        tb.join(5)
        tc.join(5)
        td.join(5)
        self.assertEqual(order, ["fifo-b", "fifo-c", "fifo-d"])
        self.assertEqual(controller.snapshot()["active"], 0)

    def test_head_blocked_by_principal_cap_does_not_block_others(self) -> None:
        from bi_agent.concurrency import RequestPrincipal

        self.set_limits(
            CHATBI_MAX_ACTIVE_TURNS=3,
            CHATBI_MAX_ACTIVE_PER_PRINCIPAL=2,
            CHATBI_MAX_WAITING_TURNS=10,
            CHATBI_ADMISSION_WAIT_SECONDS=3,
        )
        controller = STATE.admission
        # x occupies both of its per-principal slots; y takes the 3rd slot.
        x1 = controller.acquire(RequestPrincipal(session_id="cap-x"))
        x2 = controller.acquire(RequestPrincipal(session_id="cap-x"))
        y1 = controller.acquire(RequestPrincipal(session_id="cap-y"))
        results: dict[str, str] = {}

        def waiter(name: str) -> None:
            try:
                ticket = controller.acquire(RequestPrincipal(session_id=name))
                results[name] = "granted"
                controller.release(ticket)
            except Exception as exc:  # pragma: no cover - failure surface
                results[name] = f"err:{exc}"

        tx3 = threading.Thread(target=waiter, args=("cap-x",))
        tx3.start()
        tz = threading.Thread(target=waiter, args=("cap-z",))
        tz.start()
        deadline = time.monotonic() + 3
        while time.monotonic() < deadline and controller.snapshot()["waiting"] < 2:
            time.sleep(0.01)
        self.assertEqual(controller.snapshot()["waiting"], 2)
        # y frees a global slot, but the queue head (cap-x) is still at its
        # per-principal cap — the runnable z behind it must still get in.
        controller.release(y1)
        deadline = time.monotonic() + 3
        while time.monotonic() < deadline and "cap-z" not in results:
            time.sleep(0.01)
        self.assertEqual(results.get("cap-z"), "granted")
        self.assertNotIn("cap-x", results)
        # One of x's active slots frees → the blocked head finally runs.
        controller.release(x1)
        tx3.join(5)
        tz.join(5)
        self.assertEqual(results.get("cap-x"), "granted")
        controller.release(x2)
        self.assertEqual(controller.snapshot()["active"], 0)

    def test_admission_cancel_removes_queue_ticket(self) -> None:
        from bi_agent.concurrency import AdmissionRejected, RequestPrincipal

        self.set_limits(
            CHATBI_MAX_ACTIVE_TURNS=1,
            CHATBI_MAX_WAITING_TURNS=5,
            CHATBI_ADMISSION_WAIT_SECONDS=5,
        )
        controller = STATE.admission
        holder = controller.acquire(RequestPrincipal(session_id="cancel-a"))
        cancel = threading.Event()
        result: dict[str, str] = {}

        def waiter() -> None:
            try:
                ticket = controller.acquire(RequestPrincipal(session_id="cancel-b"), cancel_event=cancel)
                result["b"] = "granted"
                controller.release(ticket)
            except AdmissionRejected as exc:
                result["b"] = exc.code

        t = threading.Thread(target=waiter)
        t.start()
        deadline = time.monotonic() + 3
        while time.monotonic() < deadline and controller.snapshot()["waiting"] < 1:
            time.sleep(0.01)
        self.assertEqual(controller.snapshot()["waiting"], 1)
        cancel.set()
        t.join(3)
        self.assertFalse(t.is_alive(), "cancelled waiter must leave the queue")
        self.assertEqual(result["b"], "ADMISSION_CANCELLED")
        self.assertEqual(controller.snapshot()["waiting"], 0)
        controller.release(holder)
        self.assertEqual(controller.snapshot()["active"], 0)

    def test_reset_cancels_turn_waiting_in_admission(self) -> None:
        """A queued turn (holding its session lease, still waiting for a
        global active slot) is cancelled promptly by a reset — the cancel
        event bound at ``try_acquire`` is the SAME event the admission wait
        polls, so there is no unattached window."""
        from bi_agent.concurrency import RequestPrincipal

        self.set_limits(
            CHATBI_MAX_ACTIVE_TURNS=1,
            CHATBI_MAX_WAITING_TURNS=5,
            CHATBI_ADMISSION_WAIT_SECONDS=5,
        )
        # A occupies the only global active slot (direct ticket).
        holder = STATE.admission.acquire(RequestPrincipal(session_id="adm-a"))
        provider = FakeProvider([text_script()])
        mp = patch("bi_agent.web.session.stream_message", side_effect=provider)
        mp.start()
        self.addCleanup(mp.stop)

        result: dict[str, object] = {}

        def post_b() -> None:
            resp = self.client.post("/api/chat", json={"message": "hi", "session_id": "adm-b"})
            result["status"] = resp.status_code
            body = resp.json()
            result["code"] = body.get("code")

        t_b = threading.Thread(target=post_b)
        t_b.start()
        deadline = time.monotonic() + 3
        while time.monotonic() < deadline and STATE.admission.snapshot()["waiting"] < 1:
            time.sleep(0.01)
        self.assertEqual(STATE.admission.snapshot()["waiting"], 1)
        slot_b = STATE.session_slots.get(_slot_key("data", "adm-b"))
        self.assertIsNotNone(slot_b)
        self.assertTrue(slot_b.busy, "B must hold the session lease while queued")

        started = time.monotonic()
        resp = self.client.post("/api/session/reset", params={"session_id": "adm-b"})
        self.assertEqual(resp.status_code, 200)
        t_b.join(2)
        elapsed = time.monotonic() - started
        self.assertFalse(t_b.is_alive(), "queued turn must leave admission promptly")
        self.assertLess(elapsed, 0.8, f"queued turn took {elapsed:.2f}s to cancel")
        self.assertEqual(STATE.admission.snapshot()["waiting"], 0)
        self.assertEqual(STATE.admission.snapshot()["active"], 1,
                         "A still holds active; B must never obtain it")
        self.assertEqual(provider.calls, 0, "B must never reach the LLM provider")
        self.assertFalse(slot_b.busy, "superseded lease must not keep the slot busy")
        self.assertEqual(result["code"], "ADMISSION_CANCELLED")
        self.assertEqual(result["status"], 429)

        STATE.admission.release(holder)
        self.assertEqual(STATE.admission.snapshot()["active"], 0)

    def test_restore_cancels_turn_waiting_in_admission(self) -> None:
        """Restore/activate (which funnels through ``_supersede_session``)
        cancels a turn still queued in admission, with no slot/admission
        leak."""
        from bi_agent.concurrency import RequestPrincipal

        self.set_limits(
            CHATBI_MAX_ACTIVE_TURNS=1,
            CHATBI_MAX_WAITING_TURNS=5,
            CHATBI_ADMISSION_WAIT_SECONDS=5,
        )
        holder = STATE.admission.acquire(RequestPrincipal(session_id="adm-a2"))
        provider = FakeProvider([text_script()])
        mp = patch("bi_agent.web.session.stream_message", side_effect=provider)
        mp.start()
        self.addCleanup(mp.stop)

        result: dict[str, object] = {}

        def post_b() -> None:
            resp = self.client.post("/api/chat", json={"message": "hi", "session_id": "adm-b2"})
            result["status"] = resp.status_code
            body = resp.json()
            result["code"] = body.get("code")

        t_b = threading.Thread(target=post_b)
        t_b.start()
        deadline = time.monotonic() + 3
        while time.monotonic() < deadline and STATE.admission.snapshot()["waiting"] < 1:
            time.sleep(0.01)
        self.assertEqual(STATE.admission.snapshot()["waiting"], 1)

        record = STATE.conversation_store.save(
            mode="data",
            title="历史会话",
            messages=[{"role": "user", "content": "被恢复的问题"}],
            chat_html="<p>history</p>",
            dashboard_html="",
        )
        resp = self.client.post(
            f"/api/conversations/{record['id']}/activate",
            params={"session_id": "adm-b2"},
        )
        self.assertEqual(resp.status_code, 200)
        t_b.join(2)
        self.assertFalse(t_b.is_alive(), "queued turn must leave admission after restore")
        self.assertEqual(STATE.admission.snapshot()["waiting"], 0)
        self.assertEqual(STATE.admission.snapshot()["active"], 1)
        self.assertEqual(provider.calls, 0)
        slot_b = STATE.session_slots.get(_slot_key("data", "adm-b2"))
        self.assertFalse(slot_b.busy)
        self.assertEqual(result["code"], "ADMISSION_CANCELLED")
        self.assertEqual(result["status"], 429)

        STATE.admission.release(holder)
        self.assertEqual(STATE.admission.snapshot()["active"], 0)

    def test_admission_grant_and_reset_race_releases_ticket(self) -> None:
        """Drive the real ``_begin_turn`` so an admission grant and a
        reset race.  Whichever branch wins, the stale request must never
        stick: admission ticket and slot lease are released, active/waiting
        recover, and a fresh turn starts immediately."""
        from fastapi import HTTPException

        from bi_agent.concurrency import RequestPrincipal
        from bi_agent.web.app import _begin_turn

        self.set_limits(
            CHATBI_MAX_ACTIVE_TURNS=1,
            CHATBI_MAX_WAITING_TURNS=5,
            CHATBI_ADMISSION_WAIT_SECONDS=5,
        )
        outcomes: dict[str, int] = {}
        for i in range(20):
            holder = STATE.admission.acquire(RequestPrincipal(session_id=f"race-holder-{i}"))
            result: dict[str, object] = {}

            def begin() -> None:
                try:
                    slot, lease, _turn_id, ticket, cancel = _begin_turn(
                        "data", f"race-turn-{i}",
                    )
                    # If the grant legitimately beat the reset, the turn must
                    # still release cleanly and never be reused.
                    result["outcome"] = "granted"
                    if slot.is_superseded(lease, cancel):
                        slot.release_turn(lease)
                        STATE.admission.release(ticket)
                        result["outcome"] = "TURN_SUPERSEDED"
                except HTTPException as exc:
                    detail = exc.detail if isinstance(exc.detail, dict) else {}
                    result["outcome"] = detail.get("code")
                    result["status"] = exc.status_code

            t = threading.Thread(target=begin)
            t.start()
            deadline = time.monotonic() + 3
            while time.monotonic() < deadline and STATE.admission.snapshot()["waiting"] < 1:
                time.sleep(0.01)
            self.assertEqual(STATE.admission.snapshot()["waiting"], 1)
            slot = STATE.session_slots.get(_slot_key("data", f"race-turn-{i}"))
            self.assertIsNotNone(slot)

            if i % 2 == 0:
                # Free global capacity first: the grant races the reset.
                STATE.admission.release(holder)
                slot.bump_generation()
            else:
                # Reset first: cancellation deterministically wins.
                slot.bump_generation()
                STATE.admission.release(holder)

            t.join(2)
            self.assertFalse(t.is_alive(), f"race iteration {i} must terminate")
            outcome = str(result.get("outcome") or "")
            self.assertIn(outcome, ("TURN_SUPERSEDED", "ADMISSION_CANCELLED", "granted"),
                          f"unexpected outcome {outcome!r} at iteration {i}")
            if outcome in ("TURN_SUPERSEDED", "ADMISSION_CANCELLED"):
                self.assertIn(result.get("status"), (409, 429))
            self.assertEqual(STATE.admission.snapshot()["active"], 0,
                             f"active must recover at iteration {i}")
            self.assertEqual(STATE.admission.snapshot()["waiting"], 0,
                             f"waiting must recover at iteration {i}")
            self.assertFalse(slot.busy, f"slot must be free at iteration {i}")
            outcomes[outcome] = outcomes.get(outcome, 0) + 1

            # A new turn can start immediately after the race.
            slot2, lease2, _tid2, ticket2, _cancel2 = _begin_turn("data", f"race-turn-{i}")
            slot2.release_turn(lease2)
            STATE.admission.release(ticket2)

        self.assertGreaterEqual(
            outcomes.get("TURN_SUPERSEDED", 0) + outcomes.get("ADMISSION_CANCELLED", 0),
            20,
            "every race iteration must terminate via a rejected/superseded path",
        )


# ---------------------------------------------------------------------------
# Downstream concurrency caps
# ---------------------------------------------------------------------------
class ResourceLimiterTests(ConcurrencyTestBase):
    def _slow_unbounded_factory(self, counter: dict, lock: threading.Lock, gate: threading.Event):
        def slow_unbounded(messages, system_prompt, allowed_tools, model_key, max_tokens, temperature, thinking=False):
            with lock:
                counter["current"] += 1
                counter["max"] = max(counter["max"], counter["current"])
            try:
                yield {"type": "text_delta", "text": "x"}
                gate.wait(10)
                yield {"type": "message_end", "stop_reason": "end_turn", "usage": {}}
            finally:
                with lock:
                    counter["current"] -= 1
        return slow_unbounded

    def test_llm_concurrency_never_exceeds_env_cap(self) -> None:
        self.set_limits(CHATBI_LLM_CONCURRENCY=1, CHATBI_MAX_ACTIVE_TURNS=8)
        counter = {"current": 0, "max": 0}
        lock = threading.Lock()
        gate = threading.Event()
        self.addCleanup(gate.set)
        slow = self._slow_unbounded_factory(counter, lock, gate)
        with patch("bi_agent.llm.provider._stream_message_unbounded", side_effect=slow):
            # Uses the REAL provider wrapper (LLM limiter) with a stubbed body.
            t1, e1, err1 = self.stream_chat_real("llm-a")
            t2, e2, err2 = self.stream_chat_real("llm-b")
            time.sleep(0.6)
            self.assertEqual(counter["max"], 1)
            gate.set()
            self.join_threads([t1, t2])
        self.assertFalse(err1)
        self.assertFalse(err2)
        self.assertIn("done", [e["type"] for e in e1])
        self.assertIn("done", [e["type"] for e in e2])

    def test_reset_while_waiting_on_llm_semaphore_cancels_promptly(self) -> None:
        from bi_agent.concurrency import get_llm_limiter

        self.set_limits(CHATBI_LLM_CONCURRENCY=1, CHATBI_MAX_ACTIVE_TURNS=8)
        gate = threading.Event()
        self.addCleanup(gate.set)
        counter = {"current": 0}
        lock = threading.Lock()

        def slow_unbounded(messages, system_prompt, allowed_tools, model_key, max_tokens, temperature, thinking=False):
            with lock:
                counter["current"] += 1
            try:
                yield {"type": "text_delta", "text": "a"}
                gate.wait(10)
                yield {"type": "message_end", "stop_reason": "end_turn", "usage": {}}
            finally:
                with lock:
                    counter["current"] -= 1

        with patch("bi_agent.llm.provider._stream_message_unbounded", side_effect=slow_unbounded):
            # Turn A holds the only LLM slot.
            t_a, e_a, err_a = self.stream_chat_real("sem-a")
            deadline = time.monotonic() + 5
            while time.monotonic() < deadline and counter["current"] < 1:
                time.sleep(0.01)
            self.assertEqual(counter["current"], 1)
            # Turn B starts and blocks inside the LLM limiter wait.
            t_b, e_b, err_b = self.stream_chat_real("sem-b")
            deadline = time.monotonic() + 3
            while time.monotonic() < deadline and STATE.admission.snapshot()["active"] < 2:
                time.sleep(0.01)
            self.assertEqual(STATE.admission.snapshot()["active"], 2)
            # Reset B: the waiting turn must cancel promptly instead of
            # blocking the worker for the full limiter timeout.
            started = time.monotonic()
            resp = self.client.post("/api/session/reset", params={"session_id": "sem-b"})
            self.assertEqual(resp.status_code, 200)
            t_b.join(3)
            elapsed = time.monotonic() - started
            self.assertLess(elapsed, 2.0, "waiting turn must cancel promptly")
            self.assertFalse(t_b.is_alive())
            self.assertFalse(err_b)
            b_types = [e["type"] for e in e_b]
            self.assertIn("session_superseded", b_types)
            self.assertNotIn("done", b_types)
            # B's slot and admission ticket are released; the LLM token was
            # never acquired by B (A still holds the single slot).
            slot_b = STATE.session_slots.get(_slot_key("data", "sem-b"))
            self.assertFalse(slot_b.busy)
            self.assertEqual(STATE.admission.snapshot()["active"], 1)
            self.assertEqual(get_llm_limiter().available, get_limits().llm_concurrency - 1)
            gate.set()
            self.join_threads([t_a])
            self.assertFalse(err_a)
            self.assertEqual(get_llm_limiter().available, get_limits().llm_concurrency)

    def stream_chat_real(self, sid: str):
        """Stream chat without patching session.stream_message (real limiter)."""
        events: list[dict] = []
        errors: list[BaseException] = []

        def run():
            client = TestClient(app)
            try:
                with client.stream("POST", "/api/chat", json={"message": "hi", "session_id": sid}) as resp:
                    for line in resp.iter_lines():
                        if line.startswith("data:"):
                            events.append(json.loads(line[5:].strip()))
            except BaseException as exc:  # pragma: no cover
                errors.append(exc)

        thread = threading.Thread(target=run)
        thread.start()
        return thread, events, errors

    def test_doris_limiter_serializes_database_tools(self) -> None:
        from bi_agent.concurrency import get_doris_limiter
        from bi_agent.tools import _limited_executor

        self.set_limits(CHATBI_DORIS_CONCURRENCY=1)
        gate = threading.Event()
        self.addCleanup(gate.set)
        counter = {"current": 0, "max": 0}
        lock = threading.Lock()

        def slow_sql(params, cwd):
            with lock:
                counter["current"] += 1
                counter["max"] = max(counter["max"], counter["current"])
            try:
                gate.wait(5)
            finally:
                with lock:
                    counter["current"] -= 1
            return "ok"

        wrapped = _limited_executor(slow_sql, get_doris_limiter())
        results = []

        def call():
            results.append(wrapped({}, self.tmp))

        threads = [threading.Thread(target=call) for _ in range(2)]
        for t in threads:
            t.start()
        time.sleep(0.5)
        self.assertEqual(counter["max"], 1)
        gate.set()
        for t in threads:
            t.join(5)
        self.assertEqual(results, ["ok", "ok"])
        self.assertEqual(counter["current"], 0)

    def test_ontology_limiter_serializes_remote_tools(self) -> None:
        from bi_agent.concurrency import get_ontology_limiter
        from bi_agent.tools import _limited_executor

        self.set_limits(CHATBI_ONTOLOGY_CONCURRENCY=1)
        gate = threading.Event()
        self.addCleanup(gate.set)
        counter = {"current": 0, "max": 0}
        lock = threading.Lock()

        def slow_remote(params, cwd):
            with lock:
                counter["current"] += 1
                counter["max"] = max(counter["max"], counter["current"])
            try:
                gate.wait(5)
            finally:
                with lock:
                    counter["current"] -= 1
            return "ok"

        wrapped = _limited_executor(slow_remote, get_ontology_limiter())
        results = []

        def call():
            results.append(wrapped({}, self.tmp))

        threads = [threading.Thread(target=call) for _ in range(2)]
        for t in threads:
            t.start()
        time.sleep(0.5)
        self.assertEqual(counter["max"], 1)
        gate.set()
        for t in threads:
            t.join(5)
        self.assertEqual(results, ["ok", "ok"])
        self.assertEqual(counter["current"], 0)

    def test_llm_semaphore_wait_cancelled_promptly(self) -> None:
        from bi_agent.concurrency import ResourceCancelled, get_llm_limiter

        self.set_limits(CHATBI_LLM_CONCURRENCY=1)
        limiter = get_llm_limiter()
        held = limiter.acquire()
        cancel = threading.Event()
        timer = threading.Timer(0.3, cancel.set)
        timer.start()
        started = time.monotonic()
        try:
            with self.assertRaises(ResourceCancelled):
                limiter.acquire(timeout=5, cancel_event=cancel)
            elapsed = time.monotonic() - started
            self.assertLess(elapsed, 2.0, "cancel must be observed promptly")
        finally:
            timer.join()
        held.release()
        self.assertEqual(limiter.available, 1)

    def test_doris_semaphore_wait_cancelled_token_not_leaked(self) -> None:
        from bi_agent.concurrency import (
            ResourceCancelled,
            clear_current_cancel,
            get_doris_limiter,
            set_current_cancel,
        )
        from bi_agent.tools import _limited_executor

        self.set_limits(CHATBI_DORIS_CONCURRENCY=1)
        limiter = get_doris_limiter()
        held = limiter.acquire()
        cancel = threading.Event()
        wrapped = _limited_executor(lambda params, cwd: "ok", limiter)
        set_current_cancel(cancel)
        timer = threading.Timer(0.3, cancel.set)
        timer.start()
        try:
            with self.assertRaises(ResourceCancelled):
                wrapped({}, self.tmp)
        finally:
            timer.join()
            clear_current_cancel()
        # The cancelled wait never acquired a token and capacity is intact.
        self.assertEqual(limiter.available, 0)
        held.release()
        self.assertEqual(limiter.available, 1)

    def test_resource_wait_timeout_recovers_capacity(self) -> None:
        from bi_agent.concurrency import ResourceTimeout, get_doris_limiter

        self.set_limits(CHATBI_DORIS_CONCURRENCY=1)
        limiter = get_doris_limiter()
        held = limiter.acquire()
        started = time.monotonic()
        with self.assertRaises(ResourceTimeout):
            limiter.acquire(timeout=0.3)
        self.assertGreaterEqual(time.monotonic() - started, 0.25)
        self.assertEqual(limiter.available, 0)
        held.release()
        self.assertEqual(limiter.available, 1)
        # Capacity is usable again after the timeout.
        token = limiter.acquire(timeout=0.5)
        token.release()
        self.assertEqual(limiter.available, 1)

    def test_resource_cancel_after_semaphore_grant_releases_capacity(self) -> None:
        """When the cancel event fires in the instant AFTER the semaphore is
        granted but BEFORE ``acquire`` returns, the slot is handed back
        immediately: the caller raises ``ResourceCancelled``, the
        provider/executor never runs, and capacity is fully restored."""
        from bi_agent.concurrency import ResourceCancelled, ResourceLimiter

        limiter = ResourceLimiter(1, "grant-race-limiter")
        cancel = threading.Event()
        original_acquire = limiter._sem.acquire

        def acquire_then_cancel(timeout=None):
            got = original_acquire(timeout)
            if got:
                cancel.set()
            return got

        limiter._sem.acquire = acquire_then_cancel
        executed = {"calls": 0}

        def provider():
            executed["calls"] += 1
            yield {"type": "text_delta", "text": "x"}
            yield {"type": "message_end", "stop_reason": "end_turn", "usage": {}}

        with self.assertRaises(ResourceCancelled):
            limiter.acquire(cancel_event=cancel)
        self.assertEqual(executed["calls"], 0, "cancelled request must not reach provider")
        self.assertEqual(limiter.available, 1, "capacity must be fully restored")

        # The same guarantee holds through the gated executor wrapper.
        from bi_agent.tools import _limited_executor
        from bi_agent.concurrency import set_current_cancel, clear_current_cancel

        limiter2 = ResourceLimiter(1, "grant-race-limiter-2")
        cancel2 = threading.Event()
        original2 = limiter2._sem.acquire

        def acquire_then_cancel2(timeout=None):
            got = original2(timeout)
            if got:
                cancel2.set()
            return got

        limiter2._sem.acquire = acquire_then_cancel2
        executor = _limited_executor(lambda params, cwd: executed.update(calls=executed["calls"] + 1) or "ok",
                                     limiter2)
        set_current_cancel(cancel2)
        try:
            with self.assertRaises(ResourceCancelled):
                executor({}, ".")
        finally:
            clear_current_cancel()
        self.assertEqual(executed["calls"], 0, "cancelled request must not reach executor")
        self.assertEqual(limiter2.available, 1, "executor path must restore capacity")


# ---------------------------------------------------------------------------
# Session lifecycle (TTL / LRU)
# ---------------------------------------------------------------------------
class SessionLifecycleTests(ConcurrencyTestBase):
    def test_ttl_never_reaps_active_session(self) -> None:
        self.set_limits(CHATBI_SESSION_IDLE_TTL_SECONDS=1)
        gate = threading.Event()
        self.addCleanup(gate.set)
        provider = FakeProvider([text_script(gate=gate)])
        thread, events, errors = self.stream_chat("active", provider)
        self.assertTrue(self.wait_busy("data", "active"))
        from bi_agent.web.app import _reap_idle_sessions

        _reap_idle_sessions()
        self.assertIsNotNone(STATE.session_slots.get(_slot_key("data", "active")))
        self.assertIn("active", STATE.sessions)
        gate.set()
        self.join_threads([thread])
        self.assertFalse(errors)

    def test_ttl_only_drops_memory_objects_never_history_files(self) -> None:
        self.set_limits(CHATBI_SESSION_IDLE_TTL_SECONDS=1)
        from bi_agent.web.app import _reap_idle_sessions

        _ensure_session("idle-session")
        # Idle for longer than the TTL so the lazy reap actually evicts it.
        time.sleep(1.1)
        self.assertIn("idle-session", STATE.sessions)
        store = STATE.conversation_store
        record = store.save(
            mode="data",
            title="历史文件",
            messages=[{"role": "user", "content": "q"}],
            chat_html="",
            dashboard_html="",
        )
        record_path = Path(store.root) / f"{record['id']}.json"
        self.assertTrue(record_path.exists())
        _reap_idle_sessions()
        self.assertNotIn("idle-session", STATE.sessions)
        self.assertNotIn("idle-session", STATE.source_contexts)
        self.assertNotIn("idle-session", STATE.roles_by_session)
        self.assertTrue(record_path.exists(), "history JSON must never be reaped")


# ---------------------------------------------------------------------------
# Unchanged behavior
# ---------------------------------------------------------------------------
class BehaviorRegressionTests(ConcurrencyTestBase):
    def test_single_user_single_turn_unchanged(self) -> None:
        events = self.post_chat("plain", message="普通问题")
        types = [e["type"] for e in events]
        self.assertIn("user_message", types)
        self.assertIn("iteration_start", types)
        self.assertIn("text_delta", types)
        self.assertIn("llm_response", types)
        self.assertIn("done", types)
        done = [e for e in events if e["type"] == "done"][0]
        self.assertEqual(done["stop_reason"], "end_turn")
        session = STATE.sessions["plain"]
        visible = [m for m in session.messages if not m.get("internal")]
        self.assertEqual(len([m for m in visible if m["role"] == "user"]), 1)
        self.assertEqual(len([m for m in visible if m["role"] == "assistant"]), 1)

    def test_ask_user_then_choice_still_works(self) -> None:
        provider = FakeProvider([ask_user_script(), text_script(text="最终答复")])
        thread, events, errors = self.stream_chat("ask", provider)
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline and not any(e["type"] == "awaiting_user_choice" for e in events):
            time.sleep(0.01)
        self.assertTrue(any(e["type"] == "awaiting_user_choice" for e in events))
        session = STATE.sessions["ask"]
        self.assertIsNotNone(session.pending_tool_use_id)
        with patch("bi_agent.web.session.stream_message", side_effect=provider):
            resp = self.client.post(
                "/api/choice",
                json={"choice_ids": ["a"], "choice_labels": ["口径A"], "session_id": "ask"},
            )
        self.assertEqual(resp.status_code, 200)
        choice_events = [
            json.loads(line[5:].strip())
            for line in resp.text.splitlines()
            if line.startswith("data:")
        ]
        self.assertIn("done", [e["type"] for e in choice_events])
        self.assertIn("user_choice_resolved", [e["type"] for e in choice_events])
        thread.join(timeout=5)
        self.assertFalse(errors)

    def test_report_mode_chat_and_choice_work(self) -> None:
        from bi_agent.web.app import _source_for_session

        source = _source_for_session("report1")
        session = WebSession(
            cwd=self.tmp,
            agent_def=STATE.agent_def,
            ontology_store=source.ontology_store,
            tools_override=[],
            role_block="",
            tool_executors={},
        )
        STATE.report_sessions["report1"] = session
        events = self.post_chat("report1", message="报表问题", url="/api/report/chat")
        self.assertIn("done", [e["type"] for e in events])
        for evt in events:
            self.assertTrue(evt.get("turn_id"))
        # choice path on the report session
        session.pending_tool_use_id = "call_ask2"
        with patch("bi_agent.web.session.stream_message", side_effect=FakeProvider([text_script(text="报表结论")])):
            resp = self.client.post(
                "/api/report/choice",
                json={"choice_ids": ["x"], "choice_labels": ["X"], "session_id": "report1"},
            )
        self.assertEqual(resp.status_code, 200)
        body = resp.text
        self.assertIn('"done"', body)

    def test_save_rejects_superseded_generation(self) -> None:
        _ensure_session("save-gen")
        slot = STATE.session_slots.get(_slot_key("data", "save-gen"))
        resp = self.client.post("/api/conversations/save", json={
            "mode": "data",
            "session_id": "save-gen",
            "title": "旧快照",
            "generation": slot.generation,
        })
        self.assertEqual(resp.status_code, 200)
        slot.bump_generation()
        resp2 = self.client.post("/api/conversations/save", json={
            "mode": "data",
            "session_id": "save-gen",
            "title": "旧快照",
            "generation": slot.generation - 1,
        })
        self.assertEqual(resp2.status_code, 409)
        self.assertEqual(resp2.json()["code"], "TURN_SUPERSEDED")

    def test_structured_claims_dedup_still_intact(self) -> None:
        # Numeric presentation is not a claims gate: the first candidate is
        # committed directly even when it contains a number absent from Claims.
        from bi_agent.web.session import WebSession

        session = WebSession(
            cwd=self.tmp,
            agent_def=STATE.agent_def,
            ontology_store=OntologyStore(),
            tools_override=[],
            tool_executors={},
        )
        from bi_agent.reliability import Claim, ClaimLevel

        claim = Claim(
            id="c1",
            statement="订单量下降",
            level=ClaimLevel.FACT,
            semantic={"semantic_type": "FACT"},
        )
        session.claims = [claim]

        def scripted(messages, system_prompt, allowed_tools=None, **kw):
            yield {"type": "text_delta", "text": "结论：订单量下降 61.3%。"}
            yield {"type": "message_end", "stop_reason": "end_turn", "usage": {}}

        with patch("bi_agent.web.session.stream_message", side_effect=scripted):
            events = list(session._run_loop())
        texts = [e["text"] for e in events if e["type"] == "text_delta"]
        self.assertEqual(texts, ["结论：订单量下降 61.3%。"])
        event_types = [e["type"] for e in events]
        self.assertNotIn("claim_context", event_types)
        self.assertNotIn("answer_validation", event_types)
        self.assertNotIn("answer_blocked", event_types)
        self.assertIn("done", event_types)
        visible = [m for m in session.messages if not m.get("internal")]
        assistant_texts = []
        for m in visible:
            if m["role"] == "assistant":
                for block in m["content"]:
                    if block.get("type") == "text":
                        assistant_texts.append(block.get("text", ""))
        self.assertEqual(assistant_texts, ["结论：订单量下降 61.3%。"])


if __name__ == "__main__":
    unittest.main()
