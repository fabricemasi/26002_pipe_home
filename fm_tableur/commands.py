"""Commandes annulables (SANS Qt) et pile d'annulation du classeur.

Toute modification du classeur passe par une commande poussée sur `UndoStack` : elle s'applique (`redo`), pousse les
cellules touchées au moteur, recalcule (mode automatique) et prévient les vues (`Workbook.notify`). La pile est
celle du DOCUMENT : la même pour la présentation dans le Board et pour le mode Standard (continuité demandée).

Les cellules étant immuables (voir `document.Cell`), une commande garde les anciennes sans les copier ; une
opération de structure garde la table de la feuille (copie de surface, ~5 ms pour 100 000 cellules)."""
from __future__ import annotations

from . import refs as R
from .document import Sheet, Workbook

UNDO_LIMIT = 300
REBUILD_ABOVE = 40_000          # insertion / suppression touchant plus de cellules : moteur reconstruit


def _engine_push(book: Workbook, sheet: Sheet, keys):
    if book.engine is not None:
        book.engine.push(sheet, keys)


class Command:
    text = ""
    kind = "cells"                     # événement envoyé aux vues : "cells", "structure", "sheets", "view"

    def redo(self, book: Workbook):
        raise NotImplementedError

    def undo(self, book: Workbook):
        raise NotImplementedError

    def sheet(self, book: Workbook):
        return None


class SetCells(Command):
    """Cellules posées / retirées (None) dans une feuille."""

    def __init__(self, sheet: Sheet, changes: dict, text: str = "Modifier"):
        self.uid = sheet.uid
        self.changes = dict(changes)
        self.before: dict = {}
        self.text = text

    def sheet(self, book):
        return book.sheet_by_uid(self.uid)

    def redo(self, book):
        sheet = self.sheet(book)
        cells = sheet.cells
        self.before = {key: cells.get(key) for key in self.changes}
        for (row, col), cell in self.changes.items():
            sheet.put(row, col, cell)
        _engine_push(book, sheet, self.changes)

    def undo(self, book):
        sheet = self.sheet(book)
        for (row, col), cell in self.before.items():
            sheet.put(row, col, cell)
        _engine_push(book, sheet, self.before)


class SheetState(Command):
    """Propriétés d'une feuille hors cellules (tailles, masquage, fusions, volets, graphiques…) : `mutate(sheet)`
    modifie la feuille ; l'état avant / après est gardé."""
    kind = "view"

    def __init__(self, sheet: Sheet, mutate, text: str = "Modifier la feuille", kind: str = "view"):
        self.uid = sheet.uid
        self.mutate = mutate
        self.text = text
        self.kind = kind
        self.before = None
        self.after = None
        self.attrs_before = None
        self.attrs_after = None

    _ATTRS = ("show_grid", "zoom", "tab_color", "hidden", "protected")

    def sheet(self, book):
        return book.sheet_by_uid(self.uid)

    def redo(self, book):
        sheet = self.sheet(book)
        if self.after is None:
            self.before = sheet.state()
            self.attrs_before = {a: getattr(sheet, a) for a in self._ATTRS}
            self.mutate(sheet)
            sheet.rows.changed()
            sheet.cols.changed()
            self.after = sheet.state()
            self.attrs_after = {a: getattr(sheet, a) for a in self._ATTRS}
        else:
            sheet.restore(self.after)
            for a, v in self.attrs_after.items():
                setattr(sheet, a, v)

    def undo(self, book):
        sheet = self.sheet(book)
        sheet.restore(self.before)
        for a, v in self.attrs_before.items():
            setattr(sheet, a, v)


def _shift_rect(rect, axis, at, count, delete):
    """Rectangle (r0, c0, r1, c1) après insertion / suppression ; None s'il disparaît."""
    r0, c0, r1, c1 = rect
    lo, hi = (r0, r1) if axis == "row" else (c0, c1)
    if delete:
        last = at + count - 1
        if hi < at:
            return rect
        if lo >= at and hi <= last:
            return None
        lo = lo if lo < at else (at if lo <= last else lo - count)
        hi = hi - count if hi > last else at - 1
    else:
        if lo >= at:
            lo += count
        if hi >= at:
            hi += count
    return (lo, c0, hi, c1) if axis == "row" else (r0, lo, r1, hi)


