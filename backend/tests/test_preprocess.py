import os

import numpy as np
import pytest

from app.pipeline import ocr as ocr_mod
from app.pipeline import preprocess
from tests.conftest import FIXTURES


def test_render_and_clean_pdf():
    pages = preprocess.preprocess_file(os.path.join(FIXTURES, "forms", "en_job_application.pdf"))
    assert len(pages) == 1
    p = pages[0]
    assert p.width > 1500 and p.height > 2200  # >= 200 DPI A4
    assert p.image.dtype == np.uint8 and set(np.unique(p.image)) <= {0, 255}
    assert len(p.lines) >= 5  # underlines were detected
    assert abs(p.skew_deg) < 0.5


def test_deskew_recovers_rotation(tmp_path):
    import cv2
    import pymupdf as fitz

    pdf = os.path.join(FIXTURES, "forms", "en_invoice.pdf")
    doc = fitz.open(pdf)
    pix = doc[0].get_pixmap(matrix=fitz.Matrix(2, 2), colorspace="gray")
    img = np.frombuffer(pix.samples, dtype=np.uint8).reshape(pix.height, pix.width)
    h, w = img.shape
    m = cv2.getRotationMatrix2D((w / 2, h / 2), 3.0, 1.0)
    rotated = cv2.warpAffine(img, m, (w, h), borderValue=255)
    out = str(tmp_path / "rot.png")
    cv2.imwrite(out, rotated)
    angle = preprocess.estimate_skew(rotated)
    assert 2.0 < abs(angle) < 4.0
    fixed = preprocess.deskew(rotated, angle)
    assert abs(preprocess.estimate_skew(fixed)) < 0.7


def _scan_image(tmp_path):
    import cv2

    img = np.full((500, 900), 255, dtype=np.uint8)
    cv2.putText(img, "Full Name: ____________", (30, 100), cv2.FONT_HERSHEY_SIMPLEX, 1.2, 0, 2)
    cv2.putText(img, "Date of Birth: ________", (30, 200), cv2.FONT_HERSHEY_SIMPLEX, 1.2, 0, 2)
    cv2.putText(img, "Email: ________________", (30, 300), cv2.FONT_HERSHEY_SIMPLEX, 1.2, 0, 2)
    cv2.putText(img, "Signature ____________", (30, 400), cv2.FONT_HERSHEY_SIMPLEX, 1.2, 0, 2)
    path = str(tmp_path / "scan.png")
    cv2.imwrite(path, img)
    return path


def test_scanned_image_without_key_gives_settings_hint(tmp_path, monkeypatch):
    from app.pipeline import ocr, pipeline

    monkeypatch.setattr(ocr, "apple_vision_available", lambda: False)
    res = pipeline.run_on_file(_scan_image(tmp_path), "d1", "scan.png", use_llm=False)
    assert res.status == "error" and "Settings" in (res.error or "")


@pytest.mark.skipif(not ocr_mod.apple_vision_available(), reason="macOS Vision only")
def test_scanned_image_is_read_by_apple_vision(tmp_path):
    from app.pipeline import pipeline

    res = pipeline.run_on_file(_scan_image(tmp_path), "d1", "scan.png", use_llm=False)
    assert res.status == "done", res.error
    labels = {f.label for f in res.fields}
    assert {"Full Name", "Date of Birth", "Email", "Signature"} <= labels


def test_llm_vision_backend_maps_boxes(tmp_path, monkeypatch):
    from app.pipeline import llm, ocr, pipeline

    monkeypatch.setattr(ocr, "apple_vision_available", lambda: False)
    monkeypatch.setattr(ocr, "available_backends", lambda: ["pdftext", "llm"])
    monkeypatch.setattr(llm, "read_page_image", lambda gray, provider=None: [
        {"text": "Full Name: ______", "bbox": [0.03, 0.15, 0.5, 0.06]},
        {"text": "Email: ______", "bbox": [0.03, 0.55, 0.4, 0.06]},
    ])
    res = pipeline.run_on_file(_scan_image(tmp_path), "d1", "scan.png", use_llm=False)
    assert res.status == "done", res.error
    assert {f.label for f in res.fields} >= {"Full Name", "Email"}
