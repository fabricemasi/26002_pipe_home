"""Vue d'un document (Qt) : pages en défilement continu / page simple / double page, zoom, rotation de vue, rendu
par TUILES dans le fil du moteur, formulaires interactifs (souris et clavier transmis à PDFium), sélection et copie
de texte, résultats de recherche, liens, surcouche d'outil (concepteur de formulaires, annotations…).

Repères : « points affichés » = points de la page TELLE QU'AFFICHÉE (rotation de vue comprise, origine en haut à
gauche) ; le moteur reçoit des points NON tournés par la vue (`to_engine` / `from_engine`) ; l'écran = points × zoom.

Fluidité (règle de l'appli) : rien de lourd ici ; pendant un zoom continu, les tuiles déjà rendues sont étirées et
le rendu net n'est demandé que 120 ms après le dernier cran ; les tuiles sorties de l'écran sont annulées ; les
invalidations d'un champ (XFA : la page entière à chaque frappe) ne redemandent que les tuiles VISIBLES, une seule
fois même si plusieurs frappes arrivent pendant le rendu ; une tuile périmée reste affichée jusqu'à la nouvelle.
"""
from __future__ import annotations

import math
import time

from PySide6.QtCore import QPoint, QPointF, QRect, QRectF, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QCursor, QGuiApplication, QPainter, QPen
from PySide6.QtWidgets import QAbstractScrollArea

from .tiles import TILE, TileCache
from .worker import PRIO_INPUT, PRIO_NEAR, PRIO_THUMB, PRIO_VISIBLE

GAP = 12.0                                  # points entre deux pages
MARGIN = 16.0
ZOOM_MIN, ZOOM_MAX = 0.05, 64.0
MODES = ("continuous", "single", "two", "two_continuous")
MODE_LABELS = {"continuous": "Défilement continu", "single": "Page simple", "two": "Double page",
               "two_continuous": "Double page continue"}
THUMB_W = 180

CURSORS = {"arrow": Qt.ArrowCursor, "nesw": Qt.SizeBDiagCursor, "nwse": Qt.SizeFDiagCursor,
           "vbeam": Qt.IBeamCursor, "hbeam": Qt.IBeamCursor, "hand": Qt.PointingHandCursor}

# Touches Qt -> codes virtuels Windows (FWL_VKEY_*) transmis aux champs
VKEYS = {Qt.Key_Backspace: 0x08, Qt.Key_Tab: 0x09, Qt.Key_Backtab: 0x09, Qt.Key_Return: 0x0D, Qt.Key_Enter: 0x0D,
         Qt.Key_Escape: 0x1B, Qt.Key_Space: 0x20, Qt.Key_PageUp: 0x21, Qt.Key_PageDown: 0x22, Qt.Key_End: 0x23,
         Qt.Key_Home: 0x24, Qt.Key_Left: 0x25, Qt.Key_Up: 0x26, Qt.Key_Right: 0x27, Qt.Key_Down: 0x28,
         Qt.Key_Insert: 0x2D, Qt.Key_Delete: 0x2E}


def _mods(qt_mods) -> int:
    out = 0
    if qt_mods & Qt.ShiftModifier:
        out |= 1
    if qt_mods & Qt.ControlModifier:
        out |= 2
    if qt_mods & Qt.AltModifier:
        out |= 4
    return out


