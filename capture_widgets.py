import shutil
from pathlib import Path
from typing import TYPE_CHECKING
from PySide6.QtCore import (
    QMimeData, QPoint, QRect, Qt, QUrl, Signal,
)
from PySide6.QtGui import (
    QDrag,
    QPainter,
    QPixmap,
)
from PySide6.QtWidgets import (
    QAbstractItemView,
    QApplication,
    QGraphicsEffect,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QLineEdit,
    QListWidget,
    QMenu,
    QMessageBox,
    QVBoxLayout,
    QWidget,
)
from app_style import (
    C,
    PREVIEW_STACK_TITLE,
    column_gap,
    font,
    role_font,
    scaled,
    resolve_color_ref,
    column_frame_style,
    column_padding_for,
    column_style_for,
)
import ui_state
from previews import (
    _cover_crop_rect,
)
from settings_widgets import (
    _paint_bordered_rect,
    _radius_any,
    _radius_dict,
    _rounded_rect_path,
)
from browser_core import (
    ROLE_ISDIR,
    ROLE_PATH,
    STATUS_FOLDERS,
    _prompt_capture_thumbnail,
    _prompt_change_thumbnail,
    _prompt_reset_thumbnail,
    _resolve_font_family,
    project_thumbnail_path,
    project_thumbnail_pixmap,
    reveal_in_file_manager,
    status_folder_state,
)

if TYPE_CHECKING:
    from column import Column


# ==========================================================================
# Liste avec glisser-deposer de vrais fichiers
# ==========================================================================

class FileListWidget(QListWidget):
    """QListWidget dont le glisser-deposer manipule des fichiers reels sur
    le disque : entre colonnes de l'app, mais aussi avec l'explorateur
    Windows (et inversement)."""

    def __init__(self, column: "Column", parent=None):
        super().__init__(parent)
        self.column = column
        self.setDragEnabled(True)
        self.setAcceptDrops(True)
        self.setDragDropMode(QAbstractItemView.DragDrop)
        self.setDefaultDropAction(Qt.MoveAction)
        self._press_on_current = None

    # Qt donne le focus a la 1re ligne quand une liste SANS ligne courante
    # recoit le focus (fermeture du menu contextuel, ouverture/fermeture de
    # la fenetre de saisie "Nouveau dossier"...) : cette selection
    # involontaire lancait une navigation. On l'annule, en silence.
    def focusInEvent(self, event):
        if self.currentItem() is not None:
            super().focusInEvent(event)
            return
        self.blockSignals(True)
        try:
            super().focusInEvent(event)
            if self.currentItem() is not None:
                self.setCurrentItem(None)
                self.clearSelection()
        finally:
            self.blockSignals(False)

    # Un clic sur la ligne DEJA selectionnee ne declenche aucun
    # currentItemChanged : la fenetre decide quoi faire (voir
    # PipelineBrowser.on_reclicked) — rien si une seule colonne est ouverte
    # apres celle-ci, sinon on revient a cette seule colonne suivante.
    def mousePressEvent(self, event):
        item = self.itemAt(event.position().toPoint())
        plain_left = event.button() == Qt.LeftButton and event.modifiers() == Qt.NoModifier
        self._press_on_current = item if (plain_left and item is not None and item is self.currentItem()) else None
        super().mousePressEvent(event)

    def mouseReleaseEvent(self, event):
        pressed, self._press_on_current = self._press_on_current, None
        super().mouseReleaseEvent(event)
        if (pressed is not None and event.button() == Qt.LeftButton
                and self.itemAt(event.position().toPoint()) is pressed):
            handler = getattr(self.column.window(), "on_reclicked", None)
            if handler is not None:
                handler(self.column)

    def mimeData(self, items):
        mime = QMimeData()
        mime.setUrls([QUrl.fromLocalFile(it.data(ROLE_PATH)) for it in items])
        return mime

    def supportedDropActions(self):
        return Qt.CopyAction | Qt.MoveAction

    def startDrag(self, supportedActions):
        items = self.selectedItems()
        if not items:
            return
        drag = QDrag(self)
        drag.setMimeData(self.mimeData(items))
        drag.exec(Qt.CopyAction | Qt.MoveAction, Qt.MoveAction)
        self.column.refresh_all()

    def dragEnterEvent(self, event):
        if event.mimeData().hasUrls():
            event.acceptProposedAction()
        else:
            event.ignore()

    def dragMoveEvent(self, event):
        if event.mimeData().hasUrls():
            event.acceptProposedAction()
        else:
            event.ignore()

    def dropEvent(self, event):
        mime = event.mimeData()
        if not mime.hasUrls():
            event.ignore()
            return

        mods = QApplication.keyboardModifiers()
        if mods & Qt.ControlModifier:
            action = Qt.CopyAction
        elif mods & Qt.ShiftModifier:
            action = Qt.MoveAction
        elif event.proposedAction() in (Qt.CopyAction, Qt.MoveAction):
            action = event.proposedAction()
        else:
            action = Qt.CopyAction

        target_item = self.itemAt(event.position().toPoint())
        dest_dir = self.column.directory
        if target_item and target_item.data(ROLE_ISDIR):
            dest_dir = Path(target_item.data(ROLE_PATH))

        last_dest = self.apply_drop(mime.urls(), action, dest_dir)

        event.setDropAction(action)
        event.accept()
        if last_dest:
            for i in range(self.count()):
                it = self.item(i)
                if it.data(ROLE_PATH) == str(last_dest):
                    self.setCurrentItem(it)
                    break

    def apply_drop(self, urls, action, dest_dir: Path | None = None) -> Path | None:
        """Copie ou deplace les fichiers/dossiers de `urls` dans `dest_dir`
        (par defaut le dossier de cette colonne ; peut aussi etre un
        sous-dossier vise directement, cf. dropEvent). Retourne le dernier
        chemin depose (ou None). Separe de dropEvent() pour rester testable
        sans QDropEvent reel."""
        dest_dir = dest_dir if dest_dir is not None else self.column.directory
        errors = []
        last_dest = None
        for url in urls:
            if not url.isLocalFile():
                continue
            src = Path(url.toLocalFile())
            if not src.exists():
                continue
            try:
                if src.resolve() == dest_dir.resolve():
                    continue
                if src.parent.resolve() == dest_dir.resolve():
                    continue  # deja dans ce dossier
                if src.is_dir() and dest_dir.resolve() != src.resolve():
                    try:
                        dest_dir.resolve().relative_to(src.resolve())
                        continue  # depose dans lui-meme ou un sous-dossier
                    except ValueError:
                        pass
            except OSError:
                continue
            dest = self.column._unique_dest_path(src, dest_dir)
            try:
                if action == Qt.MoveAction:
                    shutil.move(str(src), str(dest))
                else:
                    if src.is_dir():
                        shutil.copytree(src, dest)
                    else:
                        shutil.copy2(src, dest)
                last_dest = dest
            except OSError as exc:
                errors.append(f"{src.name} : {exc}")

        if errors:
            QMessageBox.warning(
                self, "Glisser-deposer",
                "Impossible de deplacer/copier :\n" + "\n".join(errors),
            )

        self.column.refresh_all()
        return last_dest

