"""Phase 5b — Hill-Climb Pass 2: Q&A synthesis + junk pruning (no LLM).

State: the subset of Pass-1 candidates to *keep*.

Cost rewards a subset that looks like a coherent, complete form (good coverage,
consistent field density down the page) and penalises candidates that look
like junk: headers, footers, page numbers, watermarks, decorative lines, stray
OCR noise and duplicate detections.

Moves: drop a candidate, add one back, merge two overlapping candidates.
"""
from __future__ import annotations

import random
import re
from dataclasses import dataclass
from typing import Iterable

from app.schemas import FieldCandidate, FieldType, Page, QADocument, QAField
from app.pipeline import geometry as g
from app.pipeline.hillclimb import random_restart_hill_climb
from app.pipeline.templates import synthesize_question

State = frozenset[int]

PAGE_NO_RE = re.compile(r"^(page|pg\.?|पृष्ठ|página|seite|页)?\s*\d{1,3}\s*((of|/|de|von|/)\s*\d{1,3})?$", re.I)
NOISE_RE = re.compile(r"^[^\w\s]{1,4}$|^[|l1I]{1,3}$", re.U)
TITLE_WORDS_RE = re.compile(r"\b(form|application|registration|certificate|invoice|questionnaire|survey|"
                            r"फॉर्म|आवेदन|प्रपत्र|formulario|solicitud|formulaire|antrag|表格|申請書|申请表|نموذج)\b", re.I)
INSTRUCTION_RE = re.compile(r"\b(please|fill|instructions|note|read|use|capital|block letters|attach|tick|कृपया|भरें|"
                            r"निर्देश|por favor|veuillez|bitte|请|ご記入)\b", re.I)


@dataclass
class CandidateFeatures:
    junk: float          # 0 = clearly genuine .. 1 = clearly junk
    genuine: float       # strength of evidence it is a real field
    qa: dict             # synthesized question


