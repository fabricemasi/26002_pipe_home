"""Champs de la fenetre de reglages v2 propres a Pipeline Browser (sections reprises de la v1 :
Application, Polices principales, Couleurs, ICONES). Le moteur de la v2 (settings_window_v2,
settings_cells...) n'en depend que par ses fabriques de champs : en copiant la fenetre de
reglages dans une autre appli, ce module et les lignes du CATALOG qui l'utilisent sont a retirer.
Les icones et logiciels touchent au cache de l'appli : imports tardifs (previews, browser_core),
comme dans la v1."""
from __future__ import annotations

from PySide6.QtCore import QTimer, Qt, Signal
from PySide6.QtGui import QFont, QPixmap
from PySide6.QtWidgets import (
    QApplication, QFileDialog, QHBoxLayout, QInputDialog, QLabel, QLineEdit, QMessageBox, QVBoxLayout, QWidget,
)

import config as _config
from app_style import SMOOTHING_CHOICES, SMOOTHING_LABELS_SHORT, auto_family_for_role
from settings_colorpicker import _ColorField

from settings_sections import _SMOOTHING_STEPS, _font_choices
from settings_store import M
from settings_theme import _input_radius, _register_input, _set_text_role
from settings_widgets import _Btn, _FontSelectField, _SteppedSliderField, _qfont


def _button(text: str) -> _Btn:
    return _Btn(text, M["btn_bg"], M["btn_border"], M["btn_fg"], M["btn_hover"], height=25)


def _row() -> tuple[QWidget, QHBoxLayout]:
    box = QWidget()
    box.setStyleSheet("background: transparent;")
    layout = QHBoxLayout(box)
    layout.setContentsMargins(0, 0, 0, 0)
    layout.setSpacing(8)
    return box, layout


class RootPathField(QWidget):
    """Racine par defaut : chemin (police a chasse fixe) + « Parcourir »."""

    changed = Signal()

    def __init__(self, path: str):
        super().__init__()
        self.setStyleSheet("background: transparent;")
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(6)
        self.edit = QLineEdit(path)
        self.edit.setFont(_qfont(12, 400, mono=True))
        self.edit.setFixedSize(268, 25)
        self._radius = _input_radius()
        _register_input(self)
        self._restyle()
        self.edit.textChanged.connect(lambda _t: self.changed.emit())
        browse = _button("Parcourir")
        browse.setFixedWidth(84)
        browse.clicked.connect(self._browse)
        layout.addWidget(self.edit)
        layout.addWidget(browse)
        layout.addStretch(1)

    def setRadius(self, radius: int):           # suit Geometrie > Zones de saisie
        self._radius = radius
        self._restyle()

    def _restyle(self):
        self.edit.setStyleSheet(
            f"QLineEdit {{ background: {M['field_bg']}; border: 1px solid {M['field_border']}; "
            f"border-radius: {self._radius}px; color: {M['value_fg']}; padding: 0 6px; }}")

    def _browse(self):
        chosen = QFileDialog.getExistingDirectory(self, "Racine du pipeline", self.edit.text())
        if chosen:
            self.edit.setText(chosen)

    def text(self) -> str:
        return self.edit.text()


