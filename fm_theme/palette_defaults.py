"""Défauts des réglages des barres d'outils flottantes (`palette_*`, type « palette » de fm_theme) : sans Qt, pour
que `settings_store` les déclare dans DEFAULT_SETTINGS sans charger les widgets. Voir fm_theme/palette.py."""

PREFIX = "palette_"
SIDES = ("top", "right", "bottom", "left")
TRANSPARENT = "#00000000"          # couleur transparente = la couleur habituelle du thème (jeton `M`)
CONTROL_MIN_WIDTH, CONTROL_MAX_WIDTH = 120, 520      # largeur réglable d'un contrôle (spec § 8)
TITLE_ALIGNS = (("left", "Gauche"), ("center", "Milieu"), ("right", "Droite"))
SLIDER_STYLES = (("app", "Celui des réglages (Sliders)"), ("palette", "Propre aux barres"))
TOGGLE_STYLES = (("toggle1", "Toggle 1"), ("toggle2", "Toggle 2"))

# Défauts des réglages (déclarés aussi dans DEFAULT_SETTINGS par settings_store : « toute nouvelle clé y est »).
# Les couleurs à TRANSPARENT suivent les jetons du thème (`palette._color`), les autres sont des teintes d'accent.
# Valeurs = celles du prototype validé (docs/agents/prototype_barres_outils.html, spec docs/agents/barres_outils_spec.md).
PALETTE_DEFAULTS: dict = {
    # Grille : case = icône 34 × 34, écart 4, marges égales 6 (gauche, droite, bas), bande du titre
    "palette_cell_size": 34, "palette_cell_gap": 4, "palette_margin": 6, "palette_header_height": 19,
    "palette_snap_distance": 24,
    # Cadre
    "palette_bg_color": TRANSPARENT,
    "palette_border_enabled": {s: True for s in SIDES}, "palette_border": {s: TRANSPARENT for s in SIDES},
    "palette_border_thickness": 1, "palette_corner_radius": 8,
    "palette_shadow_enabled": {s: True for s in SIDES}, "palette_shadow": {s: "#59000000" for s in SIDES},
    "palette_shadow_size": 14,
    "palette_drag_border_color": TRANSPARENT,
    # « lier les 4 » des lignes Bordures / Border radius / Ombres (Palette : Barre, Icones, Controleur) : sans clé
    # déclarée, load_settings l'ignorait et le toggle ne s'enregistrait pas (tests.test_navigation_bar, 2026-11-12)
    "palette_border_enabled_linked": True, "palette_corner_radius_linked": True,
    "palette_shadow_enabled_linked": True, "palette_cell_border_enabled_linked": True,
    "palette_bar_border_enabled_linked": True,
    # Barre clipsée (demande de l'utilisateur, 2026-11-03) : pas de bordure du côté collé ; en-tête / fond de la
    # couleur de l'élément contre lequel elle est collée
    # « Clipsée : comportement du côté collé » (2026-11-08, remplace le toggle `palette_snap_border_off`) : « none »
    # (rien), « no_border » (pas de bordure, ni sur la barre ni sur l'élément voisin le long de la barre), « color »
    # (une bordure de la couleur `palette_snap_side_color`) ; séparateur entre barres collées l'une à l'autre
    "palette_snap_side": "none", "palette_snap_side_color": TRANSPARENT, "palette_snap_separator": False,
    "palette_snap_header_color": False, "palette_snap_bg_color": False,
    "palette_snap_border_match": False,    # clipsée contre un élément à bordure : bordure de SA couleur (côté collé exclu)
    # En-tête : titre (police), poignée de déplacement
    "palette_title_font_family": "", "palette_title_font_size": 10, "palette_title_font_bold": True,
    "palette_title_font_italic": False, "palette_title_font_smoothing_enabled": False,
    "palette_title_font_smoothing": "current", "palette_title_font_color": TRANSPARENT,
    "palette_title_caps": True, "palette_title_tracking": 8, "palette_title_align": "left",
    "palette_header_shown": True,          # en-têtes affichés (aussi : clic droit sur une barre) ; sans : la tranche
    "palette_header_bg_color": TRANSPARENT,
    "palette_grip_enabled": True, "palette_grip_color": TRANSPARENT,
    # Icônes
    "palette_cell_radius": 6, "palette_icon_ratio": 59, "palette_icon_color": TRANSPARENT,
    "palette_cell_bg_color": TRANSPARENT,
    "palette_cell_border_enabled": {s: False for s in SIDES}, "palette_cell_border": {s: TRANSPARENT for s in SIDES},
    "palette_cell_border_thickness": 1,
    "palette_cell_hover_color": TRANSPARENT, "palette_cell_active_color": "#333f6f9f",
    "palette_cell_active_border_color": "#3f6f9f", "palette_cell_active_border_thickness": 1,
    "palette_drop_color": "#3f6f9f",
    "palette_separator_color": TRANSPARENT, "palette_slide_ms": 120,
    # Contrôles (slider, saisie, menu)
    "palette_bar_bg_color": TRANSPARENT,
    "palette_bar_border_enabled": {s: True for s in SIDES}, "palette_bar_border": {s: TRANSPARENT for s in SIDES},
    "palette_bar_border_thickness": 1, "palette_bar_radius": 6, "palette_bar_padding": 8,
    "palette_bar_font_family": "", "palette_bar_font_size": 11,
    "palette_bar_font_bold": False, "palette_bar_font_italic": False, "palette_bar_font_smoothing_enabled": False,
    "palette_bar_font_smoothing": "current", "palette_bar_font_color": TRANSPARENT,
    "palette_bar_value_color": TRANSPARENT, "palette_bar_grip_enabled": True, "palette_bar_grip_color": TRANSPARENT,
    "palette_bar_handle_enabled": True, "palette_bar_handle_color": TRANSPARENT,
    "palette_bar_join_gap": 1,
    # Contrôleur slider
    "palette_slider_style": "app", "palette_slider_track_height": 3, "palette_slider_thumb_width": 3,
    "palette_slider_thumb_height": 14, "palette_slider_radius": 0, "palette_slider_track_color": TRANSPARENT,
    "palette_slider_fill_color": "#3f6f9f", "palette_slider_thumb_color": "#8fb4d5", "palette_slider_value_width": 36,
    # Contrôleur liste déroulante
    "palette_select_min_width": 50, "palette_select_height": 24,
    # Contrôleur zone de saisie
    "palette_input_min_width": 40, "palette_input_height": 24,
    # Contrôleur toggle
    "palette_toggle_style": "toggle1", "palette_toggle_labels": False,
}
