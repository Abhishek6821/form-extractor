"""Phase 5a — Q&A synthesis: multilingual label -> canonical question template.

Rule/template based, no model call.  Each template has a canonical English
question, an expected answer type and aliases in several languages/scripts.
Matching is done on a normalised label: exact alias first, then containment,
then token overlap.  Unknown labels fall back to a generic question with the
type inferred from cheap regex hints.
"""
from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field

from app.schemas import FieldType
from app.pipeline import geometry as g


@dataclass
class Template:
    key: str
    question: str
    label: str
    type: FieldType
    aliases: list[str] = field(default_factory=list)
    options: list[str] = field(default_factory=list)


T = FieldType
TEMPLATES: list[Template] = [
    Template("full_name", "What is the applicant's full name?", "Full Name", T.TEXT,
             ["name", "full name", "applicant name", "name of applicant", "candidate name", "your name", "नाम",
              "पूरा नाम", "आवेदक का नाम", "nombre", "nombre completo", "nom", "nom complet", "name (vorname nachname)",
              "vollständiger name", "姓名", "名前", "氏名", "이름", "성명", "الاسم", "الاسم الكامل", "имя", "фио",
              "nome", "nome completo", "নাম", "பெயர்", "పేరు", "નામ", "ਨਾਮ", "ಹೆಸರು", "പേര്"]),
    Template("first_name", "What is the applicant's first name?", "First Name", T.TEXT,
             ["first name", "given name", "forename", "प्रथम नाम", "primer nombre", "prénom", "vorname", "名", "이름",
              "الاسم الأول", "nome próprio"]),
    Template("last_name", "What is the applicant's last name?", "Last Name", T.TEXT,
             ["last name", "surname", "family name", "उपनाम", "कुलनाम", "apellido", "apellidos", "nom de famille",
              "nachname", "familienname", "姓", "성", "اسم العائلة", "фамилия", "sobrenome", "apelido"]),
    Template("father_name", "What is the applicant's father's name?", "Father's Name", T.TEXT,
             ["father's name", "fathers name", "father name", "name of father", "पिता का नाम", "पिता", "nombre del padre",
              "nom du père", "父亲姓名", "اسم الأب", "имя отца"]),
    Template("mother_name", "What is the applicant's mother's name?", "Mother's Name", T.TEXT,
             ["mother's name", "mothers name", "mother name", "माता का नाम", "nombre de la madre", "nom de la mère",
              "母亲姓名", "اسم الأم"]),
    Template("spouse_name", "What is the applicant's spouse's name?", "Spouse's Name", T.TEXT,
             ["spouse name", "spouse's name", "husband's name", "wife's name", "पति का नाम", "पत्नी का नाम",
              "nombre del cónyuge"]),
    Template("date_of_birth", "What is the applicant's date of birth?", "Date of Birth", T.DATE,
             ["date of birth", "dob", "d.o.b", "d.o.b.", "birth date", "birthdate", "born on", "जन्म तिथि", "जन्म दिनांक",
              "जन्मतिथि", "fecha de nacimiento", "date de naissance", "geburtsdatum", "出生日期", "生年月日", "생년월일",
              "تاريخ الميلاد", "дата рождения", "data de nascimento", "জন্ম তারিখ", "பிறந்த தேதி", "పుట్టిన తేదీ",
              "જન્મ તારીખ", "ਜਨਮ ਮਿਤੀ"]),
    Template("age", "What is the applicant's age?", "Age", T.NUMBER,
             ["age", "age (years)", "आयु", "उम्र", "edad", "âge", "alter", "年龄", "年齢", "나이", "العمر", "возраст",
              "idade", "বয়স", "வயது"]),
    Template("gender", "What is the applicant's gender?", "Gender", T.MULTIPLE_CHOICE,
             ["gender", "sex", "लिंग", "género", "sexo", "sexe", "geschlecht", "性别", "性別", "성별", "الجنس", "пол"],
             options=["Male", "Female", "Other"]),
    Template("marital_status", "What is the applicant's marital status?", "Marital Status", T.MULTIPLE_CHOICE,
             ["marital status", "वैवाहिक स्थिति", "estado civil", "état civil", "familienstand", "婚姻状况", "الحالة الاجتماعية"],
             options=["Single", "Married", "Divorced", "Widowed"]),
    Template("nationality", "What is the applicant's nationality?", "Nationality", T.TEXT,
             ["nationality", "citizenship", "राष्ट्रीयता", "नागरिकता", "nacionalidad", "nationalité", "staatsangehörigkeit",
              "国籍", "الجنسية", "гражданство", "nacionalidade"]),
    Template("address", "What is the applicant's address?", "Address", T.TEXT,
             ["address", "residential address", "permanent address", "present address", "current address", "home address",
              "mailing address", "पता", "स्थायी पता", "वर्तमान पता", "dirección", "domicilio", "adresse", "anschrift",
              "地址", "住所", "주소", "العنوان", "адрес", "endereço", "ঠিকানা", "முகவரி", "చిరునామా", "સરનામું"]),
    Template("city", "Which city does the applicant live in?", "City", T.TEXT,
             ["city", "town", "city/town", "शहर", "ciudad", "ville", "stadt", "城市", "市", "도시", "المدينة", "город", "cidade"]),
    Template("state", "Which state or province?", "State / Province", T.TEXT,
             ["state", "province", "state/province", "region", "राज्य", "estado", "provincia", "état", "bundesland", "省",
              "州", "الولاية", "область"]),
    Template("district", "Which district?", "District", T.TEXT, ["district", "जिला", "ज़िला", "distrito", "区", "地区"]),
    Template("postal_code", "What is the postal / ZIP code?", "Postal Code", T.NUMBER,
             ["zip", "zip code", "postal code", "postcode", "pin", "pin code", "pincode", "पिन कोड", "पिनकोड",
              "código postal", "code postal", "postleitzahl", "plz", "邮政编码", "郵便番号", "우편번호", "الرمز البريدي",
              "почтовый индекс", "cep"]),
    Template("country", "Which country?", "Country", T.TEXT,
             ["country", "देश", "país", "pays", "land", "国家", "国", "국가", "البلد", "страна"]),
    Template("phone", "What is the applicant's phone number?", "Phone Number", T.NUMBER,
             ["phone", "phone number", "telephone", "tel", "tel.", "contact number", "contact no", "contact no.",
              "फ़ोन", "फोन", "फोन नंबर", "दूरभाष", "teléfono", "téléphone", "telefon", "电话", "電話番号", "전화번호",
              "الهاتف", "рقم الهاتف", "телефон", "telefone"]),
    Template("mobile", "What is the applicant's mobile number?", "Mobile Number", T.NUMBER,
             ["mobile", "mobile number", "mobile no", "mobile no.", "cell", "cell phone", "cellphone", "मोबाइल",
              "मोबाइल नंबर", "móvil", "celular", "portable", "handy", "手机", "携帯電話", "휴대폰", "الجوال", "мобильный"]),
    Template("email", "What is the applicant's email address?", "Email", T.TEXT,
             ["email", "e-mail", "email address", "e-mail address", "ईमेल", "correo", "correo electrónico", "courriel",
              "电子邮件", "邮箱", "メール", "이메일", "البريد الإلكتروني", "электронная почта"]),
    Template("occupation", "What is the applicant's occupation?", "Occupation", T.TEXT,
             ["occupation", "profession", "job title", "व्यवसाय", "पेशा", "ocupación", "profesión", "beruf", "职业", "職業",
              "직업", "المهنة", "профессия"]),
    Template("designation", "What is the applicant's designation?", "Designation", T.TEXT,
             ["designation", "position", "title", "पदनाम", "पद", "cargo", "poste", "职位", "役職"]),
    Template("employer", "What is the name of the employer / company?", "Company", T.TEXT,
             ["company", "company name", "employer", "organization", "organisation", "firm", "कंपनी", "नियोक्ता", "empresa",
              "entreprise", "公司", "会社", "회사", "الشركة", "компания"]),
    Template("tax_id", "What is the tax identification number?", "Tax ID", T.TEXT,
             ["gst no", "gst no.", "gstin", "gst number", "vat no", "vat number", "tin", "tax id", "tax number",
              "जीएसटी नंबर", "nif", "cif", "steuernummer", "税号"]),
    Template("department", "Which department?", "Department", T.TEXT, ["department", "dept", "विभाग", "departamento", "部门", "部署"]),
    Template("employee_id", "What is the employee ID?", "Employee ID", T.TEXT,
             ["employee id", "emp id", "employee number", "staff id", "कर्मचारी आईडी", "id de empleado", "员工编号"]),
    Template("id_number", "What is the applicant's ID number?", "ID Number", T.TEXT,
             ["id", "id no", "id no.", "id number", "identification number", "पहचान संख्या", "número de identificación",
              "numéro d'identification", "ausweisnummer", "身份证号", "رقم الهوية"]),
    Template("passport", "What is the applicant's passport number?", "Passport Number", T.TEXT,
             ["passport", "passport no", "passport no.", "passport number", "पासपोर्ट", "पासपोर्ट संख्या", "pasaporte",
              "passeport", "reisepass", "护照号码", "パスポート番号", "رقم جواز السفر"]),
    Template("aadhaar", "What is the applicant's Aadhaar number?", "Aadhaar Number", T.NUMBER,
             ["aadhaar", "aadhar", "aadhaar no", "aadhaar number", "आधार", "आधार संख्या", "आधार नंबर"]),
    Template("pan", "What is the applicant's PAN?", "PAN", T.TEXT, ["pan", "pan no", "pan number", "पैन", "पैन नंबर"]),
    Template("ssn", "What is the applicant's Social Security Number?", "SSN", T.NUMBER,
             ["ssn", "social security number", "social security no"]),
    Template("blood_group", "What is the applicant's blood group?", "Blood Group", T.MULTIPLE_CHOICE,
             ["blood group", "blood type", "रक्त समूह", "grupo sanguíneo", "groupe sanguin", "blutgruppe", "血型", "血液型"],
             options=["A+", "A-", "B+", "B-", "AB+", "AB-", "O+", "O-"]),
    Template("religion", "What is the applicant's religion?", "Religion", T.TEXT, ["religion", "धर्म", "religión", "宗教"]),
    Template("category", "Which category does the applicant belong to?", "Category", T.MULTIPLE_CHOICE,
             ["category", "caste", "श्रेणी", "वर्ग", "categoría"]),
    Template("education", "What is the applicant's highest qualification?", "Qualification", T.TEXT,
             ["education", "qualification", "educational qualification", "highest qualification", "degree", "शिक्षा",
              "योग्यता", "शैक्षणिक योग्यता", "educación", "titulación", "diplôme", "ausbildung", "学历", "学歴", "학력"]),
    Template("institution", "Which school / college / university?", "Institution", T.TEXT,
             ["school", "college", "university", "institution", "institute", "विद्यालय", "महाविद्यालय", "विश्वविद्यालय",
              "escuela", "universidad", "école", "université", "学校", "大学"]),
    Template("bank_name", "What is the bank name?", "Bank Name", T.TEXT, ["bank", "bank name", "बैंक", "बैंक का नाम", "banco", "banque", "银行"]),
    Template("account_number", "What is the bank account number?", "Account Number", T.NUMBER,
             ["account number", "account no", "account no.", "a/c no", "a/c no.", "acct no", "खाता संख्या", "खाता नंबर",
              "número de cuenta", "numéro de compte", "kontonummer", "账号", "口座番号", "رقم الحساب"]),
    Template("ifsc", "What is the IFSC code?", "IFSC Code", T.TEXT, ["ifsc", "ifsc code", "आईएफएससी", "आईएफएससी कोड"]),
    Template("branch", "Which bank branch?", "Branch", T.TEXT, ["branch", "branch name", "शाखा", "sucursal", "agence", "支行"]),
    Template("date", "What is the date?", "Date", T.DATE,
             ["date", "dated", "date:", "दिनांक", "तारीख", "तिथि", "fecha", "date", "datum", "日期", "日付", "날짜", "التاريخ",
              "дата", "data", "তারিখ", "தேதி", "తేదీ", "તારીખ", "ਮਿਤੀ"]),
    Template("start_date", "What is the start date?", "Start Date", T.DATE,
             ["start date", "from", "from date", "date from", "valid from", "date of joining", "joining date", "आरंभ तिथि",
              "से", "fecha de inicio", "date de début", "开始日期"]),
    Template("end_date", "What is the end date?", "End Date", T.DATE,
             ["end date", "to", "to date", "date to", "valid till", "valid until", "expiry date", "expiry", "date of expiry",
              "समाप्ति तिथि", "तक", "fecha de fin", "date de fin", "结束日期", "有効期限"]),
    Template("place", "What is the place?", "Place", T.TEXT, ["place", "स्थान", "lugar", "lieu", "ort", "地点", "場所"]),
    Template("signature", "Signature of the applicant", "Signature", T.SIGNATURE,
             ["signature", "sign", "signature of applicant", "applicant's signature", "signed", "हस्ताक्षर", "आवेदक के हस्ताक्षर",
              "firma", "signature du demandeur", "unterschrift", "签名", "署名", "서명", "التوقيع", "подпись", "assinatura",
              "স্বাক্ষর", "கையொப்பம்", "సంతకం", "સહી", "ਦਸਤਖਤ"]),
    Template("thumb", "Thumb impression of the applicant", "Thumb Impression", T.SIGNATURE,
             ["thumb impression", "thumb", "अंगूठे का निशान"]),
    Template("photo", "Passport-size photograph", "Photograph", T.SIGNATURE, ["photo", "photograph", "affix photo", "फोटो", "फोटोग्राफ"]),
    Template("amount", "What is the amount?", "Amount", T.NUMBER,
             ["amount", "amt", "amount (rs)", "amount (rs.)", "राशि", "रकम", "importe", "monto", "montant", "betrag",
              "金额", "金額", "금액", "المبلغ", "сумма", "valor"]),
    Template("total", "What is the total amount?", "Total", T.NUMBER,
             ["total", "total amount", "grand total", "sum", "कुल", "कुल राशि", "योग", "total general", "montant total",
              "gesamt", "gesamtbetrag", "总计", "合計", "합계", "المجموع", "итого"]),
    Template("subtotal", "What is the subtotal?", "Subtotal", T.NUMBER, ["subtotal", "sub total", "sub-total", "उप-योग"]),
    Template("tax", "What is the tax amount?", "Tax", T.NUMBER, ["tax", "gst", "vat", "कर", "जीएसटी", "impuesto", "iva", "taxe", "tva", "steuer", "税"]),
    Template("quantity", "What is the quantity?", "Quantity", T.NUMBER, ["quantity", "qty", "qty.", "मात्रा", "cantidad", "quantité", "menge", "数量"]),
    Template("price", "What is the price?", "Price", T.NUMBER, ["price", "unit price", "rate", "मूल्य", "दर", "precio", "prix", "preis", "价格", "単価"]),
    Template("invoice_number", "What is the invoice number?", "Invoice Number", T.TEXT,
             ["invoice", "invoice no", "invoice no.", "invoice number", "bill no", "bill no.", "bill number", "चालान संख्या",
              "बिल नंबर", "factura", "número de factura", "facture", "rechnungsnummer", "发票号", "請求書番号"]),
    Template("order_number", "What is the order number?", "Order Number", T.TEXT, ["order no", "order no.", "order number", "po number", "आदेश संख्या", "número de pedido"]),
    Template("reference", "What is the reference number?", "Reference Number", T.TEXT,
             ["ref", "ref no", "ref no.", "reference", "reference no", "reference number", "application no", "application no.",
              "application number", "registration no", "registration number", "संदर्भ संख्या", "आवेदन संख्या", "पंजीकरण संख्या",
              "referencia", "référence", "参考编号", "申请编号"]),
    Template("description", "What is the description?", "Description", T.TEXT, ["description", "particulars", "details", "विवरण", "descripción", "désignation", "beschreibung", "描述", "内容"]),
    Template("remarks", "Any remarks?", "Remarks", T.TEXT, ["remarks", "comments", "notes", "note", "टिप्पणी", "observaciones", "remarques", "bemerkungen", "备注", "備考"]),
    Template("reason", "What is the reason / purpose?", "Reason", T.TEXT, ["reason", "purpose", "purpose of visit", "कारण", "उद्देश्य", "motivo", "raison", "grund", "原因", "目的"]),
    Template("emergency_contact", "Who is the emergency contact?", "Emergency Contact", T.TEXT, ["emergency contact", "emergency contact name", "आपातकालीन संपर्क", "contacto de emergencia"]),
    Template("relationship", "What is the relationship?", "Relationship", T.TEXT, ["relationship", "relation", "संबंध", "रिश्ता", "parentesco", "lien", "关系", "続柄"]),
    Template("height", "What is the applicant's height?", "Height", T.NUMBER, ["height", "ऊंचाई", "कद", "altura", "taille", "größe", "身高", "身長"]),
    Template("weight", "What is the applicant's weight?", "Weight", T.NUMBER, ["weight", "वजन", "भार", "peso", "poids", "gewicht", "体重"]),
    Template("allergies", "Does the patient have any allergies?", "Allergies", T.TEXT, ["allergies", "allergy", "एलर्जी", "alergias", "allergies", "过敏"]),
    Template("medications", "What medications is the patient taking?", "Current Medications", T.TEXT, ["medications", "current medications", "medicines", "दवाइयाँ", "medicamentos", "médicaments"]),
    Template("diagnosis", "What is the diagnosis?", "Diagnosis", T.TEXT, ["diagnosis", "निदान", "diagnóstico", "diagnostic", "诊断"]),
    Template("insurance", "What is the insurance provider / policy?", "Insurance", T.TEXT, ["insurance", "insurance provider", "policy no", "policy number", "बीमा", "seguro", "assurance", "保险"]),
    Template("vehicle_number", "What is the vehicle registration number?", "Vehicle Number", T.TEXT, ["vehicle no", "vehicle no.", "vehicle number", "registration no.", "वाहन संख्या", "matrícula", "immatriculation"]),
    Template("license", "What is the licence number?", "Licence Number", T.TEXT, ["license", "licence", "license no", "licence no", "driving license", "driving licence", "dl no", "लाइसेंस", "लाइसेंस नंबर", "licencia", "permis"]),
    Template("website", "What is the website?", "Website", T.TEXT, ["website", "web", "url", "वेबसाइट", "sitio web", "site web"]),
    Template("yes_no", "Yes or no?", "Yes / No", T.CHECKBOX, ["yes", "no", "yes/no", "y/n", "हाँ", "नहीं", "sí", "oui", "non", "ja", "nein", "是", "否", "はい", "いいえ", "نعم", "لا"]),
    Template("declaration", "Does the applicant agree to the declaration?", "Declaration", T.CHECKBOX, ["declaration", "i agree", "i declare", "i hereby declare", "घोषणा", "declaración", "déclaration", "erklärung"]),
]

