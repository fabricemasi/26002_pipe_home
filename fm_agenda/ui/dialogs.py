"""Dialogues de l'agenda (briques des réglages) : comparaison et résolution des conflits de synchronisation."""
from __future__ import annotations

from datetime import date, datetime

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QDialog, QHBoxLayout, QScrollArea, QVBoxLayout, QWidget

from ..core import timeutil as tu
from . import kit


def _show(name: str, value) -> str:
    if value is None or value == "" or value == []:
        return "—"
    if name in ("start", "end") and isinstance(value, int):
        return datetime.fromtimestamp(value).strftime("%d/%m/%Y %H:%M")
    if isinstance(value, bool):
        return "oui" if value else "non"
    if name == "attendees":
        return ", ".join(a.get("name") or a.get("email", "") for a in value)
    if isinstance(value, list):
        return ", ".join(str(v) for v in value)
    return str(value)


class ConflictsDialog(QDialog):
    """Un conflit par carte : champs en conflit, version PIPE FMZ / version Google côte à côte, deux boutons."""

    def __init__(self, parent, manager):
        super().__init__(parent, Qt.Dialog | Qt.FramelessWindowHint)
        from fm_theme.tokens import M
        self.manager = manager
        self.setModal(True)
        self.setObjectName("AgendaConflicts")
        self.setAttribute(Qt.WA_StyledBackground, True)
        self.setStyleSheet(f"#AgendaConflicts {{ background: {M['panel_bg']}; border: 1px solid "
                           f"{M['panel_border']}; }}")
        outer = QVBoxLayout(self)
        outer.setContentsMargins(16, 14, 16, 12)
        outer.setSpacing(10)
        outer.addWidget(kit.label("Conflits de synchronisation", "card_title"))
        note = kit.label("Ces événements ont été modifiés ici ET dans Google avant d'être synchronisés. Les deux "
                         "versions sont gardées : choisissez celle qui l'emporte.", "inline_label")
        note.setWordWrap(True)
        outer.addWidget(note)
        area = QScrollArea()
        area.setWidgetResizable(True)
        area.setFrameShape(QScrollArea.NoFrame)
        area.setStyleSheet("QScrollArea { background: transparent; border: none; }")
        area.viewport().setStyleSheet("background: transparent;")
        holder = QWidget()
        holder.setObjectName("ConflictsBody")
        holder.setStyleSheet("#ConflictsBody { background: transparent; }")
        self.body = QVBoxLayout(holder)
        self.body.setSpacing(12)
        area.setWidget(holder)
        outer.addWidget(area, 1)
        bar = QHBoxLayout()
        bar.addStretch(1)
        bar.addWidget(kit.button("Fermer", self.accept))
        outer.addLayout(bar)
        self.resize(720, 520)
        self.refresh()

    def refresh(self) -> None:
        while self.body.count():
            item = self.body.takeAt(0)
            if item.widget() is not None:
                item.widget().deleteLater()
        from ..sync.engine import GROUP_LABELS, GROUPS
        conflicts = self.manager.conflicts()
        if not conflicts:
            self.body.addWidget(kit.label("Aucun conflit.", "value"))
        for c in conflicts:
            card = QWidget()
            lay = QVBoxLayout(card)
            lay.setContentsMargins(0, 0, 0, 0)
            lay.setSpacing(4)
            title = c["local"].get("title") or c["remote"].get("title") or "(Sans titre)"
            lay.addWidget(kit.label(title, "card_title"))
            fields = c["fields"] or []
            lay.addWidget(kit.label("En conflit : " + ", ".join(GROUP_LABELS.get(f, f) for f in fields),
                                    "inline_label"))
            for group in fields:
                names = GROUPS.get(group, (group,))
                for name in names:
                    local = c["local"].get(name) if not c["local"].get("deleted") else "(supprimé)"
                    remote = c["remote"].get(name) if not c["remote"].get("deleted") else "(supprimé)"
                    if local == remote:
                        continue
                    row = QHBoxLayout()
                    key = kit.label(GROUP_LABELS.get(name, name), "row_label")
                    key.setFixedWidth(110)
                    row.addWidget(key)
                    a = kit.label("PIPE FMZ : " + _show(name, local), "value")
                    b = kit.label("Google : " + _show(name, remote), "value")
                    a.setWordWrap(True)
                    b.setWordWrap(True)
                    row.addWidget(a, 1)
                    row.addWidget(b, 1)
                    lay.addLayout(row)
            buttons = QHBoxLayout()
            buttons.addWidget(kit.button("Garder la version PIPE FMZ", lambda _c=False, cc=c: self._resolve(cc, "local"),
                                         accent=True))
            buttons.addWidget(kit.button("Garder la version Google", lambda _c=False, cc=c: self._resolve(cc, "remote")))
            buttons.addStretch(1)
            lay.addLayout(buttons)
            self.body.addWidget(card)
        self.body.addStretch(1)

    def _resolve(self, conflict: dict, choice: str) -> None:
        self.manager.resolve_conflict(conflict, choice, on_done=lambda _r: self.refresh())
