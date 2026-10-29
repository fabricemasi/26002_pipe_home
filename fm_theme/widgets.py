from PySide6.QtCore import (
    QEasingCurve, QEvent, QPoint, QPointF, QRect, QRectF, Qt, QTimer, QVariantAnimation, Signal,
)
from PySide6.QtGui import (
    QColor,
    QCursor,
    QDoubleValidator,
    QFont,
    QGuiApplication,
    QIntValidator,
    QLinearGradient,
    QPainter,
    QPainterPath,
    QPen,
    QPixmap,
)
from PySide6.QtWidgets import (
    QApplication,
    QFrame,
    QGraphicsOpacityEffect,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMenu,
    QPushButton,
    QBoxLayout,
    QSizePolicy,
    QSpacerItem,
    QVBoxLayout,
    QWidget,
)
from fm_theme.style import (
    SEMANTIC_COLOR_SLOTS,
    _hex_to_alpha,
    _hex_to_rgb,
    apply_dwm_frame,
    get_input_radius,
    installed_font_families,
    ITEM_FONT_ROLE_LABELS,
)
from fm_theme.theme import _input_radius, _qfont, _register_input, _register_radius, _set_text_role
from fm_theme.menu import Menu, menu_row  # noqa: F401 (reexporte : menus contextuels)
from settings_store import (
    M,
    input_bg,
    input_border_decl,
    input_height,
    _CORNERS,
    _SLIDER_STYLE,
    _coerce_corner_radius,
    _coerce_side_enabled,
    _resolve_color_value,
)


# ==========================================================================
# Petits widgets reproduisant les controles de la maquette.
# ==========================================================================


# Lignes ajoutees aux menus contextuels de la fenetre de reglages (cellules, entetes de tableau,
# curseurs, titres) : chaque fournisseur recoit (widget clique, menu) et y ajoute ce qu'il veut.
# Le moteur ne sait rien de ce qui est ajoute (ex. « Ajouter une espace au-dessus » en v2).
CONTEXT_MENU_EXTRAS: list = []

# Style PROPRE d'un element (« Override settings », settings_element_style) : identifiant de
# l'element (« table:<cle de dimensions> ») -> etat resolu (voir settings_layout.table_look_scope).
# Rempli depuis les reglages (`element_style_overrides`), lu par chaque tableau a son affichage.
ELEMENT_LOOKS: dict = {}

# Style PROPRE d'une partie d'un tableau (« Override settings » > cellule / ligne / colonne, et police
# du tableau entier) : cle de dimensions du tableau -> {("cell", r, c) | ("row", r) | ("col", c) |
# ("table",) : {"bg", "padding", "font"}} (indices LOGIQUES), pose par settings_layout.apply_part_looks.
PART_LOOKS: dict = {}


# Fournisseurs appeles APRES tous les autres (fin de menu) : « Override settings » quand aucune
# ligne d'espace ne l'a deja pose (voir SPACE_MENU_HOOKS).
CONTEXT_MENU_FINAL: list = []

# Rappels (widget clique, menu, contexte des espaces) poses a la suite des lignes « Ajouter une espace
# au-dessus / en dessous » (make_space_actions) : « Override settings » apparait partout ou elles sont.
# Contexte : {"above", "below", "set_above", "set_below"}.
SPACE_MENU_HOOKS: list = []


def add_context_extras(widget: QWidget, menu: QMenu) -> None:
    for provider in list(CONTEXT_MENU_EXTRAS):
        provider(widget, menu)
    for provider in list(CONTEXT_MENU_FINAL):
        provider(widget, menu)


def run_space_menu_hooks(widget: QWidget | None, menu: QMenu, context: dict) -> None:
    """Apres des lignes d'espace : les rappels de SPACE_MENU_HOOKS (une seule fois par menu)."""
    if widget is None or getattr(menu, "_space_hooks_done", False):
        return
    menu._space_hooks_done = True
    for hook in list(SPACE_MENU_HOOKS):
        hook(widget, menu, context)


# Couleur des selections des tableaux (Tableaux > Couleur de selection) : colonnes et sous-cellules
# selectionnees (teinte translucide), carte du toggle choisi (Toggles > Style).
_TABLE_SELECTION = {"color": "#5f9bd0"}


def _selection_color(alpha: int) -> QColor:
    color = QColor(_TABLE_SELECTION["color"])
    color.setAlpha(alpha)
    return color


def _locate_in_layout(layout, widget: QWidget):
    """(layout, rang) du layout (eventuellement imbrique) qui contient directement `widget`."""
    for i in range(layout.count()):
        item = layout.itemAt(i)
        if item.widget() is widget:
            return layout, i
        if item.layout() is not None:
            found = _locate_in_layout(item.layout(), widget)
            if found:
                return found
    return None


def space_target(widget: QWidget | None, root: QWidget) -> QWidget | None:
    """Element de l'interface sous un clic droit auquel on peut ajouter une espace au-dessus : le
    premier widget (en remontant depuis `widget`) qui occupe une place dans un empilement VERTICAL
    (ou seul dans une ligne horizontale imbriquee, comme un tableau dans le corps d'un titre)."""
    w = widget
    while w is not None and w is not root:
        parent = w.parentWidget()
        if parent is None:
            return None
        lay = parent.layout()
        found = _locate_in_layout(lay, w) if lay is not None else None
        if found is not None:
            layout = found[0]
            if isinstance(layout, QBoxLayout) and layout.direction() in (QBoxLayout.TopToBottom,
                                                                         QBoxLayout.BottomToTop):
                return w
            if layout is not lay and isinstance(layout, QHBoxLayout) and                     sum(1 for i in range(layout.count()) if layout.itemAt(i).widget()) == 1:
                return w
        w = parent
    return None


def widget_path(widget: QWidget, root: QWidget) -> str | None:
    """Chemin stable de `widget` sous `root` (type + rang parmi les enfants de ce type), pour
    retrouver l'element a la reouverture (voir widget_at_path)."""
    parts, w = [], widget
    while w is not None and w is not root:
        parent = w.parentWidget()
        if parent is None:
            return None
        same = [c for c in parent.children() if isinstance(c, QWidget) and type(c) is type(w)]
        parts.append(f"{type(w).__name__}#{same.index(w)}")
        w = parent
    return "/".join(reversed(parts)) if w is root else None


def widget_at_path(root: QWidget, path: str) -> QWidget | None:
    w = root
    for part in path.split("/"):
        name, _, rank = part.rpartition("#")
        kids = [c for c in w.children() if isinstance(c, QWidget) and type(c).__name__ == name]
        if not rank.isdigit() or int(rank) >= len(kids):
            return None
        w = kids[int(rank)]
    return w


SPACE_ABOVE_TEXT = "Ajouter une espace au-dessus"
SPACE_BELOW_TEXT = "Ajouter une espace en dessous"


def make_space_action(menu: QMenu, value: int, on_change, maximum: int = 200, text_font=None,
                      text: str = SPACE_ABOVE_TEXT, separator: bool = True) -> None:
    """Ligne de menu « Ajouter une espace au-dessus » (ou `text`) + curseur (px, en direct). Police et
    alignement : ceux des menus contextuels (settings_menu ; `text_font` n'est plus utilise)."""
    field = _SliderField(0, maximum, int(value), slider_width=140, box_width=60)
    field.valueChanged.connect(on_change)
    if separator and menu.actions():
        menu.addSeparator()
    menu_row(menu, text, field)


def make_space_actions(menu: QMenu, above: int, below: int, on_above, on_below, maximum: int = 200,
                       text_font=None, widget: QWidget | None = None) -> None:
    """Les deux lignes « Ajouter une espace au-dessus / en dessous » + leurs curseurs, groupees ;
    `widget` (element clique) : suivies des lignes de SPACE_MENU_HOOKS (« Override settings »)."""
    make_space_action(menu, above, on_above, maximum, text_font)
    make_space_action(menu, below, on_below, maximum, text_font, text=SPACE_BELOW_TEXT, separator=False)
    run_space_menu_hooks(widget, menu, {"above": above, "below": below, "set_above": on_above,
                                        "set_below": on_below, "maximum": maximum})


def set_space_above(widget: QWidget, height: int) -> None:
    """Espace vide de `height` px AU-DESSUS de `widget`, dans le layout qui le contient (0 = aucun).
    Layout vertical : un espaceur fixe juste avant lui ; ligne horizontale (un tableau dans le corps
    d'un titre) : la marge haute de cette ligne. Retenu dans `widget._space_above_px`."""
    height = max(0, int(height))
    widget._space_above_px = height
    parent = widget.parentWidget()
    found = _locate_in_layout(parent.layout(), widget) if parent is not None and parent.layout() is not None else None
    if found is None:
        return
    layout, index = found
    if isinstance(layout, QHBoxLayout):
        m = layout.contentsMargins()
        layout.setContentsMargins(m.left(), height, m.right(), m.bottom())
        return
    spacer = getattr(widget, "_space_above_item", None)
    if spacer is None:
        if not height:
            return
        spacer = QSpacerItem(0, height, QSizePolicy.Minimum, QSizePolicy.Fixed)
        layout.insertItem(index, spacer)
        widget._space_above_item = spacer
    else:
        spacer.changeSize(0, height, QSizePolicy.Minimum, QSizePolicy.Fixed)
    layout.invalidate()


def set_space_below(widget: QWidget, height: int) -> None:
    """Espace vide de `height` px EN DESSOUS de `widget` (pendant de set_space_above) : un espaceur
    fixe juste apres lui, ou la marge basse de sa ligne horizontale. Retenu dans
    `widget._space_below_px`."""
    height = max(0, int(height))
    widget._space_below_px = height
    parent = widget.parentWidget()
    found = _locate_in_layout(parent.layout(), widget) if parent is not None and parent.layout() is not None else None
    if found is None:
        return
    layout, index = found
    if isinstance(layout, QHBoxLayout):
        m = layout.contentsMargins()
        layout.setContentsMargins(m.left(), m.top(), m.right(), height)
        return
    spacer = getattr(widget, "_space_below_item", None)
    if spacer is None:
        if not height:
            return
        spacer = QSpacerItem(0, height, QSizePolicy.Minimum, QSizePolicy.Fixed)
        layout.insertItem(index + 1, spacer)
        widget._space_below_item = spacer
    else:
        spacer.changeSize(0, height, QSizePolicy.Minimum, QSizePolicy.Fixed)
    layout.invalidate()


class _WidthBadge(QLabel):
    """Encart « N px » pose sur un entete (titre de colonne, legende de sous-cellule) pendant son
    redimensionnement, SANS toucher au titre. Un encart par colonne / sous-cellule concernee ; la
    valeur est la largeur REELLE mesuree (pas la largeur demandee : un minimum, un contenu plus large
    ou la derniere colonne extensible peuvent la changer, surtout en multiselection)."""

    _GAP = 3

    def __init__(self, host: QWidget):
        super().__init__(host)
        _set_text_role(self, "width_badge")
        self.setAlignment(Qt.AlignCenter)
        self.setContentsMargins(5, 0, 5, 0)
        self.setAttribute(Qt.WA_TransparentForMouseEvents, True)   # simple texte, aucun controle
        self.hide()

    def show_on(self, rect: QRect, width: int):
        """Affiche la largeur `width` dans `rect` (repere de l'hote) : collee a droite de l'entete,
        centree s'il est trop etroit, sans jamais deborder de l'hote."""
        self.setText(f"{width} px")
        self.adjustSize()
        w, h = self.width(), min(self.height(), max(10, rect.height() - 2))
        self.resize(w, h)
        if rect.width() >= w + 2 * self._GAP:
            x = rect.right() + 1 - w - self._GAP
        else:
            x = rect.center().x() - w // 2
        host = self.parentWidget()
        x = max(0, min(x, host.width() - w))
        self.move(x, rect.top() + (rect.height() - h) // 2)
        self.raise_()
        self.show()

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing, True)
        p.setPen(QPen(QColor(M["accent_border"]), 1))
        p.setBrush(QColor(M["accent"]))
        p.drawRoundedRect(QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5), 3, 3)
        p.end()
        super().paintEvent(event)


def _width_badges(host: QWidget, count: int) -> list:
    """Encarts de largeur d'un entete (un par colonne / sous-cellule), crees a la demande."""
    badges = getattr(host, "_width_badge_list", None)
    if badges is None or len(badges) < count:
        badges = (badges or []) + [_WidthBadge(host) for _ in range(count - len(badges or []))]
        host._width_badge_list = badges
    return badges


def _hide_width_badges(host: QWidget):
    for badge in getattr(host, "_width_badge_list", None) or []:
        badge.hide()


class _Btn(QPushButton):
    """Bouton rectangulaire plat. Son arrondi suit TOUJOURS Geometrie >
    Boutons > Coins arrondis (inscription automatique, voir
    settings_theme._register_radius) : ne jamais le fixer a la main."""

    def __init__(self, text: str, bg: str, border: str, fg: str, hover: str,
                 height: int = 24, weight: int = 500, padding: str = "0 11px", align_left: bool = False,
                 parent=None):
        super().__init__(text, parent)
        self.setFixedHeight(height)
        self.setCursor(Qt.ArrowCursor)
        self.setFocusPolicy(Qt.NoFocus)
        self.setFont(_qfont(11, weight))
        self._bg, self._border, self._fg, self._hover, self._padding = bg, border, fg, hover, padding
        self._align_left = align_left
        # Rayon : Geometrie > Boutons > Coins arrondis, suivi en direct (voir settings_theme).
        self._radius = _register_radius(self, "button")
        self._refresh_style()

    def _refresh_style(self):
        border_rule = f"border: 1px solid {self._border};" if self._border else "border: none;"
        self.setStyleSheet(
            f"QPushButton {{ background: {self._bg}; {border_rule} border-radius: {self._radius}px; "
            f"color: {self._fg}; padding: {self._padding}; }}"
            f"QPushButton:hover {{ background: {self._hover}; }}"
            + ("QPushButton { text-align: left; }" if self._align_left else "")
        )

    def setRadius(self, radius: int):
        self._radius = max(0, int(radius))
        self._refresh_style()

