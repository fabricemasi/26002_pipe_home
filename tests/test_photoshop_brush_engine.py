"""Module Photoshop : banc du MOTEUR DE TRAIT, indépendant de toute tablette. Traits générés mathématiquement (pression
constante ou synthétique), comparés à une référence analytique : géométrie du contour, indépendance vis-à-vis de la
fréquence d'échantillonnage et de l'espacement, extrémités, courbes de pression, modes de lissage, journal du stylet."""
import os as _os, sys as _sys  # jamais les vrais réglages / presets de l'utilisateur (tests/_isolate.py)
_sys.path.insert(0, _os.path.dirname(_os.path.abspath(__file__)))
import _isolate  # noqa: E402,F401
import math
import os
import sys
import tempfile
import unittest

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from fm_photoshop import brush as B, model as M
from fm_photoshop.pen_input import OneEuro, Weighted
from fm_photoshop.pen_log import PenLog

SS = 4


def densify(pts, step):
    out = [pts[0]]
    for (x0, y0), (x1, y1) in zip(pts[:-1], pts[1:]):
        n = max(1, int(math.hypot(x1 - x0, y1 - y0) / step))
        out.extend((x0 + (x1 - x0) * i / n, y0 + (y1 - y0) * i / n) for i in range(1, n + 1))
    return out


def reference(w, h, pts, diameter):
    """Couverture exacte (suréchantillonnée) d'un trait de diamètre constant le long de la polyligne."""
    ys, xs = np.mgrid[0:h * SS, 0:w * SS].astype(np.float32)
    px, py = (xs + 0.5) / SS, (ys + 0.5) / SS
    r = diameter / 2.0
    inside = np.zeros(px.shape, bool)
    for (x0, y0), (x1, y1) in zip(pts[:-1], pts[1:]):
        xa, xb = int(max(0, (min(x0, x1) - r - 1) * SS)), int(min(px.shape[1], (max(x0, x1) + r + 1) * SS))
        ya, yb = int(max(0, (min(y0, y1) - r - 1) * SS)), int(min(px.shape[0], (max(y0, y1) + r + 1) * SS))
        if xb <= xa or yb <= ya:
            continue
        sx, sy = px[ya:yb, xa:xb], py[ya:yb, xa:xb]
        dx, dy = x1 - x0, y1 - y0
        t = np.clip(((sx - x0) * dx + (sy - y0) * dy) / max(dx * dx + dy * dy, 1e-9), 0, 1)
        inside[ya:yb, xa:xb] |= np.hypot(sx - (x0 + t * dx), sy - (y0 + t * dy)) <= r
    return inside.astype(np.float32).reshape(h, SS, w, SS).mean(axis=(1, 3))


def paint(pts, brush, pressures=None, size=(120, 120), step=2.0, hz=120.0):
    """Trait déterministe : points densifiés à `step` px, horodatés à `hz`, pression par point (ou 1.0)."""
    doc = M.new_document(size[0], size[1], background=None)
    layer = doc.layers[0]
    dense = densify(pts, step)
    pr = pressures if pressures is not None else [1.0] * len(dense)
    stroke = B.Stroke(layer, "pixels", brush, doc.rect())
    stroke.begin(dense[0][0], dense[0][1], pr[0])
    for i in range(1, len(dense)):
        stroke.move(dense[i][0], dense[i][1], pr[i], t=i / hz)
    stroke.finish_to(dense[-1][0], dense[-1][1], 0.0)          # (pression de relâchement nulle : doit être ignorée)
    stroke.end()
    return layer.pix.read(doc.rect())[..., 3].astype(np.float32) / 255.0, stroke


def shapes():
    t = np.linspace(0, 2 * math.pi, 120)
    return {"horizontale": [(10.3, 30.4), (110.7, 30.4)], "diagonale": [(10.3, 10.4), (108.7, 100.1)],
            "cercle": [(60 + 40 * math.cos(a), 60 + 40 * math.sin(a)) for a in t],
            "angle": [(20.2, 20.3), (90.4, 20.3), (90.4, 90.9)]}


