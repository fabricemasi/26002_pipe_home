"""BLOCS du module CAD (fm_cad/cad_block.py, fm_cad/cad_commands_blocks.py, cad_items.CadInsertItem ; 2026-11-04) :
BLOC (convertir / conserver, redefinir), INSERER (echelle, rotation), references transformees (deplacer, tourner,
miroir, echelle), blocs imbriques, DECOMPOSER, enregistrement."""
import os as _os, sys as _sys  # jamais les vrais reglages / presets de l'utilisateur (tests/_isolate.py)
_sys.path.insert(0, _os.path.dirname(_os.path.abspath(__file__)))
import _isolate  # noqa: E402,F401
import unittest

from fm_cad import cad_block, cad_model, cad_shapes
from test_cad import CadBoardCase


def rnd(p):
    return tuple(round(v, 6) + 0.0 for v in p)


class PureBlockTest(unittest.TestCase):
    def cad(self):
        return {"blocks": {"T": {"base": [0.0, 0.0], "items": [
            {"type": "cad_line", "p1": [0.0, 0.0], "p2": [10.0, 0.0]},
            {"type": "cad_text", "pos": [0.0, 5.0], "text": "A", "height": 2.0}]},
            "N": {"base": [0.0, 0.0], "items": [
                {"type": "cad_insert", "block": "T", "pos": [100.0, 0.0], "scale": 1.0, "rot": 90.0}]}}}

    def test_placed_entities(self):
        found = cad_block.parts(self.cad(), {"block": "T", "pos": [5.0, 5.0], "scale": 2.0, "rot": 90.0})
        (line,) = found["prims"]
        self.assertEqual((rnd(line[1]), rnd(line[2])), ((5.0, 5.0), (5.0, 25.0)))
        self.assertEqual(len(found["texts"]), 1)
        self.assertEqual(found["texts"][0]["height"], 4.0)
        mirrored = cad_block.parts(self.cad(), {"block": "T", "pos": [0.0, 0.0], "mirror": True})["prims"][0]
        self.assertEqual(rnd(mirrored[2]), (-10.0, 0.0))

    def test_nested_and_self_reference(self):
        found = cad_block.parts(self.cad(), {"block": "N", "pos": [0.0, 0.0], "rot": 90.0})
        (line,) = found["prims"]
        self.assertEqual((rnd(line[1]), rnd(line[2])), ((0.0, 100.0), (-10.0, 100.0)))     # 90 + 90 = 180
        loop = {"blocks": {"L": {"base": [0, 0], "items": [{"type": "cad_insert", "block": "L", "pos": [1, 1]}]}}}
        self.assertEqual(cad_block.parts(loop, {"block": "L"})["prims"], [])
        self.assertTrue(cad_block.uses(self.cad(), "T", "N"))
        self.assertEqual(cad_block.clean_name(' a<b>/c '), "abc")


class InkTest(unittest.TestCase):
    """Couleur / epaisseur de CHAQUE entite d'un bloc (calque 0, PARBLOC, ByLayer, propre ; calque masque)."""

    def cad(self):
        layers = [dict(cad_model.LAYER_DEFAULTS, color="#000000"),
                  dict(cad_model.LAYER_DEFAULTS, id="R", name="Rouge", color="#ff0000", lineweight=2.0),
                  dict(cad_model.LAYER_DEFAULTS, id="H", name="Cache", color="#00ff00", visible=False)]
        return {"layers": layers, "blocks": {"K": {"base": [0, 0], "items": [
            {"type": "cad_line", "p1": [0, 0], "p2": [1, 0], "layer": "0", "color": "ByLayer"},
            {"type": "cad_line", "p1": [0, 1], "p2": [1, 1], "layer": "0", "color": cad_model.BYBLOCK,
             "lineweight": cad_model.BYBLOCK},
            {"type": "cad_line", "p1": [0, 2], "p2": [1, 2], "layer": "R", "color": "ByLayer"},
            {"type": "cad_line", "p1": [0, 3], "p2": [1, 3], "layer": "0", "color": "#0000ff", "lineweight": 5.0},
            {"type": "cad_line", "p1": [0, 4], "p2": [1, 4], "layer": "H"}]}}}

    def test_each_entity_keeps_its_ink(self):
        cad = self.cad()
        ref = {"block": "K", "layer": "R", "color": "#123456", "lineweight": 3.0}
        strokes = cad_block.parts(cad, ref)["strokes"]
        self.assertEqual(sorted(strokes), [("#0000ff", 5.0), ("#123456", 3.0), ("#ff0000", 2.0)])
        self.assertEqual(len(strokes[("#ff0000", 2.0)]), 2)          # calque 0 -> calque R ; et l'entite sur R
        self.assertEqual(len(strokes[("#123456", 3.0)]), 1)          # PARBLOC -> la reference
        self.assertEqual(len(cad_block.parts(cad, ref)["prims"]), 4)  # calque masque : rien
        plain = cad_block.parts(cad, {"block": "K"})["strokes"]       # reference ByLayer sur le calque 0
        self.assertEqual(len(plain[("#000000", 0.0)]), 2)

    def test_signature_follows_only_the_layers_of_the_block(self):
        cad = self.cad()
        ref = {"block": "K", "layer": "0"}
        before = cad_block.signature(cad, ref)
        other = dict(cad, layers=cad["layers"] + [dict(cad_model.LAYER_DEFAULTS, id="Z", name="Z")])
        self.assertEqual(cad_block.signature(other, ref), before)
        changed = dict(cad, layers=[cad["layers"][0], dict(cad["layers"][1], color="#ffff00"), cad["layers"][2]])
        self.assertNotEqual(cad_block.signature(changed, ref), before)


