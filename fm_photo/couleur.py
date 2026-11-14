"""Contrat colorimétrique du moteur photo : implémentation de RÉFÉRENCE (numpy, sans Qt), lisible et contrôlable.

Toute optimisation (Rust, GPU, LUT) est comparée à ce fichier ; il ne cherche pas la vitesse.

Domaines, à ne jamais confondre (chaque opération du moteur déclare les siens) :
- « linéaire scène » : proportionnel à la lumière, NON borné (négatifs = hors gamut, > 1 = hautes lumières) ;
  l'espace de TRAVAIL est Rec.2020 linéaire, blanc D65, float32 ;
- « log » : Cineon (densité de négatif imprimable codée sur 10 bits), pour la chaîne argentique ;
- « densité » : D = -log10(transmittance) ;
- « affichage » : valeurs encodées par la fonction de transfert d'un espace de sortie, bornées à [0, 1].

Règles : aucune fonction n'écrête en silence (l'écrêtage est un paramètre nommé de la sortie) ; les fonctions de
transfert sont prolongées par symétrie impaire pour les négatifs (pas de NaN, pas de perte) ; les matrices sont
CALCULÉES à partir des chromaticités publiées, jamais recopiées ; une adaptation chromatique (Bradford) n'a lieu
que si les blancs diffèrent. Ce modèle est RGB : il ne reconstruit aucun spectre."""
from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache

import numpy as np

BLANCS = {"D65": (0.3127, 0.3290), "D50": (0.3457, 0.3585)}


@dataclass(frozen=True)
class Espace:
    nom: str
    primaires: tuple          # ((xr, yr), (xg, yg), (xb, yb))
    blanc: str                # clé de BLANCS
    transfert: str            # clé de _TRANSFERTS


ESPACES = {
    "srgb": Espace("sRGB (IEC 61966-2-1)", ((0.64, 0.33), (0.30, 0.60), (0.15, 0.06)), "D65", "srgb"),
    "display_p3": Espace("Display P3", ((0.680, 0.320), (0.265, 0.690), (0.150, 0.060)), "D65", "srgb"),
    "adobe_rgb": Espace("Adobe RGB (1998)", ((0.64, 0.33), (0.21, 0.71), (0.15, 0.06)), "D65", "gamma_2_2"),
    "rec2020": Espace("Rec.2020", ((0.708, 0.292), (0.170, 0.797), (0.131, 0.046)), "D65", "lineaire"),
    "prophoto": Espace("ProPhoto / ROMM", ((0.7347, 0.2653), (0.1596, 0.8404), (0.0366, 0.0001)), "D50", "romm"),
}
TRAVAIL = "rec2020"           # espace de travail : primaires Rec.2020, D65, linéaire


def _xyz(xy) -> np.ndarray:
    x, y = xy
    return np.array([x / y, 1.0, (1.0 - x - y) / y], dtype=np.float64)


@lru_cache(maxsize=None)
def matrice_rgb_xyz(espace: str) -> np.ndarray:
    """RGB linéaire -> XYZ (Y du blanc = 1), au blanc propre de l'espace."""
    definition = ESPACES[espace]
    primaires = np.stack([_xyz(xy) for xy in definition.primaires], axis=1)
    gains = np.linalg.solve(primaires, _xyz(BLANCS[definition.blanc]))
    return primaires * gains


_BRADFORD = np.array([[0.8951, 0.2664, -0.1614], [-0.7502, 1.7135, 0.0367], [0.0389, -0.0685, 1.0296]])


@lru_cache(maxsize=None)
def adaptation(blanc_source: str, blanc_cible: str) -> np.ndarray:
    """Adaptation chromatique de Bradford (XYZ -> XYZ) ; identité si les blancs sont les mêmes."""
    if blanc_source == blanc_cible:
        return np.eye(3)
    source, cible = _BRADFORD @ _xyz(BLANCS[blanc_source]), _BRADFORD @ _xyz(BLANCS[blanc_cible])
    return np.linalg.inv(_BRADFORD) @ np.diag(cible / source) @ _BRADFORD


@lru_cache(maxsize=None)
def matrice(source: str, cible: str) -> np.ndarray:
    """RGB linéaire `source` -> RGB linéaire `cible` (float64 ; les appelants la passent en float32)."""
    if source == cible:
        return np.eye(3)
    vers_xyz = adaptation(ESPACES[source].blanc, ESPACES[cible].blanc) @ matrice_rgb_xyz(source)
    return np.linalg.inv(matrice_rgb_xyz(cible)) @ vers_xyz


def appliquer_matrice(image: np.ndarray, m: np.ndarray) -> np.ndarray:
    return image @ np.asarray(m, dtype=image.dtype).T


def coefficients_luminance(espace: str = TRAVAIL) -> np.ndarray:
    """Poids de la luminance relative Y pour un RGB LINÉAIRE de cet espace."""
    return matrice_rgb_xyz(espace)[1]


def luminance(image: np.ndarray, espace: str = TRAVAIL) -> np.ndarray:
    return image @ coefficients_luminance(espace).astype(image.dtype)


