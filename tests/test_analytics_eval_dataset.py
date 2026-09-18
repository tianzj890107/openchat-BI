"""Self-checks for the analytics golden set (``dataset/evals/analytics``).

These tests protect the *evaluation assets themselves*: schema, uniqueness,
fixture integrity, manifest/runner agreement and the read-only safety contract.

They are fully offline and deterministic: no LLM, no network, no Doris, no
remote ontology, and no writes outside the repository's own eval directory.

The JSON Schema in ``dataset/evals/analytics/schemas/case.schema.json`` is the
published contract; ``jsonschema`` is not a project dependency, so the same
invariants are asserted here directly.
"""

from __future__ import annotations

import hashlib
import importlib.util
import json
import re
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
EVAL_ROOT = REPO_ROOT / "dataset" / "evals" / "analytics"
CASES_DIR = EVAL_ROOT / "cases"
FIXTURE_ROOT = EVAL_ROOT / "fixtures"
SQLITE_DIR = FIXTURE_ROOT / "sqlite"
ONTOLOGY_DIR = FIXTURE_ROOT / "ontology"
MANIFEST_PATH = EVAL_ROOT / "manifest.json"
SCHEMA_PATH = EVAL_ROOT / "schemas" / "case.schema.json"

# ``ANA-P0-PROC-001`` (production-chain P0) and ``ANA-ISO-001`` both match.
CASE_ID_RE = re.compile(r"^ANA(-[A-Z0-9]+)+-[0-9]{3}$")
PRIORITIES = {"P0", "P1", "P2"}
SUITES = {"smoke", "regression", "multi-turn", "ontology", "charts",
          "adversarial", "recovery", "diagnosis", "recorded-provider", "live",
          "live-canary"}
DOMAINS = {"采购", "库存", "销售", "财务", "质量", "制造", "通用"}
CATEGORIES = {"intent", "facts", "metrics", "comparison", "trend", "anomaly",
              "diagnosis", "recommendation", "ontology", "multi_turn", "charts",
              "failure_recovery", "adversarial"}

# Fixture databases the golden set is allowed to reference.  The historical
# business databases under ``dataset/databases`` must never be used: they are
# large, contain real data and are not part of the reviewable eval fixture set.
ALLOWED_DBS = {"procurement.db", "inventory.db", "sales.db", "quality.db",
               "finance.db", "manufacturing.db"}

# Evaluators that replay a recorded provider transcript through the production
# turn loop.  Each one needs a transcript fixture and a fixture database.
RECORDED_EVALUATORS = {"recorded_provider", "generated_sql", "tool_chain",
                       "answer_grounding"}
PROVIDER_ROOT = FIXTURE_ROOT / "provider"
RATCHET_PATH = EVAL_ROOT / "known_gap_ratchet.json"
ALLOWLIST_PATH = EVAL_ROOT / "known_gap_allowlist.json"

READONLY_SQL_RE = re.compile(r"^\s*(select|with)\b", re.IGNORECASE)
FORBIDDEN_SQL_RE = re.compile(
    r"\b(insert|update|delete|drop|alter|create|attach|detach|replace|truncate|"
    r"pragma|vacuum|reindex|grant|revoke)\b",
    re.IGNORECASE,
)
# Statement chaining / comments that could smuggle a second statement in.
SQL_CHAIN_RE = re.compile(r";\s*\S|--|/\*")

# Fields every case must carry, mirroring ``required`` in the JSON Schema.
REQUIRED_FIELDS = (
    "case_id", "version", "priority", "suite", "domain", "category",
    "evaluator", "question", "conversation", "context", "fixture",
    "expected", "forbidden", "evidence_requirements", "tags",
)


def _load(path: Path) -> dict:
    with path.open(encoding="utf-8") as handle:
        return json.load(handle)


def _all_case_paths() -> list[Path]:
    return sorted(CASES_DIR.glob("*/*.json"))


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 16), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _load_runner():
    """Import ``scripts/run_analytics_eval.py`` without executing ``main``."""
    spec = importlib.util.spec_from_file_location(
        "analytics_eval_runner", REPO_ROOT / "scripts" / "run_analytics_eval.py"
    )
    module = importlib.util.module_from_spec(spec)
    import sys

    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


class GoldenSetLayoutTest(unittest.TestCase):
    def test_eval_tree_exists(self):
        for path in (CASES_DIR, FIXTURE_ROOT, SQLITE_DIR, ONTOLOGY_DIR,
                     MANIFEST_PATH, SCHEMA_PATH, EVAL_ROOT / "README.md"):
            self.assertTrue(path.exists(), f"missing eval asset: {path}")

    def test_expected_fixture_databases(self):
        present = {p.name for p in SQLITE_DIR.glob("*.db")}
        self.assertEqual(present, ALLOWED_DBS)

    def test_ontology_fixture_present(self):
        self.assertTrue((ONTOLOGY_DIR / "analytics_golden_ontology.xlsx").is_file())


