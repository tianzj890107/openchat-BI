"""Production-chain sentinels: a broken agent must make these tests go red.

Every test here applies one *mutation to production code or to the recorded
model decisions* and then asserts that a real golden-set case fails.  If the
golden set is ever weakened — a check silently dropped, a gate loosened, an
assertion turned into documentation — the mutation stops being caught and this
file fails.

Nothing is faked in the *evaluator*: the cases are run through the real
``WebSession`` turn loop with the real tools bound to the read-only eval
fixtures.  Only the model's decisions (the transcript) or a production
dependency is patched.

Fully offline: no model call, no network, no real database.
"""

from __future__ import annotations

import contextlib
import copy
import itertools
import importlib.util
import json
import re
import sys
import unittest
from pathlib import Path
from unittest import mock

REPO_ROOT = Path(__file__).resolve().parent.parent
EVAL_ROOT = REPO_ROOT / "dataset" / "evals" / "analytics"
CASES_DIR = EVAL_ROOT / "cases"
SQLITE_DIR = EVAL_ROOT / "fixtures" / "sqlite"
PROVIDER_DIR = EVAL_ROOT / "fixtures" / "provider"

if str(REPO_ROOT / "scripts") not in sys.path:
    sys.path.insert(0, str(REPO_ROOT / "scripts"))


