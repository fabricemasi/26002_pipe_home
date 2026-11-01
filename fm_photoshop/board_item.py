"""Élément « ps_doc » du Board (Qt) : un document Photoshop posé sur le canvas.

- Présentation : barre de titre + la COMPOSITION du document (damier de transparence dessous), calculée par la même
  `render.TileCache` que l'éditeur Standard (rien n'est recomposé en passant de l'un à l'autre).
- Double-clic (ou « ⤢ » de la barre de titre) : éditeur STANDARD plein cadre sur la MÊME session.
- Déplacer l'élément : Ctrl + glisser (règle de l'appli) ; sans Ctrl, un clic le choisit seulement.
- Données : les pixels ne sont JAMAIS dans le JSON du Board. À l'enregistrement (`before_save`, appelé par
  `BoardScene.to_data`) la session écrit son conteneur `.fmps` dans `<board>_assets` (nom = empreinte) et l'élément
  n'en garde que le nom (`asset`). Le conteneur n'est réécrit que si le document a changé.
- Les modifications du document ne sont PAS des étapes d'annulation du Board (historique du document, comme le Tableur) ;
  elles déclenchent l'enregistrement automatique du Board (`contentChanged`)."""
from __future__ import annotations

import copy
import math
import uuid
import weakref

from PySide6.QtCore import QRectF, Qt, QTimer
from PySide6.QtGui import QColor, QFont, QPainter, QPen
from PySide6.QtWidgets import QApplication, QGraphicsItem

from fm_miro.items import ITEM_CLASSES, BoardItem
from . import board_model as bm
from . import look, render, session as S

TITLE_H = 24.0
ACCENT = "#2f86d6"


def _scene_token(scene) -> str:
    token = getattr(scene, "_photoshop_token", None)
    if token is None:
        token = scene._photoshop_token = uuid.uuid4().hex
        weakref.finalize(scene, _forget_scene, token)
    return token


def _forget_scene(token):
    for key in [k for k in list(S._REGISTRY) if isinstance(k, tuple) and k[0] == token]:
        S.forget(key)


