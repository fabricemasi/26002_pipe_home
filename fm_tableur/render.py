"""Peinture des cellules (Qt) — UNE seule fonction pour la grille interactive (`grid.py`) et l'aperçu de l'élément
dans le Board (`board_item.py`) : quadrillage, fonds, textes (débordement sur les voisines vides comme Excel,
retour à la ligne, alignements, couleurs de format), bordures, fusions, mises en forme conditionnelles.

Fluidité : le texte affiché de chaque cellule (format appliqué) est GARDÉ (`DisplayCache`, vidé quand le classeur
change : révision du document ou nouveau calcul) ; polices et métriques gardées par (style, zoom). Seules les
cellules visibles sont peintes ; aucun widget par cellule.

Le CONTENU suit l'aspect d'Excel (fond blanc, quadrillage gris clair), comme le contenu du Board suit Miro ;
couleurs réglables (onglet Tableur des réglages, `LOOK`)."""
from __future__ import annotations

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QFont, QFontMetricsF, QPen, QStaticText, QTextOption, QTransform

from . import condfmt, numfmt, ops
from . import values as V


LOOK = {
    "background": "#ffffff", "grid": "#d9d9d9", "text": "#000000",
    "header_bg": "#f3f3f3", "header_text": "#5c5c5c", "header_line": "#d0d0d0",
    "header_sel_bg": "#d2d2d2", "header_sel_text": "#0f6b3b",
    "selection": "#107c41", "selection_fill": "#24107c41", "ref_colors": ["#3c78d8", "#e06666", "#8e63ce",
                                                                           "#38a169", "#d97706", "#0891b2"],
}
def look_from(settings: dict | None) -> dict:
    """Couleurs du contenu d'après les réglages (`tableur_<clé>` de `LOOK`) ; références « @… » de l'appli
    résolues ; teinte de la sélection dérivée de sa couleur."""
    look = dict(LOOK)
    for key in LOOK:
        value = (settings or {}).get("tableur_" + key)
        if isinstance(value, str) and value:
            if value.startswith("@"):
                try:
                    from app_style import resolve_color_ref
                    value = resolve_color_ref(value)
                except Exception:                          # noqa: BLE001 - référence inconnue : défaut
                    continue
            look[key] = value
    if (settings or {}).get("tableur_selection"):
        tint = QColor(look["selection"])
        tint.setAlpha(36)
        look["selection_fill"] = tint.name(QColor.HexArgb)
    return look


BORDER_WIDTHS = {"thin": 1.0, "hair": 0.6, "medium": 2.0, "thick": 3.0, "double": 3.0, "dashed": 1.0,
                 "dotted": 1.0, "mediumDashed": 2.0, "dashDot": 1.0, "mediumDashDot": 2.0, "dashDotDot": 1.0,
                 "mediumDashDotDot": 2.0, "slantDashDot": 2.0}
_PEN_STYLES = {"dashed": Qt.DashLine, "dotted": Qt.DotLine, "mediumDashed": Qt.DashLine, "dashDot": Qt.DashDotLine,
               "mediumDashDot": Qt.DashDotLine, "dashDotDot": Qt.DashDotDotLine,
               "mediumDashDotDot": Qt.DashDotDotLine, "hair": Qt.DotLine}
PT_TO_PX = 96.0 / 72.0


class DisplayCache:
    """Texte affiché / couleur / valeur / alignement implicite par cellule ; vidé quand le classeur change."""

    def __init__(self, book):
        self.book = book
        self._key = None
        self._items: dict = {}
        self.loc = numfmt.DEFAULT_LOCALE
        self.show_formulas = False
        self._plans: dict = {}
        self._plans_key = None
        self.formula_lang = "en"

    def _check(self):
        engine = self.book.engine
        key = (self.book.revision, getattr(engine, "last_ms", 0), id(self.loc), self.show_formulas)
        if key != self._key:
            self._key = key
            self._items = {}

    def clear(self):
        self._key = None

    def plans(self) -> dict:
        """Plans de dessin (voir `_plan`), vidés en même temps que les textes."""
        self._check()
        if len(self._plans) > 100_000 or self._plans_key is not self._items:
            self._plans = {}
            self._plans_key = self._items
        return self._plans

    def get(self, sheet, row, col):
        self._check()
        key = (sheet.uid, row, col)
        found = self._items.get(key)
        if found is None:
            text, color, value = ops.display_text(self.book, sheet, row, col, self.loc, self.show_formulas)
            if self.show_formulas and isinstance(value, str) and value.startswith("=") and text == value:
                from .formula_lang import to_local
                text = to_local(text, self.formula_lang)
            if isinstance(value, V.XLError) or isinstance(value, bool):
                align = "center"
            elif isinstance(value, (int, float)) and not (self.show_formulas and isinstance(value, str)):
                align = "right"
            else:
                align = "left"
            found = (text, color, value, align)
            if len(self._items) > 200_000:
                self._items.clear()
            self._items[key] = found
        return found


