"""Menu « Animer » d'une page (barre contextuelle, page sans sélection) : transition de la page et animation de
ses éléments en présentation (`present.py`), pour cette page ou toutes ; aperçu = présenter depuis cette page."""
from __future__ import annotations

from fm_board.ui import _menu
from . import design_model as dm, document as doc
from .menus import _popup


def edit_link(ctl, items):
    """Lien des éléments choisis (Ctrl+K, comme Canva) : adresse web ou chemin de fichier, ouvert d'un clic en
    présentation ; vide = retirer. Pastille « lien » sur l'élément, à l'écran seulement."""
    from PySide6.QtWidgets import QInputDialog
    text, ok = QInputDialog.getText(ctl.pane, "Lien", "Adresse (https://…) ou fichier ; vide = retirer :",
                                    text=items[0].data.get("link", ""))
    if ok:
        link = text.strip()
        doc.change(ctl.scene, items, lambda i: i.data.update(link=link), "Lien" if link else "Retirer le lien")


def element_animate_menu(ctl, anchor, items):
    """Animation propre aux éléments choisis : « Comme la page », « Aucune » (là dès l'arrivée) ou une autre."""
    menu = _menu(ctl.pane, "design_element_animate")
    current = items[0].data.get("animation", "")
    for value, text in (("", "Comme la page"),) + tuple(dm.ANIMATIONS):
        action = menu.addAction(text if value != "none" else "Aucune (là dès l'arrivée de la page)")
        action.setCheckable(True)
        action.setChecked(current == value)
        action.triggered.connect(lambda _c=False, v=value: doc.change(
            ctl.scene, items, lambda i: i.data.update(animation=v), "Animer l'élément"))
    page = items[0].page_item()
    if page is not None:
        menu.addSeparator()
        menu.addAction("Aperçu (présenter depuis cette page)").triggered.connect(lambda: ctl.present(page))
    _popup(ctl, menu, anchor)


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
