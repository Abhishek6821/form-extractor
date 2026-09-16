"""Phase 6 — Optimized prompt -> single LLM call (provider-agnostic).

The prompt is built from the *pruned* Q&A JSON only: one compact line per
field.  Its size is bounded by the number of genuine fields (10-40), never by
the document.  The model's only job: normalise / translate labels, validate
the question, confirm or extract the value, flag low-confidence fields.

Claude or Gemini (chosen in Settings) sit behind ``app.providers``; the output
schema — and therefore every ``ExtractedField`` — is identical for both.
When no provider is configured the template output is passed through
unchanged (``llm_used=False``).
"""
from __future__ import annotations

import base64
from typing import Optional

from app import settings
from app.providers import Provider, ProviderError
from app.schemas import ExtractedField, FieldType, QADocument

SYSTEM_PROMPT = (
    "You validate fields extracted from a scanned form. Each input line is one candidate field: "
    "id | original label (any language) | template question | expected type | detected value. "
    "For every id return: label (short normalised English label), question (natural English question "
    "the form is asking), type (one of text,date,checkbox,signature,number,multiple-choice,table-cell), "
    "value (the detected answer normalised — ISO dates, plain numbers, empty string if blank), "
    "options (only for multiple-choice/checkbox: the choices if evident, else []), "
    "confidence (0-1 that this is a genuine form field with correct label/type), "
    "needs_review (true only when the label/type is uncertain or a PRESENT value is ambiguous; a blank field "
    "on an unfilled form is normal and must NOT be flagged). Use Title Case for labels. "
    "Keep every id exactly once. Do not invent fields. Be terse."
)

FIELD_TYPES = ["text", "date", "checkbox", "signature", "number", "multiple-choice", "table-cell"]

OUTPUT_SCHEMA = {
    "type": "object",
    "properties": {
        "fields": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "id": {"type": "string"},
                    "label": {"type": "string"},
                    "question": {"type": "string"},
                    "type": {"type": "string", "enum": FIELD_TYPES},
                    "value": {"type": "string"},
                    "options": {"type": "array", "items": {"type": "string"}},
                    "confidence": {"type": "number"},
                    "needs_review": {"type": "boolean"},
                },
                "required": ["id", "label", "question", "type", "value", "options", "confidence", "needs_review"],
                "additionalProperties": False,
            },
        }
    },
    "required": ["fields"],
    "additionalProperties": False,
}


def build_prompt(qa: QADocument) -> str:
    lines = [f"{f.field_id} | {f.original_label} | {f.question} | {f.expected_answer_type.value} | "
             f"{('options: ' + ', '.join(f.options)) if f.options else (f.detected_value or '')}"
             for f in qa.fields]
    return "Fields:\n" + "\n".join(lines)


def _passthrough(qa: QADocument) -> list[ExtractedField]:
    from app.pipeline.templates import synthesize_question

    out = []
    for f in qa.fields:
        syn = synthesize_question(f.original_label, f.detected_value)
        conf = 0.45 + 0.35 * syn["match"] + 0.2 * f.grouping_score
        out.append(ExtractedField(field_id=f.field_id, question=f.question, label=syn["label_en"],
                                  label_original_language=f.original_label, type=f.expected_answer_type,
                                  value="" if f.options else f.detected_value, bbox=f.bbox, page=f.page,
                                  confidence=round(min(conf, 0.95), 3), needs_review=conf < 0.6,
                                  options=f.options or syn["options"]))
    return out


def llm_available() -> bool:
    return settings.llm_enabled()


def _merge(qa: QADocument, data: dict) -> list[ExtractedField]:
    by_id = {f.field_id: f for f in qa.fields}
    out: list[ExtractedField] = []
    seen = set()
    for item in data.get("fields", []):
        fid = item.get("id")
        if fid not in by_id or fid in seen:
            continue
        seen.add(fid)
        f = by_id[fid]
        try:
            ftype = FieldType(item.get("type", f.expected_answer_type.value))
        except ValueError:
            ftype = f.expected_answer_type
        conf = float(item.get("confidence", 0.5))
        value = item.get("value", f.detected_value) or ""
        # A blank field the model is confident about needs no human look, whatever the model's flag says.
        needs_review = conf < 0.6 or (bool(item.get("needs_review")) and bool(value.strip()))
        out.append(ExtractedField(field_id=fid, question=item.get("question") or f.question,
                                  label=item.get("label") or f.original_label, label_original_language=f.original_label,
                                  type=ftype, value=value, bbox=f.bbox, page=f.page,
                                  confidence=round(max(0.0, min(1.0, conf)), 3),
                                  needs_review=needs_review,
                                  options=[str(o) for o in item.get("options", [])] or f.options))
    for f in qa.fields:  # anything the model dropped is kept from templates, flagged for review
        if f.field_id not in seen:
            p = _passthrough(QADocument(form_confidence=qa.form_confidence, fields=[f]))[0]
            p.needs_review = True
            out.append(p)
    out.sort(key=lambda x: x.field_id)
    return out


