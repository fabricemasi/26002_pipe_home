"""Barre des modules du board (maquette « Barre des modules », demande de l'utilisateur, 2026-10-31).

Panneau VERTICAL collé au bord gauche du board, toute la hauteur : une ligne par module (Miro, CAD, Design, Tableur,
Illustrator). Par ligne : l'icône du module (couleur DOMINANTE du module, trait dessous = visible, gris = grisé,
sombre = masqué ou hors isolation ; clic = activer le module et SA barre d'outils, re-clic = aucun module ; Alt + clic
= isoler), puis trois boutons : afficher / masquer, griser (visible, non éditable), isoler. En haut : bouton qui
replie / déplie la barre ; en bas : tout réinitialiser (tout afficher, sortir de l'isolation). DEUX FAÇONS DE
REPLIER, au choix dans les réglages (`board_modulebar_fold_style`, demande de l'utilisateur) : « narrow » (PREMIÈRE
maquette : la barre reste, étroite, icônes seules ; point de la couleur d'isolation en haut à droite de l'icône d'un
module isolé) ou « tab » (SECONDE maquette : la barre disparaît entièrement, une languette au bord gauche, à
mi-hauteur, la fait revenir ; point d'isolation sur la languette). Pendant une isolation, encart « Isolé : … » +
« Quitter l'isolation » DANS la barre, juste au-dessus du bouton tout réinitialiser (demande de l'utilisateur ; il
était en haut au milieu du board) ; barre étroite : bouton ambre « Quitter l'isolation » (icône seule) à la
même place (demande de l'utilisateur).

L'état (masquer / griser / isoler) est dans la scène (`BoardScene.module_state`, affichage seulement) ; le panneau ne
fait qu'émettre des signaux et se recaler sur cet état (`sync`). HABILLAGE : Réglages : Board > Board > Barre de
sélection (clés `board_modulebar_*`, défauts = la maquette), lu par `modulebar_look` et posé par `set_look` (un seul
habillage pour tous les boards, comme les réglages). Rien n'est repeint si l'état ni l'habillage n'ont changé (les
panneaux sont repeints à chaque image du board)."""
from weakref import WeakSet

from PySide6.QtCore import QEvent, QPoint, QPointF, QRectF, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QImage, QPainter, QPainterPath, QPen, QPixmap
from PySide6.QtWidgets import QApplication, QHBoxLayout, QLabel, QPushButton, QVBoxLayout, QWidget
from shiboken6 import isValid

from fm_theme import icon_frame, icon_library

from .settings_defaults import BOARD_DEFAULTS
from .ui import _GlyphButton, custom_icon, negative_pixmap, paint_glyph

MODULE_NAMES = ("miro", "cad", "design", "tableur", "illustrator", "photoshop", "pdf")
MODULE_EMBLEMS = {
    "miro": "modules/miro/tableau_blanc_03",
    "cad": "modules/cad/cad_04",
    "design": "modules/design/design_03",
    "tableur": "modules/tableur/tableur_04",
    "illustrator": "modules/illustrator/vectoriel_03",
    "photoshop": "modules/photoshop/retouche_03",
    "pdf": "modules/pdf/pdf_04",
}
_EMBLEMES_VISIBLES = WeakSet()
DARK = "#121316"                       # glyphe sur un bouton allume (fond de sa couleur)
PREFIX = "board_modulebar_"


def _value(settings: dict, key: str):
    key = PREFIX + key
    return settings.get(key, BOARD_DEFAULTS[key])


def _color(settings: dict, key: str) -> str:
    value = _value(settings, key)
    try:
        from app_style import resolve_color_ref                # couleur des reglages (peut etre une reference)
        return resolve_color_ref(value, BOARD_DEFAULTS[PREFIX + key])
    except Exception:                                           # noqa: BLE001 - paquet seul : la valeur telle quelle
        return str(value)


def _int(settings: dict, key: str, low: int, high: int) -> int:
    value = _value(settings, key)
    try:
        return max(low, min(high, int(value)))
    except (TypeError, ValueError):
        return max(low, min(high, int(BOARD_DEFAULTS[PREFIX + key])))


