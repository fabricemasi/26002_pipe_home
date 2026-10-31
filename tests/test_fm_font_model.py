"""fm_font, MODÈLE sans Qt : projet, glyphes, contours Bézier, géométrie, composants / ancres, métriques, crénage,
features, sauvegarde atomique / réouverture, compilation, interpolation, variable, import, diagnostic.

Vérification INDÉPENDANTE du compilateur : les polices produites sont relues par fontTools (tables, cmap,
contours) et mises en forme par HarfBuzz (crénage, ligatures, marques)."""
import os as _os, sys as _sys  # jamais les vrais réglages / presets de l'utilisateur (tests/_isolate.py)
_sys.path.insert(0, _os.path.dirname(_os.path.abspath(__file__)))
import _isolate  # noqa: E402,F401

import math
import shutil
import tempfile
import unittest
from pathlib import Path

from fontTools.pens.recordingPen import RecordingPen
from fontTools.ttLib import TTFont

from fm_font import calligraphy, components, features, geometry, interpolation, kerning, metrics, shapes  # noqa: E402
from fm_font import contours as C  # noqa: E402
from fm_font.compile import CompileError, compile_static, compile_variable, export, to_bytes  # noqa: E402
from fm_font.document import FontProject, ProjectError, recover_interrupted_save  # noqa: E402
from fm_font.importer import import_binary, import_svg  # noqa: E402
from fm_font.shaping import Shaper  # noqa: E402
from fm_font.validation import BLOCKING, SUGGESTION, WARNING, diagnose  # noqa: E402


def _draw_rect(glyph, x0, y0, x1, y1):
    glyph.contours.append(shapes.rectangle(x0, y0, x1, y1))


def _family(styles=("Regular",)) -> FontProject:
    """Petite famille : H, n, o, e, acutecomb, f, i, f_i, A, V ; ancres top / _top."""
    project = FontProject.new("Essai Sans", styles=styles)
    for name in ("H", "n", "o", "e", "acutecomb", "f", "i", "f_i", "A", "V", "period"):
        project.add_glyph(name)
    for index, m in enumerate(project.masters):
        bold = 40 * index
        f = m.font
        _draw_rect(f["H"], 60, 0, 140 + bold, 700)
        _draw_rect(f["H"], 460 - bold, 0, 540, 700)
        _draw_rect(f["H"], 140 + bold, 320, 460 - bold, 400)
        f["H"].width = 600
        _draw_rect(f["n"], 60, 0, 130 + bold, 500)
        _draw_rect(f["n"], 400 - bold, 0, 470, 500)
        f["n"].width = 530
        f["o"].contours.append(shapes.ellipse(40, -10, 500 + bold, 510))
        f["o"].width = 540 + bold
        f["e"].contours.append(shapes.ellipse(40, -10, 480, 510))
        f["e"].width = 520
        components.set_anchor(f["e"], "top", 260, 520)
        components.set_anchor(f["o"], "top", 270, 520)
        f["acutecomb"].contours.append(shapes.polygon(0, 620, 60, 3))
        f["acutecomb"].width = 0
        components.set_anchor(f["acutecomb"], "_top", 0, 540)
        for g in ("f", "i", "f_i", "period"):
            _draw_rect(f[g], 50, 0, 120 + bold, 600)
        f["f_i"].width = 700
        f["A"].contours.append(C.new_contour([(20, 0, "line"), (580, 0, "line"), (300, 700, "line")]))
        f["V"].contours.append(C.new_contour([(300, 0, "line"), (580, 700, "line"), (20, 700, "line")]))
        f["A"].width = f["V"].width = 600
    return project


