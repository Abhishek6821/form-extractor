"""Pipeline orchestrator: preprocessing -> OCR -> form gate -> pass 1 -> pass 2 -> LLM."""
from __future__ import annotations

import logging
import threading
import time
from pathlib import Path
from typing import Callable, Optional

Progress = Callable[[str], None]


def _noop(stage: str) -> None:
    pass


from app.schemas import (DocumentResult, FieldType, FormGateResult, HillClimbReport, Page, PassStats, QADocument, QAField,
                         QualityReport, TokenReport)
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


def needs_ai(qa: QADocument, scanned: bool) -> bool:
    """AI 'auto' mode: skip the call when templates already produced clean canonical fields."""
    if scanned:
        return True  # OCR of scans is noisy: worth one call
    if not qa.fields:
        return False
    untemplated = sum(1 for f in qa.fields if not f.template_key)
    # Checkbox option lists ("☐ Male ☐ Female") are already parsed into options — they are not answers.
    has_values = any(f.detected_value.strip() and not f.options for f in qa.fields)
    return has_values or untemplated / len(qa.fields) > 0.2


def run_on_pages(pages: list[Page], document_id: str, filename: str, use_llm: Optional[bool] = None,
                 restarts: int = 6, timer: Optional[Timer] = None, hill_climb: bool = True,
                 max_iterations: int = 150, images: Optional[list[bytes]] = None, scanned: bool = False,
                 vision_key: Optional[int] = None, progress: Progress = _noop, ai_mode: str = "auto") -> DocumentResult:
    """Everything after OCR. Shared by the file path and the JSON-token path.

    ``hill_climb=False`` runs both passes as their non-searching baselines so the
    effect of the optimisation can be compared from the UI.
    """
    timer = timer or Timer()
    restarts = max(1, min(int(restarts), 12))
    max_iterations = max(10, min(int(max_iterations), 1000))
    llm_on = use_llm if use_llm is not None else llm.llm_available()
    if ai_mode == "off":
        llm_on = False
    progress("detecting form")
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
                            gate=gate, is_form=gate.is_form, form_confidence=gate.confidence,
                            ocr_backend=next((p.reader for p in pages if p.reader), None))
    if not gate.is_form:
        logging.getLogger("form_gate").info("rejected %s: tokens=%d signals=%s", filename, n_tokens, gate.signals)
        result.status = "rejected"
        result.timing_ms = timer.t
        return result

    # Scans read by the vision model: start the image-based field extraction now, in parallel with the
    # geometric passes, and pick the richer result at the end.
    vision_thread = None
    vision_out: dict = {}
    prefetched = llm.LAST_VISION_FIELDS.get(vision_key) if vision_key is not None else None
    if prefetched is not None:
        # The OCR call already returned the field list — no second vision request.
        vision_out["fields"] = llm.vision_fields_to_extracted(prefetched, pages[0].width, pages[0].height, pages[0].number)
        vision_out["info"] = {"llm_used": True, "input_tokens": 0, "output_tokens": 0, "model": None, "provider": None,
                              "from": "ocr call"}
    elif llm_on and images and scanned and any(p.reader == "llm" for p in pages):
        def _vision() -> None:
            try:
                vision_out["fields"], vision_out["info"] = llm.extract_fields_from_image(
                    images[0], pages[0].width, pages[0].height, pages[0].number)
            except Exception as e:
                vision_out["error"] = str(e)
        vision_thread = threading.Thread(target=_vision, daemon=True)
        vision_thread.start()

    progress("grouping fields (pass 1)")
    per_page = {}
    stats = {}
    for p in pages:
        cands, s = grouping.group_page(p, restarts=restarts, max_iterations=max_iterations, hill_climb=hill_climb)
        per_page[p.number] = cands
        stats[p.number] = s
    timer.lap("pass1_grouping")
    all_cands = [c for p in pages for c in per_page.get(p.number, [])]

    progress("pruning junk (pass 2)")
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

    # If the vision call already produced at least as many fields as the geometric passes, its
    # English labels/types are final: skip the validation call entirely.
    vision_ready = vision_out.get("fields") or []
    if vision_thread is not None:
        vision_thread.join(timeout=90)
        vision_ready = vision_out.get("fields") or []
    use_vision = bool(vision_ready) and len(vision_ready) >= len(qa.fields)
    call_ai = llm_on and not use_vision and (ai_mode == "always" or needs_ai(qa, scanned))
    progress("AI validation" if call_ai else "finishing")
    fields, info = llm.extract_with_llm(qa, use_llm=call_ai)
    if use_vision:
        fields, info = vision_ready, dict(vision_out.get("info") or {})
        info["skipped"] = "fields came from the single vision call; no validation call needed"
        logging.getLogger("form_gate").info("vision fields used for %s: %d", filename, len(fields))
    if llm_on and not call_ai and not use_vision and not info.get("skipped"):
        info["skipped"] = "templates covered every field; no AI call needed"
    if vision_out.get("error"):
        logging.getLogger("form_gate").warning("vision extraction failed: %s", vision_out["error"])
    timer.lap("llm")
    result.fields = normalize.normalize_fields(fields)
    timer.lap("normalize")
    result.llm_used = info["llm_used"]
    result.llm_provider = info.get("provider")
    result.llm_model = info.get("model")
    result.llm_input_tokens = info["input_tokens"]
    result.llm_output_tokens = info["output_tokens"]
    # --- token & quality accounting for the hill-climb dialog -------------------------------
    hc = result.hill_climb
    if hc is not None:
        raw_text = "\n".join(" ".join(p.tokens[i].text for i in r) for p in pages for r in g.cluster_rows(p.tokens))
        unpruned = QADocument(form_confidence=gate.confidence, fields=[
            QAField(field_id=c.candidate_id, question="", original_label=c.label_text, expected_answer_type=FieldType.TEXT,
                    bbox=c.bbox, detected_value=c.value_text) for c in all_cands])
        sys_tokens = llm.estimate_tokens(llm.SYSTEM_PROMPT)
        sent = llm.estimate_tokens(llm.build_prompt(qa)) + sys_tokens
        t_unpruned = llm.estimate_tokens(llm.build_prompt(unpruned)) + sys_tokens
        t_raw = llm.estimate_tokens(raw_text) + sys_tokens
        t_img = sum(llm.estimate_image_tokens(p.width, p.height) for p in pages) + sys_tokens
        baseline_kind = "image" if scanned else "raw_text"
        baseline_tokens = t_img if scanned else t_raw
        calls = llm.ledger_snapshot()
        hc.tokens = TokenReport(
            calls=calls, used_total=sum(c["input_tokens"] + c["output_tokens"] for c in calls),
            ai_called=bool(info.get("llm_used")), skipped_reason=info.get("skipped", ""),
            estimated_if_called=0 if info.get("llm_used") else sent + 70 * len(qa.fields),
            used_input=info.get("input_tokens", 0), used_output=info.get("output_tokens", 0), prompt_sent=sent,
            prompt_unpruned=t_unpruned, prompt_raw_text=t_raw, prompt_image=t_img,
            saved_vs_unpruned=max(0, t_unpruned - sent), saved_vs_raw_text=max(0, t_raw - sent),
            saved_vs_image=max(0, t_img - sent), saved_pct_vs_raw_text=round(100 * max(0, t_raw - sent) / max(t_raw, 1), 1),
            baseline=baseline_kind, tokens_saved=max(0, baseline_tokens - sent),
            saved_pct=round(100 * max(0, baseline_tokens - sent) / max(baseline_tokens, 1), 1))
        # Baseline = both passes without search (cheap: deterministic initial states).
        base_cands = 0
        base_fields = 0
        if hill_climb:
            for p in pages:
                bc, _ = grouping.group_page(p, hill_climb=False)
                base_cands += len(bc)
                bf, _, _ = pruning.prune_candidates(bc, p, hill_climb=False)
                base_fields += len(bf)
        else:
            base_cands, base_fields = len(all_cands), len(qa.fields)
        hc.quality = QualityReport(
            baseline_candidates=base_cands, baseline_fields=base_fields, candidates=len(all_cands), fields=len(qa.fields),
            junk_removed=qa.junk_candidates_removed,
            pass1_cost_initial=round(sum(s.get("initial_cost", 0.0) for s in stats.values()), 3),
            pass1_cost_final=hc.pass1.cost,
            pass2_cost_initial=round(sum(s.get("initial_cost", 0.0) for s in p2), 3), pass2_cost_final=hc.pass2.cost,
            template_hit_rate=round(sum(1 for f in qa.fields if f.template_key) / max(len(qa.fields), 1), 3))
    result.status = "done"
    result.timing_ms = timer.t | {"pass1_evals": sum(s.get("evaluations", 0) for s in stats.values()),
                                  "pass2_evals": sum(s.get("evaluations", 0) for s in pstats["pages"].values())}
    return result


