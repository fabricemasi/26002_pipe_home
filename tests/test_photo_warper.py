import _isolate  # noqa: F401 -- aucune ecriture dans les reglages reels
"""Color Warper Teinte / Saturation (`fm_photo/warper.py`) : identite, noeuds, neutres, raccord des teintes,
continuite, replis. Valeurs Oklab de controle = celles publiees par l'auteur du modele."""
import unittest

import numpy as np

from fm_photo import couleur, operations, warper
from fm_photo.operations import Contexte

CHROMA = 0.4


def _maillage_agite(amplitude=0.02, graine=5, anneaux=4, teintes=12):
    rng = np.random.default_rng(graine)
    maillage = warper.maillage_nul(anneaux, teintes)
    maillage[1:] = rng.uniform(-amplitude, amplitude, maillage[1:].shape)
    return maillage


class OklabTest(unittest.TestCase):
    def test_valeurs_publiees(self):
        blanc = warper.vers_oklab(np.ones(3))
        np.testing.assert_allclose(blanc, [1.0, 0.0, 0.0], atol=2e-3)
        rouge = warper.vers_oklab(couleur.vers_travail(np.array([[[1.0, 0.0, 0.0]]]), "srgb"))[0, 0]
        np.testing.assert_allclose(rouge, [0.627955, 0.224863, 0.125846], atol=1e-3)

    def test_aller_retour_y_compris_negatifs(self):
        rng = np.random.default_rng(2)
        image = rng.uniform(-0.2, 3.0, (20, 20, 3))
        np.testing.assert_allclose(warper.depuis_oklab(warper.vers_oklab(image)), image, atol=1e-9)


