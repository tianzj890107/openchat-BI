"""TDD RED: V6.1 handoff scope must reach the analysis turn.

The AgentKit workbench sends the card context separately from what the user
sees: the prompt carries the scope, `visible_user_text` stays the question
(spec §3.2, §4.1).
"""

from __future__ import annotations

from pathlib import Path
import sys
import types
import unittest
from unittest import mock

from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from bi_agent.web import app as web_app  # noqa: E402


SCOPE = {
    "source": "v61-cockpit",
    "anchor": "PACK_OPP_COVERAGE",
    "period": "2026Q3",
    "filters": {"customer": "宁德时代", "region": "华东"},
    "evidence": ["ev-11", "ev-12"],
    "handoff_id": "h-7",
}


class FakeSession:
    def __init__(self) -> None:
        self.calls: list[tuple[str, str | None]] = []

    def generate_turn(self, message: str, visible: str | None = None):
        self.calls.append((message, visible))

        def gen():
            yield {"type": "done", "turn_id": "t-test"}

        return gen()


class ScopeUnitTests(unittest.TestCase):
    def test_scope_text_carries_anchor_period_filters_and_evidence(self) -> None:
        text = web_app._handoff_scope_text(SCOPE)
        self.assertIn("PACK_OPP_COVERAGE", text)
        self.assertIn("2026Q3", text)
        self.assertIn("customer=宁德时代", text)
        self.assertIn("ev-11", text)
        self.assertIn("v61-cockpit", text)

    def test_scope_without_anchor_or_period_is_rejected(self) -> None:
        with self.assertRaises(web_app.HTTPException) as missing_anchor:
            web_app._handoff_scope_text({"period": "2026Q3"})
        self.assertEqual(missing_anchor.exception.status_code, 400)

        with self.assertRaises(web_app.HTTPException) as missing_period:
            web_app._handoff_scope_text({"anchor": "PACK_OPP_COVERAGE"})
        self.assertEqual(missing_period.exception.status_code, 400)

    def test_no_scope_yields_no_prefix(self) -> None:
        self.assertEqual(web_app._handoff_scope_text(None), "")


class ScopeRouteTests(unittest.TestCase):
    def setUp(self) -> None:
        self.session = FakeSession()
        self.client = TestClient(web_app.app)

    def _patch(self):
        return (
            mock.patch.object(web_app, "_ensure_session", return_value=self.session),
            mock.patch.object(web_app, "_begin_turn", return_value=(None, None, "t-test", None, None)),
            mock.patch.object(
                web_app,
                "_run_turn_stream",
                side_effect=lambda session, gen, *args, **kwargs: web_app.StreamingResponse(
                    iter([b"data: {}\n\n"]), media_type="text/event-stream"
                ),
            ),
        )

    def test_chat_carries_scope_into_the_turn_and_keeps_visible_text(self) -> None:
        ensure, begin, run = self._patch()
        with ensure, begin, run:
            response = self.client.post("/api/chat", json={
                "message": "PACK 未签单商机主要涉及哪些客户？",
                "visible_user_text": "PACK 未签单商机主要涉及哪些客户？",
                "session_id": "agentkit-test",
                "scope": SCOPE,
            })
        self.assertEqual(response.status_code, 200)
        self.assertTrue(self.session.calls, "generate_turn must run")
        prompt, visible = self.session.calls[0]
        self.assertIn("PACK_OPP_COVERAGE", prompt)
        self.assertIn("2026Q3", prompt)
        self.assertEqual(visible, "PACK 未签单商机主要涉及哪些客户？")

    def test_chat_rejects_an_incomplete_scope(self) -> None:
        ensure, begin, run = self._patch()
        with ensure, begin, run:
            response = self.client.post("/api/chat", json={
                "message": "问题",
                "session_id": "agentkit-test",
                "scope": {"period": "2026Q3"},
            })
        self.assertEqual(response.status_code, 400)
        self.assertEqual(self.session.calls, [])


if __name__ == "__main__":
    unittest.main()
