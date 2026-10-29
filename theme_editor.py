"""Éditeur fm_theme (fm_theme.bat -> `python -m fm_theme`) : la fenêtre de réglages v2 réduite à l'ASPECT
(`settings_window_v2.SettingsWindowV2(module="theme")`, onglet « Thème »), qui lit et écrit un PRESET FM_THEME
(fm_theme/presets/<nom>.json) au lieu des réglages de l'appli, avec la gestion des presets (barre en haut) et la
diffusion en direct vers les applis ouvertes (fm_theme/live.py).

Côté fm_browser (s'appuie sur la v2) tant que la fenêtre générique n'a pas rejoint fm_theme ; plan :
docs/agents/fm_theme.md, étape 5.
"""
from __future__ import annotations

import json

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QHBoxLayout, QLabel, QWidget

import fm_theme.presets as tp
from fm_theme.preview import WIDTH as PREVIEW_WIDTH, PreviewPanel
import settings_window_v2 as v2
from settings_cells import _TextField
from settings_store import M, _load_window_geometry, _save_window_geometry, load_settings, save_settings, theme_in_use
from settings_widgets import _Btn, _SelectField

LAST_PRESET_KEY = "fm_theme:preset"       # preset ouvert la derniere fois (etat des fenetres de reglages)
DELETE_CONFIRM_MS = 3000


class ThemeStore:
    """Magasin de la fenetre : l'aspect vient du preset fm_theme `name` et y retourne ; le reste (etat de la
    fenetre : dimensions des tableaux, espaces...) reste dans les reglages de l'appli."""

    def __init__(self, name: str):
        self.name = name

    def _theme_values(self) -> dict:
        return json.loads(json.dumps(tp.to_settings(tp.load_preset(tp.find_preset(self.name)))))

    def load(self) -> dict:
        settings = load_settings()
        settings.update(self._theme_values())
        return settings

    def _split(self, values: dict) -> tuple[dict, dict]:
        theme = {k: v for k, v in values.items() if tp.theme_key(k)}
        return theme, {k: v for k, v in values.items() if k not in theme}

    def _save_app(self, rest: dict, drop: tuple = ()) -> None:
        if not rest and not drop:
            return
        settings = load_settings()
        settings.update(rest)
        for key in drop:
            settings.pop(key, None)
        save_settings(settings)

    def save_partial(self, partial: dict, drop: tuple = ()) -> None:
        theme, rest = self._split(partial)
        theme_drop = tuple(k for k in drop if tp.theme_key(k))
        if theme or theme_drop:
            tp.update_preset(self.name, theme, drop=theme_drop)
        self._save_app(rest, tuple(k for k in drop if k not in theme_drop))

    def save_changes(self, changed: dict) -> dict:
        theme, rest = self._split(changed)
        if theme:
            tp.update_preset(self.name, theme)
        self._save_app(rest)
        return self.load()


def _btn(text: str) -> _Btn:
    return _Btn(text, M["btn_bg"], M["btn_border"], M["btn_fg"], M["btn_hover"], height=25, padding="0 11px")


class PresetBar(QWidget):
    """Barre des presets fm_theme, en haut de l'editeur : preset edite, nom (renommer / nom du nouveau),
    Renommer, Dupliquer, Nouveau (= les valeurs a l'ecran), Supprimer (deux clics)."""

    def __init__(self, editor: "ThemeEditor"):
        super().__init__()
        self._editor = editor
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 6, 0, 6)
        layout.setSpacing(6)
        label = QLabel("Preset")
        label.setStyleSheet(f"color: {M['label_dim']}; background: transparent;")
        layout.addWidget(label)
        self.select = _SelectField([editor.name], editor.name, width=170)
        self.select.changed.connect(editor.switch_to)
        layout.addWidget(self.select)
        self.name_field = _TextField(editor.name, width=150)
        layout.addWidget(self.name_field)
        for text, slot in (("Renommer", self._rename), ("Dupliquer", self._duplicate), ("Nouveau", self._new)):
            button = _btn(text)
            button.clicked.connect(slot)
            layout.addWidget(button)
        self.delete = _btn("Supprimer")
        self.delete.clicked.connect(self._delete)
        layout.addWidget(self.delete)
        layout.addStretch(1)
        self._armed = QTimer(self, singleShot=True, interval=DELETE_CONFIRM_MS)
        self._armed.timeout.connect(lambda: self.delete.setText("Supprimer"))
        self.refresh()

    def refresh(self):
        names = list(tp.list_presets())
        self.select.setOptions(names or [self._editor.name])
        self.select.setValue(self._editor.name)
        self.name_field.setText(self._editor.name)
        self.delete.setEnabled(len(names) > 1)       # jamais zero preset

    def _rename(self):
        new = tp.rename_preset(self._editor.name, self.name_field.text())
        self._editor.switch_to(new, save=False)

    def _duplicate(self):
        self._editor.save_pending()
        self._editor.switch_to(tp.duplicate_preset(self._editor.name, self.name_field.text()
                                                   if self.name_field.text() != self._editor.name else None))

    def _new(self):
        values = dict(self._editor.window.settings)
        values.update(self._editor.window.wired_values())          # les valeurs a l'ecran, modifications comprises
        self._editor.switch_to(tp.new_preset(self.name_field.text() or "Preset", values), save=False)

    def _delete(self):
        if not self._armed.isActive():               # 1er clic : demande confirmation
            self.delete.setText("Confirmer la suppression")
            self._armed.start()
            return
        self._armed.stop()
        gone = self._editor.name
        tp.delete_preset(gone)
        remaining = [n for n in tp.list_presets() if n != gone]
        self._editor.switch_to(remaining[0], save=False)