def _features(c: FieldCandidate, page: Page, all_cands: list[FieldCandidate]) -> CandidateFeatures:
    label = c.label_text
    norm = label.strip()
    words = norm.split()
    n_words = len(words)
    y_rel = c.bbox[1] / max(page.height, 1)
    qa = synthesize_question(label, c.value_text, c.has_checkbox)
    match = qa["match"]
    # "Gender: ☐ Male ☐ Female" -> multiple choice with options taken from the value.
    if c.has_checkbox and c.value_text:
        opts = [o.strip(" :") for o in g.CHECKBOX_INLINE_RE.split(c.value_text) if o and not g.CHECKBOX_INLINE_RE.match(o)]
        opts = [o for o in opts if o]
        n_boxes = len(g.CHECKBOX_INLINE_RE.findall(c.value_text))
        if n_boxes >= 2 and opts:
            qa["type"] = FieldType.MULTIPLE_CHOICE
            qa["options"] = opts
            if qa["template_key"] is None:
                clean = label.strip().rstrip(":：").strip()
                qa["question"] = clean if clean.endswith("?") else f"Which option applies for '{clean}'?"
                qa["label_en"] = clean
        elif n_boxes == 1 and qa["type"] not in (FieldType.MULTIPLE_CHOICE,):
            qa["type"] = FieldType.CHECKBOX
    junk = 0.0
    genuine = 0.0
    strong_sep = c.has_separator and c.separator_kind != "line"

    # --- junk evidence -----------------------------------------------------
    if PAGE_NO_RE.match(norm) and not strong_sep:
        junk += 0.9
    if NOISE_RE.match(norm):
        junk += 0.8
    if n_words == 1 and len(norm) <= 2 and not strong_sep and not c.has_checkbox:
        junk += 0.5
    in_header = y_rel < 0.08
    in_footer = y_rel > 0.93
    if (in_header or in_footer) and not strong_sep and not c.has_checkbox and match < 0.9:
        junk += 0.45
    if TITLE_WORDS_RE.search(norm + " " + c.value_text) and not strong_sep and match < 0.9:
        junk += 0.35  # e.g. "APPLICATION FORM"
    if INSTRUCTION_RE.search(norm) and not strong_sep and n_words >= 4:
        junk += 0.45
    if n_words >= 9 and not strong_sep:
        junk += 0.4  # sentence, not a label
    if re.search(r"[.。।!?]$", norm) and (n_words >= 5 or len(norm) >= 18) and not strong_sep:
        junk += 0.5  # ends like a sentence
    if n_words >= 6 and not strong_sep and match < 0.9:
        junk += 0.3
    if re.fullmatch(r"[\s☐☑☒□■▢◻◼○●◯◉\[\]()xX✓✔]+", norm):
        junk += 0.9  # a bare checkbox glyph without a label
    if norm.isupper() and n_words >= 3 and not strong_sep and match < 0.9:
        junk += 0.2  # headings in caps
    label_h = max((page.tokens[i].h for i in c.label_tokens), default=0.0)
    mh = g.median_height(page.tokens)
    if label_h > 2.2 * mh and not strong_sep:
        junk += 0.35  # big title / watermark text
    elif label_h > 1.5 * mh and not strong_sep and match < 0.9:
        junk += 0.2  # heading-sized text
    low_conf = min((page.tokens[i].confidence for i in c.label_tokens), default=1.0)
    if low_conf < 0.4:
        junk += 0.3
    if g.is_blank_line(norm):
        junk += 0.7  # a lone underline with no label
    if c.grouping_score < 0.35:
        junk += 0.25
    if c.from_prose_row and not strong_sep:
        junk += 0.6  # fragment of a sentence / instruction line

    # --- genuine evidence --------------------------------------------------
    if strong_sep:
        genuine += 0.45
    elif c.has_separator:
        genuine += 0.2
    if c.has_checkbox:
        genuine += 0.3
    genuine += 0.5 * match if qa["template_key"] else 0.0
    if c.value_region[2] >= 3 * mh:
        genuine += 0.15
    if c.value_text and not c.has_separator and 1 <= n_words <= 5:
        genuine += 0.1
    genuine += 0.2 * c.grouping_score

    return CandidateFeatures(junk=min(1.0, junk), genuine=min(1.0, genuine), qa=qa)


class PruningProblem:
    def __init__(self, cands: list[FieldCandidate], page: Page):
        self.cands = cands
        self.page = page
        self.feat = [_features(c, page, cands) for c in cands]
        n = len(cands)
        # Overlap graph for the duplicate penalty / merge moves.
        self.overlap: dict[int, set[int]] = {i: set() for i in range(n)}
        for i in range(n):
            for j in range(i + 1, n):
                if g.iou(cands[i].bbox, cands[j].bbox) > 0.45 or (
                        cands[i].label_text.strip().lower() == cands[j].label_text.strip().lower()
                        and abs(cands[i].bbox[1] - cands[j].bbox[1]) < 2 * g.median_height(page.tokens)):
                    self.overlap[i].add(j)
                    self.overlap[j].add(i)
        # Vertical bands for the density-consistency term.
        self.bands = 5
        self.band_of = [min(self.bands - 1, int(c.bbox[1] / max(page.height, 1) * self.bands)) for c in cands]

    def cost(self, state: State) -> float:
        cost = 0.0
        for i, f in enumerate(self.feat):
            if i in state:
                cost += 1.6 * f.junk
                cost -= 0.9 * f.genuine
            else:
                cost += 1.1 * f.genuine  # dropping a real field is expensive
                cost -= 0.4 * f.junk
        # Duplicates kept together.
        seen = set()
        for i in state:
            for j in self.overlap[i]:
                if j in state and (j, i) not in seen:
                    seen.add((i, j))
                    cost += 1.0
        if not state:
            cost += 5.0
        # Density consistency: variance of per-band counts, mildly penalised.
        counts = [0] * self.bands
        for i in state:
            counts[self.band_of[i]] += 1
        nonzero = [c for c in counts if c > 0]
        if len(nonzero) >= 2:
            mean = sum(nonzero) / len(nonzero)
            var = sum((c - mean) ** 2 for c in nonzero) / len(nonzero)
            cost += 0.02 * var
        return cost

    def neighbors(self, state: State) -> Iterable[State]:
        n = len(self.cands)
        for i in range(n):
            if i in state:
                yield state - {i}  # drop
                for j in self.overlap[i]:
                    if j in state and j > i:
                        # merge: keep the stronger of an overlapping pair
                        weaker = i if self.feat[i].genuine < self.feat[j].genuine else j
                        yield state - {weaker}
            else:
                yield state | {i}  # add back

    def initial(self, rng: random.Random) -> State:
        thr = rng.uniform(0.3, 0.9)
        return frozenset(i for i, f in enumerate(self.feat) if f.junk < thr or rng.random() < 0.1)