def _shift_text(text, own, target, axis, at, count, delete):
    if not text:
        return text
    if delete:
        return R.shift_delete(text, own, target, axis, at, count)
    return R.shift_insert(text, own, target, axis, at, count)


class Lines(Command):
    """Insertion (`delete` faux) ou suppression de `count` lignes / colonnes à partir de `at`."""
    kind = "structure"

    def __init__(self, sheet: Sheet, axis: str, at: int, count: int, delete: bool):
        self.uid = sheet.uid
        self.axis = axis
        self.at = at
        self.count = count
        self.delete = delete
        word = "lignes" if axis == "row" else "colonnes"
        self.text = ("Supprimer des " if delete else "Insérer des ") + word
        self._saved = None

    def sheet(self, book):
        return book.sheet_by_uid(self.uid)

    def redo(self, book):
        sheet = self.sheet(book)
        axis, at, count, delete = self.axis, self.at, self.count, self.delete
        name = sheet.name
        others: dict = {}                              # (uid, clé) -> ancienne cellule (formules d'autres feuilles)
        for other in book.sheets:
            if other is sheet:
                continue
            for key, cell in list(other.cells.items()):
                if cell.formula:
                    new = _shift_text(cell.formula, other.name, name, axis, at, count, delete)
                    if new != cell.formula:
                        others[(other.uid, key)] = cell
                        other.cells[key] = cell.with_(formula=new)
        self._saved = (dict(sheet.cells), sheet.state(), others, dict(book.names))
        limit = (R.MAX_ROWS if axis == "row" else R.MAX_COLS)
        new_cells = {}
        for (row, col), cell in sheet.cells.items():
            index = row if axis == "row" else col
            if delete and at <= index < at + count:
                continue
            if index >= at:
                index = index - count if delete else index + count
            if index >= limit:
                continue
            if cell.formula:
                text = _shift_text(cell.formula, name, name, axis, at, count, delete)
                if text != cell.formula:
                    cell = cell.with_(formula=text)
            new_cells[(index, col) if axis == "row" else (row, index)] = cell
        old_keys = set(sheet.cells)
        sheet.cells = new_cells
        sheet.invalidate_bounds()
        line_axis = sheet.rows if axis == "row" else sheet.cols
        if delete:
            line_axis.delete(at, count)
        else:
            line_axis.insert(at, count)
        sheet.merges = [m for m in (_shift_rect(m, axis, at, count, delete) for m in sheet.merges) if m]

        def move_key(key):
            index = key[0] if axis == "row" else key[1]
            if delete and at <= index < at + count:
                return None
            if index >= at:
                index = index - count if delete else index + count
            return (index, key[1]) if axis == "row" else (key[0], index)
        sheet.comments = {move_key(k): v for k, v in sheet.comments.items() if move_key(k) is not None}
        for item in sheet.cond_formats + sheet.validations:
            item["ranges"] = [r for r in (_shift_rect(tuple(r), axis, at, count, delete)
                                          for r in item.get("ranges", [])) if r]
            if item.get("formula"):
                item["formula"] = _shift_text(item["formula"], name, name, axis, at, count, delete)
        for chart in sheet.charts:
            for key in ("data", "categories"):
                if chart.get(key):
                    chart[key] = _shift_text(chart[key], name, name, axis, at, count, delete)
        for table in sheet.tables:
            table["ref"] = _shift_rect(table["ref"], axis, at, count, delete)
        sheet.tables = [t for t in sheet.tables if t["ref"] is not None]
        if sheet.autofilter:
            sheet.autofilter = _shift_rect(sheet.autofilter, axis, at, count, delete)
        for nm, text in list(book.names.items()):
            book.names[nm] = _shift_text(text, name, name, axis, at, count, delete)
        if book.engine is not None:
            if book.names != self._saved[3]:
                book.engine.rebuild()
            elif len(old_keys) + len(new_cells) > REBUILD_ABOVE:
                book.engine.rebuild()                    # moins cher que d'écrire deux fois chaque cellule
            else:
                _engine_push(book, sheet, old_keys | set(new_cells))
                for (uid, key) in others:
                    _engine_push(book, book.sheet_by_uid(uid), [key])
            if any(x.tables for x in book.sheets):
                book.engine.tables_changed()

    def undo(self, book):
        sheet = self.sheet(book)
        cells, state, others, names = self._saved
        current = set(sheet.cells)
        sheet.cells = dict(cells)
        sheet.invalidate_bounds()
        sheet.restore(state)
        for (uid, key), cell in others.items():
            book.sheet_by_uid(uid).cells[key] = cell
        changed_names = book.names != names
        book.names = dict(names)
        if book.engine is not None:
            if changed_names or len(current) + len(cells) > REBUILD_ABOVE:
                book.engine.rebuild()
            else:
                _engine_push(book, sheet, current | set(cells))
                for (uid, key) in others:
                    _engine_push(book, book.sheet_by_uid(uid), [key])
            if any(x.tables for x in book.sheets):
                book.engine.tables_changed()


