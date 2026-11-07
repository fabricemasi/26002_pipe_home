"""Module Tableur dans le sélecteur du Board (Qt) : sa barre d'outils (nouveau classeur, importer un fichier Excel /
CSV, mode Standard du classeur choisi). Activé par `BoardPane.set_module("tableur")`, comme Design.

Le module ne prend ni la souris ni le clavier de la vue (pas de crochets `view.*`) : les éléments « sheet » gèrent
eux-mêmes leurs gestes (double-clic = édition sur place, ⤢ = mode Standard, Ctrl + glisser = déplacer)."""
from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QObject, QPointF
from PySide6.QtWidgets import QFileDialog, QMessageBox, QWidget

from fm_board import model
from fm_board.bars import BoardBars
from fm_theme.palette import PaletteTextButton
from . import board_model as bm

BUTTONS = [("new", "Nouveau classeur", "Poser un classeur vide au centre de la vue", 5),
           ("import", "Importer…", "Classeur Excel (.xlsx, .xlsm) ou CSV : un nouvel élément", 3),
           ("standard", "Mode Standard", "Ouvrir le classeur choisi en plein cadre", 4)]


def default_state() -> dict:
    """Barre flottante du Tableur par défaut (demande de l'utilisateur, 2026-11-03) : « Classeur » clipsée en haut."""
    items, col = {}, 0
    for key, _t, _tip, cells in BUTTONS:
        items[key] = [col, 0, cells]
        col += cells
    return {"next": 2, "bars": [{"id": "b1", "title": "Classeur", "dock": "top", "orient": "h", "along": 260, "x": 0,
                                 "y": 0, "cols": col, "rows": 1, "items": items}]}


class TableurController(QObject):
    def __init__(self, pane):
        super().__init__(pane)
        self.pane = pane
        self.active = False
        self.ui = self
        # Barre FLOTTANTE (fm_theme/bar_manager.py, fm_board/bars.py) : disposition retenue (`board_bars["tableur"]`).
        self.bars = BoardBars(pane, "tableur", default_state())
        slots = {"new": self.new_sheet, "import": self.import_file, "standard": self.open_standard}
        for key, text, tip, cells in BUTTONS:
            button = PaletteTextButton(key, text, tip, cells=cells)
            button.clicked.connect(lambda _c=False, s=slots[key]: s())
            self.bars.register(key, button)
        self.bars.restore()
        self.bars.set_visible(False)
        self._no_bar = QWidget(pane)
        self._no_bar.hide()

    @property
    def bar(self):
        """La barre « Classeur » (un widget caché si l'utilisateur l'a vidée)."""
        bar = self.bars.manager.bar_of("new") or self.bars.bar("b1")
        return bar if bar is not None else self._no_bar

    def apply_settings(self, settings: dict):
        """Réglages `tableur_*` changés : classeurs ouverts (édition sur place, mode Standard) mis à jour."""
        from .board_item import SheetItem
        for item in self.pane.scene.board_items():
            if isinstance(item, SheetItem) and item._widget is not None:
                item._widget.apply_settings(settings)
            if isinstance(item, SheetItem):
                item.update()                              # aperçu : couleurs du contenu
        std = getattr(self.pane, "_tableur_standard", None)
        if std is not None:
            std.widget.apply_settings(settings)

    def activate(self):
        self.active = True
        self.bars.set_visible(True)
        self.place()
        self.bars.raise_all()

    def deactivate(self):
        self.active = False
        self.bars.set_visible(False)

    def place(self):
        if not self.active:
            return
        self.bars.set_area(self.pane.left_edge())

    # -- commandes --
    def _center(self) -> QPointF:
        return self.pane.view.view_center()

    def new_sheet(self, workbook: dict | None = None, title: str = "Classeur"):
        center = self._center()
        w, h = bm.DEFAULTS[bm.SHEET]["w"], bm.DEFAULTS[bm.SHEET]["h"]
        data = model.new_item(bm.SHEET, x=round(center.x() - w / 2, 2), y=round(center.y() - h / 2, 2),
                              title=title, workbook=workbook or {})
        data["z"] = self.pane.scene.next_z()
        return self.pane.scene.add_new(data, "Nouveau classeur")

    def import_file(self, path: str | None = None):
        from . import io_files, io_native, numfmt
        if path is None:
            path, _f = QFileDialog.getOpenFileName(self.pane, "Importer un classeur", "", io_files.OPEN_FILTER)
            if not path:
                return None
        try:
            book = io_files.load(path, numfmt.DEFAULT_LOCALE)
        except Exception as exc:                           # noqa: BLE001 - fichier refusé : rien n'est touché
            QMessageBox.warning(self.pane, "Import impossible", f"{Path(path).name} :\n{exc}")
            return None
        item = self.new_sheet(io_native.to_dict(book), Path(path).stem)
        lost = book.source.get("lost") or []
        if lost:
            QMessageBox.information(self.pane, "Import : éléments non repris",
                                    "Le fichier d'origine n'est pas modifié. Non repris :\n- " + "\n- ".join(lost))
        return item

    def selected_sheet(self):
        from .board_item import SheetItem
        items = [i for i in self.pane.scene.selectedItems() if isinstance(i, SheetItem)]
        return items[0] if items else None

    def open_standard(self):
        item = self.selected_sheet()
        if item is None:
            QMessageBox.information(self.pane, "Mode Standard", "Choisissez d'abord un classeur sur le Board.")
            return
        item.open_standard()
