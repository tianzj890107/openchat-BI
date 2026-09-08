#!/usr/bin/env python3
"""Push the same local HEAD to the unified GitLab development branch.

Unified GitLab workflow:

- gitlab          -> ai-team/eimosp-ontology-agentic-analytics   (branch 20260727)
- master is the sole release mainline; merges into master go through merge
  requests reviewed by tianzijing and assigned to zhangzhen.  This script
  never pushes to master or the retained historical main branch and never
  auto-merges.

Usage:
    python scripts/push_gitlab.py [--check]
    python scripts/push_gitlab.py --source-branch 20260727 \
        --target-branch 20260727

--check only inspects configuration and remote hashes without pushing.
"""

import argparse
import re
import subprocess
import sys
from pathlib import Path

GITLAB_HOST = "gitlab.boulderaitech.com"
GITLAB_OWNER_REPO = "ai-team/eimosp-ontology-agentic-analytics"
DEFAULT_SOURCE_BRANCH = "20260727"
DEFAULT_TARGET_BRANCH = "20260727"
RELEASE_BRANCH = "master"
HISTORICAL_BRANCH = "main"
REVIEWER = "tianzijing"


class PushError(RuntimeError):
    pass


def run_git(args, check=True, capture=True):
    cmd = ["git"] + args
    proc = subprocess.run(cmd, capture_output=capture, text=True)
    if check and proc.returncode != 0:
        raise PushError(
            "git %s failed: %s" % (" ".join(args), (proc.stderr or proc.stdout or "").strip())
        )
    return proc


def git_root():
    proc = run_git(["rev-parse", "--show-toplevel"])
    return Path(proc.stdout.strip())


def current_branch():
    proc = run_git(["symbolic-ref", "--quiet", "--short", "HEAD"], check=False)
    if proc.returncode != 0:
        return ""
    return proc.stdout.strip()


def remote_url(name):
    proc = run_git(["remote", "get-url", name])
    return proc.stdout.strip()


def parse_owner_repo(url):
    """Return (owner, repo) for GitLab SSH/HTTPS URLs, or None."""
    url = url.strip().rstrip("/")
    ssh = re.match(r"^git@%s:([^/]+)/(.+?)(?:\.git)?$" % re.escape(GITLAB_HOST), url)
    if ssh:
        return ssh.group(1), ssh.group(2).removesuffix(".git")
    https = re.match(r"^https?://%s/([^/]+)/(.+?)(?:\.git)?$" % re.escape(GITLAB_HOST), url)
    if https:
        return https.group(1), https.group(2).removesuffix(".git")
    return None


def verify_remote(remote_name, expected_owner_repo, allow_local):
    url = remote_url(remote_name)
    if allow_local:
        return url
    parsed = parse_owner_repo(url)
    if parsed is None:
        raise PushError(
            "remote %s URL %r 无法识别为 GitLab 仓库；预期 %s"
            % (remote_name, url, expected_owner_repo)
        )
    actual = "%s/%s" % parsed
    if actual != expected_owner_repo:
        raise PushError(
            "remote %s 指向 %r，预期 %r；拒绝继续" % (remote_name, actual, expected_owner_repo)
        )
    return url


def worktree_clean():
    proc = run_git(["status", "--porcelain"])
    return not proc.stdout.strip()


def remote_sha(remote_name, ref):
    proc = run_git(["ls-remote", remote_name, ref], check=False)
    if proc.returncode != 0:
        raise PushError(
            "无法读取 remote %s：%s" % (remote_name, (proc.stderr or "").strip())
        )
    for line in proc.stdout.splitlines():
        parts = line.split("\t")
        if len(parts) == 2 and parts[1] == ref:
            return parts[0]
    return None


def is_ancestor(ancestor, descendant):
    proc = run_git(
        ["merge-base", "--is-ancestor", ancestor, descendant], check=False
    )
    return proc.returncode == 0


def verify_remote_state(remote_name, remote_sha_value, head_sha):
    if remote_sha_value is None:
        return "missing"
    if remote_sha_value == head_sha:
        return "equal"
    if is_ancestor(remote_sha_value, head_sha):
        return "ancestor"
    raise PushError(
        "remote %s 存在本地没有的提交 %s；禁止 force push 或自动合并，拒绝 push"
        % (remote_name, remote_sha_value[:12])
    )


def do_push(remote_name, head_sha, branch):
    proc = run_git(
        ["push", remote_name, "%s:refs/heads/%s" % (head_sha, branch)],
        check=False,
    )
    if proc.returncode != 0:
        raise PushError(
            "push 到 %s/%s 失败：%s"
            % (remote_name, branch, (proc.stderr or proc.stdout or "").strip())
        )
    return proc.stdout + proc.stderr


