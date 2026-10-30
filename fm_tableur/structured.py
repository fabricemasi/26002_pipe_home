"""Tableaux structurés (SANS Qt) : définition, noms de colonnes, et traduction des RÉFÉRENCES STRUCTURÉES en plages
A1 avant l'envoi au moteur (`engine._set`).

Choix (2026-10-30) : formualizer 0.13 connaît les tableaux mais pas tout (`T[[#Data],[Col]]` non implémenté, `[@Col]`
refusé, nom de tableau seul inconnu, aucun moyen de redimensionner ni supprimer un tableau). Le module traduit donc
lui-même : le classeur garde le texte d'Excel (`=SOMME(Ventes[Montant])`), le moteur reçoit `'Feuil1'!$B$2:$B$4` ;
son graphe de dépendances fonctionne comme pour une plage ordinaire. Un tableau qui change (taille, entêtes) =
les formules qui le citent sont renvoyées au moteur (`CalcEngine.tables_changed`).

Tableau = dictionnaire dans `Sheet.tables` : `name`, `ref` (r0, c0, r1, c1, entête et totaux compris), `header`
(1re ligne = entêtes), `totals` (dernière ligne = totaux), `style` (STYLES), `banded` (lignes à bandes).
Noms de colonnes = textes de la ligne d'entête (vide : « Colonne<n> », doublon : suffixe « 2 »), comme Excel.

Syntaxe d'Excel prise en charge : `T`, `T[]`, `T[Col]`, `T[[Col]]`, `T[[Col1]:[Col2]]`, `T[#All]`, `T[#Data]`,
`T[#Headers]`, `T[#Totals]`, `T[#This Row]`, combinaisons `T[[#Headers],[#Data],[Col]]`, `T[@Col]`,
`T[@[Col 1]]`, `T[@]`, `[@Col]` (tableau de la cellule), échappements « ' » dans les noms de colonnes.
Tableau ou colonne inconnu : #REF!. Ligne courante hors du tableau : #VALUE!."""
from __future__ import annotations

import re

from . import refs as R

STYLES = {"bleu": ("#4472c4", "#d9e1f2", "TableStyleMedium2"), "orange": ("#ed7d31", "#fce4d6", "TableStyleMedium3"),
          "gris": ("#7f7f7f", "#ededed", "TableStyleMedium4"), "or": ("#ffc000", "#fff2cc", "TableStyleMedium5"),
          "vert": ("#70ad47", "#e2efda", "TableStyleMedium7"), "aucun": (None, None, "TableStyleLight1")}
EXCEL_STYLE = {v[2]: k for k, v in STYLES.items()}
_NAME = re.compile(r"^[A-Za-z_\\À-￿][\w.À-￿]*$")
_SPECIALS = {"#all", "#data", "#headers", "#totals", "#this row"}
# mots-clés d'Excel en français, acceptés à la saisie (le classeur garde l'anglais du fichier)
_FR_SPECIALS = {"#tout": "#all", "#données": "#data", "#donnees": "#data", "#en-têtes": "#headers",
                "#en-tetes": "#headers", "#totaux": "#totals", "#cette ligne": "#this row"}


def _special(text: str) -> str | None:
    low = text.strip().lower()
    low = _FR_SPECIALS.get(low, low)
    return low if low in _SPECIALS else None


# ---------------------------------------------------------------- tableaux du classeur
def all_tables(book):
    """(feuille, tableau) de tout le classeur."""
    for sheet in book.sheets:
        for table in sheet.tables:
            yield sheet, table


def find(book, name: str):
    low = name.lower()
    for sheet, table in all_tables(book):
        if table["name"].lower() == low:
            return sheet, table
    return None


def at(sheet, row: int, col: int):
    """Tableau de la feuille qui contient (row, col), ou None."""
    for table in sheet.tables:
        r0, c0, r1, c1 = table["ref"]
        if r0 <= row <= r1 and c0 <= col <= c1:
            return table
    return None


_COL_MEMO: dict = {}


