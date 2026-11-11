"""Filets et bordures peints : (1) le filet horizontal de la DERNIERE ligne d'un tableau arrondi a la meme couleur que
les autres, meme translucide (signale : « @ligne/3 » sortait plus sombre) ; (2) Theme > General > « Bordure des
fenetres » : cote par cote, couleur et epaisseur, sur le cadre de la fenetre principale (marges comprises)."""
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
from PySide6.QtWidgets import QApplication, QLabel, QVBoxLayout

APP = QApplication.instance() or QApplication([])

import settings_window_v2 as v2  # noqa: E402
import ui_state  # noqa: E402
from settings_store import DEFAULT_SETTINGS  # noqa: E402
from fm_theme.widgets import _TableRow  # noqa: E402


class LastRowLineTest(unittest.TestCase):
    def test_translucent_line_of_the_rounded_last_row_matches_the_others(self):
        settings = copy.deepcopy(DEFAULT_SETTINGS)
        settings.update(table_inner_h_color="#08ffffff", table_inner_h_enabled=True, table_radius=4)
        v2.seed_window_look(settings)
        self.addCleanup(v2.seed_window_look, copy.deepcopy(DEFAULT_SETTINGS))
        frame = v2.build_group("Couleurs", v2.ScopeValues(settings, "General", None), {}, {}, {}, [])
        self.addCleanup(shiboken6.delete, frame)
        frame.resize(400, frame.sizeHint().height())
        frame.show()
        APP.processEvents()
        image = frame.grab().toImage()
        rows = sorted((r for r in frame.findChildren(_TableRow) if r.isVisible() and not r._first_row),
                      key=lambda r: r.y())
        lines = {image.pixelColor(100, r.mapTo(frame, r.rect().topLeft()).y()).name() for r in rows}
        self.assertEqual(rows[-1]._bottom_radius, 4)                   # la derniere est bien arrondie
        self.assertEqual(len(lines), 1, lines)


class TableHeightTest(unittest.TestCase):
    """Bug signale 2026-10-30 (« les hauteurs de lignes deviennent folles ») : un cadre de tableau plus haut que ses
    lignes (place en trop d'une section parente, plancher reste d'un etat plus haut) etait rempli de VIDES entre
    toutes ses lignes. Le cadre garde toujours la hauteur de son contenu."""

    def test_frame_never_grows_past_its_rows(self):
        from PySide6.QtWidgets import QWidget
        from fm_theme.layout import _lock_min_height
        settings = copy.deepcopy(DEFAULT_SETTINGS)
        v2.seed_window_look(settings)
        host = QWidget()
        self.addCleanup(shiboken6.delete, host)
        layout = QVBoxLayout(host)
        frame = v2.build_group("toggle1 : OFF", v2.ScopeValues(settings, "General", None), {}, {}, {}, [])
        layout.addWidget(frame)
        frame.setMinimumHeight(900)                  # plancher reste d'un etat plus haut
        _lock_min_height(frame)
        host.resize(900, 1200)                       # et une section parente qui donne trop de place
        host.show()
        APP.processEvents()
        rows = sorted((r for r in frame.findChildren(_TableRow) if r.isVisible()), key=lambda r: r.y())
        gaps = [rows[i + 1].y() - (rows[i].y() + rows[i].height()) for i in range(len(rows) - 1)]
        self.assertEqual(gaps, [0] * len(gaps))
        self.assertLessEqual(frame.height() - (rows[-1].y() + rows[-1].height()), 2)
        # Ni vides, ni lignes etirees (selon que leur hauteur est fixee ou libre) : chacune a sa hauteur de contenu.
        self.assertTrue(all(r.height() <= max(r.minimumHeight(), r.layout().sizeHint().height()) + 2 for r in rows),
                        [(r.height(), r.layout().sizeHint().height()) for r in rows])
        self.assertLessEqual(frame.height(), frame.sizeHint().height() + 2)
        self.assertLess(frame.height(), 900)


