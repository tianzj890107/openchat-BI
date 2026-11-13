"""Keep one model request (input + output) within a total token budget.

Some gateways cap a request's input plus output tokens (the customer model:
12,000).  When a call runs under ``request_config(context_limit=...)`` the
dispatcher estimates the request, lowers ``max_tokens`` to what is left, and
when the input itself leaves too little room it compresses tool results:
large JSON lists (query rows) are halved and long strings shortened, so the
result stays valid JSON and small identifiers such as evidence ids survive.
System prompt, tool definitions and the user's own text are never changed.
If the request still cannot fit, ``ContextBudgetExceeded`` is raised before
anything is sent.

Token counts are estimates, not the gateway's tokenizer.  The only
measurement available is one customer request: 23.5k characters of mixed
Chinese text and JSON billed as 10.25k input tokens (0.44 per character).
The weights below give about 0.5 per character for a mix that is one third
Chinese, i.e. roughly 15 % above that measurement; text that is almost all
ASCII digits and punctuation can tokenise worse than estimated, so the
dispatcher still reports a gateway context error clearly if it happens.
"""
from __future__ import annotations

import copy
import json
import re
from typing import Any, Optional

_CJK = re.compile(r"[　-〿㐀-鿿豈-﫿＀-￯]")
_MESSAGE_OVERHEAD = 4
_COMPRESSED_MARK = "…[已按上下文预算压缩]"


class ContextBudgetExceeded(RuntimeError):
    """The request does not fit the token budget even after compression."""

    def __init__(self, message, *, estimated_input=0, limit=0, min_output=0):
        super().__init__(message)
        self.estimated_input = estimated_input
        self.limit = limit
        self.min_output = min_output


def estimate_tokens(text: Any) -> int:
    if not isinstance(text, str):
        text = json.dumps(text, ensure_ascii=False, default=str)
    cjk = len(_CJK.findall(text))
    return int(cjk * 0.8 + (len(text) - cjk) / 2.8) + 1


def _message_tokens(message: dict) -> int:
    return estimate_tokens(message.get("content", "")) + _MESSAGE_OVERHEAD


def estimate_request(messages, system_prompt, tool_schemas=()) -> int:
    return (estimate_tokens(system_prompt or "")
            + (estimate_tokens(list(tool_schemas)) if tool_schemas else 0)
            + sum(_message_tokens(message) for message in messages))


def _shrink_json(value, target_chars):
    """Halve the largest list or shorten the longest string; False if nothing left."""
    best = None  # (size, container, key)

    def visit(node):
        nonlocal best
        items = node.items() if isinstance(node, dict) else enumerate(node) if isinstance(node, list) else ()
        for key, child in items:
            if isinstance(child, list) and len(child) > 1:
                size = len(json.dumps(child, ensure_ascii=False, default=str))
                if best is None or size > best[0]:
                    best = (size, node, key)
            elif isinstance(child, str) and len(child) > 200:
                if best is None or len(child) > best[0]:
                    best = (len(child), node, key)
            if isinstance(child, (dict, list)):
                visit(child)

    visit(value)
    if best is None:
        return False
    _, node, key = best
    child = node[key]
    if isinstance(child, list):
        node[key] = child[:max(1, len(child) // 2)]
    else:
        node[key] = child[:max(120, len(child) // 2)] + _COMPRESSED_MARK
    return True


def _shrink_text(text: str, target_chars: int) -> str:
    try:
        value = json.loads(text)
    except (TypeError, ValueError):
        value = None
    if isinstance(value, (dict, list)):
        while len(json.dumps(value, ensure_ascii=False, default=str)) > target_chars:
            if not _shrink_json(value, target_chars):
                break
        return json.dumps(value, ensure_ascii=False, default=str)
    if len(text) <= target_chars:
        return text
    return text[:max(200, target_chars)] + _COMPRESSED_MARK


def _tool_result_slots(messages):
    """(message index, block index or None) of every tool result text."""
    slots = []
    for m_index, message in enumerate(messages):
        content = message.get("content")
        if message.get("role") == "tool" and isinstance(content, str):
            slots.append((m_index, None))
        elif isinstance(content, list):
            for b_index, block in enumerate(content):
                if isinstance(block, dict) and block.get("type") == "tool_result" \
                        and isinstance(block.get("content"), str):
                    slots.append((m_index, b_index))
    return slots


def _get(messages, slot):
    m_index, b_index = slot
    return (messages[m_index]["content"] if b_index is None
            else messages[m_index]["content"][b_index]["content"])


def _set(messages, slot, value):
    m_index, b_index = slot
    if b_index is None:
        messages[m_index]["content"] = value
    else:
        messages[m_index]["content"][b_index]["content"] = value


def fit_request(messages, system_prompt, tool_schemas, *, limit: int, max_tokens: int,
                min_output: int):
    """Return ``(messages, max_tokens, report)`` within ``limit`` or raise.

    ``messages`` is not modified; a compressed copy is returned when needed.
    """
    fixed = estimate_tokens(system_prompt or "") + (
        estimate_tokens(list(tool_schemas)) if tool_schemas else 0)
    estimated = estimate_request(messages, system_prompt, tool_schemas)
    report = dict(limit=limit, estimatedInput=estimated, requestedMaxTokens=max_tokens,
                  compressed=0)
    room = limit - estimated
    if room >= min_output:
        report["maxTokens"] = min(max_tokens, room)
        return messages, report["maxTokens"], report
    work = copy.deepcopy(messages)
    slots = _tool_result_slots(work)
    target_input = limit - min_output
    for _ in range(200):
        current = estimate_request(work, system_prompt, tool_schemas)
        if current <= target_input or not slots:
            break
        # Shrink the largest tool result first, to about two thirds.
        slot = max(slots, key=lambda item: len(_get(work, item)))
        text = _get(work, slot)
        smaller = _shrink_text(text, int(len(text) * 0.66))
        if len(smaller) >= len(text):
            slots.remove(slot)
            continue
        _set(work, slot, smaller)
        report["compressed"] += 1
    estimated = estimate_request(work, system_prompt, tool_schemas)
    report["estimatedInput"] = estimated
    if limit - estimated < min_output:
        raise ContextBudgetExceeded(
            f"上下文超出预算：输入预计 {estimated} token（系统提示词与工具定义 {fixed} token），"
            f"加最少输出 {min_output} token 超过上限 {limit} token；压缩工具结果后仍无法满足，未发送请求",
            estimated_input=estimated, limit=limit, min_output=min_output)
    report["maxTokens"] = min(max_tokens, limit - estimated)
    return work, report["maxTokens"], report


def cockpit_context_limit() -> Optional[int]:
    """Total token budget for cockpit model calls (``None`` disables it).

    The customer gateway allows 12,000 tokens of input plus output per
    request; 11,999 keeps every cockpit call inside it.
    """
    import os
    try:
        value = int(os.environ.get("COCKPIT_MODEL_CONTEXT_TOKENS", "11999"))
    except ValueError:
        value = 11999
    return value if value > 0 else None


def tool_schemas_for(allowed_tools: Optional[list[str]]):
    """The tool definitions a provider would send for ``allowed_tools``."""
    if allowed_tools is not None and not allowed_tools:
        return []
    try:
        from open_claude.tools import get_filtered_tool_schemas
        return get_filtered_tool_schemas(allowed_tools)
    except Exception:  # noqa: BLE001 - estimation only
        return []
