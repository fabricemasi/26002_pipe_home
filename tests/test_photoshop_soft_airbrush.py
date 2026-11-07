"""Module Photoshop : POINTES DOUCES (balayage continu + union « sur » normalisée : fin de l'effet « peau de chenille » à dureté 0,
fusion des angles et des demi-tours) et AÉROGRAPHE (dépôt temporel : immobile, en mouvement, pression, relâchement, fréquence).
Le modèle de dépôt hybride (opacité / accumulation / retours) n'est PAS modifié : voir test_photoshop_hybrid_model.py."""
import os as _os, sys as _sys  # jamais les vrais réglages / presets de l'utilisateur (tests/_isolate.py)
_sys.path.insert(0, _os.path.dirname(_os.path.abspath(__file__)))
import _isolate  # noqa: E402,F401
import math
import os
import sys
import unittest

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from fm_photoshop import brush as B, model as M, presets
from _photoshop_case import PsCase


def resample(pts, step):
    out, carry = [pts[0]], 0.0
    for (x0, y0), (x1, y1) in zip(pts[:-1], pts[1:]):
        length = math.hypot(x1 - x0, y1 - y0)
        d = step - carry
        while d <= length:
            out.append((x0 + (x1 - x0) * d / length, y0 + (y1 - y0) * d / length))
            d += step
        carry = length - (d - step)
    out.append(pts[-1])
    return out


def run(pts, size=56.0, hardness=0.0, background=None, size_doc=(260, 170), **kw):
    doc = M.new_document(size_doc[0], size_doc[1], background=background)
    layer = doc.layers[0]
    kw.setdefault("spacing", 0.2)
    kw.setdefault("color", (0, 0, 0))
    s = B.Stroke(layer, "pixels", B.Brush(size=size, hardness=hardness, **kw), doc.rect())
    s.begin(*pts[0], 1.0)
    for i, p in enumerate(pts[1:], 1):
        s.move(p[0], p[1], 1.0, t=i / 120.0)
    s.finish_to(*pts[-1], 1.0)
    s.end()
    return layer.pix.read(doc.rect())[..., 3].astype(np.float32) / 255.0


def angle_path(deg, arm=95.0, vertex=(130.0, 85.0)):
    a = math.radians(180.0 - deg)
    p0 = (vertex[0] - arm, vertex[1])
    p2 = (vertex[0] - arm * math.cos(math.pi - a), vertex[1] - arm * math.sin(math.pi - a))
    return resample([p0, vertex, p2], 2.0)


