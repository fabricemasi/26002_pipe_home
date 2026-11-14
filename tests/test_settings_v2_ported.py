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
        from fm_theme.layout import logical_parent    # corps des sections : dans le volet (theme_side_detail)
        for node in page.findChildren(v2._LazyNode):
            parent = logical_parent(node)
            while parent is not None and not isinstance(parent, v2._LazyNode):
                parent = logical_parent(parent)
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
        cls.theme = v2.SettingsWindowV2(module="theme")  # aspect generique : fenetre Theme (etape 6 de fm_theme)
        open_nodes(cls.theme, 0, PORTED + ("Général",))

    @classmethod
    def tearDownClass(cls):
        cls.win.deleteLater()
        cls.theme.deleteLater()
        app.processEvents()

    def test_values_match_the_v1_window(self):
        # Valeurs lues par l'ancienne fenetre v1 (retiree), figees : _v1_reference.py.
        expected = V1_VALUES
        values = {**self.win.wired_values(), **self.theme.wired_values()}
        groups = ("Application", "Omettre", "LUT", "Polices principales", "Raccourci",
                  "Icones : Logiciels", "Focus : Zone titre", "Projets : Icone de niveaux")
        keys = set()
        for group in groups:
            for spec in v2.CATALOG[group]:
                keys.update(k for k in (spec.key, *spec.extra_keys) if k in expected)
        # « colors » n'est plus comparé : la palette vient du preset fm_theme actif (neo…), plus des défauts figés
        # pour la v1 (tests de la palette : test_theme_palette).
        keys |= {"preview_padding", "preview_radius"}
        # Paddings de Focus > Zone titre : la reference v1 a fige le BUG « lier les 4 » (cotes inegaux alignes sur le
        # 1er, cotes caches perdus) ; corrige le 2026-11-12, verifie par tests.test_settings_round_trip.
        keys -= {"preview_title_padding", "preview_status_padding",
                 "preview_title_padding_linked", "preview_status_padding_linked"}
        self.assertGreater(len(keys), 60)
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
        rows = [(spec, w) for spec, w in self.theme.stores[v2.THEME_TAB]["specs"]
                if not isinstance(spec, str) and spec.kind == "semantic_color"]
        by_slot = {spec.key: widget for spec, widget in rows}
        original = by_slot["colors:skinAccent"].value()
        self.assertEqual(original, by_slot["colors:selCur"].value())
        by_slot["colors:skinAccent"].field.setValue("#123456")
        by_slot["colors:skinAccent"].field.changed.emit("#123456")
        self.assertEqual(by_slot["colors:skinAccent"].value(), "#123456")
        self.assertNotEqual(by_slot["colors:selCur"].value(), "#123456")
        colors = self.theme.wired_values()["colors"]
        self.assertEqual(colors["accent"], "#123456")
        self.assertNotEqual(colors["sel_focus"], "#123456")
        by_slot["colors:skinAccent"].field.setValue(original)
        by_slot["colors:skinAccent"].field.changed.emit(original)

    def test_window_radius_is_a_toggle(self):
        toggle = field(self.theme, v2.THEME_TAB, "window_radius")
        toggle.setChecked(True)
        self.assertEqual(self.theme.wired_values()["window_radius"], v2.WINDOW_RADIUS_ON)
        toggle.setChecked(False)
        self.assertEqual(self.theme.wired_values()["window_radius"], 0)

    def test_new_navigation_and_control_sections_build(self):
        open_nodes(self.theme, 0, ("Barre de navigation", "Bouton", "Tabs", "Zone de saisie"))
        keys = {spec.key for win, label in ((self.win, "General"), (self.theme, v2.THEME_TAB))
                for spec, _widget in win.stores[label]["specs"] if not isinstance(spec, str)}
        expected = {"navbar_height", "navbar_bg_color", "navbar_bottom_enabled", "navbar_title_font_family",
                    "button_bg_color", "button_border_enabled", "button_shadow_enabled",
                    "tabs_bg_color", "tabs_corner_radius", "input_bg_color", "input_corner_radius"}
        self.assertFalse(expected - keys, expected - keys)

    def test_activation_toggle_of_border_radius_shadow_padding_rows(self):
        """Demande de l'utilisateur (2026-11-11) : Bordures, Border radius, Ombres, Padding, Margin ont un toggle
        juste à droite du titre (toggle 2 depuis le 2026-11-12) ; coupé = effet coupé (valeurs neutres), ligne grisée,
        valeurs gardées."""
        from PySide6.QtWidgets import QLabel
        open_nodes(self.theme, 0, ("Bouton",))
        border = field(self.theme, v2.THEME_TAB, "button_border_enabled")
        toggle = border._v2_active
        self.assertEqual(toggle._table_style, "toggle2")
        self.assertTrue(toggle.isChecked())                       # bordure par défaut visible : actif
        holder = toggle.parentWidget()
        items = [holder.layout().itemAt(i).widget() for i in range(holder.layout().count())]
        self.assertIsInstance(items[0], QLabel)                   # titre, PUIS le toggle juste à sa droite
        self.assertIs(items[1], toggle)
        radius = field(self.theme, v2.THEME_TAB, "button_corner_radius")
        self.assertEqual(radius._v2_active.isChecked(), v2._effect_visible(
            v2.Spec("button_corner_radius", "", "corners"), v2.FIELD_READERS["corners"](
                v2.Spec("button_corner_radius", "", "corners"), radius)))
        before = self.theme.wired_values()["button_border_enabled"]
        toggle.setChecked(False)
        values = self.theme.wired_values()
        self.assertFalse(any(values["button_border_enabled"].values()))    # effet coupé pour toute l'appli
        self.assertIs(values["button_border_enabled__on"], False)
        self.assertEqual(values["button_border_enabled__kept"]["button_border_enabled"], before)
        self.assertFalse(border.isEnabled())                      # ligne grisée
        toggle.setChecked(True)
        values = self.theme.wired_values()
        self.assertEqual(values["button_border_enabled"], before)        # valeurs rendues
        self.assertTrue(border.isEnabled())
        # Effet RETIRÉ (pas laissé à 100 %) : sinon les toggles H, B, D grisés par « lier les 4 » (leur propre
        # effet, dans celui-ci) disparaissaient (signalé, variante windows_95)
        self.assertIsNone(border.graphicsEffect())
        # Valeurs posées sur place (variante, preset) : la ligne coupée affiche ses valeurs gardées
        spec = next(s for s, w in self.theme.stores[v2.THEME_TAB]["specs"] if w is border)
        kept = dict(values, button_border_thickness=4)
        self.assertTrue(v2.write_spec(spec, border, {"button_border_enabled__on": False,
                                                     "button_border_enabled__kept": kept}))
        self.assertFalse(toggle.isChecked())
        self.assertEqual(border._v2_thickness.value(), 4)
        self.assertTrue(v2.write_spec(spec, border, {"button_border_enabled": before,
                                                     "button_border_thickness": 1}))   # sans état : déduit
        self.assertTrue(toggle.isChecked())
        # Fenêtre rouverte sur une ligne coupée : les valeurs gardées, grisées
        settings = dict(_DEFAULTS, button_border_enabled__on=False,
                        button_border_enabled__kept={"button_border_thickness": 3})
        rebuilt = v2.make_field(spec, v2.ScopeValues(settings), {})
        self.assertFalse(rebuilt._v2_active.isChecked())
        self.assertEqual(rebuilt._v2_thickness.value(), 3)
        for kind in ("sides_thick", "corners", "shadow", "padding"):
            self.assertTrue(any(s.kind == kind and v2.has_activation(s) for specs in v2.CATALOG.values()
                                for s in specs if not isinstance(s, str)))
        self.assertTrue(v2.has_activation(v2.Spec("x", "Padding", "slider", 0, {"min": 0, "max": 9})))
        self.assertFalse(v2.has_activation(v2.Spec("x", "Taille", "slider", 0, {"min": 0, "max": 9})))

    def test_activation_keys_survive_loading(self):
        import settings_store
        self.assertTrue(settings_store._ACTIVATION_KEY.search("md_page_padding__kept"))
        self.assertTrue(settings_store._ACTIVATION_KEY.search("md_page_padding__on"))

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
