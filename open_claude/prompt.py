"""System prompt construction for Open Claude."""

import datetime
import os
import subprocess
from .claudemd import build_memory_prompt
from .config import get_environment_info


def _get_git_info(cwd: str) -> str:
    """Get git status info if in a git repo."""
    if not os.path.isdir(os.path.join(cwd, ".git")):
        return ""
    parts = []
    try:
        branch = subprocess.run(
            ["git", "rev-parse", "--abbrev-ref", "HEAD"],
            capture_output=True, text=True, cwd=cwd, timeout=5,
        )
        if branch.returncode == 0:
            parts.append(f"  Git branch: {branch.stdout.strip()}")

        status = subprocess.run(
            ["git", "status", "--short"],
            capture_output=True, text=True, cwd=cwd, timeout=5,
        )
        if status.returncode == 0 and status.stdout.strip():
            lines = status.stdout.strip().split("\n")
            parts.append(f"  Modified files: {len(lines)}")
    except Exception:
        pass
    return "\n".join(parts)


def _get_skills_listing() -> str:
    """Build the skills listing for the system prompt."""
    from .skills.registry import get_registry

    registry = get_registry()
    skills = registry.get_all()
    if not skills:
        return ""

    lines = []
    # User-invocable skills (slash commands)
    user_skills = [s for s in skills if s.user_invocable]
    if user_skills:
        lines.append("\nThe following skills are available for use with the Skill tool:\n")
        for s in user_skills:
            entry = f"- {s.name}"
            if s.description:
                entry += f": {s.description[:250]}"
            if s.when_to_use:
                trigger = s.when_to_use[:200]
                entry += f" - {trigger}"
            lines.append(entry)

    # Model-invocable skills (auto-trigger)
    model_skills = [s for s in skills if s.when_to_use and not s.user_invocable]
    for s in model_skills:
        entry = f"- {s.name}: {s.description[:250]}"
        if s.when_to_use:
            entry += f"\n  TRIGGER when: {s.when_to_use[:200]}"
        lines.append(entry)

    return "\n".join(lines)


def _get_project_structure(cwd: str) -> str:
    """Detect project type and key files."""
    indicators = {
        "package.json": "Node.js",
        "pyproject.toml": "Python",
        "setup.py": "Python",
        "requirements.txt": "Python",
        "Cargo.toml": "Rust",
        "go.mod": "Go",
        "pom.xml": "Java (Maven)",
        "build.gradle": "Java (Gradle)",
        "Gemfile": "Ruby",
        "composer.json": "PHP",
        "CMakeLists.txt": "C/C++ (CMake)",
        "Makefile": "Make",
        "Dockerfile": "Docker",
        "docker-compose.yml": "Docker Compose",
        ".env": "Environment config",
    }
    found = []
    for fname, ptype in indicators.items():
        if os.path.exists(os.path.join(cwd, fname)):
            found.append(ptype)

    if not found:
        return ""

    # Deduplicate
    seen = set()
    unique = []
    for f in found:
        if f not in seen:
            seen.add(f)
            unique.append(f)

    return f"  Project type: {', '.join(unique)}"


def build_system_prompt(cwd: str) -> str:
    """Build the full system prompt."""
    env = get_environment_info()
    today = datetime.date.today().isoformat()
    git_info = _get_git_info(cwd)
    skills_listing = _get_skills_listing()
    memory_prompt = build_memory_prompt(cwd)
    project_info = _get_project_structure(cwd)

    prompt = f"""You are Open Claude, an interactive CLI assistant for software engineering tasks.
You help users with coding, debugging, file operations, and shell commands.

# Tools
You have access to the following tools:
- **Bash**: Execute shell commands
- **Read**: Read file contents with line numbers
- **Write**: Create or overwrite files
- **Edit**: Perform exact string replacements in files
- **Glob**: Search for files by pattern
- **Grep**: Search file contents with regex
- **Skill**: Execute a skill (slash command) for specialized tasks
- **TaskCreate/TaskUpdate/TaskList/TaskGet**: Track multi-step work with tasks
- **Agent**: Launch a sub-agent for complex, multi-step tasks in an isolated context

# Skills
When users reference a slash command like "/commit" or "/review", use the Skill tool to invoke it.
{skills_listing if skills_listing else "No skills currently loaded."}

# Guidelines
- Read files before editing them to understand existing code.
- Use the appropriate tool: Read instead of `cat`, Edit instead of `sed`, Glob instead of `find`, Grep instead of `grep`.
- Break complex tasks into smaller steps.
- Be concise in your responses. Lead with the answer, not the reasoning.
- When referencing code, include file_path:line_number.
- Do not add unnecessary features, refactoring, or comments beyond what was asked.
- Be careful not to introduce security vulnerabilities.
- Prefer editing existing files over creating new ones.

# Doing Tasks
- Understand existing code before modifying it.
- If an approach fails, diagnose why before switching tactics.
- Only use Bash for operations that require shell execution.
- For file operations, prefer dedicated tools (Read, Write, Edit, Glob, Grep).

# Safety
- For destructive or hard-to-reverse operations, confirm with the user first.
- Do not delete files, force-push, or reset without explicit permission.
- Validate at system boundaries (user input, external APIs).

# Environment
- Working directory: {env['cwd']}
- Platform: {env['platform']}
- OS: {env['os_version']}
- Git repo: {env['is_git_repo']}
- Date: {today}
{"- Shell: The Bash tool supports Unix commands (rm, ls, grep, etc.), PowerShell cmdlets (Remove-Item, Get-ChildItem, etc.), and Windows commands (del, dir, etc.). Use whichever syntax is most appropriate." if env['platform'] == "windows" else "- Shell: bash"}
"""
    if project_info:
        prompt += f"\n# Project\n{project_info}\n"

    if git_info:
        prompt += f"\n# Git Status\n{git_info}\n"

    if memory_prompt:
        prompt += f"\n# User & Project Instructions\n{memory_prompt}\n"

    return prompt
