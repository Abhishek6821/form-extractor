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

import logging

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(name)s: %(message)s")
app = FastAPI(title="Multilingual Form Field Extractor", version="1.1.0")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])

store = Store()
UPLOAD_DIR = os.environ.get("FORM_UPLOAD_DIR", os.path.join(os.path.dirname(__file__), "..", "data", "uploads"))
os.makedirs(UPLOAD_DIR, exist_ok=True)
MAX_UPLOAD_MB = int(os.environ.get("FORM_MAX_UPLOAD_MB", "25"))
QUEUE = os.environ.get("FORM_QUEUE", "inprocess")  # inprocess | celery
from app.pipeline.preprocess import SUPPORTED_EXT as ALLOWED_EXT  # any PDF/document/image format PyMuPDF opens


class TokensPayload(BaseModel):
    filename: str = "tokens.json"
    pages: list[dict]  # [{number, width, height, tokens:[{text,bbox,confidence}], lines:[]}]
    use_llm: Optional[bool] = None
    hill_climb: bool = True
    restarts: int = 6


def _save(result: DocumentResult) -> None:
    store.put("documents", result.document_id, result.model_dump(mode="json"))


def _load(document_id: str) -> DocumentResult:
    raw = store.get("documents", document_id)
    if raw is None:
        raise HTTPException(404, "document not found")
    return DocumentResult.model_validate(raw)


# The CPU-bound pipeline runs in a separate worker process so the API process stays responsive
# (health checks, other requests) even on hosts with a fraction of a CPU — Python's GIL would
# otherwise block everything while the hill-climb passes run.
_POOL: Optional["concurrent.futures.ProcessPoolExecutor"] = None
_POOL_WORKERS = int(os.environ.get("FORM_WORKERS", "1"))
# Hosts with a fraction of a CPU (Render free = 0.1) get throttled as a whole while the search runs,
# so cap the search effort server-side; the UI shows the cap.
MAX_RESTARTS = int(os.environ.get("FORM_MAX_RESTARTS", "12"))
MAX_ITERATIONS = int(os.environ.get("FORM_MAX_ITERATIONS", "1000"))


def _low_priority() -> None:
    try:
        os.nice(10)  # let the API process win the CPU when both are runnable
    except Exception:
        pass


def _pool():
    global _POOL
    import concurrent.futures

    if _POOL is None:
        _POOL = concurrent.futures.ProcessPoolExecutor(max_workers=_POOL_WORKERS, initializer=_low_priority)
    return _POOL


def _process_file(path: str, document_id: str, filename: str, use_llm: Optional[bool], ocr_backend: str,
                  hill_climb: bool = True, restarts: int = 6, max_iterations: int = 150, file_hash: str = "",
                  ai_mode: str = "auto") -> None:
    started = datetime.now(timezone.utc)

    def progress(stage: str) -> None:
        store.put("documents", document_id, DocumentResult(document_id=document_id, filename=filename, status="processing",
                                                            stage=stage, file_hash=file_hash).model_dump(mode="json"))

    kwargs = dict(use_llm=use_llm, ocr_backend=ocr_backend, hill_climb=hill_climb,
                  restarts=min(restarts, MAX_RESTARTS), max_iterations=min(max_iterations, MAX_ITERATIONS),
                  progress=progress, ai_mode=ai_mode)
    try:
        result = pipeline.run_on_file(path, document_id, filename, **kwargs)
    except Exception as e:  # never leave a document stuck in "processing"
        result = DocumentResult(document_id=document_id, filename=filename, status="error", error=str(e))
    result.file_hash = file_hash
    result.stage = ""
    if result.status == "rejected":
        # Only forms are kept: drop the upload, keep a short-lived record so the client can read the reason.
        if os.path.exists(path):
            os.remove(path)
    _save(result)


@app.get("/", include_in_schema=False)
@app.head("/", include_in_schema=False)
def root() -> dict:
    return {"service": "form-extractor-api", "docs": "/docs", "health": "/health"}


