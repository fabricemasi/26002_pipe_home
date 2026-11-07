"""Module CAD du board : ALIGNER (ALIGN), SUPPRIMER LES DOUBLONS (OVERKILL) et SPLINE (meme protocole que
`cad_commands`) ; inscrites dans le REGISTRE a l'import (`register`)."""
from __future__ import annotations

import math

from . import cad_shapes
from . import cad_geometry as geo
from .cad_commands import Command, Prompt, _SelectingCommand, _show, _transform_ghosts


# ==========================================================================
# ALIGNER (AL)
# ==========================================================================

def align_transform(s1, d1, s2=None, d2=None, scale: bool = False):
    """(fonction point, angle en degres, facteur) qui amene s1 sur d1 et, s'ils sont donnes, la direction s1 -> s2 sur
    d1 -> d2 (avec mise a l'echelle de |s1 s2| a |d1 d2| si `scale`)."""
    angle, factor = 0.0, 1.0
    if s2 is not None and d2 is not None and geo.distance(s1, s2) > geo.EPS and geo.distance(d1, d2) > geo.EPS:
        angle = geo.angle_deg(d1, d2) - geo.angle_deg(s1, s2)
        if scale:
            factor = geo.distance(d1, d2) / geo.distance(s1, s2)

    def point_fn(p):
        q = cad_shapes.rotated_point(p, s1, angle)
        q = cad_shapes.scaled_point(q, s1, factor)
        return (q[0] - s1[0] + d1[0], q[1] - s1[1] + d1[1])
    return point_fn, angle, factor


def aligned(kind: str, data: dict, s1, d1, angle: float, factor: float) -> dict:
    out = dict(data)
    out.update(cad_shapes.rotated(kind, out, s1, angle))
    if abs(factor - 1.0) > 1e-12:
        out.update(cad_shapes.scaled(kind, out, s1, factor))
    moved = cad_shapes.translated(kind, out, geo.sub(d1, s1))
    return moved


class AlignCommand(_SelectingCommand):
    """ALIGNER (AL) : les objets, 1er point source puis 1er point de destination, 2e point source / destination
    (Entree apres une seule paire = simple deplacement), puis « Mettre les objets a l'echelle d'apres les points
    d'alignement ? » (Non par defaut)."""

    NAME = "ALIGN"
    LABEL = "Aligner"

    def after_selection(self):
        self.points = []                    # s1, d1, s2, d2
        self.asking_scale = False
        self.ctx.highlight(self.items)

    def step_prompt(self):
        if self.asking_scale:
            return Prompt("Mettre les objets à l'échelle d'après les points d'alignement",
                          [("yes", "Oui", ("O", "OUI", "Y")), ("no", "Non", ("N", "NON"))], "point", None, "Non")
        labels = ["Spécifiez le premier point source", "Spécifiez le premier point de destination",
                  "Spécifiez le deuxième point source", "Spécifiez le deuxième point de destination"]
        base = self.points[-1] if len(self.points) in (1, 3) else None
        default = "continuer" if len(self.points) == 2 else ""
        return Prompt(labels[len(self.points)], [], "point", base, default)

    def point(self, p):
        if self.items is None or self.asking_scale:
            return
        self.points.append((float(p[0]), float(p[1])))
        if len(self.points) == 4:
            self.asking_scale = True

    def keyword(self, key):
        if self.asking_scale:
            self._apply(key == "yes")

    def enter(self):
        if self.items is None:
            return
        if self.asking_scale:
            self._apply(False)
        elif len(self.points) >= 2:
            self._apply(False)
        else:
            self.finish()

    def _pairs(self):
        s1, d1 = self.points[0], self.points[1]
        s2, d2 = (self.points[2], self.points[3]) if len(self.points) >= 4 else (None, None)
        return s1, d1, s2, d2

    def _apply(self, scale: bool):
        s1, d1, s2, d2 = self._pairs()
        _fn, angle, factor = align_transform(s1, d1, s2, d2, scale)
        self.ctx.apply_edit([(item, aligned(item.kind, item.to_dict(), s1, d1, angle, factor)) for item in self.items],
                            [], "Aligner")
        self.finish()

    def finish(self):
        if not self.finished:
            self.ctx.highlight([])
        super().finish()

    def ghosts(self, p):
        if self.items is None or len(self.points) not in (1, 3):
            return []
        pts = self.points + [(float(p[0]), float(p[1]))]
        s1, d1 = pts[0], pts[1]
        s2, d2 = (pts[2], pts[3]) if len(pts) == 4 else (None, None)
        _fn, angle, factor = align_transform(s1, d1, s2, d2, False)
        return _transform_ghosts(self.ctx, self.items,
                                 lambda item: aligned(item.kind, item.to_dict(), s1, d1, angle, factor))

    def preview(self, p):
        if self.items is None or len(self.points) not in (1, 3):
            return []
        return [("rubber", self.points[-1], p)]


# ==========================================================================
# SUPPRIMER LES DOUBLONS (OVERKILL)
# ==========================================================================