class DeterministicRenderTest(unittest.TestCase):
    """Pression constante 1.0, aucun lissage : le contour doit être celui de la géométrie, rien d'autre."""

    def test_stroke_matches_the_analytic_reference(self):
        for diameter in (3.0, 12.0, 30.0):
            for name, pts in shapes().items():
                brush = B.Brush(size=diameter, hardness=1.0, spacing=0.08)
                got, _s = paint(pts, brush)
                ref = reference(120, 120, densify(pts, 2.0), diameter)
                area = got.sum() / ref.sum() - 1.0
                self.assertLess(abs(area), 0.025 if diameter < 5 else 0.01, f"{name} d={diameter} aire {area:+.3%}")
                self.assertLess(float(np.abs(got - ref)[ref > 0.001].mean()), 0.04, f"{name} d={diameter}")

    def test_edge_does_not_harden_with_denser_stamps(self):
        # Avant : le cumul « sur » des bords anticrénelés grossissait le trait de 3 à 10 % et durcissait le contour.
        pts = shapes()["diagonale"]
        loose, _a = paint(pts, B.Brush(size=12, hardness=1.0, spacing=0.20))
        tight, _b = paint(pts, B.Brush(size=12, hardness=1.0, spacing=0.02))
        self.assertLess(abs(tight.sum() / loose.sum() - 1.0), 0.01)
        self.assertLess(float(np.abs(tight - loose).max()), 0.12)

    def test_horizontal_edge_coverage_is_exact(self):
        got, _s = paint(shapes()["horizontale"], B.Brush(size=20, hardness=1.0))
        column = got[:, 60]
        self.assertAlmostEqual(float(column.sum()), 20.0, delta=0.05)           # épaisseur exacte du trait
        self.assertAlmostEqual(float(column[20]), 0.6, delta=0.02)               # bord à y = 20,4 : pixel couvert à 60 %

    def test_independent_of_sampling_frequency(self):
        pts = shapes()["cercle"]
        brush = B.Brush(size=10, hardness=1.0)
        fine, _a = paint(pts, brush, step=0.5)
        coarse, _b = paint(pts, brush, step=4.0)
        self.assertLess(abs(coarse.sum() / fine.sum() - 1.0), 0.02)

    def test_both_ends_are_complete_round_caps(self):
        pts = shapes()["horizontale"]
        got, stroke = paint(pts, B.Brush(size=20, hardness=1.0, spacing=0.25))
        ref = reference(120, 120, densify(pts, 2.0), 20)
        for x0, x1 in ((0, 25), (95, 120)):
            self.assertLess(abs(got[:, x0:x1].sum() / ref[:, x0:x1].sum() - 1.0), 0.02)

    def test_soft_brush_keeps_a_smooth_profile(self):
        got, _s = paint(shapes()["horizontale"], B.Brush(size=30, hardness=0.3, spacing=0.08))
        column = got[:, 60]
        self.assertGreater(float(column.max()), 0.99)
        self.assertLess(float(np.abs(np.diff(column)).max()), 0.25)               # pas de marche dans le dégradé

    def test_soft_brush_edge_is_anti_aliased_by_pixel_area_not_by_widening(self):
        # Dureté 80 % à d = 6 : le dégradé nominal ne fait que 0,6 px. L'anticrénelage est la MOYENNE du profil sur l'aire de
        # chaque pixel (plus de bord binaire, plus d'élargissement artificiel du dégradé) : beaucoup de pixels partiels en
        # bordure, et le diamètre perçu reste le diamètre demandé.
        for diameter in (3.0, 6.0, 12.0):
            got, _s = paint(shapes()["diagonale"], B.Brush(size=diameter, hardness=0.8, spacing=0.2))
            full = int((got >= 0.98).sum())
            partial = int(((got > 0.02) & (got < 0.98)).sum())
            self.assertGreater(partial / max(full, 1), 0.2 if diameter >= 12 else 0.4, f"d={diameter}")
        # le bord n'est PAS élargi : la matière du trait suit le diamètre nominal (dégradé nominal 0,2·R centré à 0,9·R)
        thin, _s = paint(shapes()["horizontale"], B.Brush(size=6.0, hardness=0.8, spacing=0.08))
        self.assertAlmostEqual(float(thin[:, 60].sum()), 5.4, delta=0.15)           # 2 · (R·h + largeur/2) = 2 · (2,4 + 0,3)
        flat = B.dab_alpha(20.0, 20.5, 6.0, 0.8, (0, 20, 40, 21))[0]
        self.assertEqual(int((flat[24:] > 0.001).sum()), 0)                           # nul au-delà du rayon (+ marge d'un pixel)

    def test_tiny_diameter_has_area_proportional_coverage(self):
        small, _s = paint([(20.5, 20.5), (60.5, 20.5)], B.Brush(size=0.5, hardness=1.0), size=(80, 40))
        mid = paint([(20.5, 20.5), (60.5, 20.5)], B.Brush(size=1.0, hardness=1.0), size=(80, 40))[0]
        self.assertAlmostEqual(float(small.sum() / mid.sum()), 0.5, delta=0.03)  # un demi-pixel de large : moitié moins de matière


