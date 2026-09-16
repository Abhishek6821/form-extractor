from __future__ import annotations

from dataclasses import dataclass
from typing import Optional, Protocol


class ProviderError(RuntimeError):
    """User-facing error (bad key, quota, network) raised by any provider."""


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
