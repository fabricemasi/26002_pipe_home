"""Vue d'un board : canvas infini, zoom 10-400 % AUTOUR DU CURSEUR, deplacement, et les outils.

Souris : molette = zoom (Maj + molette = deplacement horizontal, pave tactile : geste de pincement) ; bouton du
milieu, Espace tenu ou outil Main = deplacer le canvas ; outil Selection = clic / cadre de selection / deplacer
(aimante) / poignees ; tirer un point de connexion bleu = une fleche ; Ctrl + clic sur un element qui a un lien
= l'ouvrir.
Outils (touche, comme Miro quand elle existe) : Selection (V), Main (H), Post-it (N), Texte (T), Forme (S ; R =
rectangle, O = ellipse), Connecteur (L), Stylo (P), Surligneur, Dessin intelligent, Gomme (E), Gomme de
precision, Lasso, Commentaire (C), Cadre (F). Un element pose = retour a la Selection (sauf les outils de
dessin).
Clavier : Suppr / Retour arriere = supprimer, Ctrl+Z / Ctrl+Y (Ctrl+Maj+Z) = annuler / retablir, Ctrl+C / X / V,
Ctrl+D = dupliquer, Ctrl+A = tout, Ctrl+Maj+L = verrouiller, Ctrl+0 = 100 %, Maj+1 = tout voir, + / - = zoom,
fleches = deplacer (Maj = 1 unite), Echap = annuler / deselectionner / Selection. Glisser des images (ou les
coller) = elles sont copiees dans le dossier du board."""
from __future__ import annotations

import math
from pathlib import Path

from PySide6.QtCore import (QBuffer, QByteArray, QEvent, QIODevice, QLineF, QMimeData, QPoint, QPointF, QRect, QRectF,
                            QSize, Qt, QTimer, QUrl, Signal)
from PySide6.QtGui import (QColor, QDesktopServices, QImage, QImageReader, QKeySequence, QPainter, QPainterPath, QPen,
                           QPixmap,
                           QPolygonF, QRegion, QTransform)
from PySide6.QtWidgets import (QApplication, QFrame, QGraphicsItem, QGraphicsLineItem, QGraphicsPathItem,
                               QGraphicsView, QWidget)

from . import model, serialization
from fm_miro import smart
from fm_miro.items import BoardItem, CommentItem, ConnectorItem, InkItem, ink_path, ink_pen, shape_path
from .scene import CLIPBOARD_MIME, BoardScene

BADGE_GL = (0, 255, 0)             # encart du mode de rendu : OPEN GL
BADGE_CLASSIC = (255, 0, 0)         # CLASSIQUE


def paint_render_badge(painter, rect, gl: bool):
    """Encart « OPEN GL » (vert) / « CLASSIQUE » (rouge) : fond noir a 15 %, coins de 3 px. Peint par le widget de
    l'encart (rendu classique) ou DANS la couche GPU (un widget translucide au-dessus d'un QOpenGLWidget est compose opaque)."""
    painter.save()
    painter.setRenderHint(QPainter.Antialiasing, True)
    painter.setPen(Qt.NoPen)
    painter.setBrush(QColor(0, 0, 0, 38))                   # noir, 15 % d'opacite
    painter.drawRoundedRect(QRectF(rect), 3, 3)
    painter.setPen(QColor(*(BADGE_GL if gl else BADGE_CLASSIC)))
    font = painter.font()
    font.setPixelSize(12)
    font.setBold(True)
    painter.setFont(font)
    painter.drawText(rect, Qt.AlignCenter, "OPEN GL" if gl else "CLASSIQUE")
    painter.restore()


CACHE_MAX_ZOOM = 4.0          # au-dela, les images gardees des elements seraient enormes : peints directement
IMAGE_SUFFIXES = {".png", ".jpg", ".jpeg", ".gif", ".bmp", ".webp", ".tif", ".tiff"}
TOOL_KEYS = {Qt.Key_V: "select", Qt.Key_H: "hand", Qt.Key_N: "sticky", Qt.Key_T: "text", Qt.Key_S: "shape",
             Qt.Key_L: "connector", Qt.Key_P: "pen", Qt.Key_E: "eraser", Qt.Key_C: "comment", Qt.Key_F: "frame"}
DRAW_TOOLS = ("pen", "highlighter", "smart", "eraser", "precision_eraser", "lasso")
ERASER_SIZES = {"S": 8, "M": 18, "L": 36}          # gomme de precision : diametre en pixels d'ecran


