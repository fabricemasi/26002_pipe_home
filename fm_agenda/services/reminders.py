"""Rappels de l'agenda : planificateur (tant que PIPE FMZ tourne, agenda ouvert ou non) et notifications.

- Toutes les 30 s, et à l'instant exact du prochain rappel (minuteur unique), les événements à rappels de la
  fenêtre [maintenant - rattrapage, maintenant + horizon] sont déroulés (séries comprises) ; chaque rappel dû est
  montré UNE fois : `reminder_log` (base) retient les rappels déjà montrés, même après une relance.
- Rattrapage : un rappel tombé pendant que l'appli était fermée est montré au lancement s'il date de moins de
  `agenda_missed_minutes` (« manqué »).
- Notification : Windows (icône de la zone de notification : notification native de Windows 10 / 11) et / ou
  fenêtre de rappel de l'appli (Ouvrir, Reporter, Fermer), selon `agenda_notify_mode`.
- Événement « journée » : le rappel compte à partir de 9:00 le jour même (« 1 jour avant » = la veille à 9:00).

Appli FERMÉE : aucun rappel (il faudrait un service Windows ou une tâche planifiée : voir docs/agents/fm_agenda.md,
« Rappels appli fermée »)."""
from __future__ import annotations

import logging
import time
from datetime import date, datetime, timedelta

from PySide6.QtCore import QObject, QRectF, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QGuiApplication, QIcon, QPainter, QPixmap
from PySide6.QtWidgets import QHBoxLayout, QLabel, QSystemTrayIcon, QVBoxLayout, QWidget

from ..core import timeutil as tu

log = logging.getLogger("fm_agenda.reminders")

HORIZON_H = 36
MAX_LEAD_MIN = 40320                  # 4 semaines : rappel le plus lointain pris en compte
ALL_DAY_HOUR = 9


class Due:
    """Un rappel à montrer."""
    __slots__ = ("occ", "minutes", "trigger", "missed")

    def __init__(self, occ, minutes: int, trigger: float, missed: bool):
        self.occ, self.minutes, self.trigger, self.missed = occ, minutes, trigger, missed

    @property
    def key(self) -> str:
        return self.occ.key


def occurrence_base(occ, tz) -> datetime:
    if occ.all_day:
        return tu.localize(datetime(occ.start_date.year, occ.start_date.month, occ.start_date.day, ALL_DAY_HOUR), tz)
    return occ.start


def compute_due(service, now: float, missed_s: float, horizon_s: float,
                seen: set | None = None) -> tuple[list[Due], float | None]:
    """(rappels dus, prochain déclenchement futur) — sans effet de bord. `seen` : rappels montrés pas encore
    écrits par le fil d'écriture."""
    seen = seen or set()
    tz = service.display_tz
    lo = now - max(missed_s, 60)
    rows = service.reminder_rows(int(lo) - 86400, int(now + horizon_s + MAX_LEAD_MIN * 60))
    if not rows:
        return [], None
    by_id = {r.id: r for r in rows}
    d0 = datetime.fromtimestamp(lo, tz).date() - timedelta(days=1)
    d1 = datetime.fromtimestamp(now + horizon_s + MAX_LEAD_MIN * 60, tz).date() + timedelta(days=1)
    due, upcoming = [], None
    for occ in service.expand_rows(rows, d0, d1):
        if occ.status == "cancelled":
            continue
        rec = by_id.get(occ.event_id)
        if rec is None:
            continue
        minutes = list(rec.reminders)
        if rec.reminders_default:
            cal = service.calendar(rec.calendar_id)
            minutes += cal.default_reminders if cal is not None else []
        if not minutes:
            continue
        base = occurrence_base(occ, tz).timestamp()
        for m in sorted(set(int(x) for x in minutes)):
            trigger = base - m * 60
            if trigger <= now:
                if trigger >= lo and (occ.key, m) not in seen and not service.reminder_fired(occ.key, m):
                    due.append(Due(occ, m, trigger, missed=now - trigger > 90))
            elif upcoming is None or trigger < upcoming:
                upcoming = trigger
    due.sort(key=lambda d: d.trigger)
    return due, upcoming


