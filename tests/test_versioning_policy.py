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
CURRENT_VERSION = "ontology-v0.1.5"
# Tags/Releases that actually exist on the remote.  ``ontology-v0.1.0`` was
# released on 2026-09-29; ``ontology-v0.1.1`` (skill-extraction PATCH) and
# ``ontology-v0.1.2`` (progress-narration PATCH) were authorized and tagged
# on 2026-10-15; ``ontology-v0.1.3`` was released on 2026-10-20 and
# ``CURRENT_VERSION`` was backfilled on 2026-10-27 before the loading cut.
RELEASED_TAGS = frozenset(
    {"ontology-v0.1.0", "ontology-v0.1.1", "ontology-v0.1.2", "ontology-v0.1.3",
     "ontology-v0.1.4", CURRENT_VERSION}
)


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
            "ontology-v0.0.1",
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
        self.assertIn("授权 tag 不等于授权 GitLab Release", policy)
        self.assertIn("授权 Release 不等于授权部署", policy)
        self.assertIn("授权部署不等于授权升级版本", policy)

    def test_readme_links_policy(self) -> None:
        readme = (ROOT / "README.md").read_text(encoding="utf-8")
        self.assertIn("docs/versions/versioning-policy.md", readme)
        self.assertIn("commit、push、部署不自动触发版本升级", readme)

    def test_root_readme_describes_bi_project_and_runtime_docs_are_nested(self) -> None:
        readme = (ROOT / "README.md").read_text(encoding="utf-8")
        runtime = (ROOT / "open_claude/README.md").read_text(encoding="utf-8")
        self.assertTrue(readme.startswith("# eimosp-ontology-agentic-analytics · 智能分析"))
        self.assertIn("六步分析 SOP", readme)
        self.assertIn("open_claude/README.md", readme)
        self.assertNotIn("# Open Claude\n", readme)
        self.assertTrue(runtime.startswith("# Open Claude Runtime"))
        self.assertIn("[../README.md](../README.md)", runtime)
        self.assertIn("open-claude", runtime)

    def test_versions_readme_links_policy_and_tracks_the_current_version(self) -> None:
        readme = (ROOT / "docs/versions/README.md").read_text(encoding="utf-8")
        self.assertIn("./versioning-policy.md", readme)
        self.assertIn(f"当前版本：`{CURRENT_VERSION}`", readme)
        self.assertIn("不按日期机械递增", readme)

    def test_agents_md_links_policy_and_mandates_authorization(self) -> None:
        agents = (ROOT / "AGENTS.md").read_text(encoding="utf-8")
        self.assertIn("docs/versions/versioning-policy.md", agents)
        self.assertIn("Agent 不得自行判断并升级正式版本", agents)
        self.assertIn("每周不自动升级 MINOR", agents)
        self.assertIn("每次部署不自动升级 PATCH", agents)
        self.assertIn("tag、GitLab Release、部署需要各自独立授权", agents)

    def test_gitlab_workflow_doc_does_not_auto_push_tags(self) -> None:
        doc = (ROOT / "docs/gitlab-push-workflow.md").read_text(encoding="utf-8")
        self.assertIn("不自动推 tag", doc)
        self.assertIn("versioning-policy.md", doc)
        self.assertIn("push 不等于部署", doc)

    def test_product_version_is_ontology_v0_1_5(self) -> None:
        """pyproject stays PEP 440; every display surface speaks ontology-v0.1.5."""
        self.assertIn('version = "0.1.5"', (ROOT / "pyproject.toml").read_text(encoding="utf-8"))
        self.assertIn(f'__version__ = "{CURRENT_VERSION}"', (ROOT / "bi_agent/__init__.py").read_text(encoding="utf-8"))
        app = (ROOT / "bi_agent/web/app.py").read_text(encoding="utf-8")
        self.assertIn(f'APP_VERSION = "{CURRENT_VERSION}"', app)
        self.assertIn(
            'FastAPI(title=APP_DISPLAY_NAME, version=APP_VERSION, root_path=APP_ROOT_PATH)',
            app,
        )
        pkg = json.loads((ROOT / "frontend/package.json").read_text(encoding="utf-8"))
        self.assertEqual(pkg["version"], "0.1.5")
        lock = json.loads((ROOT / "frontend/package-lock.json").read_text(encoding="utf-8"))
        self.assertEqual(lock["packages"][""]["version"], "0.1.5")
        self.assertEqual(lock["version"], "0.1.5")
        main = (ROOT / "frontend/src/main.jsx").read_text(encoding="utf-8")
        self.assertIn(f'const PRODUCT_VERSION = "{CURRENT_VERSION}";', main)
        self.assertIn(f'__version__ = "{CURRENT_VERSION}"', (ROOT / "open_claude/__init__.py").read_text(encoding="utf-8"))

    def test_no_unauthorized_version_documents(self) -> None:
        versions_dir = ROOT / "docs/versions"
        allowed = {"README.md", "versioning-policy.md", "ontology-v0.1.0.md",
                   "ontology-v0.1.1.md", "ontology-v0.1.2.md",
                   "ontology-v0.1.3.md", "ontology-v0.1.4.md", f"{CURRENT_VERSION}.md"} | {
            f"ontology-v0.0.{number}.md" for number in range(1, 11)
        }
        names = {p.name for p in versions_dir.iterdir() if p.is_file()}
        self.assertEqual(names, allowed)

    def test_agents_md_requires_gitlab_release_rules(self) -> None:
        agents = (ROOT / "AGENTS.md").read_text(encoding="utf-8")
        self.assertIn("ai-team/eimosp-ontology-agentic-analytics", agents)
        self.assertIn("基于同名 tag 创建 Release", agents)
        self.assertIn("只补缺失项", agents)
        self.assertIn("禁止覆盖已有 Release", agents)

    def test_gitlab_unified_push_contract(self) -> None:
        """Daily commits push their temporary branch; main merges need review."""
        agents = (ROOT / "AGENTS.md").read_text(encoding="utf-8")
        self.assertIn("gitlab/20260727", agents)
        self.assertIn("python scripts/push_gitlab.py", agents)
        self.assertIn("feature/*", agents)
        self.assertIn("bugfix/*", agents)
        self.assertIn("hotfix/*", agents)
        self.assertIn("tianzijing", agents)
        self.assertIn("不得直接 push 到 `main`", agents)
        doc = (ROOT / "docs/gitlab-push-workflow.md").read_text(encoding="utf-8")
        self.assertIn("HEAD == gitlab/<branch>", doc)
        self.assertIn("tianzijing", doc)
        self.assertIn("不执行 main 合并", doc)
        policy = (ROOT / "docs/versions/versioning-policy.md").read_text(encoding="utf-8")
        self.assertIn("20260727", policy)
        self.assertIn("feature/*", policy)
        self.assertIn("bugfix/*", policy)
        script = (ROOT / "scripts/push_gitlab.py").read_text(encoding="utf-8")
        self.assertIn('GITLAB_OWNER_REPO = "ai-team/eimosp-ontology-agentic-analytics"', script)
        self.assertIn('DEFAULT_TARGET_BRANCH = "20260727"', script)
        self.assertIn("tianzijing", script)

    def test_policy_doc_covers_gitlab_release_rules(self) -> None:
        policy = (ROOT / "docs/versions/versioning-policy.md").read_text(encoding="utf-8")
        self.assertIn("GitLab Release 在统一协作仓库 `ai-team/eimosp-ontology-agentic-analytics`（GitLab）上创建", policy)
        self.assertIn("基于同名 tag", policy)
        self.assertIn("创建一个 Release", policy)
        self.assertIn("tag 指向定版 commit", policy)
        self.assertIn("已存在且内容正确的 Release 保留", policy)
        self.assertIn("不得自动删除、覆盖或", policy)
        self.assertIn("重建", policy)
        self.assertIn("禁止 force push", policy)

    def test_gitlab_workflow_doc_has_release_completion(self) -> None:
        doc = (ROOT / "docs/gitlab-push-workflow.md").read_text(encoding="utf-8")
        self.assertIn("## GitLab Release", doc)
        self.assertIn("GitLab 仓库存在对应的正式 Release", doc)
        self.assertIn("只补缺失项", doc)
        self.assertIn("不覆盖", doc)
        self.assertIn("已有 Release", doc)

    def test_readme_and_v010_doc_list_gitlab_release(self) -> None:
        readme = (ROOT / "README.md").read_text(encoding="utf-8")
        self.assertIn("https://gitlab.boulderaitech.com/ai-team/eimosp-ontology-agentic-analytics/-/releases/ontology-v0.0.1", readme)
        doc = (ROOT / "docs/versions/ontology-v0.0.1.md").read_text(encoding="utf-8")
        self.assertIn("https://gitlab.boulderaitech.com/ai-team/eimosp-ontology-agentic-analytics/-/releases/ontology-v0.0.1", doc)
        self.assertIn("定版 commit `e4b0a8f`", doc)

    def test_no_unexpected_git_tags(self) -> None:
        """Exactly the ten renamed tags plus the authorized release tags.

        ``ontology-v0.1.0`` was created on ``master`` (定版 commit ``74fca80``)
        after the version-cut Merge Request merged; ``ontology-v0.1.1`` and
        ``ontology-v0.1.2`` were authorized on 2026-10-15 and created on the
        ``c82221f`` / ``3c4de1e`` master merge commits.  ``CURRENT_VERSION``
        was explicitly backfilled on 2026-10-27 before the loading-optimization
        version cut.
        """
        proc = subprocess.run(
            ["git", "-C", str(ROOT), "tag", "--list"],
            capture_output=True, text=True, check=True,
        )
        tags = {t for t in proc.stdout.splitlines() if t.strip()}
        renamed = {f"ontology-v0.0.{number}" for number in range(1, 11)}
        self.assertEqual(tags, renamed | set(RELEASED_TAGS))

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
        doc = (ROOT / "docs/versions/ontology-v0.0.1.md").read_text(encoding="utf-8")
        self.assertIn("状态：正式版", doc)
        self.assertIn("Git Tag：`ontology-v0.0.1`", doc)
        index = (ROOT / "docs/versions/README.md").read_text(encoding="utf-8")
        self.assertIn("正式版 / 当前版本", index)

    def test_v010_doc_has_no_obsolete_tool_names(self) -> None:
        doc = (ROOT / "docs/versions/ontology-v0.0.1.md").read_text(encoding="utf-8")
        # MetricDataQuery / SQLRun are no longer registered tools and must not
        # be presented as current public tools in the formal version doc.
        self.assertNotIn("MetricDataQuery", doc)
        self.assertNotIn("SQLRun", doc)

    def test_v010_doc_distinguishes_metric_tool_roles(self) -> None:
        doc = (ROOT / "docs/versions/ontology-v0.0.1.md").read_text(encoding="utf-8")
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
        doc = (ROOT / "docs/versions/ontology-v0.0.1.md").read_text(encoding="utf-8")
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
