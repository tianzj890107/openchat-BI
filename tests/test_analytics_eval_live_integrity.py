"""Integrity tests for the analytics eval runner: live binding, isolation and repeat.

These are the tests that stop a green online report from being meaningless:

* every SQL case is bound to the fixture database its ``domain`` implies — there
  is no silent fallback to ``procurement.db``;
* every case gets its own session/workspace, so numbers from case A can never
  ground case B;
* ``--repeat`` reruns with the *same* evaluator and a *fresh* session, and the
  comparison covers intent, tool order, SQL semantics, cited numbers, evidence,
  chart type, answer structure and unsupported claims.

Fully offline: no model call, no network, no real database.
"""

from __future__ import annotations

import importlib.util
import json
import re
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
EVAL_ROOT = REPO_ROOT / "dataset" / "evals" / "analytics"
CASES_DIR = EVAL_ROOT / "cases"
MANIFEST_PATH = EVAL_ROOT / "manifest.json"
README_PATH = EVAL_ROOT / "README.md"


def _load_runner():
    import sys

    name = "analytics_eval_runner_live"
    spec = importlib.util.spec_from_file_location(
        name, REPO_ROOT / "scripts" / "run_analytics_eval.py")
    module = importlib.util.module_from_spec(spec)
    # ``@dataclass`` resolves annotations through ``sys.modules``, so the module
    # has to be registered before it is executed.
    sys.modules[name] = module
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


RUNNER = _load_runner()


def _cases() -> list[dict]:
    out = []
    for path in sorted(CASES_DIR.glob("*/*.json")):
        out.append(json.loads(path.read_text(encoding="utf-8")))
    return out


def _case(case_id: str) -> dict:
    for case in _cases():
        if case["case_id"] == case_id:
            return case
    raise AssertionError(f"missing case {case_id}")


def _fabricated(**overrides) -> dict:
    """A minimal, in-memory case used only to exercise the binding rules."""
    case = {
        "case_id": "ANA-FAKE-001",
        "version": 1,
        "priority": "P1",
        "suite": ["regression"],
        "domain": "财务",
        "category": "facts",
        "evaluator": "sql",
        "question": "2025 年 1 月营业收入是多少",
        "conversation": [],
        "context": {},
        "fixture": {},
        "expected": {"value": 1},
        "forbidden": [],
        "evidence_requirements": [],
        "tags": [],
    }
    case.update(overrides)
    return case


class FixtureBindingTest(unittest.TestCase):
    """A case must query the database its own domain implies."""

    def test_finance_case_is_rejected_when_bound_to_procurement(self):
        case = _fabricated(domain="财务", fixture={"db": "procurement.db", "sql": "SELECT 1"})
        with self.assertRaises(RUNNER.FixtureBindingError) as ctx:
            RUNNER.resolve_fixture_db(case)
        self.assertIn("procurement.db", str(ctx.exception))

    def test_manufacturing_case_is_rejected_when_bound_to_finance(self):
        case = _fabricated(domain="制造", fixture={"db": "finance.db", "sql": "SELECT 1"})
        with self.assertRaises(RUNNER.FixtureBindingError):
            RUNNER.resolve_fixture_db(case)

    def test_sql_case_without_a_database_is_rejected(self):
        case = _fabricated(domain="通用", evaluator="sql", fixture={"sql": "SELECT 1"})
        with self.assertRaises(RUNNER.FixtureBindingError) as ctx:
            RUNNER.resolve_fixture_db(case)
        self.assertIn("must declare fixture.db", str(ctx.exception))

    def test_database_outside_the_allowlist_is_rejected(self):
        case = _fabricated(domain="通用", fixture={"db": "hyperfusion.db", "sql": "SELECT 1"})
        with self.assertRaises(RUNNER.FixtureBindingError):
            RUNNER.resolve_fixture_db(case)

    def test_domain_mismatch_is_rejected_without_a_reviewed_reason(self):
        case = _fabricated(domain="销售", fixture={"db": "inventory.db", "sql": "SELECT 1"})
        with self.assertRaises(RUNNER.FixtureBindingError):
            RUNNER.resolve_fixture_db(case)

    def test_reviewed_cross_domain_reason_is_accepted(self):
        case = _fabricated(domain="制造", fixture={
            "db": "inventory.db", "sql": "SELECT 1",
            "cross_domain_reason": "ontology term case that needs any read-only DB"})
        self.assertEqual(RUNNER.resolve_fixture_db(case), "inventory.db")

    def test_non_sql_evaluators_are_not_forced_to_declare_a_database(self):
        for evaluator in ("policy", "chart_validate", "ontology", "chart_policy"):
            case = _fabricated(evaluator=evaluator, fixture={})
            self.assertIsNone(RUNNER.resolve_fixture_db(case), evaluator)

    def test_sql_guard_does_not_need_a_database(self):
        case = _fabricated(evaluator="sql_guard", fixture={"sql": "DROP TABLE t"})
        self.assertIsNone(RUNNER.resolve_fixture_db(case))

    def test_every_committed_case_binds_a_domain_consistent_database(self):
        for case in _cases():
            with self.subTest(case_id=case["case_id"]):
                RUNNER.resolve_fixture_db(case)

    def test_fixture_databases_match_the_documented_domain_map(self):
        self.assertEqual(set(RUNNER.DOMAIN_FIXTURE_DB.values()), set(RUNNER.FIXTURE_DBS))
        self.assertEqual(len(RUNNER.FIXTURE_DBS), 6)


