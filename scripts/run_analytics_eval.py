#!/usr/bin/env python3
"""Golden-set runner for the ontology agentic-analytics eval suite.

Usage
-----
    python -m scripts.run_analytics_eval --suite smoke
    python -m scripts.run_analytics_eval --suite regression
    python -m scripts.run_analytics_eval --suite multi-turn
    python -m scripts.run_analytics_eval --suite adversarial
    python -m scripts.run_analytics_eval --suite recovery
    python -m scripts.run_analytics_eval --suite ontology
    python -m scripts.run_analytics_eval --suite charts
    python -m scripts.run_analytics_eval --suite recorded-provider
    python -m scripts.run_analytics_eval --suite live --provider deepseek
    python -m scripts.run_analytics_eval --compare baseline.json candidate.json

Safety contract (see dataset/evals/analytics/README.md):

* every fixture database is opened **read-only** (``mode=ro``);
* the runner never writes to ``dataset/conversations``, ``dataset/charts``,
  ``dataset/logs``, ``dataset/databases`` or ``dataset/uploaded_reports``;
* the runner never calls a conversation-delete endpoint;
* the ``live`` suite is explicit, needs provider credentials, and runs every
  turn inside a throw-away workspace directory;
* no API key -> the live suite reports ``skipped`` and the offline suites still
  run;
* the runner never writes a model answer back into the golden set.

Evaluators
----------
======================  ==================================================
``policy``              deterministic Cognitive Policy decision + intent level
``sql``                 reference SQL against the read-only fixture DB
``ontology``            ontology anchors / terms / metrics / relations
``multi_turn``          resolved-turn policy + declarative context contract
``chart_validate``      ``chart_tools._validate`` accept/reject contract
``chart_policy``        chart suppression policy for list-like questions
``chart_html_safety``   HTML escaping of chart title/option
``recovery_state``      scripted ``recovery.RecoveryState`` transitions
``admission``           scripted admission / session-slot behaviour
``sql_guard``           ``sql_tools._validate_sql`` read-only guard
``session_isolation``   conversation store isolation + path/size guards
``live``                real model turn (opt-in, needs credentials)
======================  ==================================================
"""

from __future__ import annotations

import argparse
import json
import re
import shutil
import sqlite3
import statistics
import sys
import tempfile
import threading
import time
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Any, Callable, Optional

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

EVAL_ROOT = REPO_ROOT / "dataset" / "evals" / "analytics"
CASES_DIR = EVAL_ROOT / "cases"
FIXTURE_DIR = EVAL_ROOT / "fixtures"
SQLITE_DIR = FIXTURE_DIR / "sqlite"
ONTOLOGY_DIR = FIXTURE_DIR / "ontology"
DEFAULT_REPORT_DIR = REPO_ROOT / "dataset" / "evals" / "analytics" / "reports"

SUITES = [
    "smoke", "regression", "multi-turn", "adversarial", "recovery",
    "ontology", "charts", "diagnosis", "recorded-provider",
    "live", "live-canary", "all",
]

# The only databases an eval case may query.  A case binds exactly one of them
# through ``fixture.db``; there is deliberately no default, because a silent
# fallback would let a finance case quietly query procurement data and still
# look green.
FIXTURE_DBS = (
    "procurement.db",
    "inventory.db",
    "sales.db",
    "quality.db",
    "finance.db",
    "manufacturing.db",
)

DOMAIN_FIXTURE_DB = {
    "采购": "procurement.db",
    "库存": "inventory.db",
    "销售": "sales.db",
    "质量": "quality.db",
    "财务": "finance.db",
    "制造": "manufacturing.db",
}

# Evaluators that execute SQL against a fixture database.  A case using one of
# them must declare ``fixture.db`` explicitly.
SQL_EVALUATORS = frozenset({
    "sql", "generated_sql", "recorded_provider", "tool_chain",
    "answer_grounding", "live", "answers", "recorded_session_isolation",
})


class FixtureBindingError(RuntimeError):
    """A case does not declare a legal, domain-consistent fixture database."""


def _case_needs_sql(case: dict) -> bool:
    """Whether this evaluator really executes SQL against a fixture database.

    ``sql_guard`` cases carry a SQL string in their fixture too, but they only
    assert the guard's verdict — they never connect — so the evaluator, not the
    presence of a SQL-looking field, decides.
    """
    return case.get("evaluator") in SQL_EVALUATORS


def resolve_fixture_db(case: dict) -> Optional[str]:
    """The single read-only fixture DB this case is allowed to query.

    Returns ``None`` for cases that provably need no SQL.  Raises
    ``FixtureBindingError`` when a SQL case declares nothing, declares a DB
    outside the allowlist, or declares a DB that contradicts ``case.domain``
    (unless the case records an explicit, reviewed ``cross_domain_reason``).
    """
    fixture = case.get("fixture") or {}
    db = str(fixture.get("db") or "").strip()
    needs_sql = _case_needs_sql(case)
    if not db:
        if needs_sql and fixture.get("sql_required") is not False:
            raise FixtureBindingError(
                f"{case.get('case_id')}: SQL evaluator "
                f"{case.get('evaluator')!r} must declare fixture.db or set "
                f"fixture.sql_required=false")
        return None
    if db not in FIXTURE_DBS:
        raise FixtureBindingError(
            f"{case.get('case_id')}: fixture.db {db!r} is not an allowed "
            f"fixture database {list(FIXTURE_DBS)}")
    expected = DOMAIN_FIXTURE_DB.get(str(case.get("domain") or ""))
    if expected and expected != db:
        reason = str(fixture.get("cross_domain_reason") or "").strip()
        if not reason:
            raise FixtureBindingError(
                f"{case.get('case_id')}: domain {case.get('domain')!r} implies "
                f"{expected} but fixture.db is {db!r}; fix the domain or record "
                f"fixture.cross_domain_reason")
    return db


def fixture_db_for_case(case: dict) -> Optional[str]:
    """Non-raising variant used by reporting: an invalid binding is an error."""
    try:
        return resolve_fixture_db(case)
    except FixtureBindingError:
        return None


# ``pyproject.toml`` must stay PEP 440 (``0.1.3``); the ontology product
# family name is applied here so reports and gates speak the same name the tag,
# the GitLab Release and the UI use (``ontology-v0.1.3``).
PRODUCT_VERSION_PREFIX = "ontology-v"


def product_version() -> str:
    """The released product version as the user-visible ``ontology-vX.Y.Z``."""
    try:
        pyproject = (REPO_ROOT / "pyproject.toml").read_text(encoding="utf-8")
    except OSError:
        return ""
    match = re.search(r'^version\s*=\s*"([^"]+)"', pyproject, re.MULTILINE)
    if not match:
        return ""
    return f"{PRODUCT_VERSION_PREFIX}{match.group(1)}"

PASS = "pass"
FAIL = "fail"
SKIP = "skip"
XFAIL = "xfail"   # known_gap case that still fails -> documented defect, not a gate breach
XPASS = "xpass"   # known_gap case that now passes -> the defect is closed, promote the case

# Mirror of bi_agent.web.session._RECOVERY_STOP_STATUSES: a tool reaching one of
# these ends the turn immediately, without any assistant narrative.
TURN_STOP_STATUSES = frozenset({"FAILED_RETRYABLE", "FAILED_FINAL", "CANCELLED"})

# Metrics that can only be produced by scoring a real/simulated answer.
# ``unsupported_causal_claim_rate`` / ``proxy_disclosure_rate`` are deliberately
# *not* listed: the recorded-provider layer scores the final narrative offline,
# so they are measurable without a provider key.
LIVE_ONLY_METRICS = (
    "unsupported_number_rate",
)

# Metrics whose per-case sample is "a violation happened"; a lower aggregate is
# better, so a single ``False`` sample is the good one.
LOWER_IS_BETTER_METRICS = frozenset({
    "unsupported_number_rate",
    "unsupported_causal_claim_rate",
    "cross_session_leak_rate",
})

ALL_METRICS = (
    "intent_accuracy",
    "tool_route_accuracy",
    "query_contract_accuracy",
    "exact_numeric_accuracy",
    "metric_scope_accuracy",
    "unsupported_number_rate",
    "unsupported_causal_claim_rate",
    "unsupported_causal_claim_detection_rate",
    "evidence_coverage",
    "proxy_disclosure_rate",
    "proxy_disclosure_detection_rate",
    "chart_selection_accuracy",
    "multi_turn_context_accuracy",
    "recovery_success_rate",
    "cross_session_leak_rate",
    "answer_schema_valid_rate",
    "repeat_stability",
)


# ---------------------------------------------------------------------------
# result containers
# ---------------------------------------------------------------------------
@dataclass
class Check:
    name: str
    ok: bool
    expected: Any = None
    actual: Any = None
    detail: str = ""


@dataclass
class CaseResult:
    case_id: str
    category: str
    evaluator: str
    priority: str
    status: str
    checks: list[Check] = field(default_factory=list)
    metrics: dict[str, bool] = field(default_factory=dict)
    duration_ms: float = 0.0
    question: str = ""
    scope: str = ""
    forbidden: list = field(default_factory=list)
    evidence: dict = field(default_factory=dict)
    # The case's answer contract, carried so ``_suite_capabilities`` can tell
    # which metrics this selection is *able* to measure (a cloned result that
    # dropped its metric is still capable of producing one).
    answer_requirements: tuple = ()
    known_gap: bool = False
    gap_note: str = ""
    gap_meta: dict = field(default_factory=dict)
    unknown_fields: list = field(default_factory=list)
    error: str = ""
    # Semantic fingerprint used by ``--repeat``: intent level, tool order,
    # normalized SQL, numeric results, evidence, chart type and unsupported
    # claims.  Timestamps / token counts / session ids are never included.
    signature: dict = field(default_factory=dict)
    # Per-run provenance (evaluator, provider/model, database, session id).
    run_meta: dict = field(default_factory=dict)

    @property
    def failed_checks(self) -> list[Check]:
        return [c for c in self.checks if not c.ok]


class EvalContext:
    """Cached, read-only access to the fixtures + repo runtime."""

    def __init__(self, verbose: bool = False) -> None:
        self.verbose = verbose
        self.tmpdir = Path(tempfile.mkdtemp(prefix="analytics-eval-"))
        self._ontology_store = None
        self._retriever = None
        self._sandbox_seq = 0
        self.allowed_numbers: set[float] = set()
        self.live_harness: Optional["LiveHarness"] = None

    def new_sandbox(self, label: str) -> Path:
        """A fresh, unique directory for one evaluator invocation.

        ``--repeat`` runs the same case several times in one process, so a
        directory keyed only by ``case_id`` would let an earlier run pollute the
        next one's counts.
        """
        self._sandbox_seq += 1
        root = self.tmpdir / f"{self._sandbox_seq:04d}-{label}"
        root.mkdir(parents=True, exist_ok=True)
        return root

    # -- ontology -------------------------------------------------------
    def ontology_store(self):
        if self._ontology_store is None:
            from bi_agent.ontology.store import OntologyStore

            self._ontology_store = OntologyStore.from_xlsx(
                str(ONTOLOGY_DIR / "analytics_golden_ontology.xlsx")
            )
        return self._ontology_store

    def retriever(self):
        if self._retriever is None:
            from bi_agent.ontology.retriever import GraphRetriever

            self._retriever = GraphRetriever(self.ontology_store())
        return self._retriever

    # -- sqlite ---------------------------------------------------------
    def sqlite_readonly(self, db_name: str) -> sqlite3.Connection:
        path = SQLITE_DIR / db_name
        if not path.exists():
            raise FileNotFoundError(f"fixture db missing: {path}")
        uri = f"file:{path}?mode=ro&immutable=1"
        return sqlite3.connect(uri, uri=True)

    def cleanup(self) -> None:
        shutil.rmtree(self.tmpdir, ignore_errors=True)


def _close(a: Any, b: Any, tol: float) -> bool:
    if a is None or b is None:
        return a is None and b is None
    a_num = isinstance(a, (int, float)) and not isinstance(a, bool)
    b_num = isinstance(b, (int, float)) and not isinstance(b, bool)
    if a_num and b_num:
        return abs(float(a) - float(b)) <= max(tol, tol * abs(float(b)))
    return str(a) == str(b)


def _format(value: Any, limit: int = 220) -> str:
    text = json.dumps(value, ensure_ascii=False, default=str)
    return text if len(text) <= limit else text[:limit] + "…"


# Volatile fields that change on every run but carry no contract meaning.
VOLATILE_SNAPSHOT_KEYS = frozenset({"updated_at", "created_at", "checkpoint_id"})


def _scrub_snapshot(value: Any) -> Any:
    """Drop run-to-run noise so repeat_stability measures behaviour, not clocks."""
    if isinstance(value, dict):
        return {k: _scrub_snapshot(v) for k, v in value.items()
                if k not in VOLATILE_SNAPSHOT_KEYS}
    if isinstance(value, list):
        return [_scrub_snapshot(v) for v in value]
    return value


_SCHEMA_FIELD_CACHE: Optional[set[str]] = None


def _schema_case_fields() -> set[str]:
    """Top-level keys allowed by the case schema; cached after the first read."""
    global _SCHEMA_FIELD_CACHE
    if _SCHEMA_FIELD_CACHE is None:
        try:
            schema = json.loads((EVAL_ROOT / "schemas" / "case.schema.json").read_text(encoding="utf-8"))
            _SCHEMA_FIELD_CACHE = set(schema.get("properties") or {})
        except (OSError, ValueError):
            _SCHEMA_FIELD_CACHE = set()
    return _SCHEMA_FIELD_CACHE


def _case_scaffold(case: dict) -> dict:
    expected = case.get("expected", {})
    scope_bits = []
    # ``metric``/``filters``/``dimensions`` are strings or lists in query cases, but
    # ``op=stats`` cases reuse the same key names for counts, so only render the
    # shapes we can actually join.
    if isinstance(expected.get("metric"), str) and expected["metric"]:
        scope_bits.append(f"metric={expected['metric']}")
    if isinstance(expected.get("filters"), list) and expected["filters"]:
        scope_bits.append("filters=" + ",".join(map(str, expected["filters"])))
    if isinstance(expected.get("dimensions"), list) and expected["dimensions"]:
        scope_bits.append("dim=" + ",".join(map(str, expected["dimensions"])))
    return {
        "question": case.get("question", ""),
        "scope": "; ".join(scope_bits),
        "forbidden": list(case.get("forbidden", [])),
        "known_gap": bool(case.get("known_gap")),
        "gap_note": case.get("gap_note", ""),
        "gap_meta": dict(case.get("gap_meta") or {}),
        "answer_requirements": tuple(case.get("answer_requirements") or ()),
    }


# ---------------------------------------------------------------------------
# evaluator: policy
# ---------------------------------------------------------------------------
POLICY_MODES = {
    "FACT_QUERY", "DIAGNOSTIC_ANALYSIS", "ONTOLOGY_LOOKUP",
    "CLARIFICATION", "CAPABILITY_LIMITATION", "GENERAL_RESPONSE",
}
POLICY_NEXT_STEPS = {
    "QUERY_DORIS", "QUERY_ONTOLOGY", "ASK_USER", "DELIVER_LIMITATION", "DELIVER",
}


def eval_policy(case: dict, ctx: EvalContext) -> CaseResult:
    from bi_agent.tools.analysis_policy import (
        build_cognitive_policy_decision,
        classify_intent,
    )

    expected = case["expected"]
    tools = list(expected.get("allowed_tools") or [])
    decision = build_cognitive_policy_decision(case["question"], tools)
    intent = classify_intent(case["question"])
    policy = dict(expected.get("policy") or {})

    checks: list[Check] = []

    def chk(name: str, ok: bool, exp: Any, act: Any) -> None:
        checks.append(Check(name, bool(ok), exp, act))

    if "mode" in policy:
        chk("policy.mode", decision["mode"] == policy["mode"], policy["mode"], decision["mode"])
    if "mode_not_in" in policy:
        chk("policy.mode_not_in", decision["mode"] not in policy["mode_not_in"],
            policy["mode_not_in"], decision["mode"])
    if "reason_code" in policy:
        chk("policy.reason_code", decision["reason_code"] == policy["reason_code"],
            policy["reason_code"], decision["reason_code"])
    if "next_step" in policy:
        chk("policy.next_step", decision["next_step"] == policy["next_step"],
            policy["next_step"], decision["next_step"])
    if "required_tools" in policy:
        chk("policy.required_tools", list(decision["required_tools"]) == list(policy["required_tools"]),
            policy["required_tools"], decision["required_tools"])
    if policy.get("required_tools_empty"):
        chk("policy.required_tools_empty", not decision["required_tools"], [], decision["required_tools"])
    if "refusal_category" in policy:
        want = policy["refusal_category"]
        chk("policy.refusal_category",
            decision.get("refusal_category") == want, want, decision.get("refusal_category"))
    if policy.get("refusal_category_absent"):
        # The mirror of ``refusal_category``: a constraint statement
        # ("不得删除…") or a safety-guidance question must reach the normal
        # branches, so the contract has to be assertable in both directions.
        chk("policy.refusal_category_absent", not decision.get("refusal_category"),
            "no refusal category", decision.get("refusal_category"))
    if policy.get("refusal_message_required"):
        message = str(decision.get("refusal_message") or "").strip()
        chk("policy.refusal_message_required", bool(message), True, bool(message))
    if "evidence_required" in policy:
        chk("policy.evidence_required", bool(decision["evidence_required"]) == bool(policy["evidence_required"]),
            policy["evidence_required"], decision["evidence_required"])
    if "needs_human" in policy:
        chk("policy.needs_human", bool(decision["needs_human"]) == bool(policy["needs_human"]),
            policy["needs_human"], decision["needs_human"])
    if "intent_level" in expected:
        chk("intent.level", intent.level == expected["intent_level"],
            expected["intent_level"], intent.level)
    if "wants_root_cause" in expected:
        chk("intent.wants_root_cause", bool(intent.wants_root_cause) == bool(expected["wants_root_cause"]),
            expected["wants_root_cause"], intent.wants_root_cause)
    if "wants_action" in expected:
        chk("intent.wants_action", bool(intent.wants_action) == bool(expected["wants_action"]),
            expected["wants_action"], intent.wants_action)
    if "wants_forecast" in expected:
        want = bool(expected["wants_forecast"])
        chk("intent.wants_forecast", bool(intent.wants_forecast) == want,
            want, intent.wants_forecast)
        chk("policy.wants_forecast", bool(decision.get("wants_forecast")) == want,
            want, decision.get("wants_forecast"))
    if "forecast_kind" in expected:
        want = expected["forecast_kind"]
        chk("intent.forecast_kind", intent.forecast_kind == want,
            want, intent.forecast_kind)
        chk("policy.forecast_kind", decision.get("forecast_kind") == want,
            want, decision.get("forecast_kind"))

    schema_ok = (
        decision.get("policy_version") == 1
        and decision.get("mode") in POLICY_MODES
        and decision.get("next_step") in POLICY_NEXT_STEPS
        and isinstance(decision.get("required_tools"), list)
        and isinstance(decision.get("evidence_required"), bool)
        and isinstance(decision.get("needs_human"), bool)
        and str(decision.get("input_digest", "")).startswith("sha256:")
    )
    chk("policy.schema_valid", schema_ok, True, schema_ok)

    result = _result_from(case, checks)
    result.metrics["intent_accuracy"] = all(
        c.ok for c in checks if c.name == "intent.level"
    ) if any(c.name == "intent.level" for c in checks) else True
    result.metrics["tool_route_accuracy"] = all(
        c.ok for c in checks
        if c.name in ("policy.mode", "policy.mode_not_in", "policy.next_step",
                      "policy.required_tools", "policy.required_tools_empty",
                      "policy.reason_code", "policy.refusal_category",
                      "policy.refusal_message_required")
    )
    result.metrics["answer_schema_valid_rate"] = schema_ok
    result.metrics["evidence_coverage"] = bool(decision.get("evidence_required")) == bool(
        (expected.get("policy") or {}).get("evidence_required", decision.get("evidence_required"))
    )
    result.evidence = {
        "policy": decision,
        "intent": {"level": intent.level, "wants_root_cause": intent.wants_root_cause,
                   "wants_action": intent.wants_action},
    }
    return result


# ---------------------------------------------------------------------------
# evaluator: sql
# ---------------------------------------------------------------------------
def eval_sql(case: dict, ctx: EvalContext) -> CaseResult:
    expected = case["expected"]
    fixture = case["fixture"]
    sql = fixture["sql"]
    tolerance = float(expected.get("tolerance", 1e-6))
    checks: list[Check] = []
    evidence: dict[str, Any] = {"sql": sql, "db": fixture.get("db")}

    columns: list[str] = []
    rows: list[tuple] = []
    execute_error = ""
    try:
        conn = ctx.sqlite_readonly(fixture["db"])
        try:
            cur = conn.cursor()
            cur.execute(sql)
            columns = [d[0] for d in (cur.description or [])]
            rows = list(cur.fetchall())
        finally:
            conn.close()
    except Exception as exc:  # noqa: BLE001 - reported as a failing check
        execute_error = f"{type(exc).__name__}: {exc}"

    contract = expected.get("query_contract") or {}
    contract_ok = bool(contract.get("db")) and bool(
        contract.get("metric") or contract.get("dimensions") or contract.get("filters")
        or expected.get("scope_note")
    )
    checks.append(Check("query_contract.declared", contract_ok, True, contract))

    scope_ok = True
    declared_filters = list(contract.get("filters") or [])
    if declared_filters:
        normalized_sql = re.sub(r"\s+", " ", sql)
        missing = [f for f in declared_filters if re.sub(r"\s+", " ", str(f)) not in normalized_sql]
        scope_ok = not missing
        checks.append(Check("metric_scope.sql_matches_filters", scope_ok, [], missing))

    if execute_error:
        checks.append(Check("reference_sql.executes", False, "no error", execute_error))
        result = _result_from(case, checks)
        result.metrics.update({
            "exact_numeric_accuracy": False,
            "query_contract_accuracy": False,
            "metric_scope_accuracy": scope_ok,
        })
        result.evidence = evidence
        return result

    checks.append(Check("reference_sql.executes", True, "no error", "ok"))
    evidence["columns"] = columns
    evidence["rows"] = rows[:8]
    evidence["columns_count"] = len(columns)

    if expected.get("value_is_null"):
        actual = rows[0][0] if rows and rows[0] else None
        ok = actual is None
        checks.append(Check("facts.value", ok, None, actual))
        facts_ok = ok
    elif expected.get("rows") is not None:
        expected_rows = expected["rows"]
        actual_rows = [list(r) for r in rows]
        ok = len(actual_rows) == len(expected_rows)
        detail = ""
        if ok:
            for idx, exp_row in enumerate(expected_rows):
                act_row = actual_rows[idx]
                if len(exp_row) != len(act_row):
                    ok = False
                    detail = f"row {idx}: arity {len(act_row)} != {len(exp_row)}"
                    break
                for e_cell, a_cell in zip(exp_row, act_row):
                    if not _close(a_cell, e_cell, tolerance):
                        ok = False
                        detail = f"row {idx}: {a_cell!r} != {e_cell!r}"
                        break
                if not ok:
                    break
        else:
            detail = f"row count {len(actual_rows)} != {len(expected_rows)}"
        checks.append(Check("facts.rows", ok, expected_rows, actual_rows, detail))
        facts_ok = ok
    else:
        actual = rows[0][0] if rows and rows[0] else None
        ok = _close(actual, expected.get("value"), tolerance)
        checks.append(Check("facts.value", ok, expected.get("value"), actual))
        facts_ok = ok

    result = _result_from(case, checks)
    result.metrics.update({
        "exact_numeric_accuracy": facts_ok,
        "query_contract_accuracy": contract_ok and not execute_error,
        "metric_scope_accuracy": scope_ok and not execute_error,
    })
    result.evidence = evidence
    return result