class PsItem(BoardItem):
    MODULE = "photoshop"
    CONNECTABLE = True
    RESIZABLE = True

    def __init__(self, data: dict):
        self._session = None
        self._listener = None
        self._paint_retry = False
        super().__init__(data)

    # -- session --
    def _board_path(self):
        scene = self.scene()
        return getattr(scene, "board_path", None) if scene is not None else None

    def _read_asset(self):
        from fm_board import serialization
        name, path = self.data.get("asset"), self._board_path()
        if not name or path is None or not serialization.is_asset_name(name):
            return None
        try:
            return serialization.asset_path(path, name).read_bytes()
        except OSError:
            return None

    @property
    def session(self):
        if self._session is None:
            scene = self.scene()
            key = (_scene_token(scene), self.item_id) if scene is not None else ("libre", self.item_id)
            found = S.get(key)
            asset = self.data.get("asset") or ""
            if found is not None and asset and found.asset != asset and not found.is_dirty() \
                    and found.history.version == 0:
                S.forget(key)                                  # board rechargé avec un autre conteneur : on relit
                found = None
            if found is None:
                if asset:
                    found = S.open_asset(key, self._read_asset(), {"w": self.data.get("doc_w") or 800,
                                                                   "h": self.data.get("doc_h") or 600,
                                                                   "title": self.data.get("title")}, asset)
                else:
                    init = self.data.get("init") or {}
                    bg = init.get("background", [255, 255, 255, 255])
                    found = S.create(key, int(init.get("w", 1280)), int(init.get("h", 720)),
                                     init.get("name") or self.data.get("title") or "Document",
                                     float(init.get("dpi", 72.0)), tuple(bg) if bg else None)
            self._session = found
            ref = weakref.ref(self)

            def listener(kind, rect, ref=ref):
                item = ref()
                if item is not None:
                    item._document_changed(kind)
            self._listener = listener
            found.listeners.append(listener)
            self.data["doc_w"], self.data["doc_h"] = found.doc.width, found.doc.height
        return self._session

    def added_to_scene(self, scene):
        self._session = None                 # clé liée à la scène
        _ = self.session

    def removing_from_scene(self, scene):
        self._detach()

    def _detach(self):
        if self._session is not None and self._listener in self._session.listeners:
            self._session.listeners.remove(self._listener)
        self._listener = None
        self._session = None

    def _document_changed(self, kind):
        try:
            scene = self.scene()
            if not getattr(self._session, "standard_open", False) or kind == "reload":
                self.update()
            else:
                self._stale = True
        except RuntimeError:                 # élément déjà détruit
            return
        if scene is not None and kind in ("edit", "structure", "reload", "committed"):
            scene.contentChanged.emit()

    def standard_closed(self):
        self.update()

    # -- état --
    def to_dict(self) -> dict:
        data = {k: copy.deepcopy(v) for k, v in self.data.items()}
        data["x"], data["y"] = round(self.pos().x(), 2), round(self.pos().y(), 2)
        data["z"] = self.zValue()
        if self._session is not None and self._session.asset:
            data["asset"] = self._session.asset
        return data

    def before_save(self):
        """Écrit le conteneur du document dans le dossier du Board (appelé avant chaque sérialisation du Board)."""
        session = self._session
        path = self._board_path()
        if session is None or path is None:
            return
        from fm_board import serialization
        try:
            name = session.flush(lambda payload, suffix: serialization.import_image_bytes(path, payload, suffix))
        except OSError as exc:
            session.error = f"Enregistrement du document impossible : {exc}"
            return
        self.data["asset"] = name
        self.data["doc_w"], self.data["doc_h"] = session.doc.width, session.doc.height

    def apply(self, data: dict):
        """État du Board (annuler un déplacement…) : le document EN COURS est gardé, seul le cadre change."""
        data = dict(data)
        if self._session is not None and self._session.asset:
            data["asset"] = self._session.asset
        super().apply(data)

    def sync(self):
        pass

    # -- peinture --
    def paint(self, painter: QPainter, option, widget=None):
        w, h = self.size()
        rect = QRectF(0, 0, w, h)
        painter.save()
        painter.setRenderHint(QPainter.Antialiasing, False)
        painter.fillRect(rect, QColor(look.LOOK["bench_color"]))
        painter.fillRect(QRectF(0, 0, w, TITLE_H), QColor(ACCENT))
        font = QFont("Segoe UI")
        font.setPixelSize(12)
        font.setBold(True)
        painter.setFont(font)
        painter.setPen(QColor("#ffffff"))
        session = self.session
        painter.drawText(QRectF(8, 0, w - 44, TITLE_H), Qt.AlignVCenter | Qt.AlignLeft,
                         f"{self.data.get('title') or session.doc.name} — {session.doc.width} × {session.doc.height}")
        painter.drawText(self._standard_rect(), Qt.AlignCenter, "⤢")
        self._paint_document(painter, QRectF(0, TITLE_H, w, h - TITLE_H))
        painter.setPen(QPen(QColor(ACCENT) if self.isSelected() else QColor("#808080"), 1))
        painter.setBrush(Qt.NoBrush)
        painter.drawRect(rect.adjusted(0.5, 0.5, -0.5, -0.5))
        painter.restore()
        if self.isSelected():
            self.paint_selection(painter)

    def _standard_rect(self) -> QRectF:
        w, _h = self.size()
        return QRectF(w - 30, 0, 28, TITLE_H)

    def fit_rect(self, area: QRectF) -> QRectF:
        doc = self.session.doc
        scale = min((area.width() - 8) / doc.width, (area.height() - 8) / doc.height)
        width, height = doc.width * scale, doc.height * scale
        return QRectF(area.left() + (area.width() - width) / 2, area.top() + (area.height() - height) / 2, width,
                      height)

    def _paint_document(self, painter, area: QRectF):
        session = self.session
        doc = session.doc
        if area.width() < 12 or area.height() < 12:
            return
        target = self.fit_rect(area)
        painter.setBrush(Qt.NoBrush)
        painter.fillRect(target, render.checker_brush(look.LOOK["checker_a"], look.LOOK["checker_b"], 6))
        cache = render.cache_for(session)
        scale = target.width() / doc.width
        painter.save()
        painter.setClipRect(target)
        painter.translate(target.topLeft())
        painter.scale(scale, scale)
        painter.setRenderHint(QPainter.SmoothPixmapTransform, True)
        keys = cache.keys_for(doc.rect())
        cache.pump(keys, 8.0)                                   # tranche de temps : un grand document apparaît par morceaux
        ready = True
        for key in keys:
            if cache.is_ready(key):
                painter.drawImage(key[0] * render.TILE, key[1] * render.TILE, cache.tiles[key][1])
            else:
                ready = False
        painter.restore()
        painter.setPen(QPen(QColor(look.LOOK["frame_color"]), 1))
        painter.setBrush(Qt.NoBrush)
        painter.drawRect(target.adjusted(-0.5, -0.5, 0.5, 0.5))
        if not ready and not self._paint_retry:
            self._paint_retry = True
            ref = weakref.ref(self)

            def again():
                item = ref()
                if item is not None:
                    item._paint_retry = False
                    try:
                        item.update()
                    except RuntimeError:
                        pass
            QTimer.singleShot(1, again)
        if session.error:
            painter.setPen(QColor("#ff8a80"))
            painter.drawText(area.adjusted(8, 8, -8, -8), Qt.AlignTop | Qt.AlignLeft | Qt.TextWordWrap, session.error)

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
            self.open_standard()
            return
        super().mouseDoubleClickEvent(event)

    # -- éditeur Standard --
    def board_pane(self):
        scene = self.scene()
        if scene is None:
            return None
        parent = scene.parent()
        return parent if hasattr(parent, "save") else None

    def open_standard(self):
        board = self.board_pane()
        if board is None:
            return None
        from .standard import StandardPane
        return StandardPane.open(board, self)


ITEM_CLASSES[bm.PS_DOC] = PsItem