# ==========================================================================
# Apercu empile (premiere colonne) : quand un projet, puis un sous-projet,
# est selectionne plus loin dans l'arborescence, la toute premiere colonne
# affiche sous sa propre liste un aperçu (image carree + titre) par niveau
# selectionne ayant une vignette, empiles les uns sous les autres.
# ==========================================================================

PREVIEW_TITLE_HEIGHT = 52   # hauteur fixe de la barre de titre (grand intitule "affiche"), au-dessus de chaque image empilee

PREVIEW_STATUS_HEIGHT = 26  # hauteur de la rangee d'indicateurs in/over/out, au-dessus du titre

PREVIEW_HEADER_HEIGHT = PREVIEW_STATUS_HEIGHT + PREVIEW_TITLE_HEIGHT

class _SquarePreviewImage(QLabel):
    """Image bord a bord (aucune marge) avec les bords de la colonne, de
    taille EXPLICITEMENT fixee (voir set_rect) plutot que recalculee en
    reaction a un resizeEvent : un widget dont la taille reagit a son propre
    resizeEvent peut se faire redimensionner une seconde fois par son parent
    avant que ce premier changement soit repercute, le rendant tantot trop
    petit, tantot etire par un layout qui redistribue l'espace en trop —
    exactement le symptome observe (espaces morts, doublons visuels lors
    d'une navigation rapide). Taille fixe des le depart = aucune ambiguite.
    Le fichier d'origine sur le disque n'est jamais modifie/degrade : on ne
    fait que le redimensionner en memoire pour l'affichage.

    "Square" dans le nom pour raisons historiques (garde tel quel, deja
    reference ailleurs) : le rectangle n'est plus force carre depuis
    Colonnes > Apercu > Image > Ratio (voir set_rect/la remarque de
    l'utilisateur, "je veux une section ratio")."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._raw = QPixmap()
        # Pas de "border-bottom" ici (essaye puis abandonne) : sur un QLabel
        # de taille fixe rempli d'un pixmap plein cadre, ce filet ne se
        # rendait pas de facon fiable. Le separateur entre blocs est
        # desormais un widget dedie, voir _PreviewBlock. Fond C["chrome"]
        # (pas C["well"]) : c'est la couleur des en-tetes de colonne, celle
        # de tout le bloc (voir _PreviewBlock) — doit rester coherente
        # derriere l'image elle-meme, la ou le padding/le lettrboxing la
        # laisse apparaitre.
        self.setStyleSheet(f"background: {C['chrome']};")

    def set_source_pixmap(self, pixmap: QPixmap):
        self._raw = pixmap
        self._refresh()

    def set_side(self, side: int):
        """Alias retro-compatible de set_rect(side, side) — carre."""
        self.set_rect(side, side)

    def set_rect(self, width: int, height: int):
        if width > 0 and height > 0:
            self.setFixedSize(width, height)
        self._refresh()

    def _refresh(self):
        width, height = self.width(), self.height()
        if width <= 0 or height <= 0 or self._raw.isNull():
            self.clear()
            return
        # Padding (voir Colonnes > Apercu > Image) N'EST PLUS gere ici : le
        # widget recoit desormais directement sa taille FINALE, deja
        # reduite du padding par _PreviewBlock (voir sa remarque, "la
        # largeur de l'image correspond a la largeur de la colonne moins
        # les differents padding") — ce widget ne fait plus que recadrer
        # "cover"/arrondir sur SA PROPRE taille, sans plus rien composer
        # dedans. Rayon (dict 4 coins INDEPENDANTS, voir apply_all_
        # settings) : minimum=0 — une valeur reglee a 0 doit le rester
        # (voir scaled).
        radius = {k: scaled(v, 0) for k, v in _radius_dict(ui_state.PREVIEW_IMAGE_RADIUS).items()}
        # _cover_crop_rect (PAS un simple scaled()) : "remplir" (recadre en
        # conservant le ratio, comme le fond d'ecran Windows), voir la
        # remarque de l'utilisateur, "l'image d'origine doit s'adapter aux
        # dimensions choisies ... comme 'remplir' dans Windows".
        cropped = _cover_crop_rect(self._raw, width, height)
        if not _radius_any(radius):
            self.setPixmap(cropped)
            return
        # Coins arrondis (voir Colonnes > Apercu > Image) : masque construit
        # a la main (REMPLISSAGE antialiase + CONTOUR de composition
        # DestinationIn via drawPixmap), PAS un fillPath direct sur
        # `masked` — MEME correctif/MEME raison que _paint_row_image (voir
        # sa docstring) : fillPath ne compose que les pixels que le CHEMIN
        # touche reellement, laissant les coins (hors chemin) intacts/
        # opaques — un fillPath direct ici est EXACTEMENT le bug signale
        # par l'utilisateur, "les coins arrondis ... ça ne fonctionne
        # pas". Un mask PIXMAP intermediaire, lui, couvre le rectangle
        # ENTIER (drawPixmap touche tous les pixels), donc les coins y
        # redeviennent bien transparents.
        mask = QPixmap(width, height)
        mask.fill(Qt.transparent)
        mkp = QPainter(mask)
        mkp.setRenderHint(QPainter.Antialiasing, True)
        mkp.setPen(Qt.NoPen)
        mkp.setBrush(Qt.white)
        mkp.drawPath(_rounded_rect_path(QRect(0, 0, width, height), radius))
        mkp.end()

        masked = QPixmap(width, height)
        masked.fill(Qt.transparent)
        mp = QPainter(masked)
        mp.setRenderHint(QPainter.Antialiasing, True)
        mp.drawPixmap(0, 0, cropped)
        mp.setCompositionMode(QPainter.CompositionMode_DestinationIn)
        mp.drawPixmap(0, 0, mask)
        mp.end()
        self.setPixmap(masked)

class _StatusLabel(QLabel):
    """Un des trois indicateurs in/over/out en tete d'un _PreviewBlock : voir
    STATUS_FOLDERS/status_folder_state. Sombre et inerte si le dossier
    correspondant est vide/absent, clair et cliquable (ouvre le dossier) des
    qu'il contient quelque chose."""

    clicked = Signal()

    def __init__(self, name: str, active: bool, parent=None, font_size: int = 10,
                 active_color: str | None = None, idle_color: str | None = None,
                 font_family: str | None = None, smoothing: str = "current",
                 weight: int = 700, italic: bool = False):
        super().__init__(name.upper(), parent)
        self._active = active
        # `font_family` (voir Colonnes > Apercu > Zone titre > Polices >
        # "Apercu des dossiers") : famille REELLEMENT resolue (voir
        # _resolve_font_family), pas le libelle stocke — None = role
        # "info" par defaut (comportement INCHANGE). `smoothing` (voir
        # _OverrideSmoothingField) : role_font n'accepte pas de surcharge
        # explicite (suit toujours le lissage DU ROLE) — on en extrait
        # seulement la famille ici, `font()` applique ensuite le lissage
        # demande par-dessus.
        resolved_family = font_family or role_font("info", font_size, 700, tracking=0.08).family()
        self.setFont(font(font_size, weight, family=resolved_family, tracking=0.08, smoothing=smoothing, italic=italic))
        # C["text"]/C["dim"] directement, PAS role_color("info", ...) : ce
        # role peut etre personnalise par l'utilisateur (fenetre de
        # parametres) avec une couleur fixe, qui ecraserait alors les DEUX
        # branches actif/inactif avec la meme teinte (role_color ignore le
        # `default_hex` passe des qu'une surcharge existe) — l'etat vide/
        # rempli du dossier ne doit jamais dependre de ce reglage.
        # `active_color`/`idle_color` (voir Colonnes > Apercu > Zone titre >
        # Polices > "Apercu des dossiers"/"Non selectionne", MEME ligne —
        # voir la remarque de l'utilisateur, "ajoute une couleur : non
        # selectionne, sur la meme ligne que apercu des dossiers -
        # couleur").
        color = (active_color or C["text"]) if active else (idle_color or C["dim"])
        self.setStyleSheet(f"color: {color}; background: transparent;")
        if active:
            self.setCursor(Qt.PointingHandCursor)

    def mousePressEvent(self, event):
        if self._active and event.button() == Qt.LeftButton:
            self.clicked.emit()
        super().mousePressEvent(event)