class FontCache:
    def __init__(self):
        self._fonts: dict = {}

    def font(self, book, style: dict, zoom: float):
        key = (style.get("font"), style.get("size"), style.get("bold"), style.get("italic"),
               style.get("underline"), style.get("strike"), round(zoom, 3), book.default_font)
        found = self._fonts.get(key)
        if found is None:
            family = style.get("font") or book.default_font[0]
            size = float(style.get("size") or book.default_font[1])
            font = QFont(family)
            font.setPixelSize(max(1, round(size * PT_TO_PX * zoom)))
            font.setBold(bool(style.get("bold")))
            font.setItalic(bool(style.get("italic")))
            font.setUnderline(bool(style.get("underline")))
            font.setStrikeOut(bool(style.get("strike")))
            found = (font, QFontMetricsF(font))
            if len(self._fonts) > 500:
                self._fonts.clear()
            self._fonts[key] = found
        return found


_FONTS = FontCache()


def fonts() -> FontCache:
    return _FONTS


class Span:
    """Lignes ou colonnes visibles d'une zone : liste de (indice, début en px, taille en px)."""
    __slots__ = ("items", "index")

    def __init__(self, items):
        self.items = items
        self.index = {i: (p, s) for i, p, s in items}


def visible_span(axis, first: int, start_px: float, limit_px: float, zoom: float, stop: int | None = None) -> Span:
    """Indices à partir de `first` dont le début est avant `limit_px` (en pixels de l'écran)."""
    items = []
    pos = start_px
    i = first
    end = axis.count if stop is None else min(axis.count, stop)
    while i < end and pos < limit_px:
        size = axis.size(i) * zoom
        if size > 0:
            items.append((i, pos, size))
        pos += size
        i += 1
    return Span(items)


def _border_pen(line, zoom: float) -> QPen:
    style, color = (line[0], line[1]) if isinstance(line, (list, tuple)) and len(line) >= 2 else ("thin", "#000000")
    pen = QPen(QColor(color or "#000000"), max(1.0, BORDER_WIDTHS.get(style, 1.0) * max(zoom, 0.5)))
    pen.setStyle(_PEN_STYLES.get(style, Qt.SolidLine))
    pen.setCapStyle(Qt.FlatCap)
    return pen


