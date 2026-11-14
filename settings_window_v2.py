"""Fenetre de reglages "v2" : maquette COMPARATIVE de la facon dont je
(Claude) construirais la fenetre de reglages des colonnes des le depart.

Ne remplace RIEN : SettingsWindow (settings_window.py) reste la fenetre
reelle. Celle-ci reutilise les memes widgets (curseurs, couleurs, bordures,
tableaux...) pour avoir le meme aspect, mais change la CONSTRUCTION :

1. Les reglages sont des DONNEES (CATALOG, plus bas) : cle, libelle, type de
   controle, bornes, defaut. Ajouter un reglage = ajouter une ligne.
2. Un seul constructeur par type de controle (make_field) et UN SEUL
   constructeur de tableau (build_group), parametre par la PORTEE : General
   (valeurs de base, sans toggle) ou une surcharge (Type, Projets, IN...,
   avec le toggle devant chaque ligne). Plus de copie du code par onglet.
3. Rien n'est construit avant d'etre vu : un onglet a sa premiere visite,
   un groupe (Colonnes / Entetes) a son premier depliage.

Couverture : sections Colonnes (Colonnes, Entetes, Texte, Image, Selection),
TITRE, Tableaux, Toggles et Sliders dans l'onglet General, plus les 8 onglets
de surcharge (Colonnes/Entetes/Texte/Image/Selection). Voir ROADMAP en bas
de la liste des noeuds pour ce qui reste a porter. Tout est branche : apercu
en direct, enregistrement (les onglets de surcharge ecrivent dans les
dictionnaires de surcharge, comme la v1). Audit controle par controle :
`python tests/_probe_v2_params.py`.
"""
from __future__ import annotations

import json
import os
import re
import time
from dataclasses import replace
from typing import Callable

from PySide6.QtCore import QByteArray, QEvent, QObject, QPoint, QRect, QSize, Qt, QTimer, Signal
from PySide6.QtGui import QFontMetrics, QIcon
import copy
from pathlib import Path
from PySide6.QtWidgets import (
    QApplication, QDialog, QGraphicsOpacityEffect, QFileDialog, QFrame, QHBoxLayout, QInputDialog, QLabel, QMenu,
    QMessageBox, QPushButton, QScrollArea, QStackedWidget, QVBoxLayout, QWidget,
)

import settings_cells
from settings_cells import (
    seed_above_text_look,
    _Cell, _ROWS_MOVABLE, SplitCell, _TextField, apply_saved_range, attach_range_menu, build_cells_table, natural_label_width,
    normalize_toggles, set_row_kinds, slider_fields, wrap_split, ROW_TEMPLATES_KEY,
)

from app_style import apply_dwm_frame, resize_hit_test
from settings_layout import (
    _padding_tuple, _ReorderOverlay, _reflow_ancestors,
    _Section, _SectionHeader, _SubSection, _TabStrip, _TABLE_HEAD, _ResizableTableHeader, _TableRow,
    set_tab_look,
    _make_accordion,
    _ancestors, _flat_tables, _reflow_all, logical_parent,
    _section_host, _seed_flat_tables_style, _set_flat_tables_style,
)
from settings_sections import (
    _CellPaddingField, _CompactAppOrCustomColorField, _CornerRadiusField, _CornerRadiusSliders, _InnerLineField,
    _ITEM_TEXT_FIELD_SPECS, _SidePaddingField, _ToggleSideColorsField, _font_choices,
)
from settings_store import (
    M, _coerce_corner_radius, _coerce_side_enabled, _load_window_geometry,
    _resolve_color_value, _ICONS_DIR, _save_window_geometry, import_toggle_image, toggle_style_list,
    update_active_preset, _subsection_left_margin, _title_indent, _sync_dynamic_M,
    _sync_slider_style, _sync_title_level_style, load_settings, save_settings,
)
from fm_theme.tokens import set_table_bg
from fm_theme.style import (BUTTON_FOLLOW_CHOICES, BUTTON_STATE_FOLLOW, BUTTON_STATE_ROWS, button_state_copy,
                            button_state_override, button_state_value)
from settings_theme import _qfont, _set_button_radius, _set_input_radius, _set_text_role, _text_label
from settings_widgets import (
    Menu, _Btn, _DualFontSelectField, _FontSelectField, _MiniSlider, _OverrideSmoothingField, _RatioSliderField,
    _ResizeBadgePositionField, _RowBorderField, _ShortcutField, _SliderField, _TableFrame, _Toggle,
    _ToggleStylePicker, _DIMMED_OPACITY, _SelectField, _set_dimmed, _set_faded, _toggle_icon_pixmap, _toggle_image_pixmap,
    _TABLE_DIMS, _TABLE_SELECTION, _TOGGLE_STYLE_NAMES, _set_table_dims, _set_table_inner_border,
    _set_table_shadow, shadow_look, _sync_toggle_style, TOGGLE_STYLE_LISTENERS, CONTEXT_MENU_EXTRAS,
    make_space_actions, set_space_above, set_space_below, space_target, widget_at_path, widget_path,
    toggle_animation_left_ms,
)
from settings_window import (_NoSqueezeScrollArea, _OmitListField, _PanelFrame, _SettingsTitleBar, _omit_file_values,
                             install_extra_window, seed_extra_window_look, shadow_margins)
from settings_lut import LUT_HELP_TEXT, LutTestImagesField
from settings_sections import _FONT_ROLES
from settings_v2_app import FontRoleField, LogicielsField, RootPathField, SemanticColorField, UiIconField, icon_table
from settings_v2_app import _button as _settings_button
from settings_catalog import _BORD, CATALOG, Node, Spec, _ctx_font, _gabarit_extra, _shadow_spec
# Reglages des modules : definis dans LEUR paquet (inscrits dans CATALOG a l'import).
from fm_video.settings import VIDEO_TAB, VIDEO_TREE
from fm_markdown.settings import MARKDOWN_TAB, MARKDOWN_TREE, MD_ALIGN, MD_MODES, MD_OPEN_MD
from fm_board.settings import BOARD_MENU_GROUPS, BOARD_TAB, BOARD_TREE, MRO_TAB, MRO_TREE
from fm_cad.settings import CAD_TAB, CAD_TREE
from fm_design.settings import DESIGN_TAB, DESIGN_TREE
from fm_tableur.settings import TABLEUR_TAB, TABLEUR_TREE
from fm_illustrator.settings import ILL_TAB, ILL_TREE
from fm_photoshop.settings import PS_TAB, PS_TREE
from fm_font.settings import TYPO_TAB, TYPO_TREE
from fm_pdf.settings import PDF_TAB, PDF_TREE
from fm_agenda.settings import AGENDA_TAB, AGENDA_TREE
from fm_taches.settings import TACHES_TAB, TACHES_TREE
from fm_visionneuse.settings import VIEWER_TAB, VIEWER_TREE
from app_style import SEMANTIC_COLOR_SLOTS


# ==========================================================================
# 1. Le catalogue : les reglages decrits comme des donnees
# ==========================================================================


def _selection_specs(prefix: str, color_key: str, color_default, app_color: bool, title: str) -> list[Spec]:
    """5 lignes d'un etat de selection. `prefix` = "item_selection" (Focus) ou
    "item_selection_<etat>" : les cles *_override des etats sont gouvernees
    par le meme champ que la cle principale."""
    state = prefix != "item_selection"
    ov = (lambda k: (f"{k}_override",)) if state else (lambda k: ())
    # General : les etats clones ont un interrupteur d'override par ligne (cle `<..>_override`).
    gt = (lambda k: f"{k}_override") if state else (lambda k: None)
    return [
        Spec(color_key, "Couleur", "color_app" if app_color else "color", color_default, {"title": title}),
        Spec(f"{prefix}_padding", "Padding du selecteur", "padding", {}, {"linked_default": False},
             extra_keys=ov(f"{prefix}_padding"),
             general_toggle=gt(f"{prefix}_padding")),
        Spec(f"{prefix}_border_enabled", "Bordures du selecteur", "sides", False,
             {"colors_key": f"{prefix}_border"},
             extra_keys=(f"{prefix}_border", *ov(f"{prefix}_border")), general_toggle=gt(f"{prefix}_border")),
        Spec(f"{prefix}_radius", "Border radius", "corners", 0, {"max": 20},
             extra_keys=ov(f"{prefix}_radius"), general_toggle=gt(f"{prefix}_radius")),
        Spec(f"{prefix}_edge_border", "Bordure au bord de la colonne", "bool", True,
             extra_keys=ov(f"{prefix}_edge_border"), general_toggle=gt(f"{prefix}_edge_border")),
    ]


# Selection = 4 etats, chacun un tableau (sous-sections de niveau 3).
SELECTION_STATES: list[tuple[str, str]] = [
    ("Selection : Focus", "Focus"), ("Selection : Non focus", "Non focus"),
    ("Selection : Survol", "Survol"), ("Selection : Non selectionne", "Non selectionne"),
]
CATALOG["Selection : Focus"] = _selection_specs(
    "item_selection", "item_selection_focus_color", "#3f6f9f", False, "Selection (focus)")
CATALOG["Selection : Non focus"] = _selection_specs(
    "item_selection_unfocus", "item_selection_unfocus_color", "#2e3338", False, "Non focus")
CATALOG["Selection : Survol"] = _selection_specs(
    "item_selection_hover", "item_hover_color", "#232729", False, "Survol")
CATALOG["Selection : Non selectionne"] = _selection_specs(
    "item_selection_idle", "item_idle_color", "@itemIdle", True, "Non selectionne")

# -- General > Colonnes : la section telle que l'ancienne fenetre la construit --


CATALOG["G Colonnes"] = [
    Spec("item_column_width", "Largeur par defaut", "slider", 180, {"min": 120, "max": 640, "width": 280}),
    Spec("column_gap", "Distance entre colonnes", "slider", 0, {"min": 0, "max": 40, "width": 280}),
    Spec("column_padding", "Padding", "padding", {}),
    Spec("column_bg_color", "Couleur de fond", "color_app", "@skinN2", {"title": "Fond de colonne"}),
    Spec("column_border_enabled", "Bordure", "sides_thick", True, _BORD("column_border"),
         extra_keys=("column_border", "column_border_thickness")),
    Spec("column_border_radius", "Border radius", "corners", 0, {"max": 20}),
    Spec("folder_reorder_enabled", "Permettre le replacement des dossiers", "bool", True),
]
CATALOG["G Encart"] = [
    Spec("resize_badge_position", "Position", "badge_position", "bottom_right",
         extra_keys=("resize_badge_offset_x", "resize_badge_offset_y")),
    Spec("resize_badge_font_family", "Police", "font_gabarit", "",
         {"prefix": "resize_badge", "keys": {"color": "resize_badge_text_color"}, "size": (6, 24),
          "size_default": 11, "color_default": "#d6d9dc",
          "color_title": "Texte du cadre de redimensionnement"},
         extra_keys=("resize_badge_font_bold", "resize_badge_font_italic", "resize_badge_font_size",
                     "resize_badge_font_smoothing_enabled", "resize_badge_font_smoothing",
                     "resize_badge_text_color")),
    Spec("resize_badge_bg_color", "Couleur de fond", "color_app", "#202326",
         {"title": "Fond du cadre de redimensionnement"}),
    Spec("resize_badge_border_enabled", "Bordure", "sides_thick", True, _BORD("resize_badge_border"),
         extra_keys=("resize_badge_border", "resize_badge_border_thickness")),
    Spec("resize_badge_border_radius", "Border radius", "corners", 4, {"max": 20}),
]
CATALOG["G Entetes"] = [
    Spec("header_visible", "Afficher", "bool", True),
    Spec("header_height", "Hauteur des entetes", "slider", 26, {"min": 16, "max": 56, "width": 280}),
    Spec("header_padding", "Padding des entetes", "slider", 0, {"min": 0, "max": 32, "width": 280}),
    Spec("header_color", "Couleur des entetes", "header_color", "skinN1"),
    Spec("header_radius", "Border radius", "corners", 0, {"max": 16}),
    Spec("header_border_enabled", "Bordure", "sides_thick", False, _BORD("header_border"),
         extra_keys=("header_border", "header_border_thickness")),
    Spec("header_icon_right_padding", "Padding droit des icones", "slider", 0,
         {"min": 0, "max": 40, "width": 280}),
    Spec("header_font_family", "Police / gras / couleur / hauteur du titre", "font_gabarit", "",
         {"prefix": "header", "family_width": 130, "size": (6, 24), "color_default": "#9aa1a7",
          "color_title": "Couleur du titre",
          "keys": {"smoothing_enabled": "header_font_antialias_override_enabled",
                   "smoothing": "header_font_antialias_override"}},
         extra_keys=("header_font_bold", "header_font_italic", "header_font_size", "header_font_color",
                     "header_font_antialias_override_enabled", "header_font_antialias_override")),
]
CATALOG["G Lignes"] = [
    Spec("item_row_height", "Hauteur de ligne", "slider", 25, {"min": 14, "max": 80}),
    Spec("item_row_spacing", "Espacement entre les lignes", "slider", 1, {"min": 0, "max": 20}),
    Spec("item_header_gap", "Espace avant le premier item", "slider", 0, {"min": 0, "max": 40}),
    Spec("item_row_bg_color", "Couleur de fond", "color_app", "@skinN2", {"title": "Fond des lignes"}),
    Spec("item_row_border_enabled", "Bordure entre les lignes", "row_border", False,
         extra_keys=("item_row_border_color", "item_row_border_thickness")),
]
CATALOG["G Texte"] = [
    Spec("item_font_family", "Police", "font_gabarit", "",
         {"prefix": "item", "toggle_style": "toggle1", "size": (6, 24), "size_default": 10, "size_width": 140,
          "bold_default": False, "color_default": "#d6d9dc", "color_title": "Couleur",
          "keys": {"color": "item_color", "smoothing_enabled": "item_antialias_override_enabled",
                   "smoothing": "item_antialias_override"}},
         extra_keys=("item_font_bold", "item_font_italic", "item_font_size", "item_color",
                     "item_antialias_override_enabled", "item_antialias_override")),
    Spec("item_text_padding", "Padding gauche", "slider", 8, {"min": 0, "max": 32}),
    # Extension des fichiers dans sa propre couleur (demande de l'utilisateur).
    Spec("item_ext_color_enabled", "Couleur des extensions", "bg_fill", False,
         {"color_key": "item_ext_color", "color_default": "#8a9097", "title": "Couleur des extensions"},
         extra_keys=("item_ext_color",)),
]
CATALOG["G Icone"] = [
    Spec("item_icon_size", "Taille de l'icone par defaut (0 = hauteur de la ligne)", "slider", 0,
         {"min": 0, "max": 128}),
    Spec("item_icon_padding_left", "Padding gauche", "slider", 0, {"min": 0, "max": 64}),
]
CATALOG["G Apercu"] = [
    Spec("item_image_padding", "Padding", "padding", {}),
    Spec("item_image_border_enabled", "Bordure", "sides_thick", False, _BORD("item_image_border"),
         extra_keys=("item_image_border", "item_image_border_thickness")),
    _shadow_spec("item_image_shadow"),
    Spec("item_image_radius", "Border radius", "corners", 0, {"max": 20}),
    Spec("item_image_ratio", "Ratio (largeur/hauteur)", "ratio_slider", 1.0),
]


# -- TITRE : 5 niveaux de titre (police composite, espacements, fond du paragraphe) --
# Plus de Titre > Retraits en v2 : le padding/margin du fond du parent place les titres (les cles
# title_level<N>_indent restent pour la v1).
def _title_specs() -> list[Spec]:
    fonts = []
    for n in range(1, 6):
        pre = f"title_level{n}"
        fonts.append(Spec(
            f"{pre}_font_family", f"Police titre niveau {n}", "font_gabarit", "",
            {"prefix": pre, "toggle_style": "toggle2", "size": (6, 32), "color_default": "#d6d9dc",
             "color_title": f"Couleur titre niveau {n}", "smoothing_title": False},
            extra_keys=tuple(f"{pre}_font_{k}" for k in
                             ("bold", "italic", "size", "smoothing_enabled", "smoothing", "color"))))
    return fonts


CATALOG["Titre : Polices"] = _title_specs()


def _title_bg_specs(n: int) -> list[Spec]:
    """Titre > Fond > Niveau n : fond du paragraphe (le titre et tout son contenu jusqu'au titre suivant)."""
    pre = f"title_level{n}_bg"
    return [
        Spec(f"{pre}_enabled", "Couleur de fond", "bg_fill", False,
             {"color_key": f"{pre}_color", "color_default": "@skinN2", "title": f"Fond titre niveau {n}"},
             extra_keys=(f"{pre}_color",)),
        Spec(f"{pre}_margin", "Margin", "padding", {}),
        Spec(f"{pre}_padding", "Padding", "padding", {}),
        # Padding (titre) : ligne du titre seule (lier les 4 | G | H | B | D) + espacement avant le 1er /
        # apres le dernier titre d'une pile de ce niveau (ex-sous-section « Padding (titre seulement) »).
        Spec(f"title_level{n}_text_padding", "Padding (titre)", "title_padding", {},
             {"linked_default": False, "before_key": f"title_level{n}_space_before",
              "after_key": f"title_level{n}_space_after", "max": 60},
             extra_keys=(f"title_level{n}_space_before", f"title_level{n}_space_after")),
        # Padding (paragraphe) : autour de tout ce que contient le titre (tableaux, sous-titres).
        Spec(f"title_level{n}_body_padding", "Padding (paragraphe)", "padding", {}),
        Spec(f"{pre}_border_enabled", "Bordures", "sides_thick", False,
             {"colors_key": f"{pre}_border", "thickness_key": f"{pre}_border_thickness", "width": 90, "box": 54},
             extra_keys=(f"{pre}_border", f"{pre}_border_thickness")),
        Spec(f"{pre}_radius", "Border radius", "corners", 0, {"max": 30}),
        # Titre DEPLOYE (demande de l'utilisateur, 2026-11-08) : fond de son paragraphe (transparent = le fond
        # habituel ; editeur fm_theme : aussi le volet des parametres, theme_side_detail), texte impose.
        Spec(f"title_level{n}_open_bg_color", "Déployé : couleur de fond", "color_app", "#00000000",
             {"title": f"Fond titre déployé niveau {n}"}),
        Spec(f"title_level{n}_open_color_enabled", "Déployé : override couleur de texte", "bg_fill", False,
             {"color_key": f"title_level{n}_open_color", "color_default": "#ffffff",
              "title": f"Texte titre déployé niveau {n}"}, extra_keys=(f"title_level{n}_open_color",)),
        # Aucun cote allume : les bordures habituelles du titre ; editeur fm_theme : aussi le contour du volet.
        Spec(f"title_level{n}_open_border_enabled", "Déployé : bordures", "sides_thick", False,
             {"colors_key": f"title_level{n}_open_border", "thickness_key": f"title_level{n}_open_border_thickness",
              "width": 90, "box": 54},
             extra_keys=(f"title_level{n}_open_border", f"title_level{n}_open_border_thickness")),
        Spec(f"title_level{n}_open_bold", "Déployé : override gras", "choice", "follow",
             {"choices": _OPEN_STYLE_CHOICES, "width": 160}),
        Spec(f"title_level{n}_open_italic", "Déployé : override italique", "choice", "follow",
             {"choices": _OPEN_STYLE_CHOICES, "width": 160}),
    ]


# Override gras / italique d'un titre deploye : « follow » = la police du niveau (fm_theme.tokens._title_open_text).
_OPEN_STYLE_CHOICES = (("follow", "Suivre la police"), ("on", "Oui"), ("off", "Non"))

for _n in range(1, 6):
    CATALOG[f"Titre : Fond {_n}"] = _title_bg_specs(_n)

# -- Tableaux --
CATALOG["Tableaux"] = [
    Spec("columns_resizable", "Colonnes dimensionnables", "bool", True),
    # Fond des lignes de tous les tableaux (2026-11-08) : « @tableRow » = la pastille Couleurs > Fond de tableau.
    Spec("table_bg_color", "Couleur de fond", "color_app", "@tableRow", {"title": "Fond des tableaux"}),
    Spec("table_border_enabled", "Bordure", "sides_thick", True,
         {"colors_key": "table_border", "thickness_key": "table_border_thickness", "width": 140, "box": 58},
         extra_keys=("table_border", "table_border_thickness")),
    _shadow_spec("table_shadow"),
    Spec("table_inner_h_enabled", "Bordure intérieure H", "inner_line", True, {"axis": "h"},
         extra_keys=("table_inner_h_color", "table_inner_h_thickness")),
    Spec("table_inner_v_enabled", "Bordure intérieure V", "inner_line", True, {"axis": "v"},
         extra_keys=("table_inner_v_color", "table_inner_v_thickness")),
    Spec("table_radius", "Rayon des angles", "slider", 0, {"min": 0, "max": 16, "width": 140, "box": 58}),
    Spec("table_cell_padding", "Padding des cellules", "padding", {}),
    Spec("table_head_color", "Couleur d'en-tete", "header_color", "tableHead"),
    Spec("table_selection_color", "Couleur de sélection", "color", "#5f9bd0", {"title": "Couleur de sélection"}),
    Spec("table_rows_movable", "Permettre le déplacement des lignes", "bool", True),
    Spec("table_cell_head_color", "Couleur d'entête (cellules)", "header_color", "tableHead"),
]

# -- Toggles : un choix de style, puis Type, État OFF et État ON pour chaque style --
CATALOG["Toggles : Style"] = [Spec("toggle_style", "Style", "toggle_style", "toggle1")]


TOGGLE_STATES = (("off", "OFF"), ("on", "ON"))
# Tableaux d'un style : Type, puis UN tableau par etat (groupes « <style> : OFF » / « <style> : ON »), Fond et
# Coche cote a cote dans chaque ligne (cellule divisee, demande de l'utilisateur 2026-10-30).
TOGGLE_STATE_PARTS = tuple(label for _s, label in TOGGLE_STATES)


def _state_pair(label: str, fond: Spec | None, coche: Spec | None, **params) -> Spec:
    """Ligne « Fond | Coche » d'un tableau d'etat : chaque sous-cellule porte le champ de sa partie (vide si
    la partie n'a pas ce reglage). Lue / ecrite comme ses champs (kind `state_pair`)."""
    keys = tuple(k for sub in (fond, coche) if sub is not None for k in (sub.key, *sub.extra_keys))
    return Spec(keys[0], label, "state_pair", None, {"parts": (("Fond", fond), ("Coche", coche)), **params},
                extra_keys=keys[1:])


def _toggle_state_specs(prefix: str, state: str) -> list[Spec]:
    """Tableau d'un etat (Etat OFF / Etat ON, memes lignes) : Fond et Coche dans les deux sous-cellules."""
    from fm_theme.toggle_states import defaults
    pre = f"{prefix}_{state}"
    base = defaults(prefix)

    def size(part, field):
        key = f"{pre}_{part}_{field}"
        return Spec(key, {"width": "Largeur", "height": "Hauteur"}[field], "slider", base[key],
                    {"min": 1, "max": 80, "width": 110, "box": 54})

    def border(part):
        return Spec(f"{pre}_{part}_border_enabled", "Bordure", "sides_thick", True,
                    {"colors_key": f"{pre}_{part}_border", "thickness_key": f"{pre}_{part}_border_thickness",
                     "width": 90, "box": 54},
                    extra_keys=(f"{pre}_{part}_border", f"{pre}_{part}_border_thickness"))

    def radius(part):
        return Spec(f"{pre}_{part}_border_radius", "Border radius", "corners", 0, {"max": 20})

    def color(part):
        return Spec(f"{pre}_{part}_color", "Couleur de fond", "color", base[f"{pre}_{part}_color"],
                    {"title": f"{'Fond' if part == 'bg' else 'Coche'} ({state.upper()})"})

    skin = f"{pre}_coche_skin"
    text_pre = f"{pre}_coche_text"
    return [
        *(_state_pair(label, maker("bg"), maker("coche")) for label, maker in (
            ("Largeur", lambda part: size(part, "width")), ("Hauteur", lambda part: size(part, "height")),
            ("Bordure", border), ("Border radius", radius), ("Couleur de fond", color))),
        # Habillage (coche seulement) : un texte OU une icone, au milieu de la coche ; leurs lignes sont grisees sinon.
        _state_pair("Habillage", None, Spec(skin, "Habillage", "coche_skin", "none")),
        _state_pair("Texte", None, Spec(f"{pre}_coche_text", "Texte", "text", ""), active_when=(skin, "text")),
        _state_pair("Police", None, Spec(
            f"{text_pre}_font_family", "Police", "font_gabarit", "",
            {"prefix": text_pre, "size": (4, 32), "size_default": 10, "color_default": "#ffffff",
             "color_title": "Couleur du texte"},
            extra_keys=tuple(f"{text_pre}_font_{k}" for k in
                             ("bold", "italic", "size", "smoothing_enabled", "smoothing", "color"))),
            active_when=(skin, "text")),
        _state_pair("Icône", None, Spec(f"{pre}_coche_icon", "Icône", "toggle_image", "", {"style": prefix}),
                    active_when=(skin, "icon")),
    ]


def _toggle_specs(prefix: str) -> tuple[list[Spec], ...]:
    """Tableaux d'un style : (Type, Etat OFF, Etat ON)."""
    small = {"width": 90, "box": 54}
    # Type : peint par Qt (fond + coche) ou images importees (ON / OFF + sequence entre les deux).
    kind = [
        Spec(f"{prefix}_kind", "Type", "toggle_kind", "qt"),
        Spec(f"{prefix}_motion", "Mouvement de la coche", "toggle_motion",
             "fade" if prefix == "toggle2" else "slide"),
        Spec(f"{prefix}_icon_on", "Icônes", "toggle_icons", "", {"style": prefix, "off_key": f"{prefix}_icon_off",
                                                                  "active_when": (f"{prefix}_kind", "icons")},
             extra_keys=(f"{prefix}_icon_off",)),
        Spec(f"{prefix}_icon_frames", "Animation (images entre off et on)", "image_sequence", [],
             {"style": prefix, "active_when": (f"{prefix}_kind", "icons")}),
        Spec(f"{prefix}_anim_ms", "Durée de l'animation (ms)", "slider", 140, {"min": 0, "max": 2000, **small}),
    ]
    return (kind, *(_toggle_state_specs(prefix, state) for state, _label in TOGGLE_STATES))


def register_toggle_catalog(prefix: str):
    """Declare les tableaux d'un style de toggle (tous les styles ont les memes) : Type, Etat OFF, Etat ON."""
    kind, *parts = _toggle_specs(prefix)
    CATALOG[f"{prefix} : Type"] = kind
    for name, specs in zip(TOGGLE_STATE_PARTS, parts):
        CATALOG[f"{prefix} : {name}"] = specs


def unregister_toggle_catalog(prefix: str):
    for name in ("Type", *TOGGLE_STATE_PARTS, "OFF Fond", "OFF Coche", "ON Fond", "ON Coche", "Cadre", "Coche"):
        CATALOG.pop(f"{prefix} : {name}", None)


for _p in ("toggle1", "toggle2"):
    register_toggle_catalog(_p)

# -- Sliders : Selecteur (le curseur mobile) et Rail (la piste) --
CATALOG["Slider : Selecteur"] = [
    Spec("slider_thumb_width", "Largeur", "slider", 3, {"min": 1, "max": 20, "width": 110, "box": 54}),
    Spec("slider_thumb_height", "Hauteur", "slider", 14, {"min": 1, "max": 40, "width": 110, "box": 54}),
    Spec("slider_thumb_color", "Couleur", "color", "#8fb4d5", {"title": "Couleur du selecteur"}),
    Spec("slider_thumb_border_enabled", "Bordure", "sides", True, {"colors_key": "slider_thumb_border"},
         extra_keys=("slider_thumb_border",)),
    Spec("slider_thumb_radius", "Border radius", "corners", 0, {"max": 16}),
]
CATALOG["Slider : Rail"] = [
    Spec("slider_track_height", "Hauteur", "slider", 3, {"min": 1, "max": 20, "width": 110, "box": 54}),
    Spec("slider_track_fill_color", "Rail parcouru", "color", "#3f6f9f", {"title": "Rail parcouru"}),
    Spec("slider_track_empty_color", "Rail a parcourir", "color", "#25292d", {"title": "Rail a parcourir"}),
    Spec("slider_track_border_enabled", "Bordure", "sides", True, {"colors_key": "slider_track_border"},
         extra_keys=("slider_track_border",)),
    Spec("slider_track_radius", "Border radius", "corners", 0, {"max": 16}),
]


# ==========================================================================
# Sections reprises de la v1 (Application, Dossiers et fichiers a omettre, LUT, Polices principales,
# Couleurs, Geometrie, ICONES, RACCOURCI ; onglets Focus et Projets : Image, Zone titre, Bouton
# repliement, Icone de niveaux). Memes cles et memes bornes que la v1.
# ==========================================================================

CATALOG["Application"] = [
    Spec("root_path", "Racine par defaut", "root_path", r"F:\PIPELINE"),
    Spec("default_preset", "Preset par defaut", "preset", ""),
    Spec("ui_scale", "Scale interface", "slider", 100, {"min": 50, "max": 200, "unit": "%", "width": 280}),
    Spec("auto_collapse_set_columns", "Replier les colonnes de set une fois l'espace de travail atteint", "bool",
         True),
    Spec("window_radius", "Coins arrondis de la fenetre principale", "window_radius", 0),
]
CATALOG["Chargement et génération automatique"] = [
    spec for task, label in (("settings", "Paramètres de settings"), ("moodboard", "Moodboard (fichiers MKV uniquement)"),
                             ("video", "Aperçus fichiers vidéo"))
    for spec in (
        Spec(f"auto_{task}_enabled", label, "bool", task == "settings"),
        Spec(f"auto_{task}_when", "Déclenchement", "choice", "app", {"choices": (
            ("app", "Quand l'appli n'a plus le focus depuis"),
            ("computer", "Quand l'ordinateur est inactif depuis"))}),
        Spec(f"auto_{task}_delay", "Temps d'attente", "choice", 60, {"choices": (
            (0, "Immédiatement"), (10, "10 secondes"), (20, "20 secondes"),
            (30, "30 secondes"), (60, "1 minute"))}),
    )]


def _f_extension_list(spec, v, colors):
    field = _OmitListField(prompt=spec.params.get("prompt", "Extension :"))
    field.set_values(_normalized_extensions(v.seed(spec.key, spec.default)))
    field.setToolTip("Extensions des fichiers que le double-clic ouvre dans le module (.md toujours compris).")
    return field


def _normalized_extensions(values) -> list[str]:
    if isinstance(values, str):
        values = values.replace(",", " ").replace(";", " ").split()
    out = []
    for value in values or []:
        text = str(value).strip().lower().lstrip("*")
        if text:
            text = text if text.startswith(".") else "." + text
            if text not in out:
                out.append(text)
    if ".md" not in out:
        out.insert(0, ".md")
    return out


# -- Menu contextuel (settings_menu : tous les menus contextuels, lus a chaque ouverture) --
# Fenetres additionnelles (demande de l'utilisateur) : toutes les fenetres en plus de la principale.
CATALOG["Fenêtres additionnelles"] = [
    # Fond et bordures PROPRES (demande de l'utilisateur, 2026-11-08) : la « Bordure des fenêtres » de Thème > Général
    # ne vaut plus que pour la fenêtre principale. fm_theme.window.seed_extra_window_look.
    Spec("extra_window_bg_color", "Couleur de fond", "color_app", "@skinN1", {"title": "Fond des fenêtres additionnelles"}),
    Spec("extra_window_border_enabled", "Bordures", "sides_thick", True,
         {"colors_key": "extra_window_border", "thickness_key": "extra_window_border_thickness", "width": 90, "box": 54},
         extra_keys=("extra_window_border", "extra_window_border_thickness")),
    Spec("extra_window_radius", "Border radius", "corners", 0, {"max": 24}),
    _shadow_spec("extra_window_shadow"),
    # Barre de navigation des fenetres : dans Barre de navigation > Fenetres additionnelles (2026-11-05).
    Spec("extra_window_buttons_line_enabled", "Bordure interface / barre des boutons", "inner_line", True,
         {"prefix": "extra_window", "axis": "buttons_line"},
         extra_keys=("extra_window_buttons_line_color", "extra_window_buttons_line_thickness")),
]

# Tableaux > « Texte au dessus » : police des textes poses au-dessus d'une ligne (settings_cells).
CATALOG["Tableaux"].append(_ctx_font("table_above_text", "Texte au dessus", 11, "#8d949a"))

# Barre de navigation > Fenetres additionnelles : la barre du haut de toutes les fenetres en plus de la principale
# (avant : dans Fenetres additionnelles ; demande de l'utilisateur, 2026-11-05 : tout ce qui regle une barre de
# navigation dans la section Barre de navigation).
CATALOG["Barre de navigation : Fenetres additionnelles"] = [
    Spec("extra_window_title_height", "Hauteur barre", "slider", 32, {"min": 16, "max": 80}),
    Spec("extra_window_title_bg", "Couleur de fond", "color", "#101214",
         {"title": "Barre de navigation des fenêtres"}),
    _ctx_font("extra_window_title_text", "Texte", 11, "#8d949a"),
    Spec("extra_window_title_button_width", "Taille des boutons", "xy", 36,
         {"range": (12, 120), "defaults": (36, 32), "second_key": "extra_window_title_button_height",
          "captions": ("X", "Y")}, extra_keys=("extra_window_title_button_height",)),
    Spec("extra_window_title_button_radius", "Border radius des boutons", "corners", 0, {"max": 20}),
    Spec("extra_window_title_line_enabled", "Bordure barre / interface", "inner_line", True,
         {"prefix": "extra_window", "axis": "title_line"},
         extra_keys=("extra_window_title_line_color", "extra_window_title_line_thickness")),
]

CATALOG["Menu contextuel : Menu"] = [
    Spec("ctx_menu_editable", "Personnalisation (glisser, clic droit)", "bool", True),
    Spec("ctx_menu_bg", "Couleur de fond", "color", "#202326", {"title": "Fond des menus"}),
    Spec("ctx_menu_border_enabled", "Bordures", "sides_thick", True,
         {"colors_key": "ctx_menu_border", "thickness_key": "ctx_menu_border_thickness", "width": 90, "box": 54},
         extra_keys=("ctx_menu_border", "ctx_menu_border_thickness")),
    # Une couleur pour les 4 cotes (demande de l'utilisateur) : la changer la pose sur chaque cote de la
    # ligne Bordures (`params["sets_side_colors"]`), dont les couleurs par cote restent reglables ensuite.
    Spec("ctx_menu_border_color", "Couleur des bordures", "color", "#2c3034",
         {"title": "Couleur des bordures", "sets_side_colors": "ctx_menu_border_enabled"}),
    Spec("ctx_menu_border_radius", "Border radius", "corners", 0, {"max": 20}),
    _shadow_spec("ctx_menu_shadow"),
    Spec("ctx_menu_padding", "Padding", "padding", {}),
]
CATALOG["Menu contextuel : Lignes"] = [
    _ctx_font("ctx_menu", "Police", 11, "#d6d9dc"),
    Spec("ctx_menu_item_padding", "Padding des lignes", "padding", {}),
    Spec("ctx_menu_disabled_color", "Couleur du texte grisé", "color", "#7d858b", {"title": "Couleur du texte grisé"}),
    Spec("ctx_menu_ghost_color", "Couleur des options fantômes", "color", "#e0a040",
         {"title": "Options fantômes (Ctrl+Maj + clic droit)"}),
    Spec("ctx_menu_current_color", "Couleur de l'élément en cours", "color", "#4d5f9bd0",
         {"title": "Élément en cours (ex. couleur « app » choisie)"}),
    Spec("ctx_menu_icon_size", "Taille des icônes", "slider", 16, {"min": 8, "max": 40}),
    Spec("ctx_menu_control_gap", "Écart texte / contrôle", "slider", 16, {"min": 0, "max": 80}),
    Spec("ctx_menu_slider_width", "Largeur des curseurs", "slider", 140, {"min": 60, "max": 320}),
]
CATALOG["Menu contextuel : Survol"] = [
    Spec("ctx_menu_hover_color", "Couleur de fond", "color", "#3f6f9f", {"title": "Fond du survol"}),
    Spec("ctx_menu_hover_text_color", "Couleur du texte", "color", "#eef2f5", {"title": "Texte survolé"}),
    Spec("ctx_menu_hover_border_enabled", "Bordures", "sides_thick", False,
         {"colors_key": "ctx_menu_hover_border", "thickness_key": "ctx_menu_hover_border_thickness",
          "width": 90, "box": 54},
         extra_keys=("ctx_menu_hover_border", "ctx_menu_hover_border_thickness")),
    Spec("ctx_menu_hover_radius", "Border radius", "corners", 0, {"max": 16}),
    Spec("ctx_menu_hover_margin", "Marge", "padding", {}),
]
CATALOG["Menu contextuel : Libelles"] = [
    _ctx_font("ctx_menu_label", "Police libellé", 10, "#7d858b", bold=True),
    Spec("ctx_menu_label_bg", "Couleur de fond", "color", "#00000000", {"title": "Fond des libellés"}),
    Spec("ctx_menu_label_padding", "Padding", "padding", {}),
    Spec("ctx_menu_label_uppercase", "Capitales", "bool", True),
]
CATALOG["Menu contextuel : Separateurs"] = [
    Spec("ctx_menu_sep_color", "Couleur", "color", "#2c3034", {"title": "Couleur des séparateurs"}),
    Spec("ctx_menu_sep_thickness", "Épaisseur", "slider", 1, {"min": 0, "max": 8}),
    Spec("ctx_menu_sep_padding", "Marges", "padding", {}),
]


