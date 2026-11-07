"""Module CAD du board : RENDU des entites CAD dans la scene du board. Une entite = un element du board
(`BoardItem`) : selection, annulation, copier / coller, export, enregistrement passent par les mecanismes du
board ; la geometrie de reference reste celle du DOCUMENT (cad_geometry), l'aspect est calcule ici.

`CadLineItem` (type `cad_line`) :
- geometrie : `p1` / `p2` en coordonnees du document (Y vers le haut), en double precision ; la place Qt de
  l'element (`pos`, deplacement par le board hors du mode CAD, collage) est AJOUTEE puis repliee dans les
  points a l'enregistrement (`to_dict` : x = y = 0, aucun arrondi des points) ;
- aspect : proprietes EFFECTIVES lues dans le calque (cad_model.resolve, ByLayer dynamique) ; contour exact
  du trait epais genere ici (`line_outline`) : coupe franche, arrondi (demi-cercle au-dela du point), border
  radius (coins arrondis dans la coupe, rayon = % de la demi-epaisseur ; deux extremites trop proches :
  rayons reduits ensemble) ; motifs des types de ligne en unites du document (trop serres a l'ecran : trait
  continu) ; epaisseur 0 ou < 1 pixel = trait fin d'un pixel ;
- jamais d'image gardee (NoCache, `NO_CACHE`) : un trait se dessine plus vite qu'une image de la taille de
  son emprise (une diagonale couvrirait l'ecran) ; contours et motifs gardes en cache, refaits seulement quand
  la geometrie ou les proprietes changent.

DESSIN GROUPE (`CadLayer`, `CadBatch`) : peindre chaque ligne par son propre `paint` coutait ~20 us de Python
et de QGraphicsView par ligne (5 000 lignes : ~100 ms par image, donc par cran de zoom) contre ~5 ms pour Qt en
un seul appel. Les lignes CAD CONSECUTIVES dans l'ordre d'empilement du board (aucun autre element entre elles)
forment un lot : un element `CadBatch` place a leur hauteur, qui les peint toutes (traits fins de meme
couleur en UN `drawLines`, traits epais de meme couleur en UN chemin), dans leur ordre ; chaque ligne du lot
porte `ItemHasNoContents` (Qt ne l'appelle plus) mais reste un element normal (selection, accrochage,
annulation, enregistrement, deplacement par le board). L'ordre d'empilement avec les autres elements est
garde exactement (un element du board entre deux lignes coupe le lot). Une ligne hors lot (juste creee,
changee de hauteur) se peint elle-meme jusqu'au regroupement suivant (boucle d'evenements suivante) : jamais
d'image fausse. Geometrie en cache par ligne (repere de la scene), listes de dessin en cache par lot, refaites
seulement pour ce qui change ; le classement trait fin / trait epais / motif serre ne depend du zoom qu'a des
seuils (`_thresholds`) : il n'est refait que quand le zoom en franchit un.
Le dessin ne touche jamais au disque ni au reste de la scene."""
from __future__ import annotations

import copy
import math

import bisect

from PySide6.QtCore import QLineF, QPointF, QRect, QRectF, Qt, QTimer
from PySide6.QtGui import QColor, QFont, QFontMetricsF, QGuiApplication, QImage, QPainter, QPainterPath, QPainterPathStroker, QPen, QTransform
from PySide6.QtWidgets import QGraphicsItem, QStyle

from . import cad_geometry as geo
from . import cad_assoc, cad_block, cad_dims, cad_hatch, cad_image, cad_model, cad_point, cad_shapes, cad_text, cad_xline
from fm_miro import items as _items
from fm_miro.items import ITEM_CLASSES, BoardItem

GRIP_PX = 8                 # poignees (grips), pixels d'ecran ; reglable (board_cad_grip_size)
GRIP_COLOR = "#2f6bff"      # grip froid (bleu, comme AutoCAD) ; reglable (board_cad_grip_color)
GRIP_BORDER = "#ffffff"     # contour des poignees ; reglable (board_cad_grip_border_color)
DENSE_PX = 4.0              # motif plus serre que ca a l'ecran : trait continu ; reglable (board_cad_dense_px)
MAX_DASHES = 4000


def paint_grips(painter, points, size: float, fill, border):
    """Poignees : carres PARFAITS de `size` pixels d'ecran, poses sur les pixels PHYSIQUES (sans anticrenelage : ni
    bord flou ni cote plus epais qu'un autre), contour d'UN pixel PLEINEMENT OPAQUE de la couleur `border` sur tout le
    pourtour (demande de l'utilisateur), dedans de la couleur `fill` (sa transparence ne touche pas le contour : les
    deux ne se recouvrent pas). Cote IMPAIR (taille paire : un pixel de plus) : centre EXACTEMENT sur le pixel du point,
    comme le reticule (une taille paire laissait 2 pixels de contour d'un cote, 1 de l'autre). `points` : dans le
    repere courant du peintre (element, vue ou zone GPU)."""
    ratio = painter.device().devicePixelRatioF() or 1.0
    world = painter.transform()
    side = max(3, round(size * ratio)) | 1
    edge = max(1, round(ratio))
    ink = QColor(border)
    ink.setAlpha(255)
    inside = QColor(fill)
    painter.save()
    painter.setTransform(QTransform.fromScale(1.0 / ratio, 1.0 / ratio))
    painter.setRenderHint(QPainter.Antialiasing, False)
    for point in points:
        q = world.map(QPointF(point))
        x0 = math.floor(q.x() * ratio) - side // 2
        y0 = math.floor(q.y() * ratio) - side // 2
        painter.fillRect(QRect(x0, y0, side, edge), ink)
        painter.fillRect(QRect(x0, y0 + side - edge, side, edge), ink)
        painter.fillRect(QRect(x0, y0 + edge, edge, side - 2 * edge), ink)
        painter.fillRect(QRect(x0 + side - edge, y0 + edge, edge, side - 2 * edge), ink)
        if side > 2 * edge:
            painter.fillRect(QRect(x0 + edge, y0 + edge, side - 2 * edge, side - 2 * edge), inside)
    painter.restore()


class PixelLines:
    """Traits fins (1 pixel) d'un lot : les horizontaux et verticaux sont recales sur le CENTRE d'un pixel au
    moment de peindre (sinon un trait a cheval sur deux rangees de pixels s'etale en deux traits gris de moitie
    d'intensite : le flou qu'on voyait) ; les obliques gardent l'anticrenelage de Qt (couverture exacte). Le
    recalage depend de la place de la vue (defilement, zoom) : refait seulement quand la transformation change."""

    def __init__(self, lines):
        self.free = []
        self.h = []                                 # (x1, x2, y)
        self.v = []                                 # (y1, y2, x)
        for line in lines:
            x1, y1, x2, y2 = line.x1(), line.y1(), line.x2(), line.y2()
            if y1 == y2:
                self.h.append((x1, x2, y1))
            elif x1 == x2:
                self.v.append((y1, y2, x1))
            else:
                self.free.append(line)
        self._key = None
        self._lines = None

    def extend(self, lines):
        more = PixelLines(lines)
        self.free += more.free
        self.h += more.h
        self.v += more.v
        self._key = None

    def lines(self, t: QTransform, crisp: bool = True) -> list:
        if not crisp or abs(t.m12()) > 1e-9 or abs(t.m21()) > 1e-9 or abs(t.m11()) < 1e-12 or abs(t.m22()) < 1e-12:
            return self.free + [QLineF(x1, y, x2, y) for x1, x2, y in self.h] +                 [QLineF(x, y1, x, y2) for y1, y2, x in self.v]
        # Le recalage ne depend que de l'echelle et de la partie FRACTIONNAIRE du decalage : un defilement d'un nombre
        # entier de pixels (deplacement du board, masques des bandes qui apparaissent) reprend les memes traits.
        dx, dy = t.dx() - math.floor(t.dx()), t.dy() - math.floor(t.dy())
        key = (t.m11(), t.m22(), round(dx, 9), round(dy, 9))
        if key != self._key:
            sx, sy, dx, dy = key
            floor = math.floor
            out = list(self.free)
            out += [QLineF(x1, yy, x2, yy) for x1, x2, yy in
                    ((x1, x2, (floor(y * sy + dy) + 0.5 - dy) / sy) for x1, x2, y in self.h)]
            out += [QLineF(xx, y1, xx, y2) for y1, y2, xx in
                    ((y1, y2, (floor(x * sx + dx) + 0.5 - dx) / sx) for y1, y2, x in self.v)]
            self._key, self._lines = key, out
        return self._lines


def line_outline(length: float, half: float, end1: dict, end2: dict) -> QPainterPath:
    """Contour EXACT d'un trait epais dans son repere local : axe de (0, 0) a (length, 0), demi-epaisseur
    `half` (repere Qt : v vers le bas). Extremite 1 en u = 0, extremite 2 en u = length."""
    path = QPainterPath()
    h = max(0.0, half)
    if h <= 0:
        return path
    s1, s2 = end1.get("style", "flat"), end2.get("style", "flat")
    if length <= geo.EPS:
        if "round" in (s1, s2) or (s1 == "radius" and end1.get("radius", 0) > 0) or (
                s2 == "radius" and end2.get("radius", 0) > 0):
            path.addEllipse(QPointF(0, 0), h, h)
        else:
            path.addRect(QRectF(-h, -h, 2 * h, 2 * h))
        return path
    r1 = h * max(0.0, min(100.0, float(end1.get("radius", 0.0)))) / 100.0 if s1 == "radius" else 0.0
    r2 = h * max(0.0, min(100.0, float(end2.get("radius", 0.0)))) / 100.0 if s2 == "radius" else 0.0
    if r1 + r2 > length:                            # extremites qui se rencontrent : rayons reduits ensemble
        k = length / (r1 + r2)
        r1, r2 = r1 * k, r2 * k
    L = length
    path.moveTo(r1, -h)
    path.lineTo(L - r2, -h)
    if s2 == "round":
        path.arcTo(QRectF(L - h, -h, 2 * h, 2 * h), 90, -180)
    elif r2 > 0:
        path.arcTo(QRectF(L - 2 * r2, -h, 2 * r2, 2 * r2), 90, -90)
        path.lineTo(L, h - r2)
        path.arcTo(QRectF(L - 2 * r2, h - 2 * r2, 2 * r2, 2 * r2), 0, -90)
    else:
        path.lineTo(L, -h)
        path.lineTo(L, h)
    path.lineTo(r1, h)
    if s1 == "round":
        path.arcTo(QRectF(-h, -h, 2 * h, 2 * h), 270, -180)
    elif r1 > 0:
        path.arcTo(QRectF(0, h - 2 * r1, 2 * r1, 2 * r1), 270, -90)
        path.lineTo(0, -h + r1)
        path.arcTo(QRectF(0, -h, 2 * r1, 2 * r1), 180, -90)
    else:
        path.lineTo(0, h)
        path.lineTo(0, -h)
    path.closeSubpath()
    return path


# Ce qui change l'aspect d'une ligne (proprietes effectives relues a chaque changement de calque / de reglage).
FADE_OPACITY = 0.3                    # elements grises d'un module du board (selecteur de modules)
FADE_SATURATION = 1.0                 # saturation des elements grises (1 = couleurs gardees, 0 = gris)


def fade_ink(color) -> str:
    """Couleur d'un element grise : desaturee selon FADE_SATURATION (reglage de la barre des modules du board)."""
    sat = FADE_SATURATION
    if sat >= 0.999:
        return color if isinstance(color, str) else QColor(color).name(QColor.HexArgb)
    c = QColor(color)
    luma = 0.2126 * c.redF() + 0.7152 * c.greenF() + 0.0722 * c.blueF()
    out = QColor.fromRgbF(*(luma + (v - luma) * sat for v in (c.redF(), c.greenF(), c.blueF())), c.alphaF())
    return out.name(QColor.HexArgb)


def cad_module_look(scene) -> tuple:
    """(masque, grise) du module CAD sur ce board (selecteur de modules, `BoardScene.module_look`). Etat GLOBAL lu au
    dessin (rendu GPU, rendu par lots, textes, hachures, export) et a la recherche des entites : rien n'est refait
    entite par entite (le faire coutait ~0,6 s pour 5 000 entites, mesure)."""
    look = getattr(scene, "module_look", None)
    if look is None:
        return False, False
    cad = look["cad"]
    return cad["hide"], cad["fade"] and not cad["hide"]


STYLE_KEYS = ("color", "lineweight", "linetype", "pattern", "ltscale", "extra", "distribute", "resize", "end1", "end2",
              "inner", "visible", "locked")


def unit_of(scene, cad: dict) -> float:
    """Unites du board par unite de mesure du dessin : la sienne (reglages du dessin), sinon la generale (posee sur la
    scene par le board, Reglages > Module CAD > Unites)."""
    general = getattr(scene, "cad_unit", cad_model.DEFAULT_UNIT) if scene is not None else cad_model.DEFAULT_UNIT
    return cad_model.unit_scale(cad_model.drawing_unit(cad, general))


def pattern_layout(props: dict, length: float) -> tuple:
    """(echelle du motif, decalage, longueur occupee) d'une ligne. Repartir les segments = cycles ENTIERS + segment
    additionnel, le motif garde sa taille et le groupe est CENTRE sur la ligne ; avec « redimensionner », le motif est
    allonge ou raccourci pour remplir toute la ligne (aucun decalage)."""
    scale = props["ltscale"]
    if not props.get("distribute"):
        return scale, 0.0, length
    period = cad_model.pattern_period(props["pattern"]) * scale
    extra = props.get("extra", 0.0) * scale
    if props.get("resize"):
        return scale * cad_model.distribution(length, period, extra), 0.0, length
    offset, span = cad_model.centered_span(length, period, extra)
    return scale, offset, span


def tess_band(scene) -> float:
    """Zoom (puissance de 2 au-dessus) pour lequel les COURBES sont tessellees en traits fins : la vue ne le change
    qu'a la FIN d'un zoom (`scene.cad_tess_zoom`) — pendant le geste on garde la tessellation (« regeneration »
    differee, comme AutoCAD)."""
    zoom = float(getattr(scene, "cad_tess_zoom", getattr(scene, "zoom", 1.0)) or 1.0) if scene is not None else 1.0
    return 2.0 ** math.ceil(math.log2(max(1e-4, zoom)))


def scene_path(primitives) -> QPainterPath:
    """Trace (axe) dans le repere de la scene : segments et arcs EXACTS (Qt : meme sens des angles que le document,
    l'axe Y etant retourne)."""
    path = QPainterPath()
    last = None
    for p in primitives:
        start = cad_shapes.prim_start(p)
        sx, sy = start[0], -start[1]
        fresh = last is None or geo.distance(last, start) > geo.EPS * 10
        if p[0] == "segment":
            if fresh:
                path.moveTo(sx, sy)
            path.lineTo(p[2][0], -p[2][1])
        else:
            c, r = p[1], p[2]
            rect = QRectF(c[0] - r, -c[1] - r, 2 * r, 2 * r)
            if fresh:
                # Depart EXACT de l'arc (arcMoveTo) : un moveTo sur le point calcule laissait arcTo ajouter un segment
                # minuscule de direction quelconque, dont la coupe franche faisait une encoche au bout (signale
                # 2026-11-05, cercle coupe).
                path.arcMoveTo(rect, p[3])
            path.arcTo(rect, p[3], p[4])
        last = cad_shapes.prim_end(p)
    return path


