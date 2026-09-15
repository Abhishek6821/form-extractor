"""Generate the eval set: multilingual form PDFs + non-form PDFs with ground truth.

Each form spec is a list of rows; a row is a list of cells (label, kind):
  kind = "line"  -> label followed by a long underline blank
         "colon" -> "Label:" followed by blank space
         "box"   -> checkbox glyph + label
         "value" -> label: pre-filled value
Junk rows (title, instructions, footer, page number) are added automatically
and recorded so pruning precision can be measured.

Run:  python eval/make_fixtures.py
"""
from __future__ import annotations

import json
import os
import random
import sys

import pymupdf as fitz

HERE = os.path.dirname(os.path.abspath(__file__))
FORMS = os.path.join(HERE, "fixtures", "forms")
NONF = os.path.join(HERE, "fixtures", "non_forms")
FONT = "/System/Library/Fonts/Supplemental/Arial Unicode.ttf"
if not os.path.exists(FONT):
    FONT = None  # falls back to built-in fonts (Latin only)

W, H = 595, 842

FORM_SPECS: dict[str, dict] = {
    "en_job_application": {"title": "EMPLOYMENT APPLICATION FORM", "lang": "en", "rows": [
        [("Full Name", "colon"), ("Date of Birth (DD/MM/YYYY)", "colon")],
        [("Father's Name", "line")],
        [("Permanent Address", "line")],
        [("City", "colon"), ("State", "colon"), ("PIN Code", "colon")],
        [("Mobile No.", "colon"), ("Email", "colon")],
        [("Gender", "box3:Male,Female,Other")],
        [("Highest Qualification", "line")],
        [("Designation Applied For", "colon"), ("Expected Salary", "colon")],
        [("Date", "colon"), ("Signature of Applicant", "line")],
    ]},
    "hi_bank_form": {"title": "बैंक खाता खोलने का फॉर्म", "lang": "hi", "rows": [
        [("नाम", "colon"), ("जन्म तिथि", "colon")],
        [("पिता का नाम", "line")],
        [("पता", "line")],
        [("शहर", "colon"), ("राज्य", "colon"), ("पिन कोड", "colon")],
        [("मोबाइल नंबर", "colon"), ("ईमेल", "colon")],
        [("आधार संख्या", "colon"), ("पैन नंबर", "colon")],
        [("खाता संख्या", "line")],
        [("लिंग", "box3:पुरुष,महिला,अन्य")],
        [("दिनांक", "colon"), ("हस्ताक्षर", "line")],
    ]},
    "es_medical_intake": {"title": "FORMULARIO DE ADMISIÓN MÉDICA", "lang": "es", "rows": [
        [("Nombre completo", "colon"), ("Fecha de nacimiento", "colon")],
        [("Dirección", "line")],
        [("Ciudad", "colon"), ("Código postal", "colon")],
        [("Teléfono", "colon"), ("Correo electrónico", "colon")],
        [("Grupo sanguíneo", "colon"), ("Peso", "colon"), ("Altura", "colon")],
        [("Alergias", "line")],
        [("Medicamentos", "line")],
        [("Contacto de emergencia", "colon"), ("Parentesco", "colon")],
        [("Fecha", "colon"), ("Firma", "line")],
    ]},
    "fr_registration": {"title": "FORMULAIRE D'INSCRIPTION", "lang": "fr", "rows": [
        [("Nom de famille", "colon"), ("Prénom", "colon")],
        [("Date de naissance", "colon"), ("Nationalité", "colon")],
        [("Adresse", "line")],
        [("Ville", "colon"), ("Code postal", "colon"), ("Pays", "colon")],
        [("Téléphone", "colon"), ("Courriel", "colon")],
        [("Profession", "line")],
        [("État civil", "box3:Célibataire,Marié(e),Divorcé(e)")],
        [("Date", "colon"), ("Signature", "line")],
    ]},
    "de_antrag": {"title": "ANTRAG AUF MITGLIEDSCHAFT", "lang": "de", "rows": [
        [("Vorname", "colon"), ("Nachname", "colon")],
        [("Geburtsdatum", "colon"), ("Staatsangehörigkeit", "colon")],
        [("Anschrift", "line")],
        [("PLZ", "colon"), ("Stadt", "colon")],
        [("Telefon", "colon"), ("E-Mail", "colon")],
        [("Beruf", "line")],
        [("Kontonummer", "colon"), ("Bank", "colon")],
        [("Datum", "colon"), ("Unterschrift", "line")],
    ]},
    "zh_application": {"title": "申请表", "lang": "zh", "rows": [
        [("姓名", "colon"), ("出生日期", "colon")],
        [("性别", "box3:男,女,其他")],
        [("地址", "line")],
        [("城市", "colon"), ("邮政编码", "colon")],
        [("电话", "colon"), ("电子邮件", "colon")],
        [("职业", "line")],
        [("公司", "line")],
        [("日期", "colon"), ("签名", "line")],
    ]},
    "ja_form": {"title": "入会申込書", "lang": "ja", "rows": [
        [("氏名", "colon"), ("生年月日", "colon")],
        [("住所", "line")],
        [("郵便番号", "colon"), ("電話番号", "colon")],
        [("メール", "colon")],
        [("職業", "line")],
        [("日付", "colon"), ("署名", "line")],
    ]},
    "ar_form": {"title": "نموذج طلب", "lang": "ar", "rows": [
        [("الاسم الكامل", "colon"), ("تاريخ الميلاد", "colon")],
        [("العنوان", "line")],
        [("المدينة", "colon"), ("البلد", "colon")],
        [("الهاتف", "colon"), ("البريد الإلكتروني", "colon")],
        [("المهنة", "line")],
        [("التاريخ", "colon"), ("التوقيع", "line")],
    ]},
    "en_invoice": {"title": "TAX INVOICE", "lang": "en", "rows": [
        [("Invoice No.", "value:INV-2024-0117"), ("Date", "value:14/03/2024")],
        [("Bill To", "line")],
        [("Address", "line")],
        [("GST No.", "colon"), ("PAN", "colon")],
        [("Description", "colon"), ("Quantity", "colon"), ("Rate", "colon"), ("Amount", "colon")],
        [("Subtotal", "value:12,500.00"), ("Tax", "value:2,250.00")],
        [("Total", "value:14,750.00")],
        [("Authorised Signature", "line")],
    ]},
    "en_survey": {"title": "CUSTOMER SATISFACTION SURVEY", "lang": "en", "rows": [
        [("Name", "colon"), ("Age", "colon")],
        [("Email", "colon")],
        [("How did you hear about us?", "box3:Friend,Online,Advertisement")],
        [("Would you recommend us?", "box3:Yes,No,Maybe")],
        [("Overall rating", "box3:Excellent,Good,Poor")],
        [("Comments", "line")],
        [("Date", "colon"), ("Signature", "line")],
    ]},
    "ru_pt_mixed": {"title": "АНКЕТА / FORMULÁRIO", "lang": "ru", "rows": [
        [("ФИО", "colon"), ("Дата рождения", "colon")],
        [("Адрес", "line")],
        [("Город", "colon"), ("Страна", "colon")],
        [("Телефон", "colon"), ("Электронная почта", "colon")],
        [("Nome completo", "colon"), ("Data de nascimento", "colon")],
        [("Endereço", "line")],
        [("Telefone", "colon"), ("Assinatura", "line")],
    ]},
    "en_school_admission": {"title": "SCHOOL ADMISSION FORM", "lang": "en", "rows": [
        [("Name of Student", "line")],
        [("Date of Birth", "colon"), ("Blood Group", "colon"), ("Gender", "box3:Male,Female,Other")],
        [("Father's Name", "colon"), ("Occupation", "colon")],
        [("Mother's Name", "colon"), ("Occupation", "colon")],
        [("Residential Address", "line")],
        [("Contact Number", "colon"), ("Emergency Contact", "colon")],
        [("Previous School", "line")],
        [("Class Applied For", "colon"), ("Religion", "colon"), ("Category", "colon")],
        [("Nationality", "colon"), ("Aadhaar No.", "colon")],
        [("Place", "colon"), ("Date", "colon")],
        [("Signature of Parent", "line")],
    ]},
    "ta_te_form": {"title": "விண்ணப்பப் படிவம்", "lang": "ta", "rows": [
        [("பெயர்", "colon"), ("பிறந்த தேதி", "colon")],
        [("முகவரி", "line")],
        [("పేరు", "colon"), ("పుట్టిన తేదీ", "colon")],
        [("చిరునామా", "line")],
        [("தேதி", "colon"), ("கையொப்பம்", "line")],
    ]},
}

