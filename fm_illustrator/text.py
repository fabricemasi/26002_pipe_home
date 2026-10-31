"""Texte du module Illustrator (Qt) : mise en page des trois modes, chemin des lettres, SVG, vectorisation, éditeur
sur place.

Mise en page faite avec une police de BASE de 100 px (`BASE`), puis mise à l'échelle de la taille voulue : le rendu ne
dépend ni de l'écran ni de son DPI (une taille en points convertie par Qt suivrait le DPI de l'écran).
- point : lignes séparées par « \\n », origine = ligne de base du 1er trait ; alignement autour de l'origine ;
- captif (« area ») : retour à la ligne aux espaces dans la largeur `w` ; ce qui dépasse la hauteur `h` n'est pas
  dessiné (`overflow`, signalé par l'overlay comme le « + » rouge d'Illustrator) ; justifié = espaces élargis sauf la
  dernière ligne d'un paragraphe ;
- sur tracé (« path ») : chaque lettre posée sur le tracé de base (1er sous-tracé), tournée selon la tangente
  (repris de l'idée de `fm_design/text_curve.py`), depuis `path_offset` ; ce qui dépasse la fin n'est pas dessiné.
Le chemin des lettres sert au rendu (fond, contour, dégradés comme un tracé), à la vectorisation (Ctrl+Maj+O) et à
l'aperçu ; il est refait seulement quand le texte ou son style change (`IllTextItem.sync`)."""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from xml.sax.saxutils import escape, quoteattr

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QFont, QFontMetricsF, QPainterPath, QTextOption, QTransform
from PySide6.QtWidgets import QGraphicsItem, QGraphicsTextItem

from . import bezier as bz

BASE = 100.0                            # taille de la police de mise en page (px)


@dataclass
class Layout:
    path: QPainterPath
    box: QRectF                          # cadre (repère de l'élément) : sélection, zone cliquable
    lines: list = field(default_factory=list)   # [(texte, x, ligne de base)] (point / captif), repère de l'élément
    overflow: bool = False
    ascent: float = 0.0                  # hauteurs à la taille réelle
    descent: float = 0.0


_FONTS: dict = {}


def base_font(data: dict, tracking: bool = True) -> QFont:
    from fm_miro.items import resolve_family
    key = (data.get("font_family") or "", bool(data.get("bold")), bool(data.get("italic")),
           float(data.get("tracking", 0.0)) if tracking else 0.0)
    font = _FONTS.get(key)
    if font is None:
        font = QFont(resolve_family(key[0]))
        font.setPixelSize(int(BASE))
        font.setBold(key[1])
        font.setItalic(key[2])
        font.setKerning(True)
        if key[3]:
            font.setLetterSpacing(QFont.AbsoluteSpacing, key[3] / 1000.0 * BASE)
        _FONTS[key] = font
    return QFont(font)


def layout(data: dict) -> Layout:
    mode = data.get("mode", "point")
    if mode == "path" and data.get("subpaths"):
        return _layout_path(data)
    font = base_font(data)
    metrics = QFontMetricsF(font)
    k = float(data.get("font_size", 16.0)) / BASE
    ascent, descent = metrics.ascent() * k, metrics.descent() * k
    step = float(data.get("leading", 1.2)) * float(data.get("font_size", 16.0))
    text = str(data.get("text", ""))
    align = data.get("align", "left")
    base = QPainterPath()
    base.setFillRule(Qt.WindingFill)
    lines = []
    overflow = False
    if mode == "area":
        width = float(data.get("w", 200.0))
        height = float(data.get("h", 100.0))
        rows = _wrap(text, metrics, width / k)
        y = ascent
        for words, last in rows:
            if y + descent > height + 1e-6:
                overflow = True
                break
            _place_words(base, font, metrics, words, last, align, width / k, y / k, lines, k)
            y += step
        box = QRectF(0, 0, width, height)
    else:
        rows = text.split("\n")
        widths = [metrics.horizontalAdvance(r) for r in rows]
        left = right = 0.0
        for n, (row, w) in enumerate(zip(rows, widths)):
            x = 0.0 if align in ("left", "justify") else (-w / 2 if align == "center" else -w)
            baseline = n * step / k
            base.addText(x, baseline, font, row)
            lines.append((row, x * k, baseline * k))
            left, right = min(left, x * k), max(right, (x + w) * k)
        box = QRectF(left, -ascent, max(right - left, k * 2), (len(rows) - 1) * step + ascent + descent)
    path = QTransform.fromScale(k, k).map(base)
    return Layout(path, box, lines, overflow, ascent, descent)


def _wrap(text: str, metrics: QFontMetricsF, width: float) -> list[tuple[list[str], bool]]:
    """Lignes d'un texte captif : [(mots, dernière ligne du paragraphe)] ; un mot plus long que la ligne reste seul."""
    rows = []
    space = metrics.horizontalAdvance(" ")
    for paragraph in text.split("\n"):
        words = paragraph.split(" ")
        current: list[str] = []
        used = 0.0
        for word in words:
            w = metrics.horizontalAdvance(word)
            if current and used + space + w > width:
                rows.append((current, False))
                current, used = [word], w
            else:
                used = w if not current else used + space + w
                current.append(word)
        rows.append((current, True))
    return rows


