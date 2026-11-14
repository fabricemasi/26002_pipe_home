"""Recettes photographiques : format, matrice d'un boîtier, vérification de compatibilité (sans Qt).

Deux sortes, toujours distinguées (`type`) :
- « boitier » : seulement des réglages qu'on peut saisir sur un boîtier identifié (modèle + firmware) ;
- « logicielle » : une recette PIPE FMZ, qui peut en plus porter une suite d'opérations du moteur (`operations`,
  mêmes primitives que le développement et FM Film : aucun traitement n'est dupliqué ici).
La compatibilité des RÉGLAGES ne dit rien de l'équivalence des PIXELS : le rendu d'une recette n'est « validé »
que par une calibration RAW + JPEG appariés (`validation`, vide par défaut = « non validée »).

Format (JSON, clés inconnues gardées) :
    {"schema": 1, "nom": "", "type": "boitier", "famille": "", "tags": [], "favori": false, "version": 1,
     "boitier": {"modele": "fujifilm_x_t5", "firmware": "4.00", "format": "JPEG"},
     "reglages": {"film_simulation": "CLASSIC CHROME", "dynamic_range": "200", "color": 2},
     "prise_de_vue": {"iso": 250, "compensation_exposition": "+1/3"},
     "operations": [], "references": [], "validation": {"statut": "non validée", "preuves": []}}

La matrice X-T5 vient du manuel officiel (docs/agents/fm_photo_sources.md, section 2). Ce que le manuel n'écrit pas
(pas de la courbe de tons, plages du WB Shift et de Monochromatic Color, valeurs par défaut) n'est PAS inventé :
ces réglages sont acceptés mais rapportés « non vérifiables ». Aucun transfert vers un boîtier n'existe."""
from __future__ import annotations

import copy
import json
from dataclasses import dataclass, field

SCHEMA = 1
NON_VALIDEE = "non validée"


@dataclass(frozen=True)
class Reglage:
    valeurs: tuple = ()              # énumération documentée ; vide si `bornes` ou non documenté
    bornes: tuple | None = None      # (min, max) documentés
    pas: float | None = None         # pas documenté ; None = non écrit dans le manuel
    documente: bool = True           # False : plage absente du manuel (accepté, rapporté non vérifiable)


_FORCE = ("OFF", "WEAK", "STRONG")
_ACROS = tuple(f"ACROS{filtre}" for filtre in ("", "+Ye", "+R", "+G"))
_MONO = tuple(f"MONOCHROME{filtre}" for filtre in ("", "+Ye", "+R", "+G"))
X_T5 = {
    "film_simulation": Reglage(("PROVIA/STANDARD", "Velvia/VIVID", "ASTIA/SOFT", "CLASSIC CHROME", "REALA ACE",
                                "PRO Neg. Hi", "PRO Neg. Std", "CLASSIC Neg.", "NOSTALGIC Neg.", "ETERNA/CINEMA",
                                "ETERNA BLEACH BYPASS") + _ACROS + _MONO + ("SEPIA",)),
    "grain_roughness": Reglage(_FORCE), "grain_size": Reglage(("SMALL", "LARGE")),
    "color_chrome_effect": Reglage(_FORCE), "color_chrome_fx_blue": Reglage(_FORCE),
    "smooth_skin_effect": Reglage(_FORCE),
    "white_balance": Reglage(("WHITE PRIORITY", "AUTO", "AMBIENCE PRIORITY", "CUSTOM 1", "CUSTOM 2", "CUSTOM 3",
                              "COLOR TEMPERATURE", "DAYLIGHT", "SHADE", "FLUORESCENT 1", "FLUORESCENT 2",
                              "FLUORESCENT 3", "INCANDESCENT", "UNDERWATER")),
    "color_temperature": Reglage(bornes=(2500, 10000), pas=10),
    "wb_shift_r": Reglage(documente=False), "wb_shift_b": Reglage(documente=False),
    "monochromatic_wc": Reglage(documente=False), "monochromatic_mg": Reglage(documente=False),
    "dynamic_range": Reglage(("AUTO", "100", "200", "400")),
    "d_range_priority": Reglage(("OFF", "AUTO", "WEAK", "STRONG")),
    "tone_curve_highlights": Reglage(bornes=(-2, 4)), "tone_curve_shadows": Reglage(bornes=(-2, 4)),
    "color": Reglage(bornes=(-4, 4), pas=1), "sharpness": Reglage(bornes=(-4, 4), pas=1),
    "high_iso_nr": Reglage(bornes=(-4, 4), pas=1), "clarity": Reglage(bornes=(-5, 5), pas=1),
}
BOITIERS = {"fujifilm_x_t5": X_T5}
ISO_MINIMALE = {"dynamic_range": {"200": 250, "400": 500}, "d_range_priority": {"WEAK": 250, "STRONG": 500}}
FIRMWARE_MINIMAL = {"REALA ACE": "4.00"}
# Capacités de rendu du moteur PIPE FMZ pour les réglages d'un boîtier : AUCUNE à ce jour (registre, ligne 15).
CAPACITES_MOTEUR: frozenset = frozenset()