def _calendar_icon(color: str = "#3f6f9f") -> QIcon:
    pix = QPixmap(64, 64)
    pix.fill(Qt.transparent)
    p = QPainter(pix)
    p.setRenderHint(QPainter.Antialiasing, True)
    p.setBrush(QColor("#16181a"))
    p.setPen(QColor(color))
    p.drawRoundedRect(QRectF(6, 10, 52, 48), 8, 8)
    p.fillRect(QRectF(7, 11, 50, 12), QColor(color))
    p.setPen(QColor("#eef0f2"))
    f = p.font()
    f.setPixelSize(24)
    f.setBold(True)
    p.setFont(f)
    p.drawText(QRectF(6, 24, 52, 32), Qt.AlignCenter, str(date.today().day))
    p.end()
    return QIcon(pix)


class ReminderToast(QWidget):
    """Fenêtre de rappel de l'appli (coin bas-droit de l'écran), aux couleurs du thème de l'agenda."""

    def __init__(self, scheduler: "ReminderScheduler", due: Due):
        super().__init__(None, Qt.Tool | Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint)
        from ..ui import theme as th
        from ..ui.widgets import AgendaButton, ThemeHolder
        self.setAttribute(Qt.WA_DeleteOnClose, True)
        self.setAttribute(Qt.WA_ShowWithoutActivating, True)
        self.scheduler = scheduler
        self.due = due
        settings = scheduler.service.settings
        self.holder = ThemeHolder(th.from_settings(settings))
        t = self.holder.t
        self.setObjectName("AgendaToast")
        self.setAttribute(Qt.WA_StyledBackground, True)
        self.setStyleSheet(f"#AgendaToast {{ background: {t.hexc('side')}; border: 1px solid {t.hexc('line')}; "
                           f"border-radius: 8px; }}")
        lay = QVBoxLayout(self)
        lay.setContentsMargins(16, 12, 16, 12)
        lay.setSpacing(4)
        occ = due.occ
        head = QLabel(("Rappel manqué · " if due.missed else "Rappel · ") + scheduler.service.calendar(
            occ.calendar_id).name if scheduler.service.calendar(occ.calendar_id) else "Rappel")
        head.setFont(th.font(11, 700))
        head.setStyleSheet(f"color: {t.hexc('section')}; background: transparent;")
        title = QLabel(occ.title or "(Sans titre)")
        title.setWordWrap(True)
        title.setFont(th.font(15, 600))
        title.setStyleSheet(f"color: {t.hexc('strong')}; background: transparent;")
        when = QLabel(scheduler.when_text(due))
        when.setFont(th.font(12))
        when.setStyleSheet(f"color: {t.hexc('muted')}; background: transparent;")
        lay.addWidget(head)
        lay.addWidget(title)
        lay.addWidget(when)
        if occ.location:
            where = QLabel(occ.location)
            where.setFont(th.font(12))
            where.setStyleSheet(f"color: {t.hexc('dim')}; background: transparent;")
            lay.addWidget(where)
        row = QHBoxLayout()
        row.setContentsMargins(0, 8, 0, 0)
        row.setSpacing(8)
        snooze = int(settings.get("agenda_snooze_minutes", 5) or 5)
        b_open = AgendaButton(self.holder, "Ouvrir", kind="primary")
        b_snooze = AgendaButton(self.holder, f"Reporter {snooze} min")
        b_close = AgendaButton(self.holder, "Fermer")
        b_open.clicked.connect(self._open)
        b_snooze.clicked.connect(lambda: (scheduler.snooze(due, snooze), self.close()))
        b_close.clicked.connect(self.close)
        for b in (b_open, b_snooze, b_close):
            row.addWidget(b)
        row.addStretch(1)
        lay.addLayout(row)
        self.setFixedWidth(340)

    def _open(self):
        occ = self.due.occ
        self.scheduler.openRequested.emit(occ.start_date if occ.all_day else occ.start.date(), occ.key)
        self.close()

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