class NativeImportTest(unittest.TestCase):
    def test_inserts_kept_as_blocks_match_the_exploded_geometry(self):
        import tempfile
        from pathlib import Path
        import fm_board  # noqa: F401
        from fm_cad import cad_import
        ezdxf = __import__("ezdxf")
        doc = ezdxf.new("R2018")
        doc.header["$INSUNITS"] = 0
        block = doc.blocks.new("B", base_point=(5, 0))
        block.add_line((5, 0), (15, 0))
        block.add_circle((10, 5), 2)
        inner = doc.blocks.new("IN")
        inner.add_line((0, 0), (0, 3))
        block.add_blockref("IN", (15, 0), dxfattribs={"rotation": 90})
        msp = doc.modelspace()
        msp.add_blockref("B", (100, 0), dxfattribs={"rotation": 30, "xscale": 2, "yscale": 2})
        msp.add_blockref("B", (0, 100), dxfattribs={"xscale": -1})
        path = Path(tempfile.mkdtemp()) / "blocs.dxf"
        doc.saveas(path)
        flat, _r = cad_import.read_drawing(path, native_blocks=False)
        kept, report = cad_import.read_drawing(path, native_blocks=True)
        self.assertEqual(report["blocks"], 2)
        refs = [i for i in kept["items"] if i["type"] == "cad_insert"]
        self.assertEqual(len(refs), 2)
        cad = kept["page"]["cad"]

        def segs(prims):
            out = set()
            for p in prims:
                if p[0] == "segment":
                    out.add(tuple(sorted((rnd(p[1]), rnd(p[2])))))
                else:
                    out.add(("arc", rnd(p[1]), round(p[2], 6)))
            return out
        native = set().union(*(segs(cad_block.parts(cad, r)["prims"]) for r in refs))
        exploded = set()
        for item in flat["items"]:
            exploded |= segs(cad_shapes.prims(item["type"], item))
        self.assertEqual(native, exploded)

    def test_byblock_entities_are_kept_and_written_back(self):
        import tempfile
        from pathlib import Path
        import fm_board  # noqa: F401
        from fm_cad import cad_import
        ezdxf = __import__("ezdxf")
        doc = ezdxf.new("R2018")
        block = doc.blocks.new("C")
        block.add_line((0, 0), (1, 0), dxfattribs={"color": 0, "lineweight": -2})
        block.add_line((0, 1), (1, 1), dxfattribs={"color": 1})
        doc.modelspace().add_blockref("C", (0, 0), dxfattribs={"color": 3})
        path = Path(tempfile.mkdtemp()) / "parbloc.dxf"
        doc.saveas(path)
        kept, _report = cad_import.read_drawing(path, native_blocks=True)
        items = kept["page"]["cad"]["blocks"]["C"]["items"]
        self.assertEqual([i["color"] for i in items], [cad_model.BYBLOCK, "#ff0000"])
        self.assertEqual(items[0]["lineweight"], cad_model.BYBLOCK)
        (ref,) = [i for i in kept["items"] if i["type"] == "cad_insert"]
        inks = sorted(c for c, _w in cad_block.parts(kept["page"]["cad"], ref)["strokes"])
        self.assertEqual(inks, ["#00ff00", "#ff0000"])


