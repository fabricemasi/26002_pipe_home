"""Module Tableur dans le sélecteur du Board (Qt) : sa barre d'outils (nouveau classeur, importer un fichier Excel /
CSV, mode Standard du classeur choisi). Activé par `BoardPane.set_module("tableur")`, comme Design.

Le module ne prend ni la souris ni le clavier de la vue (pas de crochets `view.*`) : les éléments « sheet » gèrent
eux-mêmes leurs gestes (double-clic = édition sur place, ⤢ = mode Standard, Ctrl + glisser = déplacer)."""
from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QObject, QPointF
from PySide6.QtWidgets import QFileDialog, QMessageBox

from fm_board import model
from fm_board.ui import _bar, _TextButton
from . import board_model as bm


class TableurController(QObject):
    def __init__(self, pane):
        super().__init__(pane)
        self.pane = pane
        self.active = False
        self.ui = self
        self.bar, row = _bar(pane, False)
        for text, tip, slot in (("Nouveau classeur", "Poser un classeur vide au centre de la vue", self.new_sheet),
                                ("Importer…", "Classeur Excel (.xlsx, .xlsm) ou CSV : un nouvel élément", self.import_file),
                                ("Mode Standard", "Ouvrir le classeur choisi en plein cadre", self.open_standard)):
            button = _TextButton(text, tip, self.bar)
            button.clicked.connect(lambda _c=False, s=slot: s())
            row.addWidget(button)
        self.bar.hide()

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
        self.bar.show()
        self.place()

    def deactivate(self):
        self.active = False
        self.bar.hide()

    def place(self):
        if not self.active:
            return
        self.bar.layout().activate()
        self.bar.resize(self.bar.sizeHint())
        area = self.pane.title_area()
        self.bar.move(area.right() + 12, area.top() + (area.height() - self.bar.height()) // 2)
        self.bar.raise_()

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
