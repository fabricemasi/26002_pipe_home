"""Transformation libre à poignées (géométrie SANS widget) : échelle, rotation, déplacement d'UN calque autour de son centre.

Le calque est toujours recalculé depuis son ORIGINAL (`transform.TransformSession`) : aucun rééchantillonnage successif pendant
un même geste. Paramètres : décalage (dx, dy), échelles (sx, sy, négatives = symétrie), angle en degrés ; matrice = décalage ∘
rotation ∘ échelle, toutes autour du centre d'origine. Poignées : 8 autour du cadre + une de rotation au-dessus du côté haut."""
from __future__ import annotations

import math

from . import transform as T

HANDLES = {"nw": (-1, -1), "n": (0, -1), "ne": (1, -1), "e": (1, 0), "se": (1, 1), "s": (0, 1), "sw": (-1, 1), "w": (-1, 0)}
ROTATE_OFFSET_PX = 28.0


class FreeTransform:
    def __init__(self, layer):
        self.job = T.TransformSession(layer)
        rect = self.job.rect()
        if rect is None:
            raise ValueError("Calque vide : rien à transformer.")
        self.rect = rect
        self.cx, self.cy = (rect[0] + rect[2]) / 2.0, (rect[1] + rect[3]) / 2.0
        self.hw, self.hh = max(0.5, (rect[2] - rect[0]) / 2.0), max(0.5, (rect[3] - rect[1]) / 2.0)
        self.reset()
        self._drag = None

    def reset(self):
        self.dx = self.dy = 0.0
        self.sx = self.sy = 1.0
        self.angle = 0.0

    # -- géométrie --
    def matrix(self):
        m = T.scaling(self.sx, self.sy, self.cx, self.cy)
        m = T.compose_matrices(T.rotation(self.angle, self.cx, self.cy), m)
        return T.compose_matrices(T.translation(self.dx, self.dy), m)

    def is_identity(self) -> bool:
        return (abs(self.dx) < 1e-9 and abs(self.dy) < 1e-9 and abs(self.sx - 1) < 1e-9 and abs(self.sy - 1) < 1e-9
                and abs(self.angle) < 1e-9)

    def _to_world(self, ux, uy):
        """Point local (autour du centre, avant échelle) -> document."""
        r = math.radians(self.angle)
        c, s = math.cos(r), math.sin(r)
        x, y = ux * self.sx, uy * self.sy
        return self.cx + self.dx + c * x - s * y, self.cy + self.dy + s * x + c * y

    def _to_local(self, x, y):
        """Document -> point local « tourné » (avant échelle) : inverse de la rotation seulement."""
        r = math.radians(-self.angle)
        c, s = math.cos(r), math.sin(r)
        px, py = x - self.cx - self.dx, y - self.cy - self.dy
        return c * px - s * py, s * px + c * py

    def corners(self):
        return [self._to_world(-self.hw, -self.hh), self._to_world(self.hw, -self.hh),
                self._to_world(self.hw, self.hh), self._to_world(-self.hw, self.hh)]

    def handle_points(self, zoom: float = 1.0) -> dict:
        out = {name: self._to_world(hx * self.hw, hy * self.hh) for name, (hx, hy) in HANDLES.items()}
        r = math.radians(self.angle)
        top = out["n"]
        gap = ROTATE_OFFSET_PX / max(zoom, 1e-6)
        sg = 1.0 if self.sy >= 0 else -1.0          # normale extérieure du côté haut, dans le repère tourné
        out["rot"] = (top[0] + math.sin(r) * gap * sg, top[1] - math.cos(r) * gap * sg)
        return out

    def hit(self, x, y, zoom: float = 1.0, tolerance_px: float = 7.0):
        """Nom de la poignée touchée (« nw »…, « rot »), « body » à l'intérieur du cadre, sinon None."""
        tol = tolerance_px / max(zoom, 1e-6)
        for name, (px, py) in self.handle_points(zoom).items():
            if abs(px - x) <= tol and abs(py - y) <= tol:
                return name
        ux, uy = self._to_local(x, y)
        if abs(ux) <= abs(self.sx) * self.hw and abs(uy) <= abs(self.sy) * self.hh:
            return "body"
        return None

    # -- geste --
    def begin(self, name: str, x: float, y: float):
        self._drag = {"name": name, "start": (x, y), "d0": (self.dx, self.dy), "angle0": self.angle,
                      "s0": (self.sx, self.sy)}

    def drag(self, x: float, y: float, shift: bool = False):
        d = self._drag
        if d is None:
            return
        name = d["name"]
        if name == "body":
            self.dx, self.dy = d["d0"][0] + x - d["start"][0], d["d0"][1] + y - d["start"][1]
        elif name == "rot":
            angle = math.degrees(math.atan2(y - self.cy - self.dy, x - self.cx - self.dx)) + 90.0
            if self.sy < 0:
                angle += 180.0
            angle = (angle + 180.0) % 360.0 - 180.0
            self.angle = round(angle / 15.0) * 15.0 if shift else angle
        else:
            hx, hy = HANDLES[name]
            ux, uy = self._to_local(x, y)
            sx, sy = d["s0"]
            if hx:
                sx = ux / (hx * self.hw)
            if hy:
                sy = uy / (hy * self.hh)
            if abs(sx) < 0.01:
                sx = 0.01 if sx >= 0 else -0.01
            if abs(sy) < 0.01:
                sy = 0.01 if sy >= 0 else -0.01
            if shift and hx and hy:
                k = max(abs(sx), abs(sy))
                sx, sy = math.copysign(k, sx), math.copysign(k, sy)
            self.sx, self.sy = sx, sy

    def end(self):
        self._drag = None

    # -- résultat --
    def preview(self):
        """Pose le calque transformé (bilinéaire) ; rend la zone à repeindre."""
        return self.job.render(self.matrix(), "bilinear")

    def cancel(self):
        self.job.cancel()
        return self.job.rect()

    def command(self, quality: str = "bicubic"):
        self.job.matrix = self.matrix()
        return self.job.command(quality, "Transformation libre")