class _ColumnStyleBorderOverlay(QWidget):
    """Fine couche transparente, toujours AU-DESSUS des autres enfants (voir
    _PreviewBlock, raise_ee a chaque redimensionnement) :
    peint SEULEMENT la bordure/le rayon "style colonne" (voir
    _paint_column_style_border) PAR-DESSUS le contenu deja peint (l'image
    bord a bord y compris) — un paintEvent directement sur le widget parent
    serait, lui, peint AVANT ses enfants (l'ordre normal de composition
    Qt : parent, puis enfants par-dessus), donc recouvert par l'image
    plutot que visible par-dessus elle."""

    def __init__(self, parent):
        super().__init__(parent)
        self.setAttribute(Qt.WA_TransparentForMouseEvents, True)
        self.setStyleSheet("background: transparent;")

    def paintEvent(self, event):
        _paint_column_style_border(self)

def _paint_column_style_border(widget: QWidget):
    """Peint, PAR-DESSUS le contenu deja affiche de `widget`, le MEME cadre
    (bordure/rayon, PAS le fond — deja peint par le style-sheet du widget)
    que celui des vraies colonnes (voir app_style.column_frame_style,
    style GENERAL) — voir la remarque de l'utilisateur, "je veux les trois
    colonnes (avec style predefini dans les settings) les unes sur les
    autres" : _PreviewBlock doit avoir l'air d'une colonne a lui seul.
    PREVIEW_STACK_TITLE (PAS "Sous-projet", contrairement a une version
    precedente) : "Sous-projet" est desormais un titre SURCHARGEABLE (voir
    settings_window._build_column_override_page), une surcharge active la
    aurait alors fuite ICI (sur le bloc "Projets" aussi, montre avec le
    MEME style que celui de "Sous-projet") au lieu du style GENERAL voulu
    pour ce cadre "decoratif" — PREVIEW_STACK_TITLE n'est jamais surcharge,
    garantit donc TOUJOURS le style general, quoi que l'utilisateur regle
    par ailleurs. scaled() sur rayon/epaisseur : meme raison que Column.
    refresh_colors (coherence a l'echelle d'interface)."""
    frame = column_frame_style(PREVIEW_STACK_TITLE)
    radius = {k: scaled(v, 0) for k, v in frame["radius"].items()}
    thickness = scaled(frame["thickness"], 0)
    painter = QPainter(widget)
    painter.setRenderHint(QPainter.Antialiasing, _radius_any(radius))
    _paint_bordered_rect(painter, widget.rect(), radius, frame["enabled"], thickness, frame["colors"], None)
    painter.end()

