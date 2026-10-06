import config as _config
import json
import os
import sys
from pathlib import Path
from typing import Any
from PySide6.QtCore import (
    QByteArray, QPoint, QRectF, Qt, QTimer, Signal,
)
from PySide6.QtGui import (
    QColor,
    QFont,
    QPainter,
    QPainterPath,
    QPen,
    QPixmap,
)
from PySide6.QtWidgets import (
    QApplication,
    QDialog,
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)
from app_style import (
    C,
    INSPECTOR_TITLE,
    PREVIEW_STACK_TITLE,
    SMOOTHING_CHOICES,
    apply_dwm_frame,
    auto_family_for_role,
    ITEM_FONT_ROLE_LABELS,
    resize_hit_test,
    start_native_move,
)
from settings_lut import LUT_HELP_TEXT, LutTestImagesField
from settings_theme import _set_button_radius, _set_input_radius, _set_text_role, _text_label  # noqa: F401
from settings_store import (
    DEFAULT_SETTINGS,
    M,
    _PRESETS_PATH,
    _coerce_corner_radius,
    _coerce_side_enabled,
    _load_presets,
    _load_window_geometry,
    _resolve_color_value,
    _save_presets,
    _save_window_geometry,
    _subsection_left_margin,
    _sync_dynamic_M,
    _sync_slider_style,
    _sync_title_level_style,
    _title_color,
    _title_font,
    _title_gap,
    _title_gap_next,
    _title_indent,
    load_settings,
    save_settings,
)
from settings_widgets import (
    _TableFrame,
    _TABLE_DIMS,
    _set_table_dims,
    _set_table_inner_border,
    _AppOrCustomColorField,
    _Btn,
    _DualFontSelectField,
    _FontSelectField,
    _MiniSlider,
    _OverrideSmoothingField,
    _RatioSliderField,
    _ResizeBadgePositionField,
    _RowBorderField,
    _SelectField,
    _SliderField,
    _Toggle,
    _ToggleStylePicker,
    _qfont,
    _restyle_table_row,
    _sync_toggle_style,
    _table_frame,
)
from settings_sections import (
    _CellPaddingField,
    _ColorGrid,
    _CompactAppOrCustomColorField,
    _CornerRadiusField,
    _DoubleClickBox,
    _FONT_ROLES,
    _ControlsTable,
    _GeoTable,
    _InnerLineField,
    _HamburgerButton,
    _HeaderColorField,
    _ITEM_TEXT_FIELD_ATTR,
    _ITEM_TEXT_FIELD_SPECS,
    _PresetListRow,
    _SMOOTHING_STEPS,
    _SimpleFontTable,
    _TYPE_LINKED_KEYS,
    _TablePreview,
    _ToggleSideColorsField,
    _font_choices,
    _read_override_field_raw,
)
from settings_colorpicker import (
    _CheckSquare,
    _ColorField,
)
from settings_layout import (
    _ResizableTableHeader,
    _TABLE_HEAD,
    _TableRow,
    _set_active_loading_window,
    _section_host,
    _FlatColumnResizer,
    _Section,
    _SubSection,
    _TabStrip,
    _build_flat_table,
    _build_font_gabarit_row,
    _build_override_flat_table,
    _flat_tables,
    _lock_min_height,
    _make_accordion,
    _section_preview_wrap,
    _set_flat_tables_style,
    _seed_flat_tables_style,
    _flat_tables_padding,
    _make_gap_spacer,
    _reflow_all,
    _refresh_gap_spacers,
    _stack_subsections,
    _table_row,
    _table_header,
    _table_cell,
    _wire_resizable_columns,
    _register_cells_table,
)


# ==========================================================================
# Fenetre principale (frameless, chrome propre a cette fenetre).
# ==========================================================================

class _SettingsTitleBar(QWidget):
    closeClicked = Signal()

    def __init__(self, dialog: QDialog, parent=None, title: str = "Parametres generaux"):
        super().__init__(parent)
        self._dialog = dialog
        self.setFixedHeight(28)
        self.setObjectName("SettingsTitleBar")
        self.setAttribute(Qt.WA_StyledBackground, True)
        self.setStyleSheet(
            f"#SettingsTitleBar {{ background: {M['titlebar_bg']}; border-bottom: 1px solid {M['panel_border']}; }}"
        )
        layout = QHBoxLayout(self)
        layout.setContentsMargins(10, 0, 0, 0)
        layout.setSpacing(9)
        import previews as pb_previews

        dot = QLabel()
        dot.setFixedSize(9, 9)
        # Icone perso (voir Settings > ICONES > General, UI_ICON_SETTINGS_
        # GEAR) si l'utilisateur en a choisi une, sinon le carre neutre
        # d'origine — voir la remarque de l'utilisateur, "cette icone sera
        # aussi utilisee sur la fenetre de settings elle-meme avant le
        # titre dans la barre de navigation".
        custom_gear = pb_previews.custom_ui_icon_pixmap(pb_previews.UI_ICON_SETTINGS_GEAR, 9)
        if custom_gear is not None:
            dot.setPixmap(custom_gear)
            dot.setStyleSheet("background: transparent;")
        else:
            dot.setStyleSheet(f"border: 1px solid {M['dot_border']}; background: transparent;")
        layout.addWidget(dot)
        title = QLabel(title)
        _set_text_role(title, "window_title")
        layout.addWidget(title)
        layout.addStretch(1)
        self.dirty_label = QLabel("")
        self.dirty_label.setFont(_qfont(10, 400, mono=True))
        layout.addWidget(self.dirty_label)
        self.close_btn = QPushButton("×")
        self.close_btn.setFixedSize(26, 20)
        self.close_btn.setCursor(Qt.ArrowCursor)
        self.close_btn.setFocusPolicy(Qt.NoFocus)
        self.close_btn.setFlat(True)
        self.close_btn.setFont(_qfont(11, 400, mono=True))
        self.close_btn.setStyleSheet(
            "QPushButton { background: transparent; border: none; padding: 0; color: " + M["close_fg"] + "; }"
            "QPushButton:hover { background: " + M["close_hover_bg"] + "; color: " + M["close_hover_fg"] + "; }"
        )
        self.close_btn.clicked.connect(self.closeClicked.emit)
        layout.addWidget(self.close_btn)
        self.set_dirty(False)

    def set_dirty(self, dirty: bool):
        self.dirty_label.setText("modifications non enregistrees" if dirty else "a jour")
        self.dirty_label.setStyleSheet(
            f"color: {M['dirty_fg'] if dirty else M['clean_fg']}; background: transparent;"
        )

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            start_native_move(self._dialog)
            event.accept()
        else:
            super().mousePressEvent(event)

class _NoSqueezeScrollArea(QScrollArea):
    """QScrollArea dont le widget interne suit la LARGEUR de la fenetre
    (comme un setWidgetResizable(True) classique) mais ne descend JAMAIS en
    hauteur sous sa taille naturelle (minimumSizeHint, recalculee a chaque
    fois — suit donc aussi un contenu qui change, par exemple une section
    repliee) : au-dela, une scrollbar verticale apparait a la place d'un
    tassement des lignes.

    Necessaire car setWidgetResizable(True) seul redimensionne bel et bien
    son widget a la taille EXACTE du viewport, y compris en dessous de son
    minimumSizeHint — resize() ne respecte le minimum d'un widget QUE
    lorsqu'il est appele PAR le systeme de layout/redimensionnement
    interactif d'une fenetre, jamais sur un appel direct comme celui-ci.
    Le contenu se retrouvait alors tasse (chaque ligne ecrasee en dessous
    de sa hauteur minimale, jusqu'au chevauchement de texte) au lieu de
    faire apparaitre une scrollbar — voir la remarque de l'utilisateur,
    capture a l'appui. Corrige ici en reprenant la main juste APRES le
    redimensionnement automatique de Qt, pour forcer un plancher."""

    def resizeEvent(self, event):
        super().resizeEvent(event)
        widget = self.widget()
        if widget is not None:
            target_height = max(self.viewport().height(), widget.minimumSizeHint().height())
            if widget.height() != target_height or widget.width() != self.viewport().width():
                widget.resize(self.viewport().width(), target_height)

