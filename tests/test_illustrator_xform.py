"""Module Illustrator, tranche 17 : outils à point d'origine (Rotation R, Mise à l'échelle S, Symétrie O : glisser,
clic = origine, Alt + clic = valeur saisie), Transformer de nouveau (Ctrl+D, pas et répétition après Ctrl + Alt +
glisser), Déplacer…, Aligner / Répartir, repères commentés pendant un déplacement (Ctrl+U)."""
import os as _os, sys as _sys  # jamais les vrais réglages / presets de l'utilisateur (tests/_isolate.py)
_sys.path.insert(0, _os.path.dirname(_os.path.abspath(__file__)))
import _isolate  # noqa: E402,F401
import unittest
from unittest import mock

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtWidgets import QInputDialog

from test_illustrator import IllTestCase
from fm_illustrator import bezier as bz


class OriginToolsTest(IllTestCase):
    def test_rotate_tool_around_center(self):
        a = self.rect(100, 100, 100, 40)
        self.key(Qt.Key_R, text="r")
        self.assertEqual(self.ctl.tool, "rotate")
        c = a.geometry_rect().center()
        self.drag(c + QPointF(100, 0), c + QPointF(0, 100))          # +90° autour du centre
        r = a.geometry_rect()
        self.assertAlmostEqual(r.width(), 40, places=3)
        self.assertAlmostEqual(r.center().x(), c.x(), places=3)
        self.scene.undo.undo()
        self.assertAlmostEqual(a.geometry_rect().width(), 100, places=3)

    def test_click_sets_origin_and_alt_click_asks_value(self):
        a = self.rect(100, 100, 100, 100)
        self.ctl.set_tool("scale")
        self.click(QPointF(100, 100))                                  # origine : coin haut gauche
        with mock.patch.object(QInputDialog, "getDouble", return_value=(50.0, True)):
            self.click(QPointF(100, 100), mods=Qt.AltModifier)
        r = a.geometry_rect()
        self.assertEqual((round(r.x()), round(r.y()), round(r.width())), (100, 100, 50))

    def test_scale_tool_uniform_and_reflect(self):
        tri = self.ctl.new_path([{"closed": True, "nodes": [bz.node(0, 0), bz.node(100, 0), bz.node(0, 50)]}],
                                QPointF(100, 100))
        self.ctl.commit_new(tri, "t")
        self.ctl.set_tool("scale")
        self.drag(QPointF(200, 150), QPointF(250, 175), mods=Qt.ShiftModifier)    # depuis le coin : × 2 uniforme
        r = tri.geometry_rect()
        self.assertAlmostEqual(r.width() / r.height(), 2.0, places=3)
        self.assertAlmostEqual(r.width(), 200, delta=1)
        self.ctl.set_tool("reflect")
        c = tri.geometry_rect().center()
        before = [(n[0] + tri.data["x"], n[1] + tri.data["y"]) for n in tri.data["subpaths"][0]["nodes"]]
        self.drag(c + QPointF(0, -50), c + QPointF(0, 60))              # axe vertical par le centre
        after = [(n[0] + tri.data["x"], n[1] + tri.data["y"]) for n in tri.data["subpaths"][0]["nodes"]]
        for (x0, y0), (x1, y1) in zip(before, after):
            self.assertAlmostEqual(x0 + x1, 2 * c.x(), places=3)
            self.assertAlmostEqual(y0, y1, places=3)


class TransformAgainTest(IllTestCase):
    def test_ctrl_d_repeats_rotation(self):
        a = self.rect(100, 100, 100, 40)
        self.ctl.select([a])
        self.ctl.rotate_selection(45)
        self.key(Qt.Key_D, Qt.ControlModifier)
        r = a.geometry_rect()
        self.assertAlmostEqual(r.width(), 40, places=3)                # 45 + 45 = 90°

    def test_step_and_repeat_after_copy_move(self):
        a = self.rect(100, 100, 40, 40)
        self.ctl.set_tool("select")
        self.click(QPointF(120, 120))
        self.drag(QPointF(120, 120), QPointF(180, 120), mods=Qt.ControlModifier | Qt.AltModifier)
        self.key(Qt.Key_D, Qt.ControlModifier)
        self.key(Qt.Key_D, Qt.ControlModifier)
        xs = sorted(round(p.geometry_rect().x()) for p in self.paths())
        self.assertEqual(xs, [100, 160, 220, 280])
        self.assertEqual(round(a.geometry_rect().x()), 100)

    def test_move_dialog(self):
        a = self.rect(100, 100, 40, 40)
        self.ctl.select([a])
        with mock.patch.object(QInputDialog, "getText", return_value=("15, -5", True)):
            self.ctl.move_dialog()
        self.assertEqual((round(a.geometry_rect().x()), round(a.geometry_rect().y())), (115, 95))


class AlignTest(IllTestCase):
    def test_align_and_distribute(self):
        a = self.rect(100, 100, 40, 40)
        b = self.rect(170, 160, 60, 20)
        c = self.rect(400, 220, 20, 50)
        self.ctl.select([a, b, c])
        self.ctl.align("left")
        self.assertEqual({round(i.geometry_rect().x()) for i in (a, b, c)}, {100})
        self.ctl.distribute("v")
        centers = sorted(i.geometry_rect().center().y() for i in (a, b, c))
        self.assertAlmostEqual(centers[1] - centers[0], centers[2] - centers[1], places=3)
        self.ctl.distribute("v", spacing=True)
        rects = sorted((i.geometry_rect() for i in (a, b, c)), key=lambda r: r.top())
        self.assertAlmostEqual(rects[1].top() - rects[0].bottom(), rects[2].top() - rects[1].bottom(), places=3)

    def test_single_object_aligns_to_artboard(self):
        self.ctl.add_artboard(QRectF(0, 0, 400, 300))
        a = self.rect(50, 60, 40, 40)
        self.ctl.select([a])
        self.ctl.align("hcenter")
        self.ctl.align("vcenter")
        self.assertEqual((round(a.geometry_rect().center().x()), round(a.geometry_rect().center().y())), (200, 150))


class SmartGuidesTest(IllTestCase):
    def test_move_snaps_to_edges_and_ctrl_u_turns_off(self):
        self.rect(100, 100, 50, 50)                                     # a : 100-150
        b = self.rect(300, 300, 50, 50)
        self.ctl.set_tool("select")
        self.click(QPointF(320, 320))
        self.drag(QPointF(320, 320), QPointF(173, 123), mods=Qt.ControlModifier)    # gauche 153, haut 103
        r = b.geometry_rect()
        self.assertEqual((r.x(), r.y()), (150.0, 100.0))               # aimanté au bord droit et au haut de a
        self.assertEqual(self.ctl.guides, [])                           # lignes effacées au relâché
        self.scene.undo.undo()
        self.key(Qt.Key_U, Qt.ControlModifier)
        self.assertFalse(self.ctl.smart_guides)
        self.drag(QPointF(320, 320), QPointF(173, 123), mods=Qt.ControlModifier)
        r = b.geometry_rect()
        self.assertEqual((r.x(), r.y()), (153.0, 103.0))


if __name__ == "__main__":
    unittest.main()
