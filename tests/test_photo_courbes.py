import _isolate  # noqa: F401 -- aucune ecriture dans les reglages reels
"""Courbes monotones (`fm_photo/courbes.py`) : passe par les points, jamais de depassement, prolongement explicite.
La courbe d'essai a la FORME d'une courbe caracteristique (pied, partie droite, epaule) ; ce n'est la donnee
d'aucun film."""
import unittest

import numpy as np

from fm_photo.courbes import CourbeMonotone, gamma

LOG_H = np.array([-3.0, -2.5, -2.0, -1.5, -1.0, -0.5, 0.0, 0.5, 1.0])
DENSITE = np.array([0.10, 0.11, 0.18, 0.45, 0.95, 1.45, 1.90, 2.15, 2.20])       # pied, droite, epaule


class CourbeMonotoneTest(unittest.TestCase):
    def test_passe_par_les_points(self):
        courbe = CourbeMonotone(LOG_H, DENSITE)
        np.testing.assert_allclose(courbe(LOG_H), DENSITE, atol=1e-12)

    def test_monotone_et_sans_depassement_entre_les_points(self):
        courbe = CourbeMonotone(LOG_H, DENSITE)
        fin = np.linspace(-3.0, 1.0, 40001)
        valeurs = courbe(fin)
        self.assertTrue(np.all(np.diff(valeurs) >= -1e-12))
        self.assertGreaterEqual(float(valeurs.min()), 0.10 - 1e-12)                # jamais sous D-min
        self.assertLessEqual(float(valeurs.max()), 2.20 + 1e-12)                   # jamais au-dessus de D-max
        self.assertTrue(np.all(courbe.derivee(fin) >= -1e-9))

    def test_palier_et_extremum_conserves(self):
        courbe = CourbeMonotone([0, 1, 2, 3, 4], [0, 1, 1, 1, 2])
        np.testing.assert_allclose(courbe(np.linspace(1, 3, 101)), 1.0, atol=1e-12)   # le palier reste plat
        bosse = CourbeMonotone([0, 1, 2], [0, 1, 0])
        self.assertLessEqual(float(bosse(np.linspace(0, 2, 1001)).max()), 1.0 + 1e-12)

    def test_une_droite_reste_une_droite(self):
        courbe = CourbeMonotone([0, 1, 3, 7], [1, 3, 7, 15], "lineaire")
        x = np.linspace(-2, 10, 121)
        np.testing.assert_allclose(courbe(x), 2 * x + 1, atol=1e-12)
        np.testing.assert_allclose(courbe.derivee(x), 2.0, atol=1e-12)

    def test_continuite_de_la_pente_aux_noeuds(self):
        courbe = CourbeMonotone(LOG_H, DENSITE)
        for noeud in LOG_H[1:-1]:
            avant, apres = courbe.derivee(noeud - 1e-9), courbe.derivee(noeud + 1e-9)
            self.assertAlmostEqual(float(avant), float(apres), places=6)

    def test_prolongement_explicite(self):
        constante = CourbeMonotone(LOG_H, DENSITE)
        np.testing.assert_allclose(constante([-9.0, 5.0]), [0.10, 2.20], atol=1e-12)
        np.testing.assert_array_equal(constante.derivee([-9.0, 5.0]), [0.0, 0.0])
        lineaire = CourbeMonotone([0, 1, 2], [0, 1, 4], "lineaire")
        self.assertAlmostEqual(float(lineaire(3.0)), 4.0 + float(lineaire.derivee(2.0)), places=12)
        with self.assertRaises(ValueError):
            CourbeMonotone(LOG_H, DENSITE, "devine")

    def test_reciproque(self):
        courbe = CourbeMonotone(LOG_H[1:-1], DENSITE[1:-1])                         # partie strictement croissante
        x = np.linspace(-2.4, 0.4, 500)
        np.testing.assert_allclose(courbe.inverse()(courbe(x)), x, atol=2e-4)
        with self.assertRaises(ValueError):
            CourbeMonotone([0, 1, 2], [0, 1, 1]).inverse()

    def test_gamma_de_la_partie_droite(self):
        courbe = CourbeMonotone(LOG_H, DENSITE)
        self.assertAlmostEqual(gamma(courbe, -1.5, -0.5), 1.0, places=12)          # (1,45 - 0,45) / 1 decade

    def test_donnees_invalides_refusees(self):
        for x, y in (([0], [0]), ([0, 0, 1], [0, 1, 2]), ([0, 2, 1], [0, 1, 2]), ([0, 1], [0, 1, 2])):
            with self.assertRaises(ValueError):
                CourbeMonotone(x, y)


if __name__ == "__main__":
    unittest.main()
