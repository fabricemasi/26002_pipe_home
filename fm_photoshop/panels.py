"""Panneaux de l'éditeur Standard (Qt) : calques (liste, réglages, masques) et brosse (taille, dureté, couleurs).

Briques du Board et des réglages (`_slider`, `_TextButton`, `_ColorPickerPopup`, rôles de texte) : aucun style inventé.
Réglage d'un curseur (opacité…) : appliqué en direct, UNE seule étape d'annulation à la fin du geste."""
from __future__ import annotations

from PySide6.QtCore import QSignalBlocker, QSize, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QIcon, QImage, QPainter, QPen, QPixmap
from PySide6.QtWidgets import (QAbstractItemView, QCheckBox, QComboBox, QGridLayout, QHBoxLayout, QLabel, QListWidget,
                               QListWidgetItem, QPushButton, QVBoxLayout, QWidget)

from . import ops
from .brush import Brush
from .history import CallCommand
from .model import BLEND_LABELS, BLEND_MODES


import os as _os

PEN_LOG_FOLDER = _os.path.join(_os.path.dirname(_os.path.dirname(_os.path.abspath(__file__))), "data", "pen_logs")


def _title(text: str) -> QLabel:
    from settings_theme import _text_label
    return _text_label(text, "card_title")


def _button(text: str, tip: str, slot, parent=None, checkable=False) -> QPushButton:
    from fm_board.ui import _TextButton
    button = _TextButton(text, tip, parent)
    button.setCheckable(checkable)
    button.clicked.connect(lambda _c=False: slot())
    return button


def _slider(label: str, minimum, maximum, value, unit, on_change, parent=None, label_width=64):
    from fm_board.ui import _slider as make
    box = QWidget(parent)
    row = QHBoxLayout(box)
    row.setContentsMargins(0, 0, 0, 0)
    row.setSpacing(6)
    text = QLabel(label)
    text.setFixedWidth(label_width)
    field = make(minimum, maximum, value, unit)
    field.valueChanged.connect(on_change)
    row.addWidget(text)
    row.addWidget(field, 1)
    box.field = field
    return box


class Swatch(QPushButton):
    """Pastille de couleur (premier plan / arrière-plan) : un clic ouvre le sélecteur de couleur des réglages."""

    def __init__(self, getter, setter, label: str, parent=None):
        super().__init__(parent)
        self.getter, self.setter, self.label = getter, setter, label
        self.setFixedSize(34, 34)
        self.setToolTip(label)
        self.clicked.connect(self._pick)

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.fillRect(self.rect().adjusted(3, 3, -3, -3), QColor(*self.getter()))
        painter.setPen(QPen(QColor("#888888"), 1))
        painter.drawRect(self.rect().adjusted(3, 3, -4, -4))

    def _pick(self):
        from .bars import pick_color
        self._popup = pick_color(self, self.getter, self._set, self.label)

    def _set(self, rgb):
        self.setter(rgb)
        self.update()


class _Row:
    """Ligne de réglage dont le champ (`field`) est un élément d'une barre flottante : mêmes noms que `_slider`."""

    def __init__(self, field):
        self.field = field