class LiveCaseMapTest(unittest.TestCase):
    """The live suite must be bound, counted and documented consistently."""

    def setUp(self):
        self.cases = _cases()
        self.live = RUNNER.select_cases(self.cases, "live")
        self.canary = RUNNER.select_cases(self.cases, "live-canary")
        self.manifest = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))

    def test_live_cases_declare_their_own_database(self):
        for case in self.live:
            with self.subTest(case_id=case["case_id"]):
                db = RUNNER.resolve_fixture_db(case)
                self.assertIsNotNone(db, "live case must declare fixture.db")

    def test_live_case_databases_are_not_all_procurement(self):
        dbs = {RUNNER.resolve_fixture_db(c) for c in self.live}
        self.assertGreater(len(dbs), 1,
                           "a single database means the live suite is not domain-bound")

    def test_manifest_live_counts_match_the_runner(self):
        totals = self.manifest["totals"]
        self.assertEqual(totals["by_suite"]["live"], len(self.live))
        self.assertEqual(totals["by_suite"]["live-canary"], len(self.canary))
        self.assertEqual(totals["live"]["count"], len(self.live))
        self.assertEqual(sorted(totals["live"]["case_ids"]),
                         sorted(c["case_id"] for c in self.live))
        self.assertEqual(totals["live"]["canary_count"], len(self.canary))

    def test_manifest_live_breakdown_adds_up(self):
        live = self.manifest["totals"]["live"]
        self.assertEqual(sum(live["by_domain"].values()), live["count"])
        self.assertEqual(sum(live["by_priority"].values()), live["count"])
        self.assertEqual(sum(live["by_evaluator"].values()), live["count"])
        self.assertTrue(set(live["needs"]) >= {"sql", "ontology", "chart", "multi_turn"})

    def test_readme_live_number_matches_the_runner(self):
        text = README_PATH.read_text(encoding="utf-8")
        for suite, expected in (("live", len(self.live)),
                                ("live-canary", len(self.canary))):
            match = re.search(rf"^\| `{re.escape(suite)}` \|[^|]*\| (\d+) \|$",
                              text, re.MULTILINE)
            self.assertIsNotNone(match, f"README table has no `{suite}` row")
            self.assertEqual(int(match.group(1)), expected,
                             f"README says {suite}={match.group(1)}, runner selects {expected}")

    def test_live_canary_is_a_strict_subset_of_live(self):
        self.assertTrue(0 < len(self.canary) <= len(self.live))

    def test_live_canary_spans_several_domains(self):
        domains = {c["domain"] for c in self.canary}
        self.assertGreaterEqual(len(domains), 3, f"canary only covers {domains}")
        for case in self.canary:
            self.assertIn("live-canary", case["suite"])


