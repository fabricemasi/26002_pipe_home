"""`BoardPane` : le board pose sur la zone des colonnes de la fenetre principale (qu'il recouvre).

- barre d'outils a gauche : selection, main, post-it, texte, FORMES (menu de toutes les formes), connecteur,
  DESSIN (ouvre la barre de dessin), commentaire, cadre, image ; en bas : REGLAGES DE LA PAGE (couleur du
  canvas, grille, commentaires resolus, options d'export, import / export Miro) ;
- barre de DESSIN (capture 3 de l'utilisateur, fonctions de Miro) : stylo, surligneur, dessin intelligent,
  gomme, gomme de precision, lasso, puis 3 PRESETS (couleur + epaisseur) par outil ; re-cliquer le preset
  choisi = le modifier (retenu dans les reglages de l'appli, `board_pen_presets`) ; gomme de precision : S / M / L ;
- barre CONTEXTUELLE au-dessus de la selection (capture 4) : forme, police, taille, style du texte, alignement,
  lien, couleur du texte, surlignage, contour (couleur, epaisseur, style, opacite, ARRONDI DES ANGLES), fond
  (couleur, opacite), fleche (forme, extremites), commentaire, verrou, plus (dupliquer, ordre, rotation...) ;
  une sélection MULTIPLE : chaque commande s'applique a tous les elements qui ont la propriete (une etape
  d'annulation), la valeur montree est celle du premier ;
- fil de COMMENTAIRE (messages dates, modifier, supprimer, resoudre / rouvrir, supprimer le fil) ;
- zoom en bas a droite, nom + etat en haut a gauche.
Menus : `settings_menu.Menu` / `menu_row` et champs des reglages (curseurs, couleurs). Enregistrement
AUTOMATIQUE 800 ms apres chaque changement (et a la fermeture, avec la vue) ; images inutilisees retirees du
dossier du board aux moments surs (voir `serialization`)."""
from __future__ import annotations

import math
import time
from pathlib import Path

from PySide6.QtCore import QEasingCurve, QEvent, QPointF, QPropertyAnimation, QRect, QRectF, QSize, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QPainter, QPainterPath, QPen, QPixmap, QPolygonF
from PySide6.QtWidgets import (
    QAbstractButton, QFileDialog, QFontDialog, QGraphicsOpacityEffect, QGridLayout, QHBoxLayout, QInputDialog,
    QMessageBox, QPlainTextEdit, QPushButton, QVBoxLayout, QWidget,
)

from fm_cad import cad_aliases, cad_model
from . import export, model, serialization
from fm_miro import miro_io
from fm_miro.items import BoardItem, CommentItem, max_radius, shape_path
from .scene import BoardScene
from .view import DRAW_TOOLS, ERASER_SIZES, BoardView, paint_render_badge

AUTOSAVE_MS = 800
FADE_MS = 160
TOOLS = [("select", "Sélection (V)"), ("hand", "Main (H, ou Espace)"), ("sticky", "Post-it (N)"),
         ("text", "Texte (T)"), ("shape", "Formes (S ; R rectangle, O ellipse)"), ("connector", "Connecteur (L)"),
         ("draw", "Dessin à main levée (P)"), ("comment", "Commentaire (C)"), ("frame", "Cadre (F)"),
         ("image", "Image depuis un fichier…")]
# Selecteur de modules (demande de l'utilisateur) : a l'ouverture, aucune barre d'outils, seulement ces boutons ; la
# barre d'outils d'un module s'affiche quand il est active. Par module : griser, masquer ses elements.
MODULES = [("miro", "Miro", "Module Miro : post-it, textes, formes, dessin, commentaires (sa barre d'outils)"),
           ("cad", "CAD", "Module CAD : dessin technique 2D (lignes, calques, accrochages, barre de commande)"),
           ("design", "Design", "Module Design : pages, formes, textes, images, modèles, export (à la manière de Canva)")]
DRAW_BAR = [("pen", "Stylo"), ("highlighter", "Surligneur"), ("smart", "Dessin intelligent (formes reconnues)"),
            ("eraser", "Gomme (traits entiers)"), ("precision_eraser", "Gomme de précision (coupe les traits)"),
            ("lasso", "Lasso (sélection à main levée)")]
DEFAULT_PRESETS = {
    # Mesures sur la capture 3 : noir fin (choisi), rouge #ee7168 moyen, vert #62c167 epais.
    "pen": [{"color": model.MIRO_INK, "width": 2.0}, {"color": "#ee7168", "width": 4.0},
            {"color": "#62c167", "width": 8.0}],
    "highlighter": [{"color": "#fac710", "width": 16.0, "opacity": 0.45},
                    {"color": "#8fd14f", "width": 16.0, "opacity": 0.45},
                    {"color": "#ee7168", "width": 24.0, "opacity": 0.45}],
    "smart": [{"color": model.MIRO_INK, "width": 2.0}, {"color": "#ee7168", "width": 4.0},
              {"color": "#3663f7", "width": 4.0}],
}
COLOR_KEYS = {"sticky": "color", "shape": "fill", "frame": "fill"}
# Icones reglables (Reglages > Module MRO > Icones) : un glyphe peint par defaut ; une icone perso la remplace.
# `ICON_PROVIDER(kind, taille)` -> QPixmap | None est pose par l'appli (le paquet ne connait pas ses icones).
ICON_PROVIDER = None
# `SETTING_WRITER(cle, valeur)` est pose par l'appli : enregistre un reglage de l'appli (Reglages > Module MRO) et le
# fait suivre a la fenetre de reglages ; sans lui, le changement ne vaut que pour la session.
SETTING_WRITER = None
ICON_ROWS = model.ICON_ROWS


def custom_icon(kind: str, size: int):
    provider = ICON_PROVIDER
    if provider is None:
        return None
    try:
        return provider(kind.replace(":", "_"), size)
    except Exception:                                   # noqa: BLE001 - une icone illisible : le glyphe reste
        return None
TEXT_KINDS = ("sticky", "text", "shape")


def paint_glyph(painter: QPainter, kind: str, rect: QRectF, color: QColor):
    """Icones des outils et commandes (traits, comme les glyphes des boutons de l'appli)."""
    if kind.startswith("cad"):
        from fm_cad.cad_ui import paint_cad_glyph              # module CAD : ses icones
        paint_cad_glyph(painter, kind, rect, color)
        return
    if kind.startswith("design"):
        from fm_design.glyphs import paint_design_glyph        # module Design : ses icones
        paint_design_glyph(painter, kind, rect, color)
        return
    pen = QPen(color, 1.4)
    pen.setCapStyle(Qt.RoundCap)
    pen.setJoinStyle(Qt.RoundJoin)
    painter.setPen(pen)
    painter.setBrush(Qt.NoBrush)
    c = rect.center()
    s = min(rect.width(), rect.height()) * 0.2
    cx, cy = c.x(), c.y()
    if kind.startswith("shape:"):
        painter.drawPath(shape_path(kind[6:], QRectF(cx - s * 1.5, cy - s * 1.1, s * 3.0, s * 2.2), s * 0.5))
        return
    if kind == "select":
        painter.setBrush(color)
        painter.drawPolygon(QPolygonF([QPointF(cx - s * 1.0, cy - s * 1.5), QPointF(cx + s * 1.1, cy + s * 0.3),
                                       QPointF(cx + s * 0.05, cy + s * 0.45), QPointF(cx - s * 0.4, cy + s * 1.5)]))
    elif kind == "hand":
        painter.drawRoundedRect(QRectF(cx - s * 1.0, cy - s * 0.2, s * 2.0, s * 1.7), s * 0.6, s * 0.6)
        for i in range(4):
            x = cx - s * 0.75 + i * s * 0.5
            painter.drawLine(QPointF(x, cy - s * 0.1), QPointF(x, cy - s * (1.1 + (0.3 if i in (1, 2) else 0))))
    elif kind == "sticky":
        painter.drawPolygon(QPolygonF([QPointF(cx - s * 1.4, cy - s * 1.4), QPointF(cx + s * 1.4, cy - s * 1.4),
                                       QPointF(cx + s * 1.4, cy + s * 0.6), QPointF(cx + s * 0.6, cy + s * 1.4),
                                       QPointF(cx - s * 1.4, cy + s * 1.4)]))
        painter.drawPolyline(QPolygonF([QPointF(cx + s * 1.4, cy + s * 0.6), QPointF(cx + s * 0.6, cy + s * 0.6),
                                        QPointF(cx + s * 0.6, cy + s * 1.4)]))
    elif kind == "text":
        painter.drawLine(QPointF(cx - s * 1.3, cy - s * 1.3), QPointF(cx + s * 1.3, cy - s * 1.3))
        painter.drawLine(QPointF(cx, cy - s * 1.3), QPointF(cx, cy + s * 1.4))
    elif kind == "shape":
        painter.drawRect(QRectF(cx - s * 1.5, cy - s * 0.2, s * 1.7, s * 1.7))
        painter.drawEllipse(QPointF(cx + s * 0.6, cy - s * 0.5), s * 0.95, s * 0.95)
    elif kind == "connector":
        a, b = QPointF(cx - s * 1.4, cy + s * 1.4), QPointF(cx + s * 1.4, cy - s * 1.4)
        painter.drawLine(a, b)
        painter.drawPolyline(QPolygonF([QPointF(b.x() - s * 1.1, b.y()), b, QPointF(b.x(), b.y() + s * 1.1)]))
    elif kind in ("draw", "pen"):
        painter.save()
        painter.translate(cx, cy)
        painter.rotate(45)
        painter.drawRoundedRect(QRectF(-s * 0.45, -s * 1.7, s * 0.9, s * 2.6), s * 0.2, s * 0.2)
        painter.drawPolygon(QPolygonF([QPointF(-s * 0.45, s * 0.9), QPointF(s * 0.45, s * 0.9),
                                       QPointF(0, s * 1.7)]))
        painter.restore()
    elif kind == "highlighter":
        painter.save()
        painter.translate(cx, cy)
        painter.rotate(45)
        painter.drawRect(QRectF(-s * 0.7, -s * 1.6, s * 1.4, s * 2.0))
        painter.drawPolygon(QPolygonF([QPointF(-s * 0.7, s * 0.4), QPointF(s * 0.7, s * 0.4), QPointF(s * 0.35, s * 1.3),
                                       QPointF(-s * 0.35, s * 1.3)]))
        painter.restore()
        painter.drawLine(QPointF(cx - s * 1.6, cy + s * 1.6), QPointF(cx - s * 0.2, cy + s * 1.6))
    elif kind == "smart":
        painter.drawEllipse(QPointF(cx - s * 0.5, cy + s * 0.4), s * 0.9, s * 0.9)
        painter.drawRect(QRectF(cx, cy - s * 1.4, s * 1.3, s * 1.3))
        painter.drawLine(QPointF(cx - s * 1.5, cy - s * 1.0), QPointF(cx - s * 0.9, cy - s * 1.0))
        painter.drawLine(QPointF(cx - s * 1.2, cy - s * 1.3), QPointF(cx - s * 1.2, cy - s * 0.7))
    elif kind in ("eraser", "precision_eraser"):
        painter.save()
        painter.translate(cx, cy)
        painter.rotate(-40)
        painter.drawRoundedRect(QRectF(-s * 1.5, -s * 0.7, s * 3.0, s * 1.4), s * 0.3, s * 0.3)
        painter.drawLine(QPointF(-s * 0.3, -s * 0.7), QPointF(-s * 0.3, s * 0.7))
        painter.restore()
        if kind == "precision_eraser":
            painter.setBrush(color)
            for i in range(3):
                painter.drawEllipse(QPointF(cx + s * (0.6 + i * 0.45), cy + s * 1.5), s * 0.12, s * 0.12)
    elif kind == "lasso":
        painter.setPen(QPen(color, 1.4, Qt.DashLine))
        painter.drawEllipse(QPointF(cx, cy - s * 0.3), s * 1.4, s * 1.0)
        painter.setPen(pen)
        painter.drawLine(QPointF(cx - s * 0.6, cy + s * 0.6), QPointF(cx - s * 0.9, cy + s * 1.6))
    elif kind == "comment":
        path = QPainterPath()
        path.addRoundedRect(QRectF(cx - s * 1.5, cy - s * 1.3, s * 3.0, s * 2.1), s * 0.5, s * 0.5)
        painter.drawPath(path)
        painter.drawLine(QPointF(cx - s * 0.6, cy + s * 0.8), QPointF(cx - s * 1.0, cy + s * 1.5))
    elif kind == "frame":
        for x in (cx - s * 0.8, cx + s * 0.8):
            painter.drawLine(QPointF(x, cy - s * 1.6), QPointF(x, cy + s * 1.6))
        for y in (cy - s * 0.8, cy + s * 0.8):
            painter.drawLine(QPointF(cx - s * 1.6, y), QPointF(cx + s * 1.6, y))
    elif kind == "image":
        frame = QRectF(cx - s * 1.5, cy - s * 1.15, s * 3.0, s * 2.3)
        painter.drawRoundedRect(frame, s * 0.25, s * 0.25)
        painter.drawPolyline(QPolygonF([QPointF(frame.left() + s * 0.3, frame.bottom() - s * 0.3),
                                        QPointF(cx - s * 0.3, cy - s * 0.1), QPointF(cx + s * 0.3, cy + s * 0.5),
                                        QPointF(cx + s * 0.7, cy + s * 0.15),
                                        QPointF(frame.right() - s * 0.3, frame.bottom() - s * 0.3)]))
    elif kind == "page":
        r = s * 1.5
        painter.drawEllipse(QPointF(cx, cy), r * 0.45, r * 0.45)
        import math
        for i in range(8):
            ang = math.radians(i * 45)
            painter.drawLine(QPointF(cx + math.cos(ang) * r * 0.7, cy + math.sin(ang) * r * 0.7),
                             QPointF(cx + math.cos(ang) * r, cy + math.sin(ang) * r))
    elif kind == "grid":                                    # grille : 3 x 3 cases
        r = s * 1.2
        for n in range(4):
            v = -r + n * 2 * r / 3
            painter.drawLine(QPointF(cx + v, cy - r), QPointF(cx + v, cy + r))
            painter.drawLine(QPointF(cx - r, cy + v), QPointF(cx + r, cy + v))
    elif kind == "miro":                                    # module Miro : post-it
        paint_glyph(painter, "sticky", rect, color)
    elif kind == "fade":                                    # griser : carre plein en transparence
        faded = QColor(color)
        faded.setAlpha(90)
        box = QRectF(cx - s * 1.3, cy - s * 1.3, s * 2.6, s * 2.6)
        painter.fillRect(box, faded)
        painter.drawRect(box)
    elif kind == "hide":                                    # masquer : oeil barre
        eye = QPainterPath()
        eye.moveTo(cx - s * 1.6, cy)
        eye.quadTo(cx, cy - s * 1.7, cx + s * 1.6, cy)
        eye.quadTo(cx, cy + s * 1.7, cx - s * 1.6, cy)
        painter.drawPath(eye)
        painter.drawEllipse(QPointF(cx, cy), s * 0.5, s * 0.5)
        painter.drawLine(QPointF(cx - s * 1.4, cy + s * 1.4), QPointF(cx + s * 1.4, cy - s * 1.4))
    elif kind == "invert":                                  # negatif : disque a moitie plein
        r = s * 1.2
        painter.drawEllipse(QPointF(cx, cy), r, r)
        half = QPainterPath()
        half.moveTo(cx, cy - r)
        half.arcTo(QRectF(cx - r, cy - r, 2 * r, 2 * r), 90, 180)
        half.closeSubpath()
        painter.fillPath(half, color)
    elif kind == "close":
        painter.drawLine(QPointF(cx - s, cy - s), QPointF(cx + s, cy + s))
        painter.drawLine(QPointF(cx - s, cy + s), QPointF(cx + s, cy - s))
    elif kind in ("minus", "plus"):
        painter.drawLine(QPointF(cx - s, cy), QPointF(cx + s, cy))
        if kind == "plus":
            painter.drawLine(QPointF(cx, cy - s), QPointF(cx, cy + s))
    elif kind == "fit":
        for sx, sy in ((-1, -1), (1, -1), (1, 1), (-1, 1)):
            corner = QPointF(cx + sx * s * 1.3, cy + sy * s * 1.3)
            painter.drawLine(corner, QPointF(corner.x() - sx * s * 0.8, corner.y()))
            painter.drawLine(corner, QPointF(corner.x(), corner.y() - sy * s * 0.8))
    elif kind == "frame_format":
        painter.drawRect(QRectF(cx - s * 1.0, cy - s * 1.4, s * 2.0, s * 2.8))
        painter.drawLine(QPointF(cx - s * 1.6, cy + s * 1.0), QPointF(cx + s * 1.6, cy - s * 1.0))
    elif kind == "lock":
        painter.drawRect(QRectF(cx - s * 1.1, cy - s * 0.2, s * 2.2, s * 1.6))
        painter.drawArc(QRectF(cx - s * 0.75, cy - s * 1.4, s * 1.5, s * 2.2), 0, 180 * 16)
    elif kind == "link":
        for dx in (-0.55, 0.55):
            painter.drawRoundedRect(QRectF(cx + dx * s - s * 0.9, cy - s * 0.55, s * 1.8, s * 1.1), s * 0.55, s * 0.55)
    elif kind == "more":
        painter.setBrush(color)
        for dy in (-1, 0, 1):
            painter.drawEllipse(QPointF(cx, cy + dy * s * 0.9), s * 0.18, s * 0.18)
    elif kind == "text_style":
        font = painter.font()
        font.setPixelSize(int(s * 2.4))
        font.setBold(True)
        painter.setFont(font)
        painter.drawText(rect, Qt.AlignCenter, "B")
        painter.drawLine(QPointF(cx - s * 0.8, cy + s * 1.5), QPointF(cx + s * 0.8, cy + s * 1.5))
    elif kind == "align":
        for i, w in enumerate((1.5, 1.0, 1.5)):
            y = cy + (i - 1) * s * 0.9
            painter.drawLine(QPointF(cx - s * w, y), QPointF(cx + s * w, y))
    elif kind in ("text_color", "highlight"):
        font = painter.font()
        font.setPixelSize(int(s * 2.2))
        painter.setFont(font)
        painter.drawText(QRectF(rect.left(), rect.top() - s * 0.3, rect.width(), rect.height()), Qt.AlignCenter,
                         "A" if kind == "text_color" else "✎")
    elif kind == "border":
        painter.setPen(QPen(color, 2.2))
        painter.drawEllipse(QPointF(cx, cy), s * 1.3, s * 1.3)
    elif kind == "fill":
        size = s * 0.7
        for i in range(4):
            for j in range(4):
                if (i + j) % 2 == 0:
                    painter.fillRect(QRectF(cx - s * 1.4 + i * size, cy - s * 1.4 + j * size, size, size),
                                     QColor(color.red(), color.green(), color.blue(), 110))
    elif kind == "arrow":
        painter.drawLine(QPointF(cx - s * 1.5, cy), QPointF(cx + s * 1.5, cy))
        painter.drawPolyline(QPolygonF([QPointF(cx + s * 0.6, cy - s * 0.8), QPointF(cx + s * 1.5, cy),
                                        QPointF(cx + s * 0.6, cy + s * 0.8)]))
    elif kind in ("S", "M", "L"):
        painter.setBrush(color)
        radius = {"S": 0.35, "M": 0.7, "L": 1.2}[kind] * s
        painter.drawEllipse(QPointF(cx, cy), radius, radius)