def paint_cells(painter, book, sheet, rows: Span, cols: Span, zoom: float, cache: DisplayCache, look=None,
                clip: QRectF | None = None, grid: bool | None = None):
    """Peint les cellules des lignes / colonnes visibles (positions déjà calculées en pixels)."""
    look = look or LOOK
    if not rows.items or not cols.items:
        return
    x0 = cols.items[0][1]
    y0 = rows.items[0][1]
    x1 = cols.items[-1][1] + cols.items[-1][2]
    y1 = rows.items[-1][1] + rows.items[-1][2]
    area = QRectF(x0, y0, x1 - x0, y1 - y0)
    if clip is not None:
        area = area.intersected(clip)
    painter.save()
    painter.setClipRect(area)
    painter.fillRect(area, QColor(look["background"]))
    styles = book.styles
    cells = sheet.cells
    r_first, r_last = rows.items[0][0], rows.items[-1][0]
    c_first, c_last = cols.items[0][0], cols.items[-1][0]
    merges = [m for m in sheet.merges if not (m[2] < r_first or m[0] > r_last or m[3] < c_first or m[1] > c_last)]
    show_grid = sheet.show_grid if grid is None else grid
    cond = condfmt.Evaluator(book, sheet, cache) if sheet.cond_formats else None
    # 1. quadrillage
    if show_grid:
        painter.setPen(QPen(QColor(look["grid"]), 1))
        for _c, x, w in cols.items:
            painter.drawLine(int(x + w) - 1 + 0.5, int(y0), int(x + w) - 1 + 0.5, int(y1))
        for _r, y, h in rows.items:
            painter.drawLine(int(x0), int(y + h) - 1 + 0.5, int(x1), int(y + h) - 1 + 0.5)
    # cellules à peindre : existantes visibles (+ styles de ligne / colonne pour les fonds)
    area_cells = (len(rows.items) * len(cols.items))
    visible = []
    if area_cells <= len(cells) * 2 or area_cells < 4000:
        get = cells.get
        for r, y, h in rows.items:
            for c, x, w in cols.items:
                cell = get((r, c))
                if cell is not None:
                    visible.append((r, c, cell, x, y, w, h))
    else:
        for (r, c), cell in cells.items():
            if r_first <= r <= r_last and c_first <= c <= c_last and r in rows.index and c in cols.index:
                ry, rh = rows.index[r]
                cx, cw = cols.index[c]
                visible.append((r, c, cell, cx, ry, cw, rh))
    has_axis_styles = bool(sheet.rows.styles or sheet.cols.styles)
    # 2. fonds
    fills = []
    if has_axis_styles:
        for r, y, h in rows.items:
            for c, x, w in cols.items:
                if (r, c) not in cells:
                    st = styles.get(sheet.style_index(r, c))
                    if st.get("fill"):
                        fills.append((QRectF(x, y, w, h), st["fill"]))
    for r, c, cell, x, y, w, h in visible:
        st = styles.get(cell.style)
        fill = st.get("fill")
        if cond is not None:
            fill = cond.fill(r, c) or fill
        if fill:
            fills.append((QRectF(x, y, w, h), fill))
    for m in merges:
        rect = _merge_rect(m, rows, cols, sheet, zoom)
        if rect is not None:
            st = styles.get(sheet.style_index(m[0], m[1]))
            fills.append((rect, st.get("fill") or look["background"]))
    for rect, color in fills:
        painter.fillRect(rect, QColor(color))
    if cond is not None:
        cond.paint_bars(painter, visible)
    # 3. textes
    merged_at = {(m[0], m[1]): m for m in merges}
    covered = set()
    for m in merges:
        for r in range(m[0], m[2] + 1):
            for c in range(m[1], m[3] + 1):
                if (r, c) != (m[0], m[1]):
                    covered.add((r, c))
    painted_anchors = set()
    if merges:
        for m in merges:                                 # ancre d'une fusion hors de l'écran : texte quand même
            if (m[0], m[1]) not in cells or m[0] < r_first or m[1] < c_first:
                cell = cells.get((m[0], m[1]))
                if cell is not None:
                    rect = _merge_rect(m, rows, cols, sheet, zoom)
                    if rect is not None:
                        _paint_text(painter, book, sheet, m[0], m[1], cell, rect, zoom, cache, look, cells,
                                    cols, None, cond)
                        painted_anchors.add((m[0], m[1]))
    spill_probe = book.engine is not None and book.engine.available
    for r, c, cell, x, y, w, h in visible:
        if (r, c) in covered or (r, c) in painted_anchors:
            continue
        m = merged_at.get((r, c))
        rect = _merge_rect(m, rows, cols, sheet, zoom) if m else QRectF(x, y, w, h)
        _paint_text(painter, book, sheet, r, c, cell, rect, zoom, cache, look, cells, cols,
                    None if m else (x1 if clip is None else min(x1, clip.right())), cond)
    if spill_probe:
        # valeurs DÉBORDÉES (tableaux dynamiques) : cellules vides du modèle qui ont une valeur du moteur
        anchors = getattr(book.engine, "_anchors", {}).get(sheet.uid)
        if anchors:
            for r, y, h in rows.items:
                for c, x, w in cols.items:
                    if (r, c) not in cells and (r, c) not in covered:
                        text, color, value, align = cache.get(sheet, r, c)
                        if text:
                            _draw_text(painter, book, {}, text, color, align, QRectF(x, y, w, h), zoom, look)
    # 4. bordures
    for r, c, cell, x, y, w, h in visible:
        st = styles.get(cell.style)
        if not (st.get("border_l") or st.get("border_r") or st.get("border_t") or st.get("border_b")):
            continue
        m = merged_at.get((r, c))
        rect = _merge_rect(m, rows, cols, sheet, zoom) if m else QRectF(x, y, w, h)
        for key, (ax, ay, bx, by) in (("border_t", (rect.left(), rect.top(), rect.right(), rect.top())),
                                      ("border_b", (rect.left(), rect.bottom() - 1, rect.right(), rect.bottom() - 1)),
                                      ("border_l", (rect.left(), rect.top(), rect.left(), rect.bottom())),
                                      ("border_r", (rect.right() - 1, rect.top(), rect.right() - 1, rect.bottom()))):
            line = st.get(key)
            if line:
                painter.setPen(_border_pen(line, zoom))
                painter.drawLine(QRectF(ax, ay, 0, 0).topLeft(), QRectF(bx, by, 0, 0).topLeft())
    painter.restore()


