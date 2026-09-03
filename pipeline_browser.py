#!/usr/bin/env python3
"""
Pipeline Browser - navigateur en colonnes (Miller columns) pour F:\\PIPELINE.

Habillage base sur la maquette Claude Design :
  IBM Plex Sans / IBM Plex Mono, fond #1a1c1e, accent #3f6f9f,
  colonnes de 220px, lignes de 24px, barre de statut monospace.

Lecture seule pour l'instant.

    pip install PySide6
    pythonw pipeline_browser.py   (pythonw = sans fenetre console ; python = avec)
"""

import os
import shutil
import subprocess
import sys
from datetime import datetime
from pathlib import Path

from PySide6.QtCore import QEvent, QMimeData, QSize, Qt, QUrl, Signal
from PySide6.QtGui import (
    QAction,
    QColor,
    QDesktopServices,
    QDrag,
    QPainter,
    QPixmap,
)
from PySide6.QtWidgets import (
    QAbstractItemView,
    QApplication,
    QFileDialog,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMainWindow,
    QMenu,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QStyle,
    QStyledItemDelegate,
    QVBoxLayout,
    QWidget,
)

from app_style import C, apply_style, font

# ==========================================================================
# Configuration
# ==========================================================================

ROOT = Path(r"F:\PIPELINE")

COLUMN_LABELS = ["Type", "Projets", "Sous-dossiers", "Logiciels", "Contenu"]

# Dossiers dont le contenu est remonte dans la colonne du parent.
FLATTEN_FOLDERS = {"WORK"}

HIDDEN_PREFIXES = (".", "$", "~")

IMAGE_EXTENSIONS = {
    ".jpg", ".jpeg", ".png", ".gif", ".bmp", ".webp", ".tif", ".tiff", ".ico",
}

PREVIEW_MIN_HEIGHT = 104   # hauteur de la vignette sans image (ou image tres petite)
PREVIEW_MAX_HEIGHT = 800   # jamais plus grand que ca, meme pour une tres grande image

# ==========================================================================
# Design tokens : voir app_style.py (C, STYLESHEET, font()) partage entre
# toutes les applications du pipeline.
# ==========================================================================

COLUMN_WIDTH = 220
COLUMN_MIN_WIDTH = 120
COLUMN_MAX_WIDTH = 640
COLUMN_RESIZE_MARGIN = 5   # zone (px) autour de la bordure ou le curseur change
ROW_HEIGHT = 24
HEADER_HEIGHT = 26
TOPBAR_HEIGHT = 40
STATUS_HEIGHT = 24


# ==========================================================================
# Scan disque
# ==========================================================================

def human_size(n: int) -> str:
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if n < 1024 or unit == "TB":
            return f"{n:.0f} {unit}" if unit == "B" else f"{n:.1f} {unit}"
        n /= 1024.0
    return ""


def list_entries(directory: Path) -> list[Path]:
    """Dossiers puis fichiers, tries. Les FLATTEN_FOLDERS sont traverses."""
    dirs: list[Path] = []
    files: list[Path] = []
    try:
        with os.scandir(directory) as it:
            for entry in it:
                if entry.name.startswith(HIDDEN_PREFIXES):
                    continue
                path = Path(entry.path)
                if entry.is_dir():
                    if entry.name.upper() in FLATTEN_FOLDERS:
                        dirs.extend(p for p in list_entries(path) if p.is_dir())
                    else:
                        dirs.append(path)
                else:
                    files.append(path)
    except OSError:
        return []
    key = lambda p: p.name.lower()
    return sorted(dirs, key=key) + sorted(files, key=key)


def open_path(path: Path):
    QDesktopServices.openUrl(QUrl.fromLocalFile(str(path)))


def reveal_in_file_manager(path: Path):
    if sys.platform == "win32":
        subprocess.Popen(["explorer", "/select,", str(path)])
    elif sys.platform == "darwin":
        subprocess.Popen(["open", "-R", str(path)])
    else:
        subprocess.Popen(["xdg-open", str(path.parent)])


# ==========================================================================
# Rendu des lignes
# ==========================================================================

ROLE_PATH = Qt.UserRole
ROLE_ISDIR = Qt.UserRole + 1
ROLE_META = Qt.UserRole + 2


