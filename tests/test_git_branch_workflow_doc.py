"""Contract tests for the Git branch and merge workflow spec.

These tests pin the branch model, the PR-based merge mechanism and the
release / hotfix rules agreed for this repository.  They never touch git
history, remotes or user data.
"""

from __future__ import annotations

import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
BRANCH_DOC = "docs/git-branch-workflow.md"
DIAGRAM_DOC = "docs/diagrams/13-git-branch-model.md"


def read(relative: str) -> str:
    return (ROOT / relative).read_text(encoding="utf-8")


class GitBranchWorkflowDocTests(unittest.TestCase):
    def test_branch_workflow_doc_exists_and_links_version_policy(self) -> None:
        self.assertTrue((ROOT / BRANCH_DOC).is_file(), f"{BRANCH_DOC} must exist")
        self.assertIn("./versions/versioning-policy.md", read(BRANCH_DOC))

    def test_doc_defines_long_lived_and_temporary_branches(self) -> None:
        text = read(BRANCH_DOC)
        for name in ("master", "release/", "feature/", "bugfix/", "hotfix/"):
            self.assertIn(name, text)
        self.assertIn("归档分支", text)
        self.assertIn("不允许直接提交", text)
        self.assertIn("从 `master` 拉出", text)
        self.assertRegex(text, r"`release/\*`\s*拉出")

    def test_every_merge_back_uses_a_pull_request(self) -> None:
        text = read(BRANCH_DOC)
        self.assertIn("Pull Request", text)
        self.assertIn("直接推进长期分支", text)
        self.assertIn("`feature/*` → `master`", text)
        self.assertIn("`bugfix/*` → `master`", text)
        self.assertIn("`hotfix/*` → `release/*`", text)
        self.assertIn("`hotfix/*` → `master`", text)

    def test_release_branch_is_cut_from_a_stable_master_node(self) -> None:
        text = read(BRANCH_DOC)
        self.assertIn("稳定节点", text)
        self.assertIn("阶段性功能开发", text)

    def test_hotfix_merges_back_into_both_release_and_master(self) -> None:
        text = read(BRANCH_DOC)
        self.assertIn("双 PR", text)
        self.assertIn("向 `release/*` 提 PR", text)
        self.assertIn("向 `master` 提 PR", text)

    def test_branch_prefixes_are_canonical_over_diagram_labels(self) -> None:
        text = read(BRANCH_DOC)
        self.assertIn("前缀", text)
        for sample in ("feature-1", "bugfix-1", "hotfix-1"):
            self.assertIn(sample, text)

    def test_doc_never_auto_bumps_the_version(self) -> None:
        text = read(BRANCH_DOC)
        self.assertIn("人工建议", text)
        self.assertRegex(text, r"不自动触发|不自动升级")

    def test_diagram_is_registered_in_the_directory(self) -> None:
        self.assertTrue((ROOT / DIAGRAM_DOC).is_file(), f"{DIAGRAM_DOC} must exist")
        self.assertIn("13-git-branch-model.md", read("docs/diagrams/README.md"))

    def test_diagram_shows_both_hotfix_pull_requests(self) -> None:
        text = read(DIAGRAM_DOC)
        self.assertIn("```mermaid", text)
        self.assertIn("PR 1", text)
        self.assertIn("PR 2", text)
        self.assertEqual(text.count("```") % 2, 0, "code fences must be balanced")

    def test_workflow_docs_point_to_the_branch_spec(self) -> None:
        for relative in ("docs/gitlab-push-workflow.md", "docs/versions/README.md"):
            with self.subTest(path=relative):
                self.assertIn("git-branch-workflow.md", read(relative))


if __name__ == "__main__":
    unittest.main()
