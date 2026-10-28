"""Attributs des fichiers dans l'interface : étoiles, couleurs, drapeaux, éditeur, fenêtre des mots clés.

Découpé de focus.py (2026-10-28) ; carte : docs/agents/fm_visionneuse.md."""
from pathlib import Path
from typing import TYPE_CHECKING

from PySide6.QtCore import QEvent, QObject, QPoint, QPointF, QSize, Qt, Signal
from PySide6.QtGui import QColor, QPainter, QPen, QTextCursor
from PySide6.QtWidgets import QApplication, QWidget

from app_style import scaled
import previews

from .loader import display_name

if TYPE_CHECKING:
    from .gallery import FocusGallery


def filter_colors() -> list[tuple[str, str]]:
    """(nom, couleur) des 5 couleurs de Reglages > Visionneuse > Filtres (couleurs de l'appli resolues)."""
    import ui_state
    from app_style import resolve_color_ref
    from settings_store import DEFAULT_SETTINGS
    settings = ui_state.APPLIED_SETTINGS or DEFAULT_SETTINGS
    out = []
    for n in range(1, 6):
        name = str(settings.get(f"viewer_filter_color_{n}_name") or DEFAULT_SETTINGS[f"viewer_filter_color_{n}_name"])
        color = settings.get(f"viewer_filter_color_{n}") or DEFAULT_SETTINGS[f"viewer_filter_color_{n}"]
        out.append((name, resolve_color_ref(color)))
    return out


