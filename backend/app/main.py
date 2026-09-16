"""Phase 7 — Backend API (FastAPI).

POST  /documents                          upload PDF/image, run the pipeline
GET   /documents/{id}                     full document result
GET   /documents/{id}/fields              extracted field JSON
PATCH /documents/{id}/fields/{field_id}   user corrections (logged for tuning)
POST  /forms                              save an editor layout
GET   /forms/{id}                         fetch a layout
GET   /forms/{id}/preview                 render the assembled form (HTML)
GET   /forms/{id}/export?format=pdf|html|json
POST  /documents/tokens                   run the pipeline on pre-OCR'd tokens (eval / tests)
"""
from __future__ import annotations

import os
import shutil
import tempfile
import uuid
from datetime import datetime, timezone
from typing import Optional

from fastapi import BackgroundTasks, FastAPI, File, Header, HTTPException, Query, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, Response
from pydantic import BaseModel, Field

from app import settings as settings_mod
from app.pipeline import export as export_mod
from app.pipeline import llm, ocr, pipeline
from app.schemas import DocumentResult, ExtractedField, FieldPatch, FormLayout, SavedForm
from app.storage import Store

app = FastAPI(title="Multilingual Form Field Extractor", version="1.1.0")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])

store = Store()
UPLOAD_DIR = os.environ.get("FORM_UPLOAD_DIR", os.path.join(os.path.dirname(__file__), "..", "data", "uploads"))
os.makedirs(UPLOAD_DIR, exist_ok=True)
MAX_UPLOAD_MB = int(os.environ.get("FORM_MAX_UPLOAD_MB", "25"))
QUEUE = os.environ.get("FORM_QUEUE", "inprocess")  # inprocess | celery
ALLOWED_EXT = {".pdf", ".png", ".jpg", ".jpeg", ".tif", ".tiff", ".bmp", ".webp"}


class TokensPayload(BaseModel):
    filename: str = "tokens.json"
    pages: list[dict]  # [{number, width, height, tokens:[{text,bbox,confidence}], lines:[]}]
    use_llm: Optional[bool] = None


def _save(result: DocumentResult) -> None:
    store.put("documents", result.document_id, result.model_dump(mode="json"))


def _load(document_id: str) -> DocumentResult:
    raw = store.get("documents", document_id)
    if raw is None:
        raise HTTPException(404, "document not found")
    return DocumentResult.model_validate(raw)


def _process_file(path: str, document_id: str, filename: str, use_llm: Optional[bool], ocr_backend: str) -> None:
    def progress(stage: str) -> None:
        store.put("documents", document_id, DocumentResult(document_id=document_id, filename=filename,
                                                            status="processing", stage=stage).model_dump(mode="json"))

    try:
        result = pipeline.run_on_file(path, document_id, filename, use_llm=use_llm, ocr_backend=ocr_backend, progress=progress)
    except Exception as e:  # never leave a document stuck in "processing"
        result = DocumentResult(document_id=document_id, filename=filename, status="error", error=str(e))
    _save(result)


@app.get("/health")
def health() -> dict:
    s = settings_mod.load()
    return {"status": "ok", "llm_available": llm.llm_available(), "provider": s.provider,
            "ocr_backends": ocr.available_backends(), "version": app.version}


# ------------------------------------------------------------- settings


ADMIN_TOKEN = os.environ.get("FORM_ADMIN_TOKEN", "")


def _require_admin(token: Optional[str]) -> None:
    """On a shared deployment only the owner (who knows FORM_ADMIN_TOKEN) may change settings."""
    if ADMIN_TOKEN and token != ADMIN_TOKEN:
        raise HTTPException(401, "admin token required to change settings")


@app.get("/settings", response_model=settings_mod.SettingsView)
def get_settings() -> settings_mod.SettingsView:
    v = settings_mod.view()
    v.admin_required = bool(ADMIN_TOKEN)
    return v


@app.put("/settings", response_model=settings_mod.SettingsView)
def put_settings(patch: settings_mod.SettingsPatch, x_admin_token: Optional[str] = Header(None)) -> settings_mod.SettingsView:
    _require_admin(x_admin_token)
    try:
        settings_mod.save(patch)
    except ValueError as e:
        raise HTTPException(422, str(e))
    return get_settings()


@app.get("/settings/models")
def list_models() -> dict:
    """Models available to the active provider's key (falls back to suggestions without a key)."""
    return settings_mod.list_models()


@app.post("/settings/test")
def test_settings(x_admin_token: Optional[str] = Header(None)) -> dict:
    """Validate the stored key with a free token-count call."""
    _require_admin(x_admin_token)
    return llm.test_connection()


