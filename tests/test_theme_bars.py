"""Moteur des barres d'outils flottantes (fm_theme/bar_manager.py + fm_theme/palette.py), d'après la spec
docs/agents/barres_outils_spec.md et le prototype docs/agents/prototype_barres_outils.html (son code fait foi) :
aimantation en direct aux bords et aux barres, coins et bordures au contact ; et la capture annotée de l'utilisateur :
grille de cases (redimensionnement accroché, icône dans n'importe quelle case libre, d'une barre à l'autre ou dans le vide :
nouvelle barre), titre (glisser, Ctrl + clic, double-clic), barre d'état, état enregistrable."""
import _isolate  # noqa: F401
import os
import unittest
from unittest import mock

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from PySide6.QtCore import QPoint, QRect, Qt  # noqa: E402
from PySide6.QtTest import QTest  # noqa: E402
from PySide6.QtWidgets import QApplication, QWidget  # noqa: E402

from fm_theme import bar_manager as BM  # noqa: E402
from fm_theme import palette as P  # noqa: E402

APP = QApplication.instance() or QApplication([])

STATE = {"next": 4, "bars": [
    {"id": "b1", "title": "Outils", "dock": "top", "orient": "h", "along": 0, "x": 0, "y": 0, "cols": 3, "rows": 1,
     "items": {"square": [0, 0, 1], "triangle": [1, 0, 1], "image": [2, 0, 1]}},
    {"id": "b2", "title": "Créer", "dock": None, "orient": "h", "along": 0, "x": 300, "y": 200, "cols": 8, "rows": 2,
     "items": {"table": [0, 0, 1], "pen": [1, 0, 1], "circle": [2, 0, 1], "opacity": [0, 1, 6]}},
    {"id": "b3", "title": "Calque", "dock": "bottom", "orient": "h", "along": 0, "x": 0, "y": 0, "cols": 5, "rows": 1,
     "items": {"name": [0, 0, 5]}}]}


def make_manager(root: QWidget, state: dict | None = STATE) -> BM.BarManager:
    mgr = BM.BarManager(root)
    for kind in ("square", "triangle", "image", "table", "pen", "circle"):
        mgr.register(kind, P.PaletteButton(kind, kind, P.demo_glyph(kind)))
    opacity = P.PaletteSliderBar("opacity", "Opacité", 0, 100, 80, "%")
    opacity.persist_value = True
    mgr.register("opacity", opacity)
    mgr.register("name", P.PaletteInputBar("name", "Nom", "Calque 1"))
    mgr.default_state = state
    mgr.restore(state)
    return mgr


class BarCase(unittest.TestCase):
    def setUp(self):
        P.set_look({})
        self.addCleanup(P.set_look, {})
        self.root = QWidget()
        self.addCleanup(self.root.deleteLater)
        self.root.resize(800, 600)
        self.mgr = make_manager(self.root)
        self.root.show()
        APP.processEvents()
        self.changed, self.messages = [], []
        self.mgr.layoutChanged.connect(lambda: self.changed.append(1))
        self.mgr.statusChanged.connect(self.messages.append)

    def bar(self, bar_id):
        return self.mgr.bar(bar_id)

    def drag_bar(self, bar, *steps):
        """Glisse le titre de `bar` (sans Ctrl) par les points (de l'espace de travail) `steps`."""
        start = bar.header_rect().center()
        QTest.mousePress(bar, Qt.LeftButton, Qt.NoModifier, start)
        for p in steps:
            QTest.mouseMove(bar, bar.mapFromGlobal(self.root.mapToGlobal(p)))
        QTest.mouseRelease(bar, Qt.LeftButton, Qt.NoModifier, bar.mapFromGlobal(self.root.mapToGlobal(steps[-1])))

    def drag_item(self, key, target_ws, release=True):
        """Glisse l'élément `key` (icône : lui-même ; contrôle : sa poignée) jusqu'au point `target_ws` de l'espace."""
        widget = self.mgr.bar_of(key).item(key)
        start = widget._grip_rect.center() if isinstance(widget, P.PaletteControl) else widget.rect().center()
        QTest.mousePress(widget, Qt.LeftButton, Qt.NoModifier, start)
        QTest.mouseMove(widget, start + QPoint(6, 0))
        QTest.mouseMove(widget, widget.mapFromGlobal(self.root.mapToGlobal(target_ws)))
        if release:
            QTest.mouseRelease(widget, Qt.LeftButton, Qt.NoModifier, widget.mapFromGlobal(self.root.mapToGlobal(target_ws)))
        return widget


