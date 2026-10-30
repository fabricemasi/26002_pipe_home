"""Élément « sheet » du Board (Qt) : un classeur posé sur le canvas.

- Hors édition : APERÇU peint par `render.paint_cells` (le code de la grille) à partir de la position de navigation
  de la session (le Board montre l'endroit où l'on travaillait), graphiques compris ; gardé en image par le Board.
- Double-clic : ÉDITION SUR PLACE — un classeur complet (`widget.SpreadsheetWidget`, ruban compact) est posé dans
  l'élément (`QGraphicsProxyWidget`) ; la vue du Board lui laisse souris et clavier (`EMBEDDED`, `editing()`).
  Échap (sans saisie en cours) ou clic ailleurs : fin de l'édition.
- Bouton « ⤢ » de la barre de titre (ou du ruban) : MODE STANDARD plein cadre (`standard.StandardPane`) sur la MÊME
  session : document, annulation, feuille, sélection, défilement gardés, rien n'est rechargé ni recalculé.
- Déplacer l'élément : Ctrl + glisser (règle de l'appli) ; sans Ctrl, un clic le choisit seulement.
- Le classeur vit dans une `session.Session` (clé : jeton de la scène + identifiant de l'élément) ; `to_dict` y lit
  le dictionnaire natif GARDÉ tant que le classeur ne change pas. Une saisie n'est PAS une étape d'annulation du
  Board (pile du classeur) ; elle déclenche l'enregistrement automatique du Board (`contentChanged`)."""
from __future__ import annotations

import copy
import uuid
import weakref

from PySide6.QtCore import QPointF, QRectF, Qt, QTimer
from PySide6.QtGui import QColor, QFont, QPainter, QPen
from PySide6.QtWidgets import QApplication, QGraphicsItem, QGraphicsProxyWidget

from fm_miro.items import ITEM_CLASSES, BoardItem
from . import board_model as bm
from . import render, session as S

TITLE_H = 26.0
HEADER_H = 20.0
HEADER_W = 36.0


def _scene_token(scene) -> str:
    token = getattr(scene, "_tableur_token", None)
    if token is None:
        token = scene._tableur_token = uuid.uuid4().hex
        weakref.finalize(scene, _forget_scene, token)
    return token


def _forget_scene(token):
    for key in [k for k in list(S._REGISTRY) if isinstance(k, tuple) and k[0] == token]:
        S.forget(key)


class _Embedded(QGraphicsProxyWidget):
    """Classeur posé dans l'élément pendant l'édition : la vue du Board lui laisse souris et clavier."""
    EMBEDDED = True

    def __init__(self, owner):
        super().__init__(owner)
        self.owner = owner

    def editing(self) -> bool:
        return True

    def focusOutEvent(self, event):
        super().focusOutEvent(event)


