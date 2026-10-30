"""Textes du module Design : boîte de texte (`DesignTextItem` : largeur fixe, hauteur suivie du contenu, style de
la boîte, parties stylées `spans`, listes, contour, ombre) et son éditeur sur place (`_DesignText` : raccourcis de
style d'une partie, menus qui ne terminent pas l'édition). Sorti de `items.py` (taille des fichiers)."""
from __future__ import annotations

from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import (QBrush, QColor, QFont, QImage, QPainter, QPen, QPixmap, QTextBlockFormat, QTextCharFormat,
                           QTextCursor, QTextFormat, QTextOption)
from PySide6.QtWidgets import QGraphicsTextItem

from fm_miro.items import ITEM_CLASSES, _Text, text_font
from . import design_model as dm
from .items import ALIGN, DesignElement, shadow_extent
from .text_curve import curve_layout, paint_curve


class _DesignText(_Text):
    """Texte en cours d'édition : Ctrl+B / I / U et Ctrl+Maj+> / < stylent la PARTIE choisie du texte ; un menu de
    la barre contextuelle (couleur, police, taille) n'interrompt pas l'édition (il s'applique à la partie choisie)."""

    def paint(self, painter, option, widget=None):
        page = self.owner.parentItem()
        if (page is not None and getattr(page, "snapshot", None) is not None and not self.editing()
                and not self.owner.live):
            return                                  # zoom continu : dans l'image de la page
        if getattr(self.owner, "_curve", None) is not None and not self.editing():
            return                                  # texte courbé : peint par la boîte (text_curve.py)
        super().paint(painter, option, widget)

    def focusOutEvent(self, event):
        if event.reason() == Qt.PopupFocusReason and self.editing():
            QGraphicsTextItem.focusOutEvent(self, event)       # menu ouvert : l'édition continue
            return
        super().focusOutEvent(event)

    def keyPressEvent(self, event):
        mods, key = event.modifiers(), event.key()
        cursor = self.textCursor()
        if mods & Qt.ControlModifier and cursor.hasSelection():
            current = cursor.charFormat()
            fmt = QTextCharFormat()
            shift = bool(mods & Qt.ShiftModifier)
            if key == Qt.Key_B and not shift:
                fmt.setFontWeight(QFont.Normal if current.fontWeight() > QFont.Normal else QFont.Bold)
            elif key == Qt.Key_I and not shift:
                fmt.setFontItalic(not current.fontItalic())
            elif key == Qt.Key_U and not shift:
                fmt.setFontUnderline(not current.fontUnderline())
            elif shift and key in (Qt.Key_Greater, Qt.Key_Less, Qt.Key_Period, Qt.Key_Comma):
                size = current.intProperty(QTextFormat.FontPixelSize) or self.font().pixelSize() or 24
                k = 1.1 if key in (Qt.Key_Greater, Qt.Key_Period) else 1 / 1.1
                fmt.setProperty(QTextFormat.FontPixelSize, max(4, int(round(size * k))))
            else:
                fmt = None
            if fmt is not None:
                cursor.mergeCharFormat(fmt)
                self.setTextCursor(cursor)
                event.accept()
                return
        super().keyPressEvent(event)


def _list_style(kind: str):
    from PySide6.QtGui import QTextListFormat
    return QTextListFormat.ListDecimal if kind == "number" else QTextListFormat.ListDisc


