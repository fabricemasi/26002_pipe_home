"""Défauts des réglages du board (onglet « MRO ») : source unique, fusionnés dans DEFAULT_SETTINGS par
`settings_store`. Aucun import de l'appli. Les copies des menus contextuels (`board_ctx_menu…`, `board_ovr_…`) sont
faites par settings_store depuis les menus de l'appli. Lignes de la fenêtre : `settings.py`."""
from typing import Any

BOARD_DEFAULTS: dict[str, Any] = {
    # Module « Board » (board/, .mro) : magnetisme GENERAL (Reglages > Module MRO ; Alt tenu = sans). Seuil en pixels
    # d'ecran (meme effet a tout zoom). Les reglages propres a un board (couleur du canvas...) sont dans le .mro.
    # Double-clic sur un dessin DXF / DWG dans une colonne : ouvert dans le module MRO (lu, jamais reecrit).
    "board_open_cad_drawings": True,
    "board_snap_enabled": True,
    "board_snap_objects": True,
    "board_snap_grid": False,
    "board_snap_guides": True,
    "board_snap_resize": True,
    "board_snap_distance": 6,
    # Presets des outils de dessin du board (etat temps reel) : {outil: [{color, width, opacity?} x 3]}.
    "board_pen_presets": {},
    # Module Design : kit de marque PARTAGÉ entre tous les boards (état temps réel) : couleurs et polices favorites.
    "board_design_brand": {"colors": [], "fonts": [], "logos": []},
    # Grille unique du board et du CAD (Reglages > Module MRO > Grille) : pas en centiemes, intensite en dixiemes de %
    "board_grid_step": 400, "board_grid_unit": "board", "board_grid_factor": 4, "board_grid_fade_start": 12,
    "board_grid_fade_full": 60, "board_grid_style": "lines", "board_grid_thickness": 1, "board_grid_auto_color": True,
    "board_grid_intensity": 66, "board_grid_color": "#11000000", "board_grid_levels": 12, "board_grid_dot_size": 2,
    "board_grid_origin_x": 0, "board_grid_origin_y": 0, "board_grid_axes": False, "board_grid_axes_color": "#66ff2f2f",
    "board_grid_axes_thickness": 1,
    "board_zoom_speed": 15, "board_zoom_fine": 3,           # zoom du board : % par cran de molette (Maj = fin)
    # Module « Board » (board/) — Reglages > Module MRO > Barres d'outils : apparence d'origine par defaut (palette des
    # panneaux des reglages : fond #16181a, filet #2a2e32 d'un pixel, angles droits ; texte #d6d9dc).
    "board_toolbar_bg_color": "#16181a",
    "board_toolbar_border_enabled": {s: True for s in ("top", "right", "bottom", "left")},
    "board_toolbar_border": {s: "#2a2e32" for s in ("top", "right", "bottom", "left")},
    "board_toolbar_border_thickness": 1, "board_toolbar_border_enabled_linked": True,
    "board_toolbar_corner_radius": {"top_left": 0, "top_right": 0, "bottom_right": 0, "bottom_left": 0},
    "board_toolbar_corner_radius_linked": True,
    "board_toolbar_padding": {s: 6 for s in ("top", "right", "bottom", "left")},
    "board_toolbar_padding_linked": True,
    "board_toolbar_shadow_enabled": {s: False for s in ("top", "right", "bottom", "left")},
    "board_toolbar_shadow": {s: "#8c000000" for s in ("top", "right", "bottom", "left")},
    "board_toolbar_shadow_size": 10, "board_toolbar_shadow_enabled_linked": True,
    "board_toolbar_text_font_family": "", "board_toolbar_text_font_size": 12, "board_toolbar_text_font_bold": False,
    "board_toolbar_text_font_italic": False, "board_toolbar_text_font_color": "#d6d9dc",
    "board_toolbar_text_font_smoothing_enabled": False, "board_toolbar_text_font_smoothing": "current",
    "board_toolbar_invert": False,                 # icones et textes des barres en negatif
    "board_toolbar_focus_width": 26, "board_toolbar_focus_color": "#6e3f6f9f",
    "board_toolbar_focus_radius": 6, "board_toolbar_hover_color": "#232729",
    "board_toolbar_hover_radius": 6,
}
