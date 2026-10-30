"""Opérations du tableur (SANS Qt) : chacune construit des commandes (`commands.py`) — une étape d'annulation.

Saisie, effacement, styles, copier / couper / coller (formules recopiées comme Excel), recopie incrémentée (poignée
de recopie), tri, filtre automatique, fusion, lignes / colonnes, feuilles, rechercher / remplacer, doublons.
Une plage = (r0, c0, r1, c1) inclusive, indices à partir de 0."""
from __future__ import annotations

import copy
import datetime as _dt
import re

from . import commands as C
from . import numfmt
from . import refs as R
from . import values as V
from .document import Cell, Sheet, Workbook
from .engine import cell_value

PER_CELL_LIMIT = 500_000                 # au-delà, la mise en forme passe par les styles de ligne / colonne


def norm(rect):
    r0, c0, r1, c1 = rect
    return min(r0, r1), min(c0, c1), max(r0, r1), max(c0, c1)


def clip_to_used(sheet: Sheet, rect):
    """Plage ramenée à la zone utilisée (colonnes / lignes entières)."""
    used = sheet.used_range()
    r0, c0, r1, c1 = norm(rect)
    if used is None:
        return None
    r0, c0 = max(r0, used[0]), max(c0, used[1])
    r1, c1 = min(r1, used[2]), min(c1, used[3])
    if r0 > r1 or c0 > c1:
        return None
    return r0, c0, r1, c1


def cells_in(sheet: Sheet, rect):
    """Cellules existantes d'une plage : (clé, cellule) ; parcourt le plus petit des deux (plage / feuille)."""
    r0, c0, r1, c1 = norm(rect)
    area = (r1 - r0 + 1) * (c1 - c0 + 1)
    if area <= len(sheet.cells):
        get = sheet.cells.get
        for r in range(r0, r1 + 1):
            for c in range(c0, c1 + 1):
                cell = get((r, c))
                if cell is not None:
                    yield (r, c), cell
    else:
        for key, cell in list(sheet.cells.items()):
            if r0 <= key[0] <= r1 and c0 <= key[1] <= c1:
                yield key, cell


# ---------------------------------------------------------------- saisie
def input_cell(book: Workbook, sheet: Sheet, row: int, col: int, text: str, loc=numfmt.DEFAULT_LOCALE,
               date_order: str = "dmy") -> Cell | None:
    """Cellule résultant d'une saisie (style gardé ; format implicite d'une date / % / monnaie posé)."""
    old = sheet.cell(row, col)
    style = old.style if old is not None else sheet.style_index(row, col)
    parsed = V.parse_input(text, loc.decimal, date_order)
    if parsed.formula is None and parsed.value is None:
        return Cell(None, None, style) if style else None
    current_fmt = book.styles.get(style).get("fmt")
    if parsed.formula is None and current_fmt == "@":
        return Cell(text, None, style)                # cellule au format Texte : gardé tel quel
    if parsed.fmt and (not current_fmt or current_fmt == numfmt.GENERAL
                       or numfmt.is_date_code(parsed.fmt) != numfmt.is_date_code(current_fmt)):
        style = book.styles.merged(style, {"fmt": parsed.fmt})
    return Cell(parsed.value, parsed.formula, style)


def set_input(book, stack, sheet, row, col, text, loc=numfmt.DEFAULT_LOCALE, rect=None, date_order="dmy"):
    """Saisie validée (Entrée) ; `rect` donné (Ctrl+Entrée) : même saisie dans toute la plage, formules recopiées."""
    if rect is None:
        stack.begin("Saisir")
        old_names = None
        if sheet.tables:
            from . import structured
            table = structured.at(sheet, row, col)
            if table is not None and row == table["ref"][0] and table.get("header", True):
                old_names = structured.columns(book, sheet, table)
        engine = book.engine
        hold = old_names is not None and engine is not None
        if hold:
            engine.hold_tables = True                      # entête : UNE retraduction, après réécriture des formules
        try:
            stack.push(C.SetCells(sheet, {(row, col): input_cell(book, sheet, row, col, text, loc, date_order)},
                                  "Saisir"))
            if sheet.tables:                               # tableaux : entête renommée, extension, colonne calculée
                from . import tables_ops
                tables_ops.header_renamed(book, stack, sheet, row, col, old_names)
        finally:
            if hold:
                engine.hold_tables = False
                engine.tables_changed(size_only=True)      # les formules réécrites ont déjà été renvoyées
        if sheet.tables:
            tables_ops.after_input(book, stack, sheet, row, col)
        stack.end()
        return
    r0, c0, r1, c1 = norm(rect)
    changes = {}
    base = input_cell(book, sheet, row, col, text, loc, date_order)
    for r in range(r0, r1 + 1):
        for c in range(c0, c1 + 1):
            cell = input_cell(book, sheet, r, c, text, loc, date_order)
            if cell is not None and base is not None and base.formula:
                cell = cell.with_(formula=R.translate(base.formula, r - row, c - col))
            changes[(r, c)] = cell
    stack.push(C.SetCells(sheet, changes, "Saisir"))


