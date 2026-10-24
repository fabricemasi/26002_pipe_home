"""Reglages > Zone de saisie / Tabs : les valeurs s'appliquent a TOUTES les zones de saisie (champ racine et menu des
presets de la barre de navigation compris) ; tabs : hauteur, espacement, polices, bordures des non selectionnes."""
import os as _os, sys as _sys  # jamais les vrais reglages / presets de l'utilisateur (tests/_isolate.py)
_sys.path.insert(0, _os.path.dirname(_os.path.abspath(__file__)))
import _isolate  # noqa: E402,F401
import os
import shutil
import sys
import tempfile
import time
import unittest
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from PySide6.QtGui import QColor
from PySide6.QtWidgets import QApplication

APP = QApplication.instance() or QApplication([])

import app_style
import browser_core
import pipeline_browser as pb
import settings_layout
import settings_store
import settings_window_v2 as v2
from settings_widgets import _SelectField


def settle(seconds=0.2):
    end = time.monotonic() + seconds
    while time.monotonic() < end:
        APP.processEvents()
        time.sleep(0.005)


class InputLookTest(unittest.TestCase):
    def setUp(self):
        app_style.apply_style(APP)
        self.root = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.root, True)
        (self.root / "a").mkdir()
        self.win = pb.PipelineBrowser(self.root)
        self.win._idle_preview_scheduler.timer.stop()
        self.win.resize(1300, 800)
        self.win.show()
        self.addCleanup(self.win.deleteLater)
        settle()

    def _apply(self, **changes):
        settings = dict(settings_store.load_settings())
        settings["root_path"] = self.win.root_field.text()
        settings.update(changes)
        self.win._apply_settings(settings)
        self.win._flush_stylesheet_rebuild()
        settle(0.1)

    def test_root_field_and_preset_menu_follow_the_input_settings(self):
        self._apply(input_bg_color="#aa1122", input_border_enabled={"top": True, "right": True, "bottom": True,
                                                                    "left": True},
                    input_border={s: "#22bb33" for s in ("top", "right", "bottom", "left")},
                    input_border_thickness=2, input_corner_radius=0, input_height=0)
        sheet = self.win.styleSheet()
        self.assertIn("#aa1122", sheet)                                  # QLineEdit de l'appli (champ racine)
        image = self.win.root_field.grab().toImage()
        self.assertEqual(image.pixelColor(image.width() - 12, image.height() // 2).name(), "#aa1122")
        select = self.win.preset_picker.select                          # menu des presets (brique des reglages)
        self.assertIn("#aa1122", select.styleSheet())
        self.assertIn("border-top: 2px solid #22bb33", select.styleSheet())

    def test_input_height_applies_to_the_bar_fields_and_to_every_input(self):
        self._apply(input_height=26)
        self.assertEqual(self.win.root_field.height(), 26)
        self.assertEqual(self.win.preset_picker.select.height(), 26)
        field = _SelectField(["a", "b"], "a")
        self.assertEqual(field.height(), 26)                            # nouvelle zone de saisie : a la bonne hauteur
        self._apply(input_height=0)
        self.assertEqual(self.win.root_field.height(), 20)              # 0 : retour a la hauteur d'origine
        self.assertEqual(self.win.preset_picker.select.height(), 20)

    def test_inputs_ignore_the_height_when_the_row_is_too_small(self):
        self._apply(input_height=60)
        self.assertLessEqual(self.win.root_field.height(), app_style.scaled(28))

    def test_registered_inputs_are_restyled_live(self):
        field = _SelectField(["a", "b"], "a")
        browser_core.apply_all_settings({**settings_store.load_settings(), "input_bg_color": "#334455",
                                         "input_height": 31, "input_corner_radius": 7})
        settle(0.3)                                       # les zones cachees sont refaites par petits paquets
        self.assertIn("#334455", field.styleSheet())
        self.assertIn("border-radius: 7px", field.styleSheet())
        self.assertEqual(field.height(), 31)

    def test_unchanged_input_look_restyles_nothing(self):
        # Chaque apercu en direct (n'importe quel curseur) passe par apply_all_settings : sans signature,
        # ~1000 zones de saisie etaient repeintes a chaque cran (~1 s).
        from PySide6.QtWidgets import QPushButton
        from settings_theme import _register_input, apply_input_look

        class Probe(QPushButton):
            calls = 0

            def setRadius(self, radius):
                Probe.calls += 1

        probe = Probe()
        probe.show()
        _register_input(probe)
        settings = {**settings_store.load_settings(), "input_bg_color": "#123456"}
        apply_input_look(settings)
        first = Probe.calls
        for _ in range(5):
            apply_input_look({**settings, "crumb_spacing": 9})          # autre chose a change
        self.assertEqual(Probe.calls, first)
        apply_input_look({**settings, "input_bg_color": "#654321"})     # la zone de saisie, si
        self.assertEqual(Probe.calls, first + 1)

    def test_separator_uses_the_same_font_as_the_texts_and_updates_in_place(self):
        bar = self.win.titlebar
        bar.set_crumbs([("set", "a", lambda: None), ("set", "b", lambda: None)], force=True)
        chips = bar.crumbs.findChildren(pb._CrumbChip)
        separators = [w for w in bar.crumbs.findChildren(pb.QLabel)]
        self.assertEqual(len(separators), 1)
        text_font = chips[0]._look["font"]                              # famille et taille : celles des textes
        self.assertEqual((separators[0].font().family(), separators[0].font().pixelSize()),
                         (text_font.family(), text_font.pixelSize()))
        before = (id(chips[0]), id(separators[0]))
        import ui_state
        import browser_core
        browser_core.apply_all_settings({**settings_store.load_settings(), "crumb_font_size": 17, "crumb_spacing": 12})
        bar.refresh_crumbs()
        chips = bar.crumbs.findChildren(pb._CrumbChip)
        separators = [w for w in bar.crumbs.findChildren(pb.QLabel)]
        self.assertEqual((id(chips[0]), id(separators[0])), before)      # rien de recree : mise a jour sur place
        self.assertEqual(separators[0].font().pixelSize(), 17)           # le separateur suit la taille des textes
        self.assertEqual(chips[0]._look["font"].pixelSize(), 17)
        self.assertEqual(bar._crumb_layout.spacing(), 12)


class HiddenSliderRestyleTest(unittest.TestCase):
    def test_a_slider_restyled_while_hidden_keeps_room_for_its_value_box(self):
        """Signale (Zone de saisie > Border radius) : case « 4 px » coupee en bas. Restyle en fond alors que sa
        section etait cachee et tassee, le curseur etait fige a ~17 px, sa case de valeur en faisant 25."""
        from PySide6.QtWidgets import QWidget, QVBoxLayout
        from settings_widgets import _SliderField
        import settings_theme
        holder = QWidget()
        lay = QVBoxLayout(holder)
        field = _SliderField(0, 30, 4)
        lay.addWidget(field)
        holder.resize(300, 12)                              # cache, mise en page tassee
        field.resize(field.width(), 12)
        field.__dict__.pop("_default_height", None)
        settings_theme._restyle_input(field)
        self.assertGreaterEqual(field.height(), field.box.height())
        self.assertGreaterEqual(field.maximumHeight(), field.box.height())
        holder.deleteLater()


class TabsLookTest(unittest.TestCase):
    def tearDown(self):
        settings_layout.set_tab_look({})

    def test_height_spacing_fonts_and_inactive_borders(self):
        look = {"tabs_height": 44, "tabs_spacing": 11, "tabs_font_size": 15, "tabs_font_bold": False,
                "tabs_font_italic": True, "tabs_corner_radius": 4,
                "tabs_inactive_border_enabled": {"top": True, "right": False, "bottom": False, "left": False},
                "tabs_inactive_border": {"top": "#112233"}, "tabs_inactive_border_thickness": 3, "colors": {}}
        settings_layout.set_tab_look(look)
        strip = settings_layout._TabStrip(["A", "B", "C"])
        self.assertEqual(strip.layout().spacing(), 11)
        for button in strip._btns:
            self.assertEqual(button.height() if button.isVisible() else button.minimumHeight(), 44)
            sheet = button.styleSheet()
            self.assertIn("font-size: 15px", sheet)                      # dans la feuille de style de CHAQUE tab
            self.assertIn("font-style: italic", sheet)
            self.assertIn("font-weight: normal", sheet)
        self.assertIn("border-top: 3px solid #112233", strip._btns[1].styleSheet())   # non selectionne
        self.assertNotIn("border-top: 3px solid #112233", strip._btns[0].styleSheet())  # selectionne : les siennes

    def test_catalog_has_the_new_rows(self):
        labels = [s.label for s in v2.CATALOG["Tabs"]]
        for expected in ("Couleur sous les tabs", "Hauteur des tabs", "Espacement entre les tabs",
                         "Bordures des tabs non sélectionnés", "Couleur du tab en cours"):
            self.assertIn(expected, labels)
        self.assertIn("Hauteur des zones de saisie (0 = d'origine)", [s.label for s in v2.CATALOG["Zone de saisie"]])
        for key in ("tabs_height", "tabs_spacing", "tabs_strip_color", "tabs_inactive_border_enabled", "input_height"):
            self.assertIn(key, settings_store.DEFAULT_SETTINGS)

    def test_strip_color_paints_the_bar_under_the_tabs(self):
        css = v2.SettingsWindowV2._tab_bar_css({"tabs_strip_color": "#445566", "colors": {}})
        self.assertIn("#445566", css)
        line = v2.SettingsWindowV2._tab_bar_css({"colors": {}, "tabs_bottom_color": "#abcdef",
                                                 "tabs_bottom_thickness": 3})
        self.assertIn("border-bottom: 3px solid #abcdef", line)          # bordure entre tabs et interface
        self.assertIn("border-bottom: none", v2.SettingsWindowV2._tab_bar_css({"colors": {},
                                                                             "tabs_bottom_enabled": False}))
        default = v2.SettingsWindowV2._tab_bar_css({"colors": {}, "extra_window_title_bg": "#101214"})
        self.assertIn("#101214", default)                       # par defaut : couleur de la barre de navigation

    def test_zone_under_the_navigation_bar_has_the_navigation_bar_color(self):
        win = v2.SettingsWindowV2()
        self.addCleanup(win.deleteLater)
        win.resize(760, 500)
        win.show()
        settle(0.6)
        if win._tab_gap.height() <= 0:
            self.skipTest("pas d'espace entre la barre de navigation et les tabs dans ces reglages")
        image = win.grab().toImage()
        title = image.pixelColor(300, win.titlebar.geometry().center().y()).name()
        gap = win._tab_gap.geometry()
        self.assertEqual(image.pixelColor(300, gap.center().y()).name(), title)       # la zone de l'espace
        sub = win._tab_subbar.geometry()
        self.assertEqual(image.pixelColor(2, sub.center().y()).name(), title)         # et la barre des tabs


if __name__ == "__main__":
    unittest.main()
