from __future__ import annotations

from dataclasses import dataclass
from typing import Optional, Protocol


class ProviderError(RuntimeError):
    """User-facing error (bad key, quota, network) raised by any provider."""


class ProviderOverloaded(ProviderError):
    """Transient capacity error (503 / 429 / 529) — safe to retry on another model."""


def with_fallbacks(primary: str, fallbacks: list[str], call):
    """Run ``call(model)`` on the primary model, then on each fallback when overloaded."""
    tried: list[str] = []
    last: Exception | None = None
    for m in [primary] + [f for f in fallbacks if f != primary]:
        try:
            return call(m)
        except ProviderOverloaded as e:
            tried.append(m)
            last = e
    raise ProviderError(f"All models overloaded ({', '.join(tried)}): {last}")


@dataclass
class Usage:
    input_tokens: int = 0
    output_tokens: int = 0
    model: str = ""
    provider: str = ""


class Provider(Protocol):
    name: str
    model: str

    def complete_json(self, system: str, text: str, schema: dict, image_png: Optional[bytes] = None,
                      max_tokens: int = 8000) -> tuple[dict, Usage]:
        """One request; returns parsed JSON that matches ``schema`` plus token usage."""
        ...

    def test_connection(self) -> dict:
        """Cheap validation of the key/model. Returns {ok, model, error?}."""
        ...

    def list_models(self) -> list[str]:
        """Model ids usable for generation with this key (live catalogue)."""
        ...
