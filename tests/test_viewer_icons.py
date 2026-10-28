"""Reglages > Visionneuse > Icones : les icones perso remplacent les glyphes des boutons de la visionneuse
et des attributs des diapositives (etoiles, drapeaux, « + »). Dossier d'icones temporaire."""
import os as _os, sys as _sys  # jamais les vrais reglages / presets de l'utilisateur (tests/_isolate.py)
_sys.path.insert(0, _os.path.dirname(_os.path.abspath(__file__)))
import _isolate  # noqa: E402,F401
import os
import shutil
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from PySide6.QtCore import QRect
from PySide6.QtGui import QColor, QImage, QPainter, QPixmap
from PySide6.QtWidgets import QApplication

APP = QApplication.instance() or QApplication([])

from fm_visionneuse import focus
import preview_column
import previews
import settings_window_v2 as v2


def render(draw, size=40) -> QImage:
    image = QImage(size, size, QImage.Format_ARGB32)
    image.fill(0)
    painter = QPainter(image)
    draw(painter)
    painter.end()
    return image


class ViewerIconsTest(unittest.TestCase):
    def setUp(self):
        self.dir = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.dir, True)
        patcher = mock.patch.object(previews, "CUSTOM_SOFTWARE_ICON_DIR", self.dir)
        patcher.start()
        self.addCleanup(patcher.stop)
        previews.forget_mtime()
        self.addCleanup(previews.forget_mtime)

    def _icon(self, key: str, color: str):
        pix = QPixmap(32, 32)
        pix.fill(QColor(color))
        self.assertTrue(pix.save(str(previews.custom_software_icon_path(key)), "PNG"))
        previews.forget_mtime()

    def test_settings_has_an_icons_subsection_with_every_viewer_icon(self):
        titles = [n.title for node in v2.GENERAL_TREE if node.title == "Visionneuse" for n in node.children]
        self.assertIn("Icônes", titles)
        rows = {s.params["ui_key"] for s in v2.CATALOG["Visionneuse : Icones"]}
        self.assertEqual(rows, {k[len("ui_"):] for k in previews.VIEWER_ICON_KEYS})
        for spec in v2.CATALOG["Visionneuse : Icones"]:         # le champ retrouve la cle de l'appli
            self.assertTrue(hasattr(previews, f"UI_ICON_{spec.params['ui_key'].upper()}"))

    def test_buttons_use_the_chosen_icon(self):
        button = preview_column.IconButton("gallery", "#ccc", "#fff")
        button.resize(30, 30)
        self.assertIsNone(button._custom_icon_pixmap(button.rect()))
        self._icon(previews.UI_ICON_VIEWER_GALLERY, "#ff0000")
        self.assertIsNotNone(button._custom_icon_pixmap(button.rect()))
        for kind in ("fade_columns", "show_columns", "single_image", "filter"):
            self.assertIn(kind, previews.VIEWER_BUTTON_ICONS)

    def test_star_flag_and_plus_use_the_chosen_icons(self):
        rect = QRect(5, 5, 28, 28)
        plain = render(lambda p: focus._paint_star(p, rect, True))
        self._icon(previews.UI_ICON_VIEWER_STAR_ON, "#00ff00")
        custom = render(lambda p: focus._paint_star(p, rect, True))
        self.assertNotEqual(plain, custom)
        self.assertEqual(custom.pixelColor(19, 19).green(), 255)
        empty = render(lambda p: focus._paint_star(p, rect, False))
        self.assertNotEqual(empty, custom)                      # sans etoile vide choisie : l'allumee estompee
        self.assertLess(empty.pixelColor(19, 19).alpha(), 255)
        self._icon(previews.UI_ICON_VIEWER_FLAG_KEEP, "#0000ff")
        flag = focus._flag_pixmap("keep", 20)
        self.assertEqual(flag.toImage().pixelColor(10, 10).blue(), 255)

    def test_cells_are_redrawn_when_an_icon_changes(self):
        before = focus._film_look_signature()
        self._icon(previews.UI_ICON_VIEWER_PLUS, "#ffffff")
        self.assertNotEqual(before, focus._film_look_signature())

    def test_cells_have_separate_image_and_attribute_icon_paddings(self):
        node = next(n for n in v2.GENERAL_TREE if n.title == "Visionneuse")
        self.assertIn("Cellules", [c.title for c in node.children])
        labels = [s.label for s in v2.CATALOG["Visionneuse : Cellule image"]]
        self.assertIn("Padding de l'image", labels)
        self.assertIn("Padding des icônes d'attribut", labels)
        look = focus._film_look()
        self.assertEqual(set(look["image_padding"]), set(look["attr_padding"]))
        import ui_state
        applied = ui_state.APPLIED_SETTINGS
        self.addCleanup(setattr, ui_state, "APPLIED_SETTINGS", applied)
        ui_state.APPLIED_SETTINGS = {**(applied or {}), "viewer_film_attr_padding": {"left": 7, "top": 3},
                                     "viewer_film_image_padding": {"left": 20}}
        look = focus._film_look()
        self.assertEqual((look["attr_padding"]["left"], look["attr_padding"]["top"]), (7, 3))
        self.assertEqual(look["image_padding"]["left"], 20)
        self.assertEqual(look["attr_padding"]["right"], 0)        # deux calques independants

    def test_marks_follow_the_cell_background_or_the_table_cell(self):
        # Focus / survol / couleur : fond du tableau transparent -> fond de la cellule (ses 4 coins) ; sinon la
        # cellule du tableau, dont seuls les coins du tableau sont arrondis.
        square = {k: 0 for k in ("top_left", "top_right", "bottom_right", "bottom_left")}
        table_radius = {**square, "top_left": 9, "top_right": 9, "bottom_right": 9, "bottom_left": 9}
        cell_radius = {**square, "top_left": 5, "top_right": 5, "bottom_right": 5, "bottom_left": 5}
        look = {"split": False, "table": {"fill": None, "thick": 0, "radius": table_radius},
                "image_cell": {"fill": None, "radius": cell_radius}, "text_cell": {"fill": None, "radius": square}}
        self.assertTrue(focus._gallery_mark_on_sub_cells(look))
        self.assertEqual(focus._gallery_mark_radius(look, frozenset({"top_left"})), cell_radius)
        look["table"]["fill"] = "#80000000"
        self.assertFalse(focus._gallery_mark_on_sub_cells(look))
        radius = focus._gallery_mark_radius(look, frozenset({"top_left"}))
        self.assertEqual(radius, {**square, "top_left": 9})


if __name__ == "__main__":
    unittest.main()