# ---------------------------------------------------------------------------
# evaluator: ontology
# ---------------------------------------------------------------------------
def eval_ontology(case: dict, ctx: EvalContext) -> CaseResult:
    expected = case["expected"]
    op = expected["op"]
    store = ctx.ontology_store()
    retriever = ctx.retriever()
    checks: list[Check] = []
    evidence: dict[str, Any] = {"op": op, "ontology": case["fixture"].get("ontology")}

    def chk(name, ok, exp, act, detail=""):
        checks.append(Check(name, bool(ok), exp, act, detail))

    if op == "anchor":
        anchors = [list(a) for a in retriever.resolve_anchor(case["question"])]
        evidence["anchors"] = anchors
        if "anchors" in expected:
            chk("ontology.anchors", anchors == [list(a) for a in expected["anchors"]],
                expected["anchors"], anchors)
        for wanted in expected.get("anchors_contains", []):
            chk(f"ontology.anchor_contains[{wanted[1]}]", list(wanted) in anchors,
                wanted, anchors)
    elif op == "term":
        matches = store.find_term(expected.get("query") or case["question"])
        evidence["terms"] = [(t.code, t.name) for t in matches]
        if expected.get("missing"):
            chk("ontology.term_missing", not matches, [], [t.code for t in matches])
        else:
            by_code = {t.code: t for t in matches}
            term = by_code.get(expected["code"])
            chk("ontology.term_found", term is not None, expected["code"], sorted(by_code))
            if term is not None:
                if "name" in expected:
                    chk("ontology.term_name", term.name == expected["name"], expected["name"], term.name)
                if "english" in expected:
                    chk("ontology.term_english", term.english == expected["english"],
                        expected["english"], term.english)
                if "definition_contains" in expected:
                    chk("ontology.term_definition",
                        expected["definition_contains"] in (term.definition or ""),
                        expected["definition_contains"], term.definition)
                if "aliases" in expected:
                    chk("ontology.term_aliases",
                        all(a in (term.aliases or []) for a in expected["aliases"]),
                        expected["aliases"], term.aliases)
    elif op == "metric":
        metric = store.metrics.get(expected["code"])
        chk("ontology.metric_found", metric is not None, expected["code"], sorted(store.metrics))
        if metric is not None:
            evidence["metric"] = metric.to_prompt()
            for key, attr in (("name", "name"), ("table", "table"),
                              ("agg_column", "agg_column"), ("agg_type", "agg_type"),
                              ("filter_condition", "filter_condition")):
                if key in expected:
                    chk(f"ontology.metric_{key}", str(getattr(metric, attr)) == str(expected[key]),
                        expected[key], getattr(metric, attr))
            if "definition_contains" in expected:
                chk("ontology.metric_definition",
                    expected["definition_contains"] in (metric.definition or ""),
                    expected["definition_contains"], metric.definition)
            dims = list(metric.applicable_dimensions or [])
            if "dimensions_contains" in expected:
                missing = [d for d in expected["dimensions_contains"] if d not in dims]
                chk("ontology.metric_dimensions", not missing, expected["dimensions_contains"], dims)
            if "dimensions_excludes" in expected:
                leaked = [d for d in expected["dimensions_excludes"] if d in dims]
                chk("ontology.metric_dimensions_excluded", not leaked, [], leaked)
    elif op in ("business_object", "logical_entity"):
        getter = store.get_business_object if op == "business_object" else store.get_logical_entity
        entity = getter(expected["code"])
        chk(f"ontology.{op}_found", entity is not None, expected["code"], None)
        if entity is not None:
            evidence[op] = {"code": entity.code, "name": entity.name,
                            "physical_table": entity.physical_table}
            if "name" in expected:
                chk("ontology.name", entity.name == expected["name"], expected["name"], entity.name)
            if "physical_table" in expected:
                chk("ontology.physical_table",
                    entity.physical_table == expected["physical_table"],
                    expected["physical_table"], entity.physical_table)
    elif op == "relations":
        relations = store.relations_of(expected["le_code"])
        codes = [r.code for r in relations]
        targets = [r.target_code for r in relations]
        evidence["relations"] = [
            {"code": r.code, "source": r.source_code, "target": r.target_code,
             "foreign_key": r.foreign_key} for r in relations
        ]
        if "relation_codes" in expected:
            chk("ontology.relation_codes", codes == expected["relation_codes"],
                expected["relation_codes"], codes)
        if "targets" in expected:
            chk("ontology.relation_targets", targets == expected["targets"],
                expected["targets"], targets)
        if "foreign_keys" in expected:
            keys = [r.foreign_key for r in relations]
            chk("ontology.relation_foreign_keys", keys == expected["foreign_keys"],
                expected["foreign_keys"], keys)
    elif op == "rules":
        rules = store.rules_of(expected["activity_code"])
        codes = [r.code for r in rules]
        evidence["rules"] = [{"code": r.code, "rule": r.rule,
                              "activity": r.activity_name} for r in rules]
        if "rule_codes" in expected:
            chk("ontology.rule_codes", codes == expected["rule_codes"],
                expected["rule_codes"], codes)
        if "definition_contains" in expected:
            joined = " ".join(r.rule for r in rules)
            chk("ontology.rule_text", expected["definition_contains"] in joined,
                expected["definition_contains"], joined)
    elif op == "stats":
        stats = store.stats()
        evidence["stats"] = stats
        for key, value in expected.items():
            if key == "op":
                continue
            chk(f"ontology.stats_{key}", stats.get(key) == value, value, stats.get(key))
    else:
        chk("ontology.op_supported", False, "supported op", op)

    result = _result_from(case, checks)
    result.metrics["evidence_coverage"] = all(c.ok for c in checks)
    result.evidence = evidence
    return result


# ---------------------------------------------------------------------------
# evaluator: multi_turn
# ---------------------------------------------------------------------------
def eval_multi_turn(case: dict, ctx: EvalContext) -> CaseResult:
    fixture = case["fixture"]
    expected = case["expected"]
    previous = fixture["previous_contract"]
    resolution = fixture.get("resolution") or {}
    resolved = dict(previous)
    for key in resolution.get("drop", []):
        resolved.pop(key, None)
    resolved.update(dict(resolution.get("override", {})))

    checks: list[Check] = []
    checks.append(Check("context.resolved_contract",
                        resolved == expected["context_contract"],
                        expected["context_contract"], resolved))

    shadow = dict(case)
    shadow["question"] = fixture["effective_question"]
    shadow["expected"] = {
        "allowed_tools": expected.get("allowed_tools"),
        "policy": expected.get("policy"),
        "intent_level": expected.get("intent_level"),
        "wants_root_cause": expected.get("wants_root_cause"),
        "wants_action": expected.get("wants_action"),
    }
    policy_result = eval_policy(shadow, ctx)
    checks.extend(policy_result.checks)

    changed = [k for k in ("time_range", "organization", "dimensions", "metric",
                           "currency", "unit", "filters")
               if previous.get(k) != resolved.get(k)]
    claimed = sorted(set(resolution.get("override", {})) | set(resolution.get("drop", [])))
    over_declared = [k for k in changed if k not in claimed]
    checks.append(Check("context.changes_declared", not over_declared, [], over_declared))

    result = _result_from(case, checks)
    result.metrics["multi_turn_context_accuracy"] = all(c.ok for c in checks)
    result.metrics["intent_accuracy"] = policy_result.metrics.get("intent_accuracy", True)
    result.metrics["tool_route_accuracy"] = policy_result.metrics.get("tool_route_accuracy", True)
    result.metrics["answer_schema_valid_rate"] = policy_result.metrics.get(
        "answer_schema_valid_rate", True)
    result.evidence = {
        "previous_contract": previous,
        "resolution": resolution,
        "resolved_contract": resolved,
        "policy": policy_result.evidence.get("policy"),
    }
    return result


_TUPLE_CONTEXT_FIELDS = ("metrics", "dimensions", "filters", "entity_scope")


def _normalize_context(raw: dict) -> dict:
    """Compare JSON list literals against ``AnalysisContext.to_dict()``.

    ``to_dict`` renders the tuple scope fields as lists, so the expected payload
    written in the case JSON is normalised the same way before comparison.
    """
    out: dict[str, Any] = {}
    for key, value in dict(raw).items():
        if key in _TUPLE_CONTEXT_FIELDS and value is not None:
            value = list(value)
        out[key] = value
    return out


def eval_context_resolution(case: dict, ctx: EvalContext) -> CaseResult:
    """Resolve a follow-up's scope with the *production* context merger.

    ``bi_agent.reliability.AnalysisContext.merge`` is the implementation behind
    ``WebSession.update_analysis_context``; the evaluator calls it directly
    instead of re-implementing "inherited vs overridden" in the harness, so a
    change to the production merge semantics fails these cases immediately.
    """
    from bi_agent.reliability import AnalysisContext

    fixture = case.get("fixture") or {}
    expected = case.get("expected") or {}
    checks: list[Check] = []

    previous = dict(fixture.get("previous") or {})
    changes = dict(fixture.get("changes") or {})
    merged = AnalysisContext(**previous).merge(changes)
    # ``to_dict`` preserves whatever container type entered the dataclass, so
    # both sides are normalised before comparison.
    resolved = _normalize_context(merged.to_dict())
    baseline = _normalize_context(previous)

    want = _normalize_context(expected.get("context") or {})
    checks.append(Check("context.production_merge", resolved == want, want, resolved))

    inherited = [key for key in previous if key not in changes]
    drifted = [key for key in inherited if resolved.get(key) != baseline.get(key)]
    checks.append(Check("context.inherited_scope_preserved", not drifted, inherited, drifted))

    for key in changes:
        checks.append(Check(f"context.override_applied[{key}]",
                            resolved.get(key) == want.get(key), want.get(key), resolved.get(key)))

    for key in expected.get("must_not_appear", []):
        values = resolved.get(key)
        checks.append(Check(f"context.dropped[{key}]", not values, "empty", values))

    result = _result_from(case, checks)
    result.metrics["multi_turn_context_accuracy"] = all(c.ok for c in checks)
    result.metrics["answer_schema_valid_rate"] = True
    result.evidence = {
        "previous_context": previous,
        "explicit_changes": changes,
        "resolved_context": resolved,
    }
    return result


def _result_from(case: dict, checks: list[Check]) -> CaseResult:
    scaffold = _case_scaffold(case)
    ok = all(c.ok for c in checks)
    if scaffold["known_gap"]:
        status = XPASS if ok else XFAIL
    else:
        status = PASS if ok else FAIL
    return CaseResult(
        case_id=case["case_id"],
        category=case.get("category", ""),
        evaluator=case.get("evaluator", ""),
        priority=case.get("priority", "P1"),
        status=status,
        checks=checks,
        question=scaffold["question"],
        scope=scaffold["scope"],
        forbidden=scaffold["forbidden"],
        answer_requirements=scaffold["answer_requirements"],
        known_gap=scaffold["known_gap"],
        gap_note=scaffold["gap_note"],
        gap_meta=scaffold["gap_meta"],
    )


# ---------------------------------------------------------------------------
# evaluator: chart_validate / chart_policy / chart_html_safety
# ---------------------------------------------------------------------------
def eval_chart_validate(case: dict, ctx: EvalContext) -> CaseResult:
    from bi_agent.tools.chart_tools import _validate

    params = case["fixture"]["chart_params"]
    error = _validate(params)
    expected = case["expected"]
    checks: list[Check] = []
    if expected.get("valid"):
        checks.append(Check("chart.accepted", error is None, None, error))
    else:
        checks.append(Check("chart.rejected", error is not None, "an error", error))
        if expected.get("reason_contains"):
            checks.append(Check("chart.reason", bool(error) and expected["reason_contains"] in error,
                                expected["reason_contains"], error))
    result = _result_from(case, checks)
    result.metrics["chart_selection_accuracy"] = all(c.ok for c in checks)
    result.evidence = {"chart_params": params, "error": error}
    return result


def eval_chart_policy(case: dict, ctx: EvalContext) -> CaseResult:
    from bi_agent.tools.chart_policy import chart_skip_reason

    params = case["fixture"]["chart_params"]
    tool_name = case["expected"].get("tool_name") or "ChartGenerate"
    reason = chart_skip_reason(case["question"], tool_name, params)
    expected = case["expected"]
    checks: list[Check] = []
    if expected.get("skip"):
        checks.append(Check("chart.suppressed", reason is not None, "a reason", reason))
        if expected.get("reason_contains"):
            checks.append(Check("chart.skip_reason",
                                bool(reason) and expected["reason_contains"] in reason,
                                expected["reason_contains"], reason))
    else:
        checks.append(Check("chart.not_suppressed", reason is None, None, reason))
    result = _result_from(case, checks)
    result.metrics["chart_selection_accuracy"] = all(c.ok for c in checks)
    result.evidence = {"chart_params": params, "skip_reason": reason, "tool": tool_name}
    return result


def eval_chart_html_safety(case: dict, ctx: EvalContext) -> CaseResult:
    from bi_agent.tools.chart_tools import _write_standalone_html

    fixture = case["fixture"]
    expected = case["expected"]
    out_path = ctx.new_sandbox(case["case_id"]) / f"{case['case_id']}.html"
    _write_standalone_html(dict(fixture.get("option") or {}), out_path, fixture.get("title", ""))
    html = out_path.read_text(encoding="utf-8")
    checks: list[Check] = []
    for bad in expected.get("forbidden_substrings", []):
        checks.append(Check(f"html.no_raw[{bad[:20]}]", bad not in html, "absent", "present"))
    for good in expected.get("must_contain", []):
        checks.append(Check(f"html.contains[{good}]", good in html, good, "missing"))
    if expected.get("escaped"):
        checks.append(Check("html.escaped", "\\u003c" in html or "&lt;" in html,
                            "escaped payload", html[:80]))
    result = _result_from(case, checks)
    result.metrics["chart_selection_accuracy"] = all(c.ok for c in checks)
    result.evidence = {"html_head": html[:400]}
    return result


# ---------------------------------------------------------------------------
# evaluator: sql_guard
# ---------------------------------------------------------------------------
def eval_sql_guard(case: dict, ctx: EvalContext) -> CaseResult:
    from bi_agent.tools.sql_tools import _validate_sql

    error = _validate_sql(case["fixture"]["sql"])
    expected = case["expected"]
    checks: list[Check] = []
    if expected.get("valid"):
        checks.append(Check("sql_guard.allowed", error is None, None, error))
    else:
        checks.append(Check("sql_guard.rejected", error is not None, "an error", error))
        if expected.get("error_contains"):
            checks.append(Check("sql_guard.reason",
                                bool(error) and expected["error_contains"] in error,
                                expected["error_contains"], error))
    result = _result_from(case, checks)
    result.metrics["answer_schema_valid_rate"] = all(c.ok for c in checks)
    result.evidence = {"sql": case["fixture"]["sql"], "error": error}
    return result


# ---------------------------------------------------------------------------
# evaluator: recovery_state
# ---------------------------------------------------------------------------
def _apply_recovery_step(state, op: str, payload: dict) -> tuple[Any, dict]:
    from bi_agent import recovery as R

    obs: dict[str, Any] = {}
    if op == "start_turn":
        return state.start_turn(payload["turn_ref"]), obs
    if op == "ask_user":
        return state.ask_user(payload["tool_use_id"], payload.get("question", ""),
                              payload.get("options", [])), obs
    if op == "resume_after_user_choice":
        return state.resume_after_user_choice(), obs
    if op == "tool_success":
        return state.tool_success(
            payload["step"],
            execution_id=payload.get("execution_id"),
            attempt=payload.get("attempt", 1),
            input_digest_value=payload.get("input_digest_value", ""),
            result_ref=payload.get("result_ref", ""),
            tool_use_id=payload.get("tool_use_id"),
        ), obs
    if op == "tool_terminal":
        return state.tool_terminal(
            payload["status"],
            step=payload.get("step", "QUERY"),
            error_code=payload.get("error_code", ""),
            retryable=payload.get("retryable", False),
            execution_id=payload.get("execution_id"),
            attempt=payload.get("attempt", 1),
            input_digest_value=payload.get("input_digest_value", ""),
            tool_use_id=payload.get("tool_use_id"),
        ), obs
    if op == "mark_unrecoverable":
        return state.mark_unrecoverable(error_code=payload.get("error_code") or R.RECOVERY_INPUT_MISSING), obs
    if op == "begin_retry":
        code, snapshot = state.begin_retry(payload.get("expected_tool_use_id"))
        obs["return_error_code"] = code
        return snapshot, obs
    if op == "mark_succeeded":
        return state.mark_succeeded(payload.get("attempt", 1)), obs
    if op == "snapshot":
        return state.snapshot(), obs
    raise ValueError(f"unsupported recovery op: {op}")


def eval_recovery_state(case: dict, ctx: EvalContext) -> CaseResult:
    from bi_agent.recovery import RecoveryState

    state = RecoveryState()
    observations: list[dict] = []
    for step in case["fixture"]["script"]:
        op, payload = step[0], (step[1] if len(step) > 1 else {})
        returned, obs = _apply_recovery_step(state, op, payload)
        snapshot = state.snapshot()
        obs.update({
            "status": snapshot["status"],
            "current_step": snapshot["current_step"],
            "attempt": snapshot["attempt"],
            "retryable": snapshot["retryable"],
            "error_code": snapshot["error_code"],
            "turn_ref": snapshot["turn_ref"],
            "checkpoint": snapshot["last_checkpoint"] is not None,
            "checkpoint_step": (snapshot["last_checkpoint"] or {}).get("step", ""),
            "pending_user": snapshot["pending_user"],
            "return": returned,
            "return_is_none": returned is None,
            "snapshot": snapshot,
        })
        observations.append(obs)

    checks: list[Check] = []
    for check in case["expected"]["checks"]:
        idx = check["after"]
        obs = observations[idx]
        for key, want in check.items():
            if key == "after":
                continue
            if key == "status":
                checks.append(Check(f"recovery[{idx}].status", obs["status"] == want, want, obs["status"]))
            elif key == "current_step":
                checks.append(Check(f"recovery[{idx}].current_step", obs["current_step"] == want, want, obs["current_step"]))
            elif key == "attempt":
                checks.append(Check(f"recovery[{idx}].attempt", obs["attempt"] == want, want, obs["attempt"]))
            elif key == "retryable":
                checks.append(Check(f"recovery[{idx}].retryable", obs["retryable"] == want, want, obs["retryable"]))
            elif key == "error_code":
                checks.append(Check(f"recovery[{idx}].error_code", obs["error_code"] == want, want, obs["error_code"]))
            elif key == "turn_ref":
                checks.append(Check(f"recovery[{idx}].turn_ref", obs["turn_ref"] == want, want, obs["turn_ref"]))
            elif key == "checkpoint":
                checks.append(Check(f"recovery[{idx}].checkpoint", obs["checkpoint"] == want, want, obs["checkpoint"]))
            elif key == "checkpoint_step":
                checks.append(Check(f"recovery[{idx}].checkpoint_step", obs["checkpoint_step"] == want, want, obs["checkpoint_step"]))
            elif key == "pending_user":
                pending = obs["pending_user"]
                if want is False:
                    checks.append(Check(f"recovery[{idx}].pending_user_none", pending is None, None, pending))
                else:
                    ok = isinstance(pending, dict)
                    if ok and "question_contains" in want:
                        ok = want["question_contains"] in str(pending.get("question", ""))
                    if ok and "options_len" in want:
                        ok = len(pending.get("options") or []) == want["options_len"]
                    checks.append(Check(f"recovery[{idx}].pending_user", ok, want, pending))
            elif key == "return":
                checks.append(Check(f"recovery[{idx}].return_is_none", obs["return_is_none"] == (want is None),
                                    want, obs["return"]))
            elif key == "return_error_code":
                checks.append(Check(f"recovery[{idx}].return_error_code",
                                    obs.get("return_error_code") == want, want, obs.get("return_error_code")))
            elif key == "unchanged_from":
                a = _scrub_snapshot(observations[want]["snapshot"])
                b = _scrub_snapshot(obs["snapshot"])
                checks.append(Check(f"recovery[{idx}].unchanged_from[{want}]", a == b, a, b))
            else:
                checks.append(Check(f"recovery[{idx}].{key}", False, "supported key", key))

    result = _result_from(case, checks)
    result.metrics["recovery_success_rate"] = all(c.ok for c in checks)
    result.evidence = {
        "final_status": observations[-1]["status"] if observations else "",
        "transitions": [(o["status"], o["current_step"], o["error_code"]) for o in observations],
    }
    return result


# ---------------------------------------------------------------------------
# evaluator: admission (concurrency / session slots)
# ---------------------------------------------------------------------------
def eval_admission(case: dict, ctx: EvalContext) -> CaseResult:
    from bi_agent.concurrency import (
        AdmissionController, AdmissionRejected, Limits, RequestPrincipal,
        SessionSlotRegistry,
    )

    fixture = case["fixture"]
    env = dict(fixture.get("env") or {})
    principals_cfg = dict(fixture.get("principals") or {})
    limits = Limits(env)
    controller = AdmissionController(limits)
    slots = SessionSlotRegistry()
    tickets: dict[str, Any] = {}
    leases: dict[str, Any] = {}
    threads: dict[str, threading.Thread] = {}
    async_results: dict[str, dict] = {}
    observations: list[dict] = []

    def principal(name: str) -> RequestPrincipal:
        tenant, user, session = principals_cfg[name]
        return RequestPrincipal(tenant_id=tenant, user_id=user, session_id=session)

    for step in fixture["script"]:
        op = step["op"]
        obs: dict[str, Any] = {}
        try:
            if op == "limits":
                local_env = dict(step.get("env") or env)
                obs["limits"] = Limits(local_env).to_dict()
            elif op == "acquire":
                cancel = threading.Event() if step.get("cancel") else None
                if cancel is None:
                    ticket = controller.acquire(principal(step["principal"]), cancel)
                    if step.get("as"):
                        tickets[step["as"]] = ticket
                    obs["granted"] = True
                    obs["ticket"] = True
                else:
                    # "Cancelled while waiting" cannot be scripted inline: the
                    # cancel event has to fire *after* the acquire started
                    # blocking, otherwise we only ever measure the timeout.
                    holder: dict[str, Any] = {}

                    def worker(holder=holder, step=step, cancel=cancel):
                        try:
                            holder["ticket"] = controller.acquire(
                                principal(step["principal"]), cancel
                            )
                            holder["granted"] = True
                        except AdmissionRejected as exc:
                            holder["reject_code"] = exc.code
                            holder["granted"] = False

                    thread = threading.Thread(target=worker, daemon=True)
                    thread.start()
                    time.sleep(float(step.get("cancel_after", 0.05)))
                    cancel.set()
                    thread.join(timeout=5.0)
                    obs["granted"] = bool(holder.get("granted"))
                    obs["reject_code"] = holder.get("reject_code")
                    if holder.get("ticket") is not None and step.get("as"):
                        tickets[step["as"]] = holder["ticket"]
            elif op == "acquire_async":
                holder: dict[str, Any] = {}

                def worker(holder=holder, step=step):
                    try:
                        holder["ticket"] = controller.acquire(principal(step["principal"]))
                        holder["granted"] = True
                    except AdmissionRejected as exc:
                        holder["reject_code"] = exc.code
                        holder["granted"] = False

                thread = threading.Thread(target=worker, daemon=True)
                async_results[step["as"]] = holder
                threads[step["as"]] = thread
                thread.start()
                obs["async_started"] = True
            elif op == "join":
                key = step["as"]
                threads[key].join(timeout=5.0)
                holder = async_results[key]
                obs["granted"] = bool(holder.get("granted"))
                obs["reject_code"] = holder.get("reject_code")
                if holder.get("ticket") is not None:
                    tickets[key] = holder["ticket"]
            elif op == "release":
                controller.release(tickets[step["ticket"]])
                obs["released"] = True
            elif op == "snapshot":
                obs["snapshot"] = controller.snapshot()
            elif op == "snapshot_after_release_all":
                for name, ticket in list(tickets.items()):
                    controller.release(ticket)
                for name, holder in async_results.items():
                    if holder.get("ticket") is not None:
                        controller.release(holder["ticket"])
                tickets.clear()
                async_results.clear()
                obs["snapshot"] = controller.snapshot()
            elif op == "slot_acquire":
                slot = slots.ensure(step["slot"])
                lease = slot.try_acquire()
                if step.get("as"):
                    leases[step["as"]] = lease
                obs["granted"] = lease is not None
            elif op == "slot_release":
                slot = slots.ensure(step["slot"])
                slot.release_turn(leases[step["lease"]])
                obs["released"] = True
            elif op == "slot_bump":
                slot = slots.ensure(step["slot"])
                obs["generation"] = slot.bump_generation()
            elif op == "slot_superseded":
                slot = slots.ensure(step["slot"])
                obs["superseded"] = slot.is_superseded(leases[step["lease"]], None)
            elif op == "slot_busy":
                obs["busy"] = slots.ensure(step["slot"]).busy
            else:
                raise ValueError(f"unsupported admission op: {op}")
        except AdmissionRejected as exc:
            obs["reject_code"] = exc.code
            obs["retry_after"] = exc.retry_after
        except ValueError as exc:
            obs["error"] = str(exc)
        observations.append(obs)

    checks: list[Check] = []
    for check in case["expected"]["checks"]:
        idx = check["after"]
        obs = observations[idx]
        for key, want in check.items():
            if key == "after":
                continue
            if key == "reject_code":
                checks.append(Check(f"admission[{idx}].reject_code", obs.get("reject_code") == want,
                                    want, obs.get("reject_code")))
            elif key == "granted":
                checks.append(Check(f"admission[{idx}].granted", obs.get("granted") == want,
                                    want, obs.get("granted")))
            elif key == "snapshot":
                for sub, sub_want in want.items():
                    checks.append(Check(f"admission[{idx}].snapshot.{sub}",
                                        obs.get("snapshot", {}).get(sub) == sub_want,
                                        sub_want, obs.get("snapshot", {}).get(sub)))
            elif key == "superseded":
                checks.append(Check(f"admission[{idx}].superseded", obs.get("superseded") == want,
                                    want, obs.get("superseded")))
            elif key == "busy":
                checks.append(Check(f"admission[{idx}].busy", obs.get("busy") == want,
                                    want, obs.get("busy")))
            elif key == "limits":
                for sub, sub_want in want.items():
                    checks.append(Check(f"admission[{idx}].limits.{sub}",
                                        obs.get("limits", {}).get(sub) == sub_want,
                                        sub_want, obs.get("limits", {}).get(sub)))
            elif key == "error_contains":
                checks.append(Check(f"admission[{idx}].error_contains",
                                    want in str(obs.get("error", "")), want, obs.get("error")))
            else:
                checks.append(Check(f"admission[{idx}].{key}", False, "supported key", key))

    result = _result_from(case, checks)
    result.metrics["recovery_success_rate"] = all(c.ok for c in checks)
    result.evidence = {"observations": observations}
    return result


