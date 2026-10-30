"""Références A1 (SANS Qt) : noms de colonnes, cellules, plages, et RÉÉCRITURE des formules.

Les formules sont gardées dans la syntaxe d'Excel en anglais (celle des fichiers .xlsx : `=SUM(A1:B2)`, virgule
entre les arguments). Une formule est parcourue par `iter_refs` (chaînes "…" et noms de feuille '…' respectés) ;
chaque référence trouvée peut être remplacée (`rewrite`). Sémantique d'Excel :
- copier / recopier (`translate`) : seules les parties RELATIVES bougent ; hors de la feuille = #REF! ;
- insérer des lignes / colonnes (`shift_insert`) : toute référence (relative OU absolue) au-delà du point bouge ; une
  plage qui contient le point s'agrandit ;
- supprimer (`shift_delete`) : une cellule supprimée = #REF! ; une plage rétrécit ; plage entièrement supprimée = #REF! ;
- renommer une feuille : ses références suivent ; supprimer une feuille : ses références = #REF!.
Indices internes : lignes et colonnes à partir de 0."""
from __future__ import annotations

import re
from dataclasses import dataclass, replace

MAX_ROWS = 1_048_576
MAX_COLS = 16_384
REF_ERROR = "#REF!"


# ---------------------------------------------------------------- noms
def col_name(col: int) -> str:
    """0 -> A, 25 -> Z, 26 -> AA."""
    col += 1
    out = ""
    while col:
        col, rest = divmod(col - 1, 26)
        out = chr(65 + rest) + out
    return out


def col_index(name: str) -> int:
    """A -> 0 ; -1 si ce n'est pas un nom de colonne valable."""
    value = 0
    for ch in name.upper():
        if not "A" <= ch <= "Z":
            return -1
        value = value * 26 + ord(ch) - 64
    return value - 1 if 0 < value <= MAX_COLS else -1


def cell_name(row: int, col: int, row_abs: bool = False, col_abs: bool = False) -> str:
    return f"{'$' if col_abs else ''}{col_name(col)}{'$' if row_abs else ''}{row + 1}"


def range_name(r0: int, c0: int, r1: int, c1: int) -> str:
    a = cell_name(r0, c0)
    return a if (r0, c0) == (r1, c1) else f"{a}:{cell_name(r1, c1)}"


_SHEET_PLAIN = re.compile(r"^[A-Za-z_À-￿][\w.À-￿]*$")


def quote_sheet(name: str) -> str:
    """Nom de feuille tel qu'il s'écrit dans une formule (entre apostrophes si besoin)."""
    if _SHEET_PLAIN.match(name) and not _CELL_ONLY.match(name) and name.upper() not in ("TRUE", "FALSE"):
        return name
    return "'" + name.replace("'", "''") + "'"


# ---------------------------------------------------------------- analyse
@dataclass(frozen=True)
class Part:
    """Une extrémité de référence : `row` None = colonne entière, `col` None = ligne entière."""
    row: int | None
    col: int | None
    row_abs: bool = False
    col_abs: bool = False

    def text(self) -> str:
        out = ""
        if self.col is not None:
            out += ("$" if self.col_abs else "") + col_name(self.col)
        if self.row is not None:
            out += ("$" if self.row_abs else "") + str(self.row + 1)
        return out


@dataclass(frozen=True)
class Ref:
    start: int                  # position dans la formule
    end: int
    sheet: str | None           # nom de la feuille (sans apostrophes), None = feuille de la formule
    a: Part
    b: Part | None              # seconde extrémité d'une plage

    def text(self, sheet_text: str | None = None) -> str:
        prefix = ""
        if self.sheet is not None:
            prefix = (sheet_text if sheet_text is not None else quote_sheet(self.sheet)) + "!"
        body = self.a.text() if self.b is None else f"{self.a.text()}:{self.b.text()}"
        return prefix + body

    def bounds(self) -> tuple[int, int, int, int]:
        """(r0, c0, r1, c1) inclusifs ; colonnes / lignes entières étendues à la feuille."""
        b = self.b or self.a
        r0 = 0 if self.a.row is None else self.a.row
        r1 = MAX_ROWS - 1 if b.row is None else b.row
        c0 = 0 if self.a.col is None else self.a.col
        c1 = MAX_COLS - 1 if b.col is None else b.col
        return min(r0, r1), min(c0, c1), max(r0, r1), max(c0, c1)


