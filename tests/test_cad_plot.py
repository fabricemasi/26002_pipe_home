"""PRESENTATIONS et IMPRESSION du module CAD (fm_cad/cad_plot.py, cad_plot_ui.py, cad_commands_plot.py ;
2026-11-05) : mise en page (papier, orientation, echelle 1:N, fenetre), TRACEUP en PDF vectoriel a l'echelle exacte,
presentations d'un DWG importees."""
import os as _os, sys as _sys  # jamais les vrais reglages / presets de l'utilisateur (tests/_isolate.py)
_sys.path.insert(0, _os.path.dirname(_os.path.abspath(__file__)))
import _isolate  # noqa: E402,F401
import tempfile
import unittest
from pathlib import Path

from fm_cad import cad_model, cad_plot
from test_cad import CadBoardCase


class PurePlotTest(unittest.TestCase):
    def test_frame_at_scale_and_fit(self):
        mm = 96.0 / 25.4                                                     # unites du board par mm
        layout = cad_plot.clean({"name": "P", "paper": "A4", "landscape": True, "scale": 100, "margin": 10,
                                 "area": [0, 0, 10000 * mm, 5000 * mm]})    # 10 m x 5 m
        frame = cad_plot.plot_frame(layout, [0, 0, 1, 1])
        self.assertEqual(frame["paper"], (297.0, 210.0))
        self.assertAlmostEqual(frame["target"][2], 100.0)                    # 10 m au 1:100 = 100 mm
        self.assertAlmostEqual(frame["target"][3], 50.0)
        self.assertTrue(frame["fits"])
        fit = cad_plot.plot_frame(dict(layout, scale=0.0), [0, 0, 1, 1])
        self.assertAlmostEqual(fit["target"][2], 277.0)                      # largeur utile
        self.assertAlmostEqual(fit["scale"], 10000 / 277.0, places=6)
        self.assertEqual(cad_plot.parse_scale("1:50"), 50.0)
        self.assertEqual(cad_plot.parse_scale("ajuster"), 0.0)
        self.assertIsNone(cad_plot.parse_scale("x"))
        self.assertEqual(cad_plot.describe_scale(2.0), "1:2")
        self.assertEqual(cad_plot.paper_size(cad_plot.clean({"name": "Q", "paper": "500x300", "landscape": False})),
                         (300.0, 500.0))

    def test_layout_list_edits(self):
        cad = cad_plot.with_layout({}, dict(cad_plot.DEFAULT, name="A"))
        cad = cad_plot.with_layout(cad, dict(cad_plot.DEFAULT, name="B"))
        self.assertEqual([l["name"] for l in cad_plot.layouts(cad)], ["A", "B"])
        self.assertEqual(cad_plot.current(cad)["name"], "B")
        cad = cad_plot.without_layout(cad, "B")
        self.assertEqual(cad_plot.current(cad)["name"], "A")
        self.assertEqual(cad_plot.unique_name(cad), "Présentation1")


class LayoutImportTest(unittest.TestCase):
    def test_paper_layout_with_viewport(self):
        import fm_board  # noqa: F401
        from fm_cad import cad_import
        ezdxf = __import__("ezdxf")
        doc = ezdxf.new("R2018")
        doc.header["$INSUNITS"] = 4                                          # mm
        doc.modelspace().add_line((0, 0), (5000, 0))
        layout = doc.layouts.new("PLAN")
        layout.page_setup(size=(420, 297), margins=(10, 10, 10, 10), units="mm")
        layout.add_viewport(center=(210, 148.5), size=(400, 200), view_center_point=(2500, 1250), view_height=20000)
        path = Path(tempfile.mkdtemp()) / "presentation.dxf"
        doc.saveas(path)
        data, report = cad_import.read_drawing(path, native_blocks=False)
        found = cad_plot.layouts(data["page"]["cad"])
        plan = next(l for l in found if l["name"] == "PLAN")
        self.assertEqual(plan["paper"], "A3")
        self.assertTrue(plan["landscape"])
        self.assertAlmostEqual(plan["scale"], 100.0, places=3)               # 200 mm de papier = 20 000 mm
        self.assertGreaterEqual(report["layouts"], 1)


class PlotOnTheBoardTest(CadBoardCase):
    def test_pagesetup_then_plot_pdf(self):
        self.line((0, 0), (1000, 0))
        self.line((0, 0), (0, 500))
        self.type("PAGESETUP", "P", "A3", "E", "1:10", "F", "0,0", "1000,500", "")
        layout = cad_plot.current(cad_model.page_cad(self.pane.scene.page))
        self.assertEqual((layout["paper"], layout["scale"]), ("A3", 10.0))
        self.assertIsNotNone(layout["area"])
        self.ctl.undo()                                                      # une etape
        self.assertIsNone(cad_plot.current(cad_model.page_cad(self.pane.scene.page)))
        self.ctl.redo()
        target = self.dir / "plan.pdf"
        self.type("PLOT", "", str(target))
        self.assertTrue(target.exists())
        data = target.read_bytes()
        self.assertTrue(data.startswith(b"%PDF"))
        self.assertGreater(len(data), 500)
        from PySide6.QtPdf import QPdfDocument
        pdf = QPdfDocument()
        pdf.load(str(target))
        size = pdf.pagePointSize(0)                                          # A3 paysage en points
        self.assertAlmostEqual(size.width(), 420 / 25.4 * 72, delta=1.0)
        self.assertAlmostEqual(size.height(), 297 / 25.4 * 72, delta=1.0)


if __name__ == "__main__":
    unittest.main()
