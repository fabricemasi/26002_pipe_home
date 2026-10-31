"""Défauts des réglages du module typographique (clés `typo_*`) : source unique, fusionnés dans DEFAULT_SETTINGS
par `settings_store`. Aucun import de l'appli. Lus par `canvas.GlyphCanvas.apply_settings`, `glyph_grid`,
`preview`, `pane`."""
from typing import Any

TYPO_DEFAULTS: dict[str, Any] = {
    # Nouveau projet : unités par em et métriques verticales proposées.
    "typo_new_upm": 1000,
    "typo_new_ascender": 800,
    "typo_new_descender": -200,
    "typo_new_cap_height": 700,
    "typo_new_x_height": 500,
    # Canvas : couleurs du dessin (fond clair d'un éditeur de glyphes par défaut).
    "typo_canvas_bg": "#f4f4f2",
    "typo_fill": "#1b1b1b",
    "typo_outline": "#2b2b2b",
    "typo_node": "#2f6fd6",
    "typo_node_smooth": "#1f9d55",
    "typo_handle": "#8a8f98",
    "typo_selection": "#e2572b",
    "typo_metrics": "#9bb7d4",
    "typo_grid": "#e2e2de",
    "typo_component": "#7a5cc4",
    "typo_anchor": "#c9348f",
    "typo_compare": "#d08a2e",
    # Taille des nœuds (px) ; grille (unités) ; magnétisme (px) ; arrondir les coordonnées à l'unité.
    "typo_node_size": 7,
    "typo_grid_step": 10,
    "typo_show_grid": True,
    "typo_show_rulers": True,
    "typo_snap_distance": 6,
    "typo_snap_integer": True,
    # Affichage du glyphe : « fill » (rempli), « outline » (contour), « both » (rempli + nœuds).
    "typo_display": "both",
    # Tolérances, en DIXIÈMES (curseur entier, affiché avec une décimale) : conversion cubique -> quadratique
    # (10 = 1,0 unité), précision du crayon (30 = 3,0 px à l'écran).
    "typo_quadratic_tolerance": 10,
    "typo_pencil_error": 30,
    "typo_pencil_smoothing": 2,
    # Rayon des coins arrondis (menu Tracés > Arrondir les coins), en unités.
    "typo_corner_radius": 40,
    "typo_nib_width": 80,
    "typo_nib_angle": 30,
    "typo_brush_width": 60,
    "typo_use_pressure": True,
    # Grille des glyphes : taille des cases (px).
    "typo_cell_size": 72,
    # Aperçu : taille du texte (px) et texte par défaut.
    "typo_preview_size": 72,
    "typo_preview_text": "Portez ce vieux whisky au juge blond qui fume",
    # Sauvegarde de SECOURS du travail non enregistré (proposée à la réouverture après un plantage) : toutes les N
    # secondes, 0 = jamais. Hors du projet (%LOCALAPPDATA%/fm_font/secours).
    "typo_autosave_seconds": 60,
    # Molette du canvas : zoom (vrai) ; sinon défilement, zoom avec Ctrl.
    "typo_wheel_zoom": True,
}
