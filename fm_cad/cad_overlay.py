"""Module CAD du board : rendu TEMPORAIRE (aucune entite, aucun changement de la scene) — elastique,
fantomes, marqueurs et infobulles d'accrochage, lignes de suivi, points acquis, fenetre / capture de
selection, survol, poignee chaude, saisie dynamique, reticule.

Un widget transparent a la souris pose sur le viewport de la vue du board. Ses tailles sont en pixels d'ECRAN
(marqueurs, poignees, tolerances lisibles a tout zoom) ; la geometrie arrive en coordonnees du DOCUMENT et
passe par `to_view` (document -> scene -> viewport, en flottants).

LATENCE (mesures : tests/_probe_cad_latency.py, ecran 2560 x 1440 a 60 Hz) :
- le RETICULE suit la souris par le CURSEUR DU SYSTEME (`native_cursor` : croix + boite de selection dessinees
  dans une image de curseur, deplacee par Windows sans attendre l'appli). Un reticule peint par l'appli arrive
  toujours au moins une image apres la souris (peinture, composition de Windows), plus encore quand la scene
  est lourde : c'etait la « trainee » du curseur. Il n'est peint ici que pour l'aimant (curseur cale sur un
  point d'accrochage, immobile tant qu'il y reste) ou au-dela de la taille d'un curseur (`NATIVE_MAX_PX`) ;
- un mouvement ne repeint que ce qui CHANGE : chaque element est mis en page (`_layout` : un rectangle par
  element), l'overlay ne repeint que la reunion des anciens et des nouveaux rectangles, et rien du tout quand
  rien ne change (envoyer toute la fenetre a Windows coute 4 a 17 ms par image en 2400 x 1300, un petit
  rectangle 0,1 ms) ;
- la scene n'est jamais repeinte pour un mouvement : l'overlay garde une IMAGE du viewport (`backdrop`) et se
  peint OPAQUE par-dessus (Qt ne peint plus le viewport en dessous). L'image est jetee des que la scene, le
  zoom, le defilement ou la taille changent (`invalidate`) : l'overlay redevient transparent, Qt repeint la
  scene NORMALEMENT (une seule fois) et l'image est RELEVEE dans la memoire de la fenetre juste apres
  (`capture`, appelee par `BoardView.paintEvent` : ~2,5 ms en 2400 x 1300). Refaire l'image par
  `QGraphicsView.render` coutait une seconde peinture, plus lente (sa recherche d'elements appelle le
  `boundingRect` Python de chaque ligne : 27 ms a 5 000 lignes), et elle partait 90 ms apres le dernier
  changement : figement au repos, scene repeinte a chaque mouvement d'ici la. `render` ne sert plus que si la
  memoire de la fenetre n'est pas lisible (`_render_backdrop`)."""
from __future__ import annotations

import math

from PySide6.QtCore import QEvent, QPoint, QPointF, QRect, QRectF, Qt
from PySide6.QtGui import QColor, QCursor, QFont, QFontMetricsF, QImage, QPainter, QPen, QPixmap, QPolygonF, QRegion, QTransform
from PySide6.QtWidgets import QWidget

from . import cad_geometry as geo
from .cad_items import paint_grips

MARKER_STYLE = {"end": "square", "mid": "triangle", "cen": "circle", "gcen": "circle_x", "qua": "diamond",
                "int": "x", "extint": "x_square", "appint": "x_square", "ext": "dots", "per": "perp",
                "tan": "tangent", "nea": "hourglass", "par": "parallel", "node": "circle_x", "ins": "insert"}

NATIVE_MAX_PX = 128         # bras du reticule au-dela : curseur trop grand pour Windows, reticule peint
BADGE_ROOM = 22             # place (pixels logiques, de chaque cote du centre) que prend l'indicateur « en memoire »
_CURSORS: dict = {}


def crosshair_rects(cx: int, cy: int, arm: int, half: int, box: bool = True) -> list:
    """Le reticule en rectangles de PIXELS PHYSIQUES entiers (x, y, largeur, hauteur), centre sur le pixel (cx, cy) :
    quatre bras d'UN pixel de large (`arm` pixels depuis le centre) et la boite de selection de demi-cote `half`
    (contour d'un pixel). Avec la boite, les bras PARTENT DE SON BORD (dedans vide, comme AutoCAD : demande de
    l'utilisateur) ; sans elle (invite de point, fenetre de selection), une croix pleine. Le meme dessin pour le
    curseur du systeme et pour le reticule peint par l'overlay. `box` False : les bras s'arretent au bord de la boite
    sans la dessiner (reticule aimante sur une poignee : son contour tient lieu de boite)."""
    rects = []
    if arm > 0 and half > 0:
        if arm > half:
            length = arm - half
            rects += [(cx - arm, cy, length, 1), (cx + half + 1, cy, length, 1),
                      (cx, cy - arm, 1, length), (cx, cy + half + 1, 1, length)]
    elif arm > 0:
        rects.append((cx - arm, cy, 2 * arm + 1, 1))
        rects.append((cx, cy - arm, 1, 2 * arm + 1))
    if half > 0 and box:
        side = 2 * half + 1
        rects += [(cx - half, cy - half, side, 1), (cx - half, cy + half, side, 1),
                  (cx - half, cy - half + 1, 1, side - 2), (cx + half, cy - half + 1, 1, side - 2)]
    return rects


def paint_memory_badge(painter, x: float, y: float, source: str, ink: str):
    """Indicateur « des proprietes sont en memoire » (pipette en cours) pres du reticule : une pipette dont la pointe
    est de la couleur de l'objet source. (x, y) = centre du reticule, en pixels logiques du painter."""
    painter.save()
    painter.setRenderHint(QPainter.Antialiasing, True)
    outline = QColor(ink)
    pen = QPen(outline, 1.6)
    pen.setCapStyle(Qt.RoundCap)
    painter.setPen(pen)
    painter.drawLine(QPointF(x + 18, y + 8), QPointF(x + 11, y + 15))          # corps de la pipette
    painter.setPen(QPen(outline, 3.4, Qt.SolidLine, Qt.RoundCap))
    painter.drawLine(QPointF(x + 17, y + 9), QPointF(x + 19.5, y + 6.5))       # poire
    painter.setPen(QPen(outline, 1.0))
    painter.setBrush(QColor(source))
    painter.drawEllipse(QPointF(x + 9.2, y + 16.8), 3.1, 3.1)                    # pointe : couleur de la source
    painter.restore()


