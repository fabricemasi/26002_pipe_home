"""Colonnes > Lignes > Texte > « Couleur des extensions » : l'extension des FICHIERS (« .jpg ») est peinte
dans sa propre couleur, juste apres le nom ; les dossiers et les noms sans extension ne changent pas."""
import os as _os, sys as _sys  # jamais les vrais reglages / presets de l'utilisateur (tests/_isolate.py)
_sys.path.insert(0, _os.path.dirname(_os.path.abspath(__file__)))
import _isolate  # noqa: E402,F401
import os
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from PySide6.QtGui import QColor
from PySide6.QtWidgets import QApplication

APP = QApplication.instance() or QApplication([])

import settings_store
import settings_window_v2 as v2
import ui_state
from column import Column

RED = "#ff0000"


def red_pixels(widget) -> list:
    image = widget.grab().toImage()
    xs = []
    for y in range(image.height()):
        for x in range(image.width()):
            c = image.pixelColor(x, y)
            if c.red() > 200 and c.green() < 60 and c.blue() < 60:
                xs.append(x)
    return xs


class ExtensionColorTest(unittest.TestCase):
    def setUp(self):
        self.root = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.root, True)
        self.addCleanup(setattr, ui_state, "ITEM_EXT_COLOR", ui_state.ITEM_EXT_COLOR)

    def column(self, *names, dirs=()):
        for name in names:
            (self.root / name).write_text("x")
        for name in dirs:
            (self.root / name).mkdir()
        column = Column(self.root, "Contenu")
        column.resize(320, 200)
        column.show()
        column.refresh()
        self.addCleanup(column.deleteLater)
        APP.processEvents()
        return column

    def test_setting_is_declared(self):
        self.assertFalse(settings_store.DEFAULT_SETTINGS["item_ext_color_enabled"])
        keys = [spec.key for spec in v2.CATALOG["G Texte"]]
        self.assertIn("item_ext_color_enabled", keys)

    def test_extension_of_files_only_is_coloured(self):
        column = self.column("photo.jpg")
        ui_state.ITEM_EXT_COLOR = None
        self.assertEqual(red_pixels(column.list.viewport()), [])
        ui_state.ITEM_EXT_COLOR = RED
        column.list.viewport().update()
        xs = red_pixels(column.list.viewport())
        self.assertTrue(xs)                                   # l'extension, en rouge
        rect = column.list.visualItemRect(column.list.item(0))
        self.assertGreater(min(xs), rect.left() + 30)         # apres le nom, pas tout le nom

    def test_folders_and_names_without_extension_are_unchanged(self):
        column = self.column("LISEZMOI", dirs=("dossier.v2",))
        ui_state.ITEM_EXT_COLOR = RED
        column.list.viewport().update()
        self.assertEqual(red_pixels(column.list.viewport()), [])


if __name__ == "__main__":
    unittest.main()
