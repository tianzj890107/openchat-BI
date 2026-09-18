"""Contracts that stop the analytics release gate from being softened.

The release gate is only real if the CI job that carries it cannot quietly
become non-blocking, if ``--release`` cannot be dropped, if a tag pipeline
cannot skip the gate, and if the known-gap allowlist cannot be widened into
"ignore everything".  Every check below is written as a pure
``... -> violations`` function so the same function proves both directions:
the current file is clean, and a mutated file is caught.
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import re
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
CI_PATH = REPO_ROOT / ".gitlab-ci.yml"
RUNNER_PATH = REPO_ROOT / "scripts" / "run_analytics_eval.py"
EVAL_ROOT = REPO_ROOT / "dataset" / "evals" / "analytics"

RELEASE_JOB = "analytics-eval-release-gate"
BLOCKING_JOBS = (
    "analytics-eval-smoke",
    "analytics-eval-regression",
    "analytics-eval-recorded-provider",
)


def _load_runner():
    name = "analytics_eval_runner_release_ci"
    spec = importlib.util.spec_from_file_location(name, RUNNER_PATH)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


RUNNER = _load_runner()

_SKIP_CATEGORIES = (
    "missing_frontend_dependency",
    "missing_external_service",
    "redis",
    "live_credentials",
    "platform_unsupported",
    "explicit_integration",
    "other",
)


def job_block(text: str, job: str):
    """Return the YAML block of ``job`` (top-level key) or ``None``."""
    lines = text.splitlines()
    start = None
    for index, line in enumerate(lines):
        if line.rstrip() == f"{job}:":
            start = index
            break
    if start is None:
        return None
    block = [lines[start]]
    for line in lines[start + 1:]:
        if line.strip() and not line.startswith((" ", "\t")):
            break
        block.append(line)
    return "\n".join(block)


def job_rules(block: str):
    """Parse the ``rules:`` list of a job block into dicts of scalars."""
    lines = block.splitlines()
    start = None
    for index, line in enumerate(lines):
        if line.strip() == "rules:":
            start = index
            break
    if start is None:
        return []
    indent = len(lines[start]) - len(lines[start].lstrip())
    rules: list[dict] = []
    current: dict | None = None
    for line in lines[start + 1:]:
        if not line.strip():
            continue
        line_indent = len(line) - len(line.lstrip())
        if line_indent <= indent:
            break
        stripped = line.strip()
        if stripped.startswith("- "):
            current = {}
            rules.append(current)
            stripped = stripped[2:].strip()
        if current is None or ":" not in stripped:
            continue
        key, _, value = stripped.partition(":")
        current[key.strip()] = value.strip().strip("'\"")
    return rules


def ci_violations(text: str) -> list[str]:
    """Every way the release gate must not be weakened."""
    problems: list[str] = []
    block = job_block(text, RELEASE_JOB)
    if block is None:
        return [f"{RELEASE_JOB} job is missing"]

    if not re.search(r"^[ \t]+allow_failure:[ \t]*false[ \t]*$", block, re.M):
        problems.append(f"{RELEASE_JOB} must set allow_failure: false")

    rules = job_rules(block)
    tag_rules = [r for r in rules if "CI_COMMIT_TAG" in r.get("if", "")]
    if not tag_rules:
        problems.append(f"{RELEASE_JOB} has no tag-pipeline rule")
    else:
        for rule in tag_rules:
            if rule.get("when") != "always":
                problems.append(
                    f"{RELEASE_JOB} tag rule must run with when: always, "
                    f"not {rule.get('when')!r}")
    default_rules = [r for r in rules if not r.get("if")]
    if not any(r.get("when") == "manual" for r in default_rules):
        problems.append(
            f"{RELEASE_JOB} must stay a blocking manual job for pipelines")

    if "--release" not in block:
        problems.append(f"{RELEASE_JOB} must run the runner with --release")
    if "--no-gate" in block:
        problems.append(f"{RELEASE_JOB} must not use --no-gate")
    if "--ignore-all-known-gaps" in text or "ignore_all" in text:
        problems.append("no wildcard 'ignore all known gaps' switch is allowed")

    for job in BLOCKING_JOBS:
        other = job_block(text, job)
        if other is None:
            problems.append(f"{job} job is missing")
            continue
        if re.search(r"^[ \t]+allow_failure:[ \t]*true[ \t]*$", other, re.M):
            problems.append(f"{job} must not allow failure")
        if re.search(r"^[ \t]+when:[ \t]*manual[ \t]*$", other, re.M):
            problems.append(f"{job} must run automatically on every pipeline")
    return problems


class ReleaseCiContractTest(unittest.TestCase):
    def setUp(self):
        self.ci = CI_PATH.read_text(encoding="utf-8")

    def test_the_current_pipeline_satisfies_the_contract(self):
        self.assertEqual(ci_violations(self.ci), [])

    def test_a_non_blocking_release_gate_is_caught(self):
        mutated = self.ci.replace(
            f"{RELEASE_JOB}:\n  stage: eval", f"{RELEASE_JOB}:\n  stage: eval", 1)
        mutated = re.sub(
            rf"({RELEASE_JOB}:[\s\S]*?)allow_failure: false",
            r"\1allow_failure: true", mutated, count=1)
        self.assertTrue(any("allow_failure" in p for p in ci_violations(mutated)))

    def test_a_deleted_release_gate_is_caught(self):
        block = job_block(self.ci, RELEASE_JOB)
        self.assertTrue(any("missing" in p
                            for p in ci_violations(self.ci.replace(block, ""))))

    def test_a_dropped_release_flag_is_caught(self):
        mutated = self.ci.replace("      --release\n", "", 1)
        self.assertNotEqual(mutated, self.ci)
        self.assertTrue(any("--release" in p for p in ci_violations(mutated)))

    def test_a_tag_pipeline_that_skips_the_gate_is_caught(self):
        block = job_block(self.ci, RELEASE_JOB)
        mutated_block = block.replace("""    - if: '$CI_COMMIT_TAG'
      when: always