class BrushPanel(QWidget):
    """Brosse : espacement, lissage, rayon de retouche, modes, pression ; présélections. Taille, dureté, opacité et débit
    (`QUICK`) et les couleurs de premier plan / arrière-plan sont des éléments des barres flottantes du module
    (`bars.StandardPalettes`) : créés ici (ils pilotent la brosse de la session), posés dans les barres par l'éditeur."""

    QUICK = ("size", "hardness", "opacity", "flow")

    def __init__(self, session, canvas, parent=None, settings=None):
        super().__init__(parent)
        self.session, self.canvas = session, canvas
        self._settings_dict = settings if isinstance(settings, dict) else {}
        box = QVBoxLayout(self)
        box.setContentsMargins(0, 0, 0, 0)
        box.setSpacing(4)
        box.addWidget(_title("Brosse"))
        self.presets = QComboBox(self)
        self.presets.setToolTip("Présélections de brosses (persistantes)")
        self.presets.activated.connect(self._preset_chosen)
        line = QHBoxLayout()
        line.addWidget(self.presets, 1)
        line.addWidget(_button("Enregistrer", "Enregistrer la brosse actuelle comme présélection", self.save_preset, self))
        line.addWidget(_button("Retirer", "Retirer la présélection choisie (celles d'usine restent)", self.delete_preset,
                               self))
        box.addLayout(line)
        b = session.brush
        self.rows = {}
        for key, label, lo, hi, value, unit, scale in (
                ("size", "Taille", 1, 1000, b.size, "px", 1), ("hardness", "Dureté", 0, 100, b.hardness * 100, "%", 100),
                ("opacity", "Opacité", 1, 100, b.opacity * 100, "%", 100), ("flow", "Débit", 1, 100, b.flow * 100, "%", 100),
                ("spacing", "Espacement", 2, 200, b.spacing * 100, "%", 100),
                ("smoothing", "Lissage", 0, 95, b.smoothing * 100, "%", 100),
                ("sigma", "Rayon retouche", 1, 50, b.sigma, "px", 1)):
            change = lambda v, k=key, s=scale: self._set(k, v / s)
            if key in self.QUICK:
                from fm_theme.palette import PaletteSliderBar
                bar = PaletteSliderBar("brush_" + key, label, lo, hi, round(value), unit)
                bar.valueChanged.connect(change)
                self.rows[key] = _Row(bar)
                continue
            row = _slider(label, lo, hi, round(value), unit, change, self)
            self.rows[key] = row
            box.addWidget(row)
        from .brush import SMOOTHING_LABELS
        mode_line = QHBoxLayout()
        mode_label = QLabel("Mode lissage")
        mode_label.setFixedWidth(64)
        self.smoothing_mode = QComboBox(self)
        self.smoothing_mode.setToolTip("Aucun : la trajectoire du stylet telle quelle. Adaptatif : filtre One Euro (petits mouvements "
                                       "lents lissés, gestes rapides intacts). Pondéré : moyenne sur la distance, angles conservés. "
                                       "Stabilisateur : corde tirée pour l'encrage.")
        for kind, label in SMOOTHING_LABELS.items():
            self.smoothing_mode.addItem(label, kind)
        self.smoothing_mode.setCurrentIndex(self.smoothing_mode.findData(b.smoothing_kind()))
        self.smoothing_mode.activated.connect(self._mode_chosen)
        mode_line.addWidget(mode_label)
        mode_line.addWidget(self.smoothing_mode, 1)
        box.addLayout(mode_line)
        from .brush import PAINT_LABELS
        paint_line = QHBoxLayout()
        paint_label = QLabel("Dépôt")
        paint_label.setFixedWidth(64)
        self.paint_mode = QComboBox(self)
        self.paint_mode.setToolTip("Plafond : l'opacité est une limite, repasser dans le trait n'ajoute rien au-delà ; le débit règle "
                                   "la vitesse pour l'atteindre. Accumulation naturelle : un passage dépose son opacité de façon "
                                   "homogène, chaque retour sur une zone déjà peinte s'y ajoute (deux passages à 30 % donnent 51 %). "
                                   "Indépendant de la pression.")
        for kind, label in PAINT_LABELS.items():
            self.paint_mode.addItem(label, kind)
        self.paint_mode.setCurrentIndex(self.paint_mode.findData(b.paint_mode))
        self.paint_mode.activated.connect(lambda i: setattr(self.session.brush, "paint_mode", self.paint_mode.itemData(i)))
        paint_line.addWidget(paint_label)
        paint_line.addWidget(self.paint_mode, 1)
        box.addLayout(paint_line)
        flags = QHBoxLayout()
        self.pressure_size = QCheckBox("Taille")
        self.pressure_flow = QCheckBox("Débit")
        self.pressure_opacity = QCheckBox("Opacité")
        self.airbrush = QCheckBox("Aérographe")
        self.airbrush.setToolTip("Le dépôt dépend du TEMPS : la peinture continue de s'ajouter tant que le stylet reste appuyé, même "
                                 "immobile (le débit = part déposée par seconde). Les modes Plafond / Accumulation gardent leur sens.")
        self.airbrush.setChecked(b.airbrush)
        self.airbrush.toggled.connect(lambda on: setattr(session.brush, "airbrush", on))
        for check, key in ((self.pressure_size, "pressure_size"), (self.pressure_flow, "pressure_flow"),
                           (self.pressure_opacity, "pressure_opacity")):
            check.setChecked(getattr(b, key))
            check.setToolTip("La pression du stylet commande : " + check.text().lower())
            check.toggled.connect(lambda on, k=key: setattr(session.brush, k, on))
        flags.addWidget(QLabel("Pression :"))
        flags.addWidget(self.pressure_size)
        flags.addWidget(self.pressure_flow)
        flags.addWidget(self.pressure_opacity)
        flags.addStretch(1)
        flags.addWidget(self.airbrush)
        box.addLayout(flags)
        self._build_tuning(box)
        from .bars import PsSwatch
        self.fg = PsSwatch("fg", lambda: session.fg, lambda c: setattr(session, "fg", c), "Couleur de premier plan")
        self.bg = PsSwatch("bg", lambda: session.bg, lambda c: setattr(session, "bg", c), "Couleur d'arrière-plan")
        canvas.colorsChanged.connect(self.sync)
        self._fill_presets()

    # -- réglages d'essai du moteur de trait (temporaires : pour trouver les bonnes valeurs) --
    TUNING_SLIDERS = (                                # (clé, libellé, min, max, unité, échelle)
        ("pressure_filter", "Filtre pression", 5, 100, "%", 100),
        ("size_gamma", "Courbe taille", 30, 300, "", 100),
        ("opacity_gamma", "Courbe opacité", 30, 300, "", 100),
        ("flow_gamma", "Courbe débit", 30, 300, "", 100),
        ("min_diameter", "Diamètre min.", 0, 100, "%", 100),
        ("oe_cutoff_max", "Adaptatif : coupure", 2, 100, "Hz", 1),
        ("oe_beta", "Adaptatif : vitesse", 0, 100, "/100", 100),
        ("weighted_px", "Pondéré : fenêtre", 5, 200, "px", 1),
        ("rope_px", "Stabilis. : corde", 10, 400, "px", 1),
        ("continuous_spacing", "Espacement serré", 1, 35, "%", 100),
        ("curve_chord", "Pas de courbe", 3, 40, "/10 px", 10),
        ("feather", "Douceur du bord", 0, 40, "/10 px", 10),
        ("hard_feather", "Douceur bord dur", 0, 30, "/10 px", 10),
        ("soft_union", "Fusion pointes douces", 0, 100, "%", 100),
        ("air_rate", "Aérographe : vitesse", 10, 500, "%", 100),
        ("catch_up_speed", "Vitesse rattrapage", 2, 100, "%", 100))
    TUNING_TOGGLES = (("zoom_adjust", "Ajuster pour le zoom"),
                      ("catch_up_end", "Rattrapage en fin de trait"),
                      ("catch_up_pause", "Rattrapage pendant une pause"),
                      ("pressure_at_tip", "Pression suivant la pointe"))

    def _build_tuning(self, box):
        from .brush import TUNING
        self.tuning_toggle = _button("Réglages d'essai ▾", "Valeurs du moteur de trait à essayer (temporaire)",
                                     self._show_tuning, self, checkable=True)
        self.tuning_toggle.setChecked(True)
        box.addWidget(self.tuning_toggle)
        self.tuning_box = QWidget(self)
        inner = QVBoxLayout(self.tuning_box)
        inner.setContentsMargins(0, 0, 0, 0)
        inner.setSpacing(4)
        self.tuning_rows, self.tuning_flags = {}, {}
        for key, label, lo, hi, unit, scale in self.TUNING_SLIDERS:
            row = _slider(label, lo, hi, round(getattr(TUNING, key) * scale), unit,
                          lambda v, k=key, s=scale: setattr(TUNING, k, v / s), self.tuning_box, label_width=104)
            self.tuning_rows[key] = row
            inner.addWidget(row)
        for key, label in self.TUNING_TOGGLES:
            check = QCheckBox(label)
            check.setChecked(getattr(TUNING, key))
            check.toggled.connect(lambda on, k=key: setattr(TUNING, k, on))
            self.tuning_flags[key] = check
            inner.addWidget(check)
        line = QHBoxLayout()
        line.addWidget(_button("Valeurs d'origine", "Remet les réglages d'essai aux valeurs par défaut",
                               self._reset_tuning, self.tuning_box))
        line.addWidget(_button("Copier les valeurs", "Copie les valeurs dans le presse-papiers (à me coller)",
                               self._copy_tuning, self.tuning_box))
        inner.addLayout(line)
        journal = QHBoxLayout()
        self.log_toggle = QCheckBox("Journal du stylet")
        self.log_toggle.setToolTip("Enregistre ce que le stylet envoie (position, pression brute, cadence, source) "
                                   "et ce que le moteur en fait")
        self.log_toggle.toggled.connect(self._log_enabled)
        self.trace_toggle = QCheckBox("Points du trait")
        self.trace_toggle.setToolTip("Superpose, sur le dernier trait : points bruts (rouge), trajectoire filtrée (vert), "
                                     "centres des empreintes (bleu)")
        self.trace_toggle.toggled.connect(self._trace_enabled)
        journal.addWidget(self.trace_toggle)
        journal.addWidget(self.log_toggle)
        journal.addWidget(_button("Enregistrer", "Écrit le journal en JSON (dossier data/pen_logs) et affiche les statistiques",
                                  self.save_log, self.tuning_box))
        inner.addLayout(journal)
        box.addWidget(self.tuning_box)

    def _mode_chosen(self, index):
        b = self.session.brush
        b.smoothing_mode = self.smoothing_mode.itemData(index)
        if b.smoothing_mode != "none" and b.smoothing <= 0.0:
            b.smoothing = 0.3                           # un mode sans intensité ne changerait rien : intensité de départ
        self.sync()

    def _trace_enabled(self, on):
        self.canvas.debug_trace = on
        if not on:
            self.canvas._last_trace = None
        self.canvas.update()

    def _log_enabled(self, on):
        from .pen_log import PenLog
        self.canvas.pen_log = PenLog() if on else None

    def save_log(self):
        """Écrit le journal du stylet (JSON) et affiche les statistiques d'entrée (cadence, pression, double évènements)."""
        import os
        import time as _time
        log = self.canvas.pen_log
        if log is None or not log.events:
            self.canvas.message.emit("Journal du stylet vide : cochez « Journal du stylet », tracez, puis enregistrez.")
            return None
        folder = PEN_LOG_FOLDER
        os.makedirs(folder, exist_ok=True)
        path = os.path.join(folder, "stylet_" + _time.strftime("%Y%m%d_%H%M%S") + ".json")
        log.save(path)
        self.canvas.message.emit("Journal enregistré : " + path + " | " + log.summary())
        return path

    def _show_tuning(self):
        on = self.tuning_toggle.isChecked()
        self.tuning_box.setVisible(on)
        self.tuning_toggle.setText("Réglages d'essai ▾" if on else "Réglages d'essai ▸")

    def _sync_tuning(self):
        from .brush import TUNING
        for key, scale in ((k, s) for k, _l, _a, _b, _u, s in self.TUNING_SLIDERS):
            field = self.tuning_rows[key].field
            with QSignalBlocker(field):
                field.setValue(round(getattr(TUNING, key) * scale))
        for key, check in self.tuning_flags.items():
            with QSignalBlocker(check):
                check.setChecked(getattr(TUNING, key))

    def _reset_tuning(self):
        from .brush import TUNING
        TUNING.reset()
        self._sync_tuning()

    def _copy_tuning(self):
        from PySide6.QtGui import QGuiApplication
        from .brush import TUNING
        text = TUNING.as_text()
        QGuiApplication.clipboard().setText(text)
        self.canvas.message.emit("Valeurs copiées : " + text)

    # -- présélections (persistantes) --
    def _settings(self) -> dict:
        return self._settings_dict

    def _raw_presets(self):
        return self._settings().get("board_ps_brush_presets", [])

    def _store(self, raw):
        """Enregistre la liste : réglage de l'appli (fichier + preset actif) si l'appli l'a branché, sinon session."""
        from fm_board import ui as board_ui
        writer = board_ui.SETTING_WRITER
        if writer is not None:
            writer("board_ps_brush_presets", raw)
        settings = self._settings()
        if isinstance(settings, dict):
            settings["board_ps_brush_presets"] = raw

    def _fill_presets(self, select: str | None = None):
        from . import presets
        self.presets.blockSignals(True)
        self.presets.clear()
        for brush in presets.all_presets(self._raw_presets()):
            self.presets.addItem(brush.name, brush.to_dict())
        index = self.presets.findText(select) if select else -1
        self.presets.setCurrentIndex(max(0, index) if select else -1)
        self.presets.blockSignals(False)

    def _preset_chosen(self, index):
        from .brush import Brush
        data = self.presets.itemData(index)
        if data:
            keep = self.session.brush
            brush = Brush.from_dict(data)
            for key in ("size", "hardness", "opacity", "flow", "spacing", "smoothing", "smoothing_mode", "paint_mode", "airbrush",
                        "pressure_size", "pressure_flow", "pressure_opacity", "sigma"):
                setattr(keep, key, getattr(brush, key))
            self.sync()

    def save_preset(self, name: str | None = None):
        from . import presets
        if name is None:
            from PySide6.QtWidgets import QInputDialog
            name, ok = QInputDialog.getText(self, "Présélection de brosse", "Nom :")
            if not ok:
                return None
        try:
            raw = presets.with_saved(self._raw_presets(), self.session.brush, name)
        except ValueError as exc:
            self.canvas.message.emit(str(exc))
            return None
        self._store(raw)
        self._fill_presets(name.strip()[:40])
        return raw

    def delete_preset(self, name: str | None = None):
        from . import presets
        name = name or self.presets.currentText()
        if not name or name in {b.name for b in presets.FACTORY}:
            self.canvas.message.emit("Les présélections d'usine ne se retirent pas.")
            return None
        raw = presets.without(self._raw_presets(), name)
        self._store(raw)
        self._fill_presets()
        return raw

    def _set(self, key, value):
        setattr(self.session.brush, key, float(value))
        self.canvas.update()

    def swap(self):
        s = self.session
        s.fg, s.bg = s.bg, s.fg
        self.sync()

    def sync(self):
        b = self.session.brush
        for key, value in (("size", b.size), ("hardness", b.hardness * 100), ("opacity", b.opacity * 100),
                           ("flow", b.flow * 100), ("spacing", b.spacing * 100), ("smoothing", b.smoothing * 100),
                           ("sigma", b.sigma)):
            field = self.rows[key].field
            with QSignalBlocker(field):
                field.setValue(round(value))
        for box, value in ((self.pressure_size, b.pressure_size), (self.pressure_flow, b.pressure_flow),
                           (self.pressure_opacity, b.pressure_opacity)):
            with QSignalBlocker(box):
                box.setChecked(value)
        with QSignalBlocker(self.smoothing_mode):
            self.smoothing_mode.setCurrentIndex(self.smoothing_mode.findData(b.smoothing_kind()))
        with QSignalBlocker(self.airbrush):
            self.airbrush.setChecked(b.airbrush)
        with QSignalBlocker(self.paint_mode):
            self.paint_mode.setCurrentIndex(self.paint_mode.findData(b.paint_mode))
        self.fg.update()
        self.bg.update()
        self.canvas.update()


