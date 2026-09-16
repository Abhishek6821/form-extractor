"""Shared data models for the whole pipeline.

The field taxonomy (Phase 0) and the final field schema (Phase 7) are defined
here once and reused by extraction, the Q&A synthesis, the API and the editor.
"""
from __future__ import annotations

from enum import Enum
from typing import Any, Literal, Optional

from pydantic import BaseModel, Field


class FieldType(str, Enum):
    TEXT = "text"
    DATE = "date"
    CHECKBOX = "checkbox"
    SIGNATURE = "signature"
    NUMBER = "number"
    MULTIPLE_CHOICE = "multiple-choice"
    TABLE_CELL = "table-cell"


BBox = list[float]  # [x, y, w, h] in page pixel coordinates


class Token(BaseModel):
    """One OCR word/segment with geometry."""

    text: str
    bbox: BBox  # [x, y, w, h]
    confidence: float = 1.0
    page: int = 1
    script: Optional[str] = None

    @property
    def x(self) -> float:
        return self.bbox[0]

    @property
    def y(self) -> float:
        return self.bbox[1]

    @property
    def w(self) -> float:
        return self.bbox[2]

    @property
    def h(self) -> float:
        return self.bbox[3]

    @property
    def cx(self) -> float:
        return self.bbox[0] + self.bbox[2] / 2

    @property
    def cy(self) -> float:
        return self.bbox[1] + self.bbox[3] / 2

    @property
    def x2(self) -> float:
        return self.bbox[0] + self.bbox[2]

    @property
    def y2(self) -> float:
        return self.bbox[1] + self.bbox[3]


class Page(BaseModel):
    number: int
    width: float
    height: float
    tokens: list[Token] = Field(default_factory=list)
    # Horizontal / vertical rule lines detected during preprocessing, as bboxes.
    lines: list[BBox] = Field(default_factory=list)
    reader: str = ""  # which text source produced the tokens: pdftext | paddle | apple | llm | json


class FormGateResult(BaseModel):
    is_form: bool
    confidence: float
    signals: dict[str, float] = Field(default_factory=dict)
    used_classifier: bool = False


class FieldCandidate(BaseModel):
    """Output of Hill-Climb Pass 1: a label with an associated value region."""

    candidate_id: str
    page: int
    label_tokens: list[int]  # indices into Page.tokens
    label_text: str
    value_tokens: list[int] = Field(default_factory=list)
    value_text: str = ""
    value_region: BBox  # where the answer is / should be written
    bbox: BBox  # union of label + value region
    grouping_score: float = 0.0
    has_separator: bool = False
    has_checkbox: bool = False
    separator_kind: str = ""  # colon | blank | box | line
    from_prose_row: bool = False  # the row reads like a sentence, not labels


class QAField(BaseModel):
    """Output of Hill-Climb Pass 2 (the 'perfect question' set)."""

    field_id: str
    question: str
    original_label: str
    expected_answer_type: FieldType
    bbox: BBox
    page: int = 1
    grouping_score: float = 0.0
    detected_value: str = ""
    template_key: Optional[str] = None
    options: list[str] = Field(default_factory=list)


class QADocument(BaseModel):
    document_type: Literal["form", "not_form"] = "form"
    form_confidence: float
    fields: list[QAField] = Field(default_factory=list)
    junk_candidates_removed: int = 0


class PassStats(BaseModel):
    """Search statistics of one hill-climb pass."""

    enabled: bool = True
    restarts: int = 0
    iterations: int = 0
    evaluations: int = 0
    cost: float = 0.0
    candidates_in: int = 0
    candidates_out: int = 0
    ms: float = 0.0


class TokenReport(BaseModel):
    """What the single LLM call cost, and what it would have cost without the local passes (estimates)."""

    used_input: int = 0
    used_output: int = 0
    prompt_sent: int = 0            # estimated tokens of the prompt we actually built (pruned fields)
    prompt_unpruned: int = 0        # if every pass-1 candidate had been sent
    prompt_raw_text: int = 0        # if the whole OCR text had been sent
    prompt_image: int = 0           # if the page image had been sent
    saved_vs_unpruned: int = 0
    saved_vs_raw_text: int = 0
    saved_vs_image: int = 0
    saved_pct_vs_raw_text: float = 0.0


class QualityReport(BaseModel):
    """How much the search improved on its non-searching baseline."""

    baseline_candidates: int = 0    # pass 1 without search
    baseline_fields: int = 0        # pass 2 without search
    candidates: int = 0
    fields: int = 0
    junk_removed: int = 0
    pass1_cost_initial: float = 0.0
    pass1_cost_final: float = 0.0
    pass2_cost_initial: float = 0.0
    pass2_cost_final: float = 0.0
    template_hit_rate: float = 0.0  # share of kept fields that got a canonical question


class HillClimbReport(BaseModel):
    enabled: bool = True
    restarts: int = 6
    max_iterations: int = 150
    pass1: PassStats = Field(default_factory=PassStats)  # field grouping (geometry)
    pass2: PassStats = Field(default_factory=PassStats)  # Q&A synthesis + junk pruning (selection)
    tokens: TokenReport = Field(default_factory=TokenReport)
    quality: QualityReport = Field(default_factory=QualityReport)


class ExtractedField(BaseModel):
    """Final field schema (Phase 7)."""

    field_id: str
    question: str
    label: str
    label_original_language: str
    type: FieldType
    value: str = ""
    raw_value: str = ""  # value before normalisation (as read from the page / model)
    bbox: BBox
    page: int = 1
    confidence: float = 0.0
    needs_review: bool = False
    options: list[str] = Field(default_factory=list)
    required: bool = False


class FieldPatch(BaseModel):
    question: Optional[str] = None
    label: Optional[str] = None
    type: Optional[FieldType] = None
    value: Optional[str] = None
    required: Optional[bool] = None
    options: Optional[list[str]] = None


class DocumentResult(BaseModel):
    document_id: str
    filename: str
    status: Literal["queued", "processing", "done", "rejected", "error"]
    is_form: bool = False
    form_confidence: float = 0.0
    gate: Optional[FormGateResult] = None
    pages: int = 0
    fields: list[ExtractedField] = Field(default_factory=list)
    qa: Optional[QADocument] = None  # Pass 2 output: the optimized Q&A JSON
    candidates: list[FieldCandidate] = Field(default_factory=list)  # Pass 1 output: field grouping
    hill_climb: Optional[HillClimbReport] = None
    llm_used: bool = False
    llm_provider: Optional[str] = None
    llm_model: Optional[str] = None
    ocr_backend: Optional[str] = None
    llm_input_tokens: int = 0
    llm_output_tokens: int = 0
    timing_ms: dict[str, float] = Field(default_factory=dict)
    error: Optional[str] = None
    corrections: list[dict[str, Any]] = Field(default_factory=list)


# ---- Form layouts built in the editor (Phase 8/9) -------------------------


class LayoutField(BaseModel):
    field_id: str
    label: str
    type: FieldType
    x: int  # grid units
    y: int
    w: int = 6
    h: int = 1
    required: bool = False
    placeholder: str = ""
    options: list[str] = Field(default_factory=list)
    value: str = ""


class FormLayout(BaseModel):
    title: str = "Untitled form"
    source_document_id: Optional[str] = None
    grid_columns: int = 12
    fields: list[LayoutField] = Field(default_factory=list)


class SavedForm(FormLayout):
    form_id: str
