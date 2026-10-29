"""Animations, filtres de survol et temporisateurs haute résolution. Carte : docs/agents/colonnes.md."""

import sys
from PySide6.QtCore import QElapsedTimer, QEvent, QObject, QRect, Qt, QTimer
from PySide6.QtGui import QColor, QPainter, QPixmap, QRegion
from PySide6.QtWidgets import QWidget

class _HoverPrime(QObject):
    """Appelle `callback` quand la souris entre sur le widget surveille : sert a
    preparer une capture (voir PipelineBrowser._prime_*) pendant que
    l'utilisateur approche du bouton, pour que le clic n'ait plus rien a calculer."""

    def __init__(self, widget, callback):
        super().__init__(widget)
        self._callback = callback
        widget.installEventFilter(self)

    def eventFilter(self, obj, event):
        if event.type() == QEvent.Enter:
            self._callback()
        return False

_GIL_USERS = [0]

_SWITCH_INTERVAL = [None]

def _snappy_gil(enable: bool) -> None:
    """Appels apparies, pendant une animation LEGERE pour Python (chaque image pose une image toute
    faite : glissement de la planche) : le verrou de Python (GIL) change de main toutes les 0,5 ms au
    lieu de 5. Un decodage d'apercu en fond (code Python du pipeline) le gardait jusqu'a 5 ms a chaque
    retour du fil de l'interface depuis Qt : images de 30 a 60 ms au lieu de 11 (mesure :
    tests/_probe_gallery_scroll.py). PAS pour une animation qui peint beaucoup en Python (ouverture de la
    planche : sa peinture, sans cesse interrompue, passait de 5 a 25 ms, tests/_probe_gallery_frames.py)."""
    _GIL_USERS[0] = max(0, _GIL_USERS[0] + (1 if enable else -1))
    if enable and _GIL_USERS[0] == 1:
        _SWITCH_INTERVAL[0] = sys.getswitchinterval()
        sys.setswitchinterval(0.0005)
    elif not enable and _GIL_USERS[0] == 0 and _SWITCH_INTERVAL[0] is not None:
        sys.setswitchinterval(_SWITCH_INTERVAL[0])
        _SWITCH_INTERVAL[0] = None

def _fine_timer(enable: bool) -> None:
    """Windows : resolution d'horloge a 1 ms pendant une animation (sinon les
    minuteurs ne tombent que tous les ~15,6 ms). Appels apparies (compteur
    interne du systeme) ; sans effet ailleurs."""
    if sys.platform != "win32":
        return
    try:
        import ctypes
        (ctypes.windll.winmm.timeBeginPeriod if enable else ctypes.windll.winmm.timeEndPeriod)(1)
    except (AttributeError, OSError):
        pass