def _exact_arc_outline(primitives, half: float, start, end, closed: bool):
    """Contour exact d'un cercle (anneau) ou d'un arc seul (secteur d'anneau, bouts francs radiaux, disque aux bouts
    « arrondi ») ; None pour toute autre courbe."""
    if len(primitives) != 1 or primitives[0][0] != "arc" or half <= 0:
        return None
    _kind, c, r, a0, sweep = primitives[0]
    cx, cy = c[0], -c[1]
    outer = QRectF(cx - r - half, cy - r - half, 2 * (r + half), 2 * (r + half))
    inner_r = max(0.0, r - half)
    inner = QRectF(cx - inner_r, cy - inner_r, 2 * inner_r, 2 * inner_r)
    path = QPainterPath()
    if closed or abs(sweep) >= 360.0 - 1e-9:
        # Trou trace a REBOURS : vide aussi en remplissage « winding » (les lots fusionnent les contours, ThickPaths).
        path.setFillRule(Qt.WindingFill)
        path.addEllipse(outer)
        if inner_r > 0:
            hole = QPainterPath()
            hole.addEllipse(inner)
            path.addPath(hole.toReversed())
        return path
    path.arcMoveTo(outer, a0)
    path.arcTo(outer, a0, sweep)
    if inner_r > 0:
        path.arcTo(inner, a0 + sweep, -sweep)            # retour par le bord interieur (le lineTo est le bout radial)
    else:
        path.lineTo(cx, cy)
    path.closeSubpath()
    caps = QPainterPath()
    for end_style, point in ((start, cad_shapes.prim_start(primitives[0])), (end, cad_shapes.prim_end(primitives[0]))):
        if end_style is not None and end_style.get("style") == "round":
            caps.addEllipse(QPointF(point[0], -point[1]), half, half)
    if not caps.isEmpty():
        path = path.united(caps)
    path.setFillRule(Qt.WindingFill)
    return path


def _radius_corners(path: QPainterPath, primitives, half: float, start, end) -> QPainterPath:
    """Bouts « border radius » d'une courbe epaisse (demande, 2026-11-05 : avant, rendus en coupe franche) : a chaque
    coin du bout, la zone hors du quart de cercle de rayon rr (= % de la demi-epaisseur) est retiree. Le bout est
    perpendiculaire au trace (radial pour un arc) : les coins sont des angles droits."""
    notches = QPainterPath()
    for end_style, prim, s_at, outward in ((start, primitives[0], 0.0, -1.0),
                                           (end, primitives[-1], None, 1.0)):
        if end_style is None or end_style.get("style") != "radius":
            continue
        rr = half * max(0.0, min(100.0, float(end_style.get("radius", 0.0)))) / 100.0
        if rr <= geo.EPS:
            continue
        s = cad_shapes.prim_length(prim) if s_at is None else s_at
        point = cad_shapes.prim_point(prim, s)
        t = cad_shapes.prim_tangent(prim, s)
        d = (outward * t[0], -outward * t[1])                      # vers l'exterieur du bout, repere de la scene
        n0 = (-d[1], d[0])
        p = (point[0], -point[1])
        m = rr * 0.5 + 1e-3                                         # marge hors de la forme (courbure)
        for side in (1.0, -1.0):
            n = (n0[0] * side, n0[1] * side)
            c = (p[0] + n[0] * half, p[1] + n[1] * half)            # coin
            def at(a, b):                                            # a vers l'interieur le long du trace, b vers l'axe
                return QPointF(c[0] - d[0] * a - n[0] * b, c[1] - d[1] * a - n[1] * b)
            square = QPainterPath()
            square.moveTo(at(-m, -m))
            square.lineTo(at(rr, -m))
            square.lineTo(at(rr, rr))
            square.lineTo(at(-m, rr))
            square.closeSubpath()
            disc = QPainterPath()
            disc.addEllipse(at(rr, rr), rr, rr)
            notches.addPath(square.subtracted(disc))
    if notches.isEmpty():
        return path
    out = path.subtracted(notches)
    out.setFillRule(Qt.WindingFill)
    return out


def stroke_outline(primitives, half: float, start: dict | None, end: dict | None, closed: bool) -> QPainterPath:
    """Contour d'un trait epais qui suit les primitives : coupe franche, angles en onglet (polylignes larges
    d'AutoCAD), disque pose aux bouts « arrondi », coins arrondis aux bouts « border radius » (`start` / `end` =
    terminaison, None = aucune)."""
    out = _stroke_outline(primitives, half, start, end, closed)
    if closed or not primitives or half <= 0:
        return out
    return _radius_corners(out, primitives, half, start, end)


def _stroke_outline(primitives, half: float, start: dict | None, end: dict | None, closed: bool) -> QPainterPath:
    # Trait EPAIS sur une courbe : le decalage des courbes de Bezier par Qt est approche, et se deforme quand la
    # demi-epaisseur approche le rayon (trou « carre » d'un cercle epais, signale 2026-11-05). Cercle / arc seul :
    # contour EXACT (anneau, secteur d'anneau) ; autre courbe tres epaisse : petits segments, decales sans erreur.
    exact = _exact_arc_outline(primitives, half, start, end, closed)
    if exact is not None:
        return exact
    radii = [p[2] for p in primitives if p[0] != "segment" and p[2] > 0]
    if radii and half > 0.1 * min(radii):
        fine = cad_shapes.tessellate(primitives, max(min(radii) * 2e-4, 1e-6))
        path = QPainterPath()
        for pts in fine:
            path.moveTo(pts[0][0], -pts[0][1])
            for q in pts[1:]:
                path.lineTo(q[0], -q[1])
    else:
        path = scene_path(primitives)
    if closed:
        path.closeSubpath()
    stroker = QPainterPathStroker()
    stroker.setWidth(2.0 * half)
    stroker.setCapStyle(Qt.FlatCap)
    stroker.setJoinStyle(Qt.MiterJoin)
    stroker.setMiterLimit(4.0)
    out = stroker.createStroke(path)
    out.setFillRule(Qt.WindingFill)
    if not closed and primitives:
        for end_style, point in ((start, cad_shapes.prim_start(primitives[0])),
                                 (end, cad_shapes.prim_end(primitives[-1]))):
            if end_style is not None and end_style.get("style") == "round":
                out.addEllipse(QPointF(point[0], -point[1]), half, half)
    return out


def dashed_outline(intervals, length: float, half: float, end1: dict, end2: dict, inner: dict) -> QPainterPath:
    """Contour des traits d'un motif (repere local de la ligne) : le bout qui tombe sur une extremite de la LIGNE prend
    sa terminaison (debut / fin), les autres bouts celle des segments interieurs."""
    dashed = QPainterPath()
    dashed.setFillRule(Qt.WindingFill)
    for u0, u1 in intervals:
        first = end1 if u0 <= geo.EPS else inner
        last = end2 if u1 >= length - geo.EPS else inner
        dashed.addPath(QTransform().translate(u0, 0).map(line_outline(u1 - u0, half, first, last)))
    return dashed


