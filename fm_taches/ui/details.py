"""Panneau de détails de la tâche sélectionnée (à droite), en briques des réglages / fm_theme (règle de l'appli :
jamais un style inventé) : titre, notes, échéance (date en saisie libre + heure + raccourcis), priorité, marquée,
liste, lien, sous-tâches, dates, supprimer. Chaque champ enregistre à la fin de sa saisie (une commande
annulable par champ) ; recharger une tâche ne déclenche aucune écriture."""
from __future__ import annotations

from datetime import date, datetime, timedelta

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import QHBoxLayout, QLabel, QSizePolicy, QVBoxLayout, QWidget

from fm_agenda.core import timeutil as tu
from fm_agenda.ui import kit
from . import theme as th

FIELD_W = 262


def _caption(text: str) -> QLabel:
    lab = QLabel(text)
    lab.setObjectName("dMuted")
    return lab


class DetailsPanel(QWidget):
    edited = Signal(str, dict)                   # (id, champs)
    moveToList = Signal(str, str)                # (id, liste)
    addSubtask = Signal(str)
    deleteRequested = Signal(str)

    def __init__(self, holder, parent=None):
        super().__init__(parent)
        self.holder = holder
        self.task = None
        self.lists: list = []
        self._loading = False
        self.setObjectName("TachesDetails")
        self.setAttribute(Qt.WA_StyledBackground, True)
        self.setFixedWidth(FIELD_W + 36)
        self.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Expanding)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(18, 16, 18, 16)
        lay.setSpacing(6)
        self.empty = QLabel("Aucune tâche sélectionnée")
        self.empty.setObjectName("dDim")
        self.empty.setAlignment(Qt.AlignCenter)
        lay.addWidget(self.empty)
        self.body = QWidget()
        b = QVBoxLayout(self.body)
        b.setContentsMargins(0, 0, 0, 0)
        b.setSpacing(6)
        lay.addWidget(self.body)
        lay.addStretch(1)

        b.addWidget(_caption("Titre"))
        self.title = kit.text_field("", FIELD_W, "Titre de la tâche")
        self.title.editingFinished.connect(lambda: self._text_done("title", self.title.text().strip()))
        b.addWidget(self.title)
        b.addWidget(_caption("Notes"))
        self.notes = kit.lines_field((), FIELD_W, 4)
        self.notes.setPlaceholderText("Notes")
        self.notes.installEventFilter(self)
        b.addWidget(self.notes)

        b.addSpacing(6)
        b.addWidget(_caption("Échéance"))
        row = QHBoxLayout()
        row.setSpacing(6)
        self.due = kit.text_field("", 150, "jj/mm/aaaa, demain…")
        self.due.editingFinished.connect(self._due_done)
        self.time = kit.text_field("", 70, "hh:mm")
        self.time.editingFinished.connect(self._time_done)
        row.addWidget(self.due)
        row.addWidget(self.time)
        row.addStretch(1)
        b.addLayout(row)
        quick = QHBoxLayout()
        quick.setSpacing(6)
        for text, days in (("Aujourd'hui", 0), ("Demain", 1), ("Aucune", None)):
            quick.addWidget(kit.button(text, lambda d=days: self._quick_due(d)))
        quick.addStretch(1)
        b.addLayout(quick)
        self.due_note = QLabel("")
        self.due_note.setObjectName("dDim")
        self.due_note.setWordWrap(True)
        b.addWidget(self.due_note)
        b.addWidget(_caption("Rappel"))
        self.reminder = kit.select(["Aucun rappel"], "Aucun rappel", FIELD_W)
        self.reminder.changed.connect(self._reminder_done)
        b.addWidget(self.reminder)
        self.at_due = True                            # réglage `taches_remind_at_due` (posé par le panneau)

        b.addSpacing(6)
        grid = QHBoxLayout()
        grid.setSpacing(12)
        col1 = QVBoxLayout()
        col1.addWidget(_caption("Priorité"))
        self.priority = kit.select(list(th.PRIORITY_LABELS), th.PRIORITY_LABELS[0], 120)
        self.priority.changed.connect(lambda v: self._emit({"priority": th.PRIORITY_LABELS.index(v)}))
        col1.addWidget(self.priority)
        col2 = QVBoxLayout()
        col2.addWidget(_caption("Marquée"))
        from fm_theme.widgets import _Toggle
        self.flag = _Toggle(False, "oui", "non")
        self.flag.toggled.connect(lambda on: self._emit({"flagged": bool(on)}))
        col2.addWidget(self.flag)
        grid.addLayout(col1)
        grid.addLayout(col2)
        grid.addStretch(1)
        b.addLayout(grid)

        b.addWidget(_caption("Liste"))
        self.list_sel = kit.select(["—"], "—", FIELD_W)
        self.list_sel.changed.connect(self._list_done)
        b.addWidget(self.list_sel)
        b.addWidget(_caption("Lien"))
        self.url = kit.text_field("", FIELD_W, "https://…")
        self.url.editingFinished.connect(lambda: self._text_done("url", self.url.text().strip()))
        b.addWidget(self.url)

        b.addSpacing(8)
        self.info = QLabel("")
        self.info.setObjectName("dDim")
        self.info.setTextFormat(Qt.PlainText)
        self.info.setWordWrap(True)
        b.addWidget(self.info)
        actions = QHBoxLayout()
        actions.setSpacing(6)
        self.sub_btn = kit.button("Ajouter une sous-tâche", lambda: self.task and self.addSubtask.emit(self.task.id))
        actions.addWidget(self.sub_btn)
        actions.addWidget(kit.button("Supprimer", lambda: self.task and self.deleteRequested.emit(self.task.id)))
        actions.addStretch(1)
        b.addLayout(actions)
        self.show_task(None, [])

    # -- chargement --

    def show_task(self, task, lists, children=(), can_nest: bool = True, google: bool = False) -> None:
        """Recharge les champs (aucune écriture ; un champ en cours de saisie garde son texte)."""
        self.lists = list(lists)
        self.task = task
        self._loading = True
        try:
            self.empty.setVisible(task is None)
            self.body.setVisible(task is not None)
            if task is None:
                return
            if not self.title.hasFocus():
                self.title.setText(task.title)
            if not self.notes.hasFocus():
                self.notes.setPlainText(task.notes)
            if not self.due.hasFocus():
                self.due.setText(tu.fmt_numeric(task.due) if task.due else "")
            if not self.time.hasFocus():
                self.time.setText(task.due_time or "")
            self.due_note.setText("Google Tasks ne garde que la date : l'heure reste dans PIPE FMZ."
                                  if google and task.due_time else "")
            self.due_note.setVisible(bool(self.due_note.text()))
            options = self._reminder_options(task)
            self.reminder.setOptions([label for label, _v in options])
            self.reminder.setValue(options[0][0])
            self.priority.setValue(th.PRIORITY_LABELS[task.priority])
            self.flag.setChecked(task.flagged)
            names = [lst.name for lst in self.lists] or ["—"]
            self.list_sel.setOptions(names)
            current = next((lst.name for lst in self.lists if lst.id == task.list_id), names[0])
            self.list_sel.setValue(current)
            if not self.url.hasFocus():
                self.url.setText(task.url)
            parts = []
            if children:
                done = sum(1 for c in children if c.done)
                parts.append(f"{len(children)} sous-tâche{'s' if len(children) > 1 else ''}"
                             + (f" ({done} terminée{'s' if done > 1 else ''})" if done else ""))
            if task.created_at:
                parts.append("Créée le " + _stamp(task.created_at))
            if task.done and task.completed_at:
                parts.append("Terminée le " + _stamp(task.completed_at))
            self.info.setText("\n".join(parts))
            self.sub_btn.setEnabled(can_nest)
        finally:
            self._loading = False

    # -- saisies --

    def _emit(self, fields: dict) -> None:
        if self._loading or self.task is None:
            return
        changed = {k: v for k, v in fields.items() if getattr(self.task, k) != v}
        if changed:
            self.edited.emit(self.task.id, changed)

    def _text_done(self, key: str, value: str) -> None:
        if key == "title" and not value:
            self.title.setText(self.task.title if self.task else "")
            return
        self._emit({key: value})

    def eventFilter(self, obj, event):
        if obj is self.notes and event.type() == event.Type.FocusOut:
            self._emit({"notes": self.notes.toPlainText().rstrip()})
        return False

    def _due_done(self) -> None:
        text = self.due.text().strip()
        if not text:
            self._emit({"due_date": None, "due_time": None})
            return
        parsed = tu.parse_user_date(text)
        if parsed is None:
            self.due.setText(tu.fmt_numeric(self.task.due) if self.task and self.task.due else "")
            return
        self.due.setText(tu.fmt_numeric(parsed))
        self._emit({"due_date": parsed.isoformat()})

    def _time_done(self) -> None:
        text = self.time.text().strip()
        if not text:
            self._emit({"due_time": None})
            return
        hm = tu.parse_user_time(text)
        if hm is None or hm[0] >= 24:
            self.time.setText(self.task.due_time or "" if self.task else "")
            return
        value = f"{hm[0]:02d}:{hm[1]:02d}"
        self.time.setText(value)
        fields = {"due_time": value}
        if self.task is not None and not self.task.due_date:
            fields["due_date"] = date.today().isoformat()          # une heure sans date = aujourd'hui
        self._emit(fields)

    def _quick_due(self, days) -> None:
        if days is None:
            self._emit({"due_date": None, "due_time": None})
            return
        today = date.today()
        d = th.next_weekday(today, 0) if days == "lundi" else today + timedelta(days=days)
        self._emit({"due_date": d.isoformat()})

    # -- rappel --

    def _reminder_options(self, task) -> list[tuple[str, object]]:
        """[(libellé, horodatage | None | « keep »)] : l'état actuel d'abord (choisi = rien à faire), puis les
        choix ; « avant » se compte depuis l'échéance (9:00 pour une tâche sans heure)."""
        now = datetime.now()
        if task.reminder_at:
            current = "Rappel : " + _stamp(task.reminder_at)
        elif self.at_due and task.due_time and task.due:
            current = f"À l'échéance (automatique, {task.due_time})"
        else:
            current = "Aucun rappel"
        out = [(current, "keep")]
        if task.due:
            hh, mm = (int(x) for x in (task.due_time or "09:00").split(":"))
            due_dt = datetime.combine(task.due, datetime.min.time()).replace(hour=hh, minute=mm)
            for label, delta in (("À l'échéance", timedelta()), ("15 min avant", timedelta(minutes=15)),
                                 ("1 h avant", timedelta(hours=1))):
                out.append((label, (due_dt - delta).timestamp()))
            eve = datetime.combine(task.due - timedelta(days=1), datetime.min.time()).replace(hour=9)
            out.append(("La veille à 9:00", eve.timestamp()))
        out.append(("Dans 1 heure", (now + timedelta(hours=1)).timestamp()))
        tomorrow = datetime.combine(now.date() + timedelta(days=1), datetime.min.time()).replace(hour=9)
        out.append(("Demain à 9:00", tomorrow.timestamp()))
        if task.reminder_at:
            out.append(("Retirer le rappel", None))
        return out

    def _reminder_done(self, label: str) -> None:
        if self._loading or self.task is None:
            return
        value = dict(self._reminder_options(self.task)).get(label, "keep")
        if value != "keep":
            self._emit({"reminder_at": int(value) if value is not None else None})

    def _list_done(self, name: str) -> None:
        if self._loading or self.task is None:
            return
        target = next((lst.id for lst in self.lists if lst.name == name), None)
        if target and target != self.task.list_id:
            self.moveToList.emit(self.task.id, target)


def _stamp(ts: int) -> str:
    d = datetime.fromtimestamp(ts)
    return f"{tu.fmt_date(d.date())} à {d:%H:%M}"
