"""Changement de style a la volee : fenetre flottante REUTILISABLE pour regler le style d'un element
de l'interface (police, padding...) en le regardant changer, sans ouvrir les reglages.

Un tableau fait avec les briques de la fenetre de reglages v2 (lignes du CATALOG : memes champs, memes
gabarits), applique en direct (signal `styleChanged`, dict de valeurs) ; c'est l'appelant qui
enregistre le style lui-meme. La fenetre, elle, retient seule sa mise en forme, comme tout tableau de
la v2 : largeurs de colonnes et de sous-cellules, hauteurs de lignes, justifications, ordre
(`table_dims`, cle `Changement de style à la volée/<nom>#0`) et plages des curseurs (`slider_ranges`).
Le tableau est contraint a droite par la fenetre (meme marge sur les 4 cotes) : tirer un bord gauche /
droit de la fenetre change la largeur de sa derniere colonne (enregistree avec le tableau), elargir une
colonne elargit la fenetre.

Usage : `QuickStyleWindow(nom, specs, valeurs, titre=..., settings=...)`, `specs` = lignes du tableau
(`font_padding_specs(prefixe)` pour le cas courant Police | Padding ; une ligne peut aussi etre
`(libelle, champ, lecteur)` : champ fait des briques des reglages, fourni par l'appelant — filtres de la
planche). Premier usage : style d'un titre
pose au-dessus d'une ligne de colonne (column.py). Ne depend d'aucun code propre a l'appli."""
from __future__ import annotations

import time

from PySide6.QtCore import QEvent, QPoint, Qt, QTimer, Signal
from PySide6.QtGui import QCursor, QGuiApplication
from PySide6.QtWidgets import QDialog, QFrame, QHBoxLayout, QScrollArea, QVBoxLayout, QWidget

import settings_window_v2 as v2
from app_style import apply_dwm_frame, resize_hit_test
from settings_cells import normalize_toggles
from settings_store import M, load_settings, save_live_state, save_settings
from settings_widgets import _TABLE_DIMS, toggle_animation_left_ms
from settings_window import _PanelFrame, _SettingsTitleBar, chrome_size, install_extra_window, shadow_margins

NAME = "Changement de style à la volée"


def font_padding_specs(prefix: str, size=(6, 48), size_default: int = 10, color_default: str = "#d6d9dc",
                       color_title: str = "Couleur du texte") -> tuple:
    """Lignes Police | Padding : cles `<prefix>_font_*` (police, gras, italique, hauteur, lissage,
    couleur) et `<prefix>_padding` (+ `<prefix>_padding_linked`)."""
    return (
        v2.Spec(f"{prefix}_font_family", "Police", "font_gabarit", "",
                {"prefix": prefix, "size": size, "size_default": size_default, "color_default": color_default,
                 "color_title": color_title},
                extra_keys=tuple(f"{prefix}_font_{k}" for k in
                                 ("bold", "italic", "size", "smoothing_enabled", "smoothing", "color"))),
        v2.Spec(f"{prefix}_padding", "Padding", "padding", {}, {"linked_default": False}),
    )


# Place de chaque fenetre a sa fermeture, {nom: [x, y]} (copie de `quick_style_positions`).
_POSITIONS: dict = {}


