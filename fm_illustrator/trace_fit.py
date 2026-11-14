"""Vectorisation, étape 2 (SANS Qt ; numpy) : contour subpixel (trace_contours) -> sous-tracé de Bézier cubiques.

Reconstruction géométrique, pas un lissage : les points d'ancrage sont posés là où la forme l'exige, puis chaque
intervalle reçoit UNE cubique quand elle suffit.
1. Angles : virage mesuré sur ±r le long du contour (r = 3 px), et CONCENTRÉ (le virage sur ±r/2 en garde au moins
   65 % : un vrai angle tourne d'un coup, une courbe serrée progressivement) ; maxima locaux ; sommet reconstruit à
   l'intersection des deux côtés (l'anticrénelage arrondit la pointe d'un demi-pixel : on la retrouve).
2. Droites : portions dont la flèche reste sous la tolérance de ligne sur au moins `MIN_LINE` px, vérifiées sur tous
   leurs points ; leurs extrémités sont des points de transition, tangente = direction de la droite (G1 avec la
   courbe voisine).
3. Extrema : tangente horizontale ou verticale (convention des logiciels de dessin et des polices : poignées droites,
   faciles à éditer), hors des droites, filtrés contre le bruit.
4. Ajustement : cubique à tangentes imposées (moindres carrés de Schneider, reparamétrage de Newton), erreur maximale
   mesurée sur les points du contour ; programmation dynamique sur les points candidats : le moins d'ancres possible,
   chaque cubique sous la tolérance ; un intervalle que rien ne couvre est subdivisé au point d'erreur maximale
   (tangente centrale : G1).
Les tangentes de chaque ancre sont calculées UNE fois et partagées par les deux segments voisins : continuité G1
partout sauf aux angles (nœud « lisse »). Coordonnées : celles du contour."""
from __future__ import annotations

import math

import numpy as np

R = 3.0                  # px : échelle des angles et des tangentes
MIN_LINE = 12.0          # px : longueur minimale d'une droite (plus courte : un angle ou une courbe s'en charge)
LINE_SHARE = 0.03        # part minimale du contour : une droite est un trait de la forme, pas une corde de courbe
LINE_NOISE = 0.08        # px : bruit du contour subpixel toléré par une droite courte
LINE_BOW = 0.005         # flèche de la parabole des moindres carrés tolérée par px de longueur (0,5 %)
LINE_SLOPE = 0.008       # écart toléré d'une droite par px de longueur (0,8 % : un fût de 75 px peut bomber de 0,6)
CONCENTRATION = 0.70     # part du virage (sur ±r) déjà faite sur ±r/2 : angle (≈ 0,8-1) ou courbe serrée (≈ 0,5-0,66)
EXTREMUM_MERGE = 4.0     # px : extremum fondu dans le bout d'une droite voisine
KINK = 10.0              # degrés : pli minimal au bout d'une droite pour en faire un angle
FIT_POINTS = 100         # points au plus pour ajuster une cubique (l'erreur est mesurée sur tous)
CORNER_MARGIN = 0.8      # px : points du contour ignorés autour d'un angle (arrondi d'anticrénelage)


class Contour:
    """Boucle fermée (n × 2) paramétrée par la longueur d'arc ; `at(s)` interpole (s quelconque, cyclique)."""

    def __init__(self, pts: np.ndarray):
        self.P = np.asarray(pts, dtype=np.float64)
        seg = np.roll(self.P, -1, axis=0) - self.P
        d = np.hypot(seg[:, 0], seg[:, 1])
        self.s = np.concatenate([[0.0], np.cumsum(d)[:-1]])
        self.L = float(d.sum())
        self._s = np.concatenate([self.s, [self.L]])
        self._x = np.concatenate([self.P[:, 0], self.P[:1, 0]])
        self._y = np.concatenate([self.P[:, 1], self.P[:1, 1]])

    def at(self, s):
        s = np.mod(np.asarray(s, dtype=np.float64), self.L)
        return np.stack([np.interp(s, self._s, self._x), np.interp(s, self._s, self._y)], axis=-1)

    def points_between(self, s0: float, s1: float) -> np.ndarray:
        """Points du contour d'abscisse strictement entre s0 et s1 (s1 > s0, au plus un tour)."""
        base = s0 - (s0 % self.L)
        ss = np.concatenate([self.s + base, self.s + base + self.L])
        pp = np.concatenate([self.P, self.P])
        sel = (ss > s0) & (ss < s1)
        return pp[sel], ss[sel]


def _unit(v):
    n = np.hypot(v[..., 0], v[..., 1])
    return v / np.maximum(n, 1e-12)[..., None]


