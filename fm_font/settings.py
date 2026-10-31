"""Réglages du module typographique (fenêtre « Réglages : Typographie ») : lignes `CATALOG["Typographie : …"]` et
arbre `TYPO_TREE`. Données seulement (aucun widget) : la fenêtre générique des réglages les construit. Défauts :
`settings_defaults.py`. Appliqués EN DIRECT au module ouvert (chemin rapide des clés `typo_` de
`PipelineBrowser._apply_settings` -> `FontPane.apply_settings`)."""
from __future__ import annotations

from settings_catalog import CATALOG, Node, Spec

TYPO_TAB = "Module Typographie"

CATALOG["Typographie : Ouverture"] = [
    Spec("typo_open_double_click", "Double-clic sur une source (.ufo, .designspace) ou une police (.ttf, .otf, "
                                   ".woff) : module typographique", "bool", True),
]
CATALOG["Typographie : Secours"] = [
    Spec("typo_autosave_seconds", "Sauvegarde de secours du travail non enregistré (0 = jamais)", "slider", 60,
         {"min": 0, "max": 900, "unit": "s"}),
]
CATALOG["Typographie : Nouveaux projets"] = [
    Spec("typo_new_upm", "Unités par em", "slider", 1000, {"min": 16, "max": 4096, "unit": "u"}),
    Spec("typo_new_ascender", "Ascendante", "slider", 800, {"min": 0, "max": 4096, "unit": "u"}),
    Spec("typo_new_descender", "Descendante", "slider", -200, {"min": -2048, "max": 0, "unit": "u"}),
    Spec("typo_new_cap_height", "Hauteur de capitale", "slider", 700, {"min": 0, "max": 4096, "unit": "u"}),
    Spec("typo_new_x_height", "Hauteur d'x", "slider", 500, {"min": 0, "max": 4096, "unit": "u"}),
]
CATALOG["Typographie : Éditeur"] = [
    Spec("typo_display", "Affichage du glyphe", "choice", "both",
         {"choices": (("both", "Rempli + nœuds"), ("outline", "Contour"), ("fill", "Rempli")), "width": 170}),
    Spec("typo_node_size", "Taille des nœuds", "slider", 7, {"min": 3, "max": 16, "unit": "px"}),
    Spec("typo_show_grid", "Grille", "bool", True),
    Spec("typo_grid_step", "Pas de la grille", "slider", 10, {"min": 1, "max": 200, "unit": "u"}),
    Spec("typo_show_rulers", "Règles", "bool", True),
    Spec("typo_snap_distance", "Magnétisme (métriques, nœuds)", "slider", 6, {"min": 0, "max": 30, "unit": "px"}),
    Spec("typo_snap_integer", "Coordonnées arrondies à l'unité", "bool", True),
    Spec("typo_wheel_zoom", "Molette = zoom (sinon défilement, zoom avec Ctrl)", "bool", True),
]
CATALOG["Typographie : Tracé"] = [
    Spec("typo_quadratic_tolerance", "Tolérance cubique -> quadratique", "slider", 10,
         {"min": 1, "max": 100, "scale": 10, "unit": "u"}),
    Spec("typo_pencil_error", "Crayon : précision de l'ajustement", "slider", 30,
         {"min": 5, "max": 200, "scale": 10, "unit": "px"}),
    Spec("typo_pencil_smoothing", "Lissage du tracé libre", "slider", 2, {"min": 0, "max": 8}),
    Spec("typo_corner_radius", "Rayon des coins arrondis", "slider", 40, {"min": 1, "max": 500, "unit": "u"}),
    Spec("typo_nib_width", "Plume : largeur du bec", "slider", 80, {"min": 2, "max": 600, "unit": "u"}),
    Spec("typo_nib_angle", "Plume : angle du bec", "slider", 30, {"min": -90, "max": 90, "unit": "°"}),
    Spec("typo_brush_width", "Brosse : largeur", "slider", 60, {"min": 2, "max": 600, "unit": "u"}),
    Spec("typo_use_pressure", "Pression de la tablette", "bool", True),
]
CATALOG["Typographie : Grille et aperçu"] = [
    Spec("typo_cell_size", "Taille des cases de la grille", "slider", 72, {"min": 32, "max": 256, "unit": "px"}),
    Spec("typo_preview_size", "Taille du texte de l'aperçu", "slider", 72, {"min": 8, "max": 400, "unit": "px"}),
]
CATALOG["Typographie : Couleurs"] = [
    Spec(f"typo_{key}", label, "color", default, {"title": label}) for key, label, default in (
        ("canvas_bg", "Fond du canvas", "#f4f4f2"), ("fill", "Remplissage", "#1b1b1b"),
        ("outline", "Contour", "#2b2b2b"), ("node", "Nœuds (coin)", "#2f6fd6"),
        ("node_smooth", "Nœuds lisses", "#1f9d55"), ("handle", "Poignées", "#8a8f98"),
        ("selection", "Sélection", "#e2572b"), ("metrics", "Lignes de métriques", "#9bb7d4"),
        ("grid", "Grille", "#e2e2de"), ("component", "Composants", "#7a5cc4"), ("anchor", "Ancres", "#c9348f"),
        ("compare", "Master comparé", "#d08a2e"))
]

TYPO_TREE = (
    Node("Ouverture", "Typographie : Ouverture"),
    Node("Secours", "Typographie : Secours"),
    Node("Nouveaux projets", "Typographie : Nouveaux projets"),
    Node("Éditeur", "Typographie : Éditeur"),
    Node("Tracé", "Typographie : Tracé"),
    Node("Grille et aperçu", "Typographie : Grille et aperçu"),
    Node("Couleurs", "Typographie : Couleurs"),
)
