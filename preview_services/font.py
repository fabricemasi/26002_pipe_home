"""Aperçus des polices.

Carte et pièges : docs/agents/apercus.md.
"""

import threading
from pathlib import Path
from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QFont, QFontDatabase, QImage, QPainter

_FONT_RENDER_LOCK = threading.Lock()

def _decode_font_image(path: Path, max_dim: int) -> QImage | None:
    """Planche d'echantillons d'une police (.ttf/.otf...) : nom, "Aa",
    alphabet, chiffres et phrase en plusieurs tailles. La police est chargee
    le temps du rendu puis retiree (aucune installation systeme)."""
    width = max(480, min(max_dim, 1100))
    height = round(width * 0.75)
    with _FONT_RENDER_LOCK:
        font_id = QFontDatabase.addApplicationFont(str(path))
        if font_id < 0:
            return None
        try:
            families = QFontDatabase.applicationFontFamilies(font_id)
            if not families:
                return None
            family = families[0]
            image = QImage(width, height, QImage.Format_ARGB32)
            image.fill(QColor("#f4f4f2"))
            painter = QPainter(image)
            try:
                painter.setRenderHint(QPainter.Antialiasing, True)
                painter.setRenderHint(QPainter.TextAntialiasing, True)
                painter.setPen(QColor("#1c1c1c"))
                margin = round(width * 0.05)
                inner = width - 2 * margin
                y = margin

                def _line(text: str, px: int, fam: str = family) -> None:
                    nonlocal y
                    font = QFont(fam)
                    font.setPixelSize(max(6, px))
                    painter.setFont(font)
                    metrics = painter.fontMetrics()
                    text = metrics.elidedText(text, Qt.ElideRight, inner)
                    y += metrics.ascent()
                    painter.drawText(margin, y, text)
                    y += metrics.descent() + round(px * 0.35)

                _line("Aa", round(width * 0.2))
                painter.setPen(QColor("#6a6a6a"))
                _line(family, round(width * 0.035))
                painter.setPen(QColor("#1c1c1c"))
                _line("ABCDEFGHIJKLMNOPQRSTUVWXYZ", round(width * 0.05))
                _line("abcdefghijklmnopqrstuvwxyz", round(width * 0.05))
                _line("0123456789 !?&@#%()[]{}", round(width * 0.05))
                _line("Portez ce vieux whisky au juge blond qui fume", round(width * 0.032))
                _line("The quick brown fox jumps over the lazy dog", round(width * 0.022))
            finally:
                painter.end()
            return image
        finally:
            QFontDatabase.removeApplicationFont(font_id)
