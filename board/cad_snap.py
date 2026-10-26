"""Module CAD du board : moteur d'ACCROCHAGE centralise (aucun Qt) — accrochages aux objets (OSNAP),
ORTHO, suivi POLAIRE, suivi d'accrochage (OTRACK), grille. Tous les outils CAD passent par lui pour obtenir LE
point qui sera valide : la previsualisation montre exactement ce point.

Ordre de resolution d'un point (comme AutoCAD) :
1. valeurs imposees par la saisie (angle `<a`, distance ou angle verrouilles par la saisie dynamique) ;
2. accrochage aux objets (permanent si OSNAP est actif, ou ponctuel pour le point suivant : `END`, menu
   Maj + clic droit…) — il l'emporte sur ORTHO et le suivi polaire ;
3. suivi : intersections de lignes de suivi (polaires depuis le point de base, lignes passant par les points
   ACQUIS), puis la ligne de suivi la plus proche ;
4. ORTHO (axes du document depuis le point de base) — exclusif du suivi polaire ;
5. accrochage a la grille (F9) ;
6. le curseur.

Tous les calculs sont faits dans les coordonnees du DOCUMENT ; la distance de detection (`aperture_px`) est
en pixels d'ECRAN, convertie avec l'echelle de la vue (pixels par unite) : meme effet a tout zoom.

Geometrie des entites : chacune rend des PRIMITIVES (`snap_primitives`, voir cad_shapes) : `("segment", a, b)`
(ligne, segment droit de polyligne) et `("arc", c, r, a0, ouverture)` (arc, cercle, segment courbe de polyligne) :
Extremite, Milieu, Centre, Quadrant, Proche, Perpendiculaire, Tangente (depuis le point de base) et Intersection
(segments et arcs entre eux). Nodal, Insertion, Centre geometrique sont declares mais ne rendent RIEN tant qu'aucune
entite ne les porte : jamais de faux accrochage.

Recherche localisee : `source(rect)` rend les entites visibles dont l'emprise touche le rectangle (index BSP
de la scene, voir cad.py) ; rien n'est parcouru en entier a chaque mouvement de souris. Limite connue :
l'intersection apparente ne considere que les entites proches du curseur (4 fois la distance de detection) et
les entites ACQUISES (voir `note_hover`)."""
from __future__ import annotations

import time
from dataclasses import dataclass, field

import math

from . import cad_geometry as geo
from . import cad_shapes

MODES = ("end", "mid", "cen", "gcen", "qua", "int", "appint", "ext", "per", "tan", "nea", "par", "node", "ins")
LABELS = {"end": "Extrémité", "mid": "Milieu", "cen": "Centre", "gcen": "Centre géométrique",
          "qua": "Quadrant", "int": "Intersection", "appint": "Intersection apparente", "ext": "Extension",
          "per": "Perpendiculaire", "tan": "Tangente", "nea": "Proche", "par": "Parallèle", "node": "Nodal",
          "ins": "Insertion", "extint": "Intersection de prolongement", "none": "Aucun"}
ENGLISH = {"end": "Endpoint", "mid": "Midpoint", "cen": "Center", "gcen": "Geometric Center", "qua": "Quadrant",
           "int": "Intersection", "appint": "Apparent Intersection", "ext": "Extension", "per": "Perpendicular",
           "tan": "Tangent", "nea": "Nearest", "par": "Parallel", "node": "Node", "ins": "Insertion"}
# Priorite : les accrochages a un POINT caracteristique passent avant ceux qui glissent le long d'un objet.
PRIORITY = {"end": 0, "mid": 0, "cen": 0, "gcen": 0, "qua": 0, "int": 0, "extint": 0, "appint": 0, "node": 0,
            "ins": 0, "per": 1, "tan": 1, "par": 1, "ext": 1, "nea": 2}
