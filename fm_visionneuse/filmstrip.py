"""Pellicule de vignettes sous la visionneuse (FocusFilmstrip) et infobulle de source des proxies.

Découpé de focus.py (2026-10-28) ; carte : docs/agents/fm_visionneuse.md."""
import math
import time
from pathlib import Path

from PySide6.QtCore import QElapsedTimer, QEvent, QObject, QPoint, QPointF, QRectF, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QCursor, QFontMetrics, QLinearGradient, QPainter, QPen
from PySide6.QtWidgets import QApplication, QWidget

from app_style import C, scaled
import previews

from .loader import _pixmap_size, display_name
from . import film_cache
from .film_cache import FILM_SCALE_BUDGET, FILM_THUMB_MAX, _FILM_SIGNALS
from .film_look import _PROXY_SOURCES, _film_inner, _film_look, _paint_film_box, film_text_ratio
from .overlay import FocusOverlay


class ProxySourceTip(QObject):
    """Encart « Source du proxy » sous le curseur quand on survole une diapositive (planche,
    pellicule) avec Maj enfonce (demande de l'utilisateur). Habillage = l'encart des reglages
    (`settings_widgets._WidthBadge`, role width_badge), jamais un style a part. Source lue EN FOND
    (`lightroom_bridge.request_sources`, catalogue et Previews.lrdata), gardee par fichier ; Maj
    enfoncee / relachee sans bouger la souris : filtre d'application (touches seulement)."""

    def __init__(self, host: QWidget, path_at):
        super().__init__(host)
        self._host, self._path_at = host, path_at
        self._badge = None
        self._path: str | None = None
        self._pos = QPoint()
        QApplication.instance().installEventFilter(self)
        try:
            import lightroom_bridge
            lightroom_bridge._signal_bus().sources_ready.connect(self._on_sources)
        except (ImportError, OSError, ValueError):
            pass

    def update_at(self, global_pos: QPoint | None = None, shift: bool | None = None):
        if shift is None:
            shift = bool(QApplication.queryKeyboardModifiers() & Qt.ShiftModifier)
        host = self._host
        pos = host.mapFromGlobal(global_pos if global_pos is not None else QCursor.pos())
        path = None
        if shift and host.isVisible() and host.rect().contains(pos):
            path = self._path_at(pos)
        if not path:
            self.hide()
            return
        self._path, self._pos = str(path), pos
        text = _PROXY_SOURCES.get(self._path)
        if text is None:
            text = self._ask(Path(path))
        self._show(text)

    def _ask(self, path: Path) -> str:
        try:
            import lightroom_bridge
            if lightroom_bridge.is_managed(path):
                lightroom_bridge.request_sources(path)
                return "lecture…"
        except (ImportError, OSError, ValueError):
            pass
        text = _PROXY_SOURCES[str(path)] = "Application · aperçu créé par l'application"
        return text

    def _on_sources(self, path: str, proxy: str, _full: str):
        _PROXY_SOURCES[path] = proxy
        if path == self._path and self._badge is not None and self._badge.isVisible():
            self._show(proxy)

    def _show(self, text: str):
        from settings_widgets import _WidthBadge
        if self._badge is None:
            self._badge = _WidthBadge(self._host)
        badge = self._badge
        badge.setText(f"Source du proxy : {text}")
        badge.adjustSize()
        gap = scaled(14)
        room = self._host.rect()
        x = min(self._pos.x() + gap, room.right() - badge.width())
        y = self._pos.y() + gap
        if y + badge.height() > room.bottom():
            y = self._pos.y() - gap - badge.height()
        badge.move(max(0, x), max(0, y))
        badge.raise_()
        badge.show()

    def hide(self):
        self._path = None
        if self._badge is not None:
            self._badge.hide()

    def eventFilter(self, obj, event):
        kind = event.type()
        if kind in (QEvent.KeyPress, QEvent.KeyRelease) and event.key() == Qt.Key_Shift                 and not event.isAutoRepeat():
            self.update_at(shift=kind == QEvent.KeyPress)
        return False