def run_on_file(path: str | Path, document_id: str, filename: str, use_llm: Optional[bool] = None,
                ocr_backend: str = "auto", restarts: int = 6, hill_climb: bool = True,
                max_iterations: int = 150, progress: Progress = _noop, ai_mode: str = "auto") -> DocumentResult:
    timer = Timer()
    llm.ledger_reset()
    try:
        progress("preprocessing")
        page_images = preprocess.preprocess_file(path)
        timer.lap("preprocess")
        progress("reading text")
        pages = ocr.run_ocr(page_images, backend=ocr_backend)
        timer.lap("ocr")
    except Exception as e:  # surface as a document error, not a 500
        return DocumentResult(document_id=document_id, filename=filename, status="error", error=str(e), timing_ms=timer.t)
    try:
        scanned = not any(p.pdf_path for p in page_images) or all(len(p.tokens) == 0 for p in pages)
        images = [llm.encode_image(page_images[0].source)] if page_images else None
        return run_on_pages(pages, document_id, filename, use_llm=use_llm, restarts=restarts, timer=timer,
                            hill_climb=hill_climb, max_iterations=max_iterations, images=images, scanned=scanned,
                            vision_key=id(page_images[0].source) if page_images else None, progress=progress,
                            ai_mode=ai_mode)
    except Exception as e:
        return DocumentResult(document_id=document_id, filename=filename, status="error", error=str(e),
                              pages=len(pages), timing_ms=timer.t)
