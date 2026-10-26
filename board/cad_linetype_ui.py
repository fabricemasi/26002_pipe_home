"""Module CAD du board : Reglages > Module CAD > Types de ligne (`board_cad_linetypes`).

Un TABLEAU des reglages (`build_cells_table`), une ligne par type : nom, sequence (« 1 0.5 0.5 0.5 » : trait,
espace, trait, espace… dans l'unite de mesure du CAD), terminaisons du debut et de la fin de la ligne, terminaison
des segments interieurs (chacune avec son border radius), segment additionnel pour la repartition, apercu, action.
Champs = briques des reglages (`_TextField`, `_SelectField`, `_SliderField`, boutons `_Btn`) ; l'apercu dessine le
motif avec le MEME code que les lignes du board (`cad_items.line_outline` / `dashed_outline`, `dash_intervals`).

Apercu : un repere (triangle accent) se deplace le long de la ligne a la souris, aimante aux debuts / fins des
traits et des espaces ; du debut de la ligne au repere = le SEGMENT ADDITIONNEL de la repartition (« Repartir les
segments » dans les proprietes d'un objet : cycles entiers + ce segment sur toute la longueur)."""
from __future__ import annotations

import copy

from PySide6.QtCore import QPointF, QRectF, Qt, Signal
from PySide6.QtGui import QColor, QPainter, QPainterPath, QPen, QPolygonF
from PySide6.QtWidgets import QHBoxLayout, QVBoxLayout, QWidget

from . import cad_geometry as geo
from . import cad_model
from .cad_items import dashed_outline, line_outline

SNAP_PX = 8.0                       # aimantation du repere aux bords des traits / espaces (pixels)
CYCLES_SHOWN = 2.5                  # cycles du motif montres dans l'apercu
COLUMNS = (("Nom", 150), ("Séquence", 170), ("Début de ligne", 290), ("Fin de ligne", 290),
           ("Segments intérieurs", 290), ("Segment additionnel", 130), ("Répartir", 90), ("Redimensionner", 120), ("Aperçu", 300),
           ("Action", 120))


class LinetypePreview(QWidget):
    """Apercu d'un type de ligne + repere du segment additionnel (voir l'entete du module)."""

    extraChanged = Signal(float)         # pendant le glisser
    extraCommitted = Signal(float)       # au relachement

    MARGIN = 14.0
    WEIGHT = 8.0

    def __init__(self, definition: dict, parent=None):
        super().__init__(parent)
        self.definition = definition
        self._drag = False
        self.setFixedSize(270, 46)
        self.setAttribute(Qt.WA_TranslucentBackground, True)
        self.setMouseTracking(True)
        self.setCursor(Qt.SizeHorCursor)

    def set_definition(self, definition: dict):
        self.definition = definition
        self.update()

    # -- geometrie de l'apercu --
    def _pattern(self) -> tuple:
        return cad_model.sequence_pattern(self.definition.get("sequence") or ())

    def _span(self) -> tuple[float, float, float]:
        """(x de depart, longueur en pixels, pixels par unite)."""
        x0 = self.MARGIN
        length = self.width() - 2 * self.MARGIN
        period = cad_model.pattern_period(self._pattern())
        return x0, length, (length / (CYCLES_SHOWN * period) if period > 0 else 1.0)

    def _snaps(self) -> list[float]:
        """Positions (unites du motif) des debuts / fins de traits et d'espaces visibles dans l'apercu."""
        pattern = self._pattern()
        _x0, length, per_unit = self._span()
        if not pattern:
            return [0.0]
        out, u = [0.0], 0.0
        limit = length / per_unit
        while u < limit:
            for step in pattern:
                u += abs(step)
                out.append(u)
                if u >= limit:
                    break
        return out

    def _x_of(self, extra: float) -> float:
        x0, length, per_unit = self._span()
        return x0 + min(length, extra * per_unit)

    def _extra_at(self, x: float) -> float:
        x0, length, per_unit = self._span()
        x = max(x0, min(x0 + length, x))
        best = (x - x0) / per_unit
        for snap in self._snaps():
            if abs(self._x_of(snap) - x) <= SNAP_PX:
                if abs(self._x_of(snap) - x) < abs(self._x_of(best) - x) or best == (x - x0) / per_unit:
                    best = snap
        return round(best, 6)

    # -- dessin --
    def paintEvent(self, event):
        from settings_store import M
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing, True)
        definition = self.definition
        pattern = self._pattern()
        x0, length, per_unit = self._span()
        y = self.height() * 0.62
        half = self.WEIGHT / 2.0
        extra = float(definition.get("extra", 0.0)) if pattern else 0.0
        if pattern:                                         # zone du segment additionnel (debut -> repere)
            band = QColor(M["accent"])
            band.setAlphaF(0.18)
            painter.fillRect(QRectF(x0, y - half - 4, self._x_of(extra) - x0, self.WEIGHT + 8), band)
        end1, end2, inner = (definition.get(k) or cad_model.END_DEFAULT for k in ("end1", "end2", "inner"))
        if pattern:
            intervals = geo.dash_intervals(length, tuple(v * per_unit for v in pattern), 1.0,
                                           dot_length=self.WEIGHT, limit=4000) or [(0.0, length)]
            path = dashed_outline(intervals, length, half, end1, end2, inner)
        else:
            path = line_outline(length, half, end1, end2)
        painter.translate(x0, y)
        painter.fillPath(path, QColor(M["value_fg"]))
        painter.translate(-x0, -y)
        if pattern:                                         # repere : triangle + trait
            x = self._x_of(extra)
            accent = QColor(M["accent"])
            pen = QPen(accent, 1.5)
            painter.setPen(pen)
            painter.drawLine(QPointF(x, 8), QPointF(x, y + half + 4))
            painter.setBrush(accent)
            painter.setPen(Qt.NoPen)
            painter.drawPolygon(QPolygonF([QPointF(x - 6, 1), QPointF(x + 6, 1), QPointF(x, 9)]))
        painter.end()

    # -- souris --
    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton and self._pattern():
            self._drag = True
            self._move_to(event.position().x())

    def mouseMoveEvent(self, event):
        if self._drag:
            self._move_to(event.position().x())
        else:
            self._tip()

    def mouseReleaseEvent(self, event):
        if self._drag:
            self._drag = False
            self.extraCommitted.emit(float(self.definition.get("extra", 0.0)))

    def _move_to(self, x: float):
        extra = self._extra_at(x)
        if extra != self.definition.get("extra"):
            self.definition["extra"] = extra
            self.update()
            self.extraChanged.emit(extra)
        self._tip()

    def _tip(self):
        if self._pattern():
            self.setToolTip(f"Segment additionnel pour la répartition : {self.definition.get('extra', 0.0):g} "
                            "(du début de la ligne au repère ; aimanté aux traits et aux espaces)")
        else:
            self.setToolTip("Ligne continue : rien à répartir")


