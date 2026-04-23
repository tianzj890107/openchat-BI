"""Open Claude - REPL loop with streaming display and tool execution."""

import os
import sys
from typing import Any, Optional

from rich.console import Console
from rich.panel import Panel
from rich.syntax import Syntax
from rich.text import Text

from .agent import execute_agent
from .agent_def import AgentDef, BASE_AGENT_DEF, get_agent_def_registry, load_agent_defs
from .agent_instance import AgentInstance, InstanceState, get_instance_store
from .api import create_client, stream_message
from .compact import compact_conversation, needs_compaction
from .config import get_model
from .prompt import build_system_prompt
from .skills.bundled import init_bundled_skills
from .skills.registry import get_registry, load_skills
from .tasks import get_task_store
from .tokens import CostTracker, estimate_messages_tokens, tokens_remaining
from .tools import execute_tool, get_filtered_tool_schemas

console = Console()


# ---------------------------------------------------------------------------
# Permission system
# ---------------------------------------------------------------------------

# Tools that are safe to auto-execute (read-only, no side effects)
SAFE_TOOLS = {"Read", "Glob", "Grep", "Skill", "TaskCreate", "TaskUpdate", "TaskList", "TaskGet", "Agent"}

# Tools that modify files or run commands - require confirmation
DANGEROUS_TOOLS = {"Bash", "Write", "Edit"}


class PermissionManager:
    """Manages user permission for tool execution."""

    def __init__(self):
        # "default" = ask each time for dangerous tools
        # "always_allow" = auto-approve everything
        # "deny_all" = block all dangerous tools
        self.mode = "default"
        # Per-tool session memory: tool_name -> bool (True=allowed this session)
        self._session_allowed: dict[str, bool] = {}
        # Per-tool always-allow set (user said "allow all" for this tool)
        self._always_allowed: set[str] = set()

    def check_permission(self, tool_name: str, tool_input: dict[str, Any]) -> tuple[bool, str]:
        """
        Check if a tool call is permitted.
        Returns (allowed: bool, reason: str).
        If not allowed, reason explains why (e.g., "denied by user").
        """
        # Safe tools always allowed
        if tool_name in SAFE_TOOLS:
            return True, ""

        # Global auto-approve mode
        if self.mode == "always_allow":
            return True, ""

        # Global deny mode
        if self.mode == "deny_all":
            return False, "All dangerous tools are blocked (deny_all mode)"

        # Per-tool always-allow
        if tool_name in self._always_allowed:
            return True, ""

        # Ask the user
        return self._prompt_user(tool_name, tool_input)

    def _prompt_user(self, tool_name: str, tool_input: dict[str, Any]) -> tuple[bool, str]:
        """Interactively ask the user for permission."""
        console.print()

        # Show what will be executed
        if tool_name == "Bash":
            cmd = tool_input.get("command", "")
            console.print(Panel(
                Syntax(cmd, "bash", theme="monokai", line_numbers=False),
                title="[bold yellow]Bash Command[/bold yellow]",
                border_style="yellow",
            ))
        elif tool_name == "Write":
            fp = tool_input.get("file_path", "")
            content = tool_input.get("content", "")
            lines = content.split("\n")
            preview = "\n".join(lines[:20])
            if len(lines) > 20:
                preview += f"\n... ({len(lines) - 20} more lines)"
            console.print(Panel(
                f"[bold]File:[/bold] {fp}\n[bold]Content:[/bold]\n{preview}",
                title="[bold yellow]Write File[/bold yellow]",
                border_style="yellow",
            ))
        elif tool_name == "Edit":
            fp = tool_input.get("file_path", "")
            old = tool_input.get("old_string", "")
            new = tool_input.get("new_string", "")
            console.print(Panel(
                f"[bold]File:[/bold] {fp}\n"
                f"[bold red]- {_shorten(old, 200)}[/bold red]\n"
                f"[bold green]+ {_shorten(new, 200)}[/bold green]",
                title="[bold yellow]Edit File[/bold yellow]",
                border_style="yellow",
            ))

        # Prompt
        console.print(
            "  [bold cyan]y[/bold cyan] = yes  "
            "[bold cyan]n[/bold cyan] = no  "
            "[bold cyan]a[/bold cyan] = always allow this tool  "
            "[bold cyan]A[/bold cyan] = always allow all"
        )

        while True:
            try:
                choice = console.input("  [bold]Allow? [y/n/a/A] > [/bold]").strip()
            except (EOFError, KeyboardInterrupt):
                return False, "User cancelled"

            if choice in ("y", "Y", "yes"):
                return True, ""
            elif choice in ("n", "N", "no"):
                return False, "Denied by user"
            elif choice == "a":
                self._always_allowed.add(tool_name)
                console.print(f"  [dim]{tool_name} will be auto-approved for this session[/dim]")
                return True, ""
            elif choice == "A":
                self.mode = "always_allow"
                console.print("  [dim]All tools will be auto-approved for this session[/dim]")
                return True, ""
            else:
                console.print("  [dim]Please enter y, n, a, or A[/dim]")


