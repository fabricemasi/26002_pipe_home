"""Module CAD du board : commandes des phases 2 et 3 du cahier des charges, a la maniere d'AutoCAD (voir
`cad_commands` pour le protocole : invites, points resolus, options, Entree / Echap, une etape d'annulation par
commande) — POINT, DIVISER, MESURER, ELLIPSE, POLYGONE, PROLONGER, ETIRER, COUPURE, JOINDRE, RESEAU. Geometrie dans
`cad_draw` (pure). Inscrites dans le REGISTRE de `cad_commands` a l'import (`register`)."""
from __future__ import annotations

import math

from . import cad_draw, cad_point, cad_shapes, cad_trim
from . import cad_geometry as geo
from .cad_commands import (EXIT_OPT, TRIMMABLE, UNDO_OPT, Command, Prompt, TrimCommand, _SelectingCommand, _show,
                           _transform_ghosts)


def _point_data(ctx, p) -> dict:
    """Champs d'un point neuf : position + figure des reglages (Module CAD > Points)."""
    mode = cad_point.clean_mode(ctx.setting("board_cad_point_mode", cad_point.DEFAULTS["pdmode"]))
    size = max(0.0, float(ctx.setting("board_cad_point_size", 300) or 0.0)) / 100.0 * ctx.unit()
    return {"pos": [float(p[0]), float(p[1])], "pdmode": mode, "pdsize": size, "lineweight": 0.0}


# ==========================================================================
# POINT (PO), DIVISER (DIV), MESURER (ME)
# ==========================================================================

class PointCommand(Command):
    """POINT (PO) : un point a chaque clic (figure et taille des reglages, comme PDMODE / PDSIZE) ; Entree / Echap
    termine. Une etape d'annulation pour tous."""

    NAME = "POINT"
    LABEL = "Point"

    def start(self):
        self.made = []

    def prompt(self):
        return Prompt("Spécifiez un point", [], "point", None, "terminer" if self.made else "")

    def point(self, p):
        self.made.append(self.ctx.create_entity("cad_point", _point_data(self.ctx, p)))

    def finish(self):
        if not self.finished and self.made:
            self.ctx.commit_created(self.made, "Point")
        super().finish()

    def preview(self, p):
        return _show(self.ctx, "cad_point", _point_data(self.ctx, p))


class DivideCommand(Command):
    """DIVISER (DIV) : un objet, puis le nombre de segments (2 a 32 767) : des points a intervalles egaux le long de
    l'objet (ni au debut ni a la fin ; un objet ferme : n points). MESURER (ME) : la longueur d'un segment, des points
    tous les tant depuis le bout le plus proche du clic."""

    NAME = "DIVIDE"
    LABEL = "Diviser"
    IMMEDIATE_PICK = True
    MEASURE = False

    def start(self):
        self.item = None
        self.pick = None

    def prompt(self):
        if self.item is None:
            return Prompt("Choisissez l'objet à " + ("mesurer" if self.MEASURE else "diviser"), [], "select")
        if self.MEASURE:
            return Prompt("Spécifiez la longueur de segment", [], "point", None, value="length")
        return Prompt("Entrez le nombre de segments", [], "point", None, value="count")

    def picked(self, items):
        items = [i for i in items if i.kind in TRIMMABLE]
        if not items:
            self.ctx.message("Lignes, arcs, cercles et polylignes seulement.", error=True)
            return
        self.item = items[0]
        self.pick = self.ctx.last_pick_doc
        self.ctx.highlight([self.item])

    def selection_done(self, items):
        if items:
            self.picked(items)
        else:
            self.finish()

    def point(self, p):
        if self.item is None:
            return
        if self.MEASURE:
            self.value(geo.distance(self.pick or p, p))
        else:
            self.ctx.message("Tapez le nombre de segments.", error=True)

    def value(self, number):
        if self.item is None:
            return
        primitives = self.item.prims()
        total = cad_shapes.total_length(primitives)
        closed = cad_trim.is_closed(self.item.kind, self.item.to_dict())
        if self.MEASURE:
            if number <= geo.EPS:
                self.ctx.message("La longueur doit être positive.", error=True)
                return
            if self.pick is not None and not closed and \
                    geo.distance(self.pick, cad_shapes.prim_end(primitives[-1])) < \
                    geo.distance(self.pick, cad_shapes.prim_start(primitives[0])):
                primitives = cad_draw.reverse(primitives)          # depuis le bout le plus proche du clic
            params = [k * number for k in range(1, int(total / number + 1e-9) + 1)]
            if params and abs(params[-1] - total) <= geo.EPS and not closed:
                params.pop()
        else:
            count = int(round(number))
            if count < 2 or count > 32767:
                self.ctx.message("Le nombre de segments doit aller de 2 à 32767.", error=True)
                return
            params = [total * k / count for k in (range(count) if closed else range(1, count))]
        made = [self.ctx.create_entity("cad_point", _point_data(self.ctx, cad_draw.station(primitives, s)[0]))
                for s in params]
        if made:
            self.ctx.commit_created(made, self.LABEL)
            self.ctx.message(f"{self.LABEL} : {len(made)} point(s).")
        else:
            self.ctx.message("Segment plus long que l'objet : aucun point.", error=True)
        self.finish()

    def finish(self):
        if not self.finished:
            self.ctx.highlight([])
        super().finish()


class MeasureCommand(DivideCommand):
    NAME = "MEASURE"
    LABEL = "Mesurer"
    MEASURE = True


# ==========================================================================
# ELLIPSE (EL)
# ==========================================================================

