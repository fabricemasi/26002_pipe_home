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
    "board_ps_zoom_step": 1.15,
    "board_ps_max_zoom": 32.0,
    "board_ps_cursor_outline": True,
    "board_ps_history_mb": 384,
}