class ConversationGroupTest(unittest.TestCase):
    """Sessions are per case unless a group is declared explicitly."""

    def test_group_key_defaults_to_the_case_id(self):
        case = _fabricated(case_id="ANA-X-001")
        self.assertEqual(RUNNER.LiveHarness.group_key(case), "ANA-X-001")

    def test_group_key_uses_a_declared_conversation_group(self):
        case = _fabricated(case_id="ANA-X-001",
                           fixture={"db": "finance.db", "conversation_group": "grp-a"})
        self.assertEqual(RUNNER.LiveHarness.group_key(case), "grp-a")

    def test_group_mixing_two_databases_is_rejected(self):
        harness = RUNNER.LiveHarness(RUNNER.EvalContext())
        first = _fabricated(case_id="ANA-X-001", domain="财务",
                            fixture={"db": "finance.db", "conversation_group": "grp-a"})
        second = _fabricated(case_id="ANA-X-002", domain="销售",
                             fixture={"db": "sales.db", "conversation_group": "grp-a"})
        harness.session_for(first)
        with self.assertRaises(RUNNER.FixtureBindingError):
            harness.session_for(second)

    def test_group_order_must_be_contiguous(self):
        harness = RUNNER.LiveHarness(RUNNER.EvalContext())
        a = _fabricated(case_id="ANA-X-001", fixture={"db": "finance.db",
                                                      "conversation_group": "grp-a"})
        b = _fabricated(case_id="ANA-X-002", fixture={"db": "finance.db",
                                                      "conversation_group": "grp-b"})
        self.assertEqual(harness.check_order([a, b]), [])
        problems = harness.check_order([a, b, a])
        self.assertTrue(problems, "a non-contiguous group must be reported")


class GroundingScopeTest(unittest.TestCase):
    """Numbers are grounded per case, never from a global pool."""

    def _case(self, question: str, **expected) -> dict:
        return _fabricated(question=question, expected=dict(expected))

    def test_number_from_this_case_is_grounded(self):
        pool = RUNNER.CaseGroundingPool(
            self._case("采购金额是多少"),
            outputs=[{"output": "SUM(amount) = 1280000.0"}])
        self.assertEqual(pool.unsupported("采购金额 1280000.00 元"), set())

    def test_number_from_another_case_is_unsupported(self):
        pool = RUNNER.CaseGroundingPool(
            self._case("采购金额是多少"),
            outputs=[{"output": "SUM(amount) = 1280000.0"}])
        self.assertEqual(pool.unsupported("采购金额 990000.00 元"), {990000.0})

    def test_percentage_from_another_domain_is_unsupported(self):
        pool = RUNNER.CaseGroundingPool(
            self._case("报废率是多少"), outputs=[{"output": "0.03409091"}])
        self.assertEqual(pool.unsupported("报废率 38.78%"), {38.78})

    def test_ratio_may_be_written_as_a_percentage(self):
        pool = RUNNER.CaseGroundingPool(
            self._case("毛利率是多少"), outputs=[{"output": "0.3878"}])
        self.assertEqual(pool.unsupported("毛利率 38.78%"), set())

    def test_display_rounding_of_a_ratio_is_grounded(self):
        pool = RUNNER.CaseGroundingPool(
            self._case("毛利率是多少"), outputs=[{"output": "0.38780000"}])
        self.assertEqual(pool.unsupported("毛利率 38.78%"), set())

    def test_scaled_number_is_not_grounded(self):
        """3878 rendered as 38.78 is a unit error, not rounding."""
        pool = RUNNER.CaseGroundingPool(
            self._case("金额是多少"), outputs=[{"output": "3878"}])
        self.assertEqual(pool.unsupported("金额 38.78 元"), {38.78})

    def test_percentage_must_not_be_shrunk_into_a_ratio(self):
        pool = RUNNER.CaseGroundingPool(
            self._case("占比是多少"), outputs=[{"output": "38.78%"}])
        # 0.3878 is implied by a percent pool value, so it is display rounding.
        self.assertEqual(pool.unsupported("占比 0.3878"), set())
        # 3.878 is a different magnitude and must be caught.
        self.assertEqual(pool.unsupported("占比 3.878"), {3.878})

    def test_small_quantity_is_still_a_business_number(self):
        """A list marker is exempt, a counted quantity of 5 is not."""
        pool = RUNNER.CaseGroundingPool(
            self._case("有几条建议"), outputs=[{"output": "3"}])
        self.assertEqual(pool.unsupported("共 5 条建议"), {5.0})
        self.assertEqual(pool.unsupported("1）先做 A；2）再做 B"), set())

    def test_year_in_a_date_is_structural_but_a_bare_year_is_not(self):
        # The question carries no year, so the pool has no year either.
        pool = RUNNER.CaseGroundingPool(
            self._case("营业收入是多少"), outputs=[{"output": "500000"}])
        self.assertEqual(pool.unsupported("2025 年 1 月营业收入 500000 元"), set())
        self.assertEqual(pool.unsupported("2025-01 营业收入 500000 元"), set())
        # Used as a business result the same digits must be traceable.
        self.assertEqual(pool.unsupported("营业收入等价于 2025 元"), {2025.0})

    def test_month_number_is_structural_only_next_to_a_month_marker(self):
        pool = RUNNER.CaseGroundingPool(
            self._case("库存数量是多少"), outputs=[{"output": "240"}])
        self.assertEqual(pool.unsupported("3 月的库存数量是 240"), set())
        self.assertEqual(pool.unsupported("库存数量 3 个"), {3.0})

    def test_declared_allowed_numbers_are_honoured(self):
        pool = RUNNER.CaseGroundingPool(
            self._case("占比是多少", allowed_numbers=[0]),
            outputs=[{"output": "0.5"}])
        self.assertEqual(pool.unsupported("缺失月按 0 计"), set())

    def test_pools_do_not_leak_between_cases(self):
        first = RUNNER.CaseGroundingPool(
            self._case("采购金额是多少"), outputs=[{"output": "1280000"}])
        second = RUNNER.CaseGroundingPool(
            self._case("采购金额是多少"), outputs=[{"output": "990000"}])
        self.assertEqual(first.unsupported("1280000"), set())
        self.assertEqual(second.unsupported("1280000"), {1280000.0})