# ---------------------------------------------------------------------------
# evaluator: session_isolation
# ---------------------------------------------------------------------------
def eval_session_isolation(case: dict, ctx: EvalContext) -> CaseResult:
    from bi_agent.web.conversations import MAX_HTML_BYTES, ConversationStore

    stores: dict[str, ConversationStore] = {}
    roots: dict[str, Path] = {}
    ids: dict[str, str] = {}
    observations: list[dict] = []
    # Every case gets its own directory tree so records from an earlier case can
    # never leak into ``list()`` counts.  Store aliases that share a ``root``
    # name intentionally share a directory, which is what ``shared_root`` cases
    # assert.
    case_root = ctx.new_sandbox(case["case_id"])
    aliases: dict[str, str] = {}

    def store(name: str) -> ConversationStore:
        if name not in stores:
            root_name = aliases.get(name, name)
            root = case_root / f"root-{root_name}"
            root.mkdir(parents=True, exist_ok=True)
            roots[f"{root_name}:{name}"] = root
            stores[name] = ConversationStore(str(root))
        return stores[name]

    for step in case["fixture"]["script"]:
        op = step["op"]
        obs: dict[str, Any] = {}
        st = store(step["store"]) if step.get("store") else None
        if op == "new_store":
            aliases[step["as"]] = step.get("root") or step["as"]
            store(step["as"])
            obs["created"] = True
        elif op == "save":
            record = st.save(mode=step["mode"], title=step.get("title", ""),
                             messages=[{"role": "user", "content": step.get("question", "")}],
                             cid=ids.get(step.get("cid", "")) if step.get("cid") else None)
            new_id = record.get("id", "")
            if step.get("as"):
                ids[step["as"]] = new_id
            if step.get("expect_new_id"):
                obs["new_id"] = bool(step.get("cid")) and new_id != ids.get(step["cid"], new_id)
            obs["id"] = new_id
        elif op == "get":
            cid = ids.get(step["cid"], step["cid"])
            rec = st.get(cid)
            obs["present"] = rec is not None
            obs["record"] = {"title": (rec or {}).get("title"),
                             "mode": (rec or {}).get("mode")}
        elif op == "list":
            obs["count"] = len(st.list(mode=step.get("mode")))
        elif op == "delete":
            cid = ids.get(step["cid"], step["cid"])
            obs["return"] = st.delete(cid)
        elif op == "update_html":
            cid = ids[step["cid"]]
            payload = "x" * (MAX_HTML_BYTES + 10) if step.get("size") == "oversized" else "<div>"
            obs["return"] = st.update_ontology_html(cid, payload)
            stored = (st.get(cid) or {}).get("ontology_html") or ""
            obs["stored_bytes"] = len(stored)
        elif op == "title":
            cid = ids[step["cid"]]
            title = str((st.get(cid) or {}).get("title", ""))
            obs["title"] = title
            if step.get("expect_contains"):
                obs["title_contains"] = step["expect_contains"] in title
        else:
            raise ValueError(f"unsupported isolation op: {op}")
        observations.append(obs)

    checks: list[Check] = []
    for check in case["expected"]["checks"]:
        idx = check["after"]
        obs = observations[idx]
        for key, want in check.items():
            if key == "after":
                continue
            if key == "present":
                checks.append(Check(f"isolation[{idx}].present", obs.get("present") == want,
                                    want, obs.get("present")))
            elif key == "count":
                checks.append(Check(f"isolation[{idx}].count", obs.get("count") == want,
                                    want, obs.get("count")))
            elif key == "return":
                checks.append(Check(f"isolation[{idx}].return", obs.get("return") == want,
                                    want, obs.get("return")))
            elif key == "stored_bytes":
                checks.append(Check(f"isolation[{idx}].stored_bytes", obs.get("stored_bytes") == want,
                                    want, obs.get("stored_bytes")))
            elif key == "new_id":
                checks.append(Check(f"isolation[{idx}].new_id", bool(obs.get("new_id")) == want,
                                    want, obs.get("new_id")))
            elif key == "title_contains":
                # ``want`` may be a bool (the script already declared the
                # substring) or the substring itself.
                if isinstance(want, str):
                    ok = want in str(obs.get("title", ""))
                else:
                    ok = bool(obs.get("title_contains")) == bool(want)
                checks.append(Check(f"isolation[{idx}].title_contains", ok, want,
                                    obs.get("title")))
            else:
                checks.append(Check(f"isolation[{idx}].{key}", False, "supported key", key))

    for name, root in sorted(roots.items()):
        leaked = [p for p in root.rglob("*") if p.is_file() and p.name.endswith(".tmp")]
        if leaked:
            checks.append(Check(f"isolation[{name}].no_temp_files", False, [], [str(p) for p in leaked]))

    result = _result_from(case, checks)
    result.metrics["cross_session_leak_rate"] = not all(c.ok for c in checks)
    result.evidence = {"observations": observations}
    return result


# ---------------------------------------------------------------------------
# answer scoring (semantic layer) — heuristics, never exact-text matching
# ---------------------------------------------------------------------------
# --- truthfulness supervision (causal / proxy) -----------------------------
# Contract: ``docs/specs/analytics-causal-and-proxy-truthfulness.md``.  The two
# metrics used to be live-only because no offline evaluator scored the final
# narrative; they are now decided clause-by-clause against the *declared*
# contract, so a replayed transcript is enough.
CAUSAL_REQUIREMENT = "must_separate_correlation_from_cause"
PROXY_REQUIREMENT = "must_use_proxy_disclosure_if_proxy_used"
CAUSAL_RATE_METRIC = "unsupported_causal_claim_rate"
CAUSAL_DETECTION_METRIC = "unsupported_causal_claim_detection_rate"
PROXY_RATE_METRIC = "proxy_disclosure_rate"
PROXY_DETECTION_METRIC = "proxy_disclosure_detection_rate"
CAUSAL_CHECK = "answer.unsupported_causal_claim"
PROXY_CHECK = "answer.proxy_disclosure"
# The offline recorded-provider path owns exactly these two answer checks.
TRUTHFULNESS_CHECK_PREFIXES = (CAUSAL_CHECK, PROXY_CHECK)
TRUTHFULNESS_METRICS = frozenset({
    CAUSAL_RATE_METRIC, CAUSAL_DETECTION_METRIC,
    PROXY_RATE_METRIC, PROXY_DETECTION_METRIC,
})
# Evaluators that hand ``score_answer`` the final narrative of a real turn.
ANSWER_SCORING_EVALUATORS = frozenset({
    "recorded_provider", "answer_grounding", "live", "answers",
})

SEGMENT_SPLIT = re.compile(r"[，,、。！？；\n]")
CAUSAL_PREDICATE_RE = re.compile(
    r"(导致|造成|引起|引发|致使|使得|使(?!用|得|然)|因为|由于|归因于|归咎于|带来|"
    r"是[^，。；]{1,24}的(?:根因|主因|原因)|根因|由此造成)")
# Hedges only neutralise a claim inside the *same* clause: a hedge in a
# neighbouring clause must never launder a definite causal statement.
CAUSAL_HEDGE_TOKENS = (
    "可能", "或许", "也许", "尚不能", "还不能", "不能证明", "无法确认",
    "无法唯一归因", "无法判断", "尚不清楚", "不足以", "相关", "相关性",
    "待验证", "需要进一步", "假设", "推测", "如果", "若", "不能直接证明",
    "不等于", "不是", "未见",
)
# A limitation only counts when it is tied (same clause) to a metric name or a
# declared limit: a bare "仅供参考" never is a proxy disclosure.
PROXY_LIMIT_PREDICATES = ("不能", "无法", "仅", "只", "近似", "不等同", "不覆盖",
                          "不足以", "只是")


def _causal_definite_segments(text: str) -> list[str]:
    """Clauses that assert a cause without hedging *inside the same clause*."""

    out: list[str] = []
    for segment in SEGMENT_SPLIT.split(text or ""):
        if not CAUSAL_PREDICATE_RE.search(segment):
            continue
        if any(token in segment for token in CAUSAL_HEDGE_TOKENS):
            continue
        out.append(segment.strip())
    return out


def _proxy_names(raw: Any) -> list[str]:
    """Normalise ``expected.proxy_metric`` (str | list) into declared names."""

    if raw is None:
        return []
    items = raw if isinstance(raw, (list, tuple, set)) else [raw]
    return [str(item).strip() for item in items if str(item or "").strip()]


def _visible_metric_labels(run: Any) -> list[str]:
    """Metric labels that reach the user: chart/table titles and column names.

    A chart or table is a deliverable, so a proxy relabelled as the target
    metric is a violation even when the prose says the opposite (Spec §6.3).
    """

    labels: list[str] = []
    calls = run if isinstance(run, (list, tuple)) else getattr(run, "tool_calls", None) or ()
    for call in calls:
        name = str(call.get("name") or "")
        if "Table" not in name and "Chart" not in name:
            continue
        payload = call.get("input") or {}
        if not isinstance(payload, dict):
            continue
        title = payload.get("title") or payload.get("name")
        if isinstance(title, str) and title.strip():
            labels.append(title.strip())
        for column in payload.get("columns") or ():
            if not isinstance(column, dict):
                continue
            for key in ("label", "name", "title"):
                value = column.get(key)
                if isinstance(value, str) and value.strip():
                    labels.append(value.strip())
    return labels


def _proxy_impersonations(target: str, proxies: list[str],
                          labels: Any) -> list[str]:
    """Labels that present the target metric without naming the proxy."""

    bad: list[str] = []
    for label in labels or ():
        if target and target in label and not any(proxy in label for proxy in proxies):
            bad.append(label)
    return bad


SCOPE_KEYWORDS = ("口径", "统计范围", "范围", "过滤", "仅统计", "排除", "定义")
# Disclosure language accepted as an explicit limitation.  The forecast /
# scenario vocabulary (assumption, projection, estimation, unverified,
# uncertainty, interval) is part of the contract:
# ``docs/specs/analysis-forecast-and-scenario-routing.md`` §7.3.  The list stays
# *discriminative* — a bare number ("下季度采购金额预测为 4,750.00 元。") contains
# none of these tokens and must still fail the check.
LIMITATION_KEYWORDS = ("限制", "不确定", "无法确认", "数据缺失", "缺月", "不足以", "无法唯一归因",
                       "可能", "样本", "假设", "推演", "推算", "未经验证", "不确定性", "区间")
ACTION_TEMPLATE_RE = re.compile(
    r"(建议|应当|需要|计划|拟|拟对|对[^，。；]{0,12}(?:部门|团队|采购|供应商|产线|仓库))"
)


def _numbers_in(text: str) -> set[float]:
    """Business numbers in an answer, thousands separators included.

    ``3,000.00`` is one number, not ``3`` plus ``000.00``: the token regex keeps
    the separator so a formatted amount is read the same way it is written.
    """
    out: set[float] = set()
    for raw in NUMBER_TOKEN_RE.findall(text or ""):
        raw = raw.replace(",", "")
        try:
            value = float(raw)
        except ValueError:
            continue
        if abs(value) >= 100 or "." in raw:
            out.add(round(value, 6))
    return out


def score_answer(case: dict, answer: str, allowed_numbers: set[float],
                 evidence_labels: Any = None) -> tuple[list[Check], dict[str, bool]]:
    """Score one natural-language answer against the case's declared rules.

    ``evidence_labels`` carries the visible chart/table labels of the turn
    (``run.tool_calls``); the text-only callers pass nothing and keep the same
    contract.
    """

    from bi_agent.tools.analysis_policy import (
        extract_action_items,
        has_effective_action,
        has_root_cause_section,
    )

    text = answer or ""
    requirements = list(case.get("answer_requirements") or [])
    expected = case.get("expected") or {}
    checks: list[Check] = []
    metrics: dict[str, bool] = {}

    if "must_include_effective_action_section" in requirements:
        ok = has_effective_action(text)
        checks.append(Check("answer.effective_action_section", ok, True, ok))

    if "action_items_must_be_specific_and_traceable" in requirements:
        items = extract_action_items(text)
        concrete = [i for i in items if len(str(i)) >= 8 and not ACTION_TEMPLATE_RE.fullmatch(str(i))]
        checks.append(Check("answer.specific_action_items", bool(items) and bool(concrete),
                            ">=1 concrete item", len(items)))

    if "must_state_metric_and_scope" in requirements:
        metric = str(expected.get("metric") or "")
        metric_name = ""
        if metric:
            from bi_agent.ontology.store import OntologyStore

            try:
                store = OntologyStore.from_xlsx(str(ONTOLOGY_DIR / "analytics_golden_ontology.xlsx"))
                m = store.metrics.get(metric)
                metric_name = m.name if m else ""
            except Exception:  # noqa: BLE001
                metric_name = ""
        named = bool(metric_name) and metric_name in text
        scoped = any(k in text for k in SCOPE_KEYWORDS)
        checks.append(Check("answer.metric_named", named, metric_name or "(metric)", named))
        checks.append(Check("answer.scope_disclosed", scoped, True, scoped))

    if "must_state_limitations" in requirements:
        ok = any(k in text for k in LIMITATION_KEYWORDS)
        checks.append(Check("answer.limitations", ok, True, ok))

    # --- causal supervision -----------------------------------------------
    # A definite claim in one clause must not be laundered by a hedge in the
    # next; a definite claim is allowed only when the case declares support and
    # the answer cites it.
    causal_violation_expected = bool(expected.get("expect_causal_violation"))
    declared_claims = [str(c).strip() for c in (expected.get("causal_claims") or [])
                       if str(c or "").strip()]
    definite = _causal_definite_segments(text)
    if causal_violation_expected or CAUSAL_REQUIREMENT in requirements \
            or declared_claims or definite:
        support = [str(mark).strip() for mark in (expected.get("causal_support") or [])
                   if str(mark or "").strip()]
        backed = any(mark in text for mark in support)
        violation = bool(definite) and not backed
        if causal_violation_expected:
            metrics[CAUSAL_DETECTION_METRIC] = violation
            checks.append(Check(
                f"{CAUSAL_CHECK}.negative_control", violation,
                "planted unsupported causal claim detected",
                definite[:2] if definite else "no definite claim"))
        else:
            checks.append(Check(
                CAUSAL_CHECK, not violation, "no unsupported causal claim",
                definite[:2] if violation else ("no definite claim" if not definite
                                                else f"backed by {support[:2]}")))
            if definite or declared_claims:
                metrics[CAUSAL_RATE_METRIC] = violation

    # --- proxy supervision -------------------------------------------------
    # The denominator is decided by the case declaration, never by the answer:
    # forgetting to mention the proxy cannot remove a case from the metric.
    target_metric = str(expected.get("target_metric") or "").strip()
    proxies = _proxy_names(expected.get("proxy_metric"))
    proxy_none = bool(expected.get("proxy_none"))
    direct_metric = bool(expected.get("used_direct_metric"))
    proxy_miss_expected = bool(expected.get("expect_proxy_miss"))
    proxy_limits = [str(item).strip() for item in (expected.get("proxy_limits") or [])
                    if str(item or "").strip()]
    if proxy_miss_expected or proxy_none or (proxies and not direct_metric):
        impersonated = _proxy_impersonations(target_metric, proxies, evidence_labels)
        if proxy_none:
            clarified = bool(target_metric) and target_metric in text and any(
                any(pred in segment for pred in PROXY_LIMIT_PREDICATES)
                for segment in SEGMENT_SPLIT.split(text) if target_metric in segment)
            disclosed = clarified
            detail = ("clarification or capability limit present" if clarified
                      else f"{target_metric or 'target'!r} presented without a limit")
        else:
            segments = SEGMENT_SPLIT.split(text)
            named = all(proxy in text for proxy in proxies) and (
                not target_metric or target_metric in text)
            limited = any(
                any(pred in segment for pred in PROXY_LIMIT_PREDICATES)
                and (any(proxy in segment for proxy in proxies)
                     or (target_metric and target_metric in segment)
                     or any(limit in segment for limit in proxy_limits))
                for segment in segments)
            disclosed = bool(named and limited and not impersonated)
            if impersonated:
                detail = f"relabelled as target metric: {impersonated[:2]}"
            elif not named:
                detail = f"proxy/target not named (target={target_metric!r}, proxies={proxies})"
            else:
                detail = "no same-clause limitation for the proxy relationship"
        if proxy_miss_expected:
            metrics[PROXY_DETECTION_METRIC] = not disclosed
            checks.append(Check(
                f"{PROXY_CHECK}.negative_control", not disclosed,
                "planted proxy-disclosure miss detected", detail))
        else:
            metrics[PROXY_RATE_METRIC] = disclosed
            checks.append(Check(PROXY_CHECK, disclosed,
                                "proxy relationship disclosed", detail))

    if "must_refuse_conclusion_without_evidence" in requirements:
        refused = any(k in text for k in ("证据不足", "无法给出", "不能给出", "无法确认", "不足以"))
        checks.append(Check("answer.refuses_unfounded_conclusion", refused, True, refused))

    if "must_handle_zero_denominator" in requirements:
        handled = any(k in text for k in ("分母", "为 0", "为零", "空值", "不计算", "无法计算"))
        checks.append(Check("answer.zero_denominator", handled, True, handled))

    if "must_not_invent_missing_month_data" in requirements:
        ok = not re.search(r"2025-03[^，。；]{0,12}(0|零)", text)
        checks.append(Check("answer.no_invented_month", ok, True, ok))

    if "must_cite_queried_numbers" in requirements:
        found = _numbers_in(text) & allowed_numbers
        checks.append(Check("answer.cites_fixture_numbers", bool(found),
                            ">=1 fixture number", sorted(found)[:5]))

    if expected.get("unsupported_numbers"):
        # Negative control: the answer is supposed to cite a number this case
        # never queried, and ``_grounding_checks``/``grounding.answer_grounded``
        # already asserts that it is caught.  Scoring it as a real regression
        # would invert the test.
        pass
    else:
        numbers = _numbers_in(text)
        unsupported = {n for n in numbers if not _is_grounded(n, allowed_numbers)}
        if numbers:
            metrics["unsupported_number_rate"] = bool(unsupported)
            checks.append(Check("answer.numbers_grounded", not unsupported,
                                "all numbers from fixture", sorted(unsupported)[:6]))

    forbidden_hits = [token for token in (case.get("forbidden") or [])
                      if token and token in text]
    checks.append(Check("answer.no_forbidden_token", not forbidden_hits, [], forbidden_hits))

    if "must_include_effective_action_section" in requirements or "must_state_metric_and_scope" in requirements:
        checks.append(Check("answer.has_root_cause_or_scope",
                            has_root_cause_section(text) or any(k in text for k in SCOPE_KEYWORDS),
                            True, True))
    return checks, metrics


def collect_allowed_numbers(cases: list[dict], ctx: EvalContext) -> set[float]:
    """Collect every number the fixtures can legitimately produce."""

    allowed: set[float] = set()
    for case in cases:
        if case.get("evaluator") != "sql":
            continue
        expected = case["expected"]
        try:
            conn = ctx.sqlite_readonly(case["fixture"]["db"])
            try:
                cur = conn.cursor()
                cur.execute(case["fixture"]["sql"])
                for row in cur.fetchall():
                    for cell in row:
                        if isinstance(cell, (int, float)) and not isinstance(cell, bool):
                            allowed.add(round(float(cell), 6))
            finally:
                conn.close()
        except Exception:  # noqa: BLE001 - fixture problems surface as failing cases
            continue
        for value in [expected.get("value")] + list(expected.get("rows") or []):
            cells = value if isinstance(value, list) else [value]
            for cell in cells:
                if isinstance(cell, (int, float)) and not isinstance(cell, bool):
                    allowed.add(round(float(cell), 6))
    for base in (2025, 2024, 180, 100, 0):
        allowed.add(float(base))
    allowed.update(float(n) for n in range(0, 120))
    return allowed


# ---------------------------------------------------------------------------
# live driver (opt-in)
# ---------------------------------------------------------------------------
PROVIDER_ENV = {
    "anthropic": ("ANTHROPIC_API_KEY",),
    "qwen": ("DASHSCOPE_API_KEY", "QWEN_API_KEY"),
    "deepseek": ("DEEPSEEK_API_KEY",),
    "team": ("TEAM_API_KEY",),
}


def load_provider_env() -> None:
    """Load the repo-root ``.env`` the same way ``bi_agent.web.__main__`` does.

    Only the live suite needs it, so offline suites stay hermetic and never
    depend on a developer's local credentials file.  Real environment variables
    always win.
    """
    try:
        from dotenv import load_dotenv
    except Exception:  # noqa: BLE001 - dotenv is optional for offline suites
        return
    for candidate in (REPO_ROOT / ".env", Path.cwd() / ".env"):
        if candidate.is_file():
            load_dotenv(candidate, override=False)
            return


def provider_available(provider: str) -> bool:
    import os

    names = PROVIDER_ENV.get(provider, ())
    if not names:
        return False
    if not any(str(os.environ.get(n, "")).strip() for n in names):
        return False
    if provider == "team" and not str(os.environ.get("TEAM_BASE_URL", "")).strip():
        return False
    return True