_BY_KEY = {t.key: t for t in TEMPLATES}
_STRIP_RE = re.compile(r"[\s:：\-–—_.*#()\[\]\"'“”‘’/\\,;|]+")
_NUM_PREFIX_RE = re.compile(r"^\s*(\(?[0-9ivxIVX]{1,3}[.)]|[a-zA-Z][.)]|[•·●■□▪-])\s*")
_TRAILING_RE = re.compile(r"[\s:：\-–—_.*/\\]+$")


def normalize_label(label: str) -> str:
    s = unicodedata.normalize("NFKC", label).strip()
    s = _NUM_PREFIX_RE.sub("", s)
    s = _TRAILING_RE.sub("", s)
    s = s.lower()
    s = re.sub(r"\s+", " ", s)
    s = s.replace("’", "'")
    return s.strip(" :-_.")


_ALIAS_INDEX: dict[str, Template] = {}
for _t in TEMPLATES:
    for _a in [_t.label] + _t.aliases:
        _ALIAS_INDEX.setdefault(normalize_label(_a), _t)


def _tokens(s: str) -> set[str]:
    return {w for w in re.split(r"[\s/]+", s) if w and (len(w) > 1 or not w.isascii())}


_CJK_RE = re.compile(r"^[\u3000-\u9fff\uac00-\ud7af\uff00-\uffef]+$")


