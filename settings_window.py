#!/usr/bin/env python3
"""
Fenetre de parametres de Pipeline Browser.

Reproduction fidele de la maquette html "Parametres generaux" (refonte totale,
remplace l'ancienne fenetre a navigation laterale + pages) : meme barre de
titre, meme barre d'outils presets, un unique panneau defilant a sections
(Application / Polices / Couleurs / Entetes / Geometrie), meme barre du bas
(Valeurs par defaut / Appliquer / Annuler / Enregistrer). La maquette avait
en plus un panneau "Apercu en direct" a droite (fenetre miniature simulee) —
supprime a la demande de l'utilisateur, la previsualisation en direct reste
assuree sur la VRAIE fenetre principale (voir settingsChanged).

La maquette n'expose que 8 couleurs semantiques, 4 roles de police (famille
seule, sans taille/gras/couleur/lissage) et aucun reglage par colonne — bien
moins que ce que l'appli sait faire (29 couleurs, 8 roles de police detailles,
5 pages de geometrie de colonnes, mode de sauvegarde...). Choix assume (voir
l'echange avec l'utilisateur) : fidelite totale a la maquette. Les reglages
qui n'y figurent plus RESTENT dans le fichier de reglages et continuent
d'etre appliques tels quels (voir DEFAULT_SETTINGS et apply_all_settings dans
pipeline_browser.py) — simplement plus aucune UI ici pour les changer, ils
restent fixes a leur valeur actuelle. Voir SEMANTIC_COLOR_SLOTS (app_style.py)
pour le detail du mappage des 8 couleurs vers les cles reelles de C.

Les couleurs/tailles ci-dessous (voir M) sont la palette FIXE de cette
fenetre, independante de celle (modifiable en direct) du navigateur
principal — memes raisons que l'ancienne fenetre : une fenetre de parametres
qui s'auto-appliquerait ses propres reglages pourrait se rendre illisible.

    python settings_window.py   (pour previsualiser la fenetre seule)
"""

import json
import sys
from pathlib import Path
from typing import Any

from PySide6.QtCore import (
    QByteArray, QEasingCurve, QEvent, QObject, QPoint, QPointF, QRect, QRectF, Qt, QTimer, QVariantAnimation, Signal,
)
from PySide6.QtGui import (
    QColor,
    QCursor,
    QFont,
    QGuiApplication,
    QImage,
    QIntValidator,
    QLinearGradient,
    QPainter,
    QPainterPath,
    QPen,
    QPixmap,
)
from PySide6.QtSvg import QSvgRenderer
from PySide6.QtWidgets import (
    QApplication,
    QDialog,
    QFileDialog,
    QFrame,
    QGraphicsOpacityEffect,
    QGridLayout,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMenu,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from app_style import (
    C,
    COLOR_FIELDS,
    SEMANTIC_COLOR_SLOTS,
    SMOOTHING_CHOICES,
    SMOOTHING_LABELS_SHORT,
    apply_dwm_frame,
    auto_family_for_role,
    get_button_radius,
    get_input_radius,
    installed_font_families,
    resize_hit_test,
    start_native_move,
)

# ==========================================================================
# Palette et metriques FIXES de cette fenetre (voir la remarque de tete de
# fichier) — recopiees de la maquette html.
# ==========================================================================

M = {
    "accent": "#3f6f9f",
    "accent_border": "#4c80b3",
    "accent_hover": "#487bad",
    "accent_fg": "#f2f6f9",
    "panel_bg": "#16181a",
    "panel_border": "#2a2e32",
    "titlebar_bg": "#101214",
    "title_fg": "#8d949a",
    "dirty_fg": "#c2914a",
    "clean_fg": "#5d656b",
    "dirty_border": "#5c4f2a",
    "dirty_dot": "#c2914a",
    "clean_dot": "#3f8f6b",
    "close_hover_bg": "#232a30",
    "close_fg": "#7d858b",
    "close_hover_fg": "#d6d9dc",
    "dot_border": "#4d565c",
    "toolbar_bg": "#1b1e21",
    "field_bg": "#101214",
    "field_border": "#2e343a",
    "field_border_hover": "#3f6f9f",
    "label_dim": "#6e767c",
    "value_fg": "#d6d9dc",
    "value_muted": "#8d949a",
    "chevron": "#6e767c",
    "btn_bg": "#262b30",
    "btn_border": "#353b41",
    "btn_fg": "#c4cacf",
    "btn_hover": "#2f353b",
    "placeholder": "#5d656b",
    "section_title": "#5f9bd0",
    "group_title": "#d6d9dc",
    "group_note": "#5d656b",
    "row_label": "#cdd2d6",
    "row_label_off": "#7a828a",
    "row_note": "#5d656b",
    "value_text": "#e0e4e7",
    "value_text_off": "#6a7278",
    "unit": "#5d656b",
    "track_bg": "#25292d",
    "knob_off": "#5d656b",
    "toggle_on_fg": "#9dc0e0",
    "toggle_off_fg": "#5d656b",
    "swatch_border": "#3a4045",
    "swatch_border_hover": "#5f9bd0",
    "table_head_bg": "#1b1e21",
    "table_row_a": "#181b1d",
    "table_row_b": "#181b1d",
    "table_head_fg": "#8d949a",
    "bold_mark_fg": "#0f1114",
    "preview_bg": "#131517",
    "preview_border": "#23282c",
    "reset_fg": "#9aa2a9",
    "reset_hover_fg": "#c8ced3",
    "edge_off": "#262a2e",
    "edge_hint": "#4c545a",
    "dash": "#454d53",
}


def _sync_dynamic_M(colors: dict) -> None:
    """Aligne les entrees de M qui suivent desormais les couleurs REGLABLES
    de l'appli (voir app_style.SEMANTIC_COLOR_SLOTS/COLOR_FIELDS) au lieu de
    rester fixes — "Zone de saisie" (well), "Skin principale niveau 1"
    (topbar), et les 2 couleurs de tableau "Fond entete de tableau"/"Fond de
    tableau" (table_head/table_row) — voir la remarque de l'utilisateur,
    capture annotee de cette fenetre a l'appui (chaque zone visait un role
    deja existant ailleurs dans l'appli, plus 2 nouvelles couleurs pour ses
    propres tableaux). table_row_a ET table_row_b (ligne impaire/paire)
    valent tous deux exactement "table_row", SANS variation automatique
    entre les deux — une version precedente assombrissait legerement la
    ligne paire (voir _shade_hex, retire), mais l'utilisateur veut que
    TOUTES les lignes restent exactement la couleur choisie (capture a
    l'appui : l'alternance elle-meme etait le probleme signale, pas juste
    son absence de reglage).

    `colors` : dict de cles REELLES de C (pas de slots semantiques) —
    typiquement self.settings["colors"] fusionne avec les edits en cours du
    color grid (voir SettingsWindow._on_colors_changed/_refresh_dynamic_colors),
    JAMAIS C directement : le C global n'est mis a jour qu'au bout du
    round-trip vers la fenetre principale (settingsChanged, debounce de
    30ms) — beaucoup trop lent pour un apercu en direct pendant le glisser
    d'une pastille de couleur. `C[key]` sert seulement de repli si `colors`
    ne contient pas encore la cle (tout premier appel, preset incomplet...)."""
    well = colors.get("well", C["well"])
    topbar = colors.get("topbar", C["topbar"])
    table_head = colors.get("table_head", C["table_head"])
    table_row = colors.get("table_row", C["table_row"])
    M["field_bg"] = well
    M["toolbar_bg"] = topbar
    M["panel_bg"] = topbar
    M["table_head_bg"] = table_head
    M["table_row_a"] = table_row
    M["table_row_b"] = table_row


# Habillage des sliders peints a la main de cette fenetre (voir _MiniSlider) —
# reglable depuis Geometrie > Slider (voir SettingsWindow._section_geometry),
# sur le meme principe que _sync_dynamic_M ci-dessus : un dict a part (pas
# M directement, ce ne sont pas que des couleurs) que chaque _MiniSlider lit
# en direct a chaque peinture, mis a jour ici a l'ouverture de la fenetre et
# a chaque changement de l'un de ces reglages (voir SettingsWindow.
# _apply_slider_style, qui rappelle aussi .apply_style() sur chaque instance
# deja construite — necessaire pour thumb_h/track_h, qui influent sur la
# hauteur meme du widget, pas juste sa peinture).
_SLIDER_STYLE = {
    "thumb_w": 3,
    "thumb_h": 14,
    "thumb_color": "#8fb4d5",
    "thumb_border_top": "#8fb4d5",
    "thumb_border_right": "#8fb4d5",
    "thumb_border_bottom": "#8fb4d5",
    "thumb_border_left": "#8fb4d5",
    # dict {cote: bool}, pas un bool unique (voir _coerce_side_enabled/la
    # remarque de l'utilisateur, "un toggle par cote") — reecrase de toute
    # facon par _sync_slider_style avant le 1er rendu.
    "thumb_border_enabled": {"top": True, "right": True, "bottom": True, "left": True},
    "thumb_radius": {"top_left": 0, "top_right": 0, "bottom_right": 0, "bottom_left": 0},
    "track_h": 3,
    "track_fill": "#3f6f9f",
    "track_empty": "#25292d",
    "track_border_top": "#25292d",
    "track_border_right": "#25292d",
    "track_border_bottom": "#25292d",
    "track_border_left": "#25292d",
    "track_border_enabled": {"top": True, "right": True, "bottom": True, "left": True},
    "track_radius": {"top_left": 0, "top_right": 0, "bottom_right": 0, "bottom_left": 0},
}


def _sync_slider_style(settings: dict) -> None:
    _SLIDER_STYLE["thumb_w"] = max(1, int(settings.get("slider_thumb_width", 3)))
    _SLIDER_STYLE["thumb_h"] = max(1, int(settings.get("slider_thumb_height", 14)))
    thumb_color = settings.get("slider_thumb_color", "#8fb4d5")
    _SLIDER_STYLE["thumb_color"] = thumb_color
    # _resolve_color_value : voir _sync_toggle_shape_style, meme raison
    # (thumb_border/track_border peuvent contenir un hex direct OU une
    # reference "@<slot>", voir _AppOrCustomColorField).
    colors = settings.get("colors") or {}
    thumb_border = settings.get("slider_thumb_border") or {}
    for side in ("top", "right", "bottom", "left"):
        _SLIDER_STYLE[f"thumb_border_{side}"] = _resolve_color_value(
            thumb_border.get(side, thumb_color), colors)
    _SLIDER_STYLE["thumb_border_enabled"] = _coerce_side_enabled(settings.get("slider_thumb_border_enabled", True))
    _SLIDER_STYLE["thumb_radius"] = _coerce_corner_radius(settings.get("slider_thumb_radius", 0))
    _SLIDER_STYLE["track_h"] = max(1, int(settings.get("slider_track_height", 3)))
    track_empty = settings.get("slider_track_empty_color", "#25292d")
    _SLIDER_STYLE["track_fill"] = settings.get("slider_track_fill_color", "#3f6f9f")
    _SLIDER_STYLE["track_empty"] = track_empty
    track_border = settings.get("slider_track_border") or {}
    for side in ("top", "right", "bottom", "left"):
        _SLIDER_STYLE[f"track_border_{side}"] = _resolve_color_value(
            track_border.get(side, track_empty), colors)
    _SLIDER_STYLE["track_border_enabled"] = _coerce_side_enabled(settings.get("slider_track_border_enabled", True))
    _SLIDER_STYLE["track_radius"] = _coerce_corner_radius(settings.get("slider_track_radius", 0))


# ==========================================================================
# Persistance — un seul emplacement (voir la remarque de tete de fichier :
# le mode de sauvegarde a 4 positions de l'ancienne fenetre a disparu avec
# la maquette, qui n'a qu'un reglage "Preset" ; le fichier actif reste celui
# deja utilise aujourd'hui, aucun changement de comportement).
# ==========================================================================

_SCRIPT_DIR = Path(__file__).resolve().parent
_PER_USER_PATH = _SCRIPT_DIR / "pipeline_settings.json"
_PRESETS_PATH = _SCRIPT_DIR / "pipeline_settings.presets.json"
_WINDOW_STATE_PATH = _SCRIPT_DIR / "pipeline_settings_window_state.json"
# Icones SVG (voir _Chevron) — copiees depuis le repertoire personnel de
# l'utilisateur (F:\SYNC\Sync\IMAGES\ico\SVG, "chevron bas"/"chevron droite")
# plutot que reference directe : rester utilisable meme si ce repertoire
# externe bouge/n'existe pas sur une autre machine.
_ICONS_DIR = _SCRIPT_DIR / "icons"


def _load_window_geometry() -> str | None:
    """Recharge la geometrie (taille/position) de CETTE fenetre au moment de
    sa derniere fermeture — meme mecanisme que PipelineBrowser (saveGeometry/
    restoreGeometry encodes en base64, voir pipeline_browser.py), mais dans
    un fichier a part pour ne pas melanger etat de fenetre et reglages
    (celui-ci n'est jamais propose au choix d'un preset)."""
    try:
        if _WINDOW_STATE_PATH.is_file():
            data = json.loads(_WINDOW_STATE_PATH.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                return data.get("geometry")
    except (OSError, ValueError):
        pass
    return None


def _save_window_geometry(geometry_b64: str) -> None:
    try:
        _WINDOW_STATE_PATH.write_text(
            json.dumps({"geometry": geometry_b64}, indent=2, ensure_ascii=False), encoding="utf-8"
        )
    except OSError:
        pass

_DEFAULT_FONT = {
    "family": "", "size": 12, "bold": False, "smoothing": "current", "color": "", "custom": False,
}

DEFAULT_COLUMNS: dict[str, dict[str, Any]] = {
    "Type":        {"width": 140, "height": 25, "spacing": 0},
    "Projets":     {"width": 208, "height": 58, "spacing": 1, "img_pad": 0, "img_radius": 0,
                    "sep_h": True, "sep_v": True},
    "Sous-projet": {"width": 208, "height": 58, "spacing": 1, "img_pad": 0, "img_radius": 0,
                    "img_pad_link": True, "img_radius_link": True, "sep_h": True, "sep_v": True},
    "Logiciels":   {"width": 186, "height": 30, "plain_height": 22, "spacing": 0, "img_pad": 3, "img_radius": 2,
                    "sep_h": True, "sep_v": True},
    "Contenu":     {"width": 186, "height": 25, "plain_height": 20, "spacing": 0, "img_pad": 3, "img_radius": 0,
                    "sep_h": True, "sep_v": True},
}

DEFAULT_SETTINGS: dict[str, Any] = {
    "root_path": r"F:\PIPELINE",
    "ui_scale": 100,
    "window_radius": 0,
    "header_height": 26,
    "header_padding": 0,
    "header_color": "skinN1",
    "header_radius": 0,
    "header_radius_linked": True,
    # Bordure des entetes (voir _ToggleSideColorsField — MEME widget/memes
    # parametres que Colonnes > Bordure, voir la remarque de l'utilisateur,
    # "renomme le parametre 'cadre des entetes' -> 'Bordure' ... je veux
    # exactement les memes parametre de controle que celui des colonnes") :
    # un interrupteur PAR COTE + une couleur INDEPENDANTE par cote + une
    # epaisseur partagee. Remplace "header_edges" (ancien nom, meme format
    # dict {cote: bool} pour l'activation — conserve en repli au chargement,
    # voir pipeline_browser.apply_all_settings/_apply_values_to_controls).
    "header_border_enabled": {"top": False, "right": False, "bottom": True, "left": False},
    "header_border": {
        "top": "#2a2e32", "right": "#2a2e32", "bottom": "#2a2e32", "left": "#2a2e32",
    },
    "header_border_thickness": 1,
    # Distance (px) entre 2 colonnes adjacentes du navigateur principal
    # (voir app_style.set_column_gap/pipeline_browser.PipelineBrowser.
    # columns_layout) — 0 par defaut : colonnes deja collees jusqu'ici,
    # aucun changement visuel tant que l'utilisateur n'y touche pas — voir
    # la remarque de l'utilisateur, "ajoute un parametre 'distance entre
    # colonne' en px".
    "column_gap": 0,
    # Padding de la colonne (voir _ColumnPreview.setPadding) — MEME widget
    # que Tableaux > Padding des cellules (_CellPaddingField, un par cote),
    # un niveau au-dessus de header_padding (tout le contenu de la
    # colonne, pas juste son entete) — voir la remarque de l'utilisateur,
    # "je veux un padding (de la mm maniere que le padding des entetes :
    # selection pour les 4 cotes)".
    "column_padding_linked": True,
    "column_padding": {"top": 0, "right": 0, "bottom": 0, "left": 0},
    # Bordure de l'apercu Colonnes (voir settings_window._ToggleSideColorsField
    # — MEME widget que Toggles > Cadre/Coche > Bordure, voir la remarque de
    # l'utilisateur, "ajoute moi un parametre de bordure exactement le meme
    # que toggle") : un interrupteur PAR COTE (voir la remarque de
    # l'utilisateur, "au lieu d'avoir un seul toggle pour activer les
    # bordures, je veux un toggle par cote") + une couleur INDEPENDANTE par
    # cote + epaisseur/rayon des angles partages (voir la remarque de
    # l'utilisateur, "ajoute une valeur de bordure radius, la largeur de
    # bordure"). #2a2e32 partout par defaut = M['panel_border']
    # (settings_window._M), la couleur deja codee en dur jusqu'ici dans
    # _ColumnPreview._refresh_frame — aucun changement visuel tant que
    # l'utilisateur n'y touche pas.
    "column_border_enabled": {"top": True, "right": True, "bottom": True, "left": True},
    "column_border": {
        "top": "#2a2e32", "right": "#2a2e32", "bottom": "#2a2e32", "left": "#2a2e32",
    },
    "column_border_thickness": 2,
    "column_border_radius": 0,
    "column_border_radius_linked": True,
    # Items texte des colonnes (voir SettingsWindow._section_items) — voir
    # la remarque de l'utilisateur, "ajoute un tableau pour les items
    # textes dans les colonnes". "" = police Systeme (meme convention que
    # font_table_columns/_FontSelectField). Couleurs par defaut alignees
    # sur les pastilles reelles deja utilisees par la liste (C['text']/
    # C['accent']/C['sel_idle']/C['hover']/C['border']).
    "item_font_family": "",
    "item_color": "#d6d9dc",
    "item_icon_enabled": True,
    "item_row_height": 25,
    "item_row_spacing": 1,   # voir pipeline_browser.ROW_SPACING
    "item_text_padding": 8,
    "item_selection_focus_color": "#3f6f9f",
    "item_selection_unfocus_color": "#2e3338",
    "item_hover_color": "#232729",
    "item_selection_padding_linked": False,
    "item_selection_padding": {"top": 4, "right": 8, "bottom": 4, "left": 8},
    "item_selection_border_enabled": {"top": False, "right": False, "bottom": False, "left": False},
    "item_selection_border": {
        "top": "#2c3034", "right": "#2c3034", "bottom": "#2c3034", "left": "#2c3034",
    },
    "item_selection_radius": 0,
    "item_selection_radius_linked": True,
    # Filet de la selection au croisement avec le bord de la colonne (cote
    # dont le padding tombe a 0, voir _ItemPreviewRow.paintEvent) — actif
    # par defaut (comportement le plus proche d'un filet visible sur tout
    # le pourtour de la selection) — voir la remarque de l'utilisateur,
    # "toggle 1 pour bordure ou non au croisement entre la selection et le
    # bord de la colonne".
    "item_selection_edge_border": True,
    # Colonnes > Type (voir SettingsWindow._build_column_type_page) : vide
    # par defaut — AUCUNE ligne surchargee, la colonne "Type" suit alors
    # EXACTEMENT le style general ci-dessus (voir la remarque de
    # l'utilisateur, "je veux que tu appliques exactement le style de
    # colonne (GENERAL/COLONNES) sur la colonne TYPE").
    "column_type_overrides": {},
    "column_type_override_enabled": {},
    "column_type_override_linked": {},
    "header_font_family": "",   # fige : plus d'UI (voir remarque de tete de fichier)
    "input_frame": True,
    "input_radius": 0,
    "button_frame": True,
    "button_radius": 0,
    "table_radius": 0,
    # Padding du texte a l'interieur des cellules de tableau (voir
    # _CellPaddingField/SettingsWindow._apply_cell_padding) — 4 valeurs
    # independantes par cote, "linked" gouverne si le 1er slider (Haut)
    # pilote les 3 autres (voir _CellPaddingField.setLinked). Valeurs par
    # defaut = celles deja codees en dur jusqu'ici pour les tableaux
    # "fermes" (_build_flat_table/_section_headers, voir _table_row) :
    # aucun changement visuel tant que l'utilisateur n'y touche pas.
    "table_cell_padding_linked": False,
    "table_cell_padding": {"top": 8, "right": 14, "bottom": 8, "left": 14},
    # Couleur d'en-tete des tableaux "fermes" A EN-TETE de cette fenetre
    # (Polices/Geometrie, voir _ResizableTableHeader) — nom de pastille
    # semantique (voir app_style.SEMANTIC_COLOR_SLOTS), meme mecanique que
    # header_color plus haut mais pour CES tableaux plutot que les colonnes
    # du navigateur principal (voir la remarque de l'utilisateur, "ajoute
    # couleur d'entete pour les tableaux"). "tableHead" par defaut : la
    # pastille "Tableau - entete" deja utilisee jusqu'ici (M['table_head_
    # bg']), aucun changement visuel tant que l'utilisateur n'y touche pas.
    "table_head_color": "tableHead",
    # Section "Tableaux" (voir SettingsWindow._section_tables) : colonnes du
    # navigateur principal agrandissables a la main (glisser la bordure
    # droite, voir pipeline_browser._Column._in_resize_zone) — deja le
    # comportement actuel par defaut (True), ce reglage permet juste de le
    # desactiver (voir app_style.set_columns_resizable).
    "columns_resizable": True,
    # Largeurs de colonnes des 2 tableaux a en-tete multi-colonnes de cette
    # fenetre (Geometrie, Polices principales — voir _ResizableTableHeader.
    # columnWidths/setColumnWidths), sauvegardables dans un preset (voir la
    # remarque de l'utilisateur : "je veux que les positions de colonnes
    # soit sauvegardable dans les preset"). Valeurs par defaut IDENTIQUES
    # aux largeurs codees en dur a la construction (voir _GeoTable/
    # _SimpleFontTable) — le 0 (colonne extensible : "Element"/"Apercu")
    # est garde pour aligner les INDICES, mais jamais lui-meme restaure.
    "geo_table_columns": [0, 150, 246],
    "font_table_columns": [150, 170, 170, 0],
    # Section "Toggles" (voir SettingsWindow._section_toggles) : style
    # visuel de TOUS les _Toggle de cette fenetre — "toggle1" (cadre
    # RECTANGLE, coche calee en haut a droite a distance egale du bord en
    # horizontale qu'en verticale) ou "toggle2" (cadre CARRE, coche
    # PARFAITEMENT centree) — voir la remarque de l'utilisateur, capture
    # annotee a l'appui (mockup corrige des 2 styles). Chaque style a son
    # propre jeu de reglages complet (prefixe toggle1_/toggle2_), toujours
    # tenus a jour tous les deux — seul "toggle_style" choisit lequel est
    # REELLEMENT applique. Valeurs par defaut IDENTIQUES a l'ancien rendu
    # code en dur pour toggle1 (piste 29x14, coche 11x11) ; toggle2 recoit
    # un cadre carre 22x22 pour rester visuellement equilibre.
    "toggle_style": "toggle1",
    "toggle1_outer_width": 29,
    "toggle1_outer_height": 14,
    "toggle1_outer_border_enabled": True,
    "toggle1_outer_border_thickness": 1,
    "toggle1_outer_border_radius": 0,
    "toggle1_outer_border_radius_linked": True,
    "toggle1_outer_border": {
        "top": "#2e343a", "right": "#2e343a", "bottom": "#2e343a", "left": "#2e343a",
    },
    "toggle1_outer_bg": "#141618",
    "toggle1_coche_width": 11,
    # Pas de "toggle1_coche_height" : la hauteur de la coche est LIEE a
    # celle du cadre (voir _sync_toggle_shape_style — remarque de
    # l'utilisateur, "la hauteur de la coche doit etre liee a celle du
    # toggle, tout en respectant la valeur de x sur le schema"). "x" lui,
    # est reglable (voir Toggles > Coche > Distance du bord) — 1px ici (pas
    # 4 comme "toggle2") : cadre "toggle1" bien plus BAS (14px) que large,
    # une marge haute/basse de 4px y ecrasait la coche a 6px de haut, dont
    # le creux (etat OFF) devenait quasi invisible — voir la remarque de
    # l'utilisateur, capture a l'appui ("les etats OFF changent").
    "toggle1_coche_margin": 1,
    "toggle1_coche_border_enabled": True,
    "toggle1_coche_border_thickness": 1,
    "toggle1_coche_border_radius": 0,
    "toggle1_coche_border_radius_linked": True,
    "toggle1_coche_border": {
        "top": "#2e343a", "right": "#2e343a", "bottom": "#2e343a", "left": "#2e343a",
    },
    "toggle1_coche_color": "#3f6f9f",
    "toggle2_outer_width": 22,
    "toggle2_outer_height": 22,
    "toggle2_outer_border_enabled": True,
    "toggle2_outer_border_thickness": 1,
    "toggle2_outer_border_radius": 0,
    "toggle2_outer_border_radius_linked": True,
    "toggle2_outer_border": {
        "top": "#2e343a", "right": "#2e343a", "bottom": "#2e343a", "left": "#2e343a",
    },
    "toggle2_outer_bg": "#141618",
    "toggle2_coche_width": 11,
    "toggle2_coche_margin": 4,
    "toggle2_coche_border_enabled": True,
    "toggle2_coche_border_thickness": 1,
    "toggle2_coche_border_radius": 0,
    "toggle2_coche_border_radius_linked": True,
    "toggle2_coche_border": {
        "top": "#2e343a", "right": "#2e343a", "bottom": "#2e343a", "left": "#2e343a",
    },
    "toggle2_coche_color": "#3f6f9f",
    # Habillage des sliders de CETTE fenetre (voir _MiniSlider/_SLIDER_STYLE
    # et Geometrie > Slider, sous-section demandee par l'utilisateur) :
    # "selecteur" = le curseur mobile, "rail" = la piste qu'il parcourt.
    # Valeurs par defaut IDENTIQUES a l'ancien rendu code en dur, pour ne
    # rien changer visuellement tant que l'utilisateur ne personnalise pas.
    "slider_thumb_width": 3,
    "slider_thumb_height": 14,
    "slider_thumb_color": "#8fb4d5",
    "slider_thumb_border": {
        "top": "#8fb4d5", "right": "#8fb4d5", "bottom": "#8fb4d5", "left": "#8fb4d5",
    },
    "slider_thumb_border_enabled": True,
    "slider_thumb_radius": 0,
    "slider_thumb_radius_linked": True,
    "slider_track_height": 3,
    "slider_track_fill_color": "#3f6f9f",
    "slider_track_empty_color": "#25292d",
    "slider_track_border": {
        "top": "#25292d", "right": "#25292d", "bottom": "#25292d", "left": "#25292d",
    },
    "slider_track_border_enabled": True,
    "slider_track_radius": 0,
    "slider_track_radius_linked": True,
    "colors": {key: C[key] for key, _, _ in COLOR_FIELDS},
    "font_main": dict(_DEFAULT_FONT),
    "font_titles": dict(_DEFAULT_FONT),
    "font_folders": dict(_DEFAULT_FONT),    # fige
    "font_files": dict(_DEFAULT_FONT),
    "font_buttons": dict(_DEFAULT_FONT),    # fige
    "font_colhead": dict(_DEFAULT_FONT),    # fige
    "font_info": dict(_DEFAULT_FONT),
    "font_info2": dict(_DEFAULT_FONT),      # fige
    "font_code": dict(_DEFAULT_FONT),
    "columns": json.loads(json.dumps(DEFAULT_COLUMNS)),   # fige
    "preview_pad": 0,     # fige
    "preview_radius": 0,  # fige
}


def load_settings() -> dict[str, Any]:
    settings = json.loads(json.dumps(DEFAULT_SETTINGS))

    def _merge(data: dict):
        for key, value in data.items():
            if key not in DEFAULT_SETTINGS:
                continue
            if isinstance(value, dict) and isinstance(settings.get(key), dict):
                for sub_key, sub_val in value.items():
                    if isinstance(sub_val, dict) and isinstance(settings[key].get(sub_key), dict):
                        settings[key][sub_key].update(sub_val)
                    else:
                        settings[key][sub_key] = sub_val
            else:
                settings[key] = value

    try:
        if _PER_USER_PATH.is_file():
            raw = json.loads(_PER_USER_PATH.read_text(encoding="utf-8"))
            # Migration "header_edges" (ancien nom) -> "header_border_enabled"
            # (voir SettingsWindow._apply_values_to_controls, meme raison) :
            # SANS ca, `_merge` ci-dessus ignore silencieusement "header_
            # edges" (plus dans DEFAULT_SETTINGS depuis ce renommage) et un
            # pipeline_settings.json ecrit avant ce changement perdrait sa
            # config de bordure d'entete au chargement.
            if "header_border_enabled" not in raw and "header_edges" in raw:
                raw["header_border_enabled"] = raw["header_edges"]
            _merge(raw)
    except (OSError, ValueError):
        pass
    return settings


def save_settings(settings: dict[str, Any]) -> None:
    try:
        _PER_USER_PATH.parent.mkdir(parents=True, exist_ok=True)
        _PER_USER_PATH.write_text(json.dumps(settings, indent=2, ensure_ascii=False), encoding="utf-8")
    except OSError:
        pass


def _load_presets() -> dict[str, dict]:
    try:
        if _PRESETS_PATH.is_file():
            data = json.loads(_PRESETS_PATH.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                return data
    except (OSError, ValueError):
        pass
    return {}


def _save_presets(presets: dict[str, dict]) -> None:
    try:
        _PRESETS_PATH.write_text(json.dumps(presets, indent=2, ensure_ascii=False), encoding="utf-8")
    except OSError:
        pass


# ==========================================================================
# Petits widgets reproduisant les controles de la maquette.
# ==========================================================================

def _qfont(size: int, weight: int = 400, mono: bool = False, tracking: float = 0.0) -> QFont:
    f = QFont("Consolas" if mono else "Segoe UI")
    f.setPixelSize(size)
    f.setWeight(QFont.Weight(weight))
    if tracking:
        f.setLetterSpacing(QFont.AbsoluteSpacing, tracking)
    return f


class _Btn(QPushButton):
    """Bouton rectangulaire plat (voir la meme classe dans l'ancienne
    fenetre — inchangee, deja fidele). radius=0 par defaut (angle droit) ;
    le popup couleur passe explicitement get_button_radius() pour ses
    propres boutons (Reinitialiser/Annuler/Valider), qui restaient a angle
    droit alors que les icones d'en-tete du meme popup (pipette...), elles,
    suivent deja ce rayon (heritee du QSS global de l'appli, faute de
    fond/bordure propres) — incoherent visuellement, voir la remarque de
    l'utilisateur, capture annotee a l'appui : memes arrondis que
    l'interface principale pour les boutons.

    setRadius (voir SettingsWindow._apply_button_radius) : TOUS les autres
    boutons persistants de cette fenetre (barre du bas, Parcourir, presets)
    passaient bien radius=0 explicitement a la construction et ne le
    reconsideraient plus jamais ensuite — orphelins de Geometrie > Boutons
    > Coins arrondis quoi qu'il arrive, voir la remarque de l'utilisateur,
    capture a l'appui ("leur bordure radius est a 0 alors que dans les
    settings il a une valeur")."""

    def __init__(self, text: str, bg: str, border: str, fg: str, hover: str,
                 height: int = 24, weight: int = 500, padding: str = "0 11px", radius: int = 0, parent=None):
        super().__init__(text, parent)
        self.setFixedHeight(height)
        self.setCursor(Qt.ArrowCursor)
        self.setFocusPolicy(Qt.NoFocus)
        self.setFont(_qfont(11, weight))
        self._bg, self._border, self._fg, self._hover, self._padding = bg, border, fg, hover, padding
        self._radius = max(0, int(radius))
        self._refresh_style()

    def _refresh_style(self):
        border_rule = f"border: 1px solid {self._border};" if self._border else "border: none;"
        self.setStyleSheet(
            f"QPushButton {{ background: {self._bg}; {border_rule} border-radius: {self._radius}px; "
            f"color: {self._fg}; padding: {self._padding}; }}"
            f"QPushButton:hover {{ background: {self._hover}; }}"
        )

    def setRadius(self, radius: int):
        self._radius = max(0, int(radius))
        self._refresh_style()


class _MiniSlider(QWidget):
    """Slider peint a la main : rail + curseur ("selecteur"), habillage
    entierement lu depuis _SLIDER_STYLE (voir Geometrie > Slider) plutot que
    fige en dur — voir apply_style, a rappeler sur toute instance deja
    construite quand ce reglage change."""

    valueChanged = Signal(int)

    def __init__(self, minimum: int, maximum: int, value: int, width: int = 170, parent=None):
        super().__init__(parent)
        self._min, self._max = minimum, maximum
        self._value = max(minimum, min(maximum, value))
        self._width = width
        self.setCursor(Qt.ArrowCursor)
        self._apply_size()

    def _apply_size(self):
        # +8 : meme marge verticale que l'ancien fixe (14 + 8 = 22) —
        # garde le curseur/le rail respirer plutot que toucher les bords
        # haut/bas du widget quel que soit thumb_h/track_h.
        h = max(_SLIDER_STYLE["thumb_h"], _SLIDER_STYLE["track_h"]) + 8
        self.setFixedSize(self._width, h)

    def apply_style(self):
        """A rappeler sur toute instance deja construite quand Geometrie >
        Slider change (voir SettingsWindow._apply_slider_style) : thumb_h/
        track_h influent sur la hauteur meme du widget, pas seulement sa
        peinture — un simple update() ne suffirait pas pour ces deux-la."""
        self._apply_size()
        self.update()

    def value(self) -> int:
        return self._value

    def setValue(self, value: int):
        value = max(self._min, min(self._max, value))
        if value != self._value:
            self._value = value
            self.update()
            self.valueChanged.emit(value)

    def _pct(self) -> float:
        span = self._max - self._min
        return 0.0 if span <= 0 else (self._value - self._min) / span

    def _set_from_x(self, x: int):
        pct = max(0.0, min(1.0, x / max(1, self.width())))
        self.setValue(round(self._min + pct * (self._max - self._min)))

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            self._set_from_x(event.position().toPoint().x())

    def mouseMoveEvent(self, event):
        if event.buttons() & Qt.LeftButton:
            self._set_from_x(event.position().toPoint().x())

    def _paint_bordered(self, p: QPainter, rect: QRect, radius, border_on,
                         border_colors: dict, fill_layers):
        """Peint `rect` (rail ou selecteur) avec, cote par cote actif, une
        bordure 1px MITREE (diagonales depuis le centre vers chaque coin,
        comme un cadre photo) plutot que 4 bandes droites independantes —
        celles-ci restaient bien 4 couleurs differentes sur un rectangle
        (radius=0) mais DISPARAISSAIENT pres des coins des que radius>0 (la
        bande, toujours large d'1 PIXEL en ligne droite, sort du contour
        arrondi qui se retrecit vers le coin — voir la remarque de
        l'utilisateur, capture a l'appui, "quelque chose de bizarre avec
        les bordures des rails"). Le miter, lui, reste une bordure
        CONTINUE quel que soit le rayon : chaque cote occupe le triangle
        entre ses 2 coins et le centre du rectangle, intersecte avec
        l'anneau exterieur-moins-interieur (les 2 chemins arrondis) —
        exactement comme les 4 cotes d'un cadre a coins coupes a 45°.

        `border_on` : bool (tous les cotes pareil, retro-compatible) OU
        dict {"top": bool, ...} — un cote DESACTIVE (voir _SideColorsField,
        la remarque de l'utilisateur "un toggle par cote") ne consomme plus
        d'epaisseur de CE cote (inset ASYMETRIQUE), le remplissage s'etend
        alors jusqu'a ce bord tout en restant en retrait des autres, actifs.
        `fill_layers` (callable prenant `p, inner_rect`) peint l'interieur —
        `inner_rect` deja calcule en tenant compte de cet inset asymetrique,
        rempli JUSQU'AU bord de chaque cote sans bordure active."""
        if rect.width() <= 0 or rect.height() <= 0:
            return
        if isinstance(border_on, dict):
            sides_on = {k: bool(border_on.get(k, False)) for k in ("top", "right", "bottom", "left")}
        else:
            v = bool(border_on)
            sides_on = {k: v for k in ("top", "right", "bottom", "left")}
        any_on = any(sides_on.values())
        t = {k: (1 if sides_on[k] else 0) for k in sides_on}
        inner_rect = QRect(
            rect.left() + t["left"], rect.top() + t["top"],
            rect.width() - t["left"] - t["right"], rect.height() - t["top"] - t["bottom"],
        )
        has_inner = inner_rect.width() > 0 and inner_rect.height() > 0
        p.save()
        p.setRenderHint(QPainter.Antialiasing, _radius_any(radius))
        if any_on:
            outer_path = _rounded_rect_path(rect, radius)
            inner_radius = _radius_shrink(radius, 1)
            # QRectF(rect), PAS rect.right()/rect.bottom() : ces 2 methodes
            # de QRect sont INCLUSIVES (topLeft + taille - 1, la convention
            # "dernier pixel valide" de QRect), alors que addRoundedRect
            # travaille en coordonnees CONTINUES (QRectF, right/bottom =
            # topLeft + taille, sans le -1) — un ecart d'1px entre les coins
            # du triangle mitre et le contour arrondi reel, qui faisait
            # disparaitre ou deformer 1 ou plusieurs cotes selon le rayon/la
            # hauteur (voir la remarque de l'utilisateur, capture a l'appui,
            # "je suis sense avoir les 4 bordures").
            ring = outer_path.subtracted(_rounded_rect_path(inner_rect, inner_radius)) if has_inner else outer_path
            rf = QRectF(rect)
            center = rf.center()
            corners = {
                "top": (QPointF(rf.left(), rf.top()), QPointF(rf.right(), rf.top())),
                "right": (QPointF(rf.right(), rf.top()), QPointF(rf.right(), rf.bottom())),
                "bottom": (QPointF(rf.right(), rf.bottom()), QPointF(rf.left(), rf.bottom())),
                "left": (QPointF(rf.left(), rf.bottom()), QPointF(rf.left(), rf.top())),
            }
            p.setPen(Qt.NoPen)
            # Voir _paint_bordered_rect (meme technique/meme raison) : chaque
            # coin allonge de EPS UNIQUEMENT du cote ou le voisin de ce coin
            # est desactive (le vrai trou) — jamais quand les 2 cotes d'un
            # coin sont actifs. Et meme dans ce cas (2 cotes actifs), 2
            # morceaux de meme couleur sont ACCUMULES puis peints en UNE
            # seule fois (united()) plutot que separement, pour ne pas
            # laisser de lisere fantome sur la diagonale du miter (2 formes
            # anti-aliasees peintes separement ne se recouvrent jamais
            # exactement pixel pour pixel).
            EPS = 0.75
            order = ("top", "right", "bottom", "left")
            color_paths: dict[str, QPainterPath] = {}
            for i, side in enumerate(order):
                if not sides_on[side]:
                    continue
                p1, p2 = corners[side]
                neighbor_p1 = order[i - 1]
                neighbor_p2 = order[(i + 1) % 4]
                dx, dy = p2.x() - p1.x(), p2.y() - p1.y()
                length = (dx * dx + dy * dy) ** 0.5
                ux, uy = (dx / length, dy / length) if length > 0 else (0.0, 0.0)
                p1e = QPointF(p1.x() - ux * EPS, p1.y() - uy * EPS) if not sides_on[neighbor_p1] else p1
                p2e = QPointF(p2.x() + ux * EPS, p2.y() + uy * EPS) if not sides_on[neighbor_p2] else p2
                wedge = QPainterPath()
                wedge.moveTo(p1e)
                wedge.lineTo(p2e)
                wedge.lineTo(center)
                wedge.closeSubpath()
                # Voir _paint_bordered_rect (meme technique/meme raison) :
                # coin ou le voisin est desactive -> unir avec le quadrant
                # COMPLET (pas juste la moitie triangulaire) pour ne pas
                # laisser un triangle de l'anneau non couvert (visible
                # surtout sur une bordure fine et un rectangle allonge).
                if not sides_on[neighbor_p1]:
                    wedge = wedge.united(_quadrant_path(p1, center))
                if not sides_on[neighbor_p2]:
                    wedge = wedge.united(_quadrant_path(p2, center))
                piece = ring.intersected(wedge)
                color = border_colors[side]
                color_paths[color] = color_paths[color].united(piece) if color in color_paths else piece
            for color, path in color_paths.items():
                p.setBrush(QColor(color))
                p.drawPath(path)
        if has_inner:
            # Bordure desactivee : le rayon doit quand meme s'appliquer au
            # remplissage, sur le rect COMPLET (pas d'inset ni de rayon
            # reduit puisqu'il n'y a pas de bordure a loger) — voir la
            # remarque de l'utilisateur, "le rayon des angles ne fonctionne
            # pas du tout quand les bordures sont desactivees" : cette
            # branche ne posait auparavant AUCUN clip, laissant le
            # remplissage carre quel que soit le rayon choisi.
            clip_radius = _radius_shrink(radius, 1) if any_on else radius
            if _radius_any(clip_radius):
                p.setClipPath(_rounded_rect_path(inner_rect, clip_radius))
            fill_layers(p, inner_rect)
        p.restore()

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing, False)
        mid_y = self.height() // 2

        # -- rail : voir _paint_bordered — bordure INDEPENDANTE par cote
        # (voir la remarque de l'utilisateur, "4 couleurs comme la bordure
        # du selecteur") puis remplissage deja-parcouru/a-parcourir.
        track_h = _SLIDER_STYLE["track_h"]
        track_rect = QRect(0, mid_y - track_h // 2, self.width(), track_h)
        # track_h > 2 : rail trop fin pour loger meme 1px de bordure sur
        # chaque cote (voir l'ancien code, meme garde-fou) — tous les cotes
        # forces a "off" dans ce cas, quel que soit le reglage par cote.
        if track_h > 2:
            track_border_on = dict(_SLIDER_STYLE["track_border_enabled"])
        else:
            track_border_on = {k: False for k in ("top", "right", "bottom", "left")}

        def _fill_track(p, inner):
            p.fillRect(inner, QColor(_SLIDER_STYLE["track_empty"]))
            fill_w = round(self._pct() * inner.width())
            if fill_w > 0:
                p.fillRect(inner.x(), inner.y(), fill_w, inner.height(), QColor(_SLIDER_STYLE["track_fill"]))

        self._paint_bordered(
            p, track_rect, _SLIDER_STYLE["track_radius"], track_border_on,
            {side: _SLIDER_STYLE[f"track_border_{side}"] for side in ("top", "right", "bottom", "left")},
            _fill_track,
        )

        # -- selecteur : meme principe, une couleur de bordure par cote
        # (voir la remarque de l'utilisateur, "1 couleur pour chaque cote").
        thumb_w, thumb_h = _SLIDER_STYLE["thumb_w"], _SLIDER_STYLE["thumb_h"]
        fill_w = round(self._pct() * self.width())
        knob_x = max(0, min(self.width() - thumb_w, fill_w - thumb_w // 2))
        thumb_rect = QRect(knob_x, mid_y - thumb_h // 2, thumb_w, thumb_h)
        thumb_border_on = _SLIDER_STYLE["thumb_border_enabled"]

        def _fill_thumb(p, inner):
            p.fillRect(inner, QColor(_SLIDER_STYLE["thumb_color"]))

        self._paint_bordered(
            p, thumb_rect, _SLIDER_STYLE["thumb_radius"], thumb_border_on,
            {side: _SLIDER_STYLE[f"thumb_border_{side}"] for side in ("top", "right", "bottom", "left")},
            _fill_thumb,
        )
        p.end()


class _SliderField(QWidget):
    """Slider + boite de lecture/saisie numerique a droite (unite comprise)."""

    valueChanged = Signal(int)

    def __init__(self, minimum: int, maximum: int, value: int, unit: str = "px",
                 slider_width: int = 170, box_width: int = 68, parent=None):
        super().__init__(parent)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(10)
        self.slider = _MiniSlider(minimum, maximum, value, slider_width)
        self._radius = 0
        self.box = box = QWidget()
        box.setObjectName("SliderValueBox")
        box.setAttribute(Qt.WA_StyledBackground, True)
        box.setFixedSize(box_width, 25)
        self._refresh_box_style()
        box_l = QHBoxLayout(box)
        box_l.setContentsMargins(7, 0, 7, 0)
        box_l.setSpacing(4)
        self._min, self._max = minimum, maximum
        self.value_label = QLineEdit(str(value))
        self.value_label.setFont(_qfont(11, 400, mono=True))
        self.value_label.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        self.value_label.setFrame(False)
        self.value_label.setValidator(QIntValidator(self.value_label))
        self.value_label.setStyleSheet(f"background: transparent; border: none; padding: 0; color: {M['value_text']};")
        self.value_label.editingFinished.connect(self._on_text_edited)
        unit_label = QLabel(unit)
        unit_label.setFont(_qfont(9, 400, mono=True))
        unit_label.setStyleSheet(f"color: {M['unit']}; background: transparent;")
        box_l.addWidget(self.value_label, 1)
        box_l.addWidget(unit_label)
        layout.addWidget(self.slider)
        layout.addWidget(box)
        self.slider.valueChanged.connect(self._on_change)

    def _refresh_box_style(self):
        self.box.setStyleSheet(
            f"#SliderValueBox {{ background: {M['field_bg']}; border: 1px solid {M['field_border']}; "
            f"border-radius: {self._radius}px; }}"
        )

    def setRadius(self, radius: int):
        """Suit le slider Geometrie > Zones de saisie > Coins arrondis —
        cette boite a le meme habillage qu'une zone de saisie normale (voir
        SettingsWindow._apply_dropdown_radius, qui l'appelle sur TOUS les
        _SliderField de la fenetre, elle-meme comprise)."""
        self._radius = max(0, int(radius))
        self._refresh_box_style()

    def _on_change(self, value: int):
        self.value_label.setText(str(value))
        self.valueChanged.emit(value)

    def _on_text_edited(self):
        text = self.value_label.text().strip()
        try:
            value = max(self._min, min(self._max, int(text)))
        except ValueError:
            value = self.slider.value()
        self.slider.setValue(value)
        self.value_label.setText(str(self.slider.value()))

    def value(self) -> int:
        return self.slider.value()

    def setValue(self, value: int):
        self.slider.setValue(value)


class _SteppedSliderField(QWidget):
    """Slider a positions FIXES (voir _MiniSlider, deja entier par nature —
    aucune valeur intermediaire possible) affichant un LIBELLE a cote plutot
    qu'un nombre dans une boite de saisie — utilise pour Lissage (voir la
    remarque de l'utilisateur : "slider 3 points (crante)" plutot qu'un
    menu deroulant, puisque le lissage n'a de toute facon que ces quelques
    niveaux reels cote Qt/Windows, voir app_style.font()). PAS de boite
    "zone de saisie" (fond/bordure) autour du libelle — voir la remarque de
    l'utilisateur, capture a l'appui : ce texte n'est ni cliquable ni
    editable, l'habiller comme un champ suggerait le contraire ; un simple
    texte informatif, comme la colonne Apercu du meme tableau."""

    changed = Signal(int)

    def __init__(self, labels: list[str], value: int, slider_width: int = 170, box_width: int = 90, parent=None):
        super().__init__(parent)
        self._labels = labels
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        # 18 (pas 10 comme _SliderField) : slider tres court (20px, voir la
        # remarque de l'utilisateur) donc slider+libelle se retrouvaient
        # colles l'un a l'autre avec le meme espacement qu'un _SliderField
        # normal (dont le slider fait 5x plus large) — voir la remarque de
        # l'utilisateur, capture a l'appui ("zone rognee, infos entassees").
        layout.setSpacing(18)
        self.slider = _MiniSlider(0, len(labels) - 1, value, slider_width)
        self.value_label = QLabel(labels[value])
        self.value_label.setFont(_qfont(11, 400))
        self.value_label.setFixedWidth(box_width)
        self.value_label.setStyleSheet(f"color: {M['value_muted']}; background: transparent;")
        layout.addWidget(self.slider)
        layout.addWidget(self.value_label)
        self.slider.valueChanged.connect(self._on_change)

    def _on_change(self, value: int):
        self.value_label.setText(self._labels[value])
        self.changed.emit(value)

    def value(self) -> int:
        return self.slider.value()

    def setValue(self, value: int):
        value = max(0, min(len(self._labels) - 1, value))
        self.slider.setValue(value)
        self.value_label.setText(self._labels[value])


class _SelectField(QPushButton):
    """Bouton "select" (valeur + chevron), ouvre un QMenu. Cette boite a
    exactement le meme habillage (fond/bordure) qu'une zone de saisie
    normale (QLineEdit) \u2014 voir setRadius : elle suit donc en direct le
    reglage Geometrie > Zones de saisie > Coins arrondis, au meme titre que
    les vrais champs de texte (voir SettingsWindow._apply_field_radius)."""

    changed = Signal(str)

    def __init__(self, options: list[str], current: str, width: int = 200, parent=None):
        super().__init__(parent)
        self._options = options
        self._value = current if current in options else options[0]
        self._radius = 0
        self.setFixedSize(width, 25)
        self.setCursor(Qt.ArrowCursor)
        self.setFocusPolicy(Qt.NoFocus)
        self.setFont(_qfont(11, 400))
        self._refresh_style()
        self.clicked.connect(self._open_menu)
        self._sync_text()

    def _refresh_style(self):
        self.setStyleSheet(
            f"QPushButton {{ background: {M['field_bg']}; border: 1px solid {M['field_border']}; "
            f"border-radius: {self._radius}px; "
            f"color: {M['value_fg']}; text-align: left; padding: 0 8px; }}"
            f"QPushButton:hover {{ border-color: {M['field_border_hover']}; }}"
        )

    def setRadius(self, radius: int):
        self._radius = max(0, int(radius))
        self._refresh_style()

    def _sync_text(self):
        self.setText(self._value + "  \u25be")

    def _open_menu(self):
        menu = QMenu(self)
        menu.setFont(_qfont(11, 400))
        menu.setStyleSheet(
            f"QMenu {{ background: {M['toolbar_bg']}; border: 1px solid {M['field_border']}; "
            f"border-radius: {self._radius}px; padding: 4px 0; }}"
            f"QMenu::item {{ padding: 5px 16px; color: {M['value_fg']}; }}"
            f"QMenu::item:selected {{ background: {M['accent']}; color: {M['accent_fg']}; }}"
        )
        for opt in self._options:
            action = menu.addAction(opt)
            action.triggered.connect(lambda _checked=False, o=opt: self._select(o))
        menu.exec(self.mapToGlobal(QPoint(0, self.height())))

    def _select(self, opt: str):
        if opt != self._value:
            self._value = opt
            self._sync_text()
            self.changed.emit(opt)

    def value(self) -> str:
        return self._value

    def setValue(self, value: str):
        if value in self._options and value != self._value:
            self._value = value
            self._sync_text()


class _FontSelectField(_SelectField):
    """Variante de _SelectField pour choisir une police : vraie liste
    deroulante (scroll natif, molette comprise) ou chaque nom de police est
    rendu DANS cette police — voir la meme classe dans l'ancienne fenetre,
    logique inchangee."""

    def __init__(self, options: list[str], current: str, width: int = 200,
                 auto_label: str | None = None, parent=None):
        self._auto_label = auto_label
        super().__init__(options, current, width, parent)

    def _display_label(self, opt: str) -> str:
        if opt == "Systeme" and self._auto_label:
            return self._auto_label
        return opt

    def _sync_text(self):
        self.setText(self._display_label(self._value) + "  \u25be")

    def _open_menu(self):
        popup = QWidget(self, Qt.Popup)
        popup.setObjectName("FontPopup")
        popup.setAttribute(Qt.WA_StyledBackground, True)
        popup.setStyleSheet(
            f"#FontPopup {{ background: {M['toolbar_bg']}; border: 1px solid {M['field_border']}; "
            f"border-radius: {self._radius}px; }}"
        )
        layout = QVBoxLayout(popup)
        layout.setContentsMargins(1, 1, 1, 1)
        layout.setSpacing(0)

        listw = QListWidget(popup)
        listw.setFrameShape(QFrame.NoFrame)
        listw.setUniformItemSizes(True)
        listw.setStyleSheet(
            "QListWidget { background: transparent; border: none; outline: none; }"
            f"QListWidget::item {{ padding: 6px 12px; color: {M['value_fg']}; }}"
            f"QListWidget::item:selected {{ background: {M['accent']}; color: {M['accent_fg']}; }}"
            f"QListWidget::item:hover:!selected {{ background: {M['close_hover_bg']}; }}"
        )
        current_item = None
        for opt in self._options:
            if opt == self._auto_label and opt != self._value:
                continue
            item = QListWidgetItem(self._display_label(opt))
            item.setData(Qt.UserRole, opt)
            item.setFont(_qfont(12, 400) if opt == "Systeme" else QFont(opt, 12))
            listw.addItem(item)
            if opt == self._value:
                current_item = item
        listw.itemClicked.connect(lambda item: self._pick_from_popup(item.data(Qt.UserRole), popup))

        layout.addWidget(listw)
        popup.setFixedWidth(max(self.width(), 240))
        popup.setFixedHeight(320)
        popup.move(self.mapToGlobal(QPoint(0, self.height())))
        popup.show()
        if current_item is not None:
            listw.setCurrentItem(current_item)
            listw.scrollToItem(current_item)
        listw.setFocus()

    def _pick_from_popup(self, opt: str, popup: QWidget):
        popup.close()
        self._select(opt)


# Style visuel de TOUS les _Toggle de cette fenetre (voir Toggles > Style,
# SettingsWindow._section_toggles) — "toggle1" (cadre RECTANGLE, coche
# calee en haut a droite a distance egale du bord en horizontale qu'en
# verticale) ou "toggle2" (cadre CARRE, coche PARFAITEMENT centree) — voir
# la remarque de l'utilisateur, capture annotee a l'appui (mockup corrige
# des 2 styles, "je me suis trompe, j'ai modifie les types"). Chaque style
# a son propre jeu de reglages COMPLET (_TOGGLE1_STYLE/_TOGGLE2_STYLE,
# toujours tenus a jour tous les deux — seul _TOGGLE_STYLE choisit lequel
# est REELLEMENT dessine) ; _TOGGLE_STYLE change une fois, s'applique a
# tous les toggles deja construits (voir SettingsWindow._on_toggle_style_
# changed, qui rappelle .apply_style() sur chacun), meme principe que
# _SLIDER_STYLE.
_TOGGLE_STYLE = "toggle1"

_ALL_SIDES_ON = {"top": True, "right": True, "bottom": True, "left": True}
_TOGGLE_SHAPE_DEFAULTS = {
    "outer_w": 29, "outer_h": 14,
    # dict {cote: bool}, pas un bool unique (voir _coerce_side_enabled/la
    # remarque de l'utilisateur, "un toggle par cote") — reecrase de toute
    # facon par _sync_toggle_shape_style avant le 1er rendu, valeur de
    # depart seulement.
    "outer_border_enabled": dict(_ALL_SIDES_ON), "outer_border_thickness": 1,
    "outer_border_radius": {"top_left": 0, "top_right": 0, "bottom_right": 0, "bottom_left": 0},
    "outer_border_top": "#2e343a", "outer_border_right": "#2e343a",
    "outer_border_bottom": "#2e343a", "outer_border_left": "#2e343a",
    "outer_bg": "#141618",
    "coche_w": 11, "coche_h": 11,
    # Marge (px, "x" sur le schema de l'utilisateur) entre le bord du cadre
    # et la coche — reglable (voir Toggles > Coche > Distance du bord),
    # PAR STYLE (chacun le sien). Sert de marge HAUTE et BASSE (voir
    # _sync_toggle_shape_style, qui EN DEDUIT coche_h — la hauteur de la
    # coche est LIEE a celle du cadre, voir la remarque de l'utilisateur)
    # et, pour "toggle1", de marge DROITE aussi (voir _paint_toggle_shape).
    "coche_margin": 4,
    "coche_border_enabled": dict(_ALL_SIDES_ON), "coche_border_thickness": 1,
    "coche_border_radius": {"top_left": 0, "top_right": 0, "bottom_right": 0, "bottom_left": 0},
    "coche_border_top": "#2e343a", "coche_border_right": "#2e343a",
    "coche_border_bottom": "#2e343a", "coche_border_left": "#2e343a",
    "coche_color": "#3f6f9f",
}
_TOGGLE1_STYLE = dict(_TOGGLE_SHAPE_DEFAULTS)
_TOGGLE2_STYLE = dict(_TOGGLE_SHAPE_DEFAULTS)
_TOGGLE2_STYLE.update({"outer_w": 22, "outer_h": 22})


def _active_toggle_style() -> dict:
    return _TOGGLE1_STYLE if _TOGGLE_STYLE == "toggle1" else _TOGGLE2_STYLE


def _sync_toggle_shape_style(target: dict, settings: dict, prefix: str) -> None:
    """Recopie les reglages `{prefix}_*` de `settings` dans `target`
    (_TOGGLE1_STYLE ou _TOGGLE2_STYLE) — voir _sync_toggle_style, qui
    l'appelle pour chacun des 2 styles a chaque changement."""
    target["outer_w"] = max(4, int(settings.get(f"{prefix}_outer_width", target["outer_w"])))
    target["outer_h"] = max(4, int(settings.get(f"{prefix}_outer_height", target["outer_h"])))
    target["outer_border_enabled"] = _coerce_side_enabled(settings.get(f"{prefix}_outer_border_enabled", True))
    target["outer_border_thickness"] = max(0, int(settings.get(f"{prefix}_outer_border_thickness", 1)))
    target["outer_border_radius"] = _coerce_corner_radius(settings.get(f"{prefix}_outer_border_radius", 0))
    # _resolve_color_value : outer_border/coche_border (voir _AppOrCustom
    # ColorField, bordures Toggles/Sliders) peuvent contenir un hex direct
    # OU une reference "@<slot>" a une pastille semantique — cette derniere
    # doit etre resolue en hex REEL avant de finir ici, seule forme que
    # _paint_bordered_rect (QColor(...)) sait interpreter.
    colors = settings.get("colors") or {}
    outer_border = settings.get(f"{prefix}_outer_border") or {}
    for side in ("top", "right", "bottom", "left"):
        target[f"outer_border_{side}"] = _resolve_color_value(
            outer_border.get(side, target[f"outer_border_{side}"]), colors)
    target["outer_bg"] = settings.get(f"{prefix}_outer_bg", target["outer_bg"])
    target["coche_w"] = max(2, int(settings.get(f"{prefix}_coche_width", target["coche_w"])))
    target["coche_margin"] = max(0, int(settings.get(f"{prefix}_coche_margin", target["coche_margin"])))
    # coche_h LIEE a outer_h (voir la remarque de l'utilisateur), pas un
    # reglage independant — marge haute ET basse egales a x (coche_margin),
    # ce qui centre aussi verticalement la coche (equivalent, voir
    # _paint_toggle_shape).
    target["coche_h"] = max(2, target["outer_h"] - 2 * target["coche_margin"])
    target["coche_border_enabled"] = _coerce_side_enabled(settings.get(f"{prefix}_coche_border_enabled", True))
    target["coche_border_thickness"] = max(0, int(settings.get(f"{prefix}_coche_border_thickness", 1)))
    target["coche_border_radius"] = _coerce_corner_radius(settings.get(f"{prefix}_coche_border_radius", 0))
    coche_border = settings.get(f"{prefix}_coche_border") or {}
    for side in ("top", "right", "bottom", "left"):
        target[f"coche_border_{side}"] = _resolve_color_value(
            coche_border.get(side, target[f"coche_border_{side}"]), colors)
    target["coche_color"] = settings.get(f"{prefix}_coche_color", target["coche_color"])


def _sync_toggle_style(settings: dict) -> None:
    global _TOGGLE_STYLE
    style = settings.get("toggle_style", "toggle1")
    _TOGGLE_STYLE = style if style in ("toggle1", "toggle2") else "toggle1"
    _sync_toggle_shape_style(_TOGGLE1_STYLE, settings, "toggle1")
    _sync_toggle_shape_style(_TOGGLE2_STYLE, settings, "toggle2")


_CORNERS = ("top_left", "top_right", "bottom_right", "bottom_left")


def _radius_dict(radius) -> dict:
    """Normalise `radius` (int uniforme OU dict {"top_left": int, ...}) en
    dict complet sur les 4 coins — voir _rounded_rect_path/_paint_bordered_
    rect et la remarque de l'utilisateur, "si deux colonnes sont cote a
    cote ... le rayon contre l'autre colonne doit etre a zero" (rayon
    INDEPENDANT par coin, voir _ColumnPreview.paintEvent)."""
    if isinstance(radius, dict):
        return {k: max(0, int(radius.get(k, 0))) for k in _CORNERS}
    r = max(0, int(radius))
    return {k: r for k in _CORNERS}


def _radius_shrink(radius, amount: int):
    """`radius` (int ou dict) retranche de `amount` sur chaque coin, jamais
    sous 0 — repasse a un int simple si les 4 coins retombent egaux (evite
    de trainer un dict la ou un simple radius suffit)."""
    shrunk = {k: max(0, v - amount) for k, v in _radius_dict(radius).items()}
    values = set(shrunk.values())
    return values.pop() if len(values) == 1 else shrunk


def _radius_any(radius) -> bool:
    return any(v > 0 for v in _radius_dict(radius).values())


def _nibble_header_radius(header_radius, column_radius, header_padding: int = 0) -> dict:
    """Rayon d'entete EFFECTIF : ses 2 coins HAUTS agrandis au rayon de la
    COLONNE elle-meme s'il est plus grand — MAIS SEULEMENT si l'entete est
    reellement COLLEE au coin haut de la colonne (Padding des entetes <= 0
    — voir _ColumnPreview._refresh_seam_margin, header_band lui-meme
    TOUJOURS colle sans marge, seul header_fill — le fond colore — en est
    inset via ce padding) : sinon rien ne touche le coin arrondi, rien a
    rogner — voir la remarque de l'utilisateur, "je ne veux pas du tout
    que les valeurs de corner radius de l'entete changent [...] je veux
    que l'entete soit rognee par la corner radius de la colonne" (voir
    aussi app_style.column_header_qss, MEME calcul/MEME condition cote
    appli reelle)."""
    header = dict(_radius_dict(header_radius))
    if int(header_padding) <= 0:
        column = _radius_dict(column_radius)
        header["top_left"] = max(header["top_left"], column["top_left"])
        header["top_right"] = max(header["top_right"], column["top_right"])
    return header


def _rounded_rect_path(rect: QRect, radius) -> QPainterPath:
    """Chemin rectangle arrondi — `radius` : int (rayon UNIFORME, retro-
    compatible) OU dict {"top_left": int, "top_right": int, "bottom_right":
    int, "bottom_left": int} pour un rayon INDEPENDANT par coin (voir
    _radius_dict/la remarque de l'utilisateur ci-dessus)."""
    if isinstance(radius, dict):
        d = _radius_dict(radius)
        if len(set(d.values())) == 1:
            radius = next(iter(d.values()))
        else:
            r = QRectF(rect)
            tl = min(d["top_left"], r.width() / 2, r.height() / 2)
            tr = min(d["top_right"], r.width() / 2, r.height() / 2)
            br = min(d["bottom_right"], r.width() / 2, r.height() / 2)
            bl = min(d["bottom_left"], r.width() / 2, r.height() / 2)
            path = QPainterPath()
            path.moveTo(r.left() + tl, r.top())
            path.lineTo(r.right() - tr, r.top())
            if tr > 0:
                path.arcTo(r.right() - 2 * tr, r.top(), 2 * tr, 2 * tr, 90, -90)
            path.lineTo(r.right(), r.bottom() - br)
            if br > 0:
                path.arcTo(r.right() - 2 * br, r.bottom() - 2 * br, 2 * br, 2 * br, 0, -90)
            path.lineTo(r.left() + bl, r.bottom())
            if bl > 0:
                path.arcTo(r.left(), r.bottom() - 2 * bl, 2 * bl, 2 * bl, -90, -90)
            path.lineTo(r.left(), r.top() + tl)
            if tl > 0:
                path.arcTo(r.left(), r.top(), 2 * tl, 2 * tl, 180, -90)
            path.closeSubpath()
            return path
    path = QPainterPath()
    if radius > 0:
        path.addRoundedRect(QRectF(rect), radius, radius)
    else:
        path.addRect(QRectF(rect))
    return path


def _quadrant_path(corner: QPointF, center: QPointF) -> QPainterPath:
    """Rectangle AXE-ALIGNE plein entre `corner` (un coin du rect) et
    `center` (son centre) — le quadrant COMPLET de ce coin, pas juste sa
    moitie triangulaire (voir _paint_bordered_rect/_MiniSlider._paint_
    bordered, la diagonale-vers-le-centre d'un wedge ne couvre QUE sa
    moitie du carre de coin ; quand le cote voisin est desactive, cette
    moitie manquante de l'anneau ne revient a personne)."""
    path = QPainterPath()
    path.addRect(QRectF(corner, center).normalized())
    return path


def _paint_bordered_rect(p: QPainter, rect: QRect, radius: int, border_on, thickness: int,
                          border_colors: dict, fill_color: str | None):
    """Peint un rectangle avec bordure MITREE par cote (voir _MiniSlider.
    _paint_bordered, meme technique — diagonales depuis le centre vers
    chaque coin, continue quel que soit le rayon) generalisee ici a une
    EPAISSEUR de bordure variable (les sliders restent a 1px fixe, les
    toggles l'exposent en reglage, voir Toggles > Cadre/Coche > Epaisseur
    de bordure) + remplissage (`fill_color`, ou aucun si None — la coche a
    l'etat OFF, "creuse").

    `border_on` : bool (tous les cotes pareil, retro-compatible) OU dict
    {"top": bool, ...} — un cote DESACTIVE (voir _SideColorsField, la
    remarque de l'utilisateur "au lieu d'avoir un seul toggle pour activer
    les bordures, je veux un toggle par cote") ne consomme plus d'epaisseur
    de CE cote : le remplissage s'etend alors jusqu'a ce bord, tout en
    restant en retrait des autres cotes toujours actifs (inset ASYMETRIQUE,
    pas juste un on/off global comme avant).

    `radius` : int (rayon uniforme, retro-compatible) OU dict {"top_left":
    int, ...} — un rayon INDEPENDANT par coin (voir _rounded_rect_path/la
    remarque de l'utilisateur, "si deux colonnes sont cote a cote ... le
    rayon contre l'autre colonne doit etre a zero", voir _ColumnPreview)."""
    if rect.width() <= 0 or rect.height() <= 0:
        return
    if isinstance(border_on, dict):
        sides_on = {k: bool(border_on.get(k, False)) for k in ("top", "right", "bottom", "left")}
    else:
        v = bool(border_on)
        sides_on = {k: v for k in ("top", "right", "bottom", "left")}
    thickness = max(0, int(thickness))
    t = {k: (thickness if sides_on[k] else 0) for k in sides_on}
    any_on = thickness > 0 and any(sides_on.values())
    inner_rect = QRect(
        rect.left() + t["left"], rect.top() + t["top"],
        rect.width() - t["left"] - t["right"], rect.height() - t["top"] - t["bottom"],
    )
    has_inner = inner_rect.width() > 0 and inner_rect.height() > 0
    p.save()
    p.setRenderHint(QPainter.Antialiasing, _radius_any(radius))
    # Cas RAPIDE, cote uniforme (voir plus bas, MEME resultat GEOMETRIQUE que
    # la decoupe MITREE ci-dessous, mais peint en UN SEUL drawPath via un
    # QPen — pas de sous-remplissage manuel/union de wedges) : tous les
    # cotes actifs, meme couleur — de tres loin le cas le plus courant
    # (Colonnes > Bordure "liee", Toggles/Sliders...). A un PETIT rayon
    # (proche de l'epaisseur, ex. rayon 5 / epaisseur 1) le sous-remplissage
    # par wedges (outer moins inner, coupe en 4 coins puis reunis) laissait
    # un arc visiblement plus FONCE/moins sature que les segments droits —
    # voir la remarque de l'utilisateur, "les arrondis apparaissent... plus
    # sombre que la bordure elle-meme" : l'anneau y est si fin (1px de
    # rayon entre le cercle interieur et exterieur) que chaque triangle-
    # wedge, rasterise et rempli INDEPENDAMMENT avant sa reunion, y perd de
    # la couverture sous-pixel — un trait STROKE (QPen, le rasteriseur de
    # contour dedie de Qt, concu pour garder une epaisseur visuelle
    # CONSTANTE tout le long d'un chemin, virages compris) rend cette meme
    # geometrie sans ce sous-remplissage.
    ring_painted = False
    if any_on and all(sides_on.values()) and thickness > 0:
        uniform_colors = {border_colors[s] for s in ("top", "right", "bottom", "left")}
        if len(uniform_colors) == 1:
            inset = thickness / 2.0
            centerline_rect = QRectF(rect).adjusted(inset, inset, -inset, -inset)
            centerline_radius = _radius_shrink(radius, inset)
            if centerline_rect.width() > 0 and centerline_rect.height() > 0:
                # Sur-echantillonne (4x, puis remis a l'echelle via
                # devicePixelRatio — MEME technique que _tinted_svg_pixmap,
                # deja utilisee pour rester net en HiDPI) : a UNE seule
                # passe d'antialiasing (ci-dessous, avant ce correctif), un
                # trait de 1px sur un PETIT rayon (proche de l'epaisseur)
                # ne couvre par endroits qu'une fraction du pixel le long
                # de la diagonale — geometriquement correct, mais lu par
                # l'oeil comme un arc plus terne que les segments droits.
                # 4 sous-echantillons par pixel de sortie (moyennes lors de
                # la mise a l'echelle) lissent cette transition sur PLUS de
                # pixels au lieu d'une chute brutale de couverture sur 1
                # seul — voir la remarque de l'utilisateur, "je veux que le
                # lissage de l'arrondi soit parfait" / "il faut que
                # l'epaisseur de la bordure soit a 1px" (contrainte fixe,
                # pas question de l'epaissir pour resoudre ca autrement).
                # REMPLISSAGE d'un anneau (outer moins inner, QPainterPath.
                # subtracted — PAS un QPen/stroke, essaye puis abandonne :
                # le rasteriseur de CONTOUR de Qt tesselle/offsette le
                # chemin pour lui donner une epaisseur, une etape EN PLUS
                # par rapport a un simple REMPLISSAGE de forme deja fermee
                # — sur un 1px de large, cette tesselisation supplementaire
                # laissait par endroits un arc plus terne. Un remplissage
                # direct, LUI, n'a qu'UNE seule passe d'antialiasing —
                # MEME technique que le fond (fill_color plus bas), qui n'a
                # jamais souffert de ce defaut — voir la remarque de
                # l'utilisateur, "essaye de trouver un autre algorithme...
                # celui-ci est vraiment pas beau" (carre de demonstration
                # 200x200 a l'appui, isole de toute interference de
                # contenu). Sur-echantillonne (8x, encore un cran au-dessus
                # du 1er essai a 4x) : MEME technique que _tinted_svg_
                # pixmap, deja utilisee pour rester net en HiDPI.
                ss = 8
                pad = max(1, int(thickness))
                ss_rect = QRectF(
                    0, 0, (rect.width() + 2 * pad) * ss, (rect.height() + 2 * pad) * ss)
                pixmap = QPixmap(max(1, round(ss_rect.width())), max(1, round(ss_rect.height())))
                pixmap.fill(Qt.transparent)
                sp = QPainter(pixmap)
                sp.setRenderHint(QPainter.Antialiasing, True)
                sp.scale(ss, ss)
                sp.translate(pad - rect.left(), pad - rect.top())
                outer = _rounded_rect_path(rect, radius)
                inner = _rounded_rect_path(inner_rect, _radius_shrink(radius, thickness)) if has_inner else QPainterPath()
                ring_shape = outer.subtracted(inner) if has_inner else outer
                sp.setPen(Qt.NoPen)
                sp.setBrush(QColor(next(iter(uniform_colors))))
                sp.drawPath(ring_shape)
                sp.end()
                pixmap.setDevicePixelRatio(ss)
                # SmoothPixmapTransform EXPLICITE sur `p` (PAS seulement
                # sur `sp` plus haut, un peintre DIFFERENT) : sans lui, la
                # mise a l'echelle 8x -> 1x de ce drawPixmap (via le simple
                # ecart de devicePixelRatio entre le pixmap et `p`) retombe
                # sur un plus-proche-voisin BLOCS, pas un filtrage lisse —
                # annulant tout le benefice du sur-echantillonnage ci-dessus
                # (l'escalier redevient dur, SANS aucun pixel de transition)
                # — voir la remarque de l'utilisateur, capture a l'appui,
                # "il n'est pas antialiase la ?".
                p.setRenderHint(QPainter.SmoothPixmapTransform, True)
                p.drawPixmap(QPointF(rect.left() - pad, rect.top() - pad), pixmap)
                ring_painted = True   # deja peint : saute le sous-remplissage MITRE ci-dessous
                # any_on RESTE True (pas touche) : le remplissage plus bas
                # (fill_color) doit continuer a cibler inner_rect, PAS le
                # rect ENTIER, sinon il repeindrait PAR-DESSUS l'anneau
                # qu'on vient de tracer (voir la remarque de l'utilisateur,
                # "les arrondis... plus sombre" — 1er essai de ce correctif,
                # qui mettait any_on a False ici, recouvrait justement le
                # trait par le fond).
    if any_on and not ring_painted:
        outer_path = _rounded_rect_path(rect, radius)
        inner_radius = _radius_shrink(radius, thickness)
        ring = outer_path.subtracted(_rounded_rect_path(inner_rect, inner_radius)) if has_inner else outer_path
        rf = QRectF(rect)
        center = rf.center()
        corners = {
            "top": (QPointF(rf.left(), rf.top()), QPointF(rf.right(), rf.top())),
            "right": (QPointF(rf.right(), rf.top()), QPointF(rf.right(), rf.bottom())),
            "bottom": (QPointF(rf.right(), rf.bottom()), QPointF(rf.left(), rf.bottom())),
            "left": (QPointF(rf.left(), rf.bottom()), QPointF(rf.left(), rf.top())),
        }
        p.setPen(Qt.NoPen)
        # Chaque coin (p1/p2) ALLONGE de EPS le long de son propre cote,
        # au-dela du coin REEL du rectangle — sans ca, 2 coins ENTRE UN
        # COTE ACTIF ET UN COTE DESACTIVE (voir _SideColorsField, un
        # interrupteur PAR cote) se rejoignaient exactement sur la
        # diagonale-vers-le-centre du cote actif, et l'antialiasing y
        # laissait un mini-vide (le "coin" pile a la frontiere entre 2
        # coins ne revient VRAIMENT a aucun des 2 triangles) — voir la
        # remarque de l'utilisateur, capture annotee a l'appui, "la ligne
        # ne forme pas" (le filet restait ouvert a chaque coin plutot que
        # de former un rectangle ferme).
        #
        # Cette rallonge ne doit s'appliquer QUE du cote ou le VOISIN de ce
        # coin est desactive (le vrai trou) — PAS quand les 2 cotes d'un
        # coin sont actifs : la, le triangle du voisin recouvre alors ce
        # meme demi-pixel en double, et sur un rayon arrondi (zone deja
        # anti-aliasee) ce double-recouvrement se voit comme un lisere plus
        # sature / une sorte dedgrade au lieu d'un bord net (voir la
        # remarque de l'utilisateur, "il y a encore comme une sorte de
        # degrade, je ne veux pas ca"). Donc rallonge SEULEMENT au coin ou
        # le voisin est off ; coin exact (sans rallonge) si le voisin est on
        # — le miter diagonal s'y ferme deja parfaitement, sans besoin de
        # fudge.
        # Meme 2 cotes ACTIFS de la MEME couleur (le cas le plus courant —
        # bordure uniforme) laissaient un lisere fantome pile sur la
        # diagonale du miter : 2 formes anti-aliasees peintes separement,
        # bord a bord, ne se recouvrent JAMAIS parfaitement pixel pour pixel
        # (chaque drawPath calcule sa propre att'nuation en bord de forme) —
        # visible surtout sur un coin arrondi (voir la remarque de
        # l'utilisateur, "il y a encore comme une sorte de degrade"). Fix :
        # au lieu de dessiner chaque cote separement, on ACCUMULE les
        # morceaux par couleur (united()) et on ne peint qu'UNE fois par
        # couleur — un seul drawPath = une seule frontiere anti-aliasee,
        # plus de couture interne (que les 2 cotes soient adjacents ou non,
        # united() sur des morceaux disjoints ne change rien au rendu).
        EPS = 0.75
        order = ("top", "right", "bottom", "left")
        color_paths: dict[str, QPainterPath] = {}
        for i, side in enumerate(order):
            if not sides_on[side]:
                continue
            p1, p2 = corners[side]
            neighbor_p1 = order[i - 1]
            neighbor_p2 = order[(i + 1) % 4]
            dx, dy = p2.x() - p1.x(), p2.y() - p1.y()
            length = (dx * dx + dy * dy) ** 0.5
            ux, uy = (dx / length, dy / length) if length > 0 else (0.0, 0.0)
            p1e = QPointF(p1.x() - ux * EPS, p1.y() - uy * EPS) if not sides_on[neighbor_p1] else p1
            p2e = QPointF(p2.x() + ux * EPS, p2.y() + uy * EPS) if not sides_on[neighbor_p2] else p2
            wedge = QPainterPath()
            wedge.moveTo(p1e)
            wedge.lineTo(p2e)
            wedge.lineTo(center)
            wedge.closeSubpath()
            # Coin ou le voisin est desactive : la diagonale-vers-le-centre
            # ne couvre que LA MOITIE du carre de ce coin (l'autre moitie
            # appartenait au triangle du voisin, qui n'existe plus) — plus
            # le rectangle est fin/allonge, plus cette diagonale rase le
            # bord et laisse un triangle de l'anneau non couvert PRES du
            # coin (personne ne le reclame) — voir la remarque de
            # l'utilisateur, capture a l'appui, "la bordure de la selection
            # ne continue pas de maniere constante jusqu'au bord de la
            # colonne". Fix : unir le wedge avec le rectangle ENTIER coin<->
            # centre (le quadrant complet, pas juste sa moitie triangulaire)
            # — recouvre alors aussi la moitie qui revenait au voisin,
            # sans effet de bord (intersecte avec `ring` de toute facon).
            if not sides_on[neighbor_p1]:
                wedge = wedge.united(_quadrant_path(p1, center))
            if not sides_on[neighbor_p2]:
                wedge = wedge.united(_quadrant_path(p2, center))
            piece = ring.intersected(wedge)
            color = border_colors[side]
            color_paths[color] = color_paths[color].united(piece) if color in color_paths else piece
        for color, path in color_paths.items():
            p.setBrush(QColor(color))
            p.drawPath(path)
    if fill_color is not None:
        target_rect = inner_rect if any_on else rect
        if target_rect.width() > 0 and target_rect.height() > 0:
            clip_radius = _radius_shrink(radius, thickness) if any_on else radius
            if _radius_any(clip_radius):
                p.setClipPath(_rounded_rect_path(target_rect, clip_radius))
            p.fillRect(target_rect, QColor(fill_color))
    p.restore()


def _paint_toggle_shape(p: QPainter, x: int, y: int, style_key: str, style: dict, checked: bool,
                         progress: float | None = None):
    """Dessine le cadre EXTERIEUR + la coche INTERIEURE d'un toggle a la
    position (x, y), selon `style` (voir _TOGGLE1_STYLE/_TOGGLE2_STYLE) —
    factorise entre _Toggle.paintEvent (style COURANT de la fenetre, voir
    _TOGGLE_STYLE) et _ToggleShapePreview (apercu de CHAQUE style, voir
    Toggles > Style, toujours a l'etat FIXE ON/OFF — jamais anime).

    `progress` (0.0 = OFF, 1.0 = ON) anime la TRANSITION entre les 2 etats
    (voir _Toggle, qui glisse cette valeur de 0 a 1 ou l'inverse au clic —
    voir la remarque de l'utilisateur, "une animation quand le toggle
    passe de l'etat on a l'etat off et vice versa") ; None (les 2 apercus
    statiques ci-dessus) retombe sur l'etat fixe de `checked` (0.0 ou 1.0).

    Les 2 styles se comportent tres differemment entre ON et OFF (voir la
    remarque de l'utilisateur, corrigeant un malentendu precedent) :
    - "toggle1" : GLISSIERE classique — la coche garde TOUJOURS le meme
      style (bordure/couleur/taille inchangees), seule sa POSITION change,
      caleé a droite (ON) ou a gauche (OFF), avec la meme marge des 2
      cotes (voir Toggles > Coche > Distance du bord) — animee ici par un
      simple LERP de sa position x entre les 2 bornes.
    - "toggle2" : la coche reste centree mais DISPARAIT completement a
      l'etat OFF (rien de dessine, pas meme un contour) — ne s'affiche
      qu'a l'etat ON — animee ici par un FONDU (opacite = progress)."""
    if progress is None:
        progress = 1.0 if checked else 0.0
    outer_rect = QRect(x, y, style["outer_w"], style["outer_h"])
    outer_colors = {side: style[f"outer_border_{side}"] for side in ("top", "right", "bottom", "left")}
    _paint_bordered_rect(p, outer_rect, style["outer_border_radius"], style["outer_border_enabled"],
                          style["outer_border_thickness"], outer_colors, style["outer_bg"])
    margin = style["coche_margin"]
    # coche_h est deduite de outer_h en retirant 2x la marge (voir
    # _sync_toggle_shape_style), donc marge haute = marge basse = margin,
    # ce qui centre deja la coche verticalement — vrai pour les 2 styles,
    # quel que soit l'etat.
    cy = y + margin
    if style_key == "toggle2":
        if progress <= 0.0:
            return   # coche invisible a l'etat OFF (rien a peindre)
        cx = x + (style["outer_w"] - style["coche_w"]) // 2
    else:
        off_x = margin
        on_x = max(0, style["outer_w"] - margin - style["coche_w"])
        cx = x + round(off_x + (on_x - off_x) * progress)
    coche_rect = QRect(cx, cy, style["coche_w"], style["coche_h"])
    coche_colors = {side: style[f"coche_border_{side}"] for side in ("top", "right", "bottom", "left")}
    if style_key == "toggle2" and progress < 1.0:
        p.save()
        p.setOpacity(p.opacity() * progress)
        _paint_bordered_rect(p, coche_rect, style["coche_border_radius"], style["coche_border_enabled"],
                              style["coche_border_thickness"], coche_colors, style["coche_color"])
        p.restore()
    else:
        _paint_bordered_rect(p, coche_rect, style["coche_border_radius"], style["coche_border_enabled"],
                              style["coche_border_thickness"], coche_colors, style["coche_color"])


class _Toggle(QWidget):
    """Interrupteur peint a la main selon le style COURANT (voir
    _TOGGLE_STYLE/_paint_toggle_shape — cadre + coche, entierement
    reglables, voir Toggles > Style) + libelle d'etat a droite — utilise
    pour les cadres actif/sans de la page Geometrie, et pour tout autre
    reglage on/off de cette fenetre.

    La transition ON<->OFF est ANIMEE (voir _progress/_anim ci-dessous,
    et _paint_toggle_shape qui sait desormais peindre un etat
    INTERMEDIAIRE) — voir la remarque de l'utilisateur, "une animation
    quand le toggle passe de l'etat on a l'etat off et vice versa"."""

    _ANIM_MS = 140

    toggled = Signal(bool)

    def __init__(self, checked: bool = False, on_label="actif", off_label="sans", parent=None,
                 style_override: str | None = None, show_label: bool = True):
        super().__init__(parent)
        self._checked = checked
        # _progress (0.0 = OFF, 1.0 = ON) est ce que peint REELLEMENT
        # paintEvent — _checked est l'etat final CIBLE (deja a jour des le
        # clic, voir setChecked : le libelle texte, lui, bascule tout de
        # suite plutot que de tenter un fondu croise entre 2 mots) ; SEUL
        # _progress glisse progressivement de l'un a l'autre pendant
        # l'animation.
        self._progress = 1.0 if checked else 0.0
        self._on_label, self._off_label = on_label, off_label
        # `style_override` ("toggle1"/"toggle2"/None) : ignore le style
        # COURANT de la fenetre (_TOGGLE_STYLE) et fige celui-ci a la place
        # — voir la remarque de l'utilisateur, "je veux overider le style
        # du toggle ici pour le toggle 2" (les interrupteurs par cote des
        # reglages de bordure, voir _SideColorsField, doivent toujours
        # avoir l'apparence "toggle2" quel que soit le style choisi dans
        # Toggles > Style). `show_label` False : masque "actif"/"sans" a
        # cote du cadre — voir la remarque de l'utilisateur, "ne mets pas
        # l'annotation actif a cote du toggle, uniquement le toggle en lui
        # meme" (memes interrupteurs par cote).
        self._style_override = style_override
        self._show_label = show_label
        self.setCursor(Qt.PointingHandCursor)
        self._anim = QVariantAnimation(self)
        self._anim.setDuration(self._ANIM_MS)
        self._anim.setEasingCurve(QEasingCurve.OutCubic)
        self._anim.valueChanged.connect(self._on_anim_value)
        self.apply_style()

    def _on_anim_value(self, value):
        self._progress = float(value)
        self.update()

    def _style_key(self) -> str:
        return self._style_override or _TOGGLE_STYLE

    def _style(self) -> dict:
        if self._style_override == "toggle2":
            return _TOGGLE2_STYLE
        if self._style_override == "toggle1":
            return _TOGGLE1_STYLE
        return _active_toggle_style()

    def apply_style(self):
        """Rejoue le style COURANT (voir _TOGGLE_STYLE), OU celui fige par
        `style_override` (voir __init__) — a rappeler sur toute instance
        deja construite quand ce reglage change (voir SettingsWindow.
        _on_toggle_style_changed) : necessaire, pas un simple repaint,
        puisque la taille meme du cadre (outer_w/outer_h) peut avoir
        change."""
        style = self._style()
        self._outer_w = style["outer_w"]
        h = max(25, style["outer_h"] + 8)
        # Pas de place reservee au libelle (+9+40) si `show_label` est
        # False (voir __init__) : juste le cadre, une petite marge (6px,
        # meme valeur que le 1er terme de "9" ci-dessous arrondi) pour ne
        # pas coller le cadre au bord du widget.
        w = max(30, style["outer_w"]) + (9 + 40 if self._show_label else 6)
        self.setFixedSize(w, h)
        self.update()

    def isChecked(self) -> bool:
        return self._checked

    def setChecked(self, checked: bool):
        if checked == self._checked:
            return
        self._checked = checked
        # Pas de garde sur self.isVisible() : la plupart des toggles vivent
        # dans une section REPLIEE par defaut (voir _Section), donc
        # invisibles la plupart du temps sans etre pour autant "avant le
        # premier affichage" — anime dans tous les cas (l'animation, ~140ms,
        # est de toute facon terminee bien avant qu'on deplie la section
        # pour la voir)."""
        self._anim.stop()
        self._anim.setStartValue(self._progress)
        self._anim.setEndValue(1.0 if checked else 0.0)
        self._anim.start()
        self.toggled.emit(checked)

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            self.setChecked(not self._checked)

    def paintEvent(self, event):
        p = QPainter(self)
        style = self._style()
        y = (self.height() - style["outer_h"]) // 2
        # x=0 quand un libelle suit a droite (voir apply_style, largeur du
        # widget = cadre + marge fixe reservee au texte) ; SANS libelle, le
        # cadre est plus etroit que le widget (voir apply_style, marge de
        # 6px) et doit alors etre CENTRE horizontalement dans ce widget —
        # sinon il apparait decale par rapport a la pastille de couleur/au
        # texte G/H/B/D juste en dessous (voir _SideColorsField, meme
        # colonne alignee au centre) — voir la remarque de l'utilisateur,
        # "le toggle n'est pas centre avec le carre de couleur".
        x = 0 if self._show_label else max(0, (self.width() - style["outer_w"]) // 2)
        _paint_toggle_shape(p, x, y, self._style_key(), style, self._checked, progress=self._progress)
        if self._show_label:
            p.setFont(_qfont(10, 400, mono=True))
            # Couleur du libelle interpolee sur _progress (pas juste
            # _checked) : suit le meme fondu que la coche plutot que de
            # sauter net des le debut du glisser.
            on_color, off_color = QColor(M["toggle_on_fg"]), QColor(M["toggle_off_fg"])
            t = self._progress
            label_color = QColor(
                round(off_color.red() + (on_color.red() - off_color.red()) * t),
                round(off_color.green() + (on_color.green() - off_color.green()) * t),
                round(off_color.blue() + (on_color.blue() - off_color.blue()) * t),
            )
            p.setPen(label_color)
            label_x = self._outer_w + 9
            p.drawText(label_x, 0, 40, self.height(), Qt.AlignVCenter | Qt.AlignLeft,
                       self._on_label if self._checked else self._off_label)
        p.end()


class _ToggleShapePreview(QWidget):
    """Apercu ON+OFF cote a cote pour un style ("toggle1"/"toggle2") — LIT
    en direct _TOGGLE1_STYLE/_TOGGLE2_STYLE (voir refresh, rappele par
    SettingsWindow._on_toggle_style_changed a chaque reglage touche dans
    les tableaux Cadre/Coche ci-dessous) : pas un simple apercu fige, il
    suit les 2 tableaux en temps reel. Pur apercu, non interactif — le
    choix du style se fait en cliquant la carte englobante (voir
    _ToggleStyleCard)."""

    _GAP = 16
    _PAD = 6

    def __init__(self, style_key: str, parent=None):
        super().__init__(parent)
        self._style_key = style_key
        self._slot_w = 40
        self.refresh()

    def _style(self) -> dict:
        return _TOGGLE1_STYLE if self._style_key == "toggle1" else _TOGGLE2_STYLE

    def sizeHint(self):
        # setFixedSize() pose deja minimumSize()/maximumSize(), mais PAS
        # sizeHint() (QWidget la laisse invalide par defaut, voir sa doc) —
        # un ancetre cache puis reaffiche (voir _Section.set_collapsed)
        # peut alors re-figer un layout base sur cette taille invalide
        # avant que minimumSize() ne soit reconsideree, laissant cet apercu
        # ecrase a une hauteur minuscule (voir la remarque de l'utilisateur,
        # capture a l'appui : carte de style quasi vide).
        return self.size()

    def refresh(self):
        style = self._style()
        self._slot_w = max(style["outer_w"], style["coche_w"]) + self._PAD * 2
        h = max(style["outer_h"], 18) + self._PAD * 2 + 16
        self.setFixedSize(self._slot_w * 2 + self._GAP, h)
        self.updateGeometry()
        self.update()

    def paintEvent(self, event):
        p = QPainter(self)
        style = self._style()
        y = self._PAD
        x0 = (self._slot_w - style["outer_w"]) // 2
        x1 = self._slot_w + self._GAP + (self._slot_w - style["outer_w"]) // 2
        _paint_toggle_shape(p, x0, y, self._style_key, style, True)
        _paint_toggle_shape(p, x1, y, self._style_key, style, False)
        p.setFont(_qfont(8, 600, mono=True, tracking=0.4))
        p.setPen(QColor(M["unit"]))
        label_y = y + style["outer_h"] + 4
        p.drawText(0, label_y, self._slot_w, 14, Qt.AlignHCenter, "ON")
        p.drawText(self._slot_w + self._GAP, label_y, self._slot_w, 14, Qt.AlignHCenter, "OFF")
        p.end()


class _ToggleStyleCard(QWidget):
    """Une carte cliquable du selecteur de style (voir _ToggleStylePicker) :
    libelle + apercu ON/OFF en direct (voir _ToggleShapePreview) — bordure
    accentuee quand selectionnee, meme logique que les autres "cartes"
    cliquables de cette fenetre (voir _PresetListRow)."""

    clicked = Signal()

    def __init__(self, style_key: str, label: str, parent=None):
        super().__init__(parent)
        self._selected = False
        self.setObjectName("ToggleStyleCard")
        self.setAttribute(Qt.WA_StyledBackground, True)
        self.setCursor(Qt.PointingHandCursor)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 10, 16, 10)
        layout.setSpacing(8)
        title = QLabel(label)
        title.setFont(_qfont(11, 600))
        title.setAlignment(Qt.AlignHCenter)
        title.setStyleSheet(f"color: {M['value_fg']}; background: transparent;")
        layout.addWidget(title, 0, Qt.AlignHCenter)
        self.preview = _ToggleShapePreview(style_key)
        layout.addWidget(self.preview, 0, Qt.AlignHCenter)
        self._refresh_style()

    def _refresh_style(self):
        border = M["accent"] if self._selected else M["field_border"]
        bg = M["btn_hover"] if self._selected else M["field_bg"]
        self.setStyleSheet(f"#ToggleStyleCard {{ background: {bg}; border: 1px solid {border}; border-radius: 4px; }}")

    def setSelected(self, selected: bool):
        if selected != self._selected:
            self._selected = selected
            self._refresh_style()

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            self.clicked.emit()


class _ToggleStylePicker(QWidget):
    """Choix du style visuel de TOUS les toggles de cette fenetre (voir
    _Toggle/_TOGGLE_STYLE) — 2 cartes cliquables (Toggle 1/Toggle 2),
    chacune avec son propre apercu ON/OFF en direct — voir la remarque de
    l'utilisateur, capture annotee a l'appui (mockup corrige des 2
    styles)."""

    changed = Signal(str)

    _OPTIONS = [("toggle1", "Toggle 1"), ("toggle2", "Toggle 2")]

    def __init__(self, value: str, parent=None):
        super().__init__(parent)
        valid = dict(self._OPTIONS)
        self._value = value if value in valid else "toggle1"
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(14)
        self._cards: dict[str, _ToggleStyleCard] = {}
        for key, label in self._OPTIONS:
            card = _ToggleStyleCard(key, label)
            card.setSelected(key == self._value)
            card.clicked.connect(lambda _checked=False, k=key: self._select(k))
            self._cards[key] = card
            layout.addWidget(card)

    def _select(self, key: str):
        if key != self._value:
            self._value = key
            for k, card in self._cards.items():
                card.setSelected(k == key)
            self.changed.emit(key)

    def value(self) -> str:
        return self._value

    def setValue(self, value: str):
        if value in self._cards and value != self._value:
            self._select(value)

    def refreshPreviews(self):
        """Rappele quand les tableaux Cadre/Coche changent (voir
        SettingsWindow._on_toggle_style_changed) : les apercus de CETTE
        carte lisent _TOGGLE1_STYLE/_TOGGLE2_STYLE en direct, ils ont juste
        besoin d'un repaint (+ recalcul de taille, voir _ToggleShapePreview.
        refresh)."""
        for card in self._cards.values():
            card.preview.refresh()


# ==========================================================================
# Selecteur de couleur maison (remplace QColorDialog, dont l'habillage
# systeme jurait avec le reste de l'appli — voir la remarque de
# l'utilisateur, maquette html fournie a l'appui) : carre saturation/
# luminosite + 3 sliders TSL + 3 sliders RVB, tous synchronises sur une
# seule verite (self._h/_s/_v), plus palette de l'appli (C) et couleurs
# recentes. colorChanged emet a CHAQUE mouvement (glisser un slider, le
# carre...), pas seulement a la validation : c'est ce qui permet a
# _ColorField de repercuter le changement en direct sur la fenetre
# principale, exactement comme le faisait deja QColorDialog en connectant
# son propre currentColorChanged — voir _ColorField._pick.
# ==========================================================================

def _hsv_to_rgb(h: float, s: float, v: float) -> tuple[int, int, int]:
    c = v * s
    x = c * (1 - abs((h / 60) % 2 - 1))
    m = v - c
    if h < 60:
        r, g, b = c, x, 0.0
    elif h < 120:
        r, g, b = x, c, 0.0
    elif h < 180:
        r, g, b = 0.0, c, x
    elif h < 240:
        r, g, b = 0.0, x, c
    elif h < 300:
        r, g, b = x, 0.0, c
    else:
        r, g, b = c, 0.0, x
    return (
        max(0, min(255, round((r + m) * 255))),
        max(0, min(255, round((g + m) * 255))),
        max(0, min(255, round((b + m) * 255))),
    )


def _rgb_to_hex(rgb) -> str:
    return "#{:02x}{:02x}{:02x}".format(*(max(0, min(255, int(c))) for c in rgb))


def _rgb_to_hsv(r: int, g: int, b: int) -> tuple[float, float, float]:
    rf, gf, bf = r / 255, g / 255, b / 255
    mx, mn = max(rf, gf, bf), min(rf, gf, bf)
    d = mx - mn
    if d == 0:
        h = 0.0
    elif mx == rf:
        h = 60 * (((gf - bf) / d) % 6)
    elif mx == gf:
        h = 60 * ((bf - rf) / d + 2)
    else:
        h = 60 * ((rf - gf) / d + 4)
    return h % 360, (d / mx if mx else 0.0), mx


def _hex_to_rgb(hexval: str) -> tuple[int, int, int]:
    h = (hexval or "#000000").lstrip("#")
    if len(h) != 6:
        h = "000000"
    return tuple(int(h[i:i + 2], 16) for i in (0, 2, 4))


def _hex_to_hsv(hexval: str) -> tuple[float, float, float]:
    return _rgb_to_hsv(*_hex_to_rgb(hexval))


class _SVPad(QWidget):
    """Carre saturation/luminosite peint a la main : fond = degrade blanc
    -> teinte pure (horizontal) par-dessus degrade transparent -> noir
    (vertical), curseur rond a la position (s, v) courante."""

    changed = Signal(float, float)   # (s, v), chacun 0..1

    def __init__(self, width: int = 276, height: int = 160, parent=None):
        super().__init__(parent)
        self._hue = 0.0
        self._s = 0.0
        self._v = 0.0
        self.setFixedSize(width, height)
        self.setCursor(Qt.CrossCursor)

    def setHue(self, hue: float):
        if hue != self._hue:
            self._hue = hue
            self.update()

    def setSV(self, s: float, v: float):
        s = max(0.0, min(1.0, s))
        v = max(0.0, min(1.0, v))
        if (s, v) != (self._s, self._v):
            self._s, self._v = s, v
            self.update()

    def _emit_from_pos(self, pos):
        w, h = max(1, self.width() - 1), max(1, self.height() - 1)
        s = max(0.0, min(1.0, pos.x() / w))
        v = 1.0 - max(0.0, min(1.0, pos.y() / h))
        self._s, self._v = s, v
        self.update()
        self.changed.emit(s, v)

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            self._emit_from_pos(event.position().toPoint())

    def mouseMoveEvent(self, event):
        if event.buttons() & Qt.LeftButton:
            self._emit_from_pos(event.position().toPoint())

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing, False)
        rect = self.rect()
        pure = QColor(*_hsv_to_rgb(self._hue, 1.0, 1.0))
        p.fillRect(rect, pure)
        sat_grad = QLinearGradient(rect.topLeft(), rect.topRight())
        sat_grad.setColorAt(0, QColor(255, 255, 255, 255))
        sat_grad.setColorAt(1, QColor(255, 255, 255, 0))
        p.fillRect(rect, sat_grad)
        val_grad = QLinearGradient(rect.topLeft(), rect.bottomLeft())
        val_grad.setColorAt(0, QColor(0, 0, 0, 0))
        val_grad.setColorAt(1, QColor(0, 0, 0, 255))
        p.fillRect(rect, val_grad)
        p.setRenderHint(QPainter.Antialiasing, True)
        x = int(self._s * (self.width() - 1))
        y = int((1 - self._v) * (self.height() - 1))
        p.setPen(QPen(QColor("#ffffff"), 2))
        p.setBrush(Qt.NoBrush)
        p.drawEllipse(QPoint(x, y), 6, 6)
        p.setPen(QPen(QColor(0, 0, 0, 160), 1))
        p.drawEllipse(QPoint(x, y), 7, 7)
        p.end()


class _GradientSlider(QWidget):
    """Slider horizontal peint a la main, degrade fourni par l'appelant
    (voir setStops) — utilise pour les 6 lignes TSL/RVB du selecteur de
    couleur : le degrade de chaque slider montre le resultat du
    deplacement AVANT de le faire (voir _ColorPickerPopup._refresh_all,
    qui recalcule ces degrades a chaque changement, meme sur un AUTRE
    slider — ex : le degrade "Saturation" depend de la Luminosite
    courante)."""

    changed = Signal(float)   # 0..1

    def __init__(self, width: int = 140, height: int = 13, parent=None):
        super().__init__(parent)
        self._frac = 0.0
        self._stops: list[tuple[float, QColor]] = [(0.0, QColor("#000000")), (1.0, QColor("#ffffff"))]
        # Largeur MINIMALE, pas fixe : ce slider est ajoute avec un facteur
        # d'etirement (voir _make_row, row.addWidget(slider, 1)) pour
        # occuper l'espace restant de la ligne — un setFixedSize figeait sa
        # largeur a `width` quoi qu'il arrive, ce qui neutralisait cet
        # etirement et pouvait meme faire deborder la ligne (ex. largeur de
        # boite de valeur/espacement augmentes plus tard, voir la remarque
        # de l'utilisateur sur l'espace slider/boite) au lieu de simplement
        # se retrecir pour laisser la place. La hauteur, elle, reste fixe
        # (barre fine, jamais besoin de grandir verticalement).
        self.setMinimumWidth(min(width, 60))
        self.setFixedHeight(height)
        self.setCursor(Qt.CrossCursor)

    def setStops(self, stops):
        self._stops = [(pos, QColor(hexval)) for pos, hexval in stops]
        self.update()

    def setFraction(self, frac: float):
        frac = max(0.0, min(1.0, frac))
        if frac != self._frac:
            self._frac = frac
            self.update()

    def _emit_from_x(self, x: int):
        w = max(1, self.width() - 1)
        frac = max(0.0, min(1.0, x / w))
        self._frac = frac
        self.update()
        self.changed.emit(frac)

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            self._emit_from_x(int(event.position().x()))

    def mouseMoveEvent(self, event):
        if event.buttons() & Qt.LeftButton:
            self._emit_from_x(int(event.position().x()))

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing, False)
        rect = self.rect()
        grad = QLinearGradient(rect.topLeft(), rect.topRight())
        for pos, color in self._stops:
            grad.setColorAt(pos, color)
        p.fillRect(rect, grad)
        p.setPen(QPen(QColor(M["swatch_border"]), 1))
        p.drawRect(rect.adjusted(0, 0, -1, -1))
        x = int(self._frac * max(0, self.width() - 3))
        p.setPen(Qt.NoPen)
        p.setBrush(QColor("#ffffff"))
        p.drawRect(x, -3, 3, self.height() + 6)
        p.setPen(QPen(QColor(0, 0, 0, 160), 1))
        p.setBrush(Qt.NoBrush)
        p.drawRect(x, -3, 3, self.height() + 6)
        p.end()


class _PickerCloseButton(QPushButton):
    """Petit bouton "X" peint a la main — meme raison que _HamburgerButton
    (glyphe unicode non fiable a cette taille selon la police systeme)."""

    def __init__(self, color: str, parent=None):
        super().__init__(parent)
        self._color = color

    def paintEvent(self, event):
        super().paintEvent(event)
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing, True)
        painter.setPen(QPen(QColor(self._color), 1.3))
        w, h = self.width(), self.height()
        cx, cy = w / 2, h / 2
        s = min(w, h) * 0.22
        painter.drawLine(QPointF(cx - s, cy - s), QPointF(cx + s, cy + s))
        painter.drawLine(QPointF(cx - s, cy + s), QPointF(cx + s, cy - s))
        painter.end()


class _PipetteButton(QPushButton):
    """Petit bouton pipette peint a la main — meme raison que
    _PickerCloseButton (glyphe unicode non fiable selon la police
    systeme) : capture d'une couleur n'importe ou a l'ecran."""

    def __init__(self, color: str, parent=None):
        super().__init__(parent)
        self._color = color

    def paintEvent(self, event):
        super().paintEvent(event)
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing, True)
        painter.setPen(QPen(QColor(self._color), 1.3))
        w, h = self.width(), self.height()
        # corps du compte-gouttes : trait diagonal + pointe, incline a 45°
        x1, y1 = w * 0.28, h * 0.72
        x2, y2 = w * 0.68, h * 0.32
        painter.drawLine(QPointF(x1, y1), QPointF(x2, y2))
        painter.drawEllipse(QPointF(x2, y2), 2.2, 2.2)
        painter.drawLine(QPointF(w * 0.22, h * 0.78), QPointF(w * 0.32, h * 0.68))
        painter.end()


class _PipetteAreaButton(QPushButton):
    """Variante "zone" du bouton pipette — glyphe rectangle en pointilles,
    pour la difference de la pipette point (_PipetteButton)."""

    def __init__(self, color: str, parent=None):
        super().__init__(parent)
        self._color = color

    def paintEvent(self, event):
        super().paintEvent(event)
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing, True)
        pen = QPen(QColor(self._color), 1.3, Qt.DashLine)
        painter.setPen(pen)
        w, h = self.width(), self.height()
        rect = QRect(int(w * 0.22), int(h * 0.28), int(w * 0.56), int(h * 0.44))
        painter.drawRect(rect)
        painter.end()


def _grab_virtual_desktop() -> tuple[QPixmap, QPoint]:
    """Capture tous les ecrans en un seul pixmap, recale sur l'origine du
    bureau virtuel (qui peut etre negative si un moniteur est place a
    gauche/au-dessus du principal). Retourne (pixmap, origine)."""
    screens = QGuiApplication.screens()
    geo = QRect()
    for screen in screens:
        geo = geo.united(screen.geometry())
    origin = geo.topLeft()
    pixmap = QPixmap(geo.size())
    pixmap.fill(Qt.black)
    painter = QPainter(pixmap)
    for screen in screens:
        shot = screen.grabWindow(0)
        shot.setDevicePixelRatio(1.0)
        painter.drawPixmap(screen.geometry().translated(-origin), shot)
    painter.end()
    return pixmap, origin


def _make_pipette_cursor() -> QCursor:
    """Curseur "compte-gouttes" — remplace le curseur systeme le temps de
    la capture (voir la demande : le curseur doit rester ce glyphe jusqu'a
    la selection, pas juste une croix generique)."""
    size = 28
    pm = QPixmap(size, size)
    pm.fill(Qt.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.Antialiasing, True)
    tip = QPointF(5, 23)
    tail = QPointF(19, 9)
    pen_outline = QPen(QColor("#000000"), 4.2)
    pen_outline.setCapStyle(Qt.RoundCap)
    p.setPen(pen_outline)
    p.drawLine(tip, tail)
    pen_fill = QPen(QColor("#ffffff"), 2.2)
    pen_fill.setCapStyle(Qt.RoundCap)
    p.setPen(pen_fill)
    p.drawLine(tip, tail)
    p.setPen(QPen(QColor("#000000"), 1))
    p.setBrush(QColor("#ffffff"))
    p.drawEllipse(tip, 2.6, 2.6)
    p.end()
    return QCursor(pm, int(tip.x()), int(tip.y()))


class _ScreenCaptureOverlay(QWidget):
    """Base commune aux deux pipettes : fenetre plein "bureau virtuel"
    (tous les moniteurs) affichant une copie figee de l'ecran, sur
    laquelle vient se dessiner l'interaction propre a chaque sous-classe
    (point ou rectangle). Echap annule toujours."""

    picked = Signal(str)
    cancelled = Signal()

    def __init__(self):
        super().__init__(None, Qt.FramelessWindowHint | Qt.Tool | Qt.WindowStaysOnTopHint)
        self.setAttribute(Qt.WA_DeleteOnClose)
        self.setMouseTracking(True)
        self._resolved = False
        self._pixmap, self._origin = _grab_virtual_desktop()
        self._image = self._pixmap.toImage()
        self.setGeometry(QRect(self._origin, self._pixmap.size()))

    def paintEvent(self, event):
        p = QPainter(self)
        p.drawPixmap(0, 0, self._pixmap)
        self._paint_overlay(p)
        p.end()

    def _paint_overlay(self, painter: QPainter):
        pass

    def _color_at(self, pos: QPoint):
        x, y = pos.x(), pos.y()
        if 0 <= x < self._image.width() and 0 <= y < self._image.height():
            return QColor(self._image.pixel(x, y))
        return None

    def keyPressEvent(self, event):
        if event.key() == Qt.Key_Escape:
            self._finish(None)
        else:
            super().keyPressEvent(event)

    def _finish(self, hexval):
        if self._resolved:
            return
        self._resolved = True
        if hexval is not None:
            self.picked.emit(hexval)
        else:
            self.cancelled.emit()
        self.close()


class _EyedropperOverlay(_ScreenCaptureOverlay):
    """Pipette "point" — capture la couleur du pixel sous le curseur.
    Le curseur systeme prend la forme d'un compte-gouttes et le garde
    jusqu'au clic (voir _make_pipette_cursor) ; une pastille flottante
    affiche le hex du pixel survole, en plus du curseur, pour lire la
    valeur avant de valider. Clic gauche valide, tout autre bouton ou
    Echap annule."""

    def __init__(self):
        super().__init__()
        self.setCursor(_make_pipette_cursor())
        self._last_hex = "#000000"
        self._preview = QLabel(self)
        self._preview.setFont(_qfont(10, 600, mono=True))
        self._preview.hide()

    def mouseMoveEvent(self, event):
        pos = event.position().toPoint()
        color = self._color_at(pos)
        if color is not None:
            self._last_hex = color.name()
            fg = "#000000" if color.lightness() > 128 else "#ffffff"
            self._preview.setText(f"  {self._last_hex}  ")
            self._preview.setStyleSheet(
                f"background: {self._last_hex}; color: {fg}; border: 1px solid #000000; padding: 2px;"
            )
            self._preview.adjustSize()
            self._preview.move(pos.x() + 18, pos.y() + 22)
            self._preview.show()

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            color = self._color_at(event.position().toPoint())
            self._finish(color.name() if color is not None else self._last_hex)
        else:
            self._finish(None)


class _AreaEyedropperOverlay(_ScreenCaptureOverlay):
    """Pipette "zone" — on glisse un rectangle, la couleur retenue est la
    moyenne des pixels de la selection (sous-echantillonnee sur une
    grille 32x32 pour rester instantanee meme sur une grande zone).
    Clic-glisser puis relacher valide ; Echap ou clic droit annule."""

    def __init__(self):
        super().__init__()
        self.setCursor(Qt.CrossCursor)
        self._dragging = False
        self._start = QPoint()
        self._current_rect = QRect()
        self._last_hex = "#000000"
        self._preview = QLabel(self)
        self._preview.setFont(_qfont(10, 600, mono=True))
        self._preview.hide()

    def _average_color(self, rect: QRect) -> QColor:
        rect = rect.intersected(self._image.rect())
        if rect.width() <= 0 or rect.height() <= 0:
            return QColor(self._last_hex)
        sample = self._image.copy(rect).scaled(
            32, 32, Qt.IgnoreAspectRatio, Qt.SmoothTransformation
        )
        r = g = b = n = 0
        for y in range(sample.height()):
            for x in range(sample.width()):
                c = sample.pixelColor(x, y)
                r += c.red()
                g += c.green()
                b += c.blue()
                n += 1
        if n == 0:
            return QColor(self._last_hex)
        return QColor(r // n, g // n, b // n)

    def _update_preview(self, pos: QPoint):
        color = self._average_color(self._current_rect)
        self._last_hex = color.name()
        fg = "#000000" if color.lightness() > 128 else "#ffffff"
        self._preview.setText(f"  {self._last_hex}  moyenne  ")
        self._preview.setStyleSheet(
            f"background: {self._last_hex}; color: {fg}; border: 1px solid #000000; padding: 2px;"
        )
        self._preview.adjustSize()
        self._preview.move(pos.x() + 18, pos.y() + 22)
        self._preview.show()

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            self._dragging = True
            self._start = event.position().toPoint()
            self._current_rect = QRect(self._start, self._start)
            self.update()
        else:
            self._finish(None)

    def mouseMoveEvent(self, event):
        pos = event.position().toPoint()
        if self._dragging:
            self._current_rect = QRect(self._start, pos).normalized()
            self._update_preview(pos)
            self.update()

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.LeftButton and self._dragging:
            self._dragging = False
            color = self._average_color(self._current_rect)
            self._finish(color.name())

    def _paint_overlay(self, painter: QPainter):
        if self._current_rect.isNull() or self._current_rect.isEmpty():
            return
        painter.setPen(QPen(QColor("#ffffff"), 1.5))
        painter.setBrush(QColor(255, 255, 255, 40))
        painter.drawRect(self._current_rect)


class _PopupHeader(QWidget):
    """En-tete du popup couleur — glissable : le popup n'a pas d'autre
    barre de titre ni de bord redimensionnable, et s'ouvre toujours a une
    position fixe pres de la pastille cliquee (voir show_near), qui peut
    geneur (ex. juste au-dessus d'une zone de l'ecran qu'on veut piocher a
    la pipette). Cliquer-glisser n'importe ou sur ce bandeau (hors les
    boutons pipette/fermer, qui recoivent et consomment deja leurs propres
    clics avant que head en soit informe) deplace tout le popup."""

    def __init__(self, popup: QWidget, parent=None):
        super().__init__(parent)
        self._popup = popup
        self._drag_offset = None

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            self._drag_offset = event.globalPosition().toPoint() - self._popup.pos()
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        if self._drag_offset is not None and (event.buttons() & Qt.LeftButton):
            self._popup.move(event.globalPosition().toPoint() - self._drag_offset)
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        self._drag_offset = None
        super().mouseReleaseEvent(event)


class _ColorPickerPopup(QWidget):
    """Selecteur de couleur maison — remplace QColorDialog. colorChanged
    emet a chaque mouvement (previsualisation en direct sur la fenetre
    principale, voir _ColorField._pick) ; committed seulement a la
    validation (Valider, ou un clic en dehors du popup — voir closeEvent),
    qui fige aussi la couleur dans les "Recentes" ; cancelled restaure la
    valeur de depart (bouton Annuler ou croix, jamais un simple clic
    dehors — voir la meme remarque)."""

    colorChanged = Signal(str)
    committed = Signal(str)
    cancelled = Signal()

    # Bornes du glisser sur le bord droit (voir mousePressEvent) : 300 =
    # largeur d'origine (avant setFixedWidth), 640 = large sans depasser
    # demesurement un ecran modeste.
    _MIN_WIDTH = 300
    _MAX_WIDTH = 640
    _RESIZE_MARGIN = 6

    def __init__(self, initial_hex: str, title: str, parent=None):
        super().__init__(parent, Qt.Popup)
        self._before = initial_hex
        self._resolved = False
        self._h, self._s, self._v = _hex_to_hsv(initial_hex)
        # Meme rayon que les vraies zones de saisie de l'appli principale
        # (voir get_input_radius) — calcule ici, AVANT _make_row (boites de
        # valeur TSL/RVB) ET la boite HEX/le bloc avant-apres plus bas, qui
        # en ont tous besoin.
        self._input_radius = get_input_radius()

        self.setObjectName("ColorPicker")
        self.setAttribute(Qt.WA_StyledBackground, True)
        self.setStyleSheet(
            f"#ColorPicker {{ background: {M['panel_bg']}; border: 1px solid {M['panel_border']}; }}"
        )
        # Largeur MINIMALE (plus fixe) : le bord droit devient une poignee
        # de redimensionnement (voir mousePressEvent/mouseMoveEvent/
        # resizeEvent plus bas) — l'utilisateur peut elargir le popup pour
        # des sliders TSL/RVB plus longs, donc un controle plus precis (voir
        # sa remarque). show_near() rappelle adjustSize() a chaque ouverture,
        # qui revient a cette largeur par defaut (pas de memorisation d'une
        # largeur choisie d'une ouverture a l'autre, hors scope de la
        # demande).
        self.setMinimumWidth(self._MIN_WIDTH)
        self._resizing = False
        self._resize_start_x = 0
        self._resize_start_width = 0
        self.setMouseTracking(True)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        # -- en-tete --
        head = _PopupHeader(self)
        head.setFixedHeight(28)
        head.setStyleSheet(f"background: {M['btn_hover']}; border-bottom: 2px solid {M['accent']};")
        head_l = QHBoxLayout(head)
        head_l.setContentsMargins(10, 0, 8, 0)
        head_l.setSpacing(8)
        tag = QLabel("COULEUR")
        tag.setFont(_qfont(9, 600, tracking=0.7))
        tag.setStyleSheet(f"color: {M['toggle_on_fg']}; background: transparent;")
        head_l.addWidget(tag)
        title_label = QLabel(title)
        title_label.setFont(_qfont(11, 600))
        title_label.setStyleSheet(f"color: {M['value_fg']}; background: transparent;")
        title_label.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
        head_l.addWidget(title_label, 1)
        pipette_btn = _PipetteButton(M["label_dim"])
        pipette_btn.setFixedSize(16, 16)
        pipette_btn.setCursor(Qt.ArrowCursor)
        pipette_btn.setFlat(True)
        pipette_btn.setToolTip("Piocher une couleur a l'ecran")
        pipette_btn.clicked.connect(lambda: self._on_pipette(_EyedropperOverlay))
        head_l.addWidget(pipette_btn)
        pipette_area_btn = _PipetteAreaButton(M["label_dim"])
        pipette_area_btn.setFixedSize(16, 16)
        pipette_area_btn.setCursor(Qt.ArrowCursor)
        pipette_area_btn.setFlat(True)
        pipette_area_btn.setToolTip("Piocher la couleur moyenne d'une zone de l'ecran")
        pipette_area_btn.clicked.connect(lambda: self._on_pipette(_AreaEyedropperOverlay))
        head_l.addWidget(pipette_area_btn)
        close_btn = _PickerCloseButton(M["label_dim"])
        close_btn.setFixedSize(16, 16)
        close_btn.setCursor(Qt.ArrowCursor)
        close_btn.setFlat(True)
        close_btn.clicked.connect(self._on_cancel)
        head_l.addWidget(close_btn)
        outer.addWidget(head)

        # -- corps --
        body = QVBoxLayout()
        body.setContentsMargins(12, 12, 12, 12)
        body.setSpacing(12)

        self.pad = _SVPad(width=276)
        self.pad.changed.connect(self._on_sv)
        body.addWidget(self.pad)

        hsl_row = QVBoxLayout()
        hsl_row.setSpacing(8)
        self._hsl_rows = []
        for i, (label, unit) in enumerate((("Teinte", "°"), ("Saturation", "%"), ("Luminosite", "%"))):
            row, slider, val_label = self._make_row(label, unit)
            slider.changed.connect(lambda f, idx=i: self._on_hsl(idx, f))
            self._hsl_rows.append((slider, val_label))
            hsl_row.addLayout(row)
        body.addLayout(hsl_row)

        body.addWidget(self._divider())

        body.addWidget(self._tag_label("COMPOSANTES RVB"))
        rgb_col = QVBoxLayout()
        rgb_col.setSpacing(8)
        self._rgb_rows = []
        for i, label in enumerate(("Rouge", "Vert", "Bleu")):
            row, slider, val_label = self._make_row(label, "")
            slider.changed.connect(lambda f, idx=i: self._on_rgb(idx, f))
            self._rgb_rows.append((slider, val_label))
            rgb_col.addLayout(row)
        body.addLayout(rgb_col)

        body.addWidget(self._divider())

        # -- avant/apres + hex --
        # Habille "comme un tableau" (voir la remarque de l'utilisateur,
        # capture annotee a l'appui) : memes primitives _TableFrame/
        # _restyle_table_row que les VRAIS tableaux de cette fenetre
        # (Polices/Entetes/Geometrie) — cadre exterieur a filet unique,
        # coins arrondis PORTES par les lignes elles-memes (ici "avant" en
        # haut, "apres" en bas, exactement comme la premiere/derniere ligne
        # d'un tableau sans entete — voir la table Entetes), et un seul
        # filet 1px entre les deux lignes (le border-top que
        # _restyle_table_row ajoute deja automatiquement pour toute ligne
        # non "first").
        hex_row = QHBoxLayout()
        hex_row.setSpacing(9)
        stacked, stacked_l = _table_frame()
        stacked.setFixedSize(58, 34)
        stacked.setRadius(self._input_radius)
        self._before_swatch = QWidget()
        self._before_swatch.setObjectName("TableRow")
        self._before_swatch.setAttribute(Qt.WA_StyledBackground, True)
        self._after_swatch = QWidget()
        self._after_swatch.setObjectName("TableRow")
        self._after_swatch.setAttribute(Qt.WA_StyledBackground, True)
        stacked_l.addWidget(self._before_swatch, 1)
        stacked_l.addWidget(self._after_swatch, 1)
        hex_row.addWidget(stacked)

        hex_box = QWidget()
        hex_box.setFixedHeight(34)
        hex_box.setObjectName("HexBox")
        hex_box.setAttribute(Qt.WA_StyledBackground, True)
        hex_box.setStyleSheet(
            f"#HexBox {{ background: {M['field_bg']}; border: 1px solid {M['field_border']}; "
            f"border-radius: {self._input_radius}px; }}"
        )
        hex_l = QHBoxLayout(hex_box)
        hex_l.setContentsMargins(9, 0, 9, 0)
        hex_l.setSpacing(9)
        hex_tag = QLabel("HEX")
        hex_tag.setFont(_qfont(9, 400, mono=True))
        hex_tag.setStyleSheet(f"color: {M['label_dim']}; background: transparent;")
        hex_l.addWidget(hex_tag)
        self.hex_edit = QLineEdit()
        self.hex_edit.setFont(_qfont(13, 400, mono=True))
        self.hex_edit.setFrame(False)
        # setFrame(False) desactive seulement le cadre NATIF Qt — le QSS
        # global de l'appli (QLineEdit { border: ... }) continue de
        # s'appliquer par-dessus tant que "border" n'est pas explicitement
        # ecrase ici, d'ou ce filet visible autour du champ hex en plus de
        # celui de HexBox qui l'entoure deja — voir la remarque de
        # l'utilisateur, capture annotee a l'appui ("pas de bordure").
        self.hex_edit.setStyleSheet(f"background: transparent; border: none; color: {M['value_fg']};")
        self.hex_edit.editingFinished.connect(self._on_hex_edited)
        hex_l.addWidget(self.hex_edit, 1)
        hex_row.addWidget(hex_box, 1)
        body.addLayout(hex_row)

        outer.addLayout(body)

        # -- bas --
        foot = QWidget()
        foot.setFixedHeight(40)
        foot.setStyleSheet(f"background: {M['toolbar_bg']}; border-top: 1px solid {M['panel_border']};")
        foot_l = QHBoxLayout(foot)
        foot_l.setContentsMargins(12, 0, 12, 0)
        foot_l.setSpacing(6)
        btn_radius = get_button_radius()
        reset_btn = _Btn("Reinitialiser", "transparent", M["btn_border"], M["reset_fg"], M["btn_bg"],
                          height=25, padding="0 10px", radius=btn_radius)
        reset_btn.clicked.connect(self._on_reset)
        foot_l.addWidget(reset_btn)
        foot_l.addStretch(1)
        cancel_btn = _Btn("Annuler", M["btn_bg"], M["btn_border"], M["btn_fg"], M["btn_hover"], height=25,
                           radius=btn_radius)
        cancel_btn.clicked.connect(self._on_cancel)
        foot_l.addWidget(cancel_btn)
        # Pas de bordure (voir la remarque de l'utilisateur, capture
        # annotee a l'appui, "supprime bordure") — fond plein uniquement,
        # comme un bouton primaire de l'appli principale.
        ok_btn = _Btn("Valider", M["accent"], "", M["accent_fg"], M["accent_hover"],
                      height=25, weight=600, padding="0 14px", radius=btn_radius)
        ok_btn.clicked.connect(self._on_commit)
        foot_l.addWidget(ok_btn)
        outer.addWidget(foot)

        self._refresh_all()

    # -- construction --

    def _tag_label(self, text: str) -> QLabel:
        label = QLabel(text)
        label.setFont(_qfont(9, 600, tracking=0.7))
        label.setStyleSheet(f"color: {M['label_dim']}; background: transparent;")
        return label

    def _divider(self) -> QWidget:
        line = QWidget()
        line.setFixedHeight(1)
        line.setStyleSheet(f"background: {M['edge_off']};")
        return line

    def _make_row(self, label: str, unit: str):
        row = QHBoxLayout()
        row.setSpacing(9)
        name = QLabel(label)
        name.setFixedWidth(70)
        name.setFont(_qfont(11, 400))
        name.setStyleSheet(f"color: {M['row_label']}; background: transparent;")
        row.addWidget(name)
        slider = _GradientSlider()
        row.addWidget(slider, 1)
        # Espace visible avant la boite de valeur (en plus des 9px de
        # row.setSpacing deja appliques) : le curseur du slider pouvait
        # quasiment toucher la boite en fin de course — voir la remarque
        # de l'utilisateur, capture annotee a l'appui ("reduire la zone de
        # saisie pour avoir un espace"). Boite retrecie (60, pas 64) pour
        # compenser et garder le popup a la meme largeur totale.
        row.addSpacing(10)
        box = QWidget()
        box.setFixedSize(60, 22)
        box.setObjectName("ValBox")
        box.setAttribute(Qt.WA_StyledBackground, True)
        # C'est une zone de saisie comme les autres : meme rayon que hex_box
        # (self._input_radius) — voir la remarque de l'utilisateur, capture
        # annotee a l'appui ("zone de saisie donc arrondie les angles").
        box.setStyleSheet(
            f"#ValBox {{ background: {M['field_bg']}; border: 1px solid {M['field_border']}; "
            f"border-radius: {self._input_radius}px; }}"
        )
        box_l = QHBoxLayout(box)
        box_l.setContentsMargins(9, 0, 9, 0)
        box_l.setSpacing(2)
        val_label = QLabel("0")
        val_label.setFont(_qfont(11, 400, mono=True))
        val_label.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        val_label.setStyleSheet(f"color: {M['value_text']}; background: transparent;")
        box_l.addWidget(val_label, 1)
        if unit:
            unit_label = QLabel(unit)
            unit_label.setFont(_qfont(9, 400, mono=True))
            unit_label.setStyleSheet(f"color: {M['unit']}; background: transparent;")
            box_l.addWidget(unit_label)
        row.addWidget(box)
        return row, slider, val_label

    # -- etat --

    def _current_hex(self) -> str:
        return _rgb_to_hex(_hsv_to_rgb(self._h, self._s, self._v))

    def _refresh_all(self):
        rgb = _hsv_to_rgb(self._h, self._s, self._v)
        hexval = _rgb_to_hex(rgb)
        self.pad.setHue(self._h)
        self.pad.setSV(self._s, self._v)

        hue_slider, hue_val = self._hsl_rows[0]
        hue_slider.setStops([
            (0.0, "#ff0000"), (1 / 6, "#ffff00"), (2 / 6, "#00ff00"),
            (3 / 6, "#00ffff"), (4 / 6, "#0000ff"), (5 / 6, "#ff00ff"), (1.0, "#ff0000"),
        ])
        hue_slider.setFraction(self._h / 360)
        hue_val.setText(str(round(self._h)))

        sat_slider, sat_val = self._hsl_rows[1]
        sat_slider.setStops([
            (0.0, _rgb_to_hex(_hsv_to_rgb(self._h, 0.0, self._v))),
            (1.0, _rgb_to_hex(_hsv_to_rgb(self._h, 1.0, self._v))),
        ])
        sat_slider.setFraction(self._s)
        sat_val.setText(str(round(self._s * 100)))

        lum_slider, lum_val = self._hsl_rows[2]
        lum_slider.setStops([(0.0, "#000000"), (1.0, _rgb_to_hex(_hsv_to_rgb(self._h, self._s, 1.0)))])
        lum_slider.setFraction(self._v)
        lum_val.setText(str(round(self._v * 100)))

        for i, (slider, val_label) in enumerate(self._rgb_rows):
            lo, hi = list(rgb), list(rgb)
            lo[i], hi[i] = 0, 255
            slider.setStops([(0.0, _rgb_to_hex(lo)), (1.0, _rgb_to_hex(hi))])
            slider.setFraction(rgb[i] / 255)
            val_label.setText(str(rgb[i]))

        # Habille comme les 2 lignes d'un vrai tableau sans entete de cette
        # fenetre (voir _restyle_table_row/la table Entetes, meme
        # technique) : "avant" = premiere ligne (porte le rayon HAUT du
        # cadre), "apres" = derniere ligne (porte le rayon BAS, et le seul
        # filet horizontal separant les deux, ajoute automatiquement par
        # _restyle_table_row pour toute ligne non "first") — voir la
        # remarque de l'utilisateur, capture annotee a l'appui ("comme un
        # tableau").
        _restyle_table_row(self._before_swatch, self._before, first=True, top_radius=self._input_radius)
        _restyle_table_row(self._after_swatch, hexval, first=False, bottom_radius=self._input_radius)
        if self.hex_edit.text().lower() != hexval:
            cursor = self.hex_edit.cursorPosition()
            self.hex_edit.setText(hexval)
            self.hex_edit.setCursorPosition(min(cursor, len(hexval)))

        self.colorChanged.emit(hexval)

    # -- interactions --

    def _on_sv(self, s: float, v: float):
        self._s, self._v = s, v
        self._refresh_all()

    def _on_hsl(self, idx: int, frac: float):
        if idx == 0:
            self._h = frac * 360
        elif idx == 1:
            self._s = frac
        else:
            self._v = frac
        self._refresh_all()

    def _on_rgb(self, idx: int, frac: float):
        rgb = list(_hsv_to_rgb(self._h, self._s, self._v))
        rgb[idx] = round(frac * 255)
        self._h, self._s, self._v = _rgb_to_hsv(*rgb)
        self._refresh_all()

    def _on_hex_edited(self):
        text = self.hex_edit.text().strip()
        if not text.startswith("#"):
            text = "#" + text
        if len(text) == 7:
            try:
                int(text[1:], 16)
            except ValueError:
                pass
            else:
                self._h, self._s, self._v = _hex_to_hsv(text)
        self._refresh_all()

    def _on_reset(self):
        self._h, self._s, self._v = _hex_to_hsv(self._before)
        self._refresh_all()

    def _on_pipette(self, overlay_cls):
        # Le popup reste ouvert mais s'efface le temps de la capture, pour
        # ne pas se piocher lui-meme comme couleur. _pipette_active evite
        # que ce hide() soit interprete comme une validation par
        # hideEvent (voir sa remarque : hide() = clic dehors = commit).
        self._pipette_active = True
        self.hide()
        # Ce popup est une fenetre Qt.Popup : elle detient un grab souris
        # implicite tant qu'elle est visible. hide() le relache, mais Qt
        # ne finalise cette liberation qu'au retour dans la boucle
        # d'evenements — creer/afficher l'overlay de capture (qui doit
        # lui-meme recevoir les clics) DANS ce meme cycle d'evenement (le
        # slot du clic sur le bouton pipette) le fait echouer silencieuse-
        # ment : l'overlay s'affiche mais ne recoit rien. D'ou ce
        # singleShot(0, ...), qui reporte sa creation au prochain passage
        # de la boucle, une fois le grab du popup vraiment libere.
        QTimer.singleShot(0, lambda: self._launch_pipette(overlay_cls))

    def _launch_pipette(self, overlay_cls):
        overlay = overlay_cls()
        self._active_overlay = overlay   # garde une reference forte (sinon GC Python possible)
        overlay.picked.connect(self._on_pipette_picked)
        overlay.cancelled.connect(self._on_pipette_cancelled)
        overlay.destroyed.connect(lambda *_: self._show_after_pipette())
        overlay.show()
        overlay.raise_()
        overlay.activateWindow()
        overlay.setFocus(Qt.ActiveWindowFocusReason)

    def _show_after_pipette(self):
        self._active_overlay = None
        self._pipette_active = False
        if not self._resolved:
            self.show()

    def _on_pipette_picked(self, hexval: str):
        self._h, self._s, self._v = _hex_to_hsv(hexval)
        self._refresh_all()

    def _on_pipette_cancelled(self):
        pass

    def _on_cancel(self):
        if self._resolved:
            return
        self._resolved = True
        self.cancelled.emit()
        self.close()

    def _on_commit(self):
        if self._resolved:
            return
        self._resolved = True
        hexval = self._current_hex()
        self.committed.emit(hexval)
        self.close()

    def hideEvent(self, event):
        # Un clic EN DEHORS du popup ferme un widget Qt.Popup directement
        # via hide() (pas close()/closeEvent — verifie sur ce Qt : le
        # gestionnaire de popups de Qt appelle QWidget::hide() en
        # interne), d'ou hideEvent plutot que closeEvent ici — ce cas vaut
        # validation de la couleur affichee, plus intuitif qu'une
        # annulation silencieuse pendant qu'on ajustait un slider (voir la
        # remarque de tete de classe). _resolved evite un double signal
        # quand Valider/Annuler vient d'etre clique juste avant (close()
        # declenche aussi hide()) — et gere donc les DEUX chemins de
        # fermeture avec cette seule methode.
        if not self._resolved and not getattr(self, "_pipette_active", False):
            self._resolved = True
            hexval = self._current_hex()
            self.committed.emit(hexval)
        super().hideEvent(event)

    # -- redimensionnement (bord droit) --

    def _on_resize_edge(self, pos) -> bool:
        return self.width() - self._RESIZE_MARGIN <= pos.x() <= self.width()

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton and self._on_resize_edge(event.position().toPoint()):
            self._resizing = True
            self._resize_start_x = event.globalPosition().toPoint().x()
            self._resize_start_width = self.width()
            event.accept()
            return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        if self._resizing:
            delta = event.globalPosition().toPoint().x() - self._resize_start_x
            new_width = max(self._MIN_WIDTH, min(self._MAX_WIDTH, self._resize_start_width + delta))
            self.resize(new_width, self.height())
            event.accept()
            return
        cursor = Qt.SizeHorCursor if self._on_resize_edge(event.position().toPoint()) else Qt.ArrowCursor
        self.setCursor(cursor)
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        if self._resizing:
            self._resizing = False
            event.accept()
            return
        super().mouseReleaseEvent(event)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        # Le carre SV et les sliders TSL/RVB (voir _make_row, stretch=1)
        # suivent la nouvelle largeur ; la hauteur du carre reste fixe (pas
        # demandee par l'utilisateur, seule la precision HORIZONTALE des
        # sliders est en jeu).
        if hasattr(self, "pad"):
            self.pad.setFixedWidth(max(1, self.width() - 24))

    def show_near(self, widget: QWidget):
        self.adjustSize()
        pos = widget.mapToGlobal(QPoint(0, widget.height() + 4))
        screen = QApplication.screenAt(widget.mapToGlobal(QPoint(0, 0))) or QApplication.primaryScreen()
        if screen is not None:
            avail = screen.availableGeometry()
            pos.setX(max(avail.left(), min(pos.x(), avail.right() - self.width())))
            pos.setY(max(avail.top(), min(pos.y(), avail.bottom() - self.height())))
        self.move(pos)
        self.show()
        # Sans ca, sur Windows 11 le compositeur DWM impose son propre
        # arrondi par defaut a CETTE fenetre (frameless de premier niveau,
        # voir Qt.Popup ci-dessus) par-dessus le perimetre bien carre (0px)
        # deja peint cote QSS — et pas force ment de facon uniforme sur les
        # 4 coins (constate : parfois un seul coin visiblement arrondi,
        # voir la remarque de l'utilisateur, capture annotee a l'appui,
        # "pourquoi souvent tu mets des bordures juste sur 1 coin"). Meme
        # correctif que SettingsWindow._apply_panel_radius : redemander
        # explicitement DONOTROUND cote DWM (winId() n'existe qu'apres
        # show(), d'ou l'appel ICI et pas dans __init__).
        apply_dwm_frame(self, 0, M["panel_border"])


class _ColorField(QWidget):
    """Pastille cliquable (ouvre _ColorPickerPopup) + boite hexadecimale."""

    changed = Signal(str)

    def __init__(self, value: str, swatch_size: int = 24, title: str = "Couleur", parent=None):
        super().__init__(parent)
        self._value = value
        self._title = title
        self._before_pick = value
        self._popup: _ColorPickerPopup | None = None
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(10)
        self.swatch = QPushButton()
        self.swatch.setFixedSize(swatch_size, swatch_size)
        self.swatch.setCursor(Qt.ArrowCursor)
        self.swatch.setFocusPolicy(Qt.NoFocus)
        self.swatch.clicked.connect(self._pick)
        layout.addWidget(self.swatch)
        self._refresh()

    def _refresh(self):
        # border-radius FIXE (2px, jamais suivi le slider Geometrie >
        # Tableaux/Zones de saisie — voir la remarque de l'utilisateur,
        # capture a l'appui) : juste un adoucissement discret du carre,
        # pas un reglage.
        self.swatch.setStyleSheet(
            "QPushButton { background: " + self._value + "; border: 1px solid " + M["swatch_border"]
            + "; border-radius: 2px; }"
            "QPushButton:hover { border-color: " + M["swatch_border_hover"] + "; }"
        )

    def _pick(self):
        self._before_pick = self._value
        popup = _ColorPickerPopup(self._value, self._title, self)
        self._popup = popup
        # colorChanged (glisser un slider/le carre) ET committed (Valider,
        # ou un clic dehors — voir _ColorPickerPopup.closeEvent) suivent
        # le MEME chemin : appliquer tout de suite, en direct sur la
        # fenetre principale (voir SettingsWindow._on_colors_changed, qui
        # lit self._value via value() a chaque signal changed). cancelled
        # (Annuler/croix) restaure la valeur de depart par le meme chemin.
        popup.colorChanged.connect(self._apply_live)
        popup.committed.connect(self._apply_live)
        popup.cancelled.connect(lambda: self._apply_live(self._before_pick))
        popup.show_near(self.swatch)

    def _apply_live(self, hexval: str):
        self._value = hexval
        self._refresh()
        self.changed.emit(self._value)

    def value(self) -> str:
        return self._value

    def setValue(self, value: str):
        self._value = value
        self._refresh()


class _CheckSquare(QWidget):
    """Petite case carree — purement decorative ici (voir _EdgeCheckItem :
    le clic est capte par la ligne entiere, pas par la case elle-meme)."""

    def __init__(self, checked: bool = False, parent=None):
        super().__init__(parent)
        self._checked = checked
        self.setFixedSize(14, 14)
        self.setAttribute(Qt.WA_TransparentForMouseEvents, True)

    def isChecked(self) -> bool:
        return self._checked

    def setChecked(self, checked: bool):
        if checked != self._checked:
            self._checked = checked
            self.update()

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing, False)
        bg = QColor(M["accent"] if self._checked else M["field_bg"])
        bd = QColor(M["accent_border"] if self._checked else M["field_border"])
        p.setPen(bd)
        p.setBrush(bg)
        p.drawRect(0, 0, 13, 13)
        if self._checked:
            p.setPen(QColor(M["bold_mark_fg"]))
            p.setFont(_qfont(9, 700, mono=True))
            p.drawText(0, 0, 13, 13, Qt.AlignCenter, "\u2713")
        p.end()


# ==========================================================================
# Blocs de mise en page (sections / lignes), fideles a la maquette.
# ==========================================================================

def _label_block(text: str, note: str = "") -> QWidget:
    box = QWidget()
    # Meme correctif que _table_cell (voir son commentaire) : ce bloc est
    # aussi pose directement dans une ligne de tableau "ferme" (voir la
    # table Entetes, SettingsWindow._section_headers) et souffrait du meme
    # masquage de la couleur "Fond de tableau" ; sans effet visible dans son
    # AUTRE usage (_Row, hors tableau), ou le fond herite etait deja le bon.
    box.setStyleSheet("background: transparent;")
    box.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
    layout = QVBoxLayout(box)
    layout.setContentsMargins(0, 6, 0, 6)
    layout.setSpacing(1)
    name = QLabel(text)
    name.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
    name.setFont(_qfont(12, 400))
    name.setStyleSheet(f"color: {M['row_label']}; background: transparent;")
    layout.addWidget(name)
    if note:
        sub = QLabel(note)
        sub.setWordWrap(True)
        sub.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
        sub.setFont(_qfont(10, 400))
        sub.setStyleSheet(f"color: {M['row_note']}; background: transparent;")
        layout.addWidget(sub)
    return box


def _label_block_natural_width(label_block: QWidget) -> int:
    """Largeur naturelle (texte, pas la boite) d'un _label_block — utilise
    par _FlatColumnResizer (voir _build_flat_table/SettingsWindow.
    _section_headers) pour choisir une largeur de depart qui ne change RIEN
    a l'apparence par defaut. PAS label_block.sizeHint().width() : la boite
    elle-meme a un SizePolicy Ignored en largeur (voir _label_block), ce
    qui fait remonter une largeur de 0 quel que soit son contenu — le
    QLabel interieur, lui, garde son sizeHint() reel malgre la meme
    policy (Ignored ne change que la facon dont le layout PARENT traite ce
    sizeHint, jamais la valeur qu'il retourne)."""
    label = label_block.findChild(QLabel)
    return label.sizeHint().width() if label is not None else 0


def _section_preview_wrap(widget: QWidget) -> QWidget:
    """Centre horizontalement `widget` (aucune largeur imposee, garde sa
    taille naturelle) au-dessus du tableau de reglages d'une section — voir
    Colonnes/Tableaux/Toggles/Sliders (SettingsWindow._section_headers/
    _section_tables/_section_toggles/_section_slider), qui l'utilisent
    chacun pour leur apercu de l'element concerne par la section (voir la
    remarque de l'utilisateur, "un apercu de l'element concerne par la
    section, juste avant le tableau des parametres... centre en
    horizontal")."""
    wrap = QWidget()
    wrap.setStyleSheet("background: transparent;")
    layout = QHBoxLayout(wrap)
    layout.setContentsMargins(0, 0, 0, 18)
    layout.addStretch(1)
    layout.addWidget(widget)
    layout.addStretch(1)
    return wrap


class _Row(QWidget):
    """Ligne de reglage : libelle(+note) a gauche, controle a droite. Pas de
    filet de separation entre les lignes d'un groupe (juge parasite a
    l'usage — voir la remarque de l'utilisateur, capture a l'appui)."""

    def __init__(self, label: str, control: QWidget, note: str = "", parent=None):
        super().__init__(parent)
        self.setAttribute(Qt.WA_StyledBackground, True)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(14)
        layout.setAlignment(Qt.AlignVCenter)
        layout.addWidget(_label_block(label, note), 1)
        control.setParent(self)
        layout.addWidget(control, 0, Qt.AlignVCenter)
        self.setMinimumHeight(32)


_SVG_PIXMAP_CACHE: dict[tuple[str, int, str], QPixmap] = {}


def _tinted_svg_pixmap(name: str, size: int, color: str) -> QPixmap:
    """Charge icons/{name}.svg (trace uni, sans fill) et le recolore en
    `color` — les fichiers sources n'ont pas de couleur propre (destines a
    heriter de currentColor), donc rendus ici comme un simple masque alpha
    (le SVG en noir) puis remplis via CompositionMode_SourceIn. Rendu a 4x
    la taille cible puis mis a l'echelle (devicePixelRatio) pour rester net
    sur un ecran HiDPI. Mis en cache par (nom, taille, couleur) : la couleur
    ne change qu'au fil d'un theme/preview, pas a chaque repaint."""
    key = (name, size, color)
    pix = _SVG_PIXMAP_CACHE.get(key)
    if pix is not None:
        return pix
    renderer = QSvgRenderer(str(_ICONS_DIR / f"{name}.svg"))
    scale = 4
    pix = QPixmap(size * scale, size * scale)
    pix.fill(Qt.transparent)
    p = QPainter(pix)
    p.setRenderHint(QPainter.Antialiasing, True)
    renderer.render(p)
    p.setCompositionMode(QPainter.CompositionMode_SourceIn)
    p.fillRect(pix.rect(), QColor(color))
    p.end()
    pix.setDevicePixelRatio(scale)
    _SVG_PIXMAP_CACHE[key] = pix
    return pix


class _Chevron(QWidget):
    """Chevron SVG (icons/chevron-bas.svg, icons/chevron-droite.svg — voir
    _tinted_svg_pixmap) — remplace l'ancien chevron peint a la main (2
    traits) par les icones perso de l'utilisateur (F:\\SYNC\\Sync\\IMAGES\\
    ico\\SVG, "chevron bas"/"chevron droite"), recolorees en direct pour
    suivre M['section_title']. Pointe vers le bas deplie, vers la droite
    replie — voir la remarque de l'utilisateur, capture a l'appui du style
    recherche."""

    def __init__(self, size: int = 16, parent=None):
        super().__init__(parent)
        self._collapsed = False
        self.setFixedSize(size, size)

    def setCollapsed(self, collapsed: bool):
        if collapsed != self._collapsed:
            self._collapsed = collapsed
            self.update()

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing, True)
        # SmoothPixmapTransform : c'est CE hint (pas Antialiasing, qui ne
        # joue que sur le trace vectoriel) qui commande le lissage quand
        # QPainter reduit un pixmap (ici le rendu 4x/devicePixelRatio vers
        # la taille reelle du chevron, voir _tinted_svg_pixmap) — sans lui
        # Qt reechantillonne au plus proche voisin, d'ou le rendu "pas
        # terrible" (crenele) signale par l'utilisateur.
        p.setRenderHint(QPainter.SmoothPixmapTransform, True)
        name = "chevron-droite" if self._collapsed else "chevron-bas"
        pix = _tinted_svg_pixmap(name, self.width(), M["section_title"])
        p.drawPixmap(0, 0, pix)
        p.end()


# Espacement entre deux sections (voir SettingsWindow._build_content, qui
# pose un spaceur dedie apres chaque _Section plutot qu'un
# QVBoxLayout.setSpacing uniforme) : plein quand la section au-dessus est
# deployee, quasi nul quand elle est repliee (voir _Section.collapsedChanged
# — son corps est deja masque, rien ne justifie plus un grand espacement)
# — pas 0 pile : une marge minimale separe visuellement deux bandeaux-titre
# consecutifs, sans quoi ils se touchent litteralement.
_SECTION_GAP_EXPANDED = 34
_SECTION_GAP_COLLAPSED = 2


class _SectionHeader(QWidget):
    """Bandeau titre d'une _Section — toute sa largeur est cliquable pour
    replier/deplier (voir _Section), pas seulement le chevron (memes raisons
    que _EdgeCheckItem/_PresetListRow : une cible de clic plus large que le
    seul glyphe est plus confortable)."""

    clicked = Signal()

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            self.clicked.emit()
        super().mousePressEvent(event)


def _activate_layout_tree(widget: QWidget):
    """Force un recalcul COMPLET et immediat (invalidate + activate) de
    TOUS les layouts sous `widget`, feuilles d'abord (recursion en POST-
    ORDRE) — necessaire pour lire un sizeHint() fiable juste apres avoir
    replie/deplie un sous-groupe imbrique (voir _Section.refresh_min_
    height/_SubSection, la remarque de l'utilisateur, "il y a des bugs
    importants quand on plie/deplie les sous sections").

    QWidget.updateGeometry() (voir _SubSection.set_collapsed) n'invalide
    QUE le layout du parent DIRECT — au-dela d'1 niveau de QWidget nu
    imbrique (tres frequent ici : chaque sous-groupe vit dans sa propre
    boite intermediaire, voir Colonnes/Entetes/Toggles > Cadre/Coche...),
    Qt ne fait PAS remonter cette invalidation plus loin de facon
    SYNCHRONE — seulement plus tard, via la file d'evenements
    (QEvent.LayoutRequest, traitee au prochain passage de la boucle
    d'evenements) : un sizeHint() lu tout de suite (avant ce passage,
    exactement le cas de refresh_min_height/refresh_layout, appeles EN
    REACTION au clic) restait donc perime a un ou plusieurs niveaux
    d'ecart. Ici, on force nous-memes ce recalcul, tout de suite, sur
    l'arbre ENTIER (peu importe sa profondeur d'imbrication)."""
    for child in widget.children():
        if isinstance(child, QWidget):
            _activate_layout_tree(child)
    lay = widget.layout()
    if lay is not None:
        lay.invalidate()
        lay.activate()


class _Section(QWidget):
    """Section de la page : titre bleu petites capitales + note optionnelle,
    PAS de filet horizontal (la maquette n'en a pas ici, contrairement a
    l'ancien _Group) — juste un espacement genereux (voir SettingsWindow.
    _build_content, un spaceur dedie entre chaque section, pas
    QVBoxLayout.setSpacing). Repliable (voir toggle) : un chevron devant le
    titre, tout le bandeau cliquable (voir _SectionHeader) — replier masque
    juste le corps (self._body), le titre restant toujours visible — voir
    la remarque de l'utilisateur. collapsedChanged permet a l'appelant de
    reduire a son tour l'espace APRES la section (voir _build_content) :
    repliee, elle n'a plus besoin d'un espacement aussi genereux avec la
    section suivante."""

    collapsedChanged = Signal(bool)

    def __init__(self, title: str, note: str = "", parent=None):
        super().__init__(parent)
        self._collapsed = False
        self._layout = QVBoxLayout(self)
        self._layout.setContentsMargins(0, 0, 0, 0)
        self._layout.setSpacing(0)

        head = self.head = _SectionHeader()
        head.setCursor(Qt.PointingHandCursor)
        head_l = QHBoxLayout(head)
        self._head_layout = head_l
        # Marge du bas : espace le titre du corps quand il est visible —
        # inutile repliee (le corps est masque, voir set_collapsed, qui la
        # ramene alors a 0 pour ne rien laisser trainer sous le titre en
        # plus du spaceur inter-sections, voir SettingsWindow._build_content).
        head_l.setContentsMargins(0, 0, 0, 10)
        head_l.setSpacing(10)
        # Chevron peint (voir _Chevron) et titre agrandis, police de texte
        # principal (Segoe UI, sans le petites-capitales/tracking d'origine,
        # jugee trop discrete une fois le titre devenu cliquable — voir la
        # remarque de l'utilisateur, capture a l'appui).
        self._chevron = _Chevron(size=16)
        head_l.addWidget(self._chevron)
        name = QLabel(title.upper())
        name.setFont(_qfont(14, 600))
        name.setStyleSheet(f"color: {M['section_title']}; background: transparent;")
        head_l.addWidget(name)
        if note:
            note_label = QLabel(note)
            note_label.setFont(_qfont(10, 400))
            note_label.setStyleSheet(f"color: {M['group_note']}; background: transparent;")
            head_l.addWidget(note_label)
        head_l.addStretch(1)
        head.clicked.connect(self.toggle)
        self._layout.addWidget(head)

        self._body = QWidget()
        self._body_layout = QVBoxLayout(self._body)
        self._body_layout.setContentsMargins(0, 0, 0, 0)
        self._body_layout.setSpacing(0)
        self._layout.addWidget(self._body)

        self._refresh_chevron()

    def add(self, widget: QWidget):
        self._body_layout.addWidget(widget)

    def toggle(self):
        self.set_collapsed(not self._collapsed)

    def set_collapsed(self, collapsed: bool):
        if self._collapsed == collapsed:
            return
        self._collapsed = collapsed
        self._body.setVisible(not collapsed)
        self._head_layout.setContentsMargins(0, 0, 0, 0 if collapsed else 10)
        # activate() (pas juste invalidate(), ni compter sur le prochain
        # passage de l'event loop) : FORCE ce layout precis, dont on vient
        # de changer les marges, a se recalculer TOUT DE SUITE. Sans ca, le
        # sizeHint() lu juste en dessous restait construit avec l'ANCIENNE
        # hauteur du bandeau (marge du bas encore a 0 au lieu de 10) — un
        # deficit de quelques pixels, constant et reproductible, meme si
        # head.sizeHint() interroge DIRECTEMENT rendait deja la bonne
        # valeur : c'est la mise en cache du PARENT (self._layout, qui
        # empile bandeau+corps) qui ne se met a jour QUE sur un vrai
        # QResizeEvent ou un activate() explicite de CE layout interne —
        # updateGeometry()/invalidate() sur self._layout, essayes ici en
        # premier, ne suffisaient pas non plus. Voir la remarque de
        # l'utilisateur, capture annotee a l'appui (bord bas des pastilles
        # de Couleurs recouvert par le filet de la ligne suivante).
        # _activate_layout_tree (pas juste _head_layout) : un _SubSection
        # imbrique dans le corps peut avoir change de taille PENDANT que
        # cette section etait repliee (invisible, donc jamais relayoutee
        # entre-temps) — voir refresh_min_height, meme raison.
        _activate_layout_tree(self)
        self._refresh_chevron()
        # setMinimumHeight explicite a la taille naturelle : sans lui, le
        # layout PARENT (SettingsWindow._build_content, qui empile toutes
        # les sections) redistribue l'espace total disponible en gardant un
        # minimumSizeHint() DEVENU INCOHERENT avec le sizeHint() reel de
        # cette section une fois son corps deplie — observe avec les 2 gros
        # tableaux Cadre/Coche de Toggle 1/Toggle 2 (voir Toggles > Style,
        # capture a l'appui) : la section restait ecrasee sous sa propre
        # taille naturelle malgre une hauteur totale disponible largement
        # suffisante (minimumSizeHint() de Qt, ici, ne recalcule pas le
        # necessaire pour un contenu qui vient d'apparaitre — juste
        # updateGeometry()/invalidate() ne suffit pas a corriger ca).
        # Relachee (0) repliee : la section retrouve alors sa taille
        # naturelle, tres compacte (juste le bandeau titre).
        self.setMinimumHeight(self.sizeHint().height() if not collapsed else 0)
        self.updateGeometry()
        self.collapsedChanged.emit(collapsed)

    def is_collapsed(self) -> bool:
        return self._collapsed

    def refresh_min_height(self):
        """Meme recalcul que la fin de set_collapsed (memes 2 lignes,
        memes raisons — voir ses commentaires), mais appelable a N'IMPORTE
        QUEL moment, pas seulement au repliage/depliage : necessaire quand
        le CONTENU d'une section DEJA depliee change de taille en direct
        (voir SettingsWindow._apply_cell_padding, Tableaux > Padding des
        cellules) — sans reappeler ceci ensuite, le plancher restait celui
        capture au dernier depliage, desormais trop petit pour le nouveau
        contenu : la section (et tout ce qui suit dans _build_content)
        gardait l'ancienne hauteur, plus courte que le tableau agrandi —
        voir la remarque de l'utilisateur, "je veux que la position du
        tableau ne change pas du tout en haut a gauche, mais que le
        tableau se redimensionne automatiquement vers le bas"."""
        if self._collapsed:
            return
        # _activate_layout_tree (pas juste les 2 layouts directs) : un
        # _SubSection imbrique dans le corps (voir Colonnes/Entetes/Toggles
        # > Cadre/Coche...) peut se replier/deplier PLUSIEURS niveaux plus
        # bas — voir sa remarque, meme raison.
        _activate_layout_tree(self)
        self.setMinimumHeight(self.sizeHint().height())
        self.updateGeometry()

    def _refresh_chevron(self):
        # Chevron bas = deplie, chevron droit = replie — meme convention que
        # les menus deroulants (▾) de cette fenetre (voir _SelectField).
        self._chevron.setCollapsed(self._collapsed)


class _SubSection(QWidget):
    """Sous-groupe repliable A L'INTERIEUR d'une _Section (voir SettingsWindow.
    _sub_heading, dont ceci prend desormais la place partout ou un sous-titre
    precedait un SEUL bloc de contenu — Colonnes/Entetes/Texte/Selection,
    Cadre/Coche, Rail/Selecteur, Toggle 1/Toggle 2) — meme mecanique que
    _Section (chevron + bandeau entierement cliquable, collapsedChanged) mais
    habillage DISCRET (petites capitales, pas de gros titre) pour rester au
    niveau visuel d'un _sub_heading plutot que rivaliser avec le titre de
    section — voir la remarque de l'utilisateur, "fait en sorte que les sous
    sections soient collapsable aussi". `indent` : meme retrait que _sub_
    heading pour les sous-groupes de 2e niveau (voir SettingsWindow.
    _build_collapsible_group)."""

    collapsedChanged = Signal(bool)

    def __init__(self, title: str, indent: bool = False, parent=None):
        super().__init__(parent)
        self._collapsed = False
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        self._indent = indent
        head = self.head = _SectionHeader()
        head.setCursor(Qt.PointingHandCursor)
        head_l = QHBoxLayout(head)
        self._head_layout = head_l
        # MEME principe que _Section.__init__ (voir son commentaire) : PAS
        # de marge haute (0), seule la marge BASSE espace le bandeau de son
        # corps quand il est visible — reduite a 0 repliee (voir
        # set_collapsed) — toute la "respiration" entre 2 sous-groupes vient
        # du spaceur DEDIE (_SUBSECTION_GAP_*/_stack_subsections), pas d'une
        # marge fixe sur le bandeau lui-meme — voir la remarque de
        # l'utilisateur, "base toi sur ce que tu avais fait sur les
        # sections" (une marge haute fixe de 14px restait telle quelle meme
        # repliee, contrairement a _Section).
        head_l.setContentsMargins(20 if indent else 0, 0, 0, 6)
        head_l.setSpacing(6)
        self._chevron = _Chevron(size=11)
        head_l.addWidget(self._chevron)
        label = QLabel(title.upper())
        label.setFont(_qfont(10, 600, tracking=0.6))
        label.setStyleSheet(
            f"color: {M['group_title'] if not indent else M['group_note']}; background: transparent;"
        )
        head_l.addWidget(label)
        head_l.addStretch(1)
        head.clicked.connect(self.toggle)
        layout.addWidget(head)

        self._body = QWidget()
        self._body_layout = QVBoxLayout(self._body)
        self._body_layout.setContentsMargins(0, 0, 0, 0)
        self._body_layout.setSpacing(0)
        layout.addWidget(self._body)
        self._refresh_chevron()

    def add(self, widget: QWidget):
        self._body_layout.addWidget(widget)
        # Verrouille tout de suite le plancher de hauteur de CE sous-groupe
        # sur son contenu REEL (voir refresh_layout, meme necessite que
        # _Section) -- systematique, sans rien demander a l'appelant : la
        # toute PREMIERE cause de l'ecrasement observe etait justement un
        # sous-groupe JAMAIS replie/deplie (donc jamais passe par
        # set_collapsed) qui n'avait encore AUCUN plancher propre -- voir la
        # remarque de l'utilisateur, "corrige l'ecrasement du tableau ...
        # que tu le prennes systematiquement en compte pour tous les
        # tableaux".
        self.refresh_layout()

    def toggle(self):
        self.set_collapsed(not self._collapsed)

    def set_collapsed(self, collapsed: bool):
        if self._collapsed == collapsed:
            return
        self._collapsed = collapsed
        self._body.setVisible(not collapsed)
        self._head_layout.setContentsMargins(20 if self._indent else 0, 0, 0, 0 if collapsed else 6)
        self._refresh_chevron()
        self.refresh_layout()
        self.collapsedChanged.emit(collapsed)

    def refresh_layout(self):
        """Force CE sous-groupe (et tout ce qu'il contient, meme imbrique
        plus bas) a recalculer sa taille tout de suite — voir
        _activate_layout_tree/_Section.refresh_min_height, meme necessite/
        memes raisons (voir la remarque de l'utilisateur, capture a
        l'appui, "il y a des bugs importants quand on plie/deplie les
        sous sections").

        setMinimumHeight explicite (voir _Section.set_collapsed, MEME
        necessite) : sans lui, ce sous-groupe n'a AUCUN plancher propre —
        des que l'espace total disponible manque un peu (fenetre pas assez
        haute, ou juste apres un depli qui agrandit soudain le contenu),
        Qt le COMPRESSE en dessous de son besoin reel plutot que de
        respecter le minimumHeight de CHAQUE ligne de tableau a l'interieur
        (voir _lock_min_height) — un tableau "ecrase" (texte/sliders
        chevauches) meme si chaque ligne a pourtant son propre plancher —
        voir la remarque de l'utilisateur, capture a l'appui, "corrige
        l'ecrasement du tableau ... que tu le prennes systematiquement en
        compte pour tous les tableaux"."""
        _activate_layout_tree(self)
        self.setMinimumHeight(self.sizeHint().height() if not self._collapsed else 0)
        self.updateGeometry()

    def is_collapsed(self) -> bool:
        return self._collapsed

    def _refresh_chevron(self):
        self._chevron.setCollapsed(self._collapsed)


# Espacement entre 2 _SubSection empilees — MEME principe que _SECTION_GAP_*/
# SettingsWindow._build_content (un spaceur dedie, plein entre 2 sous-groupes
# DEPLIES, quasi nul des que celui du dessus est REPLIE) mais des valeurs
# plus discretes : un sous-groupe reste un repere de second niveau, pas une
# section a part entiere — voir _stack_subsections/la remarque de
# l'utilisateur, "je veux que tu normalises l'espacement entre les sections
# ... comme tu l'avais fait pour les sections".
_SUBSECTION_GAP_EXPANDED = 8
_SUBSECTION_GAP_COLLAPSED = 0


def _stack_subsections(layout: QVBoxLayout, subsections: list[_SubSection]):
    """Empile plusieurs _SubSection dans `layout` (deja cree, vide) avec un
    espacement ADAPTATIF entre chaque paire — voir _SUBSECTION_GAP_*
    ci-dessus. Ne remplace PAS le cablage vers un eventuel _Section.
    refresh_min_height/_activate_layout_tree englobant (voir les
    appelants) : ce spaceur ne fait QUE gerer l'espace VISUEL entre les
    sous-groupes, independamment du recalcul de hauteur globale.

    setSpacing(0) — PAS laisse a la valeur par defaut du style (~6px,
    QStyle::PM_LayoutVerticalSpacing) : sans ca, cette valeur s'ajoutait
    EN PLUS du spaceur dedie de CHAQUE cote (avant ET apres), doublant
    l'ecart REPLIE malgre un spaceur a 0 — voir la remarque de
    l'utilisateur, "base toi sur ce que tu avais fait sur les sections"
    (_Section/SettingsWindow._build_content n'ont ce probleme que parce
    que leur layout EXTERIEUR a deja son propre setSpacing(0) explicite)."""
    layout.setSpacing(0)
    for i, sub in enumerate(subsections):
        # Repliee a l'ouverture (voir la remarque de l'utilisateur, "je
        # veux que toutes les sections (y compris sous sections) soient
        # repliees a l'ouverture de la fenetre de settings").
        sub.set_collapsed(True)
        layout.addWidget(sub)
        if i == len(subsections) - 1:
            continue
        spacer = QWidget()
        spacer.setStyleSheet("background: transparent;")
        spacer.setFixedHeight(_SUBSECTION_GAP_COLLAPSED if sub.is_collapsed() else _SUBSECTION_GAP_EXPANDED)
        sub.collapsedChanged.connect(
            lambda collapsed, s=spacer: s.setFixedHeight(
                _SUBSECTION_GAP_COLLAPSED if collapsed else _SUBSECTION_GAP_EXPANDED
            )
        )
        layout.addWidget(spacer)
    _make_accordion(subsections)


def _make_accordion(items: list):
    """Regroupe plusieurs _Section/_SubSection SOEURS en accordeon : en
    deplier une replie automatiquement les AUTRES du groupe — sauf en
    maintenant CTRL enfonce au clic (voir la remarque de l'utilisateur,
    "quand une section est depliee, et qu'on en deplie une seconde, la
    premiere se replie automatiquement sauf si on appuie sur la touche
    CTRL en meme temps").

    Se branche sur `item.head.clicked` (voir _Section/_SubSection.head),
    APRES la connexion existante `head.clicked -> item.toggle` (faite en
    premier, dans __init__) : au moment ou ce gestionnaire s'execute,
    `item` a donc DEJA bascule — is_collapsed() reflete l'etat REEL apres
    le clic, pas besoin de le calculer a la main. QApplication.
    keyboardModifiers() (pas event.modifiers(), _SectionHeader.clicked
    n'en transporte pas) : lu ICI, dans le gestionnaire du CLIC reel —
    jamais reevalue plus tard pour un set_collapsed() PROGRAMMATIQUE (voir
    plus bas, qui appelle set_collapsed directement, pas item.toggle() —
    ne re-declenche donc jamais ce gestionnaire, pas de recursion)."""
    for item in items:
        def _on_clicked(item=item):
            if item.is_collapsed():
                return  # ce clic vient de REPLIER item, rien a faire
            if QApplication.keyboardModifiers() & Qt.ControlModifier:
                return  # CTRL enfonce : laisse les autres tels quels
            for other in items:
                if other is not item and not other.is_collapsed():
                    other.set_collapsed(True)
        item.head.clicked.connect(_on_clicked)


class _TabStrip(QWidget):
    """Barre d'onglets texte (libelles en petites capitales, soulignement
    accent sur l'onglet actif) — reutilisee a 2 niveaux (voir SettingsWindow.
    __init__ : General/Colonnes) et (voir _build_columns_page : Type/Projets/
    Sous-projets a l'interieur de l'onglet Colonnes). Pas de QTabWidget natif
    Qt : son chrome ne suit pas la palette M de cette fenetre, contrairement
    a ces boutons peints via stylesheet, ici sans effet visible autre que le
    changement d'onglet (le contenu de chaque page reste un widget normal,
    voir SettingsWindow._main_stack/_columns_stack)."""

    changed = Signal(int)

    def __init__(self, labels: list[str], parent=None):
        super().__init__(parent)
        self._index = 0
        self._btns: list[QPushButton] = []
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(4)
        for i, label in enumerate(labels):
            btn = QPushButton(label.upper())
            btn.setFlat(True)
            btn.setCursor(Qt.PointingHandCursor)
            btn.setFocusPolicy(Qt.NoFocus)
            btn.setFixedHeight(36)
            btn.setFont(_qfont(11, 600, tracking=0.4))
            btn.clicked.connect(lambda _checked=False, idx=i: self.setCurrentIndex(idx))
            layout.addWidget(btn)
            self._btns.append(btn)
        layout.addStretch(1)
        self._refresh()

    def _refresh(self):
        for i, btn in enumerate(self._btns):
            if i == self._index:
                btn.setStyleSheet(
                    f"QPushButton {{ color: {M['section_title']}; background: transparent; "
                    f"border: none; border-bottom: 2px solid {M['accent']}; padding: 0 14px; }}"
                )
            else:
                btn.setStyleSheet(
                    f"QPushButton {{ color: {M['label_dim']}; background: transparent; "
                    f"border: none; border-bottom: 2px solid transparent; padding: 0 14px; }}"
                    f"QPushButton:hover {{ color: {M['value_fg']}; }}"
                )

    def setCurrentIndex(self, index: int):
        if index == self._index:
            return
        self._index = index
        self._refresh()
        self.changed.emit(index)

    def currentIndex(self) -> int:
        return self._index


def _apply_stylesheet_cached(widget: QWidget, stylesheet: str) -> None:
    """Remplace un setStyleSheet direct : n'appelle rien si le CSS calcule
    est identique au dernier applique a CE widget. Qt ne fait pas ce
    filtrage lui-meme (un setStyleSheet(memes_octets) redeclenche quand
    meme tout le recalcul de style, y compris en cascade sur les
    descendants d'un widget qui en a beaucoup, mesure a plusieurs ms meme
    pour un tableau de taille moyenne — voir _PanelFrame, meme constat en
    pire pour la fenetre entiere). Utile partout ou une valeur reglable
    (rayon, couleur de tableau...) est reappliquee en boucle a chaque
    glisser d'un slider de couleur (voir SettingsWindow._refresh_dynamic_
    colors) alors qu'elle n'a en realite pas change : la plupart des
    tableaux/lignes stylises ici ne dependent PAS de la couleur en cours
    d'edition — voir la remarque de l'utilisateur sur la latence."""
    if getattr(widget, "_cached_stylesheet", None) == stylesheet:
        return
    widget._cached_stylesheet = stylesheet
    widget.setStyleSheet(stylesheet)


class _TableFrame(QWidget):
    """Cadre exterieur complet (perimetre 1px) d'un tableau — entete et
    lignes empilees a l'interieur, separees seulement par un filet
    horizontal (voir _table_header/_table_row), jamais par des boites
    individuelles : un tableau bien "ferme" (un seul rectangle), pas une
    pile de rectangles accoles (voir la remarque de l'utilisateur, capture
    a l'appui — les tableaux Polices/Geometrie avaient chacun leur propre
    filet gauche/droite/bas, un empilement qui pouvait paraitre "ouvert").

    Suit en direct le slider Geometrie > Tableaux > Coins arrondis (voir
    setRadius), mais UNIQUEMENT pour son propre filet 1px : l'entete et les
    lignes a l'interieur gardent chacune leur propre fond plein (couleurs
    alternees, WA_StyledBackground) que ce border-radius ne touche jamais
    (un border-radius QSS n'arrondit que le PROPRE fond/bordure du widget,
    jamais celui de ses enfants). Une premiere version decoupait tout le
    contenu au masque (QRegion/setMask) pour compenser — mais un masque est
    un decoupage BINAIRE, non anti-aliase : le filet du cadre (lui bien
    arrondi en douceur par le QSS) se retrouvait recoupe au pixel pres par
    ce masque grossier, d'ou des bordures qui ne suivaient plus vraiment la
    courbe (voir la remarque de l'utilisateur, capture a l'appui). Corrige
    en arrondissant plutot CHAQUE piece a l'endroit exact ou elle touche un
    coin (les coins hauts de l'entete/de la premiere ligne si l'entete est
    absente, les coins bas de la derniere ligne — voir
    SettingsWindow._apply_table_radius et ses homologues par tableau), qui
    reste un rendu QSS natif, donc aussi lisse que le filet du cadre."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("TableFrame")
        self.setAttribute(Qt.WA_StyledBackground, True)
        self._radius = 0
        self._refresh_style()

    def _refresh_style(self):
        _apply_stylesheet_cached(
            self, f"#TableFrame {{ border: 1px solid {M['panel_border']}; border-radius: {self._radius}px; }}"
        )

    def setRadius(self, radius: int):
        self._radius = max(0, int(radius))
        self._refresh_style()


def _table_frame() -> tuple[QWidget, QVBoxLayout]:
    frame = _TableFrame()
    layout = QVBoxLayout(frame)
    # Marge de 1px (= l'epaisseur du filet de #TableFrame), PAS 0 : a marge
    # nulle, l'entete/les lignes (chacun avec son propre fond peint via
    # WA_StyledBackground) recouvrent exactement le filet du cadre et le
    # rendent invisible — meme bug, meme correctif que #Panel dans
    # SettingsWindow.__init__ (voir la remarque de l'utilisateur, capture
    # a l'appui : le cadre etait bel et bien absent a l'ecran).
    layout.setContentsMargins(1, 1, 1, 1)
    layout.setSpacing(0)
    return frame, layout


def _restyle_table_head(head: QWidget, radius: int = 0):
    """(Re)applique le fond/filet/coins de l'entete d'un tableau — coins HAUTS
    seulement (voir _TableFrame : c'est elle qui touche le coin haut du
    cadre, pas de coins bas puisqu'une ligne de donnees suit toujours).

    Fond = M['table_head_bg'] par defaut (la pastille "Tableau - entete" de
    Couleurs), SAUF si `head._custom_bg` a ete pose (voir SettingsWindow.
    _apply_table_head_color, Tableaux > Couleur d'en-tete — voir la
    remarque de l'utilisateur, "ajoute couleur d'entete pour les
    tableaux") : un selecteur PARMI les pastilles semantiques, comme
    Colonnes > Couleur des entetes mais pour les tableaux "fermes" de
    CETTE fenetre (Polices/Geometrie, les seuls a avoir un entete) plutot
    que les colonnes du navigateur principal."""
    bg = getattr(head, "_custom_bg", None) or M["table_head_bg"]
    _apply_stylesheet_cached(
        head,
        f"#TableHead {{ background: {bg}; border-bottom: 1px solid {M['panel_border']}; "
        f"border-top-left-radius: {radius}px; border-top-right-radius: {radius}px; }}",
    )


class _ResizableTableHeader(QWidget):
    """En-tete de tableau ferme (voir l'ancienne _table_header, dont c'est
    desormais l'implementation) — chaque colonne a largeur FIXE (pas la
    colonne extensible, largeur 0 dans `cells`) a une poignee de
    redimensionnement sur sa bordure droite, exactement comme les colonnes
    du navigateur principal (voir pipeline_browser.Column._in_resize_zone)
    — voir la remarque de l'utilisateur : "c'est bien ce que je voulais
    depuis le debut". `resized` (index de colonne, nouvelle largeur) permet
    a l'appelant de repercuter le changement sur la cellule correspondante
    de CHAQUE ligne de donnees (voir _wire_resizable_columns) ; la colonne
    extensible absorbe seule la difference (stretch=1, voir Qt), quelle
    que soit sa position parmi les autres.

    La bordure de chaque colonne est detectee via la geometrie REELLE de sa
    cellule (cell.geometry(), fixee par le layout au premier affichage),
    pas en recalculant une position a partir des largeurs statiques de
    `cells` : la colonne extensible peut se trouver n'importe ou dans
    l'ordre (voir _GeoTable, ou elle est la PREMIERE) et sa largeur reelle
    n'est de toute facon connue qu'une fois le layout resolu."""

    resized = Signal(int, int)  # (index de colonne, nouvelle largeur)

    _MARGIN = 5
    _MIN_WIDTH = 60
    _MAX_WIDTH = 640

    def __init__(self, cells: list[tuple[str, int]], parent=None):
        super().__init__(parent)
        self.setObjectName("TableHead")
        self.setAttribute(Qt.WA_StyledBackground, True)
        self.setFixedHeight(26)
        self.setMouseTracking(True)
        _restyle_table_head(self)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        self._widths = [w for _text, w in cells]
        self._cells: list[QLabel] = []
        self._padding_lr = (10, 10)
        for text, width in cells:
            cell = QLabel(text.upper())
            cell.setFont(_qfont(9, 600))
            cell.setStyleSheet(
                f"color: {M['table_head_fg']}; background: transparent; "
                f"padding: 0 {self._padding_lr[1]}px 0 {self._padding_lr[0]}px;"
            )
            # Sans ca, chaque libelle occupe TOUTE sa colonne bord a bord
            # (aucun espace vide entre les cellules, voir le layout
            # ci-dessus) : un vrai clic a la souris sur une bordure de
            # colonne atterrit alors sur ce QLabel (voir QWidget.childAt),
            # PAS sur _ResizableTableHeader lui-meme — mousePressEvent/
            # mouseMoveEvent ci-dessous ne voyaient donc jamais rien passer
            # (voir la remarque de l'utilisateur, capture a l'appui : "ca ne
            # fonctionne pas"). Rendu transparent aux evenements souris, ce
            # widget laisse passer le clic/survol jusqu'a son parent.
            cell.setAttribute(Qt.WA_TransparentForMouseEvents, True)
            self._cells.append(cell)
            if width:
                cell.setFixedWidth(width)
                layout.addWidget(cell, 0)
            else:
                layout.addWidget(cell, 1)
        self._resizing_index: int | None = None
        self._resizing_sign = 1
        self._resize_start_x = 0
        self._resize_start_width = 0
        self._resizable = True

    def setResizable(self, enabled: bool):
        """Tableaux > Colonnes dimensionnables (voir SettingsWindow._section_
        tables) : desactive, ni le curseur ni le glisser ne s'activent plus
        sur aucune bordure — meme reglage que celui qui gouverne deja les
        colonnes du navigateur principal (voir pipeline_browser._Column._in_
        resize_zone), applique ici a ses propres tableaux."""
        self._resizable = bool(enabled)
        if not self._resizable and self._resizing_index is not None:
            self._resizing_index = None
            self.unsetCursor()

    def setCellPadding(self, left: int, right: int):
        """Tableaux > Padding des cellules (voir SettingsWindow.
        _apply_cell_padding) : suit le padding GAUCHE/DROITE des lignes de
        donnees (pas Haut/Bas — cette entete a une hauteur fixe, 26px, son
        contenu deja centre verticalement par le layout) pour que le
        libelle de chaque colonne reste aligne avec le contenu de la
        colonne en dessous."""
        self._padding_lr = (max(0, int(left)), max(0, int(right)))
        for cell in self._cells:
            cell.setStyleSheet(
                f"color: {M['table_head_fg']}; background: transparent; "
                f"padding: 0 {self._padding_lr[1]}px 0 {self._padding_lr[0]}px;"
            )

    def _column_edges(self) -> list[int]:
        """Position (x) du bord droit de chaque colonne, calculee a partir
        des largeurs fixes ET de la largeur REELLE actuelle de ce widget
        (self.width(), toujours fiable — contrairement a cell.geometry(),
        qui peut ne pas encore refleter le dernier passage de layout) : la
        ou toute colonne extensible se trouve dans `cells` se voit
        attribuer le meme partage de l'espace restant qu'un vrai stretch=1
        de QHBoxLayout."""
        stretch_count = self._widths.count(0)
        used = sum(w for w in self._widths if w)
        stretch_width = max(0, self.width() - used) // stretch_count if stretch_count else 0
        edges = []
        pos = 0
        for w in self._widths:
            pos += w if w else stretch_width
            edges.append(pos)
        return edges

    def _draggable_boundaries(self) -> list[tuple[int, int, int]]:
        """Bordures REELLEMENT glissables : (position x, index de colonne
        controlee, signe) — signe +1 si glisser vers la DROITE agrandit
        cette colonne (sa propre bordure DROITE, le cas normal), -1 si
        glisser vers la DROITE la retrecit (sa bordure GAUCHE — n'existe
        que quand la colonne PRECEDENTE est extensible, voir _GeoTable ou
        "Element" precede "Cadre" : sans ce cas, la bordure entre les deux
        ne controlait RIEN, obligeant l'utilisateur a aller chercher celle,
        bien plus loin, apres TOUTE la colonne Cadre — voir sa remarque,
        capture a l'appui, "il faut que j'aille chercher le slider apres le
        texte cadre")."""
        edges = self._column_edges()
        boundaries: list[tuple[int, int, int]] = []
        left = 0
        for i, width in enumerate(self._widths):
            if width == 0:
                left = edges[i]
                continue
            if i > 0 and self._widths[i - 1] == 0:
                boundaries.append((left, i, -1))
            boundaries.append((edges[i], i, 1))
            left = edges[i]
        return boundaries

    def _boundary_at(self, x: int) -> tuple[int, int] | None:
        if not self._resizable:
            return None
        for pos, index, sign in self._draggable_boundaries():
            if pos - self._MARGIN <= x <= pos + self._MARGIN:
                return index, sign
        return None

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            hit = self._boundary_at(event.position().toPoint().x())
            if hit is not None:
                self._resizing_index, self._resizing_sign = hit
                self._resize_start_x = event.globalPosition().toPoint().x()
                self._resize_start_width = self._widths[self._resizing_index]
                event.accept()
                return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        if self._resizing_index is not None:
            delta = event.globalPosition().toPoint().x() - self._resize_start_x
            new_width = max(self._MIN_WIDTH, min(self._MAX_WIDTH, self._resize_start_width + self._resizing_sign * delta))
            self._set_width(self._resizing_index, new_width)
            event.accept()
            return
        hit = self._boundary_at(event.position().toPoint().x())
        self.setCursor(Qt.SizeHorCursor if hit is not None else Qt.ArrowCursor)
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        if self._resizing_index is not None:
            self._resizing_index = None
            event.accept()
            return
        super().mouseReleaseEvent(event)

    def leaveEvent(self, event):
        if self._resizing_index is None:
            self.unsetCursor()
        super().leaveEvent(event)

    def _set_width(self, index: int, width: int):
        self._widths[index] = width
        self._cells[index].setFixedWidth(width)
        self.resized.emit(index, width)

    def columnWidths(self) -> list[int]:
        """Voir setColumnWidths — a sauvegarder tel quel dans les reglages
        (un preset, voir SettingsWindow._current_values) : inclut aussi la
        largeur (0) de la colonne extensible, pour garder les INDICES
        alignes avec `cells` a la restauration."""
        return list(self._widths)

    def setColumnWidths(self, widths: list[int]):
        """Restaure des largeurs sauvegardees (voir columnWidths/
        SettingsWindow._apply_values_to_controls) — reutilise _set_width
        pour chaque colonne FIXE, qui repercute automatiquement sur la
        cellule correspondante de chaque ligne (voir _wire_resizable_
        columns) ; la colonne extensible (largeur 0 dans `cells`, jamais
        stockee) est ignoree, tout comme une liste trop courte/vide (ancien
        preset sans ce reglage — voir DEFAULT_SETTINGS)."""
        for i, width in enumerate(widths):
            if i < len(self._widths) and self._widths[i] and width:
                self._set_width(i, max(self._MIN_WIDTH, min(self._MAX_WIDTH, int(width))))


class _FlatColumnResizer(QObject):
    """Bordure libelle/controle glissable a la main, sur un tableau "ferme"
    SANS entete de colonnes (_build_flat_table/_section_headers, voir
    _table_row) — meme experience que _ResizableTableHeader (curseur au
    survol, glisser change la largeur) mais SANS widget d'entete a saisir
    puisque ces tableaux n'en ont pas : la bordure se saisit directement
    sur N'IMPORTE QUELLE ligne du tableau (installe en filtre d'evenements
    sur chacune, voir wire()) et gouverne TOUTES les lignes a la fois — une
    SEULE largeur de libelle partagee — voir la remarque de l'utilisateur,
    "je veux aussi pouvoir redimensionner les colonnes meme si le tableau
    n'a pas d'entete", "glisser la bordure entre libelle et controle, sur
    n'importe quelle ligne".

    Le controle reste TOUJOURS colle au bord droit de la ligne (voir la
    remarque de l'utilisateur, qui a tranche explicitement pour cette
    option) : seule la largeur du libelle change ; voir _build_flat_table/
    _section_headers, qui ajoutent l'espaceur extensible entre les deux
    necessaire pour ca (le libelle n'a plus lui-meme ce stretch=1, tenu
    desormais par cet espaceur dedie)."""

    resized = Signal(int)

    _MARGIN = 5
    _MIN_WIDTH = 60
    _MAX_WIDTH = 400

    def __init__(self, width: int, parent=None):
        super().__init__(parent)
        self._cells: list[QWidget] = []
        self._rows: list[QWidget] = []
        self._width = max(self._MIN_WIDTH, min(self._MAX_WIDTH, width))
        self._resizing = False
        self._resize_start_x = 0
        self._resize_start_width = self._width
        self._resizable = True

    def wire(self, row: QWidget, label_cell: QWidget):
        """A appeler pour CHAQUE ligne du tableau, juste apres l'avoir
        remplie (voir _build_flat_table/_section_headers) : `label_cell`
        (le libelle, 1er widget de la ligne) suit desormais la largeur
        partagee, `row` (la ligne entiere, pas juste le libelle — la
        bordure doit rester saisissable sur toute sa hauteur) recoit ce
        controleur comme filtre d'evenements."""
        label_cell.setFixedWidth(self._width)
        self._cells.append(label_cell)
        self._rows.append(row)
        row.setMouseTracking(True)
        row.installEventFilter(self)

    def setResizable(self, enabled: bool):
        """Tableaux > Colonnes dimensionnables (voir SettingsWindow.
        _apply_columns_resizable) — meme reglage que celui qui gouverne
        deja _ResizableTableHeader, applique ici a ces tableaux SANS
        entete."""
        self._resizable = bool(enabled)
        if not self._resizable and self._resizing:
            self._resizing = False
            for row in self._rows:
                row.unsetCursor()

    def setWidth(self, width: int):
        self._width = max(self._MIN_WIDTH, min(self._MAX_WIDTH, int(width)))
        for cell in self._cells:
            cell.setFixedWidth(self._width)

    def width(self) -> int:
        return self._width

    def _boundary_x(self, row: QWidget) -> int:
        left, _top, _right, _bottom = row.layout().getContentsMargins()
        return left + self._width

    def eventFilter(self, row, event):
        if not self._resizable:
            return False
        etype = event.type()
        if etype == QEvent.MouseMove:
            if self._resizing:
                delta = event.globalPosition().toPoint().x() - self._resize_start_x
                self.setWidth(self._resize_start_width + delta)
                self.resized.emit(self._width)
                return True
            near = abs(event.position().toPoint().x() - self._boundary_x(row)) <= self._MARGIN
            row.setCursor(Qt.SizeHorCursor if near else Qt.ArrowCursor)
        elif etype == QEvent.MouseButtonPress:
            if event.button() == Qt.LeftButton and \
                    abs(event.position().toPoint().x() - self._boundary_x(row)) <= self._MARGIN:
                self._resizing = True
                self._resize_start_x = event.globalPosition().toPoint().x()
                self._resize_start_width = self._width
                return True
        elif etype == QEvent.MouseButtonRelease:
            if self._resizing:
                self._resizing = False
                self.resized.emit(self._width)
                return True
        elif etype == QEvent.Leave:
            if not self._resizing:
                row.unsetCursor()
        return False


def _table_header(cells: list[tuple[str, int]]) -> QWidget:
    """cells : (libelle, largeur) — largeur 0 => colonne extensible. Filet
    du bas SEULEMENT (separation avec la premiere ligne) : le perimetre du
    tableau est deja fourni par _table_frame, pas par l'entete elle-meme.
    Voir _ResizableTableHeader pour l'implementation (poignees de
    redimensionnement) et _wire_resizable_columns pour la repercuter sur
    les lignes de donnees."""
    return _ResizableTableHeader(cells)


def _wire_resizable_columns(head: _ResizableTableHeader, column_cells: dict[int, list[QWidget]]):
    """Repercute un redimensionnement de colonne (voir
    _ResizableTableHeader.resized) sur la cellule correspondante de CHAQUE
    ligne de donnees — `column_cells` : {index de colonne: [cellules de
    cette colonne, une par ligne]}, construit par l'appelant a partir des
    QWidget renvoyes par _table_cell (voir _GeoTable/_SimpleFontTable)."""
    def _on_resize(index: int, width: int):
        for cell in column_cells.get(index, []):
            cell.setFixedWidth(width)

    head.resized.connect(_on_resize)


def _restyle_table_row(row: QWidget, bg: str, first: bool, top_radius: int = 0, bottom_radius: int = 0):
    """(Re)applique le fond/filet/coins d'une ligne de donnees. `top_radius`
    n'est utile que pour la toute premiere ligne d'un tableau SANS entete
    (elle touche alors elle-meme le coin haut du cadre — voir la table
    Entetes) ; `bottom_radius` seulement pour la toute derniere ligne (elle
    touche toujours le coin bas du cadre, entete ou pas) — voir
    SettingsWindow._apply_table_radius et homologues, qui recalculent ces
    deux valeurs a chaque cran du slider Geometrie > Tableaux."""
    border = "" if first else f"border-top: 1px solid {M['panel_border']};"
    _apply_stylesheet_cached(
        row,
        f"#TableRow {{ background: {bg}; {border} "
        f"border-top-left-radius: {top_radius}px; border-top-right-radius: {top_radius}px; "
        f"border-bottom-left-radius: {bottom_radius}px; border-bottom-right-radius: {bottom_radius}px; }}",
    )


def _table_row(bg: str, first: bool) -> tuple[QWidget, QHBoxLayout]:
    """`first` : la toute premiere ligne de donnees colle directement sous
    l'entete (qui a deja son propre filet du bas) — seules les lignes
    SUIVANTES ont besoin de leur propre filet du haut ; aucune ligne ne
    dessine plus ses propres cotes gauche/droite (voir _table_frame)."""
    row = QWidget()
    row.setObjectName("TableRow")
    row.setAttribute(Qt.WA_StyledBackground, True)
    # 36 : plancher de secours pour un contenu tres court (une seule ligne
    # de texte, sans note). Insuffisant des que la ligne contient un
    # libelle+note ou un controle plus haut — l'appelant DOIT alors finir
    # par _lock_min_height(row) une fois la ligne remplie, qui remplace ce
    # plancher par le vrai besoin (voir sa docstring pour le detail du bug
    # que ca corrige).
    row.setMinimumHeight(36)
    _restyle_table_row(row, bg, first)
    layout = QHBoxLayout(row)
    layout.setContentsMargins(0, 6, 0, 6)
    layout.setSpacing(0)
    return row, layout


def _lock_min_height(row: QWidget):
    """A appeler UNE FOIS une ligne/cellule de tableau REMPLIE (libelle,
    pastille, controle... voir les appelants de _table_row ET de
    _ColorGrid.__init__) — DOIT venir apres, jamais dans _table_row lui-
    meme : sizeHint() n'est fiable qu'une fois le contenu reellement present
    (une ligne vide ferait remonter un sizeHint() minuscule).

    Fait deux choses, INDISSOCIABLES : SizePolicy.Minimum sur la hauteur
    (le layout ne retrecit plus cette ligne PAR PREFERENCE quand de la
    place est disponible ailleurs) ET minimumHeight() fige a sizeHint()
    (ce que les CONTENEURS PARENTS — tableau, section, ascenseur de
    _build_content, voir _NoSqueezeScrollArea — accumulent pour savoir de
    combien d'espace le contenu a REELLEMENT besoin en tout ; SizePolicy
    seule n'y suffit pas, elle ne change rien a minimumSizeHint(), calcule
    par Qt a partir du minimumSize EXPLICITE de chaque enfant). Sans ce 2e
    volet, l'accumulation remontait un minimum sous-estime des qu'une ligne
    contenait un libelle sur 2 lignes/une pastille plus haute que le texte
    seul, et la fenetre entiere se retrouvait autorisee a s'ouvrir/se
    redimensionner plus bas que ce contenu reel — un deficit de quelques
    pixels a peine, mais suffisant pour rogner le bas du texte des
    libelles (ex. "Racine par defaut" -> "Racine nar defaut", le bas du
    "p" disparaissant) ou le bord bas des pastilles de couleur (Couleurs,
    _ColorGrid) — voir la remarque de l'utilisateur, capture annotee a
    l'appui pour les deux.
    """
    row.setSizePolicy(row.sizePolicy().horizontalPolicy(), QSizePolicy.Minimum)
    row.setMinimumHeight(max(row.minimumHeight(), row.sizeHint().height()))


def _table_cell(widget: QWidget, width: int, layout: QHBoxLayout, center: bool = False) -> QWidget:
    cell = QWidget()
    # Fond transparent EXPLICITE : sans lui, ce QWidget nu se voit quand
    # meme peint (le style sheet global de l'appli active WA_StyledBackground
    # implicitement sur tout QWidget), avec la couleur heritee du fond de
    # l'ascenseur de contenu (voir SettingsWindow._build_content, scroller.
    # setStyleSheet) plutot que rester invisible — cette cellule recouvre la
    # quasi-totalite de chaque ligne de tableau (Polices/Geometrie), ce qui
    # masquait entierement la couleur "Fond de tableau" (table_row/M['table_
    # row_a'/'table_row_b']) choisie par l'utilisateur, ne laissant filtrer
    # que le fin liseret des marges de la ligne — voir la remarque de
    # l'utilisateur, capture a l'appui.
    cell.setStyleSheet("background: transparent;")
    cell_l = QHBoxLayout(cell)
    cell_l.setContentsMargins(10, 0, 10, 0)
    if center:
        cell_l.setAlignment(Qt.AlignVCenter)
    cell_l.addWidget(widget)
    if width:
        cell.setFixedWidth(width)
        layout.addWidget(cell, 0)
    else:
        layout.addWidget(cell, 1)
    return cell


def _build_flat_table(
    rows: list[tuple[str, QWidget]],
) -> tuple[QWidget, list[tuple[QWidget, str, bool]], _FlatColumnResizer]:
    """Tableau ferme SANS entete (voir _section_headers, meme technique) :
    une ligne "libelle / controle" par reglage — utilise par les sous-tables
    de Geometrie > Slider (voir SettingsWindow._section_geometry). Retourne
    (frame, row_meta, resizer) ; row_meta est a repasser tel quel a chaque
    appel de SettingsWindow._restyle_flat_table (Geometrie > Tableaux >
    Coins arrondis) ; resizer (voir _FlatColumnResizer) permet de glisser
    la bordure libelle/controle SANS entete a saisir — voir la remarque de
    l'utilisateur, "je veux aussi pouvoir redimensionner les colonnes meme
    si le tableau n'a pas d'entete".

    Le libelle n'a PLUS le stretch=1 qui le faisait jusqu'ici absorber tout
    l'espace restant (largeur fixe desormais, pilotee par le resizer) : un
    espaceur extensible dedie prend le relai pour garder le controle colle
    au bord droit (voir la remarque de l'utilisateur, qui a tranche
    explicitement pour cette option)."""
    frame, layout = _table_frame()
    row_meta: list[tuple[QWidget, str, bool]] = []
    label_blocks: list[QWidget] = []
    rows_widgets: list[QWidget] = []
    for i, (label, control) in enumerate(rows):
        bg = M["table_row_a"] if i % 2 else M["table_row_b"]
        row, row_l = _table_row(bg, first=(i == 0))
        row_meta.append((row, bg, i == 0))
        row_l.setContentsMargins(14, 8, 14, 8)
        row_l.setSpacing(14)
        label_block = _label_block(label)
        row_l.addWidget(label_block, 0)
        row_l.addStretch(1)
        row_l.addWidget(control, 0, Qt.AlignVCenter)
        label_blocks.append(label_block)
        rows_widgets.append(row)
        _lock_min_height(row)
        layout.addWidget(row)
    # Largeur de depart = la plus grande sizeHint() naturelle des libelles
    # de CE tableau (pas une constante arbitraire) : le texte de chaque
    # libelle restant aligne a GAUCHE dans sa boite (voir _label_block),
    # cette largeur ne change RIEN a l'apparence par defaut (juste la place
    # invisible avant l'espaceur) tant que l'utilisateur ne glisse pas la
    # bordure — voir la remarque de l'utilisateur sur l'absence de
    # changement visuel par defaut, deja appliquee au padding/a la couleur
    # d'en-tete plus haut dans cette session.
    natural_width = max((_label_block_natural_width(lb) for lb in label_blocks), default=_FlatColumnResizer._MIN_WIDTH)
    resizer = _FlatColumnResizer(natural_width)
    for row, label_block in zip(rows_widgets, label_blocks):
        resizer.wire(row, label_block)
    # Verrouille aussi le CADRE entier (pas seulement chaque ligne, deja
    # fait ci-dessus) sur sa hauteur naturelle — systematique, POUR TOUS
    # LES TABLEAUX construits par cette fonction (aucun site d'appel n'a
    # rien a faire de plus) : sans ca, un CONTENEUR englobant a court
    # d'espace (fenetre trop basse, sous-groupe qui vient de se deplier...)
    # peut toujours compresser le cadre lui-meme en dessous de la somme de
    # ses lignes, malgre le plancher de CHAQUE ligne prise separement —
    # voir la remarque de l'utilisateur, capture a l'appui, "corrige
    # l'ecrasement du tableau ... que tu le prennes systematiquement en
    # compte pour tous les tableaux".
    _lock_min_height(frame)
    return frame, row_meta, resizer


def _set_label_block_dim(label_block: QWidget, dim: bool):
    """Grise (ou re-eclaircit) le texte d'un _label_block — voir
    _build_override_flat_table, un toggle OFF grise le libelle de sa ligne
    ("ce qui grisera la ligne", remarque de l'utilisateur)."""
    color = M["label_dim"] if dim else M["row_label"]
    for label in label_block.findChildren(QLabel):
        label.setStyleSheet(f"color: {color}; background: transparent;")


def _build_override_flat_table(
    rows: list[tuple[str, QWidget, "_Toggle"]],
) -> tuple[QWidget, list[tuple[QWidget, str, bool]], _FlatColumnResizer]:
    """Meme construction que _build_flat_table (tableau ferme SANS entete),
    mais chaque ligne est precedee d'un toggle1 (voir Colonnes > Type,
    SettingsWindow._build_column_type_page — la remarque de l'utilisateur,
    "juste devant le texte de chaque parametre, tu mets un toggle 1 en off,
    ce qui grisera la ligne") : OFF grise le libelle ET desactive le
    controle (la ligne suit alors la valeur GENERALE, voir
    SettingsWindow._apply_column_type_preview) ; ON re-eclaircit le libelle
    et active le controle, dont la propre valeur prend alors le relai — "le
    fait de mettre le toggle en ON overide le parametre et la modification
    est apportee en temps reel". Le toggle reste HORS de la cellule
    redimensionnable (voir _FlatColumnResizer.wire ci-dessous, appele sur
    le SEUL label_block comme dans _build_flat_table) : sa largeur est
    fixe, glisser la frontiere libelle/controle ne doit faire bouger que le
    texte, pas le toggle."""
    frame, layout = _table_frame()
    row_meta: list[tuple[QWidget, str, bool]] = []
    label_blocks: list[QWidget] = []
    rows_widgets: list[QWidget] = []
    for i, (label, control, toggle) in enumerate(rows):
        bg = M["table_row_a"] if i % 2 else M["table_row_b"]
        row, row_l = _table_row(bg, first=(i == 0))
        row_meta.append((row, bg, i == 0))
        row_l.setContentsMargins(14, 8, 14, 8)
        row_l.setSpacing(14)
        # Toggle + libelle RAPPROCHES l'un de l'autre (6px, pas les 14px du
        # reste de la ligne) dans leur propre petite boite — voir la
        # remarque de l'utilisateur, "approche les textes des parametre
        # proche des toggles" — plutot que le rythme uniforme de
        # _build_flat_table, pense pour des cellules independantes.
        toggle_label_box = QWidget()
        toggle_label_box.setStyleSheet("background: transparent;")
        toggle_label_l = QHBoxLayout(toggle_label_box)
        toggle_label_l.setContentsMargins(0, 0, 0, 0)
        toggle_label_l.setSpacing(6)
        toggle_label_l.addWidget(toggle, 0, Qt.AlignVCenter)
        label_block = _label_block(label)
        toggle_label_l.addWidget(label_block, 0)
        row_l.addWidget(toggle_label_box, 0)
        row_l.addStretch(1)
        row_l.addWidget(control, 0, Qt.AlignVCenter)
        label_blocks.append(label_block)
        rows_widgets.append(row)

        def _sync_override(checked: bool, control=control, label_block=label_block):
            control.setEnabled(checked)
            _set_label_block_dim(label_block, not checked)

        toggle.toggled.connect(_sync_override)
        _sync_override(toggle.isChecked())
        _lock_min_height(row)
        layout.addWidget(row)
    natural_width = max((_label_block_natural_width(lb) for lb in label_blocks), default=_FlatColumnResizer._MIN_WIDTH)
    resizer = _FlatColumnResizer(natural_width)
    for row, label_block in zip(rows_widgets, label_blocks):
        resizer.wire(row, label_block)
    # Verrouille aussi le CADRE entier — voir _build_flat_table, meme
    # necessite/memes raisons (systematique pour tous les tableaux, voir
    # la remarque de l'utilisateur, "corrige l'ecrasement du tableau ...
    # que tu le prennes systematiquement en compte pour tous les
    # tableaux").
    _lock_min_height(frame)
    return frame, row_meta, resizer


# ==========================================================================
# Colonnes > Type — surcharge PARAMETRE PAR PARAMETRE de la section
# "Colonnes" de l'onglet General (voir SettingsWindow._build_column_type_
# page/_section_headers) — cle de reglage -> attribut du champ GENERAL
# correspondant (celui suivi quand le toggle de la ligne est OFF, voir
# SettingsWindow._resolve_type_effective). Duplique volontairement
# pipeline_browser.COLUMN_TYPE_OVERRIDE_KEYS (meme liste) : settings_window
# ne peut pas importer pipeline_browser (sens d'import inverse).
# ==========================================================================

_COLUMN_TYPE_OVERRIDE_KEYS = [
    "header_height", "header_padding", "header_color", "header_radius",
    "header_border_enabled", "header_border", "header_border_thickness",
    "column_padding", "column_border_enabled", "column_border", "column_border_thickness", "column_border_radius",
    "item_font_family", "item_color", "item_icon_enabled", "item_row_height", "item_row_spacing",
    "item_text_padding", "item_selection_focus_color", "item_selection_unfocus_color", "item_hover_color",
    "item_selection_padding", "item_selection_border_enabled", "item_selection_border",
    "item_selection_radius", "item_selection_edge_border",
]

_TYPE_GENERAL_FIELD_ATTR = {
    "header_height": "header_height_field",
    "header_padding": "header_padding_field",
    "header_color": "header_color_field",
    "header_radius": "header_radius_field",
    "header_border_enabled": "header_border_field",
    "header_border": "header_border_field",
    "header_border_thickness": "header_border_thickness_field",
    "column_padding": "column_padding_field",
    "column_border_enabled": "column_border_field",
    "column_border": "column_border_field",
    "column_border_thickness": "column_border_thickness_field",
    "column_border_radius": "column_border_radius_field",
    "item_font_family": "item_font_field",
    "item_color": "item_color_field",
    "item_icon_enabled": "item_icon_field",
    "item_row_height": "item_row_height_field",
    "item_row_spacing": "item_row_spacing_field",
    "item_text_padding": "item_text_padding_field",
    "item_selection_focus_color": "item_selection_focus_field",
    "item_selection_unfocus_color": "item_selection_unfocus_field",
    "item_hover_color": "item_hover_field",
    "item_selection_padding": "item_selection_padding_field",
    "item_selection_border_enabled": "item_selection_border_field",
    "item_selection_border": "item_selection_border_field",
    "item_selection_radius": "item_selection_radius_field",
    "item_selection_edge_border": "item_selection_edge_border_field",
}

# Cles dont le reglage LIE ("linked"/"libre", voir _CornerRadiusField/
# _CellPaddingField) doit aussi etre suivi/persiste a part (voir
# SettingsWindow._type_override_linked/_current_values).
_TYPE_LINKED_KEYS = (
    "header_radius", "column_padding", "column_border_radius", "item_selection_padding", "item_selection_radius",
)


def _read_override_field_raw(key: str, widget):
    """Valeur BRUTE (meme forme que dans settings.json — pas de couleur
    "@slot" resolue, voir app_style.resolve_color_ref, qui s'en charge cote
    appli reelle) d'un champ de Colonnes > Type OU de son homologue GENERAL
    (voir SettingsWindow._resolve_type_effective, appele sur l'un ou
    l'autre selon l'etat du toggle de la ligne)."""
    if key in ("header_radius", "column_border_radius", "item_selection_radius"):
        return widget.cornersValue()
    if key in ("header_border_enabled", "column_border_enabled", "item_selection_border_enabled"):
        return widget.sidesEnabledValue()
    if key in ("header_border", "column_border", "item_selection_border"):
        return widget.sidesValue()
    if key in ("item_selection_padding", "column_padding"):
        return widget.sidesValue()
    if key == "header_color":
        return widget.value()
    if key == "item_font_family":
        v = widget.value()
        return "" if v == "Systeme" else v
    if key in ("item_icon_enabled", "item_selection_edge_border"):
        return widget.isChecked()
    if key in ("item_color", "item_selection_focus_color", "item_selection_unfocus_color", "item_hover_color"):
        return widget.value()
    return widget.value()  # sliders (int) : header_height/padding/thickness..., item_row_height/spacing/text_padding


# ==========================================================================
# Section "Polices" — table Role/Police/Lissage/Apercu (4 colonnes, famille
# + niveau de lissage). Les 4 roles non repris ici (dossiers, boutons,
# entete de colonnes, info2) restent dans le fichier de reglages tels quels
# (voir DEFAULT_SETTINGS) : ils suivent silencieusement "Police principale"
# si elle est personnalisee (voir app_style.role_font), sinon
# l'auto-detection habituelle — exactement leur comportement actuel, juste
# sans UI pour le changer directement.
# ==========================================================================

_FONT_ROLES = [
    ("font_main", "app", "Police principale", "asset__spaceship_01"),
    ("font_info", "info", "Police informations", "121.7 KB · v004 · 2026-09-03"),
    ("font_titles", "titles", "Police principale titres", "Fichiers pour AIRPLANE"),
    ("font_files", "files", "Police fichiers", "foot.001.OBJ"),
    # "Code" : role ajoute sur demande de l'utilisateur, Consolas explicite
    # (voir app_style.code_family) — pas encore consommee ailleurs dans
    # l'appli (meme principe que "table_head"/"table_row" en leur temps).
    ("font_code", "code", "Police code", "def render(frame: int) -> None:"),
]

def _font_choices() -> list[str]:
    return ["Systeme"] + installed_font_families()


# Ordre des 3 crans du slider Lissage (voir _SteppedSliderField), du moins
# au plus lisse — cles de app_style.SMOOTHING_CHOICES/SMOOTHING_LABELS_SHORT,
# juste reordonnees pour correspondre a la remarque de l'utilisateur :
# "0=pas du tout, 1=un peu, 2=important".
_SMOOTHING_STEPS = ("none", "previous", "current")


class _SimpleFontTable(QWidget):
    """Une ligne par role (voir _FONT_ROLES) : nom de role, selecteur de
    police, apercu du nom de fichier/dossier dans cette police. Choisir une
    police (meme "Systeme" explicitement) marque le role "personnalise"
    (voir _current_values dans SettingsWindow) — sinon le changement de
    famille resterait sans effet si ce role n'avait encore jamais ete
    personnalise (voir app_style.role_font : la famille stockee n'est prise
    en compte que si `custom` est vrai)."""

    changed = Signal()

    def __init__(self, settings: dict, parent=None):
        super().__init__(parent)
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        self.frame, layout = _table_frame()
        frame = self.frame
        self.head = _table_header([("Role", 150), ("Police", 170), ("Lissage", 170), ("Apercu", 0)])
        layout.addWidget(self.head)

        # Libelles dans l'ORDRE des crans du slider (voir _SMOOTHING_STEPS,
        # 0 = pas du tout, 2 = important) — slider a positions FIXES plutot
        # qu'un menu deroulant (voir la remarque de l'utilisateur : "slider
        # 3 points (crante)"), le lissage n'ayant de toute facon que ces 3
        # niveaux reels cote Qt/Windows (voir app_style.font()).
        smoothing_labels = [SMOOTHING_LABELS_SHORT[key] for key in _SMOOTHING_STEPS]

        self.rows: dict[str, dict[str, Any]] = {}
        self._row_meta: list[tuple[QWidget, str, bool]] = []
        # Toutes les cellules (_table_cell), TOUTES colonnes confondues —
        # separee de column_cells ci-dessous (qui ne sert qu'au cablage du
        # redimensionnement par colonne, voir _wire_resizable_columns) :
        # necessaire pour le padding (voir setCellPadding/SettingsWindow.
        # _apply_cell_padding), qui doit toucher CHAQUE cellule.
        self._cells: list[QWidget] = []
        column_cells: dict[int, list[QWidget]] = {}
        for i, (key, style_role, label, sample) in enumerate(_FONT_ROLES):
            conf = settings[key]
            bg = M["table_row_a"] if i % 2 else M["table_row_b"]
            row, row_l = _table_row(bg, first=(i == 0))
            self._row_meta.append((row, bg, i == 0))

            name = QLabel(label)
            name.setFont(_qfont(12, 400))
            name.setStyleSheet(f"color: {M['row_label']}; background: transparent;")
            cell = _table_cell(name, 150, row_l, center=True)
            column_cells.setdefault(0, []).append(cell)
            self._cells.append(cell)

            current_family = conf.get("family") or "Systeme"
            auto_label = auto_family_for_role(style_role)
            font_select = _FontSelectField(_font_choices(), current_family, width=162, auto_label=auto_label)
            cell = _table_cell(font_select, 170, row_l, center=True)
            column_cells.setdefault(1, []).append(cell)
            self._cells.append(cell)

            current_smoothing = conf.get("smoothing") or "current"
            if current_smoothing not in SMOOTHING_CHOICES:
                current_smoothing = "current"
            smoothing_step = _SMOOTHING_STEPS.index(current_smoothing)
            smoothing_select = _SteppedSliderField(smoothing_labels, smoothing_step, slider_width=20, box_width=90)
            cell = _table_cell(smoothing_select, 170, row_l, center=True)
            column_cells.setdefault(2, []).append(cell)
            self._cells.append(cell)

            preview = QLabel(sample)
            preview.setFont(QFont(current_family if current_family != "Systeme" else auto_label, 10))
            preview.setStyleSheet(f"color: {M['value_muted']}; background: transparent;")
            self._cells.append(_table_cell(preview, 0, row_l, center=True))

            _lock_min_height(row)
            layout.addWidget(row)
            entry = {
                "field": font_select, "smoothing_field": smoothing_select,
                "preview": preview, "auto": auto_label, "custom": bool(conf.get("custom", False)),
            }
            self.rows[key] = entry

            def _on_pick(family: str, e=entry):
                e["custom"] = True
                shown = family if family != "Systeme" else e["auto"]
                e["preview"].setFont(QFont(shown, 10))
                self.changed.emit()

            font_select.changed.connect(_on_pick)
            smoothing_select.changed.connect(lambda _step: self.changed.emit())
        _wire_resizable_columns(self.head, column_cells)
        # Largeurs sauvegardees (voir _GeoTable, meme raison de venir APRES
        # le cablage ci-dessus).
        saved_widths = settings.get("font_table_columns")
        if saved_widths:
            self.head.setColumnWidths(saved_widths)

        outer.addWidget(frame)

    def value(self) -> dict[str, dict]:
        out = {}
        for key, entry in self.rows.items():
            family = entry["field"].value()
            out[key] = {
                "family": "" if family == "Systeme" else family,
                "smoothing": _SMOOTHING_STEPS[entry["smoothing_field"].value()],
                "custom": entry["custom"],
            }
        return out

    def apply_radius(self, radius: int):
        """Voir _TableFrame : l'entete porte les coins hauts, la derniere
        ligne les coins bas — jamais le cadre lui-meme au-dela de son propre
        filet 1px. `bg` est RECALCULEE ici (pas reprise telle quelle depuis
        `_row_meta`, qui ne la garde que pour son ordre pair/impair) : cette
        methode sert aussi de rafraichissement apres un changement de
        couleur (voir SettingsWindow._refresh_dynamic_colors, qui l'appelle
        avec le rayon courant), donc la valeur stockee peut etre perimee."""
        self.frame.setRadius(radius)
        _restyle_table_head(self.head, radius)
        last = len(self._row_meta) - 1
        new_meta = []
        for i, (row, _old_bg, first) in enumerate(self._row_meta):
            bg = M["table_row_a"] if i % 2 == 0 else M["table_row_b"]
            _restyle_table_row(row, bg, first, bottom_radius=(radius if i == last else 0))
            new_meta.append((row, bg, first))
        self._row_meta = new_meta

    def setCellPadding(self, sides: dict):
        """Tableaux > Padding des cellules (voir SettingsWindow.
        _apply_cell_padding) : applique aux cellules (_table_cell) de CE
        tableau — contrairement aux tableaux "1 valeur par ligne", le
        padding touche ici chaque _table_cell individuellement (pas la
        ligne elle-meme, qui n'a pas de marge propre — voir _table_cell,
        (0, 6, 0, 6) fige a la construction), et l'entete (voir
        _ResizableTableHeader.setCellPadding) suit le GAUCHE/DROITE pour
        rester aligne avec le contenu — voir la remarque de l'utilisateur,
        "je ne vois pas pourquoi ca ne fonctionnerait pas" (Polices/
        Geometrie en etaient exclus jusqu'ici)."""
        left, top = int(sides.get("left", 10)), int(sides.get("top", 0))
        right, bottom = int(sides.get("right", 10)), int(sides.get("bottom", 0))
        for cell in self._cells:
            cell.layout().setContentsMargins(left, top, right, bottom)
        for row, _bg, _first in self._row_meta:
            row.setMinimumHeight(0)
            _lock_min_height(row)
        self.head.setCellPadding(left, right)


# ==========================================================================
# Section "Couleurs" — grille 2 colonnes, 8 pastilles semantiques (voir
# app_style.SEMANTIC_COLOR_SLOTS). "Selection en cours" et "Bouton" pilotent
# la MEME cle reelle ("accent", voir la remarque dans app_style.py) : les
# deux pastilles restent donc synchronisees, un changement sur l'une se
# repercute immediatement sur l'autre — fidele au reste de l'appli, qui n'a
# qu'une seule couleur d'accent pour les deux roles.
# ==========================================================================

class _ColorGrid(QWidget):
    """Grille 2 colonnes des pastilles semantiques — visuellement aussi un
    "tableau" (perimetre + gouttiere 1px entre cellules, voir wrap) que
    Polices/Entetes/Geometrie, donc suit lui aussi le slider Geometrie >
    Tableaux > Coins arrondis (voir setRadius) — voir la remarque de
    l'utilisateur, capture a l'appui : il manquait a l'appel."""

    changed = Signal()

    def __init__(self, colors: dict, parent=None):
        super().__init__(parent)
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        self.wrap = wrap = QWidget()
        wrap.setAttribute(Qt.WA_StyledBackground, True)
        grid = QGridLayout(wrap)
        grid.setContentsMargins(1, 1, 1, 1)
        grid.setHorizontalSpacing(1)
        grid.setVerticalSpacing(1)
        self._fields_by_real_key: dict[str, list[_ColorField]] = {}
        self._hex_labels_by_real_key: dict[str, list[QLabel]] = {}
        # (widget, row, col) de chaque cellule — voir setRadius, qui a
        # besoin de savoir laquelle occupe chaque coin de la grille (le
        # nombre de pastilles etant impair, la derniere rangee n'a qu'une
        # seule cellule, en colonne 0 : voir _last_row/_last_col_in_last_row).
        self._cells: list[tuple[QWidget, int, int]] = []
        n = len(SEMANTIC_COLOR_SLOTS)
        self._last_row = (n - 1) // 2
        for i, (slot, real_key, label) in enumerate(SEMANTIC_COLOR_SLOTS):
            cell = QWidget()
            cell.setAttribute(Qt.WA_StyledBackground, True)
            cell_l = QHBoxLayout(cell)
            cell_l.setContentsMargins(10, 7, 10, 7)
            cell_l.setSpacing(10)
            field = _ColorField(colors.get(real_key, "#000000"), swatch_size=24, title=label)
            cell_l.addWidget(field)
            name = QLabel(label)
            name.setFont(_qfont(11, 400))
            name.setStyleSheet(f"color: {M['row_label']}; background: transparent;")
            name.setWordWrap(False)
            cell_l.addWidget(name, 1)
            hex_label = QLabel(colors.get(real_key, ""))
            hex_label.setFont(_qfont(10, 400, mono=True))
            hex_label.setStyleSheet(f"color: {M['table_head_fg']}; background: transparent;")
            cell_l.addWidget(hex_label)
            self._fields_by_real_key.setdefault(real_key, []).append(field)
            self._hex_labels_by_real_key.setdefault(real_key, []).append(hex_label)
            field.changed.connect(lambda v, rk=real_key: self._sync_key(rk, v))
            row, col = divmod(i, 2)
            self._cells.append((cell, row, col))
            # Voir _lock_min_height : meme risque de tassement que les
            # lignes de _table_row (fenetre trop petite/pas assez de
            # place), ici sur une CELLULE de grille plutot qu'une ligne de
            # tableau — sans ca, la pastille de couleur (fixe, 24px) finit
            # par deborder du bas de sa cellule une fois celle-ci ecrasee
            # sous les ~38px qu'elle demande reellement (24 + marges 7/7),
            # recouvrant le filet de separation du bas — voir la remarque
            # de l'utilisateur, capture annotee a l'appui.
            _lock_min_height(cell)
            grid.addWidget(cell, row, col)
        self.setRadius(0)
        outer.addWidget(wrap)

    def setRadius(self, radius: int):
        """Voir _TableFrame.setRadius : le cadre exterieur (wrap, qui joue
        ici a la fois le role du cadre ET des filets entre cellules) porte
        toujours le rayon sur ses 4 coins ; seule la cellule qui occupe
        REELLEMENT un coin donne (voir self._cells) recoit ce meme rayon sur
        CE coin precis, pour ne pas laisser son angle carre depasser du
        cadre arrondi."""
        radius = max(0, int(radius))
        _apply_stylesheet_cached(self.wrap, f"background: {M['panel_border']}; border-radius: {radius}px;")
        for cell, row, col in self._cells:
            tl = radius if (row == 0 and col == 0) else 0
            tr = radius if (row == 0 and col == 1) else 0
            bl = radius if (row == self._last_row and col == 0) else 0
            br = radius if (row == self._last_row and col == 1) else 0
            _apply_stylesheet_cached(
                cell,
                f"background: {M['table_row_b']}; "
                f"border-top-left-radius: {tl}px; border-top-right-radius: {tr}px; "
                f"border-bottom-left-radius: {bl}px; border-bottom-right-radius: {br}px;",
            )

    def _sync_key(self, real_key: str, value: str):
        """Repercute un changement sur TOUTES les pastilles qui pointent
        vers la meme cle reelle (voir la remarque de tete de classe :
        selCur/button partagent "accent")."""
        for field in self._fields_by_real_key[real_key]:
            field.setValue(value)
        for label in self._hex_labels_by_real_key[real_key]:
            label.setText(value)
        self.changed.emit()

    def value(self) -> dict[str, str]:
        return {real_key: fields[0].value() for real_key, fields in self._fields_by_real_key.items()}


# ==========================================================================
# Section "Entetes" — hauteur / couleur (choisie parmi les 8 pastilles
# semantiques) / rayon des angles / cadre par cote.
# ==========================================================================

_SLOT_LABELS = {slot: label for slot, _real, label in SEMANTIC_COLOR_SLOTS}
_SLOT_REAL = {slot: real for slot, real, _label in SEMANTIC_COLOR_SLOTS}


def _resolve_color_value(value: str, colors: dict) -> str:
    """Resout une valeur de couleur qui peut etre soit un hex direct
    ("#rrggbb"), soit une reference "@<slot>" a une pastille semantique
    (voir _AppOrCustomColorField, bordures de Toggles/Sliders) — utilise
    partout ou une telle valeur doit finir en hex REEL (ex: la peinture
    d'un toggle, voir _sync_toggle_shape_style) plutot que le marqueur
    "@..." lui-meme, que QColor() ne saurait pas interpreter."""
    if isinstance(value, str) and value.startswith("@"):
        return colors.get(_SLOT_REAL.get(value[1:], "chrome"), "#000000")
    return value


def _coerce_side_enabled(value, default: bool = True) -> dict[str, bool]:
    """Normalise un reglage de bordure "activee" en dict {cote: bool} —
    accepte soit l'ancien format (un seul bool, pour tous les cotes a la
    fois — retro-compatibilite avec les presets/pipeline_settings.json
    existants), soit deja un dict {"top": bool, ...} (nouveau format, voir
    _SideColorsField/_ToggleSideColorsField et la remarque de l'utilisateur,
    "au lieu d'avoir un seul toggle pour activer les bordures, je veux un
    toggle par cote")."""
    if isinstance(value, dict):
        return {k: bool(value.get(k, default)) for k in ("top", "right", "bottom", "left")}
    v = default if value is None else bool(value)
    return {k: v for k in ("top", "right", "bottom", "left")}


def _coerce_corner_radius(value, default: int = 0) -> dict[str, int]:
    """Normalise un reglage de rayon en dict {coin: int} — accepte soit
    l'ancien format (un seul int, meme rayon pour les 4 coins — retro-
    compatibilite avec les presets/pipeline_settings.json existants), soit
    deja un dict {"top_left": int, ...} — voir _CornerRadiusField et la
    remarque de l'utilisateur, "dans tous les parametres de coins arrondis,
    je veux exactement le meme fonctionnement que les padding (un par
    coin)"."""
    if isinstance(value, dict):
        return {k: max(0, int(value.get(k, default))) for k in _CORNERS}
    v = max(0, int(value)) if value is not None else default
    return {k: v for k in _CORNERS}


class _CornerRadiusSliders(QWidget):
    """4 sliders cote a cote (Haut-Gauche/Haut-Droite/Bas-Droite/Bas-Gauche)
    — MEME mecanique que _SidePaddingField (lien PERMANENT ou transfert
    PONCTUEL du 1er coin sur les 3 autres, voir sa remarque de tete de
    classe), transposee du padding au rayon des coins — voir la remarque de
    l'utilisateur, "dans tous les parametres de coins arrondis, je veux
    exactement le meme fonctionnement que les padding (un par coin)"."""

    changed = Signal()

    _ORDER = [("top_left", "HG"), ("top_right", "HD"), ("bottom_right", "BD"), ("bottom_left", "BG")]
    _LEADER = _ORDER[0][0]
    _OTHERS = tuple(key for key, _label in _ORDER[1:])

    def __init__(self, corners: dict, minimum: int = 0, maximum: int = 40, parent=None):
        super().__init__(parent)
        self.setStyleSheet("background: transparent;")
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(12)
        self._linked = False
        self.fields: dict[str, _SliderField] = {}
        for key, letter in self._ORDER:
            wrap = QWidget()
            wrap.setStyleSheet("background: transparent;")
            wrap_l = QVBoxLayout(wrap)
            wrap_l.setContentsMargins(0, 0, 0, 0)
            wrap_l.setSpacing(3)
            tag = QLabel(letter)
            tag.setFont(_qfont(9, 600, tracking=0.5))
            tag.setStyleSheet(f"color: {M['label_dim']}; background: transparent;")
            wrap_l.addWidget(tag)
            field = _SliderField(minimum, maximum, int(corners.get(key, 0)), slider_width=60, box_width=42)
            field.valueChanged.connect(lambda _v, k=key: self._on_side_changed(k))
            self.fields[key] = field
            wrap_l.addWidget(field)
            layout.addWidget(wrap)

    def _on_side_changed(self, key: str):
        if self._linked and key == self._LEADER:
            value = self.fields[self._LEADER].value()
            for other_key in self._OTHERS:
                self.fields[other_key].setValue(value)
        self.changed.emit()

    def value(self) -> dict[str, int]:
        return {key: field.value() for key, field in self.fields.items()}

    def setValue(self, corners: dict):
        for key, field in self.fields.items():
            field.setValue(int(corners.get(key, field.value())))

    def setLinked(self, linked: bool):
        self._linked = linked
        if linked:
            value = self.fields[self._LEADER].value()
            for key in self._OTHERS:
                self.fields[key].setValue(value)
        for key in self._OTHERS:
            field = self.fields[key]
            field.setEnabled(not linked)
            effect = field.graphicsEffect()
            if not isinstance(effect, QGraphicsOpacityEffect):
                effect = QGraphicsOpacityEffect(field)
                field.setGraphicsEffect(effect)
            effect.setOpacity(0.35 if linked else 1.0)

    def setRadius(self, radius: int):
        for field in self.fields.values():
            field.setRadius(radius)

    def copyLeaderToOthers(self):
        value = self.fields[self._LEADER].value()
        for key in self._OTHERS:
            self.fields[key].setValue(value)
        self.changed.emit()


class _CornerRadiusField(QWidget):
    """Rayon des angles avec toggle "lie"/"libre" (voir _Toggle) + les 4
    sliders par coin (_CornerRadiusSliders) — "lie" : le coin Haut-Gauche
    pilote alors les 3 autres, exactement comme _CellPaddingField pour le
    padding des cellules — voir la remarque de l'utilisateur, "dans tous
    les parametres de coins arrondis, je veux exactement le meme
    fonctionnement que les padding (un par coin)"."""

    changed = Signal()

    def __init__(self, linked: bool, corners: dict, minimum: int = 0, maximum: int = 40, parent=None):
        super().__init__(parent)
        self.setStyleSheet("background: transparent;")
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(14)
        self.toggle = _Toggle(linked, on_label="lie", off_label="libre")
        self.toggle.toggled.connect(self._on_toggled)
        layout.addWidget(self.toggle)
        corner_names = {
            "top_left": "Haut-Gauche", "top_right": "Haut-Droite",
            "bottom_right": "Bas-Droite", "bottom_left": "Bas-Gauche",
        }
        leader_key, leader_letter = _CornerRadiusSliders._ORDER[0]
        self.copy_btn = _Btn(
            f"Copier {leader_letter} →", M["btn_bg"], M["btn_border"], M["btn_fg"], M["btn_hover"], height=25)
        others_full = [corner_names[k] for k in _CornerRadiusSliders._OTHERS]
        self.copy_btn.setToolTip(f"Copier la valeur de {corner_names[leader_key]} sur {'/'.join(others_full)}")
        layout.addWidget(self.copy_btn)
        self.sides = _CornerRadiusSliders(corners, minimum, maximum)
        self.sides.changed.connect(self.changed.emit)
        self.copy_btn.clicked.connect(self.sides.copyLeaderToOthers)
        layout.addWidget(self.sides)
        self.sides.setLinked(linked)
        self.copy_btn.setEnabled(not linked)

    def _on_toggled(self, checked: bool):
        self.sides.setLinked(checked)
        self.copy_btn.setEnabled(not checked)
        self.changed.emit()

    def isLinked(self) -> bool:
        return self.toggle.isChecked()

    def cornersValue(self) -> dict[str, int]:
        return self.sides.value()

    def setValue(self, linked: bool, corners: dict):
        self.toggle.setChecked(linked)
        self.sides.setValue(corners)
        self.sides.setLinked(linked)
        self.copy_btn.setEnabled(not linked)

    def setRadius(self, radius: int):
        self.sides.setRadius(radius)


class _HeaderColorField(QWidget):
    """Ligne cliquable (pastille + libelle + chevron) ouvrant un QMenu sur
    les 8 pastilles semantiques + "Personnalisee..." tout en bas (ouvre
    alors le popup HSL/RVB/hex habituel, voir _ColorPickerPopup) — une
    boite hex a droite en lecture seule affiche toujours la couleur
    resolue, quel que soit le mode — voir la remarque de l'utilisateur,
    "je veux pouvoir personnaliser la couleur" (deja possible cote
    bordures de Toggles/Sliders, voir _AppOrCustomColorField ; meme choix
    ici, transpose a ce widget bouton+chevron plutot qu'une simple
    pastille).

    Valeur stockee (voir value()/setValue()) : un nom de pastille
    semantique (INCHANGE par rapport a avant, seul format possible
    jusqu'ici — retro-compatible) OU une chaine hex "#rrggbb" (couleur
    personnalisee, nouveau) — un nom de pastille ne commence jamais par
    "#", ce prefixe suffit donc a distinguer les 2 sans marqueur dedie."""

    changed = Signal(str)

    def __init__(self, colors: dict, current_value: str, parent=None):
        super().__init__(parent)
        self._colors = colors
        self._value = current_value if (current_value in _SLOT_LABELS or current_value.startswith("#")) else "skinN1"
        self._radius = 0
        self._before_pick = self._value
        self._popup: _ColorPickerPopup | None = None
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(10)

        self.btn = QPushButton()
        self.btn.setFlat(True)
        self.btn.setCursor(Qt.ArrowCursor)
        self.btn.setFocusPolicy(Qt.NoFocus)
        self.btn.setFixedHeight(25)
        # Largeur fixe (280, meme calcul que les sliders de cette meme
        # section — voir _section_headers) : sans elle, ce bouton ne se
        # dimensionne que sur son propre texte et le controle entier ne
        # s'aligne pas avec les autres lignes du tableau Entetes.
        self.btn.setFixedWidth(280)
        self.btn.clicked.connect(self._open_menu)
        layout.addWidget(self.btn, 1)

        self.hex_box = hex_box = QWidget()
        hex_box.setObjectName("HeaderHexBox")
        hex_box.setAttribute(Qt.WA_StyledBackground, True)
        hex_box.setFixedSize(68, 25)
        hex_l = QHBoxLayout(hex_box)
        hex_l.setContentsMargins(7, 0, 7, 0)
        self.hex_label = QLabel()
        self.hex_label.setFont(_qfont(11, 400, mono=True))
        self.hex_label.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        self.hex_label.setStyleSheet(f"color: {M['value_muted']}; background: transparent;")
        hex_l.addWidget(self.hex_label)
        layout.addWidget(hex_box)
        self._refresh_style()
        self._refresh()

    def _is_custom(self) -> bool:
        return self._value.startswith("#")

    def _current_hex(self) -> str:
        if self._is_custom():
            return self._value
        return self._colors.get(_SLOT_REAL.get(self._value, "chrome"), "#000000")

    def _refresh_style(self):
        """Habillage (fond/bordure/coins) du bouton et de la boite hex — a
        part de _refresh (contenu : icone/texte/valeur), pour pouvoir suivre
        le slider Zones de saisie sans redemander la couleur courante (voir
        setRadius)."""
        self.btn.setStyleSheet(
            f"QPushButton {{ background: {M['field_bg']}; border: 1px solid {M['field_border']}; "
            f"border-radius: {self._radius}px; text-align: left; padding: 0 8px; }}"
            f"QPushButton:hover {{ border-color: {M['field_border_hover']}; }}"
        )
        self.hex_box.setStyleSheet(
            f"#HeaderHexBox {{ background: {M['field_bg']}; border: 1px solid {M['field_border']}; "
            f"border-radius: {self._radius}px; }}"
        )

    def setRadius(self, radius: int):
        self._radius = max(0, int(radius))
        self._refresh_style()

    def _refresh(self):
        hexval = self._current_hex()
        self.btn.setIcon(_solid_icon(hexval))
        self.btn.setIconSize(self.btn.iconSize())
        label = "Personnalisee" if self._is_custom() else _SLOT_LABELS.get(self._value, self._value)
        self.btn.setText("  " + label + "  ▾")
        self.hex_label.setText(hexval)

    def _open_menu(self):
        menu = QMenu(self)
        menu.setFont(_qfont(11, 400))
        menu.setStyleSheet(
            f"QMenu {{ background: {M['toolbar_bg']}; border: 1px solid {M['field_border']}; "
            f"border-radius: {self._radius}px; padding: 4px 0; }}"
            f"QMenu::item {{ padding: 5px 16px; color: {M['value_fg']}; }}"
            f"QMenu::item:selected {{ background: {M['accent']}; color: {M['accent_fg']}; }}"
            f"QMenu::separator {{ background: {M['panel_border']}; height: 1px; margin: 4px 0; }}"
        )
        for slot, _real, label in SEMANTIC_COLOR_SLOTS:
            action = menu.addAction(_solid_icon(self._colors.get(_SLOT_REAL[slot], "#000")), label)
            action.triggered.connect(lambda _c=False, s=slot: self._select(s))
        menu.addSeparator()
        custom_action = menu.addAction("Personnalisee...")
        custom_action.triggered.connect(self._open_custom_picker)
        menu.exec(self.btn.mapToGlobal(QPoint(0, self.btn.height())))

    def _select(self, slot: str):
        if slot != self._value:
            self._value = slot
            self._refresh()
            self.changed.emit(slot)

    def _open_custom_picker(self):
        self._before_pick = self._value
        popup = _ColorPickerPopup(self._current_hex(), "Couleur", self)
        self._popup = popup
        popup.colorChanged.connect(self._apply_custom_live)
        popup.committed.connect(self._apply_custom_live)
        popup.cancelled.connect(lambda: self._apply_custom_live(self._before_pick))
        popup.show_near(self.btn)

    def _apply_custom_live(self, value: str):
        self._value = value
        self._refresh()
        self.changed.emit(self._value)

    def value(self) -> str:
        return self._value

    def refresh_colors(self, colors: dict):
        """A appeler quand la page Couleurs a change une valeur — la
        pastille choisie ici doit suivre (voir SettingsWindow._on_colors_changed)."""
        self._colors = colors
        self._refresh()

    def setValue(self, value: str, colors: dict):
        """Reapplique a la fois la valeur (slot OU hex personnalise) ET la
        palette source — utilise par Valeurs par defaut / chargement d'un
        preset (voir SettingsWindow._apply_values_to_controls), qui
        doivent pouvoir changer les deux d'un coup sans emettre `changed` a
        chaque etape intermediaire."""
        self._value = value if (value in _SLOT_LABELS or value.startswith("#")) else "skinN1"
        self._colors = colors
        self._refresh()


def _solid_icon(hex_value: str):
    from PySide6.QtGui import QIcon, QPixmap
    pix = QPixmap(14, 14)
    pix.fill(QColor(hex_value))
    return QIcon(pix)


class _ColumnPreviewHeaderFill(QWidget):
    """Fond configurable de l'entete d'_ColumnPreview (Couleur/Arrondi/
    Cadre des entetes) — peint a la main (QPainter, voir _paint_bordered_
    rect) plutot que via border-radius en QSS : le moteur de style Qt
    lisse assez mal les angles arrondis des bordures QSS (surtout a rayon
    ou epaisseur variables), la ou _paint_bordered_rect (deja utilise pour
    les cadres/coches de Toggles et les rails/selecteurs de Sliders) donne
    un rendu net grace a l'antialiasing explicite de QPainter — voir la
    remarque de l'utilisateur, "le lissage des border radius est tres
    moyen, tu peux ameliorer ca ?"."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._bg = M["field_bg"]
        self._radius = _radius_dict(0)
        self._edges = {"top": False, "right": False, "bottom": False, "left": False}
        self._border_colors = {k: M["panel_border"] for k in ("top", "right", "bottom", "left")}
        self._thickness = 1
        # Cotes GAUCHE/DROIT dont les 2 coins doivent tomber a 0, quel que
        # soit `_radius` (colonnes collees, voir _ColumnPreview.
        # _corner_radii/la remarque de l'utilisateur, "si deux colonnes
        # sont cote a cote ... le rayon contre l'autre colonne doit etre a
        # zero") — sinon le coin arrondi de l'entete depasserait du cadre
        # exterieur, lui aussi aplati la a la meme frontiere.
        self._flat_left = False
        self._flat_right = False

    def setStyle(self, bg: str, radius, edges: dict, border_colors: dict | None = None, thickness: int = 1):
        self._bg = bg
        # `radius` : int (retro-compatible) OU dict {"top_left": int, ...}
        # (voir _radius_dict/_CornerRadiusField — un rayon PAR COIN, meme
        # mecanique que le padding, voir la remarque de l'utilisateur,
        # "dans tous les parametres de coins arrondis, je veux exactement
        # le meme fonctionnement que les padding").
        self._radius = _radius_dict(radius)
        self._edges = {k: bool(edges.get(k, False)) for k in ("top", "right", "bottom", "left")}
        border_colors = border_colors or {}
        self._border_colors = {k: border_colors.get(k) or M["panel_border"] for k in ("top", "right", "bottom", "left")}
        self._thickness = max(0, int(thickness))
        self.update()

    def setFlatSides(self, flat_left: bool, flat_right: bool):
        if flat_left == self._flat_left and flat_right == self._flat_right:
            return
        self._flat_left, self._flat_right = flat_left, flat_right
        self.update()

    def _corner_radii(self) -> dict:
        r = dict(self._radius)
        if self._flat_left:
            r["top_left"] = 0
            r["bottom_left"] = 0
        if self._flat_right:
            r["top_right"] = 0
            r["bottom_right"] = 0
        return r

    def paintEvent(self, event):
        p = QPainter(self)
        radius = self._corner_radii()
        p.setRenderHint(QPainter.Antialiasing, _radius_any(radius))
        _paint_bordered_rect(p, self.rect(), radius, self._edges, self._thickness, self._border_colors, self._bg)
        p.end()


class _ColumnPreview(QWidget):
    """Apercu d'une colonne du navigateur principal (150x250 fixe, voir la
    remarque de l'utilisateur — "deux colonnes cote a cote de 150px chacune
    de large et 250px de hauteur") pour Colonnes > l'apercu au-dessus de
    son tableau de reglages (voir _section_preview_wrap/SettingsWindow.
    _section_headers) — reproduit la structure REELLE d'une colonne (voir
    pipeline_browser.Column.__init__ : header_fill inset de header_padding
    dans une bande de header_height, voir aussi app_style.header_qss) pour
    suivre fidelement Hauteur/Padding/Couleur/Arrondi/Cadre des entetes EN
    DIRECT plutot qu'une re-interpretation approximative.

    Cadre exterieur ET header_fill (voir _ColumnPreviewHeaderFill) sont
    tous les 2 peints a la main (paintEvent/QPainter), PAS via une
    border-radius QSS — voir la remarque de l'utilisateur, "le lissage des
    border radius est tres moyen"."""

    _WIDTH = 150
    _HEIGHT = 250

    def __init__(self, title: str = "Type", count: str = "12", has_left_neighbor: bool = True,
                 has_right_neighbor: bool = True, parent=None):
        super().__init__(parent)
        self.setObjectName("ColumnPreview")
        # Transparent EXPLICITE (meme piege/correctif recurrent que
        # _ItemPreviewRow etc. — voir son commentaire) : sans lui, ce
        # QWidget nu heriterait du fond OPAQUE par defaut de la feuille de
        # style globale, masquant le fond du PANNEAU derriere la colonne
        # la ou Padding (voir setPadding) fait maintenant RETRECIR le fond
        # peint de la colonne elle-meme (M['field_bg'], voir paintEvent) en
        # dessous de la taille pleine de ce widget — voir la remarque de
        # l'utilisateur, "je veux que le fond de la colonne se replie".
        self.setStyleSheet("background: transparent;")
        self._column_padding = {"top": 0, "right": 0, "bottom": 0, "left": 0}
        # Fond de CETTE boite (voir paintEvent/setFillColor) : valeur de
        # depart M['field_bg'] (chrome de LA FENETRE de parametres, sans
        # rapport avec les couleurs REGLABLES de l'appli) — remplace des le
        # 1er appel de SettingsWindow._apply_column_preview par la couleur
        # LIVE reellement utilisee par la vraie colonne (C['void'], voir
        # app_style.Column.refresh_colors/"skin - niveau2") — voir la
        # remarque de l'utilisateur, "la couleur de fond de colonne est
        # fausse dans l'apercu" : elle suivait jusqu'ici le theme de CETTE
        # fenetre plutot que la palette Couleurs reglee par l'utilisateur.
        self._fill_color = M["field_bg"]
        # Fond DISTINCT du panneau qui l'entoure (M['well'], pas M['panel_
        # bg']) + un filet tout autour : sans ca, le CORPS de la colonne
        # (tout ce qui n'est pas la bande d'entete) se confondait
        # entierement avec le fond de la section — l'apercu semblait vide
        # (juste la bande d'entete, discrete par defaut) au lieu de montrer
        # visiblement les dimensions/la forme d'une colonne — voir la
        # remarque de l'utilisateur, "l'apercu ne fonctionne pas du tout".
        #
        # `has_left_neighbor` (False seulement pour la 1ere boite de la
        # rangee, voir SettingsWindow._section_headers) : le filet GAUCHE ne
        # se masque QUE si cette boite touche reellement une autre boite de
        # ce cote (voir setSeamHidden) — meme repartition que Column.
        # border-right TOUJOURS peint vs DetailPanel.border-left
        # CONDITIONNEL (voir app_style.column_seam_border) : a chaque
        # frontiere entre 2 boites voisines, un SEUL filet reste visible
        # (celui de DROITE de la boite de gauche) plutot que 2 cumules —
        # voir la remarque de l'utilisateur, "je veux que les deux
        # bordures qui se chevauchent n'en forment qu'une seule". Le filet
        # DROIT n'est JAMAIS masque ni sa marge compensee (une precedente
        # version le faisait aussi cote droit "pour equilibrer les
        # largeurs" : le filet droit restait bel et bien peint, mais
        # header_fill s'etendait alors PAR-DESSUS lui, le rendant invisible
        # pile a la hauteur de l'entete tout en le laissant visible plus
        # bas dans le corps — voir la remarque de l'utilisateur, "pourquoi
        # il n'y a pas de bordure entre les deux premieres entetes ?" —
        # d'ou la regle stricte "seul le cote dont le filet DISPARAIT
        # vraiment recupere de la marge").
        #
        # Sans voisine a gauche, la 1ere boite garde donc TOUJOURS ses 2
        # filets (gauche ET droit) — voir la remarque de l'utilisateur, "du
        # coup on perd la bordure a gauche de la premiere colonne" — alors
        # que ses voisines fusionnees n'en gardent qu'un : ELARGIE de 1px
        # (voir _refresh_frame) quand column_gap()<=0 pour compenser, afin
        # que son bandeau colore reste quand meme aussi large que les
        # leurs (meme largeur "de bordure a bordure") — voir la remarque de
        # l'utilisateur, "la colonne 1 fait 148px de large ... alors que
        # les autres font 149".
        self._has_left_neighbor = has_left_neighbor
        # `has_right_neighbor` (False seulement pour la DERNIERE boite de la
        # rangee) : cote DROIT jamais masque (voir plus haut), mais ses 2
        # coins doivent quand meme s'aplatir quand ce cote touche une autre
        # boite (gap<=0) — voir _corner_radii/la remarque de l'utilisateur,
        # "si deux colonnes sont cote a cote, a zero pixels d'intervalle,
        # le rayon de bordure contre l'autre colonne doit etre a zero".
        self._has_right_neighbor = has_right_neighbor
        self._seam_active = False
        # Bordure configurable (Colonnes > Bordure, voir _ToggleSideColorsField/
        # setBorder) : valeurs de depart = l'ancien filet gris fixe codee en
        # dur ici (M['panel_border']), pour ne rien changer visuellement tant
        # que SettingsWindow._apply_column_preview n'a pas encore rejoue les
        # reglages reels (1er appel, voir __init__ plus bas). enabled = dict
        # {cote: bool} (pas un bool unique, voir la remarque de
        # l'utilisateur, "un toggle par cote").
        self._border_enabled = {k: True for k in ("top", "right", "bottom", "left")}
        self._border_colors = {k: M["panel_border"] for k in ("top", "right", "bottom", "left")}
        self._border_thickness = 1
        self._border_radius = _radius_dict(0)
        self._refresh_frame()
        outer_layout = self._outer_layout = QVBoxLayout(self)
        outer_layout.setSpacing(0)
        self._refresh_content_margins()
        # header_band (hauteur = header_height) > header_fill (inset de
        # header_padding sur les 4 cotes) : MEME imbrication que la vraie
        # colonne (voir header_outer_layout/header_fill dans Column).
        self.header_band = QWidget()
        self.header_band.setStyleSheet("background: transparent;")
        self.header_band.setFixedHeight(26)
        header_outer_layout = QHBoxLayout(self.header_band)
        header_outer_layout.setContentsMargins(0, 0, 0, 0)
        self.header_fill = _ColumnPreviewHeaderFill()
        self.header_fill.setObjectName("ColumnPreviewHeader")
        # Libelle + compteur, MEME disposition que le vrai header_layout
        # d'une colonne (voir pipeline_browser.Column.__init__ : title_
        # label a gauche, count_label a droite, marges 10/0/10/0) — voir la
        # remarque de l'utilisateur, "ajoute les entetes de colonne dans
        # l'apercu" (jusqu'ici juste une bande coloree, sans texte).
        self.header_fill_layout = QHBoxLayout(self.header_fill)
        self.header_fill_layout.setContentsMargins(10, 0, 10, 0)
        header_fill_layout = self.header_fill_layout
        self.title_label = QLabel(title.upper())
        self.title_label.setFont(_qfont(10, 600, tracking=0.9))
        self.title_label.setStyleSheet(f"color: {M['table_head_fg']}; background: transparent;")
        header_fill_layout.addWidget(self.title_label)
        header_fill_layout.addStretch(1)
        self.count_label = QLabel(count)
        self.count_label.setFont(_qfont(10, 400))
        self.count_label.setStyleSheet(f"color: {M['value_muted']}; background: transparent;")
        header_fill_layout.addWidget(self.count_label)
        header_outer_layout.addWidget(self.header_fill)
        outer_layout.addWidget(self.header_band)
        # Corps : 4 lignes de demonstration (Normal/Survol/Selection en
        # focus/Selection hors focus, voir _ItemPreviewRow) — l'apercu
        # d'Items > Texte/Selection se fait ICI, sur les colonnes de
        # demonstration DEJA existantes (Type/Projets/Sous-projet), plutot
        # que sur un widget d'apercu separe — voir la remarque de
        # l'utilisateur, "l'apercu doit se faire sur les colonnes deja
        # existantes".
        self.body = QWidget()
        self.body.setStyleSheet("background: transparent;")
        self.body_layout = QVBoxLayout(self.body)
        self.body_layout.setContentsMargins(0, 0, 0, 0)
        self.body_layout.setSpacing(0)
        self.item_rows: list[_ItemPreviewRow] = []
        for row_text in ("Normal.txt", "Survol.txt", "Selection (focus).txt", "Selection (hors focus).txt"):
            row = _ItemPreviewRow(row_text)
            self.body_layout.addWidget(row)
            self.item_rows.append(row)
        outer_layout.addWidget(self.body)
        outer_layout.addStretch(1)
        self._refresh_seam_margin()
        self._refresh_header_flat_sides()

    def refresh(self, height: int, padding: int, hexval: str, radius: int, edges: dict,
                border_colors: dict | None = None, border_thickness: int = 1):
        self.header_band.setFixedHeight(max(1, int(height)))
        self._padding = max(0, int(padding))
        self._refresh_seam_margin()
        self.header_fill.setStyle(hexval, radius, edges, border_colors, border_thickness)

    def setPadding(self, padding: dict):
        """Colonnes > Colonnes > Padding, PAR COTE (voir _CellPaddingField
        — meme widget que Tableaux > Padding des cellules/Items >
        Selection > Padding du selecteur) — fait RETRECIR la colonne
        ENTIERE (fond + bordure, pas seulement son contenu) de ce nombre
        de px sur chaque cote choisi, revelant le fond du PANNEAU en
        dessous tout autour (une "carte flottante" a l'interieur de
        l'emplacement alloue a la colonne) — voir la remarque de
        l'utilisateur, "je veux que les parametres de padding interviennent
        sur la colonne en elle meme, pas son contenu ... je veux que le
        fond de la colonne se replie" (PAS un simple retrait du CONTENU
        dans un cadre reste a taille fixe, un 1er essai corrige suite a
        cette remarque). Le cadre exterieur peint par paintEvent (voir
        _corner_radii/setBorder) ET le contenu (bande d'entete + corps,
        voir header_band/self.body, via self._outer_layout) suivent tous
        les 2 ce MEME retrait — voir paintEvent, qui peint desormais sur
        `self._padded_rect()`, plus sur `self.rect()`."""
        # self._column_padding (PAS self._padding — deja pris par refresh()
        # ci-dessus, l'INT du padding des ENTETES, lu par
        # _refresh_seam_margin) : un dict, 4 cotes.
        self._column_padding = {side: max(0, int(padding.get(side, 0))) for side in ("top", "right", "bottom", "left")}
        self._refresh_content_margins()
        self.update()

    def _refresh_content_margins(self):
        """Espace reserve, en PLUS du padding, entre le cadre EXTERIEUR
        peint par paintEvent et le contenu (header_band + body, tous 2
        a fond OPAQUE) — pour l'epaisseur de bordure REELLEMENT peinte sur
        CE cote : sans ca, le contenu recouvrait le filet la ou il passe
        DERRIERE lui (l'entete, notamment) alors que le padding le
        revelait deja correctement tout autour — voir la remarque de
        l'utilisateur, capture a l'appui, "pourquoi la bordure disparait
        derriere l'entete". MEME necessite/MEME calcul (reserve()) que
        pipeline_browser.Column.refresh_header, qui l'a deja pour la
        vraie colonne — cote GAUCHE seul conditionne par le seam (voir
        paintEvent, MEME regle : filet gauche non peint si fusionne avec
        la voisine)."""
        t = self._border_thickness

        def reserve(side_on: bool) -> int:
            return t if side_on else 0

        left_on = self._border_enabled["left"] and not (self._seam_active and self._has_left_neighbor)
        p = self._column_padding
        self._outer_layout.setContentsMargins(
            p["left"] + reserve(left_on), p["top"] + reserve(self._border_enabled["top"]),
            p["right"] + reserve(self._border_enabled["right"]), p["bottom"] + reserve(self._border_enabled["bottom"]),
        )

    def _padded_rect(self) -> QRect:
        p = self._column_padding
        return self.rect().adjusted(p["left"], p["top"], -p["right"], -p["bottom"])

    def setItemStyle(self, *, font_family: str, color_hex: str, icon_enabled: bool, row_height: int,
                      row_spacing: int, text_padding: int, hover_color: str, focus_color: str,
                      unfocus_color: str, padding: dict, enabled: dict, colors: dict, radius: int,
                      edge_border: bool):
        """Items > Texte/Selection (voir SettingsWindow._apply_item_preview)
        — voir sa remarque de tete de classe, "l'apercu doit se faire sur
        les colonnes deja existentes" : les 4 lignes de demonstration
        vivent ICI (self.item_rows), pas dans un widget d'apercu a part."""
        self.body_layout.setSpacing(max(0, int(row_spacing)))
        for row in self.item_rows:
            row.setRowStyle(font_family, color_hex, icon_enabled, row_height, text_padding)
        sel_colors = (None, hover_color, focus_color, unfocus_color)
        for row, sel_color in zip(self.item_rows, sel_colors):
            row.setSelectionStyle(sel_color, padding, enabled, colors, radius, edge_border)
        # 2 lignes selectionnees adjacentes (voir la remarque de
        # l'utilisateur, "comme les lignes de colonne, quand deux lignes
        # selectionnees sont cote a cote, la bordure entre les deux doit
        # etre visible, et de la valeur d'epaisseur choisie (pas le
        # double)") : leurs 2 pastilles ne se touchent VRAIMENT que sans
        # espacement de ligne NI padding vertical (sinon un vrai espace les
        # separe deja, rien a fusionner) — dans ce cas, celle du DESSUS
        # garde son filet BAS (jamais masque, comme le filet DROIT
        # d'_ColumnPreview entre 2 colonnes), celle du DESSOUS perd son
        # filet HAUT (voir _ItemPreviewRow.setSeamTop) : un SEUL filet
        # reste visible a la frontiere plutot que 2 cumules en 2x
        # l'epaisseur choisie. LE RAYON, lui, s'aplatit des DEUX cotes
        # (voir setSeamBottom en plus de setSeamTop) : contrairement au
        # filet (ou UN seul suffit), un coin arrondi restant sur L'UN des 2
        # laisserait un residu a la jointure meme si son filet est correct
        # — voir la remarque de l'utilisateur, capture a l'appui, "le
        # probleme des bordures qui apparaissent mal ... est toujours
        # present".
        touching = int(row_spacing) <= 0 and int(padding.get("top", 0)) <= 0 and int(padding.get("bottom", 0)) <= 0
        for prev_row, row in zip(self.item_rows, self.item_rows[1:]):
            seam = touching and prev_row._sel_color is not None and row._sel_color is not None
            row.setSeamTop(seam)
            prev_row.setSeamBottom(seam)

    def setSeamHidden(self, hidden: bool):
        """Distance entre colonnes > SettingsWindow._apply_column_preview :
        masque (si `hidden`, et si has_left_neighbor — voir __init__) le
        filet gauche — MEME comportement que le vrai navigateur (voir
        app_style.column_seam_border/pipeline_browser.Column)."""
        if hidden == self._seam_active:
            return
        self._seam_active = hidden
        self._refresh_frame()
        self._refresh_seam_margin()
        self._refresh_header_flat_sides()
        self._refresh_content_margins()

    def _corner_radii(self) -> dict:
        """Rayon PAR COIN du cadre exterieur : le(s) coin(s) du cote qui
        touche reellement une autre boite (gap<=0 ET has_left_neighbor/
        has_right_neighbor, voir __init__) retombent a 0 — voir la remarque
        de l'utilisateur, "si deux colonnes sont cote a cote, a zero pixels
        d'intervalle, le rayon de bordure contre l'autre colonne doit etre
        a zero" (sinon le coin arrondi depasserait dans le filet unique de
        la frontiere, ou laisserait un residu de fond visible a travers)."""
        r = self._border_radius
        flat_left = self._seam_active and self._has_left_neighbor
        flat_right = self._seam_active and self._has_right_neighbor
        return {
            "top_left": 0 if flat_left else r["top_left"],
            "bottom_left": 0 if flat_left else r["bottom_left"],
            "top_right": 0 if flat_right else r["top_right"],
            "bottom_right": 0 if flat_right else r["bottom_right"],
        }

    def _refresh_header_flat_sides(self):
        """Repercute le meme aplatissement sur les coins du fond d'entete
        (voir _ColumnPreviewHeaderFill.setFlatSides) ET des pastilles de
        selection de chaque ligne (voir _ItemPreviewRow.setFlatSides) — sans
        ca, l'entete ET/OU la selection garderaient un coin arrondi
        depassant du cadre exterieur, lui, deja aplati a la meme frontiere
        — voir la remarque de l'utilisateur, capture annotee a l'appui,
        "les bordures ne se font pas tres bien de partout"."""
        flat_left = self._seam_active and self._has_left_neighbor
        flat_right = self._seam_active and self._has_right_neighbor
        self.header_fill.setFlatSides(flat_left, flat_right)
        for row in self.item_rows:
            row.setFlatSides(flat_left, flat_right)

    def _refresh_seam_margin(self):
        """Quand le filet gauche est masque (voir setSeamHidden), Qt ne
        recupere PAS automatiquement ce pixel pour le contenu interne. Le
        filet qui disparait est celui peint par _refresh_frame sur `self`
        (le cadre EXTERIEUR de l'apercu, colle contre header_band puisque
        outer_layout n'a aucune marge) — c'est donc la marge GAUCHE de
        header_band (= Padding des entetes, header_padding_field) qui doit
        recuperer ce pixel, PAS celle de header_fill_layout (le texte
        titre/compteur, imbrique un niveau plus profond, une frontiere
        differente qui ne borde jamais le filet exterieur) — voir la
        remarque de l'utilisateur, "il y a un espace entre l'entete et la
        colonne precedente" (le meme fix que pipeline_browser.DetailPanel.
        refresh_seam_margin, mais applique a la bonne marge cette fois).
        La marge DROITE, elle, ne bouge JAMAIS : son filet ne disparait
        jamais non plus (voir _refresh_frame) — la compenser quand meme
        (une precedente version le faisait, "pour equilibrer les largeurs")
        etendait header_fill PAR-DESSUS ce filet toujours peint, le
        rendant invisible pile a la hauteur de l'entete tout en le
        laissant visible plus bas dans le corps — voir la remarque de
        l'utilisateur, "pourquoi il n'y a pas de bordure entre les deux
        premieres entetes ?". Sans voisine a gauche (has_left_neighbor
        False), le filet gauche ne disparait jamais non plus : c'est
        _refresh_frame qui elargit alors la boite de 1px pour compenser,
        pas cette marge — voir sa remarque."""
        m = getattr(self, "_padding", 0)
        left = max(0, m - 1) if (self._seam_active and self._has_left_neighbor) else m
        self.header_band.layout().setContentsMargins(left, m, m, m)

    def setBorder(self, enabled: dict, colors: dict, thickness: int = 1, radius=0):
        """Colonnes > Bordure (voir _ToggleSideColorsField, MEME widget que
        Toggles > Cadre/Coche > Bordure) : remplace le filet gris fixe
        d'origine par un interrupteur PAR COTE (voir la remarque de
        l'utilisateur, "au lieu d'avoir un seul toggle pour activer les
        bordures, je veux un toggle par cote") + une couleur par cote +
        epaisseur partagee + un rayon PAR COIN (voir _radius_dict/
        _CornerRadiusField, meme mecanique que le padding — la remarque de
        l'utilisateur, "dans tous les parametres de coins arrondis, je veux
        exactement le meme fonctionnement que les padding (un par coin)")."""
        self._border_enabled = {k: bool(enabled.get(k, True)) for k in ("top", "right", "bottom", "left")}
        self._border_colors = {k: colors.get(k) or M["panel_border"] for k in ("top", "right", "bottom", "left")}
        self._border_thickness = max(0, int(thickness))
        self._border_radius = _radius_dict(radius)
        self._refresh_content_margins()
        self._refresh_frame()

    def _refresh_frame(self):
        # Sans voisine a gauche (1ere boite de la rangee), le filet gauche
        # reste TOUJOURS peint (voir __init__, la remarque de l'utilisateur
        # "on perd la bordure a gauche de la premiere colonne") : elle
        # garde donc ses 2 filets alors que ses voisines fusionnees n'en
        # gardent qu'un — ELARGIE de 1px ici (150 -> 151, uniquement quand
        # column_gap()<=0) pour que son bandeau colore reste quand meme
        # aussi large que le leur (header_band suit automatiquement, voir
        # __init__ : il occupe toute la largeur de self via outer_layout,
        # sans marge) — voir la remarque de l'utilisateur, "la colonne 1
        # fait 148px de large ... alors que les autres font 149".
        grow = 1 if (self._seam_active and not self._has_left_neighbor) else 0
        self.setFixedSize(self._WIDTH + grow, self._HEIGHT)
        self.update()

    def setFillColor(self, hexval: str):
        """Fond REEL de la colonne (voir __init__/paintEvent) — appele avec
        la couleur LIVE C['void'] resolue (voir SettingsWindow.
        _apply_column_preview) a chaque rafraichissement de l'apercu, pour
        suivre la palette Couleurs reglee par l'utilisateur plutot qu'un
        chrome fixe de cette fenetre."""
        if hexval == self._fill_color:
            return
        self._fill_color = hexval
        self.update()

    def paintEvent(self, event):
        """Cadre exterieur peint a la main (QPainter, voir _paint_bordered_
        rect) plutot que via une border-radius QSS — voir la remarque de
        l'utilisateur, "le lissage des border radius est tres moyen"."""
        p = QPainter(self)
        radius = self._corner_radii()
        p.setRenderHint(QPainter.Antialiasing, _radius_any(radius))
        sides = dict(self._border_enabled)
        if self._seam_active and self._has_left_neighbor:
            sides["left"] = False
        _paint_bordered_rect(
            p, self._padded_rect(), radius, sides, self._border_thickness,
            self._border_colors, self._fill_color,
        )
        p.end()


class _ItemPreviewRow(QWidget):
    """Une ligne de la liste (icone optionnelle + texte) avec sa pastille de
    selection (fond/bordure/rayon/padding, peinte a la main — QPainter, voir
    _paint_bordered_rect) — utilisee par _ItemRowPreview pour demontrer les
    4 etats (Normal/Survol/Selection en focus/Selection hors focus) de
    Items > l'apercu, voir la remarque de l'utilisateur, "ajoute un tableau
    pour les items textes dans les colonnes"."""

    def __init__(self, text: str, parent=None):
        super().__init__(parent)
        # Fond transparent EXPLICITE : meme piege/correctif que
        # _SidePaddingField (voir son commentaire) — sans lui, ce QWidget nu
        # se voit quand meme peint d'un fond OPAQUE (le style sheet global
        # de l'appli active WA_StyledBackground implicitement sur tout
        # QWidget), masquant a la fois le fond de _ColumnPreview ENTRE les
        # lignes (visible normalement au travers de "Espacement entre les
        # lignes") ET le filet exterieur de la colonne (peint par le PARENT,
        # _ColumnPreview.paintEvent, recouvert par cette ligne des qu'elle
        # touche son bord gauche/droit) — voir la remarque de l'utilisateur,
        # capture annotee a l'appui, "pourquoi la ligne ne va pas jusqu'au
        # bout"/"pourquoi cet espace alors que le parametre 'distance entre
        # les lignes' est a 0".
        self.setStyleSheet("background: transparent;")
        self._sel_color: str | None = None
        self._sel_padding = {"top": 0, "right": 0, "bottom": 0, "left": 0}
        self._sel_enabled = {"top": False, "right": False, "bottom": False, "left": False}
        self._sel_colors = {k: M["panel_border"] for k in ("top", "right", "bottom", "left")}
        self._sel_radius = _radius_dict(0)
        self._edge_border = True
        # Cotes GAUCHE/DROIT dont les 2 coins de la SELECTION doivent tomber
        # a 0, quel que soit leur rayon regle (colonnes collees, voir
        # _ColumnPreview._corner_radii/setFlatSides — MEME mecanique que le
        # cadre exterieur et le fond d'entete) : sans ca, le rayon de la
        # pastille de selection laisse un residu de fond visible NON
        # colore au coin qui touche le filet unique fusionne entre 2
        # colonnes — voir la remarque de l'utilisateur, capture annotee a
        # l'appui, "les bordures ne se font pas tres bien de partout".
        self._flat_left = False
        self._flat_right = False
        # Filet HAUT force a "none" quand cette ligne touche une AUTRE
        # ligne selectionnee juste au-dessus (padding vertical a 0, voir
        # _ColumnPreview.setItemStyle) — meme mecanique que le filet gauche
        # d'_ColumnPreview lui-meme entre 2 colonnes collees (voir
        # _refresh_frame/has_left_neighbor) : celle du DESSUS garde son
        # filet BAS (jamais masque), celle du DESSOUS perd son filet HAUT,
        # pour qu'un SEUL filet reste visible a la frontiere plutot que 2
        # cumules — voir la remarque de l'utilisateur, "comme les lignes de
        # colonne, quand deux lignes selectionnees sont cote a cote, la
        # bordure entre les deux doit etre visible, et de la valeur
        # d'epaisseur choisie (pas le double)".
        self._seam_top = False
        # Symetrique de _seam_top, cote de la ligne du DESSUS (voir
        # setSeamBottom) : le FILET bas, lui, reste TOUJOURS peint (comme
        # le filet droit d'_ColumnPreview entre 2 colonnes — un SEUL filet
        # suffit), mais le RAYON bas doit lui aussi s'aplatir cote colle —
        # sinon son propre coin arrondi (independant de celui, deja
        # aplati, de la ligne du dessous) laisse un residu en triangle a
        # la frontiere — voir la remarque de l'utilisateur, capture a
        # l'appui, "le probleme des bordures qui apparaissent mal dans les
        # textes selectionnes est toujours present".
        self._seam_bottom = False
        layout = QHBoxLayout(self)
        layout.setContentsMargins(8, 0, 8, 0)
        layout.setSpacing(8)
        self.icon_box = QWidget()
        self.icon_box.setFixedSize(14, 14)
        self.icon_box.setStyleSheet(f"background: transparent; border: 1px solid {M['label_dim']};")
        layout.addWidget(self.icon_box)
        self.label = QLabel(text)
        self.label.setStyleSheet("background: transparent;")
        layout.addWidget(self.label, 1)

    def setRowStyle(self, font_family: str, color_hex: str, icon_enabled: bool, row_height: int, text_padding: int):
        self.setFixedHeight(max(1, int(row_height)))
        self.icon_box.setVisible(bool(icon_enabled))
        self.label.setFont(QFont(font_family, 10) if font_family else _qfont(10, 400))
        self.label.setStyleSheet(f"color: {color_hex}; background: transparent;")
        pad = max(0, int(text_padding))
        self.layout().setContentsMargins(pad, 0, pad, 0)

    def setSelectionStyle(self, sel_color: str | None, padding: dict, enabled: dict, colors: dict,
                           radius, edge_border: bool):
        self._sel_color = sel_color
        self._sel_padding = padding
        self._sel_enabled = enabled
        self._sel_colors = colors
        self._sel_radius = _radius_dict(radius)
        self._edge_border = edge_border
        self.update()

    def setSeamTop(self, seam_top: bool):
        """Voir __init__ : masque le filet HAUT de la selection quand la
        ligne au-dessus est ELLE AUSSI selectionnee et les touche (padding
        vertical a 0) — appelee par _ColumnPreview.setItemStyle, jamais
        directement depuis le tableau de reglages."""
        seam_top = bool(seam_top)
        if seam_top == self._seam_top:
            return
        self._seam_top = seam_top
        self.update()

    def setSeamBottom(self, seam_bottom: bool):
        """Voir __init__ : aplatit (mais NE masque PAS son filet, qui reste
        l'unique filet visible a cette frontiere) le RAYON bas de la
        selection quand la ligne EN DESSOUS est ELLE AUSSI selectionnee et
        la touche — appelee par _ColumnPreview.setItemStyle, jamais
        directement depuis le tableau de reglages."""
        seam_bottom = bool(seam_bottom)
        if seam_bottom == self._seam_bottom:
            return
        self._seam_bottom = seam_bottom
        self.update()

    def setFlatSides(self, flat_left: bool, flat_right: bool):
        """Voir __init__ : aplatit les 2 coins gauche (ou droit) de la
        SELECTION quand ce cote touche le filet unique fusionne entre 2
        colonnes — appelee par _ColumnPreview, jamais directement depuis le
        tableau de reglages."""
        flat_left, flat_right = bool(flat_left), bool(flat_right)
        if flat_left == self._flat_left and flat_right == self._flat_right:
            return
        self._flat_left, self._flat_right = flat_left, flat_right
        self.update()

    def _effective_radius(self) -> dict:
        """Aplatit un coin QUE si son cote touche VRAIMENT le filet fusionne
        de la colonne (flat_left/flat_right, voir setFlatSides) ET que la
        selection elle-meme est flush de ce cote (padding a 0) — sans cette
        2e condition, un padding non nul (ex. "Padding du selecteur" G=7,
        la selection inset, PAS collee au bord) aplatissait quand meme le
        coin a tort : la boite du MILIEU (qui touche un filet fusionne des
        2 cotes) se retrouvait entierement carree meme cote gauche, avec
        7px d'espace bien visible avant le filet — voir la remarque de
        l'utilisateur, capture a l'appui, "qu'est-ce que tu as fait avec
        les angles ??"."""
        r = dict(self._sel_radius)
        pad = self._sel_padding
        left_flush = max(0, int(pad.get("left", 0))) <= 0
        right_flush = max(0, int(pad.get("right", 0))) <= 0
        if self._flat_left and left_flush:
            r["top_left"] = 0
            r["bottom_left"] = 0
        if self._flat_right and right_flush:
            r["top_right"] = 0
            r["bottom_right"] = 0
        # Symetrique de flat_left/flat_right, mais pour la frontiere avec la
        # ligne du dessus/dessous (voir setSeamTop/setSeamBottom) : LES 2
        # cotes de la frontiere doivent aplatir leur rayon (pas seulement
        # celui dont le filet disparait) — sinon un coin arrondi restant
        # sur L'UN des 2 (meme si son filet, lui, est bien masque/garde
        # correctement) laisse un residu en triangle a la jointure, voir la
        # remarque de l'utilisateur, "le probleme des bordures qui
        # apparaissent mal dans les textes selectionnes est toujours
        # present".
        if self._seam_top:
            r["top_left"] = 0
            r["top_right"] = 0
        if self._seam_bottom:
            r["bottom_left"] = 0
            r["bottom_right"] = 0
        return r

    def paintEvent(self, event):
        if self._sel_color:
            p = QPainter(self)
            rect = self.rect()
            pad = self._sel_padding
            sel_rect = QRect(
                rect.left() + max(0, int(pad.get("left", 0))), rect.top() + max(0, int(pad.get("top", 0))),
                rect.width() - max(0, int(pad.get("left", 0))) - max(0, int(pad.get("right", 0))),
                rect.height() - max(0, int(pad.get("top", 0))) - max(0, int(pad.get("bottom", 0))),
            )
            # "Bordure au bord de la colonne" (`_edge_border`) ne concerne
            # QUE gauche/droite — les 2 seuls cotes qui peuvent vraiment
            # toucher le bord de la COLONNE (padding a 0 = filet colle au
            # bord gauche/droit de la colonne) : un cote "a plat" LA ne
            # garde son filet que si `edge_border` est actif — voir la
            # remarque de l'utilisateur, "toggle 1 pour bordure ou non au
            # croisement entre la selection et le bord de la colonne".
            # Haut/bas, EUX, ne touchent jamais "le bord de la colonne" —
            # juste la ligne voisine — et suivent donc TOUJOURS l'
            # interrupteur par cote tel quel, quel que soit leur padding ;
            # seule la fusion avec une ligne selectionnee adjacente (voir
            # setSeamTop) peut masquer le HAUT — voir la remarque de
            # l'utilisateur, capture a l'appui, "pour chaque ligne a
            # selection, la bordure devrait apparaitre en bas et en haut
            # ... et pas a droite" (elle disparaissait a tort en haut/bas
            # aussi des que leur padding tombait a 0).
            enabled = {side: bool(self._sel_enabled.get(side, False)) for side in ("top", "right", "bottom", "left")}
            for side in ("left", "right"):
                flush = max(0, int(pad.get(side, 0))) <= 0
                if flush and not self._edge_border:
                    enabled[side] = False
            if self._seam_top:
                enabled["top"] = False
            radius = self._effective_radius()
            p.setRenderHint(QPainter.Antialiasing, _radius_any(radius))
            _paint_bordered_rect(p, sel_rect, radius, enabled, 1, self._sel_colors, self._sel_color)
            p.end()
        super().paintEvent(event)


class _EdgeBar(QWidget):
    """Un des 4 filets cliquables de _EdgeBox (haut/droite/bas/gauche)."""

    clicked = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._on = False
        self.setCursor(Qt.PointingHandCursor)

    def setOn(self, on: bool):
        if on != self._on:
            self._on = on
            self.update()

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            self.clicked.emit()

    def paintEvent(self, event):
        p = QPainter(self)
        p.fillRect(self.rect(), QColor(M["accent"] if self._on else M["edge_off"]))
        p.end()


class _EdgeBox(QWidget):
    """Rectangle en pointilles (92x52) representant l'entete, avec ses 4
    cotes cliquables — voir _HeaderEdgesField pour la synchronisation avec
    la liste de cases a cocher juxtaposee."""

    changed = Signal(str)   # emet le cote qui vient de changer

    def __init__(self, edges: dict, parent=None):
        super().__init__(parent)
        self.setFixedSize(92, 52)
        self.setAttribute(Qt.WA_StyledBackground, True)
        self._refresh_style()
        label = QLabel("entete", self)
        label.setFont(_qfont(9, 400, mono=True))
        label.setStyleSheet(f"color: {M['edge_hint']}; background: transparent;")
        label.adjustSize()
        label.move((92 - label.width()) // 2, (52 - label.height()) // 2)
        self.bars: dict[str, _EdgeBar] = {}
        for name in ("top", "right", "bottom", "left"):
            bar = _EdgeBar(self)
            bar.setOn(bool(edges.get(name, False)))
            bar.clicked.connect(lambda n=name: self._toggle(n))
            self.bars[name] = bar
        self.bars["top"].setGeometry(0, 0, 92, 3)
        self.bars["bottom"].setGeometry(0, 49, 92, 3)
        self.bars["left"].setGeometry(0, 0, 3, 52)
        self.bars["right"].setGeometry(89, 0, 3, 52)

    def _refresh_style(self):
        self.setStyleSheet(f"background: {M['field_bg']}; border: 1px dashed {M['panel_border']};")

    def _toggle(self, name: str):
        bar = self.bars[name]
        bar.setOn(not bar._on)
        self.changed.emit(name)

    def value(self) -> dict[str, bool]:
        return {name: bar._on for name, bar in self.bars.items()}

    def setValue(self, edges: dict):
        for name, bar in self.bars.items():
            bar.setOn(bool(edges.get(name, False)))

    def refresh_colors(self):
        self._refresh_style()


class _EdgeCheckItem(QWidget):
    """Une ligne de la liste 2x2 (case + libelle) — toute la ligne est
    cliquable, pas seulement la case (voir _CheckSquare.WA_TransparentFor
    MouseEvents : la case est purement decorative ici)."""

    clicked = Signal()

    def __init__(self, label: str, on: bool, parent=None):
        super().__init__(parent)
        self.setCursor(Qt.PointingHandCursor)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(7)
        self.box = _CheckSquare(on)
        layout.addWidget(self.box)
        self.text = QLabel(label)
        self.text.setFont(_qfont(11, 400))
        layout.addWidget(self.text, 1)
        self._refresh_label(on)

    def _refresh_label(self, on: bool):
        self.text.setStyleSheet(f"color: {M['row_label'] if on else M['row_label_off']}; background: transparent;")

    def setOn(self, on: bool):
        self.box.setChecked(on)
        self._refresh_label(on)

    def isOn(self) -> bool:
        return self.box.isChecked()

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            self.clicked.emit()


class _HeaderEdgesField(QWidget):
    """Boite a cotes cliquables + liste de cases 2x2, synchronisees dans
    les deux sens (cliquer un cote de la boite coche/decoche la case
    correspondante, et inversement)."""

    changed = Signal()

    _ORDER = [("top", "Haut"), ("right", "Droite"), ("bottom", "Bas"), ("left", "Gauche")]

    def __init__(self, edges: dict, parent=None):
        super().__init__(parent)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(14)
        self.box = _EdgeBox(edges)
        self.box.changed.connect(self._on_box_toggled)
        layout.addWidget(self.box)

        grid_wrap = QWidget()
        grid = QGridLayout(grid_wrap)
        grid.setContentsMargins(0, 0, 0, 0)
        grid.setHorizontalSpacing(10)
        grid.setVerticalSpacing(5)
        self.items: dict[str, _EdgeCheckItem] = {}
        for i, (key, label) in enumerate(self._ORDER):
            item = _EdgeCheckItem(label, bool(edges.get(key, False)))
            item.clicked.connect(lambda k=key: self._toggle(k))
            self.items[key] = item
            row, col = divmod(i, 2)
            grid.addWidget(item, row, col)
        layout.addWidget(grid_wrap, 1)

    def _toggle(self, key: str):
        item = self.items[key]
        new_on = not item.isOn()
        item.setOn(new_on)
        self.box.bars[key].setOn(new_on)
        self.changed.emit()

    def _on_box_toggled(self, key: str):
        """Clic direct sur un cote de la boite (plutot que sur la ligne de
        la liste) : repercute l'etat du filet sur la case correspondante."""
        self.items[key].setOn(self.box.bars[key]._on)
        self.changed.emit()

    def value(self) -> dict[str, bool]:
        return {key: item.isOn() for key, item in self.items.items()}

    def setValue(self, edges: dict):
        self.box.setValue(edges)
        for key, item in self.items.items():
            item.setOn(bool(edges.get(key, False)))

    def refresh_colors(self):
        self.box.refresh_colors()


class _AppOrCustomColorField(QWidget):
    """Pastille de couleur cliquable, choisissable PARMI les pastilles
    semantiques de l'appli (comme _HeaderColorField, voir SEMANTIC_COLOR_
    SLOTS) OU une couleur personnalisee (comme _ColorField, popup HSL/RVB/
    hex) — utilisee par _SideColorsField (bordures de Toggles/Sliders) —
    voir la remarque de l'utilisateur, "j'aimerais pouvoir avoir le choix
    entre une couleur de l'application (skin principale niveau 1 ...) ou
    des couleurs personnalisees".

    Un seul clic ouvre un menu (les pastilles semantiques + "Personnalisee
    ..." tout en bas, qui ouvre alors le popup HSL/RVB/hex habituel) —
    pas de bascule separee "App/Personnalise" : le menu EST le choix.

    Valeur stockee (voir value()/setValue()) : une chaine hex "#rrggbb"
    (couleur personnalisee, format INCHANGE par rapport a l'ancien
    _ColorField qu'elle remplace ici, retro-compatible avec les presets
    existants) OU "@<slot>" (reference a une pastille semantique) — ce
    prefixe "@" est le SEUL nouveau format possible."""

    changed = Signal(str)

    def __init__(self, value: str, colors: dict, swatch_size: int = 20, title: str = "Couleur", parent=None):
        super().__init__(parent)
        self._value = value
        self._colors = colors
        self._title = title
        self._before_pick = value
        self._popup: _ColorPickerPopup | None = None
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        self.swatch = QPushButton()
        self.swatch.setFixedSize(swatch_size, swatch_size)
        self.swatch.setCursor(Qt.ArrowCursor)
        self.swatch.setFocusPolicy(Qt.NoFocus)
        self.swatch.clicked.connect(self._open_menu)
        layout.addWidget(self.swatch)
        self._refresh()

    def _is_slot(self) -> bool:
        return self._value.startswith("@")

    def _resolved_hex(self) -> str:
        return _resolve_color_value(self._value, self._colors)

    def _refresh(self):
        hexval = self._resolved_hex()
        self.swatch.setStyleSheet(
            "QPushButton { background: " + hexval + "; border: 1px solid " + M["swatch_border"]
            + "; border-radius: 2px; }"
            "QPushButton:hover { border-color: " + M["swatch_border_hover"] + "; }"
        )
        self.swatch.setToolTip(_SLOT_LABELS.get(self._value[1:], hexval) if self._is_slot() else hexval)

    def _open_menu(self):
        menu = QMenu(self)
        menu.setFont(_qfont(11, 400))
        menu.setStyleSheet(
            f"QMenu {{ background: {M['toolbar_bg']}; border: 1px solid {M['field_border']}; padding: 4px 0; }}"
            f"QMenu::item {{ padding: 5px 16px; color: {M['value_fg']}; }}"
            f"QMenu::item:selected {{ background: {M['accent']}; color: {M['accent_fg']}; }}"
            f"QMenu::separator {{ background: {M['panel_border']}; height: 1px; margin: 4px 0; }}"
        )
        for slot, real, label in SEMANTIC_COLOR_SLOTS:
            action = menu.addAction(_solid_icon(self._colors.get(real, "#000")), label)
            action.triggered.connect(lambda _c=False, s=slot: self._select_slot(s))
        menu.addSeparator()
        custom_action = menu.addAction("Personnalisee...")
        custom_action.triggered.connect(self._open_custom_picker)
        menu.exec(self.swatch.mapToGlobal(QPoint(0, self.swatch.height())))

    def _select_slot(self, slot: str):
        self._value = f"@{slot}"
        self._refresh()
        self.changed.emit(self._value)

    def _open_custom_picker(self):
        self._before_pick = self._value
        popup = _ColorPickerPopup(self._resolved_hex(), self._title, self)
        self._popup = popup
        popup.colorChanged.connect(self._apply_custom_live)
        popup.committed.connect(self._apply_custom_live)
        popup.cancelled.connect(lambda: self._apply_custom_live(self._before_pick))
        popup.show_near(self.swatch)

    def _apply_custom_live(self, value: str):
        self._value = value
        self._refresh()
        self.changed.emit(self._value)

    def value(self) -> str:
        return self._value

    def setValue(self, value: str):
        self._value = value
        self._refresh()

    def refresh_colors(self, colors: dict):
        """A appeler quand la page Couleurs change (voir SettingsWindow.
        _on_colors_changed) : une pastille en mode "App" (voir _is_slot)
        doit suivre EN DIRECT la couleur reelle de sa pastille semantique."""
        self._colors = colors
        self._refresh()


class _SideColorsField(QWidget):
    """4 pastilles de couleur cote a cote (Gauche/Haut/Bas/Droite — meme
    ordre, pour la meme raison, que _SidePaddingField, voir sa remarque de
    tete de classe) — utilise pour la bordure du selecteur de slider (voir
    Geometrie > Slider), des lignes "Bordure" de Toggles > Cadre/Coche ET
    de Colonnes > Bordure, qui ont besoin d'une couleur INDEPENDANTE par
    cote (contrairement a _HeaderEdgesField ci-dessus, une seule couleur
    partagee + un simple on/off par cote).

    Chaque cote a aussi son PROPRE interrupteur actif/inactif — un vrai
    _Toggle (MEME widget que partout ailleurs dans cette fenetre, voir
    enabledValue/setEnabledValue), pas une case a cocher a part : voir la
    remarque de l'utilisateur, "les toggles que tu as mis en place doivent
    etre du type de ceux de la fenetre de settings" (corrige une 1ere
    version qui utilisait une petite case dediee, _SideEnableCheck,
    abandonnee). Remplace l'ancien interrupteur global unique de
    _ToggleSideColorsField, voir la remarque de l'utilisateur, "au lieu
    d'avoir un seul toggle pour activer les bordures, je veux un toggle
    par cote" : un cote desactive grise sa pastille (non cliquable, meme
    mecanique que l'ancien setLocked, mais desormais PAR cote plutot que
    global).

    Le 1er cote de _ORDER (_LEADER) peut piloter les 3 autres — COULEUR ET
    interrupteur actif/inactif — lien PERMANENT (voir setLinked) ou
    transfert PONCTUEL (voir copyLeaderToOthers) — memes 2 mecaniques,
    memes raisons, que _SidePaddingField (voir sa remarque de tete de
    classe) : la aussi, reordonner _ORDER suffit a changer QUEL cote est
    le maitre. Lie, seul l'interrupteur du maitre reste cliquable, les 3
    autres suivent (voir _on_side_enabled_changed/la remarque de
    l'utilisateur, "quand les 4 cotes sont lies, et que l'on active la
    bordure du premier cote, les autres ne suivent pas").

    Chaque pastille est un _AppOrCustomColorField (pas un simple
    _ColorField) : couleur PARMI les pastilles semantiques de l'appli OU
    personnalisee — voir sa remarque de tete de classe et la remarque de
    l'utilisateur."""

    changed = Signal()

    _ORDER = [("left", "G"), ("top", "H"), ("bottom", "B"), ("right", "D")]
    _LEADER = _ORDER[0][0]
    _OTHERS = tuple(key for key, _label in _ORDER[1:])

    def __init__(self, sides: dict, colors: dict, enabled: dict | None = None, parent=None):
        super().__init__(parent)
        # Fond transparent EXPLICITE (self ET wrap ci-dessous) : meme piege/
        # correctif que _SidePaddingField (voir son commentaire) — sans lui,
        # ces QWidget nus se voient quand meme peints (le style sheet global
        # de l'appli active WA_StyledBackground implicitement sur tout
        # QWidget), masquant le fond alterne de la ligne de tableau
        # (table_row_a/table_row_b) sous les toggles/pastilles — voir la
        # remarque de l'utilisateur, "le fond des modificateur n'est pas le
        # fond des tableaux alors qu'il devraient l'etre".
        self.setStyleSheet("background: transparent;")
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(12)
        self._linked = False
        enabled = enabled or {}
        self._enabled: dict[str, bool] = {key: bool(enabled.get(key, True)) for key, _ in self._ORDER}
        self.fields: dict[str, _AppOrCustomColorField] = {}
        self.side_checks: dict[str, _Toggle] = {}
        for key, letter in self._ORDER:
            wrap = QWidget()
            wrap.setStyleSheet("background: transparent;")
            wrap_l = QVBoxLayout(wrap)
            wrap_l.setContentsMargins(0, 0, 0, 0)
            wrap_l.setSpacing(3)
            wrap_l.setAlignment(Qt.AlignHCenter)
            check = _Toggle(self._enabled[key], style_override="toggle2", show_label=False)
            check.toggled.connect(lambda on, k=key: self._on_side_enabled_changed(k, on))
            self.side_checks[key] = check
            wrap_l.addWidget(check, 0, Qt.AlignHCenter)
            field = _AppOrCustomColorField(
                sides.get(key, "#000000"), colors, swatch_size=20, title=f"Bordure {letter}")
            field.changed.connect(lambda _v, k=key: self._on_side_changed(k))
            self.fields[key] = field
            wrap_l.addWidget(field, 0, Qt.AlignHCenter)
            tag = QLabel(letter)
            tag.setFont(_qfont(9, 600, tracking=0.5))
            tag.setAlignment(Qt.AlignHCenter)
            tag.setStyleSheet(f"color: {M['label_dim']}; background: transparent;")
            wrap_l.addWidget(tag)
            layout.addWidget(wrap)
        self._refresh_field_states()

    def _on_side_changed(self, key: str):
        # Voir _SidePaddingField._on_side_changed, meme mecanique : le
        # maitre (_LEADER) pilote les 3 autres tant que le lien est actif ;
        # les 3 autres sont de toute facon non cliquables pendant ce temps
        # (voir setLinked), ce cas ne peut donc survenir qu'en changeant le
        # maitre lui-meme.
        if self._linked and key == self._LEADER:
            value = self.fields[self._LEADER].value()
            for other_key in self._OTHERS:
                self.fields[other_key].setValue(value)
        self.changed.emit()

    def _on_side_enabled_changed(self, key: str, on: bool):
        # Voir _on_side_changed, meme mecanique : le maitre (_LEADER)
        # pilote aussi les 3 autres INTERRUPTEURS tant que le lien est
        # actif (pas seulement les couleurs, voir setLinked) — voir la
        # remarque de l'utilisateur, "quand les 4 cotes sont lies, et que
        # l'on active la bordure du premier cote, les autres ne suivent
        # pas". Les 3 autres sont de toute facon non cliquables pendant ce
        # temps (voir _refresh_field_states), ce cas ne peut donc survenir
        # qu'en changeant le maitre lui-meme.
        self._enabled[key] = bool(on)
        if self._linked and key == self._LEADER:
            for other_key in self._OTHERS:
                self._enabled[other_key] = self._enabled[key]
                self.side_checks[other_key].setChecked(self._enabled[key])
        self._refresh_field_states()
        self.changed.emit()

    def value(self) -> dict[str, str]:
        return {key: field.value() for key, field in self.fields.items()}

    def setValue(self, sides: dict):
        for key, field in self.fields.items():
            field.setValue(sides.get(key, field.value()))

    def enabledValue(self) -> dict[str, bool]:
        return dict(self._enabled)

    def setEnabledValue(self, enabled: dict):
        for key, check in self.side_checks.items():
            on = bool(enabled.get(key, self._enabled.get(key, True)))
            self._enabled[key] = on
            check.setChecked(on)
        self._refresh_field_states()

    def _refresh_field_states(self):
        """Une pastille est non cliquable/grisee si SON PROPRE cote est
        desactive (_enabled, voir side_checks) OU si le lien est actif et
        que ce n'est pas le maitre (_linked, voir setLinked) — le maitre,
        lui, reste toujours editable tant que SON PROPRE cote est actif,
        lien ou pas (voir _CellPaddingField, meme principe transpose des
        valeurs px aux couleurs). Meme chose pour l'interrupteur actif/
        inactif de chaque cote (voir side_checks) : lie, seul celui du
        maitre reste cliquable, les 3 autres suivent (voir
        _on_side_enabled_changed)."""
        for key, field in self.fields.items():
            locked = not self._enabled.get(key, True) or (self._linked and key != self._LEADER)
            field.swatch.setEnabled(not locked)
            effect = field.graphicsEffect()
            if not isinstance(effect, QGraphicsOpacityEffect):
                effect = QGraphicsOpacityEffect(field)
                field.setGraphicsEffect(effect)
            effect.setOpacity(0.35 if locked else 1.0)
        for key, check in self.side_checks.items():
            lock_toggle = self._linked and key != self._LEADER
            check.setEnabled(not lock_toggle)

    def setLinked(self, linked: bool):
        """Voir _SidePaddingField.setLinked, meme mecanique (le maitre
        pilote les 3 autres, resynchronises TOUT DE SUITE dessus des
        l'activation du lien) — COULEUR ET interrupteur actif/inactif du
        maitre (voir _on_side_enabled_changed/la remarque de l'utilisateur,
        "quand les 4 cotes sont lies, et que l'on active la bordure du
        premier cote, les autres ne suivent pas")."""
        self._linked = linked
        if linked:
            value = self.fields[self._LEADER].value()
            enabled = self._enabled[self._LEADER]
            for key in self._OTHERS:
                self.fields[key].setValue(value)
                self._enabled[key] = enabled
                self.side_checks[key].setChecked(enabled)
        self._refresh_field_states()

    def copyLeaderToOthers(self):
        """Voir _SidePaddingField.copyLeaderToOthers, meme mecanique :
        transfert PONCTUEL, sans activer le lien permanent. COULEUR ET
        interrupteur actif/inactif du maitre (voir _on_side_enabled_changed)
        — voir la remarque de l'utilisateur, "je veux que copier G concerne
        aussi les toggle d'activation" (contrairement au lien "lie"/"libre"
        permanent, qui reste lui COULEUR uniquement, voir setLinked)."""
        value = self.fields[self._LEADER].value()
        enabled = self._enabled[self._LEADER]
        for key in self._OTHERS:
            self.fields[key].setValue(value)
            self._enabled[key] = enabled
            self.side_checks[key].setChecked(enabled)
        self._refresh_field_states()
        self.changed.emit()

    def refresh_colors(self, colors: dict):
        """Voir _AppOrCustomColorField.refresh_colors, meme raison —
        rappele sur les 4 pastilles a la fois."""
        for field in self.fields.values():
            field.refresh_colors(colors)


class _ToggleSideColorsField(QWidget):
    """Bordure, avec un interrupteur INDEPENDANT par cote (un vrai _Toggle
    par cote, voir _SideColorsField.side_checks — remplace l'ancien
    interrupteur global unique, voir la remarque de l'utilisateur, "au
    lieu d'avoir un seul toggle pour activer les bordures, je veux un
    toggle par cote") + un toggle "lie"/"libre" + bouton "Copier" (voir
    _SideColorsField.setLinked/copyLeaderToOthers, memes 2 mecaniques que
    _CellPaddingField pour le padding, transposees aux couleurs — voir la
    remarque de l'utilisateur) + ses 4 couleurs par cote (_SideColorsField)
    — un cote desactive grise sa propre pastille (voir _SideColorsField.
    _refresh_field_states), independamment des 3 autres."""

    changed = Signal()

    def __init__(self, enabled: dict, sides: dict, colors: dict, parent=None):
        super().__init__(parent)
        # Fond transparent EXPLICITE : meme piege/correctif que
        # _SideColorsField ci-dessus (voir son commentaire) — voir la
        # remarque de l'utilisateur, "le fond des modificateur n'est pas le
        # fond des tableaux alors qu'il devraient l'etre".
        self.setStyleSheet("background: transparent;")
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(14)
        self.link_toggle = _Toggle(False, on_label="lie", off_label="libre")
        self.link_toggle.toggled.connect(self._on_link_toggled)
        layout.addWidget(self.link_toggle)
        side_names = {"top": "Haut", "right": "Droite", "bottom": "Bas", "left": "Gauche"}
        leader_key, leader_letter = _SideColorsField._ORDER[0]
        self.copy_btn = _Btn(
            f"Copier {leader_letter} →", M["btn_bg"], M["btn_border"], M["btn_fg"], M["btn_hover"], height=25)
        others_full = [side_names[k] for k in _SideColorsField._OTHERS]
        self.copy_btn.setToolTip(f"Copier la valeur de {side_names[leader_key]} sur {'/'.join(others_full)}")
        layout.addWidget(self.copy_btn)
        self.sides = _SideColorsField(sides, colors, enabled)
        self.sides.changed.connect(self.changed.emit)
        self.copy_btn.clicked.connect(self.sides.copyLeaderToOthers)
        layout.addWidget(self.sides)

    def _on_link_toggled(self, checked: bool):
        self.sides.setLinked(checked)
        self.copy_btn.setEnabled(not checked)
        self.changed.emit()

    def sidesValue(self) -> dict[str, str]:
        return self.sides.value()

    def sidesEnabledValue(self) -> dict[str, bool]:
        return self.sides.enabledValue()

    def setValue(self, enabled: dict, sides: dict):
        self.sides.setValue(sides)
        self.sides.setEnabledValue(enabled)

    def setRadius(self, radius: int):
        self.copy_btn.setRadius(radius)

    def refresh_colors(self, colors: dict):
        """Voir _SideColorsField.refresh_colors, meme raison."""
        self.sides.refresh_colors(colors)


class _SidePaddingField(QWidget):
    """4 sliders cote a cote (Gauche/Haut/Bas/Droite — voir la remarque de
    l'utilisateur pour cet ordre precis, DIFFERENT de celui de
    _SideColorsField/_HeaderEdgesField ; meme disposition — tag au-dessus,
    controle en dessous) : un slider de valeur px par cote, pour le padding
    du texte des cellules de tableau (voir _CellPaddingField).

    Le 1er cote de _ORDER (pas force "top") pilote les 3 autres quand le
    lien est actif (voir setLinked) — c'est lui que _CellPaddingField
    propose de recopier sur les 3 autres (bouton "Copier"), voir
    copyLeaderToOthers : reordonner _ORDER suffit donc a changer QUEL cote
    est le "maitre", pas seulement l'ordre d'affichage."""

    changed = Signal()

    _ORDER = [("left", "G"), ("top", "H"), ("bottom", "B"), ("right", "D")]
    _LEADER = _ORDER[0][0]
    _OTHERS = tuple(key for key, _label in _ORDER[1:])

    def __init__(self, sides: dict, minimum: int = 0, maximum: int = 32, parent=None):
        super().__init__(parent)
        # Fond transparent EXPLICITE (self ET wrap ci-dessous) : meme piege/
        # correctif que _table_cell (voir son commentaire) — sans lui, ce
        # QWidget nu se voit quand meme peint (le style sheet global de
        # l'appli active WA_StyledBackground implicitement sur tout
        # QWidget), masquant le fond alterne de la ligne de tableau
        # (table_row_a/table_row_b) sous les sliders — voir la remarque de
        # l'utilisateur, capture a l'appui : "je veux la couleur fond
        # tableau" sous les sliders.
        self.setStyleSheet("background: transparent;")
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(12)
        self._linked = False
        self.fields: dict[str, _SliderField] = {}
        for key, letter in self._ORDER:
            wrap = QWidget()
            wrap.setStyleSheet("background: transparent;")
            wrap_l = QVBoxLayout(wrap)
            wrap_l.setContentsMargins(0, 0, 0, 0)
            wrap_l.setSpacing(3)
            tag = QLabel(letter)
            tag.setFont(_qfont(9, 600, tracking=0.5))
            tag.setStyleSheet(f"color: {M['label_dim']}; background: transparent;")
            wrap_l.addWidget(tag)
            field = _SliderField(minimum, maximum, int(sides.get(key, 0)), slider_width=60, box_width=42)
            field.valueChanged.connect(lambda _v, k=key: self._on_side_changed(k))
            self.fields[key] = field
            wrap_l.addWidget(field)
            layout.addWidget(wrap)

    def _on_side_changed(self, key: str):
        # Le "maitre" (_LEADER, 1er cote de _ORDER) pilote les 3 autres
        # tant que le lien est actif (voir _CellPaddingField/setLinked) —
        # glisser un des 3 AUTRES ne fait rien ici : ils sont de toute
        # facon desactives par setLinked pendant que le lien est actif
        # (voir plus bas), ce cas ne peut donc survenir qu'en glissant le
        # maitre lui-meme.
        if self._linked and key == self._LEADER:
            value = self.fields[self._LEADER].value()
            for other_key in self._OTHERS:
                self.fields[other_key].setValue(value)
        self.changed.emit()

    def value(self) -> dict[str, int]:
        return {key: field.value() for key, field in self.fields.items()}

    def setValue(self, sides: dict):
        for key, field in self.fields.items():
            field.setValue(int(sides.get(key, field.value())))

    def setLinked(self, linked: bool):
        """Lien actif : le maitre (_LEADER) pilote les 3 autres, qui
        deviennent non modifiables directement (meme correctif que
        _SideColorsField.setLocked — un simple setEnabled resterait
        invisible a l'oeil sans l'effet d'opacite, voir sa remarque de tete
        de methode) — et on resynchronise TOUT DE SUITE sur le maitre pour
        qu'un lien qu'on vient d'activer ne laisse pas les 3 autres a une
        ancienne valeur divergente tant qu'on n'a pas retouche le maitre."""
        self._linked = linked
        if linked:
            value = self.fields[self._LEADER].value()
            for key in self._OTHERS:
                self.fields[key].setValue(value)
        for key in self._OTHERS:
            field = self.fields[key]
            field.setEnabled(not linked)
            effect = field.graphicsEffect()
            if not isinstance(effect, QGraphicsOpacityEffect):
                effect = QGraphicsOpacityEffect(field)
                field.setGraphicsEffect(effect)
            effect.setOpacity(0.35 if linked else 1.0)

    def setRadius(self, radius: int):
        for field in self.fields.values():
            field.setRadius(radius)

    def copyLeaderToOthers(self):
        """Bouton "Copier" de _CellPaddingField : transfert PONCTUEL du
        maitre (_LEADER, 1er cote de _ORDER) sur les 3 autres cotes, sans
        activer le lien permanent (voir setLinked) — contrairement au
        lien, les 3 autres restent ensuite modifiables independamment.
        Inutile (et le bouton reste desactive, voir _CellPaddingField.
        _on_toggled) tant que le lien est deja actif, les 3 autres suivant
        alors deja le maitre en direct — voir la remarque de l'utilisateur :
        "un petit bouton qui me permette de transferer la premiere valeur
        sur les trois autres"."""
        value = self.fields[self._LEADER].value()
        for key in self._OTHERS:
            self.fields[key].setValue(value)
        self.changed.emit()


class _CellPaddingField(QWidget):
    """Padding du texte a l'interieur des cellules de tableau — toggle
    "lie"/"libre" (voir _Toggle) + les 4 sliders par cote (_SidePaddingField)
    — "lie" : le slider "Haut" pilote alors les 3 autres cotes, exactement
    comme _ToggleSideColorsField ci-dessus pour la bordure du selecteur/du
    rail, meme mecanique transposee des couleurs aux valeurs px."""

    changed = Signal()

    def __init__(self, linked: bool, sides: dict, parent=None):
        super().__init__(parent)
        self.setStyleSheet("background: transparent;")  # voir _SidePaddingField, meme correctif
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(14)
        self.toggle = _Toggle(linked, on_label="lie", off_label="libre")
        self.toggle.toggled.connect(self._on_toggled)
        layout.addWidget(self.toggle)
        # Bouton "Copier" : transfert PONCTUEL du maitre (1er cote de
        # _SidePaddingField._ORDER, voir copyLeaderToOthers) sur les 3
        # autres, a cote du lien PERMANENT ci-dessus plutot qu'a sa place —
        # desactive pendant que le lien est actif (les 3 autres suivent
        # deja le maitre en direct dans ce cas, le bouton n'aurait rien a
        # faire) — voir la remarque de l'utilisateur. Libelle/infobulle
        # LUS depuis _ORDER (pas "Haut"/"H" en dur) : reordonner _ORDER
        # suffit alors a garder ce bouton coherent avec le nouveau maitre.
        side_names = {"top": "Haut", "right": "Droite", "bottom": "Bas", "left": "Gauche"}
        leader_key, leader_letter = _SidePaddingField._ORDER[0]
        self.copy_btn = _Btn(
            f"Copier {leader_letter} →", M["btn_bg"], M["btn_border"], M["btn_fg"], M["btn_hover"], height=25)
        others_full = [side_names[k] for k in _SidePaddingField._OTHERS]
        self.copy_btn.setToolTip(f"Copier la valeur de {side_names[leader_key]} sur {'/'.join(others_full)}")
        layout.addWidget(self.copy_btn)
        self.sides = _SidePaddingField(sides)
        self.sides.changed.connect(self.changed.emit)
        self.copy_btn.clicked.connect(self.sides.copyLeaderToOthers)
        layout.addWidget(self.sides)
        self.sides.setLinked(linked)
        self.copy_btn.setEnabled(not linked)

    def _on_toggled(self, checked: bool):
        self.sides.setLinked(checked)
        self.copy_btn.setEnabled(not checked)
        self.changed.emit()

    def isLinked(self) -> bool:
        return self.toggle.isChecked()

    def sidesValue(self) -> dict[str, int]:
        return self.sides.value()

    def setValue(self, linked: bool, sides: dict):
        self.toggle.setChecked(linked)
        self.sides.setValue(sides)
        self.sides.setLinked(linked)
        self.copy_btn.setEnabled(not linked)

    def setRadius(self, radius: int):
        # copy_btn suit un AUTRE rayon (Geometrie > Boutons, voir
        # SettingsWindow._apply_button_radius, ou il est aussi enregistre) —
        # celui-ci ne concerne que les boites de valeur des sliders (voir
        # _apply_dropdown_radius, qui appelle cette methode).
        self.sides.setRadius(radius)


# ==========================================================================
# Section "Geometrie" — table Element/Cadre/Coins arrondis, 3 lignes :
# Fenetres (rayon seul, pas de cadre reglable — le filet du panneau
# principal est structurel, voir #CentralFrame dans pipeline_browser.py),
# Zones de saisie et Boutons (cadre actif/sans + rayon).
# ==========================================================================

class _GeoTable(QWidget):
    changed = Signal()

    def __init__(self, window_radius: int, input_frame: bool, input_radius: int,
                 button_frame: bool, button_radius: int,
                 column_widths: list[int] | None = None, parent=None):
        super().__init__(parent)
        self.frame_wrap = None
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        frame_wrap, layout = _table_frame()
        self.frame_wrap = frame_wrap
        self.head = _table_header([("Element", 0), ("Cadre", 150), ("Coins arrondis", 246)])
        layout.addWidget(self.head)

        self.window_radius_field = _SliderField(0, 24, window_radius, slider_width=140, box_width=58)
        self.input_frame_toggle = _Toggle(input_frame)
        self.input_radius_field = _SliderField(0, 16, input_radius, slider_width=140, box_width=58)
        self.button_frame_toggle = _Toggle(button_frame)
        self.button_radius_field = _SliderField(0, 16, button_radius, slider_width=140, box_width=58)

        # "Tableaux" deplace dans sa propre section (voir la remarque de
        # l'utilisateur, capture a l'appui) — voir SettingsWindow.
        # _section_tables/self.table_radius_field.
        rows = [
            ("Fenetres", None, self.window_radius_field),
            ("Zones de saisie", self.input_frame_toggle, self.input_radius_field),
            ("Boutons", self.button_frame_toggle, self.button_radius_field),
        ]
        self._row_meta: list[tuple[QWidget, str, bool]] = []
        # Voir _SimpleFontTable._cells, meme raison (toutes les cellules,
        # pas seulement celles cablees au redimensionnement par colonne).
        self._cells: list[QWidget] = []
        column_cells: dict[int, list[QWidget]] = {}
        for i, (label, frame_toggle, radius_field) in enumerate(rows):
            bg = M["table_row_a"] if i % 2 else M["table_row_b"]
            row, row_l = _table_row(bg, first=(i == 0))
            self._row_meta.append((row, bg, i == 0))
            name = QLabel(label)
            name.setFont(_qfont(12, 400))
            name.setStyleSheet(f"color: {M['row_label']}; background: transparent;")
            self._cells.append(_table_cell(name, 0, row_l, center=True))
            if frame_toggle is not None:
                cell = _table_cell(frame_toggle, 150, row_l, center=True)
                frame_toggle.toggled.connect(lambda _c: self.changed.emit())
            else:
                dash = QLabel("—")
                dash.setFont(_qfont(10, 400, mono=True))
                dash.setStyleSheet(f"color: {M['dash']}; background: transparent;")
                cell = _table_cell(dash, 150, row_l, center=True)
            column_cells.setdefault(1, []).append(cell)
            self._cells.append(cell)
            cell = _table_cell(radius_field, 246, row_l, center=True)
            column_cells.setdefault(2, []).append(cell)
            self._cells.append(cell)
            radius_field.valueChanged.connect(lambda _v: self.changed.emit())
            _lock_min_height(row)
            layout.addWidget(row)
        _wire_resizable_columns(self.head, column_cells)
        # Largeurs sauvegardees (voir SettingsWindow._current_values, un
        # preset) — APRES le cablage ci-dessus, pas avant : setColumnWidths
        # emet resized par colonne, qui ne repercute sur les lignes que si
        # _wire_resizable_columns les a deja enregistrees (sinon l'entete
        # affiche la largeur sauvegardee mais les lignes restent a la
        # largeur par defaut).
        if column_widths:
            self.head.setColumnWidths(column_widths)

        outer.addWidget(frame_wrap)

    def value(self) -> dict[str, Any]:
        return {
            "window_radius": self.window_radius_field.value(),
            "input_frame": self.input_frame_toggle.isChecked(),
            "input_radius": self.input_radius_field.value(),
            "button_frame": self.button_frame_toggle.isChecked(),
            "button_radius": self.button_radius_field.value(),
        }

    def apply_radius(self, radius: int):
        """Voir _SimpleFontTable.apply_radius (meme logique : entete =
        coins hauts, derniere ligne = coins bas, `bg` recalculee a chaque
        appel, pas reprise de `_row_meta`)."""
        self.frame_wrap.setRadius(radius)
        _restyle_table_head(self.head, radius)
        last = len(self._row_meta) - 1
        new_meta = []
        for i, (row, _old_bg, first) in enumerate(self._row_meta):
            bg = M["table_row_a"] if i % 2 == 0 else M["table_row_b"]
            _restyle_table_row(row, bg, first, bottom_radius=(radius if i == last else 0))
            new_meta.append((row, bg, first))
        self._row_meta = new_meta

    def setCellPadding(self, sides: dict):
        """Voir _SimpleFontTable.setCellPadding, meme logique."""
        left, top = int(sides.get("left", 10)), int(sides.get("top", 0))
        right, bottom = int(sides.get("right", 10)), int(sides.get("bottom", 0))
        for cell in self._cells:
            cell.layout().setContentsMargins(left, top, right, bottom)
        for row, _bg, _first in self._row_meta:
            row.setMinimumHeight(0)
            _lock_min_height(row)
        self.head.setCellPadding(left, right)


class _TablePreview(QWidget):
    """Apercu de tableau (2 colonnes x 3 lignes, AVEC entete) pour Tableaux
    > l'apercu au-dessus de son tableau de reglages (voir
    _section_preview_wrap/SettingsWindow._section_tables) — contenu
    purement demonstratif (pas de vraies donnees), mais suit EN DIRECT les
    3 reglages de la section (Rayon des angles/Padding des cellules/
    Couleur d'en-tete, voir SettingsWindow._apply_table_radius/
    _apply_cell_padding/_apply_table_head_color, qui l'incluent desormais
    comme un 3e tableau a en-tete, au meme titre que Polices/Geometrie) —
    voir la remarque de l'utilisateur, "un tableau de 2 colonnes et 3
    lignes avec entete"."""

    def __init__(self, parent=None):
        super().__init__(parent)
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        self.frame, layout = _table_frame()
        self.head = _table_header([("Colonne A", 100), ("Colonne B", 100)])
        layout.addWidget(self.head)
        self._row_meta: list[tuple[QWidget, str, bool]] = []
        self._cells: list[QWidget] = []
        for i in range(3):
            bg = M["table_row_a"] if i % 2 else M["table_row_b"]
            row, row_l = _table_row(bg, first=(i == 0))
            self._row_meta.append((row, bg, i == 0))
            for col in (0, 1):
                value = QLabel(str(i * 2 + col + 1))
                value.setFont(_qfont(11, 400, mono=True))
                value.setStyleSheet(f"color: {M['value_muted']}; background: transparent;")
                self._cells.append(_table_cell(value, 100, row_l, center=True))
            _lock_min_height(row)
            layout.addWidget(row)
        outer.addWidget(self.frame)

    def apply_radius(self, radius: int):
        """Voir _SimpleFontTable.apply_radius, meme logique."""
        self.frame.setRadius(radius)
        _restyle_table_head(self.head, radius)
        last = len(self._row_meta) - 1
        new_meta = []
        for i, (row, _old_bg, first) in enumerate(self._row_meta):
            bg = M["table_row_a"] if i % 2 == 0 else M["table_row_b"]
            _restyle_table_row(row, bg, first, bottom_radius=(radius if i == last else 0))
            new_meta.append((row, bg, first))
        self._row_meta = new_meta

    def setCellPadding(self, sides: dict):
        """Voir _SimpleFontTable.setCellPadding, meme logique."""
        left, top = int(sides.get("left", 10)), int(sides.get("top", 0))
        right, bottom = int(sides.get("right", 10)), int(sides.get("bottom", 0))
        for cell in self._cells:
            cell.layout().setContentsMargins(left, top, right, bottom)
        for row, _bg, _first in self._row_meta:
            row.setMinimumHeight(0)
            _lock_min_height(row)
        self.head.setCellPadding(left, right)


class _HamburgerButton(QPushButton):
    """Bouton icone "liste de presets" — 3 barres dessinees au QPainter au
    lieu d'un glyphe unicode (le glyphe "hamburger" n'est pas garanti par
    toutes les polices systeme et rendait un carre vide a l'ecran)."""

    def paintEvent(self, event):
        super().paintEvent(event)
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing, False)
        color = self.palette().color(self.foregroundRole())
        painter.setPen(QPen(QColor(color), 1.4))
        w, h = self.width(), self.height()
        bar_w = 12
        x0 = (w - bar_w) / 2
        for i, dy in enumerate((-4, 0, 4)):
            y = h / 2 + dy
            painter.drawLine(int(x0), int(y), int(x0 + bar_w), int(y))
        painter.end()


class _DoubleClickBox(QWidget):
    """QWidget generique qui emet doubleClicked — utilise pour la boite de
    preset (double-clic pour renommer, voir SettingsWindow._build_toolbar)."""

    doubleClicked = Signal()

    def mouseDoubleClickEvent(self, event):
        if event.button() == Qt.LeftButton:
            self.doubleClicked.emit()
        super().mouseDoubleClickEvent(event)


class _PresetListRow(QWidget):
    """Une ligne de la liste de presets (voir SettingsWindow.
    _open_preset_popup) : nom cliquable (charge ce preset) + croix a droite
    (le supprime) — toute la ligne HORS la croix reagit au clic, voir
    mousePressEvent."""

    clicked = Signal()
    deleteClicked = Signal()

    def __init__(self, name: str, parent=None):
        super().__init__(parent)
        self.setObjectName("PresetListRow")
        self.setAttribute(Qt.WA_StyledBackground, True)
        self.setCursor(Qt.PointingHandCursor)
        self.setFixedHeight(28)
        self.setStyleSheet(
            f"#PresetListRow {{ background: transparent; }}"
            f"#PresetListRow:hover {{ background: {M['btn_hover']}; }}"
        )
        layout = QHBoxLayout(self)
        layout.setContentsMargins(12, 0, 6, 0)
        layout.setSpacing(8)
        label = QLabel(name)
        label.setFont(_qfont(11, 400))
        label.setStyleSheet(f"color: {M['value_fg']}; background: transparent;")
        layout.addWidget(label, 1)
        del_btn = QPushButton("×")
        del_btn.setFlat(True)
        del_btn.setCursor(Qt.ArrowCursor)
        del_btn.setFocusPolicy(Qt.NoFocus)
        del_btn.setFixedSize(20, 20)
        del_btn.setFont(_qfont(13, 400, mono=True))
        del_btn.setStyleSheet(
            "QPushButton { background: transparent; border: none; padding: 0; color: " + M["close_fg"] + "; }"
            "QPushButton:hover { background: " + M["close_hover_bg"] + "; color: #ff8a80; }"
        )
        del_btn.clicked.connect(self.deleteClicked.emit)
        layout.addWidget(del_btn)

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            self.clicked.emit()


# ==========================================================================
# Fenetre principale (frameless, chrome propre a cette fenetre).
# ==========================================================================

class _SettingsTitleBar(QWidget):
    closeClicked = Signal()

    def __init__(self, dialog: QDialog, parent=None):
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
        dot = QLabel()
        dot.setFixedSize(9, 9)
        dot.setStyleSheet(f"border: 1px solid {M['dot_border']}; background: transparent;")
        layout.addWidget(dot)
        title = QLabel("Parametres generaux")
        title.setFont(_qfont(11, 400))
        title.setStyleSheet(f"color: {M['title_fg']}; background: transparent;")
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


class SettingsWindow(QDialog):
    """Fenetre de parametres, reproduction fidele de la maquette html
    "Parametres generaux". Chaque changement se previsualise en direct sur
    la fenetre principale (settingsChanged), sans toucher au disque ;
    Enregistrer persiste (settingsSaved)."""

    settingsChanged = Signal(dict)
    settingsSaved = Signal(dict)

    def __init__(self, parent=None):
        super().__init__(parent)
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
        geometry_b64 = _load_window_geometry()
        if geometry_b64:
            try:
                self.restoreGeometry(QByteArray.fromBase64(geometry_b64.encode("ascii")))
            except (ValueError, TypeError):
                pass

        self.settings = load_settings()
        self._original_settings = json.loads(json.dumps(self.settings))
        self._saved = False
        self._dirty = False
        # Tableaux "fermes" SANS entete de colonnes (voir _build_flat_table)
        # — un _FlatColumnResizer par tableau, ajoute ici par chaque
        # _section_xxx qui en construit un : permet de tous les retrouver
        # d'un coup (voir _apply_columns_resizable, qui doit les activer/
        # desactiver comme les tableaux A entete).
        self._flat_resizers: list[_FlatColumnResizer] = []
        self._current_preset = "Personnalise"
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

        # Voir la meme remarque dans l'ancienne fenetre : le rafraichissement
        # (previsualisation complete sur la fenetre principale) est lourd,
        # on le differe donc toujours de 30ms au fil d'un glisser de slider.
        self._live_pending = False
        self._live_timer = QTimer(self)
        self._live_timer.setInterval(30)
        self._live_timer.setSingleShot(True)
        self._live_timer.timeout.connect(self._flush_live_apply)

        self.panel = panel = _PanelFrame(self)
        self._apply_panel_radius(int(self.settings.get("window_radius", 0)))
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.addWidget(panel)

        root = QVBoxLayout(panel)
        root.setContentsMargins(1, 1, 1, 1)
        root.setSpacing(0)

        self.titlebar = _SettingsTitleBar(self)
        self.titlebar.closeClicked.connect(self.reject)
        root.addWidget(self.titlebar)

        root.addWidget(self._build_toolbar())
        root.addWidget(self._build_main_tabbar())

        body = QHBoxLayout()
        body.setContentsMargins(0, 0, 0, 0)
        body.setSpacing(0)
        self._main_stack = QStackedWidget()
        self._main_stack.addWidget(self._build_content())       # 0: General
        self._main_stack.addWidget(self._build_columns_page())  # 1: Colonnes
        body.addWidget(self._main_stack, 1)
        root.addLayout(body, 1)

        root.addWidget(self._build_bottom_bar())

        self._connect_live_updates()
        self._preview_now()

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
        tag.setFont(_qfont(9, 600, tracking=0.7))
        tag.setStyleSheet(f"color: {M['label_dim']}; background: transparent;")
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
        # radius=self.settings[...] (pas encore self.geo_table, construit
        # PLUS TARD dans __init__ — voir _connect_live_updates/
        # _apply_button_radius pour le suivi en direct du slider ensuite).
        save_btn = _Btn("Enregistrer", M["btn_bg"], M["btn_border"], M["btn_fg"], M["btn_hover"], height=26,
                         radius=int(self.settings.get("button_radius", 0)))
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
        path_label.setFont(_qfont(10, 400, mono=True))
        path_label.setStyleSheet(f"color: {M['group_note']}; background: transparent;")
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
                       height=30, weight=500, padding="0 12px",
                       radius=self.geo_table.button_radius_field.value())
        new_btn.setStyleSheet(new_btn.styleSheet() + "QPushButton { text-align: left; }")
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
        if not ok or not name.strip():
            return
        presets = _load_presets()
        presets[name.strip()] = self._current_values()
        _save_presets(presets)
        self._current_preset = name.strip()
        self._dirty = False
        self.titlebar.set_dirty(False)
        self._sync_preset_box()

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

    def _apply_column_type_overrides_to_controls(self):
        """Reapplique Colonnes > Type (voir _build_column_type_page) depuis
        self.settings — meme principe que le reste de _apply_values_to_
        controls, appelee juste apres (Valeurs par defaut/chargement d'un
        preset). Sans effet tant que _build_column_type_page n'a pas encore
        construit self._type_fields (jamais le cas aux 2 seuls appelants,
        tous 2 posterieurs a la construction complete de la fenetre — garde
        quand meme, par prudence)."""
        if not hasattr(self, "_type_fields"):
            return
        overrides = self.settings.get("column_type_overrides") or {}
        enabled_map = self.settings.get("column_type_override_enabled") or {}
        linked_map = self.settings.get("column_type_override_linked") or {}

        def seed(key, default):
            return overrides.get(key, self.settings.get(key, default))

        for key, toggle in self._type_toggles.items():
            toggle.setChecked(bool(enabled_map.get(key, False)))

        f = self._type_fields
        f["header_height"].setValue(int(seed("header_height", 26)))
        f["header_padding"].setValue(int(seed("header_padding", 0)))
        f["header_color"].setValue(seed("header_color", "skinN1"), self.settings["colors"])
        f["header_radius"].setValue(
            bool(linked_map.get("header_radius", True)), _coerce_corner_radius(seed("header_radius", 0)))
        f["header_border_enabled"].setValue(
            _coerce_side_enabled(seed("header_border_enabled", False)), seed("header_border", {}) or {})
        f["header_border_thickness"].setValue(int(seed("header_border_thickness", 1)))
        f["column_padding"].setValue(
            bool(linked_map.get("column_padding", True)), seed("column_padding", {}) or {})
        f["column_border_enabled"].setValue(
            _coerce_side_enabled(seed("column_border_enabled", True)), seed("column_border", {}) or {})
        f["column_border_thickness"].setValue(int(seed("column_border_thickness", 1)))
        f["column_border_radius"].setValue(
            bool(linked_map.get("column_border_radius", True)), _coerce_corner_radius(seed("column_border_radius", 0)))
        f["item_font_family"].setValue(seed("item_font_family", "") or "Systeme")
        f["item_color"].setValue(seed("item_color", "#d6d9dc"))
        f["item_icon_enabled"].setChecked(bool(seed("item_icon_enabled", True)))
        f["item_row_height"].setValue(int(seed("item_row_height", 25)))
        f["item_row_spacing"].setValue(int(seed("item_row_spacing", 1)))
        f["item_text_padding"].setValue(int(seed("item_text_padding", 8)))
        f["item_selection_focus_color"].setValue(seed("item_selection_focus_color", "#3f6f9f"))
        f["item_selection_unfocus_color"].setValue(seed("item_selection_unfocus_color", "#2e3338"))
        f["item_hover_color"].setValue(seed("item_hover_color", "#232729"))
        f["item_selection_padding"].setValue(
            bool(linked_map.get("item_selection_padding", False)), seed("item_selection_padding", {}) or {})
        f["item_selection_border_enabled"].setValue(
            _coerce_side_enabled(seed("item_selection_border_enabled", False)), seed("item_selection_border", {}) or {})
        f["item_selection_radius"].setValue(
            bool(linked_map.get("item_selection_radius", True)), _coerce_corner_radius(seed("item_selection_radius", 0)))
        f["item_selection_edge_border"].setChecked(bool(seed("item_selection_edge_border", True)))
        self._apply_column_type_preview()

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

        self.root_field.setText(self.settings.get("root_path", DEFAULT_SETTINGS["root_path"]))
        self.scale_field.setValue(int(self.settings.get("ui_scale", 100)))
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
        self.column_gap_field.setValue(int(self.settings.get("column_gap", 0)))
        self.column_padding_field.setValue(
            bool(self.settings.get("column_padding_linked", True)), self.settings.get("column_padding") or {})
        self.column_border_field.setValue(
            _coerce_side_enabled(self.settings.get("column_border_enabled", True)),
            self.settings.get("column_border") or {})
        self.column_border_thickness_field.setValue(int(self.settings.get("column_border_thickness", 1)))
        self.column_border_radius_field.setValue(
            bool(self.settings.get("column_border_radius_linked", True)),
            _coerce_corner_radius(self.settings.get("column_border_radius", 0)))
        self.item_font_field.setValue(self.settings.get("item_font_family") or "Systeme")
        self.item_color_field.setValue(self.settings.get("item_color", "#d6d9dc"))
        self.item_icon_field.setChecked(bool(self.settings.get("item_icon_enabled", True)))
        self.item_row_height_field.setValue(int(self.settings.get("item_row_height", 25)))
        self.item_row_spacing_field.setValue(int(self.settings.get("item_row_spacing", 1)))
        self.item_text_padding_field.setValue(int(self.settings.get("item_text_padding", 8)))
        self.item_selection_focus_field.setValue(self.settings.get("item_selection_focus_color", "#3f6f9f"))
        self.item_selection_unfocus_field.setValue(self.settings.get("item_selection_unfocus_color", "#2e3338"))
        self.item_hover_field.setValue(self.settings.get("item_hover_color", "#232729"))
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
        self._apply_column_type_overrides_to_controls()
        self.columns_resizable_toggle.setChecked(bool(self.settings.get("columns_resizable", True)))
        self.geo_table.head.setColumnWidths(self.settings.get("geo_table_columns") or [])
        self.font_table.head.setColumnWidths(self.settings.get("font_table_columns") or [])
        self.toggle_style_field.setValue(self.settings.get("toggle_style", "toggle1"))
        self._apply_toggle_shape_values("toggle1")
        self._apply_toggle_shape_values("toggle2")
        self.geo_table.window_radius_field.setValue(int(self.settings.get("window_radius", 0)))
        self.geo_table.input_frame_toggle.setChecked(bool(self.settings.get("input_frame", True)))
        self.geo_table.input_radius_field.setValue(int(self.settings.get("input_radius", 0)))
        self.geo_table.button_frame_toggle.setChecked(bool(self.settings.get("button_frame", True)))
        self.geo_table.button_radius_field.setValue(int(self.settings.get("button_radius", 0)))
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

    def _on_main_tab_changed(self, index: int):
        self._main_stack.setCurrentIndex(index)

    def _build_columns_page(self) -> QWidget:
        """Onglet Colonnes : barre d'onglets internes Type/Projets/Sous-
        projets, chacune avec sa propre page (voir _build_column_type_page —
        seule construite pour l'instant, voir la remarque de l'utilisateur :
        "pour le moment je vais me concentrer que sur l'onglet type"). La
        section "Entetes" (renommee "Colonnes", voir _section_headers) est
        repassee dans l'onglet General, sous Geometrie — voir la remarque
        de l'utilisateur : "deplace la section entetes dans l'onglet
        general juste au dessous de geometrie"."""
        page = QWidget()
        page.setStyleSheet(f"background: {M['panel_bg']};")
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        subbar = QWidget()
        subbar.setStyleSheet(f"background: {M['toolbar_bg']}; border-bottom: 1px solid {M['panel_border']};")
        subbar_l = QHBoxLayout(subbar)
        subbar_l.setContentsMargins(20, 0, 20, 0)
        self._columns_tabs = _TabStrip(["Type", "Projets", "Sous-projets"])
        subbar_l.addWidget(self._columns_tabs)
        layout.addWidget(subbar)

        self._columns_stack = QStackedWidget()
        self._columns_stack.addWidget(self._build_column_type_page())
        self._columns_stack.addWidget(self._build_column_placeholder_page("Projets"))
        self._columns_stack.addWidget(self._build_column_placeholder_page("Sous-projets"))
        self._columns_tabs.changed.connect(self._columns_stack.setCurrentIndex)
        layout.addWidget(self._columns_stack, 1)
        return page

    def _build_column_placeholder_page(self, title: str) -> QWidget:
        """Page vide (Projets/Sous-projets, pas encore construites — voir
        _build_columns_page) : juste une note, meme habillage que le corps
        des sections (voir _build_content)."""
        page = QWidget()
        page.setStyleSheet(f"background: {M['panel_bg']};")
        layout = QVBoxLayout(page)
        layout.setContentsMargins(20, 18, 18, 26)
        note = QLabel(f"Aucun reglage \"{title}\" pour le moment.")
        note.setFont(_qfont(12, 400))
        note.setStyleSheet(f"color: {M['group_note']}; background: transparent;")
        layout.addWidget(note)
        layout.addStretch(1)
        return page

    def _type_override_seed(self, key: str, default):
        """Valeur de depart d'un champ de surcharge (Colonnes > Type) : la
        derniere valeur ENREGISTREE pour cette surcharge si elle existe
        (column_type_overrides), sinon la valeur GENERALE courante (onglet
        General) — jamais `default` tout court, pour qu'activer le toggle
        la toute premiere fois affiche ce que la colonne montre DEJA (voir
        _apply_column_type_preview), pas une valeur arbitraire."""
        overrides = self.settings.get("column_type_overrides") or {}
        if key in overrides:
            return overrides[key]
        return self.settings.get(key, default)

    def _type_override_enabled(self, key: str) -> bool:
        return bool((self.settings.get("column_type_override_enabled") or {}).get(key, False))

    def _type_override_linked(self, key: str) -> bool:
        linked_map = self.settings.get("column_type_override_linked") or {}
        return bool(linked_map.get(key, self.settings.get(f"{key}_linked", True)))

    def _build_column_type_page(self) -> QWidget:
        """Onglet Colonnes > Type : surcharge, PARAMETRE PAR PARAMETRE, la
        section "Colonnes" de l'onglet General (voir _section_headers) sur
        la colonne "Type" — meme 4 tableaux (Colonnes/Entetes/Texte/
        Selection), memes champs, mais chaque ligne est precedee d'un
        toggle1 (voir _build_override_flat_table) : OFF (par defaut) grise
        la ligne et la colonne Type suit la valeur GENERALE ; ON active le
        champ de CETTE ligne, dont la valeur SURCHARGE alors la generale —
        en direct, dans l'apercu de cette fenetre (la boite "Type", voir
        _apply_column_type_preview) ET dans l'appli reelle (voir
        pipeline_browser.apply_all_settings/COLUMN_TYPE_OVERRIDE_KEYS) —
        voir la remarque de l'utilisateur, "je veux que tu appliques
        exactement le style de colonne (GENERAL/COLONNES) sur la colonne
        TYPE ... un toggle 1 en off, ce qui grisera la ligne ... le fait de
        mettre le toggle en ON overide le parametre et la modification est
        apportee en temps reel".

        `self._type_fields`/`self._type_toggles` (par CLE de reglage, pas
        par ligne d'UI — une ligne "Bordure" combinee gouverne 2 cles a la
        fois, *_border_enabled ET *_border, depuis le MEME champ/le MEME
        toggle, voir _current_values/_apply_column_type_preview) gardent la
        reference a chaque widget pour le reste de la fenetre."""
        page = QWidget()
        page.setStyleSheet(f"background: {M['panel_bg']};")
        outer = QVBoxLayout(page)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        scroller = _NoSqueezeScrollArea()
        scroller.setWidgetResizable(True)
        scroller.setFrameShape(QFrame.NoFrame)
        scroller.setStyleSheet(f"background: {M['panel_bg']};")
        inner = QWidget()
        layout = QVBoxLayout(inner)
        layout.setContentsMargins(20, 18, 18, 26)
        layout.setSpacing(18)

        note = QLabel(
            "Chaque ligne suit par defaut le reglage general (Colonnes, "
            "onglet General) — activez son interrupteur pour le surcharger "
            "sur cette colonne uniquement."
        )
        note.setWordWrap(True)
        note.setFont(_qfont(11, 400))
        note.setStyleSheet(f"color: {M['group_note']}; background: transparent;")
        layout.addWidget(note)

        self._type_fields: dict[str, QWidget] = {}
        self._type_toggles: dict[str, _Toggle] = {}

        def make_toggle(*keys: str) -> _Toggle:
            # show_label=False : pas de "actif"/"sans" a cote du cadre — voir
            # la remarque de l'utilisateur, "supprime tous les textes (sans
            # et actif) a cote des toggle d'overide".
            toggle = _Toggle(self._type_override_enabled(keys[0]), style_override="toggle1", show_label=False)
            for key in keys:
                self._type_toggles[key] = toggle
            return toggle

        # -- Colonnes (Padding/Bordure/Epaisseur/Rayon — "Distance entre
        # colonnes" exclue : un espacement ENTRE colonnes n'a pas de sens
        # pour une seule colonne, voir pipeline_browser.
        # COLUMN_TYPE_OVERRIDE_KEYS) --
        col_padding_toggle = make_toggle("column_padding")
        col_padding_field = _CellPaddingField(
            self._type_override_linked("column_padding"),
            self._type_override_seed("column_padding", {}) or {})
        self._type_fields["column_padding"] = col_padding_field

        col_border_toggle = make_toggle("column_border_enabled", "column_border")
        col_border_field = _ToggleSideColorsField(
            _coerce_side_enabled(self._type_override_seed("column_border_enabled", True)),
            self._type_override_seed("column_border", {}) or {}, self.settings["colors"])
        self._type_fields["column_border_enabled"] = col_border_field
        self._type_fields["column_border"] = col_border_field

        col_thickness_toggle = make_toggle("column_border_thickness")
        col_thickness_field = _SliderField(
            0, 8, int(self._type_override_seed("column_border_thickness", 1)), slider_width=200, box_width=68)
        self._type_fields["column_border_thickness"] = col_thickness_field

        col_radius_toggle = make_toggle("column_border_radius")
        col_radius_field = _CornerRadiusField(
            self._type_override_linked("column_border_radius"),
            _coerce_corner_radius(self._type_override_seed("column_border_radius", 0)), maximum=20)
        self._type_fields["column_border_radius"] = col_radius_field

        columns_frame, self._type_columns_row_meta, columns_resizer = _build_override_flat_table([
            ("Padding", col_padding_field, col_padding_toggle),
            ("Bordure", col_border_field, col_border_toggle),
            ("Epaisseur de bordure", col_thickness_field, col_thickness_toggle),
            ("Rayon des angles de bordure", col_radius_field, col_radius_toggle),
        ])
        self._flat_resizers.append(columns_resizer)
        columns_sub = _SubSection("Colonnes", indent=True)
        columns_sub.add(columns_frame)

        # -- Entetes --
        height_toggle = make_toggle("header_height")
        height_field = _SliderField(16, 56, int(self._type_override_seed("header_height", 26)), slider_width=200, box_width=68)
        self._type_fields["header_height"] = height_field

        padding_toggle = make_toggle("header_padding")
        padding_field = _SliderField(0, 32, int(self._type_override_seed("header_padding", 0)), slider_width=200, box_width=68)
        self._type_fields["header_padding"] = padding_field

        color_toggle = make_toggle("header_color")
        color_field = _HeaderColorField(self.settings["colors"], self._type_override_seed("header_color", "skinN1"))
        self._type_fields["header_color"] = color_field

        radius_toggle = make_toggle("header_radius")
        radius_field = _CornerRadiusField(
            self._type_override_linked("header_radius"),
            _coerce_corner_radius(self._type_override_seed("header_radius", 0)), maximum=16)
        self._type_fields["header_radius"] = radius_field

        border_toggle = make_toggle("header_border_enabled", "header_border")
        border_field = _ToggleSideColorsField(
            _coerce_side_enabled(self._type_override_seed("header_border_enabled", False)),
            self._type_override_seed("header_border", {}) or {}, self.settings["colors"])
        self._type_fields["header_border_enabled"] = border_field
        self._type_fields["header_border"] = border_field

        border_thickness_toggle = make_toggle("header_border_thickness")
        border_thickness_field = _SliderField(
            0, 8, int(self._type_override_seed("header_border_thickness", 1)), slider_width=200, box_width=68)
        self._type_fields["header_border_thickness"] = border_thickness_field

        headers_frame, self._type_headers_row_meta, headers_resizer = _build_override_flat_table([
            ("Hauteur des entetes", height_field, height_toggle),
            ("Padding des entetes", padding_field, padding_toggle),
            ("Couleur des entetes", color_field, color_toggle),
            ("Arrondi des angles", radius_field, radius_toggle),
            ("Bordure", border_field, border_toggle),
            ("Epaisseur de bordure", border_thickness_field, border_thickness_toggle),
        ])
        self._flat_resizers.append(headers_resizer)
        headers_sub = _SubSection("Entetes", indent=True)
        headers_sub.add(headers_frame)

        # -- Texte --
        font_toggle = make_toggle("item_font_family")
        font_field = _FontSelectField(
            _font_choices(), self._type_override_seed("item_font_family", "") or "Systeme", width=170, auto_label="Systeme")
        self._type_fields["item_font_family"] = font_field

        item_color_toggle = make_toggle("item_color")
        item_color_field = _ColorField(self._type_override_seed("item_color", "#d6d9dc"), swatch_size=24, title="Couleur")
        self._type_fields["item_color"] = item_color_field

        icon_toggle = make_toggle("item_icon_enabled")
        icon_field = _Toggle(bool(self._type_override_seed("item_icon_enabled", True)), style_override="toggle1")
        self._type_fields["item_icon_enabled"] = icon_field

        row_height_toggle = make_toggle("item_row_height")
        row_height_field = _SliderField(14, 80, int(self._type_override_seed("item_row_height", 25)), slider_width=170, box_width=68)
        self._type_fields["item_row_height"] = row_height_field

        row_spacing_toggle = make_toggle("item_row_spacing")
        row_spacing_field = _SliderField(0, 20, int(self._type_override_seed("item_row_spacing", 1)), slider_width=170, box_width=68)
        self._type_fields["item_row_spacing"] = row_spacing_field

        text_padding_toggle = make_toggle("item_text_padding")
        text_padding_field = _SliderField(0, 32, int(self._type_override_seed("item_text_padding", 8)), slider_width=170, box_width=68)
        self._type_fields["item_text_padding"] = text_padding_field

        text_frame, self._type_text_row_meta, text_resizer = _build_override_flat_table([
            ("Police", font_field, font_toggle),
            ("Couleur", item_color_field, item_color_toggle),
            ("Icone", icon_field, icon_toggle),
            ("Hauteur de la ligne", row_height_field, row_height_toggle),
            ("Espacement entre les lignes", row_spacing_field, row_spacing_toggle),
            ("Padding du texte", text_padding_field, text_padding_toggle),
        ])
        self._flat_resizers.append(text_resizer)
        text_sub = _SubSection("Texte", indent=True)
        text_sub.add(text_frame)

        # -- Selection --
        focus_toggle = make_toggle("item_selection_focus_color")
        focus_field = _ColorField(
            self._type_override_seed("item_selection_focus_color", "#3f6f9f"), swatch_size=24, title="Selection (focus)")
        self._type_fields["item_selection_focus_color"] = focus_field

        unfocus_toggle = make_toggle("item_selection_unfocus_color")
        unfocus_field = _ColorField(
            self._type_override_seed("item_selection_unfocus_color", "#2e3338"), swatch_size=24, title="Selection (hors focus)")
        self._type_fields["item_selection_unfocus_color"] = unfocus_field

        hover_toggle = make_toggle("item_hover_color")
        hover_field = _ColorField(
            self._type_override_seed("item_hover_color", "#232729"), swatch_size=24, title="Survol")
        self._type_fields["item_hover_color"] = hover_field

        sel_padding_toggle = make_toggle("item_selection_padding")
        sel_padding_field = _CellPaddingField(
            self._type_override_linked("item_selection_padding"),
            self._type_override_seed("item_selection_padding", {}) or {})
        self._type_fields["item_selection_padding"] = sel_padding_field

        sel_border_toggle = make_toggle("item_selection_border_enabled", "item_selection_border")
        sel_border_field = _ToggleSideColorsField(
            _coerce_side_enabled(self._type_override_seed("item_selection_border_enabled", False)),
            self._type_override_seed("item_selection_border", {}) or {}, self.settings["colors"])
        self._type_fields["item_selection_border_enabled"] = sel_border_field
        self._type_fields["item_selection_border"] = sel_border_field

        sel_radius_toggle = make_toggle("item_selection_radius")
        sel_radius_field = _CornerRadiusField(
            self._type_override_linked("item_selection_radius"),
            _coerce_corner_radius(self._type_override_seed("item_selection_radius", 0)), maximum=20)
        self._type_fields["item_selection_radius"] = sel_radius_field

        edge_border_toggle = make_toggle("item_selection_edge_border")
        edge_border_field = _Toggle(
            bool(self._type_override_seed("item_selection_edge_border", True)), style_override="toggle1")
        self._type_fields["item_selection_edge_border"] = edge_border_field

        selection_frame, self._type_selection_row_meta, selection_resizer = _build_override_flat_table([
            ("Couleur de selection en focus", focus_field, focus_toggle),
            ("Couleur de selection non focus", unfocus_field, unfocus_toggle),
            ("Couleur de survol", hover_field, hover_toggle),
            ("Padding du selecteur", sel_padding_field, sel_padding_toggle),
            ("Bordures du selecteur", sel_border_field, sel_border_toggle),
            ("Arrondi des coins de la selection", sel_radius_field, sel_radius_toggle),
            ("Bordure au bord de la colonne", edge_border_field, edge_border_toggle),
        ])
        self._flat_resizers.append(selection_resizer)
        selection_sub = _SubSection("Selection", indent=True)
        selection_sub.add(selection_frame)

        # Les 4 sous-groupes empiles ENSEMBLE, espacement ADAPTATIF uniforme
        # entre chacun (voir _stack_subsections/la remarque de l'utilisateur,
        # "je veux que tu normalises l'espacement entre les sections ...
        # comme tu l'avais fait pour les sections").
        subsections_wrap = QWidget()
        subsections_wrap.setStyleSheet("background: transparent;")
        subsections_wrap_l = QVBoxLayout(subsections_wrap)
        subsections_wrap_l.setContentsMargins(0, 0, 0, 0)
        _stack_subsections(subsections_wrap_l, [columns_sub, headers_sub, text_sub, selection_sub])
        layout.addWidget(subsections_wrap)

        layout.addStretch(1)
        scroller.setWidget(inner)
        outer.addWidget(scroller)
        # Pas de _Section englobante ici (juste ce scroller, voir plus haut)
        # pour rafraichir automatiquement — chaque sous-groupe doit donc
        # lui-meme forcer le recalcul de TOUT le contenu de la page quand il
        # se replie/deplie (voir _activate_layout_tree, meme necessite que
        # _Section.refresh_min_height : Qt ne fait pas remonter ca de lui-
        # meme au-dela d'1 niveau de QWidget imbrique — voir la remarque de
        # l'utilisateur, "il y a des bugs importants quand on plie/deplie
        # les sous sections").
        for sub in (columns_sub, headers_sub, text_sub, selection_sub):
            sub.collapsedChanged.connect(lambda _checked=False, inner=inner: _activate_layout_tree(inner))
        self._connect_column_type_overrides()
        return page

    def _connect_column_type_overrides(self):
        """Cable chaque champ/toggle de Colonnes > Type (voir
        _build_column_type_page) sur _mark_dirty (persistance + application
        en direct a l'appli reelle, voir SettingsWindow._mark_dirty/
        pipeline_browser.apply_all_settings/COLUMN_TYPE_OVERRIDE_KEYS) ET
        sur _apply_column_type_preview (rafraichit EN DIRECT la boite "Type"
        de l'apercu Colonnes, onglet General — meme principe que
        _connect_live_updates pour les champs generaux)."""
        signals = []
        for toggle in set(self._type_toggles.values()):
            signals.append(toggle.toggled)
        seen = set()
        for field in self._type_fields.values():
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
            sig.connect(self._apply_column_type_preview)
        self._apply_column_type_preview()

    def _resolve_type_effective(self, key: str):
        """Valeur EFFECTIVE (brute, voir _read_override_field_raw) d'une
        cle Colonnes > Type : celle de SON PROPRE champ si le toggle de la
        ligne est ON, sinon celle du champ GENERAL correspondant (voir
        _TYPE_GENERAL_FIELD_ATTR) — repli final sur self.settings si le
        champ general n'existe pas encore (fenetre en cours de
        construction)."""
        toggle = self._type_toggles.get(key)
        if toggle is not None and toggle.isChecked() and key in self._type_fields:
            return _read_override_field_raw(key, self._type_fields[key])
        general_widget = getattr(self, _TYPE_GENERAL_FIELD_ATTR.get(key, ""), None)
        if general_widget is not None:
            return _read_override_field_raw(key, general_widget)
        return self.settings.get(key)

    def _apply_column_type_preview(self, *_args):
        """Rejoue, sur la SEULE boite "Type" de l'apercu Colonnes (onglet
        General, voir _section_headers/self.column_previews[0]), le style
        EFFECTIF de Colonnes > Type (general ou surcharge par ligne, voir
        _resolve_type_effective) — meme principe/memes methodes que
        _apply_column_preview/_apply_item_preview, mais valeur par valeur
        plutot qu'un seul jeu de reglages partage par les 3 boites. Sans
        effet tant que _build_column_type_page n'a pas encore construit
        self._type_toggles (voir son appel a _connect_column_type_overrides,
        avant que self.column_previews existe meme — garde en tete de
        methode)."""
        if not hasattr(self, "_type_toggles") or not getattr(self, "column_previews", None):
            return
        live_colors = dict(self.settings["colors"])
        live_colors.update(self.color_grid.value())

        def hexval(value) -> str:
            if isinstance(value, str) and value.startswith("#"):
                return value
            return live_colors.get(_SLOT_REAL.get(value, "chrome"), "#000000")

        def colors_of(d: dict) -> dict:
            return {k: _resolve_color_value(v, live_colors) for k, v in (d or {}).items()}

        vals = {key: self._resolve_type_effective(key) for key in _COLUMN_TYPE_OVERRIDE_KEYS}
        preview = self.column_previews[0]
        preview.refresh(
            int(vals["header_height"]), int(vals["header_padding"]), hexval(vals["header_color"]),
            _nibble_header_radius(vals["header_radius"], vals["column_border_radius"], int(vals["header_padding"])),
            vals["header_border_enabled"],
            colors_of(vals["header_border"]), int(vals["header_border_thickness"]),
        )
        preview.setBorder(
            vals["column_border_enabled"], colors_of(vals["column_border"]),
            int(vals["column_border_thickness"]), vals["column_border_radius"],
        )
        preview.setPadding(vals["column_padding"])
        font_family = vals["item_font_family"] or ""
        preview.setItemStyle(
            font_family=font_family,
            color_hex=vals["item_color"],
            icon_enabled=bool(vals["item_icon_enabled"]),
            row_height=int(vals["item_row_height"]),
            row_spacing=int(vals["item_row_spacing"]),
            text_padding=int(vals["item_text_padding"]),
            hover_color=vals["item_hover_color"],
            focus_color=vals["item_selection_focus_color"],
            unfocus_color=vals["item_selection_unfocus_color"],
            padding=vals["item_selection_padding"],
            enabled=vals["item_selection_border_enabled"],
            colors=colors_of(vals["item_selection_border"]),
            radius=vals["item_selection_radius"],
            edge_border=bool(vals["item_selection_edge_border"]),
        )

    # -- contenu (sections) --

    def _build_content(self) -> QWidget:
        # _NoSqueezeScrollArea (pas QScrollArea nu) : la fenetre reste
        # redimensionnable librement (y compris plus bas que le contenu),
        # mais une scrollbar verticale apparait alors a droite au lieu de
        # tasser les lignes de reglage les unes contre les autres — voir la
        # remarque de l'utilisateur, capture a l'appui.
        scroller = _NoSqueezeScrollArea()
        self._content_scroller = scroller
        scroller.setWidgetResizable(True)
        scroller.setFrameShape(QFrame.NoFrame)
        scroller.setStyleSheet(f"background: {M['panel_bg']};")
        inner = QWidget()
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
        sections = [
            self._section_application(),
            self._section_fonts(),
            self._section_colors(),
            self._section_geometry(),
            self._section_headers(),
            self._section_tables(),
            self._section_toggles(),
            self._section_slider(),
        ]
        # TOUTES repliees par defaut a l'ouverture, "Application" y compris
        # — voir la remarque de l'utilisateur, "je veux que toutes les
        # sections (y compris sous sections) soient repliees a l'ouverture
        # de la fenetre de settings" (revient sur l'exception faite plus
        # haut pour "Application"). Fait AVANT la boucle ci-dessous : le
        # spaceur de chaque section lit is_collapsed() a sa creation pour
        # partir a la bonne hauteur.
        for section in sections:
            section.set_collapsed(True)
        for i, section in enumerate(sections):
            layout.addWidget(section)
            if i == len(sections) - 1:
                continue
            spacer = QWidget()
            spacer.setFixedHeight(_SECTION_GAP_COLLAPSED if section.is_collapsed() else _SECTION_GAP_EXPANDED)
            section.collapsedChanged.connect(
                lambda collapsed, s=spacer: s.setFixedHeight(
                    _SECTION_GAP_COLLAPSED if collapsed else _SECTION_GAP_EXPANDED
                )
            )
            layout.addWidget(spacer)
        # Accordeon entre les sections PRINCIPALES elles-memes (voir
        # _make_accordion, deja applique aux sous-sections DANS chaque
        # section, voir _stack_subsections) — meme comportement, un seul
        # niveau plus haut.
        _make_accordion(sections)
        layout.addStretch(1)
        scroller.setWidget(inner)
        return scroller

    def _section_application(self) -> _Section:
        section = _Section("Application")

        self.root_field = QLineEdit(self.settings["root_path"])
        self.root_field.setFont(_qfont(12, 400, mono=True))
        self.root_field.setFixedSize(268, 25)
        self._refresh_root_field_style()
        # radius=self.settings[...] (self.geo_table pas encore construit a
        # ce stade — voir _apply_button_radius pour le suivi en direct).
        browse_btn = _Btn("Parcourir", M["btn_bg"], M["btn_border"], M["btn_fg"], M["btn_hover"], height=25,
                           radius=int(self.settings.get("button_radius", 0)))
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

        self.scale_field = _SliderField(50, 200, int(self.settings["ui_scale"]), "%", slider_width=280, box_width=68)

        # Tableau ferme (voir _build_flat_table — meme technique que
        # Colonnes/Sliders) plutot que 2 _Row nues, pour rester coherent
        # avec le reste de la fenetre — voir la remarque de l'utilisateur.
        self.app_table_frame, self._app_table_row_meta, resizer = _build_flat_table([
            ("Racine par defaut", root_row),
            ("Scale interface", self.scale_field),
        ])
        self._flat_resizers.append(resizer)
        section.add(self.app_table_frame)
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

    def _section_headers(self) -> _Section:
        section = _Section("Colonnes")
        # Apercu de l'element concerne par la section, centre (voir
        # _section_preview_wrap/la remarque de l'utilisateur, "fait deux
        # colonnes cote a cote de 150px chacune de large et 250px de
        # hauteur") — voir _ColumnPreview/_apply_column_preview, qui les
        # tient a jour EN DIRECT (Hauteur/Padding/Couleur/Arrondi/Cadre des
        # entetes/Distance entre colonnes).
        preview_row = QWidget()
        preview_row.setStyleSheet("background: transparent;")
        self.column_preview_row_l = QHBoxLayout(preview_row)
        self.column_preview_row_l.setContentsMargins(0, 0, 0, 0)
        # Chaque boite masque son propre filet GAUCHE quand column_gap()<=0
        # (voir _ColumnPreview/app_style.column_seam_border, meme
        # repartition que Column.border-right TOUJOURS peint vs
        # DetailPanel.border-left CONDITIONNEL) : un SEUL filet reste
        # visible a chaque frontiere collee (celui de DROITE de la boite de
        # gauche) plutot que 2 cumules OU aucun — voir la remarque de
        # l'utilisateur, "je veux que les deux bordures qui se chevauchent
        # n'en forment qu'une seule". Trois boites (Type/Projets/Sous-
        # projet, voir la remarque de l'utilisateur, "rajoute une troisieme
        # colonne") ; has_left_neighbor=False seulement sur la 1ere (aucune
        # boite a sa gauche — voir _ColumnPreview, la remarque de
        # l'utilisateur, "on perd la bordure a gauche de la premiere
        # colonne"), has_right_neighbor=False seulement sur la derniere
        # (aucune boite a sa droite — voir _ColumnPreview._corner_radii, la
        # remarque de l'utilisateur, "si deux colonnes sont cote a cote ...
        # le rayon de bordure contre l'autre colonne doit etre a zero").
        self.column_previews = [
            _ColumnPreview("Type", "12", has_left_neighbor=False),
            _ColumnPreview("Projets", "4"),
            _ColumnPreview("Sous-projet", "7", has_right_neighbor=False),
        ]
        for preview in self.column_previews:
            self.column_preview_row_l.addWidget(preview)
        section.add(_section_preview_wrap(preview_row))

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
        self.header_border_field = _ToggleSideColorsField(
            _coerce_side_enabled(self.settings.get("header_border_enabled")
                                  or self.settings.get("header_edges") or {}, default=False),
            self.settings.get("header_border") or {}, self.settings["colors"])
        self.header_border_thickness_field = _SliderField(
            0, 8, int(self.settings.get("header_border_thickness", 1)), slider_width=280, box_width=68)
        # Distance entre colonnes (voir app_style.set_column_gap/
        # pipeline_browser.PipelineBrowser.columns_layout) — voir la
        # remarque de l'utilisateur, "ajoute un parametre 'distance entre
        # colonne' en px". Minimum -1 (pas 0) : chaque colonne a deja son
        # propre filet de separation de 1px (voir Column, sep_v) — un
        # espacement de -1 les superpose au lieu de les cumuler en un
        # filet de 2px visible, voir la remarque de l'utilisateur, "de
        # maniere a ce que les bordures ne se cumulent pas".
        self.column_gap_field = _SliderField(
            -1, 40, int(self.settings.get("column_gap", 0)), slider_width=280, box_width=68)
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
        self.column_border_field = _ToggleSideColorsField(
            _coerce_side_enabled(self.settings.get("column_border_enabled", True)),
            self.settings.get("column_border") or {}, self.settings["colors"])
        self.column_border_thickness_field = _SliderField(
            0, 8, int(self.settings.get("column_border_thickness", 1)), slider_width=280, box_width=68)
        self.column_border_radius_field = _CornerRadiusField(
            bool(self.settings.get("column_border_radius_linked", True)),
            _coerce_corner_radius(self.settings.get("column_border_radius", 0)), maximum=20)

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
        columns_frame, self._columns_table_row_meta, columns_resizer = _build_flat_table([
            ("Distance entre colonnes", self.column_gap_field),
            ("Padding", self.column_padding_field),
            ("Bordure", self.column_border_field),
            ("Epaisseur de bordure", self.column_border_thickness_field),
            ("Rayon des angles de bordure", self.column_border_radius_field),
        ])
        self._flat_resizers.append(columns_resizer)
        self.columns_table_frame = columns_frame
        columns_sub = _SubSection("Colonnes", indent=True)
        columns_sub.add(columns_frame)
        columns_sub.collapsedChanged.connect(section.refresh_min_height)

        headers_frame, self._headers_table_row_meta, headers_resizer = _build_flat_table([
            ("Hauteur des entetes", self.header_height_field),
            ("Padding des entetes", self.header_padding_field),
            ("Couleur des entetes", self.header_color_field),
            ("Arrondi des angles", self.header_radius_field),
            ("Bordure", self.header_border_field),
            ("Epaisseur de bordure", self.header_border_thickness_field),
        ])
        self._flat_resizers.append(headers_resizer)
        self.headers_table_frame = headers_frame
        headers_sub = _SubSection("Entetes", indent=True)
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

        self.item_font_field = _FontSelectField(
            _font_choices(), self.settings.get("item_font_family") or "Systeme", width=170, auto_label="Systeme")
        self.item_color_field = _ColorField(self.settings.get("item_color", "#d6d9dc"), swatch_size=24, title="Couleur")
        # Toggle1 explicitement (voir la remarque de l'utilisateur, "icone
        # ou non (toggle 1)") — PAS le style COURANT de Toggles > Style,
        # meme mecanique que les interrupteurs par cote de _SideColorsField
        # (style_override), mais figee sur "toggle1" ici plutot que
        # "toggle2".
        self.item_icon_field = _Toggle(
            bool(self.settings.get("item_icon_enabled", True)), style_override="toggle1")
        self.item_row_height_field = _SliderField(
            14, 80, int(self.settings.get("item_row_height", 25)), slider_width=200, box_width=68)
        # Espacement (px) ENTRE les lignes (voir pipeline_browser.
        # ROW_SPACING) — distinct de "Hauteur de la ligne" (la hauteur
        # d'UNE ligne) — voir la remarque de l'utilisateur, "ajoute un
        # parametre espacement entre les lignes".
        self.item_row_spacing_field = _SliderField(
            0, 20, int(self.settings.get("item_row_spacing", 1)), slider_width=200, box_width=68)
        self.item_text_padding_field = _SliderField(
            0, 32, int(self.settings.get("item_text_padding", 8)), slider_width=200, box_width=68)

        text_frame, self._item_text_row_meta, text_resizer = _build_flat_table([
            ("Police", self.item_font_field),
            ("Couleur", self.item_color_field),
            ("Icone", self.item_icon_field),
            ("Hauteur de la ligne", self.item_row_height_field),
            ("Espacement entre les lignes", self.item_row_spacing_field),
            ("Padding du texte", self.item_text_padding_field),
        ])
        self._flat_resizers.append(text_resizer)
        self.item_text_frame = text_frame
        text_sub = _SubSection("Texte", indent=True)
        text_sub.add(text_frame)
        text_sub.collapsedChanged.connect(section.refresh_min_height)

        self.item_selection_focus_field = _ColorField(
            self.settings.get("item_selection_focus_color", "#3f6f9f"), swatch_size=24, title="Selection (focus)")
        self.item_selection_unfocus_field = _ColorField(
            self.settings.get("item_selection_unfocus_color", "#2e3338"), swatch_size=24, title="Selection (hors focus)")
        self.item_hover_field = _ColorField(
            self.settings.get("item_hover_color", "#232729"), swatch_size=24, title="Survol")
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

        selection_frame, self._item_selection_row_meta, selection_resizer = _build_flat_table([
            ("Couleur de selection en focus", self.item_selection_focus_field),
            ("Couleur de selection non focus", self.item_selection_unfocus_field),
            ("Couleur de survol", self.item_hover_field),
            ("Padding du selecteur", self.item_selection_padding_field),
            ("Bordures du selecteur", self.item_selection_border_field),
            ("Arrondi des coins de la selection", self.item_selection_radius_field),
            ("Bordure au bord de la colonne", self.item_selection_edge_border_field),
        ])
        self._flat_resizers.append(selection_resizer)
        self.item_selection_frame = selection_frame
        selection_sub = _SubSection("Selection", indent=True)
        selection_sub.add(selection_frame)
        selection_sub.collapsedChanged.connect(section.refresh_min_height)

        # Les 4 sous-groupes empiles ENSEMBLE (pas 2 paires separees comme
        # avant), espacement ADAPTATIF UNIFORME entre chacun (voir
        # _stack_subsections/la remarque de l'utilisateur, "je veux que tu
        # normalises l'espacement entre les sections ... comme tu l'avais
        # fait pour les sections").
        subsections_wrap = QWidget()
        subsections_wrap.setStyleSheet("background: transparent;")
        subsections_wrap_l = QVBoxLayout(subsections_wrap)
        subsections_wrap_l.setContentsMargins(0, 0, 0, 0)
        _stack_subsections(subsections_wrap_l, [columns_sub, headers_sub, text_sub, selection_sub])
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
        # Apercu de l'element concerne par la section, centre (voir
        # _section_preview_wrap/la remarque de l'utilisateur, "un tableau
        # de 2 colonnes et 3 lignes avec entete") — voir _TablePreview,
        # inclus comme un 3e tableau a en-tete dans _apply_table_radius/
        # _apply_cell_padding/_apply_table_head_color plus bas.
        self.table_preview = _TablePreview()
        section.add(_section_preview_wrap(self.table_preview))
        self.columns_resizable_toggle = _Toggle(bool(self.settings.get("columns_resizable", True)))
        # Deplace ici depuis Geometrie (voir la remarque de l'utilisateur,
        # capture a l'appui : ce reglage concerne les tableaux, pas la
        # geometrie generale — colle desormais avec sa propre section).
        self.table_radius_field = _SliderField(
            0, 16, int(self.settings.get("table_radius", 0)), slider_width=140, box_width=58)
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
        frame, self._tables_row_meta, resizer = _build_flat_table([
            ("Colonnes dimensionnables", self.columns_resizable_toggle),
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
        style_frame, self._toggles_row_meta, resizer = _build_flat_table([
            ("Style", self.toggle_style_field),
        ])
        self._flat_resizers.append(resizer)
        self.toggles_table_frame = style_frame
        section.add(style_frame)

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
        self._toggle_frames: dict[str, dict[str, tuple]] = {}
        self._toggle_style_pages: dict[str, QWidget] = {}
        style_subs = []
        for prefix, label in (("toggle1", "Toggle 1"), ("toggle2", "Toggle 2")):
            page = QWidget()
            page.setStyleSheet("background: transparent;")
            page_l = QVBoxLayout(page)
            page_l.setContentsMargins(0, 0, 0, 0)
            page_l.setSpacing(0)
            style_sub = _SubSection(label)
            # Cadre/Coche sont ici imbriques SOUS style_sub, elle-meme sous
            # `section` ("Toggles") : refresh_min_height recalcule tout
            # l'arbre (voir _activate_layout_tree), peu importe la
            # profondeur — un simple branchement direct suffit donc a
            # CHAQUE niveau.
            columns_wrap, widgets, frames = self._build_toggle_shape_tables(prefix, section.refresh_min_height)
            style_sub.add(columns_wrap)
            style_sub.set_collapsed(True)  # voir _stack_subsections, meme raison
            style_sub.collapsedChanged.connect(section.refresh_min_height)
            page_l.addWidget(style_sub)
            section.add(page)
            self._toggle_widgets[prefix] = widgets
            self._toggle_frames[prefix] = frames
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
        w: dict[str, QWidget] = {
            "outer_width": _SliderField(4, 80, int(s.get(f"{prefix}_outer_width", 29)), slider_width=90, box_width=54),
            "outer_height": _SliderField(4, 60, int(s.get(f"{prefix}_outer_height", 14)), slider_width=90, box_width=54),
            "outer_border": _ToggleSideColorsField(
                _coerce_side_enabled(s.get(f"{prefix}_outer_border_enabled", True)), s.get(f"{prefix}_outer_border") or {},
                s["colors"]),
            "outer_border_thickness": _SliderField(
                0, 8, int(s.get(f"{prefix}_outer_border_thickness", 1)), slider_width=90, box_width=54),
            "outer_border_radius": _CornerRadiusField(
                bool(s.get(f"{prefix}_outer_border_radius_linked", True)),
                _coerce_corner_radius(s.get(f"{prefix}_outer_border_radius", 0)), maximum=20),
            "outer_bg": _ColorField(s.get(f"{prefix}_outer_bg", "#141618"), swatch_size=24, title="Fond"),
            "coche_width": _SliderField(2, 60, int(s.get(f"{prefix}_coche_width", 11)), slider_width=90, box_width=54),
            "coche_margin": _SliderField(0, 30, int(s.get(f"{prefix}_coche_margin", 4)), slider_width=90, box_width=54),
            "coche_border": _ToggleSideColorsField(
                _coerce_side_enabled(s.get(f"{prefix}_coche_border_enabled", True)), s.get(f"{prefix}_coche_border") or {},
                s["colors"]),
            "coche_border_thickness": _SliderField(
                0, 8, int(s.get(f"{prefix}_coche_border_thickness", 1)), slider_width=90, box_width=54),
            "coche_border_radius": _CornerRadiusField(
                bool(s.get(f"{prefix}_coche_border_radius_linked", True)),
                _coerce_corner_radius(s.get(f"{prefix}_coche_border_radius", 0)), maximum=20),
            "coche_color": _ColorField(s.get(f"{prefix}_coche_color", "#3f6f9f"), swatch_size=24, title="Couleur"),
        }

        outer_frame, outer_meta, outer_resizer = _build_flat_table([
            ("Largeur", w["outer_width"]),
            ("Hauteur", w["outer_height"]),
            ("Bordure", w["outer_border"]),
            ("Epaisseur de bordure", w["outer_border_thickness"]),
            ("Rayon des angles", w["outer_border_radius"]),
            ("Fond", w["outer_bg"]),
        ])
        self._flat_resizers.append(outer_resizer)
        outer_sub = _SubSection("Cadre", indent=True)
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
            ("Epaisseur de bordure", w["coche_border_thickness"]),
            ("Rayon des angles", w["coche_border_radius"]),
            ("Couleur", w["coche_color"]),
        ])
        self._flat_resizers.append(coche_resizer)
        coche_sub = _SubSection("Coche", indent=True)
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
            int(self.settings.get("window_radius", 0)),
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
        self.slider_thumb_frame, self._slider_thumb_row_meta, resizer = _build_flat_table([
            ("Largeur", self.slider_thumb_width_field),
            ("Hauteur", self.slider_thumb_height_field),
            ("Couleur", self.slider_thumb_color_field),
            ("Bordure", self.slider_thumb_border_field),
            ("Rayon des angles", self.slider_thumb_radius_field),
        ])
        self._flat_resizers.append(resizer)
        thumb_sub = _SubSection("Selecteur", indent=True)
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
        self.slider_rail_frame, self._slider_rail_row_meta, resizer = _build_flat_table([
            ("Hauteur", self.slider_track_height_field),
            ("Rail parcouru", self.slider_track_fill_field),
            ("Rail a parcourir", self.slider_track_empty_field),
            ("Bordure", self.slider_track_border_field),
            ("Rayon des angles", self.slider_track_radius_field),
        ])
        self._flat_resizers.append(resizer)
        rail_sub = _SubSection("Rail", indent=True)
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
        btn_radius = self.geo_table.button_radius_field.value()

        reset_btn = _Btn("Valeurs par defaut", "transparent", M["btn_border"], M["reset_fg"], M["btn_bg"],
                          height=27, padding="0 12px", radius=btn_radius)
        reset_btn.clicked.connect(self._reset_defaults)
        layout.addWidget(reset_btn)
        layout.addStretch(1)

        apply_btn = _Btn("Appliquer", M["btn_bg"], M["btn_border"], M["btn_fg"], M["btn_hover"],
                          height=27, padding="0 13px", radius=btn_radius)
        apply_btn.clicked.connect(self._on_apply)
        layout.addWidget(apply_btn)

        cancel_btn = _Btn("Annuler", M["btn_bg"], M["btn_border"], M["btn_fg"], M["btn_hover"],
                           height=27, padding="0 13px", radius=btn_radius)
        cancel_btn.clicked.connect(self.reject)
        layout.addWidget(cancel_btn)

        save_btn = _Btn("Enregistrer", M["accent"], M["accent_border"], M["accent_fg"], M["accent_hover"],
                        height=27, weight=600, padding="0 17px", radius=btn_radius)
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

    def _apply_panel_radius(self, radius: int):
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

    def _connect_live_updates(self):
        # La racine par defaut suivait auparavant seulement Appliquer/
        # Enregistrer (voir _on_apply) ; l'utilisateur veut desormais que
        # TOUT changement se repercute en direct, sans exception.
        self.root_field.textChanged.connect(self._mark_dirty)
        self.scale_field.valueChanged.connect(self._mark_dirty)
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
        self.header_height_field.valueChanged.connect(self._mark_dirty)
        self.header_padding_field.valueChanged.connect(self._mark_dirty)
        self.header_color_field.changed.connect(self._mark_dirty)
        self.header_radius_field.changed.connect(self._mark_dirty)
        self.header_border_field.changed.connect(self._mark_dirty)
        self.header_border_thickness_field.valueChanged.connect(self._mark_dirty)
        self.column_gap_field.valueChanged.connect(self._mark_dirty)
        self.column_padding_field.changed.connect(self._mark_dirty)
        self.column_border_field.changed.connect(self._mark_dirty)
        self.column_border_thickness_field.valueChanged.connect(self._mark_dirty)
        self.column_border_radius_field.changed.connect(self._mark_dirty)
        # Apercu Colonnes (voir _ColumnPreview) : contrairement au reste
        # ci-dessus, doit AUSSI se redessiner EN DIRECT (pas seulement
        # _mark_dirty — cet apercu ne vit que dans cette fenetre, rien ne
        # le repeint via apply_all_settings).
        for field_signal in (
            self.header_height_field.valueChanged, self.header_padding_field.valueChanged,
            self.header_color_field.changed, self.header_radius_field.changed,
            self.header_border_field.changed, self.header_border_thickness_field.valueChanged,
            self.column_gap_field.valueChanged, self.column_padding_field.changed,
            self.column_border_field.changed,
            self.column_border_thickness_field.valueChanged, self.column_border_radius_field.changed,
        ):
            field_signal.connect(self._apply_column_preview)
            # Colonnes > Type (voir _apply_column_type_preview) : une ligne
            # dont le toggle est OFF suit CE champ general — la boite
            # "Type" de l'apercu doit donc AUSSI se redessiner quand il
            # bouge, pas seulement quand un champ de Colonnes > Type change.
            if hasattr(self, "_type_toggles"):
                field_signal.connect(self._apply_column_type_preview)
        self._apply_column_preview()
        # Items (voir _section_items/_ItemRowPreview) : meme principe que
        # l'apercu Colonnes juste au-dessus (_mark_dirty PARTOUT +
        # redessin EN DIRECT de l'apercu, propre a cette fenetre).
        self.item_font_field.changed.connect(self._mark_dirty)
        self.item_color_field.changed.connect(self._mark_dirty)
        self.item_icon_field.toggled.connect(self._mark_dirty)
        self.item_row_height_field.valueChanged.connect(self._mark_dirty)
        self.item_row_spacing_field.valueChanged.connect(self._mark_dirty)
        self.item_text_padding_field.valueChanged.connect(self._mark_dirty)
        self.item_selection_focus_field.changed.connect(self._mark_dirty)
        self.item_selection_unfocus_field.changed.connect(self._mark_dirty)
        self.item_hover_field.changed.connect(self._mark_dirty)
        self.item_selection_padding_field.changed.connect(self._mark_dirty)
        self.item_selection_border_field.changed.connect(self._mark_dirty)
        self.item_selection_radius_field.changed.connect(self._mark_dirty)
        self.item_selection_edge_border_field.toggled.connect(self._mark_dirty)
        for field_signal in (
            self.item_font_field.changed, self.item_color_field.changed, self.item_icon_field.toggled,
            self.item_row_height_field.valueChanged, self.item_row_spacing_field.valueChanged,
            self.item_text_padding_field.valueChanged,
            self.item_selection_focus_field.changed, self.item_selection_unfocus_field.changed,
            self.item_hover_field.changed, self.item_selection_padding_field.changed,
            self.item_selection_border_field.changed, self.item_selection_radius_field.changed,
            self.item_selection_edge_border_field.toggled,
        ):
            field_signal.connect(self._apply_item_preview)
            if hasattr(self, "_type_toggles"):
                field_signal.connect(self._apply_column_type_preview)
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
                "outer_border", "coche_border", "outer_bg", "coche_color",
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
        self.geo_table.input_radius_field.valueChanged.connect(self._apply_dropdown_radius)
        self._apply_dropdown_radius(self.geo_table.input_radius_field.value())
        self.table_radius_field.valueChanged.connect(self._apply_table_radius)
        self._apply_table_radius(self.table_radius_field.value())
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
        self.geo_table.button_radius_field.valueChanged.connect(self._apply_button_radius)
        self._apply_button_radius(self.geo_table.button_radius_field.value())

    def _apply_button_radius(self, radius: int):
        for btn in (
            self._preset_save_btn, self._browse_btn,
            self._bottombar_reset_btn, self._bottombar_apply_btn,
            self._bottombar_cancel_btn, self._bottombar_save_btn,
            self.cell_padding_field.copy_btn,
            self.slider_thumb_border_field.copy_btn,
            self.slider_track_border_field.copy_btn,
            self.column_border_field.copy_btn,
            self.header_border_field.copy_btn,
            self.item_selection_padding_field.copy_btn,
            self.item_selection_border_field.copy_btn,
            self.header_radius_field.copy_btn,
            self.column_border_radius_field.copy_btn,
        ):
            btn.setRadius(radius)
        for w in self._toggle_widgets.values():
            w["outer_border"].copy_btn.setRadius(radius)
            w["coche_border"].copy_btn.setRadius(radius)
            w["outer_border_radius"].copy_btn.setRadius(radius)
            w["coche_border_radius"].copy_btn.setRadius(radius)
        self.item_selection_radius_field.copy_btn.setRadius(radius)
        self.slider_thumb_radius_field.copy_btn.setRadius(radius)
        self.slider_track_radius_field.copy_btn.setRadius(radius)

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
        self.font_table.head.setResizable(enabled)
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
        _sync_toggle_style(settings)
        for toggle in self.findChildren(_Toggle):
            toggle.apply_style()
        self.toggle_style_field.refreshPreviews()
        self._sync_toggle_style_visibility()
        self._mark_dirty()

    def _apply_dropdown_radius(self, radius: int):
        """Applique le rayon a TOUTES les boites habillees comme une zone de
        saisie (voir _SelectField/_HeaderColorField/_SliderField.setRadius) :
        pas seulement les vrais QLineEdit de la fenetre principale, mais
        aussi les menus deroulants, les boites de valeur des sliders, et la
        boite de preset — voir la remarque de l'utilisateur, capture a
        l'appui."""
        for entry in self.font_table.rows.values():
            entry["field"].setRadius(radius)
        self.header_color_field.setRadius(radius)
        self.table_head_color_field.setRadius(radius)
        self.item_font_field.setRadius(radius)
        for slider_field in (
            self.scale_field, self.header_height_field, self.header_padding_field,
            self.header_radius_field, self.header_border_thickness_field,
            self.column_gap_field, self.column_border_thickness_field, self.column_border_radius_field,
            self.geo_table.window_radius_field,
            self.geo_table.input_radius_field, self.geo_table.button_radius_field,
            self.table_radius_field, self.slider_thumb_width_field,
            self.slider_thumb_height_field, self.slider_track_height_field,
            self.slider_thumb_radius_field, self.slider_track_radius_field,
            self.item_row_height_field, self.item_row_spacing_field, self.item_text_padding_field,
            self.item_selection_radius_field,
        ):
            slider_field.setRadius(radius)
        self.cell_padding_field.setRadius(radius)
        self.item_selection_padding_field.setRadius(radius)
        self._sync_preset_box()

    def _apply_column_preview(self, *_args):
        """Colonnes > l'apercu (voir _ColumnPreview) : relit les reglages
        de la section et les rejoue sur les colonnes de demonstration —
        voir la remarque de l'utilisateur. _current_hex() (pas
        self.settings["colors"]) : meme raison que _apply_table_head_color,
        lit la palette LIVE que le champ suit deja pendant un glisser de la
        page Couleurs.

        column_gap_field EN PLUS des 4 autres (Hauteur/Padding/Couleur/
        Arrondi/Cadre) depuis la remarque de l'utilisateur, "ajoute un
        parametre 'distance entre colonne'... fait en sorte que l'apercu
        se mette bien a jour avec ca" — pilote l'espacement ENTRE les 2
        colonnes de demonstration plutot que leur contenu propre, d'ou le
        setSpacing sur le layout qui les empile plutot qu'un appel a
        preview.refresh() — meme comportement que le vrai navigateur (voir
        pipeline_browser.PipelineBrowser._apply_settings/app_style.
        column_seam_border), PAS une reinterpretation propre a l'apercu :
        voir la remarque de l'utilisateur, "je veux que le fonctionnement
        de l'apercu soit le meme que dans l'appli". max(0, ...) avant
        setSpacing (comme cote navigateur) : QBoxLayout.setSpacing() n'accepte
        PAS un espacement reellement negatif, TOUTE valeur negative y
        retombe silencieusement sur l'espacement du STYLE (6px ici) plutot
        que -1px reel — sans ce clamp, les 2 pastilles s'ecartaient au lieu
        de se toucher a Distance < 0 (voir la remarque de l'utilisateur,
        "les colonnes s'ecartent... dans cet apercu"). Le filet manquant
        est gere a la place par setSeamHidden (voir _ColumnPreview), pas
        par un espacement negatif — meme mecanisme que column_seam_border."""
        hexval = self.header_color_field._current_hex()
        edges = self.header_border_field.sidesEnabledValue()
        gap = self.column_gap_field.value()
        live_colors = dict(self.settings["colors"])
        live_colors.update(self.color_grid.value())
        header_border_colors = {
            k: _resolve_color_value(v, live_colors) for k, v in self.header_border_field.sidesValue().items()
        }
        border_enabled = self.column_border_field.sidesEnabledValue()
        border_colors = {
            k: _resolve_color_value(v, live_colors) for k, v in self.column_border_field.sidesValue().items()
        }
        header_radius = _nibble_header_radius(
            self.header_radius_field.cornersValue(), self.column_border_radius_field.cornersValue(),
            self.header_padding_field.value())
        pad = self.column_padding_field.sidesValue()
        # MEME regle que pipeline_browser.Column._suppress_left (PAS
        # seulement gap<=0, voir sa docstring) : 2 boites ne fusionnent leur
        # filet/coin QUE si elles se touchent VRAIMENT — un padding actif
        # d'un cote ou de l'autre les ecarte deja, meme a gap<=0, et leurs 2
        # filets/coins arrondis doivent alors REAPPARAITRE — voir la
        # remarque de l'utilisateur, "il devrait y avoir un coin arrondi
        # entre les colonnes car le padding des colonnes est different de
        # 0 ... pareil pour les bordures". Toutes les boites partagent ICI
        # le MEME padding general (Colonnes > Type peut le surcharger pour
        # la 1ere boite seule, voir _apply_column_type_preview, qui rejoue
        # setPadding/setBorder par-dessus mais pas ce seam — ecart mineur,
        # deja la avant ce correctif).
        seam_hidden = gap <= 0 and int(pad.get("left", 0)) <= 0 and int(pad.get("right", 0)) <= 0
        # Fond REEL de la colonne (voir _ColumnPreview.setFillColor) :
        # C['void'] ("skin - niveau2"), MEME couleur que pipeline_browser.
        # Column.refresh_colors (card.setFrameStyle(C["void"], ...)) —
        # live_colors.get("void", ...) (pas C["void"] directement) : suit
        # la palette LIVE pendant un glisser de la page Couleurs, meme
        # raison que header_border_colors/border_colors ci-dessus — voir la
        # remarque de l'utilisateur, "la couleur de fond de colonne est
        # fausse dans l'apercu".
        fill_hex = live_colors.get("void", C["void"])
        for preview in self.column_previews:
            preview.refresh(
                self.header_height_field.value(), self.header_padding_field.value(),
                hexval, header_radius, edges,
                header_border_colors, self.header_border_thickness_field.value(),
            )
            preview.setBorder(
                border_enabled, border_colors,
                self.column_border_thickness_field.value(), self.column_border_radius_field.cornersValue(),
            )
            preview.setFillColor(fill_hex)
            preview.setPadding(pad)
            preview.setSeamHidden(seam_hidden)
        self.column_preview_row_l.setSpacing(max(0, gap))

    def _apply_item_preview(self, *_args):
        """Items > Texte/Selection : relit les reglages des 2 tableaux et
        les rejoue sur les 4 lignes de demonstration DE CHACUNE des boites
        Type/Projets/Sous-projet DEJA utilisees par Colonnes/Entetes (voir
        _ColumnPreview.setItemStyle/la remarque de l'utilisateur, "l'apercu
        doit se faire sur les colonnes deja existantes" — pas de widget
        d'apercu separe) — meme raison/meme technique que
        _apply_column_preview (_current_hex()/_resolve_color_value :
        palette LIVE pendant un glisser de la page Couleurs)."""
        live_colors = dict(self.settings["colors"])
        live_colors.update(self.color_grid.value())
        font_family = self.item_font_field.value()
        if font_family == "Systeme":
            font_family = ""
        sel_enabled = self.item_selection_border_field.sidesEnabledValue()
        sel_colors = {
            k: _resolve_color_value(v, live_colors) for k, v in self.item_selection_border_field.sidesValue().items()
        }
        for preview in self.column_previews:
            preview.setItemStyle(
                font_family=font_family,
                color_hex=self.item_color_field.value(),
                icon_enabled=self.item_icon_field.isChecked(),
                row_height=self.item_row_height_field.value(),
                row_spacing=self.item_row_spacing_field.value(),
                text_padding=self.item_text_padding_field.value(),
                hover_color=self.item_hover_field.value(),
                focus_color=self.item_selection_focus_field.value(),
                unfocus_color=self.item_selection_unfocus_field.value(),
                padding=self.item_selection_padding_field.sidesValue(),
                enabled=sel_enabled,
                colors=sel_colors,
                radius=self.item_selection_radius_field.cornersValue(),
                edge_border=self.item_selection_edge_border_field.isChecked(),
            )

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
        self.font_table.head._custom_bg = hexval
        self.geo_table.head._custom_bg = hexval
        self.table_preview.head._custom_bg = hexval
        self._apply_table_radius(self.table_radius_field.value())

    def _apply_table_radius(self, radius: int):
        """Slider Geometrie > Tableaux > Coins arrondis (voir _TableFrame) :
        arrondit les 3 tableaux "fermes" de cette fenetre (Polices, Entetes,
        Geometrie — celui-ci y compris, voir la remarque de tete de
        _TableFrame) — voir la remarque de l'utilisateur, capture a
        l'appui. Prepare aussi le rayon des futurs tableaux STANDARD de
        l'appli principale, s'il en apparait un jour (voir app_style.
        set_table_radius, applique par pipeline_browser.apply_all_settings).

        Polices et Geometrie ont chacun leur propre entete de colonnes (voir
        _table_header) qui porte les coins hauts ; le tableau Entetes n'en a
        pas (une seule "valeur" par ligne, voir _section_headers) — c'est
        alors sa PREMIERE ligne qui doit porter les coins hauts, en plus de
        la derniere qui porte toujours les coins bas."""
        self.font_table.apply_radius(radius)
        self.geo_table.apply_radius(radius)
        self.table_preview.apply_radius(radius)
        self.color_grid.setRadius(radius)
        # Table Application (voir _build_flat_table, meme technique que la
        # table Entetes/Colonnes ci-dessous).
        self._app_table_row_meta = self._restyle_flat_table(self.app_table_frame, self._app_table_row_meta, radius)
        # Table Tableaux (voir _section_tables, meme technique).
        self._tables_row_meta = self._restyle_flat_table(self.tables_table_frame, self._tables_row_meta, radius)
        # Table Toggles > Style (voir _section_toggles, meme technique) —
        # trouvee manquante ici (comme dans _apply_cell_padding, meme
        # lacune) en verifiant TOUS les tableaux un par un suite a la
        # remarque de l'utilisateur.
        self._toggles_row_meta = self._restyle_flat_table(self.toggles_table_frame, self._toggles_row_meta, radius)
        # 2 tableaux Colonnes/Entetes (voir _section_headers, meme technique
        # _build_flat_table que les tables Application/Tableaux ci-dessus —
        # remplace l'ancien tableau UNIQUE "Entetes", voir la remarque de
        # l'utilisateur, "fait deux tableaux plutot qu'un").
        self._columns_table_row_meta = self._restyle_flat_table(
            self.columns_table_frame, self._columns_table_row_meta, radius)
        self._headers_table_row_meta = self._restyle_flat_table(
            self.headers_table_frame, self._headers_table_row_meta, radius)
        # 2 tableaux Texte/Selection de Items (voir _section_items, meme
        # technique).
        self._item_text_row_meta = self._restyle_flat_table(
            self.item_text_frame, self._item_text_row_meta, radius)
        self._item_selection_row_meta = self._restyle_flat_table(
            self.item_selection_frame, self._item_selection_row_meta, radius)
        # Les 2 sous-tables de Geometrie > Slider (voir _build_flat_table,
        # meme technique que la table Entetes ci-dessus) suivent le meme
        # rayon.
        self._slider_thumb_row_meta = self._restyle_flat_table(
            self.slider_thumb_frame, self._slider_thumb_row_meta, radius)
        self._slider_rail_row_meta = self._restyle_flat_table(
            self.slider_rail_frame, self._slider_rail_row_meta, radius)
        # Les 4 sous-tables Cadre/Coche de Toggle 1/Toggle 2 (voir
        # _build_toggle_shape_tables, meme technique) suivent le meme
        # rayon.
        for frames in self._toggle_frames.values():
            for shape in ("outer", "coche"):
                frame, meta = frames[shape]
                frames[shape] = (frame, self._restyle_flat_table(frame, meta, radius))

    def _apply_cell_padding(self, sides: dict):
        """Tableaux > Padding des cellules (voir _CellPaddingField) :
        s'applique a TOUS les tableaux de cette fenetre — les tableaux "1
        valeur par ligne" (_build_flat_table/_section_headers, voir
        _table_row), la grille Couleurs (voir _ColorGrid) ET, depuis la
        remarque de l'utilisateur ("je ne vois pas pourquoi ca ne
        fonctionnerait pas"), Polices/Geometrie aussi (voir _table_cell,
        _SimpleFontTable.setCellPadding/_GeoTable.setCellPadding) — leur
        entete (voir _ResizableTableHeader.setCellPadding) suit le GAUCHE/
        DROITE pour rester aligne avec les colonnes en dessous."""
        left = int(sides.get("left", 14))
        top = int(sides.get("top", 8))
        right = int(sides.get("right", 14))
        bottom = int(sides.get("bottom", 8))
        rows = [
            *self._app_table_row_meta,
            *self._tables_row_meta,
            *self._columns_table_row_meta,
            *self._headers_table_row_meta,
            *self._item_text_row_meta,
            *self._item_selection_row_meta,
            *self._slider_thumb_row_meta,
            *self._slider_rail_row_meta,
            # Toggles > Style (voir _section_toggles) : ce petit tableau a
            # 1 seule ligne ("Style") etait oublie ici (deja oublie aussi
            # de _apply_table_radius, meme tableau, meme lacune anterieure
            # a cette fonction) — trouve en verifiant TOUS les tableaux un
            # par un suite a la remarque de l'utilisateur.
            *self._toggles_row_meta,
        ]
        for frames in self._toggle_frames.values():
            for shape in ("outer", "coche"):
                _frame, meta = frames[shape]
                rows.extend(meta)
        for row, _bg, _first in rows:
            row.layout().setContentsMargins(left, top, right, bottom)
            # _lock_min_height (voir sa docstring) RE-appele ici, pas
            # seulement a la construction de la ligne : son minimumHeight
            # fige reste sinon celui calcule pour l'ANCIEN padding — ce
            # qu'il faut pour un padding AGRANDI en direct (sans ca,
            # l'espace de contenu reellement disponible passait sous zero,
            # rendant texte/controle quasiment invisibles) mais _lock_min_
            # height() prend le MAX avec la valeur figee EXISTANTE (voir sa
            # docstring : c'est la protection voulue face a un contenu qui
            # vient d'apparaitre, pas face a un padding qui vient de
            # RETRECIR) — sans remettre ce plancher a zero d'abord, un
            # padding reduit ne redescendait donc jamais (aucun effet visible
            # en diminuant Haut/Bas, seul Gauche/Droite — pas concernes par
            # une hauteur minimale — reagissaient) — voir la remarque de
            # l'utilisateur.
            row.setMinimumHeight(0)
            _lock_min_height(row)
        # Grille Couleurs (voir _ColorGrid) : meme correctif que ci-dessus,
        # sur ses cellules plutot que des lignes de tableau — chacune a
        # aussi son propre minimumHeight fige (voir _ColorGrid.__init__,
        # ou _lock_min_height est deja appele a la construction pour EVITER
        # le tassement des pastilles, remarque de l'utilisateur precedente).
        for cell, _row, _col in self.color_grid._cells:
            cell.layout().setContentsMargins(left, top, right, bottom)
            cell.setMinimumHeight(0)
            _lock_min_height(cell)
        # Polices/Geometrie (voir la remarque de l'utilisateur) : chacun
        # gere son propre padding (Gauche/Droite repercute aussi sur son
        # entete, voir _SimpleFontTable/_GeoTable.setCellPadding).
        self.font_table.setCellPadding(sides)
        self.geo_table.setCellPadding(sides)
        self.table_preview.setCellPadding(sides)
        # TOUS les cadres de tableau touches ci-dessus : voir
        # _refresh_content_layout, qui a besoin que chacun ait deja
        # digere son (ses) changement(s) de ligne/cellule AVANT de
        # remonter la chaine plus haut (section, ascenseur).
        frames = [
            self.app_table_frame, self.tables_table_frame,
            self.columns_table_frame, self.headers_table_frame,
            self.item_text_frame, self.item_selection_frame,
            self.slider_thumb_frame, self.slider_rail_frame, self.toggles_table_frame,
            self.color_grid.wrap, self.font_table.frame, self.geo_table.frame_wrap,
            self.table_preview.frame,
        ]
        for toggle_frames in self._toggle_frames.values():
            for shape in ("outer", "coche"):
                frames.append(toggle_frames[shape][0])
        self._refresh_content_layout(frames)

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

    def _restyle_flat_table(self, frame: QWidget, row_meta: list, radius: int) -> list:
        """Factorise le meme recalcul que la boucle ci-dessus (table Entetes),
        pour les tableaux batis via _build_flat_table (voir Geometrie >
        Slider)."""
        frame.setRadius(radius)
        last = len(row_meta) - 1
        new_meta = []
        for i, (row, _old_bg, first) in enumerate(row_meta):
            bg = M["table_row_a"] if i % 2 == 0 else M["table_row_b"]
            _restyle_table_row(
                row, bg, first,
                top_radius=(radius if i == 0 else 0),
                bottom_radius=(radius if i == last else 0),
            )
            new_meta.append((row, bg, first))
        return new_meta

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
        _sync_slider_style(settings)
        for slider in self.findChildren(_MiniSlider):
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
        self.item_selection_border_field.refresh_colors(merged_colors)
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
        self._apply_panel_radius(self.geo_table.window_radius_field.value())
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
        self._apply_panel_radius(self.geo_table.window_radius_field.value())
        self._mark_dirty()

    def _current_values(self) -> dict:
        colors = dict(self.settings["colors"])
        colors.update(self.color_grid.value())
        geo = self.geo_table.value()
        out = dict(self.settings)
        out.update({
            "root_path": self.root_field.text().strip() or DEFAULT_SETTINGS["root_path"],
            "ui_scale": self.scale_field.value(),
            "colors": colors,
            "header_height": self.header_height_field.value(),
            "header_padding": self.header_padding_field.value(),
            "header_color": self.header_color_field.value(),
            "header_radius": self.header_radius_field.cornersValue(),
            "header_radius_linked": self.header_radius_field.isLinked(),
            "header_border_enabled": self.header_border_field.sidesEnabledValue(),
            "header_border": self.header_border_field.sidesValue(),
            "header_border_thickness": self.header_border_thickness_field.value(),
            "column_gap": self.column_gap_field.value(),
            "column_padding_linked": self.column_padding_field.isLinked(),
            "column_padding": self.column_padding_field.sidesValue(),
            "column_border_enabled": self.column_border_field.sidesEnabledValue(),
            "column_border": self.column_border_field.sidesValue(),
            "column_border_thickness": self.column_border_thickness_field.value(),
            "column_border_radius": self.column_border_radius_field.cornersValue(),
            "column_border_radius_linked": self.column_border_radius_field.isLinked(),
            "item_font_family": "" if self.item_font_field.value() == "Systeme" else self.item_font_field.value(),
            "item_color": self.item_color_field.value(),
            "item_icon_enabled": self.item_icon_field.isChecked(),
            "item_row_height": self.item_row_height_field.value(),
            "item_row_spacing": self.item_row_spacing_field.value(),
            "item_text_padding": self.item_text_padding_field.value(),
            "item_selection_focus_color": self.item_selection_focus_field.value(),
            "item_selection_unfocus_color": self.item_selection_unfocus_field.value(),
            "item_hover_color": self.item_hover_field.value(),
            "item_selection_padding_linked": self.item_selection_padding_field.isLinked(),
            "item_selection_padding": self.item_selection_padding_field.sidesValue(),
            "item_selection_border_enabled": self.item_selection_border_field.sidesEnabledValue(),
            "item_selection_border": self.item_selection_border_field.sidesValue(),
            "item_selection_radius": self.item_selection_radius_field.cornersValue(),
            "item_selection_radius_linked": self.item_selection_radius_field.isLinked(),
            "item_selection_edge_border": self.item_selection_edge_border_field.isChecked(),
            # Colonnes > Type (voir _build_column_type_page/
            # _resolve_type_effective) : un toggle par ligne (ON = cette
            # cle SURCHARGE la valeur generale sur la colonne "Type") + la
            # valeur BRUTE de chaque champ (meme forme que son homologue
            # general ci-dessus) + le "lie"/"libre" des 4 champs qui
            # l'exposent (voir _TYPE_LINKED_KEYS).
            "column_type_override_enabled": {
                key: toggle.isChecked() for key, toggle in self._type_toggles.items()
            },
            "column_type_overrides": {
                key: _read_override_field_raw(key, field) for key, field in self._type_fields.items()
            },
            "column_type_override_linked": {
                key: self._type_fields[key].isLinked() for key in _TYPE_LINKED_KEYS if key in self._type_fields
            },
            "columns_resizable": self.columns_resizable_toggle.isChecked(),
            "table_radius": self.table_radius_field.value(),
            "table_cell_padding_linked": self.cell_padding_field.isLinked(),
            "table_cell_padding": self.cell_padding_field.sidesValue(),
            "table_head_color": self.table_head_color_field.value(),
            "geo_table_columns": self.geo_table.head.columnWidths(),
            "font_table_columns": self.font_table.head.columnWidths(),
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
        self.settings = self._current_values()
        save_settings(self.settings)
        self._saved = True
        self._dirty = False
        self.titlebar.set_dirty(False)
        self._sync_preset_box()
        self.settingsSaved.emit(self.settings)
        self.accept()

    def reject(self):
        if not self._saved:
            self.settingsChanged.emit(self._original_settings)
        self._save_window_geometry()
        super().reject()

    def accept(self):
        self._save_window_geometry()
        super().accept()

    def _save_window_geometry(self):
        _save_window_geometry(bytes(self.saveGeometry().toBase64()).decode("ascii"))


def main():
    from app_style import apply_style
    app = QApplication(sys.argv)
    apply_style(app)
    win = SettingsWindow()
    win.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
