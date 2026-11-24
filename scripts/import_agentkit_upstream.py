#!/usr/bin/env python3
"""Import selected AgentKit UI sources from the pinned upstream commit.

The workbench UI in this repository is assembled locally, but its interaction
and visual conventions come from AgentKit.  Upstream lives on GitLab and this
repo consumes it as **source at a fixed commit**, one explicit file at a time
(see docs/specs/workbench-agentkit-ontology-consumption.md §2.1).

``git archive --remote`` only accepts a ref name, never a raw SHA, so the
archive header commit is verified against the pin before anything is written.
If upstream ``dev`` has moved, this script fails loudly instead of importing a
different revision.

Usage:
  python scripts/import_agentkit_upstream.py --check   # verify only
  python scripts/import_agentkit_upstream.py           # import + write UPSTREAM.md
"""

from __future__ import annotations

import argparse
import hashlib
import io
import shutil
import subprocess
import sys
import tarfile
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUTPUT_DIR = ROOT / "frontend" / "agentkit" / "upstream"
RECORD = ROOT / "frontend" / "agentkit" / "UPSTREAM.md"

UPSTREAM_REMOTE = "git@gitlab.boulderaitech.com:ai-team/spzn-agentkit.git"
UPSTREAM_REF = "dev"
PINNED_COMMIT = "b8df86dfa3c30de6676cd1d768cda504bf3c3338"

# Registry entries and component sources the workbench currently leans on.
FILES = (
    "agentkit-ui/public/r/registry.json",
    "agentkit-ui/public/r/aui-thread.json",
    "agentkit-ui/public/r/aui-thread-list.json",
    "agentkit-ui/public/r/confirm-dialog.json",
    "agentkit-ui/src/components/assistant-ui/elements/thread.aui.tsx",
    "agentkit-ui/src/components/assistant-ui/elements/thread-list.aui.tsx",
    "agentkit-ui/src/components/assistant-ui/elements/tool-group.aui.tsx",
    "agentkit-ui/src/components/assistant-ui/elements/tool-call.tsx",
    "agentkit-ui/src/components/assistant-ui/elements/markdown-text.tsx",
)


def _archive() -> bytes:
    completed = subprocess.run(
        ["git", "archive", f"--remote={UPSTREAM_REMOTE}", UPSTREAM_REF, *FILES],
        capture_output=True,
        check=False,
    )
    if completed.returncode != 0:
        raise SystemExit(
            "git archive failed:\n" + completed.stderr.decode("utf-8", "replace")
        )
    return completed.stdout


def _archive_commit(archive: bytes) -> str:
    completed = subprocess.run(
        ["git", "get-tar-commit-id"],
        input=archive,
        capture_output=True,
        check=False,
    )
    if completed.returncode != 0:
        raise SystemExit(
            "git get-tar-commit-id failed:\n" + completed.stderr.decode("utf-8", "replace")
        )
    return completed.stdout.decode("utf-8").strip()


def _verify(archive: bytes) -> str:
    actual = _archive_commit(archive)
    if actual != PINNED_COMMIT:
        raise SystemExit(
            "AgentKit source commit mismatch: "
            f"expected {PINNED_COMMIT}, archived {actual or '<unknown>'}.\n"
            f"Pin the workbench to a new commit (and record it in "
            f"frontend/agentkit/UPSTREAM.md) before importing."
        )
    return actual


def _extract(archive: bytes) -> dict[str, bytes]:
    wanted = {f"{name}" for name in FILES}
    extracted: dict[str, bytes] = {}
    with tarfile.open(fileobj=io.BytesIO(archive), mode="r:") as tar:
        for member in tar.getmembers():
            if not member.isfile():
                continue
            name = member.name.lstrip("./")
            if name not in wanted:
                continue
            handle = tar.extractfile(member)
            if handle is None:
                continue
            extracted[name] = handle.read()
    missing = sorted(wanted - set(extracted))
    if missing:
        raise SystemExit("archive is missing requested files: " + ", ".join(missing))
    return extracted


def _write_record(commit: str, files: dict[str, bytes]) -> None:
    rows = []
    for name in FILES:
        payload = files[name]
        digest = hashlib.sha256(payload).hexdigest()
        rows.append(f"| `{name}` | {len(payload)} | `{digest}` |")
    stamp = datetime.now(timezone.utc).astimezone().strftime("%Y-%m-%d %H:%M %z")
    RECORD.write_text(
        "# AgentKit 上游来源记录\n\n"
        "本体消费展示工作台（`/workbench-agentkit`）复用 AgentKit 的组件与交互规范，\n"
        "按**固定提交、按文件**从上游导入源码。日常构建只读本仓文件，升级时重新执行\n"
        "`python scripts/import_agentkit_upstream.py`（先 `--check`）。\n\n"
        f"- 上游仓库：`{UPSTREAM_REMOTE}`\n"
        f"- 固定提交：`{commit}`（当前对应 `{UPSTREAM_REF}`）\n"
        f"- 导入时间：{stamp}\n"
        "- 导入方式：`git archive --remote` + `git get-tar-commit-id` 校验提交\n\n"
        "## 导入文件\n\n"
        "| 上游路径 | 字节 | sha256 |\n| --- | --- | --- |\n"
        + "\n".join(rows)
        + "\n\n## 本仓适配\n\n"
        "| 上游对象 | 本仓落点 | 说明 |\n| --- | --- | --- |\n"
        "| `agentkit-ui/public/r/aui-thread.json` | `frontend/agentkit/components/Thread.jsx` | "
        "消息流、工具分组、状态与澄清卡的交互顺序；本仓渲染分析结果与证据 |\n"
        "| `agentkit-ui/public/r/aui-thread-list.json` | `frontend/agentkit/components/SessionList.jsx` | "
        "会话列表的视觉与新建/切换行为，接本仓 `/api/conversations` |\n"
        "| `agentkit-ui/src/components/assistant-ui/elements/thread.aui.tsx` | "
        "`frontend/agentkit/state.js` | SSE → 单一会话状态的投影（同轮合并、迟到丢弃、终态幂等）|\n"
        "| `agentkit-ui/src/components/assistant-ui/elements/tool-group.aui.tsx` | "
        "`frontend/agentkit/components/Thread.jsx` | 工具调用折叠组与运行状态 |\n"
        "| `agentkit-ui/public/r/confirm-dialog.json` | `frontend/agentkit/components/HandoffBanner.jsx` | "
        "交接校验失败时的确认与返回入口 |\n\n"
        "上游源码原样保存在 `frontend/agentkit/upstream/`，不做本仓改写；\n"
        "适配逻辑留在 `frontend/agentkit/` 的本地模块里，便于升级时逐文件对照。\n",
        encoding="utf-8",
    )
    print(f"wrote {RECORD.relative_to(ROOT)}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true", help="verify the pinned commit only")
    args = parser.parse_args(argv)

    archive = _archive()
    commit = _verify(archive)
    files = _extract(archive)
    print(f"AgentKit archive commit {commit} matches the pin ({len(files)} files)")

    if args.check:
        return 0

    if OUTPUT_DIR.exists():
        shutil.rmtree(OUTPUT_DIR)
    for name, payload in files.items():
        target = OUTPUT_DIR / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(payload)
    _write_record(commit, files)
    return 0


if __name__ == "__main__":
    sys.exit(main())
