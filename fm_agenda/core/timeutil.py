"""Dates, heures et fuseaux de l'agenda (sans Qt).

Règles :
- un événement horaire porte des instants ABSOLUS (UTC, secondes epoch `start_ts` / `end_ts`) ET son fuseau IANA
  (`tzid`) : les récurrences se déroulent dans ce fuseau (10:00 Europe/Paris reste 10:00 après le passage à
  l'heure d'été) ;
- un événement « journée » porte des DATES flottantes (`start_date` inclus, `end_date` exclu), identiques quel que
  soit le fuseau ;
- l'affichage se fait dans le fuseau d'affichage (réglage `agenda_timezone`, vide = celui de Windows).

Sans la base tzdata (paquet `tzdata` absent sous Windows), un fuseau « système » calculé par l'horloge de Windows
(`_SystemLocal`) remplace le fuseau demandé : correct pour le fuseau local, changements d'heure compris."""
from __future__ import annotations

import calendar as _calendar
import time as _time
from datetime import date, datetime, timedelta, timezone, tzinfo
from functools import lru_cache

UTC = timezone.utc

MONTHS = ("janvier", "février", "mars", "avril", "mai", "juin", "juillet", "août", "septembre", "octobre",
          "novembre", "décembre")
MONTHS_SHORT = ("janv.", "févr.", "mars", "avr.", "mai", "juin", "juil.", "août", "sept.", "oct.", "nov.", "déc.")
# Index Python : lundi = 0 … dimanche = 6.
DAYS_LONG = ("lundi", "mardi", "mercredi", "jeudi", "vendredi", "samedi", "dimanche")
DAYS_SHORT = ("LUN", "MAR", "MER", "JEU", "VEN", "SAM", "DIM")
DAYS_LETTER = ("L", "M", "M", "J", "V", "S", "D")
RRULE_DAYS = ("MO", "TU", "WE", "TH", "FR", "SA", "SU")


def cap(text: str) -> str:
    return text[:1].upper() + text[1:]


# -- fuseaux -------------------------------------------------------------------------------------------------------

class _SystemLocal(tzinfo):
    """Fuseau de Windows calculé par `time.localtime` (repli sans tzdata) : changements d'heure du système suivis."""

    def utcoffset(self, dt):
        return timedelta(seconds=self._local(dt).tm_gmtoff)

    def dst(self, dt):
        lt = self._local(dt)
        return timedelta(hours=1) if lt.tm_isdst > 0 else timedelta(0)

    def tzname(self, dt):
        return self._local(dt).tm_zone

    @staticmethod
    def _local(dt):
        stamp = _calendar.timegm(dt.replace(tzinfo=None).timetuple())
        # Heure murale -> instant : deux essais suffisent (décalage avant / après).
        guess = _time.localtime(stamp)
        guess = _time.localtime(stamp - guess.tm_gmtoff)
        return guess

    def fromutc(self, dt):
        stamp = _calendar.timegm(dt.replace(tzinfo=None).timetuple())
        lt = _time.localtime(stamp)
        return (dt + timedelta(seconds=lt.tm_gmtoff)).replace(tzinfo=self)

    def __repr__(self):
        return "SystemLocal()"


SYSTEM_LOCAL = _SystemLocal()

