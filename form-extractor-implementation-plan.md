# Implementation Plan: Multilingual Form Field Extractor + Drag-and-Drop Form Editor

## 1. What you're actually building

Three connected subsystems:

1. **Extraction engine** — takes a PDF/image, in *any* language, decides whether it's even a form, and if so returns a structured list of fields (question, label, value, type, position).
2. **Field editor (frontend)** — lets the user drag/drop the extracted fields into a new layout and preview it.
3. **Optimization layer (two hill-climbing passes)** — classical local-search that does the heavy lifting of geometry and candidate selection, so an LLM is only called once per document, on a small pre-filtered set of questions. This is where you save tokens.

A key clarification before you build: hill climbing is a **local search optimization algorithm**, not something that reads text. It's excellent for *layout/geometry and selection problems* (which tokens belong together, which candidate fields are genuine vs junk) but useless for *semantic* problems (is this field called "Date of Birth" or "जन्म तिथि" and what does it mean). So the architecture below uses hill climbing twice — once for geometry, once for filtering — and reserves the LLM for the one thing it's actually needed for: understanding meaning, in a single batched call.

---

## 2. High-level pipeline

```
PDF/Image
   │
   ▼
[1] Preprocessing (deskew, denoise, DPI normalize)
   │
   ▼
[2] OCR with bounding boxes (multilingual)
   │
   ▼
[3] Form Gate — is this even a form?  ← rejects non-forms before any heavy work
   │  (structural/keyword heuristics; cheap classifier only if ambiguous)
   ▼  (reject → stop, return "not a form")
[4] Hill-Climb Pass 1: Field Grouping   ← geometry only, no LLM
   │  (clusters raw tokens into label/value candidates)
   ▼
[5] Hill-Climb Pass 2: Q&A Synthesis + Junk Pruning   ← selection, no LLM
   │  (turns candidates into questions, drops header/footer/decorative noise)
   ▼
[6] Optimized Q&A JSON  ("perfect questions" the form is implicitly asking)
   │
   ▼
[7] Single Optimized Prompt → LLM  (batched, minimal tokens — the only model call)
   │
   ▼
[8] Structured Field JSON  (question, label, value, type, bbox, confidence)
   │
   ▼
[9] Backend API
   │
   ▼
[10] Frontend: Drag-and-drop Field Editor + Live Preview
```

---

## 3. Phase-by-phase implementation

### Phase 0 — Scoping & data collection
- Collect 30–50 sample forms across languages/scripts you want to support (Latin, Devanagari, CJK, Arabic, etc.) and across form types (government forms, medical intake, invoices, surveys).
- Also collect 15–20 **non-form documents** (essays, receipts, photos, random scans) — you need these to build and test the form gate.
- Define your field taxonomy up front: `text`, `date`, `checkbox`, `signature`, `number`, `multiple-choice`, `table-cell`. This taxonomy drives extraction, the Q&A schema, and the editor UI.

### Phase 1 — Preprocessing
- PDF → image rendering: **PyMuPDF (fitz)** at 300 DPI.
- Image cleanup: OpenCV — deskew via Hough transform, adaptive thresholding, denoising.
- Output: a normalized page image + coordinate system you'll reuse throughout.

### Phase 2 — OCR with layout
- Use an OCR engine that returns **word-level bounding boxes**, not just plain text — non-negotiable, since both hill-climb passes need geometry.
- Recommended: **PaddleOCR** (strong multilingual support, 80+ languages, built-in layout detection) or **Google Cloud Vision / Azure Document Intelligence** if you want managed multilingual OCR and don't mind an API cost.
- Output per page: a list of tokens `{text, bbox, confidence, script/language}`.

### Phase 3 — Form Gate (is this a document worth processing?)
This runs before the expensive grouping work, so a non-form never reaches it.

