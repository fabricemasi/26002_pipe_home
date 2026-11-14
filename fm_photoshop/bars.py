"""Barres flottantes du module Photoshop (demande de l'utilisateur, 2026-11-02 : « les palettes d'outils des différents
modules doivent être remplacées, toutes »). Le système est celui de fm_theme (`fm_theme/bar_manager.py`, aspect = réglages
`palette_*`) branché par `fm_board/bars.BoardBars` : UN gestionnaire pour le module, disposition retenue dans
`board_bars["photoshop"]`. Deux familles d'éléments, dans les MÊMES barres :

- sur le Board : « Document » (nouveau, importer, image comme calque, mode Standard, exporter), visible avec le module ;
- dans l'éditeur Standard (`standard.StandardPane`, plein cadre au-dessus du Board) : « Outils » (les 21 outils), « Couleur »,
  « Brosse » (taille, dureté, opacité, débit), « Calque » (opacité, fusion, nom), « Fichier » (annuler, rétablir, importer,
  enregistrer, exporter), « Vue » (zoom, ajuster, 100 %, affichage), « Calques » et « Masque » (commandes). Ces éléments
  appartiennent à UNE session d'édition : ils
  sont refaits à l'ouverture (`set_dynamic`, un groupe par barre) et retirés à la fermeture ; chacun retrouve la case que
  l'utilisateur lui avait donnée (mémoire du gestionnaire, enregistrée avec la disposition).

Rien ici n'entre dans le chemin de la brosse : un curseur écrit dans le réglage de la brosse comme l'ancien panneau."""
from __future__ import annotations

from PySide6.QtCore import QEvent, QRect, QRectF, Qt
from PySide6.QtGui import QColor, QPainter, QPainterPath, QPen, QPolygonF

from fm_theme.placeholder import ink as _placeholder_ink
from fm_theme.icon_frame import framed as _framed
from fm_theme.palette import PaletteButton, PaletteInputBar, PaletteSelectBar, PaletteTextButton

# -- Disposition par défaut ----------------------------------------------------------------------------------------------

DOC_BUTTONS = (                                   # (clé, texte, info-bulle, cases, méthode du contrôleur)
    ("new", "Nouveau", "Nouveau document… : poser un nouveau document au centre de la vue", 2, "new_document_dialog"),
    ("import", "Importer", "Importer… : une image (PNG, JPEG, TIFF, WebP) devient un nouveau document", 2, "import_file"),
    ("layer", "Calque", "Image comme calque… : ajouter une image comme calque du document choisi", 2, "import_as_layer"),
    ("standard", "Standard", "Mode Standard : ouvrir le document choisi en plein cadre", 2, "open_standard"),
    ("export", "Exporter", "Exporter… : composition du document choisi (PNG, TIFF, JPEG, WebP)", 2, "export"))

# Éléments de l'éditeur Standard : groupe -> barre par défaut ; clé -> (barre, colonne, ligne, largeur ; 0 = toute la barre).
STD_GROUPS = {"tools": "t1", "colors": "t2", "brush": "t3", "layer": "t4", "file": "t5", "view": "t6", "layers": "t7",
              "masks": "t8"}
LAYER_ACTIONS = ("add", "group", "duplicate", "remove", "up", "down", "merge", "flatten")      # clés de `LayersPanel.action_buttons`
MASK_ACTIONS = ("add", "toggle", "invert", "apply", "remove")