class RowDelegate(QStyledItemDelegate):
    """Marqueur carre + nom + metadonnee alignee a droite."""

    def __init__(self, column):
        super().__init__(column)
        self.column = column
        self.font_dir = font(12, 600, tracking=0.12)
        self.font_file = font(12, 400, tracking=0.12)
        self.font_meta = font(11, 400, mono=True)

    def sizeHint(self, option, index) -> QSize:
        return QSize(COLUMN_WIDTH, ROW_HEIGHT)

    def paint(self, painter: QPainter, option, index):
        painter.save()
        painter.setRenderHint(QPainter.Antialiasing, False)

        rect = option.rect
        selected = bool(option.state & QStyle.State_Selected)
        hovered = bool(option.state & QStyle.State_MouseOver)
        is_dir = bool(index.data(ROLE_ISDIR))
        active = self.column.is_active

        if selected:
            bg = C["accent"] if active else C["sel_idle"]
        elif hovered:
            bg = C["hover"]
        else:
            bg = None
        if bg:
            painter.fillRect(rect, QColor(bg))

        # Marqueur 9x9
        mark_x = rect.left() + 10
        mark_y = rect.center().y() - 4
        if selected and active:
            border, fill = C["accent_text"], "transparent"
        elif is_dir:
            border, fill = C["mark_dir_bd"], C["mark_dir_fill"]
        else:
            border, fill = C["mark_file_bd"], "transparent"
        if fill != "transparent":
            painter.fillRect(mark_x, mark_y, 9, 9, QColor(fill))
        painter.setPen(QColor(border))
        painter.drawRect(mark_x, mark_y, 8, 8)

        # Metadonnee (taille fichier)
        meta = index.data(ROLE_META) or ""
        meta_w = 0
        if meta:
            painter.setFont(self.font_meta)
            meta_w = painter.fontMetrics().horizontalAdvance(meta) + 10
            painter.setPen(QColor(C["accent_text"] if (selected and active) else C["dim"]))
            painter.drawText(
                rect.adjusted(0, 0, -10, 0),
                Qt.AlignRight | Qt.AlignVCenter,
                meta,
            )

        # Nom
        text_x = mark_x + 16
        text_rect = rect.adjusted(text_x - rect.left(), 0, -(10 + meta_w), 0)
        painter.setFont(self.font_dir if is_dir else self.font_file)
        if selected and active:
            painter.setPen(QColor(C["accent_text"]))
        else:
            painter.setPen(QColor(C["text"] if is_dir else C["text_file"]))
        name = painter.fontMetrics().elidedText(
            index.data(Qt.DisplayRole), Qt.ElideMiddle, text_rect.width()
        )
        painter.drawText(text_rect, Qt.AlignLeft | Qt.AlignVCenter, name)

        painter.restore()


# ==========================================================================
# Liste avec glisser-deposer de vrais fichiers
# ==========================================================================