# Generation des dessins gardes des boutons : changee quand les icones perso changent (refresh_glyph_buttons).
_GLYPH_GENERATION = 0


def look_key(look) -> object:
    """Cle d'un habillage de barre (toolbar_look) pour les dessins gardes des boutons ; sans « key », l'objet
    lui-meme (garde vivant par la cle : son identifiant ne peut pas resservir)."""
    if not isinstance(look, dict):
        return None
    return look.get("key") or _IdentityKey(look)


class _IdentityKey:
    __slots__ = ("obj",)

    def __init__(self, obj):
        self.obj = obj

    def __eq__(self, other):
        return isinstance(other, _IdentityKey) and other.obj is self.obj

    def __hash__(self):
        return id(self.obj)


def refresh_glyph_buttons(root):
    """Icones perso changees (Reglages > Module MRO / CAD > Icones) : boutons du board redessines."""
    global _GLYPH_GENERATION
    _GLYPH_GENERATION += 1
    for button in root.findChildren(_GlyphButton):
        button.update()


class _GlyphButton(QAbstractButton):
    """Bouton peint (outils, commandes, zoom) : glyphe, fond accent quand il est choisi, survol.

    Dessin GARDE en image (`paint_key` : etat, taille, habillage, icones) : les barres sont posees sur le board,
    Qt les repeint a CHAQUE image du board (deplacement, zoom) ; refaire leurs glyphes et chercher leurs icones
    coutait ~8 ms par image (mesure : ~45 boutons, sonde _probe_cad_latency « pan »)."""

    def __init__(self, kind: str, tip: str, parent=None, size: int = 34):
        super().__init__(parent)
        self.kind = kind
        self.setToolTip(tip)
        self.setFixedSize(size, size)
        self.setCursor(Qt.ArrowCursor)
        self._on = False
        self._swatch = None
        self._ring = None

    def set_on(self, on: bool):
        if on != self._on:
            self._on = on
            self.update()

    def set_swatch(self, color: str, ring: float | None = None):
        """Pastille de couleur ; `ring` = diametre du point central (preset de dessin : epaisseur)."""
        self._swatch = color
        self._ring = ring
        self.update()

    def sizeHint(self):
        return self.size()

    def enterEvent(self, event):
        self.update()
        super().enterEvent(event)

    def leaveEvent(self, event):
        self.update()
        super().leaveEvent(event)

    def paintEvent(self, event):
        ratio = self.devicePixelRatioF() or 1.0
        key = (_GLYPH_GENERATION, ICON_PROVIDER, self.width(), self.height(), ratio, self.isEnabled(),
               self.underMouse(), self.paint_key())
        kept = getattr(self, "_painted", None)
        if kept is None or kept[0] != key:
            pixmap = QPixmap(max(1, math.ceil(self.width() * ratio)), max(1, math.ceil(self.height() * ratio)))
            pixmap.setDevicePixelRatio(ratio)
            pixmap.fill(Qt.transparent)
            content = QPainter(pixmap)
            self.paint_content(content)
            content.end()
            self._painted = kept = (key, pixmap)
        painter = QPainter(self)
        painter.drawPixmap(0, 0, kept[1])
        painter.end()

    def paint_key(self) -> tuple:
        """Ce dont depend le dessin, en plus de la taille, du survol et de l'etat actif (voir paintEvent)."""
        return (self.kind, self._on, self._swatch, self._ring, look_key(getattr(self.parentWidget(), "look", None)))

    def paint_content(self, painter):
        from app_style import C
        painter.setRenderHint(QPainter.Antialiasing, True)
        rect = QRectF(self.rect()).adjusted(2, 2, -2, -2)
        if self._swatch is not None:
            inner = rect.adjusted(4, 4, -4, -4)
            if self._ring is not None:
                painter.setPen(QPen(QColor(model.MIRO_ACCENT) if self._on else QColor(0, 0, 0, 40),
                                    2.0 if self._on else 1.0))
                painter.setBrush(QColor("#ffffff"))
                painter.drawEllipse(inner)
                painter.setPen(Qt.NoPen)
                painter.setBrush(QColor(self._swatch))
                d = max(3.0, min(inner.width() - 6, self._ring))
                painter.drawEllipse(inner.center(), d / 2, d / 2)
            else:
                painter.setPen(QPen(QColor(model.MIRO_ACCENT) if self._on else
                                    QColor(0, 0, 0, 110 if self.underMouse() else 40), 2.0 if self._on else 1.2))
                painter.setBrush(QColor(self._swatch))
                painter.drawEllipse(inner)
            return
        look = getattr(self.parentWidget(), "look", None)
        if self._on or self.underMouse():
            size = min(float(look["focus_width"]) if look else 26, self.width(), self.height())
            mark = QRectF(0, 0, size, size)
            mark.moveCenter(QRectF(self.rect()).center())
            color = (look["focus_color"] if self._on else look["hover_color"]) if look else (
                "#6e3f6f9f" if self._on else C["hover"])
            radius = (look["focus_radius"] if self._on else look["hover_radius"]) if look else 6
            painter.setPen(Qt.NoPen)
            painter.setBrush(QColor(color))
            painter.drawRoundedRect(mark, radius, radius)
        side = int(min(rect.width(), rect.height()) * 0.62)
        pixmap = custom_icon(self.kind, side)
        look = getattr(self.parentWidget(), "look", None)       # barre d'outils : habillage (negatif)
        invert = bool(look and look.get("invert"))
        if pixmap is not None and not pixmap.isNull() and invert:
            pixmap = negative_pixmap(pixmap)
        if pixmap is not None and not pixmap.isNull():
            target = QRectF(0, 0, pixmap.width() / max(1.0, pixmap.devicePixelRatio()),
                            pixmap.height() / max(1.0, pixmap.devicePixelRatio()))
            target.moveCenter(rect.center())
            painter.drawPixmap(target, pixmap, QRectF(pixmap.rect()))
        else:
            paint_glyph(painter, self.kind, rect, QColor(self.glyph_ink(invert)))

    def glyph_ink(self, invert: bool) -> str:
        """Couleur du glyphe peint (sans icone choisie) : texte de l'appli, en negatif si la barre l'est."""
        from app_style import C
        return negative(C["text"], invert)


class _TextButton(QPushButton):
    """Bouton texte de la barre contextuelle (police, taille) : habillage de la feuille de style de l'appli."""

    def __init__(self, text: str, tip: str, parent=None, width: int = 0):
        super().__init__(text, parent)
        self.setToolTip(tip)
        self.setCursor(Qt.ArrowCursor)
        self.setFlat(True)
        self.setFixedHeight(30)
        if width:
            self.setFixedWidth(width)


class _RenderBadge(QWidget):
    """Encart en haut a droite : mode de rendu REEL du board, mis a jour des qu'il change (`BoardView.renderModeChanged`) :
    OPEN GL (vert) quand la couche GPU est active, CLASSIQUE (rouge) sinon ; fond noir a 15 %, coins de 3 px. Rendu
    classique : ce widget le peint ; rendu OpenGL : il est cache et la couche GPU peint l'encart a sa place
    (`BoardView.gpu_badge`)."""

    def __init__(self, parent):
        super().__init__(parent)
        self._gl = False
        self.setAttribute(Qt.WA_TransparentForMouseEvents, True)
        font = self.font()
        font.setPixelSize(12)
        font.setBold(True)
        self.setFont(font)
        self._fit()

    def set_gl(self, on: bool):
        if bool(on) != self._gl:
            self._gl = bool(on)
            self._fit()
            self.update()
            parent = self.parentWidget()
            if parent is not None and hasattr(parent, "_place_chrome"):
                try:
                    parent._place_chrome()
                except AttributeError:                      # barres pas encore toutes creees (construction)
                    pass

    def label(self) -> str:
        return "OPEN GL" if self._gl else "CLASSIQUE"

    def _fit(self):
        width = self.fontMetrics().horizontalAdvance(self.label())
        self.resize(width + 20, self.fontMetrics().height() + 10)

    def paintEvent(self, _event):
        painter = QPainter(self)
        paint_render_badge(painter, self.rect(), self._gl)


class _ZoomLabel(_GlyphButton):
    """Pourcentage du zoom ; clic = 100 %."""

    def __init__(self, view, parent=None):
        super().__init__("zoom", "100 % (Ctrl+0)", parent, 30)
        self._view = view
        self.setFixedWidth(58)

    def paint_key(self) -> tuple:
        pane = self.parent().parent() if self.parent() is not None else None
        return (format_zoom(self._view.zoom()), look_key(getattr(pane, "toolbar_style", None)))

    def paint_content(self, painter):
        from app_style import C, role_font
        if self.underMouse():
            painter.setRenderHint(QPainter.Antialiasing, True)
            painter.setPen(Qt.NoPen)
            painter.setBrush(QColor(C["hover"]))
            painter.drawRoundedRect(QRectF(self.rect()).adjusted(2, 2, -2, -2), 6, 6)
        pane = self.parent().parent() if self.parent() is not None else None      # barre de zoom -> panneau
        look = getattr(pane, "toolbar_style", None)
        painter.setPen(QColor(look["text"] if look else C["text"]))
        painter.setFont(look["font"] if look else role_font("info", 12))
        painter.drawText(self.rect(), Qt.AlignCenter, format_zoom(self._view.zoom()))


def format_zoom(zoom: float) -> str:
    """Pourcentage du zoom : une decimale sous 10 % (0,1 % a 9,9 %), entier au-dessus."""
    percent = zoom * 100
    if percent < 9.95:
        return f"{percent:.1f}".replace(".", ",") + " %"
    return f"{round(percent)} %"


def parse_percent(text: str) -> float | None:
    """« 0,1 % », « 2000 », « 12.5% » -> 0,001 / 20 / 0,125 (zoom) ; None si illisible."""
    cleaned = text.strip().replace("%", "").replace(",", ".").replace(" ", "")
    try:
        value = float(cleaned)
    except ValueError:
        return None
    return value / 100 if value > 0 else None


class _PercentField(QWidget):
    """Champ « n % » des reglages de la page (zone de saisie de l'appli) : valide a la sortie / Entree ;
    `check(valeur)` -> message d'erreur ou None ; invalide = message, la valeur d'avant revient."""

    committed = Signal(float)

    def __init__(self, value: float, check, parent=None):
        super().__init__(parent)
        from PySide6.QtWidgets import QLineEdit
        from settings_theme import _text_label
        row = QHBoxLayout(self)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(8)
        self.field = QLineEdit(format_zoom(value))
        self.field.setFixedWidth(90)
        self.field.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        self.error = _text_label("", "value_muted")
        row.addWidget(self.field)
        row.addWidget(self.error)
        self._value = value
        self._check = check
        self.field.editingFinished.connect(self._commit)

    def _commit(self):
        from settings_store import M
        from settings_theme import _set_text_role
        value = parse_percent(self.field.text())
        message = "valeur illisible" if value is None else self._check(value)
        if message:
            _set_text_role(self.error, "value_muted", M["dirty_frame"])
            self.error.setText(message)
            self.field.setText(format_zoom(self._value))
            return
        self.error.setText("")
        self._value = value
        self.field.setText(format_zoom(value))
        self.committed.emit(value)