def _std_cells(tool_keys: tuple) -> dict:
    cells = {key: ("t1", index % 2, index // 2, 1) for index, key in enumerate(tool_keys)}
    cells.update({"fg": ("t2", 0, 0, 1), "bg": ("t2", 1, 0, 1), "swap": ("t2", 0, 1, 1)})
    cells.update({key: ("t3", 0, row, 0) for row, key in enumerate(("brush_size", "brush_hardness", "brush_opacity",
                                                                    "brush_flow"))})
    cells.update({key: ("t4", 0, row, 0) for row, key in enumerate(("layer_opacity", "layer_blend", "layer_name"))})
    cells.update({"undo": ("t5", 0, 0, 2), "redo": ("t5", 2, 0, 2), "std_import": ("t5", 4, 0, 2), "save": ("t5", 6, 0, 3),
                  "std_export": ("t5", 9, 0, 2)})
    cells.update({"zoom": ("t6", 0, 0, 5), "fit": ("t6", 5, 0, 2), "actual": ("t6", 7, 0, 2), "display": ("t6", 0, 1, 0)})
    cells.update({"layer_" + key: ("t7", 2 * (i % 2), i // 2, 2) for i, key in enumerate(LAYER_ACTIONS)})
    cells.update({"mask_" + key: ("t8", 2 * (i % 2), i // 2, 2) for i, key in enumerate(MASK_ACTIONS)})
    cells.update({"target_pixels": ("t8", 0, 3, 2), "target_mask": ("t8", 2, 3, 2)})
    return cells


TOOL_KEYS = ("brush", "eraser", "eyedropper", "move", "hand", "rect_select", "ellipse_select", "lasso", "poly_lasso", "wand",
             "text", "shape_rect", "shape_ellipse", "shape_line", "clone", "heal", "blur", "sharpen", "smudge", "dodge", "burn")


def photoshop_default_state() -> dict:
    """Disposition par défaut : « Document » en haut (Board) ; barres de l'éditeur Standard vides (leurs éléments sont posés
    à l'ouverture d'après la mémoire ci-dessous) : « Outils » et « Couleurs » clipsées à gauche l'une derrière l'autre,
    « Brosse » et « Calque » en bas, « Fichier » en haut, « Vue » en bas à droite, « Calques » et « Masque » (commandes) clipsées
    à droite l'une derrière l'autre."""
    def bar(bar_id, title, items, cols, rows, **extra):
        entry = {"id": bar_id, "title": title, "dock": None, "orient": "h", "along": 0, "x": 0, "y": 0, "cols": cols,
                 "rows": rows, "items": {key: list(cell) for key, cell in items.items()}}
        entry.update(extra)
        return entry
    document = {key: (index * 2, 0, 2) for index, (key, *_rest) in enumerate(DOC_BUTTONS)}
    return {"next": 9, "bars": [
        bar("b1", "Document", document, 2 * len(DOC_BUTTONS), 1, dock="top", along=16),
        bar("t1", "Outils", {}, 2, 11, dock="left", orient="v", along=16),
        bar("t2", "Couleur", {}, 2, 2, dock="left", orient="v", after="t1"),
        bar("t3", "Brosse", {}, 6, 4, dock="bottom", along=16),
        bar("t4", "Calque", {}, 6, 3, dock="bottom", after="t3"),
        bar("t5", "Fichier", {}, 11, 1, dock="top", along=128),         # (à droite de « Outils » : même coin, pas de recouvrement)
        bar("t6", "Vue", {}, 9, 2, dock="bottom", end=True),
        bar("t7", "Calques", {}, 4, 4, dock="right", orient="v", along=16),
        bar("t8", "Masque", {}, 4, 4, dock="right", orient="v", after="t7")],
        "memory": {key: list(cell) for key, cell in _std_cells(TOOL_KEYS).items()}}


# -- Icônes des outils (aucun style inventé : traits et remplissages de la couleur d'icône de la barre) -------------------

def _poly(p, pts, close=False):
    from PySide6.QtCore import QPointF
    poly = QPolygonF([QPointF(x, y) for x, y in pts])
    p.drawPolygon(poly) if close else p.drawPolyline(poly)


def _dashed(p, width: float = 1.7):
    pen = QPen(p.pen())
    pen.setWidthF(width)
    pen.setStyle(Qt.CustomDashLine)
    pen.setDashPattern([1.5, 1.3])
    p.setPen(pen)


def _g_brush(p, c):
    p.drawLine(20, 4, 11, 13)
    p.setBrush(c)
    path = QPainterPath()
    path.moveTo(11, 13)
    path.cubicTo(8, 13, 5, 15, 5, 19)
    path.cubicTo(5, 20.5, 6, 20.5, 7, 20.5)
    path.cubicTo(10, 20.5, 12.5, 18, 13, 14.5)
    path.closeSubpath()
    p.drawPath(path)


def _g_eraser(p, c):
    p.save()
    p.translate(12, 11)
    p.rotate(-45)
    p.drawRoundedRect(QRectF(-8, -4, 16, 8), 1.5, 1.5)
    p.drawLine(-2, -4, -2, 4)
    p.restore()
    p.drawLine(5, 20, 20, 20)


def _g_eyedropper(p, c):
    p.drawLine(4, 20, 12, 12)
    p.save()
    p.translate(15.5, 8.5)
    p.rotate(45)
    p.drawRoundedRect(QRectF(-2.2, -5.5, 4.4, 8.5), 1.5, 1.5)
    p.drawLine(-3.5, -5.5, 3.5, -5.5)
    p.restore()


def _g_move(p, c):
    p.drawLine(12, 3, 12, 21)
    p.drawLine(3, 12, 21, 12)
    _poly(p, [(9, 6), (12, 3), (15, 6)])
    _poly(p, [(9, 18), (12, 21), (15, 18)])
    _poly(p, [(6, 9), (3, 12), (6, 15)])
    _poly(p, [(18, 9), (21, 12), (18, 15)])


def _g_rect_select(p, c):
    _dashed(p)
    p.drawRect(QRectF(4, 6, 16, 12))


def _g_ellipse_select(p, c):
    _dashed(p)
    p.drawEllipse(QRectF(3.5, 5.5, 17, 13))


def _g_lasso(p, c):
    q = QPen(p.pen())
    _dashed(p)
    p.drawEllipse(QRectF(4, 4.5, 16, 10))
    p.setPen(q)
    path = QPainterPath()
    path.moveTo(9, 14)
    path.cubicTo(8, 17, 7, 19, 10, 21)
    p.drawPath(path)


def _g_poly_lasso(p, c):
    _dashed(p)
    _poly(p, [(4, 18), (7, 6), (16, 4), (20, 12), (14, 19)], True)


def _g_wand(p, c):
    pen = QPen(p.pen())
    pen.setWidthF(2.4)
    p.setPen(pen)
    p.drawLine(4, 20, 14, 10)
    pen.setWidthF(1.5)
    p.setPen(pen)
    p.drawLine(17, 3, 17, 8)
    p.drawLine(14.5, 5.5, 19.5, 5.5)
    p.drawLine(20, 12, 20, 15)
    p.drawLine(18.5, 13.5, 21.5, 13.5)


def _g_text(p, c):
    p.drawLine(5, 5, 19, 5)
    p.drawLine(12, 5, 12, 19)
    p.drawLine(9, 19, 15, 19)


def _g_shape_rect(p, c):
    p.drawRect(QRectF(4, 6, 16, 12))


def _g_shape_ellipse(p, c):
    p.drawEllipse(QRectF(3.5, 5.5, 17, 13))


def _g_shape_line(p, c):
    p.drawLine(6, 18, 18, 6)
    p.setBrush(c)
    p.drawEllipse(QRectF(3.8, 15.8, 4.4, 4.4))
    p.drawEllipse(QRectF(15.8, 3.8, 4.4, 4.4))


def _g_clone(p, c):
    p.drawEllipse(QRectF(9.5, 3, 5, 5))
    p.drawLine(12, 8, 12, 12)
    p.drawRoundedRect(QRectF(5, 12, 14, 5), 1.5, 1.5)
    p.drawLine(4, 20.5, 20, 20.5)


def _g_heal(p, c):
    p.save()
    p.translate(12, 12)
    p.rotate(-45)
    p.drawRoundedRect(QRectF(-9, -4, 18, 8), 3, 3)
    p.drawLine(-3, -4, -3, 4)
    p.drawLine(3, -4, 3, 4)
    p.restore()
    p.setBrush(c)
    for x, y in ((11, 11), (13, 13), (11, 13), (13, 11)):
        p.drawEllipse(QRectF(x - 0.6, y - 0.6, 1.2, 1.2))


def _g_blur(p, c):
    path = QPainterPath()
    path.moveTo(12, 3)
    path.cubicTo(12, 3, 5, 11, 5, 15)
    path.cubicTo(5, 19, 8, 21, 12, 21)
    path.cubicTo(16, 21, 19, 19, 19, 15)
    path.cubicTo(19, 11, 12, 3, 12, 3)
    p.drawPath(path)


def _g_sharpen(p, c):
    _poly(p, [(12, 4), (20, 19), (4, 19)], True)
    p.drawLine(12, 10, 12, 15)


def _g_smudge(p, c):
    path = QPainterPath()
    path.moveTo(5, 17)
    path.cubicTo(8, 9, 12, 9, 14, 12)
    path.cubicTo(16, 15, 18, 11, 20, 7)
    p.drawPath(path)
    p.setBrush(c)
    p.drawEllipse(QRectF(3.2, 15.2, 4.6, 4.6))


def _g_dodge(p, c):
    p.drawEllipse(QRectF(8, 8, 8, 8))
    import math
    for k in range(8):
        a = k * math.pi / 4
        p.drawLine(12 + 6 * math.cos(a), 12 + 6 * math.sin(a), 12 + 9 * math.cos(a), 12 + 9 * math.sin(a))


def _g_burn(p, c):
    p.drawEllipse(QRectF(5, 5, 14, 14))
    path = QPainterPath()
    path.moveTo(12, 5)
    path.arcTo(QRectF(5, 5, 14, 14), 90, 180)
    path.closeSubpath()
    p.setBrush(c)
    p.drawPath(path)


def _g_swap(p, c):
    _poly(p, [(4, 9), (20, 9)])
    _poly(p, [(16, 5), (20, 9), (16, 13)])
    _poly(p, [(20, 16), (4, 16)])
    _poly(p, [(8, 12), (4, 16), (8, 20)])


GLYPHS = {"brush": _g_brush, "eraser": _g_eraser, "eyedropper": _g_eyedropper, "move": _g_move, "rect_select": _g_rect_select,
          "ellipse_select": _g_ellipse_select, "lasso": _g_lasso, "poly_lasso": _g_poly_lasso, "wand": _g_wand,
          "text": _g_text, "shape_rect": _g_shape_rect, "shape_ellipse": _g_shape_ellipse, "shape_line": _g_shape_line,
          "clone": _g_clone, "heal": _g_heal, "blur": _g_blur, "sharpen": _g_sharpen, "smudge": _g_smudge,
          "dodge": _g_dodge, "burn": _g_burn, "swap": _g_swap}


@_framed("photoshop")                                 # cadre des icones (fm_theme > General > Marge des icones)
def paint_tool(painter: QPainter, tool: str, rect: QRectF, color: QColor) -> None:
    """Icône d'un outil : dessinée dans une grille de 24 unités, traits arrondis de la couleur d'icône de la barre."""
    color = _placeholder_ink(color)                     # icone dessinee par le code : magenta (provisoire)
    painter.save()
    painter.setRenderHint(QPainter.Antialiasing, True)
    if tool == "hand":
        from fm_board.ui import paint_glyph             # la main du Board : la même icône
        paint_glyph(painter, "hand", rect, color)
        painter.restore()
        return
    painter.translate(rect.topLeft())
    painter.scale(rect.width() / 24.0, rect.height() / 24.0)
    pen = QPen(color, 1.7)
    pen.setCapStyle(Qt.RoundCap)
    pen.setJoinStyle(Qt.RoundJoin)
    painter.setPen(pen)
    painter.setBrush(Qt.NoBrush)
    GLYPHS.get(tool, _g_shape_rect)(painter, color)
    painter.restore()


# -- Éléments ------------------------------------------------------------------------------------------------------------

class PsTool(PaletteButton):
    """Case d'un outil de l'éditeur Standard ; `isChecked` / `setChecked` : mêmes noms que l'ancien bouton à cocher."""

    def __init__(self, tool: str, tip: str, parent=None):
        super().__init__(tool, tip, lambda p, r, c, t=tool: paint_tool(p, t, r, c), parent)
        if tool == "brush":
            self.set_library_icon("modules/photoshop/pinceau_03")
        self.tool = tool

    def isChecked(self) -> bool:
        return self.active

    def setChecked(self, on: bool) -> None:
        self.set_active(on)


def pick_color(owner, getter, setter, label: str):
    """Sélecteur de couleur des réglages ouvert près de `owner` (premier plan / arrière-plan) ; le garde vivant."""
    from settings_widgets import _ColorPickerPopup
    r, g, b = getter()
    popup = _ColorPickerPopup("#%02x%02x%02x" % (r, g, b), label, owner.window())
    popup.colorChanged.connect(lambda color: setter(_rgb(color)))
    popup.committed.connect(lambda color: setter(_rgb(color)))
    popup.show_near(owner)
    return popup


def _rgb(color) -> tuple:
    c = QColor(color)
    return c.red(), c.green(), c.blue()


class PsSwatch(PaletteButton):
    """Pastille de couleur (premier plan / arrière-plan) d'une barre : un clic ouvre le sélecteur de couleur des réglages."""

    def __init__(self, key: str, getter, setter, label: str, parent=None):
        super().__init__(key, label, self._paint, parent)
        self.getter, self.setter, self.label = getter, setter, label
        self.clicked.connect(self._pick)
        self._popup = None

    def _paint(self, painter, rect, color):
        inner = QRectF(rect).adjusted(-2, -2, 2, 2)
        painter.setPen(QPen(color, 1.2))
        painter.setBrush(QColor(*self.getter()))
        painter.drawRoundedRect(inner, 3, 3)

    def extra_key(self) -> tuple:
        return (tuple(self.getter()),)

    def _pick(self):
        self._popup = pick_color(self, self.getter, self._set, self.label)

    def _set(self, color: tuple) -> None:
        self.setter(color)
        self.update()


class PsTextButton(PaletteTextButton):
    """Bouton à texte d'une barre ; grisé quand il est désactivé (ex. commandes de masque sans masque)."""

    def extra_key(self) -> tuple:
        return (self._text, self.isEnabled())

    def _paint_content(self, painter: QPainter) -> None:
        if not self.isEnabled():
            painter.setOpacity(0.4)
        super()._paint_content(painter)

    def changeEvent(self, event):
        if event.type() == QEvent.EnabledChange:
            self.update()
        super().changeEvent(event)


def text_button(key: str, text: str, tip: str, slot, cells: int = 2) -> PsTextButton:
    button = PsTextButton(key, text, tip, cells=cells)
    button.clicked.connect(lambda _c=False: slot())
    return button


# -- Le module : un gestionnaire, deux familles d'éléments ----------------------------------------------------------------

def controller_for(board):
    """Le contrôleur Photoshop du Board, créé au besoin (l'éditeur Standard peut s'ouvrir sans que le module soit choisi)."""
    controller = getattr(board, "photoshop", None)
    if controller is None:
        from .board_ui import PhotoshopController
        controller = board.photoshop = PhotoshopController(board)
    return controller


class PhotoshopBars:
    """Les barres flottantes de Photoshop sur le Board : « Document » (inscrites une fois) et celles de l'éditeur Standard
    (`attach` / `detach`, un groupe par barre)."""

    def __init__(self, controller):
        from fm_board.bars import BoardBars
        self.controller = controller
        self.pane = controller.pane
        self.bars = BoardBars(self.pane, "photoshop", photoshop_default_state())
        self.manager = self.bars.manager
        self.std = None                                   # l'éditeur Standard ouvert (ses éléments sont posés)
        self.buttons: dict = {}
        for key, text, tip, cells, method in DOC_BUTTONS:
            button = text_button(key, text, tip, lambda m=method: getattr(controller, m)(), cells)
            self.bars.register(key, button)
            self.buttons[key] = button
        self.bars.restore()
        self.bars.set_visible(False)
        self._no_bar = None

    def document_bar(self):
        """La barre « Document » (b1) ; si l'utilisateur l'a supprimée, un widget caché."""
        bar = self.bars.bar("b1")
        if bar is None:
            if self._no_bar is None:
                from PySide6.QtWidgets import QWidget
                self._no_bar = QWidget(self.pane)
                self._no_bar.hide()
            return self._no_bar
        return bar

    def refresh(self) -> None:
        """Le module est actif et rien n'est ouvert en plein cadre : « Document » ; l'éditeur Standard ouvert : ses barres."""
        show_document = bool(self.controller.active) and self.std is None
        for button in self.buttons.values():
            if button.isHidden() == show_document:
                button.setVisible(show_document)
        self.bars.set_visible(show_document or self.std is not None)

    def area(self) -> QRect:
        std = self.std
        if std is not None:
            return std.bars_area()
        left = self.pane.left_edge()
        return QRect(left, 0, max(0, self.pane.width() - left), self.pane.height())

    def place(self) -> None:
        self.manager.set_area(self.area())

    def raise_all(self) -> None:
        self.bars.raise_all()

    def attach(self, std, groups: dict) -> None:
        """L'éditeur Standard `std` pose ses éléments : `groups` = {groupe : [(clé, widget)]} (groupes de `STD_GROUPS`)."""
        self.std = std
        for group, items in groups.items():
            self.manager.set_dynamic("std_" + group, items, STD_GROUPS[group])
        self.refresh()
        self.place()
        self.raise_all()

    def detach(self, std) -> None:
        if self.std is not std:
            return
        self.manager.remember()                           # la place de chaque élément est retenue avant qu'ils disparaissent
        self.std = None
        for group in STD_GROUPS:
            self.manager.set_dynamic("std_" + group, [], STD_GROUPS[group])
        self.refresh()
        self.place()


class StandardPalettes:
    """Les éléments des barres de l'éditeur Standard : créés par le `StandardPane` (leurs actions sont les siennes), posés
    dans les barres par `PhotoshopBars.attach`."""

    def __init__(self, std, tool_rows):
        from .display import DISPLAY_LABELS
        self.std = std
        s = std.session
        self.tools = {}
        for tool, _text, tip in tool_rows:
            button = PsTool(tool, tip)
            button.clicked.connect(lambda _c=False, t=tool: std.canvas.set_tool(t))
            self.tools[tool] = button
        panel, layers = std.brush_panel, std.layers_panel
        self.swap = PaletteButton("swap", "Permuter les couleurs (X)", lambda p, r, c: paint_tool(p, "swap", r, c))
        self.swap.clicked.connect(lambda _c=False: panel.swap())
        self.undo = text_button("undo", "Annuler", "Annuler (Ctrl+Z)", lambda: std.canvas.undo())
        self.redo = text_button("redo", "Rétablir", "Rétablir (Ctrl+Y)", lambda: std.canvas.redo())
        self.imp = text_button("std_import", "Importer", "Importer… : ajouter une image comme nouveau calque", std.import_layer)
        self.save = text_button("save", "Enregistrer", "Enregistrer le Board (Ctrl+S)", std._save, 3)
        self.export = text_button("std_export", "Exporter", "Exporter… : composition ou calque (PNG, TIFF, JPEG, WebP)",
                                  std.export)
        self.zoom = PaletteInputBar("zoom", "Zoom %", "100")
        self.zoom.setToolTip("Zoom : saisir un pourcentage puis Entrée (Ctrl+molette sur l'établi)")
        self.zoom.valueChanged.connect(std._zoom_typed)
        self.fit = text_button("fit", "Ajuster", "Tout voir (Ctrl+0)", lambda: std.canvas.fit())
        self.actual = text_button("actual", "100 %", "Taille réelle (Ctrl+1)", lambda: std.canvas.set_zoom(1.0))
        self.display_labels = dict(DISPLAY_LABELS)
        self.display = PaletteSelectBar("display", "Affichage", list(self.display_labels.values()),
                                        self.display_labels.get(s.display_filter, "Pixels (voisin)"))
        self.display.setToolTip("Qualité de l'AFFICHAGE à fort zoom (diagnostic) : ne modifie jamais les pixels du document")
        self.display.valueChanged.connect(std._display_chosen)
        self.groups = {
            "tools": [(tool, button) for tool, button in self.tools.items()],
            "colors": [("fg", panel.fg), ("bg", panel.bg), ("swap", self.swap)],
            "brush": [("brush_" + key, panel.rows[key].field) for key in ("size", "hardness", "opacity", "flow")],
            "layer": [("layer_opacity", layers.opacity.field), ("layer_blend", layers.blend),
                      ("layer_name", layers.name_edit)],
            "file": [("undo", self.undo), ("redo", self.redo), ("std_import", self.imp), ("save", self.save),
                     ("std_export", self.export)],
            "view": [("zoom", self.zoom), ("fit", self.fit), ("actual", self.actual), ("display", self.display)],
            "layers": [("layer_" + key, layers.action_buttons[key]) for key in LAYER_ACTIONS],
            "masks": [("mask_" + key, layers.mask_buttons[key]) for key in MASK_ACTIONS]
                     + [("target_pixels", layers.target_pixels), ("target_mask", layers.target_mask)]}