class SheetItem(BoardItem):
    MODULE = "tableur"
    CONNECTABLE = True
    RESIZABLE = True

    def __init__(self, data: dict):
        self._session = None
        self._proxy = None
        self._widget = None
        self._listener = None
        super().__init__(data)

    # -- session --
    @property
    def session(self):
        if self._session is None:
            scene = self.scene()
            key = (_scene_token(scene), self.item_id) if scene is not None else ("libre", self.item_id)
            self._session = S.obtain(key, self.data.get("workbook"))
            ref = weakref.ref(self)

            def listener(kind, _sheet, ref=ref):
                item = ref()
                if item is not None:
                    item._book_changed(kind)
            self._listener = listener
            self._session.book.listeners.append(listener)
        return self._session

    def added_to_scene(self, scene):
        self._session = None                 # clé liée à la scène
        _ = self.session

    def removing_from_scene(self, scene):
        self.stop_edit()
        if self._session is not None and self._listener in self._session.book.listeners:
            self._session.book.listeners.remove(self._listener)

    def _book_changed(self, kind):
        try:
            self.update()
            scene = self.scene()
        except RuntimeError:                 # élément déjà détruit
            return
        if scene is not None and kind not in ("selection",):
            scene.contentChanged.emit()

    # -- état --
    def to_dict(self) -> dict:
        data = {k: copy.deepcopy(v) for k, v in self.data.items() if k != "workbook"}
        data["x"], data["y"] = round(self.pos().x(), 2), round(self.pos().y(), 2)
        data["z"] = self.zValue()
        data["workbook"] = self.session.snapshot()
        return data

    def apply(self, data: dict):
        """État du Board (annuler un déplacement…) : le classeur EN COURS est gardé, seul le cadre change."""
        keep = self.data.get("workbook")
        data = dict(data)
        if self._session is not None:
            data["workbook"] = keep
        super().apply(data)

    def sync(self):
        if self._proxy is not None:
            w, h = self.size()
            self._proxy.setPos(0, TITLE_H)
            self._widget.resize(int(w), int(max(40.0, h - TITLE_H)))

    # -- peinture --
    def paint(self, painter: QPainter, option, widget=None):
        w, h = self.size()
        rect = QRectF(0, 0, w, h)
        painter.save()
        painter.setRenderHint(QPainter.Antialiasing, False)
        painter.fillRect(rect, QColor("#ffffff"))
        painter.fillRect(QRectF(0, 0, w, TITLE_H), QColor("#107c41"))
        font = QFont("Segoe UI")
        font.setPixelSize(12)
        font.setBold(True)
        painter.setFont(font)
        painter.setPen(QColor("#ffffff"))
        session = self.session
        title = f"{self.data.get('title') or 'Classeur'} — {session.sheet.name}"
        painter.drawText(QRectF(8, 0, w - 70, TITLE_H), Qt.AlignVCenter | Qt.AlignLeft, title)
        painter.drawText(self._standard_rect(), Qt.AlignCenter, "⤢")
        if self._proxy is None:
            self._paint_preview(painter, QRectF(0, TITLE_H, w, h - TITLE_H))
        painter.setPen(QPen(QColor("#107c41") if self.isSelected() else QColor("#b8b8b8"), 1))
        painter.setBrush(Qt.NoBrush)
        painter.drawRect(rect.adjusted(0.5, 0.5, -0.5, -0.5))
        painter.restore()
        if self.isSelected() and self._proxy is None:
            self.paint_selection(painter)

    def _standard_rect(self) -> QRectF:
        w, _h = self.size()
        return QRectF(w - 30, 0, 28, TITLE_H)

    def _paint_preview(self, painter, area: QRectF):
        session = self.session
        sheet = session.sheet
        book = session.book
        view = session.view(sheet)
        z = 1.0
        fr, fc = sheet.freeze
        sx, sy = view.scroll
        first_row = sheet.rows.index_at(sy + sheet.rows.pos(fr)) if sy else fr
        first_col = sheet.cols.index_at(sx + sheet.cols.pos(fc)) if sx else fc
        top = area.top() + HEADER_H
        left = area.left() + HEADER_W
        rows_top = render.visible_span(sheet.rows, 0, top, top + sheet.rows.pos(fr), z, stop=fr)
        y_main = top + sheet.rows.pos(fr)
        cols_left = render.visible_span(sheet.cols, 0, left, left + sheet.cols.pos(fc), z, stop=fc)
        x_main = left + sheet.cols.pos(fc)
        rows = render.Span(rows_top.items + render.visible_span(sheet.rows, first_row, y_main, area.bottom(),
                                                                z).items)
        cols = render.Span(cols_left.items + render.visible_span(sheet.cols, first_col, x_main, area.right(),
                                                                 z).items)
        cache = getattr(self, "_cache", None)
        if cache is None or cache.book is not book:
            cache = self._cache = render.DisplayCache(book)
        body = QRectF(left, top, area.right() - left, area.bottom() - top)
        board = self._board_pane()
        look = render.look_from(getattr(board, "_settings", None))
        render.paint_cells(painter, book, sheet, rows, cols, z, cache, look, clip=body)
        # entêtes
        painter.fillRect(QRectF(area.left(), area.top(), area.width(), HEADER_H), QColor(look["header_bg"]))
        painter.fillRect(QRectF(area.left(), area.top(), HEADER_W, area.height()), QColor(look["header_bg"]))
        font = QFont("Segoe UI")
        font.setPixelSize(11)
        painter.setFont(font)
        from . import refs as R
        painter.setClipRect(QRectF(left, area.top(), area.right() - left, HEADER_H))
        for c, x, cw in cols.items:
            painter.setPen(QColor(look["header_line"]))
            painter.drawLine(QPointF(x + cw - 0.5, area.top()), QPointF(x + cw - 0.5, top))
            painter.setPen(QColor(look["header_text"]))
            painter.drawText(QRectF(x, area.top(), cw, HEADER_H), Qt.AlignCenter, R.col_name(c))
        painter.setClipRect(QRectF(area.left(), top, HEADER_W, area.bottom() - top))
        for r, y, rh in rows.items:
            painter.setPen(QColor(look["header_line"]))
            painter.drawLine(QPointF(area.left(), y + rh - 0.5), QPointF(left, y + rh - 0.5))
            painter.setPen(QColor(look["header_text"]))
            painter.drawText(QRectF(area.left(), y, HEADER_W - 4, rh), Qt.AlignRight | Qt.AlignVCenter, str(r + 1))
        painter.setClipping(False)
        if sheet.charts:
            from .charts import chart_rect, paint_chart
            col_x = {c: x for c, x, _w in cols.items}
            row_y = {r: y for r, y, _h in rows.items}

            def x_of(c):
                if c in col_x:
                    return col_x[c]
                return x_main + (sheet.cols.pos(c) - sheet.cols.pos(first_col))

            def y_of(r):
                if r in row_y:
                    return row_y[r]
                return y_main + (sheet.rows.pos(r) - sheet.rows.pos(first_row))
            painter.setClipRect(body)
            for chart in sheet.charts:
                rect = chart_rect(sheet, chart, x_of, y_of, 1.0)
                if rect.intersects(body):
                    paint_chart(painter, rect, book, sheet, chart, 1.0)
            painter.setClipping(False)

    # -- souris --
    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton and self._standard_rect().contains(event.pos()):
            event.accept()
            QTimer.singleShot(0, self.open_standard)
            return
        ctrl = bool(QApplication.keyboardModifiers() & Qt.ControlModifier)
        self.setFlag(QGraphicsItem.ItemIsMovable, ctrl and not self.locked())   # Ctrl + glisser = déplacer
        super().mousePressEvent(event)

    def mouseReleaseEvent(self, event):
        super().mouseReleaseEvent(event)
        self.setFlag(QGraphicsItem.ItemIsMovable, False)

    def _place_from_data(self):
        super()._place_from_data()
        self.setFlag(QGraphicsItem.ItemIsMovable, False)

    def mouseDoubleClickEvent(self, event):
        if event.pos().y() > TITLE_H and not self.locked():
            event.accept()
            self.start_edit()
            return
        super().mouseDoubleClickEvent(event)

    # -- édition sur place --
    def is_editing(self) -> bool:
        return self._proxy is not None

    def start_edit(self):
        if self._proxy is not None:
            return
        from .widget import SpreadsheetWidget
        board = self._board_pane()
        settings = getattr(board, "_settings", {}) if board is not None else {}
        widget = SpreadsheetWidget(self.session, settings, compact=True)
        widget.grid.embedded = True
        widget.leaveRequested.connect(lambda: QTimer.singleShot(0, self.stop_edit))
        widget.saveRequested.connect(self._save_board)
        proxy = _Embedded(self)
        proxy.setWidget(widget)
        self._proxy, self._widget = proxy, widget
        scene = self.scene()
        if scene is not None:
            scene.embedded_item = self
        self.sync()
        self.setCacheMode(QGraphicsItem.NoCache)
        proxy.setFocus()
        widget.grid.setFocus()
        self.update()

    def stop_edit(self):
        proxy, widget = self._proxy, self._widget
        if proxy is None:
            return
        if widget.grid.is_editing():
            widget.grid.commit_edit(move=None)
        self._proxy = self._widget = None
        scene = self.scene()
        if scene is not None and getattr(scene, "embedded_item", None) is self:
            scene.embedded_item = None
        widget.detach()
        proxy.setWidget(None)
        proxy.setParentItem(None)
        if scene is not None:
            scene.removeItem(proxy)
        widget.deleteLater()
        proxy.deleteLater()
        self.setCacheMode(QGraphicsItem.DeviceCoordinateCache)
        self.update()
        views = scene.views() if scene is not None else []
        if views:
            views[0].setFocus()

    def _board_pane(self):
        scene = self.scene()
        if scene is None:
            return None
        parent = scene.parent()
        return parent if hasattr(parent, "save") else None

    def _save_board(self):
        board = self._board_pane()
        if board is not None:
            board.save()

    # -- mode Standard --
    def open_standard(self):
        board = self._board_pane()
        if board is None:
            return
        self.stop_edit()
        from .standard import StandardPane
        StandardPane.open(board, self)


ITEM_CLASSES[bm.SHEET] = SheetItem
