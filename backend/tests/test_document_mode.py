from app.pipeline import document, pipeline
from app.schemas import FieldType, Page, Token
from tests.conftest import make_prose_page, tok


def receipt_page():
    lines = ["GREENLEAF GROCERY", "Invoice No: INV-2024-0117", "Date: 14/03/2024", "Contact: +91 98765 43210",
             "Email: shop@greenleaf.example", "Total: ₹ 1,250.00", "www.greenleaf.example"]
    toks = []
    for i, ln in enumerate(lines):
        x = 40
        for w in ln.split():
            toks.append(tok(w, x, 60 + i * 30))
            x += 6 * len(w) + 8
    return Page(number=1, width=600, height=850, tokens=toks)


def test_heuristic_facts_without_llm():
    info, fields = document._heuristic([receipt_page()])
    labels = {f.label: f.value for f in fields}
    assert info.title == "GREENLEAF GROCERY" and "Total" in info.full_text
    assert labels["Date"] == "14/03/2024" and labels["Email"] == "shop@greenleaf.example"
    assert labels["Reference Number"] == "INV-2024-0117" and labels["Amount"].endswith("1,250.00")
    assert labels["Website"].startswith("www.")
    assert all(f.field_id.startswith("d_") for f in fields)


def test_pipeline_does_not_reject_prose():
    res = pipeline.run_on_pages([make_prose_page()], "d", "essay.pdf", use_llm=False)
    assert res.status == "done" and res.is_form is False and res.qa is None
    assert res.info is not None and "libraries" in res.info.full_text


def test_document_mode_with_fake_provider():
    class Prov:
        name, model = "fake", "m"

        def complete_json(self, system, text, schema, image_png=None, max_tokens=8000):
            from app.providers import Usage

            assert "OCR text" in text and image_png == b"png"
            return {"document_type": "receipt", "title": "Greenleaf", "language": "en", "summary": "A grocery receipt.",
                    "full_text": "GREENLEAF GROCERY ...", "facts": [
                        {"label": "Total", "value": "1,250.00", "type": "number", "confidence": 0.95},
                        {"label": "Date", "value": "2024-03-14", "type": "date", "confidence": 0.9},
                        {"label": "", "value": "x", "type": "text", "confidence": 0.9}]}, Usage(10, 5, "m", "fake")

    info, fields, usage = document.extract_document([receipt_page()], images=[b"png"], provider=Prov(), use_llm=True)
    assert info.document_type == "receipt" and info.summary and usage["llm_used"]
    assert [(f.label, f.type) for f in fields] == [("Total", FieldType.NUMBER), ("Date", FieldType.DATE)]
    assert fields[0].value == "1,250.00"  # normalisation happens in the pipeline