class _MiniSlider(QWidget):
    """Slider peint a la main : rail + curseur ("selecteur"), habillage
    entierement lu depuis _SLIDER_STYLE (voir Geometrie > Slider) plutot que
    fige en dur — voir apply_style, a rappeler sur toute instance deja
    construite quand ce reglage change."""

    valueChanged = Signal(int)

    def __init__(self, minimum: int, maximum: int, value: int, width: int = 170, parent=None):
        super().__init__(parent)
        self._min, self._max = minimum, maximum
        self._value = max(minimum, min(maximum, value))
        self._width = width
        self._grab_offset = 0
        self.setCursor(Qt.ArrowCursor)
        self._apply_size()

    def _apply_size(self):
        # +8 : meme marge verticale que l'ancien fixe (14 + 8 = 22) —
        # garde le curseur/le rail respirer plutot que toucher les bords
        # haut/bas du widget quel que soit thumb_h/track_h.
        h = max(_SLIDER_STYLE["thumb_h"], _SLIDER_STYLE["track_h"]) + 8
        self.setFixedSize(self._width, h)

    def apply_style(self):
        """A rappeler sur toute instance deja construite quand Geometrie >
        Slider change (voir SettingsWindow._apply_slider_style) : thumb_h/
        track_h influent sur la hauteur meme du widget, pas seulement sa
        peinture — un simple update() ne suffirait pas pour ces deux-la."""
        self._apply_size()
        self.update()

    def value(self) -> int:
        return self._value

    def setValue(self, value: int):
        value = max(self._min, min(self._max, value))
        if value != self._value:
            self._value = value
            self.update()
            self.valueChanged.emit(value)

    def _pct(self) -> float:
        span = self._max - self._min
        return 0.0 if span <= 0 else (self._value - self._min) / span

    def _set_from_x(self, x: int):
        pct = max(0.0, min(1.0, x / max(1, self.width())))
        self.setValue(round(self._min + pct * (self._max - self._min)))

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            x = event.position().toPoint().x()
            # Clic SUR le curseur : on le saisit la ou il est (pas de saut
            # vers le pointeur) ; ailleurs, il vient sous le pointeur.
            thumb_w = _SLIDER_STYLE["thumb_w"]
            knob_center = round(self._pct() * self.width())
            self._grab_offset = x - knob_center if abs(x - knob_center) <= thumb_w // 2 + 2 else 0
            # Ancrage ECRAN du glisser : la valeur suit le deplacement de la souris depuis le clic,
            # pas sa position dans le curseur. Un reglage applique en direct qui deplace le curseur
            # lui-meme (ex. padding gauche d'un titre qui decale le tableau) ne fait donc plus
            # repartir la valeur en arriere sous la souris immobile (a-coups en boucle).
            self._press_x = x - self._grab_offset
            self._press_global_x = event.globalPosition().x()
            self._set_from_x(self._press_x)

    def mouseMoveEvent(self, event):
        if event.buttons() & Qt.LeftButton:
            start = getattr(self, "_press_global_x", None)
            if start is None:
                self._set_from_x(event.position().toPoint().x() - self._grab_offset)
            else:
                self._set_from_x(round(self._press_x + event.globalPosition().x() - start))

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.LeftButton:
            self._press_global_x = None
        super().mouseReleaseEvent(event)

    def mouseDoubleClickEvent(self, event):
        """Double-clic SUR le curseur (la poignée) : `knob_double_clicked` (ex. valeur d'origine) ; ailleurs, le
        double-clic reste un clic (le curseur vient sous le pointeur)."""
        handler = getattr(self, "knob_double_clicked", None)
        if event.button() == Qt.LeftButton and handler is not None:
            x = event.position().toPoint().x()
            if abs(x - round(self._pct() * self.width())) <= _SLIDER_STYLE["thumb_w"] // 2 + 3:
                self._press_global_x = None
                handler()
                event.accept()
                return
        self.mousePressEvent(event)

    def _paint_bordered(self, p: QPainter, rect: QRect, radius, border_on,
                         border_colors: dict, fill_layers, key=None):
        """Peint `rect` (rail ou selecteur) avec, cote par cote actif, une
        bordure 1px MITREE (diagonales depuis le centre vers chaque coin,
        comme un cadre photo) plutot que 4 bandes droites independantes —
        celles-ci restaient bien 4 couleurs differentes sur un rectangle
        (radius=0) mais DISPARAISSAIENT pres des coins des que radius>0 (la
        bande, toujours large d'1 PIXEL en ligne droite, sort du contour
        arrondi qui se retrecit vers le coin — voir la remarque de
        l'utilisateur, capture a l'appui, "quelque chose de bizarre avec
        les bordures des rails"). Le miter, lui, reste une bordure
        CONTINUE quel que soit le rayon : chaque cote occupe le triangle
        entre ses 2 coins et le centre du rectangle, intersecte avec
        l'anneau exterieur-moins-interieur (les 2 chemins arrondis) —
        exactement comme les 4 cotes d'un cadre a coins coupes a 45°.

        `border_on` : bool (tous les cotes pareil, retro-compatible) OU
        dict {"top": bool, ...} — un cote DESACTIVE (voir _SideColorsField,
        la remarque de l'utilisateur "un toggle par cote") ne consomme plus
        d'epaisseur de CE cote (inset ASYMETRIQUE), le remplissage s'etend
        alors jusqu'a ce bord tout en restant en retrait des autres, actifs.
        `fill_layers` (callable prenant `p, inner_rect`) peint l'interieur —
        `inner_rect` deja calcule en tenant compte de cet inset asymetrique,
        rempli JUSQU'AU bord de chaque cote sans bordure active.
        `key` (decrit tout ce qui est peint) : rendu sur-echantillonne et lisse (_paint_smooth),
        clip arrondi du remplissage compris (un setClipPath direct n'est pas antialiase)."""
        if rect.width() <= 0 or rect.height() <= 0:
            return
        if key is not None and _smooth_paintable(p, rect):
            _paint_smooth(p, rect, (key, _hashable(radius), _hashable(border_on), _hashable(border_colors)),
                          lambda sp, local: self._paint_bordered(sp, local, radius, border_on,
                                                                 border_colors, fill_layers))
            return
        if isinstance(border_on, dict):
            sides_on = {k: bool(border_on.get(k, False)) for k in ("top", "right", "bottom", "left")}
        else:
            v = bool(border_on)
            sides_on = {k: v for k in ("top", "right", "bottom", "left")}
        any_on = any(sides_on.values())
        t = {k: (1 if sides_on[k] else 0) for k in sides_on}
        inner_rect = QRect(
            rect.left() + t["left"], rect.top() + t["top"],
            rect.width() - t["left"] - t["right"], rect.height() - t["top"] - t["bottom"],
        )
        has_inner = inner_rect.width() > 0 and inner_rect.height() > 0
        p.save()
        p.setRenderHint(QPainter.Antialiasing, _radius_any(radius))
        if any_on:
            outer_path = _rounded_rect_path(rect, radius)
            inner_radius = _radius_shrink(radius, 1)
            # QRectF(rect), PAS rect.right()/rect.bottom() : ces 2 methodes
            # de QRect sont INCLUSIVES (topLeft + taille - 1, la convention
            # "dernier pixel valide" de QRect), alors que addRoundedRect
            # travaille en coordonnees CONTINUES (QRectF, right/bottom =
            # topLeft + taille, sans le -1) — un ecart d'1px entre les coins
            # du triangle mitre et le contour arrondi reel, qui faisait
            # disparaitre ou deformer 1 ou plusieurs cotes selon le rayon/la
            # hauteur (voir la remarque de l'utilisateur, capture a l'appui,
            # "je suis sense avoir les 4 bordures").
            ring = outer_path.subtracted(_rounded_rect_path(inner_rect, inner_radius)) if has_inner else outer_path
            rf = QRectF(rect)
            center = rf.center()
            corners = {
                "top": (QPointF(rf.left(), rf.top()), QPointF(rf.right(), rf.top())),
                "right": (QPointF(rf.right(), rf.top()), QPointF(rf.right(), rf.bottom())),
                "bottom": (QPointF(rf.right(), rf.bottom()), QPointF(rf.left(), rf.bottom())),
                "left": (QPointF(rf.left(), rf.bottom()), QPointF(rf.left(), rf.top())),
            }
            p.setPen(Qt.NoPen)
            # Voir _paint_bordered_rect (meme technique/meme raison) : chaque
            # coin allonge de EPS UNIQUEMENT du cote ou le voisin de ce coin
            # est desactive (le vrai trou) — jamais quand les 2 cotes d'un
            # coin sont actifs. Et meme dans ce cas (2 cotes actifs), 2
            # morceaux de meme couleur sont ACCUMULES puis peints en UNE
            # seule fois (united()) plutot que separement, pour ne pas
            # laisser de lisere fantome sur la diagonale du miter (2 formes
            # anti-aliasees peintes separement ne se recouvrent jamais
            # exactement pixel pour pixel).
            EPS = 0.75
            order = ("top", "right", "bottom", "left")
            color_paths: dict[str, QPainterPath] = {}
            for i, side in enumerate(order):
                if not sides_on[side]:
                    continue
                p1, p2 = corners[side]
                neighbor_p1 = order[i - 1]
                neighbor_p2 = order[(i + 1) % 4]
                dx, dy = p2.x() - p1.x(), p2.y() - p1.y()
                length = (dx * dx + dy * dy) ** 0.5
                ux, uy = (dx / length, dy / length) if length > 0 else (0.0, 0.0)
                p1e = QPointF(p1.x() - ux * EPS, p1.y() - uy * EPS) if not sides_on[neighbor_p1] else p1
                p2e = QPointF(p2.x() + ux * EPS, p2.y() + uy * EPS) if not sides_on[neighbor_p2] else p2
                wedge = QPainterPath()
                wedge.moveTo(p1e)
                wedge.lineTo(p2e)
                wedge.lineTo(center)
                wedge.closeSubpath()
                # Voir _paint_bordered_rect (meme technique/meme raison) :
                # coin ou le voisin est desactive -> unir avec le quadrant
                # COMPLET (pas juste la moitie triangulaire) pour ne pas
                # laisser un triangle de l'anneau non couvert (visible
                # surtout sur une bordure fine et un rectangle allonge).
                if not sides_on[neighbor_p1]:
                    wedge = wedge.united(_quadrant_path(p1, center))
                if not sides_on[neighbor_p2]:
                    wedge = wedge.united(_quadrant_path(p2, center))
                piece = ring.intersected(wedge)
                color = border_colors[side]
                color_paths[color] = color_paths[color].united(piece) if color in color_paths else piece
            for color, path in color_paths.items():
                p.setBrush(QColor(color))
                p.drawPath(path)
        if has_inner:
            # Bordure desactivee : le rayon doit quand meme s'appliquer au
            # remplissage, sur le rect COMPLET (pas d'inset ni de rayon
            # reduit puisqu'il n'y a pas de bordure a loger) — voir la
            # remarque de l'utilisateur, "le rayon des angles ne fonctionne
            # pas du tout quand les bordures sont desactivees" : cette
            # branche ne posait auparavant AUCUN clip, laissant le
            # remplissage carre quel que soit le rayon choisi.
            clip_radius = _radius_shrink(radius, 1) if any_on else radius
            if _radius_any(clip_radius):
                p.setClipPath(_rounded_rect_path(inner_rect, clip_radius))
            fill_layers(p, inner_rect)
        p.restore()

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing, False)
        mid_y = self.height() // 2

        # -- rail : voir _paint_bordered — bordure INDEPENDANTE par cote
        # (voir la remarque de l'utilisateur, "4 couleurs comme la bordure
        # du selecteur") puis remplissage deja-parcouru/a-parcourir.
        track_h = _SLIDER_STYLE["track_h"]
        track_rect = QRect(0, mid_y - track_h // 2, self.width(), track_h)
        # track_h > 2 : rail trop fin pour loger meme 1px de bordure sur
        # chaque cote (voir l'ancien code, meme garde-fou) — tous les cotes
        # forces a "off" dans ce cas, quel que soit le reglage par cote.
        if track_h > 2:
            track_border_on = dict(_SLIDER_STYLE["track_border_enabled"])
        else:
            track_border_on = {k: False for k in ("top", "right", "bottom", "left")}

        def _fill_track(p, inner):
            p.fillRect(inner, QColor(_SLIDER_STYLE["track_empty"]))
            fill_w = round(self._pct() * inner.width())
            if fill_w > 0:
                p.fillRect(inner.x(), inner.y(), fill_w, inner.height(), QColor(_SLIDER_STYLE["track_fill"]))

        self._paint_bordered(
            p, track_rect, _SLIDER_STYLE["track_radius"], track_border_on,
            {side: _SLIDER_STYLE[f"track_border_{side}"] for side in ("top", "right", "bottom", "left")},
            _fill_track,
            key=("track", self._value, self._min, self._max, _SLIDER_STYLE["track_empty"],
                 _SLIDER_STYLE["track_fill"]),
        )

        # -- selecteur : meme principe, une couleur de bordure par cote
        # (voir la remarque de l'utilisateur, "1 couleur pour chaque cote").
        thumb_w, thumb_h = _SLIDER_STYLE["thumb_w"], _SLIDER_STYLE["thumb_h"]
        fill_w = round(self._pct() * self.width())
        knob_x = max(0, min(self.width() - thumb_w, fill_w - thumb_w // 2))
        thumb_rect = QRect(knob_x, mid_y - thumb_h // 2, thumb_w, thumb_h)
        thumb_border_on = _SLIDER_STYLE["thumb_border_enabled"]

        def _fill_thumb(p, inner):
            p.fillRect(inner, QColor(_SLIDER_STYLE["thumb_color"]))

        self._paint_bordered(
            p, thumb_rect, _SLIDER_STYLE["thumb_radius"], thumb_border_on,
            {side: _SLIDER_STYLE[f"thumb_border_{side}"] for side in ("top", "right", "bottom", "left")},
            _fill_thumb,
            key=("thumb", _SLIDER_STYLE["thumb_color"]),
        )
        p.end()

class _SliderField(QWidget):
    """Slider + boite de lecture/saisie numerique a droite (unite comprise)."""

    valueChanged = Signal(int)

    def __init__(self, minimum: int, maximum: int, value: int, unit: str = "px",
                 slider_width: int = 170, box_width: int = 68, parent=None, scale: int = 1):
        super().__init__(parent)
        # `scale` (10, 100…) : valeur ENTIERE stockee, affichee / saisie avec des decimales (valeur / scale) —
        # ex. exposition en stops au centieme (module video).
        self._scale = max(1, int(scale))
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(10)
        self.slider = _MiniSlider(minimum, maximum, value, slider_width)
        self._radius = _input_radius()
        _register_input(self)
        self.box = box = QWidget()
        box.setObjectName("SliderValueBox")
        box.setAttribute(Qt.WA_StyledBackground, True)
        box._free_object = True        # objets libres (Ctrl+Maj / Ctrl+Maj+X) : la case entiere, pas son champ
        box.setFixedSize(box_width, 25)
        self._refresh_box_style()
        box_l = QHBoxLayout(box)
        box_l.setContentsMargins(7, 0, 7, 0)
        box_l.setSpacing(4)
        self._min, self._max = minimum, maximum
        self.value_label = QLineEdit(self._text(value))
        self.value_label.setFont(_qfont(11, 400, mono=True))
        self.value_label.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        self.value_label.setFrame(False)
        if self._scale == 1:
            self.value_label.setValidator(QIntValidator(self.value_label))
        else:
            self.value_label.setValidator(QDoubleValidator(minimum / self._scale, maximum / self._scale,
                                                           len(str(self._scale)) - 1, self.value_label))
        self.value_label.setStyleSheet(f"background: transparent; border: none; padding: 0; color: {M['value_text']};")
        self.value_label.editingFinished.connect(self._on_text_edited)
        unit_label = QLabel(unit)
        _set_text_role(unit_label, "unit")
        box_l.addWidget(self.value_label, 1)
        box_l.addWidget(unit_label)
        layout.addWidget(self.slider)
        layout.addWidget(box)
        self.slider.valueChanged.connect(self._on_change)
        self._reset_value = None
        self._marked = False

    def set_reset_value(self, value: int | None):
        """Valeur d'ORIGINE (propre à ce réglage, pas forcément 0) : la case de valeur prend un contour orange
        (couleur « modifié » du thème, `M["dirty_fg"]`) tant que la valeur en diffère, et un double-clic sur la
        poignée du curseur l'y ramène. None : rien de tout cela."""
        self._reset_value = None if value is None else int(value)
        self.slider.knob_double_clicked = None if value is None else self.reset
        self._update_mark()

    def reset(self):
        if self._reset_value is not None:
            self.setValue(self._reset_value)

    def _update_mark(self):
        marked = self._reset_value is not None and self.slider.value() != self._reset_value
        if marked != self._marked:
            self._marked = marked
            self._refresh_box_style()

    def _refresh_box_style(self):
        border = f"border: 1px solid {M['dirty_fg']};" if getattr(self, "_marked", False) else input_border_decl()
        self.box.setStyleSheet(
            f"#SliderValueBox {{ background: {input_bg()}; {border} "
            f"border-radius: {self._radius}px; }}"
        )

    def setRadius(self, radius: int):
        """Suit le slider Geometrie > Zones de saisie > Coins arrondis —
        cette boite a le meme habillage qu'une zone de saisie normale (voir
        SettingsWindow._apply_dropdown_radius, qui l'appelle sur TOUS les
        _SliderField de la fenetre, elle-meme comprise)."""
        self._radius = max(0, int(radius))
        self._refresh_box_style()

    def _text(self, value: int) -> str:
        if self._scale == 1:
            return str(value)
        return f"{value / self._scale:.{len(str(self._scale)) - 1}f}"

    def _on_change(self, value: int):
        self.value_label.setText(self._text(value))
        if self._reset_value is not None:
            self._update_mark()
        self.valueChanged.emit(value)

    def _on_text_edited(self):
        text = self.value_label.text().strip().replace(",", ".")
        try:
            raw = round(float(text) * self._scale) if self._scale != 1 else int(text)
            value = max(self._min, min(self._max, raw))
        except ValueError:
            value = self.slider.value()
        self.slider.setValue(value)
        self.value_label.setText(self._text(self.slider.value()))

    def value(self) -> int:
        return self.slider.value()

    def setValue(self, value: int):
        self.slider.setValue(value)

class _RatioSliderField(QWidget):
    """Comme _SliderField, mais pour un ratio largeur/hauteur affiche
    "1/<valeur decimale>" (voir Colonnes > Lignes > Apercu > Ratio, remarque
    de l'utilisateur : "avant l'invite place le texte '1/' ... dans
    l'invite on entre la valeur de largeur (par exemple 2.35) ce qui fait un
    ratio de 1 pour 2.35"). Stockage INCHANGE (pourcentage entier, 100 = 1.0,
    voir item_image_ratio) — seul l'AFFICHAGE devient decimal (value_pct/100,
    2 decimales), la granularite du slider (pas de 1%) suffit deja pour 2
    decimales."""

    valueChanged = Signal(int)

    def __init__(self, minimum: int, maximum: int, value_pct: int,
                 slider_width: int = 170, box_width: int = 68, parent=None):
        super().__init__(parent)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(6)
        prefix = QLabel("1/")
        _set_text_role(prefix, "unit_large")
        layout.addWidget(prefix)
        self.slider = _MiniSlider(minimum, maximum, value_pct, slider_width)
        self._radius = _input_radius()
        _register_input(self)
        self._min, self._max = minimum, maximum
        self.box = box = QWidget()
        box.setObjectName("SliderValueBox")
        box.setAttribute(Qt.WA_StyledBackground, True)
        box.setFixedSize(box_width, 25)
        self._refresh_box_style()
        box_l = QHBoxLayout(box)
        box_l.setContentsMargins(7, 0, 7, 0)
        box_l.setSpacing(4)
        self.value_label = QLineEdit(self._format(value_pct))
        self.value_label.setFont(_qfont(11, 400, mono=True))
        self.value_label.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        self.value_label.setFrame(False)
        self.value_label.setValidator(QDoubleValidator(0.01, 99.99, 2, self.value_label))
        self.value_label.setStyleSheet(f"background: transparent; border: none; padding: 0; color: {M['value_text']};")
        self.value_label.editingFinished.connect(self._on_text_edited)
        box_l.addWidget(self.value_label, 1)
        layout.addWidget(self.slider)
        layout.addWidget(box)
        self.slider.valueChanged.connect(self._on_change)

    @staticmethod
    def _format(value_pct: int) -> str:
        return f"{value_pct / 100:.2f}"

    def _refresh_box_style(self):
        self.box.setStyleSheet(
            f"#SliderValueBox {{ background: {input_bg()}; {input_border_decl()} "
            f"border-radius: {self._radius}px; }}"
        )

    def setRadius(self, radius: int):
        self._radius = max(0, int(radius))
        self._refresh_box_style()

    def _on_change(self, value_pct: int):
        self.value_label.setText(self._format(value_pct))
        self.valueChanged.emit(value_pct)

    def _on_text_edited(self):
        text = self.value_label.text().strip().replace(",", ".")
        try:
            value_pct = max(self._min, min(self._max, round(float(text) * 100)))
        except ValueError:
            value_pct = self.slider.value()
        self.slider.setValue(value_pct)
        self.value_label.setText(self._format(self.slider.value()))

    def value(self) -> int:
        return self.slider.value()

    def setValue(self, value_pct: int):
        self.slider.setValue(value_pct)
        self.value_label.setText(self._format(value_pct))

class _SteppedSliderField(QWidget):
    """Slider a positions FIXES (voir _MiniSlider, deja entier par nature —
    aucune valeur intermediaire possible) affichant un LIBELLE a cote plutot
    qu'un nombre dans une boite de saisie — utilise pour Lissage (voir la
    remarque de l'utilisateur : "slider 3 points (crante)" plutot qu'un
    menu deroulant, puisque le lissage n'a de toute facon que ces quelques
    niveaux reels cote Qt/Windows, voir app_style.font()). PAS de boite
    "zone de saisie" (fond/bordure) autour du libelle — voir la remarque de
    l'utilisateur, capture a l'appui : ce texte n'est ni cliquable ni
    editable, l'habiller comme un champ suggerait le contraire ; un simple
    texte informatif, comme la colonne Apercu du meme tableau."""

    changed = Signal(int)

    def __init__(self, labels: list[str], value: int, slider_width: int = 170, box_width: int = 90, parent=None):
        super().__init__(parent)
        self._labels = labels
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        # 18 (pas 10 comme _SliderField) : slider tres court (20px, voir la
        # remarque de l'utilisateur) donc slider+libelle se retrouvaient
        # colles l'un a l'autre avec le meme espacement qu'un _SliderField
        # normal (dont le slider fait 5x plus large) — voir la remarque de
        # l'utilisateur, capture a l'appui ("zone rognee, infos entassees").
        layout.setSpacing(18)
        self.slider = _MiniSlider(0, len(labels) - 1, value, slider_width)
        self.value_label = QLabel(labels[value])
        _set_text_role(self.value_label, "value_muted")
        self.value_label.setFixedWidth(box_width)
        layout.addWidget(self.slider)
        layout.addWidget(self.value_label)
        self.slider.valueChanged.connect(self._on_change)

    def _on_change(self, value: int):
        self.value_label.setText(self._labels[value])
        self.changed.emit(value)

    def value(self) -> int:
        return self.slider.value()

    def setValue(self, value: int):
        value = max(0, min(len(self._labels) - 1, value))
        self.slider.setValue(value)
        self.value_label.setText(self._labels[value])

_ITEM_FONT_SMOOTHING_STEPS = ("none", "previous", "current")

class _OverrideSmoothingField(QWidget):
    """Slider Lissage a 3 crans (MEME widget/mecanique que Polices
    principales > Lissage, voir _SteppedSliderField/_SMOOTHING_STEPS) —
    pour Colonnes > Texte > Lissage. Le toggle "Forcer" a ete SUPPRIME (voir
    la remarque de l'utilisateur, "il y a deux toggle pour le lissage,
    supprime le premier qui ne sert a rien, et ne garde que celui a 3
    positions") : le lissage choisi ici s'applique desormais TOUJOURS
    (isChecked() renvoie donc toujours True, conserve seulement pour ne pas
    casser les appelants qui persistent encore une cle "..._enabled").
    Libelles des 3 crans : "0"/"1"/"2" (pas les noms descriptifs Fin/Moyen/
    Brut) — voir la remarque de l'utilisateur. Titre "niveau de lissage"
    centre AU-DESSUS du slider (voir la remarque de l'utilisateur, "place
    un nouveau texte juste au dessus du toggle bien centre")."""

    changed = Signal()

    def __init__(self, enabled: bool, smoothing: str, parent=None, show_title: bool = True):
        super().__init__(parent)
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(2)
        if show_title:   # sans titre quand une entete de colonne le porte deja
            title = QLabel("niveau de lissage")
            _set_text_role(title, "mini_label")
            title.setAlignment(Qt.AlignHCenter)
            outer.addWidget(title)
        step = _ITEM_FONT_SMOOTHING_STEPS.index(smoothing) if smoothing in _ITEM_FONT_SMOOTHING_STEPS else 2
        self.slider = _SteppedSliderField(["0", "1", "2"], step, slider_width=20, box_width=24)
        outer.addWidget(self.slider, 0, Qt.AlignHCenter)
        self.slider.changed.connect(lambda _s: self.changed.emit())

    def isChecked(self) -> bool:
        return True

    def smoothingValue(self) -> str:
        return _ITEM_FONT_SMOOTHING_STEPS[self.slider.value()]

    def setValue(self, enabled: bool, smoothing: str):
        step = _ITEM_FONT_SMOOTHING_STEPS.index(smoothing) if smoothing in _ITEM_FONT_SMOOTHING_STEPS else 2
        self.slider.setValue(step)

class _RowBorderField(QWidget):
    """Toggle + couleur + epaisseur du filet ENTRE les lignes d'une colonne,
    TOUS LES TROIS DANS LA MEME ligne (meme principe que
    _OverrideSmoothingField juste au-dessus, toggle + champ) — voir la
    remarque de l'utilisateur, "rassemble bordure couleur et epaisseur
    dans une seule ligne" (au lieu de 3 lignes separees). Toggle SANS
    libelle "actif"/"sans" (voir la remarque de l'utilisateur, "pas besoin
    de mettre actif") ; couleur et epaisseur se grisent (voir _set_dimmed)
    quand il est desactive (voir la meme remarque, "grise les autres
    options quand le toggle est desactive"). _AppOrCustomColorField (PAS
    _ColorField), meme raison que item_color_field : choix entre couleurs
    soft de l'appli et couleur personnalisee."""

    changed = Signal()

    def __init__(self, enabled: bool, color: str, thickness: int, colors: dict,
                 thickness_range: tuple[int, int] = (0, 8), title: str = "Couleur de bordure", parent=None,
                 color_factory=None):
        super().__init__(parent)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(14)
        self.toggle = _Toggle(bool(enabled), style_override="toggle1", show_label=False)
        layout.addWidget(self.toggle)
        # `color_factory(color, colors, title)` : autre champ couleur (meme interface), ex. le champ compact
        # app | pastille | sys de la fenetre v2.
        self.color_field = (color_factory(color, colors, title) if color_factory is not None
                            else _AppOrCustomColorField(color, colors, swatch_size=24, title=title))
        layout.addWidget(self.color_field)
        self.thickness_field = _SliderField(
            thickness_range[0], thickness_range[1], int(thickness), slider_width=140, box_width=54)
        layout.addWidget(self.thickness_field)
        layout.addStretch(1)
        self.toggle.toggled.connect(self._on_toggle)
        self.color_field.changed.connect(lambda _v: self.changed.emit())
        self.thickness_field.valueChanged.connect(lambda _v: self.changed.emit())
        self._refresh_enabled()

    def _on_toggle(self, _checked: bool):
        self._refresh_enabled()
        self.changed.emit()

    def _refresh_enabled(self):
        on = self.toggle.isChecked()
        _set_dimmed(self.color_field, not on)
        _set_dimmed(self.thickness_field, not on)

    def enabledValue(self) -> bool:
        return self.toggle.isChecked()

    def colorValue(self) -> str:
        return self.color_field.value()

    def thicknessValue(self) -> int:
        return self.thickness_field.value()

    def setValue(self, enabled: bool, color: str, thickness: int):
        self.toggle.setChecked(bool(enabled))
        self.color_field.setValue(color)
        self.thickness_field.setValue(int(thickness))
        self._refresh_enabled()

    def refresh_colors(self, colors: dict):
        self.color_field.refresh_colors(colors)

class _SelectField(QPushButton):
    """Bouton "select" (valeur + chevron), ouvre un QMenu. Cette boite a
    exactement le meme habillage (fond/bordure) qu'une zone de saisie
    normale (QLineEdit) \u2014 voir setRadius : elle suit donc en direct le
    reglage Geometrie > Zones de saisie > Coins arrondis, au meme titre que
    les vrais champs de texte (voir SettingsWindow._apply_field_radius)."""

    changed = Signal(str)

    def __init__(self, options: list[str], current: str, width: int = 200, parent=None):
        super().__init__(parent)
        self._options = options
        self._value = current if current in options else options[0]
        self._radius = _input_radius()
        _register_input(self)
        self.setFixedSize(width, 25)
        if input_height():
            self.setFixedHeight(input_height())           # Reglages > Zone de saisie > Hauteur
        self.setCursor(Qt.ArrowCursor)
        self.setFocusPolicy(Qt.NoFocus)
        self.setFont(_qfont(11, 400))
        self._refresh_style()
        self.clicked.connect(self._open_menu)
        self._sync_text()

    def _refresh_style(self):
        self.setStyleSheet(
            f"QPushButton {{ background: {input_bg()}; {input_border_decl()} "
            f"border-radius: {self._radius}px; "
            f"color: {M['value_fg']}; text-align: left; padding: 0 8px; }}"
            f"QPushButton:hover {{ border-color: {M['field_border_hover']}; }}"
        )

    def setRadius(self, radius: int):
        self._radius = max(0, int(radius))
        self._refresh_style()

    def _sync_text(self):
        self.setText(self._value + "  \u25be")

    def _open_menu(self):
        menu = QMenu(self)
        menu.setFont(_qfont(11, 400))
        menu.setStyleSheet(
            f"QMenu {{ background: {M['toolbar_bg']}; border: 1px solid {M['field_border']}; "
            f"border-radius: {self._radius}px; padding: 4px 0; }}"
            f"QMenu::item {{ padding: 5px 16px; color: {M['value_fg']}; }}"
            f"QMenu::item:selected, QMenu::item:checked {{ background: {M['accent']}; color: {M['accent_fg']}; }}"
        )
        for opt in self._options:
            action = menu.addAction(opt)
            # L'option courante reste visible meme quand le curseur ne la
            # survole pas : la coche + le fond accentue indiquent la valeur
            # active dans la liste des couleurs d'application.
            action.setCheckable(True)
            action.setChecked(opt == self._value)
            action.triggered.connect(lambda _checked=False, o=opt: self._select(o))
        menu.exec(self.mapToGlobal(QPoint(0, self.height())))

    def _select(self, opt: str):
        if opt != self._value:
            self._value = opt
            self._sync_text()
            self.changed.emit(opt)

    def value(self) -> str:
        return self._value

    def setValue(self, value: str):
        if value in self._options and value != self._value:
            self._value = value
            self._sync_text()

    def setOptions(self, options: list[str]):
        """Remplace la liste d'options EN PLACE (voir _open_menu, qui lit
        `self._options` a chaque ouverture — pas besoin de reconstruire le
        widget) : utilise par SettingsWindow._refresh_default_preset_
        options pour que "Preset par defaut" reste a jour des qu'un preset
        est cree/supprime/renomme, MEME fenetre encore ouverte — voir la
        remarque de l'utilisateur sur la refonte des presets."""
        self._options = list(options)
        if self._value not in self._options and self._options:
            self._value = self._options[0]
            self._sync_text()

class _FontSelectField(_SelectField):
    """Variante de _SelectField pour choisir une police : vraie liste
    deroulante (scroll natif, molette comprise) ou chaque nom de police est
    rendu DANS cette police — voir la meme classe dans l'ancienne fenetre,
    logique inchangee."""

    def __init__(self, options: list[str], current: str, width: int = 200,
                 auto_label: str | None = None, parent=None):
        self._auto_label = auto_label
        super().__init__(options, current, width, parent)

    def _display_label(self, opt: str) -> str:
        if opt == "Systeme" and self._auto_label:
            return self._auto_label
        return opt

    def _sync_text(self):
        self.setText(self._display_label(self._value) + "  \u25be")

    def _open_menu(self):
        popup = QWidget(self, Qt.Popup)
        popup.setObjectName("FontPopup")
        popup.setAttribute(Qt.WA_StyledBackground, True)
        popup.setStyleSheet(
            f"#FontPopup {{ background: {M['toolbar_bg']}; border: 1px solid {M['field_border']}; "
            f"border-radius: {self._radius}px; }}"
        )
        layout = QVBoxLayout(popup)
        layout.setContentsMargins(1, 1, 1, 1)
        layout.setSpacing(0)

        listw = QListWidget(popup)
        listw.setFrameShape(QFrame.NoFrame)
        listw.setUniformItemSizes(True)
        listw.setStyleSheet(
            "QListWidget { background: transparent; border: none; outline: none; }"
            f"QListWidget::item {{ padding: 6px 12px; color: {M['value_fg']}; }}"
            f"QListWidget::item:selected {{ background: {M['accent']}; color: {M['accent_fg']}; }}"
            f"QListWidget::item:hover:!selected {{ background: {M['close_hover_bg']}; }}"
        )
        current_item = None
        for opt in self._options:
            if opt == self._auto_label and opt != self._value:
                continue
            item = QListWidgetItem(self._display_label(opt))
            item.setData(Qt.UserRole, opt)
            item.setFont(_qfont(12, 400) if opt == "Systeme" else QFont(opt, 12))
            listw.addItem(item)
            if opt == self._value:
                current_item = item
        listw.itemClicked.connect(lambda item: self._pick_from_popup(item.data(Qt.UserRole), popup))

        layout.addWidget(listw)
        popup.setFixedWidth(max(self.width(), 240))
        popup.setFixedHeight(320)
        popup.move(self.mapToGlobal(QPoint(0, self.height())))
        popup.show()
        if current_item is not None:
            listw.setCurrentItem(current_item)
            listw.scrollToItem(current_item)
        listw.setFocus()

    def _pick_from_popup(self, opt: str, popup: QWidget):
        popup.close()
        self._select(opt)

class _DualFontSelectField(QWidget):
    """Colonnes > Texte > Police : DEUX listes deroulantes cote a cote au
    lieu d'une seule liste combinee — "polices du soft" (les 5 roles DEJA
    regles dans Polices principales, voir ITEM_FONT_ROLE_LABELS) et
    "polices systeme" (toutes les polices installees, + "Systeme" = auto,
    voir _FontSelectField) — chacune precedee d'un toggle EXCLUSIF (une
    seule active a la fois, l'autre liste grisee, voir _set_dimmed) — voir
    la remarque de l'utilisateur, "je veux avoir le choix entre les
    polices du soft et les polices systeme ... avec devant chacune un
    toggle pour le choix. La liste non selectionnee sera grisee".

    Valeur (voir value()/setValue()) INCHANGEE par rapport a l'ancienne
    liste unique (retro-compatible avec les presets existants) : le
    libelle "police du soft" choisi tel quel, OU "Systeme"/un nom de
    police reel pour le cote systeme — c'est SEULEMENT la PRESENTATION qui
    change ici, pas le format stocke."""

    changed = Signal()

    def __init__(self, value: str, width: int = 150, parent=None):
        super().__init__(parent)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(6)

        # MEME systeme que le gabarit "couleur" compact (voir
        # _CompactAppOrCustomColorField et la remarque de l'utilisateur,
        # "c'est possible de faire la mm chose pour le choix des polices ?")
        # : un toggle "app"/"sys" de PART ET D'AUTRE, libelle CENTRE
        # au-dessus de chacun, et UN SEUL menu deroulant central (au lieu de
        # 2 cote a cote, l'un grise) dont la liste d'options BASCULE selon
        # le mode actif (voir _refresh_options) — memes valeurs stockees
        # qu'avant (retro-compatible).
        self._soft_options = list(ITEM_FONT_ROLE_LABELS.values())
        self._system_options = ["Systeme"] + installed_font_families()
        is_soft = value in self._soft_options

        # "app" a GAUCHE de son toggle, tres rapproches.
        app_box = QWidget()
        app_box.setStyleSheet("background: transparent;")
        app_box_l = QHBoxLayout(app_box)
        app_box_l.setContentsMargins(0, 0, 0, 0)
        app_box_l.setSpacing(3)
        app_label = QLabel("app")
        _set_text_role(app_label, "mini_label")
        app_label.setContentsMargins(0, 0, 0, 3)   # remonte le texte : aligne avec le centre du toggle
        app_box_l.addWidget(app_label)
        self.soft_toggle = _Toggle(is_soft, show_label=False)
        app_box_l.addWidget(self.soft_toggle)
        layout.addWidget(app_box)

        self.field = _FontSelectField(
            self._soft_options if is_soft else self._system_options,
            value if is_soft else (value or "Systeme"), width=width, auto_label="Systeme")
        layout.addWidget(self.field)

        # "sys" a DROITE de son toggle, tres rapproches.
        sys_box = QWidget()
        sys_box.setStyleSheet("background: transparent;")
        sys_box_l = QHBoxLayout(sys_box)
        sys_box_l.setContentsMargins(0, 0, 0, 0)
        sys_box_l.setSpacing(3)
        self.system_toggle = _Toggle(not is_soft, show_label=False)
        sys_box_l.addWidget(self.system_toggle)
        sys_label = QLabel("sys")
        _set_text_role(sys_label, "mini_label")
        sys_label.setContentsMargins(0, 0, 0, 3)   # remonte le texte : aligne avec le centre du toggle
        sys_box_l.addWidget(sys_label)
        layout.addWidget(sys_box)

        # Derniere valeur connue de CHAQUE cote (voir _refresh_options) :
        # rebasculer vers "app" doit retrouver le dernier role choisi, pas
        # toujours retomber sur le 1er de la liste.
        self._last_soft = value if is_soft else self._soft_options[0]
        self._last_system = value if not is_soft else "Systeme"

        self.soft_toggle.toggled.connect(self._on_soft_toggled)
        self.system_toggle.toggled.connect(self._on_system_toggled)
        self.field.changed.connect(self._on_field_changed)

    def _on_field_changed(self, value: str):
        if self.soft_toggle.isChecked():
            self._last_soft = value
        else:
            self._last_system = value
        self.changed.emit()

    def _refresh_options(self):
        if self.soft_toggle.isChecked():
            self.field.setOptions(self._soft_options)
            self.field.setValue(self._last_soft)
        else:
            self.field.setOptions(self._system_options)
            self.field.setValue(self._last_system)

    def _on_soft_toggled(self, checked: bool):
        if checked:
            self.system_toggle.blockSignals(True)
            self.system_toggle.setChecked(False)
            self.system_toggle.blockSignals(False)
        elif not self.system_toggle.isChecked():
            # Au moins l'un des 2 doit rester actif — sans ca, decocher le
            # seul toggle actif ne selectionnerait plus AUCUNE police.
            self.system_toggle.blockSignals(True)
            self.system_toggle.setChecked(True)
            self.system_toggle.blockSignals(False)
        self._refresh_options()
        self.changed.emit()

    def _on_system_toggled(self, checked: bool):
        if checked:
            self.soft_toggle.blockSignals(True)
            self.soft_toggle.setChecked(False)
            self.soft_toggle.blockSignals(False)
        elif not self.soft_toggle.isChecked():
            self.soft_toggle.blockSignals(True)
            self.soft_toggle.setChecked(True)
            self.soft_toggle.blockSignals(False)
        self._refresh_options()
        self.changed.emit()

    def value(self) -> str:
        return self.field.value()

    def setValue(self, value: str):
        is_soft = value in self._soft_options
        for toggle, checked in ((self.soft_toggle, is_soft), (self.system_toggle, not is_soft)):
            toggle.blockSignals(True)
            toggle.setChecked(checked)
            toggle.blockSignals(False)
        if is_soft:
            self._last_soft = value
        else:
            self._last_system = value or "Systeme"
        self._refresh_options()

    def setRadius(self, radius: int):
        self.field.setRadius(radius)

# Style visuel de TOUS les _Toggle de cette fenetre (voir Toggles > Style,
# SettingsWindow._section_toggles) — "toggle1" (cadre RECTANGLE, coche
# calee en haut a droite a distance egale du bord en horizontale qu'en
# verticale) ou "toggle2" (cadre CARRE, coche PARFAITEMENT centree) — voir
# la remarque de l'utilisateur, capture annotee a l'appui (mockup corrige
# des 2 styles, "je me suis trompe, j'ai modifie les types"). Chaque style
# a son propre jeu de reglages COMPLET (_TOGGLE1_STYLE/_TOGGLE2_STYLE,
# toujours tenus a jour tous les deux — seul _TOGGLE_STYLE choisit lequel
# est REELLEMENT dessine) ; _TOGGLE_STYLE change une fois, s'applique a
# tous les toggles deja construits (voir SettingsWindow._on_toggle_style_
# changed, qui rappelle .apply_style() sur chacun), meme principe que
# _SLIDER_STYLE.
_TOGGLE_STYLE = "toggle1"

_ALL_SIDES_ON = {"top": True, "right": True, "bottom": True, "left": True}

_TOGGLE_SHAPE_DEFAULTS = {
    "outer_w": 29, "outer_h": 14,
    # dict {cote: bool}, pas un bool unique (voir _coerce_side_enabled/la
    # remarque de l'utilisateur, "un toggle par cote") — reecrase de toute
    # facon par _sync_toggle_shape_style avant le 1er rendu, valeur de
    # depart seulement.
    "outer_border_enabled": dict(_ALL_SIDES_ON), "outer_border_thickness": 1,
    "outer_border_radius": {"top_left": 0, "top_right": 0, "bottom_right": 0, "bottom_left": 0},
    "outer_border_top": "#2e343a", "outer_border_right": "#2e343a",
    "outer_border_bottom": "#2e343a", "outer_border_left": "#2e343a",
    "outer_bg": "#141618",
    # Fond a l'etat ON (voir _paint_toggle_shape, qui interpole entre
    # outer_bg -> outer_bg_on selon `progress` pendant l'animation) — voir
    # la remarque de l'utilisateur, "dans les toggles, j'aimerais que la
    # couleur de fond differe entre l'etat on et l'etat off".
    "outer_bg_on": "#3f6f9f",
    "coche_w": 11, "coche_h": 11,
    # Marge (px, "x" sur le schema de l'utilisateur) entre le bord du cadre
    # et la coche — reglable (voir Toggles > Coche > Distance du bord),
    # PAR STYLE (chacun le sien). Sert de marge HAUTE et BASSE (voir
    # _sync_toggle_shape_style, qui EN DEDUIT coche_h — la hauteur de la
    # coche est LIEE a celle du cadre, voir la remarque de l'utilisateur)
    # et, pour "toggle1", de marge DROITE aussi (voir _paint_toggle_shape).
    "coche_margin": 4,
    "coche_border_enabled": dict(_ALL_SIDES_ON), "coche_border_thickness": 1,
    "coche_border_radius": {"top_left": 0, "top_right": 0, "bottom_right": 0, "bottom_left": 0},
    "coche_border_top": "#2e343a", "coche_border_right": "#2e343a",
    "coche_border_bottom": "#2e343a", "coche_border_left": "#2e343a",
    "coche_color": "#3f6f9f",
    # Habillage de la coche : rien, un texte ou une icone dessines DANS la coche.
    "skin": "none", "text": "",
    "text_font": {"family": "", "bold": True, "italic": False, "size": 10, "smoothing": "current",
                  "color": "#ffffff"},
    "icon": "", "icon_color": "#ffffff",
    # Type : "qt" (cadre + coche peints) ou "icons" (images ON/OFF + sequence optionnelle entre les
    # deux, dans data/toggle_icons/) ; mouvement de la coche : "slide" (glissiere) ou "fade" (centree,
    # fondu) ; duree de l'animation ON <-> OFF.
    "kind": "qt", "motion": "slide", "icon_on": "", "icon_off": "", "icon_frames": [], "anim_ms": 140,
}

_TOGGLE1_STYLE = dict(_TOGGLE_SHAPE_DEFAULTS)

_TOGGLE2_STYLE = dict(_TOGGLE_SHAPE_DEFAULTS)

_TOGGLE2_STYLE.update({"outer_w": 22, "outer_h": 22, "motion": "fade"})

# Registre des styles : toggle1, toggle2 et ceux que l'utilisateur ajoute (toggle3...).
_TOGGLE_STYLES: dict[str, dict] = {"toggle1": _TOGGLE1_STYLE, "toggle2": _TOGGLE2_STYLE}
_TOGGLE_STYLE_NAMES: dict[str, str] = {"toggle1": "Toggle 1", "toggle2": "Toggle 2"}

# Reglages de chaque style deja vu, meme supprime du registre (une annulation le fait revenir).
_TOGGLE_STYLE_DICTS: dict[str, dict] = dict(_TOGGLE_STYLES)

def _toggle_style_dict(key: str) -> dict:
    """Reglages d'un style (crees a la demande, a partir des valeurs par defaut). N'inscrit PAS le
    style au registre : seul _sync_toggle_style le fait, depuis la liste des reglages."""
    style = _TOGGLE_STYLES.get(key) or _TOGGLE_STYLE_DICTS.get(key)
    if style is None:
        import copy
        style = _TOGGLE_STYLE_DICTS[key] = copy.deepcopy(_TOGGLE_SHAPE_DEFAULTS)
    return style

def _resolve_toggle_key(key: str | None) -> str:
    """Style reellement dessine pour `key` : lui s'il existe encore, sinon le style par defaut de la
    fenetre, sinon le premier (un style supprime ne laisse jamais un toggle sans apparence)."""
    if key in _TOGGLE_STYLES:
        return key
    if _TOGGLE_STYLE in _TOGGLE_STYLES:
        return _TOGGLE_STYLE
    return next(iter(_TOGGLE_STYLES), "toggle1")


def _sync_toggle_shape_style(target: dict, settings: dict, prefix: str) -> None:
    """Recopie les reglages `{prefix}_*` de `settings` dans `target`
    (_TOGGLE1_STYLE ou _TOGGLE2_STYLE) — voir _sync_toggle_style, qui
    l'appelle pour chacun des 2 styles a chaque changement."""
    target["outer_w"] = max(4, int(settings.get(f"{prefix}_outer_width", target["outer_w"])))
    target["outer_h"] = max(4, int(settings.get(f"{prefix}_outer_height", target["outer_h"])))
    target["outer_border_enabled"] = _coerce_side_enabled(settings.get(f"{prefix}_outer_border_enabled", True))
    target["outer_border_thickness"] = max(0, int(settings.get(f"{prefix}_outer_border_thickness", 1)))
    target["outer_border_radius"] = _coerce_corner_radius(settings.get(f"{prefix}_outer_border_radius", 0))
    # _resolve_color_value : outer_border/coche_border (voir _AppOrCustom
    # ColorField, bordures Toggles/Sliders) peuvent contenir un hex direct
    # OU une reference "@<slot>" a une pastille semantique — cette derniere
    # doit etre resolue en hex REEL avant de finir ici, seule forme que
    # _paint_bordered_rect (QColor(...)) sait interpreter.
    colors = settings.get("colors") or {}
    outer_border = settings.get(f"{prefix}_outer_border") or {}
    for side in ("top", "right", "bottom", "left"):
        target[f"outer_border_{side}"] = _resolve_color_value(
            outer_border.get(side, target[f"outer_border_{side}"]), colors)
    target["outer_bg"] = _resolve_color_value(settings.get(f"{prefix}_outer_bg", target["outer_bg"]), colors)
    target["outer_bg_on"] = _resolve_color_value(settings.get(f"{prefix}_outer_bg_on", target["outer_bg_on"]), colors)
    target["coche_w"] = max(2, int(settings.get(f"{prefix}_coche_width", target["coche_w"])))
    target["coche_margin"] = max(0, int(settings.get(f"{prefix}_coche_margin", target["coche_margin"])))
    # coche_h LIEE a outer_h (voir la remarque de l'utilisateur), pas un
    # reglage independant — marge haute ET basse egales a x (coche_margin),
    # ce qui centre aussi verticalement la coche (equivalent, voir
    # _paint_toggle_shape).
    target["coche_h"] = max(2, target["outer_h"] - 2 * target["coche_margin"])
    target["coche_border_enabled"] = _coerce_side_enabled(settings.get(f"{prefix}_coche_border_enabled", True))
    target["coche_border_thickness"] = max(0, int(settings.get(f"{prefix}_coche_border_thickness", 1)))
    target["coche_border_radius"] = _coerce_corner_radius(settings.get(f"{prefix}_coche_border_radius", 0))
    coche_border = settings.get(f"{prefix}_coche_border") or {}
    for side in ("top", "right", "bottom", "left"):
        target[f"coche_border_{side}"] = _resolve_color_value(
            coche_border.get(side, target[f"coche_border_{side}"]), colors)
    target["coche_color"] = _resolve_color_value(settings.get(f"{prefix}_coche_color", target["coche_color"]), colors)
    target["skin"] = settings.get(f"{prefix}_coche_skin", "none")
    target["text"] = str(settings.get(f"{prefix}_coche_text", ""))
    smoothing_on = bool(settings.get(f"{prefix}_coche_text_font_smoothing_enabled", False))
    target["text_font"] = {
        "family": settings.get(f"{prefix}_coche_text_font_family", "") or "",
        "bold": bool(settings.get(f"{prefix}_coche_text_font_bold", True)),
        "italic": bool(settings.get(f"{prefix}_coche_text_font_italic", False)),
        "size": max(4, int(settings.get(f"{prefix}_coche_text_font_size", 10))),
        "smoothing": settings.get(f"{prefix}_coche_text_font_smoothing", "current") if smoothing_on else "current",
        "color": _resolve_color_value(settings.get(f"{prefix}_coche_text_font_color", "#ffffff"), colors),
    }
    target["icon"] = str(settings.get(f"{prefix}_coche_icon", "") or "")
    target["icon_color"] = _resolve_color_value(settings.get(f"{prefix}_coche_icon_color", "#ffffff"), colors)
    target["kind"] = "icons" if settings.get(f"{prefix}_kind") == "icons" else "qt"
    motion = settings.get(f"{prefix}_motion", "fade" if prefix == "toggle2" else "slide")
    target["motion"] = "fade" if motion == "fade" else "slide"
    target["icon_on"] = str(settings.get(f"{prefix}_icon_on", "") or "")
    target["icon_off"] = str(settings.get(f"{prefix}_icon_off", "") or "")
    target["icon_frames"] = [str(f) for f in (settings.get(f"{prefix}_icon_frames") or []) if f]
    target["anim_ms"] = max(0, int(settings.get(f"{prefix}_anim_ms", 140)))

def _sync_toggle_style(settings: dict) -> None:
    """Registre des styles = la liste des reglages (toggle_style_list), dans son ordre : un style
    supprime en sort, un style renomme change de nom ; puis les reglages de chacun."""
    global _TOGGLE_STYLE
    from settings_store import toggle_style_list
    styles = toggle_style_list(settings)
    kept = {entry["key"]: _toggle_style_dict(entry["key"]) for entry in styles}
    _TOGGLE_STYLES.clear()
    _TOGGLE_STYLES.update(kept)
    _TOGGLE_STYLE_NAMES.clear()
    _TOGGLE_STYLE_NAMES.update({entry["key"]: entry["name"] for entry in styles})
    style = settings.get("toggle_style", "toggle1")
    _TOGGLE_STYLE = style if style in _TOGGLE_STYLES else styles[0]["key"]
    for key, target in list(_TOGGLE_STYLES.items()):
        _sync_toggle_shape_style(target, settings, key)

def _radius_dict(radius) -> dict:
    """Normalise `radius` (int uniforme OU dict {"top_left": int, ...}) en
    dict complet sur les 4 coins — voir _rounded_rect_path/_paint_bordered_
    rect et la remarque de l'utilisateur, "si deux colonnes sont cote a
    cote ... le rayon contre l'autre colonne doit etre a zero" (rayon
    INDEPENDANT par coin, voir _ColumnPreview.paintEvent)."""
    if isinstance(radius, dict):
        return {k: max(0, int(radius.get(k, 0))) for k in _CORNERS}
    r = max(0, int(radius))
    return {k: r for k in _CORNERS}

def _radius_shrink(radius, amount: int):
    """`radius` (int ou dict) retranche de `amount` sur chaque coin, jamais
    sous 0 — repasse a un int simple si les 4 coins retombent egaux (evite
    de trainer un dict la ou un simple radius suffit)."""
    shrunk = {k: max(0, v - amount) for k, v in _radius_dict(radius).items()}
    values = set(shrunk.values())
    return values.pop() if len(values) == 1 else shrunk

def _radius_any(radius) -> bool:
    return any(v > 0 for v in _radius_dict(radius).values())

def _rounded_rect_path(rect: QRect, radius) -> QPainterPath:
    """Chemin rectangle arrondi — `radius` : int (rayon UNIFORME, retro-
    compatible) OU dict {"top_left": int, "top_right": int, "bottom_right":
    int, "bottom_left": int} pour un rayon INDEPENDANT par coin (voir
    _radius_dict/la remarque de l'utilisateur ci-dessus)."""
    if isinstance(radius, dict):
        d = _radius_dict(radius)
        if len(set(d.values())) == 1:
            radius = next(iter(d.values()))
        else:
            r = QRectF(rect)
            tl = min(d["top_left"], r.width() / 2, r.height() / 2)
            tr = min(d["top_right"], r.width() / 2, r.height() / 2)
            br = min(d["bottom_right"], r.width() / 2, r.height() / 2)
            bl = min(d["bottom_left"], r.width() / 2, r.height() / 2)
            path = QPainterPath()
            path.moveTo(r.left() + tl, r.top())
            path.lineTo(r.right() - tr, r.top())
            if tr > 0:
                path.arcTo(r.right() - 2 * tr, r.top(), 2 * tr, 2 * tr, 90, -90)
            path.lineTo(r.right(), r.bottom() - br)
            if br > 0:
                path.arcTo(r.right() - 2 * br, r.bottom() - 2 * br, 2 * br, 2 * br, 0, -90)
            path.lineTo(r.left() + bl, r.bottom())
            if bl > 0:
                path.arcTo(r.left(), r.bottom() - 2 * bl, 2 * bl, 2 * bl, -90, -90)
            path.lineTo(r.left(), r.top() + tl)
            if tl > 0:
                path.arcTo(r.left(), r.top(), 2 * tl, 2 * tl, 180, -90)
            path.closeSubpath()
            return path
    path = QPainterPath()
    if radius > 0:
        path.addRoundedRect(QRectF(rect), radius, radius)
    else:
        path.addRect(QRectF(rect))
    return path

def _quadrant_path(corner: QPointF, center: QPointF) -> QPainterPath:
    """Rectangle AXE-ALIGNE plein entre `corner` (un coin du rect) et
    `center` (son centre) — le quadrant COMPLET de ce coin, pas juste sa
    moitie triangulaire (voir _paint_bordered_rect/_MiniSlider._paint_
    bordered, la diagonale-vers-le-centre d'un wedge ne couvre QUE sa
    moitie du carre de coin ; quand le cote voisin est desactive, cette
    moitie manquante de l'anneau ne revient a personne)."""
    path = QPainterPath()
    path.addRect(QRectF(corner, center).normalized())
    return path

# Lissage des petites formes (toggles, curseurs, coches, selections de lignes...) : la forme ENTIERE
# (bordures + fond) est peinte sur-echantillonnee (8x, 4x au-dela de _SMOOTH_SS8_AREA), REDUITE par
# moyenne de zone (QImage.scaled + SmoothTransformation : chaque pixel = moyenne de ses ss x ss
# sous-pixels, un vrai filtre) a la taille PHYSIQUE, puis collee pixel pour pixel. Ne JAMAIS laisser
# drawPixmap reduire un pixmap a devicePixelRatio 4 ou 8 : son filtrage bilineaire ne lit que 2 x 2
# sous-pixels sur 8 x 8, le sur-echantillonnage est perdu et le bord crenele (ancien _ring_pixmap).
# Un clip (setClipPath) n'est pas lisse par Qt : dans l'image sur-echantillonnee, il le devient.
_SMOOTH_CACHE: dict = {}
_SMOOTH_CACHE_MAX = 512
_SMOOTH_MAX_AREA = 24000        # pixels physiques ; au-dela (grands cadres) : trace vectoriel direct
_SMOOTH_SS8_AREA = 4096


def _smooth_paintable(p: QPainter, rect: QRect) -> bool:
    t = p.deviceTransform()
    if t.isRotating() or t.m11() <= 0 or t.m22() <= 0:
        return False
    return rect.width() * t.m11() * rect.height() * t.m22() <= _SMOOTH_MAX_AREA


def _paint_smooth(p: QPainter, rect: QRect, key, draw) -> None:
    """Peint `draw(painter, QRect(0, 0, w, h))` a la place de `rect`, sur-echantillonne puis reduit
    (voir plus haut). `key` (hachable, decrit TOUT ce que dessine `draw`) met le resultat en cache :
    la position a l'ecran n'y entre que par son decalage sous-pixel."""
    import math
    t = p.deviceTransform()
    sx, sy = t.m11(), t.m22()
    origin = t.map(QPointF(rect.topLeft()))
    ox, oy = math.floor(origin.x()), math.floor(origin.y())
    ss = 8 if rect.width() * sx * rect.height() * sy <= _SMOOTH_SS8_AREA else 4
    fx, fy = round((origin.x() - ox) * ss) / ss, round((origin.y() - oy) * ss) / ss
    w_dev = math.ceil(rect.width() * sx + fx) + 2         # 1 px de marge de chaque cote
    h_dev = math.ceil(rect.height() * sy + fy) + 2
    full_key = (key, rect.width(), rect.height(), round(sx, 4), round(sy, 4), fx, fy)
    pix = _SMOOTH_CACHE.get(full_key)
    if pix is None:
        from PySide6.QtGui import QImage
        image = QImage(w_dev * ss, h_dev * ss, QImage.Format_ARGB32_Premultiplied)
        image.fill(Qt.transparent)
        sp = QPainter(image)
        sp.setRenderHint(QPainter.Antialiasing, True)
        sp.scale(ss, ss)
        sp.translate(1 + fx, 1 + fy)
        sp.scale(sx, sy)
        draw(sp, QRect(0, 0, rect.width(), rect.height()))
        sp.end()
        pix = QPixmap.fromImage(image.scaled(w_dev, h_dev, Qt.IgnoreAspectRatio, Qt.SmoothTransformation))
        pix.setDevicePixelRatio(sx)
        if len(_SMOOTH_CACHE) >= _SMOOTH_CACHE_MAX:
            _SMOOTH_CACHE.clear()
        _SMOOTH_CACHE[full_key] = pix
    inverse, _ok = t.inverted()
    p.drawPixmap(inverse.map(QPointF(ox - 1, oy - 1)), pix)     # 1:1 sur les pixels physiques


def _hidpi_pixmap(image, width: int, height: int, dpr: float, keep_aspect: bool = True) -> QPixmap:
    """`image` (QImage, generalement plus grande) reduite par moyenne de zone a width x height
    LOGIQUES, a la densite `dpr` de l'ecran : affichee 1:1, sans reduction bilineaire au dessin."""
    mode = Qt.KeepAspectRatio if keep_aspect else Qt.IgnoreAspectRatio
    small = image.scaled(max(1, round(width * dpr)), max(1, round(height * dpr)), mode, Qt.SmoothTransformation)
    pix = QPixmap.fromImage(small)
    pix.setDevicePixelRatio(dpr)
    return pix


def _app_dpr() -> float:
    app = QGuiApplication.instance()
    return float(app.devicePixelRatio()) if app is not None else 1.0

def _paint_bordered_rect(p: QPainter, rect: QRect, radius: int, border_on, thickness: int,
                          border_colors: dict, fill_color: str | None):
    """Peint un rectangle avec bordure MITREE par cote (voir _MiniSlider.
    _paint_bordered, meme technique — diagonales depuis le centre vers
    chaque coin, continue quel que soit le rayon) generalisee ici a une
    EPAISSEUR de bordure variable (les sliders restent a 1px fixe, les
    toggles l'exposent en reglage, voir Toggles > Cadre/Coche > Epaisseur
    de bordure) + remplissage (`fill_color`, ou aucun si None — la coche a
    l'etat OFF, "creuse").

    `border_on` : bool (tous les cotes pareil, retro-compatible) OU dict
    {"top": bool, ...} — un cote DESACTIVE (voir _SideColorsField, la
    remarque de l'utilisateur "au lieu d'avoir un seul toggle pour activer
    les bordures, je veux un toggle par cote") ne consomme plus d'epaisseur
    de CE cote : le remplissage s'etend alors jusqu'a ce bord, tout en
    restant en retrait des autres cotes toujours actifs (inset ASYMETRIQUE,
    pas juste un on/off global comme avant).

    `radius` : int (rayon uniforme, retro-compatible) OU dict {"top_left":
    int, ...} — un rayon INDEPENDANT par coin (voir _rounded_rect_path/la
    remarque de l'utilisateur, "si deux colonnes sont cote a cote ... le
    rayon contre l'autre colonne doit etre a zero", voir _ColumnPreview).

    Petites formes (toggles, curseurs, selections de lignes...) : peintes SUR-ECHANTILLONNEES puis
    reduites par moyenne de zone (_paint_smooth) — bordure et fond lisses, arrondis compris. Les
    grandes (cadres de colonnes...) : trace vectoriel direct (_paint_bordered_vector)."""
    if rect.width() <= 0 or rect.height() <= 0:
        return
    if _smooth_paintable(p, rect):
        key = ("bordered", _hashable(radius), _hashable(border_on), int(thickness),
               _hashable(border_colors), _hashable(fill_color))
        _paint_smooth(p, rect, key, lambda sp, local: _paint_bordered_vector(
            sp, local, radius, border_on, thickness, border_colors, fill_color))
        return
    _paint_bordered_vector(p, rect, radius, border_on, thickness, border_colors, fill_color)


def _hashable(value):
    """Cle de cache d'un reglage (dict/list -> tuples, QColor -> nom)."""
    if isinstance(value, dict):
        return tuple(sorted((k, _hashable(v)) for k, v in value.items()))
    if isinstance(value, (list, tuple)):
        return tuple(_hashable(v) for v in value)
    if isinstance(value, QColor):
        return value.name(QColor.NameFormat.HexArgb)
    return value


def _paint_bordered_vector(p: QPainter, rect: QRect, radius, border_on, thickness: int,
                           border_colors: dict, fill_color):
    """Trace vectoriel de _paint_bordered_rect : direct pour les grandes formes, dans l'image
    sur-echantillonnee de _paint_smooth pour les petites."""
    if rect.width() <= 0 or rect.height() <= 0:
        return
    if isinstance(border_on, dict):
        sides_on = {k: bool(border_on.get(k, False)) for k in ("top", "right", "bottom", "left")}
    else:
        v = bool(border_on)
        sides_on = {k: v for k in ("top", "right", "bottom", "left")}
    thickness = max(0, int(thickness))
    t = {k: (thickness if sides_on[k] else 0) for k in sides_on}
    any_on = thickness > 0 and any(sides_on.values())
    inner_rect = QRect(
        rect.left() + t["left"], rect.top() + t["top"],
        rect.width() - t["left"] - t["right"], rect.height() - t["top"] - t["bottom"],
    )
    has_inner = inner_rect.width() > 0 and inner_rect.height() > 0
    p.save()
    p.setRenderHint(QPainter.Antialiasing, _radius_any(radius))
    p.setPen(Qt.NoPen)
    # Fond D'ABORD, sous la bordure, en CHEMIN lisse : un setClipPath + fillRect (ancienne methode)
    # n'est pas antialiase par Qt, d'ou des arrondis crenelés (disque plein d'un toggle...).
    if fill_color is not None:
        target_rect = inner_rect if any_on else rect
        if target_rect.width() > 0 and target_rect.height() > 0:
            fill_radius = _radius_shrink(radius, thickness) if any_on else radius
            if _radius_any(fill_radius):
                p.setBrush(QColor(fill_color))
                p.drawPath(_rounded_rect_path(target_rect, fill_radius))
            else:
                p.fillRect(target_rect, QColor(fill_color))
    if any_on and all(sides_on.values()) and len({border_colors[k] for k in sides_on}) == 1:
        # Bordure uniforme (cas le plus courant) : l'anneau exterieur moins interieur, en UN chemin.
        inner_path = _rounded_rect_path(inner_rect, _radius_shrink(radius, thickness)) if has_inner else None
        outer_path = _rounded_rect_path(rect, radius)
        p.setBrush(QColor(border_colors["top"]))
        p.drawPath(outer_path.subtracted(inner_path) if inner_path is not None else outer_path)
    elif any_on:
        outer_path = _rounded_rect_path(rect, radius)
        inner_radius = _radius_shrink(radius, thickness)
        ring = outer_path.subtracted(_rounded_rect_path(inner_rect, inner_radius)) if has_inner else outer_path
        rf = QRectF(rect)
        center = rf.center()
        corners = {
            "top": (QPointF(rf.left(), rf.top()), QPointF(rf.right(), rf.top())),
            "right": (QPointF(rf.right(), rf.top()), QPointF(rf.right(), rf.bottom())),
            "bottom": (QPointF(rf.right(), rf.bottom()), QPointF(rf.left(), rf.bottom())),
            "left": (QPointF(rf.left(), rf.bottom()), QPointF(rf.left(), rf.top())),
        }
        p.setPen(Qt.NoPen)
        # Chaque coin (p1/p2) ALLONGE de EPS le long de son propre cote,
        # au-dela du coin REEL du rectangle — sans ca, 2 coins ENTRE UN
        # COTE ACTIF ET UN COTE DESACTIVE (voir _SideColorsField, un
        # interrupteur PAR cote) se rejoignaient exactement sur la
        # diagonale-vers-le-centre du cote actif, et l'antialiasing y
        # laissait un mini-vide (le "coin" pile a la frontiere entre 2
        # coins ne revient VRAIMENT a aucun des 2 triangles) — voir la
        # remarque de l'utilisateur, capture annotee a l'appui, "la ligne
        # ne forme pas" (le filet restait ouvert a chaque coin plutot que
        # de former un rectangle ferme).
        #
        # Cette rallonge ne doit s'appliquer QUE du cote ou le VOISIN de ce
        # coin est desactive (le vrai trou) — PAS quand les 2 cotes d'un
        # coin sont actifs : la, le triangle du voisin recouvre alors ce
        # meme demi-pixel en double, et sur un rayon arrondi (zone deja
        # anti-aliasee) ce double-recouvrement se voit comme un lisere plus
        # sature / une sorte dedgrade au lieu d'un bord net (voir la
        # remarque de l'utilisateur, "il y a encore comme une sorte de
        # degrade, je ne veux pas ca"). Donc rallonge SEULEMENT au coin ou
        # le voisin est off ; coin exact (sans rallonge) si le voisin est on
        # — le miter diagonal s'y ferme deja parfaitement, sans besoin de
        # fudge.
        # Meme 2 cotes ACTIFS de la MEME couleur (le cas le plus courant —
        # bordure uniforme) laissaient un lisere fantome pile sur la
        # diagonale du miter : 2 formes anti-aliasees peintes separement,
        # bord a bord, ne se recouvrent JAMAIS parfaitement pixel pour pixel
        # (chaque drawPath calcule sa propre att'nuation en bord de forme) —
        # visible surtout sur un coin arrondi (voir la remarque de
        # l'utilisateur, "il y a encore comme une sorte de degrade"). Fix :
        # au lieu de dessiner chaque cote separement, on ACCUMULE les
        # morceaux par couleur (united()) et on ne peint qu'UNE fois par
        # couleur — un seul drawPath = une seule frontiere anti-aliasee,
        # plus de couture interne (que les 2 cotes soient adjacents ou non,
        # united() sur des morceaux disjoints ne change rien au rendu).
        EPS = 0.75
        order = ("top", "right", "bottom", "left")
        color_paths: dict[str, QPainterPath] = {}
        for i, side in enumerate(order):
            if not sides_on[side]:
                continue
            p1, p2 = corners[side]
            neighbor_p1 = order[i - 1]
            neighbor_p2 = order[(i + 1) % 4]
            dx, dy = p2.x() - p1.x(), p2.y() - p1.y()
            length = (dx * dx + dy * dy) ** 0.5
            ux, uy = (dx / length, dy / length) if length > 0 else (0.0, 0.0)
            p1e = QPointF(p1.x() - ux * EPS, p1.y() - uy * EPS) if not sides_on[neighbor_p1] else p1
            p2e = QPointF(p2.x() + ux * EPS, p2.y() + uy * EPS) if not sides_on[neighbor_p2] else p2
            wedge = QPainterPath()
            wedge.moveTo(p1e)
            wedge.lineTo(p2e)
            wedge.lineTo(center)
            wedge.closeSubpath()
            # Coin ou le voisin est desactive : la diagonale-vers-le-centre
            # ne couvre que LA MOITIE du carre de ce coin (l'autre moitie
            # appartenait au triangle du voisin, qui n'existe plus) — plus
            # le rectangle est fin/allonge, plus cette diagonale rase le
            # bord et laisse un triangle de l'anneau non couvert PRES du
            # coin (personne ne le reclame) — voir la remarque de
            # l'utilisateur, capture a l'appui, "la bordure de la selection
            # ne continue pas de maniere constante jusqu'au bord de la
            # colonne". Fix : unir le wedge avec le rectangle ENTIER coin<->
            # centre (le quadrant complet, pas juste sa moitie triangulaire)
            # — recouvre alors aussi la moitie qui revenait au voisin,
            # sans effet de bord (intersecte avec `ring` de toute facon).
            if not sides_on[neighbor_p1]:
                wedge = wedge.united(_quadrant_path(p1, center))
            if not sides_on[neighbor_p2]:
                wedge = wedge.united(_quadrant_path(p2, center))
            piece = ring.intersected(wedge)
            color = border_colors[side]
            color_paths[color] = color_paths[color].united(piece) if color in color_paths else piece
        for color, path in color_paths.items():
            p.setBrush(QColor(color))
            p.drawPath(path)
    p.restore()

def _blend_hex(off_hex: str, on_hex: str, t: float) -> str:
    """Interpole lineairement 2 couleurs hex ("#rrggbb") selon `t`
    (0.0 = `off_hex`, 1.0 = `on_hex`) — utilise par _paint_toggle_shape
    pour animer le FOND du cadre en meme temps que la coche (voir
    _Toggle._progress), plutot qu'un changement brusque a mi-course."""
    t = max(0.0, min(1.0, t))
    off_c, on_c = QColor(off_hex), QColor(on_hex)
    r = round(off_c.red() + (on_c.red() - off_c.red()) * t)
    g = round(off_c.green() + (on_c.green() - off_c.green()) * t)
    b = round(off_c.blue() + (on_c.blue() - off_c.blue()) * t)
    return QColor(r, g, b).name()

def _paint_toggle_shape(p: QPainter, x: int, y: int, style_key: str, style: dict, checked: bool,
                         progress: float | None = None):
    """Dessine le cadre EXTERIEUR + la coche INTERIEURE d'un toggle a la
    position (x, y), selon `style` (voir _TOGGLE1_STYLE/_TOGGLE2_STYLE) —
    factorise entre _Toggle.paintEvent (style COURANT de la fenetre, voir
    _TOGGLE_STYLE) et _ToggleShapePreview (apercu de CHAQUE style, voir
    Toggles > Style, toujours a l'etat FIXE ON/OFF — jamais anime).

    `progress` (0.0 = OFF, 1.0 = ON) anime la TRANSITION entre les 2 etats
    (voir _Toggle, qui glisse cette valeur de 0 a 1 ou l'inverse au clic —
    voir la remarque de l'utilisateur, "une animation quand le toggle
    passe de l'etat on a l'etat off et vice versa") ; None (les 2 apercus
    statiques ci-dessus) retombe sur l'etat fixe de `checked` (0.0 ou 1.0).

    Les 2 styles se comportent tres differemment entre ON et OFF (voir la
    remarque de l'utilisateur, corrigeant un malentendu precedent) :
    - "toggle1" : GLISSIERE classique — la coche garde TOUJOURS le meme
      style (bordure/couleur/taille inchangees), seule sa POSITION change,
      caleé a droite (ON) ou a gauche (OFF), avec la meme marge des 2
      cotes (voir Toggles > Coche > Distance du bord) — animee ici par un
      simple LERP de sa position x entre les 2 bornes.
    - "toggle2" : la coche reste centree mais DISPARAIT completement a
      l'etat OFF (rien de dessine, pas meme un contour) — ne s'affiche
      qu'a l'etat ON — animee ici par un FONDU (opacite = progress)."""
    if progress is None:
        progress = 1.0 if checked else 0.0
    if style.get("kind") == "icons":
        _paint_toggle_icons(p, QRect(x, y, style["outer_w"], style["outer_h"]), style, progress)
        return
    outer_rect = QRect(x, y, style["outer_w"], style["outer_h"])
    outer_colors = {side: style[f"outer_border_{side}"] for side in ("top", "right", "bottom", "left")}
    outer_bg = _blend_hex(style["outer_bg"], style["outer_bg_on"], progress)
    _paint_bordered_rect(p, outer_rect, style["outer_border_radius"], style["outer_border_enabled"],
                          style["outer_border_thickness"], outer_colors, outer_bg)
    margin = style["coche_margin"]
    # coche_h est deduite de outer_h en retirant 2x la marge (voir
    # _sync_toggle_shape_style), donc marge haute = marge basse = margin,
    # ce qui centre deja la coche verticalement — vrai pour les 2 styles,
    # quel que soit l'etat.
    cy = y + margin
    fade = style.get("motion", "slide") == "fade"
    if fade:
        if progress <= 0.0:
            return   # coche invisible a l'etat OFF (rien a peindre)
        cx = x + (style["outer_w"] - style["coche_w"]) // 2
    else:
        off_x = margin
        on_x = max(0, style["outer_w"] - margin - style["coche_w"])
        cx = x + round(off_x + (on_x - off_x) * progress)
    coche_rect = QRect(cx, cy, style["coche_w"], style["coche_h"])
    coche_colors = {side: style[f"coche_border_{side}"] for side in ("top", "right", "bottom", "left")}
    if fade and progress < 1.0:
        p.save()
        p.setOpacity(p.opacity() * progress)
        _paint_bordered_rect(p, coche_rect, style["coche_border_radius"], style["coche_border_enabled"],
                              style["coche_border_thickness"], coche_colors, style["coche_color"])
        _paint_coche_skin(p, coche_rect, style)
        p.restore()
    else:
        _paint_bordered_rect(p, coche_rect, style["coche_border_radius"], style["coche_border_enabled"],
                              style["coche_border_thickness"], coche_colors, style["coche_color"])
        _paint_coche_skin(p, coche_rect, style)

_TOGGLE_IMAGE_CACHE: dict = {}

def _toggle_image_pixmap(name: str, width: int, height: int, dpr: float | None = None) -> QPixmap | None:
    """Image importee pour un toggle « icones » (data/toggle_icons/), a ses couleurs d'origine,
    ajustee dans width x height (proportions gardees), nette en haute densite. Cache par
    (nom, taille, date du fichier)."""
    from settings_store import _TOGGLE_ICONS_DIR
    path = _TOGGLE_ICONS_DIR / name
    try:
        mtime = path.stat().st_mtime
    except OSError:
        return None
    dpr = dpr or _app_dpr()
    key = (name, width, height, mtime, dpr)
    if key in _TOGGLE_IMAGE_CACHE:
        return _TOGGLE_IMAGE_CACHE[key]
    if len(_TOGGLE_IMAGE_CACHE) > 512:
        _TOGGLE_IMAGE_CACHE.clear()
    from PySide6.QtGui import QImage
    pix = None
    if path.suffix.lower() == ".svg":
        from PySide6.QtSvg import QSvgRenderer
        renderer = QSvgRenderer(str(path))
        if renderer.isValid():
            ss = 4                                  # rendu 4x, puis reduit par moyenne de zone
            size = renderer.defaultSize()
            size.scale(round(width * dpr) * ss, round(height * dpr) * ss, Qt.KeepAspectRatio)
            image = QImage(max(1, size.width()), max(1, size.height()), QImage.Format_ARGB32_Premultiplied)
            image.fill(Qt.transparent)
            painter = QPainter(image)
            painter.setRenderHint(QPainter.Antialiasing, True)
            renderer.render(painter)
            painter.end()
            pix = _hidpi_pixmap(image, width, height, dpr)
    else:
        source = QImage(str(path))
        if not source.isNull():
            pix = _hidpi_pixmap(source.convertToFormat(QImage.Format_ARGB32_Premultiplied), width, height, dpr)
    _TOGGLE_IMAGE_CACHE[key] = pix
    return pix

def _toggle_icon_frame(style: dict, progress: float) -> str:
    """Image a montrer pour `progress` (0 = OFF, 1 = ON) : OFF, puis la sequence importee dans
    l'ordre, puis ON — jouee a l'envers de ON vers OFF (meme progress, parcouru dans l'autre sens)."""
    frames = [style.get("icon_off", "")] + list(style.get("icon_frames") or []) + [style.get("icon_on", "")]
    index = round(max(0.0, min(1.0, progress)) * (len(frames) - 1))
    return frames[index]

def _paint_toggle_icons(p: QPainter, rect: QRect, style: dict, progress: float) -> None:
    """Toggle « icones » : l'image de l'etat (ou de l'etape de l'animation), centree dans le cadre
    (Cadre > Largeur / Hauteur). Sans sequence, fondu entre OFF et ON."""
    def draw(name: str, opacity: float = 1.0):
        pix = _toggle_image_pixmap(name, rect.width(), rect.height(), p.device().devicePixelRatioF()) if name else None
        if pix is None or opacity <= 0.0:
            return
        size = pix.deviceIndependentSize()
        p.save()
        p.setOpacity(p.opacity() * opacity)
        p.setRenderHint(QPainter.SmoothPixmapTransform, True)
        p.drawPixmap(QPointF(rect.x() + (rect.width() - size.width()) / 2,
                             rect.y() + (rect.height() - size.height()) / 2), pix)
        p.restore()

    if style.get("icon_frames") or progress in (0.0, 1.0):
        draw(_toggle_icon_frame(style, progress))
        return
    draw(style.get("icon_off", ""), 1.0 - progress)
    draw(style.get("icon_on", ""), progress)

_TOGGLE_ICON_CACHE: dict = {}

def _toggle_icon_pixmap(name: str, size: int, color: str, dpr: float | None = None) -> QPixmap | None:
    """Icone de icons/ pour l'habillage d'une coche : un SVG est recolore (trace uni, rendu comme
    un masque), un PNG garde ses couleurs. Cache par (nom, taille, couleur)."""
    dpr = dpr or _app_dpr()
    key = (name, size, color, dpr)
    if key in _TOGGLE_ICON_CACHE:
        return _TOGGLE_ICON_CACHE[key]
    from settings_store import _ICONS_DIR
    path = _ICONS_DIR / name
    pix = None
    if path.is_file() and size > 0:
        from PySide6.QtGui import QImage
        if path.suffix.lower() == ".svg":
            from PySide6.QtSvg import QSvgRenderer
            side = round(size * dpr) * 4            # rendu 4x, puis reduit par moyenne de zone
            image = QImage(side, side, QImage.Format_ARGB32_Premultiplied)
            image.fill(Qt.transparent)
            painter = QPainter(image)
            painter.setRenderHint(QPainter.Antialiasing, True)
            QSvgRenderer(str(path)).render(painter)
            painter.setCompositionMode(QPainter.CompositionMode_SourceIn)
            painter.fillRect(image.rect(), QColor(color))
            painter.end()
            pix = _hidpi_pixmap(image, size, size, dpr)
        else:
            source = QImage(str(path))
            if not source.isNull():
                pix = _hidpi_pixmap(source.convertToFormat(QImage.Format_ARGB32_Premultiplied), size, size, dpr)
    _TOGGLE_ICON_CACHE[key] = pix
    return pix

def _paint_coche_skin(p: QPainter, rect: QRect, style: dict) -> None:
    """Texte ou icone dessine au centre de la coche (voir Toggles > Coche > Habillage)."""
    skin = style.get("skin", "none")
    if skin == "text" and style.get("text"):
        spec = style["text_font"]
        font = QFont(spec["family"] or "Segoe UI")
        font.setPixelSize(spec["size"])
        font.setBold(spec["bold"])
        font.setItalic(spec["italic"])
        if spec["smoothing"] == "none":
            font.setStyleStrategy(QFont.NoAntialias)
        p.save()
        p.setFont(font)
        p.setPen(QColor(spec["color"]))
        p.drawText(rect, Qt.AlignCenter, style["text"])
        p.restore()
    elif skin == "icon" and style.get("icon"):
        size = max(1, min(rect.width(), rect.height()) - 2)
        pix = _toggle_icon_pixmap(style["icon"], size, style["icon_color"], p.device().devicePixelRatioF())
        if pix is not None:
            logical = pix.deviceIndependentSize()
            p.drawPixmap(round(rect.center().x() - logical.width() / 2 + 0.5),
                         round(rect.center().y() - logical.height() / 2 + 0.5), pix)

def _precise_clock(enable: bool) -> None:
    """Windows : horloge a 1 ms pendant une animation (sinon les minuteurs tombent tous les ~15,6 ms et
    une image sur deux est ratee). Appels apparies ; sans effet ailleurs."""
    import sys
    if sys.platform != "win32":
        return
    try:
        import ctypes
        (ctypes.windll.winmm.timeBeginPeriod if enable else ctypes.windll.winmm.timeEndPeriod)(1)
    except (AttributeError, OSError):
        pass


def toggle_animation_left_ms() -> int:
    """Temps (ms) restant a la bascule de toggle en cours la plus longue (0 = aucune) : un travail lourd
    declenche par la bascule (apercu en direct...) attend ce delai, sinon il fige l'animation."""
    import time
    return max(0, int(_Toggle._anim_until - time.monotonic() * 1000.0))


class _Toggle(QWidget):
    """Interrupteur peint a la main selon le style COURANT (voir
    _TOGGLE_STYLE/_paint_toggle_shape — cadre + coche, entierement
    reglables, voir Toggles > Style) + libelle d'etat a droite — utilise
    pour les cadres actif/sans de la page Geometrie, et pour tout autre
    reglage on/off de cette fenetre.

    La transition ON<->OFF est ANIMEE (voir _progress/_anim ci-dessous,
    et _paint_toggle_shape qui sait desormais peindre un etat
    INTERMEDIAIRE) — voir la remarque de l'utilisateur, "une animation
    quand le toggle passe de l'etat on a l'etat off et vice versa"."""

    _ANIM_MS = 140
    _anim_until = 0.0        # fin (ms, horloge monotone) de la bascule en cours la plus longue

    toggled = Signal(bool)

    def __init__(self, checked: bool = False, on_label="actif", off_label="sans", parent=None,
                 style_override: str | None = None, show_label: bool = True):
        super().__init__(parent)
        self._checked = checked
        # _progress (0.0 = OFF, 1.0 = ON) est ce que peint REELLEMENT
        # paintEvent — _checked est l'etat final CIBLE (deja a jour des le
        # clic, voir setChecked : le libelle texte, lui, bascule tout de
        # suite plutot que de tenter un fondu croise entre 2 mots) ; SEUL
        # _progress glisse progressivement de l'un a l'autre pendant
        # l'animation.
        self._progress = 1.0 if checked else 0.0
        self._on_label, self._off_label = on_label, off_label
        # `style_override` ("toggle1"/"toggle2"/None) : ignore le style
        # COURANT de la fenetre (_TOGGLE_STYLE) et fige celui-ci a la place
        # — voir la remarque de l'utilisateur, "je veux overider le style
        # du toggle ici pour le toggle 2" (les interrupteurs par cote des
        # reglages de bordure, voir _SideColorsField, doivent toujours
        # avoir l'apparence "toggle2" quel que soit le style choisi dans
        # Toggles > Style). `show_label` False : masque "actif"/"sans" a
        # cote du cadre — voir la remarque de l'utilisateur, "ne mets pas
        # l'annotation actif a cote du toggle, uniquement le toggle en lui
        # meme" (memes interrupteurs par cote).
        self._style_override = style_override
        # Style d'origine (celui du code) : « Par defaut » du menu contextuel y revient. Le style
        # choisi par l'utilisateur pour CE toggle (clic droit) remplace _style_override.
        self._base_override = style_override
        # Identifiant stable pose par la fenetre qui le contient (enregistrement du style choisi).
        self.style_id: str | None = None
        self._show_label = show_label
        self.setCursor(Qt.PointingHandCursor)
        self._anim = QVariantAnimation(self)
        self._anim.setDuration(self._ANIM_MS)
        self._anim.setEasingCurve(self._CURVE)
        self._anim.valueChanged.connect(self._on_anim_value)
        self._anim.stateChanged.connect(self._on_anim_state)
        self._precise = False                 # horloge fine tenue pendant la bascule
        self.apply_style()

    # Courbe de la glissiere : depart vif mais sans saut (OutCubic faisait ~40 % de la course des la
    # premiere image), pas d'image plus longue qu'une autre.
    _CURVE = QEasingCurve.OutSine

    def _on_anim_state(self, new, _old):
        running = new == QVariantAnimation.Running
        if running != self._precise:
            self._precise = running
            _precise_clock(running)

    def _on_anim_value(self, value):
        self._progress = float(value)
        self.update()

    def _style_key(self) -> str:
        return _resolve_toggle_key(self._style_override or _TOGGLE_STYLE)

    def _style(self) -> dict:
        # Style PROPRE a ce toggle (« Override settings », settings_element_style) sinon son style nomme.
        return getattr(self, "_look_style", None) or _toggle_style_dict(self._style_key())

    def chosenStyle(self) -> str | None:
        """Style choisi a la main pour ce toggle (None : celui d'origine)."""
        return self._style_override if self._style_override != self._base_override else None

    def setStyleKey(self, key: str | None):
        """Style de CE toggle (None : celui d'origine, voir __init__)."""
        self._style_override = key or self._base_override
        self.apply_style()

    def contextMenuEvent(self, event):
        """Clic droit sur un toggle : choix de son style parmi tous les styles crees."""
        if getattr(self, "_ctx_menu_handled", False):
            # Deja propose par le menu qui le contient (edition d'un menu contextuel, settings_menu).
            self._ctx_menu_handled = False
            event.accept()
            return
        menu = Menu(self)
        add_toggle_style_menu(self, menu)
        add_context_extras(self, menu)
        menu.exec(event.globalPos())
        event.accept()

    def apply_style(self):
        """Rejoue le style COURANT (voir _TOGGLE_STYLE), OU celui fige par
        `style_override` (voir __init__) — a rappeler sur toute instance
        deja construite quand ce reglage change (voir SettingsWindow.
        _on_toggle_style_changed) : necessaire, pas un simple repaint,
        puisque la taille meme du cadre (outer_w/outer_h) peut avoir
        change."""
        style = self._style()
        self._outer_w = style["outer_w"]
        self._anim.setDuration(int(style.get("anim_ms", self._ANIM_MS)))
        # Une sequence d'images se joue a vitesse constante ; la glissiere garde sa courbe.
        self._anim.setEasingCurve(QEasingCurve.Linear if style.get("kind") == "icons" else self._CURVE)
        if self._show_label:
            h = max(25, style["outer_h"] + 8)
            w = max(30, style["outer_w"]) + 9 + 40
        else:
            # Sans libelle : le widget = ce qui est DESSINE (cadre, ou coche qui en deborde avec une
            # marge negative), +1 px de chaque cote pour l'antialiasing. Plus de taille minimale
            # (36 x 25) : elle laissait une grande marge invisible autour des petits toggles, meme
            # avec un padding de cellule a 0.
            w, h = self._drawn_size(style)
            w, h = w + 2, h + 2
        self.setFixedSize(w, h)
        self.update()

    @staticmethod
    def _drawn_size(style: dict) -> tuple[int, int]:
        """Largeur / hauteur de ce que peint _paint_toggle_shape : le cadre, agrandi de ce que la
        coche en deborde (marge negative : elle deborde des deux cotes, symetriquement)."""
        w, h = style["outer_w"], style["outer_h"]
        if style.get("kind") != "icons":
            over = max(0, -int(style.get("coche_margin", 0)))
            w = max(w, style.get("coche_w", 0), w + 2 * over)
            h = max(h, style.get("coche_h", 0))
        return w, h

    def isChecked(self) -> bool:
        return self._checked

    def setChecked(self, checked: bool):
        if checked == self._checked:
            return
        self._checked = checked
        # Pas de garde sur self.isVisible() : la plupart des toggles vivent
        # dans une section REPLIEE par defaut (voir _Section), donc
        # invisibles la plupart du temps sans etre pour autant "avant le
        # premier affichage" — anime dans tous les cas (l'animation, ~140ms,
        # est de toute facon terminee bien avant qu'on deplie la section
        # pour la voir)."""
        self._anim.stop()
        self._anim.setStartValue(self._progress)
        self._anim.setEndValue(1.0 if checked else 0.0)
        self._anim.start()
        import time
        _Toggle._anim_until = max(_Toggle._anim_until, time.monotonic() * 1000.0 + self._anim.duration())
        self.toggled.emit(checked)

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            self.setChecked(not self._checked)

    def paintEvent(self, event):
        p = QPainter(self)
        style = self._style()
        y = (self.height() - style["outer_h"]) // 2
        # x=0 quand un libelle suit a droite (voir apply_style, largeur du
        # widget = cadre + marge fixe reservee au texte) ; SANS libelle, le
        # cadre est plus etroit que le widget (voir apply_style, marge de
        # 6px) et doit alors etre CENTRE horizontalement dans ce widget —
        # sinon il apparait decale par rapport a la pastille de couleur/au
        # texte G/H/B/D juste en dessous (voir _SideColorsField, meme
        # colonne alignee au centre) — voir la remarque de l'utilisateur,
        # "le toggle n'est pas centre avec le carre de couleur".
        x = 0 if self._show_label else max(0, (self.width() - style["outer_w"]) // 2)
        _paint_toggle_shape(p, x, y, self._style_key(), style, self._checked, progress=self._progress)
        if self._show_label:
            p.setFont(_qfont(10, 400, mono=True))
            # Couleur du libelle interpolee sur _progress (pas juste
            # _checked) : suit le meme fondu que la coche plutot que de
            # sauter net des le debut du glisser.
            on_color, off_color = QColor(M["toggle_on_fg"]), QColor(M["toggle_off_fg"])
            t = self._progress
            label_color = QColor(
                round(off_color.red() + (on_color.red() - off_color.red()) * t),
                round(off_color.green() + (on_color.green() - off_color.green()) * t),
                round(off_color.blue() + (on_color.blue() - off_color.blue()) * t),
            )
            p.setPen(label_color)
            label_x = self._outer_w + 9
            p.drawText(label_x, 0, 40, self.height(), Qt.AlignVCenter | Qt.AlignLeft,
                       self._on_label if self._checked else self._off_label)
        p.end()

# Appeles quand l'utilisateur choisit le style d'un toggle (clic droit > Style du toggle) :
# (toggle, cle de style ou None pour « Par defaut »). La fenetre qui le contient l'enregistre.
TOGGLE_STYLE_LISTENERS: list = []

_DEFAULT_STYLE_LABEL = "Par défaut"


def add_toggle_style_menu(toggle: "_Toggle", menu: QMenu) -> None:
    """Ligne « Style du toggle » + menu deroulant de tous les styles crees (« Par defaut » = celui
    d'origine du toggle)."""
    names = [_TOGGLE_STYLE_NAMES.get(k, k) for k in _TOGGLE_STYLES]
    chosen = toggle.chosenStyle()
    current = _TOGGLE_STYLE_NAMES.get(chosen, _DEFAULT_STYLE_LABEL) if chosen in _TOGGLE_STYLES else _DEFAULT_STYLE_LABEL
    select = _SelectField([_DEFAULT_STYLE_LABEL] + names, current, width=160)
    by_name = {_TOGGLE_STYLE_NAMES.get(k, k): k for k in _TOGGLE_STYLES}

    def chosen_key(label: str):
        key = None if label == _DEFAULT_STYLE_LABEL else by_name.get(label)
        toggle.setStyleKey(key)
        for listener in list(TOGGLE_STYLE_LISTENERS):
            listener(toggle, key)
        menu.close()

    select.changed.connect(chosen_key)
    menu_row(menu, "Style du toggle", select)


class _ToggleShapePreview(QWidget):
    """Apercu ON+OFF cote a cote pour un style ("toggle1"/"toggle2") — LIT
    en direct _TOGGLE1_STYLE/_TOGGLE2_STYLE (voir refresh, rappele par
    SettingsWindow._on_toggle_style_changed a chaque reglage touche dans
    les tableaux Cadre/Coche ci-dessous) : pas un simple apercu fige, il
    suit les 2 tableaux en temps reel. Pur apercu, non interactif — le
    choix du style se fait en cliquant la carte englobante (voir
    _ToggleStyleCard)."""

    _GAP = 16
    _PAD = 6

    def __init__(self, style_key: str, parent=None):
        super().__init__(parent)
        self._style_key = style_key
        self._slot_w = 40
        self.refresh()

    def _style(self) -> dict:
        return _toggle_style_dict(self._style_key)

    def sizeHint(self):
        # setFixedSize() pose deja minimumSize()/maximumSize(), mais PAS
        # sizeHint() (QWidget la laisse invalide par defaut, voir sa doc) —
        # un ancetre cache puis reaffiche (voir _Section.set_collapsed)
        # peut alors re-figer un layout base sur cette taille invalide
        # avant que minimumSize() ne soit reconsideree, laissant cet apercu
        # ecrase a une hauteur minuscule (voir la remarque de l'utilisateur,
        # capture a l'appui : carte de style quasi vide).
        return self.size()

    def refresh(self):
        style = self._style()
        self._slot_w = max(style["outer_w"], style["coche_w"]) + self._PAD * 2
        h = max(style["outer_h"], 18) + self._PAD * 2 + 16
        self.setFixedSize(self._slot_w * 2 + self._GAP, h)
        self.updateGeometry()
        self.update()

    def paintEvent(self, event):
        p = QPainter(self)
        style = self._style()
        y = self._PAD
        x0 = (self._slot_w - style["outer_w"]) // 2
        x1 = self._slot_w + self._GAP + (self._slot_w - style["outer_w"]) // 2
        _paint_toggle_shape(p, x0, y, self._style_key, style, True)
        _paint_toggle_shape(p, x1, y, self._style_key, style, False)
        p.setFont(_qfont(8, 600, mono=True, tracking=0.4))
        p.setPen(QColor(M["unit"]))
        label_y = y + style["outer_h"] + 4
        p.drawText(0, label_y, self._slot_w, 14, Qt.AlignHCenter, "ON")
        p.drawText(self._slot_w + self._GAP, label_y, self._slot_w, 14, Qt.AlignHCenter, "OFF")
        p.end()

class _ToggleStyleCard(QWidget):
    """Une carte cliquable du selecteur de style (voir _ToggleStylePicker) :
    libelle + apercu ON/OFF en direct (voir _ToggleShapePreview) — bordure
    accentuee quand selectionnee, meme logique que les autres "cartes"
    cliquables de cette fenetre (voir _PresetListRow)."""

    clicked = Signal()

    # Fond des cartes : noir a 25 % ; carte choisie : teinte de selection des tableaux par-dessus.
    _BG = QColor(0, 0, 0, 64)
    _SELECTED_ALPHA = 56

    def __init__(self, style_key: str, label: str, parent=None):
        super().__init__(parent)
        self._selected = False
        self.style_key = style_key
        self.setObjectName("ToggleStyleCard")
        self.setCursor(Qt.PointingHandCursor)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 10, 16, 10)
        layout.setSpacing(8)
        title = self.title = QLabel(label)
        _set_text_role(title, "card_title")
        title.setAlignment(Qt.AlignHCenter)
        layout.addWidget(title, 0, Qt.AlignHCenter)
        self.preview = _ToggleShapePreview(style_key)
        layout.addWidget(self.preview, 0, Qt.AlignHCenter)

    def _refresh_style(self):
        self.update()

    def setSelected(self, selected: bool):
        if selected != self._selected:
            self._selected = selected
            self.update()

    def setLabel(self, label: str):
        self.title.setText(label)

    def paintEvent(self, event):
        """Cadre = celui des tableaux (Tableaux > Bordure, Rayon des angles), fond noir a 25 %."""
        from fm_theme.layout import _FLAT_TABLE_STYLE        # tardif : settings_layout importe ce module
        enabled, colors, thickness = _FLAT_TABLE_STYLE.get("border") or (True, {}, 1)
        colors = {side: (colors or {}).get(side) or M["field_border"] for side in ("top", "right", "bottom", "left")}
        radius = _FLAT_TABLE_STYLE.get("radius", 0) or 0
        p = QPainter(self)
        rect = self.rect()
        _paint_bordered_rect(p, rect, radius, enabled, thickness, colors, self._BG.name(QColor.NameFormat.HexArgb))
        if self._selected:
            _paint_bordered_rect(p, rect, radius, enabled, thickness, colors,
                                 _selection_color(self._SELECTED_ALPHA).name(QColor.NameFormat.HexArgb))
        p.end()

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            self.clicked.emit()

    def contextMenuEvent(self, event):
        """Clic droit sur une carte : renommer / supprimer CE style (grise s'il n'en reste qu'un)."""
        picker = self.parentWidget()
        menu = Menu(self)
        if isinstance(picker, _ToggleStylePicker):
            picker.populate_card_menu(menu, self.style_key)
        add_context_extras(self, menu)
        if menu.actions():
            menu.exec(event.globalPos())
        event.accept()

class _ToggleStylePicker(QWidget):
    """Choix du style visuel de TOUS les toggles de cette fenetre (voir
    _Toggle/_TOGGLE_STYLE) — 2 cartes cliquables (Toggle 1/Toggle 2),
    chacune avec son propre apercu ON/OFF en direct — voir la remarque de
    l'utilisateur, capture annotee a l'appui (mockup corrige des 2
    styles)."""

    changed = Signal(str)
    # Le selecteur s'est elargi (carte ajoutee, nom plus long) : sa colonne de tableau s'elargit
    # d'autant (build_cells_table), au lieu de rogner ou de superposer les cartes.
    contentGrew = Signal()

    def __init__(self, value: str, parent=None):
        super().__init__(parent)
        # Les cartes viennent du registre (Toggles > Style), dans son ordre.
        self._value = _resolve_toggle_key(value)
        self._layout = QHBoxLayout(self)
        self._layout.setContentsMargins(0, 0, 0, 0)
        self._layout.setSpacing(14)
        self._cards: dict[str, _ToggleStyleCard] = {}
        # Actions fournies par la fenetre : {"add": f(), "rename": f(cle), "delete": f(cle)}.
        self.style_actions: dict = {}
        for key in list(_TOGGLE_STYLES):
            self.addOption(key, _TOGGLE_STYLE_NAMES.get(key, key))

    def addOption(self, key: str, label: str):
        """Ajoute une carte (nouveau style de toggle)."""
        if key in self._cards:
            return
        card = _ToggleStyleCard(key, label)
        card.setSelected(key == self._value)
        card.clicked.connect(lambda _checked=False, k=key: self._select(k))
        self._cards[key] = card
        self._layout.addWidget(card)
        self._equalize()

    def removeOption(self, key: str):
        """Retire la carte d'un style supprime ; s'il etait choisi, le premier restant le devient."""
        card = self._cards.pop(key, None)
        if card is None:
            return
        self._layout.removeWidget(card)
        card.deleteLater()
        if self._value == key and self._cards:
            self._select(next(iter(self._cards)))
        self._equalize()

    def renameOption(self, key: str, label: str):
        if key in self._cards:
            self._cards[key].setLabel(label)
            self._equalize()

    def populate_card_menu(self, menu: QMenu, key: str):
        actions = self.style_actions
        if "rename" in actions:
            menu.addAction("Renommer le toggle…").triggered.connect(lambda _c=False: actions["rename"](key))
        if "delete" in actions:
            delete = menu.addAction("Supprimer le toggle")
            delete.setEnabled(len(self._cards) > 1)        # il reste toujours un style
            delete.triggered.connect(lambda _c=False: actions["delete"](key))
        if "add" in actions:
            menu.addSeparator()
            menu.addAction("Ajouter un nouveau toggle…").triggered.connect(lambda _c=False: actions["add"]())

    def _equalize(self):
        """Toutes les cartes ont la MEME largeur : celle de la plus large."""
        cards = list(self._cards.values())
        for card in cards:
            card.setMinimumWidth(0)
            card.setMaximumWidth(16777215)
        width = max((card.sizeHint().width() for card in cards), default=0)
        for card in cards:
            card.setFixedWidth(width)
        self.updateGeometry()
        self.contentGrew.emit()

    def _select(self, key: str):
        if key != self._value:
            self._value = key
            for k, card in self._cards.items():
                card.setSelected(k == key)
            self.changed.emit(key)

    def value(self) -> str:
        return self._value

    def setValue(self, value: str):
        if value in self._cards and value != self._value:
            self._select(value)

    def refreshPreviews(self):
        """Rappele quand les tableaux Cadre/Coche changent (voir
        SettingsWindow._on_toggle_style_changed) : les apercus de CETTE
        carte lisent _TOGGLE1_STYLE/_TOGGLE2_STYLE en direct, ils ont juste
        besoin d'un repaint (+ recalcul de taille, voir _ToggleShapePreview.
        refresh)."""
        for card in self._cards.values():
            card.preview.refresh()
            card.update()
        self._equalize()

class _CornerPositionCard(QWidget):
    """Une carte cliquable du selecteur de position (voir
    _CornerPositionField) — MEME logique que _ToggleStyleCard (bordure
    accentuee quand selectionnee), mais SANS apercu graphique : juste le
    libelle abrege (BD/BG/HD/HG)."""

    clicked = Signal()

    def __init__(self, label: str, parent=None):
        super().__init__(parent)
        self._selected = False
        self.setObjectName("CornerPositionCard")
        self.setAttribute(Qt.WA_StyledBackground, True)
        self.setCursor(Qt.PointingHandCursor)
        self.setFixedSize(52, 36)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        title = QLabel(label)
        _set_text_role(title, "card_title")
        title.setAlignment(Qt.AlignCenter)
        layout.addWidget(title, 0, Qt.AlignCenter)
        self._refresh_style()

    def _refresh_style(self):
        border = M["accent"] if self._selected else M["field_border"]
        bg = M["btn_hover"] if self._selected else M["field_bg"]
        self.setStyleSheet(
            f"#CornerPositionCard {{ background: {bg}; border: 1px solid {border}; border-radius: 4px; }}")

    def setSelected(self, selected: bool):
        if selected != self._selected:
            self._selected = selected
            self._refresh_style()

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            self.clicked.emit()

class _CornerPositionField(QWidget):
    """Choix du coin d'ancrage du cadre de redimensionnement (voir
    pipeline_browser._show_resize_width) : 4 cartes cliquables (Bas-Droite/
    Bas-Gauche/Haut-Droite/Haut-Gauche), disposees en grille 2x2 refletant
    la position REELLE de chaque coin — MEME principe que _ToggleStylePicker
    (une seule active a la fois) — voir la remarque de l'utilisateur, "je
    veux que dans general/colonnes/ tu crees une sous section cadre de
    redimensionnement avec comme parametres : ligne 1 : position (toggles)
    BD BG HD HG"."""

    changed = Signal(str)

    _OPTIONS = [
        ("top_left", "HG", 0, 0), ("top_right", "HD", 0, 1),
        ("bottom_left", "BG", 1, 0), ("bottom_right", "BD", 1, 1),
    ]

    def __init__(self, value: str, parent=None):
        super().__init__(parent)
        valid = {key for key, *_ in self._OPTIONS}
        self._value = value if value in valid else "bottom_right"
        layout = QGridLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(6)
        self._cards: dict[str, _CornerPositionCard] = {}
        for key, label, row, col in self._OPTIONS:
            card = _CornerPositionCard(label)
            card.setSelected(key == self._value)
            card.clicked.connect(lambda _checked=False, k=key: self._select(k))
            self._cards[key] = card
            layout.addWidget(card, row, col)

    def _select(self, key: str):
        if key != self._value:
            self._value = key
            for k, card in self._cards.items():
                card.setSelected(k == key)
            self.changed.emit(key)

    def value(self) -> str:
        return self._value

    def setValue(self, value: str):
        if value in self._cards and value != self._value:
            self._select(value)

class _ResizeBadgePositionField(QWidget):
    """Ligne "Position" complete du cadre de redimensionnement (voir
    Cadre de redimensionnement > Position) : le coin d'ancrage (voir
    _CornerPositionField) SUIVI, SUR LA MEME LIGNE, de 2 sliders "H"/"V" —
    le decalage (px) applique depuis ce coin, horizontal puis vertical —
    voir la remarque de l'utilisateur, "sous position je veux egalement
    deux sliders (sur la mm ligne) pour la position H et la position V".
    UN SEUL widget (comme _RowBorderField/_ToggleSideColorsField ailleurs
    dans cette fenetre) pour que _build_flat_table lui reserve UNE SEULE
    ligne malgre ses 3 sous-champs."""

    changed = Signal()

    def __init__(self, position: str, offset_x: int, offset_y: int, parent=None):
        super().__init__(parent)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(16)

        self.corner_field = _CornerPositionField(position)
        layout.addWidget(self.corner_field)

        def labeled_slider(text: str, value: int) -> tuple[QLabel, _SliderField]:
            label = QLabel(text)
            _set_text_role(label, "card_title")
            slider = _SliderField(0, 64, value, slider_width=90, box_width=48)
            return label, slider

        h_label, self.offset_x_field = labeled_slider("H", offset_x)
        v_label, self.offset_y_field = labeled_slider("V", offset_y)
        for w in (h_label, self.offset_x_field, v_label, self.offset_y_field):
            layout.addWidget(w, 0, Qt.AlignVCenter)
        layout.addStretch(1)

        self.corner_field.changed.connect(lambda _v: self.changed.emit())
        self.offset_x_field.valueChanged.connect(lambda _v: self.changed.emit())
        self.offset_y_field.valueChanged.connect(lambda _v: self.changed.emit())

    def position(self) -> str:
        return self.corner_field.value()

    def offsetX(self) -> int:
        return self.offset_x_field.value()

    def offsetY(self) -> int:
        return self.offset_y_field.value()

    def setValue(self, position: str, offset_x: int, offset_y: int):
        self.corner_field.setValue(position)
        self.offset_x_field.setValue(offset_x)
        self.offset_y_field.setValue(offset_y)

# ==========================================================================
# Selecteur de couleur maison (remplace QColorDialog, dont l'habillage
# systeme jurait avec le reste de l'appli — voir la remarque de
# l'utilisateur, maquette html fournie a l'appui) : carre saturation/
# luminosite + 3 sliders TSL + 3 sliders RVB, tous synchronises sur une
# seule verite (self._h/_s/_v), plus palette de l'appli (C) et couleurs
# recentes. colorChanged emet a CHAQUE mouvement (glisser un slider, le
# carre...), pas seulement a la validation : c'est ce qui permet a
# _ColorField de repercuter le changement en direct sur la fenetre
# principale, exactement comme le faisait deja QColorDialog en connectant
# son propre currentColorChanged — voir _ColorField._pick.
# ==========================================================================

def _hsv_to_rgb(h: float, s: float, v: float) -> tuple[int, int, int]:
    c = v * s
    x = c * (1 - abs((h / 60) % 2 - 1))
    m = v - c
    if h < 60:
        r, g, b = c, x, 0.0
    elif h < 120:
        r, g, b = x, c, 0.0
    elif h < 180:
        r, g, b = 0.0, c, x
    elif h < 240:
        r, g, b = 0.0, x, c
    elif h < 300:
        r, g, b = x, 0.0, c
    else:
        r, g, b = c, 0.0, x
    return (
        max(0, min(255, round((r + m) * 255))),
        max(0, min(255, round((g + m) * 255))),
        max(0, min(255, round((b + m) * 255))),
    )

def _rgb_to_hex(rgb) -> str:
    return "#{:02x}{:02x}{:02x}".format(*(max(0, min(255, int(c))) for c in rgb))

def _with_alpha(hexval: str, alpha: int) -> str:
    """Prefixe `hexval` ("#rrggbb") du canal alpha (0-255, voir
    app_style._hex_to_alpha) SEULEMENT si < 255 (opaque reste "#rrggbb",
    format INCHANGE — retro-compatible avec les presets/settings.json
    existants, jamais transparents jusqu'ici) — voir la remarque de
    l'utilisateur, "un parametre de transparence des couleurs dans le
    selecteur". QColor/le QSS de Qt lisent nativement ce format
    "#aarrggbb" (verifie directement), aucune autre conversion requise
    cote rendu."""
    alpha = max(0, min(255, int(alpha)))
    if alpha >= 255:
        return hexval
    return f"#{alpha:02x}{hexval.lstrip('#')}"

def _rgb_to_hsv(r: int, g: int, b: int) -> tuple[float, float, float]:
    rf, gf, bf = r / 255, g / 255, b / 255
    mx, mn = max(rf, gf, bf), min(rf, gf, bf)
    d = mx - mn
    if d == 0:
        h = 0.0
    elif mx == rf:
        h = 60 * (((gf - bf) / d) % 6)
    elif mx == gf:
        h = 60 * ((bf - rf) / d + 2)
    else:
        h = 60 * ((rf - gf) / d + 4)
    return h % 360, (d / mx if mx else 0.0), mx

def _hex_to_hsv(hexval: str) -> tuple[float, float, float]:
    return _rgb_to_hsv(*_hex_to_rgb(hexval))

class _SVPad(QWidget):
    """Carre saturation/luminosite peint a la main : fond = degrade blanc
    -> teinte pure (horizontal) par-dessus degrade transparent -> noir
    (vertical), curseur rond a la position (s, v) courante."""

    changed = Signal(float, float)   # (s, v), chacun 0..1

    def __init__(self, width: int = 276, height: int = 160, parent=None):
        super().__init__(parent)
        self._hue = 0.0
        self._s = 0.0
        self._v = 0.0
        self.setFixedSize(width, height)
        self.setCursor(Qt.CrossCursor)

    def setHue(self, hue: float):
        if hue != self._hue:
            self._hue = hue
            self.update()

    def setSV(self, s: float, v: float):
        s = max(0.0, min(1.0, s))
        v = max(0.0, min(1.0, v))
        if (s, v) != (self._s, self._v):
            self._s, self._v = s, v
            self.update()

    def _emit_from_pos(self, pos):
        w, h = max(1, self.width() - 1), max(1, self.height() - 1)
        s = max(0.0, min(1.0, pos.x() / w))
        v = 1.0 - max(0.0, min(1.0, pos.y() / h))
        self._s, self._v = s, v
        self.update()
        self.changed.emit(s, v)

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            self._emit_from_pos(event.position().toPoint())

    def mouseMoveEvent(self, event):
        if event.buttons() & Qt.LeftButton:
            self._emit_from_pos(event.position().toPoint())

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing, False)
        rect = self.rect()
        pure = QColor(*_hsv_to_rgb(self._hue, 1.0, 1.0))
        p.fillRect(rect, pure)
        sat_grad = QLinearGradient(rect.topLeft(), rect.topRight())
        sat_grad.setColorAt(0, QColor(255, 255, 255, 255))
        sat_grad.setColorAt(1, QColor(255, 255, 255, 0))
        p.fillRect(rect, sat_grad)
        val_grad = QLinearGradient(rect.topLeft(), rect.bottomLeft())
        val_grad.setColorAt(0, QColor(0, 0, 0, 0))
        val_grad.setColorAt(1, QColor(0, 0, 0, 255))
        p.fillRect(rect, val_grad)
        p.setRenderHint(QPainter.Antialiasing, True)
        x = int(self._s * (self.width() - 1))
        y = int((1 - self._v) * (self.height() - 1))
        p.setPen(QPen(QColor("#ffffff"), 2))
        p.setBrush(Qt.NoBrush)
        p.drawEllipse(QPoint(x, y), 6, 6)
        p.setPen(QPen(QColor(0, 0, 0, 160), 1))
        p.drawEllipse(QPoint(x, y), 7, 7)
        p.end()

class _GradientSlider(QWidget):
    """Slider horizontal peint a la main, degrade fourni par l'appelant
    (voir setStops) — utilise pour les 6 lignes TSL/RVB du selecteur de
    couleur : le degrade de chaque slider montre le resultat du
    deplacement AVANT de le faire (voir _ColorPickerPopup._refresh_all,
    qui recalcule ces degrades a chaque changement, meme sur un AUTRE
    slider — ex : le degrade "Saturation" depend de la Luminosite
    courante)."""

    changed = Signal(float)   # 0..1

    def __init__(self, width: int = 140, height: int = 13, parent=None, checkerboard: bool = False):
        super().__init__(parent)
        self._frac = 0.0
        self._stops: list[tuple[float, QColor]] = [(0.0, QColor("#000000")), (1.0, QColor("#ffffff"))]
        # `checkerboard` (voir _ColorPickerPopup, ligne Alpha UNIQUEMENT —
        # toutes les autres restent opaques, comportement INCHANGE) : voir
        # _paint_checkerboard, MEME raison qu'ailleurs — un degrade allant
        # jusqu'a transparent se lirait mal sans lui.
        self._checkerboard = checkerboard
        # Largeur MINIMALE, pas fixe : ce slider est ajoute avec un facteur
        # d'etirement (voir _make_row, row.addWidget(slider, 1)) pour
        # occuper l'espace restant de la ligne — un setFixedSize figeait sa
        # largeur a `width` quoi qu'il arrive, ce qui neutralisait cet
        # etirement et pouvait meme faire deborder la ligne (ex. largeur de
        # boite de valeur/espacement augmentes plus tard, voir la remarque
        # de l'utilisateur sur l'espace slider/boite) au lieu de simplement
        # se retrecir pour laisser la place. La hauteur, elle, reste fixe
        # (barre fine, jamais besoin de grandir verticalement).
        self.setMinimumWidth(min(width, 60))
        self.setFixedHeight(height)
        self.setCursor(Qt.CrossCursor)

    def setStops(self, stops):
        self._stops = [(pos, QColor(hexval)) for pos, hexval in stops]
        self.update()

    def setFraction(self, frac: float):
        frac = max(0.0, min(1.0, frac))
        if frac != self._frac:
            self._frac = frac
            self.update()

    def _emit_from_x(self, x: int):
        w = max(1, self.width() - 1)
        frac = max(0.0, min(1.0, x / w))
        self._frac = frac
        self.update()
        self.changed.emit(frac)

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            self._emit_from_x(int(event.position().x()))

    def mouseMoveEvent(self, event):
        if event.buttons() & Qt.LeftButton:
            self._emit_from_x(int(event.position().x()))

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing, False)
        rect = self.rect()
        if self._checkerboard:
            _paint_checkerboard(p, rect)
        grad = QLinearGradient(rect.topLeft(), rect.topRight())
        for pos, color in self._stops:
            grad.setColorAt(pos, color)
        p.fillRect(rect, grad)
        p.setPen(QPen(QColor(M["swatch_border"]), 1))
        p.drawRect(rect.adjusted(0, 0, -1, -1))
        x = int(self._frac * max(0, self.width() - 3))
        p.setPen(Qt.NoPen)
        p.setBrush(QColor("#ffffff"))
        p.drawRect(x, -3, 3, self.height() + 6)
        p.setPen(QPen(QColor(0, 0, 0, 160), 1))
        p.setBrush(Qt.NoBrush)
        p.drawRect(x, -3, 3, self.height() + 6)
        p.end()

class _PickerCloseButton(QPushButton):
    """Petit bouton "X" peint a la main — meme raison que _HamburgerButton
    (glyphe unicode non fiable a cette taille selon la police systeme)."""

    def __init__(self, color: str, parent=None):
        super().__init__(parent)
        self._color = color

    def paintEvent(self, event):
        super().paintEvent(event)
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing, True)
        painter.setPen(QPen(QColor(self._color), 1.3))
        w, h = self.width(), self.height()
        cx, cy = w / 2, h / 2
        s = min(w, h) * 0.22
        painter.drawLine(QPointF(cx - s, cy - s), QPointF(cx + s, cy + s))
        painter.drawLine(QPointF(cx - s, cy + s), QPointF(cx + s, cy - s))
        painter.end()

class _PipetteButton(QPushButton):
    """Petit bouton pipette peint a la main — meme raison que
    _PickerCloseButton (glyphe unicode non fiable selon la police
    systeme) : capture d'une couleur n'importe ou a l'ecran."""

    def __init__(self, color: str, parent=None):
        super().__init__(parent)
        self._color = color

    def paintEvent(self, event):
        super().paintEvent(event)
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing, True)
        painter.setPen(QPen(QColor(self._color), 1.3))
        w, h = self.width(), self.height()
        # corps du compte-gouttes : trait diagonal + pointe, incline a 45°
        x1, y1 = w * 0.28, h * 0.72
        x2, y2 = w * 0.68, h * 0.32
        painter.drawLine(QPointF(x1, y1), QPointF(x2, y2))
        painter.drawEllipse(QPointF(x2, y2), 2.2, 2.2)
        painter.drawLine(QPointF(w * 0.22, h * 0.78), QPointF(w * 0.32, h * 0.68))
        painter.end()

