"""Menu « Animer » d'une page (barre contextuelle, page sans sélection) : transition de la page et animation de
ses éléments en présentation (`present.py`), pour cette page ou toutes ; aperçu = présenter depuis cette page."""
from __future__ import annotations

from fm_board.ui import _menu
from . import design_model as dm, document as doc
from .menus import _popup


def animate_menu(ctl, anchor, page):
    menu = _menu(ctl.pane, "design_animate")
    for title, key, choices in (("Transition de la page", "transition", dm.TRANSITIONS),
                                ("Animation des éléments", "animation", dm.ANIMATIONS)):
        sub = menu.addMenu(title)
        for value, text in choices:
            action = sub.addAction(text)
            action.setCheckable(True)
            action.setChecked(page.data.get(key, "none") == value)
            action.triggered.connect(lambda _c=False, k=key, v=value: doc.change(
                ctl.scene, [page], lambda i: i.data.update({k: v}), "Animer la page"))
    menu.addSeparator()
    menu.addAction("Appliquer à toutes les pages").triggered.connect(lambda: doc.change(
        ctl.scene, doc.pages(ctl.scene), lambda i: i.data.update(transition=page.data.get("transition", "none"),
                                                                 animation=page.data.get("animation", "none")),
        "Animer toutes les pages"))
    menu.addAction("Aperçu (présenter depuis cette page)").triggered.connect(lambda: ctl.present(page))
    _popup(ctl, menu, anchor)