class ProjectTest(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="fmfont_"))

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_new_project_has_metrics_notdef_and_space(self):
        p = FontProject.new("Ma Famille", upm=2048, ascender=1600, descender=-448, cap_height=1400,
                            x_height=1000, italic_angle=-12)
        info = p.font.info
        self.assertEqual((info.unitsPerEm, info.ascender, info.descender, info.capHeight, info.xHeight,
                          info.italicAngle), (2048, 1600, -448, 1400, 1000, -12))
        self.assertEqual(p.glyph_order()[:2], [".notdef", "space"])
        self.assertEqual(len(p.font[".notdef"].contours), 2)

    def test_glyph_create_rectangle_edit_save_reopen(self):
        """Tranche de base : créer un glyphe, dessiner un rectangle, modifier ses points, enregistrer, rouvrir."""
        p = FontProject.new("Essai")
        p.add_glyph("A")
        self.assertEqual(p.font["A"].unicodes, [0x41])
        token = p.begin_edit("A")
        p.font["A"].contours.append(shapes.rectangle(100, 0, 500, 700))
        p.end_edit(token, "Rectangle")
        token = p.begin_edit("A")
        geometry.move_points(p.font["A"], {(0, 2)}, 25, 10)
        p.end_edit(token, "Déplacer")
        self.assertTrue(p.is_dirty())
        path = self.tmp / "Essai.ufo"
        p.save(path)
        self.assertFalse(p.is_dirty())
        q = FontProject.open(path)
        pts = [(pt.x, pt.y, pt.type) for pt in q.font["A"].contours[0]]
        self.assertEqual(pts, [(100, 0, "line"), (500, 0, "line"), (525, 710, "line"), (100, 700, "line")])
        self.assertEqual(q.glyph_order(), [".notdef", "space", "A"])

    def test_undo_redo_glyph_ops(self):
        p = FontProject.new("Essai")
        p.add_glyph("B")
        p.add_glyph("C")
        p.rename_glyph("C", "Cbis")
        self.assertIn("Cbis", p.font)
        p.undo.undo()
        self.assertIn("C", p.font)
        p.delete_glyphs(["B"])
        self.assertNotIn("B", p.font)
        p.undo.undo()
        self.assertIn("B", p.font)
        dup = p.duplicate_glyph("B")
        self.assertEqual((dup, p.font[dup].unicodes), ("B.copy", []))
        p.undo.undo()
        self.assertNotIn(dup, p.font)
        p.undo.redo()
        self.assertIn(dup, p.font)
        with self.assertRaises(ProjectError):
            p.add_glyph("B")
        with self.assertRaises(ProjectError):
            p.set_unicodes("C", [0x42])           # déjà à B

    def test_rename_updates_components_kerning_groups(self):
        p = _family()
        f = p.font
        components.add_component(f, f.newGlyph("Hbar"), "H")
        f.kerning[("H", "o")] = -10
        kerning.set_group(p, 1, "H", ["H", "n"])
        p.rename_glyph("H", "Hx")
        self.assertEqual(f["Hbar"].components[0].baseGlyph, "Hx")
        self.assertIn(("Hx", "o"), f.kerning)
        self.assertIn("Hx", f.groups["public.kern1.H"])

    def test_delete_refused_when_used_as_component(self):
        p = _family()
        components.add_component(p.font, p.font["period"], "o")
        with self.assertRaises(ProjectError):
            p.delete_glyphs(["o"])

    def test_atomic_save_keeps_unknown_data_and_recovers(self):
        p = _family()
        p.font.lib["com.autre.outil"] = {"garder": [1, 2]}
        p.font.data["com.autre.outil/notes.txt"] = b"inconnu"
        path = self.tmp / "Essai.ufo"
        p.save(path)
        q = FontProject.open(path)
        self.assertEqual(q.font.lib["com.autre.outil"], {"garder": [1, 2]})
        self.assertEqual(q.font.data["com.autre.outil/notes.txt"], b"inconnu")
        # sauvegarde interrompue après le renommage de l'original : la copie de sécurité est restaurée
        bak = path.with_name(path.name + ".fmf-bak")
        path.rename(bak)
        message = recover_interrupted_save(path)
        self.assertIn("restauré", message)
        self.assertTrue(path.is_dir())
        # dossier temporaire abandonné : supprimé, l'original fait foi
        shutil.copytree(path, path.with_name(path.name + ".fmf-tmp"))
        self.assertIn("ignorée", recover_interrupted_save(path))
        self.assertFalse(path.with_name(path.name + ".fmf-tmp").exists())

    def test_designspace_two_masters_roundtrip(self):
        p = _family(("Regular", "Bold"))
        path = self.tmp / "Essai.designspace"
        p.save(path)
        q = FontProject.open(path)
        self.assertEqual([m.name for m in q.masters], ["Regular", "Bold"])
        self.assertEqual(q.axes[0].tag, "wght")
        self.assertEqual(q.masters[1].location, {"Weight": 700})
        self.assertTrue((self.tmp / "masters" / "EssaiSans-Bold.ufo").is_dir())


