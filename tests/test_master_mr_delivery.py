"""Opt-in, read-only acceptance tests for a temporary-branch -> master delivery MR.

The MR source is the current temporary branch (``feature/*``, ``bugfix/*``,
``hotfix/*``); ``20260727`` is archived and no longer a delivery branch.
Override the expected source with ``MR_SOURCE_BRANCH``.

These tests never write to Git or GitLab.  They are skipped during ordinary
offline regression runs and become an operational RED/GREEN gate only when
RUN_GITLAB_DELIVERY_TESTS=1 is explicitly supplied.
"""

from __future__ import annotations

import json
import os
import subprocess
import unittest
import urllib.parse
import urllib.request
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PROJECT_ID = "1065"
API_BASE = "http://gitlab.boulderaitech.com/api/v4"


def _current_branch() -> str:
    proc = subprocess.run(
        ["git", "-C", str(ROOT), "branch", "--show-current"],
        capture_output=True,
        text=True,
    )
    return proc.stdout.strip()


SOURCE_BRANCH = os.environ.get("MR_SOURCE_BRANCH", "").strip() or _current_branch()
TARGET_BRANCH = "master"
REVIEWER_ID = 166
ASSIGNEE_ID = 245
ADMIN_IMAGE_COMMIT = "a7ebafaa0097655fdc2d8595e367f0b4adaca47d"
HUAWEI_IMAGE = "swr.cn-east-3.myhuaweicloud.com/release/python:3.13-slim"

DELIVERY_PATHS = (
    "DEPLOYMENT.md",
    "Dockerfile",
    "docs/gitlab-push-workflow.md",
    "scripts/push_gitlab.py",
    "docs/specs/master-mainline-migration.md",
    "docs/specs/master-mainline-delivery.md",
    "tests/test_master_mainline_policy.py",
    "tests/test_master_mr_delivery.py",
    "tests/test_push_gitlab.py",
)

def git(*args: str, check: bool = True) -> str:
    proc = subprocess.run(
        ["git", "-C", str(ROOT), *args],
        capture_output=True,
        text=True,
    )
    if check and proc.returncode != 0:
        raise AssertionError(proc.stderr or proc.stdout)
    return proc.stdout.strip()


