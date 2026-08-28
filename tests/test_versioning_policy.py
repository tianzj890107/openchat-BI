"""Contract tests for the semantic versioning / release policy docs.

These tests verify real document contracts (existence, key semantics, links,
authorization rules) and that this documentation-only change did not create a
new version, tag, or release artifact.  They never touch git history or user
data.
"""

import json
import re
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

    def test_root_readme_describes_bi_project_and_runtime_docs_are_nested(self) -> None:
        readme = (ROOT / "README.md").read_text(encoding="utf-8")
        runtime = (ROOT / "open_claude/README.md").read_text(encoding="utf-8")
        self.assertTrue(readme.startswith("# openchat-BI · 智能分析"))
        self.assertIn("六步分析 SOP", readme)
        self.assertIn("open_claude/README.md", readme)
        self.assertNotIn("# Open Claude\n", readme)
        self.assertTrue(runtime.startswith("# Open Claude Runtime"))
        self.assertIn("[../README.md](../README.md)", runtime)
        self.assertIn("open-claude", runtime)

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

    def test_agents_md_requires_mirrored_releases(self) -> None:
        agents = (ROOT / "AGENTS.md").read_text(encoding="utf-8")
        self.assertIn("默认在 origin 和 personal 两个仓库各发布一个", agents)
        self.assertIn("只补缺失项", agents)
        self.assertIn("禁止覆盖已有 Release", agents)

    def test_policy_doc_covers_dual_repo_releases(self) -> None:
        policy = (ROOT / "docs/versions/versioning-policy.md").read_text(encoding="utf-8")
        self.assertIn("tianzj890107/openchat-BI", policy)
        self.assertIn("zhenzhang0408/openchat-BI", policy)
        self.assertIn("两个 Release 必须使用相同的版本号、tag、名称和正式版本说明", policy)
        self.assertIn("两个 tag 必须指向同一个定版 commit", policy)
        self.assertIn("只创建缺失的 Release", policy)
        self.assertIn("不得自动删除、覆盖或重建", policy)
        self.assertIn("保留已成功的 Release", policy)
        self.assertIn("不 force push", policy)

    def test_dual_remote_doc_has_mirrored_release_completion(self) -> None:
        doc = (ROOT / "docs/git-dual-remote-workflow.md").read_text(encoding="utf-8")
        self.assertIn("GitHub Release 双仓发布", doc)
        self.assertIn("两个仓库均存在内容一致的正式 Release", doc)
        self.assertIn("只补缺失项", doc)
        self.assertIn("不覆盖", doc)
        self.assertIn("已有 Release", doc)

    def test_readme_and_v010_doc_list_both_releases(self) -> None:
        readme = (ROOT / "README.md").read_text(encoding="utf-8")
        self.assertIn("https://github.com/tianzj890107/openchat-BI/releases/tag/v0.1.0", readme)
        self.assertIn("https://github.com/zhenzhang0408/openchat-BI/releases/tag/v0.1.0", readme)
        doc = (ROOT / "docs/versions/v0.1.0.md").read_text(encoding="utf-8")
        self.assertIn("https://github.com/tianzj890107/openchat-BI/releases/tag/v0.1.0", doc)
        self.assertIn("https://github.com/zhenzhang0408/openchat-BI/releases/tag/v0.1.0", doc)
        self.assertIn("同一个定版 commit `e4b0a8f`", doc)

    def test_no_unexpected_git_tags(self) -> None:
        """Only the official v0.1.0 tag may exist locally; no other tag."""
        proc = subprocess.run(
            ["git", "-C", str(ROOT), "tag", "--list"],
            capture_output=True, text=True, check=True,
        )
        tags = {t for t in proc.stdout.splitlines() if t.strip()}
        self.assertLessEqual(tags, {"v0.1.0"})

    def _authoritative_tool_names(self) -> set[str]:
        """Tool names from the agent tools declaration and registered schemas."""
        names: set[str] = set()
        agents = [p for p in (ROOT / ".claude/agents").glob("*.md")]
        for agent in agents:
            text = agent.read_text(encoding="utf-8")
            for line in text.splitlines():
                if line.startswith("tools:"):
                    names.update(
                        part.strip()
                        for part in line[len("tools:"):].split(",")
                        if part.strip()
                    )
        schema_re = re.compile(r'"name"\s*:\s*"([^"]+)"')
        for tool_file in (ROOT / "bi_agent/tools").glob("*.py"):
            src = tool_file.read_text(encoding="utf-8")
            names.update(schema_re.findall(src))
        return names

    def test_v010_doc_is_official_release(self) -> None:
        doc = (ROOT / "docs/versions/v0.1.0.md").read_text(encoding="utf-8")
        self.assertIn("状态：正式版 / 当前版本", doc)
        self.assertIn("Git Tag：`v0.1.0`", doc)
        index = (ROOT / "docs/versions/README.md").read_text(encoding="utf-8")
        self.assertIn("正式版 / 当前版本", index)

    def test_v010_doc_has_no_obsolete_tool_names(self) -> None:
        doc = (ROOT / "docs/versions/v0.1.0.md").read_text(encoding="utf-8")
        # MetricDataQuery / SQLRun are no longer registered tools and must not
        # be presented as current public tools in the formal version doc.
        self.assertNotIn("MetricDataQuery", doc)
        self.assertNotIn("SQLRun", doc)

    def test_v010_doc_distinguishes_metric_tool_roles(self) -> None:
        doc = (ROOT / "docs/versions/v0.1.0.md").read_text(encoding="utf-8")
        for tool in ("MetricCalculation", "Ontology-MetricQuery", "Ontology-FactQuery"):
            self.assertIn(tool, doc)
        # Each role matches the authoritative semantics.
        self.assertIn("指标定义、业务公式、统计口径", doc)
        self.assertIn("指标配置查询接口计算指标数据", doc)
        self.assertIn("已获得指标", doc)
        self.assertIn("只读事实查询或自主 SQL", doc)
        self.assertIn("TableGenerate", doc)
        self.assertIn("ChartGenerate", doc)
        self.assertIn("ChartGenerateMultiDim", doc)

    def test_v010_doc_tool_names_match_code_registry(self) -> None:
        """Every tool name named in the version doc exists in the agent tools
        declaration or a registered tool schema; obsolete names are rejected."""
        doc = (ROOT / "docs/versions/v0.1.0.md").read_text(encoding="utf-8")
        authoritative = self._authoritative_tool_names()
        self.assertIn("Ontology-MetricQuery", authoritative)
        self.assertIn("Ontology-FactQuery", authoritative)
        self.assertIn("MetricCalculation", authoritative)
        # Names the version doc presents as current tools.
        doc_names = set(
            re.findall(
                r"`((?:Ontology-[A-Za-z]+|MetricCalculation|TableGenerate|"
                r"ChartGenerateMultiDim|ChartGenerate|ListTables|DescribeTable|AskUser|"
                r"MetricDataQuery|SQLRun))`",
                doc,
            )
        )
        self.assertTrue(doc_names)
        for name in doc_names:
            self.assertIn(name, authoritative)


if __name__ == "__main__":
    unittest.main()