INSTRUCTIONS = {
    "en": "Please fill in BLOCK LETTERS. Attach two passport-size photographs. Use black ink only.",
    "hi": "कृपया फॉर्म को स्पष्ट अक्षरों में भरें। दो पासपोर्ट आकार के फोटो संलग्न करें।",
    "es": "Por favor rellene con letras mayúsculas. Adjunte una copia de su identificación.",
    "fr": "Veuillez remplir en lettres capitales. Joindre une copie de votre pièce d'identité.",
    "de": "Bitte in Druckbuchstaben ausfüllen. Kopie des Ausweises beilegen.",
    "zh": "请用正楷填写本表格。请附上两张护照照片。",
    "ja": "楷書でご記入ください。写真を二枚添付してください。",
    "ar": "يرجى تعبئة النموذج بخط واضح. أرفق نسخة من الهوية.",
    "ru": "Пожалуйста, заполните печатными буквами. Приложите копию паспорта.",
    "ta": "தயவுசெய்து தெளிவாக நிரப்பவும். இரண்டு புகைப்படங்களை இணைக்கவும்.",
}
FOOTERS = {
    "en": "For office use only  |  Form No. A-17  |  www.example.org",
    "hi": "केवल कार्यालय उपयोग के लिए  |  फॉर्म संख्या ए-17",
    "es": "Solo para uso oficial  |  Formulario N.º A-17",
    "fr": "Réservé à l'administration  |  Formulaire n° A-17",
    "de": "Nur für den Dienstgebrauch  |  Formular Nr. A-17",
    "zh": "仅供办公室使用  |  表格编号 A-17",
    "ja": "事務局記入欄  |  様式 A-17",
    "ar": "للاستخدام الرسمي فقط  |  نموذج رقم A-17",
    "ru": "Только для служебного пользования  |  Форма № А-17",
    "ta": "அலுவலக பயன்பாட்டிற்கு மட்டும்  |  படிவம் எண் A-17",
}