class _PipetteAreaButton(QPushButton):
    """Variante "zone" du bouton pipette — glyphe rectangle en pointilles,
    pour la difference de la pipette point (_PipetteButton)."""

    def __init__(self, color: str, parent=None):
        super().__init__(parent)
        self._color = color

    def paintEvent(self, event):
        super().paintEvent(event)
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing, True)
        pen = QPen(QColor(self._color), 1.3, Qt.DashLine)
        painter.setPen(pen)
        w, h = self.width(), self.height()
        rect = QRect(int(w * 0.22), int(h * 0.28), int(w * 0.56), int(h * 0.44))
        painter.drawRect(rect)
        painter.end()

def _grab_virtual_desktop() -> tuple[QPixmap, QPoint]:
    """Capture tous les ecrans en un seul pixmap, recale sur l'origine du
    bureau virtuel (qui peut etre negative si un moniteur est place a
    gauche/au-dessus du principal). Retourne (pixmap, origine)."""
    screens = QGuiApplication.screens()
    geo = QRect()
    for screen in screens:
        geo = geo.united(screen.geometry())
    origin = geo.topLeft()
    pixmap = QPixmap(geo.size())
    pixmap.fill(Qt.black)
    painter = QPainter(pixmap)
    for screen in screens:
        shot = screen.grabWindow(0)
        shot.setDevicePixelRatio(1.0)
        painter.drawPixmap(screen.geometry().translated(-origin), shot)
    painter.end()
    return pixmap, origin

