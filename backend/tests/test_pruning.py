from app.pipeline import grouping, pruning
from app.schemas import FieldType


def test_pruning_drops_title_and_page_number(form_page):
    cands, _ = grouping.group_page(form_page, restarts=4)
    qa, stats = pruning.build_qa_document([form_page], {1: cands}, form_confidence=0.9, restarts=4)
    labels = [f.original_label for f in qa.fields]
    assert not any("APPLICATION" in l or "Page" in l for l in labels)
    assert qa.junk_candidates_removed >= 1
    assert "Full Name:" in labels and "Date of Birth:" in labels and "Signature" in labels


def test_qa_document_shape(form_page):
    cands, _ = grouping.group_page(form_page, restarts=4)
    qa, _ = pruning.build_qa_document([form_page], {1: cands}, form_confidence=0.9, restarts=4)
    assert qa.document_type == "form" and qa.form_confidence == 0.9
    ids = [f.field_id for f in qa.fields]
    assert ids == sorted(ids) and ids[0] == "f_001"
    dob = next(f for f in qa.fields if f.original_label == "Date of Birth:")
    assert dob.question == "What is the applicant's date of birth?"
    assert dob.expected_answer_type == FieldType.DATE
    assert len(dob.bbox) == 4 and dob.grouping_score > 0
    gender = next(f for f in qa.fields if f.original_label == "Gender:")
    assert gender.expected_answer_type == FieldType.MULTIPLE_CHOICE
    assert gender.options == ["Male", "Female"]


def test_pruning_never_keeps_empty_set(prose_page):
    cands, _ = grouping.group_page(prose_page, restarts=3)
    fields, removed, _ = pruning.prune_candidates(cands, prose_page, restarts=3)
    # prose should mostly be pruned away
    assert removed >= len(cands) * 0.5
