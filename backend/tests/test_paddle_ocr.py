import numpy as np

from app.pipeline import ocr
from app.pipeline.preprocess import PageImage

BLOCKS = [
    {"block_label": "doc_title", "block_content": "APPLICATION FORM", "block_bbox": [100, 20, 400, 50], "block_id": 0},
    {"block_label": "text", "block_content": "Full Name: ______\nDate of Birth: ______", "block_bbox": [50, 100, 550, 160]},
    {"block_label": "image", "block_content": "", "block_bbox": [0, 0, 10, 10]},
    {"block_label": "table", "block_content": "<table><tr><td>Qty:</td><td>2</td></tr></table>", "block_bbox": [50, 200, 300, 230]},
    {"block_label": "text", "block_content": "   ", "block_bbox": [0, 0, 5, 5]},
]


def test_blocks_to_tokens_splits_lines_and_words():
    toks = ocr.paddle_blocks_to_tokens(BLOCKS, page_no=1)
    texts = [t.text for t in toks]
    assert "APPLICATION" in texts and "Full" in texts and "Birth:" in texts and "Qty:" in texts
    assert not any("<" in t for t in texts)
    full = next(t for t in toks if t.text == "Full")
    birth = next(t for t in toks if t.text == "Birth:")
    assert full.bbox[1] < birth.bbox[1]  # second line sits below the first
    assert abs((full.bbox[3] + birth.bbox[3]) - 60) < 1e-6  # lines share the block height


def test_server_backend_parses_layout_parsing_response(monkeypatch):
    import httpx

    from app import settings

    posted = {}

    class R:
        status_code = 200

        def raise_for_status(self):
            pass

        def json(self):
            return {"result": {"layoutParsingResults": [{"prunedResult": {"parsing_res_list": BLOCKS}}]}}

    def fake_post(url, json, timeout):
        posted["url"] = url
        posted["fileType"] = json["fileType"]
        return R()

    monkeypatch.setattr(httpx, "post", fake_post)
    monkeypatch.setattr(settings, "paddle_server_url", lambda: "http://ocr.local:8080")
    page = PageImage(1, np.full((300, 600), 255, np.uint8), 600, 300, source=np.full((300, 600), 255, np.uint8))
    toks = ocr.ocr_paddle(page)
    assert posted["url"] == "http://ocr.local:8080/layout-parsing" and posted["fileType"] == 1
    assert any(t.text == "Name:" for t in toks)


def test_paddle_selected_in_auto_order(monkeypatch):
    from app import settings

    monkeypatch.setattr(settings, "paddle_server_url", lambda: "http://ocr.local:8080")
    monkeypatch.setattr(ocr, "apple_vision_available", lambda: True)
    assert ocr.available_backends()[:2] == ["pdftext", "paddle"]


def test_run_ocr_explicit_backend_error_message(monkeypatch):
    from app import settings

    monkeypatch.setattr(settings, "paddle_server_url", lambda: "")
    monkeypatch.setattr(ocr, "paddle_local_available", lambda: False)
    page = PageImage(1, np.full((30, 60), 255, np.uint8), 60, 30, source=np.full((30, 60), 255, np.uint8))
    try:
        ocr.run_ocr([page], backend="paddle")
        assert False, "expected an error"
    except RuntimeError as e:
        assert "PaddleOCR-VL" in str(e)
