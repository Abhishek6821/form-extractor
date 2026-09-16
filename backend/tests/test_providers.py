import json

import pytest

from app.providers import PROVIDERS, ProviderError, make_provider


def test_registry():
    assert set(PROVIDERS) == {"claude", "gemini"}
    for meta in PROVIDERS.values():
        assert meta["default_model"] in meta["models"]


def test_missing_key_is_a_provider_error():
    with pytest.raises(ProviderError):
        make_provider("gemini", "", "gemini-2.5-flash")
    with pytest.raises(ProviderError):
        make_provider("claude", "", "claude-opus-5")
    with pytest.raises(ProviderError):
        make_provider("openai", "k", "m")


def test_gemini_provider_builds_json_request(monkeypatch):
    from google import genai

    calls = []

    class Usage:
        prompt_token_count, candidates_token_count = 33, 11

    class Resp:
        text = json.dumps({"fields": []})
        usage_metadata = Usage()

    class Models:
        def generate_content(self, model, contents, config):
            calls.append((model, contents, config))
            return Resp()

        def count_tokens(self, model, contents):
            class R:
                total_tokens = 1
            return R()

    class FakeClient:
        def __init__(self, api_key):
            assert api_key == "AIza-x"
            self.models = Models()

    monkeypatch.setattr(genai, "Client", FakeClient)
    p = make_provider("gemini", "AIza-x", "gemini-2.5-flash")
    data, usage = p.complete_json("sys", "hello", {"type": "object"}, image_png=b"\x89PNG....")
    assert data == {"fields": []} and usage.input_tokens == 33 and usage.output_tokens == 11 and usage.provider == "gemini"
    model, contents, config = calls[0]
    assert model == "gemini-2.5-flash" and contents[-1] == "hello" and len(contents) == 2  # image + text
    assert config.response_mime_type == "application/json" and config.response_json_schema == {"type": "object"}
    assert config.system_instruction == "sys"
    assert p.test_connection()["ok"] is True


def test_gemini_empty_response_raises(monkeypatch):
    from google import genai

    class Resp:
        text = ""
        usage_metadata = None

    class Models:
        def generate_content(self, **kw):
            return Resp()

    class FakeClient:
        def __init__(self, api_key):
            self.models = Models()

    monkeypatch.setattr(genai, "Client", FakeClient)
    p = make_provider("gemini", "AIza-x", "gemini-2.5-flash")
    with pytest.raises(ProviderError):
        p.complete_json("s", "t", {"type": "object"})


def test_claude_provider_builds_request(monkeypatch):
    import anthropic

    calls = []

    class Block:
        type = "text"
        text = json.dumps({"ok": 1})

    class U:
        input_tokens, output_tokens = 5, 2

    class Resp:
        stop_reason = "end_turn"
        content = [Block()]
        usage = U()

    class Messages:
        def create(self, **kw):
            calls.append(kw)
            return Resp()

    class FakeClient:
        def __init__(self, api_key):
            self.messages = Messages()

    monkeypatch.setattr(anthropic, "Anthropic", FakeClient)
    p = make_provider("claude", "sk-ant-x", "claude-opus-5")
    data, usage = p.complete_json("sys", "hello", {"type": "object"}, image_png=b"png")
    assert data == {"ok": 1} and usage.provider == "claude"
    kw = calls[0]
    assert kw["model"] == "claude-opus-5" and kw["output_config"]["format"]["schema"] == {"type": "object"}
    assert kw["messages"][0]["content"][0]["type"] == "image" and kw["messages"][0]["content"][1]["text"] == "hello"