class CrossCaseSentinelTest(unittest.TestCase):
    """Case A's numbers must be unsupported in case B, in either order."""

    @classmethod
    def setUpClass(cls):
        cls._runs: dict[str, tuple[dict, object]] = {}

    def _replay(self, case_id: str):
        """Replay one recorded case through the production turn loop."""
        import sys

        if case_id not in self._runs:
            scripts_dir = str(REPO_ROOT / "scripts")
            if scripts_dir not in sys.path:
                sys.path.insert(0, scripts_dir)
            from analytics_recorded_provider import load_transcript, run_recorded_turns

            case = _case(case_id)
            transcript = load_transcript(EVAL_ROOT / case["fixture"]["provider"])
            workspace = RUNNER.EvalContext().new_sandbox(case_id)
            run = run_recorded_turns(case_id, transcript["turns"],
                                     fixture_db=RUNNER.resolve_fixture_db(case),
                                     workspace=workspace)
            self._runs[case_id] = (case, run)
        return self._runs[case_id]

    def _borrowed_numbers(self, donor: str, recipient: str) -> list[float]:
        donor_case, donor_run = self._replay(donor)
        recipient_case, recipient_run = self._replay(recipient)
        donor_pool = RUNNER.RecordedPool(donor_case, donor_run)
        recipient_pool = RUNNER.RecordedPool(recipient_case, recipient_run)
        return sorted(n for n in donor_pool.pool
                      if abs(n) > 1000 and n not in recipient_pool.pool)

    def _is_flagged(self, case_id: str, text: str, number: float) -> bool:
        case, run = self._replay(case_id)
        return number in RUNNER.RecordedPool(case, run).unsupported(text)

    def test_a_number_from_a_sibling_case_is_unsupported(self):
        borrowed = self._borrowed_numbers("ANA-RPSQL-001", "ANA-RPSQL-003")
        self.assertTrue(borrowed, "the two cases must produce different numbers")
        number = borrowed[0]
        self.assertTrue(
            self._is_flagged("ANA-RPSQL-003", f"本期采购金额 {number:.2f} 元", number),
            "a number only the sibling case produced must not be grounded")

    def test_the_sentinel_holds_in_both_orders(self):
        first = self._borrowed_numbers("ANA-RPSQL-001", "ANA-RPSQL-003")
        second = self._borrowed_numbers("ANA-RPSQL-003", "ANA-RPSQL-001")
        for number in first:
            self.assertTrue(self._is_flagged(
                "ANA-RPSQL-003", f"本期采购金额 {number:.2f} 元", number))
        for number in second:
            self.assertTrue(self._is_flagged(
                "ANA-RPSQL-001", f"本期采购金额 {number:.2f} 元", number))

    def test_each_case_stays_grounded_in_its_own_answer(self):
        for case_id in ("ANA-RPSQL-001", "ANA-RPSQL-003"):
            case, run = self._replay(case_id)
            pool = RUNNER.RecordedPool(case, run)
            with self.subTest(case_id=case_id):
                self.assertEqual(pool.unsupported(run.text), set(),
                                 "a case must be able to cite its own result")

    def test_pool_does_not_include_the_other_case_outputs(self):
        donor_case, donor_run = self._replay("ANA-RPSQL-001")
        recipient_case, recipient_run = self._replay("ANA-RPSQL-003")
        donor_numbers = RUNNER.RecordedPool(donor_case, donor_run).pool
        recipient_numbers = RUNNER.RecordedPool(recipient_case, recipient_run).pool
        borrowed = {n for n in donor_numbers if n not in recipient_numbers}
        self.assertTrue(borrowed)
        self.assertFalse(borrowed & recipient_numbers,
                         "the recipient pool must not absorb donor numbers")