# Noms Windows (registre TimeZoneKeyName) -> IANA : les fuseaux courants (table CLDR windowsZones, territoire 001).
_WINDOWS_TO_IANA = {
    "Romance Standard Time": "Europe/Paris", "W. Europe Standard Time": "Europe/Berlin",
    "Central Europe Standard Time": "Europe/Budapest", "Central European Standard Time": "Europe/Warsaw",
    "GMT Standard Time": "Europe/London", "Greenwich Standard Time": "Atlantic/Reykjavik",
    "E. Europe Standard Time": "Europe/Chisinau", "FLE Standard Time": "Europe/Kiev", "GTB Standard Time":
    "Europe/Bucharest", "Russian Standard Time": "Europe/Moscow", "Turkey Standard Time": "Europe/Istanbul",
    "Morocco Standard Time": "Africa/Casablanca", "W. Central Africa Standard Time": "Africa/Lagos",
    "South Africa Standard Time": "Africa/Johannesburg", "Egypt Standard Time": "Africa/Cairo",
    "Arabian Standard Time": "Asia/Dubai", "India Standard Time": "Asia/Calcutta", "China Standard Time":
    "Asia/Shanghai", "Tokyo Standard Time": "Asia/Tokyo", "Singapore Standard Time": "Asia/Singapore",
    "AUS Eastern Standard Time": "Australia/Sydney", "New Zealand Standard Time": "Pacific/Auckland",
    "Eastern Standard Time": "America/New_York", "Central Standard Time": "America/Chicago",
    "Mountain Standard Time": "America/Denver", "Pacific Standard Time": "America/Los_Angeles",
    "Atlantic Standard Time": "America/Halifax", "E. South America Standard Time": "America/Sao_Paulo",
    "Canada Central Standard Time": "America/Regina", "Hawaiian Standard Time": "Pacific/Honolulu",
    "Reunion Standard Time": "Indian/Reunion", "Mauritius Standard Time": "Indian/Mauritius",
    "SA Western Standard Time": "America/La_Paz", "UTC": "UTC", "Coordinated Universal Time": "UTC",
}
# Fuseaux proposés dans les réglages (le champ accepte aussi tout nom IANA).
COMMON_ZONES = ("Europe/Paris", "Europe/London", "Europe/Berlin", "Europe/Madrid", "Europe/Rome", "Europe/Brussels",
                "Europe/Zurich", "Europe/Lisbon", "Atlantic/Reykjavik", "America/New_York", "America/Chicago",
                "America/Los_Angeles", "America/Montreal", "America/Sao_Paulo", "Asia/Tokyo", "Asia/Shanghai",
                "Asia/Dubai", "Asia/Singapore", "Australia/Sydney", "Indian/Reunion", "America/Martinique",
                "Pacific/Tahiti", "UTC")


@lru_cache(maxsize=1)
def system_tz_name() -> str:
    """Nom IANA du fuseau de Windows (registre), « Europe/Paris » si inconnu."""
    try:
        import winreg
        with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE,
                            r"SYSTEM\CurrentControlSet\Control\TimeZoneInformation") as key:
            name = winreg.QueryValueEx(key, "TimeZoneKeyName")[0]
        return _WINDOWS_TO_IANA.get(str(name).strip("\x00 "), "Europe/Paris")
    except (OSError, ImportError):
        return "Europe/Paris"


@lru_cache(maxsize=64)
def get_tz(name: str | None) -> tzinfo:
    """Fuseau IANA (`ZoneInfo`) ; vide = celui de Windows ; inconnu / sans tzdata = horloge du système."""
    if not name:
        name = system_tz_name()
    if name.upper() == "UTC":
        return UTC
    try:
        from zoneinfo import ZoneInfo
        return ZoneInfo(name)
    except Exception:                               # noqa: BLE001 - tzdata absente ou nom invalide
        return SYSTEM_LOCAL


def tz_name(tz: tzinfo) -> str:
    key = getattr(tz, "key", None)
    if key:
        return key
    if tz is UTC:
        return "UTC"
    return system_tz_name()


def valid_tz(name: str) -> bool:
    try:
        from zoneinfo import ZoneInfo
        ZoneInfo(name)
        return True
    except Exception:                               # noqa: BLE001
        return name.upper() == "UTC"


# -- conversions ---------------------------------------------------------------------------------------------------

def to_ts(dt: datetime) -> int:
    """Instant (aware) -> secondes epoch UTC."""
    if dt.tzinfo is None:
        raise ValueError("datetime naïf : fuseau requis")
    return int(dt.timestamp())


def from_ts(ts: int, tz: tzinfo) -> datetime:
    return datetime.fromtimestamp(int(ts), UTC).astimezone(tz)


