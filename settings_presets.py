"""Presets : choix dans la fenetre principale (menu deroulant + bouton « Gerer les presets… ») et fenetre de
gestion (liste de tous les presets : nouveau, dupliquer, renommer, supprimer, preset par defaut).

Couche reglages : ne depend d'aucun code propre a l'appli. Donnees et regles dans settings_store
(`apply_preset`, `save_preset`, `duplicate_preset`, `rename_preset`, `delete_preset`,
`set_default_preset`, `preset_in_use`) ; c'est l'appelant qui applique les reglages a l'ecran (signal
`presetChosen` / `presetsChanged`). Habillage = briques de la fenetre de reglages v2 (`_SelectField`,
`_Btn`, `_TextField`, `_Toggle`, `build_cells_table`, `_PanelFrame`, `_SettingsTitleBar`)."""
from __future__ import annotations

from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtWidgets import QDialog, QHBoxLayout, QLabel, QVBoxLayout, QWidget

import settings_store as store
import settings_window_v2 as v2
from app_style import apply_dwm_frame
from settings_cells import build_cells_table, normalize_toggles
from settings_store import M, load_settings, save_settings
from settings_widgets import _TABLE_DIMS, _Btn, _SelectField, _Toggle
from settings_window import _PanelFrame, _SettingsTitleBar, install_extra_window

NAME = "Gérer les presets"
NO_PRESET = v2.NO_PRESET


def _plain_btn(text: str) -> _Btn:
    return _Btn(text, M["btn_bg"], M["btn_border"], M["btn_fg"], M["btn_hover"], height=25, padding="0 11px")


def _accent_btn(text: str) -> _Btn:
    return _Btn(text, M["accent"], M["accent_border"], M["accent_fg"], M["accent_hover"], height=25,
                weight=600, padding="0 13px")


class PresetPicker(QWidget):
    """Menu deroulant des presets (le preset actif) + bouton « Gerer les presets… ». `presetChosen(nom)`
    ("" = aucun) ; `manageRequested()`."""

    presetChosen = Signal(str)
    manageRequested = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setAttribute(Qt.WA_StyledBackground, False)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(6)
        self.select = _SelectField([NO_PRESET], NO_PRESET, width=150)
        self.select.setToolTip("Preset")
        self.select.changed.connect(lambda name: self.presetChosen.emit("" if name == NO_PRESET else name))
        layout.addWidget(self.select)
        self.manage = _plain_btn("Gérer les presets…")
        self.manage.clicked.connect(self.manageRequested.emit)
        layout.addWidget(self.manage)

    def refresh(self, settings: dict | None = None):
        """Liste et preset actif relus (apres un changement de preset ou de la liste)."""
        settings = settings if settings is not None else load_settings()
        names = store.preset_names()
        active = store.preset_in_use(settings)
        self.select.setOptions([NO_PRESET] + names)
        self.select.blockSignals(True)
        self.select._value = active if active in names else NO_PRESET
        self.select._sync_text()
        self.select.blockSignals(False)

    def restyle(self):
        """Palette des reglages changee (autre preset) : habillage refait."""
        self.select._refresh_style()
        for btn in (self.manage,):
            btn._bg, btn._border, btn._fg, btn._hover = M["btn_bg"], M["btn_border"], M["btn_fg"], M["btn_hover"]
            btn._refresh_style()