def modulebar_look(settings: dict | None) -> dict:
    """Habillage de la barre des modules (Reglages : Board > Board > Barre de selection)."""
    s = settings or {}
    look = {
        "buttons": bool(_value(s, "buttons")), "reset": bool(_value(s, "reset")),
        "alt_solo": bool(_value(s, "alt_solo")), "pill": bool(_value(s, "pill")),
        "long_press": _int(s, "long_press_ms", 150, 2000),
        "fold_style": "tab" if _value(s, "fold_style") == "tab" else "narrow",
        "bg": _color(s, "bg_color"), "edge": _color(s, "border_color"),
        "icon": _int(s, "icon_size", 20, 64), "button": _int(s, "button_size", 14, 40),
        "spacing": _int(s, "spacing", 0, 20), "padding": _int(s, "padding", 0, 24),
        "radius": _int(s, "row_radius", 0, 20), "row": _color(s, "row_color"),
        "active": _int(s, "active_alpha", 0, 100), "active_border": _int(s, "active_border", 0, 6),
        "hover": _color(s, "hover_color"),
        "ink": _color(s, "ink_color"), "dim_ink": _color(s, "dim_color"), "off_ink": _color(s, "off_color"),
        "fade": _color(s, "fade_color"), "solo": _color(s, "solo_color"), "tool": _color(s, "tool_color"),
        "tool_hover": _int(s, "tool_hover_alpha", 0, 100),
        "tab_w": _int(s, "tab_width", 8, 40), "tab_h": _int(s, "tab_height", 24, 160),
        "tab_bg": _color(s, "tab_color"), "tab_ink": _color(s, "tab_ink"),
        "pill_bg": _color(s, "pill_color"), "pill_size": _int(s, "pill_font_size", 8, 24),
        "colors": {m: _color(s, f"color_{m}") for m in MODULE_NAMES},
        "pads": {m: _int(s, f"icon_pad_{m}", 0, 16) for m in MODULE_NAMES},
        "tints": {m: bool(_value(s, f"icon_tint_{m}")) for m in MODULE_NAMES},
    }
    look["key"] = repr(sorted((k, v if not isinstance(v, dict) else sorted(v.items())) for k, v in look.items()))
    return look


LOOK = modulebar_look({})


def set_look(look: dict) -> bool:
    """Pose l'habillage commun ; faux s'il n'a pas change (rien a refaire)."""
    global LOOK
    if look["key"] == LOOK["key"]:
        return False
    LOOK = look
    return True


def _alpha(color: str, alpha: int) -> QColor:
    c = QColor(color)
    c.setAlpha(max(0, min(255, alpha)))
    return c


def effective(state: dict, solo_any: bool) -> str:
    """Etat affiche d'un module : « on », « dim » (grise), « off » (masque) ou « iso » (hors isolation)."""
    if solo_any:
        return ("dim" if state["fade"] else "on") if state["solo"] else "iso"
    return "off" if state["hide"] else "dim" if state["fade"] else "on"


def _draw_glyph(painter, kind: str, rect: QRectF, ink: str):
    side = int(min(rect.width(), rect.height()) * 0.62)
    pixmap = custom_icon(kind, side)                          # icone perso (Reglages > Module MRO > Icones)
    if pixmap is not None and not pixmap.isNull():
        if QColor(ink).lightness() < 60:
            pixmap = negative_pixmap(pixmap)
        target = QRectF(0, 0, pixmap.width() / max(1.0, pixmap.devicePixelRatio()),
                        pixmap.height() / max(1.0, pixmap.devicePixelRatio()))
        target.moveCenter(rect.center())
        painter.drawPixmap(target, pixmap, QRectF(pixmap.rect()))
    else:
        paint_glyph(painter, kind, rect, QColor(ink))


def _rafraichir_emblemes(modules=None):
    for bouton in _EMBLEMES_VISIBLES:
        if isValid(bouton) and (modules is None or bouton.kind in modules):
            bouton._painted = None
            bouton.update()


icon_library.on_change(_rafraichir_emblemes)
icon_frame.on_change(_rafraichir_emblemes)


def _tinted(pixmap, ink: str):
    """Copie de `pixmap` dont toute la forme prend la couleur `ink` (anticrénelage gardé)."""
    image = pixmap.toImage().convertToFormat(QImage.Format_ARGB32_Premultiplied)
    p = QPainter(image)
    p.setCompositionMode(QPainter.CompositionMode_SourceIn)
    p.fillRect(image.rect(), QColor(ink))
    p.end()
    out = QPixmap.fromImage(image)
    out.setDevicePixelRatio(pixmap.devicePixelRatio())
    return out


