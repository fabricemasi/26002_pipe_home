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

from PySide6.QtCore import QLineF, QPointF, QRectF, Qt, QTimer
from PySide6.QtGui import QColor, QFont, QFontMetricsF, QGuiApplication, QImage, QPainter, QPainterPath, QPainterPathStroker, QPen, QTransform
from PySide6.QtWidgets import QGraphicsItem, QStyle

from . import cad_geometry as geo
from . import cad_dims, cad_hatch, cad_model, cad_shapes, cad_text
from .items import ITEM_CLASSES, BoardItem

GRIP_PX = 8                 # poignees (grips), pixels d'ecran ; reglable (board_cad_grip_size)
GRIP_COLOR = "#2f6bff"      # grip froid (bleu, comme AutoCAD) ; reglable (board_cad_grip_color)
DENSE_PX = 4.0              # motif plus serre que ca a l'ecran : trait continu ; reglable (board_cad_dense_px)
MAX_DASHES = 4000


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
        if last is None or geo.distance(last, start) > geo.EPS * 10:
            path.moveTo(sx, sy)
        if p[0] == "segment":
            path.lineTo(p[2][0], -p[2][1])
        else:
            c, r = p[1], p[2]
            path.arcTo(QRectF(c[0] - r, -c[1] - r, 2 * r, 2 * r), p[3], p[4])
        last = cad_shapes.prim_end(p)
    return path


def stroke_outline(primitives, half: float, start: dict | None, end: dict | None, closed: bool) -> QPainterPath:
    """Contour d'un trait epais qui suit les primitives : coupe franche, angles en onglet (polylignes larges
    d'AutoCAD), disque pose aux bouts « arrondi » (`start` / `end` = terminaison, None = aucune). Le border radius
    des courbes est rendu en coupe franche."""
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

    def __init__(self, data: dict):
        self._geom_key = None
        self._outline = QPainterPath()
        self._dashed = None
        self._thin_dashes = None
        self._props = None
        self._bounds = QRectF()
        self._batch = None                      # lot qui peint cette ligne (CadBatch), None = se peint seule
        self._op = None                         # liste de dessin du lot qui la contient
        self._scene_geom: dict = {}             # geometrie dans le repere de la scene, par variante
        super().__init__(data)
        self.setCacheMode(QGraphicsItem.NoCache)
        self.setAcceptHoverEvents(False)

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
            props = cad_model.resolve(self.data, cad, unit_of(self.scene(), cad))
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

    def _place_from_data(self):
        self._props = None
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
        if change == QGraphicsItem.ItemSceneHasChanged and value is not None and getattr(value, "cad_gpu", False):
            self.setFlag(QGraphicsItem.ItemHasNoContents, True)     # rendu GPU : la scene ne le peint pas
        if change == QGraphicsItem.ItemSceneChange:
            old = self.scene()
            if old is not None and value is not old:
                if self._batch is not None:
                    self._batch.drop(self)
                layer = getattr(old, "cad_layer", None)
                if layer is not None:
                    layer.structure_changed()
                    layer.note_geometry(self, removed=True)    # quitte la scene : retire du dessin GPU
        elif change == QGraphicsItem.ItemSceneHasChanged:
            self._props = None
            self.sync()
            if value is not None:
                layer = CadLayer.of(value)
                layer.structure_changed()
                layer.note_geometry(self)
        elif change == QGraphicsItem.ItemZValueHasChanged:
            if self._batch is not None:
                self._batch.drop(self)              # se peint seule a sa nouvelle hauteur jusqu'au regroupement
        elif change == QGraphicsItem.ItemPositionHasChanged:
            self._scene_geom = {}
            self._touch()
        elif change == QGraphicsItem.ItemVisibleHasChanged:
            self._touch(restyle=True)
        elif change == QGraphicsItem.ItemSelectedHasChanged:
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
        a, b = self._local_points()
        weight = float(props["lineweight"])
        key = (a.x(), a.y(), b.x(), b.y(), weight, repr(props["end1"]), repr(props["end2"]), repr(props["inner"]),
               tuple(props["pattern"]), props["ltscale"], props["extra"], props["distribute"], props["resize"])
        if key == self._geom_key:
            return
        self.prepareGeometryChange()
        self._geom_key = key
        self._dashed = None
        self._thin_dashes = None
        self._scene_geom = {}
        length = QLineF(a, b).length()
        transform = QTransform()
        transform.translate(a.x(), a.y())
        transform.rotate(math.degrees(math.atan2(b.y() - a.y(), b.x() - a.x())) if length > geo.EPS else 0.0)
        self._transform = transform
        self._length = length
        half = weight / 2.0
        end1, end2, inner = props["end1"], props["end2"], props["inner"]
        self._outline = transform.map(line_outline(length, half, end1, end2)) if half > 0 else QPainterPath()
        pattern = props["pattern"]
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
        rect = QRectF(a, b).normalized().adjusted(-1.0, -1.0, 1.0, 1.0)
        self._bounds = self._outline.boundingRect().adjusted(-1.0, -1.0, 1.0, 1.0).united(rect) if half > 0             else rect
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
        zoom = self._zoom()
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
            size = self._grip_px() / zoom
            painter.setPen(QPen(QColor("#ffffff"), 1.0 / zoom))
            painter.setBrush(QColor(getattr(self.scene(), "cad_grip_color", GRIP_COLOR)))
            for point in (a, QPointF((a.x() + b.x()) / 2, (a.y() + b.y()) / 2), b):
                painter.drawRect(QRectF(point.x() - size / 2, point.y() - size / 2, size, size))


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
        zoom = self._zoom()
        accent = QColor(getattr(self.scene(), "accent", GRIP_COLOR))
        halo = QColor(accent)
        halo.setAlpha(110)
        pen = QPen(halo, 3.0, Qt.DashLine)
        pen.setCosmetic(True)
        painter.setPen(pen)
        painter.setBrush(Qt.NoBrush)
        painter.drawPath(self._center)
        if getattr(self.scene(), "cad_show_grips", True) and not self.locked():
            size = self._grip_px() / zoom
            painter.setPen(QPen(QColor("#ffffff"), 1.0 / zoom))
            painter.setBrush(QColor(getattr(self.scene(), "cad_grip_color", GRIP_COLOR)))
            for _name, point in cad_shapes.grips(self.kind, self.data):
                painter.drawRect(QRectF(point[0] - size / 2, -point[1] - size / 2, size, size))

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
        scale = self._height / (self.FONT_PX * self.CAP_RATIO)
        painter.save()
        painter.scale(scale, scale)
        painter.setRenderHint(QPainter.TextAntialiasing, True)
        painter.setFont(self._font())
        painter.setPen(QColor(parent.props()["color"]))
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
        style = found["style"]
        _metrics, cap = text_metrics(style["font"], style["bold"], style["italic"])
        k = found["height"] / cap
        painter.save()
        painter.scale(k, k)
        painter.setRenderHint(QPainter.TextAntialiasing, True)
        painter.setRenderHint(QPainter.Antialiasing, True)
        painter.setFont(text_font(style["font"], style["bold"], style["italic"]))
        painter.setPen(QColor(parent.props()["color"]))
        for line, x, y in found["lines"]:
            if line:
                painter.drawText(QPointF(x / k, -y / k), line)
        painter.restore()


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
        zoom = self._zoom()
        accent = QColor(getattr(self.scene(), "accent", GRIP_COLOR))
        halo = QColor(accent)
        halo.setAlpha(150)
        pen = QPen(halo, 1.5, Qt.DashLine)
        pen.setCosmetic(True)
        painter.setPen(pen)
        painter.setBrush(Qt.NoBrush)
        painter.drawPath(self._box_path())
        if getattr(self.scene(), "cad_show_grips", True) and not self.locked():
            size = self._grip_px() / zoom
            painter.setPen(QPen(QColor("#ffffff"), 1.0 / zoom))
            painter.setBrush(QColor(getattr(self.scene(), "cad_grip_color", GRIP_COLOR)))
            for _name, point in cad_shapes.grips(self.kind, self.data):
                painter.drawRect(QRectF(point[0] - size / 2, -point[1] - size / 2, size, size))


