"""Bouton « + » de l'entete de la colonne LOGICIELS : menu des logiciels des reglages (ceux deja
presents grises), le choix cree le dossier du logiciel (« houdini ») dans la colonne et le selectionne."""
import os as _os, sys as _sys  # jamais les vrais reglages / presets de l'utilisateur (tests/_isolate.py)
_sys.path.insert(0, _os.path.dirname(_os.path.abspath(__file__)))
import _isolate  # noqa: E402,F401
import os
import shutil
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from PySide6.QtWidgets import QApplication

app = QApplication.instance() or QApplication([])

import app_style
import browser_core
import column as column_module
from column import Column


class SoftwareMenuTest(unittest.TestCase):
    def setUp(self):
        self.root = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.root, True)
        (self.root / "maya").mkdir()
        app_style.set_custom_softwares([{"key": "GAFFER", "label": "Gaffer"}])
        app_style.set_removed_softwares(["ZBRUSH"])
        self.addCleanup(app_style.set_custom_softwares, [])
        self.addCleanup(app_style.set_removed_softwares, [])

    def _column(self, kind="logiciels"):
        column = Column(self.root, "Logiciels", source_dirs=[self.root], group_kind=kind)
        column.resize(240, 400)
        column.show()
        column.refresh()
        self.addCleanup(column.deleteLater)
        app.processEvents()
        return column

    def test_choices_follow_the_settings_list(self):
        choices = browser_core.software_choices()
        keys = [key for key, _label, _folder in choices]
        self.assertIn(("HOUDINI", "Houdini", "houdini"), choices)
        self.assertNotIn("ZBRUSH", keys)
        self.assertEqual(choices[-1], ("GAFFER", "Gaffer", "gaffer"))

    def test_only_the_software_column_has_the_button(self):
        self.assertTrue(hasattr(self._column(), "_software_btn"))
        self.assertFalse(hasattr(self._column("in"), "_software_btn"))

    def test_menu_greys_existing_and_choice_creates_the_folder(self):
        column = self._column()
        seen = {}

        class FakeMenu(column_module.Menu):
            def exec(self, *_args):
                actions = {a.data(): a for a in self.actions()}
                seen["maya"] = actions["maya"].isEnabled()
                return actions["houdini"]

        with mock.patch.object(column_module, "Menu", FakeMenu):
            column._open_software_menu()
        self.assertFalse(seen["maya"])
        self.assertTrue((self.root / "houdini").is_dir())
        current = column.list.currentItem()
        self.assertIsNotNone(current)
        self.assertEqual(Path(current.data(browser_core.ROLE_PATH)), self.root / "houdini")


if __name__ == "__main__":
    unittest.main()