class FileListWidget(QListWidget):
    """QListWidget dont le glisser-deposer manipule des fichiers reels sur
    le disque : entre colonnes de l'app, mais aussi avec l'explorateur
    Windows (et inversement)."""

    def __init__(self, column: "Column", parent=None):
        super().__init__(parent)
        self.column = column
        self.setDragEnabled(True)
        self.setAcceptDrops(True)
        self.setDragDropMode(QAbstractItemView.DragDrop)
        self.setDefaultDropAction(Qt.MoveAction)

    def mimeData(self, items):
        mime = QMimeData()
        mime.setUrls([QUrl.fromLocalFile(it.data(ROLE_PATH)) for it in items])
        return mime

    def supportedDropActions(self):
        return Qt.CopyAction | Qt.MoveAction

    def startDrag(self, supportedActions):
        items = self.selectedItems()
        if not items:
            return
        drag = QDrag(self)
        drag.setMimeData(self.mimeData(items))
        drag.exec(Qt.CopyAction | Qt.MoveAction, Qt.MoveAction)
        self.column.refresh_all()

    def dragEnterEvent(self, event):
        if event.mimeData().hasUrls():
            event.acceptProposedAction()
        else:
            event.ignore()

    def dragMoveEvent(self, event):
        if event.mimeData().hasUrls():
            event.acceptProposedAction()
        else:
            event.ignore()

    def dropEvent(self, event):
        mime = event.mimeData()
        if not mime.hasUrls():
            event.ignore()
            return

        mods = QApplication.keyboardModifiers()
        if mods & Qt.ControlModifier:
            action = Qt.CopyAction
        elif mods & Qt.ShiftModifier:
            action = Qt.MoveAction
        elif event.proposedAction() in (Qt.CopyAction, Qt.MoveAction):
            action = event.proposedAction()
        else:
            action = Qt.CopyAction

        target_item = self.itemAt(event.position().toPoint())
        dest_dir = self.column.directory
        if target_item and target_item.data(ROLE_ISDIR):
            dest_dir = Path(target_item.data(ROLE_PATH))

        last_dest = self.apply_drop(mime.urls(), action, dest_dir)

        event.setDropAction(action)
        event.accept()
        if last_dest:
            for i in range(self.count()):
                it = self.item(i)
                if it.data(ROLE_PATH) == str(last_dest):
                    self.setCurrentItem(it)
                    break

    def apply_drop(self, urls, action, dest_dir: Path | None = None) -> Path | None:
        """Copie ou deplace les fichiers/dossiers de `urls` dans `dest_dir`
        (par defaut le dossier de cette colonne ; peut aussi etre un
        sous-dossier vise directement, cf. dropEvent). Retourne le dernier
        chemin depose (ou None). Separe de dropEvent() pour rester testable
        sans QDropEvent reel."""
        dest_dir = dest_dir if dest_dir is not None else self.column.directory
        errors = []
        last_dest = None
        for url in urls:
            if not url.isLocalFile():
                continue
            src = Path(url.toLocalFile())
            if not src.exists():
                continue
            try:
                if src.resolve() == dest_dir.resolve():
                    continue
                if src.parent.resolve() == dest_dir.resolve():
                    continue  # deja dans ce dossier
                if src.is_dir() and dest_dir.resolve() != src.resolve():
                    try:
                        dest_dir.resolve().relative_to(src.resolve())
                        continue  # depose dans lui-meme ou un sous-dossier
                    except ValueError:
                        pass
            except OSError:
                continue
            dest = self.column._unique_dest_path(src, dest_dir)
            try:
                if action == Qt.MoveAction:
                    shutil.move(str(src), str(dest))
                else:
                    if src.is_dir():
                        shutil.copytree(src, dest)
                    else:
                        shutil.copy2(src, dest)
                last_dest = dest
            except OSError as exc:
                errors.append(f"{src.name} : {exc}")

        if errors:
            QMessageBox.warning(
                self, "Glisser-deposer",
                "Impossible de deplacer/copier :\n" + "\n".join(errors),
            )

        self.column.refresh_all()
        return last_dest


# ==========================================================================
# Colonne
# ==========================================================================

