"""Module Illustrator du board (paquet fm_illustrator/) : modèle sans Qt (nœuds, Bézier, transformations, SVG),
branchement dans la coque (sélecteur de modules), outils à la souris (formes, sélection, Ctrl + glisser = déplacer,
cadre de sélection, poignées, plume, sélection directe, crayon, plans de travail), clavier, commandes (grouper,
joindre, tracé transparent, suppression de points), annulation, enregistrement / réouverture, export / import SVG."""
import os as _os, sys as _sys  # jamais les vrais réglages / presets de l'utilisateur (tests/_isolate.py)
_sys.path.insert(0, _os.path.dirname(_os.path.abspath(__file__)))
import _isolate  # noqa: E402,F401
import math
import os
import shutil
import sys
import tempfile
import time
import unittest
import xml.etree.ElementTree as ET
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("QT_QPA_FONTDIR", r"C:\Windows\Fonts")       # polices réelles (texte), comme test_context_menu
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from PySide6.QtCore import QEvent, QPointF, QRectF, Qt
from PySide6.QtGui import QKeyEvent, QMouseEvent
from PySide6.QtWidgets import QApplication, QWidget

APP = QApplication.instance() or QApplication([])

from fm_board import model, serialization
from fm_board import ui as board_ui
from fm_illustrator import bezier as bz, model as im, svg
from fm_illustrator.ctl_commands import _split_without
from fm_illustrator.items import IllArtboardItem, IllPathItem

_PANES = []


def settle(seconds=0.03):
    end = time.monotonic() + seconds
    while time.monotonic() < end:
        APP.processEvents()
        time.sleep(0.003)


# ---------------------------------------------------------------- sans Qt
class BezierTest(unittest.TestCase):
    def test_ellipse_bounds_are_exact(self):
        subs = bz.ellipse(50, 40, 30, 20)
        x0, y0, x1, y1 = bz.bounds(subs)
        self.assertAlmostEqual(x0, 20, places=6)
        self.assertAlmostEqual(x1, 80, places=6)
        self.assertAlmostEqual(y0, 20, places=6)
        self.assertAlmostEqual(y1, 60, places=6)

    def test_curve_bounds_include_extrema_not_handles(self):
        sub = {"closed": False, "nodes": [bz.node(0, 0, None, None, 0, -100), bz.node(100, 0, 100, -100)]}
        x0, y0, x1, y1 = bz.bounds([sub])
        self.assertAlmostEqual(y0, -75.0, places=6)           # sommet de la cubique : 3/4 de la poignée
        self.assertEqual((x0, x1, y1), (0.0, 100.0, 0.0))

    def test_insert_node_keeps_the_shape(self):
        subs = bz.ellipse(0, 0, 100, 60)
        before = [bz.cubic_at(*bz.segment(subs[0], 0), t) for t in (0.1, 0.5, 0.9)]
        index = bz.insert_node(subs[0], 0, 0.5)
        self.assertEqual(index, 1)
        self.assertEqual(len(subs[0]["nodes"]), 5)
        mid = subs[0]["nodes"][1]
        self.assertAlmostEqual(math.dist((mid[0], mid[1]), before[1]), 0.0, places=6)
        d, *_rest = bz.nearest(subs, before[0])
        self.assertLess(d, 1e-3)

    def test_transform_rotate_and_scale(self):
        subs = bz.rect(0, 0, 10, 20)
        bz.transform(subs, bz.rotate(90, 0, 0))
        x0, y0, x1, y1 = bz.bounds(subs)
        self.assertAlmostEqual(x0, -20, places=6)
        self.assertAlmostEqual(y1, 10, places=6)
        m = bz.multiply(bz.scale(2, 3), bz.translate(5, 0))
        self.assertEqual(bz.apply(m, 1, 1), (7.0, 3.0))

    def test_smooth_handle_keeps_alignment(self):
        n = bz.node(0, 0, -10, 0, 10, 0, smooth=1)
        bz.set_handle(n, "out", 0, 20)
        self.assertAlmostEqual(n[2], 0.0)
        self.assertAlmostEqual(n[3], -10.0)                    # longueur de l'autre poignée gardée
        bz.set_handle(n, "out", 5, 5, break_link=True)
        self.assertEqual(n[6], 0)

    def test_point_inside_rules(self):
        outer = bz.rect(0, 0, 100, 100)
        inner = bz.rect(25, 25, 50, 50)
        self.assertTrue(bz.point_inside(outer + inner, (50, 50), "nonzero"))
        self.assertFalse(bz.point_inside(outer + inner, (50, 50), "evenodd"))
        self.assertTrue(bz.point_inside(outer + inner, (10, 10), "evenodd"))

    def test_join_and_reverse(self):
        a = bz.line(0, 0, 10, 0)[0]
        b = bz.line(10, 0, 10, 10)[0]
        joined = bz.join(a, b, True, True)
        self.assertEqual([(n[0], n[1]) for n in joined["nodes"]], [(0, 0), (10, 0), (10, 10)])
        bz.reverse(joined)
        self.assertEqual((joined["nodes"][0][0], joined["nodes"][0][1]), (10, 10))

    def test_split_without_opens_closed_path(self):
        sub = bz.rect(0, 0, 10, 10)[0]
        out = _split_without(sub, {0})
        self.assertEqual(len(out), 1)
        self.assertFalse(out[0]["closed"])
        self.assertEqual(len(out[0]["nodes"]), 3)
        line = {"closed": False, "nodes": [bz.node(i, 0) for i in range(5)]}
        parts = _split_without(line, {2})
        self.assertEqual([len(p["nodes"]) for p in parts], [2, 2])