class ThemeEditor:
    """L'editeur : une fenetre v2 « Theme » sur le preset `name`, refaite a chaque changement de preset ;
    pendant un geste, les cles d'aspect modifiees partent vers les applis ouvertes (`server`)."""

    def __init__(self, name: str, server=None):
        self.name = name
        self.server = server
        self.window = None
        self.open(name)

    def open(self, name: str):
        old = self.window
        self.name = name
        _save_window_geometry(name, LAST_PRESET_KEY)
        window = self.window = v2.SettingsWindowV2(None, module="theme", store=ThemeStore(name))
        window.titlebar._title.setText(f"fm_theme : {name}")
        window._tab_subbar.layout().insertWidget(0, PresetBar(self))
        window.settingsChanged.connect(self._broadcast)
        self.preview = self._add_preview(window)
        if old is not None:
            window.setGeometry(old.geometry())
        window.show()
        QTimer.singleShot(0, lambda w=window: self._follow_sections(w))
        if old is not None:
            old.hide()
            old.deleteLater()

    def _add_preview(self, window) -> PreviewPanel:
        """Aperçu à gauche des sections (demande de l'utilisateur) : la pile des pages passe à droite."""
        stack = window.stack
        root = stack.parentWidget().layout()
        index = root.indexOf(stack)
        root.removeWidget(stack)
        holder = QWidget()
        row = QHBoxLayout(holder)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(0)
        preview = PreviewPanel(lambda: window.settings)
        row.addWidget(preview)
        row.addWidget(stack, 1)
        root.insertWidget(index, holder, 1)
        if window.width() < 760 + PREVIEW_WIDTH:
            window.resize(760 + PREVIEW_WIDTH, window.height())
        window.settingsChanged.connect(self._refresh_preview)
        return preview

    def _follow_sections(self, window, tries: int = 20):
        """L'aperçu suit la section ouverte (sections de 1er niveau de la page, construite à la 1re visite)."""
        if window is not self.window:
            return
        nodes = [n for n in window.stack.findChildren(v2._LazyNode) if n.level == 1]
        if not nodes:
            if tries:
                QTimer.singleShot(50, lambda: self._follow_sections(window, tries - 1))
            return
        for node in nodes:
            node._head.collapsedChanged.connect(lambda collapsed, n=node: self._section_toggled(n, collapsed))
        opened = [n for n in nodes if not n.is_collapsed()]
        self.preview.show_section(opened[0].node.title if opened else None)

    def _section_toggled(self, node, collapsed: bool):
        if not collapsed:
            self.preview.show_section(node.node.title)
        elif self.preview.section() == node.node.title:
            self.preview.show_section(None)

    def _refresh_preview(self, _settings: dict):
        """Couleurs, polices, échelle : les boutons gardent les couleurs de leur construction, l'aperçu est refait."""
        keys = getattr(self.window, "live_changed_keys", None) or ()
        if any(k == "colors" or k.startswith("font_") or k == "ui_scale" for k in keys):
            self.preview.show_section(self.preview._section, force=True)

    def save_pending(self):
        """Modifications non enregistrees du preset ouvert : enregistrees avant d'en changer."""
        if getattr(self.window, "_dirty", False):
            self.window._write_settings()

    def switch_to(self, name: str, save: bool = True):
        if save:
            self.save_pending()
        if name and tp.find_preset(name) is not None:
            self.open(name)

    def _broadcast(self, settings: dict):
        if self.server is None:
            return
        keys = getattr(self.window, "live_changed_keys", None) or ()
        values = {k: settings[k] for k in keys if k in settings and tp.theme_key(k)}
        if values:
            self.server.broadcast(self.name, values)


def initial_preset() -> str:
    """Preset a ouvrir : le dernier edite, sinon celui de fm_browser, sinon le premier (cree s'il n'y en a aucun)."""
    names = list(tp.list_presets())
    for name in (_load_window_geometry(LAST_PRESET_KEY), theme_in_use(load_settings())):
        if name and tp.find_preset(name) is not None:
            return tp.load_preset(tp.find_preset(name))["nom"]
    if names:
        return names[0]
    return tp.new_preset("Preset", load_settings())

