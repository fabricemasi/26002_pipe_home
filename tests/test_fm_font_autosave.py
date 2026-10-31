"""fm_font, SAUVEGARDE DE SECOURS : écrite en fond hors du projet, trouvée à la réouverture si plus récente que
le fichier, récupérée (mêmes chemins, « modifié ») ou jetée, supprimée après un enregistrement."""
import os as _os, sys as _sys  # jamais les vrais réglages / presets de l'utilisateur (tests/_isolate.py)
_sys.path.insert(0, _os.path.dirname(_os.path.abspath(__file__)))
import _isolate  # noqa: E402,F401
import os
import shutil
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

from PySide6.QtWidgets import QApplication, QWidget

from _window_cleanup import WindowTestCase, track  # noqa: E402
from fm_font import pane as pane_mod  # noqa: E402
from fm_font import shapes  # noqa: E402
from fm_font.autosave import Autosaver, project_key  # noqa: E402
from fm_font.document import FontProject  # noqa: E402

app = QApplication.instance() or QApplication([])


class AutosaveTest(WindowTestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="fmfont_secours_"))
        self.rescue_dir = self.tmp / "secours"
        os.environ["FM_FONT_AUTOSAVE_DIR"] = str(self.rescue_dir)
        project = FontProject.new("Essai")
        project.add_glyph("A")
        project.font["A"].contours.append(shapes.rectangle(0, 0, 400, 700))
        self.ufo = self.tmp / "Essai.ufo"
        project.save(self.ufo)

    def tearDown(self):
        os.environ.pop("FM_FONT_AUTOSAVE_DIR", None)
        super().tearDown()
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_write_find_restore_discard(self):
        saver = Autosaver()
        p = FontProject.open(self.ufo)
        self.assertIsNone(saver.find(p.path))
        p.edit_glyph("A", "x", lambda g: setattr(g, "width", 777))
        time.sleep(0.05)
        thread = saver.write(p)
        self.assertIsNotNone(thread)                                    # écriture dans un fil
        saver.wait()
        self.assertIsNone(saver.last_error)
        folder = saver.find(self.ufo)
        self.assertEqual(folder, self.rescue_dir / project_key(p))
        q = saver.restore(folder)
        self.assertEqual((q.path, q.masters[0].path), (self.ufo, self.ufo))
        self.assertEqual(q.font["A"].width, 777)
        self.assertTrue(q.is_dirty())
        q.save()                                                        # remplace l'original (atomique)
        self.assertEqual(FontProject.open(self.ufo).font["A"].width, 777)
        self.assertIsNone(saver.find(self.ufo))                        # le fichier est maintenant plus récent
        saver.discard(q)
        self.assertFalse(folder.exists())

    def test_pane_offers_rescue_on_open_and_cleans_after_save(self):
        host = track(QWidget())
        host.resize(1200, 800)
        pane = pane_mod.FontPane(host)
        try:
            self.assertTrue(pane.open_path(self.ufo))
            pane.project.edit_glyph("A", "x", lambda g: setattr(g, "width", 650))
            time.sleep(0.05)
            pane._autosave_tick()
            pane.autosaver.wait()
            folder = pane.autosaver.folder(pane.project)
            self.assertTrue((folder / "secours.json").is_file())
            # « plantage » : un autre espace de travail rouvre le fichier et propose le secours
            other = pane_mod.FontPane(host)
            with mock.patch.object(pane_mod, "confirm", return_value=True) as asked:
                self.assertTrue(other.open_path(self.ufo))
            self.assertEqual(asked.call_count, 1)
            self.assertEqual(other.project.font["A"].width, 650)
            self.assertTrue(other.project.is_dirty())
            self.assertTrue(other.save())
            self.assertFalse(folder.exists())                           # enregistré : secours supprimé
            other.shutdown()
            # refusé : le secours est jeté
            pane.project.edit_glyph("A", "y", lambda g: setattr(g, "width", 640))
            time.sleep(0.05)
            pane._autosave_tick()
            pane.autosaver.wait()
            third = pane_mod.FontPane(host)
            with mock.patch.object(pane_mod, "confirm", return_value=False):
                third.open_path(self.ufo)
            self.assertEqual(third.project.font["A"].width, 650)
            self.assertFalse(folder.exists())
            third.shutdown()
        finally:
            pane.shutdown()

    def test_new_project_rescue_removed_after_save_as(self):
        host = track(QWidget())
        pane = pane_mod.FontPane(host)
        try:
            pane.new_field.setText("B")
            pane.create_from_field()
            pane._autosave_tick()
            pane.autosaver.wait()
            old = pane.autosaver.folder(pane.project)
            self.assertTrue(old.exists())
            target = self.tmp / "Nouveau.ufo"
            with mock.patch.object(pane_mod.QFileDialog, "getSaveFileName", return_value=(str(target), "")):
                self.assertTrue(pane.save_as_dialog())
            self.assertFalse(old.exists())
            self.assertTrue(target.is_dir())
        finally:
            pane.shutdown()


if __name__ == "__main__":
    unittest.main()
