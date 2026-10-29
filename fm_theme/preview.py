"""Aperçu de l'éditeur fm_theme (étape 5b, docs/agents/fm_theme.md) : panneau à gauche de l'éditeur qui montre
l'ÉLÉMENT EN COURS DE MODIFICATION (la section ouverte à droite) : toggles allumés / éteints sur « Toggles », un
petit tableau sur « Tableaux »... ; une planche de tous les éléments pour ce qui touche tout (Couleurs, Polices,
Général) ou quand aucune section n'est ouverte.

Construit UNIQUEMENT avec les briques de fm_theme (jamais un style inventé) : placé DANS la fenêtre de l'éditeur,
il est restylé en direct avec elle (mêmes registres, mêmes `_restyle_*`). Aucun import de l'appli.
"""
from __future__ import annotations

from typing import Callable

from PySide6.QtCore import QPoint, Qt
from PySide6.QtWidgets import QDialog, QFrame, QHBoxLayout, QLabel, QScrollArea, QVBoxLayout, QWidget

from fm_theme.cells import _TextField, build_cells_table
from fm_theme.layout import _Section, _SubSection, _TabStrip
from fm_theme.menu import Menu, menu_row
from fm_theme.theme import _set_text_role
from fm_theme.tokens import M, toggle_style_list
from fm_theme.widgets import _Btn, _MiniSlider, _SelectField, _Toggle
from fm_theme.window import _PanelFrame, _SettingsTitleBar, install_extra_window

WIDTH = 290
GALLERY = "Tous les éléments"


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


class PreviewPanel(QFrame):
    """Panneau d'aperçu : `show_section(titre)` montre les éléments de cette section (planche si inconnue)."""

    def __init__(self, settings: Callable[[], dict], parent=None):
        super().__init__(parent)
        self._settings = settings
        self._section = None
        self.setObjectName("ThemePreview")
        self.setFixedWidth(WIDTH)
        self.setStyleSheet(f"#ThemePreview {{ background: {M['panel_bg']}; border-right: 1px solid "
                           f"{M['panel_border']}; }}")
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        self._title = _label("", "card_title")
        self._title.setContentsMargins(16, 12, 16, 4)
        outer.addWidget(self._title)
        # Outils de la section (barre des variantes de l'éditeur) : sous le titre, au-dessus des éléments.
        self._tools = QVBoxLayout()
        self._tools.setContentsMargins(16, 0, 16, 4)
        outer.addLayout(self._tools)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)      # jamais plus large que le panneau
        scroll.setStyleSheet("QScrollArea, QScrollArea > QWidget > QWidget { background: transparent; }")
        outer.addWidget(scroll, 1)
        self._body = QWidget()
        self._layout = QVBoxLayout(self._body)
        self._layout.setContentsMargins(16, 8, 16, 16)
        self._layout.setSpacing(10)
        scroll.setWidget(self._body)
        self._builders = {
            "Toggles": self._toggles, "Sliders": self._sliders, "Zone de saisie": self._inputs,
            "Bouton": self._buttons, "Tableaux": self._table, "Tabs": self._tabs, "TITRES": self._titles,
            "Menu contextuel": self._menu, "Fenêtres additionnelles": self._window,
        }
        self.show_section(None)

    def set_tools(self, widget: QWidget | None) -> None:
        """Remplace les outils affichés sous le titre (None : aucun)."""
        while self._tools.count():
            old = self._tools.takeAt(0).widget()
            if old is not None:
                old.hide()
                old.setParent(None)
                old.deleteLater()
        if widget is not None:
            self._tools.addWidget(widget)

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
        self._add(_MiniSlider(0, 100, 35, width=WIDTH - 60))
        self._add(_MiniSlider(0, 100, 80, width=WIDTH - 60))

    def _inputs(self):
        self._add(_TextField("Texte saisi", width=WIDTH - 60))
        self._add(_SelectField(["Choix A", "Choix B", "Choix C"], "Choix A", width=WIDTH - 60))

    def _buttons(self):
        self._add(_row(_plain_btn("Bouton"), _accent_btn("Valider")))

    def _table(self):
        rows = [[_label(name), _label(value, "value")] for name, value in
                (("Taille", "12 Mo"), ("Type", "Image"), ("Date", "29/10/2026"))]
        frame, _head, _cells = build_cells_table([("Nom", 90), ("Valeur", 0)], rows)
        self._add(frame)

    def _tabs(self):
        self._add(_TabStrip(["Onglet 1", "Onglet 2"]))

    def _titles(self):
        titles = [_Section("Titre niveau 1")] + [_SubSection(f"Titre niveau {n}", level=n) for n in (2, 3, 4)]
        for title in titles:
            title.set_collapsed(True)            # titres seuls : leur police, couleur, retrait, paragraphe
            self._add(title)

    def _menu(self):
        button = self._add(_plain_btn("Ouvrir le menu d'exemple"))

        def open_menu():
            menu = Menu(button)
            menu.addAction("Ouvrir")
            menu.addAction("Renommer")
            menu.addSeparator()
            menu_row(menu, "Taille", _MiniSlider(0, 100, 50, width=120))
            menu.addAction("Supprimer").setEnabled(False)
            menu.exec(button.mapToGlobal(QPoint(0, button.height() + 4)))

        button.clicked.connect(open_menu)

    def _window(self):
        button = self._add(_plain_btn("Ouvrir une fenêtre d'exemple"))
        button.clicked.connect(lambda: SampleWindow(self.window()).show())