def _make_pipette_cursor() -> QCursor:
    """Curseur "compte-gouttes" — remplace le curseur systeme le temps de
    la capture (voir la demande : le curseur doit rester ce glyphe jusqu'a
    la selection, pas juste une croix generique)."""
    size = 28
    pm = QPixmap(size, size)
    pm.fill(Qt.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.Antialiasing, True)
    tip = QPointF(5, 23)
    tail = QPointF(19, 9)
    pen_outline = QPen(QColor("#000000"), 4.2)
    pen_outline.setCapStyle(Qt.RoundCap)
    p.setPen(pen_outline)
    p.drawLine(tip, tail)
    pen_fill = QPen(QColor("#ffffff"), 2.2)
    pen_fill.setCapStyle(Qt.RoundCap)
    p.setPen(pen_fill)
    p.drawLine(tip, tail)
    p.setPen(QPen(QColor("#000000"), 1))
    p.setBrush(QColor("#ffffff"))
    p.drawEllipse(tip, 2.6, 2.6)
    p.end()
    return QCursor(pm, int(tip.x()), int(tip.y()))

class _ScreenCaptureOverlay(QWidget):
    """Base commune aux deux pipettes : fenetre plein "bureau virtuel"
    (tous les moniteurs) affichant une copie figee de l'ecran, sur
    laquelle vient se dessiner l'interaction propre a chaque sous-classe
    (point ou rectangle). Echap annule toujours."""

    picked = Signal(str)
    cancelled = Signal()

    def __init__(self):
        super().__init__(None, Qt.FramelessWindowHint | Qt.Tool | Qt.WindowStaysOnTopHint)
        self.setAttribute(Qt.WA_DeleteOnClose)
        self.setMouseTracking(True)
        self._resolved = False
        self._pixmap, self._origin = _grab_virtual_desktop()
        self._image = self._pixmap.toImage()
        self.setGeometry(QRect(self._origin, self._pixmap.size()))

    def paintEvent(self, event):
        p = QPainter(self)
        p.drawPixmap(0, 0, self._pixmap)
        self._paint_overlay(p)
        p.end()

    def _paint_overlay(self, painter: QPainter):
        pass

    def _color_at(self, pos: QPoint):
        x, y = pos.x(), pos.y()
        if 0 <= x < self._image.width() and 0 <= y < self._image.height():
            return QColor(self._image.pixel(x, y))
        return None

    def keyPressEvent(self, event):
        if event.key() == Qt.Key_Escape:
            self._finish(None)
        else:
            super().keyPressEvent(event)

    def _finish(self, hexval):
        if self._resolved:
            return
        self._resolved = True
        if hexval is not None:
            self.picked.emit(hexval)
        else:
            self.cancelled.emit()
        self.close()

