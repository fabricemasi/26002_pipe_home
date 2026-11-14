import json
import re
from pathlib import Path
from typing import Any
from app_style import (
    C,
    COLOR_FIELDS,
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

# Aspect (palette M, curseurs, titres, zones de saisie, couleurs « @slot ») : dans fm_theme (source unique),
# reexporte ici pour le code qui les lit encore par settings_store.
from fm_theme.tokens import (  # noqa: E402,F401
    INPUT_LOOK,
    M,
    _CORNERS,
    _SLIDER_STYLE,
    _SLOT_REAL,
    _TITLE_LEVEL_DEFAULTS,
    _TITLE_LEVEL_STYLE,
    _coerce_corner_radius,
    _coerce_side_enabled,
    _resolve_color_value,
    _subsection_left_margin,
    _sync_dynamic_M,
    _sync_slider_style,
    _sync_title_level_style,
    _title_box,
    _title_box_defaults,
    _title_color,
    _title_font,
    _title_gap_next,
    _title_indent,
    input_bg,
    input_border_decl,
    input_height,
    set_input_look,
    toggle_style_list,
    _ICONS_DIR,
    _TOGGLE_ICONS_DIR,
)

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

# Fonctions fournies par l'appli aux champs de reglages qui en ont besoin
# (ex. settings_lut) : evite qu'un settings_* importe du code de l'appli.
HOOKS: dict[str, Any] = {}


def _theme_ui_icon(name: str, size: int):
    """Icone d'interface choisie par l'utilisateur, fournie a fm_theme (fm_theme/hooks.py) : import
    tardif de previews, rien n'est charge tant qu'aucune barre de titre ne la demande."""
    import previews as pb_previews
    key = {"settings_gear": pb_previews.UI_ICON_SETTINGS_GEAR, "navbar_pin": pb_previews.UI_ICON_NAVBAR_PIN}.get(name)
    return pb_previews.custom_ui_icon_pixmap(key, size) if key else None


import fm_theme.hooks as _theme_hooks  # noqa: E402
import fm_theme.presets as _theme_presets  # noqa: E402
import fm_theme.toggle_states as _toggle_states  # noqa: E402
_theme_hooks.HOOKS["ui_icon"] = _theme_ui_icon


def _theme_save_setting(key: str, value) -> None:
    """fm_theme a changé un réglage hors de la fenêtre de réglages (en-têtes des barres, clic droit) : il est écrit et
    gardé dans les réglages appliqués (le prochain `apply_settings` ne le défait pas)."""
    save_live_state(key, value)
    try:
        import ui_state
        if isinstance(ui_state.APPLIED_SETTINGS, dict):
            ui_state.APPLIED_SETTINGS[key] = value
    except Exception:                                  # noqa: BLE001 - la valeur est écrite quand même
        pass


_theme_hooks.HOOKS["save_setting"] = _theme_save_setting

# Visionneuse : défauts dans son paquet (source unique), fusionnés dans le dictionnaire ci-dessous.
from fm_visionneuse.settings_defaults import VIEWER_DEFAULTS  # noqa: E402

DEFAULT_SETTINGS: dict[str, Any] = {
    "root_path": r"F:\PIPELINE",
    # Images de test des apercus de LUT (.cube) ; "lut_default_image" est celle
    # sur laquelle la LUT est appliquee dans l'apercu.
    "lut_test_images": [],
    "lut_default_image": "",
    # Encodage de chaque image de test : {chemin: "srgb"|"slog3"|"flog"|"flog2"} (voir previews.LUT_IMAGE_CURVES).
    "lut_image_curves": {},
    "ui_scale": 100,
    # Valeur du grise (fm_theme > General) : opacite (%) de tout objet non utilisable (reglage inactif, bouton
    # desactive de la barre de navigation...) ; avant, constante 0.2 (et 0.35 pour la barre). Demande 2026-11-12.
    "dimmed_opacity": 20,
    "dimmed_text_opacity": 20,          # textes non utilisables (boutons desactives...)
    "dimmed_icon_opacity": 20,          # icones non utilisables (boutons de la barre de navigation...)
    "icon_margin": 20,                  # marge des icones chargees, % de chaque cote (preview_services/pixmaps.py)
    # Style des icones du catalogue dans l'interface (fm_theme.icon_library) : "monochrome" (teinte = couleur du
    # glyphe du bouton) ou "couleur" (camaieu du module). Demande de l'utilisateur, 2026-11-13.
    "icon_library_style": "monochrome",
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
    # Bordure du POURTOUR des fenetres (Theme > General, demande de l'utilisateur 2026-10-30) : fenetre
    # principale ET fenetres additionnelles (reglages, presets, editeur fm_theme...). Defaut = l'ancien filet
    # fixe de la fenetre principale (1 px « Bordures niveau 2 »).
    "window_border_enabled": {"top": True, "right": True, "bottom": True, "left": True},
    "window_border": {"top": "@border2", "right": "@border2", "bottom": "@border2", "left": "@border2"},
    "window_border_thickness": 1,
    # Editeur fm_theme, volet des variantes : CADRE DE SÉLECTION de la variante éditée (croquis de l'utilisateur,
    # 2026-11-10) ; réglages de l'appli (pas du preset), Thème > Général
    "variant_sel_border_enabled": {"top": True, "right": True, "bottom": True, "left": True},
    "variant_sel_border": {"top": "#4c80b3", "right": "#4c80b3", "bottom": "#4c80b3", "left": "#4c80b3"},
    "variant_sel_border_thickness": 1, "variant_sel_border_enabled_linked": True,
    "variant_sel_corner_radius": 6, "variant_sel_corner_radius_linked": True,
    "variant_sel_bg_color": "#00000000",
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
    "preview_image_ratio": 1.0,    # ratio (largeur/hauteur) de l'image de la colonne Focus
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
    # Côtés INÉGAUX : jamais liés par défaut (lié, le champ alignait tout sur le 1er côté et l'enregistrait, 2026-11-12)
    "preview_title_padding_linked": False,
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
    "preview_status_padding_linked": False,
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
    "shortcut_font_size": 11,
    "shortcut_font_smoothing_enabled": False,
    "shortcut_font_smoothing": "current",
    # Teinte de l'icone des dossiers selon leur sorte (Icones : General) ; blanc = icone telle quelle.
    "folder_icon_color_standard": "#ffffff",
    "folder_icon_color_shortcut": "#ffffff",
    "folder_icon_color_lightroom": "#ffffff",
    # Couleur du texte des dossiers par sorte (Icones > Couleur des dossiers, colonne Texte) : coupee = celle de la colonne.
    # « Couleur icone » (`_from_icon`) : le texte prend la couleur de l'icone.
    "folder_text_color_standard_enabled": False,
    "folder_text_color_standard_from_icon": False,
    "folder_text_color_standard": "#d6d9dc",
    "folder_text_color_shortcut_enabled": False,
    "folder_text_color_shortcut_from_icon": False,
    "folder_text_color_shortcut": "#8fb4d5",
    "folder_text_color_lightroom_enabled": False,
    "folder_text_color_lightroom_from_icon": False,
    "folder_text_color_lightroom": "#87cefa",
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
    "folder_reorder_enabled": True,   # tirer un dossier le replace dans sa colonne (toutes les colonnes)
    **VIEWER_DEFAULTS,                 # visionneuse : défauts dans son paquet (fm_visionneuse/settings_defaults.py)
    # Menus contextuels (settings_menu) : Reglages > Menu contextuel > Menu / Lignes / Libelles / Separateurs.
    "ctx_menu_editable": True,         # tirer un element = le deplacer ; clic droit = separateurs, libelles, icone
    "ctx_menu_bg": "#202326",
    "ctx_menu_border_enabled": {"top": True, "right": True, "bottom": True, "left": True},
    "ctx_menu_border": {"top": "#2c3034", "right": "#2c3034", "bottom": "#2c3034", "left": "#2c3034"},
    "ctx_menu_border_thickness": 1,
    "ctx_menu_border_color": "#2c3034",            # couleur des 4 cotes (ligne « Couleur des bordures »)
    "ctx_menu_border_radius": {"top_left": 0, "top_right": 0, "bottom_right": 0, "bottom_left": 0},
    "ctx_menu_border_radius_linked": True,
    "ctx_menu_padding": {"top": 4, "right": 0, "bottom": 4, "left": 0},
    "ctx_menu_padding_linked": False,
    "ctx_menu_font_family": "",
    "ctx_menu_font_bold": False,
    "ctx_menu_font_italic": False,
    "ctx_menu_font_size": 11,
    "ctx_menu_font_smoothing_enabled": False,
    "ctx_menu_font_smoothing": "current",
    "ctx_menu_font_color": "#d6d9dc",
    "ctx_menu_item_padding": {"top": 5, "right": 18, "bottom": 5, "left": 18},
    "ctx_menu_item_padding_linked": False,
    # Survol d'une ligne (Menu contextuel > Survol) : fond, texte, bordures, border radius, marge autour du
    # surlignage (comptes dans l'alignement de toutes les lignes, settings_menu._line_box).
    "ctx_menu_hover_color": "#3f6f9f",
    "ctx_menu_hover_text_color": "#eef2f5",
    "ctx_menu_hover_radius": {"top_left": 0, "top_right": 0, "bottom_right": 0, "bottom_left": 0},
    "ctx_menu_hover_radius_linked": True,
    "ctx_menu_hover_border_enabled": {"top": False, "right": False, "bottom": False, "left": False},
    "ctx_menu_hover_border": {"top": "#5f9bd0", "right": "#5f9bd0", "bottom": "#5f9bd0", "left": "#5f9bd0"},
    "ctx_menu_hover_border_thickness": 1,
    "ctx_menu_hover_border_enabled_linked": True,
    "ctx_menu_hover_margin": {"top": 0, "right": 0, "bottom": 0, "left": 0},
    "ctx_menu_hover_margin_linked": True,
    "ctx_menu_disabled_color": "#7d858b",
    "ctx_menu_ghost_color": "#e0a040",     # options fantomes (Ctrl+Maj + clic droit), voir fm_theme.menu
    # Fond de l'element EN COURS d'un menu (ex. la couleur « app » choisie), distinct du survol, voir fm_theme.menu.
    "ctx_menu_current_color": "#4d5f9bd0",
    "ctx_menu_icon_size": 16,
    "ctx_menu_control_gap": 16,        # entre le plus long texte et la colonne des controles
    "ctx_menu_slider_width": 140,      # rail des curseurs (tous les controles ont la meme largeur)
    "ctx_menu_label_font_family": "",
    "ctx_menu_label_font_bold": True,
    "ctx_menu_label_font_italic": False,
    "ctx_menu_label_font_size": 10,
    "ctx_menu_label_font_smoothing_enabled": False,
    "ctx_menu_label_font_smoothing": "current",
    "ctx_menu_label_font_color": "#7d858b",
    "ctx_menu_label_bg": "#00000000",
    "ctx_menu_label_padding": {"top": 6, "right": 0, "bottom": 2, "left": 0},
    "ctx_menu_label_padding_linked": False,
    "ctx_menu_label_uppercase": True,
    "ctx_menu_sep_color": "#2c3034",
    "ctx_menu_sep_thickness": 1,
    "ctx_menu_sep_padding": {"top": 4, "right": 0, "bottom": 4, "left": 0},
    "ctx_menu_sep_padding_linked": False,
    # Disposition choisie a la main pour chaque menu (ordre, separateurs, libelles, icones) : etat temps reel.
    "context_menu_layouts": {},
    # Colonnes > Lignes > Texte : extension des fichiers (« .jpg ») dans sa propre couleur.
    "item_ext_color_enabled": False,
    "item_ext_color": "#8a9097",
    # Fenetres additionnelles (reglages, override / a la volee, presets) : Reglages > Fenetres additionnelles.
    "extra_window_bg_color": "@skinN1",          # fond des fenetres additionnelles (= M["panel_bg"], skin niveau 1)
    "extra_window_border_enabled": {"top": True, "right": True, "bottom": True, "left": True},
    "extra_window_border": {"top": "#2a2e32", "right": "#2a2e32", "bottom": "#2a2e32", "left": "#2a2e32"},
    "extra_window_border_thickness": 1,
    "extra_window_radius": {"top_left": 0, "top_right": 0, "bottom_right": 0, "bottom_left": 0},
    "extra_window_radius_linked": True,
    "extra_window_title_height": 32,
    "extra_window_title_bg": "#101214",
    "extra_window_title_line_enabled": True, "extra_window_title_line_color": "#2a2e32",
    "extra_window_title_line_thickness": 1,
    "extra_window_buttons_line_enabled": True, "extra_window_buttons_line_color": "#2a2e32",
    "extra_window_buttons_line_thickness": 1,
    # Boutons de la barre de navigation (croix) : taille X / Y, border radius ; texte de la barre (gabarit police).
    "extra_window_title_button_width": 36, "extra_window_title_button_height": 32,
    "extra_window_title_button_radius": {"top_left": 0, "top_right": 0, "bottom_right": 0, "bottom_left": 0},
    "extra_window_title_button_radius_linked": True,
    "extra_window_title_text_font_family": "", "extra_window_title_text_font_bold": False,
    "extra_window_title_text_font_italic": False, "extra_window_title_text_font_size": 11,
    "extra_window_title_text_font_smoothing_enabled": False, "extra_window_title_text_font_smoothing": "current",
    "extra_window_title_text_font_color": "#8d949a",
    # Fenetres « a la volee » / d'override : place a leur fermeture, {nom: [x, y]} (etat temps reel).
    "quick_style_positions": {},
    # Style PROPRE d'un element (clic droit > Override settings, settings_element_style) :
    # {"table:<cle de dimensions>": {cle de reglage: valeur}} (seulement ce qui differe du general).
    "element_style_overrides": {},
    "ui_spaces": {},                  # espace au-dessus d'un element de la fenetre principale (clic droit) : {chemin: px}
    "ui_spaces_below": {},            # espace en dessous, meme principe
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
    # Fond de TOUTE la ligne (sous la boite du selecteur et ses paddings) ; "@skinN2" = C["void"],
    # le fond d'origine. Colonnes > Lignes > Couleur de fond (et onglets de colonne > Texte).
    "item_row_bg_color": "@skinN2",
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
    # Largeur et hauteur de ligne enregistrees par le glisser des bordures de colonne (seules cles lues,
    # voir browser_core._persist_column_width / _persist_row_height) : "Type" dans les deux premiers
    # dictionnaires, Projets / Sous-projet / Focus imbriques par titre dans les deux suivants.
    "column_type_overrides": {},
    "column_type_override_enabled": {},
    "column_overrides_by_title": {},
    "column_override_enabled_by_title": {},
    "header_font_family": "",   # fige : plus d'UI (voir remarque de tete de fichier)
    "input_frame": True,
    "input_radius": 0,
    "button_frame": True,
    "button_radius": 0,
    "navbar_height": 30,                        # 1re ligne de la barre (fm_theme)
    "navtool_extra_height": 70,                 # ajoutee a navbar_height : etage du cheminement (fm_browser)
    "window_always_on_top": False,              # fenêtre principale « toujours au-dessus » (état temps réel)
    "navbar_bg_color": "@navbar",               # fond de la barre ; « @navbar » = pastille C["app_bg"]
    # Boutons d'outils de la barre de navigation (reglages de fm_browser, 2026-11-07) : defauts = l'aspect d'avant.
    "navtool_bg_color": "#00000000",
    "navtool_border_enabled": {"top": False, "right": False, "bottom": False, "left": False},
    "navtool_border": {side: "#303539" for side in ("top", "right", "bottom", "left")},
    "navtool_border_thickness": 1,
    "navtool_corner_radius": {"top_left": 0, "top_right": 0, "bottom_right": 0, "bottom_left": 0},
    "navtool_corner_radius_linked": True,
    "navtool_hover_bg_color": "@hover",
    # Marge autour de chaque icone (carree) : 0 = les icones se touchent.
    "navtool_margin": {"left": 4, "top": 0, "right": 4, "bottom": 0},
    "navtool_margin_linked": False,
    # Cote du carre de chaque icone (jamais plus que la 1re ligne moins la marge) ; padding = entre cadre et dessin.
    "navtool_icon_size": 24,
    "navtool_icon_base_color": "#c4cacf",       # Icones > Couleur des icones (main_window/chrome._refresh_navbar_icons)
    "last_save_dir": "",  # dernier dossier d'enregistrement / d'export de l'appli (save_dialog_memory)
    "last_open_dir": "",  # dernier dossier d'ouverture / de chargement de l'appli (save_dialog_memory)
    "navtool_icon_tone_value": 30,  # module ouvert a l'icone coloree : valeur du fond (% de celle de l'icone)
    # Colonne Couleur du tableau d'icones de la barre (settings_window_v2.NAVBAR_ICON_COLORS) : fusion produit.
    "navtool_icon_color_theme": "#f28c28", "navtool_icon_color_viewer": "#ffffff",
    "navtool_icon_color_text_editor": "#ffffff", "navtool_icon_color_board": "#ffffff",
    "navtool_icon_color_video": "#ffffff", "navtool_icon_color_font": "#ffffff", "navtool_icon_color_pdf": "#ffffff",
    "navtool_icon_color_agenda": "#ffffff",
    "navtool_icon_color_taches": "#ffffff",
    "navtool_padding": {"left": 0, "top": 0, "right": 0, "bottom": 0},
    "navtool_padding_linked": True,
    # Boutons de la fenetre (punaise, reduire, agrandir, fermer ; fm_theme > Barre de navigation > Boutons fenetre,
    # 2026-11-07) : CARRES, colles en haut de la fenetre, cadre peint (IconButton).
    "navbar_winbtn_size": 30,
    "navbar_winbtn_margin": {"left": 0, "top": 0, "right": 0, "bottom": 0},
    "navbar_winbtn_margin_linked": True,
    "navbar_winbtn_padding": {"left": 0, "top": 0, "right": 0, "bottom": 0},
    "navbar_winbtn_padding_linked": True,
    "navbar_winbtn_bg_color": "#00000000",
    "navbar_winbtn_border_enabled": {"top": False, "right": False, "bottom": False, "left": False},
    "navbar_winbtn_border": {side: "#303539" for side in ("top", "right", "bottom", "left")},
    "navbar_winbtn_border_thickness": 1,
    "navbar_winbtn_corner_radius": {"top_left": 0, "top_right": 0, "bottom_right": 0, "bottom_left": 0},
    "navbar_winbtn_corner_radius_linked": True,
    "navbar_winbtn_hover_bg_color": "@hover",
    "navbar_winbtn_close_hover_bg_color": "#c42b1c",   # survol du bouton fermer (rouge)
    "navbar_bottom_enabled": True,
    "navbar_bottom_color": "#2c3034",
    "navbar_bottom_thickness": 1,
    "navbar_title_font_family": "",
    "navbar_title_font_size": 11,
    "navbar_title_font_bold": False,
    "navbar_title_font_italic": False,
    "navbar_title_font_color": "#7d858b",
    "navbar_title_font_smoothing_enabled": False,
    "navbar_title_font_smoothing": "current",
    # Barre d'etat (fm_theme > Barre d'etat, 2026-11-05) : bas de la fenetre principale (chemin a gauche, infos a
    # droite) ; valeurs par defaut = l'aspect d'avant (24 px, C['chrome'], filet C['border'], roles info / info2).
    "statusbar_height": 24,
    "statusbar_bg_color": "#202326",
    "statusbar_top_enabled": True,
    "statusbar_top_color": "#2c3034",
    "statusbar_top_thickness": 1,
    "statusbar_padding_x": 10,
    "statusbar_spacing": 12,
    "statusbar_path_font_family": "",
    "statusbar_path_font_size": 11,
    "statusbar_path_font_bold": False,
    "statusbar_path_font_italic": False,
    "statusbar_path_font_color": "#b9bfc4",
    "statusbar_path_font_smoothing_enabled": False,
    "statusbar_path_font_smoothing": "current",
    "statusbar_info_font_family": "",
    "statusbar_info_font_size": 11,
    "statusbar_info_font_bold": False,
    "statusbar_info_font_italic": False,
    "statusbar_info_font_color": "#5f666b",
    "statusbar_info_font_smoothing_enabled": False,
    "statusbar_info_font_smoothing": "current",
    "button_bg_color": "#282c30",
    "button_border_enabled": True,
    "button_border": {side: "#383d42" for side in ("top", "right", "bottom", "left")},
    "button_border_thickness": 1,
    "button_corner_radius": None,
    "button_font_family": "",
    "button_font_size": 11,
    "button_font_bold": False,
    "button_font_italic": False,
    "button_font_color": "#c4cacf",
    "button_font_smoothing_enabled": False,
    "button_font_smoothing": "current",
    # Décalage du texte dans le bouton, tous les états (-10..+10 px ; fm_theme.style.button_text_offset, 2026-11-12)
    "button_text_offset_x": 0, "button_text_offset_y": 0,
    # Survol et état actif (enfoncé / focus) ; transparent = le thème, épaisseur 0 = celle de l'état standard
    # (variante « toolbar » tirée des barres d'outils, 2026-11-10)
    "button_hover_color": "#00000000", "button_active_color": "#00000000",
    # Survol et focus complets (2026-11-11) ; transparent = inchangé, focus = le bouton qui a le focus clavier.
    # Bordures de chaque état = une ligne Bordures standard (côtés, couleur par côté, épaisseur) et police = gras
    # + couleur du texte (demande de l'utilisateur, 2026-11-11)
    **{key: value for state in ("hover", "focus", "active") for key, value in (
        (f"button_{state}_border_enabled", {"top": True, "right": True, "bottom": True, "left": True}),
        (f"button_{state}_border_enabled_linked", True),
        (f"button_{state}_border", {"top": "#00000000", "right": "#00000000", "bottom": "#00000000",
                                    "left": "#00000000"}),
        (f"button_{state}_border_thickness", 0),
        (f"button_{state}_text_color", "#00000000"),   # enfoncé : transparent = « Texte sur accent » du thème
        (f"button_{state}_font_bold", False),
        (f"button_{state}_offset_x", 0), (f"button_{state}_offset_y", 0),     # Décalage : -3..+3 px
        # Chaque ligne d'un état = override de l'état standard (2026-11-12, fm_theme.style.button_state_override) :
        # toggle None = déduit des valeurs (réglages d'avant) ; police entière et rayon None = ceux du standard.
        *((f"button_{state}_ovr_{row}", None) for row in ("color", "border", "font", "radius", "shadow")),
        *((f"button_{state}_font_{name}", None)
          for name in ("family", "size", "italic", "smoothing_enabled", "smoothing")),
        (f"button_{state}_corner_radius", None), (f"button_{state}_corner_radius_linked", None),
        (f"button_{state}_follow", "standard"))},           # lignes non surchargées : l'état suivi (2026-11-12)
    "button_focus_color": "#00000000",
    "input_bg_color": "@saisie",                # fm_theme > Couleurs > Zone de saisie (C["well"])
    "input_border_enabled": True,
    "input_border": {side: "#303539" for side in ("top", "right", "bottom", "left")},
    "input_border_thickness": 1,
    "input_corner_radius": None,
    "input_font_family": "",
    "input_font_size": 11,
    "input_font_bold": False,
    "input_font_italic": False,
    "input_font_color": "#b9bfc4",
    "input_font_smoothing_enabled": False,
    "input_font_smoothing": "current",
    # Barre de navigation > Cheminement : les onglets (refonte du 2026-11-08, main_window/title_bar._crumb_look).
    "crumb_left_spacing": 10,               # avant le 1er onglet
    "crumb_spacing": 5,                     # entre les onglets
    "crumb_cut_border_active": False,       # sous l'onglet actif : ni sa bordure basse ni le filet de la barre
    "crumb_cut_border_others": False,       # idem sous les autres onglets
    "crumb_bg_color": "@skinN1",
    "crumb_border_enabled": {"top": False, "right": False, "bottom": False, "left": False},
    "crumb_border": {side: "#303539" for side in ("top", "right", "bottom", "left")},
    "crumb_border_thickness": 1,
    "crumb_corner_radius": {"top_left": 0, "top_right": 0, "bottom_right": 0, "bottom_left": 0},
    "crumb_corner_radius_linked": True,
    # Transparent = la couleur de fond commune.
    "crumb_active_bg_color": "#00000000",
    "crumb_hover_bg_color": "#00000000",
    "crumb_after_active_bg_color": "#00000000",
    "crumb_font_family": "",
    "crumb_font_size": 10,
    "crumb_font_bold": False,
    "crumb_font_italic": False,
    "crumb_font_color": "#b9bfc4",
    "crumb_font_smoothing_enabled": False,
    "crumb_font_smoothing": "current",
    "crumb_after_active_font_family": "",
    "crumb_after_active_font_size": 10,
    "crumb_after_active_font_bold": False,
    "crumb_after_active_font_italic": False,
    "crumb_after_active_font_color": "#5f666b",
    "crumb_after_active_font_smoothing_enabled": False,
    "crumb_after_active_font_smoothing": "current",
    "input_height": 0,                  # 0 = la hauteur propre a chaque zone de saisie
    "tabs_bottom_enabled": True,        # bordure entre la barre des tabs et l'interface
    "tabs_bottom_color": "#2a2e32",
    "tabs_bottom_thickness": 1,
    "tabs_height": 36,
    "tabs_spacing": 4,
    "tabs_strip_color": "#00000000",    # transparent = la couleur habituelle de la barre des tabs
    "tabs_inactive_border_enabled": {"top": False, "right": False, "bottom": False, "left": False},
    "tabs_inactive_border": {side: "#303539" for side in ("top", "right", "bottom", "left")},
    "tabs_inactive_border_thickness": 1,
    "tabs_bg_color": "#00000000",
    "tabs_active_bg_color": "#00000000",
    "tabs_hover_bg_color": "#00000000",
    "tabs_border_enabled": {"top": False, "right": False, "bottom": True, "left": False},
    "tabs_border": {side: "#3f6f9f" for side in ("top", "right", "bottom", "left")},
    "tabs_border_thickness": 2,
    "tabs_corner_radius": 0,
    "tabs_font_family": "",
    "tabs_font_size": 11,
    "tabs_font_bold": True,
    "tabs_font_italic": False,
    "tabs_font_color": "#5f9bd0",
    "tabs_font_smoothing_enabled": False,
    "tabs_font_smoothing": "current",
    "table_radius": 0,
    "table_bg_color": "@tableRow",              # Theme > Tableaux > Couleur de fond (fm_theme.tokens.set_table_bg)
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
    # Couleur des SELECTIONS dans les tableaux (colonnes, sous-cellules : teinte translucide) et de
    # la carte du toggle choisi dans Toggles (voir settings_widgets._TABLE_SELECTION).
    "table_selection_color": "#5f9bd0",
    # Lignes des tableaux deplacables (Ctrl + glisser la 1re cellule), voir settings_cells._RowMover.
    "table_rows_movable": True,
    # Couleur de la bande de legendes des cellules divisees (meme forme que table_head_color).
    "table_cell_head_color": "tableHead",
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
    # Bordures INTERIEURES des tableaux : H = filets horizontaux entre les
    # lignes (et sous l'entete), V = filets verticaux entre les colonnes ;
    # jamais ceux qui touchent le bord du tableau (voir "table_border").
    # Texte au-dessus d'une ligne de tableau (clic droit > « Ajouter un texte au-dessus… ») : ligne gabarit police.
    "table_above_text_font_family": "", "table_above_text_font_bold": False, "table_above_text_font_italic": False,
    "table_above_text_font_size": 11, "table_above_text_font_smoothing_enabled": False,
    "table_above_text_font_smoothing": "current", "table_above_text_font_color": "#8d949a",
    "table_inner_h_enabled": True,
    "table_inner_h_color": "#2a2e32",
    "table_inner_h_thickness": 1,
    "table_inner_v_enabled": False,
    "table_inner_v_color": "#2a2e32",
    "table_inner_v_thickness": 1,
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
    # Dimensions de tous les tableaux des reglages (voir _TableFrame.dimsKey) :
    # {cle: {"width": largeur du tableau (0 = pleine), "cols": [largeurs de colonnes]}}.
    "table_dims": {},
    "slider_ranges": {},       # plages min/max modifiees par clic droit sur un curseur (v2) : {cle: [min, max]}
    "element_spaces": {},      # espace au-dessus d'un element d'une zone titre, par clic droit (v2) : {cle: px}
    "element_spaces_below": {},  # espace en dessous, meme principe
    "title_order": {},         # ordre des paragraphes (titres freres) choisi en tirant un titre (v2) : {pile: [titres]}
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
    # Fond et coche PAR ETAT (Toggles > <style> > Etat OFF / Etat ON, `<style>_off_*` / `<style>_on_*`) :
    # ajoutes apres ce dict depuis fm_theme.toggle_states.defaults (les anciennes cles `_outer_*` /
    # `_coche_*`, un seul cadre et une seule coche pour les deux etats, sont reprises a la lecture).
    # Type de toggle (Toggles > <nom> > Type) : "qt" (cadre + coche peints) ou "icons" (image ON /
    # image OFF, et une sequence d'images optionnelle jouee entre les deux). Images importees dans
    # data/toggle_icons/ (noms de fichiers).
    "toggle1_kind": "qt",
    "toggle1_motion": "slide",               # coche : "slide" (glissiere) | "fade" (centree, fondu)
    "toggle1_icon_on": "",
    "toggle1_icon_off": "",
    "toggle1_icon_frames": [],
    "toggle1_anim_ms": 140,
    "toggle2_kind": "qt",
    "toggle2_motion": "fade",
    "toggle2_icon_on": "",
    "toggle2_icon_off": "",
    "toggle2_icon_frames": [],
    "toggle2_anim_ms": 140,
    # Styles de toggle AJOUTES par l'utilisateur (Toggles > Style > clic droit > Ajouter un nouveau
    # toggle) : [{"key": "toggle3", "name": "Mon toggle"}]. Leurs reglages `toggle3_*` suivent le
    # meme schema que toggle1_* (voir _DYNAMIC_KEY).
    "toggle_custom_styles": [],
    # TOUS les styles de toggle, dans l'ordre (remplace toggle_custom_styles, relu par
    # toggle_style_list) : chacun peut etre renomme ou supprime (il en reste toujours un).
    "toggle_styles": [{"key": "toggle1", "name": "Toggle 1"}, {"key": "toggle2", "name": "Toggle 2"}],
    # Style choisi pour UN toggle (clic droit sur le toggle > Style du toggle) : {identifiant du
    # toggle: cle de style}. Identifiant pose par la fenetre qui le contient (voir _Toggle.style_id).
    "toggle_style_overrides": {},
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
    # Preset ACTIF (choisi dans le menu deroulant de la fenetre principale) : ses valeurs sont celles a
    # l'ecran, les modifications l'enregistrent. None = jamais choisi (on suit `default_preset`).
    "active_preset": None,
    # Preset fm_theme a l'ecran (aspect generique : fm_theme/presets/<nom>.json) : TOUJOURS le preset de l'appli
    # (meme nom, pose par load_settings, demande de l'utilisateur 2026-10-30). "" = aucun preset fm_theme.
    "theme_preset": "",
    # Variante d'un type d'element (titres, boutons, tableaux...) que fm_browser UTILISE a la place de la variante par
    # defaut du preset fm_theme : {type: variante} (decide par l'utilisateur, 2026-10-27). Le preset n'est pas modifie.
    "theme_default_variants": {},
    # Gabarits des lignes des fenetres de reglages ({type de ligne: aspect}, fm_theme.cells) : ranges dans le preset
    # fm_theme lie (valeur generale du theme, fm_theme.presets.GENERAL_KEYS).
    "row_templates": {},
}

# Section "TITRE" (voir SettingsWindow._section_titre/_TITLE_LEVEL_DEFAULTS,
# General > TITRE) : police/couleur/retrait des titres de _Section (niveau
# 1) et _SubSection (niveaux 2-5) de CETTE fenetre — genere depuis les
# MEMES defauts que _TITLE_LEVEL_STYLE (pas de duplication).
for _title_level, _title_defaults in _TITLE_LEVEL_DEFAULTS.items():
    for _title_key, _title_val in _title_defaults.items():
        DEFAULT_SETTINGS[f"title_level{_title_level}_{_title_key}"] = json.loads(json.dumps(_title_val))

del _title_level, _title_defaults, _title_key, _title_val

# Lignes « Ombres » (settings_widgets.shadow_look) : cotes, couleur par cote (opacite comprise), taille.
SHADOW_PREFIXES = ("button_shadow", "button_hover_shadow", "button_focus_shadow", "button_active_shadow", "item_image_shadow", "preview_shadow", "viewer_film_image_shadow", "viewer_focus_image_shadow",
                   "table_shadow", "viewer_film_table_shadow", "ctx_menu_shadow", "extra_window_shadow",
                   "video_frame_shadow")
for _shadow in SHADOW_PREFIXES:
    DEFAULT_SETTINGS[f"{_shadow}_enabled"] = {"top": False, "right": False, "bottom": False, "left": False}
    DEFAULT_SETTINGS[_shadow] = {"top": "#8c000000", "right": "#8c000000", "bottom": "#8c000000",
                                 "left": "#8c000000"}
    DEFAULT_SETTINGS[f"{_shadow}_size"] = 10
    DEFAULT_SETTINGS[f"{_shadow}_enabled_linked"] = True
del _shadow
# Etat du toggle « lier les 4 » de chaque ligne a cotes / coins / padding : une cle `<cle>_linked` DOIT etre declaree
# ici, sinon `load_settings` l'ignore et le toggle ne se retrouve pas a la reouverture (signale : Tabs > Border radius).
for _key, _default in (("button_border_enabled", False), ("button_corner_radius", True),
                       ("input_border_enabled", False), ("input_corner_radius", True),
                       ("tabs_border_enabled", False), ("tabs_inactive_border_enabled", False),
                       ("tabs_corner_radius", True), ("crumb_border_enabled", False),
                       ("navtool_border_enabled", False), ("navbar_winbtn_border_enabled", False),
                       ("ctx_menu_border_enabled", False), ("step_badge_border_enabled", False),
                       ("item_selection_unfocus_padding", True), ("item_selection_hover_padding", True),
                       ("item_selection_idle_padding", True)):
    DEFAULT_SETTINGS.setdefault(f"{_key}_linked", _default)
del _key, _default
# Menus contextuels : leur ombre remplace celle de Windows (coupee, elle debordait des coins arrondis) ->
# allumee par defaut, halo doux.
DEFAULT_SETTINGS["ctx_menu_shadow_enabled"] = {"top": True, "right": True, "bottom": True, "left": True}
DEFAULT_SETTINGS["ctx_menu_shadow"] = {s: "#73000000" for s in ("top", "right", "bottom", "left")}
DEFAULT_SETTINGS["ctx_menu_shadow_size"] = 12
# Ombre des fenetres additionnelles : allumee (elle remplace l'ombre de Windows).
DEFAULT_SETTINGS["extra_window_shadow_enabled"] = {"top": True, "right": True, "bottom": True, "left": True}
DEFAULT_SETTINGS["extra_window_shadow"] = {s: "#73000000" for s in ("top", "right", "bottom", "left")}
DEFAULT_SETTINGS["extra_window_shadow_size"] = 14

# Toggles : fond et coche PAR ETAT (OFF / ON), `_linked` compris (fm_theme/toggle_states.py).
for _p in ("toggle1", "toggle2"):
    DEFAULT_SETTINGS.update(_toggle_states.defaults(_p))
del _p

# Etat « lier les 4 » des lignes Bordures (comme `<cle>_linked` des coins et du padding).
for _sides_key in ("column_border_enabled", "header_border_enabled", "item_image_border_enabled",
                   "resize_badge_border_enabled", "table_border_enabled", "slider_thumb_border_enabled",
                   "slider_track_border_enabled",
                   *(f"viewer_film_{_part}_border_enabled" for _part in ("table", "image_cell", "image", "text_cell")),
                   "viewer_focus_image_border_enabled", "viewer_filter_row_border_enabled",
                   "extra_window_border_enabled", "window_border_enabled",
                   *(f"item_selection{_state}_border_enabled" for _state in ("", "_unfocus", "_hover", "_idle"))):
    DEFAULT_SETTINGS[f"{_sides_key}_linked"] = False
del _sides_key

# Cles creees a l'execution (reglages des styles de toggle ajoutes : toggle3_*, toggle4_*...) : pas dans
# DEFAULT_SETTINGS, mais a conserver au chargement.
_DYNAMIC_KEY = re.compile(r"^toggle(?:[3-9]\d*|[1-9]\d+)_")
# Toggle « activer » d'une ligne Bordures / Border radius / Ombres / Padding / Margin (settings_window_v2,
# `activation_keys`, 2026-11-11) : `<clé>__on` (état) et `<clé>__kept` (valeurs gardées quand il est coupé) ;
# acceptées sans être déclarées (une paire par ligne de toutes les fenêtres), retenues par les presets.
_ACTIVATION_KEY = re.compile(r"__(?:on|kept)$")


# Board (MRO) et CAD : défauts dans leur paquet (fm_board/settings_defaults.py, fm_cad/settings_defaults.py).
from fm_board.settings_defaults import BOARD_DEFAULTS  # noqa: E402
from fm_cad.settings_defaults import CAD_DEFAULTS  # noqa: E402
DEFAULT_SETTINGS.update(BOARD_DEFAULTS)
DEFAULT_SETTINGS.update(CAD_DEFAULTS)
# Reglages > Module MRO > Menus contextuels : les MEMES reglages que Menu contextuel, propres au board (`board_<cle>`),
# chacun avec son interrupteur d'override (`board_ovr_<cle>`, coupe = suit le menu de l'appli).
BOARD_MENU_KEYS = tuple(k for k in DEFAULT_SETTINGS if k.startswith("ctx_menu"))
for _key in BOARD_MENU_KEYS:
    DEFAULT_SETTINGS[f"board_{_key}"] = json.loads(json.dumps(DEFAULT_SETTINGS[_key]))
    DEFAULT_SETTINGS[f"board_ovr_{_key}"] = False
del _key

# Barre de navigation de fm_browser (demande de l'utilisateur, 2026-11-07) : bordure basse, police du titre et
# hauteur de fm_theme surchargeables dans les reglages de fm_browser — copie `navtool_<...>` de chaque cle
# `navbar_<...>`, interrupteur `navtool_ovr_<ligne>` (coupe = la valeur de fm_theme). Lu par `navbar_effective`.
NAVBAR_OVERRIDE_ROWS = {"bottom_enabled": "navbar_bottom_", "title_font_family": "navbar_title_font_",
                        "height": "navbar_height"}
NAVBAR_OVERRIDE_KEYS = {row: tuple(k for k in DEFAULT_SETTINGS if k.startswith(prefix))
                        for row, prefix in NAVBAR_OVERRIDE_ROWS.items()}
for _row, _keys in NAVBAR_OVERRIDE_KEYS.items():
    for _key in _keys:
        DEFAULT_SETTINGS["navtool" + _key[len("navbar"):]] = json.loads(json.dumps(DEFAULT_SETTINGS[_key]))
    DEFAULT_SETTINGS[f"navtool_ovr_{_row}"] = False
del _row, _keys, _key

_NAVBAR_EFFECTIVE: list = [None, None]


def navbar_effective(settings: dict) -> dict:
    """Reglages de la barre de navigation de la fenetre principale : ceux de fm_theme (`navbar_*`), remplaces par
    ceux de fm_browser (`navtool_*`) dont l'override est allume. Meme objet si aucun override ; calcule une fois
    par jeu de reglages (relu a chaque placement du cheminement)."""
    if _NAVBAR_EFFECTIVE[0] is settings and _NAVBAR_EFFECTIVE[1] is not None:
        return _NAVBAR_EFFECTIVE[1]
    result = settings
    for row, keys in NAVBAR_OVERRIDE_KEYS.items():
        if settings.get(f"navtool_ovr_{row}"):
            if result is settings:
                result = dict(settings)
            for key in keys:
                own = "navtool" + key[len("navbar"):]
                if own in settings:
                    result[key] = settings[own]
    _NAVBAR_EFFECTIVE[0], _NAVBAR_EFFECTIVE[1] = settings, result
    return result


# Module Markdown : défauts dans son paquet (fm_markdown/settings_defaults.py, source unique).
from fm_markdown.settings_defaults import MARKDOWN_DEFAULTS  # noqa: E402
DEFAULT_SETTINGS.update(MARKDOWN_DEFAULTS)
from fm_tableur.settings_defaults import TABLEUR_DEFAULTS  # noqa: E402
DEFAULT_SETTINGS.update(TABLEUR_DEFAULTS)
from fm_design.settings_defaults import DESIGN_DEFAULTS  # noqa: E402
DEFAULT_SETTINGS.update(DESIGN_DEFAULTS)
# Palette flottante à grille (type « palette » de fm_theme) : défauts dans fm_theme/palette_defaults.py.
from fm_theme.palette_defaults import PALETTE_DEFAULTS  # noqa: E402
DEFAULT_SETTINGS.update(PALETTE_DEFAULTS)
from fm_illustrator.settings_defaults import ILL_DEFAULTS  # noqa: E402
DEFAULT_SETTINGS.update(ILL_DEFAULTS)
from fm_photoshop.settings_defaults import PS_DEFAULTS  # noqa: E402
DEFAULT_SETTINGS.update(PS_DEFAULTS)
# Module typographique : défauts dans son paquet (fm_font/settings_defaults.py, source unique).
from fm_font.settings_defaults import TYPO_DEFAULTS  # noqa: E402
DEFAULT_SETTINGS.update(TYPO_DEFAULTS)
# Module PDF (fm_pdf/settings_defaults.py)
from fm_pdf.settings_defaults import PDF_DEFAULTS  # noqa: E402
DEFAULT_SETTINGS.update(PDF_DEFAULTS)
# Agenda (fm_agenda/settings_defaults.py)
from fm_agenda.settings_defaults import AGENDA_DEFAULTS  # noqa: E402
DEFAULT_SETTINGS.update(AGENDA_DEFAULTS)
# Tâches (fm_taches/settings_defaults.py)
from fm_taches.settings_defaults import TACHES_DEFAULTS  # noqa: E402
DEFAULT_SETTINGS.update(TACHES_DEFAULTS)

# Module vidéo : défauts dans son paquet (fm_video/settings_defaults.py, source unique).
from fm_video.settings_defaults import VIDEO_DEFAULTS  # noqa: E402
DEFAULT_SETTINGS.update(VIDEO_DEFAULTS)

_LIVE_STATE_KEYS = ("md_toolbar_font_color", "md_toolbar_background_color", "md_bars",
                    "table_dims", "slider_ranges", "toggle_custom_styles", "toggle_styles",
                    "toggle_style_overrides", "element_spaces", "ui_spaces",
                    "element_spaces_below", "ui_spaces_below", "title_order", "element_style_overrides",
                    "viewer_film_text_ratio", "viewer_gallery_text_height", "context_menu_layouts",
                    "viewer_button_order", "viewer_recursive", "md_last_mode", "md_code_font_zoom",
                    "md_spell_words", "board_pen_presets", "board_design_brand", "board_modulebar_folded", "board_bars", "typo_bars", "window_always_on_top",
                    "quick_style_positions", "interface_move_positions",
                    "interface_edit_appearance", "video_grade", "video_grade_presets", "video_export_last",
                    "video_info_enabled", "video_loop", "video_volume", "video_last_zoom",
                    "video_time_display", "video_scopes", "video_timeline_thumb_height",
                    "agenda_theme", "agenda_default_calendar", "taches_theme", "taches_show_done", "last_save_dir", "last_open_dir")






def import_toggle_image(source: str, style_key: str) -> str:
    """Copie une image choisie par l'utilisateur dans data/toggle_icons/ (pour ne pas dependre de
    son emplacement d'origine) ; renvoie le nom du fichier copie."""
    import shutil
    from fm_theme import tokens            # lu a l'appel (dossier redirige par les tests)
    folder = tokens._TOGGLE_ICONS_DIR
    src = Path(source)
    folder.mkdir(parents=True, exist_ok=True)
    name = f"{style_key}_{src.stem}{src.suffix.lower()}"
    target, n = folder / name, 1
    while target.exists() and target.resolve() != src.resolve():
        n += 1
        name = f"{style_key}_{src.stem}_{n}{src.suffix.lower()}"
        target = folder / name
    if target.resolve() != src.resolve():
        shutil.copyfile(src, target)
    return name

def load_settings(startup: bool = False) -> dict[str, Any]:
    """Reglages : valeurs par defaut, puis `pipeline_settings.json`, puis le preset ACTIF par-dessus
    (au lancement, `startup` : le preset PAR DEFAUT, qui devient l'actif). L'etat temps reel
    (`_LIVE_STATE_KEYS`) et les cles propres a la machine (`PRESET_EXCLUDED_KEYS`) ne viennent jamais
    d'un preset."""
    settings = json.loads(json.dumps(DEFAULT_SETTINGS))

    def _merge(data: dict):
        for key, value in data.items():
            if key not in DEFAULT_SETTINGS and not _DYNAMIC_KEY.match(key) and not _ACTIVATION_KEY.search(key):
                continue
            if isinstance(value, dict) and isinstance(settings.get(key), dict):
                for sub_key, sub_val in value.items():
                    if isinstance(sub_val, dict) and isinstance(settings[key].get(sub_key), dict):
                        settings[key][sub_key].update(sub_val)
                    else:
                        settings[key][sub_key] = sub_val
            else:
                settings[key] = value

    raw: dict = {}
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
            # Bordure d'un état du bouton : une couleur -> la ligne Bordures standard (couleur par côté), 2026-11-11
            for state in ("hover", "focus", "active"):
                old = raw.get(f"button_{state}_border_color")
                if old and f"button_{state}_border" not in raw:
                    raw[f"button_{state}_border"] = dict.fromkeys(("top", "right", "bottom", "left"), old)
            # copie : _merge partage les sous-dicts, le preset les modifierait ; anciennes cles des toggles reprises
            _merge(_toggle_states.fill_toggle_states(json.loads(json.dumps(raw))))
    except (OSError, ValueError):
        pass
    # Preset ACTIF (menu deroulant de la fenetre principale) applique PAR-DESSUS pipeline_settings.json
    # a chaque chargement ; au lancement, le preset PAR DEFAUT (General > Application) devient l'actif,
    # et le fichier le retient aussitot (sinon une relecture en cours de route reprendrait l'actif de la
    # session precedente). Silencieux si le preset nomme a ete supprime (fichier seul).
    default_preset = settings.get("default_preset")
    name = preset_in_use(settings, startup)
    if startup:
        settings["active_preset"] = name
        if raw and raw.get("active_preset") != settings["active_preset"]:
            raw["active_preset"] = settings["active_preset"]
            save_settings(raw)
    if name:
        presets = _load_presets()
        layer = _layer(presets, name)
        if layer is not None:
            _merge(_toggle_states.fill_toggle_states(
                {k: v for k, v in layer.items() if k not in PRESET_EXCLUDED_KEYS}))
            # "default_preset" fait lui-meme PARTIE des cles capturees par
            # un preset (voir _current_values, "je veux que absolument
            # tous les parametres soient enregistres dans les presets") —
            # sans repli EXPLICITE ici, le _merge ci-dessus l'ecraserait
            # avec la valeur qu'AVAIT ce preset AU MOMENT ou il a ete
            # enregistre (typiquement vide), faisant "oublier" a l'appli,
            # des ce premier chargement, LEQUEL preset par defaut vient
            # justement d'etre applique.
            settings["default_preset"] = default_preset
        settings["theme_preset"] = name          # un preset de l'appli = le preset fm_theme DE MEME NOM
    # Aspect generique : le preset fm_theme (theme_preset) par-dessus.
    theme = _load_theme_values(settings.get("theme_preset") or "", settings.get("theme_default_variants"))
    if theme:
        _merge(theme)
    if name or theme:
        # Etat enregistre en temps reel par la fenetre v2 (dimensions, plages, styles de
        # toggle crees) : il n'appartient pas au preset, qui l'ecraserait a chaque chargement.
        for key in _LIVE_STATE_KEYS:
            if key in raw:
                settings[key] = raw[key]
        for key, value in raw.items():
            if _DYNAMIC_KEY.match(key):
                settings[key] = value
    for new_key, old_key in (("button_corner_radius", "button_radius"),
                             ("input_corner_radius", "input_radius")):
        if settings.get(new_key) is None:
            settings[new_key] = settings.get(old_key, 0)
    _prune_column_overrides(settings, raw)
    for name, dims in (settings.get("table_dims") or {}).items():
        if name.endswith("Bouton#0") and isinstance(dims, dict):
            _migrate_button_dims(dims)
    return settings


# Tableau Thème > Bouton : mises en page enregistrées converties à chaque changement de ses lignes (2026-11-11).
# Étape 1 (17 -> 14) : les 4 lignes de chaque état (fond, texte, couleur de bordure, épaisseur) deviennent 3 (fond,
# Bordures standard, police) ; les lignes Bordures reprennent la mise en page de la ligne Bordures standard (1).
# Étape 2 (14 -> 20) : chaque état gagne Décalage et Ombres après sa police ; ses Ombres reprennent la mise en page
# de la ligne Ombres standard (13). Tout nouveau changement des lignes de Bouton = une étape de plus ici.
def _sort_state_groups(order: list) -> list:
    for group in ((2, 3, 4), (5, 6, 7), (8, 9, 10)):     # chaque état : fond, bordures, police dans ses emplacements
        slots = [i for i, r in enumerate(order) if r in group]
        for i, r in zip(slots, sorted(order[i] for i in slots)):
            order[i] = r
    return order


def _after_state_borders(order: list) -> list:
    out = []
    for r in order:
        out.append(r)
        if r in (3, 9, 15):                               # bordures d'un état : puis sa police et son border radius
            out += [r + 1, r + 2]
    return out


def _before_state_colors(order: list) -> list:
    out = []
    for r in order:
        if r in (3, 10, 17):                              # couleur de fond d'un état : sa ligne « suit » juste avant
            out.append(r - 1)
        out.append(r)
    return out


def _onto_follow_rows(dims: dict, remap: dict) -> None:
    """Coupe, texte au-dessus et repli de la couleur de fond d'un état -> sa ligne « suit » (qui ouvre la partie)."""
    for key in ("row_splits", "above_texts"):
        value = dims.get(key)
        if isinstance(value, dict):
            dims[key] = {str(int(k) - 1) if k.isdigit() and int(k) in (3, 10, 17) else k: v for k, v in value.items()}
    if isinstance(dims.get("collapsed"), list):
        rows = [remap.get(r, r) for r in dims["collapsed"] if isinstance(r, int)]
        dims["collapsed"] = [r - 1 if r in (3, 10, 17) else r for r in rows]


def _after_state_fonts(order: list) -> list:
    out = []
    for r in order:
        out.append(r)
        if r in (4, 9, 14):                               # police d'un état : puis son décalage et ses ombres
            out += [r + 1, r + 2]
    return out


def _remap_collapsed(dims: dict, remap: dict) -> None:
    if isinstance(dims.get("collapsed"), list):
        dims["collapsed"] = [remap[r] for r in dims["collapsed"] if isinstance(r, int) and r in remap]


def _after_standard_font(order: list) -> list:
    out = []
    for r in order:
        out.append(r)
        if r == 23:                                       # Polices standard : puis le décalage du texte
            out.append(24)
    return out


_BUTTON_DIMS_STEPS = (
    (17, 14, {0: 0, 1: 1, 2: 2, 3: 4, 4: 3, 6: 5, 7: 7, 8: 6, 10: 8, 11: 10, 12: 9, 14: 11, 15: 12, 16: 13},
     {3: 1, 6: 1, 9: 1}, _sort_state_groups),
    (14, 20, {0: 0, 1: 1, 2: 2, 3: 3, 4: 4, 5: 7, 6: 8, 7: 9, 8: 12, 9: 13, 10: 14, 11: 17, 12: 18, 13: 19},
     {6: 13, 11: 13, 16: 13}, _after_state_fonts),
    # Étape 3 (20 -> 23, 2026-11-12) : chaque état = overrides des lignes standard ; sa police (gras + couleur) devient
    # la ligne Polices standard entière et il gagne Border radius : elles reprennent la mise en page des lignes
    # standard (Polices 17, Border radius 18).
    (20, 23, {0: 0, 1: 1, 2: 2, 3: 3, 5: 6, 6: 7, 7: 8, 8: 9, 10: 12, 11: 13, 12: 14, 13: 15, 15: 18, 16: 19,
              17: 20, 18: 21, 19: 22},
     {4: 17, 10: 17, 16: 17, 5: 18, 11: 18, 17: 18}, _after_state_borders),
    # Étape 4 (23 -> 26, 2026-11-12) : chaque état s'ouvre sur une ligne « suit » (liste + « Réinitialiser ») ; sa coupe,
    # son texte au-dessus et son repli passent de sa couleur de fond à cette ligne (`_onto_follow_rows`).
    (26 - 3, 26, {**{r: r for r in (0, 1)}, **{r: r + 1 for r in range(2, 8)}, **{r: r + 2 for r in range(8, 14)},
                  **{r: r + 3 for r in range(14, 23)}},
     {}, _before_state_colors, _onto_follow_rows),
    # Étape 5 (26 -> 27, 2026-11-12) : « Décalage du texte » sous Polices standard (23) ; il reprend la mise en page
    # de la ligne Décalage de l'état survol (7).
    (26, 27, {**{r: r for r in range(24)}, 24: 25, 25: 26}, {24: 7}, _after_standard_font, _remap_collapsed),
)


def _migrate_button_dims(dims: dict) -> None:
    """Mise en page enregistrée d'un ancien tableau Bouton convertie sur place, étape par étape ; rien sinon."""
    for old_rows, new_rows, remap, copies, fix_order, *after in _BUTTON_DIMS_STEPS:
        if any(isinstance(dims.get(k), list) and len(dims[k]) == old_rows for k in ("row_order", "row_heights")):
            _remap_dims(dims, old_rows, new_rows, remap, copies, fix_order)
            for step in after:                            # ce que le renumérotage seul ne sait pas faire
                step(dims, remap)


def _remap_dims(dims: dict, old_rows: int, new_rows: int, remap: dict, copies: dict, fix_order) -> None:
    """Lignes logiques `remap` (ancienne -> nouvelle ; absente = supprimée) ; `copies` {nouvelle: ancienne dont
    elle reprend hauteur et sous-cellules}."""
    order = [remap[r] for r in dims.get("row_order") or () if r in remap]
    if order:
        order = fix_order(order)
        order += [r for r in range(new_rows) if r not in order]
        dims["row_order"] = order
    heights = dims.get("row_heights")
    if isinstance(heights, list) and len(heights) == old_rows:
        new = [0] * new_rows
        for old, row in remap.items():
            new[row] = heights[old]
        for row, source in copies.items():
            new[row] = heights[source]
        dims["row_heights"] = new
    cell = re.compile(r"r(\d+)c(\d+)$")
    for key, value in list(dims.items()):
        if not isinstance(value, dict) or key == "cols":
            continue
        out = {}
        for sub, item in value.items():
            match = cell.match(str(sub))
            if match:
                old, col = int(match.group(1)), match.group(2)
                if old in remap:
                    out[f"r{remap[old]}c{col}"] = item
                out.update({f"r{row}c{col}": json.loads(json.dumps(item))
                            for row, source in copies.items() if source == old})
            elif str(sub).isdigit():
                if int(sub) in remap:
                    out[str(remap[int(sub)])] = item
            else:
                out[sub] = item
        dims[key] = out


# Seules cles de surcharge de colonne encore lues : celles que le glisser des bordures enregistre.
_COLUMN_SIZE_KEYS = ("item_column_width", "item_row_height")


def _prune_column_overrides(settings: dict, raw: dict) -> None:
    """Les onglets de surcharge des colonnes n'existent plus : ne garde des surcharges que la largeur et
    la hauteur de ligne (colonnes Type / Projets / Sous-projet / Focus). Le ratio d'image de Focus,
    anciennement surcharge, devient `preview_image_ratio` (repris une fois s'il n'etait pas enregistre)."""
    focus_over = (settings.get("column_overrides_by_title") or {}).get("Focus") or {}
    focus_on = (settings.get("column_override_enabled_by_title") or {}).get("Focus") or {}
    if "preview_image_ratio" not in raw and focus_on.get("item_image_ratio") and "item_image_ratio" in focus_over:
        settings["preview_image_ratio"] = focus_over["item_image_ratio"]
    for over_key, on_key, by_title in (("column_type_overrides", "column_type_override_enabled", False),
                                       ("column_overrides_by_title", "column_override_enabled_by_title", True)):
        for key in (over_key, on_key):
            data = settings.get(key) or {}
            if by_title:
                data = {title: {k: v for k, v in (sub or {}).items() if k in _COLUMN_SIZE_KEYS}
                        for title, sub in data.items() if title in ("Projets", "Sous-projet", "Focus")}
            else:
                data = {k: v for k, v in data.items() if k in _COLUMN_SIZE_KEYS}
            settings[key] = data

# ---------------------------------------------------------------------------------------------------
# Presets : la LISTE est celle de fm_theme (fm_theme/presets/<nom>.json), creee, renommee et supprimee
# SEULEMENT dans fm_theme (demande de l'utilisateur, 2026-10-30). fm_browser y ajoute une COUCHE de
# reglages propres a l'appli, par nom de preset (data/pipeline_settings.presets.json, {nom: valeurs}) :
# choisir « neo » = l'aspect du preset fm_theme « neo » + la couche « neo » (absente : rien de plus).
# Jamais ce qui est propre a la machine ou a la mise en forme des fenetres.
# ---------------------------------------------------------------------------------------------------

PRESET_EXCLUDED_KEYS = frozenset(("root_path", "default_preset", "active_preset", "theme_preset",
                                  *_LIVE_STATE_KEYS))


def _theme_name(name: str) -> str:
    """Nom actuel du preset fm_theme `name` (un ancien nom garde en alias apres un renommage donne le nouveau) ;
    "" s'il n'existe pas."""
    path = _theme_presets.find_preset(name) if name else None
    if path is None:
        return ""
    if path == _theme_presets.preset_path(name):
        return name
    try:
        return _theme_presets.load_preset(path)["nom"]
    except (OSError, ValueError, KeyError):
        return ""


def preset_in_use(settings: dict, startup: bool = False) -> str:
    """Nom du preset a l'ecran, toujours un preset fm_theme existant : l'actif (choisi dans le menu deroulant),
    ou le preset par defaut au lancement / tant qu'aucun n'a ete choisi ; a defaut (supprime dans fm_theme...)
    le preset par defaut, le theme du fichier, puis le premier de la liste. "" = aucun preset fm_theme."""
    wanted = settings.get("default_preset") if startup or settings.get("active_preset") is None         else settings.get("active_preset")
    for candidate in (wanted, settings.get("default_preset"), settings.get("theme_preset")):
        name = _theme_name(candidate or "")
        if name:
            return name
    names = preset_names()
    return names[0] if names else ""


def _layer(presets: dict, name: str) -> dict | None:
    """Couche de fm_browser du preset `name` ; celle d'un ancien nom (preset renomme dans fm_theme) passe sous
    le nouveau. None : aucune."""
    if name in presets:
        return presets[name]
    try:
        aliases = _theme_presets.load_preset(_theme_presets.find_preset(name)).get("alias") or ()
    except (OSError, ValueError, TypeError):
        return None
    for alias in aliases:
        if alias in presets:
            presets[name] = presets.pop(alias)
            return presets[name]
    return None


def preset_values(settings: dict) -> dict:
    """Ce qu'un preset retient de `settings` (copie) : tout sauf `PRESET_EXCLUDED_KEYS` et les styles de
    toggle crees a l'execution (etat temps reel). Avec un preset fm_theme lie (`theme_preset`), l'aspect
    generique n'y est pas : il est dans le preset fm_theme (source unique)."""
    themed = bool(theme_in_use(settings))
    return {k: json.loads(json.dumps(v)) for k, v in settings.items()
            if k not in PRESET_EXCLUDED_KEYS and not _DYNAMIC_KEY.match(k)
            and not (themed and _theme_presets.theme_key(k))}


# -- Preset fm_theme lie (aspect generique) ---------------------------------------------------------------

def theme_in_use(settings: dict) -> str:
    """Nom du preset fm_theme dont l'aspect est a l'ecran ("" : aucun, ou introuvable)."""
    name = settings.get("theme_preset") or ""
    return name if _theme_presets.find_preset(name) is not None else ""


def _load_theme_values(name: str, variants: dict | None = None) -> dict:
    """Valeurs a plat du preset fm_theme `name`, variantes choisies par l'appli comprises ({} : absent ou
    illisible, repli silencieux)."""
    if not name:
        return {}
    try:
        return _theme_presets.to_settings(_theme_presets.load_preset(_theme_presets.find_preset(name)), variants)
    except (OSError, ValueError, KeyError, TypeError):
        return {}


def update_theme_preset(settings: dict) -> bool:
    """Modifications d'aspect enregistrees : elles vont dans le preset fm_theme lie (toutes les applis qui
    l'utilisent les voient). Fichier reecrit seulement si une valeur a change. Retourne True s'il l'a ete."""
    name = theme_in_use(settings)
    if not name:
        return False
    try:
        preset = _theme_presets.load_preset(_theme_presets.find_preset(name))
    except (OSError, ValueError, TypeError):
        return False
    # Chaque type s'ecrit dans la variante que l'appli UTILISE (jamais dans la variante par defaut a sa place).
    used = _theme_presets.used_variants(preset, settings.get("theme_default_variants"))
    current = _theme_presets.to_settings(preset, used)
    theme = {k: v for k, v in json.loads(json.dumps(settings)).items() if _theme_presets.theme_key(k)}
    if theme == current:
        return False
    _theme_presets.update_preset(name, theme, editing=used)
    return True


def theme_variant_values(settings: dict, type_name: str, variant: str) -> dict:
    """Cles a plat (`button_*`...) d'une variante NOMMEE du preset lie (sa variante par defaut si elle n'existe pas) :
    pour un element de l'appli qui porte cette variante (ex. bouton « Reinitialiser » des reglages : windows_95)."""
    try:
        preset = _theme_presets.load_preset(_theme_presets.find_preset(theme_in_use(settings)))
    except (OSError, ValueError, TypeError):
        return {}
    entry = (preset.get("types") or {}).get(type_name) or {}
    prefix = _theme_presets.TYPE_PREFIXES.get(type_name, "")
    used = _theme_presets.used_variant(entry, variant)
    return {f"{prefix}{f}": v for f, v in _theme_presets.variant_fields(entry, used).items()}


def app_variant(settings: dict, type_name: str) -> str:
    """Variante d'un type que fm_browser utilise (sa surcharge, sinon la variante par defaut du preset lie)."""
    try:
        preset = _theme_presets.load_preset(_theme_presets.find_preset(theme_in_use(settings)))
    except (OSError, ValueError, TypeError):
        return ""
    entry = (preset.get("types") or {}).get(type_name) or {}
    return _theme_presets.used_variant(entry, (settings.get("theme_default_variants") or {}).get(type_name))


def set_app_variant(type_name: str, variant: str) -> dict:
    """fm_browser utilise `variant` pour ce type (enregistre dans le fichier et le preset a l'ecran). Retourne
    les reglages relus (la variante y est deja a plat)."""
    settings = load_settings()
    chosen = dict(settings.get("theme_default_variants") or {})
    chosen[type_name] = variant
    settings["theme_default_variants"] = chosen
    save_settings(settings)
    # Seulement ce choix dans le preset a l'ecran : PAS update_active_preset, qui reecrirait dans la variante
    # nouvellement choisie les valeurs a plat de l'ancienne (encore celles de `settings`).
    presets = _load_presets()
    name = preset_in_use(settings)
    if name:
        layer = _layer(presets, name)
        presets[name] = dict(layer or {}, theme_default_variants=chosen)
        _save_presets(presets)
    return load_settings()


_PRESET_NAMES_CACHE: tuple = (None, [])


def preset_names() -> list[str]:
    """Liste des presets : celle de fm_theme, a l'identique. Relue seulement si un fichier du dossier a change
    (lire tous les presets coute ~30 ms ; le dossier seul, < 1 ms)."""
    global _PRESET_NAMES_CACHE
    folder = _theme_presets.PRESETS_DIR
    try:
        stamp = (str(folder), tuple(sorted((p.name, p.stat().st_mtime_ns) for p in folder.glob("*.json"))))
    except OSError:
        stamp = None
    if stamp is None or stamp != _PRESET_NAMES_CACHE[0]:
        _PRESET_NAMES_CACHE = (stamp, list(_theme_presets.list_presets()))
    return list(_PRESET_NAMES_CACHE[1])


def apply_preset(name: str) -> dict:
    """`name` devient le preset ACTIF : ses valeurs (aspect fm_theme + couche de l'appli) passent dans
    pipeline_settings.json (les autres reglages, et ce qui n'appartient pas aux presets, restent). Retourne les
    reglages."""
    settings = load_settings()
    settings["active_preset"] = _theme_name(name)
    save_settings(settings)
    merged = load_settings()               # fond le preset desormais actif
    save_settings(merged)
    return merged


def save_preset(name: str, values: dict) -> None:
    """« Enregistrer » : la couche de l'appli du preset `name` (fm_theme existant) retient `values` ; l'aspect
    generique va dans le preset fm_theme (`update_theme_preset`). Jamais un preset cree ici."""
    name = _theme_name(name)
    if not name:
        return
    update_theme_preset(dict(values, theme_preset=name))
    presets = _load_presets()
    _layer(presets, name)
    presets[name] = preset_values(dict(values, theme_preset=name))
    _save_presets(presets)


def update_active_preset(settings: dict) -> None:
    """Modifications enregistrees (fenetre de reglages, changement de style a la volee...) : le preset a
    l'ecran les retient aussi, sinon load_settings le rejouerait par-dessus au prochain chargement. L'aspect
    generique va dans le preset fm_theme (`update_theme_preset`)."""
    save_preset(preset_in_use(settings), settings)


def set_default_preset(name: str) -> None:
    settings = load_settings()
    settings["default_preset"] = _theme_name(name)
    save_settings(settings)


def save_settings(settings: dict[str, Any]) -> None:
    try:
        _PER_USER_PATH.parent.mkdir(parents=True, exist_ok=True)
        _PER_USER_PATH.write_text(json.dumps(settings, indent=2, ensure_ascii=False), encoding="utf-8")
    except OSError:
        pass

def save_live_state(key: str, value: Any) -> None:
    """Enregistre UNE cle d'etat temps reel (`_LIVE_STATE_KEYS`) dans le fichier TEL QU'IL EST sur le disque.
    Pas de load_settings() + save_settings() pour cela : load_settings fond le preset actif par-dessus le
    fichier, et reecrire le tout figeait les valeurs (eventuellement perimees) du preset dans le fichier —
    curseurs des reglages revenus a une hauteur que l'utilisateur n'avait pas choisie (signale)."""
    try:
        data = json.loads(_PER_USER_PATH.read_text(encoding="utf-8")) if _PER_USER_PATH.is_file() else {}
    except (OSError, ValueError):
        return                       # fichier illisible : ne surtout pas l'ecraser
    if not isinstance(data, dict):
        return
    data[key] = value
    save_settings(data)

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


# Reglages de l'appli fournis a fm_theme (fm_theme/hooks.py). Passer par le module a chaque appel : un patch
# de settings_store.load_settings (tests) reste vu par fm_theme.
_theme_hooks.HOOKS["default_settings"] = lambda: DEFAULT_SETTINGS
_theme_hooks.HOOKS["load_settings"] = lambda: load_settings()
_theme_hooks.HOOKS["save_settings"] = lambda settings: save_settings(settings)
