"""Phase 4 — Hill-Climb Pass 1: Field Grouping (geometry only, no LLM).

State
-----
Tokens are first clustered into text rows.  A state is, for every row, the set
of *boundaries* (gap positions between consecutive tokens) at which the row is
split.  Every resulting segment is one candidate field.  Inside a segment the
label/value split is derived deterministically from separators, blank
underlines and the largest internal gap, so the search space stays small.

Moves
-----
* split a segment at a gap      (add boundary)
* merge two adjacent segments   (remove boundary)
* shift a boundary by one token (remove + add adjacent)  == reassign a token

Cost (lower is better)
----------------------
* label -> value distance                  (far apart = bad)
* column alignment of label starts         (aligned = good)
* separator present between label & value (good)
* whitespace gap regularity                (a big uniform gap = blank to fill)
* orphan tokens / overlapping groups       (bad)
"""
from __future__ import annotations

import random
import re
import statistics
from dataclasses import dataclass
from functools import lru_cache
from typing import Iterable, Optional

from app.schemas import FieldCandidate, Page, Token
from app.pipeline import geometry as g
from app.pipeline.hillclimb import random_restart_hill_climb

State = tuple[frozenset[int], ...]  # per row: boundary positions

MAX_LABEL_TOKENS = 7
WORD_RE = re.compile(r"\w", re.U)
VALUE_LIKE_RE = re.compile(r"^[\d\s,./:\-–—]+$|^[A-Z]{2,4}-?\d[\w\-/]*$|^\d{1,2}[/.-]\d{1,2}[/.-]\d{2,4}$")
RTL_SCRIPTS = {"arabic", "hebrew"}


def looks_like_value(text: str) -> bool:
    """Numbers, dates, codes: things that are answers, not labels."""
    t = text.strip()
    return bool(t) and bool(VALUE_LIKE_RE.match(t)) and any(ch.isdigit() for ch in t)


@dataclass
class Segment:
    row: int
    tokens: list[int]  # token indices
    label: list[int]
    value: list[int]
    value_region: list[float]
    has_separator: bool
    has_checkbox: bool
    orphan: bool
    internal_gap: float  # largest gap inside the label (bad if huge)
    label_value_gap: float
    sep_kind: str = ""              # colon | blank | box | line
    value_like_label: bool = False  # label is a number/date/code, i.e. an answer
    starts_with_box: bool = False   # "☐ Male" after another segment = an option
    first_in_row: bool = True