class _PreviewBlock(QWidget):
    """Contenu d'UNE colonne fantome de l'apercu (voir PreviewColumn.
    set_preview_block) : une rangee d'indicateurs in/over/out, une grande
    barre de titre « affiche » (nom du projet/sous-projet), suivies
    directement (sans espace) de son image carree bord a bord avec la
    colonne. `width` (la largeur de contenu de la colonne au moment de la
    construction) fixe la taille de l'image des le depart — voir
    _SquarePreviewImage.set_side. `path` sert a determiner l'etat des trois
    indicateurs (voir status_folder_state) ; `open_status(folder_path)` est
    appele au clic sur un indicateur actif (voir
    PipelineBrowser._open_group_folder : ouvre son contenu dans la colonne
    suivante, pas dans l'explorateur Windows). PAS d'entete ICI : chaque
    niveau (Projets/Sous-projet) est une VRAIE colonne fantome a part
    entiere (voir PreviewColumn, construite avec son PROPRE titre reel),
    empilees VERTICALEMENT (une colonne sous l'autre, PAS cote a cote —
    voir PipelineBrowser.update_preview_stack), ce bloc n'est que le
    CONTENU de l'une d'elles — voir la remarque de l'utilisateur, "non,
    tu as merger les deux colonnes en une seule, ce que je veux c'est deux
    colonnes separees, une en dessous de l'autre !"."""

    def __init__(self, title: str, pixmap: QPixmap, width: int, path: Path, open_status,
                 source_column: "Column" = None, parent=None):
        super().__init__(parent)
        # Chemin REPRESENTE par ce bloc (le dossier Projet/Sous-projet/
        # niveau configure actuellement selectionne) — garde ici (self.
        # _path) pour le menu clic droit (voir _on_context_menu, la
        # remarque de l'utilisateur, "les fichiers et dossiers de focus ne
        # fonctionnent pas comme les autres colonnes, notamment pour le
        # clic droit") : jusqu'ici ce widget n'avait AUCUNE interaction
        # clic droit du tout, contrairement a une ligne normale (voir
        # Column._on_context_menu). `source_column` (voir _rename) : la
        # VRAIE colonne de navigation dont ce bloc reprend la selection
        # courante — permet de renommer avec la MEME resynchronisation de
        # la navigation qu'une ligne normale (voir Column._rename_item) —
        # voir la remarque de l'utilisateur, "je veux que le comportement
        # des colonnes fonctionne de la meme maniere sur tous les points".
        self._path = path
        self._source_column = source_column
        self.setContextMenuPolicy(Qt.CustomContextMenu)
        self.customContextMenuRequested.connect(self._on_context_menu)
        # Style EFFECTIF de Colonnes > Apercu (voir app_style.column_style_
        # for/PREVIEW_STACK_TITLE) — "Zone titre" (hauteur/police du titre/
        # police de l'apercu des dossiers) — voir la remarque de
        # l'utilisateur, "toujours dans la section colonnes/apercu, je veux
        # une section 'zone titre' avec les parametres suivants : hauteur
        # ... polices : titre (taille, couleur, padding) ... apercu des
        # dossiers (taille, couleur, padding)".
        s = column_style_for(PREVIEW_STACK_TITLE)
        title_height = int(s.get("preview_title_zone_height", PREVIEW_TITLE_HEIGHT))
        title_font_size = int(s.get("preview_title_font_size", 26))
        title_font_color = resolve_color_ref(s.get("preview_title_font_color", "#d6d9dc"))
        # Choix de police (police du soft ou police systeme, voir
        # _resolve_font_family/_DualFontSelectField) — voir la remarque de
        # l'utilisateur, "je veux le choix de la police (titre + apercu
        # des dossiers) (choix entre polices appli ou polices systeme)".
        title_font_weight = 700 if s.get("preview_title_font_bold", True) else 400
        title_font_italic = bool(s.get("preview_title_font_italic", False))
        title_font_family = _resolve_font_family(
            (s.get("preview_title_font_family") or "").strip(), title_font_size, title_font_weight)
        # Lissage (voir Colonnes > Texte > Lissage, MEME mecanique
        # toggle+niveau) — voir la remarque de l'utilisateur, "ajoute les
        # niveaux de lissage sur les lignes des polices".
        title_font_smoothing = (
            s.get("preview_title_font_smoothing", "current")
            if s.get("preview_title_font_smoothing_enabled") else "current")
        title_pad = s.get("preview_title_padding") or {"left": 14, "top": 0, "right": 14, "bottom": 8}
        status_font_size = int(s.get("preview_status_font_size", 10))
        status_font_color = resolve_color_ref(s.get("preview_status_font_color", "#d6d9dc"))
        status_font_color_idle = resolve_color_ref(s.get("preview_status_font_color_idle", "#5f666b"))
        status_font_weight = 700 if s.get("preview_status_font_bold", True) else 400
        status_font_italic = bool(s.get("preview_status_font_italic", False))
        status_font_family = _resolve_font_family(
            (s.get("preview_status_font_family") or "").strip(), status_font_size, status_font_weight,
            fallback_role="info")
        status_font_smoothing = (
            s.get("preview_status_font_smoothing", "current")
            if s.get("preview_status_font_smoothing_enabled") else "current")
        status_pad = s.get("preview_status_padding") or {"left": 14, "top": 0, "right": 14, "bottom": 0}

        # Fond unique du bloc entier (indicateurs + titre + image), pas
        # seulement derriere l'image : la "grande affiche" doit se lire
        # comme un seul panneau, sans bande de couleur differente au-dessus.
        # MEME couleur que le cadre de la colonne (Colonnes > Focus >
        # Colonnes > Couleur de fond, voir app_style.column_frame_style,
        # PAS C["chrome"] fige comme avant) : sinon, la ou l'entete est
        # masquee (header_visible=False) ou la zone titre reste
        # transparente, ce bloc laissait voir C["chrome"] au lieu de cette
        # couleur — voir la remarque de l'utilisateur, "la couleur de fond
        # doit aussi controler les zones avec la croix rouge sur le
        # screenshot et la zone sous l'entete".
        # WA_StyledBackground indispensable ici : ce widget est un ENFANT
        # (dans preview_layout/PreviewColumn, eux-memes dans la fenetre),
        # pas une fenetre top-level — sans cet attribut, Qt
        # n'applique jamais le fond du style-sheet sur un simple QWidget
        # enfant (il retombe sur le fond herite de ses parents, ici
        # C["window"] via la regle globale QWidget), meme si le style-sheet
        # semble correct. Piege deja documente ailleurs dans ce fichier
        # (TitleBar, DetailPanel, PreviewColumn) — oublie ici la premiere
        # fois, d'ou le fond incoherent malgre un style-sheet "correct".
        block_bg = resolve_color_ref(s.get("column_bg_color", "@skinN2"))
        self.setAttribute(Qt.WA_StyledBackground, True)
        self.setStyleSheet(f"background: {block_bg};")
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        status_bar = QWidget()
        status_bar.setFixedHeight(PREVIEW_STATUS_HEIGHT)
        # MEME couleur que le reste du bloc (block_bg, Colonnes > Focus >
        # Colonnes > Couleur de fond) — PAS de fond de selection sous les
        # items des colonnes Focus (essaye puis retire, voir la remarque
        # de l'utilisateur, "je ne veux pas de fond de selection sous les
        # items des colonnes focus"). Aucun filet entre les indicateurs et
        # le titre (border: none, EXPLICITE) — juste explicite ici pour ne PAS
        # heriter d'un style par defaut.
        status_bar.setAttribute(Qt.WA_StyledBackground, True)
        status_bar.setStyleSheet(f"background: {block_bg}; border: none;")
        status_layout = QHBoxLayout(status_bar)
        status_layout.setContentsMargins(
            int(status_pad.get("left", 14)), int(status_pad.get("top", 0)),
            int(status_pad.get("right", 14)), int(status_pad.get("bottom", 0)))
        status_layout.setSpacing(14)
        status_layout.addStretch(1)
        for name in STATUS_FOLDERS:
            active, folder_path = status_folder_state(path, name)
            label = _StatusLabel(
                name, active, font_size=status_font_size,
                active_color=status_font_color, idle_color=status_font_color_idle,
                font_family=status_font_family, smoothing=status_font_smoothing,
                weight=status_font_weight, italic=status_font_italic)
            if active:
                label.clicked.connect(lambda p=folder_path: open_status(p))
            status_layout.addWidget(label)
        layout.addWidget(status_bar)
        self._status_bar = status_bar

        title_bar = QWidget()
        title_bar.setFixedHeight(title_height)
        # MEME couleur que status_bar/le reste du bloc (block_bg) — voir sa
        # remarque juste au-dessus.
        title_bar.setAttribute(Qt.WA_StyledBackground, True)
        title_bar.setStyleSheet(f"background: {block_bg}; border: none;")
        title_layout = QHBoxLayout(title_bar)
        title_layout.setContentsMargins(
            int(title_pad.get("left", 14)), int(title_pad.get("top", 0)),
            int(title_pad.get("right", 14)), int(title_pad.get("bottom", 8)))
        name = QLabel(title)
        name.setFont(font(
            title_font_size, title_font_weight, family=title_font_family, tracking=0.0,
            smoothing=title_font_smoothing, italic=title_font_italic))
        name.setStyleSheet(f"color: {title_font_color}; background: transparent;")
        # Colle au bas de la barre de titre (juste au-dessus de l'image),
        # pas centre sur toute sa hauteur : plus proche de l'image, plus
        # affiche.
        title_layout.addWidget(name, 0, Qt.AlignBottom | Qt.AlignLeft)
        layout.addWidget(title_bar)
        self._title_bar = title_bar

        # Toujours enveloppee dans image_wrap (meme si le padding est nul) :
        # une structure STABLE, jamais reconstruite, est necessaire pour
        # pouvoir juste re-appeler apply_width() plus tard (voir
        # PreviewColumn.resize_update) sans reconstruire tout le bloc a
        # chaque glisser de bordure — voir la remarque de l'utilisateur,
        # "je veux pouvoir controler la largeur des colonnes focus projet
        # et sous projet en slidant les bords de celles-ci ... la largeur
        # des images ... doit etre egale a cette largeur de colonne".
        self.image = _SquarePreviewImage()
        self.image.set_source_pixmap(pixmap)
        self._image_wrap = QWidget()
        # MEME couleur que status_bar/title_bar/le reste du bloc (block_bg)
        # — visible dans la marge du Padding de l'image (voir
        # _image_wrap_layout.setContentsMargins plus bas).
        self._image_wrap.setAttribute(Qt.WA_StyledBackground, True)
        self._image_wrap.setStyleSheet(f"background: {block_bg}; border: none;")
        self._image_wrap_layout = QVBoxLayout(self._image_wrap)
        self._image_wrap_layout.setContentsMargins(0, 0, 0, 0)
        self._image_wrap_layout.setSpacing(0)
        self._image_wrap_layout.addWidget(self.image)
        layout.addWidget(self._image_wrap)

        # PAS de filet sous l'image (essaye un temps, widget dedie sous
        # l'image) : redondant avec _ColumnStyleBorderOverlay (voir plus
        # bas), qui peint deja la bordure "colonne" complete (y compris son
        # cote haut, juste sous le bloc precedent) — deux traits l'un sous
        # l'autre a la jonction — voir la remarque de l'utilisateur,
        # "supprime la bordure qu'il y a sous la colonne (juste sous
        # l'image)".
        self.apply_width(width)

        # Style "colonne" (bordure/rayon des settings, voir
        # _paint_column_style_border) par-dessus tout le bloc — voir
        # _ColumnStyleBorderOverlay, la remarque de l'utilisateur.
        self._border_overlay = _ColumnStyleBorderOverlay(self)
        self._border_overlay.setGeometry(self.rect())
        self._border_overlay.raise_()
        # APRES la construction de _status_bar/_title_bar/_image_wrap/
        # self.image (voir _connect_context_menu, sa remarque) : cable le
        # clic droit EN PLUS sur chacun d'eux.
        self._connect_context_menu()

    def apply_width(self, width: int):
        """Recalcule la largeur/hauteur de l'image (et la hauteur totale du
        bloc) pour une largeur de colonne donnee — appelee une fois a la
        construction, puis a nouveau a CHAQUE glisser de bordure (voir
        PreviewColumn.resize_update), sans reconstruire le reste du bloc
        (entete/statut/zone titre INCHANGES) — voir la remarque de
        l'utilisateur, "je veux pouvoir controler la largeur des colonnes
        focus projet et sous projet en slidant les bords de celles-ci ...
        la largeur des images de ces colonnes doit etre egale a cette
        largeur de colonne". Re-resout le style a CHAQUE appel (pas de
        valeurs mises en cache a la construction) : reste coherent meme si
        Colonnes > Focus change entre-temps (previsualisation en direct)."""
        s = column_style_for(PREVIEW_STACK_TITLE)
        title_height = int(s.get("preview_title_zone_height", PREVIEW_TITLE_HEIGHT))
        img_ratio = float(s.get("item_image_ratio", 1.0) or 1.0)
        # Padding de l'image (voir Colonnes > Apercu > Image) : une marge de
        # layout REELLE autour de _SquarePreviewImage (voir _image_wrap
        # ci-dessus) plutot qu'un inset compose a l'interieur d'un widget de
        # taille pleine colonne — voir la remarque de l'utilisateur, "de
        # base, la largeur de l'image correspond a la largeur de la colonne
        # moins les differents padding (a calculer)".
        pad = s.get("preview_padding") or {}
        pad_left = max(0, scaled(int(pad.get("left", 0)), 0))
        pad_top = max(0, scaled(int(pad.get("top", 0)), 0))
        pad_right = max(0, scaled(int(pad.get("right", 0)), 0))
        pad_bottom = max(0, scaled(int(pad.get("bottom", 0)), 0))
        available_width = max(1, width - pad_left - pad_right)
        # Largeur TOUJOURS calee sur la largeur de colonne (moins le
        # padding), hauteur deduite du Ratio — plus de reglage "Hauteur de
        # l'image" (voir Colonnes > Focus > Colonnes > Image, ancienne cle
        # preview_image_height, retiree) — voir la remarque de
        # l'utilisateur, "supprime la ligne hauteur de l'image et calle la
        # largeur de l'image a la largeur de la colonne".
        img_width = available_width
        img_height = max(1, round(available_width / img_ratio))
        self.image.set_rect(img_width, img_height)
        self._image_wrap_layout.setContentsMargins(pad_left, pad_top, pad_right, pad_bottom)
        image_area_height = pad_top + img_height + pad_bottom

        # Sans une hauteur EXPLICITE, ce widget garde une politique de
        # taille verticale "Preferred" par defaut : des qu'un parent (voir
        # Column) lui offre plus de hauteur que son contenu n'en a besoin
        # (ex. la liste TYPE capee plus haut libere de la place), Qt etire
        # le bloc au-dela de sa hauteur reelle et repartit l'exces en
        # espaces morts AVANT, ENTRE et APRES ses sous-elements —
        # exactement le defaut visible (grand vide au-dessus du titre,
        # avant l'image). PAS d'entete ICI (elle vit sur la PreviewColumn
        # qui heberge ce bloc, voir set_preview_block) : PREVIEW_STATUS_
        # HEIGHT + title_height + img_height (PAS PREVIEW_BLOCK_EXTRA_
        # HEIGHT + width, fige sur les anciennes constantes/le carre) :
        # hauteur EFFECTIVE, ratio/hauteur de zone titre compris.
        self.setFixedHeight(PREVIEW_STATUS_HEIGHT + title_height + image_area_height)

    def install_resize_filter(self, owner: QWidget):
        """Installe `owner` (PreviewColumn, voir resize_begin/resize_update/
        _in_resize_zone) comme filtre d'evenements sur chacune des barres
        pleine-largeur de ce bloc (statut/zone titre/image) : sans
        ceci, un widget ENFANT sous le curseur intercepte l'evenement souris
        AVANT que PreviewColumn ne le voie, rendant la bordure de
        redimensionnement inaccessible des que le curseur survole un bloc
        empile — MEME piege/MEME correctif que Column (voir son
        eventFilter/installEventFilter dans __init__) — voir la remarque de
        l'utilisateur, "je veux pouvoir controler la largeur des colonnes
        focus projet et sous projet en slidant les bords de celles-ci".
        setMouseTracking(True) sur chacun : Column.header s'en charge deja
        explicitement (voir Column.__init__), mais un QWidget/QLabel simple
        ne le fait PAS par defaut (contrairement au viewport d'un
        QListWidget, qui l'active tout seul) — sans lui, Qt ne livre les
        MouseMove de survol (sans bouton enfonce) a AUCUN de ces widgets,
        donc jamais a l'eventFilter installe dessus : le curseur ne se
        changeait jamais en fleche de redimensionnement en survolant un
        bloc, rendant la bordure impossible a reperer avant de cliquer a
        l'aveugle — voir la remarque de l'utilisateur, "je n'arrive pas
        bien a selectionner le bord des colonnes de focus pour le
        redimensionnement"."""
        for w in (self._status_bar, self._title_bar, self._image_wrap, self.image):
            w.setMouseTracking(True)
            w.installEventFilter(owner)

    def _on_context_menu(self, pos):
        """Relais pour self.customContextMenuRequested (voir __init__) —
        `pos` LOCALE a `self` : voir _show_context_menu pour le VRAI menu,
        partage avec _connect_context_menu (cable EN PLUS sur chaque
        widget ENFANT pleine-largeur, voir sa remarque)."""
        self._show_context_menu(self.mapToGlobal(pos))

    def _connect_context_menu(self):
        """Cable le menu clic droit EN PLUS sur chaque widget ENFANT
        pleine-largeur du bloc (statut/zone titre/image — MEME liste que
        install_resize_filter, MEME raison), pas SEULEMENT sur `self` —
        voir la remarque de l'utilisateur, "le menu clic droit n'apparait
        pas dans les colonnes focus" : compter sur la seule PROPAGATION
        Qt d'un QContextMenuEvent ignore vers le widget PARENT (ce que
        `self.setContextMenuPolicy` seul suppose) s'est avere peu fiable
        ici — voir install_resize_filter, qui documente DEJA exactement
        le meme piege ("un widget ENFANT sous le curseur intercepte
        l'evenement AVANT que le parent ne le voie") pour le
        redimensionnement, corrige alors de la MEME facon (installation
        EXPLICITE sur chaque enfant plutot que de compter sur la
        remontee). Appelee en FIN de __init__, une fois ces widgets
        construits (contrairement a self.setContextMenuPolicy, deja pose
        plus haut des la construction)."""
        for child in (self._status_bar, self._title_bar, self._image_wrap, self.image):
            child.setContextMenuPolicy(Qt.CustomContextMenu)
            child.customContextMenuRequested.connect(
                lambda pos, w=child: self._show_context_menu(w.mapToGlobal(pos)))

    def _show_context_menu(self, global_pos):
        """Menu clic droit du bloc Focus (voir _on_context_menu/
        _connect_context_menu, `global_pos` deja en coordonnees GLOBALES,
        source unique partagee par tous les points d'entree) — voir la
        remarque de tete de classe, "les fichiers et dossiers de focus ne
        fonctionnent pas comme les autres colonnes, notamment pour le
        clic droit" : ce bloc n'avait jusqu'ici AUCUNE interaction clic
        droit, contrairement a une ligne normale (voir Column.
        _on_context_menu). MEME ensemble complet d'actions qu'une ligne
        DOSSIER normale desormais (voir _rename, la remarque de
        l'utilisateur, "je veux que le comportement des colonnes
        fonctionne de la meme maniere sur tous les points") — Renommer +
        Afficher dans l'explorateur + image personnalisee (vignette de
        PROJET, exactement celle affichee ici, voir
        project_thumbnail_pixmap) + Copier/Copier le chemin."""
        path = self._path
        menu = QMenu(self)
        menu.setFont(font(11, 400))
        act_rename = menu.addAction("Renommer") if self._source_column is not None else None
        act_reveal = menu.addAction("Afficher dans l'explorateur")
        menu.addSeparator()
        has_custom = project_thumbnail_path(path).is_file()
        act_change_thumb = menu.addAction("Changer l'image..." if has_custom else "Ajouter un apercu...")
        act_capture_thumb = menu.addAction("Capturer une zone d'ecran...")
        act_reset_thumb = menu.addAction("Reinitialiser l'image") if has_custom else None
        menu.addSeparator()
        act_copy_file = menu.addAction("Copier")
        act_copy_path = menu.addAction("Copier le chemin")
        chosen = menu.exec(global_pos)
        if act_rename is not None and chosen is act_rename:
            self._rename()
        elif chosen is act_reveal:
            reveal_in_file_manager(path)
        elif chosen is act_change_thumb:
            _prompt_change_thumbnail(self, path, self._refresh_thumbnail)
        elif chosen is act_capture_thumb:
            _prompt_capture_thumbnail(self, path, self._refresh_thumbnail)
        elif act_reset_thumb is not None and chosen is act_reset_thumb:
            _prompt_reset_thumbnail(self, path, self._refresh_thumbnail)
        elif chosen is act_copy_file:
            mime = QMimeData()
            mime.setUrls([QUrl.fromLocalFile(str(path))])
            QApplication.clipboard().setMimeData(mime)
        elif chosen is act_copy_path:
            QApplication.clipboard().setText(str(path))

    def _rename(self):
        """Renomme le dossier REPRESENTE PAR LA SELECTION COURANTE de la
        VRAIE colonne source (voir __init__/_source_column) — MEME
        validations que Column._rename_item (caracteres interdits,
        collision de nom, erreur disque), pour un comportement identique
        a une ligne normale. La resynchronisation de la navigation
        (colonnes filles construites depuis l'ANCIEN chemin, redessin du
        bloc Focus lui-meme...) n'est PAS geree ICI a la main : comme pour
        Column._rename_item, on se contente de RAFRAICHIR la vraie
        colonne source puis d'y RESELECTIONNER l'item renomme —
        currentItemChanged declenche alors normalement Column.
        _on_current_changed -> PipelineBrowser.on_selected, qui fait deja
        tout le reste (prune_after + reconstruction, y compris ce bloc
        Focus lui-meme via update_preview_stack) — exactement le meme
        chemin qu'un Renommer sur une ligne normale, aucune duplication de
        logique."""
        column = self._source_column
        if column is None:
            return
        path = self._path
        new_name, ok = QInputDialog.getText(self, "Renommer", "Nouveau nom :", QLineEdit.Normal, path.name)
        if not ok:
            return
        new_name = new_name.strip()
        if not new_name or new_name == path.name:
            return
        if any(ch in new_name for ch in '\\/:*?"<>|'):
            QMessageBox.warning(self, "Renommer", "Le nom contient des caracteres interdits.")
            return
        new_path = path.with_name(new_name)
        if new_path.exists():
            QMessageBox.warning(self, "Renommer", f"« {new_name} » existe deja.")
            return
        try:
            path.rename(new_path)
        except OSError as exc:
            QMessageBox.warning(self, "Renommer", f"Impossible de renommer :\n{exc}")
            return
        column.refresh()
        for i in range(column.list.count()):
            it = column.list.item(i)
            if it.data(ROLE_PATH) == str(new_path):
                column.list.setCurrentItem(it)
                break

    def _refresh_thumbnail(self):
        """Recharge la vignette (voir project_thumbnail_pixmap, cache par
        date de modification — deja invalide des l'ecriture/suppression du
        fichier, voir _prompt_change_thumbnail/_prompt_capture_thumbnail/
        _prompt_reset_thumbnail) apres une modification depuis CE bloc —
        contrairement a une ligne normale (self.list.viewport().update(),
        qui redessine une DELEGATE a partir du modele), ce bloc affiche
        l'image directement dans un widget deja construit, il faut donc
        explicitement lui repasser le nouveau pixmap."""
        self.image.set_source_pixmap(project_thumbnail_pixmap(self._path))

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._border_overlay.setGeometry(self.rect())
        self._border_overlay.raise_()

