"""Top-level provider dispatch.

Every provider yields the SAME event dicts as open_claude.api.stream_message:

    {"type": "text_delta", "text": str}
    {"type": "thinking_delta", "text": str}              # optional, streaming
    {"type": "thinking_block", "text": str,              # optional, end-of-block
                               "signature": str | None}  #   (Anthropic only)
    {"type": "tool_use_start", "id": str, "name": str}
    {"type": "tool_input_delta", "partial_json": str}    # optional
    {"type": "tool_use_end", "id": str, "name": str, "input": dict}
    {"type": "message_end", "stop_reason": str, "usage": {"input_tokens": int, "output_tokens": int}}
    {"type": "error", "error": str}

stop_reason values are normalized across providers to:
    "end_turn" | "tool_use" | "max_tokens" | "stop_sequence"

`thinking_block` is what the session loop persists into the assistant
message so subsequent tool turns can round-trip the reasoning trace —
required by Anthropic (with `signature`) and by DeepSeek (text only)
when extended thinking is enabled.
"""

from __future__ import annotations

from typing import Any, Generator, Optional

from .registry import fallback_model_keys, get_model


def _is_quota_error(message: str) -> bool:
    text = (message or "").lower()
    return any(token in text for token in (
        "429", "rate limit", "quota", "insufficient_quota", "exceeded",
        "resource_exhausted", "限额", "额度", "用完",
    ))


def stream_message(
    messages: list[dict[str, Any]],
    system_prompt: str,
    allowed_tools: Optional[list[str]],
    model_key: str,
    max_tokens: int,
    temperature: float,
    thinking: bool = False,
) -> Generator[dict[str, Any], None, None]:
    m = get_model(model_key)
    if not m:
        yield {"type": "error", "error": f"Unknown model_key: {model_key}"}
        return

    provider = m["provider"]
    model_id = m["model_id"]
    # Only forward thinking when the model advertises support for it,
    # so providers don't have to re-check every model.
    effective_thinking = bool(thinking) and bool(m.get("supports_thinking", False))

    if provider == "anthropic":
        from . import provider_anthropic
        yield from provider_anthropic.stream(
            model_id=model_id,
            messages=messages,
            system_prompt=system_prompt,
            allowed_tools=allowed_tools,
            max_tokens=max_tokens,
            temperature=temperature,
            thinking=effective_thinking,
        )
    elif provider == "qwen":
        from . import provider_qwen
        # DashScope may reject a model after its quota is exhausted. Retry
        # only pre-stream quota/rate-limit failures with the next configured
        # Qwen model; normal errors are returned unchanged.
        attempts = [model_key] + fallback_model_keys(model_key)
        for index, attempt_key in enumerate(attempts):
            attempt = get_model(attempt_key) or m
            emitted = False
            retry = False
            for event in provider_qwen.stream(
                model_id=attempt["model_id"],
                messages=messages,
                system_prompt=system_prompt,
                allowed_tools=allowed_tools,
                max_tokens=max_tokens,
                temperature=temperature,
            ):
                if event.get("type") in {"text_delta", "tool_use_start", "tool_input_delta", "tool_use_end"}:
                    emitted = True
                if event.get("type") == "error" and not emitted and _is_quota_error(event.get("error", "")) and index < len(attempts) - 1:
                    retry = True
                    break
                yield event
            if not retry:
                return
            yield {"type": "model_fallback", "model_key": attempts[index + 1],
                   "reason": "当前模型额度或限流"}
    elif provider == "deepseek":
        from . import provider_deepseek
        yield from provider_deepseek.stream(
            model_id=model_id,
            messages=messages,
            system_prompt=system_prompt,
            allowed_tools=allowed_tools,
            max_tokens=max_tokens,
            temperature=temperature,
            thinking=effective_thinking,
        )
    else:
        yield {"type": "error", "error": f"Unsupported provider: {provider}"}


def get_model_id(model_key: str) -> str:
    m = get_model(model_key)
    return m["model_id"] if m else model_key
