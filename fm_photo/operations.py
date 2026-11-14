"""Primitives du moteur photo : registre et implémentation de RÉFÉRENCE (numpy, sans Qt).

Une opération travaille dans UN domaine déclaré (aujourd'hui toutes en « linéaire scène », espace de travail de
`couleur.py`), sur des images float32 (H, L, 3). Elle déclare :
- `defauts` : ses paramètres et leurs valeurs NEUTRES (aux défauts, l'opération ne change aucun pixel) ;
- `marge(params, contexte)` : rayon en pixels dont un pixel de sortie dépend (0 = ponctuelle) : c'est ce qui
  permet le calcul par tuiles sans couture ;
- `validation` : « référence » (définition exacte, testée) ou « tranche technique » (sert à valider
  l'intégration et les performances ; NI calibrée NI présentée comme une émulation : interdite dans un preset).

Le CONTEXTE rend un rendu indépendant de sa résolution : `echelle` = pixels rendus par pixel de pleine
définition, `largeur_pleine` = largeur de la photo entière en pixels de pleine définition. Une grandeur spatiale
s'exprime en fraction de la largeur de la photo, jamais en pixels d'écran : un aperçu réduit et l'export
calculent le même phénomène à deux échelles (égaux à l'échantillonnage près, ce que les tests mesurent)."""
from __future__ import annotations

import math
from dataclasses import dataclass, field

import numpy as np

from fm_photo import couleur


@dataclass(frozen=True)
class Contexte:
    echelle: float = 1.0            # pixels rendus / pixel de pleine définition
    largeur_pleine: int = 0         # largeur de la photo entière, pleine définition
    annule: object = None           # appelable -> True si le rendu est abandonné (testé entre les étapes)

    def abandonne(self) -> bool:
        return bool(self.annule and self.annule())


class Annule(Exception):
    """Rendu abandonné : son résultat n'existe pas (jamais d'image partielle)."""


@dataclass(frozen=True)
class Definition:
    ident: str
    version: int
    libelle: str
    defauts: dict
    appliquer: object               # (image, params, contexte) -> image
    marge: object = None            # (params, contexte) -> int ; None = ponctuelle
    validation: str = "référence"
    domaine: str = "lineaire_scene"
    notes: str = ""
    bornes: dict = field(default_factory=dict)

    def params(self, donnes: dict | None) -> dict:
        """Paramètres complets : défauts + valeurs données (les clés inconnues sont ignorées du calcul)."""
        complets = dict(self.defauts)
        complets.update({cle: valeur for cle, valeur in (donnes or {}).items() if cle in self.defauts})
        return complets

    def neutre(self, donnes: dict | None) -> bool:
        return self.params(donnes) == self.defauts


REGISTRE: dict[tuple[str, int], Definition] = {}


def declarer(definition: Definition) -> Definition:
    REGISTRE[(definition.ident, definition.version)] = definition
    return definition


def definition(ident: str, version: int = 1) -> Definition:
    return REGISTRE[(ident, version)]


# --- exposition -------------------------------------------------------------------------------------------

def _exposition(image, params, contexte):
    return image * np.float32(2.0 ** float(params["ev"]))


declarer(Definition("exposition", 1, "Exposition", {"ev": 0.0}, _exposition, bornes={"ev": (-5.0, 5.0)},
                    notes="Gain linéaire 2^EV sur la lumière de la scène ; ne restitue rien de ce qui est écrêté "
                          "dans la source."))


# --- diffusion des hautes lumières (TRANCHE TECHNIQUE) ----------------------------------------------------

TRONCATURE = 4.0                 # noyau gaussien coupé à 4 sigma (masse perdue ~6e-5, noyau renormalisé)


def sigma_pixels(params, contexte) -> float:
    return float(params["rayon"]) / 100.0 * contexte.largeur_pleine * contexte.echelle


def noyau_gaussien(sigma: float) -> np.ndarray:
    """Noyau 1D normalisé (float32), échantillonné aux centres des pixels, de rayon ceil(4 sigma)."""
    rayon = int(math.ceil(TRONCATURE * sigma))
    positions = np.arange(-rayon, rayon + 1, dtype=np.float64)
    noyau = np.exp(-0.5 * (positions / sigma) ** 2)
    return (noyau / noyau.sum()).astype(np.float32)


def flou_gaussien(image: np.ndarray, sigma: float, contexte: Contexte | None = None) -> np.ndarray:
    """Flou séparable exact (bords prolongés par répétition). Référence : une addition par prise du noyau."""
    if sigma <= 0.0:
        return image
    noyau = noyau_gaussien(sigma)
    rayon = len(noyau) // 2
    for axe in (0, 1):
        largeurs = [(rayon, rayon) if index == axe else (0, 0) for index in range(image.ndim)]
        etendue = np.pad(image, largeurs, mode="edge")
        somme = np.zeros_like(image)
        longueur = image.shape[axe]
        for prise, poids in enumerate(noyau):
            if contexte is not None and prise % 16 == 0 and contexte.abandonne():
                raise Annule()
            tranche = [slice(None)] * image.ndim
            tranche[axe] = slice(prise, prise + longueur)
            somme += poids * etendue[tuple(tranche)]
        image = somme
    return image