class BezierTest(unittest.TestCase):
    def test_segments_closed_and_open(self):
        c = shapes.ellipse(0, 0, 100, 100)
        self.assertEqual([s[3] for s in C.segments(c)], ["curve"] * 4)
        c = C.new_contour([(0, 0, "move"), (10, 0, "line"), (20, 10, "line")])
        self.assertEqual(len(C.segments(c)), 2)
        self.assertFalse(C.is_closed(c))

    def test_insert_point_on_cubic_is_exact(self):
        c = shapes.ellipse(0, 0, 200, 100)
        seg = C.segments(c)[0]
        before = C.cubic_at(*C.segment_points(c, seg), 0.3)
        index = C.insert_point(c, seg, 0.3)
        self.assertEqual(c[index].type, "curve")
        self.assertAlmostEqual(c[index].x, before[0], places=6)
        self.assertAlmostEqual(c[index].y, before[1], places=6)
        self.assertEqual(len(C.segments(c)), 5)

    def test_insert_and_delete_on_line(self):
        c = shapes.rectangle(0, 0, 100, 100)
        index = C.insert_point(c, C.segments(c)[0], 0.5)
        self.assertEqual(len(c), 5)
        C.delete_points(c, [index])
        self.assertEqual(len(c), 4)
        self.assertTrue(all(p.type == "line" for p in c))

    def test_delete_node_merges_curves(self):
        c = shapes.ellipse(0, 0, 100, 100)
        C.delete_points(c, [3])                    # un nœud lisse
        kinds = [s[3] for s in C.segments(c)]
        self.assertEqual(kinds, ["curve"] * 3)
        self.assertTrue(all(len(s[1]) == 2 for s in C.segments(c)))

    def test_smooth_and_symmetric(self):
        c = C.new_contour([(0, 0, "curve"), (0, 40), (60, 100), (100, 100, "curve"), (150, 120), (200, 50),
                           (200, 0, "curve"), (100, -40), (40, -20)])
        C.set_smooth(c, 3, True)
        a, p, b = c[2], c[3], c[4]
        cross = (a.x - p.x) * (b.y - p.y) - (a.y - p.y) * (b.x - p.x)
        self.assertAlmostEqual(cross, 0, places=6)
        C.make_symmetric(c, 3)
        self.assertAlmostEqual(math.dist((a.x, a.y), (p.x, p.y)), math.dist((b.x, b.y), (p.x, p.y)), places=6)

    def test_open_close_reverse_start(self):
        c = shapes.rectangle(0, 0, 100, 100)
        self.assertGreater(C.signed_area(c), 0)
        C.reverse(c)
        self.assertLess(C.signed_area(c), 0)
        C.reverse(c)
        C.open_at(c, 2)
        self.assertFalse(C.is_closed(c))
        self.assertEqual(len(c), 5)
        C.close(c)
        self.assertTrue(C.is_closed(c))
        self.assertEqual(len(c), 4)
        C.set_start_point(c, 2)
        self.assertEqual(len(C.segments(c)), 4)

    def test_cubic_to_quadratic_tolerance_and_back(self):
        for tol in (0.25, 1.0, 4.0):
            c = shapes.ellipse(0, 0, 1000, 600)
            cubic = C.segment_points(c, C.segments(c)[0])
            C.contour_to_quadratic(c, tol)
            seg = C.segments(c)[0]
            self.assertEqual(seg[3], "qcurve")
            quads = C.quad_segments(C.segment_points(c, seg))
            self.assertLessEqual(C.max_deviation(cubic, quads), tol * 1.05, tol)
        c = shapes.ellipse(0, 0, 1000, 600)
        C.contour_to_quadratic(c, 1.0)
        quad_poly = C.flatten_contour(c, 32)
        C.contour_to_cubic(c)
        self.assertTrue(all(s[3] == "curve" for s in C.segments(c)))
        cubic_poly = C.flatten_contour(c, 32)
        self.assertLess(max(min(math.dist(a, b) for b in quad_poly) for a in cubic_poly), 1.0)

    def test_correct_directions_counter(self):
        g = FontProject.new("x").font.newGlyph("o")
        outer = shapes.ellipse(0, 0, 500, 500)
        inner = shapes.ellipse(100, 100, 400, 400)            # même sens : faux
        g.contours.extend([outer, inner])
        self.assertEqual(C.correct_directions(g), 1)
        self.assertGreater(C.signed_area(g.contours[0]), 0)
        self.assertLess(C.signed_area(g.contours[1]), 0)