class EllipseCommand(Command):
    """ELLIPSE (EL), comme AutoCAD : extremite d'un axe, autre extremite, puis la distance a l'autre axe (ou Rotation
    autour du grand axe) ; option Centre (centre, extremite d'un axe, autre axe) ; option Arc (ellipse partielle :
    puis angles de depart et de fin). Resultat : une polyligne d'arcs (comme PELLIPSE = 1)."""

    NAME = "ELLIPSE"
    LABEL = "Ellipse"

    def start(self):
        self.arc = False
        self.mode = "axis"                  # axis (deux extremites) | center
        self.pts = []                       # extremites / centre
        self.center = self.major = None
        self.ratio = None
        self.start_t = None
        self.stage = "first"                # first | second | other | rotation | start | end

    def prompt(self):
        arc_opt = ("arc", "Arc", ("A", "ARC"))
        center_opt = ("center", "Centre", ("C", "CENTRE", "CENTER"))
        if self.stage == "first":
            if self.mode == "center":
                return Prompt("Spécifiez le centre de l'ellipse", [], "point")
            options = [center_opt] if self.arc else [arc_opt, center_opt]
            return Prompt("Spécifiez l'extrémité de l'axe " + ("de l'arc elliptique" if self.arc else "de l'ellipse"),
                          options, "point")
        if self.stage == "second":
            text = "Spécifiez l'extrémité de l'axe" if self.mode == "center" else "Spécifiez l'autre extrémité de l'axe"
            return Prompt(text, [], "point", self.pts[0])
        if self.stage == "other":
            return Prompt("Spécifiez la distance à l'autre axe", [("rotation", "Rotation", ("R", "ROTATION"))],
                          "point", self.center, value="length")
        if self.stage == "rotation":
            return Prompt("Spécifiez la rotation autour de l'axe principal", [], "point", self.center, value="angle")
        if self.stage == "start":
            return Prompt("Spécifiez l'angle de départ", [], "point", self.center, value="angle")
        return Prompt("Spécifiez l'angle de fin", [], "point", self.center, value="angle")

    def keyword(self, key):
        if key == "arc" and self.stage == "first":
            self.arc = True
        elif key == "center" and self.stage == "first":
            self.mode = "center"
        elif key == "rotation" and self.stage == "other":
            self.stage = "rotation"

    def _axis(self, p):
        """Centre et demi grand axe (vecteur) d'apres les deux premiers points."""
        a, b = self.pts[0], p
        if self.mode == "center":
            return a, geo.sub(b, a)
        return geo.midpoint(a, b), geo.mul(geo.sub(b, a), 0.5)

    def point(self, p):
        p = (float(p[0]), float(p[1]))
        if self.stage == "first":
            self.pts = [p]
            self.stage = "second"
        elif self.stage == "second":
            if geo.distance(self.pts[0], p) <= geo.EPS:
                self.ctx.message("Axe de longueur nulle.", error=True)
                return
            self.center, self.major = self._axis(p)
            self.stage = "other"
        elif self.stage == "other":
            self._other(self._distance_to_axis(p))
        elif self.stage == "rotation":
            self._rotation(geo.angle_deg(self.center, p))
        elif self.stage == "start":
            self.start_t = cad_draw.ellipse_param(self.center, self.major, self.ratio, p)
            self.stage = "end"
        elif self.stage == "end":
            self._make(cad_draw.ellipse_param(self.center, self.major, self.ratio, p))

    def _distance_to_axis(self, p) -> float:
        a = math.hypot(*self.major)
        ux, uy = self.major[0] / a, self.major[1] / a
        dx, dy = p[0] - self.center[0], p[1] - self.center[1]
        return abs(-dx * uy + dy * ux)

    def value(self, number):
        if self.stage == "other":
            self._other(number)
        elif self.stage == "rotation":
            self._rotation(number)
        elif self.stage in ("start", "end"):
            t = self._param_of_angle(number)
            if self.stage == "start":
                self.start_t = t
                self.stage = "end"
            else:
                self._make(t)
        else:
            self.ctx.message("Un point est attendu ici.", error=True)

    def _param_of_angle(self, degrees: float) -> float:
        """Angle (degres, depuis le grand axe, comme AutoCAD) -> parametre de l'ellipse."""
        r = math.radians(degrees)
        return math.atan2(math.sin(r) / self.ratio, math.cos(r)) % (2.0 * math.pi)

    def _other(self, distance: float):
        a = math.hypot(*self.major)
        if distance <= geo.EPS:
            self.ctx.message("Le demi-axe doit être positif.", error=True)
            return
        if distance > a:                                     # l'autre axe est le grand : on echange
            self.major = geo.mul((-self.major[1], self.major[0]), distance / a)
            self.ratio = a / distance
        else:
            self.ratio = distance / a
        self._after_shape()

    def _rotation(self, degrees: float):
        ratio = abs(math.cos(math.radians(degrees)))
        if ratio <= 1e-6 or abs(degrees % 180.0 - 90.0) < 0.01:
            self.ctx.message("Rotation de 89,99° au plus.", error=True)
            return
        self.ratio = ratio
        self._after_shape()

    def _after_shape(self):
        if self.arc:
            self.stage = "start"
        else:
            self._make(None)

    def _data(self, end_t):
        if end_t is None:
            vertices, closed = cad_draw.ellipse_vertices(self.center, self.major, self.ratio)
        else:
            vertices, closed = cad_draw.ellipse_vertices(self.center, self.major, self.ratio, self.start_t, end_t)
        return {"vertices": vertices, "closed": closed}

    def _make(self, end_t):
        if end_t is not None and abs((end_t - self.start_t) % (2.0 * math.pi)) <= 1e-9:
            self.ctx.message("Angles de départ et de fin confondus.", error=True)
            return
        item = self.ctx.create_entity("cad_pline", self._data(end_t))
        self.ctx.commit_created([item], "Ellipse")
        self.finish()

    def preview(self, p):
        p = (float(p[0]), float(p[1]))
        try:
            if self.stage == "second" and geo.distance(self.pts[0], p) > geo.EPS:
                center, major = self._axis(p)
                return [("rubber", self.pts[0], p)] + _show(self.ctx, "cad_pline", {
                    "vertices": cad_draw.ellipse_vertices(center, major, 0.5)[0], "closed": True})
            if self.stage == "other":
                d = self._distance_to_axis(p)
                a = math.hypot(*self.major)
                if d > geo.EPS:
                    major, ratio = (self.major, d / a) if d <= a else \
                        (geo.mul((-self.major[1], self.major[0]), d / a), a / d)
                    return [("rubber", self.center, p)] + _show(self.ctx, "cad_pline", {
                        "vertices": cad_draw.ellipse_vertices(self.center, major, ratio)[0], "closed": True})
            if self.stage == "end":
                t = cad_draw.ellipse_param(self.center, self.major, self.ratio, p)
                if abs((t - self.start_t) % (2.0 * math.pi)) > 1e-6:
                    return [("rubber", self.center, p)] + _show(self.ctx, "cad_pline", self._data(t))
            if self.stage == "start":
                return [("rubber", self.center, p)] + _show(self.ctx, "cad_pline", {
                    "vertices": cad_draw.ellipse_vertices(self.center, self.major, self.ratio)[0], "closed": True})
        except (ValueError, ZeroDivisionError):
            return []
        return []


