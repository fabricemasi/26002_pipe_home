"""Réglages du module Photoshop (onglet « Photoshop » de la fenêtre « Réglages : Board ») : lignes
`CATALOG["Photoshop : …"]` et arbre `PS_TREE`. Données seulement (aucun widget) : la fenêtre générique des réglages les
construit. Défauts : `settings_defaults.py`. Appliqués EN DIRECT, au seul contenu concerné (chemin rapide des clés
`board_` -> `BoardPane.apply_settings` -> `look.apply_settings` -> `PhotoshopController.refresh_look`). Les couleurs du
CONTENU (damier, établi, cadre, contour de sélection) sont propres au module : elles se règlent ici. Carte :
docs/agents/fm_photoshop.md."""
from __future__ import annotations

from settings_catalog import CATALOG, Node, Spec

PS_TAB = "Module Photoshop"


def _groups() -> dict:
    bench = [
        Spec("board_ps_checker_a", "Damier de transparence : case claire", "color", "#ffffff",
             {"title": "Damier : case claire"}),
        Spec("board_ps_checker_b", "Damier de transparence : case sombre", "color", "#cccccc",
             {"title": "Damier : case sombre"}),
        Spec("board_ps_checker_size", "Damier : taille d'une case (pixels d'écran)", "slider", 10,
             {"min": 2, "max": 64, "unit": "px"}),
        Spec("board_ps_bench_color", "Fond de l'établi (autour du document)", "color", "#3a3d41",
             {"title": "Fond de l'établi"}),
        Spec("board_ps_frame_color", "Cadre du document", "color", "#000000", {"title": "Cadre du document"}),
        Spec("board_ps_selection_color", "Contour de sélection (fourmis) : trait clair", "color", "#ffffff",
             {"title": "Contour de sélection"}),
    ]
    navigation = [
        Spec("board_ps_zoom_pct", "Zoom : pas par cran de molette", "slider", 15,
             {"min": 2, "max": 100, "unit": "%"}),
        Spec("board_ps_max_zoom_pct", "Zoom maximal", "slider", 3200, {"min": 100, "max": 6400, "unit": "%", "box": 70}),
        Spec("board_ps_cursor_outline", "Curseur de brosse : cercle à la taille réelle", "bool", True),
    ]
    memory = [
        Spec("board_ps_history_mb", "Historique : mémoire maximale des étapes de pixels (Mo)", "slider", 384,
             {"min": 16, "max": 4096, "unit": "Mo", "box": 70}),
    ]
    return {"Photoshop : Établi": bench, "Photoshop : Navigation": navigation, "Photoshop : Mémoire": memory}


CATALOG.update(_groups())

PS_TREE = (
    Node("Établi", "Photoshop : Établi"),
    Node("Navigation", "Photoshop : Navigation"),
    Node("Mémoire", "Photoshop : Mémoire"),
)
