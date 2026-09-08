"""Behavioral tests for scripts/push_gitlab.py.

The tests use temporary working trees and local bare remotes only — never a
real remote, never user data.  Local bare remotes run with
`--allow-local-remotes`; the GitLab URL validation is exercised separately
with fake SSH URLs (validation happens before any network access).
"""

import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
SCRIPT = REPO / "scripts" / "push_gitlab.py"


def git(repo: Path, *args: str) -> str:
    proc = subprocess.run(
        ["git", "-C", str(repo), *args],
        capture_output=True, text=True, check=True,
    )
    return proc.stdout.strip()


def git_ok(repo: Path, *args: str) -> bool:
    proc = subprocess.run(
        ["git", "-C", str(repo), *args],
        capture_output=True, text=True,
    )
    return proc.returncode == 0


class GitLabPushTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.mkdtemp(prefix="eimosp-ontology-agentic-analytics-gitlab-")
        self.base = Path(self.tmp)
        self.gitlab_bare = self.base / "gitlab.git"
        for bare in (self.gitlab_bare,):
            git(self.base, "init", "--bare", str(bare))
        # Clone a working repo from gitlab and create the dev branch.
        self.work = self.base / "work"
        git(self.base, "clone", str(self.gitlab_bare), str(self.work))
        git(self.work, "checkout", "-b", "20260727")
        git(self.work, "config", "user.name", "Test User")
        git(self.work, "config", "user.email", "test@example.com")
        (self.work / "README.md").write_text("eimosp-ontology-agentic-analytics test\n", encoding="utf-8")
        git(self.work, "add", "README.md")
        git(self.work, "commit", "-m", "init")
        git(self.work, "remote", "rename", "origin", "gitlab")

    def tearDown(self) -> None:
        shutil.rmtree(self.tmp, ignore_errors=True)

    def run_script(self, *args: str) -> subprocess.CompletedProcess:
        return subprocess.run(
            [sys.executable, str(SCRIPT), *args],
            cwd=str(self.work), capture_output=True, text=True,
        )

    def head(self) -> str:
        return git(self.work, "rev-parse", "HEAD")

    def remote_sha(self, remote: str, ref: str) -> str:
        return git(self.work, "ls-remote", remote, ref).split("\t")[0]

    def test_gitlab_push_success_and_hash_match(self) -> None:
        """Normal push: HEAD == gitlab/20260727."""
        proc = self.run_script("--allow-local-remotes")
        self.assertEqual(proc.returncode, 0, proc.stderr)
        head = self.head()
        self.assertEqual(self.remote_sha("gitlab", "refs/heads/20260727"), head)
        self.assertIn("GitLab 统一推送成功", proc.stdout)

    def test_check_mode_pushes_nothing(self) -> None:
        """--check inspects without pushing; remote stays unchanged."""
        before_gitlab = git(self.work, "ls-remote", "gitlab", "refs/heads/20260727")
        proc = self.run_script("--check", "--allow-local-remotes")
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertIn("未执行任何 push", proc.stdout)
        self.assertEqual(git(self.work, "ls-remote", "gitlab", "refs/heads/20260727"), before_gitlab)

    def test_first_push_creates_gitlab_dev_branch(self) -> None:
        """gitlab/20260727 missing on first push is created, not rejected."""
        self.assertEqual(git(self.work, "ls-remote", "gitlab", "refs/heads/20260727"), "")
        proc = self.run_script("--allow-local-remotes")
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertEqual(self.remote_sha("gitlab", "refs/heads/20260727"), self.head())

    def test_rerun_is_idempotent(self) -> None:
        """A second identical push succeeds without changes."""
        self.assertEqual(self.run_script("--allow-local-remotes").returncode, 0)
        proc = self.run_script("--allow-local-remotes")
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertEqual(self.remote_sha("gitlab", "refs/heads/20260727"), self.head())

    def test_dirty_worktree_rejected(self) -> None:
        (self.work / "uncommitted.txt").write_text("dirty\n", encoding="utf-8")
        proc = self.run_script("--allow-local-remotes")
        self.assertEqual(proc.returncode, 2)
        self.assertIn("未提交修改", proc.stderr)
        # Nothing was pushed.
        self.assertEqual(git(self.work, "ls-remote", "gitlab", "refs/heads/20260727"), "")

    def test_detached_head_rejected(self) -> None:
        git(self.work, "checkout", "--detach")
        proc = self.run_script("--allow-local-remotes")
        self.assertEqual(proc.returncode, 2)
        self.assertIn("detached HEAD", proc.stderr)

    def test_missing_gitlab_remote_rejected(self) -> None:
        git(self.work, "remote", "remove", "gitlab")
        proc = self.run_script("--allow-local-remotes")
        self.assertEqual(proc.returncode, 2)
        self.assertIn("缺少 remote gitlab", proc.stderr)

    def test_wrong_remote_url_rejected(self) -> None:
        """A remote pointing at the wrong GitLab repo is refused before any
        network access (GitLab URL validation, no --allow-local-remotes)."""
        git(self.work, "remote", "set-url", "gitlab",
            "git@gitlab.boulderaitech.com:someoneelse/eimosp-ontology-agentic-analytics.git")
        proc = self.run_script()
        self.assertEqual(proc.returncode, 2)
        self.assertIn("拒绝继续", proc.stderr)

    def test_gitlab_divergent_commits_rejected(self) -> None:
        """A gitlab/20260727 with commits the local repo lacks is never
        overwritten (no force push)."""
        other = self.base / "other"
        git(self.base, "clone", str(self.gitlab_bare), str(other))
        git(other, "config", "user.name", "Other")
        git(other, "config", "user.email", "other@example.com")
        (other / "other.txt").write_text("other\n", encoding="utf-8")
        git(other, "add", "other.txt")
        git(other, "commit", "-m", "other")
        git(other, "push", "origin", "HEAD:refs/heads/20260727")
        proc = self.run_script("--allow-local-remotes")
        self.assertEqual(proc.returncode, 2)
        self.assertIn("禁止 force push", proc.stderr)

    def test_retired_main_target_cannot_be_recreated(self) -> None:
        """The deleted main branch is never recreated by the push helper."""
        proc = self.run_script("--allow-local-remotes", "--target-branch", "main")
        self.assertEqual(proc.returncode, 2)
        self.assertIn("已退役并删除", proc.stderr)
        self.assertIn("禁止重新创建", proc.stderr)
        # Nothing was pushed to main.
        self.assertEqual(git(self.work, "ls-remote", "gitlab", "refs/heads/main"), "")

    def test_master_target_requires_reviewer(self) -> None:
        """Pushing to master is refused; master merges need review."""
        proc = self.run_script("--allow-local-remotes", "--target-branch", "master")
        self.assertEqual(proc.returncode, 2)
        self.assertIn("tianzijing", proc.stderr)
        self.assertIn("唯一发布主线 master", proc.stderr)
        self.assertIn("不执行 master 合并", proc.stderr)
        self.assertEqual(git(self.work, "ls-remote", "gitlab", "refs/heads/master"), "")

    def test_arbitrary_non_development_target_is_rejected(self) -> None:
        """The helper can only push the unified 20260727 development ref."""
        proc = self.run_script("--allow-local-remotes", "--target-branch", "feature/other")
        self.assertEqual(proc.returncode, 2)
        self.assertIn("只允许推送", proc.stderr)
        self.assertEqual(git(self.work, "ls-remote", "gitlab", "refs/heads/feature/other"), "")

    def test_no_force_push_in_push_command(self) -> None:
        """The script's push invocation never uses --force."""
        src = SCRIPT.read_text(encoding="utf-8")
        push_line = next(
            line.strip() for line in src.splitlines()
            if '["push", remote_name,' in line
        )
        self.assertNotIn("--force", push_line)


if __name__ == "__main__":
    unittest.main()