class SoftTipContinuityTest(unittest.TestCase):
    def tearDown(self):
        B.TUNING.reset()

    def test_no_bead_ripple_along_a_straight_soft_stroke(self):
        # Avant : 5 niveaux crête à crête au centre à 8 % d'espacement (16 à 16 %) = « collier de perles ».
        for dense in (0.08, 0.04, 0.02):                                            # (pointe douce : le pas réel est le double)
            B.TUNING.continuous_spacing = dense
            a = run([(20.0 + i, 40.0) for i in range(221)], hardness=0.0, spacing=0.3)
            for offset in (0, 6, 12, 18):
                self.assertLessEqual(float(np.ptp(a[40 + offset, 90:190])) * 255.0, 1.01, f"pas {dense} décalage {offset}")

    def test_section_is_stable_across_stamp_spacings(self):
        profiles = []
        for dense in (0.02, 0.04, 0.08):                                             # (pas réels 4 %, 8 %, 16 % pour une pointe douce)
            B.TUNING.continuous_spacing = dense
            profiles.append(run([(20.0 + i, 40.0) for i in range(221)], hardness=0.0, spacing=0.3)[40:70, 140])
        self.assertLess(float(max(np.abs(p - profiles[1]).max() for p in profiles)), 0.012)

    def test_sweep_equals_the_union_of_dense_stamps_and_is_finite(self):
        rect = (0, 0, 100, 60)
        for hardness in (0.0, 0.3, 0.55):
            sweep = B.dab_alpha(30.3, 30.4, 40.0, hardness, rect, to=(64.7, 31.9))
            self.assertTrue(np.isfinite(sweep).all(), "NaN sur l'axe du segment")
            dense = np.max([B.dab_alpha(30.3 + (64.7 - 30.3) * i / 60.0, 30.4 + 1.5 * i / 60.0, 40.0, hardness, rect) for i in range(61)], axis=0)
            self.assertLess(float(np.abs(sweep - dense).max()), 0.012, f"dureté {hardness}")

    def test_angles_fuse_without_groove_cusp_or_lobe(self):
        straight = run([(20.0 + i, 85.0) for i in range(221)], hardness=0.0)
        slope = float(np.hypot(*np.gradient(straight)).max())                      # pente maximale d'un trait droit
        for deg in (15, 30, 45, 90, 135):
            a = run(angle_path(deg), hardness=0.0)
            half = math.radians(deg) / 2.0
            bis = [a[int(round(85 - math.sin(half) * t * 0.0)), int(round(130 - math.cos(half) * t))] for t in range(8, 31, 2)]
            self.assertGreater(min(bis), 0.97, f"rainure sur la bissectrice à {deg}°")
            self.assertLess(float(np.hypot(*np.gradient(a)).max()), 1.3 * slope, f"couture ou lobe à {deg}°")

    def test_u_turn_merges_the_two_passes(self):
        pts = resample([(30, 70), (220, 70), (30, 85)], 2.0)
        a = run(pts, hardness=0.0)
        column = a[55:100, 120]                                                     # coupe à travers les deux passages (15 px d'écart)
        self.assertGreater(float(column[10:30].min()), 0.9 * float(column.max()), "rainure entre l'aller et le retour")

    def test_no_seam_when_a_soft_stroke_crosses_itself(self):
        loop = []
        for i in range(241):
            t = i / 240.0 * 2 * math.pi
            loop.append((130 + 70 * math.sin(2 * t), 85 + 50 * math.sin(t)))
        a = run(resample(loop, 2.0), hardness=0.0, size=40.0)
        slope = float(np.hypot(*np.gradient(run([(20.0 + i, 85.0) for i in range(221)], hardness=0.0, size=40.0))).max())
        self.assertLess(float(np.hypot(*np.gradient(a)).max()), 1.35 * slope)

    def test_hardness_is_continuous_around_zero_and_the_soft_union_limit(self):
        line = [(20.0 + i, 40.0) for i in range(221)]
        base = run(line, hardness=0.0)[20:70, 140]
        for h, limit in ((0.01, 0.02), (0.05, 0.06)):                                  # écart proportionnel au changement de dureté
            self.assertLess(float(np.abs(run(line, hardness=h)[20:70, 140] - base).max()), limit, f"saut de 0 % à {h:.0%}")
        low, high = run(line, hardness=0.799)[20:70, 140], run(line, hardness=0.801)[20:70, 140]
        self.assertLess(float(np.abs(low - high).max()), 0.01, "saut à la limite de l union douce (80 %)")
        self.assertFalse(B.Stroke(M.new_document(40, 40).layers[0], "pixels", B.Brush(size=20, hardness=0.8), (0, 0, 40, 40))._soft)

    def test_apparent_diameter_is_not_inflated_beyond_the_union_of_overlapping_stamps(self):
        line = [(20.0 + i, 40.0) for i in range(221)]
        B.TUNING.soft_union = 0.0
        single = run(line, hardness=0.0)[40:70, 140]
        B.TUNING.reset()
        fused = run(line, hardness=0.0)[40:70, 140]
        half = lambda col: float(np.interp(0.5, col[::-1], np.arange(len(col))[::-1]))
        self.assertGreater(half(fused), half(single))                               # la fusion épaissit le cœur (comme Photoshop)…
        self.assertLess(half(fused), 1.35 * half(single))                           # … sans gonfler le diamètre
        self.assertLess(float(fused[28]), 0.1)                                      # et la pointe reste nulle au rayon nominal (28 px)

    def test_wide_wobbly_soft_stroke_has_no_lobes_in_its_faint_fringe(self):
        # Capture de l'utilisateur : trait doux très large dont la frange faible portait des lobes (un maximum avec la pointe
        # seule gardait chaque coude de la trajectoire). Ondulation de 12 px sur 45 px, D = 112 : le bord à 15 % de densité
        # ondulait de 7,5 px, il doit maintenant ondoler comme l'union « sur » de Photoshop (~2 px).
        pts = []
        x = 40.0
        while x < 440.0:
            pts.append((x, 130 + 30 * math.sin((x - 40) / 150.0) + 12 * math.sin((x - 40) / 45.0 * 2 * math.pi)))
            x += 8.0
        for hardness, limit in ((0.0, 3.2), (0.3, 4.0), (0.5, 4.5)):
            a = run(pts, size=112.0, hardness=hardness, size_doc=(480, 250))
            for level in (0.15, 0.5):
                ys = np.array([int(np.argmax(a[:, x] > level)) for x in range(90, 400)], float)
                ripple = float(np.ptp((ys - np.convolve(ys, np.ones(61) / 61, mode="same"))[40:-40]))
                self.assertLess(ripple, limit, f"dureté {hardness} niveau {level} : ondulation {ripple:.1f} px")

    def test_a_single_press_keeps_a_full_core(self):
        a = run([(60.0, 60.0), (60.0, 60.0)], size=56.0, hardness=0.0, size_doc=(120, 120))
        self.assertGreater(float(a[60, 60]), 0.995)

    def test_soft_union_can_be_switched_off(self):
        line = [(20.0 + i, 40.0) for i in range(221)]
        B.TUNING.soft_union = 0.0
        self.assertEqual(B._soft_weight(0.0, 56.0), 0.0)
        a = run(line, hardness=0.0)
        self.assertAlmostEqual(float(a[40, 140]), 1.0, delta=0.01)


