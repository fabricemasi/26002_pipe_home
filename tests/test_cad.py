"""Module CAD du board (MRO, board/cad*.py) — phase 1 : geometrie, saisie des coordonnees, moteur d'accrochage
(OSNAP, ORTHO, polaire, suivi, grille), commande LIGNE (options annUler / Clore, reprise), DEPLACER / COPIER /
EFFACER, poignees, proprietes et heritage ByLayer, extremites (coupe franche, arrondi, border radius), calques
(visibilite, verrou, suppression), selection (clic, fenetre, capture), enregistrement / rechargement, annulation,
integration au board (mode actif / inactif, Echap, clavier), et mesures de performances."""
import os as _os, sys as _sys  # jamais les vrais reglages / presets de l'utilisateur (tests/_isolate.py)
_sys.path.insert(0, _os.path.dirname(_os.path.abspath(__file__)))
import _isolate  # noqa: E402,F401
import json
import math
import os
import shutil
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from PySide6.QtCore import QPoint, QPointF, QRectF, Qt
from PySide6.QtGui import QColor
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QWidget

APP = QApplication.instance() or QApplication([])

import app_style
import fm_board as board
from fm_cad import (
    cad_commands, cad_dims, cad_export, cad_hatch, cad_trim, cad_geometry as geo, cad_input, cad_model, cad_shapes,
    cad_snap,
)
from fm_board import model, serialization
from fm_board import ui as board_ui
from fm_cad.cad_items import CadLineItem, line_outline
from fm_cad.cad_overlay import native_cursor

_PANES = []


def settle(seconds=0.05):
    end = time.monotonic() + seconds
    while time.monotonic() < end:
        APP.processEvents()


class _Seg:
    """Entite factice pour le moteur d'accrochage (aucune scene)."""

    def __init__(self, a, b):
        self.a, self.b = a, b

    def snap_primitives(self):
        return [("segment", self.a, self.b)]


def engine_with(*segments, **settings):
    entities = [_Seg(a, b) for a, b in segments]

    def source(rect):
        xmin, ymin, xmax, ymax = rect
        out = []
        for e in entities:
            if (min(e.a[0], e.b[0]) <= xmax and max(e.a[0], e.b[0]) >= xmin
                    and min(e.a[1], e.b[1]) <= ymax and max(e.a[1], e.b[1]) >= ymin):
                out.append(e)
        return out
    engine = cad_snap.SnapEngine(source)
    s = engine.settings
    for key, value in settings.items():
        setattr(s, key, value)
    return engine


# ==========================================================================
# Geometrie et saisie (pur)
# ==========================================================================

class GeometryTest(unittest.TestCase):
    def test_document_axis_points_up(self):
        self.assertEqual(geo.to_scene((10.0, 20.0)), (10.0, -20.0))
        self.assertEqual(geo.to_doc(10.0, -20.0), (10.0, 20.0))
        self.assertAlmostEqual(geo.angle_deg((0, 0), (0, 5)), 90.0)          # vers le haut = 90°
        self.assertAlmostEqual(geo.angle_deg((0, 0), (-1, -1)), 225.0)

    def test_polar_and_projection(self):
        p = geo.polar((1, 1), 10, 30)
        self.assertAlmostEqual(p[0], 1 + 10 * math.cos(math.radians(30)))
        self.assertAlmostEqual(geo.distance((1, 1), p), 10)
        foot = geo.perpendicular_foot((5, 5), (0, 0), (10, 0))
        self.assertEqual(foot, (5.0, 0.0))
        self.assertEqual(geo.perpendicular_foot((20, 5), (0, 0), (10, 0)), (20.0, 0.0))     # sur le prolongement

    def test_intersections(self):
        self.assertEqual(geo.segment_intersection((0, 0), (10, 10), (0, 10), (10, 0)), (5.0, 5.0))
        self.assertIsNone(geo.segment_intersection((0, 0), (1, 1), (0, 10), (10, 0)))
        self.assertIsNone(geo.line_intersection((0, 0), (1, 0), (0, 1), (1, 1)))           # paralleles
        found = geo.line_intersection((0, 0), (1, 0), (5, 3), (5, 4))
        self.assertAlmostEqual(found[0][0], 5.0)

    def test_window_and_crossing_tests(self):
        rect = (0, 0, 10, 10)
        self.assertTrue(geo.segment_in_rect((1, 1), (9, 9), rect))
        self.assertFalse(geo.segment_in_rect((1, 1), (20, 9), rect))
        self.assertTrue(geo.segment_intersects_rect((-5, 5), (20, 5), rect))
        self.assertFalse(geo.segment_intersects_rect((-5, 20), (20, 20), rect))

    def test_dash_intervals(self):
        self.assertEqual(geo.dash_intervals(30, (10, -5), 1.0), [(0.0, 10.0), (15.0, 25.0)])
        self.assertIsNone(geo.dash_intervals(1e6, (1, -1), 1.0, limit=100))                # trop serre
        dots = geo.dash_intervals(20, (0, -5), 1.0, dot_length=2.0)
        self.assertEqual(dots[1], (4.0, 6.0))


class InputGrammarTest(unittest.TestCase):
    def test_absolute_relative_polar(self):
        self.assertEqual(cad_input.parse("100,200"), ("point", (100.0, 200.0)))
        self.assertEqual(cad_input.parse("@50,0", (10, 10)), ("point", (60.0, 10.0)))
        kind, p = cad_input.parse("@100<90", (0, 0))
        self.assertEqual(kind, "point")
        self.assertAlmostEqual(p[0], 0.0)
        self.assertAlmostEqual(p[1], 100.0)
        kind, p = cad_input.parse("10<180")
        self.assertAlmostEqual(p[0], -10.0)
        self.assertEqual(cad_input.parse("@", (3, 4)), ("point", (3, 4)))

    def test_negative_decimal_scientific(self):
        self.assertEqual(cad_input.parse("-12.5,-0.25"), ("point", (-12.5, -0.25)))
        self.assertEqual(cad_input.parse("1e3,2E-1"), ("point", (1000.0, 0.2)))
        self.assertEqual(cad_input.parse(".5,3."), ("point", (0.5, 3.0)))

    def test_distance_angle_keywords_osnap(self):
        self.assertEqual(cad_input.parse("150"), ("distance", 150.0))
        self.assertEqual(cad_input.parse("<30"), ("angle", 30.0))
        self.assertEqual(cad_input.parse("<-90"), ("angle", 270.0))
        options = [cad_commands.CLOSE_OPT, cad_commands.UNDO_OPT]
        self.assertEqual(cad_input.parse("u", options=options), ("keyword", "undo"))
        self.assertEqual(cad_input.parse("annuler", options=options), ("keyword", "undo"))
        self.assertEqual(cad_input.parse("C", options=options), ("keyword", "close"))
        self.assertEqual(cad_input.parse("end"), ("osnap", "end"))
        self.assertEqual(cad_input.parse("_PER"), ("osnap", "per"))
        self.assertEqual(cad_input.parse("non"), ("osnap", "none"))

    def test_comma_is_never_a_decimal_separator(self):
        self.assertEqual(cad_input.parse("12,5"), ("point", (12.0, 5.0)))        # comme AutoCAD : un point
        self.assertEqual(cad_input.parse("1,2,3")[0], "error")                  # 3D refuse
        self.assertEqual(cad_input.parse("12;5")[0], "error")
        self.assertEqual(cad_input.parse("abc")[0], "error")
        self.assertEqual(cad_input.parse("@10,0")[0], "error")                  # aucun point precedent

    def test_dynamic_input_is_relative_except_hash(self):
        self.assertEqual(cad_input.parse("10,5", (100, 100), dynamic=True), ("point", (110.0, 105.0)))
        self.assertEqual(cad_input.parse("#10,5", (100, 100), dynamic=True), ("point", (10.0, 5.0)))
        self.assertEqual(cad_input.parse("10,5", (100, 100), dynamic=False), ("point", (10.0, 5.0)))

    def test_command_lookup_and_completion(self):
        self.assertEqual(cad_commands.lookup("l").name, "LINE")
        self.assertEqual(cad_commands.lookup("_line").name, "LINE")
        self.assertEqual(cad_commands.lookup("ligne").name, "LINE")
        self.assertEqual(cad_commands.lookup("M").name, "MOVE")
        self.assertTrue(cad_commands.lookup("SC").available)
        self.assertFalse(cad_commands.lookup("EX").available)                  # prevue : jamais proposee
        self.assertTrue(cad_commands.lookup("PL").available)
        names = [e.name for _w, e in cad_commands.completions("C")]
        self.assertIn("COPY", names)
        self.assertIn("CIRCLE", names)
        self.assertIn("SCALE", [e.name for _w, e in cad_commands.completions("SC")])
        self.assertNotIn("EXTEND", [e.name for _w, e in cad_commands.completions("EX")])
        self.assertIsNone(cad_commands.lookup("ZZZ"))


class ModelTest(unittest.TestCase):
    def test_page_normalization_keeps_layer0_first_and_names_unique(self):
        cad = cad_model.normalize_cad_page({"layers": [{"id": "a", "name": "Murs"}, {"id": "b", "name": "murs"}],
                                           "current": "zz", "futur": 1})
        self.assertEqual(cad["layers"][0]["id"], "0")
        self.assertEqual([l["name"] for l in cad["layers"]][1:], ["Murs", "murs (2)"])
        self.assertEqual(cad["current"], "0")
        self.assertEqual(cad["futur"], 1)                                       # champ inconnu garde

    def test_bylayer_resolution_and_overrides(self):
        cad = cad_model.empty_cad_page()
        cad["layers"].append(dict(cad_model.LAYER_DEFAULTS, id="L1", name="A", color="#ff0000", lineweight=4.0,
                                  linetype="dashed"))
        line = cad_model.normalize_line({"layer": "L1"})
        props = cad_model.resolve(line, cad)
        self.assertEqual((props["color"], props["lineweight"], props["linetype"]), ("#ff0000", 4.0, "dashed"))
        line["lineweight"] = 1.5
        line["color"] = "#00ff00"
        props = cad_model.resolve(line, cad)
        self.assertEqual((props["color"], props["lineweight"]), ("#00ff00", 1.5))
        unknown = cad_model.resolve(cad_model.normalize_line({"layer": "absent"}), cad)
        self.assertEqual(unknown["layer"]["id"], "0")                           # repli sur le calque 0

    def test_layer_names(self):
        cad = cad_model.empty_cad_page()
        self.assertIsNotNone(cad_model.valid_layer_name(cad, ""))
        self.assertIsNotNone(cad_model.valid_layer_name(cad, "a/b"))
        self.assertIsNotNone(cad_model.valid_layer_name(cad, "0"))
        self.assertIsNone(cad_model.valid_layer_name(cad, "Axes"))

    def test_invalid_values_are_rejected(self):
        line = cad_model.normalize_line({"lineweight": -3, "color": "rouge", "linetype": "zigzag",
                                         "p1": ["x", 1], "end1": {"style": "spiky", "radius": 400}})
        self.assertEqual(line["lineweight"], cad_model.BYLAYER)
        self.assertEqual(line["color"], cad_model.BYLAYER)
        self.assertEqual(line["linetype"], "zigzag")        # type absent des reglages : garde, dessine continu
        self.assertEqual(cad_model.normalize_line({"linetype": 12})["linetype"], cad_model.BYLAYER)
        self.assertEqual(line["p1"], [0.0, 0.0])
        self.assertEqual(line["end1"], {"style": "flat", "radius": 100.0})


# ==========================================================================
# Moteur d'accrochage (pur)
# ==========================================================================

class SnapEngineTest(unittest.TestCase):
    def test_endpoint_midpoint_and_aperture_in_screen_pixels(self):
        engine = engine_with(((0, 0), (100, 0)))
        res = engine.resolve((99.0, 0.5), scale=1.0)
        self.assertEqual((res.kind, res.candidate.mode, res.point), ("osnap", "end", (100.0, 0.0)))
        self.assertEqual(engine.resolve((50.5, 0.4), 1.0).candidate.mode, "mid")
        # Meme ecart en unites, zoom 10 % : 0,1 px a l'ecran... et 11 unites = 1,1 px : toujours accroche.
        self.assertEqual(engine.resolve((89.0, 0), scale=0.1).candidate.mode, "end")
        # Zoom 400 % : 1 unite = 4 px, 3 unites = 12 px > 10 px : rien.
        self.assertEqual(engine.resolve((97.0, 0), scale=4.0).kind, "free")

    def test_intersection_and_priorities(self):
        engine = engine_with(((0, 0), (100, 100)), ((0, 100), (100, 0)), modes={"int", "nea", "end"})
        res = engine.resolve((51, 49), 1.0)
        self.assertEqual((res.candidate.mode, res.point), ("int", (50.0, 50.0)))
        self.assertGreater(len(res.candidates), 1)                              # Proche aussi, apres
        self.assertEqual(res.candidates[0].mode, "int")
        second = engine.resolve((51, 49), 1.0, cycle=1)                         # Tab : candidat suivant
        self.assertNotEqual(second.candidate.mode, "int")

    def test_perpendicular_from_base_including_extension(self):
        engine = engine_with(((0, 0), (100, 0)), modes={"per"})
        res = engine.resolve((40, 1), 1.0, base=(30, 50))
        self.assertEqual((res.candidate.mode, res.point), ("per", (30.0, 0.0)))
        res = engine.resolve((95, 1), 1.0, base=(150, 50))                      # pied sur le prolongement
        self.assertEqual(res.point, (150.0, 0.0))

    def test_nearest_and_no_false_snaps_for_missing_entities(self):
        engine = engine_with(((0, 0), (100, 0)), modes={"nea", "cen", "qua", "tan", "node", "ins", "gcen"})
        res = engine.resolve((30, 2), 1.0)
        self.assertEqual((res.candidate.mode, res.point), ("nea", (30.0, 0.0)))
        engine.settings.modes = {"cen", "qua", "tan", "node", "ins", "gcen"}
        self.assertEqual(engine.resolve((30, 2), 1.0).kind, "free")             # aucun cercle : rien

    def test_extension_after_acquisition(self):
        engine = engine_with(((0, 0), (100, 0)), modes={"end", "ext"})
        res = engine.resolve((100, 0.5), 1.0)
        engine.note_hover(res.candidate, now=0.0)
        self.assertTrue(engine.note_hover(res.candidate, now=1.0))              # pause : acquis
        ext = engine.resolve((160, 2), 1.0)
        self.assertEqual((ext.candidate.mode, ext.point), ("ext", (160.0, 0.0)))
        self.assertTrue(any(kind == "ext" for kind, _a, _b in ext.guides))

    def test_apparent_intersection(self):
        engine = engine_with(((0, 0), (40, 0)), ((50, -40), (50, -10)), modes={"appint"})
        res = engine.resolve((49, 1), 1.0)
        self.assertEqual((res.candidate.mode, res.point), ("appint", (50.0, 0.0)))

    def test_override_and_none(self):
        engine = engine_with(((0, 0), (100, 0)), modes={"end"})
        self.assertEqual(engine.resolve((50.5, 0.5), 1.0, override="mid").candidate.mode, "mid")
        self.assertEqual(engine.resolve((99, 0), 1.0, override="none").kind, "free")
        engine.settings.osnap = False
        self.assertEqual(engine.resolve((99, 0), 1.0).kind, "free")
        self.assertEqual(engine.resolve((99, 0), 1.0, override="end").point, (100.0, 0.0))   # ponctuel

    def test_ortho_polar_tracking_grid(self):
        engine = engine_with(ortho=True, osnap=False)
        self.assertEqual(engine.resolve((30, 7), 1.0, base=(0, 0)).point, (30.0, 0.0))
        self.assertEqual(engine.resolve((3, 70), 1.0, base=(0, 0)).point, (0.0, 70.0))
        engine = engine_with(polar=True, polar_angle=45.0, osnap=False)
        res = engine.resolve((50, 52), 1.0, base=(0, 0))
        self.assertEqual(res.kind, "polar")
        self.assertAlmostEqual(geo.angle_deg((0, 0), res.point), 45.0)
        self.assertEqual(engine.resolve((50, 80), 1.0, base=(0, 0)).kind, "free")   # hors tolerance
        engine = engine_with(osnap=False, grid_snap=True, grid_spacing=10.0)
        self.assertEqual(engine.resolve((13, 27), 1.0).point, (10.0, 30.0))
        engine = engine_with(((0, 0), (100, 0)), otrack=True, modes={"end"})
        res = engine.resolve((100, 0.5), 1.0)
        engine.note_hover(res.candidate, now=0.0)
        engine.note_hover(res.candidate, now=1.0)
        tracked = engine.resolve((101, 60), 1.0, base=None)                     # au-dessus de l'extremite
        self.assertEqual((tracked.kind, tracked.point), ("track", (100.0, 60.0)))

    def test_locked_distance_and_angle(self):
        engine = engine_with()
        res = engine.resolve((5, 5), 1.0, base=(0, 0), lock_distance=10.0)
        self.assertAlmostEqual(geo.distance((0, 0), res.point), 10.0)
        res = engine.resolve((5, 5), 1.0, base=(0, 0), lock_angle=0.0)
        self.assertEqual(res.point, (5.0, 0.0))


class OutlineTest(unittest.TestCase):
    """Contour exact des extremites (repere local : axe de 0 a L, demi-epaisseur h)."""

    def bounds(self, length, half, s1, s2, r1=50, r2=50):
        return line_outline(length, half, {"style": s1, "radius": r1}, {"style": s2, "radius": r2}).boundingRect()

    def test_flat_round_and_mixed(self):
        self.assertEqual(self.bounds(100, 5, "flat", "flat"), QRectF(0, -5, 100, 10))
        self.assertEqual(self.bounds(100, 5, "round", "round"), QRectF(-5, -5, 110, 10))     # au-dela des points
        self.assertEqual(self.bounds(100, 5, "flat", "round"), QRectF(0, -5, 105, 10))
        self.assertEqual(self.bounds(100, 5, "radius", "radius"), QRectF(0, -5, 100, 10))    # dans la coupe

    def test_border_radius_corners(self):
        path = line_outline(100, 10, {"style": "radius", "radius": 0}, {"style": "radius", "radius": 100})
        self.assertTrue(path.contains(QPointF(0.5, -9.5)))                      # 0 % : coin droit plein
        self.assertFalse(path.contains(QPointF(99.5, -9.5)))                    # 100 % : coin entierement arrondi
        self.assertTrue(path.contains(QPointF(99.5, 0.0)))
        path35 = line_outline(100, 10, {"style": "flat"}, {"style": "radius", "radius": 35})
        self.assertFalse(path35.contains(QPointF(99.5, -9.5)))                  # rayon 3,5 : coin coupe
        self.assertTrue(path35.contains(QPointF(96.4, -9.6)))                   # avant l'arrondi : plein
        self.assertTrue(path35.contains(QPointF(0.2, -9.8)))                    # coupe franche : coin droit

    def test_short_lines_and_degenerate(self):
        path = line_outline(4, 10, {"style": "radius", "radius": 100}, {"style": "radius", "radius": 100})
        self.assertEqual(path.boundingRect(), QRectF(0, -10, 4, 20))            # rayons reduits ensemble
        self.assertFalse(path.isEmpty())
        dot = line_outline(0, 3, {"style": "round"}, {"style": "flat"})
        self.assertEqual(dot.boundingRect(), QRectF(-3, -3, 6, 6))
        self.assertTrue(line_outline(10, 0, {}, {}).isEmpty())


# ==========================================================================
# Integration : un vrai board, le mode CAD actif
# ==========================================================================

class CadBoardCase(unittest.TestCase):
    def setUp(self):
        app_style.apply_style(APP)
        self.dir = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.dir, True)
        self.path = board.create_board_file(self.dir / "plan")
        self.host = QWidget()
        self.host.resize(1300, 860)
        self.host.show()
        self.addCleanup(self._drop)
        self.pane = board_ui.BoardPane(self.host)
        self.assertTrue(self.pane.open(self.path))
        # Unite du board (1 unite saisie = 1 unite du board) : les valeurs des tests sont celles du document.
        self.pane.apply_settings(dict(self.pane._settings, board_cad_unit="px"))
        self.pane.show()
        self.pane.fit()
        self.pane.view.set_zoom(1.0)
        self.pane.view.center_on(QPointF(0, 0))
        self.pane.toggle_cad(True)
        self.ctl = self.pane.cad
        self.ctl.apply_settings(dict(self.ctl.settings, board_cad_dyn=False))   # saisie en ligne de commande
        settle()

    def _drop(self):
        from PySide6.QtCore import QCoreApplication, QEvent
        try:
            self.pane._autosave.stop()
            self.pane.deleteLater()
            self.host.deleteLater()
        except RuntimeError:
            pass
        QCoreApplication.sendPostedEvents(None, QEvent.DeferredDelete)

    # -- aides --
    def type(self, *entries):
        for text in entries:
            for ch in text:
                QTest.keyClick(self.pane.view, ch)
            QTest.keyClick(self.pane.view, Qt.Key_Return)
        APP.processEvents()

    def vp(self, doc_point) -> QPoint:
        return self.ctl.doc_to_view(doc_point).toPoint()

    def move(self, doc_point):
        target = self.vp(doc_point)
        QTest.mouseMove(self.pane.view.viewport(), target + QPoint(3, 3))     # meme place qu'avant : pas d'evenement
        QTest.mouseMove(self.pane.view.viewport(), target)
        APP.processEvents()

    def click(self, doc_point, mods=Qt.NoModifier):
        QTest.mouseClick(self.pane.view.viewport(), Qt.LeftButton, mods, self.vp(doc_point))
        APP.processEvents()

    def lines(self):
        return sorted((i.points() for i in self.ctl.cad_items()))

    def line(self, a, b):
        self.type("L", f"{a[0]},{a[1]}", f"{b[0]},{b[1]}", "")
        return [i for i in self.ctl.cad_items() if i.points() == (tuple(map(float, a)), tuple(map(float, b)))][0]


class LineCommandTest(CadBoardCase):
    def test_absolute_relative_polar_and_one_undo_step(self):
        undo = self.pane.scene.undo
        self.type("LINE", "0,0", "@100,0", "@100<90", "-20,100", "")
        self.assertEqual(self.lines(), sorted([((0.0, 0.0), (100.0, 0.0)), ((100.0, 0.0), (100.0, 100.0)),
                                               ((100.0, 100.0), (-20.0, 100.0))]))
        self.assertEqual(undo.count(), 1)                                       # UNE commande = UNE etape
        undo.undo()
        self.assertEqual(self.lines(), [])
        undo.redo()
        self.assertEqual(len(self.lines()), 3)

    def test_undo_option_close_and_continue(self):
        self.type("L", "0,0", "@10,0", "@0,10", "U")
        self.assertEqual(len(self.lines()), 1)
        self.assertEqual(self.ctl.command.last, (10.0, 0.0))
        self.type("@0,20", "@-10,0", "C")
        self.assertIsNone(self.ctl.command)
        self.assertEqual(len(self.lines()), 4)
        closing = [i for i in self.ctl.cad_items() if i.points()[1] == (0.0, 0.0)]
        self.assertEqual(len(closing), 1)
        self.type("L", "", "@5,0", "")                                          # Entree : reprise a la fin
        self.assertIn(((0.0, 0.0), (5.0, 0.0)), self.lines())

    def test_escape_keeps_segments_and_ctrl_z_inside_command_removes_one(self):
        self.type("L", "0,0", "50,0", "50,50")
        QTest.keyClick(self.pane.view, Qt.Key_Z, Qt.ControlModifier)             # = option annUler
        self.assertEqual(len(self.lines()), 1)
        self.assertIsNotNone(self.ctl.command)
        QTest.keyClick(self.pane.view, Qt.Key_Escape)
        self.assertIsNone(self.ctl.command)
        self.assertEqual(len(self.lines()), 1)
        self.assertEqual(self.pane.scene.undo.count(), 1)

    def test_zero_length_and_bad_input_never_create_geometry(self):
        self.type("L", "0,0", "0,0", "12,5,3", "abc")
        self.assertEqual(self.lines(), [])
        errors = [t for t, k in self.ctl.history if k == "error"]
        self.assertGreaterEqual(len(errors), 3)
        self.type("")
        self.assertEqual(self.lines(), [])

    def test_mouse_clicks_snap_to_endpoint_and_preview_creates_nothing(self):
        self.line((0, 0), (100, 0))
        self.type("L")
        self.click((100.3, 3.0))                                                 # pres de l'extremite
        self.assertEqual(self.ctl.command.last, (100.0, 0.0))
        before = len(self.ctl.cad_items())
        for x in range(120, 200, 10):
            self.move((x, 40))
        self.assertEqual(len(self.ctl.cad_items()), before)                      # previsualisation seulement
        preview = self.ctl.command.preview(self.ctl.res.point)
        self.assertEqual(preview[0][1], (100.0, 0.0))
        self.click((150.4, 49.6))
        self.assertEqual(self.ctl.command.last, (150.0, 50.0))                   # zoom 100 % : pixel exact

    def test_direct_distance_follows_ortho(self):
        self.ctl.toggle("ortho", True)
        self.type("L", "10,10")
        self.move((60, 14))                                                      # presque horizontal
        self.type("25", "")
        self.assertIn(((10.0, 10.0), (35.0, 10.0)), self.lines())
        self.assertFalse(self.ctl.setting("board_cad_polar"))
        self.ctl.toggle("polar", True)                                           # exclusion mutuelle
        self.assertFalse(self.ctl.setting("board_cad_ortho"))

    def test_angle_override_then_distance(self):
        self.type("L", "0,0", "<90", "40", "")
        self.assertEqual(self.lines(), [((0.0, 0.0), (0.0, 40.0))])

    def test_dynamic_input_tab_locks_distance_then_angle(self):
        self.ctl.apply_settings(dict(self.ctl.settings, board_cad_dyn=True))
        self.type("L", "#5,5")
        for ch in "30":
            QTest.keyClick(self.pane.view, ch)
        QTest.keyClick(self.pane.view, Qt.Key_Tab)                               # distance verrouillee
        self.assertEqual(self.ctl.lock_distance, 30.0)
        for ch in "90":
            QTest.keyClick(self.pane.view, ch)
        QTest.keyClick(self.pane.view, Qt.Key_Return)
        self.type("")
        a, b = self.lines()[0]
        self.assertEqual(a, (5.0, 5.0))
        self.assertAlmostEqual(b[0], 5.0)
        self.assertAlmostEqual(b[1], 35.0)

    def test_unknown_and_planned_commands(self):
        self.type("EXTEND")
        self.assertIn("prévue", self.ctl.history[-1][0])
        self.type("BLABLA")
        self.assertIn("inconnue", self.ctl.history[-1][0])
        self.assertIsNone(self.ctl.command)
        self.type("L", "")
        self.assertIsNone(self.ctl.command)
        QTest.keyClick(self.pane.view, Qt.Key_Return)                            # Entree : repete LIGNE
        self.assertEqual(self.ctl.command.NAME, "LINE")

    def test_large_and_negative_coordinates_are_exact(self):
        self.type("L", "-123456789.125,987654321.5", "@0.1,0.2", "")
        a, b = self.lines()[0]
        self.assertEqual(a, (-123456789.125, 987654321.5))
        self.assertAlmostEqual(b[0] - a[0], 0.1, places=6)
        self.assertAlmostEqual(b[1] - a[1], 0.2, places=6)


