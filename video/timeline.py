"""Timeline du module vidéo : graduations en numéros d'image, en secondes ou en timecode, tête de lecture, clic / glisser =
aller à l'image (scrubbing), molette = zoom autour du curseur (de toute la durée à quelques images),
Maj + molette ou bouton du milieu = défilement, double-clic = ajuster à la durée, poignées IN / OUT à tirer,
images en cache marquées. Positions = RANGS d'image entiers (aucune approximation en secondes). L'unité « secondes »
ne change que l'AFFICHAGE : graduations posées au temps réel de chaque image (`time_of` / `index_at_time` de la
source : horodatages des vidéos à cadence variable, cadences fractionnaires 23,976 / 29,97 sans dérive)."""
from __future__ import annotations

import math
from fractions import Fraction

from PySide6.QtCore import QPointF, QRectF, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QFont, QFontMetrics, QPainter, QPen, QPixmap, QPolygonF
from PySide6.QtWidgets import QWidget

from video.media import format_timecode

_STEPS = (1, 2, 5, 10, 20, 25, 50, 100, 200, 250, 500, 1000, 2000, 2500, 5000, 10000, 20000, 50000, 100000)
# Pas des graduations en secondes.
_SECOND_STEPS = (0.01, 0.02, 0.05, 0.1, 0.2, 0.5, 1, 2, 5, 10, 15, 30, 60, 120, 300, 600, 900, 1800, 3600, 7200,
                 18000, 36000)


def format_seconds(seconds: float, step: float = 1.0, precise: bool = False) -> str:
    """« 00:01 », « 01:02:03 », avec les décimales utiles au pas (« 00:01.5 ») ; `precise` : millisecondes."""
    seconds = max(0.0, float(seconds))
    if precise:
        decimals = 3
    elif step >= 1:
        decimals = 0
    else:
        decimals = 1 if step >= 0.1 else 2
    if decimals:
        value = round(seconds, decimals)
        whole = int(value)
        frac_text = f"{value - whole:.{decimals}f}"[1:]
    else:
        frac_text = ""
        whole = int(round(seconds))
    h, rest = divmod(whole, 3600)
    m, sec = divmod(rest, 60)
    head = f"{h}:{m:02d}:{sec:02d}" if h else f"{m:02d}:{sec:02d}"
    return head + frac_text


