import _isolate  # noqa: F401 -- aucune ecriture dans les reglages reels
"""Etat non destructif (`fm_photo/etat.py`) et primitives de reference (`fm_photo/operations.py`)."""
import json
import tempfile
import unittest
from pathlib import Path

import numpy as np

from fm_photo import etat, operations
from fm_photo.operations import Contexte


def _scene(hauteur=96, largeur=128, graine=3):
    """Image lineaire avec quelques sources tres lumineuses (au-dela du blanc) sur un fond moyen."""
    rng = np.random.default_rng(graine)
    image = rng.random((hauteur, largeur, 3), dtype=np.float32) * 0.4
    for y, x in ((10, 12), (50, 100), (90, 5), (0, 127)):
        image[max(0, y - 1):y + 2, max(0, x - 1):x + 2] = (6.0, 5.0, 4.0)
    return image


DIFFUSION = [{"op": "exposition", "version": 1, "actif": True, "params": {"ev": 0.5}},
             {"op": "diffusion", "version": 1, "actif": True, "params": {"quantite": 0.8, "rayon": 3.0}}]


class EtatTest(unittest.TestCase):
    def test_les_modifications_rendent_un_nouvel_etat(self):
        depart = etat.nouvel_etat()
        suivant = etat.definir_operation(depart, "exposition", {"ev": 1.0})
        self.assertEqual(etat.operations(depart), [])
        self.assertEqual(etat.operations(suivant),
                         [{"op": "exposition", "version": 1, "actif": True, "params": {"ev": 1.0}}])
        encore = etat.definir_operation(suivant, "exposition", {"ev": 2.0})
        self.assertEqual(len(etat.operations(encore)), 1)                      # meme operation, meme place

    def test_copie_virtuelle_independante(self):
        base = etat.definir_operation(etat.nouvel_etat(), "exposition", {"ev": 1.0})
        copie = etat.copie_virtuelle(base, "Sombre")
        copie = etat.definir_operation(copie, "exposition", {"ev": -1.0})
        self.assertEqual(copie["courante"], "v2")
        self.assertEqual(etat.operations(copie, "v1")[0]["params"], {"ev": 1.0})
        self.assertEqual(etat.operations(copie, "v2")[0]["params"], {"ev": -1.0})
        self.assertEqual(etat.choisir_version(copie, "v1")["courante"], "v1")
        with self.assertRaises(KeyError):
            etat.choisir_version(copie, "absente")

    def test_signature_ne_depend_que_de_ce_qui_est_calcule(self):
        une = [{"op": "exposition", "version": 1, "actif": True, "params": {"ev": 1.0}, "note": "x"}]
        meme = [{"params": {"ev": 1.0}, "op": "exposition", "version": 1},
                {"op": "diffusion", "version": 1, "actif": False, "params": {"quantite": 1.0}}]
        self.assertEqual(etat.signature(une), etat.signature(meme))
        self.assertNotEqual(etat.signature(une), etat.signature([dict(une[0], version=2)]))
        self.assertNotEqual(etat.signature(une), etat.signature([dict(une[0], params={"ev": 1.5})]))

    def test_historique_annuler_retablir(self):
        a = etat.nouvel_etat()
        b = etat.definir_operation(a, "exposition", {"ev": 1.0})
        c = etat.definir_operation(b, "exposition", {"ev": 2.0})
        historique = etat.Historique(a)
        historique.poser(b)
        historique.poser(b)                                                    # sans changement : pas d'entree
        historique.poser(c)
        self.assertIs(historique.annuler(), b)
        self.assertIs(historique.annuler(), a)
        self.assertFalse(historique.peut_annuler())
        self.assertIs(historique.retablir(), b)
        historique.poser(a)                                                    # nouvelle branche : c est oublie
        self.assertFalse(historique.peut_retablir())

    def test_stockage_par_dossier_garde_l_inconnu(self):
        with tempfile.TemporaryDirectory() as temp:
            photo, autre = Path(temp) / "a.raf", Path(temp) / "b.raf"
            fichier = Path(temp) / etat.FICHIER
            fichier.write_text(json.dumps({"b.raf": {"schema": 1, "courante": "v1", "versions": [], "futur": 7}}),
                               encoding="utf-8")
            self.assertIsNone(etat.lire(photo))
            pose = etat.definir_operation(etat.nouvel_etat(), "exposition", {"ev": 0.3})
            pose["cle_d_un_autre_outil"] = {"x": 1}
            etat.ecrire(photo, pose)
            self.assertEqual(etat.lire(photo), pose)
            self.assertEqual(etat.lire(autre)["futur"], 7)                     # etat voisin et cle inconnue gardes
            self.assertFalse((Path(temp) / (etat.FICHIER + ".tmp")).exists())
            etat.ecrire(photo, None)
            etat.ecrire(autre, None)
            self.assertFalse(fichier.exists())                                 # plus rien : plus de fichier

    def test_un_schema_plus_recent_n_est_ni_lu_ni_reecrit(self):
        with tempfile.TemporaryDirectory() as temp:
            photo = Path(temp) / "a.raf"
            fichier = Path(temp) / etat.FICHIER
            fichier.write_text(json.dumps({"a.raf": {"schema": etat.SCHEMA + 1}}), encoding="utf-8")
            avant = fichier.read_bytes()
            with self.assertRaises(etat.EtatTropRecent):
                etat.lire(photo)
            with self.assertRaises(etat.EtatTropRecent):
                etat.ecrire(Path(temp) / "b.raf", etat.nouvel_etat())
            self.assertEqual(fichier.read_bytes(), avant)


