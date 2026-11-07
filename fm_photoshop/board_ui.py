"""Module Photoshop dans la barre des modules du Board (Qt) : sa barre FLOTTANTE « Document » (nouveau document, importer une
image, image comme calque, éditeur Standard, exporter) et celles de l'éditeur Standard (`bars.py`). Activé par
`BoardPane.set_module("photoshop")`, comme le Tableur.

Le module ne prend ni la souris ni le clavier de la vue (pas de crochets `view.*`) : les éléments « ps_doc » gèrent eux-mêmes
leurs gestes (double-clic ou ⤢ = éditeur Standard, Ctrl + glisser = déplacer)."""
from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QObject, QPointF
from PySide6.QtGui import QGuiApplication
from PySide6.QtWidgets import (QComboBox, QDialog, QDialogButtonBox, QFileDialog, QFormLayout, QLineEdit, QMessageBox,
                               QSpinBox)

from fm_board import model
from . import board_model as bm, io_images, look
from .bars import PhotoshopBars

PRESETS = (("Web 1920 × 1080", 1920, 1080, 72), ("Carré 1080 × 1080", 1080, 1080, 72),
           ("4K 3840 × 2160", 3840, 2160, 72), ("A4 300 dpi (2480 × 3508)", 2480, 3508, 300),
           ("Petit 800 × 600", 800, 600, 72))


def clipboard_image_size() -> tuple[int, int] | None:
    """(largeur, hauteur) de l'image du presse-papiers du système, ou None s'il n'y en a pas."""
    app = QGuiApplication.instance()
    mime = app.clipboard().mimeData() if app is not None else None      # None quand le presse-papiers est vide
    if mime is None or not mime.hasImage():
        return None
    image = app.clipboard().image()
    return None if image.isNull() else (image.width(), image.height())


class NewDocumentDialog(QDialog):
    """Dimensions, résolution, fond, nom d'un document neuf. Une image dans le presse-papiers ajoute sa taille aux formats
    (juste après « Personnalisé ») et cette entrée est présélectionnée."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Nouveau document Photoshop")
        form = QFormLayout(self)
        self.name = QLineEdit("Sans titre")
        self.preset = QComboBox()
        self.preset.addItem("Personnalisé")
        self._formats = [None]                                    # une entrée par ligne du choix : (largeur, hauteur, ppp | None)
        from .model import MAX_SIDE
        clip = clipboard_image_size()
        clip_listed = self._clip_listed = clip is not None and all(1 <= side <= MAX_SIDE for side in clip)
        if clip_listed:
            self.preset.addItem(f"Presse-papiers {clip[0]} × {clip[1]}")
            self._formats.append((clip[0], clip[1], None))        # résolution du champ laissée telle quelle
        for label, w, h, dpi in PRESETS:
            self.preset.addItem(label)
            self._formats.append((w, h, dpi))
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
        if clip_listed:
            self.preset.setCurrentIndex(1)                        # présélectionné : largeur et hauteur reprises par `_preset`

    def _preset(self, index):
        if index > 0:
            w, h, dpi = self._formats[index]
            self.width_box.setValue(w)
            self.height_box.setValue(h)
            if dpi is not None:
                self.dpi_box.setValue(dpi)

    def values(self) -> dict:
        bg = {"Blanc": [255, 255, 255, 255], "Transparent": None, "Noir": [0, 0, 0, 255]}[self.background.currentText()]
        return {"w": self.width_box.value(), "h": self.height_box.value(), "dpi": self.dpi_box.value(),
                "name": self.name.text().strip() or "Sans titre", "background": bg,
                "from_clipboard": self._clip_listed and self.preset.currentIndex() == 1}     # l'entrée « Presse-papiers » est choisie


class PhotoshopController(QObject):
    def __init__(self, pane):
        super().__init__(pane)
        self.pane = pane
        self.active = False
        self.ui = self
        self.bars = PhotoshopBars(self)                   # barres flottantes du module (fm_theme), disposition `board_bars["photoshop"]`
        self.buttons = self.bars.buttons                  # (clé -> bouton de la barre « Document »)

    @property
    def bar(self):
        """La barre « Document » (un widget caché si l'utilisateur l'a supprimée)."""
        return self.bars.document_bar()

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
        self.bars.refresh()
        self.place()

    def deactivate(self):
        self.active = False
        self.bars.refresh()

    def place(self):
        """Zone des barres : le Board à droite de la barre des modules (ou l'établi de l'éditeur Standard ouvert)."""
        if not self.active and self.bars.std is None:
            return
        self.bars.place()
        self.bars.raise_all()

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
        item = self.new_document(v["w"], v["h"], v["name"], v["dpi"], v["background"])
        if item is not None and v["from_clipboard"] and look.LOOK["new_paste_clipboard"]:
            from .actions import Actions
            Actions(item.session).paste()               # l'image du presse-papiers dans un calque (annulable), centrée
        return item

    def import_file(self, path: str | None = None):
        if path is None:
            path, _f = QFileDialog.getOpenFileName(self.pane, "Importer une image", "", io_images.OPEN_FILTER)
            if not path:
                return None
        if Path(path).suffix.lower() == ".psd":
            return self.import_psd(path)
        if Path(path).suffix.lower() == ".fmps":
            return self.import_native(path)
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

    def import_native(self, path):
        """Document natif `.fmps` ouvert comme NOUVEL élément (le fichier d'origine n'est jamais modifié)."""
        from . import container
        try:
            doc = container.load(Path(path))
        except container.ContainerError as exc:
            QMessageBox.warning(self.pane, "Ouverture impossible", str(exc))
            return None
        item = self.new_document(doc.width, doc.height, doc.name, doc.dpi, None)
        if item is None:
            return None
        session = item.session
        session.doc = doc
        session.active_uid = doc.layers[-1].uid
        session.notify("reload", None)
        session.notify("committed", None)
        return item

    def import_psd(self, path):
        """Fichier PSD (lecture seule, psd-tools) : un NOUVEAU document avec ses calques, groupes, masques, modes."""
        from . import io_psd
        try:
            doc, notes = io_psd.read_psd(Path(path))
        except io_images.ImageError as exc:
            QMessageBox.warning(self.pane, "Import PSD impossible", str(exc))
            return None
        item = self.new_document(doc.width, doc.height, doc.name, doc.dpi, None)
        if item is None:
            return None
        session = item.session
        session.doc = doc
        session.active_uid = doc.layers[-1].uid
        session.notify("reload", None)
        session.notify("committed", None)
        if notes:
            QMessageBox.information(self.pane, "Import PSD", "\n".join(notes))
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

    def export(self, path: str | None = None, wait: bool = False):
        """Exporte la composition du document choisi en tâche de fond (instantané), écriture atomique."""
        item = self._need_doc("Exporter")
        if item is None:
            return None
        if path is None:
            path, _f = QFileDialog.getSaveFileName(self.pane, "Exporter", f"{item.session.doc.name}.png",
                                                   io_images.SAVE_FILTER)
            if not path:
                return None
        from . import exporter
        job = exporter.start(item.session.doc, path, None, self)
        name = Path(path).name

        def done(_p, notes, error):
            if error is not None:
                QMessageBox.warning(self.pane, "Export impossible", f"{name} :\n{error}")
        job.finished.connect(done)
        if wait:
            job.wait()
        return job