class PressureTest(unittest.TestCase):
    """La pression est un signal indépendant ; chaque paramètre a sa courbe ; D = Dmax (m + (1 - m) f(p))."""

    def tearDown(self):
        B.TUNING.reset()

    def _widths(self, pressures, brush=None, length=100):
        pts = [(10.0, 30.0), (10.0 + length, 30.0)]
        n = len(densify(pts, 2.0))
        brush = brush or B.Brush(size=24, hardness=1.0, spacing=0.08, pressure_size=True)
        got, _s = paint(pts, brush, pressures=[pressures(i / (n - 1)) for i in range(n)], size=(140, 60))
        return got.sum(axis=0)[10:110]

    def test_linear_ramp_gives_the_expected_diameter(self):
        widths = self._widths(lambda u: u)                                        # rampe 0 -> 1, courbe linéaire par défaut
        for x in (20, 50, 80):
            self.assertAlmostEqual(float(widths[x]), 24.0 * (x + 0.0) / 100.0, delta=1.6)

    def test_ramp_is_progressive_without_steps(self):
        widths = self._widths(lambda u: u)
        self.assertLess(float(np.abs(np.diff(widths[5:95])).max()), 0.6)         # pas de palier ni de bosse

    def test_minimum_diameter_and_curve(self):
        B.TUNING.min_diameter = 0.25
        low = self._widths(lambda u: 0.0)
        self.assertAlmostEqual(float(low[50]), 6.0, delta=0.6)                    # D = Dmax x m à pression nulle
        B.TUNING.reset()
        B.TUNING.size_gamma = 2.0
        self.assertAlmostEqual(float(self._widths(lambda u: 0.5)[50]), 24.0 * 0.25, delta=0.7)   # f(p) = p^2

    def test_sudden_pressure_change_stays_sharp_with_raw_pressure(self):
        widths = self._widths(lambda u: 0.2 if u < 0.5 else 1.0)
        self.assertAlmostEqual(float(widths[25]), 24 * 0.2, delta=0.8)             # avant le saut : palier à D = 0,2 Dmax
        self.assertGreater(float(widths[75]), 23.0)                               # après : plein diamètre
        # le saut n'est élargi que par le rayon du tampon plein (12 px) : aucun étalement dû au filtrage de la pression
        start = int(np.argmax(widths > 8.0))
        self.assertGreaterEqual(start, 50 - 13)
        self.assertLessEqual(int(np.argmax(widths > 23.0)) - 50, 14)

    def test_sinusoid_follows_pressure_position(self):
        widths = self._widths(lambda u: 0.5 + 0.5 * math.sin(4 * math.pi * u))
        radius = np.array([12.0 * (0.5 + 0.5 * math.sin(4 * math.pi * (c / 100.0))) for c in range(101)])
        # largeur attendue = ENVELOPPE des disques (centre c, rayon r(c)) : ce que tout moteur à tampons doit produire
        expected = np.array([2.0 * max(math.sqrt(max(0.0, radius[c] ** 2 - (x + 0.5 - c) ** 2)) for c in range(101))
                             for x in range(100)])
        self.assertLess(float(np.abs(widths[14:86] - expected[14:86]).max()), 1.2)   # diamètre à la BONNE position

    def test_opacity_and_flow_have_their_own_curves(self):
        B.TUNING.opacity_gamma = 2.0
        pts = [(10.0, 20.0), (100.0, 20.0)]
        n = len(densify(pts, 2.0))
        brush = B.Brush(size=10, hardness=1.0, spacing=0.08, pressure_opacity=True)
        got, _s = paint(pts, brush, pressures=[0.5] * n, size=(120, 40))
        self.assertAlmostEqual(float(got[20, 50]), 0.25, delta=0.02)              # opacité = p^2 = 0,25
        B.TUNING.reset()
        brush = B.Brush(size=10, hardness=1.0, spacing=0.08, pressure_opacity=True, pressure_flow=True)
        light, _s = paint(pts, brush, pressures=[0.3] * n, size=(120, 40))
        # opacité 0,3 x débit 0,3 = dose de 0,09 PAR PASSAGE (indépendante de l'espacement) ; un repassage s'y ajoute
        self.assertAlmostEqual(float(light[20, 50]), 0.09, delta=0.01)

    def test_release_pressure_zero_is_ignored_and_no_dot_is_added(self):
        pts = [(10.0, 20.0), (60.0, 20.0)]
        n = len(densify(pts, 2.0))
        brush = B.Brush(size=14, hardness=1.0, spacing=0.08, pressure_size=True)
        got, _s = paint(pts, brush, pressures=[0.8] * n, size=(80, 40))           # finish_to reçoit une pression nulle
        self.assertGreater(float(got[:, 55:65].sum()), 14 * 5 * 0.9)              # bout plein, pas amaigri par le relâchement

    def test_first_event_with_near_zero_pressure_does_not_make_a_start_dot(self):
        pts = [(20.0, 20.0), (80.0, 20.0)]
        n = len(densify(pts, 2.0))
        pressures = [0.02] + [0.6] * (n - 1)                                       # le contact commence presque à vide
        brush = B.Brush(size=20, hardness=1.0, spacing=0.08, pressure_size=True)
        got, _s = paint(pts, brush, pressures=pressures, size=(100, 40))
        widths = got.sum(axis=0)
        self.assertGreater(float(widths[24]), 7.0)                                 # le départ n'est pas une pointe isolée
        self.assertGreaterEqual(float(np.diff(widths[17:32]).min()), -0.3)         # le départ s'ÉVASE sans pincement ni bosse
        self.assertLess(float(np.abs(np.diff(widths[32:70])).max()), 0.3)          # puis diamètre constant

    def test_press_without_move_paints_a_dot_at_maximum_pressure(self):
        doc = M.new_document(40, 40, background=None)
        layer = doc.layers[0]
        stroke = B.Stroke(layer, "pixels", B.Brush(size=16, hardness=1.0, pressure_size=True), doc.rect())
        stroke.begin(20, 20, 0.1)
        stroke.move(20, 20, 0.9, t=0.01)
        stroke.finish_to(20, 20, 0.0)
        stroke.end()
        self.assertGreater(layer.pix.read(doc.rect())[..., 3].astype(float).sum() / 255.0, 100.0)

    def test_pressure_filter_delays_but_default_is_raw(self):
        self.assertEqual(B.Tuning().pressure_filter, 1.0)
        raw = self._widths(lambda u: 0.2 if u < 0.5 else 1.0)
        B.TUNING.pressure_filter = 0.15
        slow = self._widths(lambda u: 0.2 if u < 0.5 else 1.0)
        self.assertLess(float(slow[56]), float(raw[56]))


