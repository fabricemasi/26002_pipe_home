"""Planche (FocusGallery) : grille de vignettes, navigation, sélection, attributs au clavier et à la souris.

Découpé de focus.py (2026-10-28) ; carte : docs/agents/fm_visionneuse.md."""
import math
import os
import stat as _stat
import time
from pathlib import Path

from PySide6.QtCore import (
    QEasingCurve, QElapsedTimer, QEvent, QPoint, QPointF, QRect, QRectF, QSize, Qt, QThreadPool, QTimer,
    QVariantAnimation, Signal,
)
from PySide6.QtGui import QColor, QCursor, QFont, QFontMetrics, QImage, QPainter, QPixmap, QRegion
from PySide6.QtWidgets import (
    QAbstractItemView, QApplication, QGraphicsOpacityEffect, QListView, QListWidget, QListWidgetItem, QWidget,
)

from browser_core import _fine_timer, _snappy_gil, human_size
from config import IMAGE_EXTENSIONS
import previews

from .loader import display_name
from .film_cache import (
    PROXY_MARGIN, _CELLS, _CELLS_MAX, _MARKED, _PROXIES, _ProxySignals, _ProxyTask, _drop_proxy, _film_look_signature,
    _store_proxy,
)
from .film_look import _FILM_SIDES, _film_inner, _film_look, _paint_film_box
from .filmstrip import ProxySourceTip
from .attributes_ui import KeywordsWindow, filter_colors
from . import gallery_paint
from .gallery_paint import _GalleryDelegate, _gallery_look, attr_hit