class _ModuleIcon(_GlyphButton):
    """Icone d'un module : glyphe de sa couleur (plus de trait dessous : demande du 2026-11-13), centre dans sa case
    avec l'espace regle par module (`pads`), fond du module actif. APPUI LONG (reglage
    `board_modulebar_long_press_ms`, 500 ms) : `longPressed(tous)` (ses boutons se deploient a cote ; Ctrl tenu a
    l'appui ou au declenchement : ceux de TOUS les modules) et pas de clic."""

    longPressed = Signal(bool)

    def __init__(self, kind: str, tip: str, parent):
        super().__init__(kind, tip, parent, LOOK["icon"])
        self.state = "on"
        self.active = False
        self.solo_mark = False                                  # module isole : point de la couleur d'isolation
        self._long = QTimer(self)
        self._long.setSingleShot(True)
        self._long.timeout.connect(self._long_press)
        _EMBLEMES_VISIBLES.add(self)

    def mousePressEvent(self, event):
        super().mousePressEvent(event)
        if event.button() == Qt.LeftButton and LOOK["buttons"]:
            self._ctrl = bool(QApplication.keyboardModifiers() & Qt.ControlModifier)
            self._long.start(LOOK["long_press"])

    def mouseMoveEvent(self, event):
        flyout = self._armed_flyout()
        if flyout is not None:                                  # bouton tenu apres l'appui long : survol du volet
            flyout.drag_to(event.globalPosition().toPoint())
            return
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        self._long.stop()
        flyout = self._armed_flyout()
        if flyout is not None:                                  # choix AU RELACHEMENT (demande, 2026-11-05)
            flyout.release_at(event.globalPosition().toPoint())
            return
        super().mouseReleaseEvent(event)

    def _armed_flyout(self):
        bar = self.parentWidget()
        while bar is not None and not hasattr(bar, "open_flyout"):
            bar = bar.parentWidget()
        flyout = getattr(bar, "_flyout", None) if bar is not None else None
        return flyout if flyout is not None and flyout.isVisible() and flyout.armed else None

    def _long_press(self):
        if self.isDown():
            self.setDown(False)                                 # pas de clic au relachement
            ctrl = getattr(self, "_ctrl", False) or bool(QApplication.keyboardModifiers() & Qt.ControlModifier)
            self.longPressed.emit(ctrl)

    def paint_key(self) -> tuple:
        return (self.kind, self.state, self.active, self.solo_mark, LOOK["key"])

    def _draw_emblem(self, painter, rect, ink, tint: bool = False):
        """L'icône choisie garde la priorité ; elle prend TOUTE la place, comme celles de la bibliothèque (avant : 62 %,
        les icônes choisies paraissaient toutes petites ; demande du 2026-11-13). `tint` (toggle « Couleur du module »,
        Barre de sélection > Icônes) : icône de la bibliothèque en MONOCHROME teinté de `ink`, icône choisie peinte de
        `ink` sur toute sa forme. Le dessin entier du bouton est déjà mis en cache (`paint_key`)."""
        side = int(min(rect.width(), rect.height()))
        pixmap = custom_icon(self.kind, side)
        if pixmap is not None and not pixmap.isNull():
            if tint:
                pixmap = _tinted(pixmap, ink)
            elif QColor(ink).lightness() < 60:
                pixmap = negative_pixmap(pixmap)
        else:
            identifiant = MODULE_EMBLEMS.get(self.kind)
            if identifiant is not None:
                style = icon_library.MONOCHROME if tint else icon_library.style_affiche(self.state == "on")
                if icon_library.peindre(painter, rect, identifiant, style=style,
                                        teinte=None if style == icon_library.COULEUR else ink):
                    return
            paint_glyph(painter, self.kind, rect, QColor(ink))
            return
        target = QRectF(0, 0, *pixmap.deviceIndependentSize().toTuple())
        target.moveCenter(rect.center())
        painter.drawPixmap(target, pixmap, QRectF(pixmap.rect()))

    def paint_content(self, painter):
        look = LOOK
        color = look["colors"].get(self.kind, look["ink"])
        painter.setRenderHint(QPainter.Antialiasing, True)
        rect = QRectF(self.rect())
        radius = max(0, look["radius"] - 1)
        if self.active or self.underMouse():
            fill = _alpha(color, round(look["active"] * 2.55)) if self.active else QColor(look["hover"])
            painter.setPen(Qt.NoPen)
            painter.setBrush(fill)
            painter.drawRoundedRect(rect, radius, radius)
        if self.active and look["active_border"] > 0:            # module actif : bordure de sa couleur
            width = look["active_border"]
            painter.setPen(QPen(QColor(color), width))
            painter.setBrush(Qt.NoBrush)
            edge = rect.adjusted(width / 2, width / 2, -width / 2, -width / 2)
            painter.drawRoundedRect(edge, max(0.0, radius - width / 2), max(0.0, radius - width / 2))
        ink = color if self.state == "on" else look["dim_ink"] if self.state == "dim" else look["off_ink"]
        unit = rect.width() / 36
        pad = min(look["pads"].get(self.kind, 3) * unit, rect.width() / 2 - 2)
        self._draw_emblem(painter, rect.adjusted(pad, pad, -pad, -pad), ink, look["tints"].get(self.kind, False))
        if self.solo_mark:
            painter.setPen(Qt.NoPen)
            painter.setBrush(QColor(look["solo"]))
            painter.drawEllipse(QPointF(rect.right() - 6.5 * unit, rect.top() + 6.5 * unit), 3.5 * unit, 3.5 * unit)