class SmoothingModesTest(unittest.TestCase):
    def test_none_mode_is_exactly_the_input_path(self):
        pts = [(10 + 1.3 * i, 20 + 0.6 * math.sin(i)) for i in range(60)]
        doc = M.new_document(100, 40, background=None)
        stroke = B.Stroke(doc.layers[0], "pixels", B.Brush(size=4, hardness=1.0), doc.rect())
        stroke.begin(*pts[0])
        for i, p in enumerate(pts[1:], 1):
            stroke.move(*p, 1.0, t=i / 120.0)
            self.assertEqual(stroke.info["used"], p)                               # aucune moyenne, aucun retard

    def test_one_euro_lag_and_noise(self):
        import random
        rnd = random.Random(3)
        for speed, max_lag in ((30, 1.5), (600, 4.0), (2000, 4.5)):
            f, lag, err = OneEuro(), [], []
            for i in range(240):
                t = i / 120.0
                tx = 20 + speed * t
                x, y = f.apply(tx + rnd.gauss(0, 0.4), 50 + rnd.gauss(0, 0.4), t, 30.0 * 0.125 + 0.3, 0.05)
                if i > 120:
                    lag.append(tx - x)
                    err.append(y - 50)
            self.assertLess(float(np.mean(lag)), max_lag, f"v={speed}")
        slow = []
        f = OneEuro()
        for i in range(240):
            _x, y = f.apply(20 + 30 * i / 120.0 + rnd.gauss(0, 0.4), 50 + rnd.gauss(0, 0.4), i / 120.0, 4.05, 0.05)
            if i > 120:
                slow.append(y - 50)
        self.assertLess(float(np.std(slow)), 0.4 * 0.45)                           # bruit lent fortement atténué

    def test_one_euro_uses_real_time_not_a_fixed_rate(self):
        a, b = OneEuro(), OneEuro()
        for i in range(30):
            a.apply(i * 2.0, 0.0, i * 0.004, 5.0, 0.0)                              # 250 Hz
            b.apply(i * 2.0, 0.0, i * 0.016, 5.0, 0.0)                              # 62,5 Hz, mêmes positions
        self.assertGreater(b.out[0], a.out[0])                                       # plus d'écart de temps : on suit davantage

    def test_one_euro_stops_without_drift(self):
        f = OneEuro()
        for i in range(60):
            f.apply(i * 3.0, 0.0, i / 120.0, 4.0, 0.05)
        for i in range(60, 400):
            out = f.apply(177.0, 0.0, i / 120.0, 4.0, 0.05)
        self.assertAlmostEqual(out[0], 177.0, delta=0.05)

    def test_weighted_keeps_a_sharp_corner(self):
        w = Weighted()
        out = None
        for i in range(30):
            out = w.apply(i * 2.0, 0.0, i / 120.0, 24.0)
        for j in range(1, 12):
            out = w.apply(58.0, j * 2.0, (30 + j) / 120.0, 24.0)
        self.assertAlmostEqual(out[0], 58.0, delta=1.0)                              # l'angle voulu n'est pas arrondi : on reste sur la verticale

    def test_stabilizer_is_independent_and_off_means_no_lag(self):
        doc = M.new_document(200, 40, background=None)
        direct = B.Stroke(doc.layers[0], "pixels", B.Brush(size=4, hardness=1.0, smoothing_mode="stabilizer", smoothing=0.0), doc.rect())
        direct.begin(10, 20)
        direct.move(100, 20, 1.0, t=0.01)
        self.assertEqual(direct._pos, (100.0, 20.0))                                  # intensité nulle : aucune corde
        rope = B.Stroke(doc.layers[0], "pixels", B.Brush(size=4, hardness=1.0, smoothing_mode="stabilizer", smoothing=0.5), doc.rect())
        rope.begin(10, 20)
        rope.move(100, 20, 1.0, t=0.01)
        self.assertAlmostEqual(rope._pos[0], 50.0, delta=0.01)                         # corde de 50 px : la pointe reste 50 px derrière

    def test_brush_without_mode_keeps_its_old_stabilizer(self):
        self.assertEqual(B.Brush(smoothing=0.4).smoothing_kind(), "stabilizer")
        self.assertEqual(B.Brush(smoothing=0.0).smoothing_kind(), "none")
        self.assertEqual(B.Brush(smoothing=0.4, smoothing_mode="none").smoothing_kind(), "none")
        self.assertEqual(B.Brush.from_dict({"smoothing": 0.4, "smoothing_mode": "adaptive"}).smoothing_kind(), "adaptive")
        self.assertEqual(B.Brush.from_dict({"smoothing": 0.4, "smoothing_mode": "bidon"}).smoothing_kind(), "stabilizer")


