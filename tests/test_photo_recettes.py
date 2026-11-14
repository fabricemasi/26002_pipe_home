import _isolate  # noqa: F401 -- aucune ecriture dans les reglages reels
"""Recettes (`fm_photo/recettes.py`) : matrice X-T5 du manuel, dependances, rien d'ignore en silence."""
import unittest

from fm_photo import recettes


def _recette(reglages, iso=None, firmware="4.32", **autres):
    recette = recettes.nouvelle("essai", firmware=firmware)
    recette["reglages"] = reglages
    if iso is not None:
        recette["prise_de_vue"]["iso"] = iso
    recette.update(autres)
    return recette


class MatriceTest(unittest.TestCase):
    def test_vingt_simulations(self):
        self.assertEqual(len(recettes.X_T5["film_simulation"].valeurs), 20)

    def test_recette_de_boitier_valide_et_transposable(self):
        rapport = recettes.verifier(_recette({"film_simulation": "CLASSIC CHROME", "dynamic_range": "200",
                                              "color": 2, "sharpness": -1, "clarity": -3, "grain_roughness": "WEAK",
                                              "grain_size": "SMALL", "color_chrome_fx_blue": "STRONG",
                                              "white_balance": "COLOR TEMPERATURE", "color_temperature": 5600},
                                             iso=250))
        self.assertEqual(rapport.erreurs, [])
        self.assertTrue(rapport.transposable)
        self.assertEqual(len(rapport.non_pris_en_charge), 10)          # le moteur n'en rend encore aucun : dit

    def test_valeurs_hors_matrice(self):
        rapport = recettes.verifier(_recette({"film_simulation": "KODACHROME", "color": 5, "clarity": 1.5,
                                              "color_temperature": 5605, "inconnu": 1,
                                              "white_balance": "COLOR TEMPERATURE"}))
        self.assertEqual(len(rapport.erreurs), 5)
        self.assertFalse(rapport.transposable)

    def test_ce_que_le_manuel_n_ecrit_pas_n_est_pas_invente(self):
        rapport = recettes.verifier(_recette({"wb_shift_r": 4, "wb_shift_b": -5, "tone_curve_highlights": -1.5,
                                              "tone_curve_shadows": 2}))
        self.assertEqual(rapport.erreurs, [])
        self.assertEqual(len(rapport.non_verifiables), 3)              # WB shift x 2, demi-pas de la courbe
        self.assertFalse(recettes.verifier(_recette({"tone_curve_shadows": 5})).valide)

    def test_plage_dynamique_et_sensibilite(self):
        self.assertFalse(recettes.verifier(_recette({"dynamic_range": "400"}, iso=250)).valide)
        self.assertFalse(recettes.verifier(_recette({"dynamic_range": "200"})).valide)       # ISO non renseignee
        self.assertTrue(recettes.verifier(_recette({"dynamic_range": "400"}, iso=500)).valide)
        self.assertTrue(recettes.verifier(_recette({"dynamic_range": "100"}, iso=125)).valide)
        self.assertFalse(recettes.verifier(_recette({"d_range_priority": "STRONG"}, iso=320)).valide)

    def test_d_range_priority_regle_seul_courbe_et_plage(self):
        rapport = recettes.verifier(_recette({"d_range_priority": "WEAK", "dynamic_range": "200",
                                              "tone_curve_highlights": 1}, iso=400))
        self.assertEqual(len(rapport.erreurs), 2)

    def test_dependances_de_simulation_firmware_et_format(self):
        self.assertFalse(recettes.verifier(_recette({"film_simulation": "REALA ACE"}, firmware="3.01")).valide)
        self.assertFalse(recettes.verifier(_recette({"film_simulation": "REALA ACE"}, firmware="")).valide)
        self.assertTrue(recettes.verifier(_recette({"film_simulation": "REALA ACE"}, firmware="4.00")).valide)
        self.assertFalse(recettes.verifier(_recette({"film_simulation": "PROVIA/STANDARD",
                                                     "monochromatic_wc": 3})).valide)
        self.assertTrue(recettes.verifier(_recette({"film_simulation": "ACROS+R", "monochromatic_wc": 3})).valide)
        heif = _recette({"clarity": 2})
        heif["boitier"]["format"] = "HEIF"
        self.assertFalse(recettes.verifier(heif).valide)
        self.assertFalse(recettes.verifier(_recette({"color_temperature": 5600})).valide)

    def test_recette_logicielle_jamais_dite_transposable(self):
        logicielle = _recette({"film_simulation": "ASTIA/SOFT"}, type="logicielle",
                              operations=[{"op": "exposition", "version": 1, "params": {"ev": 0.3}}])
        rapport = recettes.verifier(logicielle)
        self.assertTrue(rapport.valide)
        self.assertFalse(rapport.transposable)
        self.assertFalse(recettes.verifier(_recette({}, type="autre")).valide)
        inconnu = _recette({})
        inconnu["boitier"]["modele"] = "autre_boitier"
        self.assertFalse(recettes.verifier(inconnu).valide)


class EchangeTest(unittest.TestCase):
    def test_export_import_garde_tout(self):
        recette = _recette({"film_simulation": "CLASSIC Neg.", "color": -2}, iso=125)
        recette["cle_d_un_autre_outil"] = {"x": 1}
        relue = recettes.importer_json(recettes.exporter_json(recette))
        self.assertEqual(relue, recette)
        self.assertEqual(relue["validation"]["statut"], recettes.NON_VALIDEE)

    def test_import_refuse_ce_qu_il_ne_comprend_pas(self):
        with self.assertRaises(ValueError):
            recettes.importer_json('{"schema": 99, "reglages": {}}')
        with self.assertRaises(ValueError):
            recettes.importer_json('{"nom": "pas une recette"}')
        self.assertEqual(recettes.importer_json('{"reglages": {"color": 1}}')["type"], "boitier")


if __name__ == "__main__":
    unittest.main()