def main(argv=None):
    parser = argparse.ArgumentParser(description="GitLab unified dev-branch push")
    parser.add_argument("--check", action="store_true", help="只检查，不推送")
    parser.add_argument("--source-branch", default=DEFAULT_SOURCE_BRANCH)
    parser.add_argument("--target-branch", default=DEFAULT_TARGET_BRANCH)
    parser.add_argument(
        "--allow-local-remotes",
        action="store_true",
        help="测试专用：跳过 GitLab 仓库 URL 校验（允许本地 bare remote）",
    )
    args = parser.parse_args(argv)

    # 1. Must be a git repository.
    try:
        root = git_root()
    except PushError as exc:
        print("错误：当前目录不是 Git 仓库。", file=sys.stderr)
        print(str(exc), file=sys.stderr)
        return 2

    # 2. Current branch; reject detached HEAD.
    branch = current_branch()
    if not branch:
        print("错误：当前处于 detached HEAD，拒绝 push。", file=sys.stderr)
        return 2

    # 3. Default requires the current development branch.
    if branch != args.source_branch:
        print(
            "错误：当前分支 %s 不是预期开发分支 %s；拒绝 push。"
            % (branch, args.source_branch),
            file=sys.stderr,
        )
        return 2

    # 3b. This helper can only push the unified development branch.
    #     master is the sole release mainline; main is a retained historical
    #     branch.  Neither may be pushed directly, and this check happens
    #     before any remote read or push.
    if args.target_branch != DEFAULT_TARGET_BRANCH:
        if args.target_branch == RELEASE_BRANCH:
            print(
                "错误：目标分支 %s 是唯一发布主线 master；merge 到 master 必须由 %s "
                "code review 后单独发起 Merge Request，本脚本只推送统一开发分支 %s，"
                "不执行 master 合并。"
                % (args.target_branch, REVIEWER, DEFAULT_TARGET_BRANCH),
                file=sys.stderr,
            )
        elif args.target_branch == HISTORICAL_BRANCH:
            print(
                "错误：目标分支 %s 是历史保留分支，不接受新功能；本脚本只允许推送统一"
                "开发分支 %s。"
                % (args.target_branch, DEFAULT_TARGET_BRANCH),
                file=sys.stderr,
            )
        else:
            print(
                "错误：目标分支 %s 不允许；本脚本只允许推送统一开发分支 %s。"
                % (args.target_branch, DEFAULT_TARGET_BRANCH),
                file=sys.stderr,
            )
        return 2

    # 4. gitlab remote must exist.
    try:
        gitlab_url = remote_url("gitlab")
    except PushError:
        print("错误：缺少 remote gitlab；无法执行 GitLab 统一推送。", file=sys.stderr)
        return 2

    # 5. URL mapping must match ai-team/eimosp-ontology-agentic-analytics.
    try:
        gitlab_url = verify_remote("gitlab", GITLAB_OWNER_REPO, args.allow_local_remotes)
    except PushError as exc:
        print("错误：%s" % exc, file=sys.stderr)
        return 2

    # 6. Working tree must be clean (no uncommitted changes).
    if not worktree_clean():
        print("错误：工作区存在未提交修改，拒绝 push。", file=sys.stderr)
        return 2

    # 7. Local HEAD.
    head_sha = run_git(["rev-parse", "HEAD"]).stdout.strip()

    # 8. Read remote target ref and validate ancestry.
    target_ref = "refs/heads/%s" % args.target_branch
    gitlab_unreachable = None
    try:
        gitlab_sha = remote_sha("gitlab", target_ref)
    except PushError as exc:
        gitlab_unreachable = exc

    if gitlab_unreachable:
        print("错误：无法读取 gitlab：%s" % gitlab_unreachable, file=sys.stderr)
        print("无法确认 gitlab 状态，GitLab 统一推送未执行。", file=sys.stderr)
        return 2

    try:
        gitlab_state = verify_remote_state("gitlab", gitlab_sha, head_sha)
    except PushError as exc:
        print("错误：%s" % exc, file=sys.stderr)
        return 2

    print("本地 HEAD: %s" % head_sha)
    print("gitlab (%s) %s: %s (%s)" % (gitlab_url, target_ref, gitlab_sha or "(缺失)", gitlab_state))

    if args.check:
        print("--check：未执行任何 push。")
        return 0

    # 9. Push to gitlab/<target-branch>.
    try:
        print("推送到 gitlab/%s ..." % args.target_branch)
        do_push("gitlab", head_sha, args.target_branch)
    except PushError as exc:
        print("错误：%s" % exc, file=sys.stderr)
        print("GitLab 统一推送失败，任务未完成。", file=sys.stderr)
        return 1

    # 10. Post-push verification via ls-remote.
    try:
        new_gitlab_sha = remote_sha("gitlab", target_ref)
    except PushError as exc:
        print("错误：push 后读取 gitlab 失败：%s" % exc, file=sys.stderr)
        return 1
    if new_gitlab_sha != head_sha:
        print(
            "错误：push 后 hash 不一致：HEAD=%s gitlab=%s"
            % (head_sha, new_gitlab_sha or "(缺失)"),
            file=sys.stderr,
        )
        return 1

    print("GitLab 统一推送成功：HEAD == gitlab/%s == %s"
          % (args.target_branch, head_sha))
    print("提示：正式交付通过 Merge Request 由 %s code review 后合入唯一发布主线 "
          "master；本脚本不会自动合并、不会直接 push master。"
          % REVIEWER)
    return 0


if __name__ == "__main__":
    sys.exit(main())
