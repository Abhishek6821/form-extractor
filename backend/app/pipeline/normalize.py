"""Data normalisation applied to every extracted field, whichever provider (or none) produced it.

Goal: the API always returns the same clean shapes —
* labels: NFKC, trimmed, no trailing ':' / underscores, single spaces
* dates: ISO ``YYYY-MM-DD`` when parseable (dd/mm/yyyy, yyyy-mm-dd, month names in several languages)
* numbers: ASCII digits (Devanagari, Arabic-Indic, Bengali, full-width digits mapped), no thousands separators
* phone-like numbers: digits with optional leading '+'
* emails: lower-case
* checkbox: "true" / "false"
* multiple-choice: the matching option's canonical spelling
The original value is preserved in ``raw_value``.
"""
from __future__ import annotations

import re
import unicodedata

from app.schemas import ExtractedField, FieldType

# Digit blocks: Devanagari, Arabic-Indic, Extended Arabic-Indic, Bengali, Gurmukhi, Gujarati, Tamil, Telugu, full-width
_DIGIT_BLOCKS = [0x0966, 0x0660, 0x06F0, 0x09E6, 0x0A66, 0x0AE6, 0x0BE6, 0x0C66, 0xFF10]
_DIGIT_MAP = {chr(base + i): str(i) for base in _DIGIT_BLOCKS for i in range(10)}

_BLANK_RE = re.compile(r"^[\s_\.\-–—…☐□]*$")
_TRAILING_SEP_RE = re.compile(r"[\s:：\-–—_\.]+$")
_LEADING_NUM_RE = re.compile(r"^\s*(\(?[0-9ivxIVX]{1,3}[.)]|[a-zA-Z][.)])\s+")

MONTHS = {
    # en
    "jan": 1, "january": 1, "feb": 2, "february": 2, "mar": 3, "march": 3, "apr": 4, "april": 4, "may": 5, "jun": 6,
    "june": 6, "jul": 7, "july": 7, "aug": 8, "august": 8, "sep": 9, "sept": 9, "september": 9, "oct": 10, "october": 10,
    "nov": 11, "november": 11, "dec": 12, "december": 12,
    # es / pt / fr / de / it (common forms)
    "enero": 1, "febrero": 2, "marzo": 3, "abril": 4, "mayo": 5, "junio": 6, "julio": 7, "agosto": 8, "septiembre": 9,
    "setiembre": 9, "octubre": 10, "noviembre": 11, "diciembre": 12, "janeiro": 1, "fevereiro": 2, "março": 3, "maio": 5,
    "junho": 6, "julho": 7, "setembro": 9, "outubro": 10, "novembro": 11, "dezembro": 12, "janvier": 1, "février": 2,
    "mars": 3, "avril": 4, "mai": 5, "juin": 6, "juillet": 7, "août": 8, "septembre": 9, "octobre": 10, "novembre": 11,
    "décembre": 12, "januar": 1, "februar": 2, "märz": 3, "juni": 6, "juli": 7, "oktober": 10, "dezember": 12,
    # hi
    "जनवरी": 1, "फरवरी": 2, "मार्च": 3, "अप्रैल": 4, "मई": 5, "जून": 6, "जुलाई": 7, "अगस्त": 8, "सितंबर": 9, "सितम्बर": 9,
    "अक्टूबर": 10, "नवंबर": 11, "नवम्बर": 11, "दिसंबर": 12, "दिसम्बर": 12,
}

TRUE_WORDS = {"true", "yes", "y", "x", "✓", "✔", "☑", "☒", "checked", "on", "हाँ", "हां", "sí", "si", "oui", "ja", "是", "はい", "نعم", "да"}
FALSE_WORDS = {"false", "no", "n", "☐", "□", "unchecked", "off", "नहीं", "non", "nein", "否", "いいえ", "لا", "нет", ""}


def ascii_digits(s: str) -> str:
    return "".join(_DIGIT_MAP.get(ch, ch) for ch in s)


def clean_text(s: str) -> str:
    s = unicodedata.normalize("NFKC", s or "")
    s = s.replace("​", "").replace("‌", "").replace("‍", "")
    s = re.sub(r"\s+", " ", s).strip()
    return s


def normalize_label(label: str) -> str:
    s = clean_text(label)
    s = _LEADING_NUM_RE.sub("", s)
    s = _TRAILING_SEP_RE.sub("", s)
    s = re.sub(r"\s*\(\s*\)\s*$", "", s)  # "Name ( )"
    return s.strip()


def is_blank(value: str) -> bool:
    return bool(_BLANK_RE.match(value or ""))


