from app.pipeline import export
from app.schemas import FieldType, FormLayout, LayoutField


def layout():
    return FormLayout(title="Test Form", fields=[
        LayoutField(field_id="name", label="Full Name", type=FieldType.TEXT, x=0, y=0, w=6, required=True),
        LayoutField(field_id="dob", label="Date of Birth", type=FieldType.DATE, x=6, y=0, w=6),
        LayoutField(field_id="agree", label="I agree", type=FieldType.CHECKBOX, x=0, y=1, w=4),
        LayoutField(field_id="gender", label="Gender", type=FieldType.MULTIPLE_CHOICE, x=4, y=1, w=4, options=["M", "F"]),
        LayoutField(field_id="sig", label="Signature", type=FieldType.SIGNATURE, x=0, y=2, w=12),
        LayoutField(field_id="amt", label="Amount", type=FieldType.NUMBER, x=0, y=30, w=6),  # forces a 2nd page
    ])


def test_pdf_export_is_fillable_acroform():
    pdf = export.to_pdf(layout())
    assert pdf[:4] == b"%PDF"
    names = export.pdf_field_names(pdf)
    assert set(names) >= {"name", "dob", "agree", "gender", "sig", "amt"}


def test_html_export():
    html = export.to_html(layout())
    assert 'type="date"' in html and 'type="checkbox"' in html and "<select" in html and "required" in html


def test_json_schema_export():
    schema = export.to_json_schema(layout())
    assert schema["required"] == ["name"]
    assert schema["properties"]["dob"]["format"] == "date"
    assert schema["properties"]["gender"]["enum"] == ["M", "F"]
    assert schema["properties"]["agree"]["type"] == "boolean"