def spans_of(document) -> list[dict]:
    """Parties stylées d'un document (gras, italique, souligné, taille posés sur une partie), fusionnées."""
    out = []
    block = document.begin()
    while block.isValid():
        it = block.begin()
        while not it.atEnd():
            fragment = it.fragment()
            fmt = fragment.charFormat()
            span = {}
            if fmt.hasProperty(QTextFormat.FontWeight):
                span["bold"] = fmt.fontWeight() > QFont.Normal
            if fmt.hasProperty(QTextFormat.FontItalic):
                span["italic"] = fmt.fontItalic()
            if fmt.hasProperty(QTextFormat.TextUnderlineStyle) or fmt.hasProperty(QTextFormat.FontUnderline):
                span["underline"] = fmt.fontUnderline()
            if fmt.hasProperty(QTextFormat.FontPixelSize):
                span["size"] = float(fmt.intProperty(QTextFormat.FontPixelSize))
            if fmt.hasProperty(QTextFormat.ForegroundBrush):
                color = fmt.foreground().color()
                span["color"] = color.name(QColor.HexArgb if color.alpha() < 255 else QColor.HexRgb)
            if fmt.hasProperty(QTextFormat.FontFamilies) and fmt.fontFamilies():
                span["family"] = str(fmt.fontFamilies()[0])
            if span:
                start, end = fragment.position(), fragment.position() + fragment.length()
                last = out[-1] if out else None
                if last is not None and last["end"] == start and {k: v for k, v in last.items()
                                                                   if k not in ("start", "end")} == span:
                    last["end"] = end
                else:
                    out.append({"start": start, "end": end, **span})
            it += 1
        block = block.next()
    return out


def apply_spans(document, spans: list[dict]):
    length = max(0, document.characterCount() - 1)
    for span in spans or []:
        start, end = min(span["start"], length), min(span["end"], length)
        if end <= start:
            continue
        cursor = QTextCursor(document)
        cursor.setPosition(start)
        cursor.setPosition(end, QTextCursor.KeepAnchor)
        fmt = QTextCharFormat()
        if "bold" in span:
            fmt.setFontWeight(QFont.Bold if span["bold"] else QFont.Normal)
        if "italic" in span:
            fmt.setFontItalic(span["italic"])
        if "underline" in span:
            fmt.setFontUnderline(span["underline"])
        if "size" in span:
            fmt.setProperty(QTextFormat.FontPixelSize, max(4, int(round(span["size"]))))
        if "color" in span:
            fmt.setForeground(QColor(span["color"]))
        if "family" in span:
            from fm_miro.items import resolve_family
            fmt.setFontFamilies([resolve_family(span["family"])])
        cursor.mergeCharFormat(fmt)


