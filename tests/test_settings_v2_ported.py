"""Sections de la v1 portees dans la fenetre de reglages v2 : Application, omissions, LUT, Polices
principales, Couleurs, Geometrie, ICONES, RACCOURCI ; General > Colonnes speciales (Colonne Focus :
Image, Zone titre ; Colonne Projets : Icone de niveaux). Memes valeurs que la v1 sur les memes
reglages, lignes propres a une colonne ecrites dans les cles generales, pastilles liees."""
import os as _os, sys as _sys  # jamais les vrais reglages / presets de l'utilisateur (tests/_isolate.py)
_sys.path.insert(0, _os.path.dirname(_os.path.abspath(__file__)))
import _isolate  # noqa: E402,F401
import copy
import os
import sys
import unittest
from unittest import mock

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from PySide6.QtWidgets import QApplication, QMessageBox

app = QApplication.instance() or QApplication([])

import settings_v2_app
import settings_window_v2 as v2
from settings_store import DEFAULT_SETTINGS as _DEFAULTS
from settings_widgets import _SliderField, _Toggle
from _v1_reference import VALUES_PROJETS as V1_VALUES

v2.AUTOSAVE = False
_real = v2.load_settings


def setUpModule():
    v2.load_settings = lambda: copy.deepcopy(_DEFAULTS)


def tearDownModule():
    v2.load_settings = _real


PORTED = ("Application", "Dossiers et fichiers à omettre", "LUT", "Polices principales", "Couleurs",
          "ICONES", "Colonnes", "Raccourci", "Colonnes spéciales", "Colonne Projets", "Colonne Focus",
          "Image", "Zone titre", "Icône de niveaux")


def open_nodes(win, index: int, titles: tuple):
    win._show_page(index)
    page = win.stack.widget(index)
    for _ in range(3):
        for node in page.findChildren(v2._LazyNode):
            parent = node.parentWidget()
            while parent is not None and not isinstance(parent, v2._LazyNode):
                parent = parent.parentWidget()
            if node.node.title in titles or (parent is not None and parent.node.title in titles):
                node.set_collapsed(False)
        app.processEvents()
    return page


def field(win, label: str, key: str):
    return next(w for spec, w in win.stores[label]["specs"] if not isinstance(spec, str) and spec.key == key)


class PortedSectionsTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.win = v2.SettingsWindowV2()
        cls.labels = [label for label, _title in v2.SCOPES]
        open_nodes(cls.win, 0, PORTED)

    @classmethod
    def tearDownClass(cls):
        cls.win.deleteLater()
        app.processEvents()

    def test_values_match_the_v1_window(self):
        # Valeurs lues par l'ancienne fenetre v1 (retiree), figees : _v1_reference.py.
        expected = V1_VALUES
        values = self.win.wired_values()
        groups = ("Application", "Omettre", "LUT", "Polices principales", "Raccourci",
                  "Icones : Logiciels", "Focus : Zone titre", "Projets : Icone de niveaux")
        keys = set()
        for group in groups:
            for spec in v2.CATALOG[group]:
                keys.update(k for k in (spec.key, *spec.extra_keys) if k in expected)
        keys |= {"colors", "preview_padding", "preview_radius"}
        self.assertGreater(len(keys), 65)
        for key in sorted(keys):
            self.assertIn(key, values, key)
            self.assertEqual(values[key], expected[key], key)

    def test_column_own_rows_write_general_keys(self):
        """Colonne Focus > Zone titre et Image : propres a la colonne, la valeur va dans la cle generale."""
        height = field(self.win, "General", "preview_title_zone_height")
        slider = height if isinstance(height, _SliderField) else height.findChild(_SliderField)
        slider.setValue(77)
        values = self.win.wired_values()
        self.assertEqual(values["preview_title_zone_height"], 77)
        self.assertIn("preview_image_ratio", values)
        self.assertNotIn("preview_title_zone_height", self.win.stores["General"]["toggles"])
        slider.setValue(52)

    def test_skin_accent_and_focused_selection_are_independent(self):
        rows = [(spec, w) for spec, w in self.win.stores["General"]["specs"]
                if not isinstance(spec, str) and spec.kind == "semantic_color"]
        by_slot = {spec.key: widget for spec, widget in rows}
        original = by_slot["colors:skinAccent"].value()
        self.assertEqual(original, by_slot["colors:selCur"].value())
        by_slot["colors:skinAccent"].field.setValue("#123456")
        by_slot["colors:skinAccent"].field.changed.emit("#123456")
        self.assertEqual(by_slot["colors:skinAccent"].value(), "#123456")
        self.assertNotEqual(by_slot["colors:selCur"].value(), "#123456")
        colors = self.win.wired_values()["colors"]
        self.assertEqual(colors["accent"], "#123456")
        self.assertNotEqual(colors["sel_focus"], "#123456")
        by_slot["colors:skinAccent"].field.setValue(original)
        by_slot["colors:skinAccent"].field.changed.emit(original)

    def test_window_radius_is_a_toggle(self):
        toggle = field(self.win, "General", "window_radius")
        toggle.setChecked(True)
        self.assertEqual(self.win.wired_values()["window_radius"], v2.WINDOW_RADIUS_ON)
        toggle.setChecked(False)
        self.assertEqual(self.win.wired_values()["window_radius"], 0)

    def test_new_navigation_and_control_sections_build(self):
        open_nodes(self.win, 0, ("Barre de navigation", "Bouton", "Tabs", "Zone de saisie"))
        keys = {spec.key for spec, _widget in self.win.stores["General"]["specs"]
                if not isinstance(spec, str)}
        expected = {"navbar_height", "navbar_bottom_enabled", "navbar_title_font_family",
                    "button_bg_color", "button_border_enabled", "button_shadow_enabled",
                    "tabs_bg_color", "tabs_corner_radius", "input_bg_color", "input_corner_radius"}
        self.assertFalse(expected - keys, expected - keys)

    def test_add_and_remove_a_software(self):
        logiciels = field(self.win, "General", "custom_softwares")
        with mock.patch.object(settings_v2_app.QInputDialog, "getText", return_value=("Mon Outil", True)):
            logiciels._add()
        self.assertIn({"key": "MONOUTIL", "label": "Mon Outil"}, self.win.wired_values()["custom_softwares"])
        with mock.patch.object(settings_v2_app.QMessageBox, "question", return_value=QMessageBox.Yes):
            logiciels._delete("MONOUTIL", True)
        self.assertNotIn("MONOUTIL", [e["key"] for e in self.win.wired_values()["custom_softwares"]])

    def test_every_ported_toggle_is_type_2_without_text(self):
        for spec, widget in self.win.stores["General"]["specs"]:
            if isinstance(spec, str):
                continue
            for toggle in [widget] * isinstance(widget, _Toggle) + widget.findChildren(_Toggle):
                self.assertFalse(toggle.text() if hasattr(toggle, "text") else "", spec.key)


if __name__ == "__main__":
    unittest.main()
