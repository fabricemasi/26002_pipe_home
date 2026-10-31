"""Module Illustrator, tranche 13 : aspect et effets : modèle (un effet par type, ordre, bornes), géométrie (décalage,
arrondis), rendu vérifié au pixel (ombre portée, lueur, flou, contour progressif, contours supplémentaires),
commandes (ajouter, curseur en direct = une étape, désactiver, supprimer), décomposer l'aspect, SVG (`<filter>`)."""
import os as _os, sys as _sys  # jamais les vrais réglages / presets de l'utilisateur (tests/_isolate.py)
_sys.path.insert(0, _os.path.dirname(_os.path.abspath(__file__)))
import _isolate  # noqa: E402,F401
import unittest
import xml.etree.ElementTree as ET

from PySide6.QtCore import QPointF, QRectF
from PySide6.QtGui import QColor

from test_illustrator_masks import MaskTestCase
from fm_board import model
from fm_illustrator import appearance as ap, bezier as bz, model as im, svg


class AppearanceModelTest(unittest.TestCase):
    def test_effects_are_unique_ordered_and_bounded(self):
        effects = ap.valid_effects([{"type": "shadow", "opacity": 7}, {"type": "offset", "distance": 1e9},
                                    {"type": "shadow"}, {"type": "inconnu"}, {"type": "glow", "color": "x"}])
        self.assertEqual([e["type"] for e in effects], ["offset", "shadow", "glow"])
        self.assertEqual(effects[1]["opacity"], 1.0)
        self.assertEqual(effects[0]["distance"], 1000.0)
        self.assertEqual(effects[2]["color"], ap.DEFAULTS["glow"]["color"])
        item = model.normalize_item({"id": "p", "type": "ill_path", "effects": [{"type": "blur", "on": False}],
                                     "extra_strokes": [{"color": "#ff0000", "width": -3}]})
        self.assertFalse(item["effects"][0]["on"])
        self.assertEqual(item["extra_strokes"][0]["width"], 0.0)

    def test_vector_effects_geometry(self):
        data = {"subpaths": bz.rect(0, 0, 100, 100), "effects": ap.valid_effects([{"type": "offset", "distance": 10}])}
        self.assertEqual([round(v) for v in bz.bounds(ap.render_subpaths(data))], [-10, -10, 110, 110])
        data["effects"][0]["on"] = False
        self.assertIs(ap.render_subpaths(data), data["subpaths"])
        rounded = bz.round_corners(bz.rect(0, 0, 100, 100), 20)
        self.assertEqual(len(rounded[0]["nodes"]), 8)
        far = bz.round_corners(bz.rect(0, 0, 10, 10), 500)          # rayon borné par la moitié des côtés
        self.assertEqual([round(v, 6) for v in bz.bounds(far)], [0, 0, 10, 10])

    def test_svg_filter_and_extra_strokes(self):
        data = im.new_entity(im.PATH, subpaths=bz.rect(0, 0, 50, 50), fill="#ff0000", stroke="")
        data.update(type=im.PATH, effects=ap.valid_effects([{"type": "shadow"}, {"type": "blur"}]),
                    extra_strokes=[{"color": "#0000ff", "width": 8.0, "opacity": 1.0}])
        root = ET.fromstring(svg.export_svg([data], (-20.0, -20.0, 100.0, 100.0)))
        ns = f"{{{svg.SVG_NS}}}"
        flt = root.find(f"{ns}defs/{ns}filter")
        self.assertIsNotNone(flt)
        self.assertIsNotNone(flt.find(f"{ns}feOffset"))
        g = root.find(f"{ns}g")
        self.assertEqual(g.get("filter"), f"url(#{flt.get('id')})")
        paths = g.findall(f"{ns}path")
        self.assertEqual([p.get("stroke") for p in paths], ["#0000ff", None])     # contour sous l'objet


