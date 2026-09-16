"""User settings: LLM provider (Claude / Gemini) with per-provider keys, OCR backend.

Stored in the local store; environment variables act as fallbacks so a hosted
deployment can be configured without the Settings page.  Keys are never
returned in full by the API — only a masked hint.
"""
from __future__ import annotations

import os
from typing import Literal, Optional

from pydantic import BaseModel, Field

import re

from app.providers import MODEL_ID_RE, PROVIDERS, Provider, ProviderError, make_provider
from app.storage import Store

ProviderName = Literal["claude", "gemini", "kimi"]
GateProvider = Literal["auto", "claude", "gemini", "kimi"]
OcrBackend = Literal["auto", "pdftext", "apple", "paddle", "llm"]


class Settings(BaseModel):
    provider: ProviderName = "gemini"
    gate_provider: GateProvider = "auto"  # who decides "is this a form?" (auto = same as provider)
    llm_enabled: bool = True
    vision_ocr_enabled: bool = True  # let the LLM read scanned pages when no other reader can
    anthropic_api_key: str = ""
    claude_model: str = PROVIDERS["claude"]["default_model"]
    gemini_api_key: str = ""
    gemini_model: str = PROVIDERS["gemini"]["default_model"]
    kimi_api_key: str = ""
    kimi_model: str = PROVIDERS["kimi"]["default_model"]
    ocr_backend: OcrBackend = "auto"
    paddle_server_url: str = ""  # PaddleOCR-VL service (paddlex --serve --pipeline PaddleOCR-VL), e.g. http://host:8080


class ProviderView(BaseModel):
    label: str
    models: list[str]
    model: str
    has_api_key: bool
    api_key_hint: str
    key_source: str  # settings | env | none


class SettingsView(BaseModel):
    provider: ProviderName
    gate_provider: GateProvider
    gate_provider_effective: str
    llm_enabled: bool
    vision_ocr_enabled: bool
    providers: dict[str, ProviderView]
    ocr_backend: OcrBackend
    ocr_backends_available: list[str]
    paddle_server_url: str
    paddle_local_available: bool
    admin_required: bool = False


class SettingsPatch(BaseModel):
    provider: Optional[ProviderName] = None
    gate_provider: Optional[GateProvider] = None
    llm_enabled: Optional[bool] = None
    vision_ocr_enabled: Optional[bool] = None
    anthropic_api_key: Optional[str] = None  # "" clears
    claude_model: Optional[str] = None
    gemini_api_key: Optional[str] = None
    gemini_model: Optional[str] = None
    kimi_api_key: Optional[str] = None
    kimi_model: Optional[str] = None
    ocr_backend: Optional[OcrBackend] = None
    paddle_server_url: Optional[str] = None


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
    raw = _st().get("settings", "default") or {}
    # Backwards compatibility with the single-provider settings document.
    if "model" in raw and "claude_model" not in raw:
        raw["claude_model"] = raw.pop("model")
    s = Settings.model_validate({k: v for k, v in raw.items() if k in Settings.model_fields})
    env_provider = os.environ.get("FORM_LLM_PROVIDER")
    if env_provider in PROVIDERS and "provider" not in raw:
        s.provider = env_provider  # type: ignore[assignment]
    return s


def save(patch: SettingsPatch) -> Settings:
    cur = load()
    data = patch.model_dump(exclude_none=True)
    for k in ("anthropic_api_key", "gemini_api_key", "kimi_api_key", "paddle_server_url"):
        if k in data:
            data[k] = data[k].strip().rstrip("/") if k == "paddle_server_url" else data[k].strip()
    for key in ("claude_model", "gemini_model", "kimi_model"):
        if key in data:
            data[key] = data[key].strip().replace("models/", "")
            if not re.match(MODEL_ID_RE, data[key]):
                raise ValueError(f"invalid model id {data[key]!r}")
    new = cur.model_copy(update=data)
    _st().put("settings", "default", new.model_dump())
    return new


# ---------------------------------------------------------------- lookups


def api_key(provider: str, s: Optional[Settings] = None) -> tuple[str, str]:
    """(key, source) for a provider — stored settings first, then environment."""
    s = s or load()
    stored = {"claude": s.anthropic_api_key, "gemini": s.gemini_api_key, "kimi": s.kimi_api_key}[provider]
    if stored:
        return stored, "settings"
    for env in PROVIDERS[provider]["key_env"]:
        v = os.environ.get(env, "")
        if v:
            return v, "env"
    return "", "none"


def model_for(provider: str, s: Optional[Settings] = None) -> str:
    s = s or load()
    env = os.environ.get("FORM_LLM_MODEL")
    if env and re.match(MODEL_ID_RE, env):
        return env
    return {"claude": s.claude_model, "gemini": s.gemini_model, "kimi": s.kimi_model}[provider]


def llm_enabled() -> bool:
    if os.environ.get("FORM_LLM_DISABLED") == "1":
        return False
    s = load()
    return s.llm_enabled and bool(api_key(s.provider, s)[0])


def vision_ocr_enabled() -> bool:
    return llm_enabled() and load().vision_ocr_enabled


def gate_provider_name(s: Optional[Settings] = None) -> str:
    """Provider used for the form-or-not decision; falls back to the main one when not configured."""
    s = s or load()
    if s.gate_provider != "auto" and api_key(s.gate_provider, s)[0]:
        return s.gate_provider
    return s.provider


def get_provider(role: str = "extract") -> Provider:
    """The configured provider, ready to call. ``role="gate"`` = the form-check provider."""
    s = load()
    name = gate_provider_name(s) if role == "gate" else s.provider
    key, _ = api_key(name, s)
    if not key:
        raise ProviderError(f"No {PROVIDERS[name]['label']} API key configured. Add one on the Settings page.")
    return make_provider(name, key, model_for(name, s))


def paddle_server_url() -> str:
    return load().paddle_server_url or os.environ.get("PADDLE_OCR_URL", "").rstrip("/")


def view() -> SettingsView:
    from app.pipeline import ocr

    s = load()
    provs = {}
    for name, meta in PROVIDERS.items():
        key, source = api_key(name, s)
        provs[name] = ProviderView(label=meta["label"], models=meta["models"], model=model_for(name, s),
                                  has_api_key=bool(key), api_key_hint=f"…{key[-4:]}" if key else "", key_source=source)
    return SettingsView(provider=s.provider, gate_provider=s.gate_provider, gate_provider_effective=gate_provider_name(s),
                        llm_enabled=s.llm_enabled, vision_ocr_enabled=s.vision_ocr_enabled,
                        providers=provs, ocr_backend=s.ocr_backend, ocr_backends_available=ocr.available_backends(),
                        paddle_server_url=paddle_server_url(), paddle_local_available=ocr.paddle_local_available())


def list_models() -> dict:
    """Live model catalogue for the active provider (needs a key)."""
    s = load()
    try:
        return {"provider": s.provider, "models": get_provider().list_models(), "live": True}
    except ProviderError as e:
        return {"provider": s.provider, "models": PROVIDERS[s.provider]["models"], "live": False, "error": str(e)}
    except Exception as e:  # network / SDK error: fall back to the suggestions
        return {"provider": s.provider, "models": PROVIDERS[s.provider]["models"], "live": False, "error": str(e)[:200]}
