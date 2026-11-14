"""Mesures de comparaison entre deux rendus (référence numpy, sans Qt) : CIELAB, Delta E 2000, statistiques.

Sert au banc comparatif (PIPE FMZ contre une référence identifiée : export Dehancer, FilmPack, JPEG boîtier) et à
la vérification des optimisations. Les deux images sont en LINÉAIRE DE TRAVAIL (même espace, mêmes dimensions) ;
CIELAB est calculé par rapport au blanc de travail D65 (pas d'adaptation vers D50 : on compare deux images vues
dans les mêmes conditions, pas des couleurs de surface normalisées). Delta E 2000 : formule CIE (Sharma, Wu, Dalal,
2005), vérifiée sur les paires d'essai publiées par ces auteurs. Les valeurs négatives (hors gamut) passent par la
branche linéaire de CIELAB, sans écrêtage.

Un Delta E mesure un écart de COULEUR pixel à pixel : il ne juge ni un grain, ni un halo (statistiques et spectres
spatiaux à part, au registre), ni l'équivalence perceptuelle d'images entières (évaluation humaine à part)."""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from fm_photo import couleur


def vers_lab(lineaire: np.ndarray) -> np.ndarray:
    """Linéaire de travail -> CIELAB (blanc D65 de l'espace de travail), float64."""
    xyz = np.asarray(lineaire, dtype=np.float64) @ couleur.matrice_rgb_xyz(couleur.TRAVAIL).T
    rapport = xyz / (couleur.matrice_rgb_xyz(couleur.TRAVAIL) @ np.ones(3))
    delta = 6.0 / 29.0
    f = np.where(rapport > delta ** 3, np.cbrt(np.maximum(rapport, 0.0)), rapport / (3 * delta ** 2) + 4.0 / 29.0)
    return np.stack([116.0 * f[..., 1] - 16.0, 500.0 * (f[..., 0] - f[..., 1]), 200.0 * (f[..., 1] - f[..., 2])],
                    axis=-1)


def delta_e_2000(lab_1: np.ndarray, lab_2: np.ndarray) -> np.ndarray:
    """Delta E CIEDE2000 (kL = kC = kH = 1) entre deux tableaux CIELAB de même forme."""
    lab_1, lab_2 = np.asarray(lab_1, dtype=np.float64), np.asarray(lab_2, dtype=np.float64)
    l1, a1, b1 = lab_1[..., 0], lab_1[..., 1], lab_1[..., 2]
    l2, a2, b2 = lab_2[..., 0], lab_2[..., 1], lab_2[..., 2]
    c_moyen = (np.hypot(a1, b1) + np.hypot(a2, b2)) / 2.0
    g = 0.5 * (1.0 - np.sqrt(c_moyen ** 7 / (c_moyen ** 7 + 25.0 ** 7)))
    a1p, a2p = (1.0 + g) * a1, (1.0 + g) * a2
    c1p, c2p = np.hypot(a1p, b1), np.hypot(a2p, b2)
    h1p = np.degrees(np.arctan2(b1, a1p)) % 360.0
    h2p = np.degrees(np.arctan2(b2, a2p)) % 360.0
    dlp, dcp = l2 - l1, c2p - c1p
    dhp = h2p - h1p
    dhp = np.where(dhp > 180.0, dhp - 360.0, np.where(dhp < -180.0, dhp + 360.0, dhp))
    dhp = np.where(c1p * c2p == 0.0, 0.0, dhp)
    dHp = 2.0 * np.sqrt(c1p * c2p) * np.sin(np.radians(dhp) / 2.0)
    lp, cp = (l1 + l2) / 2.0, (c1p + c2p) / 2.0
    somme = h1p + h2p
    hp = np.where(np.abs(h1p - h2p) <= 180.0, somme / 2.0,
                  np.where(somme < 360.0, (somme + 360.0) / 2.0, (somme - 360.0) / 2.0))
    hp = np.where(c1p * c2p == 0.0, somme, hp)
    t = (1.0 - 0.17 * np.cos(np.radians(hp - 30.0)) + 0.24 * np.cos(np.radians(2.0 * hp))
         + 0.32 * np.cos(np.radians(3.0 * hp + 6.0)) - 0.20 * np.cos(np.radians(4.0 * hp - 63.0)))
    d_theta = 30.0 * np.exp(-(((hp - 275.0) / 25.0) ** 2))
    rc = 2.0 * np.sqrt(cp ** 7 / (cp ** 7 + 25.0 ** 7))
    sl = 1.0 + 0.015 * (lp - 50.0) ** 2 / np.sqrt(20.0 + (lp - 50.0) ** 2)
    sc = 1.0 + 0.045 * cp
    sh = 1.0 + 0.015 * cp * t
    rt = -np.sin(np.radians(2.0 * d_theta)) * rc
    return np.sqrt((dlp / sl) ** 2 + (dcp / sc) ** 2 + (dHp / sh) ** 2 + rt * (dcp / sc) * (dHp / sh))


@dataclass
class Ecart:
    mediane: float
    p95: float
    p99: float
    maximum: float
    pixels: int

    def tient(self, mediane: float, p95: float, maximum: float) -> bool:
        """Vrai si l'écart respecte des seuils FIXÉS AVANT la calibration (voir fm_film_protocole.md)."""
        return self.mediane <= mediane and self.p95 <= p95 and self.maximum <= maximum


def comparer(lineaire_a: np.ndarray, lineaire_b: np.ndarray) -> Ecart:
    """Écart de couleur Delta E 2000 entre deux images en linéaire de travail, de mêmes dimensions."""
    if lineaire_a.shape != lineaire_b.shape:
        raise ValueError(f"Dimensions différentes : {lineaire_a.shape} et {lineaire_b.shape}")
    ecarts = delta_e_2000(vers_lab(lineaire_a), vers_lab(lineaire_b)).ravel()
    return Ecart(float(np.median(ecarts)), float(np.percentile(ecarts, 95)), float(np.percentile(ecarts, 99)),
                 float(ecarts.max()), int(ecarts.size))
