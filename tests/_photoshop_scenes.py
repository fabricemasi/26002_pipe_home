"""Scènes déterministes du moteur de trait (planches de comparaison et images de référence de non-régression).
Chaque scène rend un document de 168 × 96 pixels sur fond blanc et renvoie ses pixels RGBA (uint8)."""
import math
import os
import sys

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from fm_photoshop import brush as B, model as M

W, H = 168, 96


def _line(a, b, step=1.5):
    n = max(2, int(math.hypot(b[0] - a[0], b[1] - a[1]) / step))
    return [(a[0] + (b[0] - a[0]) * i / n, a[1] + (b[1] - a[1]) * i / n) for i in range(n + 1)]


def _wave():
    return [(10 + 148 * i / 160.0, 48 + 26 * math.sin(i / 160.0 * 2 * math.pi * 1.3 + 0.4)) for i in range(161)]


def _stroke(engine, layer, doc, brush, path, pressures=None):
    pr = pressures or [1.0] * len(path)
    s = engine.Stroke(layer, "pixels", brush, doc.rect())
    s.begin(path[0][0], path[0][1], pr[0])
    for i in range(1, len(path)):
        s.move(path[i][0], path[i][1], pr[i], t=i / 120.0)
    s.finish_to(path[-1][0], path[-1][1], 0.0)
    s.end()


def _loop():
    """Trait qui se croise lui-même trois fois."""
    pts = []
    for i in range(241):
        a = i / 240.0 * 2 * math.pi * 2.5
        pts.append((84 + 62 * math.sin(a * 0.8 + 0.3) * (1.0 - 0.15 * math.cos(a)), 48 + 36 * math.sin(a * 1.6)))
    return pts


def scene_constant_opacity(engine):
    doc = M.new_document(W, H, background=(255, 255, 255, 255))
    _stroke(engine, doc.layers[0], doc, engine.Brush(size=12, hardness=0.8, spacing=0.1, color=(0, 0, 0)), _wave())
    return doc


def scene_variable_opacity(engine):
    doc = M.new_document(W, H, background=(255, 255, 255, 255))
    path = _wave()
    pr = [0.15 + 0.75 * (0.5 + 0.5 * math.sin(i / 14.0)) for i in range(len(path))]
    _stroke(engine, doc.layers[0], doc, engine.Brush(size=14, hardness=0.8, spacing=0.1, color=(0, 0, 0), pressure_opacity=True), path, pr)
    return doc


def scene_crossing_buildup(engine):
    doc = M.new_document(W, H, background=(255, 255, 255, 255))
    path = _loop()
    kw = {} if getattr(engine, "LEGACY", False) else {"paint_mode": "buildup"}
    _stroke(engine, doc.layers[0], doc, engine.Brush(size=10, hardness=1.0, spacing=0.1, opacity=0.3, color=(0, 0, 0), **kw), path)
    return doc


def scene_crossing_wash(engine):
    doc = M.new_document(W, H, background=(255, 255, 255, 255))
    path = _loop()
    kw = {} if getattr(engine, "LEGACY", False) else {"paint_mode": "wash"}
    _stroke(engine, doc.layers[0], doc, engine.Brush(size=10, hardness=1.0, spacing=0.1, opacity=0.3, color=(0, 0, 0), **kw), path)
    return doc


def scene_small_circles(engine):
    doc = M.new_document(W, H, background=(255, 255, 255, 255))
    for i, d in enumerate((1.0, 1.5, 2.0, 3.0, 4.0, 6.0)):
        cx, cy, r = 16 + i * 27, 48, 4 + i * 1.6
        path = [(cx + r * math.cos(a), cy + r * math.sin(a)) for a in np.linspace(0, 2 * math.pi, 90)]
        _stroke(engine, doc.layers[0], doc, engine.Brush(size=d, hardness=1.0, spacing=0.08, color=(0, 0, 0)), path)
    return doc


def scene_progressive_diameter(engine):
    doc = M.new_document(W, H, background=(255, 255, 255, 255))
    path = _wave()
    pr = [0.04 + 0.96 * i / (len(path) - 1) for i in range(len(path))]
    _stroke(engine, doc.layers[0], doc, engine.Brush(size=22, hardness=1.0, spacing=0.08, color=(0, 0, 0), pressure_size=True), path, pr)
    return doc