class FontRoleField(QWidget):
    """Une ligne de Polices principales : police, lissage (3 crans) et apercu dans cette police.
    Choisir une police marque le role « personnalise » (sans quoi app_style.role_font l'ignore)."""

    changed = Signal()

    def __init__(self, conf: dict, style_role: str, sample: str):
        super().__init__()
        self.conf = dict(conf)
        self.custom = bool(conf.get("custom", False))
        self.auto = auto_family_for_role(style_role)
        family = conf.get("family") or "Systeme"
        self.family = _FontSelectField(_font_choices(), family, width=162, auto_label=self.auto)
        smoothing = conf.get("smoothing") or "current"
        if smoothing not in SMOOTHING_CHOICES:
            smoothing = "current"
        self.smoothing = _SteppedSliderField([SMOOTHING_LABELS_SHORT[k] for k in _SMOOTHING_STEPS],
                                             _SMOOTHING_STEPS.index(smoothing), slider_width=20, box_width=90)
        self.preview = QLabel(sample)
        self.preview.setStyleSheet(f"color: {M['value_muted']}; background: transparent;")
        self._show(family)
        self.family.changed.connect(self._on_pick)
        self.smoothing.changed.connect(lambda _s: self.changed.emit())

    def _show(self, family: str):
        self.preview.setFont(QFont(family if family != "Systeme" else self.auto, 10))

    def _on_pick(self, family: str):
        self.custom = True
        self._show(family)
        self.changed.emit()

    def value(self) -> dict:
        family = self.family.value()
        out = dict(self.conf)
        out.update({"family": "" if family == "Systeme" else family,
                    "smoothing": _SMOOTHING_STEPS[self.smoothing.value()], "custom": self.custom})
        return out


class SemanticColorField(QWidget):
    """Pastille d'une couleur de la palette (Couleurs) + sa valeur hexadecimale."""

    changed = Signal()

    def __init__(self, value: str, title: str):
        super().__init__()
        self.setStyleSheet("background: transparent;")
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(10)
        self.field = _ColorField(value, swatch_size=24, title=title)
        self.hex = QLabel(value)
        _set_text_role(self.hex, "table_head_mono")
        layout.addWidget(self.field)
        layout.addWidget(self.hex)
        layout.addStretch(1)
        self.field.changed.connect(self._on_changed)

    def _on_changed(self, value: str):
        self.hex.setText(value)
        self.changed.emit()

    def value(self) -> str:
        return self.field.value()

    def setValue(self, value: str):
        if value != self.field.value():
            self.field.setValue(value)
            self.hex.setText(value)


# -- ICONES -------------------------------------------------------------------------------------

def _save_icon(parent: QWidget, key: str, pix: QPixmap) -> bool:
    """Enregistre `pix` comme icone perso de `key` (dossier de config cache, PNG reduit)."""
    import previews as pb_previews

    if pix.isNull():
        return False
    top = _config.CUSTOM_SOFTWARE_ICON_MAX_DIM
    if max(pix.width(), pix.height()) > top:
        pix = pix.scaled(top, top, Qt.KeepAspectRatio, Qt.SmoothTransformation)
    dest = pb_previews.custom_software_icon_path(key)
    pb_previews.forget_mtime(dest)
    try:
        was_new = not dest.parent.is_dir()
        dest.parent.mkdir(parents=True, exist_ok=True)
        if was_new:
            pb_previews._set_hidden(dest.parent)
    except OSError as exc:
        QMessageBox.warning(parent, "Icone", f"Impossible de creer le dossier de configuration :\n{exc}")
        return False
    if not pix.save(str(dest), "PNG"):
        QMessageBox.warning(parent, "Icone", "Impossible d'enregistrer l'icone.")
        return False
    pb_previews._set_hidden(dest)
    return True


def _pick_image(parent: QWidget) -> QPixmap | None:
    chosen, _ = QFileDialog.getOpenFileName(parent, "Choisir une image", "",
                                            "Images (*.png *.jpg *.jpeg *.bmp *.webp *.gif *.tif *.tiff)")
    if not chosen:
        return None
    pix = QPixmap(chosen)
    if pix.isNull():
        QMessageBox.warning(parent, "Icone", "Impossible de charger cette image.")
        return None
    return pix


def _capture(parent: QWidget, on_pixmap):
    """Capture d'une zone d'ecran (fenetre de reglages masquee le temps de la capture)."""
    import browser_core as pb_core

    window = parent.window()
    was_visible = window.isVisible()
    if was_visible:
        window.hide()
    QApplication.processEvents()

    def start():
        capture = pb_core.MultiScreenCapture()
        parent._capture_overlay = capture        # garde la capture en vie

        def finish():
            if was_visible:
                window.show()
            parent._capture_overlay = None

        def captured(pix: QPixmap):
            finish()
            on_pixmap(pix)

        capture.captured.connect(captured)
        capture.cancelled.connect(finish)

    QTimer.singleShot(150, start)


