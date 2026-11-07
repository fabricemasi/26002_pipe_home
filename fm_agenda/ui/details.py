"""Panneau de détails de la vue Jour d'après le design (`.det`, `.drow`) : calendrier (point + nom), titre, quand,
lignes « clé / valeur » (Projet, Dossier, Lieu, Lien, Répétition, Rappels, Participants, Notes), boutons « Ouvrir
le dossier » et « Modifier ». Libellés posés une fois, textes changés sur place (aucune reconstruction)."""
from __future__ import annotations

from PySide6.QtCore import QRectF, Qt, Signal
from PySide6.QtGui import QPainter
from PySide6.QtWidgets import QHBoxLayout, QLabel, QSizePolicy, QVBoxLayout, QWidget

from ..core import recurrence as rec
from ..core import timeutil as tu
from ..core.model import Occurrence
from . import theme as th
from .context import ViewContext
from .widgets import AgendaButton

ROWS = ("Projet", "Dossier", "Lieu", "Lien", "Répétition", "Rappels", "Participants", "Notes")


class _Dot(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.color = None
        self.setFixedSize(10, 10)

    def paintEvent(self, event):
        if self.color is None:
            return
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing, True)
        p.setPen(Qt.NoPen)
        p.setBrush(self.color)
        p.drawEllipse(QRectF(0, 0, 10, 10))


class _Row(QWidget):
    def __init__(self, key: str, ctx: ViewContext, parent=None):
        super().__init__(parent)
        self.ctx = ctx
        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, 9, 0, 9)
        lay.setSpacing(10)
        self.key = QLabel(key)
        self.key.setFixedWidth(64)
        self.key.setAlignment(Qt.AlignLeft | Qt.AlignTop)
        self.value = QLabel("")
        self.value.setWordWrap(True)
        self.value.setTextInteractionFlags(Qt.TextSelectableByMouse | Qt.LinksAccessibleByMouse)
        self.value.setOpenExternalLinks(False)
        self.value.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        lay.addWidget(self.key, 0, Qt.AlignTop)
        lay.addWidget(self.value, 1)

    def paintEvent(self, event):
        p = QPainter(self)
        p.fillRect(QRectF(0, 0, self.width(), 1), self.ctx.t.c("line"))


