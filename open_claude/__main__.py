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

    # Check API key
    from .config import get_api_key
    if not get_api_key():
        print("Error: No API key found.", file=sys.stderr)
        print("Set ANTHROPIC_API_KEY environment variable or add to ~/.claude/config.json", file=sys.stderr)
        sys.exit(1)

    permission_mode = "always_allow" if args.dangerously_skip_permissions else "default"

    if args.prompt:
        # Non-interactive: single prompt mode
        _run_single_prompt(args.prompt, cwd, permission_mode)
    else:
        # Interactive REPL
        from .repl import run_repl
        run_repl(cwd, permission_mode=permission_mode)


def _run_single_prompt(prompt: str, cwd: str, permission_mode: str = "default"):
    """Run a single prompt and exit."""
    from rich.console import Console
    from .repl import Conversation

    console = Console()
    conv = Conversation(cwd, permission_mode=permission_mode)
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