class PureFunctionsTest(unittest.TestCase):
    def test_snap_to_picks_the_nearest_candidate_inside_the_tolerance(self):
        self.assertEqual(BM.snap_to(100, [90, 112, 300], 24), 90)
        self.assertEqual(BM.snap_to(100, [150], 24), 100)

    def test_touching_bars_share_one_border_and_square_the_corner(self):
        touch = BM.measure_touch({"a": (200, 100, 100, 50), "b": (300, 100, 100, 50)}, 800, 600)
        self.assertTrue(touch["a"]["tr"] and touch["a"]["br"] and not touch["a"]["nr"])
        self.assertTrue(touch["b"]["tl"] and touch["b"]["bl"] and touch["b"]["nl"])       # égalité : celle de droite
        self.assertFalse(touch["a"]["tl"] or touch["b"]["tr"])

    def test_a_bar_against_the_window_edge_has_square_corners_on_that_side(self):
        touch = BM.measure_touch({"a": (0, 0, 100, 40)}, 800, 600)["a"]
        self.assertTrue(touch["tl"] and touch["tr"] and touch["bl"])
        self.assertFalse(touch["br"])

    def test_the_shorter_bar_gives_up_its_border_and_a_taller_neighbour_keeps_its_round_corner(self):
        """Spec § 4 : « Vue » plus haute que « Créer » collée à elle : le coin bas droit de « Vue » reste arrondi, les
        coins gauches de « Créer » sont carrés ; seule « Créer » efface sa bordure gauche."""
        touch = BM.measure_touch({"vue": (100, 100, 60, 120), "creer": (160, 120, 100, 40)}, 800, 600)
        self.assertFalse(touch["vue"]["br"] or touch["vue"]["tr"])
        self.assertTrue(touch["creer"]["tl"] and touch["creer"]["bl"])
        self.assertTrue(touch["creer"]["nl"])
        self.assertFalse(touch["vue"]["nr"])

    def size_for(self, orient):
        return (100, 40) if orient == "h" else (40, 100)

    def test_dragging_near_an_edge_docks_there(self):
        snap = BM.compute_snap(300, 10, 100, 40, [], 800, 600, 24, self.size_for)
        self.assertEqual((snap["dock"], snap["along"]), ("top", 300))
        self.assertEqual(snap["line"], (0, 0, 800, 3))
        snap = BM.compute_snap(5, 300, 100, 40, [], 800, 600, 24, self.size_for)
        self.assertEqual(snap["dock"], "left")
        self.assertEqual(snap["line"], (0, 0, 3, 600))

    def test_far_from_every_edge_the_bar_floats_and_aligns_on_the_others(self):
        others = [{"x": 300, "y": 300, "w": 100, "h": 40, "dock": None}]
        snap = BM.compute_snap(310, 200, 100, 40, others, 800, 600, 24, self.size_for)
        self.assertIsNone(snap["dock"])
        self.assertEqual(snap["x"], 300)
        snap = BM.compute_snap(500, 200, 100, 40, [], 800, 600, 24, self.size_for)
        self.assertEqual((snap["x"], snap["y"], snap["line"]), (500, 200, None))

    def test_a_bar_snaps_under_a_top_bar_with_the_zone_of_an_edge(self):
        others = [{"x": 0, "y": 0, "w": 300, "h": 60, "dock": "top"}]
        snap = BM.compute_snap(100, 70, 100, 40, others, 800, 600, 24, self.size_for)     # 10 px sous elle
        self.assertEqual((snap["dock"], snap["y"]), (None, 60))
        snap = BM.compute_snap(100, 40, 100, 40, others, 800, 600, 24, self.size_for)     # enfoncée de 20 px
        self.assertEqual((snap["dock"], snap["y"]), (None, 60))
        snap = BM.compute_snap(100, 90, 100, 40, others, 800, 600, 24, self.size_for)     # 30 px : hors zone
        self.assertEqual((snap["dock"], snap["y"]), (None, 90))
        snap = BM.compute_snap(400, 30, 100, 40, others, 800, 600, 10, self.size_for)     # bas à 70, le sien à 60
        self.assertEqual(snap["y"], 30)

    def test_touching_a_docked_bar_docks_on_the_same_edge(self):
        others = [{"x": 0, "y": 0, "w": 200, "h": 40, "dock": "top"}]
        snap = BM.compute_snap(205, 100, 100, 40, others, 800, 600, 10, self.size_for)
        self.assertIsNone(snap["dock"])
        snap = BM.compute_snap(201, 30, 100, 40, others, 800, 600, 10, self.size_for)
        self.assertEqual((snap["dock"], snap["along"]), ("top", 200))