class _HatchFill(QGraphicsItem):
    """Remplissage PLEIN d'une hachure : enfant de l'element (peint par la scene, sous les traits)."""

    def __init__(self, parent):
        super().__init__(parent)
        self._path = QPainterPath()
        self._solid = False
        self._alpha = 1.0
        self.setAcceptedMouseButtons(Qt.NoButton)
        self.setCacheMode(QGraphicsItem.NoCache)

    def set_area(self, loops, solid: bool, alpha: float):
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
        color = QColor(parent.props()["color"])
        color.setAlphaF(self._alpha)
        painter.setPen(Qt.NoPen)
        painter.setBrush(color)
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
        self._hatch_key = None
        self._loops_cache = []
        self._prims_cache = []
        self._reach = 0.0           # portee de selection du dernier clic (unites du document), posee par `pick_all`
        super().__init__(data)
        self._fill = _HatchFill(self)
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
               self.data.get("hatch_spacing"), repr(self.data.get("hatch_origin")))
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
            self._fill.set_area(self._loops_cache, style["pattern"] == "solid", style["alpha"])

    def shape(self) -> QPainterPath:
        return self._fill.area_path() if self._fill is not None else QPainterPath()

    def paint_selection(self, painter):
        if not self.isSelected():
            return
        zoom = self._zoom()
        accent = QColor(getattr(self.scene(), "accent", GRIP_COLOR))
        halo = QColor(accent)
        halo.setAlpha(150)
        pen = QPen(halo, 2.0, Qt.DashLine)
        pen.setCosmetic(True)
        painter.setPen(pen)
        painter.setBrush(Qt.NoBrush)
        painter.drawPath(self._fill.area_path())
        if getattr(self.scene(), "cad_show_grips", True) and not self.locked():
            size = self._grip_px() / zoom
            painter.setPen(QPen(QColor("#ffffff"), 1.0 / zoom))
            painter.setBrush(QColor(getattr(self.scene(), "cad_grip_color", GRIP_COLOR)))
            for _name, point in cad_shapes.grips(self.kind, self.data):
                painter.drawRect(QRectF(point[0] - size / 2, -point[1] - size / 2, size, size))


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
        self.gpu = None                         # couche OpenGL (cad_gpu) : peint les entites a la place des lots
        self._timer = QTimer(scene)
        self._timer.setSingleShot(True)
        self._timer.setInterval(0)
        self._timer.timeout.connect(self.rebuild)

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
        gpu = self.gpu
        if gpu is not None:
            gpu.store.mark(item, not removed and item.scene() is self.scene)
            gpu.request()

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
        try:
            if not self._timer.isActive():
                self._timer.start()
        except RuntimeError:
            pass                                # scene en cours de destruction

    def rebuild(self):
        scene = self.scene
        try:
            items = list(getattr(scene, "_items", {}).values())
        except RuntimeError:
            return
        runs, current = [], None
        if self.enabled and self.gpu is None:
            for item in sorted(items, key=lambda i: i.zValue()):    # tri stable : ordre d'insertion a z egal
                if isinstance(item, CadLineItem) and item.scene() is scene:
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