class ScenarioTest(unittest.TestCase):
    """Scénarios du cahier des charges : zoom, souris, gros diamètre, grand canevas, répétition prolongée."""

    def test_filters_work_in_screen_space_whatever_the_zoom(self):
        results = []
        for zoom in (0.5, 1.0, 4.0):
            doc = M.new_document(2000, 100, background=None)
            stroke = B.Stroke(doc.layers[0], "pixels", B.Brush(size=4, hardness=1.0, smoothing=0.6, smoothing_mode="adaptive"), doc.rect())
            stroke.zoom = zoom
            stroke.begin(10, 50)
            for i in range(1, 80):
                stroke.move(10 + i * 3.0 / zoom, 50 + (1.0 if i % 2 else -1.0) * 0.8 / zoom, 1.0, t=i / 120.0)
            results.append((stroke.info["used"][1] - 50) * zoom)                             # position filtrée, vue à l'écran
        self.assertAlmostEqual(results[0], results[2], delta=0.02 * 4.0 + 0.02)       # même geste à l'écran = même filtrage

    def test_mouse_uses_an_explicit_constant_pressure(self):
        doc = M.new_document(60, 40, background=None)
        stroke = B.Stroke(doc.layers[0], "pixels", B.Brush(size=10, hardness=1.0, pressure_size=True), doc.rect())
        stroke.begin(10, 20, 1.0)
        stroke.move(40, 20, 1.0, t=0.01)
        self.assertEqual(stroke.info["size"], 10.0)                                    # pression 1,0 : plein diamètre, jamais amaigri

    def test_very_large_diameter_is_exact_and_stays_fast(self):
        import time
        doc = M.new_document(1400, 900, background=None)
        layer = doc.layers[0]
        stroke = B.Stroke(layer, "pixels", B.Brush(size=400, hardness=1.0, spacing=0.08), doc.rect())
        start = time.perf_counter()
        stroke.begin(300, 450)
        for i in range(1, 40):
            stroke.move(300 + i * 20.0, 450, 1.0, t=i / 120.0)
        stroke.finish_to(1080, 450, 1.0)
        stroke.end()
        elapsed = time.perf_counter() - start
        area = float(layer.pix.read(doc.rect())[..., 3].astype(np.float64).sum() / 255.0)
        expected = 400 * (1080 - 300) + math.pi * 200 ** 2
        self.assertLess(abs(area / expected - 1.0), 0.003)
        self.assertLess(elapsed, 4.0)

    def test_repeated_strokes_do_not_slow_down(self):
        import time
        doc = M.new_document(400, 300, background=None)
        layer = doc.layers[0]
        durations = []
        for k in range(60):
            start = time.perf_counter()
            stroke = B.Stroke(layer, "pixels", B.Brush(size=16, hardness=0.8), doc.rect())
            stroke.begin(20, 20 + 4 * (k % 60))
            for i in range(1, 40):
                stroke.move(20 + i * 8.0, 20 + 4 * (k % 60) + 5 * math.sin(i / 3), 1.0, t=i / 120.0)
            stroke.finish_to(332, 20 + 4 * (k % 60))
            stroke.end()
            durations.append(time.perf_counter() - start)
        self.assertLess(float(np.median(durations[-10:])), float(np.median(durations[:10])) * 3.0 + 0.01)


