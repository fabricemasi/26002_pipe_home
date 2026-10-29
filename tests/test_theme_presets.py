"""Presets fm_theme (fm_theme/presets.py) : format, aller-retour sans perte, accord avec l'inventaire validé,
fichiers (écriture, lecture, format trop récent) et convertisseur. Fichiers temporaires seulement."""
import _isolate  # noqa: F401
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import settings_store
from fm_theme import presets as tp

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "tools"))
import inventaire_reglages as inv  # noqa: E402


def theme_part(values: dict) -> dict:
    return {k: v for k, v in values.items() if tp.theme_key(k)}


class FormatTest(unittest.TestCase):
    def test_keys_are_exactly_the_validated_inventory(self):
        """Les clés d'un preset fm_theme = les clés « aspect générique » de l'inventaire validé."""
        inventory = {k for k, v in settings_store.DEFAULT_SETTINGS.items() if inv.classify(k, v)[0] == inv.THEME}
        theme = set(theme_part(settings_store.DEFAULT_SETTINGS))
        self.assertEqual(inventory, theme)

    def test_round_trip_keeps_every_value(self):
        values = theme_part(settings_store.DEFAULT_SETTINGS)
        preset = json.loads(json.dumps(tp.from_settings(values, "défauts")))
        self.assertEqual(tp.to_settings(preset), values)

    def test_types_and_variants(self):
        values = {"colors": {"accent": "#ff0000"}, "font_main": {"size": 12}, "toggle_style": "toggle3",
                  "toggle3_outer_width": 40, "toggle1_outer_width": 30, "title_level1_font_size": 14,
                  "table_dims": {"x": 1}, "root_path": "F:/", "crumb_bg_color": "#000"}
        preset = tp.from_settings(values, "essai")
        self.assertEqual(preset["format"], tp.FORMAT)
        self.assertEqual(preset["general"], {"colors": {"accent": "#ff0000"}, "font_main": {"size": 12}})
        self.assertEqual(preset["types"]["toggle"]["defaut"], "toggle3")
        self.assertEqual(preset["types"]["toggle"]["variantes"]["toggle3"], {"outer_width": 40})
        self.assertEqual(preset["types"]["titres"], {"defaut": "standard",
                                                     "variantes": {"standard": {"level1_font_size": 14}}})
        # État de l'appli, fonctionnement, aspect propre à l'appli : jamais dans un preset fm_theme.
        self.assertNotIn("table_dims", tp.to_settings(preset))
        self.assertNotIn("root_path", tp.to_settings(preset))
        self.assertNotIn("crumb_bg_color", tp.to_settings(preset))

    def test_unknown_type_is_ignored(self):
        preset = {"format": 1, "nom": "x", "general": {}, "types": {"futur": {"variantes": {"a": {"b": 1}}}}}
        self.assertEqual(tp.to_settings(preset), {})


class FilesTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.folder = Path(self._tmp.name)

    def tearDown(self):
        self._tmp.cleanup()

    def test_presets_dir_is_redirected_in_tests(self):
        self.assertNotEqual(tp.PRESETS_DIR, Path(tp.__file__).resolve().parent / "presets")

    def test_save_load_list(self):
        preset = tp.from_settings({"window_radius": 8, "button_radius": 3}, 'Studio: "VFX"')
        path = tp.save_preset(preset, self.folder)
        self.assertEqual(path.name, "Studio_ _VFX_.json")
        self.assertEqual(tp.load_preset(path), preset)
        self.assertEqual(tp.list_presets(self.folder), {'Studio: "VFX"': path})
        self.assertEqual(list(self.folder.glob("*.tmp")), [])

    def test_newer_format_is_refused(self):
        path = self.folder / "futur.json"
        path.write_text(json.dumps({"format": tp.FORMAT + 1, "nom": "futur"}), encoding="utf-8")
        with self.assertRaises(ValueError):
            tp.load_preset(path)
        self.assertEqual(tp.list_presets(self.folder), {})

    def test_converter_loses_nothing(self):
        source = self.folder / "presets.json"
        old = {"fab": dict(settings_store.DEFAULT_SETTINGS, toggle3_outer_width=50, root_path="F:/"),
               "Vide": {"root_path": "G:/"}}
        source.write_text(json.dumps(old), encoding="utf-8")
        before = source.read_text(encoding="utf-8")
        paths = tp.convert_presets(source, self.folder / "out")
        self.assertEqual(len(paths), 2)
        self.assertEqual(source.read_text(encoding="utf-8"), before)          # la source n'est pas modifiée
        for name, values in old.items():
            preset = tp.load_preset(tp.preset_path(name, self.folder / "out"))
            self.assertEqual(tp.to_settings(preset), theme_part(values))


