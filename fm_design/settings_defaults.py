"""Défauts des réglages du module Design (onglet « Design » de la fenêtre « Réglages : Board », clés
`board_design_*`) : source unique, fusionnés dans DEFAULT_SETTINGS par `settings_store`. Aucun import de l'appli.
Lignes de la fenêtre : `settings.py` ; appliqués par `design_model.apply_settings` (appelé par
`BoardPane.apply_settings`)."""
from typing import Any

DESIGN_DEFAULTS: dict[str, Any] = {
    # Nouveau design (1re page créée quand le document n'en a pas) et fond de TOUTE nouvelle page (un modèle garde
    # le sien). Format : clé de `design_model.PAGE_FORMATS`.
    "board_design_page_format": "square",
    "board_design_page_bg": "#ffffff",
    # Nouveaux éléments : police (« » = celle de l'appli) des textes, tableaux et graphiques, couleur et tailles des
    # textes (titre, sous-titre, corps, en unités du board), remplissage des formes.
    "board_design_font": "",
    "board_design_text_color": "#1a1a1a",
    "board_design_heading_size": 96,
    "board_design_subheading_size": 56,
    "board_design_body_size": 32,
    "board_design_shape_fill": "#8b3dff",
    # Sélection et repères (dessin temporaire, pixels d'ÉCRAN) : couleur de sélection du module (cadres, poignées
    # de rotation exclues, page courante, miniatures), taille des poignées, repères et marges de la page, guides
    # d'alignement du magnétisme (#AARRGGBB : l'opacité compte), titres des pages, règles à l'ouverture.
    "board_design_accent": "#8b3dff",
    "board_design_handle_size": 9,
    "board_design_guide_color": "#c800beff",
    "board_design_snap_color": "#ff2fd0",
    "board_design_page_titles": True,
    "board_design_rulers": False,
    # Flèches du clavier : déplacement de la sélection (unités du board), Maj tenu.
    "board_design_nudge": 1,
    "board_design_nudge_big": 10,
    # Présentation : durée d'une transition de page et d'une animation d'éléments (ms).
    "board_design_transition_ms": 450,
    "board_design_animation_ms": 600,
}
