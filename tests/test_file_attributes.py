"""Attributs des fichiers (base du systeme de filtres) : note, couleur, j'aime, mots cles, statut ; un fichier
cache par dossier ; seulement les fichiers a apercu ; modifiables dans le tableau de la visionneuse."""
import os as _os, sys as _sys  # jamais les vrais reglages / presets de l'utilisateur (tests/_isolate.py)
_sys.path.insert(0, _os.path.dirname(_os.path.abspath(__file__)))
import _isolate  # noqa: E402,F401
import json
import os
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from PySide6.QtCore import QPoint, Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

app = QApplication.instance() or QApplication([])

import file_attributes as fa
import focus
import settings_store
import ui_state


class StorageTest(unittest.TestCase):
    def setUp(self):
        self.dir = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.dir, True)
        self.image = self.dir / "photo.jpg"
        self.image.write_bytes(b"x")

    def test_only_files_with_a_preview(self):
        self.assertTrue(fa.eligible(self.image))
        self.assertTrue(fa.eligible(self.dir / "scene.blend"))
        self.assertFalse(fa.eligible(self.dir / "notes.txt"))
        (self.dir / "dossier.png").mkdir()
        self.assertFalse(fa.eligible(self.dir / "dossier.png"))

    def test_saved_in_the_folder_and_read_back(self):
        self.assertEqual(fa.get(self.image), fa.DEFAULTS)
        fa.update(self.image, rating=4, color=2, like=True, keywords=["ciel", " nuit ", "ciel"], status="keep")
        raw = json.loads((self.dir / fa.FILENAME).read_text(encoding="utf-8"))
        self.assertEqual(raw["photo.jpg"], {"rating": 4, "color": 2, "like": True, "keywords": ["ciel", "nuit"],
                                            "status": "keep"})
        fa._CACHE.clear()
        self.assertEqual(fa.get(self.image)["keywords"], ["ciel", "nuit"])
        fa.update(self.image, rating=0, color=0, like=False, keywords=[], status="")
        self.assertFalse((self.dir / fa.FILENAME).exists())         # plus rien : fichier retire

    def test_images_of_a_pureref_board_keep_attributes_with_the_board(self):
        # Images extraites d'une planche .pur : fichiers internes de l'appli (data/), mais attributs ranges
        # dans le dossier de la planche (le tableau Attributs ne doit pas disparaitre sur elles).
        from config import DATA_DIR
        inner = DATA_DIR / "_test_pur_cache" / "img_001.png"
        self.assertFalse(fa.eligible(inner))
        pur = self.dir / "main.pur"
        fa.set_alias(inner, pur.parent, f"{pur.name}/{inner.name}")
        self.addCleanup(fa._ALIASES.pop, os.path.normcase(str(inner)), None)
        self.assertTrue(fa.eligible(inner))
        fa.update(inner, rating=3)
        raw = json.loads((self.dir / fa.FILENAME).read_text(encoding="utf-8"))
        self.assertEqual(raw["main.pur/img_001.png"], {"rating": 3})
        self.assertEqual(fa.get(inner)["rating"], 3)
        self.assertFalse(inner.parent.exists())                       # rien d'ecrit dans le cache

    def test_keywords_text(self):
        self.assertEqual(fa.parse_keywords("ciel, nuit ; ville,, "), ["ciel", "nuit", "ville"])


class ViewerTableTest(StorageTest):
    def test_attributes_are_edited_in_the_viewer_table(self):
        saved = ui_state.APPLIED_SETTINGS
        self.addCleanup(setattr, ui_state, "APPLIED_SETTINGS", saved)
        ui_state.APPLIED_SETTINGS = settings_store.load_settings()
        panel = focus.FocusInfoPanel(None)
        panel.resize(400, 700)
        panel.show()
        self.addCleanup(panel.deleteLater)
        panel.set_path(self.image)
        panel.wait_done()
        for _ in range(5):
            app.processEvents()
        editor = panel._attributes
        self.assertEqual([label for label, _w, _n in editor.rows], ["Note", "Couleur", "J'aime", "Mots clés", "Statut"])
        stars = editor.stars
        QTest.mouseClick(stars, Qt.LeftButton, Qt.NoModifier, QPoint(stars._step * 3 + 2, stars.height() // 2))
        editor.colors.changed.emit(3)
        editor.like.setChecked(True)
        # Mots cles : saisis a la volee, separes par des espaces ; enregistres a la sortie du champ.
        words = editor.keywords
        words.setFocus()
        QTest.keyClicks(words, "ciel nuit CIEL")                       # « CIEL » : doublon ignore
        words.editingFinished.emit()
        self.assertEqual(fa.get(self.image)["keywords"], ["ciel", "nuit"])
        # Les mots employes sont retenus et proposes ensuite (les plus frequents d'abord).
        fa.update(self.dir / "x.png", keywords=["nuit", "ville"])
        known = fa.known_keywords()
        self.assertLess(known.index("nuit"), known.index("ville"))     # 2 emplois avant 1
        self.assertTrue({"ciel", "nuit", "ville"} <= set(known))
        # Autocompletion du mot EN COURS : sur une partie du mot, sans casse, sauf les mots deja saisis.
        words.setText("ciel nuit ")
        words.setCursorPosition(len(words.text()))
        QTest.keyClicks(words, "IL")
        completer = words.completer_
        self.assertEqual((completer.filterMode(), completer.caseSensitivity()), (Qt.MatchContains, Qt.CaseInsensitive))
        self.assertTrue(completer.popup().isVisible())
        proposed = [completer.completionModel().index(i, 0).data() for i in range(completer.completionCount())]
        self.assertIn("ville", proposed)
        self.assertNotIn("ciel", proposed)                              # deja saisi
        completer.activated[str].emit("ville")                         # choix : remplace le mot en cours
        self.assertEqual(words.text(), "ciel nuit ville ")
        words.editingFinished.emit()
        self.assertEqual(fa.get(self.image)["keywords"], ["ciel", "nuit", "ville"])
        fa.update(self.image, keywords=["ciel", "nuit"])
        words.set_words(["ciel", "nuit"])
        editor.status.changed.emit("À supprimer")
        values = fa.get(self.image)
        self.assertEqual((values["rating"], values["color"], values["like"], values["keywords"], values["status"]),
                         (4, 3, True, ["ciel", "nuit"], "delete"))
        # Un autre fichier : ses propres attributs (vides).
        other = self.dir / "autre.png"
        other.write_bytes(b"y")
        panel.set_path(other)
        self.assertEqual(editor.stars.value(), 0)
        self.assertFalse(editor.like.isChecked())


if __name__ == "__main__":
    unittest.main()