class PenLogTest(unittest.TestCase):
    def test_stats_and_replay_are_deterministic(self):
        log = PenLog()
        pts = [(10 + 2.0 * i, 20 + 0.4 * math.sin(i / 3)) for i in range(40)]
        log.add("press", "tablet", 0.0, pts[0][0], pts[0][1], p_raw=0.1, doc=list(pts[0]))
        for i, p in enumerate(pts[1:], 1):
            log.add("move", "tablet", i * 0.008, p[0], p[1], p_raw=0.1 + 0.02 * i, doc=list(p), proc_ms=0.2 + 0.001 * i)
            log.add("move", "mouse_synth", i * 0.008, p[0], p[1], p_raw=1.0)
        log.add("release", "tablet", 0.4, pts[-1][0], pts[-1][1], p_raw=0.0, doc=list(pts[-1]))
        stats = log.stats()
        self.assertEqual(stats["tablette_move"], 39)
        self.assertEqual(stats["souris_synthetisee"], 39)                              # double évènement détecté
        self.assertAlmostEqual(stats["cadence_hz"], 125.0, delta=0.5)
        self.assertGreater(stats["pression_valeurs_distinctes"], 30)
        self.assertIn("traitement_ms_p99", stats)
        with tempfile.TemporaryDirectory() as folder:
            path = os.path.join(folder, "log.json")
            log.save(path)
            again = PenLog.load(path)
        self.assertEqual(again.stroke_samples(), log.stroke_samples())
        samples = log.stroke_samples()[0]
        results = []
        for mode in ("none", "adaptive", "weighted", "stabilizer"):                    # mêmes données, quatre algorithmes
            doc = M.new_document(120, 40, background=None)
            stroke = B.Stroke(doc.layers[0], "pixels", B.Brush(size=6, hardness=1.0, pressure_size=True, smoothing=0.3,
                                                                smoothing_mode=mode), doc.rect())
            stroke.begin(samples[0][0], samples[0][1], samples[0][2])
            for x, y, p, t in samples[1:]:
                stroke.move(x, y, p, t=t)
            stroke.finish_to(samples[-1][0], samples[-1][1], 0.0)
            stroke.end()
            results.append(doc.layers[0].pix.read(doc.rect())[..., 3].astype(int).sum())
        self.assertTrue(all(total > 0 for total in results))

    def test_engine_info_exposes_each_stage(self):
        doc = M.new_document(60, 40, background=None)
        stroke = B.Stroke(doc.layers[0], "pixels", B.Brush(size=10, hardness=1.0, pressure_size=True, pressure_opacity=True), doc.rect())
        stroke.begin(10, 20, 0.5)
        stroke.move(20, 20, 0.5, t=0.01)
        info = stroke.info
        for key in ("p_raw", "p_filtered", "size", "opacity", "flow", "raw", "used", "seconds"):
            self.assertIn(key, info)
        self.assertAlmostEqual(info["size"], 5.0, delta=0.01)


if __name__ == "__main__":
    unittest.main()