DEFAULT_MODES = {"end", "mid", "int", "ext", "cen"}
ACQUIRE_S = 0.35                    # pause sur un point pour l'acquerir (suivi, extension)
MAX_ACQUIRED = 7                    # comme AutoCAD
POLAR_ANGLES = (15.0, 30.0, 45.0, 90.0)


@dataclass
class SnapSettings:
    osnap: bool = True
    modes: set = field(default_factory=lambda: set(DEFAULT_MODES))
    aperture_px: float = 10.0
    ortho: bool = False
    polar: bool = False
    polar_angle: float = 45.0
    otrack: bool = False
    track_polar: bool = True        # suivi d'accrochage selon les angles polaires (sinon orthogonal)
    grid_snap: bool = False
    grid_spacing: float = 10.0      # pas de la grille du board affichee (pose par le controleur a chaque recherche)
    grid_origin: tuple = (0.0, 0.0)  # origine de la grille (document)

    @classmethod
    def from_settings(cls, values: dict) -> "SnapSettings":
        """Reglages de l'appli (cles `board_cad_*`, Reglages > Module CAD)."""
        g = values.get
        modes = {m for m in MODES if bool(g(f"board_cad_osnap_{m}", m in DEFAULT_MODES))}
        increment = str(g("board_cad_polar_increment", "45"))
        try:
            angle = float(g("board_cad_polar_custom", 45)) if increment == "custom" else float(increment)
        except (TypeError, ValueError):
            angle = 45.0
        return cls(osnap=bool(g("board_cad_osnap", True)), modes=modes,
                   aperture_px=max(2.0, float(g("board_cad_aperture", 10) or 10)),
                   ortho=bool(g("board_cad_ortho", False)), polar=bool(g("board_cad_polar", False)),
                   polar_angle=max(0.5, min(180.0, angle)), otrack=bool(g("board_cad_otrack", False)),
                   track_polar=bool(g("board_cad_track_polar", True)),
                   grid_snap=bool(g("board_cad_grid_snap", False)))


@dataclass
class Candidate:
    mode: str
    point: tuple
    distance_px: float
    entity: object = None
    segment: tuple | None = None
    guides: list = field(default_factory=list)     # [(sorte, a, b)] en coordonnees du document

    @property
    def priority(self) -> int:
        return PRIORITY.get(self.mode, 3)

    @property
    def label(self) -> str:
        return LABELS.get(self.mode, self.mode)


@dataclass
class Resolution:
    point: tuple                    # LE point valide par un clic (document)
    kind: str = "free"              # free | osnap | polar | ortho | track | grid | locked
    candidate: Candidate | None = None
    candidates: list = field(default_factory=list)
    guides: list = field(default_factory=list)
    label: str = ""
    angle: float | None = None      # direction acquise (polaire / suivi), degres


@dataclass
class Acquired:
    point: tuple
    mode: str
    segment: tuple | None = None    # segment porteur (extension depuis une extremite)
    entity: object = None


