import pytest

from app.pipeline.templates import match_template, normalize_label, synthesize_question
from app.schemas import FieldType


@pytest.mark.parametrize("label,key,ftype", [
    ("Date of Birth:", "date_of_birth", FieldType.DATE),
    ("DOB", "date_of_birth", FieldType.DATE),
    ("जन्म तिथि", "date_of_birth", FieldType.DATE),
    ("Fecha de nacimiento", "date_of_birth", FieldType.DATE),
    ("出生日期", "date_of_birth", FieldType.DATE),
    ("تاريخ الميلاد", "date_of_birth", FieldType.DATE),
    ("Name", "full_name", FieldType.TEXT),
    ("नाम", "full_name", FieldType.TEXT),
    ("氏名", "full_name", FieldType.TEXT),
    ("1. Mobile No.:", "mobile", FieldType.NUMBER),
    ("E-Mail", "email", FieldType.TEXT),
    ("Signature of Applicant", "signature", FieldType.SIGNATURE),
    ("हस्ताक्षर", "signature", FieldType.SIGNATURE),
    ("Firma", "signature", FieldType.SIGNATURE),
    ("Gender", "gender", FieldType.MULTIPLE_CHOICE),
    ("PIN Code", "postal_code", FieldType.NUMBER),
    ("Date of Birth (DD/MM/YYYY)", "date_of_birth", FieldType.DATE),
])
def test_template_matching(label, key, ftype):
    t, strength = match_template(label)
    assert t is not None and t.key == key, (label, t and t.key)
    assert strength >= 0.45
    assert synthesize_question(label)["type"] == ftype


def test_normalize_label():
    assert normalize_label("  2) Father's Name :__ ") == "father's name"
    assert normalize_label("पता:") == "पता"


def test_sentence_does_not_match_alias():
    t, strength = match_template("Please attach two passport-size photographs. Use black ink only.")
    assert strength < 0.45 or t is None


def test_substring_inside_word_does_not_match():
    # "пол" (gender) must not match inside "пользования"
    t, _ = match_template("Только для служебного пользования")
    assert t is None or t.key != "gender"


def test_unknown_label_gets_generic_question():
    q = synthesize_question("Expected Salary")
    assert q["template_key"] is None
    assert "Expected Salary" in q["question"]
    q = synthesize_question("Hobbies ☐", has_checkbox=True)
    assert q["type"] == FieldType.CHECKBOX


@pytest.mark.parametrize("noisy,key", [("जन्म ताथी", "date_of_birth"), ("Date of Brith", "date_of_birth"), ("Adress", "address"), ("पनि कोड", "postal_code")])
def test_fuzzy_matching_survives_ocr_noise(noisy, key):
    t, strength = match_template(noisy)
    assert t is not None and t.key == key and strength >= 0.45


def test_fuzzy_does_not_invent_matches():
    assert match_template("Hobbies")[0] is None
    assert match_template("Expected Salary")[0] is None