class CadLineItem(BoardItem):
    """Ligne CAD (entite independante, comme chaque segment de la commande LIGNE d'AutoCAD)."""

    RESIZABLE = False
    CONNECTABLE = False
    NO_CACHE = True
    CAD = True
    # Creee SANS contenu peint (lots, GPU ou chargement par tranches la peignent : voir `itemChange`), sans survol ni
    # image gardee : aucun reglage a refaire apres coup (chaque drapeau change = 2 appels Python de `itemChange`).
    ITEM_FLAGS = BoardItem.ITEM_FLAGS | QGraphicsItem.ItemHasNoContents
    HOVER = False
    CACHE_MODE = QGraphicsItem.NoCache
    INFINITE = False                # ligne de construction (XLINE / RAY) : ni lot ni GPU, decoupee a la vue

    def __init__(self, data: dict):
        self._geom_key = None
        self._outline = QPainterPath()
        self._dashed = None
        self._thin_dashes = None
        self._transform = None
        self._props = None
        self._shown = True                      # derniere visibilite notifiee (un element neuf est visible)
        self._bounds = QRectF()
        self._batch = None                      # lot qui peint cette ligne (CadBatch), None = se peint seule
        self._op = None                         # liste de dessin du lot qui la contient
        self._scene_geom: dict = {}             # geometrie dans le repere de la scene, par variante
        super().__init__(data)

    # -- etat --
    def to_dict(self) -> dict:
        """Place Qt repliee dans les points (jamais arrondis) : l'element enregistre est toujours en x = y = 0."""
        data = copy.deepcopy(self.data)
        a, b = self.points()
        data["p1"], data["p2"] = [a[0], a[1]], [b[0], b[1]]
        data["x"], data["y"] = 0.0, 0.0
        data["z"] = self.zValue()
        return data

    def points(self) -> tuple[tuple, tuple]:
        """Extremites EFFECTIVES en coordonnees du document (place Qt comprise)."""
        ox, oy = self.pos().x(), -self.pos().y()
        p1, p2 = self.data.get("p1") or (0, 0), self.data.get("p2") or (0, 0)
        return (float(p1[0]) + ox, float(p1[1]) + oy), (float(p2[0]) + ox, float(p2[1]) + oy)

    def length(self) -> float:
        a, b = self.points()
        return geo.distance(a, b)

    def angle(self) -> float:
        a, b = self.points()
        return geo.angle_deg(a, b) if geo.distance(a, b) > geo.EPS else 0.0

    def cad_page(self) -> dict:
        scene = self.scene()
        return cad_model.page_cad(getattr(scene, "page", None) or {})

    def props(self) -> dict:
        if self._props is None:
            cad = self.cad_page()
            props = cad_model.resolve_shared(self.data, cad, unit_of(self.scene(), cad))   # partagees : jamais modifiees
            scene = self.scene()
            if scene is not None and not getattr(scene, "cad_lineweights", True) and not getattr(scene, "exporting", False):
                props = dict(props)                     # affichage « simples lignes » : epaisseurs ignorees (trait fin d'un pixel)
                props["lineweight"] = 0.0
            self._props = props
        return self._props

    # -- API commune a toutes les entites (ligne, arc, cercle, polyligne : voir cad_shapes) --
    CURVED = False

    def doc_offset(self) -> tuple:
        return self.pos().x(), -self.pos().y()

    def prims(self) -> list:
        """Primitives de l'entite en coordonnees du document (place Qt comprise)."""
        return cad_shapes.prims(self.kind, self.data, self.doc_offset())

    def doc_bounds(self) -> tuple:
        return cad_shapes.bounds(self.prims())

    def outline(self, tol: float) -> list:
        """Segments [(a, b)] du trace (apercus : survol, fantomes)."""
        return cad_shapes.display_segments(self.prims(), tol)

    def geometry(self) -> dict:
        """Champs geometriques, place Qt repliee dedans."""
        data = self.to_dict()
        return {k: data[k] for k in cad_shapes.GEOMETRY_KEYS[self.kind]}

    def locked(self) -> bool:
        """Verrou du board OU calque verrouille : ni deplace, ni modifie, ni supprime (reste accrochable)."""
        return bool(self.data.get("locked", False)) or bool(self.props().get("locked"))

    # Proprietes, geometrie, verrou et visibilite calcules a l'entree dans la scene (`itemChange`) : `_add` n'a pas a
    # refaire `sync` (BoardScene._add).
    SYNCED_ON_ADD = True

    def _place_from_data(self):
        self._props = None
        if self.scene() is None:
            # Creation (`make_item`, juste avant `addItem`) : seulement la place. Proprietes (ByLayer), geometrie,
            # verrou et visibilite attendent l'entree dans la scene (SCENE_HAS_CHANGED, avec les VRAIS calques) :
            # calcules ici avec une page vide, puis refaits, ils coutaient ~3 fois le necessaire a l'ouverture
            # d'un gros dessin (mesure, 81 000 entites : `sync` 224 000 fois, `resolve` 243 000 fois).
            self.setPos(float(self.data.get("x", 0.0)), float(self.data.get("y", 0.0)))
            z = float(self.data.get("z", 0.0))
            if z:                                   # 0 : deja la hauteur d'un element neuf (un appel d'itemChange)
                self.setZValue(z)
            return
        super()._place_from_data()
        self.setVisible(self.props()["visible"])
        self._touch(restyle=True)

    def page_changed(self):
        """Calques / echelle des types de ligne changes : proprietes effectives relues (ByLayer)."""
        old = self._props
        self._props = None
        props = self.props()
        if old is not None and all(old.get(k) == props.get(k) for k in STYLE_KEYS):
            return
        self.setFlag(QGraphicsItem.ItemIsMovable, not self.locked())
        if not props["visible"] and self.isSelected():
            self.setSelected(False)
        self.setVisible(props["visible"])
        self.sync()
        self._touch(restyle=True)
        self.update()

    def itemChange(self, change, value):
        if change in _items.QUIET_CHANGES:              # drapeaux, curseur... : rien a faire (creation ~10 fois)
            return value
        if change is _items.SELECTED_CHANGE and value and any(cad_module_look(self.scene())):
            return False                                # module CAD grise ou masque : jamais selectionne
        # Entree / sortie de scene : tout est fait ici, sans repasser par `BoardItem.itemChange` (meme regroupement
        # signale) ni par Qt (qui rend la valeur telle quelle) : deux appels de moins par entite creee.
        if change is _items.SCENE_CHANGE:
            old = self.scene()
            if old is not None and value is not old:
                if self._batch is not None:
                    self._batch.drop(self)
                layer = getattr(old, "cad_layer", None)
                if layer is not None:
                    layer.structure_changed()
                    layer.extras.pop(id(self), None)
                    layer.note_geometry(self, removed=True)    # quitte la scene : retire du dessin GPU
            return value
        if change is _items.SCENE_HAS_CHANGED:
            self._props = None
            if value is not None:
                # Creee sans contenu peint (ITEM_FLAGS). Rendu GPU : la scene ne la peint pas. Chargement par
                # tranches : peinte par son lot, forme a la fin (`CadLayer.bulk_loaded`) ; seule, chaque ligne se
                # peindrait une a une (~0,1 ms chacune a chaque image). Sinon elle se peint seule jusqu'au
                # regroupement (`CadLayer.rebuild`, boucle suivante).
                if (self._batch is None and not getattr(value, "cad_gpu", False)
                        and not getattr(value, "bulk_loading", False)
                        and self.flags() & QGraphicsItem.ItemHasNoContents):
                    self.setFlag(QGraphicsItem.ItemHasNoContents, False)
                movable = not self.locked()             # verrou et visibilite du calque (voir `_place_from_data`)
                if bool(self.flags() & QGraphicsItem.ItemIsMovable) != movable:
                    self.setFlag(QGraphicsItem.ItemIsMovable, movable)
                self.setVisible(self.props()["visible"])
            self.sync()
            if value is not None:
                layer = CadLayer.of(value)
                layer.structure_changed()
                if getattr(self, "TEXTED", False):
                    layer.extras[id(self)] = self
                layer.note_geometry(self)
            return value
        if change is _items.ZVALUE_HAS_CHANGED:
            if self._batch is not None:
                self._batch.drop(self)              # se peint seule a sa nouvelle hauteur jusqu'au regroupement
        elif change is _items.POSITION_HAS_CHANGED:
            self._scene_geom = {}
            self._touch()
        elif change is _items.VISIBLE_HAS_CHANGED or change is _items.VISIBLE_CHANGE:
            # Qt « polit » tout element ajoute (boucle suivante) en lui renvoyant ces deux notifications, visibilite
            # inchangee : rien a refaire (sinon chaque ligne d'un gros dessin se reclassait dans son lot). Ni
            # `BoardItem` ni Qt n'en font rien.
            if change is _items.VISIBLE_HAS_CHANGED and bool(value) != self._shown:
                self._shown = bool(value)
                self._touch(restyle=True)
            return value
        elif change is _items.SELECTED_HAS_CHANGED:
            if self._batch is not None:
                self._batch.selection_changed(self)
        return super().itemChange(change, value)

    def _touch(self, restyle: bool = False):
        """Geometrie (ou aspect, `restyle`) changee : le lot qui peint cette ligne se met a jour, l'index des
        accrochages la reprendra."""
        if self._batch is not None:
            self._batch.member_changed(self, restyle)
        layer = getattr(self.scene(), "cad_layer", None)
        if layer is not None:
            layer.note_geometry(self)

    def zoom_changed(self):
        super().zoom_changed()
        if self._batch is not None:
            self._batch.zoom_changed()

    # -- geometrie locale (repere de l'element = scene sans la place) --
    def _local_points(self):
        p1, p2 = self.data.get("p1") or (0, 0), self.data.get("p2") or (0, 0)
        return (QPointF(float(p1[0]), -float(p1[1])), QPointF(float(p2[0]), -float(p2[1])))

    def sync(self):
        props = self.props() if self.scene() is not None else cad_model.resolve(self.data, cad_model.empty_cad_page())
        p1, p2 = self.data.get("p1") or (0, 0), self.data.get("p2") or (0, 0)
        ax, ay, bx, by = float(p1[0]), -float(p1[1]), float(p2[0]), -float(p2[1])     # repere local (Y vers le bas)
        weight = float(props["lineweight"])
        # Cle comparee par valeur (jamais hachee) : les extremites y entrent telles quelles, sans `repr` (copies
        # propres a `resolve`, jamais modifiees sur place).
        key = (ax, ay, bx, by, weight, props["end1"], props["end2"], props["inner"],
               tuple(props["pattern"]), props["ltscale"], props["extra"], props["distribute"], props["resize"])
        if key == self._geom_key:
            return
        self.prepareGeometryChange()
        self._geom_key = key
        self._dashed = None
        self._thin_dashes = None
        self._scene_geom = {}
        length = math.hypot(bx - ax, by - ay)
        self._length = length
        half = weight / 2.0
        end1, end2, inner = props["end1"], props["end2"], props["inner"]
        pattern = props["pattern"]
        transform = None                        # seulement pour un contour (trait epais) ou un motif
        if half > 0 or pattern:
            transform = QTransform()
            transform.translate(ax, ay)
            transform.rotate(math.degrees(math.atan2(by - ay, bx - ax)) if length > geo.EPS else 0.0)
        self._transform = transform
        self._outline = transform.map(line_outline(length, half, end1, end2)) if half > 0 else QPainterPath()
        if pattern:
            scale, offset, span = pattern_layout(props, length)
            intervals = geo.dash_intervals(span, pattern, scale, dot_length=weight, limit=MAX_DASHES)
            if intervals is not None and offset:
                intervals = [(u0 + offset, u1 + offset) for u0, u1 in intervals]
            if intervals is not None:
                self._intervals = intervals
                if half > 0:
                    self._dashed = transform.map(dashed_outline(intervals, length, half, end1, end2, inner))
                self._thin_dashes = intervals
            self._period = cad_model.pattern_period(pattern) * scale
        else:
            self._period = 0.0
        x0, x1 = (ax, bx) if ax <= bx else (bx, ax)
        y0, y1 = (ay, by) if ay <= by else (by, ay)
        rect = QRectF(x0 - 1.0, y0 - 1.0, x1 - x0 + 2.0, y1 - y0 + 2.0)
        self._bounds = self._outline.boundingRect().adjusted(-1.0, -1.0, 1.0, 1.0).united(rect) if half > 0 else rect
        scene = self.scene()
        if scene is not None and hasattr(scene, "fit_index"):
            scene.fit_index(self.scene_bounds())
        self._touch(restyle=True)

    def content_rect(self) -> QRectF:
        return self._bounds

    def size(self):
        return 0.0, 0.0

    def _apply_rotation(self):
        pass

    def _grip_px(self) -> float:
        return float(getattr(self.scene(), "cad_grip_px", GRIP_PX) or GRIP_PX)

    def boundingRect(self) -> QRectF:
        if self.isSelected():
            m = (self._grip_px() + 4) / self._zoom()
            return self._bounds.adjusted(-m, -m, m, m)
        return self._bounds

    def shape(self) -> QPainterPath:
        a, b = self._local_points()
        axis = QPainterPath(a)
        axis.lineTo(b)
        stroker = QPainterPathStroker()
        stroker.setWidth(float(self.props()["lineweight"]) + 10.0 / self._zoom())
        stroker.setCapStyle(Qt.RoundCap)
        return stroker.createStroke(axis)

    # -- accrochages / selection (coordonnees du document) --
    def snap_primitives(self):
        a, b = self.points()
        return [("segment", a, b)]

    def distance_to(self, p) -> float:
        a, b = self.points()
        return geo.distance_point_segment(p, a, b)

    def grips(self) -> list[tuple[str, tuple]]:
        a, b = self.points()
        return [("p1", a), ("mid", geo.midpoint(a, b)), ("p2", b)]

    # -- dessin --
    def _dense_px(self) -> float:
        return float(getattr(self.scene(), "cad_dense_px", DENSE_PX) or DENSE_PX)

    def draw_key(self, zoom: float) -> tuple:
        """Facon de peindre a ce zoom : (trait fin ?, motif trop serre ?, couleur) ; meme regle que `paint`."""
        props = self.props()
        return (float(props["lineweight"]) * zoom < 1.0, self._period > 0 and self._period * zoom < self._dense_px(),
                props["color"])

    def thresholds(self) -> list:
        """Zooms ou `draw_key` change (trait fin <-> epais, motif serre <-> dessine)."""
        out = []
        weight = float(self.props()["lineweight"])
        if weight > 0:
            out.append(1.0 / weight)
        if self._period > 0:
            out.append(self._dense_px() / self._period)
        return out

    def scene_geom(self, thin: bool, dense: bool):
        """Geometrie a peindre dans le repere de la SCENE (place Qt comprise), gardee jusqu'au prochain
        changement : trait fin = (segments, points), trait epais = chemin du contour."""
        key = (thin, dense)
        found = self._scene_geom.get(key)
        if found is not None:
            return found
        ox, oy = self.pos().x(), self.pos().y()
        if thin:
            if self._thin_dashes is not None and not dense:
                lines, dots = [], []
                for u0, u1 in self._thin_dashes:
                    if u1 - u0 <= geo.EPS:
                        p = self._transform.map(QPointF((u0 + u1) / 2, 0))
                        dots.append(QPointF(p.x() + ox, p.y() + oy))
                    else:
                        a = self._transform.map(QPointF(u0, 0))
                        b = self._transform.map(QPointF(u1, 0))
                        lines.append(QLineF(a.x() + ox, a.y() + oy, b.x() + ox, b.y() + oy))
                found = (lines, dots)
            else:
                a, b = self._local_points()
                found = ([QLineF(a.x() + ox, a.y() + oy, b.x() + ox, b.y() + oy)], [])
        else:
            path = self._dashed if (self._dashed is not None and not dense) else self._outline
            found = path.translated(ox, oy)
        self._scene_geom[key] = found
        return found

    def scene_bounds(self) -> QRectF:
        return self._bounds.translated(self.pos())

    def paint(self, painter, option, widget=None):
        option.state = option.state & ~QStyle.State_Selected
        thin, dense, color = self.draw_key(self._zoom())
        scene = self.scene()
        if getattr(scene, "cad_gpu", False) and not getattr(scene, "exporting", False):
            return                                   # rendu GPU (cad_gpu) : la scene ne peint pas les entites CAD
        hidden, faded = cad_module_look(self.scene())
        if hidden:
            return                                       # module CAD masque (selecteur de modules du board)
        if faded:
            painter.setOpacity(painter.opacity() * FADE_OPACITY)
            color = fade_ink(color)
        painter.setRenderHint(QPainter.Antialiasing, bool(getattr(scene, "cad_antialiasing", True)))
        crisp = bool(getattr(scene, "cad_crisp", True))
        geometry = self.scene_geom(thin, dense)          # repere de la scene : meme dessin que dans un lot
        cache = (PixelLines(geometry[0]), geometry[1]) if thin else geometry
        painter.save()
        painter.translate(-self.pos())
        target = linear_target(painter, scene)
        if target is None or not draw_geometry_linear(painter, thin, color, cache, self.scene_bounds(), crisp, target):
            draw_geometry(painter, thin, color, cache, crisp)
        painter.restore()
        self.paint_selection(painter)

    def paint_selection(self, painter):
        if not self.isSelected():
            return
        accent = QColor(getattr(self.scene(), "accent", GRIP_COLOR))
        a, b = self._local_points()
        halo = QColor(accent)
        halo.setAlpha(110)
        pen = QPen(halo, 3.0, Qt.DashLine)
        pen.setCosmetic(True)
        painter.setPen(pen)
        painter.setBrush(Qt.NoBrush)
        painter.drawLine(a, b)
        if getattr(self.scene(), "cad_show_grips", True) and not self.locked():
            self._paint_grips(painter, (a, QPointF((a.x() + b.x()) / 2, (a.y() + b.y()) / 2), b))

    def _paint_grips(self, painter, points):
        scene = self.scene()
        paint_grips(painter, points, self._grip_px(), getattr(scene, "cad_grip_color", GRIP_COLOR),
                    getattr(scene, "cad_grip_border", GRIP_BORDER))


class CadCurveItem(CadLineItem):
    """Arc (`cad_arc`), cercle (`cad_circle`), polyligne (`cad_pline`) : memes proprietes, calques, motifs,
    selection, accrochage et dessin GROUPE que les lignes (la classe en herite) ; seule la geometrie change
    (primitives de cad_shapes). Traits fins : courbes TESSELLEES en petits traits (un seul `drawLines` dans le lot),
    a la finesse du zoom en cours (`tess_band`, refaite a la fin d'un zoom seulement) ; traits epais : chemins
    EXACTS (arcs de Qt) — la meme geometrie a tout zoom."""

    CURVED = True

    def to_dict(self) -> dict:
        data = copy.deepcopy(self.data)
        ox, oy = self.doc_offset()
        if ox or oy:
            data.update(cad_shapes.translated(self.kind, data, (ox, oy)))
        data["x"], data["y"] = 0.0, 0.0
        data["z"] = self.zValue()
        return data

    def points(self) -> tuple[tuple, tuple]:
        """Debut et fin du trace (pour un cercle : deux fois le meme point)."""
        primitives = self.prims()
        return cad_shapes.prim_start(primitives[0]), cad_shapes.prim_end(primitives[-1])

    def length(self) -> float:
        return cad_shapes.total_length(self.prims())

    def angle(self) -> float:
        return 0.0

    def closed(self) -> bool:
        return self.kind == "cad_circle" or (self.kind == "cad_pline" and bool(self.data.get("closed"))
                                             and len(self.data.get("vertices") or []) > 2)

    def _local_prims(self):
        return cad_shapes.prims(self.kind, self.data)

    def sync(self):
        props = self.props() if self.scene() is not None else cad_model.resolve(self.data, cad_model.empty_cad_page())
        primitives = self._local_prims()
        weight = float(props["lineweight"])
        key = (repr(primitives), weight, repr(props["end1"]), repr(props["end2"]), repr(props["inner"]),
               tuple(props["pattern"]), props["ltscale"], props["extra"], props["distribute"], props["resize"])
        if key == self._geom_key:
            return
        self.prepareGeometryChange()
        self._geom_key = key
        self._dashed = None
        self._thin_dashes = None
        self._scene_geom = {}
        self._prims_local = primitives
        self._center = scene_path(primitives)
        closed = self.closed()
        if closed:
            self._center.closeSubpath()
        length = cad_shapes.total_length(primitives)
        self._length = length
        half = weight / 2.0
        end1, end2, inner = props["end1"], props["end2"], props["inner"]
        self._outline = stroke_outline(primitives, half, None if closed else end1, None if closed else end2,
                                       closed) if half > 0 else QPainterPath()
        pattern = props["pattern"]
        self._period = 0.0
        if pattern and length > geo.EPS:
            scale, offset, span = pattern_layout(props, length)
            intervals = geo.dash_intervals(span, pattern, scale, dot_length=weight, limit=MAX_DASHES)
            if intervals is not None and offset:
                intervals = [(u0 + offset, u1 + offset) for u0, u1 in intervals]
            if intervals is not None:
                self._thin_dashes = intervals
                if half > 0:
                    dashed = QPainterPath()
                    dashed.setFillRule(Qt.WindingFill)
                    for u0, u1 in intervals:
                        part = cad_shapes.sub_prims(primitives, u0, max(u1, u0 + geo.EPS))
                        if not part:
                            continue
                        first = end1 if (u0 <= geo.EPS and not closed) else inner
                        last = end2 if (u1 >= length - geo.EPS and not closed) else inner
                        dashed.addPath(stroke_outline(part, half, first, last, False))
                    self._dashed = dashed
            self._period = cad_model.pattern_period(pattern) * scale
        center_rect = self._center.boundingRect()
        self._bounds = (self._outline.boundingRect().united(center_rect) if half > 0 else center_rect) \
            .adjusted(-1.0, -1.0, 1.0, 1.0)
        scene = self.scene()
        if scene is not None and hasattr(scene, "fit_index"):
            scene.fit_index(self.scene_bounds())
        self._touch(restyle=True)

    def shape(self) -> QPainterPath:
        stroker = QPainterPathStroker()
        stroker.setWidth(float(self.props()["lineweight"]) + 10.0 / self._zoom())
        stroker.setCapStyle(Qt.RoundCap)
        return stroker.createStroke(self._center)

    def scene_geom(self, thin: bool, dense: bool):
        """Comme la ligne ; les traits fins des courbes dependent de la finesse du zoom (`tess_band`)."""
        band = tess_band(self.scene()) if thin else 0.0
        key = (thin, dense, band)
        found = self._scene_geom.get(key)
        if found is not None:
            return found
        if thin and any(k[0] and k[2] != band for k in self._scene_geom):
            self._scene_geom = {k: v for k, v in self._scene_geom.items() if not k[0]}   # ancienne finesse
        ox, oy = self.pos().x(), self.pos().y()
        if thin:
            tol = 0.25 / band
            pieces = []
            dots = []
            if self._thin_dashes is not None and not dense:
                for u0, u1 in self._thin_dashes:
                    if u1 - u0 <= geo.EPS:
                        q = cad_shapes.prim_point(*self._locate(u0))
                        dots.append(QPointF(q[0] + ox, -q[1] + oy))
                    else:
                        pieces += cad_shapes.tessellate(cad_shapes.sub_prims(self._prims_local, u0, u1), tol)
            else:
                pieces = cad_shapes.tessellate(self._prims_local, tol)
            lines = [QLineF(pts[i][0] + ox, -pts[i][1] + oy, pts[i + 1][0] + ox, -pts[i + 1][1] + oy)
                     for pts in pieces for i in range(len(pts) - 1)]
            found = (lines, dots)
        else:
            path = self._dashed if (self._dashed is not None and not dense) else self._outline
            found = path.translated(ox, oy)
        self._scene_geom[key] = found
        return found

    def _locate(self, u: float):
        """(primitive, distance dans elle) du point a la distance curviligne `u`."""
        pos = 0.0
        for p in self._prims_local:
            n = cad_shapes.prim_length(p)
            if u <= pos + n or p is self._prims_local[-1]:
                return p, max(0.0, min(n, u - pos))
            pos += n
        return self._prims_local[0], 0.0

    def paint_selection(self, painter):
        if not self.isSelected():
            return
        accent = QColor(getattr(self.scene(), "accent", GRIP_COLOR))
        halo = QColor(accent)
        halo.setAlpha(110)
        pen = QPen(halo, 3.0, Qt.DashLine)
        pen.setCosmetic(True)
        painter.setPen(pen)
        painter.setBrush(Qt.NoBrush)
        painter.drawPath(self._center)
        if getattr(self.scene(), "cad_show_grips", True) and not self.locked():
            self._paint_grips(painter, [QPointF(p[0], -p[1]) for _name, p in cad_shapes.grips(self.kind, self.data)])

    def snap_primitives(self):
        return self.prims()

    def distance_to(self, p) -> float:
        return cad_shapes.distance_to(self.prims(), p)

    def grips(self) -> list[tuple[str, tuple]]:
        return cad_shapes.grips(self.kind, self.data, self.doc_offset())


