"""Planche : un fichier qui a une couleur attribuee (file_attributes) recoit un calque de cette couleur, a la
place des marques focus / survol ; Reglages > Visionneuse > Filtres > « Opacite des couleurs attribuees »
(une ligne : opacite | bordure | epaisseur)."""
import os as _os, sys as _sys  # jamais les vrais reglages / presets de l'utilisateur (tests/_isolate.py)
_sys.path.insert(0, _os.path.dirname(_os.path.abspath(__file__)))
import _isolate  # noqa: E402,F401
import os
import shutil
import sys
import tempfile
import time
import unittest
from unittest.mock import patch
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from PySide6.QtGui import QColor, QImage
from PySide6.QtWidgets import QApplication

app = QApplication.instance() or QApplication([])

from fm_visionneuse import file_attributes as fa
from fm_visionneuse import focus, gallery_paint
import settings_store
import settings_window_v2 as v2
import ui_state


def settle(seconds=0.4):
    end = time.monotonic() + seconds
    while time.monotonic() < end:
        app.processEvents()
        time.sleep(0.01)


class ColorMarkTest(unittest.TestCase):
    def setUp(self):
        self.dir = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.dir, True)
        saved = ui_state.APPLIED_SETTINGS
        self.addCleanup(setattr, ui_state, "APPLIED_SETTINGS", saved)
        ui_state.APPLIED_SETTINGS = settings_store.load_settings()
        ui_state.APPLIED_SETTINGS.update({"viewer_filter_color_1": "#00ff00", "viewer_filter_mark_opacity": 100,
                                          "viewer_filter_mark_border": False})
        self.paths = []
        for name in ("a.png", "b.png"):
            image = QImage(40, 30, QImage.Format_RGB32)
            image.fill(QColor("#202020"))
            image.save(str(self.dir / name))
            self.paths.append(self.dir / name)
        fa.update(self.paths[1], color=1)

    def green_in(self, gallery, path) -> int:
        index = next(gallery.model().index(i, 0) for i in range(gallery.count())
                     if gallery.item(i).data(0x0100) == str(path))
        rect = gallery.visualRect(index)
        # Le calque seul : sans la bande des attributs (sa pastille montre aussi la couleur).
        with patch.object(gallery_paint, "_paint_attrs"):
            focus._CELLS.clear()
            image = gallery.cell_pixmap(index, rect.size()).toImage()
        focus._CELLS.clear()
        return sum(1 for y in range(0, image.height(), 2) for x in range(0, image.width(), 2)
                   if image.pixelColor(x, y).green() > 200 and image.pixelColor(x, y).red() < 60)

    def gallery(self):
        focus._CELLS.clear()
        gallery = focus.FocusGallery(None, self.paths, None)
        self.addCleanup(gallery.deleteLater)
        gallery.resize(700, 500)
        gallery.show()
        settle()
        return gallery

    def test_attributed_colour_fills_the_mark_area(self):
        gallery = self.gallery()
        self.assertEqual(self.green_in(gallery, self.paths[0]), 0)            # pas de couleur : rien
        self.assertGreater(self.green_in(gallery, self.paths[1]), 50)         # calque vert
        gallery.grab().save(str(self.dir / "planche.png"))

    def test_opacity_zero_and_border_only(self):
        ui_state.APPLIED_SETTINGS.update({"viewer_filter_mark_opacity": 0, "viewer_filter_mark_border": True,
                                          "viewer_filter_mark_border_thickness": 3})
        gallery = self.gallery()
        green = self.green_in(gallery, self.paths[1])
        self.assertGreater(green, 10)                                         # le contour
        ui_state.APPLIED_SETTINGS["viewer_filter_mark_border"] = False
        gallery.restyle()
        focus._CELLS.clear()
        self.assertEqual(self.green_in(gallery, self.paths[1]), 0)

    def test_frame_avoids_the_lines_painted_over_the_cells(self):
        # Filets interieurs peints PAR-DESSUS les cases, centres sur la limite : le cadre se loge apres eux
        # (ses bords gauche et haut etaient caches, signale).
        ui_state.APPLIED_SETTINGS.update({"viewer_film_table_inner_v_enabled": True,
                                          "viewer_film_table_inner_v_thickness": 3,
                                          "viewer_film_table_inner_h_enabled": True,
                                          "viewer_film_table_inner_h_thickness": 1})
        paths = list(self.paths)
        for n in range(7):
            image = QImage(40, 30, QImage.Format_RGB32)
            image.fill(QColor("#202020"))
            image.save(str(self.dir / f"x{n}.png"))
            paths.append(self.dir / f"x{n}.png")
        self.paths = paths
        gallery = self.gallery()
        self.assertGreater(gallery._cols, 2)
        self.assertGreater(gallery._rows, 1)
        middle = gallery._cols + 1                                  # 2e ligne, 2e colonne
        self.assertEqual(gallery.mark_insets(middle), (2, 1, 1, 0))
        self.assertEqual(gallery.mark_insets(0)[:2], (0, 0))        # bords du tableau sans bordure

    def test_rounded_frame_has_the_same_width_on_every_side(self):
        # Epaisseur impaire + coins arrondis : le cadre etait decale d'un demi-pixel (gauche / haut plus
        # epais, droite / bas rognes ; signale).
        from unittest import mock
        from PySide6.QtCore import QRect
        from PySide6.QtGui import QPainter
        look = {"color_mark": {"opacity": 0, "border": True, "thick": 3}}
        image = QImage(60, 40, QImage.Format_ARGB32)
        image.fill(0)
        painter = QPainter(image)
        corners = {k: 6 for k in ("top_left", "top_right", "bottom_right", "bottom_left")}
        with mock.patch("fm_visionneuse.film_look._gallery_mark_radius", return_value=corners):
            focus._paint_color_mark(painter, look, QRect(0, 0, 60, 40), "#00ff00")
        painter.end()

        def ink(points):
            return round(sum(image.pixelColor(x, y).alphaF() for x, y in points), 2)
        self.assertEqual(ink([(x, 20) for x in range(10)]), ink([(x, 20) for x in range(50, 60)]))
        self.assertEqual(ink([(30, y) for y in range(10)]), ink([(30, y) for y in range(30, 40)]))
        self.assertAlmostEqual(ink([(x, 20) for x in range(10)]), 3, delta=0.1)

    def test_setting_is_one_row(self):
        spec = next(s for s in v2.CATALOG["Visionneuse : Filtres"] if s.key == "viewer_filter_mark_opacity")
        self.assertEqual(spec.label, "Opacité des couleurs attribuées")
        values = settings_store.load_settings()
        field = v2.make_field(spec, v2.ScopeValues(values, None), values["colors"])
        self.addCleanup(field.deleteLater)
        parts = field._v2_parts
        parts["opacity"].setValue(60)
        parts["border"].setChecked(True)
        parts["thickness"].setValue(4)
        self.assertEqual(v2.read_spec(spec, field), {"viewer_filter_mark_opacity": 60,
                                                     "viewer_filter_mark_border": True,
                                                     "viewer_filter_mark_border_thickness": 4})


if __name__ == "__main__":
    unittest.main()
