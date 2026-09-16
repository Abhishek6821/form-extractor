"""Phase 2 — text with word-level bounding boxes.

No OCR engines to install.  Three sources, tried in this order:

* ``pdftext`` — the PDF's own text layer (PyMuPDF). Exact boxes, free, no key.
* ``apple``   — macOS Vision framework (built into the OS, 30 languages).
                Used automatically on a Mac when the page has no text layer.
* ``gemini``  — Gemini reads the page image and returns text lines with boxes.
                Any language / script; needs the API key from the Settings page.

Every source yields ``Page`` objects with ``Token`` lists in page-pixel
coordinates, so the rest of the pipeline never knows where text came from.
"""
from __future__ import annotations

import re
import sys
import unicodedata
from typing import Iterable, Optional

from app.schemas import Page, Token
from app.pipeline.preprocess import PageImage


def detect_script(text: str) -> str:
    for ch in text:
        if not ch.isalpha():
            continue
        try:
            name = unicodedata.name(ch)
        except ValueError:
            continue
        for tag in ("DEVANAGARI", "ARABIC", "CJK", "HIRAGANA", "KATAKANA", "HANGUL", "CYRILLIC",
                    "BENGALI", "TAMIL", "TELUGU", "GUJARATI", "GURMUKHI", "KANNADA", "MALAYALAM",
                    "THAI", "HEBREW", "GREEK"):
            if tag in name:
                return tag.lower()
        return "latin"
    return "unknown"


_GLUED_RE = re.compile(r"^(.*?[^\s_.\-–—…])([_\.\-–—…]{3,})$")


_BOX_LOOKALIKES = {"•", "▪", "◦", "口", "▫", "☐", "◻", "□"}


def _fix_ocr_boxes(t: Token) -> list[Token]:
    """OCR engines often read checkboxes as bullets or the CJK '口' glyph."""
    txt = t.text
    if txt in _BOX_LOOKALIKES:
        return [Token(text="☐", bbox=t.bbox, confidence=t.confidence, page=t.page, script="unknown")]
    if txt.count("口") >= 2 or (txt.count("口") == 1 and ("：" in txt or ":" in txt)):
        # "性别:口男口女口其他" -> "性别: ☐ 男 ☐ 女 ☐ 其他"
        fixed = txt.replace("口", " ☐ ").replace("：", ": ").replace(":", ": ")
        return split_line_into_words(" ".join(fixed.split()), list(t.bbox), t.confidence, t.page)
    return [t]


def normalize_tokens(tokens: list[Token]) -> list[Token]:
    """Split ``Address________`` into a label token and a blank token, fix box glyphs."""
    out: list[Token] = []
    for raw in tokens:
        for t in _fix_ocr_boxes(raw):
            out.extend(_split_glued(t))
    return out


def _split_glued(t: Token) -> list[Token]:
    out: list[Token] = []
    for t in [t]:
        m = _GLUED_RE.match(t.text)
        if not m:
            out.append(t)
            continue
        label, blank = m.group(1), m.group(2)
        frac = len(label) / max(len(t.text), 1)
        x, y, w, h = t.bbox
        lw = w * frac
        out.append(Token(text=label, bbox=[x, y, lw, h], confidence=t.confidence, page=t.page, script=detect_script(label)))
        out.append(Token(text=blank, bbox=[x + lw, y, w - lw, h], confidence=t.confidence, page=t.page, script="unknown"))
    return out


def split_line_into_words(text: str, bbox: list[float], conf: float, page_no: int) -> list[Token]:
    """Split a line-level box into word boxes proportionally by character count."""
    words = text.split()
    if not words:
        return []
    x, y, w, h = bbox
    total_chars = sum(len(t) for t in words) + max(0, len(words) - 1)
    cursor = x
    out = []
    for wd in words:
        frac = len(wd) / total_chars if total_chars else 1.0
        ww = w * frac
        out.append(Token(text=wd, bbox=[cursor, y, ww, h], confidence=conf, page=page_no, script=detect_script(wd)))
        cursor += ww + (w / total_chars if total_chars else 0)
    return out


# ------------------------------------------------------------------ sources