class ModelTest(unittest.TestCase):
    def test_types_known_by_the_board_and_normalized(self):
        raw = {"id": "a", "type": "ill_path", "opacity": 7, "cap": "zigzag", "fill": "rouge",
               "subpaths": [{"closed": True, "nodes": [[0, 0, 0, 0, 0, 0], [1, "x"], [5, 5, 5, 5, 5, 5, 1]]}],
               "future": 3}
        item = model.normalize_item(raw)
        self.assertEqual(item["opacity"], 1.0)
        self.assertEqual(item["cap"], "butt")
        self.assertEqual(item["fill"], im.DEFAULT_FILL)
        self.assertEqual(len(item["subpaths"][0]["nodes"]), 2)    # nœud invalide écarté
        self.assertEqual(item["subpaths"][0]["nodes"][1][6], 1)
        self.assertEqual(item["future"], 3)                       # champ inconnu gardé
        board = model.normalize_item({"id": "b", "type": "ill_artboard", "w": -4})
        self.assertEqual(board["w"], 1.0)


class SvgTest(unittest.TestCase):
    def test_export_is_valid_and_cropped_to_artboard(self):
        path = im.new_entity(im.PATH, subpaths=bz.rect(0, 0, 50, 20), fill="#ff0000", stroke="", x=110.0, y=10.0)
        hidden = im.new_entity(im.PATH, subpaths=bz.rect(0, 0, 5, 5), hidden=True)
        text = svg.export_svg([path, hidden], (100.0, 0.0, 200.0, 100.0), title="Plan")
        root = ET.fromstring(text)
        self.assertEqual(root.get("viewBox"), "0 0 200 100")
        paths = root.findall(f"{{{svg.SVG_NS}}}path")
        self.assertEqual(len(paths), 1)
        self.assertEqual(paths[0].get("d"), "M10 10L60 10L60 30L10 30Z")
        self.assertEqual(paths[0].get("fill"), "#ff0000")

    def test_round_trip_keeps_geometry_and_style(self):
        data = im.new_entity(im.PATH, subpaths=bz.ellipse(40, 40, 30, 20), fill="#80112233", stroke="#00ff00",
                             stroke_width=3.0, cap="round", join="bevel", dash=[4.0, 2.0], fill_rule="evenodd")
        text = svg.export_svg([data], (0.0, 0.0, 100.0, 100.0))
        back = svg.import_svg(text)
        self.assertEqual(len(back), 1)
        b = back[0]
        self.assertEqual((b["fill"], b["stroke"], b["cap"], b["join"], b["fill_rule"]),
                         ("#80112233", "#00ff00", "round", "bevel", "evenodd"))
        self.assertAlmostEqual(b["stroke_width"], 3.0)
        self.assertEqual(b["dash"], [4.0, 2.0])
        for p, q in zip(bz.bounds(b["subpaths"]), bz.bounds(data["subpaths"])):
            self.assertAlmostEqual(p, q, places=2)

    def test_parse_d_relative_smooth_quadratic_and_arcs(self):
        subs = svg.parse_d("m10 10 h20 v20 h-20 z M0 0 Q10 -10 20 0 T40 0 S60 10 70 0 A10 10 0 0 1 90 0")
        self.assertEqual(len(subs), 2)
        self.assertTrue(subs[0]["closed"])
        self.assertEqual(len(subs[0]["nodes"]), 4)
        last = subs[1]["nodes"][-1]
        self.assertAlmostEqual(last[0], 90.0)
        self.assertAlmostEqual(last[1], 0.0)
        box = bz.bounds([subs[1]])
        self.assertAlmostEqual(box[1], -10.0, places=3)           # arc (balayage 1) : demi-cercle vers le haut

    def test_import_shapes_groups_and_transforms(self):
        text = ('<svg xmlns="http://www.w3.org/2000/svg"><g transform="translate(100 0)" opacity="0.5">'
                '<rect x="0" y="0" width="10" height="10" fill="#00f"/><circle cx="20" cy="5" r="5" '
                'style="fill:none;stroke:red;stroke-width:2"/></g><line x1="0" y1="0" x2="5" y2="5" stroke="black"/>'
                '<polygon points="0,0 10,0 5,8"/></svg>')
        out = svg.import_svg(text)
        self.assertEqual(len(out), 4)
        rect, circle, line, poly = out
        self.assertEqual(rect["group"], circle["group"])
        self.assertTrue(rect["group"])
        self.assertEqual(bz.bounds(rect["subpaths"])[0], 100.0)
        self.assertEqual(rect["fill"], "#0000ff")
        self.assertAlmostEqual(rect["opacity"], 0.5)
        self.assertEqual((circle["fill"], circle["stroke"]), ("", "#ff0000"))
        self.assertEqual(line["fill"], "")
        self.assertTrue(poly["subpaths"][0]["closed"])


