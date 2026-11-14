"""Briques d'interface audio, TOUTES construites sur fm_theme / réglages (jamais un style inventé)."""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor
from PySide6.QtWidgets import QLabel, QPushButton

TAG = "Audio"


def tok(name: str, fallback: str = "#808080") -> QColor:
    """Couleur d'un jeton fm_theme (peinture des vues : fond, pistes, accent…)."""
    try:
        from fm_theme.tokens import M
        return QColor(M.get(name, fallback))
    except Exception:
        return QColor(fallback)


def label(text: str, role: str = "row_label") -> QLabel:
    from fm_theme.theme import _text_label
    return _text_label(text, role)


def button(text: str, tip: str, slot=None, parent=None, checkable: bool = False, compact: bool = True) -> QPushButton:
    """Bouton : aspect = fm_theme seul (`theme_button`)."""
    from fm_theme.style import theme_button
    b = theme_button(QPushButton(text, parent), compact=compact)
    b.setToolTip(tip)
    b.setCursor(Qt.ArrowCursor)
    b.setCheckable(checkable)
    b.setFocusPolicy(Qt.NoFocus)        # le clavier reste à la timeline
    if slot is not None:
        b.clicked.connect(lambda _c=False: slot())
    return b


def menu(parent=None):
    from fm_theme.menu import Menu
    return Menu(parent)


def confirm(parent, title_text: str, message: str, action: str = "Valider", items=()) -> bool:
    from fm_theme.dialogs import confirm as theme_confirm
    return theme_confirm(parent, TAG, title_text, message, items, action=action)


def choose(parent, title_text: str, message: str, choices: list) -> str | None:
    """Plusieurs actions (clé, libellé) dans la fenêtre de confirmation de l'appli ; None = annulée."""
    from PySide6.QtWidgets import QDialog
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


def fmt_time(samples: int, sr: int) -> str:
    """mm:ss.mmm"""
    s = max(0, samples) / max(1, sr)
    return f"{int(s // 60):02d}:{s % 60:06.3f}"


def ask_value(parent, title: str, message: str, default: str) -> str | None:
    """Fenêtre de confirmation de l'appli + une zone de saisie fm_theme ; None si annulée."""
    from PySide6.QtWidgets import QDialog, QHBoxLayout, QWidget
    from fm_theme.cells import _TextField
    from fm_theme.dialogs import ConfirmDialog
    dialog = ConfirmDialog(parent, TAG, title, message, (), "Appliquer")
    field = _TextField(default, 200)
    holder = QWidget()
    lay = QHBoxLayout(holder)
    lay.setContentsMargins(14, 0, 14, 14)
    lay.addWidget(field)
    dialog.layout().insertWidget(dialog.layout().count() - 1, holder)
    field.setFocus()
    try:
        return field.text() if dialog.exec() == QDialog.Accepted else None
    finally:
        dialog.deleteLater()