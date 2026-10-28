"""Fenetre de reglages v2 : apres l'ouverture, pages et sections sont construites EN DOUCE (invisibles), pour
qu'un clic sur une section l'affiche aussitot. Rien n'est modifie par cette construction."""
import os as _os, sys as _sys  # jamais les vrais reglages / presets de l'utilisateur (tests/_isolate.py)
_sys.path.insert(0, _os.path.dirname(_os.path.abspath(__file__)))
import _isolate  # noqa: E402,F401
from _lent import lent  # noqa: E402
import os
import sys
import time
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from PySide6.QtWidgets import QApplication

app = QApplication.instance() or QApplication([])

import settings_window_v2 as v2


@lent
class PrebuildTest(unittest.TestCase):
    def test_everything_is_built_in_the_background_without_a_change(self):
        v2.SettingsWindowV2.PREBUILD = True
        self.addCleanup(setattr, v2.SettingsWindowV2, "PREBUILD", False)
        v2.SettingsWindowV2.PREBUILD_GAP_MS = 0
        v2.SettingsWindowV2.PREBUILD_DUTY = 1.0          # pas de repos entre etapes : le test va vite
        v2.SettingsWindowV2.PREBUILD_IDLE_MS = 0         # et ne depend pas de l activite de la machine
        self.addCleanup(setattr, v2.SettingsWindowV2, "PREBUILD_DUTY", 0.25)
        self.addCleanup(setattr, v2.SettingsWindowV2, "PREBUILD_IDLE_MS", 600)
        win = v2.SettingsWindowV2()
        self.addCleanup(win.deleteLater)
        win.show()
        end = time.monotonic() + 120
        while time.monotonic() < end:
            app.processEvents()
            nodes = win.findChildren(v2._LazyNode)
            if len(win._built) == len(v2.SCOPES) and nodes and all(n._built for n in nodes):
                break
        nodes = win.findChildren(v2._LazyNode)
        self.assertEqual(len(win._built), len(v2.SCOPES))
        self.assertTrue(all(n._built for n in nodes))
        self.assertTrue(all(n.is_collapsed() for n in nodes))        # construites sans etre ouvertes
        self.assertFalse(win._dirty)                                 # et sans rien modifier
        node = next(n for n in nodes if n.node.title == "Visionneuse")
        start = time.perf_counter()
        node.set_collapsed(False)                                    # un clic : deja construite
        self.assertLess(time.perf_counter() - start, 0.5)


if __name__ == "__main__":
    unittest.main()