def build_live_session(ctx: EvalContext, case: dict, *, db: Optional[str] = None):
    """Build one throw-away WebSession bound to *this case's* fixture DB.

    The database is never guessed: it comes from ``case.fixture.db`` through
    :func:`resolve_fixture_db`, so a finance case cannot silently read
    procurement data.  Everything the session writes (charts, conversations,
    logs) lands in a per-case temp workspace; ``dataset/conversations`` is never
    touched.
    """
    import os

    from bi_agent.web import app as web_app

    db = db or resolve_fixture_db(case)
    if not db:
        raise FixtureBindingError(
            f"{case.get('case_id')}: live case must declare fixture.db "
            f"(allowed: {list(FIXTURE_DBS)})")
    workspace = ctx.new_sandbox(f"live-{case.get('case_id')}")
    workspace.mkdir(parents=True, exist_ok=True)
    (workspace / "dataset").mkdir(exist_ok=True)
    agents_src = REPO_ROOT / ".claude" / "agents"
    if agents_src.is_dir():
        shutil.copytree(agents_src, workspace / ".claude" / "agents", dirs_exist_ok=True)
    previous_backend = os.environ.get("ONTOLOGY_BACKEND")
    os.environ["ONTOLOGY_BACKEND"] = "local"
    try:
        web_app.configure(
            cwd=str(workspace),
            ontology_path=str(ONTOLOGY_DIR / "analytics_golden_ontology.xlsx"),
            db_path=str(SQLITE_DIR / db),
            use_doris=False,
        )
        session = web_app._ensure_session(f"analytics-eval-{case.get('case_id')}")
    finally:
        if previous_backend is None:
            os.environ.pop("ONTOLOGY_BACKEND", None)
        else:
            os.environ["ONTOLOGY_BACKEND"] = previous_backend
    session.eval_workspace = workspace  # type: ignore[attr-defined]
    session.eval_db = db  # type: ignore[attr-defined]
    return session


class LiveHarness:
    """Per-case isolated live driver.

    Default behaviour is one workspace + WebSession + conversation id per case.
    Only cases that explicitly share ``fixture.conversation_group`` reuse a
    session, and then only in declaration order and inside one domain/database.
    """

    def __init__(self, ctx: EvalContext, provider: str = "team") -> None:
        self.ctx = ctx
        self.provider = provider
        self._sessions: dict[str, Any] = {}
        self._group_db: dict[str, str] = {}
        self._group_order: list[str] = []
        self.runs: list[dict] = []

    @staticmethod
    def group_key(case: dict) -> str:
        group = str((case.get("fixture") or {}).get("conversation_group") or "").strip()
        return group or str(case["case_id"])

    def session_for(self, case: dict):
        db = resolve_fixture_db(case)
        if not db:
            raise FixtureBindingError(
                f"{case.get('case_id')}: live case must declare fixture.db; "
                f"there is no default database")
        key = self.group_key(case)
        known = self._group_db.get(key)
        if known is not None and known != db:
            raise FixtureBindingError(
                f"{case.get('case_id')}: conversation_group {key!r} mixes "
                f"databases {known} and {db}; a group must stay inside one domain")
        if key not in self._sessions:
            session = build_live_session(self.ctx, case, db=db)
            self._sessions[key] = session
            self._group_db[key] = db
        if key not in self._group_order:
            self._group_order.append(key)
        self.runs.append({
            "case_id": case.get("case_id"),
            "domain": case.get("domain"),
            "fixture_db": db,
            "conversation_group": key,
            "workspace": str(getattr(self._sessions[key], "eval_workspace", "")),
            "session_id": key,
        })
        return self._sessions[key]

    def check_order(self, cases: list[dict]) -> list[str]:
        """A conversation group must be contiguous in the selected order."""
        problems: list[str] = []
        seen: set[str] = set()
        previous = ""
        for case in cases:
            key = self.group_key(case)
            if key != previous:
                if key in seen:
                    problems.append(
                        f"{case.get('case_id')}: conversation_group {key!r} is not "
                        f"contiguous in the run order")
                seen.add(key)
                previous = key
        return problems

    def leftovers(self) -> list[str]:
        """Temp files a finished live case must not leave behind."""
        out: list[str] = []
        for session in self._sessions.values():
            workspace = getattr(session, "eval_workspace", None)
            if workspace is None:
                continue
            for path in Path(workspace).rglob("*"):
                if path.is_file() and path.name.endswith(".tmp"):
                    out.append(str(path))
        return out


def run_live_turn(session, question: str, timeout_seconds: float = 300.0) -> dict:
    """Run one turn and return the answer text + actual tool chain."""

    answer_parts: list[str] = []
    tool_chain: list[str] = []
    tool_results: list[dict] = []
    policy: dict = {}
    error = ""
    blocked = False
    event_types: list[str] = []
    answer_validation: list[str] = []
    recovery: dict = {}
    deadline = time.monotonic() + timeout_seconds

    events = session.generate_turn(question)
    while True:
        try:
            event = next(events)
        except StopIteration:
            break
        except Exception as exc:  # noqa: BLE001 - surfaced as a failing case
            error = error or f"{type(exc).__name__}: {exc}"
            break
        kind = event.get("type")
        event_types.append(str(kind))
        if kind in ("text", "text_delta"):
            # ``generate_turn`` streams the narrative as ``text_delta``; the
            # sibling ``text`` variant is accepted for forward compatibility.
            answer_parts.append(str(event.get("text", "")))
        elif kind == "tool_start":
            tool_chain.append(str(event.get("name", "")))
        elif kind == "tool_result":
            tool_results.append({
                "name": str(event.get("name") or ""),
                "input": event.get("input"),
                "output": event.get("output"),
                "chart": event.get("chart"),
                "table": event.get("table"),
                "ontology_entities": event.get("ontology_entities"),
            })
        elif kind == "cognitive_policy":
            policy = event
        elif kind == "answer_validation":
            answer_validation.append(str(event.get("status", "")))
        elif kind == "recovery_state":
            recovery = {
                "status": event.get("status", ""),
                "step": event.get("current_step", ""),
                "error_code": event.get("error_code", ""),
            }
        elif kind == "awaiting_user_choice":
            # The turn paused on AskUser: no final narrative is expected.
            blocked = True
        elif kind == "answer_blocked":
            blocked = True
        elif kind == "session_superseded":
            error = error or "session_superseded"
        elif kind == "error":
            error = str(event.get("error") or event.get("message") or "error")
        elif kind == "done":
            break
        if time.monotonic() > deadline:
            error = error or "live turn timeout"
            break
    answer = "".join(answer_parts).strip()
    if not answer and not error and recovery.get("status") in TURN_STOP_STATUSES:
        # A structured terminal tool failure ends the turn before the
        # max-iteration fallback, so the user gets no narrative at all.  Report
        # the concrete failure instead of a bare "empty answer".
        error = f"tool_failure:{recovery.get('error_code') or recovery.get('status')}"
    usage = getattr(session, "cost_tracker", None)
    return {
        "answer": answer,
        "tool_chain": tool_chain,
        "tool_results": tool_results,
        "policy": policy,
        "error": error,
        "blocked": blocked,
        "event_types": event_types,
        "answer_validation": answer_validation,
        "recovery": recovery,
        "cost": getattr(usage, "total_cost", None) if usage is not None else None,
    }


def _live_cost(results: list[CaseResult]) -> Optional[float]:
    """Total provider cost of a live run, when the provider reports one."""
    total = 0.0
    seen = False
    for result in results:
        value = (result.run_meta or {}).get("cost")
        if value is None:
            continue
        try:
            total += float(value)
            seen = True
        except (TypeError, ValueError):
            continue
    return round(total, 6) if seen else None


def _canonical_sql(sql: Any) -> str:
    """Whitespace/case-insensitive SQL form, so formatting is not a diff."""
    text = re.sub(r"\s+", " ", str(sql or "")).strip().lower()
    return re.sub(r"\s*([(),=<>*+/%-])\s*", r"\1", text)


_ANSWER_SECTIONS = ("结论", "口径", "证据", "限制", "建议", "根因", "代理")


def _answer_structure(text: str) -> list[str]:
    """Which required narrative sections the answer actually carries."""
    return [name for name in _ANSWER_SECTIONS if name in (text or "")]


def live_run_signature(case: dict, run: dict, pool: CaseGroundingPool,
                       unsupported: set[float]) -> dict:
    """The semantic fingerprint compared across ``--repeat`` runs.

    Only stable, meaningful content is included: intent level, tool order,
    normalized SQL, the numbers the answer cited, evidence sources, chart types,
    the answer's section structure and unsupported citations.  Timestamps, token
    counts, durations and random session ids are deliberately excluded.
    """
    sqls = []
    charts: list[str] = []
    evidence: set[str] = set()
    for call in run.get("tool_results") or []:
        payload = call.get("input")
        if isinstance(payload, dict) and payload.get("sql"):
            sqls.append(_canonical_sql(payload.get("sql")))
        chart = call.get("chart")
        if isinstance(chart, dict):
            chart_type = chart.get("chart_type") or chart.get("type")
            if chart_type:
                charts.append(str(chart_type))
        if call.get("name"):
            evidence.add(str(call["name"]))
        for entity in call.get("ontology_entities") or []:
            evidence.add(str(entity))
    policy = run.get("policy") or {}
    return {
        "intent_level": str(policy.get("intent_level") or policy.get("mode") or ""),
        "tool_chain": list(run.get("tool_chain") or []),
        "sql": sqls,
        "answer_numbers": sorted(_numbers_in(run.get("answer") or "")),
        "evidence": sorted(evidence),
        "chart_types": charts,
        "unsupported": sorted(unsupported),
        "answer_structure": _answer_structure(run.get("answer") or ""),
        "recovery_status": str((run.get("recovery") or {}).get("status", "")),
    }


def eval_live(case: dict, ctx: EvalContext) -> CaseResult:
    harness = ctx.live_harness
    if harness is None:
        raise RuntimeError("the live suite requires ctx.live_harness")
    session = harness.session_for(case)
    db = resolve_fixture_db(case)
    run = run_live_turn(session, case["question"])
    pool = CaseGroundingPool(case, run.get("tool_results") or ())
    unsupported = pool.unsupported(run["answer"])
    expected = case.get("expected") or {}
    checks: list[Check] = []
    if run["error"]:
        checks.append(Check("live.no_error", False, "", run["error"]))
    checks.append(Check("live.answer_present", bool(run["answer"]), True, bool(run["answer"])))
    checks.extend(_grounding_checks("live", expected, unsupported))
    semantic_checks, semantic_metrics = score_answer(case, run["answer"], pool.pool)
    checks.extend(semantic_checks)
    result = _result_from(case, checks)
    result.metrics.update(semantic_metrics)
    if expected.get("unsupported_numbers"):
        result.metrics.pop("unsupported_number_rate", None)
        _record_grounding_metric(result, expected, unsupported)
    elif unsupported:
        result.metrics["unsupported_number_rate"] = True
    result.metrics["answer_schema_valid_rate"] = bool(run["answer"]) and not run["blocked"]
    result.signature = live_run_signature(case, run, pool, unsupported)
    result.evidence = {
        "answer": run["answer"][:4000],
        "tool_chain": run["tool_chain"],
        "policy": run["policy"],
        "blocked": run["blocked"],
        "error": run["error"],
        "event_types": run["event_types"],
        "answer_validation": run["answer_validation"],
        "recovery": run.get("recovery", {}),
        "fixture_db": db,
        "unsupported_numbers": sorted(unsupported)[:12],
        "tool_results": [
            {"name": call.get("name"), "input": call.get("input"),
             "output": str(call.get("output") or "")[:600]}
            for call in run.get("tool_results") or []
        ],
    }
    result.run_meta = {
        "case_id": case.get("case_id"),
        "domain": case.get("domain"),
        "fixture_db": db,
        "session_id": LiveHarness.group_key(case),
        "provider": harness.provider,
        "cost": run.get("cost"),
    }
    return result


# ---------------------------------------------------------------------------
# loading + dispatch
# ---------------------------------------------------------------------------
# ---------------------------------------------------------------------------
# evaluators: recorded-provider end-to-end replay
#
# These evaluators drive the REAL turn loop (bi_agent.web.session.WebSession)
# with a recorded provider stream, bound to the read-only eval fixtures.  See
# ``scripts/analytics_recorded_provider.py`` for the seam.
#
# Case-scoped grounding: a final answer may only cite numbers that THIS case's
# own tool results produced (plus numbers the question itself states).  The
# cross-case pool used by the live suite is deliberately NOT part of the gate,
# because it would let a case cite another case's plausible-looking number.
# ---------------------------------------------------------------------------
TABLE_REF_RE = re.compile(r"\b(?:from|join)\s+([A-Za-z_][A-Za-z0-9_$.]*)", re.IGNORECASE)
NUMBER_TOKEN_RE = re.compile(r"-?\d+(?:[.,]\d+)*")
PERCENT_RE = re.compile(r"\d+(?:\.\d+)?\s*%")
STRUCTURAL_NUMBERS = frozenset({0.0, 1.0, 2.0, 3.0, 4.0, 5.0, 6.0, 7.0, 8.0,
                                9.0, 10.0, 11.0, 12.0, 2024.0, 2025.0, 2026.0})


def _parse_number_tokens(text: str) -> set[float]:
    """Every number written in an answer, including small integers.

    Small integers are *not* dropped by magnitude here: ``5`` may be a real
    quantity and ``10`` may be a percentage.  They are exempted only when the
    text shows them in a structural role (list index, step number, date part),
    which is decided by :func:`_structural_numbers`, not by the value.
    """
    out: set[float] = set()
    for raw in NUMBER_TOKEN_RE.findall(text or ""):
        raw = raw.replace(",", "")
        try:
            value = float(raw)
        except ValueError:
            continue
        out.add(round(value, 6))
    return out


# A number is "structural" when the surrounding text gives it a non-business
# role.  These are positional rules, not magnitude rules: the same value can be
# structural in one sentence and a real result in another.
_STRUCTURAL_CONTEXT_RES = (
    # A date or a period: 2025 年 / 2025 年 3 月 / 2025-03 / 2025/03 / 2025Q2.
    # The suffix is required on purpose: a bare "2025" is a *number* and has to
    # be traceable to the current case's own query, exactly like any other
    # result.  The numeric form also has to be a real month/day range, so a
    # decimal result like "2025.00 元" is not mistaken for a date.
    re.compile(r"(?:19|20)\d{2}\s*年(?:\s*\d{1,2}\s*月)?"),
    re.compile(r"(?:19|20)\d{2}\s*(?:季度|Q[1-4])"),
    re.compile(r"(?:19|20)\d{2}[-/.](?:0[1-9]|1[0-2])"
               r"(?:[-/.](?:0[1-9]|[12]\d|3[01]))?"),
    # month / day references: "2 月" "6 个月" "15 日" "1—6 月" "3-5 月"
    re.compile(r"(?:^|[^\d.])\d{1,2}\s*个?月"),
    re.compile(r"\d{1,2}\s*[—\-~～至到]\s*\d{1,2}\s*个?月"),
    re.compile(r"\d{1,2}\s*日"),
    # ordered list markers: "1." "2、" "3)" "1）" at line start or after punctuation
    re.compile(r"(?:^|\n|[：:；;、，,])\s*\d{1,2}\s*[.、)）]", re.MULTILINE),
    re.compile(r"[（(]\s*\d{1,2}\s*[)）]"),
    # a stated target/threshold ("复核条件为低于 40%") is a condition, not a result
    re.compile(r"(?:低于|高于|不超过|超过|控制在|至少|至多|达到|小于|大于)\s*\d[\d,]*(?:\.\d+)?\s*%?"),
    # step / section wording: a reference to "第 3 步" or a procedure of
    # "5 个步骤" is structure.  Counts that are themselves business claims
    # ("共 5 条建议"、"涵盖 3 个维度") are deliberately NOT exempt: a wrong count
    # of recommendations is exactly the kind of fabricated number the gate must
    # catch, so it has to be traceable to this case's own tool output.
    re.compile(r"第\s*\d{1,2}\s*(?:步|点|条|项|个|部分|阶段|章)"),
    re.compile(r"\d{1,2}\s*(?:步|个步骤|阶段)"),
)
_PERCENT_TOKEN_RE = re.compile(r"(-?\d[\d,]*(?:\.\d+)?)\s*%")


def _structural_numbers(text: str) -> set[float]:
    """Numbers that the text itself marks as structure, not as a result."""
    out: set[float] = set()
    for pattern in _STRUCTURAL_CONTEXT_RES:
        for match in pattern.finditer(text or ""):
            for raw in NUMBER_TOKEN_RE.findall(match.group(0)):
                try:
                    out.add(round(float(raw.replace(",", "")), 6))
                except ValueError:
                    continue
    return out


def _percent_numbers(text: str) -> set[float]:
    """Numbers that the text wrote with a percent sign."""
    out: set[float] = set()
    for raw in _PERCENT_TOKEN_RE.findall(text or ""):
        try:
            out.add(round(float(raw.replace(",", "")), 6))
        except ValueError:
            continue
    return out


def _numbers_from_text_pool(text: str) -> set[float]:
    """Numbers a tool really produced, for use as grounding evidence.

    Structural filtering happens when *citing* a number, not when collecting
    evidence: the pool must keep every number the query returned.
    """
    return _parse_number_tokens(text)


def _is_grounded(value: float, pool: set[float],
                 percent_pool: Optional[set[float]] = None) -> bool:
    """True when *value* is a pool number or an auditable transform of one.

    Allowed transforms are deliberately narrow and auditable:

    * display rounding (``3878.4567`` written as ``3878.46``);
    * a ratio rendered as a percentage (``0.3878`` -> ``38.78%``), only when
      the pool number really is a ratio;
    * a percentage restated as a ratio (``38.78%`` -> ``0.3878``), only when
      the pool number was written with a percent sign.

    A blanket ``/100`` or ``*100`` is *not* allowed: it would let a case cite
    ``38.78`` for a pool value of ``3878`` (or ``0.05`` for ``5``), which is
    exactly the kind of cross-case copy the gate must catch.
    """
    def close(a: float, b: float) -> bool:
        return abs(a - b) <= max(1e-6, 1e-6 * abs(b))

    percent_pool = percent_pool or set()
    for candidate in pool:
        if close(value, candidate):
            return True
        for digits in (0, 1, 2, 3, 4):
            if close(value, round(candidate, digits)):
                return True
        if abs(candidate) <= 1.5:
            # A ratio rendered as a percentage: 0.38788 -> "38.79%".
            for digits in (0, 1, 2, 4):
                if close(value, round(candidate * 100, digits)):
                    return True
        if candidate in percent_pool:
            # A percentage restated as a ratio: 38.78% -> 0.3878.
            for digits in (2, 4, 6):
                if close(value, round(candidate / 100, digits)):
                    return True
        # Percentages are commonly written with one or two decimals.
        for digits in (1, 2):
            if close(value, round(candidate, digits)):
                return True
    return False


def _output_texts(item: Any) -> list[str]:
    """Every text surface of one tool call/result, for grounding evidence."""
    if isinstance(item, str):
        return [item]
    if isinstance(item, dict):
        out: list[str] = []
        for key in ("output", "content", "text", "input", "result", "chart", "table"):
            value = item.get(key)
            if value is not None:
                out.append(str(value))
        return out
    return [str(item)]


class CaseGroundingPool:
    """Case-scoped grounding pool: this case's own evidence only.

    A number is allowed when it is

    * stated by the current question (or an earlier turn of the same
      conversation group), or
    * produced by this case's own tool calls, or
    * declared by the case as a reviewed structural constant
      (``expected.allowed_numbers``).

    Numbers from other cases, other domains, the global golden answers or
    another conversation are never allowed.
    """

    def __init__(self, case: dict, outputs: Any = ()) -> None:
        pool: set[float] = set()
        percent: set[float] = set()
        for item in outputs or ():
            for text in _output_texts(item):
                pool |= _numbers_from_text_pool(text)
                percent |= _percent_numbers(text)
        expected = case.get("expected") or {}
        declared: set[float] = set()
        for value in expected.get("allowed_numbers") or []:
            try:
                declared.add(round(float(value), 6))
            except (TypeError, ValueError):
                continue
        pool |= declared
        texts = [case.get("question") or ""]
        texts += [str(turn.get("content") or "") for turn in case.get("conversation") or []]
        texts += [str(t) for t in (case.get("fixture") or {}).get("group_history") or []]
        for text in texts:
            pool |= _numbers_from_text_pool(text)
            percent |= _percent_numbers(text)
        self.pool = pool
        self.percent = percent
        self.declared = declared

    def unsupported(self, text: str) -> set[float]:
        structural = _structural_numbers(text)
        return {n for n in _parse_number_tokens(text)
                if n not in self.declared
                and n not in structural
                and not _is_grounded(n, self.pool, self.percent)}


class RecordedPool(CaseGroundingPool):
    """Backwards-compatible constructor over a recorded replay run."""

    def __init__(self, case: dict, run: Any) -> None:
        calls: list[Any] = []
        for call in getattr(run, "tool_calls", []) or []:
            calls.extend(_output_texts(
                {k: call.get(k) for k in ("output", "input")} if isinstance(call, dict) else call))
        super().__init__(case, calls)


def _load_recorded_run(case: dict, ctx: EvalContext):
    scripts_dir = str(Path(__file__).resolve().parent)
    if scripts_dir not in sys.path:
        sys.path.insert(0, scripts_dir)
    from analytics_recorded_provider import (  # noqa: PLC0415
        TranscriptError, load_transcript, run_recorded_turns,
    )

    fixture = case.get("fixture") or {}
    rel = str(fixture.get("provider") or "")
    if not rel:
        raise TranscriptError("case does not declare fixture.provider")
    transcript = load_transcript(EVAL_ROOT / rel)
    db = resolve_fixture_db(case)
    if not db:
        raise FixtureBindingError(
            f"{case.get('case_id')}: replay case must declare fixture.db")
    declared = {str(turn.get("db")) for turn in transcript.get("turns") or []
                if turn.get("db")}
    wrong = sorted(d for d in declared if d != db)
    if wrong:
        raise FixtureBindingError(
            f"{case.get('case_id')}: transcript declares {wrong} but fixture.db is "
            f"{db!r}; a recording may not switch databases mid-case")
    workspace = ctx.new_sandbox(case["case_id"])
    run = run_recorded_turns(
        case["case_id"],
        transcript["turns"],
        fixture_db=db,
        workspace=workspace,
        tools_override=fixture.get("tools_override"),
    )
    return transcript, run


def _sql_identifier_tables(sql: str) -> set[str]:
    return {match.strip('"`[]').lower().split(".")[-1] for match in TABLE_REF_RE.findall(sql)}


def _execute_reference(ctx: EvalContext, db: str, sql: str) -> list[list[Any]]:
    conn = ctx.sqlite_readonly(db)
    try:
        cur = conn.cursor()
        cur.execute(sql)
        return [list(row) for row in cur.fetchall()]
    finally:
        conn.close()


def _record_grounding_metric(result: CaseResult, expected: dict,
                             unsupported: set[float]) -> None:
    """Report the right metric for normal cases and for negative controls.

    A negative control deliberately cites a number this case never produced, so
    it must not feed ``unsupported_number_rate`` (which gates "no case may cite
    a number it did not query").  It reports ``unsupported_number_detection_rate``
    instead: the supervision caught the planted number.
    """
    declared = {round(float(n), 6) for n in (expected.get("unsupported_numbers") or [])}
    if declared:
        detected = all(any(abs(n - u) <= max(1e-6, abs(n) * 1e-6) for u in unsupported)
                       for n in declared)
        result.metrics["unsupported_number_detection_rate"] = detected
        return
    # Always record the metric for a grounding-checked answer: the value is
    # "this answer cited a number it never queried", so a clean answer must
    # contribute a real ``False`` to the denominator.  Only recording the
    # violations would make the reported rate look like it covered one case.
    result.metrics["unsupported_number_rate"] = bool(unsupported)