def _board_menu_spec(spec: "Spec") -> "Spec":
    """Copie d'une ligne de Menu contextuel pour le board : cles `board_<cle>`, interrupteur d'override
    `board_ovr_<cle>` devant la ligne (coupe = la ligne suit le menu de l'appli)."""
    import copy as _copy

    def scoped(value):
        return f"board_{value}" if isinstance(value, str) and value.startswith("ctx_menu") else value
    params = {}
    for name, value in spec.params.items():
        if isinstance(value, tuple) and value and isinstance(value[0], str):
            value = tuple(scoped(v) for v in value)
        params[name] = scoped(value)
    params["override_toggle_style"] = "toggle1"         # demande de l'utilisateur : overrides MRO de type 1
    return Spec(f"board_{spec.key}", spec.label, spec.kind, _copy.deepcopy(spec.default), params,
                tuple(f"board_{k}" for k in spec.extra_keys), general_toggle=f"board_ovr_{spec.key}")


# Lignes du board qui SUIVENT celles de l'appli tant que leur override est coupe : {cle board: (interrupteur,
# cle de l'appli)} (lu par ScopeValues.seed : le champ montre alors la valeur de l'appli).
BOARD_MENU_FOLLOW: dict = {}
for _title, _group in BOARD_MENU_GROUPS:
    CATALOG[f"MRO : {_group}"] = [_board_menu_spec(sp) for sp in CATALOG[_group]]
    for _spec in CATALOG[_group]:
        for _key in (_spec.key, *_spec.extra_keys):
            BOARD_MENU_FOLLOW[f"board_{_key}"] = (f"board_ovr_{_spec.key}", _key)
            BOARD_MENU_FOLLOW[f"board_{_key}_linked"] = (f"board_ovr_{_spec.key}", f"{_key}_linked")
del _title, _group, _spec, _key


def _register_board_menu_scope():
    import settings_menu
    settings_menu.register_scope("board", "board_", {main: toggle for board_key, (toggle, main)
                                                     in BOARD_MENU_FOLLOW.items()})


_register_board_menu_scope()

CATALOG["Omettre"] = [
    Spec("application_omit_dir_names", "Dossiers a omettre", "omit_list", []),
    Spec("application_omit_file_names", "Fichiers a omettre", "omit_list", [], {"files": True},
         extra_keys=("application_omit_extensions",)),
]
CATALOG["LUT"] = [
    Spec("lut_test_images", "Images de test", "lut_images", [], extra_keys=("lut_default_image", "lut_image_curves")),
]
CATALOG["Polices principales"] = [
    Spec(key, label, "font_role", {}, {"role": role, "sample": sample}) for key, role, label, sample in _FONT_ROLES
]
CATALOG["Couleurs"] = [
    Spec(f"colors:{slot}", label, "semantic_color", None, {"real_key": real_key})
    for slot, real_key, label in SEMANTIC_COLOR_SLOTS
]
# Onglets du cheminement (refonte demandee par l'utilisateur, 2026-11-08 : ces lignes SEULES, plus d'etats Set /
# Apres set / Apres focus, ni padding, margin, ombre, bordures de survol / focus). main_window/title_bar._crumb_look.
CATALOG["Barre de navigation : Cheminement"] = [
    Spec("crumb_left_spacing", "Espacement à gauche", "slider", 10, {"min": 0, "max": 200, "unit": "px"}),
    Spec("crumb_spacing", "Espacement entre les items", "slider", 5, {"min": 0, "max": 40, "unit": "px"}),
    # Sous l'onglet : ni sa bordure basse ni le filet de la barre (les colonnes qui touchent la barre n'ont deja
    # aucune bordure haute, capture_widgets._column_edge_sides).
    Spec("crumb_cut_border_active", "Couper la bordure (onglet actif)", "bool", False),
    Spec("crumb_cut_border_others", "Couper la bordure (les autres onglets)", "bool", False),
    Spec("crumb_bg_color", "Couleur de fond", "color_app", "@skinN1", {"title": "Fond des onglets"}),
    Spec("crumb_border_enabled", "Bordures", "sides_thick", False,
         {"colors_key": "crumb_border", "thickness_key": "crumb_border_thickness", "width": 90, "box": 54},
         extra_keys=("crumb_border", "crumb_border_thickness")),
    Spec("crumb_corner_radius", "Border radius", "corners", 0, {"max": 30}),
    # Transparent = la couleur de fond commune.
    Spec("crumb_active_bg_color", "Couleur de fond onglet actif", "color_app", "#00000000",
         {"title": "Fond de l'onglet actif"}),
    Spec("crumb_hover_bg_color", "Couleur de fond survol", "color_app", "#00000000", {"title": "Fond au survol"}),
    Spec("crumb_after_active_bg_color", "Couleur de fond après onglet actif", "color_app", "#00000000",
         {"title": "Fond des onglets après l'onglet actif"}),
    Spec("crumb_font_family", "Police", "font_gabarit", "",
         {"prefix": "crumb", "size": (6, 40), "size_default": 10, "color_default": "#b9bfc4",
          "color_title": "Couleur du texte"}, extra_keys=_gabarit_extra("crumb")),
    Spec("crumb_after_active_font_family", "Police après onglet actif", "font_gabarit", "",
         {"prefix": "crumb_after_active", "size": (6, 40), "size_default": 10, "color_default": "#5f666b",
          "color_title": "Couleur du texte après l'onglet actif"}, extra_keys=_gabarit_extra("crumb_after_active")),
]
# Barre de navigation : PARTAGEE entre fm_theme et fm_browser (demande de l'utilisateur, 2026-11-07). fm_theme garde
# fond, bordure basse, police du titre (et son decalage), hauteur et les icones reduire / agrandir / fermer ; tout le
# reste (autres icones et leur colonne Couleur, cheminement, barre des fenetres additionnelles) est dans la
# fenetre de reglages de fm_browser, MEME hierarchie (a reorganiser plus tard). Voir NAVBAR_THEME_NODE / NAVBAR_APP_NODE.
_NAVBAR_ICONS = (
    ("app_logo", "Icône de l'application"), ("navbar_min", "Icône réduire"),
    ("navbar_max", "Icône agrandir"), ("navbar_close", "Icône fermer"),
    ("navbar_browse", "Icône parcourir (racine)"), ("navbar_presets", "Icône gérer les presets"),
    ("settings_gear", "Icône réglages"), ("navbar_theme", "Icône fm_theme"),
    ("navbar_columns", "Icône masquer les colonnes"), ("navbar_viewer", "Icône visionneuse"),
    ("navbar_text_editor", "Icône éditeur Markdown / code"), ("navbar_board", "Icône board"),
    ("navbar_video", "Icône module vidéo"), ("navbar_font", "Icône typographie"), ("navbar_pdf", "Icône PDF"),
    ("navbar_agenda", "Icône calendrier"), ("navbar_taches", "Icône tâches"), ("navbar_pin", "Icône « toujours au-dessus » (punaise)"))
# Colonne « Couleur » du tableau d'icones de fm_browser (demande de l'utilisateur, 2026-11-08) : icone -> (cle, defaut).
# Couleur FUSIONNEE (produit) sur l'icone du bouton tant qu'il est actif (main_window/chrome._refresh_navbar_icons) ;
# blanc = l'icone telle quelle. fm_theme : son ancien orange (ex « Couleur de l'icone fm_theme »).
NAVBAR_ICON_COLORS = {
    "navbar_theme": ("navtool_icon_color_theme", "#f28c28"), "navbar_viewer": ("navtool_icon_color_viewer", "#ffffff"),
    "navbar_text_editor": ("navtool_icon_color_text_editor", "#ffffff"),
    "navbar_board": ("navtool_icon_color_board", "#ffffff"), "navbar_video": ("navtool_icon_color_video", "#ffffff"),
    "navbar_font": ("navtool_icon_color_font", "#ffffff"), "navbar_pdf": ("navtool_icon_color_pdf", "#ffffff"),
    "navbar_agenda": ("navtool_icon_color_agenda", "#ffffff"),
    "navbar_taches": ("navtool_icon_color_taches", "#ffffff"),
}
_NAVBAR_THEME_ICONS = ("navbar_min", "navbar_max", "navbar_close", "navbar_pin")   # les boutons de la fenetre
CATALOG["Barre de navigation : Icones"] = [            # fm_theme
    Spec(f"ui_icon:{key}", label, "ui_icon", None, {"ui_key": key})
    for key, label in _NAVBAR_ICONS if key in _NAVBAR_THEME_ICONS]
CATALOG["Barre de navigation : Icones (appli)"] = [    # fm_browser
    Spec(f"ui_icon:{key}", label, "ui_icon", None, {"ui_key": key})
    for key, label in _NAVBAR_ICONS if key not in _NAVBAR_THEME_ICONS] + [
    Spec(color_key, label, "color_app", default, {"title": f"Couleur : {label[0].lower()}{label[1:]}", "icon_color_of": key})
    for key, label in _NAVBAR_ICONS if key in NAVBAR_ICON_COLORS
    for color_key, default in (NAVBAR_ICON_COLORS[key],)] + [
    # Sous le tableau d'icones (`icon_tail`), coupe et titre au-dessus (demande de l'utilisateur, 2026-11-08) : fond
    # du module OUVERT a l'icone coloree (preview_column.icon_tone_bg).
    Spec("navtool_icon_tone_value", "Valeur du fond", "slider", 30,
         {"min": 0, "max": 100, "icon_tail": "Valeur du fond des icônes colorées"})]
CATALOG["Barre de navigation"] = [                     # fm_theme
    # Fond de la barre (2026-11-07) : suit la pastille « Barre de navigation » (C["app_bg"]) par défaut.
    Spec("navbar_bg_color", "Couleur de fond", "color_app", "@navbar", {"title": "Fond de la barre de navigation"}),
    Spec("navbar_bottom_enabled", "Bordure bas", "inner_line", True,
         {"prefix": "navbar", "axis": "bottom"},
         extra_keys=("navbar_bottom_color", "navbar_bottom_thickness")),
    Spec("navbar_title_font_family", "Police titre", "font_gabarit", "",
         {"prefix": "navbar_title", "size": (6, 40), "size_default": 11,
          "color_default": "#7d858b", "color_title": "Couleur du titre"},
         extra_keys=_gabarit_extra("navbar_title")),
    # Hauteur de la 1re LIGNE (titre, outils, boutons de la fenetre, centres dessus) : celle d'une barre standard.
    Spec("navbar_height", "Hauteur barre", "slider", 30, {"min": 16, "max": 160}),
]
def _navbar_override_spec(spec: "Spec") -> "Spec":
    """Copie d'une ligne de fm_theme > Barre de navigation pour fm_browser : cles `navtool_<...>`, interrupteur
    d'override `navtool_ovr_<ligne>` devant la ligne (coupe = la valeur de fm_theme, `settings_store.navbar_effective`)."""
    import copy as _copy

    def scoped(value):
        return "navtool" + value[len("navbar"):] if isinstance(value, str) and value.startswith("navbar") else value
    params = {}
    for name, value in spec.params.items():
        if isinstance(value, tuple) and value and isinstance(value[0], str):
            value = tuple(scoped(v) for v in value)
        params[name] = scoped(value)
    params["override_toggle_style"] = "toggle1"         # overrides : toggles de type 1 (comme le board)
    return Spec(scoped(spec.key), spec.label, spec.kind, _copy.deepcopy(spec.default), params,
                tuple(scoped(k) for k in spec.extra_keys), general_toggle=f"navtool_ovr_{spec.key[len('navbar_'):]}")


# Boutons de la fenetre (punaise « toujours au-dessus », reduire, agrandir, fermer ; demande de l'utilisateur,
# 2026-11-07) : CARRES (cote = Taille, jamais plus que la 1re ligne moins la marge haut / bas), colles en haut.
CATALOG["Barre de navigation : Boutons fenetre"] = [    # fm_theme
    Spec("navbar_winbtn_size", "Taille", "slider", 30, {"min": 8, "max": 160, "unit": "px"}),
    Spec("navbar_winbtn_margin", "Margin", "padding", {}),
    Spec("navbar_winbtn_padding", "Padding", "padding", {}),
    Spec("navbar_winbtn_bg_color", "Couleur de fond", "color_app", "#00000000",
         {"title": "Fond des boutons de la fenêtre"}),
    Spec("navbar_winbtn_border_enabled", "Bordures", "sides_thick", False,
         {"colors_key": "navbar_winbtn_border", "thickness_key": "navbar_winbtn_border_thickness",
          "width": 90, "box": 54},
         extra_keys=("navbar_winbtn_border", "navbar_winbtn_border_thickness")),
    Spec("navbar_winbtn_corner_radius", "Border radius", "corners", 0, {"max": 40}),
    Spec("navbar_winbtn_hover_bg_color", "Fond survol", "color_app", "@hover",
         {"title": "Fond des boutons de la fenêtre au survol"}),
    Spec("navbar_winbtn_close_hover_bg_color", "Fond survol bouton fermer", "color_app", "#c42b1c",
         {"title": "Fond du bouton fermer au survol"}),
]
CATALOG["Barre de navigation (appli)"] = [             # fm_browser
    # Bordure basse, police du titre, hauteur de fm_theme : surchargeables ici (2026-11-07).
    *(_navbar_override_spec(_sp) for _sp in CATALOG["Barre de navigation"]
      if _sp.key in ("navbar_bottom_enabled", "navbar_title_font_family", "navbar_height")),
    # Ajoutee a la hauteur de fm_theme (1re ligne) : l'etage du cheminement (demande de l'utilisateur, 2026-11-07).
    Spec("navtool_extra_height", "Hauteur barre additionnelle", "slider", 70, {"min": 0, "max": 200, "unit": "px"}),
    # Boutons d'outils de la barre (parcourir, presets, reglages, modules...) : cadre peint (IconButton.set_frame_style).
    Spec("navtool_bg_color", "Couleur de fond des icônes", "color_app", "#00000000",
         {"title": "Fond des icônes de la barre"}),
    Spec("navtool_border_enabled", "Bordure des icônes", "sides_thick", False,
         {"colors_key": "navtool_border", "thickness_key": "navtool_border_thickness", "width": 90, "box": 54},
         extra_keys=("navtool_border", "navtool_border_thickness")),
    Spec("navtool_corner_radius", "Border radius des icônes", "corners", 0, {"max": 30}),
    Spec("navtool_hover_bg_color", "Couleur de fond du survol des icônes", "color_app", "@hover",
         {"title": "Fond des icônes au survol"}),
    # Icones CARREES (cote = taille des icones, jamais plus que la 1re ligne moins la marge du haut et du bas) ;
    # champ racine et menu des presets : meme hauteur et meme position en Y (demande de l'utilisateur, 2026-11-07).
    Spec("navtool_icon_size", "Taille des icônes", "slider", 24, {"min": 8, "max": 80, "unit": "px"}),
    Spec("navtool_padding", "Padding des icônes", "padding", {}),   # entre le cadre et le dessin
    Spec("navtool_margin", "Margin des icônes", "padding", {}),     # autour ; 0 partout : elles se touchent
]
# Cadre des modules (Visionneuse, Éditeur, Board, Vidéo, Typographie, PDF, Agenda) dans la barre : avant
# Visionneuse > Regroupement, déplacé dans fm_browser avec l'habillage de ses boutons (demande de l'utilisateur,
# 2026-11-08). Boutons : taille et padding des icônes de la barre (TitleBar.style_group_button).
CATALOG["Barre de navigation : Cadre des modules"] = [
    Spec("viewer_group_bg_color", "Couleur de fond", "color_app", "#000000", {"title": "Fond du cadre des modules"}),
    Spec("viewer_group_border_enabled", "Bordures", "sides_thick", True,
         {"colors_key": "viewer_group_border", "thickness_key": "viewer_group_border_thickness",
          "width": 90, "box": 54}, extra_keys=("viewer_group_border", "viewer_group_border_thickness")),
    Spec("viewer_group_corner_radius", "Border radius", "corners", 4, {"max": 30}),
    Spec("viewer_group_label_enabled", "Nom du module", "bool", True),
    Spec("viewer_group_label_font_family", "Police du nom", "font_gabarit", "",
         {"prefix": "viewer_group_label", "size": (6, 40), "size_default": 9, "bold_default": True,
          "color_default": "#7d858b", "color_title": "Couleur du nom"},
         extra_keys=_gabarit_extra("viewer_group_label")),
    Spec("viewer_group_padding", "Padding", "padding", {}),
    Spec("viewer_group_margin", "Margin", "padding", {}),
    Spec("viewer_group_btn_bg_color", "Boutons : couleur de fond", "color_app", "#00000000",
         {"title": "Fond des boutons du cadre"}),
    Spec("viewer_group_btn_icon_color", "Boutons : couleur de base des icônes", "color_app", "#c4cacf",
         {"title": "Couleur des icônes du cadre"}),
    Spec("viewer_group_btn_border_enabled", "Boutons : bordures", "sides_thick", False,
         {"colors_key": "viewer_group_btn_border", "thickness_key": "viewer_group_btn_border_thickness",
          "width": 90, "box": 54}, extra_keys=("viewer_group_btn_border", "viewer_group_btn_border_thickness")),
    Spec("viewer_group_btn_corner_radius", "Border radius des boutons", "corners", 4, {"max": 30}),
    Spec("viewer_group_btn_close_hover_bg_color", "Bouton fermer : fond au survol", "color_app", "#c42b1c",
         {"title": "Survol du bouton fermer le module"}),
]
# Override coupe : le champ montre la valeur de fm_theme (ScopeValues.seed).
for _sp in CATALOG["Barre de navigation"]:
    if _sp.key in ("navbar_bottom_enabled", "navbar_title_font_family", "navbar_height"):
        for _key in (_sp.key, *_sp.extra_keys):
            _own = "navtool" + _key[len("navbar"):]
            BOARD_MENU_FOLLOW[_own] = (f"navtool_ovr_{_sp.key[len('navbar_'):]}", _key)
            BOARD_MENU_FOLLOW[f"{_own}_linked"] = (f"navtool_ovr_{_sp.key[len('navbar_'):]}", f"{_key}_linked")
del _sp, _key, _own
# Barre d'etat (fm_theme, 2026-11-05) : bas de la fenetre principale, chemin a gauche, infos a droite
# (fm_theme/status_bar.py l'applique).
CATALOG["Barre d'état"] = [
    Spec("statusbar_height", "Hauteur barre", "slider", 24, {"min": 16, "max": 80}),
    Spec("statusbar_bg_color", "Couleur de fond", "color_app", "#202326", {"title": "Fond de la barre d'état"}),
    Spec("statusbar_top_enabled", "Bordure haut", "inner_line", True,
         {"prefix": "statusbar", "axis": "top"},
         extra_keys=("statusbar_top_color", "statusbar_top_thickness")),
    Spec("statusbar_padding_x", "Marge gauche / droite", "slider", 10, {"min": 0, "max": 60, "unit": "px"}),
    Spec("statusbar_spacing", "Espacement entre les éléments", "slider", 12, {"min": 0, "max": 60, "unit": "px"}),
    _ctx_font("statusbar_path", "Texte (chemin)", 11, "#b9bfc4"),
    _ctx_font("statusbar_info", "Texte (infos)", 11, "#5f666b"),
]


def _button_state_rows(state: str, label: str, bg_title: str, text_title: str) -> list[Spec]:
    """Lignes d'UN état du bouton, chacune OVERRIDE de la ligne de l'état standard (toggle devant la ligne, coupé =
    la ligne standard, affichée grisée ; demande de l'utilisateur, 2026-11-12 ; fm_theme.style.button_state_override) :
    fond, Bordures (couleur transparente = le thème, épaisseur 0 = celle de l'état standard), Polices (ligne standard
    entière), Border radius, Décalage (propre à l'état), Ombres (allumée sans côté = AUCUNE ombre)."""
    pre = f"button_{state}"

    def ovr(row: str) -> dict:
        # + petit bouton « copier » devant le titre : la ligne prend celle de l'état choisi dans « suit » (2026-11-12)
        return {"override": (f"{pre}_ovr_{row}", state, row), "copy_row": (state, row)}
    shadow = _shadow_spec(f"{pre}_shadow", f"{label} : ombres")
    shadow.params.update(ovr("shadow"))
    return [
        # 1re ligne de l'état : liste « suit » (lignes non surchargées = celles de l'état choisi) et « Réinitialiser »
        # (l'état prend exactement celui choisi) ; demande de l'utilisateur, 2026-11-12.
        Spec(f"{pre}_follow", f"{label} : suit", "state_follow", "standard", {"state": state}),
        Spec(f"{pre}_color", f"{label} : couleur de fond", "color_app", "#00000000", {"title": bg_title, **ovr("color")}),
        Spec(f"{pre}_border_enabled", f"{label} : bordures", "sides_thick", True,
             {"colors_key": f"{pre}_border", "thickness_key": f"{pre}_border_thickness",
              "thickness_label": "Épaisseur (0 = la même)", **ovr("border")},
             extra_keys=(f"{pre}_border", f"{pre}_border_thickness")),
        Spec(f"{pre}_font_family", f"{label} : polices", "font_gabarit", "",
             {"prefix": pre, "size": (6, 40), "size_default": 11, "color_default": "#00000000",
              "color_title": text_title, "keys": {"color": f"{pre}_text_color"}, "shown_color": True, **ovr("font")},
             extra_keys=_gabarit_extra(pre, f"{pre}_text_color")),
        Spec(f"{pre}_corner_radius", f"{label} : border radius", "corners", 0,
             {"max": 40, "none_from": "button_radius", **ovr("radius")}),
        # Décalage du bouton entier (ombre comprise), propre à l'état (2026-11-11, fm_theme.style `_ButtonEffect`).
        Spec(f"{pre}_offset_x", f"{label} : décalage", "offset", 0,
             {"y_key": f"{pre}_offset_y", "range": (-3, 3), "copy_row": (state, "offset")},
             extra_keys=(f"{pre}_offset_y",)),
        shadow,
    ]


def _standard_control_specs(prefix: str, *, shadow: bool = False) -> list[Spec]:
    rows = [
        Spec(f"{prefix}_bg_color", "Couleur", "color_app",
             "#282c30" if prefix == "button" else "#00000000" if prefix == "tabs" else "@saisie",
             {"title": "Couleur de fond"}),
        Spec(f"{prefix}_border_enabled", "Bordures", "sides_thick", True,
             {"colors_key": f"{prefix}_border", "thickness_key": f"{prefix}_border_thickness"},
             extra_keys=(f"{prefix}_border", f"{prefix}_border_thickness")),
        Spec(f"{prefix}_font_family", "Polices", "font_gabarit", "",
             {"prefix": prefix, "size": (6, 40), "size_default": 11,
              "color_default": "#c4cacf" if prefix == "button" else "#b9bfc4",
              "color_title": "Couleur du texte"}, extra_keys=_gabarit_extra(prefix)),
        # None = l'ancien rayon `<prefix>_radius` (fm_theme.style._control_radius) : le champ le montre aussi, sinon
        # il affichait 0 et l'enregistrer rendait carrés boutons / champs (presets Studio VFX, Test ; 2026-11-12).
        Spec(f"{prefix}_corner_radius", "Border radius", "corners", 0,
             {"max": 40, **({"none_from": f"{prefix}_radius"} if prefix in ("button", "input") else {})}),
    ]
    if shadow:
        rows.append(_shadow_spec(f"{prefix}_shadow"))
    if prefix == "button":
        # Décalage du TEXTE dans le bouton, tous les états, sous Polices (demande de l'utilisateur, 2026-11-12 ;
        # fm_theme.style.button_padding_css). Ligne logique 24 du tableau (étape 5 de `_BUTTON_DIMS_STEPS`).
        rows.insert(3, Spec("button_text_offset_x", "Décalage du texte", "offset", 0,
                            {"y_key": "button_text_offset_y", "range": (-10, 10)},
                            extra_keys=("button_text_offset_y",)))
        # Survol, focus et état enfoncé (« active »), comme les boutons des barres d'outils (2026-11-10) ;
        # chaque état : overrides des lignes standard + décalage (`_button_state_rows`, 2026-11-12). Ordre des lignes figé : `settings_store._BUTTON_DIMS_MIGRATION` y convertit l'ancienne
        # mise en page.
        rows[2:2] = [row for state, label, bg_title, text_title in (
            ("hover", "Survol", "Fond des boutons au survol (transparent = celui du thème)",
             "Texte des boutons au survol (transparent = le même)"),
            ("focus", "Focus", "Fond du bouton qui a le focus (transparent = le même)",
             "Texte du bouton qui a le focus (transparent = le même)"),
            ("active", "Enfoncé", "Fond des boutons enfoncés (transparent = l'accent)",
             "Texte des boutons enfoncés (transparent = le texte sur accent du thème)"),
        ) for row in _button_state_rows(state, label, bg_title, text_title)]
    if prefix == "input":
        rows.append(Spec("input_height", "Hauteur des zones de saisie (0 = d'origine)", "slider", 0,
                         {"min": 0, "max": 60, "unit": "px"}))
    if prefix == "tabs":
        # Tab en cours : son fond et ses bordures ; tab survole : son fond (les autres lignes = tous les tabs).
        rows[0] = Spec("tabs_bg_color", "Couleur des tabs", "color_app", "#00000000", {"title": "Fond des tabs"})
        rows[1] = Spec("tabs_border_enabled", "Bordures du tab en cours", "sides_thick", True,
                       {"colors_key": "tabs_border", "thickness_key": "tabs_border_thickness"},
                       extra_keys=("tabs_border", "tabs_border_thickness"))
        rows.insert(1, Spec("tabs_active_bg_color", "Couleur du tab en cours", "color_app", "#00000000",
                            {"title": "Fond du tab en cours"}))
        rows.insert(2, Spec("tabs_hover_bg_color", "Couleur de fond au survol", "color_app", "#00000000",
                            {"title": "Fond des tabs au survol"}))
        rows.insert(3, Spec("tabs_strip_color", "Couleur sous les tabs", "color_app", "#00000000",
                            {"title": "Fond de la barre des tabs"}))
        rows.insert(5, Spec("tabs_inactive_border_enabled", "Bordures des tabs non sélectionnés", "sides_thick",
                            False, {"colors_key": "tabs_inactive_border",
                                    "thickness_key": "tabs_inactive_border_thickness"},
                            extra_keys=("tabs_inactive_border", "tabs_inactive_border_thickness")))
        rows.append(Spec("tabs_bottom_enabled", "Bordure entre tabs et interface", "inner_line", True,
                         {"prefix": "tabs", "axis": "bottom"},
                         extra_keys=("tabs_bottom_color", "tabs_bottom_thickness")))
        rows.append(Spec("tabs_height", "Hauteur des tabs", "slider", 36, {"min": 20, "max": 80, "unit": "px"}))
        rows.append(Spec("tabs_spacing", "Espacement entre les tabs", "slider", 4, {"min": 0, "max": 40, "unit": "px"}))
    return rows


CATALOG["Bouton"] = _standard_control_specs("button", shadow=True)
CATALOG["Zone de saisie"] = _standard_control_specs("input")
CATALOG["Tabs"] = _standard_control_specs("tabs")


def _palette_specs() -> dict[str, list[Spec]]:
    """Section « Palette » (type d'élément « palette » de fm_theme, fm_theme/palette.py) : un tableau par partie (le
    Contrôleur a un sous-tableau par type : slider, liste déroulante, zone de saisie, toggle), une ligne par
    réglage `palette_*` (défauts dans fm_theme/palette_defaults.py ; couleur transparente = celle du thème)."""
    from fm_theme.palette import SNAP_SIDES
    from fm_theme.palette_defaults import PALETTE_DEFAULTS as D, SLIDER_STYLES, TITLE_ALIGNS, TOGGLE_STYLES

    def slider(key, label, low, high, unit="px"):
        return Spec(key, label, "slider", D[key], {"min": low, "max": high, "unit": unit})

    def color(key, label, title=None):
        return Spec(key, label, "color_app", D[key], {"title": title or label})

    def border(prefix, label="Bordures"):
        return Spec(f"{prefix}_border_enabled", label, "sides_thick", D[f"{prefix}_border_enabled"],
                    {"colors_key": f"{prefix}_border", "thickness_key": f"{prefix}_border_thickness"},
                    extra_keys=(f"{prefix}_border", f"{prefix}_border_thickness"))

    def font(prefix, label, size, color_default):
        return Spec(f"{prefix}_font_family", label, "font_gabarit", "",
                    {"prefix": prefix, "size": (6, 40), "size_default": size, "color_default": color_default,
                     "color_title": "Couleur du texte"}, extra_keys=_gabarit_extra(prefix))

    def choice(key, label, choices):
        return Spec(key, label, "choice", D[key], {"choices": choices})

    return {
        "Palette : Grille": [
            slider("palette_cell_size", "Taille d'une case (une icône)", 16, 96),
            slider("palette_cell_gap", "Écart entre les cases", 0, 24),
            slider("palette_margin", "Marges (gauche, droite et bas : égales)", 0, 32),
            slider("palette_snap_distance", "Accrochage aux bords et aux autres barres (distance)", 0, 120),
        ],
        "Palette : Barre": [
            color("palette_bg_color", "Couleur de fond", "Fond de la barre (transparent = fond des panneaux)"),
            border("palette"),
            Spec("palette_corner_radius", "Border radius", "corners", D["palette_corner_radius"], {"max": 40}),
            _shadow_spec("palette_shadow"),
            color("palette_drag_border_color", "Bordure pendant un déplacement"),
            # menu 1. rien / 2. pas de bordure / 3. couleur de bordure ; au 3 : sa couleur dans la sous-cellule
            # voisine (demande de l'utilisateur, 2026-11-08 ; remplace le toggle « pas de bordure du côté collé »)
            Spec("palette_snap_side", "Clipsée : comportement du côté collé", "snap_side", None,
                 {"parts": (("Comportement", Spec("palette_snap_side", "Comportement", "choice", D["palette_snap_side"],
                                                  {"choices": SNAP_SIDES, "width": 190})),
                            ("Couleur", color("palette_snap_side_color", "Couleur",
                                              "Bordure du côté collé (transparent = bordure des panneaux)")))},
                 extra_keys=("palette_snap_side_color",)),
            Spec("palette_snap_separator", "Séparateur entre barres collées l'une à l'autre", "bool",
                 D["palette_snap_separator"]),
            Spec("palette_snap_header_color", "Clipsée : en-tête de la couleur de l'élément voisin", "bool",
                 D["palette_snap_header_color"]),
            Spec("palette_snap_bg_color", "Clipsée : fond de la couleur de l'élément voisin", "bool",
                 D["palette_snap_bg_color"]),
            Spec("palette_snap_border_match", "Clipsée : bordure de la couleur de celle de l'élément voisin", "bool",
                 D["palette_snap_border_match"]),
        ],
        "Palette : En-tete": [
            Spec("palette_header_shown", "Afficher les en-têtes (sans : la barre se tire par sa tranche)", "bool",
                 D["palette_header_shown"]),
            slider("palette_header_height", "Hauteur du titre", 0, 80),
            color("palette_header_bg_color", "Couleur de fond de l'en-tête", "Fond de l'en-tête (transparent = celui de la barre)"),
            font("palette_title", "Police du titre", 10, "#8d949a"),
            choice("palette_title_align", "Justification du titre", TITLE_ALIGNS),
            Spec("palette_title_caps", "Titre en majuscules", "bool", D["palette_title_caps"]),
            slider("palette_title_tracking", "Espacement des lettres du titre", 0, 60, "1/10 px"),
            Spec("palette_grip_enabled", "Poignée de déplacement", "bool", D["palette_grip_enabled"]),
            color("palette_grip_color", "Couleur de la poignée"),
        ],
        "Palette : Icones": [
            color("palette_cell_bg_color", "Couleur de fond", "Fond d'une icône (transparent = aucun)"),
            border("palette_cell", "Bordures (couleurs, épaisseur)"),
            slider("palette_cell_radius", "Border radius", 0, 40),
            slider("palette_icon_ratio", "Taille de l'icône (part de la case)", 20, 100, "%"),
            color("palette_icon_color", "Couleur des icônes"),
            color("palette_cell_hover_color", "Fond au survol"),
            color("palette_cell_active_color", "Fond de l'icône active"),
            color("palette_cell_active_border_color", "Contour de l'icône active"),
            slider("palette_cell_active_border_thickness", "Épaisseur du contour actif", 0, 6),
            color("palette_drop_color", "Accent : case de dépôt, barre visée, trait d'aimantation"),
            color("palette_separator_color", "Couleur des séparateurs (clic droit sur une barre)"),
            slider("palette_slide_ms", "Glissement des éléments et des barres qui font place", 0, 400, "ms"),
        ],
        "Palette : Controleur": [
            color("palette_bar_bg_color", "Couleur de fond"),
            border("palette_bar"),
            slider("palette_bar_radius", "Border radius", 0, 40),
            slider("palette_bar_join_gap", "Soudés (pas d'arrondi entre eux) jusqu'à un écart de", 0, 24),
            slider("palette_bar_padding", "Marges intérieures", 0, 32),
            font("palette_bar", "Police du libellé", 11, "#8d949a"),
            color("palette_bar_value_color", "Couleur de la valeur"),
            Spec("palette_bar_grip_enabled", "Poignée de déplacement", "bool", D["palette_bar_grip_enabled"]),
            color("palette_bar_grip_color", "Couleur de la poignée"),
            Spec("palette_bar_handle_enabled", "Trait de largeur (à droite)", "bool", D["palette_bar_handle_enabled"]),
            color("palette_bar_handle_color", "Couleur du trait"),
        ],
        "Palette : Slider": [
            choice("palette_slider_style", "Choix du slider", SLIDER_STYLES),
            slider("palette_slider_track_height", "Épaisseur du rail (propre aux barres)", 1, 20),
            slider("palette_slider_thumb_width", "Largeur du sélecteur", 1, 30),
            slider("palette_slider_thumb_height", "Hauteur du sélecteur", 2, 30),
            slider("palette_slider_radius", "Border radius du rail et du sélecteur", 0, 20),
            color("palette_slider_track_color", "Couleur du rail"),
            color("palette_slider_fill_color", "Couleur du rail parcouru"),
            color("palette_slider_thumb_color", "Couleur du sélecteur"),
            slider("palette_slider_value_width", "Largeur minimale de la valeur", 0, 120),
        ],
        "Palette : Liste": [
            slider("palette_select_min_width", "Largeur minimale de la liste", 20, 300),
            slider("palette_select_height", "Hauteur de la liste", 12, 40),
        ],
        "Palette : Saisie": [
            slider("palette_input_min_width", "Largeur minimale du champ", 20, 300),
            slider("palette_input_height", "Hauteur du champ", 12, 40),
        ],
        "Palette : Toggle": [
            choice("palette_toggle_style", "Style du toggle", TOGGLE_STYLES),
            Spec("palette_toggle_labels", "Libellé d'état (actif / sans)", "bool", D["palette_toggle_labels"]),
        ],
    }


CATALOG.update(_palette_specs())
CATALOG["Raccourci"] = [
    Spec("shortcut_font_family", "Police", "font_gabarit", "",
         {"prefix": "shortcut", "size": (8, 24), "size_default": 11, "bold_default": False,
          "only": ("family", "bold", "italic", "size", "smoothing")},     # couleur : Icones > Couleur des dossiers
         extra_keys=_gabarit_extra("shortcut", only=("bold", "italic", "size", "smoothing"))),
]
UI_ICON_ROWS = (("pin", "Punaise"), ("folder_default", "Dossiers"), ("file_default", "Fichiers"),
                ("settings_gear", "Engrenage (bouton Parametres)"),
                ("settings_style", "Reglages visuels (second bouton Parametres)"),
                ("shortcut", "Raccourcis"),)
FOLDER_ICON_COLOR_ROWS = (("standard", "Standard", "Dossiers standard", "#d6d9dc"),
                          ("shortcut", "Raccourci", "Dossiers raccourcis", "#8fb4d5"),
                          ("lightroom", "Lightroom", "Dossiers Lightroom", "#87cefa"))