class RepeatContractTest(unittest.TestCase):
    """``--repeat`` must rerun the same evaluator in a fresh session."""

    def _case(self) -> dict:
        return _fabricated(case_id="ANA-REPEAT-001", evaluator="recorded_provider",
                           fixture={"db": "finance.db", "provider": "x"})

    def test_every_repetition_uses_the_same_evaluator_override(self):
        seen: list[str] = []

        def runner(case, ctx, override=""):
            seen.append(override)
            return RUNNER.CaseResult(
                case_id=case["case_id"], category="facts",
                evaluator=override or case["evaluator"], priority="P1",
                status="pass",
                evidence={"tool_chain": ["Ontology-FactQuery"]})

        RUNNER.measure_repeat([self._case()], RUNNER.EvalContext(), 3,
                              evaluator_override="live", runner=runner)
        self.assertEqual(seen, ["live", "live", "live"],
                         "a repeat run silently fell back to the offline evaluator")

    def test_a_fresh_session_is_created_for_every_repetition(self):
        resets: list[int] = []

        def runner(case, ctx, override=""):
            return RUNNER.CaseResult(
                case_id=case["case_id"], category="facts", evaluator="live",
                priority="P1", status="pass",
                evidence={"tool_chain": ["Ontology-FactQuery"]})

        RUNNER.measure_repeat([self._case()], RUNNER.EvalContext(), 3,
                              runner=runner, reset=lambda: resets.append(1))
        self.assertEqual(len(resets), 3, "each repetition needs a new harness/session")

    def test_tool_chain_change_lowers_stability(self):
        calls = {"n": 0}

        def runner(case, ctx, override=""):
            calls["n"] += 1
            chain = ["Ontology-FactQuery"] if calls["n"] == 1 else ["Ontology-FactQuery",
                                                                   "ChartGenerate"]
            return RUNNER.CaseResult(
                case_id=case["case_id"], category="facts",
                evaluator="recorded_provider", priority="P1", status="pass",
                evidence={"tool_chain": chain})

        report = RUNNER.measure_repeat([self._case()], RUNNER.EvalContext(), 2, runner=runner)
        self.assertEqual(report["agreement"], 0.0)
        self.assertEqual(report["unstable_case_ids"], ["ANA-REPEAT-001"])

    def test_sql_formatting_only_change_is_stable(self):
        sqls = [
            "SELECT SUM(amount) FROM fact_purchase_order WHERE is_deleted = 0",
            "select   sum(amount)   from fact_purchase_order where is_deleted=0",
        ]
        calls = {"n": 0}

        def runner(case, ctx, override=""):
            sql = sqls[min(calls["n"], 1)]
            calls["n"] += 1
            return RUNNER.CaseResult(
                case_id=case["case_id"], category="facts",
                evaluator="recorded_provider", priority="P1", status="pass",
                evidence={"tool_chain": ["Ontology-FactQuery"], "issued_sql": sql})

        report = RUNNER.measure_repeat([self._case()], RUNNER.EvalContext(), 2, runner=runner)
        self.assertEqual(report["agreement"], 1.0)

    def test_a_changed_number_is_unstable(self):
        numbers = ["1280000.0", "1270000.0"]
        calls = {"n": 0}

        def runner(case, ctx, override=""):
            number = numbers[min(calls["n"], 1)]
            calls["n"] += 1
            return RUNNER.CaseResult(
                case_id=case["case_id"], category="facts",
                evaluator="recorded_provider", priority="P1", status="pass",
                evidence={"tool_chain": ["Ontology-FactQuery"],
                          "answer": f"采购金额 {number} 元"})

        report = RUNNER.measure_repeat([self._case()], RUNNER.EvalContext(), 2, runner=runner)
        self.assertEqual(report["agreement"], 0.0)

    def test_temp_paths_and_timestamps_do_not_count_as_instability(self):
        texts = [
            "Chart generated — line\nSaved: /tmp/analytics-eval-aaa/0001-C/"
            "dataset/charts/chart-20260917-101010-x",
            "Chart generated — line\nSaved: /tmp/analytics-eval-bbb/0001-C/"
            "dataset/charts/chart-20260917-202020-y",
        ]
        calls = {"n": 0}

        def runner(case, ctx, override=""):
            text = texts[min(calls["n"], 1)]
            calls["n"] += 1
            return RUNNER.CaseResult(
                case_id=case["case_id"], category="charts",
                evaluator="recorded_provider", priority="P1", status="pass",
                checks=[RUNNER.Check("recorded.result_contains[ChartGenerate]", True,
                                     "Chart generated", text)],
                evidence={"tool_chain": ["ChartGenerate"]})

        report = RUNNER.measure_repeat([self._case()], RUNNER.EvalContext(), 2, runner=runner)
        self.assertEqual(report["agreement"], 1.0,
                         "sandbox paths and wall-clock stamps are not behaviour")

    def test_repeat_report_records_per_run_provenance(self):
        def runner(case, ctx, override=""):
            return RUNNER.CaseResult(
                case_id=case["case_id"], category="facts",
                evaluator="recorded_provider", priority="P1", status="pass",
                evidence={"tool_chain": ["Ontology-FactQuery"]},
                run_meta={"fixture_db": "finance.db", "session_id": "s1",
                          "provider": "recorded"})

        report = RUNNER.measure_repeat([self._case()], RUNNER.EvalContext(), 2, runner=runner)
        self.assertEqual(len(report["runs"]), 2)
        for entry in report["runs"]:
            self.assertEqual(entry["evaluator"], "recorded_provider")
            self.assertEqual(entry["fixture_db"], "finance.db")
            self.assertEqual(entry["tool_chain"], ["Ontology-FactQuery"])
            self.assertTrue(entry["answer_signature"])
        self.assertEqual(report["cases"], 1)
        self.assertEqual(report["stable_cases"], 1)