# ---------------------------------------------------------------- dans le board
class IllTestCase(unittest.TestCase):
    """Board ouvert sur un .mro temporaire, module Illustrator actif, zoom 1 centré sur l'origine."""

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="ill_test_"))
        self.path = serialization.create_board_file(self.tmp / "essai.mro")
        self.host = QWidget()
        self.host.resize(1400, 900)
        self.pane = board_ui.BoardPane(self.host)
        _PANES.append(self.pane)
        self.assertTrue(self.pane.open(self.path))
        self.pane.resize(1400, 900)
        self.host.show()
        self.pane.show()
        self.pane.set_module("illustrator")
        self.ctl = self.pane.illustrator
        self.scene = self.pane.scene
        self.view = self.pane.view
        self.view.set_zoom(1.0)
        self.view.center_on(QPointF(200, 150))
        settle()

    def tearDown(self):
        from PySide6.QtCore import QCoreApplication
        for pane in _PANES:
            try:
                pane._autosave.stop()
                pane.deleteLater()
            except RuntimeError:
                pass
        _PANES.clear()
        self.host.deleteLater()
        QCoreApplication.sendPostedEvents(None, QEvent.DeferredDelete)
        shutil.rmtree(self.tmp, ignore_errors=True)

    def mouse(self, kind, scene_pt, button=Qt.LeftButton, buttons=None, mods=Qt.NoModifier):
        pos = QPointF(self.view.mapFromScene(scene_pt))
        if buttons is None:
            buttons = Qt.NoButton if kind == QEvent.MouseButtonRelease else button
        event = QMouseEvent(kind, pos, QPointF(self.view.viewport().mapToGlobal(pos.toPoint())), button, buttons,
                            mods)
        QApplication.sendEvent(self.view.viewport(), event)

    def click(self, pt, mods=Qt.NoModifier):
        self.mouse(QEvent.MouseButtonPress, pt, mods=mods)
        self.mouse(QEvent.MouseButtonRelease, pt, mods=mods)

    def drag(self, start, end, mods=Qt.NoModifier, steps=4):
        self.mouse(QEvent.MouseButtonPress, start, mods=mods)
        for n in range(1, steps + 1):
            p = start + (end - start) * (n / steps)
            self.mouse(QEvent.MouseMove, p, buttons=Qt.LeftButton, mods=mods)
        self.mouse(QEvent.MouseButtonRelease, end, mods=mods)
        settle()

    def key(self, key, mods=Qt.NoModifier, text=""):
        QApplication.sendEvent(self.view, QKeyEvent(QEvent.KeyPress, key, mods, text))
        settle()

    def paths(self):
        return self.ctl.objects()

    def rect(self, x=100, y=100, w=100, h=60):
        self.ctl.set_tool("rect")
        self.drag(QPointF(x, y), QPointF(x + w, y + h))
        return self.paths()[-1]


