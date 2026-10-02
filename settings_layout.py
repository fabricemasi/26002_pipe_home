from PySide6.QtCore import (
    QEvent, QObject, Qt, Signal,
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
from settings_store import (
    M,
    _ICONS_DIR,
    _subsection_left_margin,
    _title_color,
    _title_font,
    _title_indent,
)
from settings_widgets import (
    _DualFontSelectField,
    _SliderField,
    _Toggle,
    _apply_stylesheet_cached,
    _qfont,
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
    name.setFont(_qfont(12, 400))
    name.setStyleSheet(f"color: {M['row_label']}; background: transparent;")
    layout.addWidget(name)
    if note:
        sub = QLabel(note)
        sub.setWordWrap(True)
        sub.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
        sub.setFont(_qfont(10, 400))
        sub.setStyleSheet(f"color: {M['row_note']}; background: transparent;")
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

class _Section(QWidget):
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
        super().__init__(parent)
        _report_construction_step(title)
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
        head_l.setContentsMargins(self._title_indent, 0, 0, 10)
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
            note_label.setFont(_qfont(10, 400))
            note_label.setStyleSheet(f"color: {M['group_note']}; background: transparent;")
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
        self._body_layout.setContentsMargins(self._title_indent + 16 + 10, 0, 0, 0)
        self._body_layout.setSpacing(0)
        self._layout.addWidget(self._body)

        self._refresh_chevron()

    def add(self, widget: QWidget):
        self._body_layout.addWidget(widget)

    def toggle(self):
        self.set_collapsed(not self._collapsed)

    def set_collapsed(self, collapsed: bool):
        if self._collapsed == collapsed:
            return
        self._collapsed = collapsed
        self._body.setVisible(not collapsed)
        self._head_layout.setContentsMargins(0, 0, 0, 0 if collapsed else 10)
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

    def is_collapsed(self) -> bool:
        return self._collapsed

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

class _SubSection(QWidget):
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
        head_l.setContentsMargins(self._left_margin, 0, 0, 6)
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
        self._body_layout.setContentsMargins(self._left_margin + 11 + 6, 0, 0, 0)
        self._body_layout.setSpacing(0)
        layout.addWidget(self._body)
        self._refresh_chevron()

    def add(self, widget: QWidget):
        self._body_layout.addWidget(widget)
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
        self._head_layout.setContentsMargins(self._left_margin, 0, 0, 0 if collapsed else 6)
        self._refresh_chevron()
        self.refresh_layout()
        self.collapsedChanged.emit(collapsed)

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

# Espacement entre 2 _SubSection empilees — MEME principe que _SECTION_GAP_*/
# SettingsWindow._build_content (un spaceur dedie, plein entre 2 sous-groupes
# DEPLIES, quasi nul des que celui du dessus est REPLIE) mais des valeurs
# plus discretes : un sous-groupe reste un repere de second niveau, pas une
# section a part entiere — voir _stack_subsections/la remarque de
# l'utilisateur, "je veux que tu normalises l'espacement entre les sections
# ... comme tu l'avais fait pour les sections".
_SUBSECTION_GAP_EXPANDED = 8

_SUBSECTION_GAP_COLLAPSED = 0

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
        spacer = QWidget()
        spacer.setStyleSheet("background: transparent;")
        spacer.setFixedHeight(_SUBSECTION_GAP_COLLAPSED if sub.is_collapsed() else _SUBSECTION_GAP_EXPANDED)
        sub.collapsedChanged.connect(
            lambda collapsed, s=spacer: s.setFixedHeight(
                _SUBSECTION_GAP_COLLAPSED if collapsed else _SUBSECTION_GAP_EXPANDED
            )
        )
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
    bg = getattr(head, "_custom_bg", None) or M["table_head_bg"]
    _apply_stylesheet_cached(
        head,
        f"#TableHead {{ background: {bg}; border-bottom: 1px solid {M['panel_border']}; "
        f"border-top-left-radius: {radius}px; border-top-right-radius: {radius}px; }}",
    )

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

    _MARGIN = 5
    _MIN_WIDTH = 60
    _MAX_WIDTH = 640

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
        for text, width in cells:
            cell = QLabel(text.upper())
            cell.setFont(_qfont(9, 600))
            cell.setStyleSheet(
                f"color: {M['table_head_fg']}; background: transparent; "
                f"padding: 0 {self._padding_lr[1]}px 0 {self._padding_lr[0]}px;"
            )
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
            if width:
                cell.setFixedWidth(width)
                layout.addWidget(cell, 0)
            else:
                layout.addWidget(cell, 1)
        self._resizing_index: int | None = None
        self._resizing_sign = 1
        self._resize_start_x = 0
        self._resize_start_width = 0
        self._resizable = True

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
        for cell in self._cells:
            cell.setStyleSheet(
                f"color: {M['table_head_fg']}; background: transparent; "
                f"padding: 0 {self._padding_lr[1]}px 0 {self._padding_lr[0]}px;"
            )

    def _column_edges(self) -> list[int]:
        """Position (x) du bord droit de chaque colonne, calculee a partir
        des largeurs fixes ET de la largeur REELLE actuelle de ce widget
        (self.width(), toujours fiable — contrairement a cell.geometry(),
        qui peut ne pas encore refleter le dernier passage de layout) : la
        ou toute colonne extensible se trouve dans `cells` se voit
        attribuer le meme partage de l'espace restant qu'un vrai stretch=1
        de QHBoxLayout."""
        stretch_count = self._widths.count(0)
        used = sum(w for w in self._widths if w)
        stretch_width = max(0, self.width() - used) // stretch_count if stretch_count else 0
        edges = []
        pos = 0
        for w in self._widths:
            pos += w if w else stretch_width
            edges.append(pos)
        return edges

    def _draggable_boundaries(self) -> list[tuple[int, int, int]]:
        """Bordures REELLEMENT glissables : (position x, index de colonne
        controlee, signe) — signe +1 si glisser vers la DROITE agrandit
        cette colonne (sa propre bordure DROITE, le cas normal), -1 si
        glisser vers la DROITE la retrecit (sa bordure GAUCHE — n'existe
        que quand la colonne PRECEDENTE est extensible, voir _GeoTable ou
        "Element" precede "Cadre" : sans ce cas, la bordure entre les deux
        ne controlait RIEN, obligeant l'utilisateur a aller chercher celle,
        bien plus loin, apres TOUTE la colonne Cadre — voir sa remarque,
        capture a l'appui, "il faut que j'aille chercher le slider apres le
        texte cadre")."""
        edges = self._column_edges()
        boundaries: list[tuple[int, int, int]] = []
        left = 0
        for i, width in enumerate(self._widths):
            if width == 0:
                left = edges[i]
                continue
            if i > 0 and self._widths[i - 1] == 0:
                boundaries.append((left, i, -1))
            boundaries.append((edges[i], i, 1))
            left = edges[i]
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
                self._resizing_index, self._resizing_sign = hit
                self._resize_start_x = event.globalPosition().toPoint().x()
                self._resize_start_width = self._widths[self._resizing_index]
                event.accept()
                return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        if self._resizing_index is not None:
            delta = event.globalPosition().toPoint().x() - self._resize_start_x
            new_width = max(self._MIN_WIDTH, min(self._MAX_WIDTH, self._resize_start_width + self._resizing_sign * delta))
            self._set_width(self._resizing_index, new_width)
            event.accept()
            return
        hit = self._boundary_at(event.position().toPoint().x())
        self.setCursor(Qt.SizeHorCursor if hit is not None else Qt.ArrowCursor)
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        if self._resizing_index is not None:
            self._resizing_index = None
            event.accept()
            return
        super().mouseReleaseEvent(event)

    def leaveEvent(self, event):
        if self._resizing_index is None:
            self.unsetCursor()
        super().leaveEvent(event)

    def _set_width(self, index: int, width: int):
        self._widths[index] = width
        self._cells[index].setFixedWidth(width)
        self.resized.emit(index, width)

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
        self._cells.append(label_cell)
        self._rows.append(row)
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
    def _on_resize(index: int, width: int):
        for cell in column_cells.get(index, []):
            cell.setFixedWidth(width)

    head.resized.connect(_on_resize)

def _table_row(bg: str, first: bool) -> tuple[QWidget, QHBoxLayout]:
    """`first` : la toute premiere ligne de donnees colle directement sous
    l'entete (qui a deja son propre filet du bas) — seules les lignes
    SUIVANTES ont besoin de leur propre filet du haut ; aucune ligne ne
    dessine plus ses propres cotes gauche/droite (voir _table_frame)."""
    row = QWidget()
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
    bold_label.setFont(_qfont(11, 400))
    bold_label.setStyleSheet(f"color: {M['row_label']}; background: transparent;")
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
        italic_label.setFont(_qfont(11, 400))
        italic_label.setStyleSheet(f"color: {M['row_label']}; background: transparent;")
        italic_pair_l.addWidget(italic_label)
        italic_pair_l.addWidget(italic_field)
        row_l.addWidget(italic_pair)
    height_label = QLabel("Hauteur")
    height_label.setFont(_qfont(11, 400))
    height_label.setStyleSheet(f"color: {M['row_label']}; background: transparent;")
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
    lbl.setFont(_qfont(11, 400))
    lbl.setStyleSheet(f"color: {M['row_label']}; background: transparent;")
    row_l.addWidget(lbl)
    toggle = _Toggle(linked, show_label=False)
    row_l.addWidget(toggle)
    return row, toggle

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
    row_meta: list[tuple[QWidget, str, bool]] = []
    label_blocks: list[QWidget] = []
    rows_widgets: list[QWidget] = []
    for i, (label, control) in enumerate(rows):
        bg = M["table_row_a"] if i % 2 else M["table_row_b"]
        row, row_l = _table_row(bg, first=(i == 0))
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
    row_meta: list[tuple[QWidget, str, bool]] = []
    label_blocks: list[QWidget] = []
    rows_widgets: list[QWidget] = []
    for i, (label, control, toggle) in enumerate(rows):
        bg = M["table_row_a"] if i % 2 else M["table_row_b"]
        row, row_l = _table_row(bg, first=(i == 0))
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
    _lock_min_height(frame)
    return frame, row_meta, resizer