def clear(book, stack, sheet, rect, what: str = "contents"):
    """Effacer : « contents » (Suppr : valeurs et formules), « formats », « all », « comments »."""
    changes = {}
    for key, cell in cells_in(sheet, rect):
        if what == "contents":
            changes[key] = Cell(None, None, cell.style) if cell.style else None
        elif what == "formats":
            changes[key] = cell.with_(style=0)
        elif what == "all":
            changes[key] = None
    stack.begin("Effacer")
    if changes:
        stack.push(C.SetCells(sheet, changes, "Effacer"))
    if what in ("all", "comments", "formats"):
        r0, c0, r1, c1 = norm(rect)

        def mutate(s):
            if what in ("all", "comments"):
                s.comments = {k: v for k, v in s.comments.items() if not (r0 <= k[0] <= r1 and c0 <= k[1] <= c1)}
            if what in ("all", "formats"):
                s.merges = [m for m in s.merges if not (m[0] >= r0 and m[2] <= r1 and m[1] >= c0 and m[3] <= c1)]
        stack.push(C.SheetState(sheet, mutate, "Effacer"))
    stack.end()


# ---------------------------------------------------------------- styles
def apply_style(book, stack, sheet, rect, changes: dict, text: str = "Mise en forme"):
    """Clés de style changées sur une plage (valeur None = retirée). Lignes / colonnes entières : styles de
    ligne / colonne + cellules existantes (jamais un million de cellules créées)."""
    r0, c0, r1, c1 = norm(rect)
    styles = book.styles
    full_cols = r0 == 0 and r1 == R.MAX_ROWS - 1
    full_rows = c0 == 0 and c1 == R.MAX_COLS - 1
    area = (r1 - r0 + 1) * (c1 - c0 + 1)
    stack.begin(text)
    if full_cols or full_rows:
        def mutate(s):
            axis, lo, hi = (s.cols, c0, c1) if full_cols else (s.rows, r0, r1)
            for i in range(lo, hi + 1):
                axis.styles[i] = styles.merged(axis.styles.get(i, 0), changes)
        stack.push(C.SheetState(sheet, mutate, text, kind="cells"))
        cell_changes = {key: cell.with_(style=styles.merged(cell.style, changes))
                        for key, cell in cells_in(sheet, rect)}
    elif area <= PER_CELL_LIMIT:
        cell_changes = {}
        get = sheet.cells.get
        cache = {}
        for r in range(r0, r1 + 1):
            for c in range(c0, c1 + 1):
                cell = get((r, c))
                base = cell.style if cell is not None else sheet.style_index(r, c)
                new = cache.get(base)
                if new is None:
                    new = cache[base] = styles.merged(base, changes)
                if cell is None:
                    if new:
                        cell_changes[(r, c)] = Cell(None, None, new)
                elif new != cell.style:
                    cell_changes[(r, c)] = cell.with_(style=new)
    else:
        cell_changes = {key: cell.with_(style=styles.merged(cell.style, changes))
                        for key, cell in cells_in(sheet, rect)}
    if cell_changes:
        stack.push(C.SetCells(sheet, cell_changes, text))
    stack.end()


def set_borders(book, stack, sheet, rect, kind: str, line=("thin", "#000000")):
    """Bordures façon Excel : « all », « outside », « inside », « top », « bottom », « left », « right », « none »,
    « thick_outside »."""
    r0, c0, r1, c1 = norm(rect)
    if kind == "thick_outside":
        kind, line = "outside", ("medium", line[1])
    styles = book.styles
    changes = {}
    for r in range(r0, r1 + 1):
        for c in range(c0, c1 + 1):
            want = {}
            if kind == "none":
                want = {"border_l": None, "border_r": None, "border_t": None, "border_b": None}
            else:
                if kind in ("all", "outside", "top") and r == r0 or kind in ("all", "inside") and r > r0:
                    want["border_t"] = line
                if kind in ("all", "outside", "bottom") and r == r1 or kind in ("all", "inside") and r < r1:
                    want["border_b"] = line
                if kind in ("all", "outside", "left") and c == c0 or kind in ("all", "inside") and c > c0:
                    want["border_l"] = line
                if kind in ("all", "outside", "right") and c == c1 or kind in ("all", "inside") and c < c1:
                    want["border_r"] = line
            if not want:
                continue
            cell = sheet.cell(r, c)
            base = cell.style if cell is not None else sheet.style_index(r, c)
            new = styles.merged(base, want)
            changes[(r, c)] = Cell(None, None, new) if cell is None else cell.with_(style=new)
    if changes:
        stack.push(C.SetCells(sheet, changes, "Bordures"))