class ShellTest(IllTestCase):
    def test_module_button_and_exclusive_modules(self):
        self.assertIn("illustrator", self.pane._module_buttons)
        self.assertTrue(self.ctl.active)
        self.assertIs(self.view.illustrator, self.ctl)
        self.assertTrue(self.ctl.ui.tools.isVisible())
        self.pane.set_module("design")
        self.assertFalse(self.ctl.active)
        self.assertFalse(self.ctl.ui.tools.isVisible())
        self.pane.set_module("cad")
        self.pane.set_module("illustrator")
        self.assertTrue(self.ctl.active)
        self.assertFalse(self.pane.cad_active())
        self.pane.set_module(None)
        self.assertFalse(self.ctl.active)

    def test_fade_and_hide_apply_to_illustrator_items(self):
        item = self.rect()
        self.pane.toggle_module_look("illustrator", "hide")
        self.assertFalse(item.isVisible())
        self.pane.toggle_module_look("illustrator", "hide")
        self.pane.toggle_module_look("illustrator", "fade")
        self.assertLess(item.opacity(), 1.0)
        self.assertFalse(item.isEnabled())

    def test_save_and_reopen(self):
        item = self.rect()
        self.ctl.add_artboard(QRectF(0, 0, 400, 300))
        data = item.to_dict()
        self.assertTrue(self.pane.save())
        self.pane.close_board() if hasattr(self.pane, "close_board") else None
        pane = board_ui.BoardPane(self.host)
        _PANES.append(pane)
        self.assertTrue(pane.open(self.path))
        again = pane.scene.item(item.item_id)
        self.assertIsInstance(again, IllPathItem)
        self.assertEqual(again.to_dict()["subpaths"], data["subpaths"])
        self.assertEqual(len([i for i in pane.scene.board_items() if isinstance(i, IllArtboardItem)]), 1)