class GeometryTest(unittest.TestCase):
    def setUp(self):
        self.font = FontProject.new("x").font
        self.g = self.font.newGlyph("a")
        self.g.width = 600

    def test_remove_overlaps_and_booleans(self):
        _draw_rect(self.g, 0, 0, 200, 200)
        _draw_rect(self.g, 100, 100, 300, 300)
        geometry.remove_overlaps(self.g)
        self.assertEqual(len(self.g.contours), 1)
        self.assertEqual(len(self.g.contours[0]), 8)
        self.g.clearContours()
        _draw_rect(self.g, 0, 0, 200, 200)
        _draw_rect(self.g, 100, 100, 300, 300)
        geometry.boolean(self.g, "difference", [0], [1])
        self.assertEqual(len(self.g.contours[0]), 6)
        self.g.clearContours()
        _draw_rect(self.g, 0, 0, 200, 200)
        _draw_rect(self.g, 100, 100, 300, 300)
        geometry.boolean(self.g, "intersection", [0], [1])
        self.assertEqual(geometry.glyph_bounds(self.g), (100, 100, 200, 200))

    def test_mirror_keeps_direction_and_transform(self):
        _draw_rect(self.g, 50, 0, 150, 100)
        geometry.mirror(self.g, horizontal=True)
        self.assertEqual(geometry.glyph_bounds(self.g), (450, 0, 550, 100))
        self.assertGreater(C.signed_area(self.g.contours[0]), 0)
        from fontTools.misc.transform import Transform
        geometry.transform_glyph(self.g, Transform().scale(2))
        self.assertEqual(geometry.glyph_bounds(self.g), (900, 0, 1100, 200))

    def test_simplify_align_distribute_round_measure(self):
        self.g.contours.append(C.new_contour([(0, 0, "line"), (50, 0, "line"), (100, 0, "line"), (100, 100, "line"),
                                              (0, 100, "line")]))
        self.assertEqual(geometry.simplify(self.g), 1)
        c = self.g.contours[0]
        c[0].x = 3.4
        geometry.round_coordinates(self.g)
        self.assertEqual(c[0].x, 3)
        geometry.align(self.g, {(0, 0), (0, 3)}, "left")
        self.assertEqual(c[0].x, c[3].x)
        self.assertEqual(geometry.measure((0, 0), (3, 4))["distance"], 5)
        hits = geometry.intersections_with_line(self.g, (-10, 50), (200, 50))
        self.assertEqual(len(hits), 2)

    def test_round_corners_is_a_true_arc(self):
        self.g.contours.append(shapes.rectangle(0, 0, 400, 400))
        self.assertEqual(geometry.round_corners(self.g, {(0, 1), (0, 2)}, 50), 2)
        contour = self.g.contours[0]
        curves = [s for s in C.segments(contour) if s[3] == "curve"]
        self.assertEqual(len(curves), 2)
        mid = C.cubic_at(*C.segment_points(contour, curves[0]), 0.5)
        self.assertAlmostEqual(math.dist(mid, (350, 50)), 50, delta=0.05)    # sur le cercle de rayon 50
        self.assertFalse(geometry.round_corner(contour, 0, 500))             # rayon trop grand : rien
        self.assertEqual(geometry.glyph_bounds(self.g), (0, 0, 400, 400))

    def test_pencil_fit_follows_points(self):
        pts = [(x, 200 * math.sin(x / 80)) for x in range(0, 500, 5)]
        contour = shapes.pencil_contour(pts, error=2.0, smoothing=0)
        self.assertLess(len([p for p in contour if p.type]), 12)
        segs = C.segments(contour)
        worst = max(min(C.nearest_on_segment(contour, seg, p)[0] for seg in segs) for p in pts)
        self.assertLess(worst, 2.5)

    def test_calligraphy_nib_and_brush_outlines(self):
        stroke = [(x, 100 + 50 * math.sin(x / 40), 0.5 + x / 800) for x in range(0, 400, 4)]
        nib = calligraphy.outline(stroke, "nib", width=60, angle=30)
        brush = calligraphy.outline(stroke, "brush", width=40)
        self.assertTrue(nib and brush)
        for contour in nib + brush:
            self.assertTrue(C.is_closed(contour))
        # la pression change l'épaisseur : bec plus large en fin de tracé
        g = self.font.newGlyph("k")
        g.contours.extend(brush)
        b = geometry.glyph_bounds(g)
        self.assertGreater(b[3] - b[1], 100)


