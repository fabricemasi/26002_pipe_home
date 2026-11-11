"""Éditeur fm_theme (fm_theme.bat -> `python -m fm_theme`) : la fenêtre de réglages v2 réduite à l'ASPECT
(`settings_window_v2.SettingsWindowV2(module="theme")`, onglet « Thème »), qui lit et écrit un PRESET FM_THEME
(fm_theme/presets/<nom>.json) au lieu des réglages de l'appli, avec la gestion des presets (barre en haut) et la
diffusion en direct vers les applis ouvertes (fm_theme/live.py).

Côté fm_browser (s'appuie sur la v2) tant que la fenêtre générique n'a pas rejoint fm_theme ; plan :
docs/agents/fm_theme.md, étape 5.
"""
from __future__ import annotations

import json

import shiboken6
from PySide6.QtCore import QEvent, Qt, QTimer
from PySide6.QtGui import QColor, QPainter
from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QPushButton, QSizePolicy, QVBoxLayout, QWidget

import fm_theme.presets as tp
from fm_theme.preview import WIDTH as PREVIEW_WIDTH, PreviewPanel
import settings_window_v2 as v2
from settings_cells import _TextField
import settings_store
from settings_store import M, _load_window_geometry, _save_window_geometry, load_settings, save_settings, theme_in_use
from fm_theme.theme import _set_text_role
from fm_theme.tokens import _resolve_color_value, toggle_style_list
from fm_theme.widgets import _Toggle
from settings_widgets import _Btn, _SelectField
from theme_side_detail import SideDetail, page_scroller

LAST_PRESET_KEY = "fm_theme:preset"       # preset ouvert la derniere fois (etat des fenetres de reglages)
PREVIEW_WIDTH_KEY = "fm_theme:preview_width"   # largeur de l'apercu (tiree a la souris), meme fichier
DELETE_CONFIRM_MS = 3000
SELECTION_PAD = 8                          # px entre le cadre de sélection d'une variante et son contenu


class ThemeStore:
    """Magasin de la fenetre : l'aspect vient du preset fm_theme `name` et y retourne ; le reste (etat de la
    fenetre : dimensions des tableaux, espaces...) reste dans les reglages de l'appli."""

    def __init__(self, name: str):
        self.name = name
        # Variante EDITEE par type (titres, boutons...) ; absente : la variante par defaut du type.
        self.editing: dict[str, str] = {}

    def _theme_values(self) -> dict:
        preset = tp.load_preset(tp.find_preset(self.name))
        values = tp.to_settings(preset)
        for type_name, variant in self.editing.items():
            values.update(tp.type_flat(preset, type_name, variant))
        return json.loads(json.dumps(values))

    def edited_variants(self, types) -> dict:
        """{type: variante editee} (types a variantes seulement) : la variante par defaut si aucune n'est choisie."""
        preset = tp.load_preset(tp.find_preset(self.name))
        return {t: self.editing.get(t) or tp.default_variant((preset.get("types") or {}).get(t) or {})
                for t in types if t in tp.TYPE_PREFIXES}

    def is_default(self, type_name: str) -> bool:
        """La variante editee de ce type est-elle sa variante par defaut (celle que recoivent les applis) ?"""
        variant = self.editing.get(type_name)
        if not variant:
            return True
        entry = (tp.load_preset(tp.find_preset(self.name)).get("types") or {}).get(type_name) or {}
        return variant == tp.default_variant(entry)

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
            tp.update_preset(self.name, theme, drop=theme_drop, editing=self.editing)
        self._save_app(rest, tuple(k for k in drop if k not in theme_drop))

    def save_row_templates(self, templates: dict) -> None:
        """Gabarits des lignes des fenetres de reglages : dans le preset edite (valeur generale du theme)."""
        tp.save_row_templates(self.name, templates)

    def save_changes(self, changed: dict) -> dict:
        theme, rest = self._split(changed)
        if theme:
            tp.update_preset(self.name, theme, editing=self.editing)
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


