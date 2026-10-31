"""fm_font, AXES DE VARIATION : édition des axes, CARTES (avar), positions des masters, instances sur plusieurs
axes ; vérification indépendante de la police variable par fontTools (avar, fvar) et HarfBuzz (chasse à une
position utilisateur)."""
import os as _os, sys as _sys  # jamais les vrais réglages / presets de l'utilisateur (tests/_isolate.py)
_sys.path.insert(0, _os.path.dirname(_os.path.abspath(__file__)))
import _isolate  # noqa: E402,F401
import shutil
import tempfile
import unittest
from pathlib import Path

from fm_font import axes, shapes  # noqa: E402
from fm_font.document import FontProject, ProjectError  # noqa: E402


def _two_masters():
    """Deux masters « Light » / « Bold » ; A a une chasse de 500 (Light) et 680 (Bold)."""
    p = FontProject.new("Axes", styles=("Light", "Bold"))
    p.add_glyph("A")
    for m, width in zip(p.masters, (500, 680)):
        g = m.font["A"]
        g.width = width
        g.contours.append(shapes.rectangle(50, 0, width - 50, 700))
    return p


class AxesModelTest(unittest.TestCase):
    def test_parse_and_format_round_trip(self):
        specs = axes.parse_axes("Weight wght 100 100 900 carte 100>20 400>80 900>200 ; Width wdth 75 100 125")
        self.assertEqual(specs[0]["map"], [(100, 20), (400, 80), (900, 200)])
        self.assertEqual(specs[1]["tag"], "wdth")
        p = _two_masters()
        axes.set_axes(p, specs)
        self.assertEqual(axes.parse_axes(axes.format_axes(p.axes)), specs)
        for bad in ("Weight wght 100", "Weight wght 100 400 900 carte 100-20",
                    "Weight wght 900 400 100", "Weight wghtt 100 400 900"):
            with self.assertRaises(ProjectError, msg=bad):
                axes.set_axes(p, axes.parse_axes(bad))

    def test_map_keeps_user_positions_and_undo(self):
        p = _two_masters()                                       # Weight 400–700, masters à 400 et 700
        axes.set_axes(p, axes.parse_axes("Weight wght 100 400 900 carte 100>20 400>80 900>200"))
        self.assertEqual(p.masters[0].location, {"Weight": 80})      # 400 utilisateur -> 80 conception
        self.assertEqual(p.masters[1].location, {"Weight": 152})     # 700 -> 80 + 300/500 × 120
        axes.set_master_location(p, 0, axes.parse_location(p, "Weight=20"))
        axes.set_master_location(p, 1, axes.parse_location(p, "wght=200"))
        with self.assertRaises(ProjectError):
            axes.set_master_location(p, 1, {"Weight": 20})           # déjà occupé par Light
        with self.assertRaises(ProjectError):
            axes.set_master_location(p, 1, {"Weight": 500})          # hors de l'axe (conception 20–200)
        with self.assertRaises(ProjectError):                        # la carte doit donner min, défaut, max
            axes.set_axes(p, axes.parse_axes("Weight wght 100 400 900 carte 100>20 900>200"))
        self.assertEqual(axes.format_location(p, p.masters[1].location, user=True), "Weight=900")
        p.undo.undo()
        p.undo.undo()
        p.undo.undo()
        self.assertEqual(p.axes[0].map, [])
        self.assertEqual([m.location for m in p.masters], [{"Weight": 400}, {"Weight": 700}])

    def test_added_axis_and_multi_axis_instances(self):
        p = _two_masters()
        axes.set_axes(p, axes.parse_axes("Weight wght 400 400 700 ; Width wdth 75 100 125"))
        self.assertEqual(p.masters[1].location, {"Weight": 700, "Width": 100})
        p.set_instances(axes.parse_instances(p, "Regular wght=400, Bold Condensed wght=700 wdth=75"))
        self.assertEqual([dict(i.location) for i in p.instances],
                         [{"Weight": 400, "Width": 100}, {"Weight": 700, "Width": 75}])
        self.assertEqual(axes.format_instances(p), "Regular Weight=400 Width=100, Bold Condensed Weight=700 Width=75")
        with self.assertRaises(ProjectError):
            axes.parse_instances(p, "Bold opsz=12")
        with self.assertRaises(ProjectError):
            axes.parse_instances(p, "Bold")

    def test_interpolation_and_instances_follow_the_map(self):
        p = _two_masters()
        axes.set_axes(p, axes.parse_axes("Weight wght 100 100 900 carte 100>20 400>80 900>200"))
        axes.set_master_location(p, 0, {"Weight": 20})
        axes.set_master_location(p, 1, {"Weight": 200})
        p.set_instances(axes.parse_instances(p, "Regular 400"))      # 400 utilisateur
        self.assertEqual(dict(p.instances[0].location), {"Weight": 80})
        self.assertEqual(axes.format_instances(p), "Regular 400")
        from fm_font.interpolation import interpolate_glyph
        self.assertEqual(interpolate_glyph(p, "A", {"Weight": 80}).width, 560)   # 500 + 180 / 3


class VariableAvarTest(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="fmfont_axes_"))

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_variable_font_has_avar_and_harfbuzz_agrees(self):
        p = _two_masters()
        axes.set_axes(p, axes.parse_axes("Weight wght 100 100 900 carte 100>20 400>80 900>200"))
        axes.set_master_location(p, 0, {"Weight": 20})
        axes.set_master_location(p, 1, {"Weight": 200})
        p.set_instances(axes.parse_instances(p, "Thin 100, Regular 400, Black 900"))
        ds = self.tmp / "Axes.designspace"
        p.save(ds)
        q = FontProject.open(ds)                                     # carte relue du Designspace
        self.assertEqual(q.axes[0].map, [(100, 20), (400, 80), (900, 200)])
        from fm_font.compile import export
        out = self.tmp / "Axes-VF.ttf"
        export(q, out, "variable-ttf")
        from fontTools.ttLib import TTFont
        tt = TTFont(out)
        self.assertIn("avar", tt)
        self.assertEqual([i.coordinates["wght"] for i in tt["fvar"].instances], [100, 400, 900])
        segment = tt["avar"].segments["wght"]
        self.assertAlmostEqual(segment[0.375], 1 / 3, places=3)      # 400 utilisateur -> 1/3 de l'axe dessiné
        import uharfbuzz as hb
        face = hb.Face(out.read_bytes())
        font = hb.Font(face)
        widths = {}
        for user in (100, 400, 900):
            font.set_variations({"wght": user})
            buf = hb.Buffer()
            buf.add_str("A")
            buf.guess_segment_properties()
            hb.shape(font, buf)
            widths[user] = buf.glyph_positions[0].x_advance
        self.assertEqual(widths, {100: 500, 400: 560, 900: 680})


if __name__ == "__main__":
    unittest.main()
