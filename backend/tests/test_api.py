import os

import pytest
from fastapi.testclient import TestClient

from tests.conftest import FIXTURES


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("FORM_DB_PATH", str(tmp_path / "store.db"))
    monkeypatch.setenv("FORM_UPLOAD_DIR", str(tmp_path / "uploads"))
    import importlib

    from app import settings
    settings.reset_cache()
    from app import main
    importlib.reload(main)
    return TestClient(main.app)


def test_health(client):
    r = client.get("/health")
    assert r.status_code == 200 and r.json()["status"] == "ok"


def test_upload_form_pdf_end_to_end(client):
    path = os.path.join(FIXTURES, "forms", "hi_bank_form.pdf")
    with open(path, "rb") as f:
        r = client.post("/documents", files={"file": ("hi_bank_form.pdf", f, "application/pdf")})
    assert r.status_code == 202, r.text
    doc = r.json()
    assert doc["status"] == "done" and doc["is_form"] is True
    assert doc["llm_used"] is False
    labels = [f["label_original_language"] for f in doc["fields"]]
    assert any("जन्म तिथि" in l for l in labels)
    dob = next(f for f in doc["fields"] if "जन्म तिथि" in f["label_original_language"])
    assert dob["type"] == "date" and dob["question"] == "What is the applicant's date of birth?"
    assert dob["label"] == "Date of Birth"
    assert doc["qa"]["junk_candidates_removed"] >= 1

    # GET fields
    r = client.get(f"/documents/{doc['document_id']}/fields")
    assert r.status_code == 200 and len(r.json()) == len(doc["fields"])

    # PATCH a correction
    r = client.patch(f"/documents/{doc['document_id']}/fields/{dob['field_id']}", json={"label": "DOB", "required": True})
    assert r.status_code == 200
    assert r.json()["label"] == "DOB" and r.json()["required"] is True and r.json()["confidence"] == 1.0
    corr = client.get(f"/documents/{doc['document_id']}/corrections").json()
    assert len(corr) == 1 and corr[0]["before"]["label"] == "Date of Birth"


def test_upload_non_form_is_rejected_early(client):
    path = os.path.join(FIXTURES, "non_forms", "en_essay.pdf")
    with open(path, "rb") as f:
        r = client.post("/documents", files={"file": ("essay.pdf", f, "application/pdf")})
    doc = r.json()
    assert doc["status"] == "rejected" and doc["is_form"] is False
    assert doc["fields"] == [] and doc["qa"] is None
    assert "pass1_grouping" not in doc["timing_ms"]  # no heavy work was done
    r = client.get(f"/documents/{doc['document_id']}/fields")
    assert r.status_code == 422 and r.json()["detail"]["is_form"] is False


def test_tokens_endpoint(client):
    payload = {"filename": "t.json", "pages": [{"number": 1, "width": 600, "height": 850, "tokens": [
        {"text": "Name:", "bbox": [40, 100, 30, 12]}, {"text": "Email:", "bbox": [320, 100, 36, 12]},
        {"text": "Date", "bbox": [40, 140, 24, 12]}, {"text": "of", "bbox": [68, 140, 12, 12]},
        {"text": "Birth:", "bbox": [84, 140, 36, 12]}, {"text": "Signature", "bbox": [40, 700, 54, 12]},
        {"text": "__________", "bbox": [100, 700, 80, 12]},
    ]}]}
    r = client.post("/documents/tokens", json=payload)
    assert r.status_code == 200, r.text
    doc = r.json()
    assert doc["is_form"] and {f["label"] for f in doc["fields"]} >= {"Full Name", "Email", "Date of Birth", "Signature"}


def test_unsupported_type(client):
    r = client.post("/documents", files={"file": ("x.txt", b"hello", "text/plain")})
    assert r.status_code == 415