class _RoundedCornersEffect(QGraphicsEffect):
    """Decoupe self.card (fond + TOUS ses enfants, entete/liste compris) a
    la silhouette de son rayon d'angle, AVEC anti-aliasing — remplace
    Column._update_card_mask/QWidget.setMask() : un QRegion est un
    decoupage BINAIRE (pixel dedans/dehors, jamais de demi-teinte), ce qui
    rendait les coins arrondis visiblement crenelés/en escalier — voir la
    remarque de l'utilisateur, capture a l'appui, "les arrondis sont
    degueulasse, ils ne sont pas lisses". Technique standard Qt pour un
    coin arrondi lisse sur un widget composite : peindre le widget (et ses
    enfants) dans un pixmap hors-ecran (sourcePixmap), puis le recomposer
    ICI a travers un QPainterPath arrondi avec Antialiasing actif — la
    MEME geometrie que celle reellement peinte par _ColumnCard.paintEvent
    (_rounded_rect_path), pour rester coherent avec le fond/la bordure."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._radius: dict = {}

    def setRadius(self, radius: dict):
        self._radius = radius
        self.update()

    def draw(self, painter: QPainter):
        """QPainter.setClipPath (1er essai, voir git blame) NE PRODUIT PAS
        d'arrondi vraiment antialiase sur le moteur de rendu RASTER de Qt
        (celui utilise ici, PAS OpenGL) : un clip y retombe sur un masque
        BINAIRE en interne, meme render hint Antialiasing actif — voir la
        remarque de l'utilisateur, comparaison a l'appui (VSCode/Electron,
        qui compose ses coins arrondis via le GPU, PAS ce chemin), "j'ai du
        mal a croire qu'il n'existe pas un autre algorithme... regarde le
        screen, il s'agit de vscode... admet qu'il y a un probleme". Fix :
        construire le masque a la main via un REMPLISSAGE (fillPath, PAS un
        clip — le remplissage, lui, est correctement antialiase par le
        moteur raster) d'un pixmap ARGB transparent, puis composer ce
        pixmap source AU TRAVERS de ce masque via CompositionMode_
        DestinationIn (l'alpha du masque, deja lisse, multiplie celui de
        l'image source) — technique Qt standard pour un decoupage
        VRAIMENT antialiase, contrairement a un simple clip path."""
        offset = QPoint()
        pixmap = self.sourcePixmap(Qt.LogicalCoordinates, offset)
        if pixmap.isNull():
            return
        dpr = pixmap.devicePixelRatio() or 1.0
        w = int(round(pixmap.width() / dpr))
        h = int(round(pixmap.height() / dpr))
        # PAS de marge elargie ici (essaye puis abandonne — voir git blame,
        # "la bordure disparait completement dans l'arrondi") : cette
        # meme classe sert AUSSI a self._content_effect (voir Column.
        # _update_card_mask), dont le rayon (RETRECI, inner_radius) doit
        # rester EXACT — l'elargir laissait l'entete/la liste (coins
        # carres) deborder PAR-DESSUS l'anneau de la bordure exactement
        # dans la courbe, la ou l'entete est peinte SANS son propre rayon
        # (voir column_header_qss, "plus de nibbling... le rognage visuel
        # est deja garanti par ce decoupage") — recouvrant entierement la
        # bordure a cet endroit precis. self._card_effect, lui, n'a de
        # toute facon plus besoin d'etre actif des qu'une bordure existe
        # (voir _update_card_mask, setEnabled) : plus rien ici a compenser
        # par une marge.
        path = _rounded_rect_path(QRect(0, 0, w, h), self._radius)
        # Masque construit a la main dans un pixmap SEPARE (REMPLISSAGE
        # antialiase dans un pixmap transparent DEDIE), PAS un fillPath
        # DIRECT sur `masked` en mode DestinationIn — MEME correctif/MEME
        # raison que _paint_row_image/_SquarePreviewImage._refresh (voir
        # leurs docstrings) : un fillPath direct dans ce mode ne compose
        # que les pixels que le CHEMIN touche reellement, laissant les
        # coins (hors chemin) intacts/opaques des que RIEN d'autre ne les
        # recouvre par-dessus (typiquement une bordure, qui masquait ce
        # defaut jusqu'ici) — exactement le bug signale par l'utilisateur,
        # "quand on n'a pas d'entete ... les coins arrondis doivent etre
        # present" (sans bordure ni entete pour le camoufler). Un mask
        # PIXMAP intermediaire, lui, couvre le rectangle ENTIER (drawPixmap
        # touche tous les pixels), donc les coins y redeviennent bien
        # transparents.
        mask = QPixmap(pixmap.size())
        mask.setDevicePixelRatio(dpr)
        mask.fill(Qt.transparent)
        mkp = QPainter(mask)
        mkp.setRenderHint(QPainter.Antialiasing, True)
        mkp.setPen(Qt.NoPen)
        mkp.setBrush(Qt.white)
        mkp.drawPath(path)
        mkp.end()

        masked = QPixmap(pixmap.size())
        masked.setDevicePixelRatio(dpr)
        masked.fill(Qt.transparent)
        mp = QPainter(masked)
        mp.setRenderHint(QPainter.Antialiasing, True)
        mp.drawPixmap(0, 0, pixmap)
        mp.setCompositionMode(QPainter.CompositionMode_DestinationIn)
        mp.drawPixmap(0, 0, mask)
        mp.end()
        painter.drawPixmap(offset, masked)

class _ColumnCard(QWidget):
    """Porte le fond/la bordure REELS d'une colonne (voir Column.card) —
    peinte a la main (QPainter, _paint_bordered_rect, MEME technique que
    settings_window._ColumnPreview) plutot que via border-radius QSS : la
    QSS et le masque de decoupe des enfants (voir Column._update_card_mask)
    utilisaient chacun leur PROPRE geometrie de coin arrondi (le moteur de
    style de Qt d'un cote, un chemin arrondi maison de l'autre), jamais
    parfaitement identiques — la bordure ne "enveloppait" alors pas
    exactement le masque — voir la remarque de l'utilisateur, capture a
    l'appui, "le cadre n'enveloppe pas les bordures radius". Peindre ICI
    avec la MEME fonction (_rounded_rect_path, via _paint_bordered_rect)
    que celle qui calcule le masque garantit desormais une geometrie
    identique au pixel pres."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._bg = "#000000"
        self._radius: dict = {}
        self._enabled: dict = {}
        self._colors: dict = {}
        self._thickness = 1

    def setFrameStyle(self, bg: str, radius: dict, enabled: dict, colors: dict, thickness: int):
        self._bg, self._radius, self._enabled, self._colors, self._thickness = bg, radius, enabled, colors, thickness
        self.update()

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing, _radius_any(self._radius))
        _paint_bordered_rect(p, self.rect(), self._radius, self._enabled, self._thickness, self._colors, self._bg)
        p.end()