_FAMILIES: list[str] | None = None
_FAMILY_SET: set[str] = set()
_LATIN: dict[str, bool] = {}
_FONT_DELEGATE = None


def installed_families() -> list[str]:
    """Polices installees, lues UNE fois (la liste ne change pas pendant la session)."""
    global _FAMILIES, _FAMILY_SET
    if _FAMILIES is None:
        from PySide6.QtGui import QFontDatabase
        _FAMILY_SET = set(QFontDatabase.families())
        _FAMILIES = sorted(_FAMILY_SET, key=str.casefold)
    return _FAMILIES


def font_installed(family: str) -> bool:
    installed_families()
    return not family or family in _FAMILY_SET


def _writes_latin(family: str) -> bool:
    if family not in _LATIN:
        from PySide6.QtGui import QFontDatabase
        _LATIN[family] = QFontDatabase.WritingSystem.Latin in QFontDatabase.writingSystems(family)
    return _LATIN[family]


def _font_delegate(parent):
    """Delegue de la liste des polices (classe construite a la 1re ouverture)."""
    global _FONT_DELEGATE
    if _FONT_DELEGATE is None:
        from PySide6.QtWidgets import QStyle, QStyledItemDelegate

        class FontDelegate(QStyledItemDelegate):
            def sizeHint(self, option, index):
                return QSize(280, 30 if index.data(Qt.UserRole) != "separator" else 22)

            def paint(self, painter, option, index):
                from PySide6.QtGui import QFont
                from app_style import C, role_font
                role = index.data(Qt.UserRole)
                family = index.data(Qt.DisplayRole) or ""
                rect = option.rect
                painter.save()
                if option.state & (QStyle.State_Selected | QStyle.State_MouseOver):
                    back = QColor(C["accent"] if option.state & QStyle.State_Selected else C["hover"])
                    if option.state & QStyle.State_Selected:
                        back.setAlpha(110)
                    painter.fillRect(rect, back)
                painter.setPen(QColor(C["text"]))
                if role == "separator":
                    painter.setFont(role_font("info", 10))
                    painter.drawText(rect.adjusted(8, 0, 0, 0), Qt.AlignVCenter | Qt.AlignLeft, "Polices installées")
                    painter.restore()
                    return
                label = rect.adjusted(10, 0, -8, 0)
                latin = role == "missing" or _writes_latin(family)
                font = QFont(family)
                font.setPixelSize(16)
                painter.setFont(font)
                painter.drawText(label, Qt.AlignVCenter | Qt.AlignLeft, family if latin else "Aa Bb 123")
                if role == "missing" or not latin:          # le nom reste lisible (police de l'interface)
                    painter.setFont(role_font("info", 10))
                    painter.drawText(label, Qt.AlignVCenter | Qt.AlignRight,
                                     "non installée" if role == "missing" else family)
                painter.restore()
        _FONT_DELEGATE = FontDelegate
    return _FONT_DELEGATE(parent)


class FontPicker(QWidget):
    """Filtre + liste des polices, chaque nom peint DANS sa police (seules les lignes visibles sont peintes ;
    une police de symboles montre aussi son nom en police de l'interface)."""

    chosen = Signal(str)

    def __init__(self, current: str, parent=None):
        super().__init__(parent)
        from PySide6.QtWidgets import QLineEdit, QListWidget, QListWidgetItem
        box = QVBoxLayout(self)
        box.setContentsMargins(0, 0, 0, 0)
        box.setSpacing(4)
        self.filter = QLineEdit()
        self.filter.setPlaceholderText("Filtrer les polices…")
        box.addWidget(self.filter)
        self.list = QListWidget()
        self.list.setFixedSize(300, 330)
        self.list.setUniformItemSizes(False)
        self.list.setMouseTracking(True)
        box.addWidget(self.list)
        installed = installed_families()
        entries = []
        if current and not font_installed(current):
            entries.append((current, "missing"))
        entries += [(f, "usual") for f in model.FONT_FAMILIES if font_installed(f)]
        entries.append(("", "separator"))
        entries += [(f, "all") for f in installed]
        selected = None
        for family, role in entries:
            item = QListWidgetItem(family)
            item.setData(Qt.UserRole, role)
            if role == "separator":
                item.setFlags(Qt.NoItemFlags)
            self.list.addItem(item)
            if selected is None and family == current:
                selected = item
        self.list.setItemDelegate(_font_delegate(self.list))
        if selected is not None:
            self.list.setCurrentItem(selected)
            self.list.scrollToItem(selected)
        self.list.itemClicked.connect(self._pick)
        self.list.itemActivated.connect(self._pick)
        self.filter.textChanged.connect(self._filter)
        self.filter.returnPressed.connect(self._first)

    def _pick(self, item):
        if item.data(Qt.UserRole) in ("usual", "all", "missing") and item.text():
            self.chosen.emit(item.text())

    def _filter(self, text: str):
        needle = text.strip().casefold()
        for row in range(self.list.count()):
            item = self.list.item(row)
            role = item.data(Qt.UserRole)
            item.setHidden(bool(needle) and (role == "separator" or needle not in item.text().casefold()))

    def _first(self):
        for row in range(self.list.count()):
            item = self.list.item(row)
            if not item.isHidden() and item.data(Qt.UserRole) != "separator":
                self._pick(item)
                return


class _SwatchGrid(QWidget):
    """Grille de pastilles ; `picked(couleur)`."""

    picked = Signal(str)

    def __init__(self, colors, current: str | None = None, columns: int = 6, extra: tuple = (), parent=None):
        super().__init__(parent)
        grid = QGridLayout(self)
        grid.setContentsMargins(0, 2, 0, 2)
        grid.setSpacing(2)
        for n, color in enumerate(colors):
            button = _GlyphButton("swatch", color, self, 28)
            button.set_swatch(color)
            button.set_on(current is not None and str(current).lower() == color.lower())
            button.clicked.connect(lambda _c=False, col=color: self.picked.emit(col))
            grid.addWidget(button, n // columns, n % columns)


def cap_icon(kind: str, end: str):
    """Apercu d'une pointe pour le menu (un bout de trait et sa pointe, du bon cote)."""
    from PySide6.QtGui import QIcon, QPixmap
    from app_style import C
    from fm_miro.items import cap_shape
    pixmap = QPixmap(48, 48)                      # carre (les icones de menu le sont), pointe bien visible
    pixmap.fill(Qt.transparent)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.Antialiasing, True)
    color = QColor(C["text"])
    tip, toward = (QPointF(6, 24), QPointF(44, 24)) if end == "start" else (QPointF(42, 24), QPointF(4, 24))
    back = 0.0
    if kind != "none":
        outline, back, filled = cap_shape(kind, tip, toward, 24.0)
    painter.setPen(QPen(color, 3.2))
    direction = 1 if end == "start" else -1
    painter.drawLine(QPointF(tip.x() + direction * back, 24), toward)
    if kind != "none":
        painter.setBrush(color if filled is True else (QColor(C["window"]) if filled is False else Qt.NoBrush))
        painter.drawPath(outline)
    painter.end()
    return QIcon(pixmap)


TOOLBAR_KEYS = "board_toolbar_"


def negative(color, on: bool = True) -> str:
    """Couleur en negatif (#rrggbb ; alpha garde)."""
    if not on:
        return color
    c = QColor(color)
    c.setRgb(255 - c.red(), 255 - c.green(), 255 - c.blue(), c.alpha())
    return c.name(QColor.HexArgb) if c.alpha() < 255 else c.name()


_NEGATIVE_PIXMAPS: dict = {}


def negative_pixmap(pixmap):
    """Icone perso en negatif (couleurs inversees, transparence gardee), faite une fois par icone."""
    from PySide6.QtGui import QImage, QPixmap
    key = pixmap.cacheKey()
    cached = _NEGATIVE_PIXMAPS.get(key)
    if cached is None:
        image = pixmap.toImage().convertToFormat(QImage.Format_ARGB32)
        image.invertPixels(QImage.InvertRgb)
        cached = QPixmap.fromImage(image)
        cached.setDevicePixelRatio(pixmap.devicePixelRatio())
        if len(_NEGATIVE_PIXMAPS) > 128:
            _NEGATIVE_PIXMAPS.clear()
        _NEGATIVE_PIXMAPS[key] = cached
    return cached


def toolbar_look(settings: dict) -> dict:
    """Habillage des barres d'outils (Reglages > Module MRO > Barres d'outils, cles `board_toolbar_*`) ; sans reglage :
    l'apparence d'origine (palette des panneaux des reglages)."""
    from settings_store import DEFAULT_SETTINGS
    from settings_menu import _border, _corners, _font, _sides
    from settings_widgets import shadow_look
    from app_style import resolve_color_ref
    values = {k: v for k, v in DEFAULT_SETTINGS.items() if k.startswith(TOOLBAR_KEYS)}
    values.update({k: v for k, v in (settings or {}).items() if k.startswith(TOOLBAR_KEYS)})
    sides, colors = _border(values, "board_toolbar_border", "#2a2e32")
    return {
        "bg": resolve_color_ref(values.get("board_toolbar_bg_color"), "#16181a"),
        "sides": {s: t > 0 for s, t in sides.items()},
        "thickness": max(sides.values()) if sides else 0,
        "border_colors": colors,
        "radius": _corners(values.get("board_toolbar_corner_radius")),
        "padding": _sides(values.get("board_toolbar_padding"), 6),
        "shadow": shadow_look(values, "board_toolbar_shadow", lambda v: resolve_color_ref(v, "#8c000000")),
        "font": _font(values, "board_toolbar_text", 12),
        "text": negative(resolve_color_ref(values.get("board_toolbar_text_font_color"), "#d6d9dc"),
                         bool(values.get("board_toolbar_invert"))),
        "invert": bool(values.get("board_toolbar_invert")),
        "focus_width": max(0, int(values.get("board_toolbar_focus_width", 26))),
        "focus_color": resolve_color_ref(values.get("board_toolbar_focus_color"), "#6e3f6f9f"),
        "focus_radius": max(0, int(values.get("board_toolbar_focus_radius", 6))),
        "hover_color": resolve_color_ref(values.get("board_toolbar_hover_color"), "#232729"),
        "hover_radius": max(0, int(values.get("board_toolbar_hover_radius", 6))),
        "key": repr(sorted(values.items())),
    }


