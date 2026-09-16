"""LLM provider abstraction.

The pipeline only ever calls ``Provider.complete_json`` (text or image in,
schema-validated JSON out).  Claude and Gemini are interchangeable behind it,
so the extracted-field output is identical whichever the user picks in
Settings.
"""
from __future__ import annotations

from app.providers.base import Provider, ProviderError, Usage

# ``models`` are suggestions shown before a key is saved; the Settings page lists
# the live catalogue from the provider once a key exists.  ``fallbacks`` are tried
# in order when the chosen model is overloaded (503 / 429).
PROVIDERS = {
    "claude": {"label": "Claude (Anthropic)",
               "models": ["claude-opus-4-6", "claude-opus-5", "claude-sonnet-5", "claude-sonnet-4-6", "claude-haiku-4-5"],
               "default_model": "claude-opus-4-6", "fallbacks": ["claude-sonnet-4-6", "claude-sonnet-5", "claude-haiku-4-5"],
               "key_env": ["ANTHROPIC_API_KEY"]},
    "gemini": {"label": "Gemini (Google)",
               "models": ["gemini-3.5-flash", "gemini-3.8-flash", "gemini-3.1-pro-preview", "gemini-flash-latest",
                          "gemini-pro-latest", "gemini-3.1-flash-lite"],
               "default_model": "gemini-3.5-flash", "fallbacks": ["gemini-3.5-flash", "gemini-3.1-flash-lite", "gemini-flash-latest"],
               "key_env": ["GEMINI_API_KEY", "GOOGLE_API_KEY"]},
}

MODEL_ID_RE = r"^[A-Za-z0-9][A-Za-z0-9._\-]{1,80}$"


def make_provider(name: str, api_key: str, model: str, fallbacks: list[str] | None = None) -> Provider:
    if name not in PROVIDERS:
        raise ProviderError(f"unknown provider {name!r}")
    fb = PROVIDERS[name]["fallbacks"] if fallbacks is None else fallbacks
    if name == "claude":
        from app.providers.claude import ClaudeProvider

        return ClaudeProvider(api_key, model, fb)
    from app.providers.gemini import GeminiProvider

    return GeminiProvider(api_key, model, fb)


__all__ = ["Provider", "ProviderError", "Usage", "PROVIDERS", "MODEL_ID_RE", "make_provider"]
