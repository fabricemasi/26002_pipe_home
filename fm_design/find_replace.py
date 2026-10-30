"""Rechercher et remplacer (Ctrl+F, comme Canva) : panneau latéral « Rechercher et remplacer » sur les textes et les
cellules des tableaux de TOUTES les pages. « Suivant » choisit l'élément suivant qui contient le texte (sa page est
affichée si elle change) ; « Remplacer » remplace dans l'élément choisi puis passe au suivant ; « Tout remplacer » =
une seule étape d'annulation. Les parties stylées d'un texte suivent le remplacement (`design_model.replace_text`).
Un élément verrouillé est trouvé mais jamais modifié."""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QHBoxLayout, QLineEdit

from . import design_model as dm, document as doc
from .datavis import DesignTableItem
from .items import DesignTextItem

STATE = {"needle": "", "replacement": "", "case": False}     # gardé d'une ouverture du panneau à l'autre


def count_in(item, needle: str, case: bool) -> int:
    if isinstance(item, DesignTextItem):
        return len(dm.find_spans(str(item.data.get("text", "")), needle, case))
    if isinstance(item, DesignTableItem):
        return sum(len(dm.find_spans(cell, needle, case)) for row in dm.table_grid(item.data) for cell in row)
    return 0


def matches(ctl, needle: str, case: bool) -> list:
    """Éléments qui contiennent `needle`, dans l'ordre des pages puis de l'empilement."""
    if not needle:
        return []
    return [element for page in ctl.pages() for element in page.elements() if count_in(element, needle, case)]


def _replace_in(item, needle: str, replacement: str, case: bool):
    data = item.data
    if isinstance(item, DesignTextItem):
        text, spans, _n = dm.replace_text(str(data.get("text", "")), data.get("spans") or [], needle, replacement,
                                          case)
        data["text"], data["spans"] = text, spans
    elif isinstance(item, DesignTableItem):
        data["cells"] = [[dm.replace_text(cell, [], needle, replacement, case)[0] for cell in row]
                         for row in dm.table_grid(data)]


def replace(ctl, items, needle: str, replacement: str, case: bool) -> int:
    """Remplace dans `items` (non verrouillés), une étape ; -> nombre d'occurrences remplacées."""
    items = [i for i in items if not i.locked() and count_in(i, needle, case)]
    total = sum(count_in(i, needle, case) for i in items)
    if items:
        doc.change(ctl.scene, items, lambda i: _replace_in(i, needle, replacement, case), "Remplacer le texte")
    return total


def show_next(ctl, needle: str, case: bool):
    """Choisit l'élément suivant (après la sélection) qui contient `needle` ; None s'il n'y en a aucun."""
    found = matches(ctl, needle, case)
    if not found:
        return None
    sel = ctl.selection()
    after = found.index(sel[0]) + 1 if len(sel) == 1 and sel[0] in found else 0
    item = found[after % len(found)]
    page = item.page_item()
    if page is not None and page is not ctl.current_page():
        ctl.set_current_page(page, show=True)
    ctl._select([item])
    return item


def build_find(ctl, parent):
    """Panneau « Rechercher et remplacer » (briques des réglages : libellés, boutons, interrupteur)."""
    from settings_widgets import _Toggle
    from .panels import _column, _label, _wide_button
    widget, layout = _column(parent)
    layout.addWidget(_label("Rechercher", "value_muted"))
    find = QLineEdit(widget)
    find.setPlaceholderText("Texte à trouver")
    find.setText(STATE["needle"])
    layout.addWidget(find)
    layout.addWidget(_label("Remplacer par", "value_muted"))
    repl = QLineEdit(widget)
    repl.setText(STATE["replacement"])
    layout.addWidget(repl)
    row = QHBoxLayout()
    case = _Toggle(STATE["case"], style_override="toggle1", show_label=False)
    row.addWidget(case)
    row.addWidget(_label("Respecter la casse", "value_muted"), 1)
    layout.addLayout(row)
    status = _label("", "value_muted")
    layout.addWidget(status)

    def current():
        STATE.update(needle=find.text(), replacement=repl.text(), case=case.isChecked())
        return STATE["needle"], STATE["replacement"], STATE["case"]

    def update_status(prefix=""):
        needle, _r, sensitive = current()
        if not needle:
            status.setText(prefix)
            return
        found = matches(ctl, needle, sensitive)
        total = sum(count_in(i, needle, sensitive) for i in found)
        text = f"{total} résultat{'s' if total > 1 else ''} dans {len(found)} élément{'s' if len(found) > 1 else ''}"
        status.setText(f"{prefix}{text}")

    def next_one():
        needle, _r, sensitive = current()
        if needle and show_next(ctl, needle, sensitive) is None:
            update_status("Introuvable. ")
        else:
            update_status()

    def replace_one():
        needle, replacement, sensitive = current()
        sel = [i for i in ctl.selection() if count_in(i, needle, sensitive)]
        if not needle:
            return
        if not sel:                                    # rien de choisi : d'abord trouver
            next_one()
            return
        locked = [i for i in sel if i.locked()]
        n = replace(ctl, sel, needle, replacement, sensitive)
        if n:
            show_next(ctl, needle, sensitive)
        update_status(f"{n} remplacé{'s' if n > 1 else ''}. " if n else ("Élément verrouillé. " if locked else ""))

    def replace_all():
        needle, replacement, sensitive = current()
        if not needle:
            return
        found = matches(ctl, needle, sensitive)
        n = replace(ctl, found, needle, replacement, sensitive)
        skipped = sum(1 for i in found if i.locked())
        note = f" ({skipped} verrouillé{'s' if skipped > 1 else ''} laissé{'s' if skipped > 1 else ''})" if skipped else ""
        update_status(f"{n} remplacé{'s' if n > 1 else ''}{note}. ")

    find.textChanged.connect(lambda _t: update_status())
    case.toggled.connect(lambda _on: update_status())
    find.returnPressed.connect(next_one)
    repl.returnPressed.connect(replace_one)
    layout.addWidget(_wide_button("Suivant (Entrée)", "Choisir l'élément suivant qui contient le texte", next_one,
                                  widget))
    layout.addWidget(_wide_button("Remplacer", "Dans l'élément choisi, puis le suivant", replace_one, widget))
    layout.addWidget(_wide_button("Tout remplacer", "Dans toutes les pages (une seule étape d'annulation)",
                                  replace_all, widget))
    layout.addStretch(1)
    update_status()
    widget.find_field = find
    widget.replace_field = repl
    widget.case_toggle = case
    widget.status = status
    widget.next_one, widget.replace_one, widget.replace_all = next_one, replace_one, replace_all
    find.setFocus(Qt.ShortcutFocusReason)
    find.selectAll()
    return widget
