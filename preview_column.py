import hashlib
import math
import mmap
import os
import re
import shutil
import subprocess
import time
from pathlib import Path
from PySide6.QtCore import (
    QEvent, QObject, QPointF, QRunnable, QRect, QRectF, QSize, Qt, QThreadPool, Signal,
)
from PySide6.QtGui import (
    QColor,
    QImage,
    QImageReader,
    QPainter,
    QPen,
    QPixmap,
)
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
    QWidget,
)
from app_style import (
    C,
    PREVIEW_STACK_TITLE,
    font,
    role_color,
    role_font,
    scaled,
    resolve_color_ref,
    column_frame_style,
    column_header_qss,
    column_padding_for,
    column_style_for,
)
import ui_state
from config import (
    PUR_MAX_EMBEDDED_IMAGES,
    TEXT_PREVIEW_MAX_BYTES,
    TEXT_PREVIEW_MAX_LINES,
    _PUR_IMAGE_INDEX_CACHE,
)
from previews import (
    FILE_IMAGE_DISK_CACHE_DIR,
    UI_ICON_COLLAPSE_TOGGLE,
    UI_ICON_SETTINGS_GEAR,
    _bounded_cache_set,
    custom_ui_icon_pixmap,
)
from settings_store import (
    _coerce_side_enabled,
)
from settings_widgets import (
    _paint_bordered_rect,
    _radius_any,
    _radius_dict,
    _radius_shrink,
)
from browser_core import (
    COLUMN_MAX_WIDTH,
    COLUMN_MIN_WIDTH,
    COLUMN_RESIZE_MARGIN,
    _hide_resize_width,
    _persist_column_width,
    _resolve_font_family,
    _show_resize_width,
    col_width,
)
from column import (
    Column,
)
from capture_widgets import (
    _ColumnCard,
    _PreviewBlock,
    _RoundedCornersEffect,
    _column_suppress_left,
)


def _dim_effect(parent):
    from PySide6.QtWidgets import QGraphicsOpacityEffect
    effect = QGraphicsOpacityEffect(parent)
    effect.setOpacity(0.35)
    return effect


