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
    "ontology", "charts", "diagnosis", "recorded-provider", "live", "all",
]

PASS = "pass"
FAIL = "fail"
SKIP = "skip"
XFAIL = "xfail"   # known_gap case that still fails -> documented defect, not a gate breach
XPASS = "xpass"   # known_gap case that now passes -> the defect is closed, promote the case

# Mirror of bi_agent.web.session._RECOVERY_STOP_STATUSES: a tool reaching one of
# these ends the turn immediately, without any assistant narrative.
TURN_STOP_STATUSES = frozenset({"FAILED_RETRYABLE", "FAILED_FINAL", "CANCELLED"})

# Metrics that can only be produced by scoring a real/simulated answer.
LIVE_ONLY_METRICS = (
    "unsupported_number_rate",
    "unsupported_causal_claim_rate",
    "proxy_disclosure_rate",
)

ALL_METRICS = (
    "intent_accuracy",
    "tool_route_accuracy",
    "query_contract_accuracy",
    "exact_numeric_accuracy",
    "metric_scope_accuracy",
    "unsupported_number_rate",
    "unsupported_causal_claim_rate",
    "evidence_coverage",
    "proxy_disclosure_rate",
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
    known_gap: bool = False
    gap_note: str = ""
    gap_meta: dict = field(default_factory=dict)
    unknown_fields: list = field(default_factory=list)
    error: str = ""

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
                      "policy.reason_code")
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
PROXY_KEYWORDS = ("代理", "近似", "间接", "相关的", "不能直接证明", "间接证据")
SCOPE_KEYWORDS = ("口径", "统计范围", "范围", "过滤", "仅统计", "排除", "定义")
LIMITATION_KEYWORDS = ("限制", "不确定", "无法确认", "数据缺失", "缺月", "不足以", "无法唯一归因",
                       "可能", "样本")
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


def score_answer(case: dict, answer: str, allowed_numbers: set[float]) -> tuple[list[Check], dict[str, bool]]:
    """Score one natural-language answer against the case's declared rules."""

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

    if "must_separate_correlation_from_cause" in requirements:
        causal = bool(re.search(r"(因为|导致|造成|由于)", text))
        hedged = any(k in text for k in ("相关", "可能", "无法确认", "需要进一步", "不能证明"))
        ok = (not causal) or hedged
        checks.append(Check("answer.correlation_not_causation", ok, True, ok))
        metrics["unsupported_causal_claim_rate"] = not ok

    if "must_use_proxy_disclosure_if_proxy_used" in requirements:
        proxy_used = bool(re.search(r"(周转|账龄|间接)", text))
        disclosed = any(k in text for k in PROXY_KEYWORDS)
        ok = (not proxy_used) or disclosed
        checks.append(Check("answer.proxy_disclosure", ok, True, ok))
        metrics["proxy_disclosure_rate"] = ok

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


def build_live_session(ctx: EvalContext):
    """Build one throw-away WebSession bound to the eval fixtures.

    Everything the session writes (charts, conversations, logs) lands in the
    runner's temp directory; ``dataset/conversations`` is never touched.
    """
    import os

    from bi_agent.web import app as web_app

    workspace = ctx.tmpdir / "live-workspace"
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
            db_path=str(SQLITE_DIR / "procurement.db"),
            use_doris=False,
        )
        return web_app._ensure_session("analytics-eval")
    finally:
        if previous_backend is None:
            os.environ.pop("ONTOLOGY_BACKEND", None)
        else:
            os.environ["ONTOLOGY_BACKEND"] = previous_backend


def run_live_turn(session, question: str, timeout_seconds: float = 300.0) -> dict:
    """Run one turn and return the answer text + actual tool chain."""

    answer_parts: list[str] = []
    tool_chain: list[str] = []
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
        "policy": policy,
        "error": error,
        "blocked": blocked,
        "event_types": event_types,
        "answer_validation": answer_validation,
        "recovery": recovery,
        "cost": getattr(usage, "total_cost", None) if usage is not None else None,
    }


