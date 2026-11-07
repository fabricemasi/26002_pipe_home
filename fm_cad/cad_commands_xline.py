"""Module CAD du board : LIGNES DE CONSTRUCTION — DROITE (XLINE / XL / DROITE : options Hor / Ver / Ang / Bissectrice /
Decalage, comme AutoCAD) et DEMI-DROITE (RAY / DEMIDROITE). Plusieurs par commande (Entree = fin), UNE etape
d'annulation. Geometrie : `cad_xline`. Inscrites dans le REGISTRE de `cad_commands` a l'import (`register`)."""
from __future__ import annotations

import math

from . import cad_xline
from . import cad_geometry as geo
from .cad_commands import Command, Prompt

XLINE_OPTIONS = [("hor", "Hor", ("H", "HOR", "HORIZONTALE")), ("ver", "Ver", ("V", "VER", "VERTICALE")),
                 ("ang", "Ang", ("A", "ANG", "ANGLE")), ("bisect", "Bissectrice", ("B", "BISSECTRICE", "BISECT")),
                 ("offset", "Décalage", ("D", "O", "DECALAGE", "OFFSET"))]


class _ConstructionCommand(Command):
    KIND = "cad_xline"

    def start(self):
        self.made = []

    def _add(self, a, b):
        if geo.distance(a, b) <= geo.EPS:
            self.ctx.message("Direction nulle : ignorée.", error=True)
            return
        self.made.append(self.ctx.create_entity(self.KIND, {"p1": [a[0], a[1]], "p2": [b[0], b[1]]}))

    def _close(self):
        if self.made:
            self.ctx.commit_created(self.made, self.LABEL)
        self.made = []
        self.finish()

    def enter(self):
        self._close()

    def cancel(self):
        self._close()

    def _ghost(self, a, b):
        found = cad_xline.clip(self.KIND, {"p1": list(a), "p2": list(b)}, self._view_rect())
        return [found] if found is not None and geo.distance(a, b) > geo.EPS else []

    def _view_rect(self):
        view = self.ctx.view
        r = view.mapToScene(view.viewport().rect()).boundingRect()
        return r.left(), -r.bottom(), r.right(), -r.top()


