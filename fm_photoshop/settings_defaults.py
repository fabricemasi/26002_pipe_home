"""Défauts des réglages du module Photoshop (clés `board_ps_*`, onglet « Photoshop » de « Réglages : Board »).
Ajoutés à `DEFAULT_SETTINGS` (settings_store.py) : `DEFAULT_SETTINGS.update(PS_DEFAULTS)`."""

PS_DEFAULTS = {
    # Contenu de l'établi (le CONTENU suit son propre habillage, comme le canvas du Board)
    "board_ps_checker_a": "#ffffff",
    "board_ps_checker_b": "#cccccc",
    "board_ps_checker_size": 10,
    "board_ps_bench_color": "#3a3d41",
    "board_ps_frame_color": "#000000",
    "board_ps_selection_color": "#ffffff",
    # Comportement
    "board_ps_zoom_pct": 15,
    "board_ps_max_zoom_pct": 3200,
    "board_ps_cursor_outline": True,
    "board_ps_history_mb": 384,
    # Nouveau document à la taille du presse-papiers : l'image y est collée dans un calque
    "board_ps_new_paste_clipboard": True,
    # Présélections de brosses de l'utilisateur (état temps réel, partagé par tous les boards) : liste de brosses
    "board_ps_brush_presets": [],
}
