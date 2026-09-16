import json

from app.pipeline import llm
from app.schemas import FieldType, QADocument, QAField


def make_qa():
    return QADocument(form_confidence=0.9, fields=[
        QAField(field_id="f_001", question="What is the applicant's full name?", original_label="नाम:",
                expected_answer_type=FieldType.TEXT, bbox=[0, 0, 10, 10], grouping_score=0.9),
        QAField(field_id="f_002", question="What is the applicant's date of birth?", original_label="DOB:",
                expected_answer_type=FieldType.DATE, bbox=[0, 20, 10, 10], grouping_score=0.9, detected_value="14/03/1990"),
    ])


def test_prompt_is_bounded_by_field_count():
    qa = make_qa()
    prompt = llm.build_prompt(qa)
    assert prompt.count("\n") == len(qa.fields)
    assert "f_001 | नाम: | What is the applicant's full name? | text |" in prompt


def test_passthrough_without_llm():
    fields, info = llm.extract_with_llm(make_qa(), use_llm=False)
    assert info["llm_used"] is False
    assert [f.field_id for f in fields] == ["f_001", "f_002"]
    assert fields[0].label == "Full Name" and fields[0].label_original_language == "नाम:"
    assert fields[1].value == "14/03/1990"


def test_merge_handles_dropped_and_unknown_ids():
    qa = make_qa()
    data = {"fields": [
        {"id": "f_002", "label": "Date of Birth", "question": "What is the date of birth?", "type": "date",
         "value": "1990-03-14", "options": [], "confidence": 0.95, "needs_review": False},
        {"id": "f_999", "label": "junk", "question": "?", "type": "text", "value": "", "options": [], "confidence": 1, "needs_review": False},
    ]}
    fields = llm._merge(qa, data)
    assert [f.field_id for f in fields] == ["f_001", "f_002"]
    assert fields[1].value == "1990-03-14" and fields[1].confidence == 0.95
    assert fields[0].needs_review is True  # dropped by the model -> flagged


class FakeProvider:
    name = "fake"
    model = "fake-model"

    def __init__(self, payload):
        self.payload = payload
        self.calls = []

    def complete_json(self, system, text, schema, image_png=None, max_tokens=8000):
        from app.providers import Usage

        self.calls.append({"system": system, "text": text, "schema": schema, "image": image_png})
        return self.payload, Usage(120, 80, self.model, self.name)

    def test_connection(self):
        return {"ok": True, "model": self.model}


def test_single_call_with_fake_provider():
    prov = FakeProvider({"fields": [
        {"id": "f_001", "label": "Full Name", "question": "What is your full name?", "type": "text", "value": "",
         "options": [], "confidence": 0.9, "needs_review": False},
        {"id": "f_002", "label": "Date of Birth", "question": "What is your date of birth?", "type": "date",
         "value": "1990-03-14", "options": [], "confidence": 0.9, "needs_review": False}]})
    fields, info = llm.extract_with_llm(make_qa(), use_llm=True, provider=prov)
    assert len(prov.calls) == 1  # exactly one batched call per document
    assert prov.calls[0]["schema"] is llm.OUTPUT_SCHEMA and prov.calls[0]["image"] is None
    assert info["llm_used"] and info["input_tokens"] == 120 and info["provider"] == "fake"
    assert fields[1].value == "1990-03-14"


def test_vision_ocr_uses_image_and_clamps_boxes():
    import numpy as np

    prov = FakeProvider({"is_form": True, "form_confidence": 0.9, "lines": [{"text": "Name: ____", "bbox": [0.1, 0.2, 0.5, 0.05]},
                                   {"text": "bad", "bbox": [0, 0, 0, 0]}, {"text": "", "bbox": [0.1, 0.1, 0.1, 0.1]},
                                   {"text": "Over", "bbox": [0.9, 0.9, 1.5, 0.05]}]})
    gray = np.full((200, 300), 255, dtype=np.uint8)
    lines = llm.read_page_image(gray, provider=prov)
    assert prov.calls[0]["image"][:4] == b"\x89PNG"
    assert [l["text"] for l in lines] == ["Name: ____", "Over"]
    assert lines[1]["bbox"][2] == 1.0
    assert llm.LAST_VISION_VERDICT[id(gray)] == (True, 0.9)  # verdict cached for the gate


def test_blank_confident_field_is_not_flagged_for_review():
    qa = make_qa()
    data = {"fields": [
        {"id": "f_001", "label": "Full Name", "question": "q", "type": "text", "value": "", "options": [], "confidence": 0.95, "needs_review": True},
        {"id": "f_002", "label": "DOB", "question": "q", "type": "date", "value": "maybe 1990", "options": [], "confidence": 0.95, "needs_review": True},
    ]}
    fields = llm._merge(qa, data)
    assert fields[0].needs_review is False  # blank + confident
    assert fields[1].needs_review is True   # present but ambiguous value
