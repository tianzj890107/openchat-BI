"""Qwen provider — DashScope OpenAI-compatible endpoint.

Uses the `openai` SDK with base_url pointing at DashScope. Messages and
tools are converted Anthropic↔OpenAI on the way in; tool_calls streaming
deltas are translated back to the Anthropic event format on the way out.

API key resolution: DASHSCOPE_API_KEY → QWEN_API_KEY → ~/.claude/config.json
key `dashscope_api_key`.
"""

from __future__ import annotations

import json
import os
from typing import Any, Generator, Optional

try:
    from openai import OpenAI  # type: ignore
except Exception:  # pragma: no cover
    OpenAI = None  # type: ignore

from open_claude.tools import get_filtered_tool_schemas


DEFAULT_BASE_URL = "https://dashscope.aliyuncs.com/compatible-mode/v1"


# ---------------------------------------------------------------------------
# Key / client
# ---------------------------------------------------------------------------

def _get_api_key() -> Optional[str]:
    for env in ("DASHSCOPE_API_KEY", "QWEN_API_KEY"):
        v = os.environ.get(env)
        if v:
            return v
    try:
        from open_claude.config import load_config
        cfg = load_config()
        for k in ("dashscope_api_key", "qwen_api_key"):
            if cfg.get(k):
                return cfg[k]
    except Exception:
        pass
    return None


def _get_base_url() -> str:
    """Return a DashScope-compatible endpoint, allowing private gateways."""
    return os.environ.get("QWEN_BASE_URL", DEFAULT_BASE_URL).rstrip("/")


def _enable_thinking() -> Optional[bool]:
    """Map QWEN_ENABLE_THINKING to DashScope's compatible API option."""
    value = os.environ.get("QWEN_ENABLE_THINKING")
    if value is None or not value.strip():
        return None
    return value.strip().lower() in {"1", "true", "yes", "on"}


# ---------------------------------------------------------------------------
# Message / tool conversion
# ---------------------------------------------------------------------------

def _convert_tools(allowed_tools: Optional[list[str]]) -> list[dict[str, Any]]:
    schemas = get_filtered_tool_schemas(allowed_tools)
    return [
        {
            "type": "function",
            "function": {
                "name": s["name"],
                "description": s.get("description", ""),
                "parameters": s["input_schema"],
            },
        }
        for s in schemas
    ]


def _block_text(content: Any) -> str:
    """Flatten a tool_result content payload to plain text."""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        out = []
        for b in content:
            if isinstance(b, dict) and b.get("type") == "text":
                out.append(b.get("text", ""))
            elif isinstance(b, str):
                out.append(b)
        return "".join(out)
    return str(content)


def _convert_messages(
    messages: list[dict[str, Any]],
    system_prompt: str,
) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = [{"role": "system", "content": system_prompt}]
    for msg in messages:
        role = msg.get("role")
        content = msg.get("content")

        if isinstance(content, str):
            out.append({"role": role, "content": content})
            continue

        if not isinstance(content, list):
            continue

        if role == "assistant":
            text_parts: list[str] = []
            tool_calls: list[dict[str, Any]] = []
            for blk in content:
                bt = blk.get("type")
                if bt == "text":
                    text_parts.append(blk.get("text", ""))
                elif bt == "tool_use":
                    tool_calls.append({
                        "id": blk["id"],
                        "type": "function",
                        "function": {
                            "name": blk["name"],
                            "arguments": json.dumps(blk.get("input", {}), ensure_ascii=False),
                        },
                    })
            assistant_msg: dict[str, Any] = {"role": "assistant"}
            text_joined = "".join(text_parts)
            assistant_msg["content"] = text_joined if text_joined else None
            if tool_calls:
                assistant_msg["tool_calls"] = tool_calls
            out.append(assistant_msg)

        elif role == "user":
            # tool_results → one OpenAI "tool" message each
            # text blocks → merged into a single user message
            text_parts: list[str] = []
            for blk in content:
                bt = blk.get("type")
                if bt == "tool_result":
                    out.append({
                        "role": "tool",
                        "tool_call_id": blk.get("tool_use_id"),
                        "content": _block_text(blk.get("content", "")),
                    })
                elif bt == "text":
                    text_parts.append(blk.get("text", ""))
            if text_parts:
                out.append({"role": "user", "content": "".join(text_parts)})

    return out


FINISH_MAP = {
    "stop": "end_turn",
    "tool_calls": "tool_use",
    "length": "max_tokens",
    "content_filter": "end_turn",
}


# ---------------------------------------------------------------------------
# Stream
# ---------------------------------------------------------------------------