class BlocksOnTheBoardTest(CadBoardCase):
    def kinds(self, kind):
        return [i for i in self.ctl.cad_items() if i.kind == kind]

    def select(self, *items):
        self.pane.scene.clearSelection()
        for item in items:
            item.setSelected(True)

    def test_block_insert_transform_explode(self):
        a = self.line((0, 0), (10, 0))
        b = self.line((10, 0), (10, 10))
        self.select(a, b)
        self.type("B", "PORTE", "0,0")
        self.assertEqual(self.kinds("cad_line"), [])                                   # convertis en bloc
        (ref,) = self.kinds("cad_insert")
        self.assertIn("PORTE", cad_model.page_cad(self.pane.scene.page).get("blocks", {}))
        self.assertEqual(len(ref.prims()), 2)
        self.ctl.undo()
        self.assertEqual(len(self.kinds("cad_line")), 2)                               # une etape
        self.assertEqual(self.kinds("cad_insert"), [])
        self.ctl.redo()
        self.type("I", "PORTE", "100,100", "2", "90")
        refs = self.kinds("cad_insert")
        self.assertEqual(len(refs), 2)
        big = next(r for r in refs if r.data["scale"] == 2.0)
        ends = sorted(rnd(p) for prim in big.prims() for p in (prim[1], prim[2]))
        self.assertIn((100.0, 120.0), ends)                                             # tournee de 90, x2
        self.select(big)
        self.type("M", "0,0", "10,0")
        self.assertEqual(rnd(big.points()[0]), (110.0, 100.0))
        self.select(big)
        self.type("X")
        lines = self.kinds("cad_line")
        self.assertEqual(len(lines), 2)
        self.assertEqual(len(self.kinds("cad_insert")), 1)

    def test_redefine_updates_references_and_survives_save(self):
        a = self.line((0, 0), (10, 0))
        self.select(a)
        self.type("B", "R", "0,0")
        self.type("I", "R", "50,0", "", "")
        refs = self.kinds("cad_insert")
        self.assertEqual(len(refs), 2)
        c = self.line((0, 0), (0, 30))
        self.select(c)
        self.type("B", "R", "0,0")                                                    # redefini : une ligne verticale
        for ref in self.kinds("cad_insert"):
            ys = [p[2][1] for p in ref.prims()]
            self.assertIn(30.0, [round(y, 6) for y in ys])
        self.assertTrue(self.pane.save())
        data = cad_model.page_cad(self.pane.scene.page)
        self.assertEqual(len(data["blocks"]["R"]["items"]), 1)

    def test_export_writes_block_definitions_and_inserts(self):
        from fm_cad import cad_export
        ezdxf = __import__("ezdxf")
        a = self.line((0, 0), (10, 0))
        self.select(a)
        self.type("B", "PLAN", "0,0")
        self.type("I", "PLAN", "100,0", "2", "90")
        target = self.dir / "blocs.dxf"
        cad_export.export_dxf(self.pane.scene, target, "px" if "px" in cad_export.UNITS else "mm")
        doc = ezdxf.readfile(target)
        self.assertIn("PLAN", [b.name for b in doc.blocks])
        inserts = doc.modelspace().query("INSERT")
        self.assertEqual(len(inserts), 2)
        self.assertEqual(sorted(round(i.dxf.rotation) for i in inserts), [0, 90])

    def test_reference_draws_other_inks_and_follows_its_layers(self):
        cad = cad_model.copy_cad(cad_model.page_cad(self.pane.scene.page))
        cad["layers"] = list(cad["layers"]) + [dict(cad_model.LAYER_DEFAULTS, id="R", name="Rouge", color="#ff0000")]
        cad["blocks"] = {"K": {"base": [0, 0], "items": [
            {"type": "cad_line", "p1": [0, 0], "p2": [10, 0], "layer": "0", "color": "ByLayer"},
            {"type": "cad_line", "p1": [0, 5], "p2": [10, 5], "layer": "R", "color": "ByLayer"}]}}
        self.pane.scene.set_page({"cad": cad}, record=False)
        ref = self.ctl.create_entity("cad_insert", {"block": "K", "pos": [0.0, 0.0]})
        self.ctl.commit_created([ref], "test")
        main, others = ref._inks()
        self.assertEqual(len(main), 1)
        self.assertEqual([(c, len(p)) for c, _w, p in others], [("#ff0000", 1)])
        self.assertEqual(len(ref.prims()), 2)                                    # accrochage : tout le bloc
        cad = cad_model.copy_cad(cad_model.page_cad(self.pane.scene.page))
        cad["layers"] = [dict(l, color="#00ff00") if l["id"] == "R" else l for l in cad["layers"]]
        self.pane.scene.set_page({"cad": cad}, record=False)
        self.assertEqual([c for c, _w, _p in ref._inks()[1]], ["#00ff00"])   # couleur du calque suivie
        cad = cad_model.copy_cad(cad_model.page_cad(self.pane.scene.page))
        cad["layers"] = [dict(l, visible=False) if l["id"] == "R" else l for l in cad["layers"]]
        self.pane.scene.set_page({"cad": cad}, record=False)
        self.assertEqual(ref._inks()[1], [])                                     # calque masque : plus dessine


if __name__ == "__main__":
    unittest.main()
