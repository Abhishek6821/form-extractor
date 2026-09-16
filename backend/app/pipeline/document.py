"""Document mode — extract everything from a page that is *not* a fillable form.

The form gate no longer rejects documents.  A non-form (invoice, receipt,
letter, article, ID card, a photo of a sign...) goes through this module:

* one LLM call (text, plus the page image for scans) → document type, title,
  language, summary and a list of key facts, each mapped to an
  ``ExtractedField`` so the editor and exports work exactly as for forms;
* without an LLM, a heuristic fallback finds dates / emails / phones / amounts
  / URLs / ids with regexes and keeps the full text.
"""
from __future__ import annotations

import re
from typing import Optional

from app.pipeline import geometry as g
from app.providers import Provider, ProviderError
from app.schemas import DocumentInfo, ExtractedField, FieldType, Page

DOC_TYPES = ["form", "invoice", "receipt", "letter", "article", "report", "id-card", "certificate", "resume",
             "contract", "bank-statement", "prescription", "ticket", "menu", "sign", "handwritten-note", "table",
             "photo", "other"]

SYSTEM_PROMPT = (
    "You extract everything useful from a document image or its OCR text. Identify what the document is, then "
    "list every key fact as label/value pairs (names, dates, ids, amounts, addresses, phone numbers, emails, "
    "totals, line items, parties, headings). Keep values in the original language; give labels in English. "
    "Use the field types text,date,number,checkbox,multiple-choice,signature,table-cell. Write dates as ISO. "
    "Return the full text in reading order under full_text (verbatim, all languages). Be exhaustive but do not invent."
)

SCHEMA = {
    "type": "object",
    "properties": {
        "document_type": {"type": "string", "enum": DOC_TYPES},
        "title": {"type": "string"},
        "language": {"type": "string"},
        "summary": {"type": "string"},
        "full_text": {"type": "string"},
        "facts": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "label": {"type": "string"},
                    "value": {"type": "string"},
                    "type": {"type": "string", "enum": ["text", "date", "number", "checkbox", "multiple-choice", "signature", "table-cell"]},
                    "confidence": {"type": "number"},
                },
                "required": ["label", "value", "type", "confidence"],
                "additionalProperties": False,
            },
        },
    },
    "required": ["document_type", "title", "language", "summary", "full_text", "facts"],
    "additionalProperties": False,
}


def page_text(pages: list[Page]) -> str:
    out = []
    for p in pages:
        for r in g.cluster_rows(p.tokens):
            out.append(" ".join(p.tokens[i].text for i in r))
    return "\n".join(out)


def _heuristic(pages: list[Page]) -> tuple[DocumentInfo, list[ExtractedField]]:
    text = page_text(pages)
    lines = [ln for ln in text.splitlines() if ln.strip()]
    title = lines[0][:120] if lines else ""
    info = DocumentInfo(document_type="document", title=title, language="", summary=" ".join(lines[1:4])[:300], full_text=text)
    facts: list[tuple[str, str, FieldType]] = []
    for m in re.finditer(r"\b\d{1,2}[/.\-]\d{1,2}[/.\-]\d{2,4}\b|\b\d{4}-\d{2}-\d{2}\b", text):
        facts.append(("Date", m.group(0), FieldType.DATE))
    for m in re.finditer(r"[\w.+-]+@[\w-]+\.[\w.-]+", text):
        facts.append(("Email", m.group(0), FieldType.TEXT))
    for m in re.finditer(r"(?<!\d)(?:\+\d{1,3}[\s-]?)?(?:\d[\s-]?){9,12}\d(?!\d)", text):
        facts.append(("Phone", m.group(0).strip(), FieldType.NUMBER))
    for m in re.finditer(r"(?:₹|\$|€|£|Rs\.?|INR|USD|EUR)\s?\d[\d,]*(?:\.\d+)?", text):
        facts.append(("Amount", m.group(0), FieldType.NUMBER))
    for m in re.finditer(r"https?://\S+|www\.\S+", text):
        facts.append(("Website", m.group(0), FieldType.TEXT))
    for m in re.finditer(r"\b(?:invoice|bill|order|ref|receipt|ticket|id)\s*(?:no|number|#)?[.:\s]*([A-Z0-9][A-Z0-9\-/]{3,})", text, re.I):
        facts.append(("Reference Number", m.group(1), FieldType.TEXT))
    seen = set()
    fields = []
    for label, value, ftype in facts:
        key = (label, value)
        if key in seen:
            continue
        seen.add(key)
        fields.append(_field(len(fields) + 1, label, value, ftype, 0.5))
    return info, fields


def _field(n: int, label: str, value: str, ftype: FieldType, conf: float, page: int = 1) -> ExtractedField:
    return ExtractedField(field_id=f"d_{n:03d}", question=f"What is the {label.lower()}?", label=label,
                          label_original_language=label, type=ftype, value=value, bbox=[0, 0, 0, 0], page=page,
                          confidence=round(max(0.0, min(1.0, conf)), 3), needs_review=conf < 0.6)


def extract_document(pages: list[Page], images: Optional[list[bytes]] = None, provider: Optional[Provider] = None,
                     use_llm: Optional[bool] = None) -> tuple[DocumentInfo, list[ExtractedField], dict]:
    """Return (info, fields, usage). One provider call per document when an LLM is available."""
    from app import settings

    usage = {"llm_used": False, "input_tokens": 0, "output_tokens": 0, "model": None, "provider": None}
    if use_llm is None:
        use_llm = settings.llm_enabled()
    if not use_llm:
        info, fields = _heuristic(pages)
        return info, fields, usage
    provider = provider or settings.get_provider()
    text = page_text(pages)
    prompt = "OCR text of the document:\n" + (text[:20000] if text.strip() else "(no text layer — read the image)")
    image = images[0] if images else None
    try:
        data, u = provider.complete_json(SYSTEM_PROMPT, prompt, SCHEMA, image_png=image, max_tokens=16000)
    except ProviderError as e:
        raise RuntimeError(str(e)) from e
    usage.update(llm_used=True, input_tokens=u.input_tokens, output_tokens=u.output_tokens, model=u.model, provider=u.provider)
    info = DocumentInfo(document_type=data.get("document_type") or "other", title=data.get("title", ""),
                        language=data.get("language", ""), summary=data.get("summary", ""),
                        full_text=data.get("full_text") or text)
    fields = []
    for i, f in enumerate(data.get("facts", []), start=1):
        try:
            ftype = FieldType(f.get("type", "text"))
        except ValueError:
            ftype = FieldType.TEXT
        if not str(f.get("label", "")).strip():
            continue
        fields.append(_field(i, str(f["label"]).strip(), str(f.get("value", "")), ftype, float(f.get("confidence", 0.7))))
    return info, fields, usage
