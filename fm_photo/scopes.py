"""Scopes du moteur photo : calculs de RÉFÉRENCE (numpy, sans Qt) sur les vrais pixels, à un point déclaré.

Deux points de mesure, jamais mélangés :
- « affichage » : valeurs ENCODÉES pour la sortie (`couleur.depuis_travail(..., ecreter=False)`), 1.0 = blanc de
  l'espace de sortie ; histogramme, forme d'onde, parade et vectorscope s'y lisent. La luma est Y' de la Rec.709
  (0,2126 R' + 0,7152 G' + 0,0722 B', sur valeurs encodées, comme un scope vidéo), pas une luminance ;
- « travail » : linéaire scène Rec.2020 D65 ; le diagramme CIE xy s'y calcule (XYZ exact du modèle RGB).
Les valeurs hors de [0, 1] ne sont pas écrêtées en silence : elles sont comptées à part (`sous`, `sur`) ; les
pixels sans chromaticité définie (X + Y + Z <= 0) sont comptés dans `exclus`.

Échantillonnage : `pas` = 1 pixel sur `pas` dans chaque direction ; `Mesure.exhaustif` n'est vrai que pour `pas` = 1 :
un scope échantillonné est un aperçu, pas une mesure de tous les pixels (à dire dans l'interface). Les calculs sont
lancés hors du fil de l'interface par l'appelant (résultats périmés abandonnés, comme `rendu.py`)."""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from fm_photo import couleur

LUMA_709 = np.array([0.2126, 0.7152, 0.0722], dtype=np.float32)
CANAUX = {"r": 0, "v": 1, "b": 2}
XY_ETENDUE = ((0.0, 0.8), (0.0, 0.9))            # étendue du diagramme CIE 1931 xy


@dataclass
class Mesure:
    donnees: np.ndarray          # comptes (entiers)
    point: str                   # « affichage » ou « travail »
    pas: int                     # échantillonnage : 1 pixel sur `pas`
    pixels: int                  # pixels mesurés
    sous: int = 0                # valeurs < 0 (comptées dans la première classe)
    sur: int = 0                 # valeurs > 1 (comptées dans la dernière classe)
    exclus: int = 0              # pixels sans valeur définie pour ce scope

    @property
    def exhaustif(self) -> bool:
        return self.pas == 1


def _pris(image: np.ndarray, pas: int) -> np.ndarray:
    return image[::pas, ::pas] if pas > 1 else image


def luma(encodee: np.ndarray) -> np.ndarray:
    return encodee @ LUMA_709


def _classes(valeurs: np.ndarray, niveaux: int) -> np.ndarray:
    return np.clip(np.floor(valeurs * niveaux), 0, niveaux - 1).astype(np.intp)


def _signal(encodee: np.ndarray, canal: str) -> np.ndarray:
    return luma(encodee) if canal == "luma" else encodee[..., CANAUX[canal]]


def histogramme(encodee: np.ndarray, niveaux: int = 256, pas: int = 1) -> Mesure:
    """Comptes (4, niveaux) : R', V', B', luma Y'. Classe k = [k / niveaux, (k + 1) / niveaux[ ; 1.0 dans la dernière."""
    prise = _pris(encodee, pas)
    signaux = [prise[..., 0], prise[..., 1], prise[..., 2], luma(prise)]
    comptes = np.stack([np.bincount(_classes(signal, niveaux).ravel(), minlength=niveaux) for signal in signaux])
    return Mesure(comptes, "affichage", pas, prise.shape[0] * prise.shape[1],
                  sous=int(sum((signal < 0).sum() for signal in signaux[:3])),
                  sur=int(sum((signal > 1).sum() for signal in signaux[:3])))