def _dabs(engine, hardness):
    doc = M.new_document(W, H, background=(255, 255, 255, 255))
    for i, d in enumerate((1, 2, 3, 4, 6, 12, 24)):
        for row, (fx, fy) in enumerate(((0.0, 0.0), (0.37, 0.61))):
            x, y = 12 + i * 22 + fx, 26 + row * 40 + fy
            _stroke(engine, doc.layers[0], doc, engine.Brush(size=float(d), hardness=hardness, spacing=0.2, color=(0, 0, 0)),
                    [(x, y), (x + 0.01, y)])
    return doc


def scene_hard_tip(engine):
    return _dabs(engine, 1.0)


def scene_soft_tip(engine):
    return _dabs(engine, 0.0)


SCENES = {
    "1_trait_opacite_constante": scene_constant_opacity,
    "2_trait_opacite_variable": scene_variable_opacity,
    "3_croisement_accumulation": scene_crossing_buildup,
    "4_croisement_plafond": scene_crossing_wash,
    "5_petits_cercles": scene_small_circles,
    "6_courbe_diametre_progressif": scene_progressive_diameter,
    "7_pointe_dure": scene_hard_tip,
    "8_pointe_douce": scene_soft_tip,
}


def render(name, engine=B) -> np.ndarray:
    doc = SCENES[name](engine)
    return doc.layers[0].pix.read(doc.rect())


# ---- Scènes de COMPARAISON des modèles (mission « douceur, opacité et accumulation ») : mêmes entrées pour tous les moteurs ----
W2, H2 = 200, 110


def _curve(y=55.0, amp=18.0, x0=12.0, x1=188.0, n=180):
    return [(x0 + (x1 - x0) * i / n, y + amp * math.sin(i / n * 2 * math.pi * 1.1 + 0.3)) for i in range(n + 1)]


def _mode(engine, mode):
    return {} if getattr(engine, "LEGACY", False) else {"paint_mode": mode}


def _white(engine):
    return M.new_document(W2, H2, background=(255, 255, 255, 255))


def cmp_line_30(engine):
    doc = _white(engine)
    _stroke(engine, doc.layers[0], doc, engine.Brush(size=14, hardness=0.8, spacing=0.08, opacity=0.3, color=(0, 0, 0), **_mode(engine, "wash")), _curve())
    return doc


def cmp_line_70(engine):
    doc = _white(engine)
    _stroke(engine, doc.layers[0], doc, engine.Brush(size=14, hardness=0.8, spacing=0.08, opacity=0.7, color=(0, 0, 0), **_mode(engine, "wash")), _curve())
    return doc


def cmp_pressure(engine):
    doc = _white(engine)
    path = _curve()
    pr = [0.12 + 0.85 * (0.5 + 0.5 * math.sin(i / 17.0)) for i in range(len(path))]
    _stroke(engine, doc.layers[0], doc, engine.Brush(size=16, hardness=0.8, spacing=0.08, color=(0, 0, 0), pressure_opacity=True,
                                                     pressure_size=True, **_mode(engine, "buildup")), path, pr)
    return doc


def cmp_loop(engine):
    doc = _white(engine)
    pts = []
    for i in range(281):
        a = i / 280.0 * 2 * math.pi * 2.5
        pts.append((100 + 80 * math.sin(a * 0.8 + 0.3) * (1.0 - 0.15 * math.cos(a)), 55 + 38 * math.sin(a * 1.6)))
    _stroke(engine, doc.layers[0], doc, engine.Brush(size=12, hardness=0.8, spacing=0.08, opacity=0.3, color=(0, 0, 0), **_mode(engine, "buildup")), pts)
    return doc


def cmp_passes(engine):
    doc = _white(engine)
    path = []
    for k in range(5):
        seg = _line((20, 55 + (k % 2) * 2.0), (180, 55 - (k % 2) * 2.0), 2.0)
        path += seg if k % 2 == 0 else seg[::-1]
    _stroke(engine, doc.layers[0], doc, engine.Brush(size=18, hardness=0.8, spacing=0.08, opacity=0.3, color=(0, 0, 0), **_mode(engine, "buildup")), path)
    return doc