def _contains_word(alias: str, label: str) -> bool:
    """Whole-word containment (plain substring for space-less CJK aliases)."""
    if _CJK_RE.match(alias):
        return alias in label
    return re.search(r"(?<![\w\-])" + re.escape(alias) + r"(?![\w\-])", label) is not None


def match_template(label: str) -> tuple[Template | None, float]:
    """Return the best template and a match strength in [0, 1]."""
    norm = normalize_label(label)
    if not norm:
        return None, 0.0
    if norm in _ALIAS_INDEX:
        return _ALIAS_INDEX[norm], 1.0
    # Strip parenthetical hints, e.g. "Date of Birth (DD/MM/YYYY)".
    stripped = re.sub(r"\(.*?\)", "", norm).strip()
    if stripped and stripped in _ALIAS_INDEX:
        return _ALIAS_INDEX[stripped], 0.95
    best: Template | None = None
    best_score = 0.0
    lab_toks = _tokens(stripped or norm)
    for alias, t in _ALIAS_INDEX.items():
        if len(alias) < 3:
            continue
        # containment (whole words only)
        if _contains_word(alias, norm):
            s = 0.6 + 0.35 * len(alias) / max(len(norm), 1)
            if len(norm) > 3 * len(alias) + 6:
                s = min(s, 0.3)  # a sentence that merely mentions the alias
        elif len(norm) >= 4 and _contains_word(norm, alias):
            s = 0.5 + 0.3 * len(norm) / len(alias)
        else:
            a_toks = _tokens(alias)
            if not a_toks or not lab_toks:
                continue
            inter = len(a_toks & lab_toks)
            if inter == 0:
                continue
            s = 0.45 * inter / len(a_toks | lab_toks) + 0.3 * inter / len(a_toks)
        if s > best_score:
            best, best_score = t, s
    if best_score < 0.45:
        return None, best_score
    return best, round(best_score, 3)


