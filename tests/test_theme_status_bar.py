"""fm_theme > Barre de navigation / Barre d'état (2026-11-05) : sections générales de fm_theme (plus dans General de
fm_browser), clés enregistrées dans le preset fm_theme, barre d'état habillée par `fm_theme.status_bar`."""
import _isolate  # noqa: F401
import os
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from PySide6.QtWidgets import QApplication, QHBoxLayout, QLabel, QWidget  # noqa: E402

import settings_store  # noqa: E402
import settings_window_v2 as v2  # noqa: E402
from fm_theme import presets as tp  # noqa: E402
from fm_theme.status_bar import apply_status_bar  # noqa: E402
from _lent import lent  # noqa: E402

APP = QApplication.instance() or QApplication([])


class SectionsTest(unittest.TestCase):
    def test_both_bars_are_theme_sections(self):
        theme = {n.title: n for n in v2.theme_tree()}
        general = [n.title for n in v2.tab_tree("General")]
        self.assertIn("Barre d'état", theme)
        self.assertNotIn("Barre d'état", general)
        # Barre de navigation partagee (2026-11-07) : fm_theme garde l'aspect de la barre et reduire / agrandir /
        # fermer, fm_browser le reste, meme hierarchie.
        self.assertIn("Barre de navigation", theme)
        self.assertIn("Barre de navigation", general)
        self.assertEqual([c.title for c in theme["Barre de navigation"].children], ["Icônes"])
        app = next(n for n in v2.tab_tree("General") if n.title == "Barre de navigation")
        self.assertEqual([c.title for c in app.children], ["Icônes", "Cheminement", "Fenêtres additionnelles"])
        self.assertEqual([s.key for s in v2.CATALOG["Barre de navigation"]],
                         ["navbar_bg_color", "navbar_bottom_enabled", "navbar_title_font_family",
                          "navbar_height"])
        self.assertEqual([s.params["ui_key"] for s in v2.CATALOG["Barre de navigation : Icones"]],
                         ["navbar_min", "navbar_max", "navbar_close"])
        self.assertEqual([s.key for s in v2.CATALOG["Barre de navigation (appli)"]],
                         ["navtool_extra_height", "navtool_bg_color",
                          "navtool_border_enabled", "navtool_corner_radius", "navtool_hover_bg_color",
                          "navtool_margin"])
        for spec in v2.CATALOG["Barre de navigation (appli)"]:
            for key in (spec.key, *spec.extra_keys):
                self.assertIn(key, settings_store.DEFAULT_SETTINGS, key)
            self.assertIsNone(tp.theme_key(spec.key) if spec.key.startswith("navtool_") else None)
        # Plus aucune ligne de barre de navigation dans Fenetres additionnelles.
        self.assertFalse([s for s in v2.CATALOG["Fenêtres additionnelles"] if s.key.startswith("extra_window_title")])

    def test_keys_belong_to_fm_theme(self):
        for key in ("navbar_height", "navbar_title_font_color", "crumb_spacing", "statusbar_height",
                    "statusbar_path_font_color", "extra_window_title_height"):
            self.assertIsNotNone(tp.theme_key(key), key)
        status = {s.key for s in v2.CATALOG["Barre d'état"]}
        for spec in v2.CATALOG["Barre d'état"]:
            for key in (spec.key, *spec.extra_keys):
                self.assertIn(key, settings_store.DEFAULT_SETTINGS, key)
        self.assertIn("statusbar_height", status)
        preset = tp.from_settings(settings_store.DEFAULT_SETTINGS, "x")
        self.assertEqual(tp.to_settings(preset)["statusbar_height"], 24)


class StatusBarLookTest(unittest.TestCase):
    def test_apply(self):
        bar = QWidget()
        bar.setObjectName("StatusBar")
        layout = QHBoxLayout(bar)
        path, info = QLabel("a"), QLabel("b")
        layout.addWidget(path)
        layout.addWidget(info)
        settings = dict(settings_store.DEFAULT_SETTINGS, statusbar_height=40, statusbar_bg_color="#123456",
                        statusbar_top_thickness=3, statusbar_padding_x=20, statusbar_path_font_size=15,
                        statusbar_info_font_color="#ff0000")
        apply_status_bar(bar, {"path": path, "info": info}, settings)
        self.assertEqual(bar.height(), 40)
        self.assertIn("#123456", bar.styleSheet())
        self.assertIn("border-top: 3px", bar.styleSheet())
        self.assertEqual(layout.contentsMargins().left(), 20)
        self.assertEqual(path.font().pixelSize(), 15)
        self.assertIn("#ff0000", info.styleSheet())
        sheet = bar.styleSheet()
        apply_status_bar(bar, {"path": path, "info": info}, dict(settings, statusbar_top_enabled=False))
        self.assertIn("border-top: 0px", bar.styleSheet())
        self.assertNotEqual(sheet, bar.styleSheet())


@lent
class MainWindowTest(unittest.TestCase):
    """Fenetre principale : un cran de Barre d'etat / Barre de navigation ne rhabille que la barre (chemin rapide)."""

    def test_live_change_only_restyles_the_bars(self):
        import shutil
        import tempfile
        import time
        from pathlib import Path
        from unittest import mock
        import app_style
        import browser_core
        import pipeline_browser as pb
        import ui_state
        app_style.apply_style(APP)
        root = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, root, True)
        win = pb.PipelineBrowser(root)
        win._idle_preview_scheduler.timer.stop()
        win.resize(1200, 700)
        win.show()
        self.addCleanup(win.deleteLater)
        for _ in range(5):
            APP.processEvents()
        browser_core.apply_all_settings(settings_store.load_settings())
        win._last_style_key = win._style_key(ui_state.APPLIED_SETTINGS)
        for key, value in (("statusbar_height", 36), ("statusbar_path_font_size", 14), ("navbar_height", 60)):
            settings = dict(ui_state.APPLIED_SETTINGS, **{key: value})
            with mock.patch.object(win, "refresh_all_columns") as columns,                     mock.patch.object(win, "refresh_colors") as colors:
                start = time.perf_counter()
                win._apply_settings(settings)
                spent = time.perf_counter() - start
            columns.assert_not_called()
            colors.assert_not_called()
            self.assertLess(spent, 0.05, key)
        self.assertEqual(win.statusbar.height(), 36)
        self.assertEqual(win.path_label.font().pixelSize(), 14)
        self.assertGreaterEqual(win.titlebar.height(), 60)


if __name__ == "__main__":
    unittest.main()
