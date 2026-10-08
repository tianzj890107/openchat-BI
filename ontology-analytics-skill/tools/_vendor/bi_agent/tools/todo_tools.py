"""
Todo / task-list tool — lets the agent maintain a running task checklist that
the Web UI pins to the top of the conversation (Claude-Code style). Mirrors the
TableGenerate convention: the payload is wrapped in <TODO_SPEC>...</TODO_SPEC>
tags inside the tool output, so WebSession can strip + extract it before
feeding the text back to the LLM.

The whole list is overwritten on every call (the agent re-sends the full set
each time, flipping a task's `status` as it progresses), so the frontend just
renders the latest snapshot.
"""

from __future__ import annotations

import json
import re
from typing import Callable

Executor = Callable[[dict, str], str]
ExecutorFactory = Callable[[], Executor]


TODO_SPEC_OPEN = "<TODO_SPEC>"
TODO_SPEC_CLOSE = "</TODO_SPEC>"
TODO_SPEC_RE = re.compile(
    re.escape(TODO_SPEC_OPEN) + r"(.*?)" + re.escape(TODO_SPEC_CLOSE),
    re.DOTALL,
)

ALLOWED_STATUS = ("pending", "in_progress", "completed")
MAX_TODOS = 12


TODO_WRITE_SCHEMA = {
    "name": "TodoWrite",
    "description": (
        "维护本轮分析的任务清单,会被置顶展示给用户(类似 Claude Code 的待办列表)。"
        "用法:在 L2 及以上的多步分析一开始,就先调用一次,把后续步骤拆成 3–6 条任务"
        "(取数 / 下钻 / 交叉验证 / 出图 / 给结论等);之后每推进一步就再调用一次,"
        "把已完成的标 `completed`、正在做的标 `in_progress`(同一时刻最多 1 条 "
        "in_progress)、还没开始的留 `pending`。**每次都要传入完整清单**(整份覆盖,"
        "不是增量)。纯 L1 取数这类一步到位的简单问题不需要用它。任务描述写成业务化的"
        "祈使短句,不要写技术旁白。"
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "todos": {
                "type": "array",
                "minItems": 1,
                "maxItems": MAX_TODOS,
                "description": "完整的任务清单(每次全量传入,顺序即展示顺序)。",
                "items": {
                    "type": "object",
                    "properties": {
                        "content": {
                            "type": "string",
                            "description": (
                                "任务的一句话业务描述(祈使句,如 "
                                "'下钻激光事业部各区域收入')。"
                            ),
                        },
                        "status": {
                            "type": "string",
                            "enum": list(ALLOWED_STATUS),
                            "description": (
                                "pending 未开始 / in_progress 进行中(最多 1 条)/ "
                                "completed 已完成。"
                            ),
                        },
                    },
                    "required": ["content", "status"],
                },
            },
        },
        "required": ["todos"],
    },
}


def _validate(params: dict) -> str | None:
    todos = params.get("todos")
    if not isinstance(todos, list) or not todos:
        return "todos must be a non-empty list"
    if len(todos) > MAX_TODOS:
        return f"todos must be ≤ {MAX_TODOS}"
    for i, t in enumerate(todos):
        if not isinstance(t, dict):
            return f"todo {i} must be an object"
        content = t.get("content")
        if not content or not isinstance(content, str):
            return f"todo {i} needs a string 'content'"
        status = t.get("status")
        if status not in ALLOWED_STATUS:
            return f"todo {i} status must be one of {list(ALLOWED_STATUS)}"
    return None


def _make_todo_write() -> Executor:
    def run(params: dict, cwd: str) -> str:
        err = _validate(params)
        if err:
            return f"TodoWrite rejected: {err}"

        todos = [
            {"content": t["content"].strip(), "status": t["status"]}
            for t in params["todos"]
        ]
        done = sum(1 for t in todos if t["status"] == "completed")
        current = next(
            (t["content"] for t in todos if t["status"] == "in_progress"), ""
        )

        header = f"任务清单已更新 — {done}/{len(todos)} 已完成"
        if current:
            header += f",当前进行中:{current}"
        elif done == len(todos):
            header += ",全部完成"

        return (
            f"{header}\n\n{TODO_SPEC_OPEN}"
            + json.dumps({"todos": todos}, ensure_ascii=False)
            + f"{TODO_SPEC_CLOSE}"
        )

    return run


def extract_todo_spec(tool_output: str) -> tuple[str, dict | None]:
    """Pull the TODO_SPEC block out of a tool output string.

    Returns (cleaned_output, parsed_spec_or_None). The cleaned output has the
    <TODO_SPEC>...</TODO_SPEC> block removed so it can be fed back to the LLM
    without the raw JSON payload.
    """
    m = TODO_SPEC_RE.search(tool_output or "")
    if not m:
        return tool_output, None
    try:
        spec = json.loads(m.group(1))
    except json.JSONDecodeError:
        return tool_output, None
    cleaned = (tool_output[: m.start()] + tool_output[m.end():]).rstrip()
    return cleaned, spec


SPECS: list[tuple[dict, ExecutorFactory]] = [
    (TODO_WRITE_SCHEMA, lambda: _make_todo_write()),
]
