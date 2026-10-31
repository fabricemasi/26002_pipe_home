"""fm_font, POLICES COULEUR (COLR v0 / CPAL), HINTING (ttfautohint), INSTANCES statiques et CLASSES de crénage
depuis l'interface : modèle, export, relecture indépendante par fontTools et HarfBuzz."""
import os as _os, sys as _sys  # jamais les vrais réglages / presets de l'utilisateur (tests/_isolate.py)
_sys.path.insert(0, _os.path.dirname(_os.path.abspath(__file__)))
import _isolate  # noqa: E402,F401
import shutil
import tempfile
import unittest
from pathlib import Path

from fontTools.ttLib import TTFont

from fm_font import color, hinting, kerning, shapes  # noqa: E402
from fm_font.compile import CompileError, export  # noqa: E402
from fm_font.document import FontProject  # noqa: E402


def _project(styles=("Regular",)):
    p = FontProject.new("Couleur", styles=styles)
    for name in ("o", "A", "A.rouge", "A.bleu", "V"):
        p.add_glyph(name)
    for i, m in enumerate(p.masters):
        for name in ("A", "A.rouge", "A.bleu", "V"):
            m.font[name].contours.append(shapes.rectangle(50, 0, 450 + 40 * i, 700))
        m.font["o"].contours.append(shapes.ellipse(40, -10, 500 + 40 * i, 510))
    return p


class ColorHintingTest(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="fmfont_color_"))

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_palette_and_layers_compile_to_colr_cpal(self):
        p = _project()
        color.set_palette(p, color.parse_palette("#ff0000 #0000ff80"))
        self.assertEqual(color.palette(p.font), ["#ff0000", "#0000ff80"])
        color.set_layers(p, "A", color.parse_layers("A.rouge:0, A.bleu:1"))
        self.assertEqual(color.layers(p.font, "A"), [("A.rouge", 0), ("A.bleu", 1)])
        with self.assertRaises(color.ColorError):
            color.set_layers(p, "A", [("A.vert", 0)])
        with self.assertRaises(color.ColorError):
            color.set_layers(p, "A", [("A.rouge", 5)])
        with self.assertRaises(color.ColorError):
            color.parse_palette("#12")
        path = self.tmp / "Couleur.ufo"
        p.save(path)
        q = FontProject.open(path)                                       # gardé dans la lib de l'UFO
        self.assertEqual(color.layers(q.font, "A"), [("A.rouge", 0), ("A.bleu", 1)])
        out = self.tmp / "Couleur.ttf"
        export(q, out)
        tt = TTFont(out)
        self.assertEqual([(l.name, l.colorID) for l in tt["COLR"].ColorLayers["A"]], [("A.rouge", 0), ("A.bleu", 1)])
        self.assertEqual(len(tt["CPAL"].palettes[0]), 2)
        p.undo.undo()
        self.assertEqual(color.layers(p.font, "A"), [])

    @unittest.skipUnless(hinting.available(), "ttfautohint absent")
    def test_hinted_ttf_export(self):
        p = _project()
        out = self.tmp / "Hint.ttf"
        export(p, out, "ttf-hinted")
        tt = TTFont(out)
        self.assertIn("fpgm", tt)
        self.assertIn("prep", tt)
        out2 = self.tmp / "Hint.woff2"
        export(p, out2, "woff2-hinted")
        self.assertEqual(TTFont(out2).flavor, "woff2")

    def test_static_instance_export(self):
        p = _project(("Regular", "Bold"))
        out = self.tmp / "Mid.otf"
        export(p, out, "otf", instance={"Weight": 550})
        tt = TTFont(out)
        self.assertEqual(tt["hmtx"]["A"][0], round(600))
        from fontTools.pens.boundsPen import BoundsPen
        pen = BoundsPen(tt.getGlyphSet())
        tt.getGlyphSet()["A"].draw(pen)
        self.assertEqual(round(pen.bounds[2]), 470)                     # 450 -> 490 à mi-chemin
        self.assertIn("Instance", tt["name"].getBestSubFamilyName())
        C_ = p.masters[1].font["A"].contours[0]
        del C_.points[0]
        with self.assertRaises(CompileError):
            export(p, self.tmp / "x.otf", "otf", instance={"Weight": 500})


class InstancesTest(unittest.TestCase):
    def test_named_instances_saved_and_in_variable_font(self):
        from fm_font.compile import compile_variable
        from fm_font.document import ProjectError
        p = _project(("Regular", "Bold"))
        p.set_instances([("Regular", {"Weight": 400}), ("Medium", {"Weight": 550}), ("Bold", {"Weight": 700})])
        with self.assertRaises(ProjectError):
            p.set_instances([("Trop", {"Weight": 950})])
        tmp = Path(tempfile.mkdtemp(prefix="fmfont_inst_"))
        try:
            p.save(tmp / "Fam.designspace")
            q = FontProject.open(tmp / "Fam.designspace")
            self.assertEqual([i.styleName for i in q.instances], ["Regular", "Medium", "Bold"])
            tt = compile_variable(q)
            self.assertEqual([i.coordinates["wght"] for i in tt["fvar"].instances], [400, 550, 700])
        finally:
            shutil.rmtree(tmp, ignore_errors=True)
        p.undo.undo()
        self.assertEqual(p.instances, [])


class KerningClassesFromGridTest(unittest.TestCase):
    def test_class_from_selection(self):
        from fm_font.actions import kerning_class
        p = _project()
        kerning_class(p, 1, ["A", "V"])
        self.assertEqual(p.font.groups["public.kern1.A"], ["A", "V"])
        kerning_class(p, 2, ["V"])
        self.assertEqual(p.font.groups["public.kern2.V"], ["V"])
        kerning_class(p, 0, ["V"])                                       # retirer de ses classes
        self.assertNotIn("V", p.font.groups["public.kern1.A"])
        self.assertNotIn("public.kern2.V", p.font.groups)
        self.assertEqual(kerning.group_of(p.font, "A", 1), "public.kern1.A")


if __name__ == "__main__":
    unittest.main()
