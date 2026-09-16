from __future__ import annotations

import json
from typing import Optional

from app.providers.base import ProviderError, Usage


class GeminiProvider:
    name = "gemini"

    def __init__(self, api_key: str, model: str):
        from google import genai

        if not api_key:
            raise ProviderError("No Gemini API key configured. Add one on the Settings page.")
        self.model = model
        self._client = genai.Client(api_key=api_key)

    def complete_json(self, system: str, text: str, schema: dict, image_png: Optional[bytes] = None,
                      max_tokens: int = 8000) -> tuple[dict, Usage]:
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
            response = self._client.models.generate_content(model=self.model, contents=contents, config=config)
        except errors.ClientError as e:
            code = getattr(e, "code", None) or getattr(e, "status_code", None)
            if code in (401, 403):
                raise ProviderError("Gemini API key was rejected. Check it on the Settings page.") from e
            if code == 429:
                raise ProviderError("Gemini quota / rate limit exceeded.") from e
            if code == 404:
                raise ProviderError(f"Gemini model {self.model!r} not found.") from e
            raise ProviderError(f"Gemini API error {code}: {e}") from e
        except errors.ServerError as e:
            raise ProviderError(f"Gemini server error: {e}") from e
        except errors.APIError as e:
            raise ProviderError(f"Gemini error: {e}") from e
        payload = response.text or ""
        if not payload.strip():
            raise ProviderError("Gemini returned an empty response (possibly blocked by safety filters).")
        um = response.usage_metadata
        usage = Usage(int(getattr(um, "prompt_token_count", 0) or 0), int(getattr(um, "candidates_token_count", 0) or 0),
                      self.model, self.name)
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