def _avatar() -> QLabel:
    avatar = QLabel()
    avatar.setFixedSize(24, 24)
    avatar.setStyleSheet("background: transparent;")
    return avatar


class UiIconField(QWidget):
    """ICONES > General : une icone d'interface (dossier, fichier, engrenage...) ou la punaise (deux
    etats sur la meme ligne). Changer / capturer / reinitialiser agit tout de suite sur le fichier
    d'icone perso, comme dans la v1 (aucun reglage enregistre)."""

    def __init__(self, ui_key: str):
        super().__init__()
        import previews as pb_previews

        self.setStyleSheet("background: transparent;")
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(24)
        if ui_key == "pin":
            states = ((pb_previews.UI_ICON_PIN_INACTIVE, "Non attachee"), (pb_previews.UI_ICON_PIN_ACTIVE, "Attachee"))
            short = True
        else:
            # Suffixe (« folder_default »...) -> cle d'icone de l'appli (previews.UI_ICON_*).
            states = ((getattr(pb_previews, f"UI_ICON_{ui_key.upper()}", ui_key), ""),)
            short = False
        for key, caption in states:
            group, group_l = _row()
            if caption:
                label = QLabel(caption)
                _set_text_role(label, "note")
                group_l.addWidget(label)
            avatar = _avatar()
            self._show(avatar, key)
            group_l.addWidget(avatar)
            for text, action in ((("Changer..." if short else "Changer l'icone..."), self._change),
                                 (("Capturer..." if short else "Capturer une zone d'ecran..."), self._capture),
                                 (("Reinit." if short else "Reinitialiser"), self._reset)):
                button = _button(text)
                button.clicked.connect(lambda _c=False, k=key, av=avatar, act=action: act(k, av))
                group_l.addWidget(button)
            layout.addWidget(group)
        layout.addStretch(1)

    @staticmethod
    def _show(avatar: QLabel, key: str):
        import browser_core as pb_core
        import previews as pb_previews

        if key == pb_previews.UI_ICON_PIN_INACTIVE:
            avatar.setPixmap(pb_core._pin_icon_pixmap(False, 24))
        elif key == pb_previews.UI_ICON_PIN_ACTIVE:
            avatar.setPixmap(pb_core._pin_icon_pixmap(True, 24))
        else:
            pix = pb_previews.custom_ui_icon_pixmap(key, 24)
            avatar.setPixmap(pix if pix is not None else QPixmap())

    def _change(self, key: str, avatar: QLabel):
        pix = _pick_image(self)
        if pix is not None and _save_icon(self, key, pix):
            self._show(avatar, key)

    def _capture(self, key: str, avatar: QLabel):
        _capture(self, lambda pix: _save_icon(self, key, pix) and self._show(avatar, key))

    def _reset(self, key: str, avatar: QLabel):
        import previews as pb_previews

        path = pb_previews.custom_software_icon_path(key)
        try:
            path.unlink(missing_ok=True)
        except OSError:
            pass
        pb_previews.forget_mtime(path)
        self._show(avatar, key)