class Column(QWidget):

    selected = Signal(object, object)   # (Column, Path | None)
    activated = Signal(object)          # Path

    def __init__(self, directory: Path, title: str, parent=None):
        super().__init__(parent)
        self.directory = directory
        self.is_active = False

        self.title_label = QLabel(title)
        self.title_label.setFont(font(10, 600, tracking=0.9, caps=True))
        self.title_label.setStyleSheet(f"color: {C['header']}; background: transparent;")

        self.count_label = QLabel("")
        self.count_label.setFont(font(10, 400, mono=True))
        self.count_label.setStyleSheet(f"color: {C['count']}; background: transparent;")

        header = QWidget()
        header.setFixedHeight(HEADER_HEIGHT)
        header.setStyleSheet(
            f"background: {C['chrome']}; border-bottom: 1px solid {C['border']};"
        )
        header_layout = QHBoxLayout(header)
        header_layout.setContentsMargins(10, 0, 10, 0)
        header_layout.addWidget(self.title_label)
        header_layout.addStretch(1)
        header_layout.addWidget(self.count_label)

        self.list = FileListWidget(self)
        self.list.setFrameShape(QFrame.NoFrame)
        self.list.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.list.setMouseTracking(True)
        self.list.setUniformItemSizes(True)
        self.list.setItemDelegate(RowDelegate(self))
        self.list.setContextMenuPolicy(Qt.CustomContextMenu)
        self.list.setViewportMargins(0, 3, 0, 3)
        self.list.currentItemChanged.connect(self._on_current_changed)
        self.list.itemDoubleClicked.connect(self._on_double_clicked)
        self.list.customContextMenuRequested.connect(self._on_context_menu)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 1, 0)
        layout.setSpacing(0)
        layout.addWidget(header)
        layout.addWidget(self.list, 1)

        self.setFixedWidth(COLUMN_WIDTH)
        self.setObjectName("Column")
        self.setAttribute(Qt.WA_StyledBackground, True)
        self.setStyleSheet(f"#Column {{ border-right: 1px solid {C['border']}; }}")

        # Redimensionnement par glisser-deposer sur la bordure droite.
        self._resizing = False
        self._resize_start_x = 0
        self._resize_start_width = 0
        self.setMouseTracking(True)
        header.setMouseTracking(True)
        header.installEventFilter(self)
        self.list.viewport().installEventFilter(self)

        self.refresh()

    def set_active(self, active: bool):
        if self.is_active != active:
            self.is_active = active
            self.list.viewport().update()

    def refresh_all(self):
        """Rafraichit toutes les colonnes de la fenetre (utilise apres un
        glisser-deposer, qui peut affecter la colonne source ET la cible)."""
        win = self.window()
        if hasattr(win, "refresh_all_columns"):
            win.refresh_all_columns()
        else:
            self.refresh()

    def _in_resize_zone(self, x: int) -> bool:
        return self.width() - COLUMN_RESIZE_MARGIN <= x <= self.width()

    @property
    def is_resizing(self) -> bool:
        return self._resizing

    def resize_begin(self, global_x: int):
        self._resizing = True
        self._resize_start_x = global_x
        self._resize_start_width = self.width()

    def resize_update(self, global_x: int):
        delta = global_x - self._resize_start_x
        new_width = max(COLUMN_MIN_WIDTH, min(COLUMN_MAX_WIDTH, self._resize_start_width + delta))
        self.setFixedWidth(new_width)

    def resize_end(self):
        self._resizing = False

    def eventFilter(self, obj, event):
        etype = event.type()
        if etype == QEvent.MouseMove:
            local_x = obj.mapTo(self, event.position().toPoint()).x()
            if self._resizing:
                self.resize_update(event.globalPosition().toPoint().x())
                return True
            obj.setCursor(Qt.SizeHorCursor if self._in_resize_zone(local_x) else Qt.ArrowCursor)
        elif etype == QEvent.MouseButtonPress and event.button() == Qt.LeftButton:
            local_x = obj.mapTo(self, event.position().toPoint()).x()
            if self._in_resize_zone(local_x):
                self.resize_begin(event.globalPosition().toPoint().x())
                return True
        elif etype == QEvent.MouseButtonRelease and self._resizing:
            self.resize_end()
            return True
        elif etype == QEvent.Leave and not self._resizing:
            obj.unsetCursor()
        return False

    def refresh(self):
        current = self.current_path()
        self.list.blockSignals(True)
        self.list.clear()
        entries = list_entries(self.directory)
        for path in entries:
            item = QListWidgetItem(path.name)
            item.setData(ROLE_PATH, str(path))
            is_dir = path.is_dir()
            item.setData(ROLE_ISDIR, is_dir)
            meta = ""
            if not is_dir:
                try:
                    meta = human_size(path.stat().st_size)
                except OSError:
                    pass
            item.setData(ROLE_META, meta)
            self.list.addItem(item)
            if current and path == current:
                self.list.setCurrentItem(item)
        self.count_label.setText(str(len(entries)))
        self.list.blockSignals(False)

    def current_path(self) -> Path | None:
        item = self.list.currentItem()
        return Path(item.data(ROLE_PATH)) if item else None

    def _on_current_changed(self, item, _previous):
        self.selected.emit(self, Path(item.data(ROLE_PATH)) if item else None)

    def _on_double_clicked(self, item):
        self.activated.emit(Path(item.data(ROLE_PATH)))

    def _on_context_menu(self, pos):
        item = self.list.itemAt(pos)
        if not item:
            menu = QMenu(self)
            menu.setFont(font(11, 400))
            act_new_folder = menu.addAction("Nouveau dossier")
            act_paste = None
            if QApplication.clipboard().mimeData().hasUrls():
                menu.addSeparator()
                act_paste = menu.addAction("Coller")
            chosen = menu.exec(self.list.mapToGlobal(pos))
            if chosen is act_new_folder:
                self._create_folder()
            elif act_paste is not None and chosen is act_paste:
                self._paste_items()
            return
        path = Path(item.data(ROLE_PATH))
        menu = QMenu(self)
        menu.setFont(font(11, 400))
        act_open = menu.addAction("Ouvrir")
        act_rename = menu.addAction("Renommer")
        act_reveal = menu.addAction("Afficher dans l'explorateur")
        menu.addSeparator()
        act_copy_file = menu.addAction("Copier")
        act_copy_path = menu.addAction("Copier le chemin")
        chosen = menu.exec(self.list.mapToGlobal(pos))
        if chosen is act_open:
            self.activated.emit(path)
        elif chosen is act_rename:
            self._rename_item(path)
        elif chosen is act_reveal:
            reveal_in_file_manager(path)
        elif chosen is act_copy_file:
            mime = QMimeData()
            mime.setUrls([QUrl.fromLocalFile(str(path))])
            QApplication.clipboard().setMimeData(mime)
        elif chosen is act_copy_path:
            QApplication.clipboard().setText(str(path))

    def _create_folder(self):
        name, ok = QInputDialog.getText(
            self, "Nouveau dossier", "Nom du dossier :", QLineEdit.Normal, "Nouveau dossier"
        )
        if not ok:
            return
        name = name.strip()
        if not name:
            return
        if any(ch in name for ch in '\\/:*?"<>|'):
            QMessageBox.warning(self, "Nouveau dossier", "Le nom contient des caracteres interdits.")
            return
        new_path = self.directory / name
        if new_path.exists():
            QMessageBox.warning(self, "Nouveau dossier", f"« {name} » existe deja.")
            return
        try:
            new_path.mkdir()
        except OSError as exc:
            QMessageBox.warning(self, "Nouveau dossier", f"Impossible de creer le dossier :\n{exc}")
            return
        self.refresh()
        for i in range(self.list.count()):
            it = self.list.item(i)
            if it.data(ROLE_PATH) == str(new_path):
                self.list.setCurrentItem(it)
                break

    def _unique_dest_path(self, src: Path, dest_dir: Path | None = None) -> Path:
        """Chemin de destination dans `dest_dir` (par defaut ce dossier), en
        evitant les collisions (« nom - copie », « nom - copie (2) », ...)."""
        dest_dir = dest_dir if dest_dir is not None else self.directory
        dest = dest_dir / src.name
        if not dest.exists():
            return dest
        stem, suffix = (src.stem, src.suffix) if src.is_file() else (src.name, "")
        candidate = dest_dir / f"{stem} - copie{suffix}"
        i = 2
        while candidate.exists():
            candidate = dest_dir / f"{stem} - copie ({i}){suffix}"
            i += 1
        return candidate

    def _paste_items(self):
        mime = QApplication.clipboard().mimeData()
        if not mime.hasUrls():
            return
        last_dest = None
        errors = []
        for url in mime.urls():
            src = Path(url.toLocalFile())
            if not src.exists():
                continue
            dest = self._unique_dest_path(src)
            try:
                if src.is_dir():
                    shutil.copytree(src, dest)
                else:
                    shutil.copy2(src, dest)
                last_dest = dest
            except OSError as exc:
                errors.append(f"{src.name} : {exc}")
        if errors:
            QMessageBox.warning(self, "Coller", "Impossible de coller :\n" + "\n".join(errors))
        self.refresh()
        if last_dest:
            for i in range(self.list.count()):
                it = self.list.item(i)
                if it.data(ROLE_PATH) == str(last_dest):
                    self.list.setCurrentItem(it)
                    break

    def _rename_item(self, path: Path):
        new_name, ok = QInputDialog.getText(
            self, "Renommer", "Nouveau nom :", QLineEdit.Normal, path.name
        )
        if not ok:
            return
        new_name = new_name.strip()
        if not new_name or new_name == path.name:
            return
        if any(ch in new_name for ch in '\\/:*?"<>|'):
            QMessageBox.warning(self, "Renommer", "Le nom contient des caracteres interdits.")
            return
        new_path = path.with_name(new_name)
        if new_path.exists():
            QMessageBox.warning(self, "Renommer", f"« {new_name} » existe deja.")
            return
        try:
            path.rename(new_path)
        except OSError as exc:
            QMessageBox.warning(self, "Renommer", f"Impossible de renommer :\n{exc}")
            return
        self.refresh()
        for i in range(self.list.count()):
            it = self.list.item(i)
            if it.data(ROLE_PATH) == str(new_path):
                self.list.setCurrentItem(it)
                break