def _turn(c: Contour, r: float) -> np.ndarray:
    """Virage signé (degrés) à chaque point du contour, mesuré sur ±r."""
    a, p, b = c.at(c.s - r), c.P, c.at(c.s + r)
    v1, v2 = p - a, b - p
    cross = v1[:, 0] * v2[:, 1] - v1[:, 1] * v2[:, 0]
    dot = (v1 * v2).sum(axis=1)
    return np.degrees(np.arctan2(cross, dot))


def _line_dir(points: np.ndarray, forward) -> np.ndarray | None:
    """Direction principale (ACP) d'un nuage de points, orientée comme `forward`."""
    if len(points) < 2:
        return None
    q = points - points.mean(axis=0)
    _u, _s, vt = np.linalg.svd(q, full_matrices=False)
    d = vt[0]
    if np.dot(d, forward) < 0:
        d = -d
    return d


def _corners(c: Contour, threshold: float, r: float) -> list[dict]:
    if c.L < 6 * r:
        return []
    t1 = np.abs(_turn(c, r))
    t_half = np.abs(_turn(c, r / 2))
    ok = (t1 >= threshold) & (t_half >= CONCENTRATION * t1)
    found = []
    for i in np.argsort(-t1):
        if not ok[i]:
            continue
        s = float(c.s[i])
        if any(min(abs(s - f["s"]), c.L - abs(s - f["s"])) < 1.5 * r for f in found):
            continue
        found.append({"s": s, "i": int(i)})
    found.sort(key=lambda f: f["s"])
    # Sommet et tangentes : droites des deux côtés (entre CORNER_MARGIN et ~2,5 r, sans dépasser la moitié de la
    # distance à l'angle voisin), intersectées.
    for k, f in enumerate(found):
        s = f["s"]
        prev_gap = (s - found[k - 1]["s"]) % c.L if len(found) > 1 else c.L
        next_gap = (found[(k + 1) % len(found)]["s"] - s) % c.L if len(found) > 1 else c.L
        span_in = max(CORNER_MARGIN + 0.5, min(2.5 * r, prev_gap / 2))
        span_out = max(CORNER_MARGIN + 0.5, min(2.5 * r, next_gap / 2))
        p = c.P[f["i"]]
        before = _side(c, s, -1, span_in)
        after = _side(c, s, 1, span_out)
        d_in = _line_dir(before[::-1], p - before[-1])              # sens du parcours, vers l'angle
        d_out = _line_dir(after, after[-1] - p)                     # sens du parcours, depuis l'angle
        apex = p
        if d_in is not None and d_out is not None:
            a0, b0 = before.mean(axis=0), after.mean(axis=0)
            m = np.array([d_in, -d_out]).T
            if abs(np.linalg.det(m)) > 1e-6:
                t, _u = np.linalg.solve(m, b0 - a0)
                q = a0 + d_in * t
                # Pointe émoussée par l'anticrénelage (~0,6 px) : le sommet s'en éloigne d'autant plus que l'angle
                # est aigu ; au-delà, l'intersection vient d'un côté mal estimé et le point du contour reste.
                inner = math.radians(180.0 - min(179.0, abs(math.degrees(math.atan2(
                    d_in[0] * d_out[1] - d_in[1] * d_out[0], float(np.dot(d_in, d_out)))))))
                if np.hypot(*(q - p)) <= min(2.5, 0.7 / max(0.2, math.sin(inner / 2))):
                    apex = q
        f["pos"] = np.asarray(apex, dtype=np.float64)
        f["t_in"] = d_in if d_in is not None else _unit(p - c.at(s - r))
        f["t_out"] = d_out if d_out is not None else _unit(c.at(s + r) - p)
    return found


def _line_fit(c: Contour, a: float, b: float):
    """Droite des moindres carrés des points entre a et b : (origine, direction, écart maximal, flèche systématique)
    ou None. Flèche = celle de la parabole des moindres carrés : un arc doux la porte (~1 % de la longueur pour un
    flanc de feuille), un fût droit seulement du bruit (≤ 0,3 % pour les fûts d'un « m » à empattements)."""
    pts, _s = c.points_between(a, b)
    pts = np.vstack([c.at(a)[None, :], pts, c.at(b)[None, :]])
    if len(pts) < 3:
        return None
    mean = pts.mean(axis=0)
    d = _line_dir(pts, pts[-1] - pts[0])
    rel = pts - mean
    y = rel[:, 0] * d[1] - rel[:, 1] * d[0]
    t = rel @ d
    span_t = float(t.max() - t.min())
    bow = abs(float(np.polyfit(t, y, 2)[0])) * span_t * span_t / 4 if len(pts) >= 4 and span_t > 1e-9 else 0.0
    return mean, d, float(np.abs(y).max()), bow


