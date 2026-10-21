"""Offline golden-set parity for the opt-in LangGraph engine.

The recorded-provider replay drives the real tool implementations against the
read-only eval fixtures.  Only the model token stream is replayed.
"""

from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPTS_DIR = REPO_ROOT / "scripts"
EVAL_ROOT = REPO_ROOT / "dataset" / "evals" / "analytics"
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))


def _case(case_id: str) -> dict:
    for path in sorted((EVAL_ROOT / "cases").glob(f"*/{case_id}.json")):
        return json.loads(path.read_text(encoding="utf-8"))
    raise AssertionError(f"missing eval case {case_id}")


class LangGraphRecordedParityTests(unittest.TestCase):
    @staticmethod
    def _normalized_messages(value):
        """Compare message semantics; replay tool ids are intentionally unique."""
        if isinstance(value, dict):
            return {
                key: (
                    "<replay-tool-id>"
                    if key in {"id", "tool_use_id"}
                    and str(item).startswith("rec-")
                    else LangGraphRecordedParityTests._normalized_messages(item)
                )
                for key, item in value.items()
            }
        if isinstance(value, list):
            return [LangGraphRecordedParityTests._normalized_messages(item) for item in value]
        return value

    def _replay(self, case_id: str, session_cls):
        from analytics_recorded_provider import load_transcript, run_recorded_turns

        case = _case(case_id)
        transcript = load_transcript(EVAL_ROOT / case["fixture"]["provider"])
        workspace = Path(tempfile.mkdtemp(prefix=f"lg-{case_id}-"))
        return run_recorded_turns(
            case_id,
            transcript["turns"],
            fixture_db=case["fixture"]["db"],
            workspace=workspace,
            tools_override=case["fixture"].get("tools_override"),
            session_cls=session_cls,
        )

    def _assert_parity(self, case_id: str) -> None:
        from bi_agent.experimental.langgraph_session import LangGraphWebSession
        from bi_agent.web.session import WebSession

        legacy = self._replay(case_id, WebSession)
        graph = self._replay(case_id, LangGraphWebSession)

        self.assertEqual(
            [event["type"] for event in graph.events],
            [event["type"] for event in legacy.events],
        )
        self.assertEqual(graph.tool_names, legacy.tool_names)
        self.assertEqual(
            [call["input"] for call in graph.tool_calls],
            [call["input"] for call in legacy.tool_calls],
        )
        self.assertEqual(
            [call["status"] for call in graph.tool_calls],
            [call["status"] for call in legacy.tool_calls],
        )
        self.assertEqual(graph.text, legacy.text)
        self.assertEqual(graph.done_stop_reason, legacy.done_stop_reason)
        self.assertEqual(
            self._normalized_messages(graph.session.messages),
            self._normalized_messages(legacy.session.messages),
        )
        self.assertEqual(
            graph.session.recovery.status(),
            legacy.session.recovery.status(),
        )
        self.assertEqual(graph.errors, legacy.errors)

    def test_generated_sql_case_matches_on_the_graph_engine(self) -> None:
        self._assert_parity("ANA-RPSQL-001")

    def test_tool_failure_case_matches_on_the_graph_engine(self) -> None:
        self._assert_parity("ANA-RPFAIL-001")

    def test_eval_runner_can_run_a_golden_case_on_the_graph_engine(self) -> None:
        import run_analytics_eval as runner
        from bi_agent.experimental.langgraph_session import LangGraphWebSession

        ctx = runner.EvalContext(session_cls=LangGraphWebSession)
        result = runner.run_case(_case("ANA-RPSQL-001"), ctx)
        self.assertEqual(result.status, runner.PASS, result.failed_checks)

    def test_eval_cli_engine_defaults_to_legacy_and_accepts_langgraph(self) -> None:
        import run_analytics_eval as runner

        self.assertEqual(runner.build_parser().parse_args([]).engine, "legacy")
        args = runner.build_parser().parse_args(["--suite", "recorded-provider", "--engine", "langgraph"])
        self.assertEqual(args.engine, "langgraph")


if __name__ == "__main__":
    unittest.main()
