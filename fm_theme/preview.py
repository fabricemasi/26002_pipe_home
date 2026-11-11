"""Aperçu de l'éditeur fm_theme (étape 5b, docs/agents/fm_theme.md) : panneau à gauche de l'éditeur qui montre
l'ÉLÉMENT EN COURS DE MODIFICATION (la section ouverte à droite) : toggles allumés / éteints sur « Toggles », un
petit tableau sur « Tableaux »... ; une planche de tous les éléments pour ce qui touche tout (Couleurs, Polices,
Général) ou quand aucune section n'est ouverte.

Construit UNIQUEMENT avec les briques de fm_theme (jamais un style inventé) : placé DANS la fenêtre de l'éditeur,
il est restylé en direct avec elle (mêmes registres, mêmes `_restyle_*`). Aucun import de l'appli.
"""
from __future__ import annotations

from typing import Callable

from PySide6.QtCore import QPoint, QRectF, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QPainter, QPainterPath, QPen, QPixmap, QRegion
from PySide6.QtWidgets import QDialog, QFrame, QHBoxLayout, QLabel, QScrollArea, QVBoxLayout, QWidget

from fm_theme.cells import _TextField, build_cells_table
from fm_theme.layout import _Section, _SubSection, _TabStrip
from fm_theme.menu import Menu
from fm_theme.theme import _set_text_role
from fm_theme.tokens import M, _resolve_color_value, toggle_style_list
from fm_theme.widgets import _Btn, _MiniSlider, _SelectField, _Toggle
from fm_theme.window import _PanelFrame, _SettingsTitleBar, install_extra_window

WIDTH = 290
MIN_WIDTH, MAX_WIDTH = 220, 900            # largeur réglable à la souris (bord gauche du panneau)
GALLERY = "Tous les éléments"


class _WidthGrip(QWidget):
    """Bord DROIT du panneau (il est à gauche des sections depuis le 2026-11-10) : le tirer change sa largeur."""

    def __init__(self, panel):
        super().__init__(panel)
        self.panel = panel
        self.setCursor(Qt.SizeHorCursor)
        self.setFixedWidth(6)
        self._start = None

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            self._start = (event.globalPosition().x(), self.panel.width())
            event.accept()

    def mouseMoveEvent(self, event):
        if self._start is not None:
            x0, w0 = self._start
            self.panel.set_panel_width(round(w0 + (event.globalPosition().x() - x0)))
            event.accept()

    def mouseReleaseEvent(self, event):
        if self._start is not None:
            self._start = None
            self.panel.widthChanged.emit(self.panel.width())
            event.accept()


def _label(text: str, role: str = "row_label") -> QLabel:
    return _set_text_role(QLabel(text), role)


def _plain_btn(text: str) -> _Btn:
    return _Btn(text, M["btn_bg"], M["btn_border"], M["btn_fg"], M["btn_hover"], height=25, padding="0 11px")


def _accent_btn(text: str) -> _Btn:
    return _Btn(text, M["accent"], M["accent_border"], M["accent_fg"], M["accent_hover"], height=25, weight=600,
                padding="0 13px")


def _row(*widgets) -> QWidget:
    holder = QWidget()
    layout = QHBoxLayout(holder)
    layout.setContentsMargins(0, 0, 0, 0)
    layout.setSpacing(8)
    for widget in widgets:
        layout.addWidget(widget)
    layout.addStretch(1)
    return holder


