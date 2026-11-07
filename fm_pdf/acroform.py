"""Conception de formulaires AcroForm (sans Qt) : créer, modifier, supprimer, ordonner des champs INTERACTIFS
standard, lisibles et remplissables par Acrobat Reader et tout lecteur conforme (aucune dépendance à l'appli).

Moteur d'écriture : PyMuPDF (apparences /AP générées, scripts /AA, tableau /CO des calculs). Les réglages que
PyMuPDF n'expose pas (alignement /Q, valeurs d'export des boutons radio, ordre de tabulation) sont posés dans les
dictionnaires eux-mêmes. JAMAIS d'aplatissement : les champs restent des champs, vides ou non.

Formats, validations, calculs : fonctions standard d'Acrobat (AFNumber_Format / Keystroke, AFDate_FormatEx /
KeystrokeEx, AFRange_Validate, AFSimple_Calculate), implémentées aussi par PDFium : même comportement dans le
module et dans Acrobat Reader.

Coordonnées : `rect` = (x0, y0, x1, y1) en POINTS, origine en haut à gauche de la page AFFICHÉE (comme le reste du
module) ; converties dans le repère de la page non tournée par la matrice de PyMuPDF.
"""
from __future__ import annotations

import io
import json
import re
from dataclasses import asdict, dataclass, field

KINDS = ("text", "multiline", "number", "date", "checkbox", "radio", "combo", "list", "button", "signature")
KIND_LABELS = {"text": "Texte", "multiline": "Texte multiligne", "number": "Nombre", "date": "Date",
               "checkbox": "Case à cocher", "radio": "Bouton radio", "combo": "Liste déroulante",
               "list": "Liste à choix", "button": "Bouton", "signature": "Signature"}
FONTS = {"Helvetica": "Helv", "Times": "TiRo", "Courier": "Cour"}
ALIGN = {"left": 0, "center": 1, "right": 2}
BORDER_STYLES = {"solid": "S", "dashed": "D", "beveled": "B", "inset": "I", "underline": "U"}
CALC_OPS = {"SUM": "Somme", "PRD": "Produit", "AVG": "Moyenne", "MIN": "Minimum", "MAX": "Maximum"}
DATE_FORMATS = ("dd/mm/yyyy", "mm/dd/yyyy", "yyyy-mm-dd", "dd.mm.yyyy", "d mmmm yyyy")

# Drapeaux /Ff (ISO 32000-1, tableaux 221, 226, 228, 230)
FF_READONLY, FF_REQUIRED, FF_NOEXPORT = 1, 2, 4
FF_MULTILINE, FF_PASSWORD, FF_NOSPELL, FF_DONOTSCROLL, FF_COMB = 1 << 12, 1 << 13, 1 << 22, 1 << 23, 1 << 24
FF_NOTOGGLEOFF, FF_RADIO, FF_PUSHBUTTON, FF_RADIOS_IN_UNISON = 1 << 14, 1 << 15, 1 << 16, 1 << 25
FF_COMBO, FF_EDIT, FF_SORT, FF_MULTISELECT, FF_COMMIT_ON_CHANGE = 1 << 17, 1 << 18, 1 << 19, 1 << 21, 1 << 26


class FormError(ValueError):
    pass


