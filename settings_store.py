import json
from pathlib import Path
from typing import Any
from PySide6.QtGui import (
    QFont,
)
from app_style import (
    C,
    COLOR_FIELDS,
    SEMANTIC_COLOR_SLOTS,
)


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
# Section "TITRE" (voir SettingsWindow._section_titre) : police + retrait
# (indentation) des titres de _Section/_SubSection de CETTE fenetre, par
# niveau d'imbrication (1 = _Section, 2..5 = _SubSection a une profondeur
# croissante) — voir la remarque de l'utilisateur, "je veux homogeneiser
# les textes des sections et sous sections". Defauts = apparence INCHANGEE
# (voir _Section/_SubSection avant ce reglage : 14/600 couleur section_title
# niveau 1, 10/600 couleur group_title/group_note + 20px/40px de retrait
# niveaux 2/3) ; niveaux 4/5 n'ont encore AUCUN site d'utilisation reel
# (aucune sous-section n'est imbriquee aussi profond aujourd'hui) — reserves
# pour une imbrication future, memes defauts que le niveau 3 mais un retrait
# plus profond (60/80px).
# ==========================================================================
_TITLE_LEVEL_DEFAULTS: dict[int, dict] = {
    1: {"font_family": "", "font_bold": True, "font_italic": False, "font_size": 14,
        "font_smoothing_enabled": False, "font_smoothing": "current", "font_color": "#5f9bd0", "indent": 0},
    2: {"font_family": "", "font_bold": True, "font_italic": False, "font_size": 10,
        "font_smoothing_enabled": False, "font_smoothing": "current", "font_color": "#5d656b", "indent": 20},
    3: {"font_family": "", "font_bold": True, "font_italic": False, "font_size": 10,
        "font_smoothing_enabled": False, "font_smoothing": "current", "font_color": "#5d656b", "indent": 40},
    4: {"font_family": "", "font_bold": True, "font_italic": False, "font_size": 10,
        "font_smoothing_enabled": False, "font_smoothing": "current", "font_color": "#5d656b", "indent": 60},
    5: {"font_family": "", "font_bold": True, "font_italic": False, "font_size": 10,
        "font_smoothing_enabled": False, "font_smoothing": "current", "font_color": "#5d656b", "indent": 80},
}

_TITLE_LEVEL_STYLE: dict[int, dict] = {level: dict(vals) for level, vals in _TITLE_LEVEL_DEFAULTS.items()}

def _sync_title_level_style(settings: dict) -> None:
    colors = settings.get("colors") or {}
    for level, defaults in _TITLE_LEVEL_DEFAULTS.items():
        prefix = f"title_level{level}"
        style = _TITLE_LEVEL_STYLE[level]
        for key, default in defaults.items():
            style[key] = settings.get(f"{prefix}_{key}", default)
        # Resolu tout de suite en hex REEL (voir _resolve_color_value) —
        # PAS conserve tel quel ("@<slot>") : _title_color n'a lui-meme
        # aucun acces a la palette (fonction MODULE, pas methode), le
        # laisser resoudre plus tard avec un dict VIDE retombait toujours
        # sur le noir de repli — voir la remarque de l'utilisateur, "quand
        # je selectionne une couleur app, elle apparait noire".
        style["font_color"] = _resolve_color_value(style["font_color"], colors)

def _title_font(level: int) -> QFont:
    """Police EFFECTIVE d'un titre de _Section (niveau 1) / _SubSection
    (niveau 2-5) — voir _TITLE_LEVEL_STYLE. Import de pipeline_browser
    LOCAL (voir _SettingsTitleBar.__init__, meme raison) : evite un import
    circulaire au chargement du module (pipeline_browser importe deja
    settings_window)."""
    import browser_core as pb_core
    from app_style import font as pb_font
    style = _TITLE_LEVEL_STYLE.get(level) or _TITLE_LEVEL_DEFAULTS[3]
    size = int(style.get("font_size", 10))
    weight = 600 if style.get("font_bold", True) else 400
    smoothing = style.get("font_smoothing", "current") if style.get("font_smoothing_enabled") else "current"
    family = pb_core._resolve_font_family((style.get("font_family") or "").strip(), size, weight)
    return pb_font(
        size, weight, family=family, italic=bool(style.get("font_italic", False)),
        smoothing=smoothing, tracking=(0.6 if level >= 2 else 0.0))