FOLDER_COLOR_COLUMNS = [("Dossier", 160), ("Icône", 90), ("Texte", 80), ("Couleur icône", 110),
                        ("Couleur du texte", 130)]
CATALOG["Icones : General"] = [
    Spec(f"ui_icon:{suffix}", label, "ui_icon", None, {"ui_key": suffix}) for suffix, label in UI_ICON_ROWS
]
# Couleurs des dossiers selon leur sorte (demande de l'utilisateur) : teinte de l'icone (blanc = icone telle quelle)
# et couleur du texte (toggle Texte coupe = couleur du texte de la colonne ; « Couleur icone » = celle de l'icone,
# couleur du texte grisee). Groupe a part : « Icones : General » reste un tableau d'icones (ICON_GROUPS : toutes ses
# lignes sont des icones). Specs par ligne, dans l'ordre des colonnes de FOLDER_COLOR_COLUMNS (voir build_group) :
# une COLONNE par reglage, jamais une cellule divisee sur toutes les lignes.
CATALOG["Icones : Couleurs des dossiers"] = [
    spec for kind, label, title, text_default in FOLDER_ICON_COLOR_ROWS for spec in (
        Spec(f"folder_icon_color_{kind}", label, "color_app", "#ffffff", {"title": f"Icône : {title.lower()}"}),
        Spec(f"folder_text_color_{kind}_enabled", label, "bool", False),
        Spec(f"folder_text_color_{kind}_from_icon", label, "bool", False),
        Spec(f"folder_text_color_{kind}", label, "color_app", text_default, {"title": f"Texte : {title.lower()}"}))
]
# Couleur des icones de la barre de navigation : deplacee dans Theme > General (2026-11-12, `navtool_icon_base_color`).
CATALOG["Icones : Logiciels"] = [
    Spec("custom_softwares", "Logiciels", "logiciels", [], extra_keys=("removed_softwares",)),
]

# General > Colonnes speciales > Colonne Focus (colonne des vignettes) : reglages propres a cette colonne.
CATALOG["Focus : Image"] = [
    Spec("preview_padding", "Padding", "padding", {}),
    Spec("preview_radius", "Border radius", "corners", 0, {"max": 40}),
    _shadow_spec("preview_shadow"),
    Spec("preview_image_ratio", "Ratio (largeur/hauteur)", "ratio", 1.0),
]
CATALOG["Focus : Zone titre"] = [
    Spec("preview_title_zone_height", "Hauteur", "slider", 52, {"min": 20, "max": 120}),
    Spec("preview_title_font_family", "Titre - police", "font_gabarit", "",
         {"prefix": "preview_title", "size": (8, 48), "size_default": 26, "color_default": "#d6d9dc",
          "color_title": "Couleur du titre"}, extra_keys=_gabarit_extra("preview_title")),
    Spec("preview_title_padding", "Titre - padding", "padding", {},
         {"order": [("left", "G"), ("top", "H"), ("bottom", "B")]}),
    Spec("preview_status_font_family", "Apercu des dossiers - police", "font_gabarit", "",
         {"prefix": "preview_status", "size": (6, 24), "size_default": 10, "color_default": "#d6d9dc",
          "color_title": "Couleur (apercu dossiers)"}, extra_keys=_gabarit_extra("preview_status")),
    Spec("preview_status_font_color_idle", "Apercu des dossiers - non selectionne", "color_app", "#5f666b",
         {"title": "Non selectionne"}),
    Spec("preview_status_padding", "Apercu des dossiers - padding", "padding", {},
         {"order": [("top", "H"), ("right", "D")]}),
]
_STEP_BADGE_BG = {"2": "#5c6368", "3": "#5c6368", "4": "#3f6f9f", "5": "#3f6f9f", "6": "#d9822b", "n": "#5c6368"}
CATALOG["Projets : Icone de niveaux"] = [
    Spec("step_badge_width", "Taille", "xy", 18,
         {"range": (8, 60), "defaults": (18, 18), "second_key": "step_badge_height",
          "captions": ("Largeur", "Hauteur")}, extra_keys=("step_badge_height",)),
    Spec("step_badge_border_enabled", "Bordures", "sides_thick", False,
         {"colors_key": "step_badge_border", "thickness_key": "step_badge_border_thickness"},
         extra_keys=("step_badge_border", "step_badge_border_thickness")),
    Spec("step_badge_border_smoothing", "Lissage de la bordure", "bool", True),
    Spec("step_badge_radius", "Border radius", "corners", 9, {"max": 30}),
    *[Spec(f"step_badge_text_color_base{n}", f"Couleurs base {n.upper()}", "color_pair", "#eef2f5",
           {"bg_key": f"step_badge_color_base{n}", "text_default": "#eef2f5", "bg_default": bg},
           extra_keys=(f"step_badge_color_base{n}",))
      for n, bg in _STEP_BADGE_BG.items()],
    Spec("step_badge_font_family", "Police du numero", "font_gabarit", "",
         {"prefix": "step_badge", "only": ("family", "bold", "smoothing"), "bold_default": True},
         extra_keys=_gabarit_extra("step_badge", only=("family", "bold", "smoothing"))),
    Spec("step_badge_offset_x", "Position", "xy", 4,
         {"range": (-100, 200), "defaults": (4, 0), "second_key": "step_badge_offset_y", "captions": ("H", "V")},
         extra_keys=("step_badge_offset_y",)),
]


# ==========================================================================
# L'arbre des sections : quoi est imbrique dans quoi (donnees, pas code)
# ==========================================================================

SELECTION_NODE = Node("Selection", children=tuple(Node(label, group) for group, label in SELECTION_STATES))

# General > Colonnes speciales : reglages propres a une colonne (ex-onglets Projets et Focus).
SPECIAL_COLUMNS = Node("Colonnes spéciales", children=(
    Node("Colonne Projets", children=(Node("Icône de niveaux", "Projets : Icone de niveaux"),)),
    Node("Colonne Focus", children=(Node("Image", "Focus : Image"), Node("Zone titre", "Focus : Zone titre"))),
))

GENERAL_COLUMNS = Node("Colonnes", children=(
    Node("Colonnes", "G Colonnes"), Node("Encart", "G Encart"), Node("Entetes", "G Entetes"),
    Node("Lignes", children=(Node("Lignes", "G Lignes"), Node("Texte", "G Texte"),
                             Node("Icone", "G Icone"), Node("Apercu", "G Apercu"))),
    Node("Raccourci", "Raccourci"),
    SELECTION_NODE,                                     # Selection (Focus + 3 etats clones)
))

def _toggle_style_node(prefix: str, label: str) -> Node:
    """Toggles > <style> : Type (intact), puis État OFF et État ON (un tableau « Fond | Coche » chacun)."""
    states = tuple(Node(f"État {label_}", f"{prefix} : {label_}") for _s, label_ in TOGGLE_STATES)
    return Node(label, children=(Node("Type", f"{prefix} : Type"), *states), toggle_key=prefix)


def general_tree(settings: dict | None = None) -> tuple:
    """Arbre de l'onglet General ; la section Toggles porte une sous-section par style (renommable,
    supprimable), dans l'ordre de la liste des styles."""
    styles = toggle_style_list(settings or {"toggle_styles": [{"key": "toggle1", "name": "Toggle 1"},
                                                              {"key": "toggle2", "name": "Toggle 2"}]})
    for style in styles:
        register_toggle_catalog(style["key"])
    toggle_nodes = tuple(_toggle_style_node(s["key"], s["name"]) for s in styles)
    return tuple(Node("Toggles", "Toggles : Style", children=toggle_nodes) if n.title == "Toggles" else n
                 for n in GENERAL_TREE)


# Barre de navigation, MEME titre dans les deux fenetres : fm_theme (aspect de la barre) / fm_browser (le reste).
NAVBAR_THEME_NODE = Node("Barre de navigation", "Barre de navigation",
                         children=(Node("Boutons fenêtre", "Barre de navigation : Boutons fenetre"),
                                   Node("Icônes", "Barre de navigation : Icones")))
NAVBAR_APP_NODE = Node("Barre de navigation", "Barre de navigation (appli)",
                       children=(Node("Icônes", "Barre de navigation : Icones (appli)"),
                                 Node("Cheminement", "Barre de navigation : Cheminement"),
                                 Node("Cadre des modules", "Barre de navigation : Cadre des modules"),
                                 Node("Fenêtres additionnelles", "Barre de navigation : Fenetres additionnelles")))

GENERAL_TREE = (
    GENERAL_COLUMNS,
    SPECIAL_COLUMNS,
    Node("TITRES", children=(Node("Polices", "Titre : Polices"),
                             Node("Paragraphes", children=tuple(Node(f"Niveau {n}", f"Titre : Fond {n}")
                                                               for n in range(1, 6))))),
    Node("Application", "Application", children=(
        Node("Chargement et génération automatique", "Chargement et génération automatique"),)),
    Node("Menu contextuel", children=(Node("Menu", "Menu contextuel : Menu"), Node("Lignes", "Menu contextuel : Lignes"),
                                      Node("Survol", "Menu contextuel : Survol"),
                                      Node("Libellés", "Menu contextuel : Libelles"),
                                      Node("Séparateurs", "Menu contextuel : Separateurs"))),
    Node("Fenêtres additionnelles", "Fenêtres additionnelles"),
    Node("Dossiers et fichiers à omettre", "Omettre"),
    Node("LUT", "LUT"),
    Node("Polices principales", "Polices principales"),
    Node("Couleurs", "Couleurs"),
    NAVBAR_APP_NODE,                                    # fm_theme : NAVBAR_THEME_NODE (voir theme_tree)
    Node("Barre d'état", "Barre d'état"),
    Node("Bouton", "Bouton"),
    Node("Tabs", "Tabs"),
    Node("Barres d'outils", children=(Node("Grille", "Palette : Grille"), Node("Barre", "Palette : Barre"),
                              Node("En-tête", "Palette : En-tete"), Node("Icônes", "Palette : Icones"),
                              Node("Contrôleur", "Palette : Controleur", children=(
                                  Node("Slider", "Palette : Slider"), Node("Liste déroulante", "Palette : Liste"),
                                  Node("Zone de saisie", "Palette : Saisie"), Node("Toggle", "Palette : Toggle"))))),
    Node("Zone de saisie", "Zone de saisie"),
    Node("Tableaux", "Tableaux"),
    Node("Toggles", "Toggles : Style", children=tuple(
        _toggle_style_node(p, label) for p, label in (("toggle1", "Toggle 1"), ("toggle2", "Toggle 2")))),
    Node("Sliders", children=(Node("Rail", "Slider : Rail"), Node("Selecteur", "Slider : Selecteur"))),
    Node("ICONES", children=(Node("General", "Icones : General"),
                             Node("Couleur des dossiers", "Icones : Couleurs des dossiers"),
                             Node("Logiciels", "Icones : Logiciels"))),
)


# Editeur fm_theme (fm_theme.bat, theme_editor.py) : l'arbre general REDUIT a l'aspect generique (inventaire valide,
# docs/agents/fm_theme_inventaire.md). Memes sections, memes champs ; « General » reprend l'echelle et l'arrondi de la
# fenetre de l'onglet Application (qui melange aspect et fonctionnement).
THEME_TAB = "Thème"
THEME_SECTIONS = ("Couleurs", "Polices principales", "TITRES", "Toggles", "Sliders", "Zone de saisie", "Bouton",
                  "Tableaux", "Tabs", "Barres d'outils", "Menu contextuel", "Fenêtres additionnelles",
                  # Barres de la fenetre (2026-11-05) : aspect general, plus dans General de fm_browser.
                  "Barre de navigation", "Barre d'état")
CATALOG["Thème : Général"] = [s for s in CATALOG["Application"] if s.key in ("ui_scale", "window_radius")] + [
    # Valeur du grise des objets non utilisables : elements d'interface (fonds, bordures, reglages inactifs), textes,
    # icones ; et la couleur des icones (ex fm_browser > ICONES) : demande de l'utilisateur, 2026-11-12.
    Spec("dimmed_opacity", "Valeur du grisé : éléments d'interface", "slider", 20,
         {"min": 5, "max": 100, "unit": "%", "width": 280}),
    Spec("dimmed_text_opacity", "Valeur du grisé : textes", "slider", 20, {"min": 5, "max": 100, "unit": "%", "width": 280}),
    Spec("dimmed_icon_opacity", "Valeur du grisé : icônes", "slider", 20, {"min": 5, "max": 100, "unit": "%", "width": 280}),
    Spec("navtool_icon_base_color", "Couleur des icônes", "color_app", "#c4cacf", {"title": "Icônes : couleur de base"}),
    # Icones chargees (fichiers choisis, icons/*.png) ramenees au bord de leurs pixels visibles puis recentrees avec
    # cette marge, % du cadre de chaque cote (demande de l'utilisateur, 2026-11-12).
    Spec("icon_margin", "Marge des icônes", "slider", 20, {"min": 0, "max": 40, "unit": "%", "width": 280}),
    # Icones du catalogue (fm_theme.icon_library) en flat monochrome ou flat couleur (demande de l'utilisateur, 2026-11-13).
    Spec("icon_library_style", "Style des icônes", "choice", "monochrome", {"choices": (
        ("monochrome", "Flat monochrome"), ("couleur", "Flat couleur")), "width": 190}),
    # Pourtour de TOUTES les fenetres (principale et additionnelles) : remplace la ligne « Bordures » des
    # Fenetres additionnelles (demande de l'utilisateur, 2026-10-30).
    Spec("window_border_enabled", "Bordure des fenêtres", "sides_thick", True,
         {"colors_key": "window_border", "thickness_key": "window_border_thickness", "width": 90, "box": 54},
         extra_keys=("window_border", "window_border_thickness")),
    # Volet des variantes de l'editeur : cadre de la variante editee (croquis de l'utilisateur, 2026-11-10).
    Spec("variant_sel_border_enabled", "Variantes : bordure du cadre de sélection", "sides_thick", True,
         {"colors_key": "variant_sel_border", "thickness_key": "variant_sel_border_thickness", "width": 90, "box": 54},
         extra_keys=("variant_sel_border", "variant_sel_border_thickness")),
    Spec("variant_sel_corner_radius", "Border radius du cadre de sélection des variantes", "corners", 6, {"max": 30}),
    Spec("variant_sel_bg_color", "Variantes : couleur de fond du cadre de sélection", "color_app", "#00000000",
         {"title": "Fond de la variante éditée (transparent = aucun)"}),
]
# Etape 6 : ces deux reglages ne sont plus dans Application (General de fm_browser), seulement dans le Theme.
CATALOG["Application"] = [s for s in CATALOG["Application"] if s.key not in ("ui_scale", "window_radius")]


def theme_tree(settings: dict | None = None) -> tuple:
    """Arbre de l'onglet Thème : « General » (echelle, arrondi de la fenetre) puis les sections d'aspect."""
    nodes = {n.title: n for n in general_tree(settings)}
    nodes["Barre de navigation"] = NAVBAR_THEME_NODE    # la partie fm_browser reste dans la fenetre generale
    return (Node("Général", "Thème : Général"),) + tuple(nodes[title] for title in THEME_SECTIONS)


def tab_tree(label: str, settings: dict | None = None) -> tuple:
    """Arbre d'un onglet : module a part, Thème (editeur fm_theme) ou General. General = fonctionnement et aspect
    PROPRE a fm_browser : l'aspect generique (THEME_SECTIONS) se regle dans fm_theme (etape 6, bouton « Thème »)."""
    if label in STANDALONE_TABS:
        return STANDALONE_TABS[label]
    if label == THEME_TAB:
        return theme_tree(settings)
    return tuple(n for n in general_tree(settings) if n.title not in THEME_SECTIONS or n is NAVBAR_APP_NODE)


# Onglets de reglages generaux a part (pas une colonne) : leur arbre.
STANDALONE_TABS = {MARKDOWN_TAB: MARKDOWN_TREE, VIDEO_TAB: VIDEO_TREE, BOARD_TAB: BOARD_TREE, MRO_TAB: MRO_TREE,
                   CAD_TAB: CAD_TREE, DESIGN_TAB: DESIGN_TREE, TABLEUR_TAB: TABLEUR_TREE, ILL_TAB: ILL_TREE, PS_TAB: PS_TREE, VIEWER_TAB: VIEWER_TREE,
                   TYPO_TAB: TYPO_TREE, PDF_TAB: PDF_TREE, AGENDA_TAB: AGENDA_TREE,
                   TACHES_TAB: TACHES_TREE}

# Groupes repris de la v1 : leurs tableaux ont une cle de dimensions a eux (voir build_group).
# Groupes dont la section porte le MEME titre qu'une section de l'autre fenetre (fm_theme / fm_browser) : la cle
# deduite des titres serait commune, et les deux tableaux s'ecrasaient leurs largeurs (signale, 2026-11-07).
SHARED_TITLE_GROUPS = frozenset(("Barre de navigation (appli)",))
# Sous-section creee a la construction pour les tableaux propres d'une section qui a aussi des sous-sections
# (_LazyNode._build ; demande de l'utilisateur, 2026-11-08).
MAIN_SUBSECTION = "Main"
PORTED_GROUPS = frozenset(("Application", "Omettre", "LUT", "Polices principales", "Couleurs",
                           "Raccourci", "Icones : General", "Icones : Logiciels", "Focus : Image",
                           "Focus : Zone titre", "Projets : Icone de niveaux"))

# A FAIRE ENSEMBLE PLUS TARD : le systeme de PRESETS (celui de la v1 ne plait pas : on le
# repense avec l'utilisateur avant de le recreer ici ; _on_save garde pour l'instant la mise a
# jour du preset actif).


# Onglets de la fenetre GENERALE : (libelle d'onglet, None).
SCOPES: list[tuple[str, str | None]] = [("General", None)]
# Une fenetre PAR MODULE (demande de l'utilisateur, 2026-10-28) : MEME classe, seuls ses onglets changent. Valeurs
# dans les cles generales (`md_*`, `video_*`, `board_*`, `viewer_*`). Ordre = rangee de boutons de la fenetre generale.
MODULE_SCOPES: dict[str, list[tuple[str, str | None]]] = {
    "video": [(VIDEO_TAB, None)],
    "markdown": [(MARKDOWN_TAB, None)],
    "board": [(BOARD_TAB, None), (MRO_TAB, None), (CAD_TAB, None), (DESIGN_TAB, None), (TABLEUR_TAB, None), (ILL_TAB, None), (PS_TAB, None), (PDF_TAB, None)],
    "viewer": [(VIEWER_TAB, None)],
    "font": [(TYPO_TAB, None)],             # module typographique (fm_font)
    "pdf": [(PDF_TAB, None)],               # éditeur PDF (fm_pdf ; aussi onglet de « Réglages : Board »)
    "agenda": [(AGENDA_TAB, None)],         # agenda (fm_agenda)
    "taches": [(TACHES_TAB, None)],         # tâches (fm_taches)
    "theme": [(THEME_TAB, None)],          # editeur fm_theme (pas dans la rangee de la fenetre generale)
}
MODULE_TITLES = {"video": "Vidéo", "markdown": "Markdown", "board": "Board", "viewer": "Visionneuse",
                 "font": "Typographie", "pdf": "PDF", "agenda": "Agenda", "taches": "Tâches"}
# Libelle AFFICHE d'un onglet quand il differe de son identifiant (cles retenues, tests).
TAB_LABELS = {MARKDOWN_TAB: "Module Markdown", BOARD_TAB: "Board", MRO_TAB: "MRO", CAD_TAB: "CAD", DESIGN_TAB: "Design",
              TABLEUR_TAB: "Tableur", ILL_TAB: "Illustrator", PS_TAB: "Photoshop", PDF_TAB: "PDF",
              AGENDA_TAB: "Agenda", TACHES_TAB: "Tâches"}


# ==========================================================================
# 2. Valeurs d'une portee (lecture seule)
# ==========================================================================

class ScopeValues:
    """Valeur de depart d'un reglage : les reglages courants (General et onglets a part)."""

    def __init__(self, settings: dict, title: str | None = None, name: str | None = None):
        self.settings = settings
        self.title = title
        # Nom de l'onglet dans les cles retenues (ordre des titres, espaces, styles de toggle) : « General »
        # ou un onglet de reglages generaux a part (« Markdown »).
        self.name = name or (title or "General")
        self.hooks: dict[str, Callable] = {}     # actions que la fenetre met a disposition des champs

    def seed(self, key: str, default):
        follow = BOARD_MENU_FOLLOW.get(key)
        if follow is not None and not self.settings.get(follow[0]):
            return self.settings.get(follow[1], default)     # override coupe : la valeur de l'appli
        if key in BUTTON_STATE_FOLLOW:                       # etat du bouton : override de l'etat standard
            return button_state_value(self.settings, key, default)
        return self.settings.get(key, default)

    def linked(self, key: str, default: bool = True) -> bool:
        """Etat "lie" des 4 cotes/coins. `default` n'a d'effet que si la cle `<key>_linked`
        n'existe pas dans les reglages (elle n'est pas toujours dans DEFAULT_SETTINGS)."""
        follow = BOARD_MENU_FOLLOW.get(f"{key}_linked")
        if follow is not None and not self.settings.get(follow[0]):
            return bool(self.settings.get(follow[1], default))
        if f"{key}_linked" in BUTTON_STATE_FOLLOW:
            value = button_state_value(self.settings, f"{key}_linked", None)
            return bool(default if value is None else value)
        return bool(self.settings.get(f"{key}_linked", default))


# ==========================================================================
# 3. Une fabrique par type de controle
# ==========================================================================

def _f_slider(spec: Spec, v: ScopeValues, colors: dict):
    field = _SliderField(spec.params["min"], spec.params["max"], int(v.seed(spec.key, spec.default)),
                         spec.params.get("unit", "px"),
                         slider_width=spec.params.get("width", 200), box_width=spec.params.get("box", 68),
                         scale=spec.params.get("scale", 1))
    if spec.params.get("reset") is not None:
        # Valeur d'origine : contour orange quand la valeur en diffère, double-clic sur la poignée = retour.
        field.set_reset_value(int(spec.params["reset"]))
    return field

def _f_bool(spec, v, colors):
    # Dans un tableau : le type 2, sans texte (voir AGENTS.md) ; params["toggle_style"] = autre style
    # demande expressement pour cette ligne (garde par normalize_toggles).
    style = spec.params.get("toggle_style") or "toggle2"
    toggle = _Toggle(bool(v.seed(spec.key, spec.default)), style_override=style, show_label=False)
    if style != "toggle2":
        toggle._table_style = style
    return toggle

def _shown_color_getter(key: str):
    """Couleur réellement affichée quand la valeur `key` est transparente et suit le thème (« le même ») :
    le sélecteur s'ouvre dessus au lieu du noir transparent (demande de l'utilisateur, 2026-11-11)."""
    if key.startswith("button_"):
        from fm_theme.style import button_shown_color
        return lambda: button_shown_color(key)
    if key.startswith("palette_"):
        from fm_theme.palette import shown_color
        return lambda: shown_color(key)
    return None


def _f_color_app(spec, v, colors):
    # Meme champ compact que les couleurs des invites police/bordures : app | pastille | sys.
    field = _CompactAppOrCustomColorField(v.seed(spec.key, spec.default), colors, swatch_size=20,
                                          title=spec.params.get("title", spec.label))
    field.set_effective(_shown_color_getter(spec.key))
    return field

class _CompactHeaderColor(_CompactAppOrCustomColorField):
    """Champ compact (app | pastille | sys) pour les couleurs d'entete : stocke un nom de pastille NU
    (« skinN1 »), pas « @skinN1 » comme le champ compact."""

    def __init__(self, value: str, colors: dict, title: str, parent=None):
        value = value if value.startswith("#") else "@" + value.lstrip("@")
        super().__init__(value, colors, swatch_size=20, title=title, parent=parent)

    def value(self) -> str:
        v = super().value()
        return v[1:] if v.startswith("@") else v

    def setValue(self, value: str):
        super().setValue(value if value.startswith("#") else "@" + value.lstrip("@"))


def _f_header_color(spec, v, colors):
    return _CompactHeaderColor(v.seed(spec.key, spec.default), colors, spec.params.get("title", spec.label))

LINK_CAPTION = "Lier les 4"


def _split_field(field: QWidget, parts: list) -> QWidget:
    """Redispose un champ existant en CELLULE DIVISEE : ses widgets (toggle « lier les 4 », curseurs,
    couleurs...) sont reutilises tels quels, donc ses valeurs, ses signaux et son lecteur restent ceux
    du champ ; seul l'habillage change (une sous-cellule + une legende par widget, plus de texte colle
    aux toggles). Les anciens conteneurs sont caches, pas detruits : le champ continue de s'en servir
    pour son lien « lier les 4 »."""
    layout = field.layout()
    for _caption, widgets in parts:
        for widget in widgets:
            widget.setParent(None)
    while layout.count():
        item = layout.takeAt(0)
        if item.widget() is not None:
            item.widget().hide()
    return wrap_split(SplitCell(parts), field)


def _corner_value(spec, value, lookup):
    """Rayon stocké ; None (« suit l'ancien réglage », `params["none_from"]`) = la valeur de cet ancien réglage."""
    if value is None and spec.params.get("none_from"):
        value = lookup(spec.params["none_from"])
    return _coerce_corner_radius(spec.default if value is None else value)


def _f_corners(spec, v, colors):
    field = _CornerRadiusField(v.linked(spec.key), _corner_value(spec, v.seed(spec.key, spec.default),
                                                                 lambda key: v.seed(key, 0)),
                               maximum=spec.params["max"])
    return _split_field(field, [(LINK_CAPTION, [field.toggle])] + [
        (letter, [field.sides.fields[key]]) for key, letter in _CornerRadiusSliders._ORDER])


def _f_padding(spec, v, colors):
    # params["order"] : seulement certains cotes (ex. Focus > Zone titre, « Titre - padding » sans D).
    order = spec.params.get("order") or _SidePaddingField._ORDER
    sides = v.seed(spec.key, spec.default) or {}
    # Maximum jamais sous la valeur enregistrée ou par défaut (2026-11-12 : Markdown > Page, 40 par défaut, était
    # rogné à 32 par le curseur et ENREGISTRÉ ainsi à la validation).
    values = [x for d in (sides, spec.default) if isinstance(d, dict) for x in d.values() if isinstance(x, (int, float))]
    maximum = max([spec.params.get("max", 32), *(int(x) for x in values)])
    field = _CellPaddingField(v.linked(spec.key, spec.params.get("linked_default", True)),
                              sides, order=spec.params.get("order"), maximum=maximum)
    # Côtés NON affichés (`order` partiel) : gardés tels quels et rendus à la lecture, sinon enregistrer les perdait.
    shown = {key for key, _letter in order}
    field._hidden_sides = {k: x for k, x in sides.items() if k not in shown} if isinstance(sides, dict) else {}
    return _split_field(field, [(LINK_CAPTION, [field.toggle])] + [
        (letter, [field.sides.fields[key]]) for key, letter in order])


def _f_title_padding(spec, v, colors):
    """Padding (titre) : `lier les 4 | G | H | B | D | avant | apres` — le padding de la ligne du titre
    et l'espacement avant le 1er / apres le dernier titre de sa pile (deux curseurs, meme champ que
    les autres curseurs)."""
    field = _CellPaddingField(v.linked(spec.key, spec.params.get("linked_default", True)),
                              v.seed(spec.key, spec.default) or {})
    top = spec.params.get("max", 60)
    before = _SliderField(0, top, int(v.seed(spec.params["before_key"], 0)), slider_width=60, box_width=54)
    after = _SliderField(0, top, int(v.seed(spec.params["after_key"], 0)), slider_width=60, box_width=54)
    holder = _split_field(field, [(LINK_CAPTION, [field.toggle])] + [
        (letter, [field.sides.fields[key]]) for key, letter in _SidePaddingField._ORDER]
        + [("Avant", [before]), ("Après", [after])])
    holder._v2_parts = {"before": before, "after": after}   # branches par _connect_changed, lus par le lecteur
    return holder


def _side_parts(field: _ToggleSideColorsField) -> list:
    """Sous-cellules des 4 cotes d'une bordure : le toggle du cote AU-DESSUS de sa couleur."""
    return [(letter, [field.sides.side_checks[key], field.sides.fields[key]])
            for key, letter in field.sides._ORDER]


def _f_sides(spec, v, colors):
    field = _ToggleSideColorsField(
        _coerce_side_enabled(v.seed(spec.key, spec.default)),
        v.seed(spec.params["colors_key"], {}) or {}, colors, linked=v.linked(spec.key, False))
    return _split_field(field, [(LINK_CAPTION, [field.link_toggle])] + _side_parts(field))

def _f_font(spec, v, colors):
    return _DualFontSelectField(v.seed(spec.key, "") or spec.default, width=130)


def _f_color(spec, v, colors):
    return _CompactAppOrCustomColorField(v.seed(spec.key, spec.default), colors, swatch_size=20,
                                         title=spec.params.get("title", spec.label))

def _f_ratio(spec, v, colors):
    return _SliderField(20, 500, int(round(float(v.seed(spec.key, spec.default)) * 100)), unit="%",
                        slider_width=170, box_width=68)

def _f_font_select(spec, v, colors):
    # params["auto_label"] : libelle du choix « valeur vide » quand il ne veut pas dire la police du systeme.
    return _FontSelectField(_font_choices(), v.seed(spec.key, "") or spec.default, width=170,
                            auto_label=spec.params.get("auto_label", "Systeme"))

def _f_item_text(spec, v, colors):
    return spec.params["item"].make_field(v.seed(spec.key, spec.default), colors, slider_width=170)

def _f_row_border(spec, v, colors):
    field = _RowBorderField(
        bool(v.seed("item_row_border_enabled", False)), v.seed("item_row_border_color", "@ligne"),
        int(v.seed("item_row_border_thickness", 1)), colors, thickness_range=(0, 8),
        color_factory=lambda value, cols, title: _CompactAppOrCustomColorField(value, cols, swatch_size=20,
                                                                                 title=title))
    return _split_field(field, [("Actif", [field.toggle]), ("Couleur", [field.color_field]),
                                ("Épaisseur", [field.thickness_field])])


def _gabarit_keys(spec: Spec) -> dict:
    """Noms de cles de la ligne police composite : `<prefix>_font_*` par defaut,
    surchargeables champ par champ via params["keys"] (ex. entetes : lissage
    `header_font_antialias_override`, couleur du texte de l'encart...)."""
    pre = spec.params["prefix"]
    keys = {"family": f"{pre}_font_family", "bold": f"{pre}_font_bold", "italic": f"{pre}_font_italic",
            "size": f"{pre}_font_size", "smoothing_enabled": f"{pre}_font_smoothing_enabled",
            "smoothing": f"{pre}_font_smoothing", "color": f"{pre}_font_color"}
    keys.update(spec.params.get("keys", {}))
    return keys


FONT_CAPTIONS = (("family", "Police"), ("bold", "Gras"), ("italic", "Italique"), ("size", "Hauteur"),
                 ("smoothing", "Niveau de lissage"), ("color", "Couleur"))


def _font_parts(spec, v, colors) -> dict:
    """Les 6 champs d'une ligne « police » : EXACTEMENT ceux de la reference (Titre > Polices de la
    v1) — police app/systeme, gras, italique (toggles type 2 sans texte), hauteur, niveau de lissage
    (sans titre : la legende de la colonne le porte), couleur compacte."""
    p, k = spec.params, _gabarit_keys(spec)
    low, high = p.get("size", (6, 32))
    family = _DualFontSelectField(v.seed(k["family"], "") or "Systeme", width=p.get("family_width", 150))
    bold = _Toggle(bool(v.seed(k["bold"], p.get("bold_default", True))), show_label=False, style_override="toggle2")
    italic = _Toggle(bool(v.seed(k["italic"], False)), show_label=False, style_override="toggle2")
    size = _SliderField(low, high, int(v.seed(k["size"], p.get("size_default", 10))),
                        slider_width=p.get("size_width", 110), box_width=54)
    smoothing = _OverrideSmoothingField(
        bool(v.seed(k["smoothing_enabled"], False)), v.seed(k["smoothing"], "current"), show_title=False)
    color = _CompactAppOrCustomColorField(
        v.seed(k["color"], p.get("color_default", "#d6d9dc")), colors, swatch_size=20,
        title=p.get("color_title", spec.label))
    parts = {"family": family, "bold": bold, "italic": italic, "size": size,
             "smoothing": smoothing, "color": color}
    if p.get("char_key"):                                # ligne « caractere + police » (Markdown)
        parts = {"char": _TextField(str(v.seed(p["char_key"], p.get("char_default", "")) or ""), width=56), **parts}
    return parts


def _f_offset(spec, v, colors):
    """Ligne « Décalage » (nouveau type, 2026-11-11) : X | Y, un curseur en px chacun (`params["range"]`, défaut
    -3..+3). Clés : `spec.key` (X) et `params["y_key"]` (Y)."""
    p = spec.params
    low, high = p.get("range", (-3, 3))
    parts = {name: _SliderField(low, high, int(v.seed(key, 0) or 0), slider_width=p.get("width", 90), box_width=54)
             for name, key in (("x", spec.key), ("y", p["y_key"]))}
    holder = wrap_split(SplitCell([("X", [parts["x"]]), ("Y", [parts["y"]])]))
    holder._v2_parts = parts            # lus par FIELD_READERS["offset"]
    return holder


def _f_font_gabarit(spec, v, colors):
    """Ligne « police » dans un tableau Parametre/Valeur : une cellule divisee, une sous-cellule par
    champ de la reference (POLICE, GRAS, ITALIQUE, HAUTEUR, NIVEAU DE LISSAGE, COULEUR)."""
    parts = _font_parts(spec, v, colors)
    only = spec.params.get("only")      # ex. Icone de niveaux : police | gras | lissage seulement
    if only:
        parts = {name: part for name, part in parts.items() if name in only}
    cells = [("Caractère", [parts["char"]])] if "char" in parts else []
    cells += [(spec.params.get("size_label", caption) if name == "size" else caption, [parts[name]]) for name, caption in FONT_CAPTIONS if name in parts]
    holder = wrap_split(SplitCell(cells))
    if spec.params.get("shown_color") and "color" in parts:   # transparent = « le même » : sélecteur ouvert dessus
        parts["color"].set_effective(_shown_color_getter(_gabarit_keys(spec)["color"]))
    holder._v2_parts = parts            # lus par FIELD_READERS["font_gabarit"]
    return holder

def _f_sides_thick(spec, v, colors):
    p = spec.params
    low, high = p.get("range", (0, 8))
    thickness = _SliderField(low, high, int(v.seed(p["thickness_key"], 1)), slider_width=p.get("width", 90),
                             box_width=p.get("box", 54))
    field_w = _ToggleSideColorsField(
        _coerce_side_enabled(v.seed(spec.key, spec.default)), v.seed(p["colors_key"], {}) or {}, colors,
        thickness_field=thickness, linked=v.linked(spec.key, False))
    field_w._v2_thickness = thickness      # lu par FIELD_READERS["sides_thick"]
    field_w._v2_parts = {"thickness": thickness}   # branche par _connect_changed (le champ ne relaie pas)
    return _split_field(field_w, [(LINK_CAPTION, [field_w.link_toggle])] + _side_parts(field_w)
                        + [(p.get("thickness_label", "Épaisseur"), [thickness])])

def _f_shadow(spec, v, colors):
    """Ligne « Ombres » (demande de l'utilisateur) : `lier les 4 | G | H | B | D | Couleur | Taille` — les
    toggles des cotes et « lier les 4 » de la ligne Bordures (_ToggleSideColorsField), ses couleurs par
    cote gardees cachees et pilotees par UNE couleur en fin de ligne, avant la taille."""
    p = spec.params
    low, high = p.get("range", (0, 40))
    size = _SliderField(low, high, int(v.seed(p["thickness_key"], 10)), slider_width=p.get("width", 90),
                        box_width=p.get("box", 54))
    stored = v.seed(p["colors_key"], {}) or {}
    if isinstance(stored, dict):
        first = next((stored[k] for k in ("left", "top", "bottom", "right") if stored.get(k)), None)
    else:
        first = stored
    first = first or "#8c000000"
    sides = ("left", "top", "bottom", "right")
    field_w = _ToggleSideColorsField(_coerce_side_enabled(v.seed(spec.key, spec.default)),
                                     {k: first for k in sides}, colors, thickness_field=size,
                                     linked=v.linked(spec.key, True))
    color = _CompactAppOrCustomColorField(first, colors, swatch_size=20, title=spec.label)

    def push(*_args):
        field_w.sides.setValue({k: color.value() for k in sides})      # la couleur vaut pour les 4 cotes
        field_w.changed.emit()

    def dim(*_args):
        _set_dimmed(color, not any(field_w.sidesEnabledValue().values()))

    color.changed.connect(push)
    field_w.changed.connect(dim)
    dim()
    field_w._v2_thickness = size           # lu par FIELD_READERS["shadow"]
    field_w._v2_parts = {"thickness": size, "color": color}
    toggles = [(letter, [field_w.sides.side_checks[key]]) for key, letter in field_w.sides._ORDER]
    return _split_field(field_w, [(LINK_CAPTION, [field_w.link_toggle])] + toggles
                        + [("Couleur", [color]), (p.get("thickness_label", "Taille"), [size])])


