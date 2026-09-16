"""Phase 6 — Optimized prompt -> single LLM call (Google Gemini).

The prompt is built from the *pruned* Q&A JSON only: one compact line per
field (id, label, template question, expected type, detected value).  Its size
is bounded by the number of genuine fields (10-40), never by the document.

The model's only job: normalise / translate labels, validate the question,
confirm or extract the value, and flag low-confidence fields.  One batched
request per document, structured JSON output.

When no Gemini credentials are available (or ``FORM_LLM_DISABLED=1``) the
template output is passed through unchanged so the rest of the pipeline still
works; the document result records ``llm_used=False``.
"""
from __future__ import annotations

import base64
import json
import os
from typing import Optional

from app import settings
from app.schemas import ExtractedField, FieldType, QADocument


def get_client():
    """Gemini client using the key from the Settings page (or the environment)."""
    from google import genai

    key, _ = settings.api_key()
    if not key:
        raise RuntimeError("No Gemini API key configured. Add one on the Settings page.")
    return genai.Client(api_key=key)


def model_id() -> str:
    return settings.model()


SYSTEM_PROMPT = (
    "You validate fields extracted from a scanned form. Each input line is one candidate field: "
    "id | original label (any language) | template question | expected type | detected value. "
    "For every id return: label (short normalised English label), question (natural English question "
    "the form is asking), type (one of text,date,checkbox,signature,number,multiple-choice,table-cell), "
    "value (the detected answer normalised — ISO dates, plain numbers, empty string if blank), "
    "options (only for multiple-choice/checkbox: the choices if evident, else []), "
    "confidence (0-1 that this is a genuine form field with correct label/type), "
    "needs_review (true when confidence < 0.6 or the value is ambiguous). "
    "Keep every id exactly once. Do not invent fields. Be terse."
)

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
                    "type": {"type": "string",
                             "enum": ["text", "date", "checkbox", "signature", "number", "multiple-choice", "table-cell"]},
                    "value": {"type": "string"},
                    "options": {"type": "array", "items": {"type": "string"}},
                    "confidence": {"type": "number"},
                    "needs_review": {"type": "boolean"},
                },
                "required": ["id", "label", "question", "type", "value", "options", "confidence", "needs_review"],
            },
        }
    },
    "required": ["fields"],
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
        out.append(ExtractedField(field_id=fid, question=item.get("question") or f.question,
                                  label=item.get("label") or f.original_label, label_original_language=f.original_label,
                                  type=ftype, value=item.get("value", f.detected_value) or "", bbox=f.bbox, page=f.page,
                                  confidence=round(max(0.0, min(1.0, conf)), 3),
                                  needs_review=bool(item.get("needs_review", conf < 0.6)),
                                  options=[str(o) for o in item.get("options", [])] or f.options))
    # Any field the model dropped is kept from templates, flagged for review.
    for f in qa.fields:
        if f.field_id not in seen:
            p = _passthrough(QADocument(form_confidence=qa.form_confidence, fields=[f]))[0]
            p.needs_review = True
            out.append(p)
    out.sort(key=lambda x: x.field_id)
    return out


def extract_with_llm(qa: QADocument, use_llm: Optional[bool] = None) -> tuple[list[ExtractedField], dict]:
    """Return final fields + usage info. Exactly one API call when enabled."""
    from google import genai
    from google.genai import types

    info = {"llm_used": False, "input_tokens": 0, "output_tokens": 0, "model": None, "prompt_chars": 0}
    if not qa.fields:
        return [], info
    if use_llm is None:
        use_llm = llm_available()
    if not use_llm:
        return _passthrough(qa), info

    client = get_client()
    prompt = build_prompt(qa)
    info["prompt_chars"] = len(prompt)
    try:
        response = client.models.generate_content(
            model=model_id(),
            contents=f"{SYSTEM_PROMPT}\n\n{prompt}",
            config=types.GenerateContentConfig(
                response_mime_type="application/json",
                response_schema=OUTPUT_SCHEMA,
            ),
        )
    except Exception as e:
        _raise_gemini_error(e)

    text = response.text or ""
    data = json.loads(text)
    usage = response.usage_metadata
    info.update(
        llm_used=True,
        input_tokens=getattr(usage, "prompt_token_count", 0) if usage else 0,
        output_tokens=getattr(usage, "candidates_token_count", 0) if usage else 0,
        model=model_id(),
    )
    return _merge(qa, data), info


