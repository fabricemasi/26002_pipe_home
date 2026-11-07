"""Presets : choix dans la fenetre principale (menu deroulant + bouton « Gerer les presets… ») et fenetre de
gestion (liste de tous les presets : actif, preset par defaut, « Enregistrer » le preset a l'ecran).

La liste est CELLE DE fm_theme, a l'identique : un preset se cree, se renomme et se supprime SEULEMENT dans
fm_theme (demande de l'utilisateur, 2026-10-30) ; fm_browser n'enregistre que sa couche de reglages propres
(settings_store, « Presets »). Donnees et regles dans settings_store (`apply_preset`, `save_preset`,
`set_default_preset`, `preset_in_use`, `preset_names`) ; c'est l'appelant qui applique les reglages a l'ecran
et suit le dossier des presets fm_theme (signaux `presetChosen` / `presetsChanged` / `themeEditorRequested`).
Habillage = briques de la fenetre de reglages v2 (`_SelectField`, `_Btn`, `_Toggle`, `build_cells_table`,
`_PanelFrame`, `_SettingsTitleBar`)."""
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
    """Menu deroulant des presets fm_theme (le preset actif) + bouton « Gerer les presets… ». `presetChosen(nom)` ;
    `manageRequested()`."""

    presetChosen = Signal(str)
    manageRequested = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setAttribute(Qt.WA_StyledBackground, False)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(6)
        self.select = _SelectField([NO_PRESET], NO_PRESET, width=150)
        self.select.setToolTip("Preset (liste de fm_theme)")
        self.select.changed.connect(lambda name: name != NO_PRESET and self.presetChosen.emit(name))
        layout.addWidget(self.select)
        self.manage = _plain_btn("Gérer les presets…")
        self.manage.clicked.connect(self.manageRequested.emit)
        layout.addWidget(self.manage)

    def refresh(self, settings: dict | None = None):
        """Liste et preset actif relus (apres un changement de preset ou de la liste)."""
        settings = settings if settings is not None else load_settings()
        names = store.preset_names()
        active = store.preset_in_use(settings)
        self.select.setOptions(names or [NO_PRESET])
        self.select.blockSignals(True)
        self.select._value = active if active in names else (names[0] if names else NO_PRESET)
        self.select._sync_text()
        self.select.blockSignals(False)

    def restyle(self):
        """Palette des reglages changee (autre preset) : habillage refait."""
        self.select._refresh_style()
        for btn in (self.manage,):
            btn._bg, btn._border, btn._fg, btn._hover = M["btn_bg"], M["btn_border"], M["btn_fg"], M["btn_hover"]
            btn._refresh_style()


class PresetManagerWindow(QDialog):
    """Fenetre outil sans cadre, non modale : un tableau, une ligne par preset fm_theme (nom, actif, preset par
    defaut, couche fm_browser, « Enregistrer » sur le preset a l'ecran), puis « Ouvrir fm_theme » (creer, renommer,
    supprimer). `presetsChanged()` : le preset par defaut a change ; `refresh()` : la liste de fm_theme a change."""

    presetsChanged = Signal()
    themeEditorRequested = Signal()  # « Ouvrir fm_theme » : seul endroit ou les presets se creent / suppriment

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
        theme = _accent_btn("Ouvrir fm_theme")
        theme.setToolTip("Les presets se créent, se renomment et se suppriment dans fm_theme")
        theme.clicked.connect(self.themeEditorRequested.emit)
        foot.addWidget(theme)
        note = v2._label("Créer, renommer, supprimer un preset : dans fm_theme.")
        foot.addWidget(note)
        foot.addStretch(1)
        self.foot = foot
        self._rebuild()
        self.body_l.addLayout(foot)
        install_extra_window(self, panel, outer, root, bar)     # Reglages > Fenetres additionnelles

    # -- tableau --

    def refresh(self):
        """Liste de fm_theme ou preset actif changes (dossier surveille par la fenetre principale)."""
        self._rebuild()

    def _rebuild(self):
        settings = load_settings()
        names = store.preset_names()
        active = store.preset_in_use(settings)
        default = settings.get("default_preset") or ""
        layers = store._load_presets()
        rows = []
        self._defaults = {}
        for name in names:
            state = QLabel("actif" if name == active else "")
            state.setStyleSheet(f"color: {M['accent']}; background: transparent;")
            toggle = _Toggle(name == default, style_override="toggle2", show_label=False)
            toggle.toggled.connect(lambda checked, n=name: self._set_default(n, checked))
            self._defaults[name] = toggle
            if name == active:
                action = _plain_btn("Enregistrer")
                action.setToolTip("Enregistre les réglages à l'écran dans ce preset (couche fm_browser et thème)")
                action.clicked.connect(lambda _c=False, n=name: self._save(n))
            else:
                action = QLabel("")
            rows.append([v2._label(name), (state, "center", "center"), (toggle, "center", "center"),
                         (v2._label("enregistrée" if name in layers else "—"), "center", "center"), action])
        if not rows:
            empty = v2._label("Aucun preset : créez-en un dans fm_theme.")
            rows.append([empty, QLabel(""), QLabel(""), QLabel(""), QLabel("")])
        frame, _head, _cells = build_cells_table(
            [("Preset", 230), ("Actif", 84), ("Par défaut", 112), ("Couche fm_browser", 160), ("Actions", 140)],
            rows)
        frame._dims_key = self._dims_key
        normalize_toggles(frame)
        frame.dimsChanged.connect(self._dims_timer.start)
        if self.table is not None:
            self.body_l.replaceWidget(self.table, frame)
            self.table.hide()
            self.table.setParent(None)
            self.table.deleteLater()
        else:
            self.body_l.insertWidget(0, frame, 0, Qt.AlignLeft | Qt.AlignTop)
        self.table = frame
        QTimer.singleShot(0, self.adjustSize)

    # -- actions (enregistrees aussitot) --

    def _save(self, name: str):
        """« Enregistrer » : les reglages a l'ecran dans le preset (jamais un preset cree ici)."""
        import ui_state
        store.save_preset(name, ui_state.APPLIED_SETTINGS or load_settings())
        self._rebuild()

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