class PreviewColumn(QWidget):
    """Colonne sans contenu de dossier propre, juste un apercu (voir
    PipelineBrowser.update_preview_stack) — utilisee pour
    PipelineBrowser.image_preview_columns : DEUX colonnes fantomes SEPAREES,
    une par niveau selectionne (Projets, Sous-projet — voir _PreviewBlock/
    set_preview_block), empilees VERTICALEMENT dans un conteneur commun
    (voir PipelineBrowser._preview_stack_wrapper), PERMANENTES — jamais
    remplacees par une vraie colonne (il n'y a pas de "dossier des images").
    `title` (le titre REEL, cle de style) est TOUJOURS PREVIEW_STACK_TITLE
    pour les 2 : SEUL l'onglet "Focus" des reglages les controle, jamais
    "Projets"/"Sous-projets" (voir `display_title`, le texte d'entete
    AFFICHE — "Focus Projet"/"Focus Sous-projet" — SEPARE de `title`) — voir
    la remarque de l'utilisateur, "il doit y avoir deux colonnes, une focus
    projet et l'autre focus sous projet, je veux aucune autre entete. a
    savoir que les settings 'focus' doivent controler les deux colonnes".

    En-tete + cadre (fond/bordure/rayon/padding) IDENTIQUES a une vraie
    colonne (voir Column.header/card/_content/column_header_qss/
    column_frame_style) — cette colonne fantome n'avait ni l'un ni l'autre
    jusqu'ici (contrairement a toutes les autres) — voir la remarque de
    l'utilisateur, "formate les comme toutes les autres colonnes ... il
    n'y a pas d'espace avec les autres colonnes, la couleur de fond
    derriere la colonne n'est pas bonne" (a propos du gros apercu image
    empile de Projets/Sous-projet une fois une selection faite) : sans un
    VRAI self.card retreci par le Padding (voir refresh_header), self
    peignait deja C['void'] sur la totalite de son rect, y compris la
    marge de padding — rendant ce retrait invisible (aucun contraste de
    couleur) et laissant voir C['void'] au lieu de C['window'] la ou une
    vraie colonne revele le fond de la fenetre."""

    def __init__(self, title: str, parent=None, on_toggle=None,
                 user_width: int | None = None, on_resize=None, fit_height: bool = False,
                 display_title: str | None = None, on_hide_columns=None):
        super().__init__(parent)
        self.column_title = title
        # `display_title` (texte de l'entete, ex. "Focus Projet"/"Focus
        # Sous-projet") : SEPARE de `title`/self.column_title (la cle de
        # STYLE — voir column_style_for/column_header_qss/column_frame_
        # style, toujours PREVIEW_STACK_TITLE pour les 2 colonnes Focus) —
        # voir la remarque de l'utilisateur, "je veux aucune autre entete
        # ... les settings 'focus' doivent controler les deux colonnes" :
        # un SEUL style ("Focus") pour les 2, mais un texte d'entete
        # DIFFERENT par colonne pour les distinguer visuellement.
        self.has_thumbnails = False
        # Hauteur reduite au CONTENU (voir _fit_height_to_content), au lieu
        # de s'etirer jusqu'en bas de la fenetre — SEULEMENT pour le role 1
        # (vignettes Focus, voir PipelineBrowser.update_preview_stack) : le
        # role 2 ("Fichiers pour X", fantome de "Logiciels") doit continuer
        # a remplir toute la hauteur disponible, comme la vraie colonne
        # qu'il remplace — voir la remarque de l'utilisateur, "Reduire les
        # colonnes en hauteur".
        self._fit_height = fit_height
        # Largeur choisie a la main (glisser le bord droit, voir resize_
        # begin/update/end plus bas) — SESSION SEULEMENT, jamais ecrite sur
        # le disque (meme convention que Column._user_width) : `user_width`
        # est fourni par l'appelant (PipelineBrowser, qui le conserve d'un
        # appel a l'autre puisque cette colonne est RECONSTRUITE a chaque
        # update_preview_stack — voir sa remarque), `on_resize(new_width)`
        # le lui renvoie a chaque glisser pour qu'il survive a la
        # prochaine reconstruction — voir la remarque de l'utilisateur,
        # "je veux pouvoir controler la largeur des colonnes focus projet
        # et sous projet en slidant les bords de celles-ci".
        self._user_width = user_width
        self._on_resize = on_resize
        self._resizing = False
        self._resize_start_x = 0
        self._resize_start_width = 0
        self.setMouseTracking(True)

        # header (exterieur, hauteur/padding EFFECTIFS, voir refresh_header)
        # ET header_fill (interieur, voir plus bas) recoivent aussi
        # setMouseTracking(True) explicitement (MEME correctif/MEME raison
        # que _PreviewBlock.install_resize_filter ci-dessous) : sans lui, le
        # survol pur (sans bouton enfonce) de l'entete ne generait jamais de
        # MouseMove, donc jamais d'appel a l'eventFilter installe dessus —
        # le curseur ne changeait jamais en fleche de redimensionnement.
        # enveloppe header_fill (interieur, fond/rayon/cadre CONFIGURABLE de
        # column_header_qss) — EXACTEMENT la meme construction que Column.
        header = QWidget()
        header.setObjectName("PreviewColumnHeaderOuter")
        header.setFixedHeight(scaled(ui_state.HEADER_HEIGHT))
        self.header = header
        header_outer_layout = QVBoxLayout(header)
        pad = scaled(ui_state.HEADER_PADDING, 0)
        header_outer_layout.setContentsMargins(pad, pad, pad, pad)
        header_outer_layout.setSpacing(0)

        header_fill = QWidget()
        header_fill.setObjectName("PreviewColumnHeader")
        header_fill.setStyleSheet(column_header_qss("PreviewColumnHeader", title))
        self.header_fill = header_fill
        self.title_label = QLabel(display_title or title)
        self.title_label.setFont(role_font("colhead", 10, 600, tracking=0.9, caps=True))
        self.title_label.setStyleSheet(f"color: {role_color('colhead', C['header'])}; background: transparent;")
        header_layout = QHBoxLayout(header_fill)
        header_layout.setContentsMargins(10, 0, 10, 0)
        header_layout.addWidget(self.title_label)
        header_layout.addStretch(1)
        header_outer_layout.addWidget(header_fill)

        self.preview_layout = QVBoxLayout()
        self.preview_layout.setContentsMargins(0, 0, 0, 0)
        self.preview_layout.setSpacing(0)

        # self.card/self._inner : MEME structure a 2 niveaux que Column.card/
        # Column._content (voir leurs remarques respectives, et DetailPanel.
        # card/_inner, MEME principe applique la en premier) — self.card
        # porte le fond/la bordure/le rayon REELS, self._inner (en-tete +
        # apercu empile) est decoupe a sa silhouette arrondie EXACTE.
        inner_layout = QVBoxLayout()
        inner_layout.setContentsMargins(0, 0, 0, 0)
        inner_layout.setSpacing(0)
        inner_layout.addWidget(header)
        inner_layout.addLayout(self.preview_layout)
        inner_layout.addStretch(1)
        self._inner = QWidget()
        self._inner.setStyleSheet("background: transparent;")
        self._inner_effect = _RoundedCornersEffect(self._inner)
        self._inner.setGraphicsEffect(self._inner_effect)
        self._inner.setLayout(inner_layout)

        self.card = _ColumnCard()
        self.card.setObjectName("PreviewColumnCard")
        self._card_effect = _RoundedCornersEffect(self.card)
        self.card.setGraphicsEffect(self._card_effect)
        card_layout = QVBoxLayout(self.card)
        card_layout.setContentsMargins(0, 0, 0, 0)   # voir refresh_header, ajuste a l'epaisseur de bordure
        card_layout.setSpacing(0)
        card_layout.addWidget(self._inner)
        self._card_layout = card_layout

        outer_layout = QVBoxLayout(self)
        outer_layout.setContentsMargins(0, 0, 0, 0)   # voir refresh_header, ajuste au Padding
        outer_layout.setSpacing(0)
        outer_layout.addWidget(self.card)
        self._outer_layout = outer_layout

        # Icone de repli/depli de Type/Projets/Sous-projet (voir
        # PipelineBrowser._toggle_project_columns) : seulement sur la
        # colonne PERMANENTE des vignettes (image_preview_column), pas sur
        # le fantome "Logiciels". Flottante (enfant direct de `self`, HORS
        # de `self.card`) plutot que dans l'en-tete : elle se superpose au
        # coin superieur gauche du 1er bloc empile, SOUS l'en-tete (voir
        # refresh_header, qui repositionne son ancrage a chaque changement
        # de hauteur/padding d'en-tete OU de Padding de colonne).
        self.toggle_btn = None
        if on_toggle is not None:
            self.toggle_btn = IconButton(
                "dchevron_right", role_color("buttons", "#c4cacf"), C["text"], parent=self
            )
            self.toggle_btn.setCursor(Qt.ArrowCursor)
            self.toggle_btn.setFlat(True)
            self.toggle_btn.setToolTip("Replier les colonnes de set")
            # Taille/fond/bordure/police-ou-icone : voir refresh_toggle_
            # style (Colonnes > Apercu > Bouton repliement) — voir la
            # remarque de l'utilisateur, "ajouter les settings de style du
            # bouton repliement".
            self.toggle_btn.clicked.connect(on_toggle)
            self.toggle_btn.raise_()
        # Bouton voisin du repli : fait disparaitre (fondu) les colonnes de set
        # et libere leur place (voir PipelineBrowser._toggle_project_columns_
        # hidden). Meme style EXACT que toggle_btn (voir refresh_toggle_style,
        # reglages Colonnes > Apercu > Bouton repliement).
        self.hide_btn = None
        if on_hide_columns is not None:
            self.hide_btn = IconButton(
                "fade_columns", role_color("buttons", "#c4cacf"), C["text"], parent=self
            )
            self.hide_btn.setCursor(Qt.ArrowCursor)
            self.hide_btn.setFlat(True)
            self.hide_btn.setToolTip("Masquer les colonnes de set")
            self.hide_btn.clicked.connect(on_hide_columns)
            self.hide_btn.raise_()

        # Largeur PAR DEFAUT (tant que l'utilisateur n'a pas encore glisse
        # son bord, voir _user_width ci-dessus) : pour le fantome "Fichiers
        # pour X" (role 2, title="Logiciels"), elle occupe la place REELLE
        # de "Logiciels" avant que cette colonne existe pour de vrai, donc
        # suit son reglage — INCHANGE. Pour la colonne des vignettes Focus
        # (role 1, title=PREVIEW_STACK_TITLE), elle n'a RIEN a voir avec
        # "Logiciels" (une colonne potentiellement large, pensee pour des
        # noms de fichiers) : caler sa largeur dessus la rendait bien trop
        # large "de base" (largeur de l'image comprise, puisqu'elle suit
        # desormais la largeur de colonne, voir _PreviewBlock.apply_width)
        # — voir la remarque de l'utilisateur, "pourquoi de base tu fait
        # une image aussi grande!!!!!!! ... je veux ... la largeur de
        # l'image egale a la largeur de la colonne [Projets/Sous-projet]".
        # col_width("Logiciels") : largeur DEJA reglee par l'utilisateur pour
        # la colonne dont ce bloc reprend le contenu, un repere bien plus
        # sense qu'une colonne sans rapport. Pour PREVIEW_STACK_TITLE, sa
        # PROPRE largeur par defaut (voir settings_window.DEFAULT_SETTINGS.
        # item_column_width, surchargeable dans Colonnes > Focus, MEME
        # mecanisme general/surcharge que Colonnes > Type/Projets/Sous-
        # projets, resolu par apply_all_settings dans column_style_for
        # (PREVIEW_STACK_TITLE)) — plus calee sur col_width("Projets"), qui
        # n'a plus aucun rapport depuis que cette colonne a son propre
        # reglage — voir la remarque de l'utilisateur, "tu as oublie
        # l'overide des colonnes focus".
        if title == "Logiciels":
            default_width = col_width("Logiciels")
        else:
            default_width = scaled(int(column_style_for(PREVIEW_STACK_TITLE).get("item_column_width") or 180))
        self.setFixedWidth(self._user_width or default_width)
        # self ne peint plus rien lui-meme desormais (voir self.card
        # ci-dessus, EXACTEMENT le meme principe que Column/DetailPanel).
        self.setObjectName("PreviewColumn")
        self.setStyleSheet("#PreviewColumn { background: transparent; }")
        self.header.setMouseTracking(True)
        self.header.installEventFilter(self)
        # self.card couvre TOUTE la surface de self (outer_layout, marges a
        # 0) : les zones NON couvertes par un bloc empile (espacement entre
        # blocs, marge sous le dernier bloc) sont donc en realite survolees
        # via self.card, pas via self directement — sans son propre
        # setMouseTracking(True), le survol de ces zones ne generait aucun
        # MouseMove, ni sur self.card (jamais filtre de toute facon) ni sur
        # self (masque dessous) : la bordure semblait "trouee" par endroits.
        self.card.setMouseTracking(True)
        self.card.installEventFilter(self)
        self.refresh_header()
        self.refresh_colors()

    def _in_resize_zone(self, x: int) -> bool:
        """MEME convention que Column._in_resize_zone (bord DROIT) — voir
        sa docstring."""
        return self.width() - COLUMN_RESIZE_MARGIN <= x <= self.width()

    def resize_begin(self, global_x: int):
        self._resizing = True
        self._resize_start_x = global_x
        self._resize_start_width = self.width()
        _show_resize_width(self, self.width())

    def resize_update(self, global_x: int):
        delta = global_x - self._resize_start_x
        new_width = max(COLUMN_MIN_WIDTH, min(COLUMN_MAX_WIDTH, self._resize_start_width + delta))
        self._user_width = new_width
        self.setFixedWidth(new_width)
        self._relayout_blocks()
        if self._on_resize is not None:
            self._on_resize(new_width)
        _show_resize_width(self, new_width)

    def resize_end(self):
        self._resizing = False
        _hide_resize_width(self)
        # Les colonnes Focus (empilees Projets/Sous-projet) n'ont pas de
        # bouton punaise (pas de Column/dossier unique auquel s'accrocher)
        # mais doivent neanmoins s'enregistrer automatiquement — voir la
        # remarque de l'utilisateur, "les seules colonnes dont les
        # parametres sont enregistrees automatiquement sont : colonne type,
        # colonnes focus, colonne inspecteur".
        _persist_column_width(self.window(), PREVIEW_STACK_TITLE, self.width())

    def set_width_external(self, new_width: int):
        """Applique une largeur decidee AILLEURS (voir PipelineBrowser.
        _on_preview_column_resized) : les colonnes Projets/Sous-projet de
        l'apercu Focus sont des colonnes SEPAREES (voir set_preview_block)
        mais doivent rester alignees a la MEME largeur, empilees dans un
        seul conteneur vertical — glisser le bord de L'UNE d'elles doit
        donc repercuter la meme largeur sur les AUTRES, MEME MECANISME que
        resize_update mais sans geste souris propre a CETTE instance — voir
        la remarque de l'utilisateur, "deux colonnes separees, une en
        dessous de l'autre"."""
        self._user_width = new_width
        if getattr(self, "_buttons_only", False):
            return
        self.setFixedWidth(new_width)
        self._relayout_blocks()

    def _relayout_blocks(self):
        """Recalcule la largeur/hauteur de l'image de chaque _PreviewBlock
        empile pour la largeur COURANTE de cette colonne (voir _PreviewBlock.
        apply_width) — appele a CHAQUE glisser de bordure, pas seulement au
        relachement, pour un retour visuel immediat (meme principe que
        Column.resize_update/_throttled_layout) — voir la remarque de
        l'utilisateur, "la largeur des images de ces colonnes doit etre
        egale a cette largeur de colonne"."""
        self._outer_layout.activate()
        # outer_layout.activate() seul ne resout QUE la geometrie de
        # self.card (son enfant DIRECT) — self._inner, imbrique un niveau
        # plus loin (DANS self.card, voir card_layout), garde sinon la
        # taille par defaut de Qt pour un widget jamais encore affiche
        # (640x480 — voir la remarque de l'utilisateur, capture a l'appui,
        # "pourquoi de base tu fait une image aussi grande!!!!!", ce widget
        # geant 640px de large etait la cause reelle) tant qu'aucun
        # evenement resize n'a encore ete traite pour de vrai — activer
        # EXPLICITEMENT card_layout en plus le force a se mettre a jour
        # tout de suite, sans attendre un passage par la boucle d'evenements.
        self._card_layout.activate()
        content_width = self._inner.width() - 1
        for i in range(self.preview_layout.count()):
            block = self.preview_layout.itemAt(i).widget()
            if isinstance(block, _PreviewBlock):
                block.apply_width(content_width)
        # La hauteur de chaque bloc peut changer avec sa largeur (le Ratio
        # deduit la hauteur de l'image de la largeur, voir _PreviewBlock.
        # apply_width) : la hauteur totale de la colonne doit suivre en
        # direct pendant le glisser, pas seulement au relachement — voir
        # _fit_height_to_content.
        self._fit_height_to_content()

    def eventFilter(self, obj, event):
        """MEME mecanique que Column.eventFilter (voir sa docstring/
        remarque de tete) : installe sur self.header ET sur les barres
        pleine-largeur du _PreviewBlock de cette colonne (voir
        set_preview_block) — sans cela, ces widgets ENFANTS
        interceptent l'evenement souris AVANT que self ne le voie, rendant
        la bordure de redimensionnement inaccessible des que le curseur
        survole un bloc."""
        etype = event.type()
        if etype == QEvent.MouseMove:
            if self._resizing:
                self.resize_update(event.globalPosition().toPoint().x())
                return True
            local_x = obj.mapTo(self, event.position().toPoint()).x()
            obj.setCursor(Qt.SizeHorCursor if self._in_resize_zone(local_x) else Qt.ArrowCursor)
        elif etype == QEvent.MouseButtonPress and event.button() == Qt.LeftButton:
            local_x = obj.mapTo(self, event.position().toPoint()).x()
            if self._in_resize_zone(local_x):
                self.resize_begin(event.globalPosition().toPoint().x())
                return True
        elif etype == QEvent.MouseButtonRelease and self._resizing:
            self.resize_end()
            return True
        elif etype == QEvent.Leave and not self._resizing:
            obj.unsetCursor()
        return False

    def mouseMoveEvent(self, event):
        if self._resizing:
            self.resize_update(event.globalPosition().toPoint().x())
            return
        x = int(event.position().x())
        self.setCursor(Qt.SizeHorCursor if self._in_resize_zone(x) else Qt.ArrowCursor)
        super().mouseMoveEvent(event)

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton and self._in_resize_zone(int(event.position().x())):
            self.resize_begin(event.globalPosition().toPoint().x())
            return
        super().mousePressEvent(event)

    def mouseReleaseEvent(self, event):
        if self._resizing:
            self.resize_end()
            return
        super().mouseReleaseEvent(event)

    def _suppress_left(self) -> bool:
        """Voir _column_suppress_left (module-level, partagee avec Column)."""
        return _column_suppress_left(self, self.column_title)

    def refresh_header(self):
        """Reapplique hauteur/padding de l'en-tete + bordure/padding du
        cadre — MEME logique que Column.refresh_header (voir sa docstring).
        Repositionne aussi l'icone de repli/depli, dont l'ancrage depend de
        la hauteur d'en-tete ET du Padding (voir _card_layout/outer_layout
        ci-dessous, INCLUS dans son decalage)."""
        s = column_style_for(self.column_title)
        self.header.setVisible(bool(s.get("header_visible", True)))
        height = int(s.get("header_height", ui_state.HEADER_HEIGHT))
        padding = int(s.get("header_padding", ui_state.HEADER_PADDING))
        self.header.setFixedHeight(scaled(height))
        pad = scaled(padding, 0)
        self.header.layout().setContentsMargins(pad, pad, pad, pad)
        # Police/gras/couleur/taille du titre (voir Column.refresh_header,
        # MEME logique/MEMES cles — bug corrige au passage, voir la
        # remarque de l'utilisateur, "le titre dans l'entete ne fonctionne
        # pas dans les settings") : cette colonne fantome N'APPLIQUAIT
        # JAMAIS ces surcharges (header_font_color/family/bold/italic/
        # taille), malgre son propre onglet de surcharge Colonnes > Focus.
        title_weight = 700 if s.get("header_font_bold", True) else 500
        title_size = int(s.get("header_font_size", 10))
        title_italic = bool(s.get("header_font_italic", False))
        title_smoothing = (
            s.get("header_font_antialias_override", "current")
            if s.get("header_font_antialias_override_enabled") else "current")
        title_family = _resolve_font_family(
            (s.get("header_font_family") or "").strip(), title_size, title_weight, fallback_role="colhead")
        self.title_label.setFont(font(
            title_size, title_weight, tracking=0.9, caps=True, family=title_family,
            smoothing=title_smoothing, italic=title_italic))
        self.title_label.setStyleSheet(
            f"color: {resolve_color_ref(s.get('header_font_color', '#9aa1a7'))}; background: transparent;")
        # PAS de stylesheet explicite sur self.header : transparent par
        # defaut, la marge du Padding d'entete revele donc deja le fond de
        # self.card (column_bg_color, voir refresh_colors/_paint_bordered_
        # rect) — UNE SEULE couleur de fond pour toute la colonne (voir
        # PLUS de reglage "Zone titre > Fond" separe, source de confusion —
        # _PreviewBlock utilise desormais cette MEME couleur) — voir la
        # remarque de l'utilisateur, "voici la couleur a appliquer sur les
        # zones avec des croix".

        border_thickness = max(0, int(s.get("column_border_thickness", 1)))
        enabled = s.get("column_border_enabled") or {}
        suppress_left = self._suppress_left()

        def reserve(side_enabled: bool) -> int:
            return border_thickness if side_enabled else 0

        self._card_layout.setContentsMargins(
            scaled(reserve(bool(enabled.get("left", True)) and not suppress_left), 0),
            scaled(reserve(bool(enabled.get("top", True))), 0),
            scaled(reserve(bool(enabled.get("right", True))), 0),
            scaled(reserve(bool(enabled.get("bottom", True))), 0),
        )
        col_pad = dict(column_padding_for(self.column_title))
        if suppress_left:
            col_pad["left"] = 0
        self._outer_layout.setContentsMargins(
            scaled(col_pad["left"], 0), scaled(col_pad["top"], 0),
            scaled(col_pad["right"], 0), scaled(col_pad["bottom"], 0),
        )
        self._update_card_mask()
        if self.toggle_btn is not None:
            # Position EXPLICITE (X/Y depuis le coin superieur GAUCHE de la
            # colonne, voir Colonnes > Apercu > Bouton repliement) — voir
            # la remarque de l'utilisateur, "supprime le padding mais
            # ajoute un parametre de position par rapport au coin
            # superieur gauche de la colonne en x et en y" (remplace
            # l'ancien ancrage automatique sous l'en-tete, fige a 8px).
            pos_x = scaled(int(s.get("preview_toggle_x", 8)), 0)
            pos_y = scaled(int(s.get("preview_toggle_y", 34)), 0)
            self.toggle_btn.move(self.card.x() + pos_x, self.card.y() + pos_y)
            self.toggle_btn.raise_()
            if self.hide_btn is not None:
                self._place_hide_btn()
                self.hide_btn.raise_()
        if self._fit_height:
            # Reste coherent si l'entete/le cadre changent (ex. echelle
            # d'interface) SANS reconstruction complete de la colonne — voir
            # _fit_height_to_content, meme raison.
            self._fit_height_to_content()

    def _update_card_mask(self):
        """MEME mecanisme que Column._update_card_mask (voir sa docstring)."""
        self._outer_layout.activate()
        radius = _radius_dict(self.card._radius)
        self._card_effect.setRadius(radius)
        self._card_effect.setEnabled(self.card._thickness <= 0)
        inner_radius = _radius_shrink(radius, self.card._thickness + 1)
        self._inner_effect.setRadius(_radius_dict(inner_radius))
        self._inner_effect.setEnabled(self.card._thickness > 0)

    def refresh_colors(self):
        self.header_fill.setStyleSheet(column_header_qss("PreviewColumnHeader", self.column_title))
        # PAS de reapplication de self.title_label ici — voir Column.
        # refresh_colors, MEME correctif/MEME raison (refresh_header,
        # toujours appele AVANT, gere deja ce style correctement).
        frame = column_frame_style(self.column_title, self._suppress_left())
        scaled_radius = {k: scaled(v, 0) for k, v in frame["radius"].items()}
        self.card.setFrameStyle(
            frame["bg"], scaled_radius, frame["enabled"], frame["colors"], scaled(frame["thickness"], 0))
        # Meme couleur que le CADRE (frame["bg"], "Couleur de fond" de
        # Colonnes > Focus > Colonnes) sur self LUI-MEME (pas seulement
        # self.card) : sans ca, la marge de Padding autour de la carte
        # (voir refresh_header/_outer_layout) revelait le fond de la
        # FENETRE au lieu de cette couleur — voir la remarque de
        # l'utilisateur, "la couleur de fond doit aussi controler les
        # zones avec la croix rouge sur le screenshot et la zone sous
        # l'entete".
        self.setStyleSheet(f"#PreviewColumn {{ background: {frame['bg']}; }}")
        self._update_card_mask()
        if self.toggle_btn is not None:
            self.toggle_btn.set_colors(role_color("buttons", "#c4cacf"), C["text"])
            if self.hide_btn is not None:
                self.hide_btn.set_colors(role_color("buttons", "#c4cacf"), C["text"])
            self.refresh_toggle_style()

    def refresh_toggle_style(self):
        """Colonnes > Apercu > Bouton repliement (taille/fond/bordure/
        rayon) — voir la remarque de l'utilisateur, "ajouter les settings
        de style du bouton repliement : taille bouton, hauteur, largeur
        ... border ... couleur fond". Remplace l'ancien QSS fixe
        (rgba(15,17,20,150), rayon 4px en dur, 22x22 fige). Toujours
        l'icone dessinee a la main (voir la remarque de l'utilisateur,
        "supprime police ou icone ... supprime image personnalisee") — la
        position (voir refresh_header) est, elle, EXPLICITE (X/Y depuis le
        coin superieur gauche de la colonne), plus un padding implicite."""
        if self.toggle_btn is None:
            return
        s = column_style_for(self.column_title)
        w = scaled(int(s.get("preview_toggle_width", 22)))
        h = scaled(int(s.get("preview_toggle_height", 22)))
        self.toggle_btn.setFixedSize(max(1, w), max(1, h))
        radius = _radius_dict(scaled(int(s.get("preview_toggle_radius", 4)), 0))
        enabled = _coerce_side_enabled(s.get("preview_toggle_border_enabled", False))
        colors = {k: resolve_color_ref(v) for k, v in (s.get("preview_toggle_border") or {}).items()}
        thickness = scaled(int(s.get("preview_toggle_border_thickness", 1)), 0)
        bg = resolve_color_ref(s.get("preview_toggle_bg_color", "#960f1114"))
        self.toggle_btn.set_frame_style(bg, enabled, colors, thickness, radius)
        if self.hide_btn is not None:
            self.hide_btn.setFixedSize(max(1, w), max(1, h))
            self.hide_btn.set_frame_style(bg, enabled, colors, thickness, radius)
            self._place_hide_btn()

    def _place_hide_btn(self):
        """A droite du bouton de repliement."""
        if self.hide_btn is None or self.toggle_btn is None:
            return
        self.hide_btn.move(self.toggle_btn.x() + self.toggle_btn.width() + scaled(4, 0), self.toggle_btn.y())

    def set_toggle_state(self, collapsed: bool):
        """Met a jour l'icone (voir __init__, `on_toggle`) apres un repli/
        depli des colonnes de set declenche depuis ailleurs (par exemple
        automatiquement, voir PipelineBrowser._sync_collapse_state) — sans
        effet si cette instance n'a pas d'icone (fantome "Logiciels")."""
        if self.toggle_btn is None:
            return
        self.toggle_btn.set_kind("dchevron_left" if collapsed else "dchevron_right")
        self.toggle_btn.setToolTip(
            "Deplier les colonnes de set" if collapsed else "Replier les colonnes de set"
        )

    def set_hide_state(self, hidden: bool):
        """Icone/infobulle du bouton « masquer les colonnes » selon l'etat."""
        if self.hide_btn is None:
            return
        self.hide_btn.set_kind("show_columns" if hidden else "fade_columns")
        self.hide_btn.setToolTip("Afficher les colonnes de set" if hidden else "Masquer les colonnes de set")

    def _set_toggle_usable(self, usable: bool):
        if self.toggle_btn is None:
            return
        self.toggle_btn.setEnabled(usable)
        self.toggle_btn.setGraphicsEffect(None if usable else _dim_effect(self.toggle_btn))

    def set_buttons_only(self, on: bool):
        """Mode « colonnes masquees » : la carte disparait et la colonne se
        reduit a l'emprise des deux boutons (leur place ne bouge pas) ; `on=False`
        restaure tout. Instantane : le fondu est joue par PipelineBrowser."""
        if on == getattr(self, "_buttons_only", False):
            return
        buttons = [b for b in (self.toggle_btn, self.hide_btn) if b is not None]
        if on:
            self._buttons_only = True
            self._place_hide_btn()
            self._saved_limits = (self.minimumWidth(), self.maximumWidth(), self.minimumHeight(), self.maximumHeight())
            self.card.hide()
            right = max((b.geometry().right() for b in buttons), default=0) + scaled(10, 0)
            bottom = max((b.geometry().bottom() for b in buttons), default=0) + scaled(8, 0)
            self.setFixedSize(right, bottom)
            # Colonnes masquees : le bouton de repliement n'a plus d'objet, il reste
            # visible mais inutilisable (et attenue).
            self._set_toggle_usable(False)
        else:
            self._buttons_only = False
            self._place_hide_btn()
            min_w, max_w, min_h, max_h = getattr(self, "_saved_limits", (0, 16777215, 0, 16777215))
            self.setMinimumSize(min_w, min_h)
            self.setMaximumSize(max_w, max_h)
            self.card.show()
            self._outer_layout.activate()
            self._set_toggle_usable(True)
        for b in buttons:
            b.raise_()

    def _clear_preview_layout(self):
        while self.preview_layout.count():
            item = self.preview_layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.hide()
                widget.setParent(None)
                widget.deleteLater()

    def _content_width(self) -> int:
        # self._inner.width() (PAS self.width()) : le Padding/la bordure de
        # self.card (voir refresh_header) retrecissent desormais le
        # contenu reel sous self — utiliser self.width() ici carrerait le
        # contenu sur la largeur TOTALE de la colonne fantome, deborderait
        # du cadre des que Padding/Bordure sont actifs.
        self._outer_layout.activate()
        # outer_layout.activate() seul ne resout QUE la geometrie de
        # self.card — self._inner (imbrique un niveau plus loin, dans
        # card_layout) garde sinon la taille par defaut de Qt pour un
        # widget jamais encore affiche (640x480, voir _relayout_blocks,
        # MEME correctif/MEME raison) tant qu'aucun resizeEvent reel n'a
        # encore ete traite — d'ou des images DEMESUREES a la toute
        # premiere construction (avant le moindre glisser de bordure) —
        # voir la remarque de l'utilisateur, capture a l'appui, "pourquoi
        # de base tu fait une image aussi grande!!!!!".
        self._card_layout.activate()
        return self._inner.width() - 1

    def set_preview_block(self, title: str, pixmap: QPixmap, path: Path, open_status, source_column: "Column"):
        """Peuple cette colonne fantome avec UN SEUL niveau d'apercu (voir
        _PreviewBlock) — cette colonne EST "Projets" ou "Sous-projet" a
        elle seule (self.column_title, passe a la construction, voir
        PipelineBrowser.update_preview_stack), avec sa PROPRE entete
        REELLE (self.header, deja construite dans __init__ a partir de ce
        meme titre) — DEUX colonnes fantomes SEPAREES (chacune son propre
        cadre/bordure/entete), empilees VERTICALEMENT dans un conteneur
        commun (voir PipelineBrowser._preview_stack_wrapper), PAS cote a
        cote et PAS fusionnees en une seule — voir la remarque de
        l'utilisateur, "non, tu as merger les deux colonnes en une seule,
        ce que je veux c'est deux colonnes separees, une en dessous de
        l'autre !". `source_column` (voir _PreviewBlock._rename/
        update_preview_stack) : la VRAIE colonne de navigation dont ce
        bloc reprend la selection courante."""
        self._clear_preview_layout()
        block = _PreviewBlock(title, pixmap, self._content_width(), path, open_status, source_column)
        # Sans ceci, la bordure de redimensionnement (voir resize_begin/
        # _in_resize_zone) est inaccessible a la souris des qu'elle
        # survole ce bloc (voir install_resize_filter).
        block.install_resize_filter(self)
        self.preview_layout.addWidget(block)
        # Ce bloc est, par defaut, empile PAR-DESSUS l'icone flottante
        # (creee avant lui, voir __init__) : la remonter au premier plan a
        # chaque reconstruction, sinon elle disparait derriere le bloc des
        # que set_preview_block est rappelee.
        if self.toggle_btn is not None:
            self.toggle_btn.raise_()
        self._fit_height_to_content()

    def _fit_height_to_content(self):
        """Hauteur reduite au CONTENU reel (entete + blocs empiles), au
        lieu de s'etirer jusqu'en bas de la fenetre comme les vraies
        colonnes (qui, elles, ont une liste a faire defiler jusqu'au bout
        de l'espace disponible) — voir la remarque de l'utilisateur,
        "Reduire les colonnes en hauteur". self.header/chaque bloc empile
        ont deja leur PROPRE hauteur FIXEE explicitement (setFixedHeight) :
        pas besoin d'activer quoi que ce soit pour les lire, contrairement
        a une largeur (voir _content_width, MEME distinction que le
        correctif du bug 640x480)."""
        if getattr(self, "_buttons_only", False):
            return
        content_height = self.header.height() + sum(
            self.preview_layout.itemAt(i).widget().height()
            for i in range(self.preview_layout.count())
        )
        card_margins = self._card_layout.contentsMargins()
        outer_margins = self._outer_layout.contentsMargins()
        self.setFixedHeight(
            content_height + card_margins.top() + card_margins.bottom()
            + outer_margins.top() + outer_margins.bottom()
        )