class _StateButton(_GlyphButton):
    """Petit bouton d'une ligne (afficher / griser / isoler) : allume = fond de sa couleur, glyphe sombre."""

    def __init__(self, kind: str, tip: str, parent, accent: str | None = None):
        super().__init__(kind, tip, parent, LOOK["button"])
        self.accent = accent                                    # cle de couleur de l'habillage (« fade », « solo »)
        self.ink = "dim_ink"

    def paint_key(self) -> tuple:
        return (self.kind, self._on, self.ink, LOOK["key"])

    def paint_content(self, painter):
        look = LOOK
        painter.setRenderHint(QPainter.Antialiasing, True)
        rect = QRectF(self.rect())
        lit = self._on and self.accent is not None
        if lit or self.underMouse():
            painter.setPen(Qt.NoPen)
            painter.setBrush(QColor(look[self.accent] if lit else look["hover"]))
            radius = max(0, look["radius"] - 2)
            painter.drawRoundedRect(rect, radius, radius)
        _draw_glyph(painter, self.kind, rect, DARK if lit else look[self.ink])


class _ToolButton(_GlyphButton):
    """Bouton replier / deplier (haut) et tout reinitialiser (bas) : glyphe de la couleur reglee ; survol = fond de
    cette couleur a faible opacite (20 % par defaut, demande de l'utilisateur)."""

    def paint_key(self) -> tuple:
        return super().paint_key() + (self._on, LOOK["key"])

    def glyph_ink(self, invert: bool) -> str:
        return LOOK["tool"]

    def paint_content(self, painter):
        look = LOOK
        painter.setRenderHint(QPainter.Antialiasing, True)
        rect = QRectF(self.rect())
        if self.underMouse() or self._on:                       # allume (grille affichee) : meme fond que le survol
            painter.setPen(Qt.NoPen)
            painter.setBrush(_alpha(look["tool"], round(look["tool_hover"] * 2.55)))
            radius = max(0, look["radius"] - 1)
            painter.drawRoundedRect(rect, radius, radius)
        _draw_glyph(painter, self.kind, rect.adjusted(2, 2, -2, -2), look["tool"])


class _SoloExitButton(_GlyphButton):
    """Barre etroite : « Quitter l'isolation » en icone seule (cible barree), couleur de l'isolation."""

    def __init__(self, parent):
        super().__init__("solo_exit", "Quitter l'isolation", parent, LOOK["icon"])

    def paint_key(self) -> tuple:
        return (self.kind, LOOK["key"])

    def paint_content(self, painter):
        look = LOOK
        painter.setRenderHint(QPainter.Antialiasing, True)
        rect = QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)
        painter.setPen(QPen(_alpha(look["solo"], 140), 1))
        painter.setBrush(_alpha(look["solo"], 77 if self.underMouse() else 30))
        radius = max(0, look["radius"] - 1)
        painter.drawRoundedRect(rect, radius, radius)
        unit = rect.width() / 36
        _draw_glyph(painter, self.kind, rect.adjusted(4 * unit, 4 * unit, -4 * unit, -4 * unit), look["solo"])


