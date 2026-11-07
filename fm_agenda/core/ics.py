"""iCalendar (RFC 5545) sans dépendance : lecture d'un fichier .ics en événements, écriture d'événements en .ics.

Lecture : lignes repliées, paramètres, échappements, VEVENT (UID, SUMMARY, DESCRIPTION, LOCATION, URL, DTSTART /
DTEND / DURATION en date, UTC, TZID IANA ou Windows, heure flottante), RRULE, EXDATE, RECURRENCE-ID (exceptions),
STATUS, TRANSP, CATEGORIES, ATTENDEE, VALARM (TRIGGER relatif au début), extensions X-PIPE-* (projet, dossier,
notes, tâche). VTIMEZONE ignoré : les TZID sont lus comme noms IANA (ou Windows, table de `timeutil`).

Écriture : VCALENDAR 2.0, un VEVENT par événement / exception, TZID IANA (sans VTIMEZONE : Google, Apple et
Outlook récents l'acceptent), lignes repliées à 75 octets, fins de ligne CRLF."""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone

from . import timeutil as tu
from .model import Attendee, EventRecord

PRODID = "-//PIPE FMZ//fm_agenda//FR"


@dataclass
class Prop:
    name: str
    params: dict
    value: str


@dataclass
class Component:
    name: str
    props: list[Prop] = field(default_factory=list)
    children: list["Component"] = field(default_factory=list)

    def get(self, name: str) -> Prop | None:
        return next((p for p in self.props if p.name == name), None)

    def all(self, name: str) -> list[Prop]:
        return [p for p in self.props if p.name == name]


def unfold(text: str) -> list[str]:
    lines: list[str] = []
    for raw in text.replace("\r\n", "\n").replace("\r", "\n").split("\n"):
        if raw[:1] in (" ", "\t") and lines:
            lines[-1] += raw[1:]
        elif raw:
            lines.append(raw)
    return lines


_PARAM_RE = re.compile(r'([A-Za-z0-9-]+)=("([^"]*)"|[^;:]*)')


def parse_line(line: str) -> Prop:
    # nom[;param=valeur…]:valeur — un « : » dans une valeur de paramètre entre guillemets ne coupe pas
    i, quoted = 0, False
    while i < len(line):
        c = line[i]
        if c == '"':
            quoted = not quoted
        elif c == ":" and not quoted:
            break
        i += 1
    head, value = line[:i], line[i + 1:]
    parts = head.split(";", 1)
    name = parts[0].upper()
    params = {}
    if len(parts) > 1:
        for m in _PARAM_RE.finditer(parts[1]):
            params[m.group(1).upper()] = m.group(3) if m.group(3) is not None else m.group(2)
    return Prop(name, params, value)


def parse(text: str) -> Component:
    root = Component("ROOT")
    stack = [root]
    for line in unfold(text):
        prop = parse_line(line)
        if prop.name == "BEGIN":
            comp = Component(prop.value.upper())
            stack[-1].children.append(comp)
            stack.append(comp)
        elif prop.name == "END":
            if len(stack) > 1:
                stack.pop()
        else:
            stack[-1].props.append(prop)
    return root


def unescape(value: str) -> str:
    out, i = [], 0
    while i < len(value):
        c = value[i]
        if c == "\\" and i + 1 < len(value):
            n = value[i + 1]
            out.append("\n" if n in "nN" else n)
            i += 2
            continue
        out.append(c)
        i += 1
    return "".join(out)


def escape(value: str) -> str:
    return (value or "").replace("\\", "\\\\").replace(";", "\\;").replace(",", "\\,").replace("\n", "\\n")


def _split_list(value: str) -> list[str]:
    out, cur, i = [], [], 0
    while i < len(value):
        c = value[i]
        if c == "\\" and i + 1 < len(value):
            cur.append(value[i:i + 2])
            i += 2
            continue
        if c == ",":
            out.append("".join(cur))
            cur = []
        else:
            cur.append(c)
        i += 1
    out.append("".join(cur))
    return [unescape(x).strip() for x in out if x.strip()]


def _tz_of(prop: Prop, default_tz):
    tzid = prop.params.get("TZID")
    if not tzid:
        return None if not prop.value.endswith("Z") else tu.UTC
    tzid = tzid.strip('"')
    if tu.valid_tz(tzid):
        return tu.get_tz(tzid)
    iana = tu._WINDOWS_TO_IANA.get(tzid)
    return tu.get_tz(iana) if iana else default_tz


