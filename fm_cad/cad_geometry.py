"""Module CAD du board : geometrie PURE (aucun Qt), en double precision, dans les coordonnees du DOCUMENT.

Trois systemes de coordonnees, jamais melanges (conversions ici et dans `cad.py`) :
- ECRAN : pixels du viewport de la vue (souris, tolerances, marqueurs) ;
- SCENE : unites du board (QGraphicsScene), Y vers le BAS ; 1 unite = 1 px CSS = 1/96 de pouce (voir model) ;
- DOCUMENT CAD : memes unites que la scene, Y vers le HAUT (comme AutoCAD), origine commune :
  doc = (scene.x, -scene.y). Angles en degres, sens TRIGONOMETRIQUE, 0 = vers l'est (convention d'AutoCAD).
La geometrie de reference (extremites, longueur, angle, accrochages) est toujours celle du document ; l'aspect
(epaisseur, extremites arrondies, motifs) n'entre jamais dans ces calculs.

Points = tuples (x, y) de flottants."""
from __future__ import annotations

import math

EPS = 1e-9                 # tolerance absolue des tests geometriques (unites du document)

Point = tuple


# -- conversions --
def to_scene(p) -> tuple[float, float]:
    """Document (Y vers le haut) -> scene du board (Y vers le bas)."""
    return float(p[0]), -float(p[1])


def to_doc(x: float, y: float) -> tuple[float, float]:
    """Scene du board -> document."""
    return float(x), -float(y)


# -- vecteurs --
def add(a, b):
    return a[0] + b[0], a[1] + b[1]


def sub(a, b):
    return a[0] - b[0], a[1] - b[1]


def mul(a, k: float):
    return a[0] * k, a[1] * k


def dot(a, b) -> float:
    return a[0] * b[0] + a[1] * b[1]


def cross(a, b) -> float:
    return a[0] * b[1] - a[1] * b[0]


def length(v) -> float:
    return math.hypot(v[0], v[1])


def distance(a, b) -> float:
    return math.hypot(b[0] - a[0], b[1] - a[1])


def normalize(v):
    n = length(v)
    return (v[0] / n, v[1] / n) if n > EPS else (0.0, 0.0)


def lerp(a, b, t: float):
    return a[0] + (b[0] - a[0]) * t, a[1] + (b[1] - a[1]) * t


def midpoint(a, b):
    return (a[0] + b[0]) / 2.0, (a[1] + b[1]) / 2.0


def angle_deg(a, b) -> float:
    """Angle de a vers b, degres dans [0, 360), sens trigonometrique, 0 = est."""
    angle = math.degrees(math.atan2(b[1] - a[1], b[0] - a[0]))
    angle = angle % 360.0
    return 0.0 if abs(angle - 360.0) < 1e-12 else angle


def polar(base, dist: float, angle: float):
    """Point a `dist` de `base` dans la direction `angle` (degres)."""
    r = math.radians(angle)
    return base[0] + dist * math.cos(r), base[1] + dist * math.sin(r)


def direction(angle: float):
    r = math.radians(angle)
    return math.cos(r), math.sin(r)


def angle_diff(a: float, b: float) -> float:
    """Ecart signe a - b ramene dans (-180, 180]."""
    d = (a - b) % 360.0
    return d - 360.0 if d > 180.0 else d


def clean(value: float, digits: int = 12) -> float:
    """Arrondi d'affichage / de saisie (bruit de l'arithmetique flottante : 99.99999999999999 -> 100.0)."""
    out = round(float(value), digits)
    return 0.0 if out == 0 else out


# -- projections --
def project_param(p, a, b) -> float:
    """Parametre t de la projection de p sur la droite (a, b) : 0 en a, 1 en b."""
    d = sub(b, a)
    n = dot(d, d)
    if n <= EPS * EPS:
        return 0.0
    return dot(sub(p, a), d) / n


def project_line(p, a, b):
    """Projection de p sur la DROITE infinie (a, b)."""
    return lerp(a, b, project_param(p, a, b))


def project_segment(p, a, b):
    """(point le plus proche sur le SEGMENT, t borne a [0, 1])."""
    t = max(0.0, min(1.0, project_param(p, a, b)))
    return lerp(a, b, t), t


def distance_point_segment(p, a, b) -> float:
    q, _t = project_segment(p, a, b)
    return distance(p, q)