# ==========================================================================
# POLYGONE (POL)
# ==========================================================================

class PolygonCommand(Command):
    """POLYGONE (POL) : nombre de cotes (3 a 1024, retenu), centre puis Inscrit / Circonscrit et le rayon (point :
    rayon ET orientation ; valeur : cote du bas horizontal), ou Cote (deux points du premier cote). Polyligne fermee."""

    NAME = "POLYGON"
    LABEL = "Polygone"

    def start(self):
        self.sides = None
        self.center = None
        self.edge = []
        self.stage = "sides"                # sides | center | kind | radius | edge1 | edge2
        self.inscribed = self.ctx.tool_memory.get("polygon_inscribed", True)

    def _default_sides(self) -> int:
        return int(self.ctx.tool_memory.get("polygon_sides", 4))

    def prompt(self):
        if self.stage == "sides":
            return Prompt("Entrez le nombre de côtés", [], "point", None, str(self._default_sides()), value="count")
        if self.stage == "center":
            return Prompt("Spécifiez le centre du polygone", [("edge", "Côté", ("C", "COTE", "CÔTÉ", "E", "EDGE"))],
                          "point")
        if self.stage == "kind":
            return Prompt("Entrez une option", [("in", "Inscrit dans le cercle", ("I", "INSCRIT")),
                                                ("out", "Circonscrit au cercle", ("C", "CIRCONSCRIT"))],
                          "point", self.center, "Inscrit" if self.inscribed else "Circonscrit")
        if self.stage == "radius":
            return Prompt("Spécifiez le rayon du cercle", [], "point", self.center, value="length")
        if self.stage == "edge1":
            return Prompt("Spécifiez la première extrémité du côté", [], "point")
        return Prompt("Spécifiez la deuxième extrémité du côté", [], "point", self.edge[0])

    def value(self, number):
        if self.stage == "sides":
            self._sides(number)
        elif self.stage == "radius":
            if number <= geo.EPS:
                self.ctx.message("Le rayon doit être positif.", error=True)
                return
            # valeur : un cote du bas horizontal (comme AutoCAD)
            step = 360.0 / self.sides
            angle = -90.0 + step / 2.0 if self.inscribed else -90.0
            self._make(cad_draw.polygon_vertices(self.center, self.sides,
                                                 cad_shapes.arc_point(self.center, number, angle), self.inscribed))
        else:
            self.ctx.message("Un point est attendu ici.", error=True)

    def _sides(self, number):
        count = int(round(number))
        if count < 3 or count > 1024:
            self.ctx.message("De 3 à 1024 côtés.", error=True)
            return
        self.sides = self.ctx.tool_memory["polygon_sides"] = count
        self.stage = "center"

    def enter(self):
        if self.stage == "sides":
            self._sides(self._default_sides())
        elif self.stage == "kind":
            self.stage = "radius"
        else:
            self.finish()

    def keyword(self, key):
        if key == "edge" and self.stage == "center":
            self.stage = "edge1"
        elif key in ("in", "out") and self.stage == "kind":
            self.inscribed = self.ctx.tool_memory["polygon_inscribed"] = key == "in"
            self.stage = "radius"

    def point(self, p):
        p = (float(p[0]), float(p[1]))
        if self.stage == "sides":
            self.ctx.message("Tapez le nombre de côtés.", error=True)
        elif self.stage == "center":
            self.center = p
            self.stage = "kind"
        elif self.stage == "kind":
            self.stage = "radius"
            self.point(p)
        elif self.stage == "radius":
            if geo.distance(self.center, p) <= geo.EPS:
                self.ctx.message("Rayon nul.", error=True)
                return
            self._make(cad_draw.polygon_vertices(self.center, self.sides, p, self.inscribed))
        elif self.stage == "edge1":
            self.edge = [p]
            self.stage = "edge2"
        elif self.stage == "edge2":
            if geo.distance(self.edge[0], p) <= geo.EPS:
                self.ctx.message("Côté de longueur nulle.", error=True)
                return
            self._make(cad_draw.polygon_from_edge(self.edge[0], p, self.sides))

    def _make(self, vertices):
        item = self.ctx.create_entity("cad_pline", {"vertices": vertices, "closed": True})
        self.ctx.commit_created([item], "Polygone")
        self.finish()

    def preview(self, p):
        if self.stage == "radius" and geo.distance(self.center, p) > geo.EPS:
            data = {"vertices": cad_draw.polygon_vertices(self.center, self.sides, p, self.inscribed), "closed": True}
            return [("rubber", self.center, p)] + _show(self.ctx, "cad_pline", data)
        if self.stage == "edge2" and geo.distance(self.edge[0], p) > geo.EPS:
            data = {"vertices": cad_draw.polygon_from_edge(self.edge[0], p, self.sides), "closed": True}
            return _show(self.ctx, "cad_pline", data)
        return []