def parse_dt(prop: Prop, default_tz):
    """Date (VALUE=DATE) ou instant aware ; une heure flottante prend le fuseau par défaut."""
    value = prop.value.strip()
    if prop.params.get("VALUE", "").upper() == "DATE" or (len(value) == 8 and value.isdigit()):
        return tu.parse_date(value[:8])
    dt = datetime.strptime(value.rstrip("Z")[:15], "%Y%m%dT%H%M%S")
    if value.endswith("Z"):
        return dt.replace(tzinfo=timezone.utc)
    tz = _tz_of(prop, default_tz) or default_tz
    return tu.localize(dt, tz)


_DUR_RE = re.compile(r"([+-])?P(?:(\d+)W)?(?:(\d+)D)?(?:T(?:(\d+)H)?(?:(\d+)M)?(?:(\d+)S)?)?")


def parse_duration(value: str) -> timedelta | None:
    m = _DUR_RE.fullmatch(value.strip())
    if not m:
        return None
    sign = -1 if m.group(1) == "-" else 1
    w, d, h, mi, s = (int(x) if x else 0 for x in m.groups()[1:])
    return sign * timedelta(weeks=w, days=d, hours=h, minutes=mi, seconds=s)


def format_duration(td: timedelta) -> str:
    total = int(td.total_seconds())
    sign = "-" if total < 0 else ""
    total = abs(total)
    days, rest = divmod(total, 86400)
    hours, rest = divmod(rest, 3600)
    minutes, seconds = divmod(rest, 60)
    out = f"{sign}P"
    if days:
        out += f"{days}D"
    if hours or minutes or seconds or not days:
        out += "T"
        if hours:
            out += f"{hours}H"
        if minutes or (not hours and not seconds):
            out += f"{minutes}M"
        if seconds:
            out += f"{seconds}S"
    return out


@dataclass
class ParsedEvent:
    uid: str
    record: EventRecord
    recurrence_id: str | None = None      # forme de l'agenda (UTC « …Z » ou date)
    sequence: int = 0


def read_events(text: str, calendar_id: str, default_tz_name: str) -> tuple[list[ParsedEvent], list[str]]:
    """Événements d'un texte .ics (enregistrements sans identifiant local) et avertissements."""
    root = parse(text)
    default_tz = tu.get_tz(default_tz_name)
    out, warnings = [], []
    cals = [c for c in root.children if c.name == "VCALENDAR"] or [root]
    for cal in cals:
        for comp in cal.children:
            if comp.name != "VEVENT":
                continue
            try:
                out.append(_read_event(comp, calendar_id, default_tz, default_tz_name))
            except Exception as exc:                     # noqa: BLE001 - un VEVENT illisible n'arrête pas l'import
                uid = comp.get("UID")
                warnings.append(f"événement ignoré ({uid.value if uid else '?'}) : {exc}")
    return out, warnings


