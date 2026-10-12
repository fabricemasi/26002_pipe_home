"""Valeurs de punaise d'une colonne (punaise, largeur, hauteur de ligne, options retenues avec elle) :
propres au PRESET en cours (demande de l'utilisateur) ; le reste du fichier de mise en page est commun."""
import os as _os, sys as _sys  # jamais les vrais reglages / presets de l'utilisateur (tests/_isolate.py)
_sys.path.insert(0, _os.path.dirname(_os.path.abspath(__file__)))
import _isolate  # noqa: E402,F401
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import browser_core as bc
import ui_state


class PinPerPresetTest(unittest.TestCase):
    def setUp(self):
        self.saved = ui_state.APPLIED_SETTINGS
        self.addCleanup(setattr, ui_state, "APPLIED_SETTINGS", self.saved)
        self.dir = Path(tempfile.mkdtemp())

    def use(self, preset):
        ui_state.APPLIED_SETTINGS = {"active_preset": preset, "default_preset": "fab"}

    def test_each_preset_has_its_own_pin_values(self):
        self.use("fab")
        bc.save_layout_settings(self.dir, {"pinned": True, "pinned_column_width": 300, "item_order": ["a"]})
        self.use("Studio VFX")
        self.assertEqual(bc.load_layout_settings(self.dir), {"item_order": ["a"]})   # rien de « fab »
        bc._update_layout_setting(self.dir, "pinned_row_height", 40)
        self.use("fab")
        view = bc.load_layout_settings(self.dir)
        self.assertEqual((view["pinned"], view["pinned_column_width"], view["item_order"]), (True, 300, ["a"]))
        self.assertNotIn("pinned_row_height", view)
        self.use("Studio VFX")
        self.assertEqual(bc.load_layout_settings(self.dir)["pinned_row_height"], 40)

    def test_old_shared_values_go_to_the_first_preset_that_reads_them(self):
        (self.dir / bc.LAYOUT_SETTINGS_FILENAME).write_text(
            json.dumps({"pinned": True, "pinned_column_width": 250, "item_order": ["x"]}), encoding="utf-8")
        self.use("fab")
        self.assertEqual(bc.load_layout_settings(self.dir)["pinned_column_width"], 250)
        self.use("Studio VFX")
        self.assertNotIn("pinned", bc.load_layout_settings(self.dir))
        raw = json.loads((self.dir / bc.LAYOUT_SETTINGS_FILENAME).read_text(encoding="utf-8"))
        self.assertNotIn("pinned", raw)
        self.assertEqual(raw["by_preset"]["fab"]["pinned_column_width"], 250)


class ColumnFollowsPresetTest(PinPerPresetTest):
    def use(self, preset):
        import settings_store
        ui_state.APPLIED_SETTINGS = {**settings_store.load_settings(), "active_preset": preset}

    def test_column_takes_the_pin_of_the_new_preset(self):
        from unittest import mock
        from PySide6.QtWidgets import QApplication
        app = QApplication.instance() or QApplication([])
        import pipeline_browser as pb
        import settings_store
        for module in (settings_store, pb, bc):
            for name in ("save_settings", "_save_window_geometry"):
                if hasattr(module, name):
                    patcher = mock.patch.object(module, name, lambda *a, **k: None)
                    patcher.start()
                    self.addCleanup(patcher.stop)
        (self.dir / "3d").mkdir()
        self.use("fab")
        win = pb.PipelineBrowser(self.dir)
        win._idle_preview_scheduler.timer.stop()
        win.show()
        app.processEvents()
        try:
            column = win.columns[0]
            column.setFixedWidth(333)
            column._toggle_pin()
            self.assertTrue(column._pin_active)
            self.use("Studio VFX")
            column.reload_pin_state()
            self.assertFalse(column._pin_active)
            self.use("fab")
            column.reload_pin_state()
            self.assertTrue(column._pin_active)
            self.assertEqual(column.width(), 333)
        finally:
            win.close()
            for _ in range(10):
                app.processEvents()


if __name__ == "__main__":
    unittest.main()