def _title_color(level: int) -> str:
    """Couleur DEJA resolue en hex (voir _sync_title_level_style, appelee
    avant toute utilisation de cette fonction) — jamais un "@<slot>" brut
    ici."""
    style = _TITLE_LEVEL_STYLE.get(level) or _TITLE_LEVEL_DEFAULTS[3]
    return style.get("font_color", "#d6d9dc")

def _title_indent(level: int) -> int:
    style = _TITLE_LEVEL_STYLE.get(level) or _TITLE_LEVEL_DEFAULTS[3]
    return max(0, int(style.get("indent", 0)))

def _subsection_left_margin(level: int) -> int:
    """Marge GAUCHE reelle du bandeau d'une _SubSection de `level` — voir la
    remarque de l'utilisateur, "pour les titres, une indentation a 0
    correspond a etre au meme niveau que le titre 1" : un retrait de 0px
    (General > TITRE > "Retrait titre niveau N") doit aligner le TEXTE de
    cette sous-section sur le TEXTE du titre de _Section (niveau 1), pas sur
    x=0 brut — or _Section et _SubSection n'ont pas le meme chevron/
    espacement (16+10 vs 11+6), d'ou l'ecart fixe "9" ci-dessous pour
    compenser cette difference AVANT d'ajouter le retrait configure."""
    return _title_indent(1) + 9 + _title_indent(level)

# ==========================================================================
# Persistance — un seul emplacement (voir la remarque de tete de fichier :
# le mode de sauvegarde a 4 positions de l'ancienne fenetre a disparu avec
# la maquette, qui n'a qu'un reglage "Preset" ; le fichier actif reste celui
# deja utilise aujourd'hui, aucun changement de comportement).
# ==========================================================================

_SCRIPT_DIR = Path(__file__).resolve().parent

_DATA_DIR = _SCRIPT_DIR / "data"

_PER_USER_PATH = _DATA_DIR / "pipeline_settings.json"

_PRESETS_PATH = _DATA_DIR / "pipeline_settings.presets.json"

_WINDOW_STATE_PATH = _DATA_DIR / "pipeline_settings_window_state.json"

# Icones SVG (voir _Chevron) — copiees depuis le repertoire personnel de
# l'utilisateur (F:\SYNC\Sync\IMAGES\ico\SVG, "chevron bas"/"chevron droite")
# plutot que reference directe : rester utilisable meme si ce repertoire
# externe bouge/n'existe pas sur une autre machine.
_ICONS_DIR = _SCRIPT_DIR / "icons"