# ==========================================================================
# PROLONGER (EX) : AJUSTER a l'envers (Maj + clic = ajuster)
# ==========================================================================

class ExtendCommand(TrimCommand):
    """PROLONGER (EX), comme AutoCAD 2021+ : memes modes, options et gestes qu'AJUSTER (Rapide : tous les objets sont
    des limites ; Standard : d'abord les limites), mais un clic PROLONGE l'objet jusqu'a la premiere limite (du cote
    du bout le plus proche du clic) et Maj + clic l'AJUSTE. Trajet, capture, trace a main levee : chaque objet touche
    est prolonge. Une etape d'annulation par geste."""

    NAME = "EXTEND"
    LABEL = "Prolonger"

    def _wants_extend(self, shift: bool) -> bool:
        return not shift

    def prompt(self):
        found = super().prompt()
        if found.text.startswith("Choisissez l'objet à ajuster"):
            found.text = "Choisissez l'objet à prolonger ou Maj + clic pour l'ajuster"
        elif found.text.startswith("Choisissez les arêtes de coupe"):
            found.text = "Choisissez les limites"
        return found

    def _extended(self, item, point):
        result = cad_trim.extend(item.kind, item.to_dict(), self._cutter_prims(item, local=False), point,
                                 self.extend_edges)
        return None if isinstance(result, str) else result

    def _apply(self, targets: dict, results: dict | None = None):
        changes, created, deleted = [], [], []
        for item, points in targets.items():
            if item.kind not in TRIMMABLE or item.locked() or not points:
                continue
            found = self._extended(item, points[0])
            if found is None:
                continue
            kind, geometry = found
            if kind == item.kind:
                changes.append((item, geometry))
            else:
                created.append((kind, geometry, item))
                deleted.append(item)
        if not (changes or created):
            self.ctx.message("Aucun objet à prolonger jusqu'à une limite.", error=True)
            return
        self.ctx.apply_edit(changes, created, "Prolonger", deleted)
        self.count += 1

    def _removed_ghosts(self, targets: dict) -> list:
        out = []
        tol = self.ctx.tess_tol()
        for item, points in targets.items():
            if item.kind in TRIMMABLE and points:
                found = self._extended(item, points[0])
                if found is not None:
                    out += cad_shapes.display_segments(cad_shapes.prims(*found), tol)
        return out

    def finish(self):
        if not self.finished:
            self.ctx.highlight([])
            if self.count:
                self.ctx.message(f"Prolonger : {self.count} modification(s).")
            self.finished = True


# ==========================================================================
# ETIRER (S)
# ==========================================================================

STRETCH_GRIPS = {"cad_line": ("p1", "p2"), "cad_arc": ("start", "end", "center"), "cad_circle": ("center",),
                 "cad_dim": ("p1", "p2", "pos"), "cad_text": ("pos",), "cad_point": ("pos",)}


def _inside(p, rect) -> bool:
    return rect[0] <= p[0] <= rect[2] and rect[1] <= p[1] <= rect[3]


def stretched(item_kind: str, data: dict, rect, delta):
    """Champs geometriques d'une entite ETIREE : ses points de definition dans la capture `rect` bougent de `delta`
    (tous dedans : elle est deplacee) ; None = rien a faire."""
    names = [name for name, p in cad_shapes.grips(item_kind, data) if _inside(p, rect)]
    if item_kind == "cad_pline":
        allowed = [n for n in names if n.startswith("v")]
        every = len(allowed) == len(data.get("vertices") or [])
    elif item_kind == "cad_hatch":
        loops = data.get("loops") or []
        every = bool(loops) and all(_inside(p, rect) for loop in loops for p in loop)
        allowed = []
    else:
        keys = STRETCH_GRIPS.get(item_kind, ())
        allowed = [n for n in names if n in keys]
        every = bool(keys) and all(n in allowed for n in keys if n != "center" or item_kind == "cad_circle")
        if item_kind == "cad_arc" and "start" in allowed and "end" in allowed:
            every = True
    if every:
        return cad_shapes.translated(item_kind, data, delta)
    if not allowed:
        return None
    if item_kind == "cad_arc":
        allowed = [n for n in allowed if n != "center"]
        if not allowed:
            return None
    return cad_shapes.grip_edit(item_kind, data, allowed, delta, False)