# Section de l'editeur -> type d'element a variantes (fm_theme.presets.TYPE_PREFIXES). Toggles : leurs styles.
SECTION_TYPES = {"TITRES": "titres", "Sliders": "slider", "Zone de saisie": "champ", "Bouton": "bouton",
                 "Tableaux": "tableau", "Tabs": "onglets", "Menu contextuel": "menu",
                 "Fenêtres additionnelles": "fenetre", "Barres d'outils": "palette", "Toggles": "toggle",
                 "Barre de navigation": "navigation", "Barre d'état": "etat"}
# Aperçus refaits par `set_values` (images, barres peintes) : la variante éditée suit le geste par eux ; les autres
# types sont restylés en direct par la fenêtre (registres des briques).
SHOT_TYPES = ("menu", "fenetre", "navigation", "etat")


def _seed_globals(type_name: str, values: dict) -> None:
    """Pose l'habillage GLOBAL des briques d'un type d'après `values`, SANS restyler les éléments déjà construits :
    sert à dessiner une variante non éditée (puis à remettre l'habillage courant)."""
    from fm_theme import tokens
    if type_name == "slider":
        tokens._sync_slider_style(values)
    elif type_name == "titres":
        tokens._sync_title_level_style(values)
    elif type_name == "champ":
        tokens.set_input_look(values)
    elif type_name == "onglets":
        from fm_theme.layout import set_tab_look
        set_tab_look(values)
    elif type_name == "tableau":
        v2.seed_table_globals(values)
    elif type_name == "palette":
        from fm_theme.palette import set_look
        set_look(values)
    elif type_name == "fenetre":
        from fm_theme import window as fw
        opened = list(fw._EXTRA_WINDOWS)             # les fenêtres ouvertes gardent leur habillage
        fw._EXTRA_WINDOWS.clear()
        try:
            fw.seed_extra_window_look(values)
        finally:
            fw._EXTRA_WINDOWS[:] = opened


def _line(vertical: bool = False, color: str | None = None) -> QFrame:
    """Filet de séparation du volet des variantes (couleur des bordures de panneau, ou `color`)."""
    line = QFrame()
    if vertical:
        line.setFixedWidth(1)
    else:
        line.setFixedHeight(1)
    line.setStyleSheet(f"background: {color or M['panel_border']}; border: none;")
    return line


def _button_states(values: dict) -> tuple[QWidget, list]:
    """Aperçus d'une variante du bouton : État standard | État survol | État focus, séparés par un filet ; chaque bouton
    est FIGÉ dans son état (`button_state_css`), sans réaction à la souris."""
    from fm_theme.style import BUTTON_STATES, button_state_css
    holder = QWidget()
    holder.setObjectName("variantStates")
    row = QHBoxLayout(holder)
    row.setContentsMargins(0, 4, 0, 4)
    row.setSpacing(10)
    buttons = []
    for index, (state, caption) in enumerate(BUTTON_STATES):
        if index:
            row.addWidget(_line(vertical=True))
        column = QVBoxLayout()
        column.setSpacing(8)
        label = _set_text_role(QLabel(caption), "inline_label")
        label.setWordWrap(True)
        label.setAlignment(Qt.AlignHCenter)
        column.addWidget(label)
        button = QPushButton("Bouton")
        button.setAttribute(Qt.WA_TransparentForMouseEvents, True)
        button.setFocusPolicy(Qt.NoFocus)
        button.setFixedHeight(26)
        button.setStyleSheet(button_state_css(values, state))
        button._state = state
        buttons.append(button)
        column.addWidget(button, 0, Qt.AlignHCenter)
        row.addLayout(column, 1)
    return holder, buttons