NON_FORMS: dict[str, tuple[str, str]] = {
    "en_essay": ("The Value of Public Libraries", """Public libraries are among the few remaining institutions that welcome everyone without asking for anything in return. They lend books, of course, but they also provide internet access, quiet study spaces, children's programs, job-search help and a place to be warm in winter. In many towns the library is the only public building open on a Saturday afternoon.
Critics sometimes argue that the internet has made libraries obsolete. The opposite is true. As information has become abundant, the skills of evaluating it have become scarce, and librarians are trained precisely in those skills. A good reference librarian can save a student days of confused searching.
Funding, however, remains fragile. Library budgets are often the first to be trimmed when a city council needs savings, because the damage is slow and invisible. Yet the cost of a library is tiny compared with the value it creates for the people who rely on it most."""),
    "en_letter": ("Letter to the Editor", """Dear Editor,
I am writing in response to your article of 3 March about the proposed closure of the Riverside footbridge. As a resident who crosses it twice daily, I can attest that it is used by hundreds of schoolchildren, commuters and elderly residents who would otherwise face a forty-minute detour along a busy road.
The council's own survey, published last year, found that the bridge was structurally sound and needed only routine maintenance. Closing it to save a modest annual sum would be a false economy.
I urge the council to reconsider and to consult the people who actually use the bridge before making a decision.
Yours faithfully,
A concerned resident"""),
    "hi_article": ("शिक्षा का महत्व", """शिक्षा मनुष्य के जीवन का सबसे महत्वपूर्ण आधार है। यह न केवल ज्ञान प्रदान करती है बल्कि व्यक्ति के चरित्र का निर्माण भी करती है। एक शिक्षित व्यक्ति समाज में अपने अधिकारों और कर्तव्यों को समझता है और देश की प्रगति में योगदान देता है।
आज के युग में शिक्षा का स्वरूप बदल गया है। कंप्यूटर और इंटरनेट ने सीखने के नए द्वार खोल दिए हैं। लेकिन इसके साथ ही यह भी आवश्यक है कि हम अपनी संस्कृति और मूल्यों को न भूलें।
सरकार को चाहिए कि वह गाँवों में अच्छे विद्यालय खोले ताकि हर बच्चे को समान अवसर मिल सके।"""),
    "es_news": ("Nueva línea de metro abrirá en primavera", """La ciudad inaugurará la nueva línea de metro a finales de abril, según confirmó ayer el ayuntamiento. La línea conectará el barrio universitario con el centro histórico en apenas doce minutos y contará con ocho estaciones, todas accesibles para personas con movilidad reducida.
Las obras, que comenzaron hace cuatro años, sufrieron varios retrasos por el hallazgo de restos arqueológicos bajo la plaza mayor. Los arqueólogos documentaron una calzada romana y varias viviendas medievales, que se exhibirán en la propia estación.
El alcalde destacó que el nuevo trazado reducirá el tráfico en el centro y mejorará la calidad del aire."""),
    "fr_recipe": ("Tarte aux pommes traditionnelle", """Préchauffez le four à 180 degrés. Étalez la pâte brisée dans un moule beurré et piquez le fond à la fourchette. Épluchez six pommes, coupez-les en fines lamelles et disposez-les en rosace sur la pâte.
Mélangez deux œufs avec cent grammes de sucre et vingt centilitres de crème, puis versez ce mélange sur les pommes. Enfournez pendant quarante minutes, jusqu'à ce que la tarte soit bien dorée.
Laissez tiédir avant de servir, idéalement avec une boule de glace à la vanille."""),
    "zh_story": ("小城的春天", """春天来了，小城的河边开满了桃花。孩子们放学后总喜欢在河堤上奔跑，老人们则坐在长椅上晒太阳，谈论着过去的岁月。
城里的老茶馆依旧热闹。每天清晨，第一壶茶泡开的时候，整条街都能闻到茶香。茶馆的老板已经七十多岁了，他说这家店是他父亲留下的，他会一直开下去。
傍晚时分，夕阳把河水染成金色，远处传来悠扬的笛声。"""),
    "en_receipt": ("Thank you for shopping with us", """GREENLEAF GROCERY
12 Market Street
Organic bananas 1.2 kg 2.88
Whole milk 2 L 3.10
Sourdough loaf 4.50
Free-range eggs 12 5.20
Olive oil 500 ml 8.95
Dish soap 2.40
Subtotal 27.03
Sales tax 2.16
TOTAL 29.19
Paid by card **** 4821
Items 6
Thank you for shopping with us. Please keep this receipt for returns within 30 days."""),
    "de_bericht": ("Jahresbericht des Vereins", """Das vergangene Jahr war für unseren Verein ein erfolgreiches. Die Mitgliederzahl stieg um zwölf Prozent, und wir konnten drei neue Trainingsgruppen für Kinder und Jugendliche einrichten. Besonders erfreulich war die Teilnahme unserer Jugendmannschaft am Landesturnier, bei dem sie den zweiten Platz erreichte.
Die Finanzen sind stabil. Dank großzügiger Spenden und der Unterstützung der Gemeinde konnten wir die Sanierung des Vereinsheims abschließen, ohne Schulden aufzunehmen.
Für das kommende Jahr planen wir ein Sommerfest und die Anschaffung neuer Sportgeräte."""),
    "ja_essay": ("読書の楽しみ", """読書は私にとって最も大切な時間です。本を開くと、遠い国や過去の時代へ旅をすることができます。登場人物の喜びや悲しみを共に感じることで、自分の世界が少しずつ広がっていくのを感じます。
最近は電子書籍も増えましたが、私は紙の本の手触りや匂いが好きです。古本屋で偶然出会った一冊が、人生を変えることもあります。
忙しい毎日の中でも、一日に三十分は本を読む時間を作るようにしています。"""),
    "ar_article": ("أهمية القراءة", """القراءة هي غذاء العقل وسبيل الإنسان إلى المعرفة. من خلال الكتب نتعرف على ثقافات الشعوب وتجارب الأمم عبر التاريخ. وقد كان العرب قديماً يقولون إن الكتاب خير جليس.
في عصرنا الحاضر تغيرت وسائل القراءة، فظهرت الكتب الإلكترونية والمكتبات الرقمية. لكن جوهر القراءة لم يتغير، فهي ما زالت رحلة في عالم الأفكار.
ينبغي على الأسرة أن تغرس حب القراءة في نفوس الأطفال منذ الصغر."""),
    "en_memo": ("Internal memo", """To all staff. Following last week's fire drill, facilities have asked us to remind everyone that the east stairwell must be kept clear at all times. Boxes left on the landing during the drill delayed the evacuation of the third floor by almost two minutes.
Please also note that the car park will be resurfaced on the weekend of the 20th. Vehicles left overnight on Friday will be towed at the owner's expense.
Finally, congratulations to the analytics team, who shipped the new reporting dashboard ahead of schedule."""),
    "ru_story": ("Зимнее утро", """Зимнее утро в деревне начинается с тишины. Снег покрывает крыши домов и ветви деревьев, и только дым из труб напоминает о том, что где-то внутри уже топят печи. Дорога к реке ещё не протоптана, и первые следы на ней оставляет старый пёс.
К полудню солнце поднимается над лесом, и снег начинает искриться так ярко, что приходится щуриться. Дети выбегают на горку с санками, и их смех разносится далеко по замёрзшему полю.
Вечером все собираются у самовара и рассказывают истории."""),
    "en_poem": ("Evening on the Marsh", """The tide draws back across the marsh
and leaves the mud to breathe;
a heron folds its patient neck,
the reeds begin to seethe.
The last light thins along the dyke,
the wind forgets its name,
and every pool the water leaves
holds up a little flame.
The village bells are far and slow,
the road is cold and bare,
and something in the failing light
is almost like a prayer."""),
    "es_letter": ("Carta de recomendación", """Estimados señores,
Tengo el placer de recomendar a la señorita Elena Ruiz, quien trabajó bajo mi supervisión durante tres años en el departamento de diseño. Durante ese tiempo demostró una capacidad excepcional para resolver problemas y una actitud siempre colaboradora con sus compañeros.
Elena dirigió el rediseño de nuestro catálogo, un proyecto que redujo los costes de impresión en un veinte por ciento y recibió elogios de nuestros clientes más exigentes.
No dudo de que será una incorporación valiosa para cualquier equipo. Quedo a su disposición para cualquier consulta adicional.
Atentamente,
Marta Gómez"""),
    "en_terms": ("Terms of service excerpt", """By using this service you agree to the following terms. The service is provided as is, without warranty of any kind, express or implied, including but not limited to the warranties of merchantability, fitness for a particular purpose and non-infringement. In no event shall the provider be liable for any claim, damages or other liability arising from the use of the service.
You may not use the service for any unlawful purpose or in any way that could damage, disable or impair the service. We reserve the right to suspend accounts that violate these terms without notice.
These terms are governed by the laws of the jurisdiction in which the provider is established."""),
}