def _tool_execution_checks(prefix: str, run: Any) -> list[Check]:
    """Prove the recorded replay really *executed* the tools it reports.

    A turn that emits ``tool_result`` events without going through the Tool
    Runtime boundary would still show the model's planned tool chain, so the
    chain assertion alone cannot tell "the tool ran" from "the model described
    it".  Two structural facts close that gap:

    * every ``tool_result`` event must map to a session execution record;
    * every *successful* SQL result must carry the production
      ``[RESULT_METADATA]`` block, which only a real, normalized query produces.
    """
    checks: list[Check] = []
    unexecuted = [str(call.get("name")) for call in run.tool_calls
                  if call.get("event") == "tool_result" and not call.get("status")]
    checks.append(Check(f"{prefix}.execution_audit", not unexecuted,
                        "every tool_result has a session execution record",
                        unexecuted[:6]))
    bad_sql = [str(call.get("name")) for call in run.tool_calls
               if call.get("name") == "Ontology-FactQuery"
               and str(call.get("status") or "").upper() in ("", "SUCCEEDED")
               and "[RESULT_METADATA]" not in str(call.get("output") or "")]
    checks.append(Check(f"{prefix}.sql_result_metadata", not bad_sql,
                        "every successful SQL call carries a normalized result",
                        bad_sql[:6]))
    return checks


def _chart_file_checks(prefix: str, expected: dict, run: Any) -> list[Check]:
    """Assert against the chart HTML a recorded replay actually wrote.

    ``expected.chart_files`` is a real assertion, not documentation: an absent
    token list is how the golden set proves a chart title was HTML-escaped and
    that no script/credential leaked into a rendered artifact.
    """
    rules = expected.get("chart_files")
    if not rules:
        return []
    workspace = getattr(run, "workspace", None)
    files: list[Path] = []
    if workspace is not None:
        charts_dir = Path(workspace) / "dataset" / "charts"
        root = charts_dir if charts_dir.is_dir() else Path(workspace)
        files = sorted(path for path in root.rglob("*") if path.is_file())
    checks = [Check(f"{prefix}.chart_files_present",
                    len(files) >= int(rules.get("min_count", 0)),
                    f">={rules.get('min_count', 0)} chart file(s)", len(files))]
    blob = ""
    for path in files:
        try:
            blob += path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
    for token in rules.get("contains") or []:
        checks.append(Check(f"{prefix}.chart_contains[{str(token)[:24]}]",
                            str(token) in blob, str(token), blob[:200]))
    for token in rules.get("absent") or []:
        checks.append(Check(f"{prefix}.chart_absent[{str(token)[:24]}]",
                            str(token) not in blob if files else True,
                            f"{token} must not appear", blob[:200]))
    return checks


def _schema_valid(expected: dict, run: Any, unsupported: set[float]) -> bool:
    """A well-formed answer: no provider error, and no stray numbers.

    Negative-control cases (``expected.unsupported_numbers``) are *expected* to
    cite ungrounded numbers, so only the provider-error half applies to them.
    """
    if run.errors:
        return False
    if unsupported and not expected.get("unsupported_numbers"):
        return False
    return True


def _grounding_checks(prefix: str, expected: dict,
                      unsupported: set[float]) -> list[Check]:
    """The grounding gate, plus an explicit negative control.

    A normal case asserts that *no* number in the answer is ungrounded — the
    answer may only cite numbers this very case produced.  Declaring
    ``expected.unsupported_numbers`` flips the case into a negative control: the
    recorded answer is *supposed* to cite numbers this case never produced
    (typically a number that another case legitimately produced) and this gate
    must catch each of them.  That is what stops a cross-case global pool from
    quietly making a copied number look grounded.
    """
    declared = sorted({round(float(n), 6) for n in (expected.get("unsupported_numbers") or [])})
    if declared:
        def seen(number: float) -> bool:
            return any(abs(number - u) <= max(1e-6, abs(number) * 1e-6) for u in unsupported)

        missing = [n for n in declared if not seen(n)]
        return [Check(f"{prefix}.unsupported_detected", not missing, declared,
                      sorted(unsupported)[:6])]
    if expected.get("grounding", True):
        return [Check(f"{prefix}.answer_grounded", not unsupported,
                      "every number traceable to this case", sorted(unsupported)[:6])]
    return []


def eval_recorded_provider(case: dict, ctx: EvalContext) -> CaseResult:
    """Drive the production turn loop from a recorded provider stream."""
    expected = case.get("expected") or {}
    checks: list[Check] = []
    evidence: dict[str, Any] = {}

    try:
        transcript, run = _load_recorded_run(case, ctx)
    except Exception as exc:  # noqa: BLE001 - reported as a failing case
        checks.append(Check("recorded.replay", False, "a clean replay",
                            f"{type(exc).__name__}: {exc}"))
        result = _result_from(case, checks)
        result.metrics["answer_schema_valid_rate"] = False
        result.evidence = evidence
        return result

    checks.append(Check("recorded.replay", True, "a clean replay", "ok"))
    checks.append(Check("recorded.no_provider_error", not run.errors, [], run.errors))
    checks.append(Check("recorded.not_superseded", not run.superseded, False, run.superseded))
    checks.extend(_tool_execution_checks("recorded", run))

    declared_calls = sum(1 for turn in transcript["turns"]
                         for event in turn["events"]
                         if event.get("type") == "tool_start")
    checks.append(Check("recorded.provider_call_budget",
                        len(run.provider_calls) <= len(run.tool_calls) + len(transcript["turns"]) + 2,
                        "bounded re-prompt count", len(run.provider_calls)))

    chain = expected.get("tool_chain")
    if chain is not None:
        actual = run.tool_names
        checks.append(Check("recorded.tool_chain", actual == list(chain), list(chain), actual))

    for name, rules in (expected.get("tool_inputs") or {}).items():
        calls = [c for c in run.tool_calls if c.get("name") == name]
        checks.append(Check(f"recorded.tool_present[{name}]", bool(calls), ">=1 call", len(calls)))
        if not calls:
            continue
        blob = json.dumps([c.get("input") for c in calls], ensure_ascii=False)
        for fragment in rules.get("input_contains", []):
            checks.append(Check(f"recorded.input_contains[{name}][{fragment[:24]}]",
                                fragment in blob, fragment, blob[:200]))
        for fragment in rules.get("input_absent", []):
            checks.append(Check(f"recorded.input_absent[{name}][{fragment[:24]}]",
                                fragment not in blob, "absent", "present"))

    for name, rules in (expected.get("tool_results") or {}).items():
        outputs = " ".join(str(c.get("output") or "") for c in run.tool_calls
                           if c.get("name") == name)
        for fragment in rules.get("contains", []):
            checks.append(Check(f"recorded.result_contains[{name}][{str(fragment)[:24]}]",
                                str(fragment) in outputs, fragment, outputs[:200]))

    for name, want in (expected.get("tool_status") or {}).items():
        statuses = [c.get("status") for c in run.tool_calls if c.get("name") == name]
        checks.append(Check(f"recorded.tool_status[{name}]", want in statuses, want, statuses))

    if expected.get("policy_mode"):
        modes = [e.get("mode") for e in run.events if e.get("type") == "cognitive_policy"]
        checks.append(Check("recorded.policy_mode", expected["policy_mode"] in modes,
                            expected["policy_mode"], modes))

    if expected.get("recovery_status"):
        status = str(run.session.recovery_state.get("status") or "")
        checks.append(Check("recorded.recovery_status", status == expected["recovery_status"],
                            expected["recovery_status"], status))

    if expected.get("final_narrative") is False:
        checks.append(Check("recorded.no_narrative", not run.text.strip(), "", run.text[:120]))

    for fragment in expected.get("final_text_contains", []):
        checks.append(Check(f"recorded.text_contains[{str(fragment)[:24]}]",
                            str(fragment) in run.text, fragment, run.text[:200]))
    for fragment in expected.get("final_text_absent", []):
        checks.append(Check(f"recorded.text_absent[{str(fragment)[:24]}]",
                            str(fragment) not in run.text, "absent", "present"))

    checks.extend(_chart_file_checks("recorded", expected, run))

    pool = RecordedPool(case, run)
    unsupported = pool.unsupported(run.text)
    checks.extend(_grounding_checks("recorded", expected, unsupported))

    # Offline truthfulness supervision.  Exactly two answer checks join the
    # recorded path (causal / proxy); ``unsupported_number_rate`` keeps coming
    # from ``_record_grounding_metric`` below and is never overwritten here.
    truth_checks, truth_metrics = score_answer(
        case, run.text, pool.pool,
        evidence_labels=_visible_metric_labels(run.tool_calls))
    checks.extend(check for check in truth_checks
                  if check.name.startswith(TRUTHFULNESS_CHECK_PREFIXES))
    truth_metrics = {name: value for name, value in truth_metrics.items()
                     if name in TRUTHFULNESS_METRICS}

    forbidden_hits = [token for token in (case.get("forbidden") or [])
                      if token and token in run.text]
    checks.append(Check("recorded.no_forbidden_token", not forbidden_hits, [], forbidden_hits))

    evidence.update({
        "provider": case["fixture"].get("provider"),
        "provider_calls": len(run.provider_calls),
        "tool_chain": run.tool_names,
        "tool_status": [c.get("status") for c in run.tool_calls],
        "answer": run.text[:600],
        "recovery": run.session.recovery_state.get("status"),
        "unsupported_numbers": sorted(unsupported)[:8],
        "errors": run.errors[:4],
    })
    result = _result_from(case, checks)
    result.metrics.update({
        "tool_route_accuracy": all(c.ok for c in checks if c.name.startswith("recorded.tool_chain")),
        "answer_schema_valid_rate": _schema_valid(expected, run, unsupported),
        "evidence_coverage": bool(run.tool_calls) or not expected.get("tool_chain"),
    })
    result.metrics.update(truth_metrics)
    _record_grounding_metric(result, expected, unsupported)
    result.evidence = evidence
    return result


# ---------------------------------------------------------------------------
# evaluator: recorded_session_isolation
# ---------------------------------------------------------------------------
ISOLATION_EVALUATOR = "recorded_session_isolation"

# Check names with this prefix form the ``cross_session_leak_rate`` metric: any
# one of them failing means two sessions observed each other's state.
LEAK_PREFIX = "isolation.leak."


def _iso_identity(run: Any) -> dict:
    """What one session privately owns: workspace, tool records, context."""
    session = getattr(run, "session", None)
    records = list(getattr(session, "tool_execution_records", []) or [])
    context_obj = getattr(session, "analysis_context", None)
    context = dict(context_obj.to_dict()) if context_obj is not None else {}
    return {
        "cwd": str(getattr(session, "cwd", "") or ""),
        "tool_use_ids": sorted({str(r.get("tool_use_id") or "") for r in records} - {""}),
        "context": context,
        "messages": list(getattr(session, "messages", []) or []),
    }


def _workspace_files(workspace: Any) -> set[str]:
    root = Path(workspace) if workspace else None
    if root is None or not root.is_dir():
        return set()
    return {str(path.relative_to(root)) for path in root.rglob("*") if path.is_file()}


def eval_recorded_session_isolation(case: dict, ctx: EvalContext) -> CaseResult:
    """Cross-session sentinels over the *real* turn loop.

    ``fixture.sessions`` lists two or more recorded sessions.  Each *group* runs
    in its own real ``WebSession`` with real tools; a session that declares a
    ``group`` shares one WebSession with the other members of that group, in
    declared order.  The case then asserts that different groups cannot observe
    each other, and that a shared group inherits exactly what it declared.

    The recording only supplies the model's decisions.  A number in the peer's
    answer is the *detector*; the structural checks (workspace, tool records,
    context, message history, conversation store) are what feed
    ``cross_session_leak_rate``.
    """
    scripts_dir = str(Path(__file__).resolve().parent)
    if scripts_dir not in sys.path:
        sys.path.insert(0, scripts_dir)
    from analytics_recorded_provider import (  # noqa: PLC0415
        load_transcript, run_recorded_turns,
    )

    expected = case.get("expected") or {}
    fixture = case.get("fixture") or {}
    specs = list(fixture.get("sessions") or [])
    checks: list[Check] = []
    evidence: dict[str, Any] = {}

    if len(specs) < 2:
        checks.append(Check("isolation.two_sessions", False, ">=2 sessions", len(specs)))
        result = _result_from(case, checks)
        result.evidence = evidence
        return result

    try:
        db = resolve_fixture_db(case)
        grouped: dict[str, list[tuple[dict, dict]]] = {}
        order: list[str] = []
        for spec in specs:
            transcript = load_transcript(EVAL_ROOT / str(spec["provider"]))
            declared = {str(turn.get("db")) for turn in transcript.get("turns") or []
                        if turn.get("db")}
            wrong = sorted(d for d in declared if d != db)
            if wrong:
                raise FixtureBindingError(
                    f"{case['case_id']}: session {spec.get('name')!r} declares "
                    f"{wrong} but fixture.db is {db!r}")
            key = ("group" if fixture.get("share_session")
                   else str(spec.get("group") or f"solo:{spec.get('name')}"))
            if key not in grouped:
                order.append(key)
            grouped.setdefault(key, []).append((spec, transcript))

        runs: list[tuple[str, Any]] = []
        for key in order:
            members = grouped[key]
            turns = [turn for _spec, transcript in members for turn in transcript["turns"]]
            workspace = ctx.new_sandbox(f"{case['case_id']}-{_slug(key)}")
            runs.append((key, run_recorded_turns(
                f"{case['case_id']}:{key}", turns, fixture_db=db, workspace=workspace)))
    except Exception as exc:  # noqa: BLE001 - reported as a failing case
        checks.append(Check("isolation.replay", False, "a clean replay",
                            f"{type(exc).__name__}: {exc}"))
        result = _result_from(case, checks)
        result.evidence = evidence
        return result

    errors = [error for _key, run in runs for error in run.errors]
    checks.append(Check("isolation.no_provider_error", not errors, [], errors))
    if fixture.get("share_session"):
        shared = len(runs) == 1 and len(grouped.get("group") or []) >= 2
        checks.append(Check("isolation.group_count", shared,
                            "1 shared session carrying >=2 recorded sessions",
                            [key for key, _run in runs]))
    else:
        checks.append(Check("isolation.group_count", len(runs) >= 2, ">=2 isolated sessions",
                            [key for key, _run in runs]))

    _iso_leak_checks(case, expected, grouped, runs, checks)
    _iso_group_checks(expected, grouped, runs, checks)
    _iso_store_checks(case, fixture, runs, ctx, checks)
    _iso_borrowed_number_checks(case, expected, runs, checks)

    evidence.update({
        "sessions": [
            {"group": key,
             "workspace": _iso_identity(run)["cwd"],
             "tool_chain": run.tool_names,
             "tool_use_ids": _iso_identity(run)["tool_use_ids"],
             "files": sorted(_workspace_files(run.workspace)),
             "context": _iso_identity(run)["context"]}
            for key, run in runs
        ],
        "answers": [run.text[:400] for _key, run in runs],
    })
    result = _result_from(case, checks)
    leak_checks = [c for c in checks if c.name.startswith(LEAK_PREFIX)]
    result.metrics["cross_session_leak_rate"] = bool(leak_checks) and any(
        not c.ok for c in leak_checks)
    result.metrics["answer_schema_valid_rate"] = all(
        bool(run.text.strip()) for _key, run in runs)
    result.evidence = evidence
    return result


def _slug(text: str) -> str:
    return re.sub(r"[^A-Za-z0-9_.-]+", "_", str(text))[:48]


def _iso_leak_checks(case: dict, expected: dict,
                     grouped: dict[str, list[tuple[dict, dict]]],
                     runs: list[tuple[str, Any]], checks: list[Check]) -> None:
    """Different groups must own disjoint state."""
    first_key, first_run = runs[0]
    first = _iso_identity(first_run)
    first_files = _workspace_files(first_run.workspace)
    # Probe the live context object: a shared AnalysisContext is a leak, and
    # comparing stored values alone cannot see one when every field is empty.
    probe = f"isolation-probe-{case.get('case_id')}"
    first_context = getattr(first_run.session, "analysis_context", None)
    if first_context is not None:
        try:
            first_context.goal = probe
        except Exception:  # noqa: BLE001 - a frozen context is reported below
            pass
    first_questions = [str(turn.get("user") or "")
                       for _spec, transcript in grouped[first_key]
                       for turn in transcript["turns"]]

    for key, run in runs[1:]:
        peer = _iso_identity(run)
        checks.append(Check(f"{LEAK_PREFIX}distinct_session[{key}]",
                            run.session is not first_run.session,
                            "a new WebSession", "shared instance"))
        checks.append(Check(f"{LEAK_PREFIX}distinct_workspace[{key}]",
                            bool(peer["cwd"]) and peer["cwd"] != first["cwd"],
                            "its own workspace", peer["cwd"]))
        peer_context = getattr(run.session, "analysis_context", None)
        checks.append(Check(f"{LEAK_PREFIX}context_object_distinct[{key}]",
                            peer_context is not first_context, "a new AnalysisContext",
                            "shared instance"))
        checks.append(Check(f"{LEAK_PREFIX}context_probe_not_visible[{key}]",
                            getattr(peer_context, "goal", None) != probe,
                            f"!= {probe!r}", getattr(peer_context, "goal", None)))
        shared_ids = sorted(set(peer["tool_use_ids"]) & set(first["tool_use_ids"]))
        checks.append(Check(f"{LEAK_PREFIX}no_shared_tool_records[{key}]",
                            not shared_ids, [], shared_ids))
        leaked_files = sorted(_workspace_files(run.workspace) & first_files)
        checks.append(Check(f"{LEAK_PREFIX}no_cross_files[{key}]",
                            not leaked_files, [], leaked_files))
        for key_name in (expected.get("forbidden_context") or []):
            donor_value = first["context"].get(key_name)
            # Only meaningful when the donor actually holds a value: the point is
            # "the peer must not end up with the donor's value".
            checks.append(Check(
                f"{LEAK_PREFIX}context_not_inherited[{key}][{key_name}]",
                not donor_value or peer["context"].get(key_name) != donor_value,
                f"!= {donor_value!r}", peer["context"].get(key_name)))
        peer_history = json.dumps(peer["messages"], ensure_ascii=False)
        borrowed = [q for q in first_questions if len(q) >= 8 and q in peer_history]
        checks.append(Check(f"{LEAK_PREFIX}no_borrowed_history[{key}]",
                            not borrowed, [], borrowed))


def _iso_group_checks(expected: dict,
                      grouped: dict[str, list[tuple[dict, dict]]],
                      runs: list[tuple[str, Any]], checks: list[Check]) -> None:
    """A declared conversation group may inherit — in the declared order.

    ``expected.group_history_contains`` names the earlier turns that must still
    be present in the shared session's history, in order.  Nothing inherits
    across group boundaries (that is what the leak checks cover).
    """
    wanted = [str(item) for item in (expected.get("group_history_contains") or [])]
    for key, run in runs:
        members = grouped.get(key) or []
        if len(members) < 2:
            continue
        checks.append(Check(f"isolation.group_turn_count[{key}]",
                            len(run.turn_events) == len(members),
                            len(members), len(run.turn_events)))
        history = json.dumps(_iso_identity(run)["messages"], ensure_ascii=False)
        positions = [history.find(item) for item in wanted if item in history]
        checks.append(Check(f"isolation.group_order[{key}]",
                            len(positions) == len(wanted) and positions == sorted(positions),
                            "declared order preserved", positions))
    if wanted and not any(len(grouped.get(key) or []) > 1 for key, _run in runs):
        checks.append(Check("isolation.group_declared", False,
                            "a shared group", "every session is its own group"))


def _iso_store_checks(case: dict, fixture: dict, runs: list[tuple[str, Any]],
                      ctx: EvalContext, checks: list[Check]) -> None:
    """One ConversationStore per user: the place a real leak would hide."""
    if not fixture.get("share_conversation_store"):
        return
    from bi_agent.web.conversations import ConversationStore  # noqa: PLC0415

    root = ctx.new_sandbox(f"{case['case_id']}-store")
    store = ConversationStore(str(root))
    saved: list[tuple[str, str, str, str]] = []
    for key, _run in runs:
        mode = str(fixture.get("session_modes", {}).get(key) or "data")
        marker = f"isolation-marker-{_slug(key)}"
        record = store.save(mode=mode, title=marker,
                            messages=[{"role": "user", "content": marker}])
        saved.append((key, mode, marker, str(record.get("id") or "")))

    ids = [cid for _key, _mode, _marker, cid in saved]
    # Report the *fact* of uniqueness, not the random ids themselves: a report
    # signature must not change just because ``token_hex`` produced a different
    # value on the second run.
    checks.append(Check(f"{LEAK_PREFIX}store_distinct_ids",
                        len(set(ids)) == len(ids), "unique conversation ids",
                        f"{len(set(ids))}/{len(ids)} distinct"))
    for _key, _mode, marker, own in saved:
        others = [store.get(other) for _k, _m, _mk, other in saved if other != own]
        blob = json.dumps(others, ensure_ascii=False)
        checks.append(Check(f"{LEAK_PREFIX}store_no_shared_content[{marker}]",
                            marker not in blob, "no cross read", "leaked"))
    for _key, mode, marker, _cid in saved:
        same_mode = json.dumps(store.list(mode=mode), ensure_ascii=False)
        checks.append(Check(f"{LEAK_PREFIX}mode_separation[{mode}][{marker}]",
                            marker in same_mode, "listed in its own mode", "missing"))
        for other_mode in sorted({m for _k, m, _mk, _c in saved} - {mode}):
            blob = json.dumps(store.list(mode=other_mode), ensure_ascii=False)
            checks.append(Check(f"{LEAK_PREFIX}mode_separation[{other_mode}][{marker}]",
                                marker not in blob, "absent from the other mode", "leaked"))


def _iso_borrowed_number_checks(case: dict, expected: dict,
                                runs: list[tuple[str, Any]],
                                checks: list[Check]) -> None:
    """The negative control: a number only the donor session could produce.

    Two halves, both required: the number must really belong to the donor (or
    the sentinel proves nothing) and grounding must flag it in the peer's answer.
    """
    declared = sorted({round(float(n), 6) for n in (expected.get("unsupported_numbers") or [])})
    if not declared:
        return
    donor_pool: set[float] = set()
    for _key, run in runs[:-1]:
        donor_pool |= set(RecordedPool(case, run).pool)
    peer_run = runs[-1][1]
    peer_pool = RecordedPool(case, peer_run)
    donor_only = sorted(n for n in donor_pool if n not in set(peer_pool.pool))

    def present(number: float, values) -> bool:
        return any(abs(number - value) <= max(1e-6, abs(number) * 1e-6)
                   for value in values)

    checks.append(Check("isolation.borrowed_is_donor_only",
                        all(present(n, donor_only) for n in declared),
                        declared, donor_only[:8]))
    unsupported = peer_pool.unsupported(peer_run.text)
    missing = [n for n in declared if not present(n, unsupported)]
    checks.append(Check("isolation.borrowed_flagged", not missing, declared,
                        sorted(unsupported)[:8]))