class _VariantBlock(QWidget):
    """Une variante : filet, nom (zone de saisie : renommer à la validation), « − » (supprimer, deux clics), interrupteur
    « par défaut » à droite ; dessous ses aperçus (bouton : ses trois états). Un clic dessus l'ÉDITE (ses valeurs dans
    les champs) ; clic droit : l'utiliser dans fm_browser."""

    def __init__(self, panel: "VariantList", name: str, *, edited: bool, default: bool, used: bool, alone: bool,
                 values: dict, label: str | None = None):
        super().__init__()
        self.panel, self.name, self.edited = panel, name, edited
        self.label = label or name
        self.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Maximum)         # jamais étirée en hauteur
        # Le fond du cadre de sélection passe SOUS les aperçus et les libellés : la feuille de l'appli peint sinon
        # « QWidget { background: window } » sur eux (demande de l'utilisateur, 2026-11-10).
        self.setStyleSheet("QWidget#variantStates, QLabel { background: transparent; }")
        layout = QVBoxLayout(self)
        pad = SELECTION_PAD + int(panel.selection.get("variant_sel_border_thickness") or 0)
        layout.setContentsMargins(pad, pad, pad, pad)
        layout.setSpacing(8)
        top = QHBoxLayout()
        top.setSpacing(6)
        self.name_field = _TextField(self.label, width=150)
        self.name_field.editingFinished.connect(self._rename)
        self.name_field.installEventFilter(self)
        top.addWidget(self.name_field)
        self.delete = _btn("−")
        self.delete.setToolTip("Supprimer cette variante (deux clics)")
        self.delete.setEnabled(not alone)                                       # jamais la dernière
        self.delete.clicked.connect(self._delete)
        top.addWidget(self.delete)
        top.addStretch(1)
        if used:
            top.addWidget(_set_text_role(QLabel("fm_browser"), "note"))
        top.addWidget(_set_text_role(QLabel("par défaut"), "note"))
        self.default = _Toggle(default)
        self.default.setToolTip("Variante par défaut (celle que reçoivent les applis)")
        self.default.toggled.connect(self._default_toggled)
        top.addWidget(self.default)
        layout.addLayout(top)
        self.buttons = []
        self.preview = None
        if panel.type_name == "bouton":
            states, self.buttons = _button_states(values)
            layout.addWidget(states)
        else:                                      # chaque variante, son aperçu sous son nom (2026-11-11)
            self.preview = panel.preview_for(name, values, edited)
            if self.preview is not None:
                layout.addWidget(self.preview)
        self._armed = QTimer(self, singleShot=True, interval=DELETE_CONFIRM_MS)
        self._armed.timeout.connect(lambda: self.delete.setText("−"))
        self.setContextMenuPolicy(Qt.CustomContextMenu)
        self.customContextMenuRequested.connect(self._menu)

    def paintEvent(self, event):
        """La variante ÉDITÉE : cadre de sélection (Thème > Général > Variantes : bordure, border radius, fond)."""
        if not self.edited:
            return
        from settings_widgets import _paint_bordered_rect, _radius_any
        look = self.panel.selection
        colors = {s: _resolve_color_value(c, look.get("colors") or {})
                  for s, c in (look.get("variant_sel_border") or {}).items()}
        fill = _resolve_color_value(look.get("variant_sel_bg_color") or "#00000000", look.get("colors") or {})
        radius = look.get("variant_sel_corner_radius") or 0
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing, _radius_any(radius))
        _paint_bordered_rect(painter, self.rect(), radius, look.get("variant_sel_border_enabled", True),
                             int(look.get("variant_sel_border_thickness") or 0), colors,
                             fill if QColor(fill).alpha() else None)
        painter.end()

    def set_values(self, values: dict) -> None:
        from fm_theme.style import button_state_css
        for button in self.buttons:
            button.setStyleSheet(button_state_css(values, button._state))

    def eventFilter(self, obj, event):
        if obj is self.name_field and event.type() == QEvent.FocusIn:
            QTimer.singleShot(0, self._edit)        # saisir son nom : c'est elle qu'on règle
        return False

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            self._edit()
        super().mousePressEvent(event)

    def _edit(self):
        self.panel.edit(self.name)

    def _rename(self):
        text = self.name_field.text().strip()
        if text and text != self.label:
            self.panel.rename(self.name, text)
        else:
            self.name_field.setText(self.label)

    def _delete(self):
        if not self._armed.isActive():
            self.delete.setText("Supprimer ?")
            self._armed.start()
            return
        self._armed.stop()
        self.panel.delete(self.name)

    def _default_toggled(self, on: bool):
        if on:
            self.panel.set_default(self.name)
        else:                                      # on ne « décoche » pas la défaut : on en choisit une autre
            QTimer.singleShot(0, lambda: self.default.setChecked(True))

    def _menu(self, pos):
        from fm_theme.menu import Menu
        menu = Menu(self)
        action = menu.addAction("Utiliser dans fm_browser")
        action.setEnabled(self.panel.app_linked and self.name != self.panel.app_variant)
        action.triggered.connect(lambda: self.panel.use_in_app(self.name))
        menu.exec(self.mapToGlobal(pos))