def native_cursor(reach: int, pickbox: int, color: str, ratio: float, badge: str | None = None) -> QCursor | None:
    """Curseur du systeme : reticule de `reach` pixels de chaque cote, boite de selection de demi-cote
    `pickbox` (0 = sans), au pixel physique pres (lignes d'un pixel, centre sur le point chaud) ; `badge` (couleur de
    l'objet source de la pipette) ajoute l'indicateur « proprietes en memoire »."""
    if reach > NATIVE_MAX_PX:
        return None
    key = (reach, pickbox, color, round(ratio, 3), badge)
    cursor = _CURSORS.get(key)
    if cursor is not None:
        return cursor
    room = max(reach, pickbox, BADGE_ROOM if badge else 0)     # reach 0 : le carre de selection seul
    size = 2 * room + 1
    device = max(1, round(size * ratio))
    centre = round(room * ratio)
    pixmap = QPixmap(device, device)
    pixmap.fill(Qt.transparent)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.Antialiasing, False)
    ink = QColor(color)
    for x, y, w, h in crosshair_rects(centre, centre, round(reach * ratio), round(pickbox * ratio) if pickbox > 0 else 0):
        painter.fillRect(QRect(x, y, w, h), ink)
    if badge:
        painter.scale(ratio, ratio)
        paint_memory_badge(painter, room + 0.5 / ratio, room + 0.5 / ratio, badge, color)
    painter.end()
    pixmap.setDevicePixelRatio(ratio)
    cursor = _CURSORS[key] = QCursor(pixmap, room, room)       # point chaud en pixels LOGIQUES (Qt)
    return cursor


# Cadres de selection par defaut (= l'ancien dessin) : [fenetre, capture].
DEFAULT_FRAMES = (
    {"bg": "#283c6eff", "sides": {"top": True, "right": True, "bottom": True, "left": True},
     "colors": {k: "#285ae6" for k in ("top", "right", "bottom", "left")}, "thickness": 1,
     "radius": {k: 0 for k in ("top_left", "top_right", "bottom_right", "bottom_left")}, "line": "solid", "scale": 100},
    {"bg": "#2850c878", "sides": {"top": True, "right": True, "bottom": True, "left": True},
     "colors": {k: "#28a05a" for k in ("top", "right", "bottom", "left")}, "thickness": 1,
     "radius": {k: 0 for k in ("top_left", "top_right", "bottom_right", "bottom_left")}, "line": "dash", "scale": 100},
)
LINE_PATTERNS = {"dash": (6.0, 4.0), "dot": (1.0, 3.0)}       # en epaisseurs de trait, a l'echelle 100 %


def _frame_pen(color: str, thickness: float, line: str, scale: float) -> QPen:
    pen = QPen(QColor(color), max(0.1, float(thickness)))
    pen.setJoinStyle(Qt.MiterJoin)
    pattern = LINE_PATTERNS.get(line)
    if pattern:
        k = max(0.1, float(scale) / 100.0)
        pen.setCapStyle(Qt.FlatCap)
        pen.setDashPattern([max(0.1, v * k) for v in pattern])
    return pen


def paint_selection_frame(painter, rect: QRectF, frame: dict):
    """Un cadre de selection : fond, bordure par cote (couleur, epaisseur, type de ligne), arrondi par coin. Les 4
    cotes allumes et de meme couleur : un seul contour (les tirets suivent les arrondis) ; sinon un trait par cote,
    chacun avec la moitie des arrondis voisins."""
    from PySide6.QtGui import QPainterPath
    radius = frame.get("radius") or {}
    w, h = rect.width(), rect.height()
    limit = max(0.0, min(w, h) / 2.0)
    r = {k: min(limit, max(0.0, float(radius.get(k, 0) or 0))) for k in ("top_left", "top_right", "bottom_right",
                                                                         "bottom_left")}
    x0, y0, x1, y1 = rect.left(), rect.top(), rect.right(), rect.bottom()
    outline = QPainterPath()
    outline.moveTo(x0 + r["top_left"], y0)
    outline.lineTo(x1 - r["top_right"], y0)
    outline.arcTo(QRectF(x1 - 2 * r["top_right"], y0, 2 * r["top_right"], 2 * r["top_right"]), 90, -90)
    outline.lineTo(x1, y1 - r["bottom_right"])
    outline.arcTo(QRectF(x1 - 2 * r["bottom_right"], y1 - 2 * r["bottom_right"], 2 * r["bottom_right"],
                         2 * r["bottom_right"]), 0, -90)
    outline.lineTo(x0 + r["bottom_left"], y1)
    outline.arcTo(QRectF(x0, y1 - 2 * r["bottom_left"], 2 * r["bottom_left"], 2 * r["bottom_left"]), 270, -90)
    outline.lineTo(x0, y0 + r["top_left"])
    outline.arcTo(QRectF(x0, y0, 2 * r["top_left"], 2 * r["top_left"]), 180, -90)
    outline.closeSubpath()
    painter.save()
    painter.setRenderHint(QPainter.Antialiasing, any(r.values()))
    painter.setPen(Qt.NoPen)
    painter.setBrush(QColor(frame.get("bg") or "#00000000"))
    painter.drawPath(outline)
    painter.setBrush(Qt.NoBrush)
    sides = frame.get("sides") or {}
    colors = frame.get("colors") or {}
    thickness, line, scale = frame.get("thickness", 1), frame.get("line", "solid"), frame.get("scale", 100)
    on = [k for k in ("top", "right", "bottom", "left") if sides.get(k)]
    if line == "solid" and len(on) == 4 and len({colors.get(k) for k in on}) == 1:
        painter.setPen(_frame_pen(colors.get("top") or "#285ae6", thickness, line, scale))
        painter.drawPath(outline)
    else:
        # Un trait par cote (avec la moitie des arrondis voisins), TOUJOURS tire depuis le meme coin : haut et bas
        # depuis la gauche, gauche et droite depuis le haut. Les tirets d'un cote dont la place et le coin de depart
        # ne bougent pas restent donc immobiles quand le cadre grandit : il n'est pas repeint (`CadOverlay._dirty`).
        # Angles de Qt : 0 = est, sens direct (vers le haut).
        def box(key, left, top):
            return QRectF(left, top, 2 * r[key], 2 * r[key])
        boxes = {"top_left": box("top_left", x0, y0), "top_right": box("top_right", x1 - 2 * r["top_right"], y0),
                 "bottom_right": box("bottom_right", x1 - 2 * r["bottom_right"], y1 - 2 * r["bottom_right"]),
                 "bottom_left": box("bottom_left", x0, y1 - 2 * r["bottom_left"])}
        # cote : (coin de depart, angle, sens), point droit d'arrivee, (coin d'arrivee, angle, sens)
        sides_path = {
            "top": (("top_left", 135, -45), (x1 - r["top_right"], y0), ("top_right", 90, -45)),
            "bottom": (("bottom_left", 225, 45), (x1 - r["bottom_right"], y1), ("bottom_right", 270, 45)),
            "left": (("top_left", 135, 45), (x0, y1 - r["bottom_left"]), ("bottom_left", 180, 45)),
            "right": (("top_right", 45, -45), (x1, y1 - r["bottom_right"]), ("bottom_right", 0, -45)),
        }
        starts = {"top": (x0, y0), "bottom": (x0, y1), "left": (x0, y0), "right": (x1, y0)}
        for key in on:
            (first, angle, sweep), point, (last, end_angle, end_sweep) = sides_path[key]
            path = QPainterPath()
            if r[first] > 0:
                path.arcMoveTo(boxes[first], angle)
                path.arcTo(boxes[first], angle, sweep)
            else:
                path.moveTo(*starts[key])
            path.lineTo(*point)
            if r[last] > 0:
                path.arcTo(boxes[last], end_angle, end_sweep)
            painter.setPen(_frame_pen(colors.get(key) or "#285ae6", thickness, line, scale))
            painter.drawPath(path)
    painter.restore()