# ---------------------------------------------------------------- presse-papiers
class Block:
    """Cellules copiées : positions relatives, styles en dictionnaires (collables dans un autre classeur)."""

    def __init__(self, sheet_name: str, rect, cells: dict, styles: dict, sizes=None, cut: bool = False):
        self.sheet_name = sheet_name
        self.rect = norm(rect)
        self.cells = cells                     # (dr, dc) -> Cell (style = indice dans `styles`)
        self.styles = styles                   # indice local -> dictionnaire
        self.cut = cut
        self.book_id = None

    @property
    def rows(self):
        return self.rect[2] - self.rect[0] + 1

    @property
    def cols(self):
        return self.rect[3] - self.rect[1] + 1


def copy_block(book, sheet, rect, cut=False) -> Block:
    r0, c0, r1, c1 = norm(rect)
    cells = {}
    styles = {}
    for (r, c), cell in cells_in(sheet, (r0, c0, r1, c1)):
        if sheet.rows.size(r) == 0 and not cut and (r1 > r0):
            continue                                   # lignes filtrées / masquées : pas copiées (Excel)
        if cell.style and cell.style not in styles:
            styles[cell.style] = dict(book.styles.get(cell.style))
        cells[(r - r0, c - c0)] = cell
    block = Block(sheet.name, (r0, c0, r1, c1), cells, styles, cut=cut)
    block.book_id = id(book)
    return block


def paste_block(book, stack, sheet, row, col, block: Block, mode: str = "all", source_sheet: Sheet | None = None,
                target_rect=None):
    """Coller à (row, col) : « all », « values », « formulas », « formats ». Couper : les cellules d'origine sont
    vidées et les références qui les visent suivent (Excel). Une sélection plus grande, multiple du bloc,
    reçoit le bloc répété."""
    reps_r = reps_c = 1
    if target_rect is not None:
        tr0, tc0, tr1, tc1 = norm(target_rect)
        h, w = tr1 - tr0 + 1, tc1 - tc0 + 1
        if h % block.rows == 0 and w % block.cols == 0:
            reps_r, reps_c = h // block.rows, w // block.cols
            row, col = tr0, tc0
    same_book = block.book_id == id(book)
    style_map = {}

    def map_style(local):
        if not local:
            return 0
        if same_book:
            return local
        if local not in style_map:
            style_map[local] = book.styles.intern(block.styles.get(local, {}))
        return style_map[local]

    changes = {}
    r0, c0 = block.rect[0], block.rect[1]
    for rep_r in range(reps_r):
        for rep_c in range(reps_c):
            base_r = row + rep_r * block.rows
            base_c = col + rep_c * block.cols
            for dr in range(block.rows):
                for dc in range(block.cols):
                    tr, tc = base_r + dr, base_c + dc
                    if tr >= R.MAX_ROWS or tc >= R.MAX_COLS:
                        continue
                    src = block.cells.get((dr, dc))
                    old = sheet.cell(tr, tc)
                    old_style = old.style if old is not None else 0
                    if src is None:
                        if mode in ("all", "values", "formulas"):
                            changes[(tr, tc)] = (Cell(None, None, old_style) if old_style and mode != "all"
                                                 else None)
                        if mode == "formats":
                            changes[(tr, tc)] = old.with_(style=0) if old is not None else None
                        continue
                    if mode == "formats":
                        changes[(tr, tc)] = (old or Cell()).with_(style=map_style(src.style))
                        continue
                    formula = src.formula
                    value = src.value
                    if formula and not block.cut:
                        formula = R.translate(formula, tr - (r0 + dr), tc - (c0 + dc))
                    if mode == "values":
                        if src.formula and source_sheet is not None:
                            value = cell_value(book, source_sheet, r0 + dr, c0 + dc)
                        formula = None
                        style = old_style
                    else:
                        style = map_style(src.style) if mode == "all" else old_style
                    changes[(tr, tc)] = Cell(value, formula, style)
    stack.begin("Coller" if not block.cut else "Déplacer")
    if block.cut and source_sheet is not None:
        cut_changes = {}
        dr, dc = row - r0, col - c0
        for (r, c) in [(r0 + k[0], c0 + k[1]) for k in block.cells]:
            if (r, c) not in changes:
                cut_changes[(r, c)] = None
        if cut_changes:
            stack.push(C.SetCells(source_sheet, cut_changes, "Couper"))
        # références qui visent les cellules déplacées : elles suivent
        moved = {}
        for other in book.sheets:
            other_changes = {}
            for key, cell in other.cells.items():
                if cell.formula:
                    new = R.move_refs(cell.formula, other.name, source_sheet.name, block.rect, dr, dc,
                                      to_sheet=sheet.name)
                    if new != cell.formula:
                        other_changes[key] = cell.with_(formula=new)
            if other_changes:
                moved[other.uid] = (other, other_changes)
        for _uid, (other, other_changes) in moved.items():
            stack.push(C.SetCells(other, other_changes, "Déplacer"))
        for key, cell in list(changes.items()):
            if cell is not None and cell.formula:
                new = R.move_refs(cell.formula, sheet.name, source_sheet.name, block.rect, dr, dc,
                                  to_sheet=sheet.name)
                changes[key] = cell.with_(formula=new)
    stack.push(C.SetCells(sheet, changes, "Coller"))
    stack.end()
    return (row, col, row + block.rows * reps_r - 1, col + block.cols * reps_c - 1)