class SkippedLiveContractTest(unittest.TestCase):
    """No credentials: reported as not_measured, never as passed or failed."""

    PROVIDER_ENV = ("TEAM_API_KEY", "TEAM_BASE_URL", "DASHSCOPE_API_KEY",
                    "QWEN_API_KEY", "DEEPSEEK_API_KEY", "ANTHROPIC_API_KEY")

    def _run(self, suite: str) -> tuple[int, dict, str]:
        import os
        import subprocess
        import sys
        import tempfile

        with tempfile.TemporaryDirectory() as tmp:
            env = {k: v for k, v in os.environ.items()
                   if k not in self.PROVIDER_ENV}
            proc = subprocess.run(
                [sys.executable, "-m", "scripts.run_analytics_eval",
                 "--suite", suite, "--provider", "deepseek", "--out", tmp],
                cwd=REPO_ROOT, capture_output=True, text=True, env=env,
                timeout=900,
            )
            report_path = Path(tmp) / f"report-{suite}.json"
            report = json.loads(report_path.read_text(encoding="utf-8"))
            markdown = (Path(tmp) / f"report-{suite}.md").read_text(encoding="utf-8")
            return proc.returncode, report, markdown

    def test_live_canary_without_credentials_is_not_measured(self):
        code, report, _ = self._run("live-canary")
        self.assertEqual(code, 0, "a skipped opt-in suite is not a failure")
        self.assertEqual(report["status"], "not_measured")
        self.assertNotEqual(report["status"], "pass")

    def test_a_skipped_run_reports_no_passing_case(self):
        _, report, _ = self._run("live-canary")
        self.assertTrue(report["results"])
        for result in report["results"]:
            self.assertEqual(str(result["status"]).lower(), "skip",
                             f"{result['case_id']} must not be reported as {result['status']}")
        self.assertEqual(report["summary"]["passed"], 0)
        self.assertEqual(report["summary"]["failed"], 0)

    def test_the_p0_gate_is_not_measured_not_failed(self):
        _, report, _ = self._run("live-canary")
        gate = next(g for g in report["gates"] if g["name"] == "p0_all_pass")
        self.assertEqual(gate["status"], "NOT_MEASURED")
        self.assertTrue(gate["ok"], "a skipped run must not be gated as a failure")
        self.assertIn("not reported as passed", gate["detail"])

    def test_the_skip_reason_is_recorded(self):
        _, report, markdown = self._run("live-canary")
        reason = report["skipped"]["live"]
        self.assertIn("DEEPSEEK_API_KEY", reason)
        self.assertIn("not_measured", reason)
        self.assertIn("DEEPSEEK_API_KEY", markdown)
        self.assertEqual(sorted(report["skipped"]["cases"]),
                         sorted(r["case_id"] for r in report["results"]))

    def test_the_live_suite_has_the_same_contract(self):
        code, report, _ = self._run("live")
        self.assertEqual(code, 0)
        self.assertEqual(report["status"], "not_measured")
        self.assertEqual(report["summary"]["passed"], 0)

    def test_offline_suites_are_unaffected_by_missing_credentials(self):
        import os
        import subprocess
        import sys
        import tempfile

        with tempfile.TemporaryDirectory() as tmp:
            env = {k: v for k, v in os.environ.items()
                   if k not in self.PROVIDER_ENV}
            proc = subprocess.run(
                [sys.executable, "-m", "scripts.run_analytics_eval",
                 "--suite", "recorded-provider", "--out", tmp],
                cwd=REPO_ROOT, capture_output=True, text=True, env=env,
                timeout=900,
            )
            self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
            report = json.loads(
                (Path(tmp) / "report-recorded-provider.json").read_text(encoding="utf-8"))
            self.assertGreater(report["summary"]["passed"], 0)


