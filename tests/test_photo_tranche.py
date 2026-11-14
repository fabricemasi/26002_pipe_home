import _isolate  # noqa: F401 -- aucune ecriture dans les reglages reels
"""Tranche de bout en bout du moteur photo : source -> rendu hors du fil de l'interface (annulable, perimes
abandonnes) -> chargeur de la visionneuse (`FocusImageLoader.set_rendition`) -> export aux memes parametres."""
import os
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import numpy as np
from PySide6.QtCore import QSize
from PySide6.QtGui import QColorSpace, QImage, QImageReader
from PySide6.QtWidgets import QApplication

from fm_photo import etat, export, moteur, operations, sources
from fm_photo.rendu import ServiceRendu
from fm_visionneuse import loader
from fm_visionneuse.loader import FocusImageLoader

_app = QApplication.instance() or QApplication([])

SUITE = [{"op": "exposition", "version": 1, "actif": True, "params": {"ev": 1.0}},
         {"op": "diffusion", "version": 1, "actif": True, "params": {"quantite": 0.6, "rayon": 0.5}}]
FOND_DEVELOPPE = 90        # code sRGB du fond 0x40 apres +1 EV (calcul dans ServiceTest)


def _attendre(condition, delai=20.0):
    fin = time.monotonic() + delai
    while time.monotonic() < fin:
        _app.processEvents()
        if condition():
            return True
        time.sleep(0.005)
    return False


class _Dossier(unittest.TestCase):
    LARGEUR, HAUTEUR = 1280, 800

    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.dossier = Path(temp.name)
        self.photo = self.dossier / "photo.png"
        image = QImage(self.LARGEUR, self.HAUTEUR, QImage.Format_RGB32)
        image.fill(0xFF404040)
        for x in range(600, 680):
            for y in range(360, 440):
                image.setPixel(x, y, 0xFFFFFFFF)
        image.save(str(self.photo), "PNG")


class SourceTest(_Dossier):
    def test_source_lineaire_avec_provenance_declaree(self):
        source = sources.charger(self.photo)
        self.assertEqual(source.pixels.shape, (self.HAUTEUR, self.LARGEUR, 3))
        self.assertEqual(source.pixels.dtype, np.float32)
        self.assertIn("sRGB supposé", source.provenance)
        self.assertFalse(source.provisoire)
        np.testing.assert_allclose(source.pixels[0, 0], 0.0513, atol=2e-4)      # 0x40 sRGB -> lineaire
        np.testing.assert_allclose(source.pixels[400, 640], 1.0, atol=1e-4)

    def test_profil_integre_reconnu(self):
        image = QImage(str(self.photo))
        image.setColorSpace(QColorSpace(QColorSpace.NamedColorSpace.DisplayP3))
        self.assertEqual(sources.espace_de(image)[0], "display_p3")
        self.assertEqual(sources.espace_de(QImage(str(self.photo)))[0], "srgb")

    def test_fichier_illisible(self):
        self.assertIsNone(sources.charger(self.dossier / "absent.png"))


class ServiceTest(_Dossier):
    def setUp(self):
        super().setUp()
        self.service = ServiceRendu()
        self.addCleanup(self.service.attendre)
        self.prets, self.sans = [], []
        self.service.pret.connect(lambda cle, rendu: self.prets.append(rendu))
        self.service.sans_rendu.connect(self.sans.append)

    def test_provisoire_puis_definition_de_l_ecran(self):
        self.service.demander(self.photo, QSize(self.LARGEUR, self.HAUTEUR), SUITE)
        self.assertTrue(_attendre(lambda: any(not rendu.provisoire for rendu in self.prets)))
        self.assertEqual([rendu.provisoire for rendu in self.prets], [True, False])
        rapide, final = self.prets
        self.assertEqual((rapide.facteur, final.facteur), (2, 1))
        self.assertIn("aperçu provisoire", rapide.origine())                     # jamais donne pour definitif
        self.assertIn("pleine définition", final.origine())
        self.assertEqual(final.signature, etat.signature(SUITE))
        self.assertEqual((final.image.width(), final.image.height()), (self.LARGEUR, self.HAUTEUR))
        self.assertEqual((final.naturelle.width(), final.naturelle.height()), (self.LARGEUR, self.HAUTEUR))
        self.assertEqual(final.image.format(), QImage.Format_RGB32)
        # +1 EV : le fond 0x40 (0,05127 lineaire) double -> 0,10254 -> sRGB 0,3534 -> code 90 ; loin du halo.
        self.assertEqual(final.image.pixelColor(5, 5).red(), FOND_DEVELOPPE)
        self.assertGreater(final.image.pixelColor(590, 400).red(), FOND_DEVELOPPE)         # halo a cote de la source

    def test_etat_enregistre_lu_hors_du_fil_de_l_interface(self):
        self.service.demander(self.photo, QSize(320, 200))                        # rien d'enregistre
        self.assertTrue(_attendre(lambda: self.sans == [str(self.photo)]))
        etat.ecrire(self.photo, etat.definir_operation(etat.nouvel_etat(), "exposition", {"ev": 1.0}))
        self.service.demander(self.photo, QSize(320, 200))
        self.assertTrue(_attendre(lambda: bool(self.prets)))
        self.assertEqual(self.prets[-1].facteur, 4)
        self.assertEqual(self.prets[-1].ajustee.width(), 320)

    def test_seule_la_derniere_demande_est_rendue(self):
        cible = QSize(self.LARGEUR, self.HAUTEUR)
        for ev in (0.2, 0.4, 0.6, 0.8):
            self.service.demander(self.photo, cible, [dict(SUITE[0], params={"ev": ev}), SUITE[1]])
        derniere = etat.signature([dict(SUITE[0], params={"ev": 0.8}), SUITE[1]])
        self.assertTrue(_attendre(lambda: any(not rendu.provisoire for rendu in self.prets)))
        self.service.attendre()
        _app.processEvents()
        self.assertEqual({rendu.signature for rendu in self.prets}, {derniere})

    def test_abandon_ne_rend_rien(self):
        self.service.demander(self.photo, QSize(self.LARGEUR, self.HAUTEUR), SUITE)
        self.service.abandonner(self.photo)
        self.service.attendre()
        _app.processEvents()
        self.assertEqual((self.prets, self.sans), ([], []))

    def test_operation_inconnue_laisse_l_image_decodee(self):
        self.service.demander(self.photo, QSize(320, 200), [{"op": "inconnue", "params": {"x": 1}}])
        self.assertTrue(_attendre(lambda: self.sans == [str(self.photo)]))