class SampleWindow(QDialog):
    """Fenêtre additionnelle d'exemple (section « Fenêtres additionnelles ») : cadre, ombre, barres."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowFlags(Qt.Tool | Qt.FramelessWindowHint)
        self.setAttribute(Qt.WA_DeleteOnClose, True)
        panel = _PanelFrame(self)
        panel.setColors(M["panel_bg"], M["panel_border"])
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.addWidget(panel)
        root = QVBoxLayout(panel)
        root.setContentsMargins(1, 1, 1, 1)
        root.setSpacing(0)
        bar = _SettingsTitleBar(self, title="Fenêtre d'exemple")
        bar.dirty_label.hide()
        bar.closeClicked.connect(self.close)
        root.addWidget(bar)
        body = QWidget()
        body_layout = QVBoxLayout(body)
        body_layout.setContentsMargins(16, 14, 16, 16)
        body_layout.addWidget(_label("Contenu de la fenêtre."))
        root.addWidget(body, 1)
        buttons = QWidget()
        buttons_layout = QHBoxLayout(buttons)
        buttons_layout.setContentsMargins(14, 8, 14, 8)
        buttons_layout.addStretch(1)
        close = _plain_btn("Fermer")
        close.clicked.connect(self.close)
        buttons_layout.addWidget(close)
        root.addWidget(buttons)
        install_extra_window(self, panel, outer, root, bar, buttons)
        self.resize(320, 200)


# -- Un élément par type à variantes (volet des variantes de l'éditeur : un aperçu SOUS CHAQUE variante, demande de
# l'utilisateur, 2026-11-11). `values` : les réglages à plat de la variante montrée (sur les réglages courants).

def _column(*widgets, spacing: int = 8) -> QWidget:
    holder = QWidget()
    layout = QVBoxLayout(holder)
    layout.setContentsMargins(0, 0, 0, 0)
    layout.setSpacing(spacing)
    for widget in widgets:
        layout.addWidget(widget)
    return holder


def grab_offscreen(widget: QWidget, width: int | None = None) -> QPixmap:
    """Image d'un élément jamais montré à l'écran (fenêtre, menu déployé, variante non éditée)."""
    from PySide6.QtWidgets import QApplication
    widget.setAttribute(Qt.WA_DontShowOnScreen, True)
    widget.show()
    QApplication.sendPostedEvents()            # mise en page faite : la hauteur voulue est la bonne
    if width:
        widget.resize(width, widget.sizeHint().height())
    else:
        widget.adjustSize()
    QApplication.sendPostedEvents()
    # Fond TRANSPARENT : `grab` d'une fenêtre jamais montrée peignait son fond par défaut (blanc) autour de l'élément.
    ratio = widget.devicePixelRatioF()
    pixmap = QPixmap(widget.size() * ratio)
    pixmap.setDevicePixelRatio(ratio)
    pixmap.fill(Qt.transparent)
    widget.render(pixmap, QPoint(), QRegion(), QWidget.RenderFlag.DrawChildren)
    widget.hide()
    return pixmap


class _Shot(QLabel):
    """Aperçu-IMAGE d'un élément qui ne vit pas dans le volet (menu déployé, fenêtre) : refait par `set_values`."""

    def __init__(self, values: dict, width: int):
        super().__init__()
        self._w = width
        self.setAttribute(Qt.WA_TransparentForMouseEvents, True)
        self.setStyleSheet("background: transparent;")
        self.set_values(values)

    def set_values(self, values: dict) -> None:
        self.setPixmap(self._render(values))

    def _render(self, values: dict) -> QPixmap:
        raise NotImplementedError


class MenuShot(_Shot):
    """Menu contextuel DÉPLOYÉ (ses lignes, un séparateur, une ligne désactivée)."""

    def _render(self, values: dict) -> QPixmap:
        from fm_theme import menu as menu_module
        saved = menu_module._STATE["values"]
        menu_module._STATE["values"] = lambda: values
        try:
            menu = Menu()
            menu.addAction("Ouvrir")
            menu.addAction("Renommer")
            menu.addAction("Copier le chemin")
            menu.addSeparator()            # (une ligne à contrôle ne se dessine pas hors écran : pas d'exemple)
            menu.addAction("Supprimer").setEnabled(False)
            menu_module.prepare_menu(menu)          # son habillage (posé d'ordinaire à l'ouverture)
            pixmap = grab_offscreen(menu)
            menu.deleteLater()
        finally:
            menu_module._STATE["values"] = saved
        return pixmap