class GroupingProblem:
    def __init__(self, page: Page):
        self.page = page
        self.tokens = page.tokens
        self.rows = g.cluster_rows(self.tokens)
        self.mh = g.median_height(self.tokens)
        # Right-to-left rows are read right-to-left so labels precede blanks.
        self.rtl: list[bool] = []
        for r in self.rows:
            alpha = [i for i in r if any(ch.isalpha() for ch in self.tokens[i].text)]
            n_rtl = sum(1 for i in alpha if (self.tokens[i].script or "") in RTL_SCRIPTS)
            is_rtl = bool(alpha) and n_rtl > len(alpha) / 2
            self.rtl.append(is_rtl)
            if is_rtl:
                r.reverse()
        self.gaps: list[list[float]] = []
        for r, rtl in zip(self.rows, self.rtl):
            if rtl:
                self.gaps.append([g.horizontal_gap(self.tokens[b], self.tokens[a]) for a, b in zip(r, r[1:])])
            else:
                self.gaps.append([g.horizontal_gap(self.tokens[a], self.tokens[b]) for a, b in zip(r, r[1:])])
        self._row_cache: dict[tuple[int, frozenset[int]], tuple[float, list[Segment]]] = {}

    # ---------------------------------------------------------- segments

    def _segments(self, row: int, boundaries: frozenset[int]) -> list[Segment]:
        r = self.rows[row]
        segs: list[Segment] = []
        start = 0
        cuts = sorted(boundaries) + [len(r) - 1]
        for cut in cuts:
            idxs = r[start:cut + 1]
            if idxs:
                toks = [self.tokens[i] for i in idxs]
                colons = [k for k, t in enumerate(toks) if g.ends_with_separator(t.text)]
                if len(colons) > 1:
                    sub_start = 0
                    for c_idx in range(len(colons) - 1):
                        next_col = colons[c_idx + 1]
                        label_start = next_col
                        while (label_start > colons[c_idx] + 1 and
                               not g.is_blank_line(toks[label_start - 1].text) and
                               not g.is_checkbox(toks[label_start - 1].text)):
                            label_start -= 1
                        sub_idxs = idxs[sub_start:label_start]
                        if sub_idxs:
                            segs.append(self._build_segment(row, sub_idxs, next_start=(idxs[label_start] if label_start < len(idxs) else None),
                                                            first_in_row=(start == 0 and sub_start == 0)))
                        sub_start = label_start
                    sub_idxs = idxs[sub_start:]
                    if sub_idxs:
                        segs.append(self._build_segment(row, sub_idxs, next_start=(r[cut + 1] if cut + 1 < len(r) else None), first_in_row=False))
                else:
                    segs.append(self._build_segment(row, idxs, next_start=(r[cut + 1] if cut + 1 < len(r) else None),
                                                    first_in_row=(start == 0)))
            start = cut + 1
        return segs

    def _build_segment(self, row: int, idxs: list[int], next_start: Optional[int], first_in_row: bool = True) -> Segment:
        toks = [self.tokens[i] for i in idxs]
        page = self.page
        rtl = self.rtl[row]
        has_sep = False
        sep_kind = ""
        has_box = any(g.is_checkbox(t.text) or g.has_checkbox_glyph(t.text) for t in toks)
        split_at = len(idxs)  # label = idxs[:split_at], value = idxs[split_at:]
        # 1) separator ":" ends the label
        for k, t in enumerate(toks):
            if g.ends_with_separator(t.text):
                split_at = k + 1
                has_sep = True
                sep_kind = "colon"
                break
        # 2) blank underline / dotted line is the value region (either side of the label)
        blank_only: list[int] = []
        if not has_sep:
            blanks = [k for k, t in enumerate(toks) if g.is_blank_line(t.text)]
            if blanks and len(blanks) < len(toks):
                blank_only = [idxs[k] for k in blanks]
                has_sep = True
                sep_kind = "blank"
        # 3) checkbox glyph: "[ ] Yes" / "Yes [ ]" -> label is the text, value is the box
        box_only: list[int] = []
        if not has_sep and has_box and len(toks) > 1:
            box_pos = [k for k, t in enumerate(toks) if g.is_checkbox(t.text)]
            if box_pos:
                box_only = [idxs[k] for k in box_pos]
                has_sep = True
                sep_kind = "box"
        # 4) largest internal gap
        internal = 0.0
        if not has_sep and len(idxs) > 1:
            gaps = [g.horizontal_gap(a, b) for a, b in zip(toks, toks[1:])]
            k = max(range(len(gaps)), key=lambda i: gaps[i])
            if gaps[k] > 2.5 * self.mh:
                split_at = k + 1
            internal = max(gaps)
        if box_only or blank_only:
            special = set(box_only) | set(blank_only)
            label = [i for i in idxs if i not in special]
            value = [i for i in idxs if i in special]
        else:
            label = idxs[:split_at]
            value = idxs[split_at:]
        label_toks = [self.tokens[i] for i in label]
        if len(label_toks) > 1:
            internal = max(g.horizontal_gap(a, b) for a, b in zip(label_toks, label_toks[1:]))
        lab_box = g.union_bbox([t.bbox for t in label_toks])
        if value:
            vr = g.union_bbox([self.tokens[i].bbox for i in value])
            if not label_toks:
                lab_box = vr
            lv_gap = vr[0] - (lab_box[0] + lab_box[2])
        else:
            # Empty value: whitespace after the label until the next segment / margin
            # (after = right of the label for LTR rows, left of it for RTL rows).
            if rtl:
                left_edge = self.tokens[next_start].x2 + self.mh * 0.5 if next_start is not None else self.mh
                x1 = lab_box[0] - self.mh * 0.3
                vr = [left_edge, lab_box[1], max(0.0, x1 - left_edge), lab_box[3]]
            else:
                right_edge = self.tokens[next_start].x - self.mh * 0.5 if next_start is not None else page.width - self.mh
                x0 = lab_box[0] + lab_box[2] + self.mh * 0.3
                vr = [x0, lab_box[1], max(0.0, right_edge - x0), lab_box[3]]
            lv_gap = 0.0
            # A drawn rule line under the blank region counts as a separator.
            if not has_sep and vr[2] >= 2 * self.mh and g.line_near(vr, page.lines, tol=self.mh * 0.8,
                                                                     max_width=0.75 * page.width):
                has_sep = True
                sep_kind = "line"
            # No room on this row: a blank underline on the *next* row directly
            # under the label (with no label of its own) is the value region.
            if vr[2] < 2 * self.mh and not has_sep:
                below = self._blank_below(row, lab_box)
                if below is not None:
                    vr = below
                    lv_gap = below[1] - (lab_box[1] + lab_box[3])
                    has_sep = True
                    sep_kind = "blank"
        orphan = (not value) and (not has_sep) and vr[2] < 3 * self.mh and not has_box
        value_like = bool(label_toks) and all(looks_like_value(t.text) for t in label_toks)
        starts_box = bool(toks) and g.is_checkbox(toks[0].text) and not first_in_row
        return Segment(row, idxs, label, value, vr, has_sep, has_box, orphan, internal, lv_gap, sep_kind, value_like,
                       starts_box, first_in_row)

    def _blank_below(self, row: int, lab_box: list[float]) -> Optional[list[float]]:
        if row + 1 >= len(self.rows):
            return None
        nxt = self.rows[row + 1]
        for i in nxt:
            t = self.tokens[i]
            if not g.is_blank_line(t.text):
                continue
            # A label right next to the blank (either side) on that row owns it.
            owned = False
            for j in nxt:
                o = self.tokens[j]
                if j == i or g.is_blank_line(o.text):
                    continue
                if min(abs(t.x - o.x2), abs(o.x - t.x2)) < 3 * self.mh:
                    owned = True
                    break
            if owned:
                continue
            if t.x < lab_box[0] + lab_box[2] and t.x2 > lab_box[0] and 0 <= t.y - (lab_box[1] + lab_box[3]) < 2.5 * self.mh:
                return list(t.bbox)
        return None

    # -------------------------------------------------------------- cost

    def row_cost(self, row: int, boundaries: frozenset[int]) -> tuple[float, list[Segment]]:
        key = (row, boundaries)
        if key in self._row_cache:
            return self._row_cache[key]
        segs = self._segments(row, boundaries)
        cost = 0.0
        mh = self.mh
        for s in segs:
            n_label = len(s.label)
            if s.orphan:
                cost += 1.5
            if n_label > MAX_LABEL_TOKENS:
                cost += 0.4 * (n_label - MAX_LABEL_TOKENS)
            if n_label == 0:
                cost += 1.0
            elif not any(WORD_RE.search(self.tokens[i].text) for i in s.label):
                cost += 1.5  # punctuation-only "label" (a stray ':' or '-')
            # Huge gap inside a label means two fields were merged wrongly.
            if s.internal_gap > 3 * mh:
                cost += 1.2 + min(3.0, s.internal_gap / (6 * mh))
            # Label far from its value.
            if s.label_value_gap > 6 * mh:
                cost += 0.8
            if s.has_separator:
                cost -= 0.9 if s.sep_kind != "line" else 0.5
                if s.value:
                    cost -= 0.3  # a label with an actual answer next to it
                elif s.value_region[2] < 2 * mh and not s.has_checkbox:
                    cost += 0.6  # "Label:" followed by nothing to write into
            if s.has_checkbox:
                cost -= 0.4
            # A number/date/code standing alone is an answer cut off from its label.
            if s.value_like_label:
                cost += 1.0
            # "☐ Option" segments belong to the field before them.
            if s.starts_with_box:
                cost += 2.0
            # A clear whitespace region to write into is a good sign (for label-like text).
            if not s.value and s.value_region[2] >= 3 * mh and not s.value_like_label:
                cost -= 0.5
            # Tiny value region with no separator: probably fragment of prose.
            if not s.value and not s.has_separator and s.value_region[2] < 2 * mh:
                cost += 0.6
            # Values that are much longer than labels look like prose.
            if len(s.value) > 12:
                cost += 0.05 * (len(s.value) - 12)
        # A chain of checkbox segments in one row is one multiple-choice field.
        for prev, cur in zip(segs, segs[1:]):
            if prev.has_checkbox and cur.has_checkbox:
                cost += 2.0
            elif prev.has_checkbox and not cur.has_separator and not cur.value and len(cur.label) <= 2:
                cost += 1.5  # trailing option whose box went to the previous segment
        # Each extra segment has a small cost so we don't over-split.
        cost += 0.25 * max(0, len(segs) - 1)
        self._row_cache[key] = (cost, segs)
        return self._row_cache[key]

    def cost(self, state: State) -> float:
        total = 0.0
        starts: list[float] = []
        for r, b in enumerate(state):
            c, segs = self.row_cost(r, b)
            total += c
            row = self.rows[r]
            for s in segs:
                if not s.label:
                    continue
                # Only "natural" column starts count: first in row, or after a big gap.
                pos = row.index(s.tokens[0])
                if pos == 0 or self.gaps[r][pos - 1] > 2 * self.mh:
                    starts.append(self.tokens[s.label[0]].x)
        # Alignment bonus: label starts sharing a column (bucketed by ~1 char).
        if starts:
            bucket = max(2.0, self.mh * 0.8)
            counts: dict[int, int] = {}
            for x in starts:
                k = int(x // bucket)
                counts[k] = counts.get(k, 0) + 1
            aligned = sum(c for c in counts.values() if c >= 2)
            total -= 0.35 * aligned
        return total

    # --------------------------------------------------------- neighbours

    def neighbors(self, state: State) -> Iterable[State]:
        for r, b in enumerate(state):
            n_gaps = len(self.gaps[r])
            if n_gaps == 0:
                continue
            for pos in range(n_gaps):
                nb: frozenset[int]
                if pos in b:
                    nb = b - {pos}  # merge
                    yield state[:r] + (nb,) + state[r + 1:]
                    for shifted in (pos - 1, pos + 1):  # shift boundary
                        if 0 <= shifted < n_gaps and shifted not in b:
                            yield state[:r] + ((b - {pos}) | {shifted},) + state[r + 1:]
                else:
                    nb = b | {pos}  # split
                    yield state[:r] + (nb,) + state[r + 1:]

    # ------------------------------------------------------------ initial

    def initial(self, rng: random.Random) -> State:
        """Split each row at gaps above a (randomised) threshold and after separators."""
        factor = rng.uniform(1.5, 5.0)
        state = []
        for r, gaps in enumerate(self.gaps):
            b = set()
            for k, gap in enumerate(gaps):
                if gap > factor * self.mh:
                    b.add(k)
                elif rng.random() < 0.08:
                    b.add(k)
            state.append(frozenset(b))
        return tuple(state)

    def deterministic_initial(self) -> State:
        state = []
        for r, gaps in enumerate(self.gaps):
            b = {k for k, gap in enumerate(gaps) if gap > 3 * self.mh}
            state.append(frozenset(b))
        return tuple(state)


def _label_text(tokens: list[Token], idxs: list[int]) -> str:
    return " ".join(tokens[i].text for i in idxs).strip()


def _value_text(tokens: list[Token], idxs: list[int]) -> str:
    return " ".join(tokens[i].text for i in idxs if not g.is_blank_line(tokens[i].text)).strip()


def group_page(page: Page, restarts: int = 6, seed: int = 0, max_iterations: int = 150) -> tuple[list[FieldCandidate], dict]:
    """Run Pass 1 on one page; returns candidates + search statistics."""
    if not page.tokens:
        return [], {"restarts": 0, "evaluations": 0, "cost": 0.0}
    prob = GroupingProblem(page)

    def make_initial(rng: random.Random) -> State:
        return prob.deterministic_initial() if rng.random() < 0.34 else prob.initial(rng)

    res = random_restart_hill_climb(make_initial, prob.cost, prob.neighbors, restarts=restarts,
                                    max_iterations=max_iterations, seed=seed)
    cands: list[FieldCandidate] = []
    n = 0
    row_costs = []
    for r, b in enumerate(res.state):
        c, segs = prob.row_cost(r, b)
        row_costs.append(c)
        for s in segs:
            if not s.label:
                continue
            n += 1
            lab = _label_text(page.tokens, s.label)
            val = _value_text(page.tokens, s.value)
            row_toks = prob.rows[r]
            prose_row = len(row_toks) >= 8 and all(gp < 1.2 * prob.mh for gp in prob.gaps[r]) and not any(
                g.ends_with_separator(page.tokens[i].text) or g.is_blank_line(page.tokens[i].text) or g.is_checkbox(page.tokens[i].text)
                for i in row_toks)
            bbox = g.union_bbox([page.tokens[i].bbox for i in s.tokens] + [s.value_region])
            # Grouping score: separator / checkbox / clear blank region push it up.
            score = 0.55
            if s.has_separator:
                score += 0.25
            if s.has_checkbox:
                score += 0.1
            if not s.value and s.value_region[2] >= 3 * prob.mh:
                score += 0.1
            if s.orphan:
                score -= 0.35
            if s.internal_gap > 3 * prob.mh:
                score -= 0.2
            if len(s.label) > MAX_LABEL_TOKENS:
                score -= 0.15
            cands.append(FieldCandidate(candidate_id=f"p{page.number}_c{n:03d}", page=page.number,
                                        label_tokens=list(s.label), label_text=lab, value_tokens=list(s.value),
                                        value_text=val, value_region=[round(v, 1) for v in s.value_region],
                                        bbox=[round(v, 1) for v in bbox], grouping_score=round(max(0.0, min(1.0, score)), 3),
                                        has_separator=s.has_separator, has_checkbox=s.has_checkbox, separator_kind=s.sep_kind,
                                        from_prose_row=prose_row))
    stats = {"restarts": res.restarts, "evaluations": res.evaluations, "iterations": res.iterations,
             "cost": round(res.cost, 3)}
    return cands, stats