class _EyedropperOverlay(_ScreenCaptureOverlay):
    """Pipette "point" — capture la couleur du pixel sous le curseur.
    Le curseur systeme prend la forme d'un compte-gouttes et le garde
    jusqu'au clic (voir _make_pipette_cursor) ; une pastille flottante
    affiche le hex du pixel survole, en plus du curseur, pour lire la
    valeur avant de valider. Clic gauche valide, tout autre bouton ou
    Echap annule."""

    def __init__(self):
        super().__init__()
        self.setCursor(_make_pipette_cursor())
        self._last_hex = "#000000"
        self._preview = QLabel(self)
        self._preview.setFont(_qfont(10, 600, mono=True))
        self._preview.hide()

    def mouseMoveEvent(self, event):
        pos = event.position().toPoint()
        color = self._color_at(pos)
        if color is not None:
            self._last_hex = color.name()
            fg = "#000000" if color.lightness() > 128 else "#ffffff"
            self._preview.setText(f"  {self._last_hex}  ")
            self._preview.setStyleSheet(
                f"background: {self._last_hex}; color: {fg}; border: 1px solid #000000; padding: 2px;"
            )
            self._preview.adjustSize()
            self._preview.move(pos.x() + 18, pos.y() + 22)
            self._preview.show()

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            color = self._color_at(event.position().toPoint())
            self._finish(color.name() if color is not None else self._last_hex)
        else:
            self._finish(None)