class ToolsTest(IllTestCase):
    def test_rectangle_drag_creates_one_undo_step(self):
        item = self.rect(100, 100, 120, 80)
        r = item.geometry_rect()
        self.assertEqual((r.x(), r.y(), r.width(), r.height()), (100, 100, 120, 80))
        self.assertTrue(item.isSelected())
        self.assertEqual(item.data["fill"], im.DEFAULT_FILL)
        self.scene.undo.undo()
        self.assertEqual(self.paths(), [])

    def test_shift_draws_a_circle_alt_from_center(self):
        self.ctl.set_tool("ellipse")
        self.drag(QPointF(200, 200), QPointF(240, 220), mods=Qt.ShiftModifier | Qt.AltModifier)
        r = self.paths()[-1].geometry_rect()
        self.assertAlmostEqual(r.width(), 80, places=3)
        self.assertAlmostEqual(r.height(), 80, places=3)
        self.assertAlmostEqual(r.center().x(), 200, places=3)

    def test_drag_without_ctrl_is_a_marquee_ctrl_drag_moves(self):
        a = self.rect(100, 100, 50, 50)
        b = self.rect(300, 100, 50, 50)
        self.ctl.set_tool("select")
        self.click(QPointF(500, 400))
        self.assertEqual(self.ctl.selection(), [])
        self.drag(QPointF(90, 90), QPointF(160, 120))           # touche a seulement
        self.assertEqual(self.ctl.selection(), [a])
        self.assertEqual(a.geometry_rect().x(), 100)               # rien n'a bougé
        self.drag(QPointF(120, 120), QPointF(150, 160), mods=Qt.ControlModifier)
        self.assertEqual((a.geometry_rect().x(), a.geometry_rect().y()), (130, 140))
        self.assertEqual(b.geometry_rect().x(), 300)
        self.scene.undo.undo()
        self.assertEqual(a.geometry_rect().x(), 100)

    def test_ctrl_alt_drag_moves_a_copy(self):
        a = self.rect(100, 100, 50, 50)
        self.ctl.set_tool("select")
        self.click(QPointF(120, 120))
        self.drag(QPointF(120, 120), QPointF(320, 120), mods=Qt.ControlModifier | Qt.AltModifier)
        self.assertEqual(len(self.paths()), 2)
        self.assertEqual(a.geometry_rect().x(), 100)
        copy = [p for p in self.paths() if p is not a][0]
        self.assertEqual(copy.geometry_rect().x(), 300)

    def test_scale_handle_and_proportions(self):
        a = self.rect(100, 100, 100, 50)
        self.ctl.set_tool("select")
        self.click(QPointF(150, 125))
        self.drag(QPointF(200, 150), QPointF(300, 150))             # coin bas droit vers la droite
        r = a.geometry_rect()
        self.assertAlmostEqual(r.width(), 200, places=3)
        self.assertAlmostEqual(r.height(), 50, places=3)
        self.drag(QPointF(300, 150), QPointF(400, 150), mods=Qt.ShiftModifier)
        r = a.geometry_rect()
        self.assertAlmostEqual(r.width(), 300, places=3)
        self.assertAlmostEqual(r.height(), 75, places=3)
        self.scene.undo.undo()
        self.assertAlmostEqual(a.geometry_rect().width(), 200, places=3)

    def test_pen_corner_smooth_and_close(self):
        self.ctl.set_tool("pen")
        self.click(QPointF(100, 100))
        self.click(QPointF(200, 100))
        self.drag(QPointF(200, 200), QPointF(240, 200))             # point lisse : poignées symétriques
        self.click(QPointF(100, 100))                                 # premier point : fermer
        settle()
        item = self.paths()[-1]
        sub = item.data["subpaths"][0]
        self.assertTrue(sub["closed"])
        self.assertEqual(len(sub["nodes"]), 3)
        smooth = sub["nodes"][2]
        self.assertEqual(smooth[6], 1)
        self.assertAlmostEqual(smooth[4] - smooth[0], 40.0)
        self.assertAlmostEqual(smooth[2] - smooth[0], -40.0)
        self.assertIsNone(self.ctl.tools["pen"].item)
        self.scene.undo.undo()
        self.assertEqual(self.paths(), [])

    def test_pen_enter_finishes_open_path_and_ctrl_z_removes_last_point(self):
        self.ctl.set_tool("pen")
        for x in (100, 150, 200):
            self.click(QPointF(x, 100))
        self.key(Qt.Key_Z, Qt.ControlModifier)
        self.key(Qt.Key_Return)
        item = self.paths()[-1]
        self.assertFalse(item.data["subpaths"][0]["closed"])
        self.assertEqual(len(item.data["subpaths"][0]["nodes"]), 2)

    def test_direct_selection_moves_one_anchor(self):
        a = self.rect(100, 100, 100, 100)
        self.ctl.set_tool("direct")
        self.drag(QPointF(200, 200), QPointF(250, 230))
        nodes = a.data["subpaths"][0]["nodes"]
        self.assertIn([250.0 - a.data["x"], 230.0 - a.data["y"]], [[n[0], n[1]] for n in nodes])
        self.assertIn([0.0, 0.0], [[n[0], n[1]] for n in nodes])     # les autres restent
        self.key(Qt.Key_Delete)                                       # le point choisi disparaît : tracé ouvert
        self.assertFalse(a.data["subpaths"][0]["closed"])
        self.assertEqual(len(a.data["subpaths"][0]["nodes"]), 3)

    def test_pencil_fits_bezier(self):
        self.ctl.set_tool("pencil")
        pts = [QPointF(100 + i * 10, 200 + 40 * math.sin(i / 3)) for i in range(20)]
        self.mouse(QEvent.MouseButtonPress, pts[0])
        for p in pts[1:]:
            self.mouse(QEvent.MouseMove, p, buttons=Qt.LeftButton)
        self.mouse(QEvent.MouseButtonRelease, pts[-1])
        item = self.paths()[-1]
        self.assertLess(len(item.data["subpaths"][0]["nodes"]), 12)
        self.assertEqual(item.data["fill"], "")

    def test_artboard_tool_creates_and_ctrl_moves(self):
        self.ctl.set_tool("artboard")
        self.drag(QPointF(0, 0), QPointF(300, 200))
        boards = self.ctl.artboards()
        self.assertEqual(len(boards), 1)
        self.assertEqual(boards[0].scene_rect(), QRectF(0, 0, 300, 200))
        self.drag(QPointF(100, 100), QPointF(150, 100))               # sans Ctrl : pas de déplacement
        self.assertEqual(boards[0].scene_rect().x(), 0)
        self.drag(QPointF(100, 100), QPointF(150, 100), mods=Qt.ControlModifier)
        self.assertEqual(boards[0].scene_rect().x(), 50)

    def test_keyboard_tools_nudge_and_colors(self):
        a = self.rect()
        self.key(Qt.Key_V, text="v")
        self.assertEqual(self.ctl.tool, "select")
        self.key(Qt.Key_P, text="p")
        self.assertEqual(self.ctl.tool, "pen")
        self.key(Qt.Key_V, text="v")
        self.ctl.select([a])
        self.key(Qt.Key_Right, Qt.ShiftModifier)
        self.assertEqual(a.geometry_rect().x(), 110)
        self.key(Qt.Key_X, Qt.ShiftModifier, "X")
        self.assertEqual((a.data["fill"], a.data["stroke"]), (im.DEFAULT_STROKE, im.DEFAULT_FILL))
        self.key(Qt.Key_D, text="d")
        self.assertEqual((a.data["fill"], a.data["stroke"]), (im.DEFAULT_FILL, im.DEFAULT_STROKE))


