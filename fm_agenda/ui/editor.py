"""Éditeur d'un événement : fenêtre additionnelle de l'appli (barre de titre, panneau, barre des boutons des
réglages) et tableau « champ | valeur » des réglages (`build_cells_table`) — briques de l'appli, jamais un style
inventé. Construit UNE fois par panneau puis rempli à chaque ouverture (ouverture immédiate).

Champs : titre, calendrier, couleur, journée, début / fin (date + heure, la fin suit le début), fuseau,
répétition (choix rapides + règle personnalisée), rappels, disponibilité, statut, lieu, lien, projet, dossier,
catégories, participants, tâche (faite), description, notes."""
from __future__ import annotations

from datetime import date, datetime, timedelta

from PySide6.QtCore import QPoint, QRectF, QSize, Qt, QTimer, Signal
from PySide6.QtGui import QPainter, QPen
from PySide6.QtWidgets import (QApplication, QDialog, QFileDialog, QHBoxLayout, QLabel, QSizePolicy, QVBoxLayout,
                               QWidget)

from ..core import recurrence as rec
from ..core import timeutil as tu
from ..core.model import PALETTE, PALETTE_LABELS, Attendee, EventRecord
from . import kit
from . import theme as th

REMINDER_CHOICES = ((0, "À l'heure de l'événement"), (5, "5 minutes avant"), (10, "10 minutes avant"),
                    (15, "15 minutes avant"), (30, "30 minutes avant"), (60, "1 heure avant"),
                    (120, "2 heures avant"), (1440, "1 jour avant"), (2880, "2 jours avant"),
                    (10080, "1 semaine avant"))
CUSTOM_RULE = "Personnalisée…"