def test_forms_save_preview_export(client):
    layout = {"title": "My Form", "grid_columns": 12, "fields": [
        {"field_id": "name", "label": "Name", "type": "text", "x": 0, "y": 0, "w": 6, "h": 1, "required": True},
        {"field_id": "dob", "label": "DOB", "type": "date", "x": 6, "y": 0, "w": 6, "h": 1},
    ]}
    r = client.post("/forms", json=layout)
    assert r.status_code == 201
    fid = r.json()["form_id"]
    assert client.get(f"/forms/{fid}").json()["title"] == "My Form"
    prev = client.get(f"/forms/{fid}/preview")
    assert prev.status_code == 200 and 'type="date"' in prev.text
    pdf = client.get(f"/forms/{fid}/export?format=pdf")
    assert pdf.status_code == 200 and pdf.content[:4] == b"%PDF"
    from app.pipeline.export import pdf_field_names
    assert set(pdf_field_names(pdf.content)) == {"name", "dob"}
    js = client.get(f"/forms/{fid}/export?format=json").json()
    assert js["required"] == ["name"]
    r = client.put(f"/forms/{fid}", json={**layout, "title": "Renamed"})
    assert r.json()["title"] == "Renamed"
    assert client.get("/forms").json()[0]["form_id"] == fid


def test_settings_roundtrip_masks_keys(client, monkeypatch):
    for v in ("ANTHROPIC_API_KEY", "GEMINI_API_KEY", "GOOGLE_API_KEY", "FORM_LLM_DISABLED", "FORM_LLM_PROVIDER"):
        monkeypatch.delenv(v, raising=False)
    r = client.get("/settings")
    body = r.json()
    assert r.status_code == 200 and body["provider"] == "gemini"
    assert body["providers"]["gemini"]["has_api_key"] is False and body["providers"]["claude"]["key_source"] == "none"
    assert "pdftext" in body["ocr_backends_available"]
    r = client.put("/settings", json={"gemini_api_key": "AIza-test-5678", "gemini_model": "gemini-2.5-pro"})
    g = r.json()["providers"]["gemini"]
    assert g["has_api_key"] and g["api_key_hint"] == "…5678" and g["key_source"] == "settings" and g["model"] == "gemini-2.5-pro"
    assert "gemini_api_key" not in r.text and "AIza-test" not in r.text
    assert client.get("/health").json()["llm_available"] is True
    # switching to claude without a claude key -> LLM unavailable
    r = client.put("/settings", json={"provider": "claude"})
    assert r.json()["provider"] == "claude" and client.get("/health").json()["llm_available"] is False
    r = client.put("/settings", json={"anthropic_api_key": "sk-ant-1234", "claude_model": "claude-sonnet-5"})
    assert r.json()["providers"]["claude"]["api_key_hint"] == "…1234" and client.get("/health").json()["llm_available"] is True
    assert client.put("/settings", json={"claude_model": "bad model id!"}).status_code == 422
    assert client.get("/settings/models").json()["live"] is False  # no key -> suggestions
    assert client.put("/settings", json={"ocr_backend": "nope"}).status_code == 422
    r = client.put("/settings", json={"ocr_backend": "paddle", "paddle_server_url": "http://ocr.local:8080/"})
    assert r.json()["ocr_backend"] == "paddle" and r.json()["paddle_server_url"] == "http://ocr.local:8080"
    assert "paddle" in r.json()["ocr_backends_available"]
    r = client.put("/settings", json={"anthropic_api_key": "", "llm_enabled": False})
    assert r.json()["providers"]["claude"]["has_api_key"] is False


def test_settings_env_fallback(client, monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "AIza-env-0001")
    body = client.get("/settings").json()
    assert body["providers"]["gemini"]["key_source"] == "env" and body["providers"]["gemini"]["api_key_hint"] == "…0001"


def test_settings_test_without_key(client, monkeypatch):
    for v in ("ANTHROPIC_API_KEY", "GEMINI_API_KEY", "GOOGLE_API_KEY"):
        monkeypatch.delenv(v, raising=False)
    r = client.post("/settings/test")
    assert r.status_code == 200 and r.json()["ok"] is False and "Settings" in r.json()["error"]


def test_settings_admin_token_guard(tmp_path, monkeypatch):
    monkeypatch.setenv("FORM_DB_PATH", str(tmp_path / "s.db"))
    monkeypatch.setenv("FORM_ADMIN_TOKEN", "secret-123")
    import importlib

    from app import main, settings
    settings.reset_cache()
    importlib.reload(main)
    c = TestClient(main.app)
    assert c.get("/settings").json()["admin_required"] is True
    assert c.put("/settings", json={"llm_enabled": False}).status_code == 401
    assert c.post("/settings/test").status_code == 401
    r = c.put("/settings", json={"llm_enabled": False}, headers={"X-Admin-Token": "secret-123"})
    assert r.status_code == 200 and r.json()["llm_enabled"] is False
    monkeypatch.delenv("FORM_ADMIN_TOKEN")
    importlib.reload(main)
