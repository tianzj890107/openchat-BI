"""Opt-in read-only acceptance for retirement of the remote main branch."""

from __future__ import annotations

import json
import os
import subprocess
import unittest
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PROJECT_ID = "1065"
API_BASE = "http://gitlab.boulderaitech.com/api/v4"
OLD_MAIN_COMMIT = "4c20b6f798568598d7480ea4ac19e83ea3700e76"
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


def read_worktree(path: str) -> str:
    """Read the candidate policy under TDD, before any commit or delivery."""
    return (ROOT / path).read_text(encoding="utf-8")


@unittest.skipUnless(
    os.environ.get("RUN_GITLAB_MAIN_DELETION_TESTS") == "1",
    "set RUN_GITLAB_MAIN_DELETION_TESTS=1 for read-only branch retirement acceptance",
)
class MainBranchRetirementTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        token_path = Path.home() / ".config" / "codex" / "gitlab_token"
        if not token_path.is_file():
            raise unittest.SkipTest("GitLab token file is unavailable")
        cls.token = token_path.read_text(encoding="utf-8").strip()
        if not cls.token:
            raise unittest.SkipTest("GitLab token file is empty")
        git("fetch", "gitlab", "master", "20260727", "--quiet")

    @classmethod
    def api_get(cls, path: str, params: dict | None = None):
        query = "?" + urllib.parse.urlencode(params or {}) if params else ""
        request = urllib.request.Request(
            f"{API_BASE}{path}{query}",
            headers={"PRIVATE-TOKEN": cls.token},
        )
        with urllib.request.urlopen(request, timeout=10) as response:
            return json.loads(response.read().decode("utf-8"))

    def test_master_is_default_and_remains_strictly_protected(self):
        project = self.api_get(f"/projects/{PROJECT_ID}")
        self.assertEqual(project.get("default_branch"), "master")
        rules = self.api_get(f"/projects/{PROJECT_ID}/protected_branches")
        by_name = {rule["name"]: rule for rule in rules}
        self.assertIn("master", by_name)
        master = by_name["master"]
        self.assertFalse(master.get("allow_force_push"))
        push = {item["access_level"] for item in master.get("push_access_levels", [])}
        merge = {item["access_level"] for item in master.get("merge_access_levels", [])}
        self.assertTrue(push and min(push) >= MAINTAINER)
        self.assertTrue(merge and min(merge) >= MAINTAINER)

    def test_master_retains_old_main_and_administrator_history(self):
        for commit in (OLD_MAIN_COMMIT, ADMIN_IMAGE_COMMIT):
            result = git("merge-base", "--is-ancestor", commit, "gitlab/master", check=False)
            self.assertEqual(result.returncode, 0, f"master 未保留历史提交 {commit}")

    def test_master_preserves_huawei_base_image(self):
        dockerfile = git("show", "gitlab/master:Dockerfile").stdout
        from_lines = [line.strip() for line in dockerfile.splitlines() if line.startswith("FROM ")]
        self.assertEqual(from_lines, [f"FROM {HUAWEI_IMAGE}"])

    def test_remote_main_branch_is_absent(self):
        remote = git("ls-remote", "gitlab", "refs/heads/main").stdout.strip()
        self.assertEqual(remote, "", "远端 refs/heads/main 仍然存在")
        with self.assertRaises(urllib.error.HTTPError) as caught:
            self.api_get(f"/projects/{PROJECT_ID}/repository/branches/main")
        self.assertEqual(caught.exception.code, 404)

    def test_main_has_no_remaining_protection_rule(self):
        rules = self.api_get(f"/projects/{PROJECT_ID}/protected_branches")
        self.assertNotIn("main", {rule["name"] for rule in rules})

    def test_no_open_merge_request_uses_retired_main(self):
        merge_requests = self.api_get(
            f"/projects/{PROJECT_ID}/merge_requests",
            {"state": "opened", "per_page": 100},
        )
        offenders = [
            mr["iid"] for mr in merge_requests
            if mr.get("source_branch") == "main" or mr.get("target_branch") == "main"
        ]
        self.assertEqual(offenders, [])

    def test_master_rules_record_main_as_deleted_not_retained(self):
        active_files = (
            "AGENTS.md",
            "docs/gitlab-push-workflow.md",
            "docs/versions/versioning-policy.md",
            "DEPLOYMENT.md",
        )
        for path in active_files:
            with self.subTest(path=path):
                text = read_worktree(path)
                self.assertIn("`main` 已退役并删除", text)
                self.assertNotIn("`main` 是历史保留分支", text)
                self.assertNotIn("`main` 仅作为历史保留分支", text)

    def test_push_script_forbids_recreating_main(self):
        script = read_worktree("scripts/push_gitlab.py")
        self.assertIn('RETIRED_BRANCH = "main"', script)
        self.assertIn("已退役并删除", script)
        self.assertNotIn('HISTORICAL_BRANCH = "main"', script)


if __name__ == "__main__":
    unittest.main()
