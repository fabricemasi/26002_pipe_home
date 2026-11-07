"""Éditeur fm_theme : liste des titres FIXE + volet des paramètres à droite (demande de l'utilisateur, 2026-11-02).

Ouvrir un titre (TITRES, TOGGLES…) ne pousse plus les autres titres vers le bas : le corps de la section ouverte
sort de la liste et se déroule dans un volet à droite des titres, juste sous le titre ouvert, qui reste en place.
Seul le corps (`_Section._body`) change de parent : les titres, leur accordéon, leurs signaux et leurs styles
restent ceux de la fenêtre de réglages. `_logical_parent` garde le corps rattaché à sa section pour les
parcours de parenté (boîtes des titres, clé d'ordre des titres : `fm_theme.layout.logical_parent`).
"""
from PySide6.QtCore import QEvent, QObject, QPoint, QTimer
from PySide6.QtWidgets import QFrame, QScrollArea, QVBoxLayout, QWidget

import settings_window_v2 as v2
from settings_store import M

PANE_MARGINS = (8, 4, 18, 26)        # gauche, haut, droite, bas : le corps garde son propre retrait
LIST_GAP = 36                        # espace entre le titre le plus long de la liste et le volet
MIN_LIST_WIDTH = 250


def page_scroller(node) -> QScrollArea | None:
    """L'ascenseur de la page qui porte la liste des titres de 1er niveau."""
    widget = node.parentWidget()
    while widget is not None and not isinstance(widget, QScrollArea):
        widget = widget.parentWidget()
    return widget


class SideDetail(QObject):
    """Volet des paramètres de la page `scroller` : `nodes` = ses titres de 1er niveau (`_LazyNode`)."""

    def __init__(self, scroller: QScrollArea, nodes: list):
        page = scroller.parentWidget()
        super().__init__(page)
        self._page, self._scroller, self._nodes = page, scroller, nodes
        pane = self.pane = QFrame(self._page)
        pane.setObjectName("ThemeSideDetail")
        pane.setStyleSheet(f"#ThemeSideDetail {{ background: {M['panel_bg']}; border-left: 1px solid "
                           f"{M['panel_border']}; }}")
        outer = QVBoxLayout(pane)
        outer.setContentsMargins(0, 0, 0, 0)
        self._scroll = v2._WideScrollArea(pane)            # un tableau plus large que le volet : défilement
        self._scroll.setWidgetResizable(True)
        self._scroll.setFrameShape(QFrame.NoFrame)
        self._scroll.setStyleSheet(f"background: {M['panel_bg']};")
        outer.addWidget(self._scroll)
        holder = QWidget(self._scroll.viewport())
        self._holder = QVBoxLayout(holder)
        self._holder.setContentsMargins(*PANE_MARGINS)
        self._holder.setSpacing(0)
        self._holder.addStretch(1)
        self._scroll.setWidget(holder)
        for node in nodes:
            self._adopt(node)
        pane.hide()
        self._page.installEventFilter(self)
        scroller.widget().installEventFilter(self)
        scroller.verticalScrollBar().valueChanged.connect(self.reposition)
        self._open_changed(False)

    def _adopt(self, node):
        """Le corps de la section passe dans le volet (masqué tant que la section est repliée)."""
        section = node._head
        body = section._body
        section._layout.removeWidget(body)
        body._logical_parent = section
        self._holder.insertWidget(self._holder.count() - 1, body)
        section.collapsedChanged.connect(self._open_changed)

    def _open_changed(self, collapsed: bool):
        if not collapsed:
            self._scroll.verticalScrollBar().setValue(0)         # une autre section : le volet repart du haut
            self._scroll.horizontalScrollBar().setValue(0)
        self.reposition()
        QTimer.singleShot(0, self.reposition)                    # une fois la liste remise en page

    def eventFilter(self, obj, event):
        if event.type() in (QEvent.Resize, QEvent.LayoutRequest):
            self.reposition()
        return False

    def _left(self) -> int:
        """Bord gauche du volet : à droite du titre le plus long (les titres ne bougent jamais)."""
        right = 0
        for node in self._nodes:
            label = node._head._name_label
            right = max(right, label.mapTo(self._page, QPoint(label.sizeHint().width(), 0)).x())
        return min(max(right + LIST_GAP, MIN_LIST_WIDTH), self._page.width() // 2)

    def reposition(self, *_args):
        """Volet sous le titre ouvert (le plus haut s'il y en a plusieurs, Ctrl), jusqu'en bas de la page."""
        try:
            opened = [n for n in self._nodes if not n.is_collapsed()]
            if not opened:
                self.pane.hide()
                return
            section = opened[0]._head
            top = section.mapTo(self._page, QPoint(0, section.height())).y()
            left = self._left()
            self.pane.setGeometry(left, top, max(0, self._page.width() - left), max(0, self._page.height() - top))
            if self.pane.isHidden():
                self.pane.show()
            self.pane.raise_()
        except RuntimeError:             # fenêtre détruite entre-temps (minuterie en attente après un changement de preset)
            pass