def read_text_preview(path: Path) -> str | None:
    """Debut du contenu de `path` (voir TEXT_PREVIEW_EXTENSIONS), pour
    affichage brut dans l'inspecteur (voir DetailPanel.show_path). Lit au
    plus TEXT_PREVIEW_MAX_BYTES sur le disque (fichier potentiellement
    enorme, pas besoin de plus pour un apercu), puis tronque a
    TEXT_PREVIEW_MAX_LINES. None si illisible ou visiblement binaire (octet
    nul dans les premiers kilo-octets)."""
    try:
        with open(path, "rb") as f:
            raw = f.read(TEXT_PREVIEW_MAX_BYTES)
    except OSError:
        return None
    if b"\x00" in raw:
        return None
    truncated_bytes = len(raw) >= TEXT_PREVIEW_MAX_BYTES
    text = raw.decode("utf-8", errors="replace")
    lines = text.splitlines()
    truncated = truncated_bytes or len(lines) > TEXT_PREVIEW_MAX_LINES
    lines = lines[:TEXT_PREVIEW_MAX_LINES]
    if truncated:
        lines.append("…")
    return "\n".join(lines)

def pur_embedded_image_ranges(path: Path, mtime: float | None = None) -> list[tuple[int, int, str]]:
    """Indexe les JPEG/PNG embarques d'un .pur sans les decoder ni les copier."""
    key = str(path)
    if mtime is None:
        try:
            mtime = path.stat().st_mtime
        except OSError:
            return []
    cached = _PUR_IMAGE_INDEX_CACHE.get(key)
    if cached is not None and cached[0] == mtime:
        return cached[1]
    ranges: list[tuple[int, int, str]] = []
    jpeg_signature = b"\xff\xd8\xff"
    png_signature = b"\x89PNG\r\n\x1a\n"
    try:
        with path.open("rb") as stream:
            if path.stat().st_size == 0:
                return []
            with mmap.mmap(stream.fileno(), 0, access=mmap.ACCESS_READ) as data:
                # PureRef 2.x a change de conteneur : les marqueurs JPEG
                # apparaissent aussi dans des donnees internes et ne
                # delimitent pas des images autonomes. Le premier JPEG de
                # l'en-tete est la vignette valide de la planche.
                header = data[4:96].decode("utf-16-be", errors="ignore")
                if re.search(r"\b2\.\d+", header):
                    start = data.find(jpeg_signature)
                    if start >= 0:
                        eoi = data.find(b"\xff\xd9", start + 3)
                        if eoi >= 0:
                            image = QImage.fromData(data[start:eoi + 2])
                            if not image.isNull():
                                ranges.append((start, eoi + 2, "JPEG"))
                    _bounded_cache_set(_PUR_IMAGE_INDEX_CACHE, key, (mtime, ranges), max_entries=24)
                    return ranges
                position = 0
                size = len(data)
                while position < size and len(ranges) < PUR_MAX_EMBEDDED_IMAGES:
                    jpeg_at = data.find(jpeg_signature, position)
                    png_at = data.find(png_signature, position)
                    candidates = [(offset, fmt) for offset, fmt in ((jpeg_at, "JPEG"), (png_at, "PNG"))
                                  if offset >= 0]
                    if not candidates:
                        break
                    start, fmt = min(candidates)
                    if fmt == "JPEG":
                        eoi = data.find(b"\xff\xd9", start + 3)
                        if eoi < 0:
                            position = start + len(jpeg_signature)
                            continue
                        end = eoi + 2
                    else:
                        # Parcourt la structure PNG jusqu'au chunk IEND pour
                        # ne pas confondre son contenu avec d'autres images.
                        cursor = start + len(png_signature)
                        end = -1
                        while cursor + 12 <= size:
                            chunk_size = int.from_bytes(data[cursor:cursor + 4], "big")
                            chunk_type = data[cursor + 4:cursor + 8]
                            next_chunk = cursor + 12 + chunk_size
                            if next_chunk > size:
                                break
                            if chunk_type == b"IEND":
                                end = next_chunk
                                break
                            cursor = next_chunk
                        if end < 0:
                            position = start + len(png_signature)
                            continue
                    ranges.append((start, end, fmt))
                    position = end
    except (OSError, ValueError):
        return []
    _bounded_cache_set(_PUR_IMAGE_INDEX_CACHE, key, (mtime, ranges), max_entries=24)
    return ranges

