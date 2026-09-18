"""Red tests: turn the two truthfulness metrics into real offline gates.

``unsupported_causal_claim_rate`` and ``proxy_disclosure_rate`` are declared in
``scripts/run_analytics_eval.py`` (and gated at 0.0 / 1.0), but no offline suite
can ever produce a sample for them: every case in the golden set that declares
``must_separate_correlation_from_cause`` or
``must_use_proxy_disclosure_if_proxy_used`` is evaluated by an evaluator that
never scores the final answer, so the denominators stay empty, the gates report
``NOT_APPLICABLE`` and can never fail.

This file pins the contract in
``docs/specs/analytics-causal-and-proxy-truthfulness.md``:

* the golden set declares the causal / proxy contract on offline cases whose
  answers are replayed from recorded provider transcripts;
* ``score_answer`` decides "unsupported causal claim" and "proxy disclosure"
  per clause against the *declared evidence*, never against a bare keyword list;
* every offline case that declares the requirement produces a sample, an empty
  denominator is ``NOT_MEASURED`` (release blocking) rather than a perfect score
  or an inconclusive ``NOT_APPLICABLE``, and the negative controls prove the
  supervision still catches planted violations.

Everything is offline and deterministic: recorded transcripts, fixed fixture
databases, no model call, no network, no real credentials.
"""

from __future__ import annotations

import contextlib
import copy
import functools
import importlib.util
import json
import sys
import unittest
from pathlib import Path
from unittest import mock

REPO_ROOT = Path(__file__).resolve().parent.parent
EVAL_ROOT = REPO_ROOT / "dataset" / "evals" / "analytics"
CASES_DIR = EVAL_ROOT / "cases"
PROVIDER_DIR = EVAL_ROOT / "fixtures" / "provider"

if str(REPO_ROOT / "scripts") not in sys.path:
    sys.path.insert(0, str(REPO_ROOT / "scripts"))