def _place_words(base, font, metrics, words, last, align, width, baseline, lines, k):
    space = metrics.horizontalAdvance(" ")
    widths = [metrics.horizontalAdvance(w) for w in words]
    total = sum(widths) + space * max(0, len(words) - 1)
    gap = space
    if align == "justify" and not last and len(words) > 1:
        gap = (width - sum(widths)) / (len(words) - 1)
        x = 0.0
    else:
        x = 0.0 if align in ("left", "justify") else ((width - total) / 2 if align == "center" else width - total)
    lines.append((" ".join(words), x * k, baseline * k))
    if gap == space:                                    # pas justifiée : la ligne d'un coup (un appel par mot
        base.addText(x, baseline, font, " ".join(words))     # coûtait ~40 ms pour 300 mots)
        return
    for word, w in zip(words, widths):
        base.addText(x, baseline, font, word)
        x += w + gap


def _baseline(subs) -> tuple[list, list]:
    pts = bz.flatten(subs[0], 0.2)
    lengths = [0.0]
    for i in range(1, len(pts)):
        lengths.append(lengths[-1] + math.dist(pts[i - 1], pts[i]))
    return pts, lengths


def _point_at(pts, lengths, s):
    """(point, angle en degrés) à la distance `s` le long de la ligne brisée."""
    if s <= 0:
        i = 1
    else:
        i = 1
        while i < len(lengths) - 1 and lengths[i] < s:
            i += 1
    a, b = pts[i - 1], pts[i]
    seg = max(lengths[i] - lengths[i - 1], 1e-9)
    t = (s - lengths[i - 1]) / seg
    p = (a[0] + (b[0] - a[0]) * t, a[1] + (b[1] - a[1]) * t)
    return p, math.degrees(math.atan2(b[1] - a[1], b[0] - a[0]))


def _layout_path(data: dict) -> Layout:
    font = base_font(data, tracking=False)
    metrics = QFontMetricsF(font)
    size = float(data.get("font_size", 16.0))
    k = size / BASE
    extra = float(data.get("tracking", 0.0)) / 1000.0 * size
    subs = data["subpaths"]
    pts, lengths = _baseline(subs)
    total = lengths[-1] if lengths else 0.0
    text = str(data.get("text", "")).replace("\n", " ")
    advances = [metrics.horizontalAdvance(ch) * k + extra for ch in text]
    run = sum(advances)
    start = float(data.get("path_offset", 0.0)) * total
    align = data.get("align", "left")
    if align == "center":
        start += (total - start - run) / 2
    elif align == "right":
        start = total - run
    path = QPainterPath()
    path.setFillRule(Qt.WindingFill)
    s = start
    overflow = False
    for ch, adv in zip(text, advances):
        mid = s + adv / 2
        if mid > total + 1e-6 or len(pts) < 2:
            overflow = True
            break
        if mid >= 0 and ch.strip():
            (px, py), angle = _point_at(pts, lengths, mid)
            glyph = QPainterPath()
            glyph.addText(-metrics.horizontalAdvance(ch) / 2, 0.0, font, ch)
            t = QTransform()
            t.translate(px, py)
            t.rotate(angle)
            t.scale(k, k)
            path.addPath(t.map(glyph))
        s += adv
    box = path.boundingRect()
    line_box = bz.bounds(subs)
    if line_box is not None:
        box = box.united(QRectF(line_box[0], line_box[1], line_box[2] - line_box[0], line_box[3] - line_box[1]))
    return Layout(path, box, [], overflow, metrics.ascent() * k, metrics.descent() * k)


# ---------------------------------------------------------------- vectorisation
def outline_subpaths(path: QPainterPath) -> list[dict]:
    """Chemin Qt (lettres) -> sous-tracés du module (Créer les contours)."""
    subs: list[dict] = []
    cur = None
    i = 0
    count = path.elementCount()
    while i < count:
        e = path.elementAt(i)
        if e.type == QPainterPath.MoveToElement:
            cur = {"closed": False, "nodes": [bz.node(e.x, e.y)]}
            subs.append(cur)
            i += 1
        elif e.type == QPainterPath.LineToElement:
            cur["nodes"].append(bz.node(e.x, e.y))
            i += 1
        elif e.type == QPainterPath.CurveToElement:
            c2, end = path.elementAt(i + 1), path.elementAt(i + 2)
            prev = cur["nodes"][-1]
            prev[4], prev[5] = e.x, e.y
            cur["nodes"].append(bz.node(end.x, end.y, c2.x, c2.y))
            i += 3
        else:
            i += 1
    out = []
    for sub in subs:
        nodes = sub["nodes"]
        if len(nodes) > 2 and abs(nodes[0][0] - nodes[-1][0]) < 1e-6 and abs(nodes[0][1] - nodes[-1][1]) < 1e-6:
            last = nodes.pop()
            nodes[0][2], nodes[0][3] = last[2], last[3]
            sub["closed"] = True
        if len(nodes) > 1:
            out.append(sub)
    return out