# ---------------------------------------------------------------------------
# Display helpers
# ---------------------------------------------------------------------------

def print_welcome(agent_def: Optional[AgentDef] = None, instance: Optional[AgentInstance] = None):
    title = "[bold cyan]Open Claude[/bold cyan]"
    model_name = (agent_def.model if agent_def and agent_def.model else get_model())

    if agent_def and not agent_def.is_base:
        title = f"[bold cyan]{agent_def.name}[/bold cyan]"
        desc = agent_def.description or ""
        if desc:
            title += f"\n[dim]{desc}[/dim]"

    instance_line = ""
    if instance:
        instance_line = f"\n[dim]Instance #{instance.id}[/dim]"

    console.print()
    console.print(Panel.fit(
        f"{title}\n"
        f"[dim]Model: {model_name}[/dim]"
        f"{instance_line}\n"
        "[dim]Type your message, or 'quit' to exit. Use Ctrl+C to cancel.[/dim]",
        border_style="cyan",
    ))
    # Show welcome message from agent definition
    if agent_def and agent_def.welcome_message:
        console.print(f"\n  [italic]{agent_def.welcome_message}[/italic]")
    console.print()


def print_tool_call(name: str, params: dict[str, Any]):
    """Display a tool call being made."""
    if name == "Bash":
        cmd = params.get("command", "")
        console.print(f"  [bold yellow]> Bash[/bold yellow] [dim]{_shorten(cmd, 120)}[/dim]")
    elif name == "Read":
        fp = params.get("file_path", "")
        console.print(f"  [bold yellow]> Read[/bold yellow] [dim]{fp}[/dim]")
    elif name == "Write":
        fp = params.get("file_path", "")
        console.print(f"  [bold yellow]> Write[/bold yellow] [dim]{fp}[/dim]")
    elif name == "Edit":
        fp = params.get("file_path", "")
        console.print(f"  [bold yellow]> Edit[/bold yellow] [dim]{fp}[/dim]")
    elif name == "Glob":
        p = params.get("pattern", "")
        console.print(f"  [bold yellow]> Glob[/bold yellow] [dim]{p}[/dim]")
    elif name == "Grep":
        p = params.get("pattern", "")
        console.print(f"  [bold yellow]> Grep[/bold yellow] [dim]{p}[/dim]")
    elif name == "Skill":
        s = params.get("skill", "")
        a = params.get("args", "")
        console.print(f"  [bold yellow]> Skill[/bold yellow] [dim]/{s} {a}[/dim]")
    elif name == "TaskCreate":
        console.print(f"  [bold yellow]> TaskCreate[/bold yellow] [dim]{params.get('subject', '')}[/dim]")
    elif name == "TaskUpdate":
        console.print(f"  [bold yellow]> TaskUpdate[/bold yellow] [dim]#{params.get('taskId', '')} -> {params.get('status', '')}[/dim]")
    elif name == "TaskList":
        console.print(f"  [bold yellow]> TaskList[/bold yellow]")
    elif name == "TaskGet":
        console.print(f"  [bold yellow]> TaskGet[/bold yellow] [dim]#{params.get('taskId', '')}[/dim]")
    elif name == "Agent":
        desc = params.get("description", "")
        console.print(f"  [bold magenta]> Agent[/bold magenta] [dim]{desc}[/dim]")
    else:
        console.print(f"  [bold yellow]> {name}[/bold yellow]")


