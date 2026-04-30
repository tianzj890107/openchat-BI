"""DeepSeek provider — OpenAI-compatible endpoint.

Mirrors `provider_qwen.py`: uses the `openai` SDK with `base_url` pointing
at DeepSeek's `/v1` endpoint. Anthropic↔OpenAI translation logic is reused
verbatim by importing the helpers from `provider_qwen`.

Adds an `thinking` flag — when True, sends `extra_body={"thinking":
{"type": "enabled"}}`, which is the parameter shape DeepSeek V4 exposes
for switchable extended-thinking on the chat-completions endpoint. If
your DeepSeek deployment uses a different param name, adjust here only.

API key resolution: DEEPSEEK_API_KEY env var → `deepseek_api_key` field
in ~/.claude/config.json.
"""

from __future__ import annotations

import json
import os
from typing import Any, Generator, Optional

try:
    from openai import OpenAI  # type: ignore
except Exception:  # pragma: no cover
    OpenAI = None  # type: ignore

from .provider_qwen import FINISH_MAP, _convert_messages, _convert_tools


BASE_URL = "https://api.deepseek.com/v1"


def _get_api_key() -> Optional[str]:
    v = os.environ.get("DEEPSEEK_API_KEY")
    if v:
        return v
    try:
        from open_claude.config import load_config
        cfg = load_config()
        if cfg.get("deepseek_api_key"):
            return cfg["deepseek_api_key"]
    except Exception:
        pass
    return None


def stream(
    *,
    model_id: str,
    messages: list[dict[str, Any]],
    system_prompt: str,
    allowed_tools: Optional[list[str]],
    max_tokens: int,
    temperature: float,
    thinking: bool = False,
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
                "No DeepSeek API key. Set DEEPSEEK_API_KEY env var, or add "
                "'deepseek_api_key' to ~/.claude/config.json."
            ),
        }
        return

    try:
        client = OpenAI(api_key=api_key, base_url=BASE_URL)
    except Exception as e:
        yield {"type": "error", "error": f"Failed to init DeepSeek client: {e}"}
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
    if thinking:
        request_kwargs["extra_body"] = {"thinking": {"type": "enabled"}}

    try:
        completion_stream = client.chat.completions.create(**request_kwargs)
    except Exception as e:
        yield {"type": "error", "error": f"DeepSeek request failed: {e}"}
        return

    tc_state: dict[int, dict[str, Any]] = {}
    stop_reason = "end_turn"
    usage = {"input_tokens": 0, "output_tokens": 0}

    try:
        for chunk in completion_stream:
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

            # DeepSeek's reasoning trace lands on a separate `reasoning_content`
            # delta (the v4 reasoning models surface it like the V3 reasoner
            # did). Forward it as the same `thinking_delta` event the
            # Anthropic provider uses, so the UI can render both uniformly.
            reasoning = getattr(delta, "reasoning_content", None)
            if reasoning:
                yield {"type": "thinking_delta", "text": reasoning}

            content = getattr(delta, "content", None)
            if content:
                yield {"type": "text_delta", "text": content}

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
        yield {"type": "error", "error": f"DeepSeek stream error: {type(e).__name__}: {e}"}