def _font_kwargs():
    return {"fontname": "F0", "fontfile": FONT} if FONT else {"fontname": "helv"}


def _text_width(text: str, size: float) -> float:
    if FONT:
        return fitz.Font(fontfile=FONT).text_length(text, fontsize=size)
    return fitz.get_text_length(text, fontname="helv", fontsize=size)


def _rtl(text: str, lang: str) -> str:
    # PyMuPDF draws logical order left-to-right and its extractor re-applies
    # bidi, so Arabic must be inserted reversed to round-trip correctly.
    return text[::-1] if lang == "ar" else text


def make_form(name: str, spec: dict, rng: random.Random) -> dict:
    doc = fitz.open()
    L = spec["lang"]
    page = doc.new_page(width=W, height=H)
    fk = _font_kwargs()
    junk: list[str] = []
    truth: list[dict] = []
    # Title (junk) + instructions (junk)
    page.insert_text((60, 55), _rtl(spec["title"], L), fontsize=16, **fk)
    junk.append(spec["title"])
    instr = INSTRUCTIONS[spec["lang"]]
    page.insert_text((60, 80), _rtl(instr, L), fontsize=8.5, **fk)
    junk.append(instr)
    page.draw_line((60, 90), (W - 60, 90))
    y = 125.0
    size = 10.5
    for row in spec["rows"]:
        n = len(row)
        col_w = (W - 120) / n
        x = 60.0
        for label, kind in row:
            if kind.startswith("box3:"):
                opts = kind.split(":", 1)[1].split(",")
                page.insert_text((x, y), _rtl(label + ":", L), fontsize=size, **fk)
                tw = _text_width(label + ":", size)
                bx = x + tw + 12
                for o in opts:
                    page.insert_text((bx, y), _rtl("☐ " + o, L), fontsize=size, **fk)
                    bx += _text_width("☐ " + o, size) + 16
                truth.append({"label": label, "type": "multiple-choice"})
            elif kind == "colon":
                page.insert_text((x, y), _rtl(label + ":", L), fontsize=size, **fk)
                tw = _text_width(label + ":", size)
                page.draw_line((x + tw + 6, y + 2), (x + col_w - 14, y + 2), width=0.5)
                truth.append({"label": label, "type": None})
            elif kind == "line":
                page.insert_text((x, y), _rtl(label, L), fontsize=size, **fk)
                tw = _text_width(label, size)
                page.insert_text((x + tw + 6, y), "_" * int((col_w - tw - 24) / 5.2), fontsize=size, fontname="helv")
                truth.append({"label": label, "type": None})
            elif kind.startswith("value:"):
                val = kind.split(":", 1)[1]
                page.insert_text((x, y), _rtl(label + ":", L), fontsize=size, **fk)
                tw = _text_width(label + ":", size)
                page.insert_text((x + tw + 8, y), val, fontsize=size, **fk)
                truth.append({"label": label, "type": None, "value": val})
            x += col_w
        y += 34 + rng.uniform(-2, 2)
    footer = FOOTERS[spec["lang"]]
    page.insert_text((60, H - 40), _rtl(footer, L), fontsize=7.5, **fk)
    junk.append(footer)
    page.insert_text((W / 2 - 15, H - 25), "Page 1 of 1", fontsize=8, fontname="helv")
    junk.append("Page 1 of 1")
    path = os.path.join(FORMS, f"{name}.pdf")
    doc.subset_fonts()  # keep only the glyphs used, not the whole 22 MB font
    doc.save(path, garbage=4, deflate=True)
    doc.close()
    gt = {"name": name, "is_form": True, "lang": spec["lang"], "fields": truth, "junk": junk}
    with open(os.path.join(FORMS, f"{name}.json"), "w", encoding="utf-8") as f:
        json.dump(gt, f, ensure_ascii=False, indent=1)
    return gt