@dataclass
class FieldSpec:
    """Un champ tel que le concepteur le décrit. `name` unique (sauf boutons radio d'un même groupe)."""
    kind: str
    name: str
    page: int
    rect: tuple
    tooltip: str = ""
    required: bool = False
    readonly: bool = False
    value: str = ""                         # valeur (texte) / valeur d'export cochée (case, radio) / choix
    default: str = ""                       # valeur par défaut (/DV)
    font: str = "Helvetica"
    font_size: float = 0.0                  # 0 = automatique
    text_color: tuple = (0.0, 0.0, 0.0)
    fill_color: tuple | None = (1.0, 1.0, 1.0)
    border_color: tuple | None = (0.45, 0.45, 0.45)
    border_width: float = 1.0
    border_style: str = "solid"
    align: str = "left"
    max_length: int = 0
    choices: list = field(default_factory=list)       # liste : [« libellé »] ou [[export, libellé]]
    editable: bool = False                  # liste déroulante modifiable
    multiselect: bool = False               # liste à choix multiples
    export_value: str = "Oui"               # case / radio : valeur quand cochée
    checked: bool = False
    caption: str = ""                       # bouton
    decimals: int = 2                       # nombre
    separator: int = 2                      # AFNumber : 0 « 1,234.56 », 1 « 1234.56 », 2 « 1.234,56 », 3 « 1234,56 »
    currency: str = ""
    date_format: str = "dd/mm/yyyy"
    min_value: float | None = None          # validation (nombre)
    max_value: float | None = None
    calc_op: str = ""                       # SUM, PRD, AVG, MIN, MAX
    calc_fields: list = field(default_factory=list)
    calc_script: str = ""                   # calcul personnalisé (JavaScript)
    validate_script: str = ""               # validation personnalisée (JavaScript)
    format_script: str = ""
    keystroke_script: str = ""
    action_script: str = ""                 # bouton : script au clic
    xref: int = 0                           # widget existant (lecture) ; 0 = nouveau

    def to_json(self) -> dict:
        return asdict(self)


def _js_str(text: str) -> str:
    return json.dumps(text, ensure_ascii=False)


def scripts_for(spec: FieldSpec) -> dict:
    """{'stroke', 'format', 'validate', 'calc', 'action'} : scripts standard Acrobat selon le type et les règles."""
    out = {}
    if spec.kind == "number":
        cur = _js_str(spec.currency)
        out["format"] = f"AFNumber_Format({int(spec.decimals)}, {int(spec.separator)}, 0, 0, {cur}, true);"
        out["stroke"] = f"AFNumber_Keystroke({int(spec.decimals)}, {int(spec.separator)}, 0, 0, {cur}, true);"
        if spec.min_value is not None or spec.max_value is not None:
            gt = "true" if spec.min_value is not None else "false"
            lt = "true" if spec.max_value is not None else "false"
            out["validate"] = (f"AFRange_Validate({gt}, {spec.min_value if spec.min_value is not None else 0}, "
                               f"{lt}, {spec.max_value if spec.max_value is not None else 0});")
    elif spec.kind == "date":
        fmt = _js_str(spec.date_format or "dd/mm/yyyy")
        out["format"] = f"AFDate_FormatEx({fmt});"
        out["stroke"] = f"AFDate_KeystrokeEx({fmt});"
    if spec.calc_op and spec.calc_fields:
        out["calc"] = calc_script(spec.calc_op, spec.calc_fields)
    if spec.calc_script:
        out["calc"] = spec.calc_script
    if spec.validate_script:
        out["validate"] = spec.validate_script
    if spec.format_script:
        out["format"] = spec.format_script
    if spec.keystroke_script:
        out["stroke"] = spec.keystroke_script
    if spec.kind == "button" and spec.action_script:
        out["action"] = spec.action_script
    return out


CALC_MARK = "/* fm_pdf calc "


def calc_script(op: str, names: list[str]) -> str:
    """Calcul simple (somme, produit, moyenne, min, max) par AFMakeNumber : lit « 12,5 » comme 12,5 dans PDFium ET
    dans Acrobat (AFSimple_Calculate de PDFium lit « 12,5 » comme 12 : mesuré). Le marqueur en tête permet au
    concepteur de le relire comme un calcul simple."""
    if op not in CALC_OPS:
        raise FormError("opération de calcul inconnue : %s" % op)
    arr = "[" + ", ".join(_js_str(n) for n in names) + "]"
    lines = [
        CALC_MARK + json.dumps({"op": op, "fields": list(names)}, ensure_ascii=False) + " */",
        "(function (doc) { var names = " + arr + ", op = " + _js_str(op) + ", r = null, n = 0;",
        "for (var i = 0; i < names.length; i++) { var f = doc.getField(names[i]); if (!f) continue;",
        "var v = AFMakeNumber(f.value); if (v === null || isNaN(v)) v = 0; n++;",
        'if (r === null) r = v; else if (op == "SUM" || op == "AVG") r += v; else if (op == "PRD") r *= v;',
        'else if (op == "MIN") r = Math.min(r, v); else if (op == "MAX") r = Math.max(r, v); }',
        'if (op == "AVG" && n) r = r / n; event.value = (r === null) ? "" : r; })(this);',
    ]
    return "\n".join(lines)