def block_to_text(book, sheet, rect, loc=numfmt.DEFAULT_LOCALE) -> str:
    """Texte tabulé (autres logiciels, Excel compris) : valeurs AFFICHÉES."""
    r0, c0, r1, c1 = norm(rect)
    lines = []
    for r in range(r0, r1 + 1):
        if sheet.rows.size(r) == 0 and r1 > r0:
            continue
        row = []
        for c in range(c0, c1 + 1):
            row.append(display_text(book, sheet, r, c, loc)[0].replace("\t", " ").replace("\n", " "))
        lines.append("\t".join(row))
    return "\r\n".join(lines) + ("\r\n" if lines else "")


def text_to_cells(book, sheet, row, col, text: str, loc=numfmt.DEFAULT_LOCALE, date_order="dmy") -> dict:
    """Texte tabulé collé (Excel, navigateur…) -> cellules typées."""
    rows = text.replace("\r\n", "\n").replace("\r", "\n").split("\n")
    if rows and rows[-1] == "":
        rows.pop()
    changes = {}
    for dr, line in enumerate(rows):
        for dc, part in enumerate(line.split("\t")):
            if row + dr < R.MAX_ROWS and col + dc < R.MAX_COLS:
                changes[(row + dr, col + dc)] = input_cell(book, sheet, row + dr, col + dc, part, loc, date_order)
    return changes


# ---------------------------------------------------------------- affichage
def display_text(book, sheet, row, col, loc=numfmt.DEFAULT_LOCALE, show_formulas=False):
    """(texte affiché, couleur imposée par le format, valeur) d'une cellule."""
    cell = sheet.cells.get((row, col))
    if show_formulas and cell is not None and cell.formula:
        return cell.formula, None, cell.formula
    value = cell_value(book, sheet, row, col)
    if value is None:
        return "", None, None
    if isinstance(value, V.XLError):
        return value.code, None, value
    style = book.styles.get(sheet.style_index(row, col))
    fmt = style.get("fmt") or numfmt.GENERAL
    if (fmt == numfmt.GENERAL and cell is not None and cell.formula and book.engine is not None
            and book.engine.available):
        kind = V.engine_kind(book.engine.raw(sheet, row, col))
        if kind == "date":
            fmt = "dd/mm/yyyy"
        elif kind == "datetime":
            fmt = "dd/mm/yyyy hh:mm"
        elif kind == "time":
            fmt = "hh:mm:ss"
    text, color = numfmt.format_value(value, fmt, loc)
    return text, color, value


# ---------------------------------------------------------------- recopie incrémentée
_LISTS = [
    numfmt.DAYS["fr"], numfmt.DAYS_SHORT["fr"], numfmt.MONTHS["fr"], numfmt.MONTHS_SHORT["fr"],
    numfmt.DAYS["en"], numfmt.DAYS_SHORT["en"], numfmt.MONTHS["en"], numfmt.MONTHS_SHORT["en"],
]
_TRAILING_NUMBER = re.compile(r"^(.*?)(\d+)(\D*)$")


def _find_list(text: str):
    low = text.strip().lower()
    for items in _LISTS:
        lowered = [i.lower() for i in items]
        if low in lowered:
            return items, lowered.index(low)
    return None


