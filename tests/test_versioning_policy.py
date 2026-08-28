"""Contract tests for the semantic versioning / release policy docs.

These tests verify real document contracts (existence, key semantics, links,
authorization rules) and that this documentation-only change did not create a
new version, tag, or release artifact.  They never touch git history or user
data.
"""

import json
import subprocess
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


class VersioningPolicyDocTests(unittest.TestCase):
    def test_policy_document_exists_with_core_semantics(self) -> None:
        policy = ROOT / "docs/versions/versioning-policy.md"
        self.assertTrue(policy.exists(), "versioning-policy.md must exist")
        text = policy.read_text(encoding="utf-8")
        for required in (
            "vMAJOR.MINOR.PATCH",
            "PATCH",
            "MINOR",
            "MAJOR",
            "v0.1.0",
            "当前正式版本保持为",
        ):
            self.assertIn(required, text)

    def test_policy_defines_record_boundaries_and_authorization(self) -> None:
        policy = (ROOT / "docs/versions/versioning-policy.md").read_text(encoding="utf-8")
        # commit / push / deploy never auto-release a version.
        self.assertIn("每次 commit 不等于发布新版本", policy)
        self.assertIn("每次 push 不等于发布新版本", policy)
        self.assertIn("每次部署也不必然升级正式版本", policy)
        self.assertIn("不要为了日期机械升级", policy)
        self.assertIn("Agent 不得自行判断并升级正式版本", policy)
        # tag / Release / deploy need independent authorization.
        self.assertIn("指定版本号不等于授权 tag", policy)
        self.assertIn("授权 tag 不等于授权 GitHub Release", policy)
        self.assertIn("授权 Release 不等于授权部署", policy)
        self.assertIn("授权部署不等于授权升级版本", policy)

    def test_readme_links_policy(self) -> None:
        readme = (ROOT / "README.md").read_text(encoding="utf-8")
        self.assertIn("docs/versions/versioning-policy.md", readme)
        self.assertIn("commit、push、部署不自动触发版本升级", readme)

    def test_versions_readme_links_policy_and_stays_on_v0_1_0(self) -> None:
        readme = (ROOT / "docs/versions/README.md").read_text(encoding="utf-8")
        self.assertIn("./versioning-policy.md", readme)
        self.assertIn("当前版本：`v0.1.0`", readme)
        self.assertIn("不按日期机械递增", readme)

    def test_agents_md_links_policy_and_mandates_authorization(self) -> None:
        agents = (ROOT / "AGENTS.md").read_text(encoding="utf-8")
        self.assertIn("docs/versions/versioning-policy.md", agents)
        self.assertIn("Agent 不得自行判断并升级正式版本", agents)
        self.assertIn("每周不自动升级 MINOR", agents)
        self.assertIn("每次部署不自动升级 PATCH", agents)
        self.assertIn("tag、GitHub Release、部署需要各自独立授权", agents)

    def test_dual_remote_doc_does_not_auto_push_tags(self) -> None:
        doc = (ROOT / "docs/git-dual-remote-workflow.md").read_text(encoding="utf-8")
        self.assertIn("不自动推 tag", doc)
        self.assertIn("versioning-policy.md", doc)
        self.assertIn("push 不等于部署", doc)

    def test_product_version_still_v0_1_0(self) -> None:
        self.assertIn('version = "0.1.0"', (ROOT / "pyproject.toml").read_text(encoding="utf-8"))
        self.assertIn('__version__ = "0.1.0"', (ROOT / "bi_agent/__init__.py").read_text(encoding="utf-8"))
        self.assertIn('version="0.1.0"', (ROOT / "bi_agent/web/app.py").read_text(encoding="utf-8"))
        pkg = json.loads((ROOT / "frontend/package.json").read_text(encoding="utf-8"))
        self.assertEqual(pkg["version"], "0.1.0")
        lock = json.loads((ROOT / "frontend/package-lock.json").read_text(encoding="utf-8"))
        self.assertEqual(lock["packages"][""]["version"], "0.1.0")
        main = (ROOT / "frontend/src/main.jsx").read_text(encoding="utf-8")
        self.assertIn('const PRODUCT_VERSION = "v0.1.0";', main)

    def test_no_unauthorized_version_documents(self) -> None:
        versions_dir = ROOT / "docs/versions"
        allowed = {"README.md", "versioning-policy.md", "v0.1.0.md"}
        names = {p.name for p in versions_dir.iterdir() if p.is_file()}
        self.assertEqual(names, allowed)
        self.assertFalse((versions_dir / "v0.1.1.md").exists())

    def test_no_git_tags_created(self) -> None:
        proc = subprocess.run(
            ["git", "-C", str(ROOT), "tag", "--list"],
            capture_output=True, text=True, check=True,
        )
        self.assertEqual(proc.stdout.strip(), "")


if __name__ == "__main__":
    unittest.main()