class TablesState(SheetState):
    """Tableaux d'une feuille modifiés (créer, redimensionner, renommer, style, totaux) : formules à références
    structurées retraduites pour le moteur dans les deux sens."""

    def __init__(self, sheet: Sheet, mutate, text: str = "Tableau", retranslate: str = "all"):
        super().__init__(sheet, mutate, text, kind="structure")
        self.retranslate = retranslate                 # « all », « size » (taille seule) ou « none » (style)

    def _engine(self, book):
        if book.engine is not None and self.retranslate != "none":
            book.engine.tables_changed(size_only=self.retranslate == "size")

    def redo(self, book):
        super().redo(book)
        self._engine(book)

    def undo(self, book):
        super().undo(book)
        self._engine(book)


class SheetsCommand(Command):
    """Opérations sur les feuilles : ajouter, supprimer, renommer, déplacer, dupliquer. État gardé : la liste des
    feuilles et les formules réécrites ailleurs."""
    kind = "sheets"

    def __init__(self, op: str, text: str, **args):
        self.op = op
        self.text = text
        self.args = args
        self._before = None
        self._after = None

    def _snapshot(self, book):
        return (list(book.sheets), [(s, s.name) for s in book.sheets], dict(book.names))

    def _rewrite_all(self, book, fn):
        changed = {}
        for sheet in book.sheets:
            for key, cell in list(sheet.cells.items()):
                if cell.formula:
                    new = fn(cell.formula)
                    if new != cell.formula:
                        changed[(sheet.uid, key)] = (cell, cell.with_(formula=new))
                        sheet.cells[key] = changed[(sheet.uid, key)][1]
            for chart in sheet.charts:
                for k in ("data", "categories"):
                    if chart.get(k):
                        chart[k] = fn(chart[k])
        for nm, text in list(book.names.items()):
            book.names[nm] = fn(text)
        return changed

    def redo(self, book):
        if self._after is not None:
            sheets, names_of, names, formulas = self._after
            book.sheets = list(sheets)
            for s, n in names_of:
                s.name = n
            book.names = dict(names)
            for (uid, key), (_old, new) in formulas.items():
                book.sheet_by_uid(uid).cells[key] = new
            if book.engine is not None:
                book.engine.rebuild()
            return
        before = self._snapshot(book)
        formulas = {}
        op, a = self.op, self.args
        engine_rebuild = True
        if op == "add":
            sheet = a.get("sheet") or Sheet(a.get("name") or book.unique_name())
            a["sheet"] = sheet
            book.sheets.insert(min(a.get("index", len(book.sheets)), len(book.sheets)), sheet)
            engine_rebuild = False
        elif op == "remove":
            sheet = book.sheet_by_uid(a["uid"])
            book.sheets.remove(sheet)
            formulas = self._rewrite_all(book, lambda f: R.remove_sheet(f, sheet.name))
        elif op == "rename":
            sheet = book.sheet_by_uid(a["uid"])
            old = sheet.name
            sheet.name = a["name"]
            formulas = self._rewrite_all(book, lambda f: R.rename_sheet(f, old, a["name"]))
        elif op == "move":
            sheet = book.sheet_by_uid(a["uid"])
            book.sheets.remove(sheet)
            book.sheets.insert(max(0, min(a["index"], len(book.sheets))), sheet)
            engine_rebuild = False
        self._before = before
        self._after = (list(book.sheets), [(s, s.name) for s in book.sheets], dict(book.names), formulas)
        if book.engine is not None:
            if engine_rebuild:
                book.engine.rebuild()
            elif op == "add":
                book.engine.add_sheet(a["sheet"])

    def undo(self, book):
        sheets, names_of, names = self._before
        book.sheets = list(sheets)
        for s, n in names_of:
            s.name = n
        book.names = dict(names)
        for (uid, key), (old, _new) in self._after[3].items():
            sheet = book.sheet_by_uid(uid)
            if sheet is not None:
                sheet.cells[key] = old
        if book.engine is not None:
            book.engine.rebuild()