- **Structural signals** (all computable from OCR output alone, language-independent): ratio of colons/underscores/boxes to total tokens, presence of grid/table lines, density of short label-like tokens followed by whitespace gaps, checkbox/radio glyph detection.
- Combine signals into a single form-likelihood score. High score → continue. Low score → reject immediately, no further cost incurred.
- **Ambiguous score only**: fall back to one cheap classification call (small model or single LLM call on a text summary, not the full document) to make the final call.
- Output: `{ "is_form": true/false, "confidence": 0.0-1.0 }`. If `false`, the pipeline stops and returns that result to the user.

### Phase 4 — Hill-Climb Pass 1: Field Grouping
Turns a flat bag of OCR tokens into field candidates (label + associated value/blank).

**State**: a partition of tokens into groups, each group a candidate field = `{label_tokens, value_region}`.

**Cost function** (lower is better):
- Spatial distance between label tokens and the adjacent value area
- Horizontal/vertical alignment consistency (forms are usually grid-aligned)
- Presence of separators (`:`, underscores, boxes, dotted lines) between label and value
- Whitespace-gap regularity (large uniform gaps usually mark a blank to fill)
- Penalize overlapping groups or orphaned tokens

**Move set (neighbors)**: merge two adjacent groups, split a group at a whitespace gap, reassign a token to a neighboring group, shift a boundary by one token.

```
current = initial_grouping(tokens)
current_cost = cost(current)
repeat until no improvement or max_iterations:
    neighbors = generate_neighbors(current)
    best_neighbor = argmin(cost(n) for n in neighbors)
    if cost(best_neighbor) < current_cost:
        current, current_cost = best_neighbor, cost(best_neighbor)
    else:
        break   # local optimum reached
```
Use **random-restart hill climbing** (5–10 runs from different initial groupings, keep the best) since plain hill climbing gets stuck in local optima on messy layouts — restarts are cheap CPU work, not model calls.

### Phase 5 — Hill-Climb Pass 2: Q&A Synthesis + Junk Pruning
This is the step that produces the "perfect questions and answers" set.

- **Synthesis (rule/template based, not LLM)**: for each field candidate from Pass 1, generate a canonical question from the label — e.g. a label token "DOB" or "जन्म तिथि" maps (via a template + light multilingual normalization) to a question like "What is the applicant's date of birth?" plus an expected answer type. Most common labels are covered by a template library; this needs no model call.
- **Pruning as a second hill climb**: now the *state* is "which subset of candidate fields to keep." The *cost function* rewards a subset that looks like a coherent, complete form (good coverage, consistent field density across the page) and penalizes candidates that look like junk — headers, watermarks, footers, page numbers, decorative lines, stray OCR noise, duplicate detections. Moves: add a candidate back in, drop a candidate, merge two overlapping candidates. Climb to a local optimum, same random-restart strategy as Pass 1.
- Output: the optimized Q&A JSON, e.g.:
```json
{
  "document_type": "form",
  "form_confidence": 0.96,
  "fields": [
    {
      "field_id": "f_003",
      "question": "What is the applicant's date of birth?",
      "original_label": "जन्म तिथि",
      "expected_answer_type": "date",
      "bbox": [120, 340, 200, 24],
      "grouping_score": 0.91
    },
    {
      "field_id": "f_004",
      "question": "What is the applicant's full name?",
      "original_label": "Name",
      "expected_answer_type": "text",
      "bbox": [120, 300, 260, 24],
      "grouping_score": 0.97
    }
  ],
  "junk_candidates_removed": 6
}
```

Both hill-climb passes run **without any LLM calls** — this is why the pipeline saves tokens.

### Phase 6 — Optimized Prompt → Single LLM Call
- Build one compact, structured prompt from the pruned Q&A JSON — not the raw OCR dump, not the image, not the full token list. The LLM's only job is to validate/normalize/translate the questions and extract or confirm the answer for each, in one batched call.
- This is the "highly optimized prompt": its size is bounded by the number of genuine fields on the form (typically 10–40), not by the size of the document.
- Output: the same JSON with each field's `value` filled in, labels normalized/translated, and low-confidence fields flagged for user review.