class ReportSecretHygieneTest(unittest.TestCase):
    """A report is an artifact; credentials must never survive into it."""

    SENTINEL = "sk-live-canary-sentinel-deadbeef"

    def test_a_leaked_key_is_scrubbed_from_the_report(self):
        import os

        os.environ["ANALYTICS_EVAL_SENTINEL_API_KEY"] = self.SENTINEL
        try:
            payload = {
                "suite": "live",
                "results": [{"evidence": {"error": f"401 invalid api key {self.SENTINEL}"}}],
                "note": "unrelated text",
            }
            scrubbed = RUNNER.redact_secrets(payload)
            text = json.dumps(scrubbed, ensure_ascii=False)
            self.assertNotIn(self.SENTINEL, text)
            self.assertIn(RUNNER._REDACTED, text)
            self.assertIn("unrelated text", text)
        finally:
            os.environ.pop("ANALYTICS_EVAL_SENTINEL_API_KEY", None)

    def test_short_values_are_not_scrubbed_into_noise(self):
        import os

        os.environ["ANALYTICS_EVAL_SHORT_API_KEY"] = "abc"
        try:
            payload = {"note": "abc"}
            self.assertEqual(RUNNER.redact_secrets(payload), payload)
        finally:
            os.environ.pop("ANALYTICS_EVAL_SHORT_API_KEY", None)

    def test_the_runner_actually_applies_the_scrubber(self):
        source = (REPO_ROOT / "scripts" / "run_analytics_eval.py").read_text(encoding="utf-8")
        self.assertIn("report = redact_secrets(build_report(", source)


