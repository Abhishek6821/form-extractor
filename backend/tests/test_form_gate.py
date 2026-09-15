from app.pipeline import form_gate


def test_form_is_accepted(form_page):
    res = form_gate.run_form_gate([form_page])
    assert res.is_form
    assert res.confidence >= 0.55
    assert not res.used_classifier


def test_prose_is_rejected(prose_page):
    res = form_gate.run_form_gate([prose_page])
    assert not res.is_form


def test_empty_page_rejected():
    from app.schemas import Page

    res = form_gate.run_form_gate([Page(number=1, width=100, height=100)])
    assert not res.is_form


def test_ambiguous_uses_classifier_once(monkeypatch):
    calls = []
    monkeypatch.setattr(form_gate, "ACCEPT_THRESHOLD", 1.01)
    monkeypatch.setattr(form_gate, "REJECT_THRESHOLD", -0.01)
    from tests.conftest import make_form_page

    def clf(summary):
        calls.append(summary)
        return True, 0.9

    res = form_gate.run_form_gate([make_form_page()], classifier=clf)
    assert res.used_classifier and res.is_form and res.confidence == 0.9
    assert len(calls) == 1
    assert len(calls[0].split()) <= 120  # a summary, never the full document