class _AreaEyedropperOverlay(_ScreenCaptureOverlay):
    """Pipette "zone" — on glisse un rectangle, la couleur retenue est la
    moyenne des pixels de la selection (sous-echantillonnee sur une
    grille 32x32 pour rester instantanee meme sur une grande zone).
    Clic-glisser puis relacher valide ; Echap ou clic droit annule."""

    def __init__(self):
        super().__init__()
        self.setCursor(Qt.CrossCursor)
        self._dragging = False
        self._start = QPoint()
        self._current_rect = QRect()
        self._last_hex = "#000000"
        self._preview = QLabel(self)
        self._preview.setFont(_qfont(10, 600, mono=True))
        self._preview.hide()

    def _average_color(self, rect: QRect) -> QColor:
        rect = rect.intersected(self._image.rect())
        if rect.width() <= 0 or rect.height() <= 0:
            return QColor(self._last_hex)
        sample = self._image.copy(rect).scaled(
            32, 32, Qt.IgnoreAspectRatio, Qt.SmoothTransformation
        )
        r = g = b = n = 0
        for y in range(sample.height()):
            for x in range(sample.width()):
                c = sample.pixelColor(x, y)
                r += c.red()
                g += c.green()
                b += c.blue()
                n += 1
        if n == 0:
            return QColor(self._last_hex)
        return QColor(r // n, g // n, b // n)

    def _update_preview(self, pos: QPoint):
        color = self._average_color(self._current_rect)
        self._last_hex = color.name()
        fg = "#000000" if color.lightness() > 128 else "#ffffff"
        self._preview.setText(f"  {self._last_hex}  moyenne  ")
        self._preview.setStyleSheet(
            f"background: {self._last_hex}; color: {fg}; border: 1px solid #000000; padding: 2px;"
        )
        self._preview.adjustSize()
        self._preview.move(pos.x() + 18, pos.y() + 22)
        self._preview.show()

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            self._dragging = True
            self._start = event.position().toPoint()
            self._current_rect = QRect(self._start, self._start)
            self.update()
        else:
            self._finish(None)

    def mouseMoveEvent(self, event):
        pos = event.position().toPoint()
        if self._dragging:
            self._current_rect = QRect(self._start, pos).normalized()
            self._update_preview(pos)
            self.update()

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.LeftButton and self._dragging:
            self._dragging = False
            color = self._average_color(self._current_rect)
            self._finish(color.name())

    def _paint_overlay(self, painter: QPainter):
        if self._current_rect.isNull() or self._current_rect.isEmpty():
            return
        painter.setPen(QPen(QColor("#ffffff"), 1.5))
        painter.setBrush(QColor(255, 255, 255, 40))
        painter.drawRect(self._current_rect)

def _paint_checkerboard(p: QPainter, rect: QRect, tile: int = 6):
    """Damier 2 tons (voir _ColorSwatchButton) — convention standard pour
    representer une transparence dans un apercu de couleur (Photoshop et
    consorts) : sans lui, une couleur partiellement transparente se
    fondrait juste avec le fond du panneau derriere la pastille, illisible
    — voir la remarque de l'utilisateur, "un parametre de transparence des
    couleurs dans le selecteur"."""
    light, dark = QColor("#4a4d51"), QColor("#34363a")
    y = rect.top()
    row = 0
    while y < rect.bottom():
        h = min(tile, rect.bottom() - y)
        x = rect.left()
        col = 0
        while x < rect.right():
            w = min(tile, rect.right() - x)
            p.fillRect(QRect(x, y, w, h), light if (row + col) % 2 == 0 else dark)
            x += tile
            col += 1
        y += tile
        row += 1

class _ColorSwatchButton(QPushButton):
    """Pastille de couleur cliquable, fond peint A LA MAIN (damier si
    alpha < 255, puis la couleur par-dessus avec son alpha REEL, puis la
    bordure) — remplace l'ancien "QPushButton { background: <hex>; }" en
    QSS (voir _ColorField/_AppOrCustomColorField, qui l'utilisaient
    toutes les deux) : un simple fond QSS composerait bien la
    transparence, mais SANS damier dessous, la rendant illisible/confondue
    avec une couleur opaque proche — voir la remarque de l'utilisateur, "un
    parametre de transparence des couleurs dans le selecteur"."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._hex = "#000000"
        self.setCursor(Qt.ArrowCursor)
        self.setFocusPolicy(Qt.NoFocus)
        self.setStyleSheet("QPushButton { background: transparent; border: none; }")
        self.setAttribute(Qt.WA_Hover, True)

    def setColorHex(self, hexval: str):
        self._hex = hexval or "#000000"
        self.update()

    def event(self, e):
        # WA_Hover (pas juste underMouse() dans paintEvent) : force un
        # repaint AU survol/depart, sinon la bordure "hover" (voir
        # paintEvent) ne se met a jour qu'au prochain repaint declenche par
        # autre chose (deja constate sur d'autres boutons customs de cette
        # fenetre).
        if e.type() in (QEvent.Enter, QEvent.Leave):
            self.update()
        return super().event(e)

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing, True)
        rect = QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)
        path = QPainterPath()
        path.addRoundedRect(rect, 2, 2)
        p.save()
        p.setClipPath(path)
        color = QColor(self._hex)
        if color.alpha() < 255:
            _paint_checkerboard(p, self.rect())
        p.fillRect(self.rect(), color)
        p.restore()
        border_color = M["swatch_border_hover"] if self.underMouse() else M["swatch_border"]
        p.setPen(QPen(QColor(border_color), 1))
        p.setBrush(Qt.NoBrush)
        p.drawPath(path)
        if getattr(self, "_drop_hover", False):
            # Couleur glissee au-dessus (copie, settings_sections) : cette pastille la recevra.
            p.setPen(QPen(QColor(M["accent"]), 2))
            p.drawRoundedRect(QRectF(self.rect()).adjusted(1, 1, -1, -1), 2, 2)
        p.end()

    def set_drop_hover(self, on: bool):
        if getattr(self, "_drop_hover", False) != on:
            self._drop_hover = on
            self.update()

class _PopupHeader(QWidget):
    """En-tete du popup couleur — glissable : le popup n'a pas d'autre
    barre de titre ni de bord redimensionnable, et s'ouvre toujours a une
    position fixe pres de la pastille cliquee (voir show_near), qui peut
    geneur (ex. juste au-dessus d'une zone de l'ecran qu'on veut piocher a
    la pipette). Cliquer-glisser n'importe ou sur ce bandeau (hors les
    boutons pipette/fermer, qui recoivent et consomment deja leurs propres
    clics avant que head en soit informe) deplace tout le popup."""

    def __init__(self, popup: QWidget, parent=None):
        super().__init__(parent)
        self._popup = popup
        self._drag_offset = None

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            self._drag_offset = event.globalPosition().toPoint() - self._popup.pos()
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        if self._drag_offset is not None and (event.buttons() & Qt.LeftButton):
            self._popup.move(event.globalPosition().toPoint() - self._drag_offset)
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        self._drag_offset = None
        super().mouseReleaseEvent(event)

class _ColorPickerPopup(QWidget):
    """Selecteur de couleur maison — remplace QColorDialog. colorChanged
    emet a chaque mouvement (previsualisation en direct sur la fenetre
    principale, voir _ColorField._pick) ; committed seulement a la
    validation (Valider, ou un clic en dehors du popup — voir closeEvent),
    qui fige aussi la couleur dans les "Recentes" ; cancelled restaure la
    valeur de depart (bouton Annuler ou croix, jamais un simple clic
    dehors — voir la meme remarque)."""

    colorChanged = Signal(str)
    committed = Signal(str)
    cancelled = Signal()

    # Bornes du glisser sur le bord droit (voir mousePressEvent) : 300 =
    # largeur d'origine (avant setFixedWidth), 640 = large sans depasser
    # demesurement un ecran modeste.
    _MIN_WIDTH = 300
    _MAX_WIDTH = 640
    _RESIZE_MARGIN = 6

    def __init__(self, initial_hex: str, title: str, parent=None):
        super().__init__(parent, Qt.Popup)
        self._before = initial_hex
        self._resolved = False
        self._h, self._s, self._v = _hex_to_hsv(initial_hex)
        # Alpha (0-255, voir app_style._hex_to_alpha/Colonnes > ... > la
        # remarque de l'utilisateur, "un parametre de transparence des
        # couleurs dans le selecteur") — 255 (opaque) pour tout hex a 6
        # chiffres, comportement INCHANGE tant que non personnalise.
        self._a = _hex_to_alpha(initial_hex)
        # Meme rayon que les vraies zones de saisie de l'appli principale
        # (voir get_input_radius) — calcule ici, AVANT _make_row (boites de
        # valeur TSL/RVB) ET la boite HEX/le bloc avant-apres plus bas, qui
        # en ont tous besoin.
        self._input_radius = get_input_radius()

        self.setObjectName("ColorPicker")
        self.setAttribute(Qt.WA_StyledBackground, True)
        self.setStyleSheet(
            f"#ColorPicker {{ background: {M['panel_bg']}; border: 1px solid {M['panel_border']}; }}"
        )
        # Largeur MINIMALE (plus fixe) : le bord droit devient une poignee
        # de redimensionnement (voir mousePressEvent/mouseMoveEvent/
        # resizeEvent plus bas) — l'utilisateur peut elargir le popup pour
        # des sliders TSL/RVB plus longs, donc un controle plus precis (voir
        # sa remarque). show_near() rappelle adjustSize() a chaque ouverture,
        # qui revient a cette largeur par defaut (pas de memorisation d'une
        # largeur choisie d'une ouverture a l'autre, hors scope de la
        # demande).
        self.setMinimumWidth(self._MIN_WIDTH)
        self._resizing = False
        self._resize_start_x = 0
        self._resize_start_width = 0
        self.setMouseTracking(True)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        # -- en-tete --
        head = _PopupHeader(self)
        head.setFixedHeight(28)
        head.setStyleSheet(f"background: {M['btn_hover']}; border-bottom: 2px solid {M['accent']};")
        head_l = QHBoxLayout(head)
        head_l.setContentsMargins(10, 0, 8, 0)
        head_l.setSpacing(8)
        tag = QLabel("COULEUR")
        _set_text_role(tag, "tag_accent")
        head_l.addWidget(tag)
        title_label = QLabel(title)
        _set_text_role(title_label, "card_title")
        title_label.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
        head_l.addWidget(title_label, 1)
        pipette_btn = _PipetteButton(M["label_dim"])
        pipette_btn.setFixedSize(16, 16)
        pipette_btn.setCursor(Qt.ArrowCursor)
        pipette_btn.setFlat(True)
        pipette_btn.setToolTip("Piocher une couleur a l'ecran")
        pipette_btn.clicked.connect(lambda: self._on_pipette(_EyedropperOverlay))
        head_l.addWidget(pipette_btn)
        pipette_area_btn = _PipetteAreaButton(M["label_dim"])
        pipette_area_btn.setFixedSize(16, 16)
        pipette_area_btn.setCursor(Qt.ArrowCursor)
        pipette_area_btn.setFlat(True)
        pipette_area_btn.setToolTip("Piocher la couleur moyenne d'une zone de l'ecran")
        pipette_area_btn.clicked.connect(lambda: self._on_pipette(_AreaEyedropperOverlay))
        head_l.addWidget(pipette_area_btn)
        close_btn = _PickerCloseButton(M["label_dim"])
        close_btn.setFixedSize(16, 16)
        close_btn.setCursor(Qt.ArrowCursor)
        close_btn.setFlat(True)
        close_btn.clicked.connect(self._on_cancel)
        head_l.addWidget(close_btn)
        outer.addWidget(head)

        # -- corps --
        body = QVBoxLayout()
        body.setContentsMargins(12, 12, 12, 12)
        body.setSpacing(12)

        self.pad = _SVPad(width=276)
        self.pad.changed.connect(self._on_sv)
        body.addWidget(self.pad)

        hsl_row = QVBoxLayout()
        hsl_row.setSpacing(8)
        self._hsl_rows = []
        for i, (label, unit) in enumerate((("Teinte", "°"), ("Saturation", "%"), ("Luminosite", "%"))):
            row, slider, val_label = self._make_row(label, unit)
            slider.changed.connect(lambda f, idx=i: self._on_hsl(idx, f))
            self._wire_value(val_label, 360 if i == 0 else 100, lambda f, idx=i: self._on_hsl(idx, f))
            self._hsl_rows.append((slider, val_label))
            hsl_row.addLayout(row)
        body.addLayout(hsl_row)

        body.addWidget(self._divider())

        body.addWidget(self._tag_label("COMPOSANTES RVB"))
        rgb_col = QVBoxLayout()
        rgb_col.setSpacing(8)
        self._rgb_rows = []
        for i, label in enumerate(("Rouge", "Vert", "Bleu")):
            row, slider, val_label = self._make_row(label, "")
            slider.changed.connect(lambda f, idx=i: self._on_rgb(idx, f))
            self._wire_value(val_label, 255, lambda f, idx=i: self._on_rgb(idx, f))
            self._rgb_rows.append((slider, val_label))
            rgb_col.addLayout(row)
        body.addLayout(rgb_col)

        body.addWidget(self._divider())

        # -- Alpha (transparence, voir la remarque de l'utilisateur, "un
        # parametre de transparence des couleurs dans le selecteur") —
        # MEME ligne/MEME slider que Teinte/Saturation/... (_make_row/
        # _GradientSlider), degrade transparent -> couleur pleine pour
        # visualiser l'effet, damier dessous (voir _paint_checkerboard)
        # pour que la moitie transparente du degrade reste lisible.
        body.addWidget(self._tag_label("TRANSPARENCE"))
        alpha_row, alpha_slider, alpha_val = self._make_row("Alpha", "%", checkerboard=True)
        alpha_slider.changed.connect(self._on_alpha)
        self._wire_value(alpha_val, 100, self._on_alpha)
        self._alpha_slider, self._alpha_val = alpha_slider, alpha_val
        body.addLayout(alpha_row)

        body.addWidget(self._divider())

        # -- avant/apres + hex --
        # Habille "comme un tableau" (voir la remarque de l'utilisateur,
        # capture annotee a l'appui) : memes primitives _TableFrame/
        # _restyle_table_row que les VRAIS tableaux de cette fenetre
        # (Polices/Entetes/Geometrie) — cadre exterieur a filet unique,
        # coins arrondis PORTES par les lignes elles-memes (ici "avant" en
        # haut, "apres" en bas, exactement comme la premiere/derniere ligne
        # d'un tableau sans entete — voir la table Entetes), et un seul
        # filet 1px entre les deux lignes (le border-top que
        # _restyle_table_row ajoute deja automatiquement pour toute ligne
        # non "first").
        hex_row = QHBoxLayout()
        hex_row.setSpacing(9)
        stacked, stacked_l = _table_frame()
        stacked.setFixedSize(58, 34)
        stacked.setRadius(self._input_radius)
        self._before_swatch = QWidget()
        self._before_swatch.setObjectName("TableRow")
        self._before_swatch.setAttribute(Qt.WA_StyledBackground, True)
        self._after_swatch = QWidget()
        self._after_swatch.setObjectName("TableRow")
        self._after_swatch.setAttribute(Qt.WA_StyledBackground, True)
        stacked_l.addWidget(self._before_swatch, 1)
        stacked_l.addWidget(self._after_swatch, 1)
        hex_row.addWidget(stacked)

        hex_box = QWidget()
        hex_box.setFixedHeight(34)
        hex_box.setObjectName("HexBox")
        hex_box.setAttribute(Qt.WA_StyledBackground, True)
        hex_box.setStyleSheet(
            f"#HexBox {{ background: {input_bg()}; {input_border_decl()} "
            f"border-radius: {self._input_radius}px; }}"
        )
        hex_l = QHBoxLayout(hex_box)
        hex_l.setContentsMargins(9, 0, 9, 0)
        hex_l.setSpacing(9)
        hex_tag = QLabel("HEX")
        _set_text_role(hex_tag, "hex_tag")
        hex_l.addWidget(hex_tag)
        self.hex_edit = QLineEdit()
        self.hex_edit.setFont(_qfont(13, 400, mono=True))
        self.hex_edit.setFrame(False)
        # setFrame(False) desactive seulement le cadre NATIF Qt — le QSS
        # global de l'appli (QLineEdit { border: ... }) continue de
        # s'appliquer par-dessus tant que "border" n'est pas explicitement
        # ecrase ici, d'ou ce filet visible autour du champ hex en plus de
        # celui de HexBox qui l'entoure deja — voir la remarque de
        # l'utilisateur, capture annotee a l'appui ("pas de bordure").
        self.hex_edit.setStyleSheet(f"background: transparent; border: none; color: {M['value_fg']};")
        self.hex_edit.editingFinished.connect(self._on_hex_edited)
        hex_l.addWidget(self.hex_edit, 1)
        hex_row.addWidget(hex_box, 1)
        body.addLayout(hex_row)

        outer.addLayout(body)

        # -- bas --
        foot = QWidget()
        foot.setFixedHeight(40)
        foot.setStyleSheet(f"background: {M['toolbar_bg']}; border-top: 1px solid {M['panel_border']};")
        foot_l = QHBoxLayout(foot)
        foot_l.setContentsMargins(12, 0, 12, 0)
        foot_l.setSpacing(6)
        reset_btn = _Btn("Reinitialiser", "transparent", M["btn_border"], M["reset_fg"], M["btn_bg"],
                          height=25, padding="0 10px")
        reset_btn.clicked.connect(self._on_reset)
        foot_l.addWidget(reset_btn)
        foot_l.addStretch(1)
        cancel_btn = _Btn("Annuler", M["btn_bg"], M["btn_border"], M["btn_fg"], M["btn_hover"], height=25)
        cancel_btn.clicked.connect(self._on_cancel)
        foot_l.addWidget(cancel_btn)
        # Pas de bordure (voir la remarque de l'utilisateur, capture
        # annotee a l'appui, "supprime bordure") — fond plein uniquement,
        # comme un bouton primaire de l'appli principale.
        ok_btn = _Btn("Valider", M["accent"], "", M["accent_fg"], M["accent_hover"],
                      height=25, weight=600, padding="0 14px")
        ok_btn.clicked.connect(self._on_commit)
        foot_l.addWidget(ok_btn)
        outer.addWidget(foot)

        self._refresh_all()

    # -- construction --

    def _tag_label(self, text: str) -> QLabel:
        label = QLabel(text)
        _set_text_role(label, "tag")
        return label

    def _divider(self) -> QWidget:
        line = QWidget()
        line.setFixedHeight(1)
        line.setStyleSheet(f"background: {M['edge_off']};")
        return line

    def _wire_value(self, edit: QLineEdit, maximum: int, on_fraction) -> None:
        """Valeur tapee (0..maximum) -> meme chemin que le curseur de la ligne (fraction 0..1), a la
        validation (Entree / clic ailleurs) ; hors bornes : ramenee dans les bornes."""
        # Chiffres seulement, autant que le maximum en a : borne a 0..maximum a la validation (un
        # validateur borne a `maximum` gardait « 999 » affiche sans jamais valider).
        edit.setValidator(QIntValidator(0, 10 ** len(str(maximum)) - 1, edit))

        def commit():
            try:
                value = int(edit.text())
            except ValueError:
                self._refresh_all()          # vide : la valeur courante revient
                return
            on_fraction(max(0, min(maximum, value)) / maximum)
            self._refresh_all()              # valeur ramenee dans les bornes affichee

        edit.editingFinished.connect(commit)

    def _make_row(self, label: str, unit: str, checkerboard: bool = False):
        row = QHBoxLayout()
        row.setSpacing(9)
        name = QLabel(label)
        name.setFixedWidth(70)
        _set_text_role(name, "inline_label")
        row.addWidget(name)
        slider = _GradientSlider(checkerboard=checkerboard)
        row.addWidget(slider, 1)
        # Espace visible avant la boite de valeur (en plus des 9px de
        # row.setSpacing deja appliques) : le curseur du slider pouvait
        # quasiment toucher la boite en fin de course — voir la remarque
        # de l'utilisateur, capture annotee a l'appui ("reduire la zone de
        # saisie pour avoir un espace"). Boite retrecie (60, pas 64) pour
        # compenser et garder le popup a la meme largeur totale.
        row.addSpacing(10)
        box = QWidget()
        box.setFixedSize(60, 22)
        box.setObjectName("ValBox")
        box.setAttribute(Qt.WA_StyledBackground, True)
        # C'est une zone de saisie comme les autres : meme rayon que hex_box
        # (self._input_radius) — voir la remarque de l'utilisateur, capture
        # annotee a l'appui ("zone de saisie donc arrondie les angles").
        # Valeur SAISISSABLE (demande de l'utilisateur : les textes du selecteur n'etaient pas
        # modifiables) : zone de saisie sans cadre dans la boite, entiers seulement (voir _wire_value).
        box.setStyleSheet(
            f"#ValBox {{ background: {input_bg()}; {input_border_decl()} "
            f"border-radius: {self._input_radius}px; }}"
            "#ValBox QLineEdit { border: none; padding: 0; margin: 0; }"
        )
        box_l = QHBoxLayout(box)
        box_l.setContentsMargins(9, 0, 9, 0)
        box_l.setSpacing(2)
        val_label = QLineEdit("0")
        val_label.setFrame(False)
        _set_text_role(val_label, "value_mono")
        val_label.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        box_l.addWidget(val_label, 1)
        if unit:
            unit_label = QLabel(unit)
            _set_text_role(unit_label, "unit")
            box_l.addWidget(unit_label)
        row.addWidget(box)
        return row, slider, val_label

    # -- etat --

    def _current_hex(self) -> str:
        return _with_alpha(_rgb_to_hex(_hsv_to_rgb(self._h, self._s, self._v)), self._a)

    def _refresh_all(self):
        rgb = _hsv_to_rgb(self._h, self._s, self._v)
        hexval = _rgb_to_hex(rgb)
        # hexval_a (PAS hexval) : c'est CETTE valeur, alpha inclus, qui
        # sort du popup (apercu apres/hex_edit/signal emis) — voir
        # _current_hex, MEME regle (opaque reste "#rrggbb").
        hexval_a = _with_alpha(hexval, self._a)
        self.pad.setHue(self._h)
        self.pad.setSV(self._s, self._v)

        hue_slider, hue_val = self._hsl_rows[0]
        hue_slider.setStops([
            (0.0, "#ff0000"), (1 / 6, "#ffff00"), (2 / 6, "#00ff00"),
            (3 / 6, "#00ffff"), (4 / 6, "#0000ff"), (5 / 6, "#ff00ff"), (1.0, "#ff0000"),
        ])
        hue_slider.setFraction(self._h / 360)
        hue_val.setText(str(round(self._h)))

        sat_slider, sat_val = self._hsl_rows[1]
        sat_slider.setStops([
            (0.0, _rgb_to_hex(_hsv_to_rgb(self._h, 0.0, self._v))),
            (1.0, _rgb_to_hex(_hsv_to_rgb(self._h, 1.0, self._v))),
        ])
        sat_slider.setFraction(self._s)
        sat_val.setText(str(round(self._s * 100)))

        lum_slider, lum_val = self._hsl_rows[2]
        lum_slider.setStops([(0.0, "#000000"), (1.0, _rgb_to_hex(_hsv_to_rgb(self._h, self._s, 1.0)))])
        lum_slider.setFraction(self._v)
        lum_val.setText(str(round(self._v * 100)))

        for i, (slider, val_label) in enumerate(self._rgb_rows):
            lo, hi = list(rgb), list(rgb)
            lo[i], hi[i] = 0, 255
            slider.setStops([(0.0, _rgb_to_hex(lo)), (1.0, _rgb_to_hex(hi))])
            slider.setFraction(rgb[i] / 255)
            val_label.setText(str(rgb[i]))

        # Degrade transparent (alpha 0) -> couleur PLEINE (alpha 255) de la
        # teinte COURANTE — MEME hexval (opaque) que les stops RVB
        # ci-dessus, juste rejoue avec chaque alpha via _with_alpha.
        self._alpha_slider.setStops([(0.0, _with_alpha(hexval, 0)), (1.0, _with_alpha(hexval, 255))])
        self._alpha_slider.setFraction(self._a / 255)
        self._alpha_val.setText(str(round(self._a / 255 * 100)))

        # Habille comme les 2 lignes d'un vrai tableau sans entete de cette
        # fenetre (voir _restyle_table_row/la table Entetes, meme
        # technique) : "avant" = premiere ligne (porte le rayon HAUT du
        # cadre), "apres" = derniere ligne (porte le rayon BAS, et le seul
        # filet horizontal separant les deux, ajoute automatiquement par
        # _restyle_table_row pour toute ligne non "first") — voir la
        # remarque de l'utilisateur, capture annotee a l'appui ("comme un
        # tableau").
        _restyle_table_row(self._before_swatch, self._before, first=True, top_radius=self._input_radius)
        _restyle_table_row(self._after_swatch, hexval_a, first=False, bottom_radius=self._input_radius)
        if self.hex_edit.text().lower() != hexval_a:
            cursor = self.hex_edit.cursorPosition()
            self.hex_edit.setText(hexval_a)
            self.hex_edit.setCursorPosition(min(cursor, len(hexval_a)))

        self.colorChanged.emit(hexval_a)

    # -- interactions --

    def _on_sv(self, s: float, v: float):
        self._s, self._v = s, v
        self._refresh_all()

    def _on_hsl(self, idx: int, frac: float):
        if idx == 0:
            self._h = frac * 360
        elif idx == 1:
            self._s = frac
        else:
            self._v = frac
        self._refresh_all()

    def _on_rgb(self, idx: int, frac: float):
        rgb = list(_hsv_to_rgb(self._h, self._s, self._v))
        rgb[idx] = round(frac * 255)
        self._h, self._s, self._v = _rgb_to_hsv(*rgb)
        self._refresh_all()

    def _on_alpha(self, frac: float):
        self._a = round(max(0.0, min(1.0, frac)) * 255)
        self._refresh_all()

    def _on_hex_edited(self):
        text = self.hex_edit.text().strip()
        if not text.startswith("#"):
            text = "#" + text
        # 7 chiffres ("#rrggbb", opaque) OU 9 ("#aarrggbb", voir _with_
        # alpha/app_style._hex_to_alpha) — voir la remarque de
        # l'utilisateur, "un parametre de transparence des couleurs dans
        # le selecteur".
        if len(text) in (7, 9):
            try:
                int(text[1:], 16)
            except ValueError:
                pass
            else:
                self._h, self._s, self._v = _hex_to_hsv(text)
                self._a = _hex_to_alpha(text)
        self._refresh_all()

    def _on_reset(self):
        self._h, self._s, self._v = _hex_to_hsv(self._before)
        self._a = _hex_to_alpha(self._before)
        self._refresh_all()

    def _on_pipette(self, overlay_cls):
        # Le popup reste ouvert mais s'efface le temps de la capture, pour
        # ne pas se piocher lui-meme comme couleur. _pipette_active evite
        # que ce hide() soit interprete comme une validation par
        # hideEvent (voir sa remarque : hide() = clic dehors = commit).
        self._pipette_active = True
        self.hide()
        # Ce popup est une fenetre Qt.Popup : elle detient un grab souris
        # implicite tant qu'elle est visible. hide() le relache, mais Qt
        # ne finalise cette liberation qu'au retour dans la boucle
        # d'evenements — creer/afficher l'overlay de capture (qui doit
        # lui-meme recevoir les clics) DANS ce meme cycle d'evenement (le
        # slot du clic sur le bouton pipette) le fait echouer silencieuse-
        # ment : l'overlay s'affiche mais ne recoit rien. D'ou ce
        # singleShot(0, ...), qui reporte sa creation au prochain passage
        # de la boucle, une fois le grab du popup vraiment libere.
        QTimer.singleShot(0, lambda: self._launch_pipette(overlay_cls))

    def _launch_pipette(self, overlay_cls):
        overlay = overlay_cls()
        self._active_overlay = overlay   # garde une reference forte (sinon GC Python possible)
        overlay.picked.connect(self._on_pipette_picked)
        overlay.cancelled.connect(self._on_pipette_cancelled)
        overlay.destroyed.connect(lambda *_: self._show_after_pipette())
        overlay.show()
        overlay.raise_()
        overlay.activateWindow()
        overlay.setFocus(Qt.ActiveWindowFocusReason)

    def _show_after_pipette(self):
        self._active_overlay = None
        self._pipette_active = False
        if not self._resolved:
            self.show()

    def _on_pipette_picked(self, hexval: str):
        self._h, self._s, self._v = _hex_to_hsv(hexval)
        self._refresh_all()

    def _on_pipette_cancelled(self):
        pass

    def _on_cancel(self):
        if self._resolved:
            return
        self._resolved = True
        self.cancelled.emit()
        self.close()

    def _on_commit(self):
        if self._resolved:
            return
        self._resolved = True
        hexval = self._current_hex()
        self.committed.emit(hexval)
        self.close()

    def hideEvent(self, event):
        # Un clic EN DEHORS du popup ferme un widget Qt.Popup directement
        # via hide() (pas close()/closeEvent — verifie sur ce Qt : le
        # gestionnaire de popups de Qt appelle QWidget::hide() en
        # interne), d'ou hideEvent plutot que closeEvent ici — ce cas vaut
        # validation de la couleur affichee, plus intuitif qu'une
        # annulation silencieuse pendant qu'on ajustait un slider (voir la
        # remarque de tete de classe). _resolved evite un double signal
        # quand Valider/Annuler vient d'etre clique juste avant (close()
        # declenche aussi hide()) — et gere donc les DEUX chemins de
        # fermeture avec cette seule methode.
        if not self._resolved and not getattr(self, "_pipette_active", False):
            self._resolved = True
            hexval = self._current_hex()
            self.committed.emit(hexval)
        super().hideEvent(event)

    # -- redimensionnement (bord droit) --

    def _on_resize_edge(self, pos) -> bool:
        return self.width() - self._RESIZE_MARGIN <= pos.x() <= self.width()

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton and self._on_resize_edge(event.position().toPoint()):
            self._resizing = True
            self._resize_start_x = event.globalPosition().toPoint().x()
            self._resize_start_width = self.width()
            event.accept()
            return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        if self._resizing:
            delta = event.globalPosition().toPoint().x() - self._resize_start_x
            new_width = max(self._MIN_WIDTH, min(self._MAX_WIDTH, self._resize_start_width + delta))
            self.resize(new_width, self.height())
            event.accept()
            return
        cursor = Qt.SizeHorCursor if self._on_resize_edge(event.position().toPoint()) else Qt.ArrowCursor
        self.setCursor(cursor)
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        if self._resizing:
            self._resizing = False
            event.accept()
            return
        super().mouseReleaseEvent(event)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        # Le carre SV et les sliders TSL/RVB (voir _make_row, stretch=1)
        # suivent la nouvelle largeur ; la hauteur du carre reste fixe (pas
        # demandee par l'utilisateur, seule la precision HORIZONTALE des
        # sliders est en jeu).
        if hasattr(self, "pad"):
            self.pad.setFixedWidth(max(1, self.width() - 24))

    def show_near(self, widget: QWidget):
        self.adjustSize()
        pos = widget.mapToGlobal(QPoint(0, widget.height() + 4))
        screen = QApplication.screenAt(widget.mapToGlobal(QPoint(0, 0))) or QApplication.primaryScreen()
        if screen is not None:
            avail = screen.availableGeometry()
            pos.setX(max(avail.left(), min(pos.x(), avail.right() - self.width())))
            pos.setY(max(avail.top(), min(pos.y(), avail.bottom() - self.height())))
        self.move(pos)
        self.show()
        # Sans ca, sur Windows 11 le compositeur DWM impose son propre
        # arrondi par defaut a CETTE fenetre (frameless de premier niveau,
        # voir Qt.Popup ci-dessus) par-dessus le perimetre bien carre (0px)
        # deja peint cote QSS — et pas force ment de facon uniforme sur les
        # 4 coins (constate : parfois un seul coin visiblement arrondi,
        # voir la remarque de l'utilisateur, capture annotee a l'appui,
        # "pourquoi souvent tu mets des bordures juste sur 1 coin"). Meme
        # correctif que SettingsWindow._apply_panel_radius : redemander
        # explicitement DONOTROUND cote DWM (winId() n'existe qu'apres
        # show(), d'ou l'appel ICI et pas dans __init__).
        apply_dwm_frame(self, 0, M["panel_border"])

def _apply_stylesheet_cached(widget: QWidget, stylesheet: str) -> None:
    """Remplace un setStyleSheet direct : n'appelle rien si le CSS calcule
    est identique au dernier applique a CE widget. Qt ne fait pas ce
    filtrage lui-meme (un setStyleSheet(memes_octets) redeclenche quand
    meme tout le recalcul de style, y compris en cascade sur les
    descendants d'un widget qui en a beaucoup, mesure a plusieurs ms meme
    pour un tableau de taille moyenne — voir _PanelFrame, meme constat en
    pire pour la fenetre entiere). Utile partout ou une valeur reglable
    (rayon, couleur de tableau...) est reappliquee en boucle a chaque
    glisser d'un slider de couleur (voir SettingsWindow._refresh_dynamic_
    colors) alors qu'elle n'a en realite pas change : la plupart des
    tableaux/lignes stylises ici ne dependent PAS de la couleur en cours
    d'edition — voir la remarque de l'utilisateur sur la latence."""
    if getattr(widget, "_cached_stylesheet", None) == stylesheet:
        return
    widget._cached_stylesheet = stylesheet
    widget.setStyleSheet(stylesheet)

# Opacite d'un widget/champ INACTIF (voir _set_dimmed) — auparavant 0.35
# (voir _CellPaddingField/_CornerRadiusField.setLinked, seuls endroits a
# deja utiliser ce mecanisme) : encore trop percu comme "actif" — voir la
# remarque de l'utilisateur, "je veux que les parametres inactifs (grise)
# soit encore moins perceptibles ... generalise ca pour tous les elements
# inactif/grise".
_DIMMED_OPACITY = 0.2
# Opacite de TOUT element tire pendant un deplacement (lignes, colonnes, sous-cellules, titres, menus,
# lignes et colonnes de la fenetre principale) : demande de l'utilisateur, valable pour tout deplacement a venir.
DRAG_GHOST_OPACITY = 0.75

def _set_dimmed(widget: QWidget, dimmed: bool) -> None:
    """setEnabled(not dimmed) + un QGraphicsOpacityEffect a _DIMMED_OPACITY
    (PAS le simple estompage :disabled de Qt, trop discret sur des widgets
    peints a la main comme _MiniSlider/_Toggle/les pastilles de couleur,
    qui ne suivent de toute facon PAS QPalette) — MEME technique deja
    utilisee par _CellPaddingField/_CornerRadiusField.setLinked, desormais
    GENERALISEE a tout champ/bouton "grise" de cette fenetre (le bouton "Copier" retire depuis, voir _build_linked_sides_toggle,
    pastilles de _SideColorsField, sliders d'_OverrideSmoothingField...) —
    voir la remarque de l'utilisateur ci-dessus. Reutilise le graphics
    effect deja pose sur ce widget s'il y en a un (evite d'en empiler un
    nouveau a chaque appel)."""
    widget.setEnabled(not dimmed)
    effect = widget.graphicsEffect()
    if not isinstance(effect, QGraphicsOpacityEffect):
        effect = QGraphicsOpacityEffect(widget)
        widget.setGraphicsEffect(effect)
    effect.setOpacity(_DIMMED_OPACITY if dimmed else 1.0)

# Dimensions enregistrees des tableaux : {cle (voir _TableFrame.dimsKey): {"width": int, "cols": [..]}}.
_TABLE_DIMS: dict = {}

def _set_table_dims(dims: dict) -> None:
    _TABLE_DIMS.clear()
    _TABLE_DIMS.update(dims or {})

class _TableEdgeGrip(QWidget):
    """Poignee invisible sur la bordure droite d'un tableau : glisser change
    la largeur du tableau (curseur de redimensionnement au survol)."""

    WIDTH = 6

    def __init__(self, frame: "_TableFrame"):
        super().__init__(frame)
        self._frame = frame
        self._start_x = 0
        self._start_w = 0
        self._dragging = False
        self.setCursor(Qt.SizeHorCursor)
        self.setAttribute(Qt.WA_NoSystemBackground, True)

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            self._dragging = True
            self._start_x = event.globalPosition().toPoint().x()
            self._start_w = self._frame.width()
            event.accept()

    def mouseMoveEvent(self, event):
        if not self._dragging:
            return
        frame = self._frame
        parent = frame.parentWidget()
        avail = (parent.contentsRect().right() + 1 - frame.x()) if parent is not None else 4000
        width = self._start_w + event.globalPosition().toPoint().x() - self._start_x
        width = max(frame.minimumSizeHint().width(), min(width, avail))
        frame.setTableWidth(0 if width >= avail - 2 else width)
        event.accept()

    def mouseReleaseEvent(self, event):
        self._dragging = False
        event.accept()

class _TableFrame(QWidget):
    """Cadre exterieur complet (perimetre 1px) d'un tableau — entete et
    lignes empilees a l'interieur, separees seulement par un filet
    horizontal (voir _table_header/_table_row), jamais par des boites
    individuelles : un tableau bien "ferme" (un seul rectangle), pas une
    pile de rectangles accoles (voir la remarque de l'utilisateur, capture
    a l'appui — les tableaux Polices/Geometrie avaient chacun leur propre
    filet gauche/droite/bas, un empilement qui pouvait paraitre "ouvert").

    Suit en direct le slider Geometrie > Tableaux > Coins arrondis (voir
    setRadius), mais UNIQUEMENT pour son propre filet 1px : l'entete et les
    lignes a l'interieur gardent chacune leur propre fond plein (couleurs
    alternees, WA_StyledBackground) que ce border-radius ne touche jamais
    (un border-radius QSS n'arrondit que le PROPRE fond/bordure du widget,
    jamais celui de ses enfants). Une premiere version decoupait tout le
    contenu au masque (QRegion/setMask) pour compenser — mais un masque est
    un decoupage BINAIRE, non anti-aliase : le filet du cadre (lui bien
    arrondi en douceur par le QSS) se retrouvait recoupe au pixel pres par
    ce masque grossier, d'ou des bordures qui ne suivaient plus vraiment la
    courbe (voir la remarque de l'utilisateur, capture a l'appui). Corrige
    en arrondissant plutot CHAQUE piece a l'endroit exact ou elle touche un
    coin (les coins hauts de l'entete/de la premiere ligne si l'entete est
    absente, les coins bas de la derniere ligne — voir
    SettingsWindow._apply_table_radius et ses homologues par tableau), qui
    reste un rendu QSS natif, donc aussi lisse que le filet du cadre."""

    # Une dimension du tableau a change (largeur du tableau, d'une colonne, d'une
    # cellule...) : la fenetre qui le souhaite enregistre alors tout de suite.
    dimsChanged = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("TableFrame")
        self.setAttribute(Qt.WA_StyledBackground, True)
        self._radius = 0
        # Bordure (voir setBorder/Tableaux > Bordure) : valeurs de depart
        # identiques a l'ancien "1px solid" fixe code en dur ici, pour ne
        # rien changer visuellement tant que SettingsWindow._apply_table_
        # border n'a pas encore rejoue les reglages reels (1er appel, meme
        # convention que _ColumnPreview._border_enabled/_border_colors).
        self._border_enabled = {k: True for k in ("top", "right", "bottom", "left")}
        self._border_colors = {k: M["panel_border"] for k in ("top", "right", "bottom", "left")}
        self._border_thickness = 1
        self._dims_applied = False
        self._grip = _TableEdgeGrip(self)
        self._refresh_style()

    # -- Largeur du tableau (bordure droite agrippable) + dimensions enregistrees --

    # Colonnes libres (tableaux de la v2) : la largeur du tableau = somme de ses colonnes, posee par
    # `_fit_columns` (fourni par le tableau) ; plus de largeur imposee ni de bordure droite a tirer
    # (c'est la bordure de la derniere colonne). `_legacy_dims` convertit d'anciennes dimensions.
    _fit_columns = None
    _legacy_dims = None

    def setWidthResizable(self, enabled: bool):
        self._grip.setVisible(bool(enabled) and self._fit_columns is None)

    def tableWidth(self) -> int:
        """Largeur imposee (0 = pleine largeur disponible)."""
        w = self.maximumWidth()
        return 0 if w >= 16777215 else w

    def setTableWidth(self, width: int):
        if self._fit_columns is not None:
            self._align_left(True)
            self._fit_columns()
            self.dimsChanged.emit()
            return
        width = int(width) if width and int(width) > 0 else 0
        self.setMaximumWidth(width or 16777215)
        self._align_left(bool(width))
        self.updateGeometry()
        self.dimsChanged.emit()

    def sizeHint(self):
        hint = super().sizeHint()
        width = self.tableWidth()
        if width:
            hint.setWidth(width)
        return hint

    def _align_left(self, on: bool):
        """Un tableau plus etroit que sa zone se colle a GAUCHE (au niveau du
        titre de sa section) au lieu d'etre centre par le layout."""
        flags = Qt.AlignLeft if on else Qt.Alignment()

        def apply(layout) -> bool:
            if layout is None:
                return False
            for i in range(layout.count()):
                item = layout.itemAt(i)
                if item.widget() is self:
                    item.setAlignment(flags)
                    return True
                if apply(item.layout()):
                    return True
            return False

        parent = self.parentWidget()
        if parent is not None:
            apply(parent.layout())

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._grip.setGeometry(self.width() - _TableEdgeGrip.WIDTH, 0, _TableEdgeGrip.WIDTH, self.height())
        self._grip.raise_()

    # Cle imposee (tableaux LIES qui partagent les memes dimensions, voir la fenetre v2) ; sinon
    # la cle se deduit des titres.
    _dims_key: str | None = None

    def dimsKey(self) -> str:
        """Cle stable : titres des sections ancetres + rang parmi les tableaux de la section."""
        if self._dims_key:
            return self._dims_key
        titles = []
        node = self.parentWidget()
        owner = None
        while node is not None:
            title = getattr(node, "_title_text", None)
            if title:
                titles.append(title)
                owner = owner or node
            node = node.parentWidget()
        rank = 0
        if owner is not None:
            frames = [f for f in owner.findChildren(_TableFrame)]
            rank = frames.index(self) if self in frames else 0
        return "/".join(reversed(titles)) + f"#{rank}"

    def _dims_children(self):
        head, resizer = None, None
        for child in self.findChildren(QWidget):
            if head is None and hasattr(child, "setColumnWidths"):
                head = child
            if resizer is None and getattr(child, "_flat_resizer", None) is not None:
                resizer = child._flat_resizer
        return head, resizer

    def collectDims(self) -> dict:
        head, resizer = self._dims_children()
        dims: dict = {"width": self.tableWidth()}
        if head is not None:
            dims["cols"] = head.columnWidths()
        elif resizer is not None:
            dims["cols"] = [resizer.width()]
        extra = getattr(self, "_extra_dims", None)     # tableaux a cellules : justifications, cellules divisees
        if extra is not None:
            dims.update(extra.collect())
        return dims

    def applyDims(self, dims: dict):
        if self._legacy_dims is not None:
            dims = self._legacy_dims(dims)
        head, resizer = self._dims_children()
        cols = dims.get("cols") or []
        if head is not None and cols:
            head.setColumnWidths(cols)
        elif resizer is not None and cols:
            resizer.setWidth(int(cols[0]))
        extra = getattr(self, "_extra_dims", None)
        if extra is not None:
            extra.apply(dims)
        self.setTableWidth(int(dims.get("width", 0) or 0))

    def showEvent(self, event):
        super().showEvent(event)
        if not self._dims_applied:
            self._dims_applied = True
            dims = _TABLE_DIMS.get(self.dimsKey())
            if dims:
                self.applyDims(dims)
            look = ELEMENT_LOOKS.get(f"table:{self.dimsKey()}")
            if look:
                from fm_theme.layout import set_table_look
                set_table_look(self, look)
            if PART_LOOKS.get(self.dimsKey()):
                from fm_theme.layout import apply_part_looks
                apply_part_looks(self)
            # Reglages > Tableaux > Ombres : sous-couche voisine (l'ombre deborde du tableau).
            attach_shadow(self, lambda: _TABLE_SHADOW["look"], lambda: self._radius)
            # Branche APRES la restauration (elle ne doit pas se reenregistrer) : une
            # colonne tiree a la main previent la fenetre.
            head, resizer = self._dims_children()
            if head is not None:
                head.resized.connect(lambda *_a: self.dimsChanged.emit())
            elif resizer is not None:
                resizer.resized.connect(lambda *_a: self.dimsChanged.emit())

    def _refresh_style(self):
        t = self._border_thickness

        def edge(side: str) -> str:
            # "0px solid transparent", PAS "none" — meme raison que
            # column_frame_qss/header_qss : "none" ferait deborder le fond
            # carre au coin arrondi, la ou une bordure a epaisseur nulle
            # (mais toujours "solid") reste correctement decoupee par le
            # border-radius du meme cote.
            # Tableau coupe (« Split au-dessus ») : la bordure est peinte partie par partie (paintEvent).
            # Les espaceurs, pas _split_gaps() : juste apres la coupe, leur geometrie est encore nulle (mise
            # en page pas faite) et la bordure QSS restait, visible a gauche / a droite dans l'espace (signale).
            if t <= 0 or not self._border_enabled.get(side, True) or self._split_spacers:
                return "0px solid transparent"
            return f"{t}px solid {self._border_colors.get(side, M['panel_border'])}"

        _apply_stylesheet_cached(
            self,
            f"#TableFrame {{ border-top: {edge('top')}; border-right: {edge('right')}; "
            f"border-bottom: {edge('bottom')}; border-left: {edge('left')}; "
            f"border-radius: {self._radius}px; }}"
        )

    def setRadius(self, radius: int):
        self._radius = max(0, int(radius))
        self._refresh_style()

    # -- « Split au-dessus » : tableau coupe en parties separees par un espace (settings_cells) --
    _split_spacers: list = []

    def _split_gaps(self) -> list:
        """(haut, bas) de chaque espace de coupe, en coordonnees du cadre (vide : pas de coupe)."""
        gaps = []
        for item in self._split_spacers:
            geo = item.geometry()
            if geo.height() > 0:
                gaps.append((geo.top(), geo.bottom() + 1))
        return sorted(gaps)

    def paintEvent(self, event):
        super().paintEvent(event)
        gaps = self._split_gaps()
        if not gaps:
            return
        # Une partie par morceau : sa bordure complete et ses 4 coins arrondis ; la bordure deborde
        # d'un pixel dans l'espace (le contenu est en retrait de 1 px, voir _table_frame).
        t = self._border_thickness
        on = {k: bool(self._border_enabled.get(k, True)) and t > 0 for k in ("top", "right", "bottom", "left")}
        corners = {c: self._radius for c in ("top_left", "top_right", "bottom_right", "bottom_left")}
        tops = [0] + [bottom - 1 for _top, bottom in gaps]
        bottoms = [top + 1 for top, _bottom in gaps] + [self.height()]
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing, True)
        for top, bottom in zip(tops, bottoms):
            if bottom - top <= 3:               # espace en tete (texte au-dessus de la 1re ligne) : pas de partie
                continue
            _paint_bordered_vector(p, QRect(0, top, self.width(), bottom - top), corners, on, t,
                                   self._border_colors, None)
        p.end()

    def setBorder(self, enabled: dict, colors: dict, thickness: int):
        """Tableaux > Bordure (voir _ToggleSideColorsField, MEME widget que
        Toggles > Cadre/Coche > Bordure et Colonnes > Bordure) — voir la
        remarque de l'utilisateur, "ajoute dans la section tableau un
        parametre bordure comme celui des toggles"."""
        self._border_enabled = {k: bool(enabled.get(k, True)) for k in ("top", "right", "bottom", "left")}
        self._border_colors = {k: colors.get(k) or M["panel_border"] for k in ("top", "right", "bottom", "left")}
        self._border_thickness = max(0, int(thickness))
        self._refresh_style()