class _DimText(QGraphicsItem):
    """Texte d'une cotation : enfant de l'element (il le suit, disparait avec lui), pose au point bas-centre du texte,
    tourne comme la ligne de cote. Peint par la scene meme avec le rendu GPU (la couche GPU n'est jamais « pure CAD »
    quand une cotation existe, `TEXTED`)."""

    FONT_PX = 100.0                 # corps du dessin ; mis a l'echelle de la hauteur du texte (hauteur des capitales)
    CAP_RATIO = 0.72

    def __init__(self, parent):
        super().__init__(parent)
        self._text = ""
        self._height = 1.0
        self._rect = QRectF()
        self.setFlag(QGraphicsItem.ItemIsSelectable, False)
        self.setAcceptedMouseButtons(Qt.NoButton)
        self.setCacheMode(QGraphicsItem.NoCache)

    def _font(self) -> QFont:
        font = QFont("Segoe UI")
        font.setPixelSize(int(self.FONT_PX))
        return font

    def set_label(self, text: str, point, angle: float, height: float):
        """`point` : bas-centre du texte (document, relatif a l'element) ; `angle` : degres du document."""
        if (text, height) != (self._text, self._height):
            self.prepareGeometryChange()
            self._text, self._height = text, height
            metrics = QFontMetricsF(self._font())
            width = metrics.horizontalAdvance(text) if text else 0.0
            self._rect = QRectF(-width / 2.0 - 4.0, -metrics.ascent() - 4.0, width + 8.0,
                                metrics.ascent() + metrics.descent() + 8.0)
        self.setPos(point[0], -point[1])
        self.setRotation(-angle)
        self.update()

    def boundingRect(self) -> QRectF:
        scale = self._height / (self.FONT_PX * self.CAP_RATIO)
        r = self._rect
        return QRectF(r.x() * scale, r.y() * scale, r.width() * scale, r.height() * scale)

    def paint(self, painter, option, widget=None):
        parent = self.parentItem()
        if not self._text or parent is None:
            return
        if self._height * device_scale(painter) < TEXT_MIN_PX:
            return                                       # trop petit pour etre vu (cotes d'un plan vu en entier)
        hidden, faded = cad_module_look(self.scene())
        if hidden:
            return                                       # module CAD masque (selecteur de modules du board)
        if faded:
            painter.setOpacity(painter.opacity() * FADE_OPACITY)
        scale = self._height / (self.FONT_PX * self.CAP_RATIO)
        painter.save()
        painter.scale(scale, scale)
        painter.setRenderHint(QPainter.TextAntialiasing, True)
        painter.setFont(self._font())
        ink = parent.props()["color"]
        painter.setPen(QColor(fade_ink(ink) if faded else ink))
        painter.drawText(QPointF(self._rect.x() + 4.0, 0.0), self._text)      # ligne de base au point d'ancrage
        painter.restore()


class CadDimItem(CadCurveItem):
    """Cotation (`cad_dim`, voir cad_dims) : meme entite que les autres (calque, selection, accrochage, poignees,
    annulation…), ses traits sont des primitives (lignes d'attache, ligne de cote, fleches : un trait fin, jamais de
    motif) et son texte un enfant (`_DimText`)."""

    TEXTED = True

    def __init__(self, data: dict):
        self._text_item = None
        super().__init__(data)
        self._text_item = _DimText(self)
        self._update_text()

    def props(self) -> dict:
        props = super().props()
        if not props.get("_dim"):
            props = dict(props)
            props.update(pattern=(), end1=dict(cad_model.END_DEFAULT), end2=dict(cad_model.END_DEFAULT),
                         inner=dict(cad_model.END_DEFAULT), _dim=True)
            self._props = props
        return props

    def _update_text(self):
        if self._text_item is None:
            return
        found = cad_dims.geometry(self.data)
        self._text_item.set_label(found["text"], found["text_pos"], found["text_angle"], found["text_height"])

    def sync(self):
        self._update_text()
        super().sync()

    def snap_primitives(self):
        return []                               # le reticule ne s'aimante jamais sur une cotation (comme les hachures)

    def measured_text(self) -> str:
        return cad_dims.geometry(self.data)["text"]


# -- textes (TEXTE / MTEXTE, voir cad_text) ----------------------------------------------------------------------------
TEXT_FONT_PX = 100.0                # corps du dessin des textes, mis a l'echelle de leur hauteur de capitales
# Lettres plus petites a l'ecran (hauteur de capitales, pixels) : pas dessinees, invisibles de toute facon (un plan
# vu en entier : des centaines de textes de 0,01 pixel coutaient chacun un `drawText` a chaque image).
TEXT_MIN_PX = 0.75


def device_scale(painter) -> float:
    """Echelle du peintre vers l'ecran (pixels de l'appareil par unite locale)."""
    return math.sqrt(abs(painter.deviceTransform().determinant()))
_TEXT_METRICS: dict = {}


def text_font(family: str, bold: bool = False, italic: bool = False) -> QFont:
    font = QFont(family or cad_text.DEFAULT_FONT)
    font.setPixelSize(int(TEXT_FONT_PX))
    font.setBold(bool(bold))
    font.setItalic(bool(italic))
    return font


def text_metrics(family: str, bold: bool = False, italic: bool = False):
    """(mesures de la police, hauteur des capitales en pixels du corps, jambages en hauteurs) ; gardees par police."""
    key = (family, bool(bold), bool(italic))
    found = _TEXT_METRICS.get(key)
    if found is None:
        metrics = QFontMetricsF(text_font(family, bold, italic))
        cap = max(1e-3, metrics.capHeight() or metrics.ascent() * 0.7)
        found = (metrics, cap)
        _TEXT_METRICS[key] = found
    return found


def _qt_measure(text: str, family: str = "", bold: bool = False, italic: bool = False) -> float:
    """Largeur d'une ligne pour une hauteur de capitales de 1 (vraie mesure de la police : `cad_text.MEASURE`)."""
    if QGuiApplication.instance() is None:
        return cad_text._estimate(text, family, bold, italic)
    metrics, cap = text_metrics(family, bold, italic)
    return metrics.horizontalAdvance(text) / cap if text else 0.0


cad_text.MEASURE = _qt_measure


class _TextLabel(QGraphicsItem):
    """Lettres d'un texte CAD : enfant de l'element (il le suit, disparait avec lui), pose au point d'insertion et
    tourne comme la ligne de base. Peint par la scene, aussi avec le rendu GPU (comme le texte des cotations : enfant
    `_text_item`, voir `BoardView._paint_gpu_texts`)."""

    def __init__(self, parent):
        super().__init__(parent)
        self._found = None
        self._rect = QRectF()
        self.setFlag(QGraphicsItem.ItemIsSelectable, False)
        self.setAcceptedMouseButtons(Qt.NoButton)
        self.setCacheMode(QGraphicsItem.NoCache)

    def set_layout(self, found: dict):
        x0, y0, x1, y1 = found["box"]
        h = found["height"]
        rect = QRectF(x0 - h * 0.3, -y1 - h * 0.3, x1 - x0 + h * 0.6, y1 - y0 + h * 0.6)
        if rect != self._rect:
            self.prepareGeometryChange()
            self._rect = rect
        self._found = found
        self.setPos(found["origin"][0], -found["origin"][1])
        self.setRotation(-found["rot"])
        self.update()

    def boundingRect(self) -> QRectF:
        return self._rect

    def paint(self, painter, option, widget=None):
        parent = self.parentItem()
        found = self._found
        if found is None or parent is None or not found["lines"]:
            return
        if found["height"] * device_scale(painter) < TEXT_MIN_PX:
            return                                       # trop petit pour etre vu
        hidden, faded = cad_module_look(self.scene())
        if hidden:
            return                                       # module CAD masque (selecteur de modules du board)
        if faded:
            painter.setOpacity(painter.opacity() * FADE_OPACITY)
        style = found["style"]
        _metrics, cap = text_metrics(style["font"], style["bold"], style["italic"])
        k = found["height"] / cap
        painter.save()
        painter.scale(k, k)
        painter.setRenderHint(QPainter.TextAntialiasing, True)
        painter.setRenderHint(QPainter.Antialiasing, True)
        painter.setFont(text_font(style["font"], style["bold"], style["italic"]))
        ink = parent.props()["color"]
        painter.setPen(QColor(fade_ink(ink) if faded else ink))
        for line, x, y in found["lines"]:
            if line:
                painter.drawText(QPointF(x / k, -y / k), line)
        painter.restore()


class CadPointItem(CadCurveItem):
    """Point (`cad_point`, voir cad_point) : sa figure (PDMODE / PDSIZE) est faite de primitives ordinaires (lots, GPU,
    choix au clic) ; l'accrochage ne voit que le point (extremite) ; poignee unique a sa position (deplace)."""

    def props(self) -> dict:
        props = super().props()
        if not props.get("_flat"):
            props = dict(props)
            props.update(pattern=(), end1=dict(cad_model.END_DEFAULT), end2=dict(cad_model.END_DEFAULT),
                         inner=dict(cad_model.END_DEFAULT), _flat=True)
            self._props = props
        return props

    def snap_primitives(self):
        return cad_point.snap_prims(self.data, self.doc_offset())

    def points(self) -> tuple[tuple, tuple]:
        p = cad_point.position(self.data, self.doc_offset())
        return p, p

    def length(self) -> float:
        return 0.0

    def closed(self) -> bool:
        return False


class _InsertTexts(QGraphicsItem):
    """Textes d'une reference de bloc (`cad_insert`) : enfant `_text_item` de l'element (peint par la scene, et par la
    couche GPU en mode pur comme les autres textes : `BoardView._paint_gpu_texts`)."""

    def __init__(self, parent):
        super().__init__(parent)
        self._found = []
        self._masks = QPainterPath()            # masques (WIPEOUT) du bloc : couleur du fond, sous les textes
        self._rect = QRectF()
        self.setFlag(QGraphicsItem.ItemIsSelectable, False)
        self.setAcceptedMouseButtons(Qt.NoButton)
        self.setCacheMode(QGraphicsItem.NoCache)

    def set_texts(self, texts, masks=()):
        found = [(cad_text.layout(data), data.get("color")) for data in texts]
        path = QPainterPath()
        path.setFillRule(Qt.WindingFill)
        for loops in masks:
            for loop in loops:
                path.moveTo(loop[0][0], -loop[0][1])
                for x, y in loop[1:]:
                    path.lineTo(x, -y)
                path.closeSubpath()
        self._masks = path
        rect = path.boundingRect() if masks else QRectF()
        for layout, _color in found:
            x0, y0, x1, y1 = cad_text.bounds(layout)
            rect = rect.united(QRectF(x0, -y1, x1 - x0, y1 - y0))
        if rect != self._rect:
            self.prepareGeometryChange()
            self._rect = rect
        self._found = found
        self.update()

    def boundingRect(self) -> QRectF:
        return self._rect.adjusted(-1.0, -1.0, 1.0, 1.0)

    def paint(self, painter, option, widget=None):
        parent = self.parentItem()
        if (not self._found and self._masks.isEmpty()) or parent is None:
            return
        hidden, faded = cad_module_look(self.scene())
        if hidden:
            return
        if not self._masks.isEmpty():
            painter.setPen(Qt.NoPen)
            painter.setBrush(QColor(getattr(self.scene(), "background", QColor("#ffffff"))))
            painter.drawPath(self._masks)
        if faded:
            painter.setOpacity(painter.opacity() * FADE_OPACITY)
        own = parent.props()["color"]
        scale = device_scale(painter)
        painter.setRenderHint(QPainter.TextAntialiasing, True)
        painter.setRenderHint(QPainter.Antialiasing, True)
        for found, color in self._found:
            if not found["lines"] or found["height"] * scale < TEXT_MIN_PX:
                continue
            ink = own if color in (None, cad_model.BYLAYER) or not isinstance(color, str) else color
            style = found["style"]
            _metrics, cap = text_metrics(style["font"], style["bold"], style["italic"])
            k = found["height"] / cap
            painter.save()
            painter.translate(found["origin"][0], -found["origin"][1])
            painter.rotate(-found["rot"])
            painter.scale(k, k)
            painter.setFont(text_font(style["font"], style["bold"], style["italic"]))
            painter.setPen(QColor(fade_ink(ink) if faded else ink))
            for line, x, y in found["lines"]:
                if line:
                    painter.drawText(QPointF(x / k, -y / k), line)
            painter.restore()


class _InsertFills(QGraphicsItem):
    """Remplissages PLEINS des hachures d'une reference de bloc : enfant `_fill` (sous les traits ; couche GPU :
    `BoardView._paint_gpu_under`)."""

    def __init__(self, parent):
        super().__init__(parent)
        self._paths = []
        self._solid = False
        self.setAcceptedMouseButtons(Qt.NoButton)
        self.setCacheMode(QGraphicsItem.NoCache)
        self.setFlag(QGraphicsItem.ItemStacksBehindParent, True)

    def set_fills(self, fills):
        paths = []
        for loops, alpha, color, *more in fills:
            path = QPainterPath()
            path.setFillRule(Qt.OddEvenFill)
            for loop in loops:
                path.moveTo(loop[0][0], -loop[0][1])
                for x, y in loop[1:]:
                    path.lineTo(x, -y)
                path.closeSubpath()
            paths.append((path, alpha / 100.0, color, more[0] if more else None))
        self.prepareGeometryChange()
        self._paths = paths
        self._solid = bool(paths)
        self.update()

    def boundingRect(self) -> QRectF:
        rect = QRectF()
        for path, _a, _c, _g in self._paths:
            rect = rect.united(path.boundingRect())
        return rect.adjusted(-1.0, -1.0, 1.0, 1.0)

    def paint(self, painter, option, widget=None):
        parent = self.parentItem()
        if not self._paths or parent is None:
            return
        hidden, faded = cad_module_look(self.scene())
        if hidden:
            return
        if faded:
            painter.setOpacity(painter.opacity() * FADE_OPACITY)
        own = parent.props()["color"]
        painter.setPen(Qt.NoPen)
        for path, alpha, color, gradient in self._paths:
            ink = own if color in (None, cad_model.BYLAYER) or not isinstance(color, str) else color
            fill = QColor(fade_ink(ink) if faded else ink)
            fill.setAlphaF(alpha)
            if gradient is not None:
                second = QColor(fade_ink(gradient["color2"]) if faded else gradient["color2"])
                second.setAlphaF(alpha)
                painter.setBrush(gradient_brush(gradient, path.boundingRect(), fill, second))
            else:
                painter.setBrush(fill)
            painter.drawPath(path)


