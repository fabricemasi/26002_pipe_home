"""Panneaux latéraux de l'éditeur PDF (Qt) : miniatures, signets, champs, commentaires, informations.

Miniatures : rendues À LA DEMANDE (seulement les lignes peintes, priorité « miniatures » du moteur), gardées par
génération du document ; réorganisation des pages au CTRL + GLISSER (règle de l'appli : tout déplacement d'élément
démarre avec Ctrl), opacité du fantôme `DRAG_GHOST_OPACITY`."""
from __future__ import annotations

from PySide6.QtCore import QAbstractListModel, QModelIndex, QRect, QSize, Qt, Signal
from PySide6.QtGui import QColor, QPainter
from PySide6.QtWidgets import (QAbstractItemView, QApplication, QListView, QStyle, QStyledItemDelegate, QTreeWidget,
                               QTreeWidgetItem, QVBoxLayout, QWidget)

from . import ui_kit
from .worker import PRIO_THUMB

THUMB = 132


def _ghost_opacity() -> float:
    try:
        import ui_state
        return float(getattr(ui_state, "DRAG_GHOST_OPACITY", 0.6))
    except Exception:                                       # noqa: BLE001
        return 0.6


class _ThumbModel(QAbstractListModel):
    def __init__(self, panel):
        super().__init__()
        self.panel = panel

    def rowCount(self, parent=QModelIndex()):
        return 0 if parent.isValid() else self.panel.count

    def data(self, index, role=Qt.DisplayRole):
        if role == Qt.DisplayRole:
            labels = self.panel.labels
            i = index.row()
            return labels[i] if i < len(labels) and labels[i] else str(i + 1)
        return None


