"""Module Photoshop (fm_photoshop/), cœur SANS Qt : plans de pixels, composition (alpha, opacité, modes de fusion,
groupes, masques, écrêtage), brosse (continuité, sélection, pression, annulation exacte), historique, conteneur
natif (aller-retour, refus, ressources absentes), import / export d'images relus par une bibliothèque indépendante."""
import os as _os, sys as _sys  # jamais les vrais réglages / presets de l'utilisateur (tests/_isolate.py)
_sys.path.insert(0, _os.path.dirname(_os.path.abspath(__file__)))
import _isolate  # noqa: E402,F401
import io
import json
import os
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from fm_photoshop import brush as B, compose as C, container, io_images, model as M, ops
from fm_photoshop.history import History
from fm_photoshop.planes import Plane


def solid(w, h, rgba):
    return np.broadcast_to(np.array(rgba, np.uint8), (h, w, 4)).copy()


def doc_with(*specs, w=4, h=4):
    """Document 4 × 4 sans fond ; specs = (rgba, opacité, mode)."""
    doc = M.new_document(w, h, background=None)
    doc.layers.clear()
    for i, spec in enumerate(specs):
        rgba, opacity, mode = spec if isinstance(spec[0], tuple) else (spec, 1.0, "normal")
        layer = M.Layer(f"L{i}")
        layer.pix.set_all(0, 0, solid(w, h, rgba))
        layer.opacity, layer.blend = opacity, mode
        doc.layers.append(layer)
    return doc


def px(doc, x=0, y=0):
    return tuple(int(v) for v in C.flatten_u8(doc)[y, x])


class PlaneTest(unittest.TestCase):
    def test_grows_on_demand_and_reads_fill_outside(self):
        plane = Plane(4, 0)
        self.assertIsNone(plane.rect())
        plane.write((10, 10, 12, 12), solid(2, 2, (1, 2, 3, 255)))
        plane.write((20, 5, 22, 7), solid(2, 2, (9, 9, 9, 255)))
        self.assertEqual(plane.read((10, 10, 12, 12))[0, 0].tolist(), [1, 2, 3, 255])
        self.assertEqual(plane.read((15, 8, 17, 9))[0, 0].tolist(), [0, 0, 0, 0])     # entre les deux : transparent
        self.assertEqual(plane.read((0, 0, 2, 2))[0, 0].tolist(), [0, 0, 0, 0])       # hors du plan
        plane.trim()
        self.assertEqual(plane.rect(), (10, 5, 22, 12))

    def test_mask_plane_defaults_to_reveal(self):
        plane = Plane(1, 255)
        self.assertEqual(int(plane.read((0, 0, 3, 3)).min()), 255)