# ==========================================================================
# Panneau de details
# ==========================================================================

class DetailPanel(QWidget):

    FIELDS = ["kind", "size", "modified", "path"]

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setStyleSheet(f"background: {C['detail_bg']};")
        self.setMinimumWidth(260)

        # Colonne juste a gauche (la derniere) : permet de la redimensionner
        # en attrapant la bordure depuis ce cote-ci aussi, puisqu'elle n'a
        # pas d'autre colonne voisine pour agrandir la zone de prise.
        self.left_column = None
        self.setMouseTracking(True)

        self.name = QLabel("")
        self.name.setFont(font(12, 600, tracking=0.12))
        self.name.setStyleSheet(f"color: {C['text']}; background: transparent;")

        self.well = QFrame()
        self.well.setFixedHeight(PREVIEW_MIN_HEIGHT)
        self.well.setStyleSheet(
            f"background: {C['well']}; border: 1px solid #282c30;"
        )
        self._preview_pixmap: QPixmap | None = None
        self.well_label = QLabel(self.well)
        self.well_label.setAlignment(Qt.AlignCenter)
        self.well_label.setStyleSheet("background: transparent; border: none;")
        well_layout = QVBoxLayout(self.well)
        well_layout.setContentsMargins(0, 0, 0, 0)
        well_layout.addWidget(self.well_label)

        grid = QGridLayout()
        grid.setContentsMargins(0, 0, 0, 0)
        grid.setHorizontalSpacing(12)
        grid.setVerticalSpacing(4)
        self.values: dict[str, QLabel] = {}
        for row, key in enumerate(self.FIELDS):
            key_label = QLabel(key)
            key_label.setFont(font(11, 400, mono=True))
            key_label.setStyleSheet(f"color: {C['dim']}; background: transparent;")
            value = QLabel("")
            value.setFont(font(11, 400, mono=True))
            value.setStyleSheet("color: #aab1b6; background: transparent;")
            value.setWordWrap(True)
            grid.addWidget(key_label, row, 0, Qt.AlignTop)
            grid.addWidget(value, row, 1)
            self.values[key] = value
        grid.setColumnStretch(1, 1)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 14, 16, 14)
        layout.setSpacing(8)
        layout.addWidget(self.name)
        layout.addWidget(self.well)
        layout.addLayout(grid)
        layout.addStretch(1)
        self.clear()

    # -- prolonge la poignee de redimensionnement de la derniere colonne --

    def mouseMoveEvent(self, event):
        col = self.left_column
        if col is None:
            return super().mouseMoveEvent(event)
        x = event.position().toPoint().x()
        if col.is_resizing:
            col.resize_update(event.globalPosition().toPoint().x())
            return
        if x <= COLUMN_RESIZE_MARGIN:
            self.setCursor(Qt.SizeHorCursor)
        else:
            self.unsetCursor()
        super().mouseMoveEvent(event)

    def mousePressEvent(self, event):
        col = self.left_column
        x = event.position().toPoint().x()
        if col is not None and event.button() == Qt.LeftButton and x <= COLUMN_RESIZE_MARGIN:
            col.resize_begin(event.globalPosition().toPoint().x())
            return
        super().mousePressEvent(event)

    def mouseReleaseEvent(self, event):
        col = self.left_column
        if col is not None and col.is_resizing:
            col.resize_end()
            return
        super().mouseReleaseEvent(event)

    def leaveEvent(self, event):
        col = self.left_column
        if col is None or not col.is_resizing:
            self.unsetCursor()
        super().leaveEvent(event)

    def clear(self):
        self.name.setText("")
        self.well.hide()
        self._preview_pixmap = None
        self.well.setFixedHeight(PREVIEW_MIN_HEIGHT)
        self.well_label.clear()
        for value in self.values.values():
            value.setText("")

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._update_preview()

    def _update_preview(self):
        if self._preview_pixmap is None:
            self.well.setFixedHeight(PREVIEW_MIN_HEIGHT)
            self.well_label.clear()
            return
        pw, ph = self._preview_pixmap.width(), self._preview_pixmap.height()
        if pw <= 0 or ph <= 0:
            self.well.setFixedHeight(PREVIEW_MIN_HEIGHT)
            self.well_label.clear()
            return
        # Largeur disponible = largeur du panneau moins ses marges (16 de
        # chaque cote). Jamais d'agrandissement au-dela de la taille reelle
        # de l'image, et jamais plus haut que PREVIEW_MAX_HEIGHT.
        avail_w = max(self.width() - 32, 50)
        scale = min(1.0, avail_w / pw, PREVIEW_MAX_HEIGHT / ph)
        final_w = max(1, round(pw * scale))
        final_h = max(1, round(ph * scale))
        self.well.setFixedHeight(max(final_h, PREVIEW_MIN_HEIGHT))
        scaled = self._preview_pixmap.scaled(
            final_w, final_h, Qt.KeepAspectRatio, Qt.SmoothTransformation
        )
        self.well_label.setPixmap(scaled)

    def show_path(self, path: Path):
        self.name.setText(path.name)
        self.well.show()
        self._preview_pixmap = None
        if not path.is_dir() and path.suffix.lower() in IMAGE_EXTENSIONS:
            pix = QPixmap(str(path))
            if not pix.isNull():
                self._preview_pixmap = pix
        self._update_preview()
        try:
            info = path.stat()
            modified = datetime.fromtimestamp(info.st_mtime).strftime("%Y-%m-%d %H:%M")
        except OSError:
            info, modified = None, "-"
        if path.is_dir():
            kind = "Dossier"
            size = f"{len(list_entries(path))} elements"
        else:
            kind = (path.suffix[1:].upper() + " file") if path.suffix else "Fichier"
            size = human_size(info.st_size) if info else "-"
        self.values["kind"].setText(kind)
        self.values["size"].setText(size)
        self.values["modified"].setText(modified)
        self.values["path"].setText(str(path))