@app.get("/health")
def health() -> dict:
    s = settings_mod.load()
    return {"status": "ok", "llm_available": llm.llm_available(), "provider": s.provider,
            "ocr_backends": ocr.available_backends(), "version": app.version,
            "limits": {"max_restarts": MAX_RESTARTS, "max_iterations": MAX_ITERATIONS}}


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
                          sync: bool = Query(False, description="Wait for the pipeline (default: return 202 immediately and poll GET /documents/{id})"),
                          use_llm: Optional[bool] = Query(None),
                          ocr_backend: str = Query("auto", pattern="^(auto|pdftext|apple|paddle|llm)$"),
                          hill_climb: bool = Query(True, description="Run the two hill-climb passes (False = baseline)"),
                          restarts: int = Query(6, ge=1, le=12, description="Random restarts per pass"),
                          max_iterations: int = Query(150, ge=10, le=1000),
                          ai_mode: str = Query("auto", pattern="^(auto|always|off)$",
                                               description="auto = call the AI only when templates leave gaps"),
                          no_cache: bool = Query(False, description="Ignore a previous identical upload")) -> DocumentResult:
    ext = os.path.splitext(file.filename or "")[1].lower()
    if ext not in ALLOWED_EXT:
        raise HTTPException(415, f"Unsupported file type {ext or '(none)'}. Upload a PDF, image (PNG/JPG/GIF/TIFF/BMP/WebP), "
                                 f"XPS, EPUB, SVG or TXT file — it will be checked for being a form.")
    import hashlib

    document_id = uuid.uuid4().hex[:12]
    dest = os.path.join(UPLOAD_DIR, f"{document_id}{ext}")
    size = 0
    digest = hashlib.sha256()
    with open(dest, "wb") as out:
        while chunk := await file.read(1 << 20):
            size += len(chunk)
            if size > MAX_UPLOAD_MB << 20:
                out.close()
                os.remove(dest)
                raise HTTPException(413, f"file larger than {MAX_UPLOAD_MB} MB")
            digest.update(chunk)
            out.write(chunk)
    file_hash = digest.hexdigest()
    params_key = f"{file_hash}:{use_llm}:{ocr_backend}:{hill_climb}:{min(restarts, MAX_RESTARTS)}:{min(max_iterations, MAX_ITERATIONS)}:{ai_mode}"
    # Same file with the same options already processed -> serve it instantly.
    if not no_cache:
        for raw in store.list("documents"):
            if raw.get("status") == "done" and raw.get("file_hash") == params_key:
                os.remove(dest)
                cached = DocumentResult.model_validate(raw)
                cached.cached = True
                return cached
    result = DocumentResult(document_id=document_id, filename=file.filename or dest, status="queued", file_hash=params_key)
    _save(result)
    if sync:
        _process_file(dest, document_id, result.filename, use_llm, ocr_backend, hill_climb, restarts, max_iterations,
                      params_key, ai_mode)
        done = _load(document_id)
        if done.status == "rejected":
            store.delete("documents", document_id)
            raise HTTPException(422, rejection_message(done))
        return done
    if QUEUE == "celery":
        from app.worker import process_document

        process_document.delay(dest, document_id, result.filename, use_llm, ocr_backend)
    else:
        background.add_task(_process_file, dest, document_id, result.filename, use_llm, ocr_backend, hill_climb,
                            restarts, max_iterations, params_key, ai_mode)
    return result


def rejection_message(done: DocumentResult) -> str:
    tokens = int((done.gate.signals if done.gate else {}).get("token_count", 0))
    if tokens == 0:
        return ("No readable text was found in this file, so it cannot be checked as a form. "
                "Try a sharper scan/photo, or a PDF with a text layer.")
    conf = round((1 - done.form_confidence) * 100) if done.gate else 0
    via = " (checked with the AI vision model)" if done.gate and done.gate.used_classifier else ""
    return (f"Only forms can be uploaded. This file does not look like a fillable form (form likelihood {conf}%){via}. "
            f"Upload a form with labels and blanks/boxes to fill.")


@app.post("/documents/tokens", response_model=DocumentResult)
def process_tokens(payload: TokensPayload) -> DocumentResult:
    """Run the gate + both hill-climb passes + LLM on already-OCR'd tokens."""
    pages = [ocr.page_from_tokens(p["tokens"], p["width"], p["height"], p.get("number", i + 1), p.get("lines"))
             for i, p in enumerate(payload.pages)]
    document_id = uuid.uuid4().hex[:12]
    result = pipeline.run_on_pages(pages, document_id, payload.filename, use_llm=payload.use_llm,
                                   hill_climb=payload.hill_climb, restarts=payload.restarts)
    _save(result)
    return result


@app.get("/documents", response_model=list[DocumentResult])
def list_documents() -> list[DocumentResult]:
    return [DocumentResult.model_validate(d) for d in store.list("documents") if d.get("status") != "rejected"]


@app.get("/documents/{document_id}", response_model=DocumentResult)
def get_document(document_id: str) -> DocumentResult:
    doc = _load(document_id)
    if doc.status == "rejected" and not doc.error:
        doc.error = rejection_message(doc)
    return doc