def _signature(kind: str, data: dict, tol: float):
    """Cle d'egalite d'une entite (geometrie arrondie a `tol`, sens ignore pour une ligne) ; None = jamais doublon."""
    def r(v):
        return round(float(v) / tol)
    if kind == "cad_line":
        a, b = (r(data["p1"][0]), r(data["p1"][1])), (r(data["p2"][0]), r(data["p2"][1]))
        return (kind,) + tuple(sorted((a, b)))
    if kind in ("cad_circle", "cad_arc"):
        out = (kind, r(data["center"][0]), r(data["center"][1]), r(data["radius"]))
        if kind == "cad_arc":
            out += (round(float(data["start"]) % 360.0, 4), round(float(data["end"]) % 360.0, 4))
        return out
    if kind == "cad_pline":
        verts = tuple((r(v[0]), r(v[1]), round(float(v[2]) if len(v) > 2 else 0.0, 6)) for v in data["vertices"])
        return (kind, bool(data.get("closed")), verts)
    if kind == "cad_point":
        return (kind, r(data["pos"][0]), r(data["pos"][1]))
    return None


def overkill(entries, tol: float):
    """[(cle, type, donnees)] -> (cles a supprimer, [(cle gardee, nouvelle geometrie)]) : doublons exacts retires
    (memes proprietes ignorees, comme OVERKILL par defaut), lignes COLINEAIRES qui se chevauchent ou se touchent
    fondues en une seule."""
    seen, gone = {}, []
    lines = []
    for key, kind, data in entries:
        sig = _signature(kind, data, tol)
        if sig is not None and sig in seen:
            gone.append(key)
            continue
        if sig is not None:
            seen[sig] = key
        if kind == "cad_line":
            lines.append((key, data))
    # lignes colineaires : regroupees par droite (direction normalisee + distance a l'origine)
    groups = {}
    for key, data in lines:
        if key in gone:
            continue
        a, b = tuple(map(float, data["p1"])), tuple(map(float, data["p2"]))
        d = geo.sub(b, a)
        n = math.hypot(*d)
        if n <= tol:
            continue
        ux, uy = d[0] / n, d[1] / n
        if ux < -1e-12 or (abs(ux) <= 1e-12 and uy < 0):
            ux, uy = -ux, -uy
        offset = -a[0] * uy + a[1] * ux
        groups.setdefault((round(ux / 1e-9), round(uy / 1e-9), round(offset / tol)), []).append(
            (key, a, b, ux, uy))
    changed = []
    for members in groups.values():
        if len(members) < 2:
            continue
        ux, uy = members[0][3], members[0][4]
        spans = sorted(((min(a[0] * ux + a[1] * uy, b[0] * ux + b[1] * uy),
                         max(a[0] * ux + a[1] * uy, b[0] * ux + b[1] * uy), key, a) for key, a, b, _x, _y in members))
        current = list(spans[0])
        merged = [current]
        for lo, hi, key, a in spans[1:]:
            if lo <= current[1] + tol:
                current[1] = max(current[1], hi)
                gone.append(key)
            else:
                current = [lo, hi, key, a]
                merged.append(current)
        for lo, hi, key, a in merged:
            t0 = a[0] * ux + a[1] * uy
            p = (a[0] + (lo - t0) * ux, a[1] + (lo - t0) * uy)
            q = (a[0] + (hi - t0) * ux, a[1] + (hi - t0) * uy)
            changed.append((key, {"p1": [p[0], p[1]], "p2": [q[0], q[1]]}))
    return gone, changed


class OverkillCommand(_SelectingCommand):
    """SUPPRIMER LES DOUBLONS (OVERKILL / -OVERKILL) : dans les objets choisis (TOUT : le dessin), les doublons
    (meme geometrie a 1e-6 unite pres) sont effaces et les lignes colineaires qui se chevauchent ou se touchent sont
    fondues. Une etape d'annulation ; compte rendu dans l'historique."""

    NAME = "OVERKILL"
    LABEL = "Supprimer les doublons"

    def after_selection(self):
        tol = 1e-6 * max(1.0, self.ctx.unit())
        entries = [(item.item_id, item.kind, item.to_dict()) for item in self.items]
        gone_ids, changed = overkill(entries, tol)
        by_id = {item.item_id: item for item in self.items}
        gone = [by_id[i] for i in dict.fromkeys(gone_ids)]
        changes = [(by_id[k], g) for k, g in changed if k not in gone_ids
                   and (by_id[k].data.get("p1"), by_id[k].data.get("p2")) != (g["p1"], g["p2"])]
        if not gone and not changes:
            self.ctx.message("Aucun doublon.")
        else:
            self.ctx.apply_edit(changes, [], "Supprimer les doublons", gone)
            self.ctx.message(f"{len(gone)} doublon(s) supprimé(s), {len(changes)} ligne(s) fondue(s).")
        self.finish()


# ==========================================================================
# SPLINE (SPL)
# ==========================================================================

