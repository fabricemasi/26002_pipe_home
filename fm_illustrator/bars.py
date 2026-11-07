"""Barres flottantes du module Illustrator (demande de l'utilisateur, 2026-11-02 : « les palettes d'outils des
différents modules doivent être remplacées, toutes »). Le système est celui de fm_theme (`fm_theme/bar_manager.py`,
`fm_theme/palette.py`) et de Miro (`fm_board/bars.py`) ; ce fichier n'apporte que ce qui est propre à Illustrator :

- `default_state()` : la disposition par défaut (clés = celles inscrites par `ui.IllustratorChrome`) ;
- `FillStrokeTool` : le témoin fond / contour d'Illustrator, case d'une barre (clic = premier plan, puis couleur) ;
- `StatusText` : le texte d'état de « Propriétés » (« 3 objets »), qui n'est pas un bouton.

Les barres elles-mêmes (`BoardBars(pane, "illustrator", …)`) et leurs éléments sont posés par `ui.py`."""
from __future__ import annotations

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QLinearGradient, QPainter, QPen

from fm_theme.palette import PaletteButton, PaletteTextButton

# Éléments par barre d'outils (clé de l'outil du contrôleur, `ctl.tools`), dans l'ordre d'Illustrator : une barre = un groupe
# de la boîte à outils ; le témoin fond / contour et l'échange ferment la dernière, comme au bas de la boîte à outils.
# La clé d'un élément est enregistrée dans la disposition de l'utilisateur : ne pas la renommer.
TOOL_BARS = [
    ("Sélection", ("select", "direct", "artboard", "hand", "zoom")),
    ("Tracé", ("pen", "add_anchor", "delete_anchor", "convert", "paintbrush", "blob", "width", "pencil")),
    ("Créer", ("type", "rect", "ellipse", "polygon", "star", "line")),
    ("Transformer", ("rotate", "scale", "reflect", "shape_builder", "gradient", "eyedropper", "fill_stroke", "swap")),
]


def _bar(bar_id: str, title: str, cells: list, cols: int, rows: int, **extra) -> dict:
    """Entrée d'état d'une barre ; `cells` = [(clé, colonne, ligne, largeur)]."""
    entry = {"id": bar_id, "title": title, "dock": None, "orient": "h", "along": 0, "x": 0, "y": 0, "cols": cols,
             "rows": rows, "items": {key: [col, row, width] for key, col, row, width in cells}}
    entry.update(extra)
    return entry