class CaseSchemaTest(unittest.TestCase):
    def setUp(self):
        self.paths = _all_case_paths()
        self.cases = [(p, _load(p)) for p in self.paths]

    def test_cases_exist(self):
        self.assertGreaterEqual(len(self.paths), 270)

    def test_required_fields_present(self):
        for path, case in self.cases:
            for field in REQUIRED_FIELDS:
                self.assertIn(field, case, f"{path} missing {field}")

    def test_case_id_format_and_filename(self):
        for path, case in self.cases:
            cid = case["case_id"]
            self.assertRegex(cid, CASE_ID_RE, str(path))
            self.assertEqual(path.stem, cid, f"{path} filename != case_id")
            self.assertEqual(path.parent.name, case["category"],
                             f"{path} not in its category directory")

    def test_priority_suite_domain_category_and_question(self):
        for path, case in self.cases:
            self.assertIn(case["priority"], PRIORITIES, str(path))
            self.assertTrue(case["suite"], f"{path} has no suite")
            self.assertTrue(set(case["suite"]) <= SUITES, f"{path} bad suite")
            self.assertIn(case["domain"], DOMAINS, str(path))
            self.assertIn(case["category"], CATEGORIES, str(path))
            self.assertIsInstance(case["question"], str)
            self.assertTrue(case["question"].strip(), f"{path} empty question")
            self.assertIsInstance(case["version"], int)
            self.assertGreaterEqual(case["version"], 1)

    def test_known_gap_requires_note(self):
        for path, case in self.cases:
            if case.get("known_gap"):
                self.assertTrue(case.get("gap_note", "").strip(),
                                f"{path} known_gap without gap_note")
                self.assertIn(case["priority"], PRIORITIES)

    def test_known_gap_requires_full_metadata(self):
        """A Red test without an owner and a target is just debt with no owner."""
        required = {"owner", "introduced_at", "target_fix_version", "severity",
                    "source_issue"}
        seen = 0
        for path, case in self.cases:
            if not case.get("known_gap"):
                continue
            seen += 1
            meta = case.get("gap_meta") or {}
            self.assertEqual(required - set(meta), set(),
                             f"{path} known_gap is missing metadata")
            self.assertRegex(meta["introduced_at"], r"^\d{4}-\d{2}-\d{2}$")
            self.assertRegex(meta["target_fix_version"], r"^v\d+\.\d+\.\d+$")
            self.assertIn(meta["severity"], {"low", "medium", "high"})
            self.assertTrue(str(meta["owner"]).strip())
            self.assertTrue(str(meta["source_issue"]).strip())
        self.assertGreater(seen, 0)

    def test_no_unknown_top_level_fields(self):
        schema = _load(SCHEMA_PATH)
        allowed = set(schema["properties"])
        for path, case in self.cases:
            unknown = sorted(set(case) - allowed)
            self.assertEqual(unknown, [], f"{path} has unknown fields {unknown}")

    def test_no_duplicate_question_evaluator_expected(self):
        """A case that only renames its id is padding, not coverage."""
        legacy = {
            frozenset({"ANA-INTENT-041", "ANA-DIAG-002"}),
            frozenset({"ANA-INTENT-042", "ANA-DIAG-003"}),
            frozenset({"ANA-INTENT-043", "ANA-DIAG-004"}),
            frozenset({"ANA-INTENT-051", "ANA-REC-002"}),
        }
        seen: dict[tuple, str] = {}
        unexplained = []
        for path, case in self.cases:
            key = (case["question"], case["evaluator"],
                   json.dumps(case["expected"], ensure_ascii=False, sort_keys=True))
            if key in seen and frozenset({seen[key], case["case_id"]}) not in legacy:
                unexplained.append((seen[key], case["case_id"]))
            seen[key] = case["case_id"]
        self.assertEqual(unexplained, [], "duplicate question+evaluator+expected")
        self.assertEqual(len(legacy), 4, "the legacy duplicate allowlist is frozen")

    def test_case_ids_are_unique(self):
        seen: dict[str, str] = {}
        for path, case in self.cases:
            cid = case["case_id"]
            self.assertNotIn(cid, seen, f"duplicate case_id {cid}: {path} / {seen.get(cid)}")
            seen[cid] = str(path)

    def test_no_secrets_or_absolute_paths_in_cases(self):
        secret_re = re.compile(r"sk-[A-Za-z0-9._\-]{12,}|BEGIN [A-Z ]*PRIVATE KEY")
        for path, case in self.cases:
            blob = json.dumps(case, ensure_ascii=False)
            self.assertIsNone(secret_re.search(blob), f"{path} looks like it embeds a secret")
            self.assertNotIn("/Users/", blob, f"{path} embeds an absolute local path")