class MaillageTest(unittest.TestCase):
    def test_maillage_nul_est_l_identite_exacte(self):
        image = np.random.default_rng(1).random((8, 8, 3), dtype=np.float32)
        nul = {"deplacements": warper.maillage_nul().tolist(), "chroma_max": CHROMA}
        connue = operations.definition("warper_teinte_saturation")
        self.assertIs(connue.appliquer(image, nul, Contexte()), image)
        self.assertIs(connue.appliquer(image, connue.defauts, Contexte()), image)
        self.assertEqual(operations.chaine([{"op": "warper_teinte_saturation", "params": {}}]), [])

    def test_un_point_sur_un_noeud_suit_exactement_le_noeud(self):
        maillage = warper.maillage_nul(4, 12)
        maillage[2, 3] = (0.03, -0.02)
        a, b = warper.noeud(2, 3, 4, 12, CHROMA)
        da, db = warper.deplacement(np.array([a]), np.array([b]), maillage, CHROMA)
        self.assertAlmostEqual(float(da[0]), 0.03, places=9)
        self.assertAlmostEqual(float(db[0]), -0.02, places=9)
        loin = warper.noeud(2, 9, 4, 12, CHROMA)                               # teinte opposee : rien ne bouge
        da, db = warper.deplacement(np.array([loin[0]]), np.array([loin[1]]), maillage, CHROMA)
        self.assertEqual((float(da[0]), float(db[0])), (0.0, 0.0))

    def test_les_neutres_restent_neutres_et_la_clarte_ne_change_pas(self):
        maillage = _maillage_agite(0.05)
        maillage[0] = 0.3                                                      # meme force : l'axe neutre est fixe
        gris = np.linspace(0.01, 4.0, 30)[:, None] * np.ones(3)
        params = {"deplacements": maillage.tolist(), "chroma_max": CHROMA}
        rendu = operations.definition("warper_teinte_saturation").appliquer(
            gris[None].astype(np.float32), params, Contexte())
        np.testing.assert_allclose(rendu[0], gris, rtol=2e-5, atol=1e-6)
        image = np.random.default_rng(3).random((16, 16, 3))
        avant = warper.vers_oklab(image)
        apres = warper.deformer(avant, maillage, CHROMA)
        np.testing.assert_array_equal(apres[..., 0], avant[..., 0])
        self.assertGreater(float(np.abs(apres[..., 1:] - avant[..., 1:]).max()), 1e-3)

    def test_continuite_au_raccord_des_teintes_et_a_l_axe_neutre(self):
        maillage = _maillage_agite(0.03)
        epsilon = 1e-7
        for rayon in (0.05, 0.17, 0.33, 0.39):
            avant = warper.deplacement(np.array([rayon * np.cos(-epsilon)]), np.array([rayon * np.sin(-epsilon)]),
                                       maillage, CHROMA)
            apres = warper.deplacement(np.array([rayon * np.cos(epsilon)]), np.array([rayon * np.sin(epsilon)]),
                                       maillage, CHROMA)
            self.assertLess(abs(float(avant[0][0] - apres[0][0])) + abs(float(avant[1][0] - apres[1][0])), 1e-6)
        angles = np.linspace(0, 2 * np.pi, 13)[:-1]
        da, db = warper.deplacement(1e-9 * np.cos(angles), 1e-9 * np.sin(angles), maillage, CHROMA)
        self.assertLess(float(np.abs(da).max() + np.abs(db).max()), 1e-8)      # tend vers 0 a l'axe, pour toute teinte

    def test_pas_de_saut_le_long_d_un_cercle_ni_d_un_rayon(self):
        maillage = _maillage_agite(0.03)
        angles = np.linspace(0, 2 * np.pi, 20001)
        for rayon in (0.1, 0.25, 0.4, 0.55):                                   # 0,55 : au-dela du dernier anneau
            da, db = warper.deplacement(rayon * np.cos(angles), rayon * np.sin(angles), maillage, CHROMA)
            self.assertLess(float(np.abs(np.diff(da)).max() + np.abs(np.diff(db)).max()), 2e-4)
            self.assertAlmostEqual(float(da[0]), float(da[-1]), places=9)      # le tour se referme
        rayons = np.linspace(0, 0.6, 20001)
        da, db = warper.deplacement(rayons * np.cos(1.0), rayons * np.sin(1.0), maillage, CHROMA)
        self.assertLess(float(np.abs(np.diff(da)).max() + np.abs(np.diff(db)).max()), 2e-4)
        self.assertAlmostEqual(float(da[-1]), float(da[np.searchsorted(rayons, CHROMA)]), places=4)

    def test_replis_detectes(self):
        self.assertEqual(warper.replis(warper.maillage_nul(), CHROMA), 0.0)
        self.assertEqual(warper.replis(_maillage_agite(0.01), CHROMA), 0.0)
        violent = warper.maillage_nul(4, 12)
        violent[2, 0] = (-0.5, 0.0)                                            # noeud pousse a travers le centre
        self.assertGreater(warper.replis(violent, CHROMA), 0.01)

    def test_saturation_d_une_teinte_les_autres_intactes(self):
        """Usage type : pousser le rouge vers l'exterieur (plus sature) sans toucher au vert oppose."""
        maillage = warper.maillage_nul(4, 12)
        teinte_rouge = int(round(np.degrees(np.arctan2(0.125846, 0.224863)) / 30.0)) % 12
        for anneau in (1, 2, 3, 4):
            a, b = warper.noeud(anneau, teinte_rouge, 4, 12, CHROMA)
            maillage[anneau, teinte_rouge] = (0.2 * a, 0.2 * b)                # +20 % de chroma sur ce rayon
        rouge = couleur.vers_travail(np.array([[[1.0, 0.0, 0.0]]]), "srgb").astype(np.float64)
        vert = couleur.vers_travail(np.array([[[0.0, 1.0, 0.0]]]), "srgb").astype(np.float64)
        def chroma(lineaire):
            lab = warper.deformer(warper.vers_oklab(lineaire), maillage, CHROMA)
            return float(np.hypot(lab[..., 1], lab[..., 2])[0, 0])
        sans = float(np.hypot(*warper.vers_oklab(rouge)[0, 0, 1:]))
        self.assertGreater(chroma(rouge), sans * 1.1)
        self.assertAlmostEqual(chroma(vert), float(np.hypot(*warper.vers_oklab(vert)[0, 0, 1:])), places=9)
        self.assertEqual(warper.replis(maillage, CHROMA), 0.0)


if __name__ == "__main__":
    unittest.main()
