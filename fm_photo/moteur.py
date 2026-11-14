"""Façade du moteur photo : une demande de rendu = une source + une suite d'opérations + une échelle (sans Qt).

API de haut niveau : l'appelant ne manipule ni tuiles ni buffers intermédiaires. Deux exécutants, MÊME contrat :
- la RÉFÉRENCE numpy (`operations.py`, `couleur.py`) : toujours disponible, juge de l'autre, lente ;
- le moteur Rust `fm_photo_moteur` (`fm_photo/moteur_rust`, PyO3 + rayon ; construit par
  `tools/build_moteur_photo.ps1`) : lit le tableau numpy SANS copie, calcule hors du verrou Python, interroge
  `annule` entre ses bandes de calcul, garde chez lui les images réduites des sources nommées par `cle`.
Le choix se fait PAR SUITE (`executant`) : Rust seulement si toutes les opérations actives de la suite sont dans
`fm_photo_moteur.operations()` (même identifiant, même version d'algorithme) ; sinon la référence, entière. Écart
Rust / référence borné par `tests/test_photo_rust.py` (seuils de `docs/agents/fm_film_protocole.md`).
Sortie d'affichage : sRGB (comme la visionneuse, qui n'applique pas le profil de l'écran), 8 bits, écrêtage
explicite du gamut et des hautes lumières (`couleur.depuis_travail`)."""
from __future__ import annotations

import json
import math

import numpy as np

from fm_photo import couleur, operations
from fm_photo import warper  # noqa: F401 -- déclare son opération dans le registre
from fm_photo.operations import Annule, Contexte  # noqa: F401 -- réexportés

try:
    import fm_photo_moteur as _rust
except ImportError:                      # moteur non construit sur cette machine : référence seule
    _rust = None

_MOTEUR = _rust.Moteur() if _rust is not None else None
_OPERATIONS_RUST = frozenset((nom, version) for nom, version in _rust.operations()) if _rust is not None else frozenset()
EXECUTANT = "Rust" if _rust is not None else "référence numpy"


def executant(suite: list, reference: bool = False) -> str:
    """« Rust » si le moteur Rust rend TOUTE cette suite, sinon « référence numpy »."""
    if _MOTEUR is None or reference:
        return "référence numpy"
    connues = all((connue.ident, connue.version) in _OPERATIONS_RUST for connue, _params in operations.chaine(suite))
    return "Rust" if connues else "référence numpy"


def _demande(suite: list, espace: str) -> str:
    return json.dumps({
        "operations": [{"op": connue.ident, "version": connue.version, "params": params}
                       for connue, params in operations.chaine(suite)],
        "luminance": [float(valeur) for valeur in couleur.coefficients_luminance()],
        "matrice": [float(valeur) for valeur in couleur.matrice(couleur.TRAVAIL, espace).ravel()],
        "transfert": couleur.ESPACES[espace].transfert})


def _rendre_rust(pixels: np.ndarray, suite: list, facteur: int, sortie: str, espace: str, annule, cle):
    pixels = np.ascontiguousarray(pixels, dtype=np.float32)
    hauteur, largeur = pixels.shape[:2]
    rendu = _MOTEUR.rendre(pixels, largeur, hauteur, _demande(suite, espace), int(facteur), sortie, annule, cle)
    if rendu is None:
        raise Annule()
    return rendu


def oublier(cle: int) -> None:
    """La source nommée `cle` n'existe plus : le moteur Rust libère ses images réduites."""
    if _MOTEUR is not None:
        _MOTEUR.oublier(int(cle))


def facteur_pour(largeur: int, hauteur: int, cible_l: int, cible_h: int) -> int:
    """Plus grande réduction entière qui garde l'image au moins aussi grande qu'une fois AJUSTÉE (ratio gardé)
    à la zone d'affichage : la réduction finale vers l'écran ne fait jamais qu'adoucir, jamais agrandir."""
    if cible_l <= 0 or cible_h <= 0:
        return 1
    return max(1, int(math.floor(max(largeur / cible_l, hauteur / cible_h))))


def facteur_rapide(largeur: int, hauteur: int, cote: int = 1024) -> int:
    """Réduction de l'aperçu PROVISOIRE : grand côté ramené sous `cote` pixels."""
    return max(1, int(math.ceil(max(largeur, hauteur) / cote)))


def rendre_lineaire(pixels: np.ndarray, suite: list, facteur: int = 1, annule=None, cle: int | None = None,
                    reference: bool = False) -> np.ndarray:
    """Linéaire de travail rendu à l'échelle 1 / facteur. `Annule` si `annule()` devient vrai."""
    if executant(suite, reference) == "Rust":
        octets, largeur, hauteur = _rendre_rust(pixels, suite, facteur, "lineaire", "srgb", annule, cle)
        return np.frombuffer(octets, dtype=np.float32).reshape(hauteur, largeur, 3)
    contexte = Contexte(1.0 / facteur, pixels.shape[1], annule)
    return operations.appliquer(operations.reduire(pixels, facteur), suite, contexte)


def vers_rgbx8(lineaire: np.ndarray, espace: str = "srgb") -> np.ndarray:
    """Linéaire de travail -> (H, L, 4) uint8 R, V, B, 255 : tampon d'un QImage Format_RGBX8888."""
    code = couleur.quantifier(couleur.depuis_travail(lineaire, espace))
    sortie = np.full(code.shape[:2] + (4,), 255, dtype=np.uint8)
    sortie[..., :3] = code
    return sortie


def rendre_affichage(pixels: np.ndarray, suite: list, facteur: int = 1, annule=None, cle: int | None = None,
                     reference: bool = False) -> np.ndarray:
    """(H, L, 4) uint8 pour l'écran. `cle` nomme la source (cache des réductions du moteur Rust)."""
    if executant(suite, reference) == "Rust":
        octets, largeur, hauteur = _rendre_rust(pixels, suite, facteur, "rgbx8", "srgb", annule, cle)
        return np.frombuffer(octets, dtype=np.uint8).reshape(hauteur, largeur, 4)
    return vers_rgbx8(rendre_lineaire(pixels, suite, facteur, annule, reference=True))


def rendre_export(pixels: np.ndarray, suite: list, espace: str = "srgb", bits: int = 16, annule=None,
                  reference: bool = False) -> np.ndarray:
    """Pleine définition, mêmes opérations et mêmes paramètres que l'aperçu : (H, L, 3) uint8 ou uint16."""
    if executant(suite, reference) == "Rust":
        sortie = "code16" if bits > 8 else "code8"
        octets, largeur, hauteur = _rendre_rust(pixels, suite, 1, sortie, espace, annule, None)
        return np.frombuffer(octets, dtype=np.uint16 if bits > 8 else np.uint8).reshape(hauteur, largeur, 3)
    lineaire = rendre_lineaire(pixels, suite, 1, annule, reference=True)
    return couleur.quantifier(couleur.depuis_travail(lineaire, espace), bits)
