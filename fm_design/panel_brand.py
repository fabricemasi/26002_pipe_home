"""Logos et styles de texte du kit de marque. Styles (onglet Texte) : police, taille, couleur, gras… d'un style du
document, ajouté par clic droit, nommé « Style N » (renommable), partagé par tous les boards ; clic = l'appliquer.
Logos (onglet Images) : images favorites partagées par TOUS les boards
(`board_design_brand["logos"]`, chemins absolus, fichiers laissés à leur place). Clic = ajouter à la page (copiée
dans le board comme toute image importée) ; clic droit = retirer de la marque. Un fichier introuvable (disque
débranché, fichier déplacé) reste dans la liste et est compté à part ; « Retirer les introuvables » le retire.
Une image de la bibliothèque s'ajoute aux logos par clic droit."""
from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QFileDialog, QGridLayout

from fm_board.ui import _menu

IMAGE_FILTER = "Images (*.png *.jpg *.jpeg *.bmp *.gif *.webp *.tif *.tiff *.svg)"


def build_brand_logos(ctl, widget, layout, tiles: list):
    from .panels import ImageTile, _label, _wide_button
    logos = ctl.brand()["logos"]
    present = [Path(p) for p in logos if Path(p).is_file()]
    missing = len(logos) - len(present)
    title = f"Marque : logos ({len(present)})"
    if missing:
        title += f" — {missing} introuvable{'s' if missing > 1 else ''}"
    layout.addWidget(_label(title))
    layout.addWidget(_wide_button("Ajouter des logos à la marque…", "Partagés par tous les boards",
                                  lambda: add_logos_dialog(ctl), widget))
    if missing:
        layout.addWidget(_wide_button("Retirer les logos introuvables", "Fichiers déplacés ou disque absent",
                                      lambda: remove_missing(ctl), widget))
    grid = QGridLayout()
    grid.setSpacing(4)
    for n, path in enumerate(present):
        tile = ImageTile(path, widget)
        tile.setToolTip(f"{path.name}\nClic : ajouter à la page\nClic droit : retirer de la marque")
        tile.clicked.connect(lambda _c=False, p=path: ctl.add_image_files([p]))
        tile.setContextMenuPolicy(Qt.CustomContextMenu)
        tile.customContextMenuRequested.connect(lambda pos, t=tile, p=path: logo_menu(ctl, t, p, pos))
        grid.addWidget(tile, n // 3, n % 3)
        tiles.append(tile)
    layout.addLayout(grid)


def logo_menu(ctl, tile, path: Path, pos):
    menu = _menu(ctl.pane, "design_brand_logo")
    menu.addAction("Retirer de la marque").triggered.connect(lambda: _remove(ctl, str(path)))
    menu.popup(tile.mapToGlobal(pos))


def library_menu(ctl, tile, path: Path, pos):
    """Clic droit sur une image de la bibliothèque."""
    menu = _menu(ctl.pane, "design_library_image")
    action = menu.addAction("Ajouter aux logos de la marque")
    action.setEnabled(str(path) not in ctl.brand()["logos"])
    action.triggered.connect(lambda: _add(ctl, [str(path)]))
    menu.popup(tile.mapToGlobal(pos))


def add_logos_dialog(ctl):
    paths, _f = QFileDialog.getOpenFileNames(ctl.pane, "Logos de la marque", "", IMAGE_FILTER)
    if paths:
        _add(ctl, [str(Path(p).resolve()) for p in paths])


def remove_missing(ctl):
    for value in [p for p in ctl.brand()["logos"] if not Path(p).is_file()]:
        ctl.brand_remove("logos", value)
    ctl.ui.set_tab("images")


def _add(ctl, paths):
    for value in reversed(paths):
        ctl.brand_add("logos", value)
    ctl.ui.set_tab("images")


def _remove(ctl, value):
    ctl.brand_remove("logos", value)
    ctl.ui.set_tab("images")


# ---------------------------------------------------------------- styles de texte
def build_brand_styles(ctl, widget, layout):
    from .panels import _label, text_style_button
    styles = ctl.brand()["styles"]
    if not styles:
        return
    layout.addSpacing(6)
    layout.addWidget(_label("Marque : styles de texte"))
    for style in styles:
        button = text_style_button(ctl, style, "Style de la marque (clic droit : renommer, retirer)", widget,
                                   style.get("name", ""))
        button.setContextMenuPolicy(Qt.CustomContextMenu)
        button.customContextMenuRequested.connect(lambda pos, b=button, st=style: brand_style_menu(ctl, b, st, pos))
        layout.addWidget(button)


def document_style_menu(ctl, button, style, pos):
    menu = _menu(ctl.pane, "design_text_style")
    known = [{k: v for k, v in s.items() if k != "name"} for s in ctl.brand()["styles"]]
    action = menu.addAction("Ajouter à la marque")
    action.setEnabled(dict(style) not in known)
    action.triggered.connect(lambda: add_style(ctl, style))
    menu.popup(button.mapToGlobal(pos))


def brand_style_menu(ctl, button, style, pos):
    from PySide6.QtCore import QTimer
    menu = _menu(ctl.pane, "design_brand_style")
    menu.addAction("Renommer…").triggered.connect(lambda: QTimer.singleShot(0, lambda: rename_style(ctl, style)))
    menu.addAction("Retirer de la marque").triggered.connect(lambda: remove_style(ctl, style))
    menu.popup(button.mapToGlobal(pos))


def add_style(ctl, style):
    styles = ctl.brand()["styles"]
    used = {s.get("name") for s in styles}
    n = 1
    while f"Style {n}" in used:
        n += 1
    ctl.brand_add("styles", {**style, "name": f"Style {n}"})
    ctl.ui.set_tab("text")


def rename_style(ctl, style):
    from PySide6.QtWidgets import QInputDialog
    name, ok = QInputDialog.getText(ctl.pane, "Style de la marque", "Nom :", text=style.get("name", ""))
    if ok and name.strip():
        style["name"] = name.strip()
        ctl._save_brand()
        ctl.ui.set_tab("text")


def remove_style(ctl, style):
    ctl.brand_remove("styles", style)
    ctl.ui.set_tab("text")
