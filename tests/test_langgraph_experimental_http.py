"""RED contract tests for the opt-in LangGraph HTTP side path.

The experimental endpoints must be invisible by default, use their own session
and source registries, and leave the legacy ``/api/chat`` engine untouched.
"""

from __future__ import annotations

import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient

import bi_agent.web.app as web_app_module
from bi_agent.concurrency import reset_limits, reset_resources
from bi_agent.ontology.store import OntologyStore
from bi_agent.web.app import STATE, app
from bi_agent.web.session import WebSession
from open_claude.agent_def import AgentDef, get_agent_def_registry


def _provider_turns(*turns):
    state = {"index": 0}

    def provider(*_args, **_kwargs):
        index = state["index"]
        state["index"] += 1
        return iter(turns[min(index, len(turns) - 1)])

    return provider


def _text_turn(text):
    return [
        {"type": "text_delta", "text": text},
        {"type": "message_end", "stop_reason": "end_turn", "usage": {}},
    ]


def _tool_turn(tool_id, name, params=None):
    return [
        {"type": "tool_use_start", "id": tool_id, "name": name},
        {"type": "tool_use_end", "id": tool_id, "name": name, "input": params or {}},
        {"type": "message_end", "stop_reason": "tool_use", "usage": {}},
    ]


def _parse_sse(response) -> list[dict]:
    return [
        json.loads(line[5:].strip())
        for line in response.text.splitlines()
        if line.startswith("data:")
    ]


class LangGraphExperimentalHttpTests(unittest.TestCase):
    def setUp(self) -> None:
        reset_limits()
        reset_resources()
        self.tmp = tempfile.mkdtemp()
        self.workspace = Path(self.tmp)
        self.agent_name = f"langgraph-http-test-{id(self)}"
        get_agent_def_registry()._defs[self.agent_name] = AgentDef(
            self.agent_name, tools=[],
        )
        with patch("bi_agent.web.app.OntologyStore.from_xlsx", return_value=OntologyStore()):
            web_app_module.configure(
                self.tmp, self.tmp, self.tmp, agent_name=self.agent_name,
            )
        self.client = TestClient(app)

    def tearDown(self) -> None:
        for key in list(os.environ):
            if key.startswith("CHATBI_"):
                os.environ.pop(key, None)
        reset_limits()
        reset_resources()
        get_agent_def_registry()._defs.pop(self.agent_name, None)

    def _conversation_files(self) -> list[str]:
        root = self.workspace / "dataset" / "conversations"
        if not root.exists():
            return []
        return sorted(str(path.relative_to(root)) for path in root.rglob("*") if path.is_file())

    def test_experimental_endpoint_is_disabled_by_default(self) -> None:
        response = self.client.post(
            "/api/experimental/langgraph/chat",
            json={"message": "你好", "session_id": "exp-off"},
        )
        self.assertEqual(response.status_code, 404)
        self.assertEqual(STATE.experimental_sessions, {})

    def test_engine_env_alone_can_enable_the_experimental_endpoint(self) -> None:
        os.environ["CHATBI_AGENT_ENGINE"] = "langgraph"
        with patch(
            "bi_agent.web.session.stream_message",
            side_effect=_provider_turns(_text_turn("环境变量启用")),
        ):
            response = self.client.post(
                "/api/experimental/langgraph/chat",
                json={"message": "你好", "session_id": "exp-engine-env"},
            )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(_parse_sse(response)[-1]["type"], "done")

    def test_experimental_chat_uses_its_own_session_and_does_not_write_history(self) -> None:
        os.environ["CHATBI_ENABLE_LANGGRAPH_EXPERIMENT"] = "1"
        before = self._conversation_files()
        with patch(
            "bi_agent.web.session.stream_message",
            side_effect=_provider_turns(_text_turn("实验回答")),
        ):
            response = self.client.post(
                "/api/experimental/langgraph/chat",
                json={"message": "你好", "session_id": "exp-on"},
            )

        self.assertEqual(response.status_code, 200)
        events = _parse_sse(response)
        self.assertEqual(events[-1]["type"], "done")
        self.assertEqual(
            "".join(e.get("text", "") for e in events if e["type"] == "text_delta"),
            "实验回答",
        )
        self.assertIn("exp-on", STATE.experimental_sessions)
        self.assertNotIn("exp-on", STATE.sessions)
        self.assertEqual(
            STATE.experimental_sessions["exp-on"].__class__.__name__,
            "LangGraphWebSession",
        )
        self.assertEqual(self._conversation_files(), before)

    def test_legacy_chat_stays_on_legacy_engine_when_experiment_is_enabled(self) -> None:
        os.environ["CHATBI_ENABLE_LANGGRAPH_EXPERIMENT"] = "1"
        with patch(
            "bi_agent.web.session.stream_message",
            side_effect=_provider_turns(_text_turn("旧引擎回答")),
        ):
            response = self.client.post(
                "/api/chat",
                json={"message": "你好", "session_id": "legacy-stays"},
            )

        self.assertEqual(response.status_code, 200)
        session = STATE.sessions["legacy-stays"]
        self.assertIs(type(session), WebSession)
        self.assertNotIn("legacy-stays", STATE.experimental_sessions)

    def test_same_session_id_keeps_legacy_and_experimental_messages_isolated(self) -> None:
        os.environ["CHATBI_ENABLE_LANGGRAPH_EXPERIMENT"] = "1"
        with patch(
            "bi_agent.web.session.stream_message",
            side_effect=_provider_turns(_text_turn("旧回答")),
        ):
            self.client.post("/api/chat", json={"message": "旧问题", "session_id": "same-id"})
        with patch(
            "bi_agent.web.session.stream_message",
            side_effect=_provider_turns(_text_turn("实验回答")),
        ):
            self.client.post(
                "/api/experimental/langgraph/chat",
                json={"message": "实验问题", "session_id": "same-id"},
            )

        self.assertEqual(STATE.sessions["same-id"].messages[0]["content"], "旧问题")
        self.assertEqual(
            STATE.experimental_sessions["same-id"].messages[0]["content"],
            "实验问题",
        )
        self.assertEqual(STATE.sessions["same-id"].messages[-1]["content"][0]["text"], "旧回答")
        self.assertEqual(
            STATE.experimental_sessions["same-id"].messages[-1]["content"][0]["text"],
            "实验回答",
        )

    def test_experimental_choice_resumes_only_the_experimental_session(self) -> None:
        os.environ["CHATBI_ENABLE_LANGGRAPH_EXPERIMENT"] = "1"
        turns = (
            _tool_turn("ask-http", "AskUser", {
                "question": "请选择口径",
                "options": [{"id": "a", "label": "口径 A"}],
            }),
            _text_turn("已按口径 A 回答"),
        )
        with patch(
            "bi_agent.web.session.stream_message",
            side_effect=_provider_turns(*turns),
        ):
            first = self.client.post(
                "/api/experimental/langgraph/chat",
                json={"message": "请分析", "session_id": "choice-only-exp"},
            )
            self.assertTrue(
                any(e["type"] == "awaiting_user_choice" for e in _parse_sse(first))
            )
            second = self.client.post(
                "/api/experimental/langgraph/choice",
                json={
                    "session_id": "choice-only-exp",
                    "choice_ids": ["a"],
                    "choice_labels": ["口径 A"],
                },
            )

        self.assertEqual(second.status_code, 200)
        events = _parse_sse(second)
        self.assertIn("user_choice_resolved", [e["type"] for e in events])
        self.assertEqual(events[-1]["type"], "done")
        self.assertNotIn("choice-only-exp", STATE.sessions)


if __name__ == "__main__":
    unittest.main()
