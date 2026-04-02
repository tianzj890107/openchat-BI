"""
Agent tool — spawns isolated sub-conversations (sub-agents).

Each sub-agent gets:
- Its own message history
- Access to the same tools (Bash, Read, Write, Edit, Glob, Grep)
- A focused system prompt derived from the parent
- A result returned to the parent conversation

Supports sync (foreground) execution. The sub-agent runs a full
tool-use loop until it produces a final text response.
"""

import json
from typing import Any, Optional

import anthropic

from .config import get_model, get_max_tokens


# Max iterations for sub-agent tool loops
MAX_AGENT_ITERATIONS = 20

# Max output tokens for sub-agent responses
AGENT_MAX_TOKENS = 16_000

AGENT_SCHEMA = {
    "name": "Agent",
    "description": (
        "Launch a sub-agent to handle a complex, multi-step task autonomously. "
        "The agent runs in an isolated conversation with its own context. "
        "Provide a clear, complete task description — the agent has no prior context."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "description": {
                "type": "string",
                "description": "Short (3-5 word) summary of what the agent will do.",
            },
            "prompt": {
                "type": "string",
                "description": "Full task description for the agent. Be specific and complete.",
            },
            "model": {
                "type": "string",
                "description": "Optional model override (e.g. 'claude-sonnet-4-6').",
            },
        },
        "required": ["description", "prompt"],
    },
}


def _build_agent_system_prompt(cwd: str) -> str:
    """Build a focused system prompt for sub-agents."""
    return f"""You are a sub-agent assistant. Complete the given task and report your findings.

You have access to tools: Bash, Read, Write, Edit, Glob, Grep.
- Use Read instead of cat, Edit instead of sed, Glob instead of find, Grep instead of grep.
- Working directory: {cwd}
- Be concise. Focus on completing the task.
- When done, provide a clear summary of what you found or accomplished."""


def execute_agent(params: dict[str, Any], cwd: str, client: anthropic.Anthropic) -> str:
    """
    Run a sub-agent synchronously.

    Creates an isolated conversation, runs tool loops, and returns the final text.
    """
    description = params.get("description", "sub-agent")
    prompt = params["prompt"]
    model = params.get("model") or get_model()

    system_prompt = _build_agent_system_prompt(cwd)

    # Lazy import to avoid circular dependency
    from .tools import get_base_tool_schemas, execute_tool

    # Sub-agent gets base tools only (no Agent/Task to prevent nesting)
    tools = get_base_tool_schemas()

    messages: list[dict[str, Any]] = [
        {"role": "user", "content": prompt},
    ]

    final_text = ""

    for iteration in range(MAX_AGENT_ITERATIONS):
        try:
            response = client.messages.create(
                model=model,
                max_tokens=AGENT_MAX_TOKENS,
                system=system_prompt,
                messages=messages,
                tools=tools,
            )
        except Exception as e:
            return f"Agent error: {e}"

        # Process response content blocks
        assistant_content: list[dict[str, Any]] = []
        tool_uses: list[dict[str, Any]] = []
        text_parts: list[str] = []

        for block in response.content:
            if block.type == "text":
                text_parts.append(block.text)
                assistant_content.append({"type": "text", "text": block.text})
            elif block.type == "tool_use":
                tool_use = {
                    "type": "tool_use",
                    "id": block.id,
                    "name": block.name,
                    "input": block.input,
                }
                assistant_content.append(tool_use)
                tool_uses.append(tool_use)

        messages.append({"role": "assistant", "content": assistant_content})

        if response.stop_reason != "tool_use" or not tool_uses:
            # Agent is done
            final_text = "\n".join(text_parts)
            break

        # Execute tools and add results
        tool_results: list[dict[str, Any]] = []
        for tu in tool_uses:
            try:
                result = execute_tool(tu["name"], tu["input"], cwd)
            except Exception as e:
                result = f"Error: {e}"

            tool_results.append({
                "type": "tool_result",
                "tool_use_id": tu["id"],
                "content": result,
            })

        messages.append({"role": "user", "content": tool_results})
    else:
        final_text += "\n[Agent reached iteration limit]"

    return final_text if final_text else "[Agent produced no output]"