class _ReorderList(QListWidget):
    """Liste des calques : Ctrl + glisser une ligne la déplace (règle de l'appli : tout déplacement démarre avec Ctrl) ;
    sans Ctrl, clic et sélection habituels."""
    reordered = Signal(str, str)                    # (uid déplacé, uid de la ligne visée)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._source = None

    def mousePressEvent(self, event):
        item = self.itemAt(event.position().toPoint())
        if item is not None and event.button() == Qt.LeftButton and event.modifiers() & Qt.ControlModifier                 and not event.modifiers() & Qt.ShiftModifier:
            self._source = item.data(Qt.UserRole)
            self.setCursor(Qt.ClosedHandCursor)
            event.accept()
            return
        self._source = None
        super().mousePressEvent(event)

    def mouseReleaseEvent(self, event):
        if self._source is not None:
            target = self.itemAt(event.position().toPoint())
            source, self._source = self._source, None
            self.unsetCursor()
            if target is not None and target.data(Qt.UserRole) != source:
                self.reordered.emit(source, target.data(Qt.UserRole))
            event.accept()
            return
        super().mouseReleaseEvent(event)


class LayersPanel(QWidget):
    def __init__(self, session, canvas, parent=None):
        super().__init__(parent)
        self.session, self.canvas = session, canvas
        self._refresh_timer = QTimer(self)
        self._refresh_timer.setSingleShot(True)
        self._refresh_timer.timeout.connect(self.refresh)
        self._live = None                           # (calque, avant, libellé) : réglage au curseur en cours
        self._thumbs: dict = {}                     # uid -> (clé de version, QIcon) : miniatures refaites seulement si besoin
        self.thumb_builds = 0                       # (tests, mesures)
        self._thumb_timer = QTimer(self)
        self._thumb_timer.setSingleShot(True)
        self._thumb_timer.setInterval(300)
        self._thumb_timer.timeout.connect(self.refresh_icons)
        self._live_timer = QTimer(self)
        self._live_timer.setSingleShot(True)
        self._live_timer.setInterval(350)
        self._live_timer.timeout.connect(self.commit_live)
        box = QVBoxLayout(self)
        box.setContentsMargins(0, 0, 0, 0)
        box.setSpacing(4)
        box.addWidget(_title("Calques"))
        self.list = _ReorderList(self)
        self.list.reordered.connect(self.reorder)
        self.list.setIconSize(QSize(36, 36))
        self.list.setSelectionMode(QAbstractItemView.ExtendedSelection)      # Ctrl / Maj + clic : plusieurs calques
        self.list.itemSelectionChanged.connect(self._selection_changed)
        self.actions = canvas.actions
        self.list.setMinimumHeight(150)
        self.list.currentRowChanged.connect(self._row_changed)
        self.list.itemChanged.connect(self._item_changed)
        box.addWidget(self.list, 1)
        # Commandes des calques et des masques : éléments des barres flottantes « Calques » et « Masque »
        # (`bars.StandardPalettes`), pas de ce panneau.
        from .bars import text_button
        self.action_buttons = {key: text_button("layer_" + key, text, tip, slot) for key, text, tip, slot in (
            ("add", "Nouveau", "Nouveau calque", self.add), ("group", "Groupe", "Nouveau groupe (ou grouper la sélection)",
                                                             self.add_group),
            ("duplicate", "Dupliquer", "Dupliquer le calque", self.duplicate),
            ("remove", "Supprimer", "Supprimer le calque", self.remove),
            ("up", "Monter", "Monter le calque", lambda: self.move(1)),
            ("down", "Descendre", "Descendre le calque", lambda: self.move(-1)),
            ("merge", "Fusionner", "Fusionner avec le calque inférieur", self.merge),
            ("flatten", "Aplatir", "Aplatir l'image", self.flatten))}
        # Opacité, fusion et nom : éléments de la barre flottante « Calque » (`bars.StandardPalettes`), pas de ce panneau.
        from fm_theme.palette import PaletteInputBar, PaletteSelectBar, PaletteSliderBar
        opacity = PaletteSliderBar("layer_opacity", "Opacité", 0, 100, 100, "%")
        opacity.valueChanged.connect(self._opacity_changed)
        self.opacity = _Row(opacity)
        self.blend = PaletteSelectBar("layer_blend", "Fusion", [BLEND_LABELS[m] for m in BLEND_MODES], BLEND_LABELS["normal"])
        self.blend.valueChanged.connect(self._blend_chosen)
        self.name_edit = PaletteInputBar("layer_name", "Nom", "", "Nom du calque")
        self.name_edit.valueChanged.connect(self._renamed)
        line = QHBoxLayout()
        self.locked = QCheckBox("Verrouillé")
        self.locked.toggled.connect(lambda on: self._prop(locked=on, label="Verrouiller le calque"))
        self.clip = QCheckBox("Écrêtage")
        self.clip.setToolTip("Limiter le calque à l'opacité du calque situé dessous")
        self.clip.toggled.connect(lambda on: self._prop(clip=on, label="Masque d'écrêtage"))
        line.addWidget(self.locked)
        line.addWidget(self.clip)
        line.addStretch(1)
        box.addLayout(line)
        self.mask_buttons = {}
        for key, text, tip, slot in (("add", "Ajouter", "Ajouter un masque (révèle tout)", self.mask_add),
                                     ("toggle", "Activer", "Activer / désactiver le masque", self.mask_toggle),
                                     ("invert", "Inverser", "Inverser le masque", self.mask_invert),
                                     ("apply", "Appliquer", "Appliquer le masque aux pixels", self.mask_apply),
                                     ("remove", "Retirer", "Supprimer le masque", self.mask_remove)):
            self.mask_buttons[key] = text_button("mask_" + key, text, tip, slot)
        self.target_pixels = text_button("target_pixels", "Sur pixels", "Cible : les outils peignent les pixels du calque",
                                         lambda: self.set_target("pixels"))
        self.target_mask = text_button("target_mask", "Sur masque",
                                       "Cible : les outils peignent le masque (noir cache, blanc révèle)",
                                       lambda: self.set_target("mask"))
        self.target_mask.set_library_icon("modules/photoshop/masque_calque_03")
        session.listeners.append(self._on_session)
        self.refresh()

    def detach(self):
        if self._on_session in self.session.listeners:
            self.session.listeners.remove(self._on_session)

    def _on_session(self, kind, _rect):
        if kind in ("structure", "reload", "view") and self._live is None:     # (pas pendant un curseur tenu)
            self._refresh_timer.start(0)
        elif kind in ("committed", "edit"):
            self._thumb_timer.start()                                         # miniatures : après le geste, pas pendant

    # -- liste --
    def _flat(self):
        out = []

        def walk(items, depth):
            for layer in reversed(items):
                out.append((layer, depth))
                if layer.children:
                    walk(layer.children, depth + 1)
        walk(self.session.doc.layers, 0)
        return out

    def refresh(self):
        s = self.session
        active = s.layer()
        with QSignalBlocker(self.list):
            self.list.clear()
            row_active = 0
            for row, (layer, depth) in enumerate(self._flat()):
                label = ("    " * depth) + ("▸ " if layer.is_group() else "◐ " if layer.is_adjustment() else "") + layer.name + \
                        ("  [masque]" if layer.mask is not None else "") + ("  ⛓" if layer.clip else "") + \
                        ("  🔒" if layer.locked else "")
                item = QListWidgetItem(label)
                item.setFlags(item.flags() | Qt.ItemIsUserCheckable)
                item.setCheckState(Qt.Checked if layer.visible else Qt.Unchecked)
                item.setData(Qt.UserRole, layer.uid)
                item.setIcon(self._thumb(layer))
                self.list.addItem(item)
                if layer is active:
                    row_active = row
            self.list.setCurrentRow(row_active)
            if len(s.multi) > 1:
                for row in range(self.list.count()):
                    if self.list.item(row).data(Qt.UserRole) in s.multi:
                        self.list.item(row).setSelected(True)
        self._sync_props(active)

    # -- miniatures --
    SIZE = 36

    def _version_key(self, layer):
        if layer.pix is None:
            return ("g", tuple(self._version_key(c) for c in layer.children), repr(layer.adjustment))
        return (layer.pix.rev, layer.pix.x, layer.pix.y, layer.mask.plane.rev if layer.mask is not None else -1,
                layer.source is not None)

    def _thumb(self, layer) -> QIcon:
        key = self._version_key(layer)
        cached = self._thumbs.get(layer.uid)
        if cached is not None and cached[0] == key:
            return cached[1]
        self.thumb_builds += 1
        size = self.SIZE
        image = QImage(size, size, QImage.Format_ARGB32_Premultiplied)
        painter = QPainter(image)
        for y in range(0, size, 6):
            for x in range(0, size, 6):
                painter.fillRect(x, y, 6, 6, QColor("#ffffff" if (x // 6 + y // 6) % 2 == 0 else "#c8c8c8"))
        if layer.pix is None:
            painter.setPen(QColor("#303030"))
            painter.drawText(image.rect(), Qt.AlignCenter, "◐" if layer.is_adjustment() else "▸▸")
        elif layer.pix.data is not None:
            import numpy as np
            from PIL import Image
            data = layer.pix.data
            h, w = data.shape[:2]
            scale = min(size / w, size / h)
            tw, th = max(1, round(w * scale)), max(1, round(h * scale))
            step_y, step_x = max(1, h // (th * 3)), max(1, w // (tw * 3))              # pré-réduction : jamais le plan entier
            small = Image.fromarray(np.ascontiguousarray(data[::step_y, ::step_x]), "RGBA").resize((tw, th), Image.BILINEAR)
            raw = np.ascontiguousarray(np.asarray(small))
            piece = QImage(raw.data, tw, th, tw * 4, QImage.Format_RGBA8888)
            painter.drawImage((size - tw) // 2, (size - th) // 2, piece)
        painter.end()
        icon = QIcon(QPixmap.fromImage(image))
        self._thumbs[layer.uid] = (key, icon)
        return icon

    def refresh_icons(self):
        """Miniatures des calques modifiés seulement (clé de version = révisions des plans)."""
        for row in range(self.list.count()):
            item = self.list.item(row)
            layer = self.session.doc.find(item.data(Qt.UserRole))
            if layer is not None:
                item.setIcon(self._thumb(layer))
        live = {l.uid for l in self.session.doc.walk()}
        for uid in [u for u in self._thumbs if u not in live]:
            del self._thumbs[uid]

    def _sync_props(self, layer):
        field = self.opacity.field
        with QSignalBlocker(field):
            field.setValue(round(layer.opacity * 100))
        self.blend.field.setValue(BLEND_LABELS.get(layer.blend, BLEND_LABELS["normal"]))
        with QSignalBlocker(self.name_edit.field):
            self.name_edit.field.setText(layer.name)
        with QSignalBlocker(self.locked):
            self.locked.setChecked(layer.locked)
        with QSignalBlocker(self.clip):
            self.clip.setChecked(layer.clip)
        has = layer.mask is not None
        for key in ("toggle", "invert", "apply", "remove"):
            self.mask_buttons[key].setEnabled(has)
        self.mask_buttons["add"].setEnabled(not has and not layer.is_group())
        self.mask_buttons["toggle"].set_text("Désactiver" if has and layer.mask.enabled else "Activer")
        self.target_mask.setEnabled(has)
        self.target_pixels.set_active(self.session.target == "pixels")
        self.target_mask.set_active(self.session.target == "mask")

    def _row_changed(self, row):
        flat = self._flat()
        if 0 <= row < len(flat):
            chosen = [i.data(Qt.UserRole) for i in self.list.selectedItems()]
            layer = flat[row][0]
            if len(chosen) > 1 and layer.uid in chosen:
                self.session.active_uid = layer.uid                 # sélection multiple : le courant est actif
            else:
                self.session.select_layer(layer)
            self._sync_props(layer)

    def _selection_changed(self):
        chosen = [i.data(Qt.UserRole) for i in self.list.selectedItems()]
        if len(chosen) > 1:
            order = [l.uid for l, _d in reversed(self._flat())]
            self.session.multi = sorted(chosen, key=order.index)

    def _item_changed(self, item):
        layer = self.session.doc.find(item.data(Qt.UserRole))
        visible = item.checkState() == Qt.Checked
        if layer is not None and layer.visible != visible:
            self.session.do(ops.set_props(layer, "Afficher / masquer le calque", visible=visible))

    # -- actions --
    def _run(self, action):
        try:
            result = action()
        except ValueError as exc:
            self.canvas.message.emit(str(exc))
            return None
        return result

    def _insert_index(self):
        layer = self.session.layer()
        siblings, at = self.session.doc.parent_list(layer)
        return siblings, at

    def add(self):
        s = self.session
        siblings, at = self._insert_index()
        parent = s.doc.parent_of(s.layer())
        layer, cmd = ops.add_layer(s.doc, "Calque", parent=parent, index=at + 1)
        s.do(cmd)
        s.select_layer(layer)

    def add_group(self):
        s = self.session
        if len(s.selected_layers()) > 1:
            self.actions.group_selected()                          # plusieurs calques choisis : on les groupe
            return
        _siblings, at = self._insert_index()
        group, cmd = ops.add_layer(s.doc, "Groupe", parent=s.doc.parent_of(s.layer()), index=at + 1, kind="group")
        s.do(cmd)
        s.select_layer(group)

    def duplicate(self):
        if len(self.session.selected_layers()) > 1:
            self.actions.duplicate_selected()
            return
        twin, cmd = ops.duplicate_layer(self.session.doc, self.session.layer())
        self.session.do(cmd)
        self.session.select_layer(twin)

    def remove(self):
        s = self.session
        if len(s.selected_layers()) > 1:
            self.actions.remove_selected()
            return
        layer = s.layer()
        siblings, at = s.doc.parent_list(layer)
        cmd = self._run(lambda: ops.remove_layer(s.doc, layer))
        if cmd is not None:
            s.do(cmd)
            s.active_uid = (siblings[max(0, at - 1)].uid if siblings else s.doc.layers[-1].uid)
            s.select_layer(s.layer())

    def reorder(self, uid: str, target_uid: str):
        """Ctrl + glisser dans la liste : le calque prend la place du calque visé (même parent que lui)."""
        s = self.session
        layer, target = s.doc.find(uid), s.doc.find(target_uid)
        if layer is None or target is None:
            return None
        parent = s.doc.parent_of(target)
        siblings, at = s.doc.parent_list(target)
        try:
            command = ops.move_layer(s.doc, layer, parent, at)
        except ValueError as exc:
            self.canvas.message.emit(str(exc))
            return None
        s.do(command)
        s.select_layer(layer)
        return command

    def move(self, direction: int):
        s = self.session
        layer = s.layer()
        siblings, at = s.doc.parent_list(layer)
        target = at + direction
        if 0 <= target < len(siblings):
            s.do(ops.move_layer(s.doc, layer, s.doc.parent_of(layer), target))

    def merge(self):
        s = self.session
        cmd = self._run(lambda: ops.merge_down(s.doc, s.layer()))
        if cmd is not None:
            s.do(cmd)
            s.select_layer(s.layer())

    def flatten(self):
        s = self.session
        layer, cmd = ops.flatten(s.doc)
        s.do(cmd)
        s.select_layer(layer)

    # -- réglages du calque --
    def _prop(self, label="Propriétés du calque", **changes):
        layer = self.session.layer()
        if any(getattr(layer, k) != v for k, v in changes.items()):
            self.session.do(ops.set_props(layer, label, **changes))

    def _blend_chosen(self, label):
        mode = next((m for m in BLEND_MODES if BLEND_LABELS[m] == label), None)
        if mode:
            self._prop("Mode de fusion", blend=mode)

    def _renamed(self, text):
        name = (text or "").strip()
        if name:
            self._prop("Renommer le calque", name=name)
        else:
            self.name_edit.field.setText(self.session.layer().name)             # un nom vide est refusé : l'ancien revient

    def _opacity_changed(self, value):
        """Curseur d'opacité : appliqué à chaque cran, UNE étape d'annulation (350 ms après le dernier)."""
        s = self.session
        layer = s.layer()
        if self._live is None or self._live[0] is not layer:
            self.commit_live()
            self._live = (layer, layer.opacity)
        layer.opacity = value / 100.0
        from . import render
        s.notify("props" if render.cache_for(s).begin_pivot(layer) else "structure", None)
        self._live_timer.start()

    def commit_live(self):
        live, self._live = self._live, None
        self._live_timer.stop()
        from . import render
        render.cache_for(self.session).end_pivot()
        if live is None:
            return
        layer, before = live
        after = layer.opacity
        if before != after:
            def apply(value, layer=layer):
                layer.opacity = value
            self.session.do(CallCommand("Opacité du calque", lambda: apply(after), lambda: apply(before)),
                            notified=True)

    # -- masques --
    def mask_add(self):
        s = self.session
        cmd = self._run(lambda: ops.add_mask(s.layer()))
        if cmd is not None:
            s.do(cmd)

    def mask_toggle(self):
        layer = self.session.layer()
        if layer.mask is not None:
            self.session.do(ops.toggle_mask(layer, not layer.mask.enabled))

    def mask_invert(self):
        s = self.session
        if s.layer().mask is not None:
            s.do(ops.invert_mask(s.layer(), s.doc.rect()))

    def mask_apply(self):
        s = self.session
        cmd = self._run(lambda: ops.apply_mask(s.layer(), s.doc.rect()))
        if cmd is not None:
            s.target = "pixels"
            s.do(cmd)

    def mask_remove(self):
        s = self.session
        cmd = self._run(lambda: ops.remove_mask(s.layer()))
        if cmd is not None:
            s.target = "pixels"
            s.do(cmd)

    def set_target(self, target):
        s = self.session
        if target == "mask" and s.layer().mask is None:
            self.canvas.message.emit("Ce calque n'a pas de masque.")
            target = "pixels"
        s.target = target
        s.notify("view", None)