def eval_live(case: dict, ctx: EvalContext) -> CaseResult:
    session = ctx.live_session
    run = run_live_turn(session, case["question"])
    checks: list[Check] = []
    if run["error"]:
        checks.append(Check("live.no_error", False, "", run["error"]))
    checks.append(Check("live.answer_present", bool(run["answer"]), True, bool(run["answer"])))
    semantic_checks, semantic_metrics = score_answer(case, run["answer"], ctx.allowed_numbers)
    checks.extend(semantic_checks)
    result = _result_from(case, checks)
    result.metrics.update(semantic_metrics)
    result.metrics["answer_schema_valid_rate"] = bool(run["answer"]) and not run["blocked"]
    result.evidence = {
        "answer": run["answer"][:4000],
        "tool_chain": run["tool_chain"],
        "policy": run["policy"],
        "blocked": run["blocked"],
        "error": run["error"],
        "event_types": run["event_types"],
        "answer_validation": run["answer_validation"],
        "recovery": run.get("recovery", {}),
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
    """Every business-looking number in a natural-language answer.

    Numbers below 100 without a decimal point are treated as prose (dates,
    counts of steps, enumerations) and ignored, mirroring ``_numbers_in``.
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


def _numbers_from_text_pool(text: str) -> set[float]:
    out: set[float] = set()
    for raw in NUMBER_TOKEN_RE.findall(text or ""):
        raw = raw.replace(",", "")
        try:
            value = float(raw)
        except ValueError:
            continue
        if value.is_integer() and abs(value) <= 12:
            continue
        out.add(round(value, 6))
    return out


def _is_grounded(value: float, pool: set[float]) -> bool:
    """True when *value* is a pool number or a plausible transform of one."""
    def close(a: float, b: float) -> bool:
        return abs(a - b) <= max(1e-6, 1e-6 * abs(b))

    for candidate in pool:
        if close(value, candidate):
            return True
        if close(value, candidate * 100) or close(value, candidate / 100):
            return True
        for digits in (0, 1, 2, 3, 4):
            if close(value, round(candidate, digits)):
                return True
        # A ratio rendered as a percentage: 0.38788 -> "38.79%".
        for digits in (0, 1, 2):
            if close(value, round(candidate * 100, digits)):
                return True
    return False


class RecordedPool:
    """Case-scoped grounding pool: this case's own evidence only."""

    def __init__(self, case: dict, run: Any) -> None:
        pool: set[float] = set()
        for call in run.tool_calls:
            pool |= _numbers_from_text_pool(str(call.get("output") or ""))
            pool |= _numbers_from_text_pool(str(call.get("input") or ""))
        expected = case.get("expected") or {}
        for value in expected.get("allowed_numbers") or []:
            try:
                pool.add(round(float(value), 6))
            except (TypeError, ValueError):
                continue
        pool |= _numbers_from_text_pool(case.get("question") or "")
        for turn in case.get("conversation") or []:
            pool |= _numbers_from_text_pool(str(turn.get("content") or ""))
        self.pool = pool

    def unsupported(self, text: str) -> set[float]:
        found = _parse_number_tokens(text)
        return {n for n in found
                if n not in STRUCTURAL_NUMBERS and not _is_grounded(n, self.pool)}


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
    workspace = ctx.new_sandbox(case["case_id"])
    run = run_recorded_turns(
        case["case_id"],
        transcript["turns"],
        fixture_db=str(fixture.get("db") or "procurement.db"),
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
    if unsupported:
        result.metrics["unsupported_number_rate"] = True


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

    pool = RecordedPool(case, run)
    unsupported = pool.unsupported(run.text)
    checks.extend(_grounding_checks("recorded", expected, unsupported))

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
    _record_grounding_metric(result, expected, unsupported)
    result.evidence = evidence
    return result


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
    pool = RecordedPool(case, run)
    unsupported = pool.unsupported(run.text)
    checks.extend(_grounding_checks("grounding", expected, unsupported))
    for fragment in expected.get("final_text_contains", []):
        checks.append(Check(f"grounding.text_contains[{str(fragment)[:24]}]",
                            str(fragment) in run.text, fragment, run.text[:200]))
    for fragment in expected.get("final_text_absent", []):
        checks.append(Check(f"grounding.text_absent[{str(fragment)[:24]}]",
                            str(fragment) not in run.text, "absent", "present"))
    answer_checks, metrics = score_answer(case, run.text, pool.pool)
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
    return result


# ---------------------------------------------------------------------------
# aggregation + gates
# ---------------------------------------------------------------------------
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
    for name in ALL_METRICS:
        values = [r.metrics[name] for r in contract if name in r.metrics]
        if not values:
            metrics[name] = None
            counts[name] = 0
            continue
        metrics[name] = round(sum(1 for v in values if v) / len(values), 6)
        counts[name] = len(values)
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
        "duration_ms": round(sum(r.duration_ms for r in results), 3),
    }


def evaluate_gates(results: list[CaseResult], metrics: dict, *,
                   release: bool = False,
                   allowlist: Optional[list[str]] = None,
                   ratchet: Optional[dict] = None) -> list[dict]:
    """P0 gates from the task spec: any breach makes the run exit non-zero.

    ``release=True`` turns the P0 known-gap allowlist into a hard gate.  A
    research run reports the same numbers but does not block, because an open
    defect must be visible without making local iteration impossible.  There is
    deliberately no "ignore all known gaps" switch: an override must name the
    individual ``case_id`` values it covers.
    """

    p0 = [r for r in results if r.priority == "P0" and not r.known_gap]
    gates = [
        {
            "name": "p0_all_pass",
            "ok": all(r.status == PASS for r in p0),
            "detail": f"{sum(1 for r in p0 if r.status == PASS)}/{len(p0)} P0 contract cases passed",
        },
    ]
    for metric, want, cmp_fn in (
        ("exact_numeric_accuracy", 1.0, lambda a, b: a >= b),
        ("answer_schema_valid_rate", 1.0, lambda a, b: a >= b),
        ("evidence_coverage", 1.0, lambda a, b: a >= b),
        ("cross_session_leak_rate", 0.0, lambda a, b: a <= b),
        ("unsupported_number_rate", 0.0, lambda a, b: a <= b),
        ("unsupported_causal_claim_rate", 0.0, lambda a, b: a <= b),
        ("proxy_disclosure_rate", 1.0, lambda a, b: a >= b),
    ):
        value = metrics.get(metric)
        if value is None:
            gates.append({"name": metric, "ok": True,
                          "detail": "not measured in this suite (live-only or absent)"})
            continue
        gates.append({
            "name": metric,
            "ok": bool(cmp_fn(value, want)),
            "detail": f"{metric}={value} (requirement {'>=' if metric in ('exact_numeric_accuracy', 'answer_schema_valid_rate', 'evidence_coverage', 'proxy_disclosure_rate') else '<='} {want})",
        })

    # --- known-gap governance -------------------------------------------
    allowed = {str(cid) for cid in (allowlist or [])}
    p0_xfailed = sorted(r.case_id for r in results
                        if r.priority == "P0" and r.status == XFAIL)
    unlisted = [cid for cid in p0_xfailed if cid not in allowed]
    if release:
        gates.append({
            "name": "p0_known_gap_allowlist",
            "ok": not unlisted,
            "detail": (f"{len(unlisted)} P0 known gap(s) not in the audited allowlist: "
                       f"{unlisted[:6]}") if unlisted
            else f"all {len(p0_xfailed)} P0 known gaps are allowlisted",
        })
    else:
        gates.append({
            "name": "p0_known_gap_allowlist",
            "ok": True,
            "detail": (f"research run: {len(p0_xfailed)} unresolved P0 known gap(s); "
                       f"{len(unlisted)} not allowlisted (blocking only with --release)"),
        })

    xpassed = sorted(r.case_id for r in results if r.status == XPASS)
    gates.append({
        "name": "known_gap_xpass",
        "ok": not xpassed,
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
            "ok": ok,
            "detail": (f"known_gap={current}/{limit}, p0_known_gap={current_p0}/{limit_p0} "
                       "(the budget may only shrink)"),
        })
    return gates


# ---------------------------------------------------------------------------
# reports
# ---------------------------------------------------------------------------
def _load_known_gap_allowlist(path_arg: str) -> list[str]:
    """Case ids whose unresolved P0 defect is accepted for a release.

    Deliberately a per-case list: there is no way to accept "all known gaps".
    """
    path = Path(path_arg) if path_arg else EVAL_ROOT / "known_gap_allowlist.json"
    if not path.is_file():
        return []
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    if isinstance(payload, dict):
        entries = payload.get("allowed_p0_known_gaps") or []
    else:
        entries = payload or []
    out: list[str] = []
    for entry in entries:
        if isinstance(entry, str):
            out.append(entry)
        elif isinstance(entry, dict) and entry.get("case_id"):
            out.append(str(entry["case_id"]))
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
    release: bool = False,
    allowlist: Optional[list[str]] = None,
    ratchet: Optional[dict] = None,
) -> dict:
    summary = aggregate(results)
    if repeat_agreement is not None:
        summary["metrics"]["repeat_stability"] = repeat_agreement
    gates = evaluate_gates(results, summary["metrics"], release=release,
                           allowlist=allowlist, ratchet=ratchet)

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
        "summary": summary,
        "gates": gates,
        "distributions": {
            "category": dist(lambda r: [r.category]),
            "priority": dist(lambda r: [r.priority]),
            "evaluator": dist(lambda r: [r.evaluator]),
        },
        "known_gaps": [
            {"case_id": r.case_id, "question": r.question, "note": r.gap_note,
             "status": r.status, "priority": r.priority, "meta": r.gap_meta}
            for r in results if r.known_gap
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
    lines.append("| 指标 | 值 | 样本数 |")
    lines.append("| --- | ---: | ---: |")
    for name in ALL_METRICS:
        value = metrics.get(name)
        shown = "未测量" if value is None else f"{value}"
        lines.append(f"| {name} | {shown} | {summary['metric_sample_sizes'].get(name, 0)} |")
    lines.append("")
    lines.append("## 门禁")
    lines.append("")
    lines.append("| 门禁 | 结果 | 说明 |")
    lines.append("| --- | --- | --- |")
    for gate in report["gates"]:
        lines.append(f"| {gate['name']} | {'PASS' if gate['ok'] else 'FAIL'} | {gate['detail']} |")
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
    parser.add_argument("--repeat", type=int, default=1,
                        help="run the selection N times to measure repeat_stability")
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
            print(f"{case['case_id']:<18} {case['priority']:<3} {case['category']:<16} "
                  f"{case['evaluator']:<18} {case['question']}")
        print(f"# {len(selected)} case(s)")
        return 0
    if not selected:
        print(f"no cases matched suite={args.suite}", file=sys.stderr)
        return 2

    ctx = EvalContext(verbose=args.verbose)
    skipped_live = ""
    answers: dict[str, str] = {}
    if args.answers:
        with Path(args.answers).open(encoding="utf-8") as handle:
            answers = json.load(handle)

    try:
        if args.suite == "live" or args.answers:
            ctx.allowed_numbers = collect_allowed_numbers(cases, ctx)
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
                    )
                else:
                    checks, metrics = score_answer(case, answer, ctx.allowed_numbers)
                    result = _result_from(case, checks)
                    result.evaluator = "answers"
                    result.metrics.update(metrics)
                    result.metrics["answer_schema_valid_rate"] = bool(answer)
                    result.evidence = {"answer": answer[:4000]}
                results.append(result)
        elif args.suite == "live":
            load_provider_env()
            if not provider_available(args.provider):
                names = ", ".join(PROVIDER_ENV.get(args.provider, ("(unknown provider)",)))
                skipped_live = (f"provider={args.provider} 未配置凭据（{names}），"
                                f"live 套件跳过；离线套件不受影响")
                results = [
                    CaseResult(
                        case_id=c["case_id"], category=c.get("category", ""),
                        evaluator="live", priority=c.get("priority", "P1"), status=SKIP,
                        question=c.get("question", ""),
                        checks=[Check("live.credentials", False, "provider credentials", "")],
                    )
                    for c in selected
                ]
            else:
                ctx.live_session = build_live_session(ctx)
                results = [run_case(case, ctx, evaluator_override="live") for case in selected]
        else:
            results = [run_case(case, ctx) for case in selected]

        repeat_agreement: Optional[float] = None
        if args.repeat and args.repeat > 1:
            signatures: dict[str, list[str]] = {}
            for result in results:
                sig = json.dumps(
                    [{"name": c.name, "ok": c.ok, "actual": _format(c.actual, 400)}
                     for c in result.checks],
                    ensure_ascii=False, sort_keys=True,
                )
                signatures.setdefault(result.case_id, []).append(sig)
            for _ in range(args.repeat - 1):
                for case in selected:
                    again = run_case(case, ctx)
                    sig = json.dumps(
                        [{"name": c.name, "ok": c.ok, "actual": _format(c.actual, 400)}
                         for c in again.checks],
                        ensure_ascii=False, sort_keys=True,
                    )
                    signatures.setdefault(again.case_id, []).append(sig)
            stable = sum(1 for sigs in signatures.values() if len(set(sigs)) == 1)
            repeat_agreement = round(stable / len(signatures), 6) if signatures else None

        allowlist = _load_known_gap_allowlist(args.allowlist)
        ratchet = _load_known_gap_ratchet(args.ratchet, results)
        report = build_report(results, args.suite, args.provider,
                              skipped_live=skipped_live,
                              repeat_agreement=repeat_agreement,
                              release=args.release, allowlist=allowlist,
                              ratchet=ratchet)

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
        print(f"suite={report['suite']} cases={summary['cases']} "
              f"passed={summary['passed']} failed={summary['failed']} "
              f"pass_rate={summary['pass_rate']}")
        print(f"known_gap={summary['known_gap_cases']} duration_ms={summary['duration_ms']}")
        print(f"p0: total={summary.get('p0_total', 0)} passed={summary.get('p0_passed', 0)} "
              f"failed={summary.get('p0_failed', 0)} xfail={summary.get('p0_xfailed', 0)} "
              f"xpass={summary.get('p0_xpassed', 0)} "
              f"unresolved={summary.get('unresolved_p0_defects', 0)}")
        print("metrics:")
        for name in ALL_METRICS:
            value = summary["metrics"].get(name)
            if value is None:
                continue
            size = summary["metric_sample_sizes"].get(name, 0)
            # ``repeat_stability`` is measured over the whole selection once,
            # not per case, so it has no per-case sample count.
            suffix = f" (n={size})" if name != "repeat_stability" else ""
            print(f"  {name}={value}{suffix}")
        if skipped_live:
            print(f"live: {skipped_live}")
        failed_gates = [g for g in report["gates"] if not g["ok"]]
        for gate in report["gates"]:
            print(f"  gate {gate['name']}: {'PASS' if gate['ok'] else 'FAIL'} — {gate['detail']}")
        print(f"reports: {json_path} , {md_path}")
        for result in results:
            if result.status == FAIL:
                print(f"  FAIL {result.case_id}: " + "; ".join(
                    f"{c.name} expected={_format(c.expected, 80)} actual={_format(c.actual, 80)}"
                    for c in result.failed_checks[:3]
                ))
        if failed_gates and not args.no_gate:
            return 1
        return 0
    finally:
        ctx.cleanup()


if __name__ == "__main__":
    raise SystemExit(main())