def _flags(spec: FieldSpec) -> int:
    f = 0
    if spec.readonly:
        f |= FF_READONLY
    if spec.required:
        f |= FF_REQUIRED
    if spec.kind == "multiline":
        f |= FF_MULTILINE
    if spec.kind == "combo" and spec.editable:
        f |= FF_EDIT
    if spec.kind == "list" and spec.multiselect:
        f |= FF_MULTISELECT
    if spec.kind == "radio":
        f |= FF_NOTOGGLEOFF
    return f


def _check_name(name: str) -> str:
    name = (name or "").strip()
    if not name:
        raise FormError("un champ doit avoir un nom")
    if "." in name:
        raise FormError("le point est réservé aux noms hiérarchiques : « %s »" % name)
    if not re.match(r"^[^()\[\]<>{}/%]+$", name):
        raise FormError("caractères interdits dans le nom « %s »" % name)
    return name


def _pdf_name(text: str) -> str:
    """Nom PDF valide pour une valeur d'export (/Oui, /Choix#201…)."""
    out = []
    for ch in text or "Oui":
        if ch.isalnum() and ord(ch) < 128:
            out.append(ch)
        else:
            out.extend("#%02X" % b for b in ch.encode("utf-8"))
    return "".join(out) or "Oui"


def _to_unrotated(page, rect):
    import pymupdf
    r = pymupdf.Rect(rect) * page.derotation_matrix
    r.normalize()
    return r


def _from_unrotated(page, rect):
    import pymupdf
    r = pymupdf.Rect(rect) * page.rotation_matrix
    r.normalize()
    return (r.x0, r.y0, r.x1, r.y1)


def _widget_type(kind):
    import pymupdf
    return {"text": pymupdf.PDF_WIDGET_TYPE_TEXT, "multiline": pymupdf.PDF_WIDGET_TYPE_TEXT,
            "number": pymupdf.PDF_WIDGET_TYPE_TEXT, "date": pymupdf.PDF_WIDGET_TYPE_TEXT,
            "checkbox": pymupdf.PDF_WIDGET_TYPE_CHECKBOX, "radio": pymupdf.PDF_WIDGET_TYPE_RADIOBUTTON,
            "combo": pymupdf.PDF_WIDGET_TYPE_COMBOBOX, "list": pymupdf.PDF_WIDGET_TYPE_LISTBOX,
            "button": pymupdf.PDF_WIDGET_TYPE_BUTTON, "signature": pymupdf.PDF_WIDGET_TYPE_SIGNATURE}[kind]


def _apply(widget, spec: FieldSpec):
    widget.field_name = spec.name
    widget.field_label = spec.tooltip or None
    widget.field_flags = _flags(spec)
    widget.text_font = FONTS.get(spec.font, "Helv")
    widget.text_fontsize = float(spec.font_size or 0)
    widget.text_color = tuple(spec.text_color)
    widget.fill_color = tuple(spec.fill_color) if spec.fill_color else None
    widget.border_color = tuple(spec.border_color) if spec.border_color else None
    widget.border_width = float(spec.border_width)
    widget.border_style = BORDER_STYLES.get(spec.border_style, "S")
    widget.border_dashes = (3, 2) if spec.border_style == "dashed" else None
    if spec.kind in ("text", "multiline", "number", "date"):
        widget.text_maxlen = int(spec.max_length or 0)
        widget.field_value = spec.value or ""
    elif spec.kind in ("combo", "list"):
        widget.choice_values = [c if isinstance(c, str) else list(c) for c in spec.choices] or [""]
        widget.field_value = spec.value or None
    elif spec.kind == "checkbox":
        widget.field_value = bool(spec.checked)
    elif spec.kind == "radio":
        widget.field_value = bool(spec.checked)
    elif spec.kind == "button":
        widget.button_caption = spec.caption or spec.name
    js = scripts_for(spec)
    if spec.kind != "button":
        widget.script_stroke = js.get("stroke")
        widget.script_format = js.get("format")
        widget.script_change = js.get("validate")
        widget.script_calc = js.get("calc")
    else:
        widget.script = js.get("action")