class GridResizeTest(BarCase):
    def test_bars_are_a_whole_grid(self):
        look = P.LOOK
        top = self.bar("b1")
        self.assertEqual(top.width(), 2 * look["border_w"] + 2 * look["margin"] + 3 * look["cell"] + 2 * look["gap"])
        self.assertEqual(top.size(), top.grid_size())

    def test_resizing_by_the_right_edge_reports_in_the_status_bar(self):
        create = self.bar("b2")
        edge = QPoint(create.width() - 2, create.height() // 2)
        QTest.mousePress(create, Qt.LeftButton, Qt.NoModifier, edge)
        QTest.mouseMove(create, edge + QPoint(P.step(), 0))
        QTest.mouseRelease(create, Qt.LeftButton, Qt.NoModifier, edge + QPoint(P.step(), 0))
        self.assertEqual((create.cols, create.rows), (9, 2))
        self.assertEqual(self.messages[-1], "« Créer » : 9 × 2 cases")
        self.assertTrue(self.changed)

    def test_a_bottom_bar_grows_by_its_top_edge_and_stays_on_the_bottom(self):
        bottom = self.bar("b3")
        edge = QPoint(20, 1)
        QTest.mousePress(bottom, Qt.LeftButton, Qt.NoModifier, edge)
        QTest.mouseMove(bottom, edge + QPoint(0, -P.step()))
        QTest.mouseRelease(bottom, Qt.LeftButton, Qt.NoModifier, edge + QPoint(0, -P.step()))
        self.assertEqual(bottom.rows, 2)
        self.assertEqual(bottom.y() + bottom.height(), 600)

    def test_emptied_cells_stay_free_for_later(self):
        create = self.bar("b2")
        self.drag_item("table", QPoint(600, 450))                         # nouvelle barre
        self.assertEqual((create.cols, create.rows), (8, 2))               # la grille garde sa taille
        self.assertTrue(create.free(0, 0, 1))


class BarDragTest(BarCase):
    def test_the_bar_docks_live_before_the_release_and_turns_at_once(self):
        create = self.bar("b2")
        start = create.header_rect().center()
        QTest.mousePress(create, Qt.LeftButton, Qt.NoModifier, start)
        QTest.mouseMove(create, create.mapFromGlobal(self.root.mapToGlobal(QPoint(12, 300))))
        self.assertEqual(create.dock, "left")                             # AVANT le relâchement
        self.assertEqual(create.orient, "v")
        self.assertEqual(create.x(), 0)
        self.assertTrue(self.mgr._line.isVisible())
        QTest.mouseRelease(create, Qt.LeftButton, Qt.NoModifier, create.header_rect().center())
        self.assertFalse(self.mgr._line.isVisible())
        self.assertEqual(self.messages[-1], "« Créer » clipsée à gauche")
        self.assertIs(self.mgr.bars[-1], create)                          # au premier plan

    def test_back_in_the_open_it_floats_with_its_drag_orientation(self):
        create = self.bar("b2")
        self.drag_bar(create, QPoint(500, 300))
        self.assertIsNone(create.dock)
        self.assertEqual(create.orient, "h")
        self.assertEqual(self.messages[-1], "« Créer » flottante")

    def test_a_bar_moving_is_lighter_and_its_shadow_stronger(self):
        create = self.bar("b2")
        self.mgr.begin_bar_drag(create, create.mapToGlobal(create.header_rect().center()))
        self.assertIsNotNone(create.graphicsEffect())                     # 0,94
        self.assertGreater(create.shadow_now()["size"], P.LOOK["shadow"]["size"])
        self.mgr.end_bar_drag(create)
        self.assertIsNone(create.graphicsEffect())

    def test_no_shadow_once_docked(self):
        self.assertIsNone(self.bar("b1").shadow_now())
        self.assertIsNotNone(self.bar("b2").shadow_now())

    def test_a_bar_against_a_top_bar_side_joins_the_top_row(self):
        top, create = self.bar("b1"), self.bar("b2")
        grab = create.header_rect().center()                              # la barre à 5 px de son côté, à 30 px du haut
        target = QPoint(top.x() + top.width() + 5 + grab.x(), 30 + grab.y())
        self.drag_bar(create, target)
        self.assertEqual(create.dock, "top")
        self.assertEqual((create.x(), create.y()), (top.x() + top.width(), 0))

    def test_ctrl_click_renames_and_escape_or_empty_keeps_the_title(self):
        create = self.bar("b2")
        with mock.patch.object(QApplication, "keyboardModifiers", return_value=Qt.ControlModifier):
            QTest.mouseClick(create, Qt.LeftButton, Qt.ControlModifier, create.header_rect().center())
        self.assertIsNotNone(create._edit)
        self.assertEqual((create.x(), create.y()), (300, 200))            # Ctrl + clic ne déplace pas
        create._edit.setText("Formes")
        create._edit.editingFinished.emit()
        self.assertEqual(create.title(), "Formes")
        create.start_rename()
        QTest.keyClick(create._edit, Qt.Key_Escape)
        self.assertEqual(create.title(), "Formes")
        create.start_rename()
        create._edit.setText("   ")
        create._edit.editingFinished.emit()
        self.assertEqual(create.title(), "Formes")

    def test_double_click_turns_a_floating_bar_only(self):
        create, top = self.bar("b2"), self.bar("b1")
        create.mouseDoubleClickEvent(_dbl(create))
        self.assertEqual(create.orient, "v")
        top.mouseDoubleClickEvent(_dbl(top))
        self.assertEqual(top.orient, "h")


def _dbl(bar):
    from PySide6.QtCore import QEvent, QPointF
    from PySide6.QtGui import QMouseEvent
    pos = QPointF(bar.header_rect().center())
    return QMouseEvent(QEvent.MouseButtonDblClick, pos, bar.mapToGlobal(pos), Qt.LeftButton, Qt.LeftButton,
                       Qt.NoModifier)


class ItemDragTest(BarCase):
    def test_a_click_below_four_pixels_clicks_and_a_drag_does_not(self):
        clicks = []
        pen = self.mgr.bar_of("pen").item("pen")
        pen.clicked.connect(lambda: clicks.append(1))
        QTest.mouseClick(pen, Qt.LeftButton, Qt.NoModifier, pen.rect().center())
        self.assertEqual(clicks, [1])
        self.drag_item("pen", QPoint(40, 30))                             # vers « Outils »
        self.assertEqual(clicks, [1])
        self.assertEqual(self.mgr.bar_of("pen").bar_id, "b1")
        self.assertEqual(self.messages[-1], "pen → « Outils »")

    def test_an_icon_goes_into_the_free_cell_under_the_cursor(self):
        create = self.bar("b2")
        point = create.mapTo(self.root, create.cell_rect(6, 0).center())  # une case vide, à droite
        widget = self.drag_item("square", point, release=False)
        self.assertEqual(create._drop, (6, 0, 1))
        self.assertTrue(create._target and create._free_shown)            # case de dépôt, cases libres en pointillés
        self.assertTrue(self.bar("b1").free(0, 0, 1))                      # sa case d'origine est libre
        QTest.mouseRelease(widget, Qt.LeftButton, Qt.NoModifier, widget.mapFromGlobal(self.root.mapToGlobal(point)))
        self.assertEqual(create.cell_of("square"), (6, 0, 1))
        self.assertEqual(widget.geometry(), create.cell_rect(6, 0))
        self.assertIsNone(create._drop)
        self.assertFalse(create._target or create._free_shown)

    def test_a_drop_on_an_item_slides_the_others_and_a_full_bar_grows(self):
        create, top = self.bar("b2"), self.bar("b1")
        self.drag_item("image", create.mapTo(self.root, create.cell_rect(1, 0).center()))       # sur « pen »
        self.assertEqual([create.cell_of(k) for k in ("image", "pen", "circle")],
                         [(1, 0, 1), (2, 0, 1), (3, 0, 1)])                # les autres ont glissé
        self.drag_item("pen", top.mapTo(self.root, top.cell_rect(1, 0).center()))
        self.assertEqual((top.cell_of("pen"), top.cell_of("triangle")), ((1, 0, 1), (2, 0, 1)))
        self.drag_item("circle", top.mapTo(self.root, top.cell_rect(1, 0).center()))      # « Outils » pleine
        self.assertEqual((top.cols, top.rows, top.cell_of("circle")), (3, 2, (1, 0, 1)))
        self.assertEqual(top.cell_of("triangle"), (0, 1, 1))               # la grille gagne une ligne

    def test_a_control_keeps_its_width_from_one_bar_to_another(self):
        create = self.bar("b2")
        create.set_item_width(self.mgr.widgets["opacity"], P.cells_px(7))
        self.drag_item("opacity", QPoint(500, 400))
        self.assertEqual(self.mgr.bar_of("opacity").cell_of("opacity")[2], 7)

    def test_a_drop_in_the_void_makes_a_new_bar_and_an_emptied_bar_disappears(self):
        widget = self.drag_item("name", QPoint(500, 400), release=False)
        self.assertTrue(self.mgr._ghost._new)                             # « + Nouvelle barre »
        QTest.mouseRelease(widget, Qt.LeftButton, Qt.NoModifier, widget.mapFromGlobal(self.root.mapToGlobal(QPoint(500, 400))))
        bar = self.mgr.bar_of("name")
        self.assertEqual(bar.title(), "Barre 4")
        self.assertEqual((bar.x(), bar.y(), bar.dock, bar.orient), (476, 380, None, "h"))
        self.assertIsNone(self.bar("b3"))
        self.assertEqual(self.messages[-1], "Nouvelle barre « Barre 4 » — Ctrl+clic sur son titre pour la renommer"
                                            " · « Calque » vide, supprimée")

    def test_a_control_is_taken_by_its_grip_only(self):
        opacity = self.mgr.bar_of("opacity").item("opacity")
        middle = QPoint(opacity.width() // 2, opacity.height() // 2)
        QTest.mousePress(opacity, Qt.LeftButton, Qt.NoModifier, middle)
        QTest.mouseMove(opacity, middle + QPoint(60, 0))
        QTest.mouseRelease(opacity, Qt.LeftButton, Qt.NoModifier, middle + QPoint(60, 0))
        self.assertEqual(self.mgr.bar_of("opacity").bar_id, "b2")
        self.assertIsNone(self.mgr._item_drag)


class StateTest(BarCase):
    def test_everything_round_trips(self):
        create = self.bar("b2")
        create.set_grid(9, 3)
        self.drag_item("pen", create.mapTo(self.root, create.cell_rect(8, 2).center()))
        opacity = self.mgr.widgets["opacity"]
        create.set_item_width(opacity, 300)
        opacity.setValue(35)
        state = self.mgr.state()
        self.assertEqual(state["widths"]["opacity"], 300)
        self.assertEqual(state["values"]["opacity"], 35)
        other = QWidget()
        other.resize(800, 600)
        self.addCleanup(other.deleteLater)
        mgr = make_manager(other, None)
        mgr.restore(state)
        layout = lambda m: [(b.bar_id, b.title(), b.dock, b.cols, b.rows, b.layout_state()["items"]) for b in m.bars]
        self.assertEqual(layout(mgr), layout(self.mgr))
        self.assertEqual(mgr.bar("b2").cell_of("pen"), (8, 2, 1))
        self.assertEqual(mgr.widgets["opacity"].width(), 300)
        self.assertEqual(mgr.widgets["opacity"].value(), 35)

    def test_a_zero_width_means_the_whole_grid_and_the_memory_keeps_cells(self):
        state = {"next": 3, "bars": [
            {"id": "b1", "title": "Dessin", "dock": None, "orient": "h", "x": 50, "y": 60, "cols": 7, "rows": 2,
             "items": {"square": [0, 0, 1], "opacity": [0, 1, 0]}}],
            "memory": {"name": ["b1", 2, 0, 5]}}
        self.mgr.widgets = {k: v for k, v in self.mgr.widgets.items() if k in ("square", "opacity", "name")}
        self.mgr.restore(state)
        self.assertEqual(self.bar("b1").cell_of("opacity"), (0, 1, 7))
        self.assertEqual(self.bar("b1").cell_of("name"), (2, 0, 5))

    def test_a_list_of_keys_without_cells_is_placed_in_reading_order(self):
        self.mgr.restore({"bars": [{"id": "b1", "title": "A", "cols": 2, "rows": 1, "items": ["square", "pen", "table"]}]})
        self.assertEqual(self.bar("b1").keys()[:3], ["square", "pen", "table"])

    def test_unknown_keys_are_ignored_and_a_new_tool_goes_to_the_first_bar(self):
        state = self.mgr.state()
        state["bars"][0]["items"]["disparu"] = [5, 0, 1]
        state["bars"][1]["items"].pop("circle")
        state["memory"].pop("circle")
        self.mgr.restore(state)
        self.assertEqual(self.mgr.bar_of("circle").bar_id, "b1")

    def test_a_broken_state_falls_back_to_the_default_layout(self):
        self.mgr.restore({"bars": "x"})
        self.assertEqual([b.bar_id for b in self.mgr.bars], ["b1", "b2", "b3"])

    def test_reset_returns_to_the_default_layout(self):
        self.drag_item("pen", QPoint(40, 30))
        self.mgr.reset()
        self.assertEqual(self.mgr.bar_of("pen").bar_id, "b2")


class DynamicItemsTest(BarCase):
    def make(self, *keys):
        return [(k, P.PaletteButton(k, k, P.demo_glyph("square"))) for k in keys]

    def test_new_items_go_to_the_default_bar_then_keep_the_place_the_user_gave(self):
        self.mgr.set_dynamic("ctx", self.make("fill", "border"), "b1")
        self.assertEqual(self.bar("b1").keys()[-2:], ["fill", "border"])
        create = self.bar("b2")
        self.drag_item("fill", create.mapTo(self.root, create.cell_rect(5, 0).center()))
        self.assertEqual(create.cell_of("fill"), (5, 0, 1))
        self.mgr.set_dynamic("ctx", self.make("border", "fill"), "b1")
        self.assertEqual(self.bar("b2").cell_of("fill"), (5, 0, 1))      # refait : il retrouve SA case

    def test_an_emptied_default_bar_is_made_again(self):
        self.drag_item("name", QPoint(500, 400))
        self.assertIsNone(self.bar("b3"))
        self.mgr.set_dynamic("ctx", self.make("lien"), "b3")
        self.assertEqual(self.mgr.bar_of("lien").bar_id, "b3")


class AnchorsTest(BarCase):
    def test_after_and_end(self):
        state = {"bars": [
            {"id": "b1", "title": "A", "dock": "left", "orient": "v", "along": 20, "rows": 1, "items": ["square"]},
            {"id": "b2", "title": "B", "dock": "left", "orient": "v", "after": "b1", "rows": 1, "items": ["pen"]},
            {"id": "b3", "title": "C", "dock": "bottom", "orient": "h", "end": True, "rows": 1, "items": ["image"]}]}
        self.mgr.widgets = {k: v for k, v in self.mgr.widgets.items() if k in ("square", "pen", "image")}
        self.mgr.restore(state)
        a, b, c = self.bar("b1"), self.bar("b2"), self.bar("b3")
        self.assertEqual(b.y(), a.y() + a.height())
        a.add_item("t2", P.PaletteButton("t2", "t2", P.demo_glyph("square")))     # « A » grandit : « B » la suit
        self.assertEqual(b.y(), a.y() + a.height())
        self.assertEqual(c.x() + c.width(), 800)
        self.root.resize(1000, 600)
        APP.processEvents()
        self.assertEqual(c.x() + c.width(), 1000)


class WantedPositionTest(unittest.TestCase):
    def test_a_floating_bar_keeps_the_position_it_was_given_when_the_area_is_tiny_at_first(self):
        P.set_look({})
        root = QWidget()
        root.resize(100, 30)
        mgr = BM.BarManager(root)
        for kind in ("square", "triangle"):
            mgr.register(kind, P.PaletteButton(kind, kind, P.demo_glyph(kind)))
        mgr.restore({"bars": [{"id": "b1", "title": "Dessin", "dock": None, "orient": "h", "x": 96, "y": 150, "rows": 1,
                               "items": ["square", "triangle"]}]})
        bar = mgr.bar("b1")
        root.resize(800, 600)
        mgr.relayout()
        self.assertEqual((bar.x(), bar.y()), (96, 150))
        mgr.set_area(QRect(100, 20, 700, 560))
        self.assertEqual((bar.x(), bar.y()), (196, 170))
        root.deleteLater()


class VisibilityTest(BarCase):
    def test_a_hidden_item_keeps_its_cell_and_an_all_hidden_bar_disappears(self):
        mid = self.bar("b2")
        width = mid.width()
        mid.item("pen").setVisible(False)
        self.mgr.sync_visibility()
        self.assertEqual(mid.width(), width)
        self.assertFalse(mid.free(1, 0, 1))
        for key in mid.keys():
            mid.item(key).setVisible(False)
        self.mgr.sync_visibility()
        self.assertFalse(mid.isVisible())

    def test_the_whole_system_can_be_hidden(self):
        self.mgr.set_visible(False)
        self.assertFalse(any(b.isVisible() for b in self.mgr.bars))
        self.mgr.set_visible(True)
        self.assertTrue(all(b.isVisible() for b in self.mgr.bars))


class TextButtonTest(BarCase):
    def test_a_text_button_is_cells_wide_and_repaints_on_new_text(self):
        pal = self.bar("b2")
        button = P.PaletteTextButton("zoom", "100 %", "Zoom", cells=2)
        pal.add_item("zoom", button)
        look = P.LOOK
        self.assertEqual(button.width(), 2 * look["cell"] + look["gap"])
        button.set_text("1 %")
        before = button.grab().toImage()
        button.set_text("250 000 %")
        self.assertNotEqual(button.grab().toImage(), before)


class PushTest(BarCase):
    """Les barres clipsées sur un même bord ne se chevauchent pas : elles se poussent (demande de l'utilisateur)."""

    def test_a_growing_bar_pushes_its_neighbour_and_it_comes_back(self):
        top = self.bar("b1")
        create = self.bar("b2")
        self.drag_bar(create, QPoint(top.width() + 10 + create.header_rect().center().x(), 30))
        self.assertEqual((create.dock, create.x()), ("top", top.width()))
        x0 = create.x()
        top.set_grid(6, 1)                                                # « Outils » s'élargit
        self.assertEqual(create.x(), top.x() + top.width())              # « Créer » est repoussée
        top.set_grid(3, 1)
        self.assertEqual(create.x(), x0)                                  # et revient à sa place

    def test_a_bar_dropped_on_another_lands_beside_it(self):
        top = self.bar("b1")
        create = self.bar("b2")
        self.drag_bar(create, QPoint(top.width() // 2 + create.header_rect().center().x(), 10))   # sur « Outils »
        self.assertEqual(create.dock, "top")
        self.assertGreaterEqual(create.x(), top.x() + top.width())        # pas de chevauchement


class ArrangeTest(BarCase):
    """Barres d'un bord qui font place, séparateurs au clic droit, rangement Ctrl + clic (demande du 2026-11-03)."""

    def dock_create_beside(self):
        top, create = self.bar("b1"), self.bar("b2")
        self.drag_bar(create, QPoint(top.width() + 10 + create.header_rect().center().x(), 30))
        self.mgr.finish_slides()
        return top, create

    def test_a_bar_dragged_before_another_makes_it_slide(self):
        top, create = self.bar("b1"), self.bar("b2")
        top.want = top.along = 300
        self.mgr.relayout()
        self.drag_bar(create, QPoint(create.header_rect().center().x() + 100, 30), QPoint(create.header_rect().center().x() + 200, 30))
        self.mgr.finish_slides()
        self.assertEqual((create.dock, create.x()), ("top", 200))
        self.assertEqual(top.x(), 200 + create.width())                    # « Outils » a glissé pour lui faire place

    def test_ctrl_clicks_align_the_bars_of_an_edge(self):
        top, create = self.dock_create_beside()
        width = self.mgr.area().width()
        total = top.width() + create.width()
        with mock.patch.object(QApplication, "keyboardModifiers", return_value=Qt.ControlModifier):
            QTest.mouseClick(top, Qt.MiddleButton, Qt.ControlModifier, top.header_rect().center())
            self.mgr.finish_slides()
            self.assertAlmostEqual(top.x(), (width - total) / 2, delta=1)   # centrées
            QTest.mouseClick(top, Qt.MiddleButton, Qt.ControlModifier, QPoint(top.width() - 1, top.height() // 2))
            self.mgr.finish_slides()
            self.assertEqual(create.x() + create.width(), width)            # tranche droite : à droite
            QTest.mouseClick(top, Qt.MiddleButton, Qt.ControlModifier, QPoint(1, top.height() // 2))
            self.mgr.finish_slides()
            self.assertEqual((top.x(), create.x()), (0, top.width()))      # tranche gauche : à gauche

    def test_centring_uses_the_middle_of_the_whole_window(self):
        top, create = self.dock_create_beside()
        self.mgr.set_area(QRect(100, 0, self.root.width() - 100, self.root.height()))      # zone décalée (modules)
        total = top.width() + create.width()
        self.mgr.align_edge("top", "center")
        self.mgr.finish_slides()
        self.assertAlmostEqual(top.x(), (self.root.width() - total) / 2, delta=1)       # milieu de la fenêtre

    def test_a_separator_goes_between_two_icons_and_is_kept(self):
        create = self.bar("b2")
        a, b = create.cell_rect(0, 0), create.cell_rect(1, 0)
        between = QPoint((a.right() + b.left()) // 2, a.center().y())
        self.assertEqual(create.boundary_at(between), (1, 0, "v"))
        self.assertIsNone(create.boundary_at(QPoint(create.cell_rect(0, 0).left() - 1, a.center().y())))
        create._toggle_sep((1, 0, "v"))
        self.assertEqual(create.seps, {(1, 0, "v")})
        saved = self.mgr.state()
        entry = next(b for b in saved["bars"] if b["id"] == "b2")
        self.assertEqual([tuple(s) for s in entry["seps"]], [(1, 0, "v")])
        self.mgr.restore(saved)
        self.assertEqual(self.bar("b2").seps, {(1, 0, "v")})
        create = self.bar("b2")
        create.set_orient("v")
        self.assertEqual(create.seps, {(0, 1, "h")})                       # pivot : le séparateur suit
        create._toggle_sep((0, 1, "h"))
        self.assertEqual(create.seps, set())


class SnappedLookTest(BarCase):
    """Barre clipsée : bordure ôtée du côté collé, en-tête et fond de la couleur de l'élément voisin (réglages)."""

    def test_a_snapped_bar_drops_its_border_and_takes_the_neighbour_colour(self):
        band = QWidget(self.root)
        band.setGeometry(0, 0, 800, 40)
        band.setStyleSheet("background: #ff0000;")
        band.setAttribute(Qt.WA_StyledBackground, True)
        band.show()
        self.mgr.set_area(QRect(0, 40, 800, 560))
        top = self.bar("b1")
        self.assertTrue(dict(top._touch)["et"])                            # collée au bord haut de la zone
        self.assertEqual(top._snap_color, "")                              # réglages coupés : rien n'est capturé
        P.restyle_palettes_in(self.root, {"palette_snap_border_off": True, "palette_snap_header_color": True,
                                          "palette_snap_bg_color": True, "palette_header_bg_color": "#00ff00"})
        self.assertEqual(top._snap_color, "#ff0000")
        image = top.grab().toImage()
        self.assertEqual(image.pixelColor(top.width() // 2, 2).name(), "#ff0000")              # en-tête
        self.assertEqual(image.pixelColor(top.width() // 2, top.height() - 3).name(), "#ff0000")  # fond
        P.restyle_palettes_in(self.root, {})
        self.assertEqual(top._snap_color, "")


class NeighbourTest(BarCase):
    """Voisin à bordure (élément hors de la zone, ou autre barre) : bordure ôtée des deux côtés le long de la barre,
    couleurs du FOND du voisin (pas de sa bordure), bordure de la barre de la couleur de la sienne."""

    def setUp(self):
        super().setUp()
        band = QWidget(self.root)
        band.setGeometry(0, 0, 800, 38)
        band.setStyleSheet("background: #ff0000;")
        line = QWidget(self.root)                                          # bordure du voisin : 2 px bleus
        line.setGeometry(0, 38, 800, 2)
        line.setStyleSheet("background: #0000ff;")
        for w in (band, line):
            w.setAttribute(Qt.WA_StyledBackground, True)
            w.show()
        self.mgr.set_area(QRect(0, 40, 800, 560))

    def test_the_neighbour_fill_and_border_are_read_apart(self):
        top = self.bar("b1")
        P.restyle_palettes_in(self.root, {"palette_snap_border_off": True, "palette_snap_bg_color": True,
                                          "palette_snap_border_match": True})
        self.assertEqual((top._snap_color, top._snap_border, top._snap_border_w), ("#ff0000", "#0000ff", 2))
        patch = self.mgr._patches[(top, "top")]                                     # bordure du voisin ôtée le long de la barre
        self.assertEqual((patch.x(), patch.y(), patch.width(), patch.height()), (top.x(), 38, top.width(), 2))
        image = self.root.grab().toImage()
        self.assertEqual(image.pixelColor(top.x() + top.width() // 2, 39).name(), "#ff0000")
        self.assertEqual(image.pixelColor(top.x() + top.width() + 20, 39).name(), "#0000ff")
        bar = top.grab().toImage()                                         # sa bordure : la couleur du voisin
        self.assertEqual(bar.pixelColor(top.width() // 2, top.height() - 1).name(), "#0000ff")   # (bas : libre)
        P.restyle_palettes_in(self.root, {})
        self.assertEqual(self.mgr._patches, {})

    def test_a_bar_touching_another_takes_its_colours_and_drops_the_shared_border(self):
        top, create = self.bar("b1"), self.bar("b2")
        P.restyle_palettes_in(self.root, {"palette_snap_border_off": True, "palette_snap_bg_color": True})
        create.set_dock(None)
        create.fx, create.fy = top.x(), top.y() + top.height() - 40                # posée sous elle (zone : y 40)
        self.mgr.relayout()
        self.assertTrue(dict(create._touch).get("st"))
        self.assertTrue(dict(top._touch).get("sb"))
        self.assertEqual(create._snap_color, "#ff0000")                    # de proche en proche : le fond du voisin

    def test_the_border_goes_only_along_the_part_that_touches(self):
        top, create = self.bar("b1"), self.bar("b2")
        P.restyle_palettes_in(self.root, {"palette_snap_border_off": True, "palette_snap_bg_color": True,
                                          "palette_snap_border_match": True})
        create.set_dock(None)
        create.fx, create.fy = top.x() + top.width() // 2, top.y() + top.height() - 40    # sous sa moitié droite
        self.mgr.relayout()
        self.assertEqual(dict(top._touch).get("gb"), ((top.width() // 2, top.width()),))
        bar = top.grab().toImage()
        y = top.height() - 1
        self.assertEqual(bar.pixelColor(top.width() // 4, y).name(), "#0000ff")        # libre : bordure gardée
        self.assertEqual(bar.pixelColor(top.width() * 3 // 4, y).name(), "#ff0000")    # collée : ôtée
    def test_the_side_neighbour_loses_its_border_too(self):
        side = QWidget(self.root)                                          # barre des modules : fond vert, bordure
        side.setGeometry(0, 40, 38, 560)                                   # droite de 2 px bleus
        line = QWidget(self.root)
        line.setGeometry(38, 40, 2, 560)
        for w, color in ((side, "#00ff00"), (line, "#0000ff")):
            w.setStyleSheet(f"background: {color};")
            w.setAttribute(Qt.WA_StyledBackground, True)
            w.show()
        self.mgr.set_area(QRect(40, 40, 760, 560))
        top = self.bar("b1")
        P.restyle_palettes_in(self.root, {"palette_snap_border_off": True, "palette_snap_bg_color": True})
        self.assertEqual(top.x(), 40)
        patch = self.mgr._patches[(top, "left")]                           # la barre touche aussi le bord gauche
        self.assertEqual((patch.x(), patch.y(), patch.width(), patch.height()), (38, top.y(), 2, top.height()))
        image = self.root.grab().toImage()
        self.assertEqual(image.pixelColor(39, top.y() + top.height() // 2).name(), "#00ff00")
        self.assertEqual(image.pixelColor(39, top.y() + top.height() + 20).name(), "#0000ff")

class BorderlessNeighbourTest(BarCase):
    """Barre collée contre un élément SANS bordure (demande de l'utilisateur, 2026-11-04) : aucune bordure, sur aucun
    côté, dès qu'un réglage de bordure de barre clipsée est allumé ; une barre collée à elle non plus (de proche en
    proche) ; sans ces réglages, la barre garde la sienne."""

    def setUp(self):
        super().setUp()
        band = QWidget(self.root)                                          # voisin du haut : fond rouge, sans bordure
        band.setGeometry(0, 0, 800, 40)
        band.setStyleSheet("background: #ff0000;")
        band.setAttribute(Qt.WA_StyledBackground, True)
        band.show()
        self.mgr.set_area(QRect(0, 40, 800, 560))

    def sides(self, bar):
        image = bar.grab().toImage()
        w, h = bar.width(), bar.height()
        return {image.pixelColor(0, h // 2).name(), image.pixelColor(w - 1, h // 2).name(),
                image.pixelColor(w // 2, h - 1).name()}

    def test_no_border_at_all_against_a_borderless_neighbour(self):
        top, create = self.bar("b1"), self.bar("b2")
        P.restyle_palettes_in(self.root, {"palette_snap_border_off": True, "palette_snap_bg_color": True})
        self.assertEqual((top._snap_color, top._snap_border), ("#ff0000", ""))
        self.assertTrue(top.borderless())
        self.assertEqual(self.sides(top), {"#ff0000"})                    # gauche, droite, bas : le fond, pas de bordure
        create.set_dock(None)
        create.fx, create.fy = top.x(), top.y() + top.height() - 40         # collée sous elle
        self.mgr.relayout()
        self.assertTrue(create.borderless())
        P.restyle_palettes_in(self.root, {"palette_snap_bg_color": True})   # aucun réglage de bordure : la sienne
        self.assertFalse(top.borderless())
        self.assertNotEqual(self.sides(top), {"#ff0000"})


class CornerTest(BarCase):
    def test_aligning_an_edge_stops_against_a_bar_in_the_corner(self):
        top, create = self.bar("b1"), self.bar("b2")
        create.set_orient("v")
        create.set_dock("left")
        create.want = create.along = 0
        self.mgr.relayout()
        self.mgr.align_edge("top", "start")
        self.mgr.finish_slides()
        self.assertEqual(top.x(), create.x() + create.width())             # contre la barre du coin, pas le bord


class HeadersTest(BarCase):
    """En-têtes masquables (clic droit, réglage) ; sans en-tête, la barre se tire par sa tranche ; curseur flèche."""

    def test_headers_hide_and_the_bar_is_moved_by_its_side(self):
        from fm_theme import hooks
        saved = []
        with mock.patch.dict(hooks.HOOKS, {"save_setting": lambda k, v: saved.append((k, v))}):
            create = self.bar("b2")
            height = create.height()
            P.toggle_headers()
            self.assertEqual(saved, [("palette_header_shown", False)])
            self.assertEqual(P.LOOK["header"], 0)
            self.assertLess(create.height(), height)                         # la bande du titre a disparu
            side = QPoint(2, create.height() // 2)                           # tranche gauche (pas un bord tiré)
            self.assertTrue(create.grab_at(side))
            self.assertFalse(create.grab_at(QPoint(create.width() - 1, create.height() // 2)))   # bord : redimensionner
            x0 = create.x()
            QTest.mousePress(create, Qt.LeftButton, Qt.NoModifier, side)
            QTest.mouseMove(create, side + QPoint(40, 0))
            QTest.mouseRelease(create, Qt.LeftButton, Qt.NoModifier, side + QPoint(40, 0))
            self.assertEqual(create.x(), x0 + 40)
            P.toggle_headers()
            self.assertEqual(saved[-1], ("palette_header_shown", True))
            self.assertEqual(create.height(), height)

    def test_one_bar_hides_its_own_header(self):
        top, create = self.bar("b1"), self.bar("b2")
        height = top.height()
        top._toggle_own_header()
        self.assertEqual(top.header_px(), 0)
        self.assertLess(top.height(), height)
        self.assertGreater(create.header_px(), 0)                          # les autres gardent le leur
        entry = next(b for b in self.mgr.state()["bars"] if b["id"] == "b1")
        self.assertTrue(entry["header_off"])
        self.mgr.restore(self.mgr.state())
        self.assertTrue(self.bar("b1").header_off)

    def test_ctrl_over_a_side_shows_an_arrow_toward_the_edge(self):
        top = self.bar("b1")
        self.assertIs(top._ctrl_cursor(QPoint(1, top.height() // 2)), P.arrow_cursor("left"))
        self.assertIs(top._ctrl_cursor(QPoint(top.width() - 1, top.height() // 2)), P.arrow_cursor("right"))
        self.assertIs(top._ctrl_cursor(top.header_rect().center()), P.arrow_cursor("center"))
        self.assertIsNone(self.bar("b2")._ctrl_cursor(QPoint(1, 20)))      # barre flottante : rien à ranger


if __name__ == "__main__":
    unittest.main()
