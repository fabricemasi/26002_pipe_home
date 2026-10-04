"""Fenetre de reglages : aller-retour des valeurs et suivi des styles communs.

Garde-fous du rangement de la fenetre de reglages : tout reglage relu puis
reinjecte doit rester identique, et chaque element d'un meme type (zone de
saisie, bouton, tableau) doit suivre son reglage de style, ou qu'il soit."""
import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
import re
import time
import unittest
from PySide6.QtWidgets import QApplication

APP = QApplication.instance() or QApplication([])
import app_style
app_style.apply_style(APP)
import settings_layout as sl
import settings_sections as ssec
import settings_widgets as swg
import settings_window as sw

_HEX = re.compile(r"^#[0-9a-fA-F]{6}$")

# Reglages qui ne survivent pas a un aller-retour modifie. Certains sont
# normaux (window_radius : simple toggle ; cotes « lies » qui se recopient),
# les autres sont des bugs a corriger. La liste ne doit que RETRECIR.
_KNOWN_ROUNDTRIP_GAPS = {
    "column_overrides_by_title", "column_padding", "column_type_override_linked", "column_type_overrides",
    "header_font_antialias_override_enabled", "header_radius", "item_antialias_override_enabled",
    "item_selection_padding", "preview_status_font_smoothing_enabled", "preview_title_font_smoothing_enabled",
    "resize_badge_font_smoothing_enabled", "shortcut_font_smoothing_enabled", "table_cell_padding",
    "title_level1_font_smoothing_enabled", "title_level2_font_smoothing_enabled",
    "title_level3_font_smoothing_enabled", "title_level4_font_smoothing_enabled",
    "title_level5_font_smoothing_enabled", "window_radius",
}


def _perturb(value):
    if isinstance(value, bool):
        return not value
    if isinstance(value, int):
        return value + 1
    if isinstance(value, float):
        return value + 0.5
    if isinstance(value, str) and _HEX.match(value):
        return "#123457" if value.lower() != "#123457" else "#654321"
    if isinstance(value, dict):
        return {k: _perturb(v) for k, v in value.items()}
    return value


def _settle():
    """Laisse partir les minuteries de regroupement (30 ms) de la fenetre."""
    for _ in range(3):
        APP.processEvents()
        time.sleep(0.05)
    APP.processEvents()


class SettingsWindowTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.window = sw.SettingsWindow()
        _settle()

    @classmethod
    def tearDownClass(cls):
        cls.window.deleteLater()
        APP.processEvents()

    def test_values_roundtrip_unchanged(self):
        w = self.window
        before = w._current_values()
        w._apply_values_to_controls(before)
        _settle()
        after = w._current_values()
        self.assertEqual(sorted(k for k in before if before[k] != after.get(k)), [])

    def test_perturbed_values_roundtrip(self):
        w = self.window
        original = w._current_values()
        try:
            perturbed = {k: _perturb(v) for k, v in original.items()}
            w._apply_values_to_controls(perturbed)
            _settle()
            read = w._current_values()
            gaps = {k for k in perturbed if read.get(k) != perturbed[k]}
            self.assertEqual(sorted(gaps - _KNOWN_ROUNDTRIP_GAPS), [], "nouveaux reglages perdus a l'aller-retour")
        finally:
            w._apply_values_to_controls(original)
            _settle()

    def test_every_input_follows_input_radius(self):
        w = self.window
        w._apply_dropdown_radius(7)
        for cls in (swg._SliderField, swg._RatioSliderField, swg._SelectField, ssec._HeaderColorField):
            stale = [o for o in w.findChildren(cls) if o._radius != 7]
            self.assertEqual(len(stale), 0, f"{cls.__name__} : {len(stale)} ne suivent pas l'arrondi des zones de saisie")

    def test_every_button_follows_button_radius(self):
        w = self.window
        w._apply_button_radius(9)
        buttons = w.findChildren(swg._Btn)
        self.assertTrue(buttons)
        self.assertEqual([b.text() for b in buttons if b._radius != 9], [])

    def test_every_table_follows_table_radius(self):
        w = self.window
        w._apply_table_radius(6)
        tables = w.findChildren(swg._TableFrame)
        self.assertTrue(sl._flat_tables(w))
        self.assertEqual(sum(1 for t in tables if t._radius != 6), 0)


if __name__ == "__main__":
    unittest.main()
