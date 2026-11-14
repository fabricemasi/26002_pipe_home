import _isolate  # noqa: F401
import os
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest import mock

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QRectF, Qt  # noqa: E402
from PySide6.QtGui import QColor, QPainter, QPixmap  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

APP = QApplication.instance() or QApplication([])


def _inks(pixmap: QPixmap) -> list:
    """Couleurs des pixels peints (alpha franc) d'une image."""
    image = pixmap.toImage()
    out = []
    for y in range(image.height()):
        for x in range(image.width()):
            c = image.pixelColor(x, y)
            if c.alpha() > 200:
                out.append(c)
    return out


def _magenta(c: QColor) -> bool:
    return c.red() > 200 and c.blue() > 200 and c.green() < 60


def _paint(painter_fn, size: int = 32) -> QPixmap:
    pix = QPixmap(size, size)
    pix.fill(Qt.transparent)
    painter = QPainter(pix)
    painter.setRenderHint(QPainter.Antialiasing, True)
    painter_fn(painter, QRectF(0, 0, size, size))
    painter.end()
    return pix


class PlaceholderIconTest(unittest.TestCase):
    """Icones DESSINEES par le code en magenta ; icones CHARGEES par l'utilisateur intactes (2026-11-08)."""

    def test_ink_keeps_the_alpha(self):
        from fm_theme.placeholder import ink
        self.assertEqual(ink("#c4cacf").name(), "#ff00ff")
        self.assertEqual(ink(QColor(10, 20, 30, 90)).alpha(), 90)
        self.assertEqual(ink().alpha(), 255)

    def test_module_glyphs_are_magenta(self):
        from fm_agenda.ui.widgets import draw_icon
        from fm_board.ui import paint_glyph
        from fm_cad.cad_ui import paint_cad_glyph
        from fm_photoshop.bars import paint_tool
        grey = QColor("#c4cacf")
        painters = {
            "board": lambda p, r: paint_glyph(p, "pdf", r, grey),
            "cad": lambda p, r: paint_cad_glyph(p, "cad_line", r, grey),
            "photoshop": lambda p, r: paint_tool(p, "brush", r, grey),
            "agenda": lambda p, r: draw_icon(p, "next", r, grey, 2.4),
        }
        for name, fn in painters.items():
            inks = _inks(_paint(fn))
            self.assertTrue(inks, name)
            self.assertTrue(all(_magenta(c) for c in inks), name)

    def test_navbar_glyph_is_magenta_but_a_loaded_icon_is_untouched(self):
        import preview_column
        from preview_column import IconButton

        def grab(button):
            button.setFlat(True)
            button.setStyleSheet("QPushButton { background: transparent; border: none; }")
            button.resize(32, 32)
            return button.grab()

        with mock.patch.object(preview_column, "custom_ui_icon_pixmap", lambda key, size: None):
            button = IconButton("close", "#c4cacf", "#ffffff")
            inks = _inks(grab(button))
        self.assertTrue(any(_magenta(c) for c in inks))
        self.assertFalse(any(abs(c.red() - 0xc4) < 8 and abs(c.green() - 0xca) < 8 for c in inks))   # plus de gris
        button.deleteLater()

        loaded = QPixmap(20, 20)
        loaded.fill(QColor("#20c040"))
        with mock.patch.object(preview_column, "custom_ui_icon_pixmap", lambda key, size: loaded):
            button = IconButton("close", "#c4cacf", "#ffffff")
            inks = _inks(grab(button))
        self.assertTrue(any(c.name() == "#20c040" for c in inks))
        self.assertFalse(any(_magenta(c) for c in inks))
        button.deleteLater()

    def test_software_badge_is_magenta_but_a_loaded_icon_is_untouched(self):
        from browser_core_parts import icons
        badge = icons._generate_software_badge("MAYA", 32).toImage()
        self.assertTrue(_magenta(badge.pixelColor(9, 16)))      # bord gauche du badge (marge des icônes : 20 %)

        folder = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, folder, True)
        own = QPixmap(32, 32)
        own.fill(QColor("#3080ff"))
        own.save(str(folder / "MAYA.png"))
        with mock.patch.object(icons, "custom_software_icon_path", lambda key: folder / f"{key}.png"), \
                mock.patch.dict(icons._software_icon_cache, clear=True):
            image = icons.software_icon_pixmap("MAYA", 32).toImage()
        self.assertEqual(image.pixelColor(16, 16).name(), "#3080ff")


if __name__ == "__main__":
    unittest.main()