class QuickStyleWindow(QDialog):
    """Fenetre outil sans cadre, non modale (habillage des reglages). `name` distingue chaque usage
    (sa mise en forme est retenue a part) ; `values` : valeurs de depart des lignes ; `settings` :
    reglages pour l'habillage et les couleurs (defaut : ceux du disque)."""

    styleChanged = Signal(dict)

    _RESIZE_BORDER = 6
    _SAVE_DELAY = 400
    MARGIN = 16          # meme marge sur les 4 cotes du tableau (demande de l'utilisateur)

    def __init__(self, name: str, specs, values: dict, title: str = "", settings: dict | None = None,
                 parent=None):
        super().__init__(parent)
        self.name = name
        self.setWindowFlags(Qt.Tool | Qt.FramelessWindowHint)
        # Fenetre additionnelle (Reglages > Fenetres additionnelles) : TRANSPARENTE, panneau arrondi et ombre
        # peints (choix de l'utilisateur, malgre un risque de clignotement au redimensionnement).
        self.setAttribute(Qt.WA_DeleteOnClose, True)
        settings = settings or load_settings()
        if name.startswith('Module vidéo'):
            from fm_video.help_ui import HelpController
            self._color_help = HelpController(self, settings)
        v2.seed_window_look(settings)
        self._dims_key = f"{NAME}/{name}#0"
        for key, pos in (settings.get("quick_style_positions") or {}).items():
            _POSITIONS.setdefault(key, pos)      # les places enregistrees ici d'abord (plus recentes)
        saved = (settings.get("table_dims") or {}).get(self._dims_key)
        if saved:
            _TABLE_DIMS[self._dims_key] = saved      # repris par le tableau a son premier affichage
        values = dict(values)
        values.setdefault("colors", settings.get("colors") or {})
        values["slider_ranges"] = settings.get("slider_ranges") or {}
        scope = v2.ScopeValues(values, None)
        # Une ligne = un `Spec` du CATALOG, ou (libelle, champ, lecteur) fourni par l'appelant (champ fait des
        # briques des reglages, `lecteur(champ) -> dict`, signal de changement reconnu par _connect_changed).
        self._fields = []                    # (Spec, champ)
        self._rows = []                      # (libelle, champ, lecteur), toutes les lignes
        for item in specs:
            if isinstance(item, v2.Spec):
                widget = v2.make_field(item, scope, values["colors"], self._on_range)
                self._fields.append((item, widget))
                self._rows.append((item.label, widget, lambda w, sp=item: v2.read_spec(sp, w)))
            else:
                self._rows.append(tuple(item))
        # Une ligne fournie par l'appelant peut porter un 4e element : l'interrupteur d'override, pose dans la 1re
        # colonne AVANT le libelle (il grise la ligne quand il est eteint).
        self.table = v2._flat_cells_table([(row[0], row[1], row[3] if len(row) > 3 else None) for row in self._rows])
        self.table._dims_key = self._dims_key
        normalize_toggles(self.table)
        for row in self._rows:
            v2._connect_changed(row[1], self._emit)
            if len(row) > 3 and row[3] is not None:
                v2._connect_changed(row[3], self._emit)
        self._dims_timer = QTimer(self)
        self._dims_timer.setSingleShot(True)
        self._dims_timer.setInterval(self._SAVE_DELAY)
        self._dims_timer.timeout.connect(self._save_dims)
        self.table.dimsChanged.connect(self._dims_timer.start)

        panel = _PanelFrame(self)
        panel.setColors(M["panel_bg"], M["panel_border"])
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.addWidget(panel)
        root = QVBoxLayout(panel)
        root.setContentsMargins(1, 1, 1, 1)
        root.setSpacing(0)
        bar = self.titlebar = _SettingsTitleBar(self, title=title or NAME)
        bar.dirty_label.hide()               # applique en direct : rien « a enregistrer »
        bar.closeClicked.connect(self.close)
        root.addWidget(bar)
        # Le tableau est CONTRAINT a droite par la fenetre (demande de l'utilisateur) : tirer un bord de la
        # fenetre elargit / retrecit sa derniere colonne, elargir une colonne elargit la fenetre ; meme
        # marge sur les 4 cotes.
        inner = QWidget()
        inner.setStyleSheet("background: transparent;")
        inner_l = QHBoxLayout(inner)
        m = self.MARGIN
        inner_l.setContentsMargins(m, m, m, m)
        inner_l.addWidget(self.table, 0, Qt.AlignLeft | Qt.AlignTop)
        self.scroller = QScrollArea()
        self.scroller.setFrameShape(QFrame.NoFrame)
        self.scroller.setStyleSheet("QScrollArea { background: transparent; }")
        self.scroller.viewport().setStyleSheet("background: transparent;")
        self.scroller.setWidgetResizable(True)
        self.scroller.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.scroller.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.scroller.setWidget(inner)
        inner.installEventFilter(self)       # le tableau change de taille : la hauteur suit
        self.table.installEventFilter(self)  # ... et la fenetre suit sa largeur
        root.addWidget(self.scroller)
        self._binding = False
        # Recalcul de la hauteur / largeur mini : UN par passage de la boucle (un redimensionnement en
        # envoie un par pas), minuteur de la fenetre (detruit avec elle : plus d'appel apres fermeture).
        self._fit_timer = QTimer(self)
        self._fit_timer.setSingleShot(True)
        self._fit_timer.setInterval(0)
        self._fit_timer.timeout.connect(self._fit_height)
        self._column = None                  # (entete, derniere colonne) en cache (_last_column)
        head, _resizer = self.table._dims_children()
        if head is not None and hasattr(head, "columnMoved"):
            head.columnMoved.connect(lambda: setattr(self, "_column", None))
        install_extra_window(self, panel, outer, root, bar)
        self._fit_height()
        self.resize(self._natural_width(), self.height())

    def _on_chrome_changed(self):
        """Cadre change (bordure, ombre, barre de titre) : taille recalee sur le contenu."""
        if hasattr(self, "_fit_timer"):
            self._fit_height()
            self._window_to_table()

    # -- taille : largeur libre (bords gauche/droit), hauteur = contenu --

    def _natural_width(self) -> int:
        """Fenetre = tableau + marges + cadre (bordure du panneau, marge de l'ombre)."""
        return self.table.width() + 2 * self.MARGIN + chrome_size(self)[0]

    def _last_column(self):
        """(entete, colonne LOGIQUE affichee la plus a droite) : c'est elle qui suit la fenetre. En cache
        (la chercher parcourt tout le tableau : ~3 ms, plusieurs fois par pas de redimensionnement) ;
        oublie quand une colonne est deplacee."""
        if self._column is not None:
            return self._column
        head, _resizer = self.table._dims_children()
        if head is None or not head._widths:
            return None, None
        order = head.order() if hasattr(head, "order") else list(range(len(head._widths)))
        self._column = (head, (order[-1] if order else len(head._widths) - 1))
        return self._column

    def _table_to_window(self):
        """Fenetre retaillee a la main : la derniere colonne prend la difference (jamais sous son minimum)."""
        head, last = self._last_column()
        if head is None or self._binding:
            return
        target = self.width() - 2 * self.MARGIN - chrome_size(self)[0]
        delta = target - self.table.width()
        if not delta:
            return
        width = max(head._FREE_MIN, head._widths[last] + delta)
        self._binding = True
        try:
            head._set_width(last, width)
        finally:
            self._binding = False

    def _window_to_table(self):
        """Le tableau a change de largeur (colonne tiree, restauration) : la fenetre suit."""
        if self._binding:
            return
        width = self._natural_width()
        if width != self.width():
            self._binding = True
            try:
                self.resize(width, self.height())
            finally:
                self._binding = False

    def _min_window_width(self) -> int:
        head, last = self._last_column()
        if head is None:
            return 160
        others = sum(w for i, w in enumerate(head._widths) if i != last)
        frame_m = self.table.layout().contentsMargins()
        return others + head._FREE_MIN + frame_m.left() + frame_m.right() + 2 * self.MARGIN + chrome_size(self)[0]

    def _fit_height(self):
        inner = self.scroller.widget()
        bar = self.scroller.horizontalScrollBar()
        needs_bar = inner.minimumSizeHint().width() > self.scroller.viewport().width()
        height = inner.sizeHint().height() + (bar.sizeHint().height() if needs_bar else 0)
        self.scroller.setFixedHeight(height)
        # Hauteur REELLE de la barre de titre (sa hauteur minimale ; son sizeHint est plus petit : il manquait
        # 8 px en bas, marge basse plus petite que les autres).
        bar = max(self.titlebar.sizeHint().height(), self.titlebar.minimumHeight())
        self.setFixedHeight(bar + height + chrome_size(self)[1])
        self.setMinimumWidth(self._min_window_width())
        self.setMaximumWidth(16777215)
        if time.monotonic() < self._center_until:
            self._center_on_screen()

    def _restore_position(self) -> bool:
        """Rouvre LA OU ELLE ETAIT a sa fermeture (demande de l'utilisateur ; `quick_style_positions`), si
        cette place est encore sur un ecran ; sinon (premiere ouverture, ecran retire) : centree."""
        pos = _POSITIONS.get(self.name)
        if not pos:
            return False
        point = QPoint(int(pos[0]), int(pos[1]))
        if QGuiApplication.screenAt(point + QPoint(40, 12)) is None:     # la barre de titre doit etre visible
            return False
        self.move(point)
        return True

    def _save_position(self):
        pos = self.pos()
        if _POSITIONS.get(self.name) == [pos.x(), pos.y()]:
            return
        _POSITIONS[self.name] = [pos.x(), pos.y()]
        save_live_state("quick_style_positions", dict(_POSITIONS))

    def _center_on_screen(self):
        """Centree sur l'ecran EN COURS (celui du curseur ; demande de l'utilisateur) a son ouverture — et
        recentree tant que sa taille se pose (premieres mises en page)."""
        screen = QGuiApplication.screenAt(QCursor.pos()) or self.screen() or QGuiApplication.primaryScreen()
        if screen is None:
            return
        area = screen.availableGeometry()
        frame = self.frameGeometry()
        self.move(area.center().x() - frame.width() // 2, area.center().y() - frame.height() // 2)

    def eventFilter(self, obj, event):
        if obj is self.scroller.widget() and event.type() == QEvent.LayoutRequest:
            self._fit_timer.start()
        elif obj is self.table and event.type() == QEvent.Resize:
            self._window_to_table()
        return super().eventFilter(obj, event)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if not self._binding and event.oldSize().width() > 0 and event.size().width() != event.oldSize().width():
            self._table_to_window()
        self._fit_timer.start()

    _center_until = 0.0

    def showEvent(self, event):
        super().showEvent(event)
        if not event.spontaneous() and not getattr(self, "_centered_once", False):
            self._centered_once = True
            if not self._restore_position():
                self._center_until = time.monotonic() + 0.5
                self._center_on_screen()
            self._fit_timer.start()
        apply_dwm_frame(self, 0, "none", resizable=True)     # cadre et ombre peints (fenetre additionnelle)

    def nativeEvent(self, eventType, message):
        if eventType == b"windows_generic_MSG":
            result = resize_hit_test(self, message, self._RESIZE_BORDER, shadow_margins(self))
            if result is not None and result[1] in (10, 11):      # bords GAUCHE / DROIT seulement
                return result
        return super().nativeEvent(eventType, message)

    # -- enregistrement automatique de la mise en forme --

    def _save_dims(self):
        """Dimensions du tableau (largeurs, hauteurs, justifications, ordre) : sur le disque aussitot,
        sans toucher au reste des reglages."""
        dims = self.table.collectDims()
        _TABLE_DIMS[self._dims_key] = dims
        settings = load_settings()
        all_dims = dict(settings.get("table_dims") or {})
        all_dims[self._dims_key] = dims
        settings["table_dims"] = all_dims
        save_settings(settings)

    def _on_range(self, key: str, low: int, high: int):
        settings = load_settings()
        ranges = dict(settings.get("slider_ranges") or {})
        ranges[key] = [low, high]
        settings["slider_ranges"] = ranges
        save_settings(settings)

    def closeEvent(self, event):
        if self._dims_timer.isActive():
            self._dims_timer.stop()
            self._save_dims()
        if getattr(self, "_centered_once", False):
            self._save_position()
        super().closeEvent(event)

    # -- valeurs --

    def style(self) -> dict:
        out = {}
        for row in self._rows:
            out.update(row[2](row[1]))
        return out

    def _emit(self):
        # Bascule de toggle en cours : l'appelant (enregistrement, restylage) attend sa fin, sinon
        # l'animation se fige.
        left = toggle_animation_left_ms()
        if left > 0:
            if not hasattr(self, "_emit_timer"):
                self._emit_timer = QTimer(self)
                self._emit_timer.setSingleShot(True)
                self._emit_timer.timeout.connect(self._emit)
            self._emit_timer.start(left + 8)
            return
        self.styleChanged.emit(self.style())
