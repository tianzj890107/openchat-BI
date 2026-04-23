"""Entry point for Open Claude: python -m open_claude"""

import argparse
import os
import sys


def main():
    parser = argparse.ArgumentParser(
        prog="open-claude",
        description="Open Claude - AI coding assistant",
    )
    parser.add_argument(
        "--version", "-v", action="store_true",
        help="Show version and exit",
    )
    parser.add_argument(
        "--cwd", type=str, default=None,
        help="Working directory (default: current directory)",
    )
    parser.add_argument(
        "--model", type=str, default=None,
        help="Model to use (overrides CLAUDE_MODEL env var)",
    )
    parser.add_argument(
        "-p", "--prompt", type=str, default=None,
        help="Run a single prompt (non-interactive mode) and exit",
    )
    parser.add_argument(
        "--dangerously-skip-permissions", action="store_true",
        help="Auto-approve all tool executions without asking (use with caution)",
    )
    parser.add_argument(
        "--agent", type=str, default=None,
        help="Agent definition name to use (e.g. 'code-reviewer'). "
             "See .claude/agents/ for available definitions.",
    )
    parser.add_argument(
        "--list-agents", action="store_true",
        help="List available agent definitions and exit",
    )

    args = parser.parse_args()

    if args.version:
        from . import __version__
        print(f"{__version__} (Open Claude)")
        return

    # Set model override
    if args.model:
        os.environ["CLAUDE_MODEL"] = args.model

    cwd = args.cwd or os.getcwd()
    if not os.path.isdir(cwd):
        print(f"Error: Directory not found: {cwd}", file=sys.stderr)
        sys.exit(1)

    # Check dependencies
    try:
        import anthropic
    except ImportError:
        print("Error: 'anthropic' package not installed.", file=sys.stderr)
        print("Run: pip install anthropic", file=sys.stderr)
        sys.exit(1)

    try:
        import rich
    except ImportError:
        print("Error: 'rich' package not installed.", file=sys.stderr)
        print("Run: pip install rich", file=sys.stderr)
        sys.exit(1)

    # Load agent definitions early (needed for --list-agents and --agent)
    from .agent_def import load_agent_defs, get_agent_def_registry
    load_agent_defs(cwd)

    # --list-agents: show available definitions and exit
    if args.list_agents:
        registry = get_agent_def_registry()
        defs = registry.get_all()
        if not defs:
            print("No agent definitions found.")
            print("Add .md files to .claude/agents/ or ~/.claude/agents/")
        else:
            print(f"{len(defs)} agent definition(s):")
            for d in defs:
                model_hint = f" (model: {d.model})" if d.model else ""
                print(f"  {d.name}{model_hint} — {d.description or '(no description)'}  [{d.source}]")
        return

    # Check API key
    from .config import get_api_key
    if not get_api_key():
        print("Error: No API key found.", file=sys.stderr)
        print("Set ANTHROPIC_API_KEY environment variable or add to ~/.claude/config.json", file=sys.stderr)
        sys.exit(1)

    # Resolve agent definition
    agent_def = None
    if args.agent:
        registry = get_agent_def_registry()
        agent_def = registry.get(args.agent)
        if not agent_def:
            print(f"Error: Unknown agent '{args.agent}'.", file=sys.stderr)
            available = registry.list_names()
            if available:
                print(f"Available agents: {', '.join(available)}", file=sys.stderr)
            else:
                print("No agent definitions found. Add .md files to .claude/agents/", file=sys.stderr)
            sys.exit(1)

    permission_mode = "always_allow" if args.dangerously_skip_permissions else "default"

    if args.prompt:
        # Non-interactive: single prompt mode
        _run_single_prompt(args.prompt, cwd, permission_mode, agent_def=agent_def)
    else:
        # Interactive REPL
        from .repl import run_repl
        run_repl(cwd, permission_mode=permission_mode, agent_def=agent_def)


def _run_single_prompt(prompt: str, cwd: str, permission_mode: str = "default", agent_def=None):
    """Run a single prompt and exit."""
    from rich.console import Console
    from .repl import Conversation

    console = Console()
    conv = Conversation(cwd, permission_mode=permission_mode, agent_def=agent_def)
    conv.add_user_message(prompt)

    try:
        conv.run_turn()
    except KeyboardInterrupt:
        console.print("\n[dim](interrupted)[/dim]")
    except Exception as e:
        console.print(f"[bold red]Error: {e}[/bold red]")
        sys.exit(1)


if __name__ == "__main__":
    main()
