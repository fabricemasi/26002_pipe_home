"""Hachures d'un DXF / DWG ouvert dans le module CAD (fm_cad/cad_import.py `_hatch`, fm_cad/cad_hatch.py motif « dxf » ;
demande de l'utilisateur, 2026-11-04 : « continue la conception du module cad », les 1 173 hachures de son DWG etaient
ignorees) : contours, motif d'AutoCAD garde tel quel (familles de traits, tirets, points), plein, degrade, blocs
tournes / retournes, transformations du module, aller-retour DXF."""
import os as _os, sys as _sys  # jamais les vrais reglages / presets de l'utilisateur (tests/_isolate.py)
_sys.path.insert(0, _os.path.dirname(_os.path.abspath(__file__)))
import _isolate  # noqa: E402,F401
import math
import tempfile
import unittest
from pathlib import Path

import fm_board  # noqa: F401  (ordre d'import : fm_board avant fm_cad)
from fm_cad import cad_commands, cad_export, cad_hatch, cad_import, cad_shapes
from test_cad import CadBoardCase

ezdxf = __import__("ezdxf")
SQUARE = [(0, 0), (100, 0), (100, 100), (0, 100)]


def drawing():
    doc = ezdxf.new("R2018")
    doc.header["$INSUNITS"] = 0                         # 1 unite du dessin = 1 unite du board
    return doc


def add_hatch(space, pattern="ANSI31", points=SQUARE, scale=1.0, angle=0.0, **attribs):
    hatch = space.add_hatch(dxfattribs=attribs)
    hatch.paths.add_polyline_path(points, is_closed=True)
    if pattern == "SOLID":
        hatch.set_solid_fill()
    else:
        hatch.set_pattern_fill(pattern, scale=scale, angle=angle)
    return hatch


def segments(data) -> set:
    """Traits du motif, sans ordre ni sens, arrondis."""
    out = set()
    for a, b in cad_hatch.pattern_segments(data["loops"], cad_hatch.style_of(data)):
        pa, pb = tuple(round(v, 3) + 0.0 for v in a), tuple(round(v, 3) + 0.0 for v in b)
        out.add(min(pa, pb) + max(pa, pb))
    return out


def moved(segs, fn) -> set:
    out = set()
    for x1, y1, x2, y2 in segs:
        pa, pb = (tuple(round(v, 3) + 0.0 for v in fn((x1, y1))), tuple(round(v, 3) + 0.0 for v in fn((x2, y2))))
        out.add(min(pa, pb) + max(pa, pb))
    return out


def close(a: set, b: set, tol: float = 0.01) -> bool:
    """Memes traits a `tol` pres (chaque trait de l'un a son pareil dans l'autre)."""
    def found(seg, others):
        return any(max(abs(u - v) for u, v in zip(seg, other)) <= tol for other in others)
    return len(a) == len(b) and all(found(seg, b) for seg in a)


class HatchImportTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        from fm_cad import cad_import
        cls._native = cad_import.NATIVE_BLOCKS
        cad_import.NATIVE_BLOCKS = False        # ces tests portent sur l'import ECLATE (blocs natifs : test_cad_blocks)

    @classmethod
    def tearDownClass(cls):
        from fm_cad import cad_import
        cad_import.NATIVE_BLOCKS = cls._native
        super().tearDownClass()

    def setUp(self):
        self.dir = Path(tempfile.mkdtemp())

    def read(self, doc, name="plan.dxf"):
        path = self.dir / name
        doc.saveas(path)
        return cad_import.read_drawing(path)

    def hatches(self, data):
        return [i for i in data["items"] if i["type"] == "cad_hatch"]

    def test_ansi31_keeps_its_lines_their_angle_and_spacing(self):
        doc = drawing()
        add_hatch(doc.modelspace())
        doc.modelspace().add_line((0, 0), (100, 100))
        data, report = self.read(doc)
        self.assertEqual(report["ignored"], {})
        (hatch,) = self.hatches(data)
        self.assertIs(data["items"][0], hatch)                                   # derriere le reste
        self.assertEqual((hatch["hatch_pattern"], hatch["hatch_name"]), (cad_hatch.DXF, "ANSI31"))
        self.assertEqual(len(hatch["loops"]), 1)
        segs = cad_hatch.pattern_segments(hatch["loops"], cad_hatch.style_of(hatch))
        self.assertGreater(len(segs), 30)
        for a, b in segs:                                                        # traits a 45°, dans le carre
            self.assertAlmostEqual(math.degrees(math.atan2(b[1] - a[1], b[0] - a[0])) % 180.0, 45.0, places=6)
            for p in (a, b):
                self.assertTrue(-1e-6 <= p[0] <= 100 + 1e-6 and -1e-6 <= p[1] <= 100 + 1e-6)
        rows = sorted({round((b[1] - b[0]) / math.sqrt(2), 6) for b in ((a[0], a[1]) for a, _b in segs)})
        gaps = {round(y - x, 3) for x, y in zip(rows, rows[1:])}
        self.assertEqual(gaps, {3.175})                                          # ecart ISO d'ANSI31
        self.assertAlmostEqual(hatch["hatch_spacing"], 3.175, places=6)

    def test_scaled_and_turned_pattern(self):
        doc = drawing()
        add_hatch(doc.modelspace(), scale=2.0, angle=30.0)
        data, _report = self.read(doc)
        (hatch,) = self.hatches(data)
        self.assertAlmostEqual(hatch["hatch_angle"], 30.0, places=6)
        self.assertAlmostEqual(hatch["hatch_spacing"], 6.35, places=6)
        for a, b in cad_hatch.pattern_segments(hatch["loops"], cad_hatch.style_of(hatch)):
            self.assertAlmostEqual(math.degrees(math.atan2(b[1] - a[1], b[0] - a[0])) % 180.0, 75.0, places=6)

    def test_dashes_and_two_families(self):
        """ANGLE : deux familles (0° et 90°) en tirets de 10,16 separes de 3,81."""
        doc = drawing()
        add_hatch(doc.modelspace(), pattern="ANGLE")
        data, _report = self.read(doc)
        (hatch,) = self.hatches(data)
        segs = cad_hatch.pattern_segments(hatch["loops"], cad_hatch.style_of(hatch))
        angles = {round(math.degrees(math.atan2(b[1] - a[1], b[0] - a[0])) % 180.0, 6) for a, b in segs}
        self.assertEqual(angles, {0.0, 90.0})
        lengths = [math.dist(a, b) for a, b in segs]
        self.assertLessEqual(max(lengths), 10.16 + 1e-6)
        self.assertGreater(sum(1 for v in lengths if abs(v - 10.16) < 1e-6), len(lengths) // 2)

    def test_dots_are_drawn(self):
        doc = drawing()
        hatch = doc.modelspace().add_hatch()
        hatch.paths.add_polyline_path(SQUARE, is_closed=True)
        hatch.set_pattern_fill("POINTS", definition=[[0.0, (0.0, 0.0), (0.0, 10.0), [0.0, -10.0]]])
        data, _report = self.read(doc)
        (item,) = self.hatches(data)
        segs = cad_hatch.pattern_segments(item["loops"], cad_hatch.style_of(item))
        self.assertGreater(len(segs), 50)                                        # ~ 10 x 10 points
        self.assertTrue(all(0.0 < math.dist(a, b) < 0.5 for a, b in segs))

    def test_solid_and_gradient_fills(self):
        doc = drawing()
        add_hatch(doc.modelspace(), pattern="SOLID")
        grad = doc.modelspace().add_hatch()
        grad.paths.add_polyline_path([(200, 0), (300, 0), (300, 100)], is_closed=True)
        grad.set_gradient((255, 0, 0), (0, 0, 255), rotation=30.0, name="CYLINDER")
        data, _report = self.read(doc)
        solid, gradient = self.hatches(data)
        self.assertEqual((solid["hatch_pattern"], solid["hatch_alpha"]), ("solid", 100.0))
        self.assertEqual((gradient["hatch_pattern"], gradient["hatch_alpha"]), (cad_hatch.GRADIENT, 100.0))
        self.assertEqual(gradient["color"], "#ff0000")                            # 1re couleur = celle de l'objet
        self.assertEqual(gradient["hatch_color2"], "#0000ff")
        self.assertEqual(gradient["hatch_gradient"], "CYLINDER")
        self.assertAlmostEqual(gradient["hatch_angle"], 30.0)
        self.assertEqual(cad_hatch.gradient_stops("INVCYLINDER"), [(0.0, 2), (0.5, 1), (1.0, 2)])
        self.assertNotEqual(solid["color"], "#ff0000")

    def test_holes_and_curved_edges(self):
        doc = drawing()
        hatch = doc.modelspace().add_hatch()
        hatch.paths.add_polyline_path(SQUARE, is_closed=True, flags=1)
        edge = hatch.paths.add_edge_path(flags=16)
        edge.add_arc((50, 50), 20, 0, 360)                                    # ilot : un cercle
        hatch.set_pattern_fill("ANSI31")
        data, _report = self.read(doc)
        (item,) = self.hatches(data)
        self.assertEqual(len(item["loops"]), 2)
        for a, b in cad_hatch.pattern_segments(item["loops"], cad_hatch.style_of(item)):
            mid = ((a[0] + b[0]) / 2, (a[1] + b[1]) / 2)
            self.assertGreater(math.dist(mid, (50, 50)), 20 - 0.5)            # rien dans le trou

    def test_block_turned_and_mirrored_keeps_the_pattern_on_the_block(self):
        """Hachure d'un bloc pose tourne / retourne / mis a l'echelle : les traits de la hachure du bloc passes par la
        matrice de l'insertion (le motif suit le bloc, comme dans AutoCAD ; l'eclatement d'ezdxf, lui, ne deplace pas
        le point de base du motif : il glisse dans la forme)."""
        doc = drawing()
        block = doc.blocks.new("B")
        add_hatch(block, pattern="ANGLE", points=[(0.37, 0.21), (40, 0.4), (40, 25), (0.2, 25)])
        own, _rgb = cad_import._hatch(next(iter(block.query("HATCH"))), 0.01)
        msp = doc.modelspace()
        inserts = [msp.add_blockref("B", (100, 0), dxfattribs={"rotation": 30, "xscale": 2, "yscale": 2}),
                   msp.add_blockref("B", (0, 100), dxfattribs={"xscale": -1}),
                   msp.add_blockref("B", (300, 300), dxfattribs={"rotation": 120, "xscale": -1.5, "yscale": 1.5})]
        data, report = self.read(doc)
        self.assertEqual(report["ignored"], {})
        found = self.hatches(data)
        self.assertEqual(len(found), 3)
        for insert, got in zip(inserts, found):
            m = insert.matrix44()
            want = moved(segments(own), lambda p: tuple(m.transform((p[0], p[1], 0.0)))[:2])
            self.assertTrue(want and close(segments(got), want))

    def test_move_turn_scale_mirror_keep_the_pattern(self):
        doc = drawing()
        add_hatch(doc.modelspace(), pattern="ANGLE", points=[(0.37, 0.21), (60, 0.5), (60, 30), (10, 45)])
        data, _report = self.read(doc)
        (hatch,) = self.hatches(data)
        before = segments(hatch)
        cases = [
            (cad_shapes.rotated("cad_hatch", hatch, (10, 5), 37.0), lambda p: cad_shapes.rotated_point(p, (10, 5), 37.0)),
            (cad_shapes.scaled("cad_hatch", hatch, (3, 4), 1.7), lambda p: cad_shapes.scaled_point(p, (3, 4), 1.7)),
            (cad_shapes.mirrored("cad_hatch", hatch, (0, 0), (10, 3)),
             lambda p: cad_shapes.mirrored_point(p, (0, 0), (10, 3))),
            ({**hatch, **cad_hatch.translate(hatch, (12.5, -3))}, lambda p: (p[0] + 12.5, p[1] - 3)),
        ]
        for changed, fn in cases:
            self.assertTrue(close(segments({**hatch, **changed}), moved(before, fn)))

    def test_families_round_trip_through_the_drawing_frame(self):
        world = [(45.0, (3.0, 4.0), (-2.245, 2.245), []), (135.0, (1.0, -2.0), (-1.0, -1.5), [5.0, -1.0, 0.0, -1.0])]
        lines = cad_hatch.families_from_world(world, (3.0, 4.0), 20.0, 3.175)
        data = {"hatch_pattern": cad_hatch.DXF, "hatch_lines": lines, "hatch_angle": 20.0, "hatch_spacing": 3.175,
                "hatch_origin": [3.0, 4.0]}
        for (a, base, offset, dashes), (a2, base2, offset2, dashes2) in zip(world, cad_hatch.families_to_world(data)):
            self.assertAlmostEqual(a, a2, places=9)
            for u, v in zip((*base, *offset, *dashes), (*base2, *offset2, *dashes2)):
                self.assertAlmostEqual(u, v, places=9)


class HatchOnTheBoardTest(CadBoardCase):
    def test_imported_pattern_is_an_entity_shown_and_exported_back(self):
        doc = drawing()
        add_hatch(doc.modelspace(), pattern="ANGLE", points=[(0.37, 0.21), (60, 0.5), (60, 30), (10, 45)])
        path = self.dir / "source.dxf"
        doc.saveas(path)
        data, _report = cad_import.read_drawing(path)
        (source,) = [i for i in data["items"] if i["type"] == "cad_hatch"]
        geometry = {k: source[k] for k in ("loops", "hatch_pattern", "hatch_angle", "hatch_spacing", "hatch_origin",
                                           "hatch_lines", "hatch_name", "hatch_alpha")}
        item = self.ctl.create_entity("cad_hatch", geometry)
        self.ctl.commit_created([item], "test")
        self.assertEqual(segments(item.data), segments(source))
        self.assertGreater(len(item.prims()), 10)                                # ses traits : lot / GPU
        self.assertEqual(cad_commands.hatch_pattern_label(cad_hatch.style_of(item.data)), "AutoCAD : ANGLE")
        target = self.dir / "retour.dxf"
        cad_export.export_dxf(self.pane.scene, target, "mm")
        back, _report = cad_import.read_drawing(target)
        (again,) = [i for i in back["items"] if i["type"] == "cad_hatch"]
        self.assertEqual((again["hatch_pattern"], again["hatch_name"]), (cad_hatch.DXF, "ANGLE"))
        self.assertTrue(close(segments(again), segments(item.data), tol=0.02))


if __name__ == "__main__":
    unittest.main()