class XlineCommand(_ConstructionCommand):
    """DROITE (XLINE / XL) : un point de base puis des points de passage ; ou Hor / Ver (des points de passage), Ang
    (un angle puis des points), Bissectrice (sommet, puis deux points : la bissectrice de l'angle), Decalage (une
    distance, une ligne, le cote)."""

    NAME = "XLINE"
    LABEL = "Droite"
    IMMEDIATE_PICK = True

    def start(self):
        super().start()
        self.mode = "point"             # point | hor | ver | ang | bisect | offset
        self.base = None
        self.angle = None
        self.bisect = []                # sommet, premier point
        self.distance = None
        self.source = None              # ligne a decaler

    def prompt(self):
        if self.mode == "point":
            if self.base is None:
                return Prompt("Spécifiez un point", XLINE_OPTIONS, "point")
            return Prompt("Spécifiez le point de passage", [], "point", self.base)
        if self.mode in ("hor", "ver"):
            return Prompt("Spécifiez le point de passage", [], "point")
        if self.mode == "ang":
            if self.angle is None:
                return Prompt("Entrez l'angle de la droite", [], "point", None, "0", value="angle")
            return Prompt("Spécifiez le point de passage", [], "point")
        if self.mode == "bisect":
            labels = ("Spécifiez le sommet de l'angle", "Spécifiez le point de départ de l'angle",
                      "Spécifiez le point d'arrivée de l'angle")
            return Prompt(labels[min(2, len(self.bisect))], [], "point", self.bisect[0] if self.bisect else None)
        if self.distance is None:
            return Prompt("Spécifiez la distance de décalage", [], "point", None, "", value="length")
        if self.source is None:
            return Prompt("Choisissez une ligne", [], "select")
        return Prompt("Spécifiez le côté du décalage", [], "point")

    def keyword(self, key):
        if self.mode == "point" and self.base is None and key in ("hor", "ver", "ang", "bisect", "offset"):
            self.mode = key

    def value(self, number):
        if self.mode == "ang" and self.angle is None:
            self.angle = number % 360.0
        elif self.mode == "offset" and self.distance is None:
            if number <= 0:
                self.ctx.message("La distance doit être > 0.", error=True)
                return
            self.distance = number

    def point(self, p):
        p = (float(p[0]), float(p[1]))
        if self.mode == "point":
            if self.base is None:
                self.base = p
            else:
                self._add(self.base, p)
        elif self.mode == "hor":
            self._add(p, (p[0] + 1.0, p[1]))
        elif self.mode == "ver":
            self._add(p, (p[0], p[1] + 1.0))
        elif self.mode == "ang" and self.angle is not None:
            r = math.radians(self.angle)
            self._add(p, (p[0] + math.cos(r), p[1] + math.sin(r)))
        elif self.mode == "bisect":
            if len(self.bisect) < 2:
                self.bisect.append(p)
            else:
                self._add(self.bisect[0], self._bisector(p))
        elif self.mode == "offset" and self.distance is not None and self.source is not None:
            self._offset(p)
        elif self.mode == "offset" and self.distance is None:
            pass

    def _bisector(self, p):
        v = self.bisect[0]
        a1 = math.atan2(self.bisect[1][1] - v[1], self.bisect[1][0] - v[0])
        a2 = math.atan2(p[1] - v[1], p[0] - v[0])
        mid = a1 + (((a2 - a1) % (2 * math.pi)) / 2.0)
        return v[0] + math.cos(mid), v[1] + math.sin(mid)

    def picked(self, items):
        for item in items:
            if item.kind in ("cad_line", "cad_xline", "cad_ray"):
                self.source = item
                return
        self.ctx.message("Il faut une ligne (ou une ligne de construction).", error=True)

    def selection_done(self, items):
        if items:
            self.picked(items)
        else:
            self._close()

    def _offset(self, side):
        a, b = self.source.points()
        d = geo.distance(a, b)
        if d <= geo.EPS:
            return
        ux, uy = (b[0] - a[0]) / d, (b[1] - a[1]) / d
        nx, ny = -uy, ux
        sign = 1.0 if (side[0] - a[0]) * nx + (side[1] - a[1]) * ny >= 0 else -1.0
        dx, dy = nx * self.distance * sign, ny * self.distance * sign
        self._add((a[0] + dx, a[1] + dy), (b[0] + dx, b[1] + dy))
        self.source = None

    def ghosts(self, p):
        p = (float(p[0]), float(p[1]))
        if self.mode == "point" and self.base is not None:
            return self._ghost(self.base, p)
        if self.mode == "hor":
            return self._ghost(p, (p[0] + 1.0, p[1]))
        if self.mode == "ver":
            return self._ghost(p, (p[0], p[1] + 1.0))
        if self.mode == "ang" and self.angle is not None:
            r = math.radians(self.angle)
            return self._ghost(p, (p[0] + math.cos(r), p[1] + math.sin(r)))
        if self.mode == "bisect" and len(self.bisect) == 2:
            return self._ghost(self.bisect[0], self._bisector(p))
        return []


class RayCommand(_ConstructionCommand):
    """DEMI-DROITE (RAY) : le point de depart, puis des points de passage (une demi-droite chacun)."""

    NAME = "RAY"
    LABEL = "Demi-droite"
    KIND = "cad_ray"

    def start(self):
        super().start()
        self.base = None

    def prompt(self):
        if self.base is None:
            return Prompt("Spécifiez le point de départ", [], "point")
        return Prompt("Spécifiez le point de passage", [], "point", self.base)

    def point(self, p):
        p = (float(p[0]), float(p[1]))
        if self.base is None:
            self.base = p
        else:
            self._add(self.base, p)

    def ghosts(self, p):
        if self.base is None:
            return []
        return self._ghost(self.base, (float(p[0]), float(p[1])))


NEW_ENTRIES = (
    ("XLINE", "Droite", ("XL", "DROITE"), XlineCommand),
    ("RAY", "Demi-droite", ("DEMIDROITE", "DEMI-DROITE"), RayCommand),
)


def register(registry, entry_class, by_word):
    for name, label, aliases, factory in NEW_ENTRIES:
        if any(e.name == name for e in registry):
            continue
        entry = entry_class(name, label, aliases, factory)
        registry.append(entry)
        for word in (name, *aliases):
            by_word.setdefault(word.upper(), entry)


def _self_register():
    from . import cad_commands as _cc
    if hasattr(_cc, "_BY_WORD"):
        register(_cc.REGISTRY, _cc.Entry, _cc._BY_WORD)


_self_register()
