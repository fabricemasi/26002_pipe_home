"""Cibles éditables des parties peintes, sans intercepter les clics du navigateur."""
from PySide6.QtCore import QPoint, QRect, Qt
from PySide6.QtWidgets import QWidget


class PaintedTarget(QWidget):
    def __init__(self, view, key, part, rect):
        super().__init__(view.viewport())
        self.view, self.key, self.part = view, key, part
        self.base = QRect(rect)
        self.setAttribute(Qt.WA_TransparentForMouseEvents)
        self.setAttribute(Qt.WA_NoSystemBackground)
        self.setGeometry(rect)
        self.show()

    def move(self, *args):
        position = QPoint(args[0]) if len(args) == 1 else QPoint(*args)
        offsets = getattr(self.view, "_edit_offsets", None)
        if offsets is None:
            offsets = self.view._edit_offsets = {}
        offsets.setdefault(self.key, {})[self.part] = position - self.base.topLeft()
        super().move(position)
        if self.part.startswith("gallery-") and hasattr(self.view, "invalidate_edited_cell"):
            self.view.invalidate_edited_cell(self.key)
        self.view.viewport().update()

    def sync(self, rect):
        offset = getattr(self.view, "_edit_offsets", {}).get(self.key, {}).get(self.part, QPoint())
        self.base = QRect(rect)
        self.setGeometry(self.base.translated(offset))


def prepare_row(view, index, rect, option):
    """Partage avec le mode édition les rectangles réellement peints."""
    from browser_core import ROLE_PATH
    key = str(index.data(ROLE_PATH) or index.row())
    offsets = getattr(view, "_edit_offsets", {}).get(key, {})
    geometry = getattr(view, "_edit_geometry", None)
    if geometry is None:
        geometry = view._edit_geometry = {}
    parts = geometry.setdefault(key, {})
    parts.clear()
    parts["row"] = QRect(rect)
    option._edit_parts = parts
    option._edit_offsets = offsets
    option._edit_text_offset = offsets.get("text", QPoint())
    return rect.translated(offsets.get("row", QPoint()))


def part_rect(option, part, rect):
    parts = getattr(option, "_edit_parts", None)
    if parts is not None:
        parts[part] = QRect(rect)
        return rect.translated(option._edit_offsets.get(part, QPoint()))
    return rect