def _table_frame() -> tuple[QWidget, QVBoxLayout]:
    frame = _TableFrame()
    layout = QVBoxLayout(frame)
    # Marge de 1px (= l'epaisseur du filet de #TableFrame), PAS 0 : a marge
    # nulle, l'entete/les lignes (chacun avec son propre fond peint via
    # WA_StyledBackground) recouvrent exactement le filet du cadre et le
    # rendent invisible — meme bug, meme correctif que #Panel dans
    # SettingsWindow.__init__ (voir la remarque de l'utilisateur, capture
    # a l'appui : le cadre etait bel et bien absent a l'ecran).
    layout.setContentsMargins(1, 1, 1, 1)
    layout.setSpacing(0)
    return frame, layout

# Bordures interieures des tableaux (voir SettingsWindow, Tableaux > Bordure
# interieure H/V) : lues par _restyle_table_row/_restyle_table_head (H) et par
# _TableRow/_ResizableTableHeader.paintEvent (V).
_TABLE_INNER_BORDER: dict = {
    "h": {"enabled": True, "color": "", "thickness": 1},
    "v": {"enabled": False, "color": "", "thickness": 1},
}

def _set_table_inner_border(h: tuple, v: tuple) -> None:
    """h, v : (actif, couleur hex, epaisseur)."""
    for key, (enabled, color, thickness) in (("h", h), ("v", v)):
        _TABLE_INNER_BORDER[key] = {"enabled": bool(enabled), "color": color, "thickness": max(0, int(thickness))}

def _inner_h_edge() -> str:
    """Filet horizontal interieur en QSS ("0px solid transparent" plutot que
    "none", meme raison que _TableFrame._refresh_style)."""
    h = _TABLE_INNER_BORDER["h"]
    if h["thickness"] <= 0 or not h["enabled"]:
        return "0px solid transparent"
    return f"{h['thickness']}px solid {h['color'] or M['panel_border']}"

def _paint_inner_vlines(widget: QWidget, xs: list[int]) -> None:
    """Filets verticaux interieurs de `widget` aux abscisses `xs` (bords
    gauches des cellules, hors premiere colonne : jamais ceux des extremites)."""
    v = _TABLE_INNER_BORDER["v"]
    if not v["enabled"] or v["thickness"] <= 0 or not xs:
        return
    p = QPainter(widget)
    color = QColor(v["color"] or M["panel_border"])
    for x in xs:
        p.fillRect(x - v["thickness"] // 2, 0, v["thickness"], widget.height(), color)
    p.end()

class _TableRow(QWidget):
    """Ligne de tableau : fond/filets H en QSS (voir _restyle_table_row), filets
    V peints ici entre ses cellules (widgets nommes "TableCell", voir
    _table_cell) ou a `_v_boundary()` (tableaux libelle/controle)."""

    def event(self, event):
        handled = super().event(event)
        # Les filets V sont peints a la position des cellules : apres un
        # redimensionnement de colonne, le layout deplace les cellules APRES
        # coup, et Qt ne repeint que leurs propres rectangles (jamais le filet,
        # dans l'espacement entre deux). On repeint donc toute la ligne une fois
        # le layout passe (le layout a deja traite LayoutRequest ici).
        if event.type() in (QEvent.LayoutRequest, QEvent.Resize):
            self.update()
        return handled

    def paintEvent(self, event):
        super().paintEvent(event)
        self._paint_part_backgrounds()
        self._paint_row_mark()
        head = getattr(self, "_sel_head", None)
        if head is not None and head._selected:
            p = QPainter(self)
            for i, (left, edge) in enumerate(head._column_spans()):
                if i in head._selected:
                    p.fillRect(left, 0, edge - left, self.height(), _selection_color(40))
            p.end()
        boundary = getattr(self, "_v_boundary", None)
        if boundary is not None:
            xs = [boundary()]
        else:
            cells = sorted((c for c in self.children()
                            if isinstance(c, QWidget) and c.objectName() == "TableCell"),
                           key=lambda c: c.x())
            xs = [c.x() for c in cells[1:]]
        _paint_inner_vlines(self, xs)

def _table_row_paint_part_backgrounds(self):
    """Fond PROPRE d'une cellule (« Override settings » > cellule / ligne / colonne, `_part_look`) :
    toute la hauteur de la ligne, sous le filet du haut, dans les coins arrondis du bas."""
    cells = [c for c in self.children() if isinstance(c, QWidget) and c.objectName() == "TableCell"
             and (getattr(c, "_part_look", None) or {}).get("bg")]
    if not cells:
        return
    h = _TABLE_INNER_BORDER["h"]
    top = 0 if getattr(self, "_first_row", True) or not h["enabled"] else h["thickness"]
    p = QPainter(self)
    radius = getattr(self, "_bottom_radius", 0)
    if radius:
        path = QPainterPath()
        path.setFillRule(Qt.WindingFill)
        path.addRoundedRect(QRectF(self.rect()), radius, radius)
        path.addRect(QRectF(0, 0, self.width(), max(0, self.height() - radius)))
        p.setClipPath(path)
    for cell in cells:
        p.fillRect(QRect(cell.x(), top, cell.width(), self.height() - top), QColor(cell._part_look["bg"]))
    p.end()


_TableRow._paint_part_backgrounds = _table_row_paint_part_backgrounds


def set_row_mark(widget: QWidget, look: dict | None) -> None:
    """Ligne d'un tableau MARQUEE (ex. fenetre des filtres : lignes ou un filtre agit) : `look` =
    {"bg": couleur ou None, "sides": {cote: bool}, "colors": {cote: couleur}, "thickness": px,
    "radius": {coin: px} (facultatif), "margin": {cote: px} (facultatif, retrait dans la ligne)} ; None =
    plus de marque. `widget` : la ligne ou un widget qu'elle contient."""
    row = widget
    while row is not None and not isinstance(row, _TableRow):
        row = row.parentWidget()
    if row is None or getattr(row, "_mark_look", None) == look:
        return
    row._mark_look = look
    row.update()


def _table_row_paint_mark(self):
    """Marque de la ligne (set_row_mark) : fond sur toute la ligne, sous le filet du haut, puis bordures
    des cotes allumes, a l'interieur de la ligne."""
    look = getattr(self, "_mark_look", None)
    if not look:
        return
    h = _TABLE_INNER_BORDER["h"]
    top = 0 if getattr(self, "_first_row", True) or not h["enabled"] else h["thickness"]
    margin = look.get("margin") or {}
    rect = QRect(0, top, self.width(), self.height() - top).adjusted(
        margin.get("left", 0), margin.get("top", 0), -margin.get("right", 0), -margin.get("bottom", 0))
    if rect.width() <= 0 or rect.height() <= 0:
        return
    p = QPainter(self)
    radius = getattr(self, "_bottom_radius", 0)
    if radius:
        path = QPainterPath()
        path.setFillRule(Qt.WindingFill)
        path.addRoundedRect(QRectF(self.rect()), radius, radius)
        path.addRect(QRectF(0, 0, self.width(), max(0, self.height() - radius)))
        p.setClipPath(path)
    t = max(0, int(look.get("thickness") or 0))
    sides, colors = look.get("sides") or {}, look.get("colors") or {}
    corners = _radius_dict(look.get("radius") or 0)
    if any(corners.values()):
        # Marque arrondie : fond = chemin arrondi ; bordure = anneau (chemin moins le meme retire de
        # l'epaisseur sur les cotes allumes), chaque cote dans sa couleur, jusqu'aux diagonales des coins.
        p.setRenderHint(QPainter.Antialiasing, True)
        outer = _rounded_rect_path(rect, corners)
        if look.get("bg"):
            p.fillPath(outer, QColor(look["bg"]))
        if t and any(sides.get(s) for s in ("left", "top", "right", "bottom")):
            inner_rect = rect.adjusted(t if sides.get("left") else 0, t if sides.get("top") else 0,
                                       -t if sides.get("right") else 0, -t if sides.get("bottom") else 0)
            ring = outer.subtracted(_rounded_rect_path(inner_rect, {k: max(0, v - t) for k, v in corners.items()}))                 if inner_rect.width() > 0 and inner_rect.height() > 0 else outer
            r = QRectF(rect)
            c = r.center()
            wedges = {"top": (r.topLeft(), r.topRight()), "right": (r.topRight(), r.bottomRight()),
                      "bottom": (r.bottomRight(), r.bottomLeft()), "left": (r.bottomLeft(), r.topLeft())}
            d = max(r.width(), r.height())
            for side, (a, b) in wedges.items():
                if not sides.get(side):
                    continue
                wedge = QPainterPath()                    # secteur du cote : centre -> ses 2 coins, prolonge
                wedge.moveTo(c)
                wedge.lineTo(c + (a - c) * (1 + d))
                wedge.lineTo(c + (b - c) * (1 + d))
                wedge.closeSubpath()
                p.fillPath(ring.intersected(wedge), QColor(colors.get(side) or "#808080"))
        p.end()
        return
    if look.get("bg"):
        p.fillRect(rect, QColor(look["bg"]))
    if t:
        bands = {"top": QRect(rect.left(), rect.top(), rect.width(), t),
                 "bottom": QRect(rect.left(), rect.bottom() - t + 1, rect.width(), t),
                 "left": QRect(rect.left(), rect.top(), t, rect.height()),
                 "right": QRect(rect.right() - t + 1, rect.top(), t, rect.height())}
        for side, band in bands.items():
            if sides.get(side):
                p.fillRect(band, QColor(colors.get(side) or "#808080"))
    p.end()


_TableRow._paint_row_mark = _table_row_paint_mark


def _restyle_table_row(row: QWidget, bg: str, first: bool, top_radius: int = 0, bottom_radius: int = 0):
    """(Re)applique le fond/filet/coins d'une ligne de donnees. `top_radius`
    n'est utile que pour la toute premiere ligne d'un tableau SANS entete
    (elle touche alors elle-meme le coin haut du cadre — voir la table
    Entetes) ; `bottom_radius` seulement pour la toute derniere ligne (elle
    touche toujours le coin bas du cadre, entete ou pas) — voir
    SettingsWindow._apply_table_radius et homologues, qui recalculent ces
    deux valeurs a chaque cran du slider Geometrie > Tableaux."""
    # « Split au-dessus » (settings_cells.apply_row_splits) : la ligne ouvre une nouvelle partie du tableau
    # (pas de filet au-dessus, coins hauts arrondis) ; celle d'avant la ferme (coins bas arrondis). Lu ICI,
    # par toute (re)application du style des lignes, pour que le split survive a tout restylage.
    frame = row.parentWidget()
    frame_radius = getattr(frame, "_radius", 0) if isinstance(frame, _TableFrame) else 0
    if getattr(row, "_split_above", False):
        first, top_radius = True, max(top_radius, frame_radius)
    if getattr(row, "_split_below", False):
        bottom_radius = max(bottom_radius, frame_radius)
    row._first_row, row._bottom_radius = first, bottom_radius      # fonds propres des cellules
    border = "" if first else f"border-top: {_inner_h_edge()};"
    _apply_stylesheet_cached(
        row,
        f"#TableRow {{ background: {bg}; {border} "
        f"border-top-left-radius: {top_radius}px; border-top-right-radius: {top_radius}px; "
        f"border-bottom-left-radius: {bottom_radius}px; border-bottom-right-radius: {bottom_radius}px; }}",
    )

# ==========================================================================
# Section "Entetes" — hauteur / couleur (choisie parmi les 8 pastilles
# semantiques) / rayon des angles / cadre par cote.
# ==========================================================================

_SLOT_LABELS = {slot: label for slot, _real, label in SEMANTIC_COLOR_SLOTS}

def _slot_of(value: str) -> str:
    """Nom de la pastille d'une valeur « @slot » ou « @slot/75 » (opacite)."""
    from fm_theme.style import split_color_ref
    return split_color_ref(value)[0][1:]


class _AppOrCustomColorField(QWidget):
    """GABARIT "couleur" (voir la remarque de l'utilisateur, "TOUTES LES
    LIGNES COULEUR ... Toggles pour choix de couleur Appli ou couleur
    personnalisee. les textes des toggles doivent etre devant les toggles
    correspondant et etre 'Couleur application' et 'Couleur systeme' ...
    les items de la liste deroulante des couleurs applications devront
    etre dans l'ordre alphabetique") — MEME mecanique exclusive que
    _DualFontSelectField (app/systeme) transposee aux couleurs : toggle
    "Couleur application" + liste deroulante des pastilles semantiques
    (SEMANTIC_COLOR_SLOTS, triees par LABEL alphabetique pour l'affichage
    seulement — la liste partagee elle-meme reste dans son ordre de
    lecture 2 colonnes, voir sa remarque de tete dans app_style.py) OU
    toggle "Couleur systeme" + pastille cliquable ouvrant le popup HSL/RVB/
    hex habituel (_ColorPickerPopup) — utilisee par _SideColorsField
    (bordures de Toggles/Sliders).

    Valeur stockee (voir value()/setValue()) : une chaine hex "#rrggbb"
    (couleur personnalisee) OU "@<slot>" (reference a une pastille
    semantique) — format INCHANGE, retro-compatible avec les presets
    existants."""

    changed = Signal(str)

    def __init__(self, value: str, colors: dict, swatch_size: int = 20, title: str = "Couleur", parent=None):
        super().__init__(parent)
        self._value = value
        self._colors = colors
        self._title = title
        self._before_pick = value
        self._popup: _ColorPickerPopup | None = None
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)

        self._slot_options = sorted(SEMANTIC_COLOR_SLOTS, key=lambda t: t[2])
        self._slot_to_label = {slot: label for slot, _real, label in self._slot_options}
        self._label_to_slot = {label: slot for slot, _real, label in self._slot_options}
        labels = [label for _slot, _real, label in self._slot_options]

        is_slot = value.startswith("@")

        app_label = QLabel("Couleur application")
        _set_text_role(app_label, "choice_label")
        layout.addWidget(app_label)
        self.app_toggle = _Toggle(is_slot, show_label=False)
        layout.addWidget(self.app_toggle)
        current_label = self._slot_to_label.get(_slot_of(value), labels[0]) if is_slot else labels[0]
        self.app_field = _SelectField(labels, current_label, width=170)
        layout.addWidget(self.app_field)

        system_label = QLabel("Couleur systeme")
        _set_text_role(system_label, "choice_label")
        layout.addWidget(system_label)
        self.system_toggle = _Toggle(not is_slot, show_label=False)
        layout.addWidget(self.system_toggle)
        self.swatch = _ColorSwatchButton()
        self.swatch.setFixedSize(swatch_size, swatch_size)
        self.swatch.clicked.connect(self._open_custom_picker)
        layout.addWidget(self.swatch)

        self.app_toggle.toggled.connect(self._on_app_toggled)
        self.system_toggle.toggled.connect(self._on_system_toggled)
        self.app_field.changed.connect(self._on_app_field_changed)
        self._refresh_dim()
        self._refresh()

    def _is_slot(self) -> bool:
        return self._value.startswith("@")

    def _resolved_hex(self) -> str:
        return _resolve_color_value(self._value, self._colors)

    def _refresh(self):
        hexval = self._resolved_hex()
        self.swatch.setColorHex(hexval)
        self.swatch.setToolTip(_SLOT_LABELS.get(_slot_of(self._value), hexval) if self._is_slot() else hexval)

    def _refresh_dim(self):
        _set_dimmed(self.app_field, not self.app_toggle.isChecked())
        _set_dimmed(self.swatch, not self.system_toggle.isChecked())

    def _on_app_toggled(self, checked: bool):
        if checked:
            self.system_toggle.blockSignals(True)
            self.system_toggle.setChecked(False)
            self.system_toggle.blockSignals(False)
        elif not self.system_toggle.isChecked():
            # Au moins l'un des 2 doit rester actif (voir _DualFontSelectField,
            # MEME raison).
            self.system_toggle.blockSignals(True)
            self.system_toggle.setChecked(True)
            self.system_toggle.blockSignals(False)
        self._refresh_dim()
        if checked:
            self._select_slot(self._label_to_slot[self.app_field.value()])
        else:
            self.changed.emit(self._value)

    def _on_system_toggled(self, checked: bool):
        if checked:
            self.app_toggle.blockSignals(True)
            self.app_toggle.setChecked(False)
            self.app_toggle.blockSignals(False)
            if self._is_slot():
                # Bascule vers "Couleur systeme" : fige la couleur RESOLUE
                # courante comme point de depart personnalise (sinon la
                # valeur stockee resterait une reference "@slot" alors que
                # le toggle affiche desormais "systeme" — etat incoherent).
                self._value = self._resolved_hex()
                self._refresh()
        elif not self.app_toggle.isChecked():
            self.app_toggle.blockSignals(True)
            self.app_toggle.setChecked(True)
            self.app_toggle.blockSignals(False)
        self._refresh_dim()
        self.changed.emit(self._value)

    def _on_app_field_changed(self, label: str):
        if self.app_toggle.isChecked():
            self._select_slot(self._label_to_slot[label])

    def _select_slot(self, slot: str):
        self._value = f"@{slot}"
        self._refresh()
        self.changed.emit(self._value)

    def _open_custom_picker(self):
        if not self.system_toggle.isChecked():
            return
        self._before_pick = self._value
        popup = _ColorPickerPopup(self._resolved_hex(), self._title, self)
        self._popup = popup
        popup.colorChanged.connect(self._apply_custom_live)
        popup.committed.connect(self._apply_custom_live)
        popup.cancelled.connect(lambda: self._apply_custom_live(self._before_pick))
        popup.show_near(self.swatch)

    def _apply_custom_live(self, value: str):
        self._value = value
        self._refresh()
        self.changed.emit(self._value)

    def value(self) -> str:
        return self._value

    def setValue(self, value: str):
        self._value = value
        is_slot = value.startswith("@")
        self.app_toggle.blockSignals(True)
        self.system_toggle.blockSignals(True)
        self.app_toggle.setChecked(is_slot)
        self.system_toggle.setChecked(not is_slot)
        self.app_toggle.blockSignals(False)
        self.system_toggle.blockSignals(False)
        if is_slot and _slot_of(value) in self._slot_to_label:
            self.app_field.setValue(self._slot_to_label[_slot_of(value)])
        self._refresh_dim()
        self._refresh()

    def refresh_colors(self, colors: dict):
        """A appeler quand la page Couleurs change (voir SettingsWindow.
        _on_colors_changed) : une pastille en mode "App" (voir _is_slot)
        doit suivre EN DIRECT la couleur reelle de sa pastille semantique."""
        self._colors = colors
        self._refresh()


