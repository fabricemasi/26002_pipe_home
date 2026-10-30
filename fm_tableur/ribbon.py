"""Ruban du tableur (Qt) : familles d'Excel — Accueil, Insertion, Formules, Données, Affichage — en barre compacte.

Briques de l'appli seulement : boutons texte du Board (`_TextButton`, feuille de style de l'appli), menus
contextuels de l'appli (`settings_menu.Menu` via `fm_board.ui._menu`, lignes `menu_row`), sélecteur de police du
Board (`FontPicker`), pastilles (`_SwatchGrid`). Chaque bouton appelle une méthode de `widget.SpreadsheetWidget`."""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QHBoxLayout, QStackedWidget, QVBoxLayout, QWidget

from . import numfmt

PALETTE = ["#000000", "#404040", "#7f7f7f", "#bfbfbf", "#f2f2f2", "#ffffff",
           "#c00000", "#ff0000", "#ffc000", "#ffff00", "#92d050", "#00b050",
           "#00b0f0", "#0070c0", "#002060", "#7030a0", "#f8cbad", "#fce4d6",
           "#e2efda", "#ddebf7", "#d9e1f2", "#ededed", "#fff2cc", "#c6efce"]
SIZES = [8, 9, 10, 10.5, 11, 12, 14, 16, 18, 20, 22, 24, 26, 28, 36, 48, 72]
TABS = ["Accueil", "Insertion", "Formules", "Données", "Affichage"]


def _button(text, tip, slot, parent, width=0, bold=False):
    from fm_board.ui import _TextButton
    button = _TextButton(text, tip, parent, width)
    button.setFixedHeight(26)
    if bold:
        font = button.font()
        font.setBold(True)
        button.setFont(font)
    if slot is not None:
        button.clicked.connect(lambda _c=False: slot())
    return button


def menu(parent, key):
    from fm_board.ui import _menu
    return _menu(parent, "tableur_" + key)


def popup_under(menu_obj, anchor):
    menu_obj.popup(anchor.mapToGlobal(anchor.rect().bottomLeft()))