def pur_file_major_version(path: Path) -> int | None:
    """Retourne la version du conteneur PureRef depuis son en-tete."""
    try:
        with path.open("rb") as stream:
            header = stream.read(96)
        text = header[4:].decode("utf-16-be", errors="ignore")
        match = re.search(r"^\s*(\d+)\.\d+", text)
        return int(match.group(1)) if match else None
    except OSError:
        return None

class _PureRefExportSignals(QObject):
    progress = Signal(str, float, object)
    finished = Signal(str, float, object, str)

class _PureRefExportTask(QRunnable):
    """Exporte les images d'une planche PureRef 2.x via son CLI officiel."""
    def __init__(self, path: Path, mtime: float):
        super().__init__()
        self.path = path
        self.mtime = mtime
        self.signals = _PureRefExportSignals()

    @staticmethod
    def _running_pids() -> set[int]:
        try:
            result = subprocess.run(
                ["tasklist", "/FI", "IMAGENAME eq PureRef.exe", "/FO", "CSV", "/NH"],
                capture_output=True, text=True, timeout=5, check=False,
            )
            return {int(value) for value in re.findall(r'"PureRef.exe","(\d+)"', result.stdout)}
        except (OSError, subprocess.SubprocessError):
            return set()

    @staticmethod
    def _executable() -> str | None:
        candidates = [
            shutil.which("PureRef.exe"),
            str(Path(os.environ.get("ProgramFiles", r"C:\Program Files")) / "PureRef" / "PureRef.exe"),
            str(Path(os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)")) / "PureRef" / "PureRef.exe"),
            str(Path(os.environ.get("LOCALAPPDATA", "")) / "Programs" / "PureRef" / "PureRef.exe"),
        ]
        return next((candidate for candidate in candidates if candidate and Path(candidate).is_file()), None)

    def run(self):
        exported: list[str] = []
        error = ""
        launched_pid: int | None = None
        try:
            digest = hashlib.sha256(f"{self.path}|{self.mtime}".encode("utf-8", errors="replace")).hexdigest()
            output_dir = FILE_IMAGE_DISK_CACHE_DIR / "pureref_images" / digest
            cached_files = sorted(output_dir.glob("*.png"), key=lambda item: item.name.casefold()) if output_dir.is_dir() else []
            exported = [str(item) for item in cached_files if item.is_file() and item.stat().st_size > 0]
            complete_marker = output_dir / ".export_complete"
            if exported and complete_marker.is_file():
                self.signals.finished.emit(str(self.path), self.mtime, exported, "")
                return
            executable = self._executable()
            if executable is None:
                raise RuntimeError("PureRef n'est pas installé à un emplacement détectable.")
            before = self._running_pids()
            if before:
                raise RuntimeError("Ferme PureRef pour permettre l'export sans modifier sa scène ouverte.")

            output_dir.mkdir(parents=True, exist_ok=True)
            for old_file in output_dir.iterdir():
                if old_file.is_file():
                    old_file.unlink(missing_ok=True)
            normalized_path = self.path.resolve().as_posix()
            normalized_output = output_dir.resolve().as_posix()
            command = [
                executable,
                "-c", f"load;{normalized_path}",
                "-c", f"exportImages;{normalized_output};false;%2",
            ]
            startup_info = None
            if os.name == "nt":
                startup_info = subprocess.STARTUPINFO()
                startup_info.dwFlags |= subprocess.STARTF_USESHOWWINDOW
                startup_info.wShowWindow = 0
            process = subprocess.Popen(command, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                                       stderr=subprocess.DEVNULL, close_fds=True, startupinfo=startup_info)
            launched_pid = process.pid
            deadline = time.monotonic() + 600
            last_signature = None
            stable_since = None
            last_progress_count = 0
            while time.monotonic() < deadline:
                files = sorted(output_dir.glob("*.png"), key=lambda item: item.name.casefold())
                file_stats = [(item, item.stat()) for item in files if item.is_file()]
                signature = tuple((item.name, stat.st_size) for item, stat in file_stats)
                stable_files = [str(item) for item, stat in file_stats
                                if stat.st_size > 0 and time.time() - stat.st_mtime >= 0.75]
                if len(stable_files) > last_progress_count:
                    last_progress_count = len(stable_files)
                    self.signals.progress.emit(str(self.path), self.mtime, stable_files)
                if signature and signature == last_signature:
                    if stable_since is None:
                        stable_since = time.monotonic()
                    elif time.monotonic() - stable_since >= 3.0:
                        exported = [str(item) for item in files if item.is_file() and item.stat().st_size > 0]
                        complete_marker.touch()
                        break
                else:
                    last_signature = signature
                    stable_since = None
                time.sleep(0.25)
            if not exported:
                raise RuntimeError("PureRef n'a retourné aucune image (délai dépassé ou scène illisible).")
        except Exception as exc:
            error = str(exc)
        finally:
            # Le CLI PureRef reste parfois ouvert après avoir terminé ses
            # commandes. Ne fermer que le PID retourné par notre Popen.
            if launched_pid is not None and launched_pid in self._running_pids():
                try:
                    subprocess.run(["taskkill", "/PID", str(launched_pid), "/T", "/F"],
                                   capture_output=True, timeout=5, check=False)
                except (OSError, subprocess.SubprocessError):
                    pass
        self.signals.finished.emit(str(self.path), self.mtime, exported, error)

_PUR_EXPORT_POOL = QThreadPool()

_PUR_EXPORT_POOL.setMaxThreadCount(1)

def read_pur_embedded_image(path: Path, image_range: tuple[int, int, str]) -> QImage | None:
    """Decode uniquement l'image PureRef selectionnee, pas les autres."""
    start, end, fmt = image_range
    try:
        with path.open("rb") as stream:
            stream.seek(start)
            raw = stream.read(end - start)
    except OSError:
        return None
    image = QImage.fromData(raw)
    if image.isNull():
        return None
    if max(image.width(), image.height()) > 1600:
        image = image.scaled(1600, 1600, Qt.KeepAspectRatio, Qt.SmoothTransformation)
    return image

def read_pur_exported_image(path: Path) -> QImage | None:
    """Charge une image exportee sans decoder sa pleine resolution en memoire."""
    reader = QImageReader(str(path))
    reader.setAutoTransform(True)
    size = reader.size()
    if size.isValid() and max(size.width(), size.height()) > 1600:
        scale = 1600 / max(size.width(), size.height())
        reader.setScaledSize(QSize(max(1, round(size.width() * scale)),
                                   max(1, round(size.height() * scale))))
    image = reader.read()
    return None if image.isNull() else image

class IconButton(QPushButton):
    """Bouton dessine au QPainter (─ □ × pour TitleBar, engrenage pour les
    Parametres) plutot qu'avec un glyphe de police : quel que soit le
    symbole choisi (─, □, ×, ⚙...), toute police testee (mono_family(),
    sans_family(), Segoe UI Symbol) le rendait soit absent soit minuscule/
    flou a ces tailles de 11-14px (verifie pixel par pixel a chaque
    tentative) — un souci de metriques internes a la police, pas de
    contenu. Dessiner l'icone soi-meme evite ce souci une fois pour
    toutes, quelle que soit la machine/les polices installees."""

    def __init__(self, kind: str, color: str, hover_color: str, parent=None):
        super().__init__(parent)
        self._kind = kind
        self._color = color
        self._hover_color = hover_color
        # Cadre CUSTOM (voir set_frame_style) — None par defaut :
        # comportement INCHANGE (fond QSS herite) pour TOUS les usages
        # existants (TitleBar min/max/close, engrenage Parametres). Utilise
        # UNIQUEMENT par PreviewColumn.toggle_btn (voir Colonnes > Apercu >
        # Bouton repliement) — voir la remarque de l'utilisateur, "ajouter
        # les settings de style du bouton repliement : taille bouton ...
        # border ... couleur fond".
        self._frame = None   # (bg, enabled, colors, thickness, radius) | None

    def set_colors(self, color: str, hover_color: str):
        self._color = color
        self._hover_color = hover_color
        self.update()

    def set_kind(self, kind: str):
        self._kind = kind
        self.update()

    def set_frame_style(self, bg: str | None, enabled: dict, colors: dict, thickness: int, radius: dict):
        """Cadre peint a la main (_paint_bordered_rect), REMPLACE le fond
        QSS herite (voir paintEvent, super().paintEvent() saute des qu'un
        cadre custom est actif) — voir Colonnes > Apercu > Bouton
        repliement > Couleur fond/Bordure."""
        self._frame = (bg, enabled, colors, thickness, radius)
        self.update()

    def paintEvent(self, event):
        if self._frame is not None:
            painter = QPainter(self)
            bg, enabled, colors, thickness, radius = self._frame
            painter.setRenderHint(QPainter.Antialiasing, _radius_any(radius))
            _paint_bordered_rect(painter, self.rect(), radius, enabled, thickness, colors, bg)
        else:
            super().paintEvent(event)
            painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing, True)
        rect = self.rect()
        custom_pix = self._custom_icon_pixmap(rect)
        if custom_pix is not None:
            target = QRect(0, 0, custom_pix.width(), custom_pix.height())
            target.moveCenter(rect.center())
            painter.drawPixmap(target, custom_pix)
            painter.end()
            return
        color = self._hover_color if self.underMouse() else self._color
        pen = QPen(QColor(color))
        pen.setWidthF(1.3)
        pen.setCapStyle(Qt.FlatCap)
        painter.setPen(pen)
        cx, cy = rect.center().x(), rect.center().y()
        s = min(rect.width(), rect.height()) * 0.16
        if self._kind == "min":
            painter.drawLine(QPointF(cx - s, cy), QPointF(cx + s, cy))
        elif self._kind == "max":
            painter.drawRect(QRectF(cx - s, cy - s, 2 * s, 2 * s))
        elif self._kind == "close":
            painter.drawLine(QPointF(cx - s, cy - s), QPointF(cx + s, cy + s))
            painter.drawLine(QPointF(cx - s, cy + s), QPointF(cx + s, cy - s))
        elif self._kind == "gear":
            r = s * 1.7
            painter.drawEllipse(QPointF(cx, cy), r * 0.5, r * 0.5)
            for i in range(8):
                ang = math.radians(i * (360 / 8))
                x1 = cx + math.cos(ang) * r * 0.7
                y1 = cy + math.sin(ang) * r * 0.7
                x2 = cx + math.cos(ang) * r
                y2 = cy + math.sin(ang) * r
                painter.drawLine(QPointF(x1, y1), QPointF(x2, y2))
        elif self._kind in ("fade_columns", "show_columns"):
            # Trois colonnes verticales : opacite decroissante ("fade_columns",
            # action = faire disparaitre) ou pleines ("show_columns", action =
            # les ramener).
            bar_w, bar_h, gap = s * 0.7, s * 2.2, s * 0.55
            for i in range(3):
                alpha = 1.0 if self._kind == "show_columns" else (1.0, 0.6, 0.25)[i]
                bar_color = QColor(color)
                bar_color.setAlphaF(alpha)
                painter.setPen(Qt.NoPen)
                painter.setBrush(bar_color)
                x = cx + (i - 1) * (bar_w + gap) - bar_w / 2
                painter.drawRect(QRectF(x, cy - bar_h / 2, bar_w, bar_h))
        elif self._kind in ("dchevron_left", "dchevron_right"):
            # Repli/depli de Type/Projets/Sous-projet (voir
            # Column.set_collapsed) : double chevron ("«"/"»") pointant vers
            # la gauche ("replier") ou la droite ("deplier") — deux chevrons
            # simples, decales horizontalement.
            sign = -1 if self._kind == "dchevron_left" else 1
            ss = s * 0.95
            for offset in (-ss * 0.85, ss * 0.85):
                ox = cx + offset
                painter.drawLine(QPointF(ox + sign * ss * 0.5, cy - ss), QPointF(ox - sign * ss * 0.5, cy))
                painter.drawLine(QPointF(ox - sign * ss * 0.5, cy), QPointF(ox + sign * ss * 0.5, cy + ss))
        painter.end()

    def _custom_icon_pixmap(self, rect: QRect) -> QPixmap | None:
        """Icone perso (voir Settings > ICONES > General) pour ce bouton,
        si l'utilisateur en a choisi une — sinon None (le glyphe peint ci-
        dessus reste le rendu par defaut). "gear" (bouton Parametres) suit
        TOUJOURS sa propre icone si elle existe ; les chevrons de repli
        (dchevron_left/right) ne la remplacent que si COLLAPSE_TOGGLE_MODE
        vaut "icone" (voir Settings > Colonnes > Focus > Bouton repliement >
        "Icone")."""
        size = int(min(rect.width(), rect.height()) * 0.9)
        if size <= 0:
            return None
        if self._kind == "gear":
            return custom_ui_icon_pixmap(UI_ICON_SETTINGS_GEAR, size)
        if self._kind in ("dchevron_left", "dchevron_right") and ui_state.COLLAPSE_TOGGLE_MODE == "icone":
            return custom_ui_icon_pixmap(UI_ICON_COLLAPSE_TOGGLE, size)
        return None
