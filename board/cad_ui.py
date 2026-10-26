"""Module CAD du board : INTERFACE — barre d'outils CAD (en haut de la page), barre de commande (en bas),
panneau Proprietes (a droite), gestionnaire de calques, fenetre des accrochages, menus.

Habillage : briques des barres du board (`_bar`, `_GlyphButton`, `_TextButton`, menus `settings_menu.Menu`,
Reglages > Module MRO > Barres d'outils) et des reglages (tableaux `build_cells_table`, champs `_TextField`,
`_SelectField`, `_SliderField`, `_Toggle`, fenetres additionnelles, « Changement de style a la volee » pour
les accrochages) : aucun style invente. Seuls les outils REELLEMENT disponibles sont activables ; ceux des
phases suivantes sont montres grises (infobulle : phase prevue)."""
from __future__ import annotations

import html

from PySide6.QtCore import QPointF, QRectF, Qt, QTimer
from PySide6.QtGui import QColor, QPainter, QPainterPath, QPen, QPolygonF
from PySide6.QtCore import QObject, QEvent, Signal
from PySide6.QtWidgets import QApplication, QDialog, QHBoxLayout, QLineEdit, QVBoxLayout, QWidget

from . import cad_commands, cad_hatch, cad_input, cad_model, cad_snap, cad_text
from . import cad_geometry as geo
from .ui import (_GlyphButton, _TextButton, _bar, _menu as _board_menu, _panel, _SwatchGrid, custom_icon, look_key,
                 negative)

# Barre d'outils : (section, [(genre d'icone, commande, infobulle, disponible)])
SECTIONS = [
    ("Dessin", [("cad_line", "LINE", "Ligne (L)", True),
                ("cad_pline", "PLINE", "Polyligne (PL)", True),
                ("cad_circle", "CIRCLE", "Cercle (C)", True),
                ("cad_arc", "ARC", "Arc (A)", True),
                ("cad_rect", "RECTANGLE", "Rectangle (REC)", True),
                ("cad_hatch", "HATCH", "Hachures (H)", True)]),
    ("Modification", [("cad_move", "MOVE", "Déplacer (M)", True),
                      ("cad_copy", "COPY", "Copier (CO)", True),
                      ("cad_erase", "ERASE", "Effacer (E, Suppr)", True),
                      ("cad_match", "MATCHPROP", "Pipette : copier les propriétés d'un objet sur d'autres (MA)", True),
                      ("cad_rotate", "ROTATE", "Rotation (RO)", True),
                      ("cad_mirror", "MIRROR", "Miroir (MI)", True),
                      ("cad_scale", "SCALE", "Échelle (SC)", True),
                      ("cad_trim", "TRIM", "Ajuster (TR)", True),
                      ("cad_offset", "OFFSET", "Décaler (O)", True),
                      ("cad_chamfer", "CHAMFER", "Chanfrein (CHA)", True),
                      ("cad_fillet", "FILLET", "Raccord / arrondi (F)", True),
                      ("cad_explode", "EXPLODE", "Décomposer : polyligne en lignes et arcs, cotation en traits et "
                                                 "texte (X)", True)]),
    ("Annotations", [("cad_text", "TEXT", "Texte (DT) : une ligne par Entrée", True),
                     ("cad_mtext", "MTEXT", "Texte multiligne (MT) : cadre, Entrée = paragraphe, "
                                            "Ctrl+Entrée = fin", True),
                     ("cad_dim", "DIMLINEAR", "Cotation linéaire (DLI)", True),
                     ("cad_dim_aligned", "DIMALIGNED", "Cotation alignée (DAL)", True),
                     ("cad_dim_radius", "DIMRADIUS", "Cotation de rayon (DRA)", True),
                     ("cad_dim_diameter", "DIMDIAMETER", "Cotation de diamètre (DDI)", True),
                     ("cad_dim_angular", "DIMANGULAR", "Cotation angulaire (DAN)", True)]),
]
PRECISION = [("osnap", "OSNAP", "Accrochages aux objets (F3)"), ("ortho", "ORTHO", "Mode orthogonal (F8)"),
             ("polar", "POLAIRE", "Suivi polaire (F10)"), ("otrack", "OTRACK", "Suivi d'accrochage (F11)"),
             ("dyn", "DYN", "Saisie dynamique (F12)"), ("grid", "GRILLE", "Grille (F7)"),
             ("grid_snap", "RESOL", "Accrochage à la grille (F9)"),
             ("lineweight", "ÉPAIS.", "Afficher les épaisseurs de ligne (LWT) : éteint = simples lignes d'un pixel, comme AutoCAD")]
OVERRIDE_TAG = "ovr:"         # fenetre des reglages du dessin : interrupteur d'override d'une ligne
WEIGHTS = (0.0, 0.1, 0.18, 0.25, 0.35, 0.5, 0.7, 1.0, 1.4, 2.0, 3.0, 5.0)   # menu des epaisseurs (unite du dessin)
HISTORY_LINES = 3
HISTORY_EXPANDED = 14


def paint_cad_glyph(painter: QPainter, kind: str, rect: QRectF, color: QColor):
    """Icones des outils CAD (traits, dans l'esprit des glyphes du board)."""
    pen = QPen(color, 1.4)
    pen.setCapStyle(Qt.RoundCap)
    pen.setJoinStyle(Qt.RoundJoin)
    painter.setPen(pen)
    painter.setBrush(Qt.NoBrush)
    c = rect.center()
    s = min(rect.width(), rect.height()) * 0.2
    cx, cy = c.x(), c.y()

    def P(x, y):
        return QPointF(cx + x * s, cy + y * s)

    def box(p, r=0.28):
        painter.drawRect(QRectF(p.x() - r * s, p.y() - r * s, 2 * r * s, 2 * r * s))
    if kind == "cad":                       # equerre + compas : dessin technique
        painter.drawPolygon(QPolygonF([P(-1.5, 1.3), P(1.5, 1.3), P(-1.5, -1.5)]))
        painter.drawPolygon(QPolygonF([P(-0.8, 0.8), P(0.1, 0.8), P(-0.8, -0.2)]))
        painter.drawLine(P(0.6, -1.5), P(1.5, 0.6))
    elif kind == "cad_line":
        painter.drawLine(P(-1.2, 1.2), P(1.2, -1.2))
        box(P(-1.2, 1.2))
        box(P(1.2, -1.2))
    elif kind == "cad_pline":
        painter.drawPolyline(QPolygonF([P(-1.4, 1.1), P(-0.4, -0.9), P(0.5, 0.6), P(1.4, -1.1)]))
    elif kind == "cad_circle":
        painter.drawEllipse(c, s * 1.4, s * 1.4)
        painter.drawPoint(c)
    elif kind == "cad_arc":
        path = QPainterPath(P(-1.4, 0.9))
        path.cubicTo(P(-1.2, -1.6), P(1.2, -1.6), P(1.4, 0.9))
        painter.drawPath(path)
    elif kind == "cad_rect":
        painter.drawRect(QRectF(P(-1.5, -1.0), P(1.5, 1.0)))
    elif kind == "cad_hatch":
        painter.drawRect(QRectF(P(-1.4, -1.4), P(1.4, 1.4)))
        for k in (-0.7, 0.0, 0.7):
            painter.drawLine(P(k - 0.7, 1.4), P(min(1.4, k + 0.7 + 0.7), max(-1.4, -0.7 - k)))
    elif kind == "cad_move":
        painter.drawLine(P(-1.5, 0), P(1.5, 0))
        painter.drawLine(P(0, -1.5), P(0, 1.5))
        for a, b, d in ((P(1.5, 0), P(1.0, -0.45), P(1.0, 0.45)), (P(-1.5, 0), P(-1.0, -0.45), P(-1.0, 0.45)),
                        (P(0, 1.5), P(-0.45, 1.0), P(0.45, 1.0)), (P(0, -1.5), P(-0.45, -1.0), P(0.45, -1.0))):
            painter.drawPolyline(QPolygonF([b, a, d]))
    elif kind == "cad_copy":
        painter.drawRect(QRectF(P(-1.4, -1.4), P(0.5, 0.5)))
        painter.drawRect(QRectF(P(-0.5, -0.5), P(1.4, 1.4)))
    elif kind == "cad_erase":
        painter.drawPolygon(QPolygonF([P(-1.4, 0.4), P(0.3, -1.3), P(1.4, -0.2), P(-0.3, 1.5)]))
        painter.drawLine(P(-0.6, -0.4), P(0.5, 0.7))
    elif kind == "cad_rotate":
        path = QPainterPath(P(1.2, -0.4))
        path.arcTo(QRectF(P(-1.3, -1.3), P(1.3, 1.3)), 15, 285)
        painter.drawPath(path)
        painter.drawPolyline(QPolygonF([P(0.5, -0.6), P(1.2, -0.4), P(1.4, -1.1)]))
    elif kind == "cad_scale":
        painter.drawRect(QRectF(P(-1.5, 0.0), P(0.0, 1.5)))
        painter.drawRect(QRectF(P(-1.5, -1.5), P(1.5, 1.5)))
        painter.drawLine(P(0.0, 0.0), P(1.5, -1.5))
        painter.drawPolyline(QPolygonF([P(0.5, -1.5), P(1.5, -1.5), P(1.5, -0.5)]))
    elif kind == "cad_mirror":
        painter.drawLine(P(0, -1.6), P(0, 1.6))
        painter.drawPolygon(QPolygonF([P(-0.4, -1.0), P(-1.5, 1.0), P(-0.4, 1.0)]))
        painter.drawPolygon(QPolygonF([P(0.4, -1.0), P(1.5, 1.0), P(0.4, 1.0)]))
    elif kind == "cad_offset":
        painter.drawLine(P(-1.4, 0.6), P(1.0, -1.4))
        painter.drawLine(P(-1.0, 1.4), P(1.4, -0.6))
    elif kind == "cad_chamfer":
        painter.drawPolyline(QPolygonF([P(-1.4, -1.3), P(0.4, -1.3), P(1.3, -0.4), P(1.3, 1.4)]))
    elif kind == "cad_fillet":
        path = QPainterPath(P(-1.4, -1.3))
        path.lineTo(P(0.0, -1.3))
        path.quadTo(P(1.3, -1.3), P(1.3, 0.0))
        path.lineTo(P(1.3, 1.4))
        painter.drawPath(path)
    elif kind == "cad_text":
        painter.drawLine(P(-1.2, -1.3), P(1.2, -1.3))
        painter.drawLine(P(0, -1.3), P(0, 1.4))
        painter.drawLine(P(-0.5, 1.4), P(0.5, 1.4))
    elif kind == "cad_mtext":                          # cadre + lignes de texte
        painter.setPen(QPen(color, 1.0, Qt.DashLine))
        painter.drawRect(QRectF(P(-1.6, -1.5), P(1.6, 1.5)))
        painter.setPen(pen)
        for dy, right in ((-0.8, 1.0), (0.0, 1.0), (0.8, 0.2)):
            painter.drawLine(P(-1.0, dy), P(right, dy))
    elif kind == "cad_explode":                        # carre dont les cotes s'ecartent
        for a, b in ((P(-1.0, -1.5), P(1.0, -1.5)), (P(-1.0, 1.5), P(1.0, 1.5)),
                     (P(-1.5, -1.0), P(-1.5, 1.0)), (P(1.5, -1.0), P(1.5, 1.0))):
            painter.drawLine(a, b)
        for a, b in ((P(-0.4, -0.4), P(-1.0, -1.0)), (P(0.4, -0.4), P(1.0, -1.0)),
                     (P(-0.4, 0.4), P(-1.0, 1.0)), (P(0.4, 0.4), P(1.0, 1.0))):
            painter.drawLine(a, b)
    elif kind == "cad_dim":
        painter.drawLine(P(-1.5, -1.2), P(-1.5, 1.2))
        painter.drawLine(P(1.5, -1.2), P(1.5, 1.2))
        painter.drawLine(P(-1.5, 0), P(1.5, 0))
        painter.drawPolyline(QPolygonF([P(-0.9, -0.4), P(-1.5, 0), P(-0.9, 0.4)]))
        painter.drawPolyline(QPolygonF([P(0.9, -0.4), P(1.5, 0), P(0.9, 0.4)]))
    elif kind == "cad_trim":                           # une traverse coupee a droite de la limite
        painter.drawLine(P(-1.5, 1.4), P(1.5, 1.4))
        painter.drawLine(P(0.2, -1.5), P(0.2, 1.4))
        pen = QPen(color, 1.4, Qt.DashLine)
        painter.setPen(pen)
        painter.drawLine(P(-1.5, -0.2), P(0.2, -0.2))
        painter.setPen(QPen(color, 1.4))
        painter.drawLine(P(0.2, -0.2), P(1.4, -0.2))
    elif kind == "cad_dim_aligned":
        painter.drawLine(P(-1.4, 1.2), P(-1.4, -0.2))
        painter.drawLine(P(1.4, 0.2), P(1.4, -1.2))
        painter.drawLine(P(-1.4, 0.7), P(1.4, -0.7))
        painter.drawPolyline(QPolygonF([P(-0.7, 0.8), P(-1.4, 0.7), P(-1.0, 0.1)]))
        painter.drawPolyline(QPolygonF([P(0.7, -0.8), P(1.4, -0.7), P(1.0, -0.1)]))
    elif kind in ("cad_dim_radius", "cad_dim_diameter"):
        painter.drawEllipse(P(0, 0), 1.2 * s, 1.2 * s)
        if kind == "cad_dim_radius":
            painter.drawLine(P(0, 0), P(1.2, -1.2))
            painter.drawPolyline(QPolygonF([P(0.5, -0.4), P(0.85, -0.85), P(0.4, -0.5)]))
        else:
            painter.drawLine(P(-1.2, 1.2), P(1.2, -1.2))
            painter.drawPolyline(QPolygonF([P(0.5, -0.4), P(0.85, -0.85), P(0.4, -0.5)]))
            painter.drawPolyline(QPolygonF([P(-0.5, 0.4), P(-0.85, 0.85), P(-0.4, 0.5)]))
    elif kind == "cad_dim_angular":
        painter.drawLine(P(-1.4, 1.3), P(1.4, 1.3))
        painter.drawLine(P(-1.4, 1.3), P(0.9, -1.3))
        path = QPainterPath(P(0.4, 1.3))
        path.arcTo(QRectF(P(-1.4, -0.1), P(1.0, 2.7)), 0.0, 48.0)
        painter.drawPath(path)
    elif kind == "cad_layers":
        for dy in (-0.9, 0.0, 0.9):
            painter.drawPolygon(QPolygonF([P(-1.5, dy), P(0, dy - 0.6), P(1.5, dy), P(0, dy + 0.6)]))
    elif kind == "cad_properties":
        for dy in (-1.0, 0.0, 1.0):
            painter.drawLine(P(-1.4, dy), P(-0.8, dy))
            painter.drawLine(P(-0.3, dy), P(1.4, dy))
    elif kind == "cad_settings":                       # cible d'accrochage
        painter.drawRect(QRectF(P(-0.7, -0.7), P(0.7, 0.7)))
        for a, b in ((P(-1.6, 0), P(-0.7, 0)), (P(0.7, 0), P(1.6, 0)), (P(0, -1.6), P(0, -0.7)), (P(0, 0.7), P(0, 1.6))):
            painter.drawLine(a, b)
    elif kind == "cad_match":                          # pipette
        painter.drawLine(P(-1.4, 1.4), P(0.2, -0.2))
        painter.drawPolygon(QPolygonF([P(-0.2, -0.6), P(0.6, 0.2), P(1.5, -0.7), P(0.7, -1.5)]))
        painter.drawLine(P(-1.4, 1.4), P(-1.0, 0.6))
    elif kind == "cad_drawing":                        # feuille + regle graduee : reglages du dessin
        painter.drawRect(QRectF(P(-1.3, -1.5), P(1.3, 1.5)))
        painter.drawLine(P(-1.3, 0.6), P(1.3, 0.6))
        for k in (-0.7, 0.0, 0.7):
            painter.drawLine(P(k, 0.6), P(k, 1.1 if k == 0.0 else 0.95))
        painter.drawLine(P(-0.7, -0.8), P(0.7, -0.8))
    elif kind == "cad_history":
        painter.drawPolyline(QPolygonF([P(-1.0, 0.4), P(0, -0.6), P(1.0, 0.4)]))