def _f_bg_fill(spec, v, colors):
    """Couleur de fond activable : cellule divisee « Actif | Couleur »."""
    p = spec.params
    toggle = _Toggle(bool(v.seed(spec.key, spec.default)), style_override="toggle2", show_label=False)
    color = _CompactAppOrCustomColorField(v.seed(p["color_key"], p["color_default"]), colors, swatch_size=20,
                                          title=p.get("title", spec.label))
    holder = wrap_split(SplitCell([("Actif", [toggle]), ("Couleur", [color])]))
    holder._v2_parts = {"enabled": toggle, "color": color}     # lus par FIELD_READERS["bg_fill"]
    return holder

def _f_inner_line(spec, v, colors):
    pre = f"{spec.params.get('prefix', 'table_inner')}_{spec.params['axis']}"   # cles <pre>_enabled / _color / _thickness
    return _InnerLineField(
        v.seed(f"{pre}_enabled", spec.default), v.seed(f"{pre}_color", "@skinN2"),
        v.seed(f"{pre}_thickness", 1), colors, spec.label)

def _f_toggle_style(spec, v, colors):
    picker = _ToggleStylePicker(v.seed(spec.key, spec.default))
    picker.style_actions = dict(v.hooks.get("toggle_actions") or {})   # clic droit sur une carte
    add = v.hooks.get("add_toggle")
    if add is not None:
        def extra(menu):
            menu.addAction("Ajouter un nouveau toggle…").triggered.connect(lambda _c=False: add())
        picker.populate_extra_menu = extra        # clic droit sur la cellule
    return picker


class _IconChoiceField(QWidget):
    """Choix d'une icone du dossier icons/ avec apercu."""

    changed = Signal()
    NONE = "(aucune)"

    def __init__(self, value: str):
        super().__init__()
        names = sorted(p.name for p in _ICONS_DIR.glob("*") if p.suffix.lower() in (".svg", ".png"))
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)
        self.select = _SelectField([self.NONE] + names, value if value in names else self.NONE, width=220)
        self.preview = QLabel()
        self.preview.setFixedSize(28, 28)
        self.preview.setAlignment(Qt.AlignCenter)
        layout.addWidget(self.select)
        layout.addWidget(self.preview)
        self.select.changed.connect(lambda _v: (self._refresh(), self.changed.emit()))
        self._refresh()

    def _refresh(self):
        pix = _toggle_icon_pixmap(self.value(), 24, M["value_fg"]) if self.value() else None
        self.preview.setPixmap(pix) if pix is not None else self.preview.clear()

    def value(self) -> str:
        return "" if self.select.value() == self.NONE else self.select.value()

    def setRadius(self, radius: int):
        self.select.setRadius(radius)


_IMAGE_FILTER = "Images (*.png *.svg *.jpg *.jpeg *.gif *.webp *.bmp)"


def _natural_key(path: str):
    """Tri « naturel » des fichiers d'une sequence (img2 avant img10)."""
    return [int(t) if t.isdigit() else t.lower() for t in re.split(r"(\d+)", path)]


class _ImageImportField(QWidget):
    """Image(s) importee(s) pour un toggle « icones » : apercu + « Importer… » + « × » (retirer).
    `multiple` : une SEQUENCE (plusieurs fichiers, tries dans l'ordre naturel de leurs noms). Les
    fichiers choisis sont copies dans data/toggle_icons/ (settings_store.import_toggle_image)."""

    changed = Signal()
    _THUMB = 24
    _MAX_THUMBS = 6

    def __init__(self, value, style_key: str, multiple: bool = False):
        super().__init__()
        self._style_key, self._multiple = style_key, multiple
        values = list(value or []) if multiple else ([value] if value else [])
        self._names: list[str] = [str(v) for v in values if v]
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(6)
        self._thumbs = QHBoxLayout()
        self._thumbs.setSpacing(3)
        layout.addLayout(self._thumbs)
        self._count = _text_label("", "row_label")
        layout.addWidget(self._count)
        pick = _Btn("Importer…", M["btn_bg"], M["btn_border"], M["btn_fg"], M["btn_hover"], height=25)
        pick.clicked.connect(self._pick)
        layout.addWidget(pick)
        clear = self._clear_btn = _Btn("×", M["btn_bg"], M["btn_border"], M["btn_fg"], M["btn_hover"], height=25,
                                       padding="0 8px")
        clear.setToolTip("Retirer")
        clear.clicked.connect(lambda _c=False: self.setNames([]))
        layout.addWidget(clear)
        self._refresh()

    def _pick(self):
        if self._multiple:
            paths, _f = QFileDialog.getOpenFileNames(self, "Importer une séquence d'images", "", _IMAGE_FILTER)
        else:
            path, _f = QFileDialog.getOpenFileName(self, "Importer une image", "", _IMAGE_FILTER)
            paths = [path] if path else []
        if paths:
            self.setFiles(paths)

    def setFiles(self, paths: list[str]):
        """Importe ces fichiers (copies dans data/toggle_icons/) et les prend comme valeur."""
        ordered = sorted(paths, key=_natural_key) if self._multiple else paths[:1]
        self.setNames([import_toggle_image(p, self._style_key) for p in ordered])

    def setNames(self, names: list[str]):
        names = [n for n in names if n]
        if names != self._names:
            self._names = names
            self._refresh()
            self.changed.emit()

    def _refresh(self):
        while self._thumbs.count():
            item = self._thumbs.takeAt(0)
            if item.widget() is not None:
                item.widget().deleteLater()
        for name in self._names[:self._MAX_THUMBS]:
            thumb = QLabel()
            thumb.setFixedSize(self._THUMB, self._THUMB)
            thumb.setAlignment(Qt.AlignCenter)
            pix = _toggle_image_pixmap(name, self._THUMB, self._THUMB)
            if pix is not None:
                thumb.setPixmap(pix)
            thumb.setToolTip(name)
            self._thumbs.addWidget(thumb)
        if self._multiple:
            n = len(self._names)
            self._count.setText("aucune" if not n else f"{n} image{'s' if n > 1 else ''}")
        else:
            self._count.setText("" if self._names else "aucune")
        self._count.setVisible(bool(self._count.text()))
        self._clear_btn.setEnabled(bool(self._names))

    def value(self):
        return list(self._names) if self._multiple else (self._names[0] if self._names else "")


def _f_toggle_icons(spec, v, colors):
    """Icones d'un toggle : cellule divisee « On | Off », une image chacune."""
    style = spec.params["style"]
    on = _ImageImportField(v.seed(spec.key, ""), style)
    off = _ImageImportField(v.seed(spec.params["off_key"], ""), style)
    holder = wrap_split(SplitCell([("On", [on]), ("Off", [off])]))
    holder._v2_parts = {"on": on, "off": off}       # branches par _connect_changed, lus par le lecteur
    return holder


def _f_toggle_image(spec, v, colors):
    """Une image choisie sur le disque (copiee dans data/toggle_icons/) : icone de la coche d'un toggle."""
    return _ImageImportField(v.seed(spec.key, "") or "", spec.params["style"])


def _f_image_sequence(spec, v, colors):
    return _ImageImportField(v.seed(spec.key, []) or [], spec.params["style"], multiple=True)


TOGGLE_KINDS = (("qt", "Qt"), ("icons", "Icônes"))
TOGGLE_MOTIONS = (("slide", "Glissière"), ("fade", "Fondu (centrée)"))


def _choice_factory(choices):
    def factory(spec, v, colors):
        current = dict(choices).get(v.seed(spec.key, spec.default), choices[0][1])
        return _SelectField([label for _k, label in choices], current, width=160)
    return factory


def _choice_reader(choices):
    return lambda sp, w: {sp.key: {label: key for key, label in choices}[w.value()]}


def _f_choice(spec, v, colors):
    """Liste de choix GENERIQUE : `params["choices"]` = ((valeur, libelle), …) (ou un appelable qui les rend)."""
    choices = spec.params["choices"]
    choices = choices() if callable(choices) else choices
    current = v.seed(spec.key, spec.default)
    labels = [label for _k, label in choices] or [str(current)]
    field = _SelectField(labels, dict(choices).get(current, labels[0]), width=spec.params.get("width", 200))
    field._choices = tuple(choices)
    return field


def _f_state_follow(spec, v, colors):
    """Ligne « suit » d'un état du bouton : liste (Standard / les autres états) + « Réinitialiser » (variante windows_95
    du bouton, de la hauteur de la liste) ; branchés par `_link_state_follow`."""
    choices = tuple((key, text) for key, text in BUTTON_FOLLOW_CHOICES if key != spec.params["state"])
    current = v.seed(spec.key, spec.default) or "standard"
    select = _SelectField([text for _k, text in choices], dict(choices).get(current, choices[0][1]), width=130)
    select._choices = choices
    reset = QPushButton("Réinitialiser")
    reset.setToolTip("Donne à cet état exactement l'aspect de l'état choisi dans la liste (toutes ses lignes)")
    reset.setFocusPolicy(Qt.NoFocus)
    reset.setFixedHeight(select.height())           # même hauteur que la liste (demande de l'utilisateur)
    from fm_theme.style import style_variant_button  # variante windows_95 du preset lié (demande de l'utilisateur)
    from settings_store import theme_variant_values
    style_variant_button(reset, theme_variant_values(v.settings, "bouton", "windows_95"))
    holder = QWidget()
    holder.setStyleSheet("background: transparent;")
    box = QHBoxLayout(holder)
    box.setContentsMargins(0, 0, 0, 0)
    box.setSpacing(8)
    box.addWidget(select, 0, Qt.AlignVCenter)
    box.addWidget(reset, 0, Qt.AlignVCenter)
    holder._v2_follow, holder._v2_reset = select, reset
    holder._v2_parts = {"follow": select}           # branché par _connect_changed (signal `changed`)
    return holder


def _state_copy_button() -> QPushButton:
    """Petit bouton à icône devant le titre d'une ligne d'état du bouton : la ligne prend celle de l'état choisi dans
    la liste « suit » de son état, surchargée donc modifiable (demande de l'utilisateur, 2026-11-12). Aspect : fm_theme
    (bouton compact), icône `icons/copier.svg` à la couleur du texte des boutons."""
    from fm_theme.style import painted_button_look, theme_button
    from fm_theme.widgets import _toggle_icon_pixmap
    button = QPushButton()
    button.setToolTip("Copier cette ligne de l'état choisi dans « suit »")
    button.setFocusPolicy(Qt.NoFocus)
    button.setFixedSize(20, 20)
    pix = _toggle_icon_pixmap("copier.svg", 14, painted_button_look()["fg"].name())   # 14 px (demande, 2026-11-12)
    if pix is not None:
        button.setIcon(QIcon(pix))
        button.setIconSize(QSize(14, 14))
    return theme_button(button, compact=True)


def _w_state_follow(spec, w, v) -> bool:
    text = dict(w._v2_follow._choices).get(v[spec.key] or "standard", w._v2_follow._choices[0][1])
    if w._v2_follow.value() != text:
        w._v2_follow.setValue(text)
    return True


def _r_choice(sp, w):
    return {sp.key: {label: key for key, label in getattr(w, "_choices", ())}.get(w.value(), w.value())}


SKINS = (("none", "Aucun"), ("text", "Texte"), ("icon", "Icône"))


def _f_coche_skin(spec, v, colors):
    current = dict(SKINS).get(v.seed(spec.key, spec.default), "Aucun")
    return _SelectField([label for _k, label in SKINS], current, width=140)


def _f_text(spec, v, colors):
    return _TextField(str(v.seed(spec.key, spec.default) or ""))


def _f_icon_choice(spec, v, colors):
    """Icone d'un fichier de `icons/` : cellule divisee « Icône (apercu) | Fichier (liste) »."""
    field = _IconChoiceField(str(v.seed(spec.key, spec.default) or ""))
    return _split_field(field, [("Icône", [field.preview]), ("Fichier", [field.select])])


def _f_badge_position(spec, v, colors):
    return _ResizeBadgePositionField(
        v.seed("resize_badge_position", "bottom_right"), int(v.seed("resize_badge_offset_x", 8)),
        int(v.seed("resize_badge_offset_y", 8)))

def _f_ratio_slider(spec, v, colors):
    return _RatioSliderField(20, 500, int(round(float(v.seed(spec.key, spec.default)) * 100)),
                             slider_width=200, box_width=68)


# -- Sections reprises de la v1 (Application, Polices principales, Couleurs, Geometrie, ICONES,
# Focus > Zone titre / Bouton repliement, Projets > Icone de niveaux) --

WINDOW_RADIUS_ON = 12          # Application > Coins arrondis : rayon de la fenetre principale quand actif
NO_PRESET = "(Aucun)"
COLLAPSE_MODES = (("chevrons", "Chevrons"), ("icone", "Icone"))


def _f_shortcut(spec, v, colors):
    return _ShortcutField(str(v.seed(spec.key, spec.default) or ""))


def _f_root_path(spec, v, colors):
    return RootPathField(str(v.seed(spec.key, spec.default) or ""))


class _MarkdownCssPathField(RootPathField):
    """Reglages > Markdown > CSS : feuille chargee par le module (par ex. un extrait CSS d'Obsidian) + export d'une
    feuille pour Obsidian d'apres les reglages de l'onglet. L'etat (chargee / introuvable -> style integre) est
    affiche a cote. Aucun fichier de l'utilisateur n'est jamais modifie : l'export refuse de remplacer une feuille
    qu'il n'a pas produite."""

    EXPORT_NAME = "pipeline-browser.css"

    def __init__(self, path):
        super().__init__(path)
        self.edit.setPlaceholderText("Aucune feuille : style intégré")
        self.setToolTip("Feuille CSS PARTAGÉE avec Obsidian (par ex. un extrait CSS de votre coffre).\n"
                        "Les réglages de cet onglet y sont écrits (bloc « pipeline-browser:sync » à la fin du fichier) ;\n"
                        "le reste du fichier n'est jamais modifié. Une modification faite dans Obsidian est reprise ici.\n"
                        "Hors de ce bloc, la feuille passe avant les réglages pour ce qu'elle définit.\n"
                        "Elle ne peut pas modifier le fonctionnement de l'éditeur (saisie, défilement, barres).\n"
                        "Absente ou illisible : le style intégré est utilisé. Vide = style intégré.")
        layout = self.layout()
        export = _settings_button("Exporter pour Obsidian…")
        export.setToolTip("Écrit une feuille CSS pour Obsidian (dossier .obsidian/snippets d'un coffre) d'après les\n"
                          "réglages de cet onglet, y compris ceux pas encore enregistrés.")
        export.clicked.connect(self._export)
        layout.insertWidget(layout.count() - 1, export)
        save_as = _settings_button("Enregistrer sous…")
        save_as.setToolTip("Enregistre une copie de la feuille CSS actuellement chargée, puis sélectionne cette copie.")
        save_as.clicked.connect(self._save_as)
        layout.insertWidget(layout.count() - 1, save_as)
        self.status = _text_label("", "note")
        layout.insertWidget(layout.count() - 1, self.status)
        self.edit.textChanged.connect(lambda _t: self._refresh_status())
        from fm_markdown import css_sync
        css_sync.engine().statusChanged.connect(self._on_sync_status)
        self._refresh_status()

    def _on_sync_status(self, _text: str):
        try:
            self._refresh_status()
        except RuntimeError:                    # champ detruit (fenetre refaite) : plus suivi
            from fm_markdown import css_sync
            try:
                css_sync.engine().statusChanged.disconnect(self._on_sync_status)
            except (RuntimeError, TypeError):
                pass

    def _refresh_status(self, note: str = ""):
        from fm_markdown import css_sync, style as md_style
        path, status = md_style.user_css({"md_css_path": self.edit.text()})
        sync = css_sync.engine()
        synced = path is not None and sync.path == path
        self.status.setText(note or ("✓ " + path.name + (" · synchronisée" if synced else "") if path is not None else
                                     ("" if not self.edit.text().strip() else "⚠ style intégré")))
        self.status.setToolTip(status + ("\n" + sync.status if synced and sync.status else ""))

    def _browse(self):
        chosen, _ = QFileDialog.getOpenFileName(self, "Choisir une feuille CSS", self.edit.text(),
                                                 "Feuilles CSS (*.css);;Tous les fichiers (*)")
        if chosen:
            self.edit.setText(chosen)

    def _export_dir(self) -> str:
        """Dossier propose : les extraits du coffre de la feuille choisie, sinon son dossier, sinon les Documents."""
        current = Path(self.edit.text().strip() or ".")
        for folder in (current.parent, *current.parents):
            if folder.name == "snippets" and folder.parent.name == ".obsidian":
                return str(folder)
            if (folder / ".obsidian" / "snippets").is_dir():
                return str(folder / ".obsidian" / "snippets")
        if current.parent.is_dir() and current.is_absolute():
            return str(current.parent)
        return str(Path.home() / "Documents")

    def _export(self):
        from fm_markdown import style as md_style
        window = self.window()
        values = window.current_values() if hasattr(window, "current_values") else {}
        if not values:
            from fm_markdown import pane as md_pane
            values = md_pane._settings()
        target, _ = QFileDialog.getSaveFileName(self, "Exporter la feuille pour Obsidian",
                                                str(Path(self._export_dir()) / self.EXPORT_NAME),
                                                "Feuilles CSS (*.css)")
        if not target:
            return
        try:
            md_style.export_obsidian_css(values, Path(target))
        except (OSError, ValueError) as exc:
            self._refresh_status("⚠ export refusé")
            self.status.setToolTip(str(exc))
            return
        self._refresh_status(f"✓ exporté : {Path(target).name}")
        self.status.setToolTip(str(target))

    def _save_as(self):
        from fm_markdown import style as md_style
        source, _ = md_style.user_css({"md_css_path": self.edit.text()})
        if source is not None:
            suggested = source
        else:
            suggested = Path(self._export_dir()) / (self.EXPORT_NAME)
        target, _ = QFileDialog.getSaveFileName(self, "Enregistrer la feuille CSS sous…", str(suggested),
                                                "Feuilles CSS (*.css)")
        if not target:
            return
        destination = Path(target)
        if destination.suffix.lower() != ".css":
            destination = destination.with_suffix(".css")
        try:
            if source is not None:
                import shutil
                if source.resolve() != destination.resolve():
                    shutil.copy2(source, destination)
            else:
                window = self.window()
                values = window.current_values() if hasattr(window, "current_values") else {}
                if not values:
                    from fm_markdown import pane as md_pane
                    values = md_pane._settings()
                md_style.export_obsidian_css(values, destination)
        except (OSError, ValueError) as exc:
            self._refresh_status("⚠ enregistrement refusé")
            self.status.setToolTip(str(exc))
            return
        self.edit.setText(str(destination))
        self._refresh_status(f"✓ enregistré : {destination.name}")
        self.status.setToolTip(str(destination))


class _CadPgpPathField(RootPathField):
    """Reglages > Module CAD > Raccourcis clavier : fichier .pgp d'AutoCAD (alias de commandes) lu par le CAD
    (`fm_cad/cad_aliases.py`). Etat a cote (alias actifs / prevus / sans equivalent), correspondance complete en
    info-bulle. Le fichier de l'utilisateur n'est jamais modifie."""

    def __init__(self, path):
        super().__init__(path)
        self.edit.setPlaceholderText("Aucun fichier : alias d'origine")
        self.setToolTip("Fichier d'alias d'AutoCAD (acad.pgp : « L, *LIGNE »). Ce que l'on tape à « Commande : » dans\n"
                        "le CAD : les alias du fichier passent avant ceux d'origine. Une commande pas encore\n"
                        "disponible garde son alias (elle l'annonce) ; une commande sans équivalent est ignorée.\n"
                        "Le fichier est relu quand il change.")
        self.status = _text_label("", "note")
        layout = self.layout()
        layout.insertWidget(layout.count() - 1, self.status)
        clear = _settings_button("Retirer")
        clear.setToolTip("N'utiliser que les alias d'origine.")
        clear.clicked.connect(lambda: self.edit.setText(""))
        layout.insertWidget(layout.count() - 1, clear)
        self.edit.textChanged.connect(lambda _t: self._refresh_status())
        self._refresh_status()

    def _refresh_status(self):
        path = self.edit.text().strip()
        if not path:
            self.status.setText("")
            self.status.setToolTip("")
            return
        try:
            from fm_cad import cad_aliases
        except Exception:                                   # noqa: BLE001 - paquet absent
            return
        loaded = cad_aliases.load(path)
        self.status.setText(loaded.summary())
        self.status.setToolTip(loaded.report())

    def _browse(self):
        chosen, _ = QFileDialog.getOpenFileName(self, "Choisir un fichier d'alias (.pgp)", self.edit.text(),
                                                 "Fichiers d'alias AutoCAD (*.pgp);;Tous les fichiers (*)")
        if chosen:
            self.edit.setText(chosen)


def _f_cad_pgp_path(spec, v, colors):
    return _CadPgpPathField(str(v.seed(spec.key, spec.default) or ""))


def _f_md_css_path(spec, v, colors):
    return _MarkdownCssPathField(str(v.seed(spec.key, spec.default) or ""))


def _f_preset(spec, v, colors):
    import settings_store                       # liste des presets = celle de fm_theme (aucun au lancement : le dernier actif)
    names = [NO_PRESET] + settings_store.preset_names()
    current = v.seed(spec.key, "") or NO_PRESET
    return _SelectField(names, current if current in names else NO_PRESET, width=268)


def _f_window_radius(spec, v, colors):
    return _Toggle(int(v.seed(spec.key, 0) or 0) > 0, style_override="toggle2", show_label=False)


def _f_omit_list(spec, v, colors):
    field = _OmitListField()
    field.set_values(_omit_file_values(v.settings) if spec.params.get("files") else v.seed(spec.key, []))
    if spec.params.get("files"):
        field.setToolTip("Nom exact de fichier, ou *.extension pour masquer toute une extension.")
    return field


def _f_lut_images(spec, v, colors):
    """Images de test des LUT : explications puis la liste (+ / - / Par defaut, apercu converti)."""
    field = LutTestImagesField()
    field.set_values(v.seed(spec.key, []), v.seed("lut_default_image", "") or "", v.seed("lut_image_curves", {}))
    holder = QWidget()
    holder.setStyleSheet("background: transparent;")
    lay = QVBoxLayout(holder)
    lay.setContentsMargins(0, 0, 0, 0)
    lay.setSpacing(10)
    help_label = _text_label(LUT_HELP_TEXT, "note")
    help_label.setWordWrap(True)
    help_label.setFixedWidth(LutTestImagesField._WIDTH)
    lay.addWidget(help_label, 0, Qt.AlignLeft)
    lay.addWidget(field, 0, Qt.AlignLeft)
    holder._v2_parts = {"images": field}       # lu par FIELD_READERS["lut_images"], branche par _connect_changed
    return holder


def _f_font_role(spec, v, colors):
    """Polices principales : une cellule divisee « Police | Lissage | Apercu » par role."""
    field = FontRoleField(v.seed(spec.key, {}) or {}, spec.params["role"], spec.params["sample"])
    holder = wrap_split(SplitCell([("Police", [field.family]), ("Lissage", [field.smoothing]),
                                   ("Aperçu", [field.preview])]))
    holder._v2_parts = {"role": field}
    return holder


def _f_semantic_color(spec, v, colors):
    """Couleurs : une pastille de la palette. Deux pastilles peuvent piloter la meme cle (« Selection
    en cours » et « Bouton » = accent) : elles restent synchronisees quand elles partagent encore une
    cle, mais les couleurs « skin - accent » et « Item - sélectionné-focus » sont independantes."""
    real_key = spec.params["real_key"]
    field = SemanticColorField(colors.get(real_key, "#000000"), spec.label)
    siblings = v.hooks.setdefault("color_slots", {}).setdefault(real_key, [])
    for other in siblings:
        try:
            field.changed.connect(lambda o=other, f=field: o.setValue(f.value()))
            other.changed.connect(lambda o=other, f=field: f.setValue(o.value()))
        except RuntimeError:
            pass
    siblings.append(field)
    return field


def _f_frame_radius(spec, v, colors):
    """Geometrie : « Cadre | Coins arrondis » d'un type d'element (zones de saisie, boutons)."""
    frame = _Toggle(bool(v.seed(spec.key, True)), style_override="toggle2", show_label=False)
    radius = _SliderField(0, 16, int(v.seed(spec.params["radius_key"], 0)), slider_width=140, box_width=58)
    holder = wrap_split(SplitCell([("Cadre", [frame]), ("Coins arrondis", [radius])]))
    holder._v2_parts = {"frame": frame, "radius": radius}
    return holder


def _f_color_pair(spec, v, colors):
    """Icone de niveaux : couleurs d'une base, « Texte | Fond »."""
    p = spec.params
    text = _CompactAppOrCustomColorField(v.seed(spec.key, p["text_default"]), colors, swatch_size=20,
                                         title=f"Texte - {spec.label}")
    back = _CompactAppOrCustomColorField(v.seed(p["bg_key"], p["bg_default"]), colors, swatch_size=20,
                                         title=f"Fond - {spec.label}")
    holder = wrap_split(SplitCell([("Texte", [text]), ("Fond", [back])]))
    holder._v2_parts = {"text": text, "bg": back}
    return holder


def _align_state_pairs(fields: dict):
    """Lignes « Fond | Coche » d'un tableau : chaque sous-cellule a au moins la largeur de la plus large de sa
    colonne, la frontiere Fond | Coche tombe au meme endroit sur toutes les lignes (largeurs reglees a la main
    inchangees)."""
    rows = list({id(w): w for w in fields.values() if isinstance(w, _StatePairField)}.values())
    if len(rows) < 2:
        return
    splits = [row.findChild(SplitCell) for row in rows]
    for index in range(len(splits[0]._cells)):
        width = max(max(sp._cells[index].sizeHint().width(), sp._cap_labels[index].sizeHint().width())
                    for sp in splits)
        for sp in splits:
            sp._cells[index].setMinimumWidth(width)


class _StatePairField(QWidget):
    """Ligne « Fond | Coche » d'un tableau d'etat de toggle (`_state_pair`) : une sous-cellule par partie, son
    champ habituel dedans (vide si la partie n'a pas ce reglage). `parts` : [(spec, champ)]."""

    changed = Signal()

    def __init__(self, spec, v, colors):
        super().__init__()
        self.parts = []
        cells = []
        for caption, sub in spec.params["parts"]:
            widget = QWidget()
            if sub is not None:
                widget = FIELD_FACTORIES[sub.kind](sub, v, colors)
                widget._row_kind = sub.kind
                _connect_changed(widget, self.changed.emit)
                self.parts.append((sub, widget))
            cells.append((caption, [widget]))
        # wrap_split sans sa feuille de style (« transparent ») : un QWidget simple ne peint deja pas de fond, et
        # une feuille de style propre fait repolir tout le contenu a chaque reparentage (~10 ms par ligne).
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        self._split = SplitCell(cells, self)
        layout.addWidget(self._split)
        self._fill_cell = True

    def field(self, key: str) -> QWidget:
        """Le champ d'une sous-cellule, par une de ses cles."""
        return next(w for sub, w in self.parts if key in (sub.key, *sub.extra_keys))


class _SnapSideField(_StatePairField):
    """« Clipsée : comportement du côté collé » : le menu, et la couleur dans la sous-cellule voisine, montrée
    seulement au choix « 3. Couleur de bordure » (Barres d'outils > Barre)."""

    def __init__(self, spec, v, colors):
        super().__init__(spec, v, colors)
        self._menu = next(w for sub, w in self.parts if sub.kind == "choice")
        self._color = next(w for sub, w in self.parts if sub.kind != "choice")
        self._menu.changed.connect(lambda *_a: self._sync())
        self._sync()

    def _sync(self):
        label = dict(getattr(self._menu, "_choices", ())).get("color")
        self._color.setVisible(self._menu.value() == label)


def _f_xy(spec, v, colors):
    """Deux curseurs sur une ligne (position X / Y, largeur / hauteur) : cellule divisee."""
    p = spec.params
    low, high = p["range"]
    first = _SliderField(low, high, int(v.seed(spec.key, p["defaults"][0])), slider_width=140, box_width=58)
    second = _SliderField(low, high, int(v.seed(p["second_key"], p["defaults"][1])), slider_width=140, box_width=58)
    holder = wrap_split(SplitCell([(p["captions"][0], [first]), (p["captions"][1], [second])]))
    holder._v2_parts = {"first": first, "second": second}
    return holder


def _f_ui_icon(spec, v, colors):
    """Cellule divisee « Icône (apercu de l'icone en cours) | Choix (changer / capturer / reinitialiser) » ; la punaise
    a deux etats : une paire de sous-cellules chacun."""
    field = UiIconField(spec.params["ui_key"])
    parts = []
    for caption, avatar, buttons, _state in field.states():
        parts += [(caption or "Icône", [avatar]), ("Choix", [buttons])]
    holder = wrap_split(SplitCell(parts))
    holder._ui_icon_field = field          # garde le champ en vie : ses boutons lui sont relies
    return holder


def _f_color_mark(spec, v, colors):
    """Une ligne : opacite (%) | bordure (toggle seul dans sa sous-cellule : type 1) | epaisseur."""
    p = spec.params
    opacity = _SliderField(0, 100, int(v.seed(spec.key, spec.default)), unit="%", slider_width=110, box_width=58)
    border = _Toggle(bool(v.seed(p["border_key"], False)), show_label=False)
    thickness = _SliderField(1, 12, int(v.seed(p["thickness_key"], 2)), slider_width=90, box_width=54)
    holder = wrap_split(SplitCell([("Opacité", [opacity]), ("Bordure", [border]), ("Épaisseur", [thickness])]))
    holder._v2_parts = {"opacity": opacity, "border": border, "thickness": thickness}
    return holder


LINE_PATTERN_CHOICES = (("solid", "Normal"), ("dash", "Pointillés"), ("dot", "Points"))


def _f_line_pattern(spec, v, colors):
    """Type de ligne d'un cadre : cellule divisee « Type (Normal / Pointillés / Points) | Échelle (%) »."""
    current = v.seed(spec.key, spec.default)
    labels = [label for _k, label in LINE_PATTERN_CHOICES]
    kind = _SelectField(labels, dict(LINE_PATTERN_CHOICES).get(current, labels[0]), width=140)
    scale = _SliderField(10, 1000, int(v.seed(spec.params["scale_key"], 100)), unit="%", slider_width=140,
                         box_width=62)
    holder = wrap_split(SplitCell([("Type", [kind]), ("Échelle", [scale])]))
    holder._v2_parts = {"kind": kind, "scale": scale}           # lus par FIELD_READERS["line_pattern"]
    return holder


def _f_cad_linetypes(spec, v, colors):
    from fm_cad.cad_linetype_ui import LinetypesField    # paquet du board : charge a la demande
    return LinetypesField(v.seed(spec.key, spec.default))


def _f_logiciels(spec, v, colors):
    return LogicielsField(v.seed("custom_softwares", []), v.seed("removed_softwares", []))


FIELD_FACTORIES: dict[str, Callable] = {
    "md_css_path": _f_md_css_path, "cad_pgp_path": _f_cad_pgp_path, "choice": _f_choice,
    "root_path": _f_root_path, "shortcut": _f_shortcut, "preset": _f_preset, "window_radius": _f_window_radius, "omit_list": _f_omit_list,
    "extension_list": _f_extension_list, "md_open_md": _choice_factory(MD_OPEN_MD),
    "md_mode": _choice_factory(MD_MODES), "md_align": _choice_factory(MD_ALIGN),
    "lut_images": _f_lut_images, "font_role": _f_font_role, "semantic_color": _f_semantic_color,
    "frame_radius": _f_frame_radius, "color_pair": _f_color_pair, "xy": _f_xy, "ui_icon": _f_ui_icon,
    "logiciels": _f_logiciels, "cad_linetypes": _f_cad_linetypes, "collapse_mode": _choice_factory(COLLAPSE_MODES),
    "coche_skin": _f_coche_skin, "text": _f_text, "icon_choice": _f_icon_choice,
    "toggle_kind": _choice_factory(TOGGLE_KINDS), "toggle_motion": _choice_factory(TOGGLE_MOTIONS),
    "toggle_icons": _f_toggle_icons, "image_sequence": _f_image_sequence, "toggle_image": _f_toggle_image,
    "state_pair": _StatePairField,
    # Meme cellule divisee (un champ par sous-cellule, `params["parts"]`), avec SON gabarit de ligne : celui des
    # lignes « Fond | Coche » ne s'y applique pas (lignes des guides du Magnetisme, fm_board/settings.py).
    "split_fields": _StatePairField,
    "snap_side": _SnapSideField,
    "badge_position": _f_badge_position, "ratio_slider": _f_ratio_slider,
    "font_gabarit": _f_font_gabarit, "sides_thick": _f_sides_thick, "shadow": _f_shadow, "inner_line": _f_inner_line,
    "toggle_style": _f_toggle_style, "bg_fill": _f_bg_fill,
    "color": _f_color, "ratio": _f_ratio, "font_select": _f_font_select, "item_text": _f_item_text,
    "row_border": _f_row_border,
    "slider": _f_slider, "bool": _f_bool, "color_app": _f_color_app, "header_color": _f_header_color,
    "color_mark": _f_color_mark, "line_pattern": _f_line_pattern,
    "corners": _f_corners, "padding": _f_padding, "title_padding": _f_title_padding, "sides": _f_sides, "font": _f_font,
}
# Champs d'actions de l'agenda (comptes Google, données locales) : definis dans leur paquet.
from fm_agenda.settings import FIELD_FACTORIES as _AGENDA_FACTORIES, FIELD_READERS as _AGENDA_READERS  # noqa: E402
FIELD_FACTORIES.update(_AGENDA_FACTORIES)
from fm_taches.settings import FIELD_FACTORIES as _TACHES_FACTORIES, FIELD_READERS as _TACHES_READERS  # noqa: E402
FIELD_FACTORIES.update(_TACHES_FACTORIES)
FIELD_FACTORIES["offset"] = _f_offset
FIELD_FACTORIES["state_follow"] = _f_state_follow


# ==========================================================================
# 3 bis. Les lecteurs : le pendant de chaque fabrique (widget -> valeurs)
# ==========================================================================
# Meme regles que SettingsWindow._current_values (verifie par
# tests/test_settings_window_v2.py, qui compare les deux au bit pres).

def _font_value(w) -> str:
    return "" if w.value() == "Systeme" else w.value()


def _r_font_gabarit(spec, w) -> dict:
    k, parts = _gabarit_keys(spec), w._v2_parts
    out = {}
    if "char" in parts:
        out[spec.params["char_key"]] = parts["char"].text()
    if "family" in parts:
        out[k["family"]] = _font_value(parts["family"])
    for name in ("bold", "italic"):
        if name in parts:
            out[k[name]] = parts[name].isChecked()
    if "size" in parts:
        out[k["size"]] = parts["size"].value()
    if "smoothing" in parts:
        out[k["smoothing_enabled"]] = parts["smoothing"].isChecked()
        out[k["smoothing"]] = parts["smoothing"].smoothingValue()
    if "color" in parts:
        out[k["color"]] = parts["color"].value()
    return out


def _r_lut_images(spec, w) -> dict:
    field = w._v2_parts["images"]
    return {spec.key: field.values(), "lut_default_image": field.default(), "lut_image_curves": field.curves()}