# ==========================================================================
# Fenetre principale
# ==========================================================================

class PipelineBrowser(QMainWindow):

    def __init__(self, root: Path):
        super().__init__()
        self.setWindowTitle("Pipeline Browser")
        self.resize(1280, 620)
        self.columns: list[Column] = []

        # --- barre du haut ---
        root_label = QLabel("Root")
        root_label.setFont(font(10, 600, tracking=0.8, caps=True))
        root_label.setStyleSheet(f"color: {C['label']}; background: transparent;")

        self.root_field = QLineEdit(str(root))
        self.root_field.setFont(font(12, 400, mono=True))
        self.root_field.setFixedHeight(24)
        self.root_field.returnPressed.connect(self.reload)

        btn_browse = QPushButton("Parcourir")
        btn_reload = QPushButton("Refresh")
        for btn in (btn_browse, btn_reload):
            btn.setFont(font(11, 500))
            btn.setFixedHeight(24)
            btn.setCursor(Qt.ArrowCursor)
        btn_browse.clicked.connect(self.browse_root)
        btn_reload.clicked.connect(self.reload)

        self.synced_label = QLabel("")
        self.synced_label.setFont(font(10, 400, mono=True))
        self.synced_label.setStyleSheet(f"color: {C['dim']}; background: transparent;")

        topbar = QWidget()
        topbar.setFixedHeight(TOPBAR_HEIGHT)
        topbar.setStyleSheet(
            f"background: {C['topbar']}; border-bottom: 1px solid {C['border']};"
        )
        top_layout = QHBoxLayout(topbar)
        top_layout.setContentsMargins(10, 0, 10, 0)
        top_layout.setSpacing(10)
        top_layout.addWidget(root_label)
        top_layout.addWidget(self.root_field, 1)
        top_layout.addWidget(btn_browse)
        top_layout.addWidget(btn_reload)
        top_layout.addWidget(self.synced_label)

        # --- zone des colonnes ---
        self.columns_layout = QHBoxLayout()
        self.columns_layout.setContentsMargins(0, 0, 0, 0)
        self.columns_layout.setSpacing(0)

        self.detail = DetailPanel()

        columns_host = QWidget()
        host_layout = QHBoxLayout(columns_host)
        host_layout.setContentsMargins(0, 0, 0, 0)
        host_layout.setSpacing(0)
        host_layout.addLayout(self.columns_layout)
        host_layout.addWidget(self.detail, 1)

        self.scroll = QScrollArea()
        self.scroll.setFrameShape(QFrame.NoFrame)
        self.scroll.setWidgetResizable(True)
        self.scroll.setWidget(columns_host)
        self.scroll.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)

        # --- barre de statut ---
        self.path_label = QLabel("")
        self.path_label.setFont(font(11, 400, mono=True))
        self.path_label.setStyleSheet(f"color: {C['text_mono']}; background: transparent;")
        self.status_right = QLabel("read-only")
        self.status_right.setFont(font(11, 400, mono=True))
        self.status_right.setStyleSheet(f"color: {C['dim']}; background: transparent;")

        statusbar = QWidget()
        statusbar.setFixedHeight(STATUS_HEIGHT)
        statusbar.setStyleSheet(
            f"background: {C['chrome']}; border-top: 1px solid {C['border']};"
        )
        status_layout = QHBoxLayout(statusbar)
        status_layout.setContentsMargins(10, 0, 10, 0)
        status_layout.setSpacing(12)
        status_layout.addWidget(self.path_label)
        status_layout.addStretch(1)
        status_layout.addWidget(self.status_right)

        central = QWidget()
        central.setStyleSheet(f"background: {C['window']};")
        layout = QVBoxLayout(central)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        layout.addWidget(topbar)
        layout.addWidget(self.scroll, 1)
        layout.addWidget(statusbar)
        self.setCentralWidget(central)

        self.addAction(QAction(self, shortcut="F5", triggered=self.reload))
        self.reload()

    # -- gestion des colonnes ------------------------------------------

    def reload(self):
        root = Path(self.root_field.text())
        self.prune_after(-1)
        self.detail.clear()
        if not root.is_dir():
            self.path_label.setText(f"Introuvable : {root}")
            self.synced_label.setText("")
            return
        self.add_column(root, 0)
        self.path_label.setText(str(root))
        self.synced_label.setText(datetime.now().strftime("scan %H:%M:%S"))

    def add_column(self, directory: Path, depth: int):
        title = COLUMN_LABELS[depth] if depth < len(COLUMN_LABELS) else "Contenu"
        column = Column(directory, title)
        column.selected.connect(self.on_selected)
        column.activated.connect(self.on_activated)
        self.columns.append(column)
        self.columns_layout.addWidget(column)
        self.detail.left_column = column
        self.update_active_column()
        bar = self.scroll.horizontalScrollBar()
        bar.setValue(bar.maximum())

    def prune_after(self, index: int):
        while len(self.columns) > index + 1:
            column = self.columns.pop()
            self.columns_layout.removeWidget(column)
            column.setParent(None)
            column.deleteLater()
        self.detail.left_column = self.columns[-1] if self.columns else None

    def refresh_all_columns(self):
        for column in self.columns:
            column.refresh()

    def update_active_column(self):
        last_selected = -1
        for i, column in enumerate(self.columns):
            if column.current_path() is not None:
                last_selected = i
        for i, column in enumerate(self.columns):
            column.set_active(i == last_selected)

    def on_selected(self, column: Column, path: Path | None):
        index = self.columns.index(column)
        self.prune_after(index)
        if path is None:
            self.detail.clear()
            self.update_active_column()
            return
        self.path_label.setText(str(path))
        self.detail.show_path(path)
        if path.is_dir():
            self.add_column(path, index + 1)
        self.update_active_column()

    def on_activated(self, path: Path):
        open_path(path)

    def browse_root(self):
        chosen = QFileDialog.getExistingDirectory(
            self, "Racine du pipeline", self.root_field.text()
        )
        if chosen:
            self.root_field.setText(chosen)
            self.reload()


def main():
    app = QApplication(sys.argv)
    apply_style(app)
    window = PipelineBrowser(ROOT)
    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
