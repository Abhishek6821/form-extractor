"""Language-independent geometry helpers shared by the gate and both passes."""
from __future__ import annotations

import re
import statistics
from typing import Sequence

from app.schemas import Token

SEPARATOR_RE = re.compile(r"[:：﹕]\s*$")
BLANK_RE = re.compile(r"^[_\.\-–—…]{3,}$")  # ________ or ........ or -----
CHECKBOX_CHARS = set("☐☑☒□■▢◻◼○●◯◉")
CHECKBOX_RE = re.compile(r"^(\[\s?[xX✓✔]?\s?\]|\(\s?[xX✓✔]?\s?\)|[☐☑☒□■▢◻◼○●◯◉])$")
CHECKBOX_INLINE_RE = re.compile(r"(\[\s?[xX✓✔]?\s?\]|\(\s?[xX✓✔]?\s?\)|[☐☑☒□■▢◻◼○●◯◉])")
DATE_HINT_RE = re.compile(r"(dd|mm|yy|yyyy|/\s*/|__/__)", re.I)


def ends_with_separator(text: str) -> bool:
    return bool(SEPARATOR_RE.search(text))


def is_blank_line(text: str) -> bool:
    return bool(BLANK_RE.match(text))


def is_checkbox(text: str) -> bool:
    return bool(CHECKBOX_RE.match(text.strip()))


def has_checkbox_glyph(text: str) -> bool:
    return bool(CHECKBOX_INLINE_RE.search(text))


def median_height(tokens: Sequence[Token]) -> float:
    hs = [t.h for t in tokens if t.h > 0]
    return statistics.median(hs) if hs else 12.0


def cluster_rows(tokens: Sequence[Token], tol_factor: float = 0.6) -> list[list[int]]:
    """Group token indices into text rows by vertical centre proximity.

    Returns rows sorted top-to-bottom, each row sorted left-to-right.
    """
    if not tokens:
        return []
    mh = median_height(tokens)
    tol = mh * tol_factor
    order = sorted(range(len(tokens)), key=lambda i: (tokens[i].cy, tokens[i].x))
    rows: list[list[int]] = []
    row_cy: list[float] = []
    for i in order:
        t = tokens[i]
        placed = False
        # Only need to check the last few rows because order is by cy.
        for r in range(len(rows) - 1, max(-1, len(rows) - 4), -1):
            if abs(row_cy[r] - t.cy) <= tol:
                rows[r].append(i)
                n = len(rows[r])
                row_cy[r] = (row_cy[r] * (n - 1) + t.cy) / n
                placed = True
                break
        if not placed:
            rows.append([i])
            row_cy.append(t.cy)
    for r in rows:
        r.sort(key=lambda i: tokens[i].x)
    rows.sort(key=lambda r: tokens[r[0]].cy)
    return rows


def horizontal_gap(a: Token, b: Token) -> float:
    """Gap between token a (left) and b (right); negative if overlapping."""
    return b.x - a.x2


def union_bbox(boxes: Sequence[Sequence[float]]) -> list[float]:
    xs0 = [b[0] for b in boxes]
    ys0 = [b[1] for b in boxes]
    xs1 = [b[0] + b[2] for b in boxes]
    ys1 = [b[1] + b[3] for b in boxes]
    x0, y0, x1, y1 = min(xs0), min(ys0), max(xs1), max(ys1)
    return [x0, y0, x1 - x0, y1 - y0]


def iou(a: Sequence[float], b: Sequence[float]) -> float:
    ax0, ay0, ax1, ay1 = a[0], a[1], a[0] + a[2], a[1] + a[3]
    bx0, by0, bx1, by1 = b[0], b[1], b[0] + b[2], b[1] + b[3]
    iw = max(0.0, min(ax1, bx1) - max(ax0, bx0))
    ih = max(0.0, min(ay1, by1) - max(ay0, by0))
    inter = iw * ih
    if inter <= 0:
        return 0.0
    return inter / (a[2] * a[3] + b[2] * b[3] - inter)


def line_near(bbox: Sequence[float], lines: Sequence[Sequence[float]], tol: float, max_width: float = 1e9) -> bool:
    """True if a detected rule line lies just under / beside the bbox.

    Lines wider than ``max_width`` (decorative full-width rules) are ignored.
    """
    x, y, w, h = bbox
    for lx, ly, lw, lh in lines:
        horizontal = lw > lh
        if horizontal:
            if lw > max_width:
                continue
            if abs(ly - (y + h)) <= tol and lx < x + w and lx + lw > x:
                return True
        else:
            if abs(lx - (x + w)) <= tol and ly < y + h and ly + lh > y:
                return True
    return False
