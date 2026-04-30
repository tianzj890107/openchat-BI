"""Model registry — UI label → (provider, model_id, defaults).

Edit `MODELS` to change the catalog. Qwen model_id strings are sent verbatim
to DashScope's OpenAI-compatible endpoint; if your account exposes snapshot
IDs (e.g. qwen-plus-2025-07-28), put them here.

`supports_thinking: True` adds an "extended thinking" toggle in the UI for
that model. The provider is responsible for translating the runtime
`thinking` flag into its native parameter (Anthropic: `thinking={…}`,
DeepSeek: `extra_body={"thinking": {"type": "enabled"}}`).
"""

from __future__ import annotations

from typing import Any, Optional


MODELS: list[dict[str, Any]] = [
    {
        "key": "opus4.7",
        "label": "Claude Opus 4.7",
        "provider": "anthropic",
        "model_id": "claude-opus-4-7",
        "default_max_tokens": 16384,
        "default_temperature": 1.0,
        "max_output_tokens": 32000,
        "supports_thinking": True,
    },
    {
        "key": "opus4.6",
        "label": "Claude Opus 4.6",
        "provider": "anthropic",
        "model_id": "claude-opus-4-6",
        "default_max_tokens": 16384,
        "default_temperature": 1.0,
        "max_output_tokens": 64000,
        "supports_thinking": True,
    },
    {
        "key": "sonnet4.6",
        "label": "Claude Sonnet 4.6",
        "provider": "anthropic",
        "model_id": "claude-sonnet-4-6",
        "default_max_tokens": 16384,
        "default_temperature": 1.0,
        "max_output_tokens": 32000,
        "supports_thinking": True,
    },
    {
        "key": "qwen3.6-plus",
        "label": "Qwen 3.6 Plus",
        "provider": "qwen",
        "model_id": "qwen3-plus",
        "default_max_tokens": 8192,
        "default_temperature": 0.7,
        "max_output_tokens": 8192,
        "supports_thinking": False,
    },
    {
        "key": "qwen3.5-plus",
        "label": "Qwen 3.5 Plus",
        "provider": "qwen",
        "model_id": "qwen-plus-latest",
        "default_max_tokens": 8192,
        "default_temperature": 0.7,
        "max_output_tokens": 8192,
        "supports_thinking": False,
    },
    {
        "key": "qwen-plus",
        "label": "Qwen Plus",
        "provider": "qwen",
        "model_id": "qwen-plus",
        "default_max_tokens": 8192,
        "default_temperature": 0.7,
        "max_output_tokens": 8192,
        "supports_thinking": False,
    },
    {
        "key": "deepseek-v4-flash",
        "label": "DeepSeek V4 Flash",
        "provider": "deepseek",
        "model_id": "deepseek-v4-flash",
        "default_max_tokens": 8192,
        "default_temperature": 0.7,
        "max_output_tokens": 16384,
        "supports_thinking": True,
    },
    {
        "key": "deepseek-v4-pro",
        "label": "DeepSeek V4 Pro",
        "provider": "deepseek",
        "model_id": "deepseek-v4-pro",
        "default_max_tokens": 8192,
        "default_temperature": 0.7,
        "max_output_tokens": 32768,
        "supports_thinking": True,
    },
]


def list_models() -> list[dict[str, Any]]:
    """Lightweight list for UI (no internal model_id)."""
    return [
        {
            "key": m["key"],
            "label": m["label"],
            "provider": m["provider"],
            "default_max_tokens": m["default_max_tokens"],
            "default_temperature": m["default_temperature"],
            "max_output_tokens": m["max_output_tokens"],
            "supports_thinking": bool(m.get("supports_thinking", False)),
        }
        for m in MODELS
    ]


def get_model(key: str) -> Optional[dict[str, Any]]:
    for m in MODELS:
        if m["key"] == key:
            return m
    return None


def get_default_model_key() -> str:
    return MODELS[0]["key"]