def _cmp_size(engine, d):
    doc = _white(engine)
    _stroke(engine, doc.layers[0], doc, engine.Brush(size=float(d), hardness=0.8, spacing=0.08, color=(0, 0, 0), **_mode(engine, "wash")),
            _curve(amp=14.0 if d < 40 else 8.0))
    return doc


def cmp_d3(engine):
    return _cmp_size(engine, 3)


def cmp_d12(engine):
    return _cmp_size(engine, 12)


def cmp_d48(engine):
    return _cmp_size(engine, 48)


SCENES_CMP = {
    "1_ligne_30": cmp_line_30, "2_ligne_70": cmp_line_70, "3_pression_variable": cmp_pressure, "4_boucle_croisee": cmp_loop,
    "5_cinq_passages": cmp_passes, "6_pinceau_3px": cmp_d3, "7_pinceau_12px": cmp_d12, "8_pinceau_48px": cmp_d48,
}


def render_cmp(name, engine=B) -> np.ndarray:
    doc = SCENES_CMP[name](engine)
    return doc.layers[0].pix.read(doc.rect())


# ---- Scènes de pointes DOUCES (mission « chenille, anticrénélage, aérographe ») : dureté 0, angles aigus, demi-tour, spirale ----
W3, H3 = 220, 140


def _soft_doc():
    return M.new_document(W3, H3, background=(255, 255, 255, 255))


def _resample(pts, step):
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


def _soft_stroke(engine, path, size=40, hardness=0.0, **kw):
    doc = _soft_doc()
    _stroke(engine, doc.layers[0], doc, engine.Brush(size=float(size), hardness=hardness, spacing=0.2, color=(0, 0, 0), **kw), path)
    return doc


def soft_angle(deg):
    def scene(engine):
        a = math.radians(180.0 - deg)
        v = (120.0, 70.0)
        p2 = (v[0] - 80 * math.cos(math.pi - a), v[1] - 80 * math.sin(math.pi - a))
        return _soft_stroke(engine, _resample([(v[0] - 80, v[1]), v, p2], 2.0), size=36)
    return scene


def soft_uturn(engine):
    return _soft_stroke(engine, _resample([(25, 55), (195, 55), (25, 72)], 2.0), size=40)


def soft_spiral(engine):
    pts = [(110 + (6 + 5.2 * t) * math.cos(t), 70 + (6 + 5.2 * t) * math.sin(t)) for t in np.linspace(0, 4 * math.pi, 260)]
    return _soft_stroke(engine, _resample(pts, 2.0), size=22)


def soft_noisy(engine):
    rng = np.random.default_rng(3)
    base = [(20 + 180 * t, 72 + 34 * math.sin(t * 5.0)) for t in np.linspace(0, 1, 400)]
    return _soft_stroke(engine, [(x + rng.normal(0, 1.6), y + rng.normal(0, 1.6)) for x, y in _resample(base, 12.0)], size=40)


def soft_pressure(engine):
    path = _resample([(15 + 190 * t, 70 + 30 * math.sin(t * 6.0)) for t in np.linspace(0, 1, 300)], 2.0)
    pr = [0.15 + 0.85 * (0.5 + 0.5 * math.sin(i / 11.0)) for i in range(len(path))]
    doc = _soft_doc()
    _stroke(engine, doc.layers[0], doc, engine.Brush(size=44.0, hardness=0.0, spacing=0.2, color=(0, 0, 0), pressure_size=True), path, pr)
    return doc


SCENES_SOFT = {"s1_angle_15": soft_angle(15), "s2_angle_30": soft_angle(30), "s3_angle_90": soft_angle(90), "s4_demi_tour": soft_uturn,
               "s5_spirale": soft_spiral, "s6_trace_bruite": soft_noisy, "s7_pression_variable": soft_pressure}


def render_soft(name, engine=B) -> np.ndarray:
    doc = SCENES_SOFT[name](engine)
    return doc.layers[0].pix.read(doc.rect())
