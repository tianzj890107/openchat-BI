"""Open Claude - Anthropic API client with streaming support."""

import json
from typing import Any, Generator, Optional

import anthropic

from .config import get_api_key, get_max_tokens, get_model
from .tools import TOOL_SCHEMAS, get_filtered_tool_schemas


def create_client() -> anthropic.Anthropic:
    """Create Anthropic API client."""
    api_key = get_api_key()
    if not api_key:
        raise ValueError(
            "No API key found. Set ANTHROPIC_API_KEY environment variable "
            "or add 'api_key' to ~/.claude/config.json"
        )
    return anthropic.Anthropic(api_key=api_key)


def get_tool_schemas(allowed_tools: Optional[list[str]] = None) -> list[dict[str, Any]]:
    """Get tool schemas in Anthropic API format, optionally filtered."""
    return get_filtered_tool_schemas(allowed_tools)


def stream_message(
    client: anthropic.Anthropic,
    messages: list[dict[str, Any]],
    system_prompt: str,
    model: Optional[str] = None,
    max_tokens: Optional[int] = None,
    allowed_tools: Optional[list[str]] = None,
) -> Generator[dict[str, Any], None, None]:
    """
    Stream a message from the API, yielding events as they arrive.

    Yields dicts with keys:
        - {"type": "text_delta", "text": "..."}
        - {"type": "thinking_delta", "text": "..."}
        - {"type": "tool_use_start", "id": "...", "name": "..."}
        - {"type": "tool_input_delta", "partial_json": "..."}
        - {"type": "tool_use_end", "id": "...", "name": "...", "input": {...}}
        - {"type": "message_end", "stop_reason": "...", "usage": {...}}
        - {"type": "error", "error": "..."}
    """
    model = model or get_model()
    max_tokens = max_tokens or get_max_tokens()

    tools = get_tool_schemas(allowed_tools)

    try:
        with client.messages.stream(
            model=model,
            max_tokens=max_tokens,
            system=system_prompt,
            messages=messages,
            tools=tools,
        ) as stream:
            # Track current tool use block
            current_tool: Optional[dict[str, Any]] = None
            current_tool_json = ""

            for event in stream:
                if event.type == "content_block_start":
                    block = event.content_block
                    if block.type == "text":
                        pass  # text deltas come via content_block_delta
                    elif block.type == "thinking":
                        pass
                    elif block.type == "tool_use":
                        current_tool = {"id": block.id, "name": block.name}
                        current_tool_json = ""
                        yield {"type": "tool_use_start", "id": block.id, "name": block.name}

                elif event.type == "content_block_delta":
                    delta = event.delta
                    if delta.type == "text_delta":
                        yield {"type": "text_delta", "text": delta.text}
                    elif delta.type == "thinking_delta":
                        yield {"type": "thinking_delta", "text": delta.thinking}
                    elif delta.type == "input_json_delta":
                        current_tool_json += delta.partial_json
                        yield {"type": "tool_input_delta", "partial_json": delta.partial_json}

                elif event.type == "content_block_stop":
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

                elif event.type == "message_delta":
                    yield {
                        "type": "message_end",
                        "stop_reason": event.delta.stop_reason,
                        "usage": {
                            "output_tokens": event.usage.output_tokens if event.usage else 0,
                        },
                    }

    except anthropic.APIError as e:
        yield {"type": "error", "error": f"API Error: {e.message}"}
    except Exception as e:
        yield {"type": "error", "error": str(e)}


def send_message(
    client: anthropic.Anthropic,
    messages: list[dict[str, Any]],
    system_prompt: str,
    model: Optional[str] = None,
    max_tokens: Optional[int] = None,
) -> dict[str, Any]:
    """Non-streaming message send. Returns full response."""
    model = model or get_model()
    max_tokens = max_tokens or get_max_tokens()

    response = client.messages.create(
        model=model,
        max_tokens=max_tokens,
        system=system_prompt,
        messages=messages,
        tools=get_tool_schemas(),
    )
    return {
        "content": response.content,
        "stop_reason": response.stop_reason,
        "usage": {
            "input_tokens": response.usage.input_tokens,
            "output_tokens": response.usage.output_tokens,
        },
    }