class CaseFixtureTest(unittest.TestCase):
    def setUp(self):
        self.cases = [(p, _load(p)) for p in _all_case_paths()]

    def test_sql_guard_cases_keep_their_dangerous_sql(self):
        """``sql_guard`` cases exist to be *rejected*; only the shape is checked.

        They must not carry a database, so a guard case can never be mistaken
        for an executable reference query.
        """
        checked = 0
        for path, case in self.cases:
            if case["evaluator"] != "sql_guard":
                continue
            checked += 1
            fixture = case["fixture"]
            sql = fixture.get("sql")
            self.assertIsInstance(sql, str, f"{path} sql must be a string")
            if not sql.strip():
                # Only the "empty SQL must be rejected" case may be empty.
                self.assertIn("empty", str(case["expected"].get("error_contains", "")).lower(),
                              f"{path} has an empty sql without an empty-SQL expectation")
            self.assertFalse(fixture.get("db"),
                             f"{path} sql_guard case must not name a database")
        self.assertGreater(checked, 0)

    def test_sql_fixtures_reference_allowed_readonly_databases(self):
        checked = 0
        for path, case in self.cases:
            if case["evaluator"] != "sql":
                continue
            fixture = case.get("fixture") or {}
            checked += 1
            db = fixture.get("db", "")
            self.assertIn(db, ALLOWED_DBS,
                          f"{path} references a non-eval database: {db!r}")
            self.assertTrue((SQLITE_DIR / db).is_file(), f"{path} db missing: {db}")
            sql = fixture.get("sql", "")
            self.assertIsInstance(sql, str)
            self.assertTrue(sql.strip(), f"{path} has an empty sql")
            self.assertRegex(sql, READONLY_SQL_RE, f"{path} sql is not a SELECT/WITH")
            self.assertIsNone(FORBIDDEN_SQL_RE.search(sql),
                              f"{path} sql contains a write/DDL keyword")
            self.assertIsNone(SQL_CHAIN_RE.search(sql),
                              f"{path} sql contains a statement chain or comment")
        self.assertGreater(checked, 50)

    def test_sql_cases_declare_a_query_contract(self):
        for path, case in self.cases:
            if case["evaluator"] != "sql":
                continue
            contract = (case["expected"] or {}).get("query_contract")
            self.assertIsInstance(contract, dict, f"{path} missing query_contract")
            self.assertTrue(contract.get("db"), f"{path} contract has no db")

    def test_ontology_fixtures_exist(self):
        for path, case in self.cases:
            name = (case.get("fixture") or {}).get("ontology")
            if not name:
                continue
            self.assertTrue((ONTOLOGY_DIR / name).is_file(),
                            f"{path} ontology fixture missing: {name}")

    def test_multi_turn_cases_carry_both_question_forms(self):
        checked = 0
        for path, case in self.cases:
            if case["evaluator"] != "multi_turn":
                continue
            checked += 1
            fixture = case["fixture"]
            for key in ("effective_question", "follow_up_question",
                        "previous_contract", "resolved_contract", "resolution"):
                self.assertIn(key, fixture, f"{path} missing fixture.{key}")
            self.assertNotEqual(fixture["effective_question"],
                                fixture["follow_up_question"],
                                f"{path} follow-up was never resolved")
        self.assertGreater(checked, 0)

    def test_evaluator_is_known_to_the_runner(self):
        runner = _load_runner()
        for path, case in self.cases:
            self.assertIn(case["evaluator"], runner.EVALUATORS,
                          f"{path} uses an evaluator the runner cannot dispatch")

    def test_manifest_case_sets_match_runner_selection(self):
        """Manifest suite counts must equal what the runner actually selects."""
        runner = _load_runner()
        manifest = _load(MANIFEST_PATH)
        cases = runner.load_cases()
        for suite, expected in manifest["totals"]["by_suite"].items():
            actual = len(runner.select_cases(cases, suite))
            self.assertEqual(actual, expected,
                             f"manifest by_suite[{suite}]={expected} but runner selects {actual}")


