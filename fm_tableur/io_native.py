"""Format NATIF du classeur (SANS Qt) : dictionnaire JSON, rangé dans l'élément « sheet » du `.mro` (Board).

Choix : le format de travail interne n'est PAS le .xlsx — un JSON compact, sans perte pour tout ce que le module
sait faire (valeurs typées, formules, styles, tailles, fusions, volets, commentaires, mises en forme
conditionnelles, validations, graphiques, filtres), lu et écrit en quelques dizaines de ms pour 100 000 cellules,
et qui GARDE les clés inconnues (version plus récente du module) : rien n'est perdu à la réécriture.

Cellule = liste courte [ligne, colonne, valeur, formule, style] (éléments finaux nuls omis) ; erreur = {"e": code}."""
from __future__ import annotations

from . import values as V
from .document import Axis, Cell, Sheet, StyleTable, Workbook

FORMAT = "fm_tableur"
VERSION = 1
_BOOK_KEYS = {"format", "version", "styles", "names", "calc_mode", "date_1904", "default_font", "sheets", "extra",
              "active", "source"}
_SHEET_KEYS = {"name", "cells", "rows", "cols", "merges", "freeze", "show_grid", "zoom", "tab_color", "hidden",
               "comments", "cond_formats", "validations", "charts", "tables", "autofilter", "filters", "protected", "extra"}


def _encode_value(value):
    if isinstance(value, V.XLError):
        return {"e": value.code}
    if isinstance(value, float) and value.is_integer() and abs(value) < 2 ** 53:
        return value                                    # float gardé (le type compte : 1.0 reste un nombre)
    return value


def _decode_value(raw):
    if isinstance(raw, dict) and "e" in raw:
        return V.XLError(str(raw["e"]))
    if isinstance(raw, (int, float, str, bool)) or raw is None:
        return raw
    return str(raw)


def _axis_to(axis: Axis) -> dict:
    out = {"default": axis.default}
    if axis.sizes:
        out["sizes"] = {str(k): round(v, 2) for k, v in axis.sizes.items()}
    if axis.hidden:
        out["hidden"] = sorted(axis.hidden)
    if axis.styles:
        out["styles"] = {str(k): v for k, v in axis.styles.items()}
    return out


def _axis_from(axis: Axis, raw):
    if not isinstance(raw, dict):
        return
    try:
        axis.default = float(raw.get("default", axis.default))
    except (TypeError, ValueError):
        pass
    for k, v in (raw.get("sizes") or {}).items():
        try:
            axis.sizes[int(k)] = float(v)
        except (TypeError, ValueError):
            continue
    axis.hidden = {int(i) for i in raw.get("hidden") or [] if isinstance(i, int)}
    for k, v in (raw.get("styles") or {}).items():
        try:
            axis.styles[int(k)] = int(v)
        except (TypeError, ValueError):
            continue
    axis.changed()


def sheet_to_dict(sheet: Sheet, engine=None) -> dict:
    """`engine` donné : la valeur CALCULÉE de chaque formule est rangée avec elle (affichage sans moteur, cache)."""
    cells = []
    live = engine is not None and engine.available
    for (r, c), cell in sheet.cells.items():
        value = engine.value(sheet, r, c) if live and cell.formula else cell.value
        item = [r, c, _encode_value(value), cell.formula, cell.style]
        while len(item) > 3 and not item[-1]:
            item.pop()
        if len(item) == 3 and item[2] is None:
            item.pop()
        cells.append(item)
    out = {"name": sheet.name, "cells": cells, "rows": _axis_to(sheet.rows), "cols": _axis_to(sheet.cols)}
    if sheet.merges:
        out["merges"] = [list(m) for m in sheet.merges]
    if sheet.freeze != (0, 0):
        out["freeze"] = list(sheet.freeze)
    if not sheet.show_grid:
        out["show_grid"] = False
    if sheet.zoom != 1.0:
        out["zoom"] = sheet.zoom
    for key in ("tab_color", "hidden", "protected"):
        if getattr(sheet, key):
            out[key] = getattr(sheet, key)
    if sheet.comments:
        out["comments"] = [[r, c, t] for (r, c), t in sheet.comments.items()]
    for key in ("cond_formats", "validations", "charts", "tables"):
        if getattr(sheet, key):
            out[key] = _jsonable(getattr(sheet, key))
    if sheet.autofilter:
        out["autofilter"] = list(sheet.autofilter)
    if sheet.filters:
        out["filters"] = {str(k): v for k, v in sheet.filters.items()}
    out.update(sheet.extra)
    return out