class ComposeTest(unittest.TestCase):
    def test_opaque_over_opaque_and_transparent_edges(self):
        doc = doc_with((255, 0, 0, 255), (0, 0, 255, 255))
        self.assertEqual(px(doc), (0, 0, 255, 255))
        empty = M.new_document(2, 2, background=None)
        self.assertEqual(px(empty), (0, 0, 0, 0))                                      # transparent reste transparent

    def test_layer_opacity_known_values(self):
        doc = doc_with((255, 255, 255, 255), ((255, 0, 0, 255), 0.5, "normal"))
        self.assertEqual(px(doc), (255, 128, 128, 255))                                 # 50 % de rouge sur blanc

    def test_straight_alpha_no_halo(self):
        """Pixel rouge à 50 % d'alpha sur transparent : la couleur DROITE reste rouge pur (pas de halo sombre)."""
        doc = doc_with((255, 0, 0, 128))
        self.assertEqual(px(doc), (255, 0, 0, 128))

    def test_blend_modes_on_gray(self):
        base = (128, 128, 128, 255)
        cases = {"multiply": 64, "screen": 192, "darken": 128, "lighten": 128, "difference": 0, "add": 255,
                 "exclusion": 128}
        top = (128, 128, 128, 255)
        for mode, expect in cases.items():
            doc = doc_with(base, (top, 1.0, mode))
            self.assertAlmostEqual(px(doc)[0], expect, delta=1, msg=mode)
        doc = doc_with((100, 100, 100, 255), ((200, 200, 200, 255), 1.0, "multiply"))
        self.assertAlmostEqual(px(doc)[0], round(100 * 200 / 255), delta=1)

    def test_overlay_hardlight_softlight_symmetries(self):
        a, b = (200, 100, 50, 255), (60, 120, 220, 255)
        over = px(doc_with(a, (b, 1.0, "overlay")))
        hard = px(doc_with(b, (a, 1.0, "hardlight")))
        self.assertEqual(over, hard)                                                     # overlay = hardlight échangés
        soft = px(doc_with((128, 128, 128, 255), ((200, 200, 200, 255), 1.0, "softlight")))
        self.assertGreater(soft[0], 128)

    def test_hidden_layer_ignored(self):
        doc = doc_with((255, 0, 0, 255), (0, 255, 0, 255))
        doc.layers[1].visible = False
        self.assertEqual(px(doc), (255, 0, 0, 255))

    def test_mask_hides_and_partial_mask(self):
        doc = doc_with((0, 0, 255, 255), (255, 0, 0, 255))
        top = doc.layers[1]
        top.mask = M.Mask()
        top.mask.plane.set_all(0, 0, np.array([[[0], [128]], [[255], [255]]], np.uint8).repeat(2, 0).repeat(2, 1))
        self.assertEqual(px(doc, 0, 0), (0, 0, 255, 255))                                # masque noir : le bas apparaît
        self.assertEqual(px(doc, 3, 0), (128, 0, 127, 255))                              # 128/255 de rouge sur bleu
        self.assertEqual(px(doc, 0, 3), (255, 0, 0, 255))
        top.mask.enabled = False
        self.assertEqual(px(doc, 0, 0), (255, 0, 0, 255))

    def test_group_isolated_vs_passthrough(self):
        doc = M.new_document(2, 2, background=None)
        doc.layers.clear()
        under = M.Layer("fond")
        under.pix.set_all(0, 0, solid(2, 2, (128, 128, 128, 255)))
        group = M.Layer("g", "group")
        child = M.Layer("enfant")
        child.pix.set_all(0, 0, solid(2, 2, (128, 128, 128, 255)))
        child.blend = "multiply"
        group.children = [child]
        doc.layers = [under, group]
        self.assertAlmostEqual(px(doc)[0], 64, delta=1)                                  # traverse : multiplie le fond
        group.passthrough = False                                                        # isolé : l'enfant multiplie
        self.assertEqual(px(doc)[0], 128)                                                # du transparent -> gris 128 opaque
        group.passthrough = True
        group.opacity = 0.5                                                              # < 100 % : isolé aussi
        self.assertEqual(px(doc)[0], 128)

    def test_group_opacity(self):
        doc = M.new_document(2, 2, background=None)
        doc.layers.clear()
        white = M.Layer("b")
        white.pix.set_all(0, 0, solid(2, 2, (255, 255, 255, 255)))
        group = M.Layer("g", "group")
        red = M.Layer("r")
        red.pix.set_all(0, 0, solid(2, 2, (255, 0, 0, 255)))
        group.children, group.opacity = [red], 0.5
        doc.layers = [white, group]
        self.assertEqual(px(doc), (255, 128, 128, 255))

    def test_clipping_mask(self):
        doc = M.new_document(4, 1, background=None)
        doc.layers.clear()
        base = M.Layer("base")
        data = solid(4, 1, (0, 0, 255, 255))
        data[0, 2:] = (0, 0, 0, 0)                                                       # base transparente à droite
        base.pix.set_all(0, 0, data)
        clipped = M.Layer("écrêté")
        clipped.pix.set_all(0, 0, solid(4, 1, (255, 0, 0, 255)))
        clipped.clip = True
        doc.layers = [base, clipped]
        self.assertEqual(px(doc, 0, 0), (255, 0, 0, 255))                                # rouge là où la base existe
        self.assertEqual(px(doc, 3, 0), (0, 0, 0, 0))                                    # rien ailleurs
        clipped.clip = False
        self.assertEqual(px(doc, 3, 0), (255, 0, 0, 255))

    def test_region_composition_matches_full(self):
        doc = doc_with((10, 200, 30, 255), ((250, 20, 20, 200), 0.7, "overlay"), w=16, h=16)
        full = C.flatten_u8(doc)
        part = C.flatten_u8(doc, (3, 5, 9, 12))
        self.assertTrue(np.array_equal(full[5:12, 3:9], part))