class _ModuleRow(QWidget):
    """Ligne d'un module : icone + afficher / griser / isoler ; fond si visible, cadre d'isolation si isole."""

    def __init__(self, name: str, label: str, tip: str, parent):
        super().__init__(parent)
        self.name = name
        self.label = label
        self._key = None
        layout = QHBoxLayout(self)
        layout.setContentsMargins(3, 3, 3, 3)
        layout.setSpacing(2)
        self.icon = _ModuleIcon(name, tip, self)
        self.vis = _StateButton("show", f"Afficher / masquer les éléments {label}", self)
        self.dim = _StateButton("fade", f"Griser les éléments {label} (visibles, ni sélectionnables ni modifiables)",
                                self, "fade")
        self.solo = _StateButton("solo", f"Isoler les éléments {label} (Alt + clic sur l'icône)", self, "solo")
        layout.addWidget(self.icon)
        for button in (self.vis, self.dim, self.solo):
            layout.addWidget(button, 0, Qt.AlignVCenter)

    def restyle(self, folded: bool = False):
        look = LOOK
        folded = True                                          # la barre garde TOUJOURS la meme largeur : boutons en volet
        self.icon.setFixedSize(look["icon"], look["icon"])
        tip = self.icon.toolTip().split("\n")[0]
        self.icon.setToolTip(tip + ("\nClic : activer le module (sa barre d'outils) ; Alt + clic : isoler ses "
                                    "éléments" if look["alt_solo"] else "\nClic : activer le module (sa barre "
                                                                        "d'outils)")
                             + ("\nAppui long : afficher / griser / isoler" if look["buttons"] else ""))
        for button in (self.vis, self.dim, self.solo):
            button.setFixedSize(look["button"], look["button"])
            if button.parentWidget() is self:
                button.setVisible(look["buttons"] and not folded)
        self._key = None
        self.layout().invalidate()                              # largeur juste tout de suite (barre etroite)
        self.layout().activate()
        self.updateGeometry()

    def sync(self, active: bool, state: dict, solo_any: bool, folded: bool = False):
        folded = True
        eff = effective(state, solo_any)
        key = (active, eff, state["hide"], state["fade"], state["solo"], LOOK["key"], folded)
        if key == self._key:
            return
        self._key = key
        self.icon.state = eff
        self.icon.active = active
        self.icon.solo_mark = state["solo"] and folded
        self.icon.update()
        shown = not state["hide"] or state["solo"]
        self.vis.kind = "show" if shown else "hide"
        self.vis.ink = "ink" if shown else "off_ink"
        self.vis.update()
        self.dim.set_on(state["fade"])
        self.solo.set_on(state["solo"])
        self.update()

    def paintEvent(self, event):
        if self._key is None:
            return
        eff, solo = self._key[1], self._key[4]
        if not solo and eff != "on":
            return
        look = LOOK
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing, True)
        if solo:
            painter.setPen(QPen(_alpha(look["solo"], 140), 1))
            painter.setBrush(_alpha(look["solo"], 26))
        else:
            painter.setPen(Qt.NoPen)
            painter.setBrush(QColor(look["row"]))
        painter.drawRoundedRect(QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5), look["radius"], look["radius"])
        painter.end()