class VariantTest(unittest.TestCase):
    """Plusieurs variantes par type : seule celle par défaut arrive à plat dans les applis."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.folder = Path(self._tmp.name)
        tp.save_preset(tp.from_settings({"button_radius": 2, "button_height": 24, "window_radius": 8}, "p"),
                       self.folder)

    def tearDown(self):
        self._tmp.cleanup()

    def preset(self):
        return tp.load_preset(tp.find_preset("p", self.folder))

    def test_new_variant_is_edited_apart_and_only_the_default_is_flat(self):
        compact = tp.add_variant("p", "bouton", "compact", folder=self.folder)
        tp.update_preset("p", {"button_radius": 9}, folder=self.folder, editing={"bouton": compact})
        self.assertEqual(tp.to_settings(self.preset())["button_radius"], 2)          # défaut : standard
        self.assertEqual(tp.type_flat(self.preset(), "bouton", compact),
                         {"button_radius": 9, "button_height": 24})
        tp.update_preset("p", {"window_radius": 3}, folder=self.folder)           # sans variante : rien d'autre
        self.assertEqual(self.preset()["types"]["bouton"]["variantes"]["standard"]["radius"], 2)
        tp.set_default_variant("p", "bouton", compact, folder=self.folder)
        self.assertEqual(tp.to_settings(self.preset())["button_radius"], 9)

    def test_rename_keeps_an_alias_and_delete_never_leaves_none(self):
        compact = tp.add_variant("p", "bouton", "compact", folder=self.folder)
        tp.set_default_variant("p", "bouton", compact, folder=self.folder)
        new = tp.rename_variant("p", "bouton", compact, "serré", folder=self.folder)
        self.assertEqual(tp.resolve_variant(self.preset(), "bouton", "compact"), new)
        self.assertEqual(self.preset()["types"]["bouton"]["defaut"], new)
        tp.delete_variant("p", "bouton", new, folder=self.folder)
        self.assertEqual(tp.variant_names(self.preset(), "bouton"), ["standard"])
        self.assertEqual(self.preset()["types"]["bouton"]["defaut"], "standard")
        tp.delete_variant("p", "bouton", "standard", folder=self.folder)           # la dernière : gardée
        self.assertEqual(tp.variant_names(self.preset(), "bouton"), ["standard"])
        self.assertEqual(tp.add_variant("p", "bouton", "standard", folder=self.folder), "standard 2")


class LinkedThemeTest(unittest.TestCase):
    """fm_browser lit et écrit son aspect générique dans le preset fm_theme lié (`theme_preset`)."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        root = Path(self._tmp.name)
        self._patches = [mock.patch.object(settings_store, "_PER_USER_PATH", root / "settings.json"),
                         mock.patch.object(settings_store, "_PRESETS_PATH", root / "presets.json"),
                         mock.patch.object(tp, "PRESETS_DIR", root / "theme")]
        for patch in self._patches:
            patch.start()
        # Preset de l'appli « fab » (ancien format : aspect compris) et preset fm_theme « fab » converti.
        app = {"window_radius": 3, "button_radius": 2, "crumb_spacing": 5}
        (root / "presets.json").write_text(json.dumps({"fab": app}), encoding="utf-8")
        tp.save_preset(tp.from_settings({"window_radius": 9, "button_radius": 7}, "fab"))
        settings_store.save_settings({"default_preset": "fab"})

    def tearDown(self):
        for patch in self._patches:
            patch.stop()
        self._tmp.cleanup()

    def test_startup_links_the_same_name_and_reads_the_theme(self):
        settings = settings_store.load_settings(startup=True)
        self.assertEqual(settings_store._load_presets()["fab"]["theme_preset"], "fab")
        self.assertEqual(settings["theme_preset"], "fab")
        self.assertEqual(settings["window_radius"], 9)          # aspect : le preset fm_theme l'emporte
        self.assertEqual(settings["crumb_spacing"], 5)          # le reste : le preset de l'appli

    def test_saved_aspect_goes_to_the_theme_and_the_rest_to_the_app_preset(self):
        settings = settings_store.load_settings(startup=True)
        settings.update(window_radius=12, crumb_spacing=8)
        settings_store.save_settings(settings)
        settings_store.update_active_preset(settings)
        theme = tp.to_settings(tp.load_preset(tp.preset_path("fab")))
        self.assertEqual(theme["window_radius"], 12)
        app = settings_store._load_presets()["fab"]
        self.assertEqual(app["crumb_spacing"], 8)
        self.assertNotIn("window_radius", app)                  # source unique : le preset fm_theme
        self.assertEqual(settings_store.load_settings()["window_radius"], 12)

    def test_unchanged_theme_is_not_rewritten(self):
        settings = settings_store.load_settings(startup=True)
        settings_store.update_active_preset(settings)           # 1er enregistrement : preset complété
        path = tp.preset_path("fab")
        before = path.stat().st_mtime_ns
        self.assertFalse(settings_store.update_theme_preset(settings_store.load_settings()))
        self.assertEqual(path.stat().st_mtime_ns, before)

    def test_without_any_theme_the_current_look_becomes_one(self):
        """Étape 6 : l'aspect ne se règle plus que dans fm_theme ; sans thème lié, l'aspect actuel en devient un."""
        settings_store._save_presets({})
        settings_store.save_settings({"button_radius": 5})
        settings = settings_store.load_settings(startup=True)
        name = settings["theme_preset"]
        self.assertTrue(name.startswith("Thème actuel"))
        self.assertEqual(tp.to_settings(tp.load_preset(tp.find_preset(name)))["button_radius"], 5)
        self.assertEqual(settings_store.load_settings()["theme_preset"], name)   # retenu dans le fichier
        self.assertEqual(settings_store.load_settings(startup=True)["theme_preset"], name)   # pas un 2e

    def test_preset_manager_links_another_theme(self):
        settings_store.load_settings(startup=True)
        tp.save_preset(tp.from_settings({"window_radius": 1}, "autre"))
        settings_store.set_preset_theme("fab", "autre")
        self.assertEqual(settings_store.load_settings()["window_radius"], 1)

    def test_missing_theme_keeps_the_aspect_in_the_app_preset(self):
        settings = settings_store.load_settings(startup=True)
        settings["theme_preset"] = "inconnu"
        self.assertEqual(settings_store.theme_in_use(settings), "")
        self.assertIn("window_radius", settings_store.preset_values(settings))


if __name__ == "__main__":
    unittest.main()