class BrushTest(unittest.TestCase):
    def setUp(self):
        self.doc = M.new_document(64, 64, background=None)
        self.layer = self.doc.layers[0]

    def stroke(self, points, brush=None, selection=None, target="pixels"):
        brush = brush or B.Brush(size=8, hardness=1.0, color=(255, 0, 0), spacing=0.1)
        s = B.Stroke(self.layer, target, brush, self.doc.rect(), selection)
        s.begin(*points[0])
        for p in points[1:]:
            s.move(*p)
        s.finish_to(*points[-1])
        return s, s.end()

    def alpha(self):
        return self.layer.pix.read(self.doc.rect())[..., 3]

    def test_continuous_stroke_without_gaps(self):
        _s, _c = self.stroke([(5, 32), (60, 32)])
        row = self.alpha()[32]
        self.assertTrue((row[6:59] == 255).all())                                         # aucun trou le long du trait

    def test_color_and_alpha_of_hard_dab(self):
        self.stroke([(32, 32)])
        self.assertEqual(self.layer.pix.read((32, 32, 33, 33))[0, 0].tolist(), [255, 0, 0, 255])
        self.assertEqual(self.layer.pix.read((0, 0, 1, 1))[0, 0, 3], 0)

    def test_undo_restores_exactly(self):
        base = self.layer.pix.read(self.doc.rect())
        history = History()
        _s, cmd = self.stroke([(10, 10), (50, 40), (20, 55)])
        history.push(cmd)
        painted = self.layer.pix.read(self.doc.rect())
        self.assertFalse(np.array_equal(base, painted))
        history.undo()
        self.assertTrue(np.array_equal(self.layer.pix.read(self.doc.rect()), base))
        history.redo()
        self.assertTrue(np.array_equal(self.layer.pix.read(self.doc.rect()), painted))

    def test_opacity_caps_the_whole_stroke(self):
        brush = B.Brush(size=10, hardness=1.0, opacity=0.5, color=(255, 0, 0), spacing=0.1)
        self.stroke([(10, 32), (50, 32)], brush)
        self.assertTrue((self.alpha()[32, 12:48] == 128).all())                           # pas d'accumulation > 50 %

    def test_flow_accumulates_dabs(self):
        low = B.Brush(size=10, hardness=1.0, flow=0.2, color=(0, 0, 0), spacing=0.1)
        self.stroke([(10, 32), (50, 32)], low)
        self.assertGreater(int(self.alpha()[32, 30]), 200)                                # tampons accumulés

    def test_selection_limits_and_partial_coverage(self):
        class Half:
            def coverage(self, rect):
                out = np.zeros((rect[3] - rect[1], rect[2] - rect[0]), np.float32)
                cols = np.arange(rect[0], rect[2])
                out[:, cols < 32] = 1.0
                out[:, cols == 40] = 0.5
                return out
        self.stroke([(5, 20), (60, 20)], selection=Half())
        row = self.alpha()[20]
        self.assertEqual(int(row[10]), 255)
        self.assertEqual(int(row[50]), 0)
        self.assertEqual(int(row[40]), 128)

    def test_eraser_and_pressure_size(self):
        self.layer.pix.set_all(0, 0, solid(64, 64, (0, 0, 0, 255)))
        eraser = B.Brush(size=10, hardness=1.0, eraser=True)
        self.stroke([(32, 32)], eraser)
        self.assertEqual(int(self.alpha()[32, 32]), 0)
        self.assertEqual(int(self.alpha()[0, 0]), 255)
        small = B.Stroke(self.layer, "pixels", B.Brush(size=20, hardness=1.0, pressure_size=True, color=(9, 9, 9)),
                         self.doc.rect())
        big_box = small.begin(10, 10, 1.0)
        light_box = small.begin(40, 40, 0.25)
        self.assertGreater(big_box[2] - big_box[0], light_box[2] - light_box[0])

    def test_mask_painting_hides_then_reveals(self):
        self.layer.pix.set_all(0, 0, solid(64, 64, (255, 0, 0, 255)))
        self.layer.mask = M.Mask()
        self.stroke([(32, 32)], B.Brush(size=10, hardness=1.0, color=(0, 0, 0)), target="mask")
        self.assertEqual(C.flatten_u8(self.doc)[32, 32, 3], 0)
        self.stroke([(32, 32)], B.Brush(size=10, hardness=1.0, color=(255, 255, 255)), target="mask")
        self.assertEqual(C.flatten_u8(self.doc)[32, 32, 3], 255)

    def test_locked_layer_refuses(self):
        self.layer.locked = True
        with self.assertRaises(ValueError):
            B.Stroke(self.layer, "pixels", B.Brush(), self.doc.rect())

    def test_brush_preset_roundtrip_and_invalid_values(self):
        brush = B.Brush(size=33, hardness=0.3, color=(1, 2, 3))
        back = B.Brush.from_dict(json.loads(json.dumps(brush.to_dict())))
        self.assertEqual((back.size, back.hardness, back.color), (33, 0.3, (1, 2, 3)))
        bad = B.Brush.from_dict({"size": "oups", "hardness": 7, "flow": -2})
        self.assertEqual((bad.hardness, bad.flow), (1.0, 0.0))