class ComponentsMetricsKerningTest(unittest.TestCase):
    def test_accented_from_anchors_and_cycles(self):
        p = _family()
        built, messages = components.build_accented(p, [0xE9])
        self.assertEqual(built, ["eacute"])
        f = p.font
        comps = f["eacute"].components
        self.assertEqual([c.baseGlyph for c in comps], ["e", "acutecomb"])
        self.assertEqual(tuple(comps[1].transformation)[4:], (260, -20))
        self.assertEqual(f["eacute"].unicodes, [0xE9])
        self.assertEqual(messages, [])
        with self.assertRaises(components.CycleError):
            components.add_component(f, f["e"], "eacute")
        # propagation : la base modifiée se voit dans le composé
        geometry.move_points(f["e"], {(0, 0)}, 0, 30)
        pen = RecordingPen()
        from fontTools.pens.recordingPen import DecomposingRecordingPen
        dpen = DecomposingRecordingPen(f)
        f["eacute"].draw(dpen)
        f["e"].draw(pen)
        self.assertEqual(dpen.value[0], pen.value[0])
        components.decompose(f, f["eacute"])
        self.assertEqual(len(f["eacute"].components), 0)
        self.assertEqual(len(f["eacute"].contours), 2)
        p.undo.undo()
        self.assertNotIn("eacute", f)

    def test_metrics(self):
        g = _family().font["H"]
        self.assertEqual((metrics.left_margin(g), metrics.right_margin(g)), (60, 60))
        metrics.set_left_margin(g, 80)
        self.assertEqual((metrics.left_margin(g), metrics.right_margin(g), g.width), (80, 60, 620))
        metrics.set_right_margin(g, 30)
        self.assertEqual(g.width, 590)
        metrics.set_width(g, 700, center=True)
        self.assertEqual(metrics.left_margin(g), metrics.right_margin(g))

    def test_kerning_groups_exceptions_and_suggestions(self):
        p = _family()
        f = p.font
        kerning.set_group(p, 1, "A", ["A"])
        kerning.set_group(p, 2, "V", ["V"])
        pair = kerning.target_pair(f, "A", "V")
        self.assertEqual(pair, ("public.kern1.A", "public.kern2.V"))
        kerning.set_value(p, 0, pair, -80)
        self.assertEqual(kerning.lookup(f, "A", "V"), (-80, pair))
        kerning.set_value(p, 0, ("A", "V"), -40)
        self.assertEqual(kerning.lookup(f, "A", "V")[0], -40)
        self.assertTrue(kerning.is_exception(f, ("A", "V")))
        p.undo.undo()
        self.assertEqual(kerning.lookup(f, "A", "V")[0], -80)
        kerning.set_group(p, 1, "AA", ["A"])                     # A quitte son ancienne classe
        self.assertNotIn("A", f.groups.get("public.kern1.A", []))
        sug = kerning.suggest(f, [("A", "V"), ("n", "n")], reference=("n", "n"))
        self.assertLess(sug[("A", "V")], 0)
        self.assertNotIn(("n", "n"), sug)


class FeaturesTest(unittest.TestCase):
    def test_check_reports_readable_errors(self):
        errors = features.check("feature liga {\n  sub f i by f_i\n} liga;", ["f", "i", "f_i"])
        self.assertEqual(len(errors), 1)
        self.assertEqual(errors[0].line, 3)
        self.assertIn("Ligne 3", str(errors[0]))
        errors = features.check("feature liga { sub f x by f_i; } liga;", ["f", "i", "f_i"])
        self.assertIn("« x » absent", str(errors[0]))
        self.assertEqual(features.check("feature liga { sub f i by f_i; } liga;", ["f", "i", "f_i"]), [])

    def test_generate_liga_and_suffix_features(self):
        p = _family()
        p.add_glyph("n.sc")
        text = features.generate(p.font, ["liga", "smcp"])
        self.assertIn("sub f i by f_i;", text)
        self.assertIn("sub n by n.sc;", text)
        merged = features.merge("feature liga { sub f f by f_f; } liga;", text)
        self.assertEqual(merged.count("feature liga"), 1)
        self.assertEqual(features.check(merged, p.font.keys()), [])


