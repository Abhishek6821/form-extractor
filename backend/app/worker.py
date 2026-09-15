"""Phase 11 — Celery worker for the OCR + hill-climbing pipeline.

The API enqueues ``process_document`` when ``FORM_QUEUE=celery``; otherwise
uploads are processed in-process (sync or FastAPI BackgroundTasks).

    celery -A app.worker.celery_app worker --loglevel=info
"""
from __future__ import annotations

import os

from celery import Celery

from app.pipeline import pipeline
from app.storage import Store

BROKER = os.environ.get("CELERY_BROKER_URL", "redis://localhost:6379/0")
celery_app = Celery("form_extractor", broker=BROKER, backend=os.environ.get("CELERY_RESULT_BACKEND", BROKER))
celery_app.conf.task_serializer = "json"
celery_app.conf.worker_prefetch_multiplier = 1  # OCR jobs are heavy; one at a time per process


@celery_app.task(name="form_extractor.process_document")
def process_document(path: str, document_id: str, filename: str, use_llm: bool | None = None,
                     ocr_backend: str = "auto") -> dict:
    store = Store()
    result = pipeline.run_on_file(path, document_id, filename, use_llm=use_llm, ocr_backend=ocr_backend)
    store.put("documents", document_id, result.model_dump(mode="json"))
    return {"document_id": document_id, "status": result.status}