class DetailsPanel(QWidget):
    editRequested = Signal(object)
    openFolder = Signal(str)
    linkActivated = Signal(str)

    def __init__(self, ctx: ViewContext, parent=None):
        super().__init__(parent)
        self.ctx = ctx
        self.occ: Occurrence | None = None
        self.setObjectName("AgendaDetails")
        self.setAttribute(Qt.WA_StyledBackground, True)
        m = ctx.t.m
        self.setMinimumWidth(m["details_min"])
        self.setMaximumWidth(m["details_max"])
        lay = QVBoxLayout(self)
        lay.setContentsMargins(20, 18, 20, 18)
        lay.setSpacing(0)
        head = QHBoxLayout()
        head.setContentsMargins(0, 0, 0, 8)
        head.setSpacing(8)
        self.dot = _Dot()
        self.cal_label = QLabel("")
        head.addWidget(self.dot, 0, Qt.AlignVCenter)
        head.addWidget(self.cal_label, 1)
        lay.addLayout(head)
        self.title = QLabel("")
        self.title.setWordWrap(True)
        self.title.setTextInteractionFlags(Qt.TextSelectableByMouse)
        lay.addWidget(self.title)
        lay.addSpacing(4)
        self.when = QLabel("")
        self.when.setWordWrap(True)
        lay.addWidget(self.when)
        lay.addSpacing(14)
        self.rows = {k: _Row(k, ctx) for k in ROWS}
        for row in self.rows.values():
            row.value.linkActivated.connect(self.linkActivated)
            lay.addWidget(row)
        buttons = QHBoxLayout()
        buttons.setContentsMargins(0, 16, 0, 0)
        buttons.setSpacing(8)
        self.b_folder = AgendaButton(ctx.holder, "Ouvrir le dossier")
        self.b_edit = AgendaButton(ctx.holder, "Modifier")
        self.b_folder.clicked.connect(lambda: self.openFolder.emit(self._folder))
        self.b_edit.clicked.connect(lambda: self.occ and self.editRequested.emit(self.occ))
        buttons.addWidget(self.b_folder)
        buttons.addWidget(self.b_edit)
        buttons.addStretch(1)
        lay.addLayout(buttons)
        self.empty = QLabel("Aucun événement ce jour-là.")
        self.empty.setWordWrap(True)
        lay.addWidget(self.empty)
        lay.addStretch(1)
        self._folder = ""
        self.restyle()
        self.show_occurrence(None)

    def restyle(self) -> None:
        """Couleurs : feuille du panneau (`AgendaPane.restyle` : `dMuted`, `dStrong`, `dDim`) ; ici les polices."""
        self.cal_label.setFont(th.font(12))
        self.title.setFont(th.font(17, 600))
        self.when.setFont(th.font(13))
        self.empty.setFont(th.font(13))
        for label, role in ((self.cal_label, "dMuted"), (self.title, "dStrong"), (self.when, "dMuted"),
                            (self.empty, "dDim")):
            label.setObjectName(role)
        for key, row in self.rows.items():
            row.key.setFont(th.font(12))
            row.key.setObjectName("dDim")
            row.value.setFont(th.font(12, mono=True) if key == "Dossier" else th.font(13))
        self.update()

    def paintEvent(self, event):
        super().paintEvent(event)
        p = QPainter(self)
        p.fillRect(QRectF(0, 0, 1, self.height()), self.ctx.t.c("line"))

    def show_occurrence(self, occ: Occurrence | None, empty_text: str = "Aucun événement ce jour-là.") -> None:
        self.occ = occ
        has = occ is not None
        for w in (self.dot, self.cal_label, self.title, self.when, self.b_edit):
            w.setVisible(has)
        self.empty.setVisible(not has)
        self.empty.setText(empty_text)
        if not has:
            for row in self.rows.values():
                row.hide()
            self.b_folder.hide()
            return
        ctx = self.ctx
        self.dot.color = ctx.colors(occ)[1]
        self.dot.update()
        self.cal_label.setText(ctx.calendar_name(occ.calendar_id) + ("  ·  lecture seule" if occ.read_only else ""))
        self.title.setText(occ.title or "(Sans titre)")
        self.when.setText(when_text(occ, ctx.h24))
        ev = None
        try:
            ev = ctx.service.get_event(occ.event_id)
        except Exception:                                # noqa: BLE001
            ev = None
        series = ev
        if ev is not None and ev.series_id:
            series = ctx.service.get_event(ev.series_id) or ev
        folder = occ.folder or (ev.folder if ev else "")
        if not folder and occ.project:
            hook = ctx.settings.get("_project_folder")
            folder = hook(occ.project) if callable(hook) else ""
        self._folder = folder
        values = {
            "Projet": occ.project or "—",
            "Dossier": folder,
            "Lieu": occ.location,
            "Lien": f"<a href='{_esc(ev.url)}' style='color:{ctx.t.hexc('link')}'>{_esc(ev.url)}</a>"
            if ev and ev.url else "",
            "Répétition": rec.describe(series.rrule, series.start_date if series.all_day else series.start,
                                       ctx.tz) if series is not None and series.rrule else "",
            "Rappels": ", ".join(tu.fmt_duration(m) for m in sorted(ev.reminders)) if ev and ev.reminders else "",
            "Participants": ", ".join(a.name or a.email for a in ev.attendees) if ev and ev.attendees else "",
            "Notes": "\n\n".join(v for v in ((ev.description if ev else ""), (ev.notes if ev else "")) if v),
        }
        for key, row in self.rows.items():
            value = values.get(key, "")
            row.setVisible(bool(value) or key == "Projet")
            if key == "Lien":
                row.value.setTextFormat(Qt.RichText)
            elif key == "Dossier":
                value = value.replace("\\", "\\​").replace("/", "/​")   # coupure possible (anywhere)
            row.value.setText(value)
        self.b_folder.setVisible(bool(folder))
        self.b_edit.setEnabled(True)
        self.b_edit.setText("Voir" if occ.read_only else "Modifier")


def when_text(occ: Occurrence, h24: bool = True) -> str:
    days = occ.days()
    if occ.all_day or occ.spans_days():
        if len(days) > 1:
            a, b = days[0], days[-1]
            return f"Du {a.day} {tu.MONTHS_SHORT[a.month - 1]} au {b.day} {tu.MONTHS_SHORT[b.month - 1]} · toute la journée"
        d = days[0]
        return f"{tu.cap(tu.DAYS_LONG[d.weekday()])} {d.day} {tu.MONTHS[d.month - 1]} · toute la journée"
    d = occ.start.date()
    head = f"{tu.cap(tu.DAYS_LONG[d.weekday()])} {d.day} {tu.MONTHS[d.month - 1]}"
    if occ.is_task and occ.end == occ.start:
        return f"{head} · tâche à {tu.fmt_time(occ.start, h24)}"
    if occ.end.date() != d:
        e = occ.end.date()
        return f"{head} {tu.fmt_time(occ.start, h24)} – {e.day} {tu.MONTHS_SHORT[e.month - 1]} {tu.fmt_time(occ.end, h24)}"
    return f"{head} · {tu.fmt_range(occ.start, occ.end, h24)}"


def _esc(text: str) -> str:
    return (text or "").replace("&", "&amp;").replace("<", "&lt;").replace("'", "&#39;")