def infer_type(label: str, value: str = "", has_checkbox: bool = False) -> FieldType:
    """Cheap regex type inference for labels without a template."""
    if has_checkbox or g.has_checkbox_glyph(label) or g.has_checkbox_glyph(value):
        return FieldType.CHECKBOX
    low = normalize_label(label)
    if g.DATE_HINT_RE.search(label) or re.search(r"\b(date|dated|day|month|year|when)\b|दिनांक|तारीख|तिथि|fecha|日期|日付", low):
        return FieldType.DATE
    if re.search(r"\b(no|no\.|number|num|amount|total|qty|quantity|count|age|price|rate|code|pin|zip|phone|mobile|tel)\b|संख्या|नंबर|राशि|मात्रा|número|数量|金额", low):
        return FieldType.NUMBER
    if re.search(r"\b(sign|signature|signed|seal|stamp)\b|हस्ताक्षर|firma|签名", low):
        return FieldType.SIGNATURE
    if value and re.fullmatch(r"[\d\s,./-]+", value) and re.search(r"\d", value):
        if re.search(r"\d{1,4}[/.-]\d{1,2}[/.-]\d{1,4}", value):
            return FieldType.DATE
        return FieldType.NUMBER
    return FieldType.TEXT


def synthesize_question(label: str, value: str = "", has_checkbox: bool = False) -> dict:
    """Return {question, label_en, type, template_key, match, options}."""
    t, strength = match_template(label)
    if t is not None and strength >= 0.45:
        ftype = t.type
        if has_checkbox and ftype not in (FieldType.CHECKBOX, FieldType.MULTIPLE_CHOICE):
            ftype = FieldType.CHECKBOX
        return {"question": t.question, "label_en": t.label, "type": ftype, "template_key": t.key,
                "match": strength, "options": list(t.options)}
    clean = normalize_label(label)
    pretty = " ".join(w.capitalize() if w.isascii() else w for w in clean.split()) or label.strip()
    ftype = infer_type(label, value, has_checkbox)
    if ftype == FieldType.CHECKBOX:
        q = f"Is '{pretty}' checked?"
    elif ftype == FieldType.SIGNATURE:
        q = f"{pretty} (signature)"
    else:
        q = f"What is the value for '{pretty}'?"
    return {"question": q, "label_en": pretty, "type": ftype, "template_key": None, "match": strength, "options": []}


def template_by_key(key: str) -> Template | None:
    return _BY_KEY.get(key)
