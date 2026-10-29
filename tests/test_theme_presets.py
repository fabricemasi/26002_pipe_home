"""Presets fm_theme (fm_theme/presets.py) : format, aller-retour sans perte, accord avec l'inventaire validé,
fichiers (écriture, lecture, format trop récent) et convertisseur. Fichiers temporaires seulement."""
import _isolate  # noqa: F401
import json
import sys
import tempfile
import unittest
from pathlib import Path

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


if __name__ == "__main__":
    unittest.main()
