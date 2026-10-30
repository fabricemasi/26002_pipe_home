"""Menus des TABLEAUX et GRAPHIQUES (barre contextuelle) et saisie des données d'un graphique."""
from __future__ import annotations

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QInputDialog

from fm_board.ui import _menu
from . import design_model as dm, document as doc
from .menus import _popup, color_menu


def table_menu(ctl, anchor, tables):
    """Lignes, colonnes, en-tête, couleurs du tableau, largeurs égales."""
    from .design_model import resize_grid
    menu = _menu(ctl.pane, "design_table")
    first = tables[0].data

    def grid(dr, dc, text):
        def change(i):
            resize_grid(i.data, int(i.data["rows"]) + dr, int(i.data["cols"]) + dc)
        return lambda: doc.change(ctl.scene, tables, change, text)
    menu.addAction("Ajouter une ligne").triggered.connect(grid(1, 0, "Ajouter une ligne"))
    menu.addAction("Ajouter une colonne").triggered.connect(grid(0, 1, "Ajouter une colonne"))
    if int(first["rows"]) > 1:
        menu.addAction("Retirer la dernière ligne").triggered.connect(grid(-1, 0, "Retirer une ligne"))
    if int(first["cols"]) > 1:
        menu.addAction("Retirer la dernière colonne").triggered.connect(grid(0, -1, "Retirer une colonne"))
    menu.addAction("Colonnes de même largeur").triggered.connect(lambda: doc.change(
        ctl.scene, tables, lambda i: i.data.update(col_widths=[]), "Largeur des colonnes"))
    header = menu.addAction("Ligne d'en-tête")
    header.setCheckable(True)
    header.setChecked(bool(first.get("header", True)))
    header.triggered.connect(lambda on: doc.change(ctl.scene, tables, lambda i: i.data.update(header=bool(on)),
                                                   "En-tête"))
    menu.addSeparator()
    for key, label in (("header_fill", "Fond de l'en-tête…"), ("header_color", "Texte de l'en-tête…"),
                       ("fill", "Fond des cellules…"), ("alt_fill", "Lignes alternées…"),
                       ("stroke", "Bordures…")):
        menu.addAction(label).triggered.connect(lambda _c=False, k=key, t=label: QTimer.singleShot(
            0, lambda: color_menu(ctl, anchor, tables, k, t.rstrip("…"), allow_none=k == "alt_fill")))
    _popup(ctl, menu, anchor)


def chart_menu(ctl, anchor, charts):
    """Type de graphique, données, valeurs, grille, couleurs."""
    menu = _menu(ctl.pane, "design_chart")
    first = charts[0].data
    for kind, text in (("bar", "Barres"), ("line", "Courbe"), ("pie", "Secteurs"), ("donut", "Anneau")):
        action = menu.addAction(text)
        action.setCheckable(True)
        action.setChecked(first.get("chart") == kind)
        action.triggered.connect(lambda _c=False, k=kind: doc.change(
            ctl.scene, charts, lambda i: i.data.update(chart=k), "Type de graphique"))
    menu.addSeparator()
    menu.addAction("Modifier les données (double-clic)…").triggered.connect(
        lambda: QTimer.singleShot(0, lambda: edit_chart_data(ctl, charts[0])))
    for key, text in (("show_values", "Afficher les valeurs"), ("show_grid", "Afficher la grille")):
        action = menu.addAction(text)
        action.setCheckable(True)
        action.setChecked(bool(first.get(key, True)))
        action.triggered.connect(lambda on, k=key: doc.change(ctl.scene, charts, lambda i: i.data.update({k: bool(on)}),
                                                              "Graphique"))
    colors = menu.addMenu("Couleurs")
    colors.addAction("Palette du module").triggered.connect(lambda: doc.change(
        ctl.scene, charts, lambda i: i.data.update(colors=[]), "Couleurs du graphique"))
    for color in dm.PALETTE[6:18]:
        colors.addAction(f"Une couleur : {color}").triggered.connect(lambda _c=False, c=color: doc.change(
            ctl.scene, charts, lambda i: i.data.update(colors=[c]), "Couleurs du graphique"))
    used = ctl.document_colors()
    if used:
        colors.addAction("Couleurs du document").triggered.connect(lambda: doc.change(
            ctl.scene, charts, lambda i: i.data.update(colors=list(used)), "Couleurs du graphique"))
    _popup(ctl, menu, anchor)


def edit_chart_data(ctl, chart):
    """Données d'un graphique : « Libellé ; valeur ; valeur… », une ligne par point, une colonne par série ; 1re ligne
    facultative = noms des séries (illisible = rien ne change)."""
    series, names = dm.chart_series(chart.data)
    text, ok = QInputDialog.getMultiLineText(
        ctl.pane, "Données du graphique",
        "Une ligne par point : « Libellé ; valeur ; valeur… » (une colonne par série).\n"
        "1re ligne facultative, les noms des séries : « Libellé ; Ventes ; Coûts ».",
        dm.series_text(chart.data.get("labels") or [], series, names))
    if not ok:
        return
    found = dm.parse_series(text)
    if found is None:
        from PySide6.QtWidgets import QMessageBox
        QMessageBox.warning(ctl.pane, "Données du graphique", "Valeur illisible : rien n'a changé.")
        return
    labels, series, names = found
    doc.change(ctl.scene, [chart], lambda i: dm.set_chart_series(i.data, labels, series, names), "Données du graphique")
