"""Kimi (Moonshot AI) — OpenAI-compatible chat completions with JSON mode and image input."""
from __future__ import annotations

import base64
import json
import re
from typing import Optional

from app.providers.base import ProviderError, ProviderOverloaded, Usage, with_fallbacks

BASE_URL = "https://api.moonshot.ai/v1"


class KimiProvider:
    name = "kimi"

    def __init__(self, api_key: str, model: str, fallbacks: Optional[list[str]] = None, base_url: str = BASE_URL):
        if not api_key:
            raise ProviderError("No Kimi (Moonshot) API key configured. Add one on the Settings page.")
        self.model = model
        self.fallbacks = fallbacks or []
        self._key = api_key
        self._base = base_url.rstrip("/")

    def _headers(self) -> dict:
        return {"Authorization": f"Bearer {self._key}", "Content-Type": "application/json"}

    def complete_json(self, system: str, text: str, schema: dict, image_png: Optional[bytes] = None,
                      max_tokens: int = 8000) -> tuple[dict, Usage]:
        return with_fallbacks(self.model, self.fallbacks,
                              lambda m: self._complete(m, system, text, schema, image_png, max_tokens))

    def _complete(self, model: str, system: str, text: str, schema: dict, image_png: Optional[bytes],
                  max_tokens: int) -> tuple[dict, Usage]:
        import httpx

        content: list = []
        if image_png is not None:
            content.append({"type": "image_url", "image_url": {
                "url": "data:image/png;base64," + base64.standard_b64encode(image_png).decode("ascii")}})
        content.append({"type": "text", "text": text})
        body = {
            "model": model,
            "temperature": 0,
            "max_tokens": max_tokens,
            "response_format": {"type": "json_object"},
            "messages": [
                {"role": "system", "content": system + "\nRespond with a single JSON object that matches this JSON Schema "
                                              "exactly (no prose, no markdown):\n" + json.dumps(schema, ensure_ascii=False)},
                {"role": "user", "content": content if image_png is not None else text},
            ],
        }
        try:
            r = httpx.post(f"{self._base}/chat/completions", headers=self._headers(), json=body, timeout=180)
        except httpx.HTTPError as e:
            raise ProviderError(f"Cannot reach Kimi: {e}") from e
        if r.status_code in (401, 403):
            raise ProviderError("Kimi API key was rejected. Check it on the Settings page.")
        if r.status_code in (429, 503, 529):
            raise ProviderOverloaded(f"Kimi {model} overloaded ({r.status_code})")
        if r.status_code == 404:
            raise ProviderError(f"Kimi model {model!r} not found.")
        if r.status_code >= 400:
            raise ProviderError(f"Kimi API error {r.status_code}: {r.text[:200]}")
        data = r.json()
        try:
            payload = data["choices"][0]["message"]["content"]
        except (KeyError, IndexError) as e:
            raise ProviderError(f"Kimi returned an unexpected response: {str(data)[:200]}") from e
        payload = re.sub(r"^```(?:json)?\s*|\s*```$", "", (payload or "").strip())
        if not payload:
            raise ProviderError("Kimi returned an empty response.")
        u = data.get("usage") or {}
        usage = Usage(int(u.get("prompt_tokens", 0)), int(u.get("completion_tokens", 0)), model, self.name)
        try:
            return json.loads(payload), usage
        except json.JSONDecodeError as e:
            raise ProviderError(f"Kimi returned invalid JSON: {e}") from e

    def test_connection(self) -> dict:
        import httpx

        try:
            r = httpx.get(f"{self._base}/models", headers=self._headers(), timeout=30)
        except httpx.HTTPError as e:
            return {"ok": False, "error": f"Cannot reach Kimi: {e}"}
        if r.status_code in (401, 403):
            return {"ok": False, "error": f"Kimi API key rejected ({r.status_code}). Check the key."}
        if r.status_code >= 400:
            return {"ok": False, "error": f"Kimi API error {r.status_code}: {r.text[:200]}"}
        ids = [m.get("id") for m in r.json().get("data", [])]
        if ids and self.model not in ids:
            return {"ok": False, "error": f"Model {self.model!r} not available; try one of {ids[:6]}"}
        return {"ok": True, "model": self.model, "input_tokens": 0}

    def list_models(self) -> list[str]:
        import httpx

        r = httpx.get(f"{self._base}/models", headers=self._headers(), timeout=30)
        r.raise_for_status()
        return sorted((m.get("id") for m in r.json().get("data", []) if m.get("id")), reverse=True)
