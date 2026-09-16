import os
import sys
import warnings

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
warnings.filterwarnings("ignore", message="The `fitz` API is deprecated")
os.environ.setdefault("FORM_LLM_DISABLED", "1")
os.environ.setdefault("FORM_INPROCESS", "1")  # tests monkeypatch modules; keep the pipeline in-process

import pytest  # noqa: E402

from app.schemas import Page, Token  # noqa: E402

FIXTURES = os.path.join(os.path.dirname(__file__), "..", "eval", "fixtures")


def tok(text, x, y, w=None, h=12.0, conf=1.0):
    return Token(text=text, bbox=[x, y, w if w is not None else 6.0 * len(text), h], confidence=conf)


def make_form_page():
    """A small synthetic form: labels with colons, blanks, checkboxes, a title and a footer."""
    toks = [
        tok("APPLICATION", 200, 30, h=20), tok("FORM", 300, 30, h=20),
        tok("Full", 40, 100), tok("Name:", 68, 100), tok("Date", 320, 100), tok("of", 350, 100), tok("Birth:", 366, 100),
        tok("Father's", 40, 140), tok("Name", 92, 140), tok("____________________", 130, 140),
        tok("Gender:", 40, 180), tok("☐", 95, 180, w=10), tok("Male", 110, 180), tok("☐", 145, 180, w=10),
        tok("Female", 160, 180),
        tok("Address:", 40, 220),
        tok("Mobile", 40, 260), tok("No.:", 82, 260), tok("Email:", 320, 260),
        tok("Signature", 40, 700), tok("_______________", 110, 700),
        tok("Page", 280, 820, h=9), tok("1", 310, 820, h=9),
    ]
    return Page(number=1, width=600, height=850, tokens=toks)


def make_prose_page():
    words = ("public libraries are among the few remaining institutions that welcome everyone without asking "
             "for anything in return they lend books of course but they also provide internet access quiet study "
             "spaces children programs job search help and a place to be warm in winter critics sometimes argue "
             "that the internet has made libraries obsolete the opposite is true as information has become "
             "abundant the skills of evaluating it have become scarce").split()
    toks = []
    x, y = 40, 60
    for w in words:
        width = 6.0 * len(w)
        if x + width > 560:
            x, y = 40, y + 18
        toks.append(tok(w, x, y, w=width))
        x += width + 5
    return Page(number=1, width=600, height=850, tokens=toks)


@pytest.fixture
def form_page():
    return make_form_page()


@pytest.fixture
def prose_page():
    return make_prose_page()