def _load_window_geometry(key: str = "geometry") -> str | None:
    """Recharge la geometrie (taille/position) de CETTE fenetre au moment de
    sa derniere fermeture — meme mecanisme que PipelineBrowser (saveGeometry/
    restoreGeometry encodes en base64, voir pipeline_browser.py), mais dans
    un fichier a part pour ne pas melanger etat de fenetre et reglages
    (celui-ci n'est jamais propose au choix d'un preset)."""
    try:
        if _WINDOW_STATE_PATH.is_file():
            data = json.loads(_WINDOW_STATE_PATH.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                return data.get(key)
    except (OSError, ValueError):
        pass
    return None

def _save_window_geometry(geometry_b64: str, key: str = "geometry") -> None:
    """key : une entree par fenetre de reglages (voir SettingsWindow, mode)."""
    try:
        data = {}
        if _WINDOW_STATE_PATH.is_file():
            loaded = json.loads(_WINDOW_STATE_PATH.read_text(encoding="utf-8"))
            if isinstance(loaded, dict):
                data = loaded
        data[key] = geometry_b64
        _WINDOW_STATE_PATH.write_text(
            json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8"
        )
    except OSError:
        pass

_DEFAULT_FONT = {
    "family": "", "size": 12, "bold": False, "smoothing": "current", "color": "", "custom": False,
}

DEFAULT_COLUMNS: dict[str, dict[str, Any]] = {
    "Type":        {"width": 140, "height": 25, "spacing": 0},
    "Projets":     {"width": 208, "height": 58, "spacing": 1, "img_pad": 0, "img_radius": 0},
    "Sous-projet": {"width": 208, "height": 58, "spacing": 1, "img_pad": 0, "img_radius": 0,
                    "img_pad_link": True, "img_radius_link": True},
    "Logiciels":   {"width": 186, "height": 30, "plain_height": 22, "spacing": 0, "img_pad": 3, "img_radius": 2},
    "Contenu":     {"width": 186, "height": 25, "plain_height": 20, "spacing": 0, "img_pad": 3, "img_radius": 0},
}

DEFAULT_SETTINGS: dict[str, Any] = {
    "root_path": r"F:\PIPELINE",
    "ui_scale": 100,
    # Section "Application" (voir SettingsWindow._section_application) :
    # repli automatique des colonnes de set (Type/Projets/niveaux
    # configures) des que la chaine de navigation atteint le repertoire de
    # travail — deja le comportement actuel par defaut (True), ce reglage
    # permet juste de le desactiver (voir app_style.
    # set_auto_collapse_set_columns/pipeline_browser._sync_collapse_state) —
    # voir la remarque de l'utilisateur, "un toggle qui permet ou pas de
    # rabattre les colonnes de set, une fois que l'on est sur l'espace de
    # travail".
    "auto_collapse_set_columns": True,
    "application_omit_file_names": [],
    "application_omit_extensions": [],
    "application_omit_dir_names": [],
    "window_radius": 0,
    "header_visible": True,
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
    "column_bg_color": "@skinN2",
    # Cadre de redimensionnement (voir pipeline_browser._show_resize_width/
    # _resize_width_indicator — le badge flottant affichant la largeur/
    # hauteur en px pendant un glisser de bordure de colonne) — voir la
    # remarque de l'utilisateur, "je veux que dans general/colonnes/ tu
    # crees une sous section cadre de redimensionnement". Position :
    # "bottom_right" (comportement INCHANGE, coin ou ce badge s'affichait
    # deja jusqu'ici). Couleur de fond/bordure : hex LITTERAL (pas "@slot")
    # correspondant a l'ancien C['chrome']/C['border'] code en dur —
    # "@border2" pour la bordure (voir app_style.SEMANTIC_COLOR_SLOTS,
    # alias EXISTANT deja pointe sur C['border']) — aucun changement visuel
    # tant que l'utilisateur n'y touche pas.
    "resize_badge_position": "bottom_right",   # bottom_right/bottom_left/top_right/top_left
    # Decalage H/V (px) depuis le coin choisi ci-dessus (voir
    # _ResizeBadgePositionField, sliders sur la MEME ligne que la position)
    # — 8 par defaut des 2 axes = l'ancienne marge fixe _RESIZE_WIDTH_MARGIN,
    # comportement INCHANGE tant que l'utilisateur n'y touche pas — voir la
    # remarque de l'utilisateur, "sous position je veux egalement deux
    # sliders (sur la mm ligne) pour la position H et la position V".
    "resize_badge_offset_x": 8,
    "resize_badge_offset_y": 8,
    "resize_badge_font_family": "",            # "" = police mono de l'appli (comportement INCHANGE)
    "resize_badge_font_bold": True,             # True : poids 600 fige avant ce toggle, comportement INCHANGE
    "resize_badge_font_italic": False,
    "resize_badge_font_size": 11,
    "resize_badge_font_smoothing_enabled": False,
    "resize_badge_font_smoothing": "current",
    "resize_badge_text_color": "#d6d9dc",      # = ancien C['text'] code en dur, comportement INCHANGE
    "resize_badge_bg_color": "#202326",
    "resize_badge_border_enabled": {"top": True, "right": True, "bottom": True, "left": True},
    "resize_badge_border": {
        "top": "@border2", "right": "@border2", "bottom": "@border2", "left": "@border2",
    },
    "resize_badge_border_thickness": 1,
    "resize_badge_border_radius": 4,
    "resize_badge_border_radius_linked": True,
    # Colonnes > Apercu (voir pipeline_browser.PreviewColumn/PREVIEW_STACK_
    # TITLE) — voir la remarque de l'utilisateur, "dans la section
    # colonnes/apercu, je veux une section image ... zone titre ... bouton
    # repliement". "preview_pad"/"preview_radius" existaient deja (lus par
    # apply_all_settings) mais sans aucun champ pour les regler jusqu'ici.
    "preview_padding": {"left": 0, "top": 0, "right": 0, "bottom": 0},
    "preview_padding_linked": True,
    "preview_radius": {"top_left": 0, "top_right": 0, "bottom_right": 0, "bottom_left": 0},
    "preview_radius_linked": True,
    "preview_title_zone_height": 52,
    "preview_title_font_size": 26,
    "preview_title_font_color": "#d6d9dc",
    "preview_title_font_family": "",
    # True (pas False) : le titre etait TOUJOURS en gras avant l'ajout de ce
    # toggle (poids fige a 700 en dur, voir pipeline_browser._build_preview_
    # stack) — comportement par defaut INCHANGE.
    "preview_title_font_bold": True,
    "preview_title_font_italic": False,
    "preview_title_font_smoothing_enabled": False,
    "preview_title_font_smoothing": "current",
    "preview_title_padding_linked": True,
    "preview_title_padding": {"left": 14, "top": 0, "right": 14, "bottom": 8},
    "preview_status_font_size": 10,
    "preview_status_font_color": "#d6d9dc",
    "preview_status_font_color_idle": "#5f666b",
    "preview_status_font_family": "",
    # True : meme raison que preview_title_font_bold (poids fige a 700
    # avant ce toggle) — comportement par defaut INCHANGE.
    "preview_status_font_bold": True,
    "preview_status_font_italic": False,
    "preview_status_font_smoothing_enabled": False,
    "preview_status_font_smoothing": "current",
    "preview_status_padding_linked": True,
    "preview_status_padding": {"left": 14, "top": 0, "right": 14, "bottom": 0},
    "preview_toggle_width": 22,
    "preview_toggle_height": 22,
    "preview_toggle_bg_color": "#960f1114",
    "preview_toggle_border_enabled": {"top": False, "right": False, "bottom": False, "left": False},
    "preview_toggle_border": {
        "top": "#2e343a", "right": "#2e343a", "bottom": "#2e343a", "left": "#2e343a",
    },
    "preview_toggle_border_thickness": 1,
    "preview_toggle_radius": 4,
    "preview_toggle_x": 8,
    "preview_toggle_y": 34,
    "collapse_toggle_mode": "chevrons",
    "detail_panel_width": 300,
    "shortcut_font_family": "",
    "shortcut_font_bold": False,
    "shortcut_font_italic": False,
    "shortcut_color": "#8fb4d5",
    "shortcut_font_size": 11,
    "shortcut_font_smoothing_enabled": False,
    "shortcut_font_smoothing": "current",
    # Items texte des colonnes (voir SettingsWindow._section_items) — voir
    # la remarque de l'utilisateur, "ajoute un tableau pour les items
    # textes dans les colonnes". "" = police Systeme (meme convention que
    # font_table_columns/_FontSelectField). Couleurs par defaut alignees
    # sur les pastilles reelles deja utilisees par la liste (C['text']/
    # C['accent']/C['sel_idle']/C['hover']/C['border']).
    "item_font_family": "",
    # Taille du texte des items de colonne (voir pipeline_browser.
    # _resolve_row_font_color, jusqu'ici fige a 10 en dur) — voir la
    # remarque de l'utilisateur, "ajoute taille" dans Colonnes > Texte >
    # Police.
    "item_font_size": 10,
    # Gras (voir pipeline_browser._resolve_row_font_color) — voir la
    # remarque de l'utilisateur, "pour les polices ... j'aimerais rajouter
    # une option pour mettre le texte en gras (toggle)".
    "item_font_bold": False,
    "item_font_italic": False,
    "item_color": "#d6d9dc",
    # Lissage FORCE du texte des items (voir app_style.font, SMOOTHING_
    # CHOICES) — desactive par defaut (suit alors le lissage habituel,
    # "current"/complet, comme avant) : voir la remarque de l'utilisateur,
    # "toggle + override l'antialiasing".
    "item_antialias_override_enabled": False,
    "item_antialias_override": "current",
    "item_icon_enabled": True,
    "item_row_height": 25,
    "item_icon_size": 0,
    "item_icon_padding_left": 0,
    "item_row_spacing": 1,   # voir pipeline_browser.ROW_SPACING
    # Largeur par defaut d'une colonne (voir pipeline_browser.COLUMN_SETTINGS/
    # col_width/apply_all_settings) — reglage GENERAL, surchargeable PAR TITRE
    # (Colonnes > Type/Projets/Sous-projets, meme mecanisme qu'item_row_height/
    # item_row_spacing juste au-dessus) : remplace les largeurs fixes codees en
    # dur (140/208/186 selon la colonne) par une valeur reglable et persistee —
    # voir la remarque de l'utilisateur, "ajoute un parametre de largeur de
    # colonne par defaut ... et un overide pour chacune des autres colonnes".
    # Bornes (120-640) : memes que COLUMN_MIN_WIDTH/COLUMN_MAX_WIDTH cote
    # pipeline_browser.py (pas importable ici, sens d'import inverse).
    "item_column_width": 180,
    # Filet horizontal entre les lignes d'une colonne (voir RowDelegate.
    # _paint_unified_row) — voir la remarque de l'utilisateur, "rajoute une
    # option pour ajouter une bordure entre les lignes avec choix de la
    # couleur (appli ou personnalisee) et de l'epaisseur". "@ligne" (voir
    # app_style.SEMANTIC_COLOR_SLOTS) est personnalisable via
    # _AppOrCustomColorField.
    "item_row_border_enabled": False,
    "item_row_border_color": "@ligne",
    "item_row_border_thickness": 1,
    # Espace (px) entre l'entete de la colonne et son 1er item de liste
    # (voir pipeline_browser.Column.header_gap_spacer) — distinct de
    # "Espacement entre les lignes" (ENTRE les items, pas avant le 1er) —
    # voir la remarque de l'utilisateur, "ajoute un slider qui cree un
    # espace entre l'entete et le premier item de la liste".
    "item_header_gap": 0,
    "item_text_padding": 8,
    # Sous-section "Image" (voir SettingsWindow._section_headers/
    # _build_column_override_page) : padding/bordure/rayon de l'image de
    # ligne (apercu personnalise sur "Type", vignette sur Projets/Sous-
    # projet/Logiciels/Contenu) — MEMES widgets que Colonnes > Bordure
    # (padding 4 cotes, bordure 4 cotes + couleur + epaisseur, rayon 4
    # coins) — voir la remarque de l'utilisateur, "ajoute une sous section
    # image ... padding de l'image (4 cotes) ... bordure de l'image (4
    # cotes, couleur, epaisseur) ... corner radius de l'image (4 coins)".
    # Neutres par defaut (0/desactive) : rendu inchange tant que
    # l'utilisateur ne personnalise pas.
    "item_image_padding_linked": True,
    "item_image_padding": {"top": 0, "right": 0, "bottom": 0, "left": 0},
    "item_image_border_enabled": {"top": False, "right": False, "bottom": False, "left": False},
    "item_image_border": {
        "top": "#2c3034", "right": "#2c3034", "bottom": "#2c3034", "left": "#2c3034",
    },
    "item_image_border_thickness": 1,
    "item_image_radius": 0,
    "item_image_radius_linked": True,
    "item_image_ratio": 1.0,
    "item_selection_focus_color": "#3f6f9f",
    "item_selection_unfocus_color": "#2e3338",
    "item_hover_color": "#232729",
    # Fond des items NON selectionnes (ni survoles), de la MEME forme que
    # les autres etats (padding/bordure/rayon du selecteur, voir
    # pipeline_browser._paint_unified_row) — voir la remarque
    # de l'utilisateur, "ajoute une couleur (sous couleur de survol) qui
    # represente la couleur non selectionnee ... un fond sur les items non
    # selectionnes, de la meme forme que les divers selections". "@itemIdle"
    # (voir app_style.SEMANTIC_COLOR_SLOTS, slot "Item - non selectionne" =
    # C["row_idle"], deja le fond actuel des lignes Type/Projets/Sous-
    # projet au repos) : par defaut, la boite est donc invisible (meme
    # couleur que le fond derriere), rendu inchange tant que l'utilisateur
    # ne personnalise pas cette couleur.
    "item_idle_color": "@itemIdle",
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
    # Non focus/Survol/Non selectionne (voir _section_headers, sous-
    # sections dediees) : "clones" de Focus (les 4 memes cles ci-dessus,
    # padding/bordure/rayon/bord de colonne), SAUF override explicite —
    # False/vide par defaut (comportement INCHANGE, un etat non pousse
    # herite integralement de Focus tant que son toggle reste OFF) — voir
    # la remarque de l'utilisateur, "non focus survol et non selectionne
    # sont des clones des focus (sauf la couleur) donc mets leur des
    # toggles d'override".
    "item_selection_unfocus_padding_override": False,
    "item_selection_unfocus_padding": {},
    "item_selection_unfocus_border_override": False,
    "item_selection_unfocus_border_enabled": {"top": False, "right": False, "bottom": False, "left": False},
    "item_selection_unfocus_border": {
        "top": "#2c3034", "right": "#2c3034", "bottom": "#2c3034", "left": "#2c3034",
    },
    "item_selection_unfocus_radius_override": False,
    "item_selection_unfocus_radius": 0,
    "item_selection_unfocus_radius_linked": True,
    "item_selection_unfocus_edge_border_override": False,
    "item_selection_unfocus_edge_border": True,
    "item_selection_hover_padding_override": False,
    "item_selection_hover_padding": {},
    "item_selection_hover_border_override": False,
    "item_selection_hover_border_enabled": {"top": False, "right": False, "bottom": False, "left": False},
    "item_selection_hover_border": {
        "top": "#2c3034", "right": "#2c3034", "bottom": "#2c3034", "left": "#2c3034",
    },
    "item_selection_hover_radius_override": False,
    "item_selection_hover_radius": 0,
    "item_selection_hover_radius_linked": True,
    "item_selection_hover_edge_border_override": False,
    "item_selection_hover_edge_border": True,
    "item_selection_idle_padding_override": False,
    "item_selection_idle_padding": {},
    "item_selection_idle_border_override": False,
    "item_selection_idle_border_enabled": {"top": False, "right": False, "bottom": False, "left": False},
    "item_selection_idle_border": {
        "top": "#2c3034", "right": "#2c3034", "bottom": "#2c3034", "left": "#2c3034",
    },
    "item_selection_idle_radius_override": False,
    "item_selection_idle_radius": 0,
    "item_selection_idle_radius_linked": True,
    "item_selection_idle_edge_border_override": False,
    "item_selection_idle_edge_border": True,
    # Colonnes > Type (voir SettingsWindow._build_column_type_page) : vide
    # par defaut — AUCUNE ligne surchargee, la colonne "Type" suit alors
    # EXACTEMENT le style general ci-dessus (voir la remarque de
    # l'utilisateur, "je veux que tu appliques exactement le style de
    # colonne (GENERAL/COLONNES) sur la colonne TYPE").
    "column_type_overrides": {},
    "column_type_override_enabled": {},
    "column_type_override_linked": {},
    # Meme principe que column_type_overrides ci-dessus, mais pour
    # Projets/Sous-projet (voir SettingsWindow._build_column_override_page/
    # _override_store) — cles "Type" historiques JAMAIS renommees (retro-
    # compatibilite avec les presets/settings.json existants), Projets/
    # Sous-projet imbriques par titre reel de colonne dans ces 3 nouvelles
    # cles plutot que de dupliquer 3 nouvelles cles PAR colonne.
    "column_overrides_by_title": {},
    "column_override_enabled_by_title": {},
    "column_override_linked_by_title": {},
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
    # Bordure des tableaux "fermes" de cette fenetre (voir _TableFrame.
    # setBorder) — MEME widget/MEME mecanique que Toggles > Cadre/Coche >
    # Bordure et Colonnes > Bordure, voir la remarque de l'utilisateur,
    # "ajoute dans la section tableau un parametre bordure comme celui des
    # toggles". Valeurs de depart = l'ancien filet fixe "1px solid
    # M['panel_border']" code en dur jusqu'ici : aucun changement visuel
    # tant que l'utilisateur n'y touche pas.
    "table_border_enabled": {"top": True, "right": True, "bottom": True, "left": True},
    "table_border": {"top": "#2a2e32", "right": "#2a2e32", "bottom": "#2a2e32", "left": "#2a2e32"},
    "table_border_thickness": 1,
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
    "toggle1_outer_bg_on": "#3f6f9f",
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
    "toggle2_outer_bg_on": "#3f6f9f",
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
    # Logiciels AJOUTES par l'utilisateur (voir SettingsWindow._section_
    # logiciels, General > LOGICIEL, "+") — chaque entree {"key": nom
    # normalise (alnum majuscule, voir pipeline_browser.software_icon_key),
    # "label": nom saisi tel quel, affiche dans le tableau}. Les logiciels
    # RECONNUS d'origine (pipeline_browser.SOFTWARE_ICONS) n'ont pas besoin
    # d'y figurer, ils apparaissent toujours dans ce meme tableau.
    "custom_softwares": [],
    # Logiciels RECONNUS D'ORIGINE explicitement retires de la liste (voir
    # SettingsWindow._delete_logiciel, bouton "Supprimer" sur une ligne
    # d'origine) — simples cles (pipeline_browser.SOFTWARE_ICONS), pas des
    # entrees completes comme custom_softwares : rien a afficher pour eux,
    # juste a exclure/ne plus reconnaitre tant qu'ils ne sont pas re-
    # ajoutes via "+ Ajouter un logiciel...".
    "removed_softwares": [],
    # Icone de niveaux (badge numerote, colonne "Projets" — voir
    # SettingsWindow._build_column_override_page, Colonnes > Projets >
    # Colonnes > "Icone de niveaux") — voir la remarque de l'utilisateur,
    # "j'aimerais pouvoir controler l'aspect de cette petite icone".
    "step_badge_width": 18,
    "step_badge_height": 18,
    "step_badge_border_enabled": {"top": False, "right": False, "bottom": False, "left": False},
    "step_badge_border": {"top": "#2e343a", "right": "#2e343a", "bottom": "#2e343a", "left": "#2e343a"},
    "step_badge_border_thickness": 1,
    "step_badge_radius": 9,
    "step_badge_radius_linked": True,
    "step_badge_color_base2": "#5c6368",
    "step_badge_color_base3": "#5c6368",
    "step_badge_color_base4": "#3f6f9f",
    "step_badge_color_base5": "#3f6f9f",
    "step_badge_color_base6": "#d9822b",
    # Couleur DEDIEE au badge "N" (voir pipeline_browser.project_step_count/
    # _step_badge_color) — affiche quand le toggle "set" (ColumnConfigDialog)
    # est desactive : ce projet n'a alors PLUS de nombre d'etapes a
    # proprement parler (Type+Projets seulement, aucune limite au-dela), le
    # badge numerote n'aurait donc aucun sens ici — voir la remarque de
    # l'utilisateur, "quand set est desactive je veux que l'indicateur de
    # base affiche N". DISTINCTE des bases 2-6 : sans ca, un projet "set
    # desactive" etait indiscernable a l'oeil d'un vrai projet "base 2".
    "step_badge_color_basen": "#5c6368",
    # Couleur du TEXTE, une par base (PAS une seule globale) — voir la
    # remarque de l'utilisateur, "enleve la couleur dans la ligne texte,
    # et met un carre de couleur pour le texte au dessus des carres de
    # couleur de fond ... la couleur du haut est pour le texte (pour
    # chacune des bases) et la couleur du bas est pour le fond".
    "step_badge_text_color_base2": "#eef2f5",
    "step_badge_text_color_base3": "#eef2f5",
    "step_badge_text_color_base4": "#eef2f5",
    "step_badge_text_color_base5": "#eef2f5",
    "step_badge_text_color_base6": "#eef2f5",
    "step_badge_text_color_basen": "#eef2f5",
    "step_badge_offset_x": 4,
    "step_badge_offset_y": 0,
    "step_badge_font_family": "",
    "step_badge_font_bold": True,
    "step_badge_font_smoothing_enabled": False,
    "step_badge_font_smoothing": "current",
    "step_badge_border_smoothing": True,
    # Entetes de colonnes (voir SettingsWindow._section_headers) — voir la
    # remarque de l'utilisateur, "ajoute un slider pour le padding droit
    # des icones ... choix de la police + gras/regular + couleur".
    "header_icon_right_padding": 0,
    "header_font_family": "",
    "header_font_bold": True,
    "header_font_color": "#9aa1a7",
    "header_font_size": 10,
    "header_font_italic": False,
    "header_font_antialias_override_enabled": False,
    "header_font_antialias_override": "current",
    # Preset applique AUTOMATIQUEMENT par-dessus pipeline_settings.json a
    # chaque chargement (voir load_settings, General > Application) — "" =
    # aucun (comportement INCHANGE, pipeline_settings.json seul fait foi).
    "default_preset": "",
}

# Section "TITRE" (voir SettingsWindow._section_titre/_TITLE_LEVEL_DEFAULTS,
# General > TITRE) : police/couleur/retrait des titres de _Section (niveau
# 1) et _SubSection (niveaux 2-5) de CETTE fenetre — genere depuis les
# MEMES defauts que _TITLE_LEVEL_STYLE (pas de duplication).
for _title_level, _title_defaults in _TITLE_LEVEL_DEFAULTS.items():
    for _title_key, _title_val in _title_defaults.items():
        DEFAULT_SETTINGS[f"title_level{_title_level}_{_title_key}"] = _title_val

del _title_level, _title_defaults, _title_key, _title_val

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
    # Preset par defaut (voir General > Application, DEFAULT_SETTINGS.
    # default_preset) : applique PAR-DESSUS pipeline_settings.json a CHAQUE
    # chargement (demarrage de l'appli ET ouverture de la fenetre de
    # parametres, tous deux passent par cette fonction) — voir la remarque
    # de l'utilisateur, "je veux un parametre preset par defaut". Silen-
    # cieux si le preset nomme a depuis ete supprime/renomme (repli sur
    # pipeline_settings.json seul, comme si aucun preset par defaut
    # n'etait configure).
    default_preset = settings.get("default_preset")
    if default_preset:
        presets = _load_presets()
        if default_preset in presets:
            _merge(presets[default_preset])
            # "default_preset" fait lui-meme PARTIE des cles capturees par
            # un preset (voir _current_values, "je veux que absolument
            # tous les parametres soient enregistres dans les presets") —
            # sans repli EXPLICITE ici, le _merge ci-dessus l'ecraserait
            # avec la valeur qu'AVAIT ce preset AU MOMENT ou il a ete
            # enregistre (typiquement vide), faisant "oublier" a l'appli,
            # des ce premier chargement, LEQUEL preset par defaut vient
            # justement d'etre applique.
            settings["default_preset"] = default_preset
    return settings

def save_settings(settings: dict[str, Any]) -> None:
    try:
        _PER_USER_PATH.parent.mkdir(parents=True, exist_ok=True)
        _PER_USER_PATH.write_text(json.dumps(settings, indent=2, ensure_ascii=False), encoding="utf-8")
    except OSError:
        pass

def _load_presets() -> dict[str, dict]:
    """Tous les presets enregistres, {nom: reglages} — {} si le fichier est
    absent/illisible/invalide (repli SILENCIEUX, meme convention que
    load_layout_settings/load_project_columns cote pipeline_browser :
    jamais bloquant)."""
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

_CORNERS = ("top_left", "top_right", "bottom_right", "bottom_left")

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
