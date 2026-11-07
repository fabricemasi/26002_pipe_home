"""Événements longs en barres (vues Jour / Semaine), d'après la maquette Claude Design « Agenda — sombre » (v10) et
la cote de l'utilisateur (2026-11-07) :

- barre pleine d'épaisseur T (`agenda_bar_width`) collée au bord gauche de la colonne, AUCUN texte ;
- en haut, chevron à 45° dont la POINTE est sur l'heure de début (il dépasse donc de A au-dessus) ; en bas, le même
  chevron en miroir, pointe sur l'heure de fin. A = épaisseur de la flèche (`agenda_arrow_width`), distance du flanc
  de la barre à la pointe ;
- arrondis : coins et creux = A / 5, pointes = A / 10 ; suite d'un jour précédent / suite le lendemain : bord droit ;
- relief discret : liseré clair en haut à gauche et sombre en bas à droite (d'après la forme, flèches comprises),
  ombre portée légère ;
- poignées : deux traits sur chaque pointe (début / fin, glisser en hauteur), trois points au milieu de l'événement
  (le décaler) ; montrées au survol de la barre, sur la barre épinglée et pendant le glisser ;
- encart : titre, horaires et durée, calendrier et projet ; relié à la barre par un trait de 24 × 14 px, à droite
  (à gauche près du bord droit), au-dessus du point visé (dessous près du haut). Épinglé : bouton × et, en vue
  Semaine, « Ouvrir la journée ».

Sans état : géométrie (chemins, zones des poignées, encart) et peinture. L'état (survol, épinglé, glisser) est dans
`timegrid._Canvas`. Les chemins sont calculés à la disposition (`build_seg`), jamais à la peinture."""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from datetime import timedelta

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QPainter, QPainterPath, QPen

from ..core import timeutil as tu
from . import theme as th
from .painting import wrap_lines
from .widgets import brighter, draw_icon

RELIEF = 1.2                   # décalage du biseau (px)
SHADOW = (0.6, 1.2)            # ombre portée (px)
LANE_GAP = 3                   # écart entre deux barres simultanées / entre la pointe et les blocs
GRIP_MIN = 14                  # hauteur minimale de la zone saisissable d'une pointe
MID_H = 22                     # zone saisissable du milieu
POP_W = 236                    # encart (maquette : .pop width 236)
POP_LEAD = (24, 14)            # trait de l'encart
POP_FLIP = 270                 # l'encart passe à gauche si la place à droite est plus courte
POP_BELOW = 120                # l'encart passe dessous si le point visé est à moins de 120 px du haut visible
MIN_MINUTES = 30               # durée minimale au glisser


def lane_width(T: float, A: float) -> float:
    return T + A + LANE_GAP


def round_path(pts) -> QPainterPath:
    """Contour fermé aux coins arrondis : `pts` = [(x, y, rayon), …] dans le sens horaire. Chaque coin devient un
    arc tangent aux deux côtés (courbe de Bézier cubique ; convexe ou rentrant selon le sens du virage) ; le rayon
    est réduit si un côté est trop court."""
    n = len(pts)
    path = QPainterPath()
    for i in range(n):
        px, py, r = pts[i]
        ax, ay = pts[i - 1][0], pts[i - 1][1]
        bx, by = pts[(i + 1) % n][0], pts[(i + 1) % n][1]
        ux, uy = ax - px, ay - py
        vx, vy = bx - px, by - py
        ul, vl = math.hypot(ux, uy) or 1.0, math.hypot(vx, vy) or 1.0
        ux, uy, vx, vy = ux / ul, uy / ul, vx / vl, vy / vl
        half = math.acos(max(-1.0, min(1.0, ux * vx + uy * vy))) / 2
        t = min(r / math.tan(half), ul / 2, vl / 2) if r > 0 and half > 1e-6 else 0.0
        p1 = QPointF(px + ux * t, py + uy * t)
        if i == 0:
            path.moveTo(p1)
        else:
            path.lineTo(p1)
        if t > 0:
            rr = t * math.tan(half)
            k = 4.0 / 3.0 * math.tan((math.pi - 2 * half) / 4) * rr
            p2 = QPointF(px + vx * t, py + vy * t)
            path.cubicTo(QPointF(p1.x() - ux * k, p1.y() - uy * k), QPointF(p2.x() - vx * k, p2.y() - vy * k), p2)
    path.closeSubpath()
    return path


@dataclass(slots=True)
class BarSeg:
    """Morceau de barre d'un événement long dans une colonne (un jour)."""
    occ: object
    col: int
    x: float                   # bord gauche de la barre
    top: float                 # haut du tracé
    height: float
    is_start: bool
    is_end: bool
    path: QPainterPath
    light: QPainterPath
    dark: QPainterPath
    shadow: QPainterPath
    bounds: QRectF             # zone à repeindre (tracé, anneau, ombre, poignées)
    grips: list = field(default_factory=list)      # [(« s » | « e » | « m », QRectF)]