class Names(Command):
    """Noms définis remplacés (dictionnaire complet)."""
    kind = "cells"

    def __init__(self, names: dict, text: str = "Noms définis"):
        self.after = dict(names)
        self.before = None
        self.text = text

    def redo(self, book):
        self.before = dict(book.names)
        book.names = dict(self.after)
        if book.engine is not None:
            book.engine.names_changed()

    def undo(self, book):
        book.names = dict(self.before)
        if book.engine is not None:
            book.engine.names_changed()


class Macro(Command):
    def __init__(self, text: str):
        self.text = text
        self.children: list[Command] = []
        self.kind = "cells"

    def redo(self, book):
        for child in self.children:
            child.redo(book)

    def undo(self, book):
        for child in reversed(self.children):
            child.undo(book)

    def sheet(self, book):
        for child in self.children:
            s = child.sheet(book)
            if s is not None:
                return s
        return None


_KIND_ORDER = {"view": 0, "cells": 1, "structure": 2, "sheets": 3}


class UndoStack:
    """Pile d'annulation du document. `listeners` : appelées sans argument quand la pile change (boutons)."""

    def __init__(self, book: Workbook, limit: int = UNDO_LIMIT):
        self.book = book
        self.limit = limit
        self._done: list[Command] = []
        self._undone: list[Command] = []
        self._macro: list[Macro] = []
        self._clean = 0                      # nombre de commandes faites au dernier « propre » (enregistrement)
        self._clean_valid = True
        self.listeners: list = []

    # -- état --
    def can_undo(self) -> bool:
        return bool(self._done) and not self._macro

    def can_redo(self) -> bool:
        return bool(self._undone) and not self._macro

    def undo_text(self) -> str:
        return self._done[-1].text if self._done else ""

    def redo_text(self) -> str:
        return self._undone[-1].text if self._undone else ""

    def is_clean(self) -> bool:
        return self._clean_valid and self._clean == len(self._done)

    def set_clean(self):
        self._clean = len(self._done)
        self._clean_valid = True

    def __len__(self):
        return len(self._done)

    # -- regroupement --
    def begin(self, text: str):
        self._macro.append(Macro(text))

    def end(self):
        macro = self._macro.pop()
        if not macro.children:
            return
        macro.kind = max((c.kind for c in macro.children), key=lambda k: _KIND_ORDER.get(k, 1))
        if self._macro:
            self._macro[-1].children.append(macro)
            return
        self._record(macro)
        self._after(macro)

    # -- commandes --
    def push(self, command: Command):
        command.redo(self.book)
        if self._macro:
            self._macro[-1].children.append(command)
            return
        self._record(command)
        self._after(command)

    def _record(self, command: Command):
        self._done.append(command)
        self._undone.clear()
        if len(self._done) > self.limit:
            drop = len(self._done) - self.limit
            del self._done[:drop]
            self._clean -= drop
            if self._clean < 0:
                self._clean_valid = False

    def undo(self) -> Command | None:
        if not self.can_undo():
            return None
        command = self._done.pop()
        command.undo(self.book)
        self._undone.append(command)
        self._after(command)
        return command

    def redo(self) -> Command | None:
        if not self.can_redo():
            return None
        command = self._undone.pop()
        command.redo(self.book)
        self._done.append(command)
        self._after(command)
        return command

    def _after(self, command: Command):
        book = self.book
        if book.engine is not None and book.calc_mode == "auto":
            book.engine.recalc()
        book.notify(command.kind, command.sheet(book))
        for listener in list(self.listeners):
            listener()