def distance_point_line(p, a, b) -> float:
    d = sub(b, a)
    n = length(d)
    if n <= EPS:
        return distance(p, a)
    return abs(cross(d, sub(p, a))) / n


def perpendicular_foot(p, a, b):
    """Pied de la perpendiculaire abaissee de p sur la droite (a, b) (accrochage Perpendiculaire)."""
    return project_line(p, a, b)


# -- intersections --
def line_intersection(a, b, c, d):
    """Intersection des DROITES (a, b) et (c, d) : (point, t, u) avec point = a + t (b - a) = c + u (d - c) ;
    None si paralleles (ou confondues)."""
    r = sub(b, a)
    s = sub(d, c)
    denom = cross(r, s)
    scale = max(length(r) * length(s), EPS)
    if abs(denom) <= 1e-12 * scale:
        return None
    qp = sub(c, a)
    t = cross(qp, s) / denom
    u = cross(qp, r) / denom
    return lerp(a, b, t), t, u


def segment_intersection(a, b, c, d, tol: float = 1e-9):
    """Intersection des SEGMENTS (point ou None). `tol` : tolerance relative sur les parametres (extremites
    communes comprises). Segments colineaires qui se chevauchent : None (pas de point unique)."""
    found = line_intersection(a, b, c, d)
    if found is None:
        return None
    point, t, u = found
    if -tol <= t <= 1 + tol and -tol <= u <= 1 + tol:
        return point
    return None


def segment_intersects_rect(a, b, rect) -> bool:
    """Le segment touche-t-il le rectangle (xmin, ymin, xmax, ymax) (selection par CAPTURE) ?"""
    xmin, ymin, xmax, ymax = rect
    if point_in_rect(a, rect) or point_in_rect(b, rect):
        return True
    corners = ((xmin, ymin), (xmax, ymin), (xmax, ymax), (xmin, ymax))
    for i in range(4):
        if segment_intersection(a, b, corners[i], corners[(i + 1) % 4]) is not None:
            return True
    return False


def point_in_rect(p, rect) -> bool:
    xmin, ymin, xmax, ymax = rect
    return xmin - EPS <= p[0] <= xmax + EPS and ymin - EPS <= p[1] <= ymax + EPS


def segment_in_rect(a, b, rect) -> bool:
    """Segment entierement dans le rectangle (selection par FENETRE)."""
    return point_in_rect(a, rect) and point_in_rect(b, rect)


def normalized_rect(a, b) -> tuple[float, float, float, float]:
    return min(a[0], b[0]), min(a[1], b[1]), max(a[0], b[0]), max(a[1], b[1])


# -- motifs de type de ligne --
def dash_intervals(total: float, pattern, scale: float, dot_length: float = 0.0, limit: int = 20000):
    """Intervalles VISIBLES [(u0, u1)] le long d'une ligne de longueur `total` pour un motif de type de ligne
    (`pattern` : longueurs > 0 = trait, < 0 = espace, 0 = point ; en unites du document, multipliees par
    `scale`). Le motif part de la premiere extremite. Un point prend la longueur `dot_length` (centre sur sa
    position). Au-dela de `limit` intervalles : None (l'appelant dessine alors un trait continu)."""
    if not pattern or total <= EPS:
        return [(0.0, total)]
    steps = [float(v) * scale for v in pattern]
    period = sum(abs(v) for v in steps)
    if period <= EPS:
        return [(0.0, total)]
    count = total / period * sum(1 for v in steps if v >= 0)
    if count > limit:
        return None
    out = []
    u = 0.0
    while u < total - EPS:
        for step in steps:
            if u >= total - EPS:
                break
            if step > 0:
                out.append((u, min(total, u + step)))
                u += step
            elif step == 0:
                half = dot_length / 2.0
                out.append((max(0.0, u - half), min(total, u + half)))
            else:
                u += -step
    return [(a, b) for a, b in out if b - a > EPS or dot_length <= EPS]


# -- grille --
def snap_to_grid(p, spacing: float, origin=(0.0, 0.0)):
    if spacing <= EPS:
        return p
    return (origin[0] + round((p[0] - origin[0]) / spacing) * spacing,
            origin[1] + round((p[1] - origin[1]) / spacing) * spacing)


