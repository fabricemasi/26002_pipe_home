import _isolate  # noqa: F401 -- aucune ecriture dans les reglages reels
"""Contrat colorimetrique du moteur photo (`fm_photo/couleur.py`) : matrices calculees, transferts, pas d'ecretage
implicite, log Cineon. Valeurs de controle = normes publiees, pas des sorties du code."""
import unittest

import numpy as np

from fm_photo import couleur


class MatricesTest(unittest.TestCase):
    def test_srgb_vers_xyz_est_la_matrice_de_la_norme(self):
        # IEC 61966-2-1, matrice sRGB lineaire -> XYZ (D65), 4 decimales.
        norme = np.array([[0.4124, 0.3576, 0.1805], [0.2126, 0.7152, 0.0722], [0.0193, 0.1192, 0.9505]])
        np.testing.assert_allclose(couleur.matrice_rgb_xyz("srgb"), norme, atol=6e-5)

    def test_luminance_rec2020_est_celle_de_la_norme(self):
        # UIT-R BT.2020 : Y = 0,2627 R + 0,6780 G + 0,0593 B.
        np.testing.assert_allclose(couleur.coefficients_luminance("rec2020"), [0.2627, 0.6780, 0.0593], atol=5e-5)

    def test_le_blanc_reste_blanc_d_un_espace_a_l_autre(self):
        for source in couleur.ESPACES:
            for cible in couleur.ESPACES:
                np.testing.assert_allclose(couleur.matrice(source, cible) @ np.ones(3), np.ones(3), atol=1e-12,
                                           err_msg=f"{source} -> {cible}")

    def test_aller_retour_est_l_identite(self):
        for espace in couleur.ESPACES:
            produit = couleur.matrice(espace, couleur.TRAVAIL) @ couleur.matrice(couleur.TRAVAIL, espace)
            np.testing.assert_allclose(produit, np.eye(3), atol=1e-12)

    def test_adaptation_seulement_si_les_blancs_different(self):
        np.testing.assert_array_equal(couleur.adaptation("D65", "D65"), np.eye(3))
        d50 = couleur.adaptation("D65", "D50") @ couleur._xyz(couleur.BLANCS["D65"])
        np.testing.assert_allclose(d50, couleur._xyz(couleur.BLANCS["D50"]), atol=1e-12)


class TransfertsTest(unittest.TestCase):
    def test_points_de_la_norme_srgb(self):
        self.assertAlmostEqual(float(couleur.decoder(0.04045, "srgb")), 0.04045 / 12.92, places=9)
        self.assertAlmostEqual(float(couleur.encoder(0.18, "srgb")), 0.4614, places=3)   # gris 18 % ~ 118 / 255
        self.assertAlmostEqual(float(couleur.encoder(1.0, "srgb")), 1.0, places=9)

    def test_aller_retour_y_compris_hors_bornes(self):
        valeurs = np.linspace(-0.5, 4.0, 181)
        for transfert in couleur._TRANSFERTS:
            np.testing.assert_allclose(couleur.decoder(couleur.encoder(valeurs, transfert), transfert), valeurs,
                                       atol=1e-9, err_msg=transfert)

    def test_negatifs_par_symetrie_sans_nan(self):
        for transfert in couleur._TRANSFERTS:
            self.assertAlmostEqual(float(couleur.encoder(-0.3, transfert)), -float(couleur.encoder(0.3, transfert)))

    def test_continuite_au_raccord_des_morceaux(self):
        for transfert, seuil in (("srgb", 0.0031308), ("romm", 1 / 512)):
            avant, apres = couleur.encoder(np.array([seuil * (1 - 1e-6), seuil * (1 + 1e-6)]), transfert)
            self.assertLess(abs(float(apres - avant)), 1e-4, transfert)


class TravailTest(unittest.TestCase):
    def test_gris_srgb_reste_neutre_et_lineaire(self):
        gris = couleur.vers_travail(np.full((2, 2, 3), 0.5, dtype=np.float32), "srgb")
        self.assertEqual(gris.dtype, np.float32)
        np.testing.assert_allclose(gris, 0.21404, atol=2e-5)                 # (0,5 + 0,055 / 1,055) ^ 2,4

    def test_aller_retour_srgb_sous_un_quart_de_code_8_bits(self):
        rng = np.random.default_rng(7)
        image = rng.random((32, 32, 3), dtype=np.float32)
        retour = couleur.depuis_travail(couleur.vers_travail(image, "srgb"), "srgb")
        self.assertLess(float(np.abs(retour - image).max()), 0.25 / 255)
        np.testing.assert_array_equal(couleur.quantifier(retour), couleur.quantifier(image))

    def test_pas_d_ecretage_implicite(self):
        # Vert pur Rec.2020, deux fois le blanc : hors gamut sRGB (negatifs) et hautes lumieres (> 1).
        image = np.array([[[0.0, 2.0, 0.0]]], dtype=np.float32)
        libre = couleur.depuis_travail(image, "srgb", ecreter=False)
        self.assertLess(float(libre.min()), 0.0)
        self.assertGreater(float(libre.max()), 1.0)
        borne = couleur.depuis_travail(image, "srgb")                         # ecretage demande, nomme
        self.assertEqual(float(borne.min()), 0.0)
        self.assertAlmostEqual(float(borne.max()), 1.0, places=6)

    def test_quantification_arrondit_au_plus_proche(self):
        np.testing.assert_array_equal(couleur.quantifier(np.array([0.0, 0.5 / 255 - 1e-6, 0.6 / 255, 1.0, 1.5])),
                                      [0, 0, 1, 255, 255])
        self.assertEqual(couleur.quantifier(np.array([1.0]), 16).dtype, np.uint16)
        self.assertEqual(int(couleur.quantifier(np.array([1.0]), 16)[0]), 65535)


class CineonTest(unittest.TestCase):
    def test_points_de_reference(self):
        self.assertAlmostEqual(float(couleur.cineon_vers_lineaire(685)), 1.0, places=12)
        self.assertAlmostEqual(float(couleur.cineon_vers_lineaire(95)), 0.0, places=12)
        # 90 codes = 0,18 de densite / 0,6 = 0,3 decade = un diaphragme (au decalage du noir pres).
        rapport = (couleur.cineon_vers_lineaire(685) + 0) / couleur.cineon_vers_lineaire(595)
        self.assertAlmostEqual(float(rapport), 2.0, delta=0.03)

    def test_aller_retour_et_monotonie(self):
        codes = np.arange(0, 1024, dtype=np.float64)
        lineaire = couleur.cineon_vers_lineaire(codes)
        self.assertTrue(np.all(np.diff(lineaire) > 0))
        np.testing.assert_allclose(couleur.lineaire_vers_cineon(lineaire), codes, atol=1e-6)

    def test_densite_et_transmittance(self):
        np.testing.assert_allclose(couleur.densite([1.0, 0.1, 0.01]), [0.0, 1.0, 2.0], atol=1e-12)
        np.testing.assert_allclose(couleur.transmittance(couleur.densite(0.37)), 0.37, atol=1e-12)


if __name__ == "__main__":
    unittest.main()
