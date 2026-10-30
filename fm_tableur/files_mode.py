"""Classeur ouvert DIRECTEMENT depuis l'explorateur (.xlsx, .xlsm, .csv, .tsv) : board en MÉMOIRE (comme un dessin
DXF, `BoardPane.open_import`) contenant un élément « sheet », affiché aussitôt en mode Standard.

Le fichier d'origine n'est JAMAIS réécrit en silence : « Enregistrer » le remplace seulement après confirmation,
seulement si l'import n'a rien perdu (sinon : « Enregistrer sous » un nouveau fichier), et après une copie
`<nom>.bak` de l'original. À la fermeture d'un classeur modifié : enregistrer / enregistrer sous / garder en
board .mro / fermer sans enregistrer / annuler. La lecture (`read_as_board`) n'utilise pas Qt : elle peut se faire
dans un fil à part (gros classeurs)."""
from __future__ import annotations

import shutil
from pathlib import Path

from PySide6.QtWidgets import QFileDialog, QMessageBox

from . import io_native, numfmt

EXTENSIONS = (".xlsx", ".xlsm", ".csv", ".tsv")


def is_spreadsheet(path) -> bool:
    return Path(path).suffix.lower() in EXTENSIONS


def read_as_board(path) -> dict:
    """Données de board (un élément « sheet » qui porte le classeur), SANS Qt. Lève une exception si refusé."""
    from fm_board import model
    from . import io_files
    path = Path(path)
    book = io_files.load(path, numfmt.DEFAULT_LOCALE)
    item = model.new_item("sheet", x=0.0, y=0.0, w=1200.0, h=700.0, title=path.stem,
                          workbook=io_native.to_dict(book))
    data = model.empty_board()
    data["items"] = [item]
    data["view"] = {"zoom": 1.0, "center": [600.0, 350.0]}
    return data


def attach(pane, path):
    """Après `open_import` : module Tableur, mode Standard, enregistrement et fermeture propres au classeur."""
    from .board_item import SheetItem
    path = Path(path)
    pane.set_module("tableur")
    items = [i for i in pane.scene.board_items() if isinstance(i, SheetItem)]
    if not items:
        return None
    item = items[0]
    pane.import_leave_hook = lambda: leave(pane, item, path)
    pane.import_save_hook = lambda: save(pane, item, path)
    item.open_standard()
    lost = item.session.book.source.get("lost") or []
    std = getattr(pane, "_tableur_standard", None)
    if lost and std is not None:
        std.widget._message("Non repris de ce fichier : " + " ; ".join(lost))
    return item


def _write(item, target: Path) -> bool:
    from . import io_csv, io_xlsx
    book = item.session.book
    if target.suffix.lower() in (".csv", ".tsv"):
        io_csv.write(book, item.session.sheet, target, numfmt.DEFAULT_LOCALE)
    else:
        io_xlsx.write(book, target.with_suffix(".xlsx") if target.suffix.lower() != ".xlsx" else target)
    return True


def save(pane, item, path: Path) -> bool:
    """« Enregistrer » : remplacer l'original (confirmé, copie .bak) si rien n'a été perdu à l'import ; sinon
    « Enregistrer sous »."""
    book = item.session.book
    lost = book.source.get("lost") or []
    macros = path.suffix.lower() == ".xlsm"
    if lost or macros:
        return save_as(pane, item, path, "Des éléments du fichier d'origine ne sont pas repris (" +
                       "; ".join(lost or ["macros"]) + ") : enregistrer dans un NOUVEAU fichier.")
    box = QMessageBox(QMessageBox.Question, "Enregistrer",
                      f"Remplacer « {path.name} » ?\nUne copie de l'original est gardée : {path.name}.bak",
                      parent=pane)
    replace = box.addButton("Remplacer", QMessageBox.AcceptRole)
    other = box.addButton("Enregistrer sous…", QMessageBox.ActionRole)
    box.addButton("Annuler", QMessageBox.RejectRole)
    box.exec()
    if box.clickedButton() is other:
        return save_as(pane, item, path)
    if box.clickedButton() is not replace:
        return False
    try:
        shutil.copy2(path, path.with_name(path.name + ".bak"))
        _write(item, path)
    except Exception as exc:                               # noqa: BLE001
        QMessageBox.warning(pane, "Enregistrement impossible", f"{path.name} :\n{exc}")
        return False
    pane._set_dirty(False)
    return True


def save_as(pane, item, path: Path, note: str = "") -> bool:
    if note:
        QMessageBox.information(pane, "Enregistrer sous", note)
    suggestion = str(path.with_name(path.stem + " (modifié).xlsx"))
    target, _f = QFileDialog.getSaveFileName(pane, "Enregistrer sous", suggestion,
                                             "Classeur Excel (*.xlsx);;CSV (*.csv)")
    if not target:
        return False
    try:
        _write(item, Path(target))
    except Exception as exc:                               # noqa: BLE001
        QMessageBox.warning(pane, "Enregistrement impossible", f"{Path(target).name} :\n{exc}")
        return False
    pane._set_dirty(False)
    return True


def leave(pane, item, path: Path) -> bool:
    """Fermeture d'un classeur ouvert depuis l'explorateur et modifié : rien n'est perdu sans le demander."""
    box = QMessageBox(QMessageBox.Question, "Classeur modifié", f"« {path.name} » a été modifié.", parent=pane)
    save_button = box.addButton("Enregistrer…", QMessageBox.AcceptRole)
    board = box.addButton("Garder en board .mro", QMessageBox.ActionRole)
    drop = box.addButton("Fermer sans enregistrer", QMessageBox.DestructiveRole)
    box.addButton("Annuler", QMessageBox.RejectRole)
    box.exec()
    clicked = box.clickedButton()
    if clicked is save_button:
        return save(pane, item, path)
    if clicked is board:
        return pane.save_import_as_board(pane.companion_path())
    return clicked is drop