class StretchCommand(Command):
    """ETIRER (S), comme AutoCAD : une CAPTURE (deux coins) choisit les objets ; leurs points dans la capture bougent
    (lignes, arcs, polylignes, cotations, textes, points : ceux de la capture ; tout dedans = deplace), le reste ne
    bouge pas ; puis point de base et deuxieme point (ou Deplacement)."""

    NAME = "STRETCH"
    LABEL = "Étirer"
    MODIFY = True

    def start(self):
        self.corner = None
        self.rect = None
        self.items = []
        self.base = None
        self.ctx.scene.clearSelection()

    def prompt(self):
        if self.rect is None:
            text = "Spécifiez le premier coin de la capture (objets à étirer)" if self.corner is None else \
                "Spécifiez le coin opposé"
            return Prompt(text, [], "point")
        if self.base is None:
            return Prompt("Spécifiez le point de base", [("disp", "Déplacement", ("D", "DEPLACEMENT"))], "point",
                          None, "Déplacement")
        return Prompt("Spécifiez le deuxième point", [], "point", self.base,
                      "utiliser le premier point comme déplacement")

    def point(self, p):
        p = (float(p[0]), float(p[1]))
        if self.rect is None:
            if self.corner is None:
                self.corner = p
                return
            a = self.corner
            self.rect = (min(a[0], p[0]), min(a[1], p[1]), max(a[0], p[0]), max(a[1], p[1]))
            found = [i for i in self.ctx._source(self.rect) if not i.locked()]
            self.items = [i for i in found if self._touches(i)]
            if not self.items:
                self.ctx.message("Aucun objet dans la capture.", error=True)
                self.finish()
                return
            self.ctx.highlight(self.items)
            return
        if self.base is None:
            self.base = p
            return
        self._apply(geo.sub(p, self.base))

    def _touches(self, item) -> bool:
        return stretched(item.kind, item.to_dict(), self.rect, (1.0, 0.0)) is not None

    def keyword(self, key):
        if key == "disp" and self.rect is not None and self.base is None:
            self.base = (0.0, 0.0)

    def enter(self):
        if self.rect is not None and self.base is not None:
            self._apply(self.base)
            return
        self.finish()

    def _apply(self, delta):
        changes = []
        for item in self.items:
            geometry = stretched(item.kind, item.to_dict(), self.rect, delta)
            if geometry is not None:
                changes.append((item, geometry))
        if changes:
            self.ctx.apply_edit(changes, [], "Étirer")
            self.ctx.message(f"Étirer : {len(changes)} objet(s).")
        self.finish()

    def finish(self):
        if not self.finished:
            self.ctx.highlight([])
        super().finish()

    def preview(self, p):
        if self.rect is None and self.corner is not None:
            (x0, y0), (x1, y1) = self.corner, p
            corners = [(x0, y0), (x1, y0), (x1, y1), (x0, y1), (x0, y0)]
            return [("fence", a, b) for a, b in zip(corners, corners[1:])]
        if self.base is not None:
            return [("rubber", self.base, p)]
        return []

    def ghosts(self, p):
        if self.rect is None or self.base is None:
            return []
        delta = geo.sub(p, self.base)
        out = []
        for item in self.items:
            geometry = stretched(item.kind, item.to_dict(), self.rect, delta)
            if geometry is not None:
                data = item.to_dict()
                data.update(geometry)
                out += cad_shapes.display_segments(cad_shapes.prims(item.kind, data), self.ctx.tess_tol())
        return out


# ==========================================================================
# COUPURE (BR)
# ==========================================================================

class BreakCommand(Command):
    """COUPURE (BR), comme AutoCAD : l'objet (le point du clic est le 1er point de coupure, option Premier point pour
    le redonner), puis le 2e point : la partie entre les deux disparait (cercle / polyligne fermee : dans le sens
    trigonometrique du 1er au 2e) ; 2e point = « @ » ou le 1er point : l'objet est COUPE EN DEUX sans rien retirer
    (COUPURE AU POINT)."""

    NAME = "BREAK"
    LABEL = "Coupure"
    IMMEDIATE_PICK = True
    MODIFY = True
    AT_POINT = False

    def start(self):
        self.item = None
        self.first = None
        self.stage = "pick"                 # pick | first | second

    def prompt(self):
        if self.item is None:
            return Prompt("Choisissez l'objet", [], "select")
        if self.stage == "first":
            return Prompt("Spécifiez le premier point de coupure", [], "point")
        if self.AT_POINT:
            return Prompt("Spécifiez le point de coupure", [], "point")
        return Prompt("Spécifiez le deuxième point de coupure", [("first", "Premier point", ("P", "PREMIER", "F"))],
                      "point", None, "@ (couper en deux)")

    def picked(self, items):
        items = [i for i in items if i.kind in TRIMMABLE and not i.locked()]
        if not items:
            self.ctx.message("Lignes, arcs, cercles et polylignes non verrouillés seulement.", error=True)
            return
        self.item = items[0]
        self.first = self.ctx.last_pick_doc
        self.stage = "first" if self.AT_POINT else "second"
        self.ctx.highlight([self.item])

    def selection_done(self, items):
        if items:
            self.picked(items)
        else:
            self.finish()

    def keyword(self, key):
        if key == "first" and self.item is not None:
            self.stage = "first"

    def point(self, p):
        if self.item is None:
            return
        p = (float(p[0]), float(p[1]))
        if self.stage == "first":
            self.first = p
            if self.AT_POINT:
                self._apply(p, p)
                return
            self.stage = "second"
            return
        self._apply(self.first, p)

    def enter(self):
        if self.item is not None and self.stage == "second" and self.first is not None:
            self._apply(self.first, self.first)            # Entree = « @ » : coupure au point
            return
        self.finish()

    def _apply(self, a, b):
        result = break_pieces(self.item.kind, self.item.to_dict(), a, b)
        if isinstance(result, str):
            self.ctx.message(result, error=True)
            return
        entities = [cad_shapes.prims_to_entity(piece, False) for piece in result]
        changes, created = [], []
        for index, (kind, geometry) in enumerate(entities):
            if index == 0 and kind == self.item.kind:
                changes.append((self.item, geometry))
            else:
                created.append((kind, geometry, self.item))
        deleted = [] if changes else [self.item]
        self.ctx.apply_edit(changes, created, "Coupure", deleted)
        self.finish()

    def finish(self):
        if not self.finished:
            self.ctx.highlight([])
        super().finish()

    def ghosts(self, p):
        if self.item is None or self.stage != "second" or self.first is None:
            return []
        result = break_pieces(self.item.kind, self.item.to_dict(), self.first, p)
        if isinstance(result, str):
            return []
        primitives = self.item.prims()
        total = cad_shapes.total_length(primitives)
        u0 = cad_trim.click_param(primitives, self.first)
        u1 = cad_trim.click_param(primitives, p)
        closed = cad_trim.is_closed(self.item.kind, self.item.to_dict())
        lo, hi = (u0, u1) if (closed or u0 <= u1) else (u1, u0)
        gone = cad_shapes.sub_prims(primitives, lo, hi) if hi >= lo else \
            cad_shapes.sub_prims(primitives, lo, total) + cad_shapes.sub_prims(primitives, 0.0, hi)
        return cad_shapes.display_segments(gone, self.ctx.tess_tol())


