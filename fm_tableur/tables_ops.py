"""Opérations sur les tableaux structurés (SANS Qt), une étape d'annulation chacune — comme Excel :

- créer (Ctrl+T / Ctrl+L) sur la sélection ou la zone de données ; entêtes détectées ou « Colonne1… » ajoutées ;
- convertir en plage (le tableau disparaît, les données et formules restent ; les références structurées des
  formules deviennent des plages A1 ordinaires) ;
- renommer (les formules qui citent l'ancien nom suivent), style à bandes, ligne des totaux (SUBTOTAL(109,…)) ;
- EXTENSION AUTOMATIQUE : une saisie dans la ligne juste sous le tableau (ou la colonne juste à droite) l'agrandit ;
- COLONNE CALCULÉE : une formule saisie dans une colonne du tableau dont les autres cellules sont vides est
  recopiée sur toute la colonne.
Le texte des formules garde la syntaxe d'Excel ; la traduction pour le moteur est dans `structured.py`."""
from __future__ import annotations

import re

from . import commands as C
from . import refs as R
from . import structured as T
from .document import Cell
from .engine import cell_value


def _looks_like_header(book, sheet, rect) -> bool:
    r0, c0, r1, c1 = rect
    first = [cell_value(book, sheet, r0, c) for c in range(c0, c1 + 1)]
    if not any(isinstance(v, str) for v in first):
        return False
    if r1 == r0:
        return True
    return all(v is None or isinstance(v, str) for v in first)


def create(book, stack, sheet, rect, header: bool | None = None, name: str | None = None, style: str = "bleu"):
    """Tableau sur `rect` (une seule cellule : la zone de données autour). Rend le tableau créé, ou None si la
    plage chevauche un autre tableau ou une fusion."""
    r0, c0, r1, c1 = rect
    if any(not (t["ref"][2] < r0 or t["ref"][0] > r1 or t["ref"][3] < c0 or t["ref"][1] > c1) for t in sheet.tables):
        return None
    if any(not (m[2] < r0 or m[0] > r1 or m[3] < c0 or m[1] > c1) for m in sheet.merges):
        return None
    if header is None:
        header = _looks_like_header(book, sheet, rect)
    table = {"name": name or T.unique_name(book), "ref": (r0, c0, r1, c1), "header": True, "totals": False,
             "style": style, "banded": True, "filter": True, "filters": {}}
    stack.begin("Créer un tableau")
    if not header:                                         # Excel ajoute une ligne d'entêtes au-dessus
        if r0 == 0 or any((r0 - 1, c) in sheet.cells for c in range(c0, c1 + 1)):
            from . import ops
            ops.insert_lines(book, stack, sheet, "row", r0, 1)
            r0, r1 = r0, r1 + 1
        else:
            r0 -= 1
        stack.push(C.SetCells(sheet, {(r0, c): Cell(f"Colonne{i + 1}") for i, c in enumerate(range(c0, c1 + 1))},
                              "Entêtes"))
        table["ref"] = (r0, c0, r1, c1)
    stack.push(C.TablesState(sheet, lambda s: s.tables.append(dict(table)), "Créer un tableau"))
    stack.end()
    return T.find(book, table["name"])[1]


def _rewrite_names(book, stack, fn, text):
    """`fn(formule) -> formule` appliquée à toutes les formules du classeur (une étape)."""
    for sheet in book.sheets:
        changes = {}
        for key, cell in sheet.cells.items():
            if cell.formula:
                new = fn(cell.formula, sheet, key)
                if new != cell.formula:
                    changes[key] = cell.with_(formula=new)
        if changes:
            stack.push(C.SetCells(sheet, changes, text))


def convert_to_range(book, stack, sheet, table):
    """Le tableau devient une plage ordinaire : ses références structurées deviennent des plages A1."""
    name = table["name"]
    stack.begin("Convertir en plage")

    def local(resolved, s, this_row):
        """Plage A1 telle qu'Excel l'écrit après conversion : sans feuille si c'est la même, relative pour @."""
        if resolved.startswith("#"):
            return resolved
        if s is sheet:
            resolved = resolved.rpartition("!")[2]
        return resolved.replace("$", "") if this_row else resolved

    def plain(formula, s, key):
        out = []
        last = 0
        for start, end, tname, spec in T.iter_structured(formula):
            target = tname or (T.at(s, *key) or {}).get("name")
            if target is None or target.lower() != name.lower():
                continue
            this_row = spec.strip().startswith("@") or "#this row" in spec.lower()
            out.append(formula[last:start])
            out.append(local(T._resolve(book, s, key[0], key[1], tname, spec), s, this_row))
            last = end
        out.append(formula[last:])
        return T._replace_outside_strings(
            "".join(out), re.compile(r"(?<![\w.$!'])" + re.escape(name) + r"(?![\w.\[(!])", re.I),
            lambda m: local(T._resolve(book, s, key[0], key[1], name, ""), s, False))
    _rewrite_names(book, stack, plain, "Convertir en plage")

    def mutate(s):
        s.tables = [t for t in s.tables if t["name"] != name]
    stack.push(C.TablesState(sheet, mutate, "Convertir en plage"))
    stack.end()


def rename(book, stack, sheet, table, new_name: str) -> str | None:
    problem = T.valid_name(book, new_name, table)
    if problem:
        return problem
    old = table["name"]
    stack.begin("Renommer le tableau")

    def fn(formula, _s, _k):
        return T._replace_outside_strings(
            formula, re.compile(r"(?<![\w.$!'])" + re.escape(old) + r"(?![\w.(!])", re.I), lambda m: new_name)
    _rewrite_names(book, stack, fn, "Renommer le tableau")

    def mutate(s):
        for t in s.tables:
            if t["name"] == old:
                t["name"] = new_name
    stack.push(C.TablesState(sheet, mutate, "Renommer le tableau"))
    stack.end()
    return None


