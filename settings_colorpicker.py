from PySide6.QtCore import (
    QEvent, QMimeData, QObject, Qt, Signal,
)
from PySide6.QtGui import (
    QColor,
    QDrag,
    QPainter,
    QPixmap,
)
from PySide6.QtWidgets import (
    QApplication,
    QHBoxLayout,
    QWidget,
)
from settings_store import (
    M,
)
from settings_widgets import (
    DRAG_GHOST_OPACITY,
    _ColorPickerPopup,
    _ColorSwatchButton,
    _qfont,
)


# -- Glisser une pastille sur une autre = lui copier sa couleur (demande de l'utilisateur : dans TOUS les
# tableaux, section Couleurs comprise). Format commun a toutes les pastilles des reglages : la valeur
# complete (« @pastille/75 » ou « #hex »). La pastille tiree suit le curseur a DRAG_GHOST_OPACITY, la
# pastille visee s'entoure de l'accent ; sans mouvement, le clic garde son sens (menu / selecteur). --

COLOR_MIME = "application/x-pipeline-color"


class _ColorDragFilter(QObject):
    def __init__(self, swatch, get_value, receive):
        super().__init__(swatch)
        self.swatch, self.get_value, self.receive = swatch, get_value, receive
        self._press = None

    def eventFilter(self, obj, event):
        kind = event.type()
        if kind == QEvent.MouseButtonPress and event.button() == Qt.LeftButton:
            self._press = event.position().toPoint()
        elif kind == QEvent.MouseMove and self._press is not None and event.buttons() & Qt.LeftButton:
            if (event.position().toPoint() - self._press).manhattanLength() >= QApplication.startDragDistance():
                self._start()
                return True
        elif kind == QEvent.MouseButtonRelease:
            self._press = None
        elif kind == QEvent.DragEnter:
            if event.mimeData().hasFormat(COLOR_MIME) and event.source() is not self.swatch:
                event.acceptProposedAction()
                self.swatch.set_drop_hover(True)
            else:
                event.ignore()
            return True
        elif kind == QEvent.DragLeave:
            self.swatch.set_drop_hover(False)
        elif kind == QEvent.Drop:
            self.swatch.set_drop_hover(False)
            if event.mimeData().hasFormat(COLOR_MIME):
                event.acceptProposedAction()
                self.receive(bytes(event.mimeData().data(COLOR_MIME)).decode("utf-8"))
            return True
        return False

    def _start(self):
        press, self._press = self._press, None
        self.swatch.setDown(False)
        mime = QMimeData()
        mime.setData(COLOR_MIME, str(self.get_value()).encode("utf-8"))
        grab = self.swatch.grab()
        ghost = QPixmap(grab.size())
        ghost.setDevicePixelRatio(grab.devicePixelRatio())
        ghost.fill(Qt.transparent)
        painter = QPainter(ghost)
        painter.setOpacity(DRAG_GHOST_OPACITY)
        painter.drawPixmap(0, 0, grab)
        painter.end()
        drag = QDrag(self.swatch)
        drag.setMimeData(mime)
        drag.setPixmap(ghost)
        drag.setHotSpot(press)
        drag.exec(Qt.CopyAction)
        self.swatch.setDown(False)


def attach_color_drag(swatch, get_value, receive) -> None:
    """Pastille `swatch` : tirable (sa valeur `get_value()`) et cible d'un depot (`receive(valeur)`)."""
    swatch.setAcceptDrops(True)
    swatch._color_drag = _ColorDragFilter(swatch, get_value, receive)
    swatch.installEventFilter(swatch._color_drag)


def plain_color(value: str) -> str:
    """Valeur deposee rendue en couleur LIBRE (pastille de la palette, section Couleurs) : une couleur de
    l'appli « @pastille/75 » est resolue ; opaque = « #rrggbb »."""
    from app_style import resolve_color_ref
    color = QColor(resolve_color_ref(value) if str(value).startswith("@") else value)
    if not color.isValid():
        return ""
    return color.name() if color.alpha() == 255 else color.name(QColor.NameFormat.HexArgb)


class _ColorField(QWidget):
    """Pastille cliquable (ouvre _ColorPickerPopup) + boite hexadecimale."""

    changed = Signal(str)

    def __init__(self, value: str, swatch_size: int = 24, title: str = "Couleur", parent=None):
        super().__init__(parent)
        self._value = value
        self._title = title
        self._before_pick = value
        self._popup: _ColorPickerPopup | None = None
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(10)
        self.swatch = _ColorSwatchButton()
        self.swatch.setFixedSize(swatch_size, swatch_size)
        self.swatch.clicked.connect(self._pick)
        layout.addWidget(self.swatch)
        attach_color_drag(self.swatch, self.value, self._receive_color)   # glisser = copier la couleur
        self._refresh()

    def _receive_color(self, value: str):
        """Couleur deposee : prise comme un choix (apercu en direct, enregistrement)."""
        hexval = plain_color(value)
        if hexval and hexval != self._value:
            self._apply_live(hexval)

    def _refresh(self):
        # damier + couleur (avec alpha) peints a la main, voir
        # _ColorSwatchButton — border-radius FIXE (2px, jamais suivi le
        # slider Geometrie > Tableaux/Zones de saisie — voir la remarque de
        # l'utilisateur, capture a l'appui) : juste un adoucissement
        # discret du carre, pas un reglage, deja fige dans cette classe.
        self.swatch.setColorHex(self._value)

    def _pick(self):
        self._before_pick = self._value
        popup = _ColorPickerPopup(self._value, self._title, self)
        self._popup = popup
        # colorChanged (glisser un slider/le carre) ET committed (Valider,
        # ou un clic dehors — voir _ColorPickerPopup.closeEvent) suivent
        # le MEME chemin : appliquer tout de suite, en direct sur la
        # fenetre principale (voir SettingsWindow._on_colors_changed, qui
        # lit self._value via value() a chaque signal changed). cancelled
        # (Annuler/croix) restaure la valeur de depart par le meme chemin.
        popup.colorChanged.connect(self._apply_live)
        popup.committed.connect(self._apply_live)
        popup.cancelled.connect(lambda: self._apply_live(self._before_pick))
        popup.show_near(self.swatch)

    def _apply_live(self, hexval: str):
        self._value = hexval
        self._refresh()
        self.changed.emit(self._value)

    def value(self) -> str:
        return self._value

    def setValue(self, value: str):
        self._value = value
        self._refresh()

class _CheckSquare(QWidget):
    """Petite case carree — purement decorative ici (voir _EdgeCheckItem :
    le clic est capte par la ligne entiere, pas par la case elle-meme)."""

    def __init__(self, checked: bool = False, parent=None):
        super().__init__(parent)
        self._checked = checked
        self.setFixedSize(14, 14)
        self.setAttribute(Qt.WA_TransparentForMouseEvents, True)

    def isChecked(self) -> bool:
        return self._checked

    def setChecked(self, checked: bool):
        if checked != self._checked:
            self._checked = checked
            self.update()

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing, False)
        bg = QColor(M["accent"] if self._checked else M["field_bg"])
        bd = QColor(M["accent_border"] if self._checked else M["field_border"])
        p.setPen(bd)
        p.setBrush(bg)
        p.drawRect(0, 0, 13, 13)
        if self._checked:
            p.setPen(QColor(M["bold_mark_fg"]))
            p.setFont(_qfont(9, 700, mono=True))
            p.drawText(0, 0, 13, 13, Qt.AlignCenter, "\u2713")
        p.end()