def _load_runner():
    name = "analytics_eval_runner_chain"
    spec = importlib.util.spec_from_file_location(
        name, REPO_ROOT / "scripts" / "run_analytics_eval.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


RUNNER = _load_runner()


def _case(case_id: str) -> dict:
    for path in sorted(CASES_DIR.glob(f"*/{case_id}.json")):
        return json.loads(path.read_text(encoding="utf-8"))
    raise AssertionError(f"missing case {case_id}")


def _run(case_id: str, patches=()) -> object:
    """Run one golden-set case with ``patches`` applied."""
    case = _case(case_id)
    ctx = RUNNER.EvalContext()
    with contextlib.ExitStack() as stack:
        for target, attribute, replacement in patches:
            stack.enter_context(mock.patch.object(target, attribute, replacement))
        return RUNNER.run_case(case, ctx)


def _failing_checks(result) -> list[str]:
    return [check.name for check in result.checks if not check.ok]


def _transcript_mutator(case_id: str, mutate):
    """Patch the recorded *model decisions* for one transcript.

    ``run_recorded_turns`` and the tools stay untouched: the mutation stands in
    for "the model said something different this time".
    """
    import analytics_recorded_provider as recorded

    original = recorded.load_transcript
    target = PROVIDER_DIR / Path(_case(case_id)["fixture"]["provider"]).relative_to("fixtures/provider")

    def load(path):
        payload = copy.deepcopy(original(path))
        if Path(path) == target:
            mutate(payload)
        return payload

    return load


def _terminate_events(payload: dict) -> list[dict]:
    return payload["turns"][0]["events"]


_REPLAY_CACHE: dict[str, tuple[dict, object]] = {}


def _replay(case_id: str):
    """Replay one recorded case through the real turn loop (cached)."""
    if case_id not in _REPLAY_CACHE:
        import analytics_recorded_provider as recorded

        case = _case(case_id)
        transcript = recorded.load_transcript(EVAL_ROOT / case["fixture"]["provider"])
        run = recorded.run_recorded_turns(
            case_id, transcript["turns"],
            fixture_db=RUNNER.resolve_fixture_db(case),
            workspace=RUNNER.EvalContext().new_sandbox(case_id))
        _REPLAY_CACHE[case_id] = (case, run)
    return _REPLAY_CACHE[case_id]


def _borrowed_numbers(donor: str, recipient: str) -> list[float]:
    """Distinctive numbers ``donor`` produced that ``recipient`` never produced."""
    donor_case, donor_run = _replay(donor)
    recipient_case, recipient_run = _replay(recipient)
    donor_pool = RUNNER.RecordedPool(donor_case, donor_run).pool
    recipient_pool = RUNNER.RecordedPool(recipient_case, recipient_run).pool
    return sorted(n for n in donor_pool if abs(n) > 1000 and n not in recipient_pool)


class BaselineTest(unittest.TestCase):
    """The cases under mutation must be green before the mutation."""

    def test_reference_cases_pass_unmutated(self):
        for case_id in ("ANA-RPSQL-001", "ANA-RPCHART-009", "ANA-RPFAIL-001"):
            with self.subTest(case_id=case_id):
                result = _run(case_id)
                self.assertEqual(result.status, RUNNER.PASS, _failing_checks(result))


class ToolExecutionMutationTest(unittest.TestCase):
    def test_websession_that_skips_tool_execution_is_caught(self):
        from bi_agent.web import session as session_module

        def _no_tools(self, tool_use, turn_ctx=None, *, retry=False):
            return "", False

        result = _run("ANA-RPSQL-001", [
            (session_module.WebSession, "_execute_tool", _no_tools)])
        self.assertEqual(result.status, RUNNER.FAIL,
                         "a session that never executes tools must be caught")
        failing = _failing_checks(result)
        self.assertTrue(any(name.endswith("execution_audit") for name in failing), failing)
        self.assertTrue(any(name.endswith("sql_result_metadata") for name in failing), failing)

    def test_sql_tool_replaced_by_a_stub_is_caught(self):
        import analytics_recorded_provider as recorded
        from bi_agent.tools import build_source_executors

        def _stubbed(store, db_path, fixture_dir=None):
            executors = dict(build_source_executors(store, db_path))
            executors["Ontology-FactQuery"] = lambda params, cwd: "SQL: (stub)\n\nv\n999999\n"
            return executors

        result = _run("ANA-RPSQL-001", [(recorded, "_ensure_registration", _stubbed)])
        self.assertEqual(result.status, RUNNER.FAIL,
                         "a stubbed SQL tool must not satisfy a generated-SQL case")
        failing = _failing_checks(result)
        self.assertTrue(any(name.endswith("sql_result_metadata") for name in failing), failing)

    def test_sql_tool_bound_to_the_wrong_database_is_caught(self):
        import analytics_recorded_provider as recorded
        from bi_agent.tools import build_source_executors

        def _wrong_db(store, db_path, fixture_dir=None):
            return build_source_executors(store, str(SQLITE_DIR / "procurement.db"))

        result = _run("ANA-RPSQL-017", [(recorded, "_ensure_registration", _wrong_db)])
        self.assertEqual(result.status, RUNNER.FAIL,
                         "a finance case must fail when the tool reads procurement data")
        failing = _failing_checks(result)
        self.assertTrue("generated_sql.sql_result_metadata" in failing
                        or "generated_sql.matches_reference" in failing, failing)


class TranscriptMutationTest(unittest.TestCase):
    """Model-side mutations: the gate must catch what the model got wrong."""

    def test_a_dropped_required_filter_is_caught(self):
        def strip_filter(payload):
            for event in _terminate_events(payload):
                if event.get("type") == "tool_start" and isinstance(event.get("input"), dict):
                    sql = event["input"].get("sql")
                    if isinstance(sql, str):
                        event["input"]["sql"] = sql.replace(" WHERE is_deleted = 0", "")

        result = _run("ANA-RPSQL-001",
                      [(sys.modules["analytics_recorded_provider"], "load_transcript",
                        _transcript_mutator("ANA-RPSQL-001", strip_filter))])
        self.assertEqual(result.status, RUNNER.FAIL)
        self.assertTrue(any("required_filter" in name for name in _failing_checks(result)),
                        _failing_checks(result))

    def test_an_unauthorised_table_is_caught(self):
        def join_secret_table(payload):
            for event in _terminate_events(payload):
                if event.get("type") == "tool_start" and isinstance(event.get("input"), dict):
                    sql = event["input"].get("sql")
                    if isinstance(sql, str):
                        event["input"]["sql"] = sql.replace(
                            "FROM fact_purchase_order",
                            "FROM fact_purchase_order JOIN salary_ledger ON 1=1")

        result = _run("ANA-RPSQL-002",
                      [(sys.modules["analytics_recorded_provider"], "load_transcript",
                        _transcript_mutator("ANA-RPSQL-002", join_secret_table))])
        self.assertEqual(result.status, RUNNER.FAIL)
        self.assertTrue(any("tables_allowed" in name for name in _failing_checks(result)),
                        _failing_checks(result))

    def test_a_hallucinated_number_is_caught(self):
        def invent_number(payload):
            for event in _terminate_events(payload):
                if event.get("type") == "text_delta":
                    event["text"] = str(event["text"]) + " 参考金额 9876543.21 元。"

        result = _run("ANA-RPSQL-001",
                      [(sys.modules["analytics_recorded_provider"], "load_transcript",
                        _transcript_mutator("ANA-RPSQL-001", invent_number))])
        self.assertEqual(result.status, RUNNER.FAIL)
        self.assertTrue(any(name.endswith("answer_grounded") for name in _failing_checks(result)),
                        _failing_checks(result))

    def test_a_number_copied_from_a_sibling_case_is_caught(self):
        borrowed = _borrowed_numbers("ANA-RPSQL-013", "ANA-RPSQL-001")
        self.assertTrue(borrowed, "the two cases must produce distinct numbers")
        donor_number = borrowed[0]

        def cite_sibling_number(payload):
            for event in _terminate_events(payload):
                if event.get("type") == "text_delta":
                    event["text"] = str(event["text"]) + f"（同期值 {donor_number:.2f} 元）"

        result = _run("ANA-RPSQL-001",
                      [(sys.modules["analytics_recorded_provider"], "load_transcript",
                        _transcript_mutator("ANA-RPSQL-001", cite_sibling_number))])
        self.assertEqual(result.status, RUNNER.FAIL,
                         "a sibling case's number must not ground this answer")
        self.assertTrue(any(name.endswith("answer_grounded") for name in _failing_checks(result)),
                        _failing_checks(result))

    def test_duplicate_provider_tool_call_is_caught(self):
        def duplicate(payload):
            events = _terminate_events(payload)
            first = next(e for e in events if e.get("type") == "tool_start")
            events.insert(events.index(first) + 1, copy.deepcopy(first))

        result = _run("ANA-RPSQL-001",
                      [(sys.modules["analytics_recorded_provider"], "load_transcript",
                        _transcript_mutator("ANA-RPSQL-001", duplicate))])
        self.assertEqual(result.status, RUNNER.FAIL,
                         "a duplicated tool call must break the tool-chain assertion")

    def test_a_truncated_provider_stream_is_caught(self):
        def truncate(payload):
            events = _terminate_events(payload)
            payload["turns"][0]["events"] = [e for e in events if e.get("type") != "text_delta"]

        result = _run("ANA-RPSQL-001",
                      [(sys.modules["analytics_recorded_provider"], "load_transcript",
                        _transcript_mutator("ANA-RPSQL-001", truncate))])
        self.assertEqual(result.status, RUNNER.FAIL,
                         "a provider stream without its narrative must not pass silently")

    def test_a_superseded_turn_that_keeps_running_is_caught(self):
        """A cancel/preemption that no longer supersedes the old turn must fail."""
        from bi_agent import concurrency as concurrency_module

        result = _run("ANA-CONC-010", [
            (concurrency_module.SessionSlot, "is_superseded",
             lambda self, lease, cancel: False)])
        self.assertEqual(result.status, RUNNER.FAIL,
                         "a preempted turn that keeps running must be caught")
        self.assertTrue(_failing_checks(result))


class EvidenceChainMutationTest(unittest.TestCase):
    def test_evidence_from_another_session_is_not_grounded(self):
        """A pool built for case B never accepts case A's outputs."""
        borrowed = _borrowed_numbers("ANA-RPSQL-013", "ANA-RPSQL-001")
        self.assertTrue(borrowed, "the two cases must produce distinct numbers")
        case_b, run_b = _replay("ANA-RPSQL-001")
        pool_b = RUNNER.RecordedPool(case_b, run_b)
        for number in borrowed:
            with self.subTest(number=number):
                self.assertIn(number, pool_b.unsupported(f"本期金额 {number:.2f} 元"))

    def test_recovery_state_is_not_skipped(self):
        from bi_agent import recovery as recovery_module

        def _never_terminal(self, *args, **kwargs):
            return None

        result = _run("ANA-RPFAIL-001", [
            (recovery_module.RecoveryState, "tool_terminal", _never_terminal)])
        self.assertEqual(result.status, RUNNER.FAIL,
                         "a recovery machine that never terminalizes must be caught")
        self.assertIn("recorded.recovery_status", _failing_checks(result))

    def test_negative_context_override_is_not_dropped(self):
        from bi_agent import reliability as reliability_module

        original = reliability_module.AnalysisContext.merge

        def _skip_empty(self, changes):
            return original(self, {k: v for k, v in changes.items() if v})

        result = _run("ANA-CTX-009", [
            (reliability_module.AnalysisContext, "merge", _skip_empty)])
        self.assertEqual(result.status, RUNNER.FAIL,
                         "dropping an empty (negative) override must be caught")
        self.assertTrue(_failing_checks(result))


class PresentationMutationTest(unittest.TestCase):
    def test_unescaped_chart_title_is_caught(self):
        from bi_agent.tools import chart_tools

        result = _run("ANA-RPCHART-009", [
            (chart_tools, "escape", lambda value, quote=True: str(value))])
        self.assertEqual(result.status, RUNNER.FAIL,
                         "writing the raw title into the chart HTML must be caught")
        self.assertTrue(any("chart_absent" in name for name in _failing_checks(result)),
                        _failing_checks(result))


class ToolRegistryContractTest(unittest.TestCase):
    """Every tool a recorded transcript calls must exist in the registry."""

    @staticmethod
    def _registered_tool_names() -> set[str]:
        from bi_agent.tools import (
            ask_user, chart_multidim_tools, chart_tools, graph_tools,
            ontology_tools, sql_tools, table_tools, todo_tools,
        )

        names: set[str] = set()
        for module in (ask_user, chart_multidim_tools, chart_tools, graph_tools,
                       ontology_tools, sql_tools, table_tools, todo_tools):
            for schema, _factory in module.SPECS:
                names.add(str(schema["name"]))
        return names

    @staticmethod
    def _transcript_tool_names() -> set[str]:
        names: set[str] = set()
        for path in sorted(PROVIDER_DIR.rglob("*.json")):
            payload = json.loads(path.read_text(encoding="utf-8"))
            for turn in payload.get("turns", []):
                for event in turn.get("events", []):
                    if event.get("type") == "tool_start":
                        names.add(str(event.get("name")))
        return names

    def test_every_recorded_tool_exists_in_the_registry(self):
        registered = self._registered_tool_names()
        used = self._transcript_tool_names()
        self.assertTrue(used)
        self.assertEqual(sorted(used - registered), [],
                         "the golden set calls a tool the registry no longer provides")

    def test_renaming_a_tool_breaks_the_contract(self):
        from bi_agent.tools import sql_tools

        original = sql_tools.SPECS[0][0]["name"]
        try:
            sql_tools.SPECS[0][0]["name"] = "RenamedTool"
            self.assertTrue(self._transcript_tool_names() - self._registered_tool_names(),
                            "a renamed tool must be reported as missing")
        finally:
            sql_tools.SPECS[0][0]["name"] = original


# ---------------------------------------------------------------------------
# Prompt contract
# ---------------------------------------------------------------------------
#
# The system prompt is the model's real contract: it lists the tools the agent
# may call and carries the safety rules.  A prompt regression (a section
# silently dropped, a tool no longer described, a safety rule deleted) is
# invisible to every other test in this repository, because they never look at
# the assembled prompt.
#
# The contract asserts *semantic anchors* only.  There is deliberately no
# stored copy or hash of the prompt: rewording, whitespace and reordering must
# stay allowed, otherwise every prompt edit becomes a maintenance chore and the
# contract gets weakened instead of maintained.

REQUIRED_PROMPT_SECTIONS = (
    "# Tools",
    "# Skills",
    "# Guidelines",
    "# Doing Tasks",
    "# Safety",
    "# 运作方式",
    "# AnalysisContext",
    "# 输出展示规范",
    "# 分析深度与卡片约束",
)

REQUIRED_SAFETY_RULES = (
    "destructive or hard-to-reverse",
    "Do not delete files, force-push",
    "Validate at system boundaries",
)

NEXT_TOP_LEVEL_HEADING = re.compile(r"^# ", re.MULTILINE)


def _tools_section(prompt: str) -> str:
    """Return the ``# Tools`` block, or an empty string when it is absent."""
    start = prompt.find("# Tools")
    if start < 0:
        return ""
    rest = prompt[start + len("# Tools"):]
    match = NEXT_TOP_LEVEL_HEADING.search(rest.lstrip("\n"))
    if not match:
        return rest
    return rest.lstrip("\n")[:match.start()]


def _prompt_contract_violations(prompt: str, tools: list[str]) -> list[str]:
    """Semantic violations of the system-prompt contract.

    Pure function: the same inputs always give the same answer, so a mutation
    can be applied to a copy without touching production state.
    """
    violations: list[str] = []
    for section in REQUIRED_PROMPT_SECTIONS:
        if section not in prompt:
            violations.append(f"missing section: {section}")
    tools_block = _tools_section(prompt)
    if not tools_block.strip():
        violations.append("missing tool listing (# Tools is empty)")
    else:
        for tool in tools:
            if tool not in tools_block:
                violations.append(f"tool not described in # Tools: {tool}")
    for rule in REQUIRED_SAFETY_RULES:
        if rule not in prompt:
            violations.append(f"missing safety rule: {rule}")
    if len(prompt) < 4000:
        violations.append("system prompt is too short to carry the SOP")
    return violations


_PROMPT_CACHE: dict[str, object] = {}


def _prompt_contract_fixture() -> tuple[str, list[str]]:
    """Build the real analytics system prompt through the production seam."""
    if not _PROMPT_CACHE:
        import analytics_recorded_provider as recorded

        from bi_agent.web.session import WebSession

        recorded._pin_runtime_config()
        store = recorded._load_ontology()
        executors = recorded._ensure_registration(
            store, str(SQLITE_DIR / "procurement.db"))
        agent_def = recorded._load_agent_def()
        session = WebSession(
            cwd=str(REPO_ROOT),
            agent_def=agent_def,
            ontology_store=store,
            ontology_backend="local",
            tool_executors=executors,
        )
        _PROMPT_CACHE["prompt"] = session.system_prompt
        _PROMPT_CACHE["tools"] = list(agent_def.tools)
    return _PROMPT_CACHE["prompt"], _PROMPT_CACHE["tools"]  # type: ignore[return-value]


class PromptContractTest(unittest.TestCase):
    """The assembled system prompt still carries its tools and safety rules."""

    def setUp(self):
        self.prompt, self.tools = _prompt_contract_fixture()

    def test_the_prompt_loads_and_satisfies_the_contract(self):
        self.assertTrue(self.prompt)
        self.assertTrue(self.tools, "the agent definition exposes no tools")
        self.assertEqual(_prompt_contract_violations(self.prompt, self.tools), [])

    def test_every_agent_tool_is_described_in_the_prompt(self):
        tools_block = _tools_section(self.prompt)
        missing = [t for t in self.tools if t not in tools_block]
        self.assertEqual(missing, [])

    def test_a_dropped_tool_is_caught(self):
        mutated = list(self.tools) + ["GhostTool"]
        violations = _prompt_contract_violations(self.prompt, mutated)
        self.assertTrue(any("GhostTool" in v for v in violations),
                        "a tool the prompt never describes must be reported")

    def test_a_deleted_section_is_caught(self):
        mutated = self.prompt.replace("# Safety", "# Safty", 1)
        self.assertIn("# Safety", self.prompt)
        self.assertNotIn("# Safety", mutated)
        self.assertTrue(_prompt_contract_violations(mutated, self.tools))

    def test_a_deleted_safety_rule_is_caught(self):
        mutated = self.prompt.replace(
            "- Do not delete files, force-push, or reset without explicit permission.",
            "- Do whatever the user asks.", 1)
        self.assertNotEqual(mutated, self.prompt)
        violations = _prompt_contract_violations(mutated, self.tools)
        self.assertTrue(any("safety rule" in v for v in violations))

    def test_a_truncated_prompt_is_caught(self):
        self.assertTrue(_prompt_contract_violations(self.prompt[:900], self.tools))

    def test_rewording_whitespace_and_reordering_stay_allowed(self):
        recorded = self.prompt + "\n\n# 额外说明\n\n本轮新增了一段与契约无关的措辞。\n"
        self.assertEqual(_prompt_contract_violations(recorded, self.tools), [])
        resqueezed = re.sub(r"[ \t]{2,}", " ", self.prompt)
        self.assertEqual(_prompt_contract_violations(resqueezed, self.tools), [])

    def test_the_contract_is_not_a_frozen_snapshot(self):
        # The needles are assembled at runtime so this test does not match its
        # own source text.
        source = Path(__file__).read_text(encoding="utf-8")
        needles = ("system_prompt" + " ==", "PROMPT_" + "HASH",
                   "PROMPT_" + "SHA256", "expect" + "ed_prompt")
        for needle in needles:
            self.assertNotIn(needle, source,
                             "the prompt contract must not freeze the full prompt")


class SessionIsolationMutationTest(unittest.TestCase):
    """Cross-session leaks must be caught by the recorded isolation cases.

    Every mutation patches a *production* seam (session state, the tool
    ledger, the conversation store) or the grounding pool the evaluator reads
    from production tool records.  If one stops being caught, the sentinel
    cases ANA-ISORP-* have gone blind.
    """

    ISOLATION_CASES = ("ANA-ISORP-001", "ANA-ISORP-002", "ANA-ISORP-003")

    def _run_with(self, case_id: str, patches, expect_check: str):
        case = _case(case_id)
        ctx = RUNNER.EvalContext()
        with contextlib.ExitStack() as stack:
            for target, attribute, replacement in patches:
                stack.enter_context(mock.patch.object(target, attribute, replacement))
            result = RUNNER.run_case(case, ctx)
        self.assertEqual(result.status, RUNNER.FAIL,
                         f"{case_id}: mutation was not caught")
        failed = _failing_checks(result)
        self.assertTrue(any(name.startswith(expect_check) for name in failed),
                        f"{case_id}: expected {expect_check!r} in {failed}")
        return result

    def test_the_isolation_cases_pass_unmutated(self):
        for case_id in self.ISOLATION_CASES + ("ANA-ISORP-004", "ANA-ISORP-005",
                                               "ANA-ISORP-006"):
            with self.subTest(case_id=case_id):
                result = _run(case_id)
                self.assertEqual(result.status, RUNNER.PASS, _failing_checks(result))

    def test_one_conversation_id_for_every_session_is_caught(self):
        from bi_agent.web import conversations

        def _same_id(self):
            return "deadbeef"

        self._run_with("ANA-ISORP-003",
                       [(conversations.ConversationStore, "_new_id", _same_id)],
                       "isolation.leak.store_distinct_ids")

    def test_one_shared_analysis_context_is_caught(self):
        from bi_agent.web import session as session_module

        shared = session_module.AnalysisContext()

        def _factory(*args, **kwargs):
            return shared

        self._run_with("ANA-ISORP-001",
                       [(session_module, "AnalysisContext", _factory)],
                       "isolation.leak.context_object_distinct")

    def test_a_global_grounding_pool_is_caught(self):
        seen: set = set()
        original = RUNNER.RecordedPool

        class _GlobalPool(original):  # type: ignore[misc, valid-type]
            def __init__(self, case, run):
                super().__init__(case, run)
                seen.update(self.pool)
                self.pool = set(self.pool) | set(seen)

        self._run_with("ANA-ISORP-001",
                       [(RUNNER, "RecordedPool", _GlobalPool)],
                       "isolation.borrowed_is_donor_only")

    def test_random_conversation_ids_do_not_destabilise_repeat(self):
        """``--repeat`` must ignore the random ids a store happens to mint.

        The ids in ``isolation.leak.store_distinct_ids`` are generated by
        ``secrets.token_hex``; reporting them verbatim made the same case look
        unstable on the second run.
        """
        from bi_agent.web import conversations

        counter = itertools.count(1)

        def _varying_id(self):
            # Same shape as ``secrets.token_hex(4)``: the store validates ids as
            # single safe filenames, so the mutation has to stay hex-shaped.
            value = next(counter)
            return f"{value:08x}"

        case = _case("ANA-ISORP-003")
        signatures = []
        with mock.patch.object(conversations.ConversationStore, "_new_id", _varying_id):
            for _ in range(2):
                result = RUNNER.run_case(case, RUNNER.EvalContext())
                self.assertEqual(result.status, RUNNER.PASS, _failing_checks(result))
                signatures.append(RUNNER.result_signature(result))
        self.assertEqual(signatures[0], signatures[1],
                         "a random conversation id made a stable case unstable")

    def test_the_signature_still_catches_a_real_difference(self):
        case = _case("ANA-ISORP-001")
        first = RUNNER.run_case(case, RUNNER.EvalContext())
        self.assertEqual(first.status, RUNNER.PASS, _failing_checks(first))

        original = RUNNER._iso_leak_checks

        def _mutated(case_dict, expected, grouped, runs, checks):
            original(case_dict, expected, grouped, runs, checks)
            checks[-1] = RUNNER.Check(checks[-1].name, checks[-1].ok,
                                      checks[-1].expected, "tampered")

        with mock.patch.object(RUNNER, "_iso_leak_checks", _mutated):
            second = RUNNER.run_case(case, RUNNER.EvalContext())
        self.assertNotEqual(RUNNER.result_signature(first),
                            RUNNER.result_signature(second))

    def test_a_peer_reading_the_donor_tool_ledger_is_caught(self):
        from bi_agent.web import session as session_module

        shared = session_module.ToolExecutionLedger("session:shared")

        def _factory(*args, **kwargs):
            return shared

        self._run_with("ANA-ISORP-001",
                       [(session_module, "ToolExecutionLedger", _factory)],
                       "isolation.leak.no_shared_tool_records")


if __name__ == "__main__":
    unittest.main()
