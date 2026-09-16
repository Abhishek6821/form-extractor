"""Pipeline orchestrator: preprocessing -> OCR -> form gate -> pass 1 -> pass 2 -> LLM."""
from __future__ import annotations

import logging
import time
from pathlib import Path
from typing import Optional

from app.schemas import DocumentResult, FormGateResult, HillClimbReport, Page, PassStats, QADocument
from app.pipeline import form_gate, grouping, llm, normalize, ocr, preprocess, pruning
from app.pipeline import geometry as g


class Timer:
    def __init__(self) -> None:
        self.t: dict[str, float] = {}
        self._start = time.perf_counter()

    def lap(self, name: str) -> None:
        now = time.perf_counter()
        self.t[name] = round((now - self._start) * 1000, 1)
        self._start = now


def run_on_pages(pages: list[Page], document_id: str, filename: str, use_llm: Optional[bool] = None,
                 restarts: int = 6, timer: Optional[Timer] = None, hill_climb: bool = True,
                 max_iterations: int = 150, images: Optional[list[bytes]] = None, scanned: bool = False,
                 vision_key: Optional[int] = None) -> DocumentResult:
    """Everything after OCR. Shared by the file path and the JSON-token path.

    ``hill_climb=False`` runs both passes as their non-searching baselines so the
    effect of the optimisation can be compared from the UI.
    """
    timer = timer or Timer()
    restarts = max(1, min(int(restarts), 12))
    max_iterations = max(10, min(int(max_iterations), 1000))
    llm_on = use_llm if use_llm is not None else llm.llm_available()
    classifier = llm.classify_form_summary if llm_on else None
    gate = form_gate.run_form_gate(pages, classifier=classifier)
    n_tokens = sum(len(p.tokens) for p in pages)
    # A scan the text gate rejects (or that yielded almost no text) gets a second opinion from the
    # vision model before we turn it away — OCR of photos is often too poor for the structural signals.
    if llm_on and images and (not gate.is_form or n_tokens < 15):
        try:
            verdict = llm.LAST_VISION_VERDICT.get(vision_key) if vision_key is not None else None
            if verdict is not None:  # the OCR call already judged the page — no extra request
                is_form, conf, reason = verdict[0], verdict[1], "from the OCR call"
            else:
                is_form, conf, reason = llm.classify_form_image(images[0])
            gate = FormGateResult(is_form=is_form, confidence=round(conf, 3), signals=gate.signals | {"vision_reason": 0.0},
                                  used_classifier=True)
            gate.signals["text_score"] = gate.signals.get("token_count", 0.0)
            logging.getLogger("form_gate").info("vision gate for %s: is_form=%s conf=%.2f (%s)", filename, is_form, conf, reason)
        except Exception as e:  # keep the text decision if the model is unavailable
            logging.getLogger("form_gate").warning("vision gate failed: %s", e)
    timer.lap("form_gate")
    result = DocumentResult(document_id=document_id, filename=filename, status="processing", pages=len(pages),
                            gate=gate, is_form=gate.is_form, form_confidence=gate.confidence)
    if not gate.is_form:
        logging.getLogger("form_gate").info("rejected %s: tokens=%d signals=%s", filename, n_tokens, gate.signals)
        result.status = "rejected"
        result.timing_ms = timer.t
        return result

    per_page = {}
    stats = {}
    for p in pages:
        cands, s = grouping.group_page(p, restarts=restarts, max_iterations=max_iterations, hill_climb=hill_climb)
        per_page[p.number] = cands
        stats[p.number] = s
    timer.lap("pass1_grouping")
    all_cands = [c for p in pages for c in per_page.get(p.number, [])]

    qa, pstats = pruning.build_qa_document(pages, per_page, gate.confidence, restarts=restarts, hill_climb=hill_climb,
                                           max_iterations=max_iterations)
    timer.lap("pass2_pruning")
    result.qa = qa
    result.candidates = all_cands
    p2 = list(pstats["pages"].values())
    result.hill_climb = HillClimbReport(
        enabled=hill_climb, restarts=restarts, max_iterations=max_iterations,
        pass1=PassStats(enabled=hill_climb, restarts=sum(s.get("restarts", 0) for s in stats.values()),
                        iterations=sum(s.get("iterations", 0) for s in stats.values()),
                        evaluations=sum(s.get("evaluations", 0) for s in stats.values()),
                        cost=round(sum(s.get("cost", 0.0) for s in stats.values()), 3),
                        candidates_in=sum(len(p.tokens) for p in pages), candidates_out=len(all_cands),
                        ms=timer.t.get("pass1_grouping", 0.0)),
        pass2=PassStats(enabled=hill_climb, restarts=sum(s.get("restarts", 0) for s in p2),
                        iterations=sum(s.get("iterations", 0) for s in p2), evaluations=sum(s.get("evaluations", 0) for s in p2),
                        cost=round(sum(s.get("cost", 0.0) for s in p2), 3), candidates_in=len(all_cands),
                        candidates_out=len(qa.fields), ms=timer.t.get("pass2_pruning", 0.0)),
    )

    fields, info = llm.extract_with_llm(qa, use_llm=use_llm)
    # Photos: vision OCR boxes are approximate, so grouping can under-segment. When we found clearly fewer
    # fields than the page has label-like lines, read the fields straight off the image instead.
    expected = sum(1 for p in pages for r in g.cluster_rows(p.tokens)
                   if any(g.ends_with_separator(p.tokens[i].text) or g.is_blank_line(p.tokens[i].text) or g.is_checkbox(p.tokens[i].text) for i in r))
    if llm_on and images and scanned and len(fields) < max(3, 0.6 * expected):
        try:
            vfields, vinfo = llm.extract_fields_from_image(images[0], pages[0].width, pages[0].height, pages[0].number)
            if len(vfields) > len(fields):
                fields, info = vfields, vinfo
                logging.getLogger("form_gate").info("vision extraction used for %s: %d fields", filename, len(vfields))
        except Exception as e:
            logging.getLogger("form_gate").warning("vision extraction failed: %s", e)
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
                ocr_backend: str = "auto", restarts: int = 6, hill_climb: bool = True,
                max_iterations: int = 150) -> DocumentResult:
    timer = Timer()
    try:
        page_images = preprocess.preprocess_file(path)
        timer.lap("preprocess")
        pages = ocr.run_ocr(page_images, backend=ocr_backend)
        timer.lap("ocr")
    except Exception as e:  # surface as a document error, not a 500
        return DocumentResult(document_id=document_id, filename=filename, status="error", error=str(e), timing_ms=timer.t)
    try:
        scanned = not any(p.pdf_path for p in page_images) or all(len(p.tokens) == 0 for p in pages)
        images = [llm.encode_image(page_images[0].source)] if page_images else None
        return run_on_pages(pages, document_id, filename, use_llm=use_llm, restarts=restarts, timer=timer,
                            hill_climb=hill_climb, max_iterations=max_iterations, images=images, scanned=scanned,
                            vision_key=id(page_images[0].source) if page_images else None)
    except Exception as e:
        return DocumentResult(document_id=document_id, filename=filename, status="error", error=str(e),
                              pages=len(pages), timing_ms=timer.t)
