"""Team OpenAI-compatible provider.

The team gateway exposes several routed models behind one OpenAI-compatible
endpoint.  This adapter intentionally uses the same normalized event schema as
the Qwen/DeepSeek adapters so tool calling, streaming and model fallback stay
inside the existing Agent loop.
"""

from __future__ import annotations

import json
import os
from typing import Any, Generator, Optional

try:
    from openai import OpenAI  # type: ignore
except Exception:  # pragma: no cover
    OpenAI = None  # type: ignore

from .provider_deepseek import _convert_messages
from .provider_qwen import FINISH_MAP, _convert_tools


DEFAULT_BASE_URL = "http://127.0.0.1:4000/v1"


def _get_api_key() -> Optional[str]:
    value = os.environ.get("TEAM_API_KEY")
    if value:
        return value
    try:
        from open_claude.config import load_config
        cfg = load_config()
        if cfg.get("team_api_key"):
            return cfg["team_api_key"]
    except Exception:
        pass
    return None


def _get_base_url() -> str:
    return os.environ.get("TEAM_BASE_URL", DEFAULT_BASE_URL).rstrip("/")


def _enable_thinking() -> Optional[bool]:
    value = os.environ.get("TEAM_ENABLE_THINKING")
    if value is None or not value.strip():
        return None
    return value.strip().lower() in {"1", "true", "yes", "on"}


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
        yield {"type": "error", "error": "The 'openai' package is not installed."}
        return

    api_key = _get_api_key()
    if not api_key:
        yield {"type": "error", "error": "No TEAM_API_KEY configured."}
        return

    try:
        client = OpenAI(api_key=api_key, base_url=_get_base_url())
        oa_messages = _convert_messages(
            messages, system_prompt, include_reasoning=bool(thinking)
        )
        oa_tools = _convert_tools(allowed_tools)
    except Exception as e:
        yield {"type": "error", "error": f"Team client/message setup failed: {e}"}
        return

    request_kwargs: dict[str, Any] = {
        "model": model_id,
        "messages": oa_messages,
        "max_tokens": max_tokens,
        "temperature": temperature,
        "stream": True,
        "stream_options": {"include_usage": True},
    }
    if oa_tools:
        request_kwargs["tools"] = oa_tools
        request_kwargs["tool_choice"] = "auto"
    enabled = _enable_thinking()
    if enabled is not None:
        request_kwargs["extra_body"] = {
            "thinking": {"type": "enabled" if enabled else "disabled"}
        }

    try:
        completion_stream = client.chat.completions.create(**request_kwargs)
    except Exception as e:
        yield {"type": "error", "error": f"Team API request failed: {e}"}
        return

    tc_state: dict[int, dict[str, Any]] = {}
    stop_reason = "end_turn"
    usage = {"input_tokens": 0, "output_tokens": 0}
    reasoning_buf = ""

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

            reasoning = getattr(delta, "reasoning_content", None)
            if reasoning:
                reasoning_buf += reasoning
                yield {"type": "thinking_delta", "text": reasoning}

            content = getattr(delta, "content", None)
            if content:
                yield {"type": "text_delta", "text": content}

            for tc in getattr(delta, "tool_calls", None) or []:
                idx = getattr(tc, "index", 0)
                state = tc_state.setdefault(
                    idx, {"id": None, "name": None, "args": "", "started": False}
                )
                tc_id = getattr(tc, "id", None)
                if tc_id and not state["id"]:
                    state["id"] = tc_id
                fn = getattr(tc, "function", None)
                if fn is not None:
                    name = getattr(fn, "name", None)
                    if name and not state["name"]:
                        state["name"] = name
                if not state["started"] and state["id"] and state["name"]:
                    yield {
                        "type": "tool_use_start",
                        "id": state["id"],
                        "name": state["name"],
                    }
                    state["started"] = True
                args = getattr(fn, "arguments", None) if fn is not None else None
                if args:
                    state["args"] += args
                    yield {"type": "tool_input_delta", "partial_json": args}

            finish = getattr(choice, "finish_reason", None)
            if finish:
                stop_reason = FINISH_MAP.get(finish, "end_turn")

        for idx in sorted(tc_state):
            state = tc_state[idx]
            if not state["started"]:
                continue
            try:
                tool_input = json.loads(state["args"]) if state["args"] else {}
            except json.JSONDecodeError:
                tool_input = {}
            yield {
                "type": "tool_use_end",
                "id": state["id"],
                "name": state["name"],
                "input": tool_input,
            }
        if reasoning_buf:
            yield {"type": "thinking_block", "text": reasoning_buf}
        yield {"type": "message_end", "stop_reason": stop_reason, "usage": usage}
    except Exception as e:
        yield {"type": "error", "error": f"Team API stream error: {type(e).__name__}: {e}"}