@app.post("/documents", response_model=DocumentResult, status_code=202)
async def upload_document(background: BackgroundTasks, file: UploadFile = File(...),
                          sync: bool = Query(False, description="Wait for the pipeline, or (default) return 202 and poll GET /documents/{id}"),
                          use_llm: Optional[bool] = Query(None),
                          ocr_backend: str = Query("auto", pattern="^(auto|pdftext|apple|paddle|llm)$")) -> DocumentResult:
    ext = os.path.splitext(file.filename or "")[1].lower()
    if ext not in ALLOWED_EXT:
        raise HTTPException(415, f"unsupported file type {ext!r}; use PDF or an image")
    document_id = uuid.uuid4().hex[:12]
    dest = os.path.join(UPLOAD_DIR, f"{document_id}{ext}")
    size = 0
    with open(dest, "wb") as out:
        while chunk := await file.read(1 << 20):
            size += len(chunk)
            if size > MAX_UPLOAD_MB << 20:
                out.close()
                os.remove(dest)
                raise HTTPException(413, f"file larger than {MAX_UPLOAD_MB} MB")
            out.write(chunk)
    result = DocumentResult(document_id=document_id, filename=file.filename or dest, status="queued")
    _save(result)
    if sync:
        _process_file(dest, document_id, result.filename, use_llm, ocr_backend)
        return _load(document_id)
    if QUEUE == "celery":
        from app.worker import process_document

        process_document.delay(dest, document_id, result.filename, use_llm, ocr_backend)
    else:
        background.add_task(_process_file, dest, document_id, result.filename, use_llm, ocr_backend)
    return result


@app.post("/documents/tokens", response_model=DocumentResult)
def process_tokens(payload: TokensPayload) -> DocumentResult:
    """Run the gate + both hill-climb passes + LLM on already-OCR'd tokens."""
    pages = [ocr.page_from_tokens(p["tokens"], p["width"], p["height"], p.get("number", i + 1), p.get("lines"))
             for i, p in enumerate(payload.pages)]
    document_id = uuid.uuid4().hex[:12]
    result = pipeline.run_on_pages(pages, document_id, payload.filename, use_llm=payload.use_llm)
    _save(result)
    return result


@app.get("/documents", response_model=list[DocumentResult])
def list_documents() -> list[DocumentResult]:
    return [DocumentResult.model_validate(d) for d in store.list("documents")]


@app.get("/documents/{document_id}", response_model=DocumentResult)
def get_document(document_id: str) -> DocumentResult:
    return _load(document_id)


@app.get("/documents/{document_id}/fields", response_model=list[ExtractedField])
def get_fields(document_id: str) -> list[ExtractedField]:
    doc = _load(document_id)
    if doc.status in ("queued", "processing"):
        raise HTTPException(409, f"document is still {doc.status}")
    if doc.status == "error":
        raise HTTPException(500, doc.error or "pipeline error")
    return doc.fields


@app.patch("/documents/{document_id}/fields/{field_id}", response_model=ExtractedField)
def patch_field(document_id: str, field_id: str, patch: FieldPatch) -> ExtractedField:
    doc = _load(document_id)
    for f in doc.fields:
        if f.field_id == field_id:
            before = f.model_dump(mode="json")
            changes = patch.model_dump(exclude_none=True)
            for k, v in changes.items():
                setattr(f, k, v)
            f.needs_review = False
            f.confidence = 1.0  # a human confirmed it
            # Corrections are kept as tuning data for the cost functions / templates.
            doc.corrections.append({"field_id": field_id, "before": before, "after": f.model_dump(mode="json"),
                                    "at": datetime.now(timezone.utc).isoformat()})
            _save(doc)
            return f
    raise HTTPException(404, "field not found")


@app.get("/documents/{document_id}/corrections")
def get_corrections(document_id: str) -> list[dict]:
    return _load(document_id).corrections


@app.delete("/documents/{document_id}", status_code=204)
def delete_document(document_id: str) -> Response:
    _load(document_id)
    store.delete("documents", document_id)
    for ext in ALLOWED_EXT:
        p = os.path.join(UPLOAD_DIR, f"{document_id}{ext}")
        if os.path.exists(p):
            os.remove(p)
    return Response(status_code=204)


# ---------------------------------------------------------------- forms


@app.post("/forms", response_model=SavedForm, status_code=201)
def save_form(layout: FormLayout) -> SavedForm:
    form = SavedForm(form_id=uuid.uuid4().hex[:12], **layout.model_dump())
    store.put("forms", form.form_id, form.model_dump(mode="json"))
    return form


@app.put("/forms/{form_id}", response_model=SavedForm)
def update_form(form_id: str, layout: FormLayout) -> SavedForm:
    if store.get("forms", form_id) is None:
        raise HTTPException(404, "form not found")
    form = SavedForm(form_id=form_id, **layout.model_dump())
    store.put("forms", form_id, form.model_dump(mode="json"))
    return form


@app.get("/forms", response_model=list[SavedForm])
def list_forms() -> list[SavedForm]:
    return [SavedForm.model_validate(f) for f in store.list("forms")]


@app.get("/forms/{form_id}", response_model=SavedForm)
def get_form(form_id: str) -> SavedForm:
    raw = store.get("forms", form_id)
    if raw is None:
        raise HTTPException(404, "form not found")
    return SavedForm.model_validate(raw)


@app.get("/forms/{form_id}/preview", response_class=HTMLResponse)
def preview_form(form_id: str) -> HTMLResponse:
    return HTMLResponse(export_mod.to_html(get_form(form_id)))


@app.get("/forms/{form_id}/export")
def export_form(form_id: str, format: str = Query("pdf", pattern="^(pdf|html|json)$")) -> Response:
    content, media, name = export_mod.export(get_form(form_id), format)
    return Response(content, media_type=media, headers={"Content-Disposition": f'attachment; filename="{name}"'})


@app.post("/export", summary="Export an unsaved layout directly from the editor")
def export_layout(layout: FormLayout, format: str = Query("pdf", pattern="^(pdf|html|json)$")) -> Response:
    content, media, name = export_mod.export(layout, format)
    return Response(content, media_type=media, headers={"Content-Disposition": f'attachment; filename="{name}"'})