def _jsonable(obj):
    if isinstance(obj, dict):
        return {str(k): _jsonable(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_jsonable(v) for v in obj]
    return obj


def sheet_from_dict(raw: dict) -> Sheet:
    sheet = Sheet(str(raw.get("name") or "Feuil1"))
    cells = sheet.cells
    for item in raw.get("cells") or []:
        if not isinstance(item, list) or len(item) < 2:
            continue
        try:
            r, c = int(item[0]), int(item[1])
        except (TypeError, ValueError):
            continue
        value = _decode_value(item[2]) if len(item) > 2 else None
        formula = item[3] if len(item) > 3 and isinstance(item[3], str) else None
        style = int(item[4]) if len(item) > 4 and isinstance(item[4], int) else 0
        cells[(r, c)] = Cell(value, formula, style)
    _axis_from(sheet.rows, raw.get("rows"))
    _axis_from(sheet.cols, raw.get("cols"))
    sheet.merges = [tuple(int(x) for x in m) for m in raw.get("merges") or [] if isinstance(m, list) and len(m) == 4]
    freeze = raw.get("freeze") or [0, 0]
    sheet.freeze = (int(freeze[0]), int(freeze[1])) if isinstance(freeze, list) and len(freeze) == 2 else (0, 0)
    sheet.show_grid = bool(raw.get("show_grid", True))
    try:
        sheet.zoom = float(raw.get("zoom", 1.0))
    except (TypeError, ValueError):
        sheet.zoom = 1.0
    sheet.tab_color = raw.get("tab_color") if isinstance(raw.get("tab_color"), str) else None
    sheet.hidden = bool(raw.get("hidden", False))
    sheet.protected = bool(raw.get("protected", False))
    sheet.comments = {(int(r), int(c)): str(t) for r, c, t in (x for x in raw.get("comments") or []
                                                               if isinstance(x, list) and len(x) == 3)}
    for key in ("cond_formats", "validations", "charts", "tables"):
        items = raw.get(key)
        setattr(sheet, key, [dict(i) for i in items if isinstance(i, dict)] if isinstance(items, list) else [])
    for item in sheet.cond_formats + sheet.validations:
        item["ranges"] = [tuple(r) for r in item.get("ranges", []) if isinstance(r, (list, tuple)) and len(r) == 4]
    sheet.tables = [t for t in sheet.tables if isinstance(t.get("name"), str)
                    and isinstance(t.get("ref"), (list, tuple)) and len(t["ref"]) == 4]
    for table in sheet.tables:
        table["ref"] = tuple(int(x) for x in table["ref"])
    af = raw.get("autofilter")
    sheet.autofilter = tuple(int(x) for x in af) if isinstance(af, list) and len(af) == 4 else None
    sheet.filters = {int(k): v for k, v in (raw.get("filters") or {}).items() if str(k).isdigit()}
    sheet.extra = {k: v for k, v in raw.items() if k not in _SHEET_KEYS}
    return sheet


def to_dict(book: Workbook, active: int = 0) -> dict:
    out = {"format": FORMAT, "version": VERSION, "styles": book.styles.to_list(), "names": dict(book.names),
           "calc_mode": book.calc_mode, "sheets": [sheet_to_dict(s, book.engine) for s in book.sheets],
           "active": active}
    if book.date_1904:
        out["date_1904"] = True
    if tuple(book.default_font) != ("Calibri", 11.0):
        out["default_font"] = list(book.default_font)
    if book.source:
        out["source"] = dict(book.source)
    out.update(book.extra)
    return out


def from_dict(raw) -> tuple[Workbook, int]:
    """Classeur (et feuille active) d'un dictionnaire natif ; un classeur vide d'une feuille si `raw` est vide."""
    book = Workbook()
    if not isinstance(raw, dict) or not raw.get("sheets"):
        book.add_sheet()
        return book, 0
    book.styles = StyleTable.from_list(raw.get("styles"))
    book.names = {str(k): str(v) for k, v in (raw.get("names") or {}).items()}
    book.calc_mode = "manual" if raw.get("calc_mode") == "manual" else "auto"
    book.date_1904 = bool(raw.get("date_1904", False))
    font = raw.get("default_font")
    if isinstance(font, list) and len(font) == 2:
        book.default_font = (str(font[0]), float(font[1]))
    if isinstance(raw.get("source"), dict):
        book.source = dict(raw["source"])
    for item in raw.get("sheets") or []:
        if isinstance(item, dict):
            book.sheets.append(sheet_from_dict(item))
    if not book.sheets:
        book.add_sheet()
    book.extra = {k: v for k, v in raw.items() if k not in _BOOK_KEYS}
    active = raw.get("active", 0)
    active = active if isinstance(active, int) and 0 <= active < len(book.sheets) else 0
    return book, active
