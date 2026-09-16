"""Pipeline orchestrator: preprocessing -> OCR -> form gate -> pass 1 -> pass 2 -> LLM."""
from __future__ import annotations

import time
from pathlib import Path
from typing import Optional

from app.schemas import DocumentResult, FormGateResult, Page, QADocument
from app.pipeline import form_gate, grouping, llm, normalize, ocr, preprocess, pruning


class Timer:
    def __init__(self) -> None:
        self.t: dict[str, float] = {}
        self._start = time.perf_counter()

    def lap(self, name: str) -> None:
        now = time.perf_counter()
        self.t[name] = round((now - self._start) * 1000, 1)
        self._start = now


def run_on_pages(pages: list[Page], document_id: str, filename: str, use_llm: Optional[bool] = None,
                 restarts: int = 6, timer: Optional[Timer] = None) -> DocumentResult:
    """Everything after OCR. Shared by the file path and the JSON-token path."""
    timer = timer or Timer()
    classifier = llm.classify_form_summary if (use_llm if use_llm is not None else llm.llm_available()) else None
    gate = form_gate.run_form_gate(pages, classifier=classifier)
    timer.lap("form_gate")
    result = DocumentResult(document_id=document_id, filename=filename, status="processing", pages=len(pages),
                            gate=gate, is_form=gate.is_form, form_confidence=gate.confidence)
    if not gate.is_form:
        result.status = "rejected"
        result.timing_ms = timer.t
        return result

    per_page = {}
    stats = {}
    for p in pages:
        cands, s = grouping.group_page(p, restarts=restarts)
        per_page[p.number] = cands
        stats[p.number] = s
    timer.lap("pass1_grouping")

    qa, pstats = pruning.build_qa_document(pages, per_page, gate.confidence, restarts=restarts)
    timer.lap("pass2_pruning")
    result.qa = qa

    fields, info = llm.extract_with_llm(qa, use_llm=use_llm)
    timer.lap("llm")
    result.fields = normalize.normalize_fields(fields)
    timer.lap("normalize")
    result.llm_used = info["llm_used"]
    result.llm_provider = info.get("provider")
    result.llm_model = info.get("model")
    result.llm_input_tokens = info["input_tokens"]
    result.llm_output_tokens = info["output_tokens"]
    result.status = "done"
    result.timing_ms = timer.t | {"pass1_evals": sum(s.get("evaluations", 0) for s in stats.values()),
                                  "pass2_evals": sum(s.get("evaluations", 0) for s in pstats["pages"].values())}
    return result


def run_on_file(path: str | Path, document_id: str, filename: str, use_llm: Optional[bool] = None,
                ocr_backend: str = "auto", restarts: int = 6) -> DocumentResult:
    timer = Timer()
    try:
        page_images = preprocess.preprocess_file(path)
        timer.lap("preprocess")
        pages = ocr.run_ocr(page_images, backend=ocr_backend)
        timer.lap("ocr")
    except Exception as e:  # surface as a document error, not a 500
        return DocumentResult(document_id=document_id, filename=filename, status="error", error=str(e), timing_ms=timer.t)
    try:
        return run_on_pages(pages, document_id, filename, use_llm=use_llm, restarts=restarts, timer=timer)
    except Exception as e:
        return DocumentResult(document_id=document_id, filename=filename, status="error", error=str(e),
                              pages=len(pages), timing_ms=timer.t)