class VariantList(QWidget):
    """Volet des variantes du type de la section ouverte (croquis de l'utilisateur, 2026-11-10) : une ligne par
    variante (`_VariantBlock`) ; le « + » de l'en-tête du volet (`add_button`) en crée une, copie de l'éditée."""

    def __init__(self, editor: "ThemeEditor", type_name: str):
        super().__init__()
        self._editor, self.type_name = editor, type_name
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(6)
        self.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Maximum)         # collée sous le titre, sans trou
        settings = editor.window.current_values() if editor.window is not None else load_settings()
        self.settings = settings
        self.selection = {k: v for k, v in settings.items() if k.startswith("variant_sel_")}
        self.selection["colors"] = settings.get("colors") or {}
        pad = SELECTION_PAD + int(self.selection.get("variant_sel_border_thickness") or 0)
        self.preview_width = max(140, editor.preview._w - 32 - 2 * pad)
        labels = {}
        if type_name == "toggle":                    # styles de toggles : les réglages de la fenêtre (toggle<N>_*)
            preset = None
            styles = toggle_style_list(settings)
            names = [s["key"] for s in styles]
            labels = {s["key"]: s["name"] for s in styles}
            default = settings.get("toggle_style") if settings.get("toggle_style") in names else names[0]
        else:
            preset = tp.load_preset(tp.find_preset(editor.name))
            names = tp.variant_names(preset, type_name)
            default = tp.default_variant(preset["types"][type_name])
        self.current = editor.store.editing.get(type_name) or default
        if self.current not in names:
            self.current = default
        # fm_browser utilise-t-il cette variante (sa surcharge, ou la défaut) ? Seulement si c'est son thème.
        app = load_settings()
        self.app_linked = type_name != "toggle" and theme_in_use(app) == editor.name
        self.app_variant = settings_store.app_variant(app, type_name) if self.app_linked else None
        self.blocks = {}
        for index, name in enumerate(names):
            if index:
                layout.addWidget(_line())
            values = self._values(preset, name) if preset is not None else {}
            block = _VariantBlock(self, name, edited=name == self.current, default=name == default,
                                  used=name == self.app_variant, alone=len(names) < 2, values=values,
                                  label=labels.get(name))
            self.blocks[name] = block
            layout.addWidget(block)
        self.add_button = _btn("+")
        self.add_button.setToolTip("Nouvelle variante (copie de celle qui est éditée)")
        self.add_button.clicked.connect(self.add)

    def _values(self, preset: dict, name: str, live: dict | None = None) -> dict:
        """Valeurs d'une variante ; l'éditée : celles des champs (`live` : l'aperçu en direct ; sinon les champs lus),
        modifications non enregistrées comprises."""
        if name == self.current and self._editor.window is not None:
            prefix = tp.TYPE_PREFIXES[self.type_name]
            source = live if live is not None else self._editor.window.current_values()
            return {k: v for k, v in source.items() if k.startswith(prefix)}
        return tp.type_flat(preset, self.type_name, name)

    def preview_for(self, name: str, values: dict, edited: bool) -> QWidget | None:
        """Aperçu d'une variante sous son nom : toggles vivants (chaque style les siens) ; l'éditée : l'élément VIVANT
        (restylé en direct) ; les autres : une IMAGE dessinée avec leurs valeurs (habillage global posé le temps du
        dessin, puis remis : rien d'autre n'est restylé)."""
        from fm_theme.preview import element, grab_offscreen
        if self.type_name == "toggle":
            holder = QWidget()
            row = QHBoxLayout(holder)
            row.setContentsMargins(0, 0, 0, 0)
            row.setSpacing(10)
            for on in (True, False):
                toggle = _Toggle(on, style_override=name)
                toggle.setAttribute(Qt.WA_TransparentForMouseEvents, True)
                row.addWidget(toggle)
            row.addStretch(1)
            return holder
        merged = {**self.settings, **values}
        if edited:
            return element(self.type_name, merged, self.preview_width)
        _seed_globals(self.type_name, merged)
        try:
            widget = element(self.type_name, merged, self.preview_width)
            if widget is None:
                return None
            pixmap = widget.pixmap() if isinstance(widget, QLabel) else grab_offscreen(widget, self.preview_width)
            widget.deleteLater()
        finally:
            _seed_globals(self.type_name, self.settings)
        image = QLabel()
        image.setPixmap(pixmap)
        image.setAttribute(Qt.WA_TransparentForMouseEvents, True)      # un clic : éditer la variante
        return image

    def refresh_selection(self, live: dict) -> None:
        """Cadre de sélection réglé (Thème > Général > Variantes) : repeint en direct."""
        self.selection = {k: v for k, v in live.items() if k.startswith("variant_sel_")}
        self.selection["colors"] = live.get("colors") or {}
        block = self.blocks.get(self.current)
        if block is not None:
            block.update()

    def refresh_values(self, live: dict) -> None:
        """Aperçu en direct (`live` : toutes les valeurs) : les aperçus de la variante éditée suivent, rien d'autre."""
        block = self.blocks.get(self.current)
        if block is not None and block.buttons:
            block.set_values(self._values({}, self.current, live))
        elif block is not None and self.type_name in SHOT_TYPES and block.preview is not None:
            block.preview.set_values(live)

    def edit(self, name: str):
        if name != self.current:
            self._editor.edit_variant(self.type_name, name)

    def add(self):
        self._editor.save_pending()
        if self.type_name == "toggle":
            label = self.blocks[self.current].label
            new = self._editor.window.add_toggle_style(f"{label} copie", source=self.current)
        else:
            new = tp.add_variant(self._editor.name, self.type_name, f"{self.current} copie", self.current)
        self._editor.edit_variant(self.type_name, new, save=False)

    def rename(self, old: str, new: str):
        self._editor.save_pending()
        if self.type_name == "toggle":
            self._editor.window.rename_toggle_style(old, new)
            self._editor._refresh_variant_bar()
            return
        new = tp.rename_variant(self._editor.name, self.type_name, old, new)
        if old == self.current:
            self._editor.edit_variant(self.type_name, new, save=False)
        else:
            self._editor._refresh_variant_bar()

    def set_default(self, name: str):
        self._editor.save_pending()
        if self.type_name == "toggle":
            window = self._editor.window
            window._write_now({"toggle_style": name})
            for picker in window.findChildren(v2._ToggleStylePicker):
                picker.setValue(name)
        else:
            tp.set_default_variant(self._editor.name, self.type_name, name)
        self._editor._refresh_variant_bar()

    def delete(self, name: str):
        if self.type_name == "toggle":
            self._editor.window.delete_toggle_style(name)
            target = self.current if name != self.current else self._editor.window.settings.get("toggle_style")
            self._editor.edit_variant("toggle", target, save=False)
            return
        tp.delete_variant(self._editor.name, self.type_name, name)
        preset = tp.load_preset(tp.find_preset(self._editor.name))
        target = self.current if name != self.current else tp.default_variant(preset["types"][self.type_name])
        self._editor.edit_variant(self.type_name, target, save=False)

    def use_in_app(self, name: str):
        """fm_browser utilise cette variante pour ce type (`theme_default_variants`) ; le preset ne change pas."""
        self._editor.save_pending()
        settings = settings_store.set_app_variant(self.type_name, name)
        for listener in self._editor.app_listeners:
            listener(settings)
        self._editor.edit_variant(self.type_name, name, save=False)


