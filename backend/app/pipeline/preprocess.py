"""Phase 1 — Preprocessing.

PDF -> page images at a fixed DPI (PyMuPDF), then OpenCV cleanup: deskew via
Hough transform, adaptive thresholding and denoising.  Also detects long
horizontal/vertical rule lines, which the form gate and grouping pass use as
structural signals.

All heavy imports are lazy so the pure-Python parts of the pipeline (and the
tests) work without OpenCV / PyMuPDF installed.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

DPI = int(__import__('os').environ.get('FORM_DPI', '220'))
# Everything PyMuPDF can open. "Document" formats keep a text layer; images are rasters.
DOC_EXT = {".pdf", ".xps", ".oxps", ".epub", ".mobi", ".fb2", ".cbz", ".svg", ".txt"}
IMAGE_EXT = {".png", ".jpg", ".jpeg", ".jp2", ".tif", ".tiff", ".bmp", ".gif", ".pnm", ".pgm", ".ppm", ".pam", ".webp"}
PDF_EXT = DOC_EXT  # backwards-compatible name
SUPPORTED_EXT = DOC_EXT | IMAGE_EXT


@dataclass
class PageImage:
    number: int
    image: "object"  # numpy array (H, W) uint8 binarised (text = 0)
    width: int
    height: int
    source: "object" = None  # deskewed grayscale page, fed to image-reading backends
    skew_deg: float = 0.0
    lines: list[list[float]] = field(default_factory=list)  # [x, y, w, h]
    # Kept so the digital-text OCR backend can read the vector text layer.
    pdf_path: Optional[str] = None
    scale: float = 1.0  # pixels per PDF point


def render_pages(path: str | Path, dpi: int = DPI, max_pages: int = 20) -> list[PageImage]:
    """Render a PDF or load an image into grayscale page images."""
    import numpy as np

    path = Path(path)
    ext = path.suffix.lower()
    pages: list[PageImage] = []
    if ext in DOC_EXT:
        import pymupdf as fitz

        try:
            doc = fitz.open(str(path))
        except Exception as e:
            raise ValueError(f"Could not open {ext} file: {e}") from e
        scale = dpi / 72.0
        for i, page in enumerate(doc):
            if i >= max_pages:
                break
            pix = page.get_pixmap(matrix=fitz.Matrix(scale, scale), colorspace="gray")
            arr = np.frombuffer(pix.samples, dtype=np.uint8).reshape(pix.height, pix.width)
            pages.append(PageImage(i + 1, arr.copy(), pix.width, pix.height, pdf_path=str(path), scale=scale))
        doc.close()
    elif ext in IMAGE_EXT:
        import cv2

        img = cv2.imread(str(path), cv2.IMREAD_GRAYSCALE)
        if img is None:  # formats OpenCV can't decode (gif, pnm variants...) -> PyMuPDF
            import pymupdf as fitz

            try:
                pix = fitz.Pixmap(str(path))
                if pix.n > 1:
                    pix = fitz.Pixmap(fitz.csGRAY, pix)
                img = np.frombuffer(pix.samples, dtype=np.uint8).reshape(pix.height, pix.width).copy()
            except Exception as e:
                raise ValueError(f"Could not decode image: {path.name} ({e})") from e
        pages.append(PageImage(1, img, img.shape[1], img.shape[0]))
    else:
        raise ValueError(f"Unsupported file type: {ext}")
    if not pages:
        raise ValueError("The file has no pages")
    return pages


def estimate_skew(gray) -> float:
    """Estimate page skew (degrees) with a probabilistic Hough transform."""
    import cv2
    import numpy as np

    edges = cv2.Canny(gray, 50, 150, apertureSize=3)
    min_len = max(50, gray.shape[1] // 8)
    lines = cv2.HoughLinesP(edges, 1, np.pi / 360, threshold=120, minLineLength=min_len, maxLineGap=10)
    if lines is None:
        return 0.0
    angles = []
    for x1, y1, x2, y2 in lines.reshape(-1, 4):
        ang = math.degrees(math.atan2(y2 - y1, x2 - x1))
        if abs(ang) < 15:  # near-horizontal lines only
            angles.append(ang)
    if not angles:
        return 0.0
    return float(np.median(angles))


def deskew(gray, angle: float):
    import cv2

    if abs(angle) < 0.1:
        return gray
    h, w = gray.shape[:2]
    m = cv2.getRotationMatrix2D((w / 2, h / 2), angle, 1.0)
    return cv2.warpAffine(gray, m, (w, h), flags=cv2.INTER_LINEAR, borderMode=cv2.BORDER_REPLICATE)


def clean(gray):
    """Denoise + adaptive threshold. Returns a binarised uint8 image (text = 0)."""
    import cv2

    den = cv2.medianBlur(gray, 3)  # fast salt-and-pepper removal; NL-means is ~50x slower at 300 DPI
    binar = cv2.adaptiveThreshold(den, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C, cv2.THRESH_BINARY, 31, 15)
    return binar


def detect_rule_lines(binar, min_frac: float = 0.15) -> list[list[float]]:
    """Find long horizontal and vertical lines using morphological opening."""
    import cv2

    h, w = binar.shape[:2]
    inv = 255 - binar
    out: list[list[float]] = []
    for horiz in (True, False):
        length = int((w if horiz else h) * min_frac)
        if length < 10:
            continue
        kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (length, 1) if horiz else (1, length))
        opened = cv2.morphologyEx(inv, cv2.MORPH_OPEN, kernel)
        contours, _ = cv2.findContours(opened, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        for c in contours:
            x, y, cw, ch = cv2.boundingRect(c)
            out.append([float(x), float(y), float(cw), float(ch)])
    return out


def preprocess_file(path: str | Path, dpi: int = DPI, do_deskew: bool = True) -> list[PageImage]:
    pages = render_pages(path, dpi=dpi)
    for p in pages:
        angle = estimate_skew(p.image) if do_deskew else 0.0
        p.skew_deg = angle
        img = deskew(p.image, angle)
        binar = clean(img)
        p.lines = detect_rule_lines(binar)
        p.source = img
        p.image = binar
    return pages