def _read_event(comp: Component, calendar_id: str, default_tz, default_tz_name: str) -> ParsedEvent:
    from .model import new_id
    ev = EventRecord(id=new_id(), calendar_id=calendar_id)
    uid = unescape(comp.get("UID").value) if comp.get("UID") else f"{ev.id}@import"
    ev.ical_uid = uid
    get = lambda name: unescape(comp.get(name).value) if comp.get(name) else ""   # noqa: E731
    ev.title = get("SUMMARY")
    ev.description = get("DESCRIPTION")
    ev.location = get("LOCATION")
    ev.url = get("URL")
    ev.project = get("X-PIPE-PROJECT")
    ev.folder = get("X-PIPE-FOLDER")
    ev.notes = get("X-PIPE-NOTES")
    ev.is_task = get("X-PIPE-TASK").upper() == "TRUE"
    ev.done = get("X-PIPE-DONE").upper() == "TRUE"
    color = get("X-PIPE-COLOR") or get("COLOR")
    ev.color = color if color else None
    ev.status = {"TENTATIVE": "tentative", "CANCELLED": "cancelled"}.get(get("STATUS").upper(), "confirmed")
    ev.transparency = "transparent" if get("TRANSP").upper() == "TRANSPARENT" else "opaque"
    for p in comp.all("CATEGORIES"):
        ev.categories.extend(_split_list(p.value))
    start_p = comp.get("DTSTART")
    if start_p is None:
        raise ValueError("DTSTART manquant")
    start = parse_dt(start_p, default_tz)
    end = None
    if comp.get("DTEND") is not None:
        end = parse_dt(comp.get("DTEND"), default_tz)
    elif comp.get("DURATION") is not None:
        dur = parse_duration(comp.get("DURATION").value)
        end = start + dur if dur is not None else None
    tzid = start_p.params.get("TZID", "").strip('"')
    if isinstance(start, datetime):
        ev.all_day = False
        ev.tzid = tzid if tzid and tu.valid_tz(tzid) else (tu._WINDOWS_TO_IANA.get(tzid) or default_tz_name)
        tz = tu.get_tz(ev.tzid)
        ev.start = start.astimezone(tz)
        if end is None or not isinstance(end, datetime):
            end = start
        ev.end = end.astimezone(tz) if end >= start else ev.start
        if ev.end == ev.start and not ev.is_task:
            ev.end = ev.start + timedelta(minutes=0)
    else:
        ev.all_day = True
        ev.tzid = default_tz_name
        ev.start_date = start
        ev.end_date = end if isinstance(end, date) and not isinstance(end, datetime) and end > start else \
            start + timedelta(days=1)
    rrule = comp.get("RRULE")
    if rrule is not None:
        from . import recurrence as rec
        rule = rec.parse_rrule(rrule.value)
        if rule.until and not ev.all_day and "T" not in rule.until:
            rule.until = rec.until_before(tu.localize(datetime.combine(tu.parse_date(rule.until) + timedelta(days=1),
                                                                        datetime.min.time()), ev.tz), False)
        elif rule.until and not ev.all_day and not rule.until.endswith("Z"):
            local = datetime.strptime(rule.until, "%Y%m%dT%H%M%S")
            rule.until = tu.rid_for_datetime(tu.localize(local, ev.tz))
        ev.rrule = rec.format_rrule(rule)
    for p in comp.all("EXDATE"):
        for value in p.value.split(","):
            sub = Prop("EXDATE", p.params, value)
            d = parse_dt(sub, ev.tz if not ev.all_day else default_tz)
            ev.exdates.append(tu.rid_for_date(d) if isinstance(d, date) and not isinstance(d, datetime)
                              else tu.rid_for_datetime(d))
    rid = None
    rid_p = comp.get("RECURRENCE-ID")
    if rid_p is not None:
        d = parse_dt(rid_p, ev.tz if not ev.all_day else default_tz)
        rid = tu.rid_for_date(d) if isinstance(d, date) and not isinstance(d, datetime) else tu.rid_for_datetime(d)
    for p in comp.all("ATTENDEE"):
        email = re.sub(r"^mailto:", "", p.value, flags=re.I)
        status = {"ACCEPTED": "accepted", "DECLINED": "declined", "TENTATIVE": "tentative"}.get(
            p.params.get("PARTSTAT", "").upper(), "needsAction")
        ev.attendees.append(Attendee(email=email, name=p.params.get("CN", "").strip('"'), status=status,
                                     optional=p.params.get("ROLE", "").upper() == "OPT-PARTICIPANT"))
    org = comp.get("ORGANIZER")
    if org is not None:
        email = re.sub(r"^mailto:", "", org.value, flags=re.I)
        found = next((a for a in ev.attendees if a.email.lower() == email.lower()), None)
        if found:
            found.organizer = True
    for alarm in comp.children:
        if alarm.name != "VALARM":
            continue
        trig = alarm.get("TRIGGER")
        if trig is None or trig.params.get("VALUE", "").upper() == "DATE-TIME":
            continue
        if trig.params.get("RELATED", "START").upper() != "START":
            continue
        td = parse_duration(trig.value)
        if td is not None and td <= timedelta(0):
            ev.reminders.append(int(-td.total_seconds() // 60))
    seq = comp.get("SEQUENCE")
    try:
        ev.sequence = int(seq.value) if seq else 0
    except ValueError:
        ev.sequence = 0
    return ParsedEvent(uid=uid, record=ev, recurrence_id=rid, sequence=ev.sequence)


# -- écriture --------------------------------------------------------------------------------------------------------

def fold(line: str) -> str:
    data = line.encode("utf-8")
    if len(data) <= 75:
        return line
    out, cur, size = [], "", 0
    for ch in line:
        b = len(ch.encode("utf-8"))
        if size + b > (75 if not out else 74):
            out.append(cur)
            cur, size = "", 0
        cur += ch
        size += b
    out.append(cur)
    return "\r\n ".join(out)


def _fmt_dt(name: str, value, tzid: str) -> str:
    if isinstance(value, date) and not isinstance(value, datetime):
        return f"{name};VALUE=DATE:{value.strftime('%Y%m%d')}"
    if tzid and tzid.upper() != "UTC":
        local = value.astimezone(tu.get_tz(tzid))
        return f"{name};TZID={tzid}:{local.strftime('%Y%m%dT%H%M%S')}"
    return f"{name}:{value.astimezone(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}"


def _rid_value(rid: str, all_day: bool, tzid: str):
    if all_day or "T" not in rid:
        return tu.parse_date(rid)
    return datetime.strptime(rid.rstrip("Z"), "%Y%m%dT%H%M%S").replace(tzinfo=timezone.utc)


def event_lines(ev: EventRecord, uid: str, now: datetime | None = None) -> list[str]:
    now = now or datetime.now(timezone.utc)
    tzid = ev.tzid if not ev.all_day else ""
    lines = ["BEGIN:VEVENT", f"UID:{escape(uid)}", f"DTSTAMP:{now.strftime('%Y%m%dT%H%M%SZ')}"]
    if ev.all_day:
        lines.append(_fmt_dt("DTSTART", ev.start_date, ""))
        lines.append(_fmt_dt("DTEND", ev.end_date, ""))
    else:
        lines.append(_fmt_dt("DTSTART", ev.start, tzid))
        lines.append(_fmt_dt("DTEND", ev.end, tzid))
    if ev.recurrence_id:
        lines.append(_fmt_dt("RECURRENCE-ID", _rid_value(ev.recurrence_id, ev.all_day, tzid), tzid))
    if ev.rrule and not ev.series_id:
        lines.append("RRULE:" + ev.rrule)
        for x in sorted(ev.exdates):
            lines.append(_fmt_dt("EXDATE", _rid_value(x, ev.all_day, tzid), tzid))
    lines.append("SUMMARY:" + escape(ev.title))
    for name, value in (("DESCRIPTION", ev.description), ("LOCATION", ev.location), ("URL", ev.url),
                        ("X-PIPE-PROJECT", ev.project), ("X-PIPE-FOLDER", ev.folder), ("X-PIPE-NOTES", ev.notes)):
        if value:
            lines.append(f"{name}:{escape(value)}")
    if ev.color:
        lines.append("X-PIPE-COLOR:" + escape(ev.color))
    if ev.is_task:
        lines.append("X-PIPE-TASK:TRUE")
        lines.append(f"X-PIPE-DONE:{'TRUE' if ev.done else 'FALSE'}")
    if ev.categories:
        lines.append("CATEGORIES:" + ",".join(escape(c) for c in ev.categories))
    lines.append("STATUS:" + {"tentative": "TENTATIVE", "cancelled": "CANCELLED"}.get(ev.status, "CONFIRMED"))
    lines.append("TRANSP:" + ("TRANSPARENT" if ev.transparency == "transparent" else "OPAQUE"))
    lines.append(f"SEQUENCE:{ev.sequence}")
    for a in ev.attendees:
        params = [f'CN="{a.name}"'] if a.name else []
        params.append("PARTSTAT=" + {"accepted": "ACCEPTED", "declined": "DECLINED",
                                     "tentative": "TENTATIVE"}.get(a.status, "NEEDS-ACTION"))
        if a.optional:
            params.append("ROLE=OPT-PARTICIPANT")
        lines.append(f"ATTENDEE;{';'.join(params)}:mailto:{a.email}")
    for minutes in sorted(set(ev.reminders)):
        lines += ["BEGIN:VALARM", "ACTION:DISPLAY", "DESCRIPTION:" + escape(ev.title or "Rappel"),
                  f"TRIGGER:{format_duration(-timedelta(minutes=minutes))}", "END:VALARM"]
    lines.append("END:VEVENT")
    return lines


def write_calendar(events: list[tuple[EventRecord, str]], name: str = "") -> str:
    lines = ["BEGIN:VCALENDAR", "VERSION:2.0", f"PRODID:{PRODID}", "CALSCALE:GREGORIAN"]
    if name:
        lines.append("X-WR-CALNAME:" + escape(name))
    for ev, uid in events:
        lines += event_lines(ev, uid)
    lines.append("END:VCALENDAR")
    return "\r\n".join(fold(line) for line in lines) + "\r\n"