def print_tool_result(name: str, result: str):
    """Display tool execution result."""
    lines = result.split("\n")
    if len(lines) > 30:
        preview = "\n".join(lines[:15] + [f"  ... ({len(lines) - 30} more lines) ..."] + lines[-15:])
    else:
        preview = result
    console.print(f"  [dim]{preview}[/dim]")
    console.print()


def _shorten(s: str, max_len: int) -> str:
    s = s.replace("\n", " ")
    if len(s) > max_len:
        return s[:max_len] + "..."
    return s


# ---------------------------------------------------------------------------
# Conversation management
# ---------------------------------------------------------------------------

class Conversation:
    """Manages message history and the query loop."""

    def __init__(
        self,
        cwd: str,
        permission_mode: str = "default",
        agent_def: Optional[AgentDef] = None,
    ):
        self.cwd = cwd
        self.messages: list[dict[str, Any]] = []
        self.client = create_client()
        self.permissions = PermissionManager()
        self.cost_tracker = CostTracker()

        # Agent definition — drives identity, tools, model, permissions
        self.agent_def = agent_def or BASE_AGENT_DEF

        # Model: agent def override > CLI override > config default
        self.model = self.agent_def.model or get_model()

        # Permission: agent def override > CLI flag
        self.permissions.mode = self.agent_def.permission_mode or permission_mode

        # Max tool-loop iterations
        self.max_iterations = self.agent_def.max_iterations

        # Create instance record
        store = get_instance_store()
        self.instance = store.create(self.agent_def, cwd)
        self.instance.start()

        # Initialize skills
        init_bundled_skills()
        load_skills(cwd)

        # Load agent definitions
        load_agent_defs(cwd)

        # Build system prompt (after skills loaded so they appear in prompt)
        self.system_prompt = build_system_prompt(cwd, agent_def=self.agent_def)

    def add_user_message(self, text: str):
        self.messages.append({"role": "user", "content": text})

    def run_turn(self) -> None:
        """Run one assistant turn: stream response, execute tools, loop until done."""
        for iteration in range(self.max_iterations):
            # Auto-compact if approaching context limit
            self._maybe_compact()

            stop_reason = self._stream_assistant_response()

            if stop_reason != "tool_use":
                break

            # Process all tool_use blocks in the last assistant message
            self._execute_pending_tools()

    def _maybe_compact(self):
        """Auto-compact conversation if near context window limit."""
        if not self.messages:
            return
        if needs_compaction(self.messages, self.model):
            console.print("\n  [dim bold]Compacting conversation...[/dim bold]")
            try:
                self.messages = compact_conversation(
                    self.client, self.messages, self.model, self.system_prompt,
                )
                remaining = tokens_remaining(self.messages, self.model)
                console.print(f"  [dim]Compacted. ~{remaining:,} tokens available.[/dim]\n")
            except Exception as e:
                console.print(f"  [dim red]Compaction failed: {e}[/dim red]\n")

    def _stream_assistant_response(self) -> str:
        """Stream one assistant response. Returns stop_reason."""
        text_buffer = ""
        thinking_buffer = ""
        tool_uses: list[dict[str, Any]] = []
        current_tool: Optional[dict[str, Any]] = None
        stop_reason = "end_turn"
        started_text = False

        # Use a single generator for the entire stream
        event_gen = stream_message(
            self.client, self.messages, self.system_prompt,
            allowed_tools=self.agent_def.tools,
        )

        # Show spinner until first text/tool event
        spinner_active = True
        status = console.status("[bold cyan]Thinking...[/bold cyan]", spinner="dots")
        status.start()

        for event in event_gen:
            etype = event["type"]

            if etype == "thinking_delta":
                thinking_buffer += event["text"]

            elif etype == "text_delta":
                if spinner_active:
                    status.stop()
                    spinner_active = False
                if not started_text:
                    started_text = True
                    console.print()  # Newline before response
                text = event["text"]
                text_buffer += text
                console.print(text, end="", highlight=False)

            elif etype == "tool_use_start":
                if spinner_active:
                    status.stop()
                    spinner_active = False
                current_tool = {
                    "id": event["id"],
                    "name": event["name"],
                }

            elif etype == "tool_input_delta":
                pass  # Accumulating JSON in api.py

            elif etype == "tool_use_end":
                tool_use = {
                    "type": "tool_use",
                    "id": event["id"],
                    "name": event["name"],
                    "input": event["input"],
                }
                tool_uses.append(tool_use)
                current_tool = None

            elif etype == "message_end":
                stop_reason = event.get("stop_reason", "end_turn")
                usage = event.get("usage", {})
                out_tokens = usage.get("output_tokens", 0)
                inp_tokens = usage.get("input_tokens", 0)
                self.cost_tracker.add_usage(
                    self.model,
                    input_tokens=inp_tokens,
                    output_tokens=out_tokens,
                )

            elif etype == "error":
                if spinner_active:
                    status.stop()
                    spinner_active = False
                console.print(f"\n[bold red]Error: {event['error']}[/bold red]")
                return "error"

        if spinner_active:
            status.stop()

        if started_text:
            console.print()  # Newline after text

        # Build the assistant message content blocks
        content: list[dict[str, Any]] = []
        if text_buffer:
            content.append({"type": "text", "text": text_buffer})
        for tu in tool_uses:
            content.append(tu)

        if content:
            self.messages.append({"role": "assistant", "content": content})

        return stop_reason

    def _execute_pending_tools(self):
        """Execute tool_use blocks from the last assistant message and add results."""
        if not self.messages or self.messages[-1]["role"] != "assistant":
            return

        assistant_content = self.messages[-1]["content"]
        tool_results: list[dict[str, Any]] = []

        for block in assistant_content:
            if block.get("type") != "tool_use":
                continue

            tool_name = block["name"]
            tool_input = block["input"]
            tool_id = block["id"]

            # --- Permission check ---
            allowed, reason = self.permissions.check_permission(tool_name, tool_input)

            if not allowed:
                console.print(f"  [bold red]> {tool_name} blocked[/bold red] [dim]{reason}[/dim]")
                tool_results.append({
                    "type": "tool_result",
                    "tool_use_id": tool_id,
                    "content": f"Tool execution denied by user: {reason}",
                    "is_error": True,
                })
                continue

            # Display the tool call (for safe tools that skip the permission prompt)
            if tool_name in SAFE_TOOLS:
                print_tool_call(tool_name, tool_input)

            # Execute — Agent tool needs client, others use execute_tool
            try:
                if tool_name == "Agent":
                    console.print(f"  [dim]Sub-agent running...[/dim]")
                    result = execute_agent(tool_input, self.cwd, self.client)
                else:
                    result = execute_tool(tool_name, tool_input, self.cwd)
            except Exception as e:
                result = f"Error executing {tool_name}: {e}"

            # Display result (abbreviated)
            print_tool_result(tool_name, result)

            tool_results.append({
                "type": "tool_result",
                "tool_use_id": tool_id,
                "content": result,
            })

        if tool_results:
            self.messages.append({"role": "user", "content": tool_results})


