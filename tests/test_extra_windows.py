"""Reglages > Fenetres additionnelles (demande de l'utilisateur) : toutes les fenetres en plus de la
principale (reglages, override / a la volee, presets) partagent bordures, border radius exact, ombre (peinte
dans une marge transparente), barre de navigation (hauteur, couleur, filet) et filet de la barre des boutons."""
import os as _os, sys as _sys  # jamais les vrais reglages / presets de l'utilisateur (tests/_isolate.py)
_sys.path.insert(0, _os.path.dirname(_os.path.abspath(__file__)))
import _isolate  # noqa: E402,F401
import os
import sys
import unittest
from unittest import mock

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication

app = QApplication.instance() or QApplication([])

import settings_store
import settings_window as sw
import settings_window_v2 as v2


class ExtraWindowsTest(unittest.TestCase):
    def setUp(self):
        self.addCleanup(sw.seed_extra_window_look, settings_store.DEFAULT_SETTINGS)
        patches = [mock.patch("settings_quick_style.save_settings"), mock.patch("settings_quick_style.save_live_state")]
        for p in patches:
            p.start()
            self.addCleanup(p.stop)

    def window(self, **values):
        import settings_quick_style as qs
        settings = settings_store.load_settings()
        settings.update(values)
        win = qs.QuickStyleWindow("Essai fenêtre", qs.font_padding_specs("demo"), {}, title="Essai",
                                  settings=settings)
        win.show()
        for _ in range(3):
            app.processEvents()
        self.addCleanup(lambda: win.close() if __import__("shiboken6").isValid(win) else None)
        return win

    def test_section_rows(self):
        labels = [spec.label for spec in v2.CATALOG["Fenêtres additionnelles"]]
        self.assertEqual(labels, ["Bordures", "Border radius", "Ombres", "Hauteur de la barre de navigation",
                                  "Couleur de la barre de navigation", "Texte de la barre de navigation",
                                  "Taille des boutons de la barre de navigation", "Border radius des boutons",
                                  "Bordure barre de navigation / interface", "Bordure interface / barre des boutons"])
        self.assertIn("Fenêtres additionnelles", [n.title for n in v2.GENERAL_TREE])
        values = settings_store.load_settings()
        scope = v2.ScopeValues(values, None)
        for spec in v2.CATALOG["Fenêtres additionnelles"]:
            read = v2.read_spec(spec, v2.make_field(spec, scope, values["colors"]))
            self.assertTrue(set(read) <= set(settings_store.DEFAULT_SETTINGS), read)

    def test_shadow_margin_border_and_title_bar(self):
        all_sides = {k: True for k in ("top", "right", "bottom", "left")}
        win = self.window(extra_window_shadow_size=18, extra_window_border_thickness=3,
                          extra_window_shadow_enabled=all_sides, extra_window_border_enabled=all_sides,
                          extra_window_title_height=46, extra_window_radius=10)
        self.assertTrue(win.testAttribute(Qt.WA_TranslucentBackground))
        margins = sw.shadow_margins(win)
        self.assertEqual((margins.left(), margins.top(), margins.right(), margins.bottom()), (18, 18, 18, 18))
        self.assertEqual(sw.chrome_size(win), (42, 42))                       # ombre + bordure, des 2 cotes
        self.assertEqual(win.titlebar.height(), 46)
        self.assertEqual(win.width(), win.table.width() + 2 * win.MARGIN + 42)  # le tableau suit toujours
        # Ombre coupee, en direct : plus de marge, la fenetre se recale.
        settings = settings_store.load_settings()
        settings.update(extra_window_shadow_size=0, extra_window_border_thickness=1, extra_window_border_enabled=all_sides)
        sw.seed_extra_window_look(settings)
        app.processEvents()
        self.assertEqual(sw.chrome_size(win), (2, 2))
        self.assertEqual(win.width(), win.table.width() + 2 * win.MARGIN + 2)

    def test_title_text_and_buttons(self):
        win = self.window(extra_window_title_text_font_size=17, extra_window_title_text_font_bold=True,
                          extra_window_title_text_font_color="#ff0000", extra_window_title_button_width=50,
                          extra_window_title_button_height=24, extra_window_title_height=30,
                          extra_window_title_button_radius=6)
        bar = win.titlebar
        self.assertTrue(bar._title.font().bold())
        self.assertIn("#ff0000", bar._title.styleSheet())
        self.assertEqual((bar.close_btn.width(), bar.close_btn.height()), (50, 24))
        self.assertIn("border-bottom-left-radius: 6px", bar.close_btn.styleSheet())
        self.assertGreaterEqual(bar.height(), 30)
        self.assertEqual(bar.height(), max(30, bar._text_h + 4))

    def test_alert_border(self):
        win = self.window()
        panel = win.findChild(sw._PanelFrame)
        self.assertTrue(panel._extra)
        panel.setAlert("#c62828")
        self.assertEqual(panel._alert, "#c62828")
        panel.setAlert(None)
        self.assertIsNone(panel._alert)


if __name__ == "__main__":
    unittest.main()
