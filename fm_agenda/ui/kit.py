"""Briques d'interface des fenêtres de l'agenda (éditeur, dialogues), TOUTES construites sur celles des réglages /
fm_theme (règle de l'appli : jamais un style inventé) : libellés par rôle, zones de saisie, listes de choix,
interrupteurs, boutons, fenêtre de confirmation, menus."""
from __future__ import annotations

from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import QDialog, QHBoxLayout, QLabel, QWidget

TAG = "Agenda"


def seed_look() -> None:
    try:
        import settings_window_v2 as v2
        from settings_store import load_settings
        v2.seed_window_look(load_settings())
    except Exception:                                    # noqa: BLE001 - hors de l'appli (tests) : défauts
        pass


def label(text: str, role: str = "row_label") -> QLabel:
    from fm_theme.theme import _text_label
    return _text_label(text, role)


def text_field(text: str = "", width: int = 220, placeholder: str = ""):
    from fm_theme.cells import _TextField
    field = _TextField(text, width)
    if placeholder:
        field.setPlaceholderText(placeholder)
    return field


def lines_field(lines=(), width: int = 320, rows: int = 3):
    from fm_theme.cells import _LinesField
    field = _LinesField(list(lines), width=width, rows=rows)
    from PySide6.QtWidgets import QPlainTextEdit
    field.setLineWrapMode(QPlainTextEdit.WidgetWidth)
    return field


def select(options: list[str], current: str, width: int = 220):
    from fm_theme.widgets import _SelectField
    return _SelectField(list(options) or [current], current, width=width)


def toggle(on: bool, slot=None):
    from fm_theme.widgets import _Toggle
    t = _Toggle(on)
    if slot is not None:
        t.toggled.connect(slot)
    return t


def button(text: str, slot=None, accent: bool = False, tip: str = ""):
    from fm_theme.tokens import M
    from fm_theme.widgets import _Btn
    if accent:
        b = _Btn(text, M["accent"], M["accent_border"], M["accent_fg"], M["accent_hover"], height=27, weight=600,
                 padding="0 17px")
    else:
        b = _Btn(text, M["btn_bg"], M["btn_border"], M["btn_fg"], M["btn_hover"], height=27, padding="0 13px")
    if tip:
        b.setToolTip(tip)
    if slot is not None:
        b.clicked.connect(lambda _c=False: slot())
    return b


def menu(parent=None):
    from fm_theme.menu import Menu
    return Menu(parent)


def confirm(parent, title_text: str, message: str, action: str = "Valider", items=()) -> bool:
    from fm_theme.dialogs import confirm as theme_confirm
    return theme_confirm(parent, TAG, title_text, message, items, action=action)


def choose(parent, title_text: str, message: str, choices: list[tuple[str, str]]) -> str | None:
    """Plusieurs actions (clé, libellé) dans la fenêtre de confirmation de l'appli ; None = annulée. La première
    est le bouton d'accent (Entrée)."""
    from fm_theme.dialogs import ConfirmDialog
    dialog = ConfirmDialog(parent, TAG, title_text, message, (), choices[0][1])
    chosen = [choices[0][0]]
    bar = dialog.action_btn.parentWidget().layout()
    for key, text in choices[1:]:
        b = button(text)
        b.clicked.connect(lambda _c=False, k=key: (chosen.__setitem__(0, k), dialog.accept()))
        bar.insertWidget(bar.indexOf(dialog.action_btn), b)
    dialog.action_btn.clicked.disconnect()
    dialog.action_btn.clicked.connect(lambda: (chosen.__setitem__(0, choices[0][0]), dialog.accept()))
    try:
        return chosen[0] if dialog.exec() == QDialog.Accepted else None
    finally:
        dialog.deleteLater()


def ask_text(parent, title_text: str, message: str, default: str = "", action: str = "Valider") -> str | None:
    from fm_theme.dialogs import ConfirmDialog
    dialog = ConfirmDialog(parent, TAG, title_text, message, (), action)
    field = text_field(default, 320)
    holder = QWidget()
    lay = QHBoxLayout(holder)
    lay.setContentsMargins(14, 0, 14, 14)
    lay.addWidget(field)
    layout = dialog.layout()
    layout.insertWidget(layout.count() - 1, holder)
    QTimer.singleShot(0, lambda: (field.setFocus(), field.selectAll()))
    try:
        return field.text() if dialog.exec() == QDialog.Accepted else None
    finally:
        dialog.deleteLater()


def themed_menu(parent=None):
    """Menu contextuel de l'appli (fm_theme), repli sur un QMenu si fm_theme n'est pas installé."""
    try:
        return menu(parent)
    except Exception:                                    # noqa: BLE001
        from PySide6.QtWidgets import QMenu
        return QMenu(parent)


def no_focus(widget) -> None:
    widget.setFocusPolicy(Qt.NoFocus)
