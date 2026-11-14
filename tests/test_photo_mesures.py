import _isolate  # noqa: F401 -- aucune ecriture dans les reglages reels
"""Mesures de comparaison (`fm_photo/mesures.py`). Delta E 2000 controle sur les paires d'essai publiees par
Sharma, Wu et Dalal (2005) ; CIELAB sur ses points de definition."""
import unittest

import numpy as np

from fm_photo import couleur, mesures

# (L1, a1, b1), (L2, a2, b2), Delta E 2000 publie.
SHARMA = [((50.0, 2.6772, -79.7751), (50.0, 0.0, -82.7485), 2.0425),
          ((50.0, 3.1571, -77.2803), (50.0, 0.0, -82.7485), 2.8615),
          ((50.0, 2.8361, -74.0200), (50.0, 0.0, -82.7485), 3.4412),
          ((50.0, -1.3802, -84.2814), (50.0, 0.0, -82.7485), 1.0000),
          ((50.0, 2.5, 0.0), (50.0, 0.0, -2.5), 4.3065),
          ((50.0, 2.5, 0.0), (73.0, 25.0, -18.0), 27.1492),
          ((60.2574, -34.0099, 36.2677), (60.4626, -34.1751, 39.4387), 1.2644),
          ((2.0776, 0.0795, -1.1350), (0.9033, -0.0636, -0.5514), 0.9082)]


class DeltaETest(unittest.TestCase):
    def test_paires_publiees(self):
        for lab_1, lab_2, attendu in SHARMA:
            self.assertAlmostEqual(float(mesures.delta_e_2000(np.array(lab_1), np.array(lab_2))), attendu, places=4,
                                   msg=str(lab_1))

    def test_symetrique_et_nul_sur_soi_meme(self):
        rng = np.random.default_rng(4)
        a = rng.uniform([0, -80, -80], [100, 80, 80], (200, 3))
        b = rng.uniform([0, -80, -80], [100, 80, 80], (200, 3))
        np.testing.assert_allclose(mesures.delta_e_2000(a, b), mesures.delta_e_2000(b, a), atol=1e-10)
        np.testing.assert_array_equal(mesures.delta_e_2000(a, a), 0.0)


class LabTest(unittest.TestCase):
    def test_blanc_gris_noir(self):
        np.testing.assert_allclose(mesures.vers_lab(np.ones(3)), [100.0, 0.0, 0.0], atol=1e-9)
        np.testing.assert_allclose(mesures.vers_lab(np.zeros(3)), [0.0, 0.0, 0.0], atol=1e-9)
        gris = mesures.vers_lab(np.full(3, 0.18))
        self.assertAlmostEqual(float(gris[0]), 49.496, places=2)                 # L* du gris 18 %
        np.testing.assert_allclose(gris[1:], 0.0, atol=1e-9)

    def test_rouge_srgb(self):
        # sRGB (1, 0, 0) sous D65 : L* 53,24 ; a* 80,09 ; b* 67,20 (valeurs classiques a D65).
        rouge = couleur.vers_travail(np.array([[[1.0, 0.0, 0.0]]]), "srgb")
        np.testing.assert_allclose(mesures.vers_lab(rouge)[0, 0], [53.24, 80.09, 67.20], atol=0.05)

    def test_negatifs_sans_nan(self):
        self.assertTrue(np.all(np.isfinite(mesures.vers_lab(np.array([-0.2, 0.5, -0.01])))))


class ComparerTest(unittest.TestCase):
    def test_statistiques_et_seuils(self):
        image = np.full((10, 10, 3), 0.18)
        autre = image.copy()
        autre[0, 0] = (0.30, 0.18, 0.18)                                          # un pixel sur cent s'ecarte
        ecart = mesures.comparer(image, autre)
        self.assertEqual((ecart.mediane, ecart.pixels), (0.0, 100))
        self.assertEqual(ecart.p95, 0.0)
        self.assertGreater(ecart.maximum, 10.0)
        self.assertFalse(ecart.tient(1.0, 2.5, 5.0))                              # le pire cas compte
        self.assertTrue(mesures.comparer(image, image).tient(1.0, 2.5, 5.0))
        with self.assertRaises(ValueError):
            mesures.comparer(image, image[:5])

    def test_un_tiers_de_diaphragme_se_voit(self):
        gris = np.full((4, 4, 3), 0.18)
        ecart = mesures.comparer(gris, gris * 2 ** (1 / 3))
        self.assertGreater(ecart.mediane, 2.5)                                    # nettement au-dela des seuils


class MiresTest(unittest.TestCase):
    def test_mire_tonale_par_tiers_de_diaphragme(self):
        from fm_photo import mires
        image, pastilles = mires.mire_tonale()
        valeurs = mires.attendues(pastilles)
        self.assertEqual(len(pastilles), 38)
        np.testing.assert_allclose(valeurs[0], 1.0)
        np.testing.assert_allclose(np.log2(valeurs[:-1, 0][:-1] / valeurs[:-1, 0][1:]), 1 / 3, atol=1e-12)
        np.testing.assert_allclose(valeurs[-1], 0.18)
        np.testing.assert_allclose(mires.lire_pastilles(image, pastilles), valeurs, rtol=1e-6)

    def test_mire_couleurs_encodable_en_srgb_sans_ecretage(self):
        from fm_photo import mires
        image, pastilles = mires.mire_couleurs()
        self.assertGreater(len(pastilles), 60)
        libre = couleur.depuis_travail(image, "srgb", ecreter=False)
        self.assertGreaterEqual(float(libre.min()), -1e-6)
        self.assertLessEqual(float(libre.max()), 1.0 + 1e-6)

    def test_fichier_relu_identique_aux_valeurs_declarees(self):
        """La mire ecrite en TIFF 16 bits puis relue comme une source : ecart tres sous les seuils du protocole."""
        import os
        import sys
        import tempfile
        from pathlib import Path
        os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
        from PySide6.QtWidgets import QApplication
        _app = QApplication.instance() or QApplication([])
        sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "tools"))
        import mires_photo
        from fm_photo import mires, sources
        with tempfile.TemporaryDirectory() as temp:
            ecrits = mires_photo.ecrire(Path(temp))
            self.assertEqual([chemin.name for chemin in ecrits],
                             ["mire_tonale.tif", "mire_tonale.json", "mire_couleurs.tif", "mire_couleurs.json"])
            with self.assertRaises(SystemExit):
                mires_photo.ecrire(Path(temp))                                    # rien n'est remplace
            for nom, (image, pastilles) in (("mire_tonale", mires.mire_tonale()),
                                            ("mire_couleurs", mires.mire_couleurs())):
                relue = sources.charger(Path(temp) / f"{nom}.tif")
                self.assertIn("sRGB", relue.provenance)
                lues = mires.lire_pastilles(relue.pixels, pastilles)
                ecart = mesures.delta_e_2000(mesures.vers_lab(lues), mesures.vers_lab(mires.attendues(pastilles)))
                self.assertLess(float(ecart.max()), 0.05, nom)


if __name__ == "__main__":
    unittest.main()
