"""Réglages d'interface réassignés à l'exécution par apply_all_settings (lus partout via ui_state.X)."""

from config import STEP_BADGE_MARGIN, STEP_BADGE_SIZE

HEADER_HEIGHT = 26

HEADER_PADDING = 0    # inset (4 cotes) entre le fond colore de l'entete et les bords de la colonne/inspecteur (voir Column/DetailPanel)

# Largeur de depart de l'Inspecteur (voir DetailPanel.__init__) — mutable
# par apply_all_settings (cle "detail_panel_width") : auto-enregistree sans
# punaise, comme Type/Focus, voir DetailPanel.mouseReleaseEvent — la
# colonne Inspecteur n'a pas de bouton punaise ni d'onglet de surcharge
# PAR TITRE dedie, une simple cle GENERALE suffit (une seule instance dans
# toute l'appli, contrairement a Type/Focus qui partagent un bucket de
# style avec d'autres colonnes du meme genre).
DETAIL_PANEL_WIDTH = 300

# Rayon de bordure de la fenetre principale (Parametres > General). Voir
# PipelineBrowser.__init__ (WA_TranslucentBackground) pour le mecanisme.
WINDOW_RADIUS = 0

# Rayon de bordure applique a TOUS les boutons (Parametres > Boutons) : voir
# app_style.set_button_radius / build_stylesheet.
BUTTON_RADIUS = 0

# Padding (dict, 4 cotes INDEPENDANTS) et rayon (dict, 4 coins
# INDEPENDANTS) appliques a la grande vignette carree de l'apercu empile
# (voir _SquarePreviewImage) — distinct du padding par colonne ci-dessus,
# qui lui ne concerne que les vignettes DANS les lignes des colonnes
# Projets/Sous-projet/Logiciels/Contenu.
PREVIEW_IMAGE_PAD: dict = {}

PREVIEW_IMAGE_RADIUS: dict = {}

# Style EFFECTIF du cadre de redimensionnement (voir _show_resize_width/
# _resize_width_indicator, General > Colonnes > "Cadre de redimensionnement"
# des reglages) — repeuple entierement par apply_all_settings, jamais lu
# ailleurs qu'a l'affichage du badge (pas un chemin chaud) — voir la
# remarque de l'utilisateur, "je veux que dans general/colonnes/ tu crees
# une sous section cadre de redimensionnement". Valeurs par defaut ICI =
# comportement D'AVANT ce reglage (coin bas-droit, police mono de l'appli,
# fond/bordure C['chrome']/C['border'] fige, 1px, 4px de rayon) — utilisees
# tant qu'apply_all_settings n'a pas encore tourne (tout debut du
# demarrage).
RESIZE_BADGE_STYLE: dict = {
    "position": "bottom_right",
    "offset_x": 8,
    "offset_y": 8,
    "font_family": "",
    "text_color": "#d6d9dc",
    "bg_color": "#202326",
    "border_enabled": {"top": True, "right": True, "bottom": True, "left": True},
    "border": {"top": "@border2", "right": "@border2", "bottom": "@border2", "left": "@border2"},
    "border_thickness": 1,
    "border_radius": {"top_left": 4, "top_right": 4, "bottom_right": 4, "bottom_left": 4},
}

STEP_BADGE_STYLE: dict = {
    "width": STEP_BADGE_SIZE, "height": STEP_BADGE_SIZE,
    "border_enabled": {"top": False, "right": False, "bottom": False, "left": False},
    "border": {}, "border_thickness": 1,
    "radius": {"top_left": 9, "top_right": 9, "bottom_right": 9, "bottom_left": 9},
    "colors": {2: "#5c6368", 3: "#5c6368", 4: "#3f6f9f", 5: "#3f6f9f", 6: "#d9822b", "N": "#5c6368"},
    "text_colors": {2: "#eef2f5", 3: "#eef2f5", 4: "#eef2f5", 5: "#eef2f5", 6: "#eef2f5", "N": "#eef2f5"},
    "offset_x": STEP_BADGE_MARGIN, "offset_y": 0,
    "font_family": "", "font_bold": True, "border_smoothing": True,
    "font_smoothing_enabled": False, "font_smoothing": "current",
}

# Police/couleur des lignes "raccourci" (voir ROLE_IS_SHORTCUT, Settings >
# RACCOURCI) — DISTINCTES du reste du texte de la ligne, pour reperer un
# raccourci au premier coup d'oeil, meme rendu partage (_paint_unified_row)
# que le reste : voir la remarque de l'utilisateur, "police : choix de la
# police avec toggle : app ou systeme, toggle gras ou regulier, couleur,
# taille".
SHORTCUT_TEXT_STYLE: dict = {
    "font_family": "", "font_bold": False, "color": "#8fb4d5", "font_size": 11,
}

# Bouton de repliement de colonne (voir Column.set_collapsed/toggle_btn) :
# "chevrons" (defaut, comportement inchange, voir IconButton kind
# dchevron_left/right) ou "icone" (voir UI_ICON_COLLAPSE_TOGGLE, Settings >
# ICONES > General) — reglage Settings > Colonnes > Focus > Bouton
# repliement > "Icone".
COLLAPSE_TOGGLE_MODE = "chevrons"
