"""Module Illustrator, tranche 15 : vectorisation d'une image : contours orientés (trous), quantification (noir et
blanc, niveaux de gris, couleurs), bruit, angles gardés, déterminisme ; dans le board : l'image remplacée par un groupe
de tracés en une étape (rendu vérifié au pixel), calcul en fil de fond, annulation."""
import os as _os, sys as _sys  # jamais les vrais réglages / presets de l'utilisateur (tests/_isolate.py)
_sys.path.insert(0, _os.path.dirname(_os.path.abspath(__file__)))
import _isolate  # noqa: E402,F401
import math
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


def aa(inside, w=200, h=200, k=4):
    """Image anticrénelée EXACTE (suréchantillonnage k × k) : noir là où inside(x, y), blanc ailleurs."""
    o = (np.arange(k) + 0.5) / k
    ys, xs = np.mgrid[0:h, 0:w].astype(np.float64)
    cover = np.zeros((h, w))
    for dy in o:
        for dx in o:
            cover += inside(xs + dx, ys + dy)
    img = canvas(w, h)
    img[..., :3] = np.round(255 * (1 - cover / (k * k)))[..., None].astype(np.uint8)
    return img


def anchors(result):
    return [n for _c, subs in result for s in subs for n in s["nodes"]]


def dense(subs, n=40):
    pts = []
    for sub in subs:
        for p0, c1, c2, p3 in bz.segments(sub):
            for t in np.linspace(0, 1, n):
                pts.append(bz.cubic_at(p0, c1, c2, p3, t))
    return np.array(pts)