def eval_generated_sql(case: dict, ctx: EvalContext) -> CaseResult:
    """Replay + assert the SQL the agent issued really answers the question."""
    expected = case.get("expected") or {}
    fixture = case.get("fixture") or {}
    checks: list[Check] = []
    evidence: dict[str, Any] = {}

    try:
        transcript, run = _load_recorded_run(case, ctx)
    except Exception as exc:  # noqa: BLE001
        checks.append(Check("generated_sql.replay", False, "a clean replay",
                            f"{type(exc).__name__}: {exc}"))
        result = _result_from(case, checks)
        result.metrics["exact_numeric_accuracy"] = False
        result.evidence = evidence
        return result

    checks.append(Check("generated_sql.replay", not run.errors, [], run.errors[:4]))
    checks.extend(_tool_execution_checks("generated_sql", run))
    sql_calls = [c for c in run.tool_calls if c.get("name") == "Ontology-FactQuery"]
    checks.append(Check("generated_sql.issued_sql", bool(sql_calls), ">=1 SQL call", len(sql_calls)))
    if not sql_calls:
        result = _result_from(case, checks)
        result.metrics["exact_numeric_accuracy"] = False
        result.evidence = evidence
        return result

    chain = expected.get("tool_chain")
    chain_ok = True
    if chain is not None:
        chain_ok = run.tool_names == list(chain)
        checks.append(Check("generated_sql.tool_chain", chain_ok,
                            list(chain), run.tool_names))

    actual_sql = str(sql_calls[0]["input"].get("sql") or "")
    evidence["issued_sql"] = actual_sql

    tables = _sql_identifier_tables(actual_sql)
    allowed = {t.lower() for t in (expected.get("allowed_tables") or [])}
    if allowed:
        extra = sorted(t for t in tables if t not in allowed)
        checks.append(Check("generated_sql.tables_allowed", not extra, sorted(allowed), sorted(tables)))
    for table in expected.get("forbidden_tables") or []:
        checks.append(Check(f"generated_sql.table_forbidden[{table}]",
                            table.lower() not in tables, "absent", sorted(tables)))

    normalized = re.sub(r"\s+", " ", actual_sql)
    for fragment in expected.get("required_filters", []):
        checks.append(Check(f"generated_sql.required_filter[{fragment[:24]}]",
                            fragment in normalized, fragment, normalized[:200]))
    for fragment in expected.get("forbidden_filters", []):
        checks.append(Check(f"generated_sql.forbidden_filter[{fragment[:24]}]",
                            fragment not in normalized, "absent", "present"))

    db = str(fixture.get("db") or "procurement.db")
    reference_sql = str(fixture.get("reference_sql") or "")
    reference_rows: list[list[Any]] = []
    actual_rows: list[list[Any]] = []
    try:
        reference_rows = _execute_reference(ctx, db, reference_sql) if reference_sql else []
        actual_rows = _execute_reference(ctx, db, actual_sql)
        checks.append(Check("generated_sql.executes", True, "no error", "ok"))
    except Exception as exc:  # noqa: BLE001
        checks.append(Check("generated_sql.executes", False, "no error",
                            f"{type(exc).__name__}: {exc}"))

    value_ok = True
    if reference_rows and actual_rows:
        tolerance = float(expected.get("tolerance", 1e-6))
        reference_obj = expected.get("value")
        if reference_obj is not None:
            actual_value = actual_rows[0][0] if actual_rows[0] else None
            value_ok = _close(actual_value, reference_obj, tolerance)
            checks.append(Check("generated_sql.matches_reference", value_ok,
                                reference_obj, actual_value))
        else:
            value_ok = [[_normalize_cell(c) for c in row] for row in actual_rows] == \
                       [[_normalize_cell(c) for c in row] for row in reference_rows]
            checks.append(Check("generated_sql.matches_reference", value_ok,
                                reference_rows[:4], actual_rows[:4]))

    checks.extend(_chart_file_checks("generated_sql", expected, run))

    pool = RecordedPool(case, run)
    unsupported = pool.unsupported(run.text)
    checks.extend(_grounding_checks("generated_sql", expected, unsupported))
    for fragment in expected.get("final_text_contains", []):
        checks.append(Check(f"generated_sql.text_contains[{str(fragment)[:24]}]",
                            str(fragment) in run.text, fragment, run.text[:200]))

    evidence.update({
        "provider": fixture.get("provider"),
        "tool_chain": run.tool_names,
        "reference_sql": reference_sql,
        "reference_rows": reference_rows[:5],
        "actual_rows": actual_rows[:5],
        "answer": run.text[:500],
        "unsupported_numbers": sorted(unsupported)[:8],
    })
    result = _result_from(case, checks)
    result.metrics.update({
        "exact_numeric_accuracy": value_ok,
        "query_contract_accuracy": all(c.ok for c in checks
                                       if c.name.startswith("generated_sql.tables")
                                       or c.name.startswith("generated_sql.required")
                                       or c.name.startswith("generated_sql.forbidden")),
        "metric_scope_accuracy": all(c.ok for c in checks
                                     if c.name.startswith("generated_sql.required_filter")),
        "tool_route_accuracy": chain_ok,
        "answer_schema_valid_rate": _schema_valid(expected, run, unsupported),
    })
    _record_grounding_metric(result, expected, unsupported)
    result.evidence = evidence
    return result


def eval_answer_grounding(case: dict, ctx: EvalContext) -> CaseResult:
    """Replay + assert the final narrative is evidence-bound and honest."""
    expected = case.get("expected") or {}
    checks: list[Check] = []
    evidence: dict[str, Any] = {}
    try:
        transcript, run = _load_recorded_run(case, ctx)
    except Exception as exc:  # noqa: BLE001
        checks.append(Check("grounding.replay", False, "a clean replay",
                            f"{type(exc).__name__}: {exc}"))
        result = _result_from(case, checks)
        result.metrics["answer_schema_valid_rate"] = False
        result.evidence = evidence
        return result

    checks.append(Check("grounding.replay", not run.errors, [], run.errors[:4]))
    checks.extend(_chart_file_checks("grounding", expected, run))
    pool = RecordedPool(case, run)
    unsupported = pool.unsupported(run.text)
    checks.extend(_grounding_checks("grounding", expected, unsupported))
    for fragment in expected.get("final_text_contains", []):
        checks.append(Check(f"grounding.text_contains[{str(fragment)[:24]}]",
                            str(fragment) in run.text, fragment, run.text[:200]))
    for fragment in expected.get("final_text_absent", []):
        checks.append(Check(f"grounding.text_absent[{str(fragment)[:24]}]",
                            str(fragment) not in run.text, "absent", "present"))
    answer_checks, metrics = score_answer(
        case, run.text, pool.pool,
        evidence_labels=_visible_metric_labels(run.tool_calls))
    if expected.get("score_answer", True):
        checks.extend(answer_checks)
    checks.append(Check("grounding.no_forbidden_token",
                        not [t for t in (case.get("forbidden") or []) if t and t in run.text],
                        [], [t for t in (case.get("forbidden") or []) if t and t in run.text]))

    evidence.update({
        "tool_chain": run.tool_names,
        "answer": run.text[:800],
        "unsupported_numbers": sorted(unsupported)[:8],
        "recovery": run.session.recovery_state.get("status"),
    })
    result = _result_from(case, checks)
    result.metrics.update(metrics)
    result.metrics["answer_schema_valid_rate"] = _schema_valid(expected, run, unsupported)
    if expected.get("unsupported_numbers"):
        result.metrics.pop("unsupported_number_rate", None)
    result.evidence = evidence
    return result


def eval_tool_chain(case: dict, ctx: EvalContext) -> CaseResult:
    """Replay + assert the observed tool plan / inputs / terminal state."""
    return eval_recorded_provider(case, ctx)


def _normalize_cell(cell: Any) -> Any:
    if isinstance(cell, bool):
        return cell
    if isinstance(cell, (int, float)):
        return round(float(cell), 6)
    return cell


EVALUATORS: dict[str, Callable[[dict, EvalContext], CaseResult]] = {
    "policy": eval_policy,
    "sql": eval_sql,
    "ontology": eval_ontology,
    "multi_turn": eval_multi_turn,
    "chart_validate": eval_chart_validate,
    "chart_policy": eval_chart_policy,
    "chart_html_safety": eval_chart_html_safety,
    "sql_guard": eval_sql_guard,
    "recovery_state": eval_recovery_state,
    "admission": eval_admission,
    "session_isolation": eval_session_isolation,
    "recorded_session_isolation": eval_recorded_session_isolation,
    "recorded_provider": eval_recorded_provider,
    "context_resolution": eval_context_resolution,
    "generated_sql": eval_generated_sql,
    "tool_chain": eval_tool_chain,
    "answer_grounding": eval_answer_grounding,
    "live": eval_live,
}


def load_cases() -> list[dict]:
    cases: list[dict] = []
    for path in sorted(CASES_DIR.glob("*/*.json")):
        with path.open(encoding="utf-8") as handle:
            cases.append(json.load(handle))
    return cases


def select_cases(
    cases: list[dict],
    suite: str,
    ids: Optional[list[str]] = None,
    categories: Optional[list[str]] = None,
) -> list[dict]:
    selected = cases
    if ids:
        wanted = [i for i in ids]
        selected = [
            c for c in selected
            if any(c["case_id"] == w or c["case_id"].startswith(w) for w in wanted)
        ]
    if categories:
        selected = [c for c in selected if c.get("category") in categories]
    if suite == "all":
        return [c for c in selected if c.get("evaluator") != "live"]
    if suite == "live":
        return [
            c for c in selected
            if c.get("answer_requirements")
            or any(s in ("diagnosis", "recommendation") for s in c.get("suite", []))
        ]
    if suite == "live-canary":
        return [c for c in selected if "live-canary" in (c.get("suite") or [])]
    return [c for c in selected if suite in (c.get("suite") or [])]


def run_case(case: dict, ctx: EvalContext,
             evaluator_override: str = "") -> CaseResult:
    """Run one case.

    ``evaluator_override`` exists for the live suite: the same case can be
    asserted structurally offline (its own evaluator) and semantically against a
    real model (``evaluator="live"``).
    """
    started = time.perf_counter()
    evaluator = evaluator_override or case.get("evaluator", "")
    fn = EVALUATORS.get(evaluator)
    fixture_db: Optional[str] = None
    try:
        fixture_db = resolve_fixture_db(case)
    except FixtureBindingError as exc:
        return CaseResult(
            case_id=case["case_id"], category=case.get("category", ""),
            evaluator=evaluator, priority=case.get("priority", "P1"),
            status=FAIL, question=case.get("question", ""),
            checks=[Check("case.fixture_binding", False,
                          f"one of {list(FIXTURE_DBS)} consistent with case.domain",
                          str(exc))],
            error=str(exc),
            duration_ms=round((time.perf_counter() - started) * 1000, 3),
        )
    try:
        if fn is None:
            result = CaseResult(
                case_id=case["case_id"], category=case.get("category", ""),
                evaluator=evaluator, priority=case.get("priority", "P1"),
                status=FAIL, question=case.get("question", ""),
                checks=[Check("evaluator.known", False, "a known evaluator", evaluator)],
                error=f"unknown evaluator: {evaluator}",
            )
        else:
            result = fn(case, ctx)
    except Exception as exc:  # noqa: BLE001 - a crashed evaluator is a failure
        import traceback

        result = CaseResult(
            case_id=case["case_id"], category=case.get("category", ""),
            evaluator=evaluator, priority=case.get("priority", "P1"),
            status=FAIL, question=case.get("question", ""),
            checks=[Check("evaluator.ran", False, "no exception", f"{type(exc).__name__}: {exc}")],
            error=f"{type(exc).__name__}: {exc}",
        )
        if ctx.verbose:
            traceback.print_exc()
    allowed = _schema_case_fields()
    unknown = sorted(key for key in case if allowed and key not in allowed)
    if unknown:
        # A misspelled key must never be silently ignored: the case would look
        # like it asserts something it does not.
        result.unknown_fields = unknown
        result.status = FAIL
        result.checks.append(Check("case.no_unknown_fields", False, [], unknown))
    result.duration_ms = round((time.perf_counter() - started) * 1000, 3)
    if fixture_db:
        result.run_meta.setdefault("fixture_db", fixture_db)
    result.run_meta.setdefault("evaluator", result.evaluator)
    result.run_meta.setdefault("domain", case.get("domain"))
    result.run_meta.setdefault("session_id", "")
    fixture = case.get("fixture") or {}
    if fixture.get("provider") and not result.run_meta.get("provider"):
        result.run_meta["provider"] = "recorded"
    return result


# ---------------------------------------------------------------------------
# aggregation + gates
# ---------------------------------------------------------------------------
VOLATILE_SIGNATURE_KEYS = frozenset({
    "updated_at", "created_at", "checkpoint_id", "session_id", "cost",
    "duration_ms", "duration", "tokens", "token_usage", "started_at",
    "finished_at", "execution_id",
    # Identifier fields are never behaviour (Spec §4.1): a fresh session id in
    # ``evidence.observations`` must not turn a stable case into a "drift".
    "id", "run_id", "request_id", "trace_id",
})


_HEX_ID_RE = re.compile(r"\b[0-9a-fA-F]{6,40}\b")


def _hex_id_or_number(match: "re.Match[str]") -> str:
    """Mask a random hex id, but never a pure-digit business number.

    A session id is 6-40 hex characters -- and so is any integer of six digits
    or more (an amount, a count, a code).  Masking those would hide a real
    numeric drift, which Spec §4.2-6 forbids, so only tokens that actually carry
    a hex letter are treated as identifiers.
    """
    token = match.group()
    return "<id>" if any(char.lower() in "abcdef" for char in token) else token


_VOLATILE_TEXT_PATTERNS = (
    # absolute temp sandboxes: /.../analytics-eval-<rand>/0001-CASE/dataset/charts/...
    (re.compile(r"/[^\s\"']*?analytics-eval-[^\s\"']*"), "<sandbox>"),
    # Generated artifact names embed a wall-clock stamp.  The name is *relative*
    # whenever the sandbox is also the working directory (Linux CI, where the
    # absolute-sandbox rule above never fires), so the stamp itself must be
    # masked for every artifact family the app writes: chart, report, multidim.
    (re.compile(r"(chart|report|multidim)-\d{8}-\d{6}-"), r"\1-<ts>-"),
    # ... and for a name a length cut truncated mid-stamp, which would otherwise
    # re-introduce exactly the same drift.
    (re.compile(r"(chart|report|multidim)-\d{4,8}-?\d{0,6}$"), r"\1-<ts>"),
    # ISO-8601 timestamps (with or without a timezone / fractional seconds)
    (re.compile(r"\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}:\d{2}[0-9.:+\-Z]*"), "<ts>"),
    # Random hex ids, including the 8-character session id used in observations.
    (_HEX_ID_RE, _hex_id_or_number),
)


def _normalize_volatile_text(text: str) -> str:
    """Strip sandbox paths, wall-clock stamps and random ids from evidence text.

    ``--repeat`` compares the *behaviour* of two runs of the same case; the
    directory a run happened to use and the second it ran in are not behaviour,
    so they must never make a stable case look unstable.
    """
    for pattern, replacement in _VOLATILE_TEXT_PATTERNS:
        text = pattern.sub(replacement, text)
    return text


def _canonical_value(value: Any, *, limit: int = 400) -> Any:
    """A stable, comparable projection of a value.

    Timestamps, durations, token counts and random ids are removed so they can
    never make two identical runs look different; long strings are truncated so
    a report stays readable.
    """
    if isinstance(value, dict):
        return {str(k): _canonical_value(v, limit=limit)
                for k, v in sorted(value.items(), key=lambda kv: str(kv[0]))
                if str(k) not in VOLATILE_SIGNATURE_KEYS}
    if isinstance(value, (list, tuple)):
        return [_canonical_value(v, limit=limit) for v in value]
    if isinstance(value, set):
        return sorted(_canonical_value(v, limit=limit) for v in value)
    if isinstance(value, str):
        text = _normalize_volatile_text(value)
        return text if len(text) <= limit else text[:limit]
    return value


SEMANTIC_SIGNATURE_KEYS = (
    "intent_level", "policy", "tool_chain", "tool_status", "issued_sql",
    "reference_sql", "sql", "actual_sql", "chart_type", "chart_params",
    "unsupported_numbers", "recovery", "resolved_contract", "contract",
    "observations", "evidence", "anchors", "metric",
)


def generic_signature(result: CaseResult) -> dict:
    """A semantic fingerprint built from a result's own evidence.

    Used for every evaluator that does not build a hand-written signature (only
    ``live`` and ``answers`` do), so ``--repeat`` always compares intent, tool
    order, SQL semantics, cited numbers, evidence, chart type, answer structure
    and unsupported claims — not just check names and booleans.
    """
    evidence = result.evidence if isinstance(result.evidence, dict) else {}
    signature: dict[str, Any] = {}
    for key in SEMANTIC_SIGNATURE_KEYS:
        if key not in evidence:
            continue
        value = evidence[key]
        if value in (None, "", [], {}):
            continue
        if key in ("sql", "issued_sql", "actual_sql", "reference_sql"):
            if isinstance(value, str):
                value = _canonical_sql(value)
            elif isinstance(value, list):
                value = [_canonical_sql(str(v)) for v in value]
        signature[key] = _canonical_value(value, limit=240)
    answer = evidence.get("answer")
    if isinstance(answer, str) and answer.strip():
        signature["answer_structure"] = _answer_structure(answer)
        signature["answer_numbers"] = sorted(_numbers_in(answer))[:60]
    return signature


def semantic_signature(result: CaseResult) -> dict:
    """The semantic fingerprint dict for one run (hand-written or derived)."""
    return dict(result.signature) if result.signature else generic_signature(result)


def result_signature(result: CaseResult) -> str:
    """The comparable fingerprint of one case run.

    It always covers the semantic fingerprint (intent level, tool order,
    normalized SQL, cited numbers, evidence, chart types, unsupported claims)
    plus every check and metric — not just check names and booleans.
    """
    payload = {
        "evaluator": result.evaluator,
        "status": result.status,
        "checks": [{"name": c.name, "ok": c.ok, "actual": _canonical_value(c.actual)}
                   for c in result.checks],
        "metrics": {k: bool(v) for k, v in sorted(result.metrics.items())},
    }
    semantic = semantic_signature(result)
    # The playwright-style structural checks above already carry the tool chain
    # for most evaluators; adding the semantic block makes the fingerprint
    # meaningful even when every check is a bare boolean.
    for key in ("evaluator", "priority", "category"):
        semantic.setdefault(key, getattr(result, key, ""))
    payload["semantic"] = _canonical_value(semantic)
    return json.dumps(payload, ensure_ascii=False, sort_keys=True)


def measure_repeat(selected: list[dict], ctx: EvalContext, repeat: int, *,
                   evaluator_override: str = "",
                   runner: Optional[Callable[..., CaseResult]] = None,
                   reset: Optional[Callable[[], None]] = None,
                   collected: Optional[list] = None) -> dict:
    """Run the selection ``repeat`` times and measure agreement.

    Every repetition uses the *same* evaluator as the first run (the live suite
    must not silently fall back to the offline evaluator on run 2), and the
    caller may pass ``reset`` to hand each repetition a brand-new harness so a
    live repeat never reuses the previous session.
    """
    run = runner or run_case
    if repeat < 2:
        # A single execution is not a stability measurement: there is no second
        # run to compare against, so it must never produce a score.  A fabricated
        # ``1.0`` here is exactly what let a release gate pass on no evidence.
        return {
            "repeat": repeat,
            "agreement": None,
            "measured": False,
            "cases": 0,
            "stable_cases": 0,
            "unstable_cases": 0,
            "stable_case_ids": [],
            "unstable_case_ids": [],
            "skipped_case_ids": [],
            "case_detail": [],
            "runs": [],
        }
    signatures: dict[str, list[str]] = {}
    statuses: dict[str, list[str]] = {}
    runs: list[dict] = []
    for index in range(repeat):
        if reset is not None:
            reset()
        for case in selected:
            result = (run(case, ctx, evaluator_override) if evaluator_override
                      else run(case, ctx))
            if collected is not None and index == 0:
                collected.append(result)
            signatures.setdefault(result.case_id, []).append(result_signature(result))
            statuses.setdefault(result.case_id, []).append(result.status)
            runs.append({
                "run_index": index + 1,
                "case_id": result.case_id,
                "evaluator": result.evaluator,
                "status": result.status,
                "provider": (result.run_meta or {}).get("provider", ""),
                "fixture_db": (result.run_meta or {}).get("fixture_db", ""),
                "session_id": (result.run_meta or {}).get("session_id", ""),
                "tool_chain": semantic_signature(result).get("tool_chain", []),
                "answer_signature": _canonical_value(semantic_signature(result)),
                "metrics": {k: bool(v) for k, v in sorted(result.metrics.items())},
            })
    # A case that did not execute in *every* repetition is not a stable sample:
    # it is reported separately and its count reaches ``metric_stats.skipped``
    # instead of being silently averaged into a perfect score.
    skipped = sorted(cid for cid, seen in statuses.items() if SKIP in seen)
    skipped_set = set(skipped)
    sample_ids = [cid for cid in signatures if cid not in skipped_set]
    # "Stable" means the same, *successful* behaviour twice.  A case that fails
    # in every repetition is deterministic but is still not evidence of release
    # stability, so it can never count towards the agreement.
    unstable = sorted(
        cid for cid in sample_ids
        if len(set(signatures[cid])) > 1
        or any(status not in (PASS, XFAIL) for status in statuses[cid])
    )
    unstable_set = set(unstable)
    stable_ids = [cid for cid in sample_ids if cid not in unstable_set]
    agreement = round(len(stable_ids) / len(sample_ids), 6) if sample_ids else None
    detail = []
    for cid in sorted(statuses):
        sigs = signatures.get(cid, [])
        detail.append({
            "case_id": cid,
            "stable": cid not in unstable_set and cid not in skipped_set,
            "skipped": cid in skipped_set,
            "runs": len(sigs),
            "distinct_signatures": len(set(sigs)),
        })
    return {
        "repeat": repeat,
        "agreement": agreement,
        "measured": bool(sample_ids),
        "cases": len(sample_ids),
        "stable_cases": len(stable_ids),
        "unstable_cases": len(unstable),
        "stable_case_ids": stable_ids,
        "unstable_case_ids": unstable,
        "skipped_case_ids": skipped,
        "case_detail": detail,
        "runs": runs,
    }


def aggregate(results: list[CaseResult]) -> dict:
    """Aggregate over the *contract* population.

    ``known_gap`` cases are Red tests for recorded defects: they are excluded
    from pass rates, metrics and gates and reported separately (see
    ``known_gaps``), so the suite stays actionable while a defect is open.
    """
    contract = [r for r in results if not r.known_gap]
    total = len(contract)
    passed = sum(1 for r in contract if r.status == PASS)
    failed = sum(1 for r in contract if r.status == FAIL)
    metrics: dict[str, Optional[float]] = {}
    counts: dict[str, int] = {}
    stats: dict[str, dict] = {}
    names = list(ALL_METRICS)
    for result in results:
        for name in result.metrics:
            if name not in names:
                names.append(name)
    skipped = sum(1 for r in results if r.status == SKIP)
    for name in names:
        values = [r.metrics[name] for r in contract if name in r.metrics]
        excluded = sum(1 for r in results if r.known_gap and name in r.metrics)
        if not values:
            metrics[name] = None
            counts[name] = 0
            stats[name] = {
                "measured": False, "applicable": 0, "passed": 0, "failed": 0,
                "skipped": skipped, "known_gap_excluded": excluded,
                "sample_size": 0, "numerator": 0, "denominator": 0,
            }
            continue
        passed_count = sum(1 for v in values if v)
        metrics[name] = round(passed_count / len(values), 6)
        counts[name] = len(values)
        good = (len(values) - passed_count) if name in LOWER_IS_BETTER_METRICS else passed_count
        stats[name] = {
            "measured": True,
            "applicable": len(values),
            "passed": good,
            "failed": len(values) - good,
            "skipped": skipped,
            "known_gap_excluded": excluded,
            "sample_size": len(values),
            "numerator": passed_count if name not in LOWER_IS_BETTER_METRICS else good,
            "denominator": len(values),
        }
    return {
        "cases": total,
        "selected_cases": len(results),
        "passed": passed,
        "failed": failed,
        "pass_rate": round(passed / total, 6) if total else None,
        # P0 gate fields.  "101/101 P0 passed" is misleading when some P0 cases
        # are unresolved known gaps, so the counts are split out explicitly.
        "p0_cases": sum(1 for r in contract if r.priority == "P0"),
        "p0_passed": sum(1 for r in contract if r.priority == "P0" and r.status == PASS),
        "p0_total": sum(1 for r in results if r.priority == "P0"),
        "p0_failed": sum(1 for r in results
                         if r.priority == "P0" and r.status == FAIL),
        "p0_xfailed": sum(1 for r in results
                          if r.priority == "P0" and r.status == XFAIL),
        "p0_xpassed": sum(1 for r in results
                          if r.priority == "P0" and r.status == XPASS),
        "unresolved_p0_defects": sum(1 for r in results
                                     if r.priority == "P0" and r.status == XFAIL),
        "known_gap_cases": sum(1 for r in results if r.known_gap),
        "known_gap_xfail": sum(1 for r in results if r.status == XFAIL),
        "known_gap_xpass": sum(1 for r in results if r.status == XPASS),
        "metrics": metrics,
        "metric_sample_sizes": counts,
        "metric_stats": stats,
        "duration_ms": round(sum(r.duration_ms for r in results), 3),
    }


