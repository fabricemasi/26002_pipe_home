"""Fenetre de reglages v2 : tant qu'une modification n'est pas enregistree, la bordure de la fenetre est
ROUGE (M["dirty_frame"]) ; a l'ouverture et apres Appliquer / Enregistrer, la bordure normale."""
import os as _os, sys as _sys  # jamais les vrais reglages / presets de l'utilisateur (tests/_isolate.py)
_sys.path.insert(0, _os.path.dirname(_os.path.abspath(__file__)))
import _isolate  # noqa: E402,F401
import os
import sys
import time
import unittest
from unittest import mock

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from PySide6.QtWidgets import QApplication

app = QApplication.instance() or QApplication([])

import settings_window_v2 as v2
from settings_store import M
from settings_widgets import _Toggle


class DirtyFrameTest(unittest.TestCase):
    def test_border_is_red_until_saved(self):
        win = v2.SettingsWindowV2()
        self.addCleanup(win.deleteLater)
        win.show()
        end = time.monotonic() + 0.5
        while time.monotonic() < end:
            app.processEvents()
        self.assertIsNone(win.panel._alert)          # rien de modifie a l'ouverture
        win._mark_dirty()                                               # un champ change (voir _connect_changed)
        self.assertEqual(win.panel._alert, M["dirty_frame"])
        with mock.patch.object(v2, "save_settings"), mock.patch.object(v2, "update_active_preset"):
            win._on_apply()
        self.assertIsNone(win.panel._alert)
        self.assertFalse(win._dirty)

    def test_clicking_the_unsaved_label_saves_and_it_is_red(self):
        from PySide6.QtCore import Qt
        from PySide6.QtTest import QTest
        win = v2.SettingsWindowV2()
        self.addCleanup(win.deleteLater)
        win.show()
        app.processEvents()
        label = win.titlebar.dirty_label
        QTest.mouseClick(label, Qt.LeftButton)                       # « a jour » : rien
        win._mark_dirty()
        self.assertIn(M["dirty_frame"], label.styleSheet())           # texte rouge
        with mock.patch.object(v2, "save_settings") as save, mock.patch.object(v2, "update_active_preset"):
            QTest.mouseClick(label, Qt.LeftButton)
        save.assert_called_once()
        self.assertFalse(win._dirty)
        self.assertEqual(label.text(), "a jour")
        self.assertIsNone(win.panel._alert)

    def test_a_real_field_change_turns_it_red(self):
        win = v2.SettingsWindowV2()
        self.addCleanup(win.deleteLater)
        win.show()
        v2.expand_all(win.stack.currentWidget())
        for node in win.stack.currentWidget().findChildren(v2._LazyNode):
            node.set_collapsed(False)
        app.processEvents()
        toggle = next(t for t in win.findChildren(_Toggle) if t.isEnabled())
        self.assertIsNone(win.panel._alert)
        toggle.setChecked(not toggle.isChecked())
        app.processEvents()
        self.assertEqual(win.panel._alert, M["dirty_frame"])
        win.reject()


if __name__ == "__main__":
    unittest.main()