class _InsertStrokes(QGraphicsItem):
    """Traits d'une reference de bloc d'une AUTRE encre que la sienne (couleur / epaisseur propres des entites du
    bloc) : enfant `_strokes`, peint par QPainter hors du mode GPU (sinon : instances de la couche GPU,
    `cad_gpu.item_instances` lit `_ink_groups`)."""

    def __init__(self, parent):
        super().__init__(parent)
        self._groups = []
        self._rect = QRectF()
        self.setAcceptedMouseButtons(Qt.NoButton)
        self.setCacheMode(QGraphicsItem.NoCache)

    def set_groups(self, groups):
        built, rect = [], QRectF()
        for ink, weight, prims in groups:
            path = scene_path(prims)
            built.append((QColor(ink), float(weight), path))
            rect = rect.united(path.boundingRect().adjusted(-weight, -weight, weight, weight))
        if rect != self._rect:
            self.prepareGeometryChange()
            self._rect = rect
        self._groups = built
        self.update()

    def boundingRect(self) -> QRectF:
        return self._rect.adjusted(-1.0, -1.0, 1.0, 1.0)

    def paint(self, painter, option, widget=None):
        scene = self.scene()
        if not self._groups or (getattr(scene, "cad_gpu", False) and not getattr(scene, "exporting", False)):
            return
        hidden, faded = cad_module_look(scene)
        if hidden:
            return
        if faded:
            painter.setOpacity(painter.opacity() * FADE_OPACITY)
        painter.setRenderHint(QPainter.Antialiasing, bool(getattr(scene, "cad_antialiasing", True)))
        painter.setBrush(Qt.NoBrush)
        scale = device_scale(painter)
        for ink, weight, path in self._groups:
            color = QColor(fade_ink(ink.name())) if faded else ink
            if weight * scale < 1.0:
                pen = QPen(color, 1.0)
                pen.setCosmetic(True)
            else:
                pen = QPen(color, weight, Qt.SolidLine, Qt.FlatCap, Qt.MiterJoin)
            painter.setPen(pen)
            painter.drawPath(path)


class CadInsertItem(CadCurveItem):
    """Reference de bloc (`cad_insert`, voir cad_block) : une entite comme les autres (calque, couleur, selection,
    poignee au point d'insertion, deplacement, rotation, miroir, echelle, copie, annulation). Ses traits = ceux de
    toutes les entites du bloc transformees (un lot / des instances GPU) ; ses textes et pleins : enfants
    `_text_item` / `_fill`. Accrochable sur la geometrie du bloc et au point d'insertion."""

    TEXTED = True

    def __init__(self, data: dict):
        self._parts = None
        self._parts_key = None
        self._text_item = None
        self._fill = None
        self._strokes = None
        self._ink_groups = []               # [(couleur, epaisseur, primitives)] des traits d'une autre encre
        self._ink_key = None
        self._ink_main = None
        super().__init__(data)
        self._text_item = _InsertTexts(self)
        self._fill = _InsertFills(self)
        self._strokes = _InsertStrokes(self)
        self._update_children()

    def props(self) -> dict:
        props = super().props()
        if not props.get("_flat"):
            props = dict(props)
            props.update(pattern=(), end1=dict(cad_model.END_DEFAULT), end2=dict(cad_model.END_DEFAULT),
                         inner=dict(cad_model.END_DEFAULT), _flat=True)
            self._props = props
        return props

    def block_parts(self) -> dict:
        """Parties de la reference dans le repere LOCAL de l'element (place Qt non comprise), gardees tant que ni la
        reference ni la definition du bloc ne changent."""
        scene = self.scene()
        cad = cad_model.page_cad(scene.page) if scene is not None and hasattr(scene, "page") else {}
        definition = cad_block.blocks(cad).get(str(self.data.get("block") or ""))
        key = (id(definition), cad_block.signature(cad, self.data) if definition is not None else None,
               tuple(repr(self.data.get(k)) for k in cad_block.DRAWN_KEYS))
        if key != self._parts_key or self._parts is None:
            self._parts_key = key
            if definition is None:
                self._parts = {"prims": [], "strokes": {}, "texts": [], "fills": [], "count": 0}
            else:
                self._parts = cad_block.parts(cad, self.data, unit_of(scene, cad) if scene is not None else 1.0)
        return self._parts

    def _inks(self):
        """(traits de l'encre de la reference, [(couleur, epaisseur, traits)] des autres encres)."""
        found = self.block_parts()
        props = self.props() if self.scene() is not None else None
        own = (str(props["color"]).lower(), float(props["lineweight"])) if props is not None else None
        key = (id(found), own)
        if key != self._ink_key or self._ink_main is None:
            main, others = [], []
            for (ink, weight), prims in found.get("strokes", {}).items():
                if own is None or (str(ink).lower(), float(weight)) == own:
                    main.extend(prims)
                else:
                    others.append((ink, weight, prims))
            self._ink_key, self._ink_main, self._ink_groups = key, main, others
        return self._ink_main, self._ink_groups

    def page_changed(self):
        """Calques changes : la reference ET les entites de son bloc sur d'autres calques (couleur, epaisseur,
        visibilite) ; refaite seulement si son dessin change (`cad_block.signature`)."""
        old = self._parts
        changed = old is not None and self.block_parts() is not old
        if changed:
            self._geom_key = None
        super().page_changed()
        if changed:
            self.sync()
            self._touch(restyle=True)
            self.update()

    def refresh_block(self):
        """Definition du bloc changee (BLOC redefini) : la reference se redessine."""
        self._parts_key = None
        self._geom_key = None
        self.sync()

    def _local_prims(self):
        found = self._inks()[0]
        if found:
            return found
        p = cad_shapes._pt(self.data.get("pos"))
        return [("segment", p, p)]

    def prims(self) -> list:
        ox, oy = self.doc_offset()
        out = []
        found = self.block_parts()["prims"]
        if not found:
            p = cad_shapes._pt(self.data.get("pos"))
            found = [("segment", p, p)]
        for p in found:
            if p[0] == "segment":
                out.append(("segment", (p[1][0] + ox, p[1][1] + oy), (p[2][0] + ox, p[2][1] + oy)))
            else:
                out.append(("arc", (p[1][0] + ox, p[1][1] + oy)) + tuple(p[2:]))
        return out

    def snap_primitives(self):
        ox, oy = self.doc_offset()
        p = cad_shapes._pt(self.data.get("pos"))
        return self.prims() + [("segment", (p[0] + ox, p[1] + oy), (p[0] + ox, p[1] + oy))]

    def points(self) -> tuple[tuple, tuple]:
        ox, oy = self.doc_offset()
        p = cad_shapes._pt(self.data.get("pos"))
        return (p[0] + ox, p[1] + oy), (p[0] + ox, p[1] + oy)

    def length(self) -> float:
        return 0.0

    def closed(self) -> bool:
        return False

    def sync(self):
        super().sync()
        self._update_children()

    def _update_children(self):
        if self._text_item is None or self._fill is None:
            return
        found = self.block_parts()
        self._text_item.set_texts(found["texts"], found.get("masks", ()))
        self._fill.set_fills(found["fills"])
        if self._strokes is not None:
            self._strokes.set_groups(self._inks()[1])


IMAGE_MAX_PX = 4096                 # image lue au plus a cette taille (cote le plus long) : memoire bornee
_PICTURES: dict = {}                # chemin -> (date du fichier, QImage ou None) : chaque fichier lu une fois


def picture(path: str):
    """QImage du fichier (lue une fois, reduite a IMAGE_MAX_PX) ; None = absent ou illisible."""
    import os
    from PySide6.QtGui import QImageReader
    try:
        stamp = os.stat(path).st_mtime_ns
    except (OSError, ValueError):
        return None
    found = _PICTURES.get(path)
    if found is not None and found[0] == stamp:
        return found[1]
    reader = QImageReader(path)
    reader.setAutoTransform(True)
    size = reader.size()
    if size.isValid() and max(size.width(), size.height()) > IMAGE_MAX_PX:
        reader.setScaledSize(size.scaled(IMAGE_MAX_PX, IMAGE_MAX_PX, Qt.KeepAspectRatio))
    image = reader.read()
    image = None if image.isNull() else image
    if len(_PICTURES) > 64:
        _PICTURES.clear()
    _PICTURES[path] = (stamp, image)
    return image


class _ImagePicture(QGraphicsItem):
    """Image d'une entite `cad_image` : enfant `_fill` (peint SOUS les traits : par la scene, ou par la couche GPU,
    `BoardView._paint_gpu_under`). `_solid` faux = fichier absent (seul le cadre se voit)."""

    def __init__(self, parent):
        super().__init__(parent)
        self._image = None
        self._place = QTransform()
        self._rect = QRectF()
        self._solid = False
        self._opacity = 1.0
        self.setAcceptedMouseButtons(Qt.NoButton)
        self.setCacheMode(QGraphicsItem.NoCache)
        self.setFlag(QGraphicsItem.ItemStacksBehindParent, True)

    def set_picture(self, image, corners, opacity: float):
        """`corners` : coins (bas gauche, bas droit, haut droit, haut gauche) dans le repere LOCAL (document)."""
        self.prepareGeometryChange()
        self._image = image
        self._opacity = opacity
        p0, p1, _p2, p3 = [(x, -y) for x, y in corners]             # repere de la scene : Y vers le bas
        xs, ys = [c[0] for c in (p0, p1, _p2, p3)], [c[1] for c in (p0, p1, _p2, p3)]
        self._rect = QRectF(min(xs), min(ys), max(xs) - min(xs), max(ys) - min(ys))
        self._solid = image is not None
        if image is not None and image.width() > 0 and image.height() > 0:
            w, h = float(image.width()), float(image.height())
            right = ((p1[0] - p0[0]) / w, (p1[1] - p0[1]) / w)          # pixel (x, y) -> haut gauche + x u + y v
            down = ((p0[0] - p3[0]) / h, (p0[1] - p3[1]) / h)
            self._place = QTransform(right[0], right[1], down[0], down[1], p3[0], p3[1])
        self.update()

    def area_path(self) -> QPainterPath:
        path = QPainterPath()
        path.addRect(self._rect)
        return path

    def boundingRect(self) -> QRectF:
        return self._rect.adjusted(-1.0, -1.0, 1.0, 1.0)

    def paint(self, painter, option, widget=None):
        if self._image is None:
            return
        hidden, faded = cad_module_look(self.scene())
        if hidden:
            return
        painter.save()
        painter.setOpacity(painter.opacity() * self._opacity * (FADE_OPACITY if faded else 1.0))
        painter.setRenderHint(QPainter.SmoothPixmapTransform, True)
        painter.setTransform(self._place, True)
        painter.drawImage(0, 0, self._image)
        painter.restore()


class CadImageItem(CadCurveItem):
    """Image referencee (`cad_image`, voir cad_image) : une entite comme les autres (calque, selection, deplacement,
    rotation, miroir, echelle, copie, annulation). Son cadre = ses traits (accrochable, comme IMAGEFRAME 1) ; l'image
    un enfant `_fill` peint sous les traits ; on la choisit en cliquant dedans."""

    TEXTED = True                   # peinte en partie par la scene (enfant), comme les hachures
    AREA = True                     # choisie en cliquant dedans ; jamais arete de coupe ni contour de hachures

    def __init__(self, data: dict):
        self._fill = None
        self._reach = 0.0
        super().__init__(data)
        self._fill = _ImagePicture(self)
        self._update_picture()

    def props(self) -> dict:
        props = super().props()
        if not props.get("_flat"):
            props = dict(props)
            props.update(pattern=(), end1=dict(cad_model.END_DEFAULT), end2=dict(cad_model.END_DEFAULT),
                         inner=dict(cad_model.END_DEFAULT), _flat=True)
            self._props = props
        return props

    def _local_prims(self):
        return cad_image.prims(self.data)

    def points(self) -> tuple[tuple, tuple]:
        p = cad_image.corners(self.data, self.doc_offset())[0]
        return p, p

    def length(self) -> float:
        return 0.0

    def closed(self) -> bool:
        return False

    def distance_to(self, p) -> float:
        ox, oy = self.doc_offset()
        if cad_image.inside(self.data, (p[0] - ox, p[1] - oy)):
            return min(cad_shapes.distance_to(self.prims(), p), self._reach * 0.99)
        return cad_shapes.distance_to(self.prims(), p)

    def shape(self) -> QPainterPath:
        return self._fill.area_path() if self._fill is not None else super().shape()

    def sync(self):
        super().sync()
        self._update_picture()

    def _update_picture(self):
        if self._fill is None:
            return
        s = cad_image.style_of(self.data)
        image = picture(s["path"]) if s["path"] else None
        key = (id(image), repr(s))
        if key == getattr(self, "_picture_key", None):
            return                                      # rien de change : pas de prepareGeometryChange a chaque sync
        self._picture_key = key
        self._fill.set_picture(image, cad_image.corners(self.data), 1.0 - s["fade"] / 100.0)


def _visible_doc_rect(painter, margin: float = 0.0) -> tuple:
    """Rectangle (document, repere LOCAL de l'element : Y vers le haut) couvert par le peintre (zone decoupee, sinon
    toute la surface), elargi de `margin`."""
    if painter.hasClipping():
        local = painter.clipBoundingRect()
    else:
        device = painter.device()
        inverse, ok = painter.transform().inverted()
        local = inverse.mapRect(QRectF(0, 0, device.width(), device.height())) if ok else QRectF()
    local = local.adjusted(-margin, -margin, margin, margin)
    return local.left(), -local.bottom(), local.right(), -local.top()


class _XlinePaint(QGraphicsItem):
    """Dessin d'une ligne de construction : la droite DECOUPEE au rectangle peint (scene, ou passe des textes de la
    couche GPU), jamais tracee sur toute sa longueur de calcul."""

    def __init__(self, parent):
        super().__init__(parent)
        self._rect = QRectF()
        self._solid = True
        self.setAcceptedMouseButtons(Qt.NoButton)
        self.setCacheMode(QGraphicsItem.NoCache)

    def set_rect(self, rect: QRectF):
        if rect != self._rect:
            self.prepareGeometryChange()
            self._rect = rect

    def boundingRect(self) -> QRectF:
        return self._rect

    def paint(self, painter, option, widget=None):
        parent = self.parentItem()
        if parent is None:
            return
        hidden, faded = cad_module_look(self.scene())
        if hidden:
            return
        found = cad_xline.clip(parent.kind, parent.data, _visible_doc_rect(painter, 4.0))
        if found is None:
            return
        props = parent.props()
        color = QColor(fade_ink(props["color"]) if faded else props["color"])
        weight = float(props["lineweight"])
        if weight * device_scale(painter) < 1.0:
            pen = QPen(color, 1.0)
            pen.setCosmetic(True)
        else:
            pen = QPen(color, weight, Qt.SolidLine, Qt.FlatCap)
        if faded:
            painter.setOpacity(painter.opacity() * FADE_OPACITY)
        painter.setRenderHint(QPainter.Antialiasing, bool(getattr(self.scene(), "cad_antialiasing", True)))
        painter.setPen(pen)
        (x0, y0), (x1, y1) = found
        painter.drawLine(QPointF(x0, -y0), QPointF(x1, -y1))


