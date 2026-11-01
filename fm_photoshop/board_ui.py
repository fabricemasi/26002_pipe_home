"""Module Photoshop dans la barre des modules du Board (Qt) : sa barre d'outils (nouveau document, importer une image,
éditeur Standard, exporter). Activé par `BoardPane.set_module("photoshop")`, comme le Tableur.

Le module ne prend ni la souris ni le clavier de la vue (pas de crochets `view.*`) : les éléments « ps_doc » gèrent eux-mêmes
leurs gestes (double-clic ou ⤢ = éditeur Standard, Ctrl + glisser = déplacer)."""
from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QObject, QPointF
from PySide6.QtWidgets import (QComboBox, QDialog, QDialogButtonBox, QFileDialog, QFormLayout, QLineEdit, QMessageBox,
                               QSpinBox)

from fm_board import model
from fm_board.ui import _bar, _TextButton
from . import board_model as bm, io_images, look

PRESETS = (("Web 1920 × 1080", 1920, 1080, 72), ("Carré 1080 × 1080", 1080, 1080, 72),
           ("4K 3840 × 2160", 3840, 2160, 72), ("A4 300 dpi (2480 × 3508)", 2480, 3508, 300),
           ("Petit 800 × 600", 800, 600, 72))


class NewDocumentDialog(QDialog):
    """Dimensions, résolution, fond, nom d'un document neuf."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Nouveau document Photoshop")
        form = QFormLayout(self)
        self.name = QLineEdit("Sans titre")
        self.preset = QComboBox()
        self.preset.addItem("Personnalisé")
        for label, *_ in PRESETS:
            self.preset.addItem(label)
        self.width_box, self.height_box, self.dpi_box = QSpinBox(), QSpinBox(), QSpinBox()
        for box, value, hi in ((self.width_box, 1280, 30000), (self.height_box, 720, 30000), (self.dpi_box, 72, 2400)):
            box.setRange(1, hi)
            box.setValue(value)
        self.background = QComboBox()
        self.background.addItems(["Blanc", "Transparent", "Noir"])
        form.addRow("Nom", self.name)
        form.addRow("Format", self.preset)
        form.addRow("Largeur (px)", self.width_box)
        form.addRow("Hauteur (px)", self.height_box)
        form.addRow("Résolution (ppp)", self.dpi_box)
        form.addRow("Fond", self.background)
        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        form.addRow(buttons)
        self.preset.currentIndexChanged.connect(self._preset)

    def _preset(self, index):
        if index > 0:
            _label, w, h, dpi = PRESETS[index - 1]
            self.width_box.setValue(w)
            self.height_box.setValue(h)
            self.dpi_box.setValue(dpi)

    def values(self) -> dict:
        bg = {"Blanc": [255, 255, 255, 255], "Transparent": None, "Noir": [0, 0, 0, 255]}[self.background.currentText()]
        return {"w": self.width_box.value(), "h": self.height_box.value(), "dpi": self.dpi_box.value(),
                "name": self.name.text().strip() or "Sans titre", "background": bg}


class PhotoshopController(QObject):
    def __init__(self, pane):
        super().__init__(pane)
        self.pane = pane
        self.active = False
        self.ui = self
        self.bar, row = _bar(pane, False)
        self.buttons = {}
        for key, text, tip, slot in (
                ("new", "Nouveau document…", "Poser un nouveau document au centre de la vue", self.new_document_dialog),
                ("import", "Importer…", "Une image (PNG, JPEG, TIFF, WebP) devient un nouveau document", self.import_file),
                ("layer", "Image comme calque…", "Ajouter une image comme calque du document choisi",
                 self.import_as_layer),
                ("standard", "Mode Standard", "Ouvrir le document choisi en plein cadre", self.open_standard),
                ("export", "Exporter…", "Composition du document choisi : PNG, TIFF, JPEG, WebP", self.export)):
            button = _TextButton(text, tip, self.bar)
            button.clicked.connect(lambda _c=False, s=slot: s())
            row.addWidget(button)
            self.buttons[key] = button
        self.bar.hide()

    def refresh_look(self):
        """Réglages `board_ps_*` changés (déjà posés dans `look`) : seul le contenu concerné est repeint."""
        from .board_item import PsItem
        for item in self.pane.scene.board_items():
            if isinstance(item, PsItem):
                item.update()
        std = getattr(self.pane, "_photoshop_standard", None)
        if std is not None:
            std.canvas.update()

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

    def _add_item(self, title: str, init: dict, doc_w: int, doc_h: int):
        center = self._center()
        w, h = bm.fit_size(doc_w, doc_h)
        data = model.new_item(bm.PS_DOC, x=round(center.x() - w / 2, 2), y=round(center.y() - h / 2, 2), w=w, h=h,
                              title=title, init=init, doc_w=doc_w, doc_h=doc_h)
        data["z"] = self.pane.scene.next_z()
        return self.pane.scene.add_new(data, "Nouveau document Photoshop")

    def new_document(self, width: int, height: int, name: str = "Sans titre", dpi: float = 72.0,
                     background=(255, 255, 255, 255)):
        from .model import MAX_SIDE
        if not (1 <= width <= MAX_SIDE and 1 <= height <= MAX_SIDE):
            QMessageBox.warning(self.pane, "Nouveau document", f"Dimensions de 1 à {MAX_SIDE} pixels.")
            return None
        return self._add_item(name, {"w": int(width), "h": int(height), "dpi": float(dpi), "name": name,
                                     "background": list(background) if background else None}, int(width), int(height))

    def new_document_dialog(self):
        dialog = NewDocumentDialog(self.pane)
        if dialog.exec() != QDialog.Accepted:
            return None
        v = dialog.values()
        return self.new_document(v["w"], v["h"], v["name"], v["dpi"], v["background"])

    def import_file(self, path: str | None = None):
        if path is None:
            path, _f = QFileDialog.getOpenFileName(self.pane, "Importer une image", "", io_images.OPEN_FILTER)
            if not path:
                return None
        try:
            rgba, dpi, icc, notes = io_images.import_image(path)
        except io_images.ImageError as exc:
            QMessageBox.warning(self.pane, "Import impossible", str(exc))
            return None
        height, width = rgba.shape[:2]
        item = self.new_document(width, height, Path(path).stem, dpi, None)
        if item is None:
            return None
        from . import ops
        session = item.session
        doc = session.doc
        doc.layers[0].name = Path(path).stem
        doc.layers[0].pix.set_all(0, 0, rgba)
        if icc:
            doc.icc_profile = icc
        session.notify("reload", None)
        session.notify("committed", None)
        if notes:
            QMessageBox.information(self.pane, "Import", "\n".join(notes))
        return item

    def selected_doc(self):
        from .board_item import PsItem
        items = [i for i in self.pane.scene.selectedItems() if isinstance(i, PsItem)]
        return items[0] if items else None

    def _need_doc(self, title):
        item = self.selected_doc()
        if item is None:
            QMessageBox.information(self.pane, title, "Choisissez d'abord un document Photoshop sur le Board.")
        return item

    def import_as_layer(self):
        item = self._need_doc("Image comme calque")
        if item is not None:
            pane = item.open_standard()
            if pane is not None:
                pane.import_layer()

    def open_standard(self):
        item = self._need_doc("Mode Standard")
        if item is not None:
            item.open_standard()

    def export(self, path: str | None = None):
        item = self._need_doc("Exporter")
        if item is None:
            return None
        if path is None:
            path, _f = QFileDialog.getSaveFileName(self.pane, "Exporter", f"{item.session.doc.name}.png",
                                                   io_images.SAVE_FILTER)
            if not path:
                return None
        try:
            return io_images.export_document(item.session.doc, path)
        except (io_images.ImageError, OSError) as exc:
            QMessageBox.warning(self.pane, "Export impossible", f"{Path(path).name} :\n{exc}")
            return None
