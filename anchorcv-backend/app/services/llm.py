"""
Multi-provider LLM routing.

The whole legacy pipeline (anchor_core + legacy_bridge) talks to OpenAI through
``client.chat.completions.create(...)`` and only ever reads
``response.choices[0].message.content``.  ``RoutedChatClient`` reproduces that
exact interface and routes any ``claude-*`` model to the Anthropic Messages API
(via httpx — no extra SDK dependency), while every other model is delegated to
the real OpenAI client.  This makes the entire app multi-provider without
touching the quality-gated prompt pipeline.

Edit ``AVAILABLE_MODELS`` to add or remove models from the user-facing picker.
"""
import logging
import os
from types import SimpleNamespace

import httpx
from openai import OpenAI

from app.config import settings

logger = logging.getLogger(__name__)

ANTHROPIC_API_URL = "https://api.anthropic.com/v1/messages"
ANTHROPIC_VERSION = "2023-06-01"
ANTHROPIC_MAX_TOKENS = 4096

DEFAULT_MODEL = "gpt-4o-mini"

# Single source of truth for the model picker. ``tier`` is informational for
# the UI; ``provider`` decides routing.
AVAILABLE_MODELS = [
    {
        "id": "gpt-4o-mini",
        "label": "GPT-4o mini",
        "provider": "openai",
        "tier": "fast",
        "description": "Fast and reliable — the default.",
    },
    {
        "id": "gpt-4o",
        "label": "GPT-4o",
        "provider": "openai",
        "tier": "advanced",
        "description": "OpenAI's stronger general model.",
    },
    {
        "id": "claude-haiku-4-5",
        "label": "Claude Haiku 4.5",
        "provider": "anthropic",
        "tier": "fast",
        "description": "Anthropic's fast model — crisp, natural writing.",
    },
    {
        "id": "claude-sonnet-4-6",
        "label": "Claude Sonnet 4.6",
        "provider": "anthropic",
        "tier": "advanced",
        "description": "Anthropic's strongest writing model for CVs and letters.",
    },
]

ALLOWED_MODEL_IDS = {m["id"] for m in AVAILABLE_MODELS}


def list_available_models() -> list[dict]:
    """Models usable with the API keys currently configured."""
    models = []
    for model in AVAILABLE_MODELS:
        if model["provider"] == "openai" and not settings.openai_api_key:
            continue
        if model["provider"] == "anthropic" and not settings.anthropic_api_key:
            continue
        models.append(model)
    return models


def resolve_model(model: str | None) -> str:
    """Clamp arbitrary client input to the allowlist."""
    if model and model in ALLOWED_MODEL_IDS:
        return model
    return DEFAULT_MODEL


def _is_anthropic_model(model: str) -> bool:
    return (model or "").lower().startswith("claude")


def _to_openai_shape(text: str) -> SimpleNamespace:
    """Mimic the OpenAI chat-completion response shape the pipeline reads."""
    return SimpleNamespace(
        choices=[SimpleNamespace(message=SimpleNamespace(content=text))]
    )


def _call_anthropic_sync(
    model: str,
    messages: list[dict],
    temperature: float | None,
    max_tokens: int | None,
    response_format: dict | None,
) -> SimpleNamespace:
    api_key = settings.anthropic_api_key
    if not api_key:
        raise RuntimeError("Anthropic API is not configured (missing ANTHROPIC_API_KEY).")

    system_parts = [m.get("content", "") for m in messages if m.get("role") == "system"]
    chat_messages = [
        {"role": m["role"], "content": m.get("content", "")}
        for m in messages
        if m.get("role") in ("user", "assistant")
    ]
    if not chat_messages:
        chat_messages = [{"role": "user", "content": ""}]

    system = "\n\n".join(part for part in system_parts if part)
    if response_format and response_format.get("type") == "json_object":
        system = (system + "\n\n" if system else "") + (
            "Respond with a single valid JSON object only. "
            "No prose, no markdown code fences."
        )

    body = {
        "model": model,
        "max_tokens": max_tokens or ANTHROPIC_MAX_TOKENS,
        "messages": chat_messages,
    }
    if system:
        body["system"] = system
    if temperature is not None:
        # Anthropic accepts 0..1; OpenAI callers may pass up to 2.
        body["temperature"] = max(0.0, min(float(temperature), 1.0))

    headers = {
        "x-api-key": api_key,
        "anthropic-version": ANTHROPIC_VERSION,
        "content-type": "application/json",
    }

    with httpx.Client(timeout=120.0) as client:
        response = client.post(ANTHROPIC_API_URL, headers=headers, json=body)
        response.raise_for_status()
        data = response.json()

    text = "".join(
        block.get("text", "")
        for block in data.get("content", [])
        if block.get("type") == "text"
    ).strip()

    if not text:
        raise ValueError("Claude returned an empty response.")

    if response_format and response_format.get("type") == "json_object":
        # Claude occasionally wraps JSON in code fences despite instructions.
        if text.startswith("```"):
            text = text.strip("`")
            if text.lower().startswith("json"):
                text = text[4:]
            text = text.strip()

    return _to_openai_shape(text)


class _RoutedCompletions:
    def __init__(self, get_openai_client):
        self._get_openai_client = get_openai_client

    def create(self, **kwargs):
        model = kwargs.get("model") or DEFAULT_MODEL
        if _is_anthropic_model(model):
            return _call_anthropic_sync(
                model=model,
                messages=kwargs.get("messages") or [],
                temperature=kwargs.get("temperature"),
                max_tokens=kwargs.get("max_tokens"),
                response_format=kwargs.get("response_format"),
            )
        return self._get_openai_client().chat.completions.create(**kwargs)


class RoutedChatClient:
    """Drop-in replacement for the OpenAI client used by the legacy pipeline."""

    def __init__(self):
        self._openai_client = None
        self.chat = SimpleNamespace(
            completions=_RoutedCompletions(self._openai)
        )

    def _openai(self):
        if self._openai_client is None:
            self._openai_client = OpenAI(
                api_key=settings.openai_api_key or os.getenv("OPENAI_API_KEY", "")
            )
        return self._openai_client


_routed_client: RoutedChatClient | None = None


def get_routed_client() -> RoutedChatClient:
    global _routed_client
    if _routed_client is None:
        _routed_client = RoutedChatClient()
    return _routed_client