class CadXlineItem(CadCurveItem):
    """Ligne de construction (`cad_xline` : droite ; `cad_ray` : demi-droite ; voir cad_xline) : une entite comme
    une ligne (calque, couleur, selection, poignees base / direction, deplacer, tourner, miroir, copie, ajuster...).
    Dessin : enfant `_text_item` (`_XlinePaint`) ; hors des lots et du GPU (`INFINITE`) ; son emprise pour le zoom
    etendu et l'index de la scene = ses deux points."""

    INFINITE = True
    TEXTED = True

    def __init__(self, data: dict):
        self._text_item = None
        super().__init__(data)
        self._text_item = _XlinePaint(self)
        self._update_paint()

    def props(self) -> dict:
        props = super().props()
        if not props.get("_flat"):
            props = dict(props)
            props.update(pattern=(), end1=dict(cad_model.END_DEFAULT), end2=dict(cad_model.END_DEFAULT),
                         inner=dict(cad_model.END_DEFAULT), _flat=True)
            self._props = props
        return props

    def _local_prims(self):
        return cad_xline.prims(self.kind, self.data)

    def closed(self) -> bool:
        return False

    def points(self) -> tuple[tuple, tuple]:
        ox, oy = self.doc_offset()
        a = cad_shapes._pt(self.data.get("p1"))
        b = cad_shapes._pt(self.data.get("p2"))
        return (a[0] + ox, a[1] + oy), (b[0] + ox, b[1] + oy)

    def scene_bounds(self) -> QRectF:
        """Ses deux points seulement (zoom etendu, etendue de la scene) : la droite est infinie."""
        a, b = (cad_shapes._pt(self.data.get(k)) for k in ("p1", "p2"))
        rect = QRectF(QPointF(min(a[0], b[0]), -max(a[1], b[1])), QPointF(max(a[0], b[0]), -min(a[1], b[1])))
        return rect.adjusted(-1.0, -1.0, 1.0, 1.0).translated(self.pos())

    def scene_rect(self) -> QRectF:
        return self.scene_bounds()

    def paint(self, painter, option, widget=None):
        pass                                            # l'enfant `_XlinePaint` dessine

    def outline(self, tol: float) -> list:
        """Survol / fantomes : le morceau visible (vue du board), pas les 2 x 10^7 unites du segment de calcul."""
        scene = self.scene()
        views = scene.views() if scene is not None else []
        if views:
            view = views[0]
            r = view.mapToScene(view.viewport().rect()).boundingRect()
            ox, oy = self.doc_offset()
            found = cad_xline.clip(self.kind, self.data, (r.left(), -r.bottom(), r.right(), -r.top()), (ox, oy))
            return [found] if found is not None else []
        return super().outline(tol)

    def paint_selection(self, painter):
        if not self.isSelected():
            return
        found = cad_xline.clip(self.kind, self.data, _visible_doc_rect(painter, 4.0))
        accent = QColor(getattr(self.scene(), "accent", GRIP_COLOR))
        halo = QColor(accent)
        halo.setAlpha(110)
        pen = QPen(halo, 3.0, Qt.DashLine)
        pen.setCosmetic(True)
        painter.setPen(pen)
        painter.setBrush(Qt.NoBrush)
        if found is not None:
            (x0, y0), (x1, y1) = found
            painter.drawLine(QPointF(x0, -y0), QPointF(x1, -y1))
        if getattr(self.scene(), "cad_show_grips", True) and not self.locked():
            a, b = (cad_shapes._pt(self.data.get(k)) for k in ("p1", "p2"))
            self._paint_grips(painter, (QPointF(a[0], -a[1]), QPointF(b[0], -b[1])))

    def sync(self):
        super().sync()
        self._update_paint()

    def _update_paint(self):
        if self._text_item is not None:
            self._text_item.set_rect(self._bounds)


class CadTextItem(CadCurveItem):
    """Texte (`cad_text`, voir cad_text) : une entite comme les autres (calque, couleur ByLayer, selection, poignee au
    point d'insertion, deplacement, copie, rotation, miroir, echelle, annulation…). Aucun trait : ses lettres sont un
    enfant (`_TextLabel`, attribut `_text_item`) ; on le choisit en cliquant dans son cadre. Jamais accrochable."""

    TEXTED = True

    def __init__(self, data: dict):
        self._text_item = None
        self._layout = None
        self._layout_key = None
        super().__init__(data)
        self._text_item = _TextLabel(self)
        self._update_text()

    def props(self) -> dict:
        props = super().props()
        if not props.get("_flat"):
            props = dict(props)
            props.update(pattern=(), lineweight=0.0, end1=dict(cad_model.END_DEFAULT),
                         end2=dict(cad_model.END_DEFAULT), inner=dict(cad_model.END_DEFAULT), _flat=True)
            self._props = props
        return props

    def layout(self) -> dict:
        """Mise en page en coordonnees LOCALES de l'element (place Qt non comprise), gardee tant que rien ne change."""
        data = self.data
        key = tuple(repr(data.get(k)) for k in ("text", "pos", "rot", "height", "width", "justify", "spacing", "font",
                                                 "bold", "italic"))
        if key != self._layout_key:
            self._layout_key = key
            self._layout = cad_text.layout(data)
        return self._layout

    def doc_layout(self) -> dict:
        ox, oy = self.doc_offset()
        if not ox and not oy:
            return self.layout()
        return cad_text.layout(self.data, (ox, oy))

    def text(self) -> str:
        return str(self.data.get("text") or "")

    def _local_prims(self):
        return []                               # aucun trait (ni dans les lots, ni sur le GPU)

    def prims(self) -> list:
        return [("segment", a, b) for a, b in cad_text.box_segments(self.doc_layout()["corners"])]

    def doc_bounds(self) -> tuple:
        return cad_text.bounds(self.doc_layout())

    def outline(self, tol: float) -> list:
        return cad_text.box_segments(self.doc_layout()["corners"])

    def snap_primitives(self):
        return []

    def points(self) -> tuple[tuple, tuple]:
        p = self.doc_layout()["origin"]
        return p, p

    def length(self) -> float:
        return 0.0

    def closed(self) -> bool:
        return False

    def distance_to(self, p) -> float:
        return cad_text.distance(self.doc_layout(), p)

    def _update_text(self):
        if self._text_item is not None:
            self._text_item.set_layout(self.layout())

    def sync(self):
        self._update_text()
        super().sync()
        corners = self.layout()["corners"]
        xs, ys = [c[0] for c in corners], [-c[1] for c in corners]
        bounds = QRectF(min(xs), min(ys), max(xs) - min(xs), max(ys) - min(ys)).adjusted(-1.0, -1.0, 1.0, 1.0)
        if bounds != self._bounds:
            self.prepareGeometryChange()
            self._bounds = bounds
            scene = self.scene()
            if scene is not None and hasattr(scene, "fit_index"):
                scene.fit_index(self.scene_bounds())
            self._touch()

    def _box_path(self) -> QPainterPath:
        corners = self.layout()["corners"]
        path = QPainterPath(QPointF(corners[0][0], -corners[0][1]))
        for x, y in corners[1:]:
            path.lineTo(x, -y)
        path.closeSubpath()
        return path

    def shape(self) -> QPainterPath:
        return self._box_path()

    def paint_selection(self, painter):
        if not self.isSelected():
            return
        accent = QColor(getattr(self.scene(), "accent", GRIP_COLOR))
        halo = QColor(accent)
        halo.setAlpha(150)
        pen = QPen(halo, 1.5, Qt.DashLine)
        pen.setCosmetic(True)
        painter.setPen(pen)
        painter.setBrush(Qt.NoBrush)
        painter.drawPath(self._box_path())
        if getattr(self.scene(), "cad_show_grips", True) and not self.locked():
            self._paint_grips(painter, [QPointF(p[0], -p[1]) for _name, p in cad_shapes.grips(self.kind, self.data)])


def gradient_brush(style: dict, rect: QRectF, color1: QColor, color2: QColor):
    """Pinceau d'un DEGRADE (`cad_hatch.GRADIENT`) sur `rect` (repere de la scene : Y vers le bas) : lineaire /
    cylindre / courbe le long de l'angle, sphere / hemisphere autour du centre (decale vers le bas pour l'hemisphere)."""
    from PySide6.QtGui import QLinearGradient, QRadialGradient
    name = style["gradient"]
    c = rect.center()
    base = name[3:] if name.startswith("INV") else name
    if base in ("SPHERICAL", "HEMISPHERICAL"):
        radius = max(1e-6, math.hypot(rect.width(), rect.height()) / 2.0)
        center = c if base == "SPHERICAL" or style["centered"] else QPointF(c.x(), rect.bottom())
        gradient = QRadialGradient(center, radius if base == "SPHERICAL" else radius * 1.4)
    else:
        a = math.radians(-style["angle"])
        dx, dy = math.cos(a), math.sin(a)
        half = abs(dx) * rect.width() / 2.0 + abs(dy) * rect.height() / 2.0
        gradient = QLinearGradient(c.x() - dx * half, c.y() - dy * half, c.x() + dx * half, c.y() + dy * half)
    for t, which in cad_hatch.gradient_stops(name):
        gradient.setColorAt(t, color1 if which == 1 else color2)
    return gradient


class _HatchFill(QGraphicsItem):
    """Remplissage PLEIN d'une hachure : enfant de l'element (peint par la scene, sous les traits)."""

    def __init__(self, parent):
        super().__init__(parent)
        self._path = QPainterPath()
        self._solid = False
        self._alpha = 1.0
        self._gradient = None           # style de la hachure si c'est un degrade
        self.setAcceptedMouseButtons(Qt.NoButton)
        self.setCacheMode(QGraphicsItem.NoCache)

    def set_area(self, loops, solid: bool, alpha: float, gradient: dict | None = None):
        self._gradient = gradient
        path = QPainterPath()
        path.setFillRule(Qt.OddEvenFill)
        for loop in loops:
            path.moveTo(loop[0][0], -loop[0][1])
            for x, y in loop[1:]:
                path.lineTo(x, -y)
            path.closeSubpath()
        if path != self._path or solid != self._solid:
            self.prepareGeometryChange()
        self._path, self._solid, self._alpha = path, solid, alpha / 100.0
        self.update()

    def area_path(self) -> QPainterPath:
        return self._path

    def boundingRect(self) -> QRectF:
        return self._path.boundingRect().adjusted(-1.0, -1.0, 1.0, 1.0)

    def paint(self, painter, option, widget=None):
        parent = self.parentItem()
        if not self._solid or parent is None or self._path.isEmpty():
            return
        hidden, faded = cad_module_look(self.scene())
        if hidden:
            return                                       # module CAD masque (selecteur de modules du board)
        if faded:
            painter.setOpacity(painter.opacity() * FADE_OPACITY)
        ink = parent.props()["color"]
        color = QColor(fade_ink(ink) if faded else ink)
        color.setAlphaF(self._alpha)
        painter.setPen(Qt.NoPen)
        if self._gradient is not None:
            second = QColor(fade_ink(self._gradient["color2"]) if faded else self._gradient["color2"])
            second.setAlphaF(self._alpha)
            painter.setBrush(gradient_brush(self._gradient, self._path.boundingRect(), color, second))
        else:
            painter.setBrush(color)
        painter.drawPath(self._path)


class _HatchMask(QGraphicsItem):
    """MASQUE (hachure de motif « wipeout », WIPEOUT d'AutoCAD) : la zone peinte de la couleur du FOND, PAR-DESSUS les
    traits (enfant `_text_item` : passe des textes de la couche GPU, masques peints avant les textes,
    `BoardView._paint_gpu_texts`). `_solid` faux pour une hachure ordinaire (rien a peindre)."""

    MASK = True

    def __init__(self, parent):
        super().__init__(parent)
        self._path = QPainterPath()
        self._solid = False
        self.setAcceptedMouseButtons(Qt.NoButton)
        self.setCacheMode(QGraphicsItem.NoCache)

    def set_area(self, path: QPainterPath, on: bool):
        if path != self._path or on != self._solid:
            self.prepareGeometryChange()
        self._path, self._solid = path, on
        self.update()

    def boundingRect(self) -> QRectF:
        return self._path.boundingRect().adjusted(-1.0, -1.0, 1.0, 1.0) if self._solid else QRectF()

    def paint(self, painter, option, widget=None):
        if not self._solid or self._path.isEmpty():
            return
        scene = self.scene()
        if cad_module_look(scene)[0]:
            return
        painter.setPen(Qt.NoPen)
        painter.setBrush(QColor(getattr(scene, "background", QColor("#ffffff"))))
        painter.drawPath(self._path)