class BoardView(QGraphicsView):
    zoomChanged = Signal(float)
    toolChanged = Signal(str)
    commentOpened = Signal(object, bool)       # CommentItem, nouveau (pas encore dans l'annulation)
    renderModeChanged = Signal(bool)           # rendu OpenGL (vrai) ou classique (faux) : voir `set_gpu`
    gpuFailed = Signal(str)                    # rendu GPU du CAD impossible : retour au rendu par lots (message)

    def __init__(self, scene: BoardScene, parent=None, opengl: bool = False):
        super().__init__(scene, parent)
        if opengl:
            try:
                from PySide6.QtOpenGLWidgets import QOpenGLWidget
                self.setViewport(QOpenGLWidget())
            except Exception:
                pass
        self.setRenderHints(QPainter.Antialiasing | QPainter.SmoothPixmapTransform | QPainter.TextAntialiasing)
        self.setFrameShape(QFrame.NoFrame)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.setTransformationAnchor(QGraphicsView.NoAnchor)
        self.setResizeAnchor(QGraphicsView.AnchorViewCenter)
        self.setViewportUpdateMode(QGraphicsView.FullViewportUpdate)
        self.setOptimizationFlags(QGraphicsView.DontSavePainterState)
        self.setDragMode(QGraphicsView.RubberBandDrag)
        self.setRubberBandSelectionMode(Qt.IntersectsItemShape)
        self.setAcceptDrops(True)
        self.setMouseTracking(True)
        self.viewport().grabGesture(Qt.PinchGesture)
        self.tool = "select"
        self.shape_kind = "rect"
        # Outils de dessin : style du preset choisi (barre de dessin, `ui`) ; taille de la gomme de precision.
        self.ink_styles = {"pen": {"color": model.MIRO_INK, "width": 2.0},
                           "highlighter": {"color": "#fac710", "width": 16.0, "opacity": 0.45},
                           "smart": {"color": model.MIRO_INK, "width": 2.0}}
        self.eraser_size = "M"
        # Format des cadres a creer (barre d'outils > Cadre) : voir model.FRAME_FORMATS.
        self.frame_format = {"format": "free", "orientation": "landscape", "ratio": [16.0, 9.0],
                             "ratio_locked": False}
        self._zoom = 1.0
        self._pan = None
        self._gpu_texts = None          # textes des cotes peints dans la couche GPU (cette image)
        self._pan_frame = None          # image du viewport pendant un deplacement (voir _pan_paint)
        self.gpu_badge = None           # QRect (viewport) de l'encart du mode de rendu, peint dans la couche GPU
        self.zoom_step = 1.15                   # facteur de zoom par cran de molette (Reglages > Module MRO > Navigation)
        self.zoom_fine_step = 1.03              # idem avec Maj : zoom fin
        self._pan_shift = [0, 0]
        self._space = False
        self._draft = None
        self._press = None
        self.cad = None                 # module CAD (fm_cad/cad.py) : actif, il recoit souris et clavier
        self.design = None              # module Design (fm_design/controller.py) : idem quand il est actif

    def _cad_on(self) -> bool:
        return self.cad is not None and self.cad.active

    def _design_on(self) -> bool:
        return self.design is not None and self.design.active

    # -- rendu GPU du CAD (fm_cad/cad_gpu.py, reglage board_cad_gpu) --
    def set_gpu(self, on: bool) -> bool:
        """Couche OpenGL du CAD allumee / eteinte ; faux si OpenGL est indisponible (rendu par lots du processeur)."""
        ok = self._set_gpu(on)
        self.renderModeChanged.emit(getattr(self, "gpu", None) is not None)
        return ok

    def gpu_active(self) -> bool:
        return getattr(self, "gpu", None) is not None

    def _set_gpu(self, on: bool) -> bool:
        from fm_cad import cad_gpu
        from fm_cad.cad_items import CadLayer
        layer = getattr(self, "gpu", None)
        if on and layer is None:
            layer = cad_gpu.create_layer(self)
            if layer is None:
                return False
            layer.paint_hook = self._paint_gpu_overlay
            layer.paint_bounds = self._gpu_overlay_bounds
            layer.texture_provider = self._gpu_texture
            layer.under_hook = self._paint_gpu_under
            layer.under_bounds = lambda: self._gpu_extra_bounds("_fill")
            layer.obstacles = self._gpu_obstacles
            layer.failed.connect(self._gpu_failed)
            self.gpu = layer
            layer.show()
            layer.raise_()
            for signal in (self.zoomChanged,):
                signal.connect(layer.request)
            self.horizontalScrollBar().valueChanged.connect(layer.request)
            self.verticalScrollBar().valueChanged.connect(layer.request)
            CadLayer.of(self.board).set_gpu(layer)
            if self.cad is not None:
                self.cad.overlay.attach_gpu(layer)
            self._gpu_mode_timer = QTimer(self)             # mode « pur CAD » reevalue apres les changements du board
            self._gpu_mode_timer.setSingleShot(True)
            self._gpu_mode_timer.setInterval(0)
            self._gpu_mode_timer.timeout.connect(self.refresh_gpu_mode)
            self.board.contentChanged.connect(self._gpu_mode_timer.start)
            self.board.pageChanged.connect(self._gpu_mode_timer.start)
            self.board.pageChanged.connect(layer.request)
            self.board.selectionChanged.connect(layer.request)    # halo et poignees
            self.refresh_gpu_mode()
            QTimer.singleShot(1500, lambda: self._check_gpu(layer, 5))
        elif not on and layer is not None:
            self.gpu = None
            layer.set_pure(False)
            for signal in (self.board.contentChanged, self.board.pageChanged):
                try:
                    signal.disconnect(self._gpu_mode_timer.start)
                except (TypeError, RuntimeError):
                    pass
            for signal in (self.board.pageChanged, self.board.selectionChanged):
                try:
                    signal.disconnect(layer.request)
                except (TypeError, RuntimeError):
                    pass
            CadLayer.of(self.board).set_gpu(None)
            if self.cad is not None:
                self.cad.overlay.attach_gpu(None)
            try:
                self.zoomChanged.disconnect(layer.request)
                self.horizontalScrollBar().valueChanged.disconnect(layer.request)
                self.verticalScrollBar().valueChanged.disconnect(layer.request)
            except (TypeError, RuntimeError):
                pass
            layer.release()
            layer.hide()
            layer.deleteLater()
            self.viewport().update()
        return getattr(self, "gpu", None) is not None or not on

    def _gpu_failed(self, message: str):
        """Contexte OpenGL 3.3 impossible (pilote, bureau a distance…) : les entites CAD reviennent au rendu par lots."""
        self.set_gpu(False)
        self.gpuFailed.emit(message)

    def _check_gpu(self, layer, tries: int):
        """Couche visible mais sans contexte OpenGL valide apres un moment : secours (sinon le CAD resterait invisible,
        la scene ne le peint plus)."""
        if getattr(self, "gpu", None) is not layer:
            return
        if layer.isVisible() and not layer.isValid():
            self._gpu_failed("contexte OpenGL indisponible")
        elif not layer.isVisible() and tries > 0:
            QTimer.singleShot(3000, lambda: self._check_gpu(layer, tries - 1))

    def refresh_gpu_mode(self):
        """Mode « pur CAD » (fond et grille sur le GPU, vue raster figee) tant que le board ne contient QUE des entites
        CAD et que la grille est en lignes ; sinon la couche reste translucide au-dessus de la vue raster."""
        layer = getattr(self, "gpu", None)
        if layer is None:
            return
        scene = self.board
        pure = (scene.grid_look["style"] == "lines"
                and all(getattr(item, "CAD", False) for item in scene._items.values()))
        layer.set_pure(pure)         # textes des cotes et remplissages des hachures : peints par QPainter (_paint_gpu_*)

    def _gpu_extras(self, kind: str):
        """Enfants a peindre par QPainter dans la couche GPU : `_fill` (remplissage plein d'une hachure, SOUS les traits) ou
        `_text_item` (texte d'une cote, PAR-DESSUS)."""
        for item in self.board._items.values():
            child = getattr(item, kind, None)
            if child is not None and item.isVisible() and child.isVisible() and getattr(child, "_solid", True):
                yield child

    def _gpu_extra_bounds(self, kind: str, children=None) -> QRect:
        out = QRect()
        for child in (self._gpu_extras(kind) if children is None else children):
            box = self.mapFromScene(child.sceneBoundingRect()).boundingRect().adjusted(-2, -2, 2, 2)
            out = box if out.isNull() else out.united(box)
        return out

    def _paint_gpu_under(self, painter, transform):
        painter.save()
        painter.setTransform(transform, True)
        for child in self._gpu_extras("_fill"):
            painter.save()
            painter.setTransform(child.sceneTransform(), True)
            child.paint(painter, None)
            painter.restore()
        painter.restore()

    def _paint_gpu_texts(self, painter, transform):
        painter.save()
        painter.setTransform(transform, True)
        texts = self._gpu_texts                     # releves UNE fois par image (`_gpu_overlay_bounds`)
        for child in (self._gpu_extras("_text_item") if texts is None else texts):
            painter.save()
            painter.setTransform(child.sceneTransform(), True)
            child.paint(painter, None)
            painter.restore()
        painter.restore()

    def _paint_gpu_overlay(self, painter, transform):
        """Dans la couche GPU (QPainter) : halo et poignees des entites selectionnees, puis le rendu temporaire du CAD
        (apercus, reticule peint, infobulles…)."""
        painter.save()
        painter.setTransform(transform, True)         # COMBINEE : le peintre est deja decale de la zone peinte (`_paint_qt`)
        for item in self.board.selectedItems():
            if getattr(item, "CAD", False) and item.isVisible():
                painter.save()
                painter.translate(item.pos())
                item.paint_selection(painter)
                painter.restore()
        painter.restore()
        if self.gpu is not None and self.gpu.pure:
            self._paint_gpu_texts(painter, transform)
        if self.gpu_badge is not None:
            paint_render_badge(painter, self.gpu_badge, True)
        if self.cad is not None and self.cad.active and self.cad.overlay.paint_into(painter):
            self.cad.painted_cursor_shown()

    def _gpu_overlay_bounds(self) -> list:
        """Zones (viewport) qui contiennent le dessin de `_paint_gpu_overlay` : halo et poignees des entites
        selectionnees, textes du mode pur, encart du rendu, rendu temporaire du CAD ; vide = rien a peindre. Gardees
        SEPAREES quand elles sont loin les unes des autres (fondues sinon, `CadOverlay._merge`) : leur rectangle
        englobant (le reticule au centre + l'encart en haut a droite = la moitie de la vue) etait efface, peint et
        envoye au GPU a CHAQUE image d'un pan (+3 ms de processeur par image, mesure)."""
        from fm_cad.cad_overlay import CadOverlay
        parts = []
        margin = int(getattr(self.board, "cad_grip_px", 8) or 8) + 10
        for item in self.board.selectedItems():
            if getattr(item, "CAD", False) and item.isVisible():
                parts.append(self.mapFromScene(item.sceneBoundingRect()).boundingRect()
                             .adjusted(-margin, -margin, margin, margin))
        if self.gpu_badge is not None:
            parts.append(self.gpu_badge.adjusted(-2, -2, 2, 2))
        self._gpu_texts = None
        if self.gpu is not None and self.gpu.pure:
            # Un seul parcours des elements par image (il etait refait pour chaque zone peinte).
            self._gpu_texts = list(self._gpu_extras("_text_item"))
            parts.append(self._gpu_extra_bounds("_text_item", self._gpu_texts))
        if self.cad is not None and self.cad.active:
            parts.append(self.cad.overlay.prepare())
        return CadOverlay._merge([r for r in parts if not r.isNull()])

    def _gpu_obstacles(self) -> list:
        """Zones (coordonnees du viewport) des panneaux flottants du board, widgets AU-DESSUS de la vue : la couche GPU
        les laisse libres (sinon elle les recouvrirait)."""
        viewport = self.viewport()
        pane = self.parentWidget()
        if pane is None:
            return []
        rects = []
        bounds = viewport.rect()
        for widget in pane.children():
            if (not isinstance(widget, QWidget) or widget is self or not widget.isVisible()
                    or type(widget).__name__ == "ShadowUnderlay"):
                continue
            top_left = viewport.mapFromGlobal(widget.mapToGlobal(QPoint(0, 0)))
            rect = QRect(top_left, widget.size()).intersected(bounds)
            if not rect.isEmpty():
                rects.append(rect)
        return rects

    @property
    def board(self) -> BoardScene:
        return self.scene()

    # -- zoom / deplacement --
    def zoom(self) -> float:
        return self._zoom

    def limits(self) -> tuple[float, float]:
        """Zoom minimal / maximal de la PAGE (reglages du .mro ; 10 % - 400 % par defaut)."""
        return model.zoom_limits(self.board.page)

    def set_zoom(self, zoom: float, anchor=None):
        low, high = self.limits()
        zoom = max(low, min(high, float(zoom)))
        if anchor is None:
            anchor = QPointF(self.viewport().rect().center())
        anchor = QPointF(anchor)
        # Point fixe calcule en flottants (mapToScene arrondit au pixel : a 0,1 % un pixel = 1 000 unites).
        fixed = self.viewportTransform().inverted()[0].map(anchor)
        was_cached = self._zoom <= CACHE_MAX_ZOOM
        self._zoom = zoom
        self._fit_scroll_area()
        self.setTransform(QTransform.fromScale(zoom, zoom))
        self.board.set_zoom(zoom)
        if not self.zooming():
            self.board.cad_tess_zoom = zoom         # finesse des courbes CAD : pas pendant un zoom continu
        moved = self.viewportTransform().map(fixed) - anchor
        self._scroll_by(moved.x(), moved.y())
        if was_cached != (zoom <= CACHE_MAX_ZOOM) and not getattr(self, "_zoom_timer", None):
            self._set_item_cache(True)
        self._note_visible()
        self.zoomChanged.emit(zoom)

    def _fit_scroll_area(self):
        """Zone de defilement de la VUE (pas de la scene : son index ne bouge pas) : assez grande pour
        circuler a 0,1 %, assez petite pour que les barres (entiers) ne debordent pas a 2 000 %."""
        size = max(self.viewport().width(), self.viewport().height(), 1000)
        half = min(1e9 / self._zoom, max(5e5, 4 * size / self._zoom))
        rect = QRectF(-half, -half, 2 * half, 2 * half)
        if self.sceneRect() != rect:
            self.setSceneRect(rect)

    def enforce_limits(self):
        """Limites de la page changees : zoom ramene dans la plage, autour du centre de la vue."""
        low, high = self.limits()
        if not (low <= self._zoom <= high):
            self.set_zoom(self._zoom)

    def zoom_by(self, factor: float, anchor=None):
        self._zoom_gesture()
        self.set_zoom(self._zoom * factor, anchor)

    def _zoom_gesture(self):
        """Pendant un zoom continu (molette, pincement) les elements sont peints directement : leur image a
        l'ecran (cache) serait refaite a CHAQUE cran, plus cher qu'une simple peinture (mesure, 500 elements :
        ~80 -> voir AGENTS.md). Le cache revient 250 ms apres le dernier cran (deplacements fluides)."""
        from PySide6.QtCore import QTimer
        timer = getattr(self, "_zoom_timer", None)
        if timer is None:
            timer = self._zoom_timer = QTimer(self)
            timer.setSingleShot(True)
            timer.setInterval(250)
            timer.timeout.connect(self._zoom_settled)
        if not timer.isActive():
            self._set_item_cache(False)
        timer.start()

    def _zoom_settled(self):
        self._set_item_cache(True)
        if getattr(self.board, "cad_tess_zoom", None) != self._zoom:
            self.board.cad_tess_zoom = self._zoom   # courbes CAD retessellees a la fin du geste (cad_items.tess_band)
            self.board.update()
        if self._cad_on():
            self.cad.overlay.invalidate()           # image du viewport relevee maintenant (pas pendant le geste)

    def zooming(self) -> bool:
        timer = getattr(self, "_zoom_timer", None)
        return timer is not None and timer.isActive()

    def _set_item_cache(self, on: bool):
        on = on and self._zoom <= CACHE_MAX_ZOOM
        mode = QGraphicsItem.DeviceCoordinateCache if on else QGraphicsItem.NoCache
        for item in self.board.board_items():
            if isinstance(item, CommentItem) or getattr(item, "NO_CACHE", False):
                continue
            item.setCacheMode(mode)
            if item.text_item is not None and not item.text_item.editing():
                item.text_item.setCacheMode(mode)

    def _scroll_by(self, dx: float, dy: float):
        """Defilement en pixels ; les barres ne prennent que des entiers : le reste est GARDE pour le pas
        suivant (sinon le zoom autour du curseur derivait d'un demi-pixel par cran)."""
        rx, ry = getattr(self, "_scroll_rest", (0.0, 0.0))
        dx, dy = dx + rx, dy + ry
        ix, iy = round(dx), round(dy)
        self._scroll_rest = (dx - ix, dy - iy)
        h, v = self.horizontalScrollBar(), self.verticalScrollBar()
        before = (h.value(), v.value())
        h.setValue(h.value() + ix)
        v.setValue(v.value() + iy)
        if self._pan is not None and self._pan_frame is not None:     # deplacement : image recopiee (_pan_paint)
            self._pan_shift[0] += h.value() - before[0]
            self._pan_shift[1] += v.value() - before[1]
        self._note_visible()

    def center_on(self, point: QPointF):
        self.centerOn(point)
        self._note_visible()

    def view_center(self) -> QPointF:
        return self.mapToScene(self.viewport().rect().center())

    def fit_all(self):
        rect = self.board.content_rect()
        if not rect.isValid() or rect.isNull():
            self.set_zoom(1.0)
            self.center_on(QPointF(0, 0))
            return
        rect = rect.adjusted(-60, -60, 60, 60)
        area = self.viewport().rect()
        zoom = min(area.width() / max(1.0, rect.width()), area.height() / max(1.0, rect.height()))
        self.set_zoom(min(1.0, zoom))                       # borne aux limites de la page par set_zoom
        self.center_on(rect.center())

    def _note_visible(self):
        self.board.visible_rect = self.mapToScene(self.viewport().rect()).boundingRect()

    def paintEvent(self, event):
        if self._pan is not None and self._pan_frame is not None and self._pan_paint():
            return
        super().paintEvent(event)
        if self._pan is not None:
            self._pan_frame = self._grab_painted(event.rect())     # 1re image du geste : peinture ordinaire relevee
        if self.cad is not None and self.cad.active:
            self.cad.overlay.capture(event.rect())     # image du viewport pour les mouvements (cad_overlay)

    # -- deplacement (pan) par recopie de l'image --
    # Signale : « le pan n'est pas super fluide ». Mesure (fenetre reelle 2400 x 1300, sonde _probe_cad_latency
    # « pan ») : chaque pas de souris repeignait TOUTE la scene (vue en FullViewportUpdate : 7 ms board vide, 27 ms
    # avec 150 post-it / formes, 35 ms avec 5 000 lignes CAD en plus), alors que seule une bande de quelques pixels
    # apparait. Pendant le geste, l'image de la scene est gardee a part (`_pan_frame`, pixels physiques, sans les
    # barres posees dessus) : chaque pas la decale EN PLACE (QPixmap.scroll) et ne dessine que les bandes qui
    # apparaissent au bord. Scene changee pendant le geste (image arrivee...) ou decalage non entier en pixels
    # physiques : image refaite en entier. Le geste fini, peinture ordinaire.
    def _pan_paint(self) -> bool:
        viewport = self.viewport()
        ratio = viewport.devicePixelRatioF() or 1.0
        rect = viewport.rect()
        if rect.isEmpty():
            return False
        size = QSize(math.ceil(rect.width() * ratio), math.ceil(rect.height() * ratio))
        dx, dy = self._pan_shift
        self._pan_shift = [0, 0]
        frame = self._pan_frame
        whole = (frame is None or frame.size() != size or abs(dx * ratio - round(dx * ratio)) > 1e-6
                 or abs(dy * ratio - round(dy * ratio)) > 1e-6)
        if whole:
            frame = QPixmap(size)
            frame.setDevicePixelRatio(ratio)
            painter = QPainter(frame)
            self._render_part(painter, rect)
        else:
            frame.scroll(-round(dx * ratio), -round(dy * ratio), frame.rect())     # en place (memmove)
            painter = QPainter(frame)
            exposed = QRegion(rect).subtracted(QRegion(rect.translated(-dx, -dy)))
            for part in exposed:
                self._render_part(painter, part)
        painter.end()
        self._pan_frame = frame
        out = QPainter(viewport)
        out.setCompositionMode(QPainter.CompositionMode_Source)
        out.drawPixmap(0, 0, frame)
        out.end()
        return True

    def _grab_painted(self, rect):
        """Image de la scene que le viewport vient de peindre EN ENTIER, relevee dans la memoire de la fenetre
        (~3 ms ; la refaire a part coutait jusqu'a ~110 ms au depart du geste) ; None si ce n'est pas sur
        (peinture partielle, overlay CAD opaque par-dessus, autre moteur de rendu)."""
        viewport = self.viewport()
        if rect != viewport.rect() or (self.cad is not None and self.cad.overlay.backdrop is not None):
            return None
        try:
            store = viewport.backingStore()
            device = store.paintDevice() if store is not None else None
        except (AttributeError, RuntimeError):
            return None
        if not isinstance(device, QImage) or device.isNull():
            return None
        ratio = device.devicePixelRatio() or 1.0
        if abs(ratio - (viewport.devicePixelRatioF() or 1.0)) > 1e-6:
            return None
        corner = viewport.mapTo(viewport.window(), rect.topLeft())
        area = QRectF(corner.x() * ratio, corner.y() * ratio, rect.width() * ratio, rect.height() * ratio).toRect()
        if not device.rect().contains(area):
            return None
        frame = QPixmap.fromImage(device.copy(area))
        frame.setDevicePixelRatio(ratio)
        return frame

    def _render_part(self, painter, rect):
        painter.save()
        painter.setClipRect(rect)
        painter.setRenderHints(self.renderHints())
        self.render(painter, QRectF(rect), rect, Qt.IgnoreAspectRatio)
        painter.restore()

    def _gpu_texture(self, rect):
        """Contenu raster du board (fond, grille, post-it, formes, textes… ; le CAD est peint par le GPU) de la zone `rect`
        de la vue (pixels logiques) : bande envoyee a la texture que la couche GPU decale pendant un deplacement."""
        ratio = self.viewport().devicePixelRatioF() or 1.0
        image = QImage(math.ceil(rect.width() * ratio), math.ceil(rect.height() * ratio), QImage.Format_RGB32)
        image.setDevicePixelRatio(ratio)
        painter = QPainter(image)
        painter.translate(-rect.x(), -rect.y())
        self._gpu_texturing = True
        try:
            self._render_part(painter, rect)
        finally:
            self._gpu_texturing = False
            painter.end()
        return image

    def _pan_started(self):
        self._pan_frame = None
        self._pan_shift = [0, 0]
        gpu = getattr(self, "gpu", None)
        if gpu is not None and gpu.texture_provider is not None:
            gpu.begin_texture()
        if not getattr(self, "_pan_watching", False):  # relachement jamais recu (fenetre quittee) : pas de doublon
            self.board.changed.connect(self._pan_scene_changed)
            self._pan_watching = True

    def _pan_finished(self):
        if getattr(self, "_pan_watching", False):
            self.board.changed.disconnect(self._pan_scene_changed)
            self._pan_watching = False
        self._pan_frame = None
        gpu = getattr(self, "gpu", None)
        if gpu is not None:
            gpu.end_texture()
        self.viewport().update()                        # peinture ordinaire (caches, image du CAD relevee)

    def _pan_scene_changed(self, _rects=None):
        self._pan_frame = None                          # contenu change : prochaine image refaite en entier
        gpu = getattr(self, "gpu", None)
        if gpu is not None and not getattr(self, "_gpu_texturing", False):
            gpu.stale_texture()
            gpu.request()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._note_visible()
        if self.cad is not None:
            self.cad.overlay.setGeometry(self.viewport().rect())
            self.cad.overlay.invalidate()

    def event(self, event):
        # Mode CAD : ses touches (Entree, F3, F7-F12, lettres de la barre de commande…) ne partent pas vers
        # les raccourcis de la fenetre principale.
        if event.type() == QEvent.ShortcutOverride and self._cad_on() and self.cad.claims(event):
            event.accept()
            return True
        if event.type() == QEvent.ShortcutOverride and self._design_on() and self.design.claims(event):
            event.accept()
            return True
        return super().event(event)

    def focusNextPrevChild(self, forward: bool) -> bool:
        if self._cad_on():
            return False                    # Tab : saisie dynamique / accrochage suivant (mode CAD)
        return super().focusNextPrevChild(forward)

    def leaveEvent(self, event):
        if self._cad_on():
            self.cad.leave()
        super().leaveEvent(event)

    def wheelEvent(self, event):
        """Molette = zoom autour du curseur (Reglages > Module MRO > Navigation : `zoom_step` par cran) ; Maj tenu =
        zoom FIN (`zoom_fine_step`, demande de l'utilisateur ; Maj + molette deplacait la vue a l'horizontale) ; pave
        tactile, deux doigts en travers = deplacement."""
        delta = event.angleDelta()
        if event.modifiers() & Qt.ShiftModifier:
            steps = (delta.y() or delta.x()) / 120.0        # Windows peut rendre la molette en x avec Maj
            if steps:
                self.zoom_by(self.zoom_fine_step ** steps, event.position())
            event.accept()
            return
        pixel = event.pixelDelta()
        if not (event.modifiers() & Qt.ControlModifier) and not pixel.isNull() and delta.y() == 0:
            self._scroll_by(-pixel.x(), -pixel.y())          # pave tactile, deux doigts en travers
            event.accept()
            return
        steps = delta.y() / 120.0
        if steps:
            self.zoom_by(self.zoom_step ** steps, event.position())
        event.accept()

    def viewportEvent(self, event):
        if event.type() == QEvent.NativeGesture and event.gestureType() == Qt.ZoomNativeGesture:
            self.zoom_by(1.0 + event.value(), event.position())
            return True
        if event.type() == QEvent.Gesture:
            pinch = event.gesture(Qt.PinchGesture)
            if pinch is not None:
                self.zoom_by(pinch.scaleFactor(), self.viewport().mapFromGlobal(pinch.centerPoint().toPoint()))
                return True
        return super().viewportEvent(event)

    # -- outils --
    def set_tool(self, tool: str):
        if tool == self.tool:
            return
        self._cancel_draft()
        self.tool = tool
        self.setDragMode(QGraphicsView.RubberBandDrag if tool == "select" else QGraphicsView.NoDrag)
        self._sync_cursor()
        self.toolChanged.emit(tool)

    def _sync_cursor(self):
        if self._cad_on():
            self.cad._sync_cursor()         # mode CAD : le reticule, meme pendant un deplacement (il suit le pointeur)
            return
        if self._design_on() and self._pan is None and not self._space and self.design.sync_cursor():
            return
        if self._pan is not None:
            self.viewport().setCursor(Qt.ClosedHandCursor)
        elif self._space or self.tool == "hand":
            self.viewport().setCursor(Qt.OpenHandCursor)
        elif self.tool == "select":
            self.viewport().unsetCursor()
        else:
            self.viewport().setCursor(Qt.CrossCursor)

    def _item_at(self, view_pos) -> BoardItem | None:
        for item in self.items(view_pos.toPoint() if hasattr(view_pos, "toPoint") else view_pos):
            while item is not None and not isinstance(item, BoardItem):
                item = item.parentItem()
            if isinstance(item, BoardItem) and self.board.item_active(item):   # grise / masque (module) : ignore
                return item
        return None

    def finish_text_edit(self, exclude=None):
        """Un clic ailleurs que sur le texte en cours d'edition le termine (une etape d'annulation) : la scene,
        elle, laissait le focus au texte et l'edition continuait (bug signale)."""
        focus = self.board.focusItem()
        if focus is not None and hasattr(focus, "editing") and focus.editing() and focus.owner is not exclude:
            focus.clearFocus()

    def editing_text(self) -> bool:
        focus = self.board.focusItem()
        return focus is not None and hasattr(focus, "editing") and focus.editing()

    def _preview(self, item, pen):
        item.setPen(pen)
        item.setZValue(1e9)
        self.board.addItem(item)
        return item

    def mousePressEvent(self, event):
        pos = event.position()
        scene_pos = self.mapToScene(pos.toPoint())
        self.board.commit_live()
        if event.button() == Qt.MiddleButton or (event.button() == Qt.LeftButton
                                                 and (self._space or self.tool == "hand")):
            self._pan = pos
            self._pan_started()
            self._sync_cursor()
            if self._cad_on():
                self.cad.note_pan()
            event.accept()
            return
        if self._cad_on() and self.cad.mouse_press(event):
            event.accept()
            return
        if self._design_on() and self.design.mouse_press(event):
            event.accept()
            return
        if event.button() == Qt.LeftButton and self.tool == "select":
            self.finish_text_edit(exclude=self._item_at(pos))
            selected = [i for i in self.board.selectedItems() if isinstance(i, BoardItem)]
            if len(selected) == 1 and selected[0].connection_dot_at(scene_pos):
                pen = QPen(QColor(self.board.accent), 2)
                pen.setCosmetic(True)
                preview = self._preview(QGraphicsLineItem(QLineF(scene_pos, scene_pos)), pen)
                self._draft = {"kind": "connector", "src": selected[0], "start": scene_pos, "preview": preview,
                               "back_to": "select"}
                event.accept()
                return
            target = self._item_at(pos)
            if event.modifiers() & Qt.ControlModifier and target is not None and target.data.get("link"):
                self.open_link(target.data["link"])
                event.accept()
                return
            self._press = (pos, target)
            super().mousePressEvent(event)
            return
        if event.button() != Qt.LeftButton:
            super().mousePressEvent(event)
            return
        if self.editing_text():
            self.board.focusItem().clearFocus()
        tool = self.tool
        if tool in ("sticky", "text"):
            data = model.new_item(tool)
            data["x"] = scene_pos.x() - (data["w"] / 2 if tool == "sticky" else 0)
            data["y"] = scene_pos.y() - (data["h"] / 2)
            item = self.board.add_new(data, "Ajouter un post-it" if tool == "sticky" else "Ajouter un texte")
            self.set_tool("select")
            item.start_edit()
        elif tool in ("shape", "frame"):
            pen = QPen(QColor(self.board.accent), 1.5)
            pen.setCosmetic(True)
            preview = self._preview(QGraphicsPathItem(), pen)
            self._draft = {"kind": tool, "start": scene_pos, "preview": preview}
            self._update_shape_draft(scene_pos)
        elif tool in ("pen", "highlighter", "smart"):
            style = self._ink_data(tool)
            preview = self._preview(QGraphicsPathItem(), ink_pen(style))
            self._draft = {"kind": "ink", "tool": tool, "points": [scene_pos], "preview": preview}
        elif tool == "eraser":
            self._draft = {"kind": "eraser", "hit": [], "last": pos}
            self._erase_at(pos)
        elif tool == "precision_eraser":
            self._draft = {"kind": "precision", "before": {}, "created": set(), "last": pos}
            self._precision_at(scene_pos)
        elif tool == "lasso":
            pen = QPen(QColor(self.board.accent), 1.2, Qt.DashLine)
            pen.setCosmetic(True)
            preview = self._preview(QGraphicsPathItem(), pen)
            self._draft = {"kind": "lasso", "points": [scene_pos], "preview": preview}
        elif tool == "connector":
            pen = QPen(QColor(self.board.accent), 2)
            pen.setCosmetic(True)
            preview = self._preview(QGraphicsLineItem(QLineF(scene_pos, scene_pos)), pen)
            source = self._item_at(pos)
            if isinstance(source, (ConnectorItem, CommentItem)):
                source = None
            self._draft = {"kind": "connector", "src": source, "start": scene_pos, "preview": preview}
        elif tool == "comment":
            target = self._item_at(pos)
            if isinstance(target, (ConnectorItem, CommentItem)):
                target = None
            data = model.new_item("comment", x=scene_pos.x(), y=scene_pos.y())
            if target is not None:
                r = target.scene_rect()
                data.update(target=target.item_id, dx=scene_pos.x() - r.left(), dy=scene_pos.y() - r.top())
            comment = self.board._add(data)                 # entre dans l'annulation a son 1er message
            self.set_tool("select")
            self.commentOpened.emit(comment, True)
        event.accept()

    def _ink_data(self, tool: str) -> dict:
        style = dict(self.ink_styles.get(tool) or self.ink_styles["pen"])
        data = {"tool": "highlighter" if tool == "highlighter" else "pen", "color": style.get("color", model.MIRO_INK),
                "width": float(style.get("width", 2.0)), "opacity": float(style.get("opacity", 1.0))}
        return data

    def mouseMoveEvent(self, event):
        pos = event.position()
        if self._pan is not None:
            delta = pos - self._pan
            self._pan = pos
            cad = self._cad_on()
            if cad:
                self.cad.cursor_view = QPointF(pos)     # relu par _view_changed pendant le defilement
            before = (self.horizontalScrollBar().value(), self.verticalScrollBar().value())
            self._scroll_by(-delta.x(), -delta.y())
            if cad:
                self.cad.pan_moved(pos, before != (self.horizontalScrollBar().value(),
                                                   self.verticalScrollBar().value()))
            event.accept()
            return
        if self._cad_on() and self.cad.mouse_move(event):
            event.accept()
            return
        if self._design_on() and self.design.mouse_move(event):
            event.accept()
            return
        draft = self._draft
        if draft is None:
            super().mouseMoveEvent(event)
            return
        scene_pos = self.mapToScene(pos.toPoint())
        kind = draft["kind"]
        if kind in ("shape", "frame"):
            self._update_shape_draft(scene_pos)
        elif kind in ("ink", "lasso"):
            points = draft["points"]
            if QLineF(points[-1], scene_pos).length() * self._zoom >= 2:
                points.append(scene_pos)
                if kind == "ink":
                    draft["preview"].setPath(ink_path([(p.x(), p.y()) for p in points]))
                else:
                    path = QPainterPath()
                    path.addPolygon(QPolygonF(points))
                    draft["preview"].setPath(path)
        elif kind in ("eraser", "precision"):
            # Toute la trajectoire depuis l'evenement precedent (un geste rapide ne saute aucun trait).
            last = draft.get("last", pos)
            steps = max(1, int(QLineF(last, pos).length() / 4))
            for n in range(1, steps + 1):
                point = last + (pos - last) * (n / steps)
                if kind == "eraser":
                    self._erase_at(point)
                else:
                    self._precision_at(self.mapToScene(point.toPoint()))
            draft["last"] = pos
        elif kind == "connector":
            draft["preview"].setLine(QLineF(draft["start"], scene_pos))
        event.accept()

    def mouseReleaseEvent(self, event):
        if self._pan is not None and event.button() in (Qt.MiddleButton, Qt.LeftButton):
            self._pan = None
            self._pan_finished()
            self._sync_cursor()
            if self._cad_on():
                self.cad._sync_cursor()
            event.accept()
            return
        if self._cad_on() and self.cad.mouse_release(event):
            event.accept()
            return
        if self._design_on() and self.design.mouse_release(event):
            event.accept()
            return
        draft, self._draft = self._draft, None
        if draft is None:
            press, self._press = self._press, None
            super().mouseReleaseEvent(event)
            if (press is not None and isinstance(press[1], CommentItem)
                    and QLineF(press[0], event.position()).length() < 4):
                self.commentOpened.emit(press[1], False)
            return
        scene_pos = self.mapToScene(event.position().toPoint())
        kind = draft["kind"]
        preview = draft.get("preview")
        if preview is not None:
            self.board.removeItem(preview)
        if kind in ("shape", "frame"):
            self._finish_shape(draft, scene_pos)
        elif kind == "ink":
            self._finish_ink(draft)
        elif kind == "eraser":
            hit = [i for i in draft["hit"] if i.scene() is self.board]
            for item in hit:
                item.setOpacity(self.board.item_opacity(item))
            self.board.delete_items(hit)
        elif kind == "precision":
            self._finish_precision(draft)
        elif kind == "lasso":
            self._finish_lasso(draft)
        elif kind == "connector":
            self._finish_connector(draft, event.position(), scene_pos)
        event.accept()

    def _frame_rect(self, start: QPointF, end: QPointF) -> QRectF:
        """Cadre tire : proportions du format choisi (hauteur tiree de la largeur)."""
        rect = QRectF(start, end).normalized()
        ratio = model.frame_ratio(self.frame_format)
        if ratio is None or rect.width() <= 0:
            return rect
        h = rect.width() / ratio
        top = start.y() if end.y() >= start.y() else start.y() - h
        return QRectF(rect.left(), top, rect.width(), h)

    def _finish_shape(self, draft, scene_pos):
        kind = draft["kind"]
        rect = (self._frame_rect(draft["start"], scene_pos) if kind == "frame"
                else QRectF(draft["start"], scene_pos).normalized())
        data = model.new_item("frame" if kind == "frame" else "shape")
        if kind == "frame":
            data.update(self.frame_format, ratio=list(self.frame_format.get("ratio", [16.0, 9.0])))
        if rect.width() * self._zoom < 8 and rect.height() * self._zoom < 8:   # simple clic : taille d'origine
            w, h = data["w"], data["h"]
            if kind == "frame":
                real = model.paper_size(data)
                ratio = model.frame_ratio(data)
                if real is not None:
                    w, h = real                                   # format papier : taille « reelle » (96 ppp)
                elif ratio is not None:
                    h = w / ratio
            rect = QRectF(0, 0, w, h)
            rect.moveCenter(draft["start"])
        data.update(x=rect.x(), y=rect.y(), w=max(24.0, rect.width()), h=max(24.0, rect.height()))
        if kind == "frame":
            frames = [i for i in self.board.board_items() if i.kind == "frame"]
            data["title"] = f"Cadre {len(frames) + 1}"
        else:
            data["shape"] = self.shape_kind
            if self.shape_kind == "round":
                data["radius"] = round(min(data["w"], data["h"]) * 0.18, 2)
        self.board.add_new(data, "Ajouter un cadre" if kind == "frame" else "Ajouter une forme")
        self.set_tool("select")

    def _finish_ink(self, draft):
        points = draft["points"]
        style = self._ink_data(draft["tool"])
        if draft["tool"] == "smart":
            found = smart.recognize(points)
            if found is not None:
                self._add_recognized(found, style)
                return
        base = smart.bounds(points).topLeft()
        data = model.new_item("ink", **style,
                              points=[[round(p.x() - base.x(), 2), round(p.y() - base.y(), 2)] for p in points],
                              x=base.x(), y=base.y())
        if style["tool"] == "highlighter":
            data["z"] = 0
        self.board.add_new(data, "Surligner" if style["tool"] == "highlighter" else "Dessiner", select=False)

    def _add_recognized(self, found, style):
        if found[0] == "line":
            _kind, a, b = found
            data = model.new_item("connector", src={"x": a.x(), "y": a.y()}, dst={"x": b.x(), "y": b.y()},
                                  arrow_end=False, end_cap="none", color=style["color"], width=style["width"])
            self.board.add_new(data, "Dessin intelligent : ligne", select=False)
            return
        kind, rect = found
        data = model.new_item("shape", shape=kind, x=rect.x(), y=rect.y(), w=max(24.0, rect.width()),
                              h=max(24.0, rect.height()), stroke=style["color"], stroke_width=style["width"])
        self.board.add_new(data, "Dessin intelligent : forme", select=False)

    def _finish_lasso(self, draft):
        points = draft["points"]
        if len(points) < 3:
            return
        path = QPainterPath()
        path.addPolygon(QPolygonF(points))
        path.closeSubpath()
        self.board.clearSelection()
        for item in self.board.board_items():
            if item.isVisible() and path.contains(item.scene_rect().center()):
                item.setSelected(True)

    def _finish_connector(self, draft, view_pos, scene_pos):
        target = self._item_at(view_pos)
        if isinstance(target, (ConnectorItem, CommentItem)):
            target = None
        source = draft["src"]
        if QLineF(draft["start"], scene_pos).length() * self._zoom >= 6 and not (
                source is not None and target is source):
            data = model.new_item(
                "connector",
                src={"item": source.item_id} if source else {"x": draft["start"].x(), "y": draft["start"].y()},
                dst={"item": target.item_id} if target else {"x": scene_pos.x(), "y": scene_pos.y()})
            self.board.add_new(data, "Ajouter un connecteur")
            self.set_tool("select")

    def _update_shape_draft(self, scene_pos):
        draft = self._draft
        rect = QRectF(draft["start"], scene_pos).normalized()
        path = QPainterPath()
        if draft["kind"] == "frame":
            path.addRect(self._frame_rect(draft["start"], scene_pos))
        else:
            path = shape_path(self.shape_kind, rect, min(rect.width(), rect.height()) * 0.18
                              if self.shape_kind == "round" else 0.0)
        draft["preview"].setPath(path)

    def _erase_at(self, view_pos):
        """Gomme : un trait (stylo, surligneur) touche disparait en entier (au relachement, une etape)."""
        radius = 6
        rect = QRectF(view_pos.x() - radius, view_pos.y() - radius, 2 * radius, 2 * radius).toRect()
        for item in self.items(rect):
            if (isinstance(item, InkItem) and not item.locked() and item.isEnabled()
                    and item not in self._draft["hit"]):
                self._draft["hit"].append(item)
                item.setOpacity(0.25)

    def _precision_at(self, scene_pos):
        """Gomme de precision : coupe les traits sous le cercle (diametre `ERASER_SIZES`, pixels d'ecran)."""
        draft = self._draft
        radius = ERASER_SIZES.get(self.eraser_size, 18) / 2 / self._zoom
        area = QRectF(scene_pos.x() - radius, scene_pos.y() - radius, 2 * radius, 2 * radius)
        for item in self.board.items(area):
            if not isinstance(item, InkItem) or item.locked():
                continue
            origin = item.pos()
            points = [QPointF(origin.x() + float(x), origin.y() + float(y)) for x, y in item.data.get("points", [])]
            pieces = smart.cut(points, scene_pos, radius, max(1.0, float(item.data.get("width", 2.0)) / 2))
            if pieces is None:
                continue
            if item.item_id not in draft["created"]:
                draft["before"][item.item_id] = item.to_dict()
            draft["created"].discard(item.item_id)
            base = item.to_dict()
            self.board._remove(item.item_id)
            for piece in pieces:
                rect = smart.bounds(piece)
                data = dict(base, id=model.new_id(), x=rect.x(), y=rect.y(),
                            points=[[round(p.x() - rect.x(), 2), round(p.y() - rect.y(), 2)] for p in piece])
                self.board._add(data)
                draft["created"].add(data["id"])

    def _finish_precision(self, draft):
        if not draft["before"]:
            return
        before = dict(draft["before"])
        before.update({i: None for i in draft["created"]})
        after = {i: None for i in draft["before"]}
        after.update(self.board.snapshot([i for i in draft["created"] if self.board.item(i) is not None]))
        self.board.push(before, after, "Gomme de précision")

    def _cancel_draft(self):
        draft, self._draft = self._draft, None
        if draft is None:
            return
        if draft.get("preview") is not None:
            self.board.removeItem(draft["preview"])
        for item in draft.get("hit", []):
            item.setOpacity(self.board.item_opacity(item))
        if draft.get("kind") == "precision":
            self._finish_precision(draft)

    @staticmethod
    def open_link(link: str):
        url = QUrl.fromUserInput(link, "", QUrl.AssumeLocalFile)
        QDesktopServices.openUrl(url)

    # -- clavier --
    def _refresh_gesture(self, event):
        """Maj enfoncee / relachee pendant un redimensionnement : le geste est rejoue aussitot."""
        grabber = self.board.mouseGrabberItem()
        if event.key() == Qt.Key_Shift and isinstance(grabber, BoardItem):
            grabber.refresh_gesture(event.modifiers())

    def mouseDoubleClickEvent(self, event):
        if self._cad_on() and self.cad.mouse_double_click(event):
            event.accept()
            return
        if self._design_on() and self.design.mouse_double_click(event):
            event.accept()
            return
        super().mouseDoubleClickEvent(event)

    def keyPressEvent(self, event):
        self._refresh_gesture(event)
        if self.editing_text():
            super().keyPressEvent(event)
            return
        if self._cad_on() and self.cad.key_press(event):
            event.accept()
            return
        if self._design_on() and self.design.key_press(event):
            event.accept()
            return
        key, mods = event.key(), event.modifiers()
        board = self.board
        selected = [i for i in board.selectedItems() if isinstance(i, BoardItem)]
        if key == Qt.Key_Space and not event.isAutoRepeat():
            self._space = True
            self._sync_cursor()
        elif key in (Qt.Key_Delete, Qt.Key_Backspace):
            board.delete_items(selected)
        elif event.matches(QKeySequence.Undo):
            board.undo.undo()
        elif event.matches(QKeySequence.Redo) or (mods & Qt.ControlModifier and key == Qt.Key_Y):
            board.undo.redo()
        elif event.matches(QKeySequence.Copy):
            self.copy_selection()
        elif event.matches(QKeySequence.Cut):
            self.copy_selection()
            board.delete_items(selected)
        elif event.matches(QKeySequence.Paste):
            self.paste()
        elif event.matches(QKeySequence.SelectAll):
            for item in board.board_items():
                if item.isVisible():
                    item.setSelected(True)
        elif mods & Qt.ControlModifier and mods & Qt.ShiftModifier and key == Qt.Key_L:
            self.toggle_lock(selected)
        elif mods & Qt.ControlModifier and key == Qt.Key_D:
            self.duplicate(selected)
        elif mods & Qt.ControlModifier and key == Qt.Key_0:
            self.set_zoom(1.0)
        elif key == Qt.Key_Exclam or (mods & Qt.ShiftModifier and key == Qt.Key_1):
            self.fit_all()
        elif key in (Qt.Key_Plus, Qt.Key_Equal):
            self.zoom_by(1.25)
        elif key in (Qt.Key_Minus, Qt.Key_Underscore):
            self.zoom_by(1 / 1.25)
        elif key in (Qt.Key_Return, Qt.Key_Enter) and len(selected) == 1 and selected[0].text_item is not None:
            selected[0].start_edit()
        elif key == Qt.Key_Escape:
            if self._draft is not None:
                self._cancel_draft()
            elif selected:
                board.clearSelection()
            elif self.tool != "select":
                self.set_tool("select")
            else:
                event.ignore()                              # le panneau ferme le board
                return
        elif not mods and key in (Qt.Key_R, Qt.Key_O):
            self.shape_kind = "rect" if key == Qt.Key_R else "ellipse"
            self.set_tool("select")
            self.set_tool("shape")
        elif not mods and key in TOOL_KEYS:
            self.set_tool(TOOL_KEYS[key])
        elif (not mods & (Qt.ControlModifier | Qt.AltModifier) and selected
              and key in (Qt.Key_Left, Qt.Key_Right, Qt.Key_Up, Qt.Key_Down)):
            step = 1 if mods & Qt.ShiftModifier else 10
            dx = {Qt.Key_Left: -step, Qt.Key_Right: step}.get(key, 0)
            dy = {Qt.Key_Up: -step, Qt.Key_Down: step}.get(key, 0)
            movable = [i for i in selected if i.flags() & QGraphicsItem.ItemIsMovable]
            before = board.snapshot([i.item_id for i in movable])
            for item in movable:
                item.moveBy(dx, dy)
            board.push(before, board.snapshot(list(before)), "Deplacer")
        else:
            super().keyPressEvent(event)
            return
        event.accept()

    def keyReleaseEvent(self, event):
        if self._cad_on() and self.cad.key_release(event):
            event.accept()
            return
        if self._design_on() and self.design.key_release(event):
            event.accept()
            return
        self._refresh_gesture(event)
        if event.key() == Qt.Key_Space and not event.isAutoRepeat() and self._space:
            self._space = False
            self._sync_cursor()
        super().keyReleaseEvent(event)

    # -- commandes de la selection --
    def duplicate(self, items):
        items = [i for i in items if isinstance(i, BoardItem)]
        if items:
            self.board.paste(self.board.serialize(items), QPointF(30, 30), "Dupliquer")

    def toggle_lock(self, items):
        items = [i for i in items if isinstance(i, BoardItem)]
        if not items:
            return
        lock = not all(i.locked() for i in items)
        self.board.change_items(items, lambda i: i.data.update(locked=lock),
                                "Verrouiller" if lock else "Déverrouiller", include_locked=True)

    # -- presse-papiers / depot --
    def copy_selection(self):
        """Copie : format interne (entre boards, objets complets) + texte brut et tableau HTML (une cellule
        par objet a texte) pour les autres logiciels — Miro en fait des post-it modifiables (voir clipboard)."""
        from . import clipboard
        items = [i for i in self.board.selectedItems() if isinstance(i, BoardItem)]
        if not items:
            return
        mime = QMimeData()
        mime.setData(CLIPBOARD_MIME, QByteArray(self.board.clipboard_payload(self.board.serialize(items))))
        texts = clipboard.items_text(items)
        if texts:
            mime.setText("\n".join(t.replace("\n", " ") for t in texts))
            mime.setHtml(clipboard.table_html(texts))
        QApplication.clipboard().setMimeData(mime)

    def copy_selection_image(self):
        """Copier en image (PNG) : un RENDU APLATI de la selection (non modifiable ailleurs)."""
        from . import export
        items = [i for i in self.board.selectedItems() if isinstance(i, BoardItem)]
        if items:
            QApplication.clipboard().setImage(export.render_items(self.board, items))

    def _paste_point(self) -> QPointF:
        local = self.viewport().mapFromGlobal(self.cursor().pos())
        if self.viewport().rect().contains(local):
            return self.mapToScene(local)
        return self.view_center()

    def paste(self):
        mime = QApplication.clipboard().mimeData()
        at = self._paste_point()
        if mime.hasFormat(CLIPBOARD_MIME):
            dicts, source = self.board.read_payload(mime.data(CLIPBOARD_MIME).data())
            if dicts:
                origin = QRectF()
                for d in dicts:
                    if d.get("type") != "connector":
                        origin = origin.united(QRectF(d.get("x", 0.0), d.get("y", 0.0),
                                                      d.get("w", 1.0) or 1.0, d.get("h", 1.0) or 1.0))
                self.board.paste(dicts, at - origin.center() if origin.isValid() else QPointF(30, 30),
                                 source_board=Path(source) if source else None)
            return
        if mime.hasHtml() and self._paste_html(mime.html(), at):
            return
        if mime.hasUrls() and self.add_image_files([Path(u.toLocalFile()) for u in mime.urls()], at):
            return
        if mime.hasImage() and self.board.board_path is not None:      # dessin DXF importe : pas de dossier
            image = QImage(mime.imageData())
            if not image.isNull():
                buffer = QBuffer()
                buffer.open(QIODevice.WriteOnly)
                image.save(buffer, "PNG")
                self._add_image(serialization.import_image_bytes(self.board.board_path, bytes(buffer.data())),
                                image.width(), image.height(), at)
                return
        if mime.hasText() and mime.text().strip():
            data = model.new_item("text", text=mime.text().strip(), x=at.x(), y=at.y())
            self.board.add_new(data, "Coller du texte")

    def _paste_html(self, markup: str, at: QPointF) -> bool:
        """Tableau (Excel, Miro...) ou objets copies dans Miro : un post-it par cellule / objet (le texte seul :
        le format interne de Miro n'est pas documente). Autre HTML : False (texte brut ou image ensuite)."""
        from . import clipboard
        kind, texts = clipboard.html_texts(markup)
        if kind not in ("table", "miro") or not texts:
            return False
        columns = max(1, min(6, round(len(texts) ** 0.5)))
        dicts = []
        for n, text in enumerate(texts[:500]):
            data = model.new_item("sticky", text=text)
            data["x"] = (n % columns) * (data["w"] + 20)
            data["y"] = (n // columns) * (data["h"] + 20)
            dicts.append(data)
        rows = (len(dicts) + columns - 1) // columns
        width, height = columns * 220 - 20, rows * 220 - 20
        self.board.paste(dicts, at - QPointF(width / 2, height / 2),
                         "Coller depuis Miro" if kind == "miro" else "Coller un tableau")
        return True

    def add_image_files(self, paths, at: QPointF) -> bool:
        added = False
        if self.board.board_path is None:                  # dessin DXF / DWG pas encore enregistre en .mro
            return False
        for i, path in enumerate(p for p in paths if p.suffix.lower() in IMAGE_SUFFIXES and p.is_file()):
            size = QImageReader(str(path)).size()
            if not size.isValid():
                continue
            name = serialization.import_asset(self.board.board_path, path)
            self._add_image(name, size.width(), size.height(), at + QPointF(40 * i, 40 * i))
            added = True
        return added

    def _add_image(self, name: str, width: int, height: int, at: QPointF):
        side = 600.0
        scale = min(1.0, side / max(1, width, height))
        w, h = max(24.0, width * scale), max(24.0, height * scale)
        data = model.new_item("image", asset=name, w=w, h=h, x=at.x() - w / 2, y=at.y() - h / 2)
        self.board.add_new(data, "Ajouter une image")

    def dragEnterEvent(self, event):
        if event.mimeData().hasUrls() or event.mimeData().hasImage():
            event.acceptProposedAction()
        else:
            super().dragEnterEvent(event)

    def dragMoveEvent(self, event):
        if event.mimeData().hasUrls() or event.mimeData().hasImage():
            event.acceptProposedAction()
        else:
            super().dragMoveEvent(event)

    def dropEvent(self, event):
        mime = event.mimeData()
        at = self.mapToScene(event.position().toPoint())
        if mime.hasUrls() and self._design_on() and self.design.drop_files(
                [Path(u.toLocalFile()) for u in mime.urls() if u.isLocalFile()], at):
            event.acceptProposedAction()
            return
        if mime.hasUrls() and self.add_image_files([Path(u.toLocalFile()) for u in mime.urls()], at):
            event.acceptProposedAction()
            return
        super().dropEvent(event)
