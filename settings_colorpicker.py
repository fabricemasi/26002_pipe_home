from PySide6.QtCore import (
    Qt, Signal,
)
from PySide6.QtGui import (
    QColor,
    QPainter,
)
from PySide6.QtWidgets import (
    QHBoxLayout,
    QWidget,
)
from settings_store import (
    M,
)
from settings_widgets import (
    _ColorPickerPopup,
    _ColorSwatchButton,
    _qfont,
)


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
        self._refresh()

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