class SnapEngine:
    """Etat du suivi (points acquis) + resolution des points. `source(rect)` : entites dont l'emprise touche
    `rect` = (xmin, ymin, xmax, ymax) en coordonnees du document ; chaque entite a `snap_primitives()`."""

    def __init__(self, source=None):
        self.source = source or (lambda rect: [])
        self.settings = SnapSettings()
        self.acquired: list[Acquired] = []
        self.parallel: list[tuple] = []             # segments acquis pour l'accrochage Parallele
        self._hover = None                          # (cle, depuis) du candidat sous le curseur

    # -- suivi : acquisition par une pause --
    def reset_tracking(self):
        self.acquired.clear()
        self.parallel.clear()
        self._hover = None

    def note_hover(self, candidate: Candidate | None, now: float | None = None) -> bool:
        """Le curseur reste sur `candidate` : apres ACQUIRE_S, son point est ACQUIS (suivi, extension) — ou
        relache s'il l'etait deja (comme AutoCAD). Un segment survole en mode Parallele est acquis aussi.
        Rend True si l'ensemble acquis a change (a redessiner)."""
        now = time.monotonic() if now is None else now
        if candidate is None:
            self._hover = None
            return False
        key = (candidate.mode, round(candidate.point[0], 9), round(candidate.point[1], 9))
        if self._hover is None or self._hover[0] != key:
            self._hover = (key, now, False)
            return False
        _key, since, done = self._hover
        if done or now - since < ACQUIRE_S:
            return False
        self._hover = (key, since, True)
        s = self.settings
        if candidate.mode in ("nea", "per", "par") and candidate.segment is not None and "par" in s.modes:
            seg = candidate.segment
            for i, other in enumerate(self.parallel):
                if other == seg:
                    del self.parallel[i]
                    return True
            self.parallel = (self.parallel + [seg])[-3:]
            return True
        if candidate.priority != 0 or not (s.otrack or "ext" in s.modes):
            return False
        for i, item in enumerate(self.acquired):
            if geo.distance(item.point, candidate.point) <= geo.EPS * 10:
                del self.acquired[i]
                return True
        self.acquired = (self.acquired + [Acquired(candidate.point, candidate.mode, candidate.segment,
                                                   candidate.entity)])[-MAX_ACQUIRED:]
        return True

    # -- resolution --
    def resolve(self, cursor, scale: float, base=None, override: str | None = None, cycle: int = 0,
                lock_angle: float | None = None, lock_distance: float | None = None) -> Resolution:
        """Point valide pour la position `cursor` (document). `scale` = pixels d'ecran par unite ; `base` =
        point de reference de l'invite (dernier point) ; `override` = accrochage ponctuel (« none » = aucun) ;
        `cycle` = rang du candidat choisi par Tab."""
        s = self.settings
        scale = max(scale, 1e-12)
        aperture = s.aperture_px / scale
        if base is not None and (lock_angle is not None or lock_distance is not None):
            angle = lock_angle if lock_angle is not None else geo.angle_deg(base, cursor)
            if lock_distance is not None:
                dist = lock_distance
            else:
                dist = geo.dot(geo.sub(cursor, base), geo.direction(angle))
            point = geo.polar(base, dist, angle)
            return Resolution(point, "locked", guides=[("polar", base, point)], angle=angle)
        use_osnap = override != "none" and (s.osnap or override is not None)
        if use_osnap:
            modes = {override} if override not in (None, "none") else s.modes
            candidates = self.candidates(cursor, scale, base, modes)
            if candidates:
                chosen = candidates[cycle % len(candidates)]
                return Resolution(chosen.point, "osnap", chosen, candidates, list(chosen.guides), chosen.label)
        if override is not None and override != "none":
            return Resolution(tuple(cursor), "free", label=f"{LABELS.get(override, override)} : aucun objet")
        tracked = self._tracking(cursor, aperture, base)
        if tracked is not None:
            return tracked
        point = tuple(cursor)
        kind = "free"
        if s.grid_snap:
            point = geo.snap_to_grid(point, s.grid_spacing, s.grid_origin)
            kind = "grid"
        if s.ortho and base is not None:
            d = geo.sub(point, base)
            point = (point[0], base[1]) if abs(d[0]) >= abs(d[1]) else (base[0], point[1])
            return Resolution(point, "ortho", guides=[("ortho", base, point)],
                              angle=geo.angle_deg(base, point) if geo.distance(base, point) > geo.EPS else None)
        return Resolution(point, kind)

    # -- accrochages aux objets --
    def _near(self, cursor, radius):
        rect = (cursor[0] - radius, cursor[1] - radius, cursor[0] + radius, cursor[1] + radius)
        out = []
        for entity in self.source(rect):
            for prim in entity.snap_primitives():
                out.append((entity, prim))
        return out

    def candidates(self, cursor, scale: float, base=None, modes=None) -> list[Candidate]:
        """Tous les candidats d'accrochage a portee du curseur, tries (priorite, distance a l'ecran)."""
        modes = self.settings.modes if modes is None else modes
        aperture = self.settings.aperture_px / scale
        near = self._near(cursor, aperture)
        found: list[Candidate] = []

        def add(mode, point, entity=None, segment=None, guides=None, dist_px=None):
            d = geo.distance(cursor, point) * scale if dist_px is None else dist_px
            if d <= self.settings.aperture_px + 1e-9 or dist_px is not None:
                found.append(Candidate(mode, (float(point[0]), float(point[1])), d, entity, segment,
                                       guides or []))

        segments = [(e, (p[1], p[2])) for e, p in near if p[0] == "segment"]
        for entity, (a, b) in segments:
            if "end" in modes:
                add("end", a, entity, (a, b))
                add("end", b, entity, (b, a))
            if "mid" in modes:
                add("mid", geo.midpoint(a, b), entity, (a, b))
            on_seg = geo.distance_point_segment(cursor, a, b) * scale
            if on_seg <= self.settings.aperture_px:
                if "nea" in modes:
                    q, _t = geo.project_segment(cursor, a, b)
                    add("nea", q, entity, (a, b))
                if "per" in modes and base is not None and geo.distance_point_line(base, a, b) > geo.EPS:
                    foot = geo.perpendicular_foot(base, a, b)
                    guides = [("per", base, foot)]
                    q, t = geo.project_segment(foot, a, b)
                    if not (0.0 <= geo.project_param(foot, a, b) <= 1.0):
                        guides.append(("ext", q, foot))       # pied sur le prolongement de l'objet
                    add("per", foot, entity, (a, b), guides, dist_px=on_seg)
        arcs = [(e, p) for e, p in near if p[0] == "arc"]
        for entity, arc in arcs:
            self._arc_candidates(cursor, scale, base, modes, entity, arc, add)
        if "int" in modes and arcs:
            prims = [(e, ("segment", a, b)) for e, (a, b) in segments] + arcs
            for i in range(len(prims)):
                ea, pa = prims[i]
                for j in range(i + 1, len(prims)):
                    eb, pb = prims[j]
                    if pa[0] == "segment" and pb[0] == "segment":
                        continue                            # deja vu ci-dessous
                    for point in cad_shapes.prim_intersections(pa, pb):
                        add("int", point, ea, None)
        if "int" in modes and len(segments) > 1:
            for i in range(len(segments)):
                ea, (a, b) = segments[i]
                for j in range(i + 1, len(segments)):
                    eb, (c, d) = segments[j]
                    point = geo.segment_intersection(a, b, c, d)
                    if point is not None:
                        add("int", point, ea, (a, b))
        if "ext" in modes:
            self._extension_candidates(cursor, scale, segments, add)
        if "appint" in modes:
            self._apparent_candidates(cursor, scale, add)
        if "par" in modes and base is not None:
            for seg in self.parallel:
                a, b = seg
                if geo.distance(a, b) <= geo.EPS:
                    continue
                d = geo.normalize(geo.sub(b, a))
                far = geo.add(base, d)
                off = geo.distance_point_line(cursor, base, far) * scale
                if off <= self.settings.aperture_px and geo.distance(base, cursor) * scale > self.settings.aperture_px:
                    q = geo.project_line(cursor, base, far)
                    add("par", q, None, seg, [("par", base, q), ("acquired", a, b)], dist_px=off)
        # Inutile de garder deux fois le meme point (extremite commune de deux lignes) : le premier suffit.
        found.sort(key=lambda c: (c.priority, c.distance_px))
        unique, seen = [], set()
        for cand in found:
            key = (cand.mode, round(cand.point[0], 9), round(cand.point[1], 9))
            if key not in seen:
                seen.add(key)
                unique.append(cand)
        return unique

    def _arc_candidates(self, cursor, scale, base, modes, entity, arc, add):
        """Accrochages d'un arc / cercle (centre c, rayon r) : extremites, milieu, centre, quadrants, proche,
        perpendiculaire et tangente depuis le point de base."""
        c, r, a0, sweep = arc[1], arc[2], arc[3], arc[4]
        full = abs(sweep) >= 360.0 - 1e-9
        aperture = self.settings.aperture_px
        near_q, on_px, _s = cad_shapes.closest_on_prim(arc, cursor)
        on_px *= scale
        if not full:
            if "end" in modes:
                add("end", cad_shapes.prim_start(arc), entity)
                add("end", cad_shapes.prim_end(arc), entity)
            if "mid" in modes:
                add("mid", cad_shapes.prim_mid(arc), entity)
        if "cen" in modes and (on_px <= aperture or geo.distance(cursor, c) * scale <= aperture):
            # Le centre se propose en survolant le trait (comme AutoCAD), classe par sa VRAIE distance : il ne passe
            # jamais devant un point caracteristique sous le curseur (Tab pour le choisir).
            add("cen", c, entity, dist_px=geo.distance(cursor, c) * scale)
        if "qua" in modes:
            for q in (0.0, 90.0, 180.0, 270.0):
                if cad_shapes.angle_in_arc(q, a0, sweep):
                    add("qua", cad_shapes.arc_point(c, r, q), entity)
        if on_px > aperture:
            return
        if "nea" in modes:
            add("nea", near_q, entity)
        if base is None or r <= geo.EPS:
            return
        d = geo.distance(base, c)
        if "per" in modes and d > geo.EPS:
            for k in (1.0, -1.0):                          # points de l'arc sur la droite base - centre
                q = geo.add(c, geo.mul(geo.sub(base, c), k * r / d))
                theta = geo.angle_deg(c, q)
                if cad_shapes.angle_in_arc(theta, a0, sweep) and geo.distance(q, cursor) * scale <= aperture * 2:
                    add("per", q, entity, None, [("per", base, q)], dist_px=geo.distance(q, cursor) * scale)
        if "tan" in modes and d > r + geo.EPS:
            half = math.degrees(math.acos(r / d))
            toward = geo.angle_deg(c, base)
            for theta in (toward + half, toward - half):
                q = cad_shapes.arc_point(c, r, theta)
                if cad_shapes.angle_in_arc(theta, a0, sweep) and geo.distance(q, cursor) * scale <= aperture * 2:
                    add("tan", q, entity, None, [("per", base, q)], dist_px=geo.distance(q, cursor) * scale)

    def _extension_candidates(self, cursor, scale, segments, add):
        rays = []
        for item in self.acquired:
            if item.mode != "end" or item.segment is None:
                continue
            end, other = item.segment
            if geo.distance(end, other) <= geo.EPS:
                continue
            d = geo.normalize(geo.sub(end, other))
            rays.append((end, d, item))
        aperture = self.settings.aperture_px
        for end, d, item in rays:
            t = geo.dot(geo.sub(cursor, end), d)
            if t <= aperture / scale:
                continue
            q = geo.add(end, geo.mul(d, t))
            if geo.distance(q, cursor) * scale <= aperture:
                add("ext", q, item.entity, item.segment, [("ext", end, q)])
            for entity, (a, b) in segments:                 # prolongement qui coupe un objet proche
                found = geo.line_intersection(end, geo.add(end, d), a, b)
                if found is None:
                    continue
                point, tt, u = found
                if tt > geo.EPS and -1e-9 <= u <= 1 + 1e-9:
                    add("extint", point, entity, (a, b), [("ext", end, point)])
        for i in range(len(rays)):                          # deux prolongements qui se coupent
            e1, d1, _i1 = rays[i]
            for j in range(i + 1, len(rays)):
                e2, d2, _i2 = rays[j]
                found = geo.line_intersection(e1, geo.add(e1, d1), e2, geo.add(e2, d2))
                if found is not None and found[1] > geo.EPS and found[2] > geo.EPS:
                    add("extint", found[0], None, None, [("ext", e1, found[0]), ("ext", e2, found[0])])

    def _apparent_candidates(self, cursor, scale, add):
        radius = 4 * self.settings.aperture_px / scale
        lines = [(e, (p[1], p[2])) for e, p in self._near(cursor, radius) if p[0] == "segment"]
        lines += [(item.entity, item.segment) for item in self.acquired if item.segment is not None]
        seen = set()
        for i in range(len(lines)):
            ea, (a, b) = lines[i]
            for j in range(i + 1, len(lines)):
                eb, (c, d) = lines[j]
                if ea is not None and ea is eb:
                    continue
                key = (id(ea), id(eb))
                if key in seen:
                    continue
                seen.add(key)
                found = geo.line_intersection(a, b, c, d)
                if found is None:
                    continue
                point, t, u = found
                real = -1e-9 <= t <= 1 + 1e-9 and -1e-9 <= u <= 1 + 1e-9
                if real:
                    continue                                # intersection reelle : mode Intersection
                guides = []
                if not -1e-9 <= t <= 1 + 1e-9:
                    guides.append(("ext", a if t < 0 else b, point))
                if not -1e-9 <= u <= 1 + 1e-9:
                    guides.append(("ext", c if u < 0 else d, point))
                add("appint", point, ea, (a, b), guides)

    # -- suivi polaire et suivi d'accrochage --
    def polar_angles(self) -> list[float]:
        step = self.settings.polar_angle
        count = max(1, int(round(360.0 / step)))
        return [(k * step) % 360.0 for k in range(count)]

    def _tracking(self, cursor, aperture, base):
        s = self.settings
        lines = []                                          # (origine, angle, sorte)
        if base is not None and s.polar and not s.ortho:
            lines += [(base, a, "polar") for a in self.polar_angles()]
        if s.otrack and self.acquired:
            angles = self.polar_angles() if (s.track_polar and s.polar) else [0.0, 90.0, 180.0, 270.0]
            for item in self.acquired:
                lines += [(item.point, a, "track") for a in angles]
        if not lines:
            return None
        near = []
        for origin, angle, kind in lines:
            d = geo.direction(angle)
            t = geo.dot(geo.sub(cursor, origin), d)
            if t <= 0:
                continue                                    # demi-droite : du cote ou l'on va
            q = geo.add(origin, geo.mul(d, t))
            dist = geo.distance(q, cursor)
            if dist <= aperture:
                near.append((dist, origin, angle, kind, q))
        if not near:
            return None
        # Intersection de deux lignes de suivi (l'une au moins issue d'un point acquis) a portee : prioritaire.
        best = None
        for i in range(len(near)):
            for j in range(i + 1, len(near)):
                _d1, o1, a1, k1, _q1 = near[i]
                _d2, o2, a2, k2, _q2 = near[j]
                if geo.distance(o1, o2) <= geo.EPS:
                    continue
                found = geo.line_intersection(o1, geo.polar(o1, 1.0, a1), o2, geo.polar(o2, 1.0, a2))
                if found is None:
                    continue
                point = found[0]
                dist = geo.distance(point, cursor)
                if dist <= aperture and (best is None or dist < best[0]):
                    best = (dist, point, (o1, a1, k1), (o2, a2, k2))
        if best is not None:
            _dist, point, l1, l2 = best
            guides = [(l1[2], l1[0], point), (l2[2], l2[0], point)]
            return Resolution(point, "track", guides=guides, label="Intersection de suivi",
                              angle=geo.angle_deg(base, point) if base is not None else None)
        near.sort(key=lambda n: (n[0], n[3] != "polar"))
        _dist, origin, angle, kind, q = near[0]
        label = "Polaire" if kind == "polar" else "Suivi"
        return Resolution(q, "polar" if kind == "polar" else "track", guides=[(kind, origin, q)],
                          label=label, angle=angle)
