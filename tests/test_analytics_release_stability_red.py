"""Red tests: make release stability a real, gate-able property.

`repeat_stability` is declared in `scripts/run_analytics_eval.py` and reported in
every report, but it is **never gated**: `evaluate_gates` has no
`repeat_stability` gate, the metric is not in `RELEASE_REQUIRED_METRICS`, and the
CI release job runs `--suite smoke --release` *without* `--repeat`.  A run with
five drifting cases (`--suite all --repeat 2 --release`) therefore still exits 0,
and `--release` reports `repeat_stability=not_measured` while claiming a pass.

The measurement itself is also not canonical: the five `ANA-ISO-00x`
(`session_isolation`) cases are flagged unstable although both runs pass and the
only difference is the random 8-hex session id inside `evidence.observations`,
which the Spec lists as a *allowed* variation (session/run id).

This file pins the contract in `docs/specs/analytics-release-stability.md`:

* a `repeat_stability` gate exists, is release-required, and is NOT_MEASURED
  (blocking) when a release run did not repeat;
* a measured drift blocks any run; a repetition that did not execute (skip) is
  never counted as a stable sample and blocks a release;
* the compared fingerprint normalizes session/run ids, timestamps, trace ids,
  sandbox paths, SQL whitespace and JSON key order, while still catching drift in
  intent, route, tools, query scope, numbers, units, refusals, forecast flags,
  proxy/causal disclosure, multi-turn context, answer structure and metrics.

Everything is offline and deterministic: recorded provider transcripts, fixture
databases, no model call, no network, no credentials.
"""

from __future__ import annotations

import contextlib
import copy
import functools
import importlib.util
import io
import json
import re
import sys
import tempfile
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
EVAL_ROOT = REPO_ROOT / "dataset" / "evals" / "analytics"
CI_PATH = REPO_ROOT / ".gitlab-ci.yml"

if str(REPO_ROOT / "scripts") not in sys.path:
    sys.path.insert(0, str(REPO_ROOT / "scripts"))


