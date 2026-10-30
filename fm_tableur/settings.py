"""Réglages du module Tableur : section « Tableur » de l'onglet « Module MRO » (fenêtre « Réglages : Board »),
lignes `CATALOG["MRO : Tableur"]`. Données seulement (aucun widget) : la fenêtre générique des réglages les
construit. Défauts : `settings_defaults.py`. Appliqués EN DIRECT (chemin rapide des clés `tableur_` de
`PipelineBrowser._apply_settings` -> `BoardPane.apply_settings` -> classeurs ouverts)."""
from __future__ import annotations

from settings_catalog import CATALOG, Spec

CATALOG["MRO : Tableur"] = [
    Spec("tableur_open_double_click", "Double-clic sur un classeur (.xlsx, .csv) : module Tableur", "bool", False),
    Spec("tableur_formula_lang", "Formules à l'écran", "choice", "fr",
         {"choices": (("fr", "Français : =SOMME(A1;B2)"), ("en", "Anglais : =SUM(A1,B2)")), "width": 230}),
    Spec("tableur_decimal_sep", "Séparateur décimal", "choice", ",",
         {"choices": ((",", "Virgule"), (".", "Point")), "width": 160}),
    Spec("tableur_thousands_sep", "Séparateur de milliers", "choice", "espace",
         {"choices": (("espace", "Espace fine"), ("point", "Point"), ("virgule", "Virgule"), ("aucun", "Aucun")),
          "width": 160}),
    Spec("tableur_date_order", "Ordre des dates saisies", "choice", "dmy",
         {"choices": (("dmy", "Jour / mois / année"), ("mdy", "Mois / jour / année")), "width": 200}),
    Spec("tableur_lang", "Noms des jours et des mois", "choice", "fr",
         {"choices": (("fr", "Français"), ("en", "Anglais")), "width": 160}),
    Spec("tableur_background", "Fond des cellules", "color", "#ffffff", {"title": "Fond des cellules"}),
    Spec("tableur_text", "Texte des cellules", "color", "#000000", {"title": "Texte des cellules"}),
    Spec("tableur_grid", "Quadrillage", "color", "#d9d9d9", {"title": "Quadrillage"}),
    Spec("tableur_header_bg", "Fond des entêtes", "color", "#f3f3f3", {"title": "Fond des entêtes"}),
    Spec("tableur_header_text", "Texte des entêtes", "color", "#5c5c5c", {"title": "Texte des entêtes"}),
    Spec("tableur_selection", "Sélection", "color", "#107c41", {"title": "Sélection"}),
    Spec("tableur_enter_moves", "Entrée valide puis va", "choice", "down",
         {"choices": (("down", "En bas"), ("right", "À droite"), ("up", "En haut"), ("left", "À gauche"),
                      ("none", "Reste sur place")), "width": 160}),
]
