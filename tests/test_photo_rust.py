import _isolate  # noqa: F401 -- aucune ecriture dans les reglages reels
"""Moteur Rust (`fm_photo_moteur`) contre la REFERENCE numpy : memes operations, ecart borne par les seuils fixes
d'avance dans docs/agents/fm_film_protocole.md (« verification d'une optimisation » : Delta E 2000 mediane 0,1,
95e centile 0,2, maximum 0,5). Saute si le moteur n'est pas construit (tools/build_moteur_photo.ps1)."""
import threading
import unittest

import numpy as np

from fm_photo import mesures, moteur, operations

EXPOSITION = [{"op": "exposition", "version": 1, "actif": True, "params": {"ev": 0.7}}]
CHAINE = EXPOSITION + [{"op": "diffusion", "version": 1, "actif": True, "params": {"quantite": 0.8, "rayon": 1.5}}]
WARPER = [{"op": "warper_teinte_saturation", "version": 1,
           "params": {"deplacements": [[[0.0, 0.0]] * 6, [[0.03, 0.0]] * 6], "chroma_max": 0.4}}]


def _scene(hauteur=301, largeur=403, graine=11):
    """Dimensions impaires (blocs partiels a la reduction), ombres, hautes lumieres au-dela du blanc, bords."""
    rng = np.random.default_rng(graine)
    image = (rng.random((hauteur, largeur, 3), dtype=np.float32) ** 2.2).astype(np.float32)
    for y, x in ((0, 0), (150, 200), (300, 402), (40, 399), (299, 3)):
        image[max(0, y - 2):y + 3, max(0, x - 2):x + 3] = (9.0, 7.0, 5.0)
    return image


@unittest.skipIf(moteur.EXECUTANT != "Rust", "moteur Rust non construit sur cette machine")
class RustContreReferenceTest(unittest.TestCase):
    def test_choix_de_l_executant_par_suite(self):
        self.assertEqual(moteur.executant(CHAINE), "Rust")
        self.assertEqual(moteur.executant(CHAINE, reference=True), "référence numpy")
        self.assertEqual(moteur.executant(CHAINE + WARPER), "référence numpy")      # une operation inconnue : tout en reference
        self.assertEqual(moteur.executant([dict(EXPOSITION[0], actif=False)] + WARPER[:0]), "Rust")

    def test_exposition_identique_au_bit_pres(self):
        image = _scene()
        np.testing.assert_array_equal(moteur.rendre_lineaire(image, EXPOSITION),
                                      moteur.rendre_lineaire(image, EXPOSITION, reference=True))

    def test_reduction_par_blocs(self):
        image = _scene()
        for facteur in (2, 3, 7):
            rust = moteur.rendre_lineaire(image, EXPOSITION, facteur)
            reference = moteur.rendre_lineaire(image, EXPOSITION, facteur, reference=True)
            self.assertEqual(rust.shape, reference.shape)
            np.testing.assert_allclose(rust, reference, rtol=2e-6, atol=1e-7, err_msg=f"facteur {facteur}")

    def test_chaine_spatiale_sous_les_seuils_du_protocole(self):
        image = _scene()
        for facteur in (1, 2):
            rust = moteur.rendre_lineaire(image, CHAINE, facteur)
            reference = moteur.rendre_lineaire(image, CHAINE, facteur, reference=True)
            ecart = mesures.comparer(rust, reference)
            self.assertTrue(ecart.tient(0.1, 0.2, 0.5), f"facteur {facteur} : {ecart}")
            np.testing.assert_allclose(rust, reference, rtol=1e-4, atol=1e-6, err_msg=f"facteur {facteur}")

    def test_affichage_8_bits_a_un_code_pres(self):
        image = _scene()
        rust = moteur.rendre_affichage(image, CHAINE, 1).astype(np.int16)
        reference = moteur.rendre_affichage(image, CHAINE, 1, reference=True).astype(np.int16)
        self.assertEqual(rust.shape, reference.shape)
        difference = np.abs(rust - reference)
        self.assertLessEqual(int(difference.max()), 1)
        self.assertLess(float((difference > 0).mean()), 0.005)                    # moins de 0,5 % des valeurs
        np.testing.assert_array_equal(rust[..., 3], 255)

    def test_export_16_bits_et_autres_espaces(self):
        image = _scene(120, 160)
        for espace in ("srgb", "display_p3", "adobe_rgb", "prophoto"):
            rust = moteur.rendre_export(image, CHAINE, espace, 16).astype(np.int32)
            reference = moteur.rendre_export(image, CHAINE, espace, 16, reference=True).astype(np.int32)
            self.assertEqual(rust.dtype, reference.dtype)
            self.assertLessEqual(int(np.abs(rust - reference).max()), 24, espace)  # < 0,1 code 8 bits
        self.assertEqual(moteur.rendre_export(image, CHAINE, "srgb", 8).dtype, np.uint8)

    def test_operation_inconnue_du_moteur_rendue_par_la_reference(self):
        image = _scene(60, 80)
        np.testing.assert_array_equal(moteur.rendre_lineaire(image, CHAINE + WARPER),
                                      moteur.rendre_lineaire(image, CHAINE + WARPER, reference=True))

    def test_annulation_interrogee_hors_du_verrou_python(self):
        image = _scene()
        appels = {"n": 0}

        def annule():
            appels["n"] += 1
            return appels["n"] > 3

        with self.assertRaises(operations.Annule):
            moteur.rendre_affichage(image, CHAINE, 1, annule)
        self.assertGreater(appels["n"], 3)
        self.assertEqual(moteur.rendre_affichage(image, CHAINE, 1, lambda: False).shape, (301, 403, 4))

    def test_cache_des_reductions_par_cle(self):
        image = _scene()
        sans = moteur.rendre_lineaire(image, CHAINE, 3)
        premier = moteur.rendre_lineaire(image, CHAINE, 3, cle=987654)
        second = moteur.rendre_lineaire(image, CHAINE, 3, cle=987654)               # reduction relue du cache
        np.testing.assert_array_equal(premier, sans)
        np.testing.assert_array_equal(second, sans)
        moteur.oublier(987654)
        np.testing.assert_array_equal(moteur.rendre_lineaire(image, CHAINE, 3, cle=987654), sans)
        moteur.oublier(987654)

    def test_tableau_non_contigu_et_source_intacte(self):
        image = _scene()
        avant = image.copy()
        vue = image[::2, ::2]
        np.testing.assert_array_equal(moteur.rendre_lineaire(vue, EXPOSITION),
                                      moteur.rendre_lineaire(np.ascontiguousarray(vue), EXPOSITION, reference=True))
        moteur.rendre_affichage(image, CHAINE, 1)
        np.testing.assert_array_equal(image, avant)                               # l'original n'est jamais modifie

    def test_le_verrou_python_est_libre_pendant_le_calcul(self):
        """Un autre fil Python avance pendant un rendu long : le calcul ne tient pas le verrou."""
        image = _scene(1200, 1600)
        tours = {"n": 0}
        fini = threading.Event()

        def compter():
            while not fini.is_set():
                tours["n"] += 1

        fil = threading.Thread(target=compter)
        fil.start()
        try:
            moteur.rendre_affichage(image, [CHAINE[0], dict(CHAINE[1], params={"quantite": 0.8, "rayon": 3.0})], 1)
        finally:
            fini.set()
            fil.join()
        self.assertGreater(tours["n"], 10000)


if __name__ == "__main__":
    unittest.main()