@unittest.skipUnless(
    os.environ.get("RUN_GITLAB_DELIVERY_TESTS") == "1",
    "set RUN_GITLAB_DELIVERY_TESTS=1 for read-only GitLab delivery acceptance",
)
class MasterMergeRequestDeliveryTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        token_path = Path.home() / ".config" / "codex" / "gitlab_token"
        if not token_path.is_file():
            raise unittest.SkipTest("GitLab token file is unavailable")
        cls.token = token_path.read_text(encoding="utf-8").strip()
        if not cls.token:
            raise unittest.SkipTest("GitLab token file is empty")

    @classmethod
    def api_get(cls, path: str, params: dict | None = None):
        query = "?" + urllib.parse.urlencode(params or {}) if params else ""
        request = urllib.request.Request(
            f"{API_BASE}{path}{query}",
            headers={"PRIVATE-TOKEN": cls.token},
        )
        with urllib.request.urlopen(request, timeout=10) as response:
            return json.loads(response.read().decode("utf-8"))

    def test_all_migration_files_are_committed_in_head(self):
        pending = []
        for path in DELIVERY_PATHS:
            status = git("status", "--porcelain", "--", path)
            if status:
                pending.append(f"{path}: {status}")
        self.assertEqual(pending, [], "交付文件尚未全部提交：" + "; ".join(pending))

        # These two files also contain pre-existing changelog-workflow edits
        # in the shared worktree.  Require the mainline-policy hunks in HEAD
        # without forcing unrelated hunks into this delivery commit.
        agents_at_head = git("show", "HEAD:AGENTS.md")
        version_policy_at_head = git("show", "HEAD:docs/versions/versioning-policy.md")
        for text in (agents_at_head, version_policy_at_head):
            self.assertIn("`master` 是唯一发布主线", text)
            self.assertIn("`main`", text)
            self.assertIn("已退役并删除", text)
            self.assertNotIn("merge 到 `main`", text)

    def test_local_branch_and_remote_development_head_match(self):
        self.assertEqual(git("branch", "--show-current"), SOURCE_BRANCH)
        local_head = git("rev-parse", "HEAD")
        remote_line = git("ls-remote", "gitlab", f"refs/heads/{SOURCE_BRANCH}")
        self.assertTrue(remote_line, f"gitlab/{SOURCE_BRANCH} 不存在（请先 push 同名临时分支）")
        self.assertEqual(remote_line.split()[0], local_head)

    def test_remote_master_still_contains_administrator_image_commit(self):
        git("fetch", "gitlab", TARGET_BRANCH, "--quiet")
        proc = subprocess.run(
            ["git", "-C", str(ROOT), "merge-base", "--is-ancestor", ADMIN_IMAGE_COMMIT, "gitlab/master"],
            capture_output=True,
            text=True,
        )
        self.assertEqual(proc.returncode, 0, "远端 master 已无法追溯 Administrator 镜像提交")

    def test_local_dockerfile_preserves_huawei_image(self):
        from_lines = [
            line.strip()
            for line in (ROOT / "Dockerfile").read_text(encoding="utf-8").splitlines()
            if line.startswith("FROM ")
        ]
        self.assertEqual(from_lines, [f"FROM {HUAWEI_IMAGE}"])

    def test_one_open_merge_request_targets_master_at_current_head(self):
        merge_requests = self.api_get(
            f"/projects/{PROJECT_ID}/merge_requests",
            {
                "state": "opened",
                "source_branch": SOURCE_BRANCH,
                "target_branch": TARGET_BRANCH,
                "per_page": 100,
            },
        )
        self.assertEqual(
            len(merge_requests), 1,
            f"必须且只能有一个开放的 {SOURCE_BRANCH} → master MR",
        )
        mr = merge_requests[0]
        self.assertEqual(mr["sha"], git("rev-parse", "HEAD"))
        self.assertEqual(mr["target_branch"], TARGET_BRANCH)
        self.assertEqual(mr["source_branch"], SOURCE_BRANCH)
        self.assertNotIn(mr.get("detailed_merge_status"), {"conflict", "cannot_be_merged"})

    def test_merge_request_metadata_and_description_are_complete(self):
        merge_requests = self.api_get(
            f"/projects/{PROJECT_ID}/merge_requests",
            {
                "state": "opened",
                "source_branch": SOURCE_BRANCH,
                "target_branch": TARGET_BRANCH,
                "per_page": 100,
            },
        )
        self.assertEqual(len(merge_requests), 1)
        mr = self.api_get(f"/projects/{PROJECT_ID}/merge_requests/{merge_requests[0]['iid']}")
        reviewer_ids = {item["id"] for item in mr.get("reviewers", [])}
        assignee_ids = {item["id"] for item in mr.get("assignees", [])}
        self.assertIn(REVIEWER_ID, reviewer_ids)
        self.assertIn(ASSIGNEE_ID, assignee_ids)

        title = str(mr.get("title") or "").strip().lower()
        source = SOURCE_BRANCH.lower()
        self.assertNotIn(title, {f"{source} → master", f"merge {source} into master"})
        self.assertGreaterEqual(len(title), 12)

        description = str(mr.get("description") or "").lower()
        for required in ("master", "tianzijing", "测试", "不自动部署"):
            self.assertIn(required, description)

    def test_delivery_does_not_prematurely_change_default_branch(self):
        project = self.api_get(f"/projects/{PROJECT_ID}")
        self.assertEqual(
            project.get("default_branch"),
            "main",
            "MR review/merge 前不得提前切换默认分支",
        )


if __name__ == "__main__":
    unittest.main()