class FocusGallery(QListWidget):
    """Planche de TOUS les fichiers a apercu (images, 3D, PSD, plans, videos...) du dossier de l'objet en focus (bouton voisin de « masquer
    les colonnes », voir PreviewColumn.gallery_btn) : grille qui remplit la zone des colonnes,
    image en cours entouree. Clic (ou Entree) sur une vignette : `chosen(Path)` ; Echap ou G :
    `closed`. Vignettes = apercus du pipeline (meme decodage asynchrone que les colonnes) :
    une case vide se remplit des que son apercu est pret (l'inspecteur repeint toutes les vues
    a chaque apercu termine). Chaque vignette est gardee ici a la taille de sa case, pour ne pas
    dependre des caches d'apercus, bornes.

    Ctrl+molette = taille des vignettes (retenue pour la session, `tile_size`) ; en continuant a
    zoomer une fois au maximum, la vignette sous le curseur s'ouvre (`zoomed_into(Path)`) : zoom
    « semantique », pendant de Ctrl+molette arriere sur l'image qui ouvre la planche. Ouverture :
    les cases apparaissent en vague depuis l'image en cours (`start_ripple`).

    TABLEAU : une cellule par fichier (image + nom + type et poids), habille comme les tableaux
    des reglages (`_gallery_look`), CALE SUR LES 4 BORDS de sa zone (`_plan`, `_layout_table`) :
    cellules agrandies pour que les colonnes remplissent la largeur et les lignes visibles la
    hauteur, en restant le plus carrees possible (contrainte n° 1). Les lignes suivantes sont sous
    la zone et defilent ligne par ligne. Trop peu de fichiers : cellules carrees, tableau centre."""

    chosen = Signal(object)
    closed = Signal()
    zoomed_into = Signal(object)
    outside_clicked = Signal()               # clic a cote du tableau (marges de la planche) : retour aux colonnes

    tile_size = 200          # taille des vignettes, gardee d'une ouverture a l'autre
    TILE_MIN = 110
    TILE_MAX = 420
    LABEL_GAP = 6            # px entre l'image et son nom
    RIPPLE_STEP_MS = 34      # retard par case d'eloignement
    RIPPLE_MS = 300          # apparition d'une case

    def __init__(self, parent, paths: list, current: str | None, on_split=None, on_menu=None):
        super().__init__(parent)
        self.current = current
        self._on_split = on_split            # (hauteur du texte en px, fini) : Ctrl + bordure image | texte
        self._on_menu = on_menu              # (position globale) : clic droit
        self._split_drag = None              # bas de la case (y global) pendant le geste
        self.film_look = _film_look()
        self._look_sig = _film_look_signature()
        self._ripple_fade = False            # True : simple fondu des cases (vague coupee dans les reglages)
        self._ripple_items: list = []        # (rect, index, en cours) des cases visibles pendant l'apparition
        self._late_proxies: set = set()      # vignettes arrivees pendant l'apparition : appliquees a sa fin
        # Decodages des vignettes demandes pendant l'ouverture animee (warm_cells -> fin de l'apparition) :
        # lances a la fin (ils prenaient du temps a l'animation). None = lances tout de suite.
        self._held_proxies: list | None = None
        self._ripple_prev: set = set()       # cases encore en mouvement a l'image precedente
        # Glissement de la molette (_scroll_to_row(animate=True)) : ligne visee, depart, horloge, image des
        # lignes qui defilent (_render_band).
        self._scroll_goal: int | None = None
        self._glide_band = None
        self._scroll_from = 0
        self._scroll_clock = QElapsedTimer()
        self._scroll_timer = QTimer(self)
        self._scroll_timer.setTimerType(Qt.PreciseTimer)
        self._scroll_timer.setInterval(8)
        self._scroll_timer.timeout.connect(self._scroll_tick)
        self._warm_timer = QTimer(self)      # cases des lignes voisines, au repos (_warm_around)
        self._warm_timer.setSingleShot(True)
        self._warm_timer.setInterval(30)
        self._warm_timer.timeout.connect(self._warm_around)
        self.TILE = FocusGallery.tile_size
        self._tiles: dict[str, QPixmap] = {}
        self._proxy_pool = QThreadPool(self)
        self._proxy_pool.setMaxThreadCount(2)
        self._proxy_signals = _ProxySignals(self)
        self._proxy_signals.done.connect(self._on_proxy)
        self._proxy_pending: dict[str, int] = {}
        self._proxy_failed: set[str] = set()
        self._zoom_into = 0
        self._ripple_origin: QPointF | None = None
        self._ripple_end = 0.0
        self._ripple_clock = QElapsedTimer()
        self._ripple_timer = QTimer(self)
        self._ripple_timer.setInterval(15)
        self._ripple_timer.timeout.connect(self._ripple_tick)
        self.setViewMode(QListView.IconMode)
        self.setResizeMode(QListView.Adjust)
        self.setMovement(QListView.Static)
        self.setUniformItemSizes(True)
        self.setWrapping(True)
        self.setSelectionMode(QAbstractItemView.SingleSelection)
        self.setVerticalScrollMode(QAbstractItemView.ScrollPerPixel)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)     # molette seulement : largeur stable
        self.setSpacing(0)
        self.setFrameShape(QListWidget.NoFrame)
        self.setMouseTracking(True)
        self.setStyleSheet("QListWidget { background: transparent; border: none; outline: 0; }"
                           "QListWidget::item, QListWidget::item:selected, QListWidget::item:hover"
                           " { background: transparent; border: none; }")
        self.viewport().setAutoFillBackground(False)
        self._look = _gallery_look()
        self._filled = False                 # Ctrl+molette avant, peu de fichiers : ils remplissent l'ecran (_fit_plan)
        self._table = QSize(0, 0)
        self._cols = self._rows = self._visible_rows = 1
        self._wheel_rest = 0
        self._box_side = self.TILE
        self.setItemDelegate(_GalleryDelegate(self))
        # Visionneuse > Tableau > Ombres : le cadre du tableau = le viewport ; l'ombre deborde dans les marges
        # de la planche (sous-couche voisine, settings_widgets.ShadowUnderlay).
        from settings_widgets import attach_shadow
        self._table_shadow = attach_shadow(self.viewport(), lambda: self.film_look["table_shadow"],
                                           lambda: self.film_look["table"]["radius"])
        current_item = None
        for path in paths:
            try:
                info = os.stat(path)
            except OSError:
                continue
            if _stat.S_ISDIR(info.st_mode):
                continue
            item = QListWidgetItem(display_name(path))
            item.setData(Qt.UserRole, str(path))
            item.setData(Qt.UserRole + 1, info.st_mtime)
            item.setData(Qt.UserRole + 2, f"{Path(path).suffix.lstrip('.').upper()} · {human_size(info.st_size)}")
            item.setToolTip(display_name(path))
            self.addItem(item)
            if str(path) == current:
                current_item = item
        self.itemClicked.connect(lambda item: self.chosen.emit(Path(item.data(Qt.UserRole))))
        # Clic a cote du tableau : sur les marges de la planche (hors viewport) ou dans le viewport hors
        # du tableau (voir eventFilter).
        self._outside_press = None
        self.installEventFilter(self)
        self.viewport().installEventFilter(self)
        self.source_tip = ProxySourceTip(self.viewport(), lambda pos: self.indexAt(pos).data(Qt.UserRole))
        self._photo_rects: dict = {}         # chemin -> place de la photo dans sa case (peinte)
        self._attr_hover = None              # (chemin, genre, valeur) de l'element d'attribut sous le curseur
        self._attr_press = False
        self._keywords_window = None
        self.hidden_path: str | None = None    # image en vol (voir _GalleryDelegate.paint)
        self._fade_anim = None
        if current_item is not None:
            self.setCurrentItem(current_item)
        self._apply_grid()

    def _apply_grid(self):
        self._layout_table()

    def _plan(self, tile: float) -> tuple:
        """Decoupage retenu. Les cases ont TOUJOURS la taille du decoupage qui remplit l'ecran
        (`_fill_plan` pour un dossier assez grand) : peu de fichiers ne les agrandit pas. Si tous les
        fichiers tiennent a l'ecran, le tableau est CARRE en nombre de cases (4 fichiers = 2 x 2, 5 = 3 x
        2, 9 = 3 x 3 : on ne remplit pas d'abord une ligne ; plus de colonnes que de lignes sur un ecran
        large, l'inverse en portrait) et centre. Sinon : `_fill_plan`, cale sur les bords et defilant."""
        if self._filled:
            return self._fit_plan()
        full = self._fill_plan(tile, crowded=True)
        count = max(1, self.count())
        if count > full[0] * full[1]:
            return self._fill_plan(tile)
        big = math.ceil(math.sqrt(count))
        small = math.ceil(count / big)
        wide = self.width() >= self.height()
        for cols, rows in (((big, small), (small, big)) if wide else ((small, big), (big, small))):
            if cols <= full[0] and rows <= full[1]:
                return cols, rows, full[2], full[3]
        cols = full[0]
        return cols, math.ceil(count / cols), full[2], full[3]

    def _fit_plan(self) -> tuple:
        """Tous les fichiers a l'ecran dans les plus grandes cases carrees possibles : tableau carre en
        nombre de cases (4 = 2 x 2...), oriente comme l'ecran, qui le remplit (Ctrl+molette avant au-dela
        de « tout tient a l'ecran », voir _zoom_fill)."""
        count = max(1, self.count())
        width, height = max(1, self.width() - 1), max(1, self.height())
        big = math.ceil(math.sqrt(count))
        small = math.ceil(count / big)
        cols, rows = max(((big, small), (small, big)), key=lambda cr: min(width // cr[0], height // cr[1]))
        side = max(1, min(width // cols, height // rows))
        return cols, rows, side, side

    def _shows_all(self, plan: tuple) -> bool:
        return math.ceil(max(1, self.count()) / max(1, plan[0])) <= plan[1]

    def _can_fill(self) -> bool:
        """Tous les fichiers sont a l'ecran et pourraient y etre plus grands (le remplir)."""
        if self._filled:
            return False
        current = self._plan(self.TILE)
        fit = self._fit_plan()
        # (au moins 3 % plus grandes : un cran qui ne changerait rien a l'ecran serait un cran perdu)
        return self._shows_all(current) and min(fit[2], fit[3]) > max(current[2], current[3]) * 1.03

    def _set_filled(self, filled: bool, anchor=None):
        """Ecran rempli par tous les fichiers (Ctrl+molette avant, peu de fichiers) ou retour a la taille
        des vignettes (Ctrl+molette arriere)."""
        if filled == self._filled:
            return
        self._filled = filled
        self._tiles.clear()
        self._apply_grid()
        self.doItemsLayout()
        if not filled and self.currentItem() is not None:
            self._scroll_to_row(self._row_of(self.currentItem()) - (self._visible_rows - 1) // 2)
        self.viewport().update()

    def _fill_plan(self, tile: float, crowded: bool = False) -> tuple:
        """(colonnes, lignes visibles, largeur, hauteur de cellule) pour une vignette de `tile` px.

        Le tableau REMPLIT la zone : colonnes = toute la largeur, lignes visibles = toute la
        hauteur (les suivantes sont plus bas, hors de la vue, et defilent ligne par ligne). Les
        cellules visibles sont donc agrandies / reduites pour s'y caler ; CONTRAINTE N° 1 : elles
        restent le plus CARREES possible — parmi les colonnes voisines de celles que demande la
        taille de vignette, on garde le decoupage le plus carre (la taille demandee departage).
        Trop peu de fichiers pour remplir la hauteur (ou la largeur) : les cellules restent
        carrees et le tableau est centre sur cet axe. `crowded` : comme si le dossier remplissait
        l'ecran (taille de reference des cases, voir _plan)."""
        pad = self._look["padding"]
        width = max(1, self.width() - 1)      # Qt passe a la ligne quand une rangee remplit EXACTEMENT le viewport
        height = max(1, self.height())
        count = 1_000_000 if crowded else max(1, self.count())
        ideal = width / max(1.0, tile + pad["left"] + pad["right"])
        best = None
        candidates = {min(count, c) for c in range(max(1, math.floor(ideal) - 2), math.ceil(ideal) + 3)}

        def consider(cols, visible, cell_w, cell_h):
            # Carre d'abord ; puis remplir la zone (part laissee vide) ; puis la taille demandee.
            nonlocal best
            if cell_w < 1 or cell_h < 1:
                return
            empty = (1.0 - cols * cell_w / width) + (1.0 - visible * cell_h / height)
            # (a 3 % pres, une cellule compte pour carree : remplir la zone l'emporte alors)
            score = (10.0 * max(0.0, abs(math.log(cell_w / cell_h)) - 0.03) + 3.0 * empty
                     + abs(math.log(cols / max(0.01, ideal))))
            if best is None or score < best[0]:
                best = (score, cols, visible, cell_w, cell_h)

        for cols in sorted(candidates):
            cell_w = width // cols
            needed = math.ceil(count / cols)
            for visible in {max(1, math.floor(height / cell_w)), max(1, math.ceil(height / cell_w))}:
                # Pas assez de lignes pour remplir : autant de lignes que de fichiers.
                visible = min(visible, needed)
                consider(cols, visible, cell_w, height // visible)            # cale sur les 4 bords
                side = min(cell_w, height // visible)
                consider(cols, visible, side, side)                           # carrees, centrees
        if best is None:
            return 1, 1, width, height
        return best[1:]

    def _layout_table(self):
        """Pose le decoupage de `_plan` : grille, marges du viewport (tableau cale sur les bords,
        ou centre s'il ne les atteint pas), defilement ramene sur une ligne entiere."""
        pad = self._look["padding"]
        cols, visible, cell_w, cell_h = self._plan(self.TILE)
        width, height = max(1, self.width()), max(1, self.height())
        rows = math.ceil(max(1, self.count()) / cols)
        table_w, table_h = cols * cell_w, rows * cell_h
        view_h = visible * cell_h
        left = max(0, (width - 1 - table_w) // 2)
        top = max(0, (height - view_h) // 2)
        self._cols, self._rows, self._visible_rows = cols, rows, visible
        self._table = QSize(table_w, table_h)
        box_side = max(1, max(cell_w - pad["left"] - pad["right"],
                              cell_h - pad["top"] - pad["bottom"] - self.label_height()))
        if box_side != self._box_side:
            self._box_side = box_side
            self._tiles.clear()
        self.setViewportMargins(left, top, max(0, width - 1 - table_w - left), max(0, height - view_h - top))
        if self.gridSize() != QSize(cell_w, cell_h):
            self.setGridSize(QSize(cell_w, cell_h))
            self.doItemsLayout()
        self._scroll_to_row(self.first_visible_row())

    def path_keys(self) -> tuple:
        """Les fichiers de la planche, dans l'ordre (reconnaitre le meme dossier d'une ouverture a l'autre)."""
        return tuple(self.item(row).data(Qt.UserRole) for row in range(self.count()))

    SCROLL_MS = 240          # glissement d'un cran de molette (Visionneuse > Scrolling anime)

    def first_visible_row(self) -> int:
        if self._scroll_goal is not None:
            return self._scroll_goal         # en plein glissement : la ligne ou il s'arretera
        return round(self.verticalScrollBar().value() / max(1, self.gridSize().height()))

    def _scroll_to_row(self, row: int, animate: bool = False):
        """Defilement par LIGNES entieres : les lignes visibles restent calees sur la zone. `animate`
        (molette, reglage « Scrolling anime ») : les lignes GLISSENT jusque-la (depart de la position
        courante : des crans rapides se cumulent sans a-coup) ; sinon saut sec."""
        row = max(0, min(int(row), self._rows - self._visible_rows))
        goal = row * self.gridSize().height()
        bar = self.verticalScrollBar()
        if not animate or bar.value() == goal:
            self._stop_scroll()
            bar.setValue(goal)
            self._schedule_warm()            # au repos : lignes voisines preparees
            return
        if self._held_proxies is None:
            self._held_proxies = []          # decodages de vignettes retenus jusqu'a l'arrivee
        # Toutes les lignes qui vont passer a l'ecran, en UNE image faite avant le depart (`_glide_band`) :
        # chaque image du glissement ne fait que la poser, decalee. Repeindre les cases a chaque pas (la
        # planche est transparente : Qt ne peut pas decaler l'ancien affichage, tout est repeint) et les
        # fabriquer au passage hachait le glissement (mesure a l'ecran : _probe_gallery_scroll.py).
        grid_h = max(1, self.gridSize().height())
        start_row = bar.value() // grid_h
        lo, hi = min(start_row, row), max(start_row, row) + self._visible_rows + 1
        band = self._glide_band
        if band is None or lo < band[0] or hi > band[1] or self._ripple_timer.isActive():
            self._glide_band = None if self._ripple_timer.isActive() else self._render_band(lo, hi)
        self._scroll_goal = row
        self._scroll_from = bar.value()
        self._scroll_clock.restart()
        if not self._scroll_timer.isActive():
            _fine_timer(True)
            _snappy_gil(True)                # chaque image ne fait que poser la bande : GIL rendu vite
            self._scroll_timer.start()

    def _scroll_tick(self):
        t = min(1.0, self._scroll_clock.elapsed() / self.SCROLL_MS)
        eased = 1.0 - (1.0 - t) ** 3 if t < 1.0 else 1.0
        goal = self._scroll_goal * self.gridSize().height()
        self.verticalScrollBar().setValue(round(self._scroll_from + (goal - self._scroll_from) * eased))
        if t >= 1.0:
            self._stop_scroll()

    def _stop_scroll(self):
        if self._glide_band is not None:
            self._glide_band = None
            self.viewport().update()         # retour aux cases vivantes (survol...)
        if self._scroll_timer.isActive():
            self._scroll_timer.stop()
            _fine_timer(False)
            _snappy_gil(False)
            self._scroll_goal = None
            if not self._ripple_timer.isActive():
                self._apply_late_proxies()   # vignettes arrivees pendant le glissement + decodages retenus
                self._schedule_warm()
        self._scroll_goal = None

    def attr_editing_allowed(self) -> bool:
        """Attributs manipulables au survol : pas pendant une animation, ni le vol d'une image."""
        return not self._busy() and self._ripple_origin is None and self._split_drag is None

    def photo_band(self, look: dict | None = None) -> int:
        """Bande reservee a la photo pour les attributs : AUCUNE (demande de l'utilisateur : le calque de l'image
        et celui des icones d'attribut sont PARALLELES, chacun avec son padding, sans influence de l'un sur
        l'autre ; les icones sont peintes par-dessus la photo)."""
        return 0

    def photo_room(self, key: str, cell: QRect) -> QRect:
        """Zone image (coins de la diapo, ou se posent les attributs) de la case `key` (cellule de grille
        `cell`, repere de la case)."""
        rel = self._photo_rects.get(key)
        if rel is None:
            look = self.film_look_for(key)
            _outer, _cell, box = self.edited_cell_boxes(QRect(QPoint(0, 0), cell.size()), look)
            bg, pad = look["bg_padding"], look["attr_padding"]
            rel = box.adjusted(bg["left"] + pad["left"], bg["top"] + pad["top"],
                               -bg["right"] - pad["right"], -bg["bottom"] - pad["bottom"])
        return QRect(rel)

    def _attr_at(self, pos: QPoint):
        """(chemin, genre, valeur, case) de l'element d'attribut sous `pos` (repere du viewport) ; None."""
        if not self.attr_editing_allowed() or not self.viewport().rect().contains(pos):
            return None
        index = self.indexAt(pos)
        if not index.isValid():
            return None
        from fm_visionneuse import file_attributes
        key = index.data(Qt.UserRole)
        if key == self.hidden_path or not file_attributes.eligible(Path(key)):
            return None
        cell = self.visualRect(index)
        hit = attr_hit(self.photo_room(key, cell), pos - cell.topLeft())
        return (key, hit[0], hit[1], cell) if hit else None

    def _set_attr_hover(self, hit, cell_pos: QPoint | None = None):
        new = (hit[0], hit[1], hit[2]) if hit else None
        if new == self._attr_hover:
            return
        old, self._attr_hover = self._attr_hover, new
        for key in {old[0] if old else None, new[0] if new else None} - {None}:
            self.viewport().update()
        self.viewport().setCursor(Qt.PointingHandCursor if new else Qt.ArrowCursor)
        if not new:
            self.viewport().unsetCursor()

    def _apply_attr(self, key: str, kind: str, value):
        """Clic sur un element d'attribut : note, couleur, drapeau (re-clic = aucun) ou fenetre des mots cles."""
        from fm_visionneuse import file_attributes
        path = Path(key)
        current = self.attr_values(key)
        if kind == "star":
            changes = {"rating": 0 if int(current.get("rating") or 0) == value else value}
        elif kind == "color":
            changes = {"color": 0 if int(current.get("color") or 0) == value else value}
        elif kind == "flag":
            changes = {"status": "" if current.get("status") == value else value}
        else:
            self.open_keywords_window(key)
            return
        file_attributes.update(path, **changes)
        merged = dict(current)
        merged.update(changes)
        self.hold_attrs(key, merged)

    def open_keywords_window(self, key: str):
        """Fenetre des mots cles de `key` ; une deja ouverte est fermee (enregistree). La reference est
        lachee a la fermeture (`closed`) : la fenetre se detruit d'elle-meme et une reference restee sur un
        objet detruit faisait echouer toute reouverture (signale : « il ne se passe rien »)."""
        previous, self._keywords_window = self._keywords_window, None
        if previous is not None:
            try:
                previous._accept()
            except RuntimeError:                      # deja detruite
                pass
        window = KeywordsWindow(self, key, self.attr_values(key).get("keywords") or [])
        self._keywords_window = window
        window.saved.connect(lambda words, k=key: self._keywords_saved(k, words))
        window.closed.connect(self._keywords_window_closed)
        window.popup_near(QCursor.pos())

    def _keywords_window_closed(self, window):
        if self._keywords_window is window:
            self._keywords_window = None

    def _keywords_saved(self, key: str, words: list):
        from fm_visionneuse import file_attributes
        file_attributes.update(Path(key), keywords=words)
        merged = dict(self.attr_values(key))
        if words:
            merged["keywords"] = words
        else:
            merged.pop("keywords", None)
        self.hold_attrs(key, merged)

    def _busy(self) -> bool:
        """Une animation de la planche tourne (apparition, glissement de la molette) : rien ne doit lui
        prendre de temps (cases refaites, decodages)."""
        return self._ripple_timer.isActive() or self._scroll_timer.isActive()

    def _cell_ready(self, index, size: QSize) -> bool:
        cached = _CELLS.get(index.data(Qt.UserRole))
        return cached is not None and cached[0] == (size.width(), size.height(),
                                                    index.data(Qt.UserRole) == self.hidden_path, self._look_sig,
                                                    self.devicePixelRatioF() or 1.0)

    def _warm_rows(self, lo: int, hi: int, budget: float | None = None) -> bool:
        """Fabrique les cases des lignes [lo, hi) qui ne sont pas pretes ; `budget` (s) : s'arrete au-dela
        (False = il en reste)."""
        size = self.gridSize()
        cols = max(1, self._cols)
        deadline = time.perf_counter() + budget if budget is not None else None
        for i in range(max(0, lo) * cols, min(self.count(), max(0, hi) * cols)):
            index = self.model().index(i, 0)
            if self._cell_ready(index, size):
                continue
            self.cell_pixmap(index, size)
            if deadline is not None and time.perf_counter() > deadline:
                return False
        return True

    def _render_band(self, lo: int, hi: int):
        """(premiere ligne, derniere + 1, image) : les lignes [lo, hi) du tableau comme a l'ecran (fond et
        cadre de Visionneuse > Tableau, cases gardees, case en cours et survolee marquees, bordures
        interieures), pour le glissement de la molette."""
        lo, hi = max(0, lo), min(self._rows, hi)
        size = self.gridSize()
        gw, gh = size.width(), size.height()
        width = max(1, self.viewport().width())
        dpr = self.devicePixelRatioF() or 1.0
        pix = QPixmap(max(1, round(width * dpr)), max(1, round(max(1, hi - lo) * gh * dpr)))
        pix.setDevicePixelRatio(dpr)
        pix.fill(Qt.transparent)
        painter = QPainter(pix)
        painter.setRenderHint(QPainter.Antialiasing, True)
        painter.setRenderHint(QPainter.SmoothPixmapTransform, True)
        table = QRect(0, -lo * gh, self._table.width(), self._table.height())
        self._paint_table_back(painter, table)
        hover = None
        if self.viewport().underMouse():
            hover = self.indexAt(self.viewport().mapFromGlobal(QCursor.pos()))
        cols = max(1, self._cols)
        for i in range(lo * cols, min(self.count(), hi * cols)):
            index = self.model().index(i, 0)
            row, col = divmod(i, cols)
            mark = ("focus" if index.data(Qt.UserRole) == self.current
                    else "hover" if hover is not None and hover.isValid() and hover.row() == i else None)
            painter.drawPixmap(QPoint(col * gw, (row - lo) * gh), self.cell_pixmap(index, size, mark))
        self._paint_table_front(painter, table)
        painter.end()
        return lo, hi, pix

    def _schedule_warm(self):
        timer = getattr(self, "_warm_timer", None)
        if timer is not None:
            timer.start()

    def _warm_around(self):
        """Au repos : les cases des lignes voisines (un ecran au-dessus et au-dessous) sont faites par
        petites tranches, pour que le prochain glissement les trouve pretes."""
        if not self.isVisible():
            return
        if self._busy():
            return                           # relance a la fin de l'animation
        first = self.first_visible_row()
        rows = max(1, self._visible_rows)
        if not self._warm_rows(first - rows, first + 2 * rows + 1, budget=0.004):
            self._warm_timer.start()

    @staticmethod
    def scroll_animated() -> bool:
        import ui_state
        return bool((ui_state.APPLIED_SETTINGS or {}).get("viewer_scroll_animated", True))

    def table_corners(self, i: int) -> frozenset:
        """Coins du TABLEAU que partage la case n° `i` ("top_left"...) : premiere / derniere colonne de la
        premiere / derniere ligne (derniere ligne incomplete : son coin bas droit est une place vide)."""
        cols, rows = max(1, self._cols), max(1, self._rows)
        row, col = divmod(i, cols)
        out = set()
        if row == 0 and col == 0:
            out.add("top_left")
        if row == 0 and col == cols - 1:
            out.add("top_right")
        if row == rows - 1 and col == 0:
            out.add("bottom_left")
        if row == rows - 1 and col == cols - 1:
            out.add("bottom_right")
        return frozenset(out)

    def mark_insets(self, i: int) -> tuple:
        """(gauche, haut, droite, bas) de la case n° `i` couverts par ce que la planche peint PAR-DESSUS les
        cases (_paint_table_front) : filets interieurs (centres sur la limite : `ep - ep // 2` px du cote de la
        case qui suit, `ep // 2` de celle qui precede) et bordure du tableau sur les bords exterieurs. Le cadre
        d'une couleur attribuee s'y loge, sinon ses bords gauche et haut etaient caches (signale)."""
        cols, rows = max(1, self._cols), max(1, self._rows)
        row, col = divmod(i, cols)
        look = self.film_look
        v_on, _c, v_t = look["inner_v"]
        h_on, _c, h_t = look["inner_h"]
        v_t, h_t = (v_t if v_on else 0), (h_t if h_on else 0)
        table = look["table"]
        edge = {side: (table["thick"] if table["on"].get(side) else 0) for side in ("left", "top", "right", "bottom")}
        left = edge["left"] if col == 0 else v_t - v_t // 2
        right = edge["right"] if col == cols - 1 else v_t // 2
        top = edge["top"] if row == 0 else h_t - h_t // 2
        bottom = edge["bottom"] if row == rows - 1 else h_t // 2
        return (left, top, right, bottom)

    def _row_of(self, item) -> int:
        return self.row(item) // max(1, self._cols)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._layout_table()

    def _table_rect(self) -> QRect:
        """Le tableau entier dans le repere du viewport (suit le defilement)."""
        return QRect(0, -self.verticalScrollBar().value(), self._table.width(), self._table.height())

    def paintEvent(self, event):
        band = self._glide_band
        if band is not None:
            # Glissement de la molette : l'image des lignes qui defilent, posee a la position courante.
            painter = QPainter(self.viewport())
            painter.drawPixmap(0, band[0] * self.gridSize().height() - self.verticalScrollBar().value(), band[2])
            painter.end()
            return
        table = self._table_rect()
        painter = QPainter(self.viewport())
        painter.setRenderHint(QPainter.Antialiasing, True)
        self._paint_table_back(painter, table)
        if self._ripple_origin is not None and self._ripple_items:
            # Pendant l'apparition (vague ou fondu) : les cases sont posees ici, directement depuis leurs
            # images gardees, sans la mecanique des delegues de la liste (trop lente a chaque image).
            self._paint_ripple(painter, event.rect())
        else:
            painter.end()
            super().paintEvent(event)
            painter = QPainter(self.viewport())
            painter.setRenderHint(QPainter.Antialiasing, True)
        self._paint_table_front(painter, table)
        painter.end()

    def _paint_table_back(self, painter: QPainter, table: QRect):
        """Fond du tableau (Reglages > Visionneuse > Tableau), sous les cases."""
        _paint_film_box(painter, QRectF(table), {**self.film_look["table"], "thick": 0})

    def _paint_table_front(self, painter: QPainter, table: QRect):
        """Par-dessus les cases : bordures interieures (Visionneuse > Tableau > Bordure interieure H / V)
        puis bordures du tableau."""
        grid = self.gridSize()
        on, color, thick = self.film_look["inner_h"]
        if on and thick:
            for row in range(1, self._rows):
                painter.fillRect(QRect(table.x(), table.y() + row * grid.height() - thick // 2, table.width(), thick), color)
        on, color, thick = self.film_look["inner_v"]
        if on and thick:
            for col in range(1, self._cols):
                painter.fillRect(QRect(table.x() + col * grid.width() - thick // 2, table.y(), thick, table.height()), color)
        _paint_film_box(painter, QRectF(table), {**self.film_look["table"], "fill": None})

    # -- Habillage (Reglages > Visionneuse), bordure image | texte, clic droit --

    def restyle(self):
        """Reglages de la visionneuse changes : nouvel habillage, hauteur du texte, mise en page."""
        self.film_look = _film_look()
        self._look = _gallery_look()
        self._table_shadow.sync()
        self._look_sig = _film_look_signature()
        self._filter_palette = None                # couleurs attribuees : reglages relus
        self._attr_colors = {}
        self._layout_table()
        self.viewport().update()

    def film_look_for(self, path: str) -> dict:
        """Habillage general complete par les overrides propres a cette cellule / image / texte."""
        import ui_state
        if not hasattr(ui_state, "GALLERY_STYLE_OVERRIDES"):
            from settings_element_style import ensure_row_text_overrides
            ensure_row_text_overrides()
        from settings_store import _coerce_corner_radius, _coerce_side_enabled
        from settings_element_style import _editable_font_size
        # Ne pas deepcopy les QFont / QColor Qt du look de base : leur copie Python peut
        # invalider des ressources C++ encore utilisees par les peintures de la planche.
        look = dict(self.film_look)
        look["split"] = bool(self.SPLIT_CELLS)       # case divisee (ancien mode) : marques sur les sous-cellules
        for key in ("image_cell", "text_cell", "image"):
            box = dict(self.film_look[key])
            box["on"] = dict(box.get("on") or {})
            box["colors"] = dict(box.get("colors") or {})
            box["radius"] = dict(box.get("radius") or {})
            look[key] = box
        overrides = getattr(ui_state, "GALLERY_STYLE_OVERRIDES", {}) or {}
        cell_values = {}
        for part in ("cell", "name", "info"):
            cell_values.update({key: value for key, value in
                                (overrides.get(f"gallery-{part}:{path}") or {}).items()
                                if key.startswith("gallery_cell_")})
        if cell_values:
            from app_style import resolve_color_ref
            enabled = _coerce_side_enabled(cell_values.get("gallery_cell_border_enabled"), False)
            raw_colors = cell_values.get("gallery_cell_border") or {}
            colors = {side: resolve_color_ref(raw_colors.get(side) if isinstance(raw_colors, dict)
                                               else raw_colors, "#2a2e32") for side in _FILM_SIDES}
            thickness = max(0, int(cell_values.get("gallery_cell_border_thickness", 1) or 0))
            fill = QColor(resolve_color_ref(cell_values.get("gallery_cell_bg"), "#00000000"))
            look["cell"] = {"on": enabled, "colors": colors,
                            "thick": thickness if any(enabled.values()) else 0,
                            "radius": _coerce_corner_radius(cell_values.get("gallery_cell_border_radius", 0)),
                            "fill": fill.name(QColor.NameFormat.HexArgb) if fill.alpha() else None}
            look["cell_padding"] = cell_values.get("gallery_cell_padding") or {}
        for part in ("cell", "image", "name", "info"):
            saved = overrides.get(f"gallery-{part}:{path}") or {}
            if not saved:
                continue
            values = dict(ui_state.APPLIED_SETTINGS or {})
            values.update(saved)
            if part in {"cell", "image"}:
                boxes = (("image", "viewer_film_image"),) if part == "image" else (
                    ("image_cell", "viewer_film_image_cell"),
                    ("text_cell", "viewer_film_text_cell"),
                    ("image", "viewer_film_image"),
                )
                for key, prefix in boxes:
                    box = look[key]
                    enabled = values.get(f"{prefix}_border_enabled")
                    if enabled is not None:
                        box["on"] = _coerce_side_enabled(enabled, False)
                    colors = values.get(f"{prefix}_border")
                    if colors is not None:
                        from app_style import resolve_color_ref
                        box["colors"] = {side: resolve_color_ref(colors.get(side) if isinstance(colors, dict)
                                                                  else colors, "#2a2e32")
                                          for side in _FILM_SIDES}
                    thickness = values.get(f"{prefix}_border_thickness")
                    if thickness is not None:
                        box["thick"] = max(0, int(thickness)) if any(box["on"].values()) else 0
                    radius = values.get(f"{prefix}_border_radius")
                    if radius is not None:
                        box["radius"] = _coerce_corner_radius(radius)
                    bg = values.get(f"{prefix}_bg")
                    if bg is not None and key != "image":
                        from app_style import resolve_color_ref
                        color = QColor(resolve_color_ref(bg, "#00000000"))
                        box["fill"] = color.name(QColor.NameFormat.HexArgb) if color.alpha() else None
                    if part == "cell" and key in {"image_cell", "text_cell"}:
                        from app_style import font as app_font, resolve_color_ref
                        family_key = f"{prefix}_font_family"
                        if family_key in values:
                            size = max(4, int(values.get(f"{prefix}_font_size", 11) or 11))
                            weight = 700 if values.get(f"{prefix}_font_bold") else 400
                            label = (values.get(family_key) or "").strip()
                            family = None
                            if label and label != "Systeme":
                                from browser_core import _resolve_font_family
                                family = _resolve_font_family(label, size, weight)
                            qfont = app_font(size, weight, family=family,
                                             italic=bool(values.get(f"{prefix}_font_italic")),
                                             smoothing=values.get(f"{prefix}_font_smoothing", "current")
                                             if values.get(f"{prefix}_font_smoothing_enabled") else "current")
                            color = QColor(resolve_color_ref(values.get(f"{prefix}_font_color"), "#d6d9dc"))
                            look["ext_font" if key == "image_cell" else "name_font"] = (qfont, color)
                if part in {"cell", "image"} and any(k.startswith("viewer_film_image_shadow") for k in values):
                    from app_style import resolve_color_ref
                    from settings_widgets import shadow_look
                    look["image_shadow"] = shadow_look(values, "viewer_film_image_shadow", resolve_color_ref)
            else:
                from app_style import font as app_font, resolve_color_ref
                qfont, qcolor = look["name_font" if part == "name" else "rank_font"]
                defaults = {"text_font_family": qfont.family(),
                            "text_font_bold": qfont.weight() >= QFont.DemiBold,
                            "text_font_italic": qfont.italic(),
                            "text_font_size": _editable_font_size(qfont),
                            "text_font_color": qcolor.name(QColor.NameFormat.HexArgb),
                            "text_font_smoothing_enabled": False, "text_font_smoothing": "current",
                            "text_padding": {s: 0 for s in ("left", "top", "right", "bottom")},
                            "text_border_enabled": {s: False for s in _FILM_SIDES},
                            "text_border": {s: "#00000000" for s in _FILM_SIDES},
                            "text_border_thickness": 1, "text_border_radius": 0,
                            "text_background_enabled": False, "text_background_color": "#00000000"}
                defaults.update(saved)
                values = defaults
                size = max(1, int(values.get("text_font_size", qfont.pointSize() or 11) or 11))
                weight = 600 if values.get("text_font_bold", qfont.weight() >= QFont.DemiBold) else 400
                family = (values.get("text_font_family") or "").strip() or qfont.family()
                smoothing = values.get("text_font_smoothing", "current") if values.get("text_font_smoothing_enabled") else "current"
                look["name_font" if part == "name" else "rank_font"] = (app_font(size, weight, family=family,
                                                   italic=bool(values.get("text_font_italic")), smoothing=smoothing),
                                         QColor(resolve_color_ref(values.get("text_font_color"), qcolor.name())))
                look[f"{part}_style"] = values
        return look

    def edit_target_at(self, point: QPoint):
        """Retourne la partie peinte cliquée et les rectangles de sa cellule (repère viewport)."""
        index = self.indexAt(point)
        if not index.isValid():
            return None
        path = str(index.data(Qt.UserRole) or "")
        rect = self.visualRect(index)
        look = self.film_look_for(path)
        cell_outer, cell, box = self.edited_cell_boxes(rect, look)
        text_box = QRect(cell.x(), box.bottom() + 1, cell.width(), max(0, cell.bottom() - box.bottom()))
        text_room = _film_inner(QRectF(text_box), look["text_cell"]).toRect()
        info = str(index.data(Qt.UserRole + 2) or "")
        name_font, info_font = look["name_font"][0], look["rank_font"][0]
        name_metrics, info_metrics = QFontMetrics(name_font), QFontMetrics(info_font)
        total = name_metrics.height() + (info_metrics.height() if info else 0)
        top = text_room.y() + max(0, (text_room.height() - total) // 2)
        name = name_metrics.elidedText(display_name(Path(path)), Qt.ElideMiddle, text_room.width())
        name_width = min(text_room.width(), name_metrics.horizontalAdvance(name))
        info_width = min(text_room.width(), info_metrics.horizontalAdvance(
            info_metrics.elidedText(info, Qt.ElideRight, text_room.width())))
        name_rect = QRect(text_room.center().x() - name_width // 2, top, name_width, name_metrics.height())
        info_rect = QRect(text_room.center().x() - info_width // 2, top + name_metrics.height(),
                          info_width, info_metrics.height())
        offsets = getattr(self, "_edit_offsets", {}).get(path, {})
        if name_rect.translated(offsets.get("gallery-name", QPoint())).contains(point):
            part, leaf_rect = "gallery-name", name_rect
        elif info and info_rect.translated(offsets.get("gallery-info", QPoint())).contains(point):
            part, leaf_rect = "gallery-info", info_rect
        elif box.contains(point):
            part, leaf_rect = "gallery-image", box
        else:
            part, leaf_rect = "gallery-cell", cell
        geometry = self.__dict__.setdefault("_edit_geometry", {}).setdefault(path, {})
        geometry.update({part: QRect(leaf_rect), "gallery-cell": QRect(cell_outer),
                         "gallery-text-bounds": QRect(text_room)})
        return path, part, leaf_rect, cell_outer

    def edited_cell_boxes(self, rect: QRect, look: dict):
        """Geometrie commune a la peinture et a la selection du mode edition."""
        outer, base_box = self.tile_boxes(rect)
        cell = QRect(outer)
        style = look.get("cell")
        if style is not None:
            pad = look.get("cell_padding") or {}
            thick = style["thick"]
            sides = style["on"]
            inset = {side: max(0, int(pad.get(side, 0))) + (thick if sides.get(side) else 0)
                     for side in _FILM_SIDES}
            inner = outer.adjusted(inset["left"], inset["top"], -inset["right"], -inset["bottom"])
            if inner.width() > 0 and inner.height() > 0:
                cell = inner
        box_height = max(1, min(cell.height(), base_box.height() - (cell.top() - outer.top())))
        return outer, cell, QRect(cell.x(), cell.y(), cell.width(), box_height)

    def invalidate_edited_cell(self, path: str, repaint: bool = True):
        _CELLS.pop(str(path), None)
        for key in [key for key in _MARKED if key[0] == str(path)]:
            _MARKED.pop(key, None)
        if repaint:
            self.viewport().update()

    def _paint_ripple(self, painter: QPainter, clip: QRect):
        size = self.gridSize()
        painter.setRenderHint(QPainter.SmoothPixmapTransform, True)
        for rect, index, is_current in self._ripple_items:
            if not rect.intersects(clip):
                continue
            opacity, scale = self.ripple_state(rect)
            if opacity <= 0.0:
                continue
            pixmap = self.cell_pixmap(index, size, "focus" if is_current else None)
            painter.setOpacity(opacity)
            if scale != 1.0:
                centre = QRectF(rect).center()
                painter.save()
                painter.translate(centre)
                painter.scale(scale, scale)
                painter.translate(-centre)
                painter.drawPixmap(rect.topLeft(), pixmap)
                painter.restore()
            else:
                painter.drawPixmap(rect.topLeft(), pixmap)
        painter.setOpacity(1.0)

    def warm_cells(self, wave: bool = True):
        """Images des cases visibles faites AVANT l'animation d'ouverture (vague ou fondu) : fabriquees
        au vol, plusieurs a la fois quand la vague les atteint, elles faisaient sauter des images (et
        fabriquees par tranches pendant l'animation, elles lui volaient du temps). Gardees d'une ouverture
        a l'autre (_CELLS) : seule la premiere ouverture d'un dossier les fabrique."""
        self._held_proxies = []              # relaches a la fin de l'apparition (release_proxies)
        view = self.viewport().rect()
        size = self.gridSize()
        for row in range(self.count()):
            index = self.model().index(row, 0)
            if self.visualRect(index).intersects(view):
                self.cell_pixmap(index, size, "focus" if index.data(Qt.UserRole) == self.current else None)

    def cell_pixmap(self, index, size: QSize, mark: str | None = None, hovered: bool = False) -> QPixmap:
        """Image de toute la case, refaite seulement si sa taille, sa vignette, l'habillage ou l'etat
        « en vol » changent : la peinture de la planche ne fait que poser ces images. Chemin rapide (une
        image par case et par peinture) : une case dont la vignette est definitive n'interroge plus rien.
        `mark` ("focus" / "hover") : variante marquee de la case, gardee a part (`_MARKED`)."""
        if mark is not None or hovered:
            return self._marked_pixmap(index, size, mark, hovered)
        key = index.data(Qt.UserRole)
        hidden = key == self.hidden_path
        color = self.attr_color(key)
        attrs = self.attr_values(key)
        import ui_state
        if not hasattr(ui_state, "GALLERY_STYLE_OVERRIDES"):
            from settings_element_style import ensure_row_text_overrides
            ensure_row_text_overrides()
        styles = getattr(ui_state, "GALLERY_STYLE_OVERRIDES", {}) or {}
        local_style = tuple(repr(styles.get(f"gallery-{part}:{key}")) for part in ("cell", "image", "name", "info"))
        base = (size.width(), size.height(), hidden, self._look_sig, self.devicePixelRatioF() or 1.0, color,
                (self.table_corners(index.row()), self.mark_insets(index.row())) if color else None, local_style,
                repr(sorted(attrs.items())) + str(gallery_paint.SHOW_KEYWORDS))
        cached = _CELLS.get(key)
        if cached is not None and cached[0] == base and (cached[2] or self._ripple_origin is not None):
            return cached[1]                 # (pendant l'apparition, meme une vignette provisoire reste)
        pix = None if hidden else self.tile_pixmap(Path(key), index.data(Qt.UserRole + 1))
        tile_key = pix.cacheKey() if pix is not None else 0
        final = hidden or key in self._tiles
        if cached is not None and cached[0] == base and cached[3] == tile_key:
            if final:
                _CELLS[key] = (base, cached[1], True, tile_key)
            return cached[1]
        dpr = base[4]
        out = QPixmap(max(1, round(size.width() * dpr)), max(1, round(size.height() * dpr)))
        out.setDevicePixelRatio(dpr)
        out.fill(Qt.transparent)
        painter = QPainter(out)
        _GalleryDelegate.paint_content(painter, self, QRect(QPoint(0, 0), size), Path(key),
                                       index.data(Qt.UserRole + 2) or "", pix, hidden,
                                       corners=base[6][0] if color else frozenset(), color=color,
                                       insets=base[6][1] if color else None, attrs=attrs)
        painter.end()
        _CELLS[key] = (base, out, final, tile_key)
        _CELLS.move_to_end(key)
        while len(_CELLS) > _CELLS_MAX:
            _CELLS.popitem(last=False)
        return out

    def attr_values(self, key: str) -> dict:
        """Attributs APPLIQUES au fichier (note, couleur, mots cles, statut ; valeurs par defaut omises),
        lus une fois par dossier, relus au plus toutes les 2 s, jamais pendant une animation. Juste apres
        un changement fait ici, la valeur choisie est gardee (`hold_attrs`) : Lightroom ecrit en differe."""
        now = time.monotonic()
        held = self.__dict__.setdefault("_attr_hold", {}).get(key)
        if held is not None and now < held[0]:
            return held[1]
        memo = self.__dict__.setdefault("_attr_values", {})
        hit = memo.get(key)
        if hit is not None and (now - hit[0] < 2.0 or self._busy()):
            return hit[1]
        from fm_visionneuse import file_attributes
        path = Path(key)
        try:
            from lightroom_bridge import is_managed, attributes
            managed = is_managed(path)
            values = attributes(path) if managed else None
        except (ImportError, OSError, ValueError):
            managed, values = False, None
        if not managed:
            folder, name = file_attributes.location(path)
            values = file_attributes._load_dir(folder, max_age=2.0).get(name)
        applied = file_attributes._clean(values if isinstance(values, dict) else {})
        memo[key] = (now, applied)
        return applied

    def hold_attrs(self, key: str, values: dict, seconds: float = 30.0):
        """Valeurs que l'on vient de choisir (barre de survol) : montrees aussitot, case refaite."""
        from fm_visionneuse import file_attributes
        self.__dict__.setdefault("_attr_hold", {})[key] = (time.monotonic() + seconds,
                                                           file_attributes._clean(values))
        self.__dict__.setdefault("_attr_values", {}).pop(key, None)
        self.invalidate_edited_cell(key)

    def attr_color(self, key: str) -> str | None:
        """Couleur attribuee au fichier (une des 5 de Visionneuse > Filtres) ou None (voir attr_values)."""
        index = int(self.attr_values(key).get("color") or 0)
        palette = self.__dict__.get("_filter_palette")
        if palette is None:
            palette = self._filter_palette = [c for _n, c in filter_colors()]
        return palette[index - 1] if 1 <= index <= len(palette) else None

    def _marked_pixmap(self, index, size: QSize, mark: str | None, hovered: bool = False) -> QPixmap:
        """Case en cours / survolee : meme image que `cell_pixmap`, marquage compris, refaite seulement
        quand la case simple l'est (meme signature, meme vignette)."""
        plain = self.cell_pixmap(index, size)
        key = index.data(Qt.UserRole)
        base, _out, _final, tile_key = _CELLS[key]
        corners = self.table_corners(index.row())
        cached = _MARKED.get((key, mark, hovered))
        if cached is not None and cached[0] == base and cached[1] == tile_key and cached[3] == corners:
            return cached[2]
        hidden = base[2]
        pix = None if hidden else self.tile_pixmap(Path(key), index.data(Qt.UserRole + 1))
        out = QPixmap(plain.size())
        out.setDevicePixelRatio(plain.devicePixelRatio())
        out.fill(Qt.transparent)
        painter = QPainter(out)
        _GalleryDelegate.paint_content(painter, self, QRect(QPoint(0, 0), size), Path(key),
                                       index.data(Qt.UserRole + 2) or "", pix, hidden, mark, corners,
                                       color=base[5], insets=base[6][1] if base[5] else None,
                                       attrs=self.attr_values(key), hovered=hovered)
        painter.end()
        _MARKED[(key, mark, hovered)] = (base, tile_key, out, corners)
        _MARKED.move_to_end((key, mark, hovered))
        while len(_MARKED) > 8:
            _MARKED.popitem(last=False)
        return out

    def _outside_table(self, obj, pos) -> bool:
        if obj is self:
            return not self.viewport().geometry().contains(pos)      # marges autour du viewport
        return not self._table_rect().contains(pos)

    def eventFilter(self, obj, event):
        if obj in (self, self.viewport()):
            kind = event.type()
            if kind == QEvent.Leave and obj is self.viewport():
                self.source_tip.hide()
                self._set_attr_hover(None)
            if kind == QEvent.MouseButtonPress and event.button() == Qt.LeftButton:
                pos = event.position().toPoint()
                self._outside_press = event.globalPosition() if self._outside_table(obj, pos) else None
                if self._outside_press is not None:
                    return True
            elif kind == QEvent.MouseButtonRelease and event.button() == Qt.LeftButton and self._outside_press is not None:
                press, self._outside_press = self._outside_press, None
                pos = event.position().toPoint()
                if ((event.globalPosition() - press).manhattanLength() < QApplication.startDragDistance()
                        and self._outside_table(obj, pos)):
                    self.outside_clicked.emit()
                return True
        return super().eventFilter(obj, event)

    def _split_cell_at(self, pos: QPoint):
        """Case dont la bordure image | texte est sous `pos` (repere du viewport, a 4 px pres)."""
        if not self.SPLIT_CELLS:
            return None
        for probe in (pos, pos - QPoint(0, 5), pos + QPoint(0, 5)):
            index = self.indexAt(probe)
            if not index.isValid():
                continue
            cell, box = self.tile_boxes(self.visualRect(index))
            if cell.left() <= pos.x() <= cell.right() and abs(pos.y() - (box.bottom() + 1)) <= 4:
                return cell
        return None

    def mousePressEvent(self, event):
        # Clic pendant un glissement de la molette : les lignes s'arretent la ou elles sont (on choisit
        # la case qu'on voit sous le curseur).
        self._stop_scroll()
        hit = self._attr_at(event.position().toPoint()) if event.button() == Qt.LeftButton else None
        if hit is not None:
            # Element d'attribut (note, couleur, drapeau, « + ») : agit, ne choisit pas l'image.
            self._attr_press = True
            self._apply_attr(hit[0], hit[1], hit[2])
            event.accept()
            return
        if event.button() == Qt.LeftButton and event.modifiers() & Qt.ControlModifier:
            cell = self._split_cell_at(event.position().toPoint())
            if cell is not None:
                # Le bas de la case reste en place : le texte prend ce que la souris lui laisse.
                self._split_drag = self.viewport().mapToGlobal(QPoint(0, cell.bottom() + 1)).y()
                self.viewport().setCursor(Qt.SplitVCursor)
                event.accept()
                return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        if self._split_drag is not None:
            height = self._split_drag - event.globalPosition().y()
            limit = max(self.TEXT_MIN, self.gridSize().height() - 24)
            height = int(round(max(self.TEXT_MIN, min(limit, height))))
            if self._on_split is not None:
                self._on_split(height, False)
            event.accept()
            return
        self.source_tip.update_at(event.globalPosition().toPoint(), bool(event.modifiers() & Qt.ShiftModifier))
        self._set_attr_hover(self._attr_at(event.position().toPoint()))
        if event.modifiers() & Qt.ControlModifier and self._split_cell_at(event.position().toPoint()) is not None:
            self.viewport().setCursor(Qt.SplitVCursor)
        else:
            self.viewport().unsetCursor()
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        if self._attr_press and event.button() == Qt.LeftButton:
            self._attr_press = False
            event.accept()
            return
        if self._split_drag is not None and event.button() == Qt.LeftButton:
            self._split_drag = None
            self.viewport().unsetCursor()
            if self._on_split is not None:
                self._on_split(self.label_height(), True)
            event.accept()
            return
        super().mouseReleaseEvent(event)

    def contextMenuEvent(self, event):
        if self._on_menu is not None:
            self._on_menu(event.globalPos())
            event.accept()
            return
        super().contextMenuEvent(event)

    def reveal_current(self, first_row: int | None = None):
        """Met en page puis fait defiler jusqu'a l'image en cours : sa case doit etre a sa place
        AVANT que l'image ne s'y pose (voir image_rect_in). `first_row` : premiere ligne visible a la
        derniere fermeture de la planche sur ce dossier — elle revient A LA MEME POSITION (demande de
        l'utilisateur : jamais recentree) ; l'image en cours hors de cette vue : defilement minimal
        (sa ligne en haut ou en bas). Sans memoire : sa ligne au milieu."""
        self._layout_table()
        self.doItemsLayout()
        item = self.currentItem()
        if first_row is None:
            if item is not None:
                self._scroll_to_row(self._row_of(item) - (self._visible_rows - 1) // 2)
            return
        row = first_row
        if item is not None:
            current = self._row_of(item)
            if current < row:
                row = current
            elif current > row + self._visible_rows - 1:
                row = current - self._visible_rows + 1
        self._scroll_to_row(row)

    def tile_boxes(self, rect: QRect) -> tuple:
        """(case, cadre de l'image) d'une vignette dont la cellule de grille est `rect`."""
        pad = self._look["padding"]
        cell = rect.adjusted(pad["left"], pad["top"], -pad["right"], -pad["bottom"])
        return cell, QRect(cell.x(), cell.y(), cell.width(), max(1, cell.height() - self.label_height()))

    @staticmethod
    def fit_in_box(pix: QPixmap, box: QRect) -> QRect:
        dpr = pix.devicePixelRatio() or 1.0
        size = QSize(round(pix.width() / dpr), round(pix.height() / dpr))
        size.scale(box.size(), Qt.KeepAspectRatio)
        target = QRect(0, 0, size.width(), size.height())
        target.moveCenter(box.center())
        return target

    def image_rect_in(self, widget: QWidget, path: str | None, pix: QPixmap) -> QRect | None:
        """Ou `pix` (l'image de `path`) se pose dans sa vignette, dans le repere de `widget` ;
        None si elle n'est pas dans la planche ou hors de la partie visible."""
        if not path or pix is None or pix.isNull():
            return None
        for i in range(self.count()):
            item = self.item(i)
            if item.data(Qt.UserRole) == path:
                rect = self.visualItemRect(item)
                if not rect.intersects(self.viewport().rect()):
                    return None
                box = self.tile_boxes(rect)[1]
                look = self.film_look_for(path)
                bg, pad = look["bg_padding"], look["image_padding"]
                box = box.adjusted(bg["left"] + pad["left"], bg["top"] + pad["top"],
                                   -bg["right"] - pad["right"], -bg["bottom"] - pad["bottom"])
                band = self.photo_band(look)
                if box.height() > 2 * band + 20:
                    box = box.adjusted(0, band, 0, -band)       # meme place que la case peinte
                target = self.fit_in_box(pix, box)
                return QRect(self.viewport().mapTo(widget, target.topLeft()), target.size())
        return None

    def set_hidden_path(self, path: str | None):
        self.hidden_path = path
        self.viewport().update()

    def fade(self, end: float, duration_ms: int, on_done=None):
        """Fondu de toute la planche vers l'opacite `end` (depuis l'opacite courante). A 1 :
        l'effet est retire (rendu direct, net et rapide)."""
        effect = self.graphicsEffect()
        if not isinstance(effect, QGraphicsOpacityEffect):
            effect = QGraphicsOpacityEffect(self)
            effect.setOpacity(1.0 if end <= 0.0 else 0.0)
            self.setGraphicsEffect(effect)
        if self._fade_anim is not None:
            self._fade_anim.stop()
        anim = self._fade_anim = QVariantAnimation(self)
        anim.setStartValue(float(effect.opacity()))
        anim.setEndValue(float(end))
        anim.setDuration(max(1, duration_ms))
        anim.setEasingCurve(QEasingCurve.InOutCubic)
        anim.valueChanged.connect(lambda value: effect.setOpacity(float(value)))

        def finished():
            if end >= 1.0:
                self.setGraphicsEffect(None)
            if on_done is not None:
                on_done()
        anim.finished.connect(finished)
        anim.start()

    # -- Apparition en vague ------------------------------------------------------------------

    FADE_MS = 260            # apparition en simple fondu (vague coupee)

    def start_ripple(self, wave: bool = True):
        """Les cases apparaissent (fondu + leger grossissement) en vague qui part de l'image en
        cours : plus une case en est loin, plus elle arrive tard. `wave` False (Reglages >
        Visionneuse, animation des diapositives coupee) : toutes ensemble, en simple fondu.
        Seules les cases encore en mouvement sont repeintes a chaque image (voir _ripple_tick)."""
        self._ripple_fade = not wave
        self._ripple_prev = set()
        # Cases visibles, figees pour toute l'apparition (posees par _paint_ripple).
        view = self.viewport().rect()
        self._ripple_items = []
        for row in range(self.count()):
            index = self.model().index(row, 0)
            rect = self.visualRect(index)
            if rect.intersects(view):
                self._ripple_items.append((rect, index, index.data(Qt.UserRole) == self.current))
        if not wave:
            self._ripple_origin = QPointF(0, 0)
            self._ripple_end = float(self.FADE_MS)
            self._ripple_clock.start()
            if not self._ripple_timer.isActive():
                _fine_timer(True)
            self._ripple_timer.start()
            self.viewport().update()
            return
        item = self.currentItem()
        origin = self.visualItemRect(item).center() if item is not None else self.viewport().rect().center()
        self._ripple_origin = QPointF(origin)
        grid = self.gridSize()
        view = self.viewport().rect()
        far = max(math.hypot((corner.x() - origin.x()) / max(1, grid.width()),
                             (corner.y() - origin.y()) / max(1, grid.height()))
                  for corner in (view.topLeft(), view.topRight(), view.bottomLeft(), view.bottomRight()))
        self._ripple_end = (far + 1) * self.RIPPLE_STEP_MS + self.RIPPLE_MS
        self._ripple_clock.start()
        if not self._ripple_timer.isActive():
            _fine_timer(True)                # une image toutes les ~16 ms, pas tous les 15,6 / 31 ms
        self._ripple_timer.start()
        self.viewport().update()

    def ripple_state(self, rect: QRect) -> tuple:
        """(opacite, echelle) d'une case pendant la vague ; (1, 1) en dehors."""
        if self._ripple_origin is None:
            return 1.0, 1.0
        if self._ripple_fade:
            t = max(0.0, min(1.0, self._ripple_clock.elapsed() / self.FADE_MS))
            return t * t * (3.0 - 2.0 * t), 1.0
        grid = self.gridSize()
        centre = rect.center()
        distance = math.hypot((centre.x() - self._ripple_origin.x()) / max(1, grid.width()),
                              (centre.y() - self._ripple_origin.y()) / max(1, grid.height()))
        t = (self._ripple_clock.elapsed() - distance * self.RIPPLE_STEP_MS) / self.RIPPLE_MS
        t = max(0.0, min(1.0, t))
        eased = 1.0 - (1.0 - t) ** 3
        return eased, 0.84 + 0.16 * eased

    def preview_ready(self, key: str):
        """Un apercu du pipeline vient d'etre decode (detail_panel) : seule sa case est repeinte, et pas
        pendant l'apparition (elle le sera a la fin)."""
        if self._busy():
            self._proxy_failed.discard(key)
            _drop_proxy(key)
            self._late_proxies.add(key)
            return
        self._tiles.pop(key, None)
        self._proxy_failed.discard(key)
        _drop_proxy(key)
        _CELLS.pop(key, None)
        for mark in ("focus", "hover"):
            _MARKED.pop((key, mark), None)
        for row in range(self.count()):
            item = self.item(row)
            if item.data(Qt.UserRole) == key:
                self.viewport().update(self.visualItemRect(item))
                break

    def _apply_late_proxies(self):
        for key in self._late_proxies:
            self._tiles.pop(key, None)
            _CELLS.pop(key, None)
        self._late_proxies = set()
        self.release_proxies()

    def release_proxies(self):
        """Fin de l'apparition : les decodages de vignettes retenus partent (les plus recents d'abord)."""
        held, self._held_proxies = self._held_proxies, None
        for key, need in held or ():
            self._request_proxy(key, need)

    def _ripple_tick(self):
        if self._ripple_clock.elapsed() >= self._ripple_end:
            self._ripple_timer.stop()
            _fine_timer(False)
            self._ripple_origin = None
            self._ripple_prev = set()
            self._apply_late_proxies()
            self.viewport().update()
            self._schedule_warm()
            return
        if self._ripple_fade:
            self.viewport().update()         # toutes les cases changent ensemble
            return
        # Vague : seules les cases en mouvement (et celles qui viennent de finir) sont repeintes.
        moving, region = set(), QRegion()
        for row, (rect, _index, _current) in enumerate(self._ripple_items):
            opacity, _scale = self.ripple_state(rect)
            if 0.0 < opacity < 1.0:
                moving.add(row)
            if row in moving or row in self._ripple_prev:
                region += QRegion(rect)
        self._ripple_prev = moving
        if not region.isEmpty():
            self.viewport().update(region)

    # -- Taille des vignettes -----------------------------------------------------------------

    def set_tile_size(self, size: float, anchor=None) -> bool:
        """Change la taille des vignettes en gardant sous `anchor` (repere du viewport) la meme
        vignette, au meme endroit. False si deja a la borne."""
        size = int(round(max(self.TILE_MIN, min(self.TILE_MAX, size))))
        if size == self.TILE:
            return False
        # Le tableau change par colonnes entieres : on avance jusqu'au decoupage suivant (sinon un
        # cran de molette ne changerait rien a l'ecran).
        step = 1 if size > self.TILE else -1
        current = self._plan(self.TILE)
        while self._plan(size) == current and self.TILE_MIN < size < self.TILE_MAX:
            size = max(self.TILE_MIN, min(self.TILE_MAX, size + step * max(1, size // 25)))
        if step > 0 and self._can_fill() and not self._shows_all(self._plan(size)):
            # Peu de fichiers : avant de les faire defiler (puis d'entrer dans une image), ils
            # remplissent l'ecran, tous ensemble.
            self._set_filled(True)
            return True
        item = self.itemAt(anchor) if anchor is not None else None
        if item is None:
            item = self.currentItem()
        # La vignette sous le curseur reste sur la meme ligne visible.
        slot = (self._row_of(item) - self.first_visible_row()) if item is not None else 0
        self.TILE = FocusGallery.tile_size = size
        self._tiles.clear()
        self._apply_grid()
        self.doItemsLayout()
        if item is not None:
            self._scroll_to_row(self._row_of(item) - min(slot, self._visible_rows - 1))
        self.viewport().update()
        return True

    def wheelEvent(self, event):
        if event.modifiers() & Qt.ControlModifier:
            delta = event.angleDelta().y()
            anchor = event.position().toPoint()
            if delta > 0 and self.TILE >= self.TILE_MAX and self._can_fill():
                self._zoom_into = 0
                self._set_filled(True)           # tous les fichiers remplissent l'ecran d'abord
            elif delta < 0 and self._filled:
                self._zoom_into = 0
                self._set_filled(False)          # retour a la taille des vignettes
            elif delta > 0 and (self.TILE >= self.TILE_MAX or self._filled):
                # Deja au plus grand (ou l'ecran est rempli) : on « entre » dans la vignette sous le curseur.
                self._zoom_into += delta
                if self._zoom_into >= 240:
                    self._zoom_into = 0
                    item = self.itemAt(anchor) or self.currentItem()
                    if item is not None:
                        self.zoomed_into.emit(Path(item.data(Qt.UserRole)))
            else:
                self._zoom_into = 0
                self.set_tile_size(self.TILE * 1.15 ** (delta / 120), anchor)
            event.accept()
            return
        # Molette : une ligne par cran (lignes visibles toujours calees sur la zone).
        self._wheel_rest += event.angleDelta().y()
        steps = int(self._wheel_rest / 120)
        if steps:
            self._wheel_rest -= steps * 120
            self._set_attr_hover(None)
            self._scroll_to_row(self.first_visible_row() - steps, animate=self.scroll_animated())
        event.accept()

    TEXT_MIN = 10            # hauteur mini de la sous-cellule texte (Ctrl + bordure)
    # Case NON divisee (demande de l'utilisateur) : plus de sous-cellule texte sous l'image, l'image est
    # centree sur toute la case (nom en info-bulle, attributs dessines sur l'image : _paint_attrs).
    SPLIT_CELLS = False

    def label_height(self) -> int:
        """Sous-cellule texte (nom + type et poids, sous l'image) : la hauteur choisie par Ctrl + bordure
        (`viewer_gallery_text_height`, px), sinon de quoi loger les deux lignes dans leurs polices ;
        0 quand la case n'est pas divisee (SPLIT_CELLS)."""
        if not self.SPLIT_CELLS:
            return 0
        import ui_state
        try:
            chosen = int((ui_state.APPLIED_SETTINGS or {}).get("viewer_gallery_text_height") or 0)
        except (TypeError, ValueError):
            chosen = 0
        if chosen > 0:
            return max(self.TEXT_MIN, chosen)
        look = self.film_look
        return (self.LABEL_GAP + QFontMetrics(look["name_font"][0]).height()
                + QFontMetrics(look["rank_font"][0]).height())

    def tile_pixmap(self, path: Path, mtime) -> QPixmap | None:
        """Vignette de `path` a la taille d'une case, tiree d'un PROXY un poil plus grand que la case
        (PROXY_MARGIN) : l'apercu du pipeline (cache de l'inspecteur, 640 px) s'il suffit, sinon une
        version decodee en fond a cette taille (en attendant : l'apercu, agrandi). Sans apercu :
        demande le decodage et rend la petite vignette des colonnes s'il y en a une."""
        key = str(path)
        tile = self._tiles.get(key)
        if tile is not None:
            return tile
        managed = False
        try:
            from lightroom_bridge import is_managed, preview_pixmap
            managed = is_managed(path)
            if managed and mtime is not None:
                preview_pixmap(path, mtime)
        except (ImportError, OSError, ValueError):
            pass
        dpr = self.devicePixelRatioF() or 1.0
        side = round(self._box_side * dpr)
        need = math.ceil(side * PROXY_MARGIN)
        source, enough = None, False
        proxy = _PROXIES.get(key)
        if proxy is not None and (mtime is None or proxy[0] == mtime):
            _PROXIES.move_to_end(key)
            source, enough = proxy[2], proxy[3] or proxy[1] >= need
        cached = previews._file_image_cache.get(key)
        if not enough and cached is not None and (mtime is None or cached[0] == mtime) and not cached[1].isNull():
            preview = cached[1]
            big = max(preview.width(), preview.height()) >= need
            if source is None or (not managed and (big or max(preview.width(), preview.height()) > max(source.width(), source.height()))):
                source, enough = preview, big and not managed
        if not enough and (managed or path.suffix.lower() in IMAGE_EXTENSIONS) and key not in self._proxy_failed:
            self._request_proxy(key, need)
        elif source is not None:
            enough = True                    # rien de mieux a attendre (fichier 3D, image illisible...)
        if source is None:
            return previews.file_image_pixmap(path, asynchronous=True)
        tile = source.scaled(side, side, Qt.KeepAspectRatio, Qt.SmoothTransformation)
        if isinstance(tile, QImage):
            tile = QPixmap.fromImage(tile)
        tile.setDevicePixelRatio(dpr)
        self._tiles[key] = tile
        return tile

    def _request_proxy(self, key: str, need: int) -> None:
        if self._held_proxies is not None:
            self._held_proxies.append((key, need))
            return
        if self._proxy_pending.get(key, 0) >= need:
            return
        mtime = previews.cached_mtime(Path(key))
        if mtime is None:
            return
        try:
            from lightroom_bridge import is_managed, preview_pixmap
            if is_managed(Path(key)):
                preview_pixmap(Path(key), mtime)
        except (ImportError, OSError, ValueError):
            pass
        self._proxy_pending[key] = need
        self._proxy_pool.start(_ProxyTask(self._proxy_signals, key, mtime, need))

    def hideEvent(self, event):
        if self._ripple_timer.isActive():
            self._ripple_timer.stop()
            _fine_timer(False)
            self._ripple_origin = None
        if self._scroll_goal is not None:
            self._scroll_to_row(self._scroll_goal)   # glissement en cours : pose sa fin (lignes calees)
        self._proxy_pool.clear()             # planche refermee : plus de decodage en file
        self._proxy_pending.clear()
        super().hideEvent(event)

    def _on_proxy(self, key: str, mtime: float, side: int, image, full: bool):
        if self._proxy_pending.get(key) == side:
            self._proxy_pending.pop(key, None)
        if image is None:
            self._proxy_failed.add(key)
            return
        fmt = QImage.Format_ARGB32_Premultiplied if image.hasAlphaChannel() else QImage.Format_RGB32
        _store_proxy(key, (mtime, side, image.convertToFormat(fmt), full))
        if self._busy():
            # Pendant l'apparition ou un glissement, une case refaite volerait une image a l'animation :
            # la meilleure vignette remplace la provisoire a la fin (_apply_late_proxies).
            self._late_proxies.add(key)
            return
        self._tiles.pop(key, None)           # la vignette provisoire est refaite depuis le proxy
        _CELLS.pop(key, None)
        for row in range(self.count()):     # seule sa case est repeinte
            item = self.item(row)
            if item.data(Qt.UserRole) == key:
                self.viewport().update(self.visualItemRect(item))
                break

    def keyPressEvent(self, event):
        if event.key() in (Qt.Key_Escape, Qt.Key_G):
            self.closed.emit()
            return
        if event.key() in (Qt.Key_Return, Qt.Key_Enter) and self.currentItem() is not None:
            self.chosen.emit(Path(self.currentItem().data(Qt.UserRole)))
            return
        if event.key() == Qt.Key_I and not event.modifiers():
            self.toggle_keywords()
            return
        super().keyPressEvent(event)

    def toggle_keywords(self):
        """Touche I : mots cles ecrits (ou non) sur les photos de la planche."""
        gallery_paint.SHOW_KEYWORDS = not gallery_paint.SHOW_KEYWORDS   # lu par le délégué (gallery_paint)
        _CELLS.clear()
        _MARKED.clear()
        self.viewport().update()