class VisionneuseTest(_Dossier):
    def test_le_rendu_remplace_l_image_decodee_dans_le_chargeur(self):
        chargeur, service = FocusImageLoader(), ServiceRendu()
        self.addCleanup(service.attendre)
        chargeur.set_fit(QSize(640, 400))
        recus = []
        chargeur.ready.connect(recus.append)
        chargeur.request(self.photo, urgent=True)
        self.assertTrue(_attendre(lambda: bool(recus)))
        decodee = chargeur.get(self.photo)
        self.assertEqual(decodee[1].pixelColor(5, 5).red(), 0x40)
        self.assertFalse(chargeur.has_rendition(self.photo))

        service.pret.connect(lambda cle, rendu: chargeur.set_rendition(
            Path(cle), rendu.image, rendu.ajustee, rendu.naturelle, rendu.origine()))
        service.demander(self.photo, chargeur.fit(), SUITE)
        self.assertTrue(_attendre(lambda: chargeur.has_rendition(self.photo)))
        pixmap, image, naturelle = chargeur.get(self.photo)
        self.assertEqual(image.pixelColor(5, 5).red(), FOND_DEVELOPPE)           # developpee
        self.assertEqual((pixmap.width(), pixmap.height()), (640, 400))          # deja ajustee a l'ecran
        self.assertEqual(naturelle.width(), self.LARGEUR)                        # la photo garde sa taille reelle
        self.assertIn("Développement PIPE FMZ", chargeur.origin(self.photo))
        self.assertEqual(recus.count(str(self.photo)), 2)                        # l'affichage a ete prevenu

        chargeur.invalidate(self.photo)                                          # nouvel apercu du pipeline
        self.assertTrue(chargeur.has_rendition(self.photo))
        self.assertEqual(chargeur.get(self.photo)[1].pixelColor(5, 5).red(), FOND_DEVELOPPE)
        chargeur.clear_rendition(self.photo)                                     # retour a l'image decodee
        self.assertTrue(_attendre(lambda: chargeur.get(self.photo) is not None))
        self.assertEqual(chargeur.get(self.photo)[1].pixelColor(5, 5).red(), 0x40)

    def test_fenetre_principale_etat_enregistre_montre_tout_seul(self):
        """Le mixin de la fenetre : une image decodee dont l'etat est enregistre arrive developpee, sans rien
        demander ; sans etat, l'image decodee reste ; `photo_develop` montre un reglage en direct."""
        from PySide6.QtCore import QObject
        from main_window.photo_module import PhotoModuleMixin

        class Fenetre(PhotoModuleMixin, QObject):
            def __init__(self):
                super().__init__()
                self._focus_images = FocusImageLoader(self)
                self._focus_images.set_fit(QSize(640, 400))
                self._install_photo()

        fenetre = Fenetre()
        self.addCleanup(lambda: fenetre._photo_service().attendre())
        chargeur = fenetre._focus_images
        chargeur.request(self.photo, urgent=True)
        self.assertTrue(_attendre(lambda: chargeur.get(self.photo) is not None))
        fenetre._photo_service().attendre()
        _app.processEvents()
        self.assertFalse(chargeur.has_rendition(self.photo))                    # aucun etat : rien ne change

        etat.ecrire(self.photo, etat.definir_operation(etat.nouvel_etat(), "exposition", {"ev": 1.0}))
        chargeur.invalidate(self.photo)
        chargeur.request(self.photo, urgent=True)
        self.assertTrue(_attendre(lambda: chargeur.has_rendition(self.photo)))
        self.assertEqual(chargeur.get(self.photo)[1].pixelColor(5, 5).red(), FOND_DEVELOPPE)

        fenetre.photo_develop(self.photo, [])                                    # reglages remis a zero, en direct
        self.assertTrue(_attendre(lambda: not chargeur.has_rendition(self.photo)))
        self.assertTrue(_attendre(lambda: chargeur.get(self.photo) is not None))
        self.assertEqual(chargeur.get(self.photo)[1].pixelColor(5, 5).red(), 0x40)

    def test_photo_lightroom_garde_le_rendu_de_lightroom(self):
        service = ServiceRendu()
        self.addCleanup(service.attendre)
        prets, sans = [], []
        service.pret.connect(lambda cle, rendu: prets.append(rendu))
        service.sans_rendu.connect(sans.append)
        etat.ecrire(self.photo, etat.definir_operation(etat.nouvel_etat(), "exposition", {"ev": 1.0}))
        with patch("lightroom_bridge.is_managed", return_value=True):
            service.demander(self.photo, QSize(320, 200))
            self.assertTrue(_attendre(lambda: sans == [str(self.photo)]))
        self.assertEqual(prets, [])

    def test_un_rendu_ne_survit_pas_au_changement_du_fichier(self):
        chargeur = FocusImageLoader()
        image = QImage(str(self.photo))
        patcher = patch.object(loader.previews, "cached_mtime", return_value=None)   # date relue sur le disque
        patcher.start()
        self.addCleanup(patcher.stop)
        chargeur.set_rendition(self.photo, image, None, image.size(), "test")
        self.assertTrue(chargeur.has_rendition(self.photo))
        os.utime(self.photo, (time.time() + 10, time.time() + 10))
        self.assertFalse(chargeur.has_rendition(self.photo))
        self.assertIsNone(chargeur.get(self.photo))


