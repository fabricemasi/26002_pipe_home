"""Récurrences RFC 5545 (RRULE) : lecture / écriture d'une règle, description en français, déroulement des
occurrences dans une fenêtre, fin d'une série, découpe « cette occurrence et les suivantes ».

Le déroulement se fait en HEURE MURALE du fuseau de l'événement (dateutil.rrule sur des datetimes naïfs), puis
chaque occurrence est située dans ce fuseau : un rendez-vous hebdomadaire de 10:00 reste à 10:00 après un
changement d'heure. Les occurrences supprimées (EXDATE) et remplacées (exceptions, RECURRENCE-ID) sont désignées
par leur identifiant d'occurrence (`timeutil.rid_for_datetime` / `rid_for_date`) : début d'ORIGINE en UTC."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta
from functools import lru_cache

from . import timeutil as tu

FREQS = ("DAILY", "WEEKLY", "MONTHLY", "YEARLY")
MAX_EXPAND = 5000                       # garde-fou par fenêtre (une règle « toutes les minutes » importée…)
ORDINALS = {1: "premier", 2: "deuxième", 3: "troisième", 4: "quatrième", 5: "cinquième", -1: "dernier",
            -2: "avant-dernier"}


@dataclass
class Rule:
    freq: str = "WEEKLY"
    interval: int = 1
    byday: list[str] = field(default_factory=list)       # « MO », « 1MO », « -1FR »
    bymonthday: list[int] = field(default_factory=list)
    bymonth: list[int] = field(default_factory=list)
    bysetpos: list[int] = field(default_factory=list)
    count: int | None = None
    until: str | None = None                             # « 20261231 » ou « 20261231T225959Z »
    wkst: str | None = None
    extra: dict = field(default_factory=dict)            # parties non gérées, recopiées telles quelles

    @property
    def infinite(self) -> bool:
        return self.count is None and self.until is None


def parse_rrule(text: str) -> Rule:
    text = (text or "").strip()
    if text.upper().startswith("RRULE:"):
        text = text[6:]
    rule = Rule()
    for part in text.split(";"):
        if "=" not in part:
            continue
        key, value = part.split("=", 1)
        key = key.strip().upper()
        value = value.strip()
        if key == "FREQ":
            rule.freq = value.upper()
        elif key == "INTERVAL":
            rule.interval = max(1, int(value))
        elif key == "BYDAY":
            rule.byday = [v.strip().upper() for v in value.split(",") if v.strip()]
        elif key == "BYMONTHDAY":
            rule.bymonthday = [int(v) for v in value.split(",") if v.strip()]
        elif key == "BYMONTH":
            rule.bymonth = [int(v) for v in value.split(",") if v.strip()]
        elif key == "BYSETPOS":
            rule.bysetpos = [int(v) for v in value.split(",") if v.strip()]
        elif key == "COUNT":
            rule.count = max(1, int(value))
        elif key == "UNTIL":
            rule.until = value.upper()
        elif key == "WKST":
            rule.wkst = value.upper()
        else:
            rule.extra[key] = value
    if rule.freq not in FREQS and rule.freq not in ("HOURLY", "MINUTELY", "SECONDLY"):
        raise ValueError(f"FREQ inconnue : {rule.freq}")
    return rule


def format_rrule(rule: Rule) -> str:
    parts = [f"FREQ={rule.freq}"]
    if rule.interval > 1:
        parts.append(f"INTERVAL={rule.interval}")
    if rule.byday:
        parts.append("BYDAY=" + ",".join(rule.byday))
    if rule.bymonthday:
        parts.append("BYMONTHDAY=" + ",".join(str(v) for v in rule.bymonthday))
    if rule.bymonth:
        parts.append("BYMONTH=" + ",".join(str(v) for v in rule.bymonth))
    if rule.bysetpos:
        parts.append("BYSETPOS=" + ",".join(str(v) for v in rule.bysetpos))
    if rule.count:
        parts.append(f"COUNT={rule.count}")
    elif rule.until:
        parts.append(f"UNTIL={rule.until}")
    if rule.wkst:
        parts.append(f"WKST={rule.wkst}")
    for key, value in rule.extra.items():
        parts.append(f"{key}={value}")
    return ";".join(parts)


def _split_byday(token: str) -> tuple[int | None, str]:
    code = token[-2:]
    n = token[:-2]
    return (int(n) if n not in ("", "+") else None), code


# -- description ---------------------------------------------------------------------------------------------------

def _day_list(codes: list[str]) -> str:
    names = [tu.DAYS_LONG[tu.RRULE_DAYS.index(c)] for c in codes if c in tu.RRULE_DAYS]
    if not names:
        return ""
    if len(names) == 1:
        return "le " + names[0]
    return "le " + ", le ".join(names[:-1]) + " et le " + names[-1]


def until_date(rule: Rule, tz) -> date | None:
    if not rule.until:
        return None
    if "T" in rule.until:
        dt = datetime.strptime(rule.until.rstrip("Z"), "%Y%m%dT%H%M%S")
        if rule.until.endswith("Z"):
            return dt.replace(tzinfo=tu.UTC).astimezone(tz).date()
        return dt.date()
    return tu.parse_date(rule.until)


def describe(rule: Rule | str, start: date | datetime | None = None, tz=None) -> str:
    """« Toutes les semaines le lundi et le jeudi, jusqu'au 6 décembre 2026 »."""
    if isinstance(rule, str):
        try:
            rule = parse_rrule(rule)
        except ValueError:
            return "Règle personnalisée"
    tz = tz or tu.get_tz(None)
    k = rule.interval
    days = [t for t in rule.byday]
    plain_days = [d for d in days if len(d) == 2]
    if rule.freq == "DAILY":
        text = "Tous les jours" if k == 1 else f"Tous les {k} jours"
    elif rule.freq == "WEEKLY":
        if sorted(plain_days) == sorted(["MO", "TU", "WE", "TH", "FR"]) and k == 1:
            text = "Tous les jours ouvrés"
        else:
            text = "Toutes les semaines" if k == 1 else f"Toutes les {k} semaines"
            if plain_days:
                text += " " + _day_list(plain_days)
            elif start is not None:
                text += " le " + tu.DAYS_LONG[start.weekday()]
    elif rule.freq == "MONTHLY":
        text = "Tous les mois" if k == 1 else f"Tous les {k} mois"
        if rule.bymonthday:
            text += " le " + ", ".join("dernier jour" if d == -1 else str(d) for d in rule.bymonthday)
        elif days:
            n, code = _split_byday(days[0])
            if n is None and rule.bysetpos:
                n = rule.bysetpos[0]
            if n is not None and code in tu.RRULE_DAYS:
                text += f" le {ORDINALS.get(n, f'{n}e')} {tu.DAYS_LONG[tu.RRULE_DAYS.index(code)]}"
        elif start is not None:
            text += f" le {start.day}"
    elif rule.freq == "YEARLY":
        text = "Tous les ans" if k == 1 else f"Tous les {k} ans"
        if start is not None:
            text += f" le {start.day} {tu.MONTHS[start.month - 1]}"
    else:
        text = "Règle personnalisée"
    if rule.count:
        text += f", {rule.count} fois"
    elif rule.until:
        end = until_date(rule, tz)
        if end:
            text += f", jusqu'au {tu.fmt_date(end)}"
    return text