class FocusFilmstrip(QWidget):
    """Pellicule de la visionneuse : vignettes de tous les fichiers du dossier, en bas de la zone.
    Un TABLEAU : une cellule par fichier, divisee en sous-cellule image (la vignette) et sous-cellule
    texte dessous (le nom ; rang « n / N » dans celle en cours) ; Ctrl + tirer la bordure entre les deux
    change leur hauteur (`viewer_film_text_ratio`, rappel `on_split(ratio, fini)`). Habillage :
    Reglages > Visionneuse > Tableau / Sous cellule image / Sous cellule texte (clic droit : `on_menu`).
    Elle suit le ruban en continu (`set_position`, rang fractionnaire), les cellules grossissent
    en approchant du centre (vague) ; celle de l'image en cours est entouree.
    Clic = aller a ce fichier (`chosen(rang)`), molette = suivant / precedent, double-clic hors
    vignette = comme sur l'image. S'efface quand la souris ne bouge plus (`reveal` la rappelle)."""

    chosen = Signal(int)

    GROW = 0.28
    HOLD_MS = 2400
    RATIO_MIN, RATIO_MAX = 0.12, 1.5
    SPLIT_GRAB = 4                         # demi-hauteur de saisie de la bordure image | texte
    # Hauteur des vignettes choisie par Ctrl+molette, retenue pour la session (None = defaut).
    session_thumb_height: int | None = None

    def __init__(self, parent, thumb, on_wheel=None, on_double_click=None, on_resized=None,
                 on_split=None, on_menu=None):
        super().__init__(parent)
        self._thumb = thumb                  # rappel (Path, cote en pixels physiques) -> QPixmap | None
        self._on_wheel = on_wheel
        self._on_double_click = on_double_click
        self._on_resized = on_resized        # la bande a change de hauteur (zoom des vignettes)
        self._on_split = on_split            # (ratio, fini) : bordure image | texte tiree (Ctrl)
        self._on_menu = on_menu              # (position globale) : clic droit
        self._split_drag = None              # (bas des cellules en y global, hauteur de l'image) pendant le geste
        _FILM_SIGNALS.ready.connect(self.update)
        previews.MTIME_SIGNALS.refreshed.connect(self.update)      # date relue en fond (memory_only)
        # Affichage LEGER quand c'est froid (demande de l'utilisateur : anticiper ce qui ferait ramer) :
        # une cellule dont la vignette n'est pas prete montre son type de fichier, et l'image y apparait
        # en fondu quand elle arrive (`_arrived`), au lieu de bloquer l'animation pour la charger.
        self._waiting: set = set()
        self._arrived: dict = {}
        self._ramp = QTimer(self)
        self._ramp.setInterval(15)
        self._ramp.timeout.connect(self.update)
        self._paths: list = []
        self._index = 0
        self._pos = 0.0
        self._hover = -1
        self.source_tip = ProxySourceTip(self, lambda pos: (
            str(self._paths[i]) if (i := self._index_at(QPointF(pos))) >= 0 else None))
        self._alpha = 0.0
        self._alpha_goal = 0.0
        self._th = scaled(60)
        self._tw = scaled(90)
        self._gap = scaled(8)
        self._pad = scaled(12)
        self.setMouseTracking(True)
        self._clock = QElapsedTimer()
        self._clock.start()
        self._last = 0
        self._fade = QTimer(self)
        self._fade.setInterval(15)
        self._fade.timeout.connect(self._fade_tick)
        self._hold = QTimer(self)
        self._hold.setSingleShot(True)
        self._hold.setInterval(self.HOLD_MS)
        self._hold.timeout.connect(self.conceal)
        # Defilement propre (glide_to) : quand l'image change sans ruban (effet slide coupe), la
        # pellicule glisse seule, meme courbe et meme duree que le ruban (FocusOverlay.SLIDE_MS).
        self._glide_from = 0.0
        self._glide_t0 = 0
        self._glide = QTimer(self)
        self._glide.setInterval(15)
        self._glide.timeout.connect(self._glide_tick)
        if FocusFilmstrip.session_thumb_height:
            self._set_thumb_height(FocusFilmstrip.session_thumb_height)

    def max_thumb_height(self) -> int:
        """Vignette la plus grande (celle du centre, grossie de GROW) : FILM_THUMB_MAX pixels
        physiques au plus sur son plus grand cote (largeur = 1,5 x hauteur), jamais agrandie."""
        dpr = self.devicePixelRatioF() or 1.0
        return max(scaled(30), int(FILM_THUMB_MAX / dpr / (1 + self.GROW) / 1.5))

    def _set_thumb_height(self, height: int) -> bool:
        height = max(scaled(30), min(self.max_thumb_height(), int(height)))
        if height == self._th:
            return False
        self._th, self._tw = height, round(height * 1.5)
        return True

    def zoom_thumbs(self, notches: float):
        """Ctrl+molette sur la pellicule : vignettes plus grandes / plus petites (x1,15 par cran),
        bornees a max_thumb_height ; la bande reservee sous l'image suit (`on_resized`)."""
        if self._set_thumb_height(round(self._th * 1.15 ** notches)):
            FocusFilmstrip.session_thumb_height = self._th
            self.update()
            if self._on_resized is not None:
                self._on_resized()

    def strip_height(self) -> int:
        """Bande reservee : la plus grande cellule (celle du centre, grossie de GROW), image + texte."""
        return round(self._pad * 2 + self._th * (1 + film_text_ratio()) * (1 + self.GROW))

    def set_paths(self, paths: list, index: int):
        self._paths = list(paths)
        self._index = index
        self._pos = float(index)
        self._hover = -1
        self.update()

    def set_current(self, index: int):
        self._index = index
        self.update()

    def set_position(self, pos: float):
        self._glide.stop()
        if abs(pos - self._pos) > 1e-4:
            self._pos = pos
            self.update()

    def glide_to(self, index: int):
        """Glisse jusqu'au rang `index` (crans rapides : l'ecart se cumule, borne a 3 rangs)."""
        offset = max(-3.0, min(3.0, self._pos - index))
        if abs(offset) < 1e-4:
            self.set_position(float(index))
            return
        self._glide_target = index
        self._glide_from = offset
        self._glide_t0 = self._clock.elapsed()
        self._pos = index + offset
        if not self._glide.isActive():
            self._glide.start()
        self.update()

    def gliding(self) -> bool:
        return self._glide.isActive()

    def _glide_tick(self):
        u = min(1.0, (self._clock.elapsed() - self._glide_t0) / FocusOverlay.SLIDE_MS)
        self._pos = self._glide_target + self._glide_from * (1.0 - u) ** 3   # depart vif, arrivee douce
        if u >= 1.0:
            self._pos = float(self._glide_target)
            self._glide.stop()
        self.update()

    def visible_amount(self) -> float:
        return self._alpha

    def reveal(self):
        self._hold.start()
        self._set_alpha_goal(1.0)

    keep_shown = None                    # rappel -> bool : rester affichee (son style se regle)

    def conceal(self):
        if self._hover >= 0 or (self.keep_shown is not None and self.keep_shown()):   # elle reste
            self._hold.start()
            return
        self._set_alpha_goal(0.0)

    def _set_alpha_goal(self, goal: float):
        self._alpha_goal = goal
        if abs(self._alpha - goal) > 1e-3 and not self._fade.isActive():
            self._last = self._clock.elapsed()
            self._fade.start()

    def _fade_tick(self):
        now = self._clock.elapsed()
        # Une image lente (disque froid...) RALENTIT le fondu au lieu de le faire sauter a sa fin :
        # au plus un pas de 30 images / s par image affichee.
        dt = min(1 / 30, max(0.001, (now - self._last) / 1000.0))
        self._last = now
        tau = 0.07 if self._alpha_goal > self._alpha else 0.18      # apparait vite, part en douceur
        self._alpha = self._alpha_goal + (self._alpha - self._alpha_goal) * math.exp(-dt / tau)
        if abs(self._alpha - self._alpha_goal) < 0.01:
            self._alpha = self._alpha_goal
            self._fade.stop()
        self.update()

    def _cells(self):
        """(rang, rectangle de la cellule) des cellules visibles, de la plus loin a la plus proche
        du centre (ordre de dessin ; l'ordre inverse sert au clic). Cellule = image + texte dessous."""
        if not self._paths:
            return []
        width = self.width()
        step = self._tw + self._gap
        bottom = self.height() - self._pad
        reach = int(width / step / 2) + 2
        first = max(0, math.floor(self._pos) - reach)
        last = min(len(self._paths) - 1, math.ceil(self._pos) + reach)
        tall = 1.0 + film_text_ratio()
        cells = []
        for i in range(first, last + 1):
            d = i - self._pos
            grow = 1.0 + self.GROW * max(0.0, 1.0 - abs(d) / 1.5)
            w, h = self._tw * grow, self._th * grow * tall
            x = width / 2 + d * step
            cells.append((abs(d), i, QRectF(x - w / 2, bottom - h, w, h)))
        cells.sort(key=lambda cell: -cell[0])
        return [(i, rect) for _distance, i, rect in cells]

    @staticmethod
    def _split(rect: QRectF) -> tuple:
        """(sous-cellule image, sous-cellule texte) d'une cellule : le texte dessous, hauteurs dans le
        rapport `viewer_film_text_ratio`."""
        ratio = film_text_ratio()
        image_h = rect.height() / (1.0 + ratio)
        return (QRectF(rect.left(), rect.top(), rect.width(), image_h),
                QRectF(rect.left(), rect.top() + image_h, rect.width(), rect.height() - image_h))

    def _index_at(self, pos: QPointF) -> int:
        for i, rect in reversed(self._cells()):
            if rect.contains(pos):
                return i
        return -1

    def _split_at(self, pos: QPointF):
        """Cellule dont la bordure image | texte est sous `pos` (a SPLIT_GRAB px pres), sinon None."""
        for _i, rect in reversed(self._cells()):
            if rect.left() <= pos.x() <= rect.right():
                line = self._split(rect)[1].top()
                if abs(pos.y() - line) <= self.SPLIT_GRAB:
                    return rect
        return None

    ARRIVE_MS = 180                       # fondu d'une vignette arrivee apres coup
    FILM_REQUEST_BUDGET = 0.004           # s de demandes de decodage par image (le reste : image suivante)

    def paintEvent(self, event):
        if self._alpha <= 0.01 or not self._paths:
            return
        # Jamais de disque pendant l'image (dates en memoire, relues en fond) et reduction des vignettes
        # bornee (FILM_SCALE_BUDGET) : la 1re image apres un long moment ne bloque plus l'animation.
        film_cache._SCALE_DEADLINE = time.perf_counter() + FILM_SCALE_BUDGET   # lu par film_cache.thumbnail
        # Pendant l'APPARITION, aucun decodage lance (ils gardent le GIL en fond et hachaient le fondu) :
        # ce qui manque est demande a l'image qui la termine (_fade_tick repeint a l'arret).
        appearing = self._fade.isActive() and self._alpha_goal > self._alpha
        try:
            with previews.memory_only(hold=appearing):
                self._paint(event)
        finally:
            film_cache._SCALE_DEADLINE = None

    def _thumb_fade(self, path, pix) -> float:
        """Opacite de l'image d'une cellule : 1, sauf pour une vignette arrivee apres que la cellule a ete
        montree sans elle (affichage leger) — fondu sur ARRIVE_MS."""
        key = str(path)
        if pix is None or pix.isNull():
            self._waiting.add(key)
            return 0.0
        now = self._clock.elapsed()
        if key in self._waiting:
            self._waiting.discard(key)
            self._arrived[key] = now
        start = self._arrived.get(key)
        if start is None:
            return 1.0
        amount = (now - start) / self.ARRIVE_MS
        if amount >= 1.0:
            del self._arrived[key]
            return 1.0
        if not self._ramp.isActive():
            self._ramp.start()
        return max(0.0, amount)

    def _paint(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing, True)
        painter.setRenderHint(QPainter.SmoothPixmapTransform, True)
        painter.setOpacity(self._alpha)
        if not self._arrived and self._ramp.isActive():
            self._ramp.stop()
        shade = QLinearGradient(0, 0, 0, self.height())
        shade.setColorAt(0.0, QColor(0, 0, 0, 0))
        shade.setColorAt(0.5, QColor(0, 0, 0, 120))
        shade.setColorAt(1.0, QColor(0, 0, 0, 190))
        painter.fillRect(self.rect(), shade)
        look = _film_look()
        from settings_widgets import paint_shadow
        width = self.width()
        dpr = self.devicePixelRatioF() or 1.0
        side = round(self._tw * (1 + self.GROW) * dpr)
        edge = (self._tw + self._gap) * 1.5
        ext_font, ext_color = look["ext_font"]
        name_font, name_color = look["name_font"]
        rank_font, rank_color = look["rank_font"]
        name_metrics, rank_metrics = QFontMetrics(name_font), QFontMetrics(rank_font)
        count = len(self._paths)
        cells = self._cells()
        # Vignettes, du CENTRE vers les bords ; demandes de decodage etalees : au-dela de
        # FILM_REQUEST_BUDGET dans cette image, les suivantes attendent l'image d'apres (sinon ~90 ms
        # d'un coup a la fin de l'apparition, quand toutes les demandes retenues partaient ensemble).
        thumbs, retry = {}, False
        request_deadline = time.perf_counter() + self.FILM_REQUEST_BUDGET
        for i, _rect in reversed(cells):
            over = time.perf_counter() > request_deadline
            with previews.memory_only(hold=over or previews.requests_held()):
                pix = self._thumb(self._paths[i], side)
            if over and (pix is None or pix.isNull()):
                retry = True
            thumbs[i] = pix
        if retry and not previews.requests_held():
            QTimer.singleShot(16, self.update)
        for i, rect in cells:
            centre = rect.center().x()
            near_edge = max(0.0, min(1.0, min(centre, width - centre) / edge))   # s'efface vers les bords
            emphasis = 1.0 if i in (self._index, self._hover) else 0.72
            painter.setOpacity(self._alpha * near_edge * emphasis)
            if look["table_shadow"] is not None:
                paint_shadow(painter, rect, look["table"]["radius"], look["table_shadow"])
            _paint_film_box(painter, rect, look["table"])
            image_cell, text_cell = self._split(_film_inner(rect, look["table"]))
            _paint_film_box(painter, image_cell, look["image_cell"])
            _paint_film_box(painter, text_cell, look["text_cell"])
            path = self._paths[i]
            room = _film_inner(image_cell, look["image_cell"]).adjusted(2, 2, -2, -2)
            pix = thumbs.get(i)
            fade = self._thumb_fade(path, pix)
            cell_opacity = painter.opacity()
            if fade < 1.0:                       # pas encore la (ou en fondu) : son type de fichier dessous
                painter.setOpacity(cell_opacity * (1.0 - fade))
                painter.setFont(ext_font)
                painter.setPen(ext_color)
                painter.drawText(room, Qt.AlignCenter, path.suffix.lstrip(".").upper())
                painter.setOpacity(cell_opacity * fade)
            if fade > 0.0 and room.width() > 0 and room.height() > 0:
                size = _pixmap_size(pix)
                size.scale(room.width(), room.height(), Qt.KeepAspectRatio)
                image_rect = QRectF(room.center().x() - size.width() / 2, room.center().y() - size.height() / 2,
                                    size.width(), size.height())
                image = look["image"]
                if look["image_shadow"] is not None:
                    paint_shadow(painter, image_rect, image["radius"], look["image_shadow"])
                painter.save()
                if any(image["radius"].values()):
                    from settings_widgets import _rounded_rect_path
                    painter.setClipPath(_rounded_rect_path(image_rect.toRect(), image["radius"]))
                painter.drawPixmap(image_rect, pix, QRectF(pix.rect()))
                painter.restore()
                _paint_film_box(painter, image_rect, image)
            painter.setOpacity(cell_opacity)
            # Sous-cellule texte : le nom ; dans la cellule en cours, suivi du rang (police du tableau).
            text_room = _film_inner(text_cell, look["text_cell"]).adjusted(4, 0, -4, 0)
            rank = f"  {i + 1} / {count}" if i == self._index else ""
            rank_w = rank_metrics.horizontalAdvance(rank) if rank else 0
            name = name_metrics.elidedText(display_name(path), Qt.ElideMiddle,
                                           max(0, int(text_room.width() - rank_w)))
            name_w = name_metrics.horizontalAdvance(name)
            x = text_room.center().x() - (name_w + rank_w) / 2
            painter.setFont(name_font)
            painter.setPen(name_color)
            painter.drawText(QRectF(x, text_room.top(), name_w + 1, text_room.height()),
                             Qt.AlignLeft | Qt.AlignVCenter, name)
            if rank:
                painter.setFont(rank_font)
                painter.setPen(rank_color)
                painter.drawText(QRectF(x + name_w, text_room.top(), rank_w + 1, text_room.height()),
                                 Qt.AlignLeft | Qt.AlignVCenter, rank)
            ring = rect.adjusted(-2, -2, 2, 2)
            radius = max(look["table"]["radius"].values()) + 2
            if i == self._index:
                painter.setBrush(Qt.NoBrush)
                painter.setPen(QPen(QColor(C["accent"]), 2))
                painter.drawRoundedRect(ring, radius, radius)
            elif i == self._hover:
                painter.setBrush(Qt.NoBrush)
                painter.setPen(QPen(QColor(255, 255, 255, 150), 1))
                painter.drawRoundedRect(rect.adjusted(-1, -1, 1, 1), radius - 1, radius - 1)

    def mouseMoveEvent(self, event):
        self.reveal()
        if self._split_drag is not None:
            bottom, image_h = self._split_drag
            text_h = bottom - event.globalPosition().y()
            ratio = max(self.RATIO_MIN, min(self.RATIO_MAX, text_h / max(1.0, image_h)))
            if self._on_split is not None:
                self._on_split(ratio, False)
            self.update()
            return
        pos = event.position()
        if event.modifiers() & Qt.ControlModifier and self._split_at(pos) is not None:
            self.setCursor(Qt.SplitVCursor)
            return
        self.source_tip.update_at(event.globalPosition().toPoint(), bool(event.modifiers() & Qt.ShiftModifier))
        hover = self._index_at(pos)
        if hover != self._hover or self.cursor().shape() == Qt.SplitVCursor:
            self._hover = hover
            self.setCursor(Qt.PointingHandCursor if hover >= 0 else Qt.ArrowCursor)
            self.setToolTip(display_name(self._paths[hover]) if hover >= 0 else "")
            self.update()
        super().mouseMoveEvent(event)

    def leaveEvent(self, event):
        self.source_tip.hide()
        if self._hover != -1:
            self._hover = -1
            self.update()
        self._hold.start()
        super().leaveEvent(event)

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            visible = self._alpha > 0.4
            self.reveal()
            cell = self._split_at(event.position()) if visible and event.modifiers() & Qt.ControlModifier else None
            if cell is not None:
                # Ctrl + bordure image | texte : le bas des cellules reste en place (y global), l'image
                # garde sa hauteur, le texte prend ce que la souris lui donne.
                bottom = self.mapToGlobal(QPointF(0, cell.bottom())).y()
                self._split_drag = (bottom, self._split(cell)[0].height())
                self.setCursor(Qt.SplitVCursor)
                event.accept()
                return
            index = self._index_at(event.position()) if visible else -1
            if index >= 0:
                self.chosen.emit(index)
            event.accept()
            return
        super().mousePressEvent(event)

    def mouseReleaseEvent(self, event):
        if self._split_drag is not None and event.button() == Qt.LeftButton:
            self._split_drag = None
            self.setCursor(Qt.ArrowCursor)
            if self._on_split is not None:
                self._on_split(film_text_ratio(), True)
            event.accept()
            return
        super().mouseReleaseEvent(event)

    def contextMenuEvent(self, event):
        if self._on_menu is not None:
            self.reveal()
            self._on_menu(event.globalPos())
            event.accept()
            return
        super().contextMenuEvent(event)

    def mouseDoubleClickEvent(self, event):
        if event.button() == Qt.LeftButton and self._index_at(event.position()) < 0 and self._on_double_click:
            self._on_double_click()
            return
        super().mouseDoubleClickEvent(event)

    def wheelEvent(self, event):
        if event.modifiers() & Qt.ControlModifier:
            self.reveal()
            self.zoom_thumbs((event.angleDelta().y() or event.angleDelta().x()) / 120)
            event.accept()
            return
        if self._on_wheel is not None:
            self.reveal()
            self._on_wheel(event)
            event.accept()
            return
        super().wheelEvent(event)
