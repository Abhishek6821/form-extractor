from __future__ import annotations

import base64
import json
from typing import Optional

from app.providers.base import ProviderError, Usage


class ClaudeProvider:
    name = "claude"

    def __init__(self, api_key: str, model: str):
        import anthropic

        if not api_key:
            raise ProviderError("No Anthropic API key configured. Add one on the Settings page.")
        self.model = model
        self._client = anthropic.Anthropic(api_key=api_key)

    def complete_json(self, system: str, text: str, schema: dict, image_png: Optional[bytes] = None,
                      max_tokens: int = 8000) -> tuple[dict, Usage]:
        import anthropic

        content: list = []
        if image_png is not None:
            content.append({"type": "image", "source": {"type": "base64", "media_type": "image/png",
                                                        "data": base64.standard_b64encode(image_png).decode("ascii")}})
        content.append({"type": "text", "text": text})
        try:
            response = self._client.messages.create(
                model=self.model,
                max_tokens=max_tokens,
                system=[{"type": "text", "text": system, "cache_control": {"type": "ephemeral"}}],
                messages=[{"role": "user", "content": content}],
                output_config={"effort": "low", "format": {"type": "json_schema", "schema": schema}},
            )
        except anthropic.AuthenticationError as e:
            raise ProviderError("Anthropic API key was rejected (401). Check it on the Settings page.") from e
        except anthropic.RateLimitError as e:
            raise ProviderError(f"Anthropic rate limit: {e.message}") from e
        except anthropic.APIStatusError as e:
            raise ProviderError(f"Anthropic API error {e.status_code}: {e.message}") from e
        except anthropic.APIConnectionError as e:
            raise ProviderError(f"Cannot reach Anthropic: {e}") from e
        if response.stop_reason == "refusal":
            raise ProviderError("The model declined this document.")
        payload = "".join(b.text for b in response.content if b.type == "text")
        usage = Usage(response.usage.input_tokens, response.usage.output_tokens, self.model, self.name)
        return json.loads(payload), usage

    def test_connection(self) -> dict:
        import anthropic

        try:
            r = self._client.messages.count_tokens(model=self.model, messages=[{"role": "user", "content": "ping"}])
            return {"ok": True, "model": self.model, "input_tokens": r.input_tokens}
        except anthropic.AuthenticationError:
            return {"ok": False, "error": "API key rejected (401). Check the key."}
        except anthropic.PermissionDeniedError:
            return {"ok": False, "error": "API key lacks permission (403)."}
        except anthropic.NotFoundError:
            return {"ok": False, "error": f"Model {self.model!r} not found for this key."}
        except anthropic.APIStatusError as e:
            return {"ok": False, "error": f"API error {e.status_code}: {e.message}"}
        except anthropic.APIConnectionError as e:
            return {"ok": False, "error": f"Cannot reach the API: {e}"}
