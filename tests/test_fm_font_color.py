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

    def test_colr_v1_gradients_follow_the_drawing(self):
        p = _project()
        color.set_palette(p, color.parse_palette("#ff0000 #0000ff #00ff00"))
        pairs = color.parse_layers("A.rouge:0, A.bleu:lin(0,1), V:lin(1,2,0), o:rad(2,0)")
        self.assertEqual(pairs[1], ("A.bleu", ("lin", 0, 1, 90.0)))
        with self.assertRaises(color.ColorError):
            color.parse_layers("A.bleu:lin(0)")
        with self.assertRaises(color.ColorError):
            color.set_layers(p, "A", [("A.bleu", ("lin", 0, 7, 90.0))])          # couleur hors palette
        color.set_layers(p, "A", pairs)
        self.assertEqual(color.format_layers(color.layers(p.font, "A")),
                         "A.rouge:0, A.bleu:lin(0,1), V:lin(1,2,0), o:rad(2,0)")
        path = self.tmp / "Degrades.ufo"
        p.save(path)
        q = FontProject.open(path)                                       # description gardée dans la lib
        self.assertEqual(color.layers(q.font, "A"), pairs)
        # le dessin du calque change APRÈS la pose du dégradé : la compilation suit le nouveau dessin
        q.font["A.bleu"].contours[0].points[2].y = 900
        q.font["A.bleu"].contours[0].points[3].y = 900
        out = self.tmp / "Degrades.ttf"
        export(q, out)
        tt = TTFont(out)
        colr = tt["COLR"]
        self.assertEqual(colr.version, 1)
        layers = colr.table.LayerList.Paint
        self.assertEqual([(l.Glyph, l.Paint.Format) for l in layers],
                         [("A.rouge", 2), ("A.bleu", 4), ("V", 4), ("o", 6)])
        lin = layers[1].Paint
        self.assertEqual((lin.x0, lin.y0, lin.x1, lin.y1), (250, 0, 250, 900))   # bas -> haut, boîte redessinée
        self.assertEqual([s.PaletteIndex for s in lin.ColorLine.ColorStop], [0, 1])
        horizontal = layers[2].Paint
        self.assertEqual((horizontal.y0, horizontal.y1), (350, 350))
        self.assertEqual(layers[3].Paint.r1, round(((500 - 40) ** 2 + 520 ** 2) ** 0.5 / 2))
        self.assertIn("CPAL", tt)
        self.assertEqual(q.font.lib[color.LAYERS_KEY]["A"]["Layers"][1]["Paint"]["y1"], 700)  # lib remise après
        color.set_layers(p, "A", color.parse_layers("A.rouge:0"))         # retour à l'aplat : COLR v0
        self.assertNotIn("A", p.font.lib.get(color.GRADIENTS_KEY, {}))
        self.assertEqual(p.font.lib[color.LAYERS_KEY]["A"], [["A.rouge", 0]])
        p.undo.undo()
        self.assertEqual(color.layers(p.font, "A"), pairs)

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

    @unittest.skipUnless(hinting.cff_available(), "afdko (otfautohint) absent")
    def test_hinted_cff_export(self):
        from fm_font import contours as C
        p = _project()
        p.add_glyph("l")
        p.font["l"].width = 300
        p.font["l"].contours.append(shapes.rectangle(110, 0, 196, 800))  # fût de 86
        p.add_glyph("O")
        outer = shapes.ellipse(40, -10, 660, 710)
        inner = shapes.ellipse(110, 62, 590, 638)                       # traverses de 72 en haut et en bas
        C.reverse(inner)
        p.font["O"].contours += [outer, inner]
        p.font["O"].width = 700
        p.font.renameGlyph("o", "o.old")                                 # « o » plein du jeu d'essai : écarté
        p.font.renameGlyph("O", "o")
        self.assertEqual(hinting.stems(p.font), (86, 72))
        out = self.tmp / "Hint.otf"
        export(p, out, "otf-hinted")
        top = TTFont(out)["CFF "].cff.topDictIndex[0]
        private = top.Private
        self.assertEqual(private.BlueValues[:2], [-12, 0])
        self.assertIn(500, private.BlueValues)                           # hauteur d'x
        self.assertEqual((private.StdVW, private.StdHW), (86, 72))
        program = top.CharStrings["l"]
        program.decompile()
        self.assertIn("vstem", [op for op in program.program if isinstance(op, str)])
        self.assertIsNone(p.font.info.postscriptBlueValues)              # source inchangée
        self.assertIsNone(p.font.info.postscriptStemSnapV)

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


class ColorPreviewTest(unittest.TestCase):
    def test_preview_paints_palette_colors_and_gradient(self):
        from PySide6.QtWidgets import QApplication
        from fm_font.preview import PreviewWidget
        from fm_font.render import PathCache
        QApplication.instance() or QApplication([])
        p = _project()
        p.add_glyph("B")
        p.font["B"].width = 500
        color.set_palette(p, color.parse_palette("#ff0000 #0000ff"))
        color.set_layers(p, "A", color.parse_layers("A.rouge:0"))
        color.set_layers(p, "B", color.parse_layers("A.bleu:lin(0,1)"))
        p.font["A"].width = 500
        preview = PreviewWidget(p, PathCache(p), {"typo_canvas_bg": "#ffffff", "typo_preview_size": 100})
        preview.resize(400, 200)
        preview.text = "AB"
        image = preview.grab().toImage()
        baseline = 16 + 80                                                # marge + ascendante × 0,1

        def rgb(x_units, y_units, advance=0):
            c = image.pixelColor(round(16 + (advance + x_units) * 0.1), round(baseline - y_units * 0.1))
            return c.red(), c.green(), c.blue()
        self.assertEqual(rgb(250, 350), (255, 0, 0))                      # A : aplat rouge (couleur 0)
        low, high = rgb(250, 30, 500), rgb(250, 670, 500)                 # B : dégradé rouge (bas) -> bleu (haut)
        self.assertGreater(low[0], 200)
        self.assertLess(low[2], 60)
        self.assertGreater(high[2], 200)
        self.assertLess(high[0], 60)
        preview.deleteLater()


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