FIELD_READERS: dict[str, Callable] = {
    "md_css_path": lambda sp, w: {sp.key: w.text().strip()},
    "cad_pgp_path": lambda sp, w: {sp.key: w.text().strip()},
    "root_path": lambda sp, w: {sp.key: w.text().strip() or sp.default},
    "shortcut": lambda sp, w: {sp.key: w.value()},
    "preset": lambda sp, w: {sp.key: "" if w.value() == NO_PRESET else w.value()},
    "window_radius": lambda sp, w: {sp.key: WINDOW_RADIUS_ON if w.isChecked() else 0},
    "omit_list": lambda sp, w: {sp.key: w.values(), **({"application_omit_extensions": []}
                                                         if sp.params.get("files") else {})},
    "lut_images": _r_lut_images,
    "extension_list": lambda sp, w: {sp.key: _normalized_extensions(w.values())},
    "choice": _r_choice,
    "md_open_md": _choice_reader(MD_OPEN_MD), "md_mode": _choice_reader(MD_MODES),
    "md_align": _choice_reader(MD_ALIGN),
    "font_role": lambda sp, w: {sp.key: w._v2_parts["role"].value()},
    # Couleurs : cle « colors:<cle reelle> », fondue dans le dictionnaire `colors` (wired_values).
    "semantic_color": lambda sp, w: {f"colors:{sp.params['real_key']}": w.value()},
    "frame_radius": lambda sp, w: {sp.key: w._v2_parts["frame"].isChecked(),
                                   sp.params["radius_key"]: w._v2_parts["radius"].value()},
    "color_pair": lambda sp, w: {sp.key: w._v2_parts["text"].value(), sp.params["bg_key"]: w._v2_parts["bg"].value()},
    "xy": lambda sp, w: {sp.key: w._v2_parts["first"].value(), sp.params["second_key"]: w._v2_parts["second"].value()},
    "ui_icon": lambda sp, w: {},                 # agit tout de suite sur les fichiers d'icone
    "logiciels": lambda sp, w: w.values(),
    "cad_linetypes": lambda sp, w: {sp.key: w.values()},
    "line_pattern": lambda sp, w: {
        sp.key: {label: key for key, label in LINE_PATTERN_CHOICES}.get(w._v2_parts["kind"].value(), "solid"),
        sp.params["scale_key"]: w._v2_parts["scale"].value()},
    "collapse_mode": _choice_reader(COLLAPSE_MODES),
    "coche_skin": lambda sp, w: {sp.key: {label: key for key, label in SKINS}[w.value()]},
    "toggle_kind": _choice_reader(TOGGLE_KINDS), "toggle_motion": _choice_reader(TOGGLE_MOTIONS),
    "toggle_icons": lambda sp, w: {sp.key: w._v2_parts["on"].value(),
                                   sp.params["off_key"]: w._v2_parts["off"].value()},
    "image_sequence": lambda sp, w: {sp.key: w.value()},
    "toggle_image": lambda sp, w: {sp.key: w.value()},
    "state_pair": lambda sp, w: {k: val for sub, f in w.parts for k, val in read_spec(sub, f).items()},
    "split_fields": lambda sp, w: {k: val for sub, f in w.parts for k, val in read_spec(sub, f).items()},
    "snap_side": lambda sp, w: {k: val for sub, f in w.parts for k, val in read_spec(sub, f).items()},
    "text": lambda sp, w: {sp.key: w.text()},
    "icon_choice": lambda sp, w: {sp.key: w.value()},
    "badge_position": lambda sp, w: {
        "resize_badge_position": w.position(), "resize_badge_offset_x": w.offsetX(),
        "resize_badge_offset_y": w.offsetY()},
    "ratio_slider": lambda sp, w: {sp.key: w.value() / 100.0},
    "slider": lambda sp, w: {sp.key: w.value()},
    "ratio": lambda sp, w: {sp.key: w.value() / 100.0},
    "bool": lambda sp, w: {sp.key: w.isChecked()},
    "color": lambda sp, w: {sp.key: w.value()},
    "color_app": lambda sp, w: {sp.key: w.value()},
    "header_color": lambda sp, w: {sp.key: w.value()},
    "toggle_style": lambda sp, w: {sp.key: w.value()},
    "bg_fill": lambda sp, w: {sp.key: w._v2_parts["enabled"].isChecked(),
                              sp.params["color_key"]: w._v2_parts["color"].value()},
    "font":lambda sp, w: {sp.key: _font_value(w)},
    "font_select": lambda sp, w: {sp.key: _font_value(w)},
    "corners": lambda sp, w: {sp.key: w.cornersValue(), f"{sp.key}_linked": w.isLinked()},
    "padding": lambda sp, w: {sp.key: {**getattr(w, "_hidden_sides", {}), **w.sidesValue()},
                              f"{sp.key}_linked": w.isLinked()},
    "title_padding": lambda sp, w: {sp.key: w.sidesValue(), f"{sp.key}_linked": w.isLinked(),
                                    sp.params["before_key"]: w._v2_parts["before"].value(),
                                    sp.params["after_key"]: w._v2_parts["after"].value()},
    "sides": lambda sp, w: {sp.key: w.sidesEnabledValue(), sp.params["colors_key"]: w.sidesValue(),
                            f"{sp.key}_linked": w.isLinked()},
    "sides_thick": lambda sp, w: {
        sp.key: w.sidesEnabledValue(), sp.params["colors_key"]: w.sidesValue(), f"{sp.key}_linked": w.isLinked(),
        sp.params["thickness_key"]: w._v2_thickness.value()},
    "shadow": lambda sp, w: {
        sp.key: w.sidesEnabledValue(), sp.params["colors_key"]: w.sidesValue(), f"{sp.key}_linked": w.isLinked(),
        sp.params["thickness_key"]: w._v2_thickness.value()},
    "inner_line": lambda sp, w: dict(zip(
        (f"{sp.params.get('prefix', 'table_inner')}_{sp.params['axis']}_{k}" for k in ("enabled", "color", "thickness")),
        w.value())),
    "row_border": lambda sp, w: {
        "item_row_border_enabled": w.enabledValue(), "item_row_border_color": w.colorValue(),
        "item_row_border_thickness": w.thicknessValue()},
    "item_text": lambda sp, w: {sp.key: sp.params["item"].raw_value(w)},
    "font_gabarit": _r_font_gabarit,
    "color_mark": lambda sp, w: {sp.key: w._v2_parts["opacity"].value(),
                                 sp.params["border_key"]: w._v2_parts["border"].isChecked(),
                                 sp.params["thickness_key"]: w._v2_parts["thickness"].value()},
}
FIELD_READERS.update(_AGENDA_READERS)
FIELD_READERS.update(_TACHES_READERS)
FIELD_READERS["offset"] = lambda sp, w: {sp.key: w._v2_parts["x"].value(), sp.params["y_key"]: w._v2_parts["y"].value()}
FIELD_READERS["state_follow"] = lambda sp, w: {
    sp.key: {text: key for key, text in w._v2_follow._choices}.get(w._v2_follow.value(), "standard")}


def read_spec(spec: Spec, widget: QWidget) -> dict:
    out = FIELD_READERS[spec.kind](spec, widget)
    toggle = getattr(widget, "_v2_active", None)
    if toggle is not None:                  # toggle « activer » de la ligne : coupé = valeurs neutres
        flag, kept = activation_keys(spec)
        if toggle.isChecked():
            out[flag], out[kept] = True, None
        else:
            out[kept] = json.loads(json.dumps(out))
            out.update(_neutral_values(spec, out))
            out[flag] = False
    override = getattr(widget, "_v2_override", None)
    if override is not None:                # toggle d'override devant la ligne (états du bouton)
        out[spec.params["override"][0]] = override.isChecked()
    return out


# -- Toggle « activer » des lignes Bordures, Border radius, Ombres, Padding, Margin (toggle 1 juste à droite du
# titre ; demande de l'utilisateur, 2026-11-11). Coupé : les clés RÉELLES reçoivent la valeur neutre (aucun côté,
# rayons / marges à 0), donc tout ce qui lit ces réglages (appli, modules) voit l'effet coupé sans rien changer ;
# les valeurs réglées sont gardées dans `<clé>__kept` (affichées grisées, reprises au rallumage) et l'état dans
# `<clé>__on`. Sans `__on` (réglages d'avant) : actif si l'effet se voit avec les valeurs actuelles.
_ACTIVATION_KINDS = ("sides_thick", "sides", "shadow", "corners", "padding", "title_padding")
_ACTIVATION_SLIDER = re.compile(r"^(border radius|padding|margin|marge)", re.I)


def has_activation(spec: Spec) -> bool:
    return spec.kind in _ACTIVATION_KINDS or (spec.kind == "slider" and bool(_ACTIVATION_SLIDER.match(spec.label)))


def activation_keys(spec: Spec) -> tuple[str, str]:
    return f"{spec.key}__on", f"{spec.key}__kept"


def _neutral_values(spec: Spec, out: dict) -> dict:
    value = out.get(spec.key)
    if spec.kind == "slider":
        return {spec.key: spec.params.get("min", 0)}
    neutral = False if spec.kind in ("sides_thick", "sides", "shadow") else 0
    if isinstance(value, dict):
        return {spec.key: dict.fromkeys(value, neutral)}
    return {spec.key: neutral}


def _effect_visible(spec: Spec, out: dict) -> bool:
    """État du toggle sans `__on` enregistré : actif dès que les valeurs diffèrent de la valeur neutre. Jamais
    « l'effet se voit-il » : une ligne déduite coupée écrirait la valeur neutre et changerait l'aspect (ex. bordure
    du survol, épaisseur 0 = « la même » : coupée, elle retirerait la bordure au survol)."""
    return _neutral_values(spec, out)[spec.key] != out.get(spec.key)


class _KeptValues(ScopeValues):
    """Valeurs de départ d'une ligne coupée : les valeurs gardées (`__kept`) avant les réglages."""

    def __init__(self, base: ScopeValues, kept: dict):
        self.__dict__.update(base.__dict__)
        self._kept = kept

    def seed(self, key: str, default):
        return self._kept[key] if key in self._kept else super().seed(key, default)

    def linked(self, key: str, default: bool = True) -> bool:
        k = f"{key}_linked"
        return bool(self._kept[k]) if k in self._kept else super().linked(key, default)


def _add_activation(spec: Spec, widget: QWidget, values: ScopeValues, on) -> None:
    if on is None:
        on = _effect_visible(spec, FIELD_READERS[spec.kind](spec, widget))
    # Toggle 2 (demande de l'utilisateur, 2026-11-12 ; toggle 1 avant) : se distingue du toggle 1 d'override.
    toggle = _Toggle(bool(on), style_override="toggle2", show_label=False)
    toggle._table_style = "toggle2"                 # imposé par la ligne (gardé par normalize_toggles)
    toggle.style_id = f"{values.name}|{spec.key}#activer"
    widget._v2_active = toggle


def _fade(widget: QWidget, faded: bool) -> None:
    """Opacité de ligne grisée SANS désactiver (le libellé reste saisissable : Ctrl + glisser). Jamais d'effet dans
    un effet (`_set_faded`)."""
    _set_faded(widget, faded)


# -- Pose de valeurs dans un champ DEJA construit (inverse de FIELD_READERS) : `external_values` s'en sert pour
# changer les valeurs affichees sans reconstruire la section (~0,3 s pour Bouton ; editeur fm_theme : changer de
# variante). `v` = toutes les cles lues du champ, mises a jour. Retourne False si le champ ne sait pas (sa
# section est alors reconstruite, comme avant).

def _w_linked(widget: QWidget, spec: Spec, v: dict) -> bool:
    """Cote / coin « lies » : pas de pose possible ; il doit rester tel quel."""
    return f"{spec.key}_linked" not in v or v[f"{spec.key}_linked"] == widget.isLinked()


def _w_sides(spec, w, v) -> bool:
    if not _w_linked(w, spec, v):
        # « Lier les 4 » différent (autre variante de fm_theme) : posé sur place quand le champ sait le faire,
        # sinon toute la section était reconstruite à chaque changement de variante.
        setter = getattr(w, "setLinkedState", None)
        if setter is None:
            return False
        setter(bool(v[f"{spec.key}_linked"]))
    w.setValue(_coerce_side_enabled(v[spec.key]), v[spec.params["colors_key"]] or {})   # ancien format : un bool
    if "thickness_key" in spec.params:
        w._v2_thickness.setValue(int(v[spec.params["thickness_key"]]))
    return True


def _w_title_padding(spec, w, v) -> bool:
    w.setValue(v[f"{spec.key}_linked"], v[spec.key])
    w._v2_parts["before"].setValue(int(v[spec.params["before_key"]]))
    w._v2_parts["after"].setValue(int(v[spec.params["after_key"]]))
    return True


def _w_font_gabarit(spec, w, v) -> bool:
    k, parts = _gabarit_keys(spec), w._v2_parts
    if "char" in parts:
        parts["char"].setText(v[spec.params["char_key"]])
    if "family" in parts:
        parts["family"].setValue(v[k["family"]] or "Systeme")
    for name in ("bold", "italic"):
        if name in parts:
            parts[name].setChecked(bool(v[k[name]]))
    if "size" in parts:
        parts["size"].setValue(int(v[k["size"]]))
    if "smoothing" in parts:
        parts["smoothing"].setValue(bool(v[k["smoothing_enabled"]]), v[k["smoothing"]])
    if "color" in parts:
        parts["color"].setValue(v[k["color"]])
    return True


def _w_inner_line(spec, w, v) -> bool:
    prefix = f"{spec.params.get('prefix', 'table_inner')}_{spec.params['axis']}"
    w.setValue(bool(v[f"{prefix}_enabled"]), v[f"{prefix}_color"], int(v[f"{prefix}_thickness"]))
    return True


def _w_bg_fill(spec, w, v) -> bool:
    w._v2_parts["enabled"].setChecked(bool(v[spec.key]))
    w._v2_parts["color"].setValue(v[spec.params["color_key"]])
    return True


def _w_value(spec, w, v) -> bool:
    w.setValue(v[spec.key])
    return True


def _w_padding(spec, w, v) -> bool:
    """Padding versé (variante, preset) : la plage d'un curseur s'élargit pour la valeur au lieu de la rogner (voir
    _f_padding)."""
    sides = v[spec.key]
    if not isinstance(sides, dict):
        return False
    fields = getattr(getattr(w, "sides", None), "fields", {})
    for key, field in fields.items():
        value = sides.get(key)
        if isinstance(value, (int, float)) and value > field.slider._max:
            field.slider._max = field._max = int(value)
    if hasattr(w, "_hidden_sides"):
        w._hidden_sides = {k: x for k, x in sides.items() if k not in fields}
    w.setValue(v[f"{spec.key}_linked"], sides)
    return True


FIELD_WRITERS: dict[str, Callable] = {
    "slider": lambda sp, w, v: (w.setValue(int(v[sp.key])), True)[1],
    "bool": lambda sp, w, v: (w.setChecked(bool(v[sp.key])), True)[1],
    "color": _w_value, "color_app": _w_value, "header_color": _w_value, "toggle_style": _w_value,
    "corners": lambda sp, w, v: (w.setValue(v[f"{sp.key}_linked"], _corner_value(            # absent : le defaut
        sp, v[sp.key], lambda key: v.get(key, 0))), True)[1],
    "padding": lambda sp, w, v: _w_padding(sp, w, v),
    "title_padding": _w_title_padding,
    "sides": _w_sides, "sides_thick": _w_sides, "shadow": _w_sides,
    "inner_line": _w_inner_line,
    "bg_fill": _w_bg_fill,
    "font_gabarit": _w_font_gabarit,
    "toggle_image": lambda sp, w, v: (w.setNames([v[sp.key]] if v[sp.key] else []), True)[1],
    "state_pair": lambda sp, w, v: all([write_spec(sub, f, v) for sub, f in w.parts]),
    "split_fields": lambda sp, w, v: all([write_spec(sub, f, v) for sub, f in w.parts]),
    "snap_side": lambda sp, w, v: (all([write_spec(sub, f, v) for sub, f in w.parts]), w._sync())[0],
    # Liste de choix : posée sur place (autre variante de fm_theme) ; sans écrivain, toute la section était refaite.
    "choice": lambda sp, w, v: (w.setValue(dict(getattr(w, "_choices", ())).get(v[sp.key], str(v[sp.key]))), True)[1],
    "xy": lambda sp, w, v: (w._v2_parts["first"].setValue(int(v[sp.key])),
                            w._v2_parts["second"].setValue(int(v[sp.params["second_key"]])), True)[2],
}
FIELD_WRITERS["state_follow"] = _w_state_follow
FIELD_WRITERS["offset"] = lambda sp, w, v: (w._v2_parts["x"].setValue(int(v[sp.key])),
                                          w._v2_parts["y"].setValue(int(v[sp.params["y_key"]])), True)[-1]


def write_spec(spec: Spec, widget: QWidget, values: dict) -> bool:
    """Pose dans `widget` les valeurs de `values` qui le concernent. False : ce champ ne sait pas (a refaire)."""
    writer = FIELD_WRITERS.get(spec.kind)
    if writer is None:
        return False
    current = read_spec(spec, widget)
    if not any(k in values for k in current):
        return True
    override = getattr(widget, "_v2_override", None)
    source = values
    if override is not None:
        # État du bouton : la ligne montre ce que l'état utilise (coupée = la ligne standard), comme à la construction.
        flag_key, state, row = spec.params["override"]
        if values.get(flag_key) is not None:
            own = bool(values[flag_key])
        elif flag_key in values:                     # jamais enregistré : déduit des valeurs versées
            own = button_state_override(values, state, row)
        else:
            own = override.isChecked()
        # « activer » de l'état absent des valeurs versées = déduit (jamais l'état lu du champ, toujours défini).
        merged = {**{k: x for k, x in current.items() if k in values or not k.endswith(("__on", "__kept"))},
                  **values, flag_key: own}
        current.update({k: button_state_value(merged, k, None if k.endswith(("__on", "__kept")) else current[k])
                        if k in BUTTON_STATE_FOLLOW else merged.get(k, current[k]) for k in current})
        current[flag_key], source = own, current
    else:
        current.update({k: values[k] for k in current if k in values})
    legacy = spec.params.get("none_from")
    if legacy and current.get(spec.key) is None:     # None = l'ancien réglage (rayon des boutons / champs)
        current[spec.key] = values.get(legacy, 0)
    toggle = getattr(widget, "_v2_active", None)
    on = None
    if toggle is not None:
        flag, kept = activation_keys(spec)
        on = source.get(flag)
        if on is False and isinstance(source.get(kept), dict):
            current.update(source[kept])            # ligne coupée : ses valeurs gardées, grisées
        if on is None:
            on = _effect_visible(spec, current)
    try:
        if not writer(spec, widget, current):
            return False
        if toggle is not None and toggle.isChecked() != bool(on):
            toggle.setChecked(bool(on))
        if override is not None and override.isChecked() != own:
            override.setChecked(own)
        return True
    except (KeyError, TypeError, ValueError, AttributeError):
        return False


def hook_ranges(widget: QWidget, key: str, settings: dict, on_range: Callable | None):
    """Clic droit sur chaque curseur de `widget` = modifier sa plage ; la plage enregistree
    (`slider_ranges`) est reappliquee a la construction. Cle : celle du reglage, suivie de `#rang` si le
    champ porte plusieurs curseurs (padding, coins...)."""
    saved = settings.get("slider_ranges") or {}
    fields = slider_fields(widget)
    for rank, field in enumerate(fields):
        range_key = key if len(fields) == 1 else f"{key}#{rank}"
        scale = 100 if isinstance(field, _RatioSliderField) else 1
        apply_saved_range(field, saved.get(range_key), scale)
        attach_range_menu(field, range_key, on_range, scale)


def tag_toggles(roots, scope: str, key: str):
    """Identifiant stable de chaque toggle d'une ligne (`portee|cle#rang`) : le style choisi pour lui
    au clic droit est enregistre sous cet identifiant (toggle_style_overrides)."""
    seen = []
    for root in roots:
        for toggle in ([root] if isinstance(root, _Toggle) else []) + root.findChildren(_Toggle):
            if toggle not in seen:
                seen.append(toggle)
    for rank, toggle in enumerate(seen):
        toggle.style_id = f"{scope}|{key}#{rank}"


def make_field(spec: Spec, values: ScopeValues, colors: dict, on_range: Callable | None = None) -> QWidget:
    on = None
    if has_activation(spec):
        flag, kept = activation_keys(spec)
        on = values.seed(flag, None)
        if on is False and isinstance(values.seed(kept, None), dict):
            values = _KeptValues(values, values.seed(kept, None))
    widget = FIELD_FACTORIES[spec.kind](spec, values, colors)
    if has_activation(spec):
        _add_activation(spec, widget, values, on)
    if spec.params.get("override"):         # override d'une ligne standard (états du bouton, 2026-11-12)
        _flag, state, row = spec.params["override"]
        toggle = _Toggle(button_state_override(values.settings, state, row), style_override="toggle1",
                         show_label=False)
        toggle._table_style = "toggle1"
        toggle.style_id = f"{values.name}|{spec.key}#override"
        widget._v2_override = toggle
    if spec.params.get("copy_row"):         # bouton « copier la ligne de l'état suivi » (branché par _link_state_follow)
        widget._v2_copy = _state_copy_button()
    # État du bouton de la ligne (Survol, Focus, Enfoncé) : parties repliées en accordéon (_flat_cells_table)
    widget._v2_state = spec.params.get("state") or (spec.params.get("copy_row") or (None,))[0]
    # Gabarit de ligne commun a toutes les lignes de ce type (fm_theme.cells) ; `params["row_kind"]` = un gabarit a
    # part pour des lignes du meme type mais d'une autre forme (polices des etats du bouton : gras + couleur).
    widget._row_kind = spec.params.get("row_kind", spec.kind)
    if spec.key.startswith(('video_', 'vg_', 'vc_')):
        from fm_video.help_content import key_for_setting
        help_key = key_for_setting(spec.key)
        if help_key:
            widget.setProperty('color_help_key', help_key)
    hook_ranges(widget, spec.key, values.settings, on_range)
    tag_toggles([widget, *getattr(widget, "_v2_parts", {}).values()], values.name, spec.key)
    return widget


# ==========================================================================
# 4. UN constructeur de groupe, pour toutes les portees
# ==========================================================================

_CHANGE_SIGNALS = ("valueChanged", "changed", "toggled", "textChanged")


def _connect_changed(widget: QWidget, callback: Callable | None):
    """Branche `callback` sur le(s) signal(aux) de modification du widget (les
    composites emettent `changed`, les curseurs `valueChanged`, les toggles
    `toggled`). Un composite porte aussi ses sous-champs (police gabarit)."""
    if callback is None:
        return
    targets = [widget, *getattr(widget, "_v2_parts", {}).values()]
    for name in ("_v2_active", "_v2_override"):
        if getattr(widget, name, None) is not None:
            targets.append(getattr(widget, name))
    for target in targets:
        for name in _CHANGE_SIGNALS:
            signal = getattr(target, name, None)
            if signal is not None and hasattr(signal, "connect"):
                signal.connect(lambda *_a, cb=callback: cb())
                break


# Groupes dont chaque ligne est UNE LIGNE A COLONNES (un champ par colonne) plutot que
# Parametre/Valeur : colonnes (titre, largeur ; 0 = extensible), comme le tableau de la v1.
COLUMN_TABLES: dict[str, list[tuple[str, int]]] = {
    "Titre : Polices": [("Niveau", 150), ("Police", 330), ("Gras", 90), ("Italique", 90), ("Hauteur", 230),
                        ("Niveau de lissage", 150), ("Couleur", 0)],
}


def _label(text: str) -> QLabel:
    label = QLabel(text)
    _set_text_role(label, "row_label")
    return label


def _build_font_table(group: str, values: ScopeValues, colors: dict, fields: dict, resizers: list,
                      record: list | None, on_change: Callable | None, on_range: Callable | None,
                      parent: QWidget | None = None) -> QWidget:
    """Tableau « une ligne par niveau, un champ par colonne » (reproduction de la v1 : Titre > Polices)."""
    columns = COLUMN_TABLES[group]
    table_rows = []
    for spec in CATALOG[group]:
        parts = _font_parts(spec, values, colors)
        holder = _label(spec.label)
        holder._v2_parts = parts
        for key in (spec.key, *spec.extra_keys):
            fields[key] = holder
        if record is not None:
            record.append((spec, holder))
            _connect_changed(holder, on_change)
        hook_ranges(parts["size"], f"{spec.key}", values.settings, on_range)
        tag_toggles(list(parts.values()), values.name, spec.key)
        table_rows.append([(holder, "left", "center")] + [(parts[name], "center", "center")
                                                          for name, _caption in FONT_CAPTIONS])
    frame, head, _cells = build_cells_table(
        columns, table_rows, head_align={i: Qt.AlignCenter for i in range(1, len(columns))}, parent=parent)
    resizers.append(head)
    normalize_toggles(frame)
    return frame


def _flat_cells_table(rows: list, parent: QWidget | None = None) -> QWidget:
    """Tableau Parametre | Valeur. `rows` : (libelle, champ, toggle d'override ou None). Un toggle
    (portee de surcharge) precede le libelle ; OFF grise la ligne, qui suit alors le General.
    `parent` : voir `build_cells_table`."""
    rows = [tuple(row) + (None,) * (4 - len(row)) for row in rows]
    toggle_extra = (40 if any(t is not None for _l, _f, t, _s in rows) else 0) + \
        (40 if any(getattr(f, "_v2_active", None) is not None for _l, f, _t, _s in rows) else 0) + \
        (28 if any(getattr(f, "_v2_copy", None) is not None for _l, f, _t, _s in rows) else 0)
    # Jamais plus etroite que le titre de son entete (« PARAMÈTRE », police des entetes) : des libelles
    # courts le tronquaient.
    head_width = QFontMetrics(_qfont(9, 600)).horizontalAdvance("PARAMÈTRE") + 28 + 6
    columns = [("Paramètre", max(head_width, natural_label_width([label for label, _f, _t, _s in rows],
                                                                   toggle_extra))), ("Valeur", 0)]
    shortcuts = any(s is not None for _l, _f, _t, s in rows)
    if shortcuts:                       # colonne « Raccourci » (lignes a raccourci clavier) ou autre (« Activer »)
        title = next(getattr(s, "_column_title", "Raccourci") for _l, _f, _t, s in rows if s is not None)
        columns.append((title, 150 if title == "Raccourci" else 90))
    table_rows = []
    toggle_width = next((t.sizeHint().width() + 8 for _l, _f, t, _s in rows if t is not None), 0)
    for label, field, toggle, shortcut in rows:
        text = _label(label)
        copy =getattr(field, "_v2_copy", None)     # états du bouton : « copier la ligne de l'état suivi »
        if toggle is None and copy is None:
            first = text
        else:
            first = QWidget()
            first.setStyleSheet("background: transparent;")
            box = QHBoxLayout(first)
            box.setContentsMargins(0, 0, 0, 0)
            box.setSpacing(8)
            # « copier » en 1re position (demande de l'utilisateur, 2026-11-12), puis l'override ; ligne sans override
            # (Décalage) : un espace à sa place, titres alignés.
            if copy is not None:
                box.addWidget(copy, 0, Qt.AlignVCenter)
            if toggle is not None:
                box.addWidget(toggle, 0, Qt.AlignVCenter)
            elif toggle_width:
                box.addSpacing(toggle_width)
            box.addWidget(text)
        active = getattr(field, "_v2_active", None)
        if active is not None:              # toggle « activer » juste à droite du titre (2026-11-11)
            holder = QWidget()
            holder.setStyleSheet("background: transparent;")
            box = QHBoxLayout(holder)
            box.setContentsMargins(0, 0, 0, 0)
            box.setSpacing(8)
            box.addWidget(first)
            box.addWidget(active, 0, Qt.AlignVCenter)
            box.addStretch(1)
            first = holder
        if toggle is not None or active is not None:
            def grey(*_a, field=field, text=text, toggle=toggle, active=active):
                # Override coupé (la ligne suit la portée générale / l'état standard) OU « activer » coupé : champ
                # grisé. Effet RETIRÉ, jamais laissé à 100 %, ni posé dans un autre (`_set_faded`) : signalé, toggles
                # H, B, D de « lier les 4 » invisibles et artefacts dans les lignes grisées.
                own = toggle is None or toggle.isChecked()
                live = active is None or active.isChecked()
                _set_dimmed(field, not (own and live))
                if toggle is not None:
                    text.setStyleSheet(f"color: {M['row_label'] if own else M['label_dim']}; background: transparent;")
                if active is not None and toggle is not None:
                    _set_dimmed(active, not own)         # override coupé : « activer » est celui de l'état standard
                if active is not None:
                    _fade(text, own and not live)

            for switch in (toggle, active):
                if switch is not None:
                    switch.toggled.connect(grey)
            grey()
        cells = [(first, "left", "center"), (field, "right", "center")]
        if shortcuts:
            if shortcut is None:
                shortcut = QWidget()
                shortcut.setStyleSheet("background: transparent;")
            cells.append((shortcut, "center", "center"))
        table_rows.append(cells)
    head_align = {1: Qt.AlignRight | Qt.AlignVCenter}
    if shortcuts:
        head_align[2] = Qt.AlignCenter
    frame, head, _cells = build_cells_table(columns, table_rows, head_align=head_align, parent=parent)
    frame._v2_head = head
    if any(getattr(f, "_v2_state", None) for _l, f, _t, _s in rows):
        # Déplier un état du bouton replie les autres (demande de l'utilisateur, 2026-11-12) ; le standard
        # (parties sans ligne d'état) n'est jamais touché.
        frame._extra_dims.accordion = lambda part: "states" if any(
            getattr(rows[r][1], "_v2_state", None) for r in part if r < len(rows)) else None
    set_row_kinds(frame, {r: _row_content_kind(field) for r, (_l, field, _t, _s) in enumerate(rows)})
    return frame


# Lignes SANS cellule divisee : meme gabarit quand elles ont le meme TYPE DE CONTENU (le meme champ : une seule
# couleur, un curseur, une liste... ; demande de l'utilisateur, 2026-10-29), quelle que soit leur cle. Variantes d'un
# meme champ ramenees a lui.
_CONTENT_FAMILIES = {"_CompactHeaderColor": "_CompactAppOrCustomColorField", "_FontSelectField": "_SelectField",
                     "_RatioSliderField": "_SliderField"}


def _row_content_kind(field: QWidget) -> str | None:
    """Type de gabarit d'une ligne : son `kind` si sa cellule est divisee (Bordures, Border radius...), sinon la
    classe de son champ (un conteneur generique, qui peut tout contenir, n'en a pas)."""
    if getattr(field, "_row_kind", None) is None:
        return None
    if getattr(field, "_split", None) is not None or isinstance(field, SplitCell):
        return field._row_kind
    name = type(field).__name__
    if type(field) is QWidget:
        return None
    return f"contenu:{_CONTENT_FAMILIES.get(name, name)}"


def _dim_row(field: QWidget, dimmed: bool):
    """Grise une ligne de tableau : son champ (inactif, 20 %) et son libelle (20 %, reste cliquable :
    Ctrl + glisser deplace toujours la ligne)."""
    _set_dimmed(field, dimmed)
    cell = field.parentWidget()
    while cell is not None and not isinstance(cell, _Cell):
        cell = cell.parentWidget()
    row = cell.parentWidget() if cell is not None else None
    if row is None:
        return
    for other in row.findChildren(_Cell, options=Qt.FindDirectChildrenOnly):
        if other is not cell:
            _set_faded(other.content(), dimmed)


def _rule_holds(value, expected) -> bool:
    return value in expected if isinstance(expected, list) else value == expected


def _link_active_rows(group: str, fields: dict):
    """Lignes actives SEULEMENT quand une autre ligne du groupe a une valeur donnee
    (`params["active_when"] = (cle, valeur)`, ex. Icones / Animation quand Type = Icones ; valeur = liste : l'une
    d'elles) : grisees sinon, en direct."""
    specs = list(CATALOG[group])
    by_key = {sp.key: sp for sp in specs}
    for sp in specs:                    # champs d'une colonne en plus (« Activer ») : pilotes eux aussi
        sub = sp.params.get("column") or sp.params.get("shortcut")
        if sub is not None:
            by_key.setdefault(sub.key, sub)
    for spec in specs:
        rules = spec.params.get("active_when")
        if not rules:
            continue
        rules = [rules] if isinstance(rules[0], str) else list(rules)   # (cle, valeur) ou liste de regles
        if spec.key not in fields or any(r[0] not in by_key or r[0] not in fields for r in rules):
            continue
        target = fields[spec.key]
        drivers = [(by_key[r[0]], fields[r[0]], r) for r in rules]
        # Le pilote est dans la MEME ligne (colonne « Activer ») : seul le champ est grise, pas la ligne
        # (le toggle qui le pilote reste net).
        same_row = any(fields[r[0]] is (fields.get((spec.params.get("column") or Spec("", "", "")).key))
                       for r in rules)

        def sync(target=target, drivers=drivers, same_row=same_row):
            off = any(not _rule_holds(read_spec(d_spec, d_widget).get(r[0]), r[1]) for d_spec, d_widget, r in drivers)
            if same_row:
                _set_dimmed(target, off)
            else:
                _dim_row(target, off)

        for _d_spec, d_widget, _r in drivers:
            _connect_changed(d_widget, sync)
        sync()


_STANDARD_ROW_SPECS = {"color": "button_bg_color", "border": "button_border_enabled", "font": "button_font_family",
                       "radius": "button_corner_radius", "shadow": "button_shadow_enabled"}


def _link_state_follow(group: str, fields: dict, values: ScopeValues):
    """États du bouton : une ligne non surchargée MONTRE, en direct, les valeurs RÉELLES de la ligne qu'elle suit
    (toggle « activer » compris) : reposée à chaque changement d'une ligne du même nom (standard ou autre état), de
    son toggle d'override ou d'une liste « suit » (demande de l'utilisateur, 2026-11-12 : « l'override est
    prioritaire : coupé, la ligne est grisée coûte que coûte et ses paramètres sont ceux de la ligne qui la pilote »).
    Seules les lignes de ce nom sont relues / reposées (≤ 4 lectures, 3 poses par mouvement d'un curseur)."""
    specs = [sp for sp in CATALOG[group] if not isinstance(sp, str) and sp.params.get("override")
             and getattr(fields.get(sp.key), "_v2_override", None) is not None]
    if not specs:
        return
    by_key = {sp.key: sp for sp in CATALOG[group] if not isinstance(sp, str)}
    follows = [sp for sp in by_key.values() if sp.kind == "state_follow" and sp.key in fields]
    rows: dict = {}                             # nom de ligne -> [ligne standard, lignes des états]
    for sp in specs:
        rows.setdefault(sp.params["override"][2], []).append(sp)
    for row, key in _STANDARD_ROW_SPECS.items():
        if row in rows and key in fields and key in by_key:
            rows[row].insert(0, by_key[key])
    busy = []

    def read(spec_list) -> dict:
        current = dict(values.settings)
        for sp in spec_list:
            if sp.key in fields and sp.kind in FIELD_READERS:
                current.update(read_spec(sp, fields[sp.key]))
        return current

    def push(names):
        if busy:                                # ses propres poses : jamais en boucle
            return
        busy.append(True)
        try:
            current = read(follows + [sp for name in names for sp in rows[name]])
            for name in names:
                for sp in rows[name]:
                    override = getattr(fields[sp.key], "_v2_override", None)
                    if override is not None and not override.isChecked():
                        write_spec(sp, fields[sp.key], current)
        finally:
            busy.clear()

    def refresh(*_args):
        push(list(rows))

    def reset(spec):
        """« Réinitialiser » : l'état prend exactement celui choisi dans sa liste, toutes ses lignes surchargées."""
        state = spec.params["state"]
        source = read_spec(spec, fields[spec.key])[spec.key]
        current = read(by_key.values())
        current.update(button_state_copy(current, source, state))
        busy.append(True)
        try:
            for sp in by_key.values():
                if sp.key.startswith(f"button_{state}_") and sp.key in fields:
                    write_spec(sp, fields[sp.key], current)
        finally:
            busy.clear()
        refresh()                               # les états qui suivent celui-ci

    def copy_row(spec):
        """Bouton « copier » d'une ligne d'état : CETTE ligne prend celle de l'état choisi dans « suit », surchargée."""
        state, row = spec.params["copy_row"]
        follow = by_key.get(f"button_{state}_follow")
        if follow is None or follow.key not in fields:
            return
        source = read_spec(follow, fields[follow.key])[follow.key]
        current = read(by_key.values())
        if row == "offset":
            keys = {f"button_{state}_offset_x", f"button_{state}_offset_y"}
        else:
            keys = {f"button_{state}_{suffix}{tail}" for suffix in BUTTON_STATE_ROWS[row]
                    for tail in ("", "_linked", "__on", "__kept")} | {f"button_{state}_ovr_{row}"}
        current.update({k: v for k, v in button_state_copy(current, source, state).items() if k in keys})
        busy.append(True)
        try:
            write_spec(spec, fields[spec.key], current)
        finally:
            busy.clear()
        if row in rows:
            push([row])                         # les états qui suivent celui-ci

    for name, row_specs in rows.items():
        for sp in row_specs:                    # valeurs, « activer » et override de la ligne
            _connect_changed(fields[sp.key], lambda name=name: push([name]))
    for sp in follows:
        fields[sp.key]._v2_follow.changed.connect(refresh)
        fields[sp.key]._v2_reset.clicked.connect(lambda _c=False, s=sp: reset(s))
    for sp in by_key.values():
        button = getattr(fields.get(sp.key), "_v2_copy", None)
        if button is not None and sp.params.get("copy_row"):
            button.clicked.connect(lambda _c=False, s=sp: copy_row(s))