SPLINE_STEPS = 8                    # arcs par intervalle entre deux points d'ajustement


def spline_points(points, closed: bool = False, steps: int = SPLINE_STEPS) -> list:
    """Points de la courbe de Catmull-Rom CENTRIPETE qui passe par `points` (lisse, sans boucle parasite)."""
    pts = [tuple(p) for p in points]
    if len(pts) < 2:
        return pts
    if closed:
        ext = [pts[-1]] + pts + [pts[0], pts[1]]
        spans = len(pts)
    else:
        ext = [geo.sub(geo.mul(pts[0], 2.0), pts[1])] + pts + [geo.sub(geo.mul(pts[-1], 2.0), pts[-2])]
        spans = len(pts) - 1
    out = [pts[0]]
    for i in range(spans):
        p0, p1, p2, p3 = ext[i], ext[i + 1], ext[i + 2], ext[i + 3]

        def knot(t, a, b):
            return t + max(geo.distance(a, b), 1e-12) ** 0.5
        t0 = 0.0
        t1 = knot(t0, p0, p1)
        t2 = knot(t1, p1, p2)
        t3 = knot(t2, p2, p3)
        for k in range(1, steps * 2 + 1):
            t = t1 + (t2 - t1) * k / (steps * 2)
            a1 = _lerp_t(p0, p1, t0, t1, t)
            a2 = _lerp_t(p1, p2, t1, t2, t)
            a3 = _lerp_t(p2, p3, t2, t3, t)
            b1 = _lerp_t(a1, a2, t0, t2, t)
            b2 = _lerp_t(a2, a3, t1, t3, t)
            out.append(_lerp_t(b1, b2, t1, t2, t))
    return out


def _lerp_t(a, b, ta, tb, t):
    if abs(tb - ta) <= 1e-15:
        return a
    w = (t - ta) / (tb - ta)
    return (a[0] + (b[0] - a[0]) * w, a[1] + (b[1] - a[1]) * w)


def spline_vertices(points, closed: bool = False) -> list:
    """Polyligne d'ARCS (chaque arc par 3 points de la courbe) qui suit la spline."""
    curve = spline_points(points, closed)
    vertices = []
    for i in range(0, len(curve) - 2, 2):
        a, m, b = curve[i], curve[i + 1], curve[i + 2]
        found = cad_shapes.arc_from_3_points(a, m, b)
        vertices.append([a[0], a[1], 0.0 if found is None else cad_shapes.arc_bulge(found[3])])
    if not closed:
        vertices.append([curve[-1][0], curve[-1][1], 0.0])
    return vertices


class SplineCommand(Command):
    """SPLINE (SPL) : points d'ajustement (la courbe passe par chacun), Entree termine ; option Clore (courbe
    fermee). Resultat : une polyligne d'arcs lisse (comme une spline convertie par AutoCAD), donc accrochages,
    AJUSTER, DECALER, export… ; annUler retire le dernier point."""

    NAME = "SPLINE"
    LABEL = "Spline"

    def start(self):
        self.points = []

    def prompt(self):
        if not self.points:
            return Prompt("Spécifiez le premier point", [], "point")
        options = [("undo", "annUler", ("U", "ANNULER", "UNDO"))]
        if len(self.points) >= 3:
            options.insert(0, ("close", "Clore", ("C", "CLORE", "CLOSE")))
        return Prompt("Entrez le point suivant", options, "point", self.points[-1],
                      "terminer" if len(self.points) >= 2 else "")

    def point(self, p):
        p = (float(p[0]), float(p[1]))
        if self.points and geo.distance(self.points[-1], p) <= geo.EPS:
            return
        self.points.append(p)

    def keyword(self, key):
        if key == "undo" and self.points:
            self.points.pop()
        elif key == "close" and len(self.points) >= 3:
            self._make(True)

    def enter(self):
        if len(self.points) >= 2:
            self._make(False)
        else:
            self.finish()

    def _make(self, closed: bool):
        item = self.ctx.create_entity("cad_pline", {"vertices": spline_vertices(self.points, closed),
                                                    "closed": closed})
        self.ctx.commit_created([item], "Spline")
        self.finish()

    def preview(self, p):
        if not self.points:
            return []
        pts = self.points + [(float(p[0]), float(p[1]))]
        if geo.distance(pts[-1], pts[-2]) <= geo.EPS:
            pts.pop()
        if len(pts) < 2:
            return []
        return _show(self.ctx, "cad_pline", {"vertices": spline_vertices(pts), "closed": False})


NEW_ENTRIES = (
    ("ALIGN", "Aligner", ("AL", "ALIGNER"), AlignCommand),
    ("OVERKILL", "Supprimer les doublons", ("OVERKILL", "-OVERKILL", "DOUBLONS", "SUPPRDOUBLONS"), OverkillCommand),
    ("SPLINE", "Spline", ("SPL", "SPLINE"), SplineCommand),
)


def register(registry, entry_class, by_word):
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
