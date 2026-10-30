"""Défauts des réglages du module Tableur (clés `tableur_*`) : source unique, fusionnés dans DEFAULT_SETTINGS par
`settings_store`. Aucun import de l'appli. Lus par `grid.GridWidget.apply_settings` (et le double-clic de
l'explorateur)."""
from typing import Any

TABLEUR_DEFAULTS: dict[str, Any] = {
    # Double-clic sur un .xlsx / .xlsm / .csv / .tsv dans une colonne : ouvert dans le module Tableur (mode Standard,
    # le fichier n'est jamais réécrit sans le demander). Faux : son logiciel (Excel) comme avant.
    "tableur_open_double_click": False,
    # Saisie et affichage des nombres : séparateur décimal (« , » / « . »), de milliers (espace, point, virgule,
    # aucun), ordre des dates saisies (« dmy » : 30/10/2026, « mdy » : 10/30/2026), langue des noms de jours / mois.
    "tableur_decimal_sep": ",",
    "tableur_thousands_sep": "espace",
    "tableur_date_order": "dmy",
    "tableur_lang": "fr",
    # Langue des formules À L'ÉCRAN (« fr » : =SOMME(A1;B2), virgule décimale ; « en » : =SUM(A1,B2)). Le classeur
    # garde toujours la syntaxe anglaise d'Excel ; les noms anglais restent acceptés à la saisie.
    "tableur_formula_lang": "fr",
    # Entrée valide puis déplace : « down », « right », « up », « left », « none ».
    "tableur_enter_moves": "down",
    # Couleurs du CONTENU de la grille (aspect d'Excel par défaut, comme le contenu du Board suit Miro).
    "tableur_background": "#ffffff",
    "tableur_text": "#000000",
    "tableur_grid": "#d9d9d9",
    "tableur_header_bg": "#f3f3f3",
    "tableur_header_text": "#5c5c5c",
    "tableur_selection": "#107c41",
}