class Ribbon(QWidget):
    def __init__(self, sheet_widget, parent=None, compact: bool = False):
        super().__init__(parent)
        self.sw = sheet_widget
        layout = QVBoxLayout(self)
        layout.setContentsMargins(4, 2, 4, 2)
        layout.setSpacing(2)
        self.tabs_row = QHBoxLayout()
        self.tabs_row.setSpacing(2)
        self.tab_buttons = []
        for index, name in enumerate(TABS):
            button = _button(name, f"Onglet {name}", lambda i=index: self.show_tab(i), self)
            button.setCheckable(True)
            self.tab_buttons.append(button)
            self.tabs_row.addWidget(button)
        self.tabs_row.addStretch(1)
        self.extra_row = self.tabs_row                 # boutons à droite (mode Standard / Board) : widget.py
        layout.addLayout(self.tabs_row)
        self.stack = QStackedWidget(self)
        layout.addWidget(self.stack)
        builders = [self._home, self._insert, self._formulas, self._data, self._view]
        for build in builders:
            page = QWidget(self.stack)
            row = QHBoxLayout(page)
            row.setContentsMargins(0, 0, 0, 0)
            row.setSpacing(2)
            build(page, row)
            row.addStretch(1)
            self.stack.addWidget(page)
        self.show_tab(0)
        if compact:
            for button in self.tab_buttons:
                button.setFixedHeight(22)

    def show_tab(self, index):
        self.stack.setCurrentIndex(index)
        for i, button in enumerate(self.tab_buttons):
            button.setChecked(i == index)

    @staticmethod
    def _sep(row):
        row.addSpacing(8)

    # ------------------------------------------------------------ Accueil
    def _home(self, page, row):
        sw = self.sw
        for text, tip, slot in (("↶", "Annuler (Ctrl+Z)", sw.undo), ("↷", "Rétablir (Ctrl+Y)", sw.redo)):
            row.addWidget(_button(text, tip, slot, page, 28))
        self._sep(row)
        paste = _button("Coller ▾", "Coller (Ctrl+V) et collages spéciaux", None, page)
        paste.clicked.connect(lambda: self._paste_menu(paste))
        row.addWidget(paste)
        row.addWidget(_button("Couper", "Couper (Ctrl+X)", lambda: sw.grid.copy(cut=True), page))
        row.addWidget(_button("Copier", "Copier (Ctrl+C)", sw.grid.copy, page))
        self._sep(row)
        self.font_button = _button("Police ▾", "Police", None, page, 120)
        self.font_button.clicked.connect(lambda: self._font_menu(self.font_button))
        row.addWidget(self.font_button)
        self.size_button = _button("11 ▾", "Taille du texte", None, page, 54)
        self.size_button.clicked.connect(lambda: self._size_menu(self.size_button))
        row.addWidget(self.size_button)
        self.style_buttons = {}
        for key, text, tip in (("bold", "G", "Gras (Ctrl+B)"), ("italic", "I", "Italique (Ctrl+I)"),
                               ("underline", "S", "Souligné (Ctrl+U)"), ("strike", "ab̶", "Barré (Ctrl+5)")):
            button = _button(text, tip, lambda k=key: sw.grid.toggle_style(k), page, 28, bold=key == "bold")
            button.setCheckable(True)
            self.style_buttons[key] = button
            row.addWidget(button)
        color = _button("A ▾", "Couleur du texte", None, page, 40)
        color.clicked.connect(lambda: self._color_menu(color, "color"))
        fill = _button("▨ ▾", "Couleur de remplissage", None, page, 40)
        fill.clicked.connect(lambda: self._color_menu(fill, "fill"))
        borders = _button("Bordures ▾", "Bordures", None, page)
        borders.clicked.connect(lambda: self._borders_menu(borders))
        for widget in (color, fill, borders):
            row.addWidget(widget)
        self._sep(row)
        self.align_buttons = {}
        for key, value, text, tip in (("halign", "left", "⇤", "Aligner à gauche"),
                                      ("halign", "center", "↔", "Centrer"),
                                      ("halign", "right", "⇥", "Aligner à droite"),
                                      ("valign", "top", "⤒", "Aligner en haut"),
                                      ("valign", "center", "↕", "Centrer verticalement"),
                                      ("valign", "bottom", "⤓", "Aligner en bas")):
            button = _button(text, tip, lambda k=key, v=value: sw.toggle_align(k, v), page, 28)
            button.setCheckable(True)
            self.align_buttons[(key, value)] = button
            row.addWidget(button)
        self.wrap_button = _button("↵", "Renvoyer à la ligne automatiquement", lambda: sw.grid.toggle_style("wrap"),
                                   page, 28)
        self.wrap_button.setCheckable(True)
        row.addWidget(self.wrap_button)
        merge = _button("Fusionner ▾", "Fusionner et centrer", None, page)
        merge.clicked.connect(lambda: self._merge_menu(merge))
        row.addWidget(merge)
        self._sep(row)
        fmt = _button("Format ▾", "Format des nombres", None, page)
        fmt.clicked.connect(lambda: self._format_menu(fmt))
        row.addWidget(fmt)
        row.addWidget(_button("%", "Pourcentage", lambda: sw.grid.apply_style({"fmt": "0%"}), page, 28))
        row.addWidget(_button("000", "Séparateur de milliers", lambda: sw.grid.apply_style({"fmt": "#,##0.00"}),
                              page, 36))
        row.addWidget(_button(",0+", "Ajouter une décimale", lambda: sw.change_decimals(1), page, 36))
        row.addWidget(_button(",0-", "Retirer une décimale", lambda: sw.change_decimals(-1), page, 36))
        self._sep(row)
        cond = _button("Conditionnelle ▾", "Mise en forme conditionnelle", None, page)
        cond.clicked.connect(lambda: self._cond_menu(cond))
        row.addWidget(cond)
        cells = _button("Cellules ▾", "Insérer, supprimer, taille, masquer", None, page)
        cells.clicked.connect(lambda: self._cells_menu(cells))
        row.addWidget(cells)
        clear = _button("Effacer ▾", "Effacer", None, page)
        clear.clicked.connect(lambda: self._clear_menu(clear))
        row.addWidget(clear)
        row.addWidget(_button("Rechercher", "Rechercher et remplacer (Ctrl+F / Ctrl+H)", lambda: sw.show_find(False),
                              page))

    def _paste_menu(self, anchor):
        m = menu(self, "coller")
        grid = self.sw.grid
        for text, mode in (("Coller", "all"), ("Coller les valeurs", "values"), ("Coller les formules", "formulas"),
                           ("Coller la mise en forme", "formats")):
            m.addAction(text).triggered.connect(lambda _c=False, md=mode: grid.paste(md))
        popup_under(m, anchor)

    def _font_menu(self, anchor):
        from fm_board.ui import FontPicker
        from settings_menu import menu_row
        m = menu(self, "police")
        r, c = self.sw.grid.view.current
        style = self.sw.book.style_of(self.sw.grid.sheet, r, c)
        picker = FontPicker(style.get("font") or self.sw.book.default_font[0])
        picker.chosen.connect(lambda family: (self.sw.grid.apply_style({"font": family}), m.close()))
        menu_row(m, "", picker)
        popup_under(m, anchor)

    def _size_menu(self, anchor):
        m = menu(self, "taille")
        for size in SIZES:
            m.addAction(str(size).replace(".", ",")).triggered.connect(
                lambda _c=False, s=size: self.sw.grid.apply_style({"size": s}))
        m.addAction("Autre taille…").triggered.connect(self.sw.ask_font_size)
        popup_under(m, anchor)

    def _color_menu(self, anchor, key):
        from fm_board.ui import _SwatchGrid
        from settings_menu import menu_row
        m = menu(self, "couleur")
        grid = _SwatchGrid(PALETTE, None, 6)
        grid.picked.connect(lambda color: (self.sw.grid.apply_style({key: color}), m.close()))
        menu_row(m, "", grid)
        m.addAction("Aucune" if key == "fill" else "Automatique").triggered.connect(
            lambda: self.sw.grid.apply_style({key: None}))
        m.addAction("Autre couleur…").triggered.connect(lambda: self.sw.pick_color(key))
        popup_under(m, anchor)

    def _borders_menu(self, anchor):
        m = menu(self, "bordures")
        for text, kind in (("Toutes les bordures", "all"), ("Bordures extérieures", "outside"),
                           ("Bordure épaisse en encadré", "thick_outside"), ("Bordures intérieures", "inside"),
                           ("Bordure supérieure", "top"), ("Bordure inférieure", "bottom"),
                           ("Bordure gauche", "left"), ("Bordure droite", "right"), ("Aucune bordure", "none")):
            m.addAction(text).triggered.connect(lambda _c=False, k=kind: self.sw.set_borders(k))
        popup_under(m, anchor)

    def _merge_menu(self, anchor):
        m = menu(self, "fusion")
        m.addAction("Fusionner et centrer").triggered.connect(lambda: self.sw.merge(center=True))
        m.addAction("Fusionner").triggered.connect(lambda: self.sw.merge())
        m.addAction("Fusionner par ligne").triggered.connect(lambda: self.sw.merge(across=True))
        m.addAction("Annuler la fusion").triggered.connect(self.sw.unmerge)
        popup_under(m, anchor)

    def _format_menu(self, anchor):
        m = menu(self, "format")
        for name, code in numfmt.PRESETS:
            m.addAction(name).triggered.connect(lambda _c=False, cd=code: self.sw.grid.apply_style({"fmt": cd}))
        m.addAction("Format personnalisé…").triggered.connect(self.sw.ask_number_format)
        popup_under(m, anchor)

    def _cond_menu(self, anchor):
        m = menu(self, "conditionnelle")
        sw = self.sw
        for text, rule in (("Supérieur à…", {"type": "cell", "op": "greaterThan"}),
                           ("Inférieur à…", {"type": "cell", "op": "lessThan"}),
                           ("Égal à…", {"type": "cell", "op": "equal"}),
                           ("Texte qui contient…", {"type": "text", "op": "contains"}),
                           ("Formule…", {"type": "formula"})):
            m.addAction(text).triggered.connect(lambda _c=False, r=rule: sw.add_cond_rule(dict(r), ask=True))
        for text, rule in (("Valeurs en double", {"type": "duplicate"}),
                           ("10 valeurs les plus élevées", {"type": "top", "rank": 10}),
                           ("Au-dessus de la moyenne", {"type": "above_average"}),
                           ("Barres de données", {"type": "bar", "color": "#638ec6"}),
                           ("Échelle vert - jaune - rouge", {"type": "scale",
                                                             "colors": ["#63be7b", "#ffeb84", "#f8696b"]}),
                           ("Échelle blanc - vert", {"type": "scale", "colors": ["#ffffff", "#63be7b"]})):
            m.addAction(text).triggered.connect(lambda _c=False, r=rule: sw.add_cond_rule(dict(r)))
        m.addAction("Effacer les règles de la sélection").triggered.connect(sw.clear_cond_rules)
        popup_under(m, anchor)

    def _cells_menu(self, anchor):
        m = menu(self, "cellules")
        grid = self.sw.grid
        sw = self.sw
        m.addAction("Insérer des lignes").triggered.connect(lambda: sw.insert_lines("row"))
        m.addAction("Insérer des colonnes").triggered.connect(lambda: sw.insert_lines("col"))
        m.addAction("Supprimer les lignes").triggered.connect(lambda: sw.delete_lines("row"))
        m.addAction("Supprimer les colonnes").triggered.connect(lambda: sw.delete_lines("col"))
        m.addSeparator()
        m.addAction("Hauteur de ligne…").triggered.connect(lambda: sw.ask_size("row"))
        m.addAction("Largeur de colonne…").triggered.connect(lambda: sw.ask_size("col"))
        m.addAction("Masquer les lignes").triggered.connect(lambda: sw.hide_lines("row", True))
        m.addAction("Afficher les lignes").triggered.connect(lambda: sw.hide_lines("row", False))
        m.addAction("Masquer les colonnes").triggered.connect(lambda: sw.hide_lines("col", True))
        m.addAction("Afficher les colonnes").triggered.connect(lambda: sw.hide_lines("col", False))
        m.addSeparator()
        m.addAction("Commentaire…").triggered.connect(sw.edit_comment)
        m.addAction("Verrouiller / déverrouiller les cellules").triggered.connect(
            lambda: grid.apply_style({"locked": False if sw.current_style().get("locked", True) is not False
                                      else None}))
        popup_under(m, anchor)

    def _clear_menu(self, anchor):
        m = menu(self, "effacer")
        grid = self.sw.grid
        for text, what in (("Effacer tout", "all"), ("Effacer les formats", "formats"),
                           ("Effacer le contenu", "contents"), ("Effacer les commentaires", "comments")):
            m.addAction(text).triggered.connect(lambda _c=False, w=what: grid.clear_selection(w))
        popup_under(m, anchor)

    # ------------------------------------------------------------ Insertion
    def _insert(self, page, row):
        sw = self.sw
        chart = _button("Graphique ▾", "Graphique lié aux données de la sélection", None, page)
        chart.clicked.connect(lambda: self._chart_menu(chart))
        row.addWidget(chart)
        row.addWidget(_button("Commentaire", "Note sur la cellule active", sw.edit_comment, page))
        row.addWidget(_button("Fonction…", "Insérer une fonction", sw.insert_function, page))
        row.addWidget(_button("Feuille", "Nouvelle feuille", sw.add_sheet, page))
        row.addWidget(_button("Liste déroulante…", "Validation : liste de valeurs permises", sw.ask_validation,
                              page))

    def _chart_menu(self, anchor):
        from .charts import CHART_TYPES
        m = menu(self, "graphique")
        for kind, label in CHART_TYPES:
            m.addAction(label).triggered.connect(lambda _c=False, k=kind: self.sw.insert_chart(k))
        popup_under(m, anchor)

    # ------------------------------------------------------------ Formules
    def _formulas(self, page, row):
        sw = self.sw
        auto = _button("Σ Somme ▾", "Somme automatique", None, page)
        auto.clicked.connect(lambda: self._auto_menu(auto))
        row.addWidget(auto)
        row.addWidget(_button("Insérer une fonction…", "Liste des fonctions du moteur", sw.insert_function, page))
        row.addWidget(_button("Noms définis…", "Gestionnaire de noms", sw.edit_names, page))
        self._sep(row)
        row.addWidget(_button("Afficher les formules", "Ctrl+`", sw.toggle_formulas, page))
        row.addWidget(_button("Calculer (F9)", "Recalculer maintenant", sw.recalc, page))
        self.calc_button = _button("Calcul : automatique", "Mode de calcul", sw.toggle_calc_mode, page)
        row.addWidget(self.calc_button)

    def _auto_menu(self, anchor):
        m = menu(self, "somme")
        for text, fn in (("Somme", "SUM"), ("Moyenne", "AVERAGE"), ("Nombre", "COUNT"), ("Max", "MAX"),
                         ("Min", "MIN")):
            m.addAction(text).triggered.connect(lambda _c=False, f=fn: self.sw.auto_function(f))
        popup_under(m, anchor)

    # ------------------------------------------------------------ Données
    def _data(self, page, row):
        sw = self.sw
        row.addWidget(_button("Trier A → Z", "Tri croissant", lambda: sw.sort(True), page))
        row.addWidget(_button("Trier Z → A", "Tri décroissant", lambda: sw.sort(False), page))
        row.addWidget(_button("Tri personnalisé…", "Plusieurs critères", sw.custom_sort, page))
        row.addWidget(_button("Filtrer", "Filtre automatique (entêtes)", sw.toggle_filter, page))
        self._sep(row)
        row.addWidget(_button("Supprimer les doublons", "Sur les colonnes de la sélection", sw.remove_duplicates,
                              page))
        row.addWidget(_button("Convertir…", "Texte en colonnes", sw.text_to_columns, page))
        row.addWidget(_button("Liste déroulante…", "Validation des données", sw.ask_validation, page))
        self._sep(row)
        row.addWidget(_button("Importer…", "Classeur Excel (.xlsx, .xlsm) ou CSV", sw.import_file, page))
        row.addWidget(_button("Exporter…", "Classeur Excel (.xlsx) ou CSV", sw.export_file, page))

    # ------------------------------------------------------------ Affichage
    def _view(self, page, row):
        sw = self.sw
        freeze = _button("Figer les volets ▾", "Lignes / colonnes toujours visibles", None, page)
        freeze.clicked.connect(lambda: self._freeze_menu(freeze))
        row.addWidget(freeze)
        row.addWidget(_button("Quadrillage", "Afficher / masquer le quadrillage", sw.toggle_grid_lines, page))
        zoom = _button("Zoom ▾", "Zoom de la feuille", None, page)
        zoom.clicked.connect(lambda: self._zoom_menu(zoom))
        row.addWidget(zoom)
        row.addWidget(_button("Formules", "Afficher les formules (Ctrl+`)", sw.toggle_formulas, page))

    def _freeze_menu(self, anchor):
        m = menu(self, "volets")
        sw = self.sw
        m.addAction("Figer à la cellule active").triggered.connect(lambda: sw.freeze("cell"))
        m.addAction("Figer la ligne supérieure").triggered.connect(lambda: sw.freeze("row"))
        m.addAction("Figer la première colonne").triggered.connect(lambda: sw.freeze("col"))
        m.addAction("Libérer les volets").triggered.connect(lambda: sw.freeze(None))
        popup_under(m, anchor)

    def _zoom_menu(self, anchor):
        m = menu(self, "zoom")
        for value in (50, 75, 90, 100, 125, 150, 200):
            m.addAction(f"{value} %").triggered.connect(lambda _c=False, v=value: self.sw.grid.set_zoom(v / 100))
        popup_under(m, anchor)

    # ------------------------------------------------------------ état
    def sync(self, style: dict, book):
        for key, button in self.style_buttons.items():
            button.setChecked(bool(style.get(key)))
        for (key, value), button in self.align_buttons.items():
            button.setChecked(style.get(key) == value)
        self.wrap_button.setChecked(bool(style.get("wrap")))
        family = style.get("font") or book.default_font[0]
        self.font_button.setText((family[:14] + "…" if len(family) > 15 else family) + " ▾")
        size = style.get("size") or book.default_font[1]
        self.size_button.setText(f"{size:g} ▾".replace(".", ","))
        self.calc_button.setText("Calcul : " + ("automatique" if book.calc_mode == "auto" else "manuel"))


__all__ = ["Ribbon", "Qt"]
