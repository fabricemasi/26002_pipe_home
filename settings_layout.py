from contextlib import contextmanager

from PySide6.QtCore import (
    QEvent, QObject, QPoint, QRect, Qt, QTimer, Signal,
)
from PySide6.QtGui import (
    QColor,
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
from settings_theme import _set_text_role, _text_label  # noqa: F401
from settings_store import (
    M,
    _ICONS_DIR,
    _subsection_left_margin,
    _title_color,
    _title_font,
    _title_gap,
    _title_gap_next,
    _title_indent,
)
from settings_widgets import (
    _DualFontSelectField,
    _SliderField,
    _Toggle,
    _apply_stylesheet_cached,
    _qfont,
    _inner_h_edge,
    _paint_inner_vlines,
    _TableRow,
    _restyle_table_row,
    _set_dimmed,
    _table_frame,
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

def _section_preview_wrap(widget: QWidget) -> QWidget:
    """Centre horizontalement `widget` (aucune largeur imposee, garde sa
    taille naturelle) au-dessus du tableau de reglages d'une section — voir
    Colonnes/Tableaux/Toggles/Sliders (SettingsWindow._section_headers/
    _section_tables/_section_toggles/_section_slider), qui l'utilisent
    chacun pour leur apercu de l'element concerne par la section (voir la
    remarque de l'utilisateur, "un apercu de l'element concerne par la
    section, juste avant le tableau des parametres... centre en
    horizontal")."""
    wrap = QWidget()
    wrap.setStyleSheet("background: transparent;")
    layout = QHBoxLayout(wrap)
    layout.setContentsMargins(0, 0, 0, 18)
    layout.addStretch(1)
    layout.addWidget(widget)
    layout.addStretch(1)
    return wrap

class _Row(QWidget):
    """Ligne de reglage : libelle(+note) a gauche, controle a droite. Pas de
    filet de separation entre les lignes d'un groupe (juge parasite a
    l'usage — voir la remarque de l'utilisateur, capture a l'appui)."""

    def __init__(self, label: str, control: QWidget, note: str = "", parent=None):
        super().__init__(parent)
        self.setAttribute(Qt.WA_StyledBackground, True)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(14)
        layout.setAlignment(Qt.AlignVCenter)
        layout.addWidget(_label_block(label, note), 1)
        control.setParent(self)
        layout.addWidget(control, 0, Qt.AlignVCenter)
        self.setMinimumHeight(32)

_SVG_PIXMAP_CACHE: dict[tuple[str, int, str], QPixmap] = {}

def _tinted_svg_pixmap(name: str, size: int, color: str) -> QPixmap:
    """Charge icons/{name}.svg (trace uni, sans fill) et le recolore en
    `color` — les fichiers sources n'ont pas de couleur propre (destines a
    heriter de currentColor), donc rendus ici comme un simple masque alpha
    (le SVG en noir) puis remplis via CompositionMode_SourceIn. Rendu a 4x
    la taille cible puis mis a l'echelle (devicePixelRatio) pour rester net
    sur un ecran HiDPI. Mis en cache par (nom, taille, couleur) : la couleur
    ne change qu'au fil d'un theme/preview, pas a chaque repaint."""
    key = (name, size, color)
    pix = _SVG_PIXMAP_CACHE.get(key)
    if pix is not None:
        return pix
    renderer = QSvgRenderer(str(_ICONS_DIR / f"{name}.svg"))
    scale = 4
    pix = QPixmap(size * scale, size * scale)
    pix.fill(Qt.transparent)
    p = QPainter(pix)
    p.setRenderHint(QPainter.Antialiasing, True)
    renderer.render(p)
    p.setCompositionMode(QPainter.CompositionMode_SourceIn)
    p.fillRect(pix.rect(), QColor(color))
    p.end()
    pix.setDevicePixelRatio(scale)
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
        pix = _tinted_svg_pixmap(name, self.width(), self._color)
        p.drawPixmap(0, 0, pix)
        p.end()

# Espacement entre deux sections (voir SettingsWindow._build_content, qui
# pose un spaceur dedie apres chaque _Section plutot qu'un
# QVBoxLayout.setSpacing uniforme) : plein quand la section au-dessus est
# deployee, quasi nul quand elle est repliee (voir _Section.collapsedChanged
# — son corps est deja masque, rien ne justifie plus un grand espacement)
# — pas 0 pile : une marge minimale separe visuellement deux bandeaux-titre
# consecutifs, sans quoi ils se touchent litteralement.
_SECTION_GAP_EXPANDED = 34

_SECTION_GAP_COLLAPSED = 2

# Espace AVANT la section "Logiciel" (voir SettingsWindow._section_logiciels)
# — voir la remarque de l'utilisateur, "en derniere position mais avec un
# espace plus important entre cette section et celle d'avant" : un simple
# multiple de _SECTION_GAP_EXPANDED plutot qu'une constante independante,
# pour rester coherent si ce dernier est un jour ajuste.
_SECTION_GAP_EXPANDED_LOGICIEL = _SECTION_GAP_EXPANDED * 2

class _SectionHeader(QWidget):
    """Bandeau titre d'une _Section — toute sa largeur est cliquable pour
    replier/deplier (voir _Section), pas seulement le chevron (memes raisons
    que _EdgeCheckItem/_PresetListRow : une cible de clic plus large que le
    seul glyphe est plus confortable)."""

    clicked = Signal()

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            self.clicked.emit()
        super().mousePressEvent(event)

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

# Fenetre de parametres EN COURS DE CONSTRUCTION (voir SettingsWindow.
# __init__/_report_loading_step) : global, PAS un parametre a threader
# dans les dizaines de call sites de _Section/_SubSection — chacune
# rapporte ainsi AUTOMATIQUEMENT son propre titre a l'indicateur de
# chargement de l'Inspecteur (voir _report_construction_step ci-dessous),
# quel que soit le niveau d'imbrication (section OU sous-section) — voir
# la remarque de l'utilisateur, "decris pas seulement les tabs mais
# toutes les sections et sous sections aussi".
_ACTIVE_LOADING_WINDOW = None


def _set_active_loading_window(window) -> None:
    global _ACTIVE_LOADING_WINDOW
    _ACTIVE_LOADING_WINDOW = window

def _report_construction_step(title: str, depth: int = 0):
    if _ACTIVE_LOADING_WINDOW is not None:
        _ACTIVE_LOADING_WINDOW._report_loading_step(title, depth=depth)

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
        row.addWidget(widget)
        self._body_rows.append(row)
        self._body_layout.addLayout(row)

    def set_body_offset(self, offset: int):
        self._body_offset = offset
        for row in self._body_rows:
            row.setContentsMargins(offset, 0, 0, 0)



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
        _report_construction_step(title)
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
        # depth = level-1 pour l'Inspecteur (voir _report_construction_step,
        # "tab = 2 carac" par niveau, remarque de l'utilisateur, "incremente
        # les differents niveaux de settings").
        _report_construction_step(title, depth=max(1, level - 1))
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

# Espacement entre 2 _SubSection empilees — MEME principe que _SECTION_GAP_*/
# SettingsWindow._build_content (un spaceur dedie, plein entre 2 sous-groupes
# DEPLIES, quasi nul des que celui du dessus est REPLIE) mais des valeurs
# plus discretes : un sous-groupe reste un repere de second niveau, pas une
# section a part entiere — voir _stack_subsections/la remarque de
# l'utilisateur, "je veux que tu normalises l'espacement entre les sections
# ... comme tu l'avais fait pour les sections".
_SUBSECTION_GAP_EXPANDED = 32

_SUBSECTION_GAP_COLLAPSED = 0

def _make_gap_spacer(item, level: int, multiplier: int = 1) -> QWidget:
    """Spaceur sous `item` (titre de `level`) : hauteur lue dans les reglages
    TITRE (_title_gap), replie ou deplie, mise a jour au repli/depli et par
    _refresh_gap_spacers (apercu en direct)."""
    spacer = QWidget()
    spacer.setStyleSheet("background: transparent;")
    item._gap_spacer = (spacer, level, multiplier)
    _refresh_gap_spacer(item)
    item.collapsedChanged.connect(lambda _c, i=item: _refresh_gap_spacer(i))
    return spacer

def _refresh_gap_spacer(item):
    spacer, level, multiplier = item._gap_spacer
    spacer.setFixedHeight(_title_gap(level, item.is_collapsed()) * multiplier)

def _refresh_gap_spacers(root: QWidget):
    for item in root.findChildren(QWidget):
        if hasattr(item, "_gap_spacer"):
            _refresh_gap_spacer(item)

def _stack_subsections(layout: QVBoxLayout, subsections: list[_SubSection]):
    """Empile plusieurs _SubSection dans `layout` (deja cree, vide) avec un
    espacement ADAPTATIF entre chaque paire — voir _SUBSECTION_GAP_*
    ci-dessus. Ne remplace PAS le cablage vers un eventuel _Section.
    refresh_min_height/_activate_layout_tree englobant (voir les
    appelants) : ce spaceur ne fait QUE gerer l'espace VISUEL entre les
    sous-groupes, independamment du recalcul de hauteur globale.

    setSpacing(0) — PAS laisse a la valeur par defaut du style (~6px,
    QStyle::PM_LayoutVerticalSpacing) : sans ca, cette valeur s'ajoutait
    EN PLUS du spaceur dedie de CHAQUE cote (avant ET apres), doublant
    l'ecart REPLIE malgre un spaceur a 0 — voir la remarque de
    l'utilisateur, "base toi sur ce que tu avais fait sur les sections"
    (_Section/SettingsWindow._build_content n'ont ce probleme que parce
    que leur layout EXTERIEUR a deja son propre setSpacing(0) explicite)."""
    layout.setSpacing(0)
    for i, sub in enumerate(subsections):
        # Repliee a l'ouverture (voir la remarque de l'utilisateur, "je
        # veux que toutes les sections (y compris sous sections) soient
        # repliees a l'ouverture de la fenetre de settings").
        sub.set_collapsed(True)
        layout.addWidget(sub)
        if i == len(subsections) - 1:
            continue
        spacer = _make_gap_spacer(sub, sub._level)
        layout.addWidget(spacer)
    _make_accordion(subsections)

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
        for i, btn in enumerate(self._btns):
            if i == self._index:
                btn.setStyleSheet(
                    f"QPushButton {{ color: {M['section_title']}; background: transparent; "
                    f"border: none; border-bottom: 2px solid {M['accent']}; padding: 0 14px; }}"
                )
            else:
                btn.setStyleSheet(
                    f"QPushButton {{ color: {M['label_dim']}; background: transparent; "
                    f"border: none; border-bottom: 2px solid transparent; padding: 0 14px; }}"
                    f"QPushButton:hover {{ color: {M['value_fg']}; }}"
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
_TABLE_HEAD: dict = {"bg": None}

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

class _ReorderOverlay(QWidget):
    """Couche posee sur le tableau pendant le deplacement d'une colonne : la colonne (entete + lignes)
    suit le curseur en transparence, son emplacement d'origine est assombri et tous les emplacements
    possibles (entre deux colonnes) sont marques, le plus proche en surbrillance."""

    def __init__(self, frame: QWidget, head: "_ResizableTableHeader", source: int, ghost, offset: int, grab_dx: int):
        super().__init__(frame)
        self.setAttribute(Qt.WA_TransparentForMouseEvents, True)
        self.setGeometry(frame.rect())
        self.head, self.source, self.ghost, self.offset, self.grab_dx = head, source, ghost, offset, grab_dx
        spans = head._column_spans()
        order = head._order
        self.gaps = [spans[i][0] for i in order] + [spans[order[-1]][1]]
        self.origin = spans[source]
        self.cursor_x = spans[source][0] + grab_dx
        self.target: int | None = None
        self.show()
        self.raise_()

    def follow(self, x: int):
        self.cursor_x = x
        position = self.head._order.index(self.source)
        nearest = min(range(len(self.gaps)), key=lambda k: abs(self.gaps[k] - (x - self.grab_dx + (self.origin[1] - self.origin[0]) // 2)))
        self.target = None if nearest in (position, position + 1) else nearest
        self.update()

    def paintEvent(self, event):
        p = QPainter(self)
        accent = QColor(M["accent"])
        p.fillRect(self.offset + self.origin[0], 0, self.origin[1] - self.origin[0], self.height(), QColor(0, 0, 0, 90))
        for k, gap in enumerate(self.gaps):
            on = k == self.target
            color = QColor(accent)
            color.setAlpha(255 if on else 70)
            width = 3 if on else 1
            p.fillRect(self.offset + gap - width // 2, 0, width, self.height(), color)
        p.setOpacity(0.75)
        p.drawPixmap(self.offset + self.cursor_x - self.grab_dx, 0, self.ghost)
        p.setOpacity(1.0)
        p.setPen(accent)
        p.drawRect(self.offset + self.cursor_x - self.grab_dx, 0, self.ghost.width() - 1, self.ghost.height() - 1)
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

    def paintEvent(self, event):
        super().paintEvent(event)
        spans = self._column_spans()
        _paint_inner_vlines(self, [spans[i][0] for i in self._order[1:]])

    def event(self, event):
        handled = super().event(event)
        # Voir _TableRow.event : les filets V suivent les cellules apres le layout.
        if event.type() == QEvent.LayoutRequest:
            self.update()
        return handled

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
        self._badged = False                      # largeurs affichees dans les titres pendant un redimensionnement
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
        bg = "rgba(95, 155, 208, 0.22)" if index in self._selected else "transparent"
        self._cells[index].setStyleSheet(
            f"color: {M['table_head_fg']}; background: {bg}; "
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
        new_width = max(self._MIN_WIDTH, self._resize_start_width + self._resizing_sign * delta)
        if not stretch:
            new_width = min(self._MAX_WIDTH, new_width)
        group = self._equal_group()
        if idx in group:
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
        """Pendant un redimensionnement, le titre de chaque colonne concernee affiche sa largeur."""
        spans = self._column_spans()
        for i in columns:
            self._cells[i].setText(f"{spans[i][1] - spans[i][0]} px")
        self._badged = True

    def _restore_titles(self):
        if self._badged:
            self._badged = False
            for cell, title in zip(self._cells, self._titles):
                cell.setText(title)

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
        overlay, self._reorder = self._reorder, None
        self.unsetCursor()
        gap = overlay.target
        overlay.hide()
        overlay.deleteLater()
        if gap is None:
            return
        order = [i for i in self._order if i != overlay.source]
        order.insert(gap - (1 if gap > self._order.index(overlay.source) else 0), overlay.source)
        self.setOrder(order)

    def mouseMoveEvent(self, event):
        if self._resizing_index is not None:
            self.dragTo(event.globalPosition().toPoint().x())
            event.accept()
            return
        if self._reorderable and self._press_pos is not None and event.buttons() & Qt.LeftButton:
            x = event.position().toPoint().x()
            if self._reorder is None and (event.position().toPoint() - self._press_pos).manhattanLength() > 6:
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
                self._set_width(i, max(self._MIN_WIDTH, min(self._MAX_WIDTH, int(width))))

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
    rows = frame._flat_rows
    radius = _FLAT_TABLE_STYLE["radius"]
    if radius is not None:
        frame.setRadius(radius)
        last = len(rows) - 1
        for i, (row, _bg, first) in enumerate(rows):
            bg = M["table_row_a"] if i % 2 == 0 else M["table_row_b"]
            _restyle_table_row(row, bg, first, bottom_radius=(radius if i == last else 0))
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


@contextmanager
def _flat_tables_padding(padding: tuple):
    """Padding pose sur les tableaux construits PENDANT ce bloc seulement
    (fenetre "general", qui n'a pas la section Tableaux pour l'appliquer) :
    le reglage partage n'est pas modifie pour les autres fenetres."""
    previous = _FLAT_TABLE_STYLE["padding"]
    _FLAT_TABLE_STYLE["padding"] = padding
    try:
        yield
    finally:
        _FLAT_TABLE_STYLE["padding"] = previous


def _set_flat_tables_style(radius: int | None = None, border: tuple | None = None,
                           padding: tuple | None = None) -> None:
    """radius ; border = (cotes actifs, couleurs, epaisseur) ; padding =
    (gauche, haut, droite, bas). Un argument omis garde sa valeur."""
    for key, value in (("radius", radius), ("border", border), ("padding", padding)):
        if value is not None:
            _FLAT_TABLE_STYLE[key] = value
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

def _set_label_block_dim(label_block: QWidget, dim: bool):
    """Grise (ou re-eclaircit) le texte d'un _label_block — voir
    _build_override_flat_table, un toggle OFF grise le libelle de sa ligne
    ("ce qui grisera la ligne", remarque de l'utilisateur)."""
    color = M["label_dim"] if dim else M["row_label"]
    for label in label_block.findChildren(QLabel):
        label.setStyleSheet(f"color: {color}; background: transparent;")

def _build_override_flat_table(
    rows: list[tuple[str, QWidget, "_Toggle"]],
) -> tuple[QWidget, list[tuple[QWidget, str, bool]], _FlatColumnResizer]:
    """Meme construction que _build_flat_table (tableau ferme SANS entete),
    mais chaque ligne est precedee d'un toggle1 (voir Colonnes > Type,
    SettingsWindow._build_column_type_page — la remarque de l'utilisateur,
    "juste devant le texte de chaque parametre, tu mets un toggle 1 en off,
    ce qui grisera la ligne") : OFF grise le libelle ET desactive le
    controle (la ligne suit alors la valeur GENERALE, voir
    SettingsWindow._apply_column_type_preview) ; ON re-eclaircit le libelle
    et active le controle, dont la propre valeur prend alors le relai — "le
    fait de mettre le toggle en ON overide le parametre et la modification
    est apportee en temps reel". Le toggle reste HORS de la cellule
    redimensionnable (voir _FlatColumnResizer.wire ci-dessous, appele sur
    le SEUL label_block comme dans _build_flat_table) : sa largeur est
    fixe, glisser la frontiere libelle/controle ne doit faire bouger que le
    texte, pas le toggle."""
    frame, layout = _table_frame()
    _prestyle_flat_frame(frame)
    row_meta: list[tuple[QWidget, str, bool]] = []
    label_blocks: list[QWidget] = []
    rows_widgets: list[QWidget] = []
    for i, (label, control, toggle) in enumerate(rows):
        bg = M["table_row_a"] if i % 2 else M["table_row_b"]
        row, row_l = _table_row(bg, first=(i == 0))
        _prestyle_flat_row(row, i, len(rows))
        row_meta.append((row, bg, i == 0))
        row_l.setContentsMargins(14, 8, 14, 8)
        row_l.setSpacing(14)
        # Toggle + libelle RAPPROCHES l'un de l'autre (6px, pas les 14px du
        # reste de la ligne) dans leur propre petite boite — voir la
        # remarque de l'utilisateur, "approche les textes des parametre
        # proche des toggles" — plutot que le rythme uniforme de
        # _build_flat_table, pense pour des cellules independantes.
        toggle_label_box = QWidget()
        toggle_label_box.setStyleSheet("background: transparent;")
        toggle_label_l = QHBoxLayout(toggle_label_box)
        toggle_label_l.setContentsMargins(0, 0, 0, 0)
        toggle_label_l.setSpacing(6)
        toggle_label_l.addWidget(toggle, 0, Qt.AlignVCenter)
        label_block = _label_block(label)
        toggle_label_l.addWidget(label_block, 0)
        row_l.addWidget(toggle_label_box, 0)
        row_l.addStretch(1)
        row_l.addWidget(control, 0, Qt.AlignVCenter)
        label_blocks.append(label_block)
        rows_widgets.append(row)

        def _sync_override(checked: bool, control=control, label_block=label_block):
            _set_dimmed(control, not checked)
            _set_label_block_dim(label_block, not checked)

        toggle.toggled.connect(_sync_override)
        _sync_override(toggle.isChecked())
        _lock_min_height(row)
        layout.addWidget(row)
    natural_width = max((_label_block_natural_width(lb) for lb in label_blocks), default=_FlatColumnResizer._MIN_WIDTH)
    resizer = _FlatColumnResizer(natural_width)
    for row, label_block in zip(rows_widgets, label_blocks):
        resizer.wire(row, label_block)
    # Verrouille aussi le CADRE entier — voir _build_flat_table, meme
    # necessite/memes raisons (systematique pour tous les tableaux, voir
    # la remarque de l'utilisateur, "corrige l'ecrasement du tableau ...
    # que tu le prennes systematiquement en compte pour tous les
    # tableaux").
    _attach_flat_head(frame, layout, resizer, rows_widgets, label_blocks)
    _register_flat_table(frame, row_meta)   # avant le verrou : le padding courant change la hauteur
    _lock_min_height(frame)
    return frame, row_meta, resizer
