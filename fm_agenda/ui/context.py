"""Contexte partagé par les vues : service, thème, réglages d'affichage, heure courante (fuseau d'affichage)."""
from __future__ import annotations

from datetime import date, datetime

from ..core.model import Occurrence
from .widgets import ThemeHolder


class ViewContext:
    def __init__(self, service, holder: ThemeHolder, settings: dict):
        self.service = service
        self.holder = holder
        self.settings = settings
        self.zoom = float(service.pref("hour_zoom", 1.0) or 1.0) if service is not None else 1.0
        self._now_override: datetime | None = None      # tests : heure figée

    @property
    def t(self):
        return self.holder.t

    @property
    def tz(self):
        return self.service.display_tz

    def now(self) -> datetime:
        if self._now_override is not None:
            return self._now_override.astimezone(self.tz)
        return datetime.now(self.tz)

    def today(self) -> date:
        return self.now().date()

    def s(self, key: str, default=None):
        value = self.settings.get(key, default)
        return default if value is None else value

    @property
    def h24(self) -> bool:
        return str(self.s("agenda_time_format", "24")) != "12"

    @property
    def first_weekday(self) -> int:
        return int(self.s("agenda_first_weekday", 0)) % 7

    @property
    def hour_h(self) -> float:
        return max(20.0, min(200.0, float(self.s("agenda_hour_height", 52)) * self.zoom))

    @property
    def hour_range(self) -> tuple[int, int]:
        if self.s("agenda_limit_hours", False):
            h0 = int(self.s("agenda_day_start", 8))
            h1 = int(self.s("agenda_day_end", 21))
            if h1 <= h0:
                h1 = min(24, h0 + 1)
            return max(0, h0), min(24, h1)
        return 0, 24

    @property
    def snap(self) -> int:
        return max(5, int(self.s("agenda_snap_minutes", 15)))

    @property
    def drag_needs_ctrl(self) -> bool:
        return bool(self.s("agenda_drag_requires_ctrl", False))

    def calendar(self, cal_id: str):
        return self.service.calendar(cal_id) if self.service is not None else None

    def color_key(self, occ: Occurrence) -> str:
        if occ.color:
            return occ.color
        cal = self.calendar(occ.calendar_id)
        return cal.color if cal is not None else "bleu"

    def colors(self, occ: Occurrence):
        return self.t.event(self.color_key(occ))

    def calendar_name(self, cal_id: str) -> str:
        cal = self.calendar(cal_id)
        return cal.name if cal is not None else ""