class CommandsTest(IllTestCase):
    def test_group_click_selects_group_and_ungroup(self):
        a = self.rect(100, 100, 40, 40)
        b = self.rect(200, 100, 40, 40)
        self.ctl.select([a, b])
        self.key(Qt.Key_G, Qt.ControlModifier)
        self.ctl.set_tool("select")
        self.click(QPointF(500, 500))
        self.click(QPointF(120, 120))
        self.assertEqual(set(self.ctl.selection()), {a, b})
        self.key(Qt.Key_G, Qt.ControlModifier | Qt.ShiftModifier)
        self.assertEqual(a.data["group"], "")

    def test_join_two_open_paths_and_compound(self):
        self.ctl.set_tool("line")
        self.drag(QPointF(100, 100), QPointF(200, 100))
        self.drag(QPointF(200, 100), QPointF(200, 200))
        self.ctl.select(self.paths())
        self.ctl.join_selection()
        self.assertEqual(len(self.paths()), 1)
        self.assertEqual(len(self.paths()[0].data["subpaths"][0]["nodes"]), 3)
        self.scene.undo.undo()
        self.assertEqual(len(self.paths()), 2)
        a = self.rect(300, 100, 100, 100)
        b = self.rect(320, 120, 40, 40)
        self.ctl.select([a, b])
        self.ctl.make_compound(True)
        compound = self.ctl.selection()[0]
        self.assertEqual(len(compound.data["subpaths"]), 2)
        self.assertEqual(compound.data["fill_rule"], "evenodd")

    def test_export_and_import_svg_files(self):
        board = self.ctl.add_artboard(QRectF(0, 0, 400, 300))
        self.rect(100, 100, 50, 50)
        target = self.ctl.export_svg(self.tmp / "plan.svg", board)
        root = ET.parse(target).getroot()
        self.assertEqual(root.get("viewBox"), "0 0 400 300")
        self.assertEqual(len(root.findall(f"{{{svg.SVG_NS}}}path")), 1)
        count = len(self.paths())
        items = self.ctl.import_svg(target, QPointF(600, 600))
        self.assertEqual(len(self.paths()), count + 1)
        self.assertAlmostEqual(items[0].geometry_rect().center().x(), 600, places=3)
        self.scene.undo.undo()
        self.assertEqual(len(self.paths()), count)

    def test_lock_hide_and_select_all(self):
        a = self.rect(100, 100)
        b = self.rect(300, 100)
        self.ctl.select([a])
        self.key(Qt.Key_2, Qt.ControlModifier)
        self.key(Qt.Key_A, Qt.ControlModifier)
        self.assertEqual(self.ctl.selection(), [b])
        self.key(Qt.Key_3, Qt.ControlModifier)
        self.assertFalse(b.isVisible())
        self.key(Qt.Key_3, Qt.ControlModifier | Qt.AltModifier)
        self.assertTrue(b.isVisible())
        self.key(Qt.Key_2, Qt.ControlModifier | Qt.AltModifier)
        self.assertFalse(a.locked())


if __name__ == "__main__":
    unittest.main()
