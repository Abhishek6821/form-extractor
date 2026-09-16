from app.pipeline import grouping


def labels(cands):
    return [c.label_text for c in cands]


def test_grouping_recovers_fields(form_page):
    cands, stats = grouping.group_page(form_page, restarts=4)
    labs = labels(cands)
    assert "Full Name:" in labs
    assert "Date of Birth:" in labs
    assert "Father's Name" in labs
    assert "Gender:" in labs
    assert "Mobile No.:" in labs
    assert stats["restarts"] == 4 and stats["evaluations"] > 0


def test_checkbox_options_stay_with_label(form_page):
    cands, _ = grouping.group_page(form_page, restarts=4)
    gender = next(c for c in cands if c.label_text == "Gender:")
    assert gender.has_checkbox
    assert "Male" in gender.value_text and "Female" in gender.value_text
    assert not any(c.label_text in ("Male", "Female") for c in cands)


def test_blank_underline_becomes_value_region(form_page):
    cands, _ = grouping.group_page(form_page, restarts=4)
    father = next(c for c in cands if c.label_text == "Father's Name")
    assert father.has_separator and father.separator_kind == "blank"
    assert father.value_text == ""  # underscores are not an answer
    assert father.value_region[2] > 50


def test_glued_underline_split():
    from app.pipeline.ocr import normalize_tokens
    from app.schemas import Token

    toks = normalize_tokens([Token(text="Address________", bbox=[0, 0, 150, 12])])
    assert [t.text for t in toks] == ["Address", "________"]
    assert toks[0].bbox[2] + toks[1].bbox[2] == 150


def test_rtl_rows_are_read_right_to_left():
    from app.schemas import Page, Token

    # "الاسم الكامل :" rendered right-to-left: the colon sits at the far left.
    toks = [Token(text=":", bbox=[100, 50, 4, 12]), Token(text="الكامل", bbox=[110, 50, 40, 12], script="arabic"),
            Token(text="الاسم", bbox=[160, 50, 40, 12], script="arabic")]
    page = Page(number=1, width=400, height=200, tokens=toks)
    cands, _ = grouping.group_page(page, restarts=3)
    assert len(cands) == 1
    assert cands[0].label_text == "الاسم الكامل :"
    assert cands[0].value_region[0] < 100  # blank space is to the left of the label


def test_row_of_only_checkboxes_does_not_crash():
    from app.schemas import Page, Token

    toks = [Token(text="☐", bbox=[40, 100, 10, 12]), Token(text="☐", bbox=[80, 100, 10, 12]), Token(text="☐", bbox=[120, 100, 10, 12]),
            Token(text="Name:", bbox=[40, 140, 30, 12]), Token(text="____", bbox=[80, 140, 60, 12])]
    page = Page(number=1, width=400, height=300, tokens=toks)
    cands, _ = grouping.group_page(page, restarts=3)
    assert any(c.label_text == "Name:" for c in cands)
