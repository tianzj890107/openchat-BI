"""RED contract tests for migrating the sole release mainline to master."""

from __future__ import annotations

import re
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def read(relative: str) -> str:
    return (ROOT / relative).read_text(encoding="utf-8")


class MasterMainlinePolicyRedTests(unittest.TestCase):
    def test_agents_declares_master_as_only_release_mainline(self):
        text = read("AGENTS.md")
        self.assertIn("`master` 是唯一发布主线", text)
        self.assertIn("`main` 已退役并删除", text)
        self.assertNotIn("`main` 是发布分支", text)
        self.assertNotIn("`main` 是历史保留分支", text)

    def test_agents_mr_mapping_targets_master_with_fixed_reviewers(self):
        text = read("AGENTS.md")
        # Temporary branches are the MR source; the archived 20260727 mapping
        # stays only as an audit record.
        self.assertRegex(
            text,
            r"source_branch[^\n]{0,120}target_branch\s*=\s*master",
        )
        for prefix in ("`feature/*`", "`bugfix/*`", "`hotfix/*`"):
            self.assertIn(prefix, text)
        self.assertIn("20260727", text)
        self.assertIn("tianzijing", text)
        self.assertIn("id 166", text)
        self.assertIn("zhangzhen", text)
        self.assertIn("id 245", text)

    def test_push_workflow_pushes_temporary_branches_and_targets_master(self):
        text = read("docs/gitlab-push-workflow.md")
        self.assertIn("HEAD == gitlab/<branch>", text)
        for prefix in ("`feature/*`", "`bugfix/*`", "`hotfix/*`"):
            self.assertIn(prefix, text)
        self.assertIn("20260727", text)
        self.assertIn("已归档", text)
        self.assertIn("不得直接 push 到", text)
        self.assertIn("`master` 是唯一发布主线", text)
        self.assertIn("`main` 已退役并删除", text)
        self.assertNotIn("merge 到 `main`", text)

    def test_live_docs_retire_archived_20260727_as_delivery_branch(self):
        """20260727 已归档：现行文档不得再要求把开发提交推到该分支。"""
        live_docs = (
            "AGENTS.md",
            "debug.md",
            ".claude/agents/devops.md",
            "docs/git-dual-remote-workflow.md",
            "docs/specs/master-mainline-delivery.md",
        )
        forbidden = (
            re.compile(r"统一开发分支（`gitlab/20260727`）"),
            re.compile(r"开发提交推送到\s*`gitlab/20260727`"),
            re.compile(r"source_branch`?\s*为\s*`?20260727"),
            re.compile(r"master\.\.20260727"),
            re.compile(r"只\s*push\s*到\s*`?gitlab/20260727"),
        )
        for path in live_docs:
            text = read(path)
            for pattern in forbidden:
                self.assertIsNone(
                    pattern.search(text),
                    "%s 仍把归档分支 20260727 当成当前交付分支：%s"
                    % (path, pattern.pattern),
                )

        agents = read("AGENTS.md")
        self.assertIn("git push gitlab <branch>", agents)
        self.assertIn("`source_branch` 为当前临时分支", agents)
        self.assertIn("`20260727` 已归档", agents)

    def test_version_policy_uses_master_as_release_branch(self):
        text = read("docs/versions/versioning-policy.md")
        self.assertIn("`master` 是唯一发布主线", text)
        self.assertIn("`main` 已退役并删除", text)
        self.assertNotIn("`main` 仅作为历史保留分支", text)
        self.assertNotIn("merge 到 `main`", text)

    def test_deployment_inventory_names_master_and_devops_source(self):
        text = read("DEPLOYMENT.md")
        self.assertIn("日常开发分支 `feature/*` / `bugfix/*`，唯一发布主线 `master`", text)
        self.assertIn("`20260727` 已归档", text)
        self.assertIn("`main` 已退役并删除", text)
        self.assertIn("DevOps 从 `master`", text)
        self.assertIn("push 不等于部署", text)

    def test_dockerfile_preserves_administrator_huawei_base_image(self):
        dockerfile = read("Dockerfile")
        from_lines = [line.strip() for line in dockerfile.splitlines() if line.startswith("FROM ")]
        self.assertEqual(
            from_lines,
            ["FROM swr.cn-east-3.myhuaweicloud.com/release/python:3.13-slim"],
        )

    def test_push_script_names_master_release_branch_and_never_recreates_main(self):
        script = read("scripts/push_gitlab.py")
        self.assertIn('RELEASE_BRANCH = "master"', script)
        self.assertIn('RETIRED_BRANCH = "main"', script)
        self.assertNotIn('HISTORICAL_BRANCH = "main"', script)
        self.assertNotIn('MAIN_BRANCH = "main"', script)
        self.assertIn("唯一发布主线 master", script)

    def test_current_policy_has_no_active_main_release_wording(self):
        files = (
            "AGENTS.md",
            "docs/gitlab-push-workflow.md",
            "docs/versions/versioning-policy.md",
            "DEPLOYMENT.md",
            "scripts/push_gitlab.py",
        )
        stale_patterns = (
            r"main 是发布分支",
            r"`main` 是发布分支",
            r"merge 到 `main`",
            r"target_branch\s*=\s*main",
            r"发布分支 `main`",
        )
        violations = []
        for filename in files:
            text = read(filename)
            for pattern in stale_patterns:
                if re.search(pattern, text):
                    violations.append(f"{filename}: {pattern}")
        self.assertEqual(violations, [], "仍存在旧主线口径：" + "; ".join(violations))


if __name__ == "__main__":
    unittest.main()
