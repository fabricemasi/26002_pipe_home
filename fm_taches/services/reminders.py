"""Rappels des tâches : planificateur (tant que PIPE FMZ tourne, module Tâches ouvert ou non) et notifications.

- Déclenchements : rappel explicite de la tâche (`reminder_at`, panneau de détails), sinon l'heure d'échéance d'une
  tâche à heure (`taches_remind_at_due`). Tâches à faire seulement. Rien chez Google (Google Tasks n'a pas de rappel).
- Calcul par les INDEX du service (tâches à rappel, échéances par date) toutes les 30 s et à l'instant exact du
  prochain rappel (minuteur unique) ; recalcul peu après une modification. Chaque rappel n'est montré qu'UNE fois
  (`reminder_log`, même après une relance) ; un rappel tombé appli fermée est montré au lancement s'il date de
  moins de `taches_missed_minutes` (« manqué »).
- Notification Windows (icône de la zone de notification) et / ou fenêtre de rappel de l'appli (Ouvrir, Terminer,
  Reporter, Fermer), selon `taches_notify_mode` — même aspect que les rappels de l'agenda.

Appli FERMÉE : aucun rappel (comme l'agenda : docs/agents/fm_agenda.md, « Rappels appli fermée »)."""
from __future__ import annotations

import logging
import time
from datetime import datetime

from PySide6.QtCore import QObject, QPointF, QRectF, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QGuiApplication, QIcon, QPainter, QPen, QPixmap
from PySide6.QtWidgets import QHBoxLayout, QLabel, QSystemTrayIcon, QVBoxLayout, QWidget

from fm_agenda.core import timeutil as tu

log = logging.getLogger("fm_taches.reminders")

HORIZON_S = 36 * 3600


class Due:
    __slots__ = ("task", "trigger", "missed")

    def __init__(self, task, trigger: float, missed: bool):
        self.task, self.trigger, self.missed = task, trigger, missed


def _task_icon() -> QIcon:
    pix = QPixmap(64, 64)
    pix.fill(Qt.transparent)
    p = QPainter(pix)
    p.setRenderHint(QPainter.Antialiasing, True)
    p.setBrush(QColor("#16181a"))
    p.setPen(QPen(QColor("#3f6f9f"), 3))
    p.drawRoundedRect(QRectF(8, 8, 48, 48), 10, 10)
    p.setPen(QPen(QColor("#eef0f2"), 6, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))
    p.drawPolyline([QPointF(18, 33), QPointF(28, 43), QPointF(46, 22)])
    p.end()
    return QIcon(pix)


def when_text(task, trigger: float, now: float) -> str:
    parts = []
    if task.due:
        parts.append(tu.fmt_day_short(task.due) + (f" · {task.due_time}" if task.due_time else ""))
    delta = (trigger - now) / 60
    if delta < -1:
        parts.append("rappel " + datetime.fromtimestamp(trigger).strftime("%H:%M"))
    return " · ".join(parts) or "Rappel"


class ReminderToast(QWidget):
    """Fenêtre de rappel (coin bas-droit de l'écran), aux couleurs du thème des tâches."""

    def __init__(self, scheduler: "TaskReminders", due: Due):
        super().__init__(None, Qt.Tool | Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint)
        from fm_agenda.ui.widgets import AgendaButton, ThemeHolder
        from ..ui import theme as th
        self.setAttribute(Qt.WA_DeleteOnClose, True)
        self.setAttribute(Qt.WA_ShowWithoutActivating, True)
        self.scheduler = scheduler
        self.due = due
        settings = scheduler.service.settings
        self.holder = ThemeHolder(th.from_settings(settings))
        t = self.holder.t
        self.setObjectName("TachesToast")
        self.setAttribute(Qt.WA_StyledBackground, True)
        self.setStyleSheet(f"#TachesToast {{ background: {t.hexc('side')}; border: 1px solid {t.hexc('line')}; "
                           f"border-radius: 8px; }}")
        lay = QVBoxLayout(self)
        lay.setContentsMargins(16, 12, 16, 12)
        lay.setSpacing(4)
        task = due.task
        lst = scheduler.service.get_list(task.list_id)
        head = QLabel(("Rappel manqué · " if due.missed else "Tâche · ") + (lst.name if lst else ""))
        head.setFont(th.font(11, 700))
        head.setStyleSheet(f"color: {t.hexc('section')}; background: transparent;")
        title = QLabel(task.title or "Sans titre")
        title.setWordWrap(True)
        title.setFont(th.font(15, 600))
        title.setStyleSheet(f"color: {t.hexc('strong')}; background: transparent;")
        when = QLabel(when_text(task, due.trigger, scheduler.clock()))
        when.setFont(th.font(12))
        when.setStyleSheet(f"color: {t.hexc('muted')}; background: transparent;")
        for w in (head, title, when):
            lay.addWidget(w)
        if task.notes.strip():
            note = QLabel(task.notes.strip().splitlines()[0])
            note.setFont(th.font(12))
            note.setStyleSheet(f"color: {t.hexc('dim')}; background: transparent;")
            lay.addWidget(note)
        row = QHBoxLayout()
        row.setContentsMargins(0, 8, 0, 0)
        row.setSpacing(8)
        snooze = int(settings.get("taches_snooze_minutes", 10) or 10)
        b_open = AgendaButton(self.holder, "Ouvrir", kind="primary")
        b_done = AgendaButton(self.holder, "Terminer")
        b_snooze = AgendaButton(self.holder, f"+{snooze} min", tip=f"Reporter de {snooze} minutes")
        b_close = AgendaButton(self.holder, "Fermer")
        b_open.clicked.connect(lambda: (scheduler.openRequested.emit(task.id), self.close()))
        b_done.clicked.connect(lambda: (scheduler.service.set_done(task.id, True), self.close()))
        b_snooze.clicked.connect(lambda: (scheduler.snooze(due, snooze), self.close()))
        b_close.clicked.connect(self.close)
        for b in (b_open, b_done, b_snooze, b_close):
            row.addWidget(b)
        row.addStretch(1)
        lay.addLayout(row)
        self.setFixedWidth(360)

    def place(self, index: int) -> None:
        self.adjustSize()
        screen = QGuiApplication.primaryScreen()
        if screen is None:
            return
        area = screen.availableGeometry()
        self.move(area.right() - self.width() - 16, area.bottom() - (self.height() + 10) * (index + 1) - 6)

    def closeEvent(self, event):
        if self in self.scheduler.toasts:
            self.scheduler.toasts.remove(self)
            self.scheduler.restack()
        super().closeEvent(event)