_CELL_ONLY = re.compile(r"^\$?[A-Za-z]{1,3}\$?\d+$")
_CELL = r"\$?[A-Za-z]{1,3}\$?\d+"
_REF_BODY = re.compile(
    rf"(?P<cc>{_CELL}:{_CELL})|(?P<c>{_CELL})|(?P<cols>\$?[A-Za-z]{{1,3}}:\$?[A-Za-z]{{1,3}})"
    rf"|(?P<rows>\$?\d+:\$?\d+)")
_PART = re.compile(r"^(\$?)([A-Za-z]{0,3})(\$?)(\d*)$")
_IDENT_CHARS = set("ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789_.$")
_UNQUOTED_SHEET = re.compile(r"[A-Za-z_À-￿][\w.À-￿]*!")


def _part(text: str) -> Part | None:
    m = _PART.match(text)
    if not m:
        return None
    col_abs, letters, row_abs, digits = m.groups()
    col = None
    row = None
    if letters:
        col = col_index(letters)
        if col < 0:
            return None
    if digits:
        row = int(digits) - 1
        if not 0 <= row < MAX_ROWS:
            return None
    if col is None and row is None:
        return None
    return Part(row, col, bool(row_abs), bool(col_abs))


def _body_at(formula: str, pos: int):
    """Référence (sans feuille) commençant à `pos`, ou None."""
    m = _REF_BODY.match(formula, pos)
    if not m:
        return None
    end = m.end()
    if end < len(formula) and (formula[end] in _IDENT_CHARS or formula[end] in "(!["):
        # A1B, LOG10(, Feuille1!…, Tableau[…] : pas une référence (tentative plus courte : A1:B2C -> rien)
        return None
    text = m.group(0)
    if ":" in text:
        left, right = text.split(":")
        a, b = _part(left), _part(right)
        if a is None or b is None:
            return None
        if m.group("cols") and (a.row is not None or b.row is not None):
            return None
        return end, a, b
    a = _part(text)
    if a is None or a.row is None or a.col is None:
        return None
    return end, a, None


def iter_refs(formula: str):
    """Références A1 d'une formule (dans l'ordre), chaînes et noms de feuille respectés."""
    i = 0
    n = len(formula)
    while i < n:
        ch = formula[i]
        if ch == '"':
            j = i + 1
            while j < n:
                if formula[j] == '"':
                    if j + 1 < n and formula[j + 1] == '"':
                        j += 2
                        continue
                    break
                j += 1
            i = j + 1
            continue
        prev = formula[i - 1] if i else ""
        if ch == "'":
            j = i + 1
            while j < n:
                if formula[j] == "'":
                    if j + 1 < n and formula[j + 1] == "'":
                        j += 2
                        continue
                    break
                j += 1
            if j + 1 < n and formula[j + 1] == "!":
                sheet = formula[i + 1:j].replace("''", "'")
                body = _body_at(formula, j + 2)
                if body is not None:
                    end, a, b = body
                    yield Ref(i, end, sheet, a, b)
                    i = end
                    continue
            i = j + 1
            continue
        if prev and (prev in _IDENT_CHARS or prev == "!"):
            i += 1
            continue
        if ch == "[":                                  # références structurées : laissées telles quelles
            depth = 0
            while i < n:
                if formula[i] == "[":
                    depth += 1
                elif formula[i] == "]":
                    depth -= 1
                    if depth == 0:
                        break
                i += 1
            i += 1
            continue
        m = _UNQUOTED_SHEET.match(formula, i)
        if m:
            body = _body_at(formula, m.end())
            if body is not None:
                end, a, b = body
                yield Ref(i, end, formula[i:m.end() - 1], a, b)
                i = end
                continue
        if ch in "$0123456789" or ch.isalpha():
            body = _body_at(formula, i)
            if body is not None:
                end, a, b = body
                yield Ref(i, end, None, a, b)
                i = end
                continue
            # identifiant (nom, fonction) : sauter jusqu'à sa fin
            j = i
            while j < n and (formula[j] in _IDENT_CHARS or formula[j].isalpha()):
                j += 1
            i = max(j, i + 1)
            continue
        i += 1


