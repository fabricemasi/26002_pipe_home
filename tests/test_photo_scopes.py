import _isolate  # noqa: F401 -- aucune ecriture dans les reglages reels
"""Scopes de reference (`fm_photo/scopes.py`) : vrais pixels, point de mesure declare, hors bornes comptes."""
import unittest

import numpy as np

from fm_photo import couleur, scopes


def _aplat(rvb, hauteur=8, largeur=16):
    return np.broadcast_to(np.asarray(rvb, dtype=np.float32), (hauteur, largeur, 3)).copy()


class HistogrammeTest(unittest.TestCase):
    def test_chaque_pixel_est_compte_une_fois_par_signal(self):
        rng = np.random.default_rng(1)
        image = rng.random((40, 60, 3), dtype=np.float32)
        mesure = scopes.histogramme(image)
        self.assertEqual(mesure.donnees.shape, (4, 256))
        np.testing.assert_array_equal(mesure.donnees.sum(axis=1), [2400] * 4)
        self.assertTrue(mesure.exhaustif)
        self.assertEqual((mesure.point, mesure.sous, mesure.sur), ("affichage", 0, 0))

    def test_classes_et_blanc_dans_la_derniere(self):
        mesure = scopes.histogramme(_aplat([0.0, 0.5, 1.0]))
        self.assertEqual(int(mesure.donnees[0, 0]), 128)
        self.assertEqual(int(mesure.donnees[1, 128]), 128)
        self.assertEqual(int(mesure.donnees[2, 255]), 128)
        luma = 0.7152 * 0.5 + 0.0722                                   # Y' Rec.709 de (0 ; 0,5 ; 1)
        self.assertEqual(int(mesure.donnees[3, int(luma * 256)]), 128)

    def test_hors_bornes_comptes_a_part_jamais_perdus(self):
        mesure = scopes.histogramme(_aplat([-0.2, 0.5, 1.4]))
        self.assertEqual((mesure.sous, mesure.sur), (128, 128))
        self.assertEqual(int(mesure.donnees[0, 0]), 128)
        self.assertEqual(int(mesure.donnees[2, 255]), 128)

    def test_echantillonnage_declare(self):
        mesure = scopes.histogramme(_aplat([0.5, 0.5, 0.5], 40, 60), pas=4)
        self.assertFalse(mesure.exhaustif)
        self.assertEqual((mesure.pas, mesure.pixels), (4, 150))
        self.assertEqual(int(mesure.donnees[0].sum()), 150)


class FormeDOndeTest(unittest.TestCase):
    def test_rampe_horizontale_donne_une_diagonale(self):
        rampe = np.linspace(0.0, 1.0, 256, dtype=np.float32)
        image = np.broadcast_to(rampe[None, :, None], (10, 256, 3)).copy()
        mesure = scopes.forme_d_onde(image, colonnes=256, niveaux=256)
        self.assertEqual(mesure.donnees.shape, (256, 256))
        np.testing.assert_array_equal(mesure.donnees.sum(axis=0), [10] * 256)      # chaque colonne : ses 10 pixels
        niveaux = mesure.donnees.argmax(axis=0)
        self.assertTrue(np.all(np.abs(niveaux - np.arange(256)) <= 1))

    def test_parade_separe_les_canaux(self):
        r, v, b = scopes.parade(_aplat([0.25, 0.5, 0.75]), colonnes=4, niveaux=4)
        self.assertEqual([int(m.donnees.argmax(axis=0)[0]) for m in (r, v, b)], [1, 2, 3])
        self.assertEqual(int(r.donnees.sum()), 128)


class VectorscopeTest(unittest.TestCase):
    def test_un_neutre_est_au_centre(self):
        for gris in (0.1, 0.5, 0.9):
            cb, cr = scopes.cb_cr(_aplat([gris] * 3))
            self.assertLess(float(np.abs(cb).max()), 1e-6)
            self.assertLess(float(np.abs(cr).max()), 1e-6)
        mesure = scopes.vectorscope(_aplat([0.5] * 3), taille=64)
        self.assertEqual(int(mesure.donnees[32, 32]), 128)

    def test_primaires_aux_valeurs_de_la_rec_709(self):
        # Rouge 100 % : Cr = +0,5 ; Cb = -0,2126 / 1,8556. Bleu 100 % : Cb = +0,5.
        cb, cr = scopes.cb_cr(_aplat([1.0, 0.0, 0.0]))
        self.assertAlmostEqual(float(cr[0, 0]), 0.5, places=4)
        self.assertAlmostEqual(float(cb[0, 0]), -0.2126 / 1.8556, places=5)
        cb, cr = scopes.cb_cr(_aplat([0.0, 0.0, 1.0]))
        self.assertAlmostEqual(float(cb[0, 0]), 0.5, places=4)
        self.assertEqual(scopes.vectorscope(_aplat([1.0, 0.0, 0.0])).sur, 0)

    def test_hors_gamut_compte(self):
        self.assertEqual(scopes.vectorscope(_aplat([1.6, -0.2, -0.2])).sur, 128)


class DiagrammeXyTest(unittest.TestCase):
    def test_blanc_et_primaires_de_l_espace_de_travail(self):
        x, y, defini = scopes.chromaticites(_aplat([0.7, 0.7, 0.7]))
        self.assertTrue(defini.all())
        self.assertAlmostEqual(float(x[0, 0]), 0.3127, places=4)                   # D65
        self.assertAlmostEqual(float(y[0, 0]), 0.3290, places=4)
        x, y, _ = scopes.chromaticites(_aplat([1.0, 0.0, 0.0]))
        self.assertAlmostEqual(float(x[0, 0]), 0.708, places=4)                    # rouge Rec.2020
        self.assertAlmostEqual(float(y[0, 0]), 0.292, places=4)

    def test_srgb_rouge_vu_depuis_le_travail(self):
        rouge = couleur.vers_travail(_aplat([1.0, 0.0, 0.0]), "srgb")
        x, y, _ = scopes.chromaticites(rouge)
        self.assertAlmostEqual(float(x[0, 0]), 0.64, places=3)
        self.assertAlmostEqual(float(y[0, 0]), 0.33, places=3)

    def test_noir_exclu_et_non_physique_compte(self):
        image = _aplat([0.0, 0.0, 0.0])
        image[0, 0] = (0.5, 0.5, 0.5)
        image[0, 1] = (-0.3, 0.0, 1.0)                                             # y negatif : hors du diagramme
        mesure = scopes.diagramme_xy(image, taille=128)
        self.assertEqual((mesure.point, mesure.exclus, mesure.sur), ("travail", 126, 1))
        self.assertEqual(int(mesure.donnees.sum()), 1)
        ligne, colonne = np.unravel_index(mesure.donnees.argmax(), mesure.donnees.shape)
        self.assertEqual((int(ligne), int(colonne)), (int(0.3290 / 0.9 * 128), int(0.3127 / 0.8 * 128)))


if __name__ == "__main__":
    unittest.main()
