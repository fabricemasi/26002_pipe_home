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
de la liste des noeuds pour ce qui reste a porter. Mode LECTURE : les valeurs
sont celles des reglages courants, les modifier n'enregistre rien. Les
apercus de demonstration (toggle/curseur d'exemple) ne sont pas reproduits.

Mesure : `python tests/_probe_settings_compare.py`.
"""
from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from typing import Any, Callable

from PySide6.QtCore import QByteArray, Qt, QTimer, Signal
import copy
from PySide6.QtWidgets import (
    QApplication, QDialog, QFrame, QHBoxLayout, QInputDialog, QLabel, QLineEdit, QStackedWidget, QVBoxLayout,
    QWidget,
)

from settings_cells import (
    SplitCell, apply_saved_range, attach_range_menu, build_cells_table, natural_label_width,
    normalize_toggles, slider_fields, wrap_split,
)

from app_style import INSPECTOR_TITLE, PREVIEW_STACK_TITLE, apply_dwm_frame, resize_hit_test
from settings_layout import (
    _Section, _SubSection, _TabStrip, _TABLE_HEAD, _ResizableTableHeader, _TableRow, _make_accordion,
    _flat_tables, _refresh_gap_spacers, _reflow_all,
    _section_host, _seed_flat_tables_style, _set_flat_tables_style,
)
from settings_colorpicker import _ColorField
from settings_sections import (
    _CellPaddingField, _CompactAppOrCustomColorField, _CornerRadiusField, _CornerRadiusSliders,
    _HeaderColorField, _InnerLineField, _ITEM_TEXT_FIELD_SPECS, _SidePaddingField, _ToggleSideColorsField,
    _font_choices,
)
from settings_store import (
    M, _coerce_corner_radius, _coerce_side_enabled, _load_presets, _load_window_geometry, _resolve_color_value,
    _ICONS_DIR, _save_presets, _save_window_geometry,
    _subsection_left_margin, _title_color, _title_font, _title_gap_next, _title_indent, _sync_dynamic_M, _sync_slider_style, _sync_title_level_style, load_settings, save_settings,
)
from settings_theme import _input_radius, _register_input, _set_button_radius, _set_input_radius, _set_text_role
from settings_widgets import (
    _AppOrCustomColorField, _Btn, _DualFontSelectField, _FontSelectField, _MiniSlider,
    _OverrideSmoothingField, _RatioSliderField, _ResizeBadgePositionField, _RowBorderField, _SliderField, _TableFrame, _Toggle, _ToggleStylePicker,
    _SelectField, _set_dimmed, _toggle_icon_pixmap,
    _set_table_dims, _set_table_inner_border, _sync_toggle_style,
)
from settings_window import _NoSqueezeScrollArea, _PanelFrame, _SettingsTitleBar


# ==========================================================================
# 1. Le catalogue : les reglages decrits comme des donnees
# ==========================================================================

@dataclass(frozen=True)
class Spec:
    """Un reglage. `kind` choisit le controle (voir FIELD_FACTORIES) ;
    `extra_keys` : cles de stockage supplementaires gouvernees par le MEME
    champ/toggle (ex. une bordure = `*_border_enabled` + `*_border`)."""
    key: str
    label: str
    kind: str
    default: Any = None
    params: dict = field(default_factory=dict)
    extra_keys: tuple = ()
    general_toggle: str | None = None   # General : cle booleenne d'un interrupteur d'override devant la ligne
    only: tuple | None = None       # titres de portee ou la ligne existe (None = General) ; None = partout
    exclude: tuple = ()             # titres de portee ou elle n'existe PAS

    def applies(self, title: str | None) -> bool:
        return (self.only is None or title in self.only) and title not in self.exclude


CATALOG: dict[str, list[Spec]] = {
    "Colonnes": [
        Spec("item_column_width", "Largeur par defaut", "slider", 180, {"min": 120, "max": 640}),
        Spec("column_padding", "Padding", "padding", {}),
        Spec("column_bg_color", "Couleur de fond", "color_app", "@skinN2", {"title": "Fond de colonne"}),
        Spec("column_border_enabled", "Bordure", "sides", True, {"colors_key": "column_border"},
             extra_keys=("column_border",)),
        Spec("column_border_thickness", "Epaisseur de bordure", "slider", 1, {"min": 0, "max": 8}),
        Spec("column_border_radius", "Border radius", "corners", 0, {"max": 20}),
    ],
    "Entetes": [
        Spec("header_visible", "Afficher", "bool", True),
        Spec("header_height", "Hauteur des entetes", "slider", 26, {"min": 16, "max": 56}),
        Spec("header_padding", "Padding des entetes", "slider", 0, {"min": 0, "max": 32}),
        Spec("header_color", "Couleur des entetes", "header_color", "skinN1"),
        Spec("header_radius", "Border radius", "corners", 0, {"max": 16}),
        Spec("header_border_enabled", "Bordure", "sides", False, {"colors_key": "header_border"},
             extra_keys=("header_border",)),
        Spec("header_border_thickness", "Epaisseur de bordure", "slider", 1, {"min": 0, "max": 8}),
        Spec("header_icon_right_padding", "Padding droit des icones", "slider", 0, {"min": 0, "max": 40}),
        Spec("header_font_family", "Police du titre", "font", "Systeme"),
        Spec("header_font_bold", "Gras du titre", "bool", True),
        Spec("header_font_color", "Couleur du titre", "color_app", "#9aa1a7", {"title": "Couleur du titre"}),
        Spec("header_font_size", "Hauteur de police du titre", "slider", 10, {"min": 6, "max": 24}),
    ],
}

ALL_GROUPS = ("Colonnes", "Entetes")


_TYPE_OR_GENERAL = ("Type", None)          # le General montre les memes lignes de texte que "Type"

def _text_specs() -> list[Spec]:
    """Groupe Texte. Police/gras + le registre _ITEM_TEXT_FIELD_SPECS (ajouter
    une entree la-bas la fait apparaitre ici) pour Type et General ; Projets,
    INTERMEDIAIRE, IN... n'ont que Hauteur/Espacement (rendu unifie)."""
    specs = [
        Spec("item_font_family", "Police", "font_select", "Systeme", only=_TYPE_OR_GENERAL),
        Spec("item_font_bold", "Gras", "bool", False, only=_TYPE_OR_GENERAL),
    ]
    for it in _ITEM_TEXT_FIELD_SPECS:
        specs.append(Spec(it.key, it.label, "item_text", it.default, {"item": it}, only=_TYPE_OR_GENERAL))
    specs += [
        Spec("item_row_height", "Hauteur de la ligne", "slider", 25, {"min": 14, "max": 80, "width": 170},
             exclude=_TYPE_OR_GENERAL),
        Spec("item_row_spacing", "Espacement entre les lignes", "slider", 1, {"min": 0, "max": 20, "width": 170},
             exclude=_TYPE_OR_GENERAL),
        Spec("item_row_border_enabled", "Bordure entre les lignes", "row_border", False,
             extra_keys=("item_row_border_color", "item_row_border_thickness")),
    ]
    return specs


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


CATALOG["Texte"] = _text_specs()
CATALOG["Image"] = [
    Spec("item_image_padding", "Padding", "padding", {}),
    Spec("item_image_border_enabled", "Bordure", "sides", False, {"colors_key": "item_image_border"},
         extra_keys=("item_image_border",)),
    Spec("item_image_border_thickness", "Epaisseur de bordure", "slider", 1, {"min": 0, "max": 8, "width": 170}),
    Spec("item_image_radius", "Border radius", "corners", 0, {"max": 20}),
    Spec("item_image_ratio", "Ratio (largeur/hauteur)", "ratio", 1.0),
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
_BORD = lambda prefix, w=140, b=54: {"colors_key": prefix, "thickness_key": f"{prefix}_thickness", "width": w, "box": b}

CATALOG["G Colonnes"] = [
    Spec("item_column_width", "Largeur par defaut", "slider", 180, {"min": 120, "max": 640, "width": 280}),
    Spec("column_gap", "Distance entre colonnes", "slider", 0, {"min": 0, "max": 40, "width": 280}),
    Spec("column_padding", "Padding", "padding", {}),
    Spec("column_bg_color", "Couleur de fond", "color_app", "@skinN2", {"title": "Fond de colonne"}),
    Spec("column_border_enabled", "Bordure", "sides_thick", True, _BORD("column_border"),
         extra_keys=("column_border", "column_border_thickness")),
    Spec("column_border_radius", "Border radius", "corners", 0, {"max": 20}),
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
    Spec("item_image_radius", "Border radius", "corners", 0, {"max": 20}),
    Spec("item_image_ratio", "Ratio (largeur/hauteur)", "ratio_slider", 1.0),
]


# Groupes visibles selon la portee (Focus/Inspecteur : pas de lignes, donc
# seulement Colonnes et Entetes).
ROWLESS_SCOPES = (PREVIEW_STACK_TITLE, INSPECTOR_TITLE)


# -- TITRE : 5 niveaux de titre (police composite, retrait, espacements) --
def _title_specs() -> tuple[list[Spec], list[Spec], list[Spec]]:
    fonts, indents, gaps = [], [], []
    for n in range(1, 6):
        pre = f"title_level{n}"
        fonts.append(Spec(
            f"{pre}_font_family", f"Police titre niveau {n}", "font_gabarit", "",
            {"prefix": pre, "toggle_style": "toggle2", "size": (6, 32), "color_default": "#d6d9dc",
             "color_title": f"Couleur titre niveau {n}", "smoothing_title": False},
            extra_keys=tuple(f"{pre}_font_{k}" for k in
                             ("bold", "italic", "size", "smoothing_enabled", "smoothing", "color"))))
        indents.append(Spec(f"{pre}_indent", f"Retrait titre niveau {n} (indentation)", "slider", 0,
                            {"min": 0, "max": 120}))
        for gap, label, default in (("gap_collapsed", "titre replie", 0), ("gap_expanded", "titre deplie", 0),
                                    ("gap_next", "avec le niveau suivant", 6)):
            gaps.append(Spec(f"{pre}_{gap}", f"Niveau {n} : {label}", "slider", default,
                             {"min": 0, "max": 120, "width": 90, "box": 56}))
    return fonts, indents, gaps


CATALOG["Titre : Polices"], CATALOG["Titre : Retraits"], CATALOG["Titre : Espacements"] = _title_specs()

# -- Tableaux --
CATALOG["Tableaux"] = [
    Spec("columns_resizable", "Colonnes dimensionnables", "bool", True),
    Spec("table_border_enabled", "Bordure", "sides_thick", True,
         {"colors_key": "table_border", "thickness_key": "table_border_thickness", "width": 140, "box": 58},
         extra_keys=("table_border", "table_border_thickness")),
    Spec("table_inner_h_enabled", "Bordure intérieure H", "inner_line", True, {"axis": "h"},
         extra_keys=("table_inner_h_color", "table_inner_h_thickness")),
    Spec("table_inner_v_enabled", "Bordure intérieure V", "inner_line", True, {"axis": "v"},
         extra_keys=("table_inner_v_color", "table_inner_v_thickness")),
    Spec("table_radius", "Rayon des angles", "slider", 0, {"min": 0, "max": 16, "width": 140, "box": 58}),
    Spec("table_cell_padding", "Padding des cellules", "padding", {}),
    Spec("table_head_color", "Couleur d'en-tete", "header_color", "tableHead"),
]

# -- Toggles : un choix de style, puis Cadre/Coche pour chacun des 2 styles --
CATALOG["Toggles : Style"] = [Spec("toggle_style", "Style", "toggle_style", "toggle1")]


def _toggle_specs(prefix: str) -> tuple[list[Spec], list[Spec]]:
    small = {"width": 90, "box": 54}
    def border(part):
        return Spec(f"{prefix}_{part}_border_enabled", "Bordure", "sides_thick", True,
                    {"colors_key": f"{prefix}_{part}_border", "thickness_key": f"{prefix}_{part}_border_thickness",
                     **small},
                    extra_keys=(f"{prefix}_{part}_border", f"{prefix}_{part}_border_thickness"))
    def radius(part):
        return Spec(f"{prefix}_{part}_border_radius", "Border radius", "corners", 0, {"max": 20})
    outer = [
        Spec(f"{prefix}_outer_width", "Largeur", "slider", 29, {"min": 4, "max": 80, **small}),
        Spec(f"{prefix}_outer_height", "Hauteur", "slider", 14, {"min": 4, "max": 60, **small}),
        border("outer"), radius("outer"),
        Spec(f"{prefix}_outer_bg", "Fond (sans)", "color", "#141618", {"title": "Fond"}),
        Spec(f"{prefix}_outer_bg_on", "Fond (actif)", "color", "#3f6f9f", {"title": "Fond (actif)"}),
    ]
    text_pre = f"{prefix}_coche_text"
    coche = [
        Spec(f"{prefix}_coche_width", "Largeur", "slider", 11, {"min": 2, "max": 60, **small}),
        Spec(f"{prefix}_coche_margin", "Distance du bord", "slider", 4, {"min": 0, "max": 30, **small}),
        border("coche"), radius("coche"),
        Spec(f"{prefix}_coche_color", "Couleur", "color", "#3f6f9f", {"title": "Couleur"}),
        # Habillage : un texte OU une icone dessine(e) dans la coche.
        Spec(f"{prefix}_coche_skin", "Habillage", "coche_skin", "none"),
        Spec(f"{prefix}_coche_text", "Texte", "text", ""),
        Spec(f"{text_pre}_font_family", "Police du texte", "font_gabarit", "",
             {"prefix": text_pre, "size": (4, 32), "size_default": 10, "color_default": "#ffffff",
              "color_title": "Couleur du texte"},
             extra_keys=tuple(f"{text_pre}_font_{k}" for k in
                              ("bold", "italic", "size", "smoothing_enabled", "smoothing", "color"))),
        Spec(f"{prefix}_coche_icon", "Icône", "icon_choice", ""),
        Spec(f"{prefix}_coche_icon_color", "Couleur de l'icône", "color_app", "#ffffff",
             {"title": "Couleur de l'icône"}),
    ]
    return outer, coche


def register_toggle_catalog(prefix: str):
    """Declare les tableaux Cadre/Coche d'un style de toggle (ceux de base, puis ceux ajoutes)."""
    CATALOG[f"{prefix} : Cadre"], CATALOG[f"{prefix} : Coche"] = _toggle_specs(prefix)


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
# L'arbre des sections : quoi est imbrique dans quoi (donnees, pas code)
# ==========================================================================

@dataclass(frozen=True)
class Node:
    """Un noeud replie/deplie : section (niveau 1), sous-section (2+). `group`
    = tableau de lignes du CATALOG ; `children` = noeuds imbriques."""
    title: str
    group: str | None = None
    children: tuple = ()


COLUMN_NODES = (
    Node("Colonnes", "Colonnes"), Node("Entetes", "Entetes"), Node("Texte", "Texte"), Node("Image", "Image"),
    Node("Selection", children=tuple(Node(label, group) for group, label in SELECTION_STATES)),
)

GENERAL_COLUMNS = Node("Colonnes", children=(
    Node("Colonnes", "G Colonnes"), Node("Encart", "G Encart"), Node("Entetes", "G Entetes"),
    Node("Lignes", children=(Node("Lignes", "G Lignes"), Node("Texte", "G Texte"),
                             Node("Icone", "G Icone"), Node("Apercu", "G Apercu"))),
    COLUMN_NODES[-1],                                   # Selection (Focus + 3 etats clones)
))

def _toggle_style_node(prefix: str, label: str) -> Node:
    return Node(label, children=(Node("Cadre", f"{prefix} : Cadre"), Node("Coche", f"{prefix} : Coche")))


def general_tree(settings: dict | None = None) -> tuple:
    """Arbre de l'onglet General ; la section Toggles porte une sous-section par style ajoute."""
    customs = (settings or {}).get("toggle_custom_styles") or []
    for custom in customs:
        register_toggle_catalog(custom["key"])
    toggle_nodes = tuple(_toggle_style_node(p, label) for p, label in (("toggle1", "Toggle 1"), ("toggle2", "Toggle 2")))
    toggle_nodes += tuple(_toggle_style_node(c["key"], c.get("name") or c["key"]) for c in customs)
    return tuple(Node("Toggles", "Toggles : Style", children=toggle_nodes) if n.title == "Toggles" else n
                 for n in GENERAL_TREE)


GENERAL_TREE = (
    GENERAL_COLUMNS,
    Node("TITRE", children=(Node("Polices", "Titre : Polices"), Node("Retraits", "Titre : Retraits"),
                            Node("Espacements", "Titre : Espacements"))),
    Node("Tableaux", "Tableaux"),
    Node("Toggles", "Toggles : Style", children=tuple(
        Node(label, children=(Node("Cadre", f"{p} : Cadre"), Node("Coche", f"{p} : Coche")))
        for p, label in (("toggle1", "Toggle 1"), ("toggle2", "Toggle 2")))),
    Node("Sliders", children=(Node("Rail", "Slider : Rail"), Node("Selecteur", "Slider : Selecteur"))),
)
# ROADMAP (reste a porter, voir la liste de l'ancienne fenetre) : Polices
# principales, Couleurs, Geometrie (+ Etapes, Redimensionnement), Focus
# (preview_*), Raccourci, Application, LUT, Icones, Omit.
# A FAIRE ENSEMBLE PLUS TARD : le systeme de PRESETS (celui de la v1 ne plait pas : on le
# repense avec l'utilisateur avant de le recreer ici ; _on_save garde pour l'instant la mise a
# jour du preset actif).


def nodes_for(title: str | None, settings: dict | None = None) -> tuple:
    """Noeuds d'un onglet : General = toute la fenetre ; surcharge = les
    groupes de colonnes (Focus/Inspecteur : Colonnes et Entetes seulement)."""
    if title is None:
        return general_tree(settings)
    return COLUMN_NODES[:2] if title in ROWLESS_SCOPES else COLUMN_NODES


# Portees : (libelle d'onglet, titre reel de colonne ou None pour General).
SCOPES: list[tuple[str, str | None]] = [
    ("General", None),
    ("Type", "Type"),
    ("Projets", "Projets"),
    ("INTERMEDIAIRE", "Sous-projet"),
    (PREVIEW_STACK_TITLE, PREVIEW_STACK_TITLE),
    ("Logiciels", "Logiciels"),
    ("IN", "IN"),
    ("OVER", "OVER"),
    ("OUT", "OUT"),
    (INSPECTOR_TITLE, INSPECTOR_TITLE),
]


# ==========================================================================
# 2. Valeurs d'une portee (lecture seule)
# ==========================================================================

class ScopeValues:
    """Valeur de depart d'un reglage pour une portee : General = reglages
    courants ; surcharge = valeur surchargee si elle existe, sinon la
    generale (meme regle que SettingsWindow._type_override_seed)."""

    def __init__(self, settings: dict, title: str | None):
        self.settings = settings
        self.title = title
        self.hooks: dict[str, Callable] = {}     # actions que la fenetre met a disposition des champs

    def _store(self, kind: str) -> dict:
        if self.title is None:
            return {}
        if self.title == "Type":
            key = {"overrides": "column_type_overrides", "enabled": "column_type_override_enabled",
                   "linked": "column_type_override_linked"}[kind]
            return self.settings.get(key) or {}
        key = {"overrides": "column_overrides_by_title", "enabled": "column_override_enabled_by_title",
               "linked": "column_override_linked_by_title"}[kind]
        return (self.settings.get(key) or {}).get(self.title) or {}

    def seed(self, key: str, default):
        overrides = self._store("overrides")
        if key in overrides:
            return overrides[key]
        return self.settings.get(key, default)

    def enabled(self, key: str) -> bool:
        return bool(self._store("enabled").get(key, False))

    def linked(self, key: str, default: bool = True) -> bool:
        """Etat "lie" des 4 cotes/coins. `default` n'a d'effet que si la cle `<key>_linked`
        n'existe pas dans les reglages (elle n'est pas toujours dans DEFAULT_SETTINGS)."""
        return bool(self._store("linked").get(key, self.settings.get(f"{key}_linked", default)))


# ==========================================================================
# 3. Une fabrique par type de controle
# ==========================================================================

def _f_slider(spec: Spec, v: ScopeValues, colors: dict):
    return _SliderField(spec.params["min"], spec.params["max"], int(v.seed(spec.key, spec.default)),
                        slider_width=spec.params.get("width", 200), box_width=spec.params.get("box", 68))

def _f_bool(spec, v, colors):
    # Dans un tableau : toujours le type 2, sans texte (voir AGENTS.md).
    return _Toggle(bool(v.seed(spec.key, spec.default)), style_override="toggle2", show_label=False)

def _f_color_app(spec, v, colors):
    return _AppOrCustomColorField(v.seed(spec.key, spec.default), colors, swatch_size=24,
                                  title=spec.params.get("title", spec.label))

def _f_header_color(spec, v, colors):
    return _HeaderColorField(colors, v.seed(spec.key, spec.default))

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


def _f_corners(spec, v, colors):
    field = _CornerRadiusField(v.linked(spec.key), _coerce_corner_radius(v.seed(spec.key, spec.default)),
                               maximum=spec.params["max"])
    return _split_field(field, [(LINK_CAPTION, [field.toggle])] + [
        (letter, [field.sides.fields[key]]) for key, letter in _CornerRadiusSliders._ORDER])


def _f_padding(spec, v, colors):
    field = _CellPaddingField(v.linked(spec.key, spec.params.get("linked_default", True)),
                              v.seed(spec.key, spec.default) or {})
    return _split_field(field, [(LINK_CAPTION, [field.toggle])] + [
        (letter, [field.sides.fields[key]]) for key, letter in _SidePaddingField._ORDER])


def _side_parts(field: _ToggleSideColorsField) -> list:
    """Sous-cellules des 4 cotes d'une bordure : le toggle du cote AU-DESSUS de sa couleur."""
    return [(letter, [field.sides.side_checks[key], field.sides.fields[key]])
            for key, letter in field.sides._ORDER]


def _f_sides(spec, v, colors):
    field = _ToggleSideColorsField(
        _coerce_side_enabled(v.seed(spec.key, spec.default)),
        v.seed(spec.params["colors_key"], {}) or {}, colors)
    return _split_field(field, [(LINK_CAPTION, [field.link_toggle])] + _side_parts(field))

def _f_font(spec, v, colors):
    return _DualFontSelectField(v.seed(spec.key, "") or spec.default, width=130)


def _f_color(spec, v, colors):
    return _ColorField(v.seed(spec.key, spec.default), swatch_size=24, title=spec.params.get("title", spec.label))

def _f_ratio(spec, v, colors):
    return _SliderField(20, 500, int(round(float(v.seed(spec.key, spec.default)) * 100)), unit="%",
                        slider_width=170, box_width=68)

def _f_font_select(spec, v, colors):
    return _FontSelectField(_font_choices(), v.seed(spec.key, "") or spec.default, width=170, auto_label="Systeme")

def _f_item_text(spec, v, colors):
    return spec.params["item"].make_field(v.seed(spec.key, spec.default), colors, slider_width=170)

def _f_row_border(spec, v, colors):
    return _RowBorderField(
        bool(v.seed("item_row_border_enabled", False)), v.seed("item_row_border_color", "@ligne"),
        int(v.seed("item_row_border_thickness", 1)), colors, thickness_range=(0, 8))


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
    return {"family": family, "bold": bold, "italic": italic, "size": size,
            "smoothing": smoothing, "color": color}


def _f_font_gabarit(spec, v, colors):
    """Ligne « police » dans un tableau Parametre/Valeur : une cellule divisee, une sous-cellule par
    champ de la reference (POLICE, GRAS, ITALIQUE, HAUTEUR, NIVEAU DE LISSAGE, COULEUR)."""
    parts = _font_parts(spec, v, colors)
    holder = wrap_split(SplitCell([(caption, [parts[name]]) for name, caption in FONT_CAPTIONS]))
    holder._v2_parts = parts            # lus par FIELD_READERS["font_gabarit"]
    return holder

def _f_sides_thick(spec, v, colors):
    p = spec.params
    thickness = _SliderField(0, 8, int(v.seed(p["thickness_key"], 1)), slider_width=p.get("width", 90),
                             box_width=p.get("box", 54))
    field_w = _ToggleSideColorsField(
        _coerce_side_enabled(v.seed(spec.key, spec.default)), v.seed(p["colors_key"], {}) or {}, colors,
        thickness_field=thickness)
    field_w._v2_thickness = thickness      # lu par FIELD_READERS["sides_thick"]
    return _split_field(field_w, [(LINK_CAPTION, [field_w.link_toggle])] + _side_parts(field_w)
                        + [("Épaisseur", [thickness])])

def _f_inner_line(spec, v, colors):
    axis = spec.params["axis"]
    return _InnerLineField(
        v.seed(f"table_inner_{axis}_enabled", True), v.seed(f"table_inner_{axis}_color", "@skinN2"),
        v.seed(f"table_inner_{axis}_thickness", 1), colors, spec.label)

def _f_toggle_style(spec, v, colors):
    picker = _ToggleStylePicker(v.seed(spec.key, spec.default))
    add = v.hooks.get("add_toggle")
    if add is not None:
        def extra(menu):
            menu.addAction("Ajouter un nouveau toggle…").triggered.connect(lambda _c=False: add())
        picker.populate_extra_menu = extra        # clic droit sur la cellule
    return picker


class _TextField(QLineEdit):
    """Zone de saisie d'un texte (habillage de coche...), habillee comme les autres champs."""

    def __init__(self, text: str, width: int = 170):
        super().__init__(text)
        self.setFixedSize(width, 25)
        self._radius = _input_radius()
        _register_input(self)
        self._restyle()

    def _restyle(self):
        self.setStyleSheet(
            f"QLineEdit {{ background: {M['field_bg']}; border: 1px solid {M['field_border']}; "
            f"border-radius: {self._radius}px; color: {M['value_fg']}; padding: 0 8px; }}")

    def setRadius(self, radius: int):
        self._radius = max(0, int(radius))
        self._restyle()


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


SKINS = (("none", "Aucun"), ("text", "Texte"), ("icon", "Icône"))


def _f_coche_skin(spec, v, colors):
    current = dict(SKINS).get(v.seed(spec.key, spec.default), "Aucun")
    return _SelectField([label for _k, label in SKINS], current, width=140)


def _f_text(spec, v, colors):
    return _TextField(str(v.seed(spec.key, spec.default) or ""))


def _f_icon_choice(spec, v, colors):
    return _IconChoiceField(str(v.seed(spec.key, spec.default) or ""))


def _f_badge_position(spec, v, colors):
    return _ResizeBadgePositionField(
        v.seed("resize_badge_position", "bottom_right"), int(v.seed("resize_badge_offset_x", 8)),
        int(v.seed("resize_badge_offset_y", 8)))

def _f_ratio_slider(spec, v, colors):
    return _RatioSliderField(20, 500, int(round(float(v.seed(spec.key, spec.default)) * 100)),
                             slider_width=200, box_width=68)


FIELD_FACTORIES: dict[str, Callable] = {
    "coche_skin": _f_coche_skin, "text": _f_text, "icon_choice": _f_icon_choice,
    "badge_position": _f_badge_position, "ratio_slider": _f_ratio_slider,
    "font_gabarit": _f_font_gabarit, "sides_thick": _f_sides_thick, "inner_line": _f_inner_line,
    "toggle_style": _f_toggle_style,
    "color": _f_color, "ratio": _f_ratio, "font_select": _f_font_select, "item_text": _f_item_text,
    "row_border": _f_row_border,
    "slider": _f_slider, "bool": _f_bool, "color_app": _f_color_app, "header_color": _f_header_color,
    "corners": _f_corners, "padding": _f_padding, "sides": _f_sides, "font": _f_font,
}


# ==========================================================================
# 3 bis. Les lecteurs : le pendant de chaque fabrique (widget -> valeurs)
# ==========================================================================
# Meme regles que SettingsWindow._current_values (verifie par
# tests/test_settings_window_v2.py, qui compare les deux au bit pres).

def _font_value(w) -> str:
    return "" if w.value() == "Systeme" else w.value()


def _r_font_gabarit(spec, w) -> dict:
    k, parts = _gabarit_keys(spec), w._v2_parts
    return {
        k["family"]: _font_value(parts["family"]),
        k["bold"]: parts["bold"].isChecked(),
        k["italic"]: parts["italic"].isChecked(),
        k["size"]: parts["size"].value(),
        k["smoothing_enabled"]: parts["smoothing"].isChecked(),
        k["smoothing"]: parts["smoothing"].smoothingValue(),
        k["color"]: parts["color"].value(),
    }


FIELD_READERS: dict[str, Callable] = {
    "coche_skin": lambda sp, w: {sp.key: {label: key for key, label in SKINS}[w.value()]},
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
    "font": lambda sp, w: {sp.key: _font_value(w)},
    "font_select": lambda sp, w: {sp.key: _font_value(w)},
    "corners": lambda sp, w: {sp.key: w.cornersValue(), f"{sp.key}_linked": w.isLinked()},
    "padding": lambda sp, w: {sp.key: w.sidesValue(), f"{sp.key}_linked": w.isLinked()},
    "sides": lambda sp, w: {sp.key: w.sidesEnabledValue(), sp.params["colors_key"]: w.sidesValue()},
    "sides_thick": lambda sp, w: {
        sp.key: w.sidesEnabledValue(), sp.params["colors_key"]: w.sidesValue(),
        sp.params["thickness_key"]: w._v2_thickness.value()},
    "inner_line": lambda sp, w: dict(zip(
        (f"table_inner_{sp.params['axis']}_{k}" for k in ("enabled", "color", "thickness")), w.value())),
    "row_border": lambda sp, w: {
        "item_row_border_enabled": w.enabledValue(), "item_row_border_color": w.colorValue(),
        "item_row_border_thickness": w.thicknessValue()},
    "item_text": lambda sp, w: {sp.key: sp.params["item"].raw_value(w)},
    "font_gabarit": _r_font_gabarit,
}


def read_spec(spec: Spec, widget: QWidget) -> dict:
    return FIELD_READERS[spec.kind](spec, widget)


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


def make_field(spec: Spec, values: ScopeValues, colors: dict, on_range: Callable | None = None) -> QWidget:
    widget = FIELD_FACTORIES[spec.kind](spec, values, colors)
    hook_ranges(widget, spec.key, values.settings, on_range)
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
    # Identique a la v1 (Titre > Espacements) : une ligne par niveau, 3 curseurs.
    "Titre : Espacements": [("Niveau", 150), ("Titre replié", 250), ("Titre déplié", 250),
                            ("Avec le niveau suivant", 0)],
}


def _label(text: str) -> QLabel:
    label = QLabel(text)
    _set_text_role(label, "row_label")
    return label


def _build_gaps_table(group: str, values: ScopeValues, colors: dict, fields: dict, resizers: list,
                      record: list | None, on_change: Callable | None, on_range: Callable | None) -> QWidget:
    """Titre > Espacements : une ligne par niveau, un curseur par colonne (3 specs par ligne)."""
    columns = COLUMN_TABLES[group]
    specs = CATALOG[group]
    per_row = len(columns) - 1
    table_rows = []
    for start in range(0, len(specs), per_row):
        cells_row = [(_label(f"Niveau {start // per_row + 1}"), "left", "center")]
        for spec in specs[start:start + per_row]:
            field_w = make_field(spec, values, colors, on_range)
            for key in (spec.key, *spec.extra_keys):
                fields[key] = field_w
            if record is not None:
                record.append((spec, field_w))
                _connect_changed(field_w, on_change)
            cells_row.append((field_w, "center", "center"))
        table_rows.append(cells_row)
    frame, head, _cells = build_cells_table(
        columns, table_rows, head_align={i: Qt.AlignCenter for i in range(1, len(columns))})
    resizers.append(head)
    normalize_toggles(frame)
    return frame


def _build_font_table(group: str, values: ScopeValues, colors: dict, fields: dict, resizers: list,
                      record: list | None, on_change: Callable | None, on_range: Callable | None) -> QWidget:
    """Tableau « une ligne par niveau, un champ par colonne » (reproduction de la v1 : Titre > Polices)."""
    if group == "Titre : Espacements":
        return _build_gaps_table(group, values, colors, fields, resizers, record, on_change, on_range)
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
        table_rows.append([(holder, "left", "center")] + [(parts[name], "center", "center")
                                                          for name, _caption in FONT_CAPTIONS])
    frame, head, _cells = build_cells_table(
        columns, table_rows, head_align={i: Qt.AlignCenter for i in range(1, len(columns))})
    resizers.append(head)
    normalize_toggles(frame)
    return frame


def _flat_cells_table(rows: list) -> QWidget:
    """Tableau Parametre | Valeur. `rows` : (libelle, champ, toggle d'override ou None). Un toggle
    (portee de surcharge) precede le libelle ; OFF grise la ligne, qui suit alors le General."""
    toggle_extra = 40 if any(t is not None for _l, _f, t in rows) else 0
    columns = [("Paramètre", natural_label_width([label for label, _f, _t in rows], toggle_extra)), ("Valeur", 0)]
    table_rows = []
    for label, field, toggle in rows:
        text = _label(label)
        if toggle is None:
            first = text
        else:
            first = QWidget()
            first.setStyleSheet("background: transparent;")
            box = QHBoxLayout(first)
            box.setContentsMargins(0, 0, 0, 0)
            box.setSpacing(8)
            box.addWidget(toggle, 0, Qt.AlignVCenter)
            box.addWidget(text)

            def sync(checked: bool, field=field, text=text):
                _set_dimmed(field, not checked)
                text.setStyleSheet(f"color: {M['row_label'] if checked else M['label_dim']}; background: transparent;")

            toggle.toggled.connect(sync)
            sync(toggle.isChecked())
        table_rows.append([(first, "left", "center"), (field, "right", "center")])
    frame, head, _cells = build_cells_table(
        columns, table_rows, head_align={1: Qt.AlignRight | Qt.AlignVCenter})
    frame._v2_head = head
    return frame


def build_group(group: str, values: ScopeValues, colors: dict,
                fields: dict, toggles: dict, resizers: list,
                record: list | None = None, on_change: Callable | None = None,
                on_range: Callable | None = None) -> QWidget:
    """Tableau d'un groupe du CATALOG. Portee General : lignes sans toggle (sauf
    celles qui portent un `general_toggle`, regroupees dans un second tableau) ;
    surcharge : un toggle devant chaque ligne (OFF = suit le General).
    `record` : liste ou s'inscrivent (spec, widget) et (cle_interrupteur, toggle).
    Tout tableau a un entete ; ses toggles sont de type 2 sans texte."""
    override = values.title is not None
    if group in COLUMN_TABLES and not override:
        return _build_font_table(group, values, colors, fields, resizers, record, on_change, on_range)
    flat_rows, toggle_rows = [], []
    for spec in (sp for sp in CATALOG[group] if sp.applies(values.title)):
        field_w = make_field(spec, values, colors, on_range)
        for key in (spec.key, *spec.extra_keys):
            fields[key] = field_w
        if record is not None:
            record.append((spec, field_w))
            _connect_changed(field_w, on_change)
        if override:
            toggle = _Toggle(values.enabled(spec.key), style_override="toggle2", show_label=False)
            for key in (spec.key, *spec.extra_keys):
                toggles[key] = toggle
            toggle_rows.append((spec.label, field_w, toggle))
        elif spec.general_toggle:
            toggle = _Toggle(bool(values.seed(spec.general_toggle, False)), style_override="toggle2", show_label=False)
            toggles[spec.general_toggle] = toggle
            toggle_rows.append((spec.label, field_w, toggle))
            if record is not None:
                record.append((spec.general_toggle, toggle))
                _connect_changed(toggle, on_change)
        else:
            flat_rows.append((spec.label, field_w, None))
    frames = []
    for rows in (flat_rows, toggle_rows):
        if rows:
            frame = _flat_cells_table(rows)
            resizers.append(frame._v2_head)
            normalize_toggles(frame)
            frames.append(frame)
    if len(frames) == 1:
        return frames[0]
    wrap = QWidget()
    wrap.setStyleSheet("background: transparent;")
    wl = QVBoxLayout(wrap)
    wl.setContentsMargins(0, 0, 0, 0)
    wl.setSpacing(0)
    for frame in frames:
        wl.addWidget(frame)
    return wrap


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
        self._child_nodes.append(child)
        self._child_wrap.layout().addWidget(child)
        _make_accordion(self._child_nodes)
        self._child_refresh()
        return child

    @property
    def head(self):
        """L'entete cliquable (ce que _make_accordion ecoute)."""
        return self._head.head

    def is_collapsed(self) -> bool:
        return self._head.is_collapsed()

    def set_collapsed(self, collapsed: bool):
        self._head.set_collapsed(collapsed)

    def _on_collapsed(self, collapsed: bool):
        if not collapsed:
            self._build()

    def _build(self):
        if self._built:
            return
        self._built = True
        node = self.node
        with _section_host(self):
            if node.group:
                self._head.add(build_group(
                    node.group, self._values, self._colors, self._store.setdefault("fields", {}),
                    self._store.setdefault("toggles", {}), self._store.setdefault("resizers", []),
                    self._store.setdefault("specs", []) if self.wired else None,
                    self._store.get("on_change"), self._store.get("on_range")))
            if node.children:
                wrap = QWidget()
                wrap.setStyleSheet("background: transparent;")
                wl = QVBoxLayout(wrap)
                wl.setContentsMargins(0, 0, 0, 0)
                wl.setSpacing(6)
                children = self._child_nodes = []
                self._child_wrap = wrap
                for child in node.children:
                    children.append(_LazyNode(child, min(self.level + 1, 5), self._values, self._colors,
                                              self._store, self._eager, self._child_refresh, wrap, self.wired))
                    wl.addWidget(children[-1])
                _make_accordion(children)      # en deplier un replie les soeurs, sauf avec Ctrl
                # Titres des enfants a leur retrait absolu : pas de decalage
                # de corps (voir _BodyMixin._holds_titles).
                self._head._body_layout.addWidget(wrap)
        after = self._store.get("after_build")
        if after is not None:
            after()
        if not self.wired:
            # Pas encore branche : on le montre mais on ne le laisse pas modifier
            # (une valeur changee ici ne serait ni appliquee ni enregistree).
            self._head._body.setEnabled(False)


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
    probe = _HeaderColorField(colors, value)
    try:
        return probe._current_hex()
    finally:
        probe.deleteLater()


def _padding_tuple(sides: dict) -> tuple:
    return (int(sides.get("left", 14)), int(sides.get("top", 8)), int(sides.get("right", 14)),
            int(sides.get("bottom", 8)))


# Sections de l'onglet General deja BRANCHEES (lues, appliquees en direct,
# enregistrees). Les autres s'affichent mais restent grisees.
WIRED_SECTIONS = ("Colonnes", "TITRE", "Tableaux", "Toggles", "Sliders")

# Enregistrement EN TEMPS REEL de ce qui n'est pas un reglage a valider : taille/position de la
# fenetre, dimensions des tableaux (largeur, colonnes, cellules, justifications) et plages des
# curseurs. Les tests le coupent.
AUTOSAVE = True
GEOMETRY_KEY = "v2"


class SettingsWindowV2(QDialog):
    """Fenetre comparative. `build_seconds` = temps de construction du
    constructeur ; `page_seconds[label]` = temps de chaque onglet a sa
    premiere visite ; `widget_count` = widgets vivants a l'ouverture."""

    settingsChanged = Signal(dict)     # apercu en direct (rien n'est ecrit sur le disque)
    settingsSaved = Signal(dict)       # apres Enregistrer

    _RESIZE_BORDER = 6

    def __init__(self, parent=None, eager: bool = False):
        super().__init__(parent)
        t0 = time.perf_counter()
        self.eager = eager   # eager=True : construit TOUT d'un coup (pour mesurer l'apport du differe)
        self.setWindowFlags(Qt.Dialog | Qt.FramelessWindowHint)
        self.setAttribute(Qt.WA_TranslucentBackground, True)
        self.resize(760, 820)
        self.setMinimumSize(640, 480)
        self._restore_geometry()

        self.settings = load_settings()
        self._original_settings = json.loads(json.dumps(self.settings))
        self._saved = False
        self._dirty = False
        self._last_live_snapshot = None
        self._last_slider_sig = None
        # Apercu en direct : regroupe les rafales (glisser un curseur) comme l'ancienne fenetre.
        self._live_timer = QTimer(self)
        self._live_timer.setInterval(30)
        self._live_timer.setSingleShot(True)
        self._live_timer.timeout.connect(self._flush_live)
        # Enregistrement en temps reel (taille de la fenetre, dimensions des tableaux) : regroupe
        # les rafales d'un glissement, ecrit ~0,4 s apres le dernier mouvement.
        self._persist_timer = QTimer(self)
        self._persist_timer.setInterval(400)
        self._persist_timer.setSingleShot(True)
        self._persist_timer.timeout.connect(self._persist_now)
        # Memes prerequis de style que SettingsWindow.__init__ : les widgets
        # lisent ces reglages a leur creation.
        _set_table_dims(self.settings.get("table_dims") or {})
        _set_input_radius(int(self.settings.get("input_radius", 0)))
        _set_button_radius(int(self.settings.get("button_radius", 0)))
        _sync_dynamic_M(self.settings["colors"])
        _sync_slider_style(self.settings)
        _sync_toggle_style(self.settings)
        _sync_title_level_style(self.settings)
        _seed_flat_tables_style(int(self.settings.get("table_radius", 0)), (
            _coerce_side_enabled(self.settings.get("table_border_enabled", True)),
            {k: _resolve_color_value(v, self.settings["colors"])
             for k, v in (self.settings.get("table_border") or {}).items()},
            int(self.settings.get("table_border_thickness", 1))))

        self._seed_table_look()
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
        self.titlebar = _SettingsTitleBar(self, title="Reglages v2 (General branche)")
        self.titlebar.closeClicked.connect(self.reject)
        root.addWidget(self.titlebar)

        subbar = QWidget()
        subbar.setStyleSheet(f"background: {M['toolbar_bg']}; border-bottom: 1px solid {M['panel_border']};")
        sl = QHBoxLayout(subbar)
        sl.setContentsMargins(20, 0, 20, 0)
        self.tabs = _TabStrip([label for label, _t in SCOPES])
        sl.addWidget(self.tabs)
        root.addWidget(subbar)

        self.stack = QStackedWidget(panel)
        root.addWidget(self.stack, 1)
        for _label, _title in SCOPES:
            self.stack.addWidget(QWidget())      # emplacement, remplace a la premiere visite
        self.tabs.changed.connect(self._show_page)

        self.status = QLabel("")
        self.status.setStyleSheet(f"color: {M['label_dim']}; background: {M['toolbar_bg']}; padding: 6px 20px;")
        root.addWidget(self.status)
        root.addWidget(self._build_bottom_bar())

        if eager:
            for i in range(len(SCOPES)):
                self._ensure_page(i)
        else:
            self._ensure_page(0)
        self.stack.setCurrentIndex(0)
        self.build_seconds = time.perf_counter() - t0
        self._refresh_status()

    # -- enregistrement en temps reel --

    def _restore_geometry(self):
        geometry = _load_window_geometry(GEOMETRY_KEY) if AUTOSAVE else None
        if geometry:
            try:
                self.restoreGeometry(QByteArray.fromBase64(geometry.encode("ascii")))
            except (ValueError, TypeError):
                pass

    def _schedule_persist(self, *_args):
        if AUTOSAVE and self.isVisible():
            self._persist_timer.start()      # relance : on n'ecrit qu'a la fin du geste

    def _autosave(self, partial: dict):
        """Ecrit `partial` sur le disque tout de suite, sans toucher au reste (relit le disque : une
        autre fenetre a pu enregistrer entre-temps) — comme le fait _on_save."""
        settings = load_settings()
        settings.update(partial)
        save_settings(settings)
        self.settings.update(partial)
        self._original_settings.update(json.loads(json.dumps(partial)))

    def _persist_now(self):
        if not AUTOSAVE:
            return
        if self.isVisible():
            _save_window_geometry(bytes(self.saveGeometry().toBase64()).decode("ascii"), GEOMETRY_KEY)
        dims = dict(self.settings.get("table_dims") or {})
        for frame in self.findChildren(_TableFrame):
            if frame._dims_applied:          # un tableau jamais affiche n'a pas encore ses dimensions
                dims[frame.dimsKey()] = frame.collectDims()
        if dims != (self.settings.get("table_dims") or {}):
            _set_table_dims(dims)
            self._autosave({"table_dims": dims})

    def _add_toggle_style(self):
        name, ok = QInputDialog.getText(self, "Nouveau toggle", "Nom du nouveau toggle :")
        if ok and name.strip():
            self.add_toggle_style(name.strip())

    def add_toggle_style(self, name: str) -> str:
        """Cree un style de toggle (reglages copies sur le Toggle 1, enregistres tout de suite),
        sa sous-section Toggles > <nom> (Cadre + Coche) et sa carte dans le choix du style."""
        customs = list(self.settings.get("toggle_custom_styles") or [])
        taken = {c["key"] for c in customs} | {"toggle1", "toggle2"}
        number = 3
        while f"toggle{number}" in taken:
            number += 1
        key = f"toggle{number}"
        partial = {k.replace("toggle1_", f"{key}_", 1): copy.deepcopy(v)
                   for k, v in self.settings.items() if k.startswith("toggle1_")}
        partial["toggle_custom_styles"] = customs + [{"key": key, "name": name}]
        if AUTOSAVE:
            self._autosave(partial)
        else:
            self.settings.update(partial)
        register_toggle_catalog(key)
        _sync_toggle_style(self.settings)
        for picker in self.findChildren(_ToggleStylePicker):
            picker.addOption(key, name)
        for node in self.findChildren(_LazyNode):
            if node.level == 1 and node.node.title == "Toggles" and node._built:
                node.add_child(_toggle_style_node(key, name))
        return key

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
        apply_dwm_frame(self, 0, M["panel_border"], resizable=True)

    def nativeEvent(self, eventType, message):
        if eventType == b"windows_generic_MSG":
            result = resize_hit_test(self, message, self._RESIZE_BORDER)
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
        lay.addStretch(1)
        cancel = _Btn("Annuler", M["btn_bg"], M["btn_border"], M["btn_fg"], M["btn_hover"],
                      height=27, padding="0 13px")
        cancel.clicked.connect(self.reject)
        lay.addWidget(cancel)
        save = _Btn("Enregistrer", M["accent"], M["accent_border"], M["accent_fg"], M["accent_hover"],
                    height=27, weight=600, padding="0 17px")
        save.clicked.connect(self._on_save)
        lay.addWidget(save)
        return bar

    def _mark_dirty(self):
        self._dirty = True
        self.titlebar.set_dirty(True)
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

    def _flush_live(self):
        values = self.wired_values()                  # une seule lecture des champs
        merged = dict(self.settings)
        merged.update(values)
        snapshot = json.dumps(merged, sort_keys=True, default=str)
        if snapshot == self._last_live_snapshot:       # rien n'a reellement change : on n'embete personne
            return
        self._last_live_snapshot = snapshot
        self._apply_look(merged, values)
        self.settingsChanged.emit(merged)

    # -- restylages de la fenetre elle-meme (equivalents de SettingsWindow._apply_*) --

    def _restyle_sliders(self, merged: dict):
        # thumb/track changent la hauteur des curseurs : il faut rejouer apply_style().
        _sync_slider_style(merged)
        for widget in QApplication.allWidgets():
            if isinstance(widget, _MiniSlider):
                widget.apply_style()

    def _restyle_titles(self, merged: dict):
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

    def _restyle_toggles(self, merged: dict):
        _sync_toggle_style(merged)
        for toggle in self.findChildren(_Toggle):
            toggle.apply_style()
        for picker in self.findChildren(_ToggleStylePicker):
            picker.refreshPreviews()

    def _restyle_tables(self, merged: dict):
        colors = merged["colors"]
        enabled = merged.get("table_border_enabled")
        border_colors = {k: _resolve_color_value(v, colors) for k, v in (merged.get("table_border") or {}).items()}
        _set_table_inner_border(*(
            (merged[f"table_inner_{axis}_enabled"], _resolve_color_value(merged[f"table_inner_{axis}_color"], colors),
             merged[f"table_inner_{axis}_thickness"]) for axis in ("h", "v")))
        _TABLE_HEAD["bg"] = _head_hex(colors, merged.get("table_head_color", "tableHead"))
        _set_flat_tables_style(
            radius=int(merged.get("table_radius", 0)),
            border=(enabled, border_colors, int(merged.get("table_border_thickness", 1))),
            padding=_padding_tuple(merged.get("table_cell_padding") or {}))
        for widget in self.findChildren(_TableRow) + self.findChildren(_ResizableTableHeader):
            widget.update()          # les filets sont peints : un restyle a l'identique ne les repeint pas
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

    def _after_build(self):
        """Appele apres la construction d'un tableau : lui applique les reglages de tableau deja
        modifies (sinon un tableau ne naitrait qu'avec le style de depart)."""
        for frame in self.findChildren(_TableFrame):
            if not getattr(frame, "_v2_wired", False):
                frame._v2_wired = True
                frame.dimsChanged.connect(self._schedule_persist)
        if not self._columns_resizable:
            self._apply_resizable(False)

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
            height = max(scroller.viewport().height(), inner.minimumSizeHint().height())
            if inner.height() != height or inner.width() != scroller.viewport().width():
                inner.resize(scroller.viewport().width(), height)

    def _seed_table_look(self):
        """Etat de depart de l'habillage des tableaux (filets interieurs, padding, couleur d'entete) :
        chaque tableau le lit a sa creation."""
        settings, colors = self.settings, self.settings["colors"]
        _set_table_inner_border(*(
            (settings[f"table_inner_{axis}_enabled"], _resolve_color_value(settings[f"table_inner_{axis}_color"], colors),
             settings[f"table_inner_{axis}_thickness"]) for axis in ("h", "v")))
        _set_flat_tables_style(padding=_padding_tuple(settings.get("table_cell_padding") or {}))
        _TABLE_HEAD["bg"] = _head_hex(colors, settings.get("table_head_color", "tableHead"))

    def _on_save(self):
        # Comme SettingsWindow._on_save hors mode "tout" : on relit le disque et on n'y reporte
        # que ce que CETTE fenetre a modifie, sans ecraser ce qu'une autre fenetre a enregistre.
        values = self.wired_values()
        settings = load_settings()
        settings.update({k: v for k, v in values.items() if v != self._original_settings.get(k)})
        save_settings(settings)
        # Preset actif : le mettre a jour aussi, sinon le recharger plus tard rejouerait l'ancienne valeur.
        default_preset = settings.get("default_preset")
        presets = _load_presets()
        if default_preset in presets and default_preset != "Personnalise":
            presets[default_preset] = settings
            _save_presets(presets)
        self.settings = settings
        self._saved = True
        self.titlebar.set_dirty(False)
        self.settingsSaved.emit(settings)
        self.accept()

    def reject(self):
        if not self._saved and self._dirty:
            self._apply_look(self._original_settings)
            self.settingsChanged.emit(self._original_settings)
        super().reject()

    # -- pages --

    def _ensure_page(self, index: int):
        if index in self._built:
            return
        self._built.add(index)
        t = time.perf_counter()
        label, title = SCOPES[index]
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
        page.setStyleSheet(f"background: {M['panel_bg']};")
        outer = QVBoxLayout(page)
        outer.setContentsMargins(0, 0, 0, 0)
        scroller = _NoSqueezeScrollArea(page)
        scroller.setWidgetResizable(True)
        scroller.setFrameShape(QFrame.NoFrame)
        scroller.setStyleSheet(f"background: {M['panel_bg']};")
        outer.addWidget(scroller)
        inner = QWidget(scroller.viewport())
        lay = QVBoxLayout(inner)
        lay.setContentsMargins(20, 18, 18, 26)
        lay.setSpacing(18)
        values = ScopeValues(self.settings, title)
        if title is None:
            values.hooks["add_toggle"] = self._add_toggle_style
        store = self.stores.setdefault(label, {})
        store["on_change"] = self._mark_dirty
        store["after_build"] = self._after_build
        store["on_range"] = self._on_range
        colors = self.settings["colors"]
        level = 1 if title is None else 2
        with _section_host(inner):
            sections = []
            for node in nodes_for(title, self.settings):
                sections.append(_LazyNode(node, level, values, colors, store, self.eager, None, inner,
                                          wired=(title is None and node.title in WIRED_SECTIONS)))
                lay.addWidget(sections[-1])
            _make_accordion(sections)
        lay.addStretch(1)
        scroller.setWidget(inner)
        return page

    def widget_count(self) -> int:
        return len(self.findChildren(QWidget))

    def _refresh_status(self):
        done = ", ".join(f"{k} {v * 1000:.0f} ms" for k, v in self.page_seconds.items())
        self.status.setText(
            f"Ouverture : {self.build_seconds * 1000:.0f} ms  |  widgets : {self.widget_count()}  |  {done}")
