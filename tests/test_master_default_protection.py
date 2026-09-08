"""Opt-in read-only acceptance for the master default/protection cutover."""

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
ADMIN_IMAGE_COMMIT = "a7ebafaa0097655fdc2d8595e367f0b4adaca47d"
HUAWEI_IMAGE = "swr.cn-east-3.myhuaweicloud.com/release/python:3.13-slim"
MAINTAINER = 40


def git(*args: str, check: bool = True) -> subprocess.CompletedProcess:
    proc = subprocess.run(
        ["git", "-C", str(ROOT), *args],
        capture_output=True,
        text=True,
    )
    if check and proc.returncode != 0:
        raise AssertionError(proc.stderr or proc.stdout)
    return proc


@unittest.skipUnless(
    os.environ.get("RUN_GITLAB_CUTOVER_TESTS") == "1",
    "set RUN_GITLAB_CUTOVER_TESTS=1 for read-only GitLab cutover acceptance",
)
class MasterDefaultProtectionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        token_path = Path.home() / ".config" / "codex" / "gitlab_token"
        if not token_path.is_file():
            raise unittest.SkipTest("GitLab token file is unavailable")
        cls.token = token_path.read_text(encoding="utf-8").strip()
        if not cls.token:
            raise unittest.SkipTest("GitLab token file is empty")
        git("fetch", "gitlab", "main", "master", "--quiet")

    @classmethod
    def api_get(cls, path: str, params: dict | None = None):
        query = "?" + urllib.parse.urlencode(params or {}) if params else ""
        request = urllib.request.Request(
            f"{API_BASE}{path}{query}",
            headers={"PRIVATE-TOKEN": cls.token},
        )
        with urllib.request.urlopen(request, timeout=10) as response:
            return json.loads(response.read().decode("utf-8"))

    def test_main_is_ancestor_of_master_after_topology_sync(self):
        result = git("merge-base", "--is-ancestor", "gitlab/main", "gitlab/master", check=False)
        self.assertEqual(result.returncode, 0, "master 提交拓扑仍未包含 main")

    def test_main_and_master_have_identical_content_tree(self):
        main_tree = git("rev-parse", "gitlab/main^{tree}").stdout.strip()
        master_tree = git("rev-parse", "gitlab/master^{tree}").stdout.strip()
        self.assertEqual(master_tree, main_tree, "同步 MR 不得引入实际内容差异")

    def test_master_preserves_administrator_commit_and_huawei_image(self):
        ancestor = git(
            "merge-base", "--is-ancestor", ADMIN_IMAGE_COMMIT, "gitlab/master",
            check=False,
        )
        self.assertEqual(ancestor.returncode, 0)
        dockerfile = git("show", "gitlab/master:Dockerfile").stdout
        from_lines = [line.strip() for line in dockerfile.splitlines() if line.startswith("FROM ")]
        self.assertEqual(from_lines, [f"FROM {HUAWEI_IMAGE}"])

    def test_gitlab_default_branch_is_master(self):
        project = self.api_get(f"/projects/{PROJECT_ID}")
        self.assertEqual(project.get("default_branch"), "master")

    def test_master_is_protected_at_least_as_strictly_as_old_main(self):
        rules = self.api_get(f"/projects/{PROJECT_ID}/protected_branches")
        by_name = {rule["name"]: rule for rule in rules}
        self.assertIn("master", by_name)
        master = by_name["master"]
        self.assertFalse(master.get("allow_force_push"), "master 必须禁止 force push")
        push_levels = {item["access_level"] for item in master.get("push_access_levels", [])}
        merge_levels = {item["access_level"] for item in master.get("merge_access_levels", [])}
        self.assertTrue(push_levels and min(push_levels) >= MAINTAINER)
        self.assertTrue(merge_levels and min(merge_levels) >= MAINTAINER)

    def test_historical_main_still_exists_and_remains_protected(self):
        branch = self.api_get(f"/projects/{PROJECT_ID}/repository/branches/main")
        self.assertEqual(branch.get("name"), "main")
        self.assertTrue(branch.get("protected"), "历史 main 不得删除或取消保护")

    def test_no_open_merge_request_targets_historical_main(self):
        merge_requests = self.api_get(
            f"/projects/{PROJECT_ID}/merge_requests",
            {"state": "opened", "target_branch": "main", "per_page": 100},
        )
        self.assertEqual(merge_requests, [], "仍有开放 MR 错误指向历史 main")

    def test_main_to_master_sync_mr_is_merged_not_left_open(self):
        opened = self.api_get(
            f"/projects/{PROJECT_ID}/merge_requests",
            {
                "state": "opened",
                "source_branch": "main",
                "target_branch": "master",
                "per_page": 100,
            },
        )
        self.assertEqual(opened, [], "main → master 同步 MR 尚未完成 review/merge")


if __name__ == "__main__":
    unittest.main()
