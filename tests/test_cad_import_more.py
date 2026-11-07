"""Import DXF / DWG du module CAD, entites ajoutees le 2026-11-04 (fm_cad/cad_import.py ; « continue a enchainer
tous les modules autocad manquants ») : POINT (figure PDMODE / PDSIZE du dessin), SOLID / TRACE (pleins), repere
multiple (MULTILEADER eclate), maillages (POLYFACE -> aretes des faces), 3DFACE, attributs des blocs (ATTRIB),
MINSERT (grille entiere), police des styles de texte ; export des points."""
import os as _os, sys as _sys  # jamais les vrais reglages / presets de l'utilisateur (tests/_isolate.py)
_sys.path.insert(0, _os.path.dirname(_os.path.abspath(__file__)))
import _isolate  # noqa: E402,F401
import tempfile
import unittest
from pathlib import Path

import fm_board  # noqa: F401  (ordre d'import : fm_board avant fm_cad)
from fm_cad import cad_import

ezdxf = __import__("ezdxf")


def drawing():
    doc = ezdxf.new("R2018")
    doc.header["$INSUNITS"] = 0
    return doc


class ImportMoreTest(unittest.TestCase):
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

    def read(self, doc):
        path = self.dir / "plan.dxf"
        doc.saveas(path)
        return cad_import.read_drawing(path)

    def kind(self, data, kind):
        return [i for i in data["items"] if i["type"] == kind]

    def test_points_take_the_figure_of_the_drawing(self):
        doc = drawing()
        doc.header["$PDMODE"] = 34
        doc.header["$PDSIZE"] = 5.0
        doc.modelspace().add_point((10, 20))
        block = doc.blocks.new("P")
        block.add_point((1, 0))
        doc.modelspace().add_blockref("P", (100, 0), dxfattribs={"rotation": 90, "xscale": 2, "yscale": 2})
        data, report = self.read(doc)
        self.assertEqual(report["ignored"], {})
        points = sorted(self.kind(data, "cad_point"), key=lambda i: i["pos"][0])
        self.assertEqual(len(points), 2)
        self.assertEqual(points[0]["pos"], [10.0, 20.0])
        self.assertEqual((points[0]["pdmode"], points[0]["pdsize"]), (34, 5.0))
        self.assertAlmostEqual(points[1]["pos"][0], 100.0)
        self.assertAlmostEqual(points[1]["pos"][1], 2.0)
        self.assertEqual(points[1]["pdsize"], 5.0)                         # la figure ne grandit pas avec le bloc

    def test_solids_faces_and_meshes(self):
        doc = drawing()
        msp = doc.modelspace()
        msp.add_solid([(0, 0), (10, 0), (0, 10), (10, 10)])                   # ordre 1-2-4-3 : un carre
        msp.add_solid([(20, 0), (30, 0), (25, 10)])                          # triangle
        msp.add_3dface([(0, 50, 0), (10, 50, 0), (10, 60, 0), (0, 60, 0)])
        mesh = msp.add_polyface()
        mesh.append_face([(100, 0, 0), (110, 0, 0), (110, 10, 0)])
        data, report = self.read(doc)
        self.assertEqual(report["ignored"], {})
        fills = self.kind(data, "cad_hatch")
        self.assertEqual(len(fills), 2)
        self.assertTrue(all(h["hatch_pattern"] == "solid" and h["hatch_alpha"] == 100.0 for h in fills))
        square = next(h for h in fills if len(h["loops"][0]) == 4)
        self.assertEqual(sorted(map(tuple, square["loops"][0])), [(0.0, 0.0), (0.0, 10.0), (10.0, 0.0), (10.0, 10.0)])
        lines = self.kind(data, "cad_line")
        self.assertEqual(len(lines), 4 + 3)                                  # 3DFACE + face du maillage

    def test_multileader_is_exploded(self):
        doc = drawing()
        builder = doc.modelspace().add_multileader_mtext("Standard")
        builder.set_content("Repère", char_height=2.5)
        builder.add_leader_line(ezdxf.render.mleader.ConnectionSide.left, [(0, 0)])
        builder.build(insert=ezdxf.math.Vec2(20, 10))
        data, report = self.read(doc)
        self.assertNotIn("MULTILEADER", report["ignored"])
        self.assertTrue(self.kind(data, "cad_text"))
        self.assertTrue(self.kind(data, "cad_line") or self.kind(data, "cad_pline"))

    def test_attributes_and_minsert_grid(self):
        doc = drawing()
        block = doc.blocks.new("REP")
        block.add_line((0, 0), (5, 0))
        block.add_attdef("NUM", (0, 2), dxfattribs={"height": 1.0})
        insert = doc.modelspace().add_blockref("REP", (100, 100))
        insert.add_auto_attribs({"NUM": "A12"})
        grid = doc.modelspace().add_blockref("REP", (0, 0))
        grid.dxf.column_count, grid.dxf.row_count = 3, 2
        grid.dxf.column_spacing, grid.dxf.row_spacing = 10.0, 20.0
        data, _report = self.read(doc)
        texts = self.kind(data, "cad_text")
        self.assertEqual([t["text"] for t in texts], ["A12"])
        self.assertAlmostEqual(texts[0]["pos"][1], 102.0)
        lines = self.kind(data, "cad_line")
        self.assertEqual(len(lines), 1 + 6)                                  # l'insertion + les 6 cases du MINSERT
        self.assertIn([20.0, 20.0], [l["p1"] for l in lines])

    def test_text_style_font(self):
        doc = drawing()
        doc.styles.new("CARTOUCHE", dxfattribs={"font": "arialn.ttf"})
        doc.styles.new("SHX", dxfattribs={"font": "romans.shx"})
        doc.modelspace().add_text("Titre", dxfattribs={"style": "CARTOUCHE", "height": 3})
        doc.modelspace().add_text("Cote", dxfattribs={"style": "SHX", "height": 3, "insert": (0, 10)})
        data, _report = self.read(doc)
        fonts = {t["text"]: t["font"] for t in self.kind(data, "cad_text")}
        self.assertEqual(fonts["Titre"], "Arial Narrow")
        self.assertNotEqual(fonts["Cote"], "romans")                          # SHX : la police du module


if __name__ == "__main__":
    unittest.main()