class Timeline(QWidget):
    seekRequested = Signal(int)
    scrubStarted = Signal()
    scrubFinished = Signal()
    rangeChanged = Signal(object, object)       # IN, OUT (rangs ou None)
    thumbsWanted = Signal(object)               # rangs des miniatures visibles (vue changée)
    thumbHeightChanged = Signal(int)            # hauteur de la bande des miniatures choisie à la souris (relâchée)

    THUMB_MIN, THUMB_MAX = 16, 240              # bornes de la hauteur des miniatures (px)
    EDGE = 4                                    # zone de saisie du bord haut de la bande (px de part et d'autre)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMouseTracking(True)
        self.setFocusPolicy(Qt.NoFocus)
        self.setAttribute(Qt.WA_OpaquePaintEvent, True)      # peint tout son rectangle
        self.count = 1
        self.first_number = 0
        self.fps = Fraction(24)
        self.tc_start = 0
        self.current = 0
        self.in_point: int | None = None
        self.out_point: int | None = None
        self.cached: set[int] = set()
        self.missing: set[int] = set()
        self._v0, self._v1 = 0.0, 1.0           # vue : rangs [v0, v1]
        self._drag = None
        self.time_of = lambda i: float(i) / float(self.fps or 24)
        self.index_at_time = lambda t: float(t) * float(self.fps or 24)
        self.thumbs: dict[int, object] = {}     # rang -> QImage (miniatures, lues en fond par le module)
        self.thumb_aspect = 16 / 9
        self.thumb_h = 40                       # hauteur de la bande des miniatures (réglage, tirée à la souris)
        self.auto_thumbs = False                # miniatures relues à chaque changement de vue (non : bouton)
        self._requested_view = None             # vue de la dernière demande de miniatures
        self._req_quantum = 1                   # écart (en images) entre les miniatures demandées
        self._ruler_h = 22
        # Fond (règle, graduations, miniatures, sélection, cache) gardé en image : pendant la lecture seule la tête
        # de lecture change, la repeindre entière coûtait ~4 ms par image (graduations, miniatures, textes).
        self._bg = None
        self._bg_key = None
        self._ver = 0                           # change avec tout ce que montre le fond (hors vue / taille)
        self._thumb_timer = QTimer(self)
        self._thumb_timer.setSingleShot(True)
        self._thumb_timer.setInterval(80)
        self._thumb_timer.timeout.connect(lambda: self.thumbsWanted.emit(self.thumb_indices()))
        self.look = {}
        self.set_look({})

    # -- réglages --

    def set_look(self, look: dict):
        self.look = {"height": 54, "tick": 8, "density": 80, "show_tc": False, "show_frames": True,
                     "playhead": "#ff5a36", "selection": "#3a6ea5", "in_color": "#4caf50", "out_color": "#e05252",
                     "bg": "#17191b", "ruler": "#2a2d31", "text": "#a8adb3", "cache": "#3d7a4a",
                     "zoom_cursor": True, "zoom_step": 25, **look}
        before = self.thumb_h
        if "thumb_height" in look and self._drag is None:
            self.thumb_h = self._clamp_thumb(look["thumb_height"])
        self._ver += 1
        self._apply_height()
        if self.thumb_h != before:
            self._views_changed()

    def _clamp_thumb(self, value) -> int:
        return max(self.THUMB_MIN, min(self.THUMB_MAX, int(value)))

    def _apply_height(self):
        """Hauteur = règle (d'après « Hauteur de la timeline ») + bande des miniatures (sa propre hauteur) : agrandir
        les miniatures ne change ni la règle ni le zoom horizontal."""
        base = int(self.look["height"])
        self._ruler_h = max(16, int(base * 0.42))
        if self.look.get("thumbs", True):
            self.setFixedHeight(self._ruler_h + 1 + self.thumb_h + 4)
        else:
            self.setFixedHeight(base)
        self.update()

    def set_thumb_height(self, value):
        self.thumb_h = self._clamp_thumb(value)
        self._apply_height()
        self._views_changed()

    def set_media(self, count: int, first_number: int, fps: Fraction, tc_start: int = 0, missing=(),
                  keep_thumbs: bool = False):
        self.count = max(1, int(count))
        self.first_number = int(first_number)
        self.fps = fps or Fraction(24)
        self.tc_start = int(tc_start)
        self.missing = set(missing)
        self.in_point = self.out_point = None
        if not keep_thumbs:
            self.thumbs = {}
            self._requested_view = None
        self._ver += 1
        self.fit()

    def set_time_mapping(self, time_of, index_at_time):
        """Rang <-> temps réel (secondes) de la source : graduations du mode « secondes »."""
        self.time_of = time_of
        self.index_at_time = index_at_time
        self._ver += 1
        self.update()

    def set_current(self, index: int):
        index = max(0, min(int(index), self.count - 1))
        if index != self.current:
            self.current = index
            self._follow()
            self.update()

    # -- miniatures --

    def _thumb_band(self) -> tuple[float, float]:
        """(haut, hauteur) de la bande des miniatures : sous la règle ; (0, 0) si la timeline est trop basse ou
        les miniatures coupées."""
        if not self.look.get("thumbs", True):
            return 0.0, 0.0
        return self._ruler_h + 1.0, float(self.thumb_h)

    def _thumb_slots(self):
        top, band = self._thumb_band()
        if band <= 0 or self.count <= 1:
            return [], 1
        slot_w = max(12.0, band * self.thumb_aspect)
        span = max(1e-9, self._v1 - self._v0)
        per_slot = span * slot_w / max(1, self.width())
        quantum = 1 << max(0, int(math.floor(math.log2(max(1.0, per_slot)))))   # rangs réutilisés d'un zoom à l'autre
        slots = []
        x = 0.0
        while x < self.width():
            centre = self._v0 + (x + slot_w / 2) / max(1, self.width()) * span
            index = int(round(centre / quantum)) * quantum
            if 0 <= index < self.count:
                slots.append((x, slot_w, index))
            x += slot_w
        return slots, quantum

    def thumb_indices(self) -> list[int]:
        slots, _q = self._thumb_slots()
        return [index for _x, _w, index in slots]

    def add_thumb(self, index: int, image):
        if self.thumbs.get(int(index)) is image:
            return
        self.thumbs[int(index)] = image
        if image is not None and image.height():
            aspect = image.width() / image.height()
            if abs(aspect - self.thumb_aspect) > 1e-3:
                # Rapport réel (arrondi du décodage) : les cases bougent, les rangs visibles aussi -> redemandés,
                # seulement si la vue est encore celle de la demande (sinon rien ne part tout seul).
                self.thumb_aspect = aspect
                if self._requested_view == self._view_key():
                    self.request_thumbs()
        self._ver += 1
        self.update()

    def _views_changed(self):
        """Vue changée (zoom, défilement, taille) : les miniatures ne sont PAS relues toutes seules (demande de
        l'utilisateur) — seulement par le bouton du module (`request_thumbs`) ; `auto_thumbs` le rallume."""
        if (self.auto_thumbs and self._thumb_band()[1] > 0
                and not (self._drag and self._drag[0] == "thumbsize")):
            self._thumb_timer.start()

    def _view_key(self):
        return (round(self._v0, 6), round(self._v1, 6), self.thumb_h, self.width())

    def request_thumbs(self):
        """Miniatures de la vue ACTUELLE demandées (bouton « Miniatures » du module)."""
        if self._thumb_band()[1] <= 0:
            return
        self._requested_view = self._view_key()
        self._req_quantum = self._thumb_slots()[1]
        self.thumbsWanted.emit(self.thumb_indices())

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._views_changed()

    def set_cached(self, cached: set[int]):
        if cached == self.cached:
            return
        self.cached = cached
        self._ver += 1
        self.update()

    def set_range(self, in_point, out_point, emit=True):
        if in_point is not None and out_point is not None and in_point > out_point:
            in_point, out_point = out_point, in_point
        self.in_point, self.out_point = in_point, out_point
        self._ver += 1
        if emit:
            self.rangeChanged.emit(in_point, out_point)
        self.update()

    def range(self) -> tuple[int, int]:
        """Plage effective (bornes INCLUSES) : IN / OUT, sinon tout."""
        lo = self.in_point if self.in_point is not None else 0
        hi = self.out_point if self.out_point is not None else self.count - 1
        return lo, hi

    # -- vue --

    def fit(self):
        self._v0, self._v1 = -0.5, self.count - 0.5
        self._views_changed()
        self.update()

    def view(self) -> tuple[float, float]:
        return self._v0, self._v1

    def _x_of(self, index: float) -> float:
        span = max(1e-9, self._v1 - self._v0)
        return (index - self._v0) / span * self.width()

    def _index_at(self, x: float) -> int:
        span = self._v1 - self._v0
        return max(0, min(self.count - 1, int(round(self._v0 + x / max(1, self.width()) * span))))

    def zoom(self, steps: float, anchor_x: float | None = None):
        span = self._v1 - self._v0
        factor = (1.0 + int(self.look.get("zoom_step", 25)) / 100.0) ** (-steps)
        new = max(4.0, min(self.count * 1.05 + 1, span * factor))
        if anchor_x is None or not self.look.get("zoom_cursor", True):
            anchor = (self.current if self._v0 <= self.current <= self._v1 else (self._v0 + self._v1) / 2)
            t = (anchor - self._v0) / span
        else:
            t = anchor_x / max(1, self.width())
            anchor = self._v0 + t * span
        self._v0 = anchor - t * new
        self._v1 = self._v0 + new
        self._clamp_view()
        self._views_changed()
        self.update()

    def scroll(self, frames: float):
        self._v0 += frames
        self._v1 += frames
        self._clamp_view()
        self._views_changed()
        self.update()

    def _clamp_view(self):
        span = self._v1 - self._v0
        lo, hi = -0.5, self.count - 0.5
        if span >= hi - lo:
            self._v0, self._v1 = lo - (span - (hi - lo)) / 2, hi + (span - (hi - lo)) / 2
            return
        if self._v0 < lo:
            self._v0, self._v1 = lo, lo + span
        if self._v1 > hi:
            self._v0, self._v1 = hi - span, hi

    def _follow(self):
        """La tête de lecture sortie de la vue : la vue la suit (page suivante)."""
        span = self._v1 - self._v0
        if self.current > self._v1 - 0.5:
            self._v0 = self.current - span * 0.1
            self._v1 = self._v0 + span
            self._clamp_view()
        elif self.current < self._v0 + 0.5:
            self._v1 = self.current + span * 0.1
            self._v0 = self._v1 - span
            self._clamp_view()
        else:
            return
        self._views_changed()

    # -- texte --

    def label(self, index: int) -> str:
        if self.look.get("seconds"):
            return format_seconds(self.time_of(index), precise=True)
        parts = []
        if self.look.get("show_frames", True):
            parts.append(str(self.first_number + index))
        if self.look.get("show_tc", False):
            parts.append(format_timecode(index, self.fps, self.tc_start))
        return "  ".join(parts) or str(self.first_number + index)

    # -- dessin --

    def paintEvent(self, event):
        p = QPainter(self)
        w, h = self.width(), self.height()
        dpr = self.devicePixelRatioF()
        key = (w, h, dpr, self._v0, self._v1, self._ver, id(self.look))
        if self._bg is None or self._bg_key != key:
            self._bg = QPixmap(int(math.ceil(w * dpr)), int(math.ceil(h * dpr)))
            self._bg.setDevicePixelRatio(dpr)
            bp = QPainter(self._bg)
            self._paint_background(bp)
            bp.end()
            self._bg_key = key
        p.drawPixmap(0, 0, self._bg)
        font = QFont(self.font())
        font.setPixelSize(10)
        p.setFont(font)
        span = max(1e-9, self._v1 - self._v0)
        self._paint_marks(p, QFontMetrics(font), self._ruler_h, w / span)

    def _paint_background(self, p):
        L = self.look
        w, h = self.width(), self.height()
        p.fillRect(QRectF(0, 0, w, h), QColor(L["bg"]))
        ruler_h = self._ruler_h
        p.fillRect(QRectF(0, 0, w, ruler_h), QColor(L["ruler"]))
        self._paint_thumbs(p)
        span = max(1e-9, self._v1 - self._v0)
        px_per_frame = w / span
        # Sélection IN / OUT
        lo, hi = self.range()
        if self.in_point is not None or self.out_point is not None:
            sel = QColor(L["selection"])
            sel.setAlpha(110)
            p.fillRect(QRectF(self._x_of(lo - 0.5), 0, self._x_of(hi + 0.5) - self._x_of(lo - 0.5), h), sel)
        # Images en cache (fine bande en bas) et manquantes
        if px_per_frame >= 0.2:
            first, last = max(0, int(self._v0)), min(self.count - 1, int(math.ceil(self._v1)))
            cache = QColor(L["cache"])
            for i in self.cached:
                if first <= i <= last:
                    p.fillRect(QRectF(self._x_of(i - 0.5), h - 3, max(1.0, px_per_frame), 3), cache)
            miss = QColor("#a33")
            for i in self.missing:
                if first <= i <= last:
                    p.fillRect(QRectF(self._x_of(i - 0.5), ruler_h, max(1.0, px_per_frame), h - ruler_h - 3), miss)
        # Graduations
        font = QFont(self.font())
        font.setPixelSize(10)
        p.setFont(font)
        fm = QFontMetrics(font)
        density = max(30, int(L["density"]))
        if L.get("seconds"):
            self._paint_seconds(p, fm, ruler_h, px_per_frame, density)
        else:
            self._paint_frames(p, fm, ruler_h, px_per_frame, density)

    def _paint_thumbs(self, p):
        """Miniature la plus proche (rang exact, sinon une voisine déjà lue) dans chaque case de la bande."""
        slots, quantum = self._thumb_slots()
        if not slots or not self.thumbs:
            return
        top, band = self._thumb_band()
        keys = sorted(self.thumbs)
        import bisect
        p.save()
        p.setOpacity(0.85)
        p.setRenderHint(QPainter.SmoothPixmapTransform, True)
        for x, slot_w, index in slots:
            image = self.thumbs.get(index)
            if image is None:
                i = bisect.bisect_left(keys, index)
                near = [keys[j] for j in (i - 1, i) if 0 <= j < len(keys)]
                # Vue zoomée / déplacée depuis la demande : la miniature lue la plus proche, à l'écart de la
                # demande près (pas d'image lointaine répétée).
                near = [k for k in near if abs(k - index) <= max(quantum, self._req_quantum) * 2]
                if not near:
                    continue
                image = self.thumbs[min(near, key=lambda k: abs(k - index))]
            p.drawImage(QRectF(x, top, slot_w - 1, band), image)
        p.restore()

    def _paint_seconds(self, p, fm, ruler_h, px_per_frame, density):
        """Graduations en SECONDES : posées au rang (fractionnaire) de chaque temps rond."""
        L = self.look
        t0 = self.time_of(max(0.0, self._v0)) if self._v0 > 0 else 0.0
        t1 = self.time_of(min(self.count - 1, max(0, int(math.ceil(self._v1)))))
        frame_s = max(1e-6, (t1 - t0) / max(1e-9, min(self._v1, self.count - 1) - max(0.0, self._v0))) \
            if t1 > t0 else 1.0 / float(self.fps or 24)
        px_per_s = px_per_frame / frame_s
        step = next((s for s in _SECOND_STEPS if s * px_per_s >= density), _SECOND_STEPS[-1])
        minor = next((s for s in _SECOND_STEPS if s * px_per_s >= 8 and abs(step / s - round(step / s)) < 1e-6),
                     step)
        text = QColor(L["text"])
        tick = int(L["tick"])
        end = self.time_of(self.count - 1) + frame_s
        k = int(math.floor(t0 / minor))
        while True:
            t = k * minor
            if t > t1 + minor or t > end:
                break
            if t >= 0:
                x = self._x_of(self.index_at_time(t) - 0.0)
                major = abs(t / step - round(t / step)) < 1e-6
                p.setPen(QPen(text if major else QColor(text.red(), text.green(), text.blue(), 90), 1))
                p.drawLine(QPointF(x, ruler_h - (tick if major else tick // 2)), QPointF(x, ruler_h))
                if major:
                    p.drawText(QPointF(x + 3, ruler_h - tick - 2 if ruler_h - tick - 2 > fm.ascent() else fm.ascent()),
                               format_seconds(t, step))
            k += 1

    def _paint_frames(self, p, fm, ruler_h, px_per_frame, density):
        L = self.look
        step = next((s for s in _STEPS if s * px_per_frame >= density), _STEPS[-1])
        minor = next((s for s in _STEPS if s * px_per_frame >= 8 and step % s == 0), step)
        text = QColor(L["text"])
        tick = int(L["tick"])
        start = int(math.floor(self._v0 / minor)) * minor
        i = start
        while i <= self._v1 + minor:
            if 0 <= i < self.count:
                x = self._x_of(i)
                major = i % step == 0
                p.setPen(QPen(text if major else QColor(text.red(), text.green(), text.blue(), 90), 1))
                p.drawLine(QPointF(x, ruler_h - (tick if major else tick // 2)), QPointF(x, ruler_h))
                if major:
                    label = self.label(i)
                    p.drawText(QPointF(x + 3, ruler_h - tick - 2 if ruler_h - tick - 2 > fm.ascent() else fm.ascent()),
                               label)
            i += minor

    def _paint_marks(self, p, fm, ruler_h, px_per_frame):
        L = self.look
        w, h = self.width(), self.height()
        # Poignées IN / OUT
        for point, key, side in ((self.in_point, "in_color", -0.5), (self.out_point, "out_color", 0.5)):
            if point is None:
                continue
            x = self._x_of(point + side)
            c = QColor(L[key])
            p.setPen(QPen(c, 2))
            p.drawLine(QPointF(x, 0), QPointF(x, h))
            p.setBrush(c)
            dx = 7 if side < 0 else -7
            p.drawPolygon(QPolygonF([QPointF(x, ruler_h), QPointF(x + dx, ruler_h), QPointF(x, ruler_h + 9)]))
        # Tête de lecture
        x = self._x_of(self.current)
        head = QColor(L["playhead"])
        if px_per_frame > 6:
            band = QColor(head)
            band.setAlpha(60)
            p.fillRect(QRectF(self._x_of(self.current - 0.5), 0, px_per_frame, h), band)
        p.setPen(QPen(head, 2))
        p.drawLine(QPointF(x, 0), QPointF(x, h))
        p.setBrush(head)
        p.setPen(Qt.NoPen)
        p.drawPolygon(QPolygonF([QPointF(x - 6, 0), QPointF(x + 6, 0), QPointF(x, 8)]))
        label = self.label(self.current)
        tw = fm.horizontalAdvance(label) + 8
        bx = min(max(0, x + 6), w - tw)
        p.fillRect(QRectF(bx, ruler_h + 2, tw, fm.height() + 2), head)
        p.setPen(QColor("#ffffff"))
        p.drawText(QRectF(bx, ruler_h + 2, tw, fm.height() + 2), Qt.AlignCenter, label)

    # -- souris --

    def _on_thumb_edge(self, y: float) -> bool:
        top, band = self._thumb_band()
        return band > 0 and abs(y - top) <= self.EDGE

    def _handle_at(self, x: float):
        for point, name, side in ((self.in_point, "in", -0.5), (self.out_point, "out", 0.5)):
            if point is not None and abs(self._x_of(point + side) - x) <= 5:
                return name
        return None

    def mousePressEvent(self, event):
        x = event.position().x()
        if event.button() == Qt.MiddleButton:
            self._drag = ("pan", x, self._v0)
            return
        if event.button() != Qt.LeftButton:
            return
        if self._on_thumb_edge(event.position().y()):
            # Bord haut de la bande des miniatures : sa hauteur suit la souris (coordonnées ÉCRAN, la timeline
            # grandit vers le haut et ses coordonnées locales bougent avec elle).
            self._drag = ("thumbsize", event.globalPosition().y(), self.thumb_h)
            return
        handle = self._handle_at(x)
        if handle:
            self._drag = (handle, x, None)
            return
        self._drag = ("scrub", x, None)
        self.scrubStarted.emit()
        self.seekRequested.emit(self._index_at(x))

    def mouseMoveEvent(self, event):
        x = event.position().x()
        drag = self._drag
        if drag is None:
            if self._on_thumb_edge(event.position().y()):
                self.setCursor(Qt.SizeVerCursor)
            else:
                self.setCursor(Qt.SizeHorCursor if self._handle_at(x) else Qt.ArrowCursor)
            return
        kind = drag[0]
        if kind == "thumbsize":
            value = self._clamp_thumb(drag[2] + (drag[1] - event.globalPosition().y()))
            if value != self.thumb_h:
                self.thumb_h = value
                self._apply_height()
            return
        if kind == "pan":
            span = self._v1 - self._v0
            self._v0 = drag[2] - (x - drag[1]) / max(1, self.width()) * span
            self._v1 = self._v0 + span
            self._clamp_view()
            self.update()
        elif kind == "scrub":
            self.seekRequested.emit(self._index_at(x))
        elif kind in ("in", "out"):
            index = self._index_at(x)
            if kind == "in":
                self.set_range(min(index, self.out_point) if self.out_point is not None else index, self.out_point)
            else:
                self.set_range(self.in_point, max(index, self.in_point) if self.in_point is not None else index)

    def mouseReleaseEvent(self, event):
        drag = self._drag
        self._drag = None
        if drag is not None and drag[0] == "scrub":
            self.scrubFinished.emit()
        elif drag is not None and drag[0] == "thumbsize":
            self._views_changed()               # miniatures relues à la nouvelle taille, une fois
            if self.thumb_h != drag[2]:
                self.thumbHeightChanged.emit(self.thumb_h)

    def mouseDoubleClickEvent(self, event):
        if self._on_thumb_edge(event.position().y()):
            return
        self.fit()

    def wheelEvent(self, event):
        delta = event.angleDelta().y() or event.angleDelta().x()
        if not delta:
            return
        if event.modifiers() & Qt.ShiftModifier or event.angleDelta().x():
            self.scroll(-delta / 120.0 * (self._v1 - self._v0) * 0.1)
        else:
            self.zoom(delta / 120.0, event.position().x())
        event.accept()
