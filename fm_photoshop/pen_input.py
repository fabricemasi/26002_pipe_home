"""Filtres de trajectoire du stylet (SANS Qt) : un filtre par mode de lissage, tous séparés du rendu de la brosse.

Les positions arrivent en coordonnées du DOCUMENT ; les réglages (fréquences, longueurs) sont en pixels d'ÉCRAN : chaque
filtre convertit avec le zoom (« ajuster pour le zoom »), sinon un même réglage serait deux fois plus fort à 50 %.

- `OneEuro`   : lissage adaptatif (Casiez et al., 2012) : petit mouvement lent -> forte atténuation du tremblement ;
                mouvement rapide -> presque aucun filtrage ; la vitesse vient du temps RÉELLEMENT écoulé.
- `Weighted`  : lissage pondéré (moyenne gaussienne sur la distance parcourue, élargie à basse vitesse) ; un angle
                franc vide l'historique (l'angle voulu est conservé).
- `Rope`      : stabilisateur « corde tirée » (encrage, longues courbes) ; indépendant des deux autres.
Le mode « aucun » n'a pas de filtre : la trajectoire est celle du périphérique."""
from __future__ import annotations

import math


def _alpha(cutoff: float, dt: float) -> float:
    tau = 1.0 / (2.0 * math.pi * max(cutoff, 1e-6))
    return 1.0 / (1.0 + tau / max(dt, 1e-6))


class OneEuro:
    """Filtre One Euro vectoriel : une seule fréquence de coupure pour X et Y (pas de distorsion entre les axes)."""

    D_CUTOFF = 1.0          # Hz : lissage de la vitesse estimée

    def __init__(self):
        self.t = None
        self.raw = self.out = self.vel = None

    def apply(self, x, y, t, min_cutoff, beta):
        """(x, y) en pixels d'écran, `t` en secondes. Rend la position filtrée."""
        if self.t is None:
            self.t, self.raw, self.out, self.vel = t, (x, y), (x, y), (0.0, 0.0)
            return x, y
        dt = min(max(t - self.t, 1e-4), 0.25)               # temps réel entre deux échantillons (borné)
        vx, vy = (x - self.raw[0]) / dt, (y - self.raw[1]) / dt
        ad = _alpha(self.D_CUTOFF, dt)
        self.vel = (self.vel[0] + ad * (vx - self.vel[0]), self.vel[1] + ad * (vy - self.vel[1]))
        cutoff = min_cutoff + beta * math.hypot(*self.vel)
        a = _alpha(cutoff, dt)
        self.out = (self.out[0] + a * (x - self.out[0]), self.out[1] + a * (y - self.out[1]))
        self.t, self.raw = t, (x, y)
        return self.out


class Weighted:
    """Moyenne gaussienne des derniers points, pondérée par la DISTANCE parcourue derrière le curseur. La fenêtre se
    resserre quand la vitesse monte (les gestes rapides gardent leur détail) et se vide à un angle franc."""

    V_REF = 300.0           # px/s d'écran : à cette vitesse la fenêtre est réduite de moitié
    CORNER_COS = 0.5        # angle > 60° entre deux segments significatifs = changement de direction voulu

    def __init__(self):
        self.pts = []       # (x, y, s) : s = longueur d'arc cumulée
        self.t = None
        self.v = 0.0

    def apply(self, x, y, t, window):
        pts = self.pts
        if not pts:
            self.pts, self.t = [(x, y, 0.0)], t
            return x, y
        px, py, ps = pts[-1]
        seg = math.hypot(x - px, y - py)
        dt = min(max(t - self.t, 1e-4), 0.25)
        self.v += 0.5 * (seg / dt - self.v)
        self.t = t
        if seg > 1e-9:
            if len(pts) >= 2:
                ax, ay, _ = pts[-2]
                lx, ly = px - ax, py - ay
                ln = math.hypot(lx, ly)
                if ln > 2.0 and seg > 2.0 and (lx * (x - px) + ly * (y - py)) / (ln * seg) < self.CORNER_COS:
                    pts[:] = [pts[-1]]                      # angle franc : on repart du coin
            pts.append((x, y, pts[-1][2] + seg))
        sigma = max(0.01, window / 2.0 / (1.0 + self.v / self.V_REF))
        s_now = pts[-1][2]
        while len(pts) > 2 and s_now - pts[0][2] > 3.0 * sigma:
            pts.pop(0)
        sw = sx = sy = 0.0
        for qx, qy, qs in pts:
            w = math.exp(-0.5 * ((s_now - qs) / sigma) ** 2)
            sw += w
            sx += w * qx
            sy += w * qy
        return sx / sw, sy / sw


class Rope:
    """Stabilisateur « corde tirée » : la pointe suit le curseur à distance de corde ; tant que le curseur reste dans la
    corde, rien n'avance."""

    def __init__(self, start):
        self.tip = start

    def apply(self, x, y, rope):
        px, py = self.tip
        dx, dy = x - px, y - py
        dist = math.hypot(dx, dy)
        if dist <= rope:
            return None
        f = (dist - rope) / dist
        self.tip = (px + dx * f, py + dy * f)
        return self.tip
