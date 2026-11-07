"""Presets : la liste est CELLE DE fm_theme (créés / renommés / supprimés seulement dans fm_theme) ; fm_browser
y ajoute sa couche de réglages par nom. Preset actif (menu déroulant), preset par défaut au lancement, valeurs à
l'écran enregistrées dans le preset actif, fenêtre « Gérer les presets », suivi du dossier. Fichiers TEMPORAIRES :
jamais les réglages ni les presets réels."""
import os as _os, sys as _sys  # jamais les vrais reglages / presets de l'utilisateur (tests/_isolate.py)
_sys.path.insert(0, _os.path.dirname(_os.path.abspath(__file__)))
import _isolate  # noqa: E402,F401
import copy
import json
import os
import shutil
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from PySide6.QtWidgets import QApplication

APP = QApplication.instance() or QApplication([])

import fm_theme.presets as tp
import settings_store as store
from settings_store import DEFAULT_SETTINGS


class PresetStoreTest(unittest.TestCase):
    def setUp(self):
        self.dir = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.dir, True)
        for module, name, path in ((store, "_PER_USER_PATH", self.dir / "settings.json"),
                                   (store, "_PRESETS_PATH", self.dir / "presets.json"),
                                   (tp, "PRESETS_DIR", self.dir / "theme")):
            patcher = mock.patch.object(module, name, path)
            patcher.start()
            self.addCleanup(patcher.stop)
        settings = copy.deepcopy(DEFAULT_SETTINGS)
        settings["root_path"] = "D:/projets"
        settings["table_dims"] = {"x#0": {"w": 1}}
        store.save_settings(settings)
        # Presets fm_theme (aspect) : A et B ; couches de fm_browser (item_row_spacing, propre à l'appli).
        for name, accent, radius in (("A", "#aa0000", 1), ("B", "#00bb00", 9)):
            tp.save_preset(tp.from_settings({"colors": {**settings["colors"], "accent": accent},
                                             "button_radius": radius}, name))
        store._save_presets({"A": {"item_row_spacing": 3}, "B": {"item_row_spacing": 7}})

    def test_list_is_the_fm_theme_list(self):
        self.assertEqual(store.preset_names(), ["A", "B"])
        tp.save_preset(tp.from_settings({"button_radius": 4}, "neo"))      # créé dans fm_theme
        self.assertEqual(store.preset_names(), ["A", "B", "neo"])
        store.save_preset("inconnu", store.load_settings())                # jamais créé ici
        self.assertNotIn("inconnu", store._load_presets())
        self.assertNotIn("inconnu", store.preset_names())

    def test_preset_never_holds_machine_or_live_state(self):
        presets = store._load_presets()
        store.save_preset("A", dict(store.load_settings(), root_path="Z:/autre", button_radius=2))
        presets = store._load_presets()
        for key in ("root_path", "default_preset", "active_preset", "table_dims", "theme_preset", "button_radius"):
            self.assertNotIn(key, presets["A"])
        self.assertEqual(tp.to_settings(tp.load_preset(tp.find_preset("A")))["button_radius"], 2)   # au thème

    def test_choosing_a_preset_applies_its_theme_and_layer(self):
        settings = store.apply_preset("B")
        self.assertEqual((settings["active_preset"], settings["theme_preset"]), ("B", "B"))
        self.assertEqual(settings["colors"]["accent"], "#00bb00")           # aspect : le preset fm_theme B
        self.assertEqual(settings["button_radius"], 9)
        self.assertEqual(settings["item_row_spacing"], 7)                      # couche de fm_browser B
        self.assertEqual(settings["root_path"], "D:/projets")             # pas dans un preset
        self.assertEqual(settings["table_dims"], {"x#0": {"w": 1}})        # etat temps reel garde
        self.assertEqual(store.load_settings()["colors"]["accent"], "#00bb00")   # relu : le meme

    def test_same_name_same_theme(self):
        """Le défaut signalé : « neo » des deux côtés mais deux thèmes différents. Plus possible."""
        tp.save_preset(tp.from_settings({"button_radius": 4}, "neo"))
        layers = store._load_presets()
        layers["neo"] = {"item_row_spacing": 2, "theme_preset": "A"}            # ancien lien vers un autre thème
        store._save_presets(layers)
        settings = store.apply_preset("neo")
        self.assertEqual((settings["theme_preset"], settings["button_radius"]), ("neo", 4))
        self.assertEqual(settings["item_row_spacing"], 2)

    def test_deleted_or_renamed_in_fm_theme(self):
        store.apply_preset("B")
        store.set_default_preset("A")
        os.remove(tp.find_preset("B"))                                      # supprimé dans fm_theme
        self.assertNotIn("B", store.preset_names())
        self.assertEqual(store.preset_in_use(store.load_settings()), "A")  # repli : le preset par défaut
        tp.rename_preset("A", "Studio")                                     # renommé dans fm_theme
        settings = store.apply_preset("A")                                  # ancien nom : alias
        self.assertEqual((settings["active_preset"], settings["item_row_spacing"]), ("Studio", 3))
        store.update_active_preset(settings)
        self.assertIn("Studio", store._load_presets())                      # la couche suit le renommage
        self.assertNotIn("A", store._load_presets())

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
        settings.update(button_radius=5, item_row_spacing=11)
        store.save_settings(settings)
        store.update_active_preset(settings)
        self.assertEqual(store._load_presets()["B"]["item_row_spacing"], 11)  # couche de fm_browser
        self.assertEqual(tp.to_settings(tp.load_preset(tp.find_preset("B")))["button_radius"], 5)   # thème
        self.assertEqual(store._load_presets()["A"]["item_row_spacing"], 3)
        self.assertEqual(store.load_settings()["button_radius"], 5)

    def test_manager_window(self):
        import settings_presets
        store.apply_preset("A")
        store.set_default_preset("A")
        window = settings_presets.PresetManagerWindow(store.load_settings())
        self.addCleanup(window.close)
        for gone in ("_new", "_duplicate", "_delete", "_rename"):        # ni création, ni suppression ici
            self.assertFalse(hasattr(window, gone))
        changes = []
        window.presetsChanged.connect(lambda: changes.append(1))
        window._defaults["B"].setChecked(True)                            # un seul preset par defaut
        self.assertEqual(store.load_settings()["default_preset"], "B")
        self.assertFalse(window._defaults["A"].isChecked())
        tp.save_preset(tp.from_settings({"button_radius": 4}, "neo"))
        window.refresh()
        self.assertEqual(list(window._defaults), ["A", "B", "neo"])
        import ui_state
        self.addCleanup(setattr, ui_state, "APPLIED_SETTINGS", ui_state.APPLIED_SETTINGS)
        ui_state.APPLIED_SETTINGS = dict(store.load_settings(), item_row_spacing=9)   # a l'ecran
        window._save("A")                                                  # « Enregistrer » le preset actif
        self.assertEqual(store._load_presets()["A"]["item_row_spacing"], 9)
        self.assertTrue(changes)

    def test_picker(self):
        import settings_presets
        picker = settings_presets.PresetPicker()
        self.addCleanup(picker.deleteLater)
        chosen = []
        picker.presetChosen.connect(chosen.append)
        picker.refresh(store.apply_preset("A"))
        self.assertEqual(picker.select.value(), "A")
        self.assertEqual(picker.select._options, ["A", "B"])               # la liste de fm_theme, sans « (Aucun) »
        picker.select._select("B")
        self.assertEqual(chosen, ["B"])

    def test_main_window_follows_the_fm_theme_list(self):
        import ui_state
        from main_window.settings_link import SettingsLinkMixin

        class Window(SettingsLinkMixin):
            _preset_manager = None

            def __init__(self):
                self.chosen, self.refreshed = [], 0

            def _choose_preset(self, name):
                self.chosen.append(name)

            def _refresh_preset_ui(self, settings=None):
                self.refreshed += 1

        self.addCleanup(setattr, ui_state, "APPLIED_SETTINGS", ui_state.APPLIED_SETTINGS)
        ui_state.APPLIED_SETTINGS = store.apply_preset("B")
        store.set_default_preset("A")
        window = Window()
        tp.save_preset(tp.from_settings({"button_radius": 4}, "neo"))      # créé : la liste seule est relue
        window._on_theme_list_changed()
        self.assertEqual((window.chosen, window.refreshed), ([], 1))
        os.remove(tp.find_preset("B"))                                      # le preset à l'écran est supprimé
        window._on_theme_list_changed()
        self.assertEqual(window.chosen, ["A"])

    def test_list_watcher_sees_creation_and_deletion(self):
        from fm_theme import live
        watcher = live.PresetListWatcher(tp.PRESETS_DIR)
        self.addCleanup(watcher.deleteLater)
        seen = []
        watcher.changed.connect(lambda: seen.append(1))

        def wait():
            deadline = time.monotonic() + 3
            count = len(seen)
            while len(seen) == count and time.monotonic() < deadline:
                APP.processEvents()
                time.sleep(0.01)

        tp.save_preset(tp.from_settings({"button_radius": 4}, "neo"))
        wait()
        self.assertEqual(len(seen), 1)
        os.remove(tp.find_preset("neo"))
        wait()
        self.assertEqual(len(seen), 2)


if __name__ == "__main__":
    unittest.main()