class CadHatchItem(CadCurveItem):
    """Hachures (`cad_hatch`, voir cad_hatch) : une entite comme les autres (calque, selection, deplacement, rotation,
    miroir, annulation…). Ses traits sont des primitives en trait fin (un lot, GPU compris), le remplissage plein un
    enfant (`_HatchFill`) ; elle n'est jamais accrochable (comme AutoCAD) et se choisit en cliquant DANS la zone
    (sur le motif, ou n'importe ou si le remplissage est plein)."""

    TEXTED = True                   # peinte en partie par la scene : jamais le mode « pur CAD » du rendu GPU
    AREA = True

    def __init__(self, data: dict):
        self._fill = None
        self._text_item = None
        self._hatch_key = None
        self._loops_cache = []
        self._prims_cache = []
        self._reach = 0.0           # portee de selection du dernier clic (unites du document), posee par `pick_all`
        super().__init__(data)
        self._fill = _HatchFill(self)
        self._text_item = _HatchMask(self)
        self._update_fill()

    def props(self) -> dict:
        props = super().props()
        if not props.get("_flat"):
            props = dict(props)
            props.update(pattern=(), end1=dict(cad_model.END_DEFAULT), end2=dict(cad_model.END_DEFAULT),
                         inner=dict(cad_model.END_DEFAULT), _flat=True)
            self._props = props
        return props

    # -- geometrie (en cache : un motif compte des milliers de traits) --
    def _refresh_cache(self):
        key = (repr(self.data.get("loops")), self.data.get("hatch_pattern"), self.data.get("hatch_angle"),
               self.data.get("hatch_spacing"), repr(self.data.get("hatch_origin")), repr(self.data.get("hatch_lines")))
        if key != self._hatch_key:
            self._hatch_key = key
            self._loops_cache = cad_hatch.clean_loops(self.data.get("loops"))
            self._prims_cache = cad_hatch.prims(self.data)

    def _shifted(self, primitives):
        ox, oy = self.doc_offset()
        if not ox and not oy:
            return primitives
        return [("segment", (p[1][0] + ox, p[1][1] + oy), (p[2][0] + ox, p[2][1] + oy)) for p in primitives]

    def _local_prims(self):
        self._refresh_cache()
        return self._prims_cache

    def prims(self) -> list:
        self._refresh_cache()
        return self._shifted(self._prims_cache)

    def loops(self) -> list:
        """Contours en coordonnees du document (place Qt comprise)."""
        self._refresh_cache()
        ox, oy = self.doc_offset()
        return [[(x + ox, y + oy) for x, y in loop] for loop in self._loops_cache]

    def doc_bounds(self) -> tuple:
        box = cad_hatch.bounds(self.loops())
        return box

    def select_prims(self) -> list:
        return [("segment", a, b) for a, b in cad_hatch.boundary_segments(self.loops())]

    def outline(self, tol: float) -> list:
        return cad_hatch.boundary_segments(self.loops())

    def snap_primitives(self):
        return []

    def points(self) -> tuple[tuple, tuple]:
        loops = self.loops()
        p = loops[0][0] if loops else (0.0, 0.0)
        return p, p

    def length(self) -> float:
        return 0.0

    def distance_to(self, p) -> float:
        loops = self.loops()
        if not loops:
            return math.inf
        if not cad_hatch.inside(loops, p):
            return cad_hatch.distance_to_boundary(loops, p)
        ox, oy = self.doc_offset()
        inner = cad_hatch.distance_inside(self.data, (p[0] - ox, p[1] - oy))
        return inner if math.isfinite(inner) else self._reach * 0.99

    def sync(self):
        self._refresh_cache()
        super().sync()
        self._update_fill()
        if self._loops_cache:
            area = QRectF(*[0.0] * 4)
            box = cad_hatch.bounds(self._loops_cache)
            area = QRectF(box[0], -box[3], box[2] - box[0], box[3] - box[1]).adjusted(-1.0, -1.0, 1.0, 1.0)
            self._bounds = self._bounds.united(area)

    def _update_fill(self):
        if self._fill is not None:
            style = cad_hatch.style_of(self.data)
            self._fill.set_area(self._loops_cache, style["pattern"] in ("solid", cad_hatch.WIPEOUT, cad_hatch.GRADIENT),
                                style["alpha"], style if style["pattern"] == cad_hatch.GRADIENT else None)
            mask = style["pattern"] == cad_hatch.WIPEOUT
            if mask:
                self._fill._solid = False               # masque : peint au-dessus des traits, pas dessous
            if self._text_item is not None:
                self._text_item.set_area(self._fill.area_path(), mask)

    def shape(self) -> QPainterPath:
        return self._fill.area_path() if self._fill is not None else QPainterPath()

    def paint_selection(self, painter):
        if not self.isSelected():
            return
        accent = QColor(getattr(self.scene(), "accent", GRIP_COLOR))
        halo = QColor(accent)
        halo.setAlpha(150)
        pen = QPen(halo, 2.0, Qt.DashLine)
        pen.setCosmetic(True)
        painter.setPen(pen)
        painter.setBrush(Qt.NoBrush)
        painter.drawPath(self._fill.area_path())
        if getattr(self.scene(), "cad_show_grips", True) and not self.locked():
            self._paint_grips(painter, [QPointF(p[0], -p[1]) for _name, p in cad_shapes.grips(self.kind, self.data)])


# -- rendu a melange LINEAIRE (anticrenelage corrige du gamma) --------------------------------------------------------
# Qt calcule une couverture exacte des bords, mais melange trait et fond dans l'espace sRGB (valeurs gamma) : un bord
# couvert a 50 % d'un trait clair sur fond sombre sort a ~57 % de la luminance au lieu de ~74 % — les bords paraissent
# rognes, les arrondis en escalier (signale). Comme Skia / DirectWrite, on garde la couverture de Qt mais on la remappe
# pour que le melange soit juste en lumiere LINEAIRE : chaque liste de dessin (une couleur) est rasterisee en masque de
# couverture (un octet par pixel, anticrenele par Qt), puis posee par une table de 256 opacites calculee pour (couleur, fond).
# Table = zero copie : le masque est relu comme une image indexee.

def _to_linear(v: float) -> float:
    return v / 12.92 if v <= 0.04045 else ((v + 0.055) / 1.055) ** 2.4


def _to_srgb(v: float) -> float:
    return v * 12.92 if v <= 0.0031308 else 1.055 * v ** (1 / 2.4) - 0.055


def _luma(color: QColor) -> float:
    return 0.2126 * _to_linear(color.redF()) + 0.7152 * _to_linear(color.greenF()) + 0.0722 * _to_linear(color.blueF())


_LINEAR_TABLES: dict = {}


def linear_blend_table(color: str, background: QColor) -> list:
    """Table de couleurs (256 entrees ARGB) : couverture `i` -> `color` avec l'opacite qui donne, melangee en sRGB sur
    `background`, la luminance du melange lineaire. Couleurs de luminance voisine : opacite inchangee."""
    key = (color, background.rgba())
    table = _LINEAR_TABLES.get(key)
    if table is not None:
        return table
    ink = QColor(color)
    yb, yc = _luma(background), _luma(ink)
    lb, lc = _to_srgb(yb), _to_srgb(yc)
    rgb = ink.rgb() & 0xFFFFFF
    alpha = ink.alphaF()
    table = []
    for i in range(256):
        a = i / 255.0
        if abs(lc - lb) > 0.02:
            a = min(1.0, max(0.0, (_to_srgb(yb + a * (yc - yb)) - lb) / (lc - lb)))
        table.append((round(a * alpha * 255) << 24) | rgb)
    if len(_LINEAR_TABLES) > 256:
        _LINEAR_TABLES.clear()
    _LINEAR_TABLES[key] = table
    return table


def linear_target(painter, scene):
    """(zone de l'appareil, fond) quand le melange lineaire s'applique a ce painter, sinon None : anticrenelage et
    reglage allumes, appareil raster (ecran, image), jamais pendant un export."""
    device = painter.device()
    if (scene is None or device is None or not painter.testRenderHint(QPainter.Antialiasing)
            or not bool(getattr(scene, "cad_linear_blend", True)) or getattr(scene, "exporting", False)
            or device.devType() not in _RASTER_DEVICES):
        return None
    ratio = max(1.0, float(device.devicePixelRatioF()))
    rect = QRectF(0, 0, device.width(), device.height()) if device.devType() == 1 else \
        QRectF(0, 0, device.width() / ratio, device.height() / ratio)
    if painter.hasClipping():
        rect = rect.intersected(painter.worldTransform().mapRect(painter.clipBoundingRect()))
    return rect, QColor(getattr(scene, "background", QColor("#ffffff")))


class ThickPaths:
    """Traits EPAIS d'une liste de dessin : le chemin de tous (`path`, peinture ordinaire et exports) et, pour le
    rendu a melange lineaire, des COUCHES dont les traits ne se chevauchent pas (emprises disjointes).

    Pourquoi (mesure, octobre 2026, arrondis du trapeze signales) : le rasteriseur de Qt calcule pour chaque pixel la
    MOYENNE du nombre d'enroulement puis l'ecrete a 1 : exact sans chevauchement, mais deux traits qui se recouvrent
    additionnent leurs couvertures sur les pixels de bord qu'ils partagent. Aux angles d'une polyligne, les bouts ronds
    de deux traits ont le MEME contour exterieur : bord compte deux fois (jusqu'a +48 % de couverture, arrondis gras et
    en escalier). L'union exacte (`QPainterPath.simplified`) donne <= 3 % d'ecart mais coute 0,9 s pour 1 000 traits
    enchaines (18 s pour 3 000) : inutilisable. Ici chaque couche est rasterisee a part (somme exacte : rien ne s'y
    recouvre) et les couches sont fusionnees par MAXIMUM : bords communs exacts, angles interieurs (bords qui se
    croisent) a quelques pourcents pres ; ecart maximal 48 % -> 17 % (3 pixels par angle interieur), moyen 2,5 -> 1,3 %.
    Couches tenues a jour trait par trait (grille d'emprises) : rien n'est refait a la peinture."""

    MAX_LAYERS = 6                              # au-dela : la derniere couche recoit le reste (somme, comme avant)
    CELL = 256.0                                # grille des emprises (unites de la scene)

    def __init__(self):
        self.path = QPainterPath()
        self.path.setFillRule(Qt.WindingFill)
        self.layers: list[QPainterPath] = []
        self._grids: list[dict] = []

    def add(self, path: QPainterPath):
        self.path.addPath(path)
        rect = path.boundingRect()
        cell = self.CELL
        cells = [(cx, cy) for cx in range(math.floor(rect.left() / cell), math.floor(rect.right() / cell) + 1)
                 for cy in range(math.floor(rect.top() / cell), math.floor(rect.bottom() / cell) + 1)]
        for index, grid in enumerate(self._grids):
            last = index == self.MAX_LAYERS - 1
            if last or not any(rect.intersects(other) for c in cells for other in grid.get(c, ())):
                break
        else:
            index = len(self.layers)
            layer = QPainterPath()
            layer.setFillRule(Qt.WindingFill)
            self.layers.append(layer)
            self._grids.append({})
        self.layers[index].addPath(path)
        grid = self._grids[index]
        for c in cells:
            grid.setdefault(c, []).append(rect)


def draw_geometry(painter, thin: bool, color: str, cache, crisp: bool, white: bool = False):
    """Peint une liste de dessin : traits fins `(PixelLines, points)` ou chemin des traits epais."""
    ink = QColor("#ffffff") if white else QColor(color)
    if thin:
        pen = QPen(ink, 1.0)
        pen.setCosmetic(True)
        pen.setCapStyle(Qt.FlatCap)
        painter.setPen(pen)
        painter.setBrush(Qt.NoBrush)
        snapped = cache[0].lines(painter.worldTransform(), crisp)
        if snapped:
            painter.drawLines(snapped)
        if cache[1]:
            painter.drawPoints(cache[1])
    else:
        painter.setPen(Qt.NoPen)
        painter.setBrush(ink)
        painter.drawPath(cache.path if isinstance(cache, ThickPaths) else cache)


def _coverage(width: int, height: int, transform: QTransform, thin: bool, cache, crisp: bool) -> QImage:
    """Masque de couverture anticrenele (un octet par pixel : 0 = vide, 255 = plein), blanc sur noir."""
    mask = QImage(width, height, QImage.Format_Grayscale8)
    mask.fill(0)
    raster = QPainter(mask)
    raster.setRenderHint(QPainter.Antialiasing, True)
    raster.setTransform(transform)
    draw_geometry(raster, thin, "#ffffff", cache, crisp, white=True)
    raster.end()
    return mask


def draw_geometry_linear(painter, thin: bool, color: str, cache, bounds: QRectF, crisp: bool, target) -> bool:
    """Liste de dessin rasterisee en masque de couverture puis posee avec la table de melange lineaire (voir
    `linear_blend_table`). Faux si impossible (transformation tournee) : l'appelant peint comme avant."""
    world = painter.worldTransform()
    if abs(world.m12()) > 1e-9 or abs(world.m21()) > 1e-9:
        return False
    device_rect, background = target
    area = world.mapRect(bounds).adjusted(-2, -2, 2, 2).intersected(device_rect)
    if area.isEmpty():
        return True
    area = area.toAlignedRect()
    ratio = max(1.0, float(painter.device().devicePixelRatioF()))
    width, height = max(1, math.ceil(area.width() * ratio)), max(1, math.ceil(area.height() * ratio))
    transform = world * QTransform.fromTranslate(-area.x(), -area.y()) * QTransform.fromScale(ratio, ratio)
    layers = cache.layers if isinstance(cache, ThickPaths) else [cache]
    if len(layers) <= 1:
        mask = _coverage(width, height, transform, thin, cache, crisp)
    else:
        # Couches fusionnees au MAXIMUM (voir ThickPaths) : niveaux de gris opaques poses en mode « eclaircir ».
        mask = _coverage(width, height, transform, False, layers[0], crisp)
        merge = QPainter(mask)
        merge.setCompositionMode(QPainter.CompositionMode_Lighten)
        for layer in layers[1:]:
            merge.drawImage(0, 0, _coverage(width, height, transform, False, layer, crisp))
        merge.end()
    indexed = QImage(mask.constBits(), width, height, mask.bytesPerLine(), QImage.Format_Indexed8)
    indexed.setColorTable(linear_blend_table(color, background))
    painter.save()
    painter.resetTransform()
    painter.drawImage(QRectF(area), indexed, QRectF(0, 0, width, height))
    painter.restore()
    return True


_RASTER_DEVICES = (1, 2, 3)                     # QInternal::Widget, Pixmap, Image : jamais PDF / SVG / impression