def _merge_rect(m, rows: Span, cols: Span, sheet, zoom) -> QRectF | None:
    """Rectangle d'une fusion à l'écran (même si son coin est hors de la zone visible)."""
    if m is None:
        return None
    r_ref, ry = rows.items[0][0], rows.items[0][1]
    c_ref, cx = cols.items[0][0], cols.items[0][1]
    top = ry + (sheet.rows.pos(m[0]) - sheet.rows.pos(r_ref)) * zoom
    left = cx + (sheet.cols.pos(m[1]) - sheet.cols.pos(c_ref)) * zoom
    height = (sheet.rows.pos(m[2] + 1) - sheet.rows.pos(m[0])) * zoom
    width = (sheet.cols.pos(m[3] + 1) - sheet.cols.pos(m[1])) * zoom
    return QRectF(left, top, width, height)


def _plan(book, sheet, r, c, cell, zoom, cache, look, cond):
    """Plan de dessin d'une cellule (texte, police, largeur, couleur, alignements, QStaticText préparé), GARDÉ dans
    le cache d'affichage : à la peinture suivante, plus aucun formatage ni objet Qt à refaire."""
    key = (sheet.uid, r, c, zoom)
    plans = cache.plans()
    plan = plans.get(key)
    if plan is not None:
        return plan
    text, color, value, align = cache.get(sheet, r, c)
    if not text:
        plans[key] = _EMPTY
        return _EMPTY
    style = book.styles.get(cell.style) if cell is not None and cell.style else \
        book.styles.get(sheet.style_index(r, c))
    if cond is not None:
        extra = cond.style(r, c)
        if extra:
            style = {**style, **extra}
    halign = style.get("halign") or "general"
    if halign == "general":
        halign = align
    font, metrics = _FONTS.font(book, style, zoom)
    wrap = bool(style.get("wrap"))
    if not wrap and "\n" in text:
        text = text.replace("\n", " ")
    width = metrics.horizontalAdvance(text)
    is_number = isinstance(value, (int, float)) and not isinstance(value, bool)
    pen = _color(color or style.get("color") or look["text"])
    static = None
    if not wrap:
        static = QStaticText(text)
        static.setTextFormat(Qt.PlainText)
        static.prepare(QTransform(), font)
    plan = (text, font, metrics, width, halign, style.get("valign") or "bottom", wrap, is_number, pen, static,
            float(style.get("indent") or 0) * 9 * zoom)
    plans[key] = plan
    return plan


_EMPTY = ("",)
_COLORS: dict = {}


def _color(name: str) -> QColor:
    found = _COLORS.get(name)
    if found is None:
        found = _COLORS[name] = QColor(name)
    return found


_H_FLAGS = {"left": int(Qt.AlignLeft), "center": int(Qt.AlignHCenter), "centerContinuous": int(Qt.AlignHCenter),
            "right": int(Qt.AlignRight), "justify": int(Qt.AlignJustify), "fill": int(Qt.AlignLeft)}