class ExportTest(_Dossier):
    def test_export_identique_a_l_apercu_a_la_meme_echelle(self):
        source = sources.charger(self.photo)
        sortie = export.exporter(export.Travail(self.photo, self.dossier / "sortie.png", SUITE), source=source)
        apercu = moteur.rendre_affichage(source.pixels, SUITE, 1)
        relu = QImage(str(sortie)).convertToFormat(QImage.Format_RGBX8888)
        octets = np.frombuffer(relu.constBits(), dtype=np.uint8).reshape(self.HAUTEUR, self.LARGEUR, 4)
        np.testing.assert_array_equal(octets[..., :3], apercu[..., :3])
        self.assertTrue(QImage(str(sortie)).colorSpace().isValid())              # profil integre

    def test_tiff_16_bits_garde_la_precision(self):
        source = sources.charger(self.photo)
        sortie = export.exporter(export.Travail(self.photo, self.dossier / "sortie.tif", SUITE, bits=16),
                                 source=source)
        relu = QImageReader(str(sortie)).read()
        self.assertIn(relu.format(), (QImage.Format_RGBX64, QImage.Format_RGBA64, QImage.Format_RGBA64_Premultiplied))
        attendu = moteur.rendre_export(source.pixels, SUITE, "srgb", 16)
        valeurs = sources.image_vers_tableau(relu)
        np.testing.assert_allclose(valeurs * 65535.0, attendu.astype(np.float32), atol=0.6)
        self.assertGreater(len(np.unique(attendu[..., 0])), 256)                 # plus de niveaux qu'en 8 bits

    def test_le_travail_fige_ses_parametres(self):
        suite = [dict(SUITE[0], params={"ev": 1.0})]
        travail = export.Travail(self.photo, self.dossier / "fige.jpg", suite)
        suite[0]["params"]["ev"] = 3.0
        self.assertEqual(travail.suite[0]["params"], {"ev": 1.0})
        self.assertEqual(travail.signature, etat.signature([dict(SUITE[0], params={"ev": 1.0})]))
        sortie = export.exporter(travail)
        self.assertAlmostEqual(QImage(str(sortie)).pixelColor(5, 5).red(), FOND_DEVELOPPE, delta=2)   # JPEG : a 2 codes pres

    def test_rien_n_est_remplace_ni_laisse_partiel(self):
        existante = self.dossier / "deja.jpg"
        existante.write_bytes(b"x")
        with self.assertRaises(export.ExportImpossible):
            export.exporter(export.Travail(self.photo, existante, SUITE))
        self.assertEqual(existante.read_bytes(), b"x")
        with self.assertRaises(export.ExportImpossible):
            export.Travail(self.photo, self.photo, SUITE)                        # l'original n'est jamais ecrase
        with self.assertRaises(export.ExportImpossible):
            export.Travail(self.photo, self.dossier / "sortie.jpg", SUITE, bits=16)
        with self.assertRaises(operations.Annule):
            export.exporter(export.Travail(self.photo, self.dossier / "annule.tif", SUITE), annule=lambda: True)
        self.assertEqual(sorted(path.name for path in self.dossier.iterdir()), ["deja.jpg", "photo.png"])


if __name__ == "__main__":
    unittest.main()
