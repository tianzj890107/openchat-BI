"""Behavioral tests for scripts/push_dual_remotes.py.

The tests use temporary working trees and local bare remotes only — never a
real remote, never user data.  Local bare remotes run with
`--allow-local-remotes`; the GitHub URL validation is exercised separately
with fake SSH URLs (validation happens before any network access).
"""

import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
SCRIPT = REPO / "scripts" / "push_dual_remotes.py"


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


class DualRemotePushTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.mkdtemp(prefix="openchat-bi-dual-")
        self.base = Path(self.tmp)
        self.origin_bare = self.base / "origin.git"
        self.personal_bare = self.base / "personal.git"
        for bare in (self.origin_bare, self.personal_bare):
            git(self.base, "init", "--bare", str(bare))
        # Clone a working repo from origin and create the dev branch.
        self.work = self.base / "work"
        git(self.base, "clone", str(self.origin_bare), str(self.work))
        git(self.work, "checkout", "-b", "20260727")
        git(self.work, "config", "user.name", "Test User")
        git(self.work, "config", "user.email", "test@example.com")
        (self.work / "README.md").write_text("openchat-BI test\n", encoding="utf-8")
        git(self.work, "add", "README.md")
        git(self.work, "commit", "-m", "init")
        git(self.work, "remote", "add", "personal", str(self.personal_bare))

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

    def test_dual_push_success_and_three_hashes_match(self) -> None:
        """Normal dual push: HEAD == origin/20260727 == personal/main."""
        proc = self.run_script("--allow-local-remotes")
        self.assertEqual(proc.returncode, 0, proc.stderr)
        head = self.head()
        self.assertEqual(self.remote_sha("origin", "refs/heads/20260727"), head)
        self.assertEqual(self.remote_sha("personal", "refs/heads/main"), head)
        self.assertIn("双远端推送成功", proc.stdout)

    def test_check_mode_pushes_nothing(self) -> None:
        """--check inspects without pushing; remotes stay unchanged."""
        before_origin = git(self.work, "ls-remote", "origin", "refs/heads/20260727")
        before_personal = git(self.work, "ls-remote", "personal", "refs/heads/main")
        proc = self.run_script("--check", "--allow-local-remotes")
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertIn("未执行任何 push", proc.stdout)
        self.assertEqual(git(self.work, "ls-remote", "origin", "refs/heads/20260727"), before_origin)
        self.assertEqual(git(self.work, "ls-remote", "personal", "refs/heads/main"), before_personal)

    def test_first_push_creates_personal_main(self) -> None:
        """personal/main missing on first push is created, not rejected."""
        self.assertEqual(git(self.work, "ls-remote", "personal", "refs/heads/main"), "")
        proc = self.run_script("--allow-local-remotes")
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertEqual(self.remote_sha("personal", "refs/heads/main"), self.head())

    def test_rerun_is_idempotent(self) -> None:
        """A second identical push succeeds without changes."""
        self.assertEqual(self.run_script("--allow-local-remotes").returncode, 0)
        proc = self.run_script("--allow-local-remotes")
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertEqual(self.remote_sha("origin", "refs/heads/20260727"), self.head())
        self.assertEqual(self.remote_sha("personal", "refs/heads/main"), self.head())

    def test_dirty_worktree_rejected(self) -> None:
        (self.work / "uncommitted.txt").write_text("dirty\n", encoding="utf-8")
        proc = self.run_script("--allow-local-remotes")
        self.assertEqual(proc.returncode, 2)
        self.assertIn("未提交修改", proc.stderr)
        # Nothing was pushed.
        self.assertEqual(git(self.work, "ls-remote", "origin", "refs/heads/20260727"), "")
        self.assertEqual(git(self.work, "ls-remote", "personal", "refs/heads/main"), "")

    def test_detached_head_rejected(self) -> None:
        git(self.work, "checkout", "--detach")
        proc = self.run_script("--allow-local-remotes")
        self.assertEqual(proc.returncode, 2)
        self.assertIn("detached HEAD", proc.stderr)

    def test_missing_personal_remote_rejected(self) -> None:
        git(self.work, "remote", "remove", "personal")
        proc = self.run_script("--allow-local-remotes")
        self.assertEqual(proc.returncode, 2)
        self.assertIn("缺少 remote personal", proc.stderr)

    def test_wrong_remote_url_rejected(self) -> None:
        """A remote pointing at the wrong GitHub repo is refused before any
        network access (GitHub URL validation, no --allow-local-remotes)."""
        git(self.work, "remote", "set-url", "origin", "git@github.com:tianzj890107/openchat-BI.git")
        git(self.work, "remote", "set-url", "personal", "git@github.com:someoneelse/openchat-BI.git")
        proc = self.run_script()
        self.assertEqual(proc.returncode, 2)
        self.assertIn("拒绝继续", proc.stderr)

    def test_personal_divergent_commits_rejected(self) -> None:
        """A personal/main with commits the local repo lacks is never
        overwritten (no force push)."""
        other = self.base / "other"
        git(self.base, "clone", str(self.personal_bare), str(other))
        git(other, "config", "user.name", "Other")
        git(other, "config", "user.email", "other@example.com")
        (other / "other.txt").write_text("other\n", encoding="utf-8")
        git(other, "add", "other.txt")
        git(other, "commit", "-m", "other")
        git(other, "branch", "-M", "main")
        git(other, "push", "origin", "main")
        proc = self.run_script("--allow-local-remotes")
        self.assertEqual(proc.returncode, 2)
        self.assertIn("禁止 force push", proc.stderr)

    def test_origin_divergent_commits_rejected(self) -> None:
        """An origin/20260727 with commits the local repo lacks is refused."""
        other = self.base / "other"
        git(self.base, "clone", str(self.origin_bare), str(other))
        git(other, "config", "user.name", "Other")
        git(other, "config", "user.email", "other@example.com")
        (other / "other.txt").write_text("other\n", encoding="utf-8")
        git(other, "add", "other.txt")
        git(other, "commit", "-m", "other")
        git(other, "push", "origin", "HEAD:refs/heads/20260727")
        proc = self.run_script("--allow-local-remotes")
        self.assertEqual(proc.returncode, 2)
        self.assertIn("禁止 force push", proc.stderr)

    def test_origin_success_personal_failure_keeps_origin(self) -> None:
        """If personal push fails after origin succeeds, origin is NOT rolled
        back and the script reports partial success."""
        git(self.work, "remote", "set-url", "personal", str(self.base / "missing-personal.git"))
        proc = self.run_script("--allow-local-remotes")
        self.assertEqual(proc.returncode, 1)
        self.assertIn("部分成功", proc.stderr)
        self.assertEqual(self.remote_sha("origin", "refs/heads/20260727"), self.head())
        # personal remote is missing entirely: no main ref can exist.
        self.assertFalse(git_ok(self.work, "ls-remote", "personal", "refs/heads/main"))

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