def extract_with_llm(qa: QADocument, use_llm: Optional[bool] = None, provider: Optional[Provider] = None
                     ) -> tuple[list[ExtractedField], dict]:
    """Return final fields + usage info. Exactly one provider call when enabled."""
    info = {"llm_used": False, "input_tokens": 0, "output_tokens": 0, "model": None, "provider": None, "prompt_chars": 0}
    if not qa.fields:
        return [], info
    if use_llm is None:
        use_llm = llm_available()
    if not use_llm:
        return _passthrough(qa), info
    provider = provider or settings.get_provider()
    prompt = build_prompt(qa)
    info["prompt_chars"] = len(prompt)
    try:
        data, usage = provider.complete_json(SYSTEM_PROMPT, prompt, OUTPUT_SCHEMA, max_tokens=8000)
    except ProviderError as e:
        if "declined" in str(e):
            return _passthrough(qa), info
        raise RuntimeError(str(e)) from e
    info.update(llm_used=True, input_tokens=usage.input_tokens, output_tokens=usage.output_tokens,
                model=usage.model, provider=usage.provider)
    return _merge(qa, data), info


# ------------------------------------------------------- form-gate fallback

GATE_SCHEMA = {"type": "object", "properties": {"is_form": {"type": "boolean"}, "confidence": {"type": "number"}},
               "required": ["is_form", "confidence"], "additionalProperties": False}


def classify_form_summary(summary: str) -> tuple[bool, float]:
    """Ambiguous-case form-gate classifier: tiny call on a text summary only."""
    data, _ = settings.get_provider().complete_json(
        "Answer whether the text below comes from a fillable form (labels with blanks/boxes to fill) "
        "or a non-form document (prose, article, receipt, letter). Reply with JSON.", summary, GATE_SCHEMA, max_tokens=64)
    return bool(data["is_form"]), float(data["confidence"])


# ---------------------------------------------------------------- vision OCR

OCR_SCHEMA = {
    "type": "object",
    "properties": {
        "lines": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "text": {"type": "string"},
                    "bbox": {"type": "array", "items": {"type": "number"}, "minItems": 4, "maxItems": 4},
                },
                "required": ["text", "bbox"],
                "additionalProperties": False,
            },
        }
    },
    "required": ["lines"],
    "additionalProperties": False,
}

OCR_PROMPT = (
    "Transcribe every piece of text on this scanned form, one entry per visual line segment. Keep the original "
    "language and script exactly; do not translate. Split a line into separate entries wherever there is a wide "
    "gap (e.g. two fields side by side). Write fill-in underlines as '______', dotted lines as '......', and "
    "empty checkboxes as '☐' (ticked as '☑'). For each entry give bbox = [x, y, w, h] as fractions of the image "
    "width/height (0-1, origin top-left), tight around the text. Include titles, instructions, footers and page "
    "numbers too. Return only the JSON."
)

MAX_IMAGE_SIDE = 1568


def encode_image(gray) -> bytes:
    import cv2

    h, w = gray.shape[:2]
    scale = min(1.0, MAX_IMAGE_SIDE / max(h, w))
    img = cv2.resize(gray, (int(w * scale), int(h * scale)), interpolation=cv2.INTER_AREA) if scale < 1 else gray
    ok, buf = cv2.imencode(".png", img)
    return buf.tobytes()


def read_page_image(gray, provider: Optional[Provider] = None) -> list[dict]:
    """One vision call per scanned page -> [{text, bbox(normalised 0-1)}]."""
    provider = provider or settings.get_provider()
    try:
        data, _ = provider.complete_json("You are a precise OCR engine.", OCR_PROMPT, OCR_SCHEMA,
                                         image_png=encode_image(gray), max_tokens=16000)
    except ProviderError as e:
        raise RuntimeError(str(e)) from e
    out = []
    for ln in data.get("lines", []):
        b = ln.get("bbox") or []
        if len(b) != 4 or not str(ln.get("text", "")).strip():
            continue
        x, y, w, h = (max(0.0, min(1.0, float(v))) for v in b)
        if w <= 0 or h <= 0:
            continue
        out.append({"text": str(ln["text"]).strip(), "bbox": [x, y, w, h]})
    return out


def test_connection() -> dict:
    try:
        return settings.get_provider().test_connection()
    except ProviderError as e:
        return {"ok": False, "error": str(e)}
