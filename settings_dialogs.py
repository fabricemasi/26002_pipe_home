"""Fenetres de confirmation (demande de l'utilisateur : supprimer un fichier / dossier, glisser des elements
dans un autre dossier). Construites avec les briques des reglages, jamais un style invente : en-tete du
selecteur de couleur (etiquette + titre + croix, glissable), textes par roles, barre du bas de la fenetre
de reglages (Annuler / bouton d'action en couleur d'accent). Couche reglages : aucune dependance a l'appli.

`confirm(parent, tag, title, message, items, action)` -> True si l'action est confirmee (bouton d'action
ou Entree) ; Annuler, la croix ou Echap -> False."""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QDialog, QHBoxLayout, QLabel, QSizePolicy, QVBoxLayout, QWidget

from settings_store import M
from settings_theme import _set_text_role
from settings_widgets import _Btn, _PickerCloseButton, _PopupHeader

MAX_LISTED = 8          # elements nommes dans la fenetre, au-dela : « ... et N autres »


class ConfirmDialog(QDialog):
    def __init__(self, parent, tag: str, title: str, message: str, items=(), action: str = "Valider"):
        super().__init__(parent, Qt.Dialog | Qt.FramelessWindowHint)
        self.setModal(True)
        self.setObjectName("ConfirmDialog")
        self.setAttribute(Qt.WA_StyledBackground, True)
        self.setStyleSheet(f"#ConfirmDialog {{ background: {M['panel_bg']}; border: 1px solid {M['panel_border']}; }}")
        self.setMinimumWidth(380)
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        # -- en-tete (celui du selecteur de couleur) --
        head = _PopupHeader(self)
        head.setFixedHeight(28)
        head.setStyleSheet(f"background: {M['btn_hover']}; border-bottom: 2px solid {M['accent']};")
        head_l = QHBoxLayout(head)
        head_l.setContentsMargins(10, 0, 8, 0)
        head_l.setSpacing(8)
        tag_label = QLabel(tag.upper())
        _set_text_role(tag_label, "tag_accent")
        head_l.addWidget(tag_label)
        title_label = QLabel(title)
        _set_text_role(title_label, "card_title")
        title_label.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
        head_l.addWidget(title_label, 1)
        close_btn = _PickerCloseButton(M["label_dim"])
        close_btn.setFixedSize(16, 16)
        close_btn.setFlat(True)
        close_btn.clicked.connect(self.reject)
        head_l.addWidget(close_btn)
        outer.addWidget(head)

        # -- corps : message + elements concernes --
        body = QVBoxLayout()
        body.setContentsMargins(14, 14, 14, 14)
        body.setSpacing(8)
        text = QLabel(message)
        text.setWordWrap(True)
        _set_text_role(text, "row_label")
        body.addWidget(text)
        items = list(items)
        if items:
            listing = QVBoxLayout()
            listing.setContentsMargins(10, 2, 0, 0)
            listing.setSpacing(3)
            for name in items[:MAX_LISTED]:
                line = QLabel(name)
                _set_text_role(line, "value")
                line.setTextInteractionFlags(Qt.TextSelectableByMouse)
                listing.addWidget(line)
            if len(items) > MAX_LISTED:
                more = QLabel(f"… et {len(items) - MAX_LISTED} autre(s)")
                _set_text_role(more, "inline_label")
                listing.addWidget(more)
            body.addLayout(listing)
        outer.addLayout(body)

        # -- barre du bas (celle de la fenetre de reglages) --
        bar = QWidget()
        bar.setFixedHeight(46)
        bar.setStyleSheet(f"background: {M['toolbar_bg']}; border-top: 1px solid {M['panel_border']};")
        lay = QHBoxLayout(bar)
        lay.setContentsMargins(14, 0, 14, 0)
        lay.setSpacing(8)
        lay.addStretch(1)
        self.cancel_btn = _Btn("Annuler", M["btn_bg"], M["btn_border"], M["btn_fg"], M["btn_hover"],
                               height=27, padding="0 13px")
        self.cancel_btn.clicked.connect(self.reject)
        lay.addWidget(self.cancel_btn)
        self.action_btn = _Btn(action, M["accent"], M["accent_border"], M["accent_fg"], M["accent_hover"],
                               height=27, weight=600, padding="0 17px")
        self.action_btn.clicked.connect(self.accept)
        lay.addWidget(self.action_btn)
        outer.addWidget(bar)

    def keyPressEvent(self, event):
        if event.key() in (Qt.Key_Return, Qt.Key_Enter):
            self.accept()
            return
        super().keyPressEvent(event)           # Echap : reject (QDialog)

    def showEvent(self, event):
        super().showEvent(event)
        parent = self.parentWidget()
        if parent is not None:                 # centree sur la fenetre qui la demande
            host = parent.window().frameGeometry()
            self.move(host.center() - self.rect().center())


def confirm(parent, tag: str, title: str, message: str, items=(), action: str = "Valider") -> bool:
    dialog = ConfirmDialog(parent, tag, title, message, items, action)
    try:
        return dialog.exec() == QDialog.Accepted
    finally:
        dialog.deleteLater()
