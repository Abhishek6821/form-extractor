from __future__ import annotations

import json
from typing import Optional

from app.providers.base import ProviderError, ProviderOverloaded, Usage, with_fallbacks

REQUEST_TIMEOUT_MS = 60_000  # an overloaded model often hangs instead of returning 503: time out and switch model


class GeminiProvider:
    name = "gemini"

    def __init__(self, api_key: str, model: str, fallbacks: Optional[list[str]] = None):
        from google import genai

        if not api_key:
            raise ProviderError("No Gemini API key configured. Add one on the Settings page.")
        from google.genai import types

        self.model = model
        self.fallbacks = fallbacks or []
        # No SDK-level retries: a 503/429 must fail fast so the fallback chain switches model
        # immediately instead of sleeping through exponential backoff (10-20 s per call).
        self._client = genai.Client(api_key=api_key, http_options=types.HttpOptions(
            timeout=REQUEST_TIMEOUT_MS, retry_options=types.HttpRetryOptions(attempts=1)))

    def complete_json(self, system: str, text: str, schema: dict, image_png: Optional[bytes] = None,
                      max_tokens: int = 8000) -> tuple[dict, Usage]:
        return with_fallbacks(self.model, self.fallbacks,
                              lambda m: self._complete(m, system, text, schema, image_png, max_tokens))

    def _complete(self, model: str, system: str, text: str, schema: dict, image_png: Optional[bytes],
                  max_tokens: int) -> tuple[dict, Usage]:
        from google.genai import errors, types

        contents: list = []
        if image_png is not None:
            contents.append(types.Part.from_bytes(data=image_png, mime_type="image/png"))
        contents.append(text)
        config = types.GenerateContentConfig(
            system_instruction=system,
            response_mime_type="application/json",
            response_json_schema=schema,
            temperature=0.0,
            max_output_tokens=max_tokens,
        )
        try:
            response = self._client.models.generate_content(model=model, contents=contents, config=config)
        except errors.ClientError as e:
            code = getattr(e, "code", None) or getattr(e, "status_code", None)
            if code in (401, 403):
                raise ProviderError("Gemini API key was rejected. Check it on the Settings page.") from e
            if code == 429:
                raise ProviderOverloaded(f"Gemini rate limit on {model}") from e
            if code == 404:
                raise ProviderError(f"Gemini model {model!r} not found.") from e
            raise ProviderError(f"Gemini API error {code}: {e}") from e
        except errors.ServerError as e:
            code = getattr(e, "code", None) or getattr(e, "status_code", None)
            if code in (503, 529):
                raise ProviderOverloaded(f"Gemini {model} overloaded (503)") from e
            raise ProviderError(f"Gemini server error: {e}") from e
        except errors.APIError as e:
            raise ProviderError(f"Gemini error: {e}") from e
        except Exception as e:  # httpx timeouts / connection resets -> try the next model
            if "timeout" in type(e).__name__.lower() or "timed out" in str(e).lower():
                raise ProviderOverloaded(f"Gemini {model} timed out after {REQUEST_TIMEOUT_MS // 1000}s") from e
            raise ProviderError(f"Gemini request failed: {e}") from e
        payload = response.text or ""
        if not payload.strip():
            raise ProviderError("Gemini returned an empty response (possibly blocked by safety filters).")
        um = response.usage_metadata
        usage = Usage(int(getattr(um, "prompt_token_count", 0) or 0), int(getattr(um, "candidates_token_count", 0) or 0),
                      model, self.name)
        try:
            return json.loads(payload), usage
        except json.JSONDecodeError as e:
            raise ProviderError(f"Gemini returned invalid JSON: {e}") from e

    def test_connection(self) -> dict:
        from google.genai import errors

        try:
            r = self._client.models.count_tokens(model=self.model, contents="ping")
            return {"ok": True, "model": self.model, "input_tokens": int(r.total_tokens or 0)}
        except errors.ClientError as e:
            code = getattr(e, "code", None) or getattr(e, "status_code", None)
            if code in (400, 401, 403):
                return {"ok": False, "error": f"Gemini API key rejected ({code}). Check the key."}
            if code == 404:
                return {"ok": False, "error": f"Model {self.model!r} not found."}
            return {"ok": False, "error": f"Gemini API error {code}: {e}"}
        except errors.APIError as e:
            return {"ok": False, "error": f"Gemini error: {e}"}
        except Exception as e:  # network
            return {"ok": False, "error": f"Cannot reach Gemini: {e}"}

    def list_models(self) -> list[str]:
        out = []
        for m in self._client.models.list():
            actions = getattr(m, "supported_actions", None) or []
            name = (m.name or "").replace("models/", "")
            # text/vision generation models only — skip TTS, image, audio, music, agent previews
            if "generateContent" in actions and name.startswith("gemini") and not any(
                    x in name for x in ("tts", "image", "audio", "omni", "transcribe", "robotics", "computer-use", "live")):
                out.append(name)
        return sorted(out, reverse=True)
