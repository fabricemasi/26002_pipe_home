"""Champ « images de test des LUT » des Parametres generaux (section LUT).

Propre a Pipeline Browser (ne pas copier dans une autre appli sans le revoir) :
il passe par `settings_store.HOOKS` (enregistres par browser_core) pour savoir
quel type d'image on a (RAW / 8 bits / flottant), quels encodages proposer et
produire l'apercu converti — aucun import de previews/browser_core ici.

Pour chaque image : un encodage (sRGB tel quel, ou S-Log3 / F-Log / F-Log2),
des explications adaptees a son type, et un apercu de l'image TELLE QUE LA LUT
la recevra.
"""
import os
from pathlib import Path

from PySide6.QtCore import QObject, QRunnable, QThreadPool, Qt, Signal
from PySide6.QtGui import QImage, QPixmap
from PySide6.QtWidgets import (
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from app_style import C
from settings_store import HOOKS, M
from settings_theme import _set_text_role
from settings_widgets import _Btn, _SelectField, _qfont

LUT_HELP_TEXT = (
    "Comment ça marche : dans l'inspecteur et les colonnes, un fichier .cube s'affiche appliqué à "
    "l'image de test par défaut (★). Ajoute tes images, choisis l'image par défaut, puis indique pour "
    "chacune l'encodage que tes LUT attendent en entrée.\n"
    "Pense-bête : une LUT « log vers Rec.709 » (S-Log3, F-Log…) doit recevoir une image log, une LUT "
    "créative une image normale. Sinon le rendu paraît faux (trop contrasté et saturé, ou délavé). "
    "Changer l'image par défaut ou son encodage régénère les aperçus .cube."
)

_KIND_NAMES = {
    "raw": "RAW (données capteur)",
    "8bit": "image 8 bits",
    "float": "image flottante (EXR/HDR)",
}

_KIND_HELP = {
    "raw": (
        "Fichier RAW (données brutes du capteur, 12 à 14 bits) : l'appli le développe elle-même, sans le "
        "style de l'appareil. Choisis l'encodage attendu par ta LUT : une LUT Sony « S-Log3 » demande "
        "S-Log3, une LUT Fuji « F-Log » demande F-Log. Avec le module rawpy, toute la latitude du capteur "
        "est conservée ; sans lui, l'appli convertit le JPEG intégré au fichier (approximation, moins de latitude)."
    ),
    "8bit": (
        "Image 8 bits (JPEG, PNG, WebP…) : déjà en sRGB, contraste et couleurs figés. « Telle quelle » "
        "convient aux LUT créatives qui attendent une image d'affichage. Pour une LUT log, choisis la "
        "conversion : elle simule une prise de vue log à partir de l'sRGB. C'est une approximation : pas de "
        "vraie latitude, hautes lumières et ombres sont déjà écrêtées. Pour un test exact, préfère un RAW."
    ),
    "float": (
        "Image flottante (EXR/HDR) : affichée avec un tone-mapping d'affichage, sans conversion log "
        "possible ici. Utilise plutôt un RAW ou une image 8 bits pour tester des LUT log."
    ),
}


def _hook(name, default=None):
    return HOOKS.get(name, default)


class _Signals(QObject):
    done = Signal(int, QImage)


class _PreviewJob(QRunnable):
    """Calcule l'image convertie hors du thread de l'interface (un RAW peut
    prendre une ou deux secondes)."""

    def __init__(self, token: int, path: str, curve: str, max_dim: int, make):
        super().__init__()
        self.token, self.path, self.curve, self.max_dim, self.make = token, path, curve, max_dim, make
        self.signals = _Signals()

    def run(self):
        image = QImage()
        try:
            result = self.make(self.path, self.curve, self.max_dim)
            if result is not None:
                image = result
        except Exception:
            pass
        self.signals.done.emit(self.token, image)


class LutTestImagesField(QWidget):
    """Liste d'images de test (+ / − / Par défaut) avec, pour l'image
    sélectionnée : type, encodage, explications, apercu converti et export."""

    changed = Signal()
    _STAR = "★ "
    _FILTER = ("Images (*.png *.jpg *.jpeg *.tif *.tiff *.bmp *.exr *.hdr *.webp *.arw *.raf *.dng "
               "*.cr2 *.cr3 *.nef *.orf *.rw2);;Tous les fichiers (*)")
    _WIDTH = 520
    _PREVIEW = (256, 144)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._default = ""
        self._curves: dict[str, str] = {}
        self._token = 0
        self._jobs: dict[int, QRunnable] = {}
        self._choices: list[tuple[str, str]] = []
        self.setFixedWidth(self._WIDTH)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(6)

        self.list = QListWidget(self)
        self.list.setFixedHeight(120)
        self.list.currentItemChanged.connect(lambda *_: self._on_selection())
        layout.addWidget(self.list)

        buttons = QHBoxLayout()
        buttons.setSpacing(4)
        for label, width, callback, tip in (
            ("+", 24, self._add, "Ajouter des images de test"),
            ("-", 24, self._remove_selected, "Retirer l'image sélectionnée de la liste (le fichier n'est pas supprimé)"),
            ("Par défaut", 80, self._set_default_selected,
             "L'image sélectionnée devient celle sur laquelle les LUT sont appliquées dans les aperçus"),
        ):
            button = QPushButton(label, self)
            button.setFixedSize(width, 20)
            button.setFont(_qfont(13 if len(label) == 1 else 9, 700))
            button.setToolTip(tip)
            button.clicked.connect(callback)
            buttons.addWidget(button)
        buttons.addStretch(1)
        layout.addLayout(buttons)

        self.info = QLabel(self)
        self.info.setWordWrap(True)
        _set_text_role(self.info, "row_label")
        layout.addWidget(self.info)

        caption = QLabel("Encodage donné à la LUT pour cette image :", self)
        _set_text_role(caption, "inline_label")
        layout.addWidget(caption)
        self.curve_field = _SelectField(["-"], "-", width=self._WIDTH)
        self.curve_field.setToolTip(
            "Encodage donné à la LUT pour cette image. Le choix proposé dépend du type de fichier (RAW ou 8 bits).")
        self.curve_field.changed.connect(self._on_curve_changed)
        layout.addWidget(self.curve_field)

        self.help = QLabel(self)
        self.help.setWordWrap(True)
        _set_text_role(self.help, "note")
        layout.addWidget(self.help)

        preview_row = QHBoxLayout()
        preview_row.setSpacing(10)
        self.thumb = QLabel(self)
        self.thumb.setFixedSize(*self._PREVIEW)
        self.thumb.setAlignment(Qt.AlignCenter)
        self.thumb.setToolTip("Image telle que la LUT la reçoit (avant application de la LUT)")
        preview_row.addWidget(self.thumb)
        side = QVBoxLayout()
        side.setSpacing(4)
        self.thumb_caption = QLabel(self)
        self.thumb_caption.setWordWrap(True)
        _set_text_role(self.thumb_caption, "note")
        side.addWidget(self.thumb_caption)
        self.export_btn = _Btn("Enregistrer l'image convertie…", M["btn_bg"], M["btn_border"], M["btn_fg"],
                               M["btn_hover"], height=24)
        self.export_btn.setToolTip(
            "Enregistre en PNG l'image convertie (avant LUT), pour la comparer ou la passer dans un autre logiciel")
        self.export_btn.clicked.connect(self._export)
        side.addWidget(self.export_btn)
        side.addStretch(1)
        preview_row.addLayout(side, 1)
        layout.addLayout(preview_row)

        self.refresh_style()
        self._on_selection()

    # -- style ---------------------------------------------------------

    def refresh_style(self):
        self.list.setStyleSheet(
            f"QListWidget {{ background: {C['well']}; color: {C['text']}; "
            f"border: 1px solid {C['border']}; border-radius: 0px; }}"
            "QListWidget::item { padding: 2px 4px; }"
            f"QListWidget::item:selected {{ background: {C['sel_idle']}; }}"
        )
        for button in self.findChildren(QPushButton):
            if isinstance(button, (_Btn, _SelectField)):
                continue
            button.setStyleSheet(
                f"QPushButton {{ background: {C['btn']}; color: {C['text']}; "
                f"border: 1px solid {C['btn_border']}; border-radius: 3px; padding: 0px; }}"
                f"QPushButton:hover {{ background: {C['btn_hover']}; }}"
            )
        self.thumb.setStyleSheet(f"background: {C['well']}; border: 1px solid {C['border']};")

    # -- liste ---------------------------------------------------------

    def _paths(self) -> list[str]:
        return [self.list.item(i).data(Qt.UserRole) for i in range(self.list.count())]

    def _current_path(self) -> str:
        item = self.list.currentItem()
        return item.data(Qt.UserRole) if item is not None else ""

    def _kind(self, path: str) -> str:
        return _hook("lut_image_kind", lambda _p: "8bit")(path)

    def _refresh_labels(self):
        for i in range(self.list.count()):
            item = self.list.item(i)
            path = item.data(Qt.UserRole)
            curve = self._curves.get(path, "srgb")
            tag = "" if curve == "srgb" else f"  [{curve}]"
            item.setText((self._STAR if path == self._default else "") + Path(path).name + tag)
            item.setToolTip(f"{path}\n{_KIND_NAMES.get(self._kind(path), '')}")

    def _append(self, path: str):
        item = QListWidgetItem(self.list)
        item.setData(Qt.UserRole, path)

    def _add(self):
        files, _ = QFileDialog.getOpenFileNames(self, "Images de test", "", self._FILTER)
        known = {os.path.normcase(p) for p in self._paths()}
        added = False
        for name in files:
            name = os.path.normpath(name)
            if os.path.normcase(name) not in known:
                self._append(name)
                known.add(os.path.normcase(name))
                added = True
        if added:
            if not self._default:
                self._default = self._paths()[0]
            self._refresh_labels()
            if self.list.currentItem() is None:
                self.list.setCurrentRow(0)
            self.changed.emit()

    def _remove_selected(self):
        selected = self.list.selectedItems()
        for item in selected:
            self._curves.pop(item.data(Qt.UserRole), None)
            self.list.takeItem(self.list.row(item))
        if selected:
            paths = self._paths()
            if self._default not in paths:
                self._default = paths[0] if paths else ""
            self._refresh_labels()
            self._on_selection()
            self.changed.emit()

    def _set_default_selected(self):
        path = self._current_path()
        if path and path != self._default:
            self._default = path
            self._refresh_labels()
            self._on_selection()
            self.changed.emit()

    # -- image sélectionnée ---------------------------------------------

    def _on_selection(self):
        path = self._current_path()
        has = bool(path)
        for widget in (self.curve_field, self.export_btn):
            widget.setEnabled(has)
        if not has:
            self.info.setText("Aucune image de test : un .cube s'affichera sur une mire de couleurs intégrée. "
                              "Ajoute une image avec « + ».")
            self.help.setText("")
            self.thumb.clear()
            self.thumb_caption.setText("")
            self._choices = []
            self.curve_field.setOptions(["-"])
            return
        kind = self._kind(path)
        star = " — image par défaut" if path == self._default else ""
        self.info.setText(f"{Path(path).name} : {_KIND_NAMES.get(kind, kind)}{star}")
        chooser = _hook("lut_curve_choices", lambda _k: [("srgb", "Telle quelle")])
        self._choices = list(chooser(kind))
        labels = [label for _key, label in self._choices]
        self.curve_field.setOptions(labels)
        current = self._curves.get(path, "srgb")
        self.curve_field.setValue(next((lb for k, lb in self._choices if k == current), labels[0]))
        self._refresh_help(kind)
        self._start_preview()

    def _current_curve(self) -> str:
        label = self.curve_field.value()
        return next((k for k, lb in self._choices if lb == label), "srgb")

    def _refresh_help(self, kind: str):
        text = _KIND_HELP.get(kind, "")
        if self._current_curve() != "srgb":
            text += ("\nL'image est donc convertie avant d'être donnée à la LUT : "
                     "elle paraît volontairement plate et délavée, c'est normal pour du log.")
        self.help.setText(text)

    def _on_curve_changed(self, _label: str):
        path = self._current_path()
        if not path:
            return
        curve = self._current_curve()
        if curve == "srgb":
            self._curves.pop(path, None)
        else:
            self._curves[path] = curve
        self._refresh_labels()
        self._refresh_help(self._kind(path))
        self._start_preview()
        self.changed.emit()

    # -- apercu converti ------------------------------------------------

    def _start_preview(self):
        make = _hook("lut_test_image")
        path = self._current_path()
        self._token += 1
        if make is None or not path:
            self.thumb.clear()
            return
        self.thumb.setText("Calcul…")
        self.thumb_caption.setText("Image telle que la LUT la reçoit (avant application de la LUT).")
        job = _PreviewJob(self._token, path, self._current_curve(), 640, make)
        job.signals.done.connect(self._on_preview_done)
        self._jobs[self._token] = job   # garde le QObject de signaux vivant jusqu'au retour
        QThreadPool.globalInstance().start(job)

    def _on_preview_done(self, token: int, image: QImage):
        self._jobs.pop(token, None)
        if token != self._token:
            return
        if image.isNull():
            self.thumb.setText("Aperçu impossible")
            self.thumb_caption.setText(
                "Cette image n'a pas pu être lue (format non géré, ou module numpy/rawpy manquant).")
            return
        self.thumb.setPixmap(QPixmap.fromImage(image).scaled(
            self.thumb.size(), Qt.KeepAspectRatio, Qt.SmoothTransformation))

    def _export(self):
        make = _hook("lut_test_image")
        path = self._current_path()
        if make is None or not path:
            return
        suggested = f"{Path(path).stem}_{self._current_curve()}.png"
        target, _ = QFileDialog.getSaveFileName(
            self, "Enregistrer l'image convertie", str(Path(path).with_name(suggested)), "PNG (*.png)")
        if not target:
            return
        image = make(path, self._current_curve(), 4096)
        if image is None or image.isNull() or not image.save(target, "PNG"):
            QMessageBox.warning(self, "Enregistrer l'image convertie", "L'image n'a pas pu être enregistrée.")

    # -- valeurs --------------------------------------------------------

    def values(self) -> list[str]:
        return self._paths()

    def default(self) -> str:
        return self._default

    def curves(self) -> dict[str, str]:
        paths = set(self._paths())
        return {p: c for p, c in self._curves.items() if p in paths and c != "srgb"}

    def set_values(self, values, default="", curves=None):
        self.list.blockSignals(True)
        self.list.clear()
        for path in values or []:
            self._append(str(path))
        paths = self._paths()
        self._default = default if default in paths else (paths[0] if paths else "")
        self._curves = {p: c for p, c in (curves or {}).items() if p in paths}
        self._refresh_labels()
        if paths:
            self.list.setCurrentRow(0)
        self.list.blockSignals(False)
        self._on_selection()
