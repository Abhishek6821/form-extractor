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


def test_single_call_with_fake_client(monkeypatch):
    import anthropic

    calls = []

    class FakeUsage:
        input_tokens, output_tokens = 120, 80

    class FakeBlock:
        type = "text"

        def __init__(self, text):
            self.text = text

    class FakeResp:
        stop_reason = "end_turn"
        usage = FakeUsage()

        def __init__(self, text):
            self.content = [FakeBlock(text)]

    class FakeMessages:
        def create(self, **kw):
            calls.append(kw)
            return FakeResp(json.dumps({"fields": [
                {"id": "f_001", "label": "Full Name", "question": "What is your full name?", "type": "text", "value": "",
                 "options": [], "confidence": 0.9, "needs_review": False},
                {"id": "f_002", "label": "Date of Birth", "question": "What is your date of birth?", "type": "date",
                 "value": "1990-03-14", "options": [], "confidence": 0.9, "needs_review": False}]}))

    class FakeClient:
        def __init__(self, *a, **k):
            self.messages = FakeMessages()

    monkeypatch.setattr(llm, "get_client", lambda: FakeClient())
    fields, info = llm.extract_with_llm(make_qa(), use_llm=True)
    assert len(calls) == 1  # exactly one batched call per document
    assert calls[0]["model"] == "claude-opus-5"
    assert calls[0]["output_config"]["format"]["type"] == "json_schema"
    assert info["llm_used"] and info["input_tokens"] == 120
    assert fields[1].value == "1990-03-14"
