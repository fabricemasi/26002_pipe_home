"""Fenêtres de réglages : liste des titres FIXE + volet des paramètres à droite (demande de l'utilisateur,
2026-11-02 pour l'éditeur fm_theme ; TOUTES les fenêtres de réglages depuis le 2026-11-08 : posé par
`settings_window_v2.SettingsWindowV2._build_page` sur chaque page, `page._side_detail`).

Ouvrir un titre (TITRES, TOGGLES…) ne pousse plus les autres titres vers le bas : le corps de la section ouverte
sort de la liste et se déroule dans un volet à droite des titres, le titre ouvert reste en place.
Seul le corps (`_Section._body`) change de parent : les titres, leur accordéon, leurs signaux et leurs styles
restent ceux de la fenêtre de réglages. `_logical_parent` garde le corps rattaché à sa section pour les
parcours de parenté (boîtes des titres, clé d'ordre des titres : `fm_theme.layout.logical_parent`).

ZONE DÉPLOYÉE (demande de l'utilisateur sur capture annotée, 2026-11-08) : le volet est un panneau à droite de la
colonne des titres, du HAUT de la liste (premier titre) jusqu'en bas de la page, aligné sur le bord droit des titres,
coins arrondis comme les titres (« Border radius » du niveau 1) sauf en haut à gauche (droit, demandé). Les titres ne
sont pas peints sous le volet (`_side_clip` : un fond semi-transparent les laissait voir). Le titre ouvert s'y ouvre
comme un ONGLET : même
fond (TITRES > Paragraphes > Niveau 1 > « Déployé : couleur de fond », sinon son fond habituel, sinon celui de la
page), sa partie droite passe sous le volet, et le contour du volet (« Déployé : bordures », sinon les bordures du
titre) est interrompu à gauche sur la hauteur du titre : titre et volet ne font qu'une forme.
"""
from PySide6.QtCore import QEvent, QObject, QPoint, QRect, QTimer
from PySide6.QtGui import QPainter, QRegion
from PySide6.QtWidgets import QFrame, QScrollArea, QVBoxLayout, QWidget

import settings_window_v2 as v2
from settings_store import M

PANE_MARGINS = (8, 4, 18, 26)        # gauche, haut, droite, bas : le corps garde son propre retrait
LIST_GAP = 36                        # espace entre le titre le plus long de la liste et le volet
MIN_LIST_WIDTH = 250
BOTTOM_GAP = 8                       # sous le volet : ses coins du bas arrondis restent visibles


class _Pane(QFrame):
    """Volet peint : fond et bordures du titre déployé, coins = ceux des titres de 1er niveau ; bord gauche ouvert
    sur la hauteur du titre ouvert (l'onglet)."""

    def __init__(self, detail: "SideDetail", parent: QWidget):
        super().__init__(parent)
        self._detail = detail

    def refresh(self):
        """Habillage des titres changé (restyle_titles_in) : place, retrait du contenu et peinture."""
        self._detail.reposition()

    def paintEvent(self, event):
        from fm_theme.layout import _title_box
        from fm_theme.widgets import _paint_bordered_rect
        section = self._detail.opened_section()
        fill = (section.box_fill() if section is not None else None) or M["panel_bg"]
        sides, colors, thickness = (section.box_border() if section is not None and section._boxed
                                    else ({}, {}, 0))
        rect = QRect(0, 0, self.width(), self.height())
        radius = dict(_title_box(1)["radius"], top_left=0)       # coin haut gauche droit (demande, 2026-11-08)
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing, True)
        _paint_bordered_rect(p, rect, radius, False, 0, {}, fill)          # fond, sous le contour
        gap = self._detail.tab_gap()
        if gap is not None and sides.get("left") and thickness:
            # Le titre ouvert entre dans le volet par là : contour JAMAIS peint (repeindre le fond par-dessus
            # laissait voir le filet sous un fond semi-transparent, signalé).
            top, bottom = gap
            p.setClipRegion(QRegion(rect).subtracted(QRegion(QRect(0, top, thickness, max(0, bottom - top)))))
        _paint_bordered_rect(p, rect, radius, sides, thickness, colors, None)
        p.end()


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
        pane = self.pane = _Pane(self, self._page)
        pane.setObjectName("ThemeSideDetail")     # restyle_titles_in le repeint (fond / coins du titre déployé)
        outer = self._outer = QVBoxLayout(pane)
        outer.setContentsMargins(0, 0, 0, 0)
        self._scroll = v2._WideScrollArea(pane)            # un tableau plus large que le volet : défilement
        self._scroll.setWidgetResizable(True)
        self._scroll.setFrameShape(QFrame.NoFrame)
        # Transparent : le fond est celui que peint le volet (_Pane).
        self._scroll.setStyleSheet("background: transparent;")
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

    def opened_section(self):
        """Titre ouvert (le plus haut s'il y en a plusieurs, Ctrl) : sa `_Section`, ou None."""
        opened = [n for n in self._nodes if not n.is_collapsed()]
        return opened[0]._head if opened else None

    def _box_span(self, section) -> tuple[int, int]:
        """(haut, bas) du fond d'un titre, repère de la page."""
        rect = section._box_rect() if section._boxed else section.rect()
        top = section.mapTo(self._page, QPoint(0, rect.top())).y()
        return top, top + rect.height()

    def tab_gap(self) -> tuple[int, int] | None:
        """Ouverture du bord gauche du volet (repère du volet) : la hauteur du fond du titre ouvert, moins ses
        filets haut / bas, qui rejoignent ceux du volet."""
        section = self.opened_section()
        if section is None or not section._boxed:
            return None
        sides, _colors, thickness = section.box_border()
        top, bottom = self._box_span(section)
        top += thickness if sides.get("top") else 0
        bottom -= thickness if sides.get("bottom") else 0
        return top - self.pane.y(), bottom - self.pane.y()

    def _clip_titles(self, left: int | None):
        """Fond des titres coupé au bord gauche du volet (None : entier) : rien n'est peint dessous."""
        for node in self._nodes:
            section = node._head
            clip = None if left is None else section.mapFrom(self._page, QPoint(left, 0)).x()
            if getattr(section, "_side_clip", None) != clip:
                section._side_clip = clip
                section.update()

    def reposition(self, *_args):
        """Volet à droite de la colonne des titres, du haut de la liste jusqu'en bas de la page, aligné sur le bord
        droit des titres."""
        try:
            section = self.opened_section()
            if section is None:
                self.pane.hide()
                self._clip_titles(None)
                return
            top = max(0, min(self._box_span(n._head)[0] for n in self._nodes))
            right = (section.mapTo(self._page, QPoint(section._box_rect().right() + 1, 0)).x() if section._boxed
                     else self._page.width())
            left = self._left()
            self.pane.setGeometry(left, top, max(0, right - left), max(0, self._page.height() - BOTTOM_GAP - top))
            self._clip_titles(left)
            # Contenu (et ses barres de défilement) DANS le contour : il ne recouvre jamais les bordures.
            sides, _colors, thickness = section.box_border() if section._boxed else ({}, {}, 0)
            inset = tuple(thickness if sides.get(k) else 0 for k in ("left", "top", "right", "bottom"))
            m = self._outer.contentsMargins()
            if (m.left(), m.top(), m.right(), m.bottom()) != inset:
                self._outer.setContentsMargins(*inset)
            self.pane.update()
            if self.pane.isHidden():
                self.pane.show()
            self.pane.raise_()
        except RuntimeError:             # fenêtre détruite entre-temps (minuterie en attente après un changement de preset)
            pass