class WindowShot(_Shot):
    """Fenêtre additionnelle d'exemple, en image (habillage courant des fenêtres additionnelles)."""

    def _render(self, values: dict) -> QPixmap:
        window = SampleWindow()
        window.setAttribute(Qt.WA_DeleteOnClose, False)
        pixmap = grab_offscreen(window, self._w)
        window.deleteLater()
        return pixmap


SHOT_BODY = 16                 # hauteur du morceau de fenêtre montré avec une barre (aperçu « capture »)
SHOT_RADIUS = 6


class BarShot(QWidget):
    """Barre de navigation (`kind` « navigation » : le HAUT d'une fenêtre, icône, titre, boutons de fenêtre) ou barre
    d'état (« etat » : le BAS d'une fenêtre, fermé à droite, chemin et informations), peinte d'après `values` comme un
    morceau de capture d'écran (captures de l'utilisateur, 2026-11-11)."""

    def __init__(self, kind: str, values: dict, width: int):
        super().__init__()
        self.kind = kind
        self.setFixedWidth(width)
        self.setAttribute(Qt.WA_TransparentForMouseEvents, True)
        self.set_values(values)

    def _int(self, key: str, default: int, low: int = 0) -> int:
        try:
            return max(low, int(self._v.get(key) if self._v.get(key) is not None else default))
        except (TypeError, ValueError):
            return default

    def _bar_height(self) -> int:
        return self._int("navbar_height", 30, 12) if self.kind == "navigation" else self._int("statusbar_height", 24, 12)

    def set_values(self, values: dict) -> None:
        self._v = dict(values or {})
        self.setFixedHeight(self._bar_height() + SHOT_BODY)
        self.update()

    def _color(self, key: str, default: str) -> QColor:
        color = QColor(_resolve_color_value(self._v.get(key) or default, self._v.get("colors") or {}))
        return color if color.isValid() else QColor(default)

    def paintEvent(self, event):
        from fm_theme.menu import _font
        from fm_theme.placeholder import ink
        v, w, h, bar = self._v, self.width(), self.height(), self._bar_height()
        top = self.kind == "navigation"
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing, True)
        # La fenêtre : coins arrondis du côté montré, l'autre côté coupé (hors de l'image).
        frame = QRectF(0.5, 0.5, w - 1, h + SHOT_RADIUS * 2) if top else \
            QRectF(0.5, -SHOT_RADIUS * 2, w - 1, h + SHOT_RADIUS * 2 - 0.5)
        path = QPainterPath()
        path.addRoundedRect(frame, SHOT_RADIUS, SHOT_RADIUS)
        painter.setClipPath(path)
        painter.fillRect(self.rect(), QColor(M["panel_bg"]))
        y0 = 0 if top else h - bar
        prefix = "navbar" if top else "statusbar"
        painter.fillRect(0, y0, w, bar, self._color(f"{prefix}_bg_color", "#202326"))
        line = "navbar_bottom" if top else "statusbar_top"
        if v.get(f"{line}_enabled", True):
            thick = self._int(f"{line}_thickness", 1)
            painter.fillRect(0, bar - thick if top else y0, w, thick, self._color(f"{line}_color", "#2c3034"))
        if top:
            painter.setPen(QPen(ink(), 1.4))                      # icônes dessinées par le code : magenta
            painter.setBrush(Qt.NoBrush)
            painter.drawEllipse(QRectF(11, y0 + bar / 2 - 5, 10, 10))
            painter.setFont(_font(v, "navbar_title", 11))
            painter.setPen(self._color("navbar_title_font_color", "#7d858b"))
            painter.drawText(QRectF(30, y0, max(0, w - 150), bar), Qt.AlignVCenter | Qt.AlignLeft, "Fenêtre d'exemple")
            size = self._int("navbar_winbtn_size", 30, 16)
            painter.setPen(QPen(ink(), 1.2))
            for index in range(3):
                cx, cy = w - size * (3 - index) + size / 2, y0 + bar / 2
                if index == 0:
                    painter.drawLine(QPoint(round(cx - 5), round(cy)), QPoint(round(cx + 5), round(cy)))
                elif index == 1:
                    painter.drawRect(QRectF(cx - 4.5, cy - 4.5, 9, 9))
                else:
                    painter.drawLine(QPoint(round(cx - 4), round(cy - 4)), QPoint(round(cx + 4), round(cy + 4)))
                    painter.drawLine(QPoint(round(cx + 4), round(cy - 4)), QPoint(round(cx - 4), round(cy + 4)))
        else:
            pad = self._int("statusbar_padding_x", 10)
            box = QRectF(pad, y0, max(0, w - 2 * pad), bar)
            painter.setFont(_font(v, "statusbar_path", 11))
            painter.setPen(self._color("statusbar_path_font_color", "#b9bfc4"))
            painter.drawText(box, Qt.AlignVCenter | Qt.AlignLeft, "F:\\PIPELINE\\NOTES")
            painter.setFont(_font(v, "statusbar_info", 11))
            painter.setPen(self._color("statusbar_info_font_color", "#5f666b"))
            painter.drawText(box, Qt.AlignVCenter | Qt.AlignRight, "12 éléments")
        painter.setClipping(False)
        painter.setPen(QPen(QColor(M["panel_border"]), 1))      # contour de la fenêtre (fermé à droite)
        painter.setBrush(Qt.NoBrush)
        painter.drawPath(path)
        painter.end()