def _post_fix(doc, xref: int, spec: FieldSpec):
    """Ce que PyMuPDF n'écrit pas : alignement, valeur par défaut, valeur d'export des cases / radios."""
    if spec.kind in ("text", "multiline", "number", "date", "combo", "list"):
        doc.xref_set_key(xref, "Q", str(ALIGN.get(spec.align, 0)))
        parent = _field_dict_xref(doc, xref)
        if spec.default:
            doc.xref_set_key(parent, "DV", _pdf_string(spec.default))
    if spec.kind in ("checkbox", "radio"):
        _set_export_value(doc, xref, _pdf_name(spec.export_value), spec.checked)


def _del_keys(doc, xref: int, *keys) -> None:
    """Supprime VRAIMENT des clés (xref_set_key(..., "null") écrit « /Clé null », que PDFium lit comme une valeur
    et non comme une absence : héritage du parent cassé, champ « inconnu »)."""
    import pymupdf
    m = pymupdf.mupdf
    obj = m.pdf_load_object(pymupdf._as_pdf_document(doc), xref)
    for key in keys:
        m.pdf_dict_dels(obj, key)


def _pdf_string(text: str) -> str:
    try:
        text.encode("ascii")
        return "(" + text.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)") + ")"
    except UnicodeEncodeError:
        return "<FEFF" + text.encode("utf-16-be").hex().upper() + ">"


def _field_dict_xref(doc, widget_xref: int) -> int:
    """Le dictionnaire du CHAMP : le parent s'il porte /T et pas le widget, sinon le widget lui-même."""
    kind, value = doc.xref_get_key(widget_xref, "Parent")
    if kind == "xref" and doc.xref_get_key(widget_xref, "T")[0] == "null":
        return int(value.split()[0])
    return widget_xref


def _set_export_value(doc, xref: int, on: str, checked: bool):
    """Renomme l'état « activé » des apparences /AP /N et /D en `on` ; /AS et /V suivent."""
    for key in ("AP/N", "AP/D"):
        kind, value = doc.xref_get_key(xref, key)
        if kind != "dict":
            continue
        names = re.findall(r"/([^\s/<>\[\]()]+)\s+(\d+ 0 R|<<)", value)
        old = next((n for n, _ in names if n != "Off"), None)
        if old and old != on:
            value = value.replace("/" + old + " ", "/" + on + " ", 1)
            doc.xref_set_key(xref, key, value)
    state = on if checked else "Off"
    doc.xref_set_key(xref, "AS", "/" + state)
    field_xref = _field_dict_xref(doc, xref)
    if checked:
        doc.xref_set_key(field_xref, "V", "/" + on)
    elif doc.xref_get_key(field_xref, "V")[0] == "null":
        doc.xref_set_key(field_xref, "V", "/Off")


def _open(data: bytes):
    import pymupdf
    doc = pymupdf.open(stream=data, filetype="pdf")
    if doc.is_encrypted:
        raise FormError("document chiffré : ouvrez-le avec son mot de passe puis enregistrez-le sans chiffrement")
    return doc


def _save(doc) -> bytes:
    out = io.BytesIO()
    doc.save(out, garbage=1, deflate=True)
    return out.getvalue()