class BreakAtPointCommand(BreakCommand):
    NAME = "BREAKATPOINT"
    LABEL = "Coupure au point"
    AT_POINT = True


def break_pieces(kind: str, data: dict, a, b):
    """Morceaux [[primitives], ...] qui restent apres une COUPURE entre `a` et `b` (projetes sur l'objet) ; `a` = `b`
    : l'objet en deux (un objet ferme est seulement rouvert en ce point) ; message si rien ne change."""
    primitives = cad_shapes.prims(kind, data)
    total = cad_shapes.total_length(primitives)
    if total <= geo.EPS:
        return "Objet de longueur nulle."
    closed = cad_trim.is_closed(kind, data)
    u0 = cad_trim.click_param(primitives, a)
    u1 = cad_trim.click_param(primitives, b)
    eps = max(geo.EPS, total * 1e-9)
    if abs(u1 - u0) <= eps:                                 # coupure au point
        if closed:
            return [cad_shapes.sub_prims(primitives, u0, total) + cad_shapes.sub_prims(primitives, 0.0, u0)] \
                if kind != "cad_circle" else "Un cercle ne se coupe pas en un seul point (AutoCAD non plus)."
        if u0 <= eps or u0 >= total - eps:
            return "Point de coupure à l'extrémité : rien à couper."
        return [cad_shapes.sub_prims(primitives, 0.0, u0), cad_shapes.sub_prims(primitives, u0, total)]
    if closed:
        if u1 >= u0:                                        # retire de u0 a u1 (sens de parcours)
            kept = cad_shapes.sub_prims(primitives, u1, total) + cad_shapes.sub_prims(primitives, 0.0, u0)
        else:
            kept = cad_shapes.sub_prims(primitives, u1, u0)
        kept = [p for p in kept if cad_shapes.prim_length(p) > eps]
        return [kept] if kept else "Rien ne resterait de l'objet."
    lo, hi = sorted((u0, u1))
    out = [cad_shapes.sub_prims(primitives, 0.0, lo), cad_shapes.sub_prims(primitives, hi, total)]
    out = [[p for p in piece if cad_shapes.prim_length(p) > eps] for piece in out]
    out = [piece for piece in out if piece]
    return out if out else "Rien ne resterait de l'objet."


# ==========================================================================
# JOINDRE (J)
# ==========================================================================

class JoinCommand(_SelectingCommand):
    """JOINDRE (J) : les objets choisis (lignes, arcs, polylignes ouvertes) mis BOUT A BOUT (extremites confondues a
    1e-6 du dessin pres) : lignes colineaires -> une ligne, arcs d'un meme cercle -> un arc (ou un cercle), sinon une
    POLYLIGNE ; chaque chaine garde les proprietes de son premier objet. Une etape d'annulation."""

    NAME = "JOIN"
    LABEL = "Joindre"

    def after_selection(self):
        pieces = [(item.prims(), item) for item in self.items
                  if item.kind in ("cad_line", "cad_arc", "cad_pline")
                  and not cad_trim.is_closed(item.kind, item.to_dict())]
        if len(pieces) < 2:
            self.ctx.message("Choisissez au moins deux lignes, arcs ou polylignes ouvertes.", error=True)
            self.finish()
            return
        extent = max(1.0, max(abs(v) for prims, _i in pieces for p in prims
                              for v in (*cad_shapes.prim_start(p), *cad_shapes.prim_end(p))))
        tol = max(1e-6, extent * 1e-9)
        changes, created, deleted = [], [], []
        joined_count = 0
        for found in cad_draw.chain(pieces, tol):
            if len(found) < 2:
                continue
            kind, geometry = cad_draw.joined(found, tol)
            source = found[0][1]
            if kind == source.kind:
                changes.append((source, geometry))
            else:
                created.append((kind, geometry, source))
                deleted.append(source)
            deleted.extend(key for _prims, key in found[1:])
            joined_count += len(found)
        if not (changes or created):
            self.ctx.message("Aucun objet ne se touche par ses extrémités : rien à joindre.", error=True)
            self.finish()
            return
        self.ctx.apply_edit(changes, created, "Joindre", deleted)
        self.ctx.message(f"Joindre : {joined_count} objet(s) en {len(changes) + len(created)}.")
        self.finish()


# ==========================================================================
# RESEAU (AR) : rectangulaire, polaire, le long d'un chemin (copies, non associatif)
# ==========================================================================

ARRAY_TYPES = [("rect", "Rectangulaire", ("R", "RECT", "RECTANGULAIRE")),
               ("polar", "Polaire", ("PO", "POLAIRE", "POLAR")),
               ("path", "cHemin", ("H", "CHEMIN", "PA", "PATH"))]


