"""LIGNES DE CONSTRUCTION du module CAD (XLINE / RAY : fm_cad/cad_xline.py, fm_cad/cad_commands_xline.py ;
2026-11-05) : decoupe a la vue, commandes (Hor / Ang / Bissectrice / Decalage), ajuster (-> demi-droites), hors des
lots / du GPU / de l'etendue, import et export."""
import os as _os, sys as _sys  # jamais les vrais reglages / presets de l'utilisateur (tests/_isolate.py)
_sys.path.insert(0, _os.path.dirname(_os.path.abspath(__file__)))
import _isolate  # noqa: E402,F401
import tempfile
import unittest
from pathlib import Path

from fm_cad import cad_xline
from test_cad import CadBoardCase


def rnd(p):
    return tuple(round(v, 6) + 0.0 for v in p)


class PureXlineTest(unittest.TestCase):
    def test_clip_and_pieces(self):
        data = {"p1": [0, 0], "p2": [1, 1]}
        a, b = cad_xline.clip("cad_xline", data, (-10, -5, 10, 5))
        self.assertEqual((rnd(a), rnd(b)), ((-5, -5), (5, 5)))
        a, b = cad_xline.clip("cad_ray", data, (-10, -5, 10, 5))
        self.assertEqual(rnd(a), (0, 0))                                         # demi-droite : depuis sa base
        self.assertIsNone(cad_xline.clip("cad_ray", {"p1": [0, 0], "p2": [-1, 0]}, (5, -1, 9, 1)))
        start, end = cad_xline.ends("cad_xline", data)
        kind, geometry = cad_xline.piece_entity("cad_xline", data, [("segment", start, (3.0, 3.0))])
        self.assertEqual(kind, "cad_ray")
        self.assertEqual(rnd(geometry["p1"]), (3, 3))
        self.assertLess(geometry["p2"][0], 3)                                    # vers le bout au loin
        kind, _g = cad_xline.piece_entity("cad_xline", data, [("segment", (1.0, 1.0), (2.0, 2.0))])
        self.assertEqual(kind, "cad_line")


class ImportExportTest(unittest.TestCase):
    def test_xline_and_ray_round_trip(self):
        import fm_board  # noqa: F401
        from fm_cad import cad_import
        ezdxf = __import__("ezdxf")
        doc = ezdxf.new("R2018")
        doc.header["$INSUNITS"] = 0
        doc.modelspace().add_xline((1, 2), (1, 0))
        doc.modelspace().add_ray((0, 0), (0, 1))
        path = Path(tempfile.mkdtemp()) / "construction.dxf"
        doc.saveas(path)
        data, report = cad_import.read_drawing(path, native_blocks=False)
        self.assertEqual(report["ignored"], {})
        kinds = sorted(i["type"] for i in data["items"])
        self.assertEqual(kinds, ["cad_ray", "cad_xline"])
        xline = next(i for i in data["items"] if i["type"] == "cad_xline")
        self.assertEqual((rnd(xline["p1"]), rnd(xline["p2"])), ((1, 2), (2, 2)))


class OnTheBoardTest(CadBoardCase):
    def kinds(self, kind):
        return [i for i in self.ctl.cad_items() if i.kind == kind]

    def test_commands_trim_and_display(self):
        self.type("XLINE", "0,0", "10,0", "0,10", "")                          # deux droites, une etape
        self.assertEqual(len(self.kinds("cad_xline")), 2)
        self.ctl.undo()
        self.assertEqual(self.kinds("cad_xline"), [])
        self.ctl.redo()
        self.type("XLINE", "H", "0,50", "")
        self.type("RAY", "0,0", "-10,-10", "")
        xlines = self.kinds("cad_xline")
        self.assertEqual(len(xlines), 3)
        (ray,) = self.kinds("cad_ray")
        for item in xlines + [ray]:
            self.assertTrue(item.INFINITE)
            self.assertIsNone(item._batch)                                     # hors des lots
            self.assertLess(item.scene_bounds().width(), 100)                  # hors de l'etendue
        horizontal = next(i for i in xlines if rnd(i.points()[1]) == (1.0, 50.0))
        self.assertIsNotNone(horizontal._text_item)
        self.type("XLINE", "D", "5")                                           # Decalage de 5
        self.ctl.command.picked([horizontal])
        self.ctl.command.point((0.0, 60.0))
        self.type("")
        self.assertEqual(len(self.kinds("cad_xline")), 4)
        offset = [i for i in self.kinds("cad_xline") if abs(i.points()[0][1] - 55.0) < 1e-6]
        self.assertEqual(len(offset), 1)
        line = self.line((5, -20), (5, 80))
        self.assertIsNotNone(line)
        self.type("TR")                                                        # ajuster la droite horizontale
        self.ctl.last_pick_doc = (0.0, 50.0)                                   # morceau de gauche retire
        self.ctl.command.picked([horizontal])
        rays = [r for r in self.kinds("cad_ray") if abs(r.points()[0][1] - 50.0) < 1e-6]
        self.assertEqual(len(rays), 1)                                         # droite -> demi-droite
        self.assertEqual(rnd(rays[0].points()[0]), (5.0, 50.0))
        self.assertGreater(rays[0].points()[1][0], 5.0)


if __name__ == "__main__":
    unittest.main()