class EffectsRenderTest(MaskTestCase):
    def square(self, effects=(), strokes=()):
        item = self.ctl.new_path(bz.rect(0, 0, 100, 100), QPointF(150, 150),
                                 dict(self.ctl.style, fill="#ff0000", stroke="", fill_gradient=None))
        self.ctl.commit_new(item, "a")
        if effects or strokes:
            self.ctl.change([item], lambda i: i.data.update(effects=ap.valid_effects(list(effects)),
                                                            extra_strokes=ap.valid_strokes(list(strokes))), "fx")
        return item

    AREA = QRectF(100, 100, 220, 220)

    def test_drop_shadow_below_and_offset(self):
        self.square([{"type": "shadow", "dx": 20, "dy": 20, "blur": 2, "color": "#000000", "opacity": 1.0}])
        image = self.render(self.AREA)
        self.assertEqual(self.pixel(image, 200, 200, self.AREA).name(), "#ff0000")      # l'objet dessus
        shadow = self.pixel(image, 262, 262, self.AREA)                                   # sous, décalé
        self.assertLess(shadow.lightness(), 60)
        self.assertEqual(self.pixel(image, 140, 140, self.AREA).name(), self.background(image, self.AREA))

    def test_glow_blur_and_feather(self):
        item = self.square([{"type": "glow", "blur": 12, "color": "#0000ff", "opacity": 1.0}])
        image = self.render(self.AREA)
        halo = self.pixel(image, 254, 200, self.AREA)
        self.assertGreater(halo.blue(), halo.red())                                       # bleuté autour
        self.ctl.select([item])
        self.ctl.remove_effect("glow")
        self.ctl.add_effect("blur")
        self.ctl.set_effect("blur", "radius", 16.0)
        self.scene.commit_live()
        edge = self.pixel(self.render(self.AREA), 250, 200, self.AREA)                    # bord adouci
        self.assertNotIn(edge.name(), ("#ff0000", self.background(self.render(self.AREA), self.AREA)))
        self.ctl.select([item])
        self.ctl.remove_effect("blur")
        self.ctl.add_effect("feather")
        image = self.render(self.AREA)
        self.assertEqual(self.pixel(image, 200, 200, self.AREA).name(), "#ff0000")      # cœur intact
        self.assertLess(self.pixel(image, 151, 200, self.AREA).red() - QColor(self.background(
            image, self.AREA)).red(), 200)                                                # bord transparent

    def test_offset_round_and_extra_stroke(self):
        item = self.square([{"type": "offset", "distance": 15}])
        image = self.render(self.AREA)
        self.assertEqual(self.pixel(image, 140, 200, self.AREA).name(), "#ff0000")      # au-delà du bord d'origine
        self.ctl.select([item])
        self.ctl.remove_effect("offset")
        self.ctl.add_effect("round")
        self.ctl.set_effect("round", "radius", 40.0)
        self.scene.commit_live()
        image = self.render(self.AREA)
        self.assertEqual(self.pixel(image, 152, 152, self.AREA).name(), self.background(image, self.AREA))
        self.ctl.select([item])
        self.ctl.add_extra_stroke()
        self.ctl.set_extra_stroke(0, "color", "#00ff00")
        self.ctl.set_extra_stroke(0, "width", 20.0)
        self.scene.commit_live()
        image = self.render(self.AREA)
        self.assertEqual(self.pixel(image, 255, 200, self.AREA).name(), "#00ff00")      # contour sous l'objet
        self.assertEqual(self.pixel(image, 200, 200, self.AREA).name(), "#ff0000")


class EffectsCommandTest(MaskTestCase):
    def test_live_slider_is_one_step_and_toggle(self):
        a = self.rect(100, 100, 100, 100)
        self.ctl.select([a])
        self.ctl.add_effect("shadow")
        count = self.scene.undo.count()
        for v in (5.0, 10.0, 15.0):
            self.ctl.set_effect("shadow", "dx", v)
        self.scene.commit_live()
        self.assertEqual(self.scene.undo.count(), count + 1)
        self.assertEqual(ap.effect(a.data, "shadow")["dx"], 15.0)
        self.ctl.toggle_effect("shadow")
        self.assertFalse(ap.effect(a.data, "shadow")["on"])
        self.assertFalse(ap.has_raster(a.data))
        self.scene.undo.undo()
        self.scene.undo.undo()
        self.assertEqual(ap.effect(a.data, "shadow")["dx"], ap.DEFAULTS["shadow"]["dx"])

    def test_expand_appearance(self):
        a = self.rect(100, 100, 100, 100)
        self.ctl.select([a])
        self.ctl.add_effect("offset")
        self.ctl.add_effect("shadow")
        self.ctl.add_extra_stroke()
        new = self.ctl.expand_appearance()
        self.assertEqual(len(new), 2)
        base = next(i for i in new if i.data["fill"] == a.data["fill"] or i.data.get("effects"))
        outline = next(i for i in new if i is not base)
        self.assertEqual([e["type"] for e in base.data["effects"]], ["shadow"])       # tramé : reste un effet
        self.assertAlmostEqual(base.geometry_rect().width(), 120.0, places=3)         # décalage appliqué
        self.assertLess(outline.zValue(), base.zValue())
        self.assertEqual(outline.data["group"], base.data["group"])
        self.scene.undo.undo()
        self.assertEqual(len(self.paths()), 1)


if __name__ == "__main__":
    unittest.main()
