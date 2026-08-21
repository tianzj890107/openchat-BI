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

import os
from typing import Any, Optional


MODELS: list[dict[str, Any]] = [
    {
        "key": "team-configured",
        "label": "团队 API（环境配置） · " + (
            os.environ.get("TEAM_MODEL") or "Qwen/Qwen3-80B-AWQ"
        ),
        "provider": "team",
        "model_id": os.environ.get("TEAM_MODEL") or "Qwen/Qwen3-80B-AWQ",
        "default_max_tokens": 8192,
        "default_temperature": 0.7,
        "max_output_tokens": 16384,
        "supports_thinking": False,
    },
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
        "key": "qwen-configured",
        "label": "Qwen 文本（环境配置） · " + (
            os.environ.get("QWEN_PREFERRED_TEXT_MODEL")
            or os.environ.get("QWEN_TEXT_MODEL")
            or "qwen-plus"
        ),
        "provider": "qwen",
        # Keep the actual deployment model in environment configuration. This
        # lets private DashScope-compatible gateways use an account-specific
        # model name without a source-code change.
        "model_id": (
            os.environ.get("QWEN_PREFERRED_TEXT_MODEL")
            or os.environ.get("QWEN_TEXT_MODEL")
            or "qwen-plus"
        ),
        "default_max_tokens": 8192,
        "default_temperature": 0.7,
        "max_output_tokens": 8192,
        "supports_thinking": False,
    },
    {
        "key": "qwen-vision-configured",
        "label": "Qwen 视觉（环境配置） · " + (
            os.environ.get("QWEN_PREFERRED_VISION_MODEL")
            or os.environ.get("QWEN_MODEL")
            or "qwen-vl-max"
        ),
        "provider": "qwen",
        "model_id": (
            os.environ.get("QWEN_PREFERRED_VISION_MODEL")
            or os.environ.get("QWEN_MODEL")
            or "qwen-vl-max"
        ),
        "default_max_tokens": 8192,
        "default_temperature": 0.7,
        "max_output_tokens": 8192,
        "supports_thinking": False,
    },
    {
        "key": "qwen3.7-max",
        "label": "Qwen 3.7 Max",
        "provider": "qwen",
        "model_id": "qwen3.7-max",
        "default_max_tokens": 8192,
        "default_temperature": 0.7,
        "max_output_tokens": 8192,
        "supports_thinking": False,
    },
    {
        "key": "qwen3.7-plus",
        "label": "Qwen 3.7 Plus",
        "provider": "qwen",
        "model_id": "qwen3.7-plus",
        "default_max_tokens": 8192,
        "default_temperature": 0.7,
        "max_output_tokens": 8192,
        "supports_thinking": False,
    },
    {
        "key": "qwen3.6-plus",
        "label": "Qwen 3.6 Plus",
        "provider": "qwen",
        "model_id": "qwen3.6-plus",
        "default_max_tokens": 8192,
        "default_temperature": 0.7,
        "max_output_tokens": 8192,
        "supports_thinking": False,
    },
    {
        "key": "qwen3.5-plus",
        "label": "Qwen 3.5 Plus",
        "provider": "qwen",
        "model_id": "qwen3.5-plus",
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


def _model_key(kind: str, model_id: str) -> str:
    """Make an HTML/API-safe, stable key from a provider model ID."""
    slug = "".join(c.lower() if c.isalnum() else "-" for c in model_id)
    slug = "-".join(part for part in slug.split("-") if part)
    return f"qwen-{kind}-{slug}"


def _load_qwen_catalog_from_env() -> None:
    """Expose every deployment-approved Qwen model in the web model picker.

    QWEN_VISION_MODELS and QWEN_TEXT_MODELS are comma-separated allowlists.
    They are intentionally configured in the environment so a private gateway
    can expose a different catalogue without changing application code.
    """
    existing_ids = {m["model_id"] for m in MODELS if m["provider"] == "qwen"}
    for kind, env_name, label_prefix in (
        ("vision", "QWEN_VISION_MODELS", "Qwen 视觉"),
        ("text", "QWEN_TEXT_MODELS", "Qwen 文本"),
    ):
        raw = os.environ.get(env_name, "")
        for model_id in (part.strip() for part in raw.split(",")):
            if not model_id or model_id in existing_ids:
                continue
            MODELS.append({
                "key": _model_key(kind, model_id),
                "label": f"{label_prefix} · {model_id}",
                "provider": "qwen",
                "model_id": model_id,
                "default_max_tokens": 8192,
                "default_temperature": 0.7,
                "max_output_tokens": 8192,
                "supports_thinking": False,
            })
            existing_ids.add(model_id)


def _team_model_key(model_id: str) -> str:
    slug = "".join(c.lower() if c.isalnum() else "-" for c in model_id)
    slug = "-".join(part for part in slug.split("-") if part)
    return f"team-{slug}"


def _load_team_catalog_from_env() -> None:
    """Expose all models routed by the shared team gateway."""
    existing_ids = {m["model_id"] for m in MODELS if m["provider"] == "team"}
    raw = os.environ.get("TEAM_MODELS", "")
    for model_id in (part.strip() for part in raw.split(",")):
        if not model_id or model_id in existing_ids:
            continue
        MODELS.append({
            "key": _team_model_key(model_id),
            "label": f"团队 API · {model_id}",
            "provider": "team",
            "model_id": model_id,
            "default_max_tokens": 8192,
            "default_temperature": 0.7,
            "max_output_tokens": 16384,
            "supports_thinking": False,
        })
        existing_ids.add(model_id)


_load_qwen_catalog_from_env()
_load_team_catalog_from_env()


def list_models() -> list[dict[str, Any]]:
    """Lightweight list for UI (no internal model_id).

    Team gateway models are pinned to the top of the picker so the
    deployment default stays in the first position; the remaining models
    keep their catalogue order.
    """
    ordered = [
        m for m in MODELS if m["provider"] == "team"
    ] + [
        m for m in MODELS if m["provider"] != "team"
    ]
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
        for m in ordered
    ]


def get_model(key: str) -> Optional[dict[str, Any]]:
    for m in MODELS:
        if m["key"] == key:
            return m
    return None


def fallback_model_keys(key: str) -> list[str]:
    """Return same-provider alternatives, preserving configured catalogue order."""
    current = get_model(key)
    if not current:
        return []
    provider = current["provider"]
    model_id = str(current.get("model_id", "")).lower()
    is_vision = "vision" in key.lower() or "-vl-" in model_id or model_id.startswith("qwen-vl")
    out: list[str] = []
    for model in MODELS:
        if model["provider"] != provider or model["key"] == key:
            continue
        candidate_id = str(model.get("model_id", "")).lower()
        candidate_vision = (
            "vision" in model["key"].lower()
            or "-vl-" in candidate_id
            or candidate_id.startswith("qwen-vl")
        )
        if provider == "qwen" and candidate_vision != is_vision:
            continue
        out.append(model["key"])
    return out


def get_default_model_key() -> str:
    """Choose a provider-specific default when deployment config requests it."""
    provider = os.environ.get("LLM_PROVIDER", "").strip().lower()
    if provider == "team":
        return "team-configured"
    if provider == "qwen":
        return "qwen-configured"
    return MODELS[0]["key"]