class PresetManagerWindow(QDialog):
    """Fenetre outil sans cadre, non modale : un tableau, une ligne par preset (nom modifiable, actif,
    preset par defaut, Dupliquer / Supprimer), puis « Nouveau preset » (depuis les reglages a l'ecran).
    `presetsChanged()` : la liste, un nom ou le preset par defaut a change."""

    presetsChanged = Signal()
    themeChanged = Signal(str)       # le preset fm_theme lie a ce preset de l'appli a change

    _SAVE_DELAY = 400

    def __init__(self, settings: dict | None = None, parent=None):
        super().__init__(parent)
        self.setWindowFlags(Qt.Tool | Qt.FramelessWindowHint)     # opaque : panneau rectangle plein
        self.setAttribute(Qt.WA_DeleteOnClose, True)
        settings = settings or load_settings()
        v2.seed_window_look(settings)
        self._dims_key = f"{NAME}#0"
        saved = (settings.get("table_dims") or {}).get(self._dims_key)
        if saved:
            _TABLE_DIMS[self._dims_key] = saved
        self._armed: str | None = None       # « Supprimer » : 1er clic = confirmer, 2e clic = supprimer
        self._disarm = QTimer(self)
        self._disarm.setSingleShot(True)
        self._disarm.setInterval(3000)
        self._disarm.timeout.connect(self._rebuild)
        self._dims_timer = QTimer(self)
        self._dims_timer.setSingleShot(True)
        self._dims_timer.setInterval(self._SAVE_DELAY)
        self._dims_timer.timeout.connect(self._save_dims)

        panel = _PanelFrame(self)
        panel.setColors(M["panel_bg"], M["panel_border"])
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.addWidget(panel)
        root = QVBoxLayout(panel)
        root.setContentsMargins(1, 1, 1, 1)
        root.setSpacing(0)
        bar = self.titlebar = _SettingsTitleBar(self, title=NAME)
        bar.dirty_label.hide()               # tout est enregistre aussitot
        bar.closeClicked.connect(self.close)
        root.addWidget(bar)
        self.body = QWidget()
        self.body.setStyleSheet("background: transparent;")
        self.body_l = QVBoxLayout(self.body)
        self.body_l.setContentsMargins(16, 14, 16, 16)
        self.body_l.setSpacing(12)
        root.addWidget(self.body)
        self.table = None
        foot = QHBoxLayout()
        foot.setContentsMargins(0, 0, 0, 0)
        foot.setSpacing(8)
        new = _accent_btn("Nouveau preset")
        new.setToolTip("Nouveau preset, avec les réglages à l'écran")
        new.clicked.connect(self._new)
        foot.addWidget(new)
        foot.addStretch(1)
        self.foot = foot
        self._rebuild()
        self.body_l.addLayout(foot)
        install_extra_window(self, panel, outer, root, bar)     # Reglages > Fenetres additionnelles

    # -- tableau --

    def _rebuild(self):
        self._disarm.stop()
        settings = load_settings()
        names = store.preset_names()
        active = store.preset_in_use(settings)
        default = settings.get("default_preset") or ""
        rows = []
        self._names = {}
        self._defaults = {}
        import fm_theme.presets as theme_presets
        themes = list(theme_presets.list_presets()) or [""]
        app_presets = store._load_presets()
        for name in names:
            field = v2._TextField(name, width=200)
            field.editingFinished.connect(lambda f=field, n=name: self._rename(n, f.text()))
            self._names[name] = field
            state = QLabel("actif" if name == active else "")
            state.setStyleSheet(f"color: {M['accent']}; background: transparent;")
            toggle = _Toggle(name == default, style_override="toggle2", show_label=False)
            toggle.toggled.connect(lambda checked, n=name: self._set_default(n, checked))
            self._defaults[name] = toggle
            actions = QWidget()
            actions.setStyleSheet("background: transparent;")
            box = QHBoxLayout(actions)
            box.setContentsMargins(0, 0, 0, 0)
            box.setSpacing(6)
            duplicate = _plain_btn("Dupliquer")
            duplicate.clicked.connect(lambda _c=False, n=name: self._duplicate(n))
            box.addWidget(duplicate)
            armed = self._armed == name
            delete = (_Btn("Confirmer la suppression", M["accent"], M["accent_border"], M["accent_fg"],
                           M["accent_hover"], height=25, padding="0 11px") if armed else _plain_btn("Supprimer"))
            delete.clicked.connect(lambda _c=False, n=name: self._delete(n))
            box.addWidget(delete)
            box.addStretch(1)
            # Thème (aspect generique) lie a ce preset : un preset fm_theme (alias compris).
            linked = app_presets.get(name, {}).get("theme_preset") or ""
            path = theme_presets.find_preset(linked) if linked else None
            linked = theme_presets.load_preset(path)["nom"] if path else themes[0]
            theme = _SelectField(themes, linked, width=150)
            theme.changed.connect(lambda value, n=name: self._set_theme(n, value))
            rows.append([field, (state, "center", "center"), (toggle, "center", "center"), theme,
                         actions])
        if not rows:
            empty = v2._label("Aucun preset : « Nouveau preset » enregistre les réglages à l'écran.")
            rows.append([empty, QLabel(""), QLabel(""), QLabel(""), QLabel("")])
        frame, _head, _cells = build_cells_table(
            [("Preset", 230), ("Actif", 84), ("Par défaut", 112), ("Thème", 170), ("Actions", 280)], rows)
        frame._dims_key = self._dims_key
        normalize_toggles(frame)
        frame.dimsChanged.connect(self._dims_timer.start)
        if self.table is not None:
            self.body_l.replaceWidget(self.table, frame)
            self.table.deleteLater()
        else:
            self.body_l.insertWidget(0, frame, 0, Qt.AlignLeft | Qt.AlignTop)
        self.table = frame
        if self._armed:
            self._disarm.start()
        QTimer.singleShot(0, self.adjustSize)

    # -- actions (enregistrees aussitot) --

    def _changed(self):
        self._rebuild()
        self.presetsChanged.emit()

    def _new(self):
        name = store.unique_preset_name("Nouveau preset")
        store.save_preset(name, load_settings())
        self._changed()
        field = self._names.get(name)
        if field is not None:
            field.setFocus()
            field.selectAll()

    def _duplicate(self, name: str):
        store.duplicate_preset(name)
        self._changed()

    def _rename(self, old: str, new: str):
        if (new or "").strip() and new.strip() != old:
            store.rename_preset(old, new)
            QTimer.singleShot(0, self._changed)   # pas pendant le signal du champ qu'on detruit

    def _delete(self, name: str):
        if self._armed != name:
            self._armed = name                 # 1er clic : demande de confirmation (3 s)
            self._rebuild()
            return
        self._armed = None
        store.delete_preset(name)
        self._changed()

    def _set_theme(self, name: str, theme: str):
        store.set_preset_theme(name, theme)
        self.themeChanged.emit(name)

    def _set_default(self, name: str, checked: bool):
        """Un seul preset par defaut : les autres toggles s'eteignent SUR PLACE (pas de tableau refait,
        il couperait l'animation de la bascule)."""
        current = load_settings().get("default_preset") or ""
        if checked:
            store.set_default_preset(name)
            for other, toggle in self._defaults.items():
                if other != name and toggle.isChecked():
                    toggle.blockSignals(True)
                    toggle.setChecked(False)
                    toggle.blockSignals(False)
        elif current == name:
            store.set_default_preset("")
        self.presetsChanged.emit()

    # -- mise en forme retenue (comme tout tableau des reglages) --

    def _save_dims(self):
        if self.table is None:
            return
        dims = self.table.collectDims()
        _TABLE_DIMS[self._dims_key] = dims
        settings = load_settings()
        all_dims = dict(settings.get("table_dims") or {})
        all_dims[self._dims_key] = dims
        settings["table_dims"] = all_dims
        save_settings(settings)

    def closeEvent(self, event):
        if self._dims_timer.isActive():
            self._dims_timer.stop()
            self._save_dims()
        super().closeEvent(event)

    def showEvent(self, event):
        super().showEvent(event)
        apply_dwm_frame(self, 0, "none", resizable=False)    # cadre et ombre peints
