"""Anthropic provider — wraps the Anthropic Messages API directly.

Kept local (does NOT call open_claude.api.stream_message) so we can pass
per-call model/max_tokens/temperature without touching that module.
"""

from __future__ import annotations

import json
from typing import Any, Generator, Optional

import anthropic

from open_claude.config import get_api_key
from open_claude.tools import get_filtered_tool_schemas


def _client() -> anthropic.Anthropic:
    api_key = get_api_key()
    if not api_key:
        raise ValueError(
            "No Anthropic API key found. Set ANTHROPIC_API_KEY env var or "
            "add 'api_key' to ~/.claude/config.json."
        )
    return anthropic.Anthropic(api_key=api_key)


def stream(
    *,
    model_id: str,
    messages: list[dict[str, Any]],
    system_prompt: str,
    allowed_tools: Optional[list[str]],
    max_tokens: int,
    temperature: float,
) -> Generator[dict[str, Any], None, None]:
    try:
        client = _client()
    except Exception as e:
        yield {"type": "error", "error": str(e)}
        return

    tools = get_filtered_tool_schemas(allowed_tools)
    kwargs: dict[str, Any] = dict(
        model=model_id,
        max_tokens=max_tokens,
        system=system_prompt,
        messages=messages,
        tools=tools,
    )
    if temperature is not None:
        kwargs["temperature"] = float(temperature)

    try:
        with client.messages.stream(**kwargs) as stream_ctx:
            current_tool: Optional[dict[str, Any]] = None
            current_tool_json = ""

            for event in stream_ctx:
                etype = event.type
                if etype == "content_block_start":
                    block = event.content_block
                    if block.type == "tool_use":
                        current_tool = {"id": block.id, "name": block.name}
                        current_tool_json = ""
                        yield {"type": "tool_use_start", "id": block.id, "name": block.name}
                elif etype == "content_block_delta":
                    delta = event.delta
                    dt = delta.type
                    if dt == "text_delta":
                        yield {"type": "text_delta", "text": delta.text}
                    elif dt == "thinking_delta":
                        yield {"type": "thinking_delta", "text": delta.thinking}
                    elif dt == "input_json_delta":
                        current_tool_json += delta.partial_json
                        yield {"type": "tool_input_delta", "partial_json": delta.partial_json}
                elif etype == "content_block_stop":
                    if current_tool is not None:
                        try:
                            tool_input = json.loads(current_tool_json) if current_tool_json else {}
                        except json.JSONDecodeError:
                            tool_input = {}
                        yield {
                            "type": "tool_use_end",
                            "id": current_tool["id"],
                            "name": current_tool["name"],
                            "input": tool_input,
                        }
                        current_tool = None
                        current_tool_json = ""
                elif etype == "message_delta":
                    yield {
                        "type": "message_end",
                        "stop_reason": event.delta.stop_reason,
                        "usage": {
                            "input_tokens": 0,
                            "output_tokens": event.usage.output_tokens if event.usage else 0,
                        },
                    }
    except anthropic.APIError as e:
        yield {"type": "error", "error": f"Anthropic API error: {e.message}"}
    except Exception as e:
        yield {"type": "error", "error": f"{type(e).__name__}: {e}"}
