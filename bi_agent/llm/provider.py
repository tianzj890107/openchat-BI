"""Top-level provider dispatch.

Every provider yields the SAME event dicts as open_claude.api.stream_message:

    {"type": "text_delta", "text": str}
    {"type": "thinking_delta", "text": str}              # optional
    {"type": "tool_use_start", "id": str, "name": str}
    {"type": "tool_input_delta", "partial_json": str}    # optional
    {"type": "tool_use_end", "id": str, "name": str, "input": dict}
    {"type": "message_end", "stop_reason": str, "usage": {"input_tokens": int, "output_tokens": int}}
    {"type": "error", "error": str}

stop_reason values are normalized across providers to:
    "end_turn" | "tool_use" | "max_tokens" | "stop_sequence"
"""

from __future__ import annotations

from typing import Any, Generator, Optional

from .registry import get_model


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
        yield from provider_qwen.stream(
            model_id=model_id,
            messages=messages,
            system_prompt=system_prompt,
            allowed_tools=allowed_tools,
            max_tokens=max_tokens,
            temperature=temperature,
        )
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
