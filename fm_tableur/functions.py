"""Catalogue des fonctions proposées (« Insérer une fonction ») : les fonctions VÉRIFIÉES avec le moteur (matrice :
`tools/tableur_functions.py` -> `docs/agents/fm_tableur_fonctions.md`), avec une courte description française."""
from __future__ import annotations

DESCRIPTIONS = {
    "SUM": "somme", "AVERAGE": "moyenne", "COUNT": "nombre de nombres", "COUNTA": "nombre de cellules non vides",
    "MIN": "minimum", "MAX": "maximum", "MEDIAN": "médiane", "ROUND": "arrondi", "ROUNDUP": "arrondi supérieur",
    "ROUNDDOWN": "arrondi inférieur", "ABS": "valeur absolue", "MOD": "reste", "POWER": "puissance",
    "SQRT": "racine carrée", "INT": "partie entière", "TRUNC": "tronquer", "PRODUCT": "produit",
    "SUMPRODUCT": "somme des produits", "SUMIF": "somme si", "SUMIFS": "somme si (plusieurs critères)",
    "COUNTIF": "nombre si", "COUNTIFS": "nombre si (plusieurs critères)", "AVERAGEIF": "moyenne si",
    "AVERAGEIFS": "moyenne si (plusieurs critères)", "STDEV": "écart type (échantillon)", "VAR": "variance",
    "IF": "si", "IFS": "si multiples", "AND": "et", "OR": "ou", "NOT": "non", "IFERROR": "si erreur",
    "IFNA": "si #N/A", "SWITCH": "choix", "VLOOKUP": "recherche verticale", "HLOOKUP": "recherche horizontale",
    "XLOOKUP": "recherche X", "INDEX": "index", "MATCH": "équiv", "XMATCH": "équiv X", "LEFT": "gauche",
    "RIGHT": "droite", "MID": "stxt", "LEN": "longueur", "TRIM": "supprespace", "CONCAT": "concaténer",
    "TEXTJOIN": "joindre texte", "TEXT": "texte formaté", "FIND": "trouve", "SEARCH": "cherche",
    "SUBSTITUTE": "substitue", "VALUE": "valeur", "UPPER": "majuscule", "LOWER": "minuscule", "TODAY": "aujourd'hui",
    "NOW": "maintenant", "DATE": "date", "YEAR": "année", "MONTH": "mois", "DAY": "jour", "DATEDIF": "écart de dates",
    "NETWORKDAYS": "jours ouvrés", "WORKDAY": "série jours ouvrés", "EDATE": "mois décalés", "EOMONTH": "fin de mois",
    "WEEKDAY": "jour de la semaine", "PMT": "versement (VPM)", "PV": "valeur actuelle (VA)",
    "FV": "valeur future (VC)", "RATE": "taux", "NPER": "nombre de périodes", "NPV": "valeur actuelle nette (VAN)",
    "IRR": "taux de rentabilité interne (TRI)", "XNPV": "VAN à dates", "XIRR": "TRI à dates", "FILTER": "filtrer",
    "SORT": "trier", "UNIQUE": "valeurs uniques", "SEQUENCE": "suite", "LET": "variables nommées",
    "RAND": "aléatoire", "RANDBETWEEN": "aléatoire entre", "ISBLANK": "est vide", "ISNUMBER": "est un nombre",
    "ISTEXT": "est un texte", "ISERROR": "est une erreur", "NA": "#N/A", "CHOOSE": "choisir",
    "OFFSET": "décaler", "INDIRECT": "référence indirecte", "ROW": "ligne", "COLUMN": "colonne", "ROWS": "lignes",
    "COLUMNS": "colonnes", "TRANSPOSE": "transposer", "LARGE": "k-ième plus grand", "SMALL": "k-ième plus petit",
    "RANK": "rang", "PERCENTILE": "centile", "QUARTILE": "quartile", "MODE": "mode", "CEILING": "plafond",
    "FLOOR": "plancher", "EXP": "exponentielle", "LN": "logarithme népérien", "LOG": "logarithme", "PI": "pi",
}


def catalog():
    """[(nom, description)] triés : fonctions VÉRIFIÉES (voir `SUPPORTED`) d'abord décrites."""
    names = sorted(SUPPORTED or DESCRIPTIONS)
    return [(n, DESCRIPTIONS.get(n, "")) for n in names]


def _supported() -> set[str]:
    """Liste VÉRIFIÉE produite par `tools/tableur_functions.py` (sonde du moteur) ; absente : les descriptions."""
    from pathlib import Path
    path = Path(__file__).with_name("fonctions_verifiees.txt")
    try:
        return {line.strip() for line in path.read_text(encoding="utf-8").splitlines() if line.strip()}
    except OSError:
        return set()


SUPPORTED: set[str] = _supported()
