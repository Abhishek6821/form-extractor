"""Phase 3 — Form Gate: is this document even a form?

Runs entirely on OCR output (language independent).  Combines structural
signals into a form-likelihood score; only an *ambiguous* score triggers one
cheap classification call on a short text summary (never the full document).
"""
from __future__ import annotations

import statistics
from typing import Callable, Optional

from app.schemas import FormGateResult, Page, Token
from app.pipeline import geometry as g

ACCEPT_THRESHOLD = 0.55
REJECT_THRESHOLD = 0.32

# Weights were tuned on the eval fixtures (see eval/run_eval.py).
WEIGHTS = {
    "separator_ratio": 2.2,
    "blank_ratio": 2.0,
    "checkbox_ratio": 2.0,
    "rule_line_density": 1.2,
    "short_row_ratio": 1.3,
    "gap_regularity": 1.0,
    "label_gap_ratio": 1.6,
    "prose_penalty": -2.2,
}


def compute_signals(pages: list[Page]) -> dict[str, float]:
    tokens: list[Token] = [t for p in pages for t in p.tokens]
    n = len(tokens)
    if n == 0:
        return {k: 0.0 for k in WEIGHTS} | {"token_count": 0.0}

    sep = sum(1 for t in tokens if g.ends_with_separator(t.text))
    blank = sum(1 for t in tokens if g.is_blank_line(t.text))
    boxes = sum(1 for t in tokens if g.is_checkbox(t.text) or g.has_checkbox_glyph(t.text))
    line_count = sum(len(p.lines) for p in pages)
    page_area = sum(p.width * p.height for p in pages) or 1.0

    # Row statistics (per page).
    short_rows = 0
    total_rows = 0
    row_lengths: list[int] = []
    big_gaps = 0
    label_gap_rows = 0
    for p in pages:
        rows = g.cluster_rows(p.tokens)
        mh = g.median_height(p.tokens)
        for r in rows:
            total_rows += 1
            row_lengths.append(len(r))
            if len(r) <= 4:
                short_rows += 1
            # A short label followed by a large horizontal gap = space to write.
            for a, b in zip(r, r[1:]):
                gap = g.horizontal_gap(p.tokens[a], p.tokens[b])
                if gap > 4 * mh:
                    big_gaps += 1
            last = p.tokens[r[-1]]
            trailing_space = p.width - last.x2
            if len(r) <= 5 and (trailing_space > 0.35 * p.width or any(
                    g.horizontal_gap(p.tokens[a], p.tokens[b]) > 4 * mh for a, b in zip(r, r[1:]))):
                label_gap_rows += 1
    total_rows = max(total_rows, 1)
    avg_row_len = statistics.mean(row_lengths) if row_lengths else 0.0
    row_len_var = statistics.pstdev(row_lengths) if len(row_lengths) > 1 else 0.0

    # Prose: long rows of similar length, few separators.
    prose = 0.0
    if avg_row_len >= 8:
        prose = min(1.0, (avg_row_len - 8) / 8 + 0.4)
        if row_len_var < 3:
            prose = min(1.0, prose + 0.2)

    signals = {
        "separator_ratio": min(1.0, sep / n * 6),
        "blank_ratio": min(1.0, blank / n * 8),
        "checkbox_ratio": min(1.0, boxes / n * 10),
        "rule_line_density": min(1.0, line_count / max(1.0, page_area / 1e6) / 15),
        "short_row_ratio": short_rows / total_rows,
        "gap_regularity": min(1.0, big_gaps / total_rows),
        "label_gap_ratio": label_gap_rows / total_rows,
        "prose_penalty": prose,
        "token_count": float(n),
    }
    return signals


def score(signals: dict[str, float]) -> float:
    if signals.get("token_count", 0) == 0:
        return 0.0
    total = sum(WEIGHTS[k] * signals[k] for k in WEIGHTS)
    max_pos = sum(w for w in WEIGHTS.values() if w > 0)
    return max(0.0, min(1.0, total / max_pos * 1.6))


def text_summary(pages: list[Page], max_tokens: int = 120) -> str:
    """Short text summary for the ambiguous-case classifier."""
    out = []
    for p in pages:
        for r in g.cluster_rows(p.tokens):
            out.append(" ".join(p.tokens[i].text for i in r))
    text = "\n".join(out)
    words = text.split()
    return " ".join(words[:max_tokens])


Classifier = Callable[[str], tuple[bool, float]]


def run_form_gate(pages: list[Page], classifier: Optional[Classifier] = None) -> FormGateResult:
    signals = compute_signals(pages)
    s = score(signals)
    used = False
    if s >= ACCEPT_THRESHOLD:
        is_form, conf = True, s
    elif s <= REJECT_THRESHOLD:
        is_form, conf = False, 1.0 - s
    else:
        # Ambiguous: one cheap call on a summary, never the full document.
        if classifier is not None:
            try:
                is_form, conf = classifier(text_summary(pages))
                used = True
            except Exception:
                is_form, conf = s >= 0.45, 0.5
        else:
            is_form, conf = s >= 0.45, 0.5 + abs(s - 0.45)
    return FormGateResult(is_form=is_form, confidence=round(float(conf), 3),
                          signals={k: round(v, 3) for k, v in signals.items()}, used_classifier=used)