class _PanelFrame(QWidget):
    """Conteneur racine de tout le contenu du dialogue (titlebar, toolbar,
    corps — ~300 widgets descendants) : fond + bordure + coins arrondis
    peints a la main, PAS en QSS (voir setColors/setRadius). Un widget avec
    un tel nombre de descendants coute cher a restyler via setStyleSheet —
    Qt doit repasser en cascade sur tout le sous-arbre a chaque appel
    (comportement documente), mesure a ~20ms ici — rejoue par
    SettingsWindow._apply_panel_radius a CHAQUE glisser d'un slider de
    couleur qui touche 'well'/'topbar' (voir _refresh_dynamic_colors) :
    l'essentiel de la latence residuelle signalee par l'utilisateur, une
    fois les autres pastilles de couleur deja court-circuitees. Peindre
    directement ne coute qu'un repaint de ce SEUL widget, quel que soit le
    nombre de descendants."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._bg = "#000000"
        self._border = "#000000"
        self._radius = 0

    def setColors(self, bg: str, border: str):
        if (bg, border) != (self._bg, self._border):
            self._bg, self._border = bg, border
            self.update()

    def setRadius(self, radius: int):
        radius = max(0, int(radius))
        if radius != self._radius:
            self._radius = radius
            self.update()

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing, True)
        rect = QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)
        path = QPainterPath()
        path.addRoundedRect(rect, self._radius, self._radius)
        p.fillPath(path, QColor(self._bg))
        p.setPen(QPen(QColor(self._border), 1))
        p.drawPath(path)
        p.end()

class _OmitListField(QWidget):
    """Liste de noms à masquer, avec les mêmes commandes + et − que Configuration."""

    changed = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(4)
        self.list = QListWidget(self)
        self.list.setFixedHeight(96)
        layout.addWidget(self.list)
        buttons = QHBoxLayout()
        buttons.setSpacing(4)
        for label, callback in (("+", self._add), ("-", self._remove_selected)):
            button = QPushButton(label, self)
            button.setFixedSize(24, 20)
            button.setFont(_qfont(13, 700))
            button.clicked.connect(callback)
            buttons.addWidget(button)
        buttons.addStretch(1)
        layout.addLayout(buttons)
        self.refresh_style()

    def refresh_style(self):
        self.list.setStyleSheet(
            f"QListWidget {{ background: {C['well']}; color: {C['text']}; "
            f"border: 1px solid {C['border']}; border-radius: 0px; }}"
            "QListWidget::item { padding: 2px 4px; }"
            f"QListWidget::item:selected {{ background: {C['sel_idle']}; }}"
        )
        for button in self.findChildren(QPushButton):
            button.setStyleSheet(
                f"QPushButton {{ background: {C['btn']}; color: {C['text']}; "
                f"border: 1px solid {C['btn_border']}; border-radius: 3px; padding: 0px; }}"
                f"QPushButton:hover {{ background: {C['btn_hover']}; }}"
            )

    def _add(self):
        name, ok = QInputDialog.getText(self, "Ajouter", "Nom à omettre :")
        name = name.strip()
        if ok and name and name.casefold() not in {value.casefold() for value in self.values()}:
            self.list.addItem(name)
            self.changed.emit()

    def _remove_selected(self):
        selected = self.list.selectedItems()
        for item in selected:
            self.list.takeItem(self.list.row(item))
        if selected:
            self.changed.emit()

    def values(self) -> list[str]:
        return [self.list.item(index).text() for index in range(self.list.count())]

    def set_values(self, values):
        self.list.clear()
        self.list.addItems([str(value) for value in (values or [])])

def _omit_file_values(settings: dict) -> list[str]:
    """Affiche les anciennes extensions comme règles *.ext modifiables."""
    names = settings.get("application_omit_file_names") or []
    extensions = settings.get("application_omit_extensions") or []
    if isinstance(names, str):
        names = names.replace(";", ",").split(",")
    if isinstance(extensions, str):
        extensions = [extensions]
    values = [str(name).strip() for name in names if str(name).strip()]
    for raw in extensions:
        for extension in str(raw).replace(",", " ").replace(";", " ").split():
            suffix = extension.casefold().removeprefix("*.").lstrip(".")
            if suffix:
                values.append(f"*.{suffix}")
    return list(dict((value.casefold(), value) for value in values).values())

class SettingsWindow(QDialog):
    """Fenetre de parametres, reproduction fidele de la maquette html
    "Parametres generaux". Chaque changement se previsualise en direct sur
    la fenetre principale (settingsChanged), sans toucher au disque ;
    Enregistrer persiste (settingsSaved)."""

    settingsChanged = Signal(dict)
    settingsSaved = Signal(dict)

    # Deux fenetres de reglages (voir PipelineBrowser.open_settings) :
    # "visuel" = aspect de l'application (onglets General + Colonnes, sans
    # la section Application) ; "general" = tout le reste (section
    # Application seule). "tout" = ancien comportement (tests, sondes).
    # "visuel" construit TOUS les controles (_current_values/
    # _connect_live_updates les lisent sans garde) : la section Application
    # y est simplement rangee dans un conteneur cache. "general" ne construit
    # que la section Application (voir _light).
    MODES = ("tout", "visuel", "general")
    _MODE_TITLES = {"tout": "Parametres generaux", "visuel": "Parametres visuels",
                    "general": "Parametres generaux"}
    _GENERAL_SECTIONS = ("_section_application", "_section_omit", "_section_lut")

    def __init__(self, parent=None, mode: str = "tout"):
        super().__init__(parent)
        self._mode = mode if mode in self.MODES else "tout"
        # Mode "general" : seule la section Application est construite (une
        # poignee de champs, au lieu des ~5000 widgets de la fenetre
        # complete) ; _current_values/_apply_values_to_controls/
        # _connect_live_updates ne touchent alors qu'a ses champs.
        self._light = self._mode == "general"
        _set_active_loading_window(self)
        self.setWindowFlags(Qt.Dialog | Qt.FramelessWindowHint)
        self.setAttribute(Qt.WA_TranslucentBackground, True)
        # 1020 (largeur maquette) - 284 (panneau "Apercu en direct", supprime
        # a la demande de l'utilisateur) : la page de gauche n'a plus besoin
        # de toute cette largeur.
        self.resize(760, 820)
        # Redimensionnable par l'utilisateur (voir nativeEvent ci-dessous,
        # meme mecanisme que PipelineBrowser) : la fenetre peut descendre
        # librement jusqu'a cette taille (une simple limite de confort pour
        # la barre d'outils/le bas de fenetre, pas pour le contenu) — voir
        # _NoSqueezeScrollArea, qui fait apparaitre une scrollbar plutot que
        # de tasser les lignes de reglage des que le contenu deploye ne
        # tient plus dans l'espace restant.
        self.setMinimumSize(640, 480)
        # Reapplique la taille/position de la derniere fermeture (voir
        # _load_window_geometry) — DOIT venir apres resize/setMinimumSize
        # ci-dessus, qui ne servent alors que de valeurs par defaut au tout
        # premier lancement (aucun fichier d'etat encore ecrit).
        geometry_b64 = _load_window_geometry(self._geometry_key())
        if geometry_b64:
            try:
                self.restoreGeometry(QByteArray.fromBase64(geometry_b64.encode("ascii")))
            except (ValueError, TypeError):
                pass
        elif self._mode == "general" and parent is not None:
            # Premiere ouverture : decalee pour ne pas masquer la fenetre visuelle.
            self.move(parent.x() + 80, parent.y() + 60)

        self.settings = load_settings()
        _set_table_dims(self.settings.get("table_dims") or {})
        self._original_settings = json.loads(json.dumps(self.settings))
        # Avant toute construction : chaque zone de saisie lit ce rayon a sa creation.
        _set_input_radius(int(self.settings.get("input_radius", 0)))
        _set_button_radius(int(self.settings.get("button_radius", 0)))
        # Idem pour les tableaux sans entete (voir _prestyle_flat_frame) : un
        # tableau style APRES avoir ete rempli re-style tout son contenu.
        _seed_flat_tables_style(
            int(self.settings.get("table_radius", 0)),
            (_coerce_side_enabled(self.settings.get("table_border_enabled", True)),
             {k: _resolve_color_value(v, self.settings["colors"])
              for k, v in (self.settings.get("table_border") or {}).items()},
             int(self.settings.get("table_border_thickness", 1))))
        self._seed_table_inner_border()
        self._saved = False
        self._dirty = False
        self._style_sig = self._style_signature(self.settings)
        # Liste vivante des logiciels AJOUTES (voir _section_logiciels) —
        # pas de "control" Qt unique ne peut porter une LISTE de longueur
        # variable (contrairement au reste de _current_values()), gardee a
        # part et re-injectee explicitement dans _current_values()/
        # _apply_values_to_controls.
        self._custom_softwares: list[dict] = [
            dict(e) for e in self.settings.get("custom_softwares", []) if isinstance(e, dict) and e.get("key")
        ]
        self._removed_softwares: set = set(self.settings.get("removed_softwares", []))
        # Tableaux "fermes" SANS entete de colonnes (voir _build_flat_table)
        # — un _FlatColumnResizer par tableau, ajoute ici par chaque
        # _section_xxx qui en construit un : permet de tous les retrouver
        # d'un coup (voir _apply_columns_resizable, qui doit les activer/
        # desactiver comme les tableaux A entete).
        self._flat_resizers: list[_FlatColumnResizer] = []
        # Preset EN COURS D'UTILISATION (voir la remarque de l'utilisateur,
        # "au lieu de personnalise en haut de la fenetre de settings, mets
        # le preset en cours d'utilisation") : celui configure comme preset
        # par defaut (voir load_settings/DEFAULT_SETTINGS.default_preset)
        # s'il en existe un et qu'il a bien ete applique — "Personnalise"
        # sinon (comportement INCHANGE, aucun preset par defaut configure).
        default_preset = self.settings.get("default_preset")
        self._current_preset = default_preset if default_preset in _load_presets() else "Personnalise"
        # AVANT toute construction de widget ci-dessous (_build_toolbar/
        # _build_content/_build_bottom_bar) : ces methodes lisent M au
        # moment ou elles construisent chaque widget, donc M doit deja
        # refleter les couleurs REGLABLES courantes (voir _sync_dynamic_M)
        # pour que la fenetre s'ouvre directement dans le bon habillage,
        # sans sursaut visuel au premier changement de couleur.
        _sync_dynamic_M(self.settings["colors"])
        # Idem pour l'habillage des sliders (Geometrie > Slider, voir
        # _SLIDER_STYLE) : chaque _MiniSlider construit plus bas (Application/
        # Entetes/Geometrie...) doit deja lire le bon style des sa creation.
        _sync_slider_style(self.settings)
        # Idem pour le style des toggles (Toggles > Style, voir _TOGGLE_STYLE).
        _sync_toggle_style(self.settings)
        # Idem pour la police/couleur/retrait des titres de _Section/
        # _SubSection (General > TITRE, voir _TITLE_LEVEL_STYLE) : chaque
        # _Section/_SubSection construite plus bas doit deja lire le bon
        # style des sa creation.
        _sync_title_level_style(self.settings)

        # Voir la meme remarque dans l'ancienne fenetre : le rafraichissement
        # (previsualisation complete sur la fenetre principale) est lourd,
        # on le differe donc toujours de 30ms au fil d'un glisser de slider.
        self._live_pending = False
        self._live_timer = QTimer(self)
        self._live_timer.setInterval(30)
        self._live_timer.setSingleShot(True)
        self._live_timer.timeout.connect(self._flush_live_apply)

        # PERFORMANCES (voir la remarque de l'utilisateur, "il y a des
        # problemes de performances quand on modifie les parametres des
        # settings ... geometrie/zone de saisie, geometrie/boutons") :
        # _apply_dropdown_radius/_apply_button_radius reappliquent un
        # setStyleSheet sur des DIZAINES de widgets (voir leurs corps) —
        # cable EN DIRECT sur valueChanged, un simple glisser de slider
        # rejouait ce cout a CHAQUE pas intermediaire. Meme debounce 30ms
        # que _live_timer ci-dessus, mais SEPARE (portee/semantique
        # differente : celui-ci ne fait QUE re-styler des widgets DEJA
        # construits, jamais emettre settingsChanged) — ne retient QUE la
        # DERNIERE valeur en attente pendant un glisser.
        self._dropdown_radius_pending: int | None = None
        # Bordures de tableaux : un cran de slider restyle tous les tableaux
        # (~300 ms) ; appliquees apres une courte pause pour ne pas figer le
        # slider (les ticks de souris s'accumulaient, d'ou des sauts 1 -> 3).
        self._table_border_timer = QTimer(self)
        self._table_border_timer.setInterval(60)
        self._table_border_timer.setSingleShot(True)
        self._table_border_timer.timeout.connect(self._flush_table_border)
        self._dropdown_radius_timer = QTimer(self)
        self._dropdown_radius_timer.setInterval(30)
        self._dropdown_radius_timer.setSingleShot(True)
        self._dropdown_radius_timer.timeout.connect(self._flush_dropdown_radius)
        self._button_radius_pending: int | None = None
        self._button_radius_timer = QTimer(self)
        self._button_radius_timer.setInterval(30)
        self._button_radius_timer.setSingleShot(True)
        self._button_radius_timer.timeout.connect(self._flush_button_radius)

        self.panel = panel = _PanelFrame(self)
        self._apply_panel_radius(int(self.settings.get("window_radius", 0)))
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.addWidget(panel)

        root = QVBoxLayout(panel)
        root.setContentsMargins(1, 1, 1, 1)
        root.setSpacing(0)

        self.titlebar = _SettingsTitleBar(self, title=self._MODE_TITLES[self._mode])
        self.titlebar.closeClicked.connect(self.reject)
        root.addWidget(self.titlebar)

        root.addWidget(self._build_toolbar())
        # Conteneur cache des widgets construits mais non affiches dans ce mode.
        self._hidden_holder = QWidget(panel)
        self._hidden_holder.hide()
        main_tabbar = self._build_main_tabbar()
        root.addWidget(main_tabbar)

        # PERFORMANCES : construction de HAUT EN BAS. Rattacher a un parent un
        # sous-arbre deja construit re-applique les feuilles de style de TOUS
        # ses widgets (QStyleSheetStyle::repolish, ~35us/widget) : construit
        # de bas en haut, chaque widget etait re-style une fois par niveau
        # d'assemblage. La pile (puis chaque page, chaque section, voir
        # _build_content/_SECTION_HOST) est donc deja a sa place AVANT d'etre
        # remplie.
        self._main_stack = QStackedWidget(panel)
        root.addWidget(self._main_stack, 1)
        if self._light:
            # Tableaux > Padding des cellules / Colonnes dimensionnables :
            # normalement appliques par des sections absentes de ce mode.
            sides = self.settings.get("table_cell_padding") or {}
            pad = {k: max(0, min(32, int(sides.get(k, 0)))) for k in ("left", "top", "right", "bottom")}
            if self.settings.get("table_cell_padding_linked", False):
                pad = dict.fromkeys(pad, pad["left"])
            with _flat_tables_padding((pad["left"], pad["top"], pad["right"], pad["bottom"])):
                content_page = self._build_content(self._main_stack)
            for resizer in self._flat_resizers:
                resizer.setResizable(bool(self.settings.get("columns_resizable", True)))
        else:
            content_page = self._build_content(self._main_stack)
        self._main_stack.addWidget(content_page)                # 0: General
        if self._light:
            # Une seule page (Application) : pas d'onglets ni de Colonnes.
            main_tabbar.hide()
        else:
            self._main_stack.addWidget(self._build_columns_page(self._main_stack))  # 1: Colonnes

        root.addWidget(self._build_bottom_bar())

        self._connect_live_updates()
        self._preview_now()
        self._report_loading_step(None)
        _set_active_loading_window(None)

    # -- barre d'outils (preset) --

    def _build_toolbar(self) -> QWidget:
        bar = QWidget()
        self._toolbar_bar = bar
        bar.setFixedHeight(40)
        bar.setStyleSheet(f"background: {M['toolbar_bg']};")
        layout = QHBoxLayout(bar)
        layout.setContentsMargins(14, 0, 14, 0)
        layout.setSpacing(8)

        tag = QLabel("Preset")
        _set_text_role(tag, "tag")
        layout.addWidget(tag)

        # Double-clic pour renommer (en plus du bouton "Renommer" ci-dessous
        # — voir la remarque de l'utilisateur, capture a l'appui).
        self.preset_box = _DoubleClickBox()
        self.preset_box.setObjectName("PresetBox")
        self.preset_box.setAttribute(Qt.WA_StyledBackground, True)
        self.preset_box.setFixedSize(260, 26)
        self.preset_box.doubleClicked.connect(self._rename_preset)
        preset_l = QHBoxLayout(self.preset_box)
        preset_l.setContentsMargins(9, 0, 9, 0)
        preset_l.setSpacing(8)
        self.preset_name_label = QLabel()
        self.preset_name_label.setFont(_qfont(12, 400))
        preset_l.addWidget(self.preset_name_label, 1)
        self.preset_dot = QLabel()
        self.preset_dot.setFixedSize(6, 6)
        preset_l.addWidget(self.preset_dot)
        layout.addWidget(self.preset_box)

        # "Enregistrer" remplace l'ancien bouton "Renommer" — le double-clic
        # sur la boite de preset couvre deja le renommage (voir plus haut) ;
        # ce bouton sauvegarde directement les valeurs courantes dans le
        # preset actif (ou ouvre "Nouveau preset..." s'il n'y en a pas
        # encore un de charge) — voir la remarque de l'utilisateur, capture
        # a l'appui.
        # Rayon : suivi automatique de Geometrie > Boutons (voir settings_theme).
        save_btn = _Btn("Enregistrer", M["btn_bg"], M["btn_border"], M["btn_fg"], M["btn_hover"], height=26)
        save_btn.clicked.connect(self._save_current_preset)
        layout.addWidget(save_btn)
        self._preset_save_btn = save_btn

        divider = QFrame()
        divider.setFixedSize(1, 16)
        divider.setStyleSheet(f"background: {M['panel_border']};")
        layout.addWidget(divider)

        # Un seul bouton icone remplace "Enregistrer sous…"/"Ouvrir un
        # preset…" (voir la remarque de l'utilisateur, capture a l'appui) :
        # ouvre une liste (voir _open_preset_popup) qui permet a la fois de
        # charger un preset existant, d'en supprimer un (croix), et d'en
        # enregistrer un nouveau ("+ Nouveau preset…", en tete de liste).
        self._preset_menu_btn = _HamburgerButton("")
        self._preset_menu_btn.setFixedSize(26, 26)
        self._preset_menu_btn.setCursor(Qt.ArrowCursor)
        self._preset_menu_btn.setFocusPolicy(Qt.NoFocus)
        self._preset_menu_btn.setStyleSheet(
            f"QPushButton {{ background: {M['btn_bg']}; border: 1px solid {M['btn_border']}; color: {M['btn_fg']}; }}"
            f"QPushButton:hover {{ background: {M['btn_hover']}; }}"
        )
        self._preset_menu_btn.clicked.connect(self._open_preset_popup)
        layout.addWidget(self._preset_menu_btn)

        layout.addStretch(1)

        path_label = QLabel(f"{_PRESETS_PATH.name} · {_PRESETS_PATH.parent}")
        _set_text_role(path_label, "note_mono")
        layout.addWidget(path_label)

        self._sync_preset_box()
        return bar

    def _sync_preset_box(self):
        border = M["dirty_border"] if self._dirty else M["field_border"]
        radius = self.geo_table.input_radius_field.value() if hasattr(self, "geo_table") else 0
        self.preset_box.setStyleSheet(
            f"#PresetBox {{ background: {M['field_bg']}; border: 1px solid {border}; "
            f"border-radius: {radius}px; }}"
        )
        self.preset_name_label.setText(self._current_preset + (" *" if self._dirty else ""))
        self.preset_name_label.setStyleSheet(f"color: {M['value_fg']}; background: transparent;")
        dot_color = M["dirty_dot"] if self._dirty else M["clean_dot"]
        self.preset_dot.setStyleSheet(f"background: {dot_color};")

    def _refresh_default_preset_options(self):
        """Reconstruit les options de "Preset par defaut" (General >
        Application) depuis _load_presets() A JOUR -- appelee apres CHAQUE
        creation/suppression/renommage de preset (voir _save_preset_as/
        _delete_preset/_rename_preset), et une fois a l'ouverture de la
        fenetre. AVANT ce correctif, cette liste etait figee a l'ouverture
        (voir _SelectField.setOptions, qui lit toujours la liste EN
        DIRECT a chaque clic -- pas besoin de reconstruire le widget) :
        creer ou supprimer un preset sans refermer la fenetre laissait
        cette liste perimee -- voir la remarque de l'utilisateur sur la
        refonte des presets."""
        preset_names = ["(Aucun)"] + sorted(_load_presets().keys())
        self.default_preset_field.setOptions(preset_names)

    def _open_preset_popup(self):
        """Liste des presets (voir _PresetListRow) : "+ Nouveau preset…" en
        tete (enregistre les valeurs courantes sous un nouveau nom), puis
        chaque preset existant — clic sur le nom pour le charger, sur la
        croix pour le supprimer. Remplace les 2 anciens boutons "Enregistrer
        sous…"/"Ouvrir un preset…" (voir la remarque de l'utilisateur,
        capture a l'appui)."""
        popup = QWidget(self, Qt.Popup)
        popup.setObjectName("PresetPopup")
        popup.setAttribute(Qt.WA_StyledBackground, True)
        popup.setStyleSheet(f"#PresetPopup {{ background: {M['toolbar_bg']}; border: 1px solid {M['field_border']}; }}")
        layout = QVBoxLayout(popup)
        layout.setContentsMargins(1, 1, 1, 1)
        layout.setSpacing(0)

        # radius=self.geo_table... directement (popup rebati a chaque
        # ouverture, self.geo_table existe forcement deja a ce stade —
        # inutile de le suivre en direct comme les boutons persistants, voir
        # _apply_button_radius).
        new_btn = _Btn("+  Nouveau preset…", "transparent", "", M["value_fg"], M["btn_hover"],
                       height=30, weight=500, padding="0 12px", align_left=True)
        new_btn.clicked.connect(lambda: (popup.close(), self._save_preset_as()))
        layout.addWidget(new_btn)

        presets = _load_presets()
        if presets:
            divider = QFrame()
            divider.setFixedHeight(1)
            divider.setStyleSheet(f"background: {M['field_border']};")
            layout.addWidget(divider)
            for name in presets:
                row = _PresetListRow(name)
                row.clicked.connect(lambda n=name: (popup.close(), self._load_preset(n, _load_presets())))
                row.deleteClicked.connect(lambda n=name: self._delete_preset(n, popup))
                layout.addWidget(row)
        else:
            empty = QLabel("(aucun preset enregistre)")
            empty.setFont(_qfont(11, 400))
            empty.setStyleSheet(f"color: {M['group_note']}; background: transparent; padding: 6px 12px;")
            layout.addWidget(empty)

        popup.setFixedWidth(max(self._preset_menu_btn.width(), 220))
        popup.adjustSize()
        popup.move(self._preset_menu_btn.mapToGlobal(QPoint(0, self._preset_menu_btn.height())))
        popup.show()

    def _delete_preset(self, name: str, popup: QWidget):
        presets = _load_presets()
        presets.pop(name, None)
        _save_presets(presets)
        if self._current_preset == name:
            self._current_preset = "Personnalise"
            self._sync_preset_box()
        self._refresh_default_preset_options()
        popup.close()
        # Rouvre aussitot la liste a jour (sans le preset supprime) : plus
        # pratique que refermer purement et simplement si l'utilisateur
        # veut enchainer plusieurs suppressions.
        self._open_preset_popup()

    def _load_preset(self, name: str, presets: dict):
        data = presets.get(name)
        if not data:
            return
        # _apply_values_to_controls fusionne deja data par-dessus
        # DEFAULT_SETTINGS (voir sa docstring) : pas besoin de le refaire ici.
        self._apply_values_to_controls(data)
        self._current_preset = name
        self._dirty = False
        self.titlebar.set_dirty(False)
        self._sync_preset_box()
        self._preview_now()

    def _save_preset_as(self):
        name, ok = QInputDialog.getText(self, "Enregistrer sous", "Nom du preset :")
        name = name.strip()
        if not ok or not name:
            return
        presets = _load_presets()
        if name in presets and QMessageBox.question(
            self, "Enregistrer sous", f'"{name}" existe deja. Le remplacer ?',
            QMessageBox.Yes | QMessageBox.No, QMessageBox.No,
        ) != QMessageBox.Yes:
            return
        presets[name] = self._current_values()
        _save_presets(presets)
        self._current_preset = name
        self._dirty = False
        self.titlebar.set_dirty(False)
        self._sync_preset_box()
        self._refresh_default_preset_options()

    def _save_current_preset(self):
        """Bouton "Enregistrer" de la barre a outils : sauvegarde les
        valeurs courantes dans le preset actif ; si aucun preset n'est
        charge (etat "Personnalise"), se rabat sur "Nouveau preset..."."""
        if not self._current_preset or self._current_preset == "Personnalise":
            self._save_preset_as()
            return
        presets = _load_presets()
        presets[self._current_preset] = self._current_values()
        _save_presets(presets)
        self._dirty = False
        self.titlebar.set_dirty(False)
        self._sync_preset_box()

    def _rename_preset(self):
        new_name, ok = QInputDialog.getText(self, "Renommer", "Nouveau nom :", text=self._current_preset)
        new_name = new_name.strip()
        if not ok or not new_name or new_name == self._current_preset:
            return
        presets = _load_presets()
        if self._current_preset in presets:
            presets[new_name] = presets.pop(self._current_preset)
            _save_presets(presets)
        self._current_preset = new_name
        self._sync_preset_box()
        self._refresh_default_preset_options()

    def _apply_column_type_overrides_to_controls(self):
        """Reapplique Colonnes > Type/Projets/Sous-projets (voir
        _build_column_override_page) depuis self.settings, pour LES 3
        colonnes — meme principe que le reste de _apply_values_to_
        controls, appelee juste apres (Valeurs par defaut/chargement d'un
        preset)."""
        if not hasattr(self, "_type_fields"):
            return
        for title in (
            "Type", "Projets", "Sous-projet", PREVIEW_STACK_TITLE,
            "Logiciels", "IN", "OVER", "OUT", INSPECTOR_TITLE,
        ):
            if title in self._type_fields:
                self._apply_column_overrides_to_controls_for(title)
        self._apply_column_type_preview()

    def _apply_selection_clone_values_to_controls(self):
        """Reapplique les etats "clones" de Focus (Non focus/Survol/Non
        selectionne, voir _build_selection_clone_subsection/
        _selection_clone_values) depuis self.settings — champs EAGER
        (onglet General), toujours construits, jamais de garde hasattr
        necessaire ici (contrairement a _apply_step_badge_values_to_
        controls, page "Projets" paresseuse)."""
        for state in ("unfocus", "hover", "idle"):
            getattr(self, f"item_selection_{state}_padding_toggle").setChecked(
                bool(self.settings.get(f"item_selection_{state}_padding_override", False)))
            getattr(self, f"item_selection_{state}_padding_field").setValue(
                bool(self.settings.get(f"item_selection_{state}_padding_linked", False)),
                self.settings.get(f"item_selection_{state}_padding") or {})
            getattr(self, f"item_selection_{state}_border_toggle").setChecked(
                bool(self.settings.get(f"item_selection_{state}_border_override", False)))
            getattr(self, f"item_selection_{state}_border_field").setValue(
                _coerce_side_enabled(self.settings.get(f"item_selection_{state}_border_enabled", False)),
                self.settings.get(f"item_selection_{state}_border") or {})
            getattr(self, f"item_selection_{state}_radius_toggle").setChecked(
                bool(self.settings.get(f"item_selection_{state}_radius_override", False)))
            getattr(self, f"item_selection_{state}_radius_field").setValue(
                bool(self.settings.get(f"item_selection_{state}_radius_linked", True)),
                _coerce_corner_radius(self.settings.get(f"item_selection_{state}_radius", 0)))
            getattr(self, f"item_selection_{state}_edge_border_toggle").setChecked(
                bool(self.settings.get(f"item_selection_{state}_edge_border_override", False)))
            getattr(self, f"item_selection_{state}_edge_border_field").setChecked(
                bool(self.settings.get(f"item_selection_{state}_edge_border", True)))

    def _apply_step_badge_values_to_controls(self):
        """Reapplique Colonnes > Projets > Colonnes > "Icone de niveaux"
        (voir _build_column_override_page/_step_badge_values) depuis
        self.settings — no-op si cette page (paresseuse, voir _on_columns_
        tab_changed) n'a jamais ete visitee dans cette session (rien a
        reappliquer : le prochain _build_column_override_page("Projets", ...)
        la seedera de toute facon depuis self.settings, deja a jour ICI)."""
        if not hasattr(self, "step_badge_width_field"):
            return
        self.step_badge_width_field.setValue(int(self.settings.get("step_badge_width", 18)))
        self.step_badge_height_field.setValue(int(self.settings.get("step_badge_height", 18)))
        self.step_badge_border_field.setValue(
            _coerce_side_enabled(self.settings.get("step_badge_border_enabled", False)),
            self.settings.get("step_badge_border") or {})
        self.step_badge_border_thickness_field.setValue(int(self.settings.get("step_badge_border_thickness", 1)))
        self.step_badge_radius_field.setValue(
            bool(self.settings.get("step_badge_radius_linked", True)),
            _coerce_corner_radius(self.settings.get("step_badge_radius", 9)))
        self.step_badge_color_base2_field.setValue(self.settings.get("step_badge_color_base2", "#5c6368"))
        self.step_badge_color_base3_field.setValue(self.settings.get("step_badge_color_base3", "#5c6368"))
        self.step_badge_color_base4_field.setValue(self.settings.get("step_badge_color_base4", "#3f6f9f"))
        self.step_badge_color_base5_field.setValue(self.settings.get("step_badge_color_base5", "#3f6f9f"))
        self.step_badge_color_base6_field.setValue(self.settings.get("step_badge_color_base6", "#d9822b"))
        self.step_badge_color_basen_field.setValue(self.settings.get("step_badge_color_basen", "#5c6368"))
        self.step_badge_text_color_base2_field.setValue(self.settings.get("step_badge_text_color_base2", "#eef2f5"))
        self.step_badge_text_color_base3_field.setValue(self.settings.get("step_badge_text_color_base3", "#eef2f5"))
        self.step_badge_text_color_base4_field.setValue(self.settings.get("step_badge_text_color_base4", "#eef2f5"))
        self.step_badge_text_color_base5_field.setValue(self.settings.get("step_badge_text_color_base5", "#eef2f5"))
        self.step_badge_text_color_base6_field.setValue(self.settings.get("step_badge_text_color_base6", "#eef2f5"))
        self.step_badge_text_color_basen_field.setValue(self.settings.get("step_badge_text_color_basen", "#eef2f5"))
        self.step_badge_offset_x_field.setValue(int(self.settings.get("step_badge_offset_x", 4)))
        self.step_badge_offset_y_field.setValue(int(self.settings.get("step_badge_offset_y", 0)))
        self.step_badge_font_family_field.setValue(self.settings.get("step_badge_font_family") or "Systeme")
        self.step_badge_font_bold_field.setChecked(bool(self.settings.get("step_badge_font_bold", True)))
        self.step_badge_font_smoothing_field.setValue(
            bool(self.settings.get("step_badge_font_smoothing_enabled", False)),
            self.settings.get("step_badge_font_smoothing", "current"))
        self.step_badge_border_smoothing_field.setChecked(bool(self.settings.get("step_badge_border_smoothing", True)))

    def _apply_column_overrides_to_controls_for(self, title: str):
        """Reapplique Colonnes > ... depuis self.settings, POUR LE TITRE
        donne uniquement (voir _apply_column_type_overrides_to_controls,
        qui boucle sur les 3). Chaque champ est protege par `if key in f`
        car Projets/Sous-projet n'ont pas toutes les lignes de "Type" (voir
        _build_column_override_page, sous-section Texte reduite pour ces 2
        colonnes)."""
        f = self._type_fields.get(title)
        if not f:
            return
        toggles = self._type_toggles.get(title, {})
        overrides = self._override_store("overrides", title)
        enabled_map = self._override_store("enabled", title)
        linked_map = self._override_store("linked", title)

        def seed(key, default):
            return overrides.get(key, self.settings.get(key, default))

        for key, toggle in toggles.items():
            toggle.setChecked(bool(enabled_map.get(key, False)))

        f["header_visible"].setChecked(bool(seed("header_visible", True)))
        f["header_height"].setValue(int(seed("header_height", 26)))
        f["header_padding"].setValue(int(seed("header_padding", 0)))
        f["header_color"].setValue(seed("header_color", "skinN1"), self.settings["colors"])
        f["header_radius"].setValue(
            bool(linked_map.get("header_radius", True)), _coerce_corner_radius(seed("header_radius", 0)))
        f["header_border_enabled"].setValue(
            _coerce_side_enabled(seed("header_border_enabled", False)), seed("header_border", {}) or {})
        f["header_border_thickness"].setValue(int(seed("header_border_thickness", 1)))
        if "item_column_width" in f:
            f["item_column_width"].setValue(int(seed("item_column_width", 180)))
        f["column_padding"].setValue(
            bool(linked_map.get("column_padding", True)), seed("column_padding", {}) or {})
        f["column_border_enabled"].setValue(
            _coerce_side_enabled(seed("column_border_enabled", True)), seed("column_border", {}) or {})
        f["column_border_thickness"].setValue(int(seed("column_border_thickness", 1)))
        f["column_border_radius"].setValue(
            bool(linked_map.get("column_border_radius", True)), _coerce_corner_radius(seed("column_border_radius", 0)))
        f["column_bg_color"].setValue(seed("column_bg_color", "@skinN2"))
        if "item_font_family" in f:
            f["item_font_family"].setValue(seed("item_font_family", "") or "Systeme")
        if "item_font_bold" in f:
            f["item_font_bold"].setChecked(bool(seed("item_font_bold", False)))
        for spec in _ITEM_TEXT_FIELD_SPECS:
            if spec.key in f:
                spec.seed_widget(f[spec.key], seed(spec.key, spec.default))
        if "item_row_height" in f:
            f["item_row_height"].setValue(int(seed("item_row_height", 25)))
        if "item_row_spacing" in f:
            f["item_row_spacing"].setValue(int(seed("item_row_spacing", 1)))
        # Texte/Image/Selection (item_*) : n'existent PAS pour
        # PREVIEW_STACK_TITLE/INSPECTOR_TITLE (voir _build_column_override_
        # page, aucune de ces 3 sous-sections n'y est construite) — memes
        # clefs absentes de `f` que pour Projets/Sous-projet, mais TOUTES
        # d'un coup ici (pas de `if key in f` ligne par ligne comme au-
        # dessus, plus simple).
        if title not in (PREVIEW_STACK_TITLE, INSPECTOR_TITLE):
            f["item_row_border_enabled"].setValue(
                bool(seed("item_row_border_enabled", False)),
                seed("item_row_border_color", "@ligne"), int(seed("item_row_border_thickness", 1)))
            f["item_image_padding"].setValue(
                bool(linked_map.get("item_image_padding", True)), seed("item_image_padding", {}) or {})
            f["item_image_border_enabled"].setValue(
                _coerce_side_enabled(seed("item_image_border_enabled", False)), seed("item_image_border", {}) or {})
            f["item_image_border_thickness"].setValue(int(seed("item_image_border_thickness", 1)))
            f["item_image_radius"].setValue(
                bool(linked_map.get("item_image_radius", True)), _coerce_corner_radius(seed("item_image_radius", 0)))
            f["item_image_ratio"].setValue(int(round(float(seed("item_image_ratio", 1.0)) * 100)))
            f["item_selection_focus_color"].setValue(seed("item_selection_focus_color", "#3f6f9f"))
            f["item_selection_unfocus_color"].setValue(seed("item_selection_unfocus_color", "#2e3338"))
            f["item_hover_color"].setValue(seed("item_hover_color", "#232729"))
            f["item_idle_color"].setValue(seed("item_idle_color", "@itemIdle"))
            f["item_selection_padding"].setValue(
                bool(linked_map.get("item_selection_padding", False)), seed("item_selection_padding", {}) or {})
            f["item_selection_border_enabled"].setValue(
                _coerce_side_enabled(seed("item_selection_border_enabled", False)),
                seed("item_selection_border", {}) or {})
            f["item_selection_radius"].setValue(
                bool(linked_map.get("item_selection_radius", True)),
                _coerce_corner_radius(seed("item_selection_radius", 0)))
            f["item_selection_edge_border"].setChecked(bool(seed("item_selection_edge_border", True)))

    def _apply_application_values(self):
        """Champs de la section Application (seuls construits en mode
        "general", voir _light), depuis self.settings."""
        self.root_field.setText(self.settings.get("root_path", DEFAULT_SETTINGS["root_path"]))
        self.default_preset_field.setValue(self.settings.get("default_preset") or "(Aucun)")
        self.scale_field.setValue(int(self.settings.get("ui_scale", 100)))
        self.auto_collapse_set_columns_field.setChecked(
            bool(self.settings.get("auto_collapse_set_columns", True)))
        self.omit_file_names_field.set_values(_omit_file_values(self.settings))
        self.omit_dir_names_field.set_values(self.settings.get("application_omit_dir_names"))
        self.window_radius_toggle.setChecked(int(self.settings.get("window_radius", 0)) > 0)
        self.lut_images_field.set_values(
            self.settings.get("lut_test_images"), self.settings.get("lut_default_image") or "",
            self.settings.get("lut_image_curves"))

    def _application_values(self) -> dict:
        return {
            "root_path": self.root_field.text().strip() or DEFAULT_SETTINGS["root_path"],
            "default_preset": "" if self.default_preset_field.value() == "(Aucun)" else self.default_preset_field.value(),
            "ui_scale": self.scale_field.value(),
            "auto_collapse_set_columns": self.auto_collapse_set_columns_field.isChecked(),
            "application_omit_file_names": self.omit_file_names_field.values(),
            "application_omit_extensions": [],
            "application_omit_dir_names": self.omit_dir_names_field.values(),
            "window_radius": self._window_radius_value(),
            "lut_test_images": self.lut_images_field.values(),
            "lut_default_image": self.lut_images_field.default(),
            "lut_image_curves": self.lut_images_field.curves(),
        }

    def _apply_values_to_controls(self, data: dict):
        """Reapplique un dict complet de reglages sur TOUS les controles —
        utilise par Valeurs par defaut et le chargement d'un preset.

        Remplace D'ABORD self.settings par (une copie de) `data` en entier,
        AVANT de synchroniser les widgets : _current_values() fusionne les
        valeurs des widgets par-dessus self.settings pour les cles sans UI
        (couleurs non exposees, detail des polices figees..., voir la
        remarque de tete de fichier) — sans ce remplacement prealable,
        self.settings serait reste bloque sur son contenu de CONSTRUCTION
        (le fichier charge au demarrage), et "Valeurs par defaut"/le
        chargement d'un preset auraient eu l'air de fonctionner (les
        widgets suivent bien) sans jamais reellement s'appliquer aux cles
        gelees — bug reel confirme en repassant un preset "as-is" par ce
        chemin (voir git diff sur pipeline_settings.presets.json)."""
        self.settings = json.loads(json.dumps(DEFAULT_SETTINGS))
        data = json.loads(json.dumps(data))
        # Migration "header_edges" (ancien nom) -> "header_border_enabled"
        # (nouveau, voir DEFAULT_SETTINGS/_section_headers, la remarque de
        # l'utilisateur "renomme le parametre 'cadre des entetes' ->
        # 'Bordure'") : SEULEMENT si `data` n'a pas deja la nouvelle cle —
        # sans cette migration explicite AVANT le merge, un preset ecrit
        # avant ce renommage perdrait silencieusement sa config de bordure
        # d'entete (DEFAULT_SETTINGS ne connait plus "header_edges" du
        # tout, self.settings.update(data) la laisserait donc simplement de
        # cote plutot que de la reporter sur la nouvelle cle).
        if "header_border_enabled" not in data and "header_edges" in data:
            data["header_border_enabled"] = data["header_edges"]
        self.settings.update(data)
        if self._light:
            self._apply_application_values()
            return

        for level in (1, 2, 3, 4, 5):
            prefix = f"title_level{level}"
            self.__dict__[f"{prefix}_font_family_field"].setValue(
                self.settings.get(f"{prefix}_font_family") or "Systeme")
            self.__dict__[f"{prefix}_font_bold_field"].setChecked(bool(self.settings.get(f"{prefix}_font_bold", True)))
            self.__dict__[f"{prefix}_font_italic_field"].setChecked(
                bool(self.settings.get(f"{prefix}_font_italic", False)))
            self.__dict__[f"{prefix}_font_size_field"].setValue(int(self.settings.get(f"{prefix}_font_size", 10)))
            self.__dict__[f"{prefix}_font_smoothing_field"].setValue(
                bool(self.settings.get(f"{prefix}_font_smoothing_enabled", False)),
                self.settings.get(f"{prefix}_font_smoothing", "current"))
            self.__dict__[f"{prefix}_font_color_field"].setValue(self.settings.get(f"{prefix}_font_color", "#d6d9dc"))
            self.__dict__[f"{prefix}_indent_field"].setValue(int(self.settings.get(f"{prefix}_indent", 0)))
            for gap_key in ("gap_collapsed", "gap_expanded", "gap_next"):
                self.__dict__[f"{prefix}_{gap_key}_field"].setValue(int(self.settings.get(f"{prefix}_{gap_key}", 0)))
        self._apply_title_level_style()

        self._custom_softwares = [
            dict(e) for e in self.settings.get("custom_softwares", []) if isinstance(e, dict) and e.get("key")
        ]
        self._removed_softwares = set(self.settings.get("removed_softwares", []))
        if hasattr(self, "_logiciels_section"):
            self._rebuild_logiciels_table()

        self._apply_application_values()
        for key, entry in self.font_table.rows.items():
            conf = self.settings.get(key) or {}
            family = conf.get("family") or "Systeme"
            entry["field"].setValue(family)
            shown = family if family != "Systeme" else entry["auto"]
            entry["preview"].setFont(QFont(shown, 10))
            entry["custom"] = bool(conf.get("custom", False))
            smoothing = conf.get("smoothing") or "current"
            if smoothing not in SMOOTHING_CHOICES:
                smoothing = "current"
            entry["smoothing_field"].setValue(_SMOOTHING_STEPS.index(smoothing))
        for real_key, hexval in (self.settings.get("colors") or {}).items():
            if real_key in self.color_grid._fields_by_real_key:
                self.color_grid._sync_key(real_key, hexval)
        self.header_visible_field.setChecked(bool(self.settings.get("header_visible", True)))
        self.header_height_field.setValue(int(self.settings.get("header_height", 26)))
        self.header_padding_field.setValue(int(self.settings.get("header_padding", 0)))
        self.header_color_field.setValue(self.settings.get("header_color", "skinN1"), self.settings["colors"])
        self.header_radius_field.setValue(
            bool(self.settings.get("header_radius_linked", True)), _coerce_corner_radius(self.settings.get("header_radius", 0)))
        self.header_border_field.setValue(
            _coerce_side_enabled(self.settings.get("header_border_enabled") or self.settings.get("header_edges") or {},
                                 default=False),
            self.settings.get("header_border") or {})
        self.header_border_thickness_field.setValue(int(self.settings.get("header_border_thickness", 1)))
        self.header_icon_right_padding_field.setValue(int(self.settings.get("header_icon_right_padding", 0)))
        self.header_font_family_field.setValue(self.settings.get("header_font_family") or "Systeme")
        self.header_font_bold_field.setChecked(bool(self.settings.get("header_font_bold", True)))
        self.header_font_italic_field.setChecked(bool(self.settings.get("header_font_italic", False)))
        self.header_font_color_field.setValue(self.settings.get("header_font_color", "#9aa1a7"))
        self.header_font_size_field.setValue(int(self.settings.get("header_font_size", 10)))
        self.header_font_smoothing_field.setValue(
            bool(self.settings.get("header_font_antialias_override_enabled", False)),
            self.settings.get("header_font_antialias_override", "current"))
        self.item_column_width_field.setValue(int(self.settings.get("item_column_width", 180)))
        self.column_gap_field.setValue(max(0, int(self.settings.get("column_gap", 0))))
        self.column_padding_field.setValue(
            bool(self.settings.get("column_padding_linked", True)), self.settings.get("column_padding") or {})
        self.column_border_field.setValue(
            _coerce_side_enabled(self.settings.get("column_border_enabled", True)),
            self.settings.get("column_border") or {})
        self.column_border_thickness_field.setValue(int(self.settings.get("column_border_thickness", 1)))
        self.column_border_radius_field.setValue(
            bool(self.settings.get("column_border_radius_linked", True)),
            _coerce_corner_radius(self.settings.get("column_border_radius", 0)))
        self.column_bg_color_field.setValue(self.settings.get("column_bg_color", "@skinN2"))
        self.resize_badge_position_field.setValue(
            self.settings.get("resize_badge_position", "bottom_right"),
            int(self.settings.get("resize_badge_offset_x", 8)),
            int(self.settings.get("resize_badge_offset_y", 8)))
        self.resize_badge_font_field.setValue(self.settings.get("resize_badge_font_family") or "Systeme")
        self.resize_badge_font_bold_field.setChecked(bool(self.settings.get("resize_badge_font_bold", True)))
        self.resize_badge_font_italic_field.setChecked(bool(self.settings.get("resize_badge_font_italic", False)))
        self.resize_badge_font_size_field.setValue(int(self.settings.get("resize_badge_font_size", 11)))
        self.resize_badge_font_smoothing_field.setValue(
            bool(self.settings.get("resize_badge_font_smoothing_enabled", False)),
            self.settings.get("resize_badge_font_smoothing", "current"))
        self.resize_badge_text_color_field.setValue(self.settings.get("resize_badge_text_color", "#d6d9dc"))
        self.resize_badge_bg_color_field.setValue(self.settings.get("resize_badge_bg_color", "#202326"))
        self.resize_badge_border_field.setValue(
            _coerce_side_enabled(self.settings.get("resize_badge_border_enabled", True)),
            self.settings.get("resize_badge_border") or {})
        self.resize_badge_border_thickness_field.setValue(int(self.settings.get("resize_badge_border_thickness", 1)))
        self.resize_badge_border_radius_field.setValue(
            bool(self.settings.get("resize_badge_border_radius_linked", True)),
            _coerce_corner_radius(self.settings.get("resize_badge_border_radius", 4)))
        self.item_font_field.setValue(self.settings.get("item_font_family") or "Systeme")
        self.item_font_size_field.setValue(int(self.settings.get("item_font_size", 10)))
        self.item_font_bold_field.setChecked(bool(self.settings.get("item_font_bold", False)))
        self.item_font_italic_field.setChecked(bool(self.settings.get("item_font_italic", False)))
        self.item_antialias_field.setValue(
            bool(self.settings.get("item_antialias_override_enabled", False)),
            self.settings.get("item_antialias_override", "current"))
        self.item_header_gap_field.setValue(int(self.settings.get("item_header_gap", 0)))
        for spec in _ITEM_TEXT_FIELD_SPECS:
            spec.seed_widget(getattr(self, _ITEM_TEXT_FIELD_ATTR[spec.key]), self.settings.get(spec.key, spec.default))
        self.item_row_border_field.setValue(
            bool(self.settings.get("item_row_border_enabled", False)),
            self.settings.get("item_row_border_color", "@ligne"),
            int(self.settings.get("item_row_border_thickness", 1)))
        self.item_image_padding_field.setValue(
            bool(self.settings.get("item_image_padding_linked", True)),
            self.settings.get("item_image_padding") or {},
        )
        self.item_image_border_field.setValue(
            _coerce_side_enabled(self.settings.get("item_image_border_enabled", False)),
            self.settings.get("item_image_border") or {})
        self.item_image_border_thickness_field.setValue(int(self.settings.get("item_image_border_thickness", 1)))
        self.item_image_radius_field.setValue(
            bool(self.settings.get("item_image_radius_linked", True)),
            _coerce_corner_radius(self.settings.get("item_image_radius", 0)))
        self.item_image_ratio_field.setValue(
            int(round(float(self.settings.get("item_image_ratio", 1.0)) * 100)))
        self.preview_padding_field.setValue(
            bool(self.settings.get("preview_padding_linked", True)), self.settings.get("preview_padding") or {})
        self.preview_radius_field.setValue(
            bool(self.settings.get("preview_radius_linked", True)),
            _coerce_corner_radius(self.settings.get("preview_radius", 0)))
        self.preview_title_zone_height_field.setValue(int(self.settings.get("preview_title_zone_height", 52)))
        self.preview_title_font_size_field.setValue(int(self.settings.get("preview_title_font_size", 26)))
        self.preview_title_font_color_field.setValue(self.settings.get("preview_title_font_color", "#d6d9dc"))
        self.preview_title_font_family_field.setValue(self.settings.get("preview_title_font_family") or "Systeme")
        self.preview_title_font_bold_field.setChecked(bool(self.settings.get("preview_title_font_bold", True)))
        self.preview_title_font_italic_field.setChecked(bool(self.settings.get("preview_title_font_italic", False)))
        self.preview_title_font_smoothing_field.setValue(
            bool(self.settings.get("preview_title_font_smoothing_enabled", False)),
            self.settings.get("preview_title_font_smoothing", "current"))
        self.preview_title_padding_field.setValue(
            bool(self.settings.get("preview_title_padding_linked", True)),
            self.settings.get("preview_title_padding") or {})
        self.preview_status_font_size_field.setValue(int(self.settings.get("preview_status_font_size", 10)))
        self.preview_status_font_color_field.setValue(self.settings.get("preview_status_font_color", "#d6d9dc"))
        self.preview_status_font_color_idle_field.setValue(
            self.settings.get("preview_status_font_color_idle", "#5f666b"))
        self.preview_status_font_family_field.setValue(self.settings.get("preview_status_font_family") or "Systeme")
        self.preview_status_font_bold_field.setChecked(bool(self.settings.get("preview_status_font_bold", True)))
        self.preview_status_font_italic_field.setChecked(bool(self.settings.get("preview_status_font_italic", False)))
        self.preview_status_font_smoothing_field.setValue(
            bool(self.settings.get("preview_status_font_smoothing_enabled", False)),
            self.settings.get("preview_status_font_smoothing", "current"))
        self.preview_status_padding_field.setValue(
            bool(self.settings.get("preview_status_padding_linked", True)),
            self.settings.get("preview_status_padding") or {})
        self.preview_toggle_width_field.setValue(int(self.settings.get("preview_toggle_width", 22)))
        self.preview_toggle_height_field.setValue(int(self.settings.get("preview_toggle_height", 22)))
        self.preview_toggle_bg_field.setValue(self.settings.get("preview_toggle_bg_color", "#960f1114"))
        self.preview_toggle_border_field.setValue(
            _coerce_side_enabled(self.settings.get("preview_toggle_border_enabled", False)),
            self.settings.get("preview_toggle_border") or {})
        self.preview_toggle_border_thickness_field.setValue(
            int(self.settings.get("preview_toggle_border_thickness", 1)))
        self.preview_toggle_radius_field.setValue(int(self.settings.get("preview_toggle_radius", 4)))
        self.preview_toggle_x_field.setValue(int(self.settings.get("preview_toggle_x", 8)))
        self.preview_toggle_y_field.setValue(int(self.settings.get("preview_toggle_y", 34)))
        self.shortcut_font_family_field.setValue(self.settings.get("shortcut_font_family", "") or "Systeme")
        self.shortcut_font_bold_field.setChecked(bool(self.settings.get("shortcut_font_bold", False)))
        self.shortcut_font_italic_field.setChecked(bool(self.settings.get("shortcut_font_italic", False)))
        self.shortcut_color_field.setValue(self.settings.get("shortcut_color", "#8fb4d5"))
        self.shortcut_font_size_field.setValue(int(self.settings.get("shortcut_font_size", 11)))
        self.shortcut_font_smoothing_field.setValue(
            bool(self.settings.get("shortcut_font_smoothing_enabled", False)),
            self.settings.get("shortcut_font_smoothing", "current"))
        self.item_selection_focus_field.setValue(self.settings.get("item_selection_focus_color", "#3f6f9f"))
        self.item_selection_unfocus_field.setValue(self.settings.get("item_selection_unfocus_color", "#2e3338"))
        self.item_hover_field.setValue(self.settings.get("item_hover_color", "#232729"))
        self.item_idle_field.setValue(self.settings.get("item_idle_color", "@itemIdle"))
        self.item_selection_padding_field.setValue(
            bool(self.settings.get("item_selection_padding_linked", False)),
            self.settings.get("item_selection_padding") or {},
        )
        self.item_selection_border_field.setValue(
            _coerce_side_enabled(self.settings.get("item_selection_border_enabled", False)),
            self.settings.get("item_selection_border") or {})
        self.item_selection_radius_field.setValue(
            bool(self.settings.get("item_selection_radius_linked", True)),
            _coerce_corner_radius(self.settings.get("item_selection_radius", 0)))
        self.item_selection_edge_border_field.setChecked(bool(self.settings.get("item_selection_edge_border", True)))
        self._apply_selection_clone_values_to_controls()
        self._apply_column_type_overrides_to_controls()
        self._apply_step_badge_values_to_controls()
        self.columns_resizable_toggle.setChecked(bool(self.settings.get("columns_resizable", True)))
        self.geo_table.head.setColumnWidths(self.settings.get("geo_table_columns") or [])
        self.font_table.head.setColumnWidths(self.settings.get("font_table_columns") or [])
        _set_table_dims(self.settings.get("table_dims") or {})
        for frame in self.findChildren(_TableFrame):
            if frame._dims_applied:
                dims = _TABLE_DIMS.get(frame.dimsKey())
                if dims:
                    frame.applyDims(dims)
        self.toggle_style_field.setValue(self.settings.get("toggle_style", "toggle1"))
        self._apply_toggle_shape_values("toggle1")
        self._apply_toggle_shape_values("toggle2")
        self.geo_table.input_frame_toggle.setChecked(bool(self.settings.get("input_frame", True)))
        self.geo_table.input_radius_field.setValue(int(self.settings.get("input_radius", 0)))
        self.geo_table.button_frame_toggle.setChecked(bool(self.settings.get("button_frame", True)))
        self.geo_table.button_radius_field.setValue(int(self.settings.get("button_radius", 0)))
        self.table_border_field.setValue(
            _coerce_side_enabled(self.settings.get("table_border_enabled", True)),
            self.settings.get("table_border") or {})
        self.table_border_thickness_field.setValue(int(self.settings.get("table_border_thickness", 1)))
        for axis, field in (("h", self.table_inner_h_field), ("v", self.table_inner_v_field)):
            field.setValue(self.settings[f"table_inner_{axis}_enabled"],
                           self.settings[f"table_inner_{axis}_color"],
                           self.settings[f"table_inner_{axis}_thickness"])
        self.table_radius_field.setValue(int(self.settings.get("table_radius", 0)))
        self.cell_padding_field.setValue(
            bool(self.settings.get("table_cell_padding_linked", False)),
            self.settings.get("table_cell_padding") or {},
        )
        self.table_head_color_field.setValue(
            self.settings.get("table_head_color", "tableHead"), self.settings["colors"])
        self.slider_thumb_width_field.setValue(int(self.settings.get("slider_thumb_width", 3)))
        self.slider_thumb_height_field.setValue(int(self.settings.get("slider_thumb_height", 14)))
        self.slider_thumb_color_field.setValue(self.settings.get("slider_thumb_color", "#8fb4d5"))
        self.slider_thumb_border_field.setValue(
            _coerce_side_enabled(self.settings.get("slider_thumb_border_enabled", True)),
            self.settings.get("slider_thumb_border") or {})
        self.slider_thumb_radius_field.setValue(
            bool(self.settings.get("slider_thumb_radius_linked", True)),
            _coerce_corner_radius(self.settings.get("slider_thumb_radius", 0)))
        self.slider_track_height_field.setValue(int(self.settings.get("slider_track_height", 3)))
        self.slider_track_fill_field.setValue(self.settings.get("slider_track_fill_color", "#3f6f9f"))
        self.slider_track_empty_field.setValue(self.settings.get("slider_track_empty_color", "#25292d"))
        self.slider_track_border_field.setValue(
            _coerce_side_enabled(self.settings.get("slider_track_border_enabled", True)),
            self.settings.get("slider_track_border") or {})
        self.slider_track_radius_field.setValue(
            bool(self.settings.get("slider_track_radius_linked", True)),
            _coerce_corner_radius(self.settings.get("slider_track_radius", 0)))
        # Couleurs deja synchronisees sur color_grid ci-dessus : reapplique
        # aussi tout ce qui, dans cette fenetre, suit desormais une couleur
        # reglable plutot qu'une valeur fixe de M (voir _refresh_dynamic_colors)
        # — sans ca, "Valeurs par defaut"/le chargement d'un preset changent
        # bien les pastilles mais laissent la fenetre elle-meme dans son
        # ancien habillage.
        # table_head_color_field.setValue() ci-dessus ne rejoue PAS le
        # rendu (voir sa docstring, meme raison que _CellPaddingField/
        # _apply_toggle_shape_values : eviter un rendu intermediaire par
        # reglage pendant que TOUS sont encore en train d'etre restaures) —
        # a la charge de l'appelant, ici, une fois tout repose.
        self._apply_table_head_color(self.table_head_color_field.value())
        self._apply_column_preview()
        self._apply_item_preview()
        self._refresh_dynamic_colors(self.settings["colors"])
        self._apply_slider_style()

    # -- onglets principaux (General / Colonnes) --

    def _build_main_tabbar(self) -> QWidget:
        """General/Colonnes : General regroupe tout ce qui existait avant
        (Application/Polices/Couleurs/Entetes/Geometrie, voir _build_content,
        inchange) — Colonnes est le nouvel onglet, lui-meme subdivise en
        Type/Projets/Sous-projets (voir _build_columns_page). Principe pose
        par l'utilisateur : les Parametres generaux restent prioritaires,
        chaque page de Colonnes ne fait qu'en SURCHARGER certaines valeurs
        pour son propre type de colonne — l'UI de ces surcharges reste a
        construire au fil des demandes suivantes, ces pages sont pour
        l'instant de simples emplacements vides (voir _build_columns_page)."""
        bar = QWidget()
        bar.setStyleSheet(f"background: {M['toolbar_bg']}; border-bottom: 1px solid {M['panel_border']};")
        layout = QHBoxLayout(bar)
        layout.setContentsMargins(20, 0, 20, 0)
        self._main_tabs = _TabStrip(["General", "Colonnes"])
        layout.addWidget(self._main_tabs)
        self._main_tabs.changed.connect(self._on_main_tab_changed)
        return bar

    def _build_columns_page(self, parent: QWidget | None = None) -> QWidget:
        """Onglet Colonnes : barre d'onglets internes Type/Projets/Sous-
        projets, chacune avec sa propre page (voir _build_column_type_page —
        seule construite pour l'instant, voir la remarque de l'utilisateur :
        "pour le moment je vais me concentrer que sur l'onglet type"). La
        section "Entetes" (renommee "Colonnes", voir _section_headers) est
        repassee dans l'onglet General, sous Geometrie — voir la remarque
        de l'utilisateur : "deplace la section entetes dans l'onglet
        general juste au dessous de geometrie"."""
        page = QWidget(parent)
        page.setStyleSheet(f"background: {M['panel_bg']};")
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        subbar = QWidget()
        subbar.setStyleSheet(f"background: {M['toolbar_bg']}; border-bottom: 1px solid {M['panel_border']};")
        subbar_l = QHBoxLayout(subbar)
        subbar_l.setContentsMargins(20, 0, 20, 0)
        self._columns_tabs = _TabStrip([
            "Type", "Projets", "INTERMEDIAIRE", PREVIEW_STACK_TITLE,
            "Logiciels", "IN", "OVER", "OUT", INSPECTOR_TITLE,
        ])
        subbar_l.addWidget(self._columns_tabs)
        layout.addWidget(subbar)

        self._columns_stack = QStackedWidget(page)
        layout.addWidget(self._columns_stack, 1)
        # "INTERMEDIAIRE" (onglet, voir la remarque de l'utilisateur, "le
        # tab sous projets doit maintenant se nommer 'INTERMEDIAIRE', et
        # doit controler toutes les colonnes entre celle de projet et
        # focus") surcharge la colonne reelle "Sous-projet" (cle de
        # stockage INCHANGEE, voir pipeline_browser.COLUMN_LABELS/
        # COLUMN_SETTINGS — aucune migration necessaire, les reglages/
        # presets deja enregistres sous "Sous-projet" restent valides) —
        # real_title est la cle de stockage/le titre EFFECTIF de colonne,
        # tab_title reste juste le libelle de l'onglet ci-dessus. Cote
        # pipeline_browser.py (voir Column.style_title/on_selected), CHAQUE
        # niveau d'une chaine CONFIGUREE (nom quelconque, ex. "test1") suit
        # desormais CETTE MEME cle de style "Sous-projet" plutot que de
        # retomber sur le bucket generique "Contenu" — ce tab controle donc
        # bien TOUTES les colonnes intermediaires, pas seulement l'ancienne
        # "Sous-projet" legacy.
        #
        # Type/Projets/INTERMEDIAIRE : PARESSEUX, construits seulement a la
        # premiere visite de leur propre sous-onglet (voir _on_columns_tab_
        # changed) — voir la remarque de l'utilisateur, "peux tu optimiser
        # l'ouverture des settings ?". Mesure (cProfile) : ces 3 pages (un
        # JEU COMPLET de tableaux Colonnes/Entetes/Texte/Selection chacune)
        # totalisent ~1.35s des ~4s que prenait la construction COMPLETE de
        # cette fenetre, payes a CHAQUE ouverture meme quand cet onglet
        # n'est jamais consulte dans la session. _current_values()/
        # _apply_column_type_overrides_to_controls geraient deja ce cas
        # (voir hasattr(self, "_type_fields")/_column_override_values).
        #
        # PREVIEW_STACK_TITLE (voir sa remarque de tete dans app_style.py) :
        # meme cle pour l'onglet ET le titre reel, cette colonne fantome
        # n'ayant jamais eu de "vrai" nom avant elle — voir la remarque de
        # l'utilisateur, "je veux les overrides dans les settings aussi".
        # Reste construite ICI, EAGER (pas dans la liste ci-dessous) :
        # contrairement aux 3 autres, ses champs (self.preview_padding_
        # field...) sont references SANS garde par _connect_live_updates/
        # _current_values (voir leurs docstrings) — les differer aurait
        # demande de re-cabler ces references, pour un gain marginal (une
        # seule page sur 4).
        # Cle = index ABSOLU dans _columns_tabs/_columns_stack (PAS une
        # liste positionnelle 0..N-1 contigue) : PREVIEW_STACK_TITLE
        # (index 3) reste construit EAGER (voir plus bas, sans entree ici)
        # entre les 3 premiers onglets PARESSEUX et les 5 nouveaux ajoutes
        # APRES lui (Logiciels/IN/OVER/OUT/Inspecteur, voir la remarque de
        # l'utilisateur, "ajoute la colonne logiciels dans les settings,
        # ainsi que in over et out, puis la colonne inspecteur") — un dict
        # gere ce "trou" a l'index 3 sans complication, contrairement a une
        # liste positionnelle qui supposait TOUS les onglets PARESSEUX
        # contigus a partir de 0.
        self._columns_subpage_specs = {
            0: ("Type", "Type"),
            1: ("Projets", "Projets"),
            2: ("INTERMEDIAIRE", "Sous-projet"),
            4: ("Logiciels", "Logiciels"),
            5: ("IN", "IN"),
            6: ("OVER", "OVER"),
            7: ("OUT", "OUT"),
            8: (INSPECTOR_TITLE, INSPECTOR_TITLE),
        }
        self._columns_subpage_built: set[int] = set()
        for idx in range(3):
            tab_title, _real_title = self._columns_subpage_specs[idx]
            self._columns_stack.addWidget(self._build_column_placeholder_page(tab_title))
        self._columns_stack.addWidget(
            self._build_column_override_page(PREVIEW_STACK_TITLE, PREVIEW_STACK_TITLE, self._columns_stack))
        for idx in range(4, 9):
            tab_title, _real_title = self._columns_subpage_specs[idx]
            self._columns_stack.addWidget(self._build_column_placeholder_page(tab_title))
        self._columns_tabs.changed.connect(self._on_columns_tab_changed)
        # `_TabStrip` n'emet `changed` que sur un CLIC : le sous-onglet visible
        # par defaut (index 0 = Type) est construit au PREMIER affichage de
        # l'onglet Colonnes (voir _on_main_tab_changed), pas ici — ~2.4s
        # epargnees a chaque ouverture quand cet onglet n'est pas consulte.
        return page

    def _on_main_tab_changed(self, index: int):
        if index == 1:
            # Construit (une seule fois) le sous-onglet affiche, voir
            # _build_columns_page.
            self._on_columns_tab_changed(self._columns_tabs._index)
        self._main_stack.setCurrentIndex(index)

    def _on_columns_tab_changed(self, index: int):
        spec = self._columns_subpage_specs.get(index)
        if spec is not None and index not in self._columns_subpage_built:
            self._columns_subpage_built.add(index)
            tab_title, real_title = spec
            placeholder = self._columns_stack.widget(index)
            self._columns_stack.removeWidget(placeholder)
            placeholder.deleteLater()
            self._columns_stack.insertWidget(
                index, self._build_column_override_page(tab_title, real_title, self._columns_stack))
        self._columns_stack.setCurrentIndex(index)

    def _build_column_placeholder_page(self, title: str) -> QWidget:
        """Page vide (plus utilisee par _build_columns_page depuis que
        Projets/Sous-projets ont leur propre page, voir
        _build_column_override_page — gardee au cas ou un futur onglet en
        aurait encore besoin)."""
        page = QWidget()
        page.setStyleSheet(f"background: {M['panel_bg']};")
        layout = QVBoxLayout(page)
        layout.setContentsMargins(20, 18, 18, 26)
        note = QLabel(f"Aucun reglage \"{title}\" pour le moment.")
        _set_text_role(note, "placeholder")
        layout.addWidget(note)
        layout.addStretch(1)
        return page

    def _override_store(self, kind: str, title: str) -> dict:
        """Sous-dict de stockage (overrides/enabled/linked) pour LE TITRE de
        colonne donne (voir _build_column_override_page) — "Type" garde ses
        3 cles historiques (column_type_overrides/column_type_override_
        enabled/column_type_override_linked, jamais renommees pour ne rien
        casser en retro-compatibilite avec les presets/settings.json
        existants) ; "Projets"/"Sous-projet" utilisent les 3 nouvelles cles
        imbriquees par titre (column_overrides_by_title/...), voir
        DEFAULT_SETTINGS."""
        if title == "Type":
            key = {
                "overrides": "column_type_overrides",
                "enabled": "column_type_override_enabled",
                "linked": "column_type_override_linked",
            }[kind]
            return self.settings.get(key) or {}
        key = {
            "overrides": "column_overrides_by_title",
            "enabled": "column_override_enabled_by_title",
            "linked": "column_override_linked_by_title",
        }[kind]
        return (self.settings.get(key) or {}).get(title) or {}

    def _type_override_seed(self, key: str, default, title: str = "Type"):
        """Valeur de depart d'un champ de surcharge (Colonnes > Type/
        Projets/Sous-projets) : la derniere valeur ENREGISTREE pour cette
        surcharge si elle existe (voir _override_store), sinon la valeur
        GENERALE courante (onglet General) — jamais `default` tout court,
        pour qu'activer le toggle la toute premiere fois affiche ce que la
        colonne montre DEJA (voir _apply_column_type_preview), pas une
        valeur arbitraire."""
        overrides = self._override_store("overrides", title)
        if key in overrides:
            return overrides[key]
        return self.settings.get(key, default)

    def _type_override_enabled(self, key: str, title: str = "Type") -> bool:
        return bool(self._override_store("enabled", title).get(key, False))

    def _type_override_linked(self, key: str, title: str = "Type") -> bool:
        linked_map = self._override_store("linked", title)
        return bool(linked_map.get(key, self.settings.get(f"{key}_linked", True)))

    def _build_column_override_page(self, tab_title: str, real_title: str,
                                    parent: QWidget | None = None) -> QWidget:
        """Onglet Colonnes > Type/Projets/Sous-projets : surcharge,
        PARAMETRE PAR PARAMETRE, la section "Colonnes" de l'onglet General
        (voir _section_headers) sur LA colonne `real_title` — meme 4
        tableaux (Colonnes/Entetes/Texte/Selection), memes champs, mais
        chaque ligne est precedee d'un toggle1 (voir
        _build_override_flat_table) : OFF (par defaut) grise la ligne et
        cette colonne suit la valeur GENERALE ; ON active le champ de
        CETTE ligne, dont la valeur SURCHARGE alors la generale — dans
        l'appli reelle (voir pipeline_browser.apply_all_settings/
        COLUMN_TYPE_OVERRIDE_KEYS), et EN DIRECT dans l'apercu de cette
        fenetre pour "Type" uniquement (voir _apply_column_type_preview) —
        voir la remarque de l'utilisateur, "je veux que tu appliques
        exactement le style de colonne (GENERAL/COLONNES) sur la colonne
        TYPE ... un toggle 1 en off, ce qui grisera la ligne ... le fait de
        mettre le toggle en ON overide le parametre et la modification est
        apportee en temps reel", puis "cree la section colonnes comme dans
        general ... place ensuite cette meme section dans les onglets
        projets et sous projets pour y controler les colonnes respectives".

        Texte : "Type" a les 9 lignes completes ; "Projets"/"Sous-projet"
        n'ont pas de champs police/couleur/icone/padtexte dedies dans cette
        page (rendu deja unifie, voir pipeline_browser._paint_unified_row)
        — seules Hauteur/Espacement/Bordure entre les lignes s'y appliquent.

        `self._type_fields[real_title]`/`self._type_toggles[real_title]`
        (par CLE de reglage, pas par ligne d'UI — une ligne "Bordure"
        combinee gouverne 2 cles a la fois, *_border_enabled ET *_border,
        depuis le MEME champ/le MEME toggle, voir _current_values/
        _apply_column_type_preview) gardent la reference a chaque widget
        pour le reste de la fenetre, UN dict PAR colonne reelle."""
        # Construite de haut en bas, deja dans la pile (voir __init__) :
        # page -> scroller -> inner sont rattaches AVANT d'etre remplis.
        page = QWidget(parent)
        page.setStyleSheet(f"background: {M['panel_bg']};")
        outer = QVBoxLayout(page)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        scroller = _NoSqueezeScrollArea(page)
        scroller.setWidgetResizable(True)
        scroller.setFrameShape(QFrame.NoFrame)
        scroller.setStyleSheet(f"background: {M['panel_bg']};")
        outer.addWidget(scroller)
        inner = QWidget(scroller.viewport())
        layout = QVBoxLayout(inner)
        layout.setContentsMargins(20, 18, 18, 26)
        layout.setSpacing(18)

        if not hasattr(self, "_type_fields"):
            self._type_fields: dict[str, dict[str, QWidget]] = {}
            self._type_toggles: dict[str, dict[str, _Toggle]] = {}
        fields: dict[str, QWidget] = {}
        toggles: dict[str, _Toggle] = {}
        self._type_fields[real_title] = fields
        self._type_toggles[real_title] = toggles

        def make_toggle(*keys: str) -> _Toggle:
            # show_label=False : pas de "actif"/"sans" a cote du cadre — voir
            # la remarque de l'utilisateur, "supprime tous les textes (sans
            # et actif) a cote des toggle d'overide".
            toggle = _Toggle(
                self._type_override_enabled(keys[0], real_title), style_override="toggle1", show_label=False)
            for key in keys:
                toggles[key] = toggle
            return toggle

        def seed(key, default):
            return self._type_override_seed(key, default, real_title)

        def linked(key):
            return self._type_override_linked(key, real_title)

        # -- Colonnes (Largeur/Padding/Bordure/Epaisseur/Rayon — "Distance
        # entre colonnes" exclue : un espacement ENTRE colonnes n'a pas de
        # sens pour une seule colonne, voir pipeline_browser.
        # COLUMN_TYPE_OVERRIDE_KEYS) --
        # Largeur par defaut : AUSSI pour PREVIEW_STACK_TITLE (colonnes
        # fantomes "Focus Projet"/"Focus Sous-projet", voir pipeline_
        # browser.PreviewColumn, sa largeur par defaut suit desormais ce
        # reglage — plus calee sur Colonnes > Projets comme avant) — voir la
        # remarque de l'utilisateur, "tu as oublie l'overide des colonnes
        # focus".
        col_width_toggle = make_toggle("item_column_width")
        col_width_field = _SliderField(
            120, 640, int(seed("item_column_width", 180)), slider_width=200, box_width=68)
        fields["item_column_width"] = col_width_field

        col_padding_toggle = make_toggle("column_padding")
        col_padding_field = _CellPaddingField(linked("column_padding"), seed("column_padding", {}) or {})
        fields["column_padding"] = col_padding_field

        col_border_toggle = make_toggle("column_border_enabled", "column_border")
        col_border_field = _ToggleSideColorsField(
            _coerce_side_enabled(seed("column_border_enabled", True)),
            seed("column_border", {}) or {}, self.settings["colors"])
        fields["column_border_enabled"] = col_border_field
        fields["column_border"] = col_border_field

        col_thickness_toggle = make_toggle("column_border_thickness")
        col_thickness_field = _SliderField(
            0, 8, int(seed("column_border_thickness", 1)), slider_width=200, box_width=68)
        fields["column_border_thickness"] = col_thickness_field

        col_radius_toggle = make_toggle("column_border_radius")
        col_radius_field = _CornerRadiusField(
            linked("column_border_radius"), _coerce_corner_radius(seed("column_border_radius", 0)), maximum=20)
        fields["column_border_radius"] = col_radius_field

        col_bg_toggle = make_toggle("column_bg_color")
        col_bg_field = _AppOrCustomColorField(
            seed("column_bg_color", "@skinN2"), self.settings["colors"], swatch_size=24, title="Fond de colonne")
        fields["column_bg_color"] = col_bg_field

        columns_rows = [
            ("Largeur par defaut", col_width_field, col_width_toggle),
            ("Padding", col_padding_field, col_padding_toggle),
            ("Couleur de fond", col_bg_field, col_bg_toggle),
            ("Bordure", col_border_field, col_border_toggle),
            ("Epaisseur de bordure", col_thickness_field, col_thickness_toggle),
            ("Rayon des angles de bordure", col_radius_field, col_radius_toggle),
        ]
        columns_frame, _columns_row_meta, columns_resizer = _build_override_flat_table(columns_rows)
        self._flat_resizers.append(columns_resizer)
        columns_sub = _SubSection("Colonnes", level=2)
        columns_sub.add(columns_frame)

        # -- Entetes --
        visible_toggle = make_toggle("header_visible")
        visible_field = _Toggle(bool(seed("header_visible", True)), style_override="toggle1")
        fields["header_visible"] = visible_field

        height_toggle = make_toggle("header_height")
        height_field = _SliderField(16, 56, int(seed("header_height", 26)), slider_width=200, box_width=68)
        fields["header_height"] = height_field

        padding_toggle = make_toggle("header_padding")
        padding_field = _SliderField(0, 32, int(seed("header_padding", 0)), slider_width=200, box_width=68)
        fields["header_padding"] = padding_field

        color_toggle = make_toggle("header_color")
        color_field = _HeaderColorField(self.settings["colors"], seed("header_color", "skinN1"))
        fields["header_color"] = color_field

        radius_toggle = make_toggle("header_radius")
        radius_field = _CornerRadiusField(
            linked("header_radius"), _coerce_corner_radius(seed("header_radius", 0)), maximum=16)
        fields["header_radius"] = radius_field

        border_toggle = make_toggle("header_border_enabled", "header_border")
        border_field = _ToggleSideColorsField(
            _coerce_side_enabled(seed("header_border_enabled", False)),
            seed("header_border", {}) or {}, self.settings["colors"])
        fields["header_border_enabled"] = border_field
        fields["header_border"] = border_field

        border_thickness_toggle = make_toggle("header_border_thickness")
        border_thickness_field = _SliderField(
            0, 8, int(seed("header_border_thickness", 1)), slider_width=200, box_width=68)
        fields["header_border_thickness"] = border_thickness_field

        # Padding droit des icones + police/gras/couleur/hauteur du titre
        # (voir SettingsWindow._section_headers, ajoutes cote GENERAL) —
        # voir la remarque de l'utilisateur, "mets a jour egalement les
        # colonnes overidees ... avec tous les nouveaux parametres de
        # general".
        icon_padding_toggle = make_toggle("header_icon_right_padding")
        icon_padding_field = _SliderField(
            0, 40, int(seed("header_icon_right_padding", 0)), slider_width=200, box_width=68)
        fields["header_icon_right_padding"] = icon_padding_field

        font_family_toggle = make_toggle("header_font_family")
        font_family_field = _DualFontSelectField(seed("header_font_family", "") or "Systeme", width=130)
        fields["header_font_family"] = font_family_field

        font_bold_toggle = make_toggle("header_font_bold")
        font_bold_field = _Toggle(bool(seed("header_font_bold", True)), style_override="toggle1")
        fields["header_font_bold"] = font_bold_field

        font_color_toggle = make_toggle("header_font_color")
        font_color_field = _AppOrCustomColorField(
            seed("header_font_color", "#9aa1a7"), self.settings["colors"], swatch_size=24, title="Couleur du titre")
        fields["header_font_color"] = font_color_field

        font_size_toggle = make_toggle("header_font_size")
        font_size_field = _SliderField(6, 24, int(seed("header_font_size", 10)), slider_width=200, box_width=68)
        fields["header_font_size"] = font_size_field

        headers_frame, _headers_row_meta, headers_resizer = _build_override_flat_table([
            ("Afficher", visible_field, visible_toggle),
            ("Hauteur des entetes", height_field, height_toggle),
            ("Padding des entetes", padding_field, padding_toggle),
            ("Couleur des entetes", color_field, color_toggle),
            ("Arrondi des angles", radius_field, radius_toggle),
            ("Bordure", border_field, border_toggle),
            ("Epaisseur de bordure", border_thickness_field, border_thickness_toggle),
            ("Padding droit des icones", icon_padding_field, icon_padding_toggle),
            ("Police du titre", font_family_field, font_family_toggle),
            ("Gras du titre", font_bold_field, font_bold_toggle),
            ("Couleur du titre", font_color_field, font_color_toggle),
            ("Hauteur de police du titre", font_size_field, font_size_toggle),
        ])
        self._flat_resizers.append(headers_resizer)
        headers_sub = _SubSection("Entetes", level=2)
        headers_sub.add(headers_frame)

        # Texte/Image/Selection (item_* : rendu par LIGNE, voir
        # pipeline_browser._paint_unified_row) n'ont aucun sens pour
        # PREVIEW_STACK_TITLE (pas une colonne a lignes — voir
        # pipeline_browser.PreviewColumn, empile des _PreviewBlock, pas un
        # RowDelegate) : seuls Colonnes/Entetes s'y appliquent. INSPECTOR_
        # TITLE (voir pipeline_browser.DetailPanel) : MEME raison, ce n'est
        # pas non plus une colonne a lignes (aucun item_row_*/item_image_*/
        # item_selection_* n'y a de sens) — voir la remarque de
        # l'utilisateur, "ajoute ... la colonne inspecteur" (dans les
        # settings, Colonnes/Entetes seulement, comme Focus).
        text_sub = image_sub = selection_sub = title_zone_sub = toggle_sub = None
        if real_title not in (PREVIEW_STACK_TITLE, INSPECTOR_TITLE):
            # -- Texte --
            text_rows = []
            if real_title == "Type":
                font_toggle = make_toggle("item_font_family")
                font_field = _FontSelectField(
                    _font_choices(), seed("item_font_family", "") or "Systeme", width=170, auto_label="Systeme")
                fields["item_font_family"] = font_field
                text_rows.append(("Police", font_field, font_toggle))

                bold_toggle = make_toggle("item_font_bold")
                bold_field = _Toggle(bool(seed("item_font_bold", False)), style_override="toggle1")
                fields["item_font_bold"] = bold_field
                text_rows.append(("Gras", bold_field, bold_toggle))

            # Champs "item_*" simples (couleur/toggle/slider) construits depuis
            # _ITEM_TEXT_FIELD_SPECS : ajouter une entree au registre suffit a
            # la faire apparaitre ici, avec son toggle de surcharge, sans autre
            # modification de cette methode. Seulement pour "Type" : Projets/
            # Sous-projet n'ont pas de champs police/couleur/icone/padding de
            # texte dedies dans cette page (rendu deja unifie, voir
            # pipeline_browser._paint_unified_row).
            if real_title == "Type":
                for spec in _ITEM_TEXT_FIELD_SPECS:
                    toggle = make_toggle(spec.key)
                    field = spec.make_field(seed(spec.key, spec.default), self.settings["colors"], slider_width=170)
                    fields[spec.key] = field
                    text_rows.append((spec.label, field, toggle))
            else:
                for key, label, vmin, vmax, default in (
                    ("item_row_height", "Hauteur de la ligne", 14, 80, 25),
                    ("item_row_spacing", "Espacement entre les lignes", 0, 20, 1),
                ):
                    toggle = make_toggle(key)
                    field = _SliderField(vmin, vmax, int(seed(key, default)), slider_width=170, box_width=68)
                    fields[key] = field
                    text_rows.append((label, field, toggle))

            # "Bordure entre les lignes" (voir _RowBorderField/General ci-dessus) :
            # UN SEUL toggle de surcharge pour les 3 cles a la fois (meme
            # principe que "Bordure"/"column_border_enabled"+"column_border"
            # plus haut), le widget lui-meme porte deja son propre toggle
            # actif/inactif — commun aux 3 colonnes (voir pipeline_browser.
            # _paint_row_border).
            border_toggle = make_toggle(
                "item_row_border_enabled", "item_row_border_color", "item_row_border_thickness")
            border_field = _RowBorderField(
                bool(seed("item_row_border_enabled", False)),
                seed("item_row_border_color", "@ligne"),
                int(seed("item_row_border_thickness", 1)),
                self.settings["colors"],
                thickness_range=(0, 8),
            )
            for key in ("item_row_border_enabled", "item_row_border_color", "item_row_border_thickness"):
                fields[key] = border_field
            text_rows.append(("Bordure entre les lignes", border_field, border_toggle))

            text_frame, _text_row_meta, text_resizer = _build_override_flat_table(text_rows)
            self._flat_resizers.append(text_resizer)
            text_sub = _SubSection("Texte", level=2)
            text_sub.add(text_frame)

            # -- Image (voir General ci-dessus, MEME 4 champs) --
            img_padding_toggle = make_toggle("item_image_padding")
            img_padding_field = _CellPaddingField(
                linked("item_image_padding"), seed("item_image_padding", {}) or {})
            fields["item_image_padding"] = img_padding_field

            img_border_toggle = make_toggle("item_image_border_enabled", "item_image_border")
            img_border_field = _ToggleSideColorsField(
                _coerce_side_enabled(seed("item_image_border_enabled", False)),
                seed("item_image_border", {}) or {}, self.settings["colors"])
            fields["item_image_border_enabled"] = img_border_field
            fields["item_image_border"] = img_border_field

            img_thickness_toggle = make_toggle("item_image_border_thickness")
            img_thickness_field = _SliderField(
                0, 8, int(seed("item_image_border_thickness", 1)), slider_width=170, box_width=68)
            fields["item_image_border_thickness"] = img_thickness_field

            img_radius_toggle = make_toggle("item_image_radius")
            img_radius_field = _CornerRadiusField(
                linked("item_image_radius"), _coerce_corner_radius(seed("item_image_radius", 0)), maximum=20)
            fields["item_image_radius"] = img_radius_field

            img_ratio_toggle = make_toggle("item_image_ratio")
            img_ratio_field = _SliderField(
                20, 500, int(round(float(seed("item_image_ratio", 1.0)) * 100)),
                unit="%", slider_width=170, box_width=68)
            fields["item_image_ratio"] = img_ratio_field

            image_frame, _image_row_meta, image_resizer = _build_override_flat_table([
                ("Padding", img_padding_field, img_padding_toggle),
                ("Bordure", img_border_field, img_border_toggle),
                ("Epaisseur de bordure", img_thickness_field, img_thickness_toggle),
                ("Rayon des angles", img_radius_field, img_radius_toggle),
                ("Ratio (largeur/hauteur)", img_ratio_field, img_ratio_toggle),
            ])
            self._flat_resizers.append(image_resizer)
            image_sub = _SubSection("Image", level=2)
            image_sub.add(image_frame)

            # -- Selection -- (voir General > Colonnes > Selection, MEME
            # structure a 4 sous-sections Focus/Non focus/Survol/Non
            # selectionne — voir la remarque de l'utilisateur, "mets a
            # jour egalement les colonnes overidees ... avec tous les
            # nouveaux parametres de general" puis "les parametres de
            # colonnes ne sont pas a jour, selectionfocus ...").
            focus_toggle = make_toggle("item_selection_focus_color")
            focus_field = _ColorField(
                seed("item_selection_focus_color", "#3f6f9f"), swatch_size=24, title="Selection (focus)")
            fields["item_selection_focus_color"] = focus_field

            sel_padding_toggle = make_toggle("item_selection_padding")
            sel_padding_field = _CellPaddingField(
                linked("item_selection_padding"), seed("item_selection_padding", {}) or {})
            fields["item_selection_padding"] = sel_padding_field

            sel_border_toggle = make_toggle("item_selection_border_enabled", "item_selection_border")
            sel_border_field = _ToggleSideColorsField(
                _coerce_side_enabled(seed("item_selection_border_enabled", False)),
                seed("item_selection_border", {}) or {}, self.settings["colors"])
            fields["item_selection_border_enabled"] = sel_border_field
            fields["item_selection_border"] = sel_border_field

            sel_radius_toggle = make_toggle("item_selection_radius")
            sel_radius_field = _CornerRadiusField(
                linked("item_selection_radius"), _coerce_corner_radius(seed("item_selection_radius", 0)),
                maximum=20)
            fields["item_selection_radius"] = sel_radius_field

            edge_border_toggle = make_toggle("item_selection_edge_border")
            edge_border_field = _Toggle(bool(seed("item_selection_edge_border", True)), style_override="toggle1")
            fields["item_selection_edge_border"] = edge_border_field

            focus_frame, _focus_row_meta, focus_resizer = _build_override_flat_table([
                ("Couleur", focus_field, focus_toggle),
                ("Padding du selecteur", sel_padding_field, sel_padding_toggle),
                ("Bordures du selecteur", sel_border_field, sel_border_toggle),
                ("Arrondi des coins de la selection", sel_radius_field, sel_radius_toggle),
                ("Bordure au bord de la colonne", edge_border_field, edge_border_toggle),
            ])
            self._flat_resizers.append(focus_resizer)
            focus_selection_sub = _SubSection("Focus", level=3)
            focus_selection_sub.add(focus_frame)

            def build_state_override(state: str, sub_title: str, color_key: str, color_default, use_app_color: bool):
                if use_app_color:
                    color_field = _AppOrCustomColorField(
                        seed(color_key, color_default), self.settings["colors"], swatch_size=24, title=sub_title)
                else:
                    color_field = _ColorField(seed(color_key, color_default), swatch_size=24, title=sub_title)
                color_toggle = make_toggle(color_key)
                fields[color_key] = color_field

                padding_key = f"item_selection_{state}_padding"
                padding_override_key = f"{padding_key}_override"
                padding_toggle = make_toggle(padding_key, padding_override_key)
                padding_field = _CellPaddingField(
                    linked(padding_key), seed(padding_key, {}) or {})
                fields[padding_key] = padding_field
                fields[padding_override_key] = padding_field

                border_key = f"item_selection_{state}_border"
                border_enabled_key = f"{border_key}_enabled"
                border_override_key = f"{border_key}_override"
                border_toggle = make_toggle(border_enabled_key, border_key, border_override_key)
                border_field = _ToggleSideColorsField(
                    _coerce_side_enabled(seed(border_enabled_key, False)),
                    seed(border_key, {}) or {}, self.settings["colors"])
                fields[border_enabled_key] = border_field
                fields[border_key] = border_field
                fields[border_override_key] = border_field

                radius_key = f"item_selection_{state}_radius"
                radius_override_key = f"{radius_key}_override"
                radius_toggle = make_toggle(radius_key, radius_override_key)
                radius_field = _CornerRadiusField(
                    linked(radius_key), _coerce_corner_radius(seed(radius_key, 0)), maximum=20)
                fields[radius_key] = radius_field
                fields[radius_override_key] = radius_field

                edge_key = f"item_selection_{state}_edge_border"
                edge_override_key = f"{edge_key}_override"
                edge_toggle = make_toggle(edge_key, edge_override_key)
                edge_field = _Toggle(bool(seed(edge_key, True)), style_override="toggle1")
                fields[edge_key] = edge_field
                fields[edge_override_key] = edge_field

                state_frame, _state_row_meta, state_resizer = _build_override_flat_table([
                    ("Couleur", color_field, color_toggle),
                    ("Padding du selecteur", padding_field, padding_toggle),
                    ("Bordures du selecteur", border_field, border_toggle),
                    ("Arrondi des coins de la selection", radius_field, radius_toggle),
                    ("Bordure au bord de la colonne", edge_field, edge_toggle),
                ])
                self._flat_resizers.append(state_resizer)
                state_sub = _SubSection(sub_title, level=3)
                state_sub.add(state_frame)
                return state_sub

            unfocus_selection_sub = build_state_override(
                "unfocus", "Non focus", "item_selection_unfocus_color", "#2e3338", False)
            hover_selection_sub = build_state_override(
                "hover", "Survol", "item_hover_color", "#232729", False)
            idle_selection_sub = build_state_override(
                "idle", "Non selectionne", "item_idle_color", "@itemIdle", True)

            selection_group_wrap = QWidget()
            selection_group_wrap.setStyleSheet("background: transparent;")
            selection_group_wrap_l = QVBoxLayout(selection_group_wrap)
            selection_group_wrap_l.setContentsMargins(0, 0, 0, 0)
            _stack_subsections(
                selection_group_wrap_l,
                [focus_selection_sub, unfocus_selection_sub, hover_selection_sub, idle_selection_sub])
            selection_sub = _SubSection("Selection", level=2)
            selection_sub.add(selection_group_wrap)
            for sub in (focus_selection_sub, unfocus_selection_sub, hover_selection_sub, idle_selection_sub):
                sub.collapsedChanged.connect(selection_sub.refresh_layout)
        elif real_title == PREVIEW_STACK_TITLE:
            # Colonnes > Apercu (PREVIEW_STACK_TITLE) — 3 sous-sections
            # PROPRES a cette colonne (jamais partagees/surchargeables
            # ailleurs, contrairement a Colonnes/Entetes ci-dessus) : pas
            # de toggle de surcharge ligne par ligne ici (rien a
            # "surcharger", cette colonne est la SEULE a lire ces cles) —
            # champs branches DIRECTEMENT sur self.settings, comme
            # n'importe quel champ de l'onglet General — voir la remarque
            # de l'utilisateur, "je veux une section image ... zone
            # titre ... bouton repliement". Exception : Ratio, qui
            # SURCHARGE item_image_ratio (partagee avec Type/Projets/
            # Sous-projet) via le MEME mecanisme toggle que le reste.

            # -- Image --
            # Padding/Rayon : dicts 4 cotes/4 coins INDEPENDANTS (MEMES
            # widgets que partout ailleurs, _CellPaddingField/
            # _CornerRadiusField) — voir la remarque de l'utilisateur,
            # "contrôle des paddings sur les 4 cotes comme partout
            # ailleurs ... pareil pour les coins arrondis" (l'ancienne
            # version, un slider UNIFORME, ne correspondait pas a ce
            # pattern — et son masque d'arrondi avait par-dessus un vrai
            # bug de composition, voir pipeline_browser._SquarePreviewImage.
            # _refresh, corrige au passage).
            self.preview_padding_field = _CellPaddingField(
                bool(self.settings.get("preview_padding_linked", True)),
                self.settings.get("preview_padding") or {})
            self.preview_radius_field = _CornerRadiusField(
                bool(self.settings.get("preview_radius_linked", True)),
                _coerce_corner_radius(self.settings.get("preview_radius", 0)), maximum=40)
            # Plus de reglage "Hauteur de l'image" (retire, voir la remarque
            # de l'utilisateur, "supprime la ligne hauteur de l'image et
            # calle la largeur de l'image a la largeur de la colonne") : la
            # largeur suit desormais TOUJOURS la largeur de colonne (moins
            # le Padding ci-dessous), la hauteur etant deduite du Ratio —
            # voir pipeline_browser._PreviewBlock.
            ratio_toggle = make_toggle("item_image_ratio")
            ratio_field = _SliderField(
                20, 500, int(round(float(seed("item_image_ratio", 1.0)) * 100)),
                unit="%", slider_width=170, box_width=68)
            fields["item_image_ratio"] = ratio_field

            # 2 tableaux empiles (pas 1 seul, voir _build_override_flat_
            # table ci-dessous) : Padding/Rayon n'ont RIEN a surcharger
            # (propres a cette colonne, aucune valeur GENERALE dont
            # s'ecarter) et restent donc dans un tableau SANS toggle
            # (_build_flat_table, comme l'onglet General) ; Ratio, lui,
            # SURCHARGE item_image_ratio (partage avec Type/Projets/Sous-
            # projet) et a donc besoin du toggle de surcharge habituel.
            preview_image_frame, _preview_image_row_meta, preview_image_resizer = _build_flat_table([
                ("Padding", self.preview_padding_field),
                ("Rayon des angles", self.preview_radius_field),
            ])
            self._flat_resizers.append(preview_image_resizer)
            preview_ratio_frame, _preview_ratio_row_meta, preview_ratio_resizer = _build_override_flat_table([
                ("Ratio (largeur/hauteur)", ratio_field, ratio_toggle),
            ])
            self._flat_resizers.append(preview_ratio_resizer)
            image_wrap = QWidget()
            image_wrap.setStyleSheet("background: transparent;")
            image_wrap_l = QVBoxLayout(image_wrap)
            image_wrap_l.setContentsMargins(0, 0, 0, 0)
            image_wrap_l.setSpacing(10)
            image_wrap_l.addWidget(preview_image_frame)
            image_wrap_l.addWidget(preview_ratio_frame)
            image_sub = _SubSection("Image", level=2)
            image_sub.add(image_wrap)

            # -- Zone titre -- (plus de "Fond" dedie ici : voir Colonnes >
            # Focus > Colonnes > Couleur de fond, UNIQUE couleur de fond
            # pour toute la colonne — voir la remarque de l'utilisateur,
            # "voici la couleur a appliquer sur les zones avec des croix").
            self.preview_title_zone_height_field = _SliderField(
                20, 120, int(self.settings.get("preview_title_zone_height", 52)), slider_width=170, box_width=68)
            self.preview_title_font_size_field = _SliderField(
                8, 48, int(self.settings.get("preview_title_font_size", 26)), slider_width=170, box_width=68)
            self.preview_title_font_color_field = _CompactAppOrCustomColorField(
                self.settings.get("preview_title_font_color", "#d6d9dc"), self.settings["colors"],
                swatch_size=20, title="Couleur du titre")
            # Choix de police (police du soft ou police systeme, voir
            # _DualFontSelectField/pipeline_browser._resolve_font_family) —
            # voir la remarque de l'utilisateur, "je veux le choix de la
            # police (titre + apercu des dossiers) (choix entre polices
            # appli ou polices systeme)".
            self.preview_title_font_family_field = _DualFontSelectField(
                self.settings.get("preview_title_font_family") or "Systeme", width=150)
            self.preview_title_font_bold_field = _Toggle(
                bool(self.settings.get("preview_title_font_bold", True)), show_label=False)
            self.preview_title_font_italic_field = _Toggle(
                bool(self.settings.get("preview_title_font_italic", False)), show_label=False)
            # Lissage (voir _OverrideSmoothingField/Colonnes > Texte >
            # Lissage, MEME widget) — voir la remarque de l'utilisateur,
            # "ajoute les niveaux de lissage sur les lignes des polices".
            self.preview_title_font_smoothing_field = _OverrideSmoothingField(
                bool(self.settings.get("preview_title_font_smoothing_enabled", False)),
                self.settings.get("preview_title_font_smoothing", "current"))
            preview_title_font_row = _build_font_gabarit_row(
                self.preview_title_font_family_field, self.preview_title_font_bold_field,
                self.preview_title_font_size_field, self.preview_title_font_smoothing_field,
                self.preview_title_font_color_field, italic_field=self.preview_title_font_italic_field)
            # "Titre - padding" : sans le cote Droite/"D" — voir la remarque
            # de l'utilisateur, "titre - padding : supprime padding D".
            self.preview_title_padding_field = _CellPaddingField(
                True, self.settings.get("preview_title_padding") or {},
                order=[("left", "G"), ("top", "H"), ("bottom", "B")])
            self.preview_status_font_size_field = _SliderField(
                6, 24, int(self.settings.get("preview_status_font_size", 10)), slider_width=170, box_width=68)
            self.preview_status_font_color_field = _CompactAppOrCustomColorField(
                self.settings.get("preview_status_font_color", "#d6d9dc"), self.settings["colors"],
                swatch_size=20, title="Couleur (apercu dossiers)")
            # "Non selectionne" (etat VIDE d'un indicateur in/over/out,
            # voir _StatusLabel `idle_color` — jusqu'ici fige sur C["dim"])
            # — MEME ligne que "Apercu des dossiers - couleur" ci-dessus
            # (l'etat ACTIF), voir la remarque de l'utilisateur, "ajoute
            # une couleur : non selectionne, sur la meme ligne que apercu
            # des dossiers - couleur".
            self.preview_status_font_color_idle_field = _CompactAppOrCustomColorField(
                self.settings.get("preview_status_font_color_idle", "#5f666b"), self.settings["colors"],
                swatch_size=20, title="Non selectionne")
            status_colors_row = QWidget()
            status_colors_row.setStyleSheet("background: transparent;")
            status_colors_row_l = QHBoxLayout(status_colors_row)
            status_colors_row_l.setContentsMargins(0, 0, 0, 0)
            status_colors_row_l.setSpacing(14)
            status_colors_row_l.addWidget(self.preview_status_font_color_field)
            status_colors_row_l.addWidget(self.preview_status_font_color_idle_field)
            self.preview_status_font_family_field = _DualFontSelectField(
                self.settings.get("preview_status_font_family") or "Systeme", width=150)
            self.preview_status_font_bold_field = _Toggle(
                bool(self.settings.get("preview_status_font_bold", True)), show_label=False)
            self.preview_status_font_italic_field = _Toggle(
                bool(self.settings.get("preview_status_font_italic", False)), show_label=False)
            # Lissage (voir _OverrideSmoothingField ci-dessus, meme raison).
            self.preview_status_font_smoothing_field = _OverrideSmoothingField(
                bool(self.settings.get("preview_status_font_smoothing_enabled", False)),
                self.settings.get("preview_status_font_smoothing", "current"))
            preview_status_font_row = _build_font_gabarit_row(
                self.preview_status_font_family_field, self.preview_status_font_bold_field,
                self.preview_status_font_size_field, self.preview_status_font_smoothing_field,
                status_colors_row, italic_field=self.preview_status_font_italic_field)
            # "Apercu des dossiers - padding" : sans les cotes Gauche/"G" et
            # Bas/"B" — voir la remarque de l'utilisateur, "apercu des
            # dossiers - padding : supprime padding G et B".
            self.preview_status_padding_field = _CellPaddingField(
                True, self.settings.get("preview_status_padding") or {},
                order=[("top", "H"), ("right", "D")])

            title_zone_frame, _title_zone_row_meta, title_zone_resizer = _build_flat_table([
                ("Hauteur", self.preview_title_zone_height_field),
                ("Titre - police", preview_title_font_row),
                ("Titre - padding", self.preview_title_padding_field),
                ("Apercu des dossiers - police", preview_status_font_row),
                ("Apercu des dossiers - padding", self.preview_status_padding_field),
            ])
            self._flat_resizers.append(title_zone_resizer)
            title_zone_sub = _SubSection("Zone titre", level=2)
            title_zone_sub.add(title_zone_frame)

            # -- Bouton repliement --
            self.preview_toggle_width_field = _SliderField(
                12, 60, int(self.settings.get("preview_toggle_width", 22)), slider_width=170, box_width=68)
            self.preview_toggle_height_field = _SliderField(
                12, 60, int(self.settings.get("preview_toggle_height", 22)), slider_width=170, box_width=68)
            self.preview_toggle_bg_field = _AppOrCustomColorField(
                self.settings.get("preview_toggle_bg_color", "#960f1114"), self.settings["colors"],
                swatch_size=24, title="Fond du bouton")
            self.preview_toggle_border_thickness_field = _SliderField(
                0, 8, int(self.settings.get("preview_toggle_border_thickness", 1)), slider_width=140, box_width=54)
            self.preview_toggle_border_field = _ToggleSideColorsField(
                _coerce_side_enabled(self.settings.get("preview_toggle_border_enabled", False)),
                self.settings.get("preview_toggle_border") or {}, self.settings["colors"],
                thickness_field=self.preview_toggle_border_thickness_field)
            self.preview_toggle_radius_field = _SliderField(
                0, 30, int(self.settings.get("preview_toggle_radius", 4)), slider_width=170, box_width=68)
            # Position EXPLICITE (X/Y depuis le coin superieur GAUCHE de la
            # colonne) — remplace Padding, voir la remarque de
            # l'utilisateur, "supprime le padding mais ajoute un parametre
            # de position par rapport au coin superieur gauche de la
            # colonne en x et en y".
            self.preview_toggle_x_field = _SliderField(
                0, 200, int(self.settings.get("preview_toggle_x", 8)), slider_width=170, box_width=68)
            self.preview_toggle_y_field = _SliderField(
                0, 200, int(self.settings.get("preview_toggle_y", 34)), slider_width=170, box_width=68)
            # X et Y sur UNE SEULE ligne (comme status_colors_row plus
            # haut) — voir la remarque de l'utilisateur, "position x et y
            # sur la mm ligne".
            toggle_pos_row = QWidget()
            toggle_pos_row.setStyleSheet("background: transparent;")
            toggle_pos_row_l = QHBoxLayout(toggle_pos_row)
            toggle_pos_row_l.setContentsMargins(0, 0, 0, 0)
            toggle_pos_row_l.setSpacing(14)
            toggle_pos_row_l.addWidget(self.preview_toggle_x_field)
            toggle_pos_row_l.addWidget(self.preview_toggle_y_field)

            # Icone/Chevrons (voir la remarque de l'utilisateur, "je veux
            # que dans les settings (colonne/focus/colonnes/bouton de
            # repliement tu ajoute une ligne icone, et que tu laisse le
            # choix entre icone ou chevrons comme actuellement") — "Icone"
            # utilise UI_ICON_COLLAPSE_TOGGLE (Settings > ICONES > General)
            # si l'utilisateur en a choisi une, sinon les chevrons restent
            # affiches meme si "Icone" est selectionne (voir IconButton.
            # _custom_icon_pixmap).
            self.collapse_toggle_mode_field = _SelectField(
                ["Chevrons", "Icone"],
                "Icone" if self.settings.get("collapse_toggle_mode", "chevrons") == "icone" else "Chevrons",
                width=170)

            toggle_frame, _toggle_row_meta, toggle_resizer = _build_flat_table([
                ("Largeur du bouton", self.preview_toggle_width_field),
                ("Hauteur du bouton", self.preview_toggle_height_field),
                ("Couleur de fond", self.preview_toggle_bg_field),
                ("Bordure", self.preview_toggle_border_field),
                ("Rayon des angles", self.preview_toggle_radius_field),
                ("Position X/Y", toggle_pos_row),
                ("Icone", self.collapse_toggle_mode_field),
            ])
            self._flat_resizers.append(toggle_resizer)
            toggle_sub = _SubSection("Bouton repliement", level=2)
            toggle_sub.add(toggle_frame)

        # Icone de niveaux (badge numerote, voir pipeline_browser.
        # _step_badge_rect/_step_badge_color/ProjectTileDelegate.paint) —
        # SEULEMENT sur "Projets" (seule colonne a l'afficher) : champs
        # PLATS branches directement sur self.settings, comme Colonnes >
        # Apercu ci-dessus (rien a "surcharger", cette colonne est la
        # SEULE a lire ces cles) — voir la remarque de l'utilisateur,
        # "j'aimerais pouvoir controler l'aspect de cette petite icone
        # (endroit : colonnes / projets / colonnes)".
        step_badge_sub = None
        if real_title == "Projets":
            self.step_badge_width_field = _SliderField(
                8, 60, int(self.settings.get("step_badge_width", 18)), slider_width=170, box_width=68)
            self.step_badge_height_field = _SliderField(
                8, 60, int(self.settings.get("step_badge_height", 18)), slider_width=170, box_width=68)
            step_badge_size_row = QWidget()
            step_badge_size_row.setStyleSheet("background: transparent;")
            step_badge_size_row_l = QHBoxLayout(step_badge_size_row)
            step_badge_size_row_l.setContentsMargins(0, 0, 0, 0)
            step_badge_size_row_l.setSpacing(14)
            step_badge_size_row_l.addWidget(self.step_badge_width_field)
            step_badge_size_row_l.addWidget(self.step_badge_height_field)

            self.step_badge_border_thickness_field = _SliderField(
                0, 8, int(self.settings.get("step_badge_border_thickness", 1)), slider_width=140, box_width=54)
            self.step_badge_border_field = _ToggleSideColorsField(
                _coerce_side_enabled(self.settings.get("step_badge_border_enabled", False)),
                self.settings.get("step_badge_border") or {}, self.settings["colors"],
                thickness_field=self.step_badge_border_thickness_field)

            self.step_badge_radius_field = _CornerRadiusField(
                bool(self.settings.get("step_badge_radius_linked", True)),
                _coerce_corner_radius(self.settings.get("step_badge_radius", 9)))

            # 5 paires de couleurs (texte au-dessus, fond en dessous), une
            # par palier (base 2 a 6, voir pipeline_browser._step_badge_
            # color/_step_badge_text_color) — voir la remarque de
            # l'utilisateur, "enleve la couleur dans la ligne texte, et met
            # un carre de couleur pour le texte au dessus des carres de
            # couleur de fond. De cette maniere la couleur du haut est
            # pour le texte (pour chacune des bases) et la couleur du bas
            # est pour le fond".
            self.step_badge_text_color_base2_field = _CompactAppOrCustomColorField(
                self.settings.get("step_badge_text_color_base2", "#eef2f5"), self.settings["colors"],
                swatch_size=20, title="Texte - Base 2")
            self.step_badge_text_color_base3_field = _CompactAppOrCustomColorField(
                self.settings.get("step_badge_text_color_base3", "#eef2f5"), self.settings["colors"],
                swatch_size=20, title="Texte - Base 3")
            self.step_badge_text_color_base4_field = _CompactAppOrCustomColorField(
                self.settings.get("step_badge_text_color_base4", "#eef2f5"), self.settings["colors"],
                swatch_size=20, title="Texte - Base 4")
            self.step_badge_text_color_base5_field = _CompactAppOrCustomColorField(
                self.settings.get("step_badge_text_color_base5", "#eef2f5"), self.settings["colors"],
                swatch_size=20, title="Texte - Base 5")
            self.step_badge_text_color_base6_field = _CompactAppOrCustomColorField(
                self.settings.get("step_badge_text_color_base6", "#eef2f5"), self.settings["colors"],
                swatch_size=20, title="Texte - Base 6")
            self.step_badge_color_base2_field = _CompactAppOrCustomColorField(
                self.settings.get("step_badge_color_base2", "#5c6368"), self.settings["colors"],
                swatch_size=24, title="Fond - Base 2")
            self.step_badge_color_base3_field = _CompactAppOrCustomColorField(
                self.settings.get("step_badge_color_base3", "#5c6368"), self.settings["colors"],
                swatch_size=24, title="Fond - Base 3")
            self.step_badge_color_base4_field = _CompactAppOrCustomColorField(
                self.settings.get("step_badge_color_base4", "#3f6f9f"), self.settings["colors"],
                swatch_size=24, title="Fond - Base 4")
            self.step_badge_color_base5_field = _CompactAppOrCustomColorField(
                self.settings.get("step_badge_color_base5", "#3f6f9f"), self.settings["colors"],
                swatch_size=24, title="Fond - Base 5")
            self.step_badge_color_base6_field = _CompactAppOrCustomColorField(
                self.settings.get("step_badge_color_base6", "#d9822b"), self.settings["colors"],
                swatch_size=24, title="Fond - Base 6")
            # Paire DEDIEE au badge "N" (voir DEFAULT_SETTINGS, sa remarque
            # de tete) — affiche a la place du numero quand le toggle "set"
            # (ColumnConfigDialog) est desactive pour un projet.
            self.step_badge_text_color_basen_field = _CompactAppOrCustomColorField(
                self.settings.get("step_badge_text_color_basen", "#eef2f5"), self.settings["colors"],
                swatch_size=20, title="Texte - Base N")
            self.step_badge_color_basen_field = _CompactAppOrCustomColorField(
                self.settings.get("step_badge_color_basen", "#5c6368"), self.settings["colors"],
                swatch_size=24, title="Fond - Base N")
            step_badge_colors_row = QWidget()
            step_badge_colors_row.setStyleSheet("background: transparent;")
            step_badge_colors_row_l = QHBoxLayout(step_badge_colors_row)
            step_badge_colors_row_l.setContentsMargins(0, 0, 0, 0)
            step_badge_colors_row_l.setSpacing(10)
            # Numero de base AU-DESSUS de chaque paire (voir la remarque de
            # l'utilisateur, "couleur de fond : place les numeros de base
            # juste au-dessus des couleurs") : le "title" de
            # _AppOrCustomColorField n'est visible qu'en infobulle, jamais
            # affiche a l'ecran — un QLabel DEDIE, empile dans une petite
            # colonne AVEC la pastille TEXTE puis la pastille FOND.
            for n, text_f, bg_f in (
                (2, self.step_badge_text_color_base2_field, self.step_badge_color_base2_field),
                (3, self.step_badge_text_color_base3_field, self.step_badge_color_base3_field),
                (4, self.step_badge_text_color_base4_field, self.step_badge_color_base4_field),
                (5, self.step_badge_text_color_base5_field, self.step_badge_color_base5_field),
                (6, self.step_badge_text_color_base6_field, self.step_badge_color_base6_field),
                ("N", self.step_badge_text_color_basen_field, self.step_badge_color_basen_field),
            ):
                # Separateur vertical AVANT chaque paire, y compris la
                # toute premiere (voir _SideColorsField, MEME widget/MEME
                # couleur — "est il possible de rajouter une ligne
                # verticale qui separe" — ici demande explicitement AVANT
                # ET entre, voir la remarque de l'utilisateur, "ajoute des
                # separateurs (bordures) avant et entre les couleurs de
                # colonnes/projets/colonnes/icone de niveaux").
                sep = QFrame()
                sep.setFrameShape(QFrame.VLine)
                sep.setFixedWidth(1)
                sep.setStyleSheet(f"background: {M['field_border']}; border: none;")
                step_badge_colors_row_l.addWidget(sep)
                cell = QWidget()
                cell.setStyleSheet("background: transparent;")
                cell_l = QVBoxLayout(cell)
                cell_l.setContentsMargins(0, 0, 0, 0)
                cell_l.setSpacing(4)
                cell_l.setAlignment(Qt.AlignHCenter)
                num_label = QLabel(str(n))
                _set_text_role(num_label, "note_mono_bold")
                num_label.setAlignment(Qt.AlignHCenter)
                cell_l.addWidget(num_label)
                cell_l.addWidget(text_f)
                cell_l.addWidget(bg_f)
                step_badge_colors_row_l.addWidget(cell)

            # Bornes NEGATIVES (pas seulement 0-200) : voir la remarque de
            # l'utilisateur, "je veux que l'icone des niveaux puisse aussi
            # monter (valeur negative peut etre ?)" — une position H/V
            # negative deplace le badge AU-DELA de son ancre par defaut
            # (voir _step_badge_rect), donc vers le haut/la gauche.
            self.step_badge_offset_x_field = _SliderField(
                -100, 200, int(self.settings.get("step_badge_offset_x", 4)), slider_width=170, box_width=68)
            self.step_badge_offset_y_field = _SliderField(
                -100, 200, int(self.settings.get("step_badge_offset_y", 0)), slider_width=170, box_width=68)
            step_badge_pos_row = QWidget()
            step_badge_pos_row.setStyleSheet("background: transparent;")
            step_badge_pos_row_l = QHBoxLayout(step_badge_pos_row)
            step_badge_pos_row_l.setContentsMargins(0, 0, 0, 0)
            step_badge_pos_row_l.setSpacing(14)
            step_badge_pos_row_l.addWidget(self.step_badge_offset_x_field)
            step_badge_pos_row_l.addWidget(self.step_badge_offset_y_field)

            # Police/gras/lissage du numero (PAS la couleur : voir plus
            # haut, une couleur de texte PAR BASE juste au-dessus de la
            # couleur de fond correspondante, voir la remarque de
            # l'utilisateur, "enleve la couleur dans la ligne texte") —
            # lissage AJOUTE sur cette meme ligne (voir la remarque de
            # l'utilisateur, "dans la ligne police, ajoute le slider des
            # lissage de police") — MEME widget que Colonnes > Texte >
            # Lissage (_OverrideSmoothingField).
            self.step_badge_font_family_field = _DualFontSelectField(
                self.settings.get("step_badge_font_family") or "Systeme", width=130)
            self.step_badge_font_bold_field = _Toggle(bool(self.settings.get("step_badge_font_bold", True)))
            self.step_badge_font_smoothing_field = _OverrideSmoothingField(
                bool(self.settings.get("step_badge_font_smoothing_enabled", False)),
                self.settings.get("step_badge_font_smoothing", "current"))
            step_badge_font_row = QWidget()
            step_badge_font_row.setStyleSheet("background: transparent;")
            step_badge_font_row_l = QHBoxLayout(step_badge_font_row)
            step_badge_font_row_l.setContentsMargins(0, 0, 0, 0)
            step_badge_font_row_l.setSpacing(14)
            step_badge_font_row_l.addWidget(self.step_badge_font_family_field)
            step_badge_font_row_l.addWidget(self.step_badge_font_bold_field)
            step_badge_font_row_l.addWidget(self.step_badge_font_smoothing_field)

            # Lissage (antialiasing) du TRAIT de bordure lui-meme (PAS le
            # texte, voir la remarque de l'utilisateur, "antialiasing du
            # contour de la bordure") — actif par defaut (comportement
            # INCHANGE, le trait etait deja toujours lisse jusqu'ici).
            self.step_badge_border_smoothing_field = _Toggle(
                bool(self.settings.get("step_badge_border_smoothing", True)))

            step_badge_frame, _step_badge_row_meta, step_badge_resizer = _build_flat_table([
                ("Largeur / hauteur", step_badge_size_row),
                ("Bordure", self.step_badge_border_field),
                ("Lissage de la bordure", self.step_badge_border_smoothing_field),
                ("Rayon des angles", self.step_badge_radius_field),
                ("Couleurs de fond (base 2 a 6, et N)", step_badge_colors_row),
                ("Police / gras / lissage du numero", step_badge_font_row),
                ("Position H/V", step_badge_pos_row),
            ])
            self._flat_resizers.append(step_badge_resizer)
            step_badge_sub = _SubSection("Icone de niveaux", level=2)
            step_badge_sub.add(step_badge_frame)

            # _mark_dirty CABLE ICI (pas dans _connect_live_updates, appelee
            # UNE FOIS dans __init__ AVANT que cette page "Projets" — desormais
            # PARESSEUSE, voir _on_columns_tab_changed — ait forcement ete
            # construite) : ces champs n'existent parfois pas encore a ce
            # moment-la, une connexion tentee la-bas y leverait
            # AttributeError.
            for sig in (
                self.step_badge_width_field.valueChanged, self.step_badge_height_field.valueChanged,
                self.step_badge_border_field.changed, self.step_badge_border_thickness_field.valueChanged,
                self.step_badge_radius_field.changed,
                self.step_badge_color_base2_field.changed, self.step_badge_color_base3_field.changed,
                self.step_badge_color_base4_field.changed, self.step_badge_color_base5_field.changed,
                self.step_badge_color_base6_field.changed, self.step_badge_color_basen_field.changed,
                self.step_badge_text_color_base2_field.changed, self.step_badge_text_color_base3_field.changed,
                self.step_badge_text_color_base4_field.changed, self.step_badge_text_color_base5_field.changed,
                self.step_badge_text_color_base6_field.changed, self.step_badge_text_color_basen_field.changed,
                self.step_badge_offset_x_field.valueChanged, self.step_badge_offset_y_field.valueChanged,
                self.step_badge_font_family_field.changed, self.step_badge_font_smoothing_field.changed,
            ):
                sig.connect(self._mark_dirty)
            self.step_badge_font_bold_field.toggled.connect(self._mark_dirty)
            self.step_badge_border_smoothing_field.toggled.connect(self._mark_dirty)

        # Les 4 sous-groupes empiles ENSEMBLE, espacement ADAPTATIF uniforme
        # entre chacun (voir _stack_subsections/la remarque de l'utilisateur,
        # "je veux que tu normalises l'espacement entre les sections ...
        # comme tu l'avais fait pour les sections"), le tout dans UNE section
        # "Colonnes" repliable (meme widget que General > Colonnes, voir
        # _section_headers) — voir la remarque de l'utilisateur, "cree la
        # section colonnes comme dans general ... enleve la ligne
        # explicative".
        subsections_wrap = QWidget()
        subsections_wrap.setStyleSheet("background: transparent;")
        subsections_wrap_l = QVBoxLayout(subsections_wrap)
        subsections_wrap_l.setContentsMargins(0, 0, 0, 0)
        # text_sub/image_sub/selection_sub : None pour PREVIEW_STACK_TITLE
        # (voir plus haut) — filtres ici plutot que dans chaque liste
        # ci-dessous, pour ne garder qu'UN SEUL endroit a mettre a jour si
        # d'autres sous-sections deviennent un jour elles aussi optionnelles.
        all_subs = [
            s for s in (
                columns_sub, headers_sub, text_sub, image_sub, selection_sub,
                title_zone_sub, toggle_sub, step_badge_sub,
            )
            if s is not None
        ]
        _stack_subsections(subsections_wrap_l, all_subs)

        section = _Section("Colonnes")
        section.add(subsections_wrap)
        for sub in all_subs:
            sub.collapsedChanged.connect(section.refresh_min_height)
        layout.addWidget(section)

        layout.addStretch(1)
        scroller.setWidget(inner)
        self._connect_column_type_overrides(real_title)
        return page

    def _connect_column_type_overrides(self, title: str):
        """Cable chaque champ/toggle de Colonnes > Type/Projets/Sous-
        projets POUR CETTE colonne (voir _build_column_override_page) sur
        _mark_dirty (persistance + application en direct a l'appli reelle,
        voir SettingsWindow._mark_dirty/pipeline_browser.apply_all_settings/
        COLUMN_TYPE_OVERRIDE_KEYS) ET sur _apply_column_type_preview
        (rafraichit EN DIRECT les boites de l'apercu Colonnes, onglet
        General — meme principe que _connect_live_updates pour les champs
        generaux)."""
        signals = []
        for toggle in set(self._type_toggles[title].values()):
            signals.append(toggle.toggled)
        seen = set()
        for field in self._type_fields[title].values():
            if id(field) in seen:
                continue
            seen.add(id(field))
            for attr in ("changed", "valueChanged", "toggled"):
                sig = getattr(field, attr, None)
                if sig is not None:
                    signals.append(sig)
                    break
        for sig in signals:
            sig.connect(self._mark_dirty)
            sig.connect(self._schedule_column_type_preview)
        self._apply_column_type_preview()

    def _schedule_column_type_preview(self, *_args):
        """Regroupe les changements rapproches sur Colonnes > Type/Projets/
        Sous-projets (voir _connect_column_type_overrides/
        _column_type_preview_timer, construit dans _connect_live_updates) —
        MEME principe que _schedule_colors_changed pour la page Couleurs :
        un glisser de slider emet valueChanged a CHAQUE pixel, rejouer
        _apply_column_type_preview() a ce rythme (boucle sur ~20 cles x 3
        colonnes) provoquait la lenteur ressentie au glisser. Repli direct
        (sans timer) si appele AVANT que celui-ci existe encore (tout debut
        de la construction de la fenetre, voir _connect_column_type_overrides
        appelee depuis _build_column_override_page, EN AMONT de
        _connect_live_updates qui construit le timer)."""
        timer = getattr(self, "_column_type_preview_timer", None)
        if timer is None:
            self._apply_column_type_preview()
            return
        if not timer.isActive():
            timer.start()

    def _apply_column_type_preview(self, *_args):
        """No-op — aperçus de colonnes SUPPRIMES, voir _apply_column_preview
        (MEME raison, meme gardee que pour les dizaines de signaux deja
        connectes, y compris _column_type_preview_timer/
        _schedule_column_type_preview)."""
        return

    # -- contenu (sections) --

    def _report_loading_step(self, label: str | None, depth: int = 0):
        """Reporte l'etape de construction EN COURS dans le "puits" (carre
        sombre) de l'Inspecteur de la fenetre principale (voir DetailPanel.
        show_loading_step/clear_loading_step) — `None` restaure son
        apparence normale (fin de construction). Sans effet si la fenetre
        principale n'a pas encore de panneau Inspecteur (tests headless
        construisant SettingsWindow seule, sans parent) — voir la remarque
        de l'utilisateur, "peux tu faire une sorte d'animation dans le
        champ apercu de l'inspecteur et afficher tous les elements que tu
        charges en temps reel". `processEvents()` (pas juste setText) :
        cette fenetre est construite de façon SYNCHRONE, sans jamais rendre
        la main a la boucle d'evenements entre 2 sections — sans lui, rien
        ne se peindrait avant la toute derniere section, l'indicateur
        resterait fige."""
        detail = getattr(self.parent(), "detail", None)
        if detail is not None:
            if label is not None:
                detail.show_loading_step(label, depth=depth)
            else:
                detail.clear_loading_step()
        QApplication.processEvents()

    def _build_content(self, parent: QWidget | None = None) -> QWidget:
        # _NoSqueezeScrollArea (pas QScrollArea nu) : la fenetre reste
        # redimensionnable librement (y compris plus bas que le contenu),
        # mais une scrollbar verticale apparait alors a droite au lieu de
        # tasser les lignes de reglage les unes contre les autres — voir la
        # remarque de l'utilisateur, capture a l'appui.
        # Construite de haut en bas (voir __init__) : scroller et inner sont
        # rattaches AVANT d'etre remplis, chaque section naissant directement
        # dans inner (voir _section_host).
        scroller = _NoSqueezeScrollArea(parent)
        self._content_scroller = scroller
        scroller.setWidgetResizable(True)
        scroller.setFrameShape(QFrame.NoFrame)
        scroller.setStyleSheet(f"background: {M['panel_bg']};")
        inner = QWidget(scroller.viewport())
        layout = QVBoxLayout(inner)
        layout.setContentsMargins(20, 18, 18, 26)
        # Pas de layout.setSpacing() fixe ici : ca imposerait le MEME
        # espacement entre CHAQUE paire de sections, y compris quand celle
        # du dessus est repliee — voir la remarque de l'utilisateur : une
        # section repliee doit aussi replier l'espace qui la separe de la
        # suivante. A la place, un spaceur DEDIE (largeur pleine, hauteur
        # variable) apres chaque section (sauf la derniere), dont la
        # hauteur suit collapsedChanged (voir _SECTION_GAP_*).
        layout.setSpacing(0)
        # Construite SECTION PAR SECTION (pas un seul literal de liste,
        # toutes evaluees d'un coup) : chaque _Section/_SubSection construite
        # ICI (et a l'interieur, a N'IMPORTE quel niveau d'imbrication) se
        # rapporte D'ELLE-MEME, en TEMPS REEL, au "puits" de l'Inspecteur
        # (voir _Section.__init__/_SubSection.__init__/_report_construction_
        # step, _ACTIVE_LOADING_WINDOW) — voir la remarque de l'utilisateur,
        # "la fenetre de settings est toujours tres longue a charger ...
        # decris pas seulement les tabs mais toutes les sections et sous
        # sections aussi".
        section_builders = [
            self._section_titre, self._section_application, self._section_omit, self._section_lut,
            self._section_fonts, self._section_colors,
            self._section_geometry, self._section_headers, self._section_tables,
            self._section_toggles, self._section_slider, self._section_icones,
            self._section_raccourci,
        ]
        if self._light:
            section_builders = [self._section_application, self._section_omit, self._section_lut]
        with _section_host(inner):
            sections = [builder() for builder in section_builders]
        if self._mode != "tout":
            # Sections montrees dans ce mode ; les autres sont rangees.
            general_only = {getattr(self, name) for name in self._GENERAL_SECTIONS}
            shown = []
            for builder, section in zip(section_builders, sections):
                if (builder in general_only) == (self._mode == "general"):
                    shown.append(section)
                else:
                    section.setParent(self._hidden_holder)
            sections = shown
        # TOUTES repliees par defaut a l'ouverture, "Application" y compris
        # — voir la remarque de l'utilisateur, "je veux que toutes les
        # sections (y compris sous sections) soient repliees a l'ouverture
        # de la fenetre de settings" (revient sur l'exception faite plus
        # haut pour "Application"). Fait AVANT la boucle ci-dessous : le
        # spaceur de chaque section lit is_collapsed() a sa creation pour
        # partir a la bonne hauteur.
        for section in sections:
            section.set_collapsed(self._mode != "general")
        for i, section in enumerate(sections):
            layout.addWidget(section)
            if i == len(sections) - 1:
                continue
            # Gap plus grand juste avant "Logiciel" (derniere section, voir
            # _SECTION_GAP_EXPANDED_LOGICIEL) — voir la remarque de
            # l'utilisateur.
            spacer = _make_gap_spacer(
                section, 1, 2 if i == len(sections) - 2 else 1)
            layout.addWidget(spacer)
        # Accordeon entre les sections PRINCIPALES elles-memes (voir
        # _make_accordion, deja applique aux sous-sections DANS chaque
        # section, voir _stack_subsections) — meme comportement, un seul
        # niveau plus haut.
        _make_accordion(sections)
        layout.addStretch(1)
        scroller.setWidget(inner)
        return scroller

    def _section_titre(self) -> _Section:
        """Section TITRE (voir _TITLE_LEVEL_STYLE/_title_font/_title_color/
        _title_indent) : police (GABARIT "police", voir
        _build_font_gabarit_row) + retrait (indentation, en px) des titres
        de _Section (niveau 1) et _SubSection (niveaux 2 a 5, profondeur
        d'imbrication croissante) de CETTE fenetre — voir la remarque de
        l'utilisateur, "je veux homogeneiser les textes des sections et
        sous sections"."""
        section = _Section("TITRE")
        font_rows: list[tuple[str, list[QWidget]]] = []
        indent_rows: list[tuple[str, QWidget]] = []
        gap_rows: list[tuple[str, list[QWidget]]] = []
        for level in (1, 2, 3, 4, 5):
            prefix = f"title_level{level}"
            family_field = _DualFontSelectField(
                self.settings.get(f"{prefix}_font_family") or "Systeme", width=150)
            bold_field = _Toggle(
                bool(self.settings.get(f"{prefix}_font_bold", True)), style_override="toggle2", show_label=False)
            italic_field = _Toggle(
                bool(self.settings.get(f"{prefix}_font_italic", False)), style_override="toggle2", show_label=False)
            size_field = _SliderField(
                6, 32, int(self.settings.get(f"{prefix}_font_size", 10)), slider_width=110, box_width=54)
            smoothing_field = _OverrideSmoothingField(
                bool(self.settings.get(f"{prefix}_font_smoothing_enabled", False)),
                self.settings.get(f"{prefix}_font_smoothing", "current"), show_title=False)
            color_field = _CompactAppOrCustomColorField(
                self.settings.get(f"{prefix}_font_color", "#d6d9dc"), self.settings["colors"],
                swatch_size=20, title=f"Couleur titre niveau {level}")
            indent_field = _SliderField(
                0, 120, int(self.settings.get(f"{prefix}_indent", 0)), slider_width=200, box_width=68)
            gap_fields = {}
            for gap_key, default in (("gap_collapsed", 0), ("gap_expanded", 0), ("gap_next", 6)):
                gap_fields[gap_key] = _SliderField(
                    0, 120, int(self.settings.get(f"{prefix}_{gap_key}", default)),
                    slider_width=90, box_width=56)
                setattr(self, f"{prefix}_{gap_key}_field", gap_fields[gap_key])
            gap_rows.append((f"Niveau {level}", [gap_fields["gap_collapsed"], gap_fields["gap_expanded"], gap_fields["gap_next"]]))
            setattr(self, f"{prefix}_font_family_field", family_field)
            setattr(self, f"{prefix}_font_bold_field", bold_field)
            setattr(self, f"{prefix}_font_italic_field", italic_field)
            setattr(self, f"{prefix}_font_size_field", size_field)
            setattr(self, f"{prefix}_font_smoothing_field", smoothing_field)
            setattr(self, f"{prefix}_font_color_field", color_field)
            setattr(self, f"{prefix}_indent_field", indent_field)
            font_rows.append((f"Police titre niveau {level}", [
                family_field, bold_field, italic_field, size_field, smoothing_field, color_field]))
            indent_rows.append((f"Retrait titre niveau {level} (indentation)", indent_field))
        # Polices et retraits dans deux sous-sections distinctes.
        subs = []
        self.title_font_table = _ControlsTable(
            [("Niveau", 150), ("Police", 330), ("Gras", 90), ("Italique", 90), ("Hauteur", 230),
             ("Niveau de lissage", 150), ("Couleur", 0)], font_rows)
        self.gap_table = _ControlsTable(
            [("Niveau", 150), ("Titre replié", 250), ("Titre déplié", 250), ("Avec le niveau suivant", 0)], gap_rows)
        for name, content in (("Polices", self.title_font_table), ("Retraits", indent_rows), ("Espacements", self.gap_table)):
            if isinstance(content, list):
                content, _, resizer = _build_flat_table(content)
                self._flat_resizers.append(resizer)
            sub = _SubSection(name, level=2)
            sub.add(content)
            sub.collapsedChanged.connect(section.refresh_min_height)
            subs.append(sub)
        self.titre_table_frame = subs[0]
        wrap = QWidget()
        wrap_l = QVBoxLayout(wrap)
        wrap_l.setContentsMargins(0, 0, 0, 0)
        _stack_subsections(wrap_l, subs)
        section.add(wrap)
        return section

    def _current_title_level_values(self) -> dict:
        """Valeurs COURANTES (widgets, pas self.settings) des 5 niveaux de
        TITRE — voir _apply_title_level_style, qui les fusionne par-dessus
        self.settings pour une previsualisation en direct SANS attendre
        Enregistrer."""
        out: dict[str, Any] = {}
        for level in (1, 2, 3, 4, 5):
            prefix = f"title_level{level}"
            family_field = getattr(self, f"{prefix}_font_family_field")
            out[f"{prefix}_font_family"] = "" if family_field.value() == "Systeme" else family_field.value()
            out[f"{prefix}_font_bold"] = getattr(self, f"{prefix}_font_bold_field").isChecked()
            out[f"{prefix}_font_italic"] = getattr(self, f"{prefix}_font_italic_field").isChecked()
            out[f"{prefix}_font_size"] = getattr(self, f"{prefix}_font_size_field").value()
            smoothing_field = getattr(self, f"{prefix}_font_smoothing_field")
            out[f"{prefix}_font_smoothing_enabled"] = smoothing_field.isChecked()
            out[f"{prefix}_font_smoothing"] = smoothing_field.smoothingValue()
            out[f"{prefix}_font_color"] = getattr(self, f"{prefix}_font_color_field").value()
            out[f"{prefix}_indent"] = getattr(self, f"{prefix}_indent_field").value()
            out[f"{prefix}_gap_collapsed"] = getattr(self, f"{prefix}_gap_collapsed_field").value()
            out[f"{prefix}_gap_expanded"] = getattr(self, f"{prefix}_gap_expanded_field").value()
            out[f"{prefix}_gap_next"] = getattr(self, f"{prefix}_gap_next_field").value()
        return out

    def _apply_title_level_style(self, *_args):
        """Rejoue _TITLE_LEVEL_STYLE avec les valeurs COURANTES des widgets
        (voir _current_title_level_values) puis restyle TOUTES les _Section/
        _SubSection DEJA construites de cette fenetre — meme necessite que
        _on_colors_changed/_apply_slider_style (widgets DEJA a l'ecran, pas
        seulement les prochains construits)."""
        merged = dict(self.settings)
        merged.update(self._current_title_level_values())
        _sync_title_level_style(merged)
        for section in self.findChildren(_Section):
            section._name_label.setFont(_title_font(1))
            section._name_label.setStyleSheet(f"color: {_title_color(1)}; background: transparent;")
            section._chevron.setColor(_title_color(1))
            indent = _title_indent(1)
            section._title_indent = indent
            section._head_layout.setContentsMargins(indent, 0, 0, 0 if section._collapsed else _title_gap_next(1))
            section.set_body_offset(indent + 16 + 10)
        for sub in self.findChildren(_SubSection):
            level = sub._level
            sub._name_label.setFont(_title_font(level))
            sub._name_label.setStyleSheet(f"color: {_title_color(level)}; background: transparent;")
            sub._chevron.setColor(_title_color(level))
            indent = _subsection_left_margin(level)
            sub._left_margin = indent
            sub._head_layout.setContentsMargins(indent, 0, 0, 0 if sub._collapsed else _title_gap_next(level))
            sub.set_body_offset(indent + 11 + 6)
        _refresh_gap_spacers(self)
        _reflow_all(self)
        self._mark_dirty()

    def _section_application(self) -> _Section:
        section = _Section("Application")

        self.root_field = QLineEdit(self.settings["root_path"])
        self.root_field.setFont(_qfont(12, 400, mono=True))
        self.root_field.setFixedSize(268, 25)
        self._refresh_root_field_style()
        # radius=self.settings[...] (self.geo_table pas encore construit a
        # ce stade — voir _apply_button_radius pour le suivi en direct).
        browse_btn = _Btn("Parcourir", M["btn_bg"], M["btn_border"], M["btn_fg"], M["btn_hover"], height=25)
        browse_btn.clicked.connect(self._browse_root)
        self._browse_btn = browse_btn
        # Largeur FIXE (pas le sizeHint naturel du bouton) : le bloc de
        # controle de cette ligne (champ+bouton = 268+6+84 = 358) doit faire
        # exactement la meme largeur totale que celui de "Scale interface"
        # juste en dessous (slider 280 + espacement 10 + boite 68 = 358),
        # sans quoi les deux lignes ne s'alignent ni a gauche ni a droite
        # (voir la remarque de l'utilisateur, capture a l'appui).
        browse_btn.setFixedWidth(84)
        root_row = QWidget()
        root_row_l = QHBoxLayout(root_row)
        root_row_l.setContentsMargins(0, 0, 0, 0)
        root_row_l.setSpacing(6)
        root_row_l.addWidget(self.root_field)
        root_row_l.addWidget(browse_btn)

        # Preset par defaut (voir load_settings/DEFAULT_SETTINGS.
        # default_preset) : applique AUTOMATIQUEMENT par-dessus pipeline_
        # settings.json a chaque demarrage de l'appli ET ouverture de cette
        # fenetre — voir la remarque de l'utilisateur, "dans general/
        # application, sous racine par defaut, je veux un parametre preset
        # par defaut, avec menu deroulant de tous les presets". "(Aucun)" =
        # comportement INCHANGE, pipeline_settings.json seul fait foi.
        preset_names = ["(Aucun)"] + sorted(_load_presets().keys())
        self.default_preset_field = _SelectField(
            preset_names, self.settings.get("default_preset") or "(Aucun)", width=268)

        self.scale_field = _SliderField(50, 200, int(self.settings["ui_scale"]), "%", slider_width=280, box_width=68)

        # Repli automatique des colonnes de set (voir DEFAULT_SETTINGS.
        # auto_collapse_set_columns/app_style.set_auto_collapse_set_columns/
        # pipeline_browser._sync_collapse_state) — voir la remarque de
        # l'utilisateur, "un toggle qui permet ou pas de rabattre les
        # colonnes de set, une fois que l'on est sur l'espace de travail".
        self.auto_collapse_set_columns_field = _Toggle(
            bool(self.settings.get("auto_collapse_set_columns", True)))

        self.omit_dir_names_field = _OmitListField(self)
        self.omit_dir_names_field.set_values(self.settings.get("application_omit_dir_names"))
        self.omit_file_names_field = _OmitListField(self)
        self.omit_file_names_field.set_values(_omit_file_values(self.settings))
        self.omit_file_names_field.setToolTip(
            "Nom exact de fichier, ou *.extension pour masquer toute une extension.")
        self.omit_filters_table = QWidget()
        omit_row = QHBoxLayout(self.omit_filters_table)
        omit_row.setContentsMargins(0, 0, 0, 0)
        omit_row.setSpacing(10)
        for title, field in (("Dossiers à omettre", self.omit_dir_names_field),
                             ("Fichiers à omettre", self.omit_file_names_field)):
            column = QVBoxLayout()
            column.setSpacing(5)
            label = QLabel(title)
            label.setFont(_qfont(9, 600))
            label.setStyleSheet(f"color: {C['label']}; background: transparent;")
            column.addWidget(label)
            column.addWidget(field)
            omit_row.addLayout(column, 1)

        # "Coins arrondi" (ex-Geometrie > Fenetres, un slider de rayon, puis
        # "Fenetre" une fois deplacee ici) — voir la remarque de
        # l'utilisateur, "geometrie/fenetre : deplace cette ligne dans
        # general/application mais transforme le slider en toggle", puis
        # "fenetre : renommer 'Coins arrondi'. Placer le toggle avant le
        # texte" : simple on/off (voir _window_radius_value, rayon fixe
        # _WINDOW_RADIUS_ON quand actif), toggle SANS libelle integre —
        # place ici AVANT un QLabel dedie, plutot que la colonne "libelle
        # a gauche / controle a droite" habituelle du tableau.
        self.window_radius_toggle = _Toggle(int(self.settings.get("window_radius", 0)) > 0, show_label=False)
        window_radius_row = QWidget()
        window_radius_row.setStyleSheet("background: transparent;")
        window_radius_row_l = QHBoxLayout(window_radius_row)
        window_radius_row_l.setContentsMargins(0, 0, 0, 0)
        window_radius_row_l.setSpacing(8)
        window_radius_row_l.addWidget(self.window_radius_toggle)
        window_radius_label = QLabel("Coins arrondi")
        _set_text_role(window_radius_label, "row_label")
        window_radius_row_l.addWidget(window_radius_label)
        window_radius_row_l.addStretch(1)

        # Tableau ferme (voir _build_flat_table — meme technique que
        # Colonnes/Sliders) plutot que 2 _Row nues, pour rester coherent
        # avec le reste de la fenetre — voir la remarque de l'utilisateur.
        self.app_table_frame, _, resizer = _build_flat_table([
            ("Racine par defaut", root_row),
            ("Preset par defaut", self.default_preset_field),
            ("Scale interface", self.scale_field),
            ("Replier les colonnes de set une fois l'espace de travail atteint",
             self.auto_collapse_set_columns_field),
            ("", window_radius_row),
        ])
        self._flat_resizers.append(resizer)
        section.add(self.app_table_frame)
        return section

    def _section_lut(self) -> _Section:
        section = _Section("LUT")
        self.lut_images_field = LutTestImagesField(self)
        self.lut_images_field.set_values(
            self.settings.get("lut_test_images"), self.settings.get("lut_default_image") or "",
            self.settings.get("lut_image_curves"))
        self.lut_help = _text_label(LUT_HELP_TEXT, "note")
        self.lut_help.setWordWrap(True)
        self.lut_help.setFixedWidth(LutTestImagesField._WIDTH)
        # Pas de tableau : un bloc unique aligne a gauche (comme "Dossiers et
        # fichiers a omettre"), la colonne de valeurs d'un tableau serait trop etroite.
        self.lut_block = QWidget()
        lut_block_l = QVBoxLayout(self.lut_block)
        lut_block_l.setContentsMargins(0, 0, 0, 0)
        lut_block_l.setSpacing(10)
        lut_block_l.addWidget(self.lut_help, 0, Qt.AlignLeft)
        lut_block_l.addWidget(self.lut_images_field, 0, Qt.AlignLeft)
        section.add(self.lut_block)
        return section

    def _section_omit(self) -> _Section:
        section = _Section("Dossiers et fichiers à omettre")
        section.add(self.omit_filters_table)
        return section

    def _section_fonts(self) -> _Section:
        section = _Section("Polices principales")
        self.font_table = _SimpleFontTable(self.settings)
        section.add(self.font_table)
        return section

    def _section_colors(self) -> _Section:
        section = _Section("Couleurs")
        self.color_grid = _ColorGrid(self.settings["colors"])
        section.add(self.color_grid)
        return section

    def _build_selection_clone_subsection(
        self, state: str, title: str, color_label: str, color_field: QWidget
    ) -> _SubSection:
        """Sous-section "Non focus"/"Survol"/"Non selectionne" (voir
        _section_headers, la remarque de l'utilisateur, "non focus survol
        et non selectionne sont des clones des focus (sauf la couleur)
        donc mets leur des toggles d'override exactement comme dans
        colonnes/projets/colonnes") : SA PROPRE couleur (`color_field`,
        deja construit par l'appelant, jamais un override — chaque etat a
        toujours eu sa propre couleur) + 4 parametres CLONES de Focus
        (padding/bordure/rayon/bord de colonne), chacun avec un toggle
        d'override — memes widgets que Focus, MEME mecanique de toggle que
        _build_override_flat_table (Colonnes > Type/Projets/Sous-projets).
        Champs stockes sur `self` comme `item_selection_<state>_<key>_
        field`/`_toggle`, lus par _current_values/_apply_values_to_controls."""
        def make_toggle(key: str) -> _Toggle:
            toggle = _Toggle(
                bool(self.settings.get(f"item_selection_{state}_{key}_override", False)), style_override="toggle1")
            setattr(self, f"item_selection_{state}_{key}_toggle", toggle)
            return toggle

        padding_toggle = make_toggle("padding")
        padding_field = _CellPaddingField(
            bool(self.settings.get(f"item_selection_{state}_padding_linked", False)),
            self.settings.get(f"item_selection_{state}_padding") or {})
        setattr(self, f"item_selection_{state}_padding_field", padding_field)

        border_toggle = make_toggle("border")
        border_field = _ToggleSideColorsField(
            _coerce_side_enabled(self.settings.get(f"item_selection_{state}_border_enabled", False)),
            self.settings.get(f"item_selection_{state}_border") or {}, self.settings["colors"])
        setattr(self, f"item_selection_{state}_border_field", border_field)

        radius_toggle = make_toggle("radius")
        radius_field = _CornerRadiusField(
            bool(self.settings.get(f"item_selection_{state}_radius_linked", True)),
            _coerce_corner_radius(self.settings.get(f"item_selection_{state}_radius", 0)), maximum=20)
        setattr(self, f"item_selection_{state}_radius_field", radius_field)

        edge_toggle = make_toggle("edge_border")
        edge_field = _Toggle(
            bool(self.settings.get(f"item_selection_{state}_edge_border", True)), style_override="toggle1")
        setattr(self, f"item_selection_{state}_edge_border_field", edge_field)

        color_frame, color_row_meta, color_resizer = _build_flat_table([(color_label, color_field)])
        self._flat_resizers.append(color_resizer)
        setattr(self, f"item_selection_{state}_color_frame", color_frame)

        override_frame, override_row_meta, override_resizer = _build_override_flat_table([
            ("Padding du selecteur", padding_field, padding_toggle),
            ("Bordures du selecteur", border_field, border_toggle),
            ("Arrondi des coins de la selection", radius_field, radius_toggle),
            ("Bordure au bord de la colonne", edge_field, edge_toggle),
        ])
        self._flat_resizers.append(override_resizer)
        setattr(self, f"item_selection_{state}_override_frame", override_frame)

        sub = _SubSection(title, level=3)
        sub.add(color_frame)
        sub.add(override_frame)
        return sub

    def _section_headers(self) -> _Section:
        section = _Section("Colonnes")
        # Afficher/masquer l'entete entierement (voir pipeline_browser.
        # Column/DetailPanel/PreviewColumn.refresh_header, header.setVisible)
        # — voir la remarque de l'utilisateur, "je veux aussi une option
        # dans les entetes, toggle on off, pour afficher ou non les
        # entetes". Surchargeable PAR TITRE comme le reste de cette section
        # (voir header_visible dans app_style.COLUMN_FRAME_KEYS).
        self.header_visible_field = _Toggle(bool(self.settings.get("header_visible", True)), style_override="toggle1")
        self.header_height_field = _SliderField(16, 56, int(self.settings["header_height"]), slider_width=280, box_width=68)
        self.header_padding_field = _SliderField(0, 32, int(self.settings.get("header_padding", 0)), slider_width=280, box_width=68)
        self.header_color_field = _HeaderColorField(self.settings["colors"], self.settings.get("header_color", "skinN1"))
        # Rayon PAR COIN (voir _CornerRadiusField — MEME widget/mecanique
        # que le padding des cellules, un coin peut piloter les 3 autres
        # via le lien "lie"/"libre" ou "Copier" — voir la remarque de
        # l'utilisateur, "dans tous les parametres de coins arrondis, je
        # veux exactement le meme fonctionnement que les padding (un par
        # coin)").
        self.header_radius_field = _CornerRadiusField(
            bool(self.settings.get("header_radius_linked", True)),
            _coerce_corner_radius(self.settings.get("header_radius", 0)), maximum=16)
        # Bordure des entetes (voir _ToggleSideColorsField) — MEME widget/
        # memes parametres que Colonnes > Bordure ci-dessous (toggle par
        # cote + couleur independante par cote + epaisseur partagee) — voir
        # la remarque de l'utilisateur, "renomme le parametre 'cadre des
        # entetes' -> 'Bordure' ... je veux exactement les memes parametre
        # de controle que celui des colonnes" (remplace _HeaderEdgesField,
        # une seule couleur partagee + simple on/off par cote).
        self.header_border_thickness_field = _SliderField(
            0, 8, int(self.settings.get("header_border_thickness", 1)), slider_width=140, box_width=54)
        self.header_border_field = _ToggleSideColorsField(
            _coerce_side_enabled(self.settings.get("header_border_enabled")
                                  or self.settings.get("header_edges") or {}, default=False),
            self.settings.get("header_border") or {}, self.settings["colors"],
            thickness_field=self.header_border_thickness_field)
        # Padding droit des icones dans la barre des entetes (voir
        # Column.__init__, bouton punaise — pipeline_browser._pin_icon_
        # pixmap) : espace reserve entre l'icone et le bord droit de
        # l'entete — voir la remarque de l'utilisateur, "ajoute un slider
        # pour le padding droit des icones dans la barre des entetes".
        self.header_icon_right_padding_field = _SliderField(
            0, 40, int(self.settings.get("header_icon_right_padding", 0)), slider_width=280, box_width=68)
        # Police/gras/couleur du TITRE de l'entete (voir Column.title_label)
        # — MEME trio que partout ailleurs — voir la remarque de
        # l'utilisateur, "ajoute : choix de la police (entre systeme et
        # app) + gras ou regular et couleur (sur la mm ligne)".
        self.header_font_family_field = _DualFontSelectField(
            self.settings.get("header_font_family") or "Systeme", width=130)
        self.header_font_bold_field = _Toggle(
            bool(self.settings.get("header_font_bold", True)), show_label=False)
        self.header_font_italic_field = _Toggle(
            bool(self.settings.get("header_font_italic", False)), show_label=False)
        self.header_font_color_field = _CompactAppOrCustomColorField(
            self.settings.get("header_font_color", "#9aa1a7"), self.settings["colors"],
            swatch_size=20, title="Couleur du titre")
        # Hauteur (taille) de la police, AJOUTEE sur cette meme ligne — voir
        # la remarque de l'utilisateur, "pour la police dans les entetes
        # ajoute aussi sur la ligne des polices, la hauteur des polices".
        self.header_font_size_field = _SliderField(
            6, 24, int(self.settings.get("header_font_size", 10)), slider_width=110, box_width=54)
        # Lissage (GABARIT "police") — absent jusqu'ici de cette ligne.
        self.header_font_smoothing_field = _OverrideSmoothingField(
            bool(self.settings.get("header_font_antialias_override_enabled", False)),
            self.settings.get("header_font_antialias_override", "current"))
        header_font_row = _build_font_gabarit_row(
            self.header_font_family_field, self.header_font_bold_field, self.header_font_size_field,
            self.header_font_smoothing_field, self.header_font_color_field,
            italic_field=self.header_font_italic_field)
        # Distance entre colonnes (voir app_style.set_column_gap/
        # pipeline_browser.PipelineBrowser.columns_layout) — voir la
        # remarque de l'utilisateur, "ajoute un parametre 'distance entre
        # colonne' en px". Minimum -1 (pas 0) : chaque colonne a deja son
        # propre filet de separation de 1px (voir Column, sep_v) — un
        # espacement de -1 les superpose au lieu de les cumuler en un
        # filet de 2px visible, voir la remarque de l'utilisateur, "de
        # maniere a ce que les bordures ne se cumulent pas".
        # Largeur par defaut d'une colonne (voir pipeline_browser.COLUMN_
        # SETTINGS/col_width/apply_all_settings) — 1er parametre de la table
        # Colonnes (voir columns_frame juste plus bas) : premiere chose
        # qu'on regle en ouvrant une colonne, avant meme son espacement des
        # voisines — voir la remarque de l'utilisateur, "je veux controler
        # ce parametre dans general/colonnes/colonnes/colonnes et que ce
        # soit le premier parametre de la liste". Surchargeable PAR TITRE
        # (Colonnes > Type/Projets/Sous-projets, voir _build_column_
        # override_page) comme le reste de cette table.
        self.item_column_width_field = _SliderField(
            120, 640, int(self.settings.get("item_column_width", 180)), slider_width=280, box_width=68)
        self.column_gap_field = _SliderField(
            0, 40, max(0, int(self.settings.get("column_gap", 0))), slider_width=280, box_width=68)
        # Padding de la colonne (voir _ColumnPreview.setPadding) — MEME
        # widget que Tableaux > Padding des cellules (_CellPaddingField, un
        # par cote), un niveau au-dessus de Entetes > Padding des entetes :
        # insere TOUT le contenu de la colonne (entete + corps) en retrait
        # de son cadre exterieur — voir la remarque de l'utilisateur, "je
        # veux un padding (de la mm maniere que le padding des entetes :
        # selection pour les 4 cotes)".
        self.column_padding_field = _CellPaddingField(
            bool(self.settings.get("column_padding_linked", True)),
            self.settings.get("column_padding") or {},
        )
        # Bordure des colonnes (voir _ColumnPreview.setBorder) — MEME widget
        # que Toggles > Cadre/Coche > Bordure (_ToggleSideColorsField) : voir
        # la remarque de l'utilisateur, "ajoute moi un parametre de bordure
        # exactement le meme que toggle" ; un toggle par cote (pas un
        # interrupteur global) + epaisseur/rayon (voir la remarque de
        # l'utilisateur, "ajoute une valeur de bordure radius, la largeur de
        # bordure") — meme paire de reglages que Toggles > Cadre > Epaisseur
        # de bordure/Rayon des angles.
        self.column_border_thickness_field = _SliderField(
            0, 8, int(self.settings.get("column_border_thickness", 1)), slider_width=140, box_width=54)
        self.column_border_field = _ToggleSideColorsField(
            _coerce_side_enabled(self.settings.get("column_border_enabled", True)),
            self.settings.get("column_border") or {}, self.settings["colors"],
            thickness_field=self.column_border_thickness_field)
        self.column_border_radius_field = _CornerRadiusField(
            bool(self.settings.get("column_border_radius_linked", True)),
            _coerce_corner_radius(self.settings.get("column_border_radius", 0)), maximum=20)
        # Couleur de fond de la colonne (voir app_style.column_frame_style,
        # cle "bg", "@skinN2" par defaut = C["void"], comportement INCHANGE
        # tant que non personnalise) — voir la remarque de l'utilisateur,
        # "dans la section general/colonne/colonne je veux un parametre
        # couleur de fond". _AppOrCustomColorField (comme item_idle_color) :
        # une pastille de l'appli OU une couleur libre.
        self.column_bg_color_field = _AppOrCustomColorField(
            self.settings.get("column_bg_color", "@skinN2"), self.settings["colors"],
            swatch_size=24, title="Fond de colonne")

        # 2 tableaux distincts (voir _build_flat_table — meme technique que
        # Polices/Geometrie) — un pour les reglages de la COLONNE elle-meme,
        # un pour ceux de son ENTETE — voir la remarque de l'utilisateur,
        # "fait deux tableaux plutot qu'un, avec pour le premier tous les
        # parametres relatifs aux colonnes, et le deuxieme tout ce qui est
        # relatif aux entetes" (auparavant un seul tableau melangeant les 2).
        # Cote a cote (voir _build_toggle_shape_tables/_section_slider, meme
        # technique deja utilisee pour Toggles > Cadre/Coche et Sliders >
        # Rail/Selecteur) — voir la remarque de l'utilisateur, "peux tu
        # mettre ces tableaux cote a cote stp".
        columns_frame, _, columns_resizer = _build_flat_table([
            ("Largeur par defaut", self.item_column_width_field),
            ("Distance entre colonnes", self.column_gap_field),
            ("Padding", self.column_padding_field),
            ("Couleur de fond", self.column_bg_color_field),
            ("Bordure", self.column_border_field),
            ("Rayon des angles de bordure", self.column_border_radius_field),
        ])
        self._flat_resizers.append(columns_resizer)
        self.columns_table_frame = columns_frame
        columns_sub = _SubSection("Colonnes", level=2)
        columns_sub.add(columns_frame)
        columns_sub.collapsedChanged.connect(section.refresh_min_height)

        # Cadre de redimensionnement (voir pipeline_browser._show_resize_
        # width/_resize_width_indicator, le badge flottant affichant la
        # largeur/hauteur en px pendant un glisser de bordure de colonne) —
        # voir la remarque de l'utilisateur, "je veux que dans general/
        # colonnes/ tu crees une sous section cadre de redimensionnement
        # avec comme parametres : position (toggles) BD BG HD HG / police /
        # couleur de fond / bordure / epaisseur bordure / corner radius".
        self.resize_badge_position_field = _ResizeBadgePositionField(
            self.settings.get("resize_badge_position", "bottom_right"),
            int(self.settings.get("resize_badge_offset_x", 8)),
            int(self.settings.get("resize_badge_offset_y", 8)))
        # Police : choix "polices du soft"/"polices systeme" (voir
        # _DualFontSelectField), COMME les autres sections (Colonnes >
        # Type > Texte > Police, etc.) — voir la remarque de l'utilisateur,
        # "pour la police, je veux comme les autres section le choix entre
        # les police appli et systeme". Couleur du TEXTE (distincte de
        # "Couleur de fond" plus bas) : app OU personnalisee, meme widget
        # — voir la remarque de l'utilisateur, "ainsi que la couleur
        # (couleurs app ou personnalisees)".
        self.resize_badge_font_field = _DualFontSelectField(
            self.settings.get("resize_badge_font_family") or "Systeme", width=150)
        self.resize_badge_font_bold_field = _Toggle(
            bool(self.settings.get("resize_badge_font_bold", True)), show_label=False)
        self.resize_badge_font_italic_field = _Toggle(
            bool(self.settings.get("resize_badge_font_italic", False)), show_label=False)
        self.resize_badge_font_size_field = _SliderField(
            6, 24, int(self.settings.get("resize_badge_font_size", 11)), slider_width=110, box_width=54)
        self.resize_badge_font_smoothing_field = _OverrideSmoothingField(
            bool(self.settings.get("resize_badge_font_smoothing_enabled", False)),
            self.settings.get("resize_badge_font_smoothing", "current"))
        self.resize_badge_text_color_field = _CompactAppOrCustomColorField(
            self.settings.get("resize_badge_text_color", "#d6d9dc"), self.settings["colors"],
            swatch_size=20, title="Texte du cadre de redimensionnement")
        resize_badge_font_row = _build_font_gabarit_row(
            self.resize_badge_font_field, self.resize_badge_font_bold_field, self.resize_badge_font_size_field,
            self.resize_badge_font_smoothing_field, self.resize_badge_text_color_field,
            italic_field=self.resize_badge_font_italic_field)
        self.resize_badge_bg_color_field = _AppOrCustomColorField(
            self.settings.get("resize_badge_bg_color", "#202326"), self.settings["colors"],
            swatch_size=24, title="Fond du cadre de redimensionnement")
        self.resize_badge_border_thickness_field = _SliderField(
            0, 8, int(self.settings.get("resize_badge_border_thickness", 1)), slider_width=140, box_width=54)
        self.resize_badge_border_field = _ToggleSideColorsField(
            _coerce_side_enabled(self.settings.get("resize_badge_border_enabled", True)),
            self.settings.get("resize_badge_border") or {}, self.settings["colors"],
            thickness_field=self.resize_badge_border_thickness_field)
        self.resize_badge_border_radius_field = _CornerRadiusField(
            bool(self.settings.get("resize_badge_border_radius_linked", True)),
            _coerce_corner_radius(self.settings.get("resize_badge_border_radius", 4)), maximum=20)

        resize_badge_frame, _, resize_badge_resizer = _build_flat_table([
            ("Position", self.resize_badge_position_field),
            ("Police", resize_badge_font_row),
            ("Couleur de fond", self.resize_badge_bg_color_field),
            ("Bordure", self.resize_badge_border_field),
            ("Rayon des angles", self.resize_badge_border_radius_field),
        ])
        self._flat_resizers.append(resize_badge_resizer)
        self.resize_badge_table_frame = resize_badge_frame
        resize_badge_sub = _SubSection("Encart", level=2)
        resize_badge_sub.add(resize_badge_frame)
        resize_badge_sub.collapsedChanged.connect(section.refresh_min_height)

        headers_frame, _, headers_resizer = _build_flat_table([
            ("Afficher", self.header_visible_field),
            ("Hauteur des entetes", self.header_height_field),
            ("Padding des entetes", self.header_padding_field),
            ("Couleur des entetes", self.header_color_field),
            ("Arrondi des angles", self.header_radius_field),
            ("Bordure", self.header_border_field),
            ("Padding droit des icones", self.header_icon_right_padding_field),
            ("Police / gras / couleur / hauteur du titre", header_font_row),
        ])
        self._flat_resizers.append(headers_resizer)
        self.headers_table_frame = headers_frame
        headers_sub = _SubSection("Entetes", level=2)
        headers_sub.add(headers_frame)
        headers_sub.collapsedChanged.connect(section.refresh_min_height)


        # Items texte des colonnes (nom de fichier/dossier affiche dans
        # chaque ligne) — voir la remarque de l'utilisateur, "ajoute un
        # tableau pour les items textes dans les colonnes ... ces deux
        # tableaux font partie de la section colonnes" (fusionnes ici avec
        # Colonnes/Entetes ci-dessus, PAS une section a part comme une
        # 1ere version l'avait fait). 2 tableaux cote a cote de plus (meme
        # technique) : reglages du TEXTE de la ligne, puis de sa SELECTION
        # (couleurs focus/hors focus/survol, padding a 4 cotes — MEME
        # widget que Tableaux > Padding des cellules, voir
        # _CellPaddingField — bordure — MEME widget que Sliders > Rail/
        # Selecteur, voir _ToggleSideColorsField — rayon, et un filet
        # optionnel au croisement avec le bord de la colonne). PAS de
        # widget d'apercu separe ici (une 1ere version en ajoutait un,
        # _ItemRowPreview, flottant au milieu de la section) — voir
        # _ColumnPreview.setItemStyle/_apply_item_preview : l'apercu se
        # fait directement sur les 3 boites Type/Projets/Sous-projet DEJA
        # utilisees par Colonnes/Entetes plus haut, voir la remarque de
        # l'utilisateur, "l'apercu doit se faire sur les colonnes deja
        # existantes".

        self.item_font_field = _DualFontSelectField(
            self.settings.get("item_font_family") or "Systeme", width=150)
        # Taille du texte des items (voir pipeline_browser.
        # _resolve_row_font_color, fixe a 10 en dur jusqu'ici) — voir la
        # remarque de l'utilisateur, "ajoute taille" a cote de Police.
        self.item_font_size_field = _SliderField(
            6, 24, int(self.settings.get("item_font_size", 10)), slider_width=140, box_width=54)
        # Gras (voir pipeline_browser._resolve_row_font_color) — voir la
        # remarque de l'utilisateur, "j'aimerais rajouter une option pour
        # mettre le texte en gras (toggle)".
        self.item_font_bold_field = _Toggle(
            bool(self.settings.get("item_font_bold", False)), style_override="toggle1", show_label=False)
        # Italique (GABARIT "police", voir _build_font_gabarit_row et la
        # remarque de l'utilisateur, capture d'ecran, "voici a quoi doit
        # ressembler la ligne police" — ajoute "italique" a cote de
        # "gras").
        self.item_font_italic_field = _Toggle(
            bool(self.settings.get("item_font_italic", False)), style_override="toggle1", show_label=False)
        # Toggle "Forcer" + slider Lissage (voir _OverrideSmoothingField) :
        # par defaut suit le lissage habituel de l'appli, le toggle permet
        # de le forcer independamment pour ce texte — voir la remarque de
        # l'utilisateur, "toggle + override l'antialiasing".
        self.item_antialias_field = _OverrideSmoothingField(
            bool(self.settings.get("item_antialias_override_enabled", False)),
            self.settings.get("item_antialias_override", "current"))
        # Espace avant le 1er item (voir pipeline_browser.Column.
        # header_gap_spacer) — distinct de "Espacement entre les lignes"
        # (entre CHAQUE item, celui-ci seulement AVANT le 1er) — voir la
        # remarque de l'utilisateur, "ajoute un slider qui cree un espace
        # entre l'entete et le premier item de la liste".
        self.item_header_gap_field = _SliderField(
            0, 40, int(self.settings.get("item_header_gap", 0)), slider_width=200, box_width=68)

        # Champs "item_*" simples (couleur/toggle/slider) construits depuis
        # _ITEM_TEXT_FIELD_SPECS (voir sa remarque de tete) : y ajouter une
        # entree suffit a la faire apparaitre ici ET dans Colonnes > Type
        # (_build_column_type_page), sans autre modification de cette
        # methode — inclut "Bordure entre les lignes"/"Couleur de
        # bordure"/"Epaisseur de bordure" (voir la remarque de
        # l'utilisateur, "rajoute une option pour ajouter une bordure entre
        # les lignes avec choix de la couleur ... et de l'epaisseur").
        # Index : 0 Couleur, 1 Hauteur de la ligne, 2 Taille de l'icone,
        # 3 Padding gauche de l'icone, 4 Espacement entre les lignes,
        # 5 Padding du texte.
        item_text_rows = []
        for spec in _ITEM_TEXT_FIELD_SPECS:
            field = spec.make_field(self.settings.get(spec.key, spec.default), self.settings["colors"], slider_width=200)
            setattr(self, _ITEM_TEXT_FIELD_ATTR[spec.key], field)
            item_text_rows.append((spec.label, field))

        # Toggle + couleur + epaisseur du filet ENTRE les lignes, TOUS DANS
        # LA MEME ligne (voir _RowBorderField) — voir la remarque de
        # l'utilisateur, "rajoute une option pour ajouter une bordure entre
        # les lignes avec choix de la couleur ... et de l'epaisseur", puis
        # "rassemble bordure couleur et epaisseur dans une seule ligne".
        self.item_row_border_field = _RowBorderField(
            bool(self.settings.get("item_row_border_enabled", False)),
            self.settings.get("item_row_border_color", "@ligne"),
            int(self.settings.get("item_row_border_thickness", 1)),
            self.settings["colors"],
        )

        # Ex-sous-section unique "Texte", desormais scindee en 4 sous-
        # sous-sections IMBRIQUEES dans "Lignes" (voir la remarque de
        # l'utilisateur, "renomme la 'lignes' et fait 4 sous sections" —
        # meme mecanique de 2e niveau que Colonnes > Selection ci-dessous).

        # 1) "Lignes" : hauteur, espacement, espace avant le 1er item,
        # bordure entre les lignes.
        lines_frame, _, lines_resizer = _build_flat_table([
            ("Hauteur de ligne", item_text_rows[1][1]),
            ("Espacement entre les lignes", item_text_rows[4][1]),
            ("Espace avant le premier item", self.item_header_gap_field),
            ("Bordure entre les lignes", self.item_row_border_field),
        ])
        self._flat_resizers.append(lines_resizer)
        self.item_lines_frame = lines_frame
        lines_2nd_sub = _SubSection("Lignes", level=3)
        lines_2nd_sub.add(lines_frame)

        # 2) "Texte" : gabarit "police" (voir _build_font_gabarit_row) +
        # "Padding gauche" (ex-"Padding du texte", item_text_padding).
        item_police_row = _build_font_gabarit_row(
            self.item_font_field, self.item_font_bold_field, self.item_font_size_field,
            self.item_antialias_field, item_text_rows[0][1], italic_field=self.item_font_italic_field)
        text_frame, _, text_resizer = _build_flat_table([
            ("Police", item_police_row),
            ("Padding gauche", item_text_rows[5][1]),
        ])
        self._flat_resizers.append(text_resizer)
        self.item_text_frame = text_frame
        text_2nd_sub = _SubSection("Texte", level=3)
        text_2nd_sub.add(text_frame)

        # 3) "Icone" : taille par defaut + padding gauche.
        icon_frame, _, icon_resizer = _build_flat_table([
            ("Taille de l'icone par defaut (0 = hauteur de la ligne)", item_text_rows[2][1]),
            ("Padding gauche", item_text_rows[3][1]),
        ])
        self._flat_resizers.append(icon_resizer)
        self.item_icon_frame = icon_frame
        icon_2nd_sub = _SubSection("Icone", level=3)
        icon_2nd_sub.add(icon_frame)

        # 4) "Apercu" — ex-sous-section "Image" (voir la remarque de
        # l'utilisateur, "ajoute une sous section image ... padding de
        # l'image ... bordure de l'image ... corner radius de l'image"),
        # CONTENU INCHANGE, seul le ratio devient un affichage "1/<valeur>"
        # (voir _RatioSliderField) au lieu d'un pourcentage brut — voir la
        # remarque de l'utilisateur, "avant l'invite place le texte '1/'
        # ... dans l'invite on entre la valeur de largeur (par exemple
        # 2.35)".
        self.item_image_padding_field = _CellPaddingField(
            bool(self.settings.get("item_image_padding_linked", True)),
            self.settings.get("item_image_padding") or {},
        )
        self.item_image_border_thickness_field = _SliderField(
            0, 8, int(self.settings.get("item_image_border_thickness", 1)), slider_width=140, box_width=54)
        self.item_image_border_field = _ToggleSideColorsField(
            _coerce_side_enabled(self.settings.get("item_image_border_enabled", False)),
            self.settings.get("item_image_border") or {}, self.settings["colors"],
            thickness_field=self.item_image_border_thickness_field)
        self.item_image_radius_field = _CornerRadiusField(
            bool(self.settings.get("item_image_radius_linked", True)),
            _coerce_corner_radius(self.settings.get("item_image_radius", 0)), maximum=20)
        self.item_image_ratio_field = _RatioSliderField(
            20, 500, int(round(float(self.settings.get("item_image_ratio", 1.0)) * 100)),
            slider_width=200, box_width=68)

        image_frame, _, image_resizer = _build_flat_table([
            ("Padding", self.item_image_padding_field),
            ("Bordure", self.item_image_border_field),
            ("Rayon des angles", self.item_image_radius_field),
            ("Ratio (largeur/hauteur)", self.item_image_ratio_field),
        ])
        self._flat_resizers.append(image_resizer)
        self.item_image_frame = image_frame
        apercu_2nd_sub = _SubSection("Apercu", level=3)
        apercu_2nd_sub.add(image_frame)

        # Empilage des 4 sous-sous-sections DANS "Lignes" (meme mecanique
        # que Colonnes > Selection > Focus/Non focus/Survol/Non
        # selectionne).
        lines_group_wrap = QWidget()
        lines_group_wrap.setStyleSheet("background: transparent;")
        lines_group_wrap_l = QVBoxLayout(lines_group_wrap)
        lines_group_wrap_l.setContentsMargins(0, 0, 0, 0)
        _stack_subsections(
            lines_group_wrap_l, [lines_2nd_sub, text_2nd_sub, icon_2nd_sub, apercu_2nd_sub])
        text_sub = _SubSection("Lignes", level=2)
        text_sub.add(lines_group_wrap)
        text_sub.collapsedChanged.connect(section.refresh_min_height)
        for sub in (lines_2nd_sub, text_2nd_sub, icon_2nd_sub, apercu_2nd_sub):
            sub.collapsedChanged.connect(text_sub.refresh_layout)

        # "Focus" : la BASE (voir pipeline_browser._paint_unified_row,
        # `_shape`) — Non focus/Survol/Non selectionne EN HERITENT SAUF
        # override explicite (voir _build_selection_clone_subsection plus
        # bas) — voir la remarque de l'utilisateur, "fais 4 sous sections,
        # focus, non focus, survol et non selectionne ... non focus survol
        # et non selectionne sont des clones des focus (sauf la couleur)
        # donc mets leur des toggles d'override exactement comme dans
        # colonnes/projets/colonnes".
        self.item_selection_focus_field = _ColorField(
            self.settings.get("item_selection_focus_color", "#3f6f9f"), swatch_size=24, title="Selection (focus)")
        # MEME widget que Tableaux > Padding des cellules (voir la remarque
        # de l'utilisateur, "padding du selecteur (4 sliders identique aux
        # tableaux)").
        self.item_selection_padding_field = _CellPaddingField(
            bool(self.settings.get("item_selection_padding_linked", False)),
            self.settings.get("item_selection_padding") or {},
        )
        # MEME widget que Sliders > Rail/Selecteur > Bordure (voir la
        # remarque de l'utilisateur, "bordures du selecteur (de la meme
        # maniere que les slider)") — pas d'epaisseur separee ici non plus
        # (1px fixe, comme les sliders).
        self.item_selection_border_field = _ToggleSideColorsField(
            _coerce_side_enabled(self.settings.get("item_selection_border_enabled", False)),
            self.settings.get("item_selection_border") or {}, self.settings["colors"])
        self.item_selection_radius_field = _CornerRadiusField(
            bool(self.settings.get("item_selection_radius_linked", True)),
            _coerce_corner_radius(self.settings.get("item_selection_radius", 0)), maximum=20)
        self.item_selection_edge_border_field = _Toggle(
            bool(self.settings.get("item_selection_edge_border", True)), style_override="toggle1")

        focus_frame, _, focus_resizer = _build_flat_table([
            ("Couleur", self.item_selection_focus_field),
            ("Padding du selecteur", self.item_selection_padding_field),
            ("Bordures du selecteur", self.item_selection_border_field),
            ("Arrondi des coins de la selection", self.item_selection_radius_field),
            ("Bordure au bord de la colonne", self.item_selection_edge_border_field),
        ])
        self._flat_resizers.append(focus_resizer)
        self.item_selection_frame = focus_frame
        focus_selection_sub = _SubSection("Focus", level=3)
        focus_selection_sub.add(focus_frame)
        focus_selection_sub.collapsedChanged.connect(section.refresh_min_height)

        self.item_selection_unfocus_field = _ColorField(
            self.settings.get("item_selection_unfocus_color", "#2e3338"), swatch_size=24, title="Selection (hors focus)")
        unfocus_selection_sub = self._build_selection_clone_subsection(
            "unfocus", "Non focus", "Couleur", self.item_selection_unfocus_field)
        unfocus_selection_sub.collapsedChanged.connect(section.refresh_min_height)

        self.item_hover_field = _ColorField(
            self.settings.get("item_hover_color", "#232729"), swatch_size=24, title="Survol")
        hover_selection_sub = self._build_selection_clone_subsection(
            "hover", "Survol", "Couleur", self.item_hover_field)
        hover_selection_sub.collapsedChanged.connect(section.refresh_min_height)

        # _AppOrCustomColorField (PAS _ColorField) : par defaut "@itemIdle"
        # (voir DEFAULT_SETTINGS.item_idle_color), une reference a la
        # pastille "Item - non selectionne" plutot qu'un hex fige, pour
        # rester exactement le fond actuel des lignes tant que l'utilisateur
        # ne personnalise pas — voir la remarque de l'utilisateur, "ajoute une
        # couleur (sous couleur de survol) qui represente la couleur non
        # selectionnee ... un fond sur les items non selectionnes, de la
        # meme forme que les divers selections".
        self.item_idle_field = _AppOrCustomColorField(
            self.settings.get("item_idle_color", "@itemIdle"), self.settings["colors"],
            swatch_size=24, title="Couleur non selectionnee")
        idle_selection_sub = self._build_selection_clone_subsection(
            "idle", "Non selectionne", "Couleur", self.item_idle_field)
        idle_selection_sub.collapsedChanged.connect(section.refresh_min_height)

        # Focus/Non focus/Survol/Non selectionne : sous-sections de 2e
        # niveau, IMBRIQUEES dans une sous-section "Selection" (PAS des
        # sous-sections de 1er niveau, cote a cote de Texte/Image) — voir
        # la remarque de l'utilisateur, "les sous sections selections
        # doivent etre des sous sections de general/colonnes/selection".
        selection_group_wrap = QWidget()
        selection_group_wrap.setStyleSheet("background: transparent;")
        selection_group_wrap_l = QVBoxLayout(selection_group_wrap)
        selection_group_wrap_l.setContentsMargins(0, 0, 0, 0)
        _stack_subsections(
            selection_group_wrap_l,
            [focus_selection_sub, unfocus_selection_sub, hover_selection_sub, idle_selection_sub])
        selection_sub = _SubSection("Selection", level=2)
        selection_sub.add(selection_group_wrap)
        selection_sub.collapsedChanged.connect(section.refresh_min_height)
        for sub in (focus_selection_sub, unfocus_selection_sub, hover_selection_sub, idle_selection_sub):
            sub.collapsedChanged.connect(selection_sub.refresh_layout)

        # Les sous-groupes empiles ENSEMBLE, espacement ADAPTATIF UNIFORME
        # entre chacun (voir _stack_subsections/la remarque de l'utilisateur,
        # "je veux que tu normalises l'espacement entre les sections ...
        # comme tu l'avais fait pour les sections").
        subsections_wrap = QWidget()
        subsections_wrap.setStyleSheet("background: transparent;")
        subsections_wrap_l = QVBoxLayout(subsections_wrap)
        subsections_wrap_l.setContentsMargins(0, 0, 0, 0)
        _stack_subsections(
            subsections_wrap_l,
            [columns_sub, resize_badge_sub, headers_sub, text_sub, selection_sub])
        section.add(subsections_wrap)
        return section

    def _section_tables(self) -> _Section:
        """Colonnes du navigateur principal agrandissables a la main (voir
        pipeline_browser._Column._in_resize_zone/app_style.
        set_columns_resizable) ET colonnes des tableaux de CETTE fenetre
        (Geometrie/Polices principales, voir _ResizableTableHeader.
        setResizable/_apply_columns_resizable) — voir la remarque de
        l'utilisateur : "cree un parametre colonne dimmensionnables (avec
        un toggle) afin de pouvoir aggrandir les colonnes", puis "le toggle
        dans les tableaux doit activer ou non la fonctionnalite de colonnes
        redimensionnable" (une fois cette 2e fonctionnalite ajoutee)."""
        section = _Section("Tableaux")
        # _TablePreview construit mais PLUS AFFICHE (voir la remarque de
        # l'utilisateur, "supprime l'apercu des tableaux") — garde toutefois
        # l'instance EN MEMOIRE (jamais ajoutee a un layout, donc invisible)
        # car _apply_table_radius/_apply_cell_padding/_apply_table_head_color
        # plus bas continuent de le traiter comme un 3e tableau a en-tete,
        # au meme titre que les tableaux REELLEMENT affiches — le retirer
        # de la, en plus de ces 2 lignes, demanderait de retoucher ces 3
        # methodes une par une pour un gain nul (widget deja invisible).
        self.table_preview = _TablePreview()
        self.columns_resizable_toggle = _Toggle(bool(self.settings.get("columns_resizable", True)))
        # Deplace ici depuis Geometrie (voir la remarque de l'utilisateur,
        # capture a l'appui : ce reglage concerne les tableaux, pas la
        # geometrie generale — colle desormais avec sa propre section).
        self.table_radius_field = _SliderField(
            0, 16, int(self.settings.get("table_radius", 0)), slider_width=140, box_width=58)
        # Bordure des tableaux "fermes" de cette fenetre (voir _TableFrame.
        # setBorder/DEFAULT_SETTINGS) — MEME widget/MEME agencement (Bordure
        # + Epaisseur) que Toggles > Cadre/Coche et Colonnes > Bordure —
        # voir la remarque de l'utilisateur, "ajoute dans la section
        # tableau un parametre bordure comme celui des toggles".
        self.table_border_thickness_field = _SliderField(
            0, 8, int(self.settings.get("table_border_thickness", 1)), slider_width=140, box_width=58)
        self.table_inner_h_field = _InnerLineField(
            self.settings["table_inner_h_enabled"], self.settings["table_inner_h_color"],
            self.settings["table_inner_h_thickness"], self.settings["colors"], "Bordure intérieure H")
        self.table_inner_v_field = _InnerLineField(
            self.settings["table_inner_v_enabled"], self.settings["table_inner_v_color"],
            self.settings["table_inner_v_thickness"], self.settings["colors"], "Bordure intérieure V")
        self.table_border_field = _ToggleSideColorsField(
            _coerce_side_enabled(self.settings.get("table_border_enabled", True)),
            self.settings.get("table_border") or {}, self.settings["colors"],
            thickness_field=self.table_border_thickness_field)
        # Padding du texte a l'interieur des cellules — voir _CellPaddingField
        # et SettingsWindow._apply_cell_padding, qui l'applique en direct a
        # TOUS les tableaux de cette fenetre (meme portee que "Rayon des
        # angles" juste au-dessus, voir _apply_table_radius) — voir la
        # remarque de l'utilisateur : "un parametre de padding pour le texte
        # a l'interieur des cellules, 4 slideurs pour chacun des cotes, avec
        # un toggle qui permette de choisir si le premier slider controle
        # les 4 valeurs".
        self.cell_padding_field = _CellPaddingField(
            bool(self.settings.get("table_cell_padding_linked", False)),
            self.settings.get("table_cell_padding") or {},
        )
        # Couleur d'en-tete des tableaux A EN-TETE de cette fenetre
        # (Polices/Geometrie, voir _restyle_table_head) — meme controle que
        # Colonnes > Couleur des entetes, mais pour ces tableaux-la plutot
        # que les colonnes du navigateur principal — voir la remarque de
        # l'utilisateur, "ajoute couleur d'entete pour les tableaux".
        self.table_head_color_field = _HeaderColorField(
            self.settings["colors"], self.settings.get("table_head_color", "tableHead"))
        frame, _, resizer = _build_flat_table([
            ("Colonnes dimensionnables", self.columns_resizable_toggle),
            ("Bordure", self.table_border_field),
            ("Bordure intérieure H", self.table_inner_h_field),
            ("Bordure intérieure V", self.table_inner_v_field),
            ("Rayon des angles", self.table_radius_field),
            ("Padding des cellules", self.cell_padding_field),
            ("Couleur d'en-tete", self.table_head_color_field),
        ])
        self._flat_resizers.append(resizer)
        self.tables_table_frame = frame
        section.add(frame)
        return section

    def _section_toggles(self) -> _Section:
        """Choix entre les 2 styles visuels de toggle (voir _Toggle/
        _TOGGLE_STYLE/_ToggleStylePicker), puis reglages COMPLETS de chacun
        des 2 (Cadre/Coche, 2 tableaux cote a cote par style — voir la
        remarque de l'utilisateur, "pour ca je veux deux tableaux cote a
        cote comme tu as fais pour la section slider", et capture annotee
        a l'appui pour le detail des 2 styles corriges)."""
        section = _Section("Toggles")
        # Apercu de l'element concerne par la section, juste avant son
        # tableau de reglages, centre horizontalement (voir la remarque de
        # l'utilisateur et _section_preview_wrap) — un _Toggle "de
        # demonstration" tout simple, pas rattache a un reglage particulier
        # (juste pour voir l'effet du style/des reglages Cadre/Coche/de la
        # transition animee, voir _Toggle) : suit deja tout seul le style
        # COURANT et ses changements, comme tout _Toggle de cette fenetre
        # (voir _on_toggle_style_changed, qui parcourt deja TOUS les
        # _Toggle via findChildren — pas de cablage supplementaire requis).
        self.toggle_preview = _Toggle(True)
        section.add(_section_preview_wrap(self.toggle_preview))
        self.toggle_style_field = _ToggleStylePicker(self.settings.get("toggle_style", "toggle1"))
        style_frame, _, resizer = _build_flat_table([
            ("Style", self.toggle_style_field),
        ])
        self._flat_resizers.append(resizer)
        self.toggles_table_frame = style_frame
        section.add(style_frame)
        style_gap = QWidget()
        style_gap.setStyleSheet("background: transparent;")
        style_gap.setFixedHeight(_title_gap(2, False))
        section.add(style_gap)

        # Un SEUL style affiche a la fois (voir _sync_toggle_style_visibility) :
        # celui choisi par Style ci-dessus, PAS les 2 tableaux cote a cote —
        # voir la remarque de l'utilisateur, "ce n'est pas la peine de faire
        # apparaitre les tableaux des toggles non selectionne, je compte
        # faire d'autres styles de toggle". Chaque page (titre + tableaux)
        # reste neanmoins CONSTRUITE pour tous les styles des l'ouverture
        # (juste masquee) : ses reglages restent modifiables/persistes meme
        # sans etre le style COURANT (voir _current_values, qui boucle sur
        # TOUS les prefixes independamment de l'affichage).
        self._toggle_widgets: dict[str, dict[str, QWidget]] = {}
        self._toggle_style_pages: dict[str, QWidget] = {}
        style_subs = []
        for prefix, label in (("toggle1", "Toggle 1"), ("toggle2", "Toggle 2")):
            page = QWidget()
            page.setStyleSheet("background: transparent;")
            page_l = QVBoxLayout(page)
            page_l.setContentsMargins(0, 0, 0, 0)
            page_l.setSpacing(0)
            style_sub = _SubSection(label, level=2)
            # Cadre/Coche sont ici imbriques SOUS style_sub, elle-meme sous
            # `section` ("Toggles") : refresh_min_height recalcule tout
            # l'arbre (voir _activate_layout_tree), peu importe la
            # profondeur — un simple branchement direct suffit donc a
            # CHAQUE niveau.
            columns_wrap, widgets, _frames = self._build_toggle_shape_tables(prefix, section.refresh_min_height)
            style_sub.add(columns_wrap)
            style_sub.set_collapsed(True)  # voir _stack_subsections, meme raison
            style_sub.collapsedChanged.connect(section.refresh_min_height)
            page_l.addWidget(style_sub)
            section.add(page)
            self._toggle_widgets[prefix] = widgets
            self._toggle_style_pages[prefix] = page
            style_subs.append(style_sub)
        _make_accordion(style_subs)
        self._sync_toggle_style_visibility()
        return section

    def _sync_toggle_style_visibility(self):
        """N'affiche que la page (titre + tableaux Cadre/Coche) du style
        COURANT (Toggles > Style, voir _toggle_style_pages/_section_toggles)
        — voir la remarque de l'utilisateur, "ce n'est pas la peine de faire
        apparaitre les tableaux des toggles non selectionne"."""
        current = self.toggle_style_field.value()
        for prefix, page in self._toggle_style_pages.items():
            page.setVisible(prefix == current)

    def _build_toggle_shape_tables(self, prefix: str, on_collapse_changed) -> tuple[QWidget, dict, dict]:
        """Construit les 2 tableaux Cadre/Coche d'UN style de toggle (voir
        _section_toggles) — factorise Toggle 1/Toggle 2, structurellement
        identiques (seuls le prefixe de reglage et les valeurs par defaut
        changent, voir DEFAULT_SETTINGS). Retourne (widget cote-a-cote,
        {nom logique: controle}, {"outer"/"coche": (frame, row_meta)}) pour
        que _current_values/_apply_values_to_controls/le cablage live et le
        rayon des tableaux restent generiques (boucle sur ces dicts)
        plutot que d'ecrire chaque ligne 2 fois (une par style).

        `on_collapse_changed` : callback appele quand Cadre OU Coche
        (voir outer_sub/coche_sub ci-dessous) se replie/deplie — PAS
        directement `section.refresh_min_height` (l'appelant, imbrique
        sous une AUTRE _SubSection, voir _section_toggles, doit aussi
        rafraichir CELLE-CI au passage, voir _SubSection.refresh_layout)."""
        s = self.settings
        outer_border_thickness = _SliderField(
            0, 8, int(s.get(f"{prefix}_outer_border_thickness", 1)), slider_width=90, box_width=54)
        coche_border_thickness = _SliderField(
            0, 8, int(s.get(f"{prefix}_coche_border_thickness", 1)), slider_width=90, box_width=54)
        w: dict[str, QWidget] = {
            "outer_width": _SliderField(4, 80, int(s.get(f"{prefix}_outer_width", 29)), slider_width=90, box_width=54),
            "outer_height": _SliderField(4, 60, int(s.get(f"{prefix}_outer_height", 14)), slider_width=90, box_width=54),
            "outer_border": _ToggleSideColorsField(
                _coerce_side_enabled(s.get(f"{prefix}_outer_border_enabled", True)), s.get(f"{prefix}_outer_border") or {},
                s["colors"], thickness_field=outer_border_thickness),
            "outer_border_thickness": outer_border_thickness,
            "outer_border_radius": _CornerRadiusField(
                bool(s.get(f"{prefix}_outer_border_radius_linked", True)),
                _coerce_corner_radius(s.get(f"{prefix}_outer_border_radius", 0)), maximum=20),
            "outer_bg": _ColorField(s.get(f"{prefix}_outer_bg", "#141618"), swatch_size=24, title="Fond"),
            "outer_bg_on": _ColorField(
                s.get(f"{prefix}_outer_bg_on", "#3f6f9f"), swatch_size=24, title="Fond (actif)"),
            "coche_width": _SliderField(2, 60, int(s.get(f"{prefix}_coche_width", 11)), slider_width=90, box_width=54),
            "coche_margin": _SliderField(0, 30, int(s.get(f"{prefix}_coche_margin", 4)), slider_width=90, box_width=54),
            "coche_border": _ToggleSideColorsField(
                _coerce_side_enabled(s.get(f"{prefix}_coche_border_enabled", True)), s.get(f"{prefix}_coche_border") or {},
                s["colors"], thickness_field=coche_border_thickness),
            "coche_border_thickness": coche_border_thickness,
            "coche_border_radius": _CornerRadiusField(
                bool(s.get(f"{prefix}_coche_border_radius_linked", True)),
                _coerce_corner_radius(s.get(f"{prefix}_coche_border_radius", 0)), maximum=20),
            "coche_color": _ColorField(s.get(f"{prefix}_coche_color", "#3f6f9f"), swatch_size=24, title="Couleur"),
        }

        outer_frame, outer_meta, outer_resizer = _build_flat_table([
            ("Largeur", w["outer_width"]),
            ("Hauteur", w["outer_height"]),
            ("Bordure", w["outer_border"]),
            ("Rayon des angles", w["outer_border_radius"]),
            ("Fond (sans)", w["outer_bg"]),
            ("Fond (actif)", w["outer_bg_on"]),
        ])
        self._flat_resizers.append(outer_resizer)
        outer_sub = _SubSection("Cadre", level=2)
        outer_sub.add(outer_frame)
        outer_sub.collapsedChanged.connect(on_collapse_changed)

        # Pas de ligne "Hauteur" ici : liee a celle du cadre via "Distance
        # du bord" ci-dessous (voir _sync_toggle_shape_style et la remarque
        # de l'utilisateur — "la hauteur de la coche doit etre liee a celle
        # du toggle, tout en respectant la valeur de x sur le schema").
        coche_frame, coche_meta, coche_resizer = _build_flat_table([
            ("Largeur", w["coche_width"]),
            ("Distance du bord", w["coche_margin"]),
            ("Bordure", w["coche_border"]),
            ("Rayon des angles", w["coche_border_radius"]),
            ("Couleur", w["coche_color"]),
        ])
        self._flat_resizers.append(coche_resizer)
        coche_sub = _SubSection("Coche", level=2)
        coche_sub.add(coche_frame)
        coche_sub.collapsedChanged.connect(on_collapse_changed)

        # Empiles (pas cote a cote) — voir la remarque de l'utilisateur,
        # "met les tableaux l'un au dessus de l'autre dans les sections
        # toggles et sliders" — espacement ADAPTATIF entre les 2 (voir
        # _stack_subsections/la remarque de l'utilisateur, "je veux que tu
        # normalises l'espacement entre les sections ... comme tu l'avais
        # fait pour les sections").
        columns_wrap = QWidget()
        columns_wrap.setStyleSheet("background: transparent;")
        columns_l = QVBoxLayout(columns_wrap)
        columns_l.setContentsMargins(0, 0, 0, 0)
        _stack_subsections(columns_l, [outer_sub, coche_sub])

        return columns_wrap, w, {"outer": (outer_frame, outer_meta), "coche": (coche_frame, coche_meta)}

    def _section_geometry(self) -> _Section:
        section = _Section("Geometrie")
        self.geo_table = _GeoTable(
            bool(self.settings.get("input_frame", True)),
            int(self.settings.get("input_radius", 0)),
            bool(self.settings.get("button_frame", True)),
            int(self.settings.get("button_radius", 0)),
            self.settings.get("geo_table_columns"),
        )
        section.add(self.geo_table)
        return section

    def _section_slider(self) -> _Section:
        """Habillage des sliders peints a la main de cette fenetre (voir
        _MiniSlider/_SLIDER_STYLE) — "Selecteur" = le curseur mobile, "Rail"
        = la piste qu'il parcourt. Section a part entiere, au meme niveau
        que Polices/Couleurs/Geometrie (voir la remarque de l'utilisateur :
        "met la section slider au meme niveau que les sections comme
        Polices principales Couleurs etc" — jusqu'ici une simple
        sous-categorie AU MILIEU de Geometrie, voir _sub_heading). Les 2
        tableaux Selecteur/Rail restent cote a cote (voir la remarque de
        l'utilisateur, capture a l'appui) — libelles de ligne raccourcis en
        consequence ("Largeur" plutot que "Largeur du selecteur") : le
        sous-titre de colonne donne deja ce contexte, et la moitie de
        largeur disponible laisse moins de place au libelle."""
        section = _Section("Sliders")
        # Apercu de l'element concerne par la section, centre (voir
        # _section_preview_wrap/la remarque de l'utilisateur) — un
        # _MiniSlider "de demonstration", pas rattache a un reglage
        # particulier : suit deja tout seul Selecteur/Rail et leurs
        # changements, comme tout _MiniSlider de cette fenetre (voir
        # _apply_slider_style, qui parcourt deja TOUS les _MiniSlider via
        # findChildren — pas de cablage supplementaire requis).
        self.slider_preview = _MiniSlider(0, 100, 60, width=220)
        section.add(_section_preview_wrap(self.slider_preview))

        self.slider_thumb_width_field = _SliderField(
            1, 20, int(self.settings.get("slider_thumb_width", 3)), slider_width=110, box_width=54)
        self.slider_thumb_height_field = _SliderField(
            1, 40, int(self.settings.get("slider_thumb_height", 14)), slider_width=110, box_width=54)
        self.slider_thumb_color_field = _ColorField(
            self.settings.get("slider_thumb_color", "#8fb4d5"), swatch_size=24, title="Couleur du selecteur")
        self.slider_thumb_border_field = _ToggleSideColorsField(
            _coerce_side_enabled(self.settings.get("slider_thumb_border_enabled", True)),
            self.settings.get("slider_thumb_border") or {},
            self.settings["colors"],
        )
        self.slider_thumb_radius_field = _CornerRadiusField(
            bool(self.settings.get("slider_thumb_radius_linked", True)),
            _coerce_corner_radius(self.settings.get("slider_thumb_radius", 0)), maximum=16)
        self.slider_thumb_frame, _, resizer = _build_flat_table([
            ("Largeur", self.slider_thumb_width_field),
            ("Hauteur", self.slider_thumb_height_field),
            ("Couleur", self.slider_thumb_color_field),
            ("Bordure", self.slider_thumb_border_field),
            ("Rayon des angles", self.slider_thumb_radius_field),
        ])
        self._flat_resizers.append(resizer)
        thumb_sub = _SubSection("Selecteur", level=2)
        thumb_sub.add(self.slider_thumb_frame)
        thumb_sub.collapsedChanged.connect(section.refresh_min_height)

        self.slider_track_height_field = _SliderField(
            1, 20, int(self.settings.get("slider_track_height", 3)), slider_width=110, box_width=54)
        self.slider_track_fill_field = _ColorField(
            self.settings.get("slider_track_fill_color", "#3f6f9f"), swatch_size=24, title="Rail parcouru")
        self.slider_track_empty_field = _ColorField(
            self.settings.get("slider_track_empty_color", "#25292d"), swatch_size=24, title="Rail a parcourir")
        # Bordure du rail : 4 couleurs independantes (voir la remarque de
        # l'utilisateur, "4 couleurs comme la bordure du selecteur") — meme
        # controle que le selecteur, toggle actif/sans compris (voir la
        # remarque de l'utilisateur, "si le toggle est inactif, je veux que
        # les 4 couleurs ne soient pas selectionnables").
        self.slider_track_border_field = _ToggleSideColorsField(
            _coerce_side_enabled(self.settings.get("slider_track_border_enabled", True)),
            self.settings.get("slider_track_border") or {},
            self.settings["colors"],
        )
        self.slider_track_radius_field = _CornerRadiusField(
            bool(self.settings.get("slider_track_radius_linked", True)),
            _coerce_corner_radius(self.settings.get("slider_track_radius", 0)), maximum=16)
        self.slider_rail_frame, _, resizer = _build_flat_table([
            ("Hauteur", self.slider_track_height_field),
            ("Rail parcouru", self.slider_track_fill_field),
            ("Rail a parcourir", self.slider_track_empty_field),
            ("Bordure", self.slider_track_border_field),
            ("Rayon des angles", self.slider_track_radius_field),
        ])
        self._flat_resizers.append(resizer)
        rail_sub = _SubSection("Rail", level=2)
        rail_sub.add(self.slider_rail_frame)
        rail_sub.collapsedChanged.connect(section.refresh_min_height)

        # Empiles (pas cote a cote) — voir la remarque de l'utilisateur,
        # "met les tableaux l'un au dessus de l'autre dans les sections
        # toggles et sliders" — espacement ADAPTATIF entre les 2 (voir
        # _stack_subsections/la remarque de l'utilisateur, "je veux que tu
        # normalises l'espacement entre les sections ... comme tu l'avais
        # fait pour les sections").
        columns_wrap = QWidget()
        columns_wrap.setStyleSheet("background: transparent;")
        columns_l = QVBoxLayout(columns_wrap)
        columns_l.setContentsMargins(0, 0, 0, 0)
        _stack_subsections(columns_l, [rail_sub, thumb_sub])
        section.add(columns_wrap)

        return section

    def _section_raccourci(self) -> _Section:
        """Section RACCOURCI (voir pipeline_browser.SHORTCUT_TEXT_STYLE/
        ROLE_IS_SHORTCUT, Column._on_context_menu "Ajouter un raccourci") :
        police/couleur DEDIEES pour reperer un raccourci au premier coup
        d'oeil (un dossier d'un AUTRE emplacement du disque, affiche comme
        s'il etait physiquement ici) — voir la remarque de l'utilisateur,
        "police : choix de la police avec toggle : app ou systeme, toggle
        gras ou regulier, couleur, taille"."""
        section = _Section("RACCOURCI")
        # GABARIT "police" (voir _build_font_gabarit_row) — _DualFontSelectField
        # (pas _FontSelectField, corrige lors du balayage des gabarits :
        # celle-ci n'offrait pas le choix app/systeme demande) + lissage
        # ajoute (absent jusqu'ici).
        self.shortcut_font_family_field = _DualFontSelectField(
            self.settings.get("shortcut_font_family", "") or "Systeme", width=150)
        self.shortcut_font_bold_field = _Toggle(
            bool(self.settings.get("shortcut_font_bold", False)), style_override="toggle1", show_label=False)
        self.shortcut_font_italic_field = _Toggle(
            bool(self.settings.get("shortcut_font_italic", False)), show_label=False)
        self.shortcut_color_field = _CompactAppOrCustomColorField(
            self.settings.get("shortcut_color", "#8fb4d5"), self.settings["colors"],
            swatch_size=20, title="Couleur du raccourci")
        self.shortcut_font_size_field = _SliderField(
            8, 24, int(self.settings.get("shortcut_font_size", 11)), slider_width=110, box_width=54)
        self.shortcut_font_smoothing_field = _OverrideSmoothingField(
            bool(self.settings.get("shortcut_font_smoothing_enabled", False)),
            self.settings.get("shortcut_font_smoothing", "current"))
        shortcut_font_row = _build_font_gabarit_row(
            self.shortcut_font_family_field, self.shortcut_font_bold_field, self.shortcut_font_size_field,
            self.shortcut_font_smoothing_field, self.shortcut_color_field,
            italic_field=self.shortcut_font_italic_field)
        frame, _meta, resizer = _build_flat_table([
            ("Police", shortcut_font_row),
        ])
        self._flat_resizers.append(resizer)
        section.add(frame)
        return section

    def _section_icones(self) -> _Section:
        """Section ICONES (renommee depuis "Logiciel", voir la remarque de
        l'utilisateur, "renomme la section logiciel en ICONES et crees deux
        sous sections general et logiciels") : "General" regroupe les
        icones d'INTERFACE personnalisables (dossier/fichier par defaut,
        punaise, engrenage Parametres, logo barre de navigation, bouton de
        repliement — voir _build_icones_general_body) ; "Logiciels" est
        l'ancien tableau LOGICIEL, INCHANGE (voir _rebuild_logiciels_table),
        juste deplace sous cette nouvelle sous-section.

        Les 2 sous-sections demarrent REPLIEES et VIDES (voir _SubSection.
        set_collapsed) — leur contenu (widgets, import differe de
        pipeline_browser) n'est construit qu'au premier depli (voir
        _on_icones_general_toggled/_on_icones_logiciels_toggled), MEME
        principe que Colonnes > Type/Projets/Sous-projets (voir _on_columns_
        tab_changed) — voir la remarque de l'utilisateur, "tu ne charges
        leur contenu uniquement que lorsque l'on deplie le tab concerne".
        Sans risque ici (contrairement au reste de l'onglet General) : ni
        les icones d'interface ni le tableau Logiciel n'alimentent
        _current_values() (voir _on_apply/_on_save, qui lisent self.
        _custom_softwares/self._removed_softwares directement, pas un champ
        de widget)."""
        section = _Section("ICONES")
        general_sub = _SubSection("General", level=2)
        logiciels_sub = _SubSection("Logiciels", level=2)
        self._icones_general_sub = general_sub
        self._icones_logiciels_sub = logiciels_sub
        self._icones_general_built = False
        self._icones_logiciels_built = False
        general_sub.set_collapsed(True)
        logiciels_sub.set_collapsed(True)
        general_sub.collapsedChanged.connect(self._on_icones_general_toggled)
        logiciels_sub.collapsedChanged.connect(self._on_icones_logiciels_toggled)

        wrap = QWidget()
        wrap_l = QVBoxLayout(wrap)
        wrap_l.setContentsMargins(0, 0, 0, 0)
        _stack_subsections(wrap_l, [general_sub, logiciels_sub])
        section.add(wrap)
        return section

    def _on_icones_general_toggled(self, collapsed: bool):
        if not collapsed and not self._icones_general_built:
            self._icones_general_built = True
            self._build_icones_general_body(self._icones_general_sub)

    def _on_icones_logiciels_toggled(self, collapsed: bool):
        if not collapsed and not self._icones_logiciels_built:
            self._icones_logiciels_built = True
            self._build_icones_logiciels_body(self._icones_logiciels_sub)

    def _build_icones_logiciels_body(self, sub: "_SubSection"):
        """Ancien contenu de _section_logiciels (voir son historique) —
        INCHANGE, juste rattache a une _SubSection au lieu d'une _Section
        dediee."""
        self._logiciels_section = sub
        self._logiciels_holder = QWidget()
        holder_l = QVBoxLayout(self._logiciels_holder)
        holder_l.setContentsMargins(0, 0, 0, 0)
        holder_l.setSpacing(0)
        self._logiciels_holder_layout = holder_l
        self._logiciels_frame = None
        sub.add(self._logiciels_holder)
        self._rebuild_logiciels_table()

    # -- ICONES > General : icones d'interface (voir UI_ICON_* cote
    # pipeline_browser) --

    _UI_ICON_ROWS = [
        ("folder_default", "Dossiers"),
        ("file_default", "Fichiers"),
        ("settings_gear", "Engrenage (bouton Parametres)"),
        ("settings_style", "Reglages visuels (second bouton Parametres)"),
        ("app_logo", "Icone de la barre de navigation"),
        ("collapse_toggle", "Icone de repliement de colonne"),
        ("shortcut", "Raccourcis"),
    ]

    def _build_icones_general_body(self, sub: "_SubSection"):
        frame, layout = _table_frame()
        self._ui_icon_avatars = {}
        head = _table_header([("Icone", 80), ("Nom", 0), ("Actions", 720)])
        for col in (0, 2):
            head._cells[col].setAlignment(Qt.AlignCenter)
        layout.addWidget(head)
        row_meta: list = []
        column_cells: dict = {}
        index = 0
        self._build_ui_icon_pin_row(layout, index, row_meta, column_cells)
        index += 1
        import previews as pb_previews
        for ui_suffix, label_text in self._UI_ICON_ROWS:
            ui_key = getattr(pb_previews, f"UI_ICON_{ui_suffix.upper()}")
            self._build_ui_icon_row(layout, index, ui_key, label_text, row_meta, column_cells)
            index += 1
        _wire_resizable_columns(head, column_cells)
        _register_cells_table(frame, head, row_meta)
        _lock_min_height(frame)
        sub.add(frame)
        sub.refresh_layout()

    @staticmethod
    def _icon_row_cells(row_l, column_cells: dict, icon: QWidget, name: QWidget, actions: QWidget, actions_width: int):
        """Une cellule par colonne (Icone | Nom | Actions), contenu groupe et centre
        (le nom reste a gauche), comme les autres tableaux a entete."""
        for col, (widget, width) in enumerate(((icon, 80), (name, 0), (actions, actions_width))):
            cell = _table_cell(widget, width, row_l, center=True)
            cell.layout().setAlignment(widget, (Qt.AlignLeft if col == 1 else Qt.AlignHCenter) | Qt.AlignVCenter)
            column_cells.setdefault(col, []).append(cell)

    def _icon_buttons(self, key: str, avatar: QLabel, short: bool = False, reset_label: str = "Reinitialiser") -> QWidget:
        box = QWidget()
        box.setStyleSheet("background: transparent;")
        box_l = QHBoxLayout(box)
        box_l.setContentsMargins(0, 0, 0, 0)
        box_l.setSpacing(8)
        change_btn = _Btn("Changer..." if short else "Changer l'icone...",
                          M["btn_bg"], M["btn_border"], M["btn_fg"], M["btn_hover"], height=25)
        change_btn.clicked.connect(lambda _=False, k=key, av=avatar: self._change_ui_icon(k, av))
        capture_btn = _Btn("Capturer..." if short else "Capturer une zone d'ecran...",
                           M["btn_bg"], M["btn_border"], M["btn_fg"], M["btn_hover"], height=25)
        capture_btn.clicked.connect(lambda _=False, k=key, av=avatar: self._capture_ui_icon(k, av))
        reset_btn = _Btn(reset_label, M["btn_bg"], M["btn_border"], M["btn_fg"], M["btn_hover"], height=25)
        reset_btn.clicked.connect(lambda _=False, k=key, av=avatar: self._reset_ui_icon(k, av))
        for btn in (change_btn, capture_btn, reset_btn):
            box_l.addWidget(btn)
        return box

    def _build_ui_icon_row(self, layout: QVBoxLayout, index: int, ui_key: str, label_text: str,
                           row_meta: list, column_cells: dict):
        bg = M["table_row_a"] if index % 2 else M["table_row_b"]
        row, row_l = _table_row(bg, first=(index == 0))
        row_meta.append((row, bg, index == 0))

        avatar = QLabel()
        avatar.setFixedSize(24, 24)
        avatar.setStyleSheet("background: transparent;")
        self._set_ui_icon_avatar_pixmap(avatar, ui_key)
        self._ui_icon_avatars[ui_key] = avatar

        name = QLabel(label_text)
        _set_text_role(name, "value")
        self._icon_row_cells(row_l, column_cells, avatar, name, self._icon_buttons(ui_key, avatar), 720)
        _lock_min_height(row)
        layout.addWidget(row)

    def _build_ui_icon_pin_row(self, layout: QVBoxLayout, index: int, row_meta: list, column_cells: dict):
        """Ligne "Punaise" avec les 2 etats (non attachee/attachee) sur la
        MEME ligne, voir la remarque de l'utilisateur, "punaise non
        attachee, + punaise attachee sur la mm ligne"."""
        import previews as pb_previews

        bg = M["table_row_a"] if index % 2 else M["table_row_b"]
        row, row_l = _table_row(bg, first=(index == 0))
        row_meta.append((row, bg, index == 0))

        name = QLabel("Punaise")
        _set_text_role(name, "value")
        groups = QWidget()
        groups.setStyleSheet("background: transparent;")
        groups_l = QHBoxLayout(groups)
        groups_l.setContentsMargins(0, 0, 0, 0)
        groups_l.setSpacing(24)
        for ui_key, sub_label in ((pb_previews.UI_ICON_PIN_INACTIVE, "Non attachee"), (pb_previews.UI_ICON_PIN_ACTIVE, "Attachee")):
            group = QWidget()
            group.setStyleSheet("background: transparent;")
            group_l = QHBoxLayout(group)
            group_l.setContentsMargins(0, 0, 0, 0)
            group_l.setSpacing(6)
            sub_name = QLabel(sub_label)
            _set_text_role(sub_name, "note")
            group_l.addWidget(sub_name)
            avatar = QLabel()
            avatar.setFixedSize(24, 24)
            avatar.setStyleSheet("background: transparent;")
            self._set_ui_icon_avatar_pixmap(avatar, ui_key)
            self._ui_icon_avatars[ui_key] = avatar
            group_l.addWidget(avatar)
            group_l.addWidget(self._icon_buttons(ui_key, avatar, short=True, reset_label="Reinit."))
            groups_l.addWidget(group)
        self._icon_row_cells(row_l, column_cells, QWidget(), name, groups, 720)
        _lock_min_height(row)
        layout.addWidget(row)

    def _set_ui_icon_avatar_pixmap(self, avatar: QLabel, ui_key: str):
        import browser_core as pb_core
        import previews as pb_previews

        if ui_key == pb_previews.UI_ICON_PIN_INACTIVE:
            avatar.setPixmap(pb_core._pin_icon_pixmap(False, 24))
        elif ui_key == pb_previews.UI_ICON_PIN_ACTIVE:
            avatar.setPixmap(pb_core._pin_icon_pixmap(True, 24))
        else:
            pix = pb_previews.custom_ui_icon_pixmap(ui_key, 24)
            avatar.setPixmap(pix if pix is not None else QPixmap())

    def _change_ui_icon(self, key: str, avatar: QLabel):
        chosen, _ = QFileDialog.getOpenFileName(
            self, "Choisir une image", "",
            "Images (*.png *.jpg *.jpeg *.bmp *.webp *.gif *.tif *.tiff)",
        )
        if not chosen:
            return
        pix = QPixmap(chosen)
        if pix.isNull():
            QMessageBox.warning(self, "Icone", "Impossible de charger cette image.")
            return
        self._save_ui_icon_pixmap(key, pix, avatar)

    def _capture_ui_icon(self, key: str, avatar: QLabel):
        import browser_core as pb_core

        was_visible = self.isVisible()
        if was_visible:
            self.hide()
        QApplication.processEvents()

        def start_overlay():
            capture = pb_core.MultiScreenCapture()
            self._ui_icon_capture_overlay = capture

            def finish():
                if was_visible:
                    self.show()
                self._ui_icon_capture_overlay = None

            def on_captured(pix: QPixmap):
                finish()
                self._save_ui_icon_pixmap(key, pix, avatar)

            capture.captured.connect(on_captured)
            capture.cancelled.connect(finish)

        QTimer.singleShot(150, start_overlay)

    def _save_ui_icon_pixmap(self, key: str, pix: QPixmap, avatar: QLabel):
        import previews as pb_previews

        if pix.isNull():
            return
        if max(pix.width(), pix.height()) > _config.CUSTOM_SOFTWARE_ICON_MAX_DIM:
            pix = pix.scaled(
                _config.CUSTOM_SOFTWARE_ICON_MAX_DIM, _config.CUSTOM_SOFTWARE_ICON_MAX_DIM,
                Qt.KeepAspectRatio, Qt.SmoothTransformation,
            )
        dest = pb_previews.custom_software_icon_path(key)
        try:
            was_new = not dest.parent.is_dir()
            dest.parent.mkdir(parents=True, exist_ok=True)
            if was_new:
                pb_previews._set_hidden(dest.parent)
        except OSError as exc:
            QMessageBox.warning(self, "Icone", f"Impossible de creer le dossier de configuration :\n{exc}")
            return
        if not pix.save(str(dest), "PNG"):
            QMessageBox.warning(self, "Icone", "Impossible d'enregistrer l'icone.")
            return
        self._set_ui_icon_avatar_pixmap(avatar, key)

    def _reset_ui_icon(self, key: str, avatar: QLabel):
        import previews as pb_previews

        try:
            pb_previews.custom_software_icon_path(key).unlink(missing_ok=True)
        except OSError:
            pass
        self._set_ui_icon_avatar_pixmap(avatar, key)

    def _rebuild_logiciels_table(self):
        import browser_core as pb_core
        import previews as pb_previews

        # Le tableau est reconstruit en entier (entete compris) : on garde les
        # largeurs de colonnes et la largeur du tableau d'avant.
        previous = self._logiciels_frame
        saved = previous.collectDims() if previous is not None else None
        if previous is not None:
            self._logiciels_holder_layout.removeWidget(previous)
            previous.hide()
            previous.deleteLater()
        frame, layout = _table_frame()
        self._logiciels_frame = frame
        head = _table_header([("Icone", 80), ("Nom", 0), ("Actions", 640)])
        for col in (0, 2):
            head._cells[col].setAlignment(Qt.AlignCenter)
        layout.addWidget(head)
        row_meta: list = []
        column_cells: dict = {}

        labels = {e["key"]: e["label"] for e in self._custom_softwares}
        keys = [k for k in sorted(pb_previews.SOFTWARE_ICONS.keys()) if k not in self._removed_softwares] + [
            e["key"] for e in self._custom_softwares if e["key"] not in pb_previews.SOFTWARE_ICONS
        ]

        for i, key in enumerate(keys):
            bg = M["table_row_a"] if i % 2 else M["table_row_b"]
            row, row_l = _table_row(bg, first=(i == 0))
            row_meta.append((row, bg, i == 0))

            avatar = QLabel()
            avatar.setFixedSize(24, 24)
            # Fond transparent EXPLICITE (voir _table_cell, meme raison) :
            # sans lui, le QSS global de l'appli (QWidget { background:
            # ... } ) peint un fond OPAQUE derriere ce QLabel, masquant la
            # transparence reelle de l'icone — voir la remarque de
            # l'utilisateur, "je veux que les icones prennent la
            # transparence parfaitement ... ce n'est pas le cas avec
            # blender".
            avatar.setStyleSheet("background: transparent;")
            avatar.setPixmap(pb_core.software_icon_pixmap(key, 24))

            name = QLabel(labels.get(key, key))
            _set_text_role(name, "value")
            actions = QWidget()
            actions.setStyleSheet("background: transparent;")
            actions_l = QHBoxLayout(actions)
            actions_l.setContentsMargins(0, 0, 0, 0)
            actions_l.setSpacing(8)

            change_btn = _Btn(
                "Changer l'icone...", M["btn_bg"], M["btn_border"], M["btn_fg"], M["btn_hover"],
                height=25,
            )
            change_btn.clicked.connect(lambda _=False, k=key, av=avatar: self._change_logiciel_icon(k, av))
            actions_l.addWidget(change_btn)

            capture_btn = _Btn(
                "Capturer une zone d'ecran...", M["btn_bg"], M["btn_border"], M["btn_fg"], M["btn_hover"],
                height=25,
            )
            capture_btn.clicked.connect(lambda _=False, k=key, av=avatar: self._capture_logiciel_icon(k, av))
            actions_l.addWidget(capture_btn)

            # "Supprimer" (voir la remarque de l'utilisateur, "dans les
            # logiciels ajoute aussi un bouton supprimer") : sens DIFFERENT
            # selon l'origine de la ligne — un logiciel AJOUTE (voir "+",
            # key absente de pb_previews.SOFTWARE_ICONS) n'a rien d'autre a quoi
            # revenir, "Supprimer" retire donc la ligne entiere ; un
            # logiciel RECONNU d'origine reste toujours dans la liste (il
            # est enumere depuis pb_previews.SOFTWARE_ICONS, pas depuis une liste
            # qu'on pourrait vider), "Supprimer" retire alors seulement son
            # ICONE PERSONNALISEE (retour au badge genere automatiquement —
            # meme effet que l'ancienne action "Reinitialiser l'icone du
            # logiciel").
            is_custom = key not in pb_previews.SOFTWARE_ICONS
            delete_btn = _Btn(
                "Supprimer", M["btn_bg"], M["btn_border"], M["btn_fg"], M["btn_hover"],
                height=25,
            )
            delete_btn.clicked.connect(lambda _=False, k=key, custom=is_custom: self._delete_logiciel(k, custom))
            actions_l.addWidget(delete_btn)
            self._icon_row_cells(row_l, column_cells, avatar, name, actions, 640)

            _lock_min_height(row)
            layout.addWidget(row)

        add_bg = M["table_row_a"] if len(keys) % 2 else M["table_row_b"]
        add_row, add_l = _table_row(add_bg, first=(len(keys) == 0))
        row_meta.append((add_row, add_bg, len(keys) == 0))
        add_l.setContentsMargins(14, 6, 14, 6)
        add_btn = _Btn(
            "+  Ajouter un logiciel...", "transparent", "", M["value_fg"], M["btn_hover"],
            height=28, weight=500, padding="0 12px", align_left=True,
        )
        add_btn.clicked.connect(self._add_logiciel)
        add_l.addWidget(add_btn, 0)
        add_l.addStretch(1)
        _lock_min_height(add_row)
        layout.addWidget(add_row)

        # Verrouille aussi le CADRE entier (pas seulement chaque ligne, deja
        # fait ci-dessus) — MEME correctif que _build_flat_table (voir sa
        # remarque, "sans ca, un conteneur englobant a court d'espace peut
        # toujours compresser le cadre lui-meme en dessous de la somme de
        # ses lignes") : oublie ici a la premiere version de ce tableau,
        # d'ou les lignes ecrasees/le texte chevauchant constate par
        # l'utilisateur, capture a l'appui, "le tableau des logiciels est
        # compressable".
        _wire_resizable_columns(head, column_cells)
        _register_cells_table(frame, head, row_meta)
        self._logiciels_holder_layout.addWidget(frame)
        _lock_min_height(frame)
        frame._dims_applied = True
        if saved:
            frame.applyDims(saved)
        if hasattr(self, "_logiciels_section"):
            self._logiciels_section.refresh_layout()

    def _add_logiciel(self):
        import previews as pb_previews

        name, ok = QInputDialog.getText(self, "Ajouter un logiciel", "Nom du logiciel :")
        if not ok:
            return
        name = name.strip()
        if not name:
            return
        key = "".join(ch for ch in name.upper() if ch.isalnum())
        if not key:
            QMessageBox.warning(self, "Logiciel", "Ce nom ne contient aucun caractere valide.")
            return
        # Un logiciel d'origine RETIRE (voir _delete_logiciel) reste dans
        # pb_previews.SOFTWARE_ICONS — "+" le fait juste REAPPARAITRE (voir la
        # remarque de l'utilisateur, ce doit etre le seul moyen de le
        # recuperer), plutot que de le refuser comme "deja dans la liste"
        # ou d'en creer un doublon custom.
        if key in self._removed_softwares:
            self._removed_softwares.discard(key)
            self._rebuild_logiciels_table()
            self._mark_dirty()
            return
        if key in pb_previews.SOFTWARE_ICONS or any(e["key"] == key for e in self._custom_softwares):
            QMessageBox.warning(self, "Logiciel", f"« {name} » est deja dans la liste.")
            return
        self._custom_softwares.append({"key": key, "label": name})
        self._rebuild_logiciels_table()
        self._mark_dirty()

    def _delete_logiciel(self, key: str, is_custom: bool):
        """Retire la LIGNE (voir la remarque de l'utilisateur, "le bouton
        supprimer ne marche pas, ca ne supprime pas la ligne du logiciel")
        — pour un logiciel AJOUTE (voir "+"), retire directement son
        entree ; pour un logiciel RECONNU D'ORIGINE (toujours enumere
        depuis pb_previews.SOFTWARE_ICONS, impossible a retirer de ce dict), garde
        sa cle dans self._removed_softwares (voir DEFAULT_SETTINGS) pour
        l'exclure du tableau ET de la reconnaissance automatique
        (software_icon_key) tant qu'il n'est pas re-ajoute via "+"."""
        label = key if not is_custom else next(
            (e["label"] for e in self._custom_softwares if e["key"] == key), key
        )
        if QMessageBox.question(
            self, "Supprimer", f"Retirer « {label} » de la liste des logiciels ?",
            QMessageBox.Yes | QMessageBox.No, QMessageBox.No,
        ) != QMessageBox.Yes:
            return
        if is_custom:
            self._custom_softwares = [e for e in self._custom_softwares if e["key"] != key]
        else:
            self._removed_softwares.add(key)
        self._rebuild_logiciels_table()
        self._mark_dirty()

    def _change_logiciel_icon(self, key: str, avatar: QLabel):
        pass

        chosen, _ = QFileDialog.getOpenFileName(
            self, "Choisir une image", "",
            "Images (*.png *.jpg *.jpeg *.bmp *.webp *.gif *.tif *.tiff)",
        )
        if not chosen:
            return
        pix = QPixmap(chosen)
        if pix.isNull():
            QMessageBox.warning(self, "Icone", "Impossible de charger cette image.")
            return
        self._save_logiciel_icon_pixmap(key, pix, avatar)

    def _capture_logiciel_icon(self, key: str, avatar: QLabel):
        import browser_core as pb_core

        was_visible = self.isVisible()
        if was_visible:
            self.hide()
        QApplication.processEvents()

        def start_overlay():
            capture = pb_core.MultiScreenCapture()
            self._logiciel_capture_overlay = capture

            def finish():
                if was_visible:
                    self.show()
                self._logiciel_capture_overlay = None

            def on_captured(pix: QPixmap):
                finish()
                self._save_logiciel_icon_pixmap(key, pix, avatar)

            capture.captured.connect(on_captured)
            capture.cancelled.connect(finish)

        QTimer.singleShot(150, start_overlay)

    def _save_logiciel_icon_pixmap(self, key: str, pix: QPixmap, avatar: QLabel):
        import browser_core as pb_core
        import previews as pb_previews

        if pix.isNull():
            return
        if max(pix.width(), pix.height()) > _config.CUSTOM_SOFTWARE_ICON_MAX_DIM:
            pix = pix.scaled(
                _config.CUSTOM_SOFTWARE_ICON_MAX_DIM, _config.CUSTOM_SOFTWARE_ICON_MAX_DIM,
                Qt.KeepAspectRatio, Qt.SmoothTransformation,
            )
        dest = pb_previews.custom_software_icon_path(key)
        try:
            was_new = not dest.parent.is_dir()
            dest.parent.mkdir(parents=True, exist_ok=True)
            if was_new:
                pb_previews._set_hidden(dest.parent)
        except OSError as exc:
            QMessageBox.warning(self, "Icone", f"Impossible de creer le dossier de configuration :\n{exc}")
            return
        if not pix.save(str(dest), "PNG"):
            QMessageBox.warning(self, "Icone", "Impossible d'enregistrer l'icone.")
            return
        pb_previews._set_hidden(dest)
        avatar.setPixmap(pb_core.software_icon_pixmap(key, 24))

    # -- barre du bas --

    def _build_bottom_bar(self) -> QWidget:
        bar = QWidget()
        self._bottom_bar = bar
        bar.setFixedHeight(46)
        bar.setStyleSheet(f"background: {M['toolbar_bg']}; border-top: 1px solid {M['panel_border']};")
        layout = QHBoxLayout(bar)
        layout.setContentsMargins(14, 0, 14, 0)
        layout.setSpacing(8)

        # radius=self.geo_table... : construite APRES _build_content() (voir
        # __init__), self.geo_table existe deja ici — voir aussi
        # _apply_button_radius pour le suivi en direct du slider ensuite.

        reset_btn = _Btn("Valeurs par defaut", "transparent", M["btn_border"], M["reset_fg"], M["btn_bg"],
                          height=27, padding="0 12px")
        reset_btn.clicked.connect(self._reset_defaults)
        layout.addWidget(reset_btn)
        layout.addStretch(1)

        apply_btn = _Btn("Appliquer", M["btn_bg"], M["btn_border"], M["btn_fg"], M["btn_hover"],
                          height=27, padding="0 13px")
        apply_btn.clicked.connect(self._on_apply)
        layout.addWidget(apply_btn)

        cancel_btn = _Btn("Annuler", M["btn_bg"], M["btn_border"], M["btn_fg"], M["btn_hover"],
                           height=27, padding="0 13px")
        cancel_btn.clicked.connect(self.reject)
        layout.addWidget(cancel_btn)

        save_btn = _Btn("Enregistrer", M["accent"], M["accent_border"], M["accent_fg"], M["accent_hover"],
                        height=27, weight=600, padding="0 17px")
        save_btn.clicked.connect(self._on_save)
        layout.addWidget(save_btn)

        self._bottombar_reset_btn = reset_btn
        self._bottombar_apply_btn = apply_btn
        self._bottombar_cancel_btn = cancel_btn
        self._bottombar_save_btn = save_btn
        return bar

    def _reset_defaults(self):
        defaults = json.loads(json.dumps(DEFAULT_SETTINGS))
        defaults["root_path"] = self.settings.get("root_path", DEFAULT_SETTINGS["root_path"])
        self._apply_values_to_controls(defaults)
        self._mark_dirty()
        self._preview_now()

    # -- actions --

    def _browse_root(self):
        chosen = QFileDialog.getExistingDirectory(self, "Racine par defaut", self.root_field.text())
        if chosen:
            self.root_field.setText(chosen)

    _WINDOW_RADIUS_ON = 12

    def _window_radius_value(self) -> int:
        """Fenetre (voir Application > Fenetre, self.window_radius_toggle) :
        un simple on/off desormais (voir la remarque de l'utilisateur,
        "transforme le slider en toggle") — rayon FIXE quand actif, 0 sinon
        (window_radius reste un ENTIER cote stockage, comportement INCHANGE
        pour pipeline_browser.WINDOW_RADIUS/_apply_panel_radius, seule la
        commande passe d'un slider a un toggle)."""
        return self._WINDOW_RADIUS_ON if self.window_radius_toggle.isChecked() else 0

    def _apply_panel_radius(self, radius: int):
        # Les fenetres de reglages n'ont jamais de coins arrondis, quel que
        # soit "window_radius" (qui ne concerne que la fenetre principale).
        radius = 0
        # Peint a la main (_PanelFrame), pas en QSS — voir sa remarque de
        # tete de classe : ce widget porte tout le contenu de la fenetre,
        # un setStyleSheet dessus recalculait le style de ~300 descendants
        # a chaque appel (~20ms mesures), rejoue a chaque glisser d'un
        # slider de couleur touchant well/topbar.
        self.panel.setColors(M["panel_bg"], M["panel_border"])
        self.panel.setRadius(radius)
        # resizable=True (voir PipelineBrowser._apply_native_frame, meme
        # appel) : pose WS_THICKFRAME cote Windows, sans quoi nativeEvent
        # ci-dessous n'aurait aucun bord natif a agrandir/retrecir.
        apply_dwm_frame(self, radius, M["panel_border"], resizable=True)

    _RESIZE_BORDER = 6

    def nativeEvent(self, eventType, message):
        """Redimensionnement par les bords de cette fenetre sans decoration
        systeme — voir app_style.resize_hit_test (partage avec
        PipelineBrowser.nativeEvent, meme mecanisme)."""
        if eventType == b"windows_generic_MSG":
            result = resize_hit_test(self, message, self._RESIZE_BORDER)
            if result is not None:
                return result
        return super().nativeEvent(eventType, message)

    def _connect_application_updates(self):
        self.root_field.textChanged.connect(self._mark_dirty)
        self.default_preset_field.changed.connect(self._mark_dirty)
        self.scale_field.valueChanged.connect(self._mark_dirty)
        self.auto_collapse_set_columns_field.toggled.connect(self._mark_dirty)
        self.omit_file_names_field.changed.connect(self._mark_dirty)
        self.omit_dir_names_field.changed.connect(self._mark_dirty)
        self.lut_images_field.changed.connect(self._mark_dirty)
        self.window_radius_toggle.toggled.connect(self._on_window_radius_changed)

    def _connect_live_updates(self):
        if self._light:
            self._connect_application_updates()
            return
        # TITRE (voir _section_titre/_apply_title_level_style) : tout
        # changement de police/couleur/retrait restyle EN DIRECT toutes les
        # _Section/_SubSection deja construites de cette fenetre.
        for level in (1, 2, 3, 4, 5):
            prefix = f"title_level{level}"
            self.__dict__[f"{prefix}_font_family_field"].changed.connect(self._apply_title_level_style)
            self.__dict__[f"{prefix}_font_bold_field"].toggled.connect(self._apply_title_level_style)
            self.__dict__[f"{prefix}_font_italic_field"].toggled.connect(self._apply_title_level_style)
            self.__dict__[f"{prefix}_font_size_field"].valueChanged.connect(self._apply_title_level_style)
            self.__dict__[f"{prefix}_font_smoothing_field"].changed.connect(self._apply_title_level_style)
            self.__dict__[f"{prefix}_font_color_field"].changed.connect(self._apply_title_level_style)
            self.__dict__[f"{prefix}_indent_field"].valueChanged.connect(self._apply_title_level_style)
            self.__dict__[f"{prefix}_gap_collapsed_field"].valueChanged.connect(self._apply_title_level_style)
            self.__dict__[f"{prefix}_gap_expanded_field"].valueChanged.connect(self._apply_title_level_style)
            self.__dict__[f"{prefix}_gap_next_field"].valueChanged.connect(self._apply_title_level_style)
        # La racine par defaut suivait auparavant seulement Appliquer/
        # Enregistrer (voir _on_apply) ; l'utilisateur veut desormais que
        # TOUT changement se repercute en direct, sans exception.
        self._connect_application_updates()
        self.font_table.changed.connect(self._mark_dirty)
        # _on_colors_changed reapplique le style de TOUTE la fenetre
        # (tableaux, menus, cadre natif...) — correct mais couteux, et
        # colorChanged emet a CHAQUE pixel du glisser d'un slider TSL/RVB
        # (voir _ColorPickerPopup._refresh_all) : appele en direct, ce
        # cout retombe sur le meme evenement souris que le slider doit
        # traiter, d'ou la latence enorme signalee par l'utilisateur au
        # glisser. _schedule_colors_changed regroupe les changements
        # rapproches et ne rejoue _on_colors_changed qu'a ~60 im/s
        # (voir son propre commentaire), invisible a l'oeil mais qui
        # laisse le slider lui-meme rester fluide.
        self._colors_changed_timer = QTimer(self)
        self._colors_changed_timer.setSingleShot(True)
        self._colors_changed_timer.setInterval(16)
        self._colors_changed_timer.timeout.connect(self._on_colors_changed)
        self.color_grid.changed.connect(self._schedule_colors_changed)
        # Meme regroupement que _colors_changed_timer ci-dessus, pour
        # _apply_column_type_preview (voir _connect_column_type_overrides) :
        # c'est le SEUL apercu en direct de cette fenetre encore cable sans
        # aucun debounce directement sur CHAQUE champ/toggle de 3 onglets
        # entiers (Colonnes > Type/Projets/Sous-projets) — un simple glisser
        # de slider y emet valueChanged a CHAQUE pixel, rejouant a chaque
        # fois une boucle sur ~20 cles x 3 colonnes — voir la remarque de
        # l'utilisateur, "gros ralentissements ... les manips sont donc tres
        # lourdes".
        self._column_type_preview_timer = QTimer(self)
        self._column_type_preview_timer.setSingleShot(True)
        self._column_type_preview_timer.setInterval(16)
        self._column_type_preview_timer.timeout.connect(self._apply_column_type_preview)
        self.header_visible_field.toggled.connect(self._mark_dirty)
        self.header_height_field.valueChanged.connect(self._mark_dirty)
        self.header_padding_field.valueChanged.connect(self._mark_dirty)
        self.header_color_field.changed.connect(self._mark_dirty)
        self.header_radius_field.changed.connect(self._mark_dirty)
        self.header_border_field.changed.connect(self._mark_dirty)
        self.header_border_thickness_field.valueChanged.connect(self._mark_dirty)
        self.header_icon_right_padding_field.valueChanged.connect(self._mark_dirty)
        self.header_font_family_field.changed.connect(self._mark_dirty)
        self.header_font_bold_field.toggled.connect(self._mark_dirty)
        self.header_font_italic_field.toggled.connect(self._mark_dirty)
        self.header_font_color_field.changed.connect(self._mark_dirty)
        self.header_font_size_field.valueChanged.connect(self._mark_dirty)
        self.header_font_smoothing_field.changed.connect(self._mark_dirty)
        self.item_column_width_field.valueChanged.connect(self._mark_dirty)
        self.column_gap_field.valueChanged.connect(self._mark_dirty)
        self.column_padding_field.changed.connect(self._mark_dirty)
        self.column_border_field.changed.connect(self._mark_dirty)
        self.column_border_thickness_field.valueChanged.connect(self._mark_dirty)
        self.column_border_radius_field.changed.connect(self._mark_dirty)
        self.column_bg_color_field.changed.connect(self._mark_dirty)
        self.resize_badge_position_field.changed.connect(self._mark_dirty)
        self.resize_badge_font_field.changed.connect(self._mark_dirty)
        self.resize_badge_font_bold_field.toggled.connect(self._mark_dirty)
        self.resize_badge_font_italic_field.toggled.connect(self._mark_dirty)
        self.resize_badge_font_size_field.valueChanged.connect(self._mark_dirty)
        self.resize_badge_font_smoothing_field.changed.connect(self._mark_dirty)
        self.resize_badge_text_color_field.changed.connect(self._mark_dirty)
        self.resize_badge_bg_color_field.changed.connect(self._mark_dirty)
        self.resize_badge_border_field.changed.connect(self._mark_dirty)
        self.resize_badge_border_thickness_field.valueChanged.connect(self._mark_dirty)
        self.resize_badge_border_radius_field.changed.connect(self._mark_dirty)
        # Apercu Colonnes (voir _ColumnPreview) : contrairement au reste
        # ci-dessus, doit AUSSI se redessiner EN DIRECT (pas seulement
        # _mark_dirty — cet apercu ne vit que dans cette fenetre, rien ne
        # le repeint via apply_all_settings).
        for field_signal in (
            self.header_height_field.valueChanged, self.header_padding_field.valueChanged,
            self.header_color_field.changed, self.header_radius_field.changed,
            self.header_border_field.changed, self.header_border_thickness_field.valueChanged,
            self.header_icon_right_padding_field.valueChanged, self.header_font_family_field.changed,
            self.header_font_color_field.changed, self.header_font_bold_field.toggled,
            self.header_font_size_field.valueChanged,
            self.column_gap_field.valueChanged, self.column_padding_field.changed,
            self.column_border_field.changed, self.column_bg_color_field.changed,
            self.column_border_thickness_field.valueChanged, self.column_border_radius_field.changed,
        ):
            field_signal.connect(self._apply_column_preview)
            # Colonnes > Type (voir _apply_column_type_preview) : une ligne
            # dont le toggle est OFF suit CE champ general — la boite
            # "Type" de l'apercu doit donc AUSSI se redessiner quand il
            # bouge, pas seulement quand un champ de Colonnes > Type change.
            # _schedule_column_type_preview (PAS l'appel direct) : ce champ
            # GENERAL emet, lui aussi, a chaque pixel d'un glisser de
            # slider — meme raison que _connect_column_type_overrides.
            # SANS garde hasattr (contrairement a avant) : l'onglet Colonnes
            # est desormais construit PARESSEUSEMENT (voir _on_main_tab_
            # changed), _type_toggles peut donc encore ne pas exister ICI —
            # sans consequence, _schedule_column_type_preview/_apply_column_
            # type_preview se no-opent deja proprement tant qu'il n'existe
            # pas (voir leurs docstrings), et cette connexion reste valide
            # pour la suite (une fois l'onglet visite).
            field_signal.connect(self._schedule_column_type_preview)
        self._apply_column_preview()
        # Items (voir _section_items/_ItemRowPreview) : meme principe que
        # l'apercu Colonnes juste au-dessus (_mark_dirty PARTOUT +
        # redessin EN DIRECT de l'apercu, propre a cette fenetre).
        self.item_font_field.changed.connect(self._mark_dirty)
        self.item_font_size_field.valueChanged.connect(self._mark_dirty)
        self.item_font_bold_field.toggled.connect(self._mark_dirty)
        self.item_font_italic_field.toggled.connect(self._mark_dirty)
        self.item_antialias_field.changed.connect(self._mark_dirty)
        self.item_header_gap_field.valueChanged.connect(self._mark_dirty)
        for spec in _ITEM_TEXT_FIELD_SPECS:
            spec.dirty_signal(getattr(self, _ITEM_TEXT_FIELD_ATTR[spec.key])).connect(self._mark_dirty)
        self.item_row_border_field.changed.connect(self._mark_dirty)
        self.item_image_padding_field.changed.connect(self._mark_dirty)
        self.item_image_border_field.changed.connect(self._mark_dirty)
        self.item_image_border_thickness_field.valueChanged.connect(self._mark_dirty)
        self.item_image_radius_field.changed.connect(self._mark_dirty)
        self.item_image_ratio_field.valueChanged.connect(self._mark_dirty)
        self.preview_padding_field.changed.connect(self._mark_dirty)
        self.preview_radius_field.changed.connect(self._mark_dirty)
        self.preview_title_zone_height_field.valueChanged.connect(self._mark_dirty)
        self.preview_title_font_size_field.valueChanged.connect(self._mark_dirty)
        self.preview_title_font_color_field.changed.connect(self._mark_dirty)
        self.preview_title_font_family_field.changed.connect(self._mark_dirty)
        self.preview_title_font_bold_field.toggled.connect(self._mark_dirty)
        self.preview_title_font_italic_field.toggled.connect(self._mark_dirty)
        self.preview_title_font_smoothing_field.changed.connect(self._mark_dirty)
        self.preview_title_padding_field.changed.connect(self._mark_dirty)
        self.preview_status_font_size_field.valueChanged.connect(self._mark_dirty)
        self.preview_status_font_color_field.changed.connect(self._mark_dirty)
        self.preview_status_font_color_idle_field.changed.connect(self._mark_dirty)
        self.preview_status_font_family_field.changed.connect(self._mark_dirty)
        self.preview_status_font_bold_field.toggled.connect(self._mark_dirty)
        self.preview_status_font_italic_field.toggled.connect(self._mark_dirty)
        self.preview_status_font_smoothing_field.changed.connect(self._mark_dirty)
        self.preview_status_padding_field.changed.connect(self._mark_dirty)
        self.preview_toggle_width_field.valueChanged.connect(self._mark_dirty)
        self.preview_toggle_height_field.valueChanged.connect(self._mark_dirty)
        self.preview_toggle_bg_field.changed.connect(self._mark_dirty)
        self.preview_toggle_border_field.changed.connect(self._mark_dirty)
        self.preview_toggle_border_thickness_field.valueChanged.connect(self._mark_dirty)
        self.preview_toggle_radius_field.valueChanged.connect(self._mark_dirty)
        self.preview_toggle_x_field.valueChanged.connect(self._mark_dirty)
        self.preview_toggle_y_field.valueChanged.connect(self._mark_dirty)
        self.collapse_toggle_mode_field.changed.connect(self._mark_dirty)
        self.shortcut_font_family_field.changed.connect(self._mark_dirty)
        self.shortcut_font_bold_field.toggled.connect(self._mark_dirty)
        self.shortcut_font_italic_field.toggled.connect(self._mark_dirty)
        self.shortcut_color_field.changed.connect(self._mark_dirty)
        self.shortcut_font_size_field.valueChanged.connect(self._mark_dirty)
        self.shortcut_font_smoothing_field.changed.connect(self._mark_dirty)
        self.item_selection_focus_field.changed.connect(self._mark_dirty)
        self.item_selection_unfocus_field.changed.connect(self._mark_dirty)
        self.item_hover_field.changed.connect(self._mark_dirty)
        self.item_idle_field.changed.connect(self._mark_dirty)
        self.item_selection_padding_field.changed.connect(self._mark_dirty)
        self.item_selection_border_field.changed.connect(self._mark_dirty)
        self.item_selection_radius_field.changed.connect(self._mark_dirty)
        self.item_selection_edge_border_field.toggled.connect(self._mark_dirty)
        for state in ("unfocus", "hover", "idle"):
            for key, sig_attr in (
                ("padding", "changed"), ("border", "changed"), ("radius", "changed"), ("edge_border", "toggled"),
            ):
                field_widget = getattr(self, f"item_selection_{state}_{key}_field")
                getattr(field_widget, sig_attr).connect(self._mark_dirty)
                getattr(self, f"item_selection_{state}_{key}_toggle").toggled.connect(self._mark_dirty)
        item_text_signals = [
            spec.dirty_signal(getattr(self, _ITEM_TEXT_FIELD_ATTR[spec.key])) for spec in _ITEM_TEXT_FIELD_SPECS
        ]
        for field_signal in (
            self.item_font_field.changed, self.item_font_size_field.valueChanged,
            self.item_font_bold_field.toggled,
            self.item_antialias_field.changed,
            *item_text_signals,
            self.item_row_border_field.changed,
            self.item_image_padding_field.changed, self.item_image_border_field.changed,
            self.item_image_border_thickness_field.valueChanged, self.item_image_radius_field.changed,
            self.item_header_gap_field.valueChanged,
            self.item_selection_focus_field.changed, self.item_selection_unfocus_field.changed,
            self.item_hover_field.changed, self.item_idle_field.changed, self.item_selection_padding_field.changed,
            self.item_selection_border_field.changed, self.item_selection_radius_field.changed,
            self.item_selection_edge_border_field.toggled,
            *(
                getattr(getattr(self, f"item_selection_{state}_{key}_field"), sig_attr)
                for state in ("unfocus", "hover", "idle")
                for key, sig_attr in (
                    ("padding", "changed"), ("border", "changed"),
                    ("radius", "changed"), ("edge_border", "toggled"),
                )
            ),
            *(
                getattr(self, f"item_selection_{state}_{key}_toggle").toggled
                for state in ("unfocus", "hover", "idle")
                for key in ("padding", "border", "radius", "edge_border")
            ),
        ):
            field_signal.connect(self._apply_item_preview)
            # _schedule_column_type_preview (PAS l'appel direct) : meme
            # raison que ci-dessus (Colonnes > Type suit aussi ces champs
            # GENERAUX Items quand son toggle de ligne est OFF). SANS garde
            # hasattr : voir la remarque juste au-dessus (onglet Colonnes
            # desormais paresseux).
            field_signal.connect(self._schedule_column_type_preview)
        self._apply_item_preview()
        self.columns_resizable_toggle.toggled.connect(self._mark_dirty)
        # En plus de piloter les colonnes du navigateur principal (settings
        # persistees, voir _current_values), ce toggle gouverne aussi en
        # DIRECT les colonnes des tableaux de CETTE fenetre (Geometrie/
        # Polices principales) — voir la remarque de l'utilisateur, "le
        # toggle dans les tableaux doit activer ou non la fonctionnalite de
        # colonnes redimensionnable".
        self.columns_resizable_toggle.toggled.connect(self._apply_columns_resizable)
        self._apply_columns_resizable(self.columns_resizable_toggle.isChecked())
        # Glisser une bordure de colonne (voir _ResizableTableHeader.resized,
        # Geometrie/Polices principales) est aussi une modification a
        # sauvegarder (voir geo_table_columns/font_table_columns dans
        # _current_values) — sans ce cablage, la fenetre ne se marquait
        # jamais "modifications non enregistrees" apres un tel glisser,
        # voir la remarque de l'utilisateur.
        self.geo_table.head.resized.connect(self._mark_dirty)
        self.font_table.head.resized.connect(self._mark_dirty)
        # Tableaux SANS entete (voir _FlatColumnResizer/_apply_columns_
        # resizable) : PAS de _mark_dirty ici, contrairement aux 2 ci-dessus
        # — cette largeur n'est PAS sauvegardee (pas de cle dans les
        # reglages/un preset, juste un confort d'affichage pour la session
        # en cours), un _mark_dirty afficherait donc "modifications non
        # enregistrees" pour un changement qu'Enregistrer ne capture pas
        # reellement. _refresh_content_layout (voir sa docstring) au cas ou
        # une note de ligne (voir _label_block) finirait par forcer un
        # retour a la ligne a une largeur plus etroite.
        for resizer in self._flat_resizers:
            resizer.resized.connect(lambda _w: self._refresh_content_layout())
        # Toggles > Style + Toggle 1/Toggle 2 > Cadre/Coche (voir
        # _ToggleStylePicker/_build_toggle_shape_tables/_on_toggle_style_
        # changed) : n'importe lequel de ces reglages doit rejouer le style
        # COURANT sur tous les _Toggle deja construits (voir _Toggle.
        # apply_style — necessaire, pas un simple repaint, la taille meme
        # du cadre peut avoir change) et rafraichir les 2 apercus de la
        # carte de style (voir _ToggleStylePicker.refreshPreviews).
        self.toggle_style_field.changed.connect(self._on_toggle_style_changed)
        for prefix in ("toggle1", "toggle2"):
            w = self._toggle_widgets[prefix]
            for key in (
                "outer_width", "outer_height", "outer_border_thickness",
                "coche_width", "coche_margin", "coche_border_thickness",
            ):
                w[key].valueChanged.connect(self._on_toggle_style_changed)
            for key in (
                "outer_border", "coche_border", "outer_bg", "outer_bg_on", "coche_color",
                "outer_border_radius", "coche_border_radius",
            ):
                w[key].changed.connect(self._on_toggle_style_changed)
        self.geo_table.changed.connect(self._on_window_radius_changed)
        # Geometrie > Slider (voir _section_geometry) : contrairement aux
        # AUTRES reglages ci-dessus, ceux-la doivent aussi rejouer l'habillage
        # de TOUS les _MiniSlider deja construits (voir _apply_slider_style) —
        # thumb_h/track_h changent la hauteur meme du widget, pas seulement
        # ce qu'il peint, un simple _mark_dirty (repaint implicite via
        # settingsChanged/preview) ne suffirait pas pour CETTE fenetre.
        for slider_field in (
            self.slider_thumb_width_field, self.slider_thumb_height_field, self.slider_track_height_field,
        ):
            slider_field.valueChanged.connect(self._on_slider_style_changed)
        for color_field in (
            self.slider_thumb_color_field, self.slider_track_fill_field, self.slider_track_empty_field,
            self.slider_thumb_border_field, self.slider_track_border_field,
            self.slider_thumb_radius_field, self.slider_track_radius_field,
        ):
            color_field.changed.connect(self._on_slider_style_changed)
        # Les menus deroulants (selecteurs de police, couleur d'entete) ont
        # exactement le meme habillage qu'une zone de saisie normale (voir
        # _SelectField/_HeaderColorField) : ils suivent donc ce meme reglage,
        # en plus des vrais QLineEdit de la fenetre principale (voir
        # pipeline_browser.apply_all_settings) — voir la remarque de
        # l'utilisateur, capture a l'appui.
        self.geo_table.input_radius_field.valueChanged.connect(self._queue_dropdown_radius)
        self._apply_dropdown_radius(self.geo_table.input_radius_field.value())
        self.table_radius_field.valueChanged.connect(self._apply_table_radius)
        self._apply_table_radius(self.table_radius_field.value())
        # Tableaux > Bordure/Epaisseur de bordure (voir _TableFrame.
        # setBorder) : meme cablage direct que Couleur d'en-tete plus bas
        # (pas seulement _mark_dirty — ces tableaux vivent UNIQUEMENT dans
        # cette fenetre, rien ne les repeint via apply_all_settings).
        self.table_border_field.changed.connect(self._queue_table_border)
        self.table_border_field.changed.connect(self._mark_dirty)
        self.table_border_thickness_field.valueChanged.connect(self._queue_table_border)
        self.table_border_thickness_field.valueChanged.connect(self._mark_dirty)
        for field in (self.table_inner_h_field, self.table_inner_v_field):
            field.changed.connect(self._queue_table_border)
            field.changed.connect(self._mark_dirty)
        self._apply_table_border()
        # Tableaux > Padding des cellules (voir _CellPaddingField) : meme
        # cablage que Rayon des angles juste au-dessus — le changed unique
        # du widget composite couvre a la fois le toggle "lie" et les 4
        # sliders (voir _CellPaddingField.__init__).
        self.cell_padding_field.changed.connect(self._on_cell_padding_changed)
        self._apply_cell_padding(self.cell_padding_field.sidesValue())
        # Tableaux > Couleur d'en-tete (voir _HeaderColorField) : meme
        # cablage direct que Rayon des angles/Padding ci-dessus (pas
        # seulement _mark_dirty — ces 2 tableaux vivent UNIQUEMENT dans
        # cette fenetre, rien ne les repeint via apply_all_settings).
        self.table_head_color_field.changed.connect(self._apply_table_head_color)
        self.table_head_color_field.changed.connect(self._mark_dirty)
        self._apply_table_head_color(self.table_head_color_field.value())
        # Geometrie > Boutons > Coins arrondis : jusqu'ici seul le popup
        # couleur (Reinitialiser/Annuler/Valider) suivait ce reglage — voir
        # _apply_button_radius, qui couvre desormais aussi les boutons
        # PERSISTANTS de cette fenetre (barre du bas, Parcourir, preset),
        # restes orphelins de ce reglage jusqu'a present (voir la remarque
        # de l'utilisateur, capture a l'appui).
        self.geo_table.button_radius_field.valueChanged.connect(self._queue_button_radius)
        self._apply_button_radius(self.geo_table.button_radius_field.value())

    def _queue_button_radius(self, radius: int):
        """Voir _queue_dropdown_radius, meme raison (performances)."""
        self._button_radius_pending = radius
        if not self._button_radius_timer.isActive():
            self._button_radius_timer.start()

    def _flush_button_radius(self):
        if self._button_radius_pending is not None:
            self._apply_button_radius(self._button_radius_pending)
            self._button_radius_pending = None

    def _apply_button_radius(self, radius: int):
        """Tous les _Btn suivent (inscription automatique, voir settings_theme)."""
        _set_button_radius(radius)

    def _collect_table_dims(self) -> dict:
        """Dimensions de tous les tableaux deja affiches ; les autres gardent
        leurs valeurs enregistrees."""
        dims = dict(self.settings.get("table_dims") or {})
        for frame in self.findChildren(_TableFrame):
            if frame._dims_applied:
                dims[frame.dimsKey()] = frame.collectDims()
        return dims

    def _apply_columns_resizable(self, enabled: bool):
        """Tableaux > Colonnes dimensionnables : active/desactive le
        glisser sur les tableaux a en-tete multi-colonnes de CETTE fenetre
        (Geometrie, Polices principales — voir _ResizableTableHeader.
        setResizable) ET sur les tableaux SANS entete (Application/
        Tableaux/Toggles/Sliders/Entetes — voir _FlatColumnResizer.
        setResizable) — voir la remarque de l'utilisateur, "je veux aussi
        pouvoir redimensionner les colonnes meme si le tableau n'a pas
        d'entete" : meme toggle, meme interrupteur, plutot qu'un 2e reglage
        distinct. Seule la grille Couleurs (_ColorGrid, structure en grille
        2 colonnes, pas des lignes libelle/controle) n'est pas concernee."""
        self.geo_table.head.setResizable(enabled)
        self.gap_table.head.setResizable(enabled)
        self.title_font_table.head.setResizable(enabled)
        self.font_table.head.setResizable(enabled)
        for frame in self.findChildren(_TableFrame):
            frame.setWidthResizable(enabled)
        for resizer in self._flat_resizers:
            resizer.setResizable(enabled)

    def _toggle_shape_values(self, prefix: str) -> dict:
        """Valeurs courantes des 2 tableaux Cadre/Coche d'UN style de
        toggle (voir _build_toggle_shape_tables) — utilise par
        _current_values (sauvegarde) ET _on_toggle_style_changed (aperçu en
        direct), pour ne pas dupliquer cette liste de cles a 2 endroits."""
        w = self._toggle_widgets[prefix]
        return {
            f"{prefix}_outer_width": w["outer_width"].value(),
            f"{prefix}_outer_height": w["outer_height"].value(),
            f"{prefix}_outer_border_enabled": w["outer_border"].sidesEnabledValue(),
            f"{prefix}_outer_border": w["outer_border"].sidesValue(),
            f"{prefix}_outer_border_thickness": w["outer_border_thickness"].value(),
            f"{prefix}_outer_border_radius": w["outer_border_radius"].cornersValue(),
            f"{prefix}_outer_border_radius_linked": w["outer_border_radius"].isLinked(),
            f"{prefix}_outer_bg": w["outer_bg"].value(),
            f"{prefix}_outer_bg_on": w["outer_bg_on"].value(),
            f"{prefix}_coche_width": w["coche_width"].value(),
            f"{prefix}_coche_margin": w["coche_margin"].value(),
            f"{prefix}_coche_border_enabled": w["coche_border"].sidesEnabledValue(),
            f"{prefix}_coche_border": w["coche_border"].sidesValue(),
            f"{prefix}_coche_border_thickness": w["coche_border_thickness"].value(),
            f"{prefix}_coche_border_radius": w["coche_border_radius"].cornersValue(),
            f"{prefix}_coche_border_radius_linked": w["coche_border_radius"].isLinked(),
            f"{prefix}_coche_color": w["coche_color"].value(),
        }

    def _apply_toggle_shape_values(self, prefix: str):
        """Restaure les 2 tableaux Cadre/Coche d'UN style de toggle depuis
        self.settings (voir _apply_values_to_controls, un preset)."""
        w = self._toggle_widgets[prefix]
        s = self.settings
        w["outer_width"].setValue(int(s.get(f"{prefix}_outer_width", w["outer_width"].value())))
        w["outer_height"].setValue(int(s.get(f"{prefix}_outer_height", w["outer_height"].value())))
        w["outer_border"].setValue(
            _coerce_side_enabled(s.get(f"{prefix}_outer_border_enabled", True)), s.get(f"{prefix}_outer_border") or {})
        w["outer_border_thickness"].setValue(int(s.get(f"{prefix}_outer_border_thickness", 1)))
        w["outer_border_radius"].setValue(
            bool(s.get(f"{prefix}_outer_border_radius_linked", True)),
            _coerce_corner_radius(s.get(f"{prefix}_outer_border_radius", 0)))
        w["outer_bg"].setValue(s.get(f"{prefix}_outer_bg", w["outer_bg"].value()))
        w["outer_bg_on"].setValue(s.get(f"{prefix}_outer_bg_on", w["outer_bg_on"].value()))
        w["coche_width"].setValue(int(s.get(f"{prefix}_coche_width", w["coche_width"].value())))
        w["coche_margin"].setValue(int(s.get(f"{prefix}_coche_margin", w["coche_margin"].value())))
        w["coche_border"].setValue(
            _coerce_side_enabled(s.get(f"{prefix}_coche_border_enabled", True)), s.get(f"{prefix}_coche_border") or {})
        w["coche_border_thickness"].setValue(int(s.get(f"{prefix}_coche_border_thickness", 1)))
        w["coche_border_radius"].setValue(
            bool(s.get(f"{prefix}_coche_border_radius_linked", True)),
            _coerce_corner_radius(s.get(f"{prefix}_coche_border_radius", 0)))
        w["coche_color"].setValue(s.get(f"{prefix}_coche_color", w["coche_color"].value()))

    def _on_toggle_style_changed(self, *_args):
        """Toggles > Style, ou n'importe quel reglage Cadre/Coche de Toggle
        1/Toggle 2 : rejoue le style courant sur TOUS les _Toggle deja
        construits dans cette fenetre (voir _TOGGLE_STYLE/_Toggle.
        apply_style — necessaire, pas un simple repaint, la taille meme du
        cadre peut avoir change) et rafraichit les 2 apercus de la carte de
        style (voir _ToggleStylePicker.refreshPreviews)."""
        settings = dict(self.settings)
        # colors LIVE (pas self.settings["colors"], perime pendant un
        # glisser de la page Couleurs) : necessaire pour resoudre les
        # bordures Cadre/Coche en mode "App" (voir _AppOrCustomColorField/
        # _sync_toggle_shape_style, qui lit settings["colors"]).
        colors = dict(self.settings["colors"])
        colors.update(self.color_grid.value())
        settings["colors"] = colors
        settings["toggle_style"] = self.toggle_style_field.value()
        settings.update(self._toggle_shape_values("toggle1"))
        settings.update(self._toggle_shape_values("toggle2"))
        # Court-circuit (meme principe que _refresh_dynamic_colors, voir sa
        # remarque de tete) : ce style ne depend QUE des cles rassemblees
        # ci-dessus (toggle_style + formes toggle1/toggle2 + couleurs LIVE)
        # — pas la peine de resynchroniser _TOGGLE_STYLE et repasser
        # apply_style() sur TOUS les _Toggle deja construits si rien de
        # tout ca n'a REELLEMENT change depuis le dernier appel. Appelee a
        # CHAQUE tick de _on_colors_changed (voir sa remarque, "gros
        # ralentissements ... manips tres lourdes"), le plus souvent SANS
        # le moindre rapport avec le style des toggles (la pastille glissee
        # n'etant referencee par AUCUN champ Cadre/Coche en mode "App").
        snapshot = json.dumps(settings, sort_keys=True, default=str)
        if snapshot != getattr(self, "_toggle_style_snapshot", None):
            self._toggle_style_snapshot = snapshot
            _sync_toggle_style(settings)
            for toggle in self.findChildren(_Toggle):
                toggle.apply_style()
        self.toggle_style_field.refreshPreviews()
        self._sync_toggle_style_visibility()
        self._mark_dirty()

    def _queue_dropdown_radius(self, radius: int):
        """Voir la remarque de tete pres de _dropdown_radius_timer
        (__init__) : ne fait QUE retarder l'appel reel de 30ms, en ne
        retenant que la DERNIERE valeur si plusieurs ticks arrivent avant
        l'echeance (glisser de slider)."""
        self._dropdown_radius_pending = radius
        if not self._dropdown_radius_timer.isActive():
            self._dropdown_radius_timer.start()

    def _flush_dropdown_radius(self):
        if self._dropdown_radius_pending is not None:
            self._apply_dropdown_radius(self._dropdown_radius_pending)
            self._dropdown_radius_pending = None

    def _apply_dropdown_radius(self, radius: int):
        """Applique le rayon a TOUTES les boites habillees comme une zone de
        saisie (boites de valeur des sliders, menus deroulants, boites hex,
        boite de preset) : chacune s'est inscrite a sa creation (voir
        settings_theme._register_input), aucune liste a tenir ici."""
        _set_input_radius(radius)
        self._sync_preset_box()

    def _apply_column_preview(self, *_args):
        """No-op — aperçus de colonnes SUPPRIMES (voir _section_headers,
        la remarque de l'utilisateur, "supprime les apercus de colonnes").
        Methode gardee UNIQUEMENT parce que des dizaines de signaux y sont
        deja connectes (voir _connect_live_updates) ; rien a y rejouer."""
        return

    def _apply_item_preview(self, *_args):
        """No-op — aperçus de colonnes SUPPRIMES, voir _apply_column_preview
        (MEME raison, meme gardee que pour les dizaines de signaux deja
        connectes)."""
        return

    def _resolve_item_font_family(self, value: str) -> str:
        """Colonnes > Texte > Police : `value` peut etre "Systeme" (auto,
        voir _qfont dans _ItemPreviewRow.setRowStyle), un libelle "police du
        soft" (voir ITEM_FONT_ROLE_LABELS — resolu ICI vers la famille
        REELLEMENT choisie pour ce role dans Polices principales, live, pas
        figee) ou une police SYSTEME litterale (renvoyee telle quelle)."""
        role = next((r for r, label in ITEM_FONT_ROLE_LABELS.items() if label == value), None)
        if role is None:
            return "" if value == "Systeme" else value
        settings_key = next(key for key, r, _label, _sample in _FONT_ROLES if r == role)
        picked = self.font_table.rows[settings_key]["field"].value()
        return auto_family_for_role(role) if picked == "Systeme" else picked

    def _apply_table_head_color(self, slot: str):
        """Tableaux > Couleur d'en-tete (voir _HeaderColorField) : applique
        la pastille choisie au fond de l'entete des 2 tableaux A EN-TETE de
        cette fenetre (Polices/Geometrie — les seuls a en avoir un, voir
        _restyle_table_head/_ResizableTableHeader._custom_bg). Rejoue
        ensuite _apply_table_radius (pas seulement _restyle_table_head
        directement) : c'est lui qui connait deja le rayon COURANT de
        chaque entete, evite de le dupliquer ici."""
        # _current_hex() (pas self.settings["colors"] directement) : lit la
        # palette LIVE que le champ suit deja (voir _HeaderColorField.
        # refresh_colors, rappele a chaque glisser de la page Couleurs,
        # voir _on_colors_changed) — self.settings["colors"] resterait
        # perime pendant un tel glisser (mis a jour seulement a l'Enregistrer).
        hexval = self.table_head_color_field._current_hex()
        _TABLE_HEAD["bg"] = hexval
        self.font_table.head._custom_bg = hexval
        self.geo_table.head._custom_bg = hexval
        self.gap_table.head._custom_bg = hexval
        self.title_font_table.head._custom_bg = hexval
        self.table_preview.head._custom_bg = hexval
        self._apply_table_radius(self.table_radius_field.value())

    def _apply_table_radius(self, radius: int):
        """Geometrie > Tableaux > Coins arrondis : les 4 tableaux a entete
        (Polices, Geometrie, apercu, Couleurs), plus TOUS les tableaux fermes
        sans entete, inscrits a leur construction (voir
        settings_layout._register_flat_table). La premiere ligne d'un tableau
        sans entete porte les coins hauts, la derniere les coins bas.

        La bordure est rejouee ici aussi : cette fonction est rappelee apres
        un changement de couleur (voir _refresh_dynamic_colors), et une
        couleur de bordure « @<slot> » doit suivre la palette en direct."""
        self.font_table.apply_radius(radius)
        self.geo_table.apply_radius(radius)
        self.gap_table.apply_radius(radius)
        self.title_font_table.apply_radius(radius)
        self.table_preview.apply_radius(radius)
        self.color_grid.setRadius(radius)
        _set_flat_tables_style(radius=radius)
        self._apply_table_border()

    def _queue_table_border(self, *_args):
        """Applique les bordures de tableaux apres une courte pause (voir
        _table_border_timer) : seule la derniere valeur compte."""
        self._table_border_timer.start()

    def _seed_table_inner_border(self):
        colors = self.settings["colors"]
        _set_table_inner_border(*(
            (self.settings[f"table_inner_{axis}_enabled"],
             _resolve_color_value(self.settings[f"table_inner_{axis}_color"], colors),
             self.settings[f"table_inner_{axis}_thickness"]) for axis in ("h", "v")))

    def _set_inner_from_fields(self, colors: dict):
        _set_table_inner_border(*(
            (field.value()[0], _resolve_color_value(field.value()[1], colors), field.value()[2])
            for field in (self.table_inner_h_field, self.table_inner_v_field)))

    def _restyle_table_inner(self):
        """Rejoue fond/filets des lignes et entetes de tous les tableaux quand
        la bordure interieure change (voir settings_widgets._inner_edge)."""
        from settings_widgets import _TABLE_INNER_BORDER
        sig = json.dumps(_TABLE_INNER_BORDER, sort_keys=True)
        if sig == getattr(self, "_inner_border_sig", None):
            return
        first = not hasattr(self, "_inner_border_sig")
        self._inner_border_sig = sig
        if first:
            return   # etat de depart deja pose a la construction
        radius = self.table_radius_field.value()
        for table in (self.font_table, self.geo_table, self.gap_table, self.title_font_table, self.table_preview):
            table.apply_radius(radius)
        _set_flat_tables_style(radius=radius)
        self._apply_cell_padding(self.cell_padding_field.sidesValue())
        # Les filets V sont peints (pas du QSS) : un restyle a l'identique ne
        # repeint rien, d'ou des filets coupes sur les zones non rafraichies.
        for widget in self.findChildren(_TableRow) + self.findChildren(_ResizableTableHeader):
            widget.update()

    def _flush_table_border(self):
        self._apply_table_border()

    def _apply_table_border(self, *_args):
        """Tableaux > Bordure/Epaisseur de bordure, sur les memes tableaux que
        _apply_table_radius. Couleurs resolues sur la palette EN DIRECT
        (glisser dans la page Couleurs), pas seulement self.settings."""
        enabled = self.table_border_field.sidesEnabledValue()
        live_colors = dict(self.settings["colors"])
        live_colors.update(self.color_grid.value())
        colors = {k: _resolve_color_value(v, live_colors) for k, v in self.table_border_field.sidesValue().items()}
        thickness = self.table_border_thickness_field.value()
        self._set_inner_from_fields(live_colors)
        self._restyle_table_inner()
        self.font_table.apply_border(enabled, colors, thickness)
        self.geo_table.apply_border(enabled, colors, thickness)
        self.gap_table.apply_border(enabled, colors, thickness)
        self.title_font_table.apply_border(enabled, colors, thickness)
        self.table_preview.apply_border(enabled, colors, thickness)
        _set_flat_tables_style(border=(enabled, colors, thickness))

    def _apply_cell_padding(self, sides: dict):
        """Tableaux > Padding des cellules : TOUS les tableaux de cette
        fenetre — tableaux fermes sans entete (inscrits, voir
        settings_layout._register_flat_table), grille Couleurs, Polices et
        Geometrie (leur entete suit le gauche/droite pour rester aligne)."""
        left = int(sides.get("left", 14))
        top = int(sides.get("top", 8))
        right = int(sides.get("right", 14))
        bottom = int(sides.get("bottom", 8))
        _set_flat_tables_style(padding=(left, top, right, bottom))
        for cell, _row, _col in self.color_grid._cells:
            cell.layout().setContentsMargins(left, top, right, bottom)
            cell.setMinimumHeight(0)
            _lock_min_height(cell)
        self.font_table.setCellPadding(sides)
        self.geo_table.setCellPadding(sides)
        self.gap_table.setCellPadding(sides)
        self.title_font_table.setCellPadding(sides)
        self.table_preview.setCellPadding(sides)
        self._refresh_content_layout([
            *_flat_tables(self),
            self.color_grid.wrap, self.font_table.frame, self.geo_table.frame_wrap, self.gap_table.frame_wrap, self.title_font_table.frame_wrap, self.table_preview.frame,
        ])

    def _refresh_content_layout(self, frames: list[QWidget] = ()):
        """A appeler apres tout changement qui modifie la hauteur d'un
        tableau EN DIRECT (voir _apply_cell_padding) sur une section DEJA
        depliee — sans ca, le tableau grandit bien lui-meme (son propre
        sizeHint() est a jour des l'instant du changement) mais tout ce qui
        l'entoure (son cadre, sa _Section, l'ascenseur de _build_content)
        garde encore l'ANCIEN plancher, plus court : le tableau se
        retrouvait ecrase dans un espace trop petit au lieu de pousser le
        reste de la page vers le bas — voir la remarque de l'utilisateur,
        "je veux que la position du tableau ne change pas du tout en haut
        a gauche, mais que le tableau se redimensionne automatiquement
        vers le bas".

        Remonte la chaine dans l'ordre (chaque niveau doit etre a jour
        AVANT que le niveau suivant ne le lise) :
        1. `frames` (le cadre de CHAQUE tableau modifie, voir l'appelant) —
           son layout().activate() force Qt a COMPARER sa taille au cadre a
           sa taille PRECEDENTE et a prevenir son parent (section._body) du
           changement ; interroger frame.sizeHint() seul, sans ce passage,
           ne suffit PAS malgre une valeur deja a jour — sizeHint() est une
           simple lecture, sans effet de bord, elle ne previent jamais un
           parent d'un changement (voir la remarque de l'utilisateur,
           capture a l'appui : le cadre restait a l'ancienne taille malgre
           un sizeHint() interroge directement deja correct).
        2. Chaque _Section deja depliee (refresh_min_height, voir sa
           docstring) — peut alors lire un sizeHint() de son corps
           correctement remonte depuis (1).
        3. L'ascenseur lui-meme — _NoSqueezeScrollArea ne reagit que sur un
           vrai QResizeEvent (un redimensionnement MANUEL de la fenetre par
           l'utilisateur), jamais juste parce que son contenu a change de
           taille : le meme calcul est donc rejoue ici a la main pour
           agrandir tout de suite l'espace dispo (scrollbar comprise)
           plutot que d'attendre un tel redimensionnement."""
        for frame in frames:
            frame.layout().activate()
        for section in self.findChildren(_Section):
            section.refresh_min_height()
        scroller = self._content_scroller
        inner = scroller.widget()
        inner.layout().activate()
        target_height = max(scroller.viewport().height(), inner.minimumSizeHint().height())
        if inner.height() != target_height or inner.width() != scroller.viewport().width():
            inner.resize(scroller.viewport().width(), target_height)

    def _on_cell_padding_changed(self):
        self._apply_cell_padding(self.cell_padding_field.sidesValue())
        self._mark_dirty()

    def _on_slider_style_changed(self, *_args):
        self._apply_slider_style()
        self._mark_dirty()

    def _apply_slider_style(self):
        """Reapplique en direct Geometrie > Slider sur TOUS les _MiniSlider
        deja construits (voir _MiniSlider.apply_style) — necessaire,
        contrairement aux autres reglages qui suivent M (repaint implicite
        au prochain paintEvent), car thumb_h/track_h changent la hauteur
        meme du widget, pas seulement ce qu'il peint."""
        settings = dict(self.settings)
        # colors LIVE : voir _on_toggle_style_changed, meme raison
        # (bordures Selecteur/Rail en mode "App").
        colors = dict(self.settings["colors"])
        colors.update(self.color_grid.value())
        settings["colors"] = colors
        settings["slider_thumb_width"] = self.slider_thumb_width_field.value()
        settings["slider_thumb_height"] = self.slider_thumb_height_field.value()
        settings["slider_thumb_color"] = self.slider_thumb_color_field.value()
        settings["slider_thumb_border"] = self.slider_thumb_border_field.sidesValue()
        settings["slider_thumb_border_enabled"] = self.slider_thumb_border_field.sidesEnabledValue()
        settings["slider_thumb_radius"] = self.slider_thumb_radius_field.cornersValue()
        settings["slider_track_height"] = self.slider_track_height_field.value()
        settings["slider_track_fill_color"] = self.slider_track_fill_field.value()
        settings["slider_track_empty_color"] = self.slider_track_empty_field.value()
        settings["slider_track_border"] = self.slider_track_border_field.sidesValue()
        settings["slider_track_border_enabled"] = self.slider_track_border_field.sidesEnabledValue()
        settings["slider_track_radius"] = self.slider_track_radius_field.cornersValue()
        # Court-circuit (meme principe que _on_toggle_style_changed/
        # _refresh_dynamic_colors ci-dessus) : rien a refaire si aucune des
        # cles slider_* ci-dessus n'a REELLEMENT change depuis le dernier
        # appel — meme raison, appelee a chaque tick de _on_colors_changed.
        snapshot = json.dumps(settings, sort_keys=True, default=str)
        if snapshot == getattr(self, "_slider_style_snapshot", None):
            return
        self._slider_style_snapshot = snapshot
        _sync_slider_style(settings)
        for slider in QApplication.allWidgets():
            if isinstance(slider, _MiniSlider):
                slider.apply_style()

    def _schedule_colors_changed(self):
        """Voir le commentaire de _connect_live_updates : regroupe les
        rafales de colorChanged (glisser un slider) en un seul passage
        de _on_colors_changed par fenetre de 16ms — celui-ci relit de
        toute facon l'etat COURANT (self.color_grid.value()), donc la
        derniere position du slider au moment ou le timer se declenche
        est bien celle appliquee, jamais une valeur perimee."""
        if not self._colors_changed_timer.isActive():
            self._colors_changed_timer.start()

    def _on_colors_changed(self):
        merged_colors = dict(self.settings["colors"])
        merged_colors.update(self.color_grid.value())
        self.header_color_field.refresh_colors(merged_colors)
        self.table_head_color_field.refresh_colors(merged_colors)
        # Rejoue en direct (pas seulement refresh_colors, qui ne change que
        # la palette SOURCE lue au prochain _current_hex()) : sans ca, la
        # couleur affichee sur l'entete de Polices/Geometrie restait celle
        # d'AVANT le glisser tant que la pastille choisie ici n'etait pas
        # elle-meme celle qu'on glisse (voir _refresh_dynamic_colors, dont
        # le court-circuit sur 4 cles fixes ne "connait" pas cette pastille
        # CHOISISSABLE par l'utilisateur, potentiellement une AUTRE des ~10).
        self._apply_table_head_color(self.table_head_color_field.value())
        self._apply_column_preview()
        # boite "Type" de l'apercu Colonnes (voir _apply_column_type_preview)
        # : PAS rejouee par _apply_column_preview ci-dessus (qui ne touche
        # que les boites GENERALES), pourtant sa bordure/ses autres champs
        # peuvent aussi referencer une pastille "@<slot>" — sans cet appel,
        # elle restait perimee pendant un glisser de la page Couleurs tant
        # qu'aucun AUTRE champ de bordure n'etait touche a la main (voir la
        # remarque de l'utilisateur, "les bordures ne sont pas a jour").
        self._apply_column_type_preview()
        # Bordures de Toggles/Sliders (voir _AppOrCustomColorField, une
        # pastille en mode "App" doit suivre le glisser en direct — pas
        # besoin d'un "_apply_..." separe ici, contrairement a la couleur
        # d'entete des tableaux : chaque pastille se repeint elle-meme
        # depuis sa propre palette, voir _AppOrCustomColorField.refresh_
        # colors).
        for w in self._toggle_widgets.values():
            w["outer_border"].refresh_colors(merged_colors)
            w["coche_border"].refresh_colors(merged_colors)
        self.slider_thumb_border_field.refresh_colors(merged_colors)
        self.slider_track_border_field.refresh_colors(merged_colors)
        self.column_border_field.refresh_colors(merged_colors)
        self.column_bg_color_field.refresh_colors(merged_colors)
        self.item_selection_border_field.refresh_colors(merged_colors)
        self.item_color_field.refresh_colors(merged_colors)
        self.item_row_border_field.refresh_colors(merged_colors)
        self.item_idle_field.refresh_colors(merged_colors)
        self.item_image_border_field.refresh_colors(merged_colors)
        self.table_border_field.refresh_colors(merged_colors)
        self.table_inner_h_field.refresh_colors(merged_colors)
        self.table_inner_v_field.refresh_colors(merged_colors)
        self._apply_table_border()
        self._apply_item_preview()
        # Rejoue le rendu REEL des toggles/sliders (pas seulement les
        # pastilles ci-dessus) : _TOGGLE1_STYLE/_TOGGLE2_STYLE/_SLIDER_
        # STYLE gardent sinon le hex resolu au dernier _sync_.../_apply_...,
        # perime pendant ce glisser si la pastille choisie ici (mode "App",
        # voir _AppOrCustomColorField) est justement celle qu'on glisse.
        self._on_toggle_style_changed()
        self._apply_slider_style()
        self._refresh_dynamic_colors(merged_colors)
        self._mark_dirty()

    def _refresh_root_field_style(self):
        self.root_field.setStyleSheet(
            f"background: {M['field_bg']}; border: 1px solid {M['field_border']}; "
            f"color: {M['value_muted']}; padding: 0 8px;"
        )
        self._refresh_omit_fields_style()

    def _refresh_omit_fields_style(self):
        for field_name in ("omit_file_names_field", "omit_dir_names_field", "lut_images_field"):
            field = getattr(self, field_name, None)
            if field is not None:
                field.refresh_style()

    def _refresh_dynamic_colors(self, colors: dict):
        """Reapplique en direct (pendant le glisser d'une pastille de la
        page Couleurs, voir _on_colors_changed) tout ce qui, dans cette
        fenetre, suit desormais une couleur reglable de l'appli plutot
        qu'une valeur fixe de M — voir _sync_dynamic_M pour le detail de
        quoi suit quoi (Zone de saisie/Skin niveau 1/tableaux).

        Court-circuite tout le reste si AUCUNE des 4 couleurs que
        _sync_dynamic_M lit reellement n'a bouge depuis le dernier appel :
        c'est le cas le plus frequent au glisser (l'utilisateur edite une
        des ~10 AUTRES pastilles de la page Couleurs, ex. l'accent) — sans
        ce court-circuit, tout ce qui suit (restyle de dizaines de
        widgets, appel DWM natif) etait rejoue pour rien a chaque pixel du
        glisser, meme quand rien de ce qu'il touche n'avait change (voir
        la remarque de l'utilisateur sur la latence enorme)."""
        dynamic_keys = ("well", "topbar", "table_head", "table_row")
        snapshot = tuple(colors.get(k, C[k]) for k in dynamic_keys)
        _sync_dynamic_M(colors)
        if snapshot == getattr(self, "_dynamic_colors_snapshot", None):
            return
        self._dynamic_colors_snapshot = snapshot
        self._toolbar_bar.setStyleSheet(f"background: {M['toolbar_bg']};")
        self._content_scroller.setStyleSheet(f"background: {M['panel_bg']};")
        self._bottom_bar.setStyleSheet(
            f"background: {M['toolbar_bg']}; border-top: 1px solid {M['panel_border']};"
        )
        # self.panel : le fond de base sous tout le reste (voir
        # _apply_panel_radius) partage aussi M['panel_bg'].
        self._apply_panel_radius(self._window_radius_value())
        self._refresh_root_field_style()
        self.header_border_field.refresh_colors(colors)
        # Zones de saisie (selects, boites de valeur, preset...) et les 3
        # tableaux (Polices/Entetes/Geometrie) : deja rebatis integralement
        # par ces methodes existantes (voir _apply_dropdown_radius/
        # _apply_table_radius, utilisees jusqu'ici pour le slider de rayon
        # seulement) — simplement rappelees ici avec le rayon COURANT pour
        # forcer une relecture de M a jour, sans dupliquer leur logique.
        self._apply_dropdown_radius(self.geo_table.input_radius_field.value())
        self._apply_table_radius(self.table_radius_field.value())
        # _Toggle/_CheckSquare : peints a la main (paintEvent, voir leurs
        # classes), relisent M en direct des le prochain repaint — juste
        # besoin de le declencher, pas de reconstruire de stylesheet.
        for toggle in self.findChildren(_Toggle):
            toggle.update()
        for check in self.findChildren(_CheckSquare):
            check.update()

    def _on_window_radius_changed(self):
        self._apply_panel_radius(self._window_radius_value())
        self._mark_dirty()

    def _step_badge_values(self) -> dict:
        """Les cles de l'icone de niveaux (Colonnes > Projets > Colonnes >
        "Icone de niveaux", voir _build_column_override_page) — MEME repli
        que _column_override_values (page "Projets" construite
        PARESSEUSEMENT, voir _on_columns_tab_changed) : lues depuis les
        CHAMPS live si cette page a deja ete visitee au moins une fois,
        sinon reprises telles quelles depuis self.settings."""
        if not hasattr(self, "step_badge_width_field"):
            return {
                key: self.settings.get(key) for key in (
                    "step_badge_width", "step_badge_height",
                    "step_badge_border_enabled", "step_badge_border", "step_badge_border_thickness",
                    "step_badge_radius", "step_badge_radius_linked",
                    "step_badge_color_base2", "step_badge_color_base3", "step_badge_color_base4",
                    "step_badge_color_base5", "step_badge_color_base6", "step_badge_color_basen",
                    "step_badge_text_color_base2", "step_badge_text_color_base3", "step_badge_text_color_base4",
                    "step_badge_text_color_base5", "step_badge_text_color_base6", "step_badge_text_color_basen",
                    "step_badge_offset_x", "step_badge_offset_y",
                    "step_badge_font_family", "step_badge_font_bold",
                    "step_badge_font_smoothing_enabled", "step_badge_font_smoothing",
                    "step_badge_border_smoothing",
                )
            }
        return {
            "step_badge_width": self.step_badge_width_field.value(),
            "step_badge_height": self.step_badge_height_field.value(),
            "step_badge_border_enabled": self.step_badge_border_field.sidesEnabledValue(),
            "step_badge_border": self.step_badge_border_field.sidesValue(),
            "step_badge_border_thickness": self.step_badge_border_thickness_field.value(),
            "step_badge_border_smoothing": self.step_badge_border_smoothing_field.isChecked(),
            "step_badge_radius": self.step_badge_radius_field.cornersValue(),
            "step_badge_radius_linked": self.step_badge_radius_field.isLinked(),
            "step_badge_color_base2": self.step_badge_color_base2_field.value(),
            "step_badge_color_base3": self.step_badge_color_base3_field.value(),
            "step_badge_color_base4": self.step_badge_color_base4_field.value(),
            "step_badge_color_base5": self.step_badge_color_base5_field.value(),
            "step_badge_color_base6": self.step_badge_color_base6_field.value(),
            "step_badge_color_basen": self.step_badge_color_basen_field.value(),
            "step_badge_text_color_base2": self.step_badge_text_color_base2_field.value(),
            "step_badge_text_color_base3": self.step_badge_text_color_base3_field.value(),
            "step_badge_text_color_base4": self.step_badge_text_color_base4_field.value(),
            "step_badge_text_color_base5": self.step_badge_text_color_base5_field.value(),
            "step_badge_text_color_base6": self.step_badge_text_color_base6_field.value(),
            "step_badge_text_color_basen": self.step_badge_text_color_basen_field.value(),
            "step_badge_offset_x": self.step_badge_offset_x_field.value(),
            "step_badge_offset_y": self.step_badge_offset_y_field.value(),
            "step_badge_font_family": (
                "" if self.step_badge_font_family_field.value() == "Systeme"
                else self.step_badge_font_family_field.value()),
            "step_badge_font_bold": self.step_badge_font_bold_field.isChecked(),
            "step_badge_font_smoothing_enabled": self.step_badge_font_smoothing_field.isChecked(),
            "step_badge_font_smoothing": self.step_badge_font_smoothing_field.smoothingValue(),
        }

    def _column_override_values(self) -> dict:
        """Les 6 cles de surcharge par titre de colonne (Colonnes > Type/
        Projets/Sous-projets, voir _build_column_override_page) — lues
        depuis les CHAMPS live pour chaque titre DEJA construit (visite au
        moins une fois cette session), sinon REPRISES telles quelles depuis
        self.settings — un titre A LA FOIS, PAS un repli global tout-ou-
        rien (voir la remarque de l'utilisateur, "le tab colonnes avec
        tous les overrides ne sont pas sauvegardes dans les presets") :
        des qu'UN SEUL des 3 titres (Type/Projets/Sous-projet) a ete visite
        dans cette session, l'ancien repli global (base sur `not self.
        _type_toggles`) desactivait cette protection pour TOUS les titres a
        la fois — les titres PAS ENCORE visites se retrouvaient alors
        rapportes avec des dicts VIDES (`_type_fields.get(title, {})`),
        EFFACANT silencieusement leurs surcharges deja enregistrees des le
        prochain Enregistrer/preset.

        Necessaire depuis que l'onglet Colonnes est construit PARESSEUSEMENT
        (voir _on_main_tab_changed, la remarque de l'utilisateur sur la
        lenteur a l'ouverture) : _current_values() est appelee au moins une
        fois AVANT toute visite possible de cet onglet (_preview_now() en
        fin de __init__)."""
        type_built = "Type" in getattr(self, "_type_fields", {})
        if type_built:
            column_type_override_enabled = {
                key: toggle.isChecked() for key, toggle in self._type_toggles["Type"].items()
            }
            column_type_overrides = {
                key: _read_override_field_raw(key, field) for key, field in self._type_fields["Type"].items()
            }
            column_type_override_linked = {
                key: self._type_fields["Type"][key].isLinked()
                for key in _TYPE_LINKED_KEYS if key in self._type_fields["Type"]
            }
        else:
            column_type_override_enabled = self.settings.get("column_type_override_enabled", {})
            column_type_overrides = self.settings.get("column_type_overrides", {})
            column_type_override_linked = self.settings.get("column_type_override_linked", {})

        enabled_by_title = dict(self.settings.get("column_override_enabled_by_title") or {})
        overrides_by_title = dict(self.settings.get("column_overrides_by_title") or {})
        linked_by_title = dict(self.settings.get("column_override_linked_by_title") or {})
        # PREVIEW_STACK_TITLE ("Focus") AJOUTE ici (bug latent corrige au
        # passage, jamais capture jusqu'ici malgre son propre onglet de
        # surcharge deja existant) — ainsi que "Logiciels"/"IN"/"OVER"/
        # "OUT"/INSPECTOR_TITLE (voir la remarque de l'utilisateur, "ajoute
        # la colonne logiciels dans les settings, ainsi que in over et
        # out, puis la colonne inspecteur") : MEME mecanisme "column_
        # overrides_by_title" que Projets/Sous-projet, meme garde PAR TITRE
        # (visite ou non cette session) pour ne jamais ecraser silencieusement
        # les autres.
        for title in (
            "Projets", "Sous-projet", PREVIEW_STACK_TITLE,
            "Logiciels", "IN", "OVER", "OUT", INSPECTOR_TITLE,
        ):
            if title in getattr(self, "_type_fields", {}):
                enabled_by_title[title] = {
                    key: toggle.isChecked() for key, toggle in self._type_toggles[title].items()
                }
                overrides_by_title[title] = {
                    key: _read_override_field_raw(key, field) for key, field in self._type_fields[title].items()
                }
                linked_by_title[title] = {
                    key: self._type_fields[title][key].isLinked()
                    for key in _TYPE_LINKED_KEYS if key in self._type_fields[title]
                }
        return {
            "column_type_override_enabled": column_type_override_enabled,
            "column_type_overrides": column_type_overrides,
            "column_type_override_linked": column_type_override_linked,
            "column_override_enabled_by_title": enabled_by_title,
            "column_overrides_by_title": overrides_by_title,
            "column_override_linked_by_title": linked_by_title,
        }

    def _selection_clone_values(self) -> dict:
        """Les 4x3 cles d'override des etats "clones" de Focus (Non focus/
        Survol/Non selectionne, voir _build_selection_clone_subsection) —
        ces champs sont EAGER (onglet General, jamais paresseux), pas
        besoin du repli hasattr utilise par _step_badge_values/
        _column_override_values."""
        out = {}
        for state in ("unfocus", "hover", "idle"):
            padding_field = getattr(self, f"item_selection_{state}_padding_field")
            border_field = getattr(self, f"item_selection_{state}_border_field")
            radius_field = getattr(self, f"item_selection_{state}_radius_field")
            edge_field = getattr(self, f"item_selection_{state}_edge_border_field")
            out.update({
                f"item_selection_{state}_padding_override":
                    getattr(self, f"item_selection_{state}_padding_toggle").isChecked(),
                f"item_selection_{state}_padding_linked": padding_field.isLinked(),
                f"item_selection_{state}_padding": padding_field.sidesValue(),
                f"item_selection_{state}_border_override":
                    getattr(self, f"item_selection_{state}_border_toggle").isChecked(),
                f"item_selection_{state}_border_enabled": border_field.sidesEnabledValue(),
                f"item_selection_{state}_border": border_field.sidesValue(),
                f"item_selection_{state}_radius_override":
                    getattr(self, f"item_selection_{state}_radius_toggle").isChecked(),
                f"item_selection_{state}_radius": radius_field.cornersValue(),
                f"item_selection_{state}_radius_linked": radius_field.isLinked(),
                f"item_selection_{state}_edge_border_override":
                    getattr(self, f"item_selection_{state}_edge_border_toggle").isChecked(),
                f"item_selection_{state}_edge_border": edge_field.isChecked(),
            })
        return out

    def _current_values(self) -> dict:
        if self._light:
            # Seuls les champs Application existent : le reste est repris tel
            # quel (et _on_save n'ecrit que ce qui a change).
            out = dict(self.settings)
            out.update(self._application_values())
            return out
        colors = dict(self.settings["colors"])
        colors.update(self.color_grid.value())
        geo = self.geo_table.value()
        out = dict(self.settings)
        out.update(self._current_title_level_values())
        out.update(self._application_values())
        out.update({
            "colors": colors,
            "header_visible": self.header_visible_field.isChecked(),
            "header_height": self.header_height_field.value(),
            "header_padding": self.header_padding_field.value(),
            "header_color": self.header_color_field.value(),
            "header_radius": self.header_radius_field.cornersValue(),
            "header_radius_linked": self.header_radius_field.isLinked(),
            "header_border_enabled": self.header_border_field.sidesEnabledValue(),
            "header_border": self.header_border_field.sidesValue(),
            "header_border_thickness": self.header_border_thickness_field.value(),
            "header_icon_right_padding": self.header_icon_right_padding_field.value(),
            "header_font_family": (
                "" if self.header_font_family_field.value() == "Systeme"
                else self.header_font_family_field.value()),
            "header_font_bold": self.header_font_bold_field.isChecked(),
            "header_font_italic": self.header_font_italic_field.isChecked(),
            "header_font_color": self.header_font_color_field.value(),
            "header_font_size": self.header_font_size_field.value(),
            "header_font_antialias_override_enabled": self.header_font_smoothing_field.isChecked(),
            "header_font_antialias_override": self.header_font_smoothing_field.smoothingValue(),
            "item_column_width": self.item_column_width_field.value(),
            "column_gap": self.column_gap_field.value(),
            "column_padding_linked": self.column_padding_field.isLinked(),
            "column_padding": self.column_padding_field.sidesValue(),
            "column_border_enabled": self.column_border_field.sidesEnabledValue(),
            "column_border": self.column_border_field.sidesValue(),
            "column_border_thickness": self.column_border_thickness_field.value(),
            "column_border_radius": self.column_border_radius_field.cornersValue(),
            "column_border_radius_linked": self.column_border_radius_field.isLinked(),
            "column_bg_color": self.column_bg_color_field.value(),
            "resize_badge_position": self.resize_badge_position_field.position(),
            "resize_badge_offset_x": self.resize_badge_position_field.offsetX(),
            "resize_badge_offset_y": self.resize_badge_position_field.offsetY(),
            "resize_badge_font_family": (
                "" if self.resize_badge_font_field.value() == "Systeme" else self.resize_badge_font_field.value()),
            "resize_badge_font_bold": self.resize_badge_font_bold_field.isChecked(),
            "resize_badge_font_italic": self.resize_badge_font_italic_field.isChecked(),
            "resize_badge_font_size": self.resize_badge_font_size_field.value(),
            "resize_badge_font_smoothing_enabled": self.resize_badge_font_smoothing_field.isChecked(),
            "resize_badge_font_smoothing": self.resize_badge_font_smoothing_field.smoothingValue(),
            "resize_badge_text_color": self.resize_badge_text_color_field.value(),
            "resize_badge_bg_color": self.resize_badge_bg_color_field.value(),
            "resize_badge_border_enabled": self.resize_badge_border_field.sidesEnabledValue(),
            "resize_badge_border": self.resize_badge_border_field.sidesValue(),
            "resize_badge_border_thickness": self.resize_badge_border_thickness_field.value(),
            "resize_badge_border_radius": self.resize_badge_border_radius_field.cornersValue(),
            "resize_badge_border_radius_linked": self.resize_badge_border_radius_field.isLinked(),
            "item_font_family": "" if self.item_font_field.value() == "Systeme" else self.item_font_field.value(),
            "item_font_size": self.item_font_size_field.value(),
            "item_font_bold": self.item_font_bold_field.isChecked(),
            "item_font_italic": self.item_font_italic_field.isChecked(),
            "item_antialias_override_enabled": self.item_antialias_field.isChecked(),
            "item_antialias_override": self.item_antialias_field.smoothingValue(),
            "item_header_gap": self.item_header_gap_field.value(),
            **{
                spec.key: spec.raw_value(getattr(self, _ITEM_TEXT_FIELD_ATTR[spec.key]))
                for spec in _ITEM_TEXT_FIELD_SPECS
            },
            "item_row_border_enabled": self.item_row_border_field.enabledValue(),
            "item_row_border_color": self.item_row_border_field.colorValue(),
            "item_row_border_thickness": self.item_row_border_field.thicknessValue(),
            "item_image_padding_linked": self.item_image_padding_field.isLinked(),
            "item_image_padding": self.item_image_padding_field.sidesValue(),
            "item_image_border_enabled": self.item_image_border_field.sidesEnabledValue(),
            "item_image_border": self.item_image_border_field.sidesValue(),
            "item_image_border_thickness": self.item_image_border_thickness_field.value(),
            "item_image_radius": self.item_image_radius_field.cornersValue(),
            "item_image_radius_linked": self.item_image_radius_field.isLinked(),
            "item_image_ratio": self.item_image_ratio_field.value() / 100.0,
            # Colonnes > Apercu (voir _build_column_override_page,
            # PREVIEW_STACK_TITLE) — champs PLATS, propres a cette colonne,
            # pas de pendant "General" (voir la remarque de l'utilisateur,
            # "je veux une section image ... zone titre ... bouton
            # repliement").
            "preview_padding_linked": self.preview_padding_field.isLinked(),
            "preview_padding": self.preview_padding_field.sidesValue(),
            "preview_radius_linked": self.preview_radius_field.isLinked(),
            "preview_radius": self.preview_radius_field.cornersValue(),
            "preview_title_zone_height": self.preview_title_zone_height_field.value(),
            "preview_title_font_size": self.preview_title_font_size_field.value(),
            "preview_title_font_color": self.preview_title_font_color_field.value(),
            "preview_title_font_family": (
                "" if self.preview_title_font_family_field.value() == "Systeme"
                else self.preview_title_font_family_field.value()),
            "preview_title_font_bold": self.preview_title_font_bold_field.isChecked(),
            "preview_title_font_italic": self.preview_title_font_italic_field.isChecked(),
            "preview_title_font_smoothing_enabled": self.preview_title_font_smoothing_field.isChecked(),
            "preview_title_font_smoothing": self.preview_title_font_smoothing_field.smoothingValue(),
            "preview_title_padding_linked": self.preview_title_padding_field.isLinked(),
            "preview_title_padding": self.preview_title_padding_field.sidesValue(),
            "preview_status_font_size": self.preview_status_font_size_field.value(),
            "preview_status_font_color": self.preview_status_font_color_field.value(),
            "preview_status_font_color_idle": self.preview_status_font_color_idle_field.value(),
            "preview_status_font_family": (
                "" if self.preview_status_font_family_field.value() == "Systeme"
                else self.preview_status_font_family_field.value()),
            "preview_status_font_bold": self.preview_status_font_bold_field.isChecked(),
            "preview_status_font_italic": self.preview_status_font_italic_field.isChecked(),
            "preview_status_font_smoothing_enabled": self.preview_status_font_smoothing_field.isChecked(),
            "preview_status_font_smoothing": self.preview_status_font_smoothing_field.smoothingValue(),
            "preview_status_padding_linked": self.preview_status_padding_field.isLinked(),
            "preview_status_padding": self.preview_status_padding_field.sidesValue(),
            "preview_toggle_width": self.preview_toggle_width_field.value(),
            "preview_toggle_height": self.preview_toggle_height_field.value(),
            "preview_toggle_bg_color": self.preview_toggle_bg_field.value(),
            "preview_toggle_border_enabled": self.preview_toggle_border_field.sidesEnabledValue(),
            "preview_toggle_border": self.preview_toggle_border_field.sidesValue(),
            "preview_toggle_border_thickness": self.preview_toggle_border_thickness_field.value(),
            "preview_toggle_radius": self.preview_toggle_radius_field.value(),
            "preview_toggle_x": self.preview_toggle_x_field.value(),
            "preview_toggle_y": self.preview_toggle_y_field.value(),
            "collapse_toggle_mode": (
                "icone" if self.collapse_toggle_mode_field.value() == "Icone" else "chevrons"),
            "shortcut_font_family": (
                "" if self.shortcut_font_family_field.value() == "Systeme"
                else self.shortcut_font_family_field.value()),
            "shortcut_font_bold": self.shortcut_font_bold_field.isChecked(),
            "shortcut_font_italic": self.shortcut_font_italic_field.isChecked(),
            "shortcut_color": self.shortcut_color_field.value(),
            "shortcut_font_size": self.shortcut_font_size_field.value(),
            "shortcut_font_smoothing_enabled": self.shortcut_font_smoothing_field.isChecked(),
            "shortcut_font_smoothing": self.shortcut_font_smoothing_field.smoothingValue(),
            "item_selection_focus_color": self.item_selection_focus_field.value(),
            "item_selection_unfocus_color": self.item_selection_unfocus_field.value(),
            "item_hover_color": self.item_hover_field.value(),
            "item_idle_color": self.item_idle_field.value(),
            "item_selection_padding_linked": self.item_selection_padding_field.isLinked(),
            "item_selection_padding": self.item_selection_padding_field.sidesValue(),
            "item_selection_border_enabled": self.item_selection_border_field.sidesEnabledValue(),
            "item_selection_border": self.item_selection_border_field.sidesValue(),
            "item_selection_radius": self.item_selection_radius_field.cornersValue(),
            "item_selection_radius_linked": self.item_selection_radius_field.isLinked(),
            "item_selection_edge_border": self.item_selection_edge_border_field.isChecked(),
            **self._selection_clone_values(),
            # Colonnes > Type/Projets/Sous-projets (voir _column_override_
            # values, PAS lu directement ici : l'onglet Colonnes est
            # desormais construit PARESSEUSEMENT, voir _on_main_tab_changed
            # — self._type_toggles/_type_fields peuvent encore ne pas
            # exister au tout premier appel de cette methode).
            **self._column_override_values(),
            **self._step_badge_values(),
            "columns_resizable": self.columns_resizable_toggle.isChecked(),
            "table_border_enabled": self.table_border_field.sidesEnabledValue(),
            "table_border": self.table_border_field.sidesValue(),
            "table_border_thickness": self.table_border_thickness_field.value(),
            **{f"table_inner_{axis}_{key}": val
               for axis, field in (("h", self.table_inner_h_field), ("v", self.table_inner_v_field))
               for key, val in zip(("enabled", "color", "thickness"), field.value())},
            "table_radius": self.table_radius_field.value(),
            "table_cell_padding_linked": self.cell_padding_field.isLinked(),
            "table_cell_padding": self.cell_padding_field.sidesValue(),
            "table_head_color": self.table_head_color_field.value(),
            "geo_table_columns": self.geo_table.head.columnWidths(),
            "font_table_columns": self.font_table.head.columnWidths(),
            "table_dims": self._collect_table_dims(),
            "toggle_style": self.toggle_style_field.value(),
            **self._toggle_shape_values("toggle1"),
            **self._toggle_shape_values("toggle2"),
            "slider_thumb_width": self.slider_thumb_width_field.value(),
            "slider_thumb_height": self.slider_thumb_height_field.value(),
            "slider_thumb_color": self.slider_thumb_color_field.value(),
            "slider_thumb_border": self.slider_thumb_border_field.sidesValue(),
            "slider_thumb_border_enabled": self.slider_thumb_border_field.sidesEnabledValue(),
            "slider_thumb_radius": self.slider_thumb_radius_field.cornersValue(),
            "slider_thumb_radius_linked": self.slider_thumb_radius_field.isLinked(),
            "slider_track_height": self.slider_track_height_field.value(),
            "slider_track_fill_color": self.slider_track_fill_field.value(),
            "slider_track_empty_color": self.slider_track_empty_field.value(),
            "slider_track_border": self.slider_track_border_field.sidesValue(),
            "slider_track_border_enabled": self.slider_track_border_field.sidesEnabledValue(),
            "slider_track_radius": self.slider_track_radius_field.cornersValue(),
            "slider_track_radius_linked": self.slider_track_radius_field.isLinked(),
            "custom_softwares": list(self._custom_softwares),
            "removed_softwares": sorted(self._removed_softwares),
            **geo,
        })
        for key, conf in self.font_table.value().items():
            merged = dict(self.settings[key])
            merged.update(conf)
            out[key] = merged
        return out

    def _mark_dirty(self, *_args):
        self._dirty = True
        self.titlebar.set_dirty(True)
        self._sync_preset_box()
        self._live_pending = True
        if not self._live_timer.isActive():
            self._live_timer.start()

    def _flush_live_apply(self):
        if not self._live_pending:
            return
        self._live_pending = False
        self._preview_now()

    def _preview_now(self):
        self.settingsChanged.emit(self._current_values())

    def _on_apply(self):
        """Commit immediat des valeurs courantes sans toucher au disque
        (tout est deja previsualise en direct via _mark_dirty/_preview_now,
        y compris la racine — ce bouton force juste un rafraichissement
        immediat sans attendre le debounce de 30ms)."""
        self._preview_now()

    def _on_save(self):
        values = self._current_values()
        if self._mode == "tout":
            self.settings = values
        else:
            # Deux fenetres peuvent etre ouvertes : on ne reporte sur le
            # disque que ce que CETTE fenetre a modifie, sans ecraser les
            # reglages enregistres entre-temps par l'autre.
            self.settings = load_settings()
            self.settings.update({k: v for k, v in values.items() if v != self._original_settings.get(k)})
        save_settings(self.settings)
        # Met AUSSI a jour le preset ACTIF sur le disque, s'il y en a un
        # (voir _save_current_preset, MEME logique) : sans ca, ce bouton
        # (le bouton PRINCIPAL "Enregistrer" de la fenetre) ne touchait
        # QUE pipeline_settings.json, jamais pipeline_settings.presets.json
        # — un changement fait ici semblait bien pris en compte sur le
        # moment (l'appli l'applique en direct), mais RECHARGER ce MEME
        # preset plus tard faisait silencieusement REVENIR l'ANCIENNE
        # valeur, jamais ecrite dans son fichier — voir la remarque de
        # l'utilisateur, "certains parametres ne s'enregistrent pas dans
        # les presets". Desormais peu importe LEQUEL des 2 boutons
        # "Enregistrer" est utilise (celui-ci ou le petit bouton a cote du
        # selecteur de preset, voir _save_current_preset), un preset ACTIF
        # est TOUJOURS mis a jour.
        if self._current_preset and self._current_preset != "Personnalise":
            presets = _load_presets()
            presets[self._current_preset] = self.settings
            _save_presets(presets)
        self._saved = True
        self._style_sig = self._style_signature(load_settings())
        self._dirty = False
        self.titlebar.set_dirty(False)
        self._sync_preset_box()
        self.settingsSaved.emit(self.settings)
        self.accept()

    # Reglages qui habillent la fenetre elle-meme (couleurs, sliders, toggles,
    # titres, arrondis, tableaux). Les controles qui les posent n'existent pas
    # tous dans chaque mode : si l'un d'eux change sur le disque entre deux
    # ouvertures, la fenetre cachee est perimee (voir is_stale).
    _STYLE_PREFIXES = ("colors", "slider_", "toggle", "title_level", "input_radius",
                       "button_radius", "window_radius", "table_", "font", "text_")

    @classmethod
    def _style_signature(cls, settings: dict) -> str:
        return json.dumps({k: v for k, v in settings.items() if k.startswith(cls._STYLE_PREFIXES)},
                          sort_keys=True, default=str)

    def is_stale(self) -> bool:
        """Vrai si l'habillage enregistre differe de celui avec lequel cette
        fenetre a ete construite : reopen() ne le rejouerait pas, il faut la
        reconstruire."""
        return self._style_signature(load_settings()) != self._style_sig

    def reopen(self):
        """Remet la fenetre, gardee cachee apres sa fermeture (voir
        PipelineBrowser._open_settings), dans l'etat d'une ouverture neuve :
        reglages relus sur le disque, rien de modifie. Evite de reconstruire
        ses milliers de widgets a chaque ouverture."""
        self.settings = load_settings()
        self._original_settings = json.loads(json.dumps(self.settings))
        _set_input_radius(int(self.settings.get("input_radius", 0)))
        _set_button_radius(int(self.settings.get("button_radius", 0)))
        self._saved = False
        self._apply_values_to_controls(self.settings)
        default_preset = self.settings.get("default_preset")
        self._current_preset = default_preset if default_preset in _load_presets() else "Personnalise"
        self._refresh_default_preset_options()
        # Les changements regroupes (couleurs, rayons...) que ces valeurs
        # viennent de declencher s'appliquent tout de suite : arrives apres,
        # ils marqueraient la fenetre comme modifiee.
        for name in ("_colors_changed_timer", "_dropdown_radius_timer",
                     "_button_radius_timer", "_column_type_preview_timer"):
            timer = getattr(self, name, None)
            if timer is not None and timer.isActive():
                timer.stop()
                timer.timeout.emit()
        # Les valeurs posees sont celles que l'appli applique deja : rien a
        # previsualiser, et la fenetre n'a rien de modifie.
        self._live_timer.stop()
        self._live_pending = False
        self._dirty = False
        self.titlebar.set_dirty(False)
        self._sync_preset_box()

    def reject(self):
        if not self._saved:
            self.settingsChanged.emit(self._original_settings)
            _set_input_radius(int(self._original_settings.get("input_radius", 0)))
            _set_button_radius(int(self._original_settings.get("button_radius", 0)))
        self._save_window_geometry()
        super().reject()

    def accept(self):
        self._save_window_geometry()
        super().accept()

    def _geometry_key(self) -> str:
        return "geometry_general" if self._mode == "general" else "geometry"

    def _save_window_geometry(self):
        _save_window_geometry(bytes(self.saveGeometry().toBase64()).decode("ascii"), self._geometry_key())

def main():
    from app_style import apply_style
    app = QApplication(sys.argv)
    apply_style(app)
    win = SettingsWindow()
    win.show()
    sys.exit(app.exec())

if __name__ == "__main__":
    main()
