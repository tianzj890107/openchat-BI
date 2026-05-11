"""
AskUser — a "tool" that doesn't actually execute. When the model calls it, the
WebSession intercepts the tool_use, emits a `user_choice_requested` event to
the browser, and pauses the turn. A separate endpoint (`/api/choice`) receives
the user's selection and resumes the conversation by appending a synthetic
tool_result for the deferred AskUser call.

This mechanism supports step-1 (term disambiguation, role confirmation) and
step-2 (metric / drill-down dimension choice) user-in-the-loop flows without
any threading / blocking inside the tool executor.
"""

from __future__ import annotations

from typing import Any, Callable


ASK_USER_TOOL_NAME = "AskUser"

ASK_USER_SCHEMA = {
    "name": ASK_USER_TOOL_NAME,
    "description": (
        "请用户在若干候选项中做出选择,用于消除模糊性。必须在以下三类场景使用:\n"
        "  (A) 术语消歧 — 当问句中的业务术语在本体里有多个候选口径(例如"
        "'客户活跃度'同时对应月活/周活/订单活跃)且无法从上下文唯一确定;\n"
        "  (B) 指标/维度下钻选择 — 当用户请求的指标涉及多个合理的口径"
        "(如'销售额'按订单创建月 vs 发货月)或需要在多个可行维度间挑选;\n"
        "  (C) 角色/视角确认 — 问题的回答视角不明(如'为什么销售下降'"
        "可由销售总监视角或财务分析师视角回答),需要用户先确认。\n"
        "\n"
        "非必要不使用 —— 如果可以自己通过 OntologyQuery/MetricLookup 等工具"
        "确定,直接查本体,不要打扰用户。每个 option 填 id (短英文标识符)、"
        "label (一行中文标签,带关键编码)、detail (一句话解释差异)。\n"
        "\n"
        "前端以复选框形式展示选项(支持多选),用户勾选后点击「确定」提交。\n"
        "工具返回的字符串包含用户勾选的全部 label —— 单选时直接是该 label,\n"
        "多选时形如 `User selected N options: A (id=a)、B (id=b)`。"
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "question": {
                "type": "string",
                "description": "一句话问题,告诉用户需要做什么选择。",
            },
            "options": {
                "type": "array",
                "minItems": 2,
                "maxItems": 8,
                "items": {
                    "type": "object",
                    "properties": {
                        "id": {
                            "type": "string",
                            "description": "候选项的短英文标识,用于回传。",
                        },
                        "label": {
                            "type": "string",
                            "description": "显示给用户的标签(可含本体编码)。",
                        },
                        "detail": {
                            "type": "string",
                            "description": "候选项的差异说明(一行)。",
                        },
                    },
                    "required": ["id", "label"],
                },
                "description": "可选项列表,至少 2 个。",
            },
            "context": {
                "type": "string",
                "description": "一句话说明为什么问这个选择(给用户上下文)。",
            },
        },
        "required": ["question", "options"],
    },
}


def _dummy_executor(params: dict[str, Any], cwd: str) -> str:
    """Never actually invoked — WebSession intercepts AskUser before execution."""
    return (
        "AskUser was not intercepted by the session layer. "
        "This should not happen — check WebSession.generate_turn."
    )


SPECS: list[tuple[dict, Callable[[], Callable]]] = [
    (ASK_USER_SCHEMA, lambda: _dummy_executor),
]