class ArrayCommand(_SelectingCommand):
    """RESEAU (AR) : les objets, puis le type. RECTANGULAIRE : colonnes, rangees, distance entre colonnes, entre
    rangees (valeur, ou point : la distance au point de base des objets ; negatif = vers la gauche / le bas).
    POLAIRE : centre, nombre d'elements (original compris), angle a remplir (360 = tout le tour), objets tournes ou
    non. CHEMIN : l'objet chemin, nombre d'elements (repartis de bout en bout), alignes sur le chemin ou non. Les
    copies sont des objets ordinaires (pas de reseau associatif) ; une etape d'annulation. Valeurs retenues pour la
    session."""

    NAME = "ARRAY"
    LABEL = "Réseau"
    IMMEDIATE_PICK = False

    def after_selection(self):
        self.ctx.highlight(self.items)
        memory = self.ctx.tool_memory
        self.kind = None
        self.stage = "type"
        self.values = dict(memory.get("array", {}))
        self.center = None
        self.path = None
        x0, y0, x1, y1 = _bounds(self.items)
        self.size = (max(x1 - x0, geo.EPS), max(y1 - y0, geo.EPS))
        self.origin = (x0, y0)

    def _value(self, key, default):
        return self.values.get(key, default)

    STEPS = {"rect": ("columns", "rows", "dx", "dy"), "polar": ("center", "count", "fill", "rotate"),
             "path": ("path", "count", "align")}

    def step_prompt(self):
        unit = self.ctx.unit()
        if self.stage == "type":
            return Prompt("Entrez le type de réseau", list(ARRAY_TYPES), "select", None,
                          dict((k, l) for k, l, _w in ARRAY_TYPES)[self._value("type", "rect")])
        if self.stage == "columns":
            return Prompt("Entrez le nombre de colonnes", [], "point", None, str(self._value("columns", 4)),
                          value="count")
        if self.stage == "rows":
            return Prompt("Entrez le nombre de rangées", [], "point", None, str(self._value("rows", 3)),
                          value="count")
        if self.stage == "dx":
            default = self._value("dx", self.size[0] * 1.5)
            return Prompt("Spécifiez la distance entre les colonnes", [], "point", self.origin,
                          self.ctx.fmt(default), value="length")
        if self.stage == "dy":
            default = self._value("dy", self.size[1] * 1.5)
            return Prompt("Spécifiez la distance entre les rangées", [], "point", self.origin,
                          self.ctx.fmt(default), value="length")
        if self.stage == "center":
            return Prompt("Spécifiez le centre du réseau", [], "point")
        if self.stage == "count":
            return Prompt("Entrez le nombre d'éléments", [], "point", None,
                          str(self._value("count", 6 if self.kind == "polar" else 5)), value="count")
        if self.stage == "fill":
            return Prompt("Spécifiez l'angle à remplir (+ = trigonométrique)", [], "point", self.center,
                          f"{self._value('fill', 360.0):g}", value="angle")
        if self.stage == "rotate":
            return Prompt("Faire pivoter les éléments ?", [("yes", "Oui", ("O", "OUI", "Y", "YES")),
                                                            ("no", "Non", ("N", "NON", "NO"))], "select", None,
                          "Oui" if self._value("rotate", True) else "Non")
        if self.stage == "path":
            return Prompt("Choisissez la courbe de chemin", [], "select")
        if self.stage == "align":
            return Prompt("Aligner les éléments sur le chemin ?", [("yes", "Oui", ("O", "OUI", "Y", "YES")),
                                                                    ("no", "Non", ("N", "NON", "NO"))], "select", None,
                          "Oui" if self._value("align", True) else "Non")
        del unit
        return Prompt("")

    def _next(self):
        steps = self.STEPS[self.kind]
        index = steps.index(self.stage)
        if index + 1 < len(steps):
            self.stage = steps[index + 1]
            if self.stage == "path":
                self.ctx.begin_object_selection()
        else:
            self._make()

    def keyword(self, key):
        if self.stage == "type" and key in self.STEPS:
            self._type(key)
        elif self.stage in ("rotate", "align") and key in ("yes", "no"):
            self.values[self.stage] = key == "yes"
            self._next()

    def _type(self, kind):
        self.kind = kind
        self.values["type"] = kind
        self.stage = self.STEPS[kind][0]
        if self.stage == "path":
            self.ctx.begin_object_selection()

    def enter(self):
        defaults = {"columns": 4, "rows": 3, "dx": self.size[0] * 1.5, "dy": self.size[1] * 1.5,
                    "count": 6 if self.kind == "polar" else 5, "fill": 360.0, "rotate": True, "align": True}
        if self.items is None:
            return super().enter()
        if self.stage == "type":
            self._type(self._value("type", "rect"))
        elif self.stage in defaults:
            self.values.setdefault(self.stage, defaults[self.stage])
            self._next()
        else:
            self.finish()

    def value(self, number):
        if self.stage in ("columns", "rows", "count"):
            count = int(round(number))
            if count < 1 or count > 100000:
                self.ctx.message("Nombre de 1 à 100000.", error=True)
                return
            self.values[self.stage] = count
        elif self.stage in ("dx", "dy"):
            self.values[self.stage] = number
        elif self.stage == "fill":
            if abs(number) <= geo.EPS or abs(number) > 360.0:
                self.ctx.message("Angle à remplir de -360 à 360° (non nul).", error=True)
                return
            self.values["fill"] = number
        else:
            self.ctx.message("Une valeur n'est pas attendue ici.", error=True)
            return
        self._next()

    def point(self, p):
        if self.items is None:
            return
        p = (float(p[0]), float(p[1]))
        if self.stage == "dx":
            self.value(p[0] - self.origin[0])
        elif self.stage == "dy":
            self.value(p[1] - self.origin[1])
        elif self.stage == "center":
            self.center = p
            self._next()
        elif self.stage == "fill":
            self.value(geo.angle_deg(self.center, p) or 360.0)

    def selection_done(self, items):
        if self.items is None:
            return super().selection_done(items)
        if self.stage != "path":
            self.enter()                                    # Entree a une invite d'options : la valeur proposee
            return
        if self.stage == "path":
            found = [i for i in items if i.kind in TRIMMABLE and i not in self.items]
            if not found:
                self.ctx.message("Une ligne, un arc, un cercle ou une polyligne est attendu.", error=True)
                return
            self.path = found[0]
            self._next()

    def _transforms(self) -> list:
        """[(fonction point, fonction angle, rotation en degres)] de chaque copie."""
        v = self.values
        out = []
        if self.kind == "rect":
            for dx, dy in cad_draw.rect_offsets(v.get("columns", 4), v.get("rows", 3), v.get("dx", 0.0),
                                                v.get("dy", 0.0)):
                out.append(("move", (dx, dy)))
        elif self.kind == "polar":
            for angle in cad_draw.polar_steps(v.get("count", 6), v.get("fill", 360.0)):
                out.append(("polar", angle))
        elif self.kind == "path" and self.path is not None:
            primitives = self.path.prims()
            stations = cad_draw.path_stations(primitives, v.get("count", 5))
            if stations:
                start, a0 = stations[0]
                base = _bounds_center(self.items)
                for point, angle in stations[1:]:
                    out.append(("path", (base, start, a0, point, angle)))
        return out

    def _geometry(self, item, transform) -> dict:
        kind, arg = transform
        data = item.to_dict()
        if kind == "move":
            return cad_shapes.translated(item.kind, data, arg)
        if kind == "polar":
            if self.values.get("rotate", True):
                return cad_shapes.rotated(item.kind, data, self.center, arg)
            ref = _bounds_center([item])
            moved = cad_shapes.rotated_point(ref, self.center, arg)
            return cad_shapes.translated(item.kind, data, geo.sub(moved, ref))
        base, start, a0, point, angle = arg
        delta = geo.sub(point, start)
        if self.values.get("align", True):
            turned = cad_shapes.rotated(item.kind, data, start, angle - a0)
            merged = dict(data)
            merged.update(turned)
            return cad_shapes.translated(item.kind, merged, delta)
        return cad_shapes.translated(item.kind, data, delta)

    def _make(self):
        self.ctx.tool_memory["array"] = dict(self.values)
        pairs = [(item, self._geometry(item, t)) for t in self._transforms() for item in self.items]
        if not pairs:
            self.ctx.message("Réseau sans copie.", error=True)
            self.finish()
            return
        made = self.ctx.create_copies(pairs)
        self.ctx.commit_created(made, "Réseau")
        self.ctx.message(f"Réseau : {len(made)} copie(s).")
        self.finish()

    def finish(self):
        if not self.finished:
            self.ctx.highlight([])
        super().finish()

    def ghosts(self, p):
        if self.items is None or self.kind is None or self.stage in ("type", "path"):
            return []
        saved = dict(self.values)
        try:
            if self.stage == "dx":
                self.values["dx"] = p[0] - self.origin[0]
            elif self.stage == "dy":
                self.values["dy"] = p[1] - self.origin[1]
            elif self.stage == "fill" and self.center is not None:
                self.values["fill"] = geo.angle_deg(self.center, p) or 360.0
            elif self.stage == "center":
                self.center = p
            transforms = self._transforms()[:400]                # apercu borne (fluidite)
            out = []
            for t in transforms:
                out += _transform_ghosts(self.ctx, self.items, lambda item, t=t: self._geometry(item, t))
            return out
        finally:
            self.values = saved