@app.get("/documents/{document_id}/fields", response_model=list[ExtractedField])
def get_fields(document_id: str) -> list[ExtractedField]:
    doc = _load(document_id)
    if doc.status == "rejected":
        raise HTTPException(422, {"is_form": False, "confidence": doc.form_confidence, "message": "document is not a form"})
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


# ------------------------------------------------ criteria & sample forms

SAMPLES_DIR = os.path.join(os.path.dirname(__file__), "..", "eval", "fixtures", "forms")


@app.get("/criteria", summary="What counts as a form")
def criteria() -> dict:
    return {"criteria": llm.FORM_CRITERIA, "gate_provider": settings_mod.gate_provider_name()}


@app.get("/samples", summary="Sample multilingual forms to try")
def list_samples() -> list[dict]:
    out = []
    if os.path.isdir(SAMPLES_DIR):
        for fn in sorted(os.listdir(SAMPLES_DIR)):
            if fn.endswith(".pdf"):
                lang = fn.split("_")[0]
                out.append({"name": fn, "language": lang, "url": f"/samples/{fn}"})
    return out


@app.get("/samples/{name}")
def get_sample(name: str) -> Response:
    if "/" in name or not name.endswith(".pdf"):
        raise HTTPException(404, "sample not found")
    path = os.path.join(SAMPLES_DIR, name)
    if not os.path.exists(path):
        raise HTTPException(404, "sample not found")
    with open(path, "rb") as f:
        return Response(f.read(), media_type="application/pdf", headers={"Content-Disposition": f'inline; filename="{name}"'})


# ------------------------------------------------- hill-climb data files


def _json_file(payload: dict, name: str) -> Response:
    import json as _json

    return Response(_json.dumps(payload, ensure_ascii=False, indent=2), media_type="application/json",
                    headers={"Content-Disposition": f'attachment; filename="{name}"'})


def hill_climb_data(doc: DocumentResult) -> dict[str, dict]:
    """The two data files of the implementation plan (Phase 4 and Phase 5) plus the final schema (Phase 7)."""
    base = os.path.splitext(os.path.basename(doc.filename))[0] or "document"
    hc = doc.hill_climb.model_dump() if doc.hill_climb else {}
    pass1 = {
        "algorithm": "hill-climb pass 1 — field grouping",
        "description": "State: per-row split boundaries. Moves: split / merge / shift a boundary by one token. "
                       "Cost: label-value distance, column alignment, separators, whitespace gaps, orphans.",
        "document": base, "document_id": doc.document_id, "search": hc.get("pass1", {}),
        "candidates": [c.model_dump() for c in doc.candidates],
    }
    qa = doc.qa.model_dump() if doc.qa else {"document_type": "form", "form_confidence": doc.form_confidence, "fields": [], "junk_candidates_removed": 0}
    pass2 = {
        "algorithm": "hill-climb pass 2 — Q&A synthesis + junk pruning",
        "description": "State: subset of candidates to keep. Moves: drop / add back / merge overlapping. "
                       "Cost: rewards a coherent form, penalises headers, footers, page numbers, noise, duplicates.",
        "document": base, "document_id": doc.document_id, "search": hc.get("pass2", {}),
        **qa,
    }
    schema = {
        "document_id": doc.document_id, "filename": doc.filename, "is_form": doc.is_form,
        "form_confidence": doc.form_confidence, "hill_climb": hc,
        "extraction": {"llm_used": doc.llm_used, "provider": doc.llm_provider, "model": doc.llm_model,
                       "input_tokens": doc.llm_input_tokens, "output_tokens": doc.llm_output_tokens},
        "fields": [f.model_dump(mode="json") for f in doc.fields],
    }
    return {"pass1": pass1, "pass2": pass2, "schema": schema}


@app.get("/documents/{document_id}/pass1.data.json", summary="Pass 1 (field grouping) data file")
def download_pass1(document_id: str) -> Response:
    doc = _load(document_id)
    return _json_file(hill_climb_data(doc)["pass1"], f"{os.path.splitext(doc.filename)[0]}.pass1.data.json")


@app.get("/documents/{document_id}/pass2.data.json", summary="Pass 2 (optimized Q&A JSON) data file")
def download_pass2(document_id: str) -> Response:
    doc = _load(document_id)
    return _json_file(hill_climb_data(doc)["pass2"], f"{os.path.splitext(doc.filename)[0]}.pass2.data.json")


@app.get("/documents/{document_id}/schema.json", summary="Final field schema (Phase 7)")
def download_schema(document_id: str) -> Response:
    doc = _load(document_id)
    return _json_file(hill_climb_data(doc)["schema"], f"{os.path.splitext(doc.filename)[0]}.schema.json")


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