class AirbrushTest(unittest.TestCase):
    def tearDown(self):
        B.TUNING.reset()

    @staticmethod
    def hold(seconds, hz, mode="wash", flow=0.3, opacity=1.0, pressure=1.0, hardness=0.0, size=60.0, background=None):
        doc = M.new_document(120, 120, background=background)
        layer = doc.layers[0]
        brush = B.Brush(size=size, hardness=hardness, flow=flow, opacity=opacity, paint_mode=mode, airbrush=True, color=(0, 0, 0))
        stroke = B.Stroke(layer, "pixels", brush, doc.rect())
        t0 = 100.0
        stroke.begin(60.0, 60.0, pressure, air_now=t0)
        for i in range(1, int(round(seconds * hz)) + 1):
            stroke.air_tick(t0 + i / hz)
        stroke.finish_to(60.0, 60.0, 0.0)
        stroke.end()
        return layer, doc, stroke

    @staticmethod
    def alpha(layer, doc, dx=0):
        return float(layer.pix.read((60 + dx, 60, 61 + dx, 61))[0, 0, 3]) / 255.0

    def test_stationary_pen_keeps_depositing_in_both_modes(self):
        for mode, scale in (("wash", 0.8), ("buildup", 1.0)):
            values = []
            for seconds in (0.5, 2.0, 5.0):
                layer, doc, _s = self.hold(seconds, 60, mode=mode, flow=0.3, opacity=0.8 if mode == "wash" else 1.0)
                values.append(self.alpha(layer, doc))
                expected = (1 - 0.7 ** (seconds + B.TUNING.air_first)) * scale
                self.assertAlmostEqual(values[-1], expected, delta=0.01, msg=f"{mode} {seconds} s")
            self.assertTrue(values[0] < values[1] < values[2], values)                  # la densité augmente avec la durée

    def test_ceiling_is_never_exceeded_while_accumulation_keeps_building(self):
        layer, doc, _s = self.hold(20.0, 60, mode="wash", flow=0.3, opacity=0.6)
        self.assertLessEqual(self.alpha(layer, doc), 0.6 + 1e-3)
        self.assertGreater(self.alpha(layer, doc), 0.59)
        layer, doc, _s = self.hold(3.0, 60, mode="buildup", flow=0.3, opacity=0.6)
        before = self.alpha(layer, doc)
        layer, doc, _s = self.hold(20.0, 60, mode="buildup", flow=0.3, opacity=0.6)
        self.assertGreater(self.alpha(layer, doc), before + 0.2)
        self.assertGreater(self.alpha(layer, doc), 0.95)                               # accumulation : vers la pleine densité

    def test_result_does_not_depend_on_the_update_frequency(self):
        for mode in ("wash", "buildup"):
            results = [self.alpha(*self.hold(2.0, hz, mode=mode, flow=0.3)[:2], dx) for hz in (30, 60, 120) for dx in (0, 12)]
            for dx in range(2):
                trio = results[dx::2]
                self.assertLess(max(trio) - min(trio), 0.002, f"{mode} décalage {dx}")

    def test_abnormally_long_interval_does_not_deposit_explosively(self):
        doc = M.new_document(120, 120, background=None)
        layer = doc.layers[0]
        stroke = B.Stroke(layer, "pixels", B.Brush(size=60, hardness=0.0, flow=0.3, airbrush=True, color=(0, 0, 0)), doc.rect())
        stroke.begin(60.0, 60.0, 1.0, air_now=10.0)
        stroke.air_tick(10.0 + 5.0)                                                   # interface bloquée 5 s
        stroke.finish_to(60.0, 60.0, 0.0)
        self.assertLessEqual(stroke.air_seconds, B.TUNING.air_first + B.TUNING.air_dt_max + 1e-9)

    def test_pressure_changes_without_movement_feed_the_deposit(self):
        doc = M.new_document(120, 120, background=None)
        layer = doc.layers[0]
        brush = B.Brush(size=60, hardness=0.0, flow=0.5, paint_mode="buildup", pressure_flow=True, airbrush=True, color=(0, 0, 0))
        stroke = B.Stroke(layer, "pixels", brush, doc.rect())
        t = 50.0
        stroke.begin(60.0, 60.0, 1.0, air_now=t)
        for i in range(1, 61):                                                          # 1 s immobile à la pression 1,0
            stroke.air_tick(t + i / 60.0)
        t += 1.0
        stroke.move(60.0, 60.0, 0.4, t=t, air_now=t)                                    # une nouvelle mesure de pression, sans déplacement
        for i in range(1, 61):                                                          # 1 s immobile à la dernière pression valide (0,4)
            stroke.air_tick(t + i / 60.0)
        stroke.finish_to(60.0, 60.0, 0.0)
        stroke.end()
        a = self.alpha(layer, doc)
        expected = 1.0 - 0.5 ** (1.0 + B.TUNING.air_first) * 0.8 ** 1.0                  # (1 − 0,5)^1 puis (1 − 0,5·0,4)^1
        self.assertAlmostEqual(a, expected, delta=0.02)

    def test_release_stops_the_deposit_immediately(self):
        layer, doc, stroke = self.hold(1.0, 60)
        before = layer.pix.read(doc.rect()).copy()
        self.assertIsNone(stroke.air_tick(200.0))
        self.assertIsNone(stroke.air_tick(300.0))
        self.assertTrue(np.array_equal(layer.pix.read(doc.rect()), before))
        self.assertEqual(stroke._air_queue, [])

    def test_a_tap_leaves_a_faint_dot_and_release_adds_no_stamp(self):
        doc = M.new_document(120, 120, background=None)
        layer = doc.layers[0]
        stroke = B.Stroke(layer, "pixels", B.Brush(size=60, hardness=0.0, flow=0.5, airbrush=True, color=(0, 0, 0)), doc.rect())
        stroke.begin(60.0, 60.0, 1.0, air_now=5.0)
        dabs = stroke.dabs
        self.assertIsNone(stroke.finish_to(60.0, 60.0, 0.0))
        self.assertEqual(stroke.dabs, dabs)
        self.assertGreater(self.alpha(layer, doc), 0.0)

    def test_slower_movement_exposes_longer_than_faster_movement(self):
        def pass_alpha(speed):
            doc = M.new_document(260, 100, background=None)
            layer = doc.layers[0]
            stroke = B.Stroke(layer, "pixels", B.Brush(size=40, hardness=0.5, flow=0.4, paint_mode="buildup", airbrush=True,
                                                        spacing=0.1, color=(0, 0, 0)), doc.rect())
            t = 0.0
            stroke.begin(20.0, 50.0, 1.0, air_now=t)
            x = 20.0
            while x < 230.0:
                dt = 1.0 / 120.0
                x += speed * dt
                t += dt
                stroke.move(x, 50.0, 1.0, t=t, air_now=t)
            stroke.finish_to(x, 50.0, 0.0)
            stroke.end()
            return float(layer.pix.read((120, 50, 121, 51))[0, 0, 3]) / 255.0
        slow, fast = pass_alpha(100.0), pass_alpha(400.0)
        self.assertGreater(slow, fast + 0.08)
        exposure = lambda a: -math.log(1.0 - a)
        self.assertAlmostEqual(exposure(slow) / exposure(fast), 4.0, delta=0.6)       # exposition ∝ 1 / vitesse

    def test_air_channel_is_isolated_from_the_hybrid_deposit_state(self):
        _layer, _doc, stroke = self.hold(0.5, 60)
        self.assertEqual(stroke._cov, {})
        self.assertEqual(stroke._base, {})
        self.assertGreater(len(stroke._air_cov), 0)

    def test_repeated_strokes_accumulate_over_each_other(self):
        doc = M.new_document(120, 120, background=None)
        layer = doc.layers[0]
        values = []
        for _ in range(3):
            brush = B.Brush(size=60, hardness=0.0, flow=0.3, paint_mode="buildup", airbrush=True, color=(0, 0, 0))
            stroke = B.Stroke(layer, "pixels", brush, doc.rect())
            stroke.begin(60.0, 60.0, 1.0, air_now=0.0)
            for i in range(1, 31):
                stroke.air_tick(i / 60.0)
            stroke.finish_to(60.0, 60.0, 0.0)
            stroke.end()
            values.append(self.alpha(layer, doc))
        self.assertTrue(values[0] < values[1] < values[2], values)

    def test_works_on_an_opaque_background_and_with_a_colour(self):
        layer, doc, _s = self.hold(2.0, 60, mode="buildup", flow=0.3, background=(255, 255, 255, 255))
        grey = float(layer.pix.read((60, 60, 61, 61))[0, 0, 0])
        self.assertAlmostEqual((255.0 - grey) / 255.0, 1 - 0.7 ** (2.0 + B.TUNING.air_first), delta=0.015)

    def test_selection_limits_the_airbrush(self):
        class Half:
            def coverage(self, rect):
                out = np.zeros((rect[3] - rect[1], rect[2] - rect[0]), np.float32)
                out[:, np.arange(rect[0], rect[2]) < 60] = 1.0
                return out
        doc = M.new_document(120, 120, background=None)
        layer = doc.layers[0]
        stroke = B.Stroke(layer, "pixels", B.Brush(size=60, hardness=0.0, flow=0.5, airbrush=True, color=(0, 0, 0)), doc.rect(), Half())
        stroke.begin(60.0, 60.0, 1.0, air_now=0.0)
        for i in range(1, 61):
            stroke.air_tick(i / 60.0)
        stroke.end()
        self.assertGreater(self.alpha(layer, doc, -10), 0.1)
        self.assertEqual(self.alpha(layer, doc, 10), 0.0)


