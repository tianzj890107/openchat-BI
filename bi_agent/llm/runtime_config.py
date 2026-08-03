"""Runtime config for LLM selection and params.

Single in-process singleton. Persisted to ~/.claude/bi_agent_llm.json so
settings survive server restarts. Updated via POST /api/config from the UI.

API keys are a separate concern — they live in ~/.claude/config.json (the
same file open_claude.config reads from) under keys `api_key` (Anthropic)
and `dashscope_api_key` (Qwen). Helpers at the bottom update that file.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Optional

from .registry import get_default_model_key, get_model


_CONFIG_PATH = Path.home() / ".claude" / "bi_agent_llm.json"

_MIN_MAX_TOKENS = 256
_MAX_MAX_TOKENS = 200_000
_MIN_TEMP = 0.0
_MAX_TEMP = 2.0


class RuntimeConfig:
    def __init__(self) -> None:
        key = get_default_model_key()
        m = get_model(key) or {}
        self.model_key: str = key
        self.max_tokens: int = int(m.get("default_max_tokens", 8192))
        self.temperature: float = float(m.get("default_temperature", 1.0))
        # Extended-thinking toggle. Only applied when the active model
        # advertises supports_thinking=True; providers ignore it otherwise.
        self.thinking: bool = False
        self._load()

    # -------------------------
    # I/O
    # -------------------------
    def _load(self) -> None:
        if not _CONFIG_PATH.exists():
            return
        try:
            data = json.loads(_CONFIG_PATH.read_text(encoding="utf-8"))
        except Exception:
            return
        mk = data.get("model_key")
        forced_provider = os.environ.get("LLM_PROVIDER", "").strip().lower()
        persisted_model = get_model(mk) if isinstance(mk, str) else None
        # A deployment-level provider choice must win over a stale browser
        # preference persisted on this machine (for example an old Claude
        # choice when the server is now configured for Qwen).
        if persisted_model is not None and (
            not forced_provider or persisted_model["provider"] == forced_provider
        ):
            self.model_key = mk
        mt = data.get("max_tokens")
        if isinstance(mt, int) and _MIN_MAX_TOKENS <= mt <= _MAX_MAX_TOKENS:
            self.max_tokens = mt
        t = data.get("temperature")
        if isinstance(t, (int, float)) and _MIN_TEMP <= float(t) <= _MAX_TEMP:
            self.temperature = float(t)
        thk = data.get("thinking")
        if isinstance(thk, bool):
            self.thinking = thk

    def _save(self) -> None:
        _CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
        _CONFIG_PATH.write_text(
            json.dumps(self.to_dict(), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    # -------------------------
    # Mutation
    # -------------------------
    def update(
        self,
        *,
        model_key: Optional[str] = None,
        max_tokens: Optional[int] = None,
        temperature: Optional[float] = None,
        thinking: Optional[bool] = None,
    ) -> None:
        if model_key is not None:
            if get_model(model_key) is None:
                raise ValueError(f"Unknown model_key: {model_key}")
            self.model_key = model_key
        if max_tokens is not None:
            mt = int(max_tokens)
            if not (_MIN_MAX_TOKENS <= mt <= _MAX_MAX_TOKENS):
                raise ValueError(
                    f"max_tokens out of range [{_MIN_MAX_TOKENS}, {_MAX_MAX_TOKENS}]"
                )
            self.max_tokens = mt
        if temperature is not None:
            t = float(temperature)
            if not (_MIN_TEMP <= t <= _MAX_TEMP):
                raise ValueError(
                    f"temperature out of range [{_MIN_TEMP}, {_MAX_TEMP}]"
                )
            self.temperature = t
        if thinking is not None:
            self.thinking = bool(thinking)
        self._save()

    @property
    def effective_thinking(self) -> bool:
        """`thinking` flag intersected with the active model's capability."""
        if not self.thinking:
            return False
        m = get_model(self.model_key) or {}
        return bool(m.get("supports_thinking", False))

    def to_dict(self) -> dict[str, Any]:
        return {
            "model_key": self.model_key,
            "max_tokens": self.max_tokens,
            "temperature": self.temperature,
            "thinking": self.thinking,
        }


_instance: Optional[RuntimeConfig] = None


def get_config() -> RuntimeConfig:
    global _instance
    if _instance is None:
        _instance = RuntimeConfig()
    return _instance


# ---------------------------------------------------------------------------
# API key management
# ---------------------------------------------------------------------------
# Keys are persisted into ~/.claude/config.json so both the Anthropic
# provider (open_claude.config.get_api_key) and the Qwen provider
# (bi_agent.llm.provider_qwen._get_api_key) pick them up automatically.

_CLAUDE_CONFIG_PATH = Path.home() / ".claude" / "config.json"

# Field name inside config.json → environment variable that shadows it.
_KEY_FIELDS = {
    "anthropic": ("api_key", ("ANTHROPIC_API_KEY",)),
    # DashScope documents DASHSCOPE_API_KEY, while this deployment uses the
    # clearer QWEN_API_KEY alias. Both must be visible to the UI status API.
    "qwen":      ("dashscope_api_key", ("DASHSCOPE_API_KEY", "QWEN_API_KEY")),
    "deepseek":  ("deepseek_api_key", ("DEEPSEEK_API_KEY",)),
    "team":      ("team_api_key", ("TEAM_API_KEY",)),
}


def _load_claude_config() -> dict[str, Any]:
    if _CLAUDE_CONFIG_PATH.exists():
        try:
            return json.loads(_CLAUDE_CONFIG_PATH.read_text(encoding="utf-8"))
        except Exception:
            return {}
    return {}


def _save_claude_config(data: dict[str, Any]) -> None:
    _CLAUDE_CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
    _CLAUDE_CONFIG_PATH.write_text(
        json.dumps(data, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def _mask_key(key: Optional[str]) -> Optional[str]:
    if not key:
        return None
    s = str(key)
    if len(s) <= 8:
        return "****"
    return f"{s[:4]}…{s[-4:]}"


def get_api_key_status() -> dict[str, dict[str, Any]]:
    """Return per-provider key status, with source annotation (env vs file).

    Never returns the raw key — only masked preview + where it comes from.
    """
    cfg = _load_claude_config()
    out: dict[str, dict[str, Any]] = {}
    for name, (file_key, env_keys) in _KEY_FIELDS.items():
        env_val = next((os.environ.get(k) for k in env_keys if os.environ.get(k)), None)
        file_val = cfg.get(file_key)
        key = env_val or file_val
        source = "env" if env_val else ("file" if file_val else None)
        out[name] = {
            "present": bool(key),
            "masked": _mask_key(key),
            "source": source,
            "env_var": " / ".join(env_keys),
        }
    return out


def set_api_key(provider: str, value: Optional[str]) -> None:
    """Persist a key to ~/.claude/config.json.

    - value=None or empty string → delete the field (if present).
    - Non-empty value → write it.

    Note: if the same key is also set as an environment variable, the env
    var still wins at read time (by design — env vars shadow file config).
    """
    if provider not in _KEY_FIELDS:
        raise ValueError(f"Unknown provider: {provider}")
    file_key, _ = _KEY_FIELDS[provider]
    cfg = _load_claude_config()
    if value is None or value == "":
        cfg.pop(file_key, None)
    else:
        cfg[file_key] = value.strip()
    _save_claude_config(cfg)
