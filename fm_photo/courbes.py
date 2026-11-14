"""Courbes tabulées MONOTONES : socle des courbes de tonalité et des courbes caractéristiques (sans Qt).

Une courbe caractéristique de film ou de support de tirage (densité en fonction du logarithme de l'exposition :
pied, partie utile, épaule, D-min, D-max) est une donnée MESURÉE, tabulée. L'interpoler par une spline cubique
ordinaire crée des dépassements et des inversions entre les points ; ici l'interpolation est cubique d'Hermite à
pentes de Fritsch-Carlson (PCHIP, 1980) : elle passe par tous les points, reste C1, et ne dépasse JAMAIS entre deux
points (une donnée monotone donne une courbe monotone, sans oscillation).

Hors de l'étendue des données, rien n'est inventé en silence : `prolongement` est explicite — « constante »
(la courbe reste à sa valeur extrême : un support ne dépasse pas son D-max mesuré) ou « lineaire » (pente du bord).
Ce module ne contient AUCUNE donnée de film : les tables viennent de sources citées (`fm_film_references.md`)."""
from __future__ import annotations

import numpy as np


class CourbeMonotone:
    def __init__(self, x, y, prolongement: str = "constante"):
        self.x = np.asarray(x, dtype=np.float64)
        self.y = np.asarray(y, dtype=np.float64)
        if self.x.ndim != 1 or self.x.shape != self.y.shape or len(self.x) < 2:
            raise ValueError("Il faut au moins deux points (x, y).")
        if np.any(np.diff(self.x) <= 0):
            raise ValueError("Les abscisses doivent être strictement croissantes.")
        if prolongement not in ("constante", "lineaire"):
            raise ValueError(f"Prolongement inconnu : {prolongement}")
        self.prolongement = prolongement
        self.pentes = self._pentes()

    def _pentes(self) -> np.ndarray:
        """Pentes aux nœuds (Fritsch-Carlson) : moyenne harmonique pondérée des pentes des deux segments voisins,
        nulle si elles sont de signes contraires ou si l'une est nulle (extremum ou palier conservé)."""
        pas = np.diff(self.x)
        cordes = np.diff(self.y) / pas
        pentes = np.zeros_like(self.x)
        if len(self.x) == 2:
            pentes[:] = cordes[0]
            return pentes
        meme_sens = cordes[:-1] * cordes[1:] > 0
        poids_1, poids_2 = 2 * pas[1:] + pas[:-1], pas[1:] + 2 * pas[:-1]
        with np.errstate(divide="ignore", invalid="ignore"):
            harmonique = (poids_1 + poids_2) / (poids_1 / cordes[:-1] + poids_2 / cordes[1:])
        pentes[1:-1] = np.where(meme_sens, harmonique, 0.0)
        pentes[0] = self._bord(pas[0], pas[1], cordes[0], cordes[1])
        pentes[-1] = self._bord(pas[-1], pas[-2], cordes[-1], cordes[-2])
        return pentes

    @staticmethod
    def _bord(pas_0, pas_1, corde_0, corde_1) -> float:
        """Pente d'extrémité à trois points, bornée pour garder la forme (comme l'algorithme PCHIP de référence)."""
        pente = ((2 * pas_0 + pas_1) * corde_0 - pas_0 * corde_1) / (pas_0 + pas_1)
        if np.sign(pente) != np.sign(corde_0):
            return 0.0
        if np.sign(corde_0) != np.sign(corde_1) and abs(pente) > 3 * abs(corde_0):
            return 3 * corde_0
        return float(pente)

    def _segments(self, valeurs: np.ndarray):
        index = np.clip(np.searchsorted(self.x, valeurs, side="right") - 1, 0, len(self.x) - 2)
        pas = self.x[index + 1] - self.x[index]
        return index, pas, (valeurs - self.x[index]) / pas

    def __call__(self, valeurs) -> np.ndarray:
        valeurs = np.asarray(valeurs, dtype=np.float64)
        dedans = np.clip(valeurs, self.x[0], self.x[-1])
        index, pas, t = self._segments(dedans)
        t2, t3 = t * t, t * t * t
        resultat = ((2 * t3 - 3 * t2 + 1) * self.y[index] + (t3 - 2 * t2 + t) * pas * self.pentes[index]
                    + (-2 * t3 + 3 * t2) * self.y[index + 1] + (t3 - t2) * pas * self.pentes[index + 1])
        if self.prolongement == "lineaire":
            resultat = resultat + np.where(valeurs < self.x[0], (valeurs - self.x[0]) * self.pentes[0], 0.0)
            resultat = resultat + np.where(valeurs > self.x[-1], (valeurs - self.x[-1]) * self.pentes[-1], 0.0)
        return resultat

    def derivee(self, valeurs) -> np.ndarray:
        valeurs = np.asarray(valeurs, dtype=np.float64)
        index, pas, t = self._segments(np.clip(valeurs, self.x[0], self.x[-1]))
        t2 = t * t
        pente = ((6 * t2 - 6 * t) * self.y[index] / pas + (3 * t2 - 4 * t + 1) * self.pentes[index]
                 + (-6 * t2 + 6 * t) * self.y[index + 1] / pas + (3 * t2 - 2 * t) * self.pentes[index + 1])
        if self.prolongement == "constante":
            pente = np.where((valeurs < self.x[0]) | (valeurs > self.x[-1]), 0.0, pente)
        return pente

    def inverse(self, echantillons: int = 4097) -> "CourbeMonotone":
        """Courbe réciproque (y -> x), pour une courbe STRICTEMENT croissante ; tabulée finement puis réinterpolée
        (erreur d'aller-retour mesurée par les tests, pas une inversion analytique)."""
        x = np.linspace(self.x[0], self.x[-1], echantillons)
        y = self(x)
        if np.any(np.diff(y) <= 0):
            raise ValueError("La courbe n'est pas strictement croissante : pas de réciproque.")
        return CourbeMonotone(y, x, self.prolongement)


def gamma(courbe: CourbeMonotone, x_debut: float, x_fin: float) -> float:
    """Pente moyenne de la courbe entre deux abscisses : le « gamma » d'une courbe caractéristique quand x est
    le logarithme décimal de l'exposition et y la densité (à comparer à la valeur publiée par le fabricant)."""
    return float((courbe(x_fin) - courbe(x_debut)) / (x_fin - x_debut))