def _bar_look(widget) -> dict | None:
    """Habillage de la barre CAD qui contient `widget` (texte garanti lisible sur son fond, `CadChrome.set_look`)."""
    node = widget.parentWidget()
    while node is not None:
        look = getattr(node, "look", None)
        if isinstance(look, dict) and "bg" in look:
            return look
        node = node.parentWidget()
    return None


def _menu(parent, key: str):
    """Menu du CAD : habillage des menus du board, texte garanti lisible sur son fond (`settings_menu.readable_look`)."""
    menu = _board_menu(parent, key)
    menu.setProperty("ctxContrast", True)
    return menu


class _CadButton(_GlyphButton):
    """Bouton d'outil CAD : jamais de focus clavier (la frappe reste a la page) ; grise a 20 % quand
    l'outil n'est pas encore disponible."""

    def __init__(self, kind, tip, parent=None, size: int = 30):
        super().__init__(kind, tip, parent, size)
        self.setFocusPolicy(Qt.NoFocus)

    def glyph_ink(self, invert: bool) -> str:
        look = _bar_look(self)
        return look["text"] if look else super().glyph_ink(invert)

    def paint_key(self) -> tuple:
        return super().paint_key() + (look_key(_bar_look(self)), look_key(getattr(self.window(), "toolbar_style", None)))

    def paint_content(self, painter):
        if self.isEnabled():
            super().paint_content(painter)
            return
        painter.setOpacity(0.2)
        painter.setRenderHint(QPainter.Antialiasing, True)
        look = getattr(self.parentWidget(), "look", None) or getattr(self.window(), "toolbar_style", None)
        rect = QRectF(self.rect()).adjusted(2, 2, -2, -2)
        invert = bool(look and look.get("invert"))
        side = int(min(rect.width(), rect.height()) * 0.62)
        pix = custom_icon(self.kind, side)
        if pix is not None and not pix.isNull():
            target = QRectF(0, 0, pix.width() / max(1.0, pix.devicePixelRatio()),
                            pix.height() / max(1.0, pix.devicePixelRatio()))
            target.moveCenter(rect.center())
            painter.drawPixmap(target, pix, QRectF(pix.rect()))
        else:
            paint_cad_glyph(painter, self.kind, rect, QColor(self.glyph_ink(invert)))


class _ModeButton(_CadButton):
    """Bascule de precision (OSNAP, ORTHO…) : texte court, fond accent quand le mode est actif."""

    def __init__(self, text, tip, parent=None):
        super().__init__(f"txt:{text}", tip, parent, 30)
        self.text_value = text
        self.setFixedWidth(max(46, 9 * len(text) + 12))

    def paint_key(self) -> tuple:
        return (self.text_value, self._on, look_key(getattr(self, "look", None)))

    def paint_content(self, painter):
        from app_style import C
        painter.setRenderHint(QPainter.Antialiasing, True)
        look = getattr(self, "look", None) or {}
        rect = QRectF(self.rect()).adjusted(1, 3, -1, -3)
        if self._on or self.underMouse():
            color = (look.get("focus_color", "#6e3f6f9f") if self._on else look.get("hover_color", C["hover"]))
            painter.setPen(Qt.NoPen)
            painter.setBrush(QColor(color))
            radius = look.get("focus_radius", 6) if self._on else look.get("hover_radius", 6)
            painter.drawRoundedRect(rect, radius, radius)
        text = look.get("text") or C["text"]
        color = QColor(text)
        if not self._on:
            color.setAlphaF(0.55)
        painter.setPen(color)
        font = look.get("font")
        if font is not None:
            font = type(font)(font)
            font.setBold(self._on)
            painter.setFont(font)
        painter.drawText(rect, Qt.AlignCenter, self.text_value)


def _mix(first: str, second: str, ratio: float) -> str:
    """`first` mele a `ratio` de `second` (#rrggbb)."""
    a, b = QColor(first), QColor(second)
    return QColor.fromRgbF(a.redF() + (b.redF() - a.redF()) * ratio, a.greenF() + (b.greenF() - a.greenF()) * ratio,
                           a.blueF() + (b.blueF() - a.blueF()) * ratio).name()


