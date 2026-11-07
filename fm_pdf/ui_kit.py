"""Briques d'interface du module PDF (Qt), TOUTES construites sur celles des réglages / fm_theme (règle de
l'appli : jamais un style inventé) : libellés par rôle de texte, boutons plats de la feuille de style de l'appli,
zones de saisie `_TextField`, tableaux `build_cells_table`, interrupteurs `_Toggle`, fenêtre de confirmation
`confirm` (et sa variante avec une zone de saisie : mot de passe, texte), menus `Menu`."""
from __future__ import annotations

from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import QDialog, QLabel, QPushButton, QWidget

TAG = "PDF"


def label(text: str, role: str = "row_label") -> QLabel:
    from fm_theme.theme import _text_label
    return _text_label(text, role)


def title(text: str) -> QLabel:
    return label(text, "card_title")


def button(text: str, tip: str, slot=None, parent=None, checkable: bool = False) -> QPushButton:
    """Bouton plat habillé par la feuille de style de l'appli (comme les barres du Board, du Tableur, de fm_font)."""
    b = QPushButton(text, parent)
    b.setToolTip(tip)
    b.setFlat(True)
    b.setCursor(Qt.ArrowCursor)
    b.setFixedHeight(26)
    b.setStyleSheet("QPushButton { padding: 0px 8px; }")
    b.setMinimumWidth(b.sizeHint().width())
    b.setCheckable(checkable)
    b.setFocusPolicy(Qt.NoFocus)                   # le clavier reste à la vue (champs de formulaire)
    if slot is not None:
        b.clicked.connect(lambda _c=False: slot())
    return b


def text_field(text: str = "", width: int = 120, placeholder: str = ""):
    from fm_theme.cells import _TextField
    field = _TextField(text, width)
    if placeholder:
        field.setPlaceholderText(placeholder)
    return field


def toggle(on: bool, slot=None):
    from fm_theme.widgets import _Toggle
    t = _Toggle(on)
    if slot is not None:
        t.toggled.connect(slot)
    return t


def menu(parent=None):
    from fm_theme.menu import Menu
    return Menu(parent)


def confirm(parent, title_text: str, message: str, action: str = "Valider", items=()) -> bool:
    from fm_theme.dialogs import confirm as theme_confirm
    return theme_confirm(parent, TAG, title_text, message, items, action=action)


def ask_text(parent, title_text: str, message: str, *, password: bool = False, default: str = "",
             action: str = "Valider") -> str | None:
    """Fenêtre de confirmation de l'appli + une zone de saisie ; None si annulée."""
    from PySide6.QtWidgets import QLineEdit
    from fm_theme.dialogs import ConfirmDialog
    dialog = ConfirmDialog(parent, TAG, title_text, message, (), action)
    field = text_field(default, 320)
    if password:
        field.setEchoMode(QLineEdit.Password)
    holder = QWidget()
    from PySide6.QtWidgets import QHBoxLayout
    lay = QHBoxLayout(holder)
    lay.setContentsMargins(14, 0, 14, 14)
    lay.addWidget(field)
    layout = dialog.layout()
    layout.insertWidget(layout.count() - 1, holder)
    QTimer.singleShot(0, field.setFocus)
    try:
        return field.text() if dialog.exec() == QDialog.Accepted else None
    finally:
        dialog.deleteLater()


def choose(parent, title_text: str, message: str, choices: list[tuple[str, str]]) -> str | None:
    """Plusieurs actions (clé, libellé) dans la fenêtre de confirmation de l'appli ; None = annulée.
    La première est le bouton d'accent (action par défaut, Entrée)."""
    from fm_theme.dialogs import ConfirmDialog
    from fm_theme.tokens import M
    from fm_theme.widgets import _Btn
    dialog = ConfirmDialog(parent, TAG, title_text, message, (), choices[0][1])
    chosen = [choices[0][0]]
    bar = dialog.action_btn.parentWidget().layout()
    for key, text in choices[1:]:
        b = _Btn(text, M["btn_bg"], M["btn_border"], M["btn_fg"], M["btn_hover"], height=27, padding="0 13px")
        b.clicked.connect(lambda _c=False, k=key: (chosen.__setitem__(0, k), dialog.accept()))
        bar.insertWidget(bar.indexOf(dialog.action_btn), b)
    dialog.action_btn.clicked.disconnect()
    dialog.action_btn.clicked.connect(lambda: (chosen.__setitem__(0, choices[0][0]), dialog.accept()))
    try:
        return chosen[0] if dialog.exec() == QDialog.Accepted else None
    finally:
        dialog.deleteLater()


class Table:
    """Tableau « libellé | valeur » des briques des réglages, valeurs posées sur place (construit UNE fois)."""

    def __init__(self, title_left: str, rows, width: int = 150):
        from fm_theme.cells import build_cells_table
        self.fields: dict[str, QWidget] = {}
        self.commits: dict = {}
        cells = []
        for key, text, editable, commit in rows:
            if editable:
                field = text_field("", width)
                field._start = ""
                field.editingFinished.connect(lambda k=key: self._commit(k))
            else:
                field = label("", "value")
                field.setTextInteractionFlags(Qt.TextSelectableByMouse)
                field.setWordWrap(True)
            self.fields[key] = field
            self.commits[key] = commit
            cells.append([(label(text), "left", "center"), (field, "left", "center")])
        self.frame, self.head, self.cells = build_cells_table([(title_left, 130), ("Valeur", 0)], cells)

    def _commit(self, key):
        field = self.fields[key]
        if field.text() == field._start:
            return
        value, field._start = field.text(), field.text()
        if self.commits.get(key):
            QTimer.singleShot(0, lambda: self.commits[key](value))

    def set(self, key: str, value) -> None:
        field = self.fields[key]
        text = "" if value is None else (f"{value:g}" if isinstance(value, float) else str(value))
        if hasattr(field, "_start"):
            field._start = text
            if not field.hasFocus() and field.text() != text:
                field.setText(text)
        elif field.text() != text:
            field.setText(text)

    def enable(self, key: str, on: bool) -> None:
        self.fields[key].setEnabled(on)