class ModuleBar(QWidget):
    """Panneau des modules (voir l'en-tete). Signaux : `moduleClicked(nom, alt)`, `lookToggled(nom, « hide » /
    « fade » / « solo »)`, `resetClicked()`."""

    moduleClicked = Signal(str, bool)
    lookToggled = Signal(str, str)
    resetClicked = Signal()
    gridClicked = Signal()
    backgroundClicked = Signal()
    foldClicked = Signal()
    exitSoloClicked = Signal()

    def __init__(self, modules, parent):
        super().__init__(parent)
        self.folded = False
        layout = QVBoxLayout(self)
        self._head = QWidget(self)
        self._head.setStyleSheet("background: transparent;")
        head = QHBoxLayout(self._head)
        head.setContentsMargins(0, 0, 0, 6)
        self.fold = _ToolButton("modules_fold", "Replier la barre", self._head, 32)
        self.fold.clicked.connect(self.foldClicked.emit)
        head.addWidget(self.fold, 0, Qt.AlignHCenter)
        layout.addWidget(self._head)
        self.rows = {}
        for name, label, tip in modules:
            row = _ModuleRow(name, label, tip, self)
            row.icon.clicked.connect(lambda _c=False, n=name: self.moduleClicked.emit(
                n, bool(QApplication.keyboardModifiers() & Qt.AltModifier)))
            row.vis.clicked.connect(lambda _c=False, n=name: self.lookToggled.emit(n, "hide"))
            row.dim.clicked.connect(lambda _c=False, n=name: self.lookToggled.emit(n, "fade"))
            row.solo.clicked.connect(lambda _c=False, n=name: self.lookToggled.emit(n, "solo"))
            for button in (row.vis, row.dim, row.solo):           # (apres le signal : le choix est deja fait)
                button.clicked.connect(self._choice_made)
            row.icon.longPressed.connect(lambda every, r=row: self.open_flyout(r, every))
            layout.addWidget(row)
            self.rows[name] = row
        layout.addStretch(1)
        self.pill = SoloPill(self)
        self.pill.exitClicked.connect(self.exitSoloClicked.emit)
        layout.addWidget(self.pill)
        self.solo_exit = _SoloExitButton(self)                 # barre etroite : quitter l'isolation (icone)
        self.solo_exit.clicked.connect(self.exitSoloClicked.emit)
        self.solo_exit.hide()
        layout.addWidget(self.solo_exit, 0, Qt.AlignHCenter)
        self._solo_names = []
        self._foot = QWidget(self)
        self._foot.setStyleSheet("background: transparent;")    # la feuille de l'appli lui donnait un fond
        foot = QVBoxLayout(self._foot)
        foot.setContentsMargins(0, 6, 0, 0)
        # au-dessus de « tout reinitialiser » : grille, couleur de fond de la vue (demande de l'utilisateur, 2026-11-03)
        self.grid = _ToolButton("grid", "Afficher / masquer la grille", self._foot, 32)
        self.grid.clicked.connect(self.gridClicked.emit)
        foot.addWidget(self.grid, 0, Qt.AlignHCenter)
        self.background = _ToolButton("modules_bg", "Couleur de fond de la vue", self._foot, 32)
        self.background.clicked.connect(self.backgroundClicked.emit)
        foot.addWidget(self.background, 0, Qt.AlignHCenter)
        self.reset = _ToolButton("modules_reset", "Tout afficher, sortir de l'isolation", self._foot, 32)
        self.reset.clicked.connect(self.resetClicked.emit)
        foot.addWidget(self.reset, 0, Qt.AlignHCenter)
        layout.addWidget(self._foot)
        self.restyle()

    def restyle(self):
        """Habillage change (`set_look`) : tailles, marges, boutons montres, puis tout repeint."""
        look = LOOK
        pad = look["padding"]
        self.layout().setContentsMargins(pad, pad, pad + 1, pad)
        self.layout().setSpacing(look["spacing"])
        for row in self.rows.values():
            row.restyle(self.folded)
        self.pill.restyle()
        self.solo_exit.setFixedSize(look["icon"], look["icon"])
        self._sync_pill()
        self._foot.setVisible(look["reset"])
        self._head.setVisible(False)                            # toujours etroite : rien a replier (languette : `FoldTab`)
        for button in self.findChildren(_GlyphButton):
            button.update()
        self.layout().invalidate()
        self.layout().activate()
        self.update()

    def set_folded(self, folded: bool):
        """Repliee en barre etroite : icones seules (les boutons des lignes caches)."""
        self._head.setVisible(False)                            # toujours etroite : rien a replier
        if folded == self.folded:
            return
        self.folded = folded
        self.fold.kind = "modules_unfold" if folded else "modules_fold"
        self.fold.setToolTip("Déplier la barre" if folded else "Replier la barre")
        self.restyle()

    def sync(self, active: str | None, states: dict, solo_names: list[str] | None = None):
        solo_any = any(s["solo"] for s in states.values())
        for name, row in self.rows.items():
            row.sync(active == name, states[name], solo_any, self.folded)
        self._solo_names = list(solo_names or [])
        self._sync_pill()

    def _sync_pill(self):
        """Encart « Isolé » : seulement pendant une isolation, et si le reglage le montre ; aussi large que les lignes
        (son texte passe a la ligne). Barre etroite : le bouton « Quitter l'isolation » seul, en icone."""
        isolated = bool(self._solo_names) and LOOK["pill"]
        compact = isolated                                      # barre toujours etroite : le bouton seul
        if compact:
            self.solo_exit.setToolTip("Isolé : " + ", ".join(self._solo_names) + "\nQuitter l'isolation")
        if self.solo_exit.isVisibleTo(self) != compact:
            self.solo_exit.setVisible(compact)
        show = False
        if show:
            width = max((row.sizeHint().width() for row in self.rows.values()), default=100)
            if self.pill.width() != width:
                self.pill.setFixedWidth(width)
            self.pill.set_names(self._solo_names)
            self.pill.fit_button(width)
        if self.pill.isVisibleTo(self) != show:
            self.pill.setVisible(show)

    def open_flyout(self, row: "_ModuleRow", every: bool = False):
        """Appui long sur l'icone d'un module : ses trois boutons (afficher / griser / isoler) dans un volet a droite de
        sa ligne ; la barre ne change pas de largeur. `every` (Ctrl + appui long, demande de l'utilisateur,
        2026-11-04) : les boutons de TOUS les modules, chacun en face de sa ligne, ouverts jusqu'a un clic ailleurs
        (fenetre « popup ») ; volet d'UN module : refermé des qu'un choix est fait."""
        flyout = getattr(self, "_flyout", None)
        if flyout is None:
            flyout = self._flyout = _RowFlyout(self)
        flyout.open_for(list(self.rows.values()) if every else [row])

    def _choice_made(self):
        flyout = getattr(self, "_flyout", None)
        if flyout is not None and flyout.isVisible() and flyout.single():
            flyout.hide()

    def paintEvent(self, event):
        look = LOOK
        edge = QColor(look["edge"])
        painter = QPainter(self)
        painter.fillRect(self.rect(), QColor(look["bg"]))
        painter.fillRect(QRectF(self.width() - 1, 0, 1, self.height()), edge)
        if self._head.isVisible():
            painter.fillRect(QRectF(0, self._head.geometry().bottom() + 1, self.width() - 1, 1), edge)
        if self._foot.isVisible():
            painter.fillRect(QRectF(0, self._foot.geometry().top(), self.width() - 1, 1), edge)
        painter.end()