# ---------------------------------------------------------------- SVG
def svg_text(data: dict, dx: float = 0.0, dy: float = 0.0) -> str:
    """Élément SVG d'un texte (texte modifiable : `<text>` / `<tspan>`, ou `<textPath>` pour un texte sur tracé)."""
    from .svg import _paint
    num = bz._num
    ox, oy = float(data.get("x", 0.0)) + dx, float(data.get("y", 0.0)) + dy
    size = float(data.get("font_size", 16.0))
    fill, fill_op = _paint(data.get("fill", ""))
    attrs = [f"font-family={quoteattr(base_font(data).family())}", f'font-size="{num(size)}"', f'fill="{fill}"']
    if fill != "none" and fill_op < 1:
        attrs.append(f'fill-opacity="{num(fill_op)}"')
    stroke, _op = _paint(data.get("stroke", ""))
    if stroke != "none":
        attrs.append(f'stroke="{stroke}" stroke-width="{num(float(data.get("stroke_width", 1.0)))}"')
    if data.get("bold"):
        attrs.append('font-weight="bold"')
    if data.get("italic"):
        attrs.append('font-style="italic"')
    if float(data.get("tracking", 0.0)):
        attrs.append(f'letter-spacing="{num(float(data["tracking"]) / 1000.0 * size)}"')
    if float(data.get("opacity", 1.0)) < 1:
        attrs.append(f'opacity="{num(float(data["opacity"]))}"')
    if data.get("mode") == "path" and data.get("subpaths"):
        pid = f"tracé-{data.get('id', 'texte')}"
        d = bz.svg_d(data["subpaths"][:1], ox, oy)
        offset = num(float(data.get("path_offset", 0.0)) * 100)
        return (f'<g><defs><path id={quoteattr(pid)} d="{d}"/></defs><text {" ".join(attrs)}>'
                f'<textPath href="#{escape(pid)}" startOffset="{offset}%">{escape(str(data.get("text", "")))}'
                f"</textPath></text></g>")
    rotation = float(data.get("rotation", 0.0))
    if rotation:
        attrs.append(f'transform="rotate({num(rotation)} {num(ox)} {num(oy)})"')
    spans = "".join(f'<tspan x="{num(ox + x)}" y="{num(oy + y)}">{escape(line)}</tspan>'
                    for line, x, y in layout(data).lines)
    return f'<text xml:space="preserve" {" ".join(attrs)}>{spans}</text>'


# ---------------------------------------------------------------- édition sur place
class TextEditor(QGraphicsTextItem):
    """Texte édité sur place : ENFANT de l'élément (même place, même rotation), police de base à l'échelle de la
    taille ; l'élément ne se peint pas pendant l'édition. Échap ou clic ailleurs = terminé (une étape)."""

    def __init__(self, ctl, owner):
        super().__init__(owner)
        self.ctl = ctl
        self.owner = owner
        data = owner.data
        k = float(data.get("font_size", 16.0)) / BASE
        self.setFont(base_font(data, tracking=data.get("mode") != "path"))
        from .items import qcolor
        self.setDefaultTextColor(qcolor(data.get("fill") or data.get("stroke") or "#000000"))
        self.document().setDocumentMargin(0)
        option = QTextOption(self.document().defaultTextOption())
        option.setAlignment({"center": Qt.AlignHCenter, "right": Qt.AlignRight,
                             "justify": Qt.AlignJustify}.get(data.get("align"), Qt.AlignLeft))
        self.document().setDefaultTextOption(option)
        self.setPlainText(str(data.get("text", "")))
        self.setScale(k)
        metrics = QFontMetricsF(self.font())
        mode = data.get("mode", "point")
        if mode == "area":
            self.setTextWidth(float(data.get("w", 200.0)) / k)
            self.setPos(0, 0)
        elif mode == "path" and data.get("subpaths"):
            n = data["subpaths"][0]["nodes"][0]
            self.setPos(n[0], n[1] - metrics.ascent() * k)
        else:
            self.setPos(owner.layout_box().left(), -metrics.ascent() * k)
        self.setTextInteractionFlags(Qt.TextEditorInteraction)
        self.setFlag(QGraphicsItem.ItemIsFocusable, True)
        self.setZValue(1)

    def editing(self) -> bool:
        return self.hasFocus()

    def keyPressEvent(self, event):
        if event.key() == Qt.Key_Escape:
            self.clearFocus()
            return
        super().keyPressEvent(event)

    def focusOutEvent(self, event):
        super().focusOutEvent(event)
        self.ctl.end_text_edit()

    def place_cursor(self, scene_pos: QPointF | None):
        cursor = self.textCursor()
        if scene_pos is None:
            cursor.movePosition(cursor.MoveOperation.End)
        else:
            local = self.mapFromScene(scene_pos)
            hit = self.document().documentLayout().hitTest(local, Qt.FuzzyHit)
            cursor.setPosition(max(0, hit))
        self.setTextCursor(cursor)