class _ShortcutField(QLineEdit):
    """Zone de saisie d'un raccourci clavier : cliquer dedans puis taper la touche (avec ses
    modificateurs) ; Retour arriere / Suppr = aucun raccourci, Echap = quitter sans changer.
    Valeur = texte portable de QKeySequence (« Ctrl+D », « F »), `changed` a chaque modification.
    Habillee comme les autres zones de saisie (suit Geometrie > Zones de saisie)."""

    changed = Signal()
    _MODIFIER_KEYS = (Qt.Key_Control, Qt.Key_Shift, Qt.Key_Alt, Qt.Key_Meta, Qt.Key_AltGr)

    def __init__(self, value: str = "", width: int = 120):
        super().__init__()
        self.setReadOnly(True)                  # pas de curseur de texte : on capte la touche
        self.setAlignment(Qt.AlignCenter)
        self.setFixedSize(width, 25)
        self.setPlaceholderText("aucun")
        self.setToolTip("Cliquer puis taper le raccourci (Retour arrière : aucun)")
        self.setContextMenuPolicy(Qt.NoContextMenu)
        self._value = ""
        self._setting = False
        self._radius = _input_radius()
        _register_input(self)
        self._restyle()
        self.set_value(value)
        # Texte pose autrement que par la frappe (code, tests) : lu comme le nouveau raccourci.
        self.textChanged.connect(self._on_text_changed)

    def setRadius(self, radius: int):           # suit Geometrie > Zones de saisie
        self._radius = radius
        self._restyle()

    def _restyle(self):
        self.setStyleSheet(
            f"QLineEdit {{ background: {input_bg()}; {input_border_decl()} "
            f"border-radius: {self._radius}px; color: {M['value_fg']}; padding: 0 6px; }}"
            f"QLineEdit:focus {{ border: 1px solid {M['accent_border']}; }}")

    def value(self) -> str:
        return self._value

    def set_value(self, value: str):
        from PySide6.QtGui import QKeySequence
        sequence = QKeySequence(str(value or ""))
        self._value = sequence.toString(QKeySequence.PortableText)
        self._setting = True
        try:
            self.setText(sequence.toString(QKeySequence.NativeText))
        finally:
            self._setting = False

    def _on_text_changed(self, text: str):
        if self._setting:
            return
        from PySide6.QtGui import QKeySequence
        value = QKeySequence(text.strip()).toString(QKeySequence.PortableText)
        if value != self._value:
            self._value = value
            self.changed.emit()

    def keyPressEvent(self, event):
        from PySide6.QtCore import QKeyCombination
        from PySide6.QtGui import QKeySequence
        key, mods = event.key(), event.modifiers() & ~Qt.KeypadModifier
        if key in self._MODIFIER_KEYS or key == Qt.Key_unknown:
            return
        if key == Qt.Key_Escape and not mods:
            self.clearFocus()
            return
        if key in (Qt.Key_Backspace, Qt.Key_Delete) and not mods:
            value = ""
        else:
            value = QKeySequence(QKeyCombination(mods, Qt.Key(key))).toString(QKeySequence.PortableText)
        if value != self._value:
            self.set_value(value)
            self.changed.emit()

    def event(self, event):
        # Tab et Maj+Tab sont des raccourcis possibles : ne pas les laisser deplacer le clavier.
        if event.type() == QEvent.KeyPress and event.key() in (Qt.Key_Tab, Qt.Key_Backtab):
            self.keyPressEvent(event)
            return True
        return super().event(event)


# ==========================================================================
# Ombres (lignes « Ombres » : lier les 4 | G | H | B | D | Taille — meme gabarit que les Bordures)
# ==========================================================================
# Cles d'une ligne Ombres de prefixe P : `P_enabled` (cotes actifs), `P` (couleur par cote, opacite
# comprise), `P_size` (taille en px), `P_enabled_linked`. Une ombre se dessine SOUS l'element, hors de
# sa forme (arrondie comme lui), cote par cote : chaque cote actif la pousse de ce cote-la (tous les
# cotes = halo tout autour). Rendu : un petit MODELE (forme minimale + ombre) calcule une fois et garde
# en cache, pose en 9 morceaux (coins tels quels, bords etires) : n'importe quelle taille, sans calcul
# (planche, image qui vole, image zoomee...). Ombre douce = couches empilees en addition (profil en S,
# _shadow_profile), forme videe ensuite (rien sous une image transparente).

_SHADOW_SIDES = ("top", "right", "bottom", "left")
_CORNER_SIDES = {"top_left": ("top", "left"), "top_right": ("top", "right"),
                 "bottom_right": ("bottom", "right"), "bottom_left": ("bottom", "left")}
_SHADOW_CACHE: dict = {}
_SHADOW_CACHE_MAX = 96
_SHADOW_DEFAULT = "#8c000000"
_TABLE_SHADOW: dict = {"look": None}     # Reglages > Tableaux > Ombres (tous les tableaux des reglages)


def shadow_keys(prefix: str) -> tuple:
    """(cle des cotes, cle des couleurs, cle de la taille) d'une ligne Ombres."""
    return f"{prefix}_enabled", prefix, f"{prefix}_size"


def shadow_look(values: dict, prefix: str, resolve=None) -> dict | None:
    """Ombre reglee par la ligne de prefixe `prefix` dans `values`, ou None (aucun cote actif, taille
    nulle). `resolve(valeur)` -> hex : references « @pastille » (defaut : valeur telle quelle)."""
    enabled_key, colors_key, size_key = shadow_keys(prefix)
    sides = _coerce_side_enabled_local(values.get(enabled_key))
    try:
        size = max(0, int(values.get(size_key, 0) or 0))
    except (TypeError, ValueError):
        size = 0
    if size <= 0 or not any(sides.values()):
        return None
    raw = values.get(colors_key)
    colors = {}
    for side in _SHADOW_SIDES:
        value = raw.get(side) if isinstance(raw, dict) else raw
        value = value or _SHADOW_DEFAULT
        if resolve is not None:
            value = resolve(value) or _SHADOW_DEFAULT
        colors[side] = QColor(value).name(QColor.NameFormat.HexArgb)
    return {"on": sides, "colors": colors, "size": size}


def _coerce_side_enabled_local(value) -> dict:
    if isinstance(value, dict):
        return {k: bool(value.get(k, False)) for k in _SHADOW_SIDES}
    return {k: bool(value) for k in _SHADOW_SIDES}


def _shadow_radius(radius) -> dict:
    if isinstance(radius, dict):
        return {k: max(0, int(round(float(radius.get(k, 0) or 0)))) for k in _CORNERS}
    return {k: max(0, int(round(float(radius or 0)))) for k in _CORNERS}


def _shadow_profile(t: float) -> float:
    """Opacite de l'ombre a la fraction `t` de sa taille (1 au bord de la forme, 0 au bout) : courbe en
    S (proche d'un flou gaussien), plus etalee qu'une decroissance rapide qui la reduisait a un liseré."""
    t = max(0.0, min(1.0, t))
    return 1.0 - t * t * (3.0 - 2.0 * t)


def _shadow_reach(radius: dict, look: dict) -> int:
    """Distance au bord ou l'ombre cesse de varier le long d'un cote (coin arrondi, estompage vers un cote
    eteint) : les 9 morceaux coupent au-dela, le milieu etire y est constant."""
    return max(max(radius.values()) if radius else 0, look["size"])


def _render_shadow(inner_w: int, inner_h: int, radius: dict, look: dict, dpr: float) -> QPixmap:
    """Ombre d'une forme `inner_w` x `inner_h` (px logiques, arrondie `radius`) : pixmap de la forme plus
    `look["size"]` px de marge tout autour, forme videe."""
    from PySide6.QtGui import QImage
    margin = look["size"]
    width, height = inner_w + 2 * margin, inner_h + 2 * margin
    out = QImage(max(1, round(width * dpr)), max(1, round(height * dpr)), QImage.Format_ARGB32_Premultiplied)
    out.setDevicePixelRatio(dpr)
    out.fill(Qt.transparent)
    shape = QRectF(margin, margin, inner_w, inner_h)
    steps = max(1, round(margin * dpr))
    composer = QPainter(out)
    composer.setRenderHint(QPainter.Antialiasing, True)
    # UNE forme d'ombre pour tous les cotes allumes (forme agrandie de chacun d'eux, coins arrondis qui
    # grandissent entre deux cotes allumes) : rien du cote d'un cote eteint, et pas d'ombre doublee.
    # Chaque cote en prend son SECTEUR (decoupe par les diagonales des coins) dans sa couleur, puis
    # s'estompe vers un cote voisin eteint.
    on = {q: bool(look["on"].get(q)) for q in _SHADOW_SIDES}
    # Secteurs prolonges A L'INTERIEUR de la forme le long des diagonales (de `k`, au moins le plus grand
    # rayon) : sinon le coin entre l'arrondi et l'angle droit n'appartenait a aucun cote et restait vide
    # (encoche claire au coin de toute forme arrondie, vue sur les menus).
    k = min(max(radius.values(), default=0) + 1.0, inner_w / 2.0, inner_h / 2.0)
    sl, st, sr, sb = shape.left(), shape.top(), shape.right(), shape.bottom()
    sectors = {
        "top": ((0, 0), (width, 0), (sr - k, st + k), (sl + k, st + k)),
        "bottom": ((0, height), (width, height), (sr - k, sb - k), (sl + k, sb - k)),
        "left": ((0, 0), (0, height), (sl + k, sb - k), (sl + k, st + k)),
        "right": ((width, 0), (width, height), (sr - k, sb - k), (sr - k, st + k)),
    }
    for side in _SHADOW_SIDES:
        if not on[side]:
            continue
        layer = QImage(out.size(), QImage.Format_ARGB32_Premultiplied)
        layer.setDevicePixelRatio(dpr)
        layer.fill(Qt.transparent)
        painter = QPainter(layer)
        painter.setRenderHint(QPainter.Antialiasing, True)
        painter.setCompositionMode(QPainter.CompositionMode_Plus)
        painter.setPen(Qt.NoPen)
        base = QColor(look["colors"][side])
        alpha = base.alphaF()
        for k in range(1, steps + 1):
            e = k / dpr                                   # expansion de cette couche (px logiques)
            t0, t1 = (k - 1) / steps, k / steps
            weight = _shadow_profile(t0) - _shadow_profile(t1)   # somme = 1
            color = QColor(base)
            color.setAlphaF(max(0.0, min(1.0, alpha * weight)))
            grown = {q: (e if on[q] else 0.0) for q in _SHADOW_SIDES}
            rect = shape.adjusted(-grown["left"], -grown["top"], grown["right"], grown["bottom"])
            corners = {c: r + (e if grown[_CORNER_SIDES[c][0]] and grown[_CORNER_SIDES[c][1]] else 0.0)
                       for c, r in radius.items()}
            painter.setBrush(color)
            painter.drawPath(_rounded_rect_path(rect, corners))
        # Secteur de ce cote seulement (masque sur toute l'image : le reste est efface).
        mask = QImage(out.size(), QImage.Format_ARGB32_Premultiplied)
        mask.setDevicePixelRatio(dpr)
        mask.fill(Qt.transparent)
        mp = QPainter(mask)
        # SANS lissage : chaque pixel appartient a un seul secteur. Lisses, deux secteurs voisins ne
        # couvraient pas entierement leur diagonale commune -> trait clair en travers des coins.
        mp.setRenderHint(QPainter.Antialiasing, False)
        mp.setPen(Qt.NoPen)
        mp.setBrush(QColor(0, 0, 0, 255))
        from PySide6.QtGui import QPolygonF
        mp.drawPolygon(QPolygonF([QPointF(x, y) for x, y in sectors[side]]))
        mp.end()
        painter.setCompositionMode(QPainter.CompositionMode_DestinationIn)
        painter.drawImage(0, 0, mask)
        # Transition DOUCE vers un cote voisin eteint : l'ombre de ce cote s'estompe sur ses derniers
        # pixels (longueur = la taille de l'ombre, la moitie du cote au plus), sans rien poser sur le
        # cote eteint (avant : bande coupee net au coin).
        horizontal = side in ("top", "bottom")
        fade = min(margin, (inner_w if horizontal else inner_h) / 2.0)
        for end in (("left", "right") if horizontal else ("top", "bottom")):
            if on[end] or fade <= 0:
                continue
            start = {"left": shape.left(), "right": shape.right(), "top": shape.top(), "bottom": shape.bottom()}[end]
            stop = start + fade if end in ("left", "top") else start - fade
            ramp = QLinearGradient(start, 0, stop, 0) if horizontal else QLinearGradient(0, start, 0, stop)
            for t in (0.0, 0.125, 0.25, 0.375, 0.5, 0.625, 0.75, 0.875, 1.0):
                ramp.setColorAt(t, QColor(0, 0, 0, round(255 * (1.0 - _shadow_profile(t)))))
            painter.fillRect(QRectF(0, 0, width, height), ramp)
        painter.end()
        composer.drawImage(0, 0, layer)
    # Forme videe : l'ombre n'existe que DEHORS (rien sous une image transparente).
    composer.setCompositionMode(QPainter.CompositionMode_DestinationOut)
    composer.setPen(Qt.NoPen)
    composer.setBrush(QColor(0, 0, 0, 255))
    composer.drawPath(_rounded_rect_path(shape, radius))
    composer.end()
    pix = QPixmap.fromImage(out)
    pix.setDevicePixelRatio(dpr)
    return pix


def _shadow_template(radius: dict, look: dict, dpr: float, size=None):
    """(pixmap, largeur interieure, hauteur interieure) du modele en cache. `size` (w, h) : forme trop
    petite pour les 9 morceaux, rendue a sa taille exacte."""
    reach = _shadow_reach(radius, look)
    inner = (2 * reach + 8, 2 * reach + 8) if size is None else size
    key = (inner, tuple(sorted(radius.items())), tuple(sorted(look["on"].items())),
           tuple(sorted(look["colors"].items())), look["size"], round(dpr, 3))
    pix = _SHADOW_CACHE.get(key)
    if pix is None:
        pix = _render_shadow(inner[0], inner[1], radius, look, dpr)
        if len(_SHADOW_CACHE) >= _SHADOW_CACHE_MAX:
            _SHADOW_CACHE.pop(next(iter(_SHADOW_CACHE)))
        _SHADOW_CACHE[key] = pix
    return pix, inner[0], inner[1]


def paint_shadow(painter: QPainter, rect, radius, look: dict | None, strength: float = 1.0) -> None:
    """Ombre de la forme `rect` (QRect/QRectF, arrondie `radius` : int ou dict des 4 coins) selon `look`
    (shadow_look), a dessiner AVANT l'element. `strength` (0-1) : attenuation (ex. vol d'une image)."""
    if look is None or strength <= 0.0:
        return
    rect = QRectF(rect)
    if rect.width() <= 0 or rect.height() <= 0:
        return
    device = painter.device()
    dpr = (device.devicePixelRatioF() if device is not None else 1.0) or 1.0
    corners = _shadow_radius(radius)
    reach = _shadow_reach(corners, look)
    margin = look["size"]
    painter.save()
    painter.setRenderHint(QPainter.SmoothPixmapTransform, True)
    if strength < 1.0:
        painter.setOpacity(painter.opacity() * strength)
    if rect.width() < 2 * reach + 8 or rect.height() < 2 * reach + 8:
        # Petite forme : modele a sa taille exacte (garde en cache lui aussi).
        pix, w, h = _shadow_template(corners, look, dpr, (max(1, round(rect.width())), max(1, round(rect.height()))))
        painter.drawPixmap(QRectF(rect.x() - margin, rect.y() - margin, rect.width() + 2 * margin,
                                  rect.height() + 2 * margin), pix, QRectF(pix.rect()))
        painter.restore()
        return
    pix, w, h = _shadow_template(corners, look, dpr)
    # 9 morceaux, coupes en pixels PHYSIQUES entiers du modele.
    cut = round((margin + reach + 2) * dpr)                    # coin : marge + rayon + 2 px
    pw, ph = pix.width(), pix.height()
    sx = (0, cut, pw - cut, pw)
    sy = (0, cut, ph - cut, ph)
    c = cut / dpr
    left, top = rect.x() - margin, rect.y() - margin
    right, bottom = rect.right() + margin, rect.bottom() + margin
    if isinstance(rect, QRectF):
        right, bottom = rect.x() + rect.width() + margin, rect.y() + rect.height() + margin
    tx = (left, left + c, right - c, right)
    ty = (top, top + c, bottom - c, bottom)
    for j in range(3):
        for i in range(3):
            if i == 1 and j == 1:
                continue                                       # interieur de la forme : vide
            source = QRectF(sx[i], sy[j], sx[i + 1] - sx[i], sy[j + 1] - sy[j])
            target = QRectF(tx[i], ty[j], tx[i + 1] - tx[i], ty[j + 1] - ty[j])
            if source.width() > 0 and source.height() > 0 and target.width() > 0 and target.height() > 0:
                painter.drawPixmap(target, pix, source)
    painter.restore()


class ShadowUnderlay(QWidget):
    """Ombre d'un widget-ENFANT dessinee par un voisin place juste sous lui (meme parent, meme place
    agrandie de la taille de l'ombre) : l'ombre deborde du widget, que lui-meme ne peut pas peindre.
    `look_fn()` -> shadow_look ou None ; `radius_fn()` -> rayon. Suit le widget (place, visibilite)."""

    _ALL: list = []

    def __init__(self, target: QWidget, look_fn, radius_fn):
        super().__init__(target.parentWidget())
        self.setAttribute(Qt.WA_TransparentForMouseEvents, True)
        self.setAttribute(Qt.WA_NoSystemBackground, True)
        self._target = target
        self._look_fn = look_fn
        self._radius_fn = radius_fn
        target.installEventFilter(self)
        ShadowUnderlay._ALL.append(self)
        self.destroyed.connect(lambda *_a, s=self: ShadowUnderlay._ALL.remove(s) if s in ShadowUnderlay._ALL else None)
        target.destroyed.connect(self.deleteLater)
        self.sync()

    def sync(self):
        target = self._target
        try:
            look = self._look_fn()
            visible = look is not None and target.isVisible() and target.parentWidget() is self.parentWidget()
        except RuntimeError:
            return
        if not visible:
            self.hide()
            return
        margin = look["size"]
        self.setGeometry(target.geometry().adjusted(-margin, -margin, margin, margin))
        self.stackUnder(target)
        self.show()
        self.update()

    def eventFilter(self, obj, event):
        if obj is self._target and event.type() in (QEvent.Move, QEvent.Resize, QEvent.Show, QEvent.Hide,
                                                    QEvent.ZOrderChange, QEvent.ParentChange):
            QTimer.singleShot(0, self._safe_sync)
        return False

    def _safe_sync(self):
        try:
            self.sync()
        except RuntimeError:                 # detruit entre-temps
            pass

    def paintEvent(self, event):
        look = self._look_fn()
        if look is None:
            return
        margin = look["size"]
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing, True)
        paint_shadow(painter, QRectF(margin, margin, self._target.width(), self._target.height()),
                     self._radius_fn(), look)
        painter.end()

    @classmethod
    def refresh_all(cls):
        """Reglages d'ombre changes : chaque ombre se recale et se repeint."""
        for underlay in list(cls._ALL):
            try:
                underlay.sync()
            except RuntimeError:
                pass


def attach_shadow(target: QWidget, look_fn, radius_fn) -> "ShadowUnderlay":
    """Ombre (voir ShadowUnderlay) d'un widget ; une seule par widget."""
    existing = getattr(target, "_shadow_underlay", None)
    if existing is not None:
        try:
            if existing.parentWidget() is target.parentWidget():
                existing.sync()
                return existing
            existing.deleteLater()
        except RuntimeError:
            pass
    underlay = ShadowUnderlay(target, look_fn, radius_fn)
    target._shadow_underlay = underlay
    return underlay


def _set_table_shadow(look: dict | None) -> None:
    """Reglages > Tableaux > Ombres : tous les tableaux des reglages (et ceux construits avec leurs
    briques) la suivent en direct."""
    _TABLE_SHADOW["look"] = look
    ShadowUnderlay.refresh_all()
