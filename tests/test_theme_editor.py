"""Éditeur fm_theme (theme_editor.py, fm_theme.bat) : onglet « Thème » réduit à l'aspect, magasin qui écrit
l'aspect dans le preset fm_theme et le reste dans les réglages de l'appli, gestion des presets (renommer =
alias retrouvé, dupliquer, nouveau, supprimer). Presets et réglages : copies temporaires (_isolate)."""
import _isolate  # noqa: F401
import os
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from PySide6.QtWidgets import QApplication  # noqa: E402

import settings_store  # noqa: E402
import settings_window_v2 as v2  # noqa: E402
import theme_editor  # noqa: E402
from fm_theme import presets as tp  # noqa: E402
from _window_cleanup import WindowTestCase, track_class  # noqa: E402

APP = QApplication.instance() or QApplication([])
track_class(v2.SettingsWindowV2)


def fresh_preset(name: str) -> str:
    """Preset de test (copie des défauts), nom unique."""
    return tp.new_preset(name, settings_store.DEFAULT_SETTINGS)


class TreeTest(unittest.TestCase):
    def test_theme_tab_holds_only_the_aspect(self):
        titles = [n.title for n in v2.theme_tree()]
        self.assertEqual(titles[0], "Général")
        self.assertIn("Couleurs", titles)
        self.assertIn("Toggles", titles)
        for app_only in ("Colonnes", "Barre de navigation", "LUT", "Application", "ICONES"):
            self.assertNotIn(app_only, titles)
        self.assertEqual([s.key for s in v2.CATALOG["Thème : Général"]], ["ui_scale", "window_radius"])


class StoreTest(unittest.TestCase):
    def test_aspect_goes_to_the_preset_and_the_rest_to_the_app(self):
        name = fresh_preset("Magasin")
        store = theme_editor.ThemeStore(name)
        self.assertEqual(store.load()["button_radius"], settings_store.DEFAULT_SETTINGS["button_radius"])
        saved = store.save_changes({"button_radius": 9, "table_dims": {"x#0": {"width": 1}}})
        self.assertEqual(saved["button_radius"], 9)
        self.assertEqual(tp.to_settings(tp.load_preset(tp.find_preset(name)))["button_radius"], 9)
        self.assertNotIn("table_dims", tp.to_settings(tp.load_preset(tp.find_preset(name))))
        self.assertEqual(settings_store.load_settings()["table_dims"].get("x#0"), {"width": 1})
        tp.delete_preset(name)


class ManagementTest(unittest.TestCase):
    def test_rename_keeps_the_old_name_as_alias(self):
        name = fresh_preset("Ancien")
        new = tp.rename_preset(name, "Nouveau nom")
        self.assertEqual(tp.find_preset(name), tp.find_preset(new))
        self.assertEqual(tp.load_preset(tp.find_preset(name))["nom"], new)
        # Une appli liée à l'ancien nom garde son thème.
        self.assertEqual(settings_store.theme_in_use({"theme_preset": name}), name)
        tp.delete_preset(new)
        self.assertIsNone(tp.find_preset(name))

    def test_duplicate_and_unique_names(self):
        name = fresh_preset("Double")
        copy = tp.duplicate_preset(name)
        self.assertEqual(copy, f"{name} copie")
        self.assertEqual(tp.unique_name(name), f"{name} 2")
        self.assertEqual(tp.to_settings(tp.load_preset(tp.find_preset(copy))),
                         tp.to_settings(tp.load_preset(tp.find_preset(name))))
        for n in (name, copy):
            tp.delete_preset(n)


class EditorTest(WindowTestCase):
    def test_editor_switches_presets_and_deletes_in_two_clicks(self):
        first, second = fresh_preset("Premier"), fresh_preset("Second")
        editor = theme_editor.ThemeEditor(first)
        self.assertEqual(editor.window.module, "theme")
        self.assertEqual(editor.window.titlebar._title.text(), f"fm_theme : {first}")
        editor.switch_to(second)
        self.assertEqual(editor.name, second)
        bar = editor.window._tab_subbar.findChild(theme_editor.PresetBar)
        bar._delete()
        self.assertIsNotNone(tp.find_preset(second))            # 1er clic : confirmation demandée
        bar._delete()
        self.assertIsNone(tp.find_preset(second))
        self.assertNotEqual(editor.name, second)
        editor.window.hide()
        tp.delete_preset(first)


if __name__ == "__main__":
    unittest.main()