def rewrite(formula: str, fn) -> str:
    """Remplace chaque référence par `fn(ref)` (texte) ; `fn` rend None pour la garder."""
    out = []
    last = 0
    for ref in iter_refs(formula):
        new = fn(ref)
        if new is None:
            continue
        out.append(formula[last:ref.start])
        out.append(new)
        last = ref.end
    if not out:
        return formula
    out.append(formula[last:])
    return "".join(out)


def _same_sheet(ref: Ref, own: str, target: str) -> bool:
    name = ref.sheet if ref.sheet is not None else own
    return name.lower() == target.lower()


def _ref_error(ref: Ref) -> str:
    return (quote_sheet(ref.sheet) + "!" if ref.sheet is not None else "") + REF_ERROR


# ---------------------------------------------------------------- copier / recopier
def translate(formula: str, drow: int, dcol: int) -> str:
    """Formule copiée de `drow` lignes / `dcol` colonnes : parties relatives décalées (Excel)."""
    if not drow and not dcol:
        return formula

    def move(part: Part) -> Part | None:
        row, col = part.row, part.col
        if row is not None and not part.row_abs:
            row += drow
            if not 0 <= row < MAX_ROWS:
                return None
        if col is not None and not part.col_abs:
            col += dcol
            if not 0 <= col < MAX_COLS:
                return None
        return replace(part, row=row, col=col)

    def fn(ref: Ref):
        a = move(ref.a)
        b = move(ref.b) if ref.b is not None else None
        if a is None or (ref.b is not None and b is None):
            return _ref_error(ref)
        return replace(ref, a=a, b=b).text()

    return rewrite(formula, fn)


# ---------------------------------------------------------------- insérer / supprimer
def shift_insert(formula: str, own_sheet: str, target_sheet: str, axis: str, at: int, count: int) -> str:
    """`count` lignes (`axis` = "row") ou colonnes ("col") insérées avant l'indice `at` de `target_sheet`."""
    key = "row" if axis == "row" else "col"

    def bump(part: Part) -> Part:
        value = getattr(part, key)
        if value is not None and value >= at:
            return replace(part, **{key: value + count})
        return part

    def fn(ref: Ref):
        if not _same_sheet(ref, own_sheet, target_sheet):
            return None
        a = bump(ref.a)
        b = bump(ref.b) if ref.b is not None else None
        if a == ref.a and b == ref.b:
            return None
        if getattr(a, key) is not None and getattr(a, key) >= (MAX_ROWS if key == "row" else MAX_COLS):
            return _ref_error(ref)
        return replace(ref, a=a, b=b).text()

    return rewrite(formula, fn)


def shift_delete(formula: str, own_sheet: str, target_sheet: str, axis: str, at: int, count: int) -> str:
    """`count` lignes / colonnes supprimées à partir de `at` dans `target_sheet`."""
    key = "row" if axis == "row" else "col"
    last = at + count - 1

    def fn(ref: Ref):
        if not _same_sheet(ref, own_sheet, target_sheet):
            return None
        if ref.b is None:
            value = getattr(ref.a, key)
            if value is None or value < at:
                return None
            if value <= last:
                return _ref_error(ref)
            return replace(ref, a=replace(ref.a, **{key: value - count})).text()
        lo_part, hi_part = ref.a, ref.b
        lo, hi = getattr(lo_part, key), getattr(hi_part, key)
        if lo is None or hi is None:                    # colonnes entières (axe ligne) : rien à faire
            return None
        swapped = lo > hi
        if swapped:
            lo, hi = hi, lo
        if hi < at:
            return None
        if lo >= at and hi <= last:
            return _ref_error(ref)
        new_lo = lo if lo < at else (at if lo <= last else lo - count)
        new_hi = hi - count if hi > last else at - 1
        if swapped:
            new_lo, new_hi = new_hi, new_lo
        a = replace(lo_part, **{key: new_lo})
        b = replace(hi_part, **{key: new_hi})
        if a == ref.a and b == ref.b:
            return None
        return replace(ref, a=a, b=b).text()

    return rewrite(formula, fn)