def normalize_date(value: str) -> str:
    """Return ISO date if the value is recognisably a date, else the cleaned value."""
    v = ascii_digits(clean_text(value))
    if not v:
        return ""
    # yyyy-mm-dd / yyyy/mm/dd
    m = re.fullmatch(r"(\d{4})[./\-](\d{1,2})[./\-](\d{1,2})", v)
    if m:
        y, mo, d = (int(x) for x in m.groups())
        return _iso(y, mo, d) or v
    # dd-mm-yyyy (day first: the convention on almost every non-US form)
    m = re.fullmatch(r"(\d{1,2})[./\-\s](\d{1,2})[./\-\s](\d{2,4})", v)
    if m:
        d, mo, y = (int(x) for x in m.groups())
        if y < 100:
            y += 2000 if y < 30 else 1900
        if mo > 12 and d <= 12:  # clearly mm/dd/yyyy
            d, mo = mo, d
        return _iso(y, mo, d) or v
    # 14 March 2024 / March 14, 2024 / 14 मार्च 2024
    m = re.fullmatch(r"(\d{1,2})\s*(?:st|nd|rd|th)?[\s,.\-]+([^\d\s,.]+)[\s,.\-]+(\d{4})", v, re.I)
    if m and m.group(2).lower() in MONTHS:
        return _iso(int(m.group(3)), MONTHS[m.group(2).lower()], int(m.group(1))) or v
    m = re.fullmatch(r"([^\d\s,.]+)[\s,.\-]+(\d{1,2})\s*(?:st|nd|rd|th)?[\s,.\-]+(\d{4})", v, re.I)
    if m and m.group(1).lower() in MONTHS:
        return _iso(int(m.group(3)), MONTHS[m.group(1).lower()], int(m.group(2))) or v
    return v


def _iso(y: int, m: int, d: int) -> str:
    if 1 <= m <= 12 and 1 <= d <= 31 and 1000 <= y <= 2999:
        return f"{y:04d}-{m:02d}-{d:02d}"
    return ""


def normalize_number(value: str, label: str = "") -> str:
    v = ascii_digits(clean_text(value))
    if not v:
        return ""
    low = label.lower()
    if re.search(r"phone|mobile|tel|contact|फ़ोन|फोन|मोबाइल|teléfono|téléphone|telefon|电话|携帯|هاتف|جوال|телефон", low):
        digits = re.sub(r"[^\d+]", "", v)
        if digits.count("+") > 1 or ("+" in digits and not digits.startswith("+")):
            digits = "+" + digits.replace("+", "")
        return digits or v
    # currency / thousands separators -> plain number; keep one decimal point
    num = re.sub(r"[^\d.,\-]", "", v)
    if not re.search(r"\d", num):
        return v
    if num.count(",") and num.count("."):
        num = num.replace(",", "") if num.rfind(".") > num.rfind(",") else num.replace(".", "").replace(",", ".")
    elif num.count(",") == 1 and len(num.split(",")[1]) in (1, 2):
        num = num.replace(",", ".")  # 12,50 -> 12.50 (European decimal)
    else:
        num = num.replace(",", "")
    return num.rstrip(".") if re.fullmatch(r"-?\d+(\.\d+)?\.?", num) else v


def normalize_checkbox(value: str) -> str:
    v = clean_text(value).lower()
    if v in TRUE_WORDS or "☑" in v or "☒" in v or "✓" in v:
        return "true"
    if v in FALSE_WORDS or is_blank(v):
        return "false"
    return v


def normalize_choice(value: str, options: list[str]) -> str:
    v = clean_text(value)
    v = re.sub(r"[☐☑☒□■✓✔]", "", v).strip()
    if not v:
        return ""
    for o in options:
        if clean_text(o).lower() == v.lower():
            return o
    for o in options:
        if v.lower() in clean_text(o).lower() or clean_text(o).lower() in v.lower():
            return o
    return v


def normalize_value(value: str, ftype: FieldType, label: str = "", options: list[str] | None = None) -> str:
    raw = value or ""
    if ftype == FieldType.CHECKBOX:
        return normalize_checkbox(raw)
    if is_blank(raw):
        return ""
    if ftype == FieldType.DATE:
        return normalize_date(raw)
    if ftype == FieldType.NUMBER:
        return normalize_number(raw, label)
    if ftype == FieldType.MULTIPLE_CHOICE:
        return normalize_choice(raw, options or [])
    if ftype == FieldType.SIGNATURE:
        return ""
    v = clean_text(raw)
    if re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", v):
        return v.lower()
    return v


_SMALL_WORDS = {"of", "the", "and", "or", "in", "on", "at", "to", "for", "a", "an", "de", "du", "la", "le", "von", "der"}


def title_case_label(label: str) -> str:
    """'date of birth' -> 'Date of Birth'; leaves non-Latin text and existing capitals (DOB, PAN) alone."""
    if not label.isascii():
        return label
    out = []
    for i, w in enumerate(label.split()):
        if i and w.lower() in _SMALL_WORDS:
            out.append(w.lower())
        elif w == w.lower():
            out.append("-".join(p[:1].upper() + p[1:] for p in w.split("-")))
        else:
            out.append(w)  # keep DOB, PAN, McDonald
    return " ".join(out)


def normalize_field(f: ExtractedField) -> ExtractedField:
    f.raw_value = f.value
    f.label = title_case_label(normalize_label(f.label) or f.label)
    f.label_original_language = normalize_label(f.label_original_language) or f.label_original_language
    f.question = clean_text(f.question)
    f.options = [clean_text(o) for o in f.options if clean_text(o)]
    f.value = normalize_value(f.value, f.type, f.label, f.options)
    if f.type == FieldType.DATE and f.value and not re.fullmatch(r"\d{4}-\d{2}-\d{2}", f.value):
        f.needs_review = True  # a date we could not parse deserves a human look
    return f


def normalize_fields(fields: list[ExtractedField]) -> list[ExtractedField]:
    return [normalize_field(f) for f in fields]