class ColorChooser(QWidget):
    """« Couleur du calendrier » puis les couleurs nommées ; la choisie est cerclée."""
    changed = Signal(object)

    def __init__(self, holder, parent=None):
        super().__init__(parent)
        self.holder = holder
        self.value: str | None = None
        self.calendar_color = "bleu"
        self.setFixedSize(QSize(26 * (len(PALETTE) + 1) + 4, 24))
        self.setCursor(Qt.PointingHandCursor)
        self.setMouseTracking(True)

    def _keys(self):
        return [None] + list(PALETTE)

    def paintEvent(self, event):
        t = self.holder.t
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing, True)
        for i, key in enumerate(self._keys()):
            r = QRectF(2 + i * 26 + 3, 3, 18, 18)
            color = t.event(key or self.calendar_color)[1]
            p.setPen(Qt.NoPen)
            p.setBrush(color)
            p.drawEllipse(r)
            if key is None:
                p.setPen(QPen(t.c("bg"), 2))
                p.drawLine(r.topRight() + QPoint(-4, 4), r.bottomLeft() + QPoint(4, -4))
            if key == self.value:
                p.setPen(QPen(t.c("strong"), 2))
                p.setBrush(Qt.NoBrush)
                p.drawEllipse(r.adjusted(-2.5, -2.5, 2.5, 2.5))

    def mouseMoveEvent(self, event):
        i = int((event.position().x() - 2) // 26)
        keys = self._keys()
        if 0 <= i < len(keys):
            self.setToolTip("Couleur du calendrier" if keys[i] is None else PALETTE_LABELS.get(keys[i], keys[i]))

    def mousePressEvent(self, event):
        i = int((event.position().x() - 2) // 26)
        keys = self._keys()
        if 0 <= i < len(keys):
            self.value = keys[i]
            self.update()
            self.changed.emit(self.value)


class DateTimeField(QWidget):
    """Date (saisie libre : « 6/11 », « demain »…) + heure (« 9h30 », « 1430 »), flèches ↑ ↓ sur l'heure."""
    edited = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(6)
        self.date = kit.text_field("", 150, "jj/mm/aaaa")
        self.time = kit.text_field("", 76, "hh:mm")
        self.day_label = kit.label("", "inline_label")
        lay.addWidget(self.date)
        lay.addWidget(self.time)
        lay.addWidget(self.day_label)
        lay.addStretch(1)
        self.date.editingFinished.connect(self._normalize)
        self.time.editingFinished.connect(self._normalize)
        self.time.installEventFilter(self)
        self._d: date | None = None
        self._hm: tuple[int, int] = (9, 0)

    def set_value(self, d: date, hm: tuple[int, int] | None) -> None:
        self._d = d
        if hm is not None:
            self._hm = hm
        self._show()

    def _show(self) -> None:
        if self._d is not None:
            self.date.setText(tu.fmt_numeric(self._d))
            self.day_label.setText(tu.cap(tu.DAYS_LONG[self._d.weekday()]))
        self.time.setText(f"{self._hm[0]:02d}:{self._hm[1]:02d}")

    def set_time_visible(self, on: bool) -> None:
        self.time.setVisible(on)

    def _normalize(self) -> None:
        d = tu.parse_user_date(self.date.text(), self._d or date.today())
        hm = tu.parse_user_time(self.time.text())
        changed = False
        if d is not None and d != self._d:
            self._d, changed = d, True
        if hm is not None and hm != self._hm:
            self._hm, changed = (hm if hm != (24, 0) else (23, 59)), True
        self._show()
        if changed:
            self.edited.emit()

    def eventFilter(self, obj, event):
        if obj is self.time and event.type() == event.Type.KeyPress and event.key() in (Qt.Key_Up, Qt.Key_Down):
            self._normalize()
            step = 15 if event.key() == Qt.Key_Up else -15
            minutes = (self._hm[0] * 60 + self._hm[1] + step) % 1440
            self._hm = (minutes // 60, minutes % 60)
            self._show()
            self.edited.emit()
            return True
        return False

    def value_date(self) -> date | None:
        self._normalize()
        return self._d

    def value_dt(self, tz) -> datetime | None:
        self._normalize()
        if self._d is None:
            return None
        return tu.localize(datetime(self._d.year, self._d.month, self._d.day, *self._hm), tz)


class RemindersField(QWidget):
    """Rappels choisis (« 15 minutes avant × ») + liste « Ajouter un rappel »."""

    def __init__(self, parent=None):
        super().__init__(parent)
        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(6)
        self.chips = QHBoxLayout()
        self.chips.setSpacing(4)
        lay.addLayout(self.chips)
        labels = ["Ajouter un rappel…"] + [label for _m, label in REMINDER_CHOICES]
        self.add = kit.select(labels, labels[0], 190)
        self.add.changed.connect(self._added)
        lay.addWidget(self.add)
        lay.addStretch(1)
        self.values: list[int] = []

    def set_values(self, values) -> None:
        self.values = sorted(set(int(v) for v in values))
        self._rebuild()

    def _added(self, label: str) -> None:
        for minutes, text in REMINDER_CHOICES:
            if text == label and minutes not in self.values:
                self.values = sorted(self.values + [minutes])
                self._rebuild()
        self.add.blockSignals(True)
        self.add.setValue("Ajouter un rappel…")
        self.add.blockSignals(False)

    def _rebuild(self) -> None:
        while self.chips.count():
            item = self.chips.takeAt(0)
            if item.widget() is not None:
                item.widget().deleteLater()
        for minutes in self.values:
            b = kit.button(tu.fmt_duration(minutes) + "  ×", tip="Retirer ce rappel")
            b.clicked.connect(lambda _c=False, m=minutes: self._remove(m))
            self.chips.addWidget(b)

    def _remove(self, minutes: int) -> None:
        self.values = [v for v in self.values if v != minutes]
        self._rebuild()


class RuleDialog(QDialog):
    """Règle de répétition personnalisée : fréquence, intervalle, jours, fin (jamais / le / après N fois)."""

    FREQS = (("DAILY", "Jour(s)"), ("WEEKLY", "Semaine(s)"), ("MONTHLY", "Mois"), ("YEARLY", "An(s)"))
    ENDS = (("never", "Jamais"), ("until", "Le"), ("count", "Après"))

    def __init__(self, parent, rule_text: str | None, start: date, tz):
        super().__init__(parent, Qt.Dialog | Qt.FramelessWindowHint)
        from fm_theme.tokens import M
        self.setModal(True)
        self.setObjectName("AgendaRule")
        self.setAttribute(Qt.WA_StyledBackground, True)
        self.setStyleSheet(f"#AgendaRule {{ background: {M['panel_bg']}; border: 1px solid {M['panel_border']}; }}")
        self.start = start
        self.tz = tz
        try:
            rule = rec.parse_rrule(rule_text) if rule_text else rec.Rule(freq="WEEKLY",
                                                                         byday=[tu.RRULE_DAYS[start.weekday()]])
        except ValueError:
            rule = rec.Rule()
        outer = QVBoxLayout(self)
        outer.setContentsMargins(16, 14, 16, 12)
        outer.setSpacing(10)
        outer.addWidget(kit.label("Répétition personnalisée", "card_title"))
        row = QHBoxLayout()
        row.addWidget(kit.label("Tous les"))
        self.interval = kit.text_field(str(rule.interval), 50)
        row.addWidget(self.interval)
        self.freq = kit.select([l for _k, l in self.FREQS], dict(self.FREQS).get(rule.freq, "Semaine(s)"), 140)
        row.addWidget(self.freq)
        row.addStretch(1)
        outer.addLayout(row)
        days = QHBoxLayout()
        days.setSpacing(4)
        self.day_buttons = []
        plain = [d for d in rule.byday if len(d) == 2]
        for i, code in enumerate(tu.RRULE_DAYS):
            b = kit.button(tu.DAYS_SHORT[i].capitalize()[:3])
            b.setCheckable(True)
            b.setChecked(code in plain or (not plain and i == start.weekday()))
            self.day_buttons.append((code, b))
            days.addWidget(b)
        days.addStretch(1)
        self.days_holder = QWidget()
        self.days_holder.setLayout(days)
        outer.addWidget(self.days_holder)
        self.monthly = kit.select([f"Le {start.day} du mois",
                                   f"Le {rec.ORDINALS.get((start.day - 1) // 7 + 1, '')} "
                                   f"{tu.DAYS_LONG[start.weekday()]}",
                                   f"Le dernier {tu.DAYS_LONG[start.weekday()]}"],
                                  f"Le {start.day} du mois", 260)
        if rule.freq == "MONTHLY" and rule.byday:
            n, _code = rec._split_byday(rule.byday[0])
            self.monthly.setValue(self.monthly._options[2 if n == -1 else 1])
        outer.addWidget(self.monthly)
        end = QHBoxLayout()
        end.addWidget(kit.label("Fin"))
        mode = "count" if rule.count else ("until" if rule.until else "never")
        self.end_mode = kit.select([l for _k, l in self.ENDS], dict(self.ENDS)[mode], 110)
        end.addWidget(self.end_mode)
        until = rec.until_date(rule, tz) or (start + timedelta(days=90))
        self.until = kit.text_field(tu.fmt_numeric(until), 120)
        self.count = kit.text_field(str(rule.count or 10), 60)
        self.count_label = kit.label("fois", "inline_label")
        end.addWidget(self.until)
        end.addWidget(self.count)
        end.addWidget(self.count_label)
        end.addStretch(1)
        outer.addLayout(end)
        self.preview = kit.label("", "inline_label")
        self.preview.setWordWrap(True)
        outer.addWidget(self.preview)
        bar = QHBoxLayout()
        bar.addStretch(1)
        bar.addWidget(kit.button("Annuler", self.reject))
        bar.addWidget(kit.button("Valider", self.accept, accent=True))
        outer.addLayout(bar)
        for w in (self.freq, self.end_mode, self.monthly):
            w.changed.connect(lambda _v: self._sync())
        for w in (self.interval, self.until, self.count):
            w.textChanged.connect(lambda _t: self._sync())
        for _code, b in self.day_buttons:
            b.toggled.connect(lambda _on: self._sync())
        self.setMinimumWidth(440)
        self._sync()

    def _freq(self) -> str:
        return {l: k for k, l in self.FREQS}[self.freq.value()]

    def _sync(self) -> None:
        freq = self._freq()
        self.days_holder.setVisible(freq == "WEEKLY")
        self.monthly.setVisible(freq == "MONTHLY")
        mode = {l: k for k, l in self.ENDS}[self.end_mode.value()]
        self.until.setVisible(mode == "until")
        self.count.setVisible(mode == "count")
        self.count_label.setVisible(mode == "count")
        text = self.rule_text()
        self.preview.setText(rec.describe(text, self.start, self.tz) if text else "Règle incomplète")
        self.adjustSize()

    def rule_text(self) -> str | None:
        try:
            interval = max(1, int(self.interval.text() or "1"))
        except ValueError:
            return None
        rule = rec.Rule(freq=self._freq(), interval=interval)
        if rule.freq == "WEEKLY":
            rule.byday = [code for code, b in self.day_buttons if b.isChecked()] or [
                tu.RRULE_DAYS[self.start.weekday()]]
        elif rule.freq == "MONTHLY":
            idx = self.monthly._options.index(self.monthly.value())
            code = tu.RRULE_DAYS[self.start.weekday()]
            if idx == 0:
                rule.bymonthday = [self.start.day]
            elif idx == 1:
                rule.byday = [f"{(self.start.day - 1) // 7 + 1}{code}"]
            else:
                rule.byday = [f"-1{code}"]
        mode = {l: k for k, l in self.ENDS}[self.end_mode.value()]
        if mode == "count":
            try:
                rule.count = max(1, int(self.count.text()))
            except ValueError:
                return None
        elif mode == "until":
            d = tu.parse_user_date(self.until.text(), self.start)
            if d is None:
                return None
            rule.until = tu.rid_for_date(d)
        return rec.format_rrule(rule)


class EventEditor(QDialog):
    """Fenêtre d'édition. `edit(occ, draft)` -> brouillon modifié (EventRecord) ou None (annulé) ; `action`
    vaut "save", "delete" ou "duplicate"."""

    def __init__(self, service, holder, parent=None):
        super().__init__(parent, Qt.Dialog | Qt.FramelessWindowHint)
        kit.seed_look()
        from fm_theme.tokens import M
        from fm_theme.window import _PanelFrame, _SettingsTitleBar, install_extra_window
        self.service = service
        self.holder = holder
        self.action = ""
        self.draft: EventRecord | None = None
        self.occ = None
        self.setModal(True)
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        panel = _PanelFrame(self)
        panel.setColors(M["panel_bg"], M["panel_border"])
        outer.addWidget(panel)
        root = QVBoxLayout(panel)
        root.setContentsMargins(1, 1, 1, 1)
        root.setSpacing(0)
        self.titlebar = _SettingsTitleBar(self, title="Événement")
        self.titlebar.dirty_label.hide()
        self.titlebar.closeClicked.connect(self.reject)
        root.addWidget(self.titlebar)
        body = QWidget()
        body_l = QVBoxLayout(body)
        body_l.setContentsMargins(14, 12, 14, 12)
        body_l.setSpacing(8)
        self.f_title = kit.text_field("", 520, "Titre de l'événement")
        self.f_title.setFont(th.font(15, 600))
        self.f_title.setFixedHeight(32)
        body_l.addWidget(self.f_title)
        self._build_table(body_l)
        root.addWidget(body, 1)
        bar = QWidget()
        bar_l = QHBoxLayout(bar)
        bar_l.setContentsMargins(14, 9, 14, 9)
        bar_l.setSpacing(8)
        self.b_delete = kit.button("Supprimer", lambda: self._finish("delete"))
        self.b_duplicate = kit.button("Dupliquer", lambda: self._finish("duplicate"))
        self.error = QLabel("")
        self.error.setStyleSheet(f"color: {M['dirty_frame']}; background: transparent;")
        bar_l.addWidget(self.b_delete)
        bar_l.addWidget(self.b_duplicate)
        bar_l.addWidget(self.error, 1)
        bar_l.addWidget(kit.button("Annuler", self.reject))
        self.b_save = kit.button("Enregistrer", lambda: self._finish("save"), accent=True)
        bar_l.addWidget(self.b_save)
        root.addWidget(bar)
        install_extra_window(self, panel, outer, root, self.titlebar, bar)
        self.setMinimumWidth(720)

    # -- construction --

    def _build_table(self, layout) -> None:
        from fm_theme.cells import build_cells_table
        self.f_calendar = kit.select(["—"], "—", 260)
        self.f_color = ColorChooser(self.holder)
        self.f_all_day = kit.toggle(False, lambda on: self._all_day_changed(on))
        self.f_start = DateTimeField()
        self.f_end = DateTimeField()
        self.f_start.edited.connect(self._start_edited)
        self.f_end.edited.connect(self._end_edited)
        zones = list(tu.COMMON_ZONES)
        self.f_tz = kit.select(zones, zones[0], 220)
        self.f_repeat = kit.select(["Ne se répète pas"], "Ne se répète pas", 360)
        self.f_repeat.changed.connect(self._repeat_changed)
        self.f_reminders = RemindersField()
        self.f_reminders_default = kit.toggle(False)
        rem_row = QWidget()
        rl = QHBoxLayout(rem_row)
        rl.setContentsMargins(0, 0, 0, 0)
        rl.setSpacing(8)
        rl.addWidget(self.f_reminders, 1)
        self.f_rem_default_label = kit.label("Rappels du calendrier", "inline_label")
        rl.addWidget(self.f_rem_default_label)
        rl.addWidget(self.f_reminders_default)
        self.f_busy = kit.select(["Occupé", "Disponible"], "Occupé", 140)
        self.f_status = kit.select(["Confirmé", "Provisoire"], "Confirmé", 140)
        busy_row = QWidget()
        bl = QHBoxLayout(busy_row)
        bl.setContentsMargins(0, 0, 0, 0)
        bl.setSpacing(8)
        bl.addWidget(self.f_busy)
        bl.addWidget(kit.label("Statut", "inline_label"))
        bl.addWidget(self.f_status)
        bl.addStretch(1)
        self.f_location = kit.text_field("", 420, "Lieu, adresse, salle…")
        self.f_url = kit.text_field("", 420, "https://…")
        self.f_project = kit.text_field("", 220, "26014 Teaser")
        self.f_folder = kit.text_field("", 330, "F:\\PIPELINE\\…")
        browse = kit.button("…", self._browse_folder, tip="Choisir un dossier")
        folder_row = QWidget()
        fl = QHBoxLayout(folder_row)
        fl.setContentsMargins(0, 0, 0, 0)
        fl.setSpacing(6)
        fl.addWidget(self.f_folder)
        fl.addWidget(browse)
        fl.addStretch(1)
        self.f_categories = kit.text_field("", 420, "Catégories séparées par des virgules")
        self.f_attendees = kit.lines_field((), 420, 2)
        self.f_attendees.setPlaceholderText("Un participant par ligne : Nom <adresse@exemple.fr>")
        self.f_attendees.setFixedHeight(48)
        self.f_task = kit.toggle(False)
        self.f_done = kit.toggle(False)
        task_row = QWidget()
        tl = QHBoxLayout(task_row)
        tl.setContentsMargins(0, 0, 0, 0)
        tl.setSpacing(8)
        tl.addWidget(self.f_task)
        tl.addWidget(kit.label("Faite", "inline_label"))
        tl.addWidget(self.f_done)
        tl.addStretch(1)
        self.f_description = kit.lines_field((), 420, 3)
        self.f_description.setFixedHeight(58)
        self.f_notes = kit.lines_field((), 420, 2)
        self.f_notes.setFixedHeight(46)
        rows = [("Calendrier", self.f_calendar), ("Couleur", self.f_color), ("Toute la journée", self.f_all_day),
                ("Début", self.f_start), ("Fin", self.f_end), ("Fuseau horaire", self.f_tz),
                ("Répétition", self.f_repeat), ("Rappels", rem_row), ("Disponibilité", busy_row),
                ("Lieu", self.f_location), ("Lien", self.f_url), ("Projet", self.f_project),
                ("Dossier", folder_row), ("Catégories", self.f_categories), ("Participants", self.f_attendees),
                ("Tâche", task_row), ("Description", self.f_description), ("Notes", self.f_notes)]
        cells = [[(kit.label(name), "left", "center"), (field, "left", "center")] for name, field in rows]
        frame, _head, _cells = build_cells_table([("Champ", 130), ("Valeur", 0)], cells)
        self._rows = {name: (cells[i][0][0], field) for i, (name, field) in enumerate(rows)}
        layout.addWidget(frame)

    # -- remplissage --

    def edit(self, occ, draft: EventRecord, is_new: bool) -> EventRecord | None:
        self.fill(occ, draft, is_new)
        if self.exec() != QDialog.Accepted:
            return None
        return self.draft

    def fill(self, occ, draft: EventRecord, is_new: bool) -> None:
        self.occ, self.draft, self.action = occ, draft.copy(), ""
        cals = self.service.writable_calendars()
        if draft.calendar_id and all(c.id != draft.calendar_id for c in cals):
            cal = self.service.calendar(draft.calendar_id)
            if cal is not None:
                cals = [cal] + cals
        self._cals = cals
        names = [c.name for c in cals] or ["—"]
        current = self.service.calendar(draft.calendar_id)
        self.f_calendar.setOptions(names)
        self.f_calendar.setValue(current.name if current else names[0])
        self.f_calendar.changed.connect(self._calendar_changed) if not getattr(self, "_cal_wired", False) else None
        self._cal_wired = True
        self.f_title.setText(draft.title)
        self.f_color.value = draft.color
        self.f_color.calendar_color = current.color if current else "bleu"
        self.f_color.update()
        self.f_all_day.blockSignals(True)
        self.f_all_day.setChecked(draft.all_day)
        self.f_all_day.blockSignals(False)
        tz = self.service.display_tz
        if draft.all_day:
            self.f_start.set_value(draft.start_date, None)
            self.f_end.set_value(draft.end_date - timedelta(days=1), None)
        else:
            s, e = draft.start.astimezone(tz), draft.end.astimezone(tz)
            self.f_start.set_value(s.date(), (s.hour, s.minute))
            self.f_end.set_value(e.date(), (e.hour, e.minute))
        self._duration = draft.duration
        self._all_day_changed(draft.all_day, refill=False)
        zones = list(tu.COMMON_ZONES)
        tzid = draft.tzid or tu.tz_name(tz)
        if tzid not in zones:
            zones.insert(0, tzid)
        self.f_tz.setOptions(zones)
        self.f_tz.setValue(tzid)
        self._fill_repeat(draft.rrule)
        self.f_reminders.set_values(draft.reminders)
        synced = bool(current and current.source == "google")
        self.f_reminders_default.setChecked(draft.reminders_default)
        self.f_reminders_default.setVisible(synced)
        self.f_rem_default_label.setVisible(synced)
        self.f_busy.setValue("Disponible" if draft.transparency == "transparent" else "Occupé")
        self.f_status.setValue("Provisoire" if draft.status == "tentative" else "Confirmé")
        self.f_location.setText(draft.location)
        self.f_url.setText(draft.url)
        self.f_project.setText(draft.project)
        self.f_folder.setText(draft.folder)
        self.f_categories.setText(", ".join(draft.categories))
        self.f_attendees.setPlainText("\n".join(f"{a.name} <{a.email}>" if a.name else a.email
                                                for a in draft.attendees))
        self.f_task.setChecked(draft.is_task)
        self.f_done.setChecked(draft.done)
        self.f_description.setPlainText(draft.description)
        self.f_notes.setPlainText(draft.notes)
        read_only = bool(current and current.read_only)
        self.b_save.setEnabled(not read_only)
        self.b_delete.setVisible(not is_new and not read_only)
        self.b_duplicate.setVisible(not is_new)
        self.titlebar._title.setText(("Nouvel événement" if is_new else "Modifier l'événement")
                                     + (" (lecture seule)" if read_only else ""))
        self.error.setText("")
        self.adjustSize()
        QTimer.singleShot(0, self, lambda: (self.f_title.setFocus(), self.f_title.selectAll()))

    def _fill_repeat(self, rule: str | None) -> None:
        start = self.f_start.value_date() or date.today()
        options = rec.presets(start)
        labels = [label for label, _r in options]
        self._repeat_map = {label: r for label, r in options}
        current = next((label for label, r in options if r == rule), None)
        if current is None and rule:
            current = rec.describe(rule, start, self.service.display_tz)
            labels.insert(1, current)
            self._repeat_map[current] = rule
        labels.append(CUSTOM_RULE)
        self.f_repeat.setOptions(labels)
        self.f_repeat.blockSignals(True)
        self.f_repeat.setValue(current or labels[0])
        self.f_repeat.blockSignals(False)
        self._rule = rule

    def _repeat_changed(self, label: str) -> None:
        if label == CUSTOM_RULE:
            dialog = RuleDialog(self, self._rule, self.f_start.value_date() or date.today(), self.service.display_tz)
            try:
                if dialog.exec() == QDialog.Accepted and dialog.rule_text():
                    self._rule = dialog.rule_text()
            finally:
                dialog.deleteLater()
            self._fill_repeat(self._rule)
            return
        self._rule = self._repeat_map.get(label)

    def _calendar_changed(self, name: str) -> None:
        cal = next((c for c in self._cals if c.name == name), None)
        if cal is not None:
            self.f_color.calendar_color = cal.color
            self.f_color.update()
            synced = cal.source == "google"
            self.f_reminders_default.setVisible(synced)
            self.f_rem_default_label.setVisible(synced)

    def _all_day_changed(self, on: bool, refill: bool = True) -> None:
        self.f_start.set_time_visible(not on)
        self.f_end.set_time_visible(not on)
        self.f_tz.setEnabled(not on)
        if not refill:
            return
        tz = self.service.display_tz
        if on:
            s, e = self.f_start.value_date(), self.f_end.value_date()
            if s is not None and (e is None or e < s):
                self.f_end.set_value(s, None)
            self._duration = timedelta(days=max(1, ((e or s) - s).days + 1)) if s else timedelta(days=1)
            return
        s, e = self.f_start.value_dt(tz), self.f_end.value_dt(tz)
        if s is not None and (e is None or e <= s):
            minutes = int(self.service.settings.get("agenda_default_duration", 60) or 60)
            hour = int(self.service.settings.get("agenda_day_start", 8) or 8) + 1
            if (s.hour, s.minute) == (9, 0) or (s.hour, s.minute) == (0, 0):
                s = s.replace(hour=min(23, hour), minute=0)
                self.f_start.set_value(s.date(), (s.hour, s.minute))
            e = s + timedelta(minutes=minutes)
            self.f_end.set_value(e.date(), (e.hour, e.minute))
            self._duration = e - s

    def _start_edited(self) -> None:
        """La fin suit le début (même durée)."""
        tz = self.service.display_tz
        if self.f_all_day.isChecked():
            s, e = self.f_start.value_date(), self.f_end.value_date()
            days = max(0, (self._duration.days if self._duration else 1) - 1)
            if s is not None:
                self.f_end.set_value(s + timedelta(days=days), None)
        else:
            s = self.f_start.value_dt(tz)
            if s is not None and self._duration:
                e = s + self._duration
                self.f_end.set_value(e.date(), (e.hour, e.minute))
        self._fill_repeat(self._rule)

    def _end_edited(self) -> None:
        tz = self.service.display_tz
        if self.f_all_day.isChecked():
            s, e = self.f_start.value_date(), self.f_end.value_date()
            if s and e and e >= s:
                self._duration = timedelta(days=(e - s).days + 1)
        else:
            s, e = self.f_start.value_dt(tz), self.f_end.value_dt(tz)
            if s and e and e > s:
                self._duration = e - s

    def _browse_folder(self) -> None:
        path = QFileDialog.getExistingDirectory(self, "Dossier de l'événement", self.f_folder.text() or "")
        if path:
            self.f_folder.setText(path.replace("/", "\\"))

    # -- lecture --

    def _finish(self, action: str) -> None:
        if action == "save":
            draft, error = self.collect()
            if error:
                self.error.setText(error)
                return
            self.draft = draft
        self.action = action
        self.accept()

    def collect(self) -> tuple[EventRecord | None, str]:
        d = self.draft.copy()
        d.title = self.f_title.text().strip()
        cal = next((c for c in self._cals if c.name == self.f_calendar.value()), None)
        if cal is None:
            return None, "Choisir un calendrier."
        d.calendar_id = cal.id
        d.color = self.f_color.value
        d.all_day = self.f_all_day.isChecked()
        tzid = self.f_tz.value()
        tz = tu.get_tz(tzid)
        if d.all_day:
            s, e = self.f_start.value_date(), self.f_end.value_date()
            if s is None or e is None:
                return None, "Date illisible."
            if e < s:
                return None, "La fin précède le début."
            d.start_date, d.end_date = s, e + timedelta(days=1)
            d.start = d.end = None
        else:
            s = self.f_start.value_dt(self.service.display_tz)
            e = self.f_end.value_dt(self.service.display_tz)
            if s is None or e is None:
                return None, "Date ou heure illisible."
            if e < s or (e == s and not self.f_task.isChecked()):
                return None, "La fin doit suivre le début."
            d.start, d.end = s.astimezone(tz), e.astimezone(tz)
            d.start_date = d.end_date = None
        d.tzid = tzid
        d.rrule = self._rule
        d.reminders = list(self.f_reminders.values)
        d.reminders_default = self.f_reminders_default.isChecked() and self.f_reminders_default.isVisible()
        d.transparency = "transparent" if self.f_busy.value() == "Disponible" else "opaque"
        d.status = "tentative" if self.f_status.value() == "Provisoire" else "confirmed"
        d.location = self.f_location.text().strip()
        d.url = self.f_url.text().strip()
        d.project = self.f_project.text().strip()
        d.folder = self.f_folder.text().strip()
        d.categories = [c.strip() for c in self.f_categories.text().split(",") if c.strip()]
        attendees, bad = [], []
        for line in self.f_attendees.toPlainText().splitlines():
            line = line.strip()
            if not line:
                continue
            a = parse_attendee(line)
            if a is None:
                bad.append(line)
            else:
                old = next((x for x in self.draft.attendees if x.email.lower() == a.email.lower()), None)
                if old is not None:
                    a.status, a.organizer, a.is_self, a.optional = old.status, old.organizer, old.is_self, old.optional
                attendees.append(a)
        if bad:
            return None, f"Participant illisible : {bad[0]}"
        d.attendees = attendees
        d.is_task = self.f_task.isChecked()
        d.done = self.f_done.isChecked() and d.is_task
        d.description = self.f_description.toPlainText().rstrip()
        d.notes = self.f_notes.toPlainText().rstrip()
        errors = d.validate()
        if errors:
            return None, "Événement invalide : " + ", ".join(errors)
        return d, ""

    anchor = None                                        # widget sur lequel centrer la fenêtre (le panneau)

    def showEvent(self, event):
        super().showEvent(event)
        anchor = self.anchor
        try:
            if anchor is not None and anchor.isVisible():
                host = anchor.window().frameGeometry()
                self.move(host.center() - self.rect().center())
        except RuntimeError:
            pass

    def keyPressEvent(self, event):
        if event.key() in (Qt.Key_Return, Qt.Key_Enter) and event.modifiers() & Qt.ControlModifier:
            self._finish("save")
            return
        if event.key() in (Qt.Key_Return, Qt.Key_Enter) and QApplication.focusWidget() is self.f_title:
            self._finish("save")
            return
        super().keyPressEvent(event)


def parse_attendee(text: str) -> Attendee | None:
    import re
    m = re.fullmatch(r"\s*(.*?)\s*<\s*([^<>\s]+@[^<>\s]+)\s*>\s*", text)
    if m:
        return Attendee(email=m.group(2), name=m.group(1).strip('"'))
    if re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", text):
        return Attendee(email=text)
    return None