def _widget_containing_layout(widget: QWidget):
    """Layout REEL contenant directement `widget` (voir Column.
    _suppress_left, docstring d'origine pour le detail du piege) —
    factorisee ici pour etre PARTAGEE avec PreviewColumn, qui a exactement
    le meme besoin de detection de voisin de gauche dans columns_layout."""
    parent = widget.parentWidget()
    if parent is None or parent.layout() is None:
        return None

    def search(layout):
        for i in range(layout.count()):
            item = layout.itemAt(i)
            if item.widget() is widget:
                return layout
            sub_layout = item.layout()
            if sub_layout is not None:
                found = search(sub_layout)
                if found is not None:
                    return found
        return None

    return search(parent.layout())

def _column_suppress_left(widget: QWidget, title: str) -> bool:
    """`widget` (une colonne "reelle" OU fantome — Column/PreviewColumn,
    toutes deux membres de columns_layout) a-t-elle une AUTRE colonne
    immediatement a sa gauche ET les 2 cartes se touchent VRAIMENT (aucun
    espace de layout — voir column_gap — ET aucun padding sur le cote qui
    les separe, voir column_padding_for) ? MEME regle que settings_window.
    _ColumnPreview (has_left_neighbor) — un SEUL filet reste visible a la
    frontiere entre 2 colonnes collees (celui de DROITE de celle de
    gauche) plutot que 2 cumules — voir la remarque de l'utilisateur, "je
    veux que les deux bordures qui se chevauchent n'en forment qu'une
    seule". Factorisee ici (auparavant seulement Column._suppress_left) :
    PreviewColumn en a desormais besoin aussi (voir la remarque de
    l'utilisateur, "formate les comme toutes les autres colonnes")."""
    parent_layout = _widget_containing_layout(widget)
    if parent_layout is None:
        return False
    idx = parent_layout.indexOf(widget)
    if idx <= 0 or column_gap() > 0:
        return False
    if column_padding_for(title)["left"] > 0:
        return False
    prev_item = parent_layout.itemAt(idx - 1)
    prev_widget = prev_item.widget() if prev_item is not None else None
    prev_title = getattr(prev_widget, "column_title", None)
    if prev_title is not None and column_padding_for(prev_title)["right"] > 0:
        return False
    return True
