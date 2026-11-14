"""Réglages du module Illustrator (onglet « Illustrator » de la fenêtre « Réglages : Board ») : lignes
`CATALOG["Illustrator : …"]` et arbre `ILL_TREE`. Données seulement (aucun widget) : la fenêtre générique des
réglages les construit. Défauts : `settings_defaults.py`. Appliqués EN DIRECT (chemin rapide des clés `board_` ->
`BoardPane.apply_settings` -> `look.apply_settings`). Carte : docs/agents/fm_illustrator.md."""
from __future__ import annotations

from settings_catalog import CATALOG, Node, Spec

ILL_TAB = "Module Illustrator"


def _groups() -> dict:
    from fm_illustrator.model import ARTBOARD_FORMATS
    formats = tuple((name, name) for name, _w, _h in ARTBOARD_FORMATS)
    selection = [
        Spec("board_ill_accent", "Couleur de sélection (contours, points, boîte, plan choisi)", "color", "#2f7cf6",
             {"title": "Sélection du module Illustrator"}),
        Spec("board_ill_handle_size", "Taille des poignées de la boîte (pixels d'écran)", "slider", 9,
             {"min": 5, "max": 20}),
        Spec("board_ill_anchor_size", "Taille des points d'ancrage (pixels d'écran)", "slider", 5, {"min": 3, "max": 12}),
        Spec("board_ill_smart_guides", "Repères commentés actifs à l'ouverture (Ctrl+U)", "bool", True),
        Spec("board_ill_snap_px", "Distance d'aimantation (pixels d'écran)", "slider", 6, {"min": 2, "max": 20}),
    ]
    new_objects = [
        Spec("board_ill_artboard_format", "Format d'un nouveau plan de travail", "choice", "A4",
             {"choices": formats, "width": 220}),
        Spec("board_ill_font", "Police des nouveaux textes", "font_select", "", {"auto_label": "Police de l'appli"}),
        Spec("board_ill_text_size", "Corps des nouveaux textes (pt)", "slider", 12, {"min": 4, "max": 200, "unit": ""}),
        Spec("board_ill_units", "Unité affichée (épaisseur, corps)", "choice", "pt",
             {"choices": (("pt", "Points"), ("mm", "Millimètres"), ("px", "Pixels")), "width": 160}),
    ]
    keyboard = [
        Spec("board_ill_nudge", "Flèches : déplacement de la sélection", "slider", 1, {"min": 1, "max": 100, "unit": ""}),
        Spec("board_ill_nudge_big", "Flèches avec Maj tenu", "slider", 10, {"min": 1, "max": 500, "unit": ""}),
        Spec("board_ill_pencil_fidelity", "Crayon et pinceau : fidélité (dixièmes de pixel)", "slider", 25,
             {"min": 5, "max": 100, "unit": ""}),
        Spec("board_ill_trace_detail", "Vectorisation : détail par défaut (px)", "slider", 1000,
             {"min": 100, "max": 1500, "unit": "px", "box": 68}),
    ]
    export = [
        Spec("board_ill_pdf_dpi", "PDF : résolution des effets et masques d'opacité", "slider", 300,
             {"min": 72, "max": 1200, "unit": "dpi", "box": 68}),
    ]
    return {"Illustrator : Sélection et repères": selection, "Illustrator : Nouveaux objets": new_objects,
            "Illustrator : Clavier et outils": keyboard, "Illustrator : Export": export}


CATALOG.update(_groups())

ILL_TREE = (
    Node("Sélection et repères", "Illustrator : Sélection et repères"),
    Node("Nouveaux objets", "Illustrator : Nouveaux objets"),
    Node("Clavier et outils", "Illustrator : Clavier et outils"),
    Node("Export", "Illustrator : Export"),
    Node("Icônes", "Illustrator : Icônes"),          # lignes : fm_board/settings.py (ICON_GROUPS_BY_MODULE)
)
