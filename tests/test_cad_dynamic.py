"""BLOCS DYNAMIQUES du module CAD (etats de visibilite : fm_cad/cad_block.py, fm_cad/cad_commands_dynamic.py ;
2026-11-05) : etats, reference qui montre son etat, commande ETATVIS (Nouveau / Masquer / Renommer / Supprimer),
DECOMPOSER, nom du bloc dynamique d'un bloc anonyme importe."""
import os as _os, sys as _sys  # jamais les vrais reglages / presets de l'utilisateur (tests/_isolate.py)
_sys.path.insert(0, _os.path.dirname(_os.path.abspath(__file__)))
import _isolate  # noqa: E402,F401
import unittest

from fm_cad import cad_block, cad_model
from test_cad import CadBoardCase


def cad():
    return {"blocks": {"P": {"base": [0, 0], "items": [
        {"type": "cad_line", "p1": [0, 0], "p2": [10, 0]},
        {"type": "cad_line", "p1": [0, 5], "p2": [10, 5]},
        {"type": "cad_line", "p1": [0, 9], "p2": [10, 9]}],
        "states": {"Ouvert": [2], "Fermé": [0, 1]}}}}


class PureStateTest(unittest.TestCase):
    def test_reference_shows_its_state(self):
        c = cad()
        ys = lambda ref: sorted(p[1][1] for p in cad_block.parts(c, ref)["prims"])   # noqa: E731
        self.assertEqual(ys({"block": "P"}), [0.0, 5.0])                      # premier etat par defaut
        self.assertEqual(ys({"block": "P", "state": "Fermé"}), [9.0])
        self.assertEqual(ys({"block": "P", "state": "inconnu"}), [0.0, 5.0])
        self.assertEqual(cad_block.index_at(c, {"block": "P"}, (3.0, 9.2), 0.5), 2)   # etat ignore
        self.assertIsNone(cad_block.index_at(c, {"block": "P"}, (3.0, 20.0), 0.5))
        new = cad_block.with_states(c["blocks"]["P"], {"A": {0, 7}})
        self.assertEqual(new["states"], {"A": [0]})                           # rang hors du bloc : retire
        self.assertNotIn("states", cad_block.with_states(c["blocks"]["P"], {}))


class StatesOnTheBoardTest(CadBoardCase):
    def kinds(self, kind):
        return [i for i in self.ctl.cad_items() if i.kind == kind]

    def select(self, *items):
        self.pane.scene.clearSelection()
        for item in items:
            item.setSelected(True)

    def ys(self, ref):
        return sorted(round(p[1][1], 6) for p in ref.prims())

    def test_new_state_hide_rename_delete_explode(self):
        a = self.line((0, 0), (40, 0))
        b = self.line((0, 20), (40, 20))
        self.select(a, b)
        self.type("B", "VOLET", "0,0")
        (ref,) = self.kinds("cad_insert")
        self.select(ref)
        self.type("BVSTATE", "N", "Bas")
        self.ctl.command.point((20.0, 20.0))                                 # clic sur la ligne du haut : masquee
        APP_events()
        self.type("", "N", "Haut")                                           # copie de « Bas »
        self.ctl.command.point((20.0, 20.0))                                 # remontree
        self.ctl.command.point((20.0, 0.0))                                  # celle du bas masquee
        self.type("", "")
        self.assertIsNone(self.ctl.command)
        self.assertEqual(ref.data["state"], "Haut")
        self.assertEqual(self.ys(ref), [20.0])
        definition = cad_block.blocks(cad_model.page_cad(self.pane.scene.page))["VOLET"]
        self.assertEqual(list(cad_block.states(definition)), ["Bas", "Haut"])
        self.ctl.undo()                                                      # une etape
        self.assertNotIn("states", cad_block.blocks(cad_model.page_cad(self.pane.scene.page))["VOLET"])
        self.assertEqual(self.ys(ref), [0.0, 20.0])
        self.ctl.redo()
        self.assertEqual(self.ys(ref), [20.0])
        self.select(ref)
        self.type("BVSTATE", "Bas")
        self.assertEqual(self.ys(ref), [0.0])
        self.type("R", "Ferme", "")
        self.assertEqual(ref.data["state"], "Ferme")
        self.select(ref)
        self.type("X")                                                       # decompose : l'etat montre seul
        self.assertEqual([round(l.points()[0][1], 6) for l in self.kinds("cad_line")], [0.0])


def APP_events():
    from PySide6.QtWidgets import QApplication
    QApplication.processEvents()


class DynamicImportTest(unittest.TestCase):
    def test_anonymous_variant_keeps_the_dynamic_name(self):
        import tempfile
        from pathlib import Path
        import fm_board  # noqa: F401
        from fm_cad import cad_import
        ezdxf = __import__("ezdxf")
        doc = ezdxf.new("R2018")
        original = doc.blocks.new("PORTE_DYN")
        original.add_line((0, 0), (10, 0))
        variant = doc.blocks.new_anonymous_block("U")
        variant.add_line((0, 0), (20, 0))
        variant.block_record.set_xdata("AcDbBlockRepBTag", [(1070, 1), (1005, original.block_record.dxf.handle)])
        doc.appids.new("AcDbBlockRepBTag")
        doc.modelspace().add_blockref(variant.name, (0, 0))
        path = Path(tempfile.mkdtemp()) / "dynamique.dxf"
        doc.saveas(path)
        data, _report = cad_import.read_drawing(path, native_blocks=True)
        definition = data["page"]["cad"]["blocks"][variant.name]
        self.assertEqual(definition.get("dynamic"), "PORTE_DYN")


if __name__ == "__main__":
    unittest.main()