def _grid(keys: tuple, cols: int) -> tuple[list, int]:
    """Cases d'une série d'icônes rangées ligne par ligne sur `cols` colonnes : (cellules, nombre de lignes)."""
    cells = [(key, index % cols, index // cols, 1) for index, key in enumerate(keys)]
    return cells, -(-len(keys) // cols)


def default_state() -> dict:
    """Barres d'outils clipsées à gauche l'une derrière l'autre (`after`, deux colonnes), « Propriétés » et « Objet » en
    haut (à droite des outils), « Texte » flottante (visible seulement quand la sélection contient un texte)."""
    bars: list[dict] = []
    previous = ""
    for index, (title, keys) in enumerate(TOOL_BARS, 1):
        cells, rows = _grid(keys, 2)
        bar_id = f"b{index}"
        bars.append(_bar(bar_id, title, cells, 2, rows, dock="left", orient="v", along=16, after=previous))
        previous = bar_id
    bars.append(_bar("b5", "Propriétés", [("title", 0, 0, 3), ("fill", 3, 0, 1), ("stroke", 4, 0, 1),
                                          ("stroke_width", 5, 0, 2), ("opacity", 7, 0, 5)], 12, 1, dock="top", along=120))
    bars.append(_bar("b6", "Objet", [("object", 0, 0, 2), ("brush", 2, 0, 1), ("align", 3, 0, 1), ("pathfinder", 4, 0, 1),
                                     ("effects", 5, 0, 1), ("artboards", 6, 0, 3), ("layers", 9, 0, 1),
                                     ("export", 10, 0, 1)], 11, 1, dock="top", along=0, after="b5"))
    bars.append(_bar("b7", "Texte", [("font", 0, 0, 4), ("size", 4, 0, 2), ("paragraph", 6, 0, 3)], 9, 1, x=130, y=100))
    return {"next": 8, "bars": bars}


class StatusText(PaletteTextButton):
    """Texte d'état d'une barre (« 3 objets », « Aucune sélection ») : une case de texte qui n'est pas un bouton (ni survol,
    ni curseur de main) ; Ctrl + glisser la déplace comme les autres éléments."""

    def __init__(self, key: str, text: str, tip: str, parent=None, cells: int = 2):
        super().__init__(key, text, tip, parent, cells)
        self.setCursor(Qt.ArrowCursor)

    def underMouse(self) -> bool:
        return False


class FillStrokeTool(PaletteButton):
    """Témoin fond / contour d'Illustrator dans une case de barre : carré plein (fond) et carré évidé (contour), celui au
    premier plan dessus ; clic = le mettre au premier plan, clic sur celui qui y est déjà = choisir sa couleur ; « aucun » =
    barre rouge. `values()` rend les valeurs montrées (objet choisi ou style courant). Ctrl + glisser déplace la case."""

    def __init__(self, ctl, values, pick, key: str = "fill_stroke", parent=None):
        super().__init__(key, "Fond et contour (X : premier plan, Maj+X : intervertir, D : par défaut, / : aucun) ; "
                         "clic sur celui au premier plan : sa couleur", lambda *_a: None, parent)
        self.ctl = ctl
        self.values = values
        self.pick = pick
        self.setCursor(Qt.ArrowCursor)

    def _rects(self):
        """Carré du fond et carré du contour, à l'échelle de la case (dessinés sur 40 × 40 à l'origine)."""
        scale = min(self.width(), self.height()) / 40.0
        return QRectF(2 * scale, 2 * scale, 24 * scale, 24 * scale), QRectF(14 * scale, 14 * scale, 24 * scale, 24 * scale)

    def extra_key(self) -> tuple:
        values = self.values()
        return (values.get("fill", ""), values.get("stroke", ""), repr(values.get("fill_gradient")),
                repr(values.get("stroke_gradient")), self.ctl.focus)

    def _paint_content(self, painter: QPainter) -> None:
        super()._paint_content(painter)                      # fond actif / survol (le glyphe vide ne peint rien)
        scale = min(self.width(), self.height()) / 40.0
        fill_rect, stroke_rect = self._rects()
        values = self.values()
        order = ["stroke", "fill"] if self.ctl.focus == "fill" else ["fill", "stroke"]
        grey = QColor("#9a9a9a")
        for which in order:
            rect = fill_rect if which == "fill" else stroke_rect
            color = values.get(which, "")
            painter.setPen(QPen(grey, 1))
            if which == "fill":
                painter.setBrush(QColor(color) if color else QColor("#ffffff"))
                painter.drawRect(rect)
            else:
                painter.setBrush(QColor("#ffffff") if not color else Qt.NoBrush)
                painter.drawRect(rect)
                if color:
                    painter.setPen(QPen(QColor(color), 6 * scale))
                    painter.drawRect(rect.adjusted(3 * scale, 3 * scale, -3 * scale, -3 * scale))
                    painter.setPen(QPen(grey, 1))
                    painter.setBrush(QColor("#2b2b2b"))
                    painter.drawRect(rect.adjusted(7 * scale, 7 * scale, -7 * scale, -7 * scale))
            gradient = values.get(f"{which}_gradient")
            if gradient:
                ramp = QLinearGradient(rect.topLeft(), rect.topRight())
                for offset, stop in gradient["stops"]:
                    ramp.setColorAt(offset, QColor(stop))
                painter.setPen(QPen(grey, 1))
                painter.setBrush(ramp)
                painter.drawRect(rect)
                if which == "stroke":
                    painter.setBrush(QColor("#2b2b2b"))
                    painter.drawRect(rect.adjusted(7 * scale, 7 * scale, -7 * scale, -7 * scale))
            if not color:
                painter.setPen(QPen(QColor("#e0281e"), 2))
                painter.drawLine(rect.bottomLeft() + QPointF(2, -2), rect.topRight() + QPointF(-2, 2))

    def mousePressEvent(self, event):
        self._item_press(event)                       # glisser au-delà de 4 px : déplacer la case (barres de fm_theme)
        event.accept()

    def mouseReleaseEvent(self, event):
        if self._item_release(event):
            return
        event.accept()
        if event.button() != Qt.LeftButton:
            return
        fill_rect, stroke_rect = self._rects()
        pos = QPointF(event.position())
        focus = self.ctl.focus
        front, back = (fill_rect, stroke_rect) if focus == "fill" else (stroke_rect, fill_rect)
        which = focus if front.contains(pos) else (("stroke" if focus == "fill" else "fill") if back.contains(pos) else None)
        if which is None:
            return
        if which != focus:
            self.ctl.focus = which
            self.ctl.stateChanged.emit()
            return
        self.pick(which, self)
