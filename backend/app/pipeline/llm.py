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
import threading
from typing import Optional

from app import settings
from app.providers import Provider, ProviderError, Usage
from app.schemas import ExtractedField, FieldType, QADocument

# --------------------------------------------------------------- usage ledger
# Every model call made while processing a document is recorded here so the
# hill-climb dialog can show exactly how tokens were spent (OCR, gate,
# validation, image extraction), not just the validation call.
LEDGER: list[dict] = []
_LEDGER_LOCK = threading.Lock()


def ledger_reset() -> None:
    with _LEDGER_LOCK:
        LEDGER.clear()


def ledger_snapshot() -> list[dict]:
    with _LEDGER_LOCK:
        return [dict(x) for x in LEDGER]


def _call(provider: Provider, purpose: str, system: str, text: str, schema: dict, image_png: Optional[bytes] = None,
          max_tokens: int = 8000) -> tuple[dict, Usage]:
    import time as _t

    t0 = _t.perf_counter()
    data, usage = provider.complete_json(system, text, schema, image_png=image_png, max_tokens=max_tokens)
    with _LEDGER_LOCK:
        LEDGER.append({"purpose": purpose, "provider": usage.provider, "model": usage.model,
                       "input_tokens": usage.input_tokens, "output_tokens": usage.output_tokens,
                       "with_image": image_png is not None, "ms": round((_t.perf_counter() - t0) * 1000)})
    return data, usage

SYSTEM_PROMPT = (
    "Form fields: `id|label|hint|value` per line (label may be any language; hint = template key or ?). "
    "Return every id once with: label (short Title Case English), type "
    "(text|date|checkbox|signature|number|multiple-choice|table-cell), value (normalised: ISO date, plain number, "
    "'' if blank), review (true only if label/type unsure or a present value is ambiguous). "
    "Add options only for multiple-choice. Omit question. Be terse."
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
                    "type": {"type": "string", "enum": FIELD_TYPES},
                    "value": {"type": "string"},
                    "review": {"type": "boolean"},
                    "options": {"type": "array", "items": {"type": "string"}},
                },
                "required": ["id", "label", "type", "value", "review"],
                "additionalProperties": False,
            },
        }
    },
    "required": ["fields"],
    "additionalProperties": False,
}


def field_needs_ai(f) -> bool:
    """Only fields the templates could not settle are worth model tokens."""
    if not f.template_key:
        return True
    if f.detected_value.strip() and not f.options:
        return True  # a filled-in answer to normalise / confirm
    return f.grouping_score < 0.6


def select_for_ai(qa: QADocument) -> list:
    return [f for f in qa.fields if field_needs_ai(f)]


def estimate_tokens(text: str) -> int:
    """Rough, provider-neutral token estimate: ~4 chars/token for ASCII, ~1.5 chars/token for other scripts."""
    if not text:
        return 0
    ascii_chars = sum(1 for ch in text if ch.isascii())
    other = len(text) - ascii_chars
    return int(ascii_chars / 4 + other / 1.5) + text.count("\n")


