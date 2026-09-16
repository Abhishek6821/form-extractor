"""Phase 2 — text with word-level bounding boxes.

No OCR engines to install.  Three sources, tried in this order:

* ``pdftext`` — the PDF's own text layer (PyMuPDF). Exact boxes, free, no key.
* ``apple``   — macOS Vision framework (built into the OS, 30 languages).
                Used automatically on a Mac when the page has no text layer.
* ``paddle``  — PaddleOCR-VL (0.9B vision-language OCR, 109 languages): either
                the local ``paddleocr`` package or a remote service started with
                ``paddlex --serve --pipeline PaddleOCR-VL`` (URL in Settings).
* ``llm``     — the configured LLM provider (Claude / Gemini) reads the page
                image and returns text lines with boxes. Any language / script.

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


def ocr_llm(page: PageImage) -> list[Token]:
    from app.pipeline.llm import read_page_image

    H, W = page.source.shape[:2]
    toks: list[Token] = []
    for ln in read_page_image(page.source):
        x, y, w, h = ln["bbox"]
        toks.extend(split_line_into_words(ln["text"], [x * W, y * H, w * W, h * H], 0.9, page.number))
    return toks


# ------------------------------------------------------------ PaddleOCR-VL


def paddle_local_available() -> bool:
    try:
        import importlib.util

        return importlib.util.find_spec("paddleocr") is not None and importlib.util.find_spec("paddle") is not None
    except Exception:
        return False


def paddle_available() -> bool:
    from app import settings

    return paddle_local_available() or bool(settings.paddle_server_url())


_PADDLE_PIPELINE = None


def _paddle_pipeline():
    global _PADDLE_PIPELINE
    if _PADDLE_PIPELINE is None:
        from paddleocr import PaddleOCRVL

        _PADDLE_PIPELINE = PaddleOCRVL()
    return _PADDLE_PIPELINE


def paddle_blocks_to_tokens(blocks: list[dict], page_no: int) -> list[Token]:
    """Convert PaddleOCR-VL ``parsing_res_list`` blocks (pixel [x1,y1,x2,y2]) into word tokens.

    A block is a layout region and may hold several lines; lines get an equal
    share of the block height, words a proportional share of the width.
    """
    toks: list[Token] = []
    for b in blocks:
        label = str(b.get("block_label", "text"))
        if label in ("image", "chart", "seal", "figure"):
            continue
        content = str(b.get("block_content", "") or "")
        bbox = b.get("block_bbox")
        if not content.strip() or not bbox or len(bbox) != 4:
            continue
        x1, y1, x2, y2 = (float(v) for v in bbox)
        if label == "table":
            content = re.sub(r"<[^>]+>", " ", content)  # tables come as HTML
        lines = [ln for ln in re.split(r"\r?\n|<br\s*/?>", content) if ln.strip()]
        if not lines:
            continue
        lh = (y2 - y1) / len(lines)
        for i, ln in enumerate(lines):
            ln = ln.replace("$", "").strip()  # PaddleOCR-VL wraps formulas in $
            toks.extend(split_line_into_words(ln, [x1, y1 + i * lh, x2 - x1, lh], 0.95, page_no))
    return toks


def ocr_paddle(page: PageImage) -> list[Token]:
    from app import settings

    url = settings.paddle_server_url()
    if url:
        return _ocr_paddle_server(page, url)
    if paddle_local_available():
        return _ocr_paddle_local(page)
    raise RuntimeError("PaddleOCR-VL is not available: install `paddleocr[doc-parser]` + `paddlepaddle`, "
                       "or set the PaddleOCR-VL server URL in Settings.")


def _ocr_paddle_local(page: PageImage) -> list[Token]:
    import cv2

    rgb = cv2.cvtColor(page.source, cv2.COLOR_GRAY2BGR)
    blocks: list[dict] = []
    for res in _paddle_pipeline().predict(rgb):
        data = res.json if isinstance(res.json, dict) else {}
        data = data.get("res", data)
        for blk in data.get("parsing_res_list", []) or []:
            bb = blk.get("block_bbox")
            if hasattr(bb, "tolist"):
                blk = dict(blk, block_bbox=bb.tolist())
            blocks.append(blk)
    return paddle_blocks_to_tokens(blocks, page.number)


def _ocr_paddle_server(page: PageImage, url: str) -> list[Token]:
    import base64

    import cv2
    import httpx

    ok, png = cv2.imencode(".png", page.source)
    payload = {"file": base64.b64encode(png.tobytes()).decode("ascii"), "fileType": 1}
    try:
        r = httpx.post(url.rstrip("/") + "/layout-parsing", json=payload, timeout=300)
        r.raise_for_status()
    except httpx.HTTPError as e:
        raise RuntimeError(f"PaddleOCR-VL server error: {e}") from e
    result = r.json().get("result", {})
    blocks: list[dict] = []
    for res in result.get("layoutParsingResults", []):
        blocks.extend((res.get("prunedResult") or {}).get("parsing_res_list", []) or [])
    return paddle_blocks_to_tokens(blocks, page.number)


# ------------------------------------------------------------------ driver


def available_backends() -> list[str]:
    from app import settings

    out = ["pdftext"]
    if paddle_available():
        out.append("paddle")
    if apple_vision_available():
        out.append("apple")
    if settings.vision_ocr_enabled():
        out.append("llm")
    return out


READERS = {"apple": ocr_apple, "paddle": ocr_paddle, "llm": ocr_llm}


def run_ocr(pages: Iterable[PageImage], backend: str = "auto") -> list[Page]:
    """``backend``: auto | pdftext | apple | paddle | llm. ``auto`` also honours the Settings choice."""
    from app import settings

    if backend == "auto":
        backend = settings.load().ocr_backend
    avail = available_backends()
    out: list[Page] = []
    for p in pages:
        tokens: Optional[list[Token]] = None
        if backend in ("auto", "pdftext"):
            tokens = ocr_pdftext(p)
        if tokens is None:
            if backend == "auto":
                order = [b for b in ("paddle", "apple", "llm") if b in avail]
            elif backend == "pdftext":
                order = []
            else:
                order = [backend]
            for name in order:
                if name not in avail and backend == "auto":
                    continue
                got = READERS[name](p)
                if backend == "auto" and name == "apple" and len(got) < 3:
                    continue  # Vision found nothing useful (unsupported script) -> next reader
                tokens = got
                break
        if tokens is None:
            raise RuntimeError(
                "This page is a scanned image with no text layer and no reader is available. Open Settings and "
                "either add an LLM API key (Claude/Gemini) or configure PaddleOCR-VL.")
        out.append(Page(number=p.number, width=p.width, height=p.height, tokens=normalize_tokens(tokens), lines=p.lines))
    return out


def page_from_tokens(tokens: list[dict], width: float, height: float, number: int = 1,
                     lines: Optional[list[list[float]]] = None) -> Page:
    toks = [Token(**t, script=detect_script(t["text"])) if "script" not in t else Token(**t) for t in tokens]
    for t in toks:
        t.page = number
    return Page(number=number, width=width, height=height, tokens=normalize_tokens(toks), lines=lines or [])