# -- déroulement ---------------------------------------------------------------------------------------------------

def _wall(dt: datetime | date, tz) -> datetime:
    if isinstance(dt, datetime):
        if dt.tzinfo is not None:
            dt = dt.astimezone(tz)
        return dt.replace(tzinfo=None)
    return datetime.combine(dt, time())


def _until_wall(rule: Rule, tz, all_day: bool) -> datetime | None:
    if not rule.until:
        return None
    if "T" in rule.until:
        dt = datetime.strptime(rule.until.rstrip("Z"), "%Y%m%dT%H%M%S")
        if rule.until.endswith("Z"):
            dt = dt.replace(tzinfo=tu.UTC).astimezone(tz).replace(tzinfo=None)
        return dt
    d = tu.parse_date(rule.until)
    return datetime.combine(d, time()) if all_day else datetime.combine(d, time(23, 59, 59))


@lru_cache(maxsize=512)
def _build(rule_text: str, dtstart_wall: datetime, tzkey: str, all_day: bool):
    from dateutil import rrule as du
    rule = parse_rrule(rule_text)
    tz = tu.get_tz(tzkey)
    freq = {"DAILY": du.DAILY, "WEEKLY": du.WEEKLY, "MONTHLY": du.MONTHLY, "YEARLY": du.YEARLY,
            "HOURLY": du.HOURLY, "MINUTELY": du.MINUTELY, "SECONDLY": du.SECONDLY}[rule.freq]
    weekdays = (du.MO, du.TU, du.WE, du.TH, du.FR, du.SA, du.SU)
    kwargs = {"dtstart": dtstart_wall, "interval": rule.interval, "cache": False}
    if rule.byday:
        days = []
        for token in rule.byday:
            n, code = _split_byday(token)
            wd = weekdays[tu.RRULE_DAYS.index(code)]
            days.append(wd(n) if n else wd)
        kwargs["byweekday"] = days
    if rule.bymonthday:
        kwargs["bymonthday"] = rule.bymonthday
    if rule.bymonth:
        kwargs["bymonth"] = rule.bymonth
    if rule.bysetpos:
        kwargs["bysetpos"] = rule.bysetpos
    if rule.wkst in tu.RRULE_DAYS:
        kwargs["wkst"] = weekdays[tu.RRULE_DAYS.index(rule.wkst)]
    if rule.count:
        kwargs["count"] = rule.count
    else:
        until = _until_wall(rule, tz, all_day)
        if until is not None:
            kwargs["until"] = until
    return du.rrule(freq, **kwargs), rule