def _diffusion(image, params, contexte):
    quantite = float(params["quantite"])
    sigma = sigma_pixels(params, contexte)
    if quantite == 0.0 or sigma <= 0.0:
        return image
    y = couleur.luminance(image)
    seuil = np.float32(params["seuil"])
    part = np.maximum(y - seuil, 0.0) / np.maximum(y, np.float32(1e-6))
    source = image * part[..., None]
    halo = flou_gaussien(source, sigma, contexte)
    teinte = np.asarray(params["teinte"], dtype=np.float32)
    return image + np.float32(quantite) * halo * teinte


def _marge_diffusion(params, contexte) -> int:
    if float(params["quantite"]) == 0.0:
        return 0
    return int(math.ceil(TRONCATURE * sigma_pixels(params, contexte)))


declarer(Definition(
    "diffusion", 1, "Diffusion des hautes lumières (tranche technique)",
    {"quantite": 0.0, "seuil": 1.0, "rayon": 0.5, "teinte": [1.0, 0.35, 0.15]}, _diffusion, _marge_diffusion,
    validation="tranche technique", bornes={"quantite": (0.0, 2.0), "seuil": (0.0, 16.0), "rayon": (0.01, 5.0)},
    notes="Traitement spatial coûteux, représentatif d'une halation (source limitée, diffusion, teinte, mélange "
          "additif) pour valider tuiles, annulation, convergence aperçu / export et moteur Rust. `rayon` en % de "
          "la largeur de la photo. Aucun modèle de couches ni calibration : ce n'est PAS l'outil Halation."))


# --- chaîne ------------------------------------------------------------------------------------------------

def chaine(suite: list) -> list:
    """Suite d'un état -> [(définition, paramètres complets)] des opérations ACTIVES et non neutres, dans
    l'ordre. Une opération inconnue (ou d'une version d'algorithme inconnue) lève `KeyError` : jamais ignorée."""
    retenues = []
    for entree in suite:
        if not entree.get("actif", True):
            continue
        connue = definition(entree["op"], int(entree.get("version", 1)))
        if not connue.neutre(entree.get("params")):
            retenues.append((connue, connue.params(entree.get("params"))))
    return retenues


def marge_totale(suite: list, contexte: Contexte) -> int:
    return sum(connue.marge(params, contexte) if connue.marge else 0 for connue, params in chaine(suite))


def appliquer(image: np.ndarray, suite: list, contexte: Contexte) -> np.ndarray:
    """Rendu de référence d'une image entière (linéaire de travail -> linéaire de travail)."""
    for connue, params in chaine(suite):
        if contexte.abandonne():
            raise Annule()
        image = connue.appliquer(image, params, contexte)
    return image


def appliquer_par_tuiles(image: np.ndarray, suite: list, contexte: Contexte, cote: int = 512) -> np.ndarray:
    """Même résultat que `appliquer`, calculé tuile par tuile : chaque tuile est rendue sur sa zone élargie de
    la marge de la chaîne (bornée à l'image : les bords de l'IMAGE, pas ceux de la tuile, sont prolongés)."""
    marge = marge_totale(suite, contexte)
    hauteur, largeur = image.shape[:2]
    sortie = np.empty_like(image)
    for haut in range(0, hauteur, cote):
        for gauche in range(0, largeur, cote):
            bas, droite = min(haut + cote, hauteur), min(gauche + cote, largeur)
            y0, x0 = max(0, haut - marge), max(0, gauche - marge)
            y1, x1 = min(hauteur, bas + marge), min(largeur, droite + marge)
            rendu = appliquer(image[y0:y1, x0:x1], suite, contexte)
            sortie[haut:bas, gauche:droite] = rendu[haut - y0:bas - y0, gauche - x0:droite - x0]
    return sortie


def reduire(image: np.ndarray, facteur: int) -> np.ndarray:
    """Réduction entière par moyenne de blocs `facteur` x `facteur` (en linéaire ; blocs partiels des bords
    moyennés sur leurs pixels présents). C'est LA réduction des aperçus : `echelle` = 1 / facteur."""
    if facteur <= 1:
        return image
    hauteur, largeur = image.shape[:2]
    lignes = np.add.reduceat(image, np.arange(0, hauteur, facteur), axis=0)
    blocs = np.add.reduceat(lignes, np.arange(0, largeur, facteur), axis=1)
    compte_y = np.diff(np.append(np.arange(0, hauteur, facteur), hauteur))
    compte_x = np.diff(np.append(np.arange(0, largeur, facteur), largeur))
    return (blocs / (compte_y[:, None] * compte_x[None, :])[..., None]).astype(np.float32)