def set_props(book, stack, sheet, table, text="Style du tableau", **props):
    name = table["name"]

    def mutate(s):
        for t in s.tables:
            if t["name"] == name:
                t.update(props)
    if set(props) <= {"style", "banded"}:
        retranslate = "none"                               # aspect seulement : rien à retraduire
    elif set(props) == {"ref"} and table["ref"][:2] == tuple(props["ref"])[:2] \
            and table["ref"][3] == tuple(props["ref"])[3]:
        retranslate = "size"                               # lignes ajoutées / retirées en bas
    else:
        retranslate = "all"
    stack.push(C.TablesState(sheet, mutate, text, retranslate))


def resize(book, stack, sheet, table, rect, text="Redimensionner le tableau"):
    set_props(book, stack, sheet, table, text, ref=tuple(rect))


def toggle_totals(book, stack, sheet, table):
    """Ligne des totaux (Excel) : « Total » dans la 1re colonne, SUBTOTAL(109,…) sous la dernière colonne."""
    r0, c0, r1, c1 = table["ref"]
    stack.begin("Ligne des totaux")
    if table.get("totals"):
        stack.push(C.SetCells(sheet, {(r1, c): None for c in range(c0, c1 + 1) if (r1, c) in sheet.cells},
                              "Ligne des totaux"))
        set_props(book, stack, sheet, table, "Ligne des totaux", totals=False, ref=(r0, c0, r1 - 1, c1))
    else:
        row = r1 + 1
        if any((row, c) in sheet.cells for c in range(c0, c1 + 1)):
            from . import ops
            ops.insert_lines(book, stack, sheet, "row", row, 1)
        set_props(book, stack, sheet, table, "Ligne des totaux", totals=True, ref=(r0, c0, row, c1))
        last = T.columns(book, sheet, table)[-1]
        quoted = last if re.fullmatch(r"[\w.]+", last) else "[" + re.sub(r"([\[\]#'])", r"'\1", last) + "]"
        changes = {(row, c1): Cell(None, f"=SUBTOTAL(109,{table['name']}[{quoted}])")}
        if c1 > c0:
            changes[(row, c0)] = Cell("Total")
        stack.push(C.SetCells(sheet, changes, "Ligne des totaux"))
    stack.end()


def header_renamed(book, stack, sheet, row, col, old_names):
    """Entête d'un tableau modifiée (Excel) : les formules qui citaient l'ancien nom de colonne suivent."""
    table = T.at(sheet, row, col)
    if table is None or row != table["ref"][0] or not table.get("header", True) or old_names is None:
        return
    index = col - table["ref"][1]
    new_names = T.columns(book, sheet, table)
    old, new = old_names[index], new_names[index]
    if old == new:
        return

    memo = {}

    def fn(formula, s, key):
        if "[" not in formula:
            return formula
        inside = T.at(s, *key)
        memo_key = (formula, s.uid, inside["name"] if inside else None)
        found = memo.get(memo_key)
        if found is None:                                  # même texte, même tableau : même réécriture
            found = memo[memo_key] = T.rename_column_refs(formula, s, key[0], key[1], table, old, new)
        return found
    _rewrite_names(book, stack, fn, "Renommer la colonne")


def after_input(book, stack, sheet, row, col):
    """Après une saisie (même étape d'annulation) : extension automatique et colonne calculée, comme Excel."""
    cell = sheet.cell(row, col)
    if cell is None or cell.is_blank():
        return
    for table in list(sheet.tables):
        r0, c0, r1, c1 = table["ref"]
        if table.get("totals"):
            continue
        if row == r1 + 1 and c0 <= col <= c1:
            resize(book, stack, sheet, table, (r0, c0, row, c1), "Étendre le tableau")
            _extend_calculated(book, stack, sheet, table, row)
            return
        if col == c1 + 1 and r0 <= row <= r1 and T.at(sheet, row, col) is None:
            resize(book, stack, sheet, table, (r0, c0, r1, col), "Étendre le tableau")
            if table.get("header", True) and (r0, col) not in sheet.cells:
                stack.push(C.SetCells(sheet, {(r0, col): Cell(f"Colonne{col - c0 + 1}")}, "Entête"))
            return
    table = T.at(sheet, row, col)
    if table is None or not cell.formula:
        return
    first, last = T.data_rows(table)
    if not first <= row <= last:
        return
    others = [r for r in range(first, last + 1) if r != row]
    if others and all(sheet.cell(r, col) is None or sheet.cell(r, col).is_blank() for r in others):
        stack.push(C.SetCells(sheet, {(r, col): Cell(None, R.translate(cell.formula, r - row, 0), cell.style)
                                      for r in others}, "Colonne calculée"))


def _extend_calculated(book, stack, sheet, table, new_row):
    """Ligne ajoutée sous le tableau : les colonnes calculées (même formule partout au-dessus) la reçoivent."""
    r0, c0, r1, c1 = table["ref"]
    first, _last = T.data_rows({**table, "ref": (r0, c0, new_row - 1, c1)})
    changes = {}
    for c in range(c0, c1 + 1):
        if (new_row, c) in sheet.cells:
            continue
        above = [sheet.cell(r, c) for r in range(first, new_row)]
        if above and all(x is not None and x.formula for x in above):
            base = above[-1]
            pattern = {R.translate(x.formula, new_row - 1 - (first + i), 0) for i, x in enumerate(above)}
            if len(pattern) == 1:
                changes[(new_row, c)] = Cell(None, R.translate(base.formula, 1, 0), base.style)
    if changes:
        stack.push(C.SetCells(sheet, changes, "Colonne calculée"))