def _series(book, sheet, sources: list[tuple[tuple[int, int], Cell | None]], count: int, step_sign: int,
            copy_only: bool):
    """Valeurs prolongeant une suite de cellules (dans l'ordre de la recopie) sur `count` positions."""
    cells = [c for _k, c in sources]
    n = len(cells)
    out = []
    if not n:
        return [None] * count
    styles = [c.style if c is not None else 0 for c in cells]
    numeric = all(c is not None and not c.formula and isinstance(c.value, (int, float))
                  and not isinstance(c.value, bool) for c in cells)
    if numeric and not copy_only and (n >= 2 or numfmt.is_date_code(book.styles.get(styles[0]).get("fmt", ""))):
        values = [float(c.value) for c in cells]
        fmt = book.styles.get(styles[-1]).get("fmt", "")
        if numfmt.is_date_code(fmt) and n >= 2:
            dates = [numfmt.serial_to_datetime(v) for v in values]
            if all(d is not None for d in dates) and len({d.day for d in dates}) == 1 and \
                    all(v == int(v) for v in values) and len(dates) >= 2 and \
                    (dates[1].month != dates[0].month or dates[1].year != dates[0].year):
                months = (dates[1].year - dates[0].year) * 12 + dates[1].month - dates[0].month
                last = dates[-1]
                for i in range(1, count + 1):
                    m = last.month - 1 + months * i
                    year, month = last.year + m // 12, m % 12 + 1
                    day = min(last.day, [31, 29 if year % 4 == 0 and (year % 100 or year % 400 == 0) else 28,
                                         31, 30, 31, 30, 31, 31, 30, 31, 30, 31][month - 1])
                    out.append(Cell(numfmt.datetime_to_serial(_dt.date(year, month, day)), None, styles[-1]))
                return out
        if n == 1:
            step = 1.0
        else:
            xs = list(range(n))
            mx = sum(xs) / n
            my = sum(values) / n
            den = sum((x - mx) ** 2 for x in xs)
            step = sum((x - mx) * (y - my) for x, y in zip(xs, values)) / den if den else 0.0
            intercept = my - step * mx
        for i in range(1, count + 1):
            if n == 1:
                v = values[0] + step * i
            else:
                v = intercept + step * (n - 1 + i)
            v = round(v, 12)
            out.append(Cell(int(v) if float(v).is_integer() and abs(v) < 2 ** 53 else v, None,
                            styles[(n - 1 + i) % n] if n > 1 else styles[0]))
        return out
    for i in range(count):
        index = i % n
        src = cells[index]
        if src is None:
            out.append(None)
            continue
        cycles = i // n + 1
        if src.formula:
            (sr, sc), _cell = sources[index]
            out.append(src)                             # recopie des formules : faite par l'appelant (décalage)
            continue
        value = src.value
        if not copy_only and isinstance(value, str):
            found = _find_list(value)
            if found:
                items, pos = found
                k = n if n > 1 and all(isinstance(c.value, str) and _find_list(c.value) for c in cells
                                       if c is not None) else 1
                text = items[(pos + cycles * k * step_sign) % len(items)]
                if value.isupper():
                    text = text.upper()
                elif value[:1].isupper():
                    text = text[:1].upper() + text[1:]
                out.append(src.with_(value=text))
                continue
            m = _TRAILING_NUMBER.match(value)
            if m:
                number = int(m.group(2)) + cycles * (n if n > 1 else 1) * step_sign
                if number >= 0:
                    out.append(src.with_(value=f"{m.group(1)}{str(number).zfill(len(m.group(2)))}{m.group(3)}"))
                    continue
        if not copy_only and n == 1 and isinstance(value, (int, float)) and not isinstance(value, bool) \
                and numfmt.is_date_code(book.styles.get(src.style).get("fmt", "")):
            out.append(src.with_(value=value + cycles * step_sign))
            continue
        out.append(src)
    return out


def fill(book, stack, sheet, source, target, copy_only: bool = False):
    """Poignée de recopie : `source` (plage d'origine) étendue jusqu'à `target` (plage d'arrivée qui la contient).
    Suites (nombres, dates, textes numérotés, jours, mois), formules recopiées avec leurs références relatives."""
    s0r, s0c, s1r, s1c = norm(source)
    t0r, t0c, t1r, t1c = norm(target)
    changes = {}
    if t1r > s1r or t0r < s0r:                         # vers le bas / le haut
        down = t1r > s1r
        count = (t1r - s1r) if down else (s0r - t0r)
        for c in range(s0c, s1c + 1):
            keys = [(r, c) for r in range(s0r, s1r + 1)]
            if not down:
                keys.reverse()
            sources = [(k, sheet.cell(*k)) for k in keys]
            new = _series(book, sheet, sources, count, 1 if down else -1, copy_only)
            for i, cell in enumerate(new):
                r = s1r + 1 + i if down else s0r - 1 - i
                src_key = sources[i % len(sources)][0]
                if cell is not None and cell.formula:
                    cell = cell.with_(formula=R.translate(cell.formula, r - src_key[0], 0))
                changes[(r, c)] = cell
    elif t1c > s1c or t0c < s0c:                       # vers la droite / la gauche
        right = t1c > s1c
        count = (t1c - s1c) if right else (s0c - t0c)
        for r in range(s0r, s1r + 1):
            keys = [(r, c) for c in range(s0c, s1c + 1)]
            if not right:
                keys.reverse()
            sources = [(k, sheet.cell(*k)) for k in keys]
            new = _series(book, sheet, sources, count, 1 if right else -1, copy_only)
            for i, cell in enumerate(new):
                c = s1c + 1 + i if right else s0c - 1 - i
                src_key = sources[i % len(sources)][0]
                if cell is not None and cell.formula:
                    cell = cell.with_(formula=R.translate(cell.formula, 0, c - src_key[1]))
                changes[(r, c)] = cell
    if changes:
        stack.push(C.SetCells(sheet, changes, "Recopier"))


