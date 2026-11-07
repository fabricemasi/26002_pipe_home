"""Import / export iCalendar entre un fichier .ics et l'agenda (format : `core/ics.py`).

Import : UNE commande annulable (Ctrl+Z défait tout l'import) ; un événement déjà importé (même UID dans le même
calendrier) est MIS À JOUR, jamais dupliqué ; les exceptions (RECURRENCE-ID) rejoignent leur série."""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from ..core import ics
from ..core import timeutil as tu
from ..core.model import new_id


@dataclass
class ImportReport:
    created: int = 0
    updated: int = 0
    skipped: int = 0
    warnings: list[str] = field(default_factory=list)

    def summary(self) -> str:
        text = f"Import : {self.created} créé(s), {self.updated} mis à jour"
        if self.skipped:
            text += f", {self.skipped} ignoré(s)"
        return text + (f" ({self.warnings[0]})" if self.warnings else "")


def read_text(path) -> str:
    data = Path(path).read_bytes()
    for encoding in ("utf-8-sig", "cp1252", "latin-1"):
        try:
            return data.decode(encoding)
        except UnicodeDecodeError:
            continue
    return data.decode("utf-8", "replace")


def import_text(service, text: str, calendar_id: str) -> ImportReport:
    report = ImportReport()
    cal = service.calendar(calendar_id)
    if cal is None or cal.read_only:
        raise ValueError("calendrier en lecture seule ou introuvable")
    parsed, warnings = ics.read_events(text, calendar_id, tu.tz_name(service.display_tz))
    report.warnings = warnings
    report.skipped = len(warnings)
    changes = []
    masters: dict[str, str] = {}                         # UID -> identifiant local du maître / de l'événement
    for p in sorted(parsed, key=lambda p: p.recurrence_id is not None):
        rec = p.record
        if p.recurrence_id is None:
            existing = service.repo.event_by_uid(calendar_id, p.uid, None)
            if existing is not None:
                after = existing.copy()
                for name in ("title", "description", "location", "url", "notes", "all_day", "start", "end",
                             "start_date", "end_date", "tzid", "rrule", "exdates", "color", "categories",
                             "transparency", "status", "is_task", "done", "project", "folder", "attendees",
                             "reminders", "sequence"):
                    setattr(after, name, getattr(rec, name))
                changes.append((existing.id, existing, after))
                masters[p.uid] = existing.id
                report.updated += 1
            else:
                rec.id = new_id()
                changes.append((rec.id, None, rec))
                masters[p.uid] = rec.id
                report.created += 1
            continue
        series = masters.get(p.uid)
        if series is None:
            master = service.repo.event_by_uid(calendar_id, p.uid, None)
            series = master.id if master is not None else None
        if series is None:                                # exception sans sa série : importée seule
            rec.id = new_id()
            changes.append((rec.id, None, rec))
            report.created += 1
            continue
        rec.series_id = series
        rec.recurrence_id = p.recurrence_id
        rec.rrule = None
        rec.exdates = []
        existing = service.repo.event_by_uid(calendar_id, p.uid, p.recurrence_id)
        if existing is not None:
            rec.id = existing.id
            rec.version = existing.version
            changes.append((existing.id, existing, rec))
            report.updated += 1
        else:
            rec.id = new_id()
            changes.append((rec.id, None, rec))
            report.created += 1
    for _id, _before, after in changes:
        after.version = after.version if _before is not None else 0
    service._commit("Importer un calendrier", changes)
    return report


def import_file(service, path, calendar_id: str) -> ImportReport:
    return import_text(service, read_text(path), calendar_id)


def export_text(service, calendar_ids=None, event_ids=None) -> tuple[str, int]:
    rows, seen = [], set()

    def add(ev):
        if ev is not None and not ev.deleted and ev.id not in seen:
            seen.add(ev.id)
            rows.append(ev)

    for cal_id in calendar_ids or []:
        for ev in service.repo.events_of_calendar(cal_id):
            add(service.get_event(ev.id))
    for eid in event_ids or []:
        ev = service.get_event(eid)
        add(ev)
        if ev is not None and ev.rrule:
            for o in service._overrides(ev.id):
                add(o)
    uid_of = {}
    for ev in rows:
        if not ev.series_id:
            uid_of[ev.id] = ev.ical_uid or f"{ev.id}@pipe-fmz"
    items = []
    for ev in rows:
        if ev.series_id:
            master = service.get_event(ev.series_id)
            uid = uid_of.get(ev.series_id) or (master.ical_uid if master and master.ical_uid else f"{ev.series_id}@pipe-fmz")
            if master is not None and not ev.tzid:
                ev.tzid = master.tzid
        else:
            uid = uid_of[ev.id]
        items.append((ev, uid))
    name = ""
    if calendar_ids and len(calendar_ids) == 1 and service.calendar(calendar_ids[0]):
        name = service.calendar(calendar_ids[0]).name
    return ics.write_calendar(items, name), sum(1 for ev, _u in items if not ev.series_id)


def export_events(service, path, calendar_ids=None, event_ids=None) -> int:
    text, count = export_text(service, calendar_ids, event_ids)
    Path(path).write_bytes(text.encode("utf-8"))
    return count