# --- fonctions de transfert (encodé <-> linéaire), impaires : f(-x) = -f(x) ---------------------------------

def _impaire(fonction):
    def enveloppe(valeurs):
        valeurs = np.asarray(valeurs)
        return np.sign(valeurs) * fonction(np.abs(valeurs))
    return enveloppe


@_impaire
def _srgb_decoder(v):
    return np.where(v <= 0.04045, v / 12.92, ((v + 0.055) / 1.055) ** 2.4)


@_impaire
def _srgb_encoder(lin):
    return np.where(lin <= 0.0031308, lin * 12.92, 1.055 * lin ** (1 / 2.4) - 0.055)


@_impaire
def _romm_decoder(v):
    return np.where(v < 16 / 512, v / 16, v ** 1.8)


@_impaire
def _romm_encoder(lin):
    return np.where(lin < 1 / 512, lin * 16, lin ** (1 / 1.8))


_GAMMA_ADOBE = 563 / 256      # 2,19921875 : valeur exacte de la spécification Adobe RGB (1998)
_TRANSFERTS = {
    "lineaire": (lambda v: np.asarray(v), lambda lin: np.asarray(lin)),
    "srgb": (_srgb_decoder, _srgb_encoder),
    "romm": (_romm_decoder, _romm_encoder),
    "gamma_2_2": (_impaire(lambda v: v ** _GAMMA_ADOBE), _impaire(lambda lin: lin ** (1 / _GAMMA_ADOBE))),
}


def decoder(valeurs, transfert: str):
    """Valeurs encodées -> linéaire."""
    return _TRANSFERTS[transfert][0](valeurs)


def encoder(lineaire, transfert: str):
    """Linéaire -> valeurs encodées (non bornées : l'écrêtage est décidé par l'appelant)."""
    return _TRANSFERTS[transfert][1](lineaire)


def vers_travail(image_encodee: np.ndarray, espace: str = "srgb") -> np.ndarray:
    """Image encodée (float, 1.0 = blanc) d'un espace d'entrée -> linéaire scène dans l'espace de travail."""
    lineaire = decoder(np.asarray(image_encodee, dtype=np.float32), ESPACES[espace].transfert)
    return appliquer_matrice(lineaire.astype(np.float32), matrice(espace, TRAVAIL))


def depuis_travail(image: np.ndarray, espace: str = "srgb", ecreter: bool = True) -> np.ndarray:
    """Linéaire de travail -> valeurs encodées de l'espace de sortie.

    `ecreter=True` borne le LINÉAIRE de sortie à [0, 1] canal par canal (écrêtage de gamut et de hautes
    lumières, explicite : c'est la seule transformation de sortie disponible à ce jour, pas un rendu de gamut)."""
    lineaire = appliquer_matrice(np.asarray(image, dtype=np.float32), matrice(TRAVAIL, espace))
    if ecreter:
        lineaire = np.clip(lineaire, 0.0, 1.0)
    return encoder(lineaire, ESPACES[espace].transfert).astype(np.float32)


def quantifier(encodee: np.ndarray, bits: int = 8) -> np.ndarray:
    """Valeurs encodées [0, 1] -> entiers (arrondi au plus proche, sans tramage)."""
    maximum = (1 << bits) - 1
    return np.rint(np.clip(encodee, 0.0, 1.0) * maximum).astype(np.uint8 if bits <= 8 else np.uint16)


# --- log Cineon et densité ---------------------------------------------------------------------------------

CINEON_BLANC, CINEON_NOIR = 685, 95        # codes 10 bits du blanc de référence (90 %) et du noir
CINEON_PAS = 300.0                         # 0,002 de densité par code / gamma négatif 0,6 = 1 / 300 décade par code
_CINEON_DECALAGE = 10.0 ** ((CINEON_NOIR - CINEON_BLANC) / CINEON_PAS)


def cineon_vers_lineaire(code):
    """Code Cineon 10 bits (0-1023, flottant accepté) -> linéaire, 685 -> 1.0, 95 -> 0.0 (conversion Kodak)."""
    code = np.asarray(code, dtype=np.float64)
    return (10.0 ** ((code - CINEON_BLANC) / CINEON_PAS) - _CINEON_DECALAGE) / (1.0 - _CINEON_DECALAGE)


def lineaire_vers_cineon(lineaire):
    """Inverse de `cineon_vers_lineaire` ; le linéaire sous le noir du code 0 est borné à ce code (documenté)."""
    lineaire = np.asarray(lineaire, dtype=np.float64)
    plancher = 10.0 ** (-CINEON_BLANC / CINEON_PAS)
    return CINEON_BLANC + CINEON_PAS * np.log10(np.maximum(
        lineaire * (1.0 - _CINEON_DECALAGE) + _CINEON_DECALAGE, plancher))


def densite(transmittance):
    return -np.log10(np.asarray(transmittance, dtype=np.float64))


def transmittance(d):
    return 10.0 ** (-np.asarray(d, dtype=np.float64))
