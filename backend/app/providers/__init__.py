"""LLM provider abstraction.

The pipeline only ever calls ``Provider.complete_json`` (text or image in,
schema-validated JSON out).  Claude and Gemini are interchangeable behind it,
so the extracted-field output is identical whichever the user picks in
Settings.
"""
from __future__ import annotations

from app.providers.base import Provider, ProviderError, Usage

PROVIDERS = {
    "claude": {"label": "Claude (Anthropic)", "models": ["claude-opus-5", "claude-sonnet-5", "claude-haiku-4-5"],
               "default_model": "claude-opus-5", "key_env": ["ANTHROPIC_API_KEY"], "key_prefix": "sk-ant-"},
    "gemini": {"label": "Gemini (Google)", "models": ["gemini-2.5-flash", "gemini-2.5-pro", "gemini-2.0-flash"],
               "default_model": "gemini-2.5-flash", "key_env": ["GEMINI_API_KEY", "GOOGLE_API_KEY"], "key_prefix": "AIza"},
}


def make_provider(name: str, api_key: str, model: str) -> Provider:
    if name == "claude":
        from app.providers.claude import ClaudeProvider

        return ClaudeProvider(api_key, model)
    if name == "gemini":
        from app.providers.gemini import GeminiProvider

        return GeminiProvider(api_key, model)
    raise ProviderError(f"unknown provider {name!r}")


__all__ = ["Provider", "ProviderError", "Usage", "PROVIDERS", "make_provider"]