class _ToolbarFrame(QWidget):
    """Fond, bordures par cote et coins d'une barre d'outils du board (tracés des reglages) ; son ombre est
    peinte par un voisin (settings_widgets.attach_shadow)."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.look = toolbar_look({})
        self.setAttribute(Qt.WA_StyledBackground, False)
        from settings_widgets import attach_shadow
        self._shadow = attach_shadow(self, lambda: self.look["shadow"], lambda: dict(self.look["radius"]))

    def set_look(self, look: dict):
        self.look = look
        padding = look["padding"]
        border = look["thickness"]
        if self.layout() is not None:
            self.layout().setContentsMargins(*(max(0, int(padding[side])) + border
                                               for side in ("left", "top", "right", "bottom")))
        self.update()
        try:
            self._shadow.sync()
            self._shadow.update()
        except RuntimeError:
            pass

    def paintEvent(self, event):
        # Dessin garde en image (repeint a chaque image du board qu'elle recouvre, voir _GlyphButton).
        from settings_widgets import _paint_bordered_vector
        ratio = self.devicePixelRatioF() or 1.0
        key = (self.width(), self.height(), ratio, look_key(self.look))
        kept = getattr(self, "_painted", None)
        if kept is None or kept[0] != key:
            pixmap = QPixmap(max(1, math.ceil(self.width() * ratio)), max(1, math.ceil(self.height() * ratio)))
            pixmap.setDevicePixelRatio(ratio)
            pixmap.fill(Qt.transparent)
            content = QPainter(pixmap)
            content.setRenderHint(QPainter.Antialiasing, True)
            look = self.look
            _paint_bordered_vector(content, self.rect(), dict(look["radius"]), look["sides"], look["thickness"],
                                   look["border_colors"], QColor(look["bg"]))
            content.end()
            self._painted = kept = (key, pixmap)
        painter = QPainter(self)
        painter.drawPixmap(0, 0, kept[1])
        painter.end()


def _bar(parent, vertical: bool):
    """Barre d'outils flottante du board (habillee par Reglages > Module MRO > Barres d'outils)."""
    frame = _ToolbarFrame(parent)
    layout = (QVBoxLayout if vertical else QHBoxLayout)(frame)
    layout.setContentsMargins(7, 7, 7, 7)
    layout.setSpacing(2)
    return frame, layout


def _panel(parent, vertical: bool):
    from settings_store import M
    from settings_window import _PanelFrame
    frame = _PanelFrame(parent)
    frame.setColors(M["panel_bg"], M["panel_border"])
    layout = (QVBoxLayout if vertical else QHBoxLayout)(frame)
    layout.setContentsMargins(6, 6, 6, 6)
    layout.setSpacing(2)
    return frame, layout


def _menu(parent, key: str):
    from settings_menu import Menu
    return Menu(parent, key=f"board:{key}", editable=False)


def _slider(minimum, maximum, value, unit="px"):
    from settings_widgets import _SliderField
    return _SliderField(int(minimum), int(maximum), int(value), unit=unit, slider_width=130, box_width=62)


class CommentPanel(QWidget):
    """Fil d'un commentaire : messages (date, modifier, supprimer), reponse, resoudre / rouvrir, supprimer le
    fil. Chaque action = une etape d'annulation (scene.change_items) ; un commentaire NEUF n'entre dans
    l'annulation qu'a son premier message (ferme vide = retire)."""

    def __init__(self, pane: "BoardPane"):
        super().__init__(pane)
        from settings_theme import _text_label
        self.pane = pane
        self.comment: CommentItem | None = None
        self.fresh = False
        self._editing = None
        self.setAttribute(Qt.WA_StyledBackground, True)
        frame, box = _panel(self, True)
        self._frame = frame
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.addWidget(frame)
        box.setContentsMargins(12, 10, 12, 12)
        box.setSpacing(6)
        head = QHBoxLayout()
        self._title = _text_label("Commentaire", "card_title")
        head.addWidget(self._title)
        head.addStretch(1)
        self._resolve = QPushButton("Résoudre")
        self._resolve.clicked.connect(self._toggle_resolved)
        self._delete = QPushButton("Supprimer le fil")
        self._delete.clicked.connect(self._delete_thread)
        close = _GlyphButton("minus", "Fermer", self, 26)
        close.kind = "close"
        close.clicked.connect(self.close_panel)
        for widget in (self._resolve, self._delete):
            widget.setCursor(Qt.ArrowCursor)
            head.addWidget(widget)
        head.addWidget(close)
        box.addLayout(head)
        self._messages = QVBoxLayout()
        self._messages.setSpacing(6)
        box.addLayout(self._messages)
        self._input = QPlainTextEdit()
        self._input.setPlaceholderText("Écrire un commentaire… (Ctrl+Entrée)")
        self._input.setFixedHeight(64)
        self._input.installEventFilter(self)
        box.addWidget(self._input)
        row = QHBoxLayout()
        self._hint = _text_label("", "value_muted")
        row.addWidget(self._hint)
        row.addStretch(1)
        self._send = QPushButton("Envoyer")
        self._send.clicked.connect(self._submit)
        row.addWidget(self._send)
        box.addLayout(row)
        self.setFixedWidth(320)
        self.hide()

    def eventFilter(self, obj, event):
        if obj is self._input and event.type() == QEvent.KeyPress:
            if event.key() in (Qt.Key_Return, Qt.Key_Enter) and event.modifiers() & Qt.ControlModifier:
                self._submit()
                return True
            if event.key() == Qt.Key_Escape:
                self.close_panel()
                return True
        return super().eventFilter(obj, event)

    def open(self, comment: CommentItem, fresh: bool):
        if self.comment is not None and self.comment is not comment:
            self.close_panel()
        self.comment, self.fresh, self._editing = comment, fresh, None
        self.refresh()
        self.show()
        self.raise_()
        self.place()
        self._input.setFocus()

    def place(self):
        if self.comment is None:
            return
        view = self.pane.view
        anchor = view.mapFromScene(self.comment.pos())
        x = min(max(8, anchor.x() + 34), self.pane.width() - self.width() - 8)
        y = min(max(8, anchor.y() - 40), self.pane.height() - self.height() - 8)
        self.move(int(x), int(y))

    def refresh(self):
        from settings_theme import _text_label
        while self._messages.count():
            entry = self._messages.takeAt(0)
            widget = entry.widget()
            if widget is not None:
                widget.deleteLater()
        comment = self.comment
        if comment is None:
            return
        messages = comment.data.get("messages") or []
        resolved = bool(comment.data.get("resolved"))
        self._resolve.setText("Rouvrir" if resolved else "Résoudre")
        self._resolve.setEnabled(bool(messages))
        self._delete.setEnabled(not self.fresh)
        self._title.setText("Commentaire résolu" if resolved else "Commentaire")
        for index, message in enumerate(messages):
            card = QWidget()
            col = QVBoxLayout(card)
            col.setContentsMargins(0, 0, 0, 0)
            col.setSpacing(1)
            stamp = time.strftime("%d/%m/%Y %H:%M", time.localtime(float(message.get("created", 0) or 0)))
            if message.get("edited"):
                stamp += " (modifié)"
            top = QHBoxLayout()
            top.addWidget(_text_label(stamp, "value_muted"))
            top.addStretch(1)
            for label, slot in (("Modifier", lambda _c=False, i=index: self._edit(i)),
                                ("Supprimer", lambda _c=False, i=index: self._delete_message(i))):
                button = QPushButton(label)
                button.setFlat(True)
                button.setCursor(Qt.ArrowCursor)
                button.clicked.connect(slot)
                top.addWidget(button)
            col.addLayout(top)
            text = _text_label(str(message.get("text", "")), "value")
            text.setWordWrap(True)
            text.setTextInteractionFlags(Qt.TextSelectableByMouse)
            col.addWidget(text)
            self._messages.addWidget(card)
        self._hint.setText("Modification du message" if self._editing is not None else "")
        self._send.setText("Enregistrer" if self._editing is not None else ("Envoyer" if messages else "Commenter"))
        self.adjustSize()

    def _edit(self, index: int):
        messages = self.comment.data.get("messages") or []
        if 0 <= index < len(messages):
            self._editing = index
            self._input.setPlainText(str(messages[index].get("text", "")))
            self._input.setFocus()
            self.refresh()

    def _submit(self):
        text = self._input.toPlainText().strip()
        comment = self.comment
        if comment is None or not text:
            return
        scene = self.pane.scene
        now = round(time.time(), 1)
        if self.fresh:
            comment.data = comment.to_dict()
            comment.data["messages"] = [{"id": model.new_id(), "text": text, "created": now}]
            comment.apply(comment.data)
            scene.push({comment.item_id: None}, scene.snapshot([comment.item_id]), "Ajouter un commentaire")
            self.fresh = False
        elif self._editing is not None:
            index = self._editing

            def change(item):
                messages = [dict(m) for m in item.data.get("messages") or []]
                if 0 <= index < len(messages):
                    messages[index].update(text=text, edited=now)
                item.data["messages"] = messages
            scene.change_items([comment], change, "Modifier un commentaire")
        else:
            def change(item):
                item.data["messages"] = list(item.data.get("messages") or []) + [
                    {"id": model.new_id(), "text": text, "created": now}]
            scene.change_items([comment], change, "Répondre")
        self._editing = None
        self._input.clear()
        self.refresh()

    def _delete_message(self, index: int):
        comment = self.comment
        messages = comment.data.get("messages") or []
        if len(messages) <= 1:
            self._delete_thread()
            return

        def change(item):
            item.data["messages"] = [m for i, m in enumerate(item.data.get("messages") or []) if i != index]
        self.pane.scene.change_items([comment], change, "Supprimer un message")
        self.refresh()

    def _toggle_resolved(self):
        comment = self.comment
        resolved = not bool(comment.data.get("resolved"))
        self.pane.scene.change_items([comment], lambda i: i.data.update(resolved=resolved),
                                     "Résoudre le commentaire" if resolved else "Rouvrir le commentaire")
        if resolved and not self.pane.scene.show_resolved:
            self.close_panel()
        else:
            self.refresh()

    def _delete_thread(self):
        comment, self.comment = self.comment, None
        if comment is not None:
            if self.fresh:
                self.pane.scene._remove(comment.item_id)
            else:
                comment.data["locked"] = False
                self.pane.scene.delete_items([comment])
        self.fresh = False
        self.hide()

    def close_panel(self):
        comment, self.comment = self.comment, None
        if comment is not None and self.fresh and comment.scene() is not None:
            self.pane.scene._remove(comment.item_id)          # jamais ecrit : rien dans l'annulation
        self.fresh = False
        self._editing = None
        self._input.clear()
        self.hide()
        self.pane.view.setFocus()


class BoardPane(QWidget):
    """Board ouvert au centre de la zone des colonnes."""

    dirtyChanged = Signal(bool)
    closeRequested = Signal()
    stateChanged = Signal()                 # annuler / retablir disponibles, zoom : boutons de la barre a jour

    def __init__(self, parent: QWidget, settings: dict | None = None):
        super().__init__(parent)
        self.path: Path | None = None
        self.source: Path | None = None         # dessin DXF / DWG ouvert (jamais reecrit), voir open_import
        self._mtime = None
        self._dirty = False
        self._saved_view = None
        self._saved_assets: set[str] = set()
        self._settings = dict(settings or {})
        self.setObjectName("BoardPane")
        self.setAttribute(Qt.WA_StyledBackground, True)
        # Fluidite : chaque element est garde en image a l'ecran (DeviceCoordinateCache, dans QPixmapCache) ;
        # avec la limite d'origine de Qt (10 Mo), une centaine de post-it a 100 % la depassaient et tout etait
        # repeint a chaque image du deplacement (mesure : 71 ms par image, 500 elements, 2400 x 1300).
        from PySide6.QtGui import QPixmapCache
        if QPixmapCache.cacheLimit() < 256 * 1024:
            QPixmapCache.setCacheLimit(256 * 1024)
        self.scene = BoardScene(parent=self)
        self.view = BoardView(self.scene, self, opengl=bool(self._settings.get("board_opengl", False)))
        self.scene.contentChanged.connect(self._on_changed)
        self.view.gpuFailed.connect(self._on_gpu_failed)
        self.scene.pageChanged.connect(self._on_page_changed)
        self._context_timer = QTimer(self)
        self._context_timer.setSingleShot(True)
        self._context_timer.setInterval(0)
        self._context_timer.timeout.connect(self._sync_context_bar)
        self.scene.selectionChanged.connect(self._context_timer.start)   # une fois par passage de boucle
        self.scene.undo.canUndoChanged.connect(lambda _c: self.stateChanged.emit())
        self.scene.undo.canRedoChanged.connect(lambda _c: self.stateChanged.emit())
        self.view.toolChanged.connect(self._sync_tools)
        self.view.zoomChanged.connect(self._on_zoom)
        self.view.commentOpened.connect(self._open_comment)
        self.view.installEventFilter(self)
        self._autosave = QTimer(self)
        self._autosave.setSingleShot(True)
        self._autosave.setInterval(AUTOSAVE_MS)
        self._autosave.timeout.connect(self.save)
        self._presets = self._load_presets()
        self._preset_index = {"pen": 0, "highlighter": 0, "smart": 0}
        self._draw_tool = "pen"
        self.cad = None                         # module CAD (fm_cad/cad.py), cree au 1er usage
        self.design = None                      # module Design (fm_design/controller.py), cree au 1er usage
        self.module = None                      # module actif : "miro", "cad", "design" ou None (aucune barre)
        self._cad_export_units = "mm"           # unites du dernier export DXF / DWG (session)
        self.view.cad = None
        self._build_chrome()
        self.apply_settings(self._settings)
        parent.installEventFilter(self)
        self.hide()

    # -- reglages de l'appli (Reglages > Module MRO) --
    def apply_settings(self, settings: dict):
        """Magnetisme et barres d'outils (Reglages > Module MRO) : appliques tout de suite ; les barres ne sont
        refaites que si leur habillage a change."""
        self._settings = dict(settings or {})
        look = toolbar_look(self._settings)
        if getattr(self, "_toolbar_key", None) != look["key"] and hasattr(self, "_toolbar"):
            self._toolbar_key = look["key"]
            self._apply_toolbar_look(look)
        self.scene.snap = {
            "enabled": bool(self._settings.get("board_snap_enabled", True)),
            "objects": bool(self._settings.get("board_snap_objects", True)),
            "grid": bool(self._settings.get("board_snap_grid", False)),
            "guides": bool(self._settings.get("board_snap_guides", True)),
            "resize": bool(self._settings.get("board_snap_resize", True)),
            "distance": int(self._settings.get("board_snap_distance", 6) or 6),
        }
        self.scene.set_grid_settings(self._settings)
        speed = self._settings.get("board_zoom_speed", 15)
        fine = self._settings.get("board_zoom_fine", 3)
        self.view.zoom_step = 1.0 + max(1, min(100, int(speed if isinstance(speed, (int, float)) else 15))) / 100.0
        self.view.zoom_fine_step = 1.0 + max(1, min(50, int(fine if isinstance(fine, (int, float)) else 3))) / 100.0
        # Types de ligne et unite du CAD : generaux, lus par les lignes meme sans le mode CAD (dessin d'un board).
        restyle = cad_model.set_linetypes(self._settings.get("board_cad_linetypes"))
        unit = cad_model.unit_key(self._settings.get("board_cad_unit"))
        if unit != self.scene.cad_unit:
            self.scene.cad_unit = unit
            restyle = True
        if restyle:
            self.scene.cad_style_changed()
            self.scene.update()
        pgp = str(self._settings.get("board_cad_pgp_path", "") or "").strip()
        if pgp != cad_aliases._state["path"]:
            cad_aliases.install(pgp)                              # alias de commandes du fichier .pgp choisi
        gpu = bool(self._settings.get("board_cad_gpu", False))
        if gpu != (getattr(self.view, "gpu", None) is not None):
            if not self.view.set_gpu(gpu) and gpu:
                self._settings["board_cad_gpu"] = False          # OpenGL indisponible : rendu par lots du processeur
        if self.cad is not None:
            self.cad.apply_settings(self._settings)

    def _on_gpu_failed(self, message: str):
        """Rendu GPU impossible : le reglage est remis a faux (pas de nouvel essai a chaque ouverture) et signale."""
        self._settings["board_cad_gpu"] = False
        if self.cad is not None:
            self.cad.message(f"Rendu GPU du CAD indisponible ({message}) : rendu par le processeur.", error=True)
        writer = SETTING_WRITER
        if writer is not None:
            try:
                writer("board_cad_gpu", False)
            except Exception:                        # noqa: BLE001 - la session garde la valeur
                pass

    def toggle_grid(self):
        """Bouton de la barre d'outils (et F7 du CAD) : grille de ce board, la MEME pour le board et le CAD (reglage
        de la page, annulable)."""
        on = not bool(self.scene.page.get("grid", True))
        self.scene.set_page({"grid": on}, text="Grille")
        self.view.setFocus()

    def _sync_grid_button(self):
        button = getattr(self, "_grid_button", None)
        if button is not None:
            button.set_on(bool(self.scene.page.get("grid", True)))

    def toggle_invert(self):
        """Bouton de la barre d'outils : icones et textes en negatif (meme reglage que Reglages > Module MRO > Barres
        d'outils), applique tout de suite puis enregistre par l'appli."""
        on = not bool(self._settings.get("board_toolbar_invert", False))
        self.apply_settings(dict(self._settings, board_toolbar_invert=on))
        writer = SETTING_WRITER
        if writer is not None:
            try:
                writer("board_toolbar_invert", on)
            except Exception:
                pass

    def _apply_toolbar_look(self, look: dict):
        self.toolbar_style = look
        for bar in (self._toolbar, self._drawbar, self._title, self._zoombar, self._contextbar, self._modulebar):
            bar.set_look(look)
            if bar is self._toolbar:
                margins = bar.layout().contentsMargins()
                horizontal = max(margins.left(), margins.right())
                bar.layout().setContentsMargins(horizontal, margins.top(), horizontal, margins.bottom())
            for button in bar.findChildren(_GlyphButton):
                button.update()                             # icones (negatif) repeintes
        self._style_bar_texts()
        if self.cad is not None:
            self.cad.ui.set_look(look)
        self._place_chrome()

    def _style_bar_texts(self):
        """Police et couleur des textes des barres (Reglages > Module MRO > Barres d'outils > Police)."""
        look = getattr(self, "toolbar_style", None)
        if look is None:
            return
        for bar in (self._toolbar, self._drawbar, self._title, self._zoombar, self._contextbar, self._modulebar):
            font = look["font"]
            size = font.pixelSize() if font.pixelSize() > 0 else round(font.pointSizeF() * 4 / 3)
            # Dans la feuille de style (celle de l'appli fixe la police des boutons, setFont seul serait ignore).
            css = (f"QPushButton {{ color: {look['text']}; font-family: '{font.family()}'; font-size: {size}px;"
                   f" font-weight: {700 if font.bold() else 400}; font-style: {'italic' if font.italic() else 'normal'};")
            if look.get("invert"):
                # Negatif : le fond sombre des boutons de l'appli rendait le texte (devenu sombre) illisible ;
                # le bouton prend le fond de la barre, cerne d'un filet de la couleur du texte.
                edge = QColor(look["text"])
                edge.setAlpha(90)
                css += (f" background: transparent; border: 1px solid {edge.name(QColor.HexArgb)};"
                        " border-radius: 4px;")
            css += " }"
            for button in bar.findChildren(_TextButton):
                button.setFont(font)
                button.setStyleSheet(css)
        self._name.setFont(look["font"])
        self._name.setStyleSheet(f"color: {look['text']}; background: transparent;" if look.get("invert") else "")
        self._zoom_label.update()

    def _load_presets(self) -> dict:
        saved = self._settings.get("board_pen_presets") or {}
        presets = {}
        for tool, defaults in DEFAULT_PRESETS.items():
            values = saved.get(tool) if isinstance(saved, dict) else None
            if isinstance(values, list) and len(values) == 3 and all(isinstance(v, dict) for v in values):
                presets[tool] = [dict(d, **v) for d, v in zip(defaults, values)]
            else:
                presets[tool] = [dict(d) for d in defaults]
        return presets

    def _save_presets(self):
        try:
            from settings_store import save_live_state
            import ui_state
            save_live_state("board_pen_presets", self._presets)
            if isinstance(ui_state.APPLIED_SETTINGS, dict):
                ui_state.APPLIED_SETTINGS["board_pen_presets"] = self._presets
        except Exception:
            pass

    # -- panneaux flottants --
    def _build_chrome(self):
        from settings_theme import _text_label
        self._toolbar, tools = _bar(self, True)
        tools.setAlignment(Qt.AlignHCenter)
        self._tool_buttons = {}
        for kind, tip in TOOLS:
            button = _GlyphButton(kind, tip, self._toolbar)
            button.clicked.connect(lambda _c=False, k=kind: self._on_tool_button(k))
            tools.addWidget(button)
            self._tool_buttons[kind] = button
        tools.addSpacing(10)
        page = _GlyphButton("page", "Réglages de la page (ce board)", self._toolbar)
        page.clicked.connect(self._open_page_menu)
        tools.addWidget(page)
        self._page_button = page
        grid = _GlyphButton("grid", "Grille (ce board ; F7 en mode CAD)", self._toolbar)
        grid.clicked.connect(self.toggle_grid)
        tools.addWidget(grid)
        self._grid_button = grid
        self.scene.pageChanged.connect(self._sync_grid_button)
        self._sync_grid_button()
        invert = _GlyphButton("invert", "Icônes et textes en négatif", self._toolbar)
        invert.clicked.connect(self.toggle_invert)
        tools.addWidget(invert)
        self._invert_button = invert

        self._drawbar, draw = _bar(self, True)
        self._draw_buttons = {}
        for kind, tip in DRAW_BAR:
            button = _GlyphButton(kind, tip, self._drawbar)
            button.clicked.connect(lambda _c=False, k=kind: self._choose_draw_tool(k))
            draw.addWidget(button)
            self._draw_buttons[kind] = button
        draw.addSpacing(8)
        self._preset_buttons = []
        for index in range(3):
            button = _GlyphButton("swatch", "Preset (re-cliquer pour le modifier)", self._drawbar)
            button.clicked.connect(lambda _c=False, i=index: self._on_preset(i))
            draw.addWidget(button)
            self._preset_buttons.append(button)
        self._drawbar.hide()

        self._title, title = _bar(self, False)
        title.setContentsMargins(12, 6, 12, 6)
        title.setSpacing(10)
        self._name = _text_label("", "card_title")
        self._state = _text_label("", "value_muted")
        title.addWidget(self._name)
        title.addWidget(self._state)

        self._zoombar, zoom = _bar(self, False)
        minus = _GlyphButton("minus", "Dézoomer (-)", self._zoombar, 30)
        minus.clicked.connect(lambda: self.view.zoom_by(1 / 1.25))
        self._badge = _RenderBadge(self)
        self.view.renderModeChanged.connect(self._badge.set_gl)
        self._badge.set_gl(self.view.gpu_active())
        self._zoom_label = _ZoomLabel(self.view, self._zoombar)
        self._zoom_label.clicked.connect(lambda: self.view.set_zoom(1.0))
        plus = _GlyphButton("plus", "Zoomer (+)", self._zoombar, 30)
        plus.clicked.connect(lambda: self.view.zoom_by(1.25))
        fit = _GlyphButton("fit", "Tout voir (Maj+1)", self._zoombar, 30)
        fit.clicked.connect(self.view.fit_all)
        for button in (minus, self._zoom_label, plus, fit):
            zoom.addWidget(button)

        self._contextbar, self._context_layout = _bar(self, False)
        self._contextbar.hide()
        self._comment_panel = CommentPanel(self)

        self._modulebar, modules = _bar(self, False)
        self._module_buttons = {}
        for index, (name, label, tip) in enumerate(MODULES):
            if index:
                modules.addSpacing(10)
            button = _GlyphButton(name, tip, self._modulebar)
            button.clicked.connect(lambda _c=False, n=name: self.set_module(None if self.module == n else n))
            fade = _GlyphButton("fade", f"Griser les éléments {label} (visibles, ni sélectionnables ni modifiables)",
                                self._modulebar, 30)
            fade.clicked.connect(lambda _c=False, n=name: self.toggle_module_look(n, "fade"))
            hide = _GlyphButton("hide", f"Masquer les éléments {label}", self._modulebar, 30)
            hide.clicked.connect(lambda _c=False, n=name: self.toggle_module_look(n, "hide"))
            for widget in (button, fade, hide):
                modules.addWidget(widget, 0, Qt.AlignVCenter)
            self._module_buttons[name] = (button, fade, hide)
        self._sync_tools(self.view.tool)
        self._sync_modules()

    # -- module CAD --
    def set_module(self, name: str | None):
        """Selecteur de modules : « miro » (sa barre d'outils), « cad » (mode CAD et ses barres) ou None (aucune barre
        d'outils : seulement le selecteur, comme a l'ouverture)."""
        if name != "design" and self.design_active():
            self.design.deactivate()
        self.module = name
        if name == "cad":
            self.toggle_cad(True)
            return
        if self.cad_active():
            self.toggle_cad(False)
        if name == "design":
            self._contextbar.hide()
            if self.design is None:
                from fm_design.controller import DesignController
                self.design = DesignController(self)
                self.view.design = self.design
            self.design.activate()
        if name is None and self.view.tool != "hand":
            self.view.set_tool("select")
        self._sync_tools(self.view.tool)
        self._sync_context_bar()
        self._sync_modules()
        self.view.setFocus()

    def toggle_module_look(self, module: str, what: str):
        """Bouton griser (« fade ») ou masquer (« hide ») d'un module."""
        current = self.scene.module_look[module][what]
        self.scene.set_module_look(module, **{what: not current})
        layer = getattr(self.view, "gpu", None)
        if layer is not None:
            layer.request()                             # rendu GPU du CAD : nouvelle image
        if self.cad is not None:
            self.cad.refresh()
        self._sync_context_bar()
        self._sync_modules()

    def _sync_modules(self):
        for name, (button, fade, hide) in self._module_buttons.items():
            look = self.scene.module_look[name]
            button.set_on(self.module == name)
            fade.set_on(look["fade"])
            hide.set_on(look["hide"])
        self._toolbar.setVisible(self.module == "miro")
        self._drawbar.setVisible(self.module == "miro" and self.view.tool in DRAW_TOOLS)
        self._place_chrome()

    def title_area(self) -> QRect:
        """Zone occupee en haut a gauche (nom du board + selecteur de modules) : les barres du CAD se placent a cote."""
        return self._title.geometry().united(self._modulebar.geometry())

    def toggle_cad(self, on: bool | None = None):
        """Active / desactive le mode CAD sur ce board (les entites CAD restent visibles) ; module « cad » du
        selecteur."""
        on = (self.cad is None or not self.cad.active) if on is None else on
        if on and self.design_active():
            self.design.deactivate()
        if on:
            self.module = "cad"
        elif self.module == "cad":
            self.module = None
        if on and self.cad is None:
            from fm_cad.cad import CadController
            self.cad = CadController(self)
            self.view.cad = self.cad
            look = getattr(self, "toolbar_style", None)
            if look is not None:
                self.cad.ui.set_look(look)
        if self.cad is None:
            return
        if on:
            self.view.set_tool("select")
            self._contextbar.hide()
            self.cad.activate()
        else:
            self.cad.deactivate()
            self._sync_context_bar()
        self._sync_tools(self.view.tool)
        self._sync_modules()
        self.view.setFocus()

    def cad_active(self) -> bool:
        return self.cad is not None and self.cad.active

    def design_active(self) -> bool:
        return self.design is not None and self.design.active

    def _on_tool_button(self, kind: str):
        if self.cad_active():
            self.toggle_cad(False)                  # un outil du board : retour au board
        if self.design_active():
            self.set_module("miro")
        if kind == "image":
            self.insert_image_dialog()
            return
        if kind == "shape":
            self._open_shape_menu(self._tool_buttons["shape"], create=True)
            return
        if kind == "draw":
            self._choose_draw_tool(self._draw_tool)
            return
        if kind == "frame":
            self._open_frame_menu(self._tool_buttons["frame"], create=True)
            return
        self.view.set_tool(kind)
        self.view.setFocus()

    def _sync_tools(self, tool: str):
        cad = self.cad_active()
        if not cad and self.module is None and tool not in ("select", "hand"):
            # Outil du board choisi au clavier sans module actif : le module Miro s'active (sa barre s'affiche).
            self.module = "miro"
            self._sync_modules()
        for kind, button in self._tool_buttons.items():
            button.set_on(not cad and (kind == tool or (kind == "draw" and tool in DRAW_TOOLS)))
        drawing = tool in DRAW_TOOLS
        self._drawbar.setVisible(drawing and self.module == "miro")
        if drawing:
            self._draw_tool = tool
            for kind, button in self._draw_buttons.items():
                button.set_on(kind == tool)
            self._sync_presets()
        self._place_chrome()

    def _choose_draw_tool(self, tool: str):
        self.view.set_tool(tool)
        self._apply_preset()
        self.view.setFocus()

    def _sync_presets(self):
        tool = self._draw_tool
        if tool == "precision_eraser":
            for button, size in zip(self._preset_buttons, ("S", "M", "L")):
                button.set_swatch("#1a1a1a", ring={"S": 4, "M": 8, "L": 14}[size])
                button.set_on(self.view.eraser_size == size)
                button.setToolTip(f"Taille {size} ({ERASER_SIZES[size]} px)")
                button.show()
            return
        presets = self._presets.get(tool)
        for index, button in enumerate(self._preset_buttons):
            if presets is None:
                button.hide()
                continue
            preset = presets[index]
            button.set_swatch(preset["color"], ring=min(18.0, 3.0 + float(preset["width"]) * 0.9))
            button.set_on(index == self._preset_index.get(tool, 0))
            button.setToolTip("Preset (re-cliquer pour le modifier)")
            button.show()

    def _apply_preset(self):
        tool = self._draw_tool
        presets = self._presets.get(tool)
        if presets:
            self.view.ink_styles[tool] = dict(presets[self._preset_index.get(tool, 0)])

    def _on_preset(self, index: int):
        tool = self._draw_tool
        if tool == "precision_eraser":
            self.view.eraser_size = ("S", "M", "L")[index]
            self._sync_presets()
            return
        if tool not in self._presets:
            return
        if self._preset_index.get(tool, 0) == index:
            self._edit_preset(index)
            return
        self._preset_index[tool] = index
        self._apply_preset()
        self._sync_presets()

    def _edit_preset(self, index: int):
        """Preset deja choisi : couleur + epaisseur (+ opacite du surligneur), retenus dans les reglages."""
        tool = self._draw_tool
        preset = self._presets[tool][index]
        menu = _menu(self, "preset")
        grid = _SwatchGrid(model.COLORS, preset["color"], 6)

        def pick(color):
            preset["color"] = color
            self._apply_preset()
            self._sync_presets()
            self._save_presets()
            menu.close()
        grid.picked.connect(pick)
        from settings_menu import menu_row
        menu_row(menu, "Couleur", grid)
        width = _slider(1, 48, preset["width"])

        def set_width(value):
            preset["width"] = float(value)
            self._apply_preset()
            self._sync_presets()
        width.valueChanged.connect(set_width)
        menu_row(menu, "Épaisseur", width)
        if tool == "highlighter":
            opacity = _slider(5, 100, round(float(preset.get("opacity", 0.45)) * 100), "%")
            opacity.valueChanged.connect(lambda v: (preset.update(opacity=v / 100), self._apply_preset()))
            menu_row(menu, "Opacité", opacity)
        menu.aboutToHide.connect(self._save_presets)
        button = self._preset_buttons[index]
        menu.popup(button.mapToGlobal(button.rect().topRight()))

    def _open_shape_menu(self, anchor: QWidget, create: bool):
        """Toutes les formes ; `create` : l'outil Forme dessinera celle-ci, sinon la selection change de forme."""
        from settings_menu import menu_row
        menu = _menu(self, "shapes")
        holder = QWidget()
        grid = QGridLayout(holder)
        grid.setContentsMargins(0, 0, 0, 0)
        grid.setSpacing(2)
        current = self.view.shape_kind if create else next(
            (i.data.get("shape") for i in self._selected() if i.kind == "shape"), "rect")
        for n, kind in enumerate(model.SHAPE_KINDS):
            button = _GlyphButton(f"shape:{kind}", model.SHAPE_LABELS[kind], holder, 34)
            button.set_on(kind == current)

            def chosen(_c=False, k=kind):
                menu.close()
                if create:
                    self.view.shape_kind = k
                    self.view.set_tool("select")
                    self.view.set_tool("shape")
                    self.view.setFocus()
                else:
                    self._set_shape_kind(k)
            button.clicked.connect(chosen)
            grid.addWidget(button, n // 6, n % 6)
        menu_row(menu, "", holder)
        menu.popup(anchor.mapToGlobal(anchor.rect().topRight()))

    # -- selection : barre contextuelle --
    def _selected(self) -> list[BoardItem]:
        return [i for i in self.scene.selectedItems() if isinstance(i, BoardItem)]

    def _clear_context_bar(self):
        layout = self._context_layout
        while layout.count():
            entry = layout.takeAt(0)
            widget = entry.widget()
            if widget is not None:
                widget.deleteLater()

    def _sync_context_bar(self):
        """Commandes de la selection (seulement celles qui s'appliquent a au moins un element)."""
        self.scene.commit_live()
        items = [i for i in self._selected() if not isinstance(i, CommentItem)]
        self._clear_context_bar()
        if not items or self.module != "miro":     # mode CAD (ses propres proprietes) ou aucun module : pas de barre
            self._contextbar.hide()
            return
        kinds = {i.kind for i in items}
        first = items[0]
        add = self._context_layout.addWidget
        bar = self._contextbar
        locked = all(i.locked() for i in items)

        def glyph(kind, tip, slot, on=False):
            button = _GlyphButton(kind, tip, bar, 32)
            button.set_on(on)
            button.clicked.connect(lambda _c=False, b=button: slot(b))
            add(button)
            return button

        if not locked:
            if "shape" in kinds:
                shape = next(i for i in items if i.kind == "shape").data.get("shape", "rect")
                glyph(f"shape:{shape}", "Forme", lambda b: self._open_shape_menu(b, create=False))
            if kinds & set(TEXT_KINDS):
                text_item = next(i for i in items if i.kind in TEXT_KINDS)
                from fm_miro.items import resolve_family
                chosen_family = text_item.data.get("font_family") or ""
                missing = bool(chosen_family) and not font_installed(chosen_family)   # police du fichier absente
                family = chosen_family or resolve_family("")                    # par defaut : Noto Sans ou repli
                font_button = _TextButton(family + (" (absente)" if missing else ""),
                                          "Police (non installée : remplacée à l'affichage)" if missing else "Police",
                                          bar, 130)
                font_button.clicked.connect(lambda _c=False, b=font_button: self._open_font_menu(b))
                add(font_button)
                size = int(text_item.data.get("font_size", 0) or 0)
                size_button = _TextButton("Auto" if size <= 0 else str(size), "Taille du texte", bar, 52)
                size_button.clicked.connect(lambda _c=False, b=size_button: self._open_size_menu(b))
                add(size_button)
                glyph("text_style", "Style du texte (gras, italique, souligné, barré)",
                      lambda b: self._open_text_style_menu(b))
                glyph("align", "Alignement", lambda b: self._open_align_menu(b))
                glyph("text_color", "Couleur du texte", lambda b: self._open_color_menu(
                    b, "text_color", "Couleur du texte", model.COLORS))
                glyph("highlight", "Surlignage du texte", lambda b: self._open_color_menu(
                    b, "text_bg", "Surlignage", model.STICKY_COLORS, allow_none=True))
            glyph("link", "Lien", lambda b: self._open_link_menu(b), on=bool(first.data.get("link")))
            if kinds & {"shape", "connector", "ink"}:
                glyph("border", "Contour (couleur, épaisseur, style, opacité, arrondi)",
                      lambda b: self._open_border_menu(b))
            if kinds & {"sticky", "shape", "frame"}:
                glyph("fill", "Fond (couleur, opacité)", lambda b: self._open_fill_menu(b))
            if "connector" in kinds:
                glyph("arrow", "Flèche (forme, extrémités)", lambda b: self._open_arrow_menu(b))
            if "frame" in kinds:
                glyph("frame_format", "Format du cadre (papier, carré, ratio, orientation)",
                      lambda b: self._open_frame_menu(b, create=False))
            glyph("comment", "Ajouter un commentaire", lambda _b: self._comment_on(first))
        glyph("lock", "Déverrouiller (Ctrl+Maj+L)" if locked else "Verrouiller (Ctrl+Maj+L)",
              lambda _b: (self.view.toggle_lock(self._selected()), self._sync_context_bar()), on=locked)
        glyph("more", "Plus…", lambda b: self._open_more_menu(b))
        self._style_bar_texts()
        # Barre deja affichee (ex. double-clic pour editer un texte : la selection est refaite) : des enfants
        # ajoutes a un widget VISIBLE restent caches tant qu'on ne les montre pas — la mise en page les
        # ignorait et la barre tombait a 12 x 12 px (bug signale).
        for index in range(self._context_layout.count()):
            widget = self._context_layout.itemAt(index).widget()
            if widget is not None:
                widget.show()
        bar.show()
        self._place_chrome()

    def _targets(self, kinds=None, key=None) -> list[BoardItem]:
        items = [i for i in self._selected() if not i.locked() and not isinstance(i, CommentItem)]
        if kinds is not None:
            items = [i for i in items if i.kind in kinds]
        if key is not None:
            items = [i for i in items if key in i.data]
        return items

    def _change(self, items, change, text):
        self.scene.change_items(items, change, text)
        self._sync_context_bar()

    def _set_shape_kind(self, kind: str):
        def change(item):
            item.data["shape"] = kind
            if kind == "round" and float(item.data.get("radius", 0.0)) <= 0:
                item.data["radius"] = round(min(item.data["w"], item.data["h"]) * 0.18, 2)
        self._change(self._targets(("shape",)), change, "Forme")

    def _popup(self, menu, anchor):
        menu.aboutToHide.connect(self.scene.commit_live)
        menu.popup(anchor.mapToGlobal(anchor.rect().bottomLeft()))

    def _open_font_menu(self, anchor):
        """Polices avec APERCU (chaque nom ecrit dans sa police) : la liste habituelle, puis toutes les polices
        installees (liste lue une fois, filtre a la frappe) ; une police du .mro absente est montree comme
        telle (le texte s'affiche avec la police de remplacement, la valeur du fichier est gardee)."""
        from settings_menu import menu_row
        menu = _menu(self, "font")
        targets = self._targets(TEXT_KINDS)
        current = targets[0].data.get("font_family", "") if targets else ""
        from fm_miro.items import resolve_family
        picker = FontPicker(current or resolve_family(""))

        def chosen(family):
            menu.close()
            self._change(self._targets(TEXT_KINDS), lambda i: i.data.update(font_family=family), "Police")
        picker.chosen.connect(chosen)
        menu_row(menu, "", picker)
        menu.aboutToShow.connect(picker.filter.setFocus)
        other = menu.addAction("Autre police… (fenêtre de Windows)")

        def pick_other():
            from PySide6.QtGui import QFont
            ok, font = QFontDialog.getFont(QFont(current or "Noto Sans"), self, "Police")
            if isinstance(ok, QFont):              # selon la version de PySide : (police, ok) ou (ok, police)
                ok, font = font, ok
            if ok:
                self._change(self._targets(TEXT_KINDS), lambda i: i.data.update(font_family=font.family()), "Police")
        other.triggered.connect(lambda: QTimer.singleShot(0, pick_other))
        self._popup(menu, anchor)

    def _open_size_menu(self, anchor):
        menu = _menu(self, "font_size")
        targets = self._targets(TEXT_KINDS)
        current = int(targets[0].data.get("font_size", 0) or 0) if targets else 0
        if any(i.kind == "sticky" for i in targets):
            auto = menu.addAction("Auto (post-it : la plus grande qui tient)")
            auto.setCheckable(True)
            auto.setChecked(current <= 0)
            auto.triggered.connect(lambda: self._change(
                [i for i in self._targets(TEXT_KINDS) if i.kind == "sticky"],
                lambda i: i.data.update(font_size=0), "Taille du texte"))
        for size in model.FONT_SIZES:
            action = menu.addAction(str(size))
            action.setCheckable(True)
            action.setChecked(size == current)
            action.triggered.connect(lambda _c=False, s=size: self._change(
                self._targets(TEXT_KINDS), lambda i: i.data.update(font_size=s), "Taille du texte"))
        from settings_menu import menu_row
        slider = _slider(6, 288, current or 20)
        slider.valueChanged.connect(lambda v: self.scene.live_change(
            "font_size", self._targets(TEXT_KINDS), lambda i: i.data.update(font_size=v), "Taille du texte"))
        menu_row(menu, "Taille", slider)
        menu.aboutToHide.connect(lambda: QTimer.singleShot(0, self._sync_context_bar))
        self._popup(menu, anchor)

    def _open_text_style_menu(self, anchor):
        menu = _menu(self, "text_style")
        targets = self._targets(TEXT_KINDS)
        for key, label in (("bold", "Gras"), ("italic", "Italique"), ("underline", "Souligné"), ("strike", "Barré")):
            action = menu.addAction(label)
            action.setCheckable(True)
            action.setChecked(bool(targets and targets[0].data.get(key)))
            action.triggered.connect(lambda checked, k=key: self._change(
                self._targets(TEXT_KINDS), lambda i: i.data.update({k: bool(checked)}), "Style du texte"))
        self._popup(menu, anchor)

    def _open_align_menu(self, anchor):
        menu = _menu(self, "align")
        targets = self._targets(TEXT_KINDS)
        first = targets[0].data if targets else {}
        for value, label in (("left", "À gauche"), ("center", "Centré"), ("right", "À droite")):
            action = menu.addAction(label)
            action.setCheckable(True)
            action.setChecked(first.get("align") == value)
            action.triggered.connect(lambda _c=False, v=value: self._change(
                self._targets(TEXT_KINDS), lambda i: i.data.update(align=v), "Alignement"))
        menu.addSeparator()
        for value, label in (("top", "En haut"), ("middle", "Au milieu"), ("bottom", "En bas")):
            action = menu.addAction(label)
            action.setCheckable(True)
            action.setChecked(first.get("valign") == value)
            action.triggered.connect(lambda _c=False, v=value: self._change(
                [i for i in self._targets(TEXT_KINDS) if i.kind != "text"], lambda i: i.data.update(valign=v),
                "Alignement vertical"))
        self._popup(menu, anchor)

    def _open_color_menu(self, anchor, key, label, colors, allow_none=False, kinds=TEXT_KINDS):
        from settings_menu import menu_row
        menu = _menu(self, key)
        targets = self._targets(kinds, key)
        current = targets[0].data.get(key) if targets else None
        grid = _SwatchGrid(colors, current, 6)

        def pick(color):
            menu.close()
            self._change(self._targets(kinds, key), lambda i: i.data.update({key: color}), label)
        grid.picked.connect(pick)
        menu_row(menu, label, grid)
        if allow_none:
            none = menu.addAction("Aucun")
            none.triggered.connect(lambda: self._change(self._targets(kinds, key), lambda i: i.data.update({key: ""}),
                                                        label))
        other = menu.addAction("Autre couleur…")
        other.triggered.connect(lambda: QTimer.singleShot(0, lambda: self._custom_color(
            key, label, current, kinds, anchor)))
        self._popup(menu, anchor)

    def _custom_color(self, key, label, current, kinds, anchor):
        """Selecteur de couleur des reglages : apercu en direct, une etape d'annulation (Valider / clic dehors)."""
        from settings_widgets import _ColorPickerPopup
        popup = _ColorPickerPopup(current if isinstance(current, str) and current.startswith("#") else "#ffffff",
                                  label, self)
        popup.colorChanged.connect(lambda c: self.scene.live_change(
            f"color:{key}", self._targets(kinds, key), lambda i: i.data.update({key: c}), label))
        popup.committed.connect(lambda c: (self.scene.live_change(
            f"color:{key}", self._targets(kinds, key), lambda i: i.data.update({key: c}), label),
            self.scene.commit_live(), self._sync_context_bar()))
        def cancel():
            had = self.scene._live is not None and self.scene._live[0] == f"color:{key}"
            self.scene.commit_live()
            if had:
                self.scene.undo.undo()                     # retour a la couleur d'avant (etape retiree)
        popup.cancelled.connect(cancel)
        popup.show_near(anchor)

    def _open_link_menu(self, anchor):
        menu = _menu(self, "link")
        targets = self._targets()
        link = targets[0].data.get("link", "") if targets else ""
        if link:
            show = menu.addAction(f"Ouvrir : {link[:60]}")
            show.triggered.connect(lambda: self.view.open_link(link))
        edit = menu.addAction("Modifier le lien…" if link else "Ajouter un lien (URL ou chemin)…")

        def ask():
            text, ok = QInputDialog.getText(self, "Lien", "URL ou chemin d'un fichier :", text=link)
            if ok:
                self._change(self._targets(), lambda i: i.data.update(link=text.strip()), "Lien")
        edit.triggered.connect(lambda: QTimer.singleShot(0, ask))
        if link:
            drop = menu.addAction("Retirer le lien")
            drop.triggered.connect(lambda: self._change(self._targets(), lambda i: i.data.update(link=""), "Lien"))
        self._popup(menu, anchor)

    def _open_border_menu(self, anchor):
        """Contour : couleur, epaisseur, style, opacite et — en plus de Miro — arrondi des angles (formes
        rectangulaires), borne a la moitie du plus petit cote de la plus petite forme selectionnee."""
        from settings_menu import menu_row
        menu = _menu(self, "border")
        shapes = self._targets(("shape",))
        lines = self._targets(("connector", "ink"))
        stroke_items = shapes + lines
        first = stroke_items[0].data if stroke_items else {}
        color_key = {"shape": "stroke", "connector": "color", "ink": "color"}

        def set_color(color):
            menu.close()
            self._change(self._targets(("shape", "connector", "ink")),
                         lambda i: i.data.update({color_key[i.kind]: color}), "Couleur du contour")
        grid = _SwatchGrid(model.COLORS, first.get("stroke") or first.get("color"), 6)
        grid.picked.connect(set_color)
        menu_row(menu, "Couleur", grid)
        width_key = {"shape": "stroke_width", "connector": "width", "ink": "width"}
        width = _slider(0 if shapes else 1, 24, float(first.get("stroke_width", first.get("width", 2.0))))
        width.valueChanged.connect(lambda v: self.scene.live_change(
            "stroke_width", self._targets(("shape", "connector", "ink")),
            lambda i: i.data.update({width_key[i.kind]: float(v)}), "Épaisseur du contour"))
        menu_row(menu, "Épaisseur", width)
        if shapes or self._targets(("connector",)):
            for value, label in (("solid", "Trait plein"), ("dashed", "Tirets"), ("dotted", "Pointillés")):
                action = menu.addAction(label)
                action.setCheckable(True)
                action.setChecked(first.get("stroke_style", "solid") == value)
                action.triggered.connect(lambda _c=False, v=value: self._change(
                    self._targets(("shape", "connector")), lambda i: i.data.update(stroke_style=v), "Style du contour"))
        if shapes:
            opacity = _slider(0, 100, round(float(shapes[0].data.get("stroke_opacity", 1.0)) * 100), "%")
            opacity.valueChanged.connect(lambda v: self.scene.live_change(
                "stroke_opacity", self._targets(("shape",)), lambda i: i.data.update(stroke_opacity=v / 100),
                "Opacité du contour"))
            menu_row(menu, "Opacité", opacity)
            rounded = [i for i in shapes if i.data.get("shape") in model.RADIUS_SHAPES]
            if rounded:
                bound = int(min(max_radius(*i.size()) for i in rounded))
                value = min(bound, int(round(float(rounded[0].data.get("radius", 0.0)))))
                radius = _slider(0, max(1, bound), value)
                radius.valueChanged.connect(lambda v: self.scene.live_change(
                    "radius", [i for i in self._targets(("shape",)) if i.data.get("shape") in model.RADIUS_SHAPES],
                    lambda i: i.data.update(radius=float(min(v, max_radius(*i.size())))),
                    "Arrondi des angles"))
                menu_row(menu, "Arrondi des angles", radius)
        self._popup(menu, anchor)

    def _open_fill_menu(self, anchor):
        from settings_menu import menu_row
        menu = _menu(self, "fill")
        targets = self._targets(("sticky", "shape", "frame"))
        first = targets[0] if targets else None
        current = first.data.get(COLOR_KEYS[first.kind]) if first else None
        colors = model.STICKY_COLORS if first is not None and first.kind == "sticky" else model.COLORS

        def pick(color):
            menu.close()

            def change(item):
                item.data[COLOR_KEYS[item.kind]] = color
                if item.kind == "shape" and float(item.data.get("fill_opacity", 0.0)) <= 0.0:
                    item.data["fill_opacity"] = 1.0
                if item.kind == "sticky":
                    item.data["text_color"] = model.MIRO_INK if QColor(color).lightness() > 110 else "#ffffff"
            self._change(self._targets(("sticky", "shape", "frame")), change, "Fond")
        grid = _SwatchGrid(colors, current, 6)
        grid.picked.connect(pick)
        menu_row(menu, "Couleur", grid)
        shapes = [i for i in targets if i.kind in ("shape", "frame")]
        if shapes:
            opacity = _slider(0, 100, round(float(shapes[0].data.get("fill_opacity", 0.0)) * 100), "%")
            opacity.valueChanged.connect(lambda v: self.scene.live_change(
                "fill_opacity", self._targets(("shape", "frame")), lambda i: i.data.update(fill_opacity=v / 100),
                "Opacité du fond"))
            menu_row(menu, "Opacité", opacity)
            none = menu.addAction("Transparent")
            none.triggered.connect(lambda: self._change(self._targets(("shape", "frame")),
                                                        lambda i: i.data.update(fill_opacity=0.0), "Fond"))
        other = menu.addAction("Autre couleur…")
        other.triggered.connect(lambda: QTimer.singleShot(0, lambda: self._custom_color(
            COLOR_KEYS.get(first.kind, "fill") if first else "fill", "Fond", current,
            (first.kind,) if first else ("shape",), anchor)))
        self._popup(menu, anchor)

    def _open_arrow_menu(self, anchor):
        menu = _menu(self, "arrow")
        targets = self._targets(("connector",))
        first = targets[0].data if targets else {}
        for value, label in (("straight", "Droite"), ("elbow", "Coudée"), ("curved", "Courbe")):
            action = menu.addAction(label)
            action.setCheckable(True)
            action.setChecked(first.get("style", "straight") == value)
            action.triggered.connect(lambda _c=False, v=value: self._change(
                self._targets(("connector",)), lambda i: i.data.update(style=v), "Forme de la flèche"))
        menu.addSeparator()
        from settings_menu import menu_row
        from fm_miro.items import CAP_KINDS, CAP_LABELS, cap_kind
        for end, label in (("start", "Pointe au départ"), ("end", "Pointe à l'arrivée")):
            sub = _menu(menu, f"arrow_{end}")
            sub.setTitle(label)
            current = cap_kind(first, end) if first else ("filled" if end == "end" else "none")
            for kind in CAP_KINDS:
                action = sub.addAction(cap_icon(kind, end), CAP_LABELS[kind])
                action.setCheckable(True)
                action.setChecked(kind == current)
                action.triggered.connect(lambda _c=False, e=end, k=kind: self._change(
                    self._targets(("connector",)), lambda i: i.data.update({f"{e}_cap": k}), "Pointe de la flèche"))
            menu.addMenu(sub)
        size = _slider(2, 80, round(float(first.get("cap_size", 12.0))) if first else 12)
        size.valueChanged.connect(lambda v: self.scene.live_change(
            "cap_size", self._targets(("connector",)), lambda i: i.data.update(cap_size=float(v)),
            "Taille des pointes"))
        menu_row(menu, "Taille des pointes", size)
        self._popup(menu, anchor)

    def _open_frame_menu(self, anchor, create: bool):
        """Formats des cadres : a la creation (outil Cadre) ou sur les cadres selectionnes. Choisir un format
        verrouille les proportions (largeur gardee, hauteur recalculee) ; le verrou se retire ici pour
        redimensionner librement."""
        menu = _menu(self, "frame_format")
        frames = [] if create else self._targets(("frame",))
        state = dict(self.view.frame_format if create else (frames[0].data if frames else {}))
        fmt = state.get("format", "free")
        for value in model.FRAME_FORMATS:
            label = model.FRAME_LABELS[value]
            if value == "custom" and fmt == "custom":
                w, h = model.parse_ratio(state.get("ratio")) or (16, 9)
                label = f"Ratio personnalisé ({w:g}:{h:g})…"
            action = menu.addAction(label)
            action.setCheckable(True)
            action.setChecked(value == fmt)
            action.triggered.connect(lambda _c=False, v=value: QTimer.singleShot(
                0, lambda: self._set_frame_format({"format": v}, create)))
        menu.addSeparator()
        for value, label in (("portrait", "Portrait"), ("landscape", "Paysage")):
            action = menu.addAction(label)
            action.setCheckable(True)
            action.setChecked(state.get("orientation", "landscape") == value)
            action.setEnabled(fmt not in ("free", "square"))
            action.triggered.connect(lambda _c=False, v=value: self._set_frame_format({"orientation": v}, create))
        lock = menu.addAction("Garder les proportions au redimensionnement")
        lock.setCheckable(True)
        lock.setChecked(bool(state.get("ratio_locked")))
        lock.setEnabled(fmt != "free")
        lock.triggered.connect(lambda checked: self._set_frame_format({"ratio_locked": bool(checked)}, create))
        if not create and fmt in model.FRAME_PAPERS:
            real = menu.addAction("Taille réelle (1 unité = 1/96 de pouce)")
            real.triggered.connect(lambda: self._set_frame_format({}, False, real_size=True))
        if create:
            menu.aboutToHide.connect(lambda: (self.view.set_tool("frame"), self.view.setFocus()))
        self._popup(menu, anchor)

    def _set_frame_format(self, values: dict, create: bool, real_size: bool = False):
        values = dict(values)
        if values.get("format") == "custom":
            current = self.view.frame_format if create else (self._targets(("frame",)) or [None])[0]
            ratio = (current.get("ratio") if isinstance(current, dict) else
                     current.data.get("ratio") if current is not None else [16, 9]) or [16, 9]
            text, ok = QInputDialog.getText(self, "Ratio personnalisé", "Largeur:hauteur (ex. 16:9, 4:3, 2.35:1) :",
                                            text=f"{ratio[0]:g}:{ratio[1]:g}")
            if not ok:
                return
            parsed = model.parse_ratio(text)
            if parsed is None:
                QMessageBox.warning(self, "Ratio personnalisé",
                                    "Ratio invalide : deux nombres strictement positifs, par exemple 16:9.")
                return
            values["ratio"] = [parsed[0], parsed[1]]
            values["orientation"] = "landscape" if parsed[0] >= parsed[1] else "portrait"
        if "format" in values:
            values.setdefault("ratio_locked", values["format"] != "free")
        if create:
            self.view.frame_format.update(values)
            self.view.set_tool("frame")
            self.view.setFocus()
            return

        def change(item):
            item.data.update(values)
            ratio = model.frame_ratio(item.data)
            real = model.paper_size(item.data) if real_size else None
            if real is not None:
                item.data["w"], item.data["h"] = round(real[0], 2), round(real[1], 2)
            elif ratio is not None and ("format" in values or "orientation" in values or "ratio" in values):
                item.data["h"] = round(float(item.data["w"]) / ratio, 2)     # largeur gardee, proportions exactes
        self._change(self._targets(("frame",)), change, "Format du cadre")

    def _open_more_menu(self, anchor):
        menu = _menu(self, "more")
        items = self._selected()
        for label, slot in (("Dupliquer (Ctrl+D)", lambda: self.view.duplicate(items)),
                            ("Copier (Ctrl+C)", self.view.copy_selection),
                            ("Copier en image (PNG, non modifiable)", self.view.copy_selection_image),
                            (None, None),
                            ("Premier plan", lambda: self.scene.bring_to_front(items)),
                            ("Avancer", lambda: self.scene.step_z(items, 1)),
                            ("Reculer", lambda: self.scene.step_z(items, -1)),
                            ("Arrière-plan", lambda: self.scene.send_to_back(items)),
                            (None, None),
                            ("Rotation à 0°", lambda: self._change(
                                self._targets(model.ROTATABLE), lambda i: i.data.update(rotation=0.0), "Rotation")),
                            ("Supprimer (Suppr)", lambda: self.scene.delete_items(items))):
            if label is None:
                menu.addSeparator()
                continue
            action = menu.addAction(label)
            action.triggered.connect(slot)
        self._popup(menu, anchor)

    # -- commentaires --
    def _comment_on(self, item: BoardItem):
        r = item.scene_rect()
        data = model.new_item("comment", x=r.right(), y=r.top(), target=item.item_id, dx=r.width(), dy=0.0)
        comment = self.scene._add(data)
        self._open_comment(comment, True)

    def _open_comment(self, comment, fresh: bool):
        self._comment_panel.open(comment, fresh)

    # -- reglages de la PAGE (propres a ce .mro) --
    def _open_page_menu(self):
        from settings_menu import menu_row
        menu = _menu(self, "page")
        page = self.scene.page
        background = page.get("background") or model.MIRO_BACKGROUND
        color = menu.addAction(f"Couleur du canvas… ({background})")
        color.triggered.connect(lambda: QTimer.singleShot(0, self._pick_page_color))
        reset = menu.addAction(f"Revenir à la couleur Miro ({model.MIRO_BACKGROUND})")
        reset.setEnabled(bool(page.get("background")))
        reset.triggered.connect(lambda: self.scene.set_page({"background": None}, text="Couleur du canvas"))
        grid = _SwatchGrid(["#f2f2f2", "#ffffff", "#fafaf5", "#e9eef6", "#fff8e6", "#e8f4ea", "#2b2b2b", "#1e1f21"],
                           background, 8)

        def pick(c):
            menu.close()
            self.scene.set_page({"background": None if c == model.MIRO_BACKGROUND else c}, text="Couleur du canvas")
        grid.picked.connect(pick)
        menu_row(menu, "Couleurs", grid)
        menu.addSeparator()
        for key, label in (("grid", "Grille"), ("show_resolved", "Afficher les commentaires résolus"),
                           ("export_grid", "Export : grille comprise")):
            action = menu.addAction(label)
            action.setCheckable(True)
            action.setChecked(bool(page.get(key)))
            action.triggered.connect(lambda checked, k=key, lbl=label: self.scene.set_page({k: bool(checked)}, text=lbl))
        menu.addSeparator()
        self._zoom_limit_rows(menu)
        menu.addSeparator()
        transparent = menu.addAction("Export : fond transparent (PNG, SVG)")
        transparent.setCheckable(True)
        transparent.setChecked(page.get("export_background") == "transparent")
        transparent.triggered.connect(lambda checked: self.scene.set_page(
            {"export_background": "transparent" if checked else "page"}, text="Fond de l'export"))
        menu.addSeparator()
        menu.addAction("Exporter une image (PNG, SVG, PDF)…").triggered.connect(self.export_dialog)
        menu.addAction("Importer depuis Miro (JSON de l'API)…").triggered.connect(
            lambda: QTimer.singleShot(0, self.import_miro_dialog))
        menu.addAction("Exporter pour l'API Miro (JSON)…").triggered.connect(
            lambda: QTimer.singleShot(0, self.export_miro_dialog))
        button = self._page_button
        menu.popup(button.mapToGlobal(button.rect().topRight()))

    def _on_page_changed(self):
        """Limites de zoom de la page changees (ou annulees) : le zoom courant y est ramene aussitot."""
        self.view.enforce_limits()
        self._zoom_label.update()

    def _zoom_limit_rows(self, menu):
        from settings_menu import menu_row
        low, high = self.view.limits()
        lo_bound, hi_bound = model.ZOOM_RANGE

        def check_low(value):
            if not (lo_bound <= value <= hi_bound):
                return f"de {format_zoom(lo_bound)} à {format_zoom(hi_bound)}"
            if value >= self.view.limits()[1]:
                return "doit être inférieur au maximum"
            return None

        def check_high(value):
            if not (lo_bound <= value <= hi_bound):
                return f"de {format_zoom(lo_bound)} à {format_zoom(hi_bound)}"
            if value <= self.view.limits()[0]:
                return "doit être supérieur au minimum"
            return None
        minimum = _PercentField(low, check_low)
        minimum.committed.connect(lambda v: self.scene.set_page({"zoom_min": v}, text="Zoom minimal"))
        maximum = _PercentField(high, check_high)
        maximum.committed.connect(lambda v: self.scene.set_page({"zoom_max": v}, text="Zoom maximal"))
        menu_row(menu, "Zoom minimal", minimum)
        menu_row(menu, "Zoom maximal", maximum)
        reset = menu.addAction("Limites de zoom par défaut (10 % – 400 %)")
        reset.setEnabled((low, high) != (0.1, 4.0))
        reset.triggered.connect(lambda: self.scene.set_page({"zoom_min": 0.1, "zoom_max": 4.0},
                                                            text="Limites de zoom"))

    def _pick_page_color(self):
        from settings_widgets import _ColorPickerPopup
        before = dict(self.scene.page)
        popup = _ColorPickerPopup(before.get("background") or model.MIRO_BACKGROUND, "Couleur du canvas", self)
        popup.colorChanged.connect(lambda c: self.scene.set_page({"background": c}, record=False))

        def commit(c):
            self.scene.set_page(before, record=False)
            self.scene.set_page({"background": c}, text="Couleur du canvas")
        popup.committed.connect(commit)
        popup.cancelled.connect(lambda: self.scene.set_page(before, record=False))
        popup.show_near(self._page_button)

    def import_miro_dialog(self):
        path, _ = QFileDialog.getOpenFileName(self, "Importer depuis Miro", str(self.path.parent if self.path else ""),
                                              "JSON de l'API Miro (*.json)")
        if not path:
            return
        try:
            items, report = miro_io.import_api_json(path)
        except (OSError, ValueError) as exc:
            QMessageBox.warning(self, "Import Miro", f"Fichier illisible :\n{exc}")
            return
        if items:
            center = self.view.view_center()
            rect = QRectF()
            for d in items:
                if d["type"] != "connector":
                    rect = rect.united(QRectF(d["x"], d["y"], d.get("w", 1) or 1, d.get("h", 1) or 1))
            self.scene.paste(items, center - rect.center() if rect.isValid() else QPointF(0, 0), "Importer depuis Miro")
        QMessageBox.information(self, "Import Miro", miro_io.describe(report))

    def export_miro_dialog(self):
        if self.path is None:
            return
        path, _ = QFileDialog.getSaveFileName(self, "Exporter pour l'API Miro",
                                              str(self.path.with_name(self.path.stem + "_miro.json")),
                                              "JSON (*.json)")
        if not path:
            return
        import json
        payload, report = miro_io.export_api_json(self.scene.to_data())
        try:
            Path(path).write_text(json.dumps(payload, ensure_ascii=False, indent=1), encoding="utf-8")
        except OSError as exc:
            QMessageBox.warning(self, "Export Miro", str(exc))
            return
        QMessageBox.information(self, "Export Miro", miro_io.describe(report) +
                                "\n\nCe fichier contient les requêtes de création de l'API Miro : il n'est pas "
                                "importable tel quel dans Miro (aucun envoi réseau fait par l'appli).")

    # -- place : la zone des colonnes entiere --
    def eventFilter(self, obj, event):
        if obj is self.parentWidget() and event.type() == QEvent.Resize:
            self.fit()
        elif self.cad_active() and obj is self.view and event.type() == QEvent.KeyPress:
            return False                            # mode CAD : Echap, lettres... vont au controleur CAD
        elif obj is self.view and event.type() == QEvent.KeyPress and event.key() == Qt.Key_Escape:
            if not self.view.editing_text() and not self._selected() and self.view.tool == "select" \
                    and self.view._draft is None:
                if self._comment_panel.isVisible():
                    self._comment_panel.close_panel()
                    return True
                self.closeRequested.emit()
                return True
        elif obj is self.view and event.type() == QEvent.KeyPress and event.key() == Qt.Key_P \
                and not event.modifiers() and not self.view.editing_text():
            self._choose_draw_tool(self._draw_tool if self._draw_tool in ("pen", "highlighter", "smart") else "pen")
            return True
        return super().eventFilter(obj, event)

    def fit(self):
        parent = self.parentWidget()
        if parent is None:
            return
        self.setGeometry(parent.rect())
        self.view.setGeometry(self.rect())
        if self.cad is not None:
            self.cad.overlay.setGeometry(self.view.viewport().rect())
            self.cad.overlay.invalidate()
        self._place_chrome()

    def _place_chrome(self):
        margin = 16
        for panel in (self._toolbar, self._title, self._zoombar, self._contextbar, self._drawbar, self._modulebar):
            panel.layout().activate()                      # contenu refait (barre contextuelle) : taille juste
            panel.resize(panel.sizeHint())
        self._toolbar.move(margin, max(margin + 50, (self.height() - self._toolbar.height()) // 2))
        self._drawbar.move(self._toolbar.geometry().right() + 8,
                           max(margin + 50, (self.height() - self._drawbar.height()) // 2))
        self._title.move(margin, margin)
        title = self._title.geometry()
        self._modulebar.move(title.right() + 8, title.center().y() - self._modulebar.height() // 2)
        self._zoombar.move(self.width() - self._zoombar.width() - margin,
                           self.height() - self._zoombar.height() - margin)
        self._contextbar.move(max(margin, (self.width() - self._contextbar.width()) // 2), margin)
        self._badge.move(self.width() - self._badge.width() - margin, margin)
        self._sync_badge()
        for panel in (self._toolbar, self._drawbar, self._title, self._zoombar, self._contextbar, self._modulebar,
                      self._comment_panel, self._badge):
            panel.raise_()
        if self.cad_active():
            self.cad.ui.place()
        if self.design_active():
            self.design.ui.place()

    def _sync_badge(self):
        """Rendu OpenGL : l'encart est peint par la couche GPU (le widget se cache) ; classique : le widget."""
        gl = self._badge._gl and self.view.gpu_active()
        self._badge.setVisible(not gl)
        rect = None
        if gl:
            top_left = self.view.viewport().mapFrom(self, self._badge.pos())
            rect = QRect(top_left, self._badge.size())
        if rect != self.view.gpu_badge:
            self.view.gpu_badge = rect
            layer = getattr(self.view, "gpu", None)
            if layer is not None:
                layer.request()

    def _on_zoom(self, _zoom: float):
        self._zoom_label.update()
        if self._comment_panel.isVisible():
            self._comment_panel.place()
        self.stateChanged.emit()

    # -- fichier --
    def open(self, path: Path) -> bool:
        path = Path(path)
        try:
            data = serialization.load(path)
            mtime = path.stat().st_mtime_ns
        except (OSError, serialization.BoardError) as exc:
            QMessageBox.warning(self, "Board illisible", f"{path.name} :\n{exc}")
            return False
        if self.cad is not None:
            self.cad.end_command()
            self.cad.last_point = self.cad.last_line_end = None
        self.path, self._mtime, self.source = path, mtime, None
        self.scene.board_path = path
        self.scene.load_data(data)
        self._saved_view = data.get("view") or {}
        self._saved_assets = model.referenced_assets(data)
        self._name.setText(path.stem)
        self._set_dirty(False)
        # Restes d'imports interrompus / annules : seulement plus anciens que le board (dossier synchronise).
        QTimer.singleShot(0, lambda: self._sweep_orphans(mtime))
        return True

    def open_import(self, data: dict, source: Path) -> bool:
        """Dessin DXF / DWG lu par `cad_import` (hors du fil de l'interface) : board en MEMOIRE, le dessin d'origine
        n'est jamais reecrit. Modifie, il est propose en `.mro` a cote a la fermeture (`confirm_leave`) ; images non
        disponibles tant qu'il n'est pas enregistre (pas de dossier d'images)."""
        if self.cad is not None:
            self.cad.end_command()
            self.cad.last_point = self.cad.last_line_end = None
        self.path, self._mtime, self.source = None, None, Path(source)
        self.scene.board_path = None
        self.scene.load_data(model.normalize(data))
        self._saved_view = data.get("view") or {}
        self._saved_assets = set()
        self._name.setText(self.source.name)
        self._set_dirty(False)
        return True

    def companion_path(self) -> Path | None:
        """`.mro` propose pour garder un dessin importe : a cote, « plan.mro », sinon « plan_dxf.mro », « plan_dxf_2.mro »..."""
        if self.source is None:
            return None
        candidate = self.source.with_suffix(model.EXTENSION)
        base = f"{self.source.stem}_{self.source.suffix.lstrip('.').lower()}"
        n = 1
        while candidate.exists():
            candidate = self.source.with_name(f"{base}{'' if n == 1 else f'_{n}'}{model.EXTENSION}")
            n += 1
        return candidate

    def save_import_as_board(self, target: Path | None = None) -> bool:
        """Dessin importe enregistre en board : il devient un board ordinaire (enregistrement automatique...)."""
        target = Path(target) if target is not None else self.companion_path()
        if target is None:
            return False
        data = self.scene.to_data(self._current_view())
        try:
            serialization.save(target, data)
        except OSError as exc:
            QMessageBox.warning(self, "Enregistrement impossible", f"{target.name} :\n{exc}")
            return False
        self.path, self._mtime, self.source = target, target.stat().st_mtime_ns, None
        self.scene.board_path = target
        self._saved_view = data.get("view") or {}
        self._saved_assets = model.referenced_assets(data)
        self._name.setText(target.stem)
        self._set_dirty(False)
        return True

    def _sweep_orphans(self, board_mtime_ns):
        if self.path is None:
            return
        keep = self._saved_assets | self.scene.assets_in_use()
        serialization.cleanup_assets(self.path, keep, min_age_s=serialization.ORPHAN_AGE_S,
                                     older_than=board_mtime_ns / 1e9)

    def restore_view(self):
        view = self._saved_view or {}
        self.view.set_zoom(float(view.get("zoom", 1.0)))
        cx, cy = (view.get("center") or [0.0, 0.0])[:2]
        self.view.center_on(QPointF(float(cx), float(cy)))
        if not view and self.scene.board_items():
            self.view.fit_all()

    def _current_view(self) -> dict:
        center = self.view.view_center()
        return {"zoom": round(self.view.zoom(), 4), "center": [round(center.x(), 2), round(center.y(), 2)]}

    def _on_changed(self):
        self._set_dirty(True)
        self._autosave.start()
        self.stateChanged.emit()

    def _set_dirty(self, dirty: bool):
        from settings_store import M
        from settings_theme import _set_text_role
        if dirty != self._dirty:
            self._dirty = dirty
            self.dirtyChanged.emit(dirty)
        if dirty:
            _set_text_role(self._state, "value_muted", M["dirty_frame"])
            self._state.setText("modifié")
        else:
            _set_text_role(self._state, "value_muted")
            self._state.setText("enregistré" if self.path is not None else
                                "importé, non enregistré" if self.source is not None else "")
        self._title.adjustSize()

    def is_dirty(self) -> bool:
        return self._dirty

    def save(self, with_view: bool = False) -> bool:
        """Ecrit le board (contenu modifie, ou la vue quand on ferme). Modifie ailleurs : on demande. Apres un
        enregistrement REUSSI seulement : images inutilisees retirees (voir `serialization`)."""
        self._autosave.stop()
        path = self.path
        if path is None:
            return True
        view = self._current_view()
        if not self._dirty and not (with_view and view != self._saved_view):
            return True
        try:
            changed_elsewhere = path.exists() and path.stat().st_mtime_ns != self._mtime
        except OSError:
            changed_elsewhere = False
        if changed_elsewhere:
            box = QMessageBox(QMessageBox.Warning, "Board modifié ailleurs",
                              f"« {path.name} » a été modifié en dehors de l'appli depuis son ouverture.", parent=self)
            keep = box.addButton("Garder ma version", QMessageBox.AcceptRole)
            reload = box.addButton("Recharger le fichier", QMessageBox.DestructiveRole)
            box.addButton("Annuler", QMessageBox.RejectRole)
            box.exec()
            if box.clickedButton() is reload:
                return self.reload()
            if box.clickedButton() is not keep:
                return False
        data = self.scene.to_data(view)
        try:
            serialization.save(path, data)
            self._mtime = path.stat().st_mtime_ns
        except OSError as exc:
            QMessageBox.warning(self, "Enregistrement impossible", f"{path.name} :\n{exc}")
            return False
        try:
            import previews
            previews.forget_mtime(path)
        except Exception:
            pass
        self._saved_view = view
        self._saved_assets = model.referenced_assets(data)
        self._set_dirty(False)
        self.cleanup_assets()
        return True

    def cleanup_assets(self, closing: bool = False) -> list:
        """Images du dossier qui ne servent plus : ni dans le fichier enregistre, ni (sauf a la fermeture)
        dans un etat accessible par l'annulation."""
        if self.path is None:
            return []
        keep = set(self._saved_assets)
        if not closing:
            keep |= self.scene.assets_in_use()
        return serialization.cleanup_assets(self.path, keep)

    def reload(self) -> bool:
        if self.path is None:
            return False
        view = self._current_view()
        if not self.open(self.path):
            return False
        self._saved_view = view
        self.restore_view()
        return True

    def confirm_leave(self) -> bool:
        """Avant de fermer : enregistre (contenu et vue) puis retire les images qui ne servent plus (la pile
        d'annulation disparait). Echec : on demande s'il faut fermer quand meme (rien n'est retire)."""
        self._comment_panel.close_panel()
        if self.cad is not None:
            self.cad.end_command()                  # segments deja traces : gardes, dans l'annulation
        if self.view.editing_text():
            self.scene.focusItem().clearFocus()
        self.scene.commit_live()
        if self.path is None and self.source is not None:
            if not self._dirty:
                return True
            target = self.companion_path()
            box = QMessageBox(QMessageBox.Question, "Dessin modifié",
                              f"« {self.source.name} » a été modifié dans le board (le fichier d'origine n'est jamais "
                              f"réécrit).\nL'enregistrer en board « {target.name} » à côté ?", parent=self)
            keep = box.addButton("Enregistrer en .mro", QMessageBox.AcceptRole)
            drop = box.addButton("Fermer sans enregistrer", QMessageBox.DestructiveRole)
            box.addButton("Annuler", QMessageBox.RejectRole)
            box.exec()
            if box.clickedButton() is keep:
                return self.save_import_as_board(target)
            return box.clickedButton() is drop
        if self.save(with_view=True):
            self.cleanup_assets(closing=True)
            return True
        answer = QMessageBox.question(self, "Board non enregistré",
                                      f"« {self.path.name} » n'a pas pu être enregistré. Fermer quand même ?")
        return answer == QMessageBox.Yes

    # -- actions de la barre de navigation --
    def undo(self):
        if self.cad is not None:
            self.cad.before_history()
        self.view.finish_text_edit()
        self.scene.commit_live()
        self.scene.undo.undo()

    def redo(self):
        if self.cad is not None:
            self.cad.before_history()
        self.view.finish_text_edit()
        self.scene.undo.redo()

    def can_undo(self) -> bool:
        return self.scene.undo.canUndo()

    def can_redo(self) -> bool:
        return self.scene.undo.canRedo()

    def insert_image_dialog(self):
        if self.path is None:
            return
        files, _ = QFileDialog.getOpenFileNames(self, "Ajouter des images", str(self.path.parent),
                                                "Images (*.png *.jpg *.jpeg *.gif *.bmp *.webp *.tif *.tiff)")
        if files:
            self.view.add_image_files([Path(f) for f in files], self.view.view_center())
        self.view.setFocus()

    def export_dialog(self):
        base = self.path or self.source
        if base is None:
            return
        target, chosen = QFileDialog.getSaveFileName(
            self, "Exporter le board", str(base.with_suffix(".png")),
            "Image PNG (*.png);;Image SVG (*.svg);;Document PDF (*.pdf);;"
            "Dessin DXF — lignes CAD (*.dxf);;Dessin DWG — lignes CAD (*.dwg)")
        if not target:
            return
        suffix = Path(target).suffix.lower()
        if suffix not in (".png", ".svg", ".pdf", ".dxf", ".dwg"):    # nom tape sans extension : celle du filtre
            suffix = "." + chosen.rsplit("*.", 1)[-1].rstrip(")")
            target = str(Path(target).with_suffix(suffix))
        if suffix in (".dxf", ".dwg"):
            self.export_cad(target)
            return
        try:
            export.export(self.scene, target)
        except Exception as exc:                            # noqa: BLE001 - message a l'utilisateur
            QMessageBox.warning(self, "Export impossible", str(exc))

    def export_cad(self, target: str | None = None, suffix: str = ".dxf"):
        """Lignes CAD et calques en DXF (ou DWG par ODA File Converter) ; unites demandees (voir cad_export)."""
        from PySide6.QtWidgets import QInputDialog
        from fm_cad import cad_export
        if target is None:
            base = self.path or self.source
            if base is None:
                return
            label = "Dessin DWG (*.dwg)" if suffix == ".dwg" else "Dessin DXF (*.dxf)"
            target, _ = QFileDialog.getSaveFileName(self, "Exporter les lignes CAD", str(base.with_suffix(suffix)),
                                                    label)
            if not target:
                return
            if Path(target).suffix.lower() != suffix:
                target = str(Path(target).with_suffix(suffix))
        labels = [label for label, _f, _u in cad_export.UNITS.values()]
        keys = list(cad_export.UNITS)
        if self._cad_export_units in keys:
            last = keys.index(self._cad_export_units)
        else:                                       # 1er export : l'unite de mesure du dessin
            drawing = cad_model.drawing_unit(cad_model.page_cad(self.scene.page), self.scene.cad_unit)
            last = keys.index(drawing) if drawing in keys else 0
        choice, ok = QInputDialog.getItem(self, "Unités du fichier", "Unités du dessin exporté :", labels, last, False)
        if not ok:
            return
        units = keys[labels.index(choice)]
        self._cad_export_units = units
        try:
            if Path(target).suffix.lower() == ".dwg":
                cad_export.export_dwg(self.scene, target, units)
            else:
                cad_export.export_dxf(self.scene, target, units)
        except Exception as exc:                            # noqa: BLE001 - message a l'utilisateur
            QMessageBox.warning(self, "Export impossible", str(exc))
            return
        if self.cad is not None:
            self.cad.message(f"Exporté : {Path(target).name}")

    # -- apparition / disparition : fondu court, l'effet est retire a la fin --
    def fade_in(self):
        self.fit()
        self.show()
        self.raise_()
        self.restore_view()
        self._fade(0.0, 1.0, None)
        self.view.setFocus()

    def fade_out(self, done):
        self._fade(1.0, 0.0, done)

    def _fade(self, start: float, end: float, done):
        effect = QGraphicsOpacityEffect(self)
        effect.setOpacity(start)
        self.setGraphicsEffect(effect)
        animation = QPropertyAnimation(effect, b"opacity", self)
        animation.setDuration(FADE_MS)
        animation.setStartValue(start)
        animation.setEndValue(end)
        animation.setEasingCurve(QEasingCurve.OutCubic)

        def finished():
            self.setGraphicsEffect(None)
            if done is not None:
                done()
        animation.finished.connect(finished)
        animation.start(QPropertyAnimation.DeleteWhenStopped)
        self._animation = animation
