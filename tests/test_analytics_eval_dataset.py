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

CASE_ID_RE = re.compile(r"^ANA-[A-Z0-9]+-[0-9]{3}$")
PRIORITIES = {"P0", "P1", "P2"}
SUITES = {"smoke", "regression", "multi-turn", "ontology", "charts",
          "adversarial", "recovery", "diagnosis", "live"}
DOMAINS = {"采购", "库存", "销售", "财务", "质量", "制造", "通用"}
CATEGORIES = {"intent", "facts", "metrics", "comparison", "trend", "anomaly",
              "diagnosis", "recommendation", "ontology", "multi_turn", "charts",
              "failure_recovery", "adversarial"}

# Fixture databases the golden set is allowed to reference.  The historical
# business databases under ``dataset/databases`` must never be used: they are
# large, contain real data and are not part of the reviewable eval fixture set.
ALLOWED_DBS = {"procurement.db", "inventory.db", "sales.db", "quality.db"}

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

    def test_no_live_evaluator_cases_are_committed(self):
        """``live`` is applied at run time; the stored cases stay structural."""
        for case in self.cases:
            self.assertNotEqual(case["evaluator"], "live",
                                f"{case['case_id']} stores a live evaluator")


if __name__ == "__main__":
    unittest.main()