def localize(naive: datetime, tz: tzinfo) -> datetime:
    """Heure murale -> instant dans `tz`. Une heure inexistante (saut d'été, 2:30 le dernier dimanche de mars) est
    décalée après le saut ; une heure ambiguë (retour à l'heure d'hiver) prend la première occurrence."""
    aware = naive.replace(tzinfo=tz, fold=0)
    back = aware.astimezone(UTC).astimezone(tz)
    if back.replace(tzinfo=None) != naive:          # heure inexistante : l'instant normalisé (après le saut)
        return back
    return aware


def day_start(d: date, tz: tzinfo) -> datetime:
    return localize(datetime(d.year, d.month, d.day), tz)


def day_start_ts(d: date, tz: tzinfo) -> int:
    return to_ts(day_start(d, tz))


def date_to_ord_ts(d: date) -> int:
    """Date flottante -> 00:00 UTC de ce jour (clé de tri / de requête des événements « journée »)."""
    return _calendar.timegm((d.year, d.month, d.day, 0, 0, 0))


def ord_ts_to_date(ts: int) -> date:
    return datetime.fromtimestamp(int(ts), UTC).date()


def parse_date(text: str) -> date:
    text = text.strip()
    if len(text) == 8 and text.isdigit():
        return date(int(text[:4]), int(text[4:6]), int(text[6:8]))
    return date.fromisoformat(text[:10])


# Identifiants d'occurrence (RECURRENCE-ID) : forme iCalendar, comparables et stables.
def rid_for_datetime(dt: datetime) -> str:
    return dt.astimezone(UTC).strftime("%Y%m%dT%H%M%SZ")


def rid_for_date(d: date) -> str:
    return d.strftime("%Y%m%d")


def parse_rid(rid: str, tz: tzinfo) -> datetime | date:
    if "T" in rid:
        dt = datetime.strptime(rid.rstrip("Z"), "%Y%m%dT%H%M%S")
        return dt.replace(tzinfo=UTC).astimezone(tz) if rid.endswith("Z") else localize(dt, tz)
    return parse_date(rid)


# -- calendrier ----------------------------------------------------------------------------------------------------

def iso_week(d: date) -> int:
    return d.isocalendar()[1]


def week_start(d: date, first_weekday: int = 0) -> date:
    """Premier jour de la semaine contenant `d` (`first_weekday` : 0 = lundi … 6 = dimanche)."""
    return d - timedelta(days=(d.weekday() - first_weekday) % 7)


def month_first(d: date) -> date:
    return d.replace(day=1)


def add_months(d: date, months: int) -> date:
    y, m = divmod(d.month - 1 + months, 12)
    year, month = d.year + y, m + 1
    return date(year, month, min(d.day, _calendar.monthrange(year, month)[1]))


def month_grid(first: date, first_weekday: int = 0) -> list[list[date]]:
    """6 semaines × 7 jours couvrant le mois de `first` (comme la maquette)."""
    start = week_start(first.replace(day=1), first_weekday)
    return [[start + timedelta(days=r * 7 + c) for c in range(7)] for r in range(6)]


def days_between(a: date, b: date) -> int:
    return (b - a).days


def weekday_order(first_weekday: int) -> list[int]:
    return [(first_weekday + i) % 7 for i in range(7)]


# -- textes --------------------------------------------------------------------------------------------------------

def fmt_time(dt: datetime, h24: bool = True) -> str:
    """« 9:30 », « 14:00 » (sans zéro de tête, comme la maquette) ; 12 h : « 9:30 AM »."""
    if h24:
        return f"{dt.hour}:{dt.minute:02d}"
    hour = dt.hour % 12 or 12
    return f"{hour}:{dt.minute:02d} {'AM' if dt.hour < 12 else 'PM'}"


def fmt_hour(hour: int, h24: bool = True) -> str:
    if h24:
        return f"{hour}:00"
    return f"{hour % 12 or 12} {'AM' if hour < 12 or hour == 24 else 'PM'}"


def fmt_range(start: datetime, end: datetime, h24: bool = True) -> str:
    return f"{fmt_time(start, h24)} – {fmt_time(end, h24)}"