def add_fields(data: bytes, specs: list[FieldSpec]) -> tuple[bytes, list[int]]:
    """Ajoute des champs ; renvoie (octets, xrefs des widgets créés). Noms en double refusés (sauf radios d'un même
    groupe)."""
    doc = _open(data)
    try:
        existing = {w.field_name: w.field_type_string for p in doc for w in (p.widgets() or [])}
        created = []
        radio_groups: dict[str, list] = {}
        for spec in specs:
            if spec.kind not in KINDS:
                raise FormError("type de champ inconnu : %s" % spec.kind)
            _check_name(spec.name)
            if spec.kind != "radio" and spec.name in existing:
                raise FormError("un champ « %s » existe déjà" % spec.name)
            if spec.kind == "radio" and existing.get(spec.name) not in (None, "RadioButton"):
                raise FormError("« %s » est déjà un champ d'un autre type" % spec.name)
            if not 0 <= spec.page < doc.page_count:
                raise FormError("page %d inexistante" % (spec.page + 1))
            page = doc[spec.page]
            import pymupdf
            w = pymupdf.Widget()
            w.field_type = _widget_type(spec.kind)
            w.rect = _to_unrotated(page, spec.rect)
            _apply(w, spec)
            annot = page.add_widget(w)
            _post_fix(doc, annot.xref, spec)
            created.append(annot.xref)
            existing[spec.name] = "RadioButton" if spec.kind == "radio" else spec.kind
            if spec.kind == "radio":
                radio_groups.setdefault(spec.name, []).append(annot.xref)
        for name, xrefs in radio_groups.items():
            _merge_radio_group(doc, name)
        _ensure_acroform(doc)
        return _save(doc), created
    finally:
        doc.close()


def _merge_radio_group(doc, name: str):
    """Tous les widgets radio de ce nom deviennent les enfants (/Kids) d'UN champ parent : un seul choix possible
    (structure attendue par Acrobat ; PyMuPDF peut créer des champs séparés de même nom)."""
    kids = []
    for page in doc:
        for w in page.widgets() or []:
            if w.field_name == name and w.field_type_string == "RadioButton":
                kids.append(w.xref)
    if len(kids) < 1:
        return
    parents = {doc.xref_get_key(k, "Parent")[1] for k in kids if doc.xref_get_key(k, "Parent")[0] == "xref"}
    if len(parents) == 1 and all(doc.xref_get_key(k, "T")[0] == "null" for k in kids):
        return                                          # déjà un groupe
    parent = doc.get_new_xref()
    flags = int(doc.xref_get_key(kids[0], "Ff")[1] or FF_RADIO | FF_NOTOGGLEOFF)
    value = "/Off"
    for k in kids:
        state = doc.xref_get_key(k, "AS")[1]
        if state and state != "/Off":
            value = state
    doc.update_object(parent, "<< /FT /Btn /Ff %d /T %s /V %s /Kids [%s] >>" % (
        flags | FF_RADIO, _pdf_string(name), value, " ".join("%d 0 R" % k for k in kids)))
    tu = doc.xref_get_key(kids[0], "TU")
    if tu[0] != "null":
        doc.xref_set_key(parent, "TU", tu[1])
    for k in kids:
        _del_keys(doc, k, "T", "FT", "Ff", "V", "TU", "AA", "DV")
        doc.xref_set_key(k, "Parent", "%d 0 R" % parent)
    # /AcroForm /Fields : le parent remplace ses enfants (/AcroForm en ligne ou objet : chemins de clés)
    cat = doc.pdf_catalog()
    kind, fields = doc.xref_get_key(cat, "AcroForm/Fields")
    refs = re.findall(r"(\d+) 0 R", fields) if kind == "array" else []
    refs = [r for r in refs if int(r) not in kids] + [str(parent)]
    doc.xref_set_key(cat, "AcroForm/Fields", "[" + " ".join(r + " 0 R" for r in refs) + "]")


def _ensure_acroform(doc):
    """/AcroForm avec /DA ; /NeedAppearances faux : nos apparences sont complètes."""
    cat = doc.pdf_catalog()
    if doc.xref_get_key(cat, "AcroForm")[0] == "null":
        return
    if doc.xref_get_key(cat, "AcroForm/DA")[0] == "null":
        doc.xref_set_key(cat, "AcroForm/DA", "(/Helv 0 Tf 0 g)")
    doc.xref_set_key(cat, "AcroForm/NeedAppearances", "false")