class OperationsTest(unittest.TestCase):
    def test_aux_defauts_chaque_operation_est_l_identite(self):
        image = _scene()
        contexte = Contexte(1.0, image.shape[1])
        for (ident, version), connue in operations.REGISTRE.items():
            suite = [{"op": ident, "version": version, "params": dict(connue.defauts)}]
            self.assertEqual(operations.chaine(suite), [], ident)              # neutre : meme pas calculee
            np.testing.assert_array_equal(connue.appliquer(image, connue.defauts, contexte), image, ident)

    def test_operation_coupee_ou_inconnue(self):
        image = _scene()
        coupee = [dict(DIFFUSION[1], actif=False)]
        self.assertIs(operations.appliquer(image, coupee, Contexte(1.0, 128)), image)
        with self.assertRaises(KeyError):                                      # jamais ignoree en silence
            operations.appliquer(image, [{"op": "inconnue", "params": {"x": 1}}], Contexte(1.0, 128))
        with self.assertRaises(KeyError):
            operations.appliquer(image, [dict(DIFFUSION[0], version=99)], Contexte(1.0, 128))

    def test_exposition_est_un_gain_lineaire_sans_ecretage(self):
        image = _scene()
        rendu = operations.appliquer(image, [DIFFUSION[0]], Contexte(1.0, 128))
        np.testing.assert_allclose(rendu, image * np.float32(2 ** 0.5), rtol=1e-6)
        self.assertGreater(float(rendu.max()), 8.0)

    def test_noyau_gaussien_normalise_et_symetrique(self):
        noyau = operations.noyau_gaussien(2.5)
        self.assertEqual(len(noyau), 2 * 10 + 1)
        self.assertAlmostEqual(float(noyau.sum()), 1.0, places=6)
        np.testing.assert_array_equal(noyau, noyau[::-1])

    def test_flou_conserve_un_aplat_et_l_energie_d_un_point(self):
        aplat = np.full((40, 40, 3), 0.7, dtype=np.float32)
        np.testing.assert_allclose(operations.flou_gaussien(aplat, 3.0), aplat, atol=1e-6)
        point = np.zeros((81, 81, 3), dtype=np.float32)
        point[40, 40] = 1.0
        etale = operations.flou_gaussien(point, 4.0)
        self.assertAlmostEqual(float(etale[..., 0].sum()), 1.0, places=4)
        # Ecart type mesure du halo = sigma demande (a la troncature pres).
        positions = np.arange(81) - 40.0
        variance = float((etale[..., 0].sum(axis=0) * positions ** 2).sum())
        self.assertAlmostEqual(variance ** 0.5, 4.0, delta=0.02)

    def test_tuiles_sans_couture_au_bit_pres(self):
        image = _scene()
        contexte = Contexte(1.0, image.shape[1])
        self.assertGreater(operations.marge_totale(DIFFUSION, contexte), 8)
        entier = operations.appliquer(image, DIFFUSION, contexte)
        for cote in (32, 50):
            np.testing.assert_array_equal(operations.appliquer_par_tuiles(image, DIFFUSION, contexte, cote), entier)

    def test_reduction_par_blocs_conserve_la_moyenne(self):
        image = _scene(90, 130)
        reduite = operations.reduire(image, 4)
        self.assertEqual(reduite.shape, (23, 33, 3))
        np.testing.assert_allclose(reduite[0, 0], image[:4, :4].mean(axis=(0, 1)), rtol=1e-5)
        np.testing.assert_allclose(reduite[-1, -1], image[88:, 128:].mean(axis=(0, 1)), rtol=1e-5)
        self.assertIs(operations.reduire(image, 1), image)

    def test_apercu_reduit_et_pleine_definition_convergent(self):
        """Meme phenomene a deux echelles : l'apercu au 1/4 (image reduite, PUIS traitee) reste proche de la
        pleine definition traitee PUIS reduite. Ecart borne, pas nul : un apercu reduit est provisoire."""
        image = _scene(192, 256)
        plein = operations.reduire(operations.appliquer(image, DIFFUSION, Contexte(1.0, 256)), 4)
        apercu = operations.appliquer(operations.reduire(image, 4), DIFFUSION, Contexte(0.25, 256))
        ecart = np.abs(apercu - plein)
        self.assertLess(float(np.median(ecart)), 0.01)
        self.assertLess(float(np.percentile(ecart, 99)), 0.15)

    def test_annulation_ne_rend_rien(self):
        image = _scene()
        appels = {"n": 0}

        def annule():
            appels["n"] += 1
            return appels["n"] > 2

        with self.assertRaises(operations.Annule):
            operations.appliquer(image, DIFFUSION, Contexte(1.0, 128, annule))


if __name__ == "__main__":
    unittest.main()