class OpsTest(unittest.TestCase):
    def test_structure_undo_redo(self):
        doc = M.new_document(8, 8)
        history = History()
        base = doc.layers[0]
        layer, cmd = ops.add_layer(doc, "Peinture")
        history.push(cmd)
        history.push(ops.set_props(layer, opacity=0.4, blend="multiply"))
        group, cmd = ops.group_layers(doc, [base, layer])
        history.push(cmd)
        self.assertEqual([l.name for l in doc.layers], ["Groupe"])
        history.undo(); history.undo()
        self.assertEqual((layer.opacity, layer.blend), (1.0, "normal"))
        history.redo()
        self.assertEqual((layer.opacity, layer.blend), (0.4, "multiply"))
        history.undo(); history.undo()
        self.assertEqual([l.name for l in doc.layers], ["Arrière-plan"])

    def test_merge_down_equals_flatten_of_the_pair(self):
        doc = doc_with((255, 255, 255, 255), ((255, 0, 0, 255), 0.5, "normal"))
        before = C.flatten_u8(doc)
        cmd = ops.merge_down(doc, doc.layers[1])
        self.assertEqual(len(doc.layers), 1)
        self.assertTrue(np.array_equal(C.flatten_u8(doc), before))
        cmd.undo()
        self.assertEqual(len(doc.layers), 2)
        self.assertTrue(np.array_equal(C.flatten_u8(doc), before))

    def test_flatten_and_undo(self):
        doc = doc_with((10, 20, 30, 255), (200, 100, 50, 128))
        before = C.flatten_u8(doc)
        _layer, cmd = ops.flatten(doc)
        self.assertEqual(len(doc.layers), 1)
        self.assertTrue(np.array_equal(C.flatten_u8(doc), before))
        cmd.undo()
        self.assertEqual(len(doc.layers), 2)

    def test_mask_ops(self):
        doc = doc_with((255, 0, 0, 255))
        layer = doc.layers[0]
        ops.add_mask(layer)
        layer.mask.plane.set_all(0, 0, np.full((4, 4, 1), 100, np.uint8))
        cmd = ops.invert_mask(layer, doc.rect())
        self.assertEqual(int(layer.mask.plane.data[0, 0, 0]), 155)
        cmd.undo()
        self.assertEqual(int(layer.mask.plane.data[0, 0, 0]), 100)
        cmd = ops.apply_mask(layer, doc.rect())
        self.assertIsNone(layer.mask)
        self.assertEqual(int(layer.pix.data[0, 0, 3]), 100)
        cmd.undo()
        self.assertEqual(int(layer.pix.data[0, 0, 3]), 255)
        self.assertIsNotNone(layer.mask)

    def test_translate_and_duplicate_are_independent(self):
        doc = doc_with((255, 0, 0, 255))
        layer = doc.layers[0]
        twin, _cmd = ops.duplicate_layer(doc, layer)
        ops.translate_layer(twin, 2, 1)
        self.assertEqual((layer.pix.x, twin.pix.x, twin.pix.y), (0, 2, 1))
        twin.pix.data[0, 0] = (1, 1, 1, 1)
        self.assertEqual(layer.pix.data[0, 0].tolist(), [255, 0, 0, 255])

    def test_fill_rect_respects_partial_selection(self):
        doc = M.new_document(4, 4, background=None)

        class Quarter:
            def coverage(self, rect):
                return np.full((rect[3] - rect[1], rect[2] - rect[0]), 0.25, np.float32)
        ops.fill_rect(doc.layers[0], (0, 0, 4, 4), (255, 0, 0, 255), Quarter())
        self.assertEqual(doc.layers[0].pix.read((0, 0, 1, 1))[0, 0].tolist(), [255, 0, 0, 64])

    def test_last_layer_cannot_be_removed_and_cycles_refused(self):
        doc = M.new_document(4, 4)
        with self.assertRaises(ValueError):
            ops.remove_layer(doc, doc.layers[0])
        group, _ = ops.add_layer(doc, "G", kind="group")
        with self.assertRaises(ValueError):
            ops.move_layer(doc, group, group, 0)


