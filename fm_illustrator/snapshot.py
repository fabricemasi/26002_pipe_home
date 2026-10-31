"""Image de la vue pendant un ZOOM CONTINU (molette, pincement), quand beaucoup de tracés sont visibles.

Le board peint ses éléments sans image gardée pendant un zoom continu (`BoardView._zoom_gesture`) : avec ~1 300
tracés visibles, chaque cran les repeignait tous (mesure en vraie fenêtre : ~104 ms par cran). Au premier cran,
l'image DÉJÀ AFFICHÉE est relevée dans la mémoire de la fenêtre (`BoardView._grab_painted`, ~3 ms) avec la zone de la
scène qu'elle montrait (notée à chaque peinture par l'overlay) ; elle est reposée à la nouvelle échelle pendant le
geste, et les objets du module qu'elle contient ENTIÈREMENT ne se peignent pas (`IllItem.paint`). Rendue nette
300 ms après le dernier cran. Comme les pages du module Design (`DesignPageItem.snapshot`)."""
from __future__ import annotations

from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import QPainter
from PySide6.QtWidgets import QGraphicsItem

SNAPSHOT_MIN = 300                      # objets du module dans la vue à partir desquels l'image est prise
SNAPSHOT_Z = 5e6                        # au-dessus des objets (bandes de calques), sous commentaires et overlay


class ZoomSnapshot(QGraphicsItem):
    def __init__(self, frame, rect: QRectF):
        super().__init__()
        self.frame = frame
        self.rect = QRectF(rect)
        self.setZValue(SNAPSHOT_Z)
        self.setAcceptedMouseButtons(Qt.NoButton)
        self.setAcceptHoverEvents(False)

    def boundingRect(self) -> QRectF:
        return self.rect

    def paint(self, painter: QPainter, option, widget=None):
        painter.setRenderHint(QPainter.SmoothPixmapTransform, True)
        painter.drawPixmap(self.rect, self.frame, QRectF(self.frame.rect()))


def take(ctl) -> bool:
    """Prend l'image (premier cran d'un zoom continu) si assez d'objets sont visibles ; vrai si prise."""
    from .items import IllItem
    view = ctl.view
    rect = getattr(ctl, "_painted_rect", None)
    if rect is None or not hasattr(view, "_grab_painted"):
        return False
    inside = [i for i in ctl.scene.items(rect, Qt.ContainsItemBoundingRect)
              if isinstance(i, IllItem) and i.isVisible()]
    if len(inside) < SNAPSHOT_MIN:
        return False
    frame = view._grab_painted(view.viewport().rect())
    if frame is None:
        return False
    snap = ZoomSnapshot(frame, rect)
    ctl.scene.addItem(snap)
    ctl.zoom_snapshot = snap
    IllItem.snapshot_ids = {i.item_id for i in inside}
    return True


def drop(ctl):
    from .items import IllItem
    snap, ctl.zoom_snapshot = getattr(ctl, "zoom_snapshot", None), None
    IllItem.snapshot_ids = None
    if snap is not None and snap.scene() is not None:
        snap.scene().removeItem(snap)
        ctl.scene.update()


# ---------------------------------------------------------------- Ctrl + glisser de nombreux objets
DRAG_MIN_MOVING = 50                    # objets déplacés…
DRAG_MIN_VISIBLE = 300                  # …ou objets visibles, à partir desquels le geste passe par deux images


class DragSnapshot(QGraphicsItem):
    """Ctrl + glisser : FOND (la vue sans les objets déplacés, capté une fois) et CALQUE (les objets déplacés, peints
    une fois), posés à chaque mouvement, le calque décalé. Mesure en vraie fenêtre (200 objets parmi ~1 300 visibles) :
    voir docs/agents/fm_illustrator.md. Les objets restent à jour (`setPos`) : sélection et fin du geste justes."""

    def __init__(self, background, layer, rect: QRectF):
        super().__init__()
        self.background = background
        self.layer = layer
        self.rect = QRectF(rect)
        self.offset = (0.0, 0.0)
        self.setZValue(SNAPSHOT_Z)
        self.setAcceptedMouseButtons(Qt.NoButton)

    def boundingRect(self) -> QRectF:
        return self.rect

    def paint(self, painter: QPainter, option, widget=None):
        source = QRectF(self.background.rect())
        painter.drawPixmap(self.rect, self.background, source)
        painter.drawPixmap(self.rect.translated(*self.offset), self.layer, source)


def drag_start(ctl, items):
    """Images du geste, ou None (peu d'objets : le geste ordinaire suffit)."""
    from PySide6.QtGui import QImage, QPixmap, QTransform
    from .items import IllItem
    view = ctl.view
    viewport = view.viewport()
    rect = view.mapToScene(viewport.rect()).boundingRect()
    inside = [i for i in ctl.scene.items(rect, Qt.ContainsItemBoundingRect)
              if isinstance(i, IllItem) and i.isVisible()]
    if len(items) < DRAG_MIN_MOVING and len(inside) < DRAG_MIN_VISIBLE:
        return None
    moving = {i.item_id for i in items}
    IllItem.snapshot_ids = moving                       # le fond, sans les objets déplacés ni la sélection
    ctl.overlay.setVisible(False)
    try:
        background = viewport.grab()
    finally:
        IllItem.snapshot_ids = None
        ctl.overlay.setVisible(True)
    ratio = background.devicePixelRatio() or 1.0
    layer = QImage(background.width(), background.height(), QImage.Format_ARGB32_Premultiplied)
    layer.fill(Qt.transparent)
    p = QPainter(layer)
    p.setRenderHint(QPainter.Antialiasing, True)
    base = view.viewportTransform() * QTransform.fromScale(ratio, ratio)
    for item in sorted(items, key=lambda i: i.zValue()):
        p.save()
        p.setTransform(item.sceneTransform() * base)
        p.setOpacity(item.opacity())
        item.paint_content(p)
        p.restore()
    p.end()
    layer_pixmap = QPixmap.fromImage(layer)
    layer_pixmap.setDevicePixelRatio(ratio)
    snap = DragSnapshot(background, layer_pixmap, rect)
    ctl.scene.addItem(snap)
    IllItem.snapshot_ids = moving | {i.item_id for i in inside}
    # Les objets ont une image gardée : Qt la reposerait SOUS l'image du geste à chaque mouvement (sans passer par
    # leur peinture) ; opacité nulle le temps du geste (Qt les saute ; les masquer jetait leur image gardée : ~140 ms
    # pour les refaire au relâché). Les objets déplacés ne bougent qu'au relâché (`MoveGesture`).
    snap.hidden = [(i, i.opacity()) for i in set(inside) | set(items)]
    for item, _opacity in snap.hidden:
        item.setOpacity(0.0)
    ctl.dragging_frame = True
    return snap


def drag_end(ctl, snap):
    from .items import IllItem
    IllItem.snapshot_ids = None
    ctl.dragging_frame = False
    for item, opacity in getattr(snap, "hidden", ()):
        if item.scene() is not None:
            item.setOpacity(opacity)
    if snap is not None and snap.scene() is not None:
        snap.scene().removeItem(snap)
        ctl.scene.update(snap.rect)