_V_FLAGS = {"top": int(Qt.AlignTop), "center": int(Qt.AlignVCenter), "bottom": int(Qt.AlignBottom)}


def _paint_text(painter, book, sheet, r, c, cell, rect: QRectF, zoom, cache, look, cells, cols, right_limit, cond):
    plan = _plan(book, sheet, r, c, cell, zoom, cache, look, cond)
    if len(plan) == 1:
        return
    text, font, metrics, width, halign, valign, wrap, is_number, pen, static, indent = plan
    left, right = rect.left(), rect.right()
    pad = 3 * zoom
    if not wrap and width > rect.width() - 2 * pad:
        if is_number and "E" not in text and not cache.show_formulas:
            hkey = (sheet.uid, r, c, zoom, "#", int(rect.width()))     # « #### » gardé aussi
            plans = cache.plans()
            found = plans.get(hkey)
            if found is None:
                hashes = "#" * max(1, int((rect.width() - 2 * pad) // max(1.0, metrics.horizontalAdvance("#"))))
                found = plans[hkey] = (hashes, metrics.horizontalAdvance(hashes))
            text, width = found
            static = None
        elif right_limit is not None and halign in ("left", "fill") and not is_number:
            nxt = c + 1                                   # débordement sur les cellules vides à droite (Excel)
            while right - left < width + 2 * pad and nxt <= c + 60:
                if (r, nxt) in cells:
                    break
                right += sheet.cols.size(nxt) * zoom
                nxt += 1
        elif halign == "right" and not is_number:
            prv = c - 1
            while right - left < width + 2 * pad and prv >= 0 and prv >= c - 60:
                if (r, prv) in cells:
                    break
                left -= sheet.cols.size(prv) * zoom
                prv -= 1
        elif halign == "center" and not is_number:
            extra = (width + 2 * pad - rect.width()) / 2
            left -= extra
            right += extra
    painter.setFont(font)
    painter.setPen(pen)
    inner = QRectF(left + pad + (indent if halign == "left" else 0), rect.top() + zoom,
                   (right - left) - 2 * pad - indent, rect.height() - 2 * zoom)
    if wrap:
        option = QTextOption(Qt.Alignment(_H_FLAGS.get(halign, 1) | _V_FLAGS.get(valign, 64)))
        option.setWrapMode(QTextOption.WordWrap)
        painter.drawText(inner, text, option)
        return
    if halign in ("right",):
        x = inner.right() - width
    elif halign in ("center", "centerContinuous"):
        x = inner.left() + (inner.width() - width) / 2
    else:
        x = inner.left()
    height = metrics.height()
    if valign == "top":
        y = inner.top()
    elif valign == "center":
        y = inner.top() + (inner.height() - height) / 2
    else:
        y = inner.bottom() - height
    overflow = width > inner.width() + 0.5 or height > inner.height() + 2
    if overflow:
        painter.save()
        painter.setClipRect(QRectF(left, rect.top(), right - left, rect.height()), Qt.IntersectClip)
    if static is not None:
        painter.drawStaticText(QPointF(x, y), static)
    else:
        painter.drawText(QPointF(x, y + metrics.ascent()), text)
    if overflow:
        painter.restore()


def _draw_text(painter, book, style, text, color, halign, rect: QRectF, zoom, look, font=None, metrics=None):
    """Texte simple (valeurs débordées des tableaux dynamiques)."""
    if font is None:
        font, metrics = _FONTS.font(book, style, zoom)
    painter.setFont(font)
    painter.setPen(_color(color or style.get("color") or look["text"]))
    flags = _H_FLAGS.get(halign, 1) | int(Qt.AlignBottom) | int(Qt.TextSingleLine)
    painter.drawText(rect.adjusted(3 * zoom, zoom, -3 * zoom, -zoom), flags, text)


def text_size(book, style: dict, text: str, zoom: float = 1.0):
    """(largeur, hauteur) d'un texte dans le style d'une cellule (ajustement automatique)."""
    _font, metrics = _FONTS.font(book, style, zoom)
    lines = text.split("\n") if style.get("wrap") else [text]
    return max(metrics.horizontalAdvance(t) for t in lines), metrics.height() * len(lines)