def forme_d_onde(encodee: np.ndarray, colonnes: int = 256, niveaux: int = 256, canal: str = "luma",
                 pas: int = 1) -> Mesure:
    """Comptes (niveaux, colonnes) : pour chaque bande verticale de l'image, la répartition des niveaux du
    signal (`luma`, `r`, `v`, `b`). La ligne 0 est le niveau 0 (à dessiner en bas)."""
    prise = _pris(encodee, pas)
    signal = _signal(prise, canal)
    hauteur, largeur = signal.shape
    colonnes = min(colonnes, largeur)
    bandes = np.broadcast_to((np.arange(largeur) * colonnes // largeur)[None, :], signal.shape)
    index = _classes(signal, niveaux) * colonnes + bandes
    comptes = np.bincount(index.ravel(), minlength=niveaux * colonnes).reshape(niveaux, colonnes)
    return Mesure(comptes, "affichage", pas, hauteur * largeur, sous=int((signal < 0).sum()),
                  sur=int((signal > 1).sum()))


def parade(encodee: np.ndarray, colonnes: int = 256, niveaux: int = 256, pas: int = 1) -> list:
    """Parade RVB : trois formes d'onde (R', V', B'), à poser côte à côte."""
    return [forme_d_onde(encodee, colonnes, niveaux, canal, pas) for canal in ("r", "v", "b")]


def cb_cr(encodee: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """Différences de couleur Rec.709 sur valeurs encodées : Cb = (B' - Y') / 1,8556, Cr = (R' - Y') / 1,5748,
    chacune dans [-0,5, 0,5] pour des valeurs dans [0, 1] ; un neutre donne (0, 0)."""
    y = luma(encodee)
    return (encodee[..., 2] - y) / np.float32(1.8556), (encodee[..., 0] - y) / np.float32(1.5748)


def vectorscope(encodee: np.ndarray, taille: int = 256, pas: int = 1) -> Mesure:
    """Comptes (taille, taille) : ligne = Cr (de -0,5 en haut du tableau à +0,5), colonne = Cb (de -0,5 à +0,5)."""
    prise = _pris(encodee, pas)
    cb, cr = cb_cr(prise)
    hors = (np.abs(cb) > 0.5) | (np.abs(cr) > 0.5)
    index = _classes(cr + 0.5, taille) * taille + _classes(cb + 0.5, taille)
    comptes = np.bincount(index.ravel(), minlength=taille * taille).reshape(taille, taille)
    return Mesure(comptes, "affichage", pas, prise.shape[0] * prise.shape[1], sur=int(hors.sum()))


def chromaticites(lineaire: np.ndarray) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """(x, y, défini) CIE 1931 d'une image en linéaire de travail ; `défini` est faux où X + Y + Z <= 0."""
    xyz = couleur.appliquer_matrice(np.asarray(lineaire, dtype=np.float32), couleur.matrice_rgb_xyz(couleur.TRAVAIL))
    somme = xyz.sum(axis=-1)
    defini = somme > 0
    diviseur = np.where(defini, somme, 1.0)
    return xyz[..., 0] / diviseur, xyz[..., 1] / diviseur, defini


def diagramme_xy(lineaire: np.ndarray, taille: int = 256, pas: int = 1) -> Mesure:
    """Comptes (taille, taille) sur `XY_ETENDUE` : ligne = y, colonne = x. Les chromaticités hors de l'étendue
    (couleurs non physiques d'un RGB négatif) sont comptées dans `sur`, pas rabattues sur le bord."""
    prise = _pris(lineaire, pas)
    x, y, defini = chromaticites(prise)
    (x0, x1), (y0, y1) = XY_ETENDUE
    dedans = defini & (x >= x0) & (x < x1) & (y >= y0) & (y < y1)
    colonne = ((x[dedans] - x0) / (x1 - x0) * taille).astype(np.intp)
    ligne = ((y[dedans] - y0) / (y1 - y0) * taille).astype(np.intp)
    comptes = np.bincount(ligne * taille + colonne, minlength=taille * taille).reshape(taille, taille)
    return Mesure(comptes, "travail", pas, prise.shape[0] * prise.shape[1], sur=int((defini & ~dedans).sum()),
                  exclus=int((~defini).sum()))