def _load_runner():
    name = "analytics_eval_runner_stability"
    spec = importlib.util.spec_from_file_location(
        name, REPO_ROOT / "scripts" / "run_analytics_eval.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


RUNNER = _load_runner()

GATE = "repeat_stability"
ISO_CASES = ("ANA-ISO-001", "ANA-ISO-002", "ANA-ISO-003", "ANA-ISO-004", "ANA-ISO-005")


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------
@functools.lru_cache(maxsize=1)
def _context() -> object:
    return RUNNER.EvalContext()


def tearDownModule() -> None:  # noqa: N802 - unittest hook
    if _context.cache_info().currsize:
        _context().cleanup()


@functools.lru_cache(maxsize=1)
def _cases() -> tuple:
    return tuple(RUNNER.load_cases())


def _select(suite: str) -> list[dict]:
    return RUNNER.select_cases(list(_cases()), suite)


@functools.lru_cache(maxsize=4)
def _repeat(suite: str, repeat: int = 2) -> dict:
    return RUNNER.measure_repeat(_select(suite), _context(), repeat)


def _result(case_id="ANA-RED-STABILITY-001", **overrides):
    payload = {
        "case_id": case_id,
        "category": "diagnosis",
        "evaluator": "recorded_provider",
        "priority": "P1",
        "status": RUNNER.PASS,
        "checks": [RUNNER.Check("recorded.replay", True, "a clean replay", "ok")],
        "metrics": {"answer_schema_valid_rate": True},
        "evidence": {},
    }
    payload.update(overrides)
    return RUNNER.CaseResult(**payload)


def _signature(**overrides) -> str:
    return RUNNER.result_signature(_result(**overrides))


def _gate(gates: list[dict], name: str = GATE) -> dict:
    for gate in gates:
        if gate.get("name") == name:
            return gate
    raise AssertionError(f"missing gate {name!r}; gates={[g.get('name') for g in gates]}")


def _gates_for(results, *, release=False, repeat=None):
    summary = RUNNER.aggregate(results)
    if repeat is not None:
        summary = RUNNER.build_report(
            results, "smoke", "team",
            repeat_agreement=(repeat or {}).get("agreement"),
            repeat=repeat, release=release)["summary"]
    return RUNNER.evaluate_gates(results, summary["metrics"], release=release)


def _run_cli(argv: list[str]) -> tuple[int, dict]:
    """Run the real CLI with its report directory redirected to a temp dir."""

    with tempfile.TemporaryDirectory(prefix="stability-cli-") as out:
        buffer = io.StringIO()
        with contextlib.redirect_stdout(buffer):
            code = RUNNER.main(argv + ["--out", out])
        report = json.loads(
            (Path(out) / f"report-{argv[argv.index('--suite') + 1]}.json").read_text(
                encoding="utf-8"))
    return code, report


def _strip_volatile(value):
    """Test-side projection: drop run/session ids, timestamps and paths."""

    hexes = re.compile(r"\b[0-9a-f]{6,40}\b")
    stamps = re.compile(r"\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}:\d{2}[0-9.:+\-Z]*")
    if isinstance(value, dict):
        return {k: _strip_volatile(v) for k, v in sorted(value.items())
                if str(k) not in ("id", "session_id", "run_id", "request_id", "trace_id")}
    if isinstance(value, list):
        return [_strip_volatile(v) for v in value]
    if isinstance(value, str):
        return stamps.sub("<ts>", hexes.sub("<id>", value))
    return value


_CLI_CACHE: dict[tuple, tuple[int, dict]] = {}


def _cli(args: list[str]) -> tuple[int, dict]:
    key = tuple(args)
    if key not in _CLI_CACHE:
        _CLI_CACHE[key] = _run_cli(list(args))
    return _CLI_CACHE[key]


class _CliReportMixin:
    @classmethod
    def _report(cls, args: list[str]) -> dict:
        return _cli(args)[1]

    @classmethod
    def _code(cls, args: list[str]) -> int:
        return _cli(args)[0]


# ---------------------------------------------------------------------------
# 1. the release gate must require a measured, perfect repeat stability
# ---------------------------------------------------------------------------
class ReleaseGateTests(_CliReportMixin, unittest.TestCase):
    def test_repeat_stability_is_a_gate(self):
        gates = _gates_for([])
        self.assertIn(GATE, [g["name"] for g in gates])

    def test_repeat_stability_is_release_required(self):
        self.assertIn(GATE, RUNNER.RELEASE_REQUIRED_METRICS)

    def test_repeat_stability_gate_is_exposed_by_a_real_run(self):
        report = self._report(["--suite", "smoke", "--repeat", "2"])
        gate = _gate(report["gates"])
        self.assertEqual(gate["status"], "PASS", gate)
        stats = report["summary"]["metric_stats"][GATE]
        self.assertTrue(stats["measured"], stats)
        self.assertGreater(stats["sample_size"], 0, stats)
        self.assertEqual(report["summary"]["metrics"][GATE], 1.0, stats)

    def test_release_without_repeat_blocks(self):
        code = self._code(["--suite", "smoke", "--release"])
        report = self._report(["--suite", "smoke", "--release"])
        self.assertNotEqual(code, 0, "a release run without --repeat must not pass")
        gate = _gate(report["gates"])
        self.assertEqual(gate["status"], "NOT_MEASURED", gate)
        self.assertFalse(gate["ok"], gate)

    def test_ordinary_run_without_repeat_stays_non_blocking(self):
        code = self._code(["--suite", "smoke"])
        report = self._report(["--suite", "smoke"])
        self.assertEqual(code, 0)
        gate = _gate(report["gates"])
        self.assertEqual(gate["status"], "NOT_MEASURED", gate)
        self.assertTrue(gate["ok"], gate)

    def test_repeat_one_cannot_pose_as_stable(self):
        code = self._code(["--suite", "smoke", "--repeat", "1"])
        report = self._report(["--suite", "smoke", "--repeat", "1"])
        stats = report["summary"]["metric_stats"][GATE]
        self.assertFalse(stats["measured"], stats)
        self.assertIsNone(report["summary"]["metrics"][GATE], stats)
        self.assertNotEqual(code, 0, "a release-equivalent run must not claim 1.0")
        gate = _gate(report["gates"])
        self.assertNotEqual(gate["status"], "PASS", gate)

    def test_measured_drift_fails_the_gate(self):
        cases = _select("smoke")

        def flaky(case, ctx, override=""):
            result = RUNNER.run_case(case, ctx)
            if result.case_id in ISO_CASES:
                result.status = RUNNER.FAIL
            return result

        report = RUNNER.measure_repeat(cases[:12], _context(), 2, runner=flaky)
        self.assertLess(report["agreement"], 1.0, report)
        summary = RUNNER.build_report([], "smoke", "team",
                                      repeat_agreement=report["agreement"],
                                      repeat=report)["summary"]
        gate = _gate(RUNNER.evaluate_gates([], summary["metrics"], release=False))
        self.assertEqual(gate["status"], "FAIL", gate)
        self.assertFalse(gate["ok"], gate)

    def test_second_run_failure_is_visible_per_case(self):
        cases = _select("smoke")[:12]
        calls: dict[str, int] = {}

        def flaky(case, ctx, override=""):
            case_id = case["case_id"]
            calls[case_id] = calls.get(case_id, 0) + 1
            result = RUNNER.run_case(case, ctx)
            if calls[case_id] > 1 and case_id == cases[0]["case_id"]:
                result.status = RUNNER.FAIL
            return result

        report = RUNNER.measure_repeat(cases, _context(), 2, runner=flaky)
        self.assertIn(cases[0]["case_id"], report["unstable_case_ids"], report)

    def test_second_run_skip_is_not_a_stable_sample(self):
        cases = _select("smoke")[:12]
        calls: dict[str, int] = {}
        target = cases[0]["case_id"]

        def skipper(case, ctx, override=""):
            case_id = case["case_id"]
            calls[case_id] = calls.get(case_id, 0) + 1
            result = RUNNER.run_case(case, ctx)
            if calls[case_id] > 1 and case_id == target:
                result.status = RUNNER.SKIP
            return result

        report = RUNNER.measure_repeat(cases, _context(), 2, runner=skipper)
        skipped = set(report.get("skipped_case_ids") or [])
        self.assertIn(target, skipped, report)
        self.assertNotIn(target, report.get("stable_case_ids") or [], report)
        summary = RUNNER.build_report([], "smoke", "team",
                                      repeat_agreement=report["agreement"],
                                      repeat=report)["summary"]
        gate = _gate(RUNNER.evaluate_gates([], summary["metrics"], release=True))
        self.assertFalse(gate["ok"], gate)

    def test_repeat_report_records_two_executions_per_case(self):
        report = _repeat("smoke")
        self.assertEqual(report["repeat"], 2)
        counts: dict[str, int] = {}
        for run in report["runs"]:
            counts[run["case_id"]] = counts.get(run["case_id"], 0) + 1
        self.assertTrue(counts)
        self.assertEqual(set(counts.values()), {2}, sorted(set(counts.values())))

    def test_fully_skipped_optin_suite_is_not_measured_but_not_a_defect(self):
        results = [
            RUNNER.CaseResult(case_id=c["case_id"], category=c.get("category", ""),
                              evaluator="live", priority=c.get("priority", "P1"),
                              status=RUNNER.SKIP, question=c.get("question", ""))
            for c in _select("smoke")[:5]
        ]
        summary = RUNNER.build_report(
            results, "live", "team", skipped_live="no credentials",
            repeat_agreement=None, repeat={"repeat": 2, "cases": 0,
                                           "agreement": None})["summary"]
        gate = _gate(RUNNER.evaluate_gates(results, summary["metrics"],
                                           release=True, skipped=True))
        self.assertEqual(gate["status"], "NOT_MEASURED", gate)
        self.assertTrue(gate["ok"], gate)

    def test_zero_sample_repeat_is_not_a_perfect_score(self):
        summary = RUNNER.build_report(
            [], "smoke", "team",
            repeat_agreement=1.0,
            repeat={"repeat": 2, "cases": 0, "agreement": 1.0,
                    "stable_cases": 0, "unstable_case_ids": []})["summary"]
        stats = summary["metric_stats"][GATE]
        self.assertFalse(stats["measured"], stats)
        self.assertEqual(stats["sample_size"], 0, stats)
        self.assertIsNone(summary["metrics"][GATE], stats)

    def test_repeat_count_below_two_is_rejected(self):
        report = RUNNER.measure_repeat(_select("smoke")[:8], _context(), 1)
        self.assertIsNone(report["agreement"], report)
        self.assertFalse(report.get("measured", False), report)


# ---------------------------------------------------------------------------
# 2. canonical comparison: allowed variation must not look like drift
# ---------------------------------------------------------------------------
class CanonicalNoiseTests(unittest.TestCase):
    def test_session_id_churn_does_not_change_the_signature(self):
        first = _result(evidence={"observations": [{"created": True}, {"id": "6ac1df67"}]})
        second = _result(evidence={"observations": [{"created": True}, {"id": "d4bb3a17"}]})
        self.assertEqual(RUNNER.result_signature(first), RUNNER.result_signature(second))

    def test_run_id_in_run_meta_does_not_change_the_signature(self):
        first = _result(run_meta={"session_id": "aaaabbbb", "evaluator": "recorded_provider"})
        second = _result(run_meta={"session_id": "ccccdddd", "evaluator": "recorded_provider"})
        self.assertEqual(RUNNER.result_signature(first), RUNNER.result_signature(second))

    def test_timestamp_churn_does_not_change_the_signature(self):
        first = _result(evidence={"answer": "生成时间 2026-09-18T14:51:28+08:00"})
        second = _result(evidence={"answer": "生成时间 2026-09-18T15:02:11+08:00"})
        self.assertEqual(RUNNER.result_signature(first), RUNNER.result_signature(second))

    def test_trace_id_churn_does_not_change_the_signature(self):
        first = _result(evidence={"observations": [{"trace": "0f8c1d2e3a4b5c6d7e8f90a1b2c3d4e5"}]})
        second = _result(evidence={"observations": [{"trace": "1a2b3c4d5e6f708192a3b4c5d6e7f809"}]})
        self.assertEqual(RUNNER.result_signature(first), RUNNER.result_signature(second))

    def test_sandbox_path_does_not_change_the_signature(self):
        first = _result(evidence={"answer": "报告写入 /tmp/analytics-eval-aa11bb/0001-C-001/dataset/charts/x.html"})
        second = _result(evidence={"answer": "报告写入 /tmp/analytics-eval-zz99yy/0007-C-001/dataset/charts/x.html"})
        self.assertEqual(RUNNER.result_signature(first), RUNNER.result_signature(second))

    def test_sql_whitespace_difference_does_not_change_the_signature(self):
        first = _result(evidence={"issued_sql": "SELECT  a , b\nFROM t WHERE x = 1"})
        second = _result(evidence={"issued_sql": "select a,b from t where x=1"})
        self.assertEqual(RUNNER.result_signature(first), RUNNER.result_signature(second))

    def test_json_key_order_does_not_change_the_signature(self):
        first = _result(evidence={"contract": {"b": 2, "a": 1}})
        second = _result(evidence={"contract": {"a": 1, "b": 2}})
        self.assertEqual(RUNNER.result_signature(first), RUNNER.result_signature(second))

    def test_duration_and_cost_churn_does_not_change_the_signature(self):
        first = _result(duration_ms=1.5, run_meta={"cost": 0.01, "tokens": 10})
        second = _result(duration_ms=9.5, run_meta={"cost": 0.09, "tokens": 99})
        self.assertEqual(RUNNER.result_signature(first), RUNNER.result_signature(second))

    def test_real_iso_cases_differ_only_in_identifiers(self):
        selected = {c["case_id"] for c in _select("regression")}
        self.assertTrue(set(ISO_CASES) <= selected, sorted(set(ISO_CASES) - selected))
        repeat = _repeat("regression")
        runs: dict[str, list[dict]] = {}
        for run in repeat["runs"]:
            runs.setdefault(run["case_id"], []).append(run)
        for case_id in ISO_CASES:
            with self.subTest(case_id=case_id):
                pair = runs.get(case_id) or []
                self.assertEqual(len(pair), 2, pair)
                left, right = (_strip_volatile(x["answer_signature"]) for x in pair)
                self.assertEqual(left, right,
                                 (case_id, pair[0]["answer_signature"], pair[1]["answer_signature"]))

    def test_real_smoke_selection_is_perfectly_stable(self):
        report = _repeat("smoke")
        self.assertEqual(report["agreement"], 1.0, report["unstable_case_ids"])
        self.assertEqual(report["unstable_case_ids"], [])

    def test_real_regression_selection_is_perfectly_stable(self):
        report = _repeat("regression")
        self.assertEqual(report["agreement"], 1.0, report["unstable_case_ids"])
        self.assertEqual(report["unstable_case_ids"], [])

    def test_every_selected_case_is_a_sample(self):
        report = _repeat("smoke")
        self.assertEqual(report["cases"], len(_select("smoke")))
        self.assertEqual(len(report.get("skipped_case_ids") or []), 0)


# ---------------------------------------------------------------------------
# 3. semantic drift must still be caught
# ---------------------------------------------------------------------------
class SemanticDriftTests(unittest.TestCase):
    def _assert_differs(self, first: dict, second: dict):
        self.assertNotEqual(RUNNER.result_signature(_result(**first)),
                            RUNNER.result_signature(_result(**second)))

    def test_intent_drift_is_caught(self):
        self._assert_differs({"evidence": {"policy": {"mode": "FACT_QUERY"}}},
                             {"evidence": {"policy": {"mode": "ONTOLOGY_LOOKUP"}}})

    def test_route_drift_is_caught(self):
        self._assert_differs({"evidence": {"intent_level": "L1"}},
                             {"evidence": {"intent_level": "L3"}})

    def test_required_tools_drift_is_caught(self):
        self._assert_differs({"evidence": {"tool_chain": ["Ontology-MetricQuery"]}},
                             {"evidence": {"tool_chain": ["Ontology-FactQuery"]}})

    def test_tool_status_drift_is_caught(self):
        self._assert_differs({"evidence": {"tool_status": ["SUCCEEDED", "SUCCEEDED"]}},
                             {"evidence": {"tool_status": ["SUCCEEDED", "FAILED_FINAL"]}})

    def test_query_scope_drift_is_caught(self):
        self._assert_differs(
            {"evidence": {"resolved_contract": {"filters": ["region = '华东'"]}}},
            {"evidence": {"resolved_contract": {"filters": []}}})

    def test_numeric_result_drift_is_caught(self):
        self._assert_differs({"evidence": {"answer": "采购金额 4,750.00 元"}},
                             {"evidence": {"answer": "采购金额 4,690.00 元"}})

    def test_unit_drift_is_caught(self):
        self._assert_differs({"evidence": {"contract": {"unit": "元"}}},
                             {"evidence": {"contract": {"unit": "万元"}}})

    def test_currency_drift_is_caught(self):
        self._assert_differs({"evidence": {"contract": {"currency": "CNY"}}},
                             {"evidence": {"contract": {"currency": "USD"}}})

    def test_safety_refusal_drift_is_caught(self):
        self._assert_differs(
            {"evidence": {"policy": {"refusal_category": "credential_exfiltration"}}},
            {"evidence": {"policy": {"refusal_category": None}}})

    def test_forecast_classification_drift_is_caught(self):
        self._assert_differs(
            {"evidence": {"policy": {"forecast_kind": "predictive_forecast"}}},
            {"evidence": {"policy": {"forecast_kind": "stored_forecast"}}})

    def test_proxy_disclosure_drift_is_caught(self):
        self._assert_differs({"metrics": {"proxy_disclosure_rate": True}},
                             {"metrics": {"proxy_disclosure_rate": False}})

    def test_causal_limitation_drift_is_caught(self):
        self._assert_differs({"metrics": {"unsupported_causal_claim_rate": False}},
                             {"metrics": {"unsupported_causal_claim_rate": True}})

    def test_multi_turn_context_drift_is_caught(self):
        self._assert_differs({"evidence": {"observations": [{"context": {"org": ["华东"]}}]}},
                             {"evidence": {"observations": [{"context": {"org": []}}]}})

    def test_evidence_coverage_drift_is_caught(self):
        self._assert_differs({"metrics": {"evidence_coverage": True}},
                             {"metrics": {"evidence_coverage": False}})

    def test_answer_schema_drift_is_caught(self):
        self._assert_differs({"metrics": {"answer_schema_valid_rate": True}},
                             {"metrics": {"answer_schema_valid_rate": False}})

    def test_answer_section_drift_is_caught(self):
        self._assert_differs({"evidence": {"answer": "结论：下降。建议：复核。"}},
                             {"evidence": {"answer": "结论：下降。"}})

    def test_chart_semantics_drift_is_caught(self):
        self._assert_differs({"evidence": {"chart_type": "line"}},
                             {"evidence": {"chart_type": "bar"}})

    def test_chart_dimension_drift_is_caught(self):
        self._assert_differs({"evidence": {"chart_params": {"x": "月份", "series": ["采购金额"]}}},
                             {"evidence": {"chart_params": {"x": "供应商", "series": ["采购金额"]}}})

    def test_status_drift_is_caught(self):
        self._assert_differs({"status": RUNNER.PASS}, {"status": RUNNER.FAIL})

    def test_check_outcome_drift_is_caught(self):
        self._assert_differs(
            {"checks": [RUNNER.Check("recorded.replay", True, "ok", "ok")]},
            {"checks": [RUNNER.Check("recorded.replay", False, "ok", "broken")]})

    def test_unsupported_number_drift_is_caught(self):
        self._assert_differs({"evidence": {"unsupported_numbers": []}},
                             {"evidence": {"unsupported_numbers": [1234.0]}})

    def test_planted_cross_session_leak_flips_stability(self):
        cases = [c for c in _select("smoke") if c["case_id"] not in ISO_CASES][:12]
        target = cases[0]["case_id"]
        calls: dict[str, int] = {}

        def leaker(case, ctx, override=""):
            case_id = case["case_id"]
            calls[case_id] = calls.get(case_id, 0) + 1
            result = RUNNER.run_case(case, ctx)
            if calls[case_id] > 1 and case_id == target:
                borrowed = dict(result.evidence or {})
                borrowed["observations"] = [{"present": True, "record": {"count": 987654}}]
                result.evidence = borrowed
            return result

        report = RUNNER.measure_repeat(cases, _context(), 2, runner=leaker)
        self.assertIn(target, report["unstable_case_ids"], report)

    def test_refusal_category_is_stable_for_security_cases(self):
        refusals = [c for c in _select("adversarial")
                    if c.get("evaluator") == "policy"]
        self.assertTrue(refusals)
        report = RUNNER.measure_repeat(refusals, _context(), 2)
        self.assertEqual(report["agreement"], 1.0, report["unstable_case_ids"])

    def test_truthfulness_metrics_survive_a_repeat_run(self):
        collected: list = []
        report = RUNNER.measure_repeat(_select("recorded-provider"), _context(), 2,
                                       collected=collected)
        self.assertEqual(report["agreement"], 1.0, report["unstable_case_ids"])
        summary = RUNNER.aggregate(collected)
        for name, floor in (("unsupported_causal_claim_rate", 6),
                            ("proxy_disclosure_rate", 6),
                            ("unsupported_causal_claim_detection_rate", 1),
                            ("proxy_disclosure_detection_rate", 1)):
            with self.subTest(metric=name):
                stats = summary["metric_stats"][name]
                self.assertTrue(stats["measured"], (name, stats))
                self.assertGreaterEqual(stats["sample_size"], floor, (name, stats))
        self.assertEqual(summary["metrics"]["unsupported_causal_claim_rate"], 0.0)
        self.assertEqual(summary["metrics"]["proxy_disclosure_rate"], 1.0)
        self.assertEqual(summary["metrics"]["unsupported_causal_claim_detection_rate"], 1.0)
        self.assertEqual(summary["metrics"]["proxy_disclosure_detection_rate"], 1.0)

    def test_detection_rate_regression_blocks_release(self):
        metrics = {"proxy_disclosure_detection_rate": 0.5,
                   "unsupported_causal_claim_detection_rate": 1.0}
        gate = _gate(RUNNER.evaluate_gates([], metrics, release=True),
                     "proxy_disclosure_detection_rate")
        self.assertEqual(gate["status"], "FAIL", gate)
        self.assertFalse(gate["ok"], gate)


# ---------------------------------------------------------------------------
# 4. CI policy: normal pipeline stays cheap, release pipeline repeats
# ---------------------------------------------------------------------------
def _ci_jobs() -> dict:
    """A tiny, dependency-free reader for the repository's CI YAML."""

    text = CI_PATH.read_text(encoding="utf-8")
    jobs: dict[str, str] = {}
    current = None
    for line in text.splitlines():
        if line and not line.startswith((" ", "#")) and line.rstrip().endswith(":"):
            current = line.strip().rstrip(":")
            jobs[current] = ""
        elif current is not None:
            jobs[current] += line + "\n"
    return jobs


class CiPolicyTests(unittest.TestCase):
    def test_release_gate_job_actually_repeats(self):
        body = _ci_jobs()["analytics-eval-release-gate"]
        match = re.search(r"--repeat\s+(\d+)", body)
        self.assertIsNotNone(match, body)
        self.assertGreaterEqual(int(match.group(1)), 2, body)

    def test_release_gate_job_keeps_release_flag(self):
        body = _ci_jobs()["analytics-eval-release-gate"]
        self.assertIn("--release", body)

    def test_release_gate_job_is_blocking(self):
        body = _ci_jobs()["analytics-eval-release-gate"]
        self.assertIn("allow_failure: false", body)

    def test_repeat_stability_job_fails_the_pipeline_on_drift(self):
        """Drift must fail this job: either `--release`, or a gate whose
        severity blocks a normal run.  `--no-gate` would hide it."""

        body = _ci_jobs()["analytics-eval-repeat-stability"]
        self.assertIn("--repeat 2", body)
        self.assertNotIn("--no-gate", body)
        gate = _gate(RUNNER.evaluate_gates(
            [], {"repeat_stability": 0.99}, release=False))
        self.assertEqual(gate["status"], "FAIL", gate)
        self.assertFalse(gate["ok"], gate)

    def test_normal_eval_jobs_stay_single_run(self):
        jobs = _ci_jobs()
        for job in ("analytics-eval-smoke", "analytics-eval-regression",
                    "analytics-eval-recorded-provider"):
            with self.subTest(job=job):
                self.assertNotIn("--repeat", jobs[job])

    def test_repeat_scope_is_bounded(self):
        body = _ci_jobs()["analytics-eval-repeat-stability"]
        suite = re.search(r"--suite\s+([a-z-]+)", body)
        self.assertIsNotNone(suite, body)
        self.assertIn(suite.group(1), ("smoke", "recorded-provider", "adversarial"))

    def test_live_canary_stays_manual_and_unavailable_by_default(self):
        body = _ci_jobs()["analytics-eval-live-canary"]
        self.assertIn("when: manual", body)
        self.assertNotIn("TEAM_API_KEY", body)

    def test_release_gate_does_not_use_a_provider(self):
        body = _ci_jobs()["analytics-eval-release-gate"]
        self.assertNotIn("--provider", body)


# ---------------------------------------------------------------------------
# 5. governance: the closed batches must stay closed
# ---------------------------------------------------------------------------
class GovernanceTests(_CliReportMixin, unittest.TestCase):
    def test_known_gap_ratchet_stays_zero(self):
        payload = json.loads((EVAL_ROOT / "known_gap_ratchet.json").read_text(encoding="utf-8"))
        self.assertEqual(payload["known_gap_total"], 0)
        self.assertEqual(payload["p0_known_gap"], 0)

    def test_case_count_and_priorities_are_unchanged(self):
        manifest = json.loads((EVAL_ROOT / "manifest.json").read_text(encoding="utf-8"))
        self.assertEqual(manifest["totals"]["cases"], 570)
        self.assertEqual(manifest["totals"]["by_priority"]["P0"], 147)
        self.assertEqual(manifest["totals"]["known_gap"], 0)

    def test_regression_selection_stays_green_with_p0_intact(self):
        results = [RUNNER.run_case(case, _context()) for case in _select("regression")]
        summary = RUNNER.aggregate(results)
        self.assertEqual(summary["failed"], 0, [r.case_id for r in results if r.status == RUNNER.FAIL][:5])
        self.assertEqual(summary["p0_passed"], summary["p0_total"])
        self.assertEqual(summary["p0_total"], 147)
        self.assertEqual(summary["p0_failed"], 0)

    def test_repeat_run_does_not_change_pass_rates(self):
        report = _repeat("smoke")
        statuses = {run["status"] for run in report["runs"]}
        self.assertEqual(statuses, {RUNNER.PASS}, statuses)

    def test_ordinary_smoke_run_is_unchanged_by_the_new_gate(self):
        code = self._code(["--suite", "smoke"])
        report = self._report(["--suite", "smoke"])
        self.assertEqual(code, 0)
        self.assertEqual(report["summary"]["passed"], report["summary"]["cases"])


if __name__ == "__main__":
    unittest.main()