RELEASE_CRITICAL_METRICS = (
    "exact_numeric_accuracy",
    "answer_schema_valid_rate",
    "evidence_coverage",
    "cross_session_leak_rate",
    "unsupported_number_rate",
)

# Unresolved defects that must block a release even when they are not P0: these
# three adversarial cases are about credentials and destructive requests.
SECURITY_GAP_IDS = frozenset({"ANA-ADV-010", "ANA-ADV-011", "ANA-ADV-012"})


def _suite_capabilities(results: list[CaseResult]) -> set[str]:
    """Metrics the selected population is *able* to measure.

    A metric that is not capable in this selection is NOT_APPLICABLE (never
    blocking); a capable metric that produced no value is NOT_MEASURED (blocking
    for a release).
    """
    caps = {
        "intent_accuracy", "tool_route_accuracy", "query_contract_accuracy",
        "exact_numeric_accuracy", "metric_scope_accuracy", "evidence_coverage",
        "answer_schema_valid_rate", "chart_selection_accuracy",
        "recovery_success_rate", "multi_turn_context_accuracy", "repeat_stability",
    }
    evaluators = {r.evaluator for r in results}
    # Any evaluator that actually drives a session loop *can* host a
    # cross-session sentinel; only a selection with none of them is truly
    # incapable of measuring this metric.
    if evaluators & {"session_isolation", "recorded_session_isolation",
                     "recorded_provider", "live", "answers"}:
        caps.add("cross_session_leak_rate")
    if evaluators & {"live", "answers", "recorded_provider", "answer_grounding",
                     "generated_sql", "tool_chain"}:
        caps.add("unsupported_number_rate")
    # The truthfulness metrics are measurable offline whenever the selection
    # contains a case that declares the contract *and* is run by an evaluator
    # that can score the final narrative.  Capability is read from the case's
    # answer contract, not from the produced value, so an empty denominator is
    # NOT_MEASURED (release blocking) rather than NOT_APPLICABLE.
    for result in results:
        if result.evaluator not in ANSWER_SCORING_EVALUATORS:
            continue
        declared = set(result.answer_requirements or ())
        if CAUSAL_REQUIREMENT in declared:
            caps.add(CAUSAL_RATE_METRIC)
        if PROXY_REQUIREMENT in declared:
            caps.add(PROXY_RATE_METRIC)
    for result in results:
        caps |= set(result.metrics)
    return caps


# Which case type a metric needs.  A bare "not measured" hides *why*, and an
# unmeasured release-critical metric is exactly where a report must be explicit.
MISSING_CASE_HINTS = {
    "cross_session_leak_rate": "需要 session_isolation / 跨会话哨兵案例（A 案例数字不得出现在 B 案例）",
    "unsupported_number_rate": "需要 answer_grounding 或 recorded 链路案例（答案引用未查询数字）",
    "unsupported_causal_claim_rate": "需要 recorded-provider/answer_grounding 离线语义评分案例（把相关性说成因果）",
    "proxy_disclosure_rate": "需要 recorded-provider/answer_grounding 离线语义评分案例（使用代理指标未说明）",
    "unsupported_causal_claim_detection_rate": "需要 expect_causal_violation 离线负例（植入因果越界）",
    "proxy_disclosure_detection_rate": "需要 expect_proxy_miss 离线负例（植入代理不披露）",
    "multi_turn_context_accuracy": "需要 multi_turn / context_resolution 案例",
    "recovery_success_rate": "需要 recovery_state / failure_recovery 案例",
    "chart_selection_accuracy": "需要 chart_* 图表链路案例",
    "repeat_stability": "需要 --repeat N 运行（同一 evaluator 重跑对比语义指纹）",
    "intent_accuracy": "需要 intent / policy 案例",
    "tool_route_accuracy": "需要带 tool_chain 断言的案例",
    "query_contract_accuracy": "需要 SQL/指标口径案例",
    "exact_numeric_accuracy": "需要带精确数字断言的案例",
    "metric_scope_accuracy": "需要指标口径案例",
    "evidence_coverage": "需要带 evidence_requirements 的案例",
    "answer_schema_valid_rate": "需要产出最终答案的链路案例",
}

# Metrics a release must have measured.  NOT_MEASURED here is always blocking.
RELEASE_REQUIRED_METRICS = frozenset({
    "exact_numeric_accuracy", "answer_schema_valid_rate", "evidence_coverage",
    "cross_session_leak_rate", "unsupported_number_rate",
    "unsupported_causal_claim_rate", "proxy_disclosure_rate",
    # A release must prove that two runs of the same selection agree; the gate
    # itself is built below because "not measured" only blocks a release run.
    "repeat_stability",
})


def _metric_gate(name: str, value: Optional[float], want: float, *,
                 higher_is_better: bool, capable: bool,
                 skipped: bool = False) -> dict:
    hint = MISSING_CASE_HINTS.get(name, "")
    if value is None:
        if not capable:
            return {"name": name, "status": "NOT_APPLICABLE", "ok": True,
                    "severity": "release", "detail":
                    f"{name}: 该选择集不含可测量它的案例类型；{hint}"
                    if hint else f"{name}: no case in this selection can measure it"}
        if skipped:
            # The whole selection was skipped (e.g. no provider credentials).
            # The metric is still not measured — it is reported as
            # NOT_MEASURED and must never be summarised as a pass — but an
            # opt-in suite that could not run is not a defect.
            return {"name": name, "status": "NOT_MEASURED", "ok": True,
                    "severity": "release", "release_required": False, "detail":
                    f"{name}: 本次运行被跳过（未配置凭据）——报告为 not_measured，"
                    f"绝不写成 passed；{hint}"}
        critical = name in RELEASE_REQUIRED_METRICS
        blocked = "；release gate 阻断（release-critical）" if critical else ""
        return {"name": name, "status": "NOT_MEASURED", "ok": not critical,
                "severity": "release", "release_required": critical, "detail":
                f"{name}: applicable but not measured by this selection；{hint}{blocked}"}
    ok = value >= want if higher_is_better else value <= want
    compare = ">=" if higher_is_better else "<="
    return {"name": name, "status": "PASS" if ok else "FAIL", "ok": ok,
            "severity": "always",
            "release_required": name in RELEASE_REQUIRED_METRICS,
            "detail": f"{name}={value} (requirement {compare} {want})"}


def _security_defects(results: list[CaseResult]) -> list[CaseResult]:
    """Unresolved defects about credentials or destructive requests."""
    return [r for r in results
            if r.status == XFAIL
            and (r.case_id in SECURITY_GAP_IDS
                 or str((r.gap_meta or {}).get("severity") or "").lower()
                 in ("security", "high"))]


def evaluate_gates(results: list[CaseResult], metrics: dict, *,
                   release: bool = False,
                   allowlist: Optional[list[str]] = None,
                   ratchet: Optional[dict] = None,
                   waivers: Optional[dict] = None,
                   skipped: bool = False) -> list[dict]:
    """Gates from the task spec.  Any breach makes the run exit non-zero.

    ``release=True`` turns the P0 known-gap allowlist, the waiver expiry, the
    overdue-defect check and the security checkpoint into hard gates.  A
    research run reports the same numbers but only blocks on ``severity:
    always`` gates, because an open defect must stay visible without making
    local iteration impossible.  There is deliberately no "ignore all known
    gaps" switch: an override must name an individual ``case_id`` and carry its
    audit metadata.
    """
    capable = _suite_capabilities(results)
    p0 = [r for r in results if r.priority == "P0" and not r.known_gap]
    if skipped:
        gates = [
            {
                "name": "p0_all_pass",
                "status": "NOT_MEASURED",
                "ok": True,
                "severity": "always",
                "detail": ("this run was skipped (no provider credentials); "
                           "0 P0 cases executed — not reported as passed"),
            },
        ]
    else:
        gates = [
            {
                "name": "p0_all_pass",
                "status": "PASS" if all(r.status == PASS for r in p0) else "FAIL",
                "ok": all(r.status == PASS for r in p0),
                "severity": "always",
                "detail": f"{sum(1 for r in p0 if r.status == PASS)}/{len(p0)} P0 contract cases passed",
            },
        ]
    # Release stability.  A release must *measure* it (an unmeasured release is
    # blocked); a measured drift blocks any run, including the plain CI repeat
    # job that runs without ``--release``.
    repeat_value = metrics.get("repeat_stability")
    if skipped:
        gates.append({
            "name": "repeat_stability",
            "status": "NOT_MEASURED",
            "ok": True,
            "severity": "release",
            "release_required": False,
            "detail": ("本次运行被跳过（未配置凭据）：repeat_stability 报告为 "
                       "not_measured，绝不写成 passed"),
        })
    elif repeat_value is None:
        gates.append({
            "name": "repeat_stability",
            "status": "NOT_MEASURED",
            "ok": not release,
            "severity": "release",
            "release_required": True,
            "detail": ("repeat_stability: 本次运行未测量（未带 --repeat 2，或样本不足）；"
                       + ("release gate 阻断——release 必须重复运行同一选择集"
                          if release else
                          "普通运行不阻断，`--release` 必须带 `--repeat 2`")),
        })
    else:
        repeat_ok = repeat_value >= 1.0
        gates.append({
            "name": "repeat_stability",
            "status": "PASS" if repeat_ok else "FAIL",
            "ok": repeat_ok,
            "severity": "always",
            "release_required": True,
            "detail": f"repeat_stability={repeat_value} (requirement >= 1.0)",
        })

    for metric, want, higher_is_better in (
        ("exact_numeric_accuracy", 1.0, True),
        ("answer_schema_valid_rate", 1.0, True),
        ("evidence_coverage", 1.0, True),
        ("cross_session_leak_rate", 0.0, False),
        ("unsupported_number_rate", 0.0, False),
        ("unsupported_causal_claim_rate", 0.0, False),
        ("unsupported_causal_claim_detection_rate", 1.0, True),
        ("proxy_disclosure_rate", 1.0, True),
        ("proxy_disclosure_detection_rate", 1.0, True),
    ):
        gates.append(_metric_gate(metric, metrics.get(metric), want,
                                  higher_is_better=higher_is_better,
                                  capable=metric in capable,
                                  skipped=skipped))

    # --- known-gap governance -------------------------------------------
    allowed = {str(cid) for cid in (allowlist or [])}
    p0_xfailed = sorted(r.case_id for r in results
                        if r.priority == "P0" and r.status == XFAIL)
    unlisted = [cid for cid in p0_xfailed if cid not in allowed]
    if unlisted and release:
        status, ok = "FAIL", False
        detail = (f"{len(unlisted)} P0 known gap(s) not in the audited allowlist: "
                  f"{unlisted[:6]}")
    elif unlisted:
        # A research run must stay actionable: the open defects are reported and
        # counted, but they do not stop local iteration.
        status, ok = "PASS", True
        detail = (f"research run: {len(unlisted)} unresolved P0 known gap(s) are reported "
                  f"separately and do not block local iteration; a `--release` run fails "
                  f"until each case_id is audited into the allowlist: {unlisted[:6]}")
    elif p0_xfailed:
        status, ok = "PASS", True
        detail = f"all {len(p0_xfailed)} P0 known gaps are allowlisted"
    else:
        status, ok = "PASS", True
        detail = "no unresolved P0 known gap"
    gates.append({
        "name": "p0_known_gap_allowlist",
        "status": status,
        "ok": ok,
        "severity": "release",
        "release_blocking": bool(unlisted),
        "detail": detail,
    })

    # Waivers must carry audit metadata and must not be expired.
    waiver_entries = (waivers or {}).get("entries") or []
    bad_waivers = [str(e.get("case_id")) for e in waiver_entries
                   if not all(str(e.get(key) or "").strip() for key in
                              ("case_id", "reviewer", "reviewed_at", "reason",
                               "expiry", "target_fix_version"))]
    expired = [str(e.get("case_id")) for e in waiver_entries
               if _waiver_expired(str(e.get("expiry") or ""))]
    if waiver_entries:
        gates.append({
            "name": "known_gap_waiver_metadata",
            "status": "FAIL" if bad_waivers else "PASS",
            "ok": not bad_waivers,
            "severity": "release",
            "detail": (f"{len(bad_waivers)} waiver(s) missing reviewer/reviewed_at/"
                       f"reason/expiry/target_fix_version: {bad_waivers[:6]}")
            if bad_waivers else f"{len(waiver_entries)} waiver(s) fully audited",
        })
        gates.append({
            "name": "known_gap_waiver_expiry",
            "status": "FAIL" if expired else "PASS",
            "ok": not expired,
            "severity": "release",
            "detail": (f"{len(expired)} expired waiver(s): {expired[:6]}") if expired
            else "no waiver has expired",
        })

    # A defect whose target fix version has already shipped must not stay open
    # silently: fix it, or re-target it with a fresh review note.
    version = product_version()
    overdue = sorted(r.case_id for r in results
                     if r.known_gap and _version_reached(version,
                                                         str((r.gap_meta or {}).get("target_fix_version") or "")))
    gates.append({
        "name": "known_gap_overdue",
        "status": "FAIL" if overdue else "PASS",
        "ok": not overdue,
        "severity": "release",
        "detail": (f"{len(overdue)} known gap(s) overdue at product version {version}: "
                   f"{overdue[:6]}") if overdue
        else f"no known gap is overdue at product version {version}",
    })

    security = sorted(r.case_id for r in _security_defects(results))
    gates.append({
        "name": "unresolved_security_defects",
        "status": "FAIL" if security else "PASS",
        "ok": not security,
        "severity": "release",
        "detail": (f"{len(security)} unresolved security defect(s) — credential/"
                   f"destructive-request handling cannot be waived indefinitely: "
                   f"{security[:6]}") if security
        else "no unresolved security defect",
    })

    xpassed = sorted(r.case_id for r in results if r.status == XPASS)
    gates.append({
        "name": "known_gap_xpass",
        "status": "PASS" if not xpassed else "FAIL",
        "ok": not xpassed,
        "severity": "always",
        "detail": (f"{len(xpassed)} known gap(s) now pass — remove the known_gap flag: "
                   f"{xpassed[:6]}") if xpassed else "no known gap flipped to pass",
    })

    if ratchet is not None:
        current = sum(1 for r in results if r.known_gap)
        current_p0 = sum(1 for r in results if r.known_gap and r.priority == "P0")
        limit = int(ratchet.get("known_gap_total", current))
        limit_p0 = int(ratchet.get("p0_known_gap", current_p0))
        ok = current <= limit and current_p0 <= limit_p0
        gates.append({
            "name": "known_gap_ratchet",
            "status": "PASS" if ok else "FAIL",
            "ok": ok,
            "severity": "always",
            "detail": (f"known_gap={current}/{limit}, p0_known_gap={current_p0}/{limit_p0} "
                       "(the budget may only shrink)"),
        })
    return gates


def _waiver_expired(expiry: str) -> bool:
    """True when a waiver's expiry date has passed (YYYY-MM-DD, UTC)."""
    match = re.match(r"^(\d{4})-(\d{2})-(\d{2})$", (expiry or "").strip())
    if not match:
        return True  # an unparseable expiry is an expired waiver
    import datetime as _dt

    try:
        when = _dt.date(int(match.group(1)), int(match.group(2)), int(match.group(3)))
    except ValueError:
        return True
    return when < _dt.datetime.now(_dt.timezone.utc).date()


# ``ontology-v0.1.3``, ``v0.1.3`` and ``0.1.3`` all spell the same version.
_VERSION_PREFIX_RE = re.compile(r"^(?:ontology-)?v?", re.IGNORECASE)


def _version_reached(current: str, target: str) -> bool:
    """True when *current* is at or beyond an ``X.Y.Z`` target version."""
    def parts(text: str) -> Optional[tuple]:
        stripped = _VERSION_PREFIX_RE.sub("", (text or "").strip())
        match = re.fullmatch(r"(\d+)\.(\d+)\.(\d+)", stripped)
        return tuple(int(g) for g in match.groups()) if match else None

    now, want = parts(current), parts(target)
    if not now or not want:
        return False
    return now >= want


WILDCARD_ALLOWLIST_TOKENS = ("*", "all", "ignore_all", "any")


def load_waivers(path_arg: str) -> dict:
    """The audited waiver document, verbatim.

    Deliberately a per-case list: there is no way to accept "all known gaps",
    and any wildcard or category-wide entry is rejected by the metadata gate.
    """
    path = Path(path_arg) if path_arg else EVAL_ROOT / "known_gap_allowlist.json"
    if not path.is_file():
        return {"entries": []}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {"entries": []}
    if isinstance(payload, dict):
        entries = payload.get("allowed_p0_known_gaps") or []
    else:
        entries = payload or []
    return {"entries": list(entries)}


def _load_known_gap_allowlist(path_arg: str) -> list[str]:
    """Case ids whose unresolved P0 defect is accepted for a release.

    Deliberately a per-case list: there is no way to accept "all known gaps".
    """
    out: list[str] = []
    entries = load_waivers(path_arg).get("entries") or []
    for entry in entries:
        if isinstance(entry, str):
            out.append(entry)
        elif isinstance(entry, dict) and entry.get("case_id"):
            case_id = str(entry["case_id"])
            if case_id.strip().lower() in WILDCARD_ALLOWLIST_TOKENS:
                # A wildcard must never widen a waiver into "ignore everything".
                continue
            out.append(case_id)
    return out


def _load_known_gap_ratchet(path_arg: str, results: list[CaseResult]) -> Optional[dict]:
    """Known-gap budget; only applied when the selection covers the whole set."""
    path = Path(path_arg) if path_arg else EVAL_ROOT / "known_gap_ratchet.json"
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    manifest_path = EVAL_ROOT / "manifest.json"
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    if len(results) < int(manifest.get("totals", {}).get("cases", 0)):
        # A partial selection would compare an incomplete population against a
        # whole-set budget.
        return None
    return payload


def build_report(
    results: list[CaseResult],
    suite: str,
    provider: str,
    skipped_live: str = "",
    repeat_agreement: Optional[float] = None,
    repeat: Optional[dict] = None,
    release: bool = False,
    allowlist: Optional[list[str]] = None,
    ratchet: Optional[dict] = None,
    waivers: Optional[dict] = None,
) -> dict:
    summary = aggregate(results)
    repeat_info = repeat or {}
    repeat_cases = int(repeat_info.get("cases") or 0)
    repeat_skipped = [str(cid) for cid in (repeat_info.get("skipped_case_ids") or [])]
    if repeat_info or repeat_agreement is not None:
        # Zero samples -- or samples that did not execute in every repetition --
        # must never be summarised as a score.  "1.0 from nothing" is exactly
        # what let the release gate pass without ever measuring stability.
        measured = (repeat_agreement is not None and repeat_cases > 0
                    and not repeat_skipped)
        stable = int(repeat_info.get("stable_cases") or 0)
        summary["metrics"]["repeat_stability"] = repeat_agreement if measured else None
        summary["metric_sample_sizes"]["repeat_stability"] = repeat_cases
        summary["metric_stats"]["repeat_stability"] = {
            "measured": measured,
            "applicable": repeat_cases,
            "passed": stable if measured else 0,
            "failed": (repeat_cases - stable) if measured else 0,
            "skipped": len(repeat_skipped),
            "known_gap_excluded": 0,
            "sample_size": repeat_cases,
            "numerator": stable if measured else 0,
            "denominator": repeat_cases,
        }
    # A skipped opt-in run has no evidence: every case is SKIP and no gate can
    # legitimately claim a pass or a failure.
    run_skipped = bool(skipped_live) and (
        not results or all(r.status == SKIP for r in results))
    gates = evaluate_gates(results, summary["metrics"], release=release,
                           allowlist=allowlist, ratchet=ratchet, waivers=waivers,
                           skipped=run_skipped)
    # Defect ledgers live on the summary as well as in ``defect_ledger`` so a
    # machine reader never has to hunt through nested report sections.
    summary["unresolved_security_defects"] = len(_security_defects(results))
    summary["overdue_known_gaps"] = [
        r.case_id for r in results
        if r.known_gap and _version_reached(
            product_version(), str((r.gap_meta or {}).get("target_fix_version") or ""))
    ]
    summary["expired_waivers"] = [
        str(e.get("case_id")) for e in ((waivers or {}).get("entries") or [])
        if _waiver_expired(str(e.get("expiry") or ""))
    ]
    blocking = [g for g in gates
                if not g["ok"] and (release or g.get("severity") == "always")]
    measured_gaps = summary.get("unresolved_p0_defects", 0)
    if run_skipped:
        # An opt-in suite without credentials produced no evidence at all.  It
        # must not read as a pass and must not read as a product failure.
        status = "not_measured"
    elif blocking:
        status = "fail"
    elif measured_gaps:
        # Never report a run with open P0 defects as a clean pass.
        status = "passed_with_open_defects"
    elif any(g["status"] in ("NOT_MEASURED",) for g in gates):
        status = "passed_with_unmeasured_metrics"
    else:
        status = "pass"

    def dist(key_fn) -> dict:
        out: dict[str, int] = {}
        for r in results:
            for key in key_fn(r):
                out[key] = out.get(key, 0) + 1
        return dict(sorted(out.items()))

    failures = []
    for r in results:
        if r.status != FAIL:
            continue
        failures.append({
            "case_id": r.case_id,
            "category": r.category,
            "evaluator": r.evaluator,
            "priority": r.priority,
            "question": r.question,
            "scope": r.scope,
            "expected": {c.name: c.expected for c in r.failed_checks},
            "actual": {c.name: c.actual for c in r.failed_checks},
            "detail": {c.name: c.detail for c in r.failed_checks if c.detail},
            "tool_chain_or_evidence": r.evidence,
            "forbidden": r.forbidden,
            "error": r.error,
        })

    return {
        "schema_version": 1,
        "suite": suite,
        "provider": provider,
        "status": status,
        "summary": summary,
        "gates": gates,
        "distributions": {
            "category": dist(lambda r: [r.category]),
            "priority": dist(lambda r: [r.priority]),
            "evaluator": dist(lambda r: [r.evaluator]),
        },
        # What a recorded replay can and cannot prove, stated in the artifact
        # itself so nobody reads a green replay as "the real model behaves".
        "capability": {
            "recording": "production_loop_with_recorded_model_decisions",
            "proves": [
                "the production WebSession turn loop runs",
                "recorded tool calls are parsed and executed by the production tools",
                "SQL / ontology / chart / recovery / evidence handling is correct",
                "session state advances as expected",
            ],
            "does_not_prove": [
                "the current real model still chooses these tools",
                "a prompt change did not regress model decisions",
                "the model adds no new hallucinations",
                "the live provider protocol is unchanged",
            ],
            "requires": ("a live canary run is still required before claiming model "
                         "behaviour is accepted"),
        },
        # Open defects, split the way a release decision needs them.  A single
        # "known_gap" number hides the difference between a cosmetic gap and an
        # unresolved credential-handling defect.
        "defect_ledger": {
            "known_gap_total": sum(1 for r in results if r.known_gap),
            "known_gap_p0": sum(1 for r in results if r.known_gap and r.priority == "P0"),
            "known_gap_security": len(_security_defects(results)),
            "unresolved_security_defects": len(_security_defects(results)),
            "overdue_known_gaps": [
                r.case_id for r in results
                if r.known_gap and _version_reached(
                    product_version(),
                    str((r.gap_meta or {}).get("target_fix_version") or ""))
            ],
            "expired_waivers": [
                str(e.get("case_id")) for e in ((waivers or {}).get("entries") or [])
                if _waiver_expired(str(e.get("expiry") or ""))
            ],
            "unresolved_p0_defects": summary.get("unresolved_p0_defects", 0),
        },
        "known_gaps": [
            {"case_id": r.case_id, "question": r.question, "note": r.gap_note,
             "status": r.status, "priority": r.priority, "meta": r.gap_meta}
            for r in results if r.known_gap
        ],
        "waivers": {
            "entries": list((waivers or {}).get("entries") or []),
            "allowlisted_case_ids": sorted(set(allowlist or [])),
        },
        "repeat": repeat or {},
        "live_run_map": [
            {
                "case_id": r.case_id,
                "domain": r.run_meta.get("domain"),
                "fixture_db": r.run_meta.get("fixture_db"),
                "conversation_group": r.run_meta.get("session_id"),
            }
            for r in results if r.run_meta.get("fixture_db")
        ],
        "skipped": {
            "live": skipped_live,
            "cases": [r.case_id for r in results if r.status == SKIP],
        },
        "results": [
            {
                "case_id": r.case_id,
                "category": r.category,
                "evaluator": r.evaluator,
                "priority": r.priority,
                "status": r.status,
                "question": r.question,
                "scope": r.scope,
                "forbidden": r.forbidden,
                "gap_note": r.gap_note,
                "duration_ms": r.duration_ms,
                "checks": [asdict(c) for c in r.checks],
                "metrics": r.metrics,
                "known_gap": r.known_gap,
                "evidence": r.evidence,
                "error": r.error,
            }
            for r in results
        ],
    }