class DesignTextItem(DesignElement):
    """Boîte de texte : largeur fixe, hauteur suivie du contenu ; un style pour la boîte, et des parties stylées
    (`spans`) posées pendant l'édition."""
    TEXT_KEY = "text"

    def __init__(self, data: dict):
        super().__init__(data)
        # Texte d'édition propre au module (raccourcis de style d'une partie) à la place de celui du board.
        old = self.text_item
        old.document().contentsChanged.disconnect(self.text_changed)
        old.setParentItem(None)
        self.text_item = _DesignText(self)
        self._spans_applied = None
        self._place_from_data()

    def _place_from_data(self):
        super()._place_from_data()
        item = self.text_item
        if item is None or not isinstance(item, _DesignText):
            return
        spans = self.data.get("spans") or []
        if spans_of(item.document()) != spans:
            if self._spans_applied is not None or spans:
                self._laying = True
                try:
                    item.setPlainText(str(self.data.get("text", "")))
                    # setPlainText garde le format du curseur d'édition (une partie en gras s'étendait à tout le
                    # texte) : formats remis à zéro, puis les parties stylées.
                    cursor = QTextCursor(item.document())
                    cursor.select(QTextCursor.Document)
                    cursor.setCharFormat(QTextCharFormat())
                    item.setTextCursor(QTextCursor(item.document()))
                    apply_spans(item.document(), spans)
                finally:
                    self._laying = False
                self._format_key = None
                self.layout_text()
            self._spans_applied = spans

    def to_dict(self) -> dict:
        data = super().to_dict()
        if isinstance(self.text_item, _DesignText):
            data["spans"] = spans_of(self.text_item.document())
        return data

    def layout_text(self):
        item = self.text_item
        if item is None:
            return
        data = self.data
        size = float(data.get("font_size", 48.0))
        font = text_font(data, size)
        font.setLetterSpacing(QFont.AbsoluteSpacing, size * float(data.get("letter_spacing", 0.0)) / 1000.0)
        if data.get("uppercase"):
            font.setCapitalization(QFont.AllUppercase)
        item.setFont(font)
        item.setDefaultTextColor(QColor(data.get("color", dm.INK)))
        option = QTextOption(ALIGN.get(data.get("align", "left"), Qt.AlignLeft))
        option.setWrapMode(QTextOption.WrapAtWordBoundaryOrAnywhere)
        document = item.document()
        document.setDefaultTextOption(option)
        item.setTextWidth(max(8.0, float(data.get("w", 100.0))))
        stroke = (data.get("text_stroke") or dm.INK, float(data.get("text_stroke_width", 0.0) or 0.0))
        key = (float(data.get("line_height", 1.2)), data.get("text_bg") or "", item.toPlainText(), stroke,
               data.get("list") or "")
        if getattr(self, "_format_key", None) != key:
            self._format_key = key
            cursor = QTextCursor(document)
            cursor.select(QTextCursor.Document)
            block = QTextBlockFormat()
            block.setLineHeight(key[0] * 100.0, QTextBlockFormat.ProportionalHeight.value
                                if hasattr(QTextBlockFormat.ProportionalHeight, "value")
                                else int(QTextBlockFormat.ProportionalHeight))
            cursor.mergeBlockFormat(block)
            fmt = QTextCharFormat()
            fmt.setBackground(QColor(key[1]) if key[1] else QBrush(Qt.NoBrush))
            # Contour des lettres (effet « contour » / « creux » de Canva : épaisseur en px, couleur)
            fmt.setTextOutline(QPen(QColor(stroke[0]), stroke[1]) if stroke[1] > 0 else QPen(Qt.NoPen))
            cursor.mergeCharFormat(fmt)
            self._apply_list(document, key[4])
        item.setPos(0, 0)
        if self._layout_curve(document, font):
            return
        self._curve = None
        height = max(size * 0.8, document.size().height())
        if abs(height - float(data.get("h", 0.0))) > 0.01:
            self.prepareGeometryChange()
            data["h"] = round(height, 2)
            self.setTransformOriginPoint(float(data.get("w", 0.0)) / 2, height / 2)

    def _layout_curve(self, document, font) -> bool:
        """Texte courbé (hors édition) : lettres posées sur l'arc, boîte à la taille de l'arc ; False = texte droit."""
        curve = float(self.data.get("curve", 0.0) or 0.0)
        if abs(curve) < 1 or self.text_item.editing() or not self.text_item.toPlainText().strip():
            return False
        key = (self.text_item.toPlainText(), self._format_key, repr(spans_of(document)), curve, font.toString(),
               self.data.get("color"))                 # styles réels du document (posés après la boîte)
        kept = getattr(self, "_curve", None)
        if kept is None or kept[0] != key:
            glyphs, bounds = curve_layout(document, font, QColor(self.data.get("color", dm.INK)), curve)
            kept = self._curve = (key, glyphs, bounds)
        w, h = round(max(8.0, kept[2].width()), 2), round(max(8.0, kept[2].height()), 2)
        if abs(w - float(self.data.get("w", 0.0))) > 0.01 or abs(h - float(self.data.get("h", 0.0))) > 0.01:
            self.prepareGeometryChange()
            self.data["w"], self.data["h"] = w, h
            self.setTransformOriginPoint(w / 2, h / 2)
        return True

    def start_edit(self):
        super().start_edit()
        if getattr(self, "_curve", None) is not None:
            self.layout_text()                      # texte courbé : droit pendant l'édition (comme Canva)
            self.update()

    @staticmethod
    def _apply_list(document, kind: str):
        """Liste à puces / numérotée sur TOUS les paragraphes de la boîte (« » = aucune)."""
        block = document.begin()
        while block.isValid():
            current = block.textList()
            if current is not None and (not kind or current.format().style() != _list_style(kind)):
                current.remove(block)
                cursor = QTextCursor(block)
                fmt = block.blockFormat()
                fmt.setIndent(0)
                cursor.setBlockFormat(fmt)
            block = block.next()
        if kind:
            cursor = QTextCursor(document)
            cursor.select(QTextCursor.Document)
            if document.begin().textList() is None:
                from PySide6.QtGui import QTextListFormat
                fmt = QTextListFormat()
                fmt.setStyle(_list_style(kind))
                fmt.setIndent(1)
                cursor.createList(fmt)

    def paint_margin(self) -> QRectF:
        return self.content_rect().adjusted(*([-shadow_extent(self.data)] * 2 + [shadow_extent(self.data)] * 2))

    def paint_content(self, painter):
        if not self.text_item.toPlainText() and not self.text_item.editing():
            painter.setPen(QPen(QColor(0, 0, 0, 90), 1 / self._zoom(), Qt.DashLine))
            painter.setBrush(Qt.NoBrush)
            painter.drawRect(self.content_rect())
            return
        kept = getattr(self, "_curve", None)
        if kept is not None and not self.text_item.editing():
            paint_curve(painter, kept[1], -kept[2].topLeft(), self.data.get("shadow"))
            return
        shadow = self.data.get("shadow") or {}
        if shadow.get("enabled"):
            pixmap, rect = self._shadow_pixmap(shadow)
            painter.save()
            painter.setRenderHint(QPainter.SmoothPixmapTransform, True)
            painter.drawPixmap(rect.translated(float(shadow.get("dx", 0.0)), float(shadow.get("dy", 0.0))), pixmap,
                               QRectF(pixmap.rect()))
            painter.restore()

    def _shadow_pixmap(self, shadow) -> tuple[QPixmap, QRectF]:
        """Ombre du texte : le texte peint en basse résolution, teinté, flouté (réduction / agrandissement), gardé
        tant que texte, style et ombre ne changent pas. Peinte par l'élément : présente aussi à l'export."""
        blur = max(0.0, float(shadow.get("blur", 0.0)))
        document = self.text_item.document()
        rect = self.content_rect().adjusted(-blur * 1.5, -blur * 1.5, blur * 1.5, blur * 1.5)
        key = (self.text_item.toPlainText(), self._format_key, self.data.get("w"), self.data.get("font_size"),
               self.data.get("font_family"), self.data.get("bold"), self.data.get("italic"),
               self.data.get("letter_spacing"), self.data.get("uppercase"), self.data.get("align"),
               shadow.get("color"), blur)
        kept = getattr(self, "_shadow_kept", None)
        if kept is not None and kept[0] == key:
            return kept[1], rect
        k = min(1.0, 6.0 / blur) if blur > 0 else 1.0
        k = min(k, 800.0 / max(1.0, rect.width(), rect.height()))
        w, h = max(1, int(rect.width() * k) + 1), max(1, int(rect.height() * k) + 1)
        image = QImage(w, h, QImage.Format_ARGB32_Premultiplied)
        image.fill(Qt.transparent)
        p = QPainter(image)
        p.setRenderHint(QPainter.Antialiasing, True)
        p.scale(k, k)
        p.translate(-rect.topLeft())
        document.drawContents(p)
        p.setCompositionMode(QPainter.CompositionMode_SourceIn)
        p.fillRect(rect, QColor(shadow.get("color", "#59000000")))
        p.end()
        if blur > 0:
            small = image.scaled(max(1, w // 2), max(1, h // 2), Qt.IgnoreAspectRatio, Qt.SmoothTransformation)
            image = small.scaled(w, h, Qt.IgnoreAspectRatio, Qt.SmoothTransformation)
        pixmap = QPixmap.fromImage(image)
        self._shadow_kept = (key, pixmap)
        return pixmap, rect

    def finish_edit(self):
        """Fin de l'édition ; un texte vidé disparaît (comme dans Canva), dans une étape à lui."""
        super().finish_edit()
        if abs(float(self.data.get("curve", 0.0) or 0.0)) >= 1:
            self.layout_text()                      # de nouveau courbé
            self.update()
        if not (self.data.get("text") or "").strip():
            from PySide6.QtCore import QTimer
            QTimer.singleShot(0, self._drop_if_empty)

    def _drop_if_empty(self):
        scene = self.scene()
        if scene is not None and not (self.data.get("text") or "").strip() and not self.text_item.editing():
            scene.delete_items([self])


ITEM_CLASSES[dm.TEXT] = DesignTextItem