# ---------------------------------------------------------------- tri
def _sort_key(value, ascending):
    """Ordre d'Excel : nombres < textes < logiques < erreurs ; vides toujours à la fin."""
    if value is None or value == "":
        return (1, 0, 0)
    if isinstance(value, bool):
        rank, inner = 2, value
    elif isinstance(value, (int, float)):
        rank, inner = 0, value
    elif isinstance(value, V.XLError):
        rank, inner = 3, 0
    else:
        rank, inner = 1, str(value).casefold()
    if not ascending:
        rank = 3 - rank
        if isinstance(inner, (int, float)) and not isinstance(inner, bool):
            inner = -inner
        elif isinstance(inner, str):
            inner = _Reverse(inner)
        else:
            inner = -int(inner)
    return (0, rank, inner)


class _Reverse:
    __slots__ = ("s",)

    def __init__(self, s):
        self.s = s

    def __lt__(self, other):
        return self.s > other.s

    def __eq__(self, other):
        return self.s == other.s


def sort_range(book, stack, sheet, rect, keys: list[tuple[int, bool]], header: bool = False):
    """Tri des lignes de `rect` selon `keys` = [(colonne absolue, croissant)] ; tri STABLE (Excel)."""
    r0, c0, r1, c1 = norm(rect)
    if header:
        r0 += 1
    if r0 >= r1:
        return
    rows = list(range(r0, r1 + 1))
    snapshot = {r: {c: sheet.cell(r, c) for c in range(c0, c1 + 1)} for r in rows}
    values = {r: {col: cell_value(book, sheet, r, col) for col, _asc in keys} for r in rows}
    order = rows[:]
    for col, ascending in reversed(keys):
        order.sort(key=lambda r, col=col, asc=ascending: _sort_key(values[r][col], asc))
    changes = {}
    for new_r, old_r in zip(rows, order):
        for c in range(c0, c1 + 1):
            cell = snapshot[old_r][c]
            if cell is not None and cell.formula and new_r != old_r:
                cell = cell.with_(formula=R.translate(cell.formula, new_r - old_r, 0))
            changes[(new_r, c)] = cell
    stack.push(C.SetCells(sheet, changes, "Trier"))


# ---------------------------------------------------------------- filtre automatique
def set_autofilter(book, stack, sheet, rect):
    """Pose / retire (rect None) le filtre automatique (la plage commence par la ligne d'entête)."""
    def mutate(s):
        if rect is None or s.autofilter is not None:
            for r in list(s.rows.hidden):
                if s.autofilter and s.autofilter[0] < r <= s.autofilter[2]:
                    s.rows.hidden.discard(r)
            s.autofilter = None
            s.filters = {}
        else:
            s.autofilter = norm(rect)
    stack.push(C.SheetState(sheet, mutate, "Filtrer", kind="structure"))


def filter_values(book, sheet, col) -> list[str]:
    """Valeurs affichées distinctes d'une colonne du filtre (ordre d'Excel)."""
    if sheet.autofilter is None:
        return []
    r0, _c0, r1, _c1 = sheet.autofilter
    seen = {}
    for r in range(r0 + 1, r1 + 1):
        text, _color, value = display_text(book, sheet, r, col)
        seen.setdefault(text, value)
    return [t for t, _v in sorted(seen.items(), key=lambda tv: _sort_key(tv[1], True))]