class ThemeEditor:
    """L'editeur : une fenetre v2 « Theme » sur le preset `name`, refaite a chaque changement de preset ;
    pendant un geste, les cles d'aspect modifiees partent vers les applis ouvertes (`server`)."""

    def __init__(self, name: str, server=None, listeners=(), app_listeners=()):
        self.name = name
        self.server = server
        # Rappels (reglages) quand fm_browser change de variante utilisee : fenetre principale du meme processus.
        self.app_listeners = list(app_listeners)
        # Rappels (preset, valeurs) dans le meme processus : fenetre principale de fm_browser ouverte avec l'editeur.
        self.listeners = list(listeners)
        self.window = None
        self.open(name)

    def open(self, name: str):
        old = self.window
        self.name = name
        _save_window_geometry(name, LAST_PRESET_KEY)
        self.store = ThemeStore(name)
        window = self.window = v2.SettingsWindowV2(None, module="theme", store=self.store)
        self.detail = None                   # volet des paramètres (`theme_side_detail`), posé par _follow_sections
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
        """Volet d'aperçu et des variantes à GAUCHE des sections (demande de l'utilisateur, 2026-11-10 ; à droite depuis
        le 2026-11-02) : la pile des pages est à sa droite."""
        stack = window.stack
        root = stack.parentWidget().layout()
        index = root.indexOf(stack)
        root.removeWidget(stack)
        holder = QWidget()
        row = QHBoxLayout(holder)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(0)
        try:
            width = int(_load_window_geometry(PREVIEW_WIDTH_KEY) or PREVIEW_WIDTH)
        except (TypeError, ValueError):
            width = PREVIEW_WIDTH
        preview = PreviewPanel(lambda: window.settings, width=width)
        preview.widthChanged.connect(lambda w: _save_window_geometry(str(w), PREVIEW_WIDTH_KEY))
        row.addWidget(preview)
        row.addWidget(stack, 1)
        root.insertWidget(index, holder, 1)
        if window.width() < 760 + preview.width():
            window.resize(760 + preview.width(), window.height())
        window.settingsChanged.connect(self._refresh_preview)
        return preview

    def _follow_sections(self, window, tries: int = 20):
        """L'aperçu suit la section ouverte (sections de 1er niveau de la page, construite à la 1re visite)."""
        if window is not self.window or not shiboken6.isValid(window):
            return
        nodes = [n for n in window.stack.findChildren(v2._LazyNode) if n.level == 1]
        if not nodes:
            if tries:
                QTimer.singleShot(50, lambda: self._follow_sections(window, tries - 1))
            return
        scroller = page_scroller(nodes[0])
        if scroller is not None:             # titres fixes à gauche, paramètres de la section ouverte à droite
            # Posé par la page elle-même (toutes les fenêtres de réglages, settings_window_v2._build_page).
            self.detail = getattr(scroller.parentWidget(), "_side_detail", None) or SideDetail(scroller, nodes)
        for node in nodes:
            node._head.collapsedChanged.connect(lambda collapsed, n=node: self._section_toggled(n, collapsed))
        opened = [n for n in nodes if not n.is_collapsed()]
        self.preview.show_section(opened[0].node.title if opened else None)
        self._refresh_variant_bar()

    def _section_toggled(self, node, collapsed: bool):
        if not collapsed:
            self.preview.show_section(node.node.title)
            # Seules ses sous-sections apparaissent, repliées : un tableau se monte quand on la déplie
            # (demande de l'utilisateur, 2026-11-03 ; avant : tout se déroulait d'un coup).
        elif self.preview.section() == node.node.title:
            self.preview.show_section(None)
        self._refresh_variant_bar()

    def _refresh_variant_bar(self):
        """Liste des variantes du type de la section affichee dans le volet (aucune pour les autres) ; son « + » dans
        l'en-tete du volet ; pour le bouton, elle tient lieu d'apercu (chaque variante montre ses trois etats)."""
        type_name = SECTION_TYPES.get(self.preview.section())
        variants = VariantList(self, type_name) if type_name else None
        self.preview.set_header_tool(variants.add_button if variants is not None else None)
        self.preview.set_tools(variants, replace=variants is not None)    # chaque variante montre son aperçu
        key = variants.current if type_name == "toggle" else None
        self._show_toggle_style(key)
        # La section se construit à sa 1re ouverture (après ce signal) : le filtre repasse une fois construite.
        QTimer.singleShot(0, lambda: self.window is not None and shiboken6.isValid(self.window)
                          and self._show_toggle_style(key))

    def _show_toggle_style(self, key: str | None = None):
        """Toggles comme les autres types (demande de l'utilisateur, 2026-11-11) : la section ne montre que le style
        ÉDITÉ (choisi dans le volet des variantes) ; le choix du style par cartes n'y est plus (le volet le fait)."""
        window = self.window
        if window is None:
            return
        if key is None:
            styles = [s["key"] for s in toggle_style_list(window.settings)]
            key = self.store.editing.get("toggle")
            if key not in styles:
                key = window.settings.get("toggle_style") if window.settings.get("toggle_style") in styles else \
                    (styles[0] if styles else None)
        for node in window.findChildren(v2._LazyNode):
            if node.node.toggle_key:
                node.setVisible(node.node.toggle_key == key)
        for picker in window.findChildren(v2._ToggleStylePicker):
            frame = picker
            while frame is not None and not isinstance(frame, v2._TableFrame):
                frame = frame.parentWidget()
            (frame or picker).setVisible(False)

    def edit_variant(self, type_name: str, variant: str, save: bool = True):
        """Edite une autre variante du type : ses valeurs passent dans les champs, l'apercu la montre."""
        if save:
            self.save_pending()
        self.store.editing[type_name] = variant
        if type_name == "toggle":                    # ses clés (toggle<N>_*) sont déjà dans les champs
            self._refresh_variant_bar()
            return
        window = self.window
        values = {k: v for k, v in self.store.load().items() if tp.theme_key(k)
                  and tp.theme_key(k)[0] == type_name}
        window.external_values(values)
        window._apply_look(window.settings, values)          # fenetre et apercu : la variante editee
        window._last_live_snapshot = None
        self._refresh_variant_bar()

    def _refresh_preview(self, _settings: dict):
        """Couleurs, polices, échelle : les boutons gardent les couleurs de leur construction, l'aperçu est refait."""
        keys = getattr(self.window, "live_changed_keys", None) or ()
        if any(k == "colors" or k.startswith("font_") or k == "ui_scale" for k in keys):
            self.preview.show_section(self.preview._section, force=True)
            self._refresh_variant_bar()
            return
        variants = self.preview.tools()
        if isinstance(variants, VariantList):        # aperçus de la variante éditée : en direct
            prefix = tp.TYPE_PREFIXES[variants.type_name]
            if any(k.startswith(prefix) for k in keys):
                variants.refresh_values(_settings)
            if any(k.startswith("variant_sel_") for k in keys):
                variants.refresh_selection(_settings)

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
        if self.server is None and not self.listeners:
            return
        keys = getattr(self.window, "live_changed_keys", None) or ()
        values = {k: settings[k] for k in keys if k in settings and tp.theme_key(k)}
        if not values:
            return
        # La variante editee de chaque type voyage avec : chaque appli ne prend que celle qu'elle utilise.
        variants = self.store.edited_variants({tp.theme_key(k)[0] for k in values})
        if self.server is not None:
            self.server.broadcast(self.name, values, variants)
        for listener in self.listeners:
            listener(self.name, values, variants)


def initial_preset() -> str:
    """Preset a ouvrir : le dernier edite, sinon celui de fm_browser, sinon le premier (cree s'il n'y en a aucun)."""
    names = list(tp.list_presets())
    for name in (_load_window_geometry(LAST_PRESET_KEY), theme_in_use(load_settings())):
        if name and tp.find_preset(name) is not None:
            return tp.load_preset(tp.find_preset(name))["nom"]
    if names:
        return names[0]
    return tp.new_preset("Preset", load_settings())