class _FadeOverlay(QWidget):
    """Image FIXE (capture prealable) dont l'opacite est animee au-dessus du
    contenu — beaucoup plus fluide qu'un QGraphicsOpacityEffect sur de vrais
    widgets (qui les re-rendrait a chaque image) : une seule copie de pixmap
    par image, pendant que les vrais widgets sont deja masques dessous.
    Progression calculee sur l'horloge (pas sur un compteur d'images) : la
    duree reste exacte meme si des images sont sautees ; lissage
    « smootherstep »."""

    def __init__(self, parent, pixmap: QPixmap, rect: QRect, start: float, end: float,
                 duration_ms: int = 260, on_finished=None, on_done=None):
        super().__init__(parent)
        self.setAttribute(Qt.WA_TransparentForMouseEvents, True)
        self.setGeometry(rect)
        self._pixmap = pixmap
        self._spans = []
        self._background = None
        self._exclude = None
        self.hold = False
        self._value = start
        self._from = start
        self._end = end
        self._duration = max(1, duration_ms)
        self._on_finished = on_finished
        self._on_done = on_done
        self.running = True
        self._clock = QElapsedTimer()
        self._timer = QTimer(self)
        self._timer.setTimerType(Qt.PreciseTimer)
        self._timer.setInterval(8)
        self._timer.timeout.connect(self._tick)
        self._clock.start()
        _fine_timer(True)
        self._timer.start()

    STAGGER = 0.45    # part de la duree sur laquelle s'etale le depart des colonnes

    def set_spans(self, spans: list):
        """Bandes (x0, x1) en coordonnees de l'overlay, une par colonne, de gauche a
        droite : la plus a DROITE s'estompe la premiere, puis chacune a la suite
        jusqu'a la plus a gauche (a l'envers a l'affichage)."""
        self._spans = spans if len(spans) > 1 else []

    def set_exclude(self, provider):
        """`provider()` donne (a chaque image) un QRect, en coordonnees du parent, a ne PAS
        recouvrir (ou None) : un contenu opaque passe par-dessus le fondu."""
        self._exclude = provider

    def set_holes(self, rects: list):
        """Zones laissees libres (les boutons, qui ne doivent pas s'estomper),
        en coordonnees du parent."""
        region = QRegion(self.rect())
        for rect in rects:
            region = region.subtracted(QRegion(rect.translated(-self.pos())))
        self.setMask(region)

    def retarget(self, end: float, on_finished=None):
        """Repart de la valeur COURANTE vers `end` (clic pendant le fondu)."""
        self._from = self._value
        self._end = end
        self._on_finished = on_finished
        self._clock.restart()
        if not self._timer.isActive():
            self._timer.start()

    def paintEvent(self, event):
        painter = QPainter(self)
        if self._background is not None:
            painter.fillRect(self.rect(), self._background)
        if self._exclude is not None:
            hole = self._exclude()
            if hole is not None:
                painter.setClipRegion(QRegion(self.rect()).subtracted(QRegion(hole.translated(-self.pos()))))
        if not self._spans:
            painter.setOpacity(self._value)
            painter.drawPixmap(0, 0, self._pixmap)
            return
        n = len(self._spans)
        step = self.STAGGER / (n - 1)
        q = 1.0 - self._value
        dpr = self._pixmap.devicePixelRatio()
        height = self.height()
        for i, (x0, x1) in enumerate(self._spans):
            rank = n - 1 - i
            local = min(1.0, max(0.0, (q - rank * step) / (1.0 - self.STAGGER)))
            opacity = 1.0 - local * local * (3.0 - 2.0 * local)
            if opacity <= 0.0 or x1 <= x0:
                continue
            painter.setOpacity(opacity)
            painter.drawPixmap(QRect(x0, 0, x1 - x0, height), self._pixmap,
                               QRect(int(x0 * dpr), 0, int((x1 - x0) * dpr), int(height * dpr)))

    def _tick(self):
        distance = abs(self._end - self._from)
        t = min(1.0, self._clock.elapsed() / (self._duration * max(distance, 0.05)))
        eased = t * t * t * (t * (t * 6.0 - 15.0) + 10.0)
        self._value = self._from + (self._end - self._from) * eased
        self.update()
        if t >= 1.0:
            self._finish()

    def finish_now(self):
        if self.running:
            self._finish()

    def _finish(self):
        self._timer.stop()
        _fine_timer(False)
        self.running = False
        self._value = self._end
        # try/finally : une erreur dans un rappel ne doit jamais laisser l'image
        # figee par-dessus les colonnes (ni le proprietaire croire le fondu en cours).
        try:
            if self._on_finished is not None:
                self._on_finished()
        finally:
            try:
                if not self.hold:   # hold : le proprietaire le retire (pas de trou avant la suite)
                    self.hide()
                    self.deleteLater()
            finally:
                if self._on_done is not None:
                    self._on_done()