class SectionHeightTest(unittest.TestCase):
    """Bug signale 2026-10-30 (« les espaces entre les elements des settings deviennent fous ») : une section
    ouverte gardait le plancher de hauteur de son dernier depli ; son contenu rapetissait (tableau, toggle...)
    et le surplus devenait un vide sous son titre. Sa hauteur suit maintenant toujours son contenu."""

    def test_open_section_shrinks_with_its_content(self):
        from PySide6.QtWidgets import QWidget
        from fm_theme.layout import _Section, _SubSection
        host = QWidget()
        self.addCleanup(shiboken6.delete, host)
        layout = QVBoxLayout(host)
        section = _Section("Section", parent=host)
        sub = _SubSection("Sous-section", parent=section)
        content = QWidget()
        content.setFixedHeight(600)
        sub.add(content)
        section.add(sub)
        layout.addWidget(section)
        layout.addStretch(1)
        section.set_collapsed(True)
        section.set_collapsed(False)
        host.resize(600, 1400)
        host.show()
        APP.processEvents()
        tall = section.height()
        content.setFixedHeight(100)                   # le contenu rapetisse, sans repli
        for _ in range(10):                           # un passage de boucle par niveau d'imbrication
            APP.processEvents()
        self.assertLessEqual(section.height(), tall - 500 + 2)
        self.assertLessEqual(content.mapTo(host, content.rect().topLeft()).y() - sub.head.height(), 60)


class WindowBorderTest(unittest.TestCase):
    def test_main_window_frame_follows_the_setting(self):
        from browser_core import apply_window_border
        from main_window.helpers import CentralFrame
        self.addCleanup(setattr, ui_state, "WINDOW_BORDER", ui_state.WINDOW_BORDER)
        self.addCleanup(setattr, ui_state, "WINDOW_RADIUS", ui_state.WINDOW_RADIUS)
        apply_window_border({"window_border_enabled": {"top": True, "right": False, "bottom": True, "left": True},
                             "window_border": {"top": "#ff0000", "right": "#ff0000", "bottom": "#00ff00",
                                               "left": "#0000ff"},
                             "window_border_thickness": 4, "colors": {}})
        ui_state.WINDOW_RADIUS = 0
        frame = CentralFrame()
        self.addCleanup(shiboken6.delete, frame)
        layout = QVBoxLayout(frame)
        layout.addWidget(QLabel("contenu"))
        frame.sync_margins()
        margins = layout.contentsMargins()
        self.assertEqual((margins.left(), margins.top(), margins.right(), margins.bottom()), (4, 4, 0, 4))
        frame.resize(200, 100)
        image = frame.grab().toImage()
        self.assertEqual(image.pixelColor(100, 1).name(), "#ff0000")
        self.assertEqual(image.pixelColor(100, 98).name(), "#00ff00")
        self.assertEqual(image.pixelColor(1, 50).name(), "#0000ff")
        self.assertNotEqual(image.pixelColor(198, 50).name(), "#ff0000")    # cote coupe : pas de bordure

    def test_setting_lives_in_the_theme(self):
        import fm_theme.presets as tp
        self.assertEqual([s.key for s in v2.CATALOG["Thème : Général"]][-1], "window_border_enabled")
        for key in ("window_border_enabled", "window_border", "window_border_thickness"):
            self.assertIn(key, DEFAULT_SETTINGS)
            self.assertEqual(tp.theme_key(key)[0], "general")
        # Fenetres additionnelles : de nouveau leur bordure propre (demande de l'utilisateur, 2026-11-08).
        self.assertIn("extra_window_border_enabled", [s.key for s in v2.CATALOG["Fenêtres additionnelles"]])


class TableBackgroundTest(unittest.TestCase):
    def test_background_color_of_every_table(self):
        """Thème > Tableaux > Couleur de fond : « @tableRow » (défaut) = la pastille, sinon la sienne, en direct."""
        from fm_theme.tokens import M
        settings = copy.deepcopy(DEFAULT_SETTINGS)
        self.assertEqual(settings["table_bg_color"], "@tableRow")
        self.assertIn("table_bg_color", [s.key for s in v2.CATALOG["Tableaux"]])
        settings["colors"] = dict(settings["colors"], table_row="#202020")
        v2.seed_window_look(settings)
        self.addCleanup(v2.seed_window_look, copy.deepcopy(DEFAULT_SETTINGS))
        self.assertEqual(M["table_row_a"], "#202020")
        frame = v2._flat_cells_table([("Essai", QLabel("x"), None, None), ("Essai 2", QLabel("y"), None, None)])
        self.addCleanup(shiboken6.delete, frame)
        v2.restyle_tables_in(frame, dict(settings, table_bg_color="#123456"))
        self.assertEqual((M["table_row_a"], M["table_row_b"]), ("#123456", "#123456"))
        self.assertTrue(all("#123456" in row.styleSheet() for row, _bg, _first in frame._flat_rows))


if __name__ == "__main__":
    unittest.main()