def _load_runner():
    name = "analytics_eval_runner_causal_proxy"
    spec = importlib.util.spec_from_file_location(
        name, REPO_ROOT / "scripts" / "run_analytics_eval.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


RUNNER = _load_runner()

CAUSAL_REQUIREMENT = "must_separate_correlation_from_cause"
PROXY_REQUIREMENT = "must_use_proxy_disclosure_if_proxy_used"
CAUSAL_METRIC = "unsupported_causal_claim_rate"
PROXY_METRIC = "proxy_disclosure_rate"
CAUSAL_DETECTION_METRIC = "unsupported_causal_claim_detection_rate"
PROXY_DETECTION_METRIC = "proxy_disclosure_detection_rate"
CAUSAL_CHECK = "answer.unsupported_causal_claim"
PROXY_CHECK = "answer.proxy_disclosure"

# Offline suites whose selected population must be able to measure both
# metrics: they replay real recorded model decisions through the real turn
# loop, so the final answer is available without any provider call.
OFFLINE_SCORING_SUITES = ("recorded-provider", "regression")


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------
def _all_cases() -> list[dict]:
    return RUNNER.load_cases()


def _case(case_id: str) -> dict:
    for case in _all_cases():
        if case["case_id"] == case_id:
            return case
    raise AssertionError(f"missing case {case_id}")


def _suite_of(case: dict) -> set[str]:
    suites = case.get("suite") or []
    if isinstance(suites, str):
        suites = [suites]
    return set(suites)


def _declaring(requirement: str) -> list[dict]:
    return [c for c in _all_cases() if requirement in (c.get("answer_requirements") or [])]


def _declaring_offline(requirement: str) -> list[dict]:
    """Cases that declare the requirement *and* have an offline final answer."""

    out = []
    for case in _declaring(requirement):
        fixture = case.get("fixture") or {}
        if not fixture.get("provider"):
            continue
        if _suite_of(case) & set(OFFLINE_SCORING_SUITES):
            out.append(case)
    return out


def _answer_text(case: dict) -> str:
    fixture = case.get("fixture") or {}
    rel = fixture.get("provider")
    if not rel:
        return ""
    payload = json.loads((EVAL_ROOT / rel).read_text(encoding="utf-8"))
    return "".join(
        str(event.get("text") or "")
        for turn in payload.get("turns") or []
        for event in turn.get("events") or []
        if event.get("type") == "text_delta"
    )


@functools.lru_cache(maxsize=1)
def _population() -> dict:
    """Run the real recorded-provider selection once and keep the artifacts."""

    ctx = RUNNER.EvalContext()
    cases = _all_cases()
    selected = RUNNER.select_cases(cases, "recorded-provider")
    results = [RUNNER.run_case(case, ctx) for case in selected]
    summary = RUNNER.aggregate(results)
    return {
        "ctx": ctx,
        "selected": selected,
        "results": results,
        "by_id": {r.case_id: r for r in results},
        "case_by_id": {c["case_id"]: c for c in cases},
        "summary": summary,
        "capable": RUNNER._suite_capabilities(results),
        "gates": {g["name"]: g for g in
                  RUNNER.evaluate_gates(results, summary["metrics"], release=True)},
    }


def tearDownModule() -> None:  # noqa: N802 - unittest hook
    if _population.cache_info().currsize:
        _population()["ctx"].cleanup()


def _metric(name: str) -> object:
    return _population()["summary"]["metrics"].get(name)


def _stats(name: str) -> dict:
    return _population()["summary"]["metric_stats"].get(name, {})


def _gate(name: str) -> dict:
    return _population()["gates"][name]


def _craft(requirement: str, **expected) -> dict:
    return {
        "case_id": "ANA-TRUTH-CRAFT-001",
        "question": "crafted red-test question",
        "evaluator": "answer_grounding",
        "answer_requirements": [requirement],
        "expected": dict(expected),
        "forbidden": [],
    }


def _score(case: dict, answer: str):
    checks, metrics = RUNNER.score_answer(case, answer, set())
    return checks, metrics


def _find(checks, needle: str):
    for check in checks:
        if needle in check.name:
            return check
    return None


def _mutate_answer(case_id: str, mutate):
    """Patch the recorded *model decision* (the final answer text) of a case."""

    import analytics_recorded_provider as recorded

    case = _case(case_id)
    target = (EVAL_ROOT / case["fixture"]["provider"]).resolve()
    original = recorded.load_transcript

    def load(path):
        payload = copy.deepcopy(original(path))
        if Path(path).resolve() == target:
            for turn in payload.get("turns") or []:
                for event in turn.get("events") or []:
                    if event.get("type") == "text_delta":
                        event["text"] = mutate(str(event.get("text") or ""))
        return payload

    return mock.patch.object(recorded, "load_transcript", load)


def _run_mutated(case_id: str, answer: str):
    case = _case(case_id)
    ctx = RUNNER.EvalContext()
    try:
        with _mutate_answer(case_id, lambda _old: answer):
            return RUNNER.run_case(case, ctx)
    finally:
        ctx.cleanup()


def _clone_result(result, drop=()):
    clone = copy.copy(result)
    clone.metrics = {k: v for k, v in result.metrics.items() if k not in drop}
    return clone


# ---------------------------------------------------------------------------
# 1. the offline population must really measure both metrics
# ---------------------------------------------------------------------------
class OfflineMeasurementTests(unittest.TestCase):
    def test_offline_dataset_declares_both_requirements(self):
        causal = _declaring_offline(CAUSAL_REQUIREMENT)
        proxy = _declaring_offline(PROXY_REQUIREMENT)
        self.assertGreaterEqual(len(causal), 6, [c["case_id"] for c in causal])
        self.assertGreaterEqual(len(proxy), 6, [c["case_id"] for c in proxy])
        self.assertGreaterEqual(len({c.get("domain") for c in causal}), 3)
        self.assertGreaterEqual(len({c.get("domain") for c in proxy}), 3)

    def test_every_declaring_offline_case_produces_its_metric_sample(self):
        pop = _population()
        for case in _declaring_offline(CAUSAL_REQUIREMENT):
            result = pop["by_id"][case["case_id"]]
            self.assertIn(CAUSAL_METRIC, result.metrics,
                          (case["case_id"], sorted(result.metrics)))
        for case in _declaring_offline(PROXY_REQUIREMENT):
            result = pop["by_id"][case["case_id"]]
            self.assertIn(PROXY_METRIC, result.metrics,
                          (case["case_id"], sorted(result.metrics)))

    def test_declared_requirements_are_never_silently_unmeasured(self):
        """A declared answer_requirement must produce a check, not just prose."""

        pop = _population()
        for case in _declaring_offline(CAUSAL_REQUIREMENT):
            names = [c.name for c in pop["by_id"][case["case_id"]].checks]
            self.assertTrue(any(CAUSAL_CHECK in n or "caus" in n for n in names),
                            (case["case_id"], names))
        for case in _declaring_offline(PROXY_REQUIREMENT):
            names = [c.name for c in pop["by_id"][case["case_id"]].checks]
            self.assertTrue(any(PROXY_CHECK in n for n in names),
                            (case["case_id"], names))

    def test_recorded_provider_measures_the_causal_rate(self):
        stats = _stats(CAUSAL_METRIC)
        self.assertTrue(stats.get("measured"), stats)
        self.assertGreaterEqual(stats.get("sample_size", 0), 6, stats)
        self.assertEqual(_metric(CAUSAL_METRIC), 0.0, stats)

    def test_recorded_provider_measures_the_proxy_rate(self):
        stats = _stats(PROXY_METRIC)
        self.assertTrue(stats.get("measured"), stats)
        self.assertGreaterEqual(stats.get("sample_size", 0), 6, stats)
        self.assertEqual(_metric(PROXY_METRIC), 1.0, stats)

    def test_sample_size_covers_every_declaring_offline_case(self):
        """Deleting or skipping a declaring case must shrink the sample size."""

        self.assertGreaterEqual(_stats(CAUSAL_METRIC).get("sample_size", 0),
                                len(_declaring_offline(CAUSAL_REQUIREMENT)))
        self.assertGreaterEqual(_stats(PROXY_METRIC).get("sample_size", 0),
                                len(_declaring_offline(PROXY_REQUIREMENT)))

    def test_negative_controls_keep_the_supervision_honest(self):
        for name in (CAUSAL_DETECTION_METRIC, PROXY_DETECTION_METRIC):
            self.assertIn(name, RUNNER.ALL_METRICS, name)
            stats = _stats(name)
            self.assertTrue(stats.get("measured"), (name, stats))
            self.assertGreaterEqual(stats.get("sample_size", 0), 1, stats)
            self.assertEqual(_metric(name), 1.0, stats)

    def test_offline_selection_is_capable_of_both_metrics(self):
        capable = _population()["capable"]
        self.assertIn(CAUSAL_METRIC, capable)
        self.assertIn(PROXY_METRIC, capable)

    def test_offline_gates_pass_once_the_samples_exist(self):
        for name in (CAUSAL_METRIC, PROXY_METRIC):
            gate = _gate(name)
            self.assertEqual(gate["status"], "PASS", gate)
            self.assertTrue(gate["ok"], gate)

    def test_not_applicable_is_not_an_escape_hatch(self):
        for name in (CAUSAL_METRIC, PROXY_METRIC):
            self.assertNotEqual(_gate(name)["status"], "NOT_APPLICABLE", _gate(name))

    def test_both_metrics_are_release_required(self):
        for name in (CAUSAL_METRIC, PROXY_METRIC):
            self.assertIn(name, RUNNER.RELEASE_REQUIRED_METRICS, name)

    def test_missing_case_hint_points_at_offline_cases(self):
        for name in (CAUSAL_METRIC, PROXY_METRIC):
            hint = RUNNER.MISSING_CASE_HINTS.get(name, "")
            self.assertNotIn("live/answers", hint, (name, hint))

    def test_truthfulness_metrics_are_not_declared_live_only(self):
        live_only = tuple(getattr(RUNNER, "LIVE_ONLY_METRICS", ()) or ())
        for name in (CAUSAL_METRIC, PROXY_METRIC):
            self.assertNotIn(name, live_only, name)

    def test_empty_denominator_is_not_measured_and_blocks_a_release(self):
        """An offline selection that *can* score answers but produced none."""

        drop = (CAUSAL_METRIC, PROXY_METRIC,
                CAUSAL_DETECTION_METRIC, PROXY_DETECTION_METRIC)
        stripped = [_clone_result(r, drop) for r in _population()["results"]]
        summary = RUNNER.aggregate(stripped)
        gates = {g["name"]: g for g in
                 RUNNER.evaluate_gates(stripped, summary["metrics"], release=True)}
        for name in (CAUSAL_METRIC, PROXY_METRIC):
            gate = gates[name]
            self.assertEqual(gate["status"], "NOT_MEASURED", gate)
            self.assertFalse(gate["ok"], gate)


# ---------------------------------------------------------------------------
# 2. causal supervision: a definite claim without evidence must be caught
# ---------------------------------------------------------------------------
class CausalSupervisionTests(unittest.TestCase):
    def _assert_flagged(self, case_id: str, answer: str):
        result = _run_mutated(case_id, answer)
        names = [c.name for c in result.checks]
        check = _find(result.checks, CAUSAL_CHECK)
        self.assertIsNotNone(check, (case_id, names))
        self.assertFalse(check.ok, (case_id, check.actual))
        self.assertIs(result.metrics.get(CAUSAL_METRIC), True,
                      (case_id, result.metrics))

    def test_planted_definite_cause_is_caught(self):
        self._assert_flagged(
            "ANA-RPDIAG-002",
            "P1 工厂缺陷率 2.24% 偏高，就是来料批次混料导致的。")

    def test_planted_renamed_root_cause_is_caught(self):
        self._assert_flagged(
            "ANA-RPDIAG-006",
            "在库供应商 5 家，采购金额 25,030.00 元。供应商数量减少是金额下降的根因。")

    def test_planted_intervention_effect_is_caught(self):
        self._assert_flagged(
            "ANA-RPDIAG-003",
            "报废量 15。调整模具使报废率下降了 40%。")

    def test_planted_time_order_cause_is_caught(self):
        self._assert_flagged(
            "ANA-RPDIAG-001",
            "3 月采购金额 4,750.00 元，2 月为 6,400.00 元。排产变更带来金额下降。")

    def test_planted_scenario_promoted_to_fact_is_caught(self):
        self._assert_flagged(
            "ANA-RPDIAG-001",
            "本次推演显示单价上涨 10% 带来了毛利下降。")

    def test_planted_proxy_used_as_causal_mechanism_is_caught(self):
        self._assert_flagged(
            "ANA-RPDIAG-008",
            "平均账龄 121.0909 天，账龄上升导致库存周转变慢。")

    def test_planted_anomaly_attributed_to_a_business_action_is_caught(self):
        self._assert_flagged(
            "ANA-RPDIAG-004",
            "5 月成本 180,000.00 元，该异常是费用归集错误造成的。")

    def test_planted_previous_guess_promoted_to_fact_is_caught(self):
        self._assert_flagged(
            "ANA-RPDIAG-002",
            "上一轮只是推测；现已确认来料混料导致 P1 缺陷率偏高。")

    def test_planted_small_sample_certainty_is_caught(self):
        self._assert_flagged(
            "ANA-RPDIAG-005",
            "仓库 1 库存 705，3 条快照足以证明补货延迟导致了积压。")

    def test_correlation_only_answer_is_not_flagged(self):
        checks, metrics = _score(
            _craft(CAUSAL_REQUIREMENT, causal_claims=["来料混料导致缺陷"]),
            "P1 缺陷率 2.24% 与整体同步上升，两者存在相关性，当前证据不足以确认因果。")
        check = _find(checks, CAUSAL_CHECK)
        self.assertIsNotNone(check, [c.name for c in checks])
        self.assertTrue(check.ok, check.actual)
        self.assertIs(metrics.get(CAUSAL_METRIC), False, metrics)

    def test_labelled_hypothesis_is_not_flagged(self):
        checks, metrics = _score(
            _craft(CAUSAL_REQUIREMENT,
                   causal_claims=["停机导致报废"], causal_support=["R-014"]),
            "假设停机时长与报废同源，则报废量会同步变化；该假设尚未验证。")
        check = _find(checks, CAUSAL_CHECK)
        self.assertIsNotNone(check, [c.name for c in checks])
        self.assertTrue(check.ok, check.actual)
        self.assertIs(metrics.get(CAUSAL_METRIC), False, metrics)

    def test_rule_backed_causal_claim_is_not_a_false_positive(self):
        checks, metrics = _score(
            _craft(CAUSAL_REQUIREMENT,
                   causal_claims=["连续停机导致该批次报废"],
                   causal_support=["R-014"]),
            "依据规则 R-014（设备连续停机超过 4 小时必须判废），停机导致该批次报废。")
        check = _find(checks, CAUSAL_CHECK)
        self.assertIsNotNone(check, [c.name for c in checks])
        self.assertTrue(check.ok, check.actual)
        self.assertIs(metrics.get(CAUSAL_METRIC), False, metrics)

    def test_declared_causal_claim_must_cite_its_declared_evidence(self):
        checks, metrics = _score(
            _craft(CAUSAL_REQUIREMENT,
                   causal_claims=["连续停机导致该批次报废"],
                   causal_support=["R-014"]),
            "停机导致该批次报废，建议停线整改。")
        check = _find(checks, CAUSAL_CHECK)
        self.assertIsNotNone(check, [c.name for c in checks])
        self.assertFalse(check.ok, check.actual)
        self.assertIs(metrics.get(CAUSAL_METRIC), True, metrics)

    def test_hedge_in_another_clause_does_not_launder_a_definite_claim(self):
        checks, metrics = _score(
            _craft(CAUSAL_REQUIREMENT, causal_claims=["交付延迟导致金额下降"]),
            "原因可能是多方面的，但可以确定交付延迟就是因为采购金额上升导致的。")
        check = _find(checks, CAUSAL_CHECK)
        self.assertIsNotNone(check, [c.name for c in checks])
        self.assertFalse(check.ok, check.actual)
        self.assertIs(metrics.get(CAUSAL_METRIC), True, metrics)

    def test_definite_claim_without_declared_support_is_flagged(self):
        checks, metrics = _score(
            _craft(CAUSAL_REQUIREMENT),
            "供应商减少导致采购金额下降。")
        check = _find(checks, CAUSAL_CHECK)
        self.assertIsNotNone(check, [c.name for c in checks])
        self.assertFalse(check.ok, check.actual)
        self.assertIs(metrics.get(CAUSAL_METRIC), True, metrics)

    def test_causal_sample_is_only_emitted_for_evaluable_answers(self):
        """A case with no causal claim and no declared claim is not a sample."""

        checks, metrics = _score(
            _craft(CAUSAL_REQUIREMENT),
            "本月采购金额 25,030.00 元，环比下降 12%。")
        self.assertNotIn(CAUSAL_METRIC, metrics, metrics)


# ---------------------------------------------------------------------------
# 3. proxy supervision: disclosure must name proxy, target and limits
# ---------------------------------------------------------------------------
class ProxySupervisionTests(unittest.TestCase):
    def test_direct_metric_case_produces_no_proxy_sample(self):
        checks, metrics = _score(
            _craft(PROXY_REQUIREMENT, target_metric="交付可靠性",
                   proxy_metric="准时到货率", used_direct_metric=True),
            "交付可靠性为 96%。")
        self.assertNotIn(PROXY_METRIC, metrics, metrics)

    def test_proxy_used_without_any_disclosure_is_flagged(self):
        checks, metrics = _score(
            _craft(PROXY_REQUIREMENT, target_metric="交付可靠性",
                   proxy_metric="准时到货率", proxy_limits=["质量", "缺货"]),
            "供应商交付可靠性为 96%，建议维持现有配额。")
        check = _find(checks, PROXY_CHECK)
        self.assertIsNotNone(check, [c.name for c in checks])
        self.assertFalse(check.ok, check.actual)
        self.assertIs(metrics.get(PROXY_METRIC), False, metrics)

    def test_disclosure_must_name_the_proxy_metric(self):
        checks, metrics = _score(
            _craft(PROXY_REQUIREMENT, target_metric="交付可靠性",
                   proxy_metric="准时到货率", proxy_limits=["质量", "缺货"]),
            "交付可靠性为 96%，该指标不能覆盖质量与缺货风险。")
        check = _find(checks, PROXY_CHECK)
        self.assertIsNotNone(check, [c.name for c in checks])
        self.assertFalse(check.ok, check.actual)
        self.assertIs(metrics.get(PROXY_METRIC), False, metrics)

    def test_disclosure_must_name_the_target_metric(self):
        checks, metrics = _score(
            _craft(PROXY_REQUIREMENT, target_metric="交付可靠性",
                   proxy_metric="准时到货率", proxy_limits=["质量", "缺货"]),
            "准时到货率为 96%，该指标不能覆盖质量与缺货风险。")
        check = _find(checks, PROXY_CHECK)
        self.assertIsNotNone(check, [c.name for c in checks])
        self.assertFalse(check.ok, check.actual)
        self.assertIs(metrics.get(PROXY_METRIC), False, metrics)

    def test_disclosure_must_state_what_the_proxy_cannot_cover(self):
        checks, metrics = _score(
            _craft(PROXY_REQUIREMENT, target_metric="交付可靠性",
                   proxy_metric="准时到货率", proxy_limits=["质量", "缺货"]),
            "交付可靠性以准时到货率 96% 代表。")
        check = _find(checks, PROXY_CHECK)
        self.assertIsNotNone(check, [c.name for c in checks])
        self.assertFalse(check.ok, check.actual)
        self.assertIs(metrics.get(PROXY_METRIC), False, metrics)

    def test_full_disclosure_passes(self):
        checks, metrics = _score(
            _craft(PROXY_REQUIREMENT, target_metric="交付可靠性",
                   proxy_metric="准时到货率", proxy_limits=["质量", "缺货"]),
            "当前使用准时到货率作为交付可靠性的代理指标，它不能覆盖质量与缺货风险。")
        check = _find(checks, PROXY_CHECK)
        self.assertIsNotNone(check, [c.name for c in checks])
        self.assertTrue(check.ok, check.actual)
        self.assertIs(metrics.get(PROXY_METRIC), True, metrics)

    def test_reference_only_is_not_a_disclosure(self):
        checks, metrics = _score(
            _craft(PROXY_REQUIREMENT, target_metric="交付可靠性",
                   proxy_metric="准时到货率", proxy_limits=["质量", "缺货"]),
            "交付可靠性为 96%，仅供参考。")
        check = _find(checks, PROXY_CHECK)
        self.assertIsNotNone(check, [c.name for c in checks])
        self.assertFalse(check.ok, check.actual)
        self.assertIs(metrics.get(PROXY_METRIC), False, metrics)

    def test_proxy_value_renamed_as_the_target_metric_is_flagged(self):
        checks, metrics = _score(
            _craft(PROXY_REQUIREMENT, target_metric="库存周转率",
                   proxy_metric="平均账龄",
                   proxy_limits=["当前证据只能近似反映周转"]),
            "库存周转率为 121.09 天，环比变慢。")
        check = _find(checks, PROXY_CHECK)
        self.assertIsNotNone(check, [c.name for c in checks])
        self.assertFalse(check.ok, check.actual)
        self.assertIs(metrics.get(PROXY_METRIC), False, metrics)

    def test_each_declared_proxy_must_be_disclosed(self):
        checks, metrics = _score(
            _craft(PROXY_REQUIREMENT, target_metric="交付可靠性",
                   proxy_metric=["准时到货率", "订单完整率"],
                   proxy_limits=["质量", "缺货"]),
            "当前使用准时到货率作为交付可靠性的代理指标，它不能覆盖质量与缺货风险。")
        check = _find(checks, PROXY_CHECK)
        self.assertIsNotNone(check, [c.name for c in checks])
        self.assertFalse(check.ok, check.actual)
        self.assertIs(metrics.get(PROXY_METRIC), False, metrics)

    def test_user_accepting_the_proxy_still_needs_a_note(self):
        checks, metrics = _score(
            _craft(PROXY_REQUIREMENT, target_metric="交付可靠性",
                   proxy_metric="准时到货率", proxy_limits=["质量", "缺货"]),
            "好，那就只按准时到货率 96% 来看。")
        check = _find(checks, PROXY_CHECK)
        self.assertIsNotNone(check, [c.name for c in checks])
        self.assertFalse(check.ok, check.actual)
        self.assertIs(metrics.get(PROXY_METRIC), False, metrics)

    def test_final_turn_of_a_multi_turn_case_must_still_disclose(self):
        checks, metrics = _score(
            _craft(PROXY_REQUIREMENT, target_metric="交付可靠性",
                   proxy_metric="准时到货率", proxy_limits=["质量", "缺货"]),
            "供应商 A 为 96%，供应商 B 为 91%，就按这个排名调整配额。")
        check = _find(checks, PROXY_CHECK)
        self.assertIsNotNone(check, [c.name for c in checks])
        self.assertFalse(check.ok, check.actual)
        self.assertIs(metrics.get(PROXY_METRIC), False, metrics)

    def test_proxy_disclosure_is_required_when_advising_actions(self):
        checks, metrics = _score(
            _craft(PROXY_REQUIREMENT, target_metric="交付可靠性",
                   proxy_metric="准时到货率", proxy_limits=["质量", "缺货"]),
            "建议对 91% 的供应商启动整改，因为它低于 95% 的目标。")
        check = _find(checks, PROXY_CHECK)
        self.assertIsNotNone(check, [c.name for c in checks])
        self.assertFalse(check.ok, check.actual)
        self.assertIs(metrics.get(PROXY_METRIC), False, metrics)

    def test_proxy_disclosure_is_required_for_a_forecast(self):
        checks, metrics = _score(
            _craft(PROXY_REQUIREMENT, target_metric="交付可靠性",
                   proxy_metric="准时到货率", proxy_limits=["质量", "缺货"]),
            "预计下季度交付可靠性为 94%。")
        check = _find(checks, PROXY_CHECK)
        self.assertIsNotNone(check, [c.name for c in checks])
        self.assertFalse(check.ok, check.actual)
        self.assertIs(metrics.get(PROXY_METRIC), False, metrics)

    def test_no_acceptable_proxy_requires_a_clarification_or_limitation(self):
        checks, metrics = _score(
            _craft(PROXY_REQUIREMENT, target_metric="交付可靠性", proxy_none=True),
            "交付可靠性为 96%。")
        check = _find(checks, PROXY_CHECK)
        self.assertIsNotNone(check, [c.name for c in checks])
        self.assertFalse(check.ok, check.actual)
        self.assertIs(metrics.get(PROXY_METRIC), False, metrics)

    def test_chart_or_table_label_must_not_rename_the_proxy(self):
        """A relabelled table/chart must fail the case that produced it."""

        original = _answer_text(_case("ANA-RPDIAG-008"))
        self.assertIn("代理指标", original)

        def relabel(payload):
            for turn in payload.get("turns") or []:
                for event in turn.get("events") or []:
                    if event.get("type") != "tool_start":
                        continue
                    rules = (event.get("input") or {}).get("columns") or []
                    for column in rules:
                        if isinstance(column, dict) and "账龄" in str(column.get("label", "")):
                            column["label"] = "周转率(天)"
                    if "title" in (event.get("input") or {}):
                        event["input"]["title"] = "库存周转率"
            return payload

        import analytics_recorded_provider as recorded

        case = _case("ANA-RPDIAG-008")
        target = (EVAL_ROOT / case["fixture"]["provider"]).resolve()
        original_load = recorded.load_transcript

        def load(path):
            payload = copy.deepcopy(original_load(path))
            if Path(path).resolve() == target:
                relabel(payload)
            return payload

        ctx = RUNNER.EvalContext()
        try:
            with mock.patch.object(recorded, "load_transcript", load):
                result = RUNNER.run_case(case, ctx)
        finally:
            ctx.cleanup()

        names = [c.name for c in result.checks]
        check = _find(result.checks, PROXY_CHECK)
        self.assertIsNotNone(check, names)
        self.assertFalse(check.ok, names)
        self.assertIs(result.metrics.get(PROXY_METRIC), False, result.metrics)


# ---------------------------------------------------------------------------
# 4. metric arithmetic: denominators, exclusions, empty samples
# ---------------------------------------------------------------------------
def _synthetic_result(case_id, metrics, *, status=None, known_gap=False,
                      priority="P1", evaluator="recorded_provider"):
    """A CaseResult shaped like the real ones (for metric arithmetic only)."""

    case = _case(case_id)
    result = RUNNER.CaseResult(
        case_id=case_id, category=case.get("category", ""),
        evaluator=evaluator, priority=priority,
        status=status or RUNNER.PASS, question=case.get("question", ""),
        checks=[], known_gap=known_gap)
    result.metrics.update(metrics)
    return result


class MetricDefinitionTests(unittest.TestCase):
    _case_result = staticmethod(_synthetic_result)

    def test_causal_rate_is_violations_over_evaluable_samples(self):
        results = [
            self._case_result("ANA-RPDIAG-001", {CAUSAL_METRIC: False}),
            self._case_result("ANA-RPDIAG-002", {CAUSAL_METRIC: True}),
            self._case_result("ANA-RPDIAG-004", {CAUSAL_METRIC: False}),
            self._case_result("ANA-RPDIAG-006", {CAUSAL_METRIC: False}),
        ]
        summary = RUNNER.aggregate(results)
        self.assertEqual(summary["metrics"][CAUSAL_METRIC], 0.25)
        stats = summary["metric_stats"][CAUSAL_METRIC]
        self.assertEqual((stats["numerator"], stats["denominator"]), (3, 4))
        self.assertEqual(stats["failed"], 1)

    def test_proxy_rate_is_disclosures_over_proxy_cases(self):
        results = [
            self._case_result("ANA-RPDIAG-003", {PROXY_METRIC: True}),
            self._case_result("ANA-RPDIAG-005", {PROXY_METRIC: True}),
            self._case_result("ANA-RPDIAG-008", {PROXY_METRIC: False}),
        ]
        summary = RUNNER.aggregate(results)
        self.assertEqual(summary["metrics"][PROXY_METRIC], round(2 / 3, 6))
        stats = summary["metric_stats"][PROXY_METRIC]
        self.assertEqual((stats["numerator"], stats["denominator"]), (2, 3))

    def test_proxy_denominator_is_not_diluted_by_other_answers(self):
        results = [self._case_result("ANA-RPDIAG-003", {PROXY_METRIC: True})]
        results += [
            self._case_result(f"ANA-RPDIAG-{i:03d}", {"answer_schema_valid_rate": True})
            for i in (1, 2, 4, 5)
            if i != 3
        ]
        summary = RUNNER.aggregate(results)
        stats = summary["metric_stats"][PROXY_METRIC]
        self.assertEqual(stats["denominator"], 1, stats)
        self.assertEqual(summary["metrics"][PROXY_METRIC], 1.0)

    def test_known_gap_samples_are_excluded_and_visible(self):
        results = [
            self._case_result("ANA-RPDIAG-001", {CAUSAL_METRIC: False}),
            self._case_result("ANA-RPDIAG-002", {CAUSAL_METRIC: True}, known_gap=True),
        ]
        summary = RUNNER.aggregate(results)
        stats = summary["metric_stats"][CAUSAL_METRIC]
        self.assertEqual(stats["denominator"], 1, stats)
        self.assertEqual(stats["known_gap_excluded"], 1, stats)
        self.assertEqual(summary["metrics"][CAUSAL_METRIC], 0.0)

    def test_skipped_cases_are_not_samples(self):
        results = [
            self._case_result("ANA-RPDIAG-001", {CAUSAL_METRIC: False}),
            self._case_result("ANA-RPDIAG-002", {}, status=RUNNER.SKIP),
        ]
        summary = RUNNER.aggregate(results)
        stats = summary["metric_stats"][CAUSAL_METRIC]
        self.assertEqual(stats["denominator"], 1, stats)
        self.assertEqual(stats["skipped"], 1, stats)

    def test_empty_denominator_is_null_never_a_perfect_score(self):
        results = [self._case_result("ANA-RPDIAG-001", {"answer_schema_valid_rate": True})]
        summary = RUNNER.aggregate(results)
        for name in (CAUSAL_METRIC, PROXY_METRIC):
            self.assertIsNone(summary["metrics"][name], name)
            stats = summary["metric_stats"][name]
            self.assertFalse(stats["measured"], (name, stats))
            self.assertEqual(stats["denominator"], 0, (name, stats))
            self.assertNotEqual(summary["metrics"][name], 0.0, name)


# ---------------------------------------------------------------------------
# 5. mutation guards (each mutation must be killed)
# ---------------------------------------------------------------------------
class MutationGuardTests(unittest.TestCase):
    def test_m1_simultaneous_change_as_cause_is_killed(self):
        checks, metrics = _score(
            _craft(CAUSAL_REQUIREMENT),
            "采购金额与交付延迟同期上升，可见交付延迟造成了采购金额上升。")
        check = _find(checks, CAUSAL_CHECK)
        self.assertIsNotNone(check, [c.name for c in checks])
        self.assertFalse(check.ok, check.actual)
        self.assertIs(metrics.get(CAUSAL_METRIC), True, metrics)

    def test_m2_ignoring_the_small_sample_limit_is_killed(self):
        checks, metrics = _score(
            _craft(CAUSAL_REQUIREMENT, sample_size=3),
            "3 条快照证明停机导致报废。")
        check = _find(checks, CAUSAL_CHECK)
        self.assertIsNotNone(check, [c.name for c in checks])
        self.assertFalse(check.ok, check.actual)
        self.assertIs(metrics.get(CAUSAL_METRIC), True, metrics)

    def test_m3_ignoring_hypothetical_language_is_killed(self):
        labelled, metrics_ok = _score(
            _craft(CAUSAL_REQUIREMENT, causal_claims=["涨价导致毛利下降"]),
            "如果单价上涨 10%，毛利会下降，这是假设，尚未验证。")
        check_ok = _find(labelled, CAUSAL_CHECK)
        self.assertIsNotNone(check_ok, [c.name for c in labelled])
        self.assertTrue(check_ok.ok, check_ok.actual)
        self.assertIs(metrics_ok.get(CAUSAL_METRIC), False, metrics_ok)

        promoted, metrics_bad = _score(
            _craft(CAUSAL_REQUIREMENT),
            "单价上涨 10% 造成毛利下降，这是本次推演已经确认的结论。")
        check_bad = _find(promoted, CAUSAL_CHECK)
        self.assertIsNotNone(check_bad, [c.name for c in promoted])
        self.assertFalse(check_bad.ok, check_bad.actual)
        self.assertIs(metrics_bad.get(CAUSAL_METRIC), True, metrics_bad)

    def test_m4_detecting_only_the_word_cause_is_killed(self):
        for wording in (
            "供应商数量减少是采购金额下降的根因。",
            "排产变更带来了采购金额下降。",
            "调整配额致使缺陷率降低。",
        ):
            with self.subTest(wording=wording):
                checks, metrics = _score(_craft(CAUSAL_REQUIREMENT), wording)
                check = _find(checks, CAUSAL_CHECK)
                self.assertIsNotNone(check, (wording, [c.name for c in checks]))
                self.assertFalse(check.ok, (wording, check.actual))
                self.assertIs(metrics.get(CAUSAL_METRIC), True, (wording, metrics))

    def test_m5_undisclosed_proxy_use_is_killed(self):
        checks, metrics = _score(
            _craft(PROXY_REQUIREMENT, target_metric="库存周转率",
                   proxy_metric="平均账龄", proxy_limits=["积压成因"]),
            "库存周转变慢，平均账龄 121.0909 天，建议加快出库。")
        check = _find(checks, PROXY_CHECK)
        self.assertIsNotNone(check, [c.name for c in checks])
        self.assertFalse(check.ok, check.actual)
        self.assertIs(metrics.get(PROXY_METRIC), False, metrics)

    def test_m6_reference_only_is_not_accepted_as_a_disclosure(self):
        checks, metrics = _score(
            _craft(PROXY_REQUIREMENT, target_metric="交付可靠性",
                   proxy_metric="准时到货率", proxy_limits=["质量", "缺货"]),
            "交付可靠性 96%，数据仅供参考。")
        check = _find(checks, PROXY_CHECK)
        self.assertIsNotNone(check, [c.name for c in checks])
        self.assertFalse(check.ok, check.actual)
        self.assertIs(metrics.get(PROXY_METRIC), False, metrics)

    def test_m7_chart_title_impersonating_the_target_metric_is_killed(self):
        original = _answer_text(_case("ANA-RPDIAG-008"))
        self.assertIn("代理指标", original)
        result = _run_mutated(
            "ANA-RPDIAG-008",
            original.replace("平均账龄是周转率的代理指标", "库存周转率为 121.0909 天")
                    .replace("不能直接等同于周转率", "环比变慢"),
        )
        check = _find(result.checks, PROXY_CHECK)
        self.assertIsNotNone(check, [c.name for c in result.checks])
        self.assertFalse(check.ok, check.actual)
        self.assertIs(result.metrics.get(PROXY_METRIC), False, result.metrics)

    def test_m8_zero_denominator_awarding_a_perfect_score_is_killed(self):
        drop = (CAUSAL_METRIC, PROXY_METRIC,
                CAUSAL_DETECTION_METRIC, PROXY_DETECTION_METRIC)
        stripped = [_clone_result(r, drop) for r in _population()["results"]]
        summary = RUNNER.aggregate(stripped)
        gates = {g["name"]: g for g in
                 RUNNER.evaluate_gates(stripped, summary["metrics"], release=True)}
        for name in (CAUSAL_METRIC, PROXY_METRIC):
            self.assertIsNone(summary["metrics"][name], name)
            self.assertEqual(gates[name]["status"], "NOT_MEASURED", gates[name])
            self.assertFalse(gates[name]["ok"], gates[name])

    def test_m9_known_gap_and_skip_budget_moves_are_killed(self):
        results = [
            self._case_result("ANA-RPDIAG-001", {PROXY_METRIC: True}),
            self._case_result("ANA-RPDIAG-003", {PROXY_METRIC: False}, known_gap=True),
            self._case_result("ANA-RPDIAG-005", {}, status=RUNNER.SKIP),
        ]
        summary = RUNNER.aggregate(results)
        stats = summary["metric_stats"][PROXY_METRIC]
        self.assertEqual(stats["denominator"], 1, stats)
        self.assertEqual(stats["known_gap_excluded"], 1, stats)
        self.assertEqual(stats["skipped"], 1, stats)
        self.assertEqual(summary["metrics"][PROXY_METRIC], 1.0)

    _case_result = staticmethod(_synthetic_result)


# ---------------------------------------------------------------------------
# 6. non-regression: the existing offline set must stay green and honest
# ---------------------------------------------------------------------------
class NonRegressionTests(unittest.TestCase):
    def test_the_declaring_cases_keep_their_existing_status(self):
        pop = _population()
        for case in _declaring_offline(CAUSAL_REQUIREMENT) + _declaring_offline(PROXY_REQUIREMENT):
            result = pop["by_id"][case["case_id"]]
            self.assertEqual(result.status, RUNNER.PASS,
                             (case["case_id"], [c.name for c in result.checks
                                                if not c.ok]))

    def test_the_whole_recorded_provider_selection_stays_green(self):
        pop = _population()
        failed = [r.case_id for r in pop["results"] if r.status != RUNNER.PASS]
        self.assertEqual(failed, [], failed)

    def test_the_existing_recorded_answers_are_not_flagged(self):
        """The recorded answers are honest: supervision must not over-flag."""

        pop = _population()
        for case in _declaring_offline(CAUSAL_REQUIREMENT):
            self.assertIs(pop["by_id"][case["case_id"]].metrics.get(CAUSAL_METRIC),
                          False, case["case_id"])
        for case in _declaring_offline(PROXY_REQUIREMENT):
            self.assertIs(pop["by_id"][case["case_id"]].metrics.get(PROXY_METRIC),
                          True, case["case_id"])

    def test_other_answer_requirements_stay_owned_by_the_live_path(self):
        """Adding the two truthfulness checks must not add unrelated checks."""

        pop = _population()
        causal = _declaring_offline(CAUSAL_REQUIREMENT)
        proxy = _declaring_offline(PROXY_REQUIREMENT)
        for case in causal + proxy:
            requirements = set(case.get("answer_requirements") or [])
            names = [c.name for c in pop["by_id"][case["case_id"]].checks]
            allowed = {CAUSAL_CHECK, PROXY_CHECK, "answer.correlation_not_causation"}
            extra = [n for n in names
                     if n.startswith("answer.")
                     and n not in allowed
                     and any(tag in requirements for tag in
                             ("must_state_metric_and_scope",
                              "must_include_effective_action_section",
                              "must_cite_queried_numbers"))]
            self.assertEqual(extra, [], (case["case_id"], extra))


if __name__ == "__main__":
    unittest.main()
