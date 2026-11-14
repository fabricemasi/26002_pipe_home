"""Défauts des réglages du board (onglet « MRO ») : source unique, fusionnés dans DEFAULT_SETTINGS par
`settings_store`. Aucun import de l'appli. Les copies des menus contextuels (`board_ctx_menu…`, `board_ovr_…`) sont
faites par settings_store depuis les menus de l'appli. Lignes de la fenêtre : `settings.py`."""
from typing import Any

BOARD_DEFAULTS: dict[str, Any] = {
    # Module « Board » (board/, .mro) : magnetisme GENERAL (Reglages > Module MRO ; Alt tenu = sans). Seuil en pixels
    # d'ecran (meme effet a tout zoom). Les reglages propres a un board (couleur du canvas...) sont dans le .mro.
    # Double-clic sur un dessin DXF / DWG dans une colonne : ouvert dans le module MRO (lu, jamais reecrit).
    "board_open_cad_drawings": True,
    "board_cad_import_blocks": True,           # import DXF / DWG : insertions gardees en references de blocs (fm_cad)
    "board_snap_enabled": True,
    "board_snap_objects": True,
    "board_snap_grid": False,
    "board_snap_guides": True,
    "board_snap_resize": True,
    "board_snap_distance": 6,
    # Guides d'alignement par sorte d'aimantation (Reglages > Module MRO > Magnetisme, une ligne par sorte ;
    # fm_board/snap_guides.py) : bords des documents / objets internes aux documents ; guides affiches (sous le
    # maitre board_snap_guides) ; type de ligne = cle d'un type du module CAD ; echelle du motif (en pixels
    # d'ecran) en dixiemes (20 = 2,0).
    "board_snap_doc_guides": True,
    "board_snap_doc_color": "#ff2fd0",
    "board_snap_doc_linetype": "continuous",
    "board_snap_doc_ltscale": 20,
    "board_snap_inner_guides": True,
    "board_snap_inner_color": "#ff2fd0",
    "board_snap_inner_linetype": "dashed",
    "board_snap_inner_ltscale": 20,
    "board_snap_frame_guides": True,          # cadre d'un élément sur son document (PDF : bas d'une page)
    "board_snap_frame_color": "#ff2fd0",
    "board_snap_frame_linetype": "dashdot",
    "board_snap_frame_ltscale": 20,
    # Presets des outils de dessin du board (etat temps reel) : {outil: [{color, width, opacity?} x 3]}.
    "board_pen_presets": {},
    # Barre des modules du board repliee (etat temps reel : bouton du haut de la barre ou languette).
    "board_modulebar_folded": False,
    "board_bars": {},                      # barres flottantes : {module: etat} (fm_board/bars.py, etat temps reel)
    # Barre de selection des modules (Reglages : Board > Board > Barre de selection, fm_board/modulebar.py) :
    # defauts = la maquette « Barre des modules » de l'utilisateur (2026-10-31).
    "board_modules_fade_opacity": 30,              # % : opacite des elements d'un module grise
    "board_modules_fade_saturation": 100,          # % : saturation des elements d'un module grise (0 = gris)
    "board_modulebar_buttons": True, "board_modulebar_reset": True, "board_modulebar_alt_solo": True,
    "board_modulebar_pill": True,
    "board_modulebar_long_press_ms": 500,          # appui long sur l'icone d'un module : ses boutons se deploient
    "board_modulebar_fold_style": "narrow",        # repliee : « narrow » = etroite, icones seules ; « tab » = languette
    "board_modulebar_bg_color": "#16181a", "board_modulebar_border_color": "#2a2e32",
    "board_modulebar_icon_size": 36, "board_modulebar_button_size": 24, "board_modulebar_spacing": 4,
    "board_modulebar_padding": 6, "board_modulebar_row_radius": 8, "board_modulebar_row_color": "#22242a",
    "board_modulebar_active_alpha": 18, "board_modulebar_active_border": 1, "board_modulebar_hover_color": "#232729",
    "board_modulebar_ink_color": "#d7d9de", "board_modulebar_dim_color": "#8b8e96",
    "board_modulebar_off_color": "#5a5d64", "board_modulebar_fade_color": "#9a9ca3",
    "board_modulebar_solo_color": "#f3c46b", "board_modulebar_tool_color": "#a4a6ad",
    "board_modulebar_tool_hover_alpha": 20,        # % : survol des boutons replier / tout reinitialiser
    "board_modulebar_tab_width": 14, "board_modulebar_tab_height": 56, "board_modulebar_tab_color": "#16181a",
    "board_modulebar_tab_ink": "#a4a6ad", "board_modulebar_pill_color": "#2a2418",
    "board_modulebar_pill_font_size": 13,
    # Couleur DOMINANTE de chaque module (icone, trait, fond du module actif dans la barre de selection).
    "board_modulebar_color_miro": "#f2c94c", "board_modulebar_color_cad": "#6fa8ff",
    "board_modulebar_color_design": "#4fd1c5", "board_modulebar_color_tableur": "#7bd88f",
    "board_modulebar_color_illustrator": "#f08bb4", "board_modulebar_color_photoshop": "#5aa9e6",
    "board_modulebar_color_pdf": "#e0604f",
    # Espace autour de l'icone de chaque module dans la barre de selection (px a la taille 36 ; suit la taille), regle
    # sur la ligne de son icone (Barre de selection > Icones, colonne Marge ; demande du 2026-11-13).
    **{f"board_modulebar_icon_pad_{m}": 3 for m in ("miro", "cad", "design", "tableur", "illustrator", "photoshop",
                                                       "pdf")},
    # Toggle de la meme ligne : icone teintee de la couleur du module (sinon ses propres couleurs).
    **{f"board_modulebar_icon_tint_{m}": False for m in ("miro", "cad", "design", "tableur", "illustrator",
                                                           "photoshop", "pdf")},
    # Module Design : kit de marque PARTAGÉ entre tous les boards (état temps réel) : couleurs et polices favorites.
    "board_design_brand": {"colors": [], "fonts": [], "logos": [], "styles": []},
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