def _skip_ahead(rule: Rule, dtstart: datetime, window_start: datetime) -> datetime:
    """Départ rapproché de la fenêtre pour les règles sans COUNT (jours / semaines) : dérouler cinq ans d'un
    rendez-vous quotidien à chaque affichage coûtait des milliers d'itérations. Les périodes entières sautées
    gardent l'alignement (même jour de la semaine, même heure murale)."""
    if rule.count or window_start <= dtstart:
        return dtstart
    if rule.freq == "DAILY" and not rule.bymonth and not rule.bymonthday and not rule.bysetpos:
        step = rule.interval
    elif rule.freq == "WEEKLY" and not rule.bysetpos and not rule.bymonth:
        step = 7 * rule.interval
    else:
        return dtstart
    days = (window_start - dtstart).days - 7 * rule.interval - 1
    if days <= step:
        return dtstart
    return dtstart + timedelta(days=(days // step) * step)


def occurrence_starts(rule_text: str, dtstart: datetime | date, tzid: str, all_day: bool,
                      window_start: datetime | date, window_end: datetime | date,
                      duration: timedelta = timedelta(0)) -> list:
    """Débuts des occurrences qui CHEVAUCHENT [window_start, window_end[ : datetimes aware (fuseau de
    l'événement) ou dates (journée). La première occurrence est toujours `dtstart` (RFC 5545)."""
    tz = tu.get_tz(tzid)
    start_wall = _wall(dtstart, tz)
    rr, rule = _build(rule_text, start_wall, tzid or "", all_day)
    win_lo = _wall(window_start, tz)
    hi = _wall(window_end, tz)
    lo = win_lo - duration                           # une occurrence commencée avant peut encore chevaucher

    def overlaps(wall):
        return wall < hi and (wall + duration > win_lo if duration > timedelta(0) else wall >= win_lo)

    if not rule.count:
        anchor = _skip_ahead(rule, start_wall, lo)
        if anchor != start_wall:
            rr = rr.replace(dtstart=anchor)
    out = []
    for wall in rr.xafter(lo, inc=True):
        if wall >= hi:
            break
        if overlaps(wall):
            out.append(wall)
            if len(out) >= MAX_EXPAND:
                break
    # dateutil ignore un DTSTART qui ne suit pas la règle (lundi pour BYDAY=TU) : RFC 5545 le compte quand même.
    if not rule.count and overlaps(start_wall) and start_wall not in out:
        out.insert(0, start_wall)
    return [w.date() for w in out] if all_day else [tu.localize(w, tz) for w in out]


def last_end_ts(rule_text: str, dtstart: datetime | date, tzid: str, all_day: bool,
                duration: timedelta) -> int | None:
    """Fin (epoch UTC ; minuit UTC pour une journée) de la DERNIÈRE occurrence, None si la série est infinie."""
    rule = parse_rrule(rule_text)
    if rule.infinite:
        return None
    tz = tu.get_tz(tzid)
    rr, _rule = _build(rule_text, _wall(dtstart, tz), tzid or "", all_day)
    last = None
    for i, wall in enumerate(rr):
        last = wall
        if i > 100000:
            return None
    if last is None:
        last = _wall(dtstart, tz)
    if all_day:
        return tu.date_to_ord_ts(last.date() + duration)
    return tu.to_ts(tu.localize(last, tz) + duration)


def count_before(rule_text: str, dtstart: datetime | date, tzid: str, all_day: bool,
                 occurrence: datetime | date) -> int:
    """Nombre d'occurrences STRICTEMENT avant `occurrence` (découpe d'une série à COUNT)."""
    tz = tu.get_tz(tzid)
    rr, _rule = _build(rule_text, _wall(dtstart, tz), tzid or "", all_day)
    limit = _wall(occurrence, tz)
    n = 0
    for wall in rr:
        if wall >= limit:
            break
        n += 1
    return n


def until_before(occurrence: datetime | date, all_day: bool) -> str:
    """UNTIL qui arrête une série juste avant `occurrence` (« cette occurrence et les suivantes »)."""
    if all_day:
        return tu.rid_for_date(occurrence - timedelta(days=1))
    return (occurrence.astimezone(tu.UTC) - timedelta(seconds=1)).strftime("%Y%m%dT%H%M%SZ")


def rid_of(start: datetime | date, all_day: bool) -> str:
    return tu.rid_for_date(start) if all_day else tu.rid_for_datetime(start)


def shift_rid(rid: str, delta: timedelta, all_day: bool) -> str:
    """Identifiant d'occurrence décalé avec la série (la série entière change d'heure / de jour)."""
    if all_day or "T" not in rid:
        return tu.rid_for_date(tu.parse_date(rid) + timedelta(days=delta.days))
    dt = datetime.strptime(rid.rstrip("Z"), "%Y%m%dT%H%M%S").replace(tzinfo=tu.UTC)
    return tu.rid_for_datetime(dt + delta)


# -- règles proposées dans l'éditeur -------------------------------------------------------------------------------

def presets(start: date) -> list[tuple[str, str | None]]:
    """(libellé, règle) des choix rapides de l'éditeur pour un début `start`."""
    code = tu.RRULE_DAYS[start.weekday()]
    nth = (start.day - 1) // 7 + 1
    last = (start + timedelta(days=7)).month != start.month
    out = [("Ne se répète pas", None),
           ("Tous les jours", "FREQ=DAILY"),
           ("Tous les jours ouvrés (lundi au vendredi)", "FREQ=WEEKLY;BYDAY=MO,TU,WE,TH,FR"),
           (f"Toutes les semaines le {tu.DAYS_LONG[start.weekday()]}", f"FREQ=WEEKLY;BYDAY={code}"),
           (f"Toutes les deux semaines le {tu.DAYS_LONG[start.weekday()]}", f"FREQ=WEEKLY;INTERVAL=2;BYDAY={code}"),
           (f"Tous les mois le {start.day}", f"FREQ=MONTHLY;BYMONTHDAY={start.day}"),
           (f"Tous les mois le {ORDINALS.get(nth, str(nth))} {tu.DAYS_LONG[start.weekday()]}",
            f"FREQ=MONTHLY;BYDAY={nth}{code}")]
    if last:
        out.append((f"Tous les mois le dernier {tu.DAYS_LONG[start.weekday()]}", f"FREQ=MONTHLY;BYDAY=-1{code}"))
    out.append((f"Tous les ans le {start.day} {tu.MONTHS[start.month - 1]}", "FREQ=YEARLY"))
    return out