def _minus(a: QRect, b: QRect) -> list:
    """Rectangles de `a` hors de `b` (au plus 4 bandes)."""
    inter = a.intersected(b)
    if inter.isEmpty():
        return [QRect(a)]
    out = []
    if inter.top() > a.top():
        out.append(QRect(a.left(), a.top(), a.width(), inter.top() - a.top()))
    if inter.bottom() < a.bottom():
        out.append(QRect(a.left(), inter.bottom() + 1, a.width(), a.bottom() - inter.bottom()))
    if inter.left() > a.left():
        out.append(QRect(a.left(), inter.top(), inter.left() - a.left(), inter.height()))
    if inter.right() < a.right():
        out.append(QRect(inter.right() + 1, inter.top(), a.right() - inter.right(), inter.height()))
    return out


def _pt(p: QPointF) -> tuple:
    return round(p.x(), 2), round(p.y(), 2)


def _line_rect(a: QPointF, b: QPointF, pad: float) -> QRectF:
    return QRectF(a, b).normalized().adjusted(-pad, -pad, pad, pad)


class CadOverlay(QWidget):
    def __init__(self, view, controller):
        super().__init__(view.viewport())
        self.view = view
        self.ctl = controller
        self.setAttribute(Qt.WA_TransparentForMouseEvents, True)
        self.setAttribute(Qt.WA_NoSystemBackground, True)
        self.setFocusPolicy(Qt.NoFocus)
        self.backdrop: QImage | QPixmap | None = None
        self.backdrop_enabled = True
        self._fresh = False                     # image relevee pendant cette peinture : deja a l'ecran
        self._origin = QPoint(0, 0)             # coin de l'image relevee dans le widget
        self._ops: list = []                    # elements mis en page pour la derniere peinture demandee
        self._key = None
        self._rect = QRect()                    # zone peinte par ces elements (pixels du widget)
        self._prepared = False                  # mise en page deja faite pour la prochaine image GPU (`prepare`)
        self._rects: list = []                  # la meme zone, un rectangle par element (reticule jusqu'aux bords)
        self._metrics: dict = {}
        self._capture_ok = True                 # memoire de la fenetre lisible (sinon `render`)
        self.gpu = None                         # couche OpenGL (cad_gpu) : l'overlay y est peint, ce widget reste cache
        self.resize(view.viewport().size())
        view.viewport().installEventFilter(self)    # toujours la taille du viewport (sinon image jamais relevee)

    def eventFilter(self, obj, event):
        if event.type() == QEvent.Resize and obj is self.view.viewport():
            if self.geometry() != obj.rect():
                self.setGeometry(obj.rect())
                self.invalidate()
        return False

    # -- rendu GPU : le contenu est peint dans la couche OpenGL (`paint_into`) --
    def attach_gpu(self, layer):
        """Couche GPU (cad_gpu) ou None. Allumee : ce widget est cache, plus d'image du viewport (le CAD n'est pas
        dans le viewport raster) ; tout se peint dans la couche, une image GPU par changement."""
        self.gpu = layer
        self.backdrop = None
        self.backdrop_enabled = layer is None
        self.setAttribute(Qt.WA_OpaquePaintEvent, False)
        if layer is not None:
            self.hide()
            layer.request()
        elif self.ctl.active:
            self.show()
            self.raise_()
            self.update()

    def update(self, *args):
        if self.gpu is not None:
            self.gpu.request()
            return
        super().update(*args)

    def repaint(self, *args):
        if self.gpu is not None:
            self.gpu.request()
            return
        super().repaint(*args)

    def prepare(self) -> QRect:
        """Mise en page du rendu temporaire (couche GPU) ; rend le rectangle (viewport) qui le contient."""
        if not self.ctl.active:
            return QRect()
        self._ops, self._key, self._rect = self._layout(self.ctl.overlay_state())
        self._prepared = True
        out = QRect()
        for r in self._rects_of(self._ops):
            out = r if out.isNull() else out.united(r)
        return out.adjusted(-2, -2, 2, 2) if not out.isNull() else out

    def paint_into(self, painter) -> bool:
        """Peint le rendu temporaire (apercus, marqueurs, reticule, infobulles…) avec `painter` (couche GPU) ; vrai si
        le reticule a ete peint."""
        if not self.ctl.active:
            return False
        if not self._prepared:
            self.prepare()
        self._prepared = False
        look = self.ctl.look
        painted_cursor = False
        painter.setRenderHint(QPainter.Antialiasing, True)
        for kind, rect, args in self._ops:
            getattr(self, "_paint_" + kind)(painter, look, *args)
            painted_cursor = painted_cursor or kind.startswith("cursor")
        return painted_cursor

    # -- image du viewport --
    def invalidate(self):
        """Scene, zoom, defilement ou taille changes : image jetee ; l'overlay redevient transparent, Qt repeint
        la scene (une fois) et l'image est relevee juste apres (`capture`)."""
        if self.gpu is not None:
            return
        if self.backdrop is not None:
            self.backdrop = None
            self.setAttribute(Qt.WA_OpaquePaintEvent, False)
        if self.isVisible():
            self.update()

    def set_backdrop_enabled(self, on: bool):
        self.backdrop_enabled = bool(on)
        self.backdrop = None
        self.setAttribute(Qt.WA_OpaquePaintEvent, False)
        self.update()

    def capture(self, rect):
        """Le viewport vient d'etre peint en entier (`rect`) : son image est relevee dans la memoire de la
        fenetre (aucune peinture de plus) ; l'overlay devient opaque."""
        if self.backdrop is not None or not self.backdrop_enabled or not self._capture_ok or not self.isVisible():
            return
        if self.view.zooming():
            return                              # zoom continu : relevee a la fin du geste (BoardView._zoom_settled)
        shown = self.visibleRegion().boundingRect()
        if shown.isEmpty() or not rect.contains(shown):
            return                              # peinture partielle : rien de sur a relever
        found = self._window_image(shown)
        if found is None:
            self._capture_ok = False
            return
        self.backdrop, self._origin = found
        self._fresh = True
        self.setAttribute(Qt.WA_OpaquePaintEvent, True)

    def _window_image(self, shown: QRect):
        """(image de la partie VISIBLE du viewport, son coin dans le widget) lue dans la memoire de la
        fenetre ; None si elle n'est pas lisible (autre moteur de rendu)."""
        viewport = self.view.viewport()
        try:
            store = viewport.backingStore()
            device = store.paintDevice() if store is not None else None
        except (AttributeError, RuntimeError):
            return None
        if not isinstance(device, QImage) or device.isNull():
            return None
        ratio = device.devicePixelRatio() or 1.0
        top_left = viewport.mapTo(viewport.window(), shown.topLeft())
        area = QRectF(top_left.x() * ratio, top_left.y() * ratio, shown.width() * ratio,
                      shown.height() * ratio).toRect()
        if not device.rect().contains(area):
            return None
        image = device.copy(area)
        image.setDevicePixelRatio(ratio)
        return image, shown.topLeft()

    def _render_backdrop(self):
        view = self.view
        if view.viewport().size() != self.size():
            self.resize(view.viewport().size())
        ratio = self.devicePixelRatioF()
        pixmap = QPixmap(max(1, round(self.width() * ratio)), max(1, round(self.height() * ratio)))
        pixmap.setDevicePixelRatio(ratio)
        pixmap.fill(Qt.transparent)
        painter = QPainter(pixmap)
        painter.setRenderHints(view.renderHints())
        view.render(painter, QRectF(0, 0, self.width(), self.height()), view.viewport().rect())
        painter.end()
        self.backdrop = pixmap
        self._origin = QPoint(0, 0)

    # -- conversions --
    def to_view(self, p) -> QPointF:
        x, y = geo.to_scene(p)
        return self.view.viewportTransform().map(QPointF(x, y))

    # -- mise a jour --
    def track(self):
        """Mouvement de souris (ou changement d'etat local) : seule la zone qui change est repeinte ; rien si
        le rendu temporaire est identique."""
        if self.gpu is not None:
            if self.ctl.active:
                self.gpu.request()                  # une image GPU (~0,5 ms de processeur) : tout est repeint
            return
        if not self.isVisible():
            return
        ops, key, rect = self._layout(self.ctl.overlay_state())
        rects = self._rects_of(ops)
        old_ops, old_key, old_rects = self._ops, self._key, self._rects
        self._ops, self._key, self._rect, self._rects = ops, key, rect, rects       # avant toute peinture
        if self.backdrop is None and self.backdrop_enabled:
            self.update()                       # image a relever : la scene est repeinte une fois
        elif key != old_key:
            # (les zones des elements PEINTS : `_rects` n'est pas tenu a jour par la peinture, `_ops` l'est)
            dirty = self._dirty(old_ops, self._rects_of(old_ops), ops, rects)
            if dirty is None:
                self._repaint(rects + old_rects)
            else:                               # cadre de selection : UN envoi, peinture limitee aux bords qui bougent
                region = QRegion()
                for r in self._merge(dirty):
                    region = region.united(r)
                self.update(region)

    @staticmethod
    def _dirty(old_ops, old_rects, ops, rects) -> list:
        """Zones a repeindre. Fenetre de selection (signale : « latence entre le curseur et le cadre ») : son fond est
        UNI, l'interieur commun a l'ancien et au nouveau cadre ne change pas — seuls les BORDS (bandes, arrondis
        compris) et la zone gagnee ou perdue sont repeints, pas toute sa surface (un grand cadre = presque toute la
        vue envoyee a Windows a chaque mouvement)."""
        def window(ops_, rects_):
            for index, (kind, rect, args) in enumerate(ops_):
                if kind == "window":
                    return index, rect.toAlignedRect().adjusted(-1, -1, 1, 1), args
            return None
        old, new = window(old_ops, old_rects), window(ops, rects)
        if old is None or new is None or old[2][1] != new[2][1]:
            return None
        band = max(new[2][2], old[2][2])
        out = [r for i, r in enumerate(old_rects) if i != old[0]] + [r for i, r in enumerate(rects) if i != new[0]]
        a, b = old[1], new[1]
        # Un bord dont la place ET le coin de depart (gauche pour haut / bas, haut pour gauche / droite) ne changent
        # pas reste identique : seule sa rallonge (ou ce qu'il perd) change, deja dans la zone gagnee / perdue.
        same = {"top": a.top() == b.top() and a.left() == b.left(), "bottom": a.bottom() == b.bottom()
                and a.left() == b.left(), "left": a.left() == b.left() and a.top() == b.top(),
                "right": a.right() == b.right() and a.top() == b.top()}
        for r in (a, b):
            w, h = min(band, r.width()), min(band, r.height())
            strips = {"top": QRect(r.left(), r.top(), r.width(), h),
                      "bottom": QRect(r.left(), r.bottom() - h + 1, r.width(), h),
                      "left": QRect(r.left(), r.top(), w, r.height()),
                      "right": QRect(r.right() - w + 1, r.top(), w, r.height())}
            out += [strip for side, strip in strips.items() if not same[side]]
        # zone gagnee / perdue, elargie de la bande : les arrondis et le bout des bords qui s'allongent
        out += [piece.adjusted(-band, -band, band, band).intersected(a.united(b)) for piece in _minus(a, b) + _minus(b, a)]
        return out

    def _repaint(self, rects: list):
        """Zones ancienne + nouvelle. Windows recoit pour chaque envoi le rectangle ENGLOBANT de la region : les deux
        traits d'un reticule jusqu'aux bords de la vue (une croix) font envoyer toute la vue a chaque mouvement
        (3 a 10 ms en 2400 x 1300, plus en 4K : « le reticule n'est pas fluide »). Les rectangles voisins sont fondus
        (l'ancien et le nouveau d'un meme trait), et quand il reste plusieurs grands morceaux (bande horizontale, bande
        verticale), chacun est peint et envoye a part. Decouper la region en rectangles disjoints faisait une quinzaine
        d'envois par mouvement, aussi chers qu'un seul."""
        merged = self._merge(rects)
        if len(merged) > 1:
            bounds = merged[0]
            for r in merged[1:]:
                bounds = bounds.united(r)
            if sum(r.width() * r.height() for r in merged) * 3 < bounds.width() * bounds.height():
                for r in merged:                # clairseme (une croix) : chaque morceau envoye a part
                    self.repaint(r)
                return
        region = QRegion()
        for r in merged:
            region = region.united(r)
        self.update(region)

    @staticmethod
    def _merge(rects: list) -> list:
        """Rectangles fondus tant que leur reunion ne coute pas beaucoup plus que leur somme."""
        rects = [QRect(r) for r in rects if not r.isEmpty()]
        merged = True
        while merged and len(rects) > 1:
            merged = False
            for i in range(len(rects)):
                for j in range(i + 1, len(rects)):
                    a, b = rects[i], rects[j]
                    union = a.united(b)
                    if union.width() * union.height() <= 1.5 * (a.width() * a.height() + b.width() * b.height()):
                        rects[i] = union
                        del rects[j]
                        merged = True
                        break
                if merged:
                    break
        return rects

    @staticmethod
    def _rects_of(ops) -> list:
        return [rect.toAlignedRect().adjusted(-1, -1, 1, 1) for _kind, rect, _args in ops]

    def update_all(self):
        self.update()

    # -- mise en page : (sorte, rectangle, arguments) par element ; la cle compare deux rendus --
    def _layout(self, state):
        if state is None:
            return [], (), QRect()
        look = state["look"]
        ops = []

        def add(kind, rect, *args):
            ops.append((kind, rect, args))
        to_view = self.to_view
        for segment, color in state.get("highlights", ()):
            a, b = to_view(segment[0]), to_view(segment[1])
            add("highlight", _line_rect(a, b, 4), a, b, color)
        for a, b in state.get("ghosts", ()):
            a, b = to_view(a), to_view(b)
            add("ghost", _line_rect(a, b, 2), a, b, look["ghost"])
        for kind, a, b in state.get("guides", ()):
            pa, pb = to_view(a), to_view(b)
            if kind in ("polar", "track", "ortho", "par"):
                # Ligne de suivi prolongee jusqu'au bord de la vue, comme AutoCAD (pointilles).
                d = pb - pa
                n = (d.x() ** 2 + d.y() ** 2) ** 0.5
                if n > 1e-6:
                    pb = pa + d * (4000.0 / n)
            add("guide", _line_rect(pa, pb, 2), kind, pa, pb, look["track"])
        for point in state.get("acquired", ()):
            c = to_view(point)
            add("acquired", QRectF(c.x() - 6, c.y() - 6, 12, 12), c, look["track"])
        for kind, a, b in state.get("preview", ()):
            a, b = to_view(a), to_view(b)
            add("preview", _line_rect(a, b, 2), a, b, look["rubber"])
        window = state.get("window")
        if window is not None:
            start, end, crossing = window[:3]
            a = to_view(start)
            b = QPointF(window[3]) if len(window) > 3 and window[3] is not None else to_view(end)
            rect = QRectF(a, b).normalized()
            frame = look.get("sel_crossing" if crossing else "sel_window") or {}
            pad = 2 + float(frame.get("thickness", 1))
            band = int(pad + max([0, *(frame.get("radius") or {}).values()]) + 3)   # bords a repeindre (`_dirty`)
            add("window", rect.adjusted(-pad, -pad, pad, pad), rect, crossing, band, a, b)
        path = state.get("path")
        if path:
            points = [to_view(point) for point in path]
            xs, ys = [q.x() for q in points], [q.y() for q in points]
            add("path", QRectF(min(xs) - 3, min(ys) - 3, max(xs) - min(xs) + 6, max(ys) - min(ys) + 6), points,
                look["rubber"])
        for point, color in state.get("grips", ()):
            c = to_view(point)
            size = look["grip_px"]
            add("grip", QRectF(c.x() - size / 2 - 2, c.y() - size / 2 - 2, size + 4, size + 4), c, color, size)
        snap = state.get("grid_snap")
        if snap is not None:
            c = to_view(snap[0])
            arm = min(max(snap[1], 6.0), look["marker_px"] * 1.6)
            pad = max(arm, look["marker_px"] / 2.0) + 4         # trait jusqu'a 3 pixels, cale au pixel
            add("grid_snap", QRectF(c.x() - pad, c.y() - pad, 2 * pad, 2 * pad), c, look["marker"],
                look["marker_px"] / 2.0, arm)
        cursor = state.get("cursor")
        if cursor is not None and state.get("paint_cursor"):
            half = look["pickbox_px"] if state.get("pickbox") else 0
            gap = state.get("grip_gap", 0) if not half else 0      # aimante sur une poignee : bras arretes a son bord
            badge = state.get("memory")
            box_only = state.get("box_only")                # commande de modification : le carre seul
            if look["crosshair"] and look.get("crosshair_full") and not box_only:
                # Reticule jusqu'aux bords de la vue : deux traits (zones minces), la boite de selection a part.
                w, h = float(self.width()), float(self.height())
                pad = max(2, half + 2)      # les traits englobent la boite : une seule zone par trait a repeindre
                stop = half or gap / (self.devicePixelRatioF() or 1.0)     # `gap` : pixels physiques
                add("cursor_h", QRectF(0, cursor.y() - pad, w, 2 * pad), cursor, look["cursor"], w, stop)
                add("cursor_v", QRectF(cursor.x() - pad, 0, 2 * pad, h), cursor, look["cursor"], h, stop)
                if half:
                    add("cursor", QRectF(cursor.x() - half - 2, cursor.y() - half - 2, 2 * half + 4, 2 * half + 4),
                        cursor, look["cursor"], 0, half)
            else:
                reach = look["crosshair_px"] if look["crosshair"] and not box_only else 0
                span = max(reach, half) + 2
                add("cursor", QRectF(cursor.x() - span, cursor.y() - span, 2 * span, 2 * span), cursor,
                    look["cursor"], reach, half, gap)
            if badge:
                add("badge", QRectF(cursor.x() - 2, cursor.y() - 2, BADGE_ROOM + 4, BADGE_ROOM + 4), cursor,
                    look["cursor"], badge)
        marker = state.get("marker")
        if marker is not None:
            c = to_view(marker[1])
            s = look["marker_px"] / 2.0 + 4
            add("marker", QRectF(c.x() - s, c.y() - s, 2 * s, 2 * s), marker[0], c, look["marker"],
                look["marker_px"] / 2.0)
        tip = state.get("tooltip")
        if tip and cursor is not None:
            self._layout_tip(add, cursor + QPointF(18, 22), tip, look)
        dyn = state.get("dyn")
        if dyn and cursor is not None:
            self._layout_dyn(add, cursor, dyn, look)
        key = tuple((kind, _pt(rect.topLeft()), _pt(rect.bottomRight()), args) for kind, rect, args in ops)
        bounds = QRectF()
        for _kind, rect, _args in ops:
            bounds = bounds.united(rect)
        return ops, key, bounds.toAlignedRect().adjusted(-1, -1, 1, 1) if ops else QRect()

    def _font(self, look):
        key = (look.get("font_family") or "Segoe UI", int(look.get("font_px", 12)))
        found = self._metrics.get(key)
        if found is None:
            font = QFont(key[0])
            font.setPixelSize(key[1])
            found = self._metrics[key] = (font, QFontMetricsF(font))
        return found

    def _layout_tip(self, add, at: QPointF, text: str, look):
        _font, metrics = self._font(look)
        lines = text.split("\n")
        width = max(metrics.horizontalAdvance(line) for line in lines) + 14
        height = metrics.height() * len(lines) + 8
        rect = self._clamp(QRectF(at.x(), at.y(), width, height))
        add("tip", rect.adjusted(-1, -1, 1, 1), rect, tuple(lines))

    def _layout_dyn(self, add, c: QPointF, dyn, look):
        """Saisie dynamique : un champ par valeur (distance / angle, ou X / Y) pres du curseur ; le champ
        actif est cerne de l'accent ; une valeur verrouillee (Tab) porte un repere."""
        _font, metrics = self._font(look)
        x = c.x() + 18
        y = c.y() - metrics.height() - 22
        if dyn.get("prompt"):
            prompt = dyn["prompt"]
            rect = self._clamp(QRectF(x, y - metrics.height() - 10, metrics.horizontalAdvance(prompt) + 14,
                                      metrics.height() + 6))
            add("dyn_prompt", rect.adjusted(-1, -1, 1, 1), rect, prompt)
        for label, text, active, locked in dyn.get("fields", ()):
            shown = f"{label} {text}".strip()
            pad = 12 if locked else 0
            rect = self._clamp(QRectF(x, y, max(70.0, metrics.horizontalAdvance(shown) + 14 + pad),
                                      metrics.height() + 6))
            add("dyn_field", rect.adjusted(-2, -2, 2, 2), rect, shown, bool(active), bool(locked), pad)
            x = rect.right() + 6

    def _clamp(self, rect: QRectF) -> QRectF:
        if rect.right() > self.width() - 4:
            rect.moveRight(self.width() - 4)
        if rect.bottom() > self.height() - 4:
            rect.moveBottom(self.height() - 4)
        if rect.left() < 4:
            rect.moveLeft(4)
        if rect.top() < 4:
            rect.moveTop(4)
        return rect

    # -- dessin --
    def paintEvent(self, event):
        if self.backdrop is None and self.backdrop_enabled and not self._capture_ok:
            self._render_backdrop()             # memoire de la fenetre illisible : seconde peinture
            self.setAttribute(Qt.WA_OpaquePaintEvent, True)
        if event.rect() == self.rect() or not self._ops:
            # Peinture complete (ou etat change sans `track`) : mise en page a jour.
            self._ops, self._key, self._rect = self._layout(self.ctl.overlay_state())
        painter = QPainter(self)
        if self.backdrop is not None and not (self._fresh and event.rect() == self.rect()):
            if isinstance(self.backdrop, QImage):
                for part in event.region():                 # seulement les zones a refaire (traits du reticule)
                    painter.drawImage(QRectF(part), self.backdrop, self._device_rect(part))
            else:
                painter.drawPixmap(0, 0, self.backdrop)
        self._fresh = False
        painter.setRenderHint(QPainter.Antialiasing, True)
        exposed = QRectF(event.rect())
        look = self.ctl.look
        painted_cursor = False
        for kind, rect, args in self._ops:
            if not rect.intersects(exposed):
                continue
            getattr(self, "_paint_" + kind)(painter, look, *args)
            painted_cursor = painted_cursor or kind.startswith("cursor")
        painter.end()
        if painted_cursor:
            self.ctl.painted_cursor_shown()

    def _device_rect(self, rect: QRect) -> QRectF:
        ratio = self.backdrop.devicePixelRatio() or 1.0
        x, y = rect.x() - self._origin.x(), rect.y() - self._origin.y()
        return QRectF(x * ratio, y * ratio, rect.width() * ratio, rect.height() * ratio)

    def _paint_highlight(self, painter, look, a, b, color):
        color = QColor(color)
        color.setAlpha(150)
        pen = QPen(color, 4.0)
        pen.setCapStyle(Qt.RoundCap)
        painter.setPen(pen)
        painter.drawLine(a, b)

    def _paint_ghost(self, painter, look, a, b, color):
        pen = QPen(QColor(color), 1.0, Qt.DashLine)
        pen.setCosmetic(True)
        painter.setPen(pen)
        painter.drawLine(a, b)

    def _paint_guide(self, painter, look, kind, a, b, color):
        painter.setPen(QPen(QColor(color), 1.0, Qt.DotLine if kind != "acquired" else Qt.DashLine))
        painter.drawLine(a, b)

    def _paint_acquired(self, painter, look, c, color):
        painter.setPen(QPen(QColor(color), 1.4))
        painter.drawLine(QPointF(c.x() - 4, c.y()), QPointF(c.x() + 4, c.y()))
        painter.drawLine(QPointF(c.x(), c.y() - 4), QPointF(c.x(), c.y() + 4))

    def _paint_preview(self, painter, look, a, b, color):
        pen = QPen(QColor(color), 1.2)
        pen.setCosmetic(True)
        painter.setPen(pen)
        painter.drawLine(a, b)

    def _paint_window(self, painter, look, rect, crossing, _band=0, a=None, b=None):
        """Fenetre (gauche -> droite) ou capture (droite -> gauche) : Reglages > Module CAD > Selection. Ses bords sont
        cales sur les PIXELS PHYSIQUES comme le reticule (`_centre_pixel` : pixel floor(x * ratio)) : le coin mobile
        tombe exactement sur la croix, trait net, a toute echelle d'affichage."""
        frame = dict(look.get("sel_crossing" if crossing else "sel_window") or DEFAULT_FRAMES[bool(crossing)])
        if a is not None and b is not None:
            ratio = self.devicePixelRatioF() or 1.0
            width = max(1, round(float(frame.get("thickness", 1)) * ratio))       # en pixels physiques
            centre = 0.5 if width % 2 else 0.0

            def snap(v):
                return (math.floor(v * ratio) + centre) / ratio
            xs = sorted((snap(a.x()), snap(b.x())))
            ys = sorted((snap(a.y()), snap(b.y())))
            rect = QRectF(QPointF(xs[0], ys[0]), QPointF(xs[1], ys[1]))
            frame["thickness"] = width / ratio
        paint_selection_frame(painter, rect, frame)

    def _paint_path(self, painter, look, points, color):
        """Trace a main levee d'AJUSTER."""
        pen = QPen(QColor(color), 1.2)
        pen.setCosmetic(True)
        painter.setPen(pen)
        painter.setBrush(Qt.NoBrush)
        painter.drawPolyline(QPolygonF(points))

    def _paint_grip(self, painter, look, c, color, size):
        paint_grips(painter, (c,), size, color, look.get("grip_border", "#ffffff"))

    def _paint_pixels(self, painter, rects, color):
        """Rectangles de pixels PHYSIQUES entiers : traits d'UN pixel, nets (jamais a cheval sur deux rangees)."""
        ratio = self.devicePixelRatioF() or 1.0
        unit = 1.0 / ratio
        painter.setRenderHint(QPainter.Antialiasing, False)
        ink = QColor(color)
        for x, y, w, h in rects:
            painter.fillRect(QRectF(x * unit, y * unit, w * unit, h * unit), ink)
        painter.setRenderHint(QPainter.Antialiasing, True)

    def _centre_pixel(self, c: QPointF) -> tuple:
        ratio = self.devicePixelRatioF() or 1.0
        return math.floor(c.x() * ratio), math.floor(c.y() * ratio), ratio

    def _paint_cursor(self, painter, look, c, color, reach, half, gap=0):
        cx, cy, ratio = self._centre_pixel(c)
        if gap and not half:
            rects = crosshair_rects(cx, cy, round(reach * ratio), gap, box=False)     # `gap` : pixels physiques
        else:
            rects = crosshair_rects(cx, cy, round(reach * ratio), round(half * ratio))
        self._paint_pixels(painter, rects, color)

    def _paint_cursor_h(self, painter, look, c, color, width, half=0):
        cx, cy, ratio = self._centre_pixel(c)
        end = math.ceil(width * ratio)
        gap = round(half * ratio)
        rects = [(0, cy, end, 1)] if gap <= 0 else [(0, cy, max(0, cx - gap), 1), (cx + gap + 1, cy, end, 1)]
        self._paint_pixels(painter, rects, color)

    def _paint_cursor_v(self, painter, look, c, color, height, half=0):
        cx, cy, ratio = self._centre_pixel(c)
        end = math.ceil(height * ratio)
        gap = round(half * ratio)
        rects = [(cx, 0, 1, end)] if gap <= 0 else [(cx, 0, 1, max(0, cy - gap)), (cx, cy + gap + 1, 1, end)]
        self._paint_pixels(painter, rects, color)

    def _paint_badge(self, painter, look, c, color, source):
        paint_memory_badge(painter, c.x() + 0.5, c.y() + 0.5, source, color)

    @staticmethod
    def _marker_pen(painter, look, c: QPointF, color, s: float) -> tuple:
        """Peintre passe en pixels PHYSIQUES pour un marqueur d'epaisseur EXACTE (Reglages : 1, 2 ou 3 pixels) : centre
        cale pour que chaque trait couvre des pixels entiers (epaisseur impaire : centre d'un pixel ; paire : son
        coin), demi-cote entier — le meme trait sur tout le pourtour (signale : « pas constant sur tout son
        pourtour », le centre tombait n'importe ou entre deux pixels) ; courbes et diagonales anticrenelees. Rend
        (x, y, demi-cote) dans ce repere ; l'appelant fait `painter.save()` / `restore()`."""
        ratio = painter.device().devicePixelRatioF() or 1.0
        q = painter.transform().map(c)
        width = max(1, round(float(look.get("marker_width", 2)) * ratio))
        shift = 0.5 if width % 2 else 0.0
        x = math.floor(q.x() * ratio) + shift
        y = math.floor(q.y() * ratio) + shift
        painter.setTransform(QTransform.fromScale(1.0 / ratio, 1.0 / ratio))
        painter.setRenderHint(QPainter.Antialiasing, True)
        pen = QPen(QColor(color), width)
        pen.setJoinStyle(Qt.MiterJoin)
        pen.setCapStyle(Qt.SquareCap)
        painter.setPen(pen)
        painter.setBrush(Qt.NoBrush)
        return x, y, max(1.0, float(round(s * ratio)))

    def _paint_grid_snap(self, painter, look, c, color, s, arm):
        """Accrochage a la grille (RESOL) : losange sur le croisement vise + amorces des deux lignes de grille."""
        ratio = painter.device().devicePixelRatioF() or 1.0
        painter.save()
        x, y, s = self._marker_pen(painter, look, c, color, s)
        arm = round(arm * ratio)
        painter.drawPolygon(QPolygonF([QPointF(x, y - s), QPointF(x + s, y), QPointF(x, y + s), QPointF(x - s, y)]))
        faint = QColor(color)
        faint.setAlphaF(0.55)
        painter.setPen(QPen(faint, max(1, round(ratio))))
        for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1)):
            painter.drawLine(QPointF(x + dx * s, y + dy * s), QPointF(x + dx * arm, y + dy * arm))
        painter.restore()

    def _paint_marker(self, painter, look, mode, c: QPointF, color, s):
        painter.save()
        try:
            self._draw_marker(painter, look, mode, c, color, s)
        finally:
            painter.restore()

    def _draw_marker(self, painter, look, mode, c: QPointF, color, s):
        x, y, s = self._marker_pen(painter, look, c, color, s)
        c = QPointF(x, y)
        color = QColor(color)
        style = MARKER_STYLE.get(mode, "square")
        if style == "square":
            painter.drawRect(QRectF(x - s, y - s, 2 * s, 2 * s))
        elif style == "triangle":
            painter.drawPolygon(QPolygonF([QPointF(x, y - s), QPointF(x + s, y + s * 0.8), QPointF(x - s, y + s * 0.8)]))
        elif style == "circle":
            painter.drawEllipse(c, s, s)
        elif style == "circle_x":
            painter.drawEllipse(c, s, s)
            painter.drawLine(QPointF(x - s * 0.7, y - s * 0.7), QPointF(x + s * 0.7, y + s * 0.7))
            painter.drawLine(QPointF(x - s * 0.7, y + s * 0.7), QPointF(x + s * 0.7, y - s * 0.7))
        elif style == "diamond":
            painter.drawPolygon(QPolygonF([QPointF(x, y - s), QPointF(x + s, y), QPointF(x, y + s), QPointF(x - s, y)]))
        elif style in ("x", "x_square"):
            painter.drawLine(QPointF(x - s, y - s), QPointF(x + s, y + s))
            painter.drawLine(QPointF(x - s, y + s), QPointF(x + s, y - s))
            if style == "x_square":
                painter.drawRect(QRectF(x - s, y - s, 2 * s, 2 * s))
        elif style == "dots":
            painter.setBrush(color)
            dot = 1.4 * (painter.device().devicePixelRatioF() or 1.0)
            for dx in (-s, 0.0, s):
                painter.drawEllipse(QPointF(x + dx, y), dot, dot)
            painter.setBrush(Qt.NoBrush)
        elif style == "perp":
            painter.drawLine(QPointF(x - s, y + s), QPointF(x + s, y + s))
            painter.drawLine(QPointF(x - s, y + s), QPointF(x - s, y - s))
            painter.drawPolyline(QPolygonF([QPointF(x - s, y), QPointF(x, y), QPointF(x, y + s)]))
        elif style == "tangent":
            painter.drawEllipse(c, s * 0.8, s * 0.8)
            painter.drawLine(QPointF(x - s, y - s * 0.8), QPointF(x + s, y - s * 0.8))
        elif style == "hourglass":
            painter.drawPolygon(QPolygonF([QPointF(x - s, y - s), QPointF(x + s, y - s), QPointF(x - s, y + s),
                                           QPointF(x + s, y + s)]))
        elif style == "parallel":
            painter.drawLine(QPointF(x - s, y + s * 0.4), QPointF(x - s * 0.2, y - s))
            painter.drawLine(QPointF(x + s * 0.2, y + s), QPointF(x + s, y - s * 0.4))
        elif style == "insert":
            painter.drawRect(QRectF(x - s, y - s, s, s))
            painter.drawRect(QRectF(x, y, s, s))

    def _paint_tip(self, painter, look, rect, lines):
        font, metrics = self._font(look)
        painter.setFont(font)
        painter.setPen(QPen(QColor(look["tip_border"]), 1.0))
        painter.setBrush(QColor(look["tip_bg"]))
        painter.drawRoundedRect(rect, 4, 4)
        painter.setPen(QColor(look["tip_fg"]))
        for n, line in enumerate(lines):
            painter.drawText(QPointF(rect.left() + 7, rect.top() + 4 + metrics.ascent() + n * metrics.height()), line)
        painter.setBrush(Qt.NoBrush)

    def _paint_dyn_prompt(self, painter, look, rect, prompt):
        font, metrics = self._font(look)
        painter.setFont(font)
        painter.setPen(QPen(QColor(look["tip_border"]), 1.0))
        painter.setBrush(QColor(look["tip_bg"]))
        painter.drawRoundedRect(rect, 4, 4)
        painter.setPen(QColor(look["tip_fg"]))
        painter.drawText(QPointF(rect.left() + 7, rect.top() + 3 + metrics.ascent()), prompt)
        painter.setBrush(Qt.NoBrush)

    def _paint_dyn_field(self, painter, look, rect, shown, active, locked, pad):
        font, metrics = self._font(look)
        painter.setFont(font)
        painter.setPen(QPen(QColor(look["accent"]) if active else QColor(look["tip_border"]), 1.4 if active else 1.0))
        painter.setBrush(QColor(look["field_bg"]) if active else QColor(look["tip_bg"]))
        painter.drawRoundedRect(rect, 3, 3)
        if locked:
            painter.setPen(Qt.NoPen)
            painter.setBrush(QColor(look["accent"]))
            painter.drawRoundedRect(QRectF(rect.left() + 5, rect.top() + 5, 6, rect.height() - 10), 2, 2)
        painter.setPen(QColor(look["tip_fg"]))
        painter.drawText(QPointF(rect.left() + 7 + pad, rect.top() + 3 + metrics.ascent()), shown)
        painter.setBrush(Qt.NoBrush)