def estimate_image_tokens(width: float, height: float) -> int:
    """Tokens a page image would cost (Gemini: 258 per 768px tile; Claude: w*h/750 — use the Gemini rule)."""
    w, h = max(1.0, width), max(1.0, height)
    scale = min(1.0, MAX_IMAGE_SIDE / max(w, h))
    tiles_x = max(1, int(-(-w * scale // 768)))
    tiles_y = max(1, int(-(-h * scale // 768)))
    return 258 * tiles_x * tiles_y


def build_prompt(qa: QADocument, fields=None) -> str:
    """One compact line per field that needs the model: id|label|hint|value."""
    fields = qa.fields if fields is None else fields
    lines = []
    for f in fields:
        hint = f.template_key or "?"
        value = ("opts:" + "/".join(f.options)) if f.options else (f.detected_value or "")
        lines.append(f"{f.field_id}|{f.original_label}|{hint}|{value}")
    return "\n".join(lines)


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


def _merge(qa: QADocument, data: dict, sent_ids: Optional[set] = None) -> list[ExtractedField]:
    """Combine the model's answers (slim schema) with template passthrough for everything else."""
    by_id = {f.field_id: f for f in qa.fields}
    sent_ids = set(by_id) if sent_ids is None else sent_ids
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
        value = item.get("value", f.detected_value) or ""
        label = item.get("label") or f.original_label
        # A blank field needs no human look, whatever the model's flag says.
        needs_review = bool(item.get("review", item.get("needs_review"))) and bool(value.strip())
        question = f.question if f.template_key else f"What is the {label.lower()}?"
        out.append(ExtractedField(field_id=fid, question=question, label=label, label_original_language=f.original_label,
                                  type=ftype, value=value, bbox=f.bbox, page=f.page, confidence=0.9,
                                  needs_review=needs_review,
                                  options=[str(o) for o in item.get("options", []) or []] or f.options))
    passthrough = _passthrough(QADocument(form_confidence=qa.form_confidence,
                                          fields=[f for f in qa.fields if f.field_id not in seen]))
    for p in passthrough:
        if p.field_id in sent_ids:
            p.needs_review = True  # the model dropped a field we asked about
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
    chosen = select_for_ai(qa)
    info["fields_sent"] = len(chosen)
    info["fields_total"] = len(qa.fields)
    if not chosen:
        info["skipped"] = "templates settled every field; nothing to ask the model"
        return _passthrough(qa), info
    prompt = build_prompt(qa, chosen)
    info["prompt_chars"] = len(prompt)
    try:
        data, usage = _call(provider, "validation", SYSTEM_PROMPT, prompt, OUTPUT_SCHEMA,
                            max_tokens=min(8000, 40 * len(chosen) + 200))
    except ProviderError as e:
        if "declined" in str(e):
            return _passthrough(qa), info
        raise RuntimeError(str(e)) from e
    info.update(llm_used=True, input_tokens=usage.input_tokens, output_tokens=usage.output_tokens,
                model=usage.model, provider=usage.provider)
    return _merge(qa, data, {f.field_id for f in chosen}), info


# ------------------------------------------------------- form-gate fallback

GATE_SCHEMA = {"type": "object", "properties": {"is_form": {"type": "boolean"}, "confidence": {"type": "number"}},
               "required": ["is_form", "confidence"], "additionalProperties": False}


FORM_CRITERIA = [
    "It exists to be filled in: printed labels are followed by blanks, underlines, boxes, cells or checkboxes for an answer.",
    "Most of the page is labels + empty (or filled) answer space, arranged in rows/columns — not paragraphs of prose.",
    "Typical kinds: application / registration / admission / KYC / bank / insurance / medical intake / survey / "
    "questionnaire / tax / visa / employment / feedback forms, invoices or receipts with blank fields, checklists.",
    "Filled-in forms still count (handwritten or typed answers next to the labels).",
    "NOT forms: articles, essays, letters, emails, reports, books, slides, receipts/tickets that are fully printed, "
    "ID cards, certificates, photos of scenes or objects, screenshots of chats/websites, plain data tables with no blanks.",
]


def criteria_text() -> str:
    return "A document is a fillable FORM when:\n" + "\n".join(f"- {c}" for c in FORM_CRITERIA)


def classify_form_summary(summary: str) -> tuple[bool, float]:
    """Ambiguous-case form-gate classifier: tiny call on a text summary only."""
    data, _ = _call(settings.get_provider("gate"), "form check (text)",
                    criteria_text() + "\nDecide from the OCR text below whether it comes from a fillable form. Reply with JSON.",
                    summary, GATE_SCHEMA, max_tokens=64)
    return bool(data["is_form"]), float(data["confidence"])


# ---------------------------------------------------------------- vision OCR

FIELD_ITEM_SCHEMA = {
    "type": "object",
    "properties": {
        "label": {"type": "string"}, "label_original_language": {"type": "string"},
        "type": {"type": "string", "enum": FIELD_TYPES}, "value": {"type": "string"},
        "options": {"type": "array", "items": {"type": "string"}},
        "bbox": {"type": "array", "items": {"type": "number"}, "minItems": 4, "maxItems": 4},
        "confidence": {"type": "number"},
    },
    "required": ["label", "label_original_language", "type", "value", "options", "bbox", "confidence"],
    "additionalProperties": False,
}

OCR_SCHEMA = {
    "type": "object",
    "properties": {
        "is_form": {"type": "boolean"},
        "form_confidence": {"type": "number"},
        "fields": {"type": "array", "items": FIELD_ITEM_SCHEMA},
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
    "required": ["is_form", "form_confidence", "fields", "lines"],
    "additionalProperties": False,
}

OCR_PROMPT = (
    "First decide is_form (true when the page is a fillable form per the criteria) with form_confidence 0-1. "
    "If it is a form, list its fillable fields under `fields` (label in English, label_original_language as printed, "
    "type, filled-in value or '', options for choices, bbox [x,y,w,h] as fractions 0-1 around label+blank, "
    "confidence); skip titles, instructions, footers. Then "
    "transcribe every piece of text on this page, one entry per visual line segment. Keep the original "
    "language and script exactly; do not translate. Split a line into separate entries wherever there is a wide "
    "gap (e.g. two fields side by side). Write fill-in underlines as '______', dotted lines as '......', and "
    "empty checkboxes as '☐' (ticked as '☑'). For each entry give bbox = [x, y, w, h] as fractions of the image "
    "width/height (0-1, origin top-left), tight around the text. Include titles, instructions, footers and page "
    "numbers too. Return only the JSON."
)

MAX_IMAGE_SIDE = 1536  # 2x2 Gemini tiles (768 px each) instead of 3x2 at 1568


def encode_image(gray) -> bytes:
    import cv2

    h, w = gray.shape[:2]
    scale = min(1.0, MAX_IMAGE_SIDE / max(h, w))
    img = cv2.resize(gray, (int(w * scale), int(h * scale)), interpolation=cv2.INTER_AREA) if scale < 1 else gray
    ok, buf = cv2.imencode(".png", img)
    return buf.tobytes()


LAST_VISION_VERDICT: dict = {}  # {id(gray) -> (is_form, confidence)} — lets the gate reuse the OCR call's verdict
LAST_VISION_FIELDS: dict = {}   # {id(gray) -> [raw field dicts]} — the same call's field list, no second request


def read_page_image(gray, provider: Optional[Provider] = None) -> list[dict]:
    """One vision call per scanned page -> [{text, bbox(normalised 0-1)}] (+ the form verdict, cached)."""
    provider = provider or settings.get_provider()
    try:
        data, _ = _call(provider, "OCR (vision)", "You are a precise OCR engine.\n" + criteria_text(), OCR_PROMPT, OCR_SCHEMA,
                        image_png=encode_image(gray), max_tokens=16000)
    except ProviderError as e:
        raise RuntimeError(str(e)) from e
    if "is_form" in data:
        LAST_VISION_VERDICT.clear()
        LAST_VISION_VERDICT[id(gray)] = (bool(data["is_form"]), float(data.get("form_confidence", 0.5)))
        LAST_VISION_FIELDS.clear()
        LAST_VISION_FIELDS[id(gray)] = list(data.get("fields") or [])
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


# --------------------------------------------------- vision form gate / extraction

GATE_IMAGE_SCHEMA = {"type": "object",
                     "properties": {"is_form": {"type": "boolean"}, "confidence": {"type": "number"}, "reason": {"type": "string"}},
                     "required": ["is_form", "confidence", "reason"], "additionalProperties": False}


def classify_form_image(image_png: bytes, provider: Optional[Provider] = None) -> tuple[bool, float, str]:
    """Look at the page and decide whether it is a fillable form (used before rejecting a scan)."""
    provider = provider or settings.get_provider("gate")
    data, _ = _call(provider, "form check (image)", "You classify document images.\n" + criteria_text() + "\nReply with JSON.",
                    "Is this image a fillable form? Give a one-sentence reason.", GATE_IMAGE_SCHEMA, image_png=image_png, max_tokens=200)
    return bool(data["is_form"]), float(data["confidence"]), str(data.get("reason", ""))


FIELDS_IMAGE_SCHEMA = {
    "type": "object",
    "properties": {"fields": {"type": "array", "items": {"type": "object", "properties": {
        "label": {"type": "string"}, "label_original_language": {"type": "string"}, "question": {"type": "string"},
        "type": {"type": "string", "enum": FIELD_TYPES}, "value": {"type": "string"},
        "options": {"type": "array", "items": {"type": "string"}},
        "bbox": {"type": "array", "items": {"type": "number"}, "minItems": 4, "maxItems": 4},
        "confidence": {"type": "number"}},
        "required": ["label", "label_original_language", "question", "type", "value", "options", "bbox", "confidence"],
        "additionalProperties": False}}},
    "required": ["fields"], "additionalProperties": False,
}


def extract_fields_from_image(image_png: bytes, width: float, height: float, page: int = 1,
                              provider: Optional[Provider] = None) -> tuple[list[ExtractedField], dict]:
    """Fallback for scans where OCR gave too little geometry to group: read the fields straight off the image."""
    provider = provider or settings.get_provider()
    data, usage = _call(provider, "field extraction (image)",
        "You extract the fillable fields of a form image. For every field give: label (English), "
        "label_original_language (as printed), question (what the form asks), type (text,date,checkbox,signature,"
        "number,multiple-choice,table-cell), value (filled-in answer, else empty), options (for choices), "
        "bbox [x,y,w,h] as fractions 0-1 of the image (origin top-left) around the label+blank, confidence 0-1. "
        "Skip titles, instructions, footers and page numbers.", "List every field on this form.",
        FIELDS_IMAGE_SCHEMA, image_png=image_png, max_tokens=16000)
    fields = vision_fields_to_extracted(data.get("fields", []), width, height, page)
    info = {"llm_used": True, "input_tokens": usage.input_tokens, "output_tokens": usage.output_tokens,
            "model": usage.model, "provider": usage.provider}
    return fields, info


def vision_fields_to_extracted(raw: list[dict], width: float, height: float, page: int = 1) -> list[ExtractedField]:
    fields = []
    for i, f in enumerate(raw, start=1):
        try:
            ftype = FieldType(f.get("type", "text"))
        except ValueError:
            ftype = FieldType.TEXT
        b = f.get("bbox") or [0, 0, 0, 0]
        b = [max(0.0, min(1.0, float(v))) for v in b] if len(b) == 4 else [0, 0, 0, 0]
        conf = float(f.get("confidence", 0.7))
        label = f.get("label") or f.get("label_original_language") or "Field"
        if not str(label).strip():
            continue
        fields.append(ExtractedField(field_id=f"f_{i:03d}", question=f"What is the {str(label).lower()}?",
                                     label=str(label), label_original_language=f.get("label_original_language") or str(label),
                                     type=ftype, value=f.get("value") or "", options=[str(o) for o in f.get("options", []) or []],
                                     bbox=[round(b[0] * width, 1), round(b[1] * height, 1), round(b[2] * width, 1), round(b[3] * height, 1)],
                                     page=page, confidence=round(max(0.0, min(1.0, conf)), 3), needs_review=conf < 0.6))
    return fields