def columns(book, sheet, table) -> list[str]:
    """Noms des colonnes : textes des entêtes (comme Excel : vides et doublons renommés). GARDÉS tant que le classeur
    ne change pas (une retraduction de 10 000 formules les demandait 10 000 fois)."""
    r0, c0, _r1, c1 = table["ref"]
    cells = sheet.cells                                    # cellules immuables : une entête modifiée = autre objet
    key = (id(table), tuple(table["ref"]), table.get("header", True),
           tuple(id(cells.get((r0, c))) for c in range(c0, c1 + 1)))
    found = _COL_MEMO.get(key)
    if found is not None:
        return found
    if len(_COL_MEMO) > 500:
        _COL_MEMO.clear()
    names = _columns(book, sheet, table)
    _COL_MEMO[key] = names
    return names


def _columns(book, sheet, table) -> list[str]:
    from .engine import cell_value
    r0, c0, _r1, c1 = table["ref"]
    names = []
    seen = set()
    for i, c in enumerate(range(c0, c1 + 1)):
        value = cell_value(book, sheet, r0, c) if table.get("header", True) else None
        text = ("" if value is None else str(value)).strip() or f"Colonne{i + 1}"
        base, n = text, 2
        while text.lower() in seen:
            text = f"{base}{n}"
            n += 1
        seen.add(text.lower())
        names.append(text)
    return names


def data_rows(table) -> tuple[int, int]:
    r0, _c0, r1, _c1 = table["ref"]
    return r0 + (1 if table.get("header", True) else 0), r1 - (1 if table.get("totals") else 0)


def unique_name(book, base: str = "Tableau") -> str:
    taken = {t["name"].lower() for _s, t in all_tables(book)} | {n.lower() for n in book.names}
    i = 1
    while f"{base}{i}".lower() in taken:
        i += 1
    return f"{base}{i}"


def valid_name(book, name: str, current=None) -> str | None:
    """Message si le nom de tableau est refusé (règles d'Excel), sinon None."""
    if not name or not _NAME.match(name):
        return "Nom non valable (lettres, chiffres, _ et . ; pas d'espace ; commence par une lettre)."
    if R.parse_cell(name) is not None or len(name) > 255:
        return "Ce nom ressemble à une adresse de cellule."
    found = find(book, name)
    if found is not None and found[1] is not current:
        return "Un tableau porte déjà ce nom."
    if name.lower() in {n.lower() for n in book.names}:
        return "Un nom défini porte déjà ce nom."
    return None


# ---------------------------------------------------------------- analyse de la syntaxe
def _scan_brackets(text: str, start: int) -> int:
    """Fin (exclue) du groupe « […] » qui commence à `start` (échappements « ' » d'Excel respectés)."""
    depth = 0
    i = start
    while i < len(text):
        ch = text[i]
        if ch == "'" and i + 1 < len(text):
            i += 2
            continue
        if ch == "[":
            depth += 1
        elif ch == "]":
            depth -= 1
            if depth == 0:
                return i + 1
        i += 1
    return -1


def _unescape(name: str) -> str:
    return re.sub(r"'(.)", r"\1", name)


def _parse_spec(spec: str):
    """Contenu entre crochets -> (sections spéciales, (col1, col2) ou None, ligne courante)."""
    inner = spec.strip()
    if inner == "":
        return [], None, False
    if inner.startswith("@"):
        rest = inner[1:].strip()
        if not rest:
            return ["#this row"], None, True
        if rest.startswith("["):
            rest = rest[1:-1] if rest.endswith("]") else rest
        return ["#this row"], (_unescape(rest), _unescape(rest)), True
    if not inner.startswith("["):
        special = _special(inner)
        if special:
            return [special], None, special == "#this row"
        name = _unescape(inner)
        return [], (name, name), False
    parts = []
    i = 0
    while i < len(inner):
        if inner[i] == "[":
            end = _scan_brackets(inner, i)
            if end < 0:
                raise ValueError("crochet non fermé")
            parts.append(("item", inner[i + 1:end - 1]))
            i = end
        elif inner[i] == ":":
            parts.append(("colon", None))
            i += 1
        else:
            i += 1
    specials, cols = [], []
    k = 0
    while k < len(parts):
        kind, value = parts[k]
        if kind == "item":
            if _special(value):
                specials.append(_special(value))
            elif k + 2 < len(parts) and parts[k + 1][0] == "colon":
                cols.append((_unescape(value), _unescape(parts[k + 2][1])))
                k += 2
            else:
                cols.append((_unescape(value), _unescape(value)))
        k += 1
    col = cols[0] if cols else None
    return specials, col, "#this row" in specials


