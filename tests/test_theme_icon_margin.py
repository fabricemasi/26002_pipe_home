"""Marge des icônes (fm_theme > Général, `icon_margin`, demande de l'utilisateur 2026-11-12) : TOUTE icône (chargée,
SVG, dessinée par le code) est ramenée au bord de ses pixels visibles, puis recentrée dans son cadre avec la marge
réglée (% de chaque côté) — fm_theme/icon_frame.py."""
import os as _os, sys as _sys  # jamais les vrais reglages / presets de l'utilisateur (tests/_isolate.py)
_sys.path.insert(0, _os.path.dirname(_os.path.abspath(__file__)))
import _isolate  # noqa: E402,F401
import os
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from PySide6.QtCore import QPointF, QRect, QRectF, Qt  # noqa: E402
from PySide6.QtGui import QColor, QImage, QPainter, QPen, QPixmap  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

APP = QApplication.instance() or QApplication([])

import settings_store  # noqa: E402
import settings_window_v2 as v2  # noqa: E402
from fm_theme import presets as tp  # noqa: E402
from fm_theme import icon_frame  # noqa: E402
from preview_services import icons, pixmaps  # noqa: E402


def _icon(w, h, drawn: QRect) -> QPixmap:
    pix = QPixmap(w, h)
    pix.fill(Qt.transparent)
    p = QPainter(pix)
    p.fillRect(drawn, QColor("#ff0000"))
    p.end()
    return pix


class IconMarginTest(unittest.TestCase):
    def tearDown(self):
        icons.set_icon_margin(20)

    def test_setting_lives_in_theme_general(self):
        self.assertIn("icon_margin", [s.key for s in v2.CATALOG["Thème : Général"]])
        self.assertIn("icon_margin", tp.GENERAL_KEYS)                    # enregistré avec le preset de thème
        self.assertEqual(settings_store.DEFAULT_SETTINGS["icon_margin"], 20)

    def test_icon_is_trimmed_then_centered_with_the_margin(self):
        # Dessin décentré, marges inégales (10 px à gauche, 60 en bas…) : seule sa partie visible compte.
        src = _icon(100, 100, QRect(10, 30, 30, 20))
        self.assertEqual(pixmaps._content_rect(src), QRect(10, 30, 30, 20))
        out = pixmaps._contain_square(src, 50, margin=20)               # cadre intérieur : 30 px
        self.assertEqual(pixmaps._content_rect(out), QRect(10, 15, 30, 20))
        out = pixmaps._contain_square(src, 50, margin=0)                # au bord du cadre
        self.assertEqual(pixmaps._content_rect(out).width(), 50)

    def test_opaque_or_empty_images_are_kept_whole(self):
        opaque = QPixmap(40, 20)
        opaque.fill(QColor("#123456"))
        self.assertEqual(pixmaps._content_rect(opaque), QRect(0, 0, 40, 20))
        empty = _icon(30, 30, QRect())
        self.assertEqual(pixmaps._content_rect(empty), QRect(0, 0, 30, 30))

    def test_margin_change_forgets_framed_icons(self):
        icons._UI_ICON_CACHE[("ui_x", 16)] = (1.0, QPixmap(16, 16))
        self.assertFalse(icons.set_icon_margin(20))                      # inchangée : rien n'est oublié
        self.assertIn(("ui_x", 16), icons._UI_ICON_CACHE)
        self.assertTrue(icons.set_icon_margin(10))
        self.assertEqual(icon_frame.MARGIN, 10)
        self.assertEqual(icons._UI_ICON_CACHE, {})
        icons.set_icon_margin(99)
        self.assertEqual(icon_frame.MARGIN, icon_frame.MARGIN_MAX)      # jamais plus que la moitié du cadre


def _canvas(side=48):
    pix = QPixmap(side, side)
    pix.fill(Qt.transparent)
    return pix


class DrawnIconFrameTest(unittest.TestCase):
    """Icônes dessinées par le code (`paint_framed`, décorateur `framed`)."""

    def tearDown(self):
        icon_frame.set_margin(20)

    def _framed_dash(self, half_length):
        def dash(p, r):                                  # trait au centre, épaisseur fixe 2 px
            p.setPen(QPen(QColor("#ffffff"), 2, Qt.SolidLine, Qt.FlatCap))
            c, half = r.center(), half_length(r)
            p.drawLine(QPointF(c.x() - half, c.y()), QPointF(c.x() + half, c.y()))
        pix = _canvas()
        p = QPainter(pix)
        icon_frame.paint_framed(p, QRectF(0, 0, 48, 48), dash)
        p.end()
        rect = icon_frame.content_rect(pix.toImage())
        self.assertAlmostEqual(rect.left(), 10, delta=1)                # 20 % de 48 = 9,6 px
        self.assertAlmostEqual(rect.right(), 37, delta=1)
        return rect

    def test_drawing_proportional_to_its_frame_is_redrawn_with_thin_strokes(self):
        rect = self._framed_dash(lambda r: r.width() * 0.08)
        self.assertLessEqual(rect.height(), 3)                           # redessiné : le trait n'a pas grossi

    def test_fixed_size_drawing_is_magnified_too(self):
        rect = self._framed_dash(lambda r: 4)                            # 8 px quel que soit le cadre
        self.assertGreater(rect.height(), 3)                             # agrandi en vectoriel : trait plus épais

    def test_decorated_painter_and_nesting(self):
        calls = []

        @icon_frame.framed("test-glyph")
        def glyph(p, kind, rect, color):
            calls.append(kind)
            p.fillRect(QRectF(rect.x() + 2, rect.y() + 2, 6, 6), QColor(color))   # dans un coin, petit

        @icon_frame.framed("test-outer")
        def outer(p, kind, rect, color):
            glyph(p, kind, rect, color)                  # imbriqué : peint tel quel, cadré une seule fois
        for painter_fn in (glyph, outer):
            icon_frame.set_margin(25)
            pix = _canvas(40)
            p = QPainter(pix)
            painter_fn(p, "a", QRectF(0, 0, 40, 40), QColor("#ff0000"))
            p.end()
            got = icon_frame.content_rect(pix.toImage())
            for value, want in ((got.left(), 10), (got.top(), 10), (got.width(), 20), (got.height(), 20)):
                self.assertAlmostEqual(value, want, delta=1, msg=painter_fn.__name__)
            icon_frame.set_margin(20)
        counts = []
        for _ in range(2):                               # 2e fois, même clé et même marge : servi par le cache
            pix = _canvas(40)
            p = QPainter(pix)
            glyph(p, "a", QRectF(0, 0, 40, 40), QColor("#ff0000"))
            p.end()
            counts.append(len(calls))
        self.assertGreater(counts[0], 0)
        self.assertEqual(counts[1], counts[0])

    def test_frame_image_and_icons(self):
        image = QImage(100, 100, QImage.Format_ARGB32_Premultiplied)
        image.fill(Qt.transparent)
        p = QPainter(image)
        p.fillRect(QRect(0, 0, 50, 50), QColor("#00ff00"))             # dessin collé dans un coin
        p.end()
        self.assertEqual(icon_frame.content_rect(icon_frame.frame_image(image, 10)), QRect(10, 10, 80, 80))
        self.assertEqual(icon_frame.content_rect(icon_frame.frame_into(image, 200, 100, 0)), QRect(50, 0, 100, 100))


if __name__ == "__main__":
    unittest.main()