class _StarRating(QWidget):
    """Note de 0 a 5 : clic sur une etoile = cette note, re-clic sur la note en cours = aucune ; survol =
    apercu de la note visee. Couleur de selection des tableaux pour les etoiles allumees."""

    changed = Signal(int)
    COUNT = 5

    def __init__(self, parent=None):
        super().__init__(parent)
        self._value, self._hover = 0, 0
        self._step = scaled(20)
        self.setFixedSize(self._step * self.COUNT, scaled(20))
        self.setMouseTracking(True)
        self.setCursor(Qt.PointingHandCursor)

    def value(self) -> int:
        return self._value

    def setValue(self, value: int):
        self._value = max(0, min(self.COUNT, int(value)))
        self.update()

    def _star_at(self, x: float) -> int:
        return max(1, min(self.COUNT, int(x // self._step) + 1))

    def mouseMoveEvent(self, event):
        star = self._star_at(event.position().x())
        if star != self._hover:
            self._hover = star
            self.update()

    def leaveEvent(self, event):
        self._hover = 0
        self.update()

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            star = self._star_at(event.position().x())
            self.setValue(0 if star == self._value else star)
            self.changed.emit(self._value)

    def paintEvent(self, event):
        import math
        from PySide6.QtGui import QPolygonF
        from settings_store import M
        from settings_widgets import _selection_color
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing, True)
        lit = _selection_color(255)
        off = QColor(M["field_border"])
        shown = self._hover or self._value
        radius = self.height() * 0.42
        for i in range(self.COUNT):
            cx, cy = self._step * i + self._step / 2, self.height() / 2
            points = [QPointF(cx + (radius if k % 2 == 0 else radius * 0.45) * math.sin(k * math.pi / 5),
                              cy - (radius if k % 2 == 0 else radius * 0.45) * math.cos(k * math.pi / 5))
                      for k in range(10)]
            on = i < shown
            color = QColor(lit if on else off)
            if on and self._hover and i >= self._value:
                color.setAlpha(150)                     # apercu de survol
            p.setPen(QPen(color, 1.2))
            p.setBrush(color if on else Qt.NoBrush)
            p.drawPolygon(QPolygonF(points))
        p.end()


class _ColorLabels(QWidget):
    """Les 5 couleurs de Reglages > Visionneuse > Filtres en pastilles : clic = cette couleur, re-clic sur
    la couleur en cours = aucune ; nom en info-bulle. `multi` (fenetre des filtres) : chaque clic allume /
    eteint sa couleur, plusieurs a la fois (`values`)."""

    changed = Signal(int)

    def __init__(self, parent=None, multi: bool = False):
        super().__init__(parent)
        self._value, self._colors = 0, filter_colors()
        self._multi, self._chosen = multi, set()
        self._step = scaled(22)
        self.setFixedSize(self._step * len(self._colors), scaled(20))
        self.setMouseTracking(True)
        self.setCursor(Qt.PointingHandCursor)

    def value(self) -> int:
        return self._value

    def setValue(self, value: int):
        self._value = max(0, min(len(self._colors), int(value)))
        self.update()

    def values(self) -> list[int]:
        return sorted(self._chosen)

    def setValues(self, values):
        self._chosen = {int(v) for v in values or [] if 1 <= int(v) <= len(self._colors)}
        self.update()

    def refresh_colors(self):
        self._colors = filter_colors()
        self.update()

    def _index_at(self, x: float) -> int:
        return max(1, min(len(self._colors), int(x // self._step) + 1))

    def mouseMoveEvent(self, event):
        index = self._index_at(event.position().x())
        self.setToolTip(self._colors[index - 1][0])

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            index = self._index_at(event.position().x())
            if self._multi:
                self._chosen ^= {index}
                self.update()
                self.changed.emit(index)
                return
            self.setValue(0 if index == self._value else index)
            self.changed.emit(self._value)

    def paintEvent(self, event):
        from settings_store import M
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing, True)
        size = self.height() * 0.62
        chosen_set = self._chosen if self._multi else ({self._value} if self._value else set())
        for i, (_name, color) in enumerate(self._colors):
            center = QPointF(self._step * i + self._step / 2, self.height() / 2)
            chosen = i + 1 in chosen_set
            if chosen:                                    # anneau autour de la couleur choisie
                p.setPen(QPen(QColor(M["value_fg"]), 1.6))
                p.setBrush(Qt.NoBrush)
                p.drawEllipse(center, size / 2 + 3, size / 2 + 3)
            fill = QColor(color)
            if not chosen and chosen_set:
                fill.setAlphaF(fill.alphaF() * 0.45)      # les autres s'effacent
            p.setPen(Qt.NoPen)
            p.setBrush(fill)
            p.drawEllipse(center, size / 2, size / 2)
        p.end()


class _StatusFlags(QWidget):
    """Trois actions directes pour le statut Lightroom : neutre, garder, rejeter."""

    changed = Signal(str)
    ICONS = {
        "keep": (r"F:\SYNC\Sync\IMAGES\ico\PNG\coche_01.png", "Marquée"),
        "delete": (r"F:\SYNC\Sync\IMAGES\ico\PNG\croix_01.png", "Rejetée"),
        "": (r"F:\SYNC\Sync\IMAGES\ico\PNG\moins_01.png", "Neutre"),
    }

    def __init__(self, parent=None):
        super().__init__(parent)
        from PySide6.QtGui import QIcon
        from PySide6.QtWidgets import QButtonGroup, QHBoxLayout, QToolButton

        self._buttons = {}
        self._group = QButtonGroup(self)
        self._group.setExclusive(True)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(scaled(5))
        for value, (path, label) in self.ICONS.items():
            button = QToolButton(self)
            button.setCheckable(True)
            button.setAutoRaise(True)
            button.setToolTip(label)
            custom = {"keep": previews.UI_ICON_VIEWER_FLAG_KEEP,
                      "delete": previews.UI_ICON_VIEWER_FLAG_DELETE}.get(value)
            custom_pix = previews.custom_ui_icon_pixmap(custom, scaled(48)) if custom else None
            button.setIcon(QIcon(custom_pix) if custom_pix is not None else QIcon(path))
            button.setIconSize(QSize(scaled(24), scaled(24)))
            button.setFixedSize(scaled(32), scaled(30))
            button.setStyleSheet(
                "QToolButton { border: 1px solid transparent; border-radius: 3px; padding: 2px; }"
                "QToolButton:checked { border-color: #55aaff; background: rgba(85,170,255,45); }"
            )
            button.clicked.connect(lambda _checked=False, status=value: self.changed.emit(status))
            self._group.addButton(button)
            self._buttons[value] = button
            layout.addWidget(button)
        self.setValue("")

    def setValue(self, value: str):
        self._buttons.get(value, self._buttons[""]).setChecked(True)


class FileAttributesEditor(QObject):
    """Lignes « Attributs » du tableau de la visionneuse (demande de l'utilisateur) : note, couleur,
    j'aime, mots cles, statut du fichier EN FOCUS ; chaque changement est enregistre aussitot
    (file_attributes). Champs = briques des reglages (toggle, zone de saisie, liste) + etoiles / pastilles."""

    STATUS_LABELS = (("", "Neutre"), ("keep", "Marquée"), ("delete", "Rejetée"))
    TITLE = "Attributs"

    def __init__(self, parent: QWidget):
        super().__init__(parent)
        self._path: Path | None = None
        self._loading = False
        self.rows: list = []
        self.on_saved = None                       # rappel (chemin, changements) apres chaque enregistrement

    def build_rows(self) -> list:
        """(libelle, champ, None) pour _flat_cells_table — champs neufs (le tableau est reconstruit)."""
        from settings_cells import _WordsField
        from settings_widgets import _Toggle
        self.stars = _StarRating()
        self.colors = _ColorLabels()
        # Mots cles : saisis a la volee, separes par des espaces, autocompletion des mots deja employes.
        from fm_visionneuse import file_attributes
        self.keywords = _WordsField(suggestions=file_attributes.known_keywords, width=scaled(150))
        self.keywords.setPlaceholderText("ciel nuit ville…")
        self.status = _StatusFlags()
        self.stars.changed.connect(lambda v: self._save(rating=v))
        self.colors.changed.connect(lambda v: self._save(color=v))
        self.keywords.editingFinished.connect(self._save_keywords)      # Entree / sortie du champ
        self.status.changed.connect(lambda value: self._save(status=value))
        self.rows = [("Note (0–5)", self.stars, None), ("Libellé de couleur", self.colors, None),
                     ("Drapeau", self.status, None), ("Mots clés", self.keywords, None)]
        self._load()
        return self.rows

    def set_path(self, path: Path | None, values: dict | None = None):
        """`values` : attributs deja connus (memoire de la planche) ; sinon lus (file_attributes.get)."""
        if self.rows and self._path is not None and path != self._path:
            self._save_keywords()                  # mots en cours de saisie : pas perdus
        self._path = path
        self._load(values)

    def _load(self, known: dict | None = None):
        from fm_visionneuse import file_attributes
        if not self.rows:
            return
        if not file_attributes.eligible(self._path):
            values = dict(file_attributes.DEFAULTS)
        elif known is not None:
            values = file_attributes.values_of(known)
        else:
            values = file_attributes.get(self._path)
        self._loading = True
        try:
            for control in (self.stars, self.colors, self.keywords, self.status):
                control.setEnabled(True)
            self.stars.setValue(values["rating"])
            self.colors.setValue(values["color"])
            self.keywords.set_words(values["keywords"])
            self._loaded_keywords = list(values["keywords"])
            self.status.setValue(values["status"])
        except RuntimeError:                       # champs detruits (tableau reconstruit)
            pass
        finally:
            self._loading = False

    def _save(self, **changes):
        from fm_visionneuse import file_attributes
        if self._loading or not file_attributes.eligible(self._path):
            return
        file_attributes.update(self._path, **changes)
        if "keywords" in changes:
            self._loaded_keywords = list(changes["keywords"])
        if self.on_saved is not None:
            self.on_saved(self._path, changes)

    def _save_keywords(self):
        from fm_visionneuse import file_attributes
        try:
            words = self.keywords.words()
        except RuntimeError:
            return
        if self._path is not None and file_attributes.eligible(self._path) \
                and words != self._shown_keywords():
            self._save(keywords=words)

    def _shown_keywords(self) -> list:
        """Mots cles du fichier avant la saisie (ceux charges dans le champ, ou les derniers enregistres)."""
        return list(getattr(self, "_loaded_keywords", None) or [])


class KeywordsWindow(QWidget):
    """Fenetre des mots cles d'une photo (bouton « + » de sa case) : UN MOT CLE PAR LIGNE (demande de
    l'utilisateur ; un mot cle peut contenir des espaces), zone de saisie des reglages
    (`settings_cells._LinesField`) avec autocompletion des mots deja employes ; elle contient les mots
    cles actuels — en ajouter une ligne, en effacer. Clic ailleurs ou Ctrl + Entree = enregistrer et fermer,
    Echap = fermer sans rien changer. Cadre de panneau des reglages (`_PanelFrame`). Le bouton « + » la
    rouvre a chaque fois (la reference est lachee a la fermeture)."""

    saved = Signal(list)
    closed = Signal(object)

    def __init__(self, gallery: "FocusGallery", key: str, words: list):
        super().__init__(gallery.window(), Qt.Tool | Qt.FramelessWindowHint)
        from PySide6.QtWidgets import QVBoxLayout
        from settings_cells import _LinesField
        from settings_store import M
        from settings_theme import _text_label
        from settings_window import _PanelFrame
        from fm_visionneuse import file_attributes
        self.setAttribute(Qt.WA_DeleteOnClose)
        self.key = key
        self._done = False
        self._filtered = False
        frame = _PanelFrame(self)
        frame.setColors(M["panel_bg"], M["panel_border"])
        frame.setRadius(scaled(5))
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.addWidget(frame)
        box = QVBoxLayout(frame)
        m = scaled(10)
        box.setContentsMargins(m, m, m, m)
        box.setSpacing(scaled(6))
        title = _text_label(f"Mots clés — {display_name(Path(key))}", "row_label")
        title.setWordWrap(False)
        box.addWidget(title)
        self.field = _LinesField(words, suggestions=file_attributes.known_keywords, width=scaled(300))
        self.field.setPlaceholderText("un mot clé par ligne")
        self.field.submitted.connect(self._accept)
        self.field.textChanged.connect(self._fit)
        box.addWidget(self.field)
        hint = _text_label("Ctrl+Entrée ou clic ailleurs : enregistrer · Échap : annuler", "row_label")
        hint.setWordWrap(True)
        box.addWidget(hint)
        self.setFixedWidth(scaled(340))
        self.adjustSize()

    def _fit(self):
        self.field.fit_rows()
        self.adjustSize()

    def popup_near(self, global_pos: QPoint):
        screen = QApplication.screenAt(global_pos) or QApplication.primaryScreen()
        area = screen.availableGeometry()
        x = min(max(area.left(), global_pos.x() - self.width()), area.right() - self.width())
        y = min(max(area.top(), global_pos.y() - self.height() - scaled(8)), area.bottom() - self.height())
        self.move(x, y)
        self.show()
        self.raise_()
        self.field.setFocus()
        self.field.moveCursor(QTextCursor.End)
        QApplication.instance().installEventFilter(self)

    def _accept(self):
        if self._done:
            return
        self._done = True
        self.saved.emit(self.field.lines())
        self.close()

    def keyPressEvent(self, event):
        if event.key() == Qt.Key_Escape:
            self._done = True
            self.close()
            return
        super().keyPressEvent(event)

    def _is_inside(self, global_pos: QPoint) -> bool:
        """Le point (global) est dans cette fenetre ou dans la liste de propositions du champ."""
        widget = QApplication.widgetAt(global_pos)
        if widget is None:
            return False
        popup = self.field.completer_.popup()
        return (widget is self or self.isAncestorOf(widget)
                or (popup is not None and (widget is popup or popup.isAncestorOf(widget))))

    def eventFilter(self, obj, event):
        # « Clic ailleurs » = enregistrer et fermer. Jugé sur le widget SOUS LE CURSEUR, jamais sur `obj` : pour
        # une fenetre, le filtre d'application recoit aussi le clic au niveau de la fenetre native (pas un
        # QWidget), pris a tort pour un clic exterieur — la fenetre se fermait des qu'on cliquait dedans
        # (signale : impossible d'entrer un nouveau mot cle).
        if event.type() == QEvent.MouseButtonPress and not self._done:
            if not self._is_inside(event.globalPosition().toPoint()):
                self._accept()
        return False

    def closeEvent(self, event):
        QApplication.instance().removeEventFilter(self)
        self.closed.emit(self)
        super().closeEvent(event)