_TABLE_REF = re.compile(r"(?<![\w.\]$'!])([A-Za-z_\\À-￿][\w.À-￿]*)?\[")


def iter_structured(formula: str):
    """(début, fin, nom du tableau ou None, contenu entre crochets) des références structurées (chaînes ignorées)."""
    i = 0
    n = len(formula)
    while i < n:
        ch = formula[i]
        if ch == '"':
            j = formula.find('"', i + 1)
            while j >= 0 and j + 1 < n and formula[j + 1] == '"':
                j = formula.find('"', j + 2)
            i = n if j < 0 else j + 1
            continue
        if ch == "'":                                     # nom de feuille entre apostrophes
            j = formula.find("'", i + 1)
            while j >= 0 and j + 1 < n and formula[j + 1] == "'":
                j = formula.find("'", j + 2)
            i = n if j < 0 else j + 1
            continue
        m = _TABLE_REF.match(formula, i)
        if m and (i == 0 or not (formula[i - 1].isalnum() or formula[i - 1] in "_.]$!")):
            start_bracket = m.end() - 1
            end = _scan_brackets(formula, start_bracket)
            if end > 0:
                yield i, end, m.group(1), formula[start_bracket + 1:end - 1]
                i = end
                continue
        i += 1


_ROW_ONLY: dict = {}


def row_only(formula: str, table_names) -> bool:
    """La formule ne cite les tableaux que par la LIGNE COURANTE ([@Col], T[[#This Row],…]) : sa traduction ne
    dépend pas de la taille du tableau (gardé par texte de formule)."""
    key = (formula, tuple(table_names))
    found = _ROW_ONLY.get(key)
    if found is None:
        refs = list(iter_structured(formula))
        found = bool(refs) and all(spec.strip().startswith("@") or "#this row" in spec.lower()
                                   or "#cette ligne" in spec.lower() for _s, _e, _n, spec in refs)
        if found and table_names:
            stripped = "".join(formula[i] for i in range(len(formula)))
            for start, end, _n, _spec in reversed(refs):
                stripped = stripped[:start] + stripped[end:]
            found = not any(re.search(r"(?<![\w.])" + re.escape(n) + r"(?![\w.(])", stripped, re.I)
                            for n in table_names)
        if len(_ROW_ONLY) > 5000:
            _ROW_ONLY.clear()
        _ROW_ONLY[key] = found
    return found


def rename_column_refs(formula: str, sheet, row: int, col: int, table, old: str, new: str) -> str:
    """Entête renommée (Excel) : les références à la colonne `old` du tableau deviennent `new`."""
    def esc(name):
        return re.sub(r"([\[\]#'])", r"'\1", name)
    out = []
    last = 0
    for start, end, name, spec in iter_structured(formula):
        target = name or (at(sheet, row, col) or {}).get("name")
        if target is None or target.lower() != table["name"].lower():
            continue
        new_spec = re.sub(r"(?<=\[|@)" + re.escape(esc(old)) + r"(?=\])", esc(new), spec, flags=re.I)
        if new_spec == spec:
            stripped = spec.strip()
            if stripped.lower() == esc(old).lower():
                new_spec = esc(new)
            elif stripped.startswith("@") and stripped[1:].lower() == esc(old).lower():
                new_spec = "@" + (esc(new) if re.fullmatch(r"[\w.]+", new) else "[" + esc(new) + "]")
        if new_spec != spec:
            out.append(formula[last:start])
            out.append(formula[start:end - len(spec) - 1] + new_spec + "]")
            last = end
    out.append(formula[last:])
    return "".join(out)


def has_structured(formula: str | None, book=None) -> bool:
    if not formula:
        return False
    if "[" in formula:
        return True
    if book is not None:
        names = [t["name"] for _s, t in all_tables(book)]
        return any(re.search(r"(?<![\w.])" + re.escape(n) + r"(?![\w.\[(])", formula, re.I) for n in names)
    return False