def stream(
    *,
    model_id: str,
    messages: list[dict[str, Any]],
    system_prompt: str,
    allowed_tools: Optional[list[str]],
    max_tokens: int,
    temperature: float,
) -> Generator[dict[str, Any], None, None]:
    if OpenAI is None:
        yield {
            "type": "error",
            "error": "The 'openai' package is not installed. Run: pip install 'openai>=1.40.0'",
        }
        return

    api_key = _get_api_key()
    if not api_key:
        yield {
            "type": "error",
            "error": (
                "No DashScope API key. Set DASHSCOPE_API_KEY env var, or add "
                "'dashscope_api_key' to ~/.claude/config.json."
            ),
        }
        return

    try:
        client = OpenAI(api_key=api_key, base_url=_get_base_url())
    except Exception as e:
        yield {"type": "error", "error": f"Failed to init Qwen client: {e}"}
        return

    try:
        oa_messages = _convert_messages(messages, system_prompt)
        oa_tools = _convert_tools(allowed_tools)
    except Exception as e:
        yield {"type": "error", "error": f"Message conversion failed: {e}"}
        return

    request_kwargs: dict[str, Any] = dict(
        model=model_id,
        messages=oa_messages,
        max_tokens=max_tokens,
        temperature=temperature,
        stream=True,
        stream_options={"include_usage": True},
    )
    if oa_tools:
        request_kwargs["tools"] = oa_tools
        request_kwargs["tool_choice"] = "auto"
    enable_thinking = _enable_thinking()
    if enable_thinking is not None:
        request_kwargs["extra_body"] = {"enable_thinking": enable_thinking}

    try:
        completion_stream = client.chat.completions.create(**request_kwargs)
    except Exception as e:
        yield {"type": "error", "error": f"Qwen request failed: {e}"}
        return

    # Per-index state for streaming tool_calls
    tc_state: dict[int, dict[str, Any]] = {}
    stop_reason = "end_turn"
    usage = {"input_tokens": 0, "output_tokens": 0}

    try:
        for chunk in completion_stream:
            # Some chunks (final) carry only usage
            chunk_usage = getattr(chunk, "usage", None)
            if chunk_usage:
                usage = {
                    "input_tokens": getattr(chunk_usage, "prompt_tokens", 0) or 0,
                    "output_tokens": getattr(chunk_usage, "completion_tokens", 0) or 0,
                }

            choices = getattr(chunk, "choices", None) or []
            if not choices:
                continue
            choice = choices[0]
            delta = getattr(choice, "delta", None)
            if delta is None:
                finish = getattr(choice, "finish_reason", None)
                if finish:
                    stop_reason = FINISH_MAP.get(finish, "end_turn")
                continue

            # Text content
            content = getattr(delta, "content", None)
            if content:
                yield {"type": "text_delta", "text": content}

            # Tool calls (streamed by index)
            tool_calls = getattr(delta, "tool_calls", None) or []
            for tc in tool_calls:
                idx = getattr(tc, "index", 0)
                st = tc_state.setdefault(
                    idx,
                    {"id": None, "name": None, "args_buffer": "", "started": False},
                )

                tc_id = getattr(tc, "id", None)
                if tc_id and not st["id"]:
                    st["id"] = tc_id

                fn = getattr(tc, "function", None)
                if fn is not None:
                    fn_name = getattr(fn, "name", None)
                    if fn_name and not st["name"]:
                        st["name"] = fn_name

                if not st["started"] and st["id"] and st["name"]:
                    yield {
                        "type": "tool_use_start",
                        "id": st["id"],
                        "name": st["name"],
                    }
                    st["started"] = True

                if fn is not None:
                    fn_args = getattr(fn, "arguments", None)
                    if fn_args:
                        st["args_buffer"] += fn_args
                        yield {"type": "tool_input_delta", "partial_json": fn_args}

            finish = getattr(choice, "finish_reason", None)
            if finish:
                stop_reason = FINISH_MAP.get(finish, "end_turn")

        # Flush all accumulated tool_uses
        for idx in sorted(tc_state.keys()):
            st = tc_state[idx]
            if not st["started"]:
                continue
            try:
                tool_input = json.loads(st["args_buffer"]) if st["args_buffer"] else {}
            except json.JSONDecodeError:
                tool_input = {}
            yield {
                "type": "tool_use_end",
                "id": st["id"],
                "name": st["name"],
                "input": tool_input,
            }

        yield {"type": "message_end", "stop_reason": stop_reason, "usage": usage}

    except Exception as e:
        yield {"type": "error", "error": f"Qwen stream error: {type(e).__name__}: {e}"}