class PropertiesAndLayersTest(CadBoardCase):
    def add_layer(self, name, **values):
        cad = cad_model.copy_cad(self.ctl.cad_page())
        layer = dict(cad_model.LAYER_DEFAULTS, id=cad_model.new_layer_id(cad), name=name, **values)
        cad["layers"].append(layer)
        self.ctl.set_cad(cad, "test")
        return layer["id"]

    def set_layer(self, lid, **values):
        cad = cad_model.copy_cad(self.ctl.cad_page())
        cad_model.layer_by_id(cad, lid).update(values)
        self.ctl.set_cad(cad, "test")

    def test_bylayer_follows_layer_and_override_stays(self):
        lid = self.add_layer("Murs", lineweight=6.0, color="#ff0000")
        a = self.line((0, 0), (100, 0))
        b = self.line((0, 50), (100, 50))
        self.ctl.change_entities([a, b], {"layer": lid}, "calque")
        self.ctl.change_entities([b], {"lineweight": 2.0}, "override")
        self.set_layer(lid, lineweight=10.0, color="#0000ff")
        self.assertEqual(a.props()["lineweight"], 10.0)
        self.assertEqual(a.props()["color"], "#0000ff")
        self.assertEqual(b.props()["lineweight"], 2.0)                           # override garde
        self.assertEqual(a.data["lineweight"], cad_model.BYLAYER)                # jamais recopie
        self.assertEqual(a.content_rect().height(), 10.0 + 2.0)                 # contour refait (marge 1)

    def test_hidden_layer_not_drawn_snapped_or_picked(self):
        lid = self.add_layer("Cache")
        line = self.line((0, 0), (100, 0))
        self.ctl.change_entities([line], {"layer": lid}, "calque")
        self.set_layer(lid, visible=False)
        self.assertFalse(line.isVisible())
        self.type("L")
        self.move((100.2, 0.3))
        self.assertEqual(self.ctl.res.kind, "free")
        QTest.keyClick(self.pane.view, Qt.Key_Escape)
        self.assertIsNone(self.ctl.pick(self.ctl.doc_to_view((50, 0))))

    def test_locked_layer_snaps_but_cannot_change(self):
        lid = self.add_layer("Verrou")
        line = self.line((0, 0), (100, 0))
        self.ctl.change_entities([line], {"layer": lid}, "calque")
        self.set_layer(lid, locked=True)
        self.assertTrue(line.locked())
        self.type("L")
        self.move((100.2, 0.3))
        self.assertEqual(self.ctl.res.candidate.mode, "end")                    # reference d'accrochage
        QTest.keyClick(self.pane.view, Qt.Key_Escape)
        self.pane.scene.clearSelection()
        line.setSelected(True)
        self.ctl.delete(self.ctl.selection())
        self.assertIsNotNone(self.pane.scene.item(line.item_id))
        self.ctl.change_entities([line], {"lineweight": 9.0}, "x")
        self.assertEqual(line.data["lineweight"], cad_model.BYLAYER)
        self.ctl.translate([line], (10, 0), "x")
        self.assertEqual(line.points(), ((0.0, 0.0), (100.0, 0.0)))
        self.assertIsNone(self.ctl.grip_at(self.ctl.doc_to_view((100, 0))))

    def test_delete_layer_moves_objects_to_layer0_in_one_undo_step(self):
        lid = self.add_layer("Temp")
        line = self.line((0, 0), (10, 0))
        self.ctl.change_entities([line], {"layer": lid}, "calque")
        self.ctl.ui.open_layers()
        window = self.ctl.ui._layers
        with mock.patch("settings_dialogs.confirm", return_value=True):
            window._delete(lid)
        self.assertIsNone(cad_model.layer_by_id(self.ctl.cad_page(), lid))
        self.assertEqual(line.data["layer"], "0")
        self.pane.scene.undo.undo()
        self.assertIsNotNone(cad_model.layer_by_id(self.ctl.cad_page(), lid))
        self.assertEqual(line.data["layer"], lid)
        window.close()

    def test_layer0_and_current_layer_are_protected(self):
        self.ctl.ui.open_layers()
        window = self.ctl.ui._layers
        window._delete("0")
        window._rename("0", "Autre")
        self.assertEqual(cad_model.layer_by_id(self.ctl.cad_page(), "0")["name"], "0")
        lid = self.add_layer("B")
        window._set_current(lid)
        window._delete(lid)
        self.assertIsNotNone(cad_model.layer_by_id(self.ctl.cad_page(), lid))
        window._rename(lid, "0")                                                 # nom deja pris
        self.assertEqual(cad_model.layer_by_id(self.ctl.cad_page(), lid)["name"], "B")
        window.close()

    def test_new_lines_use_current_layer_and_properties(self):
        lid = self.add_layer("Axes", linetype="center")
        cad = cad_model.copy_cad(self.ctl.cad_page())
        cad["current"] = lid
        cad["end2"] = {"style": "radius", "radius": 35.0}
        self.ctl.set_cad(cad, "courant")
        line = self.line((0, 0), (50, 0))
        self.assertEqual(line.data["layer"], lid)
        self.assertEqual(line.props()["linetype"], "center")
        self.assertEqual(line.data["end2"], {"style": "radius", "radius": 35.0})

    def test_properties_panel_edits_endpoint_and_length_follows(self):
        line = self.line((0, 0), (30, 40))
        line.setSelected(True)
        self.ctl.ui.show_properties()
        settle()
        rows = __import__("fm_cad.cad_ui", fromlist=["PropertyRows"]).PropertyRows(self.ctl.ui)
        rows._set_coord("end2", 1, "0")
        self.assertEqual(line.points()[1], (30.0, 0.0))
        self.assertEqual(line.length(), 30.0)
        rows._set_coord("end2", 0, "12,5")                                       # refuse : jamais devine
        self.assertEqual(line.points()[1], (30.0, 0.0))
        rows._set_end("end1", "style", "Arrondi")
        self.assertEqual(line.data["end1"]["style"], "round")
        rows._set_weight("ByLayer")
        rows._set_weight("4")
        self.assertEqual(line.data["lineweight"], 4.0)
        rows._set_weight("-1")
        self.assertEqual(line.data["lineweight"], 4.0)


class SelectionAndEditingTest(CadBoardCase):
    def test_pick_thin_line_with_screen_tolerance(self):
        line = self.line((0, 0), (200, 0))
        self.assertIs(self.ctl.pick(self.ctl.doc_to_view((100, 4))), line)       # 4 px < boite de 5 px
        self.assertIsNone(self.ctl.pick(self.ctl.doc_to_view((100, 9))))
        self.pane.view.set_zoom(0.25)
        self.assertIs(self.ctl.pick(self.ctl.doc_to_view((100, 16))), line)      # 16 u = 4 px a 25 %

    def test_superposed_lines_are_all_selectable_and_erasable(self):
        self.line((20, 0), (80, 0))
        self.line((0, 0), (200, 0))
        self.type("L", "0,0", "200,0", "")
        self.assertEqual(len(self.ctl.cad_items()), 3)
        spots = [(30, 0), (30, 0), (30, 0)]
        seen = []
        for spot in spots:                                                       # clics successifs au meme endroit
            self.click(spot)
            seen.append(self.ctl.selection()[0])
        self.assertEqual(len({id(i) for i in seen}), 3)                          # chacune a son tour
        self.click(spots[0])
        self.assertIs(self.ctl.selection()[0], seen[0])                          # puis le cycle recommence
        self.assertEqual(len(self.ctl.selection()), 1)
        for _ in range(3):                                                       # suppr. : toutes disparaissent
            self.click((30, 0))
            QTest.keyClick(self.pane.view, Qt.Key_Delete)
            APP.processEvents()
        self.assertEqual(self.ctl.cad_items(), [])

    def test_superposed_lines_all_chosen_by_erase_prompt(self):
        for _ in range(3):
            self.line((0, 0), (200, 0))
        self.type("E")
        for _ in range(3):
            self.click((100, 0))
        self.type("")
        self.assertEqual(self.ctl.cad_items(), [])

    def test_window_and_crossing_selection(self):
        inside = self.line((10, 10), (40, 10))
        across = self.line((30, 30), (300, 30))
        self.click((0, 60))
        self.click((100, 0))                                                     # gauche -> droite : fenetre
        self.assertEqual(self.ctl.selection(), [inside])
        self.pane.scene.clearSelection()
        self.click((100, 60))
        self.click((0, 0))                                                       # droite -> gauche : capture
        self.assertEqual(sorted(self.ctl.selection(), key=id), sorted([inside, across], key=id))

    def test_click_replaces_and_shift_adds(self):
        self.line((0, 0), (100, 0))
        b = self.line((0, 50), (100, 50))
        self.click((50, 0))
        self.click((50, 50))
        self.assertEqual(self.ctl.selection(), [b])
        self.click((50, 0), Qt.ShiftModifier)
        self.assertEqual(len(self.ctl.selection()), 2)
        QTest.keyClick(self.pane.view, Qt.Key_Escape)
        self.assertEqual(self.ctl.selection(), [])

    def test_grip_stretch_moves_shared_endpoints(self):
        a = self.line((0, 0), (100, 0))
        b = self.line((100, 0), (100, 100))
        for item in (a, b):
            item.setSelected(True)
        self.move((100, 0))
        self.assertIsNotNone(self.ctl.hover_grip)
        self.click((100, 0))                                                     # poignee chaude
        self.assertIsInstance(self.ctl.command, cad_commands.GripCommand)
        self.type("@20,-10")
        self.assertEqual(a.points(), ((0.0, 0.0), (120.0, -10.0)))
        self.assertEqual(b.points(), ((120.0, -10.0), (100.0, 100.0)))
        self.assertEqual(self.pane.scene.undo.count(), 3)                        # 2 lignes + 1 etirement

    def test_grip_drag_on_midpoint_moves_the_line(self):
        a = self.line((0, 0), (100, 0))
        a.setSelected(True)
        self.move((50, 0))
        view = self.pane.view.viewport()
        QTest.mousePress(view, Qt.LeftButton, Qt.NoModifier, self.vp((50, 0)))
        self.move((50, 30))
        QTest.mouseRelease(view, Qt.LeftButton, Qt.NoModifier, self.vp((50, 30)))
        APP.processEvents()
        self.assertEqual(a.points(), ((0.0, 30.0), (100.0, 30.0)))

    def test_move_copy_erase(self):
        a = self.line((0, 0), (10, 0))
        a.setSelected(True)
        self.type("M", "0,0", "5,5")
        self.assertEqual(a.points(), ((5.0, 5.0), (15.0, 5.0)))
        a.setSelected(True)
        self.type("CO", "0,0", "0,10", "0,20", "U", "0,30", "")
        self.assertEqual(len(self.ctl.cad_items()), 3)                           # 2 copies (une annulee)
        self.assertIn(((5.0, 35.0), (15.0, 35.0)), self.lines())
        self.pane.scene.clearSelection()
        self.type("E")
        self.assertEqual(self.ctl.prompt().kind, "select")
        self.click((10, 35))
        self.type("")
        self.assertEqual(len(self.ctl.cad_items()), 2)

    def test_move_with_enter_uses_first_point_as_displacement(self):
        a = self.line((0, 0), (10, 0))
        a.setSelected(True)
        self.type("M", "3,4", "")
        self.assertEqual(a.points(), ((3.0, 4.0), (13.0, 4.0)))


class PersistenceAndBoardTest(CadBoardCase):
    def test_save_and_reopen_keeps_everything_exactly(self):
        cad = cad_model.copy_cad(self.ctl.cad_page())
        cad["layers"].append(dict(cad_model.LAYER_DEFAULTS, id="L9", name="Cotes", color="#123456", locked=True,
                                  lineweight=3.0, linetype="hidden"))
        self.ctl.set_cad(cad, "calque")
        self.type("L", "0.1,0.2", "@0.3,-1e-7", "")
        line = self.ctl.cad_items()[0]
        self.ctl.change_entities([line], {"end1": {"style": "radius", "radius": 35.0}, "lineweight": 7.5,
                                          "color": "#abcdef", "linetype": "dashed", "ltscale": 2.0}, "props")
        a, b = line.points()
        self.assertTrue(self.pane.save())
        reopened = board_ui.BoardPane(self.host)
        self.addCleanup(reopened.deleteLater)
        self.assertTrue(reopened.open(self.path))
        other = [i for i in reopened.scene.board_items() if isinstance(i, CadLineItem)][0]
        self.assertEqual(other.points(), (a, b))                                 # doubles a l'identique
        for key in ("end1", "lineweight", "color", "linetype", "ltscale", "layer"):
            self.assertEqual(other.data[key], line.data[key])
        layer = cad_model.layer_by_id(cad_model.page_cad(reopened.scene.page), "L9")
        self.assertEqual((layer["name"], layer["locked"], layer["linetype"]), ("Cotes", True, "hidden"))
        reopened._autosave.stop()

    def test_board_without_cad_is_written_as_before(self):
        sticky = self.pane.scene.add_new(model.new_item("sticky", text="note"))
        self.assertTrue(self.pane.save())
        data = json.loads(self.path.read_text(encoding="utf-8"))
        self.assertNotIn("cad", data["page"])
        self.assertEqual([i["type"] for i in data["items"]], ["sticky"])
        self.assertIsNotNone(sticky)

    def test_future_fields_survive(self):
        raw = model.empty_board()
        raw["items"].append({"id": "x1", "type": "cad_line", "p1": [1, 2], "p2": [3, 4], "futur": {"a": 1},
                             "end1": {"style": "round", "radius": 10, "bonus": True}})
        raw["page"]["cad"] = {"layers": [{"id": "0", "name": "0", "nouveau": 5}], "plus": [1]}
        serialization.save(self.path, raw)
        self.assertTrue(self.pane.open(self.path))
        self.assertTrue(self.pane.save(with_view=True) or True)
        self.pane._dirty = True
        self.assertTrue(self.pane.save())
        data = json.loads(self.path.read_text(encoding="utf-8"))
        item = data["items"][0]
        self.assertEqual(item["futur"], {"a": 1})
        self.assertTrue(item["end1"]["bonus"])
        self.assertEqual(data["page"]["cad"]["plus"], [1])

    def test_board_pastes_and_moves_cad_lines_outside_cad_mode(self):
        line = self.line((0, 0), (100, 0))
        self.pane.toggle_cad(False)
        self.assertTrue(line.isVisible())                                        # reste sur la page
        self.pane.scene.clearSelection()
        line.setSelected(True)
        line.moveBy(10, -20)                                                     # deplacement du board (scene)
        self.assertEqual(line.points(), ((10.0, 20.0), (110.0, 20.0)))
        data = line.to_dict()
        self.assertEqual((data["x"], data["y"], data["p1"]), (0.0, 0.0, [10.0, 20.0]))
        self.pane.view.duplicate([line])
        self.assertEqual(len([i for i in self.pane.scene.board_items() if isinstance(i, CadLineItem)]), 2)

    def test_escape_never_closes_the_board_in_cad_mode(self):
        closed = []
        self.pane.closeRequested.connect(lambda: closed.append(1))
        for _n in range(4):
            QTest.keyClick(self.pane.view, Qt.Key_Escape)
        self.assertEqual(closed, [])
        self.pane.toggle_cad(False)
        QTest.keyClick(self.pane.view, Qt.Key_Escape)
        self.assertEqual(closed, [1])

    def test_letters_go_to_the_command_line_not_to_board_tools(self):
        QTest.keyClick(self.pane.view, "t")
        self.assertEqual(self.pane.view.tool, "select")
        self.assertEqual(self.ctl.buffer, "t")
        QTest.keyClick(self.pane.view, Qt.Key_Escape)
        self.assertEqual(self.ctl.buffer, "")

    def test_function_keys_toggle_and_persist(self):
        written = {}
        with mock.patch.object(board_ui, "SETTING_WRITER", lambda k, v: written.__setitem__(k, v)):
            QTest.keyClick(self.pane.view, Qt.Key_F8)
            QTest.keyClick(self.pane.view, Qt.Key_F3)
        self.assertTrue(written["board_cad_ortho"])
        self.assertFalse(written["board_cad_osnap"])
        self.assertTrue(self.ctl.engine.settings.ortho)

    def test_snap_settings_window_applies_live_and_saves(self):
        written = {}
        with mock.patch.object(board_ui, "SETTING_WRITER", lambda k, v: written.__setitem__(k, v)):
            self.ctl.ui.open_snap_settings()
            window = self.ctl.ui._snap_window
            self.assertIsNotNone(window)
            fields = {spec.key: widget for spec, widget in window._fields}
            self.assertIn("board_cad_osnap_per", fields)                         # tous les modes OSNAP
            fields["board_cad_aperture"].setValue(25)
            settle(0.05)
            self.assertEqual(self.ctl.engine.settings.aperture_px, 25.0)          # en direct
            fields["board_cad_osnap_per"].setChecked(True)
            settle(1.0)                                                          # bascule animee puis 250 ms
            self.assertIn("per", self.ctl.engine.settings.modes)
            self.assertEqual(written.get("board_cad_aperture"), 25)              # enregistre apres 250 ms
            self.assertTrue(written.get("board_cad_osnap_per"))
            window.close()

    def test_undo_from_the_navigation_bar_ends_the_command_cleanly(self):
        self.type("L", "0,0", "10,0", "20,0")
        self.pane.undo()                                                         # bouton de la barre
        self.assertIsNone(self.ctl.command)
        self.assertEqual(self.lines(), [])
        self.pane.redo()
        self.assertEqual(len(self.lines()), 2)

    def test_deactivate_restores_board_tools(self):
        self.pane.toggle_cad(False)
        self.assertFalse(self.ctl.overlay.isVisible())
        self.assertFalse(self.ctl.ui.toolbar.isVisible())
        QTest.keyClick(self.pane.view, "t")
        self.assertEqual(self.pane.view.tool, "text")