def apply_filter(book, stack, sheet, col, allowed: set[str] | None):
    """Critère d'une colonne : textes affichés gardés (None = tout). Lignes non retenues masquées."""
    def mutate(s):
        if allowed is None:
            s.filters.pop(col, None)
        else:
            s.filters[col] = {"values": sorted(allowed)}
        r0, _c0, r1, _c1 = s.autofilter
        for r in range(r0 + 1, r1 + 1):
            keep = all(display_text(book, s, r, fc)[0] in set(rule["values"]) for fc, rule in s.filters.items())
            if keep:
                s.rows.hidden.discard(r)
            else:
                s.rows.hidden.add(r)
        s.rows.changed()
    stack.push(C.SheetState(sheet, mutate, "Filtrer", kind="structure"))


# ---------------------------------------------------------------- fusion
def merge(book, stack, sheet, rect, across: bool = False, center: bool = False):
    """Fusionner (le contenu de la cellule en haut à gauche est gardé, les autres vidés, comme Excel)."""
    r0, c0, r1, c1 = norm(rect)
    if (r0, c0) == (r1, c1):
        return
    stack.begin("Fusionner")
    changes = {key: Cell(None, None, cell.style) if cell.style else None
               for key, cell in cells_in(sheet, rect) if key != (r0, c0) and not cell.is_blank()}
    if changes:
        stack.push(C.SetCells(sheet, changes, "Fusionner"))
    pieces = [(r, c0, r, c1) for r in range(r0, r1 + 1)] if across else [(r0, c0, r1, c1)]

    def mutate(s):
        s.merges = [m for m in s.merges if m[2] < r0 or m[0] > r1 or m[3] < c0 or m[1] > c1] + pieces
    stack.push(C.SheetState(sheet, mutate, "Fusionner", kind="cells"))
    if center:
        apply_style(book, stack, sheet, (r0, c0, r0, c0), {"halign": "center", "valign": "center"})
    stack.end()


def unmerge(book, stack, sheet, rect):
    r0, c0, r1, c1 = norm(rect)

    def mutate(s):
        s.merges = [m for m in s.merges if m[2] < r0 or m[0] > r1 or m[3] < c0 or m[1] > c1]
    stack.push(C.SheetState(sheet, mutate, "Annuler la fusion", kind="cells"))


# ---------------------------------------------------------------- lignes, colonnes, tailles
def insert_lines(book, stack, sheet, axis, at, count=1):
    stack.push(C.Lines(sheet, axis, at, count, delete=False))


def delete_lines(book, stack, sheet, axis, at, count=1):
    stack.push(C.Lines(sheet, axis, at, count, delete=True))


def set_sizes(book, stack, sheet, axis, indices, size):
    """Largeur de colonnes / hauteur de lignes (pixels à 100 %) ; None = taille par défaut."""
    def mutate(s):
        target = s.rows if axis == "row" else s.cols
        for i in indices:
            if size is None:
                target.sizes.pop(i, None)
            else:
                target.sizes[i] = max(0.0, float(size))
    stack.push(C.SheetState(sheet, mutate, "Taille", kind="structure"))


def set_hidden(book, stack, sheet, axis, indices, hidden: bool):
    def mutate(s):
        target = s.rows if axis == "row" else s.cols
        for i in indices:
            if hidden:
                target.hidden.add(i)
            else:
                target.hidden.discard(i)
    stack.push(C.SheetState(sheet, mutate, "Masquer" if hidden else "Afficher", kind="structure"))


def set_sheet_attr(book, stack, sheet, text, **attrs):
    def mutate(s):
        for key, value in attrs.items():
            setattr(s, key, value)
    stack.push(C.SheetState(sheet, mutate, text, kind="structure" if "freeze" in attrs else "view"))


def autofit(book, sheet, axis, index, measure) -> float | None:
    """Taille ajustée au contenu (double-clic sur la séparation) ; `measure(texte, style) -> (largeur, hauteur)`."""
    best = 0.0
    found = False
    for (r, c), _cell in list(sheet.cells.items()):
        if (c if axis == "col" else r) != index:
            continue
        text = display_text(book, sheet, r, c)[0]
        if not text:
            continue
        w, h = measure(text, book.styles.get(sheet.style_index(r, c)))
        best = max(best, (w + 8) if axis == "col" else (h + 4))
        found = True
    return best if found else None


# ---------------------------------------------------------------- feuilles
def add_sheet(book, stack, index=None, name=None) -> Sheet:
    command = C.SheetsCommand("add", "Ajouter une feuille", name=name or book.unique_name(),
                              index=len(book.sheets) if index is None else index)
    stack.push(command)
    return command.args["sheet"]


