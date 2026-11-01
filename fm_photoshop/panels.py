"""Panneaux de l'éditeur Standard (Qt) : calques (liste, réglages, masques) et brosse (taille, dureté, couleurs).

Briques du Board et des réglages (`_slider`, `_TextButton`, `_ColorPickerPopup`, rôles de texte) : aucun style inventé.
Réglage d'un curseur (opacité…) : appliqué en direct, UNE seule étape d'annulation à la fin du geste."""
from __future__ import annotations

from PySide6.QtCore import QSignalBlocker, QSize, Qt, QTimer
from PySide6.QtGui import QColor, QIcon, QImage, QPainter, QPen, QPixmap
from PySide6.QtWidgets import (QAbstractItemView, QCheckBox, QComboBox, QGridLayout, QHBoxLayout, QLabel, QListWidget,
                               QListWidgetItem, QPushButton, QVBoxLayout, QWidget)

from . import ops
from .brush import Brush
from .history import CallCommand
from .model import BLEND_LABELS, BLEND_MODES


def _title(text: str) -> QLabel:
    from settings_theme import _text_label
    return _text_label(text, "card_title")


def _button(text: str, tip: str, slot, parent=None, checkable=False) -> QPushButton:
    from fm_board.ui import _TextButton
    button = _TextButton(text, tip, parent)
    button.setCheckable(checkable)
    button.clicked.connect(lambda _c=False: slot())
    return button


def _slider(label: str, minimum, maximum, value, unit, on_change, parent=None):
    from fm_board.ui import _slider as make
    box = QWidget(parent)
    row = QHBoxLayout(box)
    row.setContentsMargins(0, 0, 0, 0)
    row.setSpacing(6)
    text = QLabel(label)
    text.setFixedWidth(64)
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
        from settings_widgets import _ColorPickerPopup
        r, g, b = self.getter()
        popup = _ColorPickerPopup("#%02x%02x%02x" % (r, g, b), self.label, self.window())
        popup.colorChanged.connect(self._set)
        popup.committed.connect(self._set)
        popup.show_near(self)
        self._popup = popup

    def _set(self, color):
        c = QColor(color)
        self.setter((c.red(), c.green(), c.blue()))
        self.update()


