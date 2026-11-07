"""Toggles par ÉTAT (demande de l'utilisateur, 2026-10-30) : Toggles > <style> > Type (intact), État OFF et État ON,
chacun avec un tableau Fond (largeur / hauteur, bordure, border radius, couleur) et un tableau Coche (idem + habillage
texte / icône au milieu de la coche ; Texte et Police grisés hors « Texte », Icône hors « Icône »). Anciennes clés
(un seul cadre, une seule coche) reprises à la lecture (fm_theme/toggle_states.py)."""
import os as _os, sys as _sys  # jamais les vrais reglages / presets de l'utilisateur (tests/_isolate.py)
_sys.path.insert(0, _os.path.dirname(_os.path.abspath(__file__)))
import _isolate  # noqa: E402,F401
import copy
import os
import sys
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import shiboken6
from PySide6.QtWidgets import QApplication

APP = QApplication.instance() or QApplication([])

import settings_window_v2 as v2  # noqa: E402
from fm_theme import toggle_states, widgets as w  # noqa: E402
from settings_store import DEFAULT_SETTINGS  # noqa: E402


class MigrationTest(unittest.TestCase):
    def test_old_keys_become_state_keys(self):
        d = {"toggle7_outer_width": 40, "toggle7_outer_height": 20, "toggle7_coche_margin": 3,
             "toggle7_outer_bg": "#111111", "toggle7_outer_bg_on": "#222222", "toggle7_coche_color": "#ff0000",
             "toggle7_coche_skin": "text", "toggle7_coche_text": "A"}
        toggle_states.fill_toggle_states(d)
        for state, bg in (("off", "#111111"), ("on", "#222222")):
            self.assertEqual(d[f"toggle7_{state}_bg_width"], 40)
            self.assertEqual(d[f"toggle7_{state}_bg_color"], bg)
            self.assertEqual(d[f"toggle7_{state}_coche_height"], 14)          # hauteur - 2 x distance du bord
            self.assertEqual((d[f"toggle7_{state}_coche_skin"], d[f"toggle7_{state}_coche_text"]), ("text", "A"))
        d["toggle7_off_bg_width"] = 55                                        # deja regle : jamais ecrase
        toggle_states.fill_toggle_states(d)
        self.assertEqual(d["toggle7_off_bg_width"], 55)

    def test_fade_style_has_no_coche_when_off(self):
        d = {"toggle2_outer_width": 22, "toggle2_coche_color": "#ff0000", "toggle2_motion": "fade"}
        toggle_states.fill_toggle_states(d)
        self.assertEqual(d["toggle2_off_coche_color"], "#00000000")
        self.assertEqual(d["toggle2_on_coche_color"], "#ff0000")

    def test_every_state_key_is_declared(self):
        for prefix in ("toggle1", "toggle2"):
            for state in ("off", "on"):
                for field in toggle_states.FIELDS:
                    self.assertIn(f"{prefix}_{state}_{field}", DEFAULT_SETTINGS)
        self.assertNotIn("toggle1_outer_width", DEFAULT_SETTINGS)


