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

from .provider_qwen import FINISH_MAP, _block_text, _convert_tools, _image_part


BASE_URL = "https://api.deepseek.com/v1"


def _convert_messages(
    messages: list[dict[str, Any]],
    system_prompt: str,
    *,
    include_reasoning: bool = True,
) -> list[dict[str, Any]]:
    """Anthropic-style messages → OpenAI-style for DeepSeek.

    Mirrors `provider_qwen._convert_messages` but additionally handles
    `thinking` blocks: the API REQUIRES that any `reasoning_content`
    produced under thinking mode be passed back on the next request,
    otherwise it returns 400 invalid_request_error.

    `include_reasoning=False` should be passed when thinking is OFF for
    the current request — re-sending prior reasoning under non-thinking
    mode is unsupported and may itself trigger a validation error.
    """
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
            reasoning_parts: list[str] = []
            tool_calls: list[dict[str, Any]] = []
            for blk in content:
                bt = blk.get("type")
                if bt == "text":
                    text_parts.append(blk.get("text", ""))
                elif bt == "thinking" and include_reasoning:
                    reasoning_parts.append(blk.get("thinking", ""))
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
            if reasoning_parts:
                assistant_msg["reasoning_content"] = "".join(reasoning_parts)
            if tool_calls:
                assistant_msg["tool_calls"] = tool_calls
            out.append(assistant_msg)

        elif role == "user":
            text_parts: list[str] = []
            content_parts: list[dict[str, Any]] = []
            for blk in content:
                bt = blk.get("type")
                if bt == "tool_result":
                    out.append({
                        "role": "tool",
                        "tool_call_id": blk.get("tool_use_id"),
                        "content": _block_text(blk.get("content", "")),
                    })
                elif bt == "text":
                    text = blk.get("text", "")
                    text_parts.append(text)
                    content_parts.append({"type": "text", "text": text})
                elif bt == "image":
                    image = _image_part(blk)
                    if image:
                        content_parts.append(image)
            if text_parts:
                if any(part.get("type") == "image_url" for part in content_parts):
                    out.append({"role": "user", "content": content_parts})
                else:
                    out.append({"role": "user", "content": "".join(text_parts)})
            elif content_parts:
                out.append({"role": "user", "content": content_parts})

    return out


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
        oa_messages = _convert_messages(messages, system_prompt, include_reasoning=bool(thinking))
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
    # DeepSeek requires the thinking parameter to be ALWAYS present for
    # V4 models — omitting it leaves the request in an ambiguous mode and
    # surfaces as `400 invalid_request_error: 'reasoning_content ... must
    # be passed back'` on follow-up turns. We therefore send an explicit
    # enabled/disabled marker every call. Note: this is DeepSeek-specific,
    # other OpenAI-compatible providers (Qwen) don't accept this field.
    request_kwargs["extra_body"] = {
        "thinking": {"type": "enabled" if thinking else "disabled"},
    }

    try:
        completion_stream = client.chat.completions.create(**request_kwargs)
    except Exception as e:
        yield {"type": "error", "error": f"DeepSeek request failed: {e}"}
        return

    tc_state: dict[int, dict[str, Any]] = {}
    stop_reason = "end_turn"
    usage = {"input_tokens": 0, "output_tokens": 0}
    # Accumulate the full reasoning trace so we can emit a final
    # `thinking_block` event after the stream ends; the session loop
    # persists it back into the assistant message and provider_deepseek's
    # `_convert_messages` translates it to `reasoning_content` on the
    # NEXT request — required by DeepSeek's thinking-mode API contract.
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

            # DeepSeek's reasoning trace lands on a separate `reasoning_content`
            # delta (the v4 reasoning models surface it like the V3 reasoner
            # did). Forward it as the same `thinking_delta` event the
            # Anthropic provider uses, so the UI can render both uniformly.
            reasoning = getattr(delta, "reasoning_content", None)
            if reasoning:
                reasoning_buf += reasoning
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

        if reasoning_buf:
            yield {
                "type": "thinking_block",
                "text": reasoning_buf,
                "signature": None,
            }

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