@dataclass
class Rapport:
    erreurs: list = field(default_factory=list)              # valeur hors matrice, dépendance violée
    non_verifiables: list = field(default_factory=list)      # plage ou pas absents du manuel
    non_pris_en_charge: list = field(default_factory=list)   # réglages que le moteur ne sait pas rendre
    transposable: bool = False                               # saisissable tel quel sur le boîtier nommé

    @property
    def valide(self) -> bool:
        return not self.erreurs


def nouvelle(nom: str = "", type_recette: str = "boitier", modele: str = "fujifilm_x_t5", firmware: str = "") -> dict:
    return {"schema": SCHEMA, "nom": nom, "type": type_recette, "famille": "", "tags": [], "favori": False,
            "version": 1, "boitier": {"modele": modele, "firmware": firmware, "format": "JPEG"}, "reglages": {},
            "prise_de_vue": {}, "operations": [], "references": [],
            "validation": {"statut": NON_VALIDEE, "preuves": []}}


def _version(texte: str) -> tuple:
    return tuple(int(part) for part in str(texte).split(".") if part.isdigit())


def verifier(recette: dict) -> Rapport:
    """Contrôle une recette contre la matrice de son boîtier ; rien n'est corrigé ni ignoré en silence."""
    rapport = Rapport()
    boitier = recette.get("boitier", {})
    matrice = BOITIERS.get(boitier.get("modele"))
    reglages = recette.get("reglages", {})
    if recette.get("type") not in ("boitier", "logicielle"):
        rapport.erreurs.append(f"type inconnu : {recette.get('type')!r}")
    if matrice is None:
        rapport.erreurs.append(f"boîtier sans matrice : {boitier.get('modele')!r}")
        return rapport
    for nom, valeur in reglages.items():
        connu = matrice.get(nom)
        if connu is None:
            rapport.erreurs.append(f"{nom} : réglage absent de la matrice du boîtier")
        elif not connu.documente:
            rapport.non_verifiables.append(f"{nom} = {valeur!r} : plage non écrite dans le manuel")
        elif connu.valeurs and valeur not in connu.valeurs:
            rapport.erreurs.append(f"{nom} = {valeur!r} : hors des valeurs du boîtier")
        elif connu.bornes:
            if not isinstance(valeur, (int, float)) or isinstance(valeur, bool) or not (
                    connu.bornes[0] <= valeur <= connu.bornes[1]):
                rapport.erreurs.append(f"{nom} = {valeur!r} : hors de {connu.bornes[0]} à {connu.bornes[1]}")
            elif connu.pas is None:
                if valeur != int(valeur):
                    rapport.non_verifiables.append(f"{nom} = {valeur!r} : pas non écrit dans le manuel")
            elif (valeur - connu.bornes[0]) % connu.pas:
                rapport.erreurs.append(f"{nom} = {valeur!r} : pas de {connu.pas:g}")
        if nom not in CAPACITES_MOTEUR:
            rapport.non_pris_en_charge.append(nom)
    iso = recette.get("prise_de_vue", {}).get("iso")
    for nom, minimums in ISO_MINIMALE.items():
        exige = minimums.get(str(reglages.get(nom)))
        if exige and (iso is None or iso < exige):
            rapport.erreurs.append(f"{nom} = {reglages[nom]} exige ISO {exige} au moins (ISO de la recette : {iso})")
    if reglages.get("d_range_priority", "OFF") != "OFF":
        for nom in ("dynamic_range", "tone_curve_highlights", "tone_curve_shadows"):
            if nom in reglages:
                rapport.erreurs.append(f"{nom} : réglé automatiquement quand D RANGE PRIORITY n'est pas OFF")
    simulation = reglages.get("film_simulation", "")
    if any(nom in reglages for nom in ("monochromatic_wc", "monochromatic_mg")) and simulation not in _ACROS + _MONO:
        rapport.erreurs.append("MONOCHROMATIC COLOR : réservé à ACROS et MONOCHROME")
    exige = FIRMWARE_MINIMAL.get(simulation)
    if exige and _version(boitier.get("firmware", "")) < _version(exige):
        rapport.erreurs.append(f"{simulation} exige le firmware {exige} (firmware de la recette : "
                               f"{boitier.get('firmware') or 'non renseigné'})")
    if boitier.get("format") == "HEIF" and reglages.get("clarity", 0) != 0:
        rapport.erreurs.append("clarity : désactivée en HEIF")
    if "color_temperature" in reglages and reglages.get("white_balance") != "COLOR TEMPERATURE":
        rapport.erreurs.append("color_temperature : seulement avec WHITE BALANCE = COLOR TEMPERATURE")
    rapport.transposable = (rapport.valide and recette.get("type") == "boitier" and not recette.get("operations"))
    return rapport


def exporter_json(recette: dict) -> str:
    return json.dumps(recette, ensure_ascii=False, indent=1, sort_keys=True)


def importer_json(texte: str) -> dict:
    """Recette lue d'un JSON exporté ; clés inconnues gardées ; schéma plus récent refusé (`ValueError`)."""
    recette = json.loads(texte)
    if not isinstance(recette, dict) or "reglages" not in recette:
        raise ValueError("Ce fichier n'est pas une recette PIPE FMZ.")
    if int(recette.get("schema", 1)) > SCHEMA:
        raise ValueError(f"Recette d'un schéma plus récent ({recette['schema']} > {SCHEMA}).")
    complete = nouvelle()
    complete.update(copy.deepcopy(recette))
    return complete
