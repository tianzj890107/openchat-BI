"""Repository-wide RED gate for stale operational references to main."""

from __future__ import annotations

from pathlib import Path
import re
import subprocess
import unittest


ROOT = Path(__file__).resolve().parents[1]
HISTORICAL_PREFIXES = (
    "changelog/",
    # Version-family archives: the retired ``v0.1.x`` naming and the current
    # ``ontology-v0.0.x`` naming both record the policy of their own time
    # (including the pre-master ``main`` mainline).
    "docs/versions/v",
    "docs/versions/ontology-v",
)
HISTORICAL_SPECS = {
    "docs/specs/delete-historical-main.md",
    "docs/specs/master-default-protection-cutover.md",
    "docs/specs/master-mainline-migration.md",
    # This contract necessarily quotes the spellings it prohibits.
    "docs/specs/repository-wide-master-branch-consistency.md",
}

# These patterns describe an actionable/current main branch, not a harmless
# Python main() symbol or an explicit "retired and must not be recreated" guard.
STALE_OPERATIONAL_PATTERNS = (
    re.compile(r"20260727\s*(?:→|->|into)\s*`?main`?", re.I),
    re.compile(r"(?:merge|合并)\s*(?:到|至|into|to)\s*`?main`?", re.I),
    re.compile(r"(?:source_branch|target_branch)\s*[=:]\s*[`\"']?main\b", re.I),
    re.compile(r"\b(?:origin|gitlab)/main\b", re.I),
    re.compile(r"refs/heads/main\b", re.I),
    re.compile(r"(?:默认分支|发布分支|保护分支)\s*(?:是|为|[:：])?\s*`?main`?", re.I),
    re.compile(r"`?main`?\s*(?:是|为)\s*(?:默认分支|发布分支|保护分支|历史保留分支)", re.I),
    re.compile(r"(?:build|构建|deploy|部署).{0,40}(?:from|基于|使用)\s*`?main`?", re.I),
)


def tracked_text_files() -> list[Path]:
    output = subprocess.check_output(
        ["git", "ls-files", "-co", "--exclude-standard", "-z"], cwd=ROOT,
    )
    paths: list[Path] = []
    for raw in output.decode("utf-8", errors="surrogateescape").split("\0"):
        if not raw:
            continue
        relative = raw.replace("\\", "/")
        if relative.startswith(HISTORICAL_PREFIXES) or relative in HISTORICAL_SPECS:
            continue
        path = ROOT / raw
        if not path.is_file() or path.stat().st_size > 2_000_000:
            continue
        try:
            path.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue
        paths.append(path)
    return paths


class RepositoryWideMasterConsistencyTests(unittest.TestCase):
    def test_active_repository_has_no_actionable_main_branch_instructions(self) -> None:
        violations: list[str] = []
        for path in tracked_text_files():
            relative = path.relative_to(ROOT).as_posix()
            # Enforcement tests quote forbidden spellings to detect them; scan
            # production/rule content here and validate test semantics below.
            if relative.startswith("tests/"):
                continue
            for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
                if any(pattern.search(line) for pattern in STALE_OPERATIONAL_PATTERNS):
                    violations.append(f"{relative}:{number}: {line.strip()}")
        self.assertEqual(
            violations, [],
            "stale operational main-branch references remain:\n" + "\n".join(violations),
        )

    def test_active_policy_uses_master_and_marks_main_deleted(self) -> None:
        for relative in (
            "AGENTS.md",
            "docs/gitlab-push-workflow.md",
            "docs/git-dual-remote-workflow.md",
            "docs/versions/versioning-policy.md",
            "DEPLOYMENT.md",
        ):
            with self.subTest(path=relative):
                text = (ROOT / relative).read_text(encoding="utf-8")
                self.assertIn("master", text)
                self.assertRegex(text, r"main.{0,20}(?:已退役并删除|退役|删除)")

    def test_push_guard_models_main_as_retired_not_historical(self) -> None:
        script = (ROOT / "scripts/push_gitlab.py").read_text(encoding="utf-8")
        self.assertIn('RETIRED_BRANCH = "main"', script)
        self.assertNotIn('HISTORICAL_BRANCH = "main"', script)
        self.assertIn("禁止重新创建", script)

    def test_legacy_policy_test_no_longer_requires_historical_main(self) -> None:
        legacy_test = (ROOT / "tests/test_master_mainline_policy.py").read_text(
            encoding="utf-8",
        )
        self.assertNotIn(
            "assertIn('HISTORICAL_BRANCH = \"main\"'", legacy_test,
            "legacy test still requires the deleted branch to be historical",
        )
        self.assertIn('RETIRED_BRANCH = "main"', legacy_test)

    def test_delivery_contract_is_20260727_to_master(self) -> None:
        agents = (ROOT / "AGENTS.md").read_text(encoding="utf-8")
        workflow = (ROOT / "docs/gitlab-push-workflow.md").read_text(encoding="utf-8")
        for text in (agents, workflow):
            self.assertRegex(text, r"20260727[\s\S]{0,40}(?:→|target_branch=)\s*`?master")
            self.assertIn("不得直接 push 到 `master`", text)


if __name__ == "__main__":
    unittest.main()