def build_seg(occ, col: int, x: float, ya: float, yb: float, is_start: bool, is_end: bool, T: float, A: float,
              mid_y: float | None = None, grips: bool = True) -> BarSeg:
    """`ya` / `yb` : hauteur (px) du début / de la fin visibles dans la colonne ; `mid_y` : milieu de l'événement
    s'il tombe dans cette colonne."""
    top = ya - A if is_start else ya
    bottom = yb + A if is_end else yb
    h = max(bottom - top, (2 * A if is_start else 0) + (2 * A if is_end else 0) + 4)
    r1, r2 = A / 5, A / 10
    pts = [(0, 0, r1), (T, 0, r1), (T + A, A, r2), (T, 2 * A, r1)] if is_start else [(0, 0, 0), (T, 0, 0)]
    pts += [(T, h - 2 * A, r1), (T + A, h - A, r2), (T, h, r1), (0, h, r1)] if is_end else [(T, h, 0), (0, h, 0)]
    path = round_path(pts).translated(x, top)
    light = path.subtracted(path.translated(RELIEF, RELIEF))
    dark = path.subtracted(path.translated(-RELIEF, -RELIEF))
    shadow = path.translated(*SHADOW)
    zones = []
    if grips:
        zh, zw = max(2 * A, GRIP_MIN), max(T + A, 16)
        s_bottom, e_top = top, top + h
        if is_start:
            r = QRectF(x, top + A - zh / 2, zw, zh)
            zones.append(("s", r))
            s_bottom = r.bottom()
        if is_end:
            r = QRectF(x, top + h - A - zh / 2, zw, zh)
            zones.append(("e", r))
            e_top = r.top()
        if mid_y is not None:
            mw = max(T + 6, 14)
            r = QRectF(x + (T - mw) / 2, mid_y - MID_H / 2, mw, MID_H)
            if r.top() >= s_bottom and r.bottom() <= e_top:
                zones.append(("m", r))
    bounds = path.boundingRect().adjusted(-3, -3, 4, 4)
    for _k, r in zones:
        bounds = bounds.united(r)
    return BarSeg(occ, col, x, top, h, is_start, is_end, path, light, dark, shadow, bounds, zones)


def hit(seg: BarSeg, pos: QPointF) -> str | None:
    """« s » / « e » / « m » (poignée), « body » (barre) ou None."""
    for kind, r in seg.grips:
        if r.contains(pos):
            return kind
    return "body" if seg.path.contains(pos) else None


def paint_seg(p: QPainter, seg: BarSeg, bar: QColor, T: float, A: float, selected: bool, hover: bool,
              accent: QColor, dim: float = 1.0, grips: bool = False, hot: str | None = None) -> None:
    fill = brighter(bar, 1.15) if hover else bar
    p.save()
    p.setOpacity(dim)
    p.setRenderHint(QPainter.Antialiasing, True)
    p.setPen(Qt.NoPen)
    p.fillPath(seg.shadow, QColor(0, 0, 0, 77))
    if selected:
        pen = QPen(accent, 3)
        pen.setJoinStyle(Qt.RoundJoin)
        p.strokePath(seg.path, pen)
    p.fillPath(seg.path, fill)
    p.fillPath(seg.light, QColor(255, 255, 255, 77))
    p.fillPath(seg.dark, QColor(0, 0, 0, 61))
    if grips:
        lw = max(4.0, T + A - 8)
        for kind, r in seg.grips:
            c = QColor(255, 255, 255, 255 if kind == hot else 191)
            cy = r.center().y()
            if kind in ("s", "e"):
                p.fillRect(QRectF(seg.x + 2, cy - 2.5, lw, 1), c)
                p.fillRect(QRectF(seg.x + 2, cy + 1.5, lw, 1), c)
            else:
                p.setBrush(c)
                cx = seg.x + T / 2
                for dy in (-5, 0, 5):
                    p.drawEllipse(QRectF(cx - 1.5, cy + dy - 1.5, 3, 3))
    p.restore()


# -- encart -----------------------------------------------------------------------------------------------------

def _hours(minutes: float) -> str:
    h = minutes / 60
    return f"{h:g} h" if abs(h - round(h)) < 1e-9 else f"{h:.1f} h".replace(".", ",")


def when_text(start, end, h24: bool) -> str:
    """« 10:00 – 15:00 · 5 h », ou sur plusieurs jours « jeu. 6:00 → ven. 9:00 · 27 h » (maquette)."""
    minutes = (end - start).total_seconds() / 60
    last = (end - timedelta(seconds=1)).date()          # une fin à minuit appartient à la veille
    if last != start.date():
        a, b = tu.DAYS_LONG[start.weekday()][:3], tu.DAYS_LONG[end.weekday()][:3]
        span = f"{a}. {tu.fmt_time(start, h24)} → {b}. {tu.fmt_time(end, h24)}"
    else:
        span = tu.fmt_range(start, end, h24)
    return f"{span} · {_hours(minutes)}"


