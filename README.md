# Open Claude

An open-source AI coding assistant CLI, powered by Anthropic's Claude API. Inspired by [Claude Code](https://docs.anthropic.com/en/docs/claude-code), built from scratch in Python.

## Features

- **Interactive REPL** with streaming responses and rich terminal UI
- **12 built-in tools**: Bash, Read, Write, Edit, Glob, Grep, Skill, TaskCreate, TaskUpdate, TaskList, TaskGet, Agent
- **Permission system** - approve/deny dangerous operations (Bash, Write, Edit) with per-tool and global controls
- **Skills (slash commands)** - bundled (`/commit`, `/review`, `/test`, `/fix`, `/explain`, `/simplify`) and user-defined
- **CLAUDE.md support** - project instructions via `CLAUDE.md`, `.claude/CLAUDE.md`, `.claude/rules/*.md`
- **Conversation compaction** - auto-summarizes when approaching context window limit
- **Token tracking & cost display** - per-model pricing, context usage monitoring
- **Sub-agent system** - spawn isolated sub-conversations for complex multi-step tasks
- **Task management** - track multi-step work with in-memory task system
- **Cross-platform** - Windows (Git Bash / PowerShell / cmd fallback), macOS, Linux

## Installation

```bash
# Clone the repo
git clone https://github.com/YOUR_USERNAME/open-claude.git
cd open-claude

# Install dependencies
pip install -e .
```

### Requirements

- Python 3.10+
- An [Anthropic API key](https://console.anthropic.com/)

## Configuration

Set your API key via environment variable:

```bash
export ANTHROPIC_API_KEY="sk-ant-..."
```

Or add it to `~/.claude/config.json`:

```json
{
  "api_key": "sk-ant-...",
  "model": "claude-sonnet-4-20250514"
}
```

### Environment Variables

| Variable | Description | Default |
|---|---|---|
| `ANTHROPIC_API_KEY` | Your Anthropic API key | (required) |
| `CLAUDE_MODEL` | Model to use | `claude-sonnet-4-20250514` |
| `CLAUDE_MAX_TOKENS` | Max output tokens | `16384` |

## Usage

```bash
# Interactive REPL
open-claude

# Or run directly
python -m open_claude

# Single prompt (non-interactive)
open-claude -p "explain this codebase"

# With a specific model
open-claude --model claude-opus-4-20250514

# Auto-approve all tool executions
open-claude --dangerously-skip-permissions

# Specify working directory
open-claude --cwd /path/to/project
```

### REPL Commands

| Command | Description |
|---|---|
| `/help` | Show help |
| `/clear` | Clear conversation history |
| `/compact` | Manually compact conversation |
| `/cost` | Show token usage and cost |
| `/model` | Show current model |
| `/tasks` | Show current tasks |
| `/skills` | List all available skills |
| `/permission` | Show/change permission mode |
| `quit` | Exit |

### Built-in Skills

| Skill | Description |
|---|---|
| `/commit` | Generate a git commit from current changes |
| `/review` | Review code changes or a pull request |
| `/test` | Find and run the project's tests |
| `/fix` | Diagnose and fix a bug or error |
| `/explain` | Explain code or a file |
| `/simplify` | Review and simplify changed code |

### Custom Skills

Create your own skills by adding `.md` files to:

- `~/.claude/skills/` (global, personal)
- `.claude/skills/` (project-specific)

Example skill file (`.claude/skills/deploy/SKILL.md`):

```markdown
---
description: Deploy to production
user-invocable: true
argument-hint: <environment>
---

Deploy the application to the specified environment.
1. Run tests first
2. Build the project
3. Deploy using the project's deploy script
```

### CLAUDE.md

Add a `CLAUDE.md` file to your project root to provide persistent instructions:

```markdown
# Project Rules
- Always use type hints in Python code
- Run `pytest` before committing
- Use conventional commit messages
```

Supports: `CLAUDE.md`, `.claude/CLAUDE.md`, `.claude/rules/*.md`, `CLAUDE.local.md`, `~/.claude/CLAUDE.md`

## Architecture

```
open_claude/
  __init__.py       # Version
  __main__.py       # CLI entry point (argparse)
  config.py         # API key, model, environment detection
  api.py            # Anthropic API client (streaming + sync)
  tools.py          # Tool schemas + executors (Bash, Read, Write, Edit, Glob, Grep, Skill)
  tasks.py          # In-memory task management system
  agent.py          # Sub-agent spawning (isolated conversations)
  repl.py           # Interactive REPL, permission system, display
  prompt.py         # System prompt construction
  tokens.py         # Token estimation, context window, cost tracking
  compact.py        # Conversation compaction (summarization)
  claudemd.py       # CLAUDE.md discovery and loading
  skills/
    __init__.py
    frontmatter.py  # YAML frontmatter parser
    registry.py     # Skill registry, discovery, loading
    bundled.py      # Built-in skills (/commit, /review, etc.)
```

## License

MIT