# Anything in the environment whose *name* looks like a credential is never
# allowed to reach a report.  A report is an artifact that gets pasted into
# issues, attached to CI jobs and committed as a baseline, so "we did not pass
# the key to build_report" is not a strong enough guarantee.
_SECRET_ENV_NAME_RE = re.compile(
    r"(API_?KEY|_TOKEN|^TOKEN|SECRET|PASSWORD|CREDENTIAL)", re.IGNORECASE)
_REDACTED = "***redacted***"


def _secret_env_values() -> dict[str, str]:
    import os

    found: dict[str, str] = {}
    for name, value in os.environ.items():
        if not _SECRET_ENV_NAME_RE.search(name):
            continue
        text = str(value or "").strip()
        if len(text) >= 8:
            found[name] = text
    return found


def redact_secrets(payload: dict) -> dict:
    """Remove provider credentials that leaked into a report payload.

    Deliberately a text-level scrub: it also catches a key embedded in a nested
    evidence blob or inside a provider error message.
    """
    secrets = _secret_env_values()
    if not secrets:
        return payload
    text = json.dumps(payload, ensure_ascii=False)
    changed = False
    for value in secrets.values():
        if value in text:
            text = text.replace(value, _REDACTED)
            changed = True
    return json.loads(text) if changed else payload


def build_baseline(report: dict) -> dict:
    """Reduce a full report to the part a committed baseline needs.

    ``compare_reports`` only reads ``summary.metrics``, ``summary.p0_passed``
    and ``gates``; the per-case statuses are kept so a reviewer can diff which
    case changed without carrying every expected/actual payload in git.
    """
    summary = dict(report["summary"])
    summary.pop("metrics", None)
    return {
        "schema_version": report["schema_version"],
        "kind": "baseline",
        "suite": report["suite"],
        "provider": report["provider"],
        "summary": {**summary, "metrics": report["summary"]["metrics"]},
        "gates": [{"name": g["name"], "ok": g["ok"]} for g in report["gates"]],
        "distributions": report["distributions"],
        "known_gaps": [
            {"case_id": g["case_id"], "status": g["status"]}
            for g in report["known_gaps"]
        ],
        "cases": [
            {"case_id": r["case_id"], "status": r["status"],
             "duration_ms": r["duration_ms"]}
            for r in report["results"]
        ],
    }


def render_markdown(report: dict) -> str:
    summary = report["summary"]
    metrics = summary["metrics"]
    lines: list[str] = []
    lines.append(f"# 分析 Agent 黄金评测报告 · suite={report['suite']}")
    lines.append("")
    lines.append(f"- 用例总数：{summary['cases']}（P0 {summary['p0_cases']}，通过 {summary['passed']}，失败 {summary['failed']}）")
    lines.append(f"- 通过率：{summary['pass_rate']}")
    lines.append(
        f"- P0 契约用例：{summary.get('p0_total', 0)} 总数"
        f"（{summary.get('p0_passed', 0)} passed + "
        f"{summary.get('p0_xfailed', 0)} unresolved known gaps + "
        f"{summary.get('p0_xpassed', 0)} xpass + {summary.get('p0_failed', 0)} failed）"
    )
    lines.append(
        f"- unresolved_p0_defects：{summary.get('unresolved_p0_defects', 0)}"
        "（research 运行不阻塞，release 运行必须被 allowlist 覆盖）"
    )
    lines.append(f"- known_gap（按当前行为断言的真实缺陷）：{summary['known_gap_cases']}"
                 f"（xfail {summary['known_gap_xfail']}，xpass {summary['known_gap_xpass']}）")
    lines.append(f"- 总耗时：{summary['duration_ms']} ms")
    if report.get("provider"):
        lines.append(f"- provider：{report['provider']}")
    if report["skipped"].get("live"):
        lines.append(f"- live 套件：{report['skipped']['live']}")
    lines.append("")
    lines.append("## 指标")
    lines.append("")
    lines.append("| 指标 | 值 | 状态 | 样本数 | 通过 | 失败 | known_gap 排除 | 分母 |")
    lines.append("| --- | ---: | --- | ---: | ---: | ---: | ---: | ---: |")
    stats_by_metric = summary.get("metric_stats") or {}
    for name in sorted(set(ALL_METRICS) | set(stats_by_metric)):
        value = metrics.get(name)
        stats = stats_by_metric.get(name) or {}
        state = "measured" if stats.get("measured") else "NOT_MEASURED"
        shown = "未测量" if value is None else f"{value}"
        lines.append(
            f"| {name} | {shown} | {state} | {stats.get('sample_size', 0)} | "
            f"{stats.get('passed', 0)} | {stats.get('failed', 0)} | "
            f"{stats.get('known_gap_excluded', 0)} | {stats.get('denominator', 0)} |")
    lines.append("")
    lines.append("## 门禁")
    lines.append("")
    lines.append("| 门禁 | 结果 | 说明 |")
    lines.append("| --- | --- | --- |")
    for gate in report["gates"]:
        lines.append(f"| {gate['name']} | {gate.get('status', 'FAIL')} | {gate['detail']} |")
    lines.append("")
    lines.append("## 这套评测能证明什么")
    lines.append("")
    capability = report.get("capability") or {}
    if capability:
        lines.append(f"- 录制回放口径：`{capability.get('recording')}`")
        lines.append("- 可以证明：" + "；".join(capability.get("proves") or []))
        lines.append("- 不能证明：" + "；".join(capability.get("does_not_prove") or []))
        lines.append(f"- 额外要求：{capability.get('requires')}")
    if report.get("repeat"):
        repeat = report["repeat"]
        lines.append(f"- 重复运行：{repeat.get('repeat')} 次，"
                     f"repeat_stability={repeat.get('agreement')}，"
                     f"不稳定用例={repeat.get('unstable_case_ids')}")
    live_map = report.get("live_run_map") or []
    if live_map:
        lines.append("")
        lines.append("| live case | domain | fixture db | conversation group |")
        lines.append("| --- | --- | --- | --- |")
        for row in live_map:
            lines.append(f"| {row.get('case_id')} | {row.get('domain')} | "
                         f"{row.get('fixture_db')} | {row.get('conversation_group')} |")
    lines.append("")
    lines.append("## 分布")
    lines.append("")
    for key, dist in report["distributions"].items():
        lines.append(f"- {key}：" + "，".join(f"{k}={v}" for k, v in dist.items()))
    lines.append("")
    if report["known_gaps"]:
        lines.append("## 已记录的真实缺陷（known_gap，本轮未修业务）")
        lines.append("")
        for gap in report["known_gaps"]:
            meta = gap.get("meta") or {}
            owner = meta.get("owner", "?")
            severity = meta.get("severity", "?")
            target = meta.get("target_fix_version", "?")
            lines.append(f"- `{gap['case_id']}`（{gap['status']} · P{gap.get('priority', '?')} · "
                         f"{severity} · owner={owner} · target={target}）：{gap['question']}")
            if gap["note"]:
                lines.append(f"  - {gap['note']}")
        lines.append("")
    if report["skipped"]["cases"]:
        lines.append("## 跳过")
        lines.append("")
        lines.append("- " + "，".join(report["skipped"]["cases"][:40]))
        lines.append("")
    failures = [r for r in report["results"] if r["status"] == "fail"]
    lines.append(f"## 失败明细（{len(failures)}）")
    lines.append("")
    for fail in failures:
        lines.append(f"### {fail['case_id']} · {fail['category']} · {fail['priority']}")
        lines.append("")
        lines.append(f"- 问题：{fail['question']}")
        if fail.get("scope"):
            lines.append(f"- 口径：{fail['scope']}")
        if fail.get("error"):
            lines.append(f"- 错误：{fail['error']}")
        for check in fail["checks"]:
            if check["ok"]:
                continue
            lines.append(f"- 断言 `{check['name']}` 失败：期望 {_format(check['expected'])}，实际 {_format(check['actual'])}")
            if check.get("detail"):
                lines.append(f"  - {check['detail']}")
        evidence = fail.get("evidence") or {}
        if evidence.get("sql"):
            lines.append(f"- 参考 SQL：`{evidence['sql']}`")
        if evidence.get("rows") is not None:
            lines.append(f"- 实际数据：{_format(evidence['rows'])}")
        if evidence.get("tool_chain"):
            lines.append(f"- 实际工具链：{evidence['tool_chain']}")
        if evidence.get("answer"):
            lines.append(f"- 实际回答（截断）：{evidence['answer'][:400]}")
        lines.append("")
    return "\n".join(lines) + "\n"


# ---------------------------------------------------------------------------
# baseline comparison
# ---------------------------------------------------------------------------
def compare_reports(baseline: dict, candidate: dict) -> tuple[bool, list[str]]:
    lines: list[str] = []
    ok = True
    base_metrics = baseline.get("summary", {}).get("metrics", {})
    cand_metrics = candidate.get("summary", {}).get("metrics", {})
    lines.append("| 指标 | baseline | candidate | 变化 | 结论 |")
    lines.append("| --- | ---: | ---: | ---: | --- |")
    for name in ALL_METRICS:
        base = base_metrics.get(name)
        cand = cand_metrics.get(name)
        if base is None and cand is None:
            continue
        if base is None or cand is None:
            lines.append(f"| {name} | {base} | {cand} | - | 样本不可比 |")
            ok = False
            continue
        delta = round(cand - base, 6)
        lower_is_better = name in ("unsupported_number_rate", "unsupported_causal_claim_rate",
                                   "cross_session_leak_rate")
        regressed = (delta > 1e-9) if lower_is_better else (delta < -1e-9)
        if regressed:
            ok = False
        lines.append(f"| {name} | {base} | {cand} | {delta:+} | {'回归' if regressed else 'ok'} |")
    base_p0 = baseline.get("summary", {}).get("p0_passed")
    cand_p0 = candidate.get("summary", {}).get("p0_passed")
    if base_p0 is not None and cand_p0 is not None and cand_p0 < base_p0:
        ok = False
        lines.append(f"\nP0 通过数下降：{base_p0} → {cand_p0}")
    for gate in candidate.get("gates", []):
        if not gate["ok"]:
            ok = False
    return ok, lines


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------
def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m scripts.run_analytics_eval",
        description="Deterministic golden-set runner for the analytics agent.",
    )
    parser.add_argument("--suite", default="smoke", choices=SUITES,
                        help="which suite to run (default: smoke)")
    parser.add_argument("--case", action="append", dest="cases", default=None,
                        help="run only these case ids/prefixes (repeatable)")
    parser.add_argument("--category", action="append", dest="categories", default=None,
                        help="run only these case categories (repeatable)")
    parser.add_argument("--provider", default="team",
                        help="LLM provider for --suite live (default: team)")
    parser.add_argument("--answers", default="",
                        help="score recorded answers: JSON {case_id: answer}")
    parser.add_argument("--repeat", type=int, default=None,
                        help="run the selection N times to measure repeat_stability "
                             "(N >= 2; omitting it means a single run, which reports "
                             "repeat_stability as not_measured)")
    parser.add_argument("--out", default="",
                        help="directory for the JSON/Markdown report "
                             f"(default: {DEFAULT_REPORT_DIR})")
    parser.add_argument("--json", default="", help="explicit JSON report path")
    parser.add_argument("--markdown", default="", help="explicit Markdown report path")
    parser.add_argument("--baseline", default="", help="write this run as a baseline JSON")
    parser.add_argument("--compare", nargs=2, metavar=("BASELINE", "CANDIDATE"),
                        help="compare two report JSON files and exit non-zero on regression")
    parser.add_argument("--list", action="store_true", help="list selected cases and exit")
    parser.add_argument("--no-gate", action="store_true",
                        help="report gate failures but exit 0")
    parser.add_argument("--release", action="store_true",
                        help="release gate: unresolved P0 known gaps must all be "
                             "covered by the audited allowlist")
    parser.add_argument("--live-budget-seconds", type=float, default=1800.0,
                        help="wall-clock budget for a live/live-canary run; once it "
                             "is gone the remaining cases are skipped, not measured "
                             "(0 disables the budget)")
    parser.add_argument("--allowlist", default="",
                        help="audited known-gap allowlist JSON (default: "
                             "dataset/evals/analytics/known_gap_allowlist.json)")
    parser.add_argument("--ratchet", default="",
                        help="known-gap ratchet baseline JSON (default: "
                             "dataset/evals/analytics/known_gap_ratchet.json)")
    parser.add_argument("--verbose", action="store_true")
    return parser


def main(argv: Optional[list[str]] = None) -> int:
    args = build_parser().parse_args(argv)

    if args.compare:
        base_path, cand_path = (Path(args.compare[0]), Path(args.compare[1]))
        with base_path.open(encoding="utf-8") as handle:
            baseline = json.load(handle)
        with cand_path.open(encoding="utf-8") as handle:
            candidate = json.load(handle)
        ok, lines = compare_reports(baseline, candidate)
        print(f"# baseline vs candidate\n\n" + "\n".join(lines))
        return 0 if ok else 1

    cases = load_cases()
    selected = select_cases(cases, args.suite, args.cases, args.categories)
    if args.list:
        for case in selected:
            db = fixture_db_for_case(case) or "-"
            print(f"{case['case_id']:<18} {case['priority']:<3} {case['category']:<16} "
                  f"{case['evaluator']:<18} {db:<18} {case['question']}")
        print(f"# {len(selected)} case(s)")
        return 0
    if not selected:
        print(f"no cases matched suite={args.suite}", file=sys.stderr)
        return 2

    live_suite = args.suite in ("live", "live-canary")
    ctx = EvalContext(verbose=args.verbose)
    skipped_live = ""
    budget_exhausted = False
    live_budget_used = 0.0
    live_active = False
    answers: dict[str, str] = {}
    if args.answers:
        with Path(args.answers).open(encoding="utf-8") as handle:
            answers = json.load(handle)

    def new_harness() -> LiveHarness:
        """A brand-new, fully isolated harness (one per repetition)."""
        harness = LiveHarness(ctx, provider=args.provider)
        ctx.live_harness = harness
        return harness

    try:
        if args.answers:
            results = []
            for case in selected:
                answer = answers.get(case["case_id"])
                if answer is None:
                    result = CaseResult(
                        case_id=case["case_id"], category=case.get("category", ""),
                        evaluator=case.get("evaluator", ""), priority=case.get("priority", "P1"),
                        status=SKIP, question=case.get("question", ""),
                        checks=[Check("answers.provided", False, "recorded answer", None)],
                        answer_requirements=tuple(case.get("answer_requirements") or ()),
                    )
                else:
                    # Case-scoped grounding: an answer may only cite numbers this
                    # case's own question or declared constants contain.
                    pool = CaseGroundingPool(case)
                    unsupported = pool.unsupported(answer)
                    checks, metrics = score_answer(case, answer, pool.pool)
                    result = _result_from(case, checks)
                    result.evaluator = "answers"
                    result.metrics.update(metrics)
                    result.metrics["unsupported_number_rate"] = bool(unsupported)
                    result.metrics["answer_schema_valid_rate"] = bool(answer)
                    result.signature = {
                        "answer_numbers": sorted(_numbers_in(answer)),
                        "unsupported": sorted(unsupported),
                        "answer_structure": _answer_structure(answer),
                    }
                    result.evidence = {"answer": answer[:4000],
                                       "unsupported_numbers": sorted(unsupported)[:12]}
                    result.run_meta = {"case_id": case["case_id"],
                                       "domain": case.get("domain"),
                                       "fixture_db": fixture_db_for_case(case)}
                results.append(result)
        elif live_suite:
            load_provider_env()
            if not provider_available(args.provider):
                names = ", ".join(PROVIDER_ENV.get(args.provider, ("(unknown provider)",)))
                skipped_live = (f"provider={args.provider} 未配置凭据（{names}），"
                                f"{args.suite} 套件标记为 not_measured；离线套件不受影响")
                results = [
                    CaseResult(
                        case_id=c["case_id"], category=c.get("category", ""),
                        evaluator="live", priority=c.get("priority", "P1"), status=SKIP,
                        question=c.get("question", ""),
                        checks=[Check("live.credentials", False, "provider credentials", "")],
                        answer_requirements=tuple(c.get("answer_requirements") or ()),
                        run_meta={"case_id": c["case_id"], "domain": c.get("domain"),
                                  "fixture_db": fixture_db_for_case(c)},
                    )
                    for c in selected
                ]
            else:
                live_active = True
                harness = new_harness()
                order_problems = harness.check_order(selected)
                # A live suite spends real money and real time, so it runs under
                # an explicit wall-clock budget: once the budget is gone the
                # remaining cases are skipped (and reported as not measured),
                # never silently dropped and never reported as passed.
                budget = max(0.0, float(args.live_budget_seconds))
                budget_started = time.monotonic()
                results = []
                budget_exhausted = False
                for case in selected:
                    if budget and time.monotonic() - budget_started > budget:
                        budget_exhausted = True
                        results.append(CaseResult(
                            case_id=case["case_id"], category=case.get("category", ""),
                            evaluator="live", priority=case.get("priority", "P1"),
                            status=SKIP, question=case.get("question", ""),
                            checks=[Check("live.suite_budget", False,
                                          f"budget {int(budget)}s", "exhausted")],
                            answer_requirements=tuple(case.get("answer_requirements") or ()),
                            run_meta={"case_id": case["case_id"],
                                      "domain": case.get("domain"),
                                      "fixture_db": fixture_db_for_case(case)},
                        ))
                        continue
                    results.append(run_case(case, ctx, evaluator_override="live"))
                live_budget_used = time.monotonic() - budget_started
                if order_problems:
                    for result in results:
                        result.checks.append(Check("live.group_order", False, [], order_problems))
                        result.status = FAIL
        else:
            results = [run_case(case, ctx) for case in selected]

        repeat_report: Optional[dict] = None
        if args.repeat and args.repeat > 1:
            collected: list[CaseResult] = []
            override = "live" if (live_suite and live_active) else ""
            repeat_report = measure_repeat(
                selected, ctx, args.repeat,
                evaluator_override=override,
                collected=collected,
                reset=new_harness if live_active else None,
            )
            if collected:
                # The first repetition's results drive the report; repeats only
                # feed the stability metric.
                results = collected

        if budget_exhausted:
            note = (f"{args.suite} 套件预算 {int(args.live_budget_seconds)}s 已用完，"
                    f"剩余用例被跳过并计为 not_measured（不会写成 passed）")
            skipped_live = f"{skipped_live}；{note}" if skipped_live else note

        allowlist = _load_known_gap_allowlist(args.allowlist)
        ratchet = _load_known_gap_ratchet(args.ratchet, results)
        waivers = load_waivers(args.allowlist)
        report = redact_secrets(build_report(results, args.suite, args.provider,
                              skipped_live=skipped_live,
                              repeat_agreement=(repeat_report or {}).get("agreement"),
                              repeat=repeat_report,
                              release=args.release, allowlist=allowlist,
                              ratchet=ratchet, waivers=waivers))
        if live_suite:
            report["live_budget_seconds"] = float(args.live_budget_seconds)
            report["live_budget_used_seconds"] = round(live_budget_used, 3)
            report["live_cost"] = _live_cost(results)

        out_dir = Path(args.out) if args.out else DEFAULT_REPORT_DIR
        out_dir.mkdir(parents=True, exist_ok=True)
        json_path = Path(args.json) if args.json else out_dir / f"report-{args.suite}.json"
        md_path = Path(args.markdown) if args.markdown else out_dir / f"report-{args.suite}.md"
        with json_path.open("w", encoding="utf-8") as handle:
            json.dump(report, handle, ensure_ascii=False, indent=2)
            handle.write("\n")
        md_path.write_text(render_markdown(report), encoding="utf-8")
        if args.baseline:
            baseline_path = Path(args.baseline)
            baseline_path.parent.mkdir(parents=True, exist_ok=True)
            baseline_path.write_text(
                json.dumps(build_baseline(report), ensure_ascii=False, indent=2) + "\n",
                encoding="utf-8")

        summary = report["summary"]
        print(f"suite={report['suite']} status={report['status']} cases={summary['cases']} "
              f"passed={summary['passed']} failed={summary['failed']} "
              f"pass_rate={summary['pass_rate']}")
        print(f"known_gap={summary['known_gap_cases']} duration_ms={summary['duration_ms']}")
        print(f"p0: total={summary.get('p0_total', 0)} passed={summary.get('p0_passed', 0)} "
              f"failed={summary.get('p0_failed', 0)} xfail={summary.get('p0_xfailed', 0)} "
              f"xpass={summary.get('p0_xpassed', 0)} "
              f"unresolved={summary.get('unresolved_p0_defects', 0)}")
        print("metrics:")
        for name, stats in sorted((summary.get("metric_stats") or {}).items()):
            value = summary["metrics"].get(name)
            state = "measured" if stats.get("measured") else "not_measured"
            print(f"  {name}={value} ({state}, n={stats.get('sample_size', 0)}, "
                  f"passed={stats.get('passed', 0)}, failed={stats.get('failed', 0)}, "
                  f"known_gap_excluded={stats.get('known_gap_excluded', 0)})")
        if skipped_live:
            print(f"live: {skipped_live}")
        if live_suite:
            cost = report.get("live_cost")
            print(f"live budget: {report.get('live_budget_used_seconds', 0):.1f}s / "
                  f"{report.get('live_budget_seconds', 0):.0f}s "
                  f"(0 = unlimited), cost={cost if cost is not None else 'n/a'}")
        for gate in report["gates"]:
            print(f"  gate {gate['name']}: {gate['status']} — {gate['detail']}")
        print(f"reports: {json_path} , {md_path}")
        for result in results:
            if result.status == FAIL:
                print(f"  FAIL {result.case_id}: " + "; ".join(
                    f"{c.name} expected={_format(c.expected, 80)} actual={_format(c.actual, 80)}"
                    for c in result.failed_checks[:3]
                ))
        blocking_gates = [g for g in report["gates"]
                          if not g["ok"] and (args.release or g.get("severity") == "always")]
        if blocking_gates and not args.no_gate:
            return 1
        if args.repeat is not None and args.repeat < 2:
            # A single repetition is not a stability measurement.  Refusing the
            # request is what stops ``--repeat 1`` from quietly degrading into a
            # normal run that reports success without any evidence.
            print("--repeat must be >= 2 (omit it for a single run); "
                  "repeat_stability is not_measured for a single run", file=sys.stderr)
            return 2
        return 0
    finally:
        ctx.cleanup()


if __name__ == "__main__":
    raise SystemExit(main())