class LinetypesField(QWidget):
    """Tableau des types de ligne (voir l'entete du module). `values()` = la liste a enregistrer ; `changed` a chaque
    modification (aussitot pour les listes et les curseurs, au relachement pour le repere, en fin de saisie pour
    les textes)."""

    changed = Signal()

    def __init__(self, values, parent=None):
        super().__init__(parent)
        self.defs = cad_model.normalize_linetypes(copy.deepcopy(values) if values else
                                                  copy.deepcopy(cad_model.LINETYPE_DEFAULTS))
        self.setStyleSheet("background: transparent;")
        self._layout = QVBoxLayout(self)
        self._layout.setContentsMargins(0, 0, 0, 0)
        self._layout.setSpacing(6)
        self._table = None
        self._rebuild()

    def values(self) -> list:
        return copy.deepcopy(self.defs)

    # -- construction --
    def _rebuild(self):
        from settings_cells import build_cells_table
        from settings_store import M
        from settings_widgets import _Btn
        while self._layout.count():
            item = self._layout.takeAt(0)
            if item.widget() is not None:
                item.widget().hide()
                item.widget().deleteLater()
        rows = [self._row(definition) for definition in self.defs]
        frame, head, _cells = build_cells_table(list(COLUMNS), rows)
        frame._dims_key = "v2:CAD : Types de ligne#0"
        frame._v2_head = head
        self._table = frame
        self._layout.addWidget(frame, 0, Qt.AlignLeft)
        add = _Btn("+  Ajouter un type de ligne", "transparent", "", M["value_fg"], M["btn_hover"],
                   height=28, weight=500, padding="0 12px", align_left=True)
        add.clicked.connect(self._add)
        line = QWidget()
        line.setStyleSheet("background: transparent;")
        line_l = QHBoxLayout(line)
        line_l.setContentsMargins(0, 0, 0, 0)
        line_l.addWidget(add)
        line_l.addStretch(1)
        self._layout.addWidget(line)
        self.updateGeometry()

    def _row(self, definition: dict) -> list:
        from settings_cells import _TextField
        from settings_theme import _text_label
        from settings_widgets import _Btn
        from settings_store import M
        preview = LinetypePreview(definition)
        name = _TextField(definition["name"], 118)
        name.editingFinished.connect(lambda d=definition, f=name: self._set_name(d, f))
        sequence = _TextField(cad_model.format_sequence(definition["sequence"]), 138)
        sequence._refuses_invalid = True                    # saisie invalide : refusee, rien ne change
        sequence.setToolTip("Trait, espace, trait, espace… dans l'unité de mesure du CAD (« 1 1 », « 1 0.5 0.5 0.5 » ; "
                            "un trait de 0 = un point ; vide = continu)")
        extra = _text_label(self._extra_text(definition), "value")
        sequence.editingFinished.connect(lambda d=definition, f=sequence, p=preview, e=extra:
                                         self._set_sequence(d, f, p, e))
        preview.extraChanged.connect(lambda _v, d=definition, e=extra: e.setText(self._extra_text(d)))
        preview.extraCommitted.connect(lambda _v: self.changed.emit())
        cells = [(name, "left", "center"), (sequence, "left", "center")]
        for key in ("end1", "end2", "inner"):
            cells.append((self._end_cell(definition, key, preview), "left", "center"))
        from settings_widgets import _Toggle
        distribute = _Toggle(bool(definition.get("distribute")), style_override="toggle1", show_label=False)
        distribute.setToolTip("Répartir les segments par défaut (lignes de ce type sans override) : cycles entiers "
                              "et segment additionnel, centrés sur la ligne")
        distribute.toggled.connect(lambda on, d=definition: (d.update(distribute=bool(on)), self.changed.emit()))
        resize = _Toggle(bool(definition.get("resize")), style_override="toggle1", show_label=False)
        resize.setToolTip("Redimensionner les segments par défaut (avec « Répartir ») : le motif est allongé ou "
                          "raccourci pour remplir toute la ligne")
        resize.toggled.connect(lambda on, d=definition: (d.update(resize=bool(on)), self.changed.emit()))
        cells += [(extra, "left", "center"), (distribute, "center", "center"), (resize, "center", "center"),
                  (preview, "left", "center")]
        if definition["key"] == "continuous":
            cells.append((_text_label("Intégré", "value_muted"), "left", "center"))
        else:
            delete = _Btn("Supprimer", M["btn_bg"], M["btn_border"], M["btn_fg"], M["btn_hover"], height=25)
            delete.clicked.connect(lambda _c=False, d=definition: self._delete(d))
            cells.append((delete, "left", "center"))
        return cells

    def _end_cell(self, definition: dict, key: str, preview: LinetypePreview) -> QWidget:
        from settings_widgets import _SelectField, _SliderField
        box = QWidget()
        box.setStyleSheet("background: transparent;")
        row = QHBoxLayout(box)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(6)
        end = definition[key]
        labels = [cad_model.END_LABELS[s] for s in cad_model.END_STYLES]
        style = _SelectField(labels, cad_model.END_LABELS[end["style"]], width=118)
        radius = _SliderField(0, 100, int(round(end["radius"])), unit="%", slider_width=46, box_width=52)
        radius.setEnabled(end["style"] == "radius")
        radius.setToolTip("Border radius : rayon des coins, en % de la demi-épaisseur")

        def set_style(label):
            end["style"] = {v: k for k, v in cad_model.END_LABELS.items()}[label]
            radius.setEnabled(end["style"] == "radius")
            preview.update()
            self.changed.emit()

        def set_radius(value):
            end["radius"] = float(value)
            preview.update()
        style.changed.connect(set_style)
        radius.valueChanged.connect(set_radius)
        radius.valueChanged.connect(lambda _v: self.changed.emit())   # l'apercu en direct se cadence lui-meme
        row.addWidget(style)
        row.addWidget(radius)
        return box

    @staticmethod
    def _extra_text(definition: dict) -> str:
        if not definition["sequence"]:
            return "—"
        return f"{definition.get('extra', 0.0):g}"

    # -- actions --
    def _set_name(self, definition: dict, field):
        name = field.text().strip()
        if not name or any(d is not definition and d["name"].lower() == name.lower() for d in self.defs):
            field.setText(definition["name"])                # vide ou deja pris : nom precedent
            return
        if name != definition["name"]:
            definition["name"] = name
            self.changed.emit()

    def _set_sequence(self, definition: dict, field, preview, extra_label):
        sequence = cad_model.parse_sequence(field.text())
        if sequence is None:
            field.setText(cad_model.format_sequence(definition["sequence"]))   # invalide : sequence precedente
            field.setToolTip("Séquence invalide : des nombres ≥ 0 séparés par des espaces (« 1 0.5 0.5 0.5 »).")
            return
        if sequence == definition["sequence"]:
            return
        definition["sequence"] = sequence
        period = cad_model.pattern_period(cad_model.sequence_pattern(sequence))
        definition["extra"] = min(definition.get("extra", 0.0), 4 * period) if period > 0 else 0.0
        preview.update()
        extra_label.setText(self._extra_text(definition))
        self.changed.emit()

    def _add(self):
        definition = cad_model.normalize_linetype({
            "key": cad_model.new_linetype_key(self.defs), "name": self._free_name("Type"),
            "sequence": [1.0, 1.0], "extra": 1.0})
        self.defs.append(definition)
        self._rebuild()
        self.changed.emit()

    def _free_name(self, base: str) -> str:
        names = {d["name"].lower() for d in self.defs}
        n = 1
        while f"{base} {n}".lower() in names:
            n += 1
        return f"{base} {n}"

    def _delete(self, definition: dict):
        from settings_dialogs import confirm
        if not confirm(self, "Supprimer", "Supprimer le type de ligne",
                       f"Supprimer « {definition['name']} » ? Les lignes qui l'utilisent sont dessinées en continu "
                       "(elles le retrouvent s'il est recréé avec la même clé).", [definition["name"]], "Supprimer"):
            return
        self.defs = [d for d in self.defs if d is not definition]
        self._rebuild()
        self.changed.emit()