class ManifestTest(unittest.TestCase):
    def setUp(self):
        self.manifest = _load(MANIFEST_PATH)
        self.cases = [(_load(p)) for p in _all_case_paths()]

    def test_manifest_matches_case_files(self):
        totals = self.manifest["totals"]
        self.assertEqual(totals["cases"], len(self.cases))
        by_category: dict[str, int] = {}
        by_evaluator: dict[str, int] = {}
        by_domain: dict[str, int] = {}
        by_priority: dict[str, int] = {}
        for case in self.cases:
            by_category[case["category"]] = by_category.get(case["category"], 0) + 1
            by_evaluator[case["evaluator"]] = by_evaluator.get(case["evaluator"], 0) + 1
            by_domain[case["domain"]] = by_domain.get(case["domain"], 0) + 1
            by_priority[case["priority"]] = by_priority.get(case["priority"], 0) + 1
        self.assertEqual(totals["by_category"], dict(sorted(by_category.items())))
        self.assertEqual(totals["by_evaluator"], dict(sorted(by_evaluator.items())))
        self.assertEqual(totals["by_domain"], dict(sorted(by_domain.items())))
        self.assertEqual(totals["by_priority"], dict(sorted(by_priority.items())))

    def test_manifest_known_gaps_match_case_flags(self):
        flagged = sorted(c["case_id"] for c in self.cases if c.get("known_gap"))
        listed = sorted(g["case_id"] for g in self.manifest["known_gaps"])
        self.assertEqual(flagged, listed)
        self.assertEqual(self.manifest["totals"]["known_gap"], len(flagged))

    def test_manifest_fixture_hashes_are_current(self):
        for rel, meta in self.manifest["fixtures"].items():
            path = FIXTURE_ROOT / rel
            self.assertTrue(path.is_file(), f"manifest lists missing fixture {rel}")
            self.assertEqual(meta["sha256"], _sha256(path),
                             f"fixture {rel} changed; regenerate the manifest")
            self.assertEqual(meta["bytes"], path.stat().st_size)

    def test_manifest_declares_every_suite_and_category(self):
        self.assertEqual(set(self.manifest["suites"]), SUITES)
        self.assertEqual(set(self.manifest["categories"]), CATEGORIES)