class BrushPanel(QWidget):
    """Brosse : taille, dureté, opacité, débit, espacement, lissage ; pression ; couleurs ; présélections."""

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
            row = _slider(label, lo, hi, round(value), unit, lambda v, k=key, s=scale: self._set(k, v / s), self)
            self.rows[key] = row
            box.addWidget(row)
        flags = QHBoxLayout()
        self.pressure_size = QCheckBox("Pression : taille")
        self.pressure_flow = QCheckBox("Pression : débit")
        self.pressure_size.setChecked(b.pressure_size)
        self.pressure_flow.setChecked(b.pressure_flow)
        self.pressure_size.toggled.connect(lambda on: setattr(session.brush, "pressure_size", on))
        self.pressure_flow.toggled.connect(lambda on: setattr(session.brush, "pressure_flow", on))
        flags.addWidget(self.pressure_size)
        flags.addWidget(self.pressure_flow)
        box.addLayout(flags)
        colors = QHBoxLayout()
        self.fg = Swatch(lambda: session.fg, lambda c: setattr(session, "fg", c), "Couleur de premier plan", self)
        self.bg = Swatch(lambda: session.bg, lambda c: setattr(session, "bg", c), "Couleur d'arrière-plan", self)
        colors.addWidget(self.fg)
        colors.addWidget(self.bg)
        colors.addWidget(_button("⇄", "Permuter les couleurs (X)", self.swap, self))
        colors.addStretch(1)
        box.addLayout(colors)
        canvas.colorsChanged.connect(self.sync)
        self._fill_presets()

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
            for key in ("size", "hardness", "opacity", "flow", "spacing", "smoothing", "pressure_size",
                        "pressure_flow", "sigma"):
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
        self.fg.update()
        self.bg.update()
        self.canvas.update()


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
        self.list = QListWidget(self)
        self.list.setIconSize(QSize(36, 36))
        self.list.setSelectionMode(QAbstractItemView.SingleSelection)
        self.list.setMinimumHeight(150)
        self.list.currentRowChanged.connect(self._row_changed)
        self.list.itemChanged.connect(self._item_changed)
        box.addWidget(self.list, 1)
        for actions in ((("Nouveau", "Nouveau calque", self.add), ("Groupe", "Nouveau groupe", self.add_group),
                         ("Dupliquer", "Dupliquer le calque", self.duplicate),
                         ("Supprimer", "Supprimer le calque", self.remove)),
                        (("Monter", "Monter le calque", lambda: self.move(1)),
                         ("Descendre", "Descendre le calque", lambda: self.move(-1)),
                         ("Fusionner", "Fusionner avec le calque inférieur", self.merge),
                         ("Aplatir", "Aplatir l'image", self.flatten))):
            row = QHBoxLayout()
            row.setSpacing(2)
            for text, tip, slot in actions:
                row.addWidget(_button(text, tip, slot, self))
            box.addLayout(row)
        self.opacity = _slider("Opacité", 0, 100, 100, "%", self._opacity_changed, self)
        box.addWidget(self.opacity)
        line = QHBoxLayout()
        self.blend = QComboBox(self)
        for mode in BLEND_MODES:
            self.blend.addItem(BLEND_LABELS[mode], mode)
        self.blend.currentIndexChanged.connect(self._blend_changed)
        self.locked = QCheckBox("Verrouillé")
        self.locked.toggled.connect(lambda on: self._prop(locked=on, label="Verrouiller le calque"))
        self.clip = QCheckBox("Écrêtage")
        self.clip.setToolTip("Limiter le calque à l'opacité du calque situé dessous")
        self.clip.toggled.connect(lambda on: self._prop(clip=on, label="Masque d'écrêtage"))
        line.addWidget(self.blend, 1)
        line.addWidget(self.locked)
        line.addWidget(self.clip)
        box.addLayout(line)
        box.addWidget(_title("Masque"))
        masks = QHBoxLayout()
        masks.setSpacing(2)
        self.mask_buttons = {}
        for key, text, tip, slot in (("add", "Ajouter", "Ajouter un masque (révèle tout)", self.mask_add),
                                     ("toggle", "Activer", "Activer / désactiver le masque", self.mask_toggle),
                                     ("invert", "Inverser", "Inverser le masque", self.mask_invert),
                                     ("apply", "Appliquer", "Appliquer le masque aux pixels", self.mask_apply),
                                     ("remove", "Retirer", "Supprimer le masque", self.mask_remove)):
            self.mask_buttons[key] = _button(text, tip, slot, self)
            masks.addWidget(self.mask_buttons[key])
        box.addLayout(masks)
        target = QHBoxLayout()
        self.target_pixels = _button("Cible : pixels", "Les outils peignent les pixels du calque", lambda: self.set_target("pixels"), self, True)
        self.target_mask = _button("Cible : masque", "Les outils peignent le masque (noir cache, blanc révèle)", lambda: self.set_target("mask"), self, True)
        target.addWidget(self.target_pixels)
        target.addWidget(self.target_mask)
        box.addLayout(target)
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
        with QSignalBlocker(self.blend):
            self.blend.setCurrentIndex(self.blend.findData(layer.blend))
        with QSignalBlocker(self.locked):
            self.locked.setChecked(layer.locked)
        with QSignalBlocker(self.clip):
            self.clip.setChecked(layer.clip)
        has = layer.mask is not None
        for key in ("toggle", "invert", "apply", "remove"):
            self.mask_buttons[key].setEnabled(has)
        self.mask_buttons["add"].setEnabled(not has and not layer.is_group())
        self.mask_buttons["toggle"].setText("Désactiver" if has and layer.mask.enabled else "Activer")
        self.target_mask.setEnabled(has)
        self.target_pixels.setChecked(self.session.target == "pixels")
        self.target_mask.setChecked(self.session.target == "mask")
        self.blend.setEnabled(not layer.is_group() or True)

    def _row_changed(self, row):
        flat = self._flat()
        if 0 <= row < len(flat):
            self.session.select_layer(flat[row][0])
            self._sync_props(flat[row][0])

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
        _siblings, at = self._insert_index()
        group, cmd = ops.add_layer(s.doc, "Groupe", parent=s.doc.parent_of(s.layer()), index=at + 1, kind="group")
        s.do(cmd)
        s.select_layer(group)

    def duplicate(self):
        twin, cmd = ops.duplicate_layer(self.session.doc, self.session.layer())
        self.session.do(cmd)
        self.session.select_layer(twin)

    def remove(self):
        s = self.session
        layer = s.layer()
        siblings, at = s.doc.parent_list(layer)
        cmd = self._run(lambda: ops.remove_layer(s.doc, layer))
        if cmd is not None:
            s.do(cmd)
            s.active_uid = (siblings[max(0, at - 1)].uid if siblings else s.doc.layers[-1].uid)
            s.select_layer(s.layer())

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

    def _blend_changed(self, _index):
        mode = self.blend.currentData()
        if mode:
            self._prop("Mode de fusion", blend=mode)

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