class TraceCoreTest(unittest.TestCase):
    def test_subpixel_contours_orientation_and_holes(self):
        from fm_illustrator import trace_contours as tc
        mask = np.zeros((10, 10))
        mask[2:8, 2:8] = 1
        mask[4:6, 4:6] = 0
        areas = sorted(round(tc.area(loop), 1) for loop in tc.iso_loops(mask - 0.5))
        self.assertEqual(areas, [-3.5, 35.5])                       # trou dans l'autre sens ; coins coupés d'1/8
        img = aa(lambda x, y: (x - 97.3) ** 2 + (y - 101.7) ** 2 < 60 ** 2)
        loop = tc.iso_loops(128.0 - tc.luminance(img))[0]
        r = np.hypot(loop[:, 0] - 97.3, loop[:, 1] - 101.7)
        self.assertLess(float(np.abs(r - 60).max()), 0.2)          # bord au dixième de pixel (anticrénelage lu)

    def test_circle_ellipse_rectangle_few_anchors_and_exact(self):
        circle = tr.trace(aa(lambda x, y: (x - 100.4) ** 2 + (y - 99.6) ** 2 < 80 ** 2), tr.settings_for("bw"))
        self.assertEqual(len(anchors(circle)), 4)                    # aux quatre extrema
        pts = dense(circle[0][1])
        self.assertLess(float(np.abs(np.hypot(pts[:, 0] - 100.4, pts[:, 1] - 99.6) - 80).max()), 0.3)
        for n in anchors(circle):
            self.assertEqual(n[6], 1)                                # lisses
            self.assertTrue(abs(n[2] - n[4]) < 1e-6 or abs(n[3] - n[5]) < 1e-6)   # poignées horizontales / verticales
        ellipse = tr.trace(aa(lambda x, y: ((x - 100.3) / 90) ** 2 + ((y - 100.2) / 45) ** 2 < 1), tr.settings_for("bw"))
        self.assertEqual(len(anchors(ellipse)), 4)
        rect = tr.trace(aa(lambda x, y: (x > 30.25) & (x < 170.5) & (y > 50.75) & (y < 140.25)), tr.settings_for("bw"))
        corners = sorted((round(n[0], 1), round(n[1], 1)) for n in anchors(rect))
        self.assertEqual(len(corners), 4)
        for (x, y), (ex, ey) in zip(corners, sorted([(30.25, 50.75), (30.25, 140.25), (170.5, 50.75), (170.5, 140.25)])):
            self.assertLess(abs(x - ex) + abs(y - ey), 0.3)         # sommets reconstruits malgré l'anticrénelage

    def test_star_keeps_sharp_corners_and_straight_sides(self):
        import math
        pts = [(100 + (90 if k % 2 == 0 else 30) * math.sin(k * math.pi / 5),
                100 - (90 if k % 2 == 0 else 30) * math.cos(k * math.pi / 5)) for k in range(10)]

        def inside(x, y):
            res = np.zeros(np.shape(x), dtype=bool)
            for (ax, ay), (bx, by) in zip(pts, pts[1:] + pts[:1]):   # parité des croisements
                cross = ((ay > y) != (by > y)) & (x < (bx - ax) * (y - ay) / np.where(by == ay, 1e-9, by - ay) + ax)
                res ^= cross
            return res
        nodes = anchors(tr.trace(aa(inside), tr.settings_for("bw")))
        self.assertEqual(len(nodes), 10)                             # les dix sommets, rien d'autre
        self.assertTrue(all(n[6] == 0 for n in nodes))               # tous des angles
        self.assertTrue(all(not bz.has_in(n) and not bz.has_out(n) for n in nodes))   # côtés droits

    def test_line_curve_transitions_are_g1(self):
        # Stade : deux côtés droits, deux demi-cercles ; droites sans poignées, transitions lisses (même direction).
        def inside(x, y):
            dx = np.clip(x, 60, 140) - x
            return dx * dx + (y - 100) ** 2 < 40 ** 2
        result = tr.trace(aa(inside), tr.settings_for("bw"))
        sub = result[0][1][0]
        straight = [seg for seg in bz.segments(sub) if bz.is_straight(seg)]
        self.assertEqual(len(straight), 2)
        for n in sub["nodes"]:
            if bz.has_in(n) and bz.has_out(n):
                a = math.atan2(n[1] - n[3], n[0] - n[2])
                b = math.atan2(n[5] - n[1], n[4] - n[0])
                self.assertLess(abs((a - b + math.pi) % (2 * math.pi) - math.pi), math.radians(1))
        self.assertLessEqual(len(sub["nodes"]), 6)

    def test_handles_bounded_on_straight_stem(self):
        # Jambage presque droit d'un « m » vectorisé (2026-11-13) : système mal conditionné -> poignées de milliers de px
        # (longue pointe sous la lettre). Une poignée ne dépasse jamais la longueur du tracé approché.
        import math
        from fm_font.shapes import fit_cubic
        piece = [(60.5, 305.0), (68.5, 305.0), (69.5, 304.0), (74.5, 303.0), (78.0, 299.5), (80.0, 294.5),
                 (80.0, 290.5), (81.0, 289.5), (81.0, 213.5), (80.0, 212.5), (79.0, 206.5), (75.5, 202.0),
                 (71.5, 200.0), (62.5, 200.0), (60.5, 201.0)]
        arc = sum(math.dist(a, b) for a, b in zip(piece, piece[1:]))
        for p0, c1, c2, p3 in fit_cubic(piece, 1.5):
            self.assertLess(max(math.dist(p0, c1), math.dist(p3, c2)), arc)

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

    def test_escape_cancels_running_trace(self):
        item = self.ctl.place_image(self.picture(), QPointF(300, 300))
        self.ctl.select([item])
        self.assertTrue(self.ctl.trace_image(tr.settings_for("bw", threshold=160)))
        self.assertTrue(self.ctl.cancel_trace())                    # Échap : calcul abandonné
        self.assertIsNone(self.ctl.tip)
        end = time.monotonic() + 3
        while time.monotonic() < end:
            APP.processEvents()
            time.sleep(0.01)
        self.assertIsNotNone(self.scene.item(item.item_id))          # l'image reste, rien n'est remplacé
        self.assertFalse(self.ctl.cancel_trace())


if __name__ == "__main__":
    unittest.main()