def ocr_pdftext(page: PageImage) -> Optional[list[Token]]:
    """Read the vector text layer of a PDF page; None when the page has none."""
    if not page.pdf_path:
        return None
    import pymupdf as fitz

    doc = fitz.open(page.pdf_path)
    try:
        words = doc[page.number - 1].get_text("words")
    finally:
        doc.close()
    if not words:
        return None
    s = page.scale
    return [Token(text=w.strip(), bbox=[x0 * s, y0 * s, (x1 - x0) * s, (y1 - y0) * s], confidence=1.0,
                  page=page.number, script=detect_script(w)) for x0, y0, x1, y1, w, *_ in words if w.strip()]


def apple_vision_available() -> bool:
    if sys.platform != "darwin":
        return False
    try:
        import Vision  # noqa: F401

        return True
    except Exception:
        return False


def ocr_apple(page: PageImage) -> list[Token]:
    """macOS Vision text recognition (no key, no install)."""
    import Quartz
    import Vision
    from Foundation import NSData

    import cv2

    ok, png = cv2.imencode(".png", page.source)
    data = NSData.dataWithBytes_length_(png.tobytes(), len(png))
    handler = Vision.VNImageRequestHandler.alloc().initWithData_options_(data, None)
    req = Vision.VNRecognizeTextRequest.alloc().init()
    req.setRecognitionLevel_(Vision.VNRequestTextRecognitionLevelAccurate)
    req.setUsesLanguageCorrection_(False)  # keep labels like "DOB" and "____" verbatim
    langs, _ = req.supportedRecognitionLanguagesAndReturnError_(None)
    req.setRecognitionLanguages_(list(langs))
    req.setAutomaticallyDetectsLanguage_(True)
    handler.performRequests_error_([req], None)
    H, W = page.source.shape[:2]
    toks: list[Token] = []
    for obs in req.results() or []:
        cand = obs.topCandidates_(1)
        if not cand:
            continue
        text = cand[0].string()
        conf = float(cand[0].confidence())
        b = obs.boundingBox()  # normalised, origin bottom-left
        x, w = b.origin.x * W, b.size.width * W
        y, h = (1 - b.origin.y - b.size.height) * H, b.size.height * H
        toks.extend(split_line_into_words(text, [x, y, w, h], conf, page.number))
    return toks


def ocr_gemini(page: PageImage) -> list[Token]:
    from app.pipeline.llm import read_page_image

    H, W = page.source.shape[:2]
    lines = read_page_image(page.source)
    toks: list[Token] = []
    for ln in lines:
        x, y, w, h = ln["bbox"]
        toks.extend(split_line_into_words(ln["text"], [x * W, y * H, w * W, h * H], 0.9, page.number))
    return toks


# ------------------------------------------------------------------ driver


def available_backends() -> list[str]:
    from app import settings

    out = ["pdftext"]
    if apple_vision_available():
        out.append("apple")
    if settings.vision_ocr_enabled():
        out.append("gemini")
    return out


def run_ocr(pages: Iterable[PageImage], backend: str = "auto") -> list[Page]:
    avail = available_backends()
    out: list[Page] = []
    for p in pages:
        tokens: Optional[list[Token]] = None
        if backend in ("auto", "pdftext"):
            tokens = ocr_pdftext(p)
        if tokens is None and backend in ("auto", "apple") and "apple" in avail:
            tokens = ocr_apple(p)
            if backend == "auto" and len(tokens) < 3:
                tokens = None  # Vision found nothing useful (e.g. unsupported script) -> try Gemini
        if tokens is None and backend in ("auto", "gemini"):
            if "gemini" in avail:
                tokens = ocr_gemini(p)
            else:
                raise RuntimeError(
                    "This page is a scanned image with no text layer. Open Settings, add your Gemini API key "
                    "and enable it so Gemini can read the image.")
        if tokens is None:
            tokens = []
        out.append(Page(number=p.number, width=p.width, height=p.height, tokens=normalize_tokens(tokens), lines=p.lines))
    return out


def page_from_tokens(tokens: list[dict], width: float, height: float, number: int = 1,
                     lines: Optional[list[list[float]]] = None) -> Page:
    toks = [Token(**t, script=detect_script(t["text"])) if "script" not in t else Token(**t) for t in tokens]
    for t in toks:
        t.page = number
    return Page(number=number, width=width, height=height, tokens=normalize_tokens(toks), lines=lines or [])
