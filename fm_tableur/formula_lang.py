"""Formules en français (SANS Qt) : comme Excel en français — noms de fonctions (`SOMME`, `RECHERCHEV`), « ; »
entre les arguments, virgule décimale. Le classeur garde TOUJOURS la syntaxe anglaise d'Excel (celle des .xlsx) :
traduction seulement à l'affichage / l'édition (`to_local`) et à la saisie (`to_english`). À la saisie, les noms
anglais restent acceptés (`=SUM(...)` en mode français). Chaînes « "…" » et noms de feuille « '…' » jamais touchés.
Réglage : `tableur_formula_lang` (« fr » / « en »)."""
from __future__ import annotations

import re

FR = {
    "ABS": "ABS", "ACOS": "ACOS", "AND": "ET", "AVERAGE": "MOYENNE", "AVERAGEA": "AVERAGEA",
    "AVERAGEIF": "MOYENNE.SI", "AVERAGEIFS": "MOYENNE.SI.ENS", "CEILING": "PLAFOND", "CEILING.MATH": "PLAFOND.MATH",
    "CHAR": "CAR", "CHOOSE": "CHOISIR", "CLEAN": "EPURAGE", "CODE": "CODE", "COLUMN": "COLONNE",
    "COLUMNS": "COLONNES", "CONCAT": "CONCAT", "CONCATENATE": "CONCATENER", "CORREL": "COEFFICIENT.CORRELATION",
    "COS": "COS", "COUNT": "NB", "COUNTA": "NBVAL", "COUNTBLANK": "NB.VIDE", "COUNTIF": "NB.SI",
    "COUNTIFS": "NB.SI.ENS", "CUMIPMT": "CUMUL.INTER", "CUMPRINC": "CUMUL.PRINCPER", "DATE": "DATE",
    "DATEDIF": "DATEDIF", "DATEVALUE": "DATEVAL", "DAY": "JOUR", "DAYS": "JOURS", "DB": "DB", "DDB": "DDB",
    "DEGREES": "DEGRES", "EDATE": "MOIS.DECALER", "EFFECT": "TAUX.EFFECTIF", "EOMONTH": "FIN.MOIS", "EVEN": "PAIR",
    "EXACT": "EXACT", "EXP": "EXP", "FACT": "FACT", "FALSE": "FAUX", "FILTER": "FILTRE", "FIND": "TROUVE",
    "FIXED": "CTXT", "FLOOR": "PLANCHER", "FLOOR.MATH": "PLANCHER.MATH", "FORECAST": "PREVISION",
    "FREQUENCY": "FREQUENCE", "FV": "VC", "GCD": "PGCD", "GEOMEAN": "MOYENNE.GEOMETRIQUE", "HLOOKUP": "RECHERCHEH",
    "HOUR": "HEURE", "HYPERLINK": "LIEN_HYPERTEXTE", "IF": "SI", "IFERROR": "SIERREUR", "IFNA": "SI.NON.DISP",
    "IFS": "SI.CONDITIONS", "INDEX": "INDEX", "INDIRECT": "INDIRECT", "INT": "ENT", "IPMT": "INTPER", "IRR": "TRI",
    "ISBLANK": "ESTVIDE", "ISERR": "ESTERR", "ISERROR": "ESTERREUR", "ISEVEN": "EST.PAIR", "ISLOGICAL": "ESTLOGIQUE",
    "ISNA": "ESTNA", "ISNONTEXT": "ESTNONTEXTE", "ISNUMBER": "ESTNUM", "ISODD": "EST.IMPAIR", "ISTEXT": "ESTTEXTE",
    "LARGE": "GRANDE.VALEUR", "LCM": "PPCM", "LEFT": "GAUCHE", "LEN": "NBCAR", "LET": "LET", "LN": "LN",
    "LOG": "LOG", "LOG10": "LOG10", "LOOKUP": "RECHERCHE", "LOWER": "MINUSCULE", "MATCH": "EQUIV", "MAX": "MAX",
    "MAXIFS": "MAX.SI.ENS", "MEDIAN": "MEDIANE", "MID": "STXT", "MIN": "MIN", "MINIFS": "MIN.SI.ENS",
    "MINUTE": "MINUTE", "MIRR": "TRIM", "MOD": "MOD", "MODE": "MODE", "MONTH": "MOIS", "MROUND": "ARRONDI.AU.MULTIPLE",
    "NA": "NA", "NETWORKDAYS": "NB.JOURS.OUVRES", "NETWORKDAYS.INTL": "NB.JOURS.OUVRES.INTL", "NOT": "NON",
    "NOW": "MAINTENANT", "NPER": "NPM", "NPV": "VAN", "NUMBERVALUE": "VALEURNOMBRE", "ODD": "IMPAIR",
    "OFFSET": "DECALER", "OR": "OU", "PERCENTILE": "CENTILE", "PI": "PI", "PMT": "VPM", "POWER": "PUISSANCE",
    "PPMT": "PRINCPER", "PRODUCT": "PRODUIT", "PROPER": "NOMPROPRE", "PV": "VA", "QUARTILE": "QUARTILE",
    "QUOTIENT": "QUOTIENT", "RADIANS": "RADIANS", "RAND": "ALEA", "RANDARRAY": "TABLEAU.ALEA",
    "RANDBETWEEN": "ALEA.ENTRE.BORNES", "RANK": "RANG", "RATE": "TAUX", "REPLACE": "REMPLACER", "REPT": "REPT",
    "RIGHT": "DROITE", "ROUND": "ARRONDI", "ROUNDDOWN": "ARRONDI.INF", "ROUNDUP": "ARRONDI.SUP", "ROW": "LIGNE",
    "ROWS": "LIGNES", "SEARCH": "CHERCHE", "SECOND": "SECONDE", "SEQUENCE": "SEQUENCE", "SIGN": "SIGNE",
    "SIN": "SIN", "SLN": "AMORLIN", "SMALL": "PETITE.VALEUR", "SORT": "TRIER", "SORTBY": "TRIERPAR",
    "SQRT": "RACINE", "STDEV": "ECARTYPE", "STDEV.P": "ECARTYPE.PEARSON", "STDEV.S": "ECARTYPE.STANDARD",
    "STDEVP": "ECARTYPEP", "SUBSTITUTE": "SUBSTITUE", "SUBTOTAL": "SOUS.TOTAL", "SUM": "SOMME",
    "SUMIF": "SOMME.SI", "SUMIFS": "SOMME.SI.ENS", "SUMPRODUCT": "SOMMEPROD", "SUMSQ": "SOMME.CARRES",
    "SWITCH": "SI.MULTIPLE", "SYD": "SYD", "T": "T", "TAN": "TAN", "TEXT": "TEXTE", "TEXTJOIN": "JOINDRE.TEXTE",
    "TIME": "TEMPS", "TIMEVALUE": "TEMPSVAL", "TODAY": "AUJOURDHUI", "TRANSPOSE": "TRANSPOSE", "TREND": "TENDANCE",
    "TRIM": "SUPPRESPACE", "TRUE": "VRAI", "TRUNC": "TRONQUE", "TYPE": "TYPE", "UNIQUE": "UNIQUE",
    "UPPER": "MAJUSCULE", "VALUE": "CNUM", "VAR": "VAR", "VAR.P": "VAR.P.N", "VAR.S": "VAR.S", "VLOOKUP": "RECHERCHEV",
    "WEEKDAY": "JOURSEM", "WEEKNUM": "NO.SEMAINE", "WORKDAY": "SERIE.JOUR.OUVRE", "XIRR": "TRI.PAIEMENTS",
    "XLOOKUP": "RECHERCHEX", "XMATCH": "EQUIVX", "XNPV": "VAN.PAIEMENTS", "YEAR": "ANNEE", "YEARFRAC": "FRACTION.ANNEE",
}
EN = {fr: en for en, fr in FR.items()}
_COMMON = r"\"(?:[^\"]|\"\")*\"|'(?:[^']|'')*'|[A-Za-z_][A-Za-z0-9_.]*(?=\s*\()|\b(?:TRUE|FALSE|VRAI|FAUX)\b(?!\s*\()"
# nombre décimal (jamais la fin d'une référence : « A1,5 » n'est pas 1,5)
_TOKEN_EN = re.compile(_COMMON + r"|(?<![A-Za-z$\d.])\d+\.\d+(?:[eE][+-]?\d+)?|[;,]", re.I)
_TOKEN_FR = re.compile(_COMMON + r"|(?<![A-Za-z$\d,])\d+,\d+(?:[eE][+-]?\d+)?|[;,]", re.I)


def to_local(formula: str, lang: str = "fr") -> str:
    """Formule du classeur (anglais) -> texte affiché / édité."""
    if lang != "fr" or not formula or not formula.startswith("="):
        return formula
    def fn(m):
        tok = m.group(0)
        if tok[0] in "\"'":
            return tok
        if tok[0].isdigit():
            return tok.replace(".", ",")
        if tok == ",":
            return ";"
        if tok == ";":
            return tok
        return FR.get(tok.upper(), tok)
    return _TOKEN_EN.sub(fn, formula)


def to_english(text: str, lang: str = "fr") -> str:
    """Formule tapée -> syntaxe du classeur. Noms français ou anglais acceptés."""
    if lang != "fr" or not text or not text.startswith("="):
        return text

    def fn(m):
        tok = m.group(0)
        if tok[0] in "\"'":
            return tok
        if tok[0].isdigit():
            return tok.replace(",", ".")
        if tok == ";":
            return ","
        if tok == ",":
            return ","
        return EN.get(tok.upper(), tok)
    return _TOKEN_FR.sub(fn, text)
