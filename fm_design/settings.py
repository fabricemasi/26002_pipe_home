"""Réglages du module Design (onglet « Design » de la fenêtre « Réglages : Board ») : lignes `CATALOG["Design : …"]`
et arbre `DESIGN_TREE`. Données seulement (aucun widget) : la fenêtre générique des réglages les construit. Défauts :
`settings_defaults.py`. Appliqués EN DIRECT (chemin rapide des clés `board_` de `PipelineBrowser._apply_settings`
-> `BoardPane.apply_settings` -> `design_model.apply_settings`). Carte : docs/agents/fm_design.md."""
from __future__ import annotations

from settings_catalog import CATALOG, Node, Spec

DESIGN_TAB = "Module Design"


def _design_groups() -> dict:
    from fm_design.design_model import PAGE_FORMATS
    formats = tuple((key, label) for key, label, _w, _h in PAGE_FORMATS)
    new_design = [
        Spec("board_design_page_format", "Format du premier design (document sans page)", "choice", "square",
             {"choices": formats, "width": 260}),
        Spec("board_design_page_bg", "Fond des nouvelles pages (un modèle garde le sien)", "color", "#ffffff",
             {"title": "Fond des nouvelles pages"}),
    ]
    elements = [
        Spec("board_design_font", "Police des textes, tableaux et graphiques", "font_select", "",
             {"auto_label": "Police de l'appli"}),
        Spec("board_design_text_color", "Couleur des textes", "color", "#1a1a1a", {"title": "Couleur des textes"}),
        Spec("board_design_heading_size", "Taille d'un titre", "slider", 96, {"min": 8, "max": 400, "unit": ""}),
        Spec("board_design_subheading_size", "Taille d'un sous-titre", "slider", 56, {"min": 8, "max": 400, "unit": ""}),
        Spec("board_design_body_size", "Taille d'un texte", "slider", 32, {"min": 6, "max": 400, "unit": ""}),
        Spec("board_design_shape_fill", "Remplissage des formes", "color", "#8b3dff",
             {"title": "Remplissage des formes"}),
    ]
    selection = [
        Spec("board_design_accent", "Couleur de sélection (cadres, page courante, miniatures)", "color", "#8b3dff",
             {"title": "Sélection du module Design"}),
        Spec("board_design_handle_size", "Taille des poignées (pixels d'écran)", "slider", 9, {"min": 5, "max": 20}),
        Spec("board_design_guide_color", "Couleur des repères et des marges (son opacité compte)", "color",
             "#c800beff", {"title": "Repères et marges"}),
        Spec("board_design_snap_color", "Couleur des guides d'alignement (magnétisme)", "color", "#ff2fd0",
             {"title": "Guides d'alignement"}),
        Spec("board_design_page_titles", "Titres des pages au-dessus de chaque page", "bool", True),
        Spec("board_design_rulers", "Règles affichées à l'ouverture du module (Maj+R)", "bool", False),
    ]
    keyboard = [
        Spec("board_design_nudge", "Flèches : déplacement de la sélection", "slider", 1, {"min": 1, "max": 100, "unit": ""}),
        Spec("board_design_nudge_big", "Flèches avec Maj tenu", "slider", 10, {"min": 1, "max": 500, "unit": ""}),
    ]
    present = [
        Spec("board_design_transition_ms", "Durée d'une transition de page", "slider", 450,
             {"min": 100, "max": 3000, "unit": "ms", "box": 68}),
        Spec("board_design_animation_ms", "Durée d'une animation d'éléments", "slider", 600,
             {"min": 100, "max": 3000, "unit": "ms", "box": 68}),
    ]
    return {"Design : Nouveau design": new_design, "Design : Nouveaux éléments": elements,
            "Design : Sélection et repères": selection, "Design : Clavier": keyboard,
            "Design : Présentation": present}


CATALOG.update(_design_groups())

# Onglet « Module Design » (voir CATALOG["Design : …"] ; ses icônes restent dans Module MRO > Icônes).
DESIGN_TREE = (
    Node("Nouveau design", "Design : Nouveau design"),
    Node("Nouveaux éléments", "Design : Nouveaux éléments"),
    Node("Sélection et repères", "Design : Sélection et repères"),
    Node("Clavier", "Design : Clavier"),
    Node("Présentation", "Design : Présentation"),
)
