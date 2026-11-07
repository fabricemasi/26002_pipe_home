"""Réglages du module PDF (fenêtre « Réglages : PDF », aussi onglet de « Réglages : Board ») : lignes
`CATALOG["PDF : …"]` et arbre `PDF_TREE`. Données seulement (aucun widget) : la fenêtre générique des réglages les
construit. Défauts : `settings_defaults.py`. Appliqués EN DIRECT à l'éditeur ouvert (chemin rapide des clés
`pdf_` de `PipelineBrowser._apply_settings` -> `PdfPane.apply_settings` : seul ce qui a changé est refait)."""
from __future__ import annotations

from settings_catalog import CATALOG, Node, Spec

from .settings_defaults import PDF_DEFAULTS as D

PDF_TAB = "Module PDF"

CATALOG["PDF : Affichage"] = [
    Spec("pdf_default_fit", "Zoom à l'ouverture", "choice", D["pdf_default_fit"],
         {"choices": (("width", "Ajuster à la largeur"), ("page", "Ajuster à la page"), ("", "Zoom fixe")),
          "width": 190}),
    Spec("pdf_default_zoom", "Zoom fixe", "slider", D["pdf_default_zoom"], {"min": 10, "max": 800, "unit": "%"}),
    Spec("pdf_default_mode", "Mode d'affichage", "choice", D["pdf_default_mode"],
         {"choices": (("continuous", "Défilement continu"), ("single", "Page simple"), ("two", "Double page"),
                      ("two_continuous", "Double page continue")), "width": 190}),
    Spec("pdf_view_background", "Fond autour des pages", "color", D["pdf_view_background"],
         {"title": "Fond autour des pages"}),
    Spec("pdf_show_thumbnails", "Panneau de gauche ouvert à l'ouverture", "bool", D["pdf_show_thumbnails"]),
    Spec("pdf_left_panel", "Panneau montré", "choice", D["pdf_left_panel"],
         {"choices": (("Pages", "Miniatures"), ("Signets", "Signets"), ("Champs", "Champs"),
                      ("Commentaires", "Commentaires"), ("Infos", "Infos")), "width": 170}),
    Spec("pdf_actual_size_dpi", "« Taille réelle » suit la résolution de l'écran", "bool", D["pdf_actual_size_dpi"]),
]
CATALOG["PDF : Rendu et mémoire"] = [
    Spec("pdf_cache_mb", "Mémoire des pages rendues", "slider", D["pdf_cache_mb"],
         {"min": 32, "max": 2048, "unit": "Mo"}),
    Spec("pdf_prefetch_screens", "Préchargement (hauteurs d'écran)", "slider", D["pdf_prefetch_screens"],
         {"min": 0, "max": 4}),
]
CATALOG["PDF : Formulaires"] = [
    Spec("pdf_forms_highlight", "Surbrillance des champs interactifs", "bool", D["pdf_forms_highlight"]),
    Spec("pdf_forms_highlight_color", "Couleur de surbrillance", "color", D["pdf_forms_highlight_color"],
         {"title": "Surbrillance des champs"}),
    Spec("pdf_forms_highlight_alpha", "Intensité de la surbrillance", "slider", D["pdf_forms_highlight_alpha"],
         {"min": 0, "max": 255}),
    Spec("pdf_javascript", "Scripts des formulaires (calculs, validations, XFA ; réseau toujours bloqué)", "bool",
         D["pdf_javascript"]),
    Spec("pdf_js_alerts", "Montrer les alertes des scripts", "bool", D["pdf_js_alerts"]),
    Spec("pdf_design_font_size", "Taille du texte des nouveaux champs (0 = auto)", "slider",
         D["pdf_design_font_size"], {"min": 0, "max": 36, "unit": "pt"}),
]
CATALOG["PDF : Ouverture et enregistrement"] = [
    Spec("pdf_open_double_click", "Double-clic sur un .pdf : éditeur PDF", "bool", D["pdf_open_double_click"]),
    Spec("pdf_save_mode", "Enregistrement", "choice", D["pdf_save_mode"],
         {"choices": (("auto", "Auto (incrémental si signé / XFA)"), ("incremental", "Toujours incrémental"),
                      ("full", "Toujours complet")), "width": 230}),
    Spec("pdf_autosave_recovery_s", "Copie de secours d'un document modifié (0 = jamais)", "slider",
         D["pdf_autosave_recovery_s"], {"min": 0, "max": 900, "unit": "s"}),
]
CATALOG["PDF : Sécurité"] = [
    Spec("pdf_confirm_links", "Demander avant d'ouvrir un lien externe", "bool", D["pdf_confirm_links"]),
    Spec("pdf_warn_active_content", "Bandeau si le document contient des scripts / pièces jointes", "bool",
         D["pdf_warn_active_content"]),
]
CATALOG["PDF : Commentaires"] = [
    Spec("pdf_annot_color", "Couleur (balisage, notes)", "color", D["pdf_annot_color"], {"title": "Commentaires"}),
    Spec("pdf_annot_ink_color", "Couleur (dessin, formes)", "color", D["pdf_annot_ink_color"], {"title": "Dessin"}),
    Spec("pdf_annot_width", "Épaisseur", "slider", D["pdf_annot_width"], {"min": 1, "max": 12, "unit": "pt"}),
]
CATALOG["PDF : OCR et impression"] = [
    Spec("pdf_ocr_languages", "Langues OCR préférées (fr;en)", "text", D["pdf_ocr_languages"], {"width": 120}),
    Spec("pdf_print_dpi", "Résolution d'impression", "slider", D["pdf_print_dpi"], {"min": 72, "max": 600,
                                                                                    "unit": "dpi"}),
    Spec("pdf_print_annotations", "Imprimer les commentaires", "bool", D["pdf_print_annotations"]),
]

PDF_TREE = (
    Node("Affichage", "PDF : Affichage"),
    Node("Rendu et mémoire", "PDF : Rendu et mémoire"),
    Node("Formulaires", "PDF : Formulaires"),
    Node("Ouverture et enregistrement", "PDF : Ouverture et enregistrement"),
    Node("Sécurité", "PDF : Sécurité"),
    Node("Commentaires", "PDF : Commentaires"),
    Node("OCR et impression", "PDF : OCR et impression"),
)