# -- index spatial --
class GridIndex:
    """Index spatial en grille uniforme (recherche LOCALISEE des entites candidates : accrochage, selection).
    `build([(objet, (xmin, ymin, xmax, ymax))])` ; `insert` / `remove` un objet (mise a jour INCREMENTALE : une
    ligne ajoutee ne refait pas l'index de tout le dessin) ; `query(rect)` rend les objets dont l'emprise touche
    `rect`. Taille des cellules adaptee aux emprises a la construction (la plupart des objets tiennent dans
    quelques cellules) ; un objet tres etendu (plus de `MAX_CELLS` cellules) va dans une liste a part, toujours
    testee par son emprise. `needs_rebuild` : le dessin a trop change depuis (taille des cellules a revoir)."""

    MAX_CELLS = 64

    def __init__(self):
        self.cell = 64.0
        self.cells: dict = {}
        self.large: dict = {}
        self.boxes: dict = {}
        self.objects: dict = {}
        self._built_count = 0

    def build(self, entries):
        entries = list(entries)
        self.cells, self.large, self.boxes, self.objects = {}, {}, {}, {}
        sides = sorted(max(b[2] - b[0], b[3] - b[1]) for _o, b in entries) or [64.0]
        median = sides[len(sides) // 2]
        self.cell = max(1e-3, median * 2.0, 1e-6 + (sides[-1] / 1e6))
        c = self.cell
        cells, large, boxes, objects = self.cells, self.large, self.boxes, self.objects
        floor = math.floor
        for obj, box in entries:                            # meme chose que `insert`, sans appel par objet
            key = id(obj)
            boxes[key] = box
            objects[key] = obj
            x0, y0, x1, y1 = floor(box[0] / c), floor(box[1] / c), floor(box[2] / c), floor(box[3] / c)
            if (x1 - x0 + 1) * (y1 - y0 + 1) > self.MAX_CELLS:
                large[key] = obj
                continue
            for gx in range(x0, x1 + 1):
                for gy in range(y0, y1 + 1):
                    bucket = cells.get((gx, gy))
                    if bucket is None:
                        cells[(gx, gy)] = [obj]
                    else:
                        bucket.append(obj)
        self._built_count = len(entries)

    def _span(self, box):
        c = self.cell
        return math.floor(box[0] / c), math.floor(box[1] / c), math.floor(box[2] / c), math.floor(box[3] / c)

    def insert(self, obj, box):
        key = id(obj)
        if key in self.boxes:
            self.remove(obj)
        self.boxes[key] = box
        self.objects[key] = obj
        x0, y0, x1, y1 = self._span(box)
        if (x1 - x0 + 1) * (y1 - y0 + 1) > self.MAX_CELLS:
            self.large[key] = obj
            return
        cells = self.cells
        for gx in range(x0, x1 + 1):
            for gy in range(y0, y1 + 1):
                cells.setdefault((gx, gy), []).append(obj)

    def remove(self, obj):
        key = id(obj)
        box = self.boxes.pop(key, None)
        if box is None:
            return
        del self.objects[key]
        if self.large.pop(key, None) is not None:
            return
        x0, y0, x1, y1 = self._span(box)
        for gx in range(x0, x1 + 1):
            for gy in range(y0, y1 + 1):
                bucket = self.cells.get((gx, gy))
                if bucket is not None:
                    for n, other in enumerate(bucket):
                        if other is obj:
                            del bucket[n]
                            break
                    if not bucket:
                        del self.cells[(gx, gy)]

    def needs_rebuild(self) -> bool:
        count = len(self.objects)
        return len(self.large) > 32 + count // 8 or count > 2 * self._built_count + 256

    def query(self, rect) -> list:
        xmin, ymin, xmax, ymax = rect
        x0, y0, x1, y1 = self._span(rect)
        if (x1 - x0 + 1) * (y1 - y0 + 1) > max(256, len(self.cells)):
            pool = list(self.objects.values())              # grande zone : un seul passage sur tout
        else:
            pool, seen = [], set()
            for gx in range(x0, x1 + 1):
                for gy in range(y0, y1 + 1):
                    for obj in self.cells.get((gx, gy), ()):
                        if id(obj) not in seen:
                            seen.add(id(obj))
                            pool.append(obj)
            pool += self.large.values()
        out = []
        boxes = self.boxes
        for obj in pool:
            b = boxes[id(obj)]
            if b[0] <= xmax and b[2] >= xmin and b[1] <= ymax and b[3] >= ymin:
                out.append(obj)
        return out
