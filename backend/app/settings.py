"""User settings (API key, LLM on/off, model) stored in the local store.

The key is never returned in full by the API — only a masked hint.  An
``ANTHROPIC_API_KEY`` environment variable still works as a fallback.
"""
from __future__ import annotations

import os
from typing import Optional

from pydantic import BaseModel

from app.storage import Store

DEFAULT_MODEL = "claude-opus-5"
MODELS = ["claude-opus-5", "claude-sonnet-5", "claude-haiku-4-5"]


class Settings(BaseModel):
    llm_enabled: bool = True
    anthropic_api_key: str = ""
    model: str = DEFAULT_MODEL
    vision_ocr_enabled: bool = True  # use Claude to read scanned images/photos


class SettingsView(BaseModel):
    llm_enabled: bool
    model: str
    vision_ocr_enabled: bool
    has_api_key: bool
    api_key_hint: str
    key_source: str  # "settings" | "env" | "none"
    admin_required: bool = False  # FORM_ADMIN_TOKEN is set on the server
    models: list[str] = MODELS


class SettingsPatch(BaseModel):
    llm_enabled: Optional[bool] = None
    anthropic_api_key: Optional[str] = None  # "" clears the stored key
    model: Optional[str] = None
    vision_ocr_enabled: Optional[bool] = None


_store: Optional[Store] = None


def _st() -> Store:
    global _store
    if _store is None:
        _store = Store()
    return _store


def reset_cache() -> None:
    global _store
    _store = None


def load() -> Settings:
    raw = _st().get("settings", "default")
    return Settings.model_validate(raw) if raw else Settings()


def save(patch: SettingsPatch) -> Settings:
    cur = load()
    data = patch.model_dump(exclude_none=True)
    if "anthropic_api_key" in data:
        data["anthropic_api_key"] = data["anthropic_api_key"].strip()
    if "model" in data and data["model"] not in MODELS:
        raise ValueError(f"unknown model {data['model']!r}; choose one of {MODELS}")
    new = cur.model_copy(update=data)
    _st().put("settings", "default", new.model_dump())
    return new


def api_key() -> tuple[str, str]:
    """Return (key, source) — stored settings first, then the environment."""
    s = load()
    if s.anthropic_api_key:
        return s.anthropic_api_key, "settings"
    env = os.environ.get("ANTHROPIC_API_KEY", "")
    if env:
        return env, "env"
    return "", "none"


def llm_enabled() -> bool:
    if os.environ.get("FORM_LLM_DISABLED") == "1":
        return False
    return load().llm_enabled and bool(api_key()[0])


def vision_ocr_enabled() -> bool:
    return llm_enabled() and load().vision_ocr_enabled


def model() -> str:
    return os.environ.get("FORM_LLM_MODEL") or load().model


def view() -> SettingsView:
    s = load()
    key, source = api_key()
    hint = f"…{key[-4:]}" if key else ""
    return SettingsView(llm_enabled=s.llm_enabled, model=model(), vision_ocr_enabled=s.vision_ocr_enabled,
                        has_api_key=bool(key), api_key_hint=hint, key_source=source)