class PdfView(QAbstractScrollArea):
    pageChanged = Signal(int)
    zoomChanged = Signal(float)
    selectionChanged = Signal(bool)
    contextMenuAt = Signal(QPoint, int, float, float)      # position globale, page, x, y (points affichés)
    linkRequested = Signal(str)                            # lien externe : la vitrine demande l'accord
    formFocusChanged = Signal(bool)
    layoutChanged = Signal()
    escapePressed = Signal()                               # Échap sans rien à annuler (Board : quitter le plein écran)

    def __init__(self, session, settings: dict | None = None, parent=None):
        super().__init__(parent)
        self.session = session
        self.settings = dict(settings or {})
        self.zoom = 1.0
        # Vue EMBARQUÉE dans le Board (QGraphicsProxyWidget, fm_pdf/board_live.py) : tuiles rendues au zoom du Board
        # (`render_scale`, nettes à l'écran) et seulement pour la partie de la vue visible à l'écran (`clip_to_exposed` :
        # la peinture ne reçoit que la zone exposée ; sans cela, un élément zoomé à 400 % ferait rendre toute sa surface).
        self.render_scale = 1.0
        self.clip_to_exposed = False
        self._exposed = None
        # Marge autour des pages (points) et réserve de l'ajustement (pixels) : 0 dans le Board (demande de
        # l'utilisateur : « pas d'écart entre le bord de la page et le cadre ») ; ailleurs, celles d'origine.
        self.margin = MARGIN
        self.fit_pad = 2
        self.fit = self.settings.get("pdf_default_fit", "width")      # "width", "page", None
        self.mode = self.settings.get("pdf_default_mode", "continuous")
        self.rotation = 0
        self.tool = "select"                                         # select, hand
        self.overlay = None                                          # outil actif (conception, annotations…)
        self.cache = TileCache(int(self.settings.get("pdf_cache_mb", 256)) * 1024 * 1024)
        self.thumbs: dict[int, object] = {}
        self._thumb_jobs: dict[int, object] = {}
        self._pending: dict = {}
        self._again: set = set()
        self._sizes: list = []
        self._rects: list[QRectF] = []
        self._content = QRectF()
        self.current = 0
        self._zooming = False
        self._settle = QTimer(self)
        self._settle.setSingleShot(True)
        self._settle.setInterval(120)
        self._settle.timeout.connect(self._zoom_settled)
        self._move_job = None
        self._move_next = None
        self._hover_field = -1
        self.form_focus = False
        self._pending_focus = False                  # clic transmis : le moteur dit s'il a touché un champ
        self._press = None
        self._pan_from = None
        self._space = False
        self.selection = None                                        # (page, début, longueur, rectangles)
        self._sel_anchor = None
        self.search_hits: dict[int, list] = {}
        self.current_hit = None                                      # (page, index)
        self.links: dict[int, list] = {}
        self._link_jobs: set = set()
        self.history: list = []
        self.history_pos = -1
        self.timings = {"tiles": 0, "tile_ms": 0.0}
        self.setMouseTracking(True)
        self.viewport().setMouseTracking(True)
        self.setFocusPolicy(Qt.StrongFocus)
        self.setAttribute(Qt.WA_InputMethodEnabled, True)
        self.viewport().setAttribute(Qt.WA_OpaquePaintEvent, True)
        self.setFrameShape(QAbstractScrollArea.NoFrame)
        self.horizontalScrollBar().valueChanged.connect(self._scrolled)
        self.verticalScrollBar().valueChanged.connect(self._scrolled)
        session.opened.connect(self._on_document)
        session.reloaded.connect(self._on_document)
        session.events.connect(self._on_events)
        self._bg = QColor(self.settings.get("pdf_view_background", "#3a3d40"))

    # -- document, mise en page --

    def _on_document(self, info: dict) -> None:
        keep_page = self.current
        self._sizes = list(info.get("sizes", []))
        self.cache.drop_generation_except(self.session.generation)
        self.thumbs.clear()
        self._thumb_jobs.clear()
        for job in self._pending.values():
            job.cancel()
        self._pending.clear()
        self._again.clear()
        self.links.clear()
        self.selection = None
        self.relayout()
        if keep_page and keep_page < len(self._sizes):
            self.go_to_page(keep_page, record=False)
        self.viewport().update()

    def page_count(self) -> int:
        return len(self._sizes)

    def display_size(self, i: int) -> tuple[float, float]:
        w, h = self._sizes[i]
        return (h, w) if self.rotation % 2 else (w, h)

    def relayout(self) -> None:
        n = len(self._sizes)
        step = 2 if self.mode in ("two", "two_continuous") else 1
        rows = [list(range(k, min(n, k + step))) for k in range(0, n, step)]
        widths = [sum(self.display_size(i)[0] for i in row) + GAP * (len(row) - 1) for row in rows]
        inner = max(widths, default=0.0)
        rects: list = [None] * n
        y = self.margin
        for row, row_w in zip(rows, widths):
            hh = max(self.display_size(i)[1] for i in row)
            x = self.margin + (inner - row_w) / 2            # rangée centrée
            for i in row:
                w, h = self.display_size(i)
                rects[i] = QRectF(x, y + (hh - h) / 2, w, h)
                x += w + GAP
            y += hh + GAP
        self._rects = rects
        self._content = QRectF(0, 0, (max((r.right() for r in rects), default=0) + self.margin),
                               (max((r.bottom() for r in rects), default=0) + self.margin))
        if self.fit:
            self._apply_fit(update=False)
        self._update_scrollbars()
        self.layoutChanged.emit()

    def _visible_indexes(self) -> list[int]:
        """Pages montrées par le mode : toutes (continu) ou la page / la paire courante."""
        n = len(self._rects)
        if self.mode == "single":
            return [self.current] if n else []
        if self.mode == "two":
            k = self.current - self.current % 2
            return [i for i in (k, k + 1) if i < n]
        return list(range(n))

    def _mode_offset(self) -> QPointF:
        """Pages isolées (page simple, double page) : décalage qui ramène la page courante en haut."""
        if self.mode in ("single", "two") and self._rects:
            first = self._visible_indexes()[0]
            return QPointF(0, self._rects[first].top() - self.margin)
        return QPointF(0, 0)

    def _extent(self) -> QRectF:
        if self.mode in ("single", "two") and self._rects:
            idx = self._visible_indexes()
            r = QRectF(self._rects[idx[0]])
            for i in idx[1:]:
                r = r.united(self._rects[i])
            return QRectF(0, 0, self._content.width(), r.height() + self.margin * 2)
        return self._content

    def _update_scrollbars(self) -> None:
        ext = self._extent()
        vw, vh = self.viewport().width(), self.viewport().height()
        cw, ch = ext.width() * self.zoom, ext.height() * self.zoom
        h, v = self.horizontalScrollBar(), self.verticalScrollBar()
        h.setRange(0, max(0, int(math.ceil(cw - vw))))
        v.setRange(0, max(0, int(math.ceil(ch - vh))))
        h.setPageStep(vw)
        v.setPageStep(vh)
        h.setSingleStep(40)
        v.setSingleStep(40)

    def page_rect(self, i: int) -> QRectF:
        """Rectangle de la page en pixels LOGIQUES du viewport."""
        r = self._rects[i]
        off = self._mode_offset()
        ext = self._extent()
        cx = max(0.0, (self.viewport().width() - ext.width() * self.zoom) / 2)
        x = (r.left() - off.x()) * self.zoom - self.horizontalScrollBar().value() + cx
        y = (r.top() - off.y()) * self.zoom - self.verticalScrollBar().value()
        return QRectF(x, y, r.width() * self.zoom, r.height() * self.zoom)

    def page_at(self, pos) -> tuple[int, float, float] | None:
        """(page, x, y en points affichés) sous la position du viewport, sinon None."""
        for i in self._visible_indexes():
            r = self.page_rect(i)
            if r.contains(QPointF(pos)):
                return i, (pos.x() - r.left()) / self.zoom, (pos.y() - r.top()) / self.zoom
        return None

    def to_engine(self, i: int, x: float, y: float) -> tuple[float, float]:
        """Points affichés -> points de la page non tournée par la vue (repère du moteur)."""
        w, h = self._sizes[i]
        r = self.rotation % 4
        if r == 1:
            return y, h - x
        if r == 2:
            return w - x, h - y
        if r == 3:
            return w - y, x
        return x, y

    def from_engine(self, i: int, x: float, y: float) -> tuple[float, float]:
        w, h = self._sizes[i]
        r = self.rotation % 4
        if r == 1:
            return h - y, x
        if r == 2:
            return w - x, h - y
        if r == 3:
            return y, w - x
        return x, y

    def engine_rect_to_view(self, i: int, rect) -> QRectF:
        """Rectangle (x0, y0, x1, y1) du moteur -> pixels du viewport."""
        a = self.from_engine(i, rect[0], rect[1])
        b = self.from_engine(i, rect[2], rect[3])
        pr = self.page_rect(i)
        return QRectF(QPointF(pr.left() + min(a[0], b[0]) * self.zoom, pr.top() + min(a[1], b[1]) * self.zoom),
                      QPointF(pr.left() + max(a[0], b[0]) * self.zoom, pr.top() + max(a[1], b[1]) * self.zoom))

    # -- zoom, navigation --

    def set_zoom(self, zoom: float, anchor: QPointF | None = None, fit=None) -> None:
        zoom = max(ZOOM_MIN, min(ZOOM_MAX, float(zoom)))
        self.fit = fit
        if abs(zoom - self.zoom) < 1e-9:
            return
        if anchor is None:
            anchor = QPointF(self.viewport().width() / 2, self.viewport().height() / 2)
        h, v = self.horizontalScrollBar(), self.verticalScrollBar()
        ext = self._extent()
        cx_old = max(0.0, (self.viewport().width() - ext.width() * self.zoom) / 2)
        px = (anchor.x() + h.value() - cx_old) / self.zoom
        py = (anchor.y() + v.value()) / self.zoom
        self.zoom = zoom
        self._update_scrollbars()
        cx_new = max(0.0, (self.viewport().width() - ext.width() * self.zoom) / 2)
        h.setValue(int(round(px * zoom - anchor.x() + cx_new)))
        v.setValue(int(round(py * zoom - anchor.y())))
        self._zooming = True
        self._settle.start()
        self.zoomChanged.emit(self.zoom)
        self.viewport().update()

    def _zoom_settled(self) -> None:
        self._zooming = False
        gen = self.session.generation
        skey = self._scale_key()
        for i in self._visible_indexes():
            self.cache.drop_scales_except(gen, i, skey) if self._page_complete(i, skey) else None
        self.viewport().update()

    def zoom_by(self, factor: float, anchor=None) -> None:
        self.set_zoom(self.zoom * factor, anchor)

    def _apply_fit(self, update=True) -> None:
        if not self._rects or self.viewport().width() < 10:
            return
        vw = self.viewport().width() - self.fit_pad
        vh = self.viewport().height() - self.fit_pad
        ext = self._extent()
        if self.fit == "width":
            z = vw / max(1.0, ext.width())
        elif self.fit == "page":
            i = self.current if self.current < len(self._rects) else 0
            idx = self._visible_indexes() if self.mode in ("single", "two") else [i]
            r = QRectF(self._rects[idx[0]])
            for k in idx[1:]:
                r = r.united(self._rects[k])
            z = min(vw / (r.width() + self.margin * 2), vh / (r.height() + self.margin * 2))
        else:
            return
        self.zoom = max(ZOOM_MIN, min(ZOOM_MAX, z))
        self._update_scrollbars()
        if update:
            self.zoomChanged.emit(self.zoom)
            self.viewport().update()

    def fit_width(self) -> None:
        self.fit = "width"
        self._apply_fit()
        self._zooming = True
        self._settle.start()

    def fit_page(self) -> None:
        self.fit = "page"
        self._apply_fit()
        self.go_to_page(self.current, record=False)
        self._zooming = True
        self._settle.start()

    def actual_size(self) -> None:
        self.set_zoom(QGuiApplication.primaryScreen().logicalDotsPerInch() / 72.0 if
                      self.settings.get("pdf_actual_size_dpi", True) else 1.0)

    def set_mode(self, mode: str) -> None:
        if mode in MODES and mode != self.mode:
            self.mode = mode
            page = self.current
            self.relayout()
            self.go_to_page(page, record=False)

    def rotate_view(self, quarter: int = 1) -> None:
        page = self.current
        self.rotation = (self.rotation + quarter) % 4
        self.cache.clear()
        self.thumbs.clear()
        self.relayout()
        self.go_to_page(page, record=False)

    def go_to_page(self, i: int, y: float | None = None, record: bool = True) -> None:
        if not self._rects:
            return
        i = max(0, min(len(self._rects) - 1, int(i)))
        if record:
            self._record_history()
        self.current = i
        if self.mode in ("single", "two"):
            self._update_scrollbars()
            self.verticalScrollBar().setValue(0 if y is None else int(y * self.zoom))
        else:
            r = self._rects[i]
            top = (r.top() - min(GAP / 2, self.margin)) * self.zoom + (y or 0) * self.zoom   # Board : bord à bord
            self.verticalScrollBar().setValue(int(round(top)))
        self.pageChanged.emit(i)
        if record:
            self._record_history()
        self.viewport().update()

    def next_page(self, step: int = 1) -> None:
        if self.mode in ("two", "two_continuous"):
            step *= 2
        self.go_to_page(self.current + step, record=False)

    def _record_history(self) -> None:
        state = (self.current, self.verticalScrollBar().value())
        if self.history_pos >= 0 and self.history[self.history_pos] == state:
            return
        del self.history[self.history_pos + 1:]
        self.history.append(state)
        self.history = self.history[-200:]
        self.history_pos = len(self.history) - 1

    def history_back(self) -> None:
        if self.history_pos > 0:
            self.history_pos -= 1
            page, value = self.history[self.history_pos]
            self.current = page
            self.verticalScrollBar().setValue(value)
            self.pageChanged.emit(page)

    def history_forward(self) -> None:
        if self.history_pos < len(self.history) - 1:
            self.history_pos += 1
            page, value = self.history[self.history_pos]
            self.current = page
            self.verticalScrollBar().setValue(value)
            self.pageChanged.emit(page)

    def ensure_visible(self, i: int, rect_view_pts) -> None:
        """Fait défiler pour montrer `rect_view_pts` (x0, y0, x1, y1 en points affichés) de la page `i`."""
        if self.mode in ("single", "two") and i not in self._visible_indexes():
            self.go_to_page(i, record=False)
        pr = self.page_rect(i)
        top = pr.top() + rect_view_pts[1] * self.zoom
        bottom = pr.top() + rect_view_pts[3] * self.zoom
        v = self.verticalScrollBar()
        if top < 40 or bottom > self.viewport().height() - 40:
            v.setValue(int(v.value() + top - self.viewport().height() / 3))
        left = pr.left() + rect_view_pts[0] * self.zoom
        h = self.horizontalScrollBar()
        if left < 0 or left > self.viewport().width() - 40:
            h.setValue(int(h.value() + left - 40))

    def _scrolled(self, _value=None) -> None:
        if self.mode in ("continuous", "two_continuous") and self._rects:
            mid = self.viewport().height() / 2
            best, dist = self.current, 1e18
            for i in range(len(self._rects)):
                r = self.page_rect(i)
                if r.bottom() < -2000 or r.top() > self.viewport().height() + 2000:
                    continue
                d = 0 if r.top() <= mid <= r.bottom() else min(abs(r.top() - mid), abs(r.bottom() - mid))
                if d < dist:
                    best, dist = i, d
            if best != self.current:
                self.current = best
                self.pageChanged.emit(best)
        self.viewport().update()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if self.fit:
            self._apply_fit()
        self._update_scrollbars()

    # -- rendu --

    def _dpr(self) -> float:
        """Pixels rendus par pixel logique : écran × zoom du Board (vue embarquée, `render_scale`)."""
        return self.devicePixelRatioF() * self.render_scale

    def set_render_scale(self, scale: float) -> None:
        """Zoom du Board changé (vue embarquée) : tuiles nettes redemandées 120 ms après le dernier changement ; en
        attendant, les tuiles déjà rendues sont étirées (comme pendant un zoom de la vue)."""
        scale = max(0.05, float(scale))
        if abs(scale - self.render_scale) < 1e-6:
            return
        self.render_scale = scale
        self._zooming = True
        self._settle.start()
        self.viewport().update()

    def set_transparent(self) -> None:
        """Board : AUCUN fond, seulement les pages (demande de l'utilisateur : « le fond doit être le fond du
        board ») ; ce qui est derrière la vue se voit autour et entre les pages."""
        self._bg = QColor(0, 0, 0, 0)
        vp = self.viewport()
        vp.setAttribute(Qt.WA_OpaquePaintEvent, False)
        vp.setAutoFillBackground(False)
        self.setAutoFillBackground(False)
        self.setStyleSheet("QAbstractScrollArea { background: transparent; border: none; }"
                           "QAbstractScrollArea > QWidget { background: transparent; }")

    def _view_area(self) -> QRectF:
        """Zone du viewport à rendre : tout le viewport, ou (vue embarquée) la partie exposée à l'écran."""
        full = QRectF(self.viewport().rect())
        if self.clip_to_exposed and self._exposed is not None:
            return self._exposed.intersected(full)
        return full

    def _scale_key(self) -> float:
        return round(self.zoom * self._dpr(), 4)

    def _tiles_for(self, i: int, scale: float, area: QRectF | None):
        """Tuiles (tx, ty, rect pixels) de la page `i` à `scale` qui recouvrent `area` (pixels logiques du viewport)."""
        w, h = self.display_size(i)
        full_w, full_h = max(1, int(round(w * scale))), max(1, int(round(h * scale)))
        pr = self.page_rect(i)
        dpr = self._dpr()
        if area is None:
            x0, y0, x1, y1 = 0, 0, full_w, full_h
        else:
            a = area.intersected(pr)
            if a.isEmpty():
                return []
            x0 = max(0, int((a.left() - pr.left()) * dpr))
            y0 = max(0, int((a.top() - pr.top()) * dpr))
            x1 = min(full_w, int(math.ceil((a.right() - pr.left()) * dpr)))
            y1 = min(full_h, int(math.ceil((a.bottom() - pr.top()) * dpr)))
        out = []
        for ty in range(y0 // TILE, (max(y0, y1 - 1)) // TILE + 1):
            for tx in range(x0 // TILE, (max(x0, x1 - 1)) // TILE + 1):
                rx, ry = tx * TILE, ty * TILE
                out.append((tx, ty, (rx, ry, min(TILE, full_w - rx), min(TILE, full_h - ry))))
        return out

    def _page_complete(self, i, skey) -> bool:
        have = self.cache.scales(self.session.generation, i).get(skey, set())
        need = self._tiles_for(i, skey, self._view_area())
        return all((tx, ty) in have for tx, ty, _ in need)

    def _request(self, i, skey, tx, ty, rect, priority) -> None:
        gen = self.session.generation
        key = (gen, i, skey, tx, ty)
        if key in self._pending:
            return
        t0 = time.perf_counter()

        def done(result, error, key=key):
            self._pending.pop(key, None)
            if error is not None or result is None:
                return
            generation, img = result
            if generation != self.session.generation:
                return
            self.timings["tiles"] += 1
            self.timings["tile_ms"] += (time.perf_counter() - t0) * 1000
            self.cache.put(key, img)
            if key in self._again:
                self._again.discard(key)
                self.cache.mark_stale(gen, i, skey, [(tx, ty)])
            self.viewport().update()
        self._pending[key] = self.session.render_tile(i, skey, rect, self.rotation, priority, done, self._dpr())

    def _request_thumb(self, i: int, urgent: bool = False) -> None:
        """Miniature (180 px de large, ~3-5 ms). `urgent` : page visible sans aucune tuile (saut de page) -> AVANT
        ses tuiles nettes : jamais de page blanche, la page floue apparaît aussitôt."""
        if i in self.thumbs or i in self._thumb_jobs or i >= len(self._sizes):
            return
        w, _h = self.display_size(i)
        scale = THUMB_W / max(1.0, w)

        def done(result, error, i=i):
            self._thumb_jobs.pop(i, None)
            if error is None and result is not None and result[0] == self.session.generation:
                self.thumbs[i] = result[1]
                self.viewport().update()
        w2, h2 = self.display_size(i)
        self._thumb_jobs[i] = self.session.render_tile(i, scale, (0, 0, int(round(w2 * scale)),
                                                                  int(round(h2 * scale))), self.rotation,
                                                       PRIO_VISIBLE - 1 if urgent else PRIO_THUMB, done)

    def paintEvent(self, event):
        painter = QPainter(self.viewport())
        painter.fillRect(event.rect(), self._bg)
        if not self._rects:
            painter.end()
            return
        gen = self.session.generation
        dpr = self._dpr()
        skey = self._scale_key()
        if self.clip_to_exposed:                  # vue embarquée : la zone peinte = la partie visible à l'écran
            self._exposed = QRectF(event.rect())
        view = self._view_area()
        wanted = set()
        painter.setRenderHint(QPainter.SmoothPixmapTransform, True)
        for i in self._visible_indexes():
            pr = self.page_rect(i)
            if pr.bottom() < 0 or pr.top() > view.bottom() or pr.right() < 0 or pr.left() > view.right():
                continue
            painter.fillRect(pr.translated(2, 3), QColor(0, 0, 0, 60))
            painter.fillRect(pr, Qt.white)
            tiles = self._tiles_for(i, skey, view)
            have = self.cache.scales(gen, i).get(skey, set())
            if any((tx, ty) not in have for tx, ty, _ in tiles):
                self._draw_fallback(painter, i, pr, skey)
            for tx, ty, rect in tiles:
                key = (gen, i, skey, tx, ty)
                img, stale = self.cache.get(key)
                if img is not None:
                    painter.drawImage(QRectF(pr.left() + rect[0] / dpr, pr.top() + rect[1] / dpr,
                                             rect[2] / dpr, rect[3] / dpr), img)
                if (img is None or stale) and not self._zooming:
                    wanted.add(key)
                    self._request(i, skey, tx, ty, rect, PRIO_INPUT + 1 if stale else PRIO_VISIBLE)
            self._paint_marks(painter, i, pr)
        if self.overlay is not None:
            self.overlay.paint(painter, self)
        painter.end()
        if not self._zooming:
            self._cancel_unwanted(wanted)
            QTimer.singleShot(0, self._prefetch)

    def _draw_fallback(self, painter, i, pr, skey) -> None:
        """Tuile absente : la meilleure tuile d'une autre échelle (zoom en cours), sinon la miniature étirée."""
        gen = self.session.generation
        scales = self.cache.scales(gen, i)
        others = sorted((s for s in scales if s != skey), key=lambda s: abs(math.log(s / skey)))
        dpr = self._dpr()
        if others:
            s = others[0]
            ratio = skey / s
            for tx, ty in scales[s]:
                img, _ = self.cache.get((gen, i, s, tx, ty))
                if img is None:
                    continue
                x, y = tx * TILE * ratio / dpr, ty * TILE * ratio / dpr
                painter.drawImage(QRectF(pr.left() + x, pr.top() + y, img.width() * ratio / dpr,
                                         img.height() * ratio / dpr), img)
            return
        thumb = self.thumbs.get(i)
        if thumb is not None:
            painter.drawImage(pr, thumb)
        else:
            self._request_thumb(i, urgent=True)

    def _cancel_unwanted(self, wanted: set) -> None:
        near = self._near_keys()
        for key, job in list(self._pending.items()):
            if key not in wanted and key not in near:
                job.cancel()
                self._pending.pop(key, None)

    def _near_keys(self) -> set:
        out = set()
        if not self._rects:
            return out
        gen, skey = self.session.generation, self._scale_key()
        base = self._view_area()
        area = base.adjusted(0, -base.height(), 0, base.height())
        for i in self._visible_indexes():
            pr = self.page_rect(i)
            if pr.bottom() < area.top() or pr.top() > area.bottom():
                continue
            for tx, ty, _ in self._tiles_for(i, skey, area):
                out.add((gen, i, skey, tx, ty))
        return out

    def _prefetch(self) -> None:
        """Après les tuiles visibles : une hauteur d'écran au-dessus et au-dessous, puis les miniatures voisines."""
        if self._zooming or not self._rects or not self.isVisible():
            return
        gen, skey = self.session.generation, self._scale_key()
        base = self._view_area()
        area = base.adjusted(0, -base.height(), 0, base.height())
        for i in self._visible_indexes():
            pr = self.page_rect(i)
            if pr.bottom() < area.top() or pr.top() > area.bottom():
                continue
            have = self.cache.scales(gen, i).get(skey, set())
            for tx, ty, rect in self._tiles_for(i, skey, area):
                if (tx, ty) not in have:
                    self._request(i, skey, tx, ty, rect, PRIO_NEAR)
        for i in range(max(0, self.current - 3), min(len(self._rects), self.current + 4)):
            self._request_thumb(i)

    def _paint_marks(self, painter, i, pr) -> None:
        """Résultats de recherche, sélection de texte, focus de champ."""
        hits = self.search_hits.get(i)
        if hits:
            for k, (start, count, rects) in enumerate(hits):
                current = self.current_hit == (i, k)
                color = QColor(255, 140, 0, 150) if current else QColor(255, 220, 0, 110)
                for rect in rects:
                    painter.fillRect(self.engine_rect_to_view(i, rect), color)
        if self.selection and self.selection[0] == i:
            for rect in self.selection[3]:
                painter.fillRect(self.engine_rect_to_view(i, rect), QColor(40, 120, 255, 80))

    # -- évènements du formulaire --

    def _on_events(self, events: list) -> None:
        dirty: dict[int, list] = {}
        for event in events:
            kind = event[0]
            if kind == "invalidate":
                dirty.setdefault(event[1], []).append(event[2])
            elif kind == "cursor":
                if self.overlay is None:
                    self.viewport().setCursor(CURSORS.get(event[1], Qt.ArrowCursor))
            elif kind == "goto":
                self.go_to_page(event[1])
            elif kind == "uri":
                self.linkRequested.emit(event[1])
            elif kind == "focus" or kind == "text_focus":
                pass
        for i, rects in dirty.items():
            self.invalidate_page(i, rects)

    def invalidate_page(self, i: int, rects=None) -> None:
        """Zones changées (points du moteur) : tuiles concernées périmées ; seules les VISIBLES sont redemandées
        (une fois, même si d'autres invalidations arrivent pendant leur rendu)."""
        if i >= len(self._rects):
            return
        gen, skey = self.session.generation, self._scale_key()
        if rects is None:
            areas = [self.page_rect(i)]
        else:
            areas = [self.engine_rect_to_view(i, r).adjusted(-2, -2, 2, 2) for r in rects]
        self.cache.drop_scales_except(gen, i, skey)
        self.thumbs.pop(i, None)
        stale = set()
        for area in areas:
            for tx, ty, _ in self._tiles_for(i, skey, area):
                stale.add((tx, ty))
        self.cache.mark_stale(gen, i, skey, stale)
        for tx, ty in stale:
            key = (gen, i, skey, tx, ty)
            if key in self._pending:
                self._again.add(key)
        self.viewport().update()

    # -- souris --

    def _forward_move(self, page, x, y, mods) -> None:
        """Survol transmis au formulaire (curseur, survol des champs) ; UN seul en vol, le dernier gagne."""
        self._move_next = (page, x, y, mods)
        if self._move_job is not None:
            return
        self._send_move()

    def _send_move(self) -> None:
        if self._move_next is None:
            self._move_job = None
            return
        page, x, y, mods = self._move_next
        self._move_next = None

        def job(doc):
            doc.mouse(page, "move", x, y, mods)
            return doc.field_at(page, x, y)

        def done(result, error):
            self._move_job = None
            if error is None:
                self._hover_field = result
                if result < 0 and self.overlay is None and not self._pan_from:
                    self._set_tool_cursor()
            if self._move_next is not None:
                self._send_move()
        self._move_job = self.session.run(job, PRIO_INPUT, done)

    def _set_tool_cursor(self) -> None:
        self.viewport().setCursor(Qt.OpenHandCursor if self.tool == "hand" or self._space else Qt.ArrowCursor)

    def _form(self, page, kind, x, y, mods=0, callback=None):
        return self.session.run(lambda doc: doc.mouse(page, kind, x, y, mods), PRIO_INPUT, callback)

    def mousePressEvent(self, event):
        self.setFocus(Qt.MouseFocusReason)
        hit = self.page_at(event.position())
        if self.overlay is not None and self.overlay.press(self, event, hit):
            return
        if event.button() == Qt.MiddleButton or (event.button() == Qt.LeftButton and
                                                  (self.tool == "hand" or self._space) and self._hover_field < 0):
            self._pan_from = (event.position(), self.horizontalScrollBar().value(), self.verticalScrollBar().value())
            self.viewport().setCursor(Qt.ClosedHandCursor)
            return
        if hit is None:
            if self.form_focus:
                self._kill_form_focus()
            return
        page, x, y = hit
        ex, ey = self.to_engine(page, x, y)
        mods = _mods(event.modifiers())
        if event.button() == Qt.RightButton:
            self.contextMenuAt.emit(event.globalPosition().toPoint(), page, x, y)
            return
        if event.button() != Qt.LeftButton:
            return
        if self.session.info.get("has_forms"):
            # Le champ sous le clic est CONFIRMÉ par le moteur dans la même tâche (survol, test, appui) : les
            # touches tapées juste après partent vers PDFium sans attendre (`_pending_focus`), même sans survol
            # préalable (mesuré : sinon la frappe n'apparaissait qu'au clignotement suivant du caret, ~500 ms).
            self._pending_focus = True

            def press(doc, page=page, ex=ex, ey=ey, mods=mods):
                doc.mouse(page, "move", ex, ey, mods)
                kind = doc.field_at(page, ex, ey)
                doc.mouse(page, "down", ex, ey, mods)
                return kind

            def pressed(kind, error):
                self._pending_focus = False
                if error is None:
                    self._hover_field = kind
                    self._set_form_focus(kind >= 0)
            self.session.run(press, PRIO_INPUT, pressed)
            if self._hover_field >= 0:
                self._set_form_focus(True)
                self._press = ("form", page)
                return
        link = self._link_at(page, ex, ey)
        if link is not None:
            self._press = ("link", link)
            return
        self._press = ("select", page)
        self._start_selection(page, ex, ey)

    def mouseMoveEvent(self, event):
        pos = event.position()
        if self._pan_from is not None:
            start, h0, v0 = self._pan_from
            self.horizontalScrollBar().setValue(int(h0 - (pos.x() - start.x())))
            self.verticalScrollBar().setValue(int(v0 - (pos.y() - start.y())))
            return
        hit = self.page_at(pos)
        if self.overlay is not None and self.overlay.move(self, event, hit):
            return
        if hit is None:
            if self.overlay is None:
                self._set_tool_cursor()
            return
        page, x, y = hit
        ex, ey = self.to_engine(page, x, y)
        if self.session.info.get("has_forms") and (self._press is None or self._press[0] == "form"):
            self._forward_move(page, ex, ey, _mods(event.modifiers()))
        if self._press and self._press[0] == "select" and event.buttons() & Qt.LeftButton:
            self._extend_selection(page, ex, ey)
        elif self._hover_field < 0 and self.overlay is None:
            self._ensure_links(page)
            if self._link_at(page, ex, ey) is not None:
                self.viewport().setCursor(Qt.PointingHandCursor)
            elif not self.session.info.get("has_forms"):
                self._set_tool_cursor()

    def mouseReleaseEvent(self, event):
        if self._pan_from is not None:
            self._pan_from = None
            self._set_tool_cursor()
            return
        hit = self.page_at(event.position())
        if self.overlay is not None and self.overlay.release(self, event, hit):
            return
        press, self._press = self._press, None
        if press is None or event.button() != Qt.LeftButton:
            return
        if press[0] == "form" and hit is not None:
            page, x, y = hit
            ex, ey = self.to_engine(page, x, y)
            self._form(page, "up", ex, ey, _mods(event.modifiers()))
        elif press[0] == "link":
            self._activate_link(press[1])
        elif press[0] == "select" and hit is not None and self.session.info.get("has_forms"):
            page, x, y = hit
            ex, ey = self.to_engine(page, x, y)
            self._form(page, "up", ex, ey, _mods(event.modifiers()))

    def mouseDoubleClickEvent(self, event):
        hit = self.page_at(event.position())
        if self.overlay is not None and self.overlay.double(self, event, hit):
            return
        if hit is None or event.button() != Qt.LeftButton:
            return
        page, x, y = hit
        ex, ey = self.to_engine(page, x, y)
        if self._hover_field >= 0:
            self._form(page, "double", ex, ey, _mods(event.modifiers()))
            return
        self._select_word(page, ex, ey)

    def wheelEvent(self, event):
        if event.modifiers() & Qt.ControlModifier:
            steps = event.angleDelta().y() / 120.0
            if steps:
                speed = float(self.settings.get("pdf_zoom_step", 1.15))
                self.zoom_by(speed ** steps, event.position())
            event.accept()
            return
        super().wheelEvent(event)

    def event(self, event):
        from PySide6.QtCore import QEvent
        if event.type() == QEvent.NativeGesture:
            from PySide6.QtCore import Qt as _Qt
            if event.gestureType() == _Qt.ZoomNativeGesture:
                self.zoom_by(1.0 + event.value(), event.position())
                return True
        if event.type() == QEvent.KeyPress and event.key() in (Qt.Key_Tab, Qt.Key_Backtab):
            self.keyPressEvent(event)                       # Tab : champ suivant, jamais le widget suivant
            return True
        return super().event(event)

    def focusNextPrevChild(self, next_):
        return False if self.form_focus else super().focusNextPrevChild(next_)

    # -- clavier --

    def _set_form_focus(self, on: bool) -> None:
        if on != self.form_focus:
            self.form_focus = on
            self.formFocusChanged.emit(on)

    def _kill_form_focus(self) -> None:
        self._set_form_focus(False)
        self.session.run(lambda doc: doc.kill_focus(), PRIO_INPUT)

    def keyPressEvent(self, event):
        if self.overlay is not None and self.overlay.key(self, event):
            return
        key = event.key()
        if key == Qt.Key_Space and not event.isAutoRepeat() and not self.form_focus:
            self._space = True
            self._set_tool_cursor()
            return
        if self.form_focus or self._pending_focus:
            if self._form_key(event):
                return
        ctrl = event.modifiers() & Qt.ControlModifier
        if ctrl and key == Qt.Key_C:
            self.copy_selection()
        elif ctrl and key in (Qt.Key_Plus, Qt.Key_Equal):
            self.zoom_by(1.25)
        elif ctrl and key == Qt.Key_Minus:
            self.zoom_by(0.8)
        elif ctrl and key == Qt.Key_0:
            self.fit_page()
        elif key == Qt.Key_PageDown or (key == Qt.Key_Right and self.mode in ("single", "two")):
            if self.mode in ("single", "two"):
                self.next_page(1)
            else:
                self.verticalScrollBar().triggerAction(self.verticalScrollBar().SliderPageStepAdd)
        elif key == Qt.Key_PageUp or (key == Qt.Key_Left and self.mode in ("single", "two")):
            if self.mode in ("single", "two"):
                self.next_page(-1)
            else:
                self.verticalScrollBar().triggerAction(self.verticalScrollBar().SliderPageStepSub)
        elif key == Qt.Key_Home and ctrl:
            self.go_to_page(0)
        elif key == Qt.Key_End and ctrl:
            self.go_to_page(len(self._rects) - 1)
        elif key == Qt.Key_Left and event.modifiers() & Qt.AltModifier:
            self.history_back()
        elif key == Qt.Key_Right and event.modifiers() & Qt.AltModifier:
            self.history_forward()
        elif key == Qt.Key_Escape:
            if self.selection:
                self.clear_selection()                      # Échap n'ouvre ni ne ferme jamais le module
            else:
                self.escapePressed.emit()                   # rien à annuler ici (Board : sortir du plein écran)
        else:
            super().keyPressEvent(event)

    def keyReleaseEvent(self, event):
        if event.key() == Qt.Key_Space and not event.isAutoRepeat():
            self._space = False
            self._set_tool_cursor()
            return
        if (self.form_focus or self._pending_focus) and event.key() in VKEYS:
            code = VKEYS[event.key()]
            mods = _mods(event.modifiers())
            self.session.run(lambda doc: doc.key(doc.current_page, "up", code, mods), PRIO_INPUT)
            return
        super().keyReleaseEvent(event)

    def _form_key(self, event) -> bool:
        """Touche transmise au champ qui a le focus. Presse-papiers : PDFium n'y a pas accès, la vue le fait."""
        key = event.key()
        mods = _mods(event.modifiers())
        ctrl = bool(event.modifiers() & Qt.ControlModifier)
        clip = QGuiApplication.clipboard()
        run = self.session.run
        if key == Qt.Key_Escape:
            self._kill_form_focus()
            return True
        if ctrl and key in (Qt.Key_C, Qt.Key_X):
            def copy(doc, cut=(key == Qt.Key_X)):
                text = doc.selected_text(doc.current_page)
                if cut and text:
                    doc.replace_selection(doc.current_page, "")
                return text
            run(copy, PRIO_INPUT, lambda text, err: clip.setText(text) if err is None and text else None)
            return True
        if ctrl and key == Qt.Key_V:
            text = clip.text()
            if text:
                run(lambda doc: doc.replace_selection(doc.current_page, text), PRIO_INPUT)
            return True
        if ctrl and key == Qt.Key_A:
            run(lambda doc: doc.select_all(doc.current_page), PRIO_INPUT)
            return True
        if ctrl and key in (Qt.Key_Z, Qt.Key_Y):
            redo = key == Qt.Key_Y or bool(event.modifiers() & Qt.ShiftModifier)
            run(lambda doc: doc.form_undo(doc.current_page, redo), PRIO_INPUT)
            return True
        if key in VKEYS:
            code = VKEYS[key]
            if key == Qt.Key_Backtab:
                mods |= 1
            text = event.text() if key in (Qt.Key_Return, Qt.Key_Enter, Qt.Key_Space) else ""

            def press(doc, code=code, mods=mods, text=text):
                handled = doc.key(doc.current_page, "down", code, mods)
                if text:
                    doc.type_text(doc.current_page, "\r" if text in ("\r", "\n") else text)
                return handled
            run(press, PRIO_INPUT)
            return True
        text = event.text()
        if text and text.isprintable() and not ctrl:
            run(lambda doc: doc.type_text(doc.current_page, text), PRIO_INPUT)
            return True
        return False

    def inputMethodEvent(self, event):
        text = event.commitString()
        if self.form_focus and text:
            self.session.run(lambda doc: doc.type_text(doc.current_page, text), PRIO_INPUT)
            event.accept()
            return
        super().inputMethodEvent(event)

    # -- sélection de texte --

    def _start_selection(self, page, ex, ey) -> None:
        self.clear_selection(emit=False)

        def job(doc):
            return doc.char_at(page, ex, ey, 6.0)
        self.session.run(job, PRIO_INPUT, lambda idx, err: setattr(self, "_sel_anchor", (page, idx))
                         if err is None and idx >= 0 else setattr(self, "_sel_anchor", None))

    def _extend_selection(self, page, ex, ey) -> None:
        anchor = self._sel_anchor
        if anchor is None or anchor[0] != page:
            return

        def job(doc):
            idx = doc.char_at(page, ex, ey, 6.0)
            if idx < 0:
                return None
            start, end = min(anchor[1], idx), max(anchor[1], idx)
            return page, start, end - start + 1, doc.range_rects(page, start, end - start + 1)
        self.session.run(job, PRIO_INPUT, self._set_selection)

    def _select_word(self, page, ex, ey) -> None:
        def job(doc):
            idx = doc.char_at(page, ex, ey, 4.0)
            if idx < 0:
                return None
            text = doc.text(page)
            if idx >= len(text) or not text[idx].isalnum():
                return None
            a = idx
            while a > 0 and text[a - 1].isalnum():
                a -= 1
            b = idx
            while b + 1 < len(text) and text[b + 1].isalnum():
                b += 1
            return page, a, b - a + 1, doc.range_rects(page, a, b - a + 1)
        self.session.run(job, PRIO_INPUT, self._set_selection)

    def _set_selection(self, result, error) -> None:
        if error is not None or result is None:
            return
        self.selection = result
        self.selectionChanged.emit(True)
        self.viewport().update()

    def clear_selection(self, emit: bool = True) -> None:
        if self.selection is not None:
            self.selection = None
            self.viewport().update()
            if emit:
                self.selectionChanged.emit(False)

    def select_all_text(self) -> None:
        page = self.current

        def job(doc):
            n = doc.char_count(page)
            return (page, 0, n, doc.range_rects(page, 0, n)) if n else None
        self.session.run(job, PRIO_INPUT, self._set_selection)

    def copy_selection(self) -> None:
        sel = self.selection
        if not sel:
            return
        if not self.session.info.get("security", {}).get("can_copy", True):
            self.session.message.emit("Copie interdite par les permissions du document")
            return
        page, start, count, _ = sel
        self.session.run(lambda doc: doc.text(page, start, count), PRIO_INPUT,
                         lambda text, err: QGuiApplication.clipboard().setText(text) if err is None else None)

    # -- liens --

    def _ensure_links(self, page) -> None:
        if page in self.links or page in self._link_jobs:
            return
        self._link_jobs.add(page)

        def done(result, error, page=page):
            self._link_jobs.discard(page)
            self.links[page] = result if error is None else []
        self.session.run(lambda doc: doc.links(page), PRIO_NEAR, done)

    def _link_at(self, page, ex, ey):
        for link in self.links.get(page, ()):
            x0, y0, x1, y1 = link["rect"]
            if x0 <= ex <= x1 and y0 <= ey <= y1:
                return link
        return None

    def _activate_link(self, link) -> None:
        if "page" in link and link["page"] >= 0:
            self.go_to_page(link["page"])
        elif link.get("uri"):
            self.linkRequested.emit(link["uri"])
        elif link.get("external"):
            self.linkRequested.emit(link["external"])

    # -- recherche --

    def set_search_hits(self, page: int, hits: list) -> None:
        if hits:
            self.search_hits[page] = hits
        else:
            self.search_hits.pop(page, None)
        self.viewport().update()

    def clear_search(self) -> None:
        self.search_hits.clear()
        self.current_hit = None
        self.viewport().update()

    def show_hit(self, page: int, index: int) -> None:
        self.current_hit = (page, index)
        hits = self.search_hits.get(page) or []
        if index < len(hits) and hits[index][2]:
            r = hits[index][2][0]
            a = self.from_engine(page, r[0], r[1])
            b = self.from_engine(page, r[2], r[3])
            self.ensure_visible(page, (min(a[0], b[0]), min(a[1], b[1]), max(a[0], b[0]), max(a[1], b[1])))
        self.viewport().update()

    # -- outils --

    def set_tool(self, tool: str) -> None:
        self.tool = tool
        self._set_tool_cursor()

    def set_overlay(self, overlay) -> None:
        if self.overlay is not None and hasattr(self.overlay, "detach"):
            self.overlay.detach(self)
        self.overlay = overlay
        if overlay is not None and hasattr(overlay, "attach"):
            overlay.attach(self)
        self.viewport().update()

    def stats(self) -> dict:
        tiles = self.timings["tiles"]
        return {"tiles": tiles, "tile_ms_avg": self.timings["tile_ms"] / tiles if tiles else 0.0,
                "cache_mb": self.cache.bytes / 1048576, "pending": len(self._pending)}