### Phase 7 — Structured output & backend API
- Final field schema:
```json
{
  "field_id": "f_012",
  "question": "What is the applicant's date of birth?",
  "label": "Date of Birth",
  "label_original_language": "जन्म तिथि",
  "type": "date",
  "value": "",
  "bbox": [x, y, w, h],
  "page": 1,
  "confidence": 0.93
}
```
- Backend: **FastAPI** (Python, same ecosystem as OCR/hill-climbing code).
- Endpoints:
  - `POST /documents` — upload PDF/image, kicks off the full pipeline (returns early with `is_form: false` if the form gate rejects it)
  - `GET /documents/{id}/fields` — returns extracted field JSON
  - `PATCH /documents/{id}/fields/{field_id}` — user corrections feed back into training/tuning data
  - `POST /forms` — save a user-built form layout (from the editor)
  - `GET /forms/{id}/preview` — render the assembled form

### Phase 8 — Frontend: drag-and-drop field editor
- **React** + **dnd-kit** for drag/drop.
- Left panel: list/palette of extracted fields (draggable cards showing question/label + detected type).
- Center canvas: drop target where the user arranges fields into a new form layout; snap-to-grid recommended.
- Each dropped field renders as an actual editable input matching its type.
- Right panel: field settings (rename label, change type, required/optional toggle).

### Phase 9 — Preview & export
- Live preview mode: render the arranged fields as a real fillable form.
- Export options: fillable PDF (pdf-lib or PyPDF for AcroForm generation), JSON schema, or HTML form.

### Phase 10 — Testing & tuning
- Build a small eval set (20–30 forms + 15–20 non-forms) with hand-labeled ground truth.
- Metrics: **form-gate accuracy** (false accepts/rejects), **grouping accuracy** (Pass 1), **pruning precision/recall** (Pass 2 — did it keep all real fields and drop all junk), **final answer accuracy** (Phase 6).
- Tune each cost function against its own metric before moving to the next stage — most of your accuracy gains come from the cost functions, not the LLM call.

### Phase 11 — Deployment
- Containerize (Docker): separate services for the OCR/pipeline worker (CPU/GPU heavy) and API/frontend.
- Queue heavy jobs (Celery/RQ + Redis) since OCR + two hill-climb passes on large multi-page PDFs can take a few seconds.

---

## 4. Suggested tech stack summary

| Layer | Choice |
|---|---|
| PDF rendering | PyMuPDF |
| Image preprocessing | OpenCV |
| OCR | PaddleOCR (self-hosted, multilingual) or Google Vision (managed) |
| Form gate | Rule-based scorer + fallback lightweight classifier |
| Field grouping (Pass 1) | Custom hill-climbing module (pure Python/NumPy) |
| Q&A synthesis + pruning (Pass 2) | Template library + hill-climbing module |
| Final extraction | LLM API, one batched call per document |
| Backend | FastAPI + PostgreSQL |
| Job queue | Celery + Redis |
| Frontend | React + dnd-kit + Tailwind |
| PDF export | pdf-lib (JS) or PyPDF (Python) for AcroForm generation |

---

## 5. Suggested build order (if working solo/small team)

1. OCR + preprocessing pipeline on a handful of sample forms (get clean tokens with bboxes).
2. Form gate — test against your form/non-form eval set until rejection accuracy is solid.
3. Hill-Climb Pass 1 (grouping) — test in isolation until field grouping is solid.
4. Q&A template library + Hill-Climb Pass 2 (pruning) — test junk precision/recall.
5. Backend API skeleton + field JSON schema.
6. Frontend editor (can be built in parallel once the field JSON schema is fixed).
7. Optimized-prompt LLM extraction call — add last, since it's the piece you're trying to minimize.
8. Export/preview, then multilingual testing pass.