class CadChrome:
    """Toute l'interface CAD d'un board ; creee avec le controleur, montree / cachee avec le mode CAD."""

    def __init__(self, pane, ctl):
        self.pane = pane
        self.ctl = ctl
        self._history_open = False
        self._properties_open = False
        self._layers = None
        self._snap_window = None
        self._drawing_window = None
        self._drawing_values = None
        self._drawing_timer = QTimer(pane)
        self._drawing_timer.setSingleShot(True)
        self._drawing_timer.setInterval(400)
        self._drawing_timer.timeout.connect(self._apply_drawing)
        self._snap_pending = {}
        self._snap_timer = QTimer(pane)
        self._snap_timer.setSingleShot(True)
        self._snap_timer.setInterval(250)
        self._snap_timer.timeout.connect(self._flush_snap)
        self._build_toolbar()
        self._build_command_bar()
        self._build_properties()
        self._sync_timer = QTimer(pane)
        self._sync_timer.setSingleShot(True)
        self._sync_timer.setInterval(0)
        self._sync_timer.timeout.connect(self.sync)
        self._props_timer = QTimer(pane)
        self._props_timer.setSingleShot(True)
        self._props_timer.setInterval(30)
        self._props_timer.timeout.connect(self._rebuild_properties)
        ctl.stateChanged.connect(self._sync_timer.start)
        ctl.selectionChanged.connect(self._props_timer.start)
        pane.scene.pageChanged.connect(self._on_page_changed)
        pane.scene.contentChanged.connect(self._props_timer.start)
        self.hide()
        look = getattr(pane, "toolbar_style", None)
        if look is not None:
            self.set_look(look)

    # -- construction --
    def _build_toolbar(self):
        from settings_theme import _text_label
        bar, outer = _bar(self.pane, True)
        outer.setSpacing(6)
        self.toolbar = bar
        self._rows = []
        for _n in range(2):                       # 2e rangee : seulement quand la page est trop etroite
            row_layout = QHBoxLayout()
            row_layout.setContentsMargins(0, 0, 0, 0)
            row_layout.setSpacing(10)
            outer.addLayout(row_layout)
            self._rows.append(row_layout)
        layout = self._rows[0]
        self._sections = []
        self._wrapped = None
        self.buttons = {}
        self.captions = []

        def section(title):
            box = QWidget(bar)
            box.setAttribute(Qt.WA_TranslucentBackground, True)
            v = QVBoxLayout(box)
            v.setContentsMargins(0, 0, 0, 0)
            v.setSpacing(1)
            caption = _text_label(title.upper(), "mini_label")
            caption.setAlignment(Qt.AlignHCenter)
            self.captions.append(caption)
            v.addWidget(caption)
            row = QHBoxLayout()
            row.setContentsMargins(0, 0, 0, 0)
            row.setSpacing(1)
            v.addLayout(row)
            layout.addWidget(box)
            self._sections.append(box)
            return row, box

        for title, tools in SECTIONS:
            row, box = section(title)
            for kind, command, tip, available in tools:
                button = _CadButton(kind, tip, box)
                button.setEnabled(available)
                button.clicked.connect(lambda _c=False, name=command: self._run(name))
                row.addWidget(button)
                self.buttons[command] = button
        row, box = section("Propriétés")
        self.layer_button = _TextButton("0", "Calque courant (ou de la sélection)", box, 110)
        self.layer_button.setFocusPolicy(Qt.NoFocus)
        self.layer_button.clicked.connect(lambda: self.layer_menu(self.layer_button))
        row.addWidget(self.layer_button)
        self.color_button = _CadButton("swatch", "Couleur (ByLayer ou propre)", box, 30)
        self.color_button.clicked.connect(lambda: self.color_menu(self.color_button, target="toolbar"))
        row.addWidget(self.color_button)
        self.weight_button = _TextButton("ByLayer", "Épaisseur (unité de mesure du dessin ; 0 = trait fin)", box, 74)
        self.weight_button.setFocusPolicy(Qt.NoFocus)
        self.weight_button.clicked.connect(lambda: self.weight_menu(self.weight_button))
        row.addWidget(self.weight_button)
        self.linetype_button = _TextButton("ByLayer", "Type de ligne", box, 86)
        self.linetype_button.setFocusPolicy(Qt.NoFocus)
        self.linetype_button.clicked.connect(lambda: self.linetype_menu(self.linetype_button))
        row.addWidget(self.linetype_button)
        row, box = section("Précision")
        self.mode_buttons = {}
        for name, text, tip in PRECISION:
            button = _ModeButton(text, tip, box)
            button.clicked.connect(lambda _c=False, n=name: self.ctl.toggle(n))
            row.addWidget(button)
            self.mode_buttons[name] = button
        settings = _CadButton("cad_settings", "Réglages des accrochages, du suivi et de la grille (OS)", box)
        settings.clicked.connect(self.open_snap_settings)
        row.addWidget(settings)
        row, box = section("Gestion")
        for kind, tip, slot in (("cad_layers", "Gestionnaire des calques (LA)", self.open_layers),
                                ("cad_properties", "Propriétés (Ctrl+1)", self.toggle_properties)):
            button = _CadButton(kind, tip, box)
            button.clicked.connect(slot)
            row.addWidget(button)
            self.buttons[kind] = button
        row, box = section("Réglages")
        button = _CadButton("cad_drawing", "Réglages du dessin en cours (unité, décimales, échelle des types de ligne, "
                                           "grille)", box)
        button.clicked.connect(self.open_drawing_settings)
        row.addWidget(button)
        self.buttons["cad_drawing"] = button

    def _build_command_bar(self):
        from settings_theme import _text_label
        bar, layout = _bar(self.pane, True)
        layout.setSpacing(4)
        self.command_bar = bar
        self.history_label = _text_label("", "value_muted")
        self.history_label.setTextFormat(Qt.RichText)
        self.history_label.setAlignment(Qt.AlignLeft | Qt.AlignBottom)
        self.history_label.setTextInteractionFlags(Qt.TextSelectableByMouse)
        layout.addWidget(self.history_label)
        row = QHBoxLayout()
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(8)
        self.prompt_label = _text_label("Commande :", "card_title")
        row.addWidget(self.prompt_label)
        from settings_cells import _TextField
        self.input = _TextField("", 260)                  # zone de saisie des reglages (fond, bordures, arrondi, police)
        self.input.setPlaceholderText("tapez une commande ou une valeur…")
        self.input.textEdited.connect(self._on_input_edited)
        self.input.returnPressed.connect(self._on_input_return)
        self.input.installEventFilter(self._InputKeys(self))
        row.addWidget(self.input, 1)
        self.hint_label = _text_label("", "value_muted")
        row.addWidget(self.hint_label)
        expand = _CadButton("cad_history", "Agrandir / réduire l'historique (F2)", bar, 26)
        expand.clicked.connect(self.toggle_history)
        row.addWidget(expand)
        layout.addLayout(row)

    class _InputKeys(QWidget):
        """Touches de la barre de commande quand ELLE a le focus : Entree / Echap / Tab / historique / F-keys
        passent par le controleur (le texte reste celui du champ)."""

        def __init__(self, chrome):
            super().__init__()
            self.chrome = chrome

        def eventFilter(self, obj, event):
            from PySide6.QtCore import QEvent
            if event.type() == QEvent.KeyPress:
                key = event.key()
                ctl = self.chrome.ctl
                if ctl.text_prompt():                 # saisie d'un texte : la frappe va au texte (espaces compris)
                    ctl.key_press(event)
                    self.chrome.pane.view.setFocus()
                    return True
                from .cad import FKEYS
                if key in (Qt.Key_Escape, Qt.Key_Tab, Qt.Key_Backtab, Qt.Key_Up, Qt.Key_Down, Qt.Key_F2) or (
                        key in FKEYS) or (key == Qt.Key_Space and not ctl.buffer.strip()):
                    if key == Qt.Key_Space:
                        ctl.submit()
                        self.chrome.pane.view.setFocus()
                        return True
                    ctl.buffer = obj.text()
                    ctl.key_press(event)
                    if key == Qt.Key_Escape:
                        self.chrome.pane.view.setFocus()
                    return True
                if key == Qt.Key_Space and ctl.buffer.strip():
                    ctl.submit()
                    self.chrome.pane.view.setFocus()
                    return True
            return False

    def _build_properties(self):
        from settings_theme import _text_label
        frame, layout = _panel(self.pane, True)
        layout.setContentsMargins(10, 8, 10, 10)
        layout.setSpacing(8)
        self.properties = frame
        head = QHBoxLayout()
        head.setContentsMargins(0, 0, 0, 0)
        self.properties_title = _text_label("Propriétés", "card_title")
        head.addWidget(self.properties_title)
        head.addStretch(1)
        close = _CadButton("close", "Fermer (Ctrl+1)", frame, 24)
        close.clicked.connect(self.toggle_properties)
        head.addWidget(close)
        layout.addLayout(head)
        from PySide6.QtWidgets import QFrame, QScrollArea
        holder = QWidget()
        holder.setAttribute(Qt.WA_TranslucentBackground, True)
        self.properties_body = QVBoxLayout(holder)
        self.properties_body.setContentsMargins(0, 0, 0, 0)
        self.properties_scroll = QScrollArea(frame)          # plus haut que la place : il defile
        self.properties_scroll.setFrameShape(QFrame.NoFrame)
        self.properties_scroll.setWidgetResizable(True)
        self.properties_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.properties_scroll.setStyleSheet("QScrollArea { background: transparent; }")
        self.properties_scroll.viewport().setStyleSheet("background: transparent;")
        self.properties_scroll.setWidget(holder)
        layout.addWidget(self.properties_scroll)
        self.properties_table = None
        self._prop_rows = None
        self._prop_shape = None
        self._prop_cache = {}                     # forme du tableau -> (tableau, lignes) : voir _rebuild_properties
        frame.hide()

    # -- visibilite / place --
    def show(self):
        self.toolbar.show()
        self.command_bar.show()
        self.properties.setVisible(self._properties_open)
        self.sync()
        self.place()

    def hide(self):
        for widget in (self.toolbar, self.command_bar, self.properties):
            widget.hide()

    def widgets(self):
        return [self.toolbar, self.command_bar, self.properties]

    def place(self):
        pane = self.pane
        if not self.ctl.active:
            return
        margin = 16
        for panel in (self.toolbar, self.command_bar, self.properties):
            panel.layout().activate()
        title = pane._title.geometry()
        left = title.right() + 12
        room = pane.width() - left - margin
        self._reflow(pane.width() - 2 * margin)
        self.toolbar.layout().activate()
        self.toolbar.resize(self.toolbar.sizeHint())
        if self.toolbar.width() <= room:            # a cote du nom du board, centree dans la place restante
            self.toolbar.move(left + max(0, (room - self.toolbar.width()) // 2), margin)
        else:                                       # sous le nom du board
            self.toolbar.move(max(pane._toolbar.geometry().right() + 10, (pane.width() - self.toolbar.width()) // 2),
                              title.bottom() + 8)
        zoom_w = pane._zoombar.width() if pane._zoombar.isVisible() else 0
        width = max(360, min(980, pane.width() - 2 * margin - 2 * (zoom_w + 12)))
        self.input.setFixedWidth(max(160, width - self.prompt_label.sizeHint().width() - 200))
        self.command_bar.resize(width, self.command_bar.sizeHint().height())
        self.command_bar.move(max(margin, (pane.width() - width) // 2),
                              pane.height() - self.command_bar.height() - margin)
        if self.properties.isVisible():
            top = self.toolbar.geometry().bottom() + 10
            room = max(160, self.command_bar.geometry().top() - 10 - top)
            table = self.properties_table
            content = table.sizeHint() if table is not None else self.properties_body.sizeHint()
            self.properties_scroll.setFixedWidth(content.width() + 14)
            self.properties_scroll.setFixedHeight(min(content.height() + 2, room - 60))
            self.properties.resize(self.properties.sizeHint().width(), min(self.properties.sizeHint().height(), room))
            self.properties.move(pane.width() - self.properties.width() - margin, top)
        for panel in (self.toolbar, self.command_bar, self.properties):
            panel.raise_()

    def _reflow(self, available: int):
        """Sections sur une rangee, ou deux si la page est trop etroite (rien ne sort de l'ecran)."""
        one_row = sum(box.sizeHint().width() for box in self._sections) + 10 * (len(self._sections) - 1) + 24
        wrap = one_row > available
        if wrap == self._wrapped:
            return
        self._wrapped = wrap
        split = (len(self._sections) + 1) // 2 if wrap else len(self._sections)
        for index, box in enumerate(self._sections):
            for row in self._rows:
                row.removeWidget(box)
            self._rows[0 if index < split else 1].addWidget(box)

    def set_look(self, look: dict):
        """`look` = habillage des barres d'outils du board ; le fond des barres du CAD (barre d'outils et barre de
        commande) est le leur : Reglages > Module CAD > Affichage > « Fond des barres du CAD » (10, 10, 10 d'origine)."""
        self._board_look = look
        self.apply_bar_look()

    def apply_bar_look(self):
        from app_style import resolve_color_ref
        from settings_menu import readable_on
        base = getattr(self, "_board_look", None)
        if base is None:
            return
        back = resolve_color_ref(self.ctl.setting("board_cad_bar_color"), "#0a0a0a")
        if getattr(self, "_look", None) is not None and self._look.get("cad_bar") == back and \
                self._look.get("board_key") == base.get("key"):
            return                                          # rien n'a change : barres non refaites
        look = dict(base)                                   # texte de la barre garanti lisible sur son fond
        look["bg"] = back
        look["board_key"] = base.get("key")
        look["cad_bar"] = back
        look["key"] = f"{base.get('key')}|cad-bar:{back}"
        look["text"] = readable_on(look["text"], look["bg"], 4.5)
        muted = _mix(look["bg"], look["text"], 0.62)
        for bar in (self.toolbar, self.command_bar):
            bar.set_look(look)
        for button in self.mode_buttons.values():
            button.look = look
            button.update()
        css = f"color: {look['text']}; background: transparent;"
        for caption in self.captions:
            caption.setStyleSheet(f"color: {muted}; background: transparent;")
        self.prompt_label.setStyleSheet(css)
        for label in (self.history_label, self.hint_label):
            label.setStyleSheet(f"color: {muted}; background: transparent;")
        tone = _mix(look["bg"], look["text"], 0.08)
        size = look["font"].pixelSize() if look["font"].pixelSize() > 0 else 12
        for button in (self.layer_button, self.weight_button, self.linetype_button):
            button.setStyleSheet(
                f"QPushButton {{ color: {look['text']}; font-size: {size}px; background: {tone}; }} "
                f"QPushButton:hover {{ background: {_mix(look['bg'], look['text'], 0.16)}; }}")
        self._look = look
        self.sync()
        self.place()

    # -- etat --
    def _run(self, name: str):
        self.ctl.run(name)
        self.pane.view.setFocus()

    def sync(self):
        ctl = self.ctl
        if not ctl.active:
            return
        for name, button in self.mode_buttons.items():
            button.set_on(ctl.mode_on(name))
        running = ctl.command.NAME if ctl.command is not None else None
        for name, button in self.buttons.items():
            button.set_on(name == running)
        self.prompt_label.setText(ctl.prompt_line())
        shown = ctl.buffer.replace("\n", " ¶ ") if ctl.text_prompt() else ctl.buffer
        if self.input.text() != shown and not self.input.hasFocus():
            self.input.setText(shown)
        elif self.input.hasFocus() and self.input.text() != ctl.buffer and not ctl.buffer:
            self.input.clear()
        hint = ""
        if ctl.prompt() is None and ctl.buffer.strip() and not any(c.isdigit() for c in ctl.buffer):
            matches = cad_commands.completions(ctl.buffer)
            hint = "  ".join(f"{e.name}" for _w, e in matches[:4]) + ("  (Tab)" if matches else "  ?")
        self.hint_label.setText(hint)
        self._sync_history()
        self._sync_properties_buttons()
        self.place()

    def _sync_history(self):
        from settings_store import M
        count = HISTORY_EXPANDED if self._history_open else HISTORY_LINES
        lines = []
        for text, kind in self.ctl.history:
            lines.extend((line, kind) for line in text.split("\n"))
        lines = lines[-count:]
        from settings_menu import readable_on
        bar_bg = getattr(self, "_look", {}).get("bg", M["panel_bg"])
        colors = {"error": readable_on(M.get("dirty_fg", "#e0524c"), bar_bg, 4.5), "echo": None, "info": None}
        out = []
        for text, kind in lines:
            safe = html.escape(text).replace("  ", "&nbsp;&nbsp;")
            color = colors.get(kind)
            out.append(f'<span style="color:{color}">{safe}</span>' if color else safe)
        while len(out) < count:
            out.insert(0, "&nbsp;")
        self.history_label.setText("<br>".join(out))

    def _sync_properties_buttons(self):
        """Barre d'outils > Proprietes : celles de la selection (valeur commune) ou les COURANTES."""
        ctl = self.ctl
        cad = ctl.cad_page()
        items = ctl.selection()
        if items:
            layers = {i.data.get("layer") for i in items}
            layer = cad_model.effective_layer(cad, next(iter(layers)))["name"] if len(layers) == 1 else "*varié*"
            color = _common([i.data.get("color") for i in items])
            weight = _common([i.data.get("lineweight") for i in items])
            linetype = _common([i.data.get("linetype") for i in items])
        else:
            layer = cad_model.effective_layer(cad, cad["current"])["name"]
            color, weight, linetype = cad["cecolor"], cad["celweight"], cad["celtype"]
        self.layer_button.setText(_elide(layer, 14))
        resolved = color
        if color == cad_model.BYLAYER or color is None:
            layer_id = items[0].data.get("layer") if items else cad["current"]
            resolved = cad_model.effective_layer(cad, layer_id)["color"]
        self.color_button.set_swatch(resolved if isinstance(resolved, str) and resolved.startswith("#") else "#808080")
        self.color_button.setToolTip(f"Couleur : {cad_model.describe_color(color) if color else '*varié*'}")
        self.weight_button.setText(cad_model.describe_weight(weight, ctl.unit()) if weight is not None else "*varié*")
        self.linetype_button.setText(_elide(cad_model.describe_linetype(linetype) if linetype else "*varié*", 10))

    def toggle_history(self):
        self._history_open = not self._history_open
        self.sync()

    def _on_input_edited(self, text):
        self.ctl.buffer = text
        self.ctl.refresh()
        self.hint_label.setText("")

    def _on_input_return(self):
        self.ctl.buffer = self.input.text()
        self.ctl.submit()
        self.input.clear()
        self.pane.view.setFocus()

    def _on_page_changed(self):
        self._props_timer.start()
        self._sync_timer.start()
        if self._layers is not None:
            self._layers.schedule()

    # -- menus --
    def _popup(self, menu, anchor):
        if isinstance(anchor, QWidget):
            menu.popup(anchor.mapToGlobal(anchor.rect().bottomLeft()))
        else:
            menu.popup(anchor)

    def osnap_menu(self, global_pos):
        """Maj + clic droit : accrochage ponctuel pour le point suivant (comme AutoCAD)."""
        menu = _menu(self.pane, "cad_osnap")
        for mode in ("end", "mid", "int", "appint", "ext", "per", "par", "nea", "cen", "qua", "tan", "node",
                     "ins", "gcen"):
            action = menu.addAction(cad_snap.LABELS[mode])
            action.triggered.connect(lambda _c=False, m=mode: self._override(m))
        menu.addSeparator()
        none = menu.addAction("Aucun (point libre)")
        none.triggered.connect(lambda: self._override("none"))
        settings = menu.addAction("Réglages des accrochages…")
        settings.triggered.connect(self.open_snap_settings)
        menu.popup(global_pos)

    def _override(self, mode):
        self.ctl.override = mode
        self.ctl.message(f"Accrochage ponctuel : {cad_snap.LABELS.get(mode, mode)} (point suivant).")
        self.ctl.refresh()

    def context_menu(self, global_pos):
        ctl = self.ctl
        menu = _menu(self.pane, "cad_context")
        if ctl.last_command:
            entry = cad_commands.lookup(ctl.last_command)
            repeat = menu.addAction(f"Répéter {entry.label if entry else ctl.last_command}")
            repeat.triggered.connect(lambda: self._run(ctl.last_command))
            menu.addSeparator()
        for name in ("LINE", "MOVE", "COPY", "ERASE"):
            entry = cad_commands.lookup(name)
            action = menu.addAction(entry.label)
            action.triggered.connect(lambda _c=False, n=name: self._run(n))
        menu.addSeparator()
        if ctl.selection():
            deselect = menu.addAction("Tout désélectionner")
            deselect.triggered.connect(lambda: (ctl.scene.clearSelection(), ctl.refresh()))
        menu.addAction("Propriétés…").triggered.connect(self.show_properties)
        menu.addAction("Calques…").triggered.connect(self.open_layers)
        menu.addAction("Accrochages et suivi…").triggered.connect(self.open_snap_settings)
        menu.popup(global_pos)

    def layer_menu(self, anchor):
        ctl = self.ctl
        cad = ctl.cad_page()
        items = ctl.selection()
        menu = _menu(self.pane, "cad_layer")
        for layer in cad["layers"]:
            mark = "● " if (not items and layer["id"] == cad["current"]) else ""
            flags = ("" if layer["visible"] else "  (masqué)") + ("  (verrouillé)" if layer["locked"] else "")
            action = menu.addAction(f"{mark}{layer['name']}{flags}")
            action.triggered.connect(lambda _c=False, lid=layer["id"]: self.apply_layer(lid))
        menu.addSeparator()
        menu.addAction("Gestionnaire des calques…").triggered.connect(self.open_layers)
        self._popup(menu, anchor)

    def apply_layer(self, layer_id):
        """Selection : ses objets vont sur ce calque ; sans selection : il devient le calque courant."""
        ctl = self.ctl
        items = ctl.selection()
        cad = cad_model.copy_cad(ctl.cad_page())
        layer = cad_model.layer_by_id(cad, layer_id)
        if layer is None:
            return
        if items:
            ctl.change_entities(items, {"layer": layer_id}, f"Calque « {layer['name']} »")
        else:
            cad["current"] = layer_id
            ctl.set_cad(cad, f"Calque courant « {layer['name']} »")
            ctl.message(f"Calque courant : {layer['name']}")
        self.pane.view.setFocus()

    def color_menu(self, anchor, target="toolbar", layer_id=None):
        """Couleur : de la selection (ou couleur courante), ou d'un calque (`layer_id`)."""
        from .model import COLORS
        menu = _menu(self.pane, "cad_color")
        grid = _SwatchGrid(COLORS, None, 6)
        from settings_menu import menu_row

        def pick(color):
            menu.close()
            self.set_color(color, layer_id)
        grid.picked.connect(pick)
        if layer_id is None:
            menu.addAction("ByLayer (couleur du calque)").triggered.connect(lambda: self.set_color(cad_model.BYLAYER))
        menu_row(menu, "Couleur", grid)
        other = menu.addAction("Autre couleur…")
        other.triggered.connect(lambda: QTimer.singleShot(0, lambda: self._custom_color(anchor, layer_id)))
        self._popup(menu, anchor)

    def _custom_color(self, anchor, layer_id):
        from settings_widgets import _ColorPickerPopup
        popup = _ColorPickerPopup("#1a1a1a", "Couleur", self.pane)
        popup.committed.connect(lambda c: self.set_color(QColor(c).name(), layer_id))
        popup.show_near(anchor)

    def set_color(self, color, layer_id=None):
        ctl = self.ctl
        cad = cad_model.copy_cad(ctl.cad_page())
        if layer_id is not None:
            layer = cad_model.layer_by_id(cad, layer_id)
            if layer is not None and color != cad_model.BYLAYER:
                layer["color"] = color
                ctl.set_cad(cad, f"Couleur du calque « {layer['name']} »")
            return
        items = ctl.selection()
        if items:
            ctl.change_entities(items, {"color": color}, "Couleur")
        else:
            cad["cecolor"] = color
            ctl.set_cad(cad, "Couleur courante")
        self.pane.view.setFocus()

    def weight_menu(self, anchor):
        menu = _menu(self.pane, "cad_weight")
        menu.addAction("ByLayer (épaisseur du calque)").triggered.connect(lambda: self.set_weight(cad_model.BYLAYER))
        unit, symbol = self.ctl.unit(), self.ctl.unit_symbol()
        for value in WEIGHTS:                               # dans l'unite du dessin
            action = menu.addAction("0 — trait fin (1 pixel)" if value == 0 else f"{value:g} {symbol}")
            action.triggered.connect(lambda _c=False, v=value: self.set_weight(v * unit))
        menu.addSeparator()
        menu.addAction("Autre valeur… (barre de commande : propriétés)").triggered.connect(self.show_properties)
        self._popup(menu, anchor)

    def set_weight(self, value):
        ctl = self.ctl
        items = ctl.selection()
        if items:
            ctl.change_entities(items, {"lineweight": value}, "Épaisseur")
        else:
            cad = cad_model.copy_cad(ctl.cad_page())
            cad["celweight"] = value
            ctl.set_cad(cad, "Épaisseur courante")
        self.pane.view.setFocus()

    def linetype_menu(self, anchor):
        menu = _menu(self.pane, "cad_linetype")
        menu.addAction("ByLayer (type du calque)").triggered.connect(lambda: self.set_linetype(cad_model.BYLAYER))
        for key, (label, _pattern) in cad_model.LINETYPES.items():
            menu.addAction(label).triggered.connect(lambda _c=False, k=key: self.set_linetype(k))
        self._popup(menu, anchor)

    def set_linetype(self, value):
        ctl = self.ctl
        items = ctl.selection()
        if items:
            ctl.change_entities(items, {"linetype": value}, "Type de ligne")
        else:
            cad = cad_model.copy_cad(ctl.cad_page())
            cad["celtype"] = value
            ctl.set_cad(cad, "Type de ligne courant")
        self.pane.view.setFocus()

    # -- panneau Proprietes --
    def show_properties(self):
        if not self._properties_open:
            self.toggle_properties()

    def toggle_properties(self):
        self._properties_open = not self._properties_open
        self.properties.setVisible(self._properties_open and self.ctl.active)
        if self._properties_open:
            self._rebuild_properties()
        self.buttons["cad_properties"].set_on(self._properties_open)
        self.place()

    def _rebuild_properties(self):
        if not (self._properties_open and self.ctl.active):
            self._sync_timer.start()
            return
        focus = self.properties.focusWidget()
        if isinstance(focus, QLineEdit) and focus.hasFocus() and focus.text() != getattr(focus, "_start", focus.text()):
            # Une saisie EN COURS (texte change, pas encore valide) : apres elle. Un champ seulement focalise ne
            # retarde plus rien (le curseur d'un border radius attendait la sortie du champ : « un temps fou »).
            self._props_timer.start(300)
            return
        builder = self._prop_rows if self._prop_rows is not None else PropertyRows(self)
        specs = builder.specs()
        count = len(self.ctl.selection())
        self.properties_title.setText("Propriétés — " + (f"{count} ligne(s)" if count else "objets créés"))
        shape = builder.shape(specs)
        cached = self._prop_cache.get(shape)
        if cached is None:
            # Forme jamais vue (aucune / une / plusieurs lignes, liste des calques) : tableau construit UNE fois
            # (~70 ms) puis garde ; les suivantes ne font que mettre les valeurs a jour (~1 ms).
            from settings_cells import build_cells_table, normalize_toggles
            import settings_window_v2 as v2
            v2.seed_window_look(full_settings(self.pane))
            builder = PropertyRows(self)
            rows = builder.build(specs)
            frame, head, cells = build_cells_table([("Propriété", 178), ("Valeur", 210)], rows)
            frame._dims_key = "MRO : CAD : propriétés#0"
            normalize_toggles(frame)
            builder.attach_dots(specs, head, cells)
            self.properties_body.addWidget(frame)
            if len(self._prop_cache) >= 6:
                _old_shape, (old_frame, _b) = self._prop_cache.popitem()
                old_frame.hide()
                old_frame.deleteLater()
            cached = self._prop_cache[shape] = (frame, builder)
        else:
            cached[1].update(specs)
        frame, builder = cached
        builder.update_dots()
        self._prop_rows, self._prop_shape = builder, shape
        if self.properties_table is not frame:
            if self.properties_table is not None:
                self.properties_table.hide()
            frame.show()
            self.properties_table = frame
            self.place()

    # -- calques / accrochages --
    def open_layers(self):
        if self._layers is None:
            self._layers = LayerManagerWindow(self)
            self._layers.destroyed.connect(lambda *_a: setattr(self, "_layers", None))
        self._layers.show()
        self._layers.raise_()
        self._layers.activateWindow()

    def open_snap_settings(self):
        """Fenetre des accrochages = « Changement de style a la volee » sur les lignes de Reglages > Module CAD
        (`CAD_GROUPS`, sans les icones) : appliquee en direct, enregistree (fichier + preset actif) 250 ms apres le
        dernier changement."""
        if self._snap_window is not None:
            try:
                self._snap_window.raise_()
                self._snap_window.activateWindow()
                return
            except RuntimeError:
                self._snap_window = None
        import settings_window_v2 as v2
        from settings_quick_style import QuickStyleWindow
        from settings_store import DEFAULT_SETTINGS
        specs = [spec for group in v2.CAD_GROUPS for spec in v2.CATALOG[group]]
        values = {k: v for k, v in DEFAULT_SETTINGS.items() if k.startswith("board_cad_")}
        values.update({k: v for k, v in (self.pane._settings or {}).items() if k.startswith("board_cad_")})
        values.update({k: v for k, v in self.ctl.settings.items() if k.startswith("board_cad_")})
        window = QuickStyleWindow("MRO : CAD : accrochages", specs, values, title="CAD — accrochages et suivi",
                                  settings=full_settings(self.pane), parent=self.pane)
        window.styleChanged.connect(self._on_snap_values)
        window.destroyed.connect(lambda *_a: setattr(self, "_snap_window", None))
        self._snap_window = window
        window.show()

    def _on_snap_values(self, values: dict):
        values = {k: v for k, v in values.items() if k.startswith("board_cad_")}
        self.ctl.settings.update(values)
        self.ctl.apply_settings(self.ctl.settings)          # en direct
        self._snap_pending.update(values)
        self._snap_timer.start()

    # -- reglages du dessin (page « cad » de ce board : overrides des reglages generaux) --
    def drawing_specs(self) -> list:
        """Reglages generaux qu'un dessin peut remplacer : unite, decimales, TOUT le reticule (regroupe), toute la
        grille."""
        import settings_window_v2 as v2
        precision = next(s for s in v2.CATALOG["CAD : Affichage"] if s.key == "board_cad_precision")
        return (list(v2.CATALOG["CAD : Unités"]) + [precision] + list(v2.CATALOG["CAD : Réticule"])
                + list(v2.CATALOG["MRO : Grille"]))

    def drawing_rows(self) -> list:
        """Lignes de la fenetre : (libelle, champ, lecteur, interrupteur). Les reglages remplacables ont leur
        interrupteur d'override dans la 1re colonne, AVANT le libelle (de type 1) : eteint, la ligne suit le reglage
        general (grisee) ; allume, la valeur est celle du dessin. Plus l'echelle des types de ligne et la grille
        affichee, propres au dessin."""
        import settings_window_v2 as v2
        from settings_widgets import _Toggle
        cad = self.ctl.cad_page()
        own = cad_model.drawing_overrides(cad)
        general = full_settings(self.pane)
        values = {**general, **own}
        scope = v2.ScopeValues(values, None)
        rows = []
        for spec in self.drawing_specs():
            field = v2.make_field(spec, scope, general.get("colors") or {})
            toggle = _Toggle(spec.key in own, style_override="toggle1", show_label=False)
            toggle._table_style = "toggle1"                 # de type 1 (demande de l'utilisateur), pas accole a une valeur
            toggle.setToolTip("Propre à ce dessin (éteint : le réglage général)")
            rows.append((spec.label, field, lambda w, sp=spec, tg=toggle: {
                OVERRIDE_TAG + sp.key: tg.isChecked(), **v2.read_spec(sp, w)}, toggle))
        for spec in (v2.Spec("ltscale", "Échelle des types de ligne (LTSCALE)", "text", "1"),
                     v2.Spec("grid", "Grille affichée (F7)", "bool", True)):
            field = v2.make_field(spec, v2.ScopeValues(self._own_values(), None), {})
            rows.append((spec.label, field, lambda w, sp=spec: v2.read_spec(sp, w)))
        return rows

    def _own_values(self) -> dict:
        cad = self.ctl.cad_page()
        return {"ltscale": f"{float(cad.get('ltscale', 1.0)):g}", "grid": self.ctl.grid_on()}

    def open_drawing_settings(self):
        """Barre CAD > Reglages : reglages de CE dessin (enregistres dans le .mro, annulables), en « Changement de style a
        la volee »."""
        if self._drawing_window is not None:
            try:
                self._drawing_window.raise_()
                self._drawing_window.activateWindow()
                return
            except RuntimeError:
                self._drawing_window = None
        from settings_quick_style import QuickStyleWindow
        window = QuickStyleWindow("MRO : CAD : dessin", self.drawing_rows(), {}, title="CAD — réglages du dessin",
                                  settings=full_settings(self.pane), parent=self.pane)
        window.styleChanged.connect(self._on_drawing_values)
        window.destroyed.connect(lambda *_a: setattr(self, "_drawing_window", None))
        self._drawing_window = window
        window.show()

    def _on_drawing_values(self, values: dict):
        self._drawing_values = dict(values)
        self._drawing_timer.start()                          # 400 ms apres le dernier changement : une etape

    def _apply_drawing(self):
        values, self._drawing_values = self._drawing_values, None
        if not values:
            return
        ctl = self.ctl
        cad = cad_model.copy_cad(ctl.cad_page())
        overrides = {key[len(OVERRIDE_TAG):]: values[key[len(OVERRIDE_TAG):]] for key, on in values.items()
                     if key.startswith(OVERRIDE_TAG) and on and key[len(OVERRIDE_TAG):] in values}
        if overrides:
            cad["overrides"] = overrides
        else:
            cad.pop("overrides", None)
        text = str(values.get("ltscale", "")).strip()
        scale = cad_input.parse_number(text)
        if scale is not None and scale > 0:
            cad["ltscale"] = scale
        elif text:
            ctl.message(f"Échelle « {text} » invalide (nombre > 0).", error=True)
        page = {}
        if cad != ctl.cad_page():
            page["cad"] = cad
        if "grid" in values and bool(values["grid"]) != ctl.grid_on():
            page["grid"] = bool(values["grid"])
        if page:
            self.pane.scene.set_page(page, text="Réglages du dessin")
            ctl.refresh()

    def _flush_snap(self):
        values, self._snap_pending = self._snap_pending, {}
        for key, value in values.items():
            self.ctl._write_setting(key, value)           # deja appliquees en direct : seulement ecrites


def full_settings(pane) -> dict:
    """Reglages complets pour l'habillage des tableaux / fenetres (ceux de l'appli par-dessus les defauts)."""
    from settings_store import DEFAULT_SETTINGS
    return {**DEFAULT_SETTINGS, **(pane._settings or {})}


def _common(values):
    values = list(values)
    return values[0] if values and all(v == values[0] for v in values) else None


def _elide(text: str, size: int) -> str:
    return text if len(text) <= size else text[:size - 1] + "…"


# ==========================================================================
# Lignes du panneau Proprietes
# ==========================================================================

class OverrideDot(QWidget):
    """Petit point orange (couleur « modifie » du theme, `M["dirty_fg"]`, sature) en haut a droite d'une cellule : la
    valeur est REMPLACEE (override) ; clic = retour au reglage (calque, type de ligne). `host` le porte, `anchor` (par
    defaut `host`) est la cellule dont il suit le coin haut droit. Dans l'entete du tableau, les titres laissent passer
    la souris : le point est pose sur l'entete elle-meme, au coin de la cellule, sinon il n'est pas cliquable."""

    clicked = Signal()
    SIZE = 14

    def __init__(self, host: QWidget, tip: str, anchor: QWidget | None = None):
        super().__init__(host)
        self._anchor = anchor if anchor is not None else host
        self.setFixedSize(self.SIZE, self.SIZE)
        self.setCursor(Qt.PointingHandCursor)
        self.setToolTip(tip)
        self.setAttribute(Qt.WA_TranslucentBackground, True)
        self._anchor.installEventFilter(self)
        if self._anchor is not host:
            host.installEventFilter(self)
        self._place()
        self.hide()

    def eventFilter(self, obj, event):
        if event.type() in (QEvent.Resize, QEvent.Show, QEvent.Move, QEvent.LayoutRequest):
            self._place()
        return False

    def _place(self):
        host, anchor = self.parentWidget(), self._anchor
        if host is None:
            return
        if anchor is host:
            self.move(host.width() - self.SIZE - 1, 1)
        else:
            self.move(anchor.x() + anchor.width() - self.SIZE - 1, anchor.y() + 1)
        self.raise_()

    @staticmethod
    def color() -> QColor:
        """Orange du theme pousse a la saturation maximale (demande de l'utilisateur : plus sature)."""
        from settings_store import M
        base = QColor(M.get("dirty_fg", "#e8913a"))
        hue = base.hsvHueF()
        return QColor.fromHsvF(hue if hue >= 0 else 0.08, 1.0, 1.0)

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing, True)
        painter.setPen(Qt.NoPen)
        painter.setBrush(self.color())
        painter.drawEllipse(QPointF(self.width() / 2.0, self.height() / 2.0), 3.8, 3.8)
        painter.end()

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.LeftButton and self.rect().contains(event.position().toPoint()):
            self.clicked.emit()


class PropertyRows:
    """Lignes du tableau des proprietes. Sans selection : proprietes COURANTES (objets crees). Une valeur
    differente entre les objets choisis est montree « *varié* » ; la modifier l'applique a tous (une etape
    d'annulation). Coordonnees : une seule ligne choisie. Longueur, angle, delta : calcules, non saisis."""

    def __init__(self, chrome: CadChrome):
        self.chrome = chrome
        self.ctl = chrome.ctl

    def _label(self, text):
        from settings_theme import _text_label
        return (_text_label(text, "row_label"), "left", "center")

    def specs(self) -> list:
        """Contenu du tableau SANS widget : [(cle, libelle, sorte, valeur, extra)] — compare d'une fois a
        l'autre pour mettre les valeurs a jour sur place (refaire le tableau coutait ~90 ms)."""
        ctl = self.ctl
        cad = ctl.cad_page()
        items = ctl.selection()
        unit = ctl.unit()
        symbol = ctl.unit_symbol()
        out = []
        layers = tuple(l["name"] for l in cad["layers"])
        if items:
            layer_ids = {i.data.get("layer") for i in items}
            layer = cad_model.effective_layer(cad, next(iter(layer_ids)))["name"] if len(layer_ids) == 1 else "*varié*"
            color = _common([i.data.get("color") for i in items])
            weight = _common([i.data.get("lineweight") for i in items])
            linetype = _common([i.data.get("linetype") for i in items])
            ends = {k: [i.data.get(k, cad_model.BYTYPE) for i in items] for k in END_KEYS}
            effective = {k: [i.props()[k] for i in items] for k in END_KEYS}
            ltscale = _common([i.data.get("ltscale") for i in items])
            distribute = _common([i.props()["distribute"] for i in items])
            resize = _common([i.props()["resize"] for i in items])
            layer_id = items[0].data.get("layer")
        else:
            layer = cad_model.effective_layer(cad, cad["current"])["name"]
            color, weight, linetype = cad["cecolor"], cad["celweight"], cad["celtype"]
            ends = {k: [cad.get(k, cad_model.BYTYPE)] for k in END_KEYS}
            current = cad_model.resolve({"layer": cad["current"], "linetype": cad["celtype"]}, cad)
            effective = {k: [cad[k] if isinstance(cad.get(k), dict) else current[k]] for k in END_KEYS}
            ltscale = None
            distribute = cad["distribute"] if isinstance(cad.get("distribute"), bool) else \
                bool(cad_model.linetype_def(current["linetype"]).get("distribute", False))
            resize = cad["resize"] if isinstance(cad.get("resize"), bool) else \
                bool(cad_model.linetype_def(current["linetype"]).get("resize", False))
            layer_id = cad["current"]
        out.append(("layer", "Calque", "select", layer, layers + ((layer,) if layer not in layers else ())))
        resolved = color if color not in (None, cad_model.BYLAYER) else cad_model.effective_layer(cad, layer_id)["color"]
        out.append(("color", "Couleur", "color", cad_model.describe_color(color) if color else "*varié*", resolved))
        out.append(("weight", f"Épaisseur ({symbol})", "text",
                    cad_model.describe_weight(weight, unit) if weight is not None else "*varié*",
                    f"ByLayer, 0 (trait fin) ou une valeur ≥ 0 en {symbol}"))
        types = (cad_model.BYLAYER,) + tuple(label for label, _p in cad_model.LINETYPES.values())
        current_type = cad_model.describe_linetype(linetype) if linetype else "*varié*"
        out.append(("linetype", "Type de ligne", "select", current_type,
                    types + ((current_type,) if current_type not in types else ())))
        if items:
            out.append(("ltscale", "Échelle du type", "text", f"{ltscale:g}" if ltscale is not None else "*varié*",
                        "nombre > 0"))
        out.append(("distribute", "Répartir les segments", "bool", bool(distribute),
                    "Cycles entiers + segment additionnel du type, centrés sur la ligne (le motif garde sa taille)"))
        out.append(("resize", "Redimensionner les segments", "bool", bool(resize),
                    "Avec « Répartir » : le motif est allongé ou raccourci pour remplir toute la ligne"))
        single = items[0] if len(items) == 1 else None
        labels = (cad_model.BYTYPE_LABEL,) + tuple(cad_model.END_LABELS[s] for s in cad_model.END_STYLES)
        for index, key in enumerate(END_KEYS):
            title = END_TITLES[key]
            if single is not None and single.kind == "cad_line" and key != "inner":
                point = single.points()[index]
                out.append((f"{key}:x", f"{title} : X", "text", ctl.fmt(point[0]), f"X ({symbol})"))
                out.append((f"{key}:y", f"{title} : Y", "text", ctl.fmt(point[1]), f"Y ({symbol})"))
            styles = {cad_model.describe_end(v) for v in ends[key]}
            style = styles.pop() if len(styles) == 1 else "*varié*"
            out.append((f"{key}:style", f"{title} : terminaison", "select", style,
                        labels + ((style,) if style not in labels else ())))
            first = effective[key][0]
            own = [v for v in ends[key] if isinstance(v, dict)]
            radius = _common([e.get("radius") for e in effective[key]])
            out.append((f"{key}:radius", f"{title} : border radius", "radius",
                        int(round(radius if radius is not None else first.get("radius", 50))),
                        len(own) == len(ends[key]) and all(v.get("style") == "radius" for v in own)))
        if single is not None and single.kind != "cad_line":
            geometry = single.geometry()
            names = {"cad_arc": "Arc", "cad_circle": "Cercle", "cad_pline": "Polyligne", "cad_dim": "Cotation",
                     "cad_hatch": "Hachures",
                     "cad_text": "Texte multiligne" if single.data.get("mtext") else "Texte"}
            out.append(("kind", "Objet", "value", names.get(single.kind, single.kind), None))
            if single.kind in ("cad_arc", "cad_circle"):
                out.append(("center", f"Centre ({symbol})", "value", ctl.fmt_point(geometry["center"]), None))
                out.append(("radius", f"Rayon ({symbol})", "value", ctl.fmt(geometry["radius"]), None))
            if single.kind == "cad_arc":
                out.append(("angles", "Angles de départ / fin", "value",
                            f"{cad_input.format_angle(geometry['start'], 2)} / {cad_input.format_angle(geometry['end'], 2)}",
                            None))
            if single.kind == "cad_hatch":
                style = cad_hatch.style_of(single.data)
                labels = tuple(cad_commands.HATCH_PATTERN_LABELS.values())
                out.append(("hatch_pattern", "Motif", "select", cad_commands.HATCH_PATTERN_LABELS[style["pattern"]], labels))
                out.append(("hatch_angle", "Angle du motif (°)", "text", f"{style['angle']:g}", "degrés"))
                out.append(("hatch_spacing", f"Espacement ({symbol})", "text", ctl.fmt(style["spacing"]),
                            f"en {symbol}"))
                out.append(("contours", "Contours", "value", f"{len(single.data.get('loops') or [])}", None))
            if single.kind == "cad_dim":
                kinds = {"linear": "linéaire", "aligned": "alignée", "radius": "de rayon", "diameter": "de diamètre",
                         "angular": "angulaire"}
                out.append(("dimtype", "Type de cotation", "value", kinds.get(single.data.get("dim_type"), "?"), None))
                out.append(("dimvalue", "Texte affiché", "value", single.measured_text(), None))
                out.append(("dim_str", "Texte imposé (« <> » = valeur mesurée)", "text",
                            str(single.data.get("dim_str") or ""), "Vide = la valeur mesurée."))
            if single.kind == "cad_text":
                style = cad_text.style_of(single.data)
                out.append(("text_value", "Contenu (\\P = nouveau paragraphe)" if style["mtext"] else "Contenu", "text",
                            style["text"].replace("\n", "\\P"), "Texte ; double-clic sur le texte : le modifier en place"))
                out.append(("text_height", f"Hauteur ({symbol})", "text", ctl.fmt(style["height"]),
                            f"hauteur des capitales, en {symbol}"))
                out.append(("text_rot", "Rotation (°)", "text", f"{style['rot']:g}", "degrés"))
                labels = tuple(f"{code} — {label}" for code, label in cad_text.JUSTIFY_LABELS.items())
                out.append(("text_justify", "Justification", "select",
                            f"{style['justify']} — {cad_text.JUSTIFY_LABELS[style['justify']]}", labels))
                out.append(("text_font", "Police", "text", style["font"], "nom d'une police installée"))
                if style["mtext"]:
                    out.append(("text_width", f"Largeur du cadre ({symbol})", "text", ctl.fmt(style["width"]),
                                f"0 = sans retour à la ligne automatique, en {symbol}"))
                out.append(("text_spacing", "Interligne (%)", "text", f"{style['spacing'] * 100:g}",
                            "100 % = 5/3 de la hauteur"))
            if single.kind == "cad_pline":
                out.append(("vertices", "Sommets", "value", f"{len(geometry['vertices'])}"
                            + (" (fermée)" if geometry.get("closed") else ""), None))
            if single.kind != "cad_text":
                out.append(("length", f"Longueur ({symbol})", "value", ctl.fmt(single.length()), None))
        elif single is not None:
            a, b = single.points()
            out.append(("length", f"Longueur ({symbol})", "value", ctl.fmt(single.length()), None))
            out.append(("angle", "Angle", "value", cad_input.format_angle(single.angle(), 2), None))
            out.append(("delta", f"Delta X / Y ({symbol})", "value", f"{ctl.fmt(b[0] - a[0])} / {ctl.fmt(b[1] - a[1])}",
                        None))
        elif items:
            out.append(("total", f"Longueur totale ({symbol})", "value", ctl.fmt(sum(i.length() for i in items)), None))
        return out

    @staticmethod
    def shape(specs) -> tuple:
        return tuple((key, kind, extra if kind == "select" else None) for key, _l, kind, _v, extra in specs)

    def build(self, specs) -> list:
        """Lignes du tableau ; `self.updaters[cle](valeur, extra)` met une valeur a jour sans rien refaire."""
        self.updaters = {}
        rows = []
        handlers = {"layer": self._set_layer, "linetype": self._set_linetype, "weight": self._set_weight,
                    "ltscale": self._set_ltscale, "dim_str": self._set_dim_text,
                    "hatch_pattern": self._set_hatch_pattern, "hatch_angle": self._set_hatch_angle,
                    "hatch_spacing": self._set_hatch_spacing,
                    "text_value": self._set_text_value, "text_height": self._set_text_height,
                    "text_rot": self._set_text_rot, "text_justify": self._set_text_justify,
                    "text_font": self._set_text_font, "text_width": self._set_text_width,
                    "text_spacing": self._set_text_spacing}
        for key, label, kind, value, extra in specs:
            if kind == "select":
                if key.endswith(":style"):
                    handler = (lambda v, k=key.split(":")[0]: self._set_end(k, "style", v))
                else:
                    handler = handlers[key]
                cell = self._select(list(extra), value, handler, key)
            elif kind == "text":
                if ":" in key:
                    end, axis = key.split(":")
                    handler = (lambda t, k=end, a=0 if axis == "x" else 1: self._set_coord(k, a, t))
                else:
                    handler = handlers[key]
                cell = self._text(value, handler, extra, key)
            elif kind == "color":
                cell = self._color_cell(value, extra, key)
            elif kind == "radius":
                cell = self._radius(value, extra, key.split(":")[0], key)
            elif kind == "bool":
                cell = self._toggle(value, extra, key, self._set_distribute if key == "distribute" else self._set_resize)
            else:
                cell = self._value(value, key)
            rows.append([self._label(label), cell])
        return rows

    def update(self, specs):
        for key, _label, _kind, value, extra in specs:
            self.updaters[key](value, extra)

    # -- overrides : points orange --
    def attach_dots(self, specs, head, cells):
        """Un point par ligne dont la propriete peut suivre un reglage (1re colonne, a cote du libelle), un sur le titre
        de cette colonne (au moins une propriete remplacee ; clic = toutes revenues au reglage)."""
        self.dots = {}
        for row, (key, _label, _kind, _value, _extra) in enumerate(specs):
            data_key = OVERRIDE_KEYS.get(key)
            if data_key is not None:
                dot = OverrideDot(cells[row][0], "Remplacée sur cet objet — clic : revenir au réglage")
                dot.clicked.connect(lambda k=data_key: QTimer.singleShot(0, lambda: self.reset([k])))
                self.dots[key] = (dot, data_key)
        self.head_dot = OverrideDot(head, "Au moins une propriété remplacée — clic : toutes reviennent "
                                          "au réglage (calque, type de ligne)", anchor=head._cells[0])
        self.head_dot.clicked.connect(lambda: QTimer.singleShot(0, lambda: self.reset(list(cad_model.FOLLOWING))))
        self.update_dots()

    def overridden_keys(self) -> set:
        items = self.ctl.selection()
        if items:
            return {k for k in cad_model.FOLLOWING if any(cad_model.overridden(i.data, k) for i in items)}
        cad = self.ctl.cad_page()
        return {k for k, (current, default) in cad_model.FOLLOWING.items()
                if current is not None and cad.get(current, default) != default}

    def update_dots(self):
        if not hasattr(self, "dots"):
            return
        keys = self.overridden_keys()
        for dot, data_key in self.dots.values():
            dot.setVisible(data_key in keys)
        self.head_dot.setVisible(bool(keys))

    def reset(self, keys):
        """Proprietes `keys` (cles de l'entite) revenues au reglage : une etape d'annulation."""
        items = self.ctl.editable(self.ctl.selection())
        if self.ctl.selection():
            targets = [i for i in items if any(cad_model.overridden(i.data, k) for k in keys)]
            if targets:
                self.ctl.scene.change_items(targets, lambda item: item.data.update(
                    {k: cad_model.FOLLOWING[k][1] for k in keys}), "Revenir au réglage")
        else:
            def mutate(cad):
                for key in keys:
                    current, default = cad_model.FOLLOWING[key]
                    if current is not None:
                        cad[current] = default
            self._apply_current(mutate, "Propriétés courantes : revenir au réglage")
        self.chrome._rebuild_properties()

    # -- champs --
    def _value(self, text, key):
        from settings_theme import _text_label
        label = _text_label(text, "value")
        self.updaters[key] = lambda value, _e: label.setText(value)
        return (label, "left", "center")

    def _select(self, options, current, on_change, key):
        from settings_widgets import _SelectField
        field = _SelectField(options, current, width=190)
        field.setFocusPolicy(Qt.NoFocus)
        field.changed.connect(lambda value: QTimer.singleShot(0, lambda: on_change(value)))

        def update(value, _extra):
            if field.value() != value:
                field.blockSignals(True)
                field._value = value
                field._sync_text()
                field.blockSignals(False)
        self.updaters[key] = update
        return (field, "left", "center")

    def _text(self, text, on_commit, tip, key):
        from settings_cells import _TextField
        field = _TextField(text, 190)
        field.setToolTip(tip)
        field._start = text

        def commit():
            if field.text() != field._start:
                value = field.text()
                self.chrome.pane.view.setFocus()            # la frappe revient a la page ; le tableau suit
                QTimer.singleShot(0, lambda: on_commit(value))
        field.editingFinished.connect(commit)

        def update(value, _extra):
            field._start = value
            if not field.hasFocus() and field.text() != value:
                field.setText(value)
        self.updaters[key] = update
        return (field, "left", "center")

    def _color_cell(self, text, resolved, key):
        from settings_theme import _text_label
        box = QWidget()
        box.setAttribute(Qt.WA_TranslucentBackground, True)
        row = QHBoxLayout(box)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(6)
        swatch = _CadButton("swatch", "Couleur", box, 28)
        swatch.set_swatch(resolved)
        swatch.clicked.connect(lambda: self.chrome.color_menu(swatch))
        row.addWidget(swatch)
        label = _text_label(text, "value")
        row.addWidget(label)
        row.addStretch(1)

        def update(value, color):
            label.setText(value)
            swatch.set_swatch(color)
        self.updaters[key] = update
        return (box, "left", "center")

    def _toggle(self, value, tip, key, on_change):
        from settings_widgets import _Toggle
        toggle = _Toggle(bool(value), style_override="toggle2", show_label=False)
        toggle.setToolTip(tip)
        toggle.toggled.connect(lambda on: QTimer.singleShot(0, lambda: on_change(on)))

        def update(new, _extra):
            if toggle.isChecked() != bool(new):
                toggle.blockSignals(True)
                toggle.setChecked(bool(new))
                toggle.blockSignals(False)
        self.updaters[key] = update
        return (toggle, "left", "center")

    def _radius(self, value, enabled, end_key, key):
        from settings_widgets import _SliderField
        field = _SliderField(0, 100, int(value), unit="%", slider_width=100, box_width=58)
        field.setEnabled(bool(enabled))
        field.setToolTip("Rayon des coins, en % de la demi-épaisseur (terminaison « Border radius »)")
        timer = QTimer(field)                               # proprietes COURANTES (page) : une etape par geste
        timer.setSingleShot(True)
        timer.setInterval(150)
        timer.timeout.connect(lambda: self._set_end(end_key, "radius", field.value()))

        def changed(value):
            if self.ctl.selection():
                self._live_radius(end_key, value)           # objets : en direct, une etape par geste
            else:
                timer.start()
        field.valueChanged.connect(changed)

        def update(new, on):
            field.setEnabled(bool(on))
            if field.value() != int(new) and not timer.isActive() and not (QApplication.mouseButtons() & Qt.LeftButton):
                field.blockSignals(True)
                field.setValue(int(new))
                field.blockSignals(False)
        self.updaters[key] = update
        return (field, "left", "center")

    def _live_radius(self, key, value):
        """Border radius tire sur la selection : applique a CHAQUE cran (scene.live_change : une seule etape
        d'annulation pour le geste) ; avant, 250 ms d'attente puis une etape par pause."""
        items = self.ctl.editable(self.ctl.selection())
        if not items:
            return

        def change(item):
            own = item.data.get(key)
            end = dict(own) if isinstance(own, dict) else dict(item.props()[key])
            end["radius"] = float(value)
            item.data[key] = end
        self.ctl.scene.live_change(f"cad-radius-{key}", items, change, END_TITLES[key] + " : border radius")

    # -- application (une etape d'annulation chacune) --
    def _apply_current(self, mutate, text):
        cad = cad_model.copy_cad(self.ctl.cad_page())
        mutate(cad)
        self.ctl.set_cad(cad, text)

    def _set_layer(self, name):
        layer = cad_model.layer_by_name(self.ctl.cad_page(), name)
        if layer is not None:
            self.chrome.apply_layer(layer["id"])

    def _set_distribute(self, on: bool):
        items = self.ctl.selection()
        if items:
            self.ctl.change_entities(items, {"distribute": bool(on)}, "Répartir les segments")
        else:
            self._apply_current(lambda cad: cad.update(distribute=bool(on)), "Répartition courante")

    def _set_resize(self, on: bool):
        items = self.ctl.selection()
        if items:
            self.ctl.change_entities(items, {"resize": bool(on)}, "Redimensionner les segments")
        else:
            self._apply_current(lambda cad: cad.update(resize=bool(on)), "Redimensionnement courant")

    def _set_weight(self, text):
        value = _parse_weight(text, self.ctl.unit())
        if value is None:
            self.ctl.message(f"Épaisseur « {text} » invalide : ByLayer, 0 ou une valeur positive.", error=True)
            self.chrome._rebuild_properties()
            return
        self.chrome.set_weight(value)

    def _set_linetype(self, label):
        for key, (name, _p) in cad_model.LINETYPES.items():
            if name == label:
                self.chrome.set_linetype(key)
                return
        if label == cad_model.BYLAYER:
            self.chrome.set_linetype(cad_model.BYLAYER)

    def _set_ltscale(self, text):
        value = cad_input.parse_number(text)
        if value is None or value <= 0:
            self.ctl.message(f"Échelle « {text} » invalide (nombre > 0).", error=True)
            self.chrome._rebuild_properties()
            return
        self.ctl.change_entities(self.ctl.selection(), {"ltscale": value}, "Échelle du type de ligne")

    def _hatches(self):
        return [i for i in self.ctl.selection() if i.kind == "cad_hatch"]

    def _set_hatch_pattern(self, label):
        keys = {v: k for k, v in cad_commands.HATCH_PATTERN_LABELS.items()}
        if self._hatches() and label in keys:
            self.ctl.change_entities(self._hatches(), {"hatch_pattern": keys[label]}, "Motif de hachures")

    def _set_hatch_angle(self, text):
        value = cad_input.parse_number(text)
        if value is None:
            self.ctl.message(f"Angle « {text} » invalide.", error=True)
            self.chrome._rebuild_properties()
            return
        self.ctl.change_entities(self._hatches(), {"hatch_angle": value % 360.0}, "Angle des hachures")

    def _set_hatch_spacing(self, text):
        value = cad_input.parse_number(text)
        if value is None or value <= 0:
            self.ctl.message(f"Espacement « {text} » invalide (nombre > 0).", error=True)
            self.chrome._rebuild_properties()
            return
        self.ctl.change_entities(self._hatches(), {"hatch_spacing": value * self.ctl.unit()}, "Espacement des hachures")

    def _texts(self):
        return [i for i in self.ctl.selection() if i.kind == "cad_text"]

    def _text_number(self, text, what: str, minimum: float | None = 0.0, strict: bool = True):
        value = cad_input.parse_number(text)
        if value is None or (minimum is not None and (value <= minimum if strict else value < minimum)):
            self.ctl.message(f"{what} « {text} » invalide.", error=True)
            self.chrome._rebuild_properties()
            return None
        return value

    def _set_text_value(self, text):
        if not str(text).strip():
            self.ctl.message("Texte vide : refusé (EFFACER pour supprimer le texte).", error=True)
            self.chrome._rebuild_properties()
            return
        self.ctl.change_entities(self._texts(), {"text": str(text).replace("\\P", "\n")}, "Texte")

    def _set_text_height(self, text):
        value = self._text_number(text, "Hauteur")
        if value is not None:
            self.ctl.change_entities(self._texts(), {"height": value * self.ctl.unit()}, "Hauteur du texte")

    def _set_text_rot(self, text):
        value = self._text_number(text, "Angle", None)
        if value is not None:
            self.ctl.change_entities(self._texts(), {"rot": value % 360.0}, "Rotation du texte")

    def _set_text_justify(self, label):
        code = str(label).split(" ")[0]
        if code in cad_text.JUSTIFY:
            self.ctl.change_entities(self._texts(), {"justify": code}, "Justification du texte")

    def _set_text_font(self, text):
        family = str(text).strip()
        if family:
            self.ctl.change_entities(self._texts(), {"font": family}, "Police du texte")

    def _set_text_width(self, text):
        value = self._text_number(text, "Largeur", 0.0, strict=False)
        if value is not None:
            self.ctl.change_entities([i for i in self._texts() if i.data.get("mtext")],
                                     {"width": value * self.ctl.unit()}, "Largeur du texte")

    def _set_text_spacing(self, text):
        value = self._text_number(text, "Interligne")
        if value is not None:
            self.ctl.change_entities(self._texts(), {"spacing": value / 100.0}, "Interligne du texte")

    def _set_dim_text(self, text):
        items = [i for i in self.ctl.selection() if i.kind == "cad_dim"]
        if items:
            self.ctl.change_entities(items, {"dim_str": str(text)}, "Texte de cotation")

    def _set_coord(self, key, axis, text):
        items = self.ctl.selection()
        if len(items) != 1:
            return
        value = cad_input.parse_number(text)
        if value is None:
            self.ctl.message(f"Coordonnée « {text} » invalide (séparateur décimal = le point).", error=True)
            self.chrome._rebuild_properties()
            return
        value *= self.ctl.unit()                            # unite du dessin -> unites du board
        item = items[0]
        a, b = item.points()
        point = list(a if key == "end1" else b)
        point[axis] = value
        other = b if key == "end1" else a
        if geo.distance(point, other) <= geo.EPS:
            self.ctl.message("Les deux extrémités seraient confondues : refusé.", error=True)
            self.chrome._rebuild_properties()
            return
        segment = (tuple(point), other) if key == "end1" else (other, tuple(point))
        self.ctl.set_segments([(item, segment[0], segment[1])], f"Extrémité {key[-1]}")

    def _set_end(self, key, field, value):
        """Terminaison (ou son border radius) du debut, de la fin ou des segments interieurs : « Selon le type » (le
        type de ligne decide) ou une valeur PROPRE a l'objet (override), partie de la terminaison effective."""
        bytype = field == "style" and value == cad_model.BYTYPE_LABEL
        if field == "style" and not bytype:
            value = {label: k for k, label in cad_model.END_LABELS.items()}.get(value)
            if value is None:
                return

        def new_end(own, effective):
            if bytype:
                return cad_model.BYTYPE
            end = dict(own) if isinstance(own, dict) else dict(effective)
            end[field] = value
            return end
        items = self.ctl.selection()
        text = END_TITLES[key] + (" : terminaison" if field == "style" else " : border radius")
        if items:
            changes = {id(i): new_end(i.data.get(key), i.props()[key]) for i in self.ctl.editable(items)}
            if changes:
                self.ctl.scene.change_items([i for i in items if id(i) in changes],
                                            lambda item: item.data.update({key: changes[id(item)]}), text)
        else:
            cad = self.ctl.cad_page()
            current = cad_model.resolve({"layer": cad["current"], "linetype": cad["celtype"]}, cad)
            self._apply_current(lambda c: c.update({key: new_end(c.get(key), current[key])}), text + " (courante)")
        if field == "style":
            self.chrome._rebuild_properties()               # curseur du rayon actif / grise TOUT DE SUITE


END_KEYS = ("end1", "end2", "inner")
# Ligne du panneau -> propriete de l'entite qui peut suivre un reglage (point orange quand elle est remplacee).
OVERRIDE_KEYS = {"color": "color", "weight": "lineweight", "linetype": "linetype", "ltscale": "ltscale",
                 "distribute": "distribute", "resize": "resize", **{f"{k}:{f}": k for k in ("end1", "end2", "inner")
                                                for f in ("style", "radius")}}
END_TITLES = {"end1": "Extrémité 1", "end2": "Extrémité 2", "inner": "Segments intérieurs"}


def _parse_weight(text: str, unit: float = 1.0):
    word = (text or "").strip().lower()
    if word in ("bylayer", "ducalque", "du calque", ""):
        return cad_model.BYLAYER
    word = word.split(" ")[0]
    value = cad_input.parse_number(word)
    if value is None or value < 0:
        return None
    return float(value) * unit


# ==========================================================================
# Gestionnaire des calques
# ==========================================================================

class LayerManagerWindow(QDialog):
    """Fenetre outil (fenetres additionnelles) : une ligne par calque — courant, nom, visible, verrouille,
    couleur, type de ligne, epaisseur, nombre d'objets, ordre, suppression. Tout changement est une etape
    d'annulation du board et s'enregistre avec lui."""

    NAME = "MRO : CAD : calques"

    def __init__(self, chrome: CadChrome):
        super().__init__(chrome.pane)
        import settings_window_v2 as v2
        from settings_store import M
        from settings_widgets import _TABLE_DIMS
        from settings_window import _PanelFrame, _SettingsTitleBar, install_extra_window
        self.chrome = chrome
        self.ctl = chrome.ctl
        self.setWindowFlags(Qt.Tool | Qt.FramelessWindowHint)
        self.setAttribute(Qt.WA_DeleteOnClose, True)
        settings = full_settings(chrome.pane)
        v2.seed_window_look(settings)
        self._dims_key = f"{self.NAME}#0"
        saved = (settings.get("table_dims") or {}).get(self._dims_key)
        if saved:
            _TABLE_DIMS[self._dims_key] = saved
        panel = _PanelFrame(self)
        panel.setColors(M["panel_bg"], M["panel_border"])
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.addWidget(panel)
        root = QVBoxLayout(panel)
        root.setContentsMargins(1, 1, 1, 1)
        root.setSpacing(0)
        bar = _SettingsTitleBar(self, title="CAD — calques")
        bar.dirty_label.hide()
        bar.closeClicked.connect(self.close)
        root.addWidget(bar)
        self.body = QWidget()
        self.body.setStyleSheet("background: transparent;")
        self.body_l = QVBoxLayout(self.body)
        self.body_l.setContentsMargins(16, 14, 16, 16)
        self.body_l.setSpacing(10)
        root.addWidget(self.body)
        self.table = None
        foot = QHBoxLayout()
        foot.setSpacing(8)
        from settings_widgets import _Btn
        new = _Btn("Nouveau calque", M["accent"], M["accent_border"], M["accent_fg"], M["accent_hover"], height=25,
                   weight=600, padding="0 13px")
        new.clicked.connect(self._new)
        foot.addWidget(new)
        move = _Btn("Sélection → calque courant", M["btn_bg"], M["btn_border"], M["btn_fg"], M["btn_hover"],
                    height=25, padding="0 11px")
        move.clicked.connect(self._selection_to_current)
        foot.addWidget(move)
        foot.addStretch(1)
        from settings_theme import _text_label
        self.status = _text_label("", "value_muted")
        foot.addWidget(self.status)
        self.foot = foot
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.setInterval(180)                        # apres la bascule animee d'un toggle
        self._timer.timeout.connect(self._rebuild)
        self._rebuild()
        self.body_l.addLayout(foot)
        install_extra_window(self, panel, outer, root, bar)

    def schedule(self):
        self._timer.start()

    def _rebuild(self):
        from settings_cells import _TextField, build_cells_table, normalize_toggles
        from settings_widgets import _SelectField, _Toggle
        from settings_theme import _text_label
        cad = self.ctl.cad_page()
        counts = {}
        selected_layers = set()
        for item in self.ctl.cad_items():
            counts[item.data.get("layer")] = counts.get(item.data.get("layer"), 0) + 1
            if item.isSelected():
                selected_layers.add(item.data.get("layer"))
        rows = []
        for index, layer in enumerate(cad["layers"]):
            lid = layer["id"]
            current = _Toggle(lid == cad["current"], style_override="toggle2", show_label=False)
            current.toggled.connect(lambda on, l=lid: on and self._set_current(l))
            name = _TextField(layer["name"], 150)
            name.setReadOnly(lid == cad_model.LAYER0)
            name.setToolTip("Le calque 0 ne se renomme pas" if lid == cad_model.LAYER0 else "Nom du calque")
            name.editingFinished.connect(lambda f=name, l=lid: self._rename(l, f.text()))
            visible = _Toggle(layer["visible"], style_override="toggle2", show_label=False)
            visible.toggled.connect(lambda on, l=lid: self._set(l, "visible", on, "Visibilité du calque"))
            locked = _Toggle(layer["locked"], style_override="toggle2", show_label=False)
            locked.toggled.connect(lambda on, l=lid: self._set(l, "locked", on, "Verrou du calque"))
            color = _CadButton("swatch", "Couleur du calque", None, 28)
            color.set_swatch(layer["color"])
            color.clicked.connect(lambda _c=False, b=color, l=lid: self.chrome.color_menu(b, layer_id=l))
            labels = [label for label, _p in cad_model.LINETYPES.values()]
            linetype = _SelectField(labels, cad_model.describe_linetype(layer["linetype"]), width=110)
            linetype.changed.connect(lambda v, l=lid: self._set_linetype(l, v))
            weight = _TextField(cad_model.describe_weight(layer["lineweight"], self.chrome.ctl.unit()).replace(
                "fin (0)", "0"), 64)
            weight.setToolTip(f"Épaisseur du calque (en {self.chrome.ctl.unit_symbol()} ; 0 = trait fin)")
            weight.editingFinished.connect(lambda f=weight, l=lid: self._set_weight(l, f.text()))
            count = _text_label(str(counts.get(lid, 0)) + (" ●" if lid in selected_layers else ""), "value")
            count.setToolTip("Objets du calque (● : il porte des objets sélectionnés)")
            actions = QWidget()
            actions.setAttribute(Qt.WA_TranslucentBackground, True)
            box = QHBoxLayout(actions)
            box.setContentsMargins(0, 0, 0, 0)
            box.setSpacing(4)
            from settings_widgets import _Btn
            from settings_store import M
            for text, tip, step in (("↑", "Monter", -1), ("↓", "Descendre", 1)):
                button = _Btn(text, M["btn_bg"], M["btn_border"], M["btn_fg"], M["btn_hover"], height=25,
                              padding="0 8px")
                button.setToolTip(tip)
                button.setEnabled(0 <= index + step < len(cad["layers"]))
                button.clicked.connect(lambda _c=False, l=lid, s=step: self._move(l, s))
                box.addWidget(button)
            delete = _Btn("Supprimer", M["btn_bg"], M["btn_border"], M["btn_fg"], M["btn_hover"], height=25,
                          padding="0 9px")
            delete.setEnabled(lid != cad_model.LAYER0 and lid != cad["current"])
            delete.setToolTip("Ni le calque 0, ni le calque courant" if not delete.isEnabled() else "Supprimer")
            delete.clicked.connect(lambda _c=False, l=lid: self._delete(l))
            box.addWidget(delete)
            box.addStretch(1)
            rows.append([(current, "center", "center"), name, (visible, "center", "center"),
                         (locked, "center", "center"), (color, "center", "center"), linetype, weight,
                         (count, "center", "center"), actions])
        frame, _head, _cells = build_cells_table(
            [("Courant", 76), ("Nom", 170), ("Visible", 70), ("Verrou", 70), ("Couleur", 70),
             ("Type de ligne", 130), ("Épaisseur", 84), ("Objets", 64), ("Ordre / actions", 190)], rows)
        frame._dims_key = self._dims_key
        normalize_toggles(frame)
        if self.table is not None:
            self.body_l.replaceWidget(self.table, frame)
            self.table.hide()
            self.table.deleteLater()
        else:
            self.body_l.insertWidget(0, frame, 0, Qt.AlignLeft | Qt.AlignTop)
        self.table = frame
        QTimer.singleShot(0, self.adjustSize)

    # -- actions (une etape d'annulation chacune) --
    def _copy(self):
        return cad_model.copy_cad(self.ctl.cad_page())

    def _say(self, text, error=False):
        self.status.setText(text)
        self.ctl.message(text, error=error)

    def _new(self):
        cad = self._copy()
        layer = dict(cad_model.LAYER_DEFAULTS, id=cad_model.new_layer_id(cad), name=cad_model.unique_layer_name(cad))
        cad["layers"].append(layer)
        self.ctl.set_cad(cad, f"Nouveau calque « {layer['name']} »")
        self._say(f"Calque « {layer['name']} » créé.")

    def _set_current(self, lid):
        cad = self._copy()
        if cad["current"] == lid:
            return
        cad["current"] = lid
        layer = cad_model.layer_by_id(cad, lid)
        self.ctl.set_cad(cad, f"Calque courant « {layer['name']} »")
        self._say(f"Calque courant : {layer['name']}")

    def _rename(self, lid, name):
        cad = self._copy()
        layer = cad_model.layer_by_id(cad, lid)
        if layer is None or lid == cad_model.LAYER0 or name.strip() == layer["name"]:
            return
        error = cad_model.valid_layer_name(cad, name, lid)
        if error:
            self._say(error, error=True)
            self.schedule()
            return
        old = layer["name"]
        layer["name"] = name.strip()
        self.ctl.set_cad(cad, f"Renommer le calque « {old} »")

    def _set(self, lid, key, value, text):
        cad = self._copy()
        layer = cad_model.layer_by_id(cad, lid)
        if layer is None or layer[key] == value:
            return
        layer[key] = value
        self.ctl.set_cad(cad, f"{text} « {layer['name']} »")

    def _set_linetype(self, lid, label):
        for key, (name, _p) in cad_model.LINETYPES.items():
            if name == label:
                self._set(lid, "linetype", key, "Type de ligne du calque")

    def _set_weight(self, lid, text):
        value = cad_input.parse_number(text)
        if value is None or value < 0:
            self._say(f"Épaisseur « {text} » invalide (nombre ≥ 0).", error=True)
            self.schedule()
            return
        self._set(lid, "lineweight", float(value) * self.ctl.unit(), "Épaisseur du calque")

    def _move(self, lid, step):
        cad = self._copy()
        layers = cad["layers"]
        index = next(i for i, l in enumerate(layers) if l["id"] == lid)
        other = index + step
        if not 0 <= other < len(layers):
            return
        layers[index], layers[other] = layers[other], layers[index]
        self.ctl.set_cad(cad, "Ordre des calques")

    def _delete(self, lid):
        cad = self._copy()
        layer = cad_model.layer_by_id(cad, lid)
        if layer is None or lid in (cad_model.LAYER0, cad["current"]):
            return
        items = [i for i in self.ctl.cad_items() if i.data.get("layer") == lid]
        if items:
            from settings_dialogs import confirm
            if not confirm(self, "CAD", "Supprimer le calque",
                           f"Le calque « {layer['name']} » contient {len(items)} objet(s) : ils passeront sur le "
                           "calque 0 (annulable).", [], "Supprimer le calque"):
                return
        cad["layers"] = [l for l in cad["layers"] if l["id"] != lid]
        if items:
            self.ctl.set_cad_and_items(cad, {i: {"layer": cad_model.LAYER0} for i in items},
                                       f"Supprimer le calque « {layer['name']} »")
        else:
            self.ctl.set_cad(cad, f"Supprimer le calque « {layer['name']} »")
        self._say(f"Calque « {layer['name']} » supprimé.")

    def _selection_to_current(self):
        cad = self.ctl.cad_page()
        items = self.ctl.selection()
        if not items:
            self._say("Aucun objet sélectionné.", error=True)
            return
        self.chrome.apply_layer(cad["current"])

    def closeEvent(self, event):
        if self.table is not None:
            try:
                from settings_store import load_settings, save_live_state
                from settings_widgets import _TABLE_DIMS
                dims = self.table.collectDims()
                _TABLE_DIMS[self._dims_key] = dims
                all_dims = dict(load_settings().get("table_dims") or {})
                all_dims[self._dims_key] = dims
                save_live_state("table_dims", all_dims)
            except Exception:                               # noqa: BLE001 - la mise en forme seulement
                pass
        super().closeEvent(event)

    def showEvent(self, event):
        super().showEvent(event)
        from app_style import apply_dwm_frame
        apply_dwm_frame(self, 0, "none", resizable=False)