class CadBatch(QGraphicsItem):
    """Lot de lignes CAD consecutives dans l'ordre d'empilement : les peint toutes, dans leur ordre (voir
    l'entete du module). Transparent a la souris et aux recherches d'elements (forme vide)."""

    def __init__(self):
        super().__init__()
        self.members: list[CadLineItem] = []
        self.selected: set = set()
        self._bounds = QRectF()
        self._ops = None                        # [[(fin, serre, couleur), lignes, cache], ...]
        self._bounds_cache: dict = {}           # id(liste de dessin) -> (cache, nb de lignes, emprise)
        self._ops_interval = None
        self._ops_zoom = 1.0
        self._thresholds: list = []
        self._threshold_set: set = set()
        self._tess_band = None                  # finesse des courbes des listes de dessin (voir tess_band)
        self.setAcceptedMouseButtons(Qt.NoButton)
        self.setAcceptHoverEvents(False)
        self.setFlag(QGraphicsItem.ItemIsSelectable, False)

    # -- membres --
    def set_members(self, members: list):
        old = self.members
        if old and len(members) > len(old) and members[len(old) - 1] is old[-1] and members[:len(old)] == old:
            self._append(members[len(old):])    # cas courant : lignes tracees au-dessus de tout
            return
        keep = set(members)
        for item in self.members:
            if item not in keep and item._batch is self:
                item._batch = None
                item._op = None
                item.setFlag(QGraphicsItem.ItemHasNoContents, False)
                item.update()
        for item in members:
            if item._batch is not self:
                if item._batch is not None:
                    item._batch.drop(item, release=False)
                item._batch = self
                if not item.flags() & QGraphicsItem.ItemHasNoContents:
                    item.setFlag(QGraphicsItem.ItemHasNoContents, True)
        self.members = list(members)
        self.selected = {item for item in members if item.isSelected()}
        if members:
            self.setZValue(members[-1].zValue())
        self._refit()
        self._ops = None
        self.update()

    def _append(self, extra: list):
        """Lignes ajoutees au bout du lot : seules elles sont classees et ajoutees aux listes de dessin (refaire
        tout le lot coutait ~30-50 ms par ligne tracee a 5 000 - 10 000 lignes)."""
        for item in extra:
            if item._batch is not None and item._batch is not self:
                item._batch.drop(item, release=False)
            item._batch = self
            if not item.flags() & QGraphicsItem.ItemHasNoContents:     # deja pose (chargement par tranches)
                item.setFlag(QGraphicsItem.ItemHasNoContents, True)
            self.members.append(item)
            if item.isSelected():
                self.selected.add(item)
            rect = item.scene_bounds()
            if not self._bounds.contains(rect):
                self.prepareGeometryChange()
                self._bounds = self._bounds.united(rect)
            if self._ops is not None:
                self._place_in_ops(item, append=True)
        self.setZValue(self.members[-1].zValue())
        self.update()

    def _place_in_ops(self, item, append: bool = False) -> bool:
        """Ligne (re)classee dans les listes de dessin sans les refaire ; False = a refaire (seuil de zoom
        nouveau, place au milieu d'une liste d'une autre facon)."""
        if self._ops is None or any(t not in self._threshold_set for t in item.thresholds()):
            self._ops = None
            return False
        if not item.isVisible():
            item._op = None
            return True
        key = item.draw_key(self._ops_zoom)
        if append:
            ops = self._ops
            if not ops or ops[-1][0] != key:
                ops.append([key, [], None])
            op = ops[-1]
            op[1].append(item)
            item._op = op
            cache = op[2]
            if cache is not None:
                if key[0]:
                    lines, dots = item.scene_geom(True, key[1])
                    cache[0].extend(lines)
                    cache[1].extend(dots)
                else:
                    cache.add(item.scene_geom(False, key[1]))
            return True
        op = item._op
        if op is not None and op[0] == key:
            op[2] = None
            return True
        self._ops = None
        return False

    def drop(self, item, release: bool = True):
        """Ligne retiree du lot (supprimee, changee de hauteur) : elle se peint seule tout de suite."""
        if item._batch is not self:
            return
        try:
            self.members.remove(item)
        except ValueError:
            pass
        self.selected.discard(item)
        op = item._op
        if op is not None and self._ops is not None:
            try:
                op[1].remove(item)
                op[2] = None
            except ValueError:
                self._ops = None
        item._batch = None
        item._op = None
        if release:
            item.setFlag(QGraphicsItem.ItemHasNoContents, False)
            item.update()
        self.update()

    def member_changed(self, item, restyle: bool):
        if restyle:
            self._place_in_ops(item)
        elif item._op is None:
            self._ops = None
        else:
            item._op[2] = None
        rect = item.scene_bounds()
        if not self._bounds.contains(rect):
            self.prepareGeometryChange()
            self._bounds = self._bounds.united(rect)
        self.update()

    def selection_changed(self, item):
        self.prepareGeometryChange()
        if item.isSelected():
            self.selected.add(item)
        else:
            self.selected.discard(item)
        self.update()

    def zoom_changed(self):
        if self.selected:
            self.prepareGeometryChange()

    def _refit(self):
        self.prepareGeometryChange()
        bounds = QRectF()
        for item in self.members:
            bounds = bounds.united(item.scene_bounds())
        self._bounds = bounds

    # -- geometrie --
    def boundingRect(self) -> QRectF:
        if self.selected:
            scene = self.scene()
            zoom = max(0.05, float(getattr(scene, "zoom", 1.0))) if scene is not None else 1.0
            grip = float(getattr(scene, "cad_grip_px", GRIP_PX) or GRIP_PX)
            m = (grip + 4) / zoom
            return self._bounds.adjusted(-m, -m, m, m)
        return self._bounds

    def shape(self) -> QPainterPath:
        return QPainterPath()                   # jamais trouve par items() : les lignes le sont

    # -- dessin --
    def _ops_for(self, zoom: float):
        if self._ops is None:
            thresholds = set()
            for item in self.members:
                thresholds.update(item.thresholds())
            self._thresholds = sorted(thresholds)
            self._threshold_set = thresholds
            self._ops_interval = None
        interval = bisect.bisect_right(self._thresholds, zoom)
        if self._ops is not None and interval == self._ops_interval:
            return self._ops
        ops = []
        for item in self.members:
            if not item.isVisible():
                item._op = None
                continue
            key = item.draw_key(zoom)
            if not ops or ops[-1][0] != key:
                ops.append([key, [], None])
            ops[-1][1].append(item)
            item._op = ops[-1]
        self._ops = ops
        self._ops_interval = interval
        self._ops_zoom = zoom
        return ops

    def _op_cache(self, op):
        (thin, dense, _color), items, cache = op
        if cache is None:
            if thin:
                lines, dots = [], []
                for item in items:
                    more_lines, more_dots = item.scene_geom(True, dense)
                    lines += more_lines
                    if more_dots:
                        dots += more_dots
                cache = (PixelLines(lines), dots)
            else:
                cache = ThickPaths()
                for item in items:
                    cache.add(item.scene_geom(False, dense))
            op[2] = cache
        return cache

    def _op_bounds(self, op) -> QRectF:
        """Emprise (scene) d'une liste de dessin, gardee tant que sa geometrie et ses lignes n'ont pas change."""
        items, cache = op[1], op[2]
        known = self._bounds_cache.get(id(op))
        if known is not None and known[0] is cache and known[1] == len(items):
            return known[2]
        bounds = QRectF()
        for item in items:
            bounds = bounds.united(item.scene_bounds())
        self._bounds_cache[id(op)] = (cache, len(items), bounds)
        return bounds

    def paint(self, painter, option, widget=None):
        scene = self.scene()
        hidden, faded = cad_module_look(self.scene())
        if hidden:
            return                                       # module CAD masque (selecteur de modules du board)
        if faded:
            painter.setOpacity(painter.opacity() * FADE_OPACITY)
        zoom = max(0.05, float(getattr(scene, "zoom", 1.0))) if scene is not None else 1.0
        painter.setRenderHint(QPainter.Antialiasing, bool(getattr(scene, "cad_antialiasing", True)))
        crisp = bool(getattr(scene, "cad_crisp", True))
        target = linear_target(painter, scene)
        band = tess_band(scene)
        if band != self._tess_band:
            # Finesse des courbes changee (fin d'un zoom) : seules les listes de traits fins qui en contiennent.
            for op in self._ops or ():
                if op[0][0] and any(item.CURVED for item in op[1]):
                    op[2] = None
            self._tess_band = band
        for op in self._ops_for(zoom):
            (thin, _dense, color), _items, cache = op[0], op[1], self._op_cache(op)
            if faded:
                color = fade_ink(color)
            if target is not None and draw_geometry_linear(painter, thin, color, cache, self._op_bounds(op), crisp,
                                                           target):
                continue
            draw_geometry(painter, thin, color, cache, crisp)
        if self.selected:
            for item in self.members:
                if item in self.selected and item.isVisible():
                    painter.save()
                    painter.translate(item.pos())
                    item.paint_selection(painter)
                    painter.restore()


class CadLayer:
    """Regroupement des lignes CAD d'une scene en lots (`CadBatch`), refait a la boucle d'evenements suivante
    quand l'empilement change (ajout, suppression, hauteur d'un element du board)."""

    def __init__(self, scene):
        self.scene = scene
        self.batches: list[CadBatch] = []
        self.enabled = True
        self.changed: dict = {}                 # lignes ajoutees / retirees / deplacees (index des accrochages)
        # Entites a enfants peints par QPainter avec le rendu GPU (textes, cotes, hachures : `TEXTED`) : la couche GPU
        # ne parcourt plus TOUS les elements a chaque image (81 000 entites : ~2 parcours par image) ; `extras_rev`
        # change avec l'une d'elles (image des textes refaite, `BoardView._gpu_text_key`).
        self.extras: dict = {}
        self.extras_rev = 0
        self.gpu = None                         # couche OpenGL (cad_gpu) : peint les entites a la place des lots
        self._timer = QTimer(scene)
        self._timer.setSingleShot(True)
        self._timer.setInterval(0)
        self._timer.timeout.connect(self.rebuild)
        # Cotations associatives (`cad_assoc`) : objets auxquels une cotation est liee ; un changement de l'un d'eux
        # fait SUIVRE ses cotations au tour suivant de la boucle (`_follow_dims` : aucune etape d'annulation propre,
        # elles suivent aussi une annulation).
        self.assoc_ids: set = set()
        self._assoc_pending: set = set()
        self._following = False
        self._follow_timer = QTimer(scene)
        self._follow_timer.setSingleShot(True)
        self._follow_timer.setInterval(0)
        self._follow_timer.timeout.connect(self._follow_dims)

    @classmethod
    def of(cls, scene) -> "CadLayer":
        layer = getattr(scene, "cad_layer", None)
        if layer is None:
            layer = cls(scene)
            scene.cad_layer = layer
        return layer

    def note_geometry(self, item, removed: bool = False):
        """Emprise d'une ligne changee (ajout, retrait, deplacement, epaisseur) : l'index spatial du CAD la
        remettra a jour, elle seule (`take_changes`)."""
        self.changed[id(item)] = item
        if getattr(item, "TEXTED", False):
            self.extras_rev += 1
            if getattr(item, "kind", "") == "cad_dim":
                links = item.data.get("assoc")
                if links:
                    self.assoc_ids |= cad_assoc.targets(links)
        if self.assoc_ids and not self._following:
            item_id = getattr(item, "item_id", None)
            if item_id in self.assoc_ids:
                self._assoc_pending.add(item_id)
                if not self._follow_timer.isActive():
                    self._follow_timer.start()
        gpu = self.gpu
        if gpu is not None:
            gpu.store.mark(item, not removed and item.scene() is self.scene)
            gpu.request()

    def _follow_dims(self):
        """Les cotations liees aux objets changes reprennent la place de leurs poignees (`cad_assoc.follow`)."""
        pending, self._assoc_pending = self._assoc_pending, set()
        scene = self.scene
        if not pending:
            return

        def lookup(item_id):
            item = scene.item(item_id) if hasattr(scene, "item") else None
            if item is None or item.scene() is not scene or not hasattr(item, "grips"):
                return None
            circle = None
            if item.kind in ("cad_circle", "cad_arc"):
                g = item.geometry()
                circle = ((float(g["center"][0]), float(g["center"][1])), float(g["radius"]))
            return item.grips(), circle
        for dim in list(self.extras.values()):
            if getattr(dim, "kind", "") != "cad_dim" or dim.scene() is not scene:
                continue
            links = dim.data.get("assoc")
            if not links or not (cad_assoc.targets(links) & pending):
                continue
            ox, oy = dim.doc_offset()
            keys = ("p1", "p2", "center") if dim.data.get("dim_type") == "angular" else ("p1", "p2")
            points = {key: (float(p[0]) + ox, float(p[1]) + oy) for key in keys
                      if (p := dim.data.get(key)) is not None}
            moved, new_links = cad_assoc.follow(points, links, lookup)
            if not moved and new_links == cad_assoc.clean(links):
                continue
            dim.data["assoc"] = new_links
            for key, p in moved.items():
                dim.data[key] = [p[0] - ox, p[1] - oy]
            self._following = True
            try:
                dim.sync()
                dim.update()
            finally:
                self._following = False

    def set_gpu(self, layer):
        """Rendu GPU allume (`layer` = GpuCadLayer) ou eteint (None : lots du processeur). Les entites passent d'un
        rendu a l'autre sans changer."""
        self.gpu = layer
        self.scene.cad_gpu = layer is not None
        self.rebuild()                          # lots du processeur formes (arret) ou dissous (marche)
        if layer is not None:
            layer.store.reset()
            for item in getattr(self.scene, "_items", {}).values():
                if isinstance(item, CadLineItem) and item.scene() is self.scene:
                    item.setFlag(QGraphicsItem.ItemHasNoContents, True)
                    layer.store.mark(item, True)
            layer.request()

    def exporting(self, on: bool):
        """Export (PNG / SVG / PDF) : les entites reprennent leur peinture ordinaire le temps de l'export."""
        if self.gpu is None:
            return
        for item in getattr(self.scene, "_items", {}).values():
            if isinstance(item, CadLineItem):
                item.setFlag(QGraphicsItem.ItemHasNoContents, not on)

    def take_changes(self) -> list:
        changed, self.changed = list(self.changed.values()), {}
        return changed

    def restyle(self):
        """Reglage d'affichage change (seuil des motifs serres...) : classement des traits refait a la prochaine image."""
        if self.gpu is not None:
            self.gpu.store.invalidate_all()
            self.gpu.store.zoom_changed(float("inf"), 0.0)
            self.gpu._zoom = None
            self.gpu.request()
        for batch in self.batches:
            batch._ops = None
            batch.update()

    def structure_changed(self):
        if getattr(self.scene, "bulk_loading", False):
            return                              # chargement par tranches : un seul regroupement, a la fin
        try:
            if not self._timer.isActive():
                self._timer.start()
        except RuntimeError:
            pass                                # scene en cours de destruction

    def bulk_append(self, items: list):
        """Tranche du chargement par tranches : ses lignes s'ajoutent au bout du dernier lot (`CadBatch._append` :
        seules elles entrent dans les listes de dessin ; sinon, tout construire a la 1re peinture figeait ~1 s a
        40 000 lignes). Un autre element du board ou une hauteur plus basse coupe l'ordre : regroupement complet a
        la fin (`bulk_loaded`)."""
        scene = self.scene
        if self.gpu is not None or not self.enabled or not getattr(scene, "_bulk_cad_tail", False) or not items:
            return
        batch = self.batches[-1] if self.batches else None
        if (any(not isinstance(item, CadLineItem) or item.INFINITE for item in items)
                or self._timer.isActive()                       # regroupement complet deja demande
                or (batch is not None and batch.members and items[0].zValue() < batch.members[-1].zValue())
                or any(b.zValue() > items[0].zValue() for b in self.batches[:-1])):
            scene._bulk_cad_tail = False
            return
        if batch is None:
            batch = CadBatch()
            scene.addItem(batch)
            self.batches.append(batch)
        batch._append(items)

    def bulk_loaded(self):
        """Fin du chargement par tranches (`BoardScene.load_data`) : les lignes, arrivees sans se peindre, sont
        regroupees en lots ; sans lots ni GPU (regroupement coupe), elles reprennent leur peinture ordinaire."""
        if self.gpu is None and not self.enabled:
            for item in getattr(self.scene, "_items", {}).values():
                if isinstance(item, CadLineItem):
                    item.setFlag(QGraphicsItem.ItemHasNoContents, False)
        if not getattr(self.scene, "_bulk_cad_tail", False) or self.gpu is not None or not self.enabled:
            self.rebuild()                      # lots deja a jour sinon (bulk_append)

    def rebuild(self):
        scene = self.scene
        try:
            items = list(getattr(scene, "_items", {}).values())
        except RuntimeError:
            return
        runs, current = [], None
        if self.enabled and self.gpu is None:
            for item in sorted(items, key=lambda i: i.zValue()):    # tri stable : ordre d'insertion a z egal
                if isinstance(item, CadLineItem) and not item.INFINITE and item.scene() is scene:
                    if current is None:
                        current = []
                        runs.append(current)
                    current.append(item)
                else:
                    current = None
        for index, members in enumerate(runs):
            if index < len(self.batches):
                batch = self.batches[index]
            else:
                batch = CadBatch()
                scene.addItem(batch)
                self.batches.append(batch)
            batch.set_members(members)
        for batch in self.batches[len(runs):]:
            batch.set_members([])
            if batch.scene() is scene:
                scene.removeItem(batch)
        del self.batches[len(runs):]


ITEM_CLASSES["cad_line"] = CadLineItem
for _kind in ("cad_arc", "cad_circle", "cad_pline"):
    ITEM_CLASSES[_kind] = CadCurveItem
ITEM_CLASSES["cad_dim"] = CadDimItem
ITEM_CLASSES["cad_hatch"] = CadHatchItem
ITEM_CLASSES["cad_text"] = CadTextItem
ITEM_CLASSES["cad_point"] = CadPointItem
ITEM_CLASSES["cad_insert"] = CadInsertItem
ITEM_CLASSES["cad_image"] = CadImageItem
ITEM_CLASSES["cad_xline"] = CadXlineItem
ITEM_CLASSES["cad_ray"] = CadXlineItem