""", "")
        self.assertIn("$CI_COMMIT_TAG", block)
        mutated = self.ci.replace(block, mutated_block)
        self.assertTrue(any("tag-pipeline rule" in p
                            for p in ci_violations(mutated)))

    def test_a_manual_only_tag_rule_is_caught(self):
        block = job_block(self.ci, RELEASE_JOB)
        mutated = self.ci.replace(
            block,
            block.replace("""    - if: '$CI_COMMIT_TAG'
      when: always""", """    - if: '$CI_COMMIT_TAG'
      when: manual"""))
        self.assertTrue(any("when: always" in p for p in ci_violations(mutated)))

    def test_a_non_blocking_manual_release_job_is_caught(self):
        block = job_block(self.ci, RELEASE_JOB)
        mutated_block = block.replace("allow_failure: false", "allow_failure: true")
        mutated_block = mutated_block.replace("    - when: manual\n", "")
        mutated = self.ci.replace(block, mutated_block)
        problems = ci_violations(mutated)
        self.assertTrue(any("blocking manual job" in p for p in problems))

    def test_a_no_gate_release_job_is_caught(self):
        block = job_block(self.ci, RELEASE_JOB)
        mutated = self.ci.replace(block, block.replace("--release", "--no-gate"))
        self.assertTrue(any("--no-gate" in p for p in ci_violations(mutated)))

    def test_an_ignore_all_switch_is_caught(self):
        mutated = self.ci + "\n# --ignore-all-known-gaps is forbidden\n"
        self.assertTrue(any("ignore all known gaps" in p
                            for p in ci_violations(mutated)))


class SkippedClassificationTest(unittest.TestCase):
    """``skipped`` is its own population — never a silently green one."""

    PATH = EVAL_ROOT / "skipped_tests.json"

    def setUp(self):
        self.payload = json.loads(self.PATH.read_text(encoding="utf-8"))

    def test_every_entry_is_classified_and_explained(self):
        categories = self.payload["categories"]
        self.assertIn("redis", categories)
        self.assertEqual(sorted(categories), sorted(_SKIP_CATEGORIES))
        required = {"test", "reason", "category", "blocks_release", "ci_hint"}
        for entry in self.payload["tests"]:
            with self.subTest(test=entry["test"]):
                self.assertTrue(required <= set(entry), sorted(entry))
                self.assertIn(entry["category"], categories)
                self.assertTrue(entry["reason"].strip())
                self.assertTrue(entry["ci_hint"].strip())

    def test_blocking_categories_match_the_declared_set(self):
        blocking = set(self.payload["blocking_categories"])
        self.assertNotIn("explicit_integration", blocking)
        self.assertIn("redis", blocking)
        for entry in self.payload["tests"]:
            self.assertEqual(entry["blocks_release"],
                             entry["category"] in blocking)

    def test_the_totals_match_the_entries(self):
        self.assertEqual(self.payload["total"], len(self.payload["tests"]))
        by_category = {name: 0 for name in self.payload["categories"]}
        for entry in self.payload["tests"]:
            by_category[entry["category"]] += 1
        self.assertEqual(self.payload["by_category"], by_category)
        self.assertGreaterEqual(self.payload["budget"], self.payload["total"],
                                "the skip budget may only ratchet down")

    def test_the_document_is_not_stale(self):
        """Every recorded reason must still exist verbatim in ``tests/``."""
        corpus = "\n".join(path.read_text(encoding="utf-8")
                           for path in sorted((REPO_ROOT / "tests").glob("test_*.py")))
        for entry in self.payload["tests"]:
            with self.subTest(test=entry["test"]):
                self.assertIn(entry["reason"], corpus)
                self.assertTrue(
                    (REPO_ROOT / entry["test"].split(":")[0]).is_file())

    def test_the_classifier_exposes_a_check_mode(self):
        source = (REPO_ROOT / "scripts" / "classify_skipped_tests.py").read_text(
            encoding="utf-8")
        self.assertIn('"--check"', source)
        self.assertIn("is stale", source)
        self.assertIn("refusing to write an empty artifact", source)

    def test_skipped_tests_are_never_reported_as_passed(self):
        self.assertTrue(self.payload["tests"], "the classification must not be empty")
        report = RUNNER.build_report([], "smoke", "", release=False)
        metrics = json.dumps(report.get("metrics") or {})
        self.assertNotIn('"skipped"', metrics)
        self.assertEqual(report.get("passed", 0), 0)
        self.assertIsNone(report.get("pass_rate"))


class KnownGapAllowlistContractTest(unittest.TestCase):
    def _write(self, payload) -> str:
        tmp = tempfile.NamedTemporaryFile(
            "w", suffix=".json", delete=False, encoding="utf-8")
        json.dump(payload, tmp, ensure_ascii=False)
        tmp.close()
        return tmp.name

    def test_a_wildcard_entry_never_widens_the_allowlist(self):
        for wildcard in ("*", "all", "ignore_all", "any"):
            path = self._write({"allowed_p0_known_gaps": [
                {"case_id": wildcard, "reviewer": "x", "reviewed_at": "2026-09-18",
                 "reason": "r", "expiry": "2099-01-01",
                 "target_fix_version": "v0.1.10"}]})
            with self.subTest(wildcard=wildcard):
                self.assertEqual(RUNNER._load_known_gap_allowlist(path), [])

    def test_case_ids_are_still_accepted_verbatim(self):
        path = self._write({"allowed_p0_known_gaps": ["ANA-INTENT-052"]})
        self.assertEqual(RUNNER._load_known_gap_allowlist(path),
                         ["ANA-INTENT-052"])

    def test_there_is_no_ignore_all_cli_switch(self):
        parser = subprocess.run(
            [sys.executable, str(RUNNER_PATH), "--suite", "smoke",
             "--ignore-all-known-gaps"],
            capture_output=True, text=True, cwd=str(REPO_ROOT))
        self.assertNotEqual(parser.returncode, 0)
        self.assertIn("unrecognized arguments", parser.stderr)

    def test_the_committed_allowlist_is_empty(self):
        path = EVAL_ROOT / "known_gap_allowlist.json"
        if not path.is_file():
            self.skipTest("no committed allowlist")
        payload = json.loads(path.read_text(encoding="utf-8"))
        entries = payload.get("allowed_p0_known_gaps") if isinstance(payload, dict) \
            else payload
        self.assertEqual(list(entries or []), [])


if __name__ == "__main__":
    unittest.main()
