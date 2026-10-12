"""Sections de la v1 portees dans la fenetre de reglages v2 : Application, omissions, LUT, Polices
principales, Couleurs, Geometrie, ICONES, RACCOURCI ; onglets Focus (Image, Zone titre, Bouton
repliement) et Projets (Icone de niveaux). Memes valeurs que la v1 sur les memes reglages, lignes
propres a une colonne ecrites dans les cles generales (pas dans les surcharges), pastilles liees."""
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
import settings_window as sw
import settings_window_v2 as v2
from app_style import PREVIEW_STACK_TITLE
from settings_store import DEFAULT_SETTINGS as _DEFAULTS
from settings_widgets import _SliderField, _Toggle

v2.AUTOSAVE = False
_real = (v2.load_settings, sw.load_settings)


def setUpModule():
    v2.load_settings = lambda: copy.deepcopy(_DEFAULTS)
    sw.load_settings = lambda: copy.deepcopy(_DEFAULTS)


def tearDownModule():
    v2.load_settings, sw.load_settings = _real


PORTED = ("Application", "Dossiers et fichiers à omettre", "LUT", "Polices principales", "Couleurs", "Geometrie",
          "ICONES", "RACCOURCI")


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
        open_nodes(cls.win, cls.labels.index(PREVIEW_STACK_TITLE), ("Image", "Zone titre", "Bouton repliement"))
        open_nodes(cls.win, cls.labels.index("Projets"), ("Icone de niveaux",))

    @classmethod
    def tearDownClass(cls):
        cls.win.deleteLater()
        app.processEvents()

    def test_values_match_the_v1_window(self):
        old = sw.SettingsWindow(mode="tout")
        self.addCleanup(old.deleteLater)
        # La page Projets de la v1 n'est construite qu'a l'ouverture (avant : valeurs du disque).
        for index, (_tab, real_title) in old._columns_subpage_specs.items():
            if real_title == "Projets":
                old._on_columns_tab_changed(index)
        expected = old._current_values()
        values = self.win.wired_values()
        groups = ("Application", "Omettre", "LUT", "Polices principales", "Geometrie", "Raccourci",
                  "Icones : Logiciels", "Focus : Zone titre", "Focus : Bouton repliement", "Projets : Icone de niveaux")
        keys = set()
        for group in groups:
            for spec in v2.CATALOG[group]:
                keys.update(k for k in (spec.key, *spec.extra_keys) if k in expected)
        keys |= {"colors", "preview_padding", "preview_radius"}
        self.assertGreater(len(keys), 80)
        for key in sorted(keys):
            self.assertIn(key, values, key)
            self.assertEqual(values[key], expected[key], key)

    def test_column_own_rows_write_general_keys(self):
        """Focus > Zone titre : propre a la colonne, sans toggle ; la valeur va dans la cle generale,
        jamais dans les surcharges. Le Ratio, lui, reste une surcharge."""
        label = PREVIEW_STACK_TITLE
        height = field(self.win, label, "preview_title_zone_height")
        slider = height if isinstance(height, _SliderField) else height.findChild(_SliderField)
        slider.setValue(77)
        values = self.win.wired_values()
        self.assertEqual(values["preview_title_zone_height"], 77)
        per_title = values["column_overrides_by_title"].get(label, {})
        self.assertNotIn("preview_title_zone_height", per_title)
        self.assertIn("item_image_ratio", self.win.stores[label]["toggles"])
        self.assertNotIn("preview_title_zone_height", self.win.stores[label]["toggles"])
        slider.setValue(52)

    def test_linked_palette_slots_stay_in_sync(self):
        rows = [(spec, w) for spec, w in self.win.stores["General"]["specs"]
                if not isinstance(spec, str) and spec.kind == "semantic_color" and spec.params["real_key"] == "accent"]
        if len(rows) < 2:
            self.skipTest("une seule pastille pour l'accent")
        original = rows[0][1].value()
        rows[0][1].field.setValue("#123456")
        rows[0][1].field.changed.emit("#123456")
        self.assertEqual(rows[1][1].value(), "#123456")
        self.assertEqual(self.win.wired_values()["colors"]["accent"], "#123456")
        rows[0][1].field.setValue(original)
        rows[0][1].field.changed.emit(original)

    def test_window_radius_is_a_toggle(self):
        toggle = field(self.win, "General", "window_radius")
        toggle.setChecked(True)
        self.assertEqual(self.win.wired_values()["window_radius"], v2.WINDOW_RADIUS_ON)
        toggle.setChecked(False)
        self.assertEqual(self.win.wired_values()["window_radius"], 0)

    def test_geometry_restyles_inputs_live(self):
        holder = field(self.win, "General", "input_frame")
        holder._v2_parts["radius"].setValue(7)
        self.win._flush_live()
        self.assertEqual(settings_v2_app._input_radius(), 7)
        holder._v2_parts["radius"].setValue(0)
        self.win._flush_live()

    def test_add_and_remove_a_software(self):
        logiciels = field(self.win, "General", "custom_softwares")
        with mock.patch.object(settings_v2_app.QInputDialog, "getText", return_value=("Mon Outil", True)):
            logiciels._add()
        self.assertIn({"key": "MONOUTIL", "label": "Mon Outil"}, self.win.wired_values()["custom_softwares"])
        with mock.patch.object(settings_v2_app.QMessageBox, "question", return_value=QMessageBox.Yes):
            logiciels._delete("MONOUTIL", True)
        self.assertNotIn("MONOUTIL", [e["key"] for e in self.win.wired_values()["custom_softwares"]])

    def test_every_ported_toggle_is_type_2_without_text(self):
        for label in ("General", PREVIEW_STACK_TITLE, "Projets"):
            for spec, widget in self.win.stores[label]["specs"]:
                if isinstance(spec, str):
                    continue
                for toggle in [widget] * isinstance(widget, _Toggle) + widget.findChildren(_Toggle):
                    self.assertFalse(toggle.text() if hasattr(toggle, "text") else "", spec.key)


if __name__ == "__main__":
    unittest.main()