def _side(c: Contour, s: float, sign: int, span: float) -> np.ndarray:
    """Points d'un côté d'un angle, de CORNER_MARGIN jusqu'à `span` px au plus : la fenêtre s'allonge tant que le
    côté reste droit (un côté court suivi d'un arrondi ne doit pas tordre la direction)."""
    best = c.at(s + sign * np.linspace(CORNER_MARGIN, CORNER_MARGIN + 0.8, 5))
    length = CORNER_MARGIN + 1.6
    while length <= span + 1e-9:
        pts = c.at(s + sign * np.linspace(CORNER_MARGIN, length, 8))
        rel = pts - pts.mean(axis=0)
        d = _line_dir(pts, pts[-1] - pts[0])
        if float(np.abs(rel[:, 0] * d[1] - rel[:, 1] * d[0]).max()) > 0.12:
            break
        best = pts
        length += 0.8
    return best


def _trim_line(c: Contour, start: float, end: float) -> tuple[float, float]:
    """Bouts d'une droite ramenés là où le contour la QUITTE : la croissance s'arrête quand l'écart atteint la
    tolérance, donc quelques pixels DANS la courbe voisine (un demi-cercle de rayon 40 : 6 px), ce qui fausse la
    tangente de la courbe suivante. Seuil = bruit du milieu de la droite (×2,5, au moins LINE_NOISE)."""
    pts, ss = c.points_between(start, end)
    if len(pts) < 8:
        return start, end
    mean = pts.mean(axis=0)
    d = _line_dir(pts, pts[-1] - pts[0])
    dev = np.abs((pts - mean) @ np.array([-d[1], d[0]]))
    mid = dev[len(dev) // 4: 3 * len(dev) // 4]
    limit = max(LINE_NOISE, 2.5 * float(np.sqrt(np.mean((mid - mid.mean()) ** 2))) + float(mid.mean()))
    i, j = 0, len(dev) - 1
    while i < j and dev[i] > limit:
        i += 1
    while j > i and dev[j] > limit:
        j -= 1
    return float(ss[i]) if i > 0 else start, float(ss[j]) if j < len(dev) - 1 else end


def _kink(c: Contour, s: float, end: np.ndarray, d: np.ndarray, sign: int):
    """Bout de droite (abscisse s, point `end`, direction d du parcours) suivi d'un pli brusque, du côté `sign`
    (+1 après la fin, −1 avant le début) : (sommet, tangente entrante, tangente sortante) ou None. Pli = direction
    du contour juste au-delà (0,6 à 2,5 px) écartée d'au moins KINK degrés, et déjà presque toute prise (≥ 60 % de
    celle mesurée de 2,5 à 5 px : une courbe qui démarre tourne progressivement)."""
    near = c.at(s + sign * np.linspace(0.6, 2.5, 6))
    far = c.at(s + sign * np.linspace(2.5, 5.0, 6))
    forward = d * sign
    d_near = _line_dir(near, near[-1] - near[0])
    d_far = _line_dir(far, far[-1] - far[0])
    if d_near is None or d_far is None:
        return None

    def angle(u):
        return abs(math.degrees(math.atan2(forward[0] * u[1] - forward[1] * u[0], float(np.dot(forward, u)))))
    a_near, a_far = angle(d_near), angle(d_far)
    if a_near < KINK or a_near < 0.6 * a_far:
        return None
    side = c.at(s + sign * np.linspace(1.0, 4.0, 8))
    d_side = _line_dir(side, side[-1] - side[0])
    m = np.array([d, -d_side]).T
    apex = end
    if abs(np.linalg.det(m)) > 1e-6:
        t, _u = np.linalg.solve(m, side.mean(axis=0) - end)
        q = end + d * t
        if np.hypot(*(q - end)) <= 1.5:
            apex = q
    oriented = d_side * sign                          # sens du parcours
    return (apex, d, oriented) if sign > 0 else (apex, oriented, d)


def _straight_runs(c: Contour, s0: float, s1: float, tol: float) -> list[tuple[float, float, np.ndarray, np.ndarray]]:
    """Droites entre s0 et s1 : (début, fin, point de début, point de fin) ; germes = portions localement droites,
    puis CROISSANCE de chaque côté tant que la droite des moindres carrés passe à `line_tol` de tous ses points
    (un fût légèrement galbé reste UNE droite, comme dans les logiciels de dessin). Extrémités = projections sur la
    droite (la courbe voisine y part avec la même direction : G1)."""
    cap = 0.6 * tol

    def allowed(length):                              # écart toléré : relatif à la longueur (un morceau de courbe
        return min(cap, max(LINE_NOISE, LINE_SLOPE * length))  # n'est jamais une droite ; un long fût à peine galbé, si)
    def bowed(length):                                # flèche systématique tolérée (arc doux = courbe)
        return max(LINE_NOISE, LINE_BOW * length)
    half = max(MIN_LINE / 2, R)
    min_len = max(MIN_LINE, LINE_SHARE * c.L)
    ss = np.arange(s0 + half, s1 - half + 1e-9, 0.5)
    if len(ss) < 2:
        return []
    def sagitta(h):
        a, p, b = c.at(ss - h), c.at(ss), c.at(ss + h)
        ab = b - a
        return np.abs(ab[:, 0] * (p - a)[:, 1] - ab[:, 1] * (p - a)[:, 0]) / np.maximum(np.hypot(ab[:, 0], ab[:, 1]), 1e-9)
    sag = sagitta(half)
    # Germe utile seulement si la droite tient déjà sur la longueur minimale (test vectorisé : sur un arc, rien
    # n'est essayé ; avant, chaque germe grandissait puis était rejeté, ~1 s pour un grand cercle).
    sag = np.where(sagitta(min_len / 2) < allowed(min_len), sag, np.inf)
    order = np.argsort(sag)
    taken = []
    runs = []
    for k in order:
        if sag[k] >= 0.06:
            break
        sk = float(ss[k])
        start, end = max(s0, sk - half), min(s1, sk + half)
        if any(start < r1 and end > r0 for r0, r1 in taken):
            continue
        fit = _line_fit(c, start, end)
        if fit is None or fit[2] > allowed(end - start) or fit[3] > bowed(end - start):
            continue
        for direction in (1, -1):                     # croissance : pas de 4 px, puis 1 px, puis 0,25 px
            for step in (4.0, 1.0, 0.25):
                while True:
                    na, nb = (start, end + step) if direction > 0 else (start - step, end)
                    if na < s0 or nb > s1 or any(na < r1 and nb > r0 for r0, r1 in taken):
                        break
                    fit = _line_fit(c, na, nb)
                    if fit is None or fit[2] > allowed(nb - na) or fit[3] > bowed(nb - na):
                        break
                    start, end = na, nb
        start, end = _trim_line(c, start, end)
        if end - start < min_len:
            continue
        mean, d, _dev, _bow = _line_fit(c, start, end)
        pa, pb = c.at(start), c.at(end)
        pa = mean + d * float(np.dot(pa - mean, d))
        pb = mean + d * float(np.dot(pb - mean, d))
        taken.append((start, end))
        runs.append((start, end, pa, pb))
    runs.sort(key=lambda r: r[0])
    return runs


def _tangent(c: Contour, s: float, w: float = R) -> np.ndarray:
    pts = c.at(s + np.linspace(-w, w, 9))
    return _line_dir(pts, pts[-1] - pts[0])


def _extrema(c: Contour, s0: float, s1: float, runs, w: float | None = None) -> list[tuple[float, np.ndarray]]:
    """Points à tangente horizontale / verticale entre s0 et s1, hors droites ; (abscisse, tangente exacte). Fenêtre
    proportionnelle au contour (1,5 % de sa longueur, 3 à 12 px) : sur un grand arc, la direction change trop peu
    sur quelques pixels pour distinguer un vrai extremum du bruit."""
    if w is None:
        w = min(12.0, max(R, 0.015 * c.L))
    cyclic = s1 - s0 >= c.L - 1e-9                  # boucle entière : aucun bord à éviter
    if not cyclic and s1 - s0 < 2 * w:
        return []
    # Boucle entière : examen FERMÉ sur lui-même (un extremum au point de départ de la boucle n'est pas perdu).
    ss = np.arange(s0, s0 + c.L + 0.5, 0.5) if cyclic else np.arange(s0 + w, s1 - w, 0.5)
    if len(ss) < 3:
        return []
    T = _unit(c.at(ss + w) - c.at(ss - w))
    far_a, far_b = _unit(c.at(ss + 2 * w) - c.at(ss)), _unit(c.at(ss) - c.at(ss - 2 * w))
    out = []
    for axis in (0, 1):
        v = T[:, axis]
        pos = v > 0                               # zéro exact (forme symétrique) : compté d'un côté, jamais perdu
        for k in np.nonzero(pos[:-1] != pos[1:])[0]:
            dv = v[k] - v[k + 1]
            s = float(ss[k] + (0.5 * v[k] / dv if abs(dv) > 1e-12 else 0.25))
            # Vrai passage (pas du bruit) : la composante a nettement changé de signe de part et d'autre.
            if cyclic:
                s = s0 + (s - s0) % c.L
            if not (far_b[k, axis] * far_a[k + 1, axis] < 0 and min(abs(far_b[k, axis]), abs(far_a[k + 1, axis])) > 0.01):
                continue
            t = np.zeros(2)
            other = 1 - axis
            t[other] = 1.0 if T[k, other] + T[k + 1, other] > 0 else -1.0
            fb, fa = far_b[k], far_a[k + 1]           # extremum NET : la courbe y tourne vraiment (≥ 8° sur ±2w)
            strong = abs(math.degrees(math.atan2(fb[0] * fa[1] - fb[1] * fa[0], float(np.dot(fb, fa))))) >= 8.0
            out.append((s, t, strong))
    out.sort(key=lambda e: e[0])
    merged = []
    for e in out:
        if merged and e[0] - merged[-1][0] < 2 * w:
            continue
        merged.append(e)
    if cyclic and len(merged) > 1 and merged[0][0] + c.L - merged[-1][0] < 2 * w:
        merged.pop()                              # le même extremum vu des deux côtés de la jonction
    return merged


# ---------------------------------------------------------------- ajustement d'une cubique
def _coefficients(ctrl):
    """B(u) = ((A·u + B)·u + C)·u + D (forme polynomiale : 3 multiplications par point au lieu de 4 bases)."""
    q0, q1, q2, q3 = (np.asarray(q, dtype=np.float64) for q in ctrl)
    return -q0 + 3 * q1 - 3 * q2 + q3, 3 * q0 - 6 * q1 + 3 * q2, 3 * (q1 - q0), q0


def _bezier_eval(ctrl, u):
    A, Bc, C, D = _coefficients(ctrl)
    uu = u[:, None]
    B = ((A * uu + Bc) * uu + C) * uu + D
    d1 = (3 * A * uu + 2 * Bc) * uu + C
    d2 = 6 * A * uu + 2 * Bc
    return B, d1, d2


def _project(ctrl, P, u, steps: int = 3):
    """Paramètres ramenés au point le plus proche de la courbe (Gauss-Newton, `steps` pas)."""
    A, Bc, C, D = _coefficients(ctrl)
    A3, B2 = 3 * A, 2 * Bc
    for _ in range(steps):
        uu = u[:, None]
        diff = ((A * uu + Bc) * uu + C) * uu + D - P
        d1 = (A3 * uu + B2) * uu + C
        den = np.einsum("ij,ij->i", d1, d1)
        u = np.clip(u - np.einsum("ij,ij->i", diff, d1) / np.maximum(den, 1e-12), 0.0, 1.0)
        u[0], u[-1] = 0.0, 1.0
    return u


def _conic_guess(p0, p3, t0, t1):
    """Poignées d'un arc de conique : les deux tangentes se coupent en X ; poignée = k(θ) × distance à X, avec
    k(θ) = 4/3 · tan(θ/4) / tan(θ/2) (θ = virage total ; 0,552 pour un quart de tour : exact pour un cercle et, par
    affinité, pour une ellipse). None si les tangentes ne se coupent pas en avant (inflexion)."""
    m = np.array([t0, t1]).T
    if abs(np.linalg.det(m)) < 1e-9:
        return None
    da, db = np.linalg.solve(m, p3 - p0)               # p0 + t0·da + t1·db = p3 : X = p0 + t0·da = p3 − t1·db
    if da <= 0 or db <= 0:
        return None
    theta = math.atan2(t0[0] * t1[1] - t0[1] * t1[0], float(np.dot(t0, t1)))
    theta = abs(theta)
    if theta < 1e-3 or theta > math.radians(179):
        return None
    k = (4 / 3) * math.tan(theta / 4) / math.tan(theta / 2)
    return (p0, p0 + t0 * (k * da), p3 - t1 * (k * db), p3)


def _alternate(P, t0, t1, u, chord, arc, iterations, good=0.0):
    """Moindres carrés des poignées (Schneider) en alternance avec la projection des points ; meilleur résultat."""
    p0, p3 = P[0], P[-1]
    best = None
    for _it in range(iterations + 1):
        mu = 1 - u
        b0, b1, b2, b3 = mu ** 3, 3 * mu * mu * u, 3 * mu * u * u, u ** 3
        A1 = t0[None, :] * b1[:, None]
        A2 = -t1[None, :] * b2[:, None]
        rest = P - ((b0 + b1)[:, None] * p0 + (b2 + b3)[:, None] * p3)
        c00, c01, c11 = (A1 * A1).sum(), (A1 * A2).sum(), (A2 * A2).sum()
        x0, x1 = (A1 * rest).sum(), (A2 * rest).sum()
        det = c00 * c11 - c01 * c01
        if abs(det) > 1e-12:
            a1, a2 = (x0 * c11 - c01 * x1) / det, (c00 * x1 - c01 * x0) / det
        else:
            a1 = a2 = chord / 3
        if not (1e-3 * chord < a1 < arc and 1e-3 * chord < a2 < arc):
            a1 = a2 = chord / 3
        ctrl = (p0, p0 + t0 * a1, p3 - t1 * a2, p3)
        u = _project(ctrl, P, u)
        B, _d1, _d2 = _bezier_eval(ctrl, u)
        err = np.hypot(*(B - P).T)
        worst = float(err.max()) if len(err) else 0.0
        if best is None or worst < best[1] - 1e-6:
            best = (ctrl, worst, int(np.argmax(err)) if len(err) else 0)
        elif worst > best[1] * 0.98:
            break                                       # plus de progrès
        if worst <= good:
            break                                       # assez précis
    return best


def fit_cubic_fixed(P: np.ndarray, t0: np.ndarray, t1: np.ndarray, iterations: int = 6, tol: float = 0.0):
    """Cubique de P[0] à P[-1], tangentes imposées (t0 au départ, t1 à l'arrivée, sens du parcours) ; -> (contrôles,
    erreur maximale, indice du point le plus éloigné). Deux départs, le meilleur gardé : paramètres à la longueur
    d'arc (Schneider), et arc de conique par l'intersection des tangentes (`_conic_guess`) : depuis le seul premier,
    l'alternance moindres carrés / projection restait dans un minimum local quand les poignées sont inégales (quart
    d'ellipse : 1,36 px d'erreur au lieu de 0,15). Longueur impossible (négative, démesurée) -> corde / 3."""
    full = P
    if tol > 0 and len(P) > 60:                   # rejet rapide : sur 24 points l'erreur ne peut qu'être SOUS-estimée
        few = P[np.linspace(0, len(P) - 1, 24).round().astype(int)]
        seg_q = np.hypot(*np.diff(few, axis=0).T)
        arc_q = float(seg_q.sum())
        quick = _alternate(few, t0, t1, np.concatenate([[0.0], np.cumsum(seg_q)]) / max(arc_q, 1e-12),
                           float(np.hypot(*(few[-1] - few[0]))), arc_q, 2, tol)
        guess = _conic_guess(few[0], few[-1], t0, t1)
        if quick[1] > 3 * tol and guess is not None:
            other = _alternate(few, t0, t1, _project(guess, few, np.linspace(0, 1, len(few)), 4),
                               float(np.hypot(*(few[-1] - few[0]))), arc_q, 2, tol)
            quick = min(quick, other, key=lambda r: r[1])
        if quick[1] > 3 * tol:
            return quick
    if len(P) > FIT_POINTS:                       # ajustement sur ~100 points réguliers, contrôle sur TOUS ensuite
        idx = np.unique(np.concatenate([np.linspace(0, len(P) - 1, FIT_POINTS).round().astype(int), [len(P) - 1]]))
        P = P[idx]
    p0, p3 = P[0], P[-1]
    chord = float(np.hypot(*(p3 - p0)))
    seg = np.hypot(*np.diff(P, axis=0).T)
    arc = float(seg.sum())
    u = np.concatenate([[0.0], np.cumsum(seg)]) / max(arc, 1e-12)
    good = 0.3 * tol
    best = _alternate(P, t0, t1, u, chord, arc, iterations, good)
    guess = _conic_guess(p0, p3, t0, t1)
    if guess is not None and best[1] > max(0.05, 0.5 * tol):
        other = _alternate(P, t0, t1, _project(guess, P, u.copy(), 6), chord, arc, iterations, good)
        if other[1] < best[1]:
            best = other
    # Sens inverse : la COURBE doit rester près du contour (une boucle ou un bec loin de tout point échappe à la
    # mesure points -> courbe).
    ctrl, worst, k = best
    if full is not P:                             # erreur sur tous les points (projection depuis l'abscisse)
        seg_f = np.hypot(*np.diff(full, axis=0).T)
        uf = _project(ctrl, full, np.concatenate([[0.0], np.cumsum(seg_f)]) / max(float(seg_f.sum()), 1e-12), 5)
        Bf, _a, _b = _bezier_eval(ctrl, uf)
        errs = np.hypot(*(Bf - full).T)
        worst, k = float(errs.max()), int(np.argmax(errs))
        P = full
    B, _d1, _d2 = _bezier_eval(ctrl, np.linspace(0.0, 1.0, 48))
    step = max(1, len(P) // 400)
    Q = P[::step]
    back = float(np.sqrt(((B[:, None, :] - Q[None, :, :]) ** 2).sum(axis=2).min(axis=1)).max())
    return ctrl, max(worst, back), k


# ---------------------------------------------------------------- reconstruction d'une boucle
def fit_loop(pts: np.ndarray, tolerance: float = 1.0, corner: float = 60.0, r: float = R) -> dict | None:
    """Boucle subpixel -> sous-tracé fermé {"closed": True, "nodes": [...]} (format de fm_illustrator.bezier)."""
    from . import bezier as bz
    c = Contour(pts)
    if c.L < 2.0 or len(c.P) < 3:
        return None
    tol = max(0.05, float(tolerance))
    corners = _corners(c, float(corner), max(R, float(r)))
    if corners:
        pieces = [(f, corners[(k + 1) % len(corners)]) for k, f in enumerate(corners)]
    else:
        pieces = [(None, None)]
    segs: list[tuple] = []                        # (p0, c1, c2, p3, coin_au_début)
    for start, end in pieces:
        if start is None:
            s0, s1 = 0.0, c.L
        else:
            s0 = start["s"]
            s1 = end["s"] if end["s"] > s0 else end["s"] + c.L
            if len(corners) == 1:
                s1 = s0 + c.L
        runs = _straight_runs(c, s0, s1, tol)
        if start is not None:                     # bout de droite à moins de 3 px d'un angle : rattaché à l'angle
            runs = [(s0 if a - s0 < 3.0 else a, s1 if s1 - b < 3.0 else b,
                     start["pos"] if a - s0 < 3.0 else pa, end["pos"] if s1 - b < 3.0 else pb) for a, b, pa, pb in runs]
        cands = []                                # (s, pos, t_in, t_out, genre)
        if start is not None:
            cands.append((s0, start["pos"], start["t_in"], start["t_out"], "corner"))
        for a, b, pa, pb in runs:
            d = _unit(pb - pa)
            # Bout de droite sur un changement de direction BRUSQUE (même faible : 17° au drapeau d'un « m ») : un
            # angle, comme dans Illustrator (deux traits droits qui se rencontrent) ; un départ progressif = lisse.
            kink = None if start is not None and a == s0 else _kink(c, a, pa, d, -1)
            cands.append((a, *kink, "corner") if kink else (a, pa, d, d, "line_start"))
            kink = None if start is not None and b == s1 else _kink(c, b, pb, d, 1)
            cands.append((b, *kink, "corner") if kink else (b, pb, d, d, "line_end"))
        spans = [(a, b) for a, b, _pa, _pb in runs]
        ends = [e for a, b in spans for e in (a, b)]
        for s, t, _strong in _extrema(c, s0, s1, spans):
            if any(abs(s - e) < EXTREMUM_MERGE for e in ends):
                continue                          # au bout d'une droite : son extrémité porte déjà la tangente
            if any(a < s < b and b - a >= 3 * MIN_LINE for a, b in spans):
                continue                          # dans une LONGUE droite (taille d'un fût) : la droite l'emporte ;
                                                  # une courte (faux plat d'ellipse) cède à l'extremum
            cands.append((s, c.at(s), t, t, "extremum"))
        cands.sort(key=lambda e: e[0])
        # Candidats trop proches (moins de 1 px) fondus, l'angle et les bouts de droite d'abord.
        rank = {"corner": 0, "line_start": 1, "line_end": 1, "extremum": 2, "extremum_soft": 3}
        kept = []
        for e in cands:
            if kept and e[0] - kept[-1][0] < 1.0:
                if rank[e[4]] < rank[kept[-1][4]]:
                    kept[-1] = e
                continue
            kept.append(e)
        if start is None:
            if len(kept) < 2:                     # aucune ancre naturelle : quatre points réguliers
                kept = [(s, c.at(s), _tangent(c, s), _tangent(c, s), "even")
                        for s in np.linspace(0, c.L, 4, endpoint=False)]
            first = kept[0]
            kept.append((first[0] + c.L, first[1], first[2], first[3], first[4]))
        else:
            while len(kept) > 1 and s1 - kept[-1][0] < 1.0:
                kept.pop()                        # extrémité de droite (ou pli) fondue dans l'angle d'arrivée
            kept.append((s1, end["pos"], end["t_in"], end["t_out"], "corner"))
        segs += _fit_piece(c, kept, spans, tol)
    if not segs:
        return None
    nodes = []
    for p0, c1, c2, p3, sharp in segs:
        if nodes:
            nodes[-1][4], nodes[-1][5] = float(c1[0]), float(c1[1])
            nodes[-1][6] = 0 if sharp else nodes[-1][6]
        else:
            nodes.append(bz.node(p0[0], p0[1], None, None, c1[0], c1[1], smooth=not sharp))
        nodes.append(bz.node(p3[0], p3[1], c2[0], c2[1], smooth=True))
    last = nodes.pop()                            # retour au départ : fusionné avec le 1er nœud
    nodes[0][2], nodes[0][3] = last[2], last[3]
    for n in nodes:                               # sans aucune poignée : pas « lisse » (une seule poignée alignée
        if not (bz.has_in(n) or bz.has_out(n)):   # sur la droite voisine = transition lisse, comme Illustrator)
            n[6] = 0
    if len(nodes) < 2:
        return None
    return {"closed": True, "nodes": nodes}


def _fit_piece(c: Contour, cands, runs, tol):
    """Programmation dynamique sur les candidats : moins d'ancres, chaque segment sous la tolérance."""
    n = len(cands)

    def is_run(i, j):                             # extrémités d'une droite (l'une a pu se fondre dans un angle)
        return j == i + 1 and any(abs(a - cands[i][0]) < 1.01 and abs(b - cands[j][0]) < 1.01 for a, b in runs)

    def span(i, j):
        s0, s1 = cands[i][0], cands[j][0]
        margin0 = CORNER_MARGIN if cands[i][4] == "corner" else 0.0
        margin1 = CORNER_MARGIN if cands[j][4] == "corner" else 0.0
        inner, _ss = c.points_between(s0 + margin0, s1 - margin1)
        return np.vstack([cands[i][1][None, :], inner, cands[j][1][None, :]])

    def line(i, j):
        return (cands[i][1], cands[i][1], cands[j][1], cands[j][1])

    best = [math.inf] * n
    choice = [None] * n
    best[0] = 0.0
    for i in range(n - 1):                        # vers l'avant : une portée qui échoue nettement arrête i
        if best[i] == math.inf:
            continue
        for j in range(i + 1, min(n, i + 13)):
            if j > i + 1 and cands[j - 1][4] in ("corner", "extremum"):
                break                             # ni un angle (pli) ni un extremum net ne sont enjambés : ancres
                                                  # aux extrema, convention d'Illustrator et des polices
            if is_run(i, j):
                cost, segs = 1.0, [line(i, j)]
            else:
                # Une droite détectée peut être TRAVERSÉE par une seule cubique si elle tient : un flanc d'ellipse
                # presque plat n'impose pas ses deux ancres ; un fût suivi d'un congé, si (aucune cubique ne passe).
                P = span(i, j)
                if cands[i][4] == "corner" and cands[j][4] == "corner" and _straight_ok(P, tol):
                    cost, segs = 1.0, [line(i, j)]
                else:
                    ctrl, err, _k = fit_cubic_fixed(P, cands[i][3], cands[j][2], tol=tol)
                    if err <= tol:
                        cost, segs = 1.0 + 0.05 * err / tol, [ctrl]     # à nombre égal : le plus précis
                    elif j == i + 1:                  # subdivision PARESSEUSE : faite seulement si retenue
                        segs = None
                        cost = 2.0 + 0.5 * min(4.0, err / tol)
                    elif err > 2.5 * tol:
                        break
                    else:
                        continue
            if best[i] + cost < best[j] - 1e-9:
                best[j] = best[i] + cost
                choice[j] = (i, segs)
    if best[n - 1] == math.inf:                   # filet : tout l'intervalle subdivisé
        P = span(0, n - 1)
        return [(*seg, cands[0][4] == "corner" and k == 0) for k, seg in enumerate(
            _subdivide(c, P, cands[0][3], cands[n - 1][2], tol, cands[0][0], cands[n - 1][0]))]
    out = []
    j = n - 1
    while j > 0:
        i, segs = choice[j]
        if segs is None:
            segs = _subdivide(c, span(i, j), cands[i][3], cands[j][2], tol, cands[i][0], cands[j][0])
        sharp = cands[i][4] == "corner"
        out[:0] = [(*seg, sharp and k == 0) for k, seg in enumerate(segs)]
        j = i
    return out


def _straight_ok(P, tol) -> bool:
    a, b = P[0], P[-1]
    d = b - a
    n = math.hypot(*d)
    if n < 1e-9:
        return True
    dev = np.abs(d[0] * (P[:, 1] - a[1]) - d[1] * (P[:, 0] - a[0])) / n
    return float(dev.max()) <= tol


def _subdivide(c: Contour, P, t0, t1, tol, s0, s1):
    """Intervalle qu'aucune cubique ne couvre : coupes récursives au point d'erreur maximale (tangente centrale,
    partagée : G1), puis REGROUPEMENT : programmation dynamique sur les points de coupe (le moins de segments sous la
    tolérance ; la coupe récursive seule en laissait trop, 4 au lieu de 2 sur le congé d'un pied)."""
    seg = np.hypot(*np.diff(P, axis=0).T)
    cum = np.concatenate([[0.0], np.cumsum(seg)])
    cuts = {0: t0, len(P) - 1: t1}

    def split(i, j, ti, tj, depth):
        _ctrl, err, k = fit_cubic_fixed(P[i:j + 1], ti, tj, tol=tol)
        if err <= tol or depth > 10 or j - i < 4:
            return
        k = i + min(max(k, 2), j - i - 2)
        tm = _tangent(c, s0 + float(cum[k]), min(R, max(0.5, (s1 - s0) / 6)))
        cuts[k] = tm
        split(i, k, ti, tm, depth + 1)
        split(k, j, tm, tj, depth + 1)
    split(0, len(P) - 1, t0, t1, 0)
    keys = sorted(cuts)
    n = len(keys)
    best = [math.inf] * n
    how = [None] * n
    best[0] = 0.0
    for a in range(n - 1):
        for b in range(a + 1, n):
            i, j = keys[a], keys[b]
            ctrl, err, _k = fit_cubic_fixed(P[i:j + 1], cuts[i], cuts[j], tol=tol)
            if err > tol and b > a + 1:
                if err > 2.5 * tol:
                    break
                continue
            if best[a] + 1 < best[b]:
                best[b], how[b] = best[a] + 1, (a, ctrl)
    out = []
    b = n - 1
    while b > 0:
        a, ctrl = how[b]
        out.insert(0, ctrl)
        b = a
    return out