class ReminderScheduler(QObject):
    fired = Signal(object)                    # Due (tests, journal)
    openRequested = Signal(object, object)    # jour, clé d'occurrence

    def __init__(self, service, parent=None, clock=time.time):
        super().__init__(parent)
        self.service = service
        self.clock = clock
        self.toasts: list[ReminderToast] = []
        self._tray: QSystemTrayIcon | None = None
        self._tick = QTimer(self)
        self._tick.setInterval(30_000)
        self._tick.timeout.connect(self.check)
        self._next = QTimer(self)
        self._next.setSingleShot(True)
        self._next.timeout.connect(self.check)
        self._snoozed: list[tuple[float, Due]] = []
        self._seen: set = set()
        self._first = True
        service.changed.connect(self._soon)

    def start(self) -> None:
        self._tick.start()
        QTimer.singleShot(1500, self, self.check)

    def stop(self) -> None:
        self._tick.stop()
        self._next.stop()
        for toast in list(self.toasts):
            toast.close()
        if self._tray is not None:
            self._tray.hide()

    def settings_changed(self, settings: dict) -> None:
        self._soon()

    def _soon(self) -> None:
        if self._tick.isActive() and not self._next.isActive():
            self._next.start(800)

    def enabled(self) -> bool:
        return bool(self.service.settings.get("agenda_reminders_enabled", True))

    def check(self) -> list[Due]:
        if not self.enabled() or getattr(self.service, "_closed", False):
            return []
        now = self.clock()
        missed = float(self.service.settings.get("agenda_missed_minutes", 30) or 0) * 60 if self._first else 120.0
        self._first = False
        try:
            due, upcoming = compute_due(self.service, now, missed, HORIZON_H * 3600, self._seen)
        except Exception:                                # noqa: BLE001 - un rappel raté ne doit rien casser
            log.exception("calcul des rappels")
            return []
        for when, item in list(self._snoozed):
            if when <= now:
                self._snoozed.remove((when, item))
                due.append(item)
            elif upcoming is None or when < upcoming:
                upcoming = when
        for item in due:
            self.notify(item)
        if upcoming is not None:
            delay = max(1.0, min(upcoming - now + 0.5, 1800.0))
            self._next.start(int(delay * 1000))
        return due

    def notify(self, item: Due) -> None:
        self._seen.add((item.key, item.minutes))
        self.service.mark_reminder(item.key, item.minutes)
        self.fired.emit(item)
        mode = self.service.settings.get("agenda_notify_mode", "both")
        if mode in ("both", "windows"):
            self._system_notification(item)
        if mode in ("both", "app") and QGuiApplication.platformName() != "offscreen":
            toast = ReminderToast(self, item)
            self.toasts.append(toast)
            toast.place(len(self.toasts) - 1)
            toast.show()

    def restack(self) -> None:
        for i, toast in enumerate(self.toasts):
            toast.place(i)

    def snooze(self, item: Due, minutes: int) -> None:
        self._snoozed.append((self.clock() + minutes * 60, Due(item.occ, item.minutes, item.trigger, False)))
        self._next.start(int(minutes * 60 * 1000))

    def when_text(self, item: Due) -> str:
        occ = item.occ
        h24 = str(self.service.settings.get("agenda_time_format", "24")) != "12"
        if occ.all_day:
            return f"{tu.fmt_day_short(occ.start_date)} · toute la journée"
        start = occ.start
        delta = (start.timestamp() - self.clock()) / 60
        if delta > 1:
            rel = f"dans {int(round(delta))} min" if delta < 60 else (
                f"dans {int(delta // 60)} h {int(delta % 60):02d}" if delta < 1440 else tu.fmt_day_short(start.date()))
        elif delta > -1:
            rel = "maintenant"
        else:
            rel = "commencé"
        return f"{tu.fmt_range(start, occ.end, h24) if occ.end > start else tu.fmt_time(start, h24)} · {rel}"

    def _system_notification(self, item: Due) -> None:
        if not QSystemTrayIcon.isSystemTrayAvailable() or QGuiApplication.platformName() == "offscreen":
            return
        if self._tray is None:
            self._tray = QSystemTrayIcon(_calendar_icon(), self)
            self._tray.setToolTip("PIPE FMZ — Agenda")
            self._tray.messageClicked.connect(lambda: self._last and self.openRequested.emit(
                self._last.occ.start_date if self._last.occ.all_day else self._last.occ.start.date(),
                self._last.occ.key))
        self._last = item
        self._tray.show()
        title = ("Rappel manqué : " if item.missed else "") + (item.occ.title or "(Sans titre)")
        self._tray.showMessage(title, self.when_text(item) + (f"\n{item.occ.location}" if item.occ.location else ""),
                               _calendar_icon(), 15000)
        QTimer.singleShot(60_000, self, lambda: self._tray and not self.toasts and self._tray.hide())

    _last = None
