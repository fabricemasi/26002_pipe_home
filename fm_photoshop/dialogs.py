"""Fenêtres de paramètres de l'éditeur Standard (Qt) : réglages et filtres avec APERÇU, transformation numérique du calque,
taille de l'image, taille de la zone de travail, valeur simple.

Aperçu des réglages : le calcul part toujours de l'ORIGINAL (copie `shadow` du calque, jamais modifiée) et tourne dans
un fil de fond ; une réponse PÉRIMÉE (un curseur a bougé entre-temps) est rejetée par numéro de génération ; seul le fil
de l'interface écrit dans le calque. Annuler remet l'original octet pour octet ; Valider pousse UNE étape."""
from __future__ import annotations

import math

import numpy as np
from PySide6.QtCore import QObject, QPointF, QRectF, QRunnable, QThreadPool, QTimer, Qt, Signal
from PySide6.QtGui import QColor, QPainter, QPen
from PySide6.QtWidgets import (QCheckBox, QComboBox, QDialog, QDialogButtonBox, QFormLayout, QHBoxLayout, QLabel,
                               QPushButton, QVBoxLayout, QWidget)

from . import adjust, ops, transform as T
from .history import TilesCommand
from .model import Layer
from .planes import rect_union


def _field(minimum, maximum, value, unit="", scale=1):
    from settings_widgets import _SliderField
    return _SliderField(int(round(minimum * scale)), int(round(maximum * scale)), int(round(value * scale)), unit=unit,
                        slider_width=190, box_width=70, scale=scale)


class _Signals(QObject):
    done = Signal(int, object)


class _Job(QRunnable):
    def __init__(self, generation, signals, work):
        super().__init__()
        self.generation, self.signals, self.work = generation, signals, work

    def run(self):
        try:
            result = self.work()
        except Exception as exc:                                       # noqa: BLE001 - affiché, jamais avalé
            result = exc
        try:
            self.signals.done.emit(self.generation, result)
        except RuntimeError:
            pass                                                       # fenêtre déjà détruite


class CurveEditor(QWidget):
    """Courbe maîtresse : glisser un point, clic = ajouter, double-clic = retirer (les extrémités restent)."""
    changed = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.points = [(0.0, 0.0), (255.0, 255.0)]
        self.setFixedSize(264, 264)
        self._drag = None

    def _to_widget(self, p):
        return QPointF(4 + p[0], 4 + 255 - p[1])

    def _from_widget(self, q):
        return (min(255.0, max(0.0, q.x() - 4)), min(255.0, max(0.0, 255 - (q.y() - 4))))

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.fillRect(self.rect(), QColor("#202225"))
        painter.setPen(QPen(QColor("#3a3d41"), 1))
        for i in range(0, 5):
            painter.drawLine(4 + i * 64, 4, 4 + i * 64, 259)
            painter.drawLine(4, 4 + i * 64, 259, 4 + i * 64)
        lut = adjust.curve_lut(self.points)
        painter.setPen(QPen(QColor("#e8e8e8"), 1.5))
        painter.setRenderHint(QPainter.Antialiasing, True)
        painter.drawPolyline([self._to_widget((i, float(lut[i]))) for i in range(256)])
        for p in self.points:
            painter.setBrush(QColor("#5aa9e6"))
            painter.drawEllipse(self._to_widget(p), 4, 4)

    def _nearest(self, q):
        for i, p in enumerate(self.points):
            if (self._to_widget(p) - q).manhattanLength() <= 10:
                return i
        return None

    def mousePressEvent(self, event):
        q = event.position()
        i = self._nearest(q)
        if i is None:
            p = self._from_widget(q)
            self.points.append(p)
            self.points.sort()
            i = self.points.index(p)
            self.changed.emit()
        self._drag = i
        self.update()

    def mouseMoveEvent(self, event):
        if self._drag is None:
            return
        x, y = self._from_widget(event.position())
        if self._drag in (0, len(self.points) - 1):
            x = self.points[self._drag][0]                                # les extrémités ne glissent qu'en hauteur
        else:
            x = min(self.points[self._drag + 1][0] - 1, max(self.points[self._drag - 1][0] + 1, x))
        self.points[self._drag] = (x, y)
        self.changed.emit()
        self.update()

    def mouseReleaseEvent(self, event):
        self._drag = None

    def mouseDoubleClickEvent(self, event):
        i = self._nearest(event.position())
        if i is not None and 0 < i < len(self.points) - 1:
            del self.points[i]
            self.changed.emit()
            self.update()