class CompileTest(unittest.TestCase):
    """Bout en bout : famille -> sauvegarde -> réouverture -> compilation -> relecture fontTools + HarfBuzz."""

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="fmfont_"))

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _ready(self, styles=("Regular",)):
        p = _family(styles)
        components.build_accented(p, [0xE9])
        for m in p.masters:
            m.font.kerning[("A", "V")] = -80
        features.set_features(p, "languagesystem DFLT dflt;\nlanguagesystem latn dflt;\n\n"
                              + features.generate(p.font, ["liga"]))
        path = self.tmp / ("Essai.designspace" if len(styles) > 1 else "Essai.ufo")
        p.save(path)
        return FontProject.open(path)

    def test_end_to_end_static_otf_ttf_woff2(self):
        p = self._ready()
        self.assertEqual([d for d in diagnose(p) if d.level == BLOCKING], [])
        for fmt in ("ttf", "otf", "woff", "woff2"):
            out = self.tmp / f"Essai.{fmt}"
            export(p, out)
            tt = TTFont(out)
            self.assertEqual(tt.flavor, fmt if fmt.startswith("woff") else None)
            self.assertEqual(tt.getBestCmap()[0xE9], "eacute")
            self.assertEqual(tt["head"].unitsPerEm, 1000)
            self.assertIn("GPOS", tt)
            self.assertEqual(tt["hmtx"]["H"][0], 600)
        shaper = Shaper((self.tmp / "Essai.ttf").read_bytes())
        shaped = shaper.shape("AV")
        self.assertEqual([g[0] for g in shaped], ["A", "V"])
        self.assertEqual(shaped[0][1], 600 - 80)                        # crénage appliqué
        self.assertEqual(shaper.names("fi"), ["f_i"])                    # liga active
        self.assertEqual(shaper.names("fi", {"liga": False}), ["f", "i"])
        self.assertEqual(shaper.advances("AV", {"kern": False}), [600, 600])
        # « é » saisi décomposé : HarfBuzz recompose vers le glyphe précomposé eacute
        self.assertEqual(shaper.names("é"), ["eacute"])
        # « o + U+0301 » (pas de précomposé) : mark positionne l'accent par les ancres (ufo2ft)
        mark = shaper.shape("ó")
        self.assertEqual([g[0] for g in mark], ["o", "acutecomb"])
        self.assertEqual((mark[1][2], mark[1][3]), (270 - 540, -20))

    def test_mark_to_mark_stacking(self):
        """mkmk : une 2e marque se pose sur l'ancre « top » de la 1re (ufo2ft), vérifié par HarfBuzz."""
        p = self._ready()
        f = p.font
        p.add_glyph("gravecomb")
        f["gravecomb"].contours.append(shapes.polygon(0, 620, 50, 3))
        components.set_anchor(f["gravecomb"], "_top", 0, 540)
        components.set_anchor(f["acutecomb"], "top", 10, 700)
        out = self.tmp / "mkmk.ttf"
        export(p, out)
        shaped = Shaper(out.read_bytes()).shape("o\u0301\u0300")
        self.assertEqual([g[0] for g in shaped], ["o", "acutecomb", "gravecomb"])
        # 2e marque : ancre top de la 1re (posée en 270 - 540, -20) + (10, 700) - _top (0, 540)
        self.assertEqual((shaped[2][2], shaped[2][3]), (270 - 540 + 10, -20 + 160))

    def test_export_blocked_and_import_never_overwritten(self):
        p = self._ready()
        p.font["H"].contours[0][0].type = "move"                       # contour ouvert : bloquant
        with self.assertRaises(CompileError) as ctx:
            export(p, self.tmp / "x.ttf")
        self.assertIn("ouvert", str(ctx.exception))
        p.font["H"].contours[0][0].type = "line"
        out = self.tmp / "Essai.ttf"
        export(p, out)
        imported = import_binary(out)
        self.assertIsNone(imported.path)
        with self.assertRaises(CompileError):
            export(imported, out)

    def test_variable_font_and_interpolation(self):
        p = self._ready(("Regular", "Bold"))
        self.assertEqual(interpolation.incompatibilities(p), [])
        mid = interpolation.interpolate_glyph(p, "H", {"Weight": 550})
        self.assertEqual(geometry.glyph_bounds(mid)[2], 540)
        self.assertEqual(mid.contours[0][1].x, 160)                       # 140 -> 180 à mi-chemin
        tt = compile_variable(p)
        for table in ("fvar", "gvar", "STAT"):
            self.assertIn(table, tt)
        self.assertEqual([i.coordinates for i in tt["fvar"].instances], [{"wght": 400}, {"wght": 700}])
        data = to_bytes(tt)
        import uharfbuzz as hb
        face = hb.Face(data)
        font = hb.Font(face)
        font.set_variations({"wght": 700})
        buf = hb.Buffer()
        buf.add_str("o")
        buf.guess_segment_properties()
        hb.shape(font, buf, {})
        self.assertEqual(buf.glyph_positions[0].x_advance, 580)         # chasse du Bold interpolée
        instance = interpolation.instance_font(p, {"Weight": 700}, "Bold")
        self.assertEqual(instance["o"].width, 580)
        self.assertEqual(instance.kerning[("A", "V")], -80)

    def test_incompatible_masters_raise_not_silent(self):
        p = self._ready(("Regular", "Bold"))
        C.delete_points(p.masters[1].font["H"].contours[0], [0])
        with self.assertRaises(interpolation.InterpolationError) as ctx:
            interpolation.interpolate_glyph(p, "H", {"Weight": 500})
        self.assertIn("H, contour 1", str(ctx.exception))
        with self.assertRaises(CompileError):
            compile_variable(p)
        self.assertTrue(any(d.level == BLOCKING for d in diagnose(p, variable=True)))

    def test_import_binary_roundtrip(self):
        p = self._ready()
        p.font.kerning.clear()
        kerning.set_group(p, 1, "A", ["A"])
        kerning.set_group(p, 2, "V", ["V"])
        p.font.kerning[("public.kern1.A", "public.kern2.V")] = -70
        p.font.kerning[("A", "o")] = -15
        out = self.tmp / "Essai.otf"
        tt = compile_static(p.font, "otf")
        tt.save(out)
        q = import_binary(out)
        self.assertEqual(q.font["H"].width, 600)
        self.assertEqual(q.font["eacute"].unicodes, [0xE9])
        self.assertEqual(geometry.glyph_bounds(q.font["H"]), (60, 0, 540, 700))
        self.assertEqual(kerning.lookup(q.font, "A", "V")[0], -70)
        self.assertEqual(kerning.lookup(q.font, "A", "o")[0], -15)
        self.assertTrue(any("Features" in m for m in q.messages))
        # réenregistré en source : UFO valide, recompilable
        q.save(self.tmp / "Import.ufo")
        compile_static(FontProject.open(self.tmp / "Import.ufo").font, "ttf")

    def test_import_svg(self):
        svg = self.tmp / "carre.svg"
        svg.write_text('<svg xmlns="http://www.w3.org/2000/svg"><path d="M10 10 H110 V60 H10 Z"/></svg>')
        g = FontProject.new("x").font.newGlyph("a")
        import_svg(svg, g, 1000, 800, fit_height=500)
        self.assertEqual(geometry.glyph_bounds(g), (0, 0, 1000, 500))

    def test_diagnostics_levels(self):
        p = _family()
        p.font["H"].unicodes = [0x6E]                                  # même code que n
        p.font["o"].contours.append(shapes.ellipse(100, 100, 200, 200))  # contrepoinçon dans le mauvais sens
        p.font["n"].contours[0].append(p.font["n"].contours[0][0].__class__(60, 0, "line"))
        found = diagnose(p)
        levels = {d.level for d in found}
        self.assertEqual(levels, {BLOCKING, WARNING, SUGGESTION})
        texts = "\n".join(str(d) for d in found)
        self.assertIn("U+006E", texts)
        self.assertIn("sens de contour", texts)
        self.assertIn("nœuds confondus", texts)


if __name__ == "__main__":
    unittest.main()