def make_non_form(name: str, title: str, body: str) -> dict:
    doc = fitz.open()
    page = doc.new_page(width=W, height=H)
    fk = _font_kwargs()
    page.insert_text((60, 60), title, fontsize=15, **fk)
    rect = fitz.Rect(60, 85, W - 60, H - 60)
    page.insert_textbox(rect, body, fontsize=10.5, lineheight=1.4, **fk)
    page.insert_text((W / 2 - 5, H - 30), "1", fontsize=8, fontname="helv")
    path = os.path.join(NONF, f"{name}.pdf")
    doc.subset_fonts()
    doc.save(path, garbage=4, deflate=True)
    doc.close()
    gt = {"name": name, "is_form": False}
    with open(os.path.join(NONF, f"{name}.json"), "w", encoding="utf-8") as f:
        json.dump(gt, f, ensure_ascii=False, indent=1)
    return gt


def main() -> None:
    os.makedirs(FORMS, exist_ok=True)
    os.makedirs(NONF, exist_ok=True)
    rng = random.Random(7)
    for name, spec in FORM_SPECS.items():
        make_form(name, spec, rng)
    for name, (title, body) in NON_FORMS.items():
        make_non_form(name, title, body)
    print(f"wrote {len(FORM_SPECS)} forms and {len(NON_FORMS)} non-forms")


if __name__ == "__main__":
    sys.exit(main())