def move_refs(formula: str, own_sheet: str, target_sheet: str, rect: tuple[int, int, int, int], drow: int,
              dcol: int, to_sheet: str | None = None) -> str:
    """Cellules de `rect` déplacées (couper / coller) : les références qui visent une cellule ou une plage ENTIÈREMENT
    dans `rect` suivent (relatives ET absolues), comme Excel. `to_sheet` : autre feuille d'arrivée."""
    r0, c0, r1, c1 = rect

    def inside(part: Part) -> bool:
        return part.row is not None and part.col is not None and r0 <= part.row <= r1 and c0 <= part.col <= c1

    def fn(ref: Ref):
        if not _same_sheet(ref, own_sheet, target_sheet):
            return None
        if not inside(ref.a) or (ref.b is not None and not inside(ref.b)):
            return None
        a = replace(ref.a, row=ref.a.row + drow, col=ref.a.col + dcol)
        b = replace(ref.b, row=ref.b.row + drow, col=ref.b.col + dcol) if ref.b is not None else None
        for part in (a, b):
            if part is not None and not (0 <= part.row < MAX_ROWS and 0 <= part.col < MAX_COLS):
                return _ref_error(ref)
        sheet = ref.sheet
        if to_sheet is not None and to_sheet.lower() != target_sheet.lower():
            sheet = to_sheet
        return replace(ref, a=a, b=b, sheet=sheet).text()

    return rewrite(formula, fn)


# ---------------------------------------------------------------- feuilles
def rename_sheet(formula: str, old: str, new: str) -> str:
    def fn(ref: Ref):
        if ref.sheet is None or ref.sheet.lower() != old.lower():
            return None
        return replace(ref, sheet=new).text()
    return rewrite(formula, fn)


def remove_sheet(formula: str, name: str) -> str:
    def fn(ref: Ref):
        if ref.sheet is None or ref.sheet.lower() != name.lower():
            return None
        return REF_ERROR
    return rewrite(formula, fn)


# ---------------------------------------------------------------- saisie d'une adresse
def parse_cell(text: str) -> tuple[int, int] | None:
    """« B3 » -> (2, 1)."""
    text = text.strip().replace("$", "")
    m = re.fullmatch(r"([A-Za-z]{1,3})(\d+)", text)
    if not m:
        return None
    col = col_index(m.group(1))
    row = int(m.group(2)) - 1
    if col < 0 or not 0 <= row < MAX_ROWS:
        return None
    return row, col


def parse_range(text: str) -> tuple[str | None, tuple[int, int, int, int]] | None:
    """« Feuil2!A1:C4 », « B3 », « A:A », « 2:5 » -> (feuille ou None, (r0, c0, r1, c1))."""
    text = text.strip()
    if not text:
        return None
    refs = list(iter_refs(text))
    if len(refs) != 1 or refs[0].start != 0 or refs[0].end != len(text):
        return None
    return refs[0].sheet, refs[0].bounds()


def referenced_ranges(formula: str, own_sheet: str):
    """(feuille, (r0, c0, r1, c1)) de chaque référence : surlignage pendant l'édition, graphiques."""
    for ref in iter_refs(formula):
        yield (ref.sheet if ref.sheet is not None else own_sheet), ref.bounds(), ref