class EffectDialog(QDialog):
    """Réglage ou filtre du calque actif, avec aperçu en direct."""

    def __init__(self, session, name: str, parent=None):
        super().__init__(parent)
        self.session, self.name = session, name
        self.label, self.kind, self.specs = adjust.EFFECTS[name][0], adjust.EFFECTS[name][1], adjust.EFFECTS[name][2]
        self.setWindowTitle(self.label)
        self.layer = session.layer()
        self.shadow = Layer("ombre")
        if self.layer.pix is not None and self.layer.pix.data is not None:
            self.shadow.pix.set_all(self.layer.pix.x, self.layer.pix.y, self.layer.pix.data.copy())
        self.fields = {}
        self._extra = {}
        self._applied = None                       # (rect, avant, après) actuellement posé dans le calque par l'aperçu
        self._generation = 0
        self._busy = 0
        self._signals = _Signals(self)
        self._signals.done.connect(self._on_result)
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.setInterval(70)
        self._timer.timeout.connect(self._compute)
        box = QVBoxLayout(self)
        form = QFormLayout()
        for p in self.specs:
            scale = 10 ** p.decimals if p.decimals else 1
            field = _field(p.low, p.high, p.default, p.unit, scale)
            field.valueChanged.connect(self.schedule)
            form.addRow(p.label, field)
            self.fields[p.key] = (field, scale)
        box.addLayout(form)
        if name == "curves":
            self.curve = CurveEditor(self)
            self.curve.changed.connect(self.schedule)
            box.addWidget(self.curve)
        if name == "color_balance":
            self._build_balance(box)
        self.state = QLabel("")
        box.addWidget(self.state)
        self.preview = QCheckBox("Aperçu")
        self.preview.setChecked(True)
        self.preview.toggled.connect(self.schedule)
        box.addWidget(self.preview)
        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel | QDialogButtonBox.Reset)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        buttons.button(QDialogButtonBox.Reset).setText("Réinitialiser")
        buttons.button(QDialogButtonBox.Reset).clicked.connect(self.reset)
        box.addWidget(buttons)
        self.schedule()

    # -- paramètres --
    def _build_balance(self, box):
        self._range = "shadows"
        self._balance = {"shadows": [0.0, 0.0, 0.0], "midtones": [0.0, 0.0, 0.0], "highlights": [0.0, 0.0, 0.0]}
        self.range_box = QComboBox()
        for key, text in (("shadows", "Ombres"), ("midtones", "Tons moyens"), ("highlights", "Hautes lumières")):
            self.range_box.addItem(text, key)
        self.range_box.currentIndexChanged.connect(self._range_changed)
        box.addWidget(self.range_box)
        self.balance_fields = []
        for text in ("Cyan – Rouge", "Magenta – Vert", "Jaune – Bleu"):
            field = _field(-1.0, 1.0, 0.0, "", 100)
            field.valueChanged.connect(self._balance_changed)
            self.balance_fields.append(field)
            row = QHBoxLayout()
            row.addWidget(QLabel(text))
            row.addWidget(field)
            box.addLayout(row)
        self.keep_luminosity = QCheckBox("Conserver la luminosité")
        self.keep_luminosity.setChecked(True)
        self.keep_luminosity.toggled.connect(self.schedule)
        box.addWidget(self.keep_luminosity)

    def _range_changed(self, _i):
        self._range = self.range_box.currentData()
        for field, value in zip(self.balance_fields, self._balance[self._range]):
            field.blockSignals(True)
            field.setValue(round(value * 100))
            field.blockSignals(False)

    def _balance_changed(self, _v):
        self._balance[self._range] = [f.value() / 100.0 for f in self.balance_fields]
        self.schedule()

    def params(self) -> dict:
        out = {key: field.value() / scale for key, (field, scale) in self.fields.items()}
        if self.name == "curves":
            out["points"] = list(self.curve.points)
        if self.name == "color_balance":
            out.update(shadows=tuple(self._balance["shadows"]), midtones=tuple(self._balance["midtones"]),
                       highlights=tuple(self._balance["highlights"]),
                       preserve_luminosity=self.keep_luminosity.isChecked())
        return out

    def reset(self):
        for p in self.specs:
            field, scale = self.fields[p.key]
            field.setValue(round(p.default * scale))
        if self.name == "curves":
            self.curve.points = [(0.0, 0.0), (255.0, 255.0)]
            self.curve.update()
        self.schedule()

    # -- aperçu en fil de fond --
    def schedule(self, *_):
        self._timer.start()

    def _compute(self):
        if not self.preview.isChecked():
            self._revert()
            self._generation += 1
            return
        self._generation += 1
        generation, params = self._generation, self.params()
        selection, rect = self.session.selection, self.session.doc.rect()
        shadow, name = self.shadow, self.name
        self.state.setText("Calcul…")
        self._busy += 1
        QThreadPool.globalInstance().start(_Job(generation, self._signals,
                                                lambda: adjust.run(shadow, name, params, selection, rect, 0)))

    def _on_result(self, generation, result):
        self._busy = max(0, self._busy - 1)
        if generation != self._generation:
            return                                                     # périmé : un curseur a bougé depuis
        if isinstance(result, Exception):
            self.state.setText(f"Erreur : {result}")
            return
        self.state.setText("")
        dirty = self._applied[0] if self._applied else None
        self._revert(notify=False)
        if result is not None:
            rect, before, after = result
            self.layer.pix.write(rect, after)
            self._applied = (rect, before, after)
            dirty = rect_union(dirty, rect)
        else:
            self._applied = None
        if dirty is not None:
            self.session.notify("paint", dirty)

    def _revert(self, notify=True):
        if self._applied is not None:
            rect, before, _after = self._applied
            self.layer.pix.write(rect, before)
            self._applied = None
            if notify:
                self.session.notify("paint", rect)

    def settle(self):
        """Attend le dernier calcul demandé (tests, validation)."""
        from PySide6.QtWidgets import QApplication
        if self._timer.isActive():
            self._timer.stop()
            self._compute()
        QThreadPool.globalInstance().waitForDone(20000)
        QApplication.processEvents()

    def accept(self):
        self.settle()
        applied, self._applied = self._applied, None
        super().accept()
        if applied is not None:
            rect, before, after = applied
            self.session.do(TilesCommand(self.label, self.layer, "pixels", [(rect, before, after)]), notified=True)

    def reject(self):
        self._generation += 1
        QThreadPool.globalInstance().waitForDone(20000)
        self._revert()
        super().reject()