class _RowFlyout(QWidget):
    """Volet des boutons d'un ou de TOUS les modules (appui long / Ctrl + appui long sur une icone) : les boutons DES
    LIGNES y sont poses le temps de l'ouverture (memes signaux, meme etat), chaque groupe en face de sa ligne, puis
    rendus a leur ligne (caches) a la fermeture."""

    GAP = 4                                                     # entre la barre et le volet

    def __init__(self, bar):
        super().__init__(bar, Qt.Popup | Qt.FramelessWindowHint | Qt.NoDropShadowWindowHint)
        self.setAttribute(Qt.WA_TranslucentBackground, True)
        self._rows = []
        self._groups = []                                       # rectangle de fond de chaque groupe (coordonnees du volet)
        # Ouvert par un appui long dont le bouton est encore tenu : glisser sur un bouton le surligne, le relacher
        # l'applique (demande, 2026-11-05) ; relache ailleurs : le volet reste ouvert pour un clic (comme avant).
        self.armed = False
        self._hot = None

    def single(self) -> bool:
        return len(self._rows) == 1

    def open_for(self, rows):
        self._give_back()
        self._rows = list(rows)
        look = LOOK
        pad_x, pad_y, spacing = 4, 3, 2
        size = look["button"]
        height = max(look["icon"] + 6, size + 2 * pad_y)
        width = 2 * pad_x + 3 * size + 2 * spacing
        tops = [row.mapToGlobal(QPoint(0, (row.height() - height) // 2)).y() for row in self._rows]
        top = min(tops)
        bottom = max(t + height for t in tops)
        self._groups = []
        for row, row_top in zip(self._rows, tops):
            y = row_top - top
            self._groups.append(QRectF(0, y, width, height))
            x = pad_x
            for button in (row.vis, row.dim, row.solo):
                button.setParent(self)
                button.installEventFilter(self)                 # geste tenu : leurs evenements reviennent au volet
                button.move(x, y + (height - size) // 2)
                button.show()
                x += size + spacing
        self.setFixedSize(width, bottom - top)
        first = self._rows[0]
        self.move(QPoint(first.mapToGlobal(QPoint(first.width() + self.GAP, 0)).x(), top))
        self.armed = bool(QApplication.mouseButtons() & Qt.LeftButton)
        self._hot = None
        self.show()
        self.raise_()

    def _button_at(self, global_pos: QPoint):
        for row in self._rows:
            for button in (row.vis, row.dim, row.solo):
                if button.isVisible() and button.rect().contains(button.mapFromGlobal(global_pos)):
                    return button
        return None

    def drag_to(self, global_pos: QPoint) -> None:
        """Bouton tenu : le bouton du volet sous le pointeur est montre enfonce."""
        hot = self._button_at(global_pos)
        if hot is not self._hot:
            if self._hot is not None:
                self._hot.setDown(False)
            if hot is not None:
                hot.setDown(True)
            self._hot = hot

    def release_at(self, global_pos: QPoint) -> None:
        """Bouton relache : le bouton du volet sous le pointeur est applique (un clic)."""
        self.armed = False
        if self._hot is not None:
            self._hot.setDown(False)
            self._hot = None
        button = self._button_at(global_pos)
        if button is not None:
            button.click()

    def eventFilter(self, obj, event):
        if self.armed and event.type() == QEvent.MouseMove:
            self.drag_to(event.globalPosition().toPoint())
            return True
        if self.armed and event.type() == QEvent.MouseButtonRelease and event.button() == Qt.LeftButton:
            self.release_at(event.globalPosition().toPoint())
            return True
        return super().eventFilter(obj, event)

    def mouseMoveEvent(self, event):                            # volet « popup » : il recoit le geste tenu
        if self.armed:
            self.drag_to(event.globalPosition().toPoint())
            return
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        if self.armed and event.button() == Qt.LeftButton:
            self.release_at(event.globalPosition().toPoint())
            return
        super().mouseReleaseEvent(event)

    def _give_back(self):
        rows, self._rows = self._rows, []
        for row in rows:
            for button in (row.vis, row.dim, row.solo):
                button.removeEventFilter(self)
                button.hide()
                button.setParent(row)
                row.layout().addWidget(button, 0, Qt.AlignVCenter)
                button.hide()

    def hideEvent(self, event):
        self._give_back()
        super().hideEvent(event)

    def paintEvent(self, event):
        look = LOOK
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing, True)
        painter.setPen(QPen(QColor(look["edge"]), 1))
        painter.setBrush(QColor(look["bg"]))
        for rect in self._groups:
            painter.drawRoundedRect(rect.adjusted(0.5, 0.5, -0.5, -0.5), look["radius"], look["radius"])
        painter.end()


class FoldTab(QWidget):
    """Languette du bord gauche (repli « tab ») : replie / deplie la barre ; point d'isolation (repliee, isole)."""

    clicked = Signal()

    def __init__(self, parent):
        super().__init__(parent)
        self.setCursor(Qt.PointingHandCursor)
        self.expanded = True
        self.solo = False
        self.restyle()

    def restyle(self):
        self.setFixedSize(LOOK["tab_w"], LOOK["tab_h"])
        self.update()

    def set_state(self, expanded: bool, solo: bool):
        if (expanded, solo) != (self.expanded, self.solo):
            self.expanded, self.solo = expanded, solo
            self.setToolTip("Replier la barre des modules" if expanded else "Déplier la barre des modules")
            self.update()

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.LeftButton and self.rect().contains(event.position().toPoint()):
            self.clicked.emit()

    def enterEvent(self, event):
        self.update()

    def leaveEvent(self, event):
        self.update()

    def paintEvent(self, event):
        look = LOOK
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing, True)
        r = QRectF(self.rect()).adjusted(-8, 0.5, -0.5, -0.5)      # coins droits seulement
        painter.setPen(QPen(QColor(look["edge"]), 1))
        painter.setBrush(QColor(look["hover"] if self.underMouse() else look["tab_bg"]))
        painter.drawRoundedRect(r, 8, 8)
        pen = QPen(QColor(look["tab_ink"]), 1.8)
        pen.setCapStyle(Qt.RoundCap)
        pen.setJoinStyle(Qt.RoundJoin)
        painter.setPen(pen)
        cx, cy, d = self.width() / 2, self.height() / 2, 3.0
        sign = 1 if self.expanded else -1                           # vers la gauche : replier
        path = QPainterPath()
        path.moveTo(cx + sign * d / 2, cy - d)
        path.lineTo(cx - sign * d / 2, cy)
        path.lineTo(cx + sign * d / 2, cy + d)
        painter.setBrush(Qt.NoBrush)
        painter.drawPath(path)
        if self.solo and not self.expanded:
            painter.setPen(Qt.NoPen)
            painter.setBrush(QColor(look["solo"]))
            painter.drawEllipse(QPointF(self.width() / 2 - 1, self.height() - 9), 3, 3)
        painter.end()


class SoloPill(QWidget):
    """Encart « Isolé : … » + « Quitter l'isolation » (dans la barre, au-dessus de tout reinitialiser)."""

    exitClicked = Signal()

    def __init__(self, parent):
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 6, 8, 6)
        layout.setSpacing(5)
        self.text = QLabel(self)
        self.text.setWordWrap(True)
        self.button = QPushButton("Quitter l'isolation", self)
        self.button.setCursor(Qt.PointingHandCursor)
        self.button.clicked.connect(self.exitClicked.emit)
        layout.addWidget(self.text)
        layout.addWidget(self.button)
        self.restyle()
        self.hide()

    def restyle(self):
        look = LOOK
        solo = QColor(look["solo"])
        size = look["pill_size"]
        self.text.setStyleSheet(f"color: {solo.name()}; background: transparent; font-size: {size}px;")
        from fm_theme.style import theme_button
        theme_button(self.button)                         # aspect : fm_theme seul (2026-11-12)
        self.adjustSize()
        self.update()

    def fit_button(self, width: int):
        """« Quitter l'isolation », ou « Quitter » si la barre est trop etroite pour le texte entier."""
        self.button.ensurePolished()
        full = "Quitter l'isolation"
        room = width - 16 - 14                              # marges de l'encart et du bouton
        text = full if self.button.fontMetrics().horizontalAdvance(full) <= room else "Quitter"
        if self.button.text() != text:
            self.button.setText(text)
            self.button.setToolTip(full)

    def set_names(self, names: list[str]):
        text = "Isolé : " + ", ".join(names)
        if text != self.text.text():
            self.text.setText(text)
            self.adjustSize()

    def paintEvent(self, event):
        look = LOOK
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing, True)
        painter.setPen(QPen(_alpha(look["solo"], 115), 1))
        painter.setBrush(QColor(look["pill_bg"]))
        r = QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)
        radius = LOOK["radius"]
        painter.drawRoundedRect(r, radius, radius)
        painter.end()
