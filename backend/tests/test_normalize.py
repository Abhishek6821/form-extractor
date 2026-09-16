import pytest

from app.pipeline import normalize as n
from app.schemas import ExtractedField, FieldType


@pytest.mark.parametrize("raw,expected", [
    ("14/03/2024", "2024-03-14"), ("14-03-24", "2024-03-14"), ("2024.03.14", "2024-03-14"), ("03/25/2024", "2024-03-25"),
    ("14 March 2024", "2024-03-14"), ("March 14, 2024", "2024-03-14"), ("१४/०३/२०२४", "2024-03-14"),
    ("14 मार्च 2024", "2024-03-14"), ("١٤/٠٣/٢٠٢٤", "2024-03-14"), ("someday", "someday"),
])
def test_dates(raw, expected):
    assert n.normalize_date(raw) == expected


@pytest.mark.parametrize("raw,label,expected", [
    ("12,500.00", "Amount", "12500.00"), ("₹ 1,20,000", "Total", "120000"), ("12,50", "Price", "12.50"),
    ("1.234.567,89", "Betrag", "1234567.89"), ("+91 98765-43210", "Mobile No.", "+919876543210"),
    ("(022) 2345 6789", "Phone", "02223456789"), ("९८७६५४३२१०", "मोबाइल नंबर", "9876543210"), ("abc", "Qty", "abc"),
])
def test_numbers(raw, label, expected):
    assert n.normalize_number(raw, label) == expected


def test_checkbox_and_choice():
    assert n.normalize_checkbox("☑") == "true" and n.normalize_checkbox("हाँ") == "true"
    assert n.normalize_checkbox("") == "false" and n.normalize_checkbox("☐") == "false"
    assert n.normalize_choice("☑ female", ["Male", "Female", "Other"]) == "Female"
    assert n.normalize_choice("fem", ["Male", "Female"]) == "Female"


def test_labels_and_blanks():
    assert n.normalize_label(" 2) Father's Name :____ ") == "Father's Name"
    assert n.normalize_label("जन्म तिथि:") == "जन्म तिथि"
    assert n.normalize_value("________", FieldType.TEXT) == ""
    assert n.normalize_value("  John@Example.COM ", FieldType.TEXT) == "john@example.com"


def test_normalize_field_keeps_raw_and_flags_unparsed_dates():
    f = ExtractedField(field_id="f_1", question="q", label="DOB:", label_original_language="जन्म तिथि:",
                       type=FieldType.DATE, value="14/03/2024", bbox=[0, 0, 1, 1])
    n.normalize_field(f)
    assert f.value == "2024-03-14" and f.raw_value == "14/03/2024" and f.label == "DOB" and not f.needs_review
    g = ExtractedField(field_id="f_2", question="q", label="Date", label_original_language="Date",
                       type=FieldType.DATE, value="next monday", bbox=[0, 0, 1, 1])
    n.normalize_field(g)
    assert g.needs_review is True


def test_title_case_labels():
    assert n.title_case_label("date of birth") == "Date of Birth"
    assert n.title_case_label("father's name") == "Father's Name"
    assert n.title_case_label("e-mail") == "E-Mail"
    assert n.title_case_label("PAN") == "PAN" and n.title_case_label("Full Name") == "Full Name"
    assert n.title_case_label("जन्म तिथि") == "जन्म तिथि"
    assert n.title_case_label("Date Of Birth") == "Date of Birth"