def fmt_day_long(d: date) -> str:
    """« Vendredi 6 novembre 2026 »."""
    return f"{cap(DAYS_LONG[d.weekday()])} {d.day} {MONTHS[d.month - 1]} {d.year}"


def fmt_day_short(d: date) -> str:
    """« Vendredi 6 nov. »."""
    return f"{cap(DAYS_LONG[d.weekday()])} {d.day} {MONTHS_SHORT[d.month - 1]}"


def fmt_date(d: date) -> str:
    """« 6 novembre 2026 »."""
    return f"{d.day} {MONTHS[d.month - 1]} {d.year}"


def fmt_numeric(d: date) -> str:
    return f"{d.day:02d}/{d.month:02d}/{d.year}"


def parse_user_date(text: str, today: date | None = None) -> date | None:
    """Saisie libre d'une date : « 6/11/2026 », « 06.11.26 », « 2026-11-06 », « 6 nov 2026 », « 6/11 »,
    « aujourd'hui », « demain ». None si illisible."""
    import re
    today = today or date.today()
    t = text.strip().lower()
    if not t:
        return None
    if t in ("aujourd'hui", "aujourd’hui", "auj", "today"):
        return today
    if t in ("demain", "tomorrow"):
        return today + timedelta(days=1)
    if t in ("hier", "yesterday"):
        return today - timedelta(days=1)
    try:
        if re.fullmatch(r"\d{4}-\d{1,2}-\d{1,2}", t):
            y, m, d = (int(x) for x in t.split("-"))
            return date(y, m, d)
        m = re.fullmatch(r"(\d{1,2})[/.\-](\d{1,2})(?:[/.\-](\d{2,4}))?", t)
        if m:
            d, mo = int(m.group(1)), int(m.group(2))
            y = int(m.group(3)) if m.group(3) else today.year
            if y < 100:
                y += 2000
            return date(y, mo, d)
        m = re.fullmatch(r"(\d{1,2})\s+([a-zéèûô\.]+)(?:\s+(\d{4}))?", t)
        if m:
            word = m.group(2).rstrip(".")
            for i, name in enumerate(MONTHS):
                if name.startswith(word[:3]) or MONTHS_SHORT[i].rstrip(".") == word:
                    y = int(m.group(3)) if m.group(3) else today.year
                    return date(y, i + 1, int(m.group(1)))
    except ValueError:
        return None
    return None


def parse_user_time(text: str) -> tuple[int, int] | None:
    """« 9 », « 9h », « 9h30 », « 09:30 », « 930 », « 2:30 pm » -> (heure, minute) ; None si illisible."""
    import re
    t = text.strip().lower().replace(" ", "")
    if not t:
        return None
    pm = t.endswith("pm")
    am = t.endswith("am")
    if pm or am:
        t = t[:-2]
    m = re.fullmatch(r"(\d{1,2})(?:[h:.](\d{0,2}))?", t) or re.fullmatch(r"(\d{1,2})(\d{2})", t)
    if not m:
        return None
    hour = int(m.group(1))
    minute = int(m.group(2)) if m.group(2) else 0
    if pm and hour < 12:
        hour += 12
    if am and hour == 12:
        hour = 0
    if hour == 24 and minute == 0:
        return 24, 0
    if not (0 <= hour < 24 and 0 <= minute < 60):
        return None
    return hour, minute


def fmt_duration(minutes: int) -> str:
    if minutes <= 0:
        return "à l'heure de l'événement"
    if minutes % 10080 == 0:
        w = minutes // 10080
        return f"{w} semaine{'s' if w > 1 else ''} avant"
    if minutes % 1440 == 0:
        d = minutes // 1440
        return f"{d} jour{'s' if d > 1 else ''} avant"
    if minutes % 60 == 0:
        h = minutes // 60
        return f"{h} heure{'s' if h > 1 else ''} avant"
    if minutes > 60:
        return f"{minutes // 60} h {minutes % 60:02d} avant"
    return f"{minutes} minute{'s' if minutes > 1 else ''} avant"


def now_utc() -> datetime:
    return datetime.now(UTC)