class LogicielsField(QWidget):
    """ICONES > Logiciels : logiciels reconnus (+ ceux ajoutes), une ligne chacun (icone, nom,
    changer / capturer l'icone, supprimer), et « Ajouter un logiciel... ». Valeurs : les logiciels
    ajoutes (`custom_softwares`) et ceux d'origine retires (`removed_softwares`)."""

    changed = Signal()

    def __init__(self, custom: list, removed: list):
        super().__init__()
        self.custom = [dict(e) for e in (custom or [])]
        self.removed = set(removed or [])
        self.setStyleSheet("background: transparent;")
        self._layout = QVBoxLayout(self)
        self._layout.setContentsMargins(0, 0, 0, 0)
        self._layout.setSpacing(4)
        self._rebuild()

    def _keys(self) -> list:
        import previews as pb_previews

        return ([k for k in sorted(pb_previews.SOFTWARE_ICONS) if k not in self.removed]
                + [e["key"] for e in self.custom if e["key"] not in pb_previews.SOFTWARE_ICONS])

    def _rebuild(self):
        import browser_core as pb_core
        import previews as pb_previews

        while self._layout.count():
            item = self._layout.takeAt(0)
            if item.widget() is not None:
                item.widget().hide()
                item.widget().deleteLater()
        labels = {e["key"]: e["label"] for e in self.custom}
        for key in self._keys():
            line, line_l = _row()
            avatar = _avatar()
            avatar.setPixmap(pb_core.software_icon_pixmap(key, 24))
            name = QLabel(labels.get(key, key))
            _set_text_role(name, "value")
            name.setFixedWidth(150)
            line_l.addWidget(avatar)
            line_l.addWidget(name)
            for text, action in (("Changer l'icone...", self._change), ("Capturer une zone d'ecran...", self._capture)):
                button = _button(text)
                button.clicked.connect(lambda _c=False, k=key, av=avatar, act=action: act(k, av))
                line_l.addWidget(button)
            delete = _button("Supprimer")
            delete.clicked.connect(
                lambda _c=False, k=key, c=key not in pb_previews.SOFTWARE_ICONS: self._delete(k, c))
            line_l.addWidget(delete)
            line_l.addStretch(1)
            self._layout.addWidget(line)
        add = _Btn("+  Ajouter un logiciel...", "transparent", "", M["value_fg"], M["btn_hover"],
                   height=28, weight=500, padding="0 12px", align_left=True)
        add.clicked.connect(self._add)
        add_line, add_l = _row()
        add_l.addWidget(add)
        add_l.addStretch(1)
        self._layout.addWidget(add_line)
        self.updateGeometry()

    def _change(self, key: str, avatar: QLabel):
        pix = _pick_image(self)
        if pix is not None and _save_icon(self, key, pix):
            self._refresh(avatar, key)

    def _capture(self, key: str, avatar: QLabel):
        _capture(self, lambda pix: _save_icon(self, key, pix) and self._refresh(avatar, key))

    @staticmethod
    def _refresh(avatar: QLabel, key: str):
        import browser_core as pb_core

        avatar.setPixmap(pb_core.software_icon_pixmap(key, 24))

    def _add(self):
        import previews as pb_previews

        name, ok = QInputDialog.getText(self, "Ajouter un logiciel", "Nom du logiciel :")
        name = name.strip() if ok else ""
        if not name:
            return
        key = "".join(ch for ch in name.upper() if ch.isalnum())
        if not key:
            QMessageBox.warning(self, "Logiciel", "Ce nom ne contient aucun caractere valide.")
            return
        if key in self.removed:
            self.removed.discard(key)
        elif key in pb_previews.SOFTWARE_ICONS or any(e["key"] == key for e in self.custom):
            QMessageBox.warning(self, "Logiciel", f"« {name} » est deja dans la liste.")
            return
        else:
            self.custom.append({"key": key, "label": name})
        self._rebuild()
        self.changed.emit()

    def _delete(self, key: str, is_custom: bool):
        label = next((e["label"] for e in self.custom if e["key"] == key), key) if is_custom else key
        if QMessageBox.question(self, "Supprimer", f"Retirer « {label} » de la liste des logiciels ?",
                                QMessageBox.Yes | QMessageBox.No, QMessageBox.No) != QMessageBox.Yes:
            return
        if is_custom:
            self.custom = [e for e in self.custom if e["key"] != key]
        else:
            self.removed.add(key)
        self._rebuild()
        self.changed.emit()

    def values(self) -> dict:
        return {"custom_softwares": [dict(e) for e in self.custom], "removed_softwares": sorted(self.removed)}
