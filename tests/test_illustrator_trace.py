"""Module Illustrator, tranche 15 : vectorisation d'une image : contours orientés (trous), quantification (noir et
blanc, niveaux de gris, couleurs), bruit, angles gardés, déterminisme ; dans le board : l'image remplacée par un groupe
de tracés en une étape (rendu vérifié au pixel), calcul en fil de fond, annulation."""
import os as _os, sys as _sys  # jamais les vrais réglages / presets de l'utilisateur (tests/_isolate.py)
_sys.path.insert(0, _os.path.dirname(_os.path.abspath(__file__)))
import _isolate  # noqa: E402,F401
import time
import unittest

import numpy as np
from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QImage, QPainter

from test_illustrator import APP
from test_illustrator_images import ImageTestCase
from fm_illustrator import bezier as bz, trace as tr
from fm_illustrator.items import IllImageItem


def canvas(w=120, h=120, color=(255, 255, 255)):
    img = np.zeros((h, w, 4), np.uint8)
    img[..., :3] = color
    img[..., 3] = 255
    return img


class TraceCoreTest(unittest.TestCase):
    def test_square_loop_and_hole_orientation(self):
        mask = np.zeros((10, 10), bool)
        mask[2:8, 2:8] = True
        mask[4:6, 4:6] = False
        areas = sorted(round(tr._area(loop)) for loop in tr.loops(mask))
        self.assertEqual(areas, [-4, 36])                           # le trou tourne dans l'autre sens
        corners = [loop for loop in tr.loops(mask) if tr._area(loop) > 0][0]
        self.assertEqual(len(corners), 4)                            # seuls les changements de direction

    def test_bw_disk_keeps_shape(self):
        img = canvas()
        yy, xx = np.mgrid[0:120, 0:120]
        img[(xx - 60) ** 2 + (yy - 60) ** 2 < 40 ** 2, :3] = 0
        result = tr.trace(img, tr.settings_for("bw"))
        self.assertEqual(len(result), 1)                             # blanc ignoré
        color, subs = result[0]
        self.assertEqual(color, "#000000")
        x0, y0, x1, y1 = bz.bounds(subs)
        self.assertAlmostEqual(x1 - x0, 80, delta=2)
        self.assertLess(len(subs[0]["nodes"]), 16)                  # quelques courbes, pas des centaines de points
        self.assertTrue(bz.point_inside(subs, (60, 60)))
        self.assertFalse(bz.point_inside(subs, (5, 5)))

    def test_colors_noise_and_corners(self):
        img = canvas()
        img[10:60, 10:60, :3] = (255, 0, 0)
        img[70:110, 20:100, :3] = (0, 0, 255)
        img[5, 100, :3] = (0, 0, 0)                                  # un pixel isolé : du bruit
        result = tr.trace(img, tr.settings_for("color3", noise=4))
        colors = [c for c, _s in result]
        self.assertEqual(colors[0], "#ffffff")                       # fond : la couleur la plus fréquente
        self.assertEqual(sorted(colors[1:]), ["#0000ff", "#ff0000"])
        red = next(s for c, s in result if c == "#ff0000")
        self.assertEqual(len(red[0]["nodes"]), 4)                    # un carré : 4 angles gardés
        x0, y0, x1, y1 = bz.bounds(red)
        self.assertAlmostEqual(x1 - x0, 50, delta=1.5)
        again = tr.trace(img, tr.settings_for("color3", noise=4))
        self.assertEqual([c for c, _s in again], colors)            # déterministe

    def test_gray_levels(self):
        img = canvas(60, 20)
        img[:, :20, :3] = 0
        img[:, 20:40, :3] = 128
        labels, palette = tr.quantize(img, tr.settings_for("gray", colors=3))
        self.assertEqual(len(set(labels.flatten().tolist())), 3)
        self.assertEqual(palette[0], "#000000")


class TraceBoardTest(ImageTestCase):
    def picture(self):
        image = QImage(160, 120, QImage.Format_RGB32)
        image.fill(QColor("#ffffff"))
        p = QPainter(image)
        p.setRenderHint(QPainter.Antialiasing, True)
        p.setBrush(QColor("#d01010"))
        p.setPen(Qt.NoPen)
        p.drawEllipse(QRectF(40, 20, 80, 80))
        p.end()
        path = self.tmp / "dessin.png"
        image.save(str(path))
        return path

    def test_trace_replaces_image_in_one_step(self):
        item = self.ctl.place_image(self.picture(), QPointF(300, 300))
        self.ctl.select([item])
        new = self.ctl.trace_image(dict(tr.settings_for("color3"), noise=20), background=False)
        self.assertGreaterEqual(len(new), 2)
        self.assertIsNone(self.scene.item(item.item_id))
        self.assertEqual(len({i.data["group"] for i in new}), 1)
        area = QRectF(220, 240, 160, 120)
        image = self.render(area)
        center = self.pixel(image, 300, 300, area)
        self.assertGreater(center.red(), 180)
        self.assertLess(center.green(), 60)
        self.assertEqual(self.pixel(image, 225, 245, area).name(), "#ffffff")
        self.scene.undo.undo()
        self.assertEqual(len(self.images()), 1)
        self.assertEqual(len(self.paths()), 1)

    def test_trace_runs_in_background(self):
        item = self.ctl.place_image(self.picture(), QPointF(300, 300))
        self.ctl.select([item])
        self.assertTrue(self.ctl.trace_image(tr.settings_for("bw", threshold=160)))
        end = time.monotonic() + 15
        while self.scene.item(item.item_id) is not None and time.monotonic() < end:
            APP.processEvents()
            time.sleep(0.01)
        self.assertIsNone(self.scene.item(item.item_id))
        self.assertTrue(self.paths())
        self.assertFalse(any(isinstance(i, IllImageItem) for i in self.paths()))
        self.assertIsNone(self.ctl.tip)


if __name__ == "__main__":
    unittest.main()