def read_fields(data: bytes) -> list[FieldSpec]:
    """Champs AcroForm du document, décrits comme le concepteur les édite."""
    doc = _open(data)
    try:
        out = []
        for page in doc:
            for w in page.widgets() or []:
                out.append(_spec_of(doc, page, w))
        return out
    finally:
        doc.close()


def _spec_of(doc, page, w) -> FieldSpec:
    import pymupdf
    t = w.field_type
    flags = w.field_flags or 0
    kind = {pymupdf.PDF_WIDGET_TYPE_CHECKBOX: "checkbox", pymupdf.PDF_WIDGET_TYPE_RADIOBUTTON: "radio",
            pymupdf.PDF_WIDGET_TYPE_COMBOBOX: "combo", pymupdf.PDF_WIDGET_TYPE_LISTBOX: "list",
            pymupdf.PDF_WIDGET_TYPE_BUTTON: "button", pymupdf.PDF_WIDGET_TYPE_SIGNATURE: "signature"}.get(t, "text")
    fmt = w.script_format or ""
    if kind == "text":
        if flags & FF_MULTILINE:
            kind = "multiline"
        elif "AFNumber_Format" in fmt:
            kind = "number"
        elif "AFDate_FormatEx" in fmt:
            kind = "date"
    spec = FieldSpec(kind=kind, name=w.field_name or "", page=page.number, rect=_from_unrotated(page, w.rect),
                     tooltip=w.field_label or "", required=bool(flags & FF_REQUIRED),
                     readonly=bool(flags & FF_READONLY), font={v: k for k, v in FONTS.items()}.get(w.text_font,
                                                                                                    "Helvetica"),
                     font_size=float(w.text_fontsize or 0), text_color=tuple(w.text_color or (0, 0, 0)),
                     fill_color=tuple(w.fill_color) if w.fill_color else None,
                     border_color=tuple(w.border_color) if w.border_color else None,
                     border_width=float(w.border_width or 0), xref=w.xref)
    spec.border_style = {v: k for k, v in BORDER_STYLES.items()}.get(w.border_style or "S", "solid")
    q = doc.xref_get_key(w.xref, "Q")[1]
    spec.align = {0: "left", 1: "center", 2: "right"}.get(int(q) if q and q.isdigit() else 0, "left")
    if kind in ("text", "multiline", "number", "date"):
        spec.value = w.field_value or ""
        spec.max_length = int(w.text_maxlen or 0)
    elif kind in ("combo", "list"):
        spec.choices = list(w.choice_values or [])
        spec.value = w.field_value if isinstance(w.field_value, str) else ""
        spec.editable = bool(flags & FF_EDIT)
        spec.multiselect = bool(flags & FF_MULTISELECT)
    elif kind in ("checkbox", "radio"):
        on = w.on_state()
        spec.export_value = on if isinstance(on, str) and on else "Oui"
        spec.checked = w.field_value not in (None, False, "Off", "")
    elif kind == "button":
        spec.caption = w.button_caption or ""
        spec.action_script = w.script or ""
    m = re.search(r"AFNumber_Format\((\d+),\s*(\d+),\s*\d+,\s*\d+,\s*(\".*?\")", fmt)
    if m:
        spec.decimals, spec.separator, spec.currency = int(m.group(1)), int(m.group(2)), json.loads(m.group(3))
    m = re.search(r"AFDate_FormatEx\((\".*?\")\)", fmt)
    if m:
        spec.date_format = json.loads(m.group(1))
    calc = w.script_calc or ""
    m = re.match(r"\s*AFSimple_Calculate\(\"(\w+)\",\s*new Array\((.*)\)\);?\s*$", calc, re.S)
    if calc.startswith(CALC_MARK):
        try:
            meta = json.loads(calc[len(CALC_MARK):calc.index(" */")])
            spec.calc_op, spec.calc_fields = meta["op"], list(meta["fields"])
        except (ValueError, KeyError):
            spec.calc_script = calc
    elif m:
        spec.calc_op = m.group(1)
        spec.calc_fields = [json.loads(x) for x in re.findall(r"\"(?:[^\"\\]|\\.)*\"", m.group(2))]
    elif calc:
        spec.calc_script = calc
    val = w.script_change or ""
    m = re.match(r"\s*AFRange_Validate\((true|false),\s*([-\d.]+),\s*(true|false),\s*([-\d.]+)\);?\s*$", val)
    if m:
        spec.min_value = float(m.group(2)) if m.group(1) == "true" else None
        spec.max_value = float(m.group(4)) if m.group(3) == "true" else None
    elif val:
        spec.validate_script = val
    return spec


