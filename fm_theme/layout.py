from contextlib import contextmanager

from PySide6.QtCore import (
    QEvent, QObject, QPoint, QPointF, QRect, Qt, QTimer, Signal,
)
from PySide6.QtGui import (
    QColor,
    QCursor,
    QFont,
    QPainter,
    QPixmap,
)
from PySide6.QtSvg import QSvgRenderer
from PySide6.QtWidgets import (
    QApplication,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)
from fm_theme.theme import _set_text_role
from settings_store import (
    M,
    _resolve_color_value,
    _ICONS_DIR,
    _subsection_left_margin,
    _title_box,
    _title_color,
    _title_font,
    _title_gap_next,
    _title_indent,
)
from fm_theme.widgets import (
    Menu, DRAG_GHOST_OPACITY, _DualFontSelectField, _selection_color, _SliderField, _Toggle,
    _apply_stylesheet_cached, _qfont, _inner_h_edge, _paint_bordered_rect, _app_dpr, _hidpi_pixmap,
    _paint_inner_vlines, _TableRow, _restyle_table_row, _table_frame, _hide_width_badges, _width_badges,
    add_context_extras,
)


# ==========================================================================
# Blocs de mise en page (sections / lignes), fideles a la maquette.
# ==========================================================================

def _label_block(text: str, note: str = "") -> QWidget:
    box = QWidget()
    # Meme correctif que _table_cell (voir son commentaire) : ce bloc est
    # aussi pose directement dans une ligne de tableau "ferme" (voir la
    # table Entetes, SettingsWindow._section_headers) et souffrait du meme
    # masquage de la couleur "Fond de tableau" ; sans effet visible dans son
    # AUTRE usage (_Row, hors tableau), ou le fond herite etait deja le bon.
    box.setStyleSheet("background: transparent;")
    box.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
    layout = QVBoxLayout(box)
    layout.setContentsMargins(0, 6, 0, 6)
    layout.setSpacing(1)
    name = QLabel(text)
    name.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
    _set_text_role(name, "row_label")
    layout.addWidget(name)
    if note:
        sub = QLabel(note)
        sub.setWordWrap(True)
        sub.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
        _set_text_role(sub, "row_note")
        layout.addWidget(sub)
    return box

def _label_block_natural_width(label_block: QWidget) -> int:
    """Largeur naturelle (texte, pas la boite) d'un _label_block — utilise
    par _FlatColumnResizer (voir _build_flat_table/SettingsWindow.
    _section_headers) pour choisir une largeur de depart qui ne change RIEN
    a l'apparence par defaut. PAS label_block.sizeHint().width() : la boite
    elle-meme a un SizePolicy Ignored en largeur (voir _label_block), ce
    qui fait remonter une largeur de 0 quel que soit son contenu — le
    QLabel interieur, lui, garde son sizeHint() reel malgre la meme
    policy (Ignored ne change que la facon dont le layout PARENT traite ce
    sizeHint, jamais la valeur qu'il retourne)."""
    label = label_block.findChild(QLabel)
    return label.sizeHint().width() if label is not None else 0



_SVG_PIXMAP_CACHE: dict[tuple[str, int, str], QPixmap] = {}

def _tinted_svg_pixmap(name: str, size: int, color: str, dpr: float | None = None) -> QPixmap:
    """Charge icons/{name}.svg (trace uni, sans fill) et le recolore en
    `color` — les fichiers sources n'ont pas de couleur propre (destines a
    heriter de currentColor), donc rendus ici comme un simple masque alpha
    (le SVG en noir) puis remplis via CompositionMode_SourceIn. Rendu a 4x
    la taille cible puis mis a l'echelle (devicePixelRatio) pour rester net
    sur un ecran HiDPI. Mis en cache par (nom, taille, couleur) : la couleur
    ne change qu'au fil d'un theme/preview, pas a chaque repaint."""
    dpr = dpr or _app_dpr()
    key = (name, size, color, dpr)
    pix = _SVG_PIXMAP_CACHE.get(key)
    if pix is not None:
        return pix
    from PySide6.QtGui import QImage
    renderer = QSvgRenderer(str(_ICONS_DIR / f"{name}.svg"))
    side = round(size * dpr) * 4
    image = QImage(side, side, QImage.Format_ARGB32_Premultiplied)
    image.fill(Qt.transparent)
    p = QPainter(image)
    p.setRenderHint(QPainter.Antialiasing, True)
    renderer.render(p)
    p.setCompositionMode(QPainter.CompositionMode_SourceIn)
    p.fillRect(image.rect(), QColor(color))
    p.end()
    # Reduit ICI par moyenne de zone a la taille physique (affiche 1:1) : laisser drawPixmap
    # reduire un pixmap 4x (filtrage bilineaire) crenelait le trace.
    pix = _hidpi_pixmap(image, size, size, dpr)
    _SVG_PIXMAP_CACHE[key] = pix
    return pix