class _SlideOverlay(QWidget):
    """Repli/depli des colonnes de set joue sur des CAPTURES (comme _FadeOverlay) :
    `left` = colonnes de set (etat deplie), `right` = les colonnes qui suivent, jusqu'a
    l'inspecteur (qui, lui, ne bouge pas : l'overlay s'arrete a `limit`).
    Progression p (0 = replie, 1 = deplie) : les colonnes de set « rentrent » dans
    l'ecran — elles reculent vers la gauche, plus lentement, en s'assombrissant —
    pendant que les autres colonnes glissent PAR-DESSUS elles (ombre portee sur leur
    bord gauche) ; l'inverse au depliage. Deux copies de pixmap par image, aucune
    mise en page recalculee. Opaque (fond fourni) : les vrais widgets, deja dans leur
    position FINALE dessous, restent caches."""

    RETREAT = 0.35    # part de leur largeur dont les colonnes de set reculent
    SHADOW = 26       # largeur (px) de l'ombre portee sur le bord gauche des colonnes qui passent

    def __init__(self, parent, left: QPixmap, right: QPixmap, x_collapsed: int, x_expanded: int,
                 background: QColor, start: float, end: float, duration_ms: int = 200, on_finished=None,
                 on_done=None, limit: int | None = None, retreat: float | None = None, shade: float = 0.45,
                 emerge: bool = False, on_progress=None, origin: int = 0):
        super().__init__(parent)
        # `origin` (apparition seulement) : l'overlay ne couvre qu'à partir de cet x (coordonnées du parent) ;
        # à sa gauche rien ne bouge, les vrais widgets restent visibles (captures plus petites, moins de
        # colonnes à repeindre : leur coût grandissait avec la profondeur). `left` commence alors à `origin`.
        self._origin = max(0, int(origin)) if emerge else 0
        # on_progress(p) : appele a chaque image (et a l'arrivee) — sert a faire suivre
        # l'inspecteur, qui se redimensionne en meme temps que le mouvement.
        self._on_progress = on_progress
        # emerge : les colonnes de droite sortent de DESSOUS celles de gauche
        # (qui restent fixes au premier plan) au lieu de glisser par-dessus.
        self._emerge = emerge
        self.emerge = emerge
        self._retreat = self.RETREAT if retreat is None else retreat
        self._shade = shade
        self.setAttribute(Qt.WA_TransparentForMouseEvents, True)
        # Opaque : Qt n'a plus a redessiner les widgets places dessous a chaque image.
        self.setAttribute(Qt.WA_OpaquePaintEvent, True)
        width = parent.width() if limit is None else max(1, min(limit, parent.width()))
        self.setGeometry(QRect(self._origin, 0, max(1, width - self._origin), parent.height()))
        self._left = left
        self._right = right
        self._xa = x_collapsed
        self._xb = x_expanded
        self._bg = background
        self._value = start
        self._from = start
        self._end = end
        self._duration = max(1, duration_ms)
        self._on_finished = on_finished
        self._on_done = on_done
        self.running = True
        self._clock = QElapsedTimer()
        self._timer = QTimer(self)
        self._timer.setTimerType(Qt.PreciseTimer)
        self._timer.setInterval(8)
        self._timer.timeout.connect(self._tick)
        self._clock.start()
        _fine_timer(True)
        self._timer.start()

    def retarget(self, end: float, on_finished=None):
        self._from = self._value
        self._end = end
        self._on_finished = on_finished
        self._clock.restart()
        if not self._timer.isActive():
            self._timer.start()

    def right_rect(self, content_width: int | None = None) -> QRect:
        """Emplacement actuel de la capture de droite (coordonnees du parent) ; `content_width`
        = largeur du contenu reel qu'elle porte (la capture, elle, se prolonge en fond)."""
        right_w = 0 if self._right.isNull() else int(self._right.deviceIndependentSize().width())
        if content_width is not None:
            right_w = min(right_w, content_width)
        right_x = int(round(self._xa + (self._xb - self._xa) * self._value))
        return QRect(right_x, 0, right_w, self.height())   # coordonnées du parent (origin compris)

    def paintEvent(self, event):
        # Peu de pixels touches par image : pas de remplissage integral du fond (seulement
        # les bandes non couvertes) et copies sans melange (captures opaques) — a l'ecran
        # haute definition, trois copies plein ecran toutes les 8 ms faisaient saccader.
        painter = QPainter(self)
        p = self._value
        height = self.height()
        width = self.width() + self._origin
        if self._origin:
            painter.translate(-self._origin, 0)     # dessin en coordonnées du parent
        left_w = int(self._left.deviceIndependentSize().width())
        right_w = 0 if self._right.isNull() else int(self._right.deviceIndependentSize().width())
        if self._emerge:
            right_x = int(round(self._xa + (self._xb - self._xa) * p))
            left_x = self._origin
        else:
            right_x = int(round(self._xa + (self._xb - self._xa) * p))
            left_x = -int(round(self._xb * self._retreat * (1.0 - p)))
        covered_left = left_x + left_w
        painter.setCompositionMode(QPainter.CompositionMode_Source)
        # bandes de fond non couvertes (entre les deux captures, apres la capture de droite)
        if right_x > covered_left:
            painter.fillRect(QRect(max(0, covered_left), 0, right_x - max(0, covered_left), height), self._bg)
        end = right_x + right_w
        if end < width:
            painter.fillRect(QRect(max(0, end), 0, width - max(0, end), height), self._bg)
        if self._emerge:
            if right_w:
                painter.drawPixmap(right_x, 0, self._right)
            painter.drawPixmap(self._origin, 0, self._left)
            return
        # 1. colonnes de set, qui reculent (et s'assombrissent a mesure)
        painter.drawPixmap(left_x, 0, self._left)
        shade = int(255 * self._shade * (1.0 - p))
        if shade > 0 and right_x > 0:
            painter.setCompositionMode(QPainter.CompositionMode_SourceOver)
            painter.fillRect(QRect(0, 0, right_x, height), QColor(0, 0, 0, shade))
            painter.setCompositionMode(QPainter.CompositionMode_Source)
        # 2. les autres colonnes, au premier plan
        if right_w:
            painter.drawPixmap(right_x, 0, self._right)

    def _tick(self):
        distance = abs(self._end - self._from)
        t = min(1.0, self._clock.elapsed() / (self._duration * max(distance, 0.05)))
        eased = 1.0 - (1.0 - t) ** 3
        self._value = self._from + (self._end - self._from) * eased
        try:
            if self._on_progress is not None:
                self._on_progress(self._value)
        except Exception:
            # Rappel en erreur : on termine plutot que de rester bloque en cours.
            self._complete()
            raise
        self.update()
        if t >= 1.0:
            self._complete()

    def finish_now(self):
        if self.running:
            self._complete()

    def _complete(self):
        if not self.running:
            return
        self._timer.stop()
        _fine_timer(False)
        self.running = False
        self._value = self._end
        # Meme garantie que _FadeOverlay._finish : l'overlay disparait toujours.
        try:
            if self._on_progress is not None:
                self._on_progress(self._value)
            if self._on_finished is not None:
                self._on_finished()
        finally:
            try:
                self.hide()
                self.deleteLater()
            finally:
                if self._on_done is not None:
                    self._on_done()