class AirbrushCanvasTest(PsCase):
    def test_timer_lives_only_during_an_airbrush_stroke(self):
        _item, std = self.editor(120, 120, zoom=1.0, background="Transparent")
        canvas, s = std.canvas, std.session
        s.tool = "brush"
        s.brush.airbrush = True
        s.brush.size = 40
        s.brush.hardness = 0.0
        self.assertFalse(canvas._air_timer.isActive())
        canvas.begin_stroke(60.0, 60.0, 1.0)
        self.assertTrue(canvas._air_timer.isActive())
        canvas._air_tick()
        canvas.end_stroke(60.0, 60.0, 0.0)
        self.assertFalse(canvas._air_timer.isActive())
        self.assertIsNone(canvas._stroke)
        canvas._air_tick()                                                              # un tick tardif ne fait rien
        s.brush.airbrush = False
        canvas.begin_stroke(60.0, 60.0, 1.0)
        self.assertFalse(canvas._air_timer.isActive())
        canvas.end_stroke(60.0, 60.0, 0.0)

    def test_factory_preset_and_panel_expose_the_airbrush(self):
        names = {b.name: b for b in presets.FACTORY}
        self.assertTrue(names["Aérographe"].airbrush)
        self.assertFalse(names["Rond dur 20"].airbrush)
        self.assertTrue(B.Brush.from_dict(names["Aérographe"].to_dict()).airbrush)
        self.assertFalse(B.Brush.from_dict({"size": 10}).airbrush)                       # ancienne présélection : inchangée


if __name__ == "__main__":
    unittest.main()