class _ThumbDelegate(QStyledItemDelegate):
    def __init__(self, panel):
        super().__init__()
        self.panel = panel

    def sizeHint(self, option, index):
        return QSize(THUMB + 24, int(THUMB * self.panel.aspect(index.row())) + 30)

    def paint(self, painter, option, index):
        i = index.row()
        r = option.rect
        selected = bool(option.state & QStyle.State_Selected) or self.panel.view.selectionModel().isSelected(index)
        painter.save()
        if selected:
            painter.fillRect(r.adjusted(2, 2, -2, -2), QColor(60, 120, 220, 70))
        h = int(THUMB * self.panel.aspect(i))
        box = QRect(r.left() + (r.width() - THUMB) // 2, r.top() + 6, THUMB, h)
        painter.fillRect(box.translated(2, 2), QColor(0, 0, 0, 70))
        img = self.panel.thumb(i)
        if img is not None:
            painter.setRenderHint(QPainter.SmoothPixmapTransform, True)
            painter.drawImage(box, img)
        else:
            painter.fillRect(box, Qt.white)
        if i == self.panel.current:
            painter.setPen(QColor(90, 160, 255))
            painter.drawRect(box.adjusted(-2, -2, 1, 1))
        painter.setPen(QColor(200, 204, 208))
        painter.drawText(QRect(r.left(), box.bottom() + 2, r.width(), 18), Qt.AlignCenter, index.data())
        target = self.panel.drop_row()
        if target is not None and target in (i, i + 1):        # marque d'insertion du Ctrl + glisser
            painter.setOpacity(_ghost_opacity())
            y = r.top() + 1 if target == i else r.bottom() - 1
            painter.fillRect(QRect(r.left() + 8, y - 1, r.width() - 16, 3), QColor(90, 160, 255))
        painter.restore()


class ThumbsPanel(QWidget):
    pageActivated = Signal(int)
    movePages = Signal(list, int)               # pages (indices), avant la page
    contextRequested = Signal(object, list)     # position globale, pages sélectionnées

    def __init__(self, session, parent=None):
        super().__init__(parent)
        self.session = session
        self.count = 0
        self.labels: list = []
        self.sizes: list = []
        self.current = 0
        self._thumbs: dict[int, object] = {}
        self._jobs: dict[int, object] = {}
        self._gen = -1
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        self.view = QListView(self)
        self.view.setUniformItemSizes(False)
        self.view.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self.view.setVerticalScrollMode(QAbstractItemView.ScrollPerPixel)
        self.view.setStyleSheet("QListView { background: transparent; border: none; }")
        self.model = _ThumbModel(self)
        self.view.setModel(self.model)
        self.view.setItemDelegate(_ThumbDelegate(self))
        self.view.clicked.connect(lambda idx: self.pageActivated.emit(idx.row()))
        self.view.setContextMenuPolicy(Qt.CustomContextMenu)
        self.view.customContextMenuRequested.connect(
            lambda pos: self.contextRequested.emit(self.view.viewport().mapToGlobal(pos), self.selected_pages()))
        self.view.viewport().installEventFilter(self)
        self._drag = None
        lay.addWidget(self.view)

    def set_document(self, info: dict) -> None:
        self.model.beginResetModel()
        self.count = info.get("page_count", 0)
        self.labels = info.get("labels") or []
        self.sizes = info.get("sizes") or []
        self._thumbs.clear()
        for job in self._jobs.values():
            job.cancel()
        self._jobs.clear()
        self._gen = self.session.generation
        self.model.endResetModel()

    def aspect(self, i: int) -> float:
        if i < len(self.sizes):
            w, h = self.sizes[i]
            return min(2.0, max(0.3, h / max(1.0, w)))
        return 1.3

    def thumb(self, i: int):
        img = self._thumbs.get(i)
        if img is None and i not in self._jobs and i < len(self.sizes):
            w, h = self.sizes[i]
            scale = THUMB * self.devicePixelRatioF() / max(1.0, w)

            def done(result, error, i=i):
                self._jobs.pop(i, None)
                if error is None and result and result[0] == self.session.generation:
                    self._thumbs[i] = result[1]
                    self.view.viewport().update()
            self._jobs[i] = self.session.render_tile(i, scale, (0, 0, max(1, int(w * scale)), max(1, int(h * scale))),
                                                     0, PRIO_THUMB, done, self.devicePixelRatioF())
        return img

    def invalidate(self, pages=None) -> None:
        for i in (pages if pages is not None else list(self._thumbs)):
            self._thumbs.pop(i, None)
        self.view.viewport().update()

    def set_current(self, i: int) -> None:
        if i == self.current:
            return
        self.current = i
        if 0 <= i < self.count:
            self.view.scrollTo(self.model.index(i), QAbstractItemView.EnsureVisible)
        self.view.viewport().update()

    def selected_pages(self) -> list[int]:
        rows = sorted(idx.row() for idx in self.view.selectionModel().selectedIndexes())
        return rows or ([self.current] if self.count else [])

    # Ctrl + glisser : déplacer les pages choisies
    def eventFilter(self, obj, event):
        from PySide6.QtCore import QEvent
        t = event.type()
        if t == QEvent.MouseButtonPress and event.button() == Qt.LeftButton and \
                QApplication.keyboardModifiers() & Qt.ControlModifier:
            idx = self.view.indexAt(event.position().toPoint())
            if idx.isValid():
                if not self.view.selectionModel().isSelected(idx):
                    self.view.setCurrentIndex(idx)
                self._drag = {"pages": self.selected_pages(), "start": event.position().toPoint(), "target": None}
                return True
        if t == QEvent.MouseMove and self._drag is not None:
            pos = event.position().toPoint()
            idx = self.view.indexAt(pos)
            if idx.isValid():
                r = self.view.visualRect(idx)
                self._drag["target"] = idx.row() + (1 if pos.y() > r.center().y() else 0)
            self.view.viewport().update()
            return True
        if t == QEvent.MouseButtonRelease and self._drag is not None:
            drag, self._drag = self._drag, None
            target = drag["target"]
            if target is not None and (event.position().toPoint() - drag["start"]).manhattanLength() > 6:
                pages = drag["pages"]
                if not (min(pages) <= target <= max(pages) + 1 and len(pages) == max(pages) - min(pages) + 1):
                    self.movePages.emit(pages, target)
            self.view.viewport().update()
            return True
        return super().eventFilter(obj, event)

    def drop_row(self) -> int | None:
        """Ligne devant laquelle les pages glissées iraient (marque peinte par le délégué)."""
        return self._drag.get("target") if self._drag else None


class OutlinePanel(QWidget):
    pageActivated = Signal(int)

    def __init__(self, parent=None):
        super().__init__(parent)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        self.tree = QTreeWidget(self)
        self.tree.setHeaderHidden(True)
        self.tree.setStyleSheet("QTreeWidget { background: transparent; border: none; }")
        self.tree.itemClicked.connect(lambda item, _c: self._go(item))
        self.empty = ui_kit.label("Aucun signet dans ce document.", "value_muted")
        lay.addWidget(self.empty)
        lay.addWidget(self.tree)

    def _go(self, item):
        page = item.data(0, Qt.UserRole)
        if page is not None and page >= 0:
            self.pageActivated.emit(page)

    def set_outline(self, outline: list) -> None:
        self.tree.clear()

        def add(parent, nodes):
            for node in nodes:
                item = QTreeWidgetItem([node["title"] or "(sans titre)"])
                item.setData(0, Qt.UserRole, node["page"])
                item.setToolTip(0, "Page %d" % (node["page"] + 1) if node["page"] >= 0 else "")
                (parent.addChild if parent is not None else self.tree.addTopLevelItem)(item)
                add(item, node["children"])
        add(None, outline)
        self.tree.expandToDepth(0)
        self.empty.setVisible(not outline)
        self.tree.setVisible(bool(outline))


class ListPanel(QWidget):
    """Liste simple (champs, commentaires) : chaque entrée garde sa donnée ; clic = activée."""
    activated = Signal(object)
    contextRequested = Signal(object, object)

    def __init__(self, empty_text: str, parent=None):
        super().__init__(parent)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        self.empty = ui_kit.label(empty_text, "value_muted")
        self.empty.setWordWrap(True)
        self.tree = QTreeWidget(self)
        self.tree.setHeaderHidden(True)
        self.tree.setRootIsDecorated(False)
        self.tree.setStyleSheet("QTreeWidget { background: transparent; border: none; }")
        self.tree.itemClicked.connect(lambda item, _c: self.activated.emit(item.data(0, Qt.UserRole)))
        self.tree.setContextMenuPolicy(Qt.CustomContextMenu)
        self.tree.customContextMenuRequested.connect(self._context)
        lay.addWidget(self.empty)
        lay.addWidget(self.tree)
        self.set_items([])

    def _context(self, pos):
        item = self.tree.itemAt(pos)
        if item is not None:
            self.contextRequested.emit(self.tree.viewport().mapToGlobal(pos), item.data(0, Qt.UserRole))

    def set_items(self, items: list[tuple[str, str, object]]) -> None:
        """[(texte, infobulle, donnée)]"""
        self.tree.clear()
        for text, tip, data in items:
            item = QTreeWidgetItem([text])
            item.setToolTip(0, tip)
            item.setData(0, Qt.UserRole, data)
            self.tree.addTopLevelItem(item)
        self.empty.setVisible(not items)
        self.tree.setVisible(bool(items))


class InfoPanel(QWidget):
    """Propriétés du document : métadonnées, sécurité, formulaire, contenu actif, actions bloquées."""

    ROWS = [("title", "Titre"), ("author", "Auteur"), ("subject", "Sujet"), ("keywords", "Mots-clés"),
            ("creator", "Créé avec"), ("producer", "Producteur"), ("created", "Création"), ("modified", "Modification"),
            ("version", "Version PDF"), ("pages", "Pages"), ("size", "Taille"), ("form", "Formulaire"),
            ("security", "Sécurité"), ("active", "Contenu actif"), ("engine", "Moteur"), ("blocked", "Bloqué")]

    def __init__(self, parent=None):
        super().__init__(parent)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(4, 4, 4, 4)
        self.table = ui_kit.Table("Propriété", [(k, label, False, None) for k, label in self.ROWS], 170)
        lay.addWidget(self.table.frame)
        lay.addStretch(1)
        self._blocked: list[str] = []

    def set_info(self, info: dict, engine_info: dict | None = None) -> None:
        meta = info.get("metadata", {})
        t = self.table
        for key, tag in (("title", "Title"), ("author", "Author"), ("subject", "Subject"), ("keywords", "Keywords"),
                         ("creator", "Creator"), ("producer", "Producer")):
            t.set(key, meta.get(tag, ""))
        t.set("created", _pdf_date(meta.get("CreationDate", "")))
        t.set("modified", _pdf_date(meta.get("ModDate", "")))
        t.set("version", meta.get("version", ""))
        t.set("pages", info.get("page_count", 0))
        t.set("size", _size(info.get("size", 0)))
        kind = info.get("form_kind", "aucun")
        form = {"aucun": "aucun", "acroform": "AcroForm (%d champs)" % len(info.get("fields", [])),
                "xfa_dynamique": "XFA dynamique", "xfa_statique": "XFA statique"}.get(kind, kind)
        if info.get("is_xfa"):
            form += " — chargé par le moteur XFA (%.0f ms)" % info.get("xfa_ms", 0) if info.get("xfa_loaded") else \
                " — moteur XFA ABSENT : seul l'aperçu statique est montré"
        t.set("form", form)
        sec = info.get("security", {})
        if sec.get("encrypted"):
            rights = [name for flag, name in (("can_print", "impression"), ("can_modify", "modification"),
                                              ("can_copy", "copie"), ("can_annotate", "commentaires"),
                                              ("can_fill", "remplissage")) if sec.get(flag)]
            t.set("security", "chiffré (révision %d) ; autorisé : %s" % (sec.get("revision", 0),
                                                                         ", ".join(rights) or "rien"))
        else:
            t.set("security", "non chiffré")
        active = info.get("active", {})
        parts = []
        if active.get("javascript"):
            parts.append("%d script(s) JavaScript" % active["javascript"])
        if active.get("attachments"):
            parts.append("%d pièce(s) jointe(s)" % active["attachments"])
        if active.get("signatures"):
            parts.append("%d signature(s)" % active["signatures"])
        t.set("active", ", ".join(parts) or "aucun")
        if engine_info:
            t.set("engine", "PDFium %s%s" % (engine_info.get("build", "?"),
                                             " (V8 + XFA)" if engine_info.get("xfa") else " (sans XFA)"))
        t.set("blocked", "\n".join(self._blocked[-6:]) or "rien")

    def add_blocked(self, what: str) -> None:
        self._blocked.append(what)
        self.table.set("blocked", "\n".join(self._blocked[-6:]))


def _size(n: int) -> str:
    for unit in ("octets", "Ko", "Mo", "Go"):
        if n < 1024 or unit == "Go":
            return ("%d %s" % (n, unit)) if unit == "octets" else ("%.1f %s" % (n, unit))
        n /= 1024.0
    return str(n)


def _pdf_date(text: str) -> str:
    """D:20260105143000+01'00' -> 05/01/2026 14:30."""
    if not text:
        return ""
    s = text[2:] if text.startswith("D:") else text
    try:
        return "%s/%s/%s %s:%s" % (s[6:8], s[4:6], s[0:4], s[8:10] or "00", s[10:12] or "00")
    except IndexError:
        return text