def duplicate_sheet(book, stack, sheet) -> Sheet:
    base = re.sub(r" \(\d+\)$", "", sheet.name)
    name = book.unique_name(base)
    clone = Sheet(name)
    clone.cells = dict(sheet.cells)
    clone.restore(copy.deepcopy(sheet.state()))
    for attr in ("show_grid", "zoom", "tab_color", "protected"):
        setattr(clone, attr, getattr(sheet, attr))
    clone.extra = copy.deepcopy(sheet.extra)
    command = C.SheetsCommand("add", "Dupliquer la feuille", sheet=clone, index=book.index_of(sheet) + 1)
    stack.push(command)
    return clone


def remove_sheet(book, stack, sheet):
    if len(book.sheets) <= 1:
        return False
    stack.push(C.SheetsCommand("remove", "Supprimer la feuille", uid=sheet.uid))
    return True


def rename_sheet(book, stack, sheet, name):
    stack.push(C.SheetsCommand("rename", "Renommer la feuille", uid=sheet.uid, name=name.strip()))


def move_sheet(book, stack, sheet, index):
    stack.push(C.SheetsCommand("move", "Déplacer la feuille", uid=sheet.uid, index=index))


# ---------------------------------------------------------------- rechercher / remplacer
def find_all(book, sheet_list, needle: str, in_formulas=True, match_case=False, whole=False, loc=None):
    """[(feuille, ligne, colonne)] des cellules qui contiennent `needle` (texte affiché ou formule)."""
    loc = loc or numfmt.DEFAULT_LOCALE
    if not needle:
        return []
    probe = needle if match_case else needle.casefold()
    out = []
    for sheet in sheet_list:
        for (r, c), cell in sorted(sheet.cells.items()):
            texts = [display_text(book, sheet, r, c, loc)[0]]
            if in_formulas and cell.formula:
                texts.append(cell.formula)
            for text in texts:
                hay = text if match_case else text.casefold()
                if (hay == probe) if whole else (probe in hay):
                    out.append((sheet, r, c))
                    break
    return out


def replace_all(book, stack, sheet_list, needle, repl, match_case=False, whole=False, loc=None) -> int:
    loc = loc or numfmt.DEFAULT_LOCALE
    flags = 0 if match_case else re.IGNORECASE
    pattern = re.compile(("^" + re.escape(needle) + "$") if whole else re.escape(needle), flags)
    total = 0
    stack.begin("Remplacer")
    for sheet in sheet_list:
        changes = {}
        for (r, c), cell in list(sheet.cells.items()):
            source = cell.formula or (V.edit_text(cell.value, None, book.styles.get(cell.style).get("fmt"), loc)
                                      if cell.value is not None else "")
            new, n = pattern.subn(repl.replace("\\", "\\\\"), source)
            if n:
                total += n
                changes[(r, c)] = input_cell(book, sheet, r, c, new, loc)
        if changes:
            stack.push(C.SetCells(sheet, changes, "Remplacer"))
    stack.end()
    return total


def remove_duplicates(book, stack, sheet, rect, cols: list[int], header=True) -> int:
    """Lignes en double (sur `cols`) retirées de la plage ; les suivantes remontent. Rend le nombre retiré."""
    r0, c0, r1, c1 = norm(rect)
    start = r0 + (1 if header else 0)
    seen = set()
    kept = []
    for r in range(start, r1 + 1):
        key = tuple(display_text(book, sheet, r, c)[0].casefold() for c in cols)
        if key in seen:
            continue
        seen.add(key)
        kept.append(r)
    removed = (r1 - start + 1) - len(kept)
    if not removed:
        return 0
    changes = {}
    for i, old_r in enumerate(kept):
        new_r = start + i
        for c in range(c0, c1 + 1):
            cell = sheet.cell(old_r, c)
            if cell is not None and cell.formula and new_r != old_r:
                cell = cell.with_(formula=R.translate(cell.formula, new_r - old_r, 0))
            changes[(new_r, c)] = cell
    for r in range(start + len(kept), r1 + 1):
        for c in range(c0, c1 + 1):
            changes[(r, c)] = None
    stack.push(C.SetCells(sheet, changes, "Supprimer les doublons"))
    return removed


def text_to_columns(book, stack, sheet, rect, sep: str, loc=numfmt.DEFAULT_LOCALE):
    """Texte d'une colonne découpé sur `sep` vers les colonnes à droite."""
    r0, c0, r1, _c1 = norm(rect)
    changes = {}
    for r in range(r0, r1 + 1):
        cell = sheet.cell(r, c0)
        if cell is None or cell.formula or not isinstance(cell.value, str):
            continue
        for i, part in enumerate(cell.value.split(sep)):
            if c0 + i < R.MAX_COLS:
                changes[(r, c0 + i)] = input_cell(book, sheet, r, c0 + i, part.strip(), loc)
    if changes:
        stack.push(C.SetCells(sheet, changes, "Convertir"))
