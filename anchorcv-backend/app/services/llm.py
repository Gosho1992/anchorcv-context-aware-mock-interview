
"""
Multi-provider LLM routing for AnchorCV.

Supports:
- OpenAI Chat Completions
- Anthropic Messages API
- Otari OpenAI-compatible gateway

All providers expose the same chat.completions.create(...) interface
to the rest of AnchorCV.
"""

import logging
from types import SimpleNamespace

import httpx
from openai import OpenAI

from app.config import settings

logger = logging.getLogger(__name__)

ANTHROPIC_API_URL = "https://api.anthropic.com/v1/messages"
ANTHROPIC_VERSION = "2023-06-01"
ANTHROPIC_MAX_TOKENS = 4096

DEFAULT_MODEL = "gpt-4o-mini"
OTARI_DEFAULT_MAX_TOKENS = 2000
OTARI_DEFAULT_REASONING_EFFORT = "low"

# Single source of truth for the model picker.
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
        "description": "Anthropic's stronger writing model for CVs and letters.",
    },
    {
        "id": "openai/gpt-oss-20b",
        "label": "GPT OSS 20B (Otari)",
        "provider": "otari",
        "tier": "fast",
        "description": "Open-weight GPT OSS model served through the Otari gateway.",
    },
]

MODEL_BY_ID = {model["id"]: model for model in AVAILABLE_MODELS}
ALLOWED_MODEL_IDS = set(MODEL_BY_ID)


def list_available_models() -> list[dict]:
    """Return models whose provider credentials are configured."""
    models = []

    for model in AVAILABLE_MODELS:
        provider = model["provider"]

        if provider == "openai" and not settings.openai_api_key:
            continue

        if provider == "anthropic" and not settings.anthropic_api_key:
            continue

        if provider == "otari" and not settings.otari_api_key:
            continue

        models.append(model)

    return models


def resolve_model(model: str | None) -> str:
    """Resolve a requested model against the configured model catalogue."""
    available_ids = {
        item["id"] for item in list_available_models()
    }

    if model and model in available_ids:
        return model

    if DEFAULT_MODEL in available_ids:
        return DEFAULT_MODEL

    if available_ids:
        return next(
            item["id"]
            for item in AVAILABLE_MODELS
            if item["id"] in available_ids
        )

    raise RuntimeError(
        "No LLM provider is configured. Add an OpenAI, Anthropic, "
        "or Otari API key to the backend environment."
    )


def _to_openai_shape(text: str) -> SimpleNamespace:
    """Return the response structure expected by existing AnchorCV code."""
    return SimpleNamespace(
        choices=[
            SimpleNamespace(
                message=SimpleNamespace(content=text)
            )
        ]
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
        raise RuntimeError(
            "Anthropic API is not configured. "
            "Missing ANTHROPIC_API_KEY."
        )

    system_parts = [
        message.get("content", "")
        for message in messages
        if message.get("role") == "system"
    ]

    chat_messages = [
        {
            "role": message["role"],
            "content": message.get("content", ""),
        }
        for message in messages
        if message.get("role") in ("user", "assistant")
    ]

    if not chat_messages:
        chat_messages = [{"role": "user", "content": ""}]

    system = "\n\n".join(
        part for part in system_parts if part
    )

    if response_format and response_format.get("type") == "json_object":
        system = (
            system + "\n\n" if system else ""
        ) + (
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
        body["temperature"] = max(
            0.0,
            min(float(temperature), 1.0),
        )

    headers = {
        "x-api-key": api_key,
        "anthropic-version": ANTHROPIC_VERSION,
        "content-type": "application/json",
    }

    with httpx.Client(timeout=120.0) as client:
        response = client.post(
            ANTHROPIC_API_URL,
            headers=headers,
            json=body,
        )
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
        if text.startswith("```"):
            text = text.strip("`")

            if text.lower().startswith("json"):
                text = text[4:]

            text = text.strip()

    return _to_openai_shape(text)


def _call_otari_sync(**kwargs):
    """Send an OpenAI-compatible chat completion request to Otari."""
    api_key = settings.otari_api_key

    if not api_key:
        raise RuntimeError(
            "Otari API is not configured. Missing OTARI_API_KEY."
        )

    # GPT-OSS can spend too much of a small output budget on reasoning.
    # Use low reasoning effort by default, but respect an explicit setting.
    extra_body = dict(kwargs.get("extra_body") or {})
    extra_body.setdefault(
        "reasoning_effort",
        OTARI_DEFAULT_REASONING_EFFORT,
    )
    kwargs["extra_body"] = extra_body

    # Preserve a caller-supplied token limit.
    kwargs.setdefault("max_tokens", OTARI_DEFAULT_MAX_TOKENS)

    client = OpenAI(
        api_key=api_key,
        base_url=settings.otari_base_url,
        default_headers={
            "Otari-Key": api_key,
        },
        timeout=120.0,
    )

    try:
        return client.chat.completions.create(**kwargs)
    finally:
        client.close()


class _RoutedCompletions:
    def __init__(self, get_openai_client):
        self._get_openai_client = get_openai_client

    def create(self, **kwargs):
        requested_model = kwargs.get("model") or DEFAULT_MODEL
        model = resolve_model(requested_model)

        provider = MODEL_BY_ID[model]["provider"]

        # Ensure the resolved model is the one sent to the provider.
        kwargs["model"] = model

        if provider == "anthropic":
            return _call_anthropic_sync(
                model=model,
                messages=kwargs.get("messages") or [],
                temperature=kwargs.get("temperature"),
                max_tokens=kwargs.get("max_tokens"),
                response_format=kwargs.get("response_format"),
            )

        if provider == "otari":
            return _call_otari_sync(**kwargs)

        return self._get_openai_client().chat.completions.create(
            **kwargs
        )


class RoutedChatClient:
    """Drop-in replacement for the OpenAI client used by AnchorCV."""

    def __init__(self):
        self._openai_client = None

        self.chat = SimpleNamespace(
            completions=_RoutedCompletions(self._openai)
        )

    def _openai(self):
        if self._openai_client is None:
            self._openai_client = OpenAI(
                api_key=settings.openai_api_key
            )

        return self._openai_client


_routed_client: RoutedChatClient | None = None


def get_routed_client() -> RoutedChatClient:
    """Return the shared multi-provider client."""
    global _routed_client

    if _routed_client is None:
        _routed_client = RoutedChatClient()

    return _routed_client