class PaintTest(unittest.TestCase):
    def tearDown(self):
        w._sync_toggle_style(copy.deepcopy(DEFAULT_SETTINGS))

    def shot(self, settings, checked):
        w._sync_toggle_style(settings)
        toggle = w._Toggle(checked, style_override="toggle1", show_label=False)
        self.addCleanup(shiboken6.delete, toggle)
        return toggle, toggle.grab().toImage()

    def test_each_state_has_its_own_background_and_coche(self):
        s = copy.deepcopy(DEFAULT_SETTINGS)
        s.update(toggle1_off_bg_width=30, toggle1_off_bg_height=14, toggle1_on_bg_width=50, toggle1_on_bg_height=24,
                 toggle1_off_bg_color="#ff0000", toggle1_on_bg_color="#00ff00",
                 toggle1_off_coche_color="#0000ff", toggle1_on_coche_color="#ffff00",
                 toggle1_off_coche_width=8, toggle1_off_coche_height=8,
                 toggle1_on_coche_width=16, toggle1_on_coche_height=16, toggle1_motion="slide")
        for state in ("off", "on"):
            s[f"toggle1_{state}_bg_border_enabled"] = s[f"toggle1_{state}_coche_border_enabled"] = False
        toggle, off = self.shot(s, False)
        self.assertEqual((w._TOGGLE_STYLES["toggle1"]["outer_w"], w._TOGGLE_STYLES["toggle1"]["outer_h"]), (50, 24))
        cx, cy = off.width() // 2, off.height() // 2
        self.assertEqual(off.pixelColor(cx, cy).name(), "#ff0000")             # fond OFF au centre
        left = cx - 15 + 3 + 4                                                 # coche OFF : a gauche, distance 3
        self.assertEqual(off.pixelColor(left, cy).name(), "#0000ff")
        _toggle, on = self.shot(s, True)
        self.assertEqual(on.pixelColor(cx, cy - 10).name(), "#00ff00")         # fond ON, plus haut
        right = cx + 25 - 4 - 8                                                # coche ON : a droite, distance 4
        self.assertEqual(on.pixelColor(right, cy).name(), "#ffff00")

    def test_text_skin_is_drawn_in_the_middle_of_the_coche(self):
        s = copy.deepcopy(DEFAULT_SETTINGS)
        s.update(toggle1_on_coche_width=30, toggle1_on_coche_height=20, toggle1_on_bg_width=60,
                 toggle1_on_bg_height=24, toggle1_on_coche_color="#000000", toggle1_on_coche_skin="text",
                 toggle1_on_coche_text="X", toggle1_on_coche_text_font_color="#ffffff",
                 toggle1_on_coche_text_font_size=14)
        _toggle, image = self.shot(s, True)
        coche_center = (image.width() // 2 + 30 - 2 - 15, image.height() // 2)
        hits = [(x, y) for x in range(coche_center[0] - 14, coche_center[0] + 15)
                for y in range(coche_center[1] - 9, coche_center[1] + 10) if image.pixelColor(x, y).lightness() > 200]
        self.assertTrue(hits)
        mean_x = sum(x for x, _y in hits) / len(hits)
        self.assertLess(abs(mean_x - coche_center[0]), 3)                     # texte centre dans la coche


class TablesTest(unittest.TestCase):
    def test_off_and_on_tables_and_greyed_skin_rows(self):
        self.assertEqual([n.title for n in v2._toggle_style_node("toggle1", "Toggle 1").children],
                         ["Type", "État OFF", "État ON"])
        values = v2.ScopeValues(copy.deepcopy(DEFAULT_SETTINGS), "General", None)
        fields = {}
        frame = v2.build_group("toggle1 : ON", values, {}, fields, {}, [])
        self.addCleanup(shiboken6.delete, frame)
        text, font, icon = (fields[k] for k in ("toggle1_on_coche_text", "toggle1_on_coche_text_font_family",
                                               "toggle1_on_coche_icon"))
        self.assertFalse(text.isEnabled() or icon.isEnabled())                  # habillage « Aucun »
        skin = fields["toggle1_on_coche_skin"].field("toggle1_on_coche_skin")
        skin._select("Texte")
        self.assertTrue(text.isEnabled())
        self.assertFalse(icon.isEnabled())
        skin._select("Icône")
        self.assertTrue(icon.isEnabled())
        self.assertFalse(text.isEnabled())
        self.assertIsNotNone(font)

    def test_fond_and_coche_share_one_split_table(self):
        """Fond et Coche d'un etat : le MEME tableau, chaque ligne divisee « Fond | Coche » (legendes au-dessus) ;
        lu et ecrit comme leurs champs."""
        from fm_theme.cells import SplitCell
        self.assertEqual([n.group for n in v2._toggle_style_node("toggle1", "Toggle 1").children],
                         ["toggle1 : Type", "toggle1 : OFF", "toggle1 : ON"])
        settings = copy.deepcopy(DEFAULT_SETTINGS)
        settings.update(toggle1_off_bg_width=33, toggle1_off_coche_width=9)
        values = v2.ScopeValues(settings, "General", None)
        fields, record = {}, []
        frame = v2.build_group("toggle1 : OFF", values, {}, fields, {}, [], record)
        self.addCleanup(shiboken6.delete, frame)
        width_row = fields["toggle1_off_bg_width"]
        self.assertIs(width_row, fields["toggle1_off_coche_width"])           # une seule ligne « Largeur »
        split = width_row.findChild(SplitCell)
        self.assertEqual(split._cap_texts, ["FOND", "COCHE"])
        spec = next(sp for sp, w in record if w is width_row)
        self.assertEqual({k: v for k, v in v2.read_spec(spec, width_row).items()},
                         {"toggle1_off_bg_width": 33, "toggle1_off_coche_width": 9})
        self.assertTrue(v2.write_spec(spec, width_row, {"toggle1_off_coche_width": 12}))
        self.assertEqual(v2.read_spec(spec, width_row)["toggle1_off_coche_width"], 12)
        keys = {k for sp, _w in record for k in v2.read_spec(sp, _w)}
        for field in toggle_states.FIELDS:                                     # tous les reglages de l'etat
            self.assertIn(f"toggle1_off_{field}", keys)


if __name__ == "__main__":
    unittest.main()