class TaskReminders(QObject):
    fired = Signal(object)                    # Due (tests, journal)
    openRequested = Signal(str)               # id de la tâche

    def __init__(self, service, parent=None, clock=time.time):
        super().__init__(parent)
        self.service = service
        self.clock = clock
        self.toasts: list[ReminderToast] = []
        self._tray: QSystemTrayIcon | None = None
        self._last: Due | None = None
        self._tick = QTimer(self)
        self._tick.setInterval(30_000)
        self._tick.timeout.connect(self.check)
        self._next = QTimer(self)
        self._next.setSingleShot(True)
        self._next.timeout.connect(self.check)
        self._snoozed: list[tuple[float, Due]] = []
        self._first = True
        service.changed.connect(self._soon)

    def start(self) -> None:
        self._tick.start()
        QTimer.singleShot(2000, self, self.check)

    def stop(self) -> None:
        self._tick.stop()
        self._next.stop()
        for toast in list(self.toasts):
            toast.close()
        if self._tray is not None:
            self._tray.hide()

    def settings_changed(self, _settings: dict) -> None:
        self._soon()

    def _soon(self, *_args) -> None:
        if self._tick.isActive() and not self._next.isActive():
            self._next.start(800)

    def check(self) -> list[Due]:
        s = self.service.settings
        if not s.get("taches_reminders_enabled", True) or getattr(self.service, "_closed", False):
            return []
        now = self.clock()
        missed = float(s.get("taches_missed_minutes", 60) or 0) * 60 if self._first else 120.0
        self._first = False
        due, upcoming = [], None
        try:
            for trigger, task in self.service.reminder_candidates(now - max(missed, 60), now + HORIZON_S,
                                                                  bool(s.get("taches_remind_at_due", True))):
                if trigger <= now:
                    if not self.service.reminder_fired(task.id, trigger):
                        due.append(Due(task, trigger, missed=now - trigger > 90))
                elif upcoming is None or trigger < upcoming:
                    upcoming = trigger
        except Exception:                                # noqa: BLE001 - un rappel raté ne doit rien casser
            log.exception("calcul des rappels des tâches")
            return []
        for when, item in list(self._snoozed):
            if when <= now:
                self._snoozed.remove((when, item))
                current = self.service.get(item.task.id)
                if current is not None and not current.done:
                    due.append(Due(current, item.trigger, False))
            elif upcoming is None or when < upcoming:
                upcoming = when
        for item in due:
            self.notify(item)
        if upcoming is not None:
            self._next.start(int(max(1.0, min(upcoming - now + 0.5, 1800.0)) * 1000))
        return due

    def notify(self, item: Due) -> None:
        self.service.mark_reminder(item.task.id, item.trigger)
        self.fired.emit(item)
        mode = self.service.settings.get("taches_notify_mode", "both")
        offscreen = QGuiApplication.platformName() == "offscreen"
        if mode in ("both", "windows"):
            self._system_notification(item)
        if mode in ("both", "app") and not offscreen:
            toast = ReminderToast(self, item)
            self.toasts.append(toast)
            toast.place(len(self.toasts) - 1)
            toast.show()

    def restack(self) -> None:
        for i, toast in enumerate(self.toasts):
            toast.place(i)

    def snooze(self, item: Due, minutes: int) -> None:
        self._snoozed.append((self.clock() + minutes * 60, item))
        self._next.start(int(minutes * 60 * 1000))

    def _system_notification(self, item: Due) -> None:
        if not QSystemTrayIcon.isSystemTrayAvailable() or QGuiApplication.platformName() == "offscreen":
            return
        if self._tray is None:
            self._tray = QSystemTrayIcon(_task_icon(), self)
            self._tray.setToolTip("PIPE FMZ — Tâches")
            self._tray.messageClicked.connect(lambda: self._last and self.openRequested.emit(self._last.task.id))
        self._last = item
        self._tray.show()
        title = ("Rappel manqué : " if item.missed else "") + (item.task.title or "Sans titre")
        self._tray.showMessage(title, when_text(item.task, item.trigger, self.clock()), _task_icon(), 15000)
        QTimer.singleShot(60_000, self, lambda: self._tray and not self.toasts and self._tray.hide())