def prune_candidates(cands: list[FieldCandidate], page: Page, restarts: int = 6, seed: int = 0,
                     hill_climb: bool = True, max_iterations: int = 200) -> tuple[list[QAField], int, dict]:
    """``hill_climb=False`` keeps every candidate whose junk score is below 0.5 (no search)."""
    if not cands:
        return [], 0, {"restarts": 0, "evaluations": 0, "iterations": 0, "cost": 0.0}
    prob = PruningProblem(cands, page)

    def make_initial(rng: random.Random) -> State:
        return frozenset(range(len(cands))) if rng.random() < 0.34 else prob.initial(rng)

    if hill_climb:
        res = random_restart_hill_climb(make_initial, prob.cost, prob.neighbors, restarts=restarts, seed=seed,
                                        max_iterations=max_iterations)
    else:
        from app.pipeline.hillclimb import ClimbResult

        init: State = frozenset(i for i, f in enumerate(prob.feat) if f.junk < 0.5)
        res = ClimbResult(init, prob.cost(init), 0, 0, 1, prob.cost(init))
    kept = sorted(res.state, key=lambda i: (cands[i].bbox[1], cands[i].bbox[0]))
    fields: list[QAField] = []
    for k, i in enumerate(kept, start=1):
        c = cands[i]
        qa = prob.feat[i].qa
        fields.append(QAField(field_id=f"f_{page.number}_{k:03d}", question=qa["question"], original_label=c.label_text,
                              expected_answer_type=qa["type"], bbox=c.bbox, page=page.number,
                              grouping_score=c.grouping_score, detected_value=c.value_text, template_key=qa["template_key"],
                              options=qa.get("options", [])))
    removed = len(cands) - len(kept)
    stats = {"restarts": res.restarts, "evaluations": res.evaluations, "iterations": res.iterations, "cost": round(res.cost, 3),
             "initial_cost": round(res.initial_cost, 3)}
    return fields, removed, stats


def build_qa_document(pages: list[Page], per_page_candidates: dict[int, list[FieldCandidate]], form_confidence: float,
                      restarts: int = 6, seed: int = 0, hill_climb: bool = True, max_iterations: int = 200
                      ) -> tuple[QADocument, dict]:
    fields: list[QAField] = []
    removed = 0
    stats: dict = {"pages": {}}
    for page in pages:
        f, r, s = prune_candidates(per_page_candidates.get(page.number, []), page, restarts=restarts, seed=seed,
                                   hill_climb=hill_climb, max_iterations=max_iterations)
        fields.extend(f)
        removed += r
        stats["pages"][page.number] = s
    # Re-number field ids document-wide.
    for k, f in enumerate(fields, start=1):
        f.field_id = f"f_{k:03d}"
    return QADocument(document_type="form", form_confidence=form_confidence, fields=fields,
                      junk_candidates_removed=removed), stats