@dataclass(slots=True)
class Popover:
    box: QRectF
    lead_from: QPointF
    lead_to: QPointF
    title: list
    when: str
    meta: str
    colors: tuple
    pinned: bool
    can_open: bool
    close_r: QRectF | None
    open_r: QRectF | None

    def rect(self) -> QRectF:
        """Zone à repeindre (encart, trait, ombre)."""
        lead = QRectF(self.lead_from, self.lead_to).normalized()
        return self.box.adjusted(-4, -4, 4, 10).united(lead.adjusted(-2, -2, 2, 2))


def layout_popover(x_left: float, x_right: float, y: float, flip: bool, below: bool, title: str, when: str,
                   meta: str, colors, pinned: bool, can_open: bool) -> Popover:
    """Encart ancré au point (flanc de la barre, `y`) : trait de 24 × 14 px puis la boîte (maquette `popGeo`)."""
    lw, lh = POP_LEAD
    px = x_left if flip else x_right
    bx = px - lw if flip else px + lw
    by = y + lh if below else y - lh
    text_w = POP_W - 12 - 8 - (30 if pinned else 0)
    lines = wrap_lines(title or "(Sans titre)", 13, 600, text_w, 3)
    height = 9 + 17 * max(1, len(lines)) + 3 + 16 + 6 + 16 + (24 if can_open else 0) + 10
    left = bx - POP_W if flip else bx
    top = by if below else by - height
    box = QRectF(left, top, POP_W, height)
    close_r = QRectF(box.right() - 8 - 24 + 2, box.top() + 5, 24, 24) if pinned else None
    open_r = None
    if can_open:
        fm = th.metrics(12, 600)
        open_r = QRectF(box.left() + 12, box.bottom() - 10 - 16, fm.horizontalAdvance("Ouvrir la journée") + 2, 16)
    return Popover(box, QPointF(px, y), QPointF(bx, by), lines, when, meta, colors, pinned, can_open, close_r, open_r)


def popover_hit(pop: Popover, pos: QPointF) -> str | None:
    if pop.close_r is not None and pop.close_r.contains(pos):
        return "close"
    if pop.open_r is not None and pop.open_r.contains(pos):
        return "open"
    return "box" if pop.box.contains(pos) else None


def paint_popover(p: QPainter, t, pop: Popover, hot: str | None = None) -> None:
    _bg, bar, _fg = pop.colors
    p.save()
    p.setRenderHint(QPainter.Antialiasing, True)
    p.setPen(QPen(bar, 1.5))
    p.drawLine(pop.lead_from, pop.lead_to)
    box = pop.box
    p.setPen(Qt.NoPen)
    for i, alpha in ((6, 18), (4, 22), (2, 26)):        # ombre douce (maquette : 0 10px 28px rgba(0,0,0,.28))
        p.setBrush(QColor(0, 0, 0, alpha))
        p.drawRoundedRect(box.adjusted(-i / 2, i, i / 2, i), 8 + i / 2, 8 + i / 2)
    p.setBrush(t.c("bar"))
    p.setPen(QPen(bar, 1.5))
    p.drawRoundedRect(box.adjusted(0.75, 0.75, -0.75, -0.75), 8, 8)
    x, y = box.left() + 12, box.top() + 9
    text_w = box.width() - 12 - 8 - (30 if pop.pinned else 0)
    p.setFont(th.font(13, 600))
    p.setPen(t.c("strong"))
    for line in pop.title:
        p.drawText(QRectF(x, y, text_w, 17), Qt.AlignLeft | Qt.AlignVCenter, line)
        y += 17
    y += 3
    p.setFont(th.font(12))
    p.setPen(t.c("muted"))
    p.drawText(QRectF(x, y, box.width() - 20, 16), Qt.AlignLeft | Qt.AlignVCenter, pop.when)
    y += 16 + 6
    p.setPen(Qt.NoPen)
    p.setBrush(bar)
    p.drawEllipse(QRectF(x, y + 4, 8, 8))
    p.setPen(t.c("dim"))
    p.drawText(QRectF(x + 14, y, box.width() - 34, 16), Qt.AlignLeft | Qt.AlignVCenter, pop.meta)
    if pop.close_r is not None:
        if hot == "close":
            p.setPen(Qt.NoPen)
            p.setBrush(t.c("btn"))
            p.drawRoundedRect(pop.close_r, 5, 5)
        c = pop.close_r.center()
        draw_icon(p, "close", QRectF(c.x() - 6, c.y() - 6, 12, 12), t.c("strong" if hot == "close" else "muted"), 1.6)
    if pop.open_r is not None:
        f = th.font(12, 600)
        f.setUnderline(hot == "open")
        p.setFont(f)
        p.setPen(t.c("section"))
        p.drawText(pop.open_r, Qt.AlignLeft | Qt.AlignVCenter, "Ouvrir la journée")
    p.restore()