def update_field(data: bytes, xref: int, spec: FieldSpec) -> bytes:
    """Remplace les propriétés du widget `xref` (et de son champ) par celles de `spec` (position comprise)."""
    doc = _open(data)
    try:
        for page in doc:
            for w in page.widgets() or []:
                if w.xref != xref:
                    continue
                if spec.name != w.field_name:
                    _check_name(spec.name)
                    names = {x.field_name for p in doc for x in (p.widgets() or []) if x.xref != xref}
                    if spec.name in names and spec.kind != "radio":
                        raise FormError("un champ « %s » existe déjà" % spec.name)
                target = doc[spec.page] if spec.page != page.number else page
                if target.number != page.number:
                    raise FormError("déplacer un champ vers une autre page : supprimez-le puis recréez-le")
                w.rect = _to_unrotated(page, spec.rect)
                _apply(w, spec)
                w.update()
                _post_fix(doc, w.xref, spec)
                return _save(doc)
        raise FormError("champ introuvable (xref %d)" % xref)
    finally:
        doc.close()


def delete_fields(data: bytes, xrefs: list[int]) -> bytes:
    doc = _open(data)
    try:
        wanted = set(xrefs)
        for page in doc:
            for w in list(page.widgets() or []):
                if w.xref in wanted:
                    page.delete_widget(w)
        return _save(doc)
    finally:
        doc.close()


def set_tab_order(data: bytes, page_index: int, xrefs: list[int]) -> bytes:
    """Ordre de tabulation MANUEL d'une page : les widgets dans l'ordre donné en tête de /Annots, /Tabs retiré
    (lecteurs : ordre du tableau)."""
    doc = _open(data)
    try:
        page = doc[page_index]
        kind, annots = doc.xref_get_key(page.xref, "Annots")
        if kind == "xref":
            arr_xref = int(annots.split()[0])
            annots = doc.xref_object(arr_xref)
        refs = [int(r) for r in re.findall(r"(\d+) 0 R", annots or "")]
        ordered = [x for x in xrefs if x in refs] + [r for r in refs if r not in xrefs]
        doc.xref_set_key(page.xref, "Annots", "[" + " ".join("%d 0 R" % r for r in ordered) + "]")
        doc.xref_set_key(page.xref, "Tabs", "null")
        return _save(doc)
    finally:
        doc.close()


def tab_order(data: bytes, page_index: int) -> list[int]:
    """xrefs des widgets de la page dans l'ordre du tableau /Annots."""
    doc = _open(data)
    try:
        page = doc[page_index]
        widgets = {w.xref for w in page.widgets() or []}
        return [a[0] for a in page.annot_xrefs() if a[0] in widgets]
    finally:
        doc.close()


def unique_name(data_or_names, base: str) -> str:
    names = set(data_or_names) if not isinstance(data_or_names, (bytes, bytearray)) else \
        {s.name for s in read_fields(data_or_names)}
    base = re.sub(r"[.()\[\]<>{}/%]", "_", base or "Champ")
    if base not in names:
        return base
    k = 2
    while f"{base}_{k}" in names:
        k += 1
    return f"{base}_{k}"


def new_blank_document(width: float = 595.28, height: float = 841.89, pages: int = 1) -> bytes:
    """Document vierge (A4 par défaut) pour partir de zéro."""
    import pymupdf
    doc = pymupdf.open()
    for _ in range(max(1, pages)):
        doc.new_page(width=width, height=height)
    try:
        return _save(doc)
    finally:
        doc.close()