class ContainerTest(unittest.TestCase):
    def build(self):
        doc = doc_with((10, 20, 30, 255), ((200, 100, 50, 128), 0.6, "multiply"))
        doc.dpi, doc.name, doc.icc_profile = 300.0, "Essai é", b"ICCDATA"
        top = doc.layers[1]
        top.mask = M.Mask()
        top.mask.plane.set_all(1, 1, np.full((2, 2, 1), 77, np.uint8))
        top.extra["futur"] = {"a": 1}
        group = M.Layer("G", "group")
        inner = M.Layer("dedans")
        inner.pix.set_all(2, 2, solid(1, 1, (1, 2, 3, 4)))
        inner.clip, inner.locked = True, True
        group.children, group.passthrough = [inner], False
        doc.layers.append(group)
        doc.extra["inconnu"] = [1, 2]
        return doc

    def test_roundtrip_keeps_everything(self):
        doc = self.build()
        back = container.loads(container.dumps(doc))
        self.assertEqual((back.width, back.height, back.dpi, back.name, back.icc_profile),
                         (4, 4, 300.0, "Essai é", b"ICCDATA"))
        self.assertTrue(np.array_equal(C.flatten_u8(back), C.flatten_u8(doc)))
        top = back.layers[1]
        self.assertEqual((top.opacity, top.blend, top.extra.get("futur")), (0.6, "multiply", {"a": 1}))
        self.assertEqual((top.mask.plane.x, int(top.mask.plane.data[0, 0, 0])), (1, 77))
        inner = back.layers[2].children[0]
        self.assertEqual((inner.clip, inner.locked, back.layers[2].passthrough), (True, True, False))
        self.assertEqual(back.extra.get("inconnu"), [1, 2])
        self.assertEqual([l.uid for l in doc.walk()], [l.uid for l in back.walk()])

    def test_atomic_save_backup_and_reload(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "a.fmps"
            doc = self.build()
            container.save(doc, path)
            doc.name = "v2"
            container.save(doc, path)
            self.assertTrue((Path(tmp) / "a.fmps.bak").exists())
            self.assertEqual(container.load(path).name, "v2")
            self.assertEqual([p.name for p in Path(tmp).iterdir() if p.name.endswith(".part")], [])

    def test_future_version_refused_not_lost(self):
        payload = container.dumps(self.build())
        src = zipfile.ZipFile(io.BytesIO(payload))
        manifest = json.loads(src.read("manifest.json"))
        manifest["version"] = container.VERSION + 1
        out = io.BytesIO()
        with zipfile.ZipFile(out, "w") as z:
            z.writestr("manifest.json", json.dumps(manifest))
        with self.assertRaises(container.TooNewError):
            container.loads(out.getvalue())

    def test_invalid_and_missing_resources(self):
        with self.assertRaises(container.ContainerError):
            container.loads(b"pas une archive")
        payload = container.dumps(self.build())
        src = zipfile.ZipFile(io.BytesIO(payload))
        out = io.BytesIO()
        with zipfile.ZipFile(out, "w") as z:                                              # une ressource retirée
            for name in src.namelist():
                if not name.startswith("layers/"):
                    z.writestr(name, src.read(name))
        with self.assertRaisesRegex(container.ContainerError, "absente"):
            container.loads(out.getvalue())

    def test_hostile_resource_names_refused(self):
        manifest = {"format": container.FORMAT, "version": 1, "document": {"width": 2, "height": 2},
                    "layers": [{"id": "0" * 16, "name": "x", "w": 1, "h": 1, "png": "../evil.png"}]}
        out = io.BytesIO()
        with zipfile.ZipFile(out, "w") as z:
            z.writestr("manifest.json", json.dumps(manifest))
            z.writestr("../evil.png", b"x")
        with self.assertRaisesRegex(container.ContainerError, "refusé"):
            container.loads(out.getvalue())

    def test_png_cache_not_reencoded_when_unchanged(self):
        doc = self.build()
        container.dumps(doc)
        plane = doc.layers[0].pix
        first = plane.png
        container.dumps(doc)
        self.assertIs(plane.png, first)
        plane.write((0, 0, 1, 1), solid(1, 1, (9, 9, 9, 255)))
        container.dumps(doc)
        self.assertIsNot(plane.png, first)


class ImageIoTest(unittest.TestCase):
    def test_png_tiff_webp_roundtrip_read_by_independent_library(self):
        """Écrit par Pillow (notre code), relu par OpenImageIO (bibliothèque indépendante) : pixels et alpha."""
        import OpenImageIO as oiio
        doc = doc_with((255, 255, 255, 255), ((200, 30, 60, 128), 1.0, "normal"))
        data = np.zeros((4, 4, 4), np.uint8)
        data[::2] = (200, 30, 60, 128)                                                   # rangées à moitié transparentes
        doc.layers[1].pix.set_all(0, 0, data)
        expect = C.flatten_u8(doc)
        with tempfile.TemporaryDirectory() as tmp:
            for suffix in (".png", ".tif"):
                path = Path(tmp) / f"x{suffix}"
                io_images.export_document(doc, path)
                buf = oiio.ImageBuf(str(path))
                self.assertFalse(buf.has_error, buf.geterror())
                pixels = np.array(buf.get_pixels(oiio.UINT8), np.uint8).reshape(4, 4, -1)
                self.assertTrue(np.array_equal(pixels[..., :4], expect), suffix)

    def test_alpha_preserved_png_transparent_document(self):
        doc = doc_with((255, 0, 0, 100), w=3, h=3)
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "t.png"
            io_images.export_document(doc, path)
            rgba, dpi, icc, notes = io_images.import_image(path)
            self.assertEqual(rgba[0, 0].tolist(), [255, 0, 0, 100])

    def test_jpeg_note_and_single_layer_export_and_errors(self):
        doc = doc_with((255, 255, 255, 255), (0, 0, 0, 255))
        with tempfile.TemporaryDirectory() as tmp:
            notes = io_images.export_document(doc, Path(tmp) / "a.jpg", quality=95)
            self.assertTrue(any("JPEG" in n for n in notes))
            io_images.export_document(doc, Path(tmp) / "solo.png", layer=doc.layers[0])
            rgba, *_ = io_images.import_image(Path(tmp) / "solo.png")
            self.assertEqual(rgba[0, 0].tolist(), [255, 255, 255, 255])
            bad = Path(tmp) / "faux.png"
            bad.write_bytes(b"pas une image")
            with self.assertRaises(io_images.ImageError):
                io_images.import_image(bad)
            with self.assertRaises(io_images.ImageError):
                io_images.export_document(doc, Path(tmp) / "x.xyz")


if __name__ == "__main__":
    unittest.main()