def _link_side_colors(group: str, fields: dict):
    """Ligne « couleur unique » (`params["sets_side_colors"]` = cle d'une ligne Bordures du groupe) : chaque
    changement de sa couleur est pose sur les 4 cotes de cette ligne, en direct."""
    for spec in CATALOG[group]:
        target_key = spec.params.get("sets_side_colors")
        if not target_key or spec.key not in fields or target_key not in fields:
            continue
        color, sides = fields[spec.key], fields[target_key]

        def push(*_args, color=color, sides=sides):
            sides.sides.setValue({k: color.value() for k in ("left", "top", "bottom", "right")})
            sides.changed.emit()
        color.changed.connect(push)


def _shortcut_field(spec: Spec, values: ScopeValues, colors: dict, fields: dict, record: list | None,
                    on_change: Callable | None) -> QWidget | None:
    """Champ de la colonne « Raccourci » d'une ligne qui en a un (`params["shortcut"]`, un Spec)."""
    sub = spec.params.get("shortcut") or spec.params.get("column")
    if sub is None:
        return None
    widget = make_field(sub, values, colors)
    widget._column_title = sub.label      # titre de la colonne (« Raccourci », « Activer »...)
    fields[sub.key] = widget
    if record is not None:
        record.append((sub, widget))
        _connect_changed(widget, on_change)
    return widget


# Groupes dont TOUTES les lignes sont des icones : un tableau d'icones commun (colonnes Apercu | Nom | Etat | Action).
# Tableaux d'icones : lignes d'icones, plus les couleurs qui s'y rattachent (`icon_color_of` : colonne Couleur).
ICON_GROUPS = frozenset(group for group, specs in CATALOG.items()
                        if specs and all(s.kind == "ui_icon" or "icon_color_of" in s.params or "icon_tail" in s.params
                                         for s in specs))


def _build_icon_table(group: str, fields: dict, resizers: list, values=None, colors=None, record=None,
                      on_change=None) -> QWidget:
    """Groupe d'icones : UN tableau commun (`settings_v2_app.icon_table`), une ligne par icone (par etat pour la
    punaise) — Apercu | Nom | Etat | Action. Les boutons agissent tout de suite sur les fichiers d'icone perso.
    Specs `icon_color_of` (barre de navigation de fm_browser) : une colonne Couleur de plus, vide pour les icones
    sans couleur ; ce sont des reglages enregistres comme les autres. `icon_column` = titre de la colonne (defaut
    « Couleur ») : UNE colonne par titre, dans l'ordre des specs (barre des modules du board : « Marge » et « Couleur
    du module », un curseur et un toggle par icone de module)."""
    specs = CATALOG[group]
    columns: dict = {}                              # titre -> {cle d'icone: spec}
    for s in specs:
        if "icon_color_of" in s.params:
            columns.setdefault(s.params.get("icon_column", "Couleur"), {})[s.params["icon_color_of"]] = s
    tints = columns
    entries, keep = [], []
    for spec in specs:
        if spec.kind != "ui_icon":
            continue
        field = UiIconField(spec.params["ui_key"])
        keep.append(field)
        fields[spec.key] = field
        extra = []
        for column in columns.values():
            tint = column.get(spec.params["ui_key"])
            if tint is None:
                extra.append(QLabel(""))
                continue
            widget = make_field(tint, values, colors)
            fields[tint.key] = widget
            if record is not None:
                record.append((tint, widget))
                _connect_changed(widget, on_change)
            extra.append(widget)
        for caption, avatar, buttons, state in field.states():
            entries.append((f"{spec.label} : {caption.lower()}" if caption else spec.label, avatar, state, buttons,
                            *extra))
    from settings_v2_app import ICON_TABLE_COLUMNS
    frame, head = icon_table(entries, ICON_TABLE_COLUMNS + tuple((title, 110 if title == "Couleur" else 160)
                                                                 for title in columns))
    frame._dims_key = f"v2:{group}#0"               # jamais les largeurs de l'ancien tableau a sous-cellules
    frame._ui_icon_fields = keep                    # garde les champs en vie : leurs boutons leur sont relies
    if tints:
        normalize_toggles(frame)                    # toggles app / sys de la colonne Couleur : type 2, sans texte
    resizers.append(head)
    tail = [s for s in specs if "icon_tail" in s.params]
    if not tail:
        return frame
    # Reglages poses SOUS le tableau d'icones (`icon_tail`) : tableau Parametre | Valeur a part, entete supprime et
    # titre au-dessus (le texte de `icon_tail`) par defaut ; l'utilisateur peut les changer (table_dims).
    rows = []
    for spec in tail:
        widget = make_field(spec, values, colors)
        fields[spec.key] = widget
        if record is not None:
            record.append((spec, widget))
            _connect_changed(widget, on_change)
        rows.append((spec.label, widget, None, None))
    wrap = QWidget()
    wrap.setStyleSheet("background: transparent;")
    lay = QVBoxLayout(wrap)
    lay.setContentsMargins(0, 0, 0, 0)
    lay.setSpacing(0)
    lay.addWidget(frame, 0, Qt.AlignLeft)
    sub = _flat_cells_table(rows, wrap)
    sub._dims_key = f"v2:{group}#1"
    normalize_toggles(sub)
    resizers.append(sub._v2_head)
    extra = getattr(sub, "_extra_dims", None)
    if extra is not None:                           # defaut, remplace par les dimensions enregistrees (showEvent)
        extra.apply({"head_hidden": True, "above_texts": {"0": tail[0].params["icon_tail"]}})
    lay.addWidget(sub, 0, Qt.AlignLeft)
    wrap._ui_icon_fields = keep
    return wrap


TABLE_FIELDS = frozenset({"cad_linetypes"})


def _link_folder_text_row(enabled: _Toggle, from_icon: _Toggle, color: QWidget) -> None:
    """Couleur des dossiers : « Couleur icone » grise si Texte est coupe ; la couleur du texte grisee si Texte est
    coupe ou si elle suit l'icone. En direct."""
    def sync(_checked=None):
        _set_dimmed(from_icon, not enabled.isChecked())
        _set_dimmed(color, not enabled.isChecked() or from_icon.isChecked())
    enabled.toggled.connect(sync)
    from_icon.toggled.connect(sync)
    sync()


def build_group(group: str, values: ScopeValues, colors: dict,
                fields: dict, toggles: dict, resizers: list,
                record: list | None = None, on_change: Callable | None = None,
                on_range: Callable | None = None, parent: QWidget | None = None) -> QWidget:
    """Tableau d'un groupe du CATALOG : lignes sans toggle (sauf celles qui portent un
    `general_toggle`, regroupees dans un second tableau).
    `record` : liste ou s'inscrivent (spec, widget) et (cle_interrupteur, toggle).
    Tout tableau a un entete ; ses toggles sont de type 2 sans texte.
    `parent` : le corps qui recevra le groupe (pas encore dans son layout). Les tableaux a lignes
    Parametre | Valeur et celui des polices naissent sous lui : les rattacher plus tard, tout remplis, coutait
    ~80 ms par tableau (voir `build_cells_table`) ; les autres groupes l'ignorent."""
    if group == "Chargement et génération automatique":
        rows = []
        specs = CATALOG[group]
        for offset in range(0, len(specs), 3):
            cells = [(_label(specs[offset].label), "left", "center")]
            for spec in specs[offset:offset + 3]:
                widget = make_field(spec, values, colors)
                fields[spec.key] = widget
                if record is not None:
                    record.append((spec, widget))
                    _connect_changed(widget, on_change)
                cells.append((widget, "center", "center"))
            rows.append(cells)
        frame, head, _cells = build_cells_table(
            [("Paramètre", 200), ("Activer", 80), ("Déclenchement", 350), ("Temps d'attente", 150)], rows)
        normalize_toggles(frame)                    # toggle seul dans sa cellule « Activer » : type 1
        frame._v2_head = head
        resizers.append(head)
        return frame
    if group == "Icones : Couleurs des dossiers":
        rows = []
        specs = CATALOG[group]
        step = len(FOLDER_COLOR_COLUMNS) - 1
        for offset in range(0, len(specs), step):
            cells = [(_label(specs[offset].label), "left", "center")]
            line = []
            for spec in specs[offset:offset + step]:
                widget = make_field(spec, values, colors)
                fields[spec.key] = widget
                if record is not None:
                    record.append((spec, widget))
                    _connect_changed(widget, on_change)
                cells.append((widget, "center", "center"))
                line.append(widget)
            _link_folder_text_row(*line[1:])
            rows.append(cells)
        frame, head, _cells = build_cells_table(FOLDER_COLOR_COLUMNS, rows)
        normalize_toggles(frame)
        frame._v2_head = head
        resizers.append(head)
        return frame
    if group in COLUMN_TABLES:
        return _build_font_table(group, values, colors, fields, resizers, record, on_change, on_range, parent)
    if group in ICON_GROUPS:
        return _build_icon_table(group, fields, resizers, values, colors, record, on_change)
    specs = CATALOG[group]
    if len(specs) == 1 and specs[0].kind in TABLE_FIELDS:
        # Le champ EST le tableau (une ligne par element : types de ligne du CAD) : pas de Parametre | Valeur autour.
        spec = specs[0]
        field_w = make_field(spec, values, colors, on_range)
        fields[spec.key] = field_w
        if record is not None:
            record.append((spec, field_w))
            _connect_changed(field_w, on_change)
        return field_w
    flat_rows, toggle_rows = [], []
    for spec in CATALOG[group]:
        field_w = make_field(spec, values, colors, on_range)
        for key in (spec.key, *spec.extra_keys):
            fields[key] = field_w
        if record is not None:
            record.append((spec, field_w))
            _connect_changed(field_w, on_change)
        if spec.general_toggle:
            style = spec.params.get("override_toggle_style", "toggle2")
            toggle = _Toggle(bool(values.seed(spec.general_toggle, False)), style_override=style, show_label=False)
            if "override_toggle_style" in spec.params:
                toggle._table_style = style                 # impose par la ligne (garde par normalize_toggles)
            toggle.style_id = f"General|{spec.general_toggle}#actif"
            toggles[spec.general_toggle] = toggle
            toggle_rows.append((spec.label, field_w, toggle))
            if record is not None:
                record.append((spec.general_toggle, toggle))
                _connect_changed(toggle, on_change)
        else:
            flat_rows.append((spec.label, field_w, getattr(field_w, "_v2_override", None), _shortcut_field(spec, values, colors, fields, record,
                                                                         on_change)))
    _align_state_pairs(fields)                      # avant le tableau : sa colonne se cale sur les sous-cellules
    frames = []
    wrap = QWidget(parent) if bool(flat_rows) + bool(toggle_rows) != 1 else None   # 2 tableaux : ils naissent sous lui
    for rows in (flat_rows, toggle_rows):
        if rows:
            frame = _flat_cells_table(rows, wrap if wrap is not None else parent)
            if group in PORTED_GROUPS or group in SHARED_TITLE_GROUPS:
                # Cle de dimensions propre a la v2 : la v1 a enregistre sous le meme titre de section
                # les largeurs de SES tableaux (autres colonnes), qui ecraseraient celles-ci.
                frame._dims_key = f"v2:{group}#{len(frames)}"
            resizers.append(frame._v2_head)
            normalize_toggles(frame)
            frames.append(frame)
    _link_active_rows(group, fields)
    _link_side_colors(group, fields)
    _link_state_follow(group, fields, values)
    if len(frames) == 1:
        return frames[0]
    wrap.setStyleSheet("background: transparent;")
    wl = QVBoxLayout(wrap)
    wl.setContentsMargins(0, 0, 0, 0)
    wl.setSpacing(0)
    for frame in frames:
        wl.addWidget(frame, 0, Qt.AlignLeft)        # tableaux justifies a gauche
    return wrap


def _fit_inner(scroller: QScrollArea):
    """Page a la taille de l'ascenseur, sans jamais descendre sous sa taille mini : ni tassee en
    hauteur, ni serree en largeur (un tableau plus large que la fenetre fait defiler a l'horizontale)."""
    inner = scroller.widget()
    if inner is None:
        return
    hint = inner.minimumSizeHint()
    width = max(scroller.viewport().width(), hint.width())
    height = max(scroller.viewport().height(), hint.height())
    if inner.width() != width or inner.height() != height:
        inner.resize(width, height)


class _WideScrollArea(_NoSqueezeScrollArea):
    """Ascenseur de page de la v2 : comme _NoSqueezeScrollArea, mais un tableau plus large que la
    fenetre (colonnes libres) elargit la page (ascenseur horizontal) au lieu d'etre rogne."""

    def setWidget(self, widget):
        super().setWidget(widget)
        widget.installEventFilter(self)

    def resizeEvent(self, event):
        QScrollArea.resizeEvent(self, event)
        _fit_inner(self)

    def eventFilter(self, obj, event):
        if obj is self.widget() and event.type() == QEvent.LayoutRequest:
            _fit_inner(self)
        return super().eventFilter(obj, event)


def _system_idle_ms() -> int | None:
    """Millisecondes depuis la derniere entree clavier / souris du systeme (Windows) ; None ailleurs."""
    try:
        import ctypes
        from ctypes import wintypes

        class _LastInput(ctypes.Structure):
            _fields_ = [("cbSize", wintypes.UINT), ("dwTime", wintypes.DWORD)]

        info = _LastInput(ctypes.sizeof(_LastInput), 0)
        if not ctypes.windll.user32.GetLastInputInfo(ctypes.byref(info)):
            return None
        return int((ctypes.windll.kernel32.GetTickCount() - info.dwTime) & 0xFFFFFFFF)
    except (AttributeError, OSError, ImportError):
        return None


class _LazyNode(QWidget):
    """Noeud replie dont le contenu (tableau et/ou noeuds enfants) n'est
    construit qu'au premier depliage — c'est ce qui evite de payer les ~15
    widgets par ligne de tout ce que l'on n'ouvre jamais. `eager=True`
    construit tout de suite (pour mesurer l'apport du differe)."""

    def __init__(self, node: Node, level: int, values: ScopeValues, colors: dict, store: dict,
                 eager: bool = False, root_refresh: Callable | None = None, parent=None,
                 wired: bool = False):
        super().__init__(parent)
        self.node, self.level, self._values, self._colors, self._store = node, level, values, colors, store
        self.wired = wired     # True : ses champs sont lus/enregistres/appliques par la fenetre
        self._eager, self._built = eager, False
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        with _section_host(self):
            self._head = _Section(node.title) if level == 1 else _SubSection(node.title, level=level)
        lay.addWidget(self._head)
        self._head.set_collapsed(True)
        self._head.enable_box()        # titre + contenu = un paragraphe (Titres > Paragraphes)
        # Section : recalcule tout l'arbre (refresh_min_height) ; sous-section
        # sous une section : on previent la section ; sinon son propre parent.
        own = self._head.refresh_min_height if level == 1 else self._head.refresh_layout
        self._child_refresh = own if root_refresh is None else root_refresh
        if root_refresh is not None:
            self._head.collapsedChanged.connect(lambda _c, f=root_refresh: f())
        self._head.collapsedChanged.connect(self._on_collapsed)
        if eager:
            self._build()

    def add_child(self, node: Node) -> "_LazyNode":
        """Ajoute une sous-section a un noeud deja construit (nouveau style de toggle)."""
        child = _LazyNode(node, min(self.level + 1, 5), self._values, self._colors, self._store, self._eager,
                          self._child_refresh, self._child_wrap, self.wired)
        _add_stacked(self._child_wrap.layout(), self._child_nodes, child)
        stack = getattr(self._child_wrap, "_title_stack", None)
        if stack is not None:
            stack.attach(child)
        _make_accordion(self._child_nodes)
        self._child_refresh()
        return child

    @property
    def head(self):
        """L'entete cliquable (ce que _make_accordion ecoute)."""
        return self._head.head

    def _stack_key(self) -> str:
        """Cle de la pile de ses enfants : onglet + chemin des titres (enregistrement de leur ordre)."""
        titles, node = [], self
        while node is not None:
            if isinstance(node, _LazyNode):
                titles.append(node.node.title)
            node = logical_parent(node)
        return f"{self._values.name}|" + "/".join(reversed(titles))

    def is_collapsed(self) -> bool:
        return self._head.is_collapsed()

    def set_collapsed(self, collapsed: bool):
        self._head.set_collapsed(collapsed)

    def _on_collapsed(self, collapsed: bool):
        note = self._store.get("on_collapsed")
        if note is not None:
            note()                      # l'utilisateur deplie / replie : la pre-construction se tait un moment
        if not collapsed:
            self._build()

    def _build(self):
        if self._built:
            return
        self._built = True
        node = self.node
        # Section qui a des sous-sections ET ses propres tableaux : ces tableaux passent dans une sous-section
        # « Main », en tete (demande de l'utilisateur, 2026-11-08). L'arbre (Node) ne change pas.
        main = Node(MAIN_SUBSECTION, node.group) if node.group and node.children else None
        with _section_host(self):
            if node.group and main is None:
                self._group_widget = self._make_group()
                self._head.add(self._group_widget)
            if node.children:
                wrap = QWidget()
                wrap.setStyleSheet("background: transparent;")
                wl = QVBoxLayout(wrap)
                wl.setContentsMargins(0, 0, 0, 0)
                wl.setSpacing(0)               # l'ecart entre titres = leurs paddings (Titres > Paragraphes)
                children = self._child_nodes = []
                self._child_wrap = wrap
                key = self._stack_key()
                ordered = self._store.get("title_order")
                nodes = ((main,) if main is not None else ()) + tuple(node.children)
                for child in (ordered(nodes, key) if ordered else nodes):
                    lazy = _LazyNode(child, min(self.level + 1, 5), self._values, self._colors, self._store,
                                     self._eager, self._child_refresh, wrap, self.wired)
                    if child is main:
                        # Largeurs enregistrees des tableaux : meme cle qu'avant « Main » (titre ignore par dimsKey).
                        lazy._head._dims_transparent = True
                    _add_stacked(wl, children, lazy)
                _make_accordion(children)      # en deplier un replie les soeurs, sauf avec Ctrl
                # Titres des enfants a leur retrait absolu : pas de decalage
                # de corps (voir _BodyMixin._holds_titles).
                self._head._body_layout.addWidget(wrap)
                for child in children:     # leur retrait se calcule depuis ce paragraphe, desormais parent
                    child._head.apply_box()
                make_stack = self._store.get("title_stack")
                if make_stack is not None:
                    make_stack(wrap, children, key)
        after = self._store.get("after_build")
        if after is not None:
            after()
        if not self.wired:
            # Pas encore branche : on le montre mais on ne le laisse pas modifier
            # (une valeur changee ici ne serait ni appliquee ni enregistree).
            self._head._body.setEnabled(False)

    def _make_group(self) -> QWidget:
        return build_group(
            self.node.group, self._values, self._colors, self._store.setdefault("fields", {}),
            self._store.setdefault("toggles", {}), self._store.setdefault("resizers", []),
            self._store.setdefault("specs", []) if self.wired else None,
            self._store.get("on_change"), self._store.get("on_range"), parent=self._head._body)

    def rebuild_group(self):
        """Tableau du groupe refait avec les valeurs COURANTES des reglages (changees hors de la fenetre :
        tableau a la volee de la visionneuse). Ses dimensions (largeurs, hauteurs...) passent a la copie."""
        old = getattr(self, "_group_widget", None)
        if not self._built or old is None:
            return
        frames = ([old] if isinstance(old, _TableFrame) else []) + old.findChildren(_TableFrame)
        for frame in frames:
            if frame._dims_applied:
                _TABLE_DIMS[frame.dimsKey()] = frame.collectDims()
        for frame in frames:
            frame._dims_retired = True              # la copie reprend SA cle (et sa mise en page), pas « #1 »
        mine = lambda w: w is old or old.isAncestorOf(w)
        store = self._store
        if "specs" in store:
            store["specs"][:] = [e for e in store["specs"] if not mine(e[1])]
        for name in ("fields", "toggles"):
            for key in [k for k, w in store.get(name, {}).items() if mine(w)]:
                del store[name][key]
        if "resizers" in store:
            store["resizers"][:] = [h for h in store["resizers"] if not mine(h)]
        with _section_host(self):
            new = self._make_group()
        for row in self._head._body_rows:
            if row.indexOf(old) >= 0:
                row.replaceWidget(old, new)
                break
        self._group_widget = new
        old.hide()
        old.deleteLater()
        after = store.get("after_build")
        if after is not None:
            after()