def small_table(width: int) -> QWidget:
    """Tableau d'exemple RÉDUIT (deux lignes, à la largeur du volet)."""
    rows = [[_label(name), _label(value, "value")] for name, value in (("Taille", "12 Mo"), ("Type", "Image"))]
    frame, _head, _cells = build_cells_table([("Nom", max(60, width // 3)), ("Valeur", 0)], rows)
    # Clé de dimensions PROPRE : sinon il reprenait les largeurs enregistrées d'un autre tableau (1142 px, hors du volet)
    frame.dimsKey = lambda: "fm_theme:apercu_tableau"
    frame.setFixedWidth(width)                 # jamais plus large que le cadre de la variante
    return frame


def titles_column() -> QWidget:
    titles = [_Section("Titre niveau 1")] + [_SubSection(f"Titre niveau {n}", level=n) for n in (2, 3, 4)]
    for title in titles:
        title.set_collapsed(True)            # titres seuls : leur police, couleur, retrait, paragraphe
    return _column(*titles, spacing=4)


def element(type_name: str, values: dict, width: int) -> QWidget | None:
    """Aperçu d'un type à variantes, à la largeur `width` : habillage COURANT des briques (posé par l'appelant), sauf
    ce que `values` donne lui-même (menu, barres, barres d'outils). None : type sans aperçu."""
    if type_name == "slider":
        return _column(_MiniSlider(0, 100, 35, width=width), _MiniSlider(0, 100, 80, width=width))
    if type_name == "champ":
        return _column(_TextField("Texte saisi", width=width),
                       _SelectField(["Choix A", "Choix B", "Choix C"], "Choix A", width=width))
    if type_name == "tableau":
        return small_table(width)
    if type_name == "onglets":
        return _TabStrip(["Onglet 1", "Onglet 2"])
    if type_name == "titres":
        return titles_column()
    if type_name == "palette":
        from fm_theme.bar_manager import sample_workspace
        from fm_theme.palette import set_look
        set_look(values)                                 # habillage de la variante avant de construire
        return sample_workspace(width, 300)
    if type_name == "menu":
        return MenuShot(values, width)
    if type_name == "fenetre":
        return WindowShot(values, width)
    if type_name in ("navigation", "etat"):
        return BarShot(type_name, values, width)
    return None


class PreviewPanel(QFrame):
    """Panneau d'aperçu, à GAUCHE des sections : `show_section(titre)` montre les éléments de cette section (planche si
    inconnue). En tête : le titre et un outil à droite (`set_header_tool` : « + » des variantes) ; dessous, dans la zone
    qui défile, les outils de la section (`set_tools` : la liste des variantes) puis ses éléments. Sa largeur se règle
    en tirant son bord droit (`set_panel_width`, `widthChanged(largeur)` en fin de geste : l'hôte la retient)."""

    widthChanged = Signal(int)

    def __init__(self, settings: Callable[[], dict], parent=None, width: int = WIDTH):
        super().__init__(parent)
        self._settings = settings
        self._section = None
        self._w = max(MIN_WIDTH, min(MAX_WIDTH, int(width or WIDTH)))
        self._rebuild = QTimer(self)                      # contenu refait à la nouvelle largeur, une fois le geste posé
        self._rebuild.setSingleShot(True)
        self._rebuild.setInterval(120)
        self._rebuild.timeout.connect(lambda: self.show_section(self._section, force=True))
        self.setObjectName("ThemePreview")
        self.setFixedWidth(self._w)
        self._grip = _WidthGrip(self)
        self.setStyleSheet(f"#ThemePreview {{ background: {M['panel_bg']}; border-right: 1px solid "
                           f"{M['panel_border']}; }}")
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        head = QHBoxLayout()
        head.setContentsMargins(16, 12, 16, 4)
        self._title = _label("", "card_title")
        head.addWidget(self._title)
        head.addStretch(1)
        self._head_tool = QHBoxLayout()           # outil de l'en-tête (« + » des variantes)
        head.addLayout(self._head_tool)
        outer.addLayout(head)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)      # jamais plus large que le panneau
        scroll.setStyleSheet("QScrollArea, QScrollArea > QWidget > QWidget { background: transparent; }")
        outer.addWidget(scroll, 1)
        self._body = QWidget()
        body = QVBoxLayout(self._body)
        body.setContentsMargins(16, 8, 16, 16)
        body.setSpacing(10)
        # Outils de la section (liste des variantes de l'éditeur) : en tête de la zone qui défile.
        self._tools = QVBoxLayout()
        self._tools.setContentsMargins(0, 0, 0, 0)
        body.addLayout(self._tools)
        self._content = QWidget()
        self._layout = QVBoxLayout(self._content)
        self._layout.setContentsMargins(0, 0, 0, 0)
        self._layout.setSpacing(10)
        body.addWidget(self._content)
        body.addStretch(1)                         # le vide sous le contenu : rien n'est étiré en hauteur
        scroll.setWidget(self._body)
        self._builders = {
            "Toggles": self._toggles, "Sliders": self._sliders, "Zone de saisie": self._inputs,
            "Bouton": self._buttons, "Tableaux": self._table, "Tabs": self._tabs, "Barres d'outils": self._palette,
            "TITRES": self._titles, "Menu contextuel": self._menu, "Fenêtres additionnelles": self._window,
            "Barre de navigation": self._navbar, "Barre d'état": self._statusbar,
        }
        self.show_section(None)

    def set_panel_width(self, width: int) -> None:
        """Nouvelle largeur (bornée) : le panneau suit tout de suite, son contenu est refait au repos (120 ms)."""
        width = max(MIN_WIDTH, min(MAX_WIDTH, int(width)))
        if width != self._w:
            self._w = width
            self.setFixedWidth(width)
            self._rebuild.start()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._grip.setGeometry(self.width() - self._grip.width(), 0, self._grip.width(), self.height())
        self._grip.raise_()

    @staticmethod
    def _clear(layout) -> None:
        while layout.count():
            old = layout.takeAt(0).widget()
            if old is not None:
                old.hide()
                old.setParent(None)
                old.deleteLater()

    def set_header_tool(self, widget: QWidget | None) -> None:
        """Remplace l'outil de l'en-tête, à droite du titre (None : aucun)."""
        self._clear(self._head_tool)
        if widget is not None:
            self._head_tool.addWidget(widget)

    def set_tools(self, widget: QWidget | None, replace: bool = False) -> None:
        """Remplace les outils de la section, en tête de la zone qui défile (None : aucun) ; `replace` : ils tiennent
        lieu d'aperçu (les éléments de la section ne sont pas montrés : variantes du bouton, chacune ses aperçus)."""
        self._clear(self._tools)
        if widget is not None:
            self._tools.addWidget(widget)
        self._content.setVisible(not (replace and widget is not None))

    def tools(self) -> QWidget | None:
        item = self._tools.itemAt(0) if self._tools.count() else None
        return item.widget() if item is not None else None

    def section(self) -> str:
        return self._section or GALLERY

    def show_section(self, title: str | None, force: bool = False) -> None:
        """Montre la section `title` (None, ou une section qui touche tout : la planche). Rien si inchangé."""
        title = title if title in self._builders else None
        if title == self._section and not force and self._layout.count():
            return
        self._section = title
        while self._layout.count():
            item = self._layout.takeAt(0)
            widget = item.widget()
            if widget is not None:                   # cache et detache TOUT DE SUITE (deleteLater attend la boucle)
                widget.hide()
                widget.setParent(None)
                widget.deleteLater()
        self._title.setText(title or GALLERY)
        builders = [self._builders[title]] if title else list(self._builders.values())
        for build in builders:
            if not title:
                self._layout.addWidget(_label(next(k for k, v in self._builders.items() if v == build), "note"))
            build()
        self._layout.addStretch(1)

    # -- Une page par section : les éléments, dans leurs états utiles --

    def _add(self, widget: QWidget) -> QWidget:
        self._layout.addWidget(widget)
        return widget

    def _toggles(self):
        for style in toggle_style_list(self._settings()):
            self._add(_label(style["name"], "inline_label"))
            self._add(_row(_Toggle(True, style_override=style["key"]), _Toggle(False, style_override=style["key"])))

    def _sliders(self):
        self._add(_MiniSlider(0, 100, 35, width=self._w - 60))
        self._add(_MiniSlider(0, 100, 80, width=self._w - 60))

    def _inputs(self):
        self._add(_TextField("Texte saisi", width=self._w - 60))
        self._add(_SelectField(["Choix A", "Choix B", "Choix C"], "Choix A", width=self._w - 60))

    def _buttons(self):
        self._add(_row(_plain_btn("Bouton"), _accent_btn("Valider")))

    def _table(self):
        self._add(small_table(self._w - 60))

    def _tabs(self):
        self._add(_TabStrip(["Onglet 1", "Onglet 2"]))

    def _palette(self):
        """Barres flottantes : un mini espace de travail avec trois barres (le prototype de l'utilisateur) ; tous les
        gestes y marchent, pour juger les réglages en situation."""
        from fm_theme.bar_manager import sample_workspace
        from fm_theme.palette import set_look
        set_look(self._settings())                       # habillage courant avant de construire
        self._add(_row(sample_workspace(self._w - 32)))
        note = _label("Titre : glisser (s'aimante aux bords et aux barres) ; Ctrl + clic : renommer ; double-clic : "
                      "pivoter. Bords : redimensionner, de case en case. Icône (ou poignée d'un contrôle) : glisser "
                      "vers une case libre, d'une barre à l'autre, ou dans le vide : nouvelle barre. Trait de droite "
                      "d'un contrôle : largeur.", "note")
        note.setWordWrap(True)
        self._add(note)

    def _titles(self):
        self._add(titles_column())

    def _menu(self):
        self._add(MenuShot(self._settings(), self._w - 32))          # déployé

    def _window(self):
        self._add(WindowShot(self._settings(), self._w - 32))

    def _navbar(self):
        self._add(BarShot("navigation", self._settings(), self._w - 32))

    def _statusbar(self):
        self._add(BarShot("etat", self._settings(), self._w - 32))
