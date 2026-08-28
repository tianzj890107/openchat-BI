# Open Claude

An open-source AI coding assistant CLI, powered by Anthropic's Claude API. Inspired by [Claude Code](https://docs.anthropic.com/en/docs/claude-code), built from scratch in Python.

> 本仓库同时承载 **openchat-BI（智能分析）** Web 应用。当前版本：`v0.1.0`
>
> - [正式版本文档](docs/versions/v0.1.0.md)
> - [版本索引](docs/versions/README.md)
> - [版本管理规范](docs/versions/versioning-policy.md)
> - [Git 双远端工作流](docs/git-dual-remote-workflow.md)
>
> commit、push、部署不自动触发版本升级；正式版本变更必须由用户明确指定目标版本。

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

## Prerequisites

- **Python 3.10+** ([download](https://www.python.org/downloads/))
- **Anthropic API Key** - get one at https://console.anthropic.com/
- **Git** (optional, for `/commit`, `/review` and other git-related skills)

## Quick Start

```bash
# 1. Clone the repo
git clone https://github.com/YOUR_USERNAME/open-claude.git
cd open-claude

# 2. (Recommended) Create a virtual environment
python -m venv .venv

# Activate it:
#   Windows (PowerShell):
.venv\Scripts\Activate.ps1
#   Windows (cmd):
.venv\Scripts\activate.bat
#   macOS / Linux:
source .venv/bin/activate

# 3. Install open-claude and all dependencies
#    This installs the `open-claude` command to your PATH
#    so you can run it from anywhere.
pip install -e .

# 4. Set your Anthropic API key
#   Windows (PowerShell):
$env:ANTHROPIC_API_KEY = "sk-ant-your-key-here"
#   Windows (cmd):
set ANTHROPIC_API_KEY=sk-ant-your-key-here
#   macOS / Linux:
export ANTHROPIC_API_KEY="sk-ant-your-key-here"

# 5. Run!
open-claude
```

> **Tip**: To avoid setting the API key every time, add the `export` / `$env:` line to your shell profile (`~/.bashrc`, `~/.zshrc`, or PowerShell `$PROFILE`), or save it in the config file (see below).

### What does `pip install -e .` do?

It reads `pyproject.toml` and:

1. Installs dependencies: `anthropic`, `rich`, `prompt_toolkit`
2. Registers the `open-claude` command on your PATH (via `[project.scripts]`)
3. `-e` (editable) means changes to the source code take effect immediately without reinstalling

After this step, you can run `open-claude` from any directory.

### Alternative: Run without installing

If you don't want to `pip install`, install dependencies manually and run as a Python module:

```bash
pip install anthropic rich prompt_toolkit
python -m open_claude

# or
python scripts/run.py
```

Note: this way you won't have the `open-claude` command, you'll need to use `python -m open_claude` every time.

## Configuration

### API Key

You have two options:

**Option A** - Environment variable (recommended):

```bash
export ANTHROPIC_API_KEY="sk-ant-..."
```

**Option B** - Config file at `~/.claude/config.json`:

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

### Interactive Mode (REPL)

```bash
open-claude
```

This opens an interactive chat session. Type your message, press Enter, and the assistant will respond with streaming output. It can read/write files, run shell commands, search your codebase, and more.

### Single Prompt Mode

```bash
# Run one prompt and exit (useful for scripting)
open-claude -p "explain the main function in src/app.py"
```

### CLI Options

```
open-claude [OPTIONS]

Options:
  -v, --version                 Show version and exit
  -p, --prompt TEXT             Run a single prompt and exit
  --model MODEL                 Model override (e.g. claude-opus-4-20250514)
  --cwd PATH                    Set working directory
  --dangerously-skip-permissions  Auto-approve all tool executions
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

Example skill file (`.claude/skills/commit/SKILL.md`):

```markdown
---
description: Commit and push the current changes (no deployment)
user-invocable: true
---

Deliver finished work with the default workflow.
1. Run tests first
2. Review `git diff` and run `git diff --check`
3. Commit the relevant files only
4. Push to the current remote branch (dual remotes: `origin/20260727` and
   `personal/main`)
5. Do not deploy — deployment requires an explicit user instruction
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

## Troubleshooting

**`No API key found`** - Set `ANTHROPIC_API_KEY` environment variable or add it to `~/.claude/config.json`.

**`'anthropic' package not installed`** - Run `pip install anthropic` (or `pip install -e .` if you cloned the repo).

**`python: command not found`** - Try `python3` instead, or ensure Python 3.10+ is installed and on your PATH.

**Windows: `open-claude` command not found after install** - Make sure your Python Scripts directory is on PATH. Alternatively, use `python -m open_claude`.

**Permission denied on tool execution** - The default mode asks before running Bash/Write/Edit. Press `y` to allow, `a` to always allow that tool, or `A` to allow all. You can also start with `--dangerously-skip-permissions`.

## License

MIT