class _TitleStack:
    """Paragraphes freres (titres d'une meme pile) reordonnes en TIRANT leur titre : le paragraphe
    entier suit le curseur, son ancienne place reste a 25 %, les emplacements possibles s'allument a
    l'approche (le meme retour visuel que les colonnes / lignes, _ReorderOverlay sur l'axe vertical).
    L'ordre est retenu par titres (`on_order(cle, [titres])`). Protocole de _ReorderOverlay :
    `_order` et `_column_spans()` (indices = places au debut du geste)."""

    def __init__(self, container: QWidget, nodes: list, key: str, on_order: Callable):
        self.container, self.nodes, self.key, self.on_order = container, nodes, key, on_order
        self._base: list = []
        self._order: list = []
        self._overlay = None
        self._gpos = None
        # Pres du haut / du bas de la page, elle defile toute seule (emplacement hors de la vue).
        self._scroll_timer = QTimer(container)
        self._scroll_timer.setInterval(16)
        self._scroll_timer.timeout.connect(self._auto_scroll)
        for node in nodes:
            self.attach(node)

    def attach(self, node: "_LazyNode"):
        node.head.drag_handler = self

    def _column_spans(self) -> list:
        spans = []
        for node in self._base:
            top = node.mapTo(self.container, QPoint(0, 0)).y()
            spans.append((top, top + node.height()))
        return spans

    def begin(self, header, press) -> bool:
        node = next((n for n in self.nodes if n.head is header), None)
        if node is None or len(self.nodes) < 2:
            return False
        self._base = list(self.nodes)
        self._order = list(range(len(self._base)))
        top = node.mapTo(self.container, QPoint(0, 0)).y()
        ghost = self.container.grab(QRect(0, top, self.container.width(), node.height()))
        self._overlay = _ReorderOverlay(self.container, self, self._base.index(node), ghost, 0,
                                        self.container.mapFromGlobal(press).y() - top, axis="y")
        return True

    _EDGE = 40          # px du bord de la page ou elle commence a defiler

    def _scroller(self):
        widget = self.container
        while widget is not None and not isinstance(widget, QScrollArea):
            widget = widget.parentWidget()
        return widget

    def move(self, gpos):
        self._gpos = gpos
        if self._overlay is not None:
            self._overlay.follow(self.container.mapFromGlobal(gpos).y())
            if not self._scroll_timer.isActive():
                self._scroll_timer.start()

    def _auto_scroll(self):
        scroller = self._scroller()
        if self._overlay is None or scroller is None or self._gpos is None:
            self._scroll_timer.stop()
            return
        y = scroller.viewport().mapFromGlobal(self._gpos).y()
        height = scroller.viewport().height()
        step = 0
        if y < self._EDGE:
            step = -max(2, (self._EDGE - y) // 2)
        elif y > height - self._EDGE:
            step = max(2, (y - (height - self._EDGE)) // 2)
        if step:
            bar = scroller.verticalScrollBar()
            bar.setValue(bar.value() + step)
            self._overlay.follow(self.container.mapFromGlobal(self._gpos).y())

    def end(self):
        self._scroll_timer.stop()
        overlay, self._overlay = self._overlay, None
        if overlay is None:
            return
        gap = overlay.target
        overlay.hide()
        overlay.deleteLater()
        if gap is None:
            return
        order = [i for i in self._order if i != overlay.source]
        order.insert(gap - (1 if gap > overlay.source else 0), overlay.source)
        self.apply([self._base[i] for i in order])
        self.on_order(self.key, [n.node.title for n in self.nodes])

    def apply(self, nodes: list):
        """Pose `nodes` dans cet ordre : layout, liste des freres (accordeon), voisins des boites."""
        layout = self.container.layout()
        # Les espaces sont des QSpacerItem places dans le layout, pas des enfants des widgets.
        # Les retirer/replacer uniquement les widgets les laissait aux anciens indices. Le layout
        # peut aussi contenir un stretch final : insérer avec addWidget() placerait alors toutes les
        # sections APRES ce stretch, qui les pousse en bas de la page. Réinsérer chaque bloc à sa
        # position de départ, avec ses espaceurs, garde le stretch après les sections.
        positions = []
        for node in self.nodes:
            positions.append(layout.indexOf(node))
            for item in (getattr(node, "_space_above_item", None), getattr(node, "_space_below_item", None)):
                if item is not None:
                    positions.extend(i for i in range(layout.count()) if layout.itemAt(i).spacerItem() is item)
        base = min(positions) if positions else 0
        for node in self.nodes:
            layout.removeWidget(node)
            for item in (getattr(node, "_space_above_item", None), getattr(node, "_space_below_item", None)):
                if item is not None:
                    layout.removeItem(item)
        pos = base
        for node in nodes:
            above = getattr(node, "_space_above_item", None)
            below = getattr(node, "_space_below_item", None)
            if above is not None:
                layout.insertItem(pos, above)
                pos += 1
            layout.insertWidget(pos, node)
            pos += 1
            if below is not None:
                layout.insertItem(pos, below)
                pos += 1
        self.nodes[:] = nodes
        for pos, node in enumerate(nodes):
            node._head._box_prev = nodes[pos - 1]._head if pos else None
            node._head._box_next = nodes[pos + 1]._head if pos + 1 < len(nodes) else None
        for node in nodes:
            node._head.apply_box()
        layout.activate()
        _reflow_ancestors(self.container)


def ordered_nodes(nodes, titles) -> list:
    """`nodes` dans l'ordre enregistre `titles` (titres inconnus : a la fin, dans leur ordre ; « Main » jamais
    deplace : en tete)."""
    nodes = list(nodes)
    if not titles:
        return nodes
    rank = {title: i for i, title in enumerate(titles)}
    return sorted(nodes, key=lambda n: (rank.get(n.title, -1 if n.title == MAIN_SUBSECTION else len(rank)),
                                        nodes.index(n)))


def _add_stacked(layout: QVBoxLayout, nodes: list, node: _LazyNode):
    """Empile `node` sous ses freres `nodes`, sans espaceur : l'ecart entre titres vient du padding du
    titre et des paragraphes (Titres > Paragraphes > Padding (titre) / Padding / Margin). Le layout doit avoir
    un espacement nul. Chaque titre connait ses voisins (boites collees : filet unique, coins droits)."""
    if nodes:
        above = nodes[-1]._head
        above._box_next, node._head._box_prev = node._head, above
        above.apply_box()
        node._head.apply_box()
    nodes.append(node)
    layout.addWidget(node)


def expand_all(root: QWidget):
    """Deplie (donc construit) tous les noeuds sous `root`, jusqu'aux feuilles."""
    while True:
        pending = [n for n in root.findChildren(_LazyNode) if n.is_collapsed()]
        if not pending:
            return
        for n in pending:
            n.set_collapsed(False)


# ==========================================================================
# 5. La fenetre
# ==========================================================================

def _head_hex(colors: dict, value: str) -> str:
    """Couleur d'entete des tableaux (pastille d'appli ou couleur libre) en hexa, comme
    _HeaderColorField._current_hex."""
    # Calcul pur (meme regle que le champ) : creer un _HeaderColorField pour le lire coutait ~3 ms, une
    # douzaine de fois par cran d'un glisser de couleur (signale : « ca rame »).
    from app_style import split_color_ref, with_alpha
    from settings_store import _SLOT_REAL
    from settings_widgets import _SLOT_LABELS
    value, alpha = split_color_ref(value) if isinstance(value, str) else ("skinN1", 100)
    if not (value in _SLOT_LABELS or value.startswith("#")):
        value = "skinN1"
    if value.startswith("#"):
        return value
    return with_alpha(colors.get(_SLOT_REAL.get(value, "chrome"), "#000000"), alpha)


# Sections de l'onglet General deja BRANCHEES (lues, appliquees en direct,
# enregistrees). Les autres s'affichent mais restent grisees.
# Sections renommees (TITRE -> TITRES, Espacements -> Padding (titre seulement), Fond -> Paragraphes) :
# la cle des dimensions d'un tableau suit les titres (_TableFrame.dimsKey). Les anciennes cles sont
# RECOPIEES (jamais deplacees : la v1 garde les siennes) vers les nouvelles si celles-ci manquent.
_DIMS_RENAMES = (("Visionneuse/Sous cellule image#", "Visionneuse/Cellules#"),
                 ("MRO#", "Magnétisme#"),                     # section MRO de General -> onglet « Module MRO »
                 ("MRO/Barres d'outils#", "Barres d'outils#"),
                 ("MRO/Menus contextuels/", "Menus contextuels/"),
                 ("TITRE/Espacements#", "TITRES/Padding (titre seulement)#"),
                 ("TITRE/Fond/", "TITRES/Paragraphes/"),
                 ("TITRE/", "TITRES/"))


def _renamed_dims(dims: dict) -> dict:
    out = dict(dims)
    for key, value in dims.items():
        for old, new in _DIMS_RENAMES:
            if key.startswith(old):
                out.setdefault(new + key[len(old):], value)
                break
    # Tableaux lies : avant le lien, chaque niveau avait ses dimensions ; on part de celles du premier.
    for group, (prefix, shared) in _LINKED_TABLES.items():
        if shared not in out:
            legacy = sorted(k for k in out if k.startswith(prefix) and k != shared)
            if legacy:
                out[shared] = out[legacy[0]]
    # Barre de navigation : ses icones sont passees dans une sous-section (lignes differentes) — des dimensions par
    # ligne d'avant viseraient d'autres lignes : seules les largeurs restent.
    for key, rows in (("Barre de navigation#0", 4),):
        old = out.get(key)
        if isinstance(old, dict) and any(int(k[1:].split("c")[0]) >= rows for k in (old.get("split") or {})
                                         if k.startswith("r") and "c" in k):
            out[key] = {k: v for k, v in old.items() if k in ("width", "cols")}
            if key == "Barre de navigation#0":
                out.setdefault("Barre de navigation/Icônes#0", dict(out[key]))
    if isinstance(out.get("TITRES/Paragraphes#0"), dict):
        out["TITRES/Paragraphes#0"] = _shift_paragraph_rows(out["TITRES/Paragraphes#0"])
    for part in _TOGGLE_TABLE_PARTS:            # tableaux des toggles : on part de ceux du Toggle 1
        shared = f"Toggles/{part}#0"
        if shared not in out:
            legacy = sorted((k for k in out if re.fullmatch(rf"Toggles/[^/]+/{part}#0", k)),
                            key=lambda k: (k != f"Toggles/Toggle 1/{part}#0", k))
            if legacy:
                out[shared] = out[legacy[0]]
    return out


_ROW_KEYED = ("align", "split", "split_order", "split_align", "split_head_align", "split_titles")


def _shift_paragraph_rows(dims: dict) -> dict:
    """Paragraphes > Niveau N a recu 2 lignes (Padding (titre), Padding (paragraphe)) apres « Padding » :
    les dimensions enregistrees avant (5 lignes, la derniere au rang 4) decalent Bordures et Border
    radius de 2 rangs (r3 -> r5, r4 -> r6). Deja a 7 lignes : rien a faire."""
    rows = {int(k[1:].split("c")[0]) for k in (dims.get("split") or {}) if k.startswith("r") and "c" in k}
    if not rows or max(rows) != 4:
        return dims

    def shifted(key: str) -> str:
        row, _, col = key[1:].partition("c")
        return f"r{int(row) + 2}c{col}" if int(row) >= 3 else key

    out = dict(dims)
    for name in _ROW_KEYED:
        if isinstance(dims.get(name), dict):
            out[name] = {shifted(k): v for k, v in dims[name].items()}
    heights = list(dims.get("row_heights") or [])
    if len(heights) > 3:
        out["row_heights"] = heights[:3] + [0, 0] + heights[3:]
    return out


# Tableaux LIES : un meme tableau repete (un par niveau) n'a qu'UNE serie de dimensions. Modifier
# une largeur de colonne ou de sous-cellule, une hauteur de ligne, un ordre ou une justification
# dans l'un se reporte en direct sur tous les autres (_link_tables). {groupe: (prefixe des cles
# deduites des titres, cle partagee)}.
_LINKED_TABLES = {"paragraphes": ("TITRES/Paragraphes/", "TITRES/Paragraphes#0")}


def seed_table_look(settings: dict):
    """Etat de depart de l'habillage des tableaux (filets interieurs, padding, couleur d'entete, de
    selection, lignes deplacables) : chaque tableau le lit a sa creation."""
    colors = settings["colors"]
    set_table_bg(settings.get("table_bg_color"), colors)      # avant tout tableau : fond de ses lignes
    _set_table_inner_border(*(
        (settings[f"table_inner_{axis}_enabled"], _resolve_color_value(settings[f"table_inner_{axis}_color"], colors),
         settings[f"table_inner_{axis}_thickness"]) for axis in ("h", "v")))
    _set_flat_tables_style(padding=_padding_tuple(settings.get("table_cell_padding") or {}))
    _TABLE_HEAD["bg"] = _head_hex(colors, settings.get("table_head_color", "tableHead"))
    _TABLE_HEAD["cell_bg"] = _head_hex(colors, settings.get("table_cell_head_color", "tableHead"))
    _TABLE_SELECTION["color"] = _resolve_color_value(settings.get("table_selection_color", "#5f9bd0"), colors)
    _ROWS_MOVABLE["enabled"] = bool(settings.get("table_rows_movable", True))
    _set_table_shadow(shadow_look(settings, "table_shadow", lambda value: _resolve_color_value(value, colors)))
    seed_above_text_look(settings)         # textes au-dessus des lignes


# Restylages par famille sur une racine quelconque : la fenetre de reglages (ses methodes `_restyle_*`) et la
# fenetre principale (chemin rapide de l'aspect, main_window/settings_link.py).
def restyle_sliders_in(root: QWidget, merged: dict):
    """Curseurs de `root` (la fenetre de reglages, elle, les reprend tous : `_restyle_sliders`)."""
    _sync_slider_style(merged)
    for widget in root.findChildren(_MiniSlider):
        widget.apply_style()


def restyle_titles_in(root: QWidget, merged: dict):
    """Titres (niveaux 1-5) : polices, couleurs, retraits et paragraphes des _Section / _SubSection de `root`."""
    _sync_title_level_style(merged)
    for section in root.findChildren(_Section):
        section.apply_text_look()          # police, couleur ; overrides du titre deploye
        section._title_indent = _title_indent(1)
    for sub in root.findChildren(_SubSection):
        level = sub._level
        sub.apply_text_look()
        sub._left_margin = _subsection_left_margin(level)
    # Paragraphes (retrait, paddings, fond) : parents d'abord, l'abscisse d'un enfant en depend.
    titles = root.findChildren(_Section) + root.findChildren(_SubSection)
    depth = {t: sum(isinstance(a, (_Section, _SubSection)) for a in _ancestors(t)) for t in titles}
    for title in sorted(titles, key=depth.get):
        title.apply_box()
    for pane in root.findChildren(QFrame, "ThemeSideDetail"):
        getattr(pane, "refresh", pane.update)()   # volet de l'editeur fm_theme : fond, contour du titre deploye
    _reflow_all(root)


def restyle_toggles_in(root: QWidget, merged: dict):
    """Toggles de `root` (et cartes du choix de style)."""
    _sync_toggle_style(merged)        # registre : styles supprimes / renommes / ajoutes
    for toggle in root.findChildren(_Toggle):
        toggle.apply_style()
    for picker in root.findChildren(_ToggleStylePicker):
        picker.refreshPreviews()


def seed_table_globals(merged: dict) -> None:
    """Habillage GLOBAL des tableaux d'après `merged`, sans restyler aucun tableau construit (éditeur fm_theme : dessiner
    une variante non éditée, puis remettre l'habillage courant)."""
    from fm_theme.layout import _FLAT_TABLE_STYLE
    from fm_theme.widgets import _TABLE_SHADOW
    colors = merged.get("colors") or {}
    set_table_bg(merged.get("table_bg_color"), colors)
    _set_table_inner_border(*(
        (merged.get(f"table_inner_{axis}_enabled", True),
         _resolve_color_value(merged.get(f"table_inner_{axis}_color", "#2c3034"), colors),
         merged.get(f"table_inner_{axis}_thickness", 1)) for axis in ("h", "v")))
    _TABLE_HEAD["bg"] = _head_hex(colors, merged.get("table_head_color", "tableHead"))
    _TABLE_HEAD["cell_bg"] = _head_hex(colors, merged.get("table_cell_head_color", "tableHead"))
    _TABLE_SELECTION["color"] = _resolve_color_value(merged.get("table_selection_color", "#5f9bd0"), colors)
    _TABLE_SHADOW["look"] = shadow_look(merged, "table_shadow", lambda value: _resolve_color_value(value, colors))
    border_colors = {k: _resolve_color_value(v, colors) for k, v in (merged.get("table_border") or {}).items()}
    _FLAT_TABLE_STYLE.update(
        radius=int(merged.get("table_radius", 0)),
        border=(merged.get("table_border_enabled"), border_colors, int(merged.get("table_border_thickness", 1))),
        padding=_padding_tuple(merged.get("table_cell_padding") or {}))


def restyle_tables_in(root: QWidget, merged: dict):
    """Tableaux de `root` : habillage commun (filets, entetes, selection, ombre, rayon, bordure, padding)."""
    colors = merged["colors"]
    set_table_bg(merged.get("table_bg_color"), colors)        # fond des lignes, repris par _set_flat_tables_style
    enabled = merged.get("table_border_enabled")
    border_colors = {k: _resolve_color_value(v, colors) for k, v in (merged.get("table_border") or {}).items()}
    _set_table_inner_border(*(
        (merged[f"table_inner_{axis}_enabled"], _resolve_color_value(merged[f"table_inner_{axis}_color"], colors),
         merged[f"table_inner_{axis}_thickness"]) for axis in ("h", "v")))
    _TABLE_HEAD["bg"] = _head_hex(colors, merged.get("table_head_color", "tableHead"))
    _TABLE_HEAD["cell_bg"] = _head_hex(colors, merged.get("table_cell_head_color", "tableHead"))
    _TABLE_SELECTION["color"] = _resolve_color_value(merged.get("table_selection_color", "#5f9bd0"), colors)
    _ROWS_MOVABLE["enabled"] = bool(merged.get("table_rows_movable", True))
    _set_table_shadow(shadow_look(merged, "table_shadow", lambda value: _resolve_color_value(value, colors)))
    seed_above_text_look(merged)          # textes au-dessus des lignes (Tableaux > Texte au dessus)
    for head in root.findChildren(_ResizableTableHeader):
        for i in range(len(head._cells)):
            head._refresh_cell_style(i)
    for split in root.findChildren(SplitCell):
        split.update()
    for picker in root.findChildren(_ToggleStylePicker):
        picker.refreshPreviews()          # cartes : cadre des tableaux, couleur de selection
    _set_flat_tables_style(
        radius=int(merged.get("table_radius", 0)),
        border=(enabled, border_colors, int(merged.get("table_border_thickness", 1))),
        padding=_padding_tuple(merged.get("table_cell_padding") or {}), force=True)
    for widget in root.findChildren(_TableRow) + root.findChildren(_ResizableTableHeader):
        widget.update()          # les filets sont peints : un restyle a l'identique ne les repeint pas


def seed_window_look(settings: dict):
    """Style commun que les champs et tableaux lisent a leur creation (zones de saisie, palette,
    curseurs, toggles, titres, tableaux) : la fenetre v2, et toute fenetre flottante construite avec
    les memes briques (ex. settings_quick_style.QuickStyleWindow)."""
    _set_input_radius(int(settings.get("input_radius", 0)))
    _set_button_radius(int(settings.get("button_radius", 0)))
    set_tab_look(settings)
    _sync_dynamic_M(settings["colors"])
    _sync_slider_style(settings)
    _sync_toggle_style(settings)
    _sync_title_level_style(settings)
    _seed_flat_tables_style(int(settings.get("table_radius", 0)), (
        _coerce_side_enabled(settings.get("table_border_enabled", True)),
        {k: _resolve_color_value(v, settings["colors"]) for k, v in (settings.get("table_border") or {}).items()},
        int(settings.get("table_border_thickness", 1))))
    seed_table_look(settings)
    seed_extra_window_look(settings)       # fenetres additionnelles (cadre, ombre, barres)
    import settings_element_style          # « Override settings » (clic droit) + styles propres enregistres
    settings_element_style.load(settings)

# Tableaux des styles de toggle : tous les styles ont les MEMES tableaux (Type, Fond et Coche de chaque etat), lies
# d'un style a l'autre, nouveaux compris. Reconnus par leur groupe du CATALOG (le titre d'un style
# est renommable), cle partagee `Toggles/<tableau>#0`.
_TOGGLE_TABLE_PARTS = ("Type", "État")
# OFF et ON partagent les dimensions de leur tableau (memes lignes) : « Toggles/État#0 ».
_TOGGLE_TABLE_GROUP = re.compile(r"^toggle\d+ : (Type|OFF|ON)$")


def _linked_group(frame: QWidget):
    """(groupe, cle partagee) d'un tableau lie, sinon None."""
    key = frame.dimsKey()
    for group, (prefix, shared) in _LINKED_TABLES.items():
        if key.startswith(prefix):
            return group, shared
    node = frame.parentWidget()
    while node is not None and not isinstance(node, _LazyNode):
        node = node.parentWidget()
    match = _TOGGLE_TABLE_GROUP.match(node.node.group or "") if node is not None else None
    if match:
        part = "Type" if match.group(1) == "Type" else "État"
        return f"toggles:{part}", f"Toggles/{part}#0"
    if node is not None and re.fullmatch(r"Markdown : H[1-6]", node.node.group or ""):
        return "markdown:headings", "Markdown/Titres H1-H6#0"
    return None


def _space_menu_extra(widget: QWidget, menu) -> None:
    """Fournisseur de menu contextuel (voir settings_widgets.CONTEXT_MENU_EXTRAS) : seulement dans la v2."""
    window = widget.window()
    if isinstance(window, SettingsWindowV2):
        window.add_space_action(widget, menu)


CONTEXT_MENU_EXTRAS.append(_space_menu_extra)


def _toggle_title_menu_extra(widget: QWidget, menu) -> None:
    """Clic droit sur le titre d'un style de toggle (Toggles > <nom>) : renommer / supprimer."""
    window = widget.window()
    if not isinstance(window, SettingsWindowV2) or not isinstance(widget, _SectionHeader):
        return
    node = widget.parentWidget()
    while node is not None and not isinstance(node, _LazyNode):
        node = node.parentWidget()
    if node is not None and node.node.toggle_key:
        window.populate_toggle_menu(menu, node.node.toggle_key)


CONTEXT_MENU_EXTRAS.insert(0, _toggle_title_menu_extra)


def _markdown_reset_menu_extra(widget: QWidget, menu) -> None:
    """Clic droit sur un titre de l'onglet Markdown : « Restaurer les valeurs d'origine » de cette partie."""
    window = widget.window()
    if not isinstance(window, SettingsWindowV2) or not isinstance(widget, _SectionHeader):
        return
    node = widget.parentWidget()
    while node is not None and not isinstance(node, _LazyNode):
        node = node.parentWidget()
    if node is None or node._values.name not in (MARKDOWN_TAB, VIDEO_TAB, BOARD_TAB, MRO_TAB, CAD_TAB, DESIGN_TAB,
                                                         TABLEUR_TAB, ILL_TAB, PS_TAB, TYPO_TAB, PDF_TAB):
        return
    title = node.node.title
    menu.addAction(f"Restaurer les valeurs d'origine de « {title} »").triggered.connect(
        lambda _c=False, n=node: window.reset_to_defaults(n))


CONTEXT_MENU_EXTRAS.insert(0, _markdown_reset_menu_extra)


def node_groups(node: Node) -> list[str]:
    """Groupes du CATALOG d'un noeud et de tous ses descendants."""
    out = [node.group] if node.group else []
    for child in node.children:
        out += node_groups(child)
    return out


def group_default_values(groups) -> dict:
    """Valeurs d'origine (DEFAULT_SETTINGS) des cles des lignes de `groups`, « lier les 4 » compris."""
    from settings_store import DEFAULT_SETTINGS
    out = {}
    for group in groups:
        for spec in CATALOG.get(group, ()):
            keys = [spec.key, *spec.extra_keys, f"{spec.key}_linked"]
            if spec.kind == "font_gabarit":
                keys += [f"{spec.params['prefix']}_font_{name}" for name in ("family", "bold", "italic", "size", "color")]
            for key in keys:
                if key in DEFAULT_SETTINGS:
                    out[key] = copy.deepcopy(DEFAULT_SETTINGS[key])
    return out


def _toggle_style_listener(toggle: QWidget, key: str | None) -> None:
    """Style choisi au clic droit sur un toggle de la fenetre : enregistre pour CE toggle."""
    window = toggle.window()
    if isinstance(window, SettingsWindowV2):
        window._set_toggle_style(toggle, key)


TOGGLE_STYLE_LISTENERS.append(_toggle_style_listener)


# Apercu en direct : au plus un toutes les LIVE_MIN_MS (16 ms ~ une image a 60 Hz ; 30 ms avant, saccade signalee
# le 2026-11-10), et jamais plus souvent que deux fois son propre cout (le glisser garde la main).
LIVE_MIN_MS = 16

WIRED_SECTIONS = ("Général", "Colonnes", "Colonnes spéciales", "TITRES", "Tableaux", "Toggles", "Sliders", "Application", "Visionneuse",
                  "Menu contextuel", "Fenêtres additionnelles",
                  "Dossiers et fichiers à omettre", "LUT", "Polices principales", "Couleurs",
                  "Barre de navigation", "Barre d'état", "Bouton", "Tabs", "Barres d'outils", "Zone de saisie",
                  "ICONES")

# Enregistrement EN TEMPS REEL de ce qui n'est pas un reglage a valider : taille/position de la
# fenetre, dimensions des tableaux (largeur, colonnes, cellules, justifications) et plages des
# curseurs. Les tests le coupent.
AUTOSAVE = True
GEOMETRY_KEY = "v2"


class _TabGap(QWidget):
    """Zone de remplissage entre la barre de navigation et la barre des tabs (voir `_tab_gap`)."""


class _TabGapWatcher(QObject):
    """Cale la zone entre la barre de navigation et la barre des tabs (voir `_tab_gap`) quand l'une des deux bouge."""

    def __init__(self, window):
        super().__init__(window)
        self._window = window

    def eventFilter(self, obj, event):
        if event.type() in (QEvent.Move, QEvent.Resize, QEvent.Show, QEvent.Hide):
            QTimer.singleShot(0, self.place)
        return False

    def place(self):
        try:
            window = self._window
            top, bottom = window.titlebar.geometry(), window._tab_subbar.geometry()
            gap = QRect(bottom.x(), top.bottom() + 1, bottom.width(), bottom.y() - top.bottom() - 1)
            window._tab_gap.setVisible(gap.height() > 0)
            window._tab_gap.setGeometry(gap)
            window._tab_gap.lower()
        except RuntimeError:
            pass


class AppSettingsStore:
    """Magasin par defaut de la fenetre : les reglages de l'appli (pipeline_settings.json, preset actif, preset
    fm_theme lie). On relit le disque a chaque ecriture : une autre fenetre a pu enregistrer entre-temps."""

    def load(self) -> dict:
        return load_settings()

    def save_partial(self, partial: dict, drop: tuple = ()) -> None:
        """Etat enregistre au fil de l'eau (dimensions, styles de toggle...) : ecrit tel quel."""
        settings = load_settings()
        settings.update(partial)
        for key in drop:
            settings.pop(key, None)
        save_settings(settings)

    def save_row_templates(self, templates: dict) -> None:
        """Gabarits de lignes : dans le preset fm_theme LIE (rien sans theme lie : ils restent dans la session)."""
        import fm_theme.presets as theme_presets
        from settings_store import theme_in_use
        name = theme_in_use(load_settings())
        if name:
            theme_presets.save_row_templates(name, templates)

    def save_changes(self, changed: dict) -> dict:
        """Enregistrer : seules les cles modifiees par la fenetre ; le preset actif (et le preset fm_theme lie)
        les retient aussi. Retourne les reglages enregistres."""
        settings = load_settings()
        settings.update(changed)
        save_settings(settings)
        update_active_preset(settings)
        return settings


def _set_icon_margin(settings: dict) -> bool:
    """Marge des icones (Theme > General, `icon_margin`) ; changee : caches d'icones vides (fm_theme.icon_frame) et
    toutes les fenetres repeintes (chaque icone refaite a sa peinture)."""
    from fm_theme.icon_frame import set_margin
    if not set_margin(settings.get("icon_margin", 20)):
        return False
    for window in QApplication.topLevelWidgets():
        window.update()
    return True


def _set_icon_style(settings: dict) -> bool:
    """Style des icones du catalogue (Theme > General, `icon_library_style`) et couleur des icones ; change : les
    fenetres sont repeintes (abonnes de fm_theme.icon_library deja prevenus)."""
    from browser_core_parts.settings import apply_icon_style
    if not apply_icon_style(settings):
        return False
    for window in QApplication.topLevelWidgets():
        window.update()
    return True


def _set_dimmed_value(settings: dict) -> bool:
    """Valeurs du grise (Theme > General : elements d'interface, textes, icones) ; vrai si une a change."""
    from fm_theme.widgets import set_dimmed_values
    return set_dimmed_values(settings.get("dimmed_opacity", 20), settings.get("dimmed_text_opacity", 20),
                             settings.get("dimmed_icon_opacity", 20))


class SettingsWindowV2(QDialog):
    """Fenetre comparative. `build_seconds` = temps de construction du
    constructeur ; `page_seconds[label]` = temps de chaque onglet a sa
    premiere visite ; `widget_count` = widgets vivants a l'ouverture."""

    # apercu en direct (rien n'est ecrit sur le disque) ; `object` : le dict passe tel quel (en `dict`, Qt le
    # convertissait a chaque tick, ~8 ms pour tous les reglages : apercu saccade, signale le 2026-11-10)
    settingsChanged = Signal(object)
    settingsSaved = Signal(dict)       # apres Enregistrer
    moduleSettingsRequested = Signal(str)   # fenetre generale : bouton d'un module (cle de MODULE_SCOPES)
    themeEditorRequested = Signal()         # fenetre generale : bouton « Thème » (editeur fm_theme)

    _RESIZE_BORDER = 6

    def __init__(self, parent=None, eager: bool = False, module: str | None = None, store=None):
        super().__init__(parent)
        t0 = time.perf_counter()
        # module=None : fenetre generale ; sinon fenetre du module (cle de MODULE_SCOPES), meme fonctionnement.
        self.module = module
        # Ou lire / ecrire : les reglages de l'appli (AppSettingsStore) ou un preset fm_theme (theme_editor.ThemeStore).
        self._store = store or AppSettingsStore()
        self.scopes = MODULE_SCOPES[module] if module else SCOPES
        self.eager = eager   # eager=True : construit TOUT d'un coup (pour mesurer l'apport du differe)
        self.setWindowFlags(Qt.Dialog | Qt.FramelessWindowHint)
        self.setAttribute(Qt.WA_TranslucentBackground, True)
        self.resize(760, 820)
        self.setMinimumSize(640, 480)
        self._restore_geometry()

        self.settings = self._store.load()
        from fm_video.help_ui import HelpController
        self._color_help = HelpController(self,self.settings)
        self._original_settings = json.loads(json.dumps(self.settings))
        self._saved = False
        self._dirty = False
        self._last_live_snapshot = None
        self._last_slider_sig = None
        # Apercu en direct : regroupe les rafales (glisser un curseur) comme l'ancienne fenetre.
        self._live_timer = QTimer(self)
        self._live_timer.setInterval(LIVE_MIN_MS)
        self._live_timer.setSingleShot(True)
        self._live_timer.timeout.connect(self._flush_live)
        # Aspect change dans l'editeur fm_theme (`follow_theme`) : regroupe, cadence adaptee a son cout.
        self._theme_pending: dict = {}
        self._theme_timer = QTimer(self)
        self._theme_timer.setInterval(16)
        self._theme_timer.setSingleShot(True)
        self._theme_timer.timeout.connect(self._flush_theme)
        # Enregistrement en temps reel (taille de la fenetre, dimensions des tableaux) : regroupe
        # les rafales d'un glissement, ecrit ~0,4 s apres le dernier mouvement.
        self._persist_timer = QTimer(self)
        self._persist_timer.setInterval(400)
        self._persist_timer.setSingleShot(True)
        self._persist_timer.timeout.connect(self._persist_now)
        # Memes prerequis de style que SettingsWindow.__init__ : les widgets
        # lisent ces reglages a leur creation.
        # Gabarits de lignes : ceux du preset fm_theme (`row_templates`, partages par toutes les applis du theme)
        # font reference. Sans eux : ceux deja poses dans cette session (une fenetre qui s'ouvre les effacait :
        # bug signale), puis ceux de l'ancien rangement (`table_dims`, cle « @lignes ») — recopies dans le preset.
        session_rows = copy.deepcopy(_TABLE_DIMS.get(ROW_TEMPLATES_KEY) or {})
        _set_table_dims(_renamed_dims(self.settings.get("table_dims") or {}))
        theme_rows = self.settings.get("row_templates")
        if theme_rows:
            _TABLE_DIMS[ROW_TEMPLATES_KEY] = copy.deepcopy(theme_rows)
        elif session_rows:
            _TABLE_DIMS[ROW_TEMPLATES_KEY] = {**(_TABLE_DIMS.get(ROW_TEMPLATES_KEY) or {}), **session_rows}
        settings_cells.add_row_template_listener(self._save_row_templates)
        if not theme_rows and _TABLE_DIMS.get(ROW_TEMPLATES_KEY):
            self._save_row_templates(copy.deepcopy(_TABLE_DIMS[ROW_TEMPLATES_KEY]))
        seed_window_look(self.settings)
        # Override d'un element enregistre pendant que la fenetre est ouverte : sa copie des
        # reglages (renvoyee par l'apercu en direct) le connait aussi.
        import settings_element_style
        settings_element_style.add_listener(self._on_element_style_saved)
        from settings_theme import apply_input_look
        apply_input_look(self.settings)          # zones de saisie creees ensuite : deja a la bonne valeur
        self._columns_resizable = bool(self.settings.get("columns_resizable", True))
        self._style_sigs: dict[str, str] = {}
        self.stores: dict[str, dict] = {}        # par onglet : fields / toggles / resizers / specs
        self.page_seconds: dict[str, float] = {}
        self._built: set[int] = set()

        panel = self.panel = _PanelFrame(self)
        panel.setColors(M["panel_bg"], M["panel_border"])
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.addWidget(panel)
        root = QVBoxLayout(panel)
        root.setContentsMargins(1, 1, 1, 1)
        root.setSpacing(0)
        title = f"Réglages : {MODULE_TITLES.get(module, module)}" if module else "Réglages"
        self.titlebar = _SettingsTitleBar(self, title=title)
        self.titlebar.closeClicked.connect(self.reject)
        self.titlebar.saveClicked.connect(self._on_apply)      # clic sur « modifications non enregistrees »
        root.addWidget(self.titlebar)

        subbar = self._tab_subbar = QWidget()
        subbar.setStyleSheet(self._tab_bar_css(self.settings))
        # Espace (reglage « espace au-dessus ») entre la barre de navigation et les tabs : meme couleur que la barre
        # des tabs, donc que la barre de navigation par defaut (une zone `panel_bg` plus claire s'y voyait).
        self._tab_gap = _TabGap(panel)           # classe a part : les chemins de widgets (`widget_path`) comptent par classe
        self._tab_gap.setObjectName("TabGap")
        self._tab_gap.setAttribute(Qt.WA_StyledBackground, True)
        self._tab_gap.setStyleSheet(f"#TabGap {{ background: {self._tab_strip_color(self.settings)}; }}")
        self._tab_gap.lower()
        self._tab_gap_watch = _TabGapWatcher(self)
        subbar.installEventFilter(self._tab_gap_watch)
        self.titlebar.installEventFilter(self._tab_gap_watch)
        sl = QHBoxLayout(subbar)
        sl.setContentsMargins(20, 0, 20, 0)
        self.tabs = _TabStrip([TAB_LABELS.get(label, label) for label, _t in self.scopes])
        self.tabs.setVisible(len(self.scopes) > 1)          # un seul onglet : rien a choisir
        sl.addWidget(self.tabs)
        root.addWidget(subbar)

        self.stack = QStackedWidget(panel)
        root.addWidget(self.stack, 1)
        for _label, _title in self.scopes:
            self.stack.addWidget(QWidget())      # emplacement, remplace a la premiere visite
        self.tabs.changed.connect(self._show_page)

        self.status = QLabel("")
        self.status.setStyleSheet(f"color: {M['label_dim']}; background: {M['toolbar_bg']}; padding: 6px 20px;")
        root.addWidget(self.status)
        buttons = self._build_bottom_bar()
        root.addWidget(buttons)
        install_extra_window(self, panel, outer, root, self.titlebar, buttons)   # Fenetres additionnelles

        if eager:
            for i in range(len(self.scopes)):
                self._ensure_page(i)
        else:
            self._ensure_page(0)
        self.stack.setCurrentIndex(0)
        self.build_seconds = time.perf_counter() - t0
        self._refresh_status()

    # -- enregistrement en temps reel --

    def _geometry_key(self) -> str:
        return f"{GEOMETRY_KEY}:{self.module}" if self.module else GEOMETRY_KEY

    def _restore_geometry(self):
        geometry = _load_window_geometry(self._geometry_key()) if AUTOSAVE else None
        if geometry:
            try:
                self.restoreGeometry(QByteArray.fromBase64(geometry.encode("ascii")))
            except (ValueError, TypeError):
                pass

    def _schedule_persist(self, *_args):
        if AUTOSAVE and self.isVisible():
            self._persist_timer.start()      # relance : on n'ecrit qu'a la fin du geste

    def _schedule_persist_frame(self, frame):
        """Un tableau signale un changement de dimensions : SEUL lui sera relu a l'enregistrement (relire les
        ~130 tableaux coutait ~0,35 s, et un simple restylage les signale tous)."""
        dirty = self.__dict__.setdefault("_dims_dirty", set())
        dirty.add(frame)
        self._schedule_persist()

    def _autosave(self, partial: dict, drop: tuple = ()):
        """Ecrit `partial` sur le disque tout de suite, sans toucher au reste (relit le disque : une
        autre fenetre a pu enregistrer entre-temps) — comme le fait _on_save. `drop` : cles a retirer
        (reglages d'un style de toggle supprime)."""
        self._store.save_partial(partial, drop)
        self.settings.update(partial)
        self._original_settings.update(json.loads(json.dumps(partial)))
        for key in drop:
            self.settings.pop(key, None)
            self._original_settings.pop(key, None)

    def _write_now(self, partial: dict, drop: tuple = ()):
        """Etat a garder tout de suite (styles de toggle crees/renommes/supprimes) : sur le disque si
        l'enregistrement en temps reel est actif, sinon dans les reglages de la fenetre."""
        if AUTOSAVE:
            self._autosave(partial, drop)
            return
        self.settings.update(partial)
        for key in drop:
            self.settings.pop(key, None)

    def _persist_now(self):
        if not AUTOSAVE:
            return
        if self.isVisible():
            _save_window_geometry(bytes(self.saveGeometry().toBase64()).decode("ascii"), self._geometry_key())
        dirty, self._dims_dirty = getattr(self, "_dims_dirty", set()), set()
        updates = {}
        for frame in dirty:
            try:
                if frame._dims_applied:      # un tableau jamais affiche n'a pas encore ses dimensions
                    updates[frame.dimsKey()] = frame.collectDims()
            except RuntimeError:             # tableau detruit depuis
                pass
        dims = dict(self.settings.get("table_dims") or {})
        if updates:
            # Seuls les tableaux modifies, sur ce qui est DEJA sur le disque : avant, toute la copie prise a
            # l'ouverture etait reecrite, et une autre fenetre (fm_theme lance a part, fm_browser) effacait les
            # largeurs que l'on venait d'enregistrer (signale : tableaux de la barre de navigation, 2026-11-07).
            dims = {**(load_settings().get("table_dims") or {}), **updates}
        dims.pop(ROW_TEMPLATES_KEY, None)          # gabarits de lignes : dans le preset fm_theme (_save_row_templates)
        if dims != (self.settings.get("table_dims") or {}):
            rows = _TABLE_DIMS.get(ROW_TEMPLATES_KEY)
            _set_table_dims(dims)
            if rows:
                _TABLE_DIMS[ROW_TEMPLATES_KEY] = rows
            self._autosave({"table_dims": dims})
        for key in ("element_spaces", "element_spaces_below", "title_order", "toggle_style_overrides"):
            state = self.settings.get(key) or {}
            if state != (self._original_settings.get(key) or {}):
                self._autosave({key: dict(state)})

    def _add_toggle_style(self):
        name, ok = QInputDialog.getText(self, "Nouveau toggle", "Nom du nouveau toggle :")
        if ok and name.strip():
            self.add_toggle_style(name.strip())

    def _unique_toggle_name(self, name: str, own_key: str | None = None) -> str:
        taken = {s["name"] for s in toggle_style_list(self.settings) if s["key"] != own_key}
        unique, n = name, 2
        while unique in taken:
            unique, n = f"{name} ({n})", n + 1
        return unique

    def add_toggle_style(self, name: str, source: str | None = None) -> str:
        """Cree un style de toggle (reglages copies sur le style par defaut, enregistres tout de suite),
        sa sous-section Toggles > <nom> (Type, État OFF, État ON) et sa carte dans le choix du style."""
        styles = toggle_style_list(self.settings)
        taken = {s["key"] for s in styles} | {"toggle1", "toggle2"}
        number = 3
        while f"toggle{number}" in taken:
            number += 1
        key = f"toggle{number}"
        name = self._unique_toggle_name(name)
        current = self.current_values()
        source = source or current.get("toggle_style")             # copie du style donné (volet des variantes)
        source = source if source in {s["key"] for s in styles} else styles[0]["key"]
        partial = {f"{key}_{k[len(source) + 1:]}": copy.deepcopy(v)
                   for k, v in current.items() if k.startswith(f"{source}_")}
        partial["toggle_styles"] = styles + [{"key": key, "name": name}]
        partial["toggle_custom_styles"] = []         # ancienne liste : fondue dans toggle_styles
        self._write_now(partial)
        register_toggle_catalog(key)
        _sync_toggle_style(self.current_values())
        for picker in self.findChildren(_ToggleStylePicker):
            picker.addOption(key, name)
        for node in self.findChildren(_LazyNode):
            if node.level == 1 and node.node.title == "Toggles" and node._built:
                node.add_child(_toggle_style_node(key, name))
        return key

    def rename_toggle_style(self, key: str, name: str) -> str | None:
        """Renomme un style (carte, sous-section, menus « Style du toggle ») ; enregistre aussitot."""
        name = name.strip()
        styles = toggle_style_list(self.settings)
        if not name or key not in {s["key"] for s in styles}:
            return None
        name = self._unique_toggle_name(name, key)
        styles = [dict(s, name=name) if s["key"] == key else s for s in styles]
        self._write_now({"toggle_styles": styles, "toggle_custom_styles": []})
        _TOGGLE_STYLE_NAMES[key] = name
        for picker in self.findChildren(_ToggleStylePicker):
            picker.renameOption(key, name)
        for node in self.findChildren(_LazyNode):
            if node.node.toggle_key == key:
                node.node = replace(node.node, title=name)
                node._head._title_text = name
                node._head._name_label.setText(name.upper())
        return name

    def delete_toggle_style(self, key: str) -> bool:
        """Supprime un style (jamais le dernier) : sa carte, sa sous-section, ses reglages. Les toggles
        qui l'utilisaient reprennent le style par defaut."""
        styles = toggle_style_list(self.settings)
        if len(styles) <= 1 or key not in {s["key"] for s in styles}:
            return False
        styles = [s for s in styles if s["key"] != key]
        for node in list(self.findChildren(_LazyNode)):
            if node.node.toggle_key == key:
                self._remove_node(node)
        for picker in self.findChildren(_ToggleStylePicker):
            picker.removeOption(key)        # s'il etait choisi, le premier restant le devient
        partial = {"toggle_styles": styles, "toggle_custom_styles": [],
                   "toggle_style_overrides": {k: v for k, v in (self.settings.get("toggle_style_overrides") or {}).items()
                                              if v != key}}
        if self.settings.get("toggle_style") == key:
            partial["toggle_style"] = styles[0]["key"]
        # Reglages du style : retires (sauf toggle1/toggle2, dont les cles par defaut existent toujours).
        drop = tuple(k for k in self.settings if k.startswith(f"{key}_")) if key not in ("toggle1", "toggle2") else ()
        self._write_now(partial, drop)
        unregister_toggle_catalog(key)
        self._restyle_toggles(self.current_values())
        return True

    def _remove_node(self, node: "_LazyNode"):
        """Retire une sous-section construite : voisins recolles, champs oublies par la fenetre."""
        parent = logical_parent(node)
        while parent is not None and not isinstance(parent, _LazyNode):
            parent = logical_parent(parent)
        siblings = getattr(parent, "_child_nodes", None) if parent is not None else None
        prev = nxt = None
        if siblings is not None and node in siblings:
            i = siblings.index(node)
            prev = siblings[i - 1]._head if i > 0 else None
            nxt = siblings[i + 1]._head if i + 1 < len(siblings) else None
            if prev is not None:
                prev._box_next = nxt
            if nxt is not None:
                nxt._box_prev = prev
            siblings.pop(i)

        def inside(widget) -> bool:
            return isinstance(widget, QWidget) and (widget is node or node.isAncestorOf(widget))

        for store in self.stores.values():
            if "specs" in store:
                store["specs"][:] = [(s, w) for s, w in store["specs"] if not inside(w)]
            if "resizers" in store:
                store["resizers"][:] = [w for w in store["resizers"] if not inside(w)]
            for name in ("fields", "toggles"):
                for k in [k for k, w in store.get(name, {}).items() if inside(w)]:
                    del store[name][k]
        node.hide()
        node.setParent(None)
        node.deleteLater()
        for title in (prev, nxt):
            if title is not None:
                title.apply_box()
        if parent is not None:
            parent._child_refresh()

    def reset_to_defaults(self, node: "_LazyNode"):
        """Restaure les valeurs d'origine d'une partie de l'onglet Markdown (et de ses sous-parties) : les champs
        montrent aussitot les valeurs d'origine, l'apercu suit ; rien n'est enregistre avant Appliquer /
        Enregistrer (Annuler revient en arriere)."""
        groups = node_groups(node.node)
        defaults = group_default_values(groups)
        if not defaults:
            return
        self.settings.update(copy.deepcopy(defaults))
        pending = [node]
        while pending:                       # tout est construit : les valeurs restaurees sont lues et enregistrees
            current = pending.pop()
            current._build()
            pending += list(getattr(current, "_child_nodes", []))
        for lazy in self.findChildren(_LazyNode):
            if lazy._built and lazy.node.group in groups:
                lazy.rebuild_group()
        self._mark_dirty()

    def populate_toggle_menu(self, menu: QMenu, key: str):
        """Lignes « Renommer le toggle… » / « Supprimer le toggle » (grisee s'il ne reste qu'un style)."""
        menu.addAction("Renommer le toggle…").triggered.connect(lambda _c=False: self._ask_rename_toggle(key))
        delete = menu.addAction("Supprimer le toggle")
        delete.setEnabled(len(toggle_style_list(self.settings)) > 1)
        delete.triggered.connect(lambda _c=False: self._ask_delete_toggle(key))

    def _ask_rename_toggle(self, key: str):
        current = _TOGGLE_STYLE_NAMES.get(key, key)
        name, ok = QInputDialog.getText(self, "Renommer le toggle", "Nouveau nom :", text=current)
        if ok and name.strip() and name.strip() != current:
            self.rename_toggle_style(key, name)

    def _ask_delete_toggle(self, key: str):
        name = _TOGGLE_STYLE_NAMES.get(key, key)
        answer = QMessageBox.question(self, "Supprimer le toggle",
                                      f"Supprimer le style « {name} » et ses réglages ?")
        if answer == QMessageBox.Yes:
            self.delete_toggle_style(key)

    # -- style choisi pour un toggle (clic droit sur le toggle) --

    def _toggle_id(self, toggle: _Toggle) -> str | None:
        if toggle.style_id:
            return toggle.style_id
        path = widget_path(toggle, self)
        return f"ui:{path}" if path else None

    def _set_toggle_style(self, toggle: _Toggle, key: str | None):
        toggle_id = self._toggle_id(toggle)
        if toggle_id is None:
            return
        overrides = dict(self.settings.get("toggle_style_overrides") or {})
        if key:
            overrides[toggle_id] = key
        else:
            overrides.pop(toggle_id, None)
        self.settings["toggle_style_overrides"] = overrides
        self._schedule_persist()

    def _apply_toggle_styles(self):
        """Style choisi a la main pour chaque toggle deja construit (une fois par toggle)."""
        overrides = self.settings.get("toggle_style_overrides") or {}
        if not overrides:
            return
        for toggle in self.findChildren(_Toggle):
            if getattr(toggle, "_style_restored", False):
                continue
            toggle._style_restored = True
            key = overrides.get(self._toggle_id(toggle))
            if key:
                toggle.setStyleKey(key)

    def _on_range(self, key: str, low: int, high: int):
        """Clic droit sur un curseur > Modifier la plage : enregistre tout de suite."""
        ranges = dict(self.settings.get("slider_ranges") or {})
        ranges[key] = [low, high]
        if AUTOSAVE:
            self._autosave({"slider_ranges": ranges})
        else:
            self.settings["slider_ranges"] = ranges

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._schedule_persist()

    def moveEvent(self, event):
        super().moveEvent(event)
        self._schedule_persist()

    def done(self, result):
        if self._persist_timer.isActive():
            self._persist_timer.stop()
            self._persist_now()
        super().done(result)

    # -- redimensionnement par les bords (meme mecanisme que SettingsWindow) --

    def showEvent(self, event):
        super().showEvent(event)
        # WS_THICKFRAME cote Windows : sans lui nativeEvent n'aurait aucun bord a saisir.
        apply_dwm_frame(self, 0, "none", resizable=True)      # cadre et ombre peints (fenetre additionnelle)
        if not getattr(self, "_prebuild_started", False) and not self.eager and self.PREBUILD:
            self._prebuild_started = True
            QTimer.singleShot(400, self._prebuild_step)       # sections construites en douce, hors de la vue

    def nativeEvent(self, eventType, message):
        if eventType == b"windows_generic_MSG":
            result = resize_hit_test(self, message, self._RESIZE_BORDER, shadow_margins(self))
            if result is not None:
                return result
        return super().nativeEvent(eventType, message)

    # -- barre du bas, valeurs, apercu en direct, enregistrement --

    def _build_bottom_bar(self) -> QWidget:
        bar = QWidget()
        bar.setFixedHeight(46)
        bar.setStyleSheet(f"background: {M['toolbar_bg']}; border-top: 1px solid {M['panel_border']};")
        lay = QHBoxLayout(bar)
        lay.setContentsMargins(14, 0, 14, 0)
        lay.setSpacing(8)
        if self.module is None:
            # Reglages des modules, ouvrables aussi module ferme (choix de l'utilisateur, 2026-10-29).
            for module, label in MODULE_TITLES.items():
                button = _Btn(label, M["btn_bg"], M["btn_border"], M["btn_fg"], M["btn_hover"],
                              height=27, padding="0 13px")
                button.clicked.connect(lambda _c=False, m=module: self.moduleSettingsRequested.emit(m))
                lay.addWidget(button)
            # Aspect generique (couleurs, polices, toggles, tableaux...) : l'editeur fm_theme, sur le preset lie.
            theme = _Btn("Thème", M["accent"], M["accent_border"], M["accent_fg"], M["accent_hover"],
                         height=27, weight=600, padding="0 13px")
            theme.clicked.connect(self.themeEditorRequested.emit)
            lay.addWidget(theme)
        lay.addStretch(1)
        cancel = _Btn("Annuler", M["btn_bg"], M["btn_border"], M["btn_fg"], M["btn_hover"],
                      height=27, padding="0 13px")
        cancel.clicked.connect(self.reject)
        lay.addWidget(cancel)
        # Appliquer = enregistrer SANS fermer (demande de l'utilisateur) : Annuler ne revient plus
        # qu'a l'etat applique.
        apply = _Btn("Appliquer", M["btn_bg"], M["btn_border"], M["btn_fg"], M["btn_hover"],
                     height=27, padding="0 13px")
        apply.clicked.connect(self._on_apply)
        lay.addWidget(apply)
        save = _Btn("Enregistrer", M["accent"], M["accent_border"], M["accent_fg"], M["accent_hover"],
                    height=27, weight=600, padding="0 17px")
        save.clicked.connect(self._on_save)
        lay.addWidget(save)
        return bar

    def _show_dirty(self, dirty: bool):
        """Etat « modifications non enregistrees » : texte de la barre de titre ET bordure de la fenetre en
        rouge (demande de l'utilisateur) — bordure peinte du panneau et filet DWM de Windows ; ne touche au
        cadre que quand l'etat change (le filet DWM coute ~20 ms)."""
        self._dirty = dirty
        self.titlebar.set_dirty(dirty)
        if getattr(self, "_frame_dirty", None) == dirty:
            return
        self._frame_dirty = dirty
        self.panel.setAlert(M["dirty_frame"] if dirty else None)      # bordure peinte du panneau

    def _mark_dirty(self):
        self._show_dirty(True)
        # PAS de restart() : on laisse tourner le minuteur en cours, pour appliquer toutes les
        # 30 ms PENDANT un glissement (relancer l'echeance a chaque mouvement n'appliquait rien
        # avant la fin du geste, d'ou des sauts). Meme logique que SettingsWindow._mark_dirty.
        if not self._live_timer.isActive():
            self._live_timer.start()

    def wired_values(self) -> dict:
        """Valeurs COURANTES de tous les champs branches deja construits (les
        sections jamais ouvertes n'existent pas : leurs cles restent celles du disque)."""
        out: dict = {}
        for store in self.stores.values():
            for spec, widget in store.get("specs", ()):
                if isinstance(spec, str):                 # interrupteur d'override du General
                    out[spec] = widget.isChecked()
                else:
                    out.update(read_spec(spec, widget))
        palette = {k[len("colors:"):]: out.pop(k) for k in [k for k in out if k.startswith("colors:")]}
        if palette:                                  # Couleurs : fondues dans la palette
            out["colors"] = {**(self.settings.get("colors") or {}), **palette}
        return out

    def current_values(self) -> dict:
        merged = dict(self.settings)
        merged.update(self.wired_values())
        return merged

    # Familles de reglages qui habillent la FENETRE elle-meme : (prefixes de cles, restyleur). Rejouees
    # seulement si leurs valeurs ont change (comme les court-circuits de SettingsWindow).
    def _looks(self) -> dict:
        return {
            "sliders": (("slider_",), self._restyle_sliders),
            "titles": (("title_level",), self._restyle_titles),
            "tables": (("table_", "columns_resizable"), self._restyle_tables),
            "toggles": (("toggle",), self._restyle_toggles),
            "geometry": (("input_radius", "button_radius"), self._restyle_geometry),
            "tabs": (("tabs_", "colors", "extra_window_title_bg"), self._restyle_tabs),
            "palettes": (("palette_", "colors"), self._restyle_palettes),
            "inputs": (("input_", "colors"), self._restyle_inputs),
            "colors": (("colors",), self._restyle_colors),
            # Fenetres additionnelles (celle-ci comprise) : en direct.
            "extra_windows": (("extra_window_", "window_border", "colors"), seed_extra_window_look),
            # Valeur du grise (Theme > General) : objets deja grises mis a jour en direct (editeur fm_theme seul aussi).
            "dimmed": (("dimmed_",), lambda merged: _set_dimmed_value(merged)),
            # Marge des icones (Theme > General) : toutes les icones refaites en direct (editeur fm_theme seul aussi).
            "icon_margin": (("icon_margin",), lambda merged: _set_icon_margin(merged)),
            "icon_library_style": (("icon_library_style", "navtool_icon_base_color"),
                                   lambda merged: _set_icon_style(merged)),
        }

    def _apply_look(self, merged: dict, values: dict | None = None):
        """Restyle la fenetre pour les familles dont les valeurs ont change. `values=None` : toutes
        (retour aux valeurs d'origine)."""
        for name, (prefixes, restyle) in self._looks().items():
            if values is not None:
                subset = {k: v for k, v in values.items() if k.startswith(prefixes)}
                if not subset:
                    continue
                sig = json.dumps(subset, sort_keys=True, default=str)
                if sig == self._style_sigs.get(name):
                    continue
                self._style_sigs[name] = sig
            restyle(merged)
        import settings_element_style            # un restylage general ne doit pas effacer un override
        settings_element_style.reapply_soon(self, self.settings)

    def _flush_live(self):
        # Une bascule de toggle est en cours : l'apercu en direct (~50 ms sur le fil de l'interface)
        # attend sa fin, sinon le toggle reste fige puis saute a la fin de sa course.
        left = toggle_animation_left_ms()
        if left > 0:
            self._live_timer.start(left + 8)
            return
        self._live_timer.setInterval(LIVE_MIN_MS)
        values = self.wired_values()                  # une seule lecture des champs
        merged = dict(self.settings)
        merged.update(values)
        self._color_help.settings = merged
        # Valeurs des champs de l'apercu precedent (un dict : la copie JSON de TOUS les reglages, faite et relue a
        # chaque tick, coutait ~4 ms)
        if values == self._last_live_snapshot:         # rien n'a reellement change : on n'embete personne
            return
        previous, self._last_live_snapshot = self._last_live_snapshot, values
        start = time.perf_counter()
        # Seulement ce qui a CHANGE depuis l'apercu precedent (ou depuis l'ouverture) : au premier changement,
        # toutes les familles etaient rejouees (tableaux : ~2 s sur une fenetre entierement construite).
        base = previous if previous is not None else self._original_settings

        changed = {k: v for k, v in values.items() if v != base.get(k)}
        self._apply_look(merged, changed)
        # Cles REELLEMENT changees par ce geste : la fenetre principale s'en sert pour choisir son chemin rapide
        # (comparer aux reglages appliques y ajoutait des cles a l'ecriture differente, au 1er changement :
        # tout etait rafraichi, ~2 s).
        self.live_changed_keys = set(changed)
        self.settingsChanged.emit(merged)
        # Cadence ADAPTEE au cout de l'apercu : au moins autant de temps libre que de travail, sinon un
        # glisser (couleur, curseur) n'a plus la main et l'interface rame (signale).
        spent = int((time.perf_counter() - start) * 1000)
        self._live_timer.setInterval(max(LIVE_MIN_MS, 2 * spent))

    # -- restylages de la fenetre elle-meme (equivalents de SettingsWindow._apply_*) --

    def _restyle_colors(self, merged: dict):
        """Section Couleurs changee (ou preset change fenetre ouverte) : la palette PARTAGEE par toutes les
        sections (`self.settings["colors"]`, donnee aux sections construites ET a venir) est mise a jour SUR
        PLACE, et chaque champ couleur la reprend (menu des pastilles de l'appli, pastille « @slot »). Avant,
        les champs gardaient la palette de l'ouverture : leurs menus ne correspondaient plus a la section
        Couleurs (signale)."""
        palette = self.settings.get("colors")
        new = merged.get("colors")
        if not isinstance(palette, dict) or not isinstance(new, dict):
            return
        if new is not palette:
            fresh = dict(new)
            palette.clear()
            palette.update(fresh)
        for widget in self.findChildren(QWidget):
            refresh = getattr(widget, "refresh_colors", None)
            if refresh is None:
                continue
            try:
                refresh(palette)
            except TypeError:
                refresh()

    def _restyle_geometry(self, merged: dict):
        # Zones de saisie et boutons inscrits (settings_theme) : leur arrondi suit Geometrie.
        _set_input_radius(int(merged.get("input_radius", 0)))
        _set_button_radius(int(merged.get("button_radius", 0)))

    @staticmethod
    def _tab_strip_color(look: dict) -> str:
        """Fond de la barre des tabs (« Couleur sous les tabs ») ; transparent = la couleur de la BARRE DE
        NAVIGATION de la fenetre (Fenetres additionnelles > couleur de la barre)."""
        from PySide6.QtGui import QColor
        from settings_store import _resolve_color_value
        colors = look.get("colors") or {}
        value = _resolve_color_value(look.get("tabs_strip_color") or "#00000000", colors)
        title = _resolve_color_value(look.get("extra_window_title_bg") or M["toolbar_bg"], colors)
        return value if QColor(value).alpha() else title

    @staticmethod
    def _tab_bar_css(look: dict) -> str:
        """Fond et filet bas de la barre des tabs."""
        from settings_store import _resolve_color_value
        colors = look.get("colors") or {}
        color = SettingsWindowV2._tab_strip_color(look)
        if not look.get("tabs_bottom_enabled", True):
            return f"background: {color}; border-bottom: none;"
        try:
            width = max(0, int(look.get("tabs_bottom_thickness", 1)))
        except (TypeError, ValueError):
            width = 1
        line = _resolve_color_value(look.get("tabs_bottom_color") or M["panel_border"], colors)
        return f"background: {color}; border-bottom: {width}px solid {line};" if width else             f"background: {color}; border-bottom: none;"

    def _restyle_tabs(self, merged: dict):
        set_tab_look(merged)
        bar = getattr(self, "_tab_subbar", None)
        if bar is not None:
            bar.setStyleSheet(self._tab_bar_css(merged))
            self._tab_gap.setStyleSheet(f"#TabGap {{ background: {self._tab_strip_color(merged)}; }}")
        for tabs in self.findChildren(_TabStrip):
            tabs._refresh()

    def _restyle_inputs(self, merged: dict):
        from settings_theme import apply_input_look
        apply_input_look(merged)

    def _restyle_palettes(self, merged: dict):
        from fm_theme.palette import restyle_palettes_in
        restyle_palettes_in(self, merged)

    def _restyle_sliders(self, merged: dict):
        # thumb/track changent la hauteur des curseurs : il faut rejouer apply_style().
        _sync_slider_style(merged)
        for widget in QApplication.allWidgets():
            if isinstance(widget, _MiniSlider):
                widget.apply_style()

    def _restyle_titles(self, merged: dict):
        restyle_titles_in(self, merged)

    def _restyle_toggles(self, merged: dict):
        restyle_toggles_in(self, merged)

    def _restyle_tables(self, merged: dict):
        restyle_tables_in(self, merged)
        self._apply_resizable(bool(merged.get("columns_resizable", True)))
        self._relayout()

    def _apply_resizable(self, enabled: bool):
        """Tableaux > Colonnes dimensionnables, sur tous les tableaux construits."""
        self._columns_resizable = enabled
        for store in self.stores.values():
            for resizer in store.get("resizers", ()):
                resizer.setResizable(enabled)
        for frame in self.findChildren(_TableFrame):
            frame.setWidthResizable(enabled)

    # -- Espace au-dessus d'un element d'une zone titre (clic droit) --

    SPACE_MAX = 200
    # Espaces par defaut de TOUT tableau des reglages (demande de l'utilisateur) : au-dessus / en dessous,
    # tant que le tableau n'a pas les siens (clic droit > « Ajouter une espace... », 0 compris).
    TABLE_SPACE = {False: 5, True: 15}

    def _default_space(self, element: QWidget, below: bool) -> int:
        return self.TABLE_SPACE[below] if isinstance(element, _TableFrame) else 0

    def _space_element(self, widget: QWidget):
        """Element sous le clic : le tableau, sinon le titre (son noeud), sinon n'importe quel autre
        element de la fenetre empile verticalement (barre d'onglets, pied de fenetre...)."""
        node = widget
        while node is not None:
            if isinstance(node, (_TableFrame, _LazyNode)):
                return node
            node = node.parentWidget()
        return space_target(widget, self)

    def _space_key(self, element: QWidget) -> str | None:
        """Cle stable : onglet + chemin des titres (+ cle de dimensions pour un tableau) ; autre
        element : son chemin dans la fenetre (`ui:`)."""
        if not isinstance(element, (_TableFrame, _LazyNode)):
            path = widget_path(element, self)
            return f"ui:{path}" if path else None
        titles, scope, node = [], None, element if isinstance(element, _LazyNode) else element.parentWidget()
        while node is not None:
            if isinstance(node, _LazyNode):
                titles.append(node.node.title)
                scope = scope or node._values.name
            node = node.parentWidget()
        path = "/".join(reversed(titles))
        if isinstance(element, _TableFrame):
            return f"{scope}|table:{element.dimsKey()}"
        return f"{scope}|title:{path}"

    _SPACE_KEYS = {False: "element_spaces", True: "element_spaces_below"}

    # -- ordre des paragraphes (titres tires a la souris, _TitleStack) --

    def _ordered_children(self, nodes, key: str) -> list:
        return ordered_nodes(nodes, (self.settings.get("title_order") or {}).get(key))

    def _make_title_stack(self, container: QWidget, nodes: list, key: str):
        container._title_stack = _TitleStack(container, nodes, key, self._set_title_order)

    def _set_title_order(self, key: str, titles: list):
        orders = dict(self.settings.get("title_order") or {})
        orders[key] = list(titles)
        self.settings["title_order"] = orders
        self._schedule_persist()

    def _place_space(self, element: QWidget, height: int, below: bool = False):
        (set_space_below if below else set_space_above)(element, height)
        if isinstance(element, _LazyNode):          # un titre decolle de son voisin : plus de filet partage
            for title in (element._head, element._head._box_next if below else element._head._box_prev):
                if title is not None:
                    title.apply_box()

    def _set_space(self, element: QWidget, key: str, height: int, below: bool = False):
        name = self._SPACE_KEYS[below]
        spaces = dict(self.settings.get(name) or {})
        if int(height) == self._default_space(element, below):
            spaces.pop(key, None)                  # valeur par defaut : rien a retenir
        elif height or self._default_space(element, below):
            spaces[key] = int(height)              # 0 retenu quand le defaut ne l'est pas (tableau)
        else:
            spaces.pop(key, None)
        self.settings[name] = spaces
        self._place_space(element, height, below)
        self._schedule_persist()

    def _apply_saved_spaces(self):
        for below, name in self._SPACE_KEYS.items():
            spaces = self.settings.get(name) or {}
            flag = "_space_below_applied" if below else "_space_applied"
            for element in self.findChildren(_TableFrame) + self.findChildren(_LazyNode):
                if getattr(element, flag, False):
                    continue
                setattr(element, flag, True)
                height = spaces.get(self._space_key(element), self._default_space(element, below))
                if height:
                    self._place_space(element, height, below)
            for key, height in spaces.items():           # autres elements : retrouves par leur chemin
                if key.startswith("ui:") and height:
                    element = widget_at_path(self, key[3:])
                    if element is not None and not getattr(element, flag, False):
                        setattr(element, flag, True)
                        self._place_space(element, height, below)

    def add_space_action(self, widget: QWidget, menu: QMenu):
        """Clic droit sur un element d'une zone titre : « Ajouter une espace au-dessus » + curseur."""
        element = self._space_element(widget)
        key = self._space_key(element) if element is not None else None
        if key is None:
            return
        above = int((self.settings.get("element_spaces") or {}).get(
            key, getattr(element, "_space_above_px", self._default_space(element, False))))
        below = int((self.settings.get("element_spaces_below") or {}).get(
            key, getattr(element, "_space_below_px", self._default_space(element, True))))
        make_space_actions(menu, above, below, lambda v, e=element, k=key: self._set_space(e, k, v),
                           lambda v, e=element, k=key: self._set_space(e, k, v, below=True), self.SPACE_MAX,
                           widget=widget)

    def contextMenuEvent(self, event):
        """Clic droit que personne n'a pris (rien n'a de menu a cet endroit) : espace au-dessus de
        l'element clique, partout dans la fenetre."""
        menu = Menu(self)
        self.add_space_action(self.childAt(event.pos()) or self, menu)
        if menu.actions():
            menu.exec(event.globalPos())
        event.accept()

    def _after_build(self):
        """Appele apres la construction d'un tableau : lui applique les reglages de tableau deja
        modifies (sinon un tableau ne naitrait qu'avec le style de depart)."""
        for frame in self.findChildren(_TableFrame):
            if not getattr(frame, "_v2_wired", False):
                frame._v2_wired = True
                self._link_table(frame)
                frame.dimsChanged.connect(lambda f=frame: self._schedule_persist_frame(f))
        if not self._columns_resizable:
            self._apply_resizable(False)
        self._apply_saved_spaces()
        self._apply_toggle_styles()
        import settings_element_style            # styles propres (« Override settings ») des elements construits
        settings_element_style.reapply_soon(self, self.settings)

    _syncing_dims = False

    def _link_table(self, frame: _TableFrame):
        """Tableau d'un groupe lie (_LINKED_TABLES) : cle de dimensions partagee, et toute modification
        de ses dimensions est recopiee aussitot sur les autres tableaux du groupe."""
        linked = _linked_group(frame)
        if linked is not None:
            frame._link_group, frame._dims_key = linked
            frame.dimsChanged.connect(lambda f=frame: self._sync_linked(f))

    def _sync_linked(self, source: _TableFrame):
        # Recopie d'un gabarit de ligne en cours : elle atteint deja les lignes des tableaux lies (refaire tout
        # leur tableau coutait ~15 ms par pas de glissement).
        # Hauteur de ligne en cours de glissement : recopie au relachement (settings_cells.HEIGHT_DRAG).
        if (self._syncing_dims or not source._dims_applied or settings_cells._SPREADING
                or settings_cells.HEIGHT_DRAG[0]):
            return
        dims = source.collectDims()
        _TABLE_DIMS[source.dimsKey()] = dims        # un tableau du groupe construit plus tard la reprend
        self._syncing_dims = True
        try:
            with settings_cells.batched_reflow():     # sections remises en page une fois pour tous les tableaux
                for frame in self.findChildren(_TableFrame):
                    if frame is not source and frame._dims_applied and \
                            getattr(frame, "_link_group", None) == source._link_group:
                        frame.applyDims(dims)
        finally:
            self._syncing_dims = False

    def _relayout(self):
        """Un padding/une bordure modifie la hauteur des tableaux deja depliees : on remonte la
        chaine (cadres, sections, ascenseurs) pour que le reste de la page suive."""
        for frame in _flat_tables(self):
            frame.layout().activate()
        for section in self.findChildren(_Section):
            section.refresh_min_height()
        for scroller in self.findChildren(_NoSqueezeScrollArea):
            inner = scroller.widget()
            if inner is None:
                continue
            inner.layout().activate()
            _fit_inner(scroller)

    def _on_element_style_saved(self, key: str, value):
        try:
            self.settings[key] = value
        except RuntimeError:
            pass

    def _save_row_templates(self, templates: dict):
        """Gabarits de lignes modifies (fm_theme.cells, fin du geste) : ranges dans le preset fm_theme par le
        magasin de la fenetre (`save_row_templates`), tout de suite (pas d'AUTOSAVE : c'est de l'aspect partage)."""
        save = getattr(self._store, "save_row_templates", None)
        if save is not None:
            save(templates)
        for target in (self.settings, self._original_settings):
            target["row_templates"] = copy.deepcopy(templates)

    def external_values(self, values: dict):
        """Reglages changes et ENREGISTRES hors de la fenetre (tableau a la volee de la visionneuse) : la
        fenetre les reprend (copie des reglages, valeurs d'origine) et refait les tableaux deja construits
        qui les montrent ; sinon ses champs, restes a l'ancienne valeur, l'ecraseraient a l'apercu suivant
        ou a l'enregistrement."""
        if not values:
            return
        if "row_templates" in values:                 # preset fm_theme relu : gabarits poses sur les lignes
            settings_cells.reload_row_templates(values.get("row_templates") or {})
        palette = self.settings.get("colors")
        self.settings.update(copy.deepcopy(values))
        self._original_settings.update(copy.deepcopy(values))
        if isinstance(palette, dict) and "colors" in values:
            # Meme objet pour toutes les sections : mis a jour SUR PLACE, puis les champs le reprennent.
            new, self.settings["colors"] = self.settings["colors"], palette
            self._restyle_colors({"colors": new})
        changed = set(values)
        # D'abord SUR PLACE (champs deja construits : `write_spec`) ; seules les sections dont un champ ne sait
        # pas poser sa valeur sont reconstruites.
        failed = self._write_in_place(values)
        for node in self.findChildren(_LazyNode):
            group = node.node.group
            if not (node._built and group and group in CATALOG):
                continue
            specs = [sp for sp in CATALOG[group] if not isinstance(sp, str)]
            keys = {k for sp in specs for k in (sp.key, *sp.extra_keys, f"{sp.key}_linked")}
            if keys & changed and any(id(sp) in failed for sp in specs):
                node.rebuild_group()

    def follow_theme(self, values: dict):
        """Aspect generique change DANS L'EDITEUR fm_theme (demande de l'utilisateur, 2026-10-30 : visible tout de
        suite, pas au redemarrage) : la fenetre reprend les valeurs (`external_values`, sans quoi son prochain
        apercu renverrait l'ancien aspect a la fenetre principale) et se restyle. Fenetre cachee (prechargee) :
        rien maintenant, `reopen` s'en charge. Rafales regroupees, au plus une fois par image."""
        if not values:
            return
        self._theme_pending.update(values)
        if self.isVisible() and not self._theme_timer.isActive():
            self._theme_timer.start()

    def _flush_theme(self):
        values, self._theme_pending = self._theme_pending, {}
        if not values or not self.isVisible():
            return
        start = time.perf_counter()
        self.external_values(values)
        seed_window_look(self.settings)
        self._apply_look(self.settings, values)
        # Au moins autant de temps libre que de travail (meme regle que `_flush_live`).
        self._theme_timer.setInterval(max(16, 2 * int((time.perf_counter() - start) * 1000)))

    def _write_in_place(self, values: dict) -> set:
        """Pose `values` dans les champs construits ; retourne les `id` des specs qui n'ont pas su. Ni « non enregistre »
        ni apercu en direct : ce sont les valeurs de reference de la fenetre."""
        failed, was_dirty = set(), self._dirty
        for store in self.stores.values():
            for spec, widget in store.get("specs", ()):
                if isinstance(spec, str):
                    continue
                try:
                    ok = write_spec(spec, widget, values)
                except RuntimeError:                     # widget detruit
                    continue
                if not ok:
                    failed.add(id(spec))        # Spec : dict dedans, pas hachable
        self._live_timer.stop()
        self._show_dirty(was_dirty)
        self._last_live_snapshot = self.wired_values()
        return failed

    def _on_save(self):
        self._write_settings()
        self._saved = True
        self.accept()

    def _on_apply(self):
        """Bouton Appliquer : enregistre et applique, la fenetre reste ouverte ; ce qui est applique
        devient l'etat de reference (Annuler n'y revient plus en arriere)."""
        settings = self._write_settings()
        self._original_settings = json.loads(json.dumps(settings))

    def _write_settings(self) -> dict:
        # Comme SettingsWindow._on_save hors mode "tout" : on relit le disque et on n'y reporte
        # que ce que CETTE fenetre a modifie, sans ecraser ce qu'une autre fenetre a enregistre.
        values = self.wired_values()
        for key in ("title_order", "element_spaces", "element_spaces_below"):
            values[key] = dict(self.settings.get(key) or {})
        settings = self._store.save_changes(
            {k: v for k, v in values.items() if v != self._original_settings.get(k)})
        self.settings = settings
        self._show_dirty(False)
        self.settingsSaved.emit(settings)
        return settings

    def discard_on_reopen(self) -> bool:
        """Fermee en annulant des modifications : ses champs gardent ces valeurs, elle ne peut pas servir."""
        return bool(getattr(self, "_discard", False))

    def reopen(self):
        """Rouvre la fenetre gardee en memoire apres sa fermeture : reprend ce qui a change dehors (tableau a la
        volee, presets, touches de la visionneuse...) comme `external_values`, puis s'affiche."""
        fresh = self._store.load()

        def dump(value):
            return json.dumps(value, sort_keys=True, default=str)

        changed = {k: v for k, v in fresh.items() if dump(v) != dump(self._original_settings.get(k))}
        seed_window_look(fresh)
        self._theme_pending = {}
        if changed:
            self.external_values(changed)
            self._apply_look(self.settings, changed)    # aspect change pendant qu'elle etait cachee (fm_theme)
        self._original_settings = json.loads(json.dumps(self.settings))
        self._last_live_snapshot = None          # prochain apercu : compare a l'etat d'ouverture
        self._saved = False
        self._show_dirty(False)
        self.show()
        self.raise_()
        self.activateWindow()

    def start_background_build(self):
        """Construction des sections en fond meme fenetre cachee (prechargement au lancement)."""
        self._keep_alive = True
        if not getattr(self, "_prebuild_started", False) and not self.eager:
            self._prebuild_started = True
            QTimer.singleShot(400, self._prebuild_step)

    def reject(self):
        self._discard = bool(not self._saved and self._dirty)
        if not self._saved and self._dirty:
            self._apply_look(self._original_settings)
            self.settingsChanged.emit(self._original_settings)
        super().reject()

    # -- pre-construction invisible --

    PREBUILD = not os.environ.get("PIPELINE_NO_PREBUILD")      # les tests l'eteignent (tests/_isolate.py)
    PREBUILD_GAP_MS = 25     # pause entre deux constructions : la fenetre reste reactive
    # Rappel pose par l'appli : vrai tant qu'elle a besoin de TOUTE la boucle d'interface (lecture video : une
    # etape de construction de 45-50 ms = 1 a 2 images perdues a chaque etape, mesure dans l'appli lancee).
    # Le moteur de reglages ne connait pas l'appli : il attend seulement que ce rappel rende faux.
    prebuild_hold = staticmethod(lambda: False)
    PREBUILD_HOLD_RETRY_MS = 500
    # Rappel pose par l'appli : vrai quand personne n'utilise l'appli (chargement sur inactivite) — l'activite du
    # reste de l'ordinateur ne compte alors plus et la preparation prend une plus grande part du temps.
    prebuild_unattended = staticmethod(lambda: False)
    PREBUILD_UNATTENDED_DUTY = 0.5
    # Rappel pose par l'appli : avancement de la preparation, fraction 0-1 (1 = tout est pret).
    prebuild_progress = staticmethod(lambda fraction: None)

    def _prebuild_step(self):
        """Apres l'ouverture, construit UNE page (onglet) ou UNE section a la fois, sans l'afficher : un clic
        sur une section l'ouvre alors tout de suite (demande de l'utilisateur). Une construction par tour de
        boucle, espacees de `PREBUILD_GAP_MS`."""
        try:
            if not self.isVisible() and not getattr(self, "_keep_alive", False):
                self._prebuild_started = False                # reprise a la prochaine ouverture
                return
            try:
                held = bool(self.prebuild_hold())
            except Exception:                                  # noqa: BLE001 - rappel de l'appli defaillant : on construit
                held = False
            if held:
                QTimer.singleShot(self.PREBUILD_HOLD_RETRY_MS, self._prebuild_step)
                return
            # Personne n'utilise l'appli (chargement sur inactivite) : l'activite du reste de l'ordinateur ne compte pas.
            active = False if self._unattended() else self._user_is_active()
            busy = time.monotonic() < getattr(self, "_prebuild_quiet_until", 0.0)
            skips = getattr(self, "_prebuild_skips", 0)
            # L'utilisateur agit (clavier, souris, animations qu'il declenche) : une construction peut durer ~0,3 s
            # et ferait ramer. On attend qu'il s'arrete ; mais une etape passe quand meme au bout de ~5 s
            # d'activite continue (sinon la preparation ne finirait jamais).
            if self._dirty_drag_in_progress() or busy or (active and skips < self.PREBUILD_MAX_SKIPS):
                self._prebuild_skips = skips + 1 if active and not busy else 0
                QTimer.singleShot(150, self._prebuild_step)
                return
            self._prebuild_skips = 0
            started = time.perf_counter()
            warm = getattr(self, "_prebuild_warm", None)
            if warm is not None:
                self._prebuild_warm = None
                self._warm_node(warm)
                self._prebuild_units = getattr(self, "_prebuild_units", 0) + 1
                self._report_prebuild()
                self._schedule_prebuild(started)
                return
            missing = [i for i in range(len(self.scopes)) if i not in self._built]
            if missing:
                self._ensure_page(missing[0])
                self._prebuild_queue = None                   # nouvelle page : liste des sections a refaire
                self._report_prebuild()
            else:
                if getattr(self, "_prebuild_queue", None) is None:
                    self._prebuild_queue = list(self.findChildren(_LazyNode))
                    self._prebuild_total = len(self._prebuild_queue)
                queue = self._prebuild_queue
                while queue and queue[0]._built:
                    skipped = queue.pop(0)                    # deplie par l'utilisateur : deja fait
                    queue.extend(getattr(skipped, "_child_nodes", ()))
                    self._prebuild_total += len(getattr(skipped, "_child_nodes", ()))
                    self._prebuild_units = getattr(self, "_prebuild_units", 0) + 2
                if not queue:
                    self._prebuild_finished = True
                    self._set_prebuild_status(None)
                    self._report_prebuild()
                    return                                    # tout est construit
                node = queue.pop(0)
                node._build()
                queue.extend(getattr(node, "_child_nodes", ()))
                self._prebuild_total += len(getattr(node, "_child_nodes", ()))
                self._prebuild_units = getattr(self, "_prebuild_units", 0) + 1
                self._set_prebuild_status(self._prebuild_total - len(queue), self._prebuild_total)
                self._report_prebuild()
                self._prebuild_warm = node                    # puis chauffee au tour suivant (styles, mise en page)
            self._schedule_prebuild(started)
        except RuntimeError:
            return                                            # fenetre detruite

    PREBUILD_DUTY = 0.25         # part du temps de la boucle d'interface laissee a la preparation (le reste : animations)
    PREBUILD_IDLE_MS = 600       # l'utilisateur est « actif » s'il a touche clavier / souris depuis moins de ca
    PREBUILD_MAX_SKIPS = 33      # ~5 s d'activite continue, puis une etape passe quand meme

    def _schedule_prebuild(self, started: float):
        """Etape suivante : apres une pause qui limite la preparation a `PREBUILD_DUTY` du temps (une etape de
        0,2 s est suivie de 0,6 s de repos)."""
        spent = time.perf_counter() - started
        duty = max(self.PREBUILD_DUTY, self.PREBUILD_UNATTENDED_DUTY) if self._unattended() else self.PREBUILD_DUTY
        rest = int(spent * (1.0 / duty - 1.0) * 1000)
        QTimer.singleShot(max(self.PREBUILD_GAP_MS, rest), self._prebuild_step)

    def _unattended(self) -> bool:
        try:
            return bool(self.prebuild_unattended())
        except Exception:                                      # noqa: BLE001 - rappel de l'appli defaillant
            return False

    def prebuild_finished(self) -> bool:
        """Toutes les pages et sections sont construites (et chauffees)."""
        return bool(getattr(self, "_prebuild_finished", False))

    def prebuild_fraction(self) -> float:
        """Avancement de la preparation, 0-1. Unites : une par page, deux par section (construite puis chauffee) ;
        le total vient de l'arbre des sections (`Node.children`), compte une fois."""
        if self.prebuild_finished():
            return 1.0
        total = getattr(self, "_prebuild_units_total", None)
        if total is None:
            def count(nodes):
                return sum(1 + count(getattr(n, "children", None) or ()) for n in nodes)
            sections = 0
            for label, title in self.scopes:
                try:
                    sections += count(tab_tree(label, self.settings))
                except Exception:                              # noqa: BLE001 - estimation seulement
                    pass
            total = self._prebuild_units_total = len(self.scopes) + 2 * sections
        done = len(self._built) + getattr(self, "_prebuild_units", 0)
        return min(0.99, done / total) if total else 0.0

    def _report_prebuild(self):
        try:
            self.prebuild_progress(self.prebuild_fraction())
        except Exception:                                      # noqa: BLE001 - rappel de l'appli defaillant
            pass

    def _user_is_active(self) -> bool:
        """Entree clavier / souris recente (horloge d'entree de Windows : couvre aussi les clics qui lancent une
        animation) ; repli : mouvement du curseur."""
        idle = _system_idle_ms()
        if idle is not None:
            return idle < self.PREBUILD_IDLE_MS
        from PySide6.QtGui import QCursor
        cursor = QCursor.pos()
        last = getattr(self, "_prebuild_cursor", None)
        moved = last is None or (cursor - last).manhattanLength() > 6
        if moved:
            self._prebuild_cursor = cursor
        return moved

    def _warm_node(self, node):
        """Fait d'avance ce que le 1er depliage paierait (application des feuilles de style, mise en page,
        evenements d'affichage des tableaux) : le contenu de la section est affiche UN INSTANT, sans retour a
        la boucle d'evenements (aucune peinture, fenetre sans mise a jour), puis recache. Aucun signal : le
        repli des sections soeurs (accordeon) n'est pas touche."""
        body = getattr(node._head, "_body", None)
        if body is None:
            return
        chain, widget = [], body
        while widget is not None and widget is not self:
            if widget.isHidden():
                chain.append(widget)
            widget = widget.parentWidget()
        self.setUpdatesEnabled(False)
        try:
            for widget in reversed(chain):            # du plus haut au plus bas
                widget.setVisible(True)
            if not self.isVisible() and self.layout() is not None:
                self.layout().activate()              # fenetre cachee : donne leur taille aux widgets avant la peinture
            for child in body.findChildren(QWidget):
                child.ensurePolished()
            body.grab()                               # 1re peinture faite d'avance : caches de dessin (cadres, toggles...)
        finally:
            for widget in chain:
                widget.setVisible(False)
            self.setUpdatesEnabled(True)

    def _set_prebuild_status(self, done: int | None, total: int = 0):
        """Avancement de la preparation en fond, a la suite du texte de la barre d'etat."""
        base = getattr(self, "_status_base", None)
        if base is None:
            base = self._status_base = self.status.text()
        suffix = "  |  toutes les sections sont pretes" if done is None else             f"  |  preparation des sections : {done} / {total}"
        self.status.setText(base + suffix)

    def _note_user_activity(self):
        """Un titre vient d'etre deplie / replie : pas de construction pendant que sa mise en page se termine
        (minuterie de `_remeasure`) et que l'utilisateur enchaine."""
        self._prebuild_quiet_until = time.monotonic() + 1.5

    def _dirty_drag_in_progress(self) -> bool:
        from PySide6.QtWidgets import QApplication
        return bool(QApplication.mouseButtons())             # pas de construction pendant un glisser

    # -- pages --

    def _ensure_page(self, index: int):
        if index in self._built:
            return
        self._built.add(index)
        t = time.perf_counter()
        label, title = self.scopes[index]
        page = self._build_page(label, title)
        old = self.stack.widget(index)
        self.stack.removeWidget(old)
        old.deleteLater()
        self.stack.insertWidget(index, page)
        self.page_seconds[label] = time.perf_counter() - t

    def _show_page(self, index: int):
        self._ensure_page(index)
        self.stack.setCurrentIndex(index)
        self._refresh_status()

    def _build_page(self, label: str, title: str | None) -> QWidget:
        page = QWidget(self.stack)
        if label in STANDALONE_TABS:
            page._dims_scope = label       # cles des tableaux propres a l'onglet (_TableFrame.dimsKey)
        page.setStyleSheet(f"background: {M['panel_bg']};")
        outer = QVBoxLayout(page)
        outer.setContentsMargins(0, 0, 0, 0)
        scroller = _WideScrollArea(page)
        scroller.setWidgetResizable(True)
        scroller.setFrameShape(QFrame.NoFrame)
        scroller.setStyleSheet(f"background: {M['panel_bg']};")
        outer.addWidget(scroller)
        inner = QWidget(scroller.viewport())
        lay = QVBoxLayout(inner)
        lay.setContentsMargins(20, 18, 18, 26)
        lay.setSpacing(0)                  # l'ecart entre sections = leurs paddings (Titres > Paragraphes)
        values = ScopeValues(self.settings, title, label if label in STANDALONE_TABS else None)
        if title is None:
            values.hooks["add_toggle"] = self._add_toggle_style
            values.hooks["toggle_actions"] = {"add": self._add_toggle_style, "rename": self._ask_rename_toggle,
                                              "delete": self._ask_delete_toggle}
        store = self.stores.setdefault(label, {})
        store["on_change"] = self._mark_dirty
        store["after_build"] = self._after_build
        store["on_collapsed"] = self._note_user_activity
        store["on_range"] = self._on_range
        store["title_order"] = self._ordered_children
        store["title_stack"] = self._make_title_stack
        colors = self.settings["colors"]
        level = 1 if title is None else 2
        top_key = f"{values.name}|"
        with _section_host(inner):
            sections = []
            nodes = tab_tree(label, self.settings)
            for node in self._ordered_children(nodes, top_key):
                _add_stacked(lay, sections, _LazyNode(
                    node, level, values, colors, store, self.eager, None, inner,
                    wired=(label in STANDALONE_TABS or node.title in WIRED_SECTIONS)))
            _make_accordion(sections)
            self._make_title_stack(inner, sections, top_key)
        lay.addStretch(1)
        scroller.setWidget(inner)
        if title is None and sections:
            # Titres FIXES a gauche, parametres de la section ouverte dans un volet a droite (onglet ouvert dans un
            # panneau) : TOUTES les fenetres de reglages, comme l'editeur fm_theme (demande de l'utilisateur,
            # 2026-11-08). Import local : theme_side_detail importe ce module.
            from theme_side_detail import SideDetail
            page._side_detail = SideDetail(scroller, sections)
        self._apply_saved_spaces()
        self._apply_toggle_styles()
        import settings_element_style
        settings_element_style.reapply_soon(self, self.settings)
        return page

    def widget_count(self) -> int:
        return len(self.findChildren(QWidget))

    def _refresh_status(self):
        self._status_base = None
        done = ", ".join(f"{k} {v * 1000:.0f} ms" for k, v in self.page_seconds.items())
        self.status.setText(
            f"Ouverture : {self.build_seconds * 1000:.0f} ms  |  widgets : {self.widget_count()}  |  {done}")
