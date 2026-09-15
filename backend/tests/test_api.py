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


def test_settings_roundtrip_masks_key(client, monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("FORM_LLM_DISABLED", raising=False)
    r = client.get("/settings")
    assert r.status_code == 200 and r.json()["has_api_key"] is False and r.json()["key_source"] == "none"
    r = client.put("/settings", json={"anthropic_api_key": "sk-ant-test-1234", "model": "claude-sonnet-5", "llm_enabled": True})
    body = r.json()
    assert body["has_api_key"] is True and body["api_key_hint"] == "…1234" and body["key_source"] == "settings"
    assert body["model"] == "claude-sonnet-5" and "anthropic_api_key" not in body
    assert client.get("/health").json()["llm_available"] is True
    r = client.put("/settings", json={"llm_enabled": False})
    assert client.get("/health").json()["llm_available"] is False
    r = client.put("/settings", json={"model": "gpt-9"})
    assert r.status_code == 422
    r = client.put("/settings", json={"anthropic_api_key": ""})
    assert r.json()["has_api_key"] is False


def test_settings_test_without_key(client, monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
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