# ---------------------------------------------------------------- traduction
def _range_text(sheet_name, r0, c0, r1, c1) -> str:
    body = f"{R.cell_name(r0, c0, True, True)}" if (r0, c0) == (r1, c1) else \
        f"{R.cell_name(r0, c0, True, True)}:{R.cell_name(r1, c1, True, True)}"
    return R.quote_sheet(sheet_name) + "!" + body


def _resolve(book, own_sheet, row, col, table_name, spec):
    if table_name:
        found = find(book, table_name)
        if found is None:
            return "#REF!"
        sheet, table = found
    else:
        table = at(own_sheet, row, col)
        if table is None:
            return "#REF!"
        sheet = own_sheet
    try:
        specials, cols, this_row = _parse_spec(spec)
    except ValueError:
        return "#REF!"
    r0, c0, r1, c1 = table["ref"]
    first, last = data_rows(table)
    if cols is not None:
        names = [n.lower() for n in columns(book, sheet, table)]
        try:
            a, b = names.index(cols[0].strip().lower()), names.index(cols[1].strip().lower())
        except ValueError:
            return "#REF!"
        ca, cb = c0 + min(a, b), c0 + max(a, b)
    else:
        ca, cb = c0, c1
    if this_row:
        if sheet is not own_sheet or not first <= row <= last:
            return "#VALUE!"
        return _range_text(sheet.name, row, ca, row, cb)
    sections = specials or ["#data"]
    rows = []
    for section in sections:
        if section == "#all":
            rows += [r0, r1]
        elif section == "#data":
            if first <= last:
                rows += [first, last]
        elif section == "#headers":
            if not table.get("header", True):
                return "#REF!"
            rows += [r0, r0]
        elif section == "#totals":
            if not table.get("totals"):
                return "#REF!"
            rows += [r1, r1]
    if not rows:
        return "#REF!"
    return _range_text(sheet.name, min(rows), ca, max(rows), cb)


def resolve(formula: str, book, sheet, row: int, col: int) -> str:
    """Formule du classeur -> formule pour le moteur (références structurées en plages A1, noms de tableau seuls =
    leur corps de données)."""
    tables = [t["name"] for _s, t in all_tables(book)]
    if not tables and "[" not in formula:
        return formula
    out = []
    last = 0
    for start, end, name, spec in iter_structured(formula):
        out.append(formula[last:start])
        out.append(_resolve(book, sheet, row, col, name, spec))
        last = end
    out.append(formula[last:])
    text = "".join(out)
    if tables:
        lower = {n.lower() for n in tables}

        def bare(m):
            word = m.group(0)
            return _resolve(book, sheet, row, col, word, "") if word.lower() in lower else word
        text = _replace_outside_strings(text, re.compile(r"(?<![\w.$!'])[A-Za-z_\\À-￿][\w.À-￿]*"
                                                         r"(?![\w.\[(!])"), bare)
    return text


def _replace_outside_strings(text, pattern, fn):
    out = []
    last = 0
    i = 0
    n = len(text)
    while i < n:
        if text[i] in "\"'":
            quote = text[i]
            j = i + 1
            while j < n:
                if text[j] == quote:
                    if j + 1 < n and text[j + 1] == quote:
                        j += 2
                        continue
                    break
                j += 1
            out.append(pattern.sub(fn, text[last:i]))
            out.append(text[i:j + 1])
            last = i = j + 1
            continue
        i += 1
    out.append(pattern.sub(fn, text[last:]))
    return "".join(out)


def to_file_syntax(formula: str, sheet, row: int, col: int) -> str:
    """Écriture d'un .xlsx : Excel range `[@Col]` sous la forme longue `T[[#This Row],[Col]]`."""
    if "[@" not in formula and "@" not in formula:
        return formula
    out = []
    last = 0
    for start, end, name, spec in iter_structured(formula):
        inner = spec.strip()
        if inner.startswith("@"):
            table = at(sheet, row, col) if name is None else None
            table_name = name or (table["name"] if table else None)
            if table_name is None:
                continue
            rest = inner[1:].strip()
            if rest.startswith("[") and rest.endswith("]"):
                rest = rest[1:-1]
            new = f"{table_name}[[#This Row]" + (f",[{rest}]]" if rest else "]")
            out.append(formula[last:start])
            out.append(new)
            last = end
    out.append(formula[last:])
    return "".join(out)