# ---------------------------------------------------------------------------
# REPL
# ---------------------------------------------------------------------------

def run_repl(
    cwd: Optional[str] = None,
    permission_mode: str = "default",
    agent_def: Optional[AgentDef] = None,
):
    """Main REPL loop."""
    cwd = cwd or os.getcwd()

    conv = Conversation(cwd, permission_mode=permission_mode, agent_def=agent_def)
    print_welcome(agent_def=conv.agent_def, instance=conv.instance)

    # Persistent prompt session
    try:
        from prompt_toolkit import PromptSession
        session = PromptSession()
        use_prompt_toolkit = True
    except ImportError:
        session = None
        use_prompt_toolkit = False

    while True:
        try:
            # Get input
            if use_prompt_toolkit:
                text = session.prompt("\nYou> ")
            else:
                text = input("\nYou> ")

            text = text.strip()
            if not text:
                continue

            # Commands
            if text.lower() in ("quit", "exit", "/quit", "/exit"):
                console.print("[dim]Goodbye![/dim]")
                break

            if text.lower() in ("/clear",):
                conv.messages.clear()
                console.print("[dim]Conversation cleared.[/dim]")
                continue

            if text.lower() in ("/help",):
                # Build skills list for help
                registry = get_registry()
                user_skills = registry.get_user_invocable()
                skills_help = ""
                if user_skills:
                    skills_help = "\n[bold]Skills (slash commands):[/bold]\n"
                    for s in user_skills:
                        hint = f" {s.argument_hint}" if s.argument_hint else ""
                        desc = f" - {s.description}" if s.description else ""
                        skills_help += f"  /{s.name}{hint}{desc}\n"

                console.print(Panel(
                    "[bold]Commands:[/bold]\n"
                    "  /clear       - Clear conversation history\n"
                    "  /help        - Show this help\n"
                    "  /tasks       - Show current tasks\n"
                    "  /skills      - List all available skills\n"
                    "  /agents      - List available agent definitions\n"
                    "  /agent       - Show current agent info\n"
                    "  /instances   - List active agent instances\n"
                    "  /model       - Show current model\n"
                    "  /cost        - Show token usage and cost\n"
                    "  /compact     - Manually compact conversation history\n"
                    "  /permission  - Show/change permission mode\n"
                    "  quit         - Exit\n"
                    + skills_help +
                    "\n[bold]Permission modes:[/bold]\n"
                    "  default      - Ask before Bash/Write/Edit (default)\n"
                    "  always_allow - Auto-approve all tools\n"
                    "  deny_all     - Block all dangerous tools\n\n"
                    "[bold]Tips:[/bold]\n"
                    "  - Just type your message and press Enter\n"
                    "  - Use /skill-name to invoke a skill directly\n"
                    "  - Claude can read/write files, run commands, search code\n"
                    "  - Use Ctrl+C to interrupt a response\n"
                    "  - When prompted, press [bold]y/n/a/A[/bold] to allow/deny tools",
                    title="Help",
                    border_style="blue",
                ))
                continue

            if text.lower() in ("/model",):
                console.print(f"[dim]Model: {get_model()}[/dim]")
                continue

            if text.lower() in ("/cost",):
                console.print(f"[dim]{conv.cost_tracker.format_summary()}[/dim]")
                remaining = tokens_remaining(conv.messages, conv.model)
                console.print(f"[dim]Context: ~{estimate_messages_tokens(conv.messages):,} tokens used, ~{remaining:,} remaining[/dim]")
                continue

            if text.lower() in ("/compact",):
                if len(conv.messages) < 4:
                    console.print("[dim]Too few messages to compact.[/dim]")
                else:
                    console.print("[dim]Compacting conversation...[/dim]")
                    try:
                        conv.messages = compact_conversation(
                            conv.client, conv.messages, conv.model, conv.system_prompt,
                        )
                        remaining = tokens_remaining(conv.messages, conv.model)
                        console.print(f"[dim]Done. ~{remaining:,} tokens available.[/dim]")
                    except Exception as e:
                        console.print(f"[dim red]Compaction failed: {e}[/dim red]")
                continue

            if text.lower().startswith("/permission"):
                parts = text.split(maxsplit=1)
                if len(parts) > 1 and parts[1] in ("default", "always_allow", "deny_all"):
                    conv.permissions.mode = parts[1]
                    conv.permissions._always_allowed.clear()
                    console.print(f"[dim]Permission mode set to: {parts[1]}[/dim]")
                else:
                    mode = conv.permissions.mode
                    allowed = ", ".join(conv.permissions._always_allowed) or "none"
                    console.print(
                        f"[dim]Current mode: {mode}\n"
                        f"Session auto-approved tools: {allowed}[/dim]"
                    )
                continue

            if text.lower() in ("/tasks",):
                store = get_task_store()
                tasks = store.list_all()
                if not tasks:
                    console.print("[dim]No tasks.[/dim]")
                else:
                    for t in tasks:
                        color = {"pending": "dim", "in_progress": "cyan", "completed": "green"}.get(t.status, "white")
                        console.print(f"  [{color}]{t.summary()}[/{color}]")
                continue

            if text.lower() in ("/skills",):
                registry = get_registry()
                all_skills = registry.get_all()
                if not all_skills:
                    console.print("[dim]No skills loaded.[/dim]")
                else:
                    console.print(f"[dim]Loaded {len(all_skills)} skill(s):[/dim]")
                    for s in all_skills:
                        src = f"[{s.source}]"
                        desc = f" - {s.description}" if s.description else ""
                        invocable = " (user-invocable)" if s.user_invocable else ""
                        console.print(f"  [bold cyan]/{s.name}[/bold cyan]{desc} [dim]{src}{invocable}[/dim]")
                continue

            if text.lower() in ("/agents",):
                adr = get_agent_def_registry()
                defs = adr.get_all()
                if not defs:
                    console.print("[dim]No agent definitions found.[/dim]")
                    console.print("[dim]Add .md files to .claude/agents/ or ~/.claude/agents/[/dim]")
                else:
                    console.print(f"[dim]{len(defs)} agent definition(s):[/dim]")
                    for d in defs:
                        console.print(f"  [bold cyan]{d.name}[/bold cyan] — {d.description or '(no description)'} [dim][{d.source}][/dim]")
                continue

            if text.lower() in ("/instances",):
                istore = get_instance_store()
                instances = istore.list_all()
                if not instances:
                    console.print("[dim]No instances.[/dim]")
                else:
                    for inst in instances:
                        color = {
                            "running": "green", "paused": "yellow",
                            "stopped": "dim", "created": "cyan",
                        }.get(inst.state, "white")
                        console.print(f"  [{color}]{inst.summary()}[/{color}]")
                continue

            if text.lower() in ("/agent",):
                # Show current agent info
                ad = conv.agent_def
                console.print(f"[dim]Current agent: {ad.name}[/dim]")
                if ad.description:
                    console.print(f"[dim]  Description: {ad.description}[/dim]")
                if ad.model:
                    console.print(f"[dim]  Model: {ad.model}[/dim]")
                if ad.tools is not None:
                    console.print(f"[dim]  Tools: {', '.join(ad.tools)}[/dim]")
                console.print(f"[dim]  Instance: #{conv.instance.id} ({conv.instance.state})[/dim]")
                continue

            # Slash command → skill invocation
            # If user types /something, try to invoke it as a skill directly
            if text.startswith("/") and not text.startswith("/permission"):
                parts = text.split(maxsplit=1)
                skill_name = parts[0].lstrip("/")
                skill_args = parts[1] if len(parts) > 1 else ""
                registry = get_registry()
                skill = registry.get(skill_name)
                if skill:
                    # Inject the skill prompt as a user message
                    prompt_content = skill.get_prompt_for_command(skill_args)
                    conv.add_user_message(prompt_content)
                    conv.run_turn()
                    continue
                # Not a known skill - pass through to model as normal text

            # Add message and run
            conv.add_user_message(text)
            conv.run_turn()

        except KeyboardInterrupt:
            console.print("\n[dim](interrupted)[/dim]")
            continue
        except EOFError:
            console.print("\n[dim]Goodbye![/dim]")
            break