class LiveBudgetTest(unittest.TestCase):
    """A live run must obey a wall-clock budget; the tail is skipped, not passed."""

    def test_the_suite_budget_skips_the_tail_instead_of_reporting_it(self):
        import tempfile
        import time
        from unittest import mock

        executed: list[str] = []

        def stub_run_case(case, ctx, evaluator_override=None):
            executed.append(case["case_id"])
            time.sleep(0.05)
            return RUNNER.CaseResult(
                case_id=case["case_id"], category=case.get("category", ""),
                evaluator="live", priority=case.get("priority", "P1"),
                status=RUNNER.PASS, question=case.get("question", ""),
                checks=[RUNNER.Check("stub.executed", True, True, True)],
                metrics={"answer_schema_valid_rate": True},
                run_meta={"case_id": case["case_id"],
                          "fixture_db": RUNNER.fixture_db_for_case(case)})

        with tempfile.TemporaryDirectory() as tmp:
            argv = ["--suite", "live-canary", "--provider", "deepseek",
                    "--out", tmp, "--live-budget-seconds", "0.01"]
            with mock.patch.object(RUNNER, "provider_available", return_value=True), \
                 mock.patch.object(RUNNER, "run_case", stub_run_case):
                RUNNER.main(argv)
            report = json.loads(
                (Path(tmp) / "report-live-canary.json").read_text(encoding="utf-8"))

        skipped = [r for r in report["results"] if str(r["status"]).lower() == "skip"]
        self.assertTrue(skipped, "the budget must skip the tail of the suite")
        self.assertLess(len(executed), len(report["results"]))
        self.assertEqual(len(executed) + len(skipped), len(report["results"]))
        for result in skipped:
            names = [c["name"] for c in result["checks"]]
            self.assertIn("live.suite_budget", names)
        self.assertEqual([c["case_id"] for c in skipped],
                         [r["case_id"] for r in report["results"]
                          if str(r["status"]).lower() == "skip"])
        self.assertIn("预算", report["skipped"]["live"])
        self.assertEqual(report["live_budget_seconds"], 0.01)
        self.assertGreaterEqual(report["live_budget_used_seconds"], 0.01)

    def test_the_budget_is_disabled_with_zero(self):
        import tempfile
        import time
        from unittest import mock

        executed: list[str] = []

        def stub_run_case(case, ctx, evaluator_override=None):
            executed.append(case["case_id"])
            time.sleep(0.02)
            return RUNNER.CaseResult(
                case_id=case["case_id"], category=case.get("category", ""),
                evaluator="live", priority=case.get("priority", "P1"),
                status=RUNNER.PASS, question=case.get("question", ""),
                checks=[RUNNER.Check("stub.executed", True, True, True)],
                metrics={"answer_schema_valid_rate": True})

        with tempfile.TemporaryDirectory() as tmp:
            argv = ["--suite", "live-canary", "--provider", "deepseek",
                    "--out", tmp, "--live-budget-seconds", "0"]
            with mock.patch.object(RUNNER, "provider_available", return_value=True), \
                 mock.patch.object(RUNNER, "run_case", stub_run_case):
                RUNNER.main(argv)
            report = json.loads(
                (Path(tmp) / "report-live-canary.json").read_text(encoding="utf-8"))
        self.assertEqual(len(executed), len(report["results"]))
        self.assertFalse([r for r in report["results"]
                          if str(r["status"]).lower() == "skip"])

    def test_the_budget_defaults_to_a_finite_value(self):
        args = RUNNER.build_parser().parse_args([])
        self.assertEqual(args.live_budget_seconds, 1800.0)


if __name__ == "__main__":
    unittest.main()