def classify_form_summary(summary: str) -> tuple[bool, float]:
    """Ambiguous-case form-gate classifier: tiny call on a text summary only."""
    from google import genai
    from google.genai import types

    client = get_client()
    schema = {
        "type": "object",
        "properties": {
            "is_form": {"type": "boolean"},
            "confidence": {"type": "number"},
        },
        "required": ["is_form", "confidence"],
    }
    system = (
        "Answer whether the text below comes from a fillable form (labels with blanks/boxes to fill) "
        "or a non-form document (prose, article, receipt, letter). Reply with JSON."
    )
    try:
        response = client.models.generate_content(
            model=model_id(),
            contents=f"{system}\n\n{summary}",
            config=types.GenerateContentConfig(
                response_mime_type="application/json",
                response_schema=schema,
            ),
        )
    except Exception as e:
        _raise_gemini_error(e)

    data = json.loads(response.text or "{}")
    return bool(data.get("is_form", False)), float(data.get("confidence", 0.5))


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
            },
        }
    },
    "required": ["lines"],
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


def _encode_image(gray) -> tuple[bytes, int, int]:
    import cv2

    h, w = gray.shape[:2]
    scale = min(1.0, MAX_IMAGE_SIDE / max(h, w))
    img = cv2.resize(gray, (int(w * scale), int(h * scale)), interpolation=cv2.INTER_AREA) if scale < 1 else gray
    ok, buf = cv2.imencode(".png", img)
    return buf.tobytes(), img.shape[1], img.shape[0]


def read_page_image(gray) -> list[dict]:
    """One vision call per scanned page -> [{text, bbox(normalised 0-1)}]."""
    from google import genai
    from google.genai import types

    client = get_client()
    img_bytes, _, _ = _encode_image(gray)

    try:
        response = client.models.generate_content(
            model=model_id(),
            contents=[
                types.Part.from_bytes(data=img_bytes, mime_type="image/png"),
                OCR_PROMPT,
            ],
            config=types.GenerateContentConfig(
                response_mime_type="application/json",
                response_schema=OCR_SCHEMA,
            ),
        )
    except Exception as e:
        _raise_gemini_error(e)

    lines = json.loads(response.text or "{}").get("lines", [])
    out = []
    for ln in lines:
        b = ln.get("bbox") or []
        if len(b) != 4 or not str(ln.get("text", "")).strip():
            continue
        x, y, w, h = (max(0.0, min(1.0, float(v))) for v in b)
        if w <= 0 or h <= 0:
            continue
        out.append({"text": str(ln["text"]).strip(), "bbox": [x, y, w, h]})
    return out


def test_connection() -> dict:
    """Validate the configured key with a lightweight generate call."""
    try:
        client = get_client()
        response = client.models.generate_content(
            model=model_id(),
            contents="Reply with the single word: ok",
        )
        return {"ok": True, "model": model_id()}
    except RuntimeError as e:
        return {"ok": False, "error": str(e)}
    except Exception as e:
        return {"ok": False, "error": _gemini_error_message(e)}


# ---------------------------------------------------------------- helpers

def _gemini_error_message(e: Exception) -> str:
    """Convert google-genai exceptions to human-readable strings."""
    name = type(e).__name__
    msg = str(e)
    if "API_KEY_INVALID" in msg or "invalid" in msg.lower() and "key" in msg.lower():
        return "Gemini API key was rejected. Check it on the Settings page."
    if "RESOURCE_EXHAUSTED" in msg or "quota" in msg.lower():
        return f"Gemini rate limit / quota exceeded: {msg}"
    if "NOT_FOUND" in msg or "not found" in msg.lower():
        return f"Model {model_id()!r} not found for this key."
    if "PERMISSION_DENIED" in msg:
        return "Gemini API key lacks permission (403)."
    return f"Gemini API error ({name}): {msg}"


def _raise_gemini_error(e: Exception) -> None:
    raise RuntimeError(_gemini_error_message(e)) from e