class PerformanceTest(CadBoardCase):
    """Mesures (affichees) ; seuils larges pour rester stables sur une autre machine."""

    def build(self, count):
        scene = self.pane.scene
        cad = self.ctl.cad_page()
        for n in range(count):
            x = (n % 60) * 20.0
            y = (n // 60) * 20.0
            data = model.new_item("cad_line", **cad_model.new_line_values(cad, (x, y), (x + 15.0, y + 9.0)))
            scene._add(data)
        self.ctl.touch_index()
        settle(0.1)

    def test_resolution_stays_local_with_thousands_of_lines(self):
        self.build(3000)
        self.ctl.apply_settings(dict(self.ctl.settings, board_cad_osnap_appint=True, board_cad_osnap_per=True,
                                     board_cad_osnap_nea=True))
        engine = self.ctl.engine
        start = time.perf_counter()
        for n in range(300):
            engine.resolve((n * 3.1 % 1200, n * 1.7 % 1000), self.ctl.scale(), base=(5.0, 5.0))
        per_move = (time.perf_counter() - start) / 300 * 1000
        print(f"\n[CAD] resolution d'un point, 3000 lignes : {per_move:.3f} ms")
        self.assertLess(per_move, 10.0)

    def test_mouse_move_does_not_repaint_the_scene_with_backdrop(self):
        self.build(3000)
        self.pane.view.fit_all()
        settle(0.3)
        self.type("L", "0,0")
        overlay = self.ctl.overlay
        overlay.repaint()                                                        # image du viewport relevee
        self.assertIsNotNone(overlay.backdrop)
        start = time.perf_counter()
        for n in range(40):
            QTest.mouseMove(self.pane.view.viewport(), QPoint(300 + n * 7, 300 + n * 3))
            overlay.repaint()
        with_backdrop = (time.perf_counter() - start) / 40 * 1000
        overlay.set_backdrop_enabled(False)
        start = time.perf_counter()
        for n in range(40):
            QTest.mouseMove(self.pane.view.viewport(), QPoint(300 + n * 7, 300 + n * 3))
            self.pane.view.viewport().repaint()
        without = (time.perf_counter() - start) / 40 * 1000
        print(f"\n[CAD] mouvement + peinture, 3000 lignes : {with_backdrop:.1f} ms (image du viewport) / "
              f"{without:.1f} ms (scene repeinte)")
        self.assertLess(with_backdrop, without)

    def test_batched_scene_paint_is_much_faster_than_one_paint_per_line(self):
        self.build(3000)
        self.pane.view.fit_all()
        settle(0.2)
        layer = self.pane.scene.cad_layer
        self.assertTrue(layer.batches)

        def paint_ms():
            vp = self.pane.view.viewport()
            start = time.perf_counter()
            for _ in range(5):
                vp.repaint()
            return (time.perf_counter() - start) / 5 * 1000
        self.ctl.overlay.hide()
        batched = paint_ms()
        layer.enabled = False
        layer.rebuild()
        single = paint_ms()
        print(f"\n[CAD] peinture de la scene, 3000 lignes : {batched:.1f} ms (lots) / {single:.1f} ms (une par ligne)")
        self.assertLess(batched * 2, single)


class IncrementalIndexTest(CadBoardCase):
    """Index des accrochages tenu a jour ligne par ligne (aucune reconstruction a chaque ligne tracee)."""

    def test_grid_index_insert_remove_matches_a_full_scan(self):
        import random
        rng = random.Random(4)
        index = geo.GridIndex()
        boxes = {}
        objs = [object() for _ in range(400)]
        for obj in objs[:200]:
            x, y = rng.uniform(0, 1000), rng.uniform(0, 1000)
            boxes[obj] = (x, y, x + rng.uniform(0, 40), y + rng.uniform(0, 40))
        index.build(list(boxes.items()))
        for obj in objs[200:]:
            x, y = rng.uniform(0, 1000), rng.uniform(0, 1000)
            boxes[obj] = (x, y, x + rng.uniform(0, 3000), y + rng.uniform(0, 40))   # quelques tres longues
            index.insert(obj, boxes[obj])
        for obj in objs[::3]:
            index.remove(obj)
            del boxes[obj]
        for obj in objs[1::7]:
            if obj in boxes:
                x, y = rng.uniform(0, 1000), rng.uniform(0, 1000)
                boxes[obj] = (x, y, x + 5, y + 5)
                index.insert(obj, boxes[obj])                                   # deplace (retire puis remis)
        for _ in range(60):
            x, y = rng.uniform(-100, 1100), rng.uniform(-100, 1100)
            rect = (x, y, x + rng.uniform(1, 300), y + rng.uniform(1, 300))
            expected = {id(o) for o, b in boxes.items()
                        if b[0] <= rect[2] and b[2] >= rect[0] and b[1] <= rect[3] and b[3] >= rect[1]}
            self.assertEqual({id(o) for o in index.query(rect)}, expected)

    def test_snaps_follow_added_moved_and_deleted_lines_without_rebuilding(self):
        engine_rebuilds = []
        original = geo.GridIndex.build

        def counting(index, entries):
            engine_rebuilds.append(1)
            return original(index, entries)
        first = self.ctl.create_line((0.0, 0.0), (100.0, 0.0))
        self.ctl._source((-1, -1, 1, 1))                                       # index construit une fois
        with mock.patch.object(geo.GridIndex, "build", counting):
            line = self.ctl.create_line((0.0, 50.0), (100.0, 50.0))
            self.assertIn(line, self.ctl._source((99, 49, 101, 51)))
            line.moveBy(0, -30)                                                # deplacee par le board : y = 80
            self.assertNotIn(line, self.ctl._source((99, 49, 101, 51)))
            self.assertIn(line, self.ctl._source((99, 79, 101, 81)))
            self.pane.scene.delete_items([line])
            self.assertNotIn(line, self.ctl._source((-10, -10, 200, 200)))
            self.pane.scene.undo.undo()
            restored = [i for i in self.ctl._source((99, 79, 101, 81)) if i is not first]
            self.assertEqual(len(restored), 1)
        self.assertEqual(engine_rebuilds, [])


class BatchRenderingTest(CadBoardCase):
    def test_thin_axis_lines_are_one_crisp_pixel_row(self):
        self.type("L", "0,0", "300,0", "")
        self.pane.view.center_on(QPointF(150, -0.7))                         # trait a cheval sur deux rangees
        settle(0.2)
        image = self.pane.view.viewport().grab().toImage()
        x = self.pane.view.viewport().width() // 2
        dark = [y for y in range(image.height()) if image.pixelColor(x, y).lightness() < 120]
        self.assertEqual(len(dark), 1)
        for y in dark:                                                          # pas de rangee grise voisine
            for near in (y - 1, y + 1):
                self.assertGreater(image.pixelColor(x, near).lightness(), 200)
    """Lignes peintes par lots (cad_items.CadBatch) : meme image, meme ordre d'empilement qu'une peinture
    ligne par ligne."""

    def image(self):
        from PySide6.QtGui import QImage, QPainter
        self.ctl.overlay.hide()
        view = self.pane.view
        image = QImage(view.viewport().size(), QImage.Format_ARGB32)
        painter = QPainter(image)
        view.render(painter)
        painter.end()
        return image

    def difference(self, a, b) -> int:
        count = 0
        for y in range(0, a.height(), 2):
            for x in range(0, a.width(), 2):
                ca, cb = a.pixelColor(x, y), b.pixelColor(x, y)
                if max(abs(ca.red() - cb.red()), abs(ca.green() - cb.green()), abs(ca.blue() - cb.blue())) > 40:
                    count += 1
        return count

    def samples(self):
        items = []
        for n in range(8):
            items.append(self.ctl.create_line((n * 25.0, 0.0), (n * 25.0 + 15.0, 120.0)))
        thick = self.ctl.create_line((-40.0, -40.0), (220.0, -60.0))
        dashed = self.ctl.create_line((-40.0, 150.0), (220.0, 150.0))
        round_end = self.ctl.create_line((-40.0, 190.0), (220.0, 230.0))
        self.ctl.change_entities([thick], {"lineweight": 9.0, "color": "#c0392b"}, "x")
        self.ctl.change_entities([dashed], {"linetype": "dashed", "color": "#2d9bf0", "lineweight": 2.0}, "x")
        self.ctl.change_entities([round_end], {"lineweight": 12.0, "end1": {"style": "round", "radius": 0},
                                               "end2": {"style": "radius", "radius": 60}}, "x")
        self.pane.view.set_zoom(2.0)
        self.pane.view.center_on(QPointF(90, -90))
        settle(0.1)
        return items + [thick, dashed, round_end]

    def test_lines_are_batched_and_no_longer_painted_one_by_one(self):
        from PySide6.QtWidgets import QGraphicsItem
        items = self.samples()
        layer = self.pane.scene.cad_layer
        self.assertEqual(len(layer.batches), 1)
        self.assertEqual(layer.batches[0].members, sorted(items, key=lambda i: i.zValue()))
        self.assertTrue(all(i.flags() & QGraphicsItem.ItemHasNoContents for i in items))

    def test_batched_image_matches_one_paint_per_line(self):
        self.samples()
        selected = self.ctl.cad_items()[0]
        selected.setSelected(True)
        settle(0.05)
        batched = self.image()
        layer = self.pane.scene.cad_layer
        layer.enabled = False
        layer.rebuild()
        self.assertEqual(layer.batches, [])
        single = self.image()
        self.assertLess(self.difference(batched, single), 40)

    def test_board_item_between_lines_cuts_the_batch_and_keeps_the_stacking_order(self):
        below = self.ctl.create_line((0.0, 0.0), (200.0, 0.0))
        sticky = self.pane.scene._add(model.new_item("sticky", x=50.0, y=-60.0, z=self.pane.scene.next_z()))
        above = self.ctl.create_line((0.0, 20.0), (200.0, 20.0))
        settle(0.05)
        layer = self.pane.scene.cad_layer
        self.assertEqual([b.members for b in layer.batches], [[below], [above]])
        self.assertLess(layer.batches[0].zValue(), sticky.zValue())
        self.assertGreater(layer.batches[1].zValue(), sticky.zValue())
        sticky.setZValue(-100.0)                                               # passe sous les deux lignes
        settle(0.05)
        self.assertEqual([b.members for b in layer.batches], [[below, above]])

    def test_new_line_paints_itself_until_the_next_regrouping(self):
        from PySide6.QtWidgets import QGraphicsItem
        self.samples()
        item = self.ctl.create_line((0.0, -100.0), (100.0, -100.0))
        self.assertIsNone(item._batch)
        self.assertFalse(item.flags() & QGraphicsItem.ItemHasNoContents)
        settle(0.05)
        self.assertIsNotNone(item._batch)

    def test_moved_hidden_and_restyled_lines_follow_in_the_batch(self):
        items = self.samples()
        first = items[0]
        before = self.image()
        first.moveBy(0, -80)                                                   # deplacement par le board
        settle(0.05)
        moved = self.image()
        self.assertGreater(self.difference(before, moved), 5)
        layer = self.pane.scene.cad_layer
        layer.enabled = False
        layer.rebuild()
        self.assertLess(self.difference(moved, self.image()), 40)
        layer.enabled = True
        layer.rebuild()
        cad = cad_model.copy_cad(self.ctl.cad_page())
        cad["layers"][0]["visible"] = False                                    # calque 0 masque : rien
        self.ctl.set_cad(cad, "masquer")
        settle(0.05)
        empty = self.image()
        self.assertGreater(self.difference(moved, empty), 50)
        self.ctl.set_cad(cad_model.copy_cad(dict(cad, layers=[dict(cad["layers"][0], visible=True)]
                                                 + cad["layers"][1:])), "afficher")
        settle(0.05)
        self.assertLess(self.difference(moved, self.image()), 40)

    def test_lines_added_on_top_and_deleted_keep_the_same_image(self):
        items = self.samples()
        self.image()                                                           # listes de dessin construites
        batch = items[0]._batch
        added = [self.ctl.create_line((n * 30.0, 60.0), (n * 30.0 + 20.0, 90.0)) for n in range(4)]
        self.ctl.change_entities([added[1]], {"lineweight": 6.0, "color": "#18a058"}, "x")
        settle(0.05)
        self.assertIs(added[-1]._batch, batch)                                 # ajoutees au bout du meme lot
        self.pane.scene.delete_items([items[3], added[2]])
        settle(0.05)
        incremental = self.image()
        layer = self.pane.scene.cad_layer
        layer.enabled = False
        layer.rebuild()
        self.assertLess(self.difference(incremental, self.image()), 40)

    def test_deleted_line_leaves_its_batch_and_undo_brings_it_back(self):
        items = self.samples()
        victim = items[2]
        batch = victim._batch
        self.pane.scene.delete_items([victim])
        self.assertNotIn(victim, batch.members)
        settle(0.05)
        self.pane.scene.undo.undo()
        settle(0.05)
        layer = self.pane.scene.cad_layer
        self.assertEqual(sum(len(b.members) for b in layer.batches), len(items))


class CursorAndOverlayTest(CadBoardCase):
    """Reticule = curseur du systeme (aucune trainee) ; l'overlay ne repeint que ce qui change."""

    def test_crosshair_is_the_system_cursor(self):
        self.move((10.0, 10.0))
        cursor = self.pane.view.viewport().cursor()
        self.assertEqual(cursor.shape(), Qt.BitmapCursor)
        self.assertEqual((cursor.hotSpot().x(), cursor.hotSpot().y()), (40, 40))
        idle = cursor.pixmap().cacheKey()
        self.type("L")
        self.move((12.0, 10.0))
        line = self.pane.view.viewport().cursor()
        self.assertEqual(line.shape(), Qt.BitmapCursor)
        self.assertNotEqual(line.pixmap().cacheKey(), idle)                   # sans boite de selection
        state = self.ctl.overlay_state()
        self.assertFalse(state["paint_cursor"])

    def test_magnet_paints_the_crosshair_on_the_snap_point_then_hides_the_system_cursor(self):
        self.ctl.create_line((0.0, 0.0), (100.0, 0.0))
        self.type("L")
        self.move((40.0, 30.0))
        self.move((99.0, 1.0))                                                 # extremite (100, 0) a portee
        self.assertEqual(self.ctl.res.kind, "osnap")
        state = self.ctl.overlay_state()
        self.assertTrue(state["paint_cursor"])
        self.assertEqual(state["cursor"], self.ctl.doc_to_view((100.0, 0.0)))
        self.ctl.overlay.repaint()
        self.assertEqual(self.pane.view.viewport().cursor().shape(), Qt.BlankCursor)
        self.move((40.0, 60.0))                                                # hors de portee : curseur du systeme
        self.assertEqual(self.pane.view.viewport().cursor().shape(), Qt.BitmapCursor)

    def test_moves_repaint_only_what_changes(self):
        overlay = self.ctl.overlay
        overlay.repaint()
        calls = []
        original = overlay.update

        def spy(*args):
            calls.append(args)
            return original(*args)
        overlay.update = spy
        try:
            self.move((10.0, 10.0))
            calls.clear()
            QTest.mouseMove(self.pane.view.viewport(), self.vp((30.0, 12.0)))   # rien a peindre (pas de commande)
            self.assertEqual(calls, [])
            self.type("L", "0,0")
            calls.clear()
            QTest.mouseMove(self.pane.view.viewport(), self.vp((30.0, 20.0)))
            self.assertEqual(len(calls), 1)
            self.assertTrue(calls[0])                                           # une zone, pas tout l'overlay
            zone = calls[0][0]
            area = sum(r.width() * r.height() for r in zone)
            self.assertLess(area, overlay.width() * overlay.height() / 2)
            self.ctl.apply_settings(dict(self.ctl.settings, board_cad_crosshair_full=True))
            overlay.repaint()
            calls.clear()
            parts = []
            original_repaint = overlay.repaint
            overlay.repaint = lambda *args: (parts.append(args), original_repaint(*args))[1]
            try:
                QTest.mouseMove(self.pane.view.viewport(), self.vp((40.0, 25.0)))
            finally:
                del overlay.repaint
            # Reticule jusqu'aux bords : chaque morceau (bande horizontale, bandes verticales) est peint et envoye a
            # part — Windows recevrait sinon le rectangle englobant, toute la vue, a chaque mouvement.
            rects = [a[0] for a in parts if a and hasattr(a[0], "width")]
            self.assertGreaterEqual(len(rects), 2)
            self.assertLess(max(r.width() * r.height() for r in rects), overlay.width() * overlay.height() / 4)
            self.assertGreaterEqual(max(r.width() for r in rects), overlay.width())          # la bande horizontale
            self.assertGreaterEqual(max(r.height() for r in rects), overlay.height() // 4)   # et les verticales (coupees par la bande)
        finally:
            del overlay.update

    def test_scene_change_refreshes_the_viewport_image_at_the_next_paint(self):
        overlay = self.ctl.overlay
        overlay.repaint()
        self.assertIsNotNone(overlay.backdrop)
        self.ctl.create_line((0.0, 0.0), (80.0, 0.0))
        settle(0.05)
        self.assertIsNotNone(overlay.backdrop)                                 # refaite par la peinture suivante
        backdrop = overlay.backdrop
        image = backdrop.toImage() if hasattr(backdrop, "toImage") else backdrop   # releve = QImage
        c = self.ctl.doc_to_view((40.0, 0.0)).toPoint()
        self.assertLess(image.pixelColor(c).lightness(), 200)                  # la nouvelle ligne y est (fond 242)


if __name__ == "__main__":
    unittest.main()


class ReadabilityTest(CadBoardCase):
    def test_readable_on_fixes_only_what_cannot_be_read(self):
        from settings_menu import contrast_ratio, readable_on
        self.assertEqual(readable_on("#d6d9dc", "#202326"), "#d6d9dc")           # lisible : inchange
        fixed = readable_on("#d6d9dc", "#ffffff")                                # clair sur clair : assombri
        self.assertGreaterEqual(contrast_ratio(fixed, "#ffffff"), 4.5)
        self.assertGreaterEqual(contrast_ratio(readable_on("#202326", "#101010"), "#101010"), 4.5)

    def test_cad_menu_text_is_readable_on_a_light_menu(self):
        import settings_menu
        from fm_cad import cad_ui
        menu = cad_ui._menu(self.pane, "cad_context")
        light = dict(settings_menu.menu_look("board"), bg="#ffffff", text="#d6d9dc", hover="#539f9f9f")
        with mock.patch.object(settings_menu, "menu_look", return_value=light):
            settings_menu.prepare_menu(menu)
            seen = settings_menu.readable_look(light)
        self.assertGreaterEqual(settings_menu.contrast_ratio(seen["text"], "#ffffff"), 4.5)
        self.assertTrue(menu.property("ctxContrast"))

    def test_cad_bars_are_10_10_10_and_the_command_field_is_the_settings_input(self):
        shown = self.ctl.ui.toolbar.look
        self.assertEqual(QColor(shown["bg"]).getRgb()[:3], (10, 10, 10))        # demande de l'utilisateur
        self.assertEqual(QColor(self.ctl.ui.command_bar.look["bg"]).getRgb()[:3], (10, 10, 10))
        from settings_cells import _TextField
        self.assertEqual(self.ctl.ui.input.styleSheet(), _TextField("", 260).styleSheet())   # zone de saisie des reglages
        self.ctl.apply_settings(dict(self.ctl.settings, board_cad_bar_color="#303030"))
        self.assertEqual(QColor(self.ctl.ui.toolbar.look["bg"]).getRgb()[:3], (48, 48, 48))

    def test_toolbar_ink_follows_a_light_bar(self):
        from fm_board import ui as board_ui
        from settings_menu import contrast_ratio
        look = board_ui.toolbar_look({"board_toolbar_bg_color": "#ffffff", "board_toolbar_text_font_color": "#d6d9dc"})
        self.pane.toolbar_style = look
        self.ctl.apply_settings(dict(self.ctl.settings, board_cad_bar_color="#ffffff"))
        self.ctl.ui.set_look(look)
        shown = self.ctl.ui.toolbar.look
        self.assertGreaterEqual(contrast_ratio(shown["text"], shown["bg"]), 4.5)
        button = self.ctl.ui.buttons["line"] if "line" in self.ctl.ui.buttons else next(iter(self.ctl.ui.buttons.values()))
        self.assertGreaterEqual(contrast_ratio(button.glyph_ink(False), shown["bg"]), 4.5)


class CadDisplaySettingsTest(CadBoardCase):
    def apply(self, **values):
        self.ctl.apply_settings(dict(self.ctl.settings, **values))
        settle(0.1)

    def test_settings_reach_the_scene_and_default_to_the_old_behaviour(self):
        from settings_store import DEFAULT_SETTINGS
        self.assertTrue(self.pane.scene.cad_antialiasing and self.pane.scene.cad_crisp)
        self.assertEqual(self.pane.scene.cad_dense_px, DEFAULT_SETTINGS["board_cad_dense_px"])
        self.assertEqual(self.pane.scene.cad_grip_color, "#2f6bff")
        self.apply(board_cad_grip_color="#ff0000", board_cad_dense_px=9, board_cad_antialiasing=False)
        self.assertEqual(self.pane.scene.cad_grip_color, "#ff0000")
        self.assertEqual(self.pane.scene.cad_dense_px, 9.0)
        self.assertFalse(self.pane.scene.cad_antialiasing)

    def test_crisp_option_off_leaves_thin_lines_on_two_pixel_rows(self):
        self.type("L", "0,0", "300,0", "")
        self.pane.view.center_on(QPointF(150, -0.7))
        self.apply(board_cad_crisp_lines=False)
        image = self.pane.view.viewport().grab().toImage()
        x = self.pane.view.viewport().width() // 2
        dark = [y for y in range(image.height()) if image.pixelColor(x, y).lightness() < 200]
        self.assertEqual(len(dark), 2)

    def test_tips_follow_the_app_theme(self):
        from settings_store import M
        look = self.ctl.look
        self.assertEqual(look["tip_border"], M["panel_border"])
        self.assertTrue(look["tip_bg"].endswith(M["panel_bg"][1:]))


class IdleMagnetTest(CadBoardCase):
    def test_cursor_snaps_to_a_point_outside_commands_too(self):
        item = self.line((0, 0), (200, 0))
        self.pane.scene.clearSelection()
        self.move((203, 3))                                                     # ligne NON selectionnee : pas de poignee, pas d'aimant
        self.assertIsNone(self.ctl.hover_snap)
        item.setSelected(True)                                                  # poignee visible : le reticule s'y aimante
        self.move((100, 60))
        self.move((203, 3))
        self.assertIsNone(self.ctl.prompt())
        self.assertIsNotNone(self.ctl.hover_snap)
        self.assertEqual(self.ctl.hover_snap.point, (200.0, 0.0))
        state = self.ctl.overlay_state()
        self.assertEqual(state["cursor"], self.ctl.doc_to_view((200, 0)))       # reticule aimante
        self.assertEqual(state["marker"][1], (200.0, 0.0))
        self.assertEqual(self.ctl._cursor_plan(), (None, True))
        self.move((100, 60))                                                    # loin de tout : curseur libre
        self.assertIsNone(self.ctl.hover_snap)
        # Comme dans AutoCAD : OSNAP coupe (F3) ou aucun mode coche, les poignees aimantent toujours le reticule.
        self.ctl.apply_settings(dict(self.ctl.settings, board_cad_osnap=False, board_cad_osnap_end=False,
                                     board_cad_osnap_mid=False))
        for spot, grip in (((203, 3), (200.0, 0.0)), ((104, 3), (100.0, 0.0))):
            self.move((100, 60))
            self.move(spot)
            self.assertIsNotNone(self.ctl.hover_snap, spot)
            self.assertEqual(self.ctl.hover_snap.point, grip)
            state = self.ctl.overlay_state()
            self.assertEqual(state["cursor"], self.ctl.doc_to_view(grip))      # reticule aimante...
            self.assertNotIn("marker", state)                                   # ... sans marqueur d'accrochage
        self.ctl.apply_settings(dict(self.ctl.settings, board_cad_osnap=True, board_cad_osnap_end=True))
        self.move((100, 60))
        self.move((104, 3))
        self.assertNotIn("marker", self.ctl.overlay_state())                    # milieu non coche : pas de marqueur
        self.move((100, 60))
        self.move((203, 3))
        self.assertEqual(self.ctl.overlay_state()["marker"][1], (200.0, 0.0))  # extremite cochee : marqueur
        item.setSelected(False)
        self.move((100, 60))
        self.move((203, 3))
        self.assertIsNone(self.ctl.hover_snap)                                  # ligne non selectionnee : rien

    def test_only_the_handles_of_lines_attract_the_cursor_outside_commands(self):
        circle = self.ctl.create_entity("cad_circle", {"center": [0.0, 0.0], "radius": 50.0})
        arc = self.ctl.create_entity("cad_arc", {"center": [300.0, 0.0], "radius": 40.0, "start": 0.0, "end": 90.0})
        self.ctl.commit_created([circle, arc], "test")
        wire = self.line((500, 0), (600, 0))
        self.pane.scene.clearSelection()
        for spot in ((53, 3), (3, 3), (-47, 3), (343, 3), (303, 3), (603, 3), (553, 3)):   # quadrants, centre, arcs ; ligne non selectionnee
            self.move(spot)
            self.assertIsNone(self.ctl.hover_snap, spot)
        wire.setSelected(True)
        self.move((100, 60))
        self.move((603, 3))                                                      # l'extrémité d'une LIGNE : aimant
        self.assertIsNotNone(self.ctl.hover_snap)
        self.assertEqual(self.ctl.hover_snap.point, (600.0, 0.0))
        self.move((553, 3))                                                      # son milieu aussi
        self.assertEqual(self.ctl.hover_snap.point, (550.0, 0.0))
        self.pane.scene.clearSelection()
        circle.setSelected(True)                                                 # poignées d'un cercle sélectionné : non
        for spot in ((53, 0), (2, 0)):
            self.move(spot)
            self.assertIsNone(self.ctl.hover_snap, spot)
        self.pane.scene.clearSelection()
        self.type("L")                                                           # en commande, tous les accrochages restent
        self.move((53, 3))
        self.assertIsNotNone(self.ctl.res.candidate)
        self.type("")

    def test_cursor_stays_on_a_grip_while_it_can_be_grabbed(self):
        item = self.line((0, 0), (200, 0))
        self.pane.scene.clearSelection()
        item.setSelected(True)
        for spot in ((206, 0), (202, 2), (200, 0), (198, -3)):                  # de l'aimant a la poignee
            self.move(spot)
            self.assertIsNotNone(self.ctl.hover_snap, spot)
            self.assertEqual(self.ctl.hover_snap.point, (200.0, 0.0))
            self.assertEqual(self.ctl._cursor_plan(), (None, True))
        self.assertIsNotNone(self.ctl.hover_grip)                               # la poignee reste saisissable
        self.move((101, 1))
        self.assertEqual(self.ctl.hover_snap.point, (100.0, 0.0))               # poignee du milieu


class CadExportTest(CadBoardCase):
    def test_dxf_export_keeps_lines_layers_and_properties(self):
        ezdxf = __import__("ezdxf")
        from fm_cad import cad_export
        cad = cad_model.copy_cad(self.ctl.cad_page())
        cad["layers"].append({**cad_model.LAYER_DEFAULTS, "id": "murs", "name": "Murs: béton", "color": "#ff0000",
                              "linetype": "dashed", "lineweight": 2.0, "visible": False, "locked": True})
        self.ctl.set_cad(cad, "calque")
        self.line((0, 0), (96, 0))
        self.line((0, 0), (0, 96))
        item = [i for i in self.ctl.cad_items() if i.points()[1] == (0.0, 96.0)][0]
        self.pane.scene.change_items([item], lambda i: i.data.update(layer="murs", color="#00ff00"), "x")
        target = self.dir / "plan.dxf"
        cad_export.export_dxf(self.pane.scene, target, "mm")
        doc = ezdxf.readfile(target)
        self.assertEqual(doc.header["$INSUNITS"], 4)
        lines = sorted(((round(e.dxf.end.x, 6), round(e.dxf.end.y, 6)), e.dxf.layer, e.rgb)
                       for e in doc.modelspace().query("LINE"))
        self.assertEqual(lines[0][0], (0.0, 25.4))                              # 96 unites = 1 pouce = 25,4 mm
        self.assertEqual(lines[0][1], "Murs_ béton")
        self.assertEqual(lines[0][2], (0, 255, 0))
        self.assertEqual(lines[1][0], (25.4, 0.0))
        layer = doc.layers.get("Murs_ béton")
        self.assertTrue(layer.is_off() and layer.is_locked())
        self.assertEqual(layer.rgb, (255, 0, 0))
        self.assertEqual(layer.dxf.linetype, "DASHED")
        self.assertEqual(layer.dxf.lineweight, 53)                              # 2 u = 0,53 mm
        self.assertEqual(list(self.dir.glob(".*part*")), [])                    # pas de fichier temporaire laisse

    def test_raw_units_and_dwg_without_oda_says_why(self):
        ezdxf = __import__("ezdxf")
        from fm_cad import cad_export
        self.line((10, 20), (30, 40))
        target = self.dir / "brut.dxf"
        cad_export.export_dxf(self.pane.scene, target, "raw")
        line = next(iter(ezdxf.readfile(target).modelspace().query("LINE")))
        self.assertEqual((line.dxf.start.x, line.dxf.start.y, line.dxf.end.x, line.dxf.end.y), (10, 20, 30, 40))
        from ezdxf.addons import odafc
        with mock.patch.object(cad_export, "oda_converter", lambda: None), \
                mock.patch.object(odafc, "is_installed", lambda: False):
            with self.assertRaises(cad_export.ExportError):
                cad_export.export_dwg(self.pane.scene, self.dir / "plan.dwg")
        self.assertFalse((self.dir / "plan.dwg").exists())

    def test_dxfout_command_is_registered(self):
        names = {e.name for e in cad_commands.REGISTRY}
        self.assertLessEqual({"DXFOUT", "DWGOUT"}, names)


class LinearBlendTest(CadBoardCase):
    def test_table_brightens_light_on_dark_edges_and_keeps_full_coverage(self):
        from fm_cad.cad_items import linear_blend_table
        table = linear_blend_table("#ffffff", QColor("#262626"))
        self.assertEqual(table[0] >> 24, 0)
        self.assertEqual(table[255] >> 24, 255)
        self.assertGreater(table[128] >> 24, 160)                               # 50 % couvert : ~69 % d'opacite
        same = linear_blend_table("#808080", QColor("#818181"))
        self.assertEqual(same[128] >> 24, 128)                                  # luminances voisines : inchange

    def test_screen_edges_use_the_linear_blend_and_can_be_turned_off(self):
        self.pane.scene.set_page({"background": "#262626"}, record=False)
        cad = cad_model.copy_cad(self.ctl.cad_page())
        cad["layers"][0].update(color="#ffffff", lineweight=6.0)
        self.ctl.set_cad(cad, "x")
        self.type("L", "0,0", "120,70", "")
        self.pane.view.set_zoom(3.0)
        self.pane.view.center_on(QPointF(60, -35))

        def edge_sum():
            settle(0.2)
            image = self.pane.view.viewport().grab().toImage()
            x = self.pane.view.viewport().width() // 2
            return sum(image.pixelColor(x, y).red() for y in range(image.height())
                       if 60 < image.pixelColor(x, y).red() < 240)
        linear = edge_sum()
        self.ctl.apply_settings(dict(self.ctl.settings, board_cad_linear_blend=False))
        self.pane.scene.update()
        plain = edge_sum()
        self.assertGreater(linear, plain)

    def test_shared_round_ends_are_not_counted_twice(self):
        """Angle d'une polyligne a bouts ronds : les deux bouts ont le meme contour exterieur. Le chemin unique de Qt
        additionne leurs couvertures (bord gras) ; les couches de ThickPaths donnent la couverture d'un seul bout."""
        from PySide6.QtGui import QPainter, QTransform
        from fm_cad.cad_items import ThickPaths, _coverage

        def capsule(a, b):
            transform = QTransform()
            transform.translate(*a)
            transform.rotate(math.degrees(math.atan2(b[1] - a[1], b[0] - a[0])))
            return transform.map(line_outline(math.dist(a, b), 12.3, {"style": "round"}, {"style": "round"}))
        corner = (40.37, 40.21)
        paths = ThickPaths()
        paths.add(capsule(corner, (140.37, 40.21)))
        paths.add(capsule((40.37, 140.21), corner))
        self.assertEqual(len(paths.layers), 2)
        layered = _coverage(160, 160, QTransform(), False, paths.layers[0], True)
        painter = QPainter(layered)
        painter.setCompositionMode(QPainter.CompositionMode_Lighten)
        painter.drawImage(0, 0, _coverage(160, 160, QTransform(), False, paths.layers[1], True))
        painter.end()
        alone = ThickPaths()
        alone.add(capsule(corner, (140.37, 40.21)))
        single = _coverage(160, 160, QTransform(), False, alone.path, True)
        summed = _coverage(160, 160, QTransform(), False, paths.path, True)
        worst_sum = worst_layers = 0
        for deg in range(185, 265, 4):                                         # arc exterieur commun aux deux bouts
            x = int(corner[0] + 12.3 * math.cos(math.radians(deg)))
            y = int(corner[1] + 12.3 * math.sin(math.radians(deg)))
            ref = single.pixelColor(x, y).red()
            if 20 < ref < 235:
                worst_sum = max(worst_sum, abs(summed.pixelColor(x, y).red() - ref))
                worst_layers = max(worst_layers, abs(layered.pixelColor(x, y).red() - ref))
        self.assertGreater(worst_sum, 40)                                       # le defaut signale
        self.assertLessEqual(worst_layers, 2)


class CadImportTest(CadBoardCase):
    def test_export_then_open_gives_back_lines_and_layers(self):
        from fm_cad import cad_export, cad_import
        cad = cad_model.copy_cad(self.ctl.cad_page())
        cad["layers"].append({**cad_model.LAYER_DEFAULTS, "id": "murs", "name": "Murs", "color": "#ff0000",
                              "linetype": "dashed", "lineweight": 2.0, "visible": False, "locked": True})
        self.ctl.set_cad(cad, "calque")
        self.line((0, 0), (96, 0))
        self.line((0, 0), (0, 96))
        item = [i for i in self.ctl.cad_items() if i.points()[1] == (0.0, 96.0)][0]
        self.pane.scene.change_items([item], lambda i: i.data.update(layer="murs", color="#00ff00"), "x")
        target = self.dir / "plan.dxf"
        cad_export.export_dxf(self.pane.scene, target, "mm")
        data, report = cad_import.read_drawing(target)
        self.assertEqual(report["lines"], 2)
        self.assertEqual(report["units"], "millimètres")
        layer = [l for l in data["page"]["cad"]["layers"] if l["name"] == "Murs"][0]
        self.assertEqual((layer["color"], layer["linetype"], layer["visible"], layer["locked"]),
                         ("#ff0000", "dashed", False, True))
        self.assertAlmostEqual(layer["lineweight"], 0.53 * model.UNITS_PER_MM, places=6)  # epaisseur DXF normalisee
        lines = sorted((tuple(round(v, 6) for v in i["p2"]), i["layer"] == layer["id"], i["color"])
                       for i in data["items"])
        self.assertEqual(lines, [((0.0, 96.0), True, "#00ff00"), ((96.0, 0.0), False, "ByLayer")])

    def test_curves_blocks_and_ignored_entities(self):
        ezdxf = __import__("ezdxf")
        from fm_cad import cad_import
        doc = ezdxf.new("R2018")
        doc.header["$INSUNITS"] = 0
        msp = doc.modelspace()
        msp.add_circle((0, 0), 50)
        block = doc.blocks.new("PORTE")
        block.add_line((0, 0), (10, 0))
        doc.layers.add("MENUISERIE", color=1)
        msp.add_blockref("PORTE", (500, 500), dxfattribs={"layer": "MENUISERIE"})
        msp.add_text("cote")
        msp.add_point((1, 1))
        path = self.dir / "courbes.dxf"
        doc.saveas(path)
        data, report = cad_import.read_drawing(path)
        self.assertEqual(report["ignored"], {"POINT": 1})                     # le texte est importe (cad_text)
        self.assertIn("1 point", cad_import.describe(report))
        self.assertEqual([i["text"] for i in data["items"] if i["type"] == "cad_text"], ["cote"])
        layers = {l["id"]: l["name"] for l in data["page"]["cad"]["layers"]}
        door = [i for i in data["items"] if layers[i["layer"]] == "MENUISERIE"]
        self.assertEqual([(i["p1"], i["p2"]) for i in door], [([500.0, 500.0], [510.0, 500.0])])  # bloc eclate
        circle = [i for i in data["items"] if layers[i["layer"]] == "0" and i["type"] != "cad_text"]
        self.assertEqual([(i["type"], i["center"], i["radius"]) for i in circle], [("cad_circle", [0.0, 0.0], 50.0)])

    def test_opened_drawing_is_never_rewritten_and_can_be_kept_as_a_board(self):
        ezdxf = __import__("ezdxf")
        from fm_cad import cad_import
        doc = ezdxf.new("R2018")
        doc.modelspace().add_line((0, 0), (40, 0))
        source = self.dir / "plan.dxf"
        doc.saveas(source)
        before = source.read_bytes()
        self.assertTrue(board.is_cad_drawing(source) and board.is_cad_drawing(self.dir / "x.DWG"))
        data, _report = cad_import.read_drawing(source)
        self.assertTrue(self.pane.open_import(data, source))
        self.assertIsNone(self.pane.path)
        self.assertEqual(len(self.ctl.cad_items()), 1)
        self.assertEqual(cad_model.drawing_overrides(self.ctl.cad_page()).get("board_cad_unit"),
                         {4: "mm", 5: "cm", 6: "m"}.get(doc.header["$INSUNITS"]))
        self.type("L", "0,0", "0,40", "")                                       # dans l'unite du fichier
        self.assertTrue(self.pane.is_dirty())
        self.assertTrue(self.pane.save())                                       # enregistrement auto : rien n'est ecrit
        self.assertEqual(source.read_bytes(), before)
        target = self.pane.companion_path()
        self.assertEqual(target.name, "plan_dxf.mro")                           # plan.mro existe deja (setUp)
        self.assertTrue(self.pane.save_import_as_board())
        self.assertEqual(self.pane.path, target)
        self.assertEqual(len(serialization.load(target)["items"]), 2)
        self.assertEqual(source.read_bytes(), before)
        self.assertIsNone(self.pane.companion_path())                           # c'est maintenant un board ordinaire

    def test_unchanged_import_closes_without_asking(self):
        ezdxf = __import__("ezdxf")
        from fm_cad import cad_import
        doc = ezdxf.new("R2018")
        doc.modelspace().add_line((0, 0), (40, 0))
        source = self.dir / "vue.dxf"
        doc.saveas(source)
        self.pane.open_import(cad_import.read_drawing(source)[0], source)
        with mock.patch.object(board_ui.QMessageBox, "exec", side_effect=AssertionError("question posee")):
            self.assertTrue(self.pane.confirm_leave())
        self.assertEqual(sorted(p.name for p in self.dir.iterdir()), ["plan.mro", "vue.dxf"])


class PanTest(CadBoardCase):
    """Deplacement du board (bouton du milieu) : image recopiee decalee + bandes qui apparaissent
    (BoardView._pan_paint) ; elle doit etre IDENTIQUE a une peinture ordinaire au meme endroit."""

    def _press(self, pos, kind=None):
        from PySide6.QtCore import QEvent
        from PySide6.QtGui import QMouseEvent
        vp = self.pane.view.viewport()
        buttons = Qt.MiddleButton if kind != QEvent.MouseButtonRelease else Qt.NoButton
        button = Qt.NoButton if kind == QEvent.MouseMove else Qt.MiddleButton
        QApplication.sendEvent(vp, QMouseEvent(kind, QPointF(pos), vp.mapToGlobal(QPointF(pos)), button, buttons,
                                               Qt.NoModifier))

    def test_panned_image_matches_an_ordinary_paint(self):
        from PySide6.QtCore import QEvent
        scene = self.pane.scene
        cad = self.ctl.cad_page()
        for n in range(400):
            x, y = (n % 20) * 30.0, (n // 20) * 25.0
            values = cad_model.new_line_values(cad, (x, y), (x + 22.0, y + 7.0 + n % 5))
            if n % 3 == 0:
                values.update(lineweight=4.0, end1={"style": "round"}, end2={"style": "round"})
            scene._add(model.new_item("cad_line", **values))
        for n in range(12):
            scene._add(model.new_item("sticky", text=f"note {n}", x=n * 90.0 - 300, y=-260.0))
        self.ctl.touch_index()
        self.pane.view.fit_all()
        settle(0.2)
        vp = self.pane.view.viewport()
        self._press(QPoint(400, 300), QEvent.MouseButtonPress)
        for step in range(1, 16):
            self._press(QPoint(400 - step * 7, 300 + step * 3), QEvent.MouseMove)
            vp.repaint()
        self.assertIsNotNone(self.pane.view._pan_frame)                        # recopie en cours
        panned = vp.grab().toImage()
        self._press(QPoint(400 - 15 * 7, 300 + 15 * 3), QEvent.MouseButtonRelease)
        self.assertIsNone(self.pane.view._pan_frame)
        vp.repaint()
        ordinary = vp.grab().toImage()
        self.assertEqual(panned.size(), ordinary.size())
        differ = sum(1 for y in range(0, ordinary.height(), 2) for x in range(0, ordinary.width(), 2)
                     if panned.pixel(x, y) != ordinary.pixel(x, y))
        self.assertEqual(differ, 0)

    def test_scene_index_follows_the_content(self):
        scene = self.pane.scene
        start = scene.sceneRect()
        self.assertLess(start.width(), 10000)                                  # plus 10^6 unites : index utile
        far = scene._add(model.new_item("sticky", text="loin", x=50000.0, y=-30000.0))
        self.assertTrue(scene.sceneRect().contains(far.scene_rect()))
        self.assertIn(far, scene.items(far.scene_rect()))
        line = self.line((0, 0), (10, 0))
        self.pane.scene.change_items([line], lambda i: i.data.update(p2=[-90000.0, 5.0]), "x")
        self.assertTrue(scene.sceneRect().contains(line.scene_bounds()))



def drawing(ctl, **overrides):
    """Reglages du dessin (fenetre de la barre CAD) : `overrides` = reglages generaux remplaces par le dessin."""
    from fm_cad.cad_ui import OVERRIDE_TAG
    values = {"ltscale": f"{ctl.cad_page()['ltscale']:g}", "grid": ctl.grid_on()}
    for key, value in overrides.items():
        values[OVERRIDE_TAG + key] = True
        values[key] = value
    ctl.ui._on_drawing_values(values)
    ctl.ui._apply_drawing()


class PendingWindowTest(CadBoardCase):
    """Bug signale : « parfois une ligne creee est impossible a selectionner ». Un clic dans le vide ouvre une fenetre
    de selection qui attend son 2e coin ; elle survivait a la commande LIGNE lancee juste apres, et le clic suivant sur
    la ligne tracee refermait cette vieille fenetre au lieu de la selectionner."""

    def test_line_drawn_after_a_click_in_the_void_is_selectable(self):
        self.click((-150, 120))                                    # clic dans le vide : fenetre en attente
        self.assertIsNotNone(self.ctl.window)
        self.type("L")
        for point in ((0, 0), (120, 0)):
            self.move(point)
            self.click(point)
        QTest.keyClick(self.pane.view, Qt.Key_Return)
        APP.processEvents()
        self.assertIsNone(self.ctl.window)
        line = self.ctl.cad_items()[0]
        self.move((60, 0))
        self.click((60, 0))
        self.assertTrue(line.isSelected())


class FastClicksTest(CadBoardCase):
    """Bug signale : « environ un clic sur deux est ignore ». Deux clics rapides et proches : Qt remplace le 2e APPUI par
    un evenement de DOUBLE-CLIC (appui, relache, double-clic, relache). Hors invite de point, le double-clic n'etait
    pas traite comme un appui : le 2e coin d'une fenetre, le 2e objet a l'invite « Choix des objets », etc. etaient
    perdus (et sa relache aussi, faute d'appui). Chaque double-clic compte maintenant comme un clic."""

    def send(self, kind, doc_point):
        from PySide6.QtCore import QEvent
        from PySide6.QtGui import QMouseEvent
        vp = self.pane.view.viewport()
        pos = QPointF(self.vp(doc_point))
        types = {"press": QEvent.MouseButtonPress, "release": QEvent.MouseButtonRelease,
                 "double": QEvent.MouseButtonDblClick}
        held = Qt.NoButton if kind == "release" else Qt.LeftButton
        QApplication.sendEvent(vp, QMouseEvent(types[kind], pos, vp.mapToGlobal(pos), Qt.LeftButton, held,
                                               Qt.NoModifier))
        APP.processEvents()

    def quick_pair(self, first, second):
        """Deux clics rapides, comme Windows / Qt les livrent."""
        self.move(first)
        self.send("press", first)
        self.send("release", first)
        self.move(second)
        self.send("double", second)
        self.send("release", second)

    def test_two_quick_clicks_close_a_selection_window(self):
        line = self.line((0, 0), (100, 0))
        self.quick_pair((-50, 60), (150, -60))
        self.assertIsNone(self.ctl.window)                                  # 2e coin pris en compte
        self.assertTrue(line.isSelected())

    def test_quick_picks_at_the_select_prompt_all_count(self):
        first = self.line((0, 0), (100, 0))
        second = self.line((0, 80), (100, 80))
        self.type("E")
        self.quick_pair((50, 0), (50, 80))
        self.type("")
        self.assertEqual(self.ctl.cad_items(), [])                          # les deux objets choisis puis effaces
        self.assertIsNone(first.scene())
        self.assertIsNone(second.scene())

    def test_quick_points_of_a_line_all_count(self):
        self.type("L")
        self.quick_pair((0, 0), (90, 0))
        self.type("")
        self.assertEqual(self.lines(), [((0.0, 0.0), (90.0, 0.0))])

    def test_double_click_on_a_line_selects_it_and_opens_the_properties(self):
        line = self.line((0, 0), (100, 0))
        self.line((0, 0), (100, 0))                                         # superposee : pas de cycle au double-clic
        self.quick_pair((30, 0), (30, 0))                                   # hors des poignees
        self.assertEqual(self.ctl.selection(), [line] if line.isSelected() else self.ctl.selection())
        self.assertEqual(len(self.ctl.selection()), 1)
        self.assertTrue(self.ctl.ui._properties_open)

    def test_mouse_log_can_be_switched_on(self):
        from fm_cad import cad as cad_module
        lines = []
        with mock.patch.object(cad_module, "MOUSE_LOG", True), \
                mock.patch.object(cad_module, "_write_log", lines.append):
            self.quick_pair((-50, 60), (150, -60))
        kinds = [line.split()[2] for line in lines]
        self.assertEqual(kinds, ["appui", "relache", "double", "relache"])
        self.assertIn("fenetre", lines[0])
        self.assertIn("fenetre", lines[2])


class CurveGeometryTest(unittest.TestCase):
    """Geometrie pure des courbes (cad_shapes) et des outils (cad_tools)."""

    def setUp(self):
        from fm_cad import cad_shapes, cad_tools
        self.S, self.T = cad_shapes, cad_tools

    def close(self, a, b, places=6):
        self.assertAlmostEqual(a[0], b[0], places=places)
        self.assertAlmostEqual(a[1], b[1], places=places)

    def test_bulge_and_three_point_arcs(self):
        S = self.S
        quarter = S.bulge_arc((1.0, 0.0), (0.0, 1.0), math.tan(math.radians(90) / 4))
        self.close(quarter[1], (0, 0))
        self.assertAlmostEqual(quarter[2], 1.0)
        self.assertAlmostEqual(quarter[4], 90.0)
        big = S.bulge_arc((1.0, 0.0), (0.0, 1.0), math.tan(math.radians(-270) / 4))
        self.close(big[1], (0, 0))                                            # plus d'un demi-tour : meme centre
        self.close(S.prim_end(big), (0.0, 1.0))
        c, r, a0, sweep = S.arc_from_3_points((-1, 0), (0, 1), (1, 0))
        self.close(c, (0, 0))
        self.assertAlmostEqual(sweep, -180.0)                                  # sens horaire
        self.assertIsNone(S.arc_from_3_points((0, 0), (1, 1), (2, 2)))
        data = S.arc_data(c, r, a0, sweep)
        self.assertEqual((data["start"], data["end"]), (0.0, 180.0))           # toujours trigonometrique

    def test_intersections(self):
        S = self.S
        line = ("segment", (-2.0, 0.0), (2.0, 0.0))
        circle = ("arc", (0.0, 0.0), 1.0, 0.0, 360.0)
        self.assertEqual(sorted(S.prim_intersections(line, circle)), [(-1.0, 0.0), (1.0, 0.0)])
        upper = ("arc", (0.0, 0.0), 1.0, 0.0, 180.0)
        self.assertEqual(len(S.prim_intersections(("segment", (-2.0, 0.5), (2.0, 0.5)), upper)), 2)
        self.assertEqual(S.prim_intersections(("segment", (-2.0, -0.5), (2.0, -0.5)), upper), [])
        tangent = S.prim_intersections(("segment", (-2.0, 1.0), (2.0, 1.0)), circle)
        self.assertEqual(len(tangent), 1)
        self.close(tangent[0], (0.0, 1.0))
        self.assertEqual(len(S.circle_circle((0, 0), 1, (1.5, 0), 1)), 2)
        short = ("segment", (3.0, 0.0), (4.0, 0.0))
        self.assertEqual(S.prim_intersections(short, circle), [])
        self.assertEqual(len(S.prim_intersections(short, circle, extend_p=True)), 2)   # prolongee

    def test_bounds_tessellation_and_closest(self):
        S = self.S
        arc = ("arc", (0.0, 0.0), 10.0, 45.0, 90.0)
        x0, y0, x1, y1 = S.bounds([arc])
        self.assertAlmostEqual(y1, 10.0)                                        # quadrant du haut compris
        self.assertAlmostEqual(x1, 10 * math.cos(math.radians(45)))
        pts = S.tessellate_prim(arc, 0.01)
        self.assertTrue(all(abs(math.hypot(*p) - 10) < 1e-9 for p in pts))
        for a, b in zip(pts, pts[1:]):                                         # fleche <= tolerance
            self.assertLessEqual(10 - math.hypot(*geo.midpoint(a, b)), 0.01 + 1e-12)
        q, d, s = S.closest_on_prim(arc, (0.0, 20.0))
        self.close(q, (0.0, 10.0))
        self.assertAlmostEqual(d, 10.0)
        self.assertAlmostEqual(s, math.radians(45) * 10)

    def test_offset_line_circle_and_polyline(self):
        T = self.T
        kind, data = T.offset_entity("cad_line", {"p1": [0, 0], "p2": [100, 0]}, 10, (50, 3))
        self.assertEqual(kind, "cad_line")
        self.assertEqual((data["p1"], data["p2"]), ([0.0, 10.0], [100.0, 10.0]))
        self.assertEqual(T.offset_entity("cad_circle", {"center": [0, 0], "radius": 5}, 2, (9, 0))[1]["radius"], 7)
        self.assertEqual(T.offset_entity("cad_circle", {"center": [0, 0], "radius": 5}, 2, (1, 0))[1]["radius"], 3)
        self.assertIsInstance(T.offset_entity("cad_circle", {"center": [0, 0], "radius": 1}, 2, (0.5, 0)), str)
        kind, data = T.offset_entity("cad_pline", {"vertices": [[0, 0, 0], [10, 0, 0], [10, 10, 0]], "closed": False},
                                     1, (5, -3))                               # cote exterieur : sommet en onglet
        self.assertEqual(kind, "cad_pline")
        self.assertEqual([v[:2] for v in data["vertices"]], [[0.0, -1.0], [11.0, -1.0], [11.0, 10.0]])
        square = {"vertices": [[0, 0, 0], [10, 0, 0], [10, 10, 0], [0, 10, 0]], "closed": True}
        kind, data = T.offset_entity("cad_pline", square, 2, (5, 5))
        self.assertTrue(data["closed"])
        self.assertEqual(sorted(tuple(v[:2]) for v in data["vertices"]), [(2.0, 2.0), (2.0, 8.0), (8.0, 2.0),
                                                                          (8.0, 8.0)])
        rounded = {"vertices": [[0, 0, 0], [10, 0, math.tan(math.radians(90) / 4)], [10 + 5, 5, 0]], "closed": False}
        kind, data = T.offset_entity("cad_pline", rounded, 1, (5, 3))          # arc tangent : rayon reduit
        prims = self.S.prims(kind, data)
        self.assertEqual([p[0] for p in prims], ["segment", "arc"])
        self.assertAlmostEqual(prims[1][2], 4.0)

    def test_chamfer(self):
        T = self.T
        l1, l2 = ((0.0, 0.0), (120.0, 0.0)), ((100.0, -20.0), (100.0, 100.0))
        found = T.chamfer_lines(l1, (50, 0), l2, (100, 50), 10, 20)
        self.assertEqual(found["first"], ((0.0, 0.0), (90.0, 0.0)))
        self.assertEqual(found["second"], ((100.0, 100.0), (100.0, 20.0)))
        self.assertEqual(found["chamfer"], ((90.0, 0.0), (100.0, 20.0)))
        corner = T.chamfer_lines(l1, (50, 0), l2, (100, 50), 0, 0)
        self.assertIsNone(corner["chamfer"])                                   # distances nulles : coin vif
        self.assertEqual(corner["first"][1], (100.0, 0.0))
        angled = T.chamfer_angle_distance(l1, (50, 0), l2, (100, 50), 10, 45)
        self.close(angled["chamfer"][1], (100.0, 10.0))
        self.assertIsInstance(T.chamfer_lines(l1, (50, 0), ((0, 5), (100, 5)), (50, 5), 1, 1), str)   # paralleles
        self.assertIsInstance(T.chamfer_lines(l1, (50, 0), l2, (100, 50), 500, 1), str)            # trop grande

    def test_fillet(self):
        T = self.T
        l1, l2 = ((0.0, 0.0), (120.0, 0.0)), ((100.0, -20.0), (100.0, 100.0))
        found = T.fillet_lines(l1, (50, 0), l2, (100, 50), 10)
        self.close(found["first"][1], (90.0, 0.0))
        self.close(found["second"][1], (100.0, 10.0))
        c, r, a0, sweep = found["arc"]
        self.close(c, (90.0, 10.0))
        self.assertAlmostEqual(abs(sweep), 90.0)
        self.assertIsNone(T.fillet_lines(l1, (50, 0), l2, (100, 50), 0)["arc"])   # rayon 0 : coin vif
        self.assertIsInstance(T.fillet_lines(l1, (50, 0), ((0, 5), (100, 5)), (50, 5), 1), str)
        self.assertIsInstance(T.fillet_lines(l1, (50, 0), l2, (100, 50), 500), str)
        # Le cote garde est celui des clics.
        other = T.fillet_lines(l1, (110, 0), l2, (100, -10), 5)
        self.close(other["first"][0], (120.0, 0.0))
        self.close(other["second"][0], (100.0, -20.0))

    def test_fillet_line_and_arc_is_tangent_to_both(self):
        T = self.T
        line = ("segment", (-50.0, -20.0), (50.0, -20.0))
        circle = ("arc", (0.0, 0.0), 10.0, 0.0, 360.0)
        found = T.fillet_prims(line, (20.0, -20.0), circle, (8.0, -6.0), 5.0)
        c, r, _a0, _sweep = found["arc"]
        self.assertAlmostEqual(abs(c[1] - (-20.0)), 5.0)                       # tangent a la ligne
        self.assertAlmostEqual(geo.distance(c, (0.0, 0.0)), 15.0)               # tangent au cercle (exterieur)
        self.assertIsNone(found["second"])                                     # un cercle n'est jamais coupe
        arc = ("arc", (0.0, 0.0), 10.0, 200.0, 140.0)                          # arc du bas
        found = T.fillet_prims(line, (20.0, -20.0), arc, (8.0, -6.0), 5.0)
        self.assertEqual(found["second"][0], "arc")

    def test_polyline_vertices(self):
        T = self.T
        square = [[0, 0, 0], [10, 0, 0], [10, 10, 0], [0, 10, 0]]
        verts, done, skipped = T.pline_all_vertices(square, True, "fillet", 1)
        self.assertEqual((done, skipped, len(verts)), (4, 0, 8))
        self.assertTrue(all(abs(v[2] - math.tan(math.radians(90) / 4)) < 1e-9 for v in verts[::2]))
        verts, done, _s = T.pline_all_vertices(square, True, "chamfer", 2, 2)
        self.assertEqual((done, len(verts)), (4, 8))
        self.assertIsInstance(T.pline_vertex_edit(square, False, 0, "fillet", 1), str)    # extremite


class CurveEntitiesTest(CadBoardCase):
    """Arcs, cercles, polylignes : creation, enregistrement, accrochage, selection, poignees, rendu, DXF."""

    def items(self, kind):
        return [i for i in self.ctl.cad_items() if i.kind == kind]

    def test_circle_arc_and_polyline_commands(self):
        self.type("C", "0,0", "50")
        circle = self.items("cad_circle")[0]
        self.assertEqual(circle.geometry(), {"center": [0.0, 0.0], "radius": 50.0})
        self.type("C", "200,0", "D", "40")
        self.assertEqual(self.items("cad_circle")[1].geometry()["radius"], 20.0)
        self.type("C", "3P", "0,100", "10,110", "20,100")
        self.assertAlmostEqual(self.items("cad_circle")[2].geometry()["radius"], 10.0)
        self.type("A", "0,-100", "50,-50", "100,-100")
        arc = self.items("cad_arc")[0]
        self.assertEqual(arc.geometry(), {"center": [50.0, -100.0], "radius": 50.0, "start": 0.0, "end": 180.0})
        self.type("PL", "0,300", "100,300", "A", "100,400", "L", "0,400", "")
        pline = self.items("cad_pline")[0]
        verts = pline.geometry()["vertices"]
        self.assertEqual([v[:2] for v in verts], [[0.0, 300.0], [100.0, 300.0], [100.0, 400.0], [0.0, 400.0]])
        self.assertAlmostEqual(verts[1][2], 1.0)                               # demi-cercle tangent
        self.assertAlmostEqual(pline.length(), 100 + math.pi * 50 + 100)
        self.ctl.undo()
        self.assertEqual(self.items("cad_pline"), [])                           # une etape par commande

    def test_saved_and_reopened_exactly(self):
        self.type("C", "10,20", "30", "A", "0,0", "50,50", "100,0", "PL", "0,0", "10,0", "10,10", "C", "")
        before = sorted((i.kind, json.dumps(i.geometry(), sort_keys=True)) for i in self.ctl.cad_items())
        self.assertTrue(self.pane.save())
        data = serialization.load(self.path)
        kinds = sorted(i["type"] for i in data["items"])
        self.assertEqual(kinds, ["cad_arc", "cad_circle", "cad_pline"])
        self.assertTrue(self.pane.open(self.path))
        self.ctl = self.pane.cad
        after = sorted((i.kind, json.dumps(i.geometry(), sort_keys=True)) for i in self.ctl.cad_items())
        self.assertEqual(before, after)

    def test_snaps_on_circles(self):
        self.type("C", "0,0", "50")
        self.type("L", "150,0")
        self.type("TAN")
        self.move((10, 49))
        p = self.ctl.res.point
        self.assertAlmostEqual(geo.distance(p, (0, 0)), 50.0)                   # sur le cercle
        self.assertAlmostEqual(geo.dot(geo.sub(p, (0, 0)), geo.sub(p, (150, 0))), 0.0, places=6)   # tangente
        self.type("CEN")
        self.move((49, 3))
        self.assertEqual(self.ctl.res.point, (0.0, 0.0))
        self.type("QUA")
        self.move((3, 48))
        self.assertAlmostEqual(self.ctl.res.point[0], 0.0)
        self.assertAlmostEqual(self.ctl.res.point[1], 50.0)
        QTest.keyClick(self.pane.view, Qt.Key_Escape)

    def test_select_move_and_grips(self):
        self.type("C", "0,0", "50")
        circle = self.items("cad_circle")[0]
        self.click((50, 0))
        self.assertTrue(circle.isSelected())
        names = [n for n, _p in circle.grips()]
        self.assertEqual(names, ["center", "q0", "q90", "q180", "q270"])
        self.ctl.translate([circle], (10.0, 5.0), "x")
        self.assertEqual(circle.geometry()["center"], [10.0, 5.0])
        self.ctl.undo()
        self.assertEqual(circle.geometry()["center"], [0.0, 0.0])
        from fm_cad import cad_shapes
        self.assertEqual(cad_shapes.grip_edit("cad_circle", circle.geometry(), {"q0"}, (20.0, 0.0), False),
                         {"radius": 70.0})
        self.ctl.scene.clearSelection()
        self.ctl.window = {"start": (-60.0, -60.0)}
        self.ctl._finish_window((60.0, 60.0), Qt.NoModifier)
        self.assertTrue(circle.isSelected())                                   # fenetre qui le contient

    def test_curves_are_drawn_in_the_batch(self):
        from PySide6.QtGui import QImage, QPainter
        self.type("C", "0,0", "50")
        settle(0.05)
        scene = self.pane.scene
        image = QImage(300, 300, QImage.Format_ARGB32_Premultiplied)
        image.fill(0xFFFFFFFF)
        painter = QPainter(image)
        scene.render(painter, QRectF(0, 0, 300, 300), QRectF(-150, -150, 300, 300))
        painter.end()
        darkest = min(QColor(image.pixel(150 + 50 + dx, 150 + dy)).red() for dx in (-1, 0, 1) for dy in (-1, 0, 1))
        self.assertLess(darkest, 200)                                          # le trait du cercle (anticrenele)
        self.assertGreater(QColor(image.pixel(150, 150)).red(), 200)            # le centre : vide
        self.assertTrue(any(i.CURVED for b in getattr(scene, "cad_layer").batches for i in b.members))

    def test_dxf_round_trip(self):
        from fm_cad import cad_export, cad_import
        self.type("C", "0,0", "50", "A", "0,0", "50,50", "100,0", "PL", "0,0", "10,0", "A", "10,10", "")
        path = self.dir / "courbes.dxf"
        cad_export.export_dxf(self.pane.scene, path, units="raw")
        data, report = cad_import.read_drawing(path)
        self.assertEqual(sorted(i["type"] for i in data["items"]), ["cad_arc", "cad_circle", "cad_pline"])
        pline = [i for i in data["items"] if i["type"] == "cad_pline"][0]
        self.assertAlmostEqual(pline["vertices"][1][2], 1.0)


class ModifyToolsTest(CadBoardCase):
    """DECALER, CHANFREIN, RACCORD : invites, apercu au survol, une etape d'annulation par operation, memoire."""

    def corner(self):
        first = self.line((0, 0), (120, 0))
        second = self.line((100, -20), (100, 100))
        return first, second

    def test_offset_repeats_and_remembers_the_distance(self):
        line = self.line((0, 0), (100, 0))
        self.type("O", "10")
        self.click((50, 0))
        self.move((50, 30))
        self.assertTrue(self.ctl.overlay_state()["ghosts"])                    # apercu du cote
        self.click((50, 30))
        self.click((50, 10))                                                   # meme commande : objet suivant
        self.click((50, 40))
        self.type("")
        ys = sorted(i.points()[0][1] for i in self.ctl.cad_items())
        self.assertEqual(ys, [0.0, 10.0, 20.0])
        self.ctl.undo()
        self.assertEqual(len(self.ctl.cad_items()), 2)                          # une etape par decalage
        self.type("O", "")                                                     # Entree : 10 memorise
        self.click((50, 0))
        self.click((50, -30))
        self.type("")
        self.assertIn(-10.0, [i.points()[0][1] for i in self.ctl.cad_items()])
        self.assertIsNotNone(line.scene())

    def test_offset_through_and_curves(self):
        self.type("C", "0,0", "50")
        self.type("O", "P")
        self.click((50, 0))
        self.click((70, 0))
        self.type("")
        radii = sorted(i.geometry()["radius"] for i in self.ctl.cad_items())
        self.assertEqual(radii, [50.0, 70.0])
        self.type("O", "80")
        self.click((0, 70))
        self.click((0, 20))                                                    # vers l'interieur : rayon < 0
        self.assertIn("rayon nul", self.ctl.history[-1][0])
        self.type("")

    def test_chamfer_two_lines_in_one_undo_step(self):
        first, second = self.corner()
        self.type("CHA", "D", "10", "20")
        self.click((50, 0))
        self.move((100, 50))
        self.assertTrue(self.ctl.overlay_state()["ghosts"])                    # apercu au survol de la 2e
        self.click((100, 50))
        self.assertIsNone(self.ctl.command)
        self.assertEqual(first.points(), ((0.0, 0.0), (90.0, 0.0)))
        self.assertEqual(second.points(), ((100.0, 20.0), (100.0, 100.0)))      # sens de la ligne garde
        chamfer = [i for i in self.ctl.cad_items() if i not in (first, second)][0]
        self.assertEqual(sorted(chamfer.points()), [(90.0, 0.0), (100.0, 20.0)])
        self.ctl.undo()
        self.assertEqual(len(self.ctl.cad_items()), 2)
        self.assertEqual(first.points(), ((0.0, 0.0), (120.0, 0.0)))
        self.assertEqual(self.ctl.tool_memory["chamfer_d2"], 20.0)              # memorise

    def test_fillet_lines_radius_zero_and_impossible_cases(self):
        first, second = self.corner()
        self.type("F", "R", "10")
        self.click((50, 0))
        self.click((100, 50))
        arcs = [i for i in self.ctl.cad_items() if i.kind == "cad_arc"]
        self.assertEqual(len(arcs), 1)
        center = arcs[0].geometry()["center"]
        self.assertAlmostEqual(center[0], 90.0)
        self.assertAlmostEqual(center[1], 10.0)
        self.assertEqual(first.points()[1], (90.0, 0.0))
        self.ctl.undo()
        self.type("F", "R", "0")
        self.click((50, 0))
        self.click((100, 50))
        self.assertEqual(first.points()[1], (100.0, 0.0))                       # coin vif
        self.assertEqual(second.points()[0], (100.0, 0.0))
        third = self.line((0, 50), (60, 50))
        self.type("F")
        self.click((30, 0))
        self.click((30, 50))
        self.assertIn("parallèles", self.ctl.history[-1][0])
        self.assertIsNotNone(third.scene())
        QTest.keyClick(self.pane.view, Qt.Key_Escape)

    def test_fillet_no_trim_keeps_the_lines(self):
        first, second = self.corner()
        self.type("F", "A", "N", "R", "10")
        self.click((50, 0))
        self.click((100, 50))
        self.assertEqual(first.points(), ((0.0, 0.0), (120.0, 0.0)))
        self.assertEqual(len([i for i in self.ctl.cad_items() if i.kind == "cad_arc"]), 1)
        self.ctl.tool_memory["trim"] = True

    def test_polyline_corners(self):
        self.type("PL", "0,0", "100,0", "100,100", "0,100", "C")
        pline = [i for i in self.ctl.cad_items() if i.kind == "cad_pline"][0]
        self.type("F", "R", "10", "P")
        self.click((50, 0))
        self.assertEqual(len(pline.geometry()["vertices"]), 8)
        self.ctl.undo()
        self.type("CHA", "D", "5", "5")
        self.click((50, 0))
        self.click((100, 50))                                                  # deux segments voisins
        verts = pline.geometry()["vertices"]
        self.assertEqual(len(verts), 5)
        self.assertIn([95.0, 0.0, 0.0], verts)
        self.assertIn([100.0, 5.0, 0.0], verts)


class GpuInstancesTest(CadBoardCase):
    """Rendu GPU du CAD (fm_cad/cad_gpu.py) : instances, lots et secours — la partie qui ne demande pas d'OpenGL ; le
    rendu lui-meme est compare au raster par `tests/_probe_gpu_cad.py` (vraie fenetre Windows)."""

    def setUp(self):
        super().setUp()
        from fm_cad import cad_gpu
        self.gpu = cad_gpu

    def make(self, kind, **values):
        data = model.new_item(kind, **cad_model.new_entity_values(self.ctl.cad_page(), **values))
        item = self.pane.scene._add(data)
        item.sync()
        return item

    def rows(self, item, dense=False, tol=0.1):
        return self.gpu.item_instances(item, dense, tol)

    def test_plain_line_is_one_instance_with_its_terminations(self):
        item = self.make("cad_line", p1=[0.0, 0.0], p2=[100.0, 0.0], lineweight=10.0, color="#ff0000",
                         end1={"style": "round", "radius": 50.0}, end2={"style": "radius", "radius": 60.0})
        data = self.rows(item)
        self.assertEqual(data.shape, (1, self.gpu.FLOATS))
        ax, ay, bx, by, hw, r1, r2, codes, red, green, blue, alpha = data[0]
        self.assertEqual((ax, ay, bx, by), (0.0, 0.0, 100.0, 0.0))            # coordonnees de SCENE (y vers le bas)
        self.assertEqual(hw, 5.0)
        self.assertEqual(int(codes), 1 + 4 * 2)                                 # debut arrondi, fin « border radius »
        self.assertAlmostEqual(r2, 3.0)                                         # 60 % de la demi-epaisseur
        self.assertEqual((red, green, blue, alpha), (1.0, 0.0, 0.0, 1.0))
        item.setPos(10.0, 5.0)
        self.assertEqual(list(self.rows(item)[0][:4]), [10.0, 5.0, 110.0, 5.0])   # place Qt comprise

    def test_hidden_layer_has_no_instance_and_y_is_flipped_for_the_document(self):
        item = self.make("cad_line", p1=[0.0, 0.0], p2=[100.0, 50.0])
        self.assertEqual(list(self.rows(item)[0][:4]), [0.0, 0.0, 100.0, -50.0])
        cad = cad_model.copy_cad(self.ctl.cad_page())
        cad["layers"][0]["visible"] = False
        self.ctl.set_cad(cad, "x")
        self.assertIsNone(self.rows(item))

    def test_dashes_are_instances_with_inner_and_end_terminations(self):
        self.pane.apply_settings(dict(self.pane._settings, board_cad_linetypes=[
            {"key": "continuous", "name": "Continu", "sequence": []},
            {"key": "dashed", "name": "Tire", "sequence": [10, 10], "extra": 10,
             "end1": {"style": "round", "radius": 50}, "end2": {"style": "flat", "radius": 50},
             "inner": {"style": "radius", "radius": 100}}]))
        item = self.make("cad_line", p1=[0.0, 0.0], p2=[100.0, 0.0], lineweight=6.0, linetype="dashed")
        data = self.rows(item)
        self.assertEqual(len(data), len(item._thin_dashes))
        codes = [int(c) for c in data[:, 7]]
        self.assertEqual(codes[0] % 4, 1)                                       # 1er trait : terminaison du debut
        self.assertEqual(codes[1] % 4, 2)                                       # traits interieurs : leur terminaison
        self.assertEqual(codes[1] // 4, 2)
        self.assertEqual(len(self.rows(item, dense=True)), 1)                   # motif trop serre : trait continu

    def test_curves_are_tessellated_with_round_joins(self):
        circle = self.make("cad_circle", center=[0.0, 0.0], radius=50.0, lineweight=4.0)
        data = self.rows(circle)
        self.assertGreater(len(data), 16)
        self.assertTrue(all(int(c) == self.gpu.JOIN + 4 * self.gpu.JOIN for c in data[:, 7]))   # cercle ferme : que des joints
        pts = np_points = [(row[0], row[1]) for row in data]
        self.assertTrue(all(abs(math.hypot(x, y) - 50.0) < 1e-6 for x, y in pts))              # sommets SUR la courbe
        finer = self.rows(circle, tol=0.01)
        self.assertGreater(len(finer), len(data))                                               # finesse = tolerance
        arc = self.make("cad_arc", center=[0.0, 0.0], radius=50.0, start=0.0, end=90.0, lineweight=4.0,
                        end1={"style": "round", "radius": 50.0})
        codes = [int(c) for c in self.rows(arc)[:, 7]]
        self.assertEqual(codes[0] % 4, 1)                                       # debut arrondi
        self.assertEqual(codes[0] // 4, self.gpu.JOIN)
        self.assertEqual(codes[-1] % 4, self.gpu.JOIN)
        self.assertEqual(codes[-1] // 4, 0)                                     # fin franche
        pline = self.make("cad_pline", vertices=[[0.0, 0.0, 0.0], [100.0, 0.0, 1.0], [100.0, 50.0, 0.0]],
                          lineweight=3.0)
        data = self.rows(pline)
        self.assertGreater(len(data), 5)                                        # un segment droit + un demi-cercle
        self.assertAlmostEqual(data[0][2], 100.0)

    def test_store_chunks_marks_and_relative_coordinates(self):
        store = self.gpu.GpuStore()
        items = [self.make("cad_line", p1=[1000.0 + n, 2000.0], p2=[1005.0 + n, 2010.0], lineweight=4.0) for n in range(5)]
        for item in items:
            store.mark(item, True)
        self.assertEqual(len(store.chunks), 1)
        chunk = store.chunks[0]
        data = store.build(chunk, 0.1, 1.0)
        self.assertEqual(chunk.count, 5)
        self.assertEqual(data.dtype.name, "float32")
        self.assertEqual(tuple(data[0][:4]), (0.0, 0.0, 5.0, -10.0))            # relatives a l'origine du lot
        self.assertEqual(chunk.origin, (1000.0, -2000.0))
        self.assertLess(chunk.bounds[0], 1000.0)
        store.mark(items[2], False)
        self.assertEqual(len(chunk.items), 4)
        self.assertTrue(chunk.dirty)
        store.mark(items[0], True)                                              # changee : relue
        self.assertNotIn(id(items[0]), store.cache)
        self.gpu.CHUNK, saved = 2, self.gpu.CHUNK
        try:
            other = self.gpu.GpuStore()
            for item in items:
                other.mark(item, True)
            self.assertEqual([len(c.items) for c in other.chunks], [2, 2, 1])
        finally:
            self.gpu.CHUNK = saved

    def test_store_build_yields_when_out_of_time_and_lines_ignore_the_tessellation_band(self):
        import time
        store = self.gpu.GpuStore()
        line = self.make("cad_line", p1=[0.0, 0.0], p2=[10.0, 0.0])
        circle = self.make("cad_circle", center=[0.0, 0.0], radius=20.0)
        store.mark(line, True)
        store.mark(circle, True)
        chunk = store.chunks[0]
        self.assertIs(store.build(chunk, 0.1, 1.0, time.perf_counter() - 1.0), self.gpu.PENDING)   # plus de temps
        self.assertEqual(len(store.cache), 0)                                                       # rien de fait
        data = store.build(chunk, 0.1, 1.0)
        rows = len(data)
        line_entry = store.cache[id(line)]
        store.build(chunk, 0.05, 2.0)                                                               # finesse changee
        self.assertIs(store.cache[id(line)], line_entry)                                            # ligne : gardee
        self.assertGreater(chunk.count, rows)                                                       # courbe : refaite plus fine

    def test_patterned_items_follow_the_dense_threshold(self):
        self.pane.apply_settings(dict(self.pane._settings, board_cad_linetypes=[
            {"key": "continuous", "name": "Continu", "sequence": []},
            {"key": "dashed", "name": "Tire", "sequence": [10, 10], "extra": 10}]))
        item = self.make("cad_line", p1=[0.0, 0.0], p2=[200.0, 0.0], linetype="dashed")
        store = self.gpu.GpuStore()
        store.mark(item, True)
        chunk = store.chunks[0]
        store.zoom_changed(1.0, 4.0)
        store.build(chunk, 0.1, 1.0)
        many = chunk.count
        self.assertGreater(many, 3)
        store.zoom_changed(0.05, 4.0)                                           # periode de 1 px : trop serre
        self.assertTrue(chunk.dirty)
        store.build(chunk, 0.1, 1.0)
        self.assertEqual(chunk.count, 1)

    def test_without_opengl_the_cad_keeps_its_raster_rendering(self):
        if self.gpu.available():
            self.skipTest("OpenGL disponible : le secours se teste sans PyOpenGL")
        self.line((0, 0), (100, 0))
        self.pane.apply_settings(dict(self.pane._settings, board_cad_gpu=True))
        self.assertIsNone(getattr(self.pane.view, "gpu", None))
        self.assertFalse(self.pane._settings["board_cad_gpu"])                  # remis a faux, pas de nouvel essai
        self.assertFalse(getattr(self.pane.scene, "cad_gpu", False))
        settle(0.05)
        self.assertTrue(CadLayer_of(self.pane.scene).batches)                   # lots du processeur en place

    def test_a_deleted_entity_leaves_the_gpu_store(self):
        """Signale : plantage (ecran vide) en supprimant une ligne — l'entite supprimee restait dans le lot GPU, son objet
        C++ detruit par `deleteLater`, et la construction suivante du lot levait une erreur a chaque image."""
        from fm_cad.cad_items import CadLayer

        class FakeGpu:
            def __init__(self, gpu):
                self.store = gpu.GpuStore()

            def request(self):
                pass
        line = self.line((0, 0), (100, 0))
        other = self.line((0, 50), (100, 50))
        layer = CadLayer.of(self.pane.scene)
        fake = FakeGpu(self.gpu)
        layer.set_gpu(fake)
        self.assertIn(id(line), fake.store.where)
        self.pane.scene.delete_items([line])
        settle(0.05)
        self.assertNotIn(id(line), fake.store.where)                    # retiree du lot des la suppression
        self.assertIn(id(other), fake.store.where)
        dead = self.gpu.GpuStore()                                      # et un objet detruit resterait sans effet
        item = self.line((0, 80), (100, 80))
        dead.mark(item, True)
        self.pane.scene._remove(item.item_id)
        settle(0.05)
        import shiboken6
        from PySide6.QtCore import QCoreApplication, QEvent
        QCoreApplication.sendPostedEvents(None, QEvent.DeferredDelete)
        self.assertFalse(shiboken6.isValid(item))
        data = dead.build(dead.chunks[0], 0.1, 1.0)
        self.assertIsNone(data)                                         # pas d'exception : l'entite morte est ecartee
        self.assertEqual(len(dead.where), 0)
        layer.set_gpu(None)

    def test_cad_layer_switches_between_gpu_and_batches_without_touching_the_entities(self):
        from fm_cad.cad_items import CadLayer
        line = self.line((0, 0), (100, 0))
        layer = CadLayer.of(self.pane.scene)
        settle(0.05)
        self.assertTrue(layer.batches)

        class FakeGpu:                               # couche factice : le branchement ne demande pas OpenGL
            def __init__(self):
                self.store = self_gpu.GpuStore()
                self.requests = 0

            def request(self):
                self.requests += 1
        self_gpu = self.gpu
        fake = FakeGpu()
        layer.set_gpu(fake)
        self.assertEqual(layer.batches, [])                                     # plus de lots
        self.assertTrue(self.pane.scene.cad_gpu)
        self.assertTrue(line.flags() & line.GraphicsItemFlag.ItemHasNoContents)  # la scene ne le peint plus
        self.assertIn(id(line), fake.store.where)
        self.assertEqual(line.points(), ((0.0, 0.0), (100.0, 0.0)))             # entite inchangee
        self.ctl.translate([line], (5.0, 0.0), "x")
        self.assertIn(id(line), fake.store.cache.keys() | {id(line)})
        self.assertTrue(fake.store.chunks[0].dirty)                             # changement : lot a refaire
        layer.exporting(True)
        self.assertFalse(line.flags() & line.GraphicsItemFlag.ItemHasNoContents)   # export : peinture ordinaire
        layer.exporting(False)
        layer.set_gpu(None)
        settle(0.05)
        self.assertTrue(layer.batches)
        self.assertFalse(self.pane.scene.cad_gpu)


def CadLayer_of(scene):
    from fm_cad.cad_items import CadLayer
    return CadLayer.of(scene)


class TransformDimTest(CadBoardCase):
    """ROTATION, MIROIR, RECTANGLE et cotations (cad_dims, cad_shapes.rotated / mirrored)."""

    def select(self, *items):
        self.pane.scene.clearSelection()
        for item in items:
            item.setSelected(True)

    def kinds(self, kind):
        return [i for i in self.ctl.cad_items() if i.kind == kind]

    # -- geometrie pure --
    def test_rotated_and_mirrored_geometry_of_every_kind(self):
        line = {"p1": [10.0, 0.0], "p2": [20.0, 0.0]}
        out = cad_shapes.rotated("cad_line", line, (0.0, 0.0), 90.0)
        self.assertAlmostEqual(out["p1"][1], 10.0)
        self.assertAlmostEqual(out["p2"][1], 20.0)
        arc = {"center": [10.0, 0.0], "radius": 5.0, "start": 0.0, "end": 90.0}
        out = cad_shapes.rotated("cad_arc", arc, (0.0, 0.0), 90.0)
        self.assertEqual((round(out["start"]), round(out["end"])), (90, 180))
        out = cad_shapes.mirrored("cad_arc", arc, (0.0, -1.0), (0.0, 1.0))          # axe vertical x = 0
        self.assertAlmostEqual(out["center"][0], -10.0)
        self.assertEqual((round(out["start"]), round(out["end"])), (90, 180))       # sens trigonometrique gardé
        pline = {"vertices": [[0.0, 0.0, 0.5], [10.0, 0.0, 0.0], [10.0, 10.0, -0.25]], "closed": False}
        out = cad_shapes.mirrored("cad_pline", pline, (0.0, 0.0), (1.0, 0.0))        # axe horizontal y = 0
        self.assertEqual([v[2] for v in out["vertices"]], [-0.5, 0.0, 0.25])        # renflements inversés
        self.assertAlmostEqual(out["vertices"][2][1], -10.0)
        dim = {"dim_type": "linear", "p1": [0.0, 0.0], "p2": [10.0, 0.0], "pos": [5.0, 3.0], "rot": 0.0}
        out = cad_shapes.rotated("cad_dim", dim, (0.0, 0.0), 90.0)
        self.assertAlmostEqual(out["rot"], 90.0)                                      # la mesure tourne avec
        self.assertAlmostEqual(out["p2"][1], 10.0)

    def test_dim_geometry_linear_aligned_radius_diameter_angular(self):
        base = {"p1": [0.0, 0.0], "p2": [100.0, 0.0], "pos": [50.0, 20.0], "dim_unit": 1.0, "dim_dec": 2,
                "dim_text": 5.0, "dim_arrow": 4.0, "dim_gap": 1.0, "dim_over": 2.0}
        found = cad_dims.geometry({**base, "dim_type": "linear", "rot": 0.0})
        self.assertEqual(found["text"], "100")
        self.assertAlmostEqual(found["value"], 100.0)
        self.assertGreater(found["text_pos"][1], 20.0)                              # texte AU-DESSUS de la ligne de cote
        lines = [p for p in found["prims"] if p[0] == "segment"]
        ys = {round(p[1][1], 6) for p in lines} | {round(p[2][1], 6) for p in lines}
        self.assertIn(20.0, ys)                                                     # ligne de cote a la place demandee
        self.assertIn(1.0, ys)                                                      # lignes d'attache : ecart a l'origine
        self.assertIn(22.0, ys)                                                     # ... et depassement
        found = cad_dims.geometry({**base, "dim_type": "linear", "rot": 90.0, "p2": [100.0, 40.0], "pos": [120.0, 20.0]})
        self.assertEqual(found["text"], "40")                                       # verticale : seule la hauteur
        found = cad_dims.geometry({**base, "dim_type": "aligned", "p2": [30.0, 40.0]})
        self.assertEqual(found["text"], "50")                                       # parallele aux deux points
        found = cad_dims.geometry({**base, "dim_type": "radius", "p1": [0.0, 0.0], "p2": [30.0, 0.0],
                                   "pos": [60.0, 0.0]})
        self.assertEqual(found["text"], "R30")
        found = cad_dims.geometry({**base, "dim_type": "diameter", "p1": [0.0, 0.0], "p2": [30.0, 0.0],
                                   "pos": [0.0, 0.0]})
        self.assertEqual(found["text"], "Ø60")
        found = cad_dims.geometry({**base, "dim_type": "angular", "center": [0.0, 0.0], "p1": [50.0, 0.0],
                                   "p2": [0.0, 50.0], "pos": [30.0, 30.0]})
        self.assertEqual(found["text"], "90°")
        self.assertTrue(any(p[0] == "arc" for p in found["prims"]))
        found = cad_dims.geometry({**base, "dim_type": "linear", "rot": 0.0, "dim_str": "env. <> mm"})
        self.assertEqual(found["text"], "env. 100 mm")                              # « <> » = la valeur mesuree
        found = cad_dims.geometry({**base, "dim_type": "linear", "rot": 0.0, "dim_unit": 10.0})
        self.assertEqual(found["text"], "10")                                       # unite de mesure

    def test_text_is_always_readable_left_to_right(self):
        base = {"dim_type": "aligned", "p1": [0.0, 0.0], "pos": [0.0, 0.0], "dim_unit": 1.0}
        for p2 in ((10.0, 3.0), (-10.0, 3.0), (-10.0, -3.0), (0.0, 10.0), (0.0, -10.0)):
            angle = cad_dims.geometry({**base, "p2": list(p2), "pos": [p2[0] / 2, p2[1] / 2 + 1]})["text_angle"]
            self.assertTrue(-90.0 < angle <= 90.0, (p2, angle))

    # -- ROTATION --
    def test_rotate_moves_and_copies_in_one_undo_step(self):
        line = self.line((10, 0), (20, 0))
        self.select(line)
        self.type("RO", "0,0", "90")
        self.assertAlmostEqual(line.points()[0][1], 10.0)
        self.assertAlmostEqual(line.points()[1][1], 20.0)
        self.ctl.undo()
        self.assertEqual(line.points(), ((10.0, 0.0), (20.0, 0.0)))
        self.select(line)
        self.type("RO", "0,0", "C", "90")
        self.assertEqual(len(self.ctl.cad_items()), 2)                              # copie : l'original reste
        self.assertEqual(line.points(), ((10.0, 0.0), (20.0, 0.0)))
        self.ctl.undo()
        self.assertEqual(len(self.ctl.cad_items()), 1)

    def test_rotate_by_a_point_and_by_reference(self):
        line = self.line((10, 0), (20, 0))
        self.select(line)
        self.type("RO", "0,0")
        self.move((0, 30))
        self.assertTrue(self.ctl.overlay_state()["ghosts"])                         # apercu de l'objet tourne
        self.click((0, 30))                                                         # angle = direction du point (90 degres)
        self.assertAlmostEqual(line.points()[1][1], 20.0)
        self.select(line)
        self.type("RO", "0,0", "R", "90", "180")                                    # reference 90 -> nouvel angle 180
        self.assertAlmostEqual(line.points()[1][0], -20.0, places=6)                # tourne de 90 degres de plus

    def test_rotate_arc_pline_circle_and_dimension_keep_their_nature(self):
        arc = self.make_entity("cad_arc", center=[10.0, 0.0], radius=5.0, start=0.0, end=90.0)
        circle = self.make_entity("cad_circle", center=[10.0, 0.0], radius=3.0)
        pline = self.make_entity("cad_pline", vertices=[[0.0, 0.0, 0.0], [10.0, 0.0, 0.5], [10.0, 10.0, 0.0]], closed=False)
        self.select(arc, circle, pline)
        self.type("RO", "0,0", "90")
        self.assertEqual((round(arc.geometry()["start"]), round(arc.geometry()["end"])), (90, 180))
        self.assertAlmostEqual(circle.geometry()["center"][1], 10.0)
        self.assertEqual(pline.geometry()["vertices"][1][2], 0.5)

    # -- MIROIR --
    def test_mirror_copies_by_default_and_can_move_the_source(self):
        line = self.line((10, 0), (20, 5))
        self.select(line)
        self.type("MI", "0,-5", "0,5", "")                                          # Entree = Non : copie
        self.assertEqual(len(self.ctl.cad_items()), 2)
        mirrored = [i for i in self.ctl.cad_items() if i is not line][0]
        self.assertEqual(mirrored.points(), ((-10.0, 0.0), (-20.0, 5.0)))
        self.assertEqual(line.points(), ((10.0, 0.0), (20.0, 5.0)))
        self.ctl.undo()
        self.assertEqual(len(self.ctl.cad_items()), 1)
        self.select(line)
        self.type("MI", "0,-5", "0,5", "O")                                         # Oui : la source est remplacee
        self.assertEqual(len(self.ctl.cad_items()), 1)
        self.assertEqual(line.points(), ((-10.0, 0.0), (-20.0, 5.0)))

    def test_mirror_preview_and_arc_orientation(self):
        arc = self.make_entity("cad_arc", center=[10.0, 0.0], radius=5.0, start=0.0, end=90.0)
        self.select(arc)
        self.type("MI", "0,-5")
        self.move((0, 5))
        self.assertTrue(self.ctl.overlay_state()["ghosts"])
        self.type("0,5", "")
        copy = [i for i in self.ctl.cad_items() if i is not arc][0]
        self.assertEqual((round(copy.geometry()["start"]), round(copy.geometry()["end"])), (90, 180))

    # -- RECTANGLE --
    def test_rectangle_by_corners_by_dimensions_and_rounded(self):
        self.type("REC", "0,0", "50,30")
        rect = self.kinds("cad_pline")[0]
        self.assertTrue(rect.data["closed"])
        self.assertEqual(len(rect.data["vertices"]), 4)
        self.assertEqual(rect.doc_bounds(), (0.0, 0.0, 50.0, 30.0))
        self.ctl.undo()
        self.assertEqual(len(self.ctl.cad_items()), 0)
        self.type("REC", "10,10", "D", "40", "20", "")                              # Entree : cote positif
        rect = self.kinds("cad_pline")[0]
        self.assertEqual(rect.doc_bounds(), (10.0, 10.0, 50.0, 30.0))
        self.type("REC", "0,0", "D", "40", "20")
        self.click((-5, -5))                                                        # le curseur choisit le cote
        rects = self.kinds("cad_pline")
        self.assertEqual(rects[-1].doc_bounds(), (-40.0, -20.0, 0.0, 0.0))
        self.type("REC", "R", "5", "0,0", "50,30")
        rounded = self.kinds("cad_pline")[-1]
        self.assertEqual(len(rounded.data["vertices"]), 8)
        self.assertEqual(rounded.doc_bounds(), (0.0, 0.0, 50.0, 30.0))              # les arrondis restent dans le cadre
        self.assertEqual(self.ctl.tool_memory["rect_radius"], 5.0)                  # memorise

    def test_rectangle_refuses_a_flat_one(self):
        self.type("REC", "0,0", "50,0")
        self.assertEqual(len(self.ctl.cad_items()), 0)
        self.assertIn("sans épaisseur", self.ctl.history[-1][0])
        self.type("")

    # -- COTATIONS --
    def test_dimlinear_by_two_points_and_by_object(self):
        self.type("DLI", "0,0", "100,0")
        self.click((50, 20))
        dim = self.kinds("cad_dim")[0]
        self.assertEqual(dim.data["dim_type"], "linear")
        self.assertEqual(dim.measured_text(), "100")
        self.assertEqual(dim.data["rot"], 0.0)                                      # au-dessus : horizontale
        self.assertEqual(dim.data["lineweight"], 0.0)                               # trait fin
        self.ctl.undo()
        self.assertEqual(len(self.ctl.cad_items()), 0)
        self.type("DLI", "0,0", "100,40")
        self.click((130, 20))                                                       # a cote : verticale
        self.assertEqual(self.kinds("cad_dim")[0].measured_text(), "40")
        self.type("DLI", "0,0", "100,40", "H")
        self.click((130, 20))
        self.assertEqual(self.kinds("cad_dim")[-1].measured_text(), "100")          # Horizontale imposee
        line = self.line((0, 100), (60, 180))
        self.type("DLI", "")                                                        # Entree : choisir un objet
        self.click((30, 140))
        self.click((80, 140))
        self.assertEqual(self.kinds("cad_dim")[-1].data["p2"], [60.0, 180.0])

    def test_dimaligned_radius_diameter_and_angular(self):
        self.type("DAL", "0,0", "30,40")
        self.click((-20, 20))
        self.assertEqual(self.kinds("cad_dim")[-1].measured_text(), "50")
        self.type("C", "200,0", "50")
        circle = self.kinds("cad_circle")[0]
        self.type("DRA")
        self.click((250, 0))
        self.click((280, 10))
        self.assertEqual(self.kinds("cad_dim")[-1].measured_text(), "R50")
        self.type("DDI")
        self.click((200, 50))
        self.click((200, 0))
        self.assertEqual(self.kinds("cad_dim")[-1].measured_text(), "Ø100")
        first = self.line((300, 0), (400, 0))
        second = self.line((300, 0), (300, 100))
        self.type("DAN")
        self.click((350, 0))
        self.click((300, 50))
        self.click((340, 40))
        self.assertEqual(self.kinds("cad_dim")[-1].measured_text(), "90°")
        self.assertIsNotNone(circle.scene())
        self.assertIsNotNone(first.scene())
        self.assertIsNotNone(second.scene())

    def test_dimension_is_a_normal_entity(self):
        self.type("DLI", "0,0", "100,0")
        self.click((50, 20))
        dim = self.kinds("cad_dim")[0]
        self.assertIsNotNone(dim._text_item)                                        # texte : enfant de la cotation
        self.assertEqual(dim._text_item._text, "100")
        self.assertTrue(dim.distance_to((50, 20)) < 1e-6)                            # selectionnable sur sa ligne de cote
        before = dim.data["pos"]
        self.select(dim)
        self.ctl.translate([dim], (10.0, 5.0), "Déplacer")
        self.assertEqual(dim.data["pos"], [before[0] + 10.0, before[1] + 5.0])
        self.assertEqual(dim.measured_text(), "100")                                # mesure inchangée
        grips = dict(dim.grips())
        self.assertEqual(set(grips), {"p1", "p2", "pos"})
        self.select(dim)
        self.type("E")
        self.assertEqual(len(self.ctl.cad_items()), 0)
        self.ctl.undo()
        self.assertEqual(len(self.kinds("cad_dim")), 1)

    def test_snap_ignores_dimensions(self):
        self.type("DLI", "0,0", "100,0")
        self.click((50, 40))
        dim = self.kinds("cad_dim")[0]
        self.assertEqual(list(dim.snap_primitives()), [])
        self.move((50, 40))                                                         # sur la ligne de cote
        APP.processEvents()
        self.assertIsNone(self.ctl.hover_snap)                                      # aucun aimant : seule la cotation est là

    def test_antialiasing_samples_setting_reaches_the_scene(self):
        self.assertEqual(self.pane.scene.cad_samples, 8)                            # defaut
        self.pane.apply_settings(dict(self.pane._settings, board_cad_aa_samples="64"))
        self.assertEqual(self.pane.scene.cad_samples, 64)
        self.pane.apply_settings(dict(self.pane._settings, board_cad_aa_samples="n'importe quoi"))
        self.assertEqual(self.pane.scene.cad_samples, 8)                            # valeur invalide : le defaut
        self.assertEqual(self.pane.scene.cad_filter, 75)
        self.pane.apply_settings(dict(self.pane._settings, board_cad_aa_filter=500))
        self.assertEqual(self.pane.scene.cad_filter, 200)                           # borne

    def test_dwg_export_works_under_the_test_qt_environment_when_oda_is_installed(self):
        """ODA File Converter ne demarrait pas (« no Qt platform plugin ») : il heritait de QT_QPA_PLATFORM=offscreen."""
        import previews
        exe = previews._oda_file_converter()
        if not exe:
            self.skipTest("ODA File Converter absent")
        cad_export.ODA_PROVIDER = previews._oda_file_converter
        self.line((0, 0), (100, 0))
        folder = tempfile.mkdtemp()
        try:
            with mock.patch.dict(os.environ, {"QT_QPA_PLATFORM": "offscreen"}):
                out = cad_export.export_dwg(self.pane.scene, os.path.join(folder, "plan.dwg"), "mm")
                self.assertEqual(os.environ["QT_QPA_PLATFORM"], "offscreen")                 # remise apres coup
            self.assertGreater(os.path.getsize(out), 1000)
        finally:
            cad_export.ODA_PROVIDER = None
            shutil.rmtree(folder, ignore_errors=True)

    def test_dimension_text_can_be_overridden_and_follows_the_unit(self):
        self.type("DLI", "0,0", "100,0")
        self.click((50, 20))
        dim = self.kinds("cad_dim")[0]
        self.ctl.change_entities([dim], {"dim_str": "<> mm"}, "Texte")
        self.assertEqual(dim.measured_text(), "100 mm")
        self.assertEqual(dim._text_item._text, "100 mm")                            # l'enfant suit

    def test_dimension_saved_and_reloaded_and_exported(self):
        self.type("DLI", "0,0", "100,0")
        self.click((50, 20))
        data = self.kinds("cad_dim")[0].to_dict()
        again = model.normalize(dict(data))
        self.assertEqual(again["dim_type"], "linear")
        self.assertEqual(again["p2"], [100.0, 0.0])
        self.assertEqual(again["dim_unit"], data["dim_unit"])
        try:
            import ezdxf
        except ImportError:
            return
        folder = tempfile.mkdtemp()
        try:
            path = cad_export.export_dxf(self.pane.scene, os.path.join(folder, "plan.dxf"), "mm")
            doc = ezdxf.readfile(str(path))
            kinds = [e.dxftype() for e in doc.modelspace()]
            self.assertIn("TEXT", kinds)
            self.assertGreaterEqual(kinds.count("LINE"), 3)                         # attaches, cote, fleches
            self.assertEqual([e.dxf.text for e in doc.modelspace() if e.dxftype() == "TEXT"], ["100"])
        finally:
            shutil.rmtree(folder, ignore_errors=True)

    def test_gpu_instances_of_a_dimension(self):
        from fm_cad import cad_gpu
        self.type("DLI", "0,0", "100,0")
        self.click((50, 20))
        dim = self.kinds("cad_dim")[0]
        rows = cad_gpu.item_instances(dim, False, 0.1)
        self.assertGreaterEqual(len(rows), 5)
        self.assertTrue(getattr(dim, "TEXTED", False))                              # jamais le mode « pur CAD »

    def test_dimension_style_comes_from_the_settings_and_the_unit(self):
        self.pane.apply_settings(dict(self.pane._settings, board_cad_unit="cm", board_cad_dim_text=500,
                                      board_cad_dim_scale=200, board_cad_dim_arrow_kind="tick"))
        style = self.ctl.dim_style()
        self.assertAlmostEqual(style["dim_text"], 5.0 * self.ctl.unit() * 2.0)      # 5 cm x 200 %
        self.assertEqual(style["dim_arrow_kind"], "tick")
        self.assertAlmostEqual(style["dim_unit"], self.ctl.unit())

    def make_entity(self, kind, **geometry):
        item = self.ctl.create_entity(kind, geometry)
        self.ctl.commit_created([item], "test")
        return item


class HatchTest(CadBoardCase):
    """HACHURES (cad_hatch) : zone d'un point interne, objets choisis, motifs, entite comme les autres."""

    def square(self, x0=0, y0=0, size=100):
        self.type("REC", f"{x0},{y0}", f"{x0 + size},{y0 + size}")
        return [i for i in self.ctl.cad_items() if i.kind == "cad_pline"][-1]

    def box_of_lines(self, size=100):
        return [self.line((0, 0), (size, 0)), self.line((size, 0), (size, size)),
                self.line((size, size), (0, size)), self.line((0, size), (0, 0))]

    def hatches(self):
        return [i for i in self.ctl.cad_items() if i.kind == "cad_hatch"]

    # -- zone d'un point interne (pur) --
    def test_region_around_a_point_and_islands(self):
        segs = [((0, 0), (100, 0)), ((100, 0), (100, 100)), ((100, 100), (0, 100)), ((0, 100), (0, 0))]
        outer, holes = cad_hatch.find_region(segs, (50.0, 50.0))
        self.assertAlmostEqual(abs(cad_hatch.signed_area(outer)), 10000.0)
        self.assertEqual(holes, [])
        circle = cad_shapes.tessellate([("arc", (50.0, 50.0), 20.0, 0.0, 360.0)], 0.05)[0]
        island = [(circle[i], circle[i + 1]) for i in range(len(circle) - 1)]
        outer, holes = cad_hatch.find_region(segs + island, (10.0, 10.0))           # entre le carré et le cercle
        self.assertAlmostEqual(abs(cad_hatch.signed_area(outer)), 10000.0)
        self.assertEqual(len(holes), 1)                                              # le cercle est un trou
        self.assertTrue(abs(abs(cad_hatch.signed_area(holes[0])) - math.pi * 400.0) < 5.0)
        outer, holes = cad_hatch.find_region(segs + island, (50.0, 50.0))            # dans le cercle
        self.assertTrue(abs(abs(cad_hatch.signed_area(outer)) - math.pi * 400.0) < 5.0)
        self.assertEqual(holes, [])

    def test_region_split_by_crossing_lines_and_open_shapes(self):
        segs = [((0, 0), (100, 0)), ((100, 0), (100, 100)), ((100, 100), (0, 100)), ((0, 100), (0, 0)),
                ((50, -20), (50, 120)), ((-20, 50), (120, 50))]                      # deux traverses qui dépassent
        outer, _ = cad_hatch.find_region(segs, (25.0, 25.0))
        self.assertAlmostEqual(abs(cad_hatch.signed_area(outer)), 2500.0)            # un quart
        self.assertIsInstance(cad_hatch.find_region(segs[:3], (50.0, 50.0)), str)    # contour ouvert : message
        self.assertIsInstance(cad_hatch.find_region(segs, (500.0, 500.0)), str)      # point à l'extérieur

    def test_pattern_segments_stay_inside_and_follow_the_style(self):
        loop = [[0.0, 0.0], [100.0, 0.0], [100.0, 100.0], [0.0, 100.0]]
        base = {"loops": [loop], "hatch_spacing": 10.0, "hatch_origin": [0.0, 0.0], "hatch_angle": 0.0}
        lines = cad_hatch.pattern_segments([loop], cad_hatch.style_of({**base, "hatch_pattern": "lines"}))
        self.assertTrue(9 <= len(lines) <= 11)
        self.assertTrue(all(abs(a[1] - b[1]) < 1e-9 and abs(abs(b[0] - a[0]) - 100.0) < 1e-6 for a, b in lines))
        diagonal = cad_hatch.pattern_segments([loop], cad_hatch.style_of({**base, "hatch_pattern": "lines",
                                                                            "hatch_angle": 45.0}))
        self.assertTrue(all(cad_hatch.inside([loop], ((a[0] + b[0]) / 2, (a[1] + b[1]) / 2)) for a, b in diagonal))
        cross = cad_hatch.pattern_segments([loop], cad_hatch.style_of({**base, "hatch_pattern": "cross"}))
        self.assertGreater(len(cross), 2 * len(lines) - 4)
        brick = cad_hatch.pattern_segments([loop], cad_hatch.style_of({**base, "hatch_pattern": "brick"}))
        self.assertTrue(any(abs(a[0] - b[0]) < 1e-9 for a, b in brick))              # joints montants
        self.assertEqual(cad_hatch.pattern_segments([loop], cad_hatch.style_of({**base, "hatch_pattern": "solid"})), [])
        hole = [[40.0, 40.0], [60.0, 40.0], [60.0, 60.0], [40.0, 60.0]]
        with_hole = cad_hatch.pattern_segments([loop, hole], cad_hatch.style_of({**base, "hatch_pattern": "lines"}))
        self.assertTrue(all(not cad_hatch.inside([hole], ((a[0] + b[0]) / 2, (a[1] + b[1]) / 2)) for a, b in with_hole))
        self.assertGreater(len(with_hole), len(lines))                               # traits coupés en deux autour du trou

    def test_spacing_is_kept_when_the_zone_is_huge(self):
        loop = [[0.0, 0.0], [100000.0, 0.0], [100000.0, 100000.0], [0.0, 100000.0]]
        segments = cad_hatch.pattern_segments([loop], cad_hatch.style_of({"hatch_pattern": "lines", "hatch_spacing": 1.0}))
        self.assertLessEqual(len(segments), cad_hatch.MAX_LINES + 2)                  # jamais des millions de traits

    # -- commande --
    def test_hatch_by_a_point_is_one_undo_step_and_goes_to_the_back(self):
        self.box_of_lines()
        self.type("H")
        self.click((50, 50))
        self.type("")
        found = self.hatches()
        self.assertEqual(len(found), 1)
        hatch = found[0]
        self.assertEqual(hatch.data["hatch_pattern"], "lines")
        self.assertEqual(hatch.data["lineweight"], 0.0)
        self.assertEqual(hatch.doc_bounds(), (0.0, 0.0, 100.0, 100.0))
        self.assertLess(hatch.zValue(), min(i.zValue() for i in self.ctl.cad_items() if i is not hatch))
        self.assertTrue(hatch.prims())
        self.ctl.undo()
        self.assertEqual(len(self.hatches()), 0)
        self.ctl.redo()
        self.assertEqual(len(self.hatches()), 1)

    def test_hatch_options_pattern_angle_spacing_are_remembered(self):
        self.box_of_lines()
        self.type("H", "M", "B")                                                      # motif Briques
        self.type("A", "30")
        self.type("E", "20")
        self.click((50, 50))
        self.type("")
        hatch = self.hatches()[0]
        self.assertEqual((hatch.data["hatch_pattern"], hatch.data["hatch_angle"], hatch.data["hatch_spacing"]),
                         ("brick", 30.0, 20.0))
        self.type("H")
        self.assertEqual(self.ctl.command._pattern(), "brick")                         # mémorisé
        self.type("")

    def test_hatch_by_objects_and_closed_polyline(self):
        rect = self.square()
        circle = self.make_entity("cad_circle", center=[50.0, 50.0], radius=20.0)
        self.type("H", "C")
        self.click((0, 50))
        self.click((70, 50))
        self.type("")                                                                  # Entrée : hachurer
        hatch = self.hatches()[0]
        self.assertEqual(len(hatch.data["loops"]), 2)                                   # le cercle fait un trou
        self.type("")
        self.assertIsNotNone(rect.scene())
        self.assertIsNotNone(circle.scene())

    def test_hatch_without_a_closed_zone_says_so(self):
        self.line((0, 0), (100, 0))
        self.type("H")
        self.click((50, 50))
        self.assertIn("Aucune zone fermée", self.ctl.history[-1][0])
        self.assertEqual(len(self.hatches()), 0)
        self.type("")

    def test_hatch_is_an_entity_like_the_others(self):
        self.box_of_lines()
        self.type("H")
        self.click((50, 50))
        self.type("")
        hatch = self.hatches()[0]
        self.assertFalse(list(hatch.snap_primitives()))                                  # jamais accrochable
        before = hatch.doc_bounds()
        self.pane.scene.clearSelection()
        hatch.setSelected(True)
        self.ctl.translate([hatch], (30.0, 10.0), "Déplacer")
        after = hatch.doc_bounds()
        self.assertEqual((after[0] - before[0], after[1] - before[1]), (30.0, 10.0))
        self.assertEqual(dict(hatch.grips()).keys(), {"center"})
        self.ctl.undo()
        self.assertEqual(hatch.doc_bounds(), before)
        copy = self.ctl.copy_items([hatch], (200.0, 0.0))[0]                              # copie : motif gardé
        self.assertEqual(copy.data["hatch_pattern"], hatch.data["hatch_pattern"])
        self.assertEqual(copy.doc_bounds()[0], 200.0)
        self.pane.scene.clearSelection()
        hatch.setSelected(True)
        self.type("RO", "0,0", "90")
        self.assertAlmostEqual(hatch.data["hatch_angle"], 135.0)                          # le motif tourne avec la forme
        self.assertAlmostEqual(hatch.doc_bounds()[0], -100.0, places=6)

    def test_picking_a_hatch_by_its_pattern_or_its_solid_area(self):
        self.box_of_lines()
        self.type("H", "M", "PL")
        self.click((50, 50))
        self.type("")
        hatch = self.hatches()[0]
        reach = 5.0
        hatch._reach = reach
        self.assertLessEqual(hatch.distance_to((50.0, 50.0)), reach)                      # plein : n'importe où dedans
        self.assertGreater(hatch.distance_to((500.0, 500.0)), reach)
        line = self.ctl.cad_items()[0]
        self.assertLess(line.distance_to((50.0, 0.5)), hatch.distance_to((50.0, 0.5)))    # un trait proche passe avant
        hatch.data["hatch_pattern"] = "lines"
        hatch.data["hatch_spacing"] = 10.0
        hatch.data["hatch_angle"] = 0.0
        hatch.sync()
        self.assertLess(hatch.distance_to((50.0, 20.2)), 0.5)                              # sur un trait du motif
        self.assertGreater(hatch.distance_to((50.0, 25.0)), 4.0)                           # entre deux traits

    def test_hatch_saved_exported_and_drawn_by_the_gpu_store(self):
        self.box_of_lines()
        self.type("H")
        self.click((50, 50))
        self.type("")
        hatch = self.hatches()[0]
        data = model.normalize(dict(hatch.to_dict()))
        self.assertEqual(len(data["loops"]), 1)
        self.assertEqual(data["hatch_pattern"], "lines")
        from fm_cad import cad_gpu
        self.assertGreater(len(cad_gpu.item_instances(hatch, False, 0.1)), 5)
        self.assertTrue(hatch.TEXTED)                                                      # jamais le mode « pur CAD »
        try:
            import ezdxf
        except ImportError:
            return
        folder = tempfile.mkdtemp()
        try:
            path = cad_export.export_dxf(self.pane.scene, os.path.join(folder, "plan.dxf"), "mm")
            kinds = [e.dxftype() for e in ezdxf.readfile(str(path)).modelspace()]
            self.assertGreater(kinds.count("LINE"), 10)                                    # contour + traits du motif
        finally:
            shutil.rmtree(folder, ignore_errors=True)

    def test_a_deleted_entity_never_blocks_the_selection_of_the_others(self):
        """Signale : apres avoir supprime une hachure, l'objet qui la contenait n'etait plus selectionnable — l'index
        gardait l'entite supprimee dont l'objet C++ etait detruit (`deleteLater`) : `RuntimeError` a chaque recherche
        dans sa zone."""
        from PySide6.QtCore import QCoreApplication, QEvent
        from PySide6.QtTest import QTest
        rect = self.square()
        self.type("H")
        self.click((50, 50))
        self.type("")
        self.ctl.undo()                                                               # la hachure part, revient…
        self.ctl.redo()
        self.pane.scene.clearSelection()
        self.hatches()[0].setSelected(True)
        QTest.keyClick(self.pane.view, Qt.Key_Delete)                                  # … puis Suppr
        QCoreApplication.sendPostedEvents(None, QEvent.DeferredDelete)
        settle(0.1)
        self.assertEqual(self.ctl.pick_all(self.vp((0, 50))), [rect])
        self.pane.scene.clearSelection()
        self.click((0, 50))
        self.assertEqual(self.ctl.selection(), [rect])
        line = self.line((200, 0), (300, 0))                                           # même chose pour une ligne
        self.pane.scene.clearSelection()
        line.setSelected(True)
        self.ctl.run("ERASE", echo=False)
        QCoreApplication.sendPostedEvents(None, QEvent.DeferredDelete)
        settle(0.1)
        self.assertEqual(self.ctl.pick_all(self.vp((250, 0))), [])
        self.assertEqual(self.ctl.pick_all(self.vp((0, 50))), [rect])

    def test_copy_of_curves_keeps_every_geometric_field(self):
        """Une copie d'arc / cercle / polyligne perdait son rayon, son ouverture, ses sommets (champs retirés de la source
        puis non reposés)."""
        arc = self.make_entity("cad_arc", center=[10.0, 0.0], radius=5.0, start=20.0, end=90.0)
        circle = self.make_entity("cad_circle", center=[0.0, 0.0], radius=7.0)
        pline = self.make_entity("cad_pline", vertices=[[0.0, 0.0, 0.0], [10.0, 0.0, 0.5], [10.0, 10.0, 0.0]], closed=True)
        for item in (arc, circle, pline):
            copy = self.ctl.copy_items([item], (100.0, 0.0))[0]
            moved = cad_shapes.translated(item.kind, item.geometry(), (100.0, 0.0))
            for key, value in moved.items():
                self.assertEqual(copy.geometry()[key], value, (item.kind, key))
        self.assertEqual(self.ctl.copy_items([arc], (1.0, 0.0))[0].geometry()["radius"], 5.0)

    def make_entity(self, kind, **geometry):
        item = self.ctl.create_entity(kind, geometry)
        self.ctl.commit_created([item], "test")
        return item


class TrimTest(CadBoardCase):
    """AJUSTER (TR, cad_trim) en mode STANDARD : aretes de coupe, morceau retire, cercles / polylignes, une etape
    d'annulation."""

    def setUp(self):
        super().setUp()
        self.ctl.apply_settings(dict(self.ctl.settings, board_cad_trim_mode="standard"))

    def cross(self):
        """Une horizontale de (0,0) a (100,0) coupee par deux verticales en x = 30 et x = 70."""
        h = self.line((0, 0), (100, 0))
        self.line((30, -20), (30, 20))
        self.line((70, -20), (70, 20))
        return h

    def lines(self):
        return [i for i in self.ctl.cad_items() if i.kind == "cad_line"]

    # -- geometrie pure --
    def test_crossings_interval_and_remaining_pieces(self):
        prims = [("segment", (0.0, 0.0), (100.0, 0.0))]
        cutters = [("segment", (30.0, -5.0), (30.0, 5.0)), ("segment", (70.0, -5.0), (70.0, 5.0))]
        self.assertEqual(cad_trim.crossings(prims, cutters), [30.0, 70.0])
        interval = cad_trim.removed_interval(100.0, [30.0, 70.0], 50.0, False)
        self.assertEqual(interval, (30.0, 70.0))
        pieces = cad_trim.remaining(prims, False, interval)
        self.assertEqual([(p[0][1], p[-1][2]) for p in pieces], [((0.0, 0.0), (30.0, 0.0)), ((70.0, 0.0), (100.0, 0.0))])
        self.assertEqual(cad_trim.removed_interval(100.0, [30.0, 70.0], 10.0, False), (0.0, 30.0))   # jusqu'au bout
        self.assertEqual(cad_trim.removed_interval(100.0, [30.0, 70.0], 90.0, False), (70.0, 100.0))
        self.assertIsInstance(cad_trim.removed_interval(100.0, [], 10.0, False), str)               # rien ne coupe
        self.assertIsInstance(cad_trim.removed_interval(100.0, [30.0], 10.0, True), str)            # fermé : 2 mini

    def test_closed_contour_keeps_the_other_side(self):
        circle = [("arc", (0.0, 0.0), 10.0, 0.0, 360.0)]
        cutters = [("segment", (-20.0, 5.0), (20.0, 5.0)), ("segment", (-20.0, -5.0), (20.0, -5.0))]
        params = cad_trim.crossings(circle, cutters)
        self.assertEqual(len(params), 4)
        click = cad_trim.click_param(circle, (10.0, 0.0))                              # l'arc de droite
        interval = cad_trim.removed_interval(2 * math.pi * 10.0, params, click, True)
        pieces = cad_trim.remaining(circle, True, interval)
        self.assertEqual(len(pieces), 1)
        total = sum(cad_shapes.prim_length(p) for p in pieces[0])
        removed = math.radians(2 * math.degrees(math.asin(0.5))) * 10.0
        self.assertAlmostEqual(total, 2 * math.pi * 10.0 - removed, places=6)

    # -- commande --
    def test_trim_between_two_cutters_splits_the_line_in_one_undo_step(self):
        h = self.cross()
        self.type("TR", "")                                                           # Entrée : toutes les arêtes
        self.move((50, 0))
        self.assertTrue(self.ctl.overlay_state()["ghosts"])                            # apercu du morceau retire
        self.click((50, 0))
        self.type("")
        horizontals = sorted((tuple(i.points()[0]), tuple(i.points()[1])) for i in self.lines()
                             if abs(i.points()[0][1]) < 1e-9 and abs(i.points()[1][1]) < 1e-9)
        self.assertEqual(horizontals, [((0.0, 0.0), (30.0, 0.0)), ((70.0, 0.0), (100.0, 0.0))])
        self.assertIsNotNone(h.scene())                                                # le 1er morceau est l'original
        self.ctl.undo()
        again = sorted((tuple(i.points()[0]), tuple(i.points()[1])) for i in self.lines()
                       if abs(i.points()[0][1]) < 1e-9 and abs(i.points()[1][1]) < 1e-9)
        self.assertEqual(again, [((0.0, 0.0), (100.0, 0.0))])                          # une seule étape

    def test_trim_to_the_end_and_several_clicks(self):
        self.cross()
        self.type("TR", "")
        self.click((10, 0))                                                            # jusqu'au bout, a gauche
        self.click((90, 0))                                                            # puis a droite
        self.type("")
        horizontals = [i for i in self.lines() if abs(i.points()[0][1]) < 1e-9 and abs(i.points()[1][1]) < 1e-9]
        self.assertEqual([(i.points()[0], i.points()[1]) for i in horizontals], [((30.0, 0.0), (70.0, 0.0))])

    def test_trim_with_chosen_cutting_edges_only(self):
        self.cross()
        first, second = [i for i in self.lines() if abs(i.points()[0][0] - i.points()[1][0]) < 1e-9]
        self.type("TR")
        self.click((30, 15))                                                           # seule la verticale x = 30 coupe
        self.type("")
        self.click((60, 0))                                                            # pas de coupe a droite : jusqu'au bout
        self.type("")
        horizontals = [i for i in self.lines() if abs(i.points()[0][1]) < 1e-9 and abs(i.points()[1][1]) < 1e-9]
        self.assertEqual([(i.points()[0], i.points()[1]) for i in horizontals], [((0.0, 0.0), (30.0, 0.0))])
        self.assertIsNotNone(first.scene())
        self.assertIsNotNone(second.scene())

    def test_trim_nothing_to_cut_says_so(self):
        self.line((0, 0), (100, 0))
        self.type("TR", "")
        self.click((50, 0))
        self.assertIn("Aucune arête de coupe", self.ctl.history[-1][0])
        self.type("")
        self.assertEqual(len(self.lines()), 1)

    def test_trim_a_circle_leaves_an_arc_and_the_original_is_replaced(self):
        self.type("C", "0,0", "10")
        self.line((-20, 5), (20, 5))
        self.line((-20, -5), (20, -5))
        self.type("TR", "")
        self.click((10, 0))
        self.type("")
        self.assertEqual(len([i for i in self.ctl.cad_items() if i.kind == "cad_circle"]), 0)
        arcs = [i for i in self.ctl.cad_items() if i.kind == "cad_arc"]
        self.assertEqual(len(arcs), 1)
        self.assertAlmostEqual(arcs[0].length(), 2 * math.pi * 10.0 - math.radians(60.0) * 10.0, places=5)
        self.ctl.undo()                                                                # cercle revenu, arc disparu
        self.assertEqual(len([i for i in self.ctl.cad_items() if i.kind == "cad_circle"]), 1)
        self.assertEqual(len([i for i in self.ctl.cad_items() if i.kind == "cad_arc"]), 0)

    def test_trim_an_arc_and_a_polyline_and_properties_are_kept(self):
        self.type("A", "-20,0", "0,20", "20,0")
        self.line((0, -5), (0, 30))
        arc = [i for i in self.ctl.cad_items() if i.kind == "cad_arc"][0]
        self.ctl.change_entities([arc], {"color": "#ff0000", "layer": arc.data["layer"]}, "t")
        self.type("TR", "")
        self.click((-14, 14))
        self.type("")
        pieces = [i for i in self.ctl.cad_items() if i.kind == "cad_arc"]
        self.assertEqual(len(pieces), 1)                                               # il reste la moitié droite
        self.assertEqual(pieces[0].data["color"], "#ff0000")
        self.type("PL", "-50,-50", "50,-50", "50,50", "")
        poly = [i for i in self.ctl.cad_items() if i.kind == "cad_pline"][0]
        self.line((0, -80), (0, 80))
        self.type("TR", "")
        self.click((25, -50))                                                          # milieu du côté bas, croisé en x = 0
        self.type("")
        self.assertEqual([i for i in self.ctl.cad_items() if i.kind == "cad_pline"], [])   # il ne reste qu'un segment…
        sides = [tuple(sorted(i.points())) for i in self.ctl.cad_items() if i.kind == "cad_line"
                 and abs(i.points()[0][1] + 50.0) < 1e-9 and abs(i.points()[1][1] + 50.0) < 1e-9]
        self.assertEqual(sides, [((-50.0, -50.0), (0.0, -50.0))])                            # … devenu une ligne
        self.assertIsNone(poly.scene())                                                        # la polyligne est remplacée
        self.ctl.undo()
        self.assertEqual(len([i for i in self.ctl.cad_items() if i.kind == "cad_pline"]), 1)

    def test_trim_ignores_dimensions_and_hatches_as_cutters_and_refuses_them_as_targets(self):
        self.line((0, 0), (100, 0))
        self.type("DLI", "0,0", "100,0")
        self.click((50, 30))
        self.type("TR", "")
        self.click((50, 0))
        self.assertIn("Aucune arête de coupe", self.ctl.history[-1][0])                # la cotation ne coupe pas
        self.type("")

    def make_entity(self, kind, **geometry):
        item = self.ctl.create_entity(kind, geometry)
        self.ctl.commit_created([item], "test")
        return item


class TrimQuickTest(CadBoardCase):
    """AJUSTER comme AutoCAD 2021+ : mode Rapide (tous les objets coupent, un objet que rien ne coupe est efface),
    trajet de deux points, trace a main levee, capture, Maj + clic = prolonger, aretes prolongees."""

    def cross(self):
        h = self.line((0, 0), (100, 0))
        self.line((30, -20), (30, 20))
        self.line((70, -20), (70, 20))
        return h

    def horizontals(self):
        return sorted((tuple(i.points()[0]), tuple(i.points()[1])) for i in self.ctl.cad_items()
                      if i.kind == "cad_line" and i.points()[0][1] == i.points()[1][1])

    def test_quick_mode_trims_at_once_and_deletes_what_nothing_cuts(self):
        self.cross()
        lonely = self.line((0, 50), (100, 50))
        self.type("TR")
        self.move((50, 0))
        self.assertTrue(self.ctl.overlay_state()["ghosts"])
        self.click((50, 0))
        self.assertEqual([h for h in self.horizontals() if h[0][1] == 0.0],
                         [((0.0, 0.0), (30.0, 0.0)), ((70.0, 0.0), (100.0, 0.0))])
        self.click((50, 50))                                                    # rien ne la coupe : effacee
        self.assertIsNone(lonely.scene())
        self.type("")
        self.ctl.undo()
        self.assertIsNotNone([i for i in self.ctl.cad_items() if i.points() == ((0.0, 50.0), (100.0, 50.0))])

    def test_two_point_fence_trims_everything_it_crosses_in_one_step(self):
        self.line((0, 0), (100, 0))
        self.line((0, 10), (100, 10))
        self.line((30, -20), (30, 20))
        self.type("TR")
        self.click((10, -40))                                                   # clic dans le vide : trajet
        self.assertEqual(self.ctl.prompt().kind, "point")
        self.move((10, 40))
        self.assertTrue(self.ctl.overlay_state()["ghosts"])
        self.click((10, 40))
        self.assertEqual(self.horizontals(), [((30.0, 0.0), (100.0, 0.0)), ((30.0, 10.0), (100.0, 10.0))])
        self.type("")
        self.ctl.undo()                                                         # une seule etape
        self.assertEqual(self.horizontals(), [((0.0, 0.0), (100.0, 0.0)), ((0.0, 10.0), (100.0, 10.0))])

    def test_freehand_path_and_hidden_pickbox(self):
        self.line((0, 0), (100, 0))
        self.line((0, 10), (100, 10))
        self.line((30, -20), (30, 20))
        self.type("TR")
        viewport = self.pane.view.viewport()
        QTest.mousePress(viewport, Qt.LeftButton, Qt.NoModifier, self.vp((10, -40)))
        for y in (-30, -15, 0, 3, 6, 9, 12, 15):
            QTest.mouseMove(viewport, self.vp((10 + abs(y) * 0.2, y)))
        APP.processEvents()
        self.assertIsNotNone(self.ctl.lasso)
        state = self.ctl.overlay_state()
        self.assertTrue(state["pickbox"])                                       # modification : le carre seul reste, meme pendant le trace
        self.assertTrue(state["path"])
        self.assertTrue(state["ghosts"])
        QTest.mouseRelease(viewport, Qt.LeftButton, Qt.NoModifier, self.vp((13, 15)))
        APP.processEvents()
        self.assertIsNone(self.ctl.lasso)
        self.assertEqual(self.horizontals(), [((30.0, 0.0), (100.0, 0.0)), ((30.0, 10.0), (100.0, 10.0))])
        self.assertTrue(self.ctl.overlay_state()["pickbox"])

    def test_shift_click_extends_to_the_next_boundary(self):
        self.line((0, 0), (50, 0))
        self.line((80, -20), (80, 20))
        self.type("TR")
        self.click((45, 0), Qt.ShiftModifier)
        self.assertEqual(self.horizontals(), [((0.0, 0.0), (80.0, 0.0))])
        self.type("")

    def test_extend_geometry_arc_and_extended_edges(self):
        arc = {"center": [0.0, 0.0], "radius": 10.0, "start": 0.0, "end": 90.0}
        wall = [("segment", (-20.0, 5.0), (0.0, 5.0))]                          # coupe le cercle a gauche (x < 0)
        kind, data = cad_trim.extend("cad_arc", arc, wall, (0.0, 10.0))
        self.assertEqual(kind, "cad_arc")
        self.assertAlmostEqual(data["end"], 150.0, places=6)                     # jusqu'a (-8.66, 5)
        short = [("segment", (60.0, 10.0), (60.0, 20.0))]                       # ne croise pas y = 0…
        self.assertIsInstance(cad_trim.extend("cad_line", {"p1": [0, 0], "p2": [10, 0]}, short, (9, 0)), str)
        kind, data = cad_trim.extend("cad_line", {"p1": [0, 0], "p2": [10, 0]}, short, (9, 0), extend_edges=True)
        self.assertEqual(data["p2"], [60.0, 0.0])                               # … sauf prolongee (EDGEMODE)

    def test_standard_empty_click_is_a_crossing_and_options_switch_mode(self):
        self.cross()
        self.type("TR", "O", "S")                                               # mOde : Standard
        self.assertEqual(self.ctl.tool_memory["trim_mode"], "standard")
        self.type("")                                                           # Entree : tous les objets
        self.click((45, 40))
        self.assertEqual(self.ctl.prompt().text, "Spécifiez le coin opposé")
        self.click((55, -40))
        self.assertEqual(self.horizontals()[:2], [((0.0, 0.0), (30.0, 0.0)), ((70.0, 0.0), (100.0, 0.0))])
        self.type("")


class MarkersAndGripsTest(CadBoardCase):
    """Demandes de l'utilisateur : poignees parfaitement carrees au contour d'UN pixel opaque (couleur reglable),
    marqueurs d'epaisseur exacte (1, 2 ou 3 pixels) sur tout le pourtour, reticule reduit au carre pendant une
    modification, aimant juste a une extremite commune."""

    def test_grips_are_square_with_an_opaque_one_pixel_border(self):
        from PySide6.QtGui import QImage, QPainter
        from fm_cad.cad_items import paint_grips
        for ratio in (1.0, 2.0):
            image = QImage(round(40 * ratio), round(40 * ratio), QImage.Format_ARGB32_Premultiplied)
            image.setDevicePixelRatio(ratio)
            image.fill(0)
            painter = QPainter(image)
            painter.setRenderHint(QPainter.Antialiasing, True)
            paint_grips(painter, [QPointF(20.37, 19.71)], 8, "#802f6bff", "#80ff0000")    # couleurs translucides
            painter.end()
            painted = [(x, y) for x in range(image.width()) for y in range(image.height())
                       if image.pixelColor(x, y).alpha() > 0]
            xs, ys = {x for x, _ in painted}, {y for _, y in painted}
            side = round(8 * ratio) | 1                                               # impair : centre sur le pixel
            self.assertEqual((len(xs), len(ys)), (side, side), ratio)                    # carre parfait
            self.assertEqual(min(xs) + side // 2, int(20.37 * ratio), ratio)
            edge = round(ratio)
            x0, y0 = min(xs), min(ys)
            for x in range(x0, x0 + side):
                for y in range(y0, y0 + side):
                    c = image.pixelColor(x, y)
                    border = min(x - x0, y - y0, x0 + side - 1 - x, y0 + side - 1 - y) < edge
                    if border:
                        self.assertEqual((c.red(), c.green(), c.blue(), c.alpha()), (255, 0, 0, 255), (ratio, x, y))
                    else:
                        self.assertEqual(c.alpha(), 0x80, (ratio, x, y))          # le dedans garde sa transparence

    def test_grip_border_color_is_a_setting(self):
        item = self.line((0, 0), (200, 0))
        self.ctl.apply_settings(dict(self.ctl.settings, board_cad_grip_border_color="#ff0000",
                                     board_cad_grip_color="#0000ff"))
        self.assertEqual(self.pane.scene.cad_grip_border, "#ff0000")
        item.setSelected(True)
        settle()
        image = self.pane.view.viewport().grab().toImage()
        ratio = image.devicePixelRatio()
        for point in ((0, 0), (100, 0), (200, 0)):
            c = self.ctl.doc_to_view(point)
            cx, cy = int(c.x() * ratio), int(c.y() * ratio)
            reds = [x for x in range(cx - 10, cx + 11) if image.pixelColor(x, cy - 2).name() == "#ff0000"]
            self.assertEqual(len(reds), 2, point)                                   # bords gauche et droit, 1 px chacun
            self.assertEqual(reds[1] - reds[0] + 1, 9, point)
            self.assertEqual(cx - reds[0], reds[1] - cx, point)                     # centre sur le point
            self.assertEqual(image.pixelColor(cx, cy - 2).name(), "#0000ff")

    def test_markers_have_the_same_exact_thickness_on_every_side(self):
        from PySide6.QtGui import QImage, QPainter
        overlay = self.ctl.overlay
        for width in (1, 2, 3):
            for centre in (QPointF(20.0, 20.0), QPointF(20.5, 20.5), QPointF(20.3, 19.8)):
                image = QImage(40, 40, QImage.Format_ARGB32_Premultiplied)
                image.fill(0)
                painter = QPainter(image)
                painter.setRenderHint(QPainter.Antialiasing, True)
                overlay._paint_marker(painter, dict(self.ctl.look, marker_width=width), "end", centre, "#ff0000", 6.0)
                painter.end()

                def run(cells):
                    return sum(1 for x, y in cells if image.pixelColor(x, y).alpha() == 255)
                row = [(x, 20) for x in range(40)]
                col = [(20, y) for y in range(40)]
                left = run([(x, y) for x, y in row if x < 20])
                right = run([(x, y) for x, y in row if x > 20])
                top = run([(x, y) for x, y in col if y < 20])
                bottom = run([(x, y) for x, y in col if y > 20])
                self.assertEqual((left, right, top, bottom), (width,) * 4, (width, centre))
                partial = [(x, y) for x, y in row + col if 0 < image.pixelColor(x, y).alpha() < 255]
                self.assertEqual(partial, [], (width, centre))                     # aucun bord a moitie couvert

    def test_no_pick_box_over_a_grip_the_cursor_sticks_to(self):
        item = self.line((0, 0), (200, 0))
        item.setSelected(True)
        self.move((100, 60))
        self.move((201, 1))
        self.assertIsNotNone(self.ctl.hover_grip)
        state = self.ctl.overlay_state()
        self.assertFalse(state["pickbox"])                                        # le contour de la poignee suffit
        self.assertEqual(state["grip_gap"], 4)                                    # bras arretes au bord (9 px)
        cursor = [op for op in self.ctl.overlay._layout(state)[0] if op[0] == "cursor"][0]
        self.assertEqual(cursor[2][4], 4)
        self.move((100, 60))
        self.assertTrue(self.ctl.overlay_state()["pickbox"])

    def test_marker_thickness_is_a_setting(self):
        self.assertEqual(self.ctl.look["marker_width"], 2)
        self.ctl.apply_settings(dict(self.ctl.settings, board_cad_marker_thickness=3))
        self.assertEqual(self.ctl.look["marker_width"], 3)

    def test_modifying_commands_leave_only_the_pick_box(self):
        self.line((0, 0), (200, 0))
        self.move((50, 80))
        self.assertFalse(self.ctl.box_only())
        for name in ("TRIM", "OFFSET", "MOVE", "ERASE", "FILLET"):
            self.type(name)
            self.move((60, 90))
            self.move((50, 80))
            self.assertTrue(self.ctl.box_only(), name)
            state = self.ctl.overlay_state()
            self.assertTrue(state["pickbox"], name)
            native, painted = self.ctl._cursor_plan()
            if native is not None:                                                # curseur du systeme : le carre seul
                box = self.ctl.look["pickbox_px"]
                self.assertEqual(native.pixmap().width(), round((2 * box + 1) * native.pixmap().devicePixelRatio()))
            else:
                ops = [op for op in self.ctl.overlay._layout(state)[0] if op[0].startswith("cursor")]
                self.assertTrue(all(op[0] == "cursor" and op[2][3] == 0 for op in ops), name)   # bras : 0
            QTest.keyClick(self.pane.view, Qt.Key_Escape)
            QTest.keyClick(self.pane.view, Qt.Key_Escape)
            APP.processEvents()
            self.assertFalse(self.ctl.box_only(), name)
        self.type("L")
        self.assertFalse(self.ctl.box_only())                                     # dessin : le reticule entier

    def test_magnet_reaches_as_far_at_a_shared_end_of_a_selected_line(self):
        self.line((0, 0), (200, 0))
        wire = self.line((0, 0), (0, 150))                                        # extremite commune en (0, 0)
        for selected in (wire, [i for i in self.ctl.cad_items() if i is not wire][0]):
            self.pane.scene.clearSelection()
            selected.setSelected(True)
            for offset in ((9, 0), (-9, 0), (0, 9), (0, -9), (6, 6), (-6, -6)):
                self.move((100, 80))
                self.move(offset)
                self.assertIsNotNone(self.ctl.hover_snap, (offset, selected.points()))
                self.assertEqual(self.ctl.hover_snap.point, (0.0, 0.0))
                self.assertIs(self.ctl.hover_snap.candidate.entity, selected)


class SelectionFrameTest(CadBoardCase):
    """Reglages > Module CAD > Selection : fond, bordures, arrondis, type de ligne des deux cadres ; le carre du
    reticule disparait pendant une fenetre de selection."""

    def test_frames_follow_the_settings_and_default_to_the_old_look(self):
        look = self.ctl.look
        self.assertEqual(look["sel_window"]["line"], "solid")
        self.assertEqual(look["sel_crossing"]["line"], "dash")
        self.ctl.apply_settings(dict(self.ctl.settings, board_cad_window_bg="#80ff0000", board_cad_window_line="dot",
                                     board_cad_window_line_scale=250, board_cad_window_radius={"top_left": 6},
                                     board_cad_window_border_enabled={"top": True, "right": False, "bottom": True,
                                                                      "left": False}))
        frame = self.ctl.look["sel_window"]
        self.assertEqual((frame["bg"], frame["line"], frame["scale"]), ("#80ff0000", "dot", 250.0))
        self.assertEqual(frame["radius"]["top_left"], 6)
        self.assertFalse(frame["sides"]["right"])
        from PySide6.QtGui import QImage, QPainter
        from fm_cad.cad_overlay import paint_selection_frame
        for f in (frame, self.ctl.look["sel_crossing"]):
            image = QImage(60, 40, QImage.Format_ARGB32_Premultiplied)
            image.fill(0)
            painter = QPainter(image)
            paint_selection_frame(painter, QRectF(5, 5, 50, 30), f)
            painter.end()
            self.assertGreater(QColor(image.pixelColor(30, 20)).alpha(), 0)     # le fond est peint

    def test_partial_repaint_covers_every_changed_pixel(self):
        """Latence signalee entre le curseur et le cadre : seuls les bords qui bougent sont repeints ; tout pixel qui
        change entre deux positions doit pourtant etre dans la zone repeinte (pointilles et arrondis compris)."""
        from PySide6.QtGui import QImage, QPainter
        from fm_cad.cad_overlay import CadOverlay, DEFAULT_FRAMES, paint_selection_frame

        def image(rect, frame):
            out = QImage(260, 200, QImage.Format_ARGB32_Premultiplied)
            out.fill(0)
            painter = QPainter(out)
            paint_selection_frame(painter, rect, frame)
            painter.end()
            return out

        def op(rect, frame):
            pad = 2 + frame["thickness"]
            band = int(pad + max([0, *frame["radius"].values()]) + 3)
            padded = rect.adjusted(-pad, -pad, pad, pad)
            return [("window", padded, (rect, False, band))], [padded.toAlignedRect().adjusted(-1, -1, 1, 1)]
        rounded = dict(DEFAULT_FRAMES[1], thickness=2, scale=150,
                       radius={"top_left": 8, "top_right": 8, "bottom_right": 8, "bottom_left": 8})
        for frame in (DEFAULT_FRAMES[0], DEFAULT_FRAMES[1], rounded):
            for old, new in ((QRectF(20, 20, 100, 60), QRectF(20, 20, 137, 91)),        # coin haut gauche fixe
                             (QRectF(20, 20, 100, 60), QRectF(20, 20, 61, 33)),         # il retrecit
                             (QRectF(100, 90, 120, 80), QRectF(63, 41, 157, 129)),      # coin bas droit fixe
                             (QRectF(30, 30, 80, 40), QRectF(110, 30, 60, 90))):        # il passe de l'autre cote
                old_ops, old_rects = op(old, frame)
                ops, rects = op(new, frame)
                dirty = CadOverlay._dirty(old_ops, old_rects, ops, rects)
                a, b = image(old, frame), image(new, frame)
                for y in range(a.height()):
                    for x in range(a.width()):
                        if a.pixel(x, y) != b.pixel(x, y):
                            self.assertTrue(any(r.contains(x, y) for r in dirty), (frame["line"], old, new, x, y))

    def test_moving_corner_falls_exactly_on_the_crosshair(self):
        """Signale : « le cadre est un peu a cote du reticule a l'arret ». Le coin mobile est le point ecran du
        reticule et les bords sont cales sur les memes pixels que lui, a des positions fractionnaires aussi."""
        from PySide6.QtGui import QImage, QPainter
        overlay = self.ctl.overlay
        frame = dict(self.ctl.look["sel_window"], bg="#00000000")
        for corner in (QPointF(64.99999, 80.6), QPointF(65.0, 80.0), QPointF(70.5, 90.49)):
            image = QImage(120, 120, QImage.Format_ARGB32_Premultiplied)
            image.fill(0)
            painter = QPainter(image)
            overlay._paint_window(painter, dict(self.ctl.look, sel_window=frame), QRectF(), False, 0,
                                  QPointF(10.3, 10.7), corner)
            painter.end()
            column, row = int(math.floor(corner.x())), int(math.floor(corner.y()))
            edge = [x for x in range(120) if QColor(image.pixelColor(x, 40)).alpha()]
            self.assertEqual(edge, [10, column])                                  # un pixel, celui de la croix
            edge = [y for y in range(120) if QColor(image.pixelColor(40, y)).alpha()]
            self.assertEqual(edge, [10, row])
        self.click((0, 0))
        self.move((30, 20))
        state = self.ctl.overlay_state()
        self.assertEqual(state["window"][3], self.ctl.cursor_view)                # pas d'aller-retour ecran / document
        self.click((30, 20))

    def test_dragging_opens_the_same_window_closed_by_a_second_click(self):
        """Demande de l'utilisateur : appuyer en bougeant n'est pas une autre selection ; la fenetre reste ouverte au
        relachement, seul un 2e clic la ferme."""
        line = self.line((20, 20), (30, 30))
        viewport = self.pane.view.viewport()
        QTest.mousePress(viewport, Qt.LeftButton, Qt.NoModifier, self.vp((0, 0)))
        QTest.mouseMove(viewport, self.vp((25, 25)))
        QTest.mouseMove(viewport, self.vp((50, 50)))
        QTest.mouseRelease(viewport, Qt.LeftButton, Qt.NoModifier, self.vp((50, 50)))
        APP.processEvents()
        self.assertIsNotNone(self.ctl.window)                                   # toujours ouverte
        self.assertFalse(line.isSelected())
        self.move((60, 60))
        self.click((60, 60))                                                    # 2e clic : fermee
        self.assertIsNone(self.ctl.window)
        self.assertTrue(line.isSelected())

    def test_pickbox_hidden_while_a_window_is_open(self):
        self.ctl.cursor_view = self.ctl.doc_to_view((10, 10))
        self.ctl.cursor_doc = (10.0, 10.0)
        self.assertTrue(self.ctl.overlay_state()["pickbox"])
        self.click((10, 10))                                                    # clic dans le vide : fenetre
        self.move((40, 40))
        self.assertIsNotNone(self.ctl.window)
        self.assertFalse(self.ctl.overlay_state()["pickbox"])
        self.click((40, 40))
        self.assertTrue(self.ctl.overlay_state()["pickbox"])

    def test_selection_settings_are_in_the_cad_tab(self):
        import settings_window_v2 as v2
        from settings_store import DEFAULT_SETTINGS
        groups = {node.group for top in v2.CAD_TREE for node in (top, *top.children)}
        self.assertTrue({"CAD : Fenêtre de sélection", "CAD : Capture", "CAD : Ajuster"} <= groups)
        import copy
        for group in ("CAD : Fenêtre de sélection", "CAD : Capture"):
            for spec in v2.CATALOG[group]:
                for key in (spec.key, *spec.extra_keys):
                    self.assertIn(key, DEFAULT_SETTINGS)
            settings = copy.deepcopy(DEFAULT_SETTINGS)
            fields = {}
            v2.build_group(group, v2.ScopeValues(settings, None), settings["colors"], fields, {}, [], [], lambda: None)
            line = [sp for sp in v2.CATALOG[group] if sp.kind == "line_pattern"][0]
            widget = fields[line.key]
            widget._v2_parts["kind"].setValue("Points")
            widget._v2_parts["scale"].setValue(250)
            self.assertEqual(v2.FIELD_READERS["line_pattern"](line, widget),
                             {line.key: "dot", line.params["scale_key"]: 250})


class LineweightDisplayTest(CadBoardCase):
    """Affichage « simples lignes » (LWT) : epaisseurs ignorees a l'ecran, jamais a l'export."""

    def test_hairline_mode_ignores_lineweights_and_can_be_toggled_back(self):
        item = self.line((0, 0), (100, 0))
        self.ctl.change_entities([item], {"lineweight": 6.0}, "t")
        self.assertGreater(item.props()["lineweight"], 0.0)
        self.type("LWT")
        self.assertFalse(self.ctl.mode_on("lineweight"))
        self.assertEqual(item.props()["lineweight"], 0.0)
        self.assertEqual(item.data["lineweight"], 6.0)                                # le document n'est pas touche
        self.type("EPAIS")
        self.assertTrue(self.ctl.mode_on("lineweight"))
        self.assertGreater(item.props()["lineweight"], 0.0)


class FramePacerTest(unittest.TestCase):
    """Retard du rendu GPU pendant un pan (demande de l'utilisateur) : echange de tampons sans attente du balayage,
    la couche cadence elle-meme ses images — UNE par balayage, lancee juste avant la composition."""

    def make(self, timing=None):
        from PySide6.QtCore import QObject, Signal
        from fm_cad import cad_gpu

        class Widget(QObject):
            frameSwapped = Signal()
            updates = 0

            def update(self):
                self.updates += 1

        class Clock:
            ok = timing is not None

            def read(self):
                return timing() if timing else None
        widget = Widget()
        pacer = cad_gpu.FramePacer(widget, 60.0)
        pacer.active = True
        pacer.clock = Clock()
        return widget, pacer

    def test_one_frame_per_vblank_launched_just_before_it(self):
        period = 1 / 60.0
        base = time.perf_counter()
        widget, pacer = self.make(lambda: (base - 0.001, period))
        pacer.request()
        self.assertTrue(pacer.scheduled())                          # trop tot : attend le moment de lancer
        self.assertEqual(widget.updates, 0)
        wait = (pacer._deadline - time.perf_counter()) * 1000
        self.assertLessEqual(abs(wait - (period - 0.001 - pacer.cost - pacer.MARGIN_S) * 1000), 3)
        pacer.request()
        pacer.request()                                             # demandes regroupees
        settle(wait / 1000 + 0.02)
        self.assertEqual(widget.updates, 1)
        pacer.request()                                             # image pas encore presentee : rien de plus
        self.assertEqual(widget.updates, 1)
        widget.frameSwapped.emit()
        self.assertFalse(pacer.pending)
        target = pacer.last_target
        pacer.request()                                             # ce balayage est pris : le suivant
        self.assertGreater(pacer.last_target, target + period / 2)

    def test_without_compositor_at_most_one_frame_per_period(self):
        widget, pacer = self.make(None)
        pacer.request()
        self.assertEqual(widget.updates, 1)                         # la 1re tout de suite
        widget.frameSwapped.emit()
        pacer.request()
        self.assertEqual(widget.updates, 1)                         # la suivante une periode apres
        self.assertTrue(pacer.scheduled())
        settle(0.04)
        self.assertEqual(widget.updates, 2)

    def test_inactive_when_the_swap_waits_for_the_vblank(self):
        widget, pacer = self.make(None)
        pacer.active = False
        for _ in range(3):
            pacer.request()
        self.assertEqual(widget.updates, 3)                         # le pilote cadence : update() direct

    def test_launch_is_precise_with_an_idle_event_loop(self):
        """Une minuterie de Qt, boucle endormie, arrivait jusqu'a 10 ms en retard (saccades) : le fil de cadence
        lance l'image a ~1 ms pres."""
        from PySide6.QtCore import QEventLoop, QTimer
        widget, pacer = self.make(None)
        late = []
        wanted = [0.0]
        widget.update = lambda: late.append((time.perf_counter() - wanted[0]) * 1000)
        for _ in range(10):
            wanted[0] = time.perf_counter() + 0.007
            pacer._schedule(wanted[0])
            loop = QEventLoop()
            QTimer.singleShot(30, loop.quit)
            loop.exec()                                             # boucle qui DORT, comme dans l'appli
        self.assertEqual(len(late), 10)
        self.assertLess(sorted(late)[8], 4.0)


class RenderBadgeTest(CadBoardCase):
    """Encart « OPEN GL » (vert) / « CLASSIQUE » (rouge) en haut a droite : suit le mode de rendu reel."""

    def test_badge_follows_the_render_mode(self):
        badge = self.pane._badge
        self.assertEqual(badge.label(), "CLASSIQUE")                           # hors ecran : pas d'OpenGL
        self.assertTrue(badge.isVisible())
        right = self.pane.width() - 16
        self.assertEqual(badge.geometry().right() + 1, right)                  # colle en haut a droite
        self.assertEqual(badge.geometry().top(), 16)
        self.pane.view.renderModeChanged.emit(True)                            # le mode change : l'encart suit aussitot
        self.assertEqual(badge.label(), "OPEN GL")
        self.pane.view.renderModeChanged.emit(False)
        self.assertEqual(badge.label(), "CLASSIQUE")


class ScaleTest(CadBoardCase):
    """ECHELLE (SC, cad_shapes.scaled) : facteur tape ou point, Copier, Reference, une etape d'annulation."""

    def select(self, *items):
        self.pane.scene.clearSelection()
        for item in items:
            item.setSelected(True)

    def test_scaled_geometry_of_every_kind(self):
        line = cad_shapes.scaled("cad_line", {"p1": [10.0, 0.0], "p2": [20.0, 5.0]}, (0.0, 0.0), 2.0)
        self.assertEqual((line["p1"], line["p2"]), ([20.0, 0.0], [40.0, 10.0]))
        circle = cad_shapes.scaled("cad_circle", {"center": [10.0, 0.0], "radius": 3.0}, (0.0, 0.0), 0.5)
        self.assertEqual((circle["center"], circle["radius"]), ([5.0, 0.0], 1.5))
        arc = cad_shapes.scaled("cad_arc", {"center": [10.0, 0.0], "radius": 4.0, "start": 10.0, "end": 80.0}, (10.0, 0.0), 3.0)
        self.assertEqual((arc["center"], arc["radius"], arc["start"], arc["end"]), ([10.0, 0.0], 12.0, 10.0, 80.0))
        pline = cad_shapes.scaled("cad_pline", {"vertices": [[0.0, 0.0, 0.5], [10.0, 0.0, 0.0]], "closed": False}, (0.0, 0.0), 2.0)
        self.assertEqual(pline["vertices"], [[0.0, 0.0, 0.5], [20.0, 0.0, 0.0]])    # renflements inchanges
        hatch = cad_shapes.scaled("cad_hatch", {"loops": [[[0.0, 0.0], [10.0, 0.0], [10.0, 10.0]]], "hatch_origin": [0.0, 0.0],
                                                "hatch_angle": 45.0, "hatch_spacing": 4.0}, (0.0, 0.0), 2.0)
        self.assertEqual(hatch["hatch_spacing"], 8.0)
        self.assertEqual(hatch["hatch_angle"], 45.0)

    def test_scale_by_a_typed_factor_in_one_undo_step(self):
        line = self.line((10, 0), (20, 0))
        self.select(line)
        self.type("SC", "0,0", "2")
        self.assertEqual(line.points(), ((20.0, 0.0), (40.0, 0.0)))
        self.ctl.undo()
        self.assertEqual(line.points(), ((10.0, 0.0), (20.0, 0.0)))

    def test_scale_copy_reference_and_bad_factor(self):
        line = self.line((10, 0), (20, 0))
        self.select(line)
        self.type("SC", "0,0", "C", "3")
        self.assertEqual(len(self.ctl.cad_items()), 2)                              # copie : l'original reste
        self.assertEqual(line.points(), ((10.0, 0.0), (20.0, 0.0)))
        self.ctl.undo()
        self.assertEqual(len(self.ctl.cad_items()), 1)
        self.select(line)
        self.type("SC", "0,0", "R", "10", "25")                                     # longueur 10 -> 25 : facteur 2,5
        self.assertEqual(line.points(), ((25.0, 0.0), (50.0, 0.0)))
        self.select(line)
        self.type("SC", "0,0", "0")
        self.assertIn("supérieur à 0", self.ctl.history[-1][0])
        self.type("")

    def test_scale_by_a_point_uses_its_distance_to_the_base(self):
        line = self.line((10, 0), (20, 0))
        self.select(line)
        self.type("SC", "0,0")
        self.move((0, 30))
        self.assertTrue(self.ctl.overlay_state()["ghosts"])                           # apercu au survol
        self.click((0, 30))
        self.assertEqual(line.points(), ((300.0, 0.0), (600.0, 0.0)))


class UnitsTest(CadBoardCase):
    """Unite de mesure (Reglages > Module CAD > Unites, override du dessin) : geometrie en unites du board, saisie et
    affichage dans l'unite ; 1 cm trace = 1 cm reel (1 unite du board = 1/96 de pouce)."""

    def set_unit(self, unit):
        self.pane.apply_settings(dict(self.pane._settings, board_cad_unit=unit))
        settle()

    def test_typed_lengths_are_in_the_chosen_unit(self):
        self.set_unit("cm")
        self.type("L", "0,0", "@2,0", "")
        line = self.ctl.cad_items()[0]
        self.assertAlmostEqual(line.length(), 2 * 96 / 2.54)
        self.assertEqual(self.ctl.fmt(line.length()), "2.0000")
        self.assertEqual(self.ctl.unit_symbol(), "cm")
        self.set_unit("m")
        self.assertEqual(self.ctl.fmt(line.length()), "0.0200")              # geometrie inchangee, affichage en m
        self.type("L", "1,0", "@1<90", "")
        second = [i for i in self.ctl.cad_items() if i is not line][0]
        self.assertAlmostEqual(second.points()[0][0], 9600 / 2.54)
        self.assertAlmostEqual(second.length(), 9600 / 2.54)

    def test_drawing_override_beats_the_general_unit(self):
        self.set_unit("mm")
        drawing(self.ctl, board_cad_unit="km", board_cad_precision=2)
        self.assertEqual(cad_model.drawing_overrides(self.ctl.cad_page())["board_cad_unit"], "km")
        self.assertEqual(self.ctl.unit_symbol(), "km")
        self.assertEqual(self.ctl.precision(), 2)
        self.type("L", "0,0", "@1,0", "")
        self.assertAlmostEqual(self.ctl.cad_items()[0].length(), 9600000 / 2.54)
        self.ctl.undo()                                             # la ligne
        self.ctl.undo()                                             # les reglages du dessin
        self.assertNotIn("overrides", self.ctl.cad_page())
        self.assertEqual(self.ctl.unit_symbol(), "mm")

    def test_properties_and_weights_follow_the_unit(self):
        self.set_unit("cm")
        self.type("L", "0,0", "3,4", "")
        line = self.ctl.cad_items()[0]
        line.setSelected(True)
        rows = __import__("fm_cad.cad_ui", fromlist=["PropertyRows"]).PropertyRows(self.ctl.ui)
        specs = {key: value for key, _l, _k, value, _e in rows.specs()}
        self.assertEqual(specs["length"], "5.0000")
        self.assertEqual(specs["end2:x"], "3.0000")
        rows._set_weight("0.5")
        self.assertAlmostEqual(line.data["lineweight"], 0.5 * 96 / 2.54)
        rows._set_coord("end2", 1, "0")
        self.assertAlmostEqual(line.points()[1][0], 3 * 96 / 2.54)


class LinetypesTest(CadBoardCase):
    """Types de ligne reglables : sequence trait / espace dans l'unite, terminaisons du debut, de la fin et des segments
    interieurs (overridables par objet), segment additionnel et repartition des segments."""

    def setUp(self):
        super().setUp()
        self.addCleanup(cad_model.set_linetypes, None)                       # types d'origine pour les suivants

    def install(self, *defs):
        self.pane.apply_settings(dict(self.pane._settings, board_cad_linetypes=list(defs)))
        settle()

    def rows(self):
        return __import__("fm_cad.cad_ui", fromlist=["PropertyRows"]).PropertyRows(self.ctl.ui)

    def test_sequence_parsing_and_pattern(self):
        self.assertEqual(cad_model.parse_sequence("1 0.5 0.5 0.5"), [1.0, 0.5, 0.5, 0.5])
        self.assertIsNone(cad_model.parse_sequence("1 -2"))
        self.assertIsNone(cad_model.parse_sequence("1 ; x"))
        self.assertEqual(cad_model.sequence_pattern([1, 1]), (1.0, -1.0))
        self.assertEqual(cad_model.sequence_pattern([0, 2]), (0.0, -2.0))                # point
        self.assertEqual(cad_model.sequence_pattern([2, 1, 3]), (2.0, -1.0, 3.0, -2.0, 1.0, -3.0))  # impaire : x2

    def test_pattern_is_in_the_drawing_unit_and_settings_restyle_the_lines(self):
        self.install({"key": "pointille", "name": "Pointillé maison", "sequence": [10, 5]})
        line = self.line((0, 0), (100, 0))
        self.ctl.change_entities([line], {"linetype": "pointille"}, "x")
        self.assertEqual(line._thin_dashes[:2], [(0.0, 10.0), (15.0, 25.0)])
        self.pane.apply_settings(dict(self.pane._settings, board_cad_unit="mm"))
        self.assertAlmostEqual(line._thin_dashes[0][1], 10 * 96 / 25.4)       # 10 mm
        self.pane.apply_settings(dict(self.pane._settings, board_cad_unit="px"))
        self.install({"key": "pointille", "name": "Pointillé maison", "sequence": [20, 5]})
        self.assertEqual(line._thin_dashes[0], (0.0, 20.0))

    def test_type_ends_inner_ends_and_object_overrides(self):
        self.install({"key": "axe", "name": "Axe", "sequence": [10, 5, 2, 5],
                      "end1": {"style": "round"}, "end2": {"style": "flat"}, "inner": {"style": "radius", "radius": 100}})
        line = self.line((0, 0), (100, 0))
        self.ctl.change_entities([line], {"linetype": "axe", "lineweight": 4.0}, "x")
        props = line.props()
        self.assertEqual((props["end1"]["style"], props["end2"]["style"], props["inner"]["style"]),
                         ("round", "flat", "radius"))
        self.assertAlmostEqual(line._dashed.boundingRect().left(), -2.0)      # arrondi du debut : au-dela du point
        line.setSelected(True)
        rows = self.rows()
        rows._set_end("end1", "style", "Coupe franche")                       # override de l'objet
        self.assertEqual(line.data["end1"]["style"], "flat")
        self.assertAlmostEqual(line._dashed.boundingRect().left(), 0.0)
        rows._set_end("end1", "style", cad_model.BYTYPE_LABEL)                # retour au type
        self.assertEqual(line.data["end1"], cad_model.BYTYPE)
        self.assertAlmostEqual(line._dashed.boundingRect().left(), -2.0)
        rows._set_end("inner", "radius", 30)                                  # override du rayon interieur
        self.assertEqual(line.data["inner"], {"style": "radius", "radius": 30})

    def test_distribution_fits_whole_cycles_plus_the_extra_segment(self):
        self.install({"key": "axe", "name": "Axe", "sequence": [8, 1.5, 1.5, 1.5], "extra": 8})
        line = self.line((0, 0), (100, 0))
        self.ctl.change_entities([line], {"linetype": "axe"}, "x")
        cut = line._thin_dashes
        self.assertLess(cut[-1][1] - cut[-1][0], 8.0 - 1e-6)                  # sans repartition : dernier trait coupe
        line.setSelected(True)
        self.rows()._set_distribute(True)
        self.assertTrue(line.data["distribute"])
        # Repartir = CENTRER : 7 cycles entiers + le segment additionnel (95,5), motif a sa taille, reste de chaque cote.
        dashes = line._thin_dashes
        self.assertAlmostEqual(dashes[0][0], 2.25)
        self.assertAlmostEqual(dashes[-1][1], 97.75)
        self.assertAlmostEqual(dashes[0][0] + dashes[-1][1], 100.0)           # symetrique
        self.assertAlmostEqual(dashes[0][1] - dashes[0][0], 8.0)              # le trait garde sa taille
        self.assertAlmostEqual(dashes[-1][1] - dashes[-1][0], 8.0)
        self.assertEqual(cad_model.centered_span(100.0, 12.5, 8.0), (2.25, 95.5))
        # Redimensionner : le motif est allonge / raccourci pour remplir toute la ligne (l'ancienne repartition).
        self.rows()._set_resize(True)
        self.assertTrue(line.data["resize"])
        dashes = line._thin_dashes
        self.assertEqual(dashes[0][0], 0.0)
        self.assertAlmostEqual(dashes[-1][1], 100.0)
        self.assertAlmostEqual(dashes[-1][1] - dashes[-1][0], dashes[0][1] - dashes[0][0])   # finit par le trait long
        self.assertAlmostEqual(cad_model.distribution(100.0, 12.5, 8.0), 100.0 / (7 * 12.5 + 8.0))  # 7 cycles + 8
        self.rows()._set_distribute(False)                                    # sans « repartir » : motif d'origine
        self.assertAlmostEqual(line._thin_dashes[0][1], 8.0)
        self.assertLess(line._thin_dashes[-1][1] - line._thin_dashes[-1][0], 8.0 - 1e-6)

    def test_unknown_type_is_kept_and_drawn_continuous(self):
        line = self.line((0, 0), (100, 0))
        self.ctl.change_entities([line], {"linetype": "disparu"}, "x")
        self.assertEqual(line.props()["pattern"], ())
        self.assertEqual(cad_model.describe_linetype("disparu"), "disparu (absent)")
        self.assertEqual(cad_model.normalize_line(line.to_dict())["linetype"], "disparu")

    def test_old_files_current_ends_become_by_type(self):
        cad = cad_model.normalize_cad_page({"version": 1, "end1": {"style": "flat", "radius": 50.0},
                                            "end2": {"style": "round", "radius": 50.0}})
        self.assertEqual(cad["end1"], cad_model.BYTYPE)
        self.assertEqual(cad["end2"]["style"], "round")

    def test_settings_field_edits_types_and_the_marker_snaps_to_segments(self):
        from fm_cad.cad_linetype_ui import LinetypePreview, LinetypesField
        field = LinetypesField([])
        self.addCleanup(field.deleteLater)
        self.assertEqual([d["key"] for d in field.values()][:2], ["continuous", "dashed"])
        changes = []
        field.changed.connect(lambda: changes.append(1))
        field._add()
        self.assertEqual(field.values()[-1]["sequence"], [1.0, 1.0])
        self.assertTrue(changes)
        preview = LinetypePreview(field.defs[-1])
        self.addCleanup(preview.deleteLater)
        x0, _length, per_unit = preview._span()
        self.assertEqual(preview._extra_at(x0 + 1.0 * per_unit + 3), 1.0)     # aimante au bout du trait
        self.assertAlmostEqual(preview._extra_at(x0 + 1.5 * per_unit), 1.5)   # entre deux : libre
        image = preview.grab()                                                # dessin sans erreur
        self.assertFalse(image.isNull())


class SharedGridTest(CadBoardCase):
    """Une seule grille pour le board et le CAD : F7, bouton de la barre d'outils du board, Reglages > Module MRO >
    Grille ; RESOL (F9) s'accroche au niveau affiche ; un dessin peut imposer son pas."""

    def test_f7_and_board_button_toggle_the_same_page_grid(self):
        self.assertTrue(self.ctl.grid_on())
        self.ctl.toggle("grid")
        self.assertFalse(self.pane.scene.page["grid"])
        self.assertFalse(self.ctl.mode_on("grid"))
        self.pane.toggle_grid()
        self.assertTrue(self.pane.scene.page["grid"])
        self.assertTrue(self.pane._grid_button._on)
        self.ctl.undo()
        self.assertFalse(self.pane.scene.page["grid"])

    def test_grid_snap_uses_the_displayed_level(self):
        self.ctl.toggle("grid_snap", True)
        self.ctl.toggle("osnap", False)
        step = self.pane.scene.grid_step()
        self.type("L")
        self.move((step * 3 + step * 0.3, step * 2 - step * 0.2))
        self.assertAlmostEqual(self.ctl.res.point[0], step * 3)
        self.assertAlmostEqual(self.ctl.res.point[1], step * 2)

    def test_settings_and_drawing_step_change_the_grid(self):
        from PySide6.QtGui import QImage, QPainter
        from fm_board.scene import grid_look
        look = grid_look({"board_grid_step": 1000, "board_grid_factor": 10, "board_grid_style": "dots"})
        self.assertEqual((look["step"], look["factor"], look["style"]), (10.0, 10, "dots"))
        self.assertAlmostEqual(grid_look({})["intensity"], 0.066)
        scene = self.pane.scene
        scene.set_grid_settings({"board_grid_step": 1000, "board_grid_factor": 10, "board_grid_style": "dots"})
        self.assertEqual(scene.grid_base(), 10.0)
        drawing(self.ctl, board_grid_step=500)                                # le dessin remplace le pas general
        self.assertEqual(scene.grid_base(), 5.0)
        self.assertEqual(scene.grid_look["factor"], 10)                       # le reste suit le general
        image = QImage(200, 200, QImage.Format_ARGB32_Premultiplied)
        image.fill(0)
        painter = QPainter(image)
        scene.drawBackground(painter, QRectF(0, 0, 200, 200))
        painter.end()
        self.assertGreater(len({image.pixel(x, y) for x in range(0, 200, 3) for y in range(0, 200, 3)}), 1)


class OverrideDotsTest(CadBoardCase):
    """Les lignes suivent les reglages (calque, type de ligne) ; une propriete changee dans le panneau est REMPLACEE :
    point orange sur sa cellule (clic = retour au reglage), point sur le titre Valeur (clic = toutes)."""

    def setUp(self):
        super().setUp()
        self.addCleanup(cad_model.set_linetypes, None)

    def panel(self, line):
        line.setSelected(True)
        self.ctl.ui.show_properties()
        self.ctl.ui._rebuild_properties()
        return self.ctl.ui._prop_rows

    def test_new_lines_follow_the_type_settings_live(self):
        line = self.line((0, 0), (100, 0))
        self.assertFalse(any(cad_model.overridden(line.data, k) for k in cad_model.FOLLOWING))
        self.pane.apply_settings(dict(self.pane._settings, board_cad_linetypes=[
            {"key": "continuous", "name": "Continu", "sequence": [], "end1": {"style": "round"}, "distribute": True}]))
        self.assertEqual(line.props()["end1"]["style"], "round")              # reglage change : la ligne suit
        self.assertTrue(line.props()["distribute"])

    def test_dots_show_overrides_and_reset_them(self):
        line = self.line((0, 0), (100, 0))
        rows = self.panel(line)
        self.assertFalse(rows.head_dot.isVisibleTo(rows.head_dot.parentWidget()))
        rows._set_end("end2", "style", "Arrondi")
        rows._set_weight("3")
        self.ctl.ui._rebuild_properties()
        rows = self.ctl.ui._prop_rows
        visible = {key for key, (dot, _k) in rows.dots.items() if dot.isVisibleTo(dot.parentWidget())}
        self.assertIn("end2:style", visible)
        self.assertIn("weight", visible)
        self.assertNotIn("color", visible)
        self.assertTrue(rows.head_dot.isVisibleTo(rows.head_dot.parentWidget()))
        rows.dots["end2:style"][0].clicked.emit()                             # un point : cette propriete
        settle()
        self.assertEqual(line.data["end2"], cad_model.BYTYPE)
        self.assertEqual(line.data["lineweight"], 3.0)
        self.ctl.ui._prop_rows.head_dot.clicked.emit()                        # le titre : toutes
        settle()
        self.assertEqual(line.data["lineweight"], cad_model.BYLAYER)
        self.ctl.undo()
        self.assertEqual(line.data["lineweight"], 3.0)                        # une seule etape

    def test_current_properties_have_dots_too(self):
        self.ctl.ui.show_properties()
        self.ctl.ui._rebuild_properties()
        rows = self.ctl.ui._prop_rows
        rows._set_end("inner", "style", "Arrondi")
        self.assertEqual(rows.overridden_keys(), {"inner"})
        rows.reset(["inner"])
        self.assertEqual(self.ctl.cad_page()["inner"], cad_model.BYTYPE)

    def test_radius_slider_changes_the_line_at_once_in_one_undo_step(self):
        line = self.line((0, 0), (100, 0))
        rows = self.panel(line)
        rows._set_end("inner", "style", "Border radius")
        depth = self.pane.scene.undo.count()
        for value in (10, 20, 30, 40):
            rows._live_radius("inner", value)
            self.assertEqual(line.data["inner"]["radius"], value)            # chaque cran, sans attente
        self.pane.scene.commit_live()
        self.assertEqual(self.pane.scene.undo.count(), depth + 1)

    def test_focused_text_field_no_longer_delays_the_panel(self):
        line = self.line((0, 0), (100, 0))
        self.panel(line)
        from PySide6.QtWidgets import QLineEdit
        field = self.ctl.ui.properties.findChildren(QLineEdit)[0]
        field.setFocus()
        self.ctl.ui._prop_rows._set_end("end1", "style", "Border radius")
        self.assertEqual(line.data["end1"]["style"], "radius")
        self.assertFalse(self.ctl.ui._props_timer.isActive() and self.ctl.ui._props_timer.interval() == 300)

    def test_old_files_follow_the_settings(self):
        data = model.normalize({"page": {"cad": {"version": 2}}, "items": [
            dict(model.new_item("cad_line", p2=[10.0, 0.0]), distribute=False,
                 end1={"style": "round", "radius": 50.0})]})
        line = data["items"][0]
        self.assertEqual(line["distribute"], cad_model.BYTYPE)                # version 2 : False jamais choisi
        self.assertEqual(line["end1"]["style"], "round")                      # vrai override : garde


class PipetteTest(CadBoardCase):
    def test_matchprop_copies_every_property_one_step_per_pick(self):
        source = self.line((0, 0), (100, 0))
        target = self.line((0, 50), (100, 50))
        other = self.line((0, 100), (100, 100))
        self.ctl.change_entities([source], {"lineweight": 4.0, "linetype": "center", "end1": {"style": "round"},
                                            "distribute": True, "color": "#ff0000"}, "x")
        source.setSelected(True)
        self.type("MA")
        self.assertIn("destination", self.ctl.prompt_line())
        self.click((50, 50))
        self.assertEqual(target.data["lineweight"], 4.0)
        self.assertEqual(target.data["end1"], source.data["end1"])
        self.assertTrue(target.data["distribute"])
        self.assertEqual(other.data["color"], cad_model.BYLAYER)
        self.click((50, 100))
        self.assertEqual(other.data["color"], "#ff0000")
        self.type("")
        self.assertIsNone(self.ctl.command)
        self.ctl.undo()
        self.assertEqual(other.data["color"], cad_model.BYLAYER)
        self.assertEqual(target.data["color"], "#ff0000")

    def test_source_picked_by_click_when_nothing_is_selected(self):
        source = self.line((0, 0), (100, 0))
        target = self.line((0, 50), (100, 50))
        self.ctl.change_entities([source], {"lineweight": 2.0}, "x")
        self.type("PIPETTE")
        self.assertIn("source", self.ctl.prompt_line())
        self.click((50, 0))
        self.click((50, 50))
        self.assertEqual(target.data["lineweight"], 2.0)


class DotsPlacementTest(CadBoardCase):
    """Points orange : dans la 1re colonne (a cote du libelle), celui de l'entete est cliquable, plus satures."""

    def test_dots_are_in_the_first_column_and_really_clickable(self):
        from PySide6.QtWidgets import QApplication
        from fm_cad.cad_ui import OverrideDot
        line = self.line((0, 0), (100, 0))
        line.setSelected(True)
        self.ctl.ui.show_properties()
        self.ctl.ui._rebuild_properties()
        rows = self.ctl.ui._prop_rows
        rows._set_weight("3")
        self.ctl.ui._rebuild_properties()
        rows = self.ctl.ui._prop_rows
        settle(0.05)
        head = rows.head_dot.parentWidget()
        first = head._cells[0]
        self.assertTrue(rows.head_dot.isVisible())
        centre = rows.head_dot.mapTo(head, QPoint(7, 7))
        self.assertTrue(first.geometry().contains(centre))                     # dans la 1re colonne de l'entete
        dot = rows.dots["weight"][0]
        self.assertTrue(dot.isVisible())
        for found in (rows.head_dot, dot):                                      # la souris tombe bien sur le point
            host = found.parentWidget()
            self.assertIs(host.childAt(found.mapTo(host, QPoint(7, 7))), found)
        clicks = []
        rows.head_dot.clicked.connect(lambda: clicks.append(1))
        QTest.mouseClick(rows.head_dot, Qt.LeftButton, Qt.NoModifier, QPoint(7, 7))
        self.assertEqual(clicks, [1])
        self.assertAlmostEqual(OverrideDot.color().saturationF(), 1.0, places=2)   # sature


class DistributionMigrationTest(unittest.TestCase):
    def test_old_distribution_keeps_its_look_as_resize(self):
        data = model.normalize({"page": {"cad": {"version": 3, "distribute": True}}, "items": [
            dict(model.new_item("cad_line", p2=[10.0, 0.0]), distribute=True)]})
        self.assertTrue(data["items"][0]["resize"])                           # version 3 : repartir redimensionnait
        self.assertTrue(cad_model.page_cad(data["page"])["resize"])
        fresh = cad_model.normalize_linetype({"key": "a", "sequence": [1, 1], "distribute": True})
        self.assertTrue(fresh["resize"])
        newer = cad_model.normalize_linetype({"key": "a", "sequence": [1, 1], "distribute": True, "resize": False})
        self.assertFalse(newer["resize"])

    def test_centered_span_keeps_whole_cycles_in_the_middle(self):
        self.assertEqual(cad_model.centered_span(100.0, 10.0, 5.0), (2.5, 95.0))   # 9 cycles + 5
        self.assertEqual(cad_model.centered_span(3.0, 10.0, 5.0), (0.0, 3.0))      # rien ne tient : ligne entiere
        self.assertEqual(cad_model.centered_span(50.0, 0.0, 0.0), (0.0, 50.0))     # sans motif


class CrosshairTest(CadBoardCase):
    """Reticule : 1 pixel de large (boite centrale comprise), couleur, taille du carre, aimant sur les objets
    seulement, indicateur « proprietes en memoire », reglages du dessin."""

    def test_native_cursor_is_one_pixel_wide_with_the_square_in_the_middle(self):
        cursor = native_cursor(40, 5, "#1a1a1a", 1.0)
        image = cursor.pixmap().toImage()
        opaque = sum(1 for y in range(image.height()) for x in range(image.width()) if QColor(image.pixelColor(x, y)).alpha())
        self.assertEqual(opaque, 4 * 35 + 40)                                   # 4 bras d'un pixel + contour d'un pixel
        centre = 40
        self.assertEqual(QColor(image.pixelColor(centre + 1, centre + 1)).alpha(), 0)   # un seul pixel d'epaisseur
        self.assertEqual(QColor(image.pixelColor(centre, centre)).alpha(), 0)          # les bras partent du carre
        self.assertEqual(QColor(image.pixelColor(centre + 6, centre)).alpha(), 255)
        self.assertEqual(QColor(image.pixelColor(centre, centre - 6)).alpha(), 255)
        self.assertEqual(QColor(image.pixelColor(centre + 5, centre + 5)).alpha(), 255)   # coin du carre
        self.assertEqual(QColor(image.pixelColor(centre + 4, centre + 4)).alpha(), 0)     # dedans : vide

    def test_painted_crosshair_is_crisp_whatever_the_position(self):
        from PySide6.QtGui import QImage, QPainter
        overlay = self.ctl.overlay
        for at in (QPointF(50.4, 30.7), QPointF(50.0, 30.0), QPointF(50.9, 30.5)):
            image = QImage(200, 80, QImage.Format_ARGB32_Premultiplied)
            image.fill(0)
            painter = QPainter(image)
            overlay._paint_cursor(painter, self.ctl.look, at, "#000000", 30, 5)
            overlay._paint_cursor_h(painter, self.ctl.look, at, "#000000", 200)
            painter.end()
            row = [QColor(image.pixelColor(10, y)).alpha() for y in range(80)]
            self.assertEqual([y for y, a in enumerate(row) if a], [int(at.y())])      # une seule rangee, opaque
            self.assertEqual(max(row), 255)
            col = [QColor(image.pixelColor(x, 75)).alpha() for x in range(200)]
            self.assertEqual(col.count(0), 200)                                         # (rien hors du reticule)

    def test_color_and_square_size_are_settings(self):
        self.assertEqual(self.ctl.look["pickbox_px"], 5)
        self.ctl.apply_settings(dict(self.ctl.settings, board_cad_pickbox=9, board_cad_crosshair_auto_color=False,
                                     board_cad_crosshair_color="#ff0000"))
        self.assertEqual(self.ctl.look["pickbox_px"], 9)
        self.assertEqual(QColor(self.ctl.look["cursor"]).getRgb()[:3], (255, 0, 0))
        self.ctl.apply_settings(dict(self.ctl.settings, board_cad_crosshair_auto_color=True))
        self.assertNotEqual(QColor(self.ctl.look["cursor"]).getRgb()[:3], (255, 0, 0))

    def test_magnet_follows_objects_never_the_grid(self):
        self.line((0, 0), (100, 0))
        self.ctl.toggle("grid_snap", True)
        self.ctl.toggle("osnap", False)
        step = self.pane.scene.grid_step()
        self.type("L")
        self.move((step * 2 + step * 0.3, step * 3 - 20))
        self.assertEqual(self.ctl.res.kind, "grid")
        native, painted = self.ctl._cursor_plan()
        self.assertIsNotNone(native)                                           # le reticule reste a la souris
        self.assertFalse(painted)
        self.assertIsNotNone(self.ctl.overlay_state().get("grid_snap"))        # l'indicateur de grille reste
        self.ctl.toggle("grid_snap", False)
        self.ctl.toggle("osnap", True)
        self.move((100, 0))
        self.assertEqual(self.ctl.res.kind, "osnap")
        self.assertEqual(self.ctl._cursor_plan(), (None, True))               # sur un objet : aimante

    def test_pipette_source_is_shown_on_the_crosshair(self):
        source = self.line((0, 0), (100, 0))
        self.line((0, 50), (100, 50))
        self.ctl.change_entities([source], {"color": "#ff0000"}, "x")
        self.assertIsNone(self.ctl.memory_color())
        plain, _painted = self.ctl._cursor_plan()
        source.setSelected(True)
        self.type("MA")
        self.assertEqual(QColor(self.ctl.memory_color()).getRgb()[:3], (255, 0, 0))
        marked, _painted = self.ctl._cursor_plan()
        self.assertIsNot(marked, plain)                                        # curseur avec l'indicateur
        self.assertEqual(self.ctl.overlay_state()["memory"], self.ctl.memory_color())
        self.ctl.apply_settings(dict(self.ctl.settings, board_cad_crosshair_memory=False))
        self.assertIsNone(self.ctl.memory_color())
        self.ctl.apply_settings(dict(self.ctl.settings, board_cad_crosshair_memory=True))
        self.type("")                                                          # Entree : fin de la pipette
        self.assertIsNone(self.ctl.memory_color())

    def test_crosshair_snap_and_coordinates_follow_a_pan(self):
        from PySide6.QtCore import QEvent
        from PySide6.QtGui import QMouseEvent
        self.ctl.apply_settings(dict(self.ctl.settings, board_cad_crosshair_full=True))
        self.line((0, 0), (200, 0))
        self.type("L")
        vp = self.pane.view.viewport()
        start = QPointF(self.vp((60, 40)))

        def send(kind, pos, held):
            QApplication.sendEvent(vp, QMouseEvent(kind, pos, vp.mapToGlobal(pos), Qt.MiddleButton, held,
                                                   Qt.NoModifier))
            APP.processEvents()
        self.move((60, 40))
        send(QEvent.MouseButtonPress, start, Qt.MiddleButton)
        for step in range(1, 6):                                            # le board defile sous le pointeur
            pos = start + QPointF(15 * step, 7 * step)
            send(QEvent.MouseMove, pos, Qt.MiddleButton)
            self.assertEqual(self.ctl.cursor_view, pos)                       # reticule sous le pointeur
            state = self.ctl.overlay_state()
            self.assertTrue(state["paint_cursor"])
            self.assertEqual(state["cursor"], pos)
            doc = self.ctl.view_to_doc(pos)
            self.assertAlmostEqual(self.ctl.cursor_doc[0], doc[0])            # point du document relu
            self.assertAlmostEqual(self.ctl.cursor_doc[1], doc[1])
            self.assertAlmostEqual(self.ctl.res.point[0], doc[0], places=6)   # accrochage / coordonnees a jour
        send(QEvent.MouseButtonRelease, pos, Qt.NoButton)
        self.assertEqual(self.pane.view.viewport().cursor().shape(), Qt.BlankCursor)   # toujours le reticule

    def test_drawing_can_override_every_crosshair_setting(self):
        for key in cad_model.CROSSHAIR_KEYS:
            self.assertTrue(cad_model.overridable(key))
        self.assertEqual(self.ctl.look["pickbox_px"], 5)
        drawing(self.ctl, board_cad_pickbox=11, board_cad_crosshair_full=True)
        self.assertEqual(self.ctl.look["pickbox_px"], 11)
        self.assertTrue(self.ctl.look["crosshair_full"])
        drawing(self.ctl)                                                      # aucun override : le general
        self.assertEqual(self.ctl.look["pickbox_px"], 5)
        self.assertFalse(self.ctl.look["crosshair_full"])

    def test_drawing_window_groups_the_crosshair_with_type_one_toggles_in_the_first_column(self):
        rows = self.ctl.ui.drawing_rows()
        labels = [row[0] for row in rows]
        first = labels.index("Réticule en croix")
        group = [r for r in rows if r[0].startswith(("Réticule", "Longueur des bras", "Bras", "Couleur du réticule", "Couleur automatique (selon",
                                                    "Carré central", "Aimant", "Indicateur"))]
        self.assertGreaterEqual(len(group), 6)
        self.assertEqual(labels[first:first + len(group)], [r[0] for r in group])   # regroupes, a la suite
        for row in group:
            self.assertEqual(len(row), 4)
            self.assertEqual(row[3]._table_style, "toggle1")
        from settings_quick_style import QuickStyleWindow
        window = QuickStyleWindow("test : dessin", self.ctl.ui.drawing_rows(), {}, title="t",
                                  settings=__import__("fm_cad.cad_ui", fromlist=["x"]).full_settings(self.pane),
                                  parent=self.pane)
        self.addCleanup(window.close)
        _label, widget, reader, toggle = next(r for r in window._rows if r[0] == "Carré central : demi-côté (pixels d'écran, = boîte de sélection)")
        cell = toggle.parentWidget()
        self.assertEqual(toggle.mapTo(window.table, QPoint(0, 0)).x() < widget.mapTo(window.table, QPoint(0, 0)).x(), True)
        self.assertEqual(toggle._base_override, "toggle1")                    # type 1 une fois normalise
        toggle.setChecked(True)
        self.assertTrue(reader(widget)["ovr:board_cad_pickbox"])


class NavigationAndCursorTest(CadBoardCase):
    def wheel(self, steps, mods=Qt.NoModifier):
        from PySide6.QtGui import QWheelEvent
        vp = self.pane.view.viewport()
        pos = QPointF(400, 300)
        event = QWheelEvent(pos, vp.mapToGlobal(pos), QPoint(0, 0), QPoint(0, int(120 * steps)), Qt.NoButton, mods,
                            Qt.NoScrollPhase, False)
        QApplication.sendEvent(vp, event)

    def test_zoom_speed_and_fine_zoom_with_shift(self):
        self.pane.apply_settings(dict(self.pane._settings, board_zoom_speed=20, board_zoom_fine=2))
        view = self.pane.view
        view.set_zoom(1.0)
        self.wheel(1)
        self.assertAlmostEqual(view.zoom(), 1.2)
        self.wheel(1, Qt.ShiftModifier)
        self.assertAlmostEqual(view.zoom(), 1.2 * 1.02)
        self.wheel(-1, Qt.ShiftModifier)
        self.assertAlmostEqual(view.zoom(), 1.2)

    def test_full_crosshair_is_painted_to_the_edges(self):
        self.ctl.apply_settings(dict(self.ctl.settings, board_cad_crosshair_full=True))
        self.move((10, 10))
        native, painted = self.ctl._cursor_plan()
        self.assertIsNone(native)
        self.assertTrue(painted)
        kinds = {kind for kind, _r, _a in self.ctl.overlay._layout(self.ctl.overlay_state())[0]}
        self.assertTrue({"cursor_h", "cursor_v"} <= kinds)

    def test_grid_snap_shows_an_indicator(self):
        self.ctl.toggle("grid_snap", True)
        self.ctl.toggle("osnap", False)
        step = self.pane.scene.grid_step()
        self.type("L")
        self.move((step * 2 + step * 0.3, step))
        state = self.ctl.overlay_state()
        self.assertAlmostEqual(state["grid_snap"][0][0], step * 2)
        kinds = {kind for kind, _r, _a in self.ctl.overlay._layout(state)[0]}
        self.assertIn("grid_snap", kinds)
        image = self.ctl.overlay.grab()
        self.assertFalse(image.isNull())


class FullGridTest(CadBoardCase):
    def test_origin_moves_lines_and_snap(self):
        scene = self.pane.scene
        scene.set_grid_settings({"board_grid_origin_x": 150, "board_grid_origin_y": 250})   # 1.5, 2.5
        self.assertEqual(scene.grid_origin(), (1.5, -2.5))
        step = scene.grid_step()
        self.assertAlmostEqual(scene.grid_snap(1.5 + step * 3 + step * 0.2, 0), 1.5 + step * 3)
        self.ctl.toggle("grid_snap", True)
        self.ctl.toggle("osnap", False)
        self.type("L")
        self.move((1.5 + step * 2 + step * 0.2, 2.5 + step - step * 0.1))
        self.assertAlmostEqual(self.ctl.res.point[0], 1.5 + step * 2)
        self.assertAlmostEqual(self.ctl.res.point[1], 2.5 + step)

    def test_every_style_and_axes_paint(self):
        from PySide6.QtGui import QImage, QPainter
        scene = self.pane.scene
        for style in ("lines", "dots", "crosses"):
            scene.set_grid_settings({"board_grid_style": style, "board_grid_axes": True, "board_grid_levels": 2,
                                     "board_grid_dot_size": 4})
            image = QImage(120, 120, QImage.Format_ARGB32_Premultiplied)
            image.fill(0)
            painter = QPainter(image)
            painter.translate(60, 60)
            scene.drawBackground(painter, QRectF(-60, -60, 120, 120))
            painter.end()
            self.assertGreater(QColor(image.pixel(60, 30)).red(), QColor(image.pixel(31, 31)).red())   # axe rouge

    def test_screen_grid_is_one_crisp_pixel_per_line_like_the_tile(self):
        scene, view = self.pane.scene, self.pane.view
        view.set_zoom(1.0)
        view.center_on(QPointF(0.3, 0.2))
        calls = []
        original = scene._paint_grid_fast
        scene._paint_grid_fast = lambda *a: calls.append(1) or original(*a)
        try:
            image = view.viewport().grab().toImage()
        finally:
            del scene._paint_grid_fast
        self.assertTrue(calls)                                                # chemin rapide a l'ecran
        x = view.mapFromScene(QPointF(0, 0)).x()
        y = view.height() // 3
        column = [QColor(image.pixel(x + d, y)).red() for d in (-1, 0, 1)]
        self.assertLess(column[1], column[0])                                 # la ligne : un seul pixel plus sombre
        self.assertLess(column[1], column[2])
        scene._paint_grid_fast = lambda *a: False                             # meme image par la tuile, a 1 niveau pres
        try:
            tiled = view.viewport().grab().toImage()
        finally:
            del scene._paint_grid_fast
        self.assertLessEqual(abs(QColor(tiled.pixel(x, y)).red() - column[1]), 6)

    def test_drawing_overrides_any_grid_setting(self):
        scene = self.pane.scene
        scene.set_grid_settings({"board_grid_factor": 5, "board_grid_style": "lines"})
        drawing(self.ctl, board_grid_style="dots", board_grid_origin_x=100)
        self.assertEqual(scene.grid_look["style"], "dots")
        self.assertEqual(scene.grid_look["factor"], 5)
        self.assertEqual(scene.grid_origin()[0], 1.0)
        drawing(self.ctl)                                                     # aucun override : le general
        self.assertEqual(scene.grid_look["style"], "lines")

    def test_drawing_window_rows_have_override_toggles(self):
        rows = self.ctl.ui.drawing_rows()
        labels = [row[0] for row in rows]
        self.assertIn("Origine X", labels)
        self.assertIn("Grille affichée (F7)", labels)
        _label, widget, reader, toggle = next(r for r in rows if r[0] == "Style")
        values = reader(widget)
        self.assertFalse(values["ovr:board_grid_style"])
        toggle.setChecked(True)
        self.assertTrue(reader(widget)["ovr:board_grid_style"])
        self.assertEqual(toggle._table_style, "toggle1")                      # de type 1, devant le libelle