class TransformDialog(QDialog):
    """Transformation numérique du calque (décalage, échelle, rotation, symétries) avec aperçu : toujours recalculée
    depuis l'original ; la validation refait le calcul en bicubique."""

    def __init__(self, session, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Transformation du calque")
        self.session = session
        self.layer = session.layer()
        self.job = T.TransformSession(self.layer)
        rect = self.job.rect()
        self.empty = rect is None
        form = QFormLayout(self)
        self.dx, self.dy = _field(-5000, 5000, 0, "px"), _field(-5000, 5000, 0, "px")
        self.scale_x, self.scale_y = _field(1, 1000, 100, "%"), _field(1, 1000, 100, "%")
        self.angle = _field(-180, 180, 0, "°")
        self.flip_h, self.flip_v = QCheckBox("Symétrie horizontale"), QCheckBox("Symétrie verticale")
        self.lock = QCheckBox("Proportions liées")
        self.lock.setChecked(True)
        self.quality = QComboBox()
        for q in T.QUALITIES:
            self.quality.addItem(T.QUALITY_LABELS[q], q)
        self.quality.setCurrentIndex(T.QUALITIES.index("bicubic"))
        for label, widget in (("Décalage X", self.dx), ("Décalage Y", self.dy), ("Échelle L", self.scale_x),
                              ("Échelle H", self.scale_y), ("Rotation", self.angle)):
            form.addRow(label, widget)
        form.addRow(self.lock)
        form.addRow(self.flip_h)
        form.addRow(self.flip_v)
        form.addRow("Qualité", self.quality)
        self.scale_x.valueChanged.connect(lambda v: self._linked(self.scale_y, v))
        self.scale_y.valueChanged.connect(lambda v: self._linked(self.scale_x, v))
        for widget in (self.dx, self.dy, self.scale_x, self.scale_y, self.angle):
            widget.valueChanged.connect(self.preview)
        for box in (self.flip_h, self.flip_v):
            box.toggled.connect(self.preview)
        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        form.addRow(buttons)
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.setInterval(60)
        self._timer.timeout.connect(self._render)

    def _linked(self, other, value):
        if self.lock.isChecked() and other.value() != value:
            other.blockSignals(True)
            other.setValue(value)
            other.blockSignals(False)

    def matrix(self):
        cx, cy = self.job.center()
        m = T.IDENTITY
        if self.flip_h.isChecked():
            m = T.compose_matrices(T.flip(True, cx, cy), m)
        if self.flip_v.isChecked():
            m = T.compose_matrices(T.flip(False, cx, cy), m)
        m = T.compose_matrices(T.scaling(self.scale_x.value() / 100.0, self.scale_y.value() / 100.0, cx, cy), m)
        m = T.compose_matrices(T.rotation(self.angle.value(), cx, cy), m)
        return T.compose_matrices(T.translation(self.dx.value(), self.dy.value()), m)

    def preview(self, *_):
        self._timer.start()

    def _render(self):
        if self.empty:
            return
        self.job.matrix = self.matrix()
        dirty = self.job.render(self.job.matrix, "bilinear")
        self.session.notify("paint", dirty)

    def accept(self):
        if self._timer.isActive():
            self._timer.stop()
        if self.empty or self.matrix() == T.IDENTITY:
            if not self.empty:
                self.job.cancel()
            super().accept()
            return
        self.job.matrix = self.matrix()
        command = self.job.command(self.quality.currentData())
        super().accept()
        self.session.do(command)

    def reject(self):
        self._timer.stop()
        if not self.empty:
            dirty = self.job.rect()
            self.job.cancel()
            after = self.job.rect()
            self.session.notify("paint", rect_union(dirty, after) if dirty and after else dirty or after)
            self.session.notify("structure", None)
        super().reject()


class SizeDialog(QDialog):
    """Taille de l'image ou de la zone de travail (largeur, hauteur, proportions, qualité ou ancrage)."""

    ANCHORS = (("Haut gauche", (0, 0)), ("Haut", (0.5, 0)), ("Haut droite", (1, 0)), ("Gauche", (0, 0.5)),
               ("Centre", (0.5, 0.5)), ("Droite", (1, 0.5)), ("Bas gauche", (0, 1)), ("Bas", (0.5, 1)),
               ("Bas droite", (1, 1)))

    def __init__(self, doc, canvas: bool, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Taille de la zone de travail" if canvas else "Taille de l'image")
        self.canvas_mode, self.ratio = canvas, doc.width / doc.height
        form = QFormLayout(self)
        self.width_field, self.height_field = _field(1, 30000, doc.width, "px"), _field(1, 30000, doc.height, "px")
        self.lock = QCheckBox("Conserver les proportions")
        self.lock.setChecked(not canvas)
        form.addRow("Largeur", self.width_field)
        form.addRow("Hauteur", self.height_field)
        form.addRow(self.lock)
        self.width_field.valueChanged.connect(lambda v: self._link(self.height_field, round(v / self.ratio)))
        self.height_field.valueChanged.connect(lambda v: self._link(self.width_field, round(v * self.ratio)))
        self.quality = QComboBox()
        self.anchor = QComboBox()
        if canvas:
            for text, value in self.ANCHORS:
                self.anchor.addItem(text, value)
            self.anchor.setCurrentIndex(4)
            form.addRow("Ancrage", self.anchor)
        else:
            for q in T.QUALITIES:
                self.quality.addItem(T.QUALITY_LABELS[q], q)
            self.quality.setCurrentIndex(T.QUALITIES.index("bicubic"))
            form.addRow("Rééchantillonnage", self.quality)
        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        form.addRow(buttons)

    def _link(self, other, value):
        if self.lock.isChecked() and other.value() != value:
            other.blockSignals(True)
            other.setValue(max(1, value))
            other.blockSignals(False)

    def values(self):
        return self.width_field.value(), self.height_field.value()


class ValueDialog(QDialog):
    """Une valeur numérique (contour progressif, agrandir, contracter…)."""

    def __init__(self, title: str, label: str, low, high, value, unit="px", parent=None):
        super().__init__(parent)
        self.setWindowTitle(title)
        form = QFormLayout(self)
        self.field = _field(low, high, value, unit)
        form.addRow(label, self.field)
        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        form.addRow(buttons)

    def value(self) -> int:
        return self.field.value()


class _SourceDialog(QDialog):
    """Base des fenêtres de texte / forme : aperçu en direct dans le calque, validation = UNE étape, annulation = retour
    exact à l'état d'avant."""
    KIND = "text"

    def __init__(self, session, actions, layer, new_source, parent=None):
        super().__init__(parent)
        self.session, self.actions = session, actions
        self.creating = layer is None
        self._finished = False
        if self.creating:
            from . import vector
            layer, self.add_command = actions._insert_source_layer(vector.normalize(new_source), "Texte")
            session.notify("structure", None)
        self.layer = layer
        self.old = actions._source_state(layer)
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.setInterval(50)
        self._timer.timeout.connect(self._apply)
        self.box = QVBoxLayout(self)

    def _buttons(self):
        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        self.box.addWidget(buttons)

    def schedule(self, *_):
        self._timer.start()

    def source(self) -> dict:
        raise NotImplementedError

    def title_of(self, source) -> str:
        return self.layer.name

    def _apply(self):
        from . import vector
        before = ops.layer_rect(self.layer)
        vector.apply_source(self.layer, self.source())
        self.layer.name = self.title_of(self.layer.source)
        self.session.notify("edit", rect_union(before, ops.layer_rect(self.layer)) or (0, 0, 1, 1))

    def accept(self):
        if self._finished:
            return                                  # déjà validée ou annulée : jamais deux étapes
        self._finished = True
        if self._timer.isActive():
            self._timer.stop()
        self._apply()
        empty = self.layer.pix.data is None
        if self.creating and empty:
            self.reject()
            return
        super().accept()
        if self.creating:
            self.session.do(self.add_command)
            self.session.select_layer(self.layer)
        else:
            final = self.layer.source
            self.actions._restore_source(self.layer, self.old)
            self.actions.edit_source(self.layer, final, "Modifier le texte" if self.KIND == "text" else
                                     "Modifier la forme")
            self.layer.name = self.title_of(self.layer.source)

    def reject(self):
        if self._finished and not self.isVisible():
            return
        self._finished = True
        self._timer.stop()
        if self.creating:
            self.add_command.undo()
        else:
            self.actions._restore_source(self.layer, self.old)
        self.session.notify("structure", None)
        super().reject()


class TextDialog(_SourceDialog):
    KIND = "text"

    def __init__(self, session, actions, layer, pos, parent=None):
        from PySide6.QtGui import QFont
        from PySide6.QtWidgets import QFontComboBox, QPlainTextEdit, QSpinBox
        from .panels import Swatch
        from . import vector
        base = dict(layer.source) if layer is not None else {
            "kind": "text", "x": pos[0], "y": pos[1], "color": list(session.fg) + [255]}
        base = vector.normalize(base)
        super().__init__(session, actions, layer, base, parent)
        self.setWindowTitle("Texte")
        s = self.layer.source or base
        self.content = QPlainTextEdit(s["content"])
        self.content.setMinimumHeight(90)
        self.font_box = QFontComboBox()
        self.font_box.setCurrentFont(QFont(s["font"]))
        self.size = QSpinBox()
        self.size.setRange(1, 2000)
        self.size.setValue(int(s["size"]))
        self.bold, self.italic = QCheckBox("Gras"), QCheckBox("Italique")
        self.bold.setChecked(s["bold"])
        self.italic.setChecked(s["italic"])
        self.align = QComboBox()
        for text, value in (("Gauche", "left"), ("Centré", "center"), ("Droite", "right")):
            self.align.addItem(text, value)
        self.align.setCurrentIndex(["left", "center", "right"].index(s["align"]))
        self.width_box = QSpinBox()
        self.width_box.setRange(0, 30000)
        self.width_box.setValue(int(s["width"]))
        self.width_box.setSpecialValueText("Automatique")
        self.line_height = QSpinBox()
        self.line_height.setRange(50, 300)
        self.line_height.setSuffix(" %")
        self.line_height.setValue(int(s["line_height"]))
        self.color = list(s["color"])
        self.swatch = Swatch(lambda: tuple(self.color[:3]), self._set_color, "Couleur du texte", self)
        self._pos = (s["x"], s["y"])
        form = QFormLayout()
        form.addRow("Texte", self.content)
        form.addRow("Police", self.font_box)
        form.addRow("Corps (px)", self.size)
        row = QHBoxLayout()
        row.addWidget(self.bold)
        row.addWidget(self.italic)
        row.addWidget(self.swatch)
        form.addRow("Style", row)
        form.addRow("Alignement", self.align)
        form.addRow("Largeur du bloc", self.width_box)
        form.addRow("Interligne", self.line_height)
        self.box.addLayout(form)
        self._buttons()
        for signal in (self.content.textChanged, self.font_box.currentFontChanged, self.size.valueChanged,
                       self.bold.toggled, self.italic.toggled, self.align.currentIndexChanged,
                       self.width_box.valueChanged, self.line_height.valueChanged):
            signal.connect(self.schedule)
        self._apply()

    def _set_color(self, rgb):
        self.color = list(rgb) + [255]
        self.schedule()

    def source(self) -> dict:
        return {"kind": "text", "content": self.content.toPlainText(), "font": self.font_box.currentFont().family(),
                "size": self.size.value(), "bold": self.bold.isChecked(), "italic": self.italic.isChecked(),
                "color": self.color, "align": self.align.currentData(), "width": self.width_box.value(),
                "line_height": self.line_height.value(), "x": self._pos[0], "y": self._pos[1]}

    def title_of(self, source) -> str:
        return ((source or {}).get("content", "").strip().splitlines() or ["Texte"])[0][:24] or "Texte"


class ShapeDialog(_SourceDialog):
    KIND = "shape"

    def __init__(self, session, actions, layer, parent=None):
        from PySide6.QtWidgets import QDoubleSpinBox
        from .panels import Swatch
        super().__init__(session, actions, layer, None, parent)
        self.setWindowTitle("Forme")
        s = self.layer.source
        self.base = dict(s)
        self.fill_on = QCheckBox("Remplissage")
        self.fill_on.setChecked(bool(s["fill"]))
        self.stroke_on = QCheckBox("Contour")
        self.stroke_on.setChecked(bool(s["stroke"]))
        self.fill_color = list(s["fill"] or [0, 0, 0, 255])
        self.stroke_color = list(s["stroke"] or [0, 0, 0, 255])
        self.fill_swatch = Swatch(lambda: tuple(self.fill_color[:3]), lambda c: self._color("fill_color", c),
                                  "Couleur de remplissage", self)
        self.stroke_swatch = Swatch(lambda: tuple(self.stroke_color[:3]), lambda c: self._color("stroke_color", c),
                                    "Couleur du contour", self)
        self.width_box = QDoubleSpinBox()
        self.width_box.setRange(0, 500)
        self.width_box.setValue(s["stroke_width"])
        self.radius = QDoubleSpinBox()
        self.radius.setRange(0, 5000)
        self.radius.setValue(s["radius"])
        self.radius.setEnabled(s["shape"] == "rect")
        form = QFormLayout()
        row1, row2 = QHBoxLayout(), QHBoxLayout()
        row1.addWidget(self.fill_on)
        row1.addWidget(self.fill_swatch)
        row2.addWidget(self.stroke_on)
        row2.addWidget(self.stroke_swatch)
        form.addRow(row1)
        form.addRow(row2)
        form.addRow("Épaisseur du contour", self.width_box)
        form.addRow("Angles arrondis", self.radius)
        self.box.addLayout(form)
        self._buttons()
        for signal in (self.fill_on.toggled, self.stroke_on.toggled, self.width_box.valueChanged,
                       self.radius.valueChanged):
            signal.connect(self.schedule)
        self.fill_on.setEnabled(s["shape"] != "line")

    def _color(self, attr, rgb):
        setattr(self, attr, list(rgb) + [255])
        self.schedule()

    def source(self) -> dict:
        out = dict(self.base)
        out.update(fill=self.fill_color if self.fill_on.isChecked() and self.base["shape"] != "line" else None,
                   stroke=self.stroke_color if self.stroke_on.isChecked() else None,
                   stroke_width=self.width_box.value(), radius=self.radius.value())
        return out


class ProfileDialog(QDialog):
    """Profil colorimétrique du document : ASSIGNER (aucun pixel ne change) ou CONVERTIR (pixels recalculés)."""

    def __init__(self, session, parent=None):
        super().__init__(parent)
        from . import color
        self.session, self.color = session, color
        self.setWindowTitle("Profil colorimétrique")
        box = QVBoxLayout(self)
        doc = session.doc
        box.addWidget(QLabel("Profil actuel : " + (color.describe(doc.icc_profile) if doc.icc_profile else
                                                   "aucun (sRVB supposé)")))
        self.profiles = color.system_profiles()
        self.choice = QComboBox()
        for name, _data in self.profiles:
            self.choice.addItem(name)
        box.addWidget(self.choice)
        self.intent = QComboBox()
        for key, (label, _v) in color.INTENTS.items():
            self.intent.addItem(label, key)
        self.intent.setCurrentIndex(1)
        form = QFormLayout()
        form.addRow("Intention de rendu (conversion)", self.intent)
        box.addLayout(form)
        buttons = QDialogButtonBox()
        self.assign_button = buttons.addButton("Assigner (sans toucher aux pixels)", QDialogButtonBox.ActionRole)
        self.convert_button = buttons.addButton("Convertir (recalcule les pixels)", QDialogButtonBox.ActionRole)
        buttons.addButton(QDialogButtonBox.Close)
        self.assign_button.clicked.connect(self.assign)
        self.convert_button.clicked.connect(self.convert)
        buttons.rejected.connect(self.reject)
        box.addWidget(buttons)
        self.state = QLabel("")
        box.addWidget(self.state)

    def _selected(self):
        return self.profiles[self.choice.currentIndex()]

    def assign(self):
        name, data = self._selected()
        self.session.do(self.color.assign(self.session.doc, data, name))
        self.state.setText(f"Profil « {name} » assigné.")

    def convert(self):
        name, data = self._selected()
        try:
            command = self.color.convert(self.session.doc, data, name, self.intent.currentData())
        except ValueError as exc:
            self.state.setText(str(exc))
            return
        self.session.do(command)
        self.state.setText(f"Converti en « {name} ».")
