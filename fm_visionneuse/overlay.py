"""Visionneuse plein cadre (FocusOverlay) : ruban d'images, zoom autour du curseur, animations.

Découpé de focus.py (2026-10-28) ; carte : docs/agents/fm_visionneuse.md."""
import math

from PySide6.QtCore import QElapsedTimer, QPointF, QRect, QRectF, QSizeF, Qt, QTimer
from PySide6.QtGui import QBrush, QImage, QPainter, QPixmap, QRegion, QTransform
from PySide6.QtWidgets import QApplication, QWidget

from browser_core import _fine_timer

from .loader import _pixmap_size, _scaled_about, fit_rect
from .film_look import _film_look


class FocusOverlay(QWidget):
    """Objet en FOCUS (image ou image de turntable) qui voyage entre sa place
    dans l'inspecteur (`source`) et le centre de la zone des colonnes
    (`target`), position ET echelle interpolees ensemble. Progression p : 0 =
    a la place de l'inspecteur, 1 = centre. Meme horloge/lissage que
    _FadeOverlay ; `retarget` repart de la valeur courante (clic pendant
    l'animation). Couvre toute la zone, transparent a la souris : seuls les
    pixels de l'objet sont peints. Premier maillon du concept « focus » : le
    contenu est un pixmap pour l'instant, d'autres types (texte...) viendront.

    Au repos au centre, c'est la VISIONNEUSE (set_viewer) : `show_image` fait glisser l'image
    suivante / precedente sur un ruban (decalage `_shift`, en images, qui revient a 0 ; les
    voisines viennent du rappel `neighbours(k)`), `bump` = petit rebond aux extremites, zoom
    anime autour d'un point (`zoom_by`, Ctrl+molette) et deplacement de l'image zoomee a la
    souris."""

    SLIDE_MS = 330
    BUMP_MS = 260

    def __init__(self, parent, pixmap: QPixmap, source: QRectF, target: QRectF, start: float, end: float,
                 duration_ms: int = 420, on_finished=None, on_done=None, on_double_click=None,
                 on_wheel=None):
        super().__init__(parent)
        self.setAttribute(Qt.WA_TransparentForMouseEvents, True)
        self.setGeometry(parent.rect())
        self._source = source
        self._target = target
        self._base = pixmap
        self._cache_key = None
        self._cache = None
        self._value = start
        self._from = start
        self._end = end
        self._duration = max(1, duration_ms)
        self._on_finished = on_finished
        self._on_done = on_done
        # Double-clic sur l'objet AU CENTRE (au repos) : `on_double_click`
        # (meme effet que le bouton « masquer », voir _update_hit_area).
        self._on_double_click = on_double_click
        # Molette sur l'objet au repos : `on_wheel(event)` (image suivante / precedente).
        self._on_wheel = on_wheel
        # Visionneuse (voir set_viewer) : taille reelle de l'image, image pleine definition pour
        # le zoom, voisines du ruban, rappel a chaque pas du ruban (la pellicule suit), zones
        # laissees a la souris (boutons).
        self._natural: QSizeF | None = None
        self._area: QRect | None = None   # zone ou l'image est ajustee (defaut : tout l'overlay)
        self._full: QImage | None = None
        self._neighbours = None
        self._on_moved = None
        self._holes: list = []
        self._shift = 0.0
        self._shift_from = 0.0
        self._slide_t0 = 0
        self._bump_dir = 0
        self._bump_t0 = 0
        self._zoom = 1.0
        self._zoom_goal = 1.0
        self._pan = QPointF()
        self._anchor = None           # (point fixe, position relative dans l'image) du zoom
        self._drag = None
        self._vclock = QElapsedTimer()
        self._vclock.start()
        self._vlast = 0
        self._vtimer = QTimer(self)
        self._vtimer.setTimerType(Qt.PreciseTimer)
        self._vtimer.setInterval(8)
        self._vtimer.timeout.connect(self._viewer_tick)
        # Cadre de l'image (Reglages > Visionneuse > Focus : bordures, border radius), `restyle`.
        look = _film_look()
        self._frame = look["focus_image"]
        self._shadow = look["focus_shadow"]      # Reglages > Visionneuse > Focus > Ombres de l'image
        self._textures: dict = {}     # cacheKey -> copie a ratio de pixels 1 (texture des coins arrondis)
        self.running = True
        self.hold = True    # le proprietaire le retire (voir PipelineBrowser._show_columns_now)
        self._clock = QElapsedTimer()
        self._timer = QTimer(self)
        self._timer.setTimerType(Qt.PreciseTimer)
        self._timer.setInterval(8)
        self._timer.timeout.connect(self._tick)
        self._clock.start()
        _fine_timer(True)
        self._timer.start()

    @staticmethod
    def target_rect(pixmap: QPixmap, area: QRect, margin: int = 40) -> QRectF:
        """Taille reelle si elle tient dans `area` (moins une marge), sinon reduite ;
        centre sur `area`."""
        return fit_rect(_pixmap_size(pixmap), area, margin)

    def _layout_size(self) -> QSizeF:
        """Taille de reference de l'image : sa taille reelle si connue (l'apercu montre en
        attendant la pleine definition prend deja sa place definitive), sinon celle du pixmap."""
        return self._natural if self._natural is not None else _pixmap_size(self._base)

    def _fit_area(self) -> QRect:
        return self._area if self._area is not None else self.parentWidget().rect()

    def set_geometry_target(self, area: QRect | None, source: QRectF = None):
        """Redimensionnement de la fenetre : recentre dans `area` (None : la zone deja connue) et
        suit l'inspecteur si connu."""
        self.setGeometry(self.parentWidget().rect())
        if area is not None:
            self._area = QRect(area)
        self._target = fit_rect(self._layout_size(), self._fit_area())
        if source is not None:
            self._source = source
        self._clamp_pan()
        self._update_hit_area()
        self.update()

    def _update_hit_area(self):
        """Au repos au centre, seuls les pixels de l'objet captent la souris
        (double-clic, deplacement de l'image zoomee) ; partout ailleurs, et pendant
        l'animation, l'overlay reste transparent a la souris."""
        at_center = not self.running and self._value >= 1.0 and self._on_double_click is not None
        # Pendant un glissement / un zoom, pas de masque : il decouperait aussi le DESSIN (voisines
        # du ruban, image qui grandit) ; la souris traverse, la molette arrive par la zone.
        at_center = at_center and not (self._vtimer.isActive() and self._drag is None)
        self.setAttribute(Qt.WA_TransparentForMouseEvents, not at_center)
        if at_center:
            # Le masque decoupe aussi le DESSIN : il couvre l'ombre de l'image (un clic dessus = un clic a
            # cote de l'image, meme effet).
            grow = self._shadow["size"] if self._shadow is not None else 0
            region = QRegion(self._view_rect().toAlignedRect().adjusted(-grow, -grow, grow, grow)
                             .intersected(self.rect()))
            for hole in self._holes:
                region -= QRegion(hole)
            self.setMask(region)
            self.setCursor(Qt.OpenHandCursor if self.zoomed() else Qt.ArrowCursor)
        else:
            self.clearMask()

    def mouseDoubleClickEvent(self, event):
        if event.button() == Qt.LeftButton and self._on_click is not None:
            event.accept()                   # visionneuse : pas de double-clic sur l'image (le clic agit seul)
            return
        if event.button() == Qt.LeftButton and self._on_double_click is not None:
            self._drag = None
            self._on_double_click()
            return
        super().mouseDoubleClickEvent(event)

    # Clic SIMPLE sur l'image (visionneuse) : agit AUSSITOT au relachement (demande de l'utilisateur :
    # plus de double-clic sur l'image, qui obligeait a attendre son delai) ; un glisser (image zoomee
    # deplacee) n'en est pas un.
    _click_at = None
    _on_click = None

    def wheelEvent(self, event):
        if self._on_wheel is not None:
            self._on_wheel(event)
            event.accept()
            return
        super().wheelEvent(event)

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton and self._on_click is not None and self._at_rest():
            self._click_at = event.globalPosition()
        if event.button() == Qt.LeftButton and self.zoomed() and self._at_rest():
            self._drag = (event.position(), QPointF(self._pan))
            self.setCursor(Qt.ClosedHandCursor)
            event.accept()
            return
        if self._click_at is not None:
            event.accept()
            return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        if self._drag is not None:
            start, pan = self._drag
            self._pan = pan + (event.position() - start)
            self._clamp_pan()
            self.update()
            event.accept()
            return
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        press, self._click_at = self._click_at, None
        clicked = (press is not None and event.button() == Qt.LeftButton and self._on_click is not None
                   and (event.globalPosition() - press).manhattanLength() < QApplication.startDragDistance())
        dragged = self._drag is not None and event.button() == Qt.LeftButton
        if dragged:
            self._drag = None
            self._update_hit_area()
        if clicked and self._at_rest():
            self._on_click(QPointF(event.position()))
        if dragged or clicked or press is not None:
            event.accept()
            return
        if press is not None:
            event.accept()
            return
        super().mouseReleaseEvent(event)

    def retarget(self, end: float, on_finished=None):
        self.reset_view()
        self._from = self._value
        self._end = end
        self._on_finished = on_finished
        self.running = True
        self._update_hit_area()
        self._clock.restart()
        if not self._timer.isActive():
            _fine_timer(True)
            self._timer.start()

    def current_rect(self) -> QRectF:
        t = self._value
        s, e = self._source, self._target
        return QRectF(s.x() + (e.x() - s.x()) * t, s.y() + (e.y() - s.y()) * t,
                      s.width() + (e.width() - s.width()) * t, s.height() + (e.height() - s.height()) * t)

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.SmoothPixmapTransform, True)
        if self._at_rest():
            self._paint_viewer(painter)
            return
        rect = self.current_rect()
        # Pre-reduit a la plus grande des deux tailles extremes : dessiner une
        # grande image reduite a chaque image de l'animation serait trop lent.
        big_w = max(self._source.width(), self._target.width())
        pixmap = self._display_pixmap(big_w)
        # Cadre (bordures, border radius) : il s'installe avec le trajet vers le centre (0 a l'inspecteur
        # ou dans la case de la planche, entier au centre), sans saut a l'arrivee.
        self._paint_framed(painter, rect, pixmap, max(0.0, min(1.0, self._value)))

    def restyle(self):
        """Reglages > Visionneuse > Focus changes : nouveau cadre de l'image."""
        look = _film_look()
        self._frame = look["focus_image"]
        self._shadow = look["focus_shadow"]
        self._update_hit_area()                  # la zone cliquable couvre l'ombre (sinon son masque la coupe)
        self.update()

    def _texture(self, src):
        """`src` (QPixmap / QImage) a ratio de pixels 1 : la texture d'un pinceau Qt est mal mise a
        l'echelle sinon (mesure : 2 fois trop petite a 1,5, 4 fois a 2). Copie faite une fois, gardee."""
        if (src.devicePixelRatio() or 1.0) == 1.0:
            return src
        key = src.cacheKey()
        tex = self._textures.get(key)
        if tex is None:
            tex = src.copy()
            tex.setDevicePixelRatio(1.0)
            if len(self._textures) > 6:
                self._textures.clear()
            self._textures[key] = tex
        return tex

    def _paint_framed(self, painter: QPainter, rect: QRectF, src, strength: float = 1.0):
        """Image `src` (QPixmap ou QImage, entiere) dans `rect`, avec le cadre de Reglages > Visionneuse >
        Focus : coins arrondis LISSES (un setClipPath ne l'est pas : l'image est posee en pinceau sur le
        chemin arrondi) puis bordures par-dessus. `strength` (0-1) : part du cadre (vol vers le centre)."""
        frame = self._frame
        radius = {k: round(v * strength) for k, v in frame["radius"].items()}
        if self._shadow is not None:
            from settings_widgets import paint_shadow
            paint_shadow(painter, rect, radius, self._shadow, strength)
        if any(radius.values()) and rect.width() > 0 and rect.height() > 0:
            from settings_widgets import _rounded_rect_path
            tex = self._texture(src)
            brush = QBrush(tex)
            transform = QTransform()
            transform.translate(rect.x(), rect.y())
            transform.scale(rect.width() / max(1, tex.width()), rect.height() / max(1, tex.height()))
            brush.setTransform(transform)
            painter.save()
            painter.setRenderHint(QPainter.Antialiasing, True)
            painter.setPen(Qt.NoPen)
            painter.setBrush(brush)
            painter.drawPath(_rounded_rect_path(rect, radius))
            painter.restore()
        elif isinstance(src, QImage):
            painter.drawImage(rect, src, QRectF(src.rect()))
        else:
            painter.drawPixmap(rect, src, QRectF(src.rect()))
        if frame["thick"] and strength > 0.0:
            from settings_widgets import _paint_bordered_vector
            painter.save()
            painter.setOpacity(painter.opacity() * strength)
            _paint_bordered_vector(painter, rect.toRect(), radius, frame["on"], frame["thick"], frame["colors"], None)
            painter.restore()

    def _display_pixmap(self, width: float) -> QPixmap:
        """L'image a `width` pixels logiques de large au plus : reduite UNE fois (gardee) si le
        pixmap est nettement plus grand, sinon tel quel."""
        dpr = self._base.devicePixelRatio() or 1.0
        if self._base.width() / dpr <= width * 1.01:
            return self._base
        key = round(width)
        if self._cache_key != key:
            self._cache = self._base.scaledToWidth(max(1, round(width * dpr)), Qt.SmoothTransformation)
            self._cache_key = key
        return self._cache

    def _tick(self):
        distance = abs(self._end - self._from)
        t = min(1.0, self._clock.elapsed() / (self._duration * max(distance, 0.05)))
        eased = t * t * t * (t * (t * 6.0 - 15.0) + 10.0)
        before = self.current_rect()
        self._value = self._from + (self._end - self._from) * eased
        # Seule la zone traversee (ancienne + nouvelle place) est repeinte : ce qui est dessous (planche,
        # colonnes) n'est pas redessine en entier a chaque image.
        grow = 2 + (self._shadow["size"] if self._shadow is not None else 0)    # ombre comprise
        self.update(before.united(self.current_rect()).toAlignedRect().adjusted(-grow, -grow, grow, grow))
        if t >= 1.0:
            self._finish()

    def finish_now(self):
        if self.running:
            self._finish()

    def jump(self, value: float):
        """Pose `value` sans animation ni rappel (une animation en cours est abandonnee)."""
        if self.running:
            self._timer.stop()
            _fine_timer(False)
            self.running = False
        self.reset_view()
        self._on_finished = None
        self._value = self._from = self._end = value
        self._update_hit_area()
        self.update()

    def _finish(self):
        self._timer.stop()
        _fine_timer(False)
        self.running = False
        self._value = self._end
        self._update_hit_area()
        self.update()
        if self._on_finished is not None:
            self._on_finished()
        if self._on_done is not None:
            self._on_done()

    def dispose(self):
        if self.running:
            self._timer.stop()
            _fine_timer(False)
            self.running = False
        self._stop_viewer_anim()
        self.hide()
        self.deleteLater()

    # -- Visionneuse --------------------------------------------------------------------------

    def set_viewer(self, neighbours=None, on_moved=None, holes=None, on_click=None):
        """`neighbours(k)` -> (QPixmap, QSizeF | None) | None : image k places plus loin sur le
        ruban (k negatif : avant) ; `on_moved(decalage)` a chaque pas du ruban ; `holes` :
        rectangles ou la souris passe a travers (boutons) ; `on_click()` : clic simple sur l'image
        (sans glisser ni double-clic, voir mouseReleaseEvent)."""
        self._neighbours = neighbours
        self._on_moved = on_moved
        self._on_click = on_click
        self._holes = list(holes or [])
        self._update_hit_area()

    def set_holes(self, holes):
        self._holes = list(holes or [])
        self._update_hit_area()

    def set_natural(self, natural: QSizeF | None, area: QRect | None = None):
        """Taille reelle de l'image : sa place au centre est calculee sur elle (dans `area`)."""
        self._natural = natural
        if area is not None:
            self._area = QRect(area)
        self._target = fit_rect(self._layout_size(), self._fit_area())
        self._clamp_pan()
        self._update_hit_area()
        self.update()

    def _at_rest(self) -> bool:
        return not self.running and self._value >= 1.0

    def show_image(self, pixmap: QPixmap, natural: QSizeF | None = None, full: QImage | None = None,
                   delta: int = 0):
        """Nouvelle image au centre. `delta` : son ecart avec la precedente (1 = suivante) ;
        elle arrive alors par le ruban du cote ou l'on va (decalage borne a 3 images)."""
        self._reset_zoom()
        self._base = pixmap
        self._cache_key = self._cache = None
        self._full = full
        self._natural = natural
        self._target = fit_rect(self._layout_size(), self._fit_area())
        if delta and self._at_rest() and self._neighbours is not None:
            self._shift_from = self._shift = max(-3.0, min(3.0, self._shift + delta))
            self._slide_t0 = self._vclock.elapsed()
            self._start_viewer_anim()
        self._update_hit_area()
        self.update()

    def upgrade(self, pixmap: QPixmap, natural: QSizeF | None = None, full: QImage | None = None):
        """Meme image, meilleure definition (pleine definition arrivee en fond) : rien ne bouge."""
        self._base = pixmap
        self._cache_key = self._cache = None
        if full is not None:
            self._full = full
        if natural is not None:
            self._natural = natural
        # Taille reelle connue : meme place. Sinon (apercu remplacant une carte) : celle du pixmap.
        self._target = fit_rect(self._layout_size(), self._fit_area())
        self._clamp_pan()
        self._update_hit_area()
        self.update()

    def bump(self, direction: int):
        """Plus d'image dans cette direction : l'image esquisse le mouvement et revient."""
        if not self._at_rest():
            return
        self._bump_dir = 1 if direction > 0 else -1
        self._bump_t0 = self._vclock.elapsed()
        self._start_viewer_anim()

    def ribbon_offset(self) -> float:
        """Decalage visuel du ruban, en images (0 = image en cours au centre)."""
        offset = self._shift
        if self._bump_dir:
            u = min(1.0, (self._vclock.elapsed() - self._bump_t0) / self.BUMP_MS)
            offset -= self._bump_dir * 0.06 * math.sin(math.pi * u) * (1.0 - u)
        return offset

    def animating(self) -> bool:
        return self.running or self._vtimer.isActive() or self._drag is not None

    def zoomed(self) -> bool:
        return self._zoom_goal > 1.001 or self._zoom > 1.001

    def _max_zoom(self) -> float:
        actual = self._actual_zoom()
        return max(4.0, min(40.0, actual * 4.0))

    def _actual_zoom(self) -> float:
        """Zoom ou l'image est a sa taille reelle (1 pixel image = 1 pixel logique)."""
        width = self._target.width()
        return max(1.0, self._layout_size().width() / width) if width > 0 else 1.0

    def zoom_by(self, factor: float, anchor: QPointF | None = None):
        """Zoom anime vers zoom courant * `factor`, en gardant fixe le point `anchor` (repere de
        l'overlay ; centre de l'image par defaut). 1 = image ajustee."""
        if not self._at_rest():
            return
        goal = max(1.0, min(self._max_zoom(), self._zoom_goal * factor))
        self._zoom_to(goal, anchor)

    def zoom_reset(self):
        self._zoom_to(1.0, None)

    def zoom_toggle_actual(self, anchor: QPointF | None = None):
        """Ajustee <-> taille reelle (sans effet si l'image tient deja a sa taille reelle)."""
        actual = self._actual_zoom()
        if actual <= 1.01 and not self.zoomed():
            return
        self._zoom_to(1.0 if self.zoomed() else actual, anchor)

    def _zoom_to(self, goal: float, anchor: QPointF | None):
        if not self._at_rest():
            return
        self._zoom_goal = goal
        # Point fixe : `anchor` (centre de la zone par defaut) et sa position RELATIVE dans
        # l'image, relevee une fois : chaque image du zoom en repart (le recentrage d'une image
        # encore plus petite que la zone ne s'accumule donc pas).
        anchor = QPointF(anchor) if anchor is not None else QPointF(self._fit_area().center())
        view = self._view_rect()
        self._anchor = (anchor, (anchor.x() - view.x()) / max(1e-6, view.width()),
                        (anchor.y() - view.y()) / max(1e-6, view.height()))
        self._start_viewer_anim()

    def _reset_zoom(self):
        self._zoom = self._zoom_goal = 1.0
        self._pan = QPointF()
        self._anchor = None
        self._drag = None

    def reset_view(self):
        """Sans animation : image ajustee, au centre du ruban (avant un vol, un changement d'etat)."""
        self._reset_zoom()
        self._shift = self._shift_from = 0.0
        self._bump_dir = 0
        self._stop_viewer_anim()
        if self._on_moved is not None:
            self._on_moved(0.0)
        self._update_hit_area()
        self.update()

    def _view_rect(self) -> QRectF:
        """Place de l'image en cours au repos : ajustee, zoomee autour de son centre + deplacement."""
        t = self._target
        z = self._zoom
        c = t.center() + self._pan
        return QRectF(c.x() - t.width() * z / 2, c.y() - t.height() * z / 2, t.width() * z, t.height() * z)

    def _clamp_pan(self):
        """Une image zoomee plus grande que la zone la couvre toujours (pas de bord vide) ; plus
        petite, elle reste centree."""
        t = self._target
        z = self._zoom
        area = QRectF(self.rect())
        base = t.center()
        x, y = self._pan.x(), self._pan.y()
        w, h = t.width() * z, t.height() * z
        if w <= area.width():
            x = 0.0
        else:
            x = max(area.right() - w / 2, min(area.left() + w / 2, base.x() + x)) - base.x()
        if h <= area.height():
            y = 0.0
        else:
            y = max(area.bottom() - h / 2, min(area.top() + h / 2, base.y() + y)) - base.y()
        self._pan = QPointF(x, y)

    def _start_viewer_anim(self):
        if not self._vtimer.isActive():
            self._vlast = self._vclock.elapsed()
            _fine_timer(True)
            self._vtimer.start()
            self._update_hit_area()          # masque retire le temps du mouvement

    def _stop_viewer_anim(self):
        if self._vtimer.isActive():
            self._vtimer.stop()
            _fine_timer(False)

    def _viewer_tick(self):
        now = self._vclock.elapsed()
        dt = max(0.001, (now - self._vlast) / 1000.0)
        self._vlast = now
        busy = False
        if self._shift_from:
            u = min(1.0, (now - self._slide_t0) / self.SLIDE_MS)
            self._shift = self._shift_from * (1.0 - u) ** 3     # depart vif, arrivee douce
            if u >= 1.0:
                self._shift = self._shift_from = 0.0
            else:
                busy = True
        if self._bump_dir:
            if now - self._bump_t0 >= self.BUMP_MS:
                self._bump_dir = 0
            else:
                busy = True
        if abs(self._zoom - self._zoom_goal) > 1e-6:
            z1 = self._zoom_goal + (self._zoom - self._zoom_goal) * math.exp(-dt / 0.06)
            if abs(z1 - self._zoom_goal) < self._zoom_goal * 0.002:
                z1 = self._zoom_goal
            self._zoom = z1
            if self._anchor is not None:
                # Le point de l'image sous le curseur reste sous le curseur.
                anchor, u, v = self._anchor
                t = self._target
                centre = QPointF(anchor.x() - (u - 0.5) * t.width() * z1, anchor.y() - (v - 0.5) * t.height() * z1)
                self._pan = centre - t.center()
            self._clamp_pan()
            busy = busy or z1 != self._zoom_goal
        if self._on_moved is not None:
            self._on_moved(self.ribbon_offset())
        self.update()
        if not busy:
            self._stop_viewer_anim()
            self._update_hit_area()

    def _paint_viewer(self, painter: QPainter):
        offset = self.ribbon_offset()
        if abs(offset) < 1e-4 or self._neighbours is None:
            self._draw_current(painter, self._view_rect())
            return
        # Ruban : chaque image a sa place k (0 = en cours), decalee de (k + offset) pas ; elle
        # recule, retrecit un peu et s'efface en s'eloignant du centre. La plus proche par-dessus.
        stride = max(1.0, self.width() * 0.72)
        area = self._fit_area()
        items = []
        for k in range(math.floor(-offset) - 1, math.ceil(-offset) + 2):
            d = k + offset
            if abs(d) >= 1.0:
                continue
            if k == 0:
                items.append((abs(d), d, None, self._view_rect()))
                continue
            got = self._neighbours(k)
            if not got:
                continue
            pixmap, natural = got
            size = natural if natural is not None else _pixmap_size(pixmap)
            items.append((abs(d), d, pixmap, fit_rect(size, area)))
        for distance, d, pixmap, rect in sorted(items, key=lambda item: -item[0]):
            painter.setOpacity(max(0.0, min(1.0, (1.0 - distance) / 0.65)))
            moved = _scaled_about(rect, 1.0 - 0.1 * distance, d * stride)
            if pixmap is None:
                self._draw_current(painter, moved)
            else:
                self._paint_framed(painter, moved, pixmap)
        painter.setOpacity(1.0)

    def _draw_current(self, painter: QPainter, rect: QRectF):
        dpr = self.devicePixelRatioF() or 1.0
        if self._full is not None and rect.width() * dpr > self._base.width() * 1.02:
            # Zoom au-dela de la version ajustee : l'image pleine definition (seule la partie
            # visible est echantillonnee).
            self._paint_framed(painter, rect, self._full)
            return
        self._paint_framed(painter, rect, self._display_pixmap(rect.width()))
