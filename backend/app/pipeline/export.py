"""Phase 9 — Export a form layout as fillable PDF (AcroForm), HTML or JSON Schema."""
from __future__ import annotations

import html
import io
import json

from app.schemas import FieldType, FormLayout

PAGE_W, PAGE_H = 595.0, 842.0  # A4 points
MARGIN = 40.0
ROW_H = 34.0
LABEL_H = 12.0


def _grid_to_page(layout: FormLayout):
    """Map grid units to A4 points; returns list of (field, x, y_top, w, h)."""
    col_w = (PAGE_W - 2 * MARGIN) / max(layout.grid_columns, 1)
    out = []
    for f in sorted(layout.fields, key=lambda f: (f.y, f.x)):
        x = MARGIN + f.x * col_w
        w = max(col_w, f.w * col_w) - 6
        y_top = MARGIN + 40 + f.y * ROW_H
        h = max(1, f.h) * ROW_H - 8
        out.append((f, x, y_top, w, h))
    return out


def to_json_schema(layout: FormLayout) -> dict:
    props = {}
    required = []
    type_map = {FieldType.TEXT: "string", FieldType.DATE: "string", FieldType.CHECKBOX: "boolean",
                FieldType.SIGNATURE: "string", FieldType.NUMBER: "number", FieldType.MULTIPLE_CHOICE: "string",
                FieldType.TABLE_CELL: "string"}
    for f in layout.fields:
        p: dict = {"type": type_map[f.type], "title": f.label}
        if f.type == FieldType.DATE:
            p["format"] = "date"
        if f.type == FieldType.MULTIPLE_CHOICE and f.options:
            p["enum"] = f.options
        if f.type == FieldType.SIGNATURE:
            p["contentEncoding"] = "base64"
            p["description"] = "Signature image"
        props[f.field_id] = p
        if f.required:
            required.append(f.field_id)
    return {"$schema": "https://json-schema.org/draft/2020-12/schema", "title": layout.title, "type": "object",
            "properties": props, "required": required}


def to_html(layout: FormLayout) -> str:
    rows = []
    for f in sorted(layout.fields, key=lambda f: (f.y, f.x)):
        lab = html.escape(f.label)
        fid = html.escape(f.field_id)
        req = " required" if f.required else ""
        if f.type == FieldType.CHECKBOX:
            ctl = f'<label><input type="checkbox" name="{fid}"{req}> {lab}</label>'
        elif f.type == FieldType.MULTIPLE_CHOICE:
            opts = "".join(f'<option>{html.escape(o)}</option>' for o in f.options) or "<option></option>"
            ctl = f'<label>{lab}<select name="{fid}"{req}>{opts}</select></label>'
        elif f.type == FieldType.SIGNATURE:
            ctl = f'<label>{lab}<div class="sig" data-name="{fid}">Sign here</div></label>'
        else:
            t = {FieldType.DATE: "date", FieldType.NUMBER: "number"}.get(f.type, "text")
            ctl = f'<label>{lab}<input type="{t}" name="{fid}" placeholder="{html.escape(f.placeholder)}"{req}></label>'
        rows.append(f'<div class="field" style="grid-column: span {max(1, min(f.w, layout.grid_columns))}">{ctl}</div>')
    return f"""<!doctype html>
<html><head><meta charset="utf-8"><title>{html.escape(layout.title)}</title>
<style>
body{{font-family:system-ui,sans-serif;max-width:900px;margin:2rem auto;padding:0 1rem}}
form{{display:grid;grid-template-columns:repeat({layout.grid_columns},1fr);gap:12px 16px}}
label{{display:flex;flex-direction:column;font-size:14px;gap:4px}}
input,select{{padding:6px 8px;border:1px solid #bbb;border-radius:4px;font-size:14px}}
.sig{{border:1px dashed #888;height:60px;display:flex;align-items:center;justify-content:center;color:#888}}
button{{grid-column:1/-1;padding:10px;font-size:15px}}
</style></head><body>
<h1>{html.escape(layout.title)}</h1>
<form>
{chr(10).join(rows)}
<button type="submit">Submit</button>
</form></body></html>"""


def to_pdf(layout: FormLayout) -> bytes:
    """Fillable AcroForm PDF via PyMuPDF widgets (PyPDF is used for verification only)."""
    import pymupdf as fitz

    doc = fitz.open()
    page = doc.new_page(width=PAGE_W, height=PAGE_H)
    page.insert_text((MARGIN, MARGIN + 10), layout.title, fontsize=16, fontname="helv")
    placed = _grid_to_page(layout)
    usable = PAGE_H - 2 * MARGIN - 40
    pages = [page]
    for f, x, y_top, w, h in placed:
        # Flow rows onto extra pages when the grid runs past the page bottom.
        page_idx = int((y_top - (MARGIN + 40)) // usable)
        while len(pages) <= page_idx:
            pages.append(doc.new_page(width=PAGE_W, height=PAGE_H))
        cur_page = pages[page_idx]
        y_top = y_top - page_idx * usable
        label = f.label + (" *" if f.required else "")
        cur_page.insert_text((x, y_top + LABEL_H - 2), label, fontsize=9, fontname="helv", color=(0.25, 0.25, 0.25))
        rect = fitz.Rect(x, y_top + LABEL_H + 2, x + w, y_top + h)
        widget = fitz.Widget()
        widget.field_name = f.field_id
        widget.rect = rect
        if f.type == FieldType.CHECKBOX:
            widget.field_type = fitz.PDF_WIDGET_TYPE_CHECKBOX
            widget.rect = fitz.Rect(x, y_top + LABEL_H + 2, x + 14, y_top + LABEL_H + 16)
            widget.field_value = f.value.lower() in ("yes", "true", "on", "x", "✓")
        elif f.type == FieldType.MULTIPLE_CHOICE:
            widget.field_type = fitz.PDF_WIDGET_TYPE_COMBOBOX
            widget.choice_values = f.options or ["—"]
            widget.field_value = f.value or (f.options[0] if f.options else "—")
        elif f.type == FieldType.SIGNATURE:
            widget.field_type = fitz.PDF_WIDGET_TYPE_TEXT
            widget.field_value = ""
            cur_page.draw_rect(rect, color=(0.5, 0.5, 0.5), dashes="[3 3] 0")
        else:
            widget.field_type = fitz.PDF_WIDGET_TYPE_TEXT
            widget.field_value = f.value
            if f.type == FieldType.NUMBER:
                widget.text_format = 1
        widget.border_color = (0.6, 0.6, 0.6)
        widget.fill_color = (0.97, 0.97, 1.0)
        widget.text_fontsize = 10
        cur_page.add_widget(widget)
    buf = io.BytesIO()
    doc.save(buf)
    doc.close()
    return buf.getvalue()


def pdf_field_names(pdf_bytes: bytes) -> list[str]:
    """Read AcroForm field names back with PyPDF (used in tests / verification)."""
    from pypdf import PdfReader

    reader = PdfReader(io.BytesIO(pdf_bytes))
    fields = reader.get_fields() or {}
    return sorted(fields.keys())


def export(layout: FormLayout, fmt: str) -> tuple[bytes, str, str]:
    """Return (content, media_type, filename)."""
    if fmt == "pdf":
        return to_pdf(layout), "application/pdf", "form.pdf"
    if fmt == "html":
        return to_html(layout).encode("utf-8"), "text/html; charset=utf-8", "form.html"
    if fmt == "json":
        return json.dumps(to_json_schema(layout), indent=2, ensure_ascii=False).encode("utf-8"), "application/json", "form.schema.json"
    raise ValueError(f"unknown export format: {fmt}")