class CoverageFloorTest(unittest.TestCase):
    """Ratchet floors: they may only move up when coverage grows."""

    def setUp(self):
        self.cases = [_load(p) for p in _all_case_paths()]

    def test_priority_and_known_gap_floors(self):
        p0 = sum(1 for c in self.cases if c["priority"] == "P0")
        gaps = sum(1 for c in self.cases if c.get("known_gap"))
        self.assertGreaterEqual(p0, 100, "too few P0 contract cases")
        self.assertGreaterEqual(gaps, 1, "known_gap must document open defects")
        self.assertLess(gaps, len(self.cases) // 10, "too much of the set is Red")

    def test_every_category_has_cases(self):
        present = {c["category"] for c in self.cases}
        self.assertEqual(present, CATEGORIES)

    def test_required_domains_are_covered(self):
        present = {c["domain"] for c in self.cases}
        for domain in ("采购", "库存", "销售", "质量"):
            self.assertIn(domain, present, f"domain {domain} has no cases")

    def test_smoke_cases_are_all_p0(self):
        smoke = [c for c in self.cases if "smoke" in c["suite"]]
        self.assertTrue(smoke)
        for case in smoke:
            self.assertEqual(case["priority"], "P0",
                             f"{case['case_id']} is in smoke but not P0")

    def test_exact_and_structural_assertions_both_present(self):
        evaluators = {c["evaluator"] for c in self.cases}
        # numeric / structural coverage
        self.assertIn("sql", evaluators)
        self.assertIn("policy", evaluators)
        # safety / isolation coverage
        self.assertIn("sql_guard", evaluators)
        self.assertIn("session_isolation", evaluators)
        self.assertIn("admission", evaluators)
        self.assertIn("chart_html_safety", evaluators)

    def test_finance_and_manufacturing_domains_are_covered(self):
        finance = [c for c in self.cases if c["domain"] == "财务"]
        manufacturing = [c for c in self.cases if c["domain"] == "制造"]
        self.assertGreaterEqual(len(finance), 25, "财务 needs >=25 numeric cases")
        self.assertGreaterEqual(len(manufacturing), 25, "制造 needs >=25 numeric cases")

    def test_recorded_provider_cases_cover_the_required_ratio(self):
        recorded = [c for c in self.cases
                    if "recorded-provider" in c["suite"]]
        self.assertGreaterEqual(len(recorded), 60,
                                "the recorded-provider layer must have >=60 cases")
        self.assertGreaterEqual(
            len([c for c in recorded if c["evaluator"] == "generated_sql"]), 25)
        self.assertGreaterEqual(
            len([c for c in recorded if c["evaluator"] == "tool_chain"]), 12)
        # Chart-chain cases are the ones recorded under fixtures/provider/chart/;
        # a couple of them are categorised as adversarial/failure_recovery on
        # purpose, so the count must not be by category.
        chart_chain = [c for c in recorded
                       if "provider/chart/" in str((c.get("fixture") or {}).get("provider"))]
        self.assertGreaterEqual(len(chart_chain), 15,
                                ">=15 end-to-end chart-chain cases expected")

    def test_p2_long_tail_has_real_assertions(self):
        p2 = [c for c in self.cases if c["priority"] == "P2"]
        self.assertGreaterEqual(len(p2), 25, ">=25 P2 long-tail cases expected")
        keys = ("value", "tool_chain", "context", "policy", "rule_codes", "stats",
                "rows", "value_is_null", "chart_type", "mode_in", "mode_not_in",
                "status", "error_contains", "allowed_tables", "final_text_contains",
                "op", "code")
        for case in p2:
            expected = case["expected"]
            self.assertTrue(expected, f"{case['case_id']} has no expected payload")
            # Presence, not truthiness: a golden value of 0 is still an assertion.
            self.assertTrue(
                any(key in expected for key in keys),
                f"{case['case_id']} P2 case asserts nothing concrete",
            )

    def test_no_live_evaluator_cases_are_committed(self):
        """``live`` is applied at run time; the stored cases stay structural."""
        for case in self.cases:
            self.assertNotEqual(case["evaluator"], "live",
                                f"{case['case_id']} stores a live evaluator")


class RecordedProviderAssetTest(unittest.TestCase):
    """The replay layer must stay self-contained, offline and deterministic."""

    def setUp(self):
        self.cases = [_load(p) for p in _all_case_paths()]
        self.manifest = _load(MANIFEST_PATH)

    def test_every_recorded_case_has_a_committed_transcript(self):
        checked = 0
        for case in self.cases:
            if case["evaluator"] not in RECORDED_EVALUATORS:
                continue
            checked += 1
            rel = (case.get("fixture") or {}).get("provider")
            self.assertTrue(rel, f"{case['case_id']} has no provider transcript")
            path = EVAL_ROOT / rel
            self.assertTrue(path.is_file(), f"{case['case_id']} transcript missing: {rel}")
            payload = _load(path)
            self.assertEqual(payload.get("version"), 1, rel)
            self.assertEqual(payload.get("provider"), "recorded", rel)
            self.assertEqual(payload.get("case_id"), case["case_id"], rel)
            self.assertTrue(payload.get("turns"), f"{rel} has no turns")
            for turn in payload["turns"]:
                self.assertTrue(turn.get("user"), f"{rel} turn without a question")
                self.assertTrue(turn.get("events"), f"{rel} turn without events")
                self.assertEqual(turn["events"][-1]["type"], "done",
                                 f"{rel} turn must end with done")
        self.assertGreaterEqual(checked, 60)

    def test_transcripts_are_hashed_in_the_manifest(self):
        hashed = [rel for rel in self.manifest["fixtures"] if rel.startswith("provider/")]
        self.assertGreaterEqual(len(hashed), 60)
        for rel in hashed:
            self.assertEqual(self.manifest["fixtures"][rel]["sha256"],
                             _sha256(FIXTURE_ROOT / rel))

    def test_recorded_cases_only_use_eval_fixture_databases(self):
        for case in self.cases:
            if case["evaluator"] not in RECORDED_EVALUATORS:
                continue
            db = (case.get("fixture") or {}).get("db")
            self.assertIn(db, ALLOWED_DBS, f"{case['case_id']} uses {db!r}")

    def test_recorded_cases_are_wired_into_the_default_regression(self):
        for case in self.cases:
            if "recorded-provider" not in case["suite"]:
                continue
            self.assertIn("regression", case["suite"],
                          f"{case['case_id']} is not part of the default regression")

    def test_no_network_is_reachable_during_replay(self):
        """Replay a recorded case with sockets disabled: it must still pass."""
        import socket

        runner = _load_runner()
        case = next(c for c in self.cases if c["case_id"] == "ANA-RPSQL-001")
        ctx = runner.EvalContext()
        real_socket = socket.socket

        def _blocked(*args, **kwargs):  # pragma: no cover - failure path only
            raise AssertionError("the offline evaluator must not open a socket")

        try:
            socket.socket = _blocked
            socket.create_connection = _blocked
            result = runner.run_case(case, ctx)
        finally:
            socket.socket = real_socket
            ctx.cleanup()
        self.assertEqual(result.status, runner.PASS,
                         [c.name for c in result.failed_checks])

    def test_grounding_negative_control_is_declared(self):
        """A number that another case produced must still count as unsupported."""
        case = next(c for c in self.cases if c["case_id"] == "ANA-RPGND-002")
        self.assertTrue(case["expected"].get("unsupported_numbers"))
        self.assertFalse(case["expected"].get("grounding", True))

        runner = _load_runner()
        ctx = runner.EvalContext()
        try:
            result = runner.run_case(case, ctx)
        finally:
            ctx.cleanup()
        self.assertEqual(result.status, runner.PASS,
                         [c.name for c in result.failed_checks])


class KnownGapGovernanceTest(unittest.TestCase):
    def setUp(self):
        self.manifest = _load(MANIFEST_PATH)
        self.cases = [_load(p) for p in _all_case_paths()]

    def test_ratchet_matches_the_committed_set(self):
        ratchet = _load(RATCHET_PATH)
        total = sum(1 for c in self.cases if c.get("known_gap"))
        p0 = sum(1 for c in self.cases if c.get("known_gap") and c["priority"] == "P0")
        self.assertEqual(ratchet["known_gap_total"], total,
                         "known-gap budget drifted from the committed set")
        self.assertEqual(ratchet["p0_known_gap"], p0)

    def test_allowlist_is_empty_and_case_scoped(self):
        allowlist = _load(ALLOWLIST_PATH)
        self.assertEqual(allowlist["allowed_p0_known_gaps"], [],
                         "an allowlist entry needs an audited justification first")
        self.assertNotIn("ignore_all", json.dumps(allowlist))

    def test_unresolved_p0_defects_are_reported(self):
        runner = _load_runner()
        cases = runner.load_cases()
        results = []
        ctx = runner.EvalContext()
        try:
            for case in runner.select_cases(cases, "smoke"):
                results.append(runner.run_case(case, ctx))
        finally:
            ctx.cleanup()
        summary = runner.aggregate(results)
        self.assertEqual(summary["p0_total"],
                         sum(1 for r in results if r.priority == "P0"))
        self.assertEqual(summary["unresolved_p0_defects"], summary["p0_xfailed"])
        self.assertGreater(summary["p0_total"], summary["p0_passed"],
                           "the P0 report must not collapse known gaps into passes")


class KnownGapGateTest(unittest.TestCase):
    """The release gate must fail on unresolved P0 defects, offline and fast."""

    def _run(self, extra: list[str]) -> tuple[int, dict]:
        import os
        import subprocess
        import sys
        import tempfile

        with tempfile.TemporaryDirectory() as tmp:
            env = dict(os.environ)
            for key in ("TEAM_API_KEY", "QWEN_API_KEY", "DASHSCOPE_API_KEY",
                        "TEAM_BASE_URL"):
                env.pop(key, None)
            proc = subprocess.run(
                [sys.executable, "-m", "scripts.run_analytics_eval",
                 "--suite", "smoke", "--out", tmp, *extra],
                cwd=REPO_ROOT, capture_output=True, text=True, env=env,
                timeout=900,
            )
            report_path = Path(tmp) / "report-smoke.json"
            report = _load(report_path) if report_path.is_file() else {}
            return proc.returncode, report

    def test_research_run_does_not_block_on_open_defects(self):
        code, report = self._run([])
        self.assertEqual(code, 0)
        gate = next(g for g in report["gates"] if g["name"] == "p0_known_gap_allowlist")
        self.assertTrue(gate["ok"])
        self.assertIn("research run", gate["detail"])

    def test_release_run_fails_while_p0_defects_are_open(self):
        code, report = self._run(["--release"])
        self.assertEqual(code, 1, "release must fail with unresolved P0 known gaps")
        gate = next(g for g in report["gates"] if g["name"] == "p0_known_gap_allowlist")
        self.assertFalse(gate["ok"])
        self.assertIn("not in the audited allowlist", gate["detail"])


class GovernanceGateTest(unittest.TestCase):
    """The release gate must be impossible to widen or forget.

    These run the *shipped* gate code with synthetic results, so they stay fast
    and offline while still pinning the behaviour a release depends on:
    waivers need audit metadata, waivers expire, security defects are their own
    gate, and the ratchet only moves down.
    """

    CURRENT_GAP = "ANA-INTENT-052"
    SECURITY_GAP = "ANA-ADV-010"

    def setUp(self):
        self.runner = _load_runner()

    def _result(self, case_id: str, status: str, *, priority: str = "P0",
                known_gap: bool = False, gap_meta: dict | None = None):
        return self.runner.CaseResult(
            case_id=case_id, category="adversarial", evaluator="policy",
            priority=priority, status=status, known_gap=known_gap,
            gap_meta=dict(gap_meta or {}), question="synthetic result")

    def _xfail_result(self, case_id: str, *, priority: str = "P0", meta: dict | None = None):
        return self._result(case_id, self.runner.XFAIL, priority=priority,
                            known_gap=True, gap_meta=meta or {})

    def _gate(self, gates: list[dict], name: str) -> dict:
        for gate in gates:
            if gate["name"] == name:
                return gate
        raise AssertionError(f"missing gate {name}; got {[g['name'] for g in gates]}")

    def _gates(self, results, *, release: bool = False, allowlist=None,
               ratchet=None, waivers=None):
        return self.runner.evaluate_gates(
            results, {}, release=release, allowlist=allowlist,
            ratchet=ratchet, waivers=waivers)

    # --- waiver hygiene --------------------------------------------------

    def test_a_waiver_without_audit_metadata_fails(self):
        gates = self._gates([], waivers={"entries": [{"case_id": self.CURRENT_GAP}]})
        gate = self._gate(gates, "known_gap_waiver_metadata")
        self.assertEqual(gate["status"], "FAIL")
        self.assertFalse(gate["ok"])
        for field in ("reviewer", "reviewed_at", "reason", "expiry",
                      "target_fix_version"):
            self.assertIn(field, gate["detail"])

    def test_an_expired_waiver_fails(self):
        entry = {
            "case_id": self.CURRENT_GAP, "reviewer": "tianzijing",
            "reviewed_at": "2026-09-01", "reason": "tracked in v0.1.10",
            "expiry": "2001-01-01", "target_fix_version": "v0.1.10",
        }
        gates = self._gates([], waivers={"entries": [entry]})
        gate = self._gate(gates, "known_gap_waiver_expiry")
        self.assertEqual(gate["status"], "FAIL")
        self.assertIn(self.CURRENT_GAP, gate["detail"])

    def test_an_unparseable_expiry_is_treated_as_expired(self):
        entry = {
            "case_id": self.CURRENT_GAP, "reviewer": "tianzijing",
            "reviewed_at": "2026-09-01", "reason": "tracked in v0.1.10",
            "expiry": "someday", "target_fix_version": "v0.1.10",
        }
        gates = self._gates([], waivers={"entries": [entry]})
        self.assertEqual(self._gate(gates, "known_gap_waiver_expiry")["status"], "FAIL")

    def test_a_fully_audited_unexpired_waiver_passes(self):
        entry = {
            "case_id": self.CURRENT_GAP, "reviewer": "tianzijing",
            "reviewed_at": "2026-09-17", "reason": "fix scheduled for v0.1.10",
            "expiry": "2099-12-31", "target_fix_version": "v0.1.10",
        }
        results = [self._xfail_result(self.CURRENT_GAP)]
        gates = self._gates(results, release=True,
                            allowlist=[self.CURRENT_GAP],
                            waivers={"entries": [entry]})
        self.assertEqual(self._gate(gates, "known_gap_waiver_expiry")["status"], "PASS")
        self.assertEqual(self._gate(gates, "p0_known_gap_allowlist")["status"], "PASS")

    def test_wildcard_entries_never_widen_the_allowlist(self):
        import tempfile

        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "allowlist.json"
            path.write_text(json.dumps({
                "allowed_p0_known_gaps": [
                    {"case_id": "*"}, {"case_id": "ignore_all"},
                    {"case_id": "ALL"}, {"case_id": "any"},
                    {"case_id": self.CURRENT_GAP},
                ],
            }), encoding="utf-8")
            honoured = self.runner._load_known_gap_allowlist(str(path))
        self.assertEqual(honoured, [self.CURRENT_GAP],
                         "a wildcard must never widen a waiver")

    def test_the_committed_allowlist_carries_audit_metadata_or_is_empty(self):
        allowlist = _load(ALLOWLIST_PATH)
        entries = allowlist.get("allowed_p0_known_gaps") or []
        for entry in entries:
            if isinstance(entry, str):
                self.fail("allowlist entries must be audited objects, not bare case ids")
            for field in ("case_id", "reviewer", "reviewed_at", "reason",
                          "expiry", "target_fix_version"):
                self.assertIn(field, entry)

    # --- defect ledgers --------------------------------------------------

    def test_an_unresolved_security_defect_is_its_own_gate(self):
        results = [self._xfail_result(self.SECURITY_GAP, priority="P1",
                                      meta={"severity": "high"})]
        gate = self._gate(self._gates(results), "unresolved_security_defects")
        self.assertEqual(gate["status"], "FAIL")
        self.assertIn(self.SECURITY_GAP, gate["detail"])

    def test_security_defects_block_a_release_but_not_research_iteration(self):
        results = [self._xfail_result(self.SECURITY_GAP, priority="P1",
                                      meta={"severity": "high"})]
        research = self.runner.build_report(
            results, "smoke", "provider", release=False)
        blocked = self.runner.build_report(
            results, "smoke", "provider", release=True)
        self.assertNotEqual(research["status"], "fail",
                            "research iteration must stay actionable")
        self.assertEqual(blocked["status"], "fail")
        self.assertFalse(
            self._gate(blocked["gates"], "unresolved_security_defects")["ok"])

    def test_a_known_gap_past_its_target_version_is_overdue(self):
        version = self.runner.product_version()
        reached = self.runner._version_reached
        self.assertEqual(version, "0.1.9")
        self.assertTrue(reached(version, "v0.0.1"))
        self.assertTrue(reached(version, "v0.1.9"))
        self.assertFalse(reached(version, "v0.1.10"))
        self.assertFalse(reached(version, "v99.0.0"))
        self.assertFalse(reached(version, ""))

    def test_the_overdue_gate_uses_the_product_version(self):
        overdue = self._xfail_result(self.CURRENT_GAP,
                                     meta={"target_fix_version": "v0.0.1"})
        gate = self._gate(self._gates([overdue]), "known_gap_overdue")
        self.assertEqual(gate["status"], "FAIL")
        self.assertIn(self.CURRENT_GAP, gate["detail"])

    def test_the_ratchet_only_moves_down(self):
        results = [self._xfail_result(self.CURRENT_GAP)]
        loose = self._gates(results, ratchet={"known_gap_total": 12, "p0_known_gap": 6})
        tight = self._gates(results, ratchet={"known_gap_total": 0, "p0_known_gap": 0})
        self.assertEqual(self._gate(loose, "known_gap_ratchet")["status"], "PASS")
        self.assertEqual(self._gate(tight, "known_gap_ratchet")["status"], "FAIL")

    def test_an_xpass_is_a_maintenance_failure(self):
        xpass = self._result(self.CURRENT_GAP, self.runner.XPASS, known_gap=True)
        gate = self._gate(self._gates([xpass]), "known_gap_xpass")
        self.assertEqual(gate["status"], "FAIL")
        self.assertIn(self.CURRENT_GAP, gate["detail"])


class RunnerContractTest(unittest.TestCase):
    """Subprocess contract: what CI calls, with the side effects we forbid."""

    def test_smoke_suite_writes_only_to_the_requested_directory(self):
        import os
        import subprocess
        import sys
        import tempfile

        reports_dir = REPO_ROOT / "reports"
        before = sorted(str(p) for p in reports_dir.rglob("*")) if reports_dir.is_dir() else []
        with tempfile.TemporaryDirectory() as tmp:
            env = dict(os.environ)
            for key in ("TEAM_API_KEY", "QWEN_API_KEY", "DASHSCOPE_API_KEY"):
                env.pop(key, None)
            proc = subprocess.run(
                [sys.executable, "-m", "scripts.run_analytics_eval",
                 "--suite", "smoke", "--out", tmp],
                cwd=REPO_ROOT, capture_output=True, text=True, env=env, timeout=900,
            )
            self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
            report = _load(Path(tmp) / "report-smoke.json")
            manifest = _load(MANIFEST_PATH)

            self.assertEqual(report["summary"]["cases"] + len(report["known_gaps"]),
                             manifest["totals"]["by_suite"]["smoke"])
            self.assertEqual(len(report["known_gaps"]), manifest["totals"]["known_gap_p0"])
            manifest = _load(MANIFEST_PATH)
            smoke_ids = {c["case_id"] for c in
                         (_load(p) for p in _all_case_paths())
                         if "smoke" in c["suite"]}
            self.assertEqual({r["case_id"] for r in report["results"]}, smoke_ids,
                             "the report must cover every smoke case, known gaps included")
            self.assertTrue((Path(tmp) / "report-smoke.md").is_file())
        after = sorted(str(p) for p in reports_dir.rglob("*")) if reports_dir.is_dir() else []
        self.assertEqual(before, after, "the runner wrote into the repo reports/ directory")

    def test_regression_suite_is_reproducible(self):
        import os
        import subprocess
        import sys
        import tempfile

        with tempfile.TemporaryDirectory() as tmp:
            env = dict(os.environ)
            for key in ("TEAM_API_KEY", "QWEN_API_KEY", "DASHSCOPE_API_KEY"):
                env.pop(key, None)
            outputs = []
            for run in ("a", "b"):
                out = Path(tmp) / run
                proc = subprocess.run(
                    [sys.executable, "-m", "scripts.run_analytics_eval",
                     "--suite", "recorded-provider", "--out", str(out)],
                    cwd=REPO_ROOT, capture_output=True, text=True, env=env, timeout=900,
                )
                self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
                report = _load(out / "report-recorded-provider.json")
                outputs.append([
                    (r["case_id"], r["status"],
                     tuple(c["name"] for c in r["checks"] if not c["ok"]))
                    for r in report["results"]
                ])
            self.assertEqual(outputs[0], outputs[1],
                             "the recorded-provider suite is not deterministic")


class GeneratorReproducibilityTest(unittest.TestCase):
    """Regenerating the assets must reproduce the committed bytes."""

    def test_regeneration_is_byte_identical(self):
        import shutil
        import subprocess
        import sys
        import tempfile

        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "analytics"
            shutil.copytree(
                EVAL_ROOT, target,
                ignore=shutil.ignore_patterns("cases", "__pycache__", "*.pyc"),
            )
            proc = subprocess.run(
                [sys.executable, str(target / "build_cases.py")],
                cwd=str(target), capture_output=True, text=True, timeout=900,
            )
            self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)

            committed = {p.relative_to(CASES_DIR): p.read_bytes()
                         for p in CASES_DIR.glob("*/*.json")}
            regenerated = {p.relative_to(target / "cases"): p.read_bytes()
                           for p in (target / "cases").glob("*/*.json")}
            self.assertEqual(sorted(committed), sorted(regenerated),
                             "regeneration produced a different case set")
            differing = [str(rel) for rel, blob in committed.items()
                         if regenerated[rel] != blob]
            self.assertEqual(differing, [], "regeneration changed committed cases")
            self.assertEqual((target / "manifest.json").read_bytes(),
                             MANIFEST_PATH.read_bytes(),
                             "regeneration changed the manifest")


if __name__ == "__main__":
    unittest.main()
