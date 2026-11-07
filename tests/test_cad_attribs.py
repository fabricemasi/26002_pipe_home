"""ATTRIBUTS de bloc du module CAD (fm_cad/cad_attrib.py, fm_cad/cad_commands_attribs.py ; 2026-11-05) : ATTDEF,
INSERER qui demande les valeurs, ATTEDIT, affichage par la reference, import (ATTDEF / ATTRIB d'un DXF) et export."""
import os as _os, sys as _sys  # jamais les vrais reglages / presets de l'utilisateur (tests/_isolate.py)
_sys.path.insert(0, _os.path.dirname(_os.path.abspath(__file__)))
import _isolate  # noqa: E402,F401
import tempfile
import unittest
from pathlib import Path

from fm_cad import cad_attrib, cad_block, cad_model
from test_cad import CadBoardCase


class PureAttribTest(unittest.TestCase):
    def definition(self):
        return {"base": [0, 0], "items": [
            {"type": "cad_text", "pos": [0, 0], "text": "NUM", "height": 1.0,
             "attdef": {"tag": "num", "prompt": "Numéro", "default": "1"}},
            {"type": "cad_text", "pos": [0, 2], "text": "CACHE", "height": 1.0,
             "attdef": {"tag": "CACHE", "default": "x", "invisible": True}},
            {"type": "cad_text", "pos": [0, 4], "text": "FIXE", "height": 1.0,
             "attdef": {"tag": "FIXE", "default": "A", "constant": True}}]}

    def test_values_and_display(self):
        d = self.definition()
        self.assertEqual([a["tag"] for a in cad_attrib.asked(d)], ["NUM", "CACHE"])     # constante : jamais demandee
        self.assertEqual(cad_attrib.values_for(d, {"num": "12"}), {"NUM": "12", "CACHE": "x"})
        cad = {"blocks": {"P": d}}
        texts = cad_block.parts(cad, {"block": "P", "attribs": {"NUM": "12"}})["texts"]
        self.assertEqual(sorted(t["text"] for t in texts), ["12", "A"])                  # invisible : rien
        self.assertEqual(sorted(t["text"] for t in cad_block.parts(cad, {"block": "P"})["texts"]), ["1", "A"])
        self.assertEqual(cad_attrib.clean_tag(" mon tag! "), "MON_TAG")

    def test_normalize_keeps_fields(self):
        text = cad_model.normalize_entity({"type": "cad_text", "attdef": {"tag": "a"}})
        self.assertEqual(text["attdef"]["tag"], "A")
        ref = cad_model.normalize_entity({"type": "cad_insert", "attribs": {"a": 3}})
        self.assertEqual(ref["attribs"], {"A": "3"})


class AttribImportTest(unittest.TestCase):
    def test_attdef_and_attrib_values_are_kept_on_the_reference(self):
        import fm_board  # noqa: F401
        from fm_cad import cad_import
        ezdxf = __import__("ezdxf")
        doc = ezdxf.new("R2018")
        block = doc.blocks.new("PORTE")
        block.add_line((0, 0), (10, 0))
        block.add_attdef("NUM", (0, 2), "0", dxfattribs={"height": 1.0, "prompt": "Numéro"})
        msp = doc.modelspace()
        ref = msp.add_blockref("PORTE", (100, 0))
        ref.add_auto_attribs({"NUM": "42"})
        moved = msp.add_blockref("PORTE", (200, 0))
        attrib = moved.add_attrib("NUM", "7", (250, 50), dxfattribs={"height": 1.0})
        self.assertIsNotNone(attrib)
        path = Path(tempfile.mkdtemp()) / "attributs.dxf"
        doc.saveas(path)
        data, _report = cad_import.read_drawing(path, native_blocks=True)
        refs = sorted((i for i in data["items"] if i["type"] == "cad_insert"), key=lambda i: i["pos"][0])
        self.assertEqual(refs[0]["attribs"], {"NUM": "42"})
        self.assertEqual(refs[1]["attribs"], {"NUM": ""})                      # deplace : un texte a part
        self.assertIn("7", [i.get("text") for i in data["items"] if i["type"] == "cad_text"])
        definition = data["page"]["cad"]["blocks"]["PORTE"]
        self.assertEqual([a["tag"] for a in cad_attrib.attdefs(definition)], ["NUM"])


class AttribsOnTheBoardTest(CadBoardCase):
    def kinds(self, kind):
        return [i for i in self.ctl.cad_items() if i.kind == kind]

    def select(self, *items):
        self.pane.scene.clearSelection()
        for item in items:
            item.setSelected(True)

    def test_attdef_block_insert_attedit_export(self):
        a = self.line((0, 0), (10, 0))
        self.type("ATTDEF", "", "REF", "Reference de la piece", "P0", "0,5", "2", "0")
        (attdef,) = self.kinds("cad_text")
        self.assertEqual(attdef.data["text"], "REF")
        self.assertEqual(attdef.data["attdef"]["prompt"], "Reference de la piece")  # (QTest : pas d accents)
        self.ctl.undo()
        self.assertEqual(self.kinds("cad_text"), [])                             # une etape
        self.ctl.redo()
        (attdef,) = self.kinds("cad_text")
        self.select(a, attdef)
        self.type("B", "PIECE", "0,0")
        self.type("I", "PIECE", "100,0", "", "", "A12")
        ref = next(r for r in self.kinds("cad_insert") if r.data["pos"] == [100.0, 0.0])
        self.assertEqual(ref.data["attribs"], {"REF": "A12"})
        self.assertEqual([t["text"] for t in ref.block_parts()["texts"]], ["A12"])
        self.select(ref)
        self.type("ATTEDIT", "B7")
        self.assertEqual(ref.data["attribs"], {"REF": "B7"})
        self.assertEqual([t["text"] for t in ref.block_parts()["texts"]], ["B7"])
        self.ctl.undo()
        self.assertEqual(ref.data["attribs"], {"REF": "A12"})
        from fm_cad import cad_export
        ezdxf = __import__("ezdxf")
        target = self.dir / "attributs.dxf"
        cad_export.export_dxf(self.pane.scene, target, "px" if "px" in cad_export.UNITS else "mm")
        doc = ezdxf.readfile(target)
        self.assertEqual([e.dxf.tag for e in doc.blocks.get("PIECE").query("ATTDEF")], ["REF"])
        texts = sorted(att.dxf.text for ins in doc.modelspace().query("INSERT") for att in ins.attribs)
        self.assertIn("A12", texts)


if __name__ == "__main__":
    unittest.main()