def _bounds(items) -> tuple:
    boxes = [item.doc_bounds() if item.CURVED else _line_bounds(item) for item in items]
    return (min(b[0] for b in boxes), min(b[1] for b in boxes), max(b[2] for b in boxes), max(b[3] for b in boxes))


def _line_bounds(item) -> tuple:
    a, b = item.points()
    return min(a[0], b[0]), min(a[1], b[1]), max(a[0], b[0]), max(a[1], b[1])


def _bounds_center(items):
    x0, y0, x1, y1 = _bounds(items)
    return ((x0 + x1) / 2.0, (y0 + y1) / 2.0)


# ==========================================================================
# Registre
# ==========================================================================

COMMANDS = {"ELLIPSE": EllipseCommand, "POLYGON": PolygonCommand, "EXTEND": ExtendCommand,
            "STRETCH": StretchCommand, "BREAK": BreakCommand, "JOIN": JoinCommand, "ARRAY": ArrayCommand}
NEW_ENTRIES = (("POINT", "Point", ("PO", "POINT"), PointCommand),
               ("DIVIDE", "Diviser", ("DIV", "DIVISER"), DivideCommand),
               ("MEASURE", "Mesurer", ("ME", "MESURER"), MeasureCommand),
               ("BREAKATPOINT", "Coupure au point", ("BREAKATPOINT", "COUPUREPOINT"), BreakAtPointCommand))


def register(registry, entry_class, by_word):
    """Branche ces commandes dans le registre de `cad_commands` (les « prevues » deviennent disponibles)."""
    for entry in registry:
        if entry.name in COMMANDS:
            entry.factory = COMMANDS[entry.name]
            entry.planned = ""
    for name, label, aliases, factory in NEW_ENTRIES:
        if any(e.name == name for e in registry):
            continue                                    # deja inscrite
        entry = entry_class(name, label, aliases, factory)
        registry.append(entry)
        for word in (name, *aliases):
            by_word.setdefault(word.upper(), entry)



def _self_register():
    """Importe AVANT `cad_commands` : `cad_commands` n'a pas pu l'inscrire (fichier encore incomplet), il le fait ici."""
    from . import cad_commands as _cc
    if hasattr(_cc, "_BY_WORD"):
        register(_cc.REGISTRY, _cc.Entry, _cc._BY_WORD)


_self_register()
