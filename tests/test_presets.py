"""Presets : preset actif (menu deroulant), preset par defaut au lancement, valeurs a l'ecran enregistrees
dans le preset actif, fenetre « Gerer les presets ». Fichiers TEMPORAIRES : jamais les reglages ni les
presets reels."""
import os as _os, sys as _sys  # jamais les vrais reglages / presets de l'utilisateur (tests/_isolate.py)
_sys.path.insert(0, _os.path.dirname(_os.path.abspath(__file__)))
import _isolate  # noqa: E402,F401
import copy
import json
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

APP = QApplication.instance() or QApplication([])

import settings_store as store
from settings_store import DEFAULT_SETTINGS


class PresetStoreTest(unittest.TestCase):
    def setUp(self):
        self.dir = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.dir, True)
        for name, path in (("_PER_USER_PATH", self.dir / "settings.json"),
                           ("_PRESETS_PATH", self.dir / "presets.json")):
            patcher = mock.patch.object(store, name, path)
            patcher.start()
            self.addCleanup(patcher.stop)
        settings = copy.deepcopy(DEFAULT_SETTINGS)
        settings["root_path"] = "D:/projets"
        settings["table_dims"] = {"x#0": {"w": 1}}
        store.save_settings(settings)
        a = dict(settings, colors={**settings["colors"], "accent": "#aa0000"}, button_radius=1, root_path="Z:/autre")
        b = dict(settings, colors={**settings["colors"], "accent": "#00bb00"}, button_radius=9)
        store.save_preset("A", a)
        store.save_preset("B", b)

    def test_preset_never_holds_machine_or_live_state(self):
        presets = store._load_presets()
        for key in ("root_path", "default_preset", "active_preset", "table_dims"):
            self.assertNotIn(key, presets["A"])

    def test_choosing_a_preset_applies_it_and_keeps_the_rest(self):
        settings = store.apply_preset("B")
        self.assertEqual(settings["active_preset"], "B")
        self.assertEqual(settings["colors"]["accent"], "#00bb00")
        self.assertEqual(settings["button_radius"], 9)
        self.assertEqual(settings["root_path"], "D:/projets")             # pas dans un preset
        self.assertEqual(settings["table_dims"], {"x#0": {"w": 1}})        # etat temps reel garde
        self.assertEqual(store.load_settings()["colors"]["accent"], "#00bb00")   # relu : le meme
        store.apply_preset("")
        self.assertEqual(store.load_settings()["active_preset"], "")

    def test_default_preset_is_applied_at_startup_and_becomes_active(self):
        store.apply_preset("B")
        store.set_default_preset("A")
        self.assertEqual(store.load_settings()["colors"]["accent"], "#00bb00")   # en cours : l'actif
        settings = store.load_settings(startup=True)
        self.assertEqual((settings["active_preset"], settings["colors"]["accent"]), ("A", "#aa0000"))
        on_disk = json.loads(store._PER_USER_PATH.read_text(encoding="utf-8"))
        self.assertEqual(on_disk["active_preset"], "A")                   # relectures suivantes : A
        self.assertEqual(store.load_settings()["colors"]["accent"], "#aa0000")

    def test_edits_go_to_the_active_preset(self):
        settings = store.apply_preset("B")
        settings["button_radius"] = 5
        store.save_settings(settings)
        store.update_active_preset(settings)
        self.assertEqual(store._load_presets()["B"]["button_radius"], 5)
        self.assertEqual(store._load_presets()["A"]["button_radius"], 1)
        self.assertEqual(store.load_settings()["button_radius"], 5)

    def test_duplicate_rename_delete(self):
        copy_name = store.duplicate_preset("A")
        self.assertEqual(copy_name, "A copie")
        self.assertEqual(store.duplicate_preset("A"), "A copie 2")
        store.apply_preset("A")
        store.set_default_preset("A")
        self.assertEqual(store.rename_preset("A", "Studio"), "Studio")
        settings = store.load_settings()
        self.assertEqual((settings["active_preset"], settings["default_preset"]), ("Studio", "Studio"))
        self.assertEqual(store.preset_names()[0], "Studio")                # garde sa place
        self.assertEqual(store.rename_preset("Studio", "B"), "B 2")        # nom deja pris
        store.delete_preset("B 2")
        settings = store.load_settings()
        self.assertNotIn("B 2", store.preset_names())
        self.assertEqual((settings["active_preset"], settings["default_preset"]), ("", ""))

    def test_manager_window(self):
        import settings_presets
        store.set_default_preset("A")
        window = settings_presets.PresetManagerWindow(store.load_settings())
        self.addCleanup(window.close)
        changes = []
        window.presetsChanged.connect(lambda: changes.append(1))
        window._new()
        self.assertIn("Nouveau preset", store.preset_names())
        window._duplicate("B")
        self.assertIn("B copie", store.preset_names())
        window._delete("B copie")                                         # 1er clic : confirmation
        self.assertIn("B copie", store.preset_names())
        window._delete("B copie")
        self.assertNotIn("B copie", store.preset_names())
        window._defaults["B"].setChecked(True)                            # un seul preset par defaut
        self.assertEqual(store.load_settings()["default_preset"], "B")
        self.assertFalse(window._defaults["A"].isChecked())
        window._names["B"].setText("Studio VFX")
        window._rename("B", "Studio VFX")
        APP.processEvents()
        self.assertIn("Studio VFX", store.preset_names())
        self.assertEqual(store.load_settings()["default_preset"], "Studio VFX")
        self.assertTrue(changes)

    def test_picker(self):
        import settings_presets
        picker = settings_presets.PresetPicker()
        self.addCleanup(picker.deleteLater)
        chosen = []
        picker.presetChosen.connect(chosen.append)
        picker.refresh(store.apply_preset("A"))
        self.assertEqual(picker.select.value(), "A")
        self.assertEqual(picker.select._options, [settings_presets.NO_PRESET, "A", "B"])
        picker.select._select("B")
        picker.select._select(settings_presets.NO_PRESET)
        self.assertEqual(chosen, ["B", ""])


if __name__ == "__main__":
    unittest.main()
