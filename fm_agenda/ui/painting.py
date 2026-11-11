"""Peinture des événements, d'après le design : bloc horaire (`.ev` : filet gauche 3 px, arrondi 4, heure 11 px à
85 %, titre 12 px 600, sous-titre 11 px), barre « journée » (`.ad` : 12 px 600, arrondi 4), pastille du mois
(`.chip`). Sélection = anneau de 2 px d'accent ; survol = `brightness(1.1)`."""
from __future__ import annotations

from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import QColor, QPainter, QPainterPath, QPen

from . import theme as th
from .widgets import brighter, draw_icon, elide, paint_check


def wrap_lines(text: str, px: int, weight: int, width: float, max_lines: int) -> list[str]:
    """Retour à la ligne par mots ; la dernière ligne permise est tronquée (…)."""
    if max_lines <= 0 or width <= 4:
        return []
    fm = th.metrics(px, weight)
    words = text.split()
    lines, cur = [], ""
    for i, w in enumerate(words):
        trial = (cur + " " + w).strip()
        if fm.horizontalAdvance(trial) <= width or not cur:
            cur = trial
            continue
        lines.append(cur)
        cur = w
        if len(lines) == max_lines - 1:
            cur = " ".join([cur] + words[i + 1:])
            break
    if cur:
        lines.append(cur)
    if len(lines) > max_lines:
        lines = lines[:max_lines]
    if lines:
        lines[-1] = elide(lines[-1], px, weight, width)
    return lines


def _ring(p: QPainter, rect: QRectF, radius: float, color: QColor) -> None:
    p.setPen(QPen(color, 2))
    p.setBrush(Qt.NoBrush)
    p.drawRoundedRect(rect.adjusted(-1, -1, 1, 1), radius + 1, radius + 1)