class _Chevron(QWidget):
    """Chevron SVG (icons/chevron-bas.svg, icons/chevron-droite.svg — voir
    _tinted_svg_pixmap) — remplace l'ancien chevron peint a la main (2
    traits) par les icones perso de l'utilisateur (F:\\SYNC\\Sync\\IMAGES\\
    ico\\SVG, "chevron bas"/"chevron droite"), recolorees en direct pour
    suivre M['section_title']. Pointe vers le bas deplie, vers la droite
    replie — voir la remarque de l'utilisateur, capture a l'appui du style
    recherche."""

    def __init__(self, size: int = 16, color: str | None = None, parent=None):
        super().__init__(parent)
        self._collapsed = False
        # `color` (voir General > TITRE, la remarque de l'utilisateur, "je
        # veux que la couleur des coches de deploiement des titre soient de
        # la mm couleur que le titre") : suit desormais la couleur du titre
        # PAR NIVEAU (voir _Section/_SubSection.__init__/_apply_title_
        # level_style) au lieu du fixe M['section_title'] d'avant.
        self._color = color or M["section_title"]
        self.setFixedSize(size, size)

    def setCollapsed(self, collapsed: bool):
        if collapsed != self._collapsed:
            self._collapsed = collapsed
            self.update()

    def setSlotWidth(self, width: int):
        """Elargit l'emplacement sans grossir la fleche (centree) : v2, meme emplacement a tous les niveaux."""
        self.setFixedSize(max(width, self.height()), self.height())
        self.update()

    def setColor(self, color: str):
        if color != self._color:
            self._color = color
            self.update()

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing, True)
        # SmoothPixmapTransform : c'est CE hint (pas Antialiasing, qui ne
        # joue que sur le trace vectoriel) qui commande le lissage quand
        # QPainter reduit un pixmap (ici le rendu 4x/devicePixelRatio vers
        # la taille reelle du chevron, voir _tinted_svg_pixmap) — sans lui
        # Qt reechantillonne au plus proche voisin, d'ou le rendu "pas
        # terrible" (crenele) signale par l'utilisateur.
        p.setRenderHint(QPainter.SmoothPixmapTransform, True)
        name = "chevron-droite" if self._collapsed else "chevron-bas"
        glyph = self.height()                  # fleche carree ; emplacement eventuellement plus large
        pix = _tinted_svg_pixmap(name, glyph, self._color, self.devicePixelRatioF())
        p.drawPixmap(QPointF((self.width() - glyph) // 2, 0), pix)     # pixel entier : copie 1:1
        p.end()

class _SectionHeader(QWidget):
    """Bandeau titre d'une _Section/_SubSection. Seule la largeur du titre
    (chevron + texte) est cliquable pour replier/deplier, pas le reste de la
    ligne (demande de l'utilisateur) ; le curseur main n'apparait que la."""

    clicked = Signal()

    _DRAG_START = 6        # px avant qu'un appui sur le titre devienne un deplacement

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMouseTracking(True)
        # Deplacement du paragraphe en tirant son titre (v2) : objet fourni par la fenetre, avec
        # begin(entete, point global) -> bool, move(point global), end(). Sans lui, le clic
        # replie / deplie des l'appui, comme avant ; avec lui, au relachement s'il n'y a pas eu
        # de deplacement.
        self.drag_handler = None
        self._press = None
        self._dragging = False

    def _hit(self, x: float) -> bool:
        parts = [w for w in self.findChildren(QWidget, options=Qt.FindDirectChildrenOnly) if w.isVisibleTo(self)]
        if not parts:
            return True
        return min(w.geometry().left() for w in parts) <= x <= max(w.geometry().right() for w in parts)

    def _sync_cursor(self, x: float):
        self.setCursor(Qt.PointingHandCursor if self._hit(x) else Qt.ArrowCursor)

    def mouseMoveEvent(self, event):
        if self._press is not None:
            gpos = event.globalPosition().toPoint()
            # Deplacer = Ctrl + glisser (demande de l'utilisateur, pour tout deplacement de l'appli).
            if (not self._dragging and QApplication.keyboardModifiers() & Qt.ControlModifier
                    and (gpos - self._press).manhattanLength() > self._DRAG_START):
                self._dragging = bool(self.drag_handler.begin(self, self._press))
                if self._dragging:
                    self.setCursor(Qt.ClosedHandCursor)
            if self._dragging:
                self.drag_handler.move(gpos)
                event.accept()
                return
        self._sync_cursor(event.position().x())
        super().mouseMoveEvent(event)

    def enterEvent(self, event):
        self._sync_cursor(self.mapFromGlobal(QCursor.pos()).x())
        super().enterEvent(event)

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton and self._hit(event.position().x()):
            if self.drag_handler is not None:
                self._press, self._dragging = event.globalPosition().toPoint(), False
                event.accept()
                return
            self.clicked.emit()
        super().mousePressEvent(event)

    def mouseReleaseEvent(self, event):
        if self._press is not None and event.button() == Qt.LeftButton:
            dragging, self._press, self._dragging = self._dragging, None, False
            if dragging:
                self.drag_handler.end()
                self._sync_cursor(event.position().x())
            else:
                self.clicked.emit()               # simple clic : replier / deplier
            event.accept()
            return
        super().mouseReleaseEvent(event)

    def contextMenuEvent(self, event):
        """Clic droit sur un titre : seulement les lignes fournies par la fenetre (add_context_extras)."""
        menu = Menu(self)
        add_context_extras(self, menu)
        if menu.actions():
            menu.exec(event.globalPos())
        event.accept()

def _activate_layout_tree(widget: QWidget):
    """Force un recalcul COMPLET et immediat (invalidate + activate) de
    TOUS les layouts sous `widget`, feuilles d'abord (recursion en POST-
    ORDRE) — necessaire pour lire un sizeHint() fiable juste apres avoir
    replie/deplie un sous-groupe imbrique (voir _Section.refresh_min_
    height/_SubSection, la remarque de l'utilisateur, "il y a des bugs
    importants quand on plie/deplie les sous sections").

    QWidget.updateGeometry() (voir _SubSection.set_collapsed) n'invalide
    QUE le layout du parent DIRECT — au-dela d'1 niveau de QWidget nu
    imbrique (tres frequent ici : chaque sous-groupe vit dans sa propre
    boite intermediaire, voir Colonnes/Entetes/Toggles > Cadre/Coche...),
    Qt ne fait PAS remonter cette invalidation plus loin de facon
    SYNCHRONE — seulement plus tard, via la file d'evenements
    (QEvent.LayoutRequest, traitee au prochain passage de la boucle
    d'evenements) : un sizeHint() lu tout de suite (avant ce passage,
    exactement le cas de refresh_min_height/refresh_layout, appeles EN
    REACTION au clic) restait donc perime a un ou plusieurs niveaux
    d'ecart. Ici, on force nous-memes ce recalcul, tout de suite, sur
    l'arbre ENTIER (peu importe sa profondeur d'imbrication)."""
    for child in widget.children():
        if isinstance(child, QWidget):
            _activate_layout_tree(child)
    lay = widget.layout()
    if lay is not None:
        lay.invalidate()
        lay.activate()

# Parent par defaut des _Section construites SANS parent explicite (voir
# _section_host, SettingsWindow._build_content) : une section qui nait deja
# a sa place n'est plus re-stylee en entier quand on la range dans la page
# (rattacher un sous-arbre deja construit re-applique les feuilles de style
# de tous ses widgets).
_SECTION_HOST = None


@contextmanager
def _section_host(widget: QWidget):
    global _SECTION_HOST
    previous, _SECTION_HOST = _SECTION_HOST, widget
    try:
        yield
    finally:
        _SECTION_HOST = previous

class _BodyMixin:
    """Corps d'une _Section/_SubSection. Les TITRES (sous-sections, seules ou
    dans un conteneur) se placent a leur retrait ABSOLU : un retrait de 0 aligne
    tous les titres, quel que soit leur niveau ou leur imbrication. Le reste du
    contenu (tableaux...) est decale pour commencer sous le texte du titre."""

    def _init_body(self, offset: int):
        self._body_layout.setContentsMargins(0, 0, 0, 0)
        self._body_rows: list[QHBoxLayout] = []
        self._body_offset = offset

    @staticmethod
    def _holds_titles(widget: QWidget) -> bool:
        if isinstance(widget, _SubSection):
            return True
        layout = widget.layout()
        if layout is None:
            return False
        found = False
        for i in range(layout.count()):
            item = layout.itemAt(i).widget()
            if isinstance(item, _SubSection):
                found = True
            elif item is not None and item.layout() is not None:
                return False
        return found

    def _add_body(self, widget: QWidget):
        if self._holds_titles(widget):
            self._body_layout.addWidget(widget)
            return
        row = QHBoxLayout()
        row.setContentsMargins(self._body_offset, 0, 0, 0)
        row.setSpacing(0)
        # Justifie a GAUCHE (regle de tous les tableaux) : un tableau a largeur fixe (somme de ses
        # colonnes, v2) serait sinon centre dans la place restante.
        row.addWidget(widget, 0, Qt.AlignLeft)
        self._body_rows.append(row)
        self._body_layout.addLayout(row)

    def set_body_offset(self, offset: int):
        self._body_offset = offset
        for row in self._body_rows:
            m = row.contentsMargins()
            row.setContentsMargins(offset, m.top(), 0, m.bottom())   # garde les espaces au-dessus / en dessous

    # -- Mode « paragraphe » (fenetre v2) ------------------------------------
    # Le titre et tout son contenu (jusqu'au titre suivant) forment une boite :
    # au debut du contenu du paragraphe parent (pas de retrait en v2 : le
    # padding du fond du parent en tient lieu), decalee de la margin (espace
    # HORS de la boite, sur les 4 cotes), puis bordure, padding du fond, et le
    # titre avec son propre padding (Titre > Espacements). Le premier / dernier
    # titre d'une pile recoit en plus l'espacement avant / apres de son niveau.
    # Plus d'espaceurs entre titres : ces espaces les remplacent.
    _boxed = False
    _box_off = 0
    _box_abs = 0
    # Freres empiles juste au-dessus / au-dessous (poses par l'empilement, v2 : _add_stacked). Deux
    # boites qui se touchent (margins nulles a la jonction) partagent UN seul filet, comme les colonnes
    # (celui du haut le porte, le bas perd son bord haut), et leurs coins de jonction sont droits.
    _box_prev = None
    _box_next = None

    # Emplacement du chevron (chevron + ecart avant le texte) COMMUN a tous les niveaux en v2 : celui du
    # niveau 1. Les textes s'alignent donc sans le decalage fixe de _subsection_left_margin (v1), et
    # une boite sans margin est collee au bord interieur du parent (filet partage, voir _joined_box).
    _BOX_CHEVRON_SLOT, _BOX_CHEVRON_GAP = 16, 10

    def enable_box(self):
        self._boxed = True
        self._chevron.setSlotWidth(self._BOX_CHEVRON_SLOT)
        self._head_layout.setSpacing(self._BOX_CHEVRON_GAP)
        # Corps transparent : le fond du paragraphe doit se voir sous le contenu.
        self._body.setStyleSheet("background: transparent;")
        self.apply_box()

    def _title_level(self) -> int:
        return getattr(self, "_level", 1)

    def _chevron_room(self) -> int:
        if self._boxed:
            return self._BOX_CHEVRON_SLOT + self._BOX_CHEVRON_GAP
        return 16 + 10 if self._title_level() == 1 else 11 + 6

    def _parent_title(self):
        for parent in _ancestors(self):
            if isinstance(parent, (_Section, _SubSection)):
                return parent
        return None

    def _box_thickness(self, box: dict) -> dict:
        return {side: (box["thickness"] if box["border_on"].get(side) else 0)
                for side in ("left", "top", "right", "bottom")}

    def _shown(self, other) -> bool:
        """Frere `other` affiche dans la pile : ni lui ni ses conteneurs PROPRES ne sont masques (l'etat
        replie/deplie des ancetres communs n'entre pas en compte)."""
        widget = other
        while widget is not None and not widget.isAncestorOf(self):
            if widget.isHidden():
                return False
            widget = widget.parentWidget()
        return other is not None

    def _stack_spaces(self, box: dict) -> tuple[int, int]:
        """Espace avant (1er titre de sa pile) et apres (dernier titre de sa pile) : un PADDING,
        dans la boite (sous le fond et entre les bordures), en plus du padding du fond."""
        return (0 if self._shown(self._box_prev) else box["space_before"],
                0 if self._shown(self._box_next) else box["space_after"])

    def _touches(self, other, side: str) -> bool:
        """Vrai si la boite `other` est collee a celle-ci par son cote `side` (« top » : `other` est au-dessus)."""
        if other is None or not other._boxed or not self._shown(other):
            return False
        lower = self if side == "top" else other              # un espace au-dessus les separe
        if getattr(lower.parentWidget(), "_space_above_px", 0) or getattr(lower, "_space_above_px", 0):
            return False
        upper = other if side == "top" else self              # ... ou un espace en dessous
        if getattr(upper.parentWidget(), "_space_below_px", 0) or getattr(upper, "_space_below_px", 0):
            return False
        mine, theirs = _title_box(self._title_level())["margin"], _title_box(other._title_level())["margin"]
        if side == "top":
            return mine[1] == 0 and theirs[3] == 0
        return mine[3] == 0 and theirs[1] == 0

    def _joined_box(self, box: dict) -> dict:
        """`box` corrige aux jonctions avec les freres colles : filet unique, coins de jonction droits."""
        border_on, radius = dict(box["border_on"]), dict(box["radius"])
        if self._touches(self._box_prev, "top"):
            radius["top_left"] = radius["top_right"] = 0
            above = _title_box(self._box_prev._title_level())
            if above["border_on"].get("bottom") and above["thickness"]:
                border_on["top"] = False       # le filet du frere du dessus sert de jonction
        if self._touches(self._box_next, "bottom"):
            radius["bottom_left"] = radius["bottom_right"] = 0
        # Collee au bord INTERIEUR de son paragraphe parent (padding du parent et margin nuls de ce
        # cote) : le filet du parent sert de jonction ; coin dans un coin du parent = son rayon
        # interieur, coin le long d'un seul bord = droit.
        parent = self._parent_title()
        if parent is not None and parent._boxed:
            pbox = getattr(parent, "_box_style", None) or _title_box(parent._title_level())
            # Padding du fond ET padding (paragraphe) du parent : l'un ou l'autre decolle l'enfant du bord.
            pad = [a + b for a, b in zip(pbox["padding"], pbox.get("body_padding", (0, 0, 0, 0)))]
            margin = box["margin"]
            last = not self._shown(self._box_next)
            inner = {"left": self._box_off == 0 and pad[0] == 0,
                     "right": pad[2] == 0 and margin[2] == 0,
                     "bottom": last and pad[3] == 0 and margin[3] == 0}
            for side, touching in inner.items():
                if touching and pbox["border_on"].get(side) and pbox["thickness"]:
                    border_on[side] = False
            inner["top"] = False               # l'entete du parent est toujours au-dessus
            for corner in ("top_left", "top_right", "bottom_left", "bottom_right"):
                v, h = corner.split("_")
                if inner[v] and inner[h]:
                    radius[corner] = max(0, pbox["radius"][corner] - pbox["thickness"])
                elif inner[v] or inner[h]:
                    radius[corner] = 0
        return dict(box, border_on=border_on, radius=radius)

    def content_abs_x(self) -> int:
        """Abscisse (repere de la page) ou commence le contenu de ce paragraphe."""
        box = getattr(self, "_box_style", None) or _title_box(self._title_level())   # filets partages compris
        return self._box_abs + self._box_thickness(box)["left"] + box["padding"][0] + box["body_padding"][0]

    def apply_box(self):
        if not self._boxed:
            return
        level = self._title_level()
        look = getattr(self, "_title_look", None)          # style PROPRE (« Override settings »)
        raw = look["box"] if look else _title_box(level)
        parent = self._parent_title()
        base = parent.content_abs_x() if parent is not None and parent._boxed else 0
        # _box_off / _box_abs = bord GAUCHE de la boite (bordure) : debut du contenu du parent + margin.
        self._box_off = raw["margin"][0]
        self._box_abs = base + self._box_off
        box = self._box_style = self._joined_box(raw)   # depend de _box_off (collee a gauche ?)
        ml, mt, mr, mb = box["margin"]
        before, after = self._box_spaces = self._stack_spaces(box)
        t = self._box_thickness(box)
        pl, pt, pr, pb = box["padding"]
        pt, pb = pt + before, pb + after       # espacements avant / apres = padding (dans la boite)
        self.layout().setContentsMargins(self._box_off + t["left"] + pl, mt + t["top"] + pt,
                                         mr + t["right"] + pr, mb + t["bottom"] + pb)
        tl, tt, tr, tb = box["text_padding"]
        self._head_layout.setContentsMargins(tl, tt, tr, tb)
        self._body_layout.setContentsMargins(*box["body_padding"])   # Padding (paragraphe) : tout le contenu
        self.set_body_offset(tl + self._chevron_room())
        self.update()

    def _box_rect(self) -> QRect:
        """Rectangle peint de la boite (bordure comprise) : tout sauf la margin."""
        _ml, mt, mr, mb = self._box_style["margin"]
        return QRect(self._box_off, mt, self.width() - self._box_off - mr, self.height() - mt - mb)

    def paintEvent(self, event):
        box = getattr(self, "_box_style", None) if self._boxed else None
        if box is not None and (box["fill"] or (box["thickness"] and any(box["border_on"].values()))):
            p = QPainter(self)
            _paint_bordered_rect(p, self._box_rect(),
                                 box["radius"], box["border_on"], box["thickness"], box["border_colors"],
                                 box["fill"])
            p.end()
        super().paintEvent(event)



class _Section(_BodyMixin, QWidget):
    """Section de la page : titre bleu petites capitales + note optionnelle,
    PAS de filet horizontal (la maquette n'en a pas ici, contrairement a
    l'ancien _Group) — juste un espacement genereux (voir SettingsWindow.
    _build_content, un spaceur dedie entre chaque section, pas
    QVBoxLayout.setSpacing). Repliable (voir toggle) : un chevron devant le
    titre, tout le bandeau cliquable (voir _SectionHeader) — replier masque
    juste le corps (self._body), le titre restant toujours visible — voir
    la remarque de l'utilisateur. collapsedChanged permet a l'appelant de
    reduire a son tour l'espace APRES la section (voir _build_content) :
    repliee, elle n'a plus besoin d'un espacement aussi genereux avec la
    section suivante."""

    collapsedChanged = Signal(bool)

    def __init__(self, title: str, note: str = "", parent=None):
        super().__init__(parent if parent is not None else _SECTION_HOST)
        self._title_text = title
        self._collapsed = False
        self._layout = QVBoxLayout(self)
        self._layout.setContentsMargins(0, 0, 0, 0)
        self._layout.setSpacing(0)

        head = self.head = _SectionHeader()
        head.setCursor(Qt.PointingHandCursor)
        head_l = QHBoxLayout(head)
        self._head_layout = head_l
        # Retrait GAUCHE configurable (voir General > TITRE > "Retrait
        # titre niveau 1", _title_indent) — voir la remarque de
        # l'utilisateur, "je veux homogeneiser les textes des sections et
        # sous sections". Marge du bas : espace le titre du corps quand il
        # est visible — inutile repliee (le corps est masque, voir
        # set_collapsed, qui la ramene alors a 0 pour ne rien laisser
        # trainer sous le titre en plus du spaceur inter-sections, voir
        # SettingsWindow._build_content).
        self._title_indent = _title_indent(1)
        head_l.setContentsMargins(self._title_indent, 0, 0, _title_gap_next(1))
        head_l.setSpacing(10)
        # Chevron peint (voir _Chevron) — taille FIXE (pas de reglage
        # dedie) ; le TEXTE (police/couleur) suit General > TITRE > "Police
        # titre niveau 1" (voir _title_font/_title_color).
        self._chevron = _Chevron(size=16, color=_title_color(1))
        head_l.addWidget(self._chevron)
        name = self._name_label = QLabel(title.upper())
        name.setFont(_title_font(1))
        name.setStyleSheet(f"color: {_title_color(1)}; background: transparent;")
        head_l.addWidget(name)
        if note:
            note_label = QLabel(note)
            _set_text_role(note_label, "note")
            head_l.addWidget(note_label)
        head_l.addStretch(1)
        head.clicked.connect(self.toggle)
        self._layout.addWidget(head)

        self._body = QWidget()
        self._body_layout = QVBoxLayout(self._body)
        # Retrait GAUCHE aligne sur le debut du TEXTE du titre (retrait +
        # chevron + espacement, voir head_l ci-dessus) — voir la remarque de
        # l'utilisateur, "les tableaux doivent commencer au meme niveau
        # d'indentation que le titre de section ... correspondant" : sans
        # cela, le contenu (tableaux compris) demarrait a 0, decale a
        # gauche du titre au-dessus.
        self._init_body(self._title_indent + 16 + 10)
        self._body_layout.setSpacing(0)
        self._layout.addWidget(self._body)

        self._refresh_chevron()

    def add(self, widget: QWidget):
        self._add_body(widget)

    def toggle(self):
        self.set_collapsed(not self._collapsed)

    def set_collapsed(self, collapsed: bool):
        if self._collapsed == collapsed:
            return
        self._collapsed = collapsed
        self._body.setVisible(not collapsed)
        if not self._boxed:     # en mode paragraphe, le padding du titre ne depend pas du repli
            self._head_layout.setContentsMargins(self._title_indent, 0, 0, 0 if collapsed else _title_gap_next(1))
        # activate() (pas juste invalidate(), ni compter sur le prochain
        # passage de l'event loop) : FORCE ce layout precis, dont on vient
        # de changer les marges, a se recalculer TOUT DE SUITE. Sans ca, le
        # sizeHint() lu juste en dessous restait construit avec l'ANCIENNE
        # hauteur du bandeau (marge du bas encore a 0 au lieu de 10) — un
        # deficit de quelques pixels, constant et reproductible, meme si
        # head.sizeHint() interroge DIRECTEMENT rendait deja la bonne
        # valeur : c'est la mise en cache du PARENT (self._layout, qui
        # empile bandeau+corps) qui ne se met a jour QUE sur un vrai
        # QResizeEvent ou un activate() explicite de CE layout interne —
        # updateGeometry()/invalidate() sur self._layout, essayes ici en
        # premier, ne suffisaient pas non plus. Voir la remarque de
        # l'utilisateur, capture annotee a l'appui (bord bas des pastilles
        # de Couleurs recouvert par le filet de la ligne suivante).
        # _activate_layout_tree (pas juste _head_layout) : un _SubSection
        # imbrique dans le corps peut avoir change de taille PENDANT que
        # cette section etait repliee (invisible, donc jamais relayoutee
        # entre-temps) — voir refresh_min_height, meme raison.
        _activate_layout_tree(self)
        self._refresh_chevron()
        # setMinimumHeight explicite a la taille naturelle : sans lui, le
        # layout PARENT (SettingsWindow._build_content, qui empile toutes
        # les sections) redistribue l'espace total disponible en gardant un
        # minimumSizeHint() DEVENU INCOHERENT avec le sizeHint() reel de
        # cette section une fois son corps deplie — observe avec les 2 gros
        # tableaux Cadre/Coche de Toggle 1/Toggle 2 (voir Toggles > Style,
        # capture a l'appui) : la section restait ecrasee sous sa propre
        # taille naturelle malgre une hauteur totale disponible largement
        # suffisante (minimumSizeHint() de Qt, ici, ne recalcule pas le
        # necessaire pour un contenu qui vient d'apparaitre — juste
        # updateGeometry()/invalidate() ne suffit pas a corriger ca).
        # Relachee (0) repliee : la section retrouve alors sa taille
        # naturelle, tres compacte (juste le bandeau titre).
        self.setMinimumHeight(self.sizeHint().height() if not collapsed else 0)
        self.updateGeometry()
        self.collapsedChanged.emit(collapsed)
        QTimer.singleShot(0, self._remeasure)

    def is_collapsed(self) -> bool:
        return self._collapsed

    def _remeasure(self):
        try:
            self.refresh_min_height()
            _reflow_ancestors(self)
        except RuntimeError:   # widget deja detruit
            pass

    def refresh_min_height(self):
        """Meme recalcul que la fin de set_collapsed (memes 2 lignes,
        memes raisons — voir ses commentaires), mais appelable a N'IMPORTE
        QUEL moment, pas seulement au repliage/depliage : necessaire quand
        le CONTENU d'une section DEJA depliee change de taille en direct
        (voir SettingsWindow._apply_cell_padding, Tableaux > Padding des
        cellules) — sans reappeler ceci ensuite, le plancher restait celui
        capture au dernier depliage, desormais trop petit pour le nouveau
        contenu : la section (et tout ce qui suit dans _build_content)
        gardait l'ancienne hauteur, plus courte que le tableau agrandi —
        voir la remarque de l'utilisateur, "je veux que la position du
        tableau ne change pas du tout en haut a gauche, mais que le
        tableau se redimensionne automatiquement vers le bas"."""
        if self._collapsed:
            return
        # _activate_layout_tree (pas juste les 2 layouts directs) : un
        # _SubSection imbrique dans le corps (voir Colonnes/Entetes/Toggles
        # > Cadre/Coche...) peut se replier/deplier PLUSIEURS niveaux plus
        # bas — voir sa remarque, meme raison.
        _activate_layout_tree(self)
        self.setMinimumHeight(self.sizeHint().height())
        self.updateGeometry()

    def _refresh_chevron(self):
        # Chevron bas = deplie, chevron droit = replie — meme convention que
        # les menus deroulants (▾) de cette fenetre (voir _SelectField).
        self._chevron.setCollapsed(self._collapsed)

class _SubSection(_BodyMixin, QWidget):
    """Sous-groupe repliable A L'INTERIEUR d'une _Section (voir SettingsWindow.
    _sub_heading, dont ceci prend desormais la place partout ou un sous-titre
    precedait un SEUL bloc de contenu — Colonnes/Entetes/Texte/Selection,
    Cadre/Coche, Rail/Selecteur, Toggle 1/Toggle 2) — meme mecanique que
    _Section (chevron + bandeau entierement cliquable, collapsedChanged) mais
    habillage DISCRET (petites capitales, pas de gros titre) pour rester au
    niveau visuel d'un _sub_heading plutot que rivaliser avec le titre de
    section — voir la remarque de l'utilisateur, "fait en sorte que les sous
    sections soient collapsable aussi". `indent` : meme retrait que _sub_
    heading pour les sous-groupes de 2e niveau (voir SettingsWindow.
    _build_collapsible_group)."""

    collapsedChanged = Signal(bool)

    def __init__(self, title: str, level: int = 2, parent=None):
        super().__init__(parent)
        self._title_text = title
        self._collapsed = False
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        # `level` (2 = sous-section de 1er niveau, 3 = imbriquee dans une
        # AUTRE _SubSection, 4/5 reserves pour une imbrication plus
        # profonde) — voir General > TITRE (_title_font/_title_color/
        # _title_indent) : police, couleur ET retrait suivent TOUS ce
        # reglage unique par niveau desormais — voir la remarque de
        # l'utilisateur, "je veux homogeneiser les textes des sections et
        # sous sections".
        self._level = level
        self._left_margin = _subsection_left_margin(level)
        head = self.head = _SectionHeader()
        head.setCursor(Qt.PointingHandCursor)
        head_l = QHBoxLayout(head)
        self._head_layout = head_l
        # MEME principe que _Section.__init__ (voir son commentaire) : PAS
        # de marge haute (0), seule la marge BASSE espace le bandeau de son
        # corps quand il est visible — reduite a 0 repliee (voir
        # set_collapsed) — toute la "respiration" entre 2 sous-groupes vient
        # du spaceur DEDIE (_SUBSECTION_GAP_*/_stack_subsections), pas d'une
        # marge fixe sur le bandeau lui-meme — voir la remarque de
        # l'utilisateur, "base toi sur ce que tu avais fait sur les
        # sections" (une marge haute fixe de 14px restait telle quelle meme
        # repliee, contrairement a _Section).
        head_l.setContentsMargins(self._left_margin, 0, 0, _title_gap_next(level))
        head_l.setSpacing(6)
        self._chevron = _Chevron(size=11, color=_title_color(level))
        head_l.addWidget(self._chevron)
        label = self._name_label = QLabel(title.upper())
        label.setFont(_title_font(level))
        label.setStyleSheet(f"color: {_title_color(level)}; background: transparent;")
        head_l.addWidget(label)
        head_l.addStretch(1)
        head.clicked.connect(self.toggle)
        layout.addWidget(head)

        self._body = QWidget()
        self._body_layout = QVBoxLayout(self._body)
        # MEME raison que _Section ci-dessus : retrait GAUCHE aligne sur le
        # debut du TEXTE du titre (retrait du bandeau + chevron + espacement).
        self._init_body(self._left_margin + 11 + 6)
        self._body_layout.setSpacing(0)
        layout.addWidget(self._body)
        self._refresh_chevron()

    def add(self, widget: QWidget):
        self._add_body(widget)
        # Verrouille tout de suite le plancher de hauteur de CE sous-groupe
        # sur son contenu REEL (voir refresh_layout, meme necessite que
        # _Section) -- systematique, sans rien demander a l'appelant : la
        # toute PREMIERE cause de l'ecrasement observe etait justement un
        # sous-groupe JAMAIS replie/deplie (donc jamais passe par
        # set_collapsed) qui n'avait encore AUCUN plancher propre -- voir la
        # remarque de l'utilisateur, "corrige l'ecrasement du tableau ...
        # que tu le prennes systematiquement en compte pour tous les
        # tableaux".
        self.refresh_layout()

    def toggle(self):
        self.set_collapsed(not self._collapsed)

    def set_collapsed(self, collapsed: bool):
        if self._collapsed == collapsed:
            return
        self._collapsed = collapsed
        self._body.setVisible(not collapsed)
        if not self._boxed:
            self._head_layout.setContentsMargins(self._left_margin, 0, 0, 0 if collapsed else _title_gap_next(self._level))
        self._refresh_chevron()
        # Signal AVANT le recalcul : ses abonnes (spaceurs entre titres, voir
        # _make_gap_spacer) changent la hauteur du contenu, que les planchers
        # calcules ensuite doivent deja inclure.
        self.collapsedChanged.emit(collapsed)
        self.refresh_layout()
        _reflow_ancestors(self)
        # Une 2e mesure apres le passage de la boucle d'evenements : la toute
        # premiere fois, un corps jamais affiche donne un sizeHint() trop
        # petit (plancher fige trop bas, titre ecrase).
        QTimer.singleShot(0, self._remeasure)

    def _remeasure(self):
        try:
            if not self._collapsed:
                self.refresh_layout()
                _reflow_ancestors(self)
        except RuntimeError:   # widget deja detruit
            pass

    def refresh_layout(self):
        """Force CE sous-groupe (et tout ce qu'il contient, meme imbrique
        plus bas) a recalculer sa taille tout de suite — voir
        _activate_layout_tree/_Section.refresh_min_height, meme necessite/
        memes raisons (voir la remarque de l'utilisateur, capture a
        l'appui, "il y a des bugs importants quand on plie/deplie les
        sous sections").

        setMinimumHeight explicite (voir _Section.set_collapsed, MEME
        necessite) : sans lui, ce sous-groupe n'a AUCUN plancher propre —
        des que l'espace total disponible manque un peu (fenetre pas assez
        haute, ou juste apres un depli qui agrandit soudain le contenu),
        Qt le COMPRESSE en dessous de son besoin reel plutot que de
        respecter le minimumHeight de CHAQUE ligne de tableau a l'interieur
        (voir _lock_min_height) — un tableau "ecrase" (texte/sliders
        chevauches) meme si chaque ligne a pourtant son propre plancher —
        voir la remarque de l'utilisateur, capture a l'appui, "corrige
        l'ecrasement du tableau ... que tu le prennes systematiquement en
        compte pour tous les tableaux"."""
        _activate_layout_tree(self)
        self.setMinimumHeight(self.sizeHint().height() if not self._collapsed else 0)
        self.updateGeometry()

    def is_collapsed(self) -> bool:
        return self._collapsed

    def _refresh_chevron(self):
        self._chevron.setCollapsed(self._collapsed)

def _reflow_ancestors(widget: QWidget):
    """Recalcule les planchers de hauteur de TOUS les _Section/_SubSection
    qui contiennent `widget` : chacun garde le sizeHint() de son dernier
    depli (voir _Section.set_collapsed/_SubSection.refresh_layout), perime
    des qu'un descendant se plie/deplie ou change d'espacement — l'espace en
    trop (ou manquant) se repartissait alors entre titre et contenu, d'ou
    des ecarts incoherents. Planchers d'abord leves, layouts recalcules une
    fois depuis le plus externe, puis replaces du plus interne au plus
    externe."""
    chain = []
    parent = widget.parentWidget()
    while parent is not None:
        if isinstance(parent, (_Section, _SubSection)):
            chain.append(parent)
        parent = parent.parentWidget()
    _reflow_chain(chain)

def _reflow_all(root: QWidget):
    """Meme recalcul que _reflow_ancestors pour tous les titres sous `root`
    (apres un changement d'espacements/de marges applique en direct)."""
    _reflow_chain(list(reversed(root.findChildren(_Section) + root.findChildren(_SubSection))))

def _reflow_chain(chain: list):
    """`chain` : du plus interne au plus externe."""
    open_items = [item for item in chain if not item.is_collapsed()]
    for item in open_items:
        item.setMinimumHeight(0)
    for item in chain:
        if item.parentWidget() is not None and not any(
                isinstance(p, (_Section, _SubSection)) for p in _ancestors(item)):
            _activate_layout_tree(item)
    for item in open_items:
        item.setMinimumHeight(item.sizeHint().height())
        item.updateGeometry()

def _ancestors(widget: QWidget):
    parent = widget.parentWidget()
    while parent is not None:
        yield parent
        parent = parent.parentWidget()

def _make_accordion(items: list):
    """Regroupe plusieurs _Section/_SubSection SOEURS en accordeon : en
    deplier une replie automatiquement les AUTRES du groupe — sauf en
    maintenant CTRL enfonce au clic (voir la remarque de l'utilisateur,
    "quand une section est depliee, et qu'on en deplie une seconde, la
    premiere se replie automatiquement sauf si on appuie sur la touche
    CTRL en meme temps").

    Se branche sur `item.head.clicked` (voir _Section/_SubSection.head),
    APRES la connexion existante `head.clicked -> item.toggle` (faite en
    premier, dans __init__) : au moment ou ce gestionnaire s'execute,
    `item` a donc DEJA bascule — is_collapsed() reflete l'etat REEL apres
    le clic, pas besoin de le calculer a la main. QApplication.
    keyboardModifiers() (pas event.modifiers(), _SectionHeader.clicked
    n'en transporte pas) : lu ICI, dans le gestionnaire du CLIC reel —
    jamais reevalue plus tard pour un set_collapsed() PROGRAMMATIQUE (voir
    plus bas, qui appelle set_collapsed directement, pas item.toggle() —
    ne re-declenche donc jamais ce gestionnaire, pas de recursion)."""
    for item in items:
        def _on_clicked(item=item):
            if item.is_collapsed():
                return  # ce clic vient de REPLIER item, rien a faire
            if QApplication.keyboardModifiers() & Qt.ControlModifier:
                return  # CTRL enfonce : laisse les autres tels quels
            for other in items:
                if other is not item and not other.is_collapsed():
                    other.set_collapsed(True)
        item.head.clicked.connect(_on_clicked)

_TAB_LOOK: dict = {}


def set_tab_look(values: dict) -> None:
    _TAB_LOOK.clear()
    _TAB_LOOK.update(values)


class _TabStrip(QWidget):
    """Barre d'onglets texte (libelles en petites capitales, soulignement
    accent sur l'onglet actif) — reutilisee a 2 niveaux (voir SettingsWindow.
    __init__ : General/Colonnes) et (voir _build_columns_page : Type/Projets/
    Sous-projets a l'interieur de l'onglet Colonnes). Pas de QTabWidget natif
    Qt : son chrome ne suit pas la palette M de cette fenetre, contrairement
    a ces boutons peints via stylesheet, ici sans effet visible autre que le
    changement d'onglet (le contenu de chaque page reste un widget normal,
    voir SettingsWindow._main_stack/_columns_stack)."""

    changed = Signal(int)

    def __init__(self, labels: list[str], parent=None):
        super().__init__(parent)
        self._index = 0
        self._btns: list[QPushButton] = []
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(4)
        for i, label in enumerate(labels):
            btn = QPushButton(label.upper())
            btn.setFlat(True)
            btn.setCursor(Qt.PointingHandCursor)
            btn.setFocusPolicy(Qt.NoFocus)
            btn.setFixedHeight(36)
            btn.setFont(_qfont(11, 600, tracking=0.4))
            btn.clicked.connect(lambda _checked=False, idx=i: self.setCurrentIndex(idx))
            layout.addWidget(btn)
            self._btns.append(btn)
        layout.addStretch(1)
        self._refresh()

    def _refresh(self):
        look = _TAB_LOOK
        # Rien n'a change depuis la derniere fois (reglages et onglet en cours) : aucune feuille de style a
        # reposer — chaque setStyleSheet repolit son bouton, cher sur une fenetre aux milliers de widgets.
        try:
            tab_height = max(16, int(look.get("tabs_height", 36)))
            spacing = max(0, int(look.get("tabs_spacing", 4)))
        except (TypeError, ValueError):
            tab_height, spacing = 36, 4
        sig = (self._index, M["label_dim"], M["value_fg"], M["section_title"],
               tuple(sorted((k, repr(v)) for k, v in look.items() if k.startswith("tabs_") or k == "colors")))
        if sig == getattr(self, "_look_sig", None):
            return
        self._look_sig = sig
        colors = look.get("colors") or {}
        bg = _resolve_color_value(look.get("tabs_bg_color", "#00000000"), colors)
        active_bg = _resolve_color_value(look.get("tabs_active_bg_color", "#00000000"), colors)
        hover_bg = _resolve_color_value(look.get("tabs_hover_bg_color", "#00000000"), colors)
        fg = _resolve_color_value(look.get("tabs_font_color", M["section_title"]), colors)
        enabled = look.get("tabs_border_enabled") or {}
        if not isinstance(enabled, dict):
            enabled = dict.fromkeys(("top", "right", "bottom", "left"), bool(enabled))
        border_colors = look.get("tabs_border") or {}
        if not isinstance(border_colors, dict):
            border_colors = dict.fromkeys(("top", "right", "bottom", "left"), border_colors)
        thickness = max(0, int(look.get("tabs_border_thickness", 2)))
        radius = look.get("tabs_corner_radius") or 0
        if not isinstance(radius, dict):
            radius = dict.fromkeys(("top_left", "top_right", "bottom_right", "bottom_left"), radius)
        corners = " ".join(f"border-{css}-radius: {max(0, int(radius.get(key, 0)))}px;" for key, css in (
            ("top_left", "top-left"), ("top_right", "top-right"),
            ("bottom_right", "bottom-right"), ("bottom_left", "bottom-left")))
        borders = " ".join(
            f"border-{side}: {thickness}px solid {_resolve_color_value(border_colors.get(side, M['accent']), colors)};"
            if enabled.get(side) and thickness else f"border-{side}: none;"
            for side in ("top", "right", "bottom", "left"))
        family = look.get("tabs_font_family") or ""
        if family:
            from browser_core import _resolve_font_family
            family = _resolve_font_family(family, int(look.get("tabs_font_size", 11)),
                                          700 if look.get("tabs_font_bold") else 400)
        # La police est AUSSI posee dans la feuille de style de chaque tab : la feuille globale des boutons
        # (`QPushButton { font-size... }`) l'emporte sinon sur `setFont` (les polices des tabs ne marchaient pas).
        font_css = (f'font-family: "{family}"; ' if family else "") + (
            f"font-size: {max(6, int(look.get('tabs_font_size', 11)))}px; "
            f"font-weight: {'bold' if look.get('tabs_font_bold', True) else 'normal'}; "
            f"font-style: {'italic' if look.get('tabs_font_italic', False) else 'normal'};")
        inactive_enabled = look.get("tabs_inactive_border_enabled") or {}
        if not isinstance(inactive_enabled, dict):
            inactive_enabled = dict.fromkeys(("top", "right", "bottom", "left"), bool(inactive_enabled))
        inactive_colors = look.get("tabs_inactive_border") or {}
        if not isinstance(inactive_colors, dict):
            inactive_colors = dict.fromkeys(("top", "right", "bottom", "left"), inactive_colors)
        inactive_width = max(0, int(look.get("tabs_inactive_border_thickness", 1)))
        inactive_borders = " ".join(
            f"border-{side}: {inactive_width}px solid "
            f"{_resolve_color_value(inactive_colors.get(side, M['panel_border']), colors)};"
            if inactive_enabled.get(side) and inactive_width else f"border-{side}: none;"
            for side in ("top", "right", "bottom", "left"))
        self.layout().setSpacing(spacing)
        for i, btn in enumerate(self._btns):
            font = _qfont(max(6, int(look.get("tabs_font_size", 11))),
                          700 if look.get("tabs_font_bold", True) else 400, tracking=0.4)
            if family:
                font.setFamily(family)
            font.setItalic(bool(look.get("tabs_font_italic", False)))
            btn.setFont(font)
            btn.setFixedHeight(tab_height)
            if i == self._index:
                btn.setStyleSheet(
                    f"QPushButton {{ color: {fg}; background: {active_bg}; {font_css} "
                    f"{borders} {corners} padding: 0 14px; }}"
                )
            else:
                btn.setStyleSheet(
                    f"QPushButton {{ color: {M['label_dim']}; background: {bg}; {font_css} "
                    f"{inactive_borders} {corners} padding: 0 14px; }}"
                    f"QPushButton:hover {{ color: {M['value_fg']}; background: {hover_bg}; }}"
                )

    def setCurrentIndex(self, index: int):
        if index == self._index:
            return
        self._index = index
        self._refresh()
        self.changed.emit(index)

    def currentIndex(self) -> int:
        return self._index

# Couleur d'entete commune (Tableaux > Couleur d'en-tete) pour les entetes
# construits apres coup (tableaux "un reglage par ligne", voir _attach_flat_head).
_TABLE_HEAD: dict = {"bg": None, "cell_bg": None}   # entetes de tableau / legendes des cellules divisees

def _restyle_table_head(head: QWidget, radius: int = 0):
    """(Re)applique le fond/filet/coins de l'entete d'un tableau — coins HAUTS
    seulement (voir _TableFrame : c'est elle qui touche le coin haut du
    cadre, pas de coins bas puisqu'une ligne de donnees suit toujours).

    Fond = M['table_head_bg'] par defaut (la pastille "Tableau - entete" de
    Couleurs), SAUF si `head._custom_bg` a ete pose (voir SettingsWindow.
    _apply_table_head_color, Tableaux > Couleur d'en-tete — voir la
    remarque de l'utilisateur, "ajoute couleur d'entete pour les
    tableaux") : un selecteur PARMI les pastilles semantiques, comme
    Colonnes > Couleur des entetes mais pour les tableaux "fermes" de
    CETTE fenetre (Polices/Geometrie, les seuls a avoir un entete) plutot
    que les colonnes du navigateur principal."""
    bg = getattr(head, "_custom_bg", None) or _TABLE_HEAD["bg"] or M["table_head_bg"]
    _apply_stylesheet_cached(
        head,
        f"#TableHead {{ background: {bg}; border-bottom: {_inner_h_edge()}; "
        f"border-top-left-radius: {radius}px; border-top-right-radius: {radius}px; }}",
    )

def _finish_reorder(owner) -> None:
    """Fin d'un deplacement par _ReorderOverlay (colonnes d'un entete, sous-cellules) : l'element tire
    passe a l'emplacement vise. `owner` a `_reorder` (l'overlay), `_order` et `setOrder`."""
    overlay, owner._reorder = owner._reorder, None
    owner.unsetCursor()
    gap = overlay.target
    overlay.hide()
    overlay.deleteLater()
    if gap is None:
        return
    order = [i for i in owner._order if i != overlay.source]
    order.insert(gap - (1 if gap > owner._order.index(overlay.source) else 0), overlay.source)
    owner.setOrder(order)


class _ReorderOverlay(QWidget):
    """Couche posee sur le tableau pendant un deplacement (colonne, sous-cellule, ligne) — MEMES regles
    pour les trois : l'element suit le curseur a opacite 75 % (GHOST_OPACITY = DRAG_GHOST_OPACITY), son emplacement
    d'origine reste visible a 25 % (ORIGIN_OPACITY), et UN SEUL emplacement est montre : le plus proche
    (demande de l'utilisateur, pour tout deplacement de l'appli, actuel et futur — plus de marques sur
    les autres emplacements). `axis` : "x" (colonnes, sous-cellules : `head._column_spans()` = abscisses)
    ou "y" (lignes : ordonnees). `head` fournit `_column_spans()` et `_order` (indices logiques dans
    l'ordre affiche)."""

    GHOST_OPACITY = DRAG_GHOST_OPACITY
    ORIGIN_OPACITY = 0.25

    def __init__(self, frame: QWidget, head, source: int, ghost, offset: int, grab_dx: int, axis: str = "x"):
        super().__init__(frame)
        self.setAttribute(Qt.WA_TransparentForMouseEvents, True)
        self.setGeometry(frame.rect())
        self.head, self.source, self.ghost, self.offset, self.grab_dx = head, source, ghost, offset, grab_dx
        self.axis = axis
        spans = head._column_spans()
        order = head._order
        self.gaps = [spans[i][0] for i in order] + [spans[order[-1]][1]]
        self.origin = spans[source]
        self.cursor_x = spans[source][0] + grab_dx
        self.target: int | None = None
        self.show()
        self.raise_()

    def _center(self) -> int:
        """Centre de l'element tire, le long de l'axe."""
        return self.cursor_x - self.grab_dx + (self.origin[1] - self.origin[0]) // 2

    def follow(self, x: int):
        self.cursor_x = x
        position = self.head._order.index(self.source)
        nearest = min(range(len(self.gaps)), key=lambda k: abs(self.gaps[k] - self._center()))
        self.target = None if nearest in (position, position + 1) else nearest
        self.update()

    def _band(self, start: int, size: int) -> QRect:
        """Bande perpendiculaire a l'axe, de `start` (repere de l'axe) sur `size` px."""
        if self.axis == "y":
            return QRect(0, self.offset + start, self.width(), size)
        return QRect(self.offset + start, 0, size, self.height())

    def paintEvent(self, event):
        p = QPainter(self)
        accent = QColor(M["accent"])
        # Emplacement d'origine a 25 % : voile du fond de la fenetre a 75 % par-dessus.
        veil = QColor(getattr(self, "veil_color", None) or M["panel_bg"])     # menus : leur fond
        veil.setAlpha(round(255 * (1.0 - self.ORIGIN_OPACITY)))
        p.fillRect(self._band(self.origin[0], self.origin[1] - self.origin[0]), veil)
        # Un seul emplacement : celui vise (aucun quand l'element resterait a sa place).
        if self.target is not None:
            gap = self.gaps[self.target]
            glow = QColor(accent)
            glow.setAlpha(60)
            p.fillRect(self._band(gap - 6, 12), glow)
            p.fillRect(self._band(gap - 1, 3), accent)
        p.setOpacity(self.GHOST_OPACITY)
        start = self.cursor_x - self.grab_dx
        if self.axis == "y":
            p.drawPixmap(0, self.offset + start, self.ghost)
            rect = QRect(0, self.offset + start, self.ghost.width() - 1, self.ghost.height() - 1)
        else:
            p.drawPixmap(self.offset + start, 0, self.ghost)
            rect = QRect(self.offset + start, 0, self.ghost.width() - 1, self.ghost.height() - 1)
        p.setOpacity(1.0)
        p.setPen(accent)
        p.drawRect(rect)
        p.end()


class _ResizableTableHeader(QWidget):
    """En-tete de tableau ferme (voir l'ancienne _table_header, dont c'est
    desormais l'implementation) — chaque colonne a largeur FIXE (pas la
    colonne extensible, largeur 0 dans `cells`) a une poignee de
    redimensionnement sur sa bordure droite, exactement comme les colonnes
    du navigateur principal (voir pipeline_browser.Column._in_resize_zone)
    — voir la remarque de l'utilisateur : "c'est bien ce que je voulais
    depuis le debut". `resized` (index de colonne, nouvelle largeur) permet
    a l'appelant de repercuter le changement sur la cellule correspondante
    de CHAQUE ligne de donnees (voir _wire_resizable_columns) ; la colonne
    extensible absorbe seule la difference (stretch=1, voir Qt), quelle
    que soit sa position parmi les autres.

    La bordure de chaque colonne est detectee via la geometrie REELLE de sa
    cellule (cell.geometry(), fixee par le layout au premier affichage),
    pas en recalculant une position a partir des largeurs statiques de
    `cells` : la colonne extensible peut se trouver n'importe ou dans
    l'ordre (voir _GeoTable, ou elle est la PREMIERE) et sa largeur reelle
    n'est de toute facon connue qu'une fois le layout resolu."""

    resized = Signal(int, int)  # (index de colonne, nouvelle largeur)
    selectionChanged = Signal()
    columnMoved = Signal()      # l'ordre des colonnes a change (voir setOrder)

    _MARGIN = 5
    _MIN_WIDTH = 60
    _MAX_WIDTH = 640
    # Colonnes LIBRES (tableaux de la v2, voir setFreeColumns) : toutes a largeur fixe, aucune
    # colonne extensible ni plafond ; c'est le tableau qui change de largeur (somme des colonnes).
    _free = False
    _FREE_MIN, _FREE_MAX = 24, 100000

    def paintEvent(self, event):
        super().paintEvent(event)
        spans = self._column_spans()
        _paint_inner_vlines(self, [spans[i][0] for i in self._order[1:]])

    def event(self, event):
        handled = super().event(event)
        # Voir _TableRow.event : les filets V suivent les cellules apres le layout.
        if event.type() == QEvent.LayoutRequest:
            self.update()
        if self._badge_cols and event.type() in (QEvent.LayoutRequest, QEvent.Resize):
            self._place_width_badges()           # la largeur REELLE n'est connue qu'apres le layout
        return handled

    _badge_cols: list = []   # (classe : event() est appele avant la fin de __init__)

    def __init__(self, cells: list[tuple[str, int]], parent=None):
        super().__init__(parent)
        self.setObjectName("TableHead")
        self.setAttribute(Qt.WA_StyledBackground, True)
        self.setFixedHeight(26)
        self.setMouseTracking(True)
        _restyle_table_head(self)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        self._widths = [w for _text, w in cells]
        self._cells: list[QLabel] = []
        self._padding_lr = (10, 10)
        self._selected: set[int] = set()          # colonnes selectionnees (multi)
        self._order: list[int] = list(range(len(cells)))   # ordre d'affichage (indices LOGIQUES des colonnes)
        self._titles: list[str] = [text.upper() for text, _w in cells]
        self._reorderable = False
        self._reorder = None                      # deplacement de colonne en cours (_ReorderOverlay)
        self._badge_cols: list[int] = []          # colonnes dont l'encart de largeur est affiche (glisser en cours)
        self._equal_toggles: list = []            # True = colonne egalisable quand plusieurs colonnes sont selectionnees
        self._press_pos = None
        self._stretch_fixed: dict[int, int] = {}   # colonne extensible figee a une largeur (groupe egal)
        self._stretch_manual: set[int] = set()   # colonne extensible figee a la main (bord droit glisse)
        self._edge_pinned = False   # groupe egal colle au bord droit : il y reste (les autres colonnes s'y adossent)
        for text, width in cells:
            cell = QLabel(text.upper())
            cell.setFont(_qfont(9, 600))
            # Sans ca, chaque libelle occupe TOUTE sa colonne bord a bord
            # (aucun espace vide entre les cellules, voir le layout
            # ci-dessus) : un vrai clic a la souris sur une bordure de
            # colonne atterrit alors sur ce QLabel (voir QWidget.childAt),
            # PAS sur _ResizableTableHeader lui-meme — mousePressEvent/
            # mouseMoveEvent ci-dessous ne voyaient donc jamais rien passer
            # (voir la remarque de l'utilisateur, capture a l'appui : "ca ne
            # fonctionne pas"). Rendu transparent aux evenements souris, ce
            # widget laisse passer le clic/survol jusqu'a son parent.
            cell.setAttribute(Qt.WA_TransparentForMouseEvents, True)
            self._cells.append(cell)
            self._equal_toggles.append(True)     # colonne pouvant etre egalisee (pas l'extensible d'un tableau libelle/valeur)
            if width:
                cell.setFixedWidth(width)
                layout.addWidget(cell, 0)
            else:
                layout.addWidget(cell, 1)
        layout.addStretch(0)  # recueille le vide quand une colonne extensible est figee
        for i in range(len(self._cells)):
            self._refresh_cell_style(i)
        self._resizing_index: int | None = None
        self._resizing_sign = 1
        self._resize_start_x = 0
        self._resize_start_width = 0
        self._resizable = True

    def setFreeColumns(self, defaults: dict[int, int]):
        """Passe en colonnes libres : chaque colonne extensible (largeur 0) est figee a `defaults[i]`.
        Plus aucune colonne n'absorbe les changements des autres, plus de largeur maxi ni de limite
        de groupe : le tableau s'elargit ou se retrecit avec ses colonnes."""
        self._free = True
        self._stretch_origin = [i for i, w in enumerate(self._widths) if not w]
        self._equal_toggles = [True] * len(self._cells)
        layout = self.layout()
        for i in self._stretch_origin:
            width = max(self._FREE_MIN, int(defaults.get(i, 160)))
            layout.setStretchFactor(self._cells[i], 0)
            self._set_width(i, width)

    def _min_for(self, index: int) -> int:
        """Largeur mini d'une colonne. En colonnes libres, le contenu des cellules n'est JAMAIS une
        contrainte : seul un plancher technique (les cellules s'adaptent, voir build_cells_table)."""
        return self._FREE_MIN if self._free else self._MIN_WIDTH

    def _max_width(self) -> int:
        return self._FREE_MAX if self._free else self._MAX_WIDTH

    def disableEqualToggle(self, index: int):
        """Cette colonne ne s'egalise pas avec les autres colonnes selectionnees (ex. colonne
        extensible d'un tableau libelle/valeur)."""
        self._equal_toggles[index] = False

    def setResizable(self, enabled: bool):
        """Tableaux > Colonnes dimensionnables (voir SettingsWindow._section_
        tables) : desactive, ni le curseur ni le glisser ne s'activent plus
        sur aucune bordure — meme reglage que celui qui gouverne deja les
        colonnes du navigateur principal (voir pipeline_browser._Column._in_
        resize_zone), applique ici a ses propres tableaux."""
        self._resizable = bool(enabled)
        if not self._resizable and self._resizing_index is not None:
            self._resizing_index = None
            self.unsetCursor()

    def setCellPadding(self, left: int, right: int):
        """Tableaux > Padding des cellules (voir SettingsWindow.
        _apply_cell_padding) : suit le padding GAUCHE/DROITE des lignes de
        donnees (pas Haut/Bas — cette entete a une hauteur fixe, 26px, son
        contenu deja centre verticalement par le layout) pour que le
        libelle de chaque colonne reste aligne avec le contenu de la
        colonne en dessous."""
        self._padding_lr = (max(0, int(left)), max(0, int(right)))
        for i in range(len(self._cells)):
            self._refresh_cell_style(i)

    def _refresh_cell_style(self, index: int):
        cell = self._cells[index]
        # Style propre du titre (« Override settings » > Entete entier / Cellule en cours, voir
        # apply_part_looks) : fond, police, couleur du texte.
        look = getattr(cell, "_head_look", None) or {}
        if not hasattr(cell, "_head_font_orig"):
            cell._head_font_orig = QFont(cell.font())
        font = look.get("font") or {}
        if font:
            from fm_theme.theme import text_look_font
            cell.setFont(text_look_font(cell._head_font_orig, font))
        else:
            cell.setFont(cell._head_font_orig)
        sel = _selection_color(56)
        bg = (f"rgba({sel.red()}, {sel.green()}, {sel.blue()}, {sel.alpha()})" if index in self._selected
              else look.get("bg") or "transparent")
        cell.setStyleSheet(
            f"color: {font.get('color') or M['table_head_fg']}; background: {bg}; "
            f"padding: 0 {self._padding_lr[1]}px 0 {self._padding_lr[0]}px;"
        )

    def _column_at(self, x: int) -> int | None:
        for i, (left, right) in enumerate(self._column_spans()):
            if left <= x < right:
                return i
        return None

    def _place_toggles(self):
        """Ancien emplacement des cases « largeurs egales » (supprimees : selectionner plusieurs
        colonnes suffit). Conserve pour les appelants."""

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if self._stretch_fixed:
            self._apply_equal()
        self._place_toggles()

    def showEvent(self, event):
        super().showEvent(event)
        self._place_toggles()

    def _select_click(self, index: int, shift: bool):
        """Clic sur un titre : seul = cette colonne uniquement (re-clic sur la
        seule colonne selectionnee = deselection) ; Maj = ajoute/retire."""
        if shift:
            self._selected ^= {index}
        elif self._selected == {index}:
            self._selected = set()
        else:
            self._selected = {index}
        for i in range(len(self._cells)):
            self._refresh_cell_style(i)
        self._release_stretch(self._equal_group())
        self.selectionChanged.emit()

    def _equal_group(self) -> list[int]:
        """Colonnes selectionnees (au moins 2) : elles gardent TOUTES exactement la meme largeur."""
        group = sorted(i for i in self._selected if self._equal_toggles[i])
        return group if len(group) > 1 else []

    def _equal_limits(self, group: list[int]) -> tuple[int, int]:
        """(nb de colonnes du groupe, largeur maxi commune) : avec une colonne
        extensible dans le groupe, tout doit tenir dans la largeur de l'entete."""
        n = len(group)
        other = sum(w for i, w in enumerate(self._widths) if w and i not in group)
        other += sum(w for i, w in self._stretch_fixed.items() if i not in group)
        room = (self.width() - other) // n if n else self._MAX_WIDTH
        return n, max(self._MIN_WIDTH, min(self._MAX_WIDTH, room))

    def _set_group_width(self, group: list[int], width: int):
        """Applique `width` a TOUT le groupe d'un coup (colonnes extensibles
        incluses : figees a cette largeur, le reste de l'entete reste vide)."""
        for i in group:
            if self._widths[i]:
                if self._widths[i] != width:
                    self._set_width(i, width, place=False)
            elif self._stretch_fixed.get(i) != width:
                self._stretch_fixed[i] = width
                self._cells[i].setFixedWidth(width)
                self.resized.emit(i, width)
        self._place_toggles()

    def _release_stretch(self, keep: list[int]):
        """Rend leur elasticite aux colonnes extensibles sorties du groupe."""
        keep = list(keep) + list(self._stretch_manual)
        for i in [i for i in self._stretch_fixed if i not in keep]:
            del self._stretch_fixed[i]
            self._cells[i].setMinimumWidth(0)
            self._cells[i].setMaximumWidth(16777215)
            self.resized.emit(i, 0)

    def _apply_equal(self):
        """Egalise les colonnes a toggle actif a la plus large (ou, avec une
        colonne extensible dans le groupe, a ce qui tient dans l'entete)."""
        group = self._equal_group()
        self._release_stretch(group)
        if not group:
            self._edge_pinned = False
            return
        n, room = self._equal_limits(group)
        has_stretch = any(not self._widths[i] for i in group)
        widest = max([self._widths[i] for i in group if self._widths[i]] + [self._stretch_fixed.get(i, 0) for i in group])
        width = min(room, widest) if has_stretch else widest
        if has_stretch and (not widest or self._edge_pinned):
            width = room
        self._edge_pinned = has_stretch and width >= room
        self._set_group_width(group, max(self._MIN_WIDTH, width))

    def _column_spans(self) -> list[tuple[int, int]]:
        """(bord gauche, bord droit) de chaque colonne, indexee par colonne LOGIQUE, calcule a partir
        des largeurs fixes ET de la largeur REELLE de ce widget (self.width(), toujours fiable —
        contrairement a cell.geometry(), qui peut ne pas encore refleter le dernier layout) : une
        colonne extensible recoit le meme partage de l'espace restant qu'un stretch=1 de QHBoxLayout,
        ou qu'elle soit dans l'ordre d'affichage."""
        free = [i for i, w in enumerate(self._widths) if not w and i not in self._stretch_fixed]
        used = sum(w for w in self._widths if w) + sum(self._stretch_fixed.values())
        stretch_width = max(0, self.width() - used) // len(free) if free else 0
        spans: list = [None] * len(self._widths)
        pos = 0
        for i in self._order:
            width = self._widths[i] or self._stretch_fixed.get(i, stretch_width)
            spans[i] = (pos, pos + width)
            pos += width
        return spans

    def _column_edges(self) -> list[int]:
        """Position (x) du bord droit de chaque colonne (indexee par colonne logique)."""
        return [right for _left, right in self._column_spans()]

    def _draggable_boundaries(self) -> list[tuple[int, int, int]]:
        """Bordures REELLEMENT glissables : (position x, index de colonne controlee, signe) — signe +1
        si glisser vers la DROITE agrandit cette colonne (sa bordure DROITE, le cas normal), -1 si
        glisser vers la DROITE la retrecit (sa bordure GAUCHE — n'existe que quand la colonne qui
        la PRECEDE a l'ecran est extensible : sans ce cas la bordure ne controlait RIEN)."""
        spans = self._column_spans()
        boundaries: list[tuple[int, int, int]] = []
        previous = None
        for i in self._order:
            left, right = spans[i]
            if self._widths[i] == 0:
                previous = i
                continue
            if previous is not None and self._widths[previous] == 0:
                boundaries.append((left, i, -1))
            boundaries.append((right, i, 1))
            previous = i
        return boundaries

    def _boundary_at(self, x: int) -> tuple[int, int] | None:
        if not self._resizable:
            return None
        for pos, index, sign in self._draggable_boundaries():
            if pos - self._MARGIN <= x <= pos + self._MARGIN:
                return index, sign
        return None

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            hit = self._boundary_at(event.position().toPoint().x())
            if hit is not None:
                self.beginDrag(hit, event.globalPosition().toPoint().x())
                event.accept()
                return
            self._press_pos = event.position().toPoint()
            self._press_shift = bool(event.modifiers() & Qt.ShiftModifier)
        super().mousePressEvent(event)

    def beginDrag(self, hit: tuple, global_x: int):
        """Debut d'un glisser de bordure (`hit` = (colonne, signe), voir _boundary_at). Public :
        les cellules des lignes (settings_cells) saisissent la MEME bordure que l'entete."""
        self._resizing_index, self._resizing_sign = hit
        self._resize_start_x = global_x
        idx = self._resizing_index
        left, right = self._column_spans()[idx]
        self._resize_start_width = self._widths[idx] or (right - left)

    def dragTo(self, global_x: int):
        delta = global_x - self._resize_start_x
        idx = self._resizing_index
        stretch = not self._widths[idx]
        group = self._equal_group()
        floor = max(self._min_for(i) for i in (group if idx in group else [idx]))
        new_width = max(floor, self._resize_start_width + self._resizing_sign * delta)
        if not stretch:
            new_width = min(self._max_width(), new_width)
        if idx in group:
            if not self._free:              # colonnes libres : aucune limite, le tableau s'elargit
                limit = self._equal_limits(group)[1]
                new_width = min(new_width, limit)
                self._edge_pinned = any(not self._widths[i] for i in group) and new_width >= limit
            self._set_group_width(group, new_width)
            self._show_width_badges(group)
        else:
            self._set_width(self._resizing_index, new_width)
            if any(not self._widths[i] for i in group):
                self._apply_equal()   # le groupe colle au bord se serre contre la colonne qui grandit
            self._show_width_badges([idx])

    def endDrag(self):
        self._resizing_index = None
        self._restore_titles()

    def _show_width_badges(self, columns: list[int]):
        """Pendant un redimensionnement, un encart dans l'entete de chaque colonne concernee affiche
        sa largeur (le titre reste)."""
        self._badge_cols = list(columns)
        self.layout().activate()
        self._place_width_badges()

    def _place_width_badges(self):
        badges = _width_badges(self, len(self._cells))
        for i, badge in enumerate(badges):
            if i not in self._badge_cols:
                badge.hide()
                continue
            rect = self._cells[i].geometry()     # colonne telle qu'affichee (largeur reelle)
            badge.show_on(rect, rect.width())

    def _restore_titles(self):
        """Fin du glisser : les encarts disparaissent (les titres n'ont jamais change)."""
        self._badge_cols = []
        _hide_width_badges(self)

    def isDragging(self) -> bool:
        return self._resizing_index is not None

    def setReorderable(self, enabled: bool):
        self._reorderable = bool(enabled)

    def order(self) -> list[int]:
        return list(self._order)

    def setOrder(self, order: list[int], notify: bool = True):
        """Ordre d'affichage des colonnes (indices logiques). Replace les titres ; les lignes du
        tableau suivent par `columnMoved`."""
        order = [int(i) for i in order]
        if sorted(order) != list(range(len(self._widths))) or order == self._order:
            return
        self._order = order
        layout = self.layout()
        for cell in self._cells:
            layout.removeWidget(cell)
        for pos, i in enumerate(order):
            layout.insertWidget(pos, self._cells[i], 0 if self._widths[i] else 1)
        self.update()
        if notify:
            self.columnMoved.emit()

    def _begin_reorder(self, x: int):
        index = self._column_at(x)
        if index is None:
            return
        frame = self.parentWidget()
        offset = self.mapTo(frame, QPoint(0, 0)).x()
        left, right = self._column_spans()[index]
        ghost = frame.grab(QRect(offset + left, 0, right - left, frame.height()))
        self._reorder = _ReorderOverlay(frame, self, index, ghost, offset, x - left)
        self.setCursor(Qt.ClosedHandCursor)

    def _update_reorder(self, x: int):
        self._reorder.follow(x)

    def _end_reorder(self):
        _finish_reorder(self)

    def mouseMoveEvent(self, event):
        if self._resizing_index is not None:
            self.dragTo(event.globalPosition().toPoint().x())
            event.accept()
            return
        if self._reorderable and self._press_pos is not None and event.buttons() & Qt.LeftButton:
            x = event.position().toPoint().x()
            # Deplacer = Ctrl + glisser (demande de l'utilisateur, pour tout deplacement de l'appli).
            if (self._reorder is None and QApplication.keyboardModifiers() & Qt.ControlModifier
                    and (event.position().toPoint() - self._press_pos).manhattanLength() > 6):
                self._begin_reorder(self._press_pos.x())
            if self._reorder is not None:
                self._update_reorder(x)
                event.accept()
                return
        hit = self._boundary_at(event.position().toPoint().x())
        self.setCursor(Qt.SizeHorCursor if hit is not None else Qt.ArrowCursor)
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        if self._resizing_index is not None:
            self._resizing_index = None
            self._restore_titles()
            event.accept()
            return
        if self._reorder is not None:
            self._end_reorder()
            self._press_pos = None
            event.accept()
            return
        pos, self._press_pos = self._press_pos, None
        if event.button() == Qt.LeftButton and pos is not None and (
                event.position().toPoint() - pos).manhattanLength() <= 4:
            index = self._column_at(pos.x())
            if index is not None:
                self._select_click(index, getattr(self, '_press_shift', False))
        super().mouseReleaseEvent(event)

    def leaveEvent(self, event):
        if self._resizing_index is None:
            self.unsetCursor()
        super().leaveEvent(event)

    def _set_width(self, index: int, width: int, place: bool = True):
        self._widths[index] = width
        self._cells[index].setFixedWidth(width)
        self.resized.emit(index, width)
        if place:
            self._place_toggles()

    def columnWidths(self) -> list[int]:
        """Voir setColumnWidths — a sauvegarder tel quel dans les reglages
        (un preset, voir SettingsWindow._current_values) : inclut aussi la
        largeur (0) de la colonne extensible, pour garder les INDICES
        alignes avec `cells` a la restauration."""
        return list(self._widths)

    def setColumnWidths(self, widths: list[int]):
        """Restaure des largeurs sauvegardees (voir columnWidths/
        SettingsWindow._apply_values_to_controls) — reutilise _set_width
        pour chaque colonne FIXE, qui repercute automatiquement sur la
        cellule correspondante de chaque ligne (voir _wire_resizable_
        columns) ; la colonne extensible (largeur 0 dans `cells`, jamais
        stockee) est ignoree, tout comme une liste trop courte/vide (ancien
        preset sans ce reglage — voir DEFAULT_SETTINGS)."""
        for i, width in enumerate(widths):
            if i < len(self._widths) and self._widths[i] and width:
                floor = self._FREE_MIN if self._free else self._MIN_WIDTH
                self._set_width(i, max(floor, min(self._max_width(), int(width))))

class _FlatColumnResizer(QObject):
    """Bordure libelle/controle glissable a la main, sur un tableau "ferme"
    SANS entete de colonnes (_build_flat_table/_section_headers, voir
    _table_row) — meme experience que _ResizableTableHeader (curseur au
    survol, glisser change la largeur) mais SANS widget d'entete a saisir
    puisque ces tableaux n'en ont pas : la bordure se saisit directement
    sur N'IMPORTE QUELLE ligne du tableau (installe en filtre d'evenements
    sur chacune, voir wire()) et gouverne TOUTES les lignes a la fois — une
    SEULE largeur de libelle partagee — voir la remarque de l'utilisateur,
    "je veux aussi pouvoir redimensionner les colonnes meme si le tableau
    n'a pas d'entete", "glisser la bordure entre libelle et controle, sur
    n'importe quelle ligne".

    Le controle reste TOUJOURS colle au bord droit de la ligne (voir la
    remarque de l'utilisateur, qui a tranche explicitement pour cette
    option) : seule la largeur du libelle change ; voir _build_flat_table/
    _section_headers, qui ajoutent l'espaceur extensible entre les deux
    necessaire pour ca (le libelle n'a plus lui-meme ce stretch=1, tenu
    desormais par cet espaceur dedie)."""

    resized = Signal(int)

    _MARGIN = 5
    _MIN_WIDTH = 60
    _MAX_WIDTH = 400

    def __init__(self, width: int, parent=None):
        super().__init__(parent)
        self._cells: list[QWidget] = []
        self._rows: list[QWidget] = []
        self._width = max(self._MIN_WIDTH, min(self._MAX_WIDTH, width))
        self._resizing = False
        self._resize_start_x = 0
        self._resize_start_width = self._width
        self._resizable = True

    def wire(self, row: QWidget, label_cell: QWidget):
        """A appeler pour CHAQUE ligne du tableau, juste apres l'avoir
        remplie (voir _build_flat_table/_section_headers) : `label_cell`
        (le libelle, 1er widget de la ligne) suit desormais la largeur
        partagee, `row` (la ligne entiere, pas juste le libelle — la
        bordure doit rester saisissable sur toute sa hauteur) recoit ce
        controleur comme filtre d'evenements."""
        label_cell.setFixedWidth(self._width)
        # Filet vertical libelle/controle (voir _TableRow) : au milieu de
        # l'espacement qui suit le libelle, comme la poignee de redimensionnement.
        row._v_boundary = lambda r=row, c=label_cell: (
            c.mapTo(r, QPoint(c.width(), 0)).x() + r.layout().spacing() // 2)
        self._cells.append(label_cell)
        self._rows.append(row)
        row._flat_resizer = self   # retrouve par _TableFrame (dimensions enregistrees)
        row.setMouseTracking(True)
        row.installEventFilter(self)

    def setResizable(self, enabled: bool):
        """Tableaux > Colonnes dimensionnables (voir SettingsWindow.
        _apply_columns_resizable) — meme reglage que celui qui gouverne
        deja _ResizableTableHeader, applique ici a ces tableaux SANS
        entete."""
        self._resizable = bool(enabled)
        if not self._resizable and self._resizing:
            self._resizing = False
            for row in self._rows:
                row.unsetCursor()

    def setWidth(self, width: int):
        self._width = max(self._MIN_WIDTH, min(self._MAX_WIDTH, int(width)))
        for cell in self._cells:
            cell.setFixedWidth(self._width)

    def width(self) -> int:
        return self._width

    def _boundary_x(self, row: QWidget) -> int:
        left, _top, _right, _bottom = row.layout().getContentsMargins()
        return left + self._width

    def eventFilter(self, row, event):
        if not self._resizable:
            return False
        etype = event.type()
        if etype == QEvent.MouseMove:
            if self._resizing:
                delta = event.globalPosition().toPoint().x() - self._resize_start_x
                self.setWidth(self._resize_start_width + delta)
                self.resized.emit(self._width)
                return True
            near = abs(event.position().toPoint().x() - self._boundary_x(row)) <= self._MARGIN
            row.setCursor(Qt.SizeHorCursor if near else Qt.ArrowCursor)
        elif etype == QEvent.MouseButtonPress:
            if event.button() == Qt.LeftButton and \
                    abs(event.position().toPoint().x() - self._boundary_x(row)) <= self._MARGIN:
                self._resizing = True
                self._resize_start_x = event.globalPosition().toPoint().x()
                self._resize_start_width = self._width
                return True
        elif etype == QEvent.MouseButtonRelease:
            if self._resizing:
                self._resizing = False
                self.resized.emit(self._width)
                return True
        elif etype == QEvent.Leave:
            if not self._resizing:
                row.unsetCursor()
        return False

def _table_header(cells: list[tuple[str, int]]) -> QWidget:
    """cells : (libelle, largeur) — largeur 0 => colonne extensible. Filet
    du bas SEULEMENT (separation avec la premiere ligne) : le perimetre du
    tableau est deja fourni par _table_frame, pas par l'entete elle-meme.
    Voir _ResizableTableHeader pour l'implementation (poignees de
    redimensionnement) et _wire_resizable_columns pour la repercuter sur
    les lignes de donnees."""
    return _ResizableTableHeader(cells)

def _wire_resizable_columns(head: _ResizableTableHeader, column_cells: dict[int, list[QWidget]]):
    """Repercute un redimensionnement de colonne (voir
    _ResizableTableHeader.resized) sur la cellule correspondante de CHAQUE
    ligne de donnees — `column_cells` : {index de colonne: [cellules de
    cette colonne, une par ligne]}, construit par l'appelant a partir des
    QWidget renvoyes par _table_cell (voir _GeoTable/_SimpleFontTable)."""
    rows = {c.parentWidget() for cells in column_cells.values() for c in cells if c.parentWidget()}

    def _on_resize(index: int, width: int):
        for cell in column_cells.get(index, []):
            if width:
                cell.setFixedWidth(width)
            else:  # colonne extensible relachee
                cell.setMinimumWidth(0)
                cell.setMaximumWidth(16777215)
        # Une cellule qui retrecit laissait sa trainee (ancien rectangle) a
        # l'ecran : on invalide la ligne entiere, repeinte apres le layout.
        for row in rows:
            row.update()

    head.resized.connect(_on_resize)

    # Colonne selectionnee : toute la colonne se teinte (les lignes peignent la
    # zone de la cellule d'entete correspondante, voir _TableRow.paintEvent).
    for row in rows:
        row._sel_head = head
        row.layout().addStretch(0)
    head.selectionChanged.connect(lambda: [r.update() for r in rows])

def _table_row(bg: str, first: bool) -> tuple[QWidget, QHBoxLayout]:
    """`first` : la toute premiere ligne de donnees colle directement sous
    l'entete (qui a deja son propre filet du bas) — seules les lignes
    SUIVANTES ont besoin de leur propre filet du haut ; aucune ligne ne
    dessine plus ses propres cotes gauche/droite (voir _table_frame)."""
    row = _TableRow()
    row.setObjectName("TableRow")
    row.setAttribute(Qt.WA_StyledBackground, True)
    # 36 : plancher de secours pour un contenu tres court (une seule ligne
    # de texte, sans note). Insuffisant des que la ligne contient un
    # libelle+note ou un controle plus haut — l'appelant DOIT alors finir
    # par _lock_min_height(row) une fois la ligne remplie, qui remplace ce
    # plancher par le vrai besoin (voir sa docstring pour le detail du bug
    # que ca corrige).
    row.setMinimumHeight(36)
    _restyle_table_row(row, bg, first)
    layout = QHBoxLayout(row)
    layout.setContentsMargins(0, 6, 0, 6)
    layout.setSpacing(0)
    return row, layout

def _lock_min_height(row: QWidget):
    """A appeler UNE FOIS une ligne/cellule de tableau REMPLIE (libelle,
    pastille, controle... voir les appelants de _table_row ET de
    _ColorGrid.__init__) — DOIT venir apres, jamais dans _table_row lui-
    meme : sizeHint() n'est fiable qu'une fois le contenu reellement present
    (une ligne vide ferait remonter un sizeHint() minuscule).

    Fait deux choses, INDISSOCIABLES : SizePolicy.Minimum sur la hauteur
    (le layout ne retrecit plus cette ligne PAR PREFERENCE quand de la
    place est disponible ailleurs) ET minimumHeight() fige a sizeHint()
    (ce que les CONTENEURS PARENTS — tableau, section, ascenseur de
    _build_content, voir _NoSqueezeScrollArea — accumulent pour savoir de
    combien d'espace le contenu a REELLEMENT besoin en tout ; SizePolicy
    seule n'y suffit pas, elle ne change rien a minimumSizeHint(), calcule
    par Qt a partir du minimumSize EXPLICITE de chaque enfant). Sans ce 2e
    volet, l'accumulation remontait un minimum sous-estime des qu'une ligne
    contenait un libelle sur 2 lignes/une pastille plus haute que le texte
    seul, et la fenetre entiere se retrouvait autorisee a s'ouvrir/se
    redimensionner plus bas que ce contenu reel — un deficit de quelques
    pixels a peine, mais suffisant pour rogner le bas du texte des
    libelles (ex. "Racine par defaut" -> "Racine nar defaut", le bas du
    "p" disparaissant) ou le bord bas des pastilles de couleur (Couleurs,
    _ColorGrid) — voir la remarque de l'utilisateur, capture annotee a
    l'appui pour les deux.
    """
    row.setSizePolicy(row.sizePolicy().horizontalPolicy(), QSizePolicy.Minimum)
    row.setMinimumHeight(max(row.minimumHeight(), row.sizeHint().height()))

def _table_cell(widget: QWidget, width: int, layout: QHBoxLayout, center: bool = False) -> QWidget:
    cell = QWidget()
    cell.setObjectName("TableCell")
    # Fond transparent EXPLICITE : sans lui, ce QWidget nu se voit quand
    # meme peint (le style sheet global de l'appli active WA_StyledBackground
    # implicitement sur tout QWidget), avec la couleur heritee du fond de
    # l'ascenseur de contenu (voir SettingsWindow._build_content, scroller.
    # setStyleSheet) plutot que rester invisible — cette cellule recouvre la
    # quasi-totalite de chaque ligne de tableau (Polices/Geometrie), ce qui
    # masquait entierement la couleur "Fond de tableau" (table_row/M['table_
    # row_a'/'table_row_b']) choisie par l'utilisateur, ne laissant filtrer
    # que le fin liseret des marges de la ligne — voir la remarque de
    # l'utilisateur, capture a l'appui.
    cell.setStyleSheet("background: transparent;")
    cell_l = QHBoxLayout(cell)
    cell_l.setContentsMargins(10, 0, 10, 0)
    if center:
        cell_l.setAlignment(Qt.AlignVCenter)
    cell_l.addWidget(widget)
    if width:
        cell.setFixedWidth(width)
        layout.addWidget(cell, 0)
    else:
        layout.addWidget(cell, 1)
    return cell

def _build_font_gabarit_row(
    family_field: "_DualFontSelectField", bold_field: "_Toggle", height_field: "_SliderField",
    smoothing_field: QWidget, color_field: QWidget, italic_field: "_Toggle | None" = None,
) -> QWidget:
    """GABARIT "police" (voir la remarque de l'utilisateur, "TOUTES LES
    LIGNES POLICES ... a l'avenir toutes les lignes police que je te ferai
    rajouter seront toutes basees sur ce gabarit sans que je te le
    mentionne", puis capture d'ecran, "voici a quoi doit ressembler la
    ligne police") : sur UNE seule ligne, dans cet ordre — police (app/
    systeme, toggles SANS texte, deja integres a _DualFontSelectField) —
    "gras" (texte AVANT le toggle, gras dans les 2 etats) — "italique"
    (texte AVANT le toggle) — "Hauteur" (texte avant le slider) — lissage
    — couleur COMPACTE ("app"/"sys", voir _CompactAppOrCustomColorField).
    `italic_field` optionnel (retro-compatibilite : anciens appelants pas
    encore migres)."""
    row = QWidget()
    row.setStyleSheet("background: transparent;")
    row_l = QHBoxLayout(row)
    row_l.setContentsMargins(0, 0, 0, 0)
    row_l.setSpacing(14)
    row_l.addWidget(family_field)
    # "gras"/"italique" : texte REGULAR (pas gras — voir la remarque de
    # l'utilisateur, "les deux doivent etre regular, je vois que tu en a
    # mis un en gras"), colle a SON PROPRE toggle (espacement serre, meme
    # principe que les toggles police 1/2 ci-dessus).
    bold_pair = QWidget()
    bold_pair.setStyleSheet("background: transparent;")
    bold_pair_l = QHBoxLayout(bold_pair)
    bold_pair_l.setContentsMargins(0, 0, 0, 0)
    bold_pair_l.setSpacing(4)
    bold_label = QLabel("gras")
    _set_text_role(bold_label, "inline_label")
    bold_pair_l.addWidget(bold_label)
    bold_pair_l.addWidget(bold_field)
    row_l.addWidget(bold_pair)
    if italic_field is not None:
        italic_pair = QWidget()
        italic_pair.setStyleSheet("background: transparent;")
        italic_pair_l = QHBoxLayout(italic_pair)
        italic_pair_l.setContentsMargins(0, 0, 0, 0)
        italic_pair_l.setSpacing(4)
        italic_label = QLabel("italique")
        _set_text_role(italic_label, "inline_label")
        italic_pair_l.addWidget(italic_label)
        italic_pair_l.addWidget(italic_field)
        row_l.addWidget(italic_pair)
    height_label = QLabel("Hauteur")
    _set_text_role(height_label, "inline_label")
    row_l.addWidget(height_label)
    row_l.addWidget(height_field)
    row_l.addWidget(smoothing_field)
    row_l.addWidget(color_field)
    row_l.addStretch(1)
    return row

def _build_linked_sides_toggle(linked: bool, label: str = "lier les 4") -> tuple[QWidget, "_Toggle"]:
    """GABARITS "arrondi des angles"/"bordures"/"padding" (voir la remarque
    de l'utilisateur, "Toggle : texte 'lier les 4' avant le toggle et pour
    les 2 etats") : le texte reste FIXE (pas de bascule "lie"/"libre" comme
    avant), place AVANT le toggle — voir _Toggle, dont le libelle integre
    est TOUJOURS peint a DROITE (show_label=False ici, le QLabel externe
    fait office de libelle). Reutilise par _ToggleSideColorsField/
    _CellPaddingField/_CornerRadiusField (un seul endroit a corriger pour
    les 3)."""
    row = QWidget()
    row.setStyleSheet("background: transparent;")
    row_l = QHBoxLayout(row)
    row_l.setContentsMargins(0, 0, 0, 0)
    row_l.setSpacing(8)
    lbl = QLabel(label)
    _set_text_role(lbl, "inline_label")
    row_l.addWidget(lbl)
    toggle = _Toggle(linked, show_label=False)
    row_l.addWidget(toggle)
    return row, toggle

# ==========================================================================
# Tableaux fermes sans entete (_build_flat_table/_build_override_flat_table) :
# chacun s'INSCRIT a sa construction et recoit aussitot le style courant
# (Geometrie > Tableaux : coins arrondis, bordure, padding des cellules),
# puis le suit en direct — y compris les tableaux construits plus tard
# (pages de surcharge par colonne...). Plus aucune liste a tenir a jour.
# ==========================================================================
import weakref

# None = pas encore regle (la fenetre de reglages les pose a sa construction).
_FLAT_TABLE_STYLE: dict = {"radius": None, "border": None, "padding": None}
_FLAT_TABLES: "weakref.WeakSet[QWidget]" = weakref.WeakSet()


def _style_flat_table(frame: QWidget) -> None:
    """Style commun ; un tableau qui a son PROPRE style (« Override settings », `frame._look_state`)
    est restyle avec celui-ci, quel que soit l'appel (restylage global compris)."""
    state = getattr(frame, "_look_state", None)
    with table_look_scope(state):
        _style_flat_table_now(frame)
        head = getattr(frame, "_flat_head", None)
        if state is not None and head is not None and hasattr(head, "_refresh_cell_style"):
            for i in range(len(head._cells)):
                head._refresh_cell_style(i)


def _style_flat_table_now(frame: QWidget) -> None:
    rows = frame._flat_rows
    radius = _FLAT_TABLE_STYLE["radius"]
    if radius is not None:
        frame.setRadius(radius)
        last = len(rows) - 1
        head = getattr(frame, "_flat_head", None)
        no_head = head is not None and head.isHidden()      # entete supprime : la 1re ligne touche le coin haut
        for i, (row, _bg, first) in enumerate(rows):
            bg = M["table_row_a"] if i % 2 == 0 else M["table_row_b"]
            _restyle_table_row(row, bg, first, top_radius=(radius if first and no_head else 0),
                               bottom_radius=(radius if i == last else 0))
        head = getattr(frame, "_flat_head", None)
        if head is not None:
            _restyle_table_head(head, radius)
    if _FLAT_TABLE_STYLE["border"] is not None:
        frame.setBorder(*_FLAT_TABLE_STYLE["border"])
    padding = _FLAT_TABLE_STYLE["padding"]
    if padding is not None and getattr(frame, "_cells_mode", False):
        head = getattr(frame, "_flat_head", None)
        if head is not None:
            head.setCellPadding(padding[0], padding[2])
        hook = getattr(frame, "_flat_cell_padding", None)    # tableaux a cellules de settings_cells
        if hook is not None:
            hook(padding)
    elif padding is not None:
        for row, _bg, _first in rows:
            row.layout().setContentsMargins(*padding)
            row.setMinimumHeight(0)
            _lock_min_height(row)
        head = getattr(frame, "_flat_head", None)
        if head is not None:
            head.setCellPadding(padding[0], padding[2])
    sync = getattr(frame, "_flat_sync", None)
    if sync is not None:
        sync()


def _prestyle_flat_frame(frame: QWidget) -> None:
    """Pose le style courant sur un cadre encore VIDE (voir _build_flat_table) :
    restyler un widget re-applique les feuilles de style de tout son sous-
    arbre, quasi gratuit tant qu'il n'a pas d'enfants. _register_flat_table
    (meme CSS, voir _apply_stylesheet_cached) n'a alors plus rien a refaire."""
    if _FLAT_TABLE_STYLE["border"] is not None:
        frame.setBorder(*_FLAT_TABLE_STYLE["border"])
    if _FLAT_TABLE_STYLE["radius"] is not None:
        frame.setRadius(_FLAT_TABLE_STYLE["radius"])


def _prestyle_flat_row(row: QWidget, index: int, count: int) -> None:
    """Meme principe que _prestyle_flat_frame pour une ligne encore vide :
    exactement le style que lui donnera _style_flat_table."""
    radius = _FLAT_TABLE_STYLE["radius"]
    if radius is not None:
        _restyle_table_row(row, M["table_row_a"] if index % 2 == 0 else M["table_row_b"], index == 0,
                           bottom_radius=(radius if index == count - 1 else 0))


def _register_cells_table(frame: QWidget, head: QWidget, row_meta: list) -> None:
    """Tableau a entete dont les lignes sont faites de cellules (Icone/Nom/Actions...) :
    suit le style commun (arrondi, bordure, couleur d'entete) ; le padding passe
    par les cellules, pas par les marges des lignes."""
    frame._flat_rows = row_meta
    frame._flat_head = head
    frame._cells_mode = True
    _FLAT_TABLES.add(frame)
    _style_flat_table(frame)


def _register_flat_table(frame: QWidget, row_meta: list) -> None:
    frame._flat_rows = row_meta
    _FLAT_TABLES.add(frame)
    _style_flat_table(frame)


def _flat_tables(root: QWidget | None = None) -> list[QWidget]:
    """Tableaux inscrits encore vivants (dans `root` s'il est donne)."""
    alive = []
    for frame in list(_FLAT_TABLES):
        try:
            if root is None or root.isAncestorOf(frame):
                alive.append(frame)
        except RuntimeError:   # objet Qt deja detruit
            _FLAT_TABLES.discard(frame)
    return alive


def _seed_flat_tables_style(radius: int, border: tuple) -> None:
    """Pose le style de depart SANS restyler les tableaux existants : appele
    avant la construction de la fenetre, pour que chaque tableau naisse
    directement avec (voir _prestyle_flat_frame)."""
    _FLAT_TABLE_STYLE["radius"] = radius
    _FLAT_TABLE_STYLE["border"] = border


# -- Style PROPRE a un tableau (« Override settings », clic droit) --------------------------------
# `state` = memes conteneurs que le style commun, avec les valeurs de CE tableau :
# {"flat": _FLAT_TABLE_STYLE, "head": _TABLE_HEAD, "selection": _TABLE_SELECTION,
#  "inner": _TABLE_INNER_BORDER, "M": M} (seules les cles presentes). Pose le temps d'un restylage
# ou d'un dessin (table_look_scope), le style commun revient aussitot apres.

def _look_targets() -> dict:
    from settings_store import M
    from fm_theme.widgets import _TABLE_INNER_BORDER, _TABLE_SELECTION
    return {"flat": _FLAT_TABLE_STYLE, "head": _TABLE_HEAD, "selection": _TABLE_SELECTION,
            "inner": _TABLE_INNER_BORDER, "M": M}


@contextmanager
def table_look_scope(state: dict | None):
    if not state:
        yield
        return
    targets = _look_targets()
    saved = {}
    for name, values in state.items():
        target = targets[name]
        saved[name] = {key: target.get(key) for key in values}
        target.update(values)
    try:
        yield
    finally:
        for name, values in saved.items():
            targets[name].update(values)


class _LookPaintFilter(QObject):
    """Dessin d'un tableau a style propre : chaque widget du tableau se peint avec SON style (filets
    verticaux, legendes, selection sont lus au moment du dessin)."""

    def __init__(self, frame: QWidget):
        super().__init__(frame)
        self._frame = frame

    def eventFilter(self, obj, event):
        if event.type() == QEvent.Paint:
            state = getattr(self._frame, "_look_state", None)
            if state:
                with table_look_scope(state):
                    obj.event(event)
                return True
        return False


def set_table_look(frame: QWidget, state: dict | None) -> None:
    """Donne a `frame` son propre style (`state`, voir table_look_scope) ou, avec None, lui rend le
    style commun ; applique aussitot (cadre, lignes, entete, filets, couleurs)."""
    frame._look_state = state or None
    widgets = [frame, *frame.findChildren(QWidget)]
    filt = getattr(frame, "_look_filter", None)
    if state and filt is None:
        filt = frame._look_filter = _LookPaintFilter(frame)
        for widget in widgets:
            widget.installEventFilter(filt)
    elif not state and filt is not None:
        for widget in widgets:
            widget.removeEventFilter(filt)
        filt.deleteLater()
        frame._look_filter = None
    if getattr(frame, "_flat_rows", None) is not None:
        _style_flat_table(frame)
        head = getattr(frame, "_flat_head", None)
        if not state and head is not None and hasattr(head, "_refresh_cell_style"):
            for i in range(len(head._cells)):
                head._refresh_cell_style(i)
    for widget in widgets:
        widget.update()


def apply_part_looks(frame: QWidget) -> None:
    """Styles PROPRES des parties de `frame` (settings_widgets.PART_LOOKS : cellule > ligne > colonne
    > tableau, champ par champ) poses sur ses cellules (`_part_look` : fond peint par la ligne,
    padding lu par le tableau ; `_text_look` : police lue par les roles de texte) puis appliques."""
    from fm_theme.theme import _refresh_text_roles
    from fm_theme.widgets import PART_LOOKS
    parts = PART_LOOKS.get(frame.dimsKey()) or {}
    frame._text_look = (parts.get(("table",)) or {}).get("font") or None
    head = getattr(frame, "_flat_head", None)
    head_cells = set()
    if head is not None:                 # l'entete n'a que SES styles (entete entier < cellule), jamais ceux du tableau
        head._text_look_barrier = True
        whole = parts.get(("head",)) or {}
        for i, label in enumerate(getattr(head, "_cells", [])):
            own = parts.get(("headcell", i)) or {}
            look = {"font": {**(whole.get("font") or {}), **(own.get("font") or {})}}
            if own.get("bg"):
                look["bg"] = own["bg"]
            label._head_look = look if look["font"] or "bg" in look else None
            head._refresh_cell_style(i)
            head_cells.add(label)
    cells = getattr(getattr(frame, "_extra_dims", None), "cells", None) or {}
    for key, cell in cells.items():
        r, c = (int(n) for n in key[1:].split("c"))
        look: dict = {}
        for part in (("table",), ("col", c), ("row", r), ("cell", r, c)):
            for field, value in (parts.get(part) or {}).items():
                if field in {"font", "border"}:
                    merged_field = dict(look.get(field) or {})
                    merged_field.update(value)
                    look[field] = merged_field
                else:
                    look[field] = value
        cell._part_look = look or None
        cell._text_look = look.get("font") or None
    padding_hook = getattr(frame, "_flat_cell_padding", None)
    if padding_hook is not None:
        import settings_window_v2 as v2
        from settings_store import load_settings
        padding_hook(v2._padding_tuple(load_settings().get("table_cell_padding") or {}))
    _refresh_text_roles(frame)
    # Textes sans role (QLabel simples) : police propre posee sur leur apparence d'origine.
    from fm_theme.theme import TEXT_ROLES, text_look_font, text_look_of
    for label in frame.findChildren(QLabel):
        if label.property("textRole") in TEXT_ROLES or label in head_cells:
            continue
        look = text_look_of(label)
        orig = getattr(label, "_part_orig", None)
        if orig is None:
            if not look:
                continue
            orig = label._part_orig = (QFont(label.font()), label.styleSheet())
        label.setFont(text_look_font(orig[0], look) if look else orig[0])
        color = (look or {}).get("color")
        label.setStyleSheet(f"color: {color}; background: transparent;" if color else orig[1])
    if getattr(frame, "_flat_rows", None) is not None:
        _style_flat_table(frame)
    for widget in [frame, *frame.findChildren(QWidget)]:
        widget.update()


def _set_flat_tables_style(radius: int | None = None, border: tuple | None = None,
                           padding: tuple | None = None, force: bool = False) -> None:
    """radius ; border = (cotes actifs, couleurs, epaisseur) ; padding =
    (gauche, haut, droite, bas). Un argument omis garde sa valeur. Rien de change : aucun tableau n'est
    refait (sinon chaque restylage de l'inspecteur, `seed_table_look`, refaisait les ~130 tableaux de la
    fenetre de reglages : ~1 s par changement de reglage, signale « les reglages reagissent des secondes
    plus tard »)."""
    changed = False
    for key, value in (("radius", radius), ("border", border), ("padding", padding)):
        if value is not None and _FLAT_TABLE_STYLE.get(key) != value:
            _FLAT_TABLE_STYLE[key] = value
            changed = True
    if not changed and not force:
        return
    for frame in _flat_tables():
        try:
            _style_flat_table(frame)
        except RuntimeError:   # fenetre fermee dont les lignes sont deja detruites
            _FLAT_TABLES.discard(frame)


def _attach_flat_head(frame: QWidget, layout: QVBoxLayout, resizer: "_FlatColumnResizer",
                      rows_widgets: list[QWidget], label_blocks: list[QWidget]) -> None:
    """Entete (Parametre | Valeur) en tete d'un tableau "un reglage par ligne",
    comme tous les autres tableaux : selection de colonne, largeur redimensionnable
    liee a la bordure libelle/controle des lignes, teinte de la colonne selectionnee."""
    head = _ResizableTableHeader([("Paramètre", resizer.width()), ("Valeur", 0)])
    head.setCellPadding(14, 14)
    head._cells[1].setAlignment(Qt.AlignRight | Qt.AlignVCenter)
    head.disableEqualToggle(1)
    layout.insertWidget(0, head)
    frame._flat_head = head
    first_row, first_label = rows_widgets[0], label_blocks[0]
    state = {"busy": False}

    def offset() -> int:
        lay = first_row.layout()
        lead = lay.itemAt(0).widget()
        extra = max(0, lead.sizeHint().width() - first_label.width()) if lead is not first_label else 0
        return lay.contentsMargins().left() + extra + lay.spacing() // 2

    def sync():
        if state["busy"]:
            return
        state["busy"] = True
        try:
            width = resizer.width() + offset()
            if head._widths[0] != width:
                head._set_width(0, width)
        finally:
            state["busy"] = False

    def on_head(index: int, width: int):
        if index != 0 or state["busy"]:
            return
        state["busy"] = True
        try:
            resizer.setWidth(width - offset())
            head._widths[0] = resizer.width() + offset()
            head._cells[0].setFixedWidth(head._widths[0])
            head._place_toggles()
            resizer.resized.emit(resizer.width())
        finally:
            state["busy"] = False

    head.resized.connect(on_head)
    resizer.resized.connect(lambda _w: sync())
    frame._flat_sync = sync
    for row in rows_widgets:
        row._sel_head = head
    head.selectionChanged.connect(lambda: [r.update() for r in rows_widgets])

def _build_flat_table(
    rows: list[tuple[str, QWidget]],
) -> tuple[QWidget, list[tuple[QWidget, str, bool]], _FlatColumnResizer]:
    """Tableau ferme SANS entete (voir _section_headers, meme technique) :
    une ligne "libelle / controle" par reglage — utilise par les sous-tables
    de Geometrie > Slider (voir SettingsWindow._section_geometry). Retourne
    (frame, row_meta, resizer) ; row_meta est a repasser tel quel a chaque
    appel de SettingsWindow._restyle_flat_table (Geometrie > Tableaux >
    Coins arrondis) ; resizer (voir _FlatColumnResizer) permet de glisser
    la bordure libelle/controle SANS entete a saisir — voir la remarque de
    l'utilisateur, "je veux aussi pouvoir redimensionner les colonnes meme
    si le tableau n'a pas d'entete".

    Le libelle n'a PLUS le stretch=1 qui le faisait jusqu'ici absorber tout
    l'espace restant (largeur fixe desormais, pilotee par le resizer) : un
    espaceur extensible dedie prend le relai pour garder le controle colle
    au bord droit (voir la remarque de l'utilisateur, qui a tranche
    explicitement pour cette option)."""
    frame, layout = _table_frame()
    _prestyle_flat_frame(frame)
    row_meta: list[tuple[QWidget, str, bool]] = []
    label_blocks: list[QWidget] = []
    rows_widgets: list[QWidget] = []
    for i, (label, control) in enumerate(rows):
        bg = M["table_row_a"] if i % 2 else M["table_row_b"]
        row, row_l = _table_row(bg, first=(i == 0))
        _prestyle_flat_row(row, i, len(rows))
        row_meta.append((row, bg, i == 0))
        row_l.setContentsMargins(14, 8, 14, 8)
        row_l.setSpacing(14)
        label_block = _label_block(label)
        row_l.addWidget(label_block, 0)
        row_l.addStretch(1)
        row_l.addWidget(control, 0, Qt.AlignVCenter)
        label_blocks.append(label_block)
        rows_widgets.append(row)
        _lock_min_height(row)
        layout.addWidget(row)
    # Largeur de depart = la plus grande sizeHint() naturelle des libelles
    # de CE tableau (pas une constante arbitraire) : le texte de chaque
    # libelle restant aligne a GAUCHE dans sa boite (voir _label_block),
    # cette largeur ne change RIEN a l'apparence par defaut (juste la place
    # invisible avant l'espaceur) tant que l'utilisateur ne glisse pas la
    # bordure — voir la remarque de l'utilisateur sur l'absence de
    # changement visuel par defaut, deja appliquee au padding/a la couleur
    # d'en-tete plus haut dans cette session.
    natural_width = max((_label_block_natural_width(lb) for lb in label_blocks), default=_FlatColumnResizer._MIN_WIDTH)
    resizer = _FlatColumnResizer(natural_width)
    for row, label_block in zip(rows_widgets, label_blocks):
        resizer.wire(row, label_block)
    # Verrouille aussi le CADRE entier (pas seulement chaque ligne, deja
    # fait ci-dessus) sur sa hauteur naturelle — systematique, POUR TOUS
    # LES TABLEAUX construits par cette fonction (aucun site d'appel n'a
    # rien a faire de plus) : sans ca, un CONTENEUR englobant a court
    # d'espace (fenetre trop basse, sous-groupe qui vient de se deplier...)
    # peut toujours compresser le cadre lui-meme en dessous de la somme de
    # ses lignes, malgre le plancher de CHAQUE ligne prise separement —
    # voir la remarque de l'utilisateur, capture a l'appui, "corrige
    # l'ecrasement du tableau ... que tu le prennes systematiquement en
    # compte pour tous les tableaux".
    _attach_flat_head(frame, layout, resizer, rows_widgets, label_blocks)
    _register_flat_table(frame, row_meta)   # avant le verrou : le padding courant change la hauteur
    _lock_min_height(frame)
    return frame, row_meta, resizer
