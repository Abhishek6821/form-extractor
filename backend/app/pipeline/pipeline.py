"""Pipeline orchestrator: preprocessing -> OCR -> form gate -> pass 1 -> pass 2 -> LLM."""
from __future__ import annotations

import time
from pathlib import Path
from typing import Callable, Optional

from app.schemas import DocumentInfo, DocumentResult, FormGateResult, Page, QADocument
from app.pipeline import document, form_gate, grouping, llm, normalize, ocr, preprocess, pruning

Progress = Callable[[str], None]  # called with a human-readable stage name


def _noop(stage: str) -> None:
    pass


class Timer:
    def __init__(self) -> None:
        self.t: dict[str, float] = {}
        self._start = time.perf_counter()

    def lap(self, name: str) -> None:
        now = time.perf_counter()
        self.t[name] = round((now - self._start) * 1000, 1)
        self._start = now


def run_on_pages(pages: list[Page], document_id: str, filename: str, use_llm: Optional[bool] = None,
                 restarts: int = 6, timer: Optional[Timer] = None, images: Optional[list[bytes]] = None,
                 progress: Progress = _noop) -> DocumentResult:
    """Everything after OCR. Shared by the file path and the JSON-token path.

    Forms go through the two hill-climb passes + one validation call.  Anything
    else is *not* rejected: it goes through document mode (type, summary,
    key facts, full text) so every upload yields its information.
    """
    timer = timer or Timer()
    progress("detecting document type")
    classifier = llm.classify_form_summary if (use_llm if use_llm is not None else llm.llm_available()) else None
    gate = form_gate.run_form_gate(pages, classifier=classifier)
    timer.lap("form_gate")
    result = DocumentResult(document_id=document_id, filename=filename, status="processing", pages=len(pages),
                            gate=gate, is_form=gate.is_form, form_confidence=gate.confidence)
    if not gate.is_form:
        progress("extracting document content")
        info, fields, usage = document.extract_document(pages, images=images, use_llm=use_llm)
        timer.lap("document_extraction")
        result.info = info
        result.fields = normalize.normalize_fields(fields)
        result.llm_used = usage["llm_used"]
        result.llm_provider = usage.get("provider")
        result.llm_model = usage.get("model")
        result.llm_input_tokens = usage["input_tokens"]
        result.llm_output_tokens = usage["output_tokens"]
        result.status = "done"
        result.stage = ""
        result.timing_ms = timer.t
        return result

    per_page = {}
    stats = {}
    progress("grouping fields (hill-climb pass 1)")
    for p in pages:
        cands, s = grouping.group_page(p, restarts=restarts)
        per_page[p.number] = cands
        stats[p.number] = s
    timer.lap("pass1_grouping")

    progress("pruning junk (hill-climb pass 2)")
    qa, pstats = pruning.build_qa_document(pages, per_page, gate.confidence, restarts=restarts)
    timer.lap("pass2_pruning")
    result.qa = qa

    progress("AI validation")
    fields, info = llm.extract_with_llm(qa, use_llm=use_llm)
    timer.lap("llm")
    result.fields = normalize.normalize_fields(fields)
    timer.lap("normalize")
    text = document.page_text(pages)
    result.info = DocumentInfo(document_type="form", title=(text.splitlines() or [""])[0][:120], full_text=text)
    result.llm_used = info["llm_used"]
    result.llm_provider = info.get("provider")
    result.llm_model = info.get("model")
    result.llm_input_tokens = info["input_tokens"]
    result.llm_output_tokens = info["output_tokens"]
    result.status = "done"
    result.stage = ""
    result.timing_ms = timer.t | {"pass1_evals": sum(s.get("evaluations", 0) for s in stats.values()),
                                  "pass2_evals": sum(s.get("evaluations", 0) for s in pstats["pages"].values())}
    return result


def run_on_file(path: str | Path, document_id: str, filename: str, use_llm: Optional[bool] = None,
                ocr_backend: str = "auto", restarts: int = 6, progress: Progress = _noop) -> DocumentResult:
    timer = Timer()
    try:
        progress("preprocessing pages")
        page_images = preprocess.preprocess_file(path)
        timer.lap("preprocess")
        progress("reading text")
        pages = ocr.run_ocr(page_images, backend=ocr_backend)
        timer.lap("ocr")
    except Exception as e:  # surface as a document error, not a 500
        return DocumentResult(document_id=document_id, filename=filename, status="error", error=str(e), timing_ms=timer.t)
    try:
        # Page images are handed to document mode so scans with no readable text can still be described.
        images = [llm.encode_image(p.source) for p in page_images[:1]]
        return run_on_pages(pages, document_id, filename, use_llm=use_llm, restarts=restarts, timer=timer, images=images,
                            progress=progress)
    except Exception as e:
        return DocumentResult(document_id=document_id, filename=filename, status="error", error=str(e),
                              pages=len(pages), timing_ms=timer.t)