def paint_event_block(p: QPainter, rect: QRectF, colors, title: str, time_text: str, sub: str, one_line: bool,
                      selected: bool, hover: bool, accent: QColor, task: bool = False, done: bool = False,
                      dim: float = 1.0, tentative: bool = False) -> None:
    bg, bar, fg = colors
    if hover:
        bg, bar, fg = brighter(bg, 1.1), brighter(bar, 1.1), brighter(fg, 1.1)
    p.save()
    p.setOpacity(dim)
    p.setRenderHint(QPainter.Antialiasing, True)
    path = QPainterPath()
    path.addRoundedRect(rect, 4, 4)
    p.setClipPath(path)
    p.fillRect(rect, bg)
    if tentative:
        p.setPen(QPen(th.with_alpha(bar, 0.35), 1))
        step = 6
        x = rect.left() - rect.height()
        while x < rect.right():
            p.drawLine(int(x), int(rect.bottom()), int(x + rect.height()), int(rect.top()))
            x += step
    p.fillRect(QRectF(rect.left(), rect.top(), 3, rect.height()), bar)
    p.setClipping(False)
    inner = rect.adjusted(3 + 6, 3, -6, -3)
    text_fg = th.with_alpha(fg, 0.55) if done else fg
    soft = th.with_alpha(fg, 0.85 * (0.6 if done else 1.0))
    x = inner.left()
    if one_line:
        cy = rect.center().y()
        if task:
            box = QRectF(x, cy - 4, 8, 8)
            p.setPen(QPen(text_fg, 1.5))
            p.setBrush(Qt.NoBrush)
            p.drawRoundedRect(box, 2, 2)
            if done:
                draw_icon(p, "check", box.adjusted(-1, -1, 1, 1), text_fg, 2.4)
            x += 8 + 5
        p.setFont(th.font(11))
        p.setPen(soft)
        tw = th.metrics(11).horizontalAdvance(time_text) if time_text else 0
        if time_text:
            p.drawText(QRectF(x, rect.top(), tw + 1, rect.height()), Qt.AlignVCenter | Qt.AlignLeft, time_text)
            x += tw + 5
        avail = inner.right() - x
        if avail > 6:
            f = th.font(12, 600)
            f.setStrikeOut(done)
            p.setFont(f)
            p.setPen(text_fg)
            p.drawText(QRectF(x, rect.top(), avail, rect.height()), Qt.AlignVCenter | Qt.AlignLeft,
                       elide(title, 12, 600, avail))
    else:
        y = inner.top()
        if time_text:
            p.setFont(th.font(11))
            p.setPen(soft)
            p.drawText(QRectF(x, y, inner.width(), 15), Qt.AlignLeft | Qt.AlignVCenter,
                       elide(time_text, 11, 400, inner.width()))
            y += 15
        room = int((inner.bottom() - y) // 15)
        sub_room = 1 if sub and room >= 2 else 0
        lines = wrap_lines(title or "(Sans titre)", 12, 600, inner.width(), max(1, room - sub_room))
        f = th.font(12, 600)
        f.setStrikeOut(done)
        p.setFont(f)
        p.setPen(text_fg)
        for line in lines:
            if y + 13 > rect.bottom():
                break
            p.drawText(QRectF(x, y, inner.width(), 15), Qt.AlignLeft | Qt.AlignVCenter, line)
            y += 15
        if sub_room and y + 2 + 13 <= rect.bottom():
            p.setFont(th.font(11))
            p.setPen(soft)
            p.drawText(QRectF(x, y + 2, inner.width(), 15), Qt.AlignLeft | Qt.AlignVCenter,
                       elide(sub, 11, 400, inner.width()))
    if selected:
        _ring(p, rect, 4, accent)
    p.restore()


def paint_bar(p: QPainter, rect: QRectF, colors, title: str, selected: bool, hover: bool, accent: QColor,
              cut_left: bool = False, cut_right: bool = False, dim: float = 1.0, task: bool = False,
              done: bool = False) -> None:
    """Barre « journée » (`.ad`) : fond et texte de la famille, 12 px 600, padding 3 × 8. Tâche : case à cocher
    (22 px cliquables à gauche, `timegrid._AllDayBand`) et titre barré une fois terminée."""
    bg, _bar, fg = colors
    if hover:
        bg, fg = brighter(bg, 1.1), brighter(fg, 1.1)
    p.save()
    p.setOpacity(dim)
    p.setRenderHint(QPainter.Antialiasing, True)
    r = 4
    from .widgets import rounded_path
    path = rounded_path(rect, (0 if cut_left else r, 0 if cut_right else r, 0 if cut_right else r,
                               0 if cut_left else r))
    p.fillPath(path, bg)
    p.setFont(th.font(12, 600))
    p.setPen(fg)
    left = rect.left() + 8 + (6 if cut_left else 0)
    if cut_left:
        draw_icon(p, "prev", QRectF(rect.left() + 1, rect.center().y() - 5, 10, 10), fg, 1.8)
    right_pad = 8 + (6 if cut_right else 0)
    avail = rect.right() - right_pad - left
    if cut_right:
        draw_icon(p, "next", QRectF(rect.right() - 11, rect.center().y() - 5, 10, 10), fg, 1.8)
    font = th.font(12, 600)
    if task:
        paint_check(p, QRectF(left - 2, rect.center().y() - 6, 12, 12), done, _bar, fg, 3)
        left += 14
        avail -= 14
        if done:
            from PySide6.QtGui import QFont
            font = QFont(font)                         # copie : la police en cache est partagée
            font.setStrikeOut(True)
            fg = th.with_alpha(fg, 0.6)
    p.setFont(font)
    p.setPen(fg)
    p.drawText(QRectF(left, rect.top(), max(0.0, avail), rect.height()), Qt.AlignVCenter | Qt.AlignLeft,
               elide(title or "(Sans titre)", 12, 600, avail))
    if selected:
        p.setPen(QPen(accent, 2))
        p.setBrush(Qt.NoBrush)
        p.drawPath(path)
    p.restore()


def paint_chip(p: QPainter, rect: QRectF, t, colors, title: str, time_text: str, bar: bool, selected: bool,
               hover: bool, faded: bool = False, done: bool = False) -> None:
    """Pastille du mois (`.chip`) : point 6 px + heure (dim) + titre ; barre « journée » pleine."""
    bg, dot, fg = colors
    p.save()
    p.setRenderHint(QPainter.Antialiasing, True)
    if faded:
        p.setOpacity(0.6)
    if bar:
        fill = brighter(bg, 1.1) if hover else bg
        p.setPen(Qt.NoPen)
        p.setBrush(fill)
        p.drawRoundedRect(rect, 3, 3)
        p.setFont(th.font(11, 600))
        p.setPen(fg)
        p.drawText(rect.adjusted(4, 0, -4, 0), Qt.AlignVCenter | Qt.AlignLeft,
                   elide(title or "(Sans titre)", 11, 600, rect.width() - 8))
    else:
        if hover:
            p.setPen(Qt.NoPen)
            p.setBrush(t.c("btn"))
            p.drawRoundedRect(rect, 3, 3)
        x = rect.left() + 4
        p.setPen(Qt.NoPen)
        p.setBrush(dot)
        p.drawEllipse(QRectF(x, rect.center().y() - 3, 6, 6))
        x += 6 + 5
        p.setFont(th.font(11))
        if time_text:
            tw = th.metrics(11).horizontalAdvance(time_text)
            p.setPen(t.c("dim"))
            p.drawText(QRectF(x, rect.top(), tw + 1, rect.height()), Qt.AlignVCenter | Qt.AlignLeft, time_text)
            x += tw + 5
        f = th.font(11)
        f.setStrikeOut(done)
        p.setFont(f)
        p.setPen(t.c("off") if faded else t.c("text"))
        p.drawText(QRectF(x, rect.top(), rect.right() - x - 2, rect.height()), Qt.AlignVCenter | Qt.AlignLeft,
                   elide(title or "(Sans titre)", 11, 400, rect.right() - x - 2))
    if selected:
        p.setOpacity(1.0)
        _ring(p, rect, 3, t.c("accent"))
    p.restore()
