"""Configuration management for Open Claude."""

import json
import os
import platform
from pathlib import Path
from typing import Any, Optional


def get_home_dir() -> Path:
    return Path.home()


def get_claude_dir() -> Path:
    d = get_home_dir() / ".claude"
    d.mkdir(parents=True, exist_ok=True)
    return d


def get_config_path() -> Path:
    return get_claude_dir() / "config.json"


def load_config() -> dict[str, Any]:
    path = get_config_path()
    if path.exists():
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            pass
    return {}


def get_api_key() -> Optional[str]:
    """Get API key from env var or config file."""
    key = os.environ.get("ANTHROPIC_API_KEY")
    if key:
        return key
    cfg = load_config()
    return cfg.get("api_key")


def get_model() -> str:
    """Get model name from env var or config, default to claude-sonnet-4-20250514."""
    model = os.environ.get("CLAUDE_MODEL") or os.environ.get("ANTHROPIC_MODEL")
    if model:
        return model
    cfg = load_config()
    return cfg.get("model", "claude-sonnet-4-20250514")


def get_max_tokens() -> int:
    val = os.environ.get("CLAUDE_MAX_TOKENS")
    if val:
        return int(val)
    return 16384


def get_environment_info() -> dict[str, str]:
    """Gather environment info for system prompt."""
    cwd = os.getcwd()
    system = platform.system()
    release = platform.release()
    is_git = os.path.isdir(os.path.join(cwd, ".git"))

    # Detect shell
    shell = os.environ.get("SHELL", "")
    if not shell:
        shell = "powershell" if system == "Windows" else "bash"

    return {
        "cwd": cwd,
        "platform": system.lower(),
        "os_version": f"{system} {release}",
        "shell": os.path.basename(shell) if "/" in shell or "\\" in shell else shell,
        "is_git_repo": str(is_git).lower(),
    }
