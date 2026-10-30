"""Filtres automatiques (SANS Qt) : celui de la feuille (`Sheet.autofilter` + `Sheet.filters`) et celui de CHAQUE
tableau structuré (`table["filter"]`, critères dans `table["filters"]`), comme Excel. Une même mécanique :

- une PORTÉE (`Scope`) = ligne d'entête, lignes de données, colonnes, critères ;
- un critère par colonne = textes AFFICHÉS gardés ; les lignes de données qui ne passent pas tous les critères
  sont masquées (`Sheet.rows.hidden`), une étape d'annulation ; pas de nouveau filtrage automatique quand les
  données changent (Excel : « Réappliquer ») ;
- critères d'un tableau rangés par POSITION dans le tableau (« 0 », « 1 »…) : ils suivent le tableau quand il bouge.
Valeurs proposées dans l'ordre d'Excel (nombres, textes, logiques, erreurs, vides)."""
from __future__ import annotations

from . import commands as C


class Scope:
    __slots__ = ("kind", "table", "header", "first", "last", "c0", "c1")

    def __init__(self, kind, header, first, last, c0, c1, table=None):
        self.kind = kind                      # « sheet » ou « table »
        self.table = table
        self.header = header
        self.first, self.last = first, last   # lignes de données
        self.c0, self.c1 = c0, c1

    @property
    def rect(self):
        return self.header, self.c0, self.last, self.c1

    def criteria(self, sheet) -> dict[int, dict]:
        """{colonne absolue: {"values": [...]}}."""
        if self.kind == "sheet":
            return dict(sheet.filters)
        out = {}
        for key, rule in (self.table.get("filters") or {}).items():
            try:
                out[self.c0 + int(key)] = rule
            except (TypeError, ValueError):
                continue
        return out


def scopes(sheet):
    """Portées filtrables de la feuille : filtre de la feuille, puis tableaux à entête dont le filtre est actif."""
    out = []
    if sheet.autofilter is not None:
        r0, c0, r1, c1 = sheet.autofilter
        out.append(Scope("sheet", r0, r0 + 1, r1, c0, c1))
    for table in sheet.tables:
        if table.get("header", True) and table.get("filter", True):
            r0, c0, r1, c1 = table["ref"]
            out.append(Scope("table", r0, r0 + 1, r1 - (1 if table.get("totals") else 0), c0, c1, table))
    return out


def scope_at(sheet, row, col):
    """Portée dont la ligne d'entête contient (row, col), ou None."""
    for scope in scopes(sheet):
        if scope.header == row and scope.c0 <= col <= scope.c1:
            return scope
    return None


def values(book, sheet, scope, col) -> list[str]:
    from .ops import _sort_key, display_text
    seen = {}
    for r in range(scope.first, scope.last + 1):
        text, _color, value = display_text(book, sheet, r, col)
        seen.setdefault(text, value)
    return [t for t, _v in sorted(seen.items(), key=lambda tv: _sort_key(tv[1], True))]


def _refilter(book, sheet, scope, criteria):
    from .ops import display_text
    rules = {c: set(rule.get("values", [])) for c, rule in criteria.items()}
    for r in range(scope.first, scope.last + 1):
        keep = all(display_text(book, sheet, r, c)[0] in allowed for c, allowed in rules.items())
        if keep:
            sheet.rows.hidden.discard(r)
        else:
            sheet.rows.hidden.add(r)
    sheet.rows.changed()


def apply(book, stack, sheet, scope, col, allowed: set[str] | None):
    """Critère de la colonne `col` (textes affichés gardés ; None = tout) ; lignes masquées en conséquence."""
    name = scope.table["name"] if scope.table is not None else None

    def mutate(s):
        target = scope
        if name is not None:                               # le tableau de l'état courant (annuler / rétablir)
            table = next((t for t in s.tables if t["name"] == name), None)
            if table is None:
                return
            target = next((x for x in scopes(s) if x.table is table), scope)
            rules = table.setdefault("filters", {})
            key = str(col - target.c0)
        else:
            rules = s.filters
            key = col
        if allowed is None:
            rules.pop(key, None)
        else:
            rules[key] = {"values": sorted(allowed)}
        _refilter(book, s, target, target.criteria(s))
    if scope.kind == "table":
        stack.push(C.TablesState(sheet, mutate, "Filtrer", retranslate="none"))
    else:
        stack.push(C.SheetState(sheet, mutate, "Filtrer", kind="structure"))


def clear(book, stack, sheet, scope):
    """Tous les critères de la portée retirés, toutes ses lignes réaffichées."""
    def mutate(s):
        if scope.table is not None:
            for t in s.tables:
                if t["name"] == scope.table["name"]:
                    t["filters"] = {}
        else:
            s.filters = {}
        for r in range(scope.first, scope.last + 1):
            s.rows.hidden.discard(r)
        s.rows.changed()
    if scope.kind == "table":
        stack.push(C.TablesState(sheet, mutate, "Effacer les filtres", retranslate="none"))
    else:
        stack.push(C.SheetState(sheet, mutate, "Effacer les filtres", kind="structure"))


def set_table_buttons(book, stack, sheet, table, on: bool):
    """Boutons de filtre d'un tableau affichés / retirés (retirés : critères effacés, lignes réaffichées)."""
    name = table["name"]

    def mutate(s):
        for t in s.tables:
            if t["name"] == name:
                if not on:
                    r0, _c0, r1, _c1 = t["ref"]
                    for r in range(r0 + 1, r1 + 1):
                        s.rows.hidden.discard(r)
                    s.rows.changed()
                    t["filters"] = {}
                t["filter"] = on
    stack.push(C.TablesState(sheet, mutate, "Boutons de filtre", retranslate="none"))
