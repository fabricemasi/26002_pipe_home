"""Service de l'agenda : SEULE porte d'entrée de l'interface (qui ne connaît ni SQLite ni Google).

Lecture : occurrences d'une période dans le fuseau d'affichage, servies depuis un cache PAR MOIS (chargé à la
demande par une requête indexée, séries déroulées une fois) ; afficher une semaine ne charge que son ou ses mois.

Écriture : une modification est d'abord appliquée en mémoire (`_pending`, cache invalidé, signal `changed`) — la
vue la montre aussitôt — puis écrite par le fil d'écriture (`DbWriter`) dans UNE transaction ; l'échec d'une
écriture annule la modification en mémoire et le signale. Chaque modification est une COMMANDE annulable
(avant / après de chaque ligne touchée).

Séries : `save_draft` / `delete_occurrence` / `move_occurrence` prennent une portée — "this" (exception de cette
occurrence), "following" (découpe de la série), "all" (série entière)."""
from __future__ import annotations

import logging
import time
from collections import OrderedDict, defaultdict
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from pathlib import Path

from PySide6.QtCore import QObject, QTimer, Signal

from ..core import recurrence as rec
from ..core import timeutil as tu
from ..core.model import Calendar, EventRecord, Occurrence, new_id
from ..store import database as db
from ..store.repository import RangeHints, Repository, now_ts, stamp
from .writer import DbWriter

log = logging.getLogger("fm_agenda.service")

DEFAULT_CALENDARS = (("Projets et revues", "bleu"), ("Rendus", "violet"), ("Livraisons et jalons", "orange"),
                     ("Équipe", "vert"), ("Tâches", "rouge"), ("Personnel", "cyan"))
MAX_CACHED_MONTHS = 36
SCOPES = ("this", "following", "all")


@dataclass
class Command:
    label: str
    changes: list = field(default_factory=list)      # [(id, avant | None, après | None)]


class AgendaService(QObject):
    changed = Signal()                  # occurrences modifiées (local, annuler, synchronisation)
    calendarsChanged = Signal()
    undoChanged = Signal()
    message = Signal(str, str)          # (niveau « info » / « erreur », texte)
    syncChanged = Signal()              # état de la synchronisation (comptes, file d'envoi, erreurs)

    def __init__(self, settings: dict | None = None, parent=None, path: Path | None = None):
        super().__init__(parent)
        self.settings = dict(settings or {})
        if path is None:
            path = db.resolve_data_dir(self.settings.get("agenda_data_dir")) / db.DB_NAME
        self.path = Path(path)
        self.hints = RangeHints()
        conn, self.open_report = db.open_database(self.path)
        self._wrepo = Repository(conn, self.hints)
        self._wrepo.refresh_hints()
        self.device_id = self._wrepo.device_id()
        self.origin = f"device:{self.device_id}"
        if not self._wrepo.list_calendars(include_deleted=True):
            self._seed_calendars()
        self._prefs = {k[5:]: v for k, v in ((r[0], r[1]) for r in conn.execute(
            "SELECT key, value FROM meta WHERE key LIKE 'pref:%'"))}
        self._prefs = {k: _json(v) for k, v in self._prefs.items()}
        self.read_conn = db.connect(self.path)
        self.repo = Repository(self.read_conn, self.hints)
        self.writer = DbWriter(conn, self.hints)
        self._calendars: dict[str, Calendar] = {c.id: c for c in self.repo.list_calendars()}
        self._pending: dict[str, EventRecord | None] = {}
        self._inflight: dict[str, int] = defaultdict(int)
        self._months: OrderedDict[tuple[int, int], list[Occurrence]] = OrderedDict()
        self._year_counts: dict[tuple[int, bool], dict[date, int]] = {}
        self._undo: list[Command] = []
        self._redo: list[Command] = []
        self._closed = False
        self.sync = None                                 # sync.engine.SyncManager (posé par la fenêtre)
        self.apply_settings(self.settings, initial=True)
        for text in self.open_report.messages:
            log.warning(text)
        self._backup_timer = QTimer(self)
        self._backup_timer.setSingleShot(True)
        self._backup_timer.timeout.connect(self._daily_backup)
        self._backup_timer.start(4000)

    # -- réglages --

    def apply_settings(self, settings: dict, initial: bool = False) -> None:
        old_tz = getattr(self, "display_tz", None)
        self.settings.update(settings or {})
        self.display_tz = tu.get_tz(self.settings.get("agenda_timezone") or None)
        self.first_weekday = int(self.settings.get("agenda_first_weekday", 0) or 0) % 7
        if not initial and old_tz is not None and tu.tz_name(old_tz) != tu.tz_name(self.display_tz):
            self.invalidate()

    def _seed_calendars(self) -> None:
        with db.transaction(self._wrepo.conn):
            for i, (name, color) in enumerate(DEFAULT_CALENDARS):
                self._wrepo.upsert_calendar(Calendar(id=new_id(), name=name, color=color, sort_order=i))

    # -- fermeture --

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        self._backup_timer.stop()
        if self.sync is not None:
            try:
                self.sync.stop()
            except Exception:                            # noqa: BLE001
                log.exception("arrêt de la synchronisation")
        self.writer.flush(15)
        self.writer.stop()
        try:
            self.read_conn.close()
        except Exception:                                # noqa: BLE001
            pass
        db.close_database(self.writer.repo.conn, self.path)

    def flush(self, timeout: float = 10.0) -> bool:
        """Attend les écritures en cours (tests, sauvegarde). Les rappels Qt restent à délivrer."""
        return self.writer.flush(timeout)

    # -- préférences de l'interface (vue, date, largeurs) : table meta --

    def pref(self, key: str, default=None):
        return self._prefs.get(key, default)

    def set_pref(self, key: str, value) -> None:
        if self._prefs.get(key) == value:
            return
        self._prefs[key] = value
        self.writer.submit(lambda repo: repo.set_meta("pref:" + key, value))

    # -- calendriers --

    def calendars(self, include_hidden: bool = True) -> list[Calendar]:
        cals = sorted(self._calendars.values(), key=lambda c: (c.sort_order, c.name.lower()))
        return [c for c in cals if include_hidden or c.visible]

    def calendar(self, cal_id: str | None) -> Calendar | None:
        return self._calendars.get(cal_id) if cal_id else None

    def default_calendar(self) -> Calendar | None:
        wanted = self.settings.get("agenda_default_calendar") or ""
        cal = self._calendars.get(wanted)
        if cal is None or cal.read_only:
            cal = next((c for c in self.calendars() if not c.read_only and c.visible), None) or next(
                (c for c in self.calendars() if not c.read_only), None)
        return cal

    def writable_calendars(self) -> list[Calendar]:
        return [c for c in self.calendars() if not c.read_only]

    def _save_calendar(self, cal: Calendar, label: str = "") -> None:
        self._calendars[cal.id] = cal
        snapshot = Calendar(**{k: (dict(v) if isinstance(v, dict) else v) for k, v in cal.__dict__.items()})

        def task(repo):
            repo.upsert_calendar(snapshot)
            repo.log_change("calendar", snapshot.id, "upsert", 0, self.origin)
        self.writer.submit(task, on_error=self._write_failed)
        self.calendarsChanged.emit()

    def create_calendar(self, name: str, color: str = "bleu") -> Calendar:
        order = max((c.sort_order for c in self._calendars.values()), default=0) + 1
        cal = Calendar(id=new_id(), name=name.strip() or "Calendrier", color=color, sort_order=order)
        self._save_calendar(cal)
        return cal

    def update_calendar(self, cal_id: str, **fields) -> None:
        cal = self._calendars.get(cal_id)
        if cal is None:
            return
        visibility_only = set(fields) <= {"visible"}
        for key, value in fields.items():
            setattr(cal, key, value)
        self._save_calendar(cal)
        if not visibility_only:
            self.invalidate()
        else:
            self._year_counts.clear()
            self.changed.emit()

    def set_visible(self, cal_id: str, visible: bool) -> None:
        self.update_calendar(cal_id, visible=bool(visible))

    def delete_calendar(self, cal_id: str) -> None:
        """Calendrier LOCAL supprimé avec ses événements (un calendrier distant se déconnecte dans Synchronisation)."""
        cal = self._calendars.pop(cal_id, None)
        if cal is None:
            return
        self._undo = [c for c in self._undo if not any(
            (b or a).calendar_id == cal_id for _i, b, a in c.changes if (b or a) is not None)]
        self._redo.clear()

        def task(repo):
            repo.delete_calendar(cal_id)
            repo.log_change("calendar", cal_id, "delete", 0, self.origin)
        self.writer.submit(task, on_error=self._write_failed)
        self.calendarsChanged.emit()
        self.invalidate()
        self.undoChanged.emit()

    def reload_calendars(self) -> None:
        self._calendars = {c.id: c for c in self.repo.list_calendars()}
        self.calendarsChanged.emit()

    # -- lecture --

    def invalidate(self) -> None:
        self._months.clear()
        self._year_counts.clear()
        self.changed.emit()

    def get_event(self, event_id: str) -> EventRecord | None:
        if event_id in self._pending:
            ev = self._pending[event_id]
            return ev.copy() if ev is not None else None
        return self.repo.get_event(event_id, include_deleted=False)

    def occurrences(self, start: date, end: date, visible_only: bool = True) -> list[Occurrence]:
        """Occurrences qui chevauchent les jours [start, end[ (fuseau d'affichage), triées par début."""
        out, seen = [], set()
        m = date(start.year, start.month, 1)
        tz = self.display_tz
        t0 = tu.day_start(start, tz)
        t1 = tu.day_start(end, tz)
        hidden = {c for c, cal in self._calendars.items() if not cal.visible} if visible_only else set()
        while m < end:
            for occ in self._month(m.year, m.month):
                if occ.key in seen or occ.calendar_id in hidden:
                    continue
                if occ.all_day:
                    if not (occ.start_date < end and occ.end_date > start):
                        continue
                elif not (occ.start < t1 and (occ.end > t0 or (occ.end == occ.start and occ.start >= t0))):
                    continue
                seen.add(occ.key)
                out.append(occ)
            m = tu.add_months(m, 1)
        out.sort(key=lambda o: (o.start, not o.all_day, -(o.end - o.start).total_seconds()))
        return out

    def _month(self, year: int, month: int) -> list[Occurrence]:
        key = (year, month)
        cached = self._months.get(key)
        if cached is not None:
            self._months.move_to_end(key)
            return cached
        if self._closed:
            return []
        d0 = date(year, month, 1)
        d1 = tu.add_months(d0, 1)
        occs = self._load(d0, d1)
        self._months[key] = occs
        while len(self._months) > MAX_CACHED_MONTHS:
            self._months.popitem(last=False)
        return occs

    def prefetch(self, around: date) -> None:
        """Mois voisins chargés pendant un temps mort (navigation suivante sans requête)."""
        if self._closed:
            return
        for delta in (-1, 1):
            m = tu.add_months(date(around.year, around.month, 1), delta)
            if (m.year, m.month) not in self._months:
                self._month(m.year, m.month)

    def _rows(self, t0: int, t1: int) -> list[EventRecord]:
        rows = self.repo.window_rows(t0, t1)
        if not self._pending:
            return rows
        out, seen = [], set()
        for r in rows:
            seen.add(r.id)
            if r.id in self._pending:
                p = self._pending[r.id]
                if p is not None:
                    out.append(p)
            else:
                out.append(r)
        for pid, p in self._pending.items():
            if pid not in seen and p is not None and not p.deleted:
                out.append(p)
        return out

    def _load(self, d0: date, d1: date) -> list[Occurrence]:
        tz = self.display_tz
        w0, w1 = tu.day_start(d0, tz), tu.day_start(d1, tz)
        rows = self._rows(tu.to_ts(w0) - 86400, tu.to_ts(w1) + 86400)
        return self._expand(rows, d0, d1, w0, w1)

    def _expand(self, rows: list[EventRecord], d0: date, d1: date, w0: datetime, w1: datetime) -> list[Occurrence]:
        tz = self.display_tz
        overrides: dict[str, dict[str, EventRecord]] = defaultdict(dict)
        for r in rows:
            if r.series_id and r.recurrence_id:
                overrides[r.series_id][r.recurrence_id] = r
        out = []
        for r in rows:
            if r.deleted:
                continue
            ro = self._read_only(r.calendar_id)
            if r.series_id:
                if r.status != "cancelled":
                    occ = self._occurrence(r, r.recurrence_id, r.series_id, ro)
                    if _overlaps(occ, d0, d1, w0, w1):
                        out.append(occ)
                continue
            if r.rrule:
                exd = set(r.exdates)
                ovr = overrides.get(r.id, {})
                try:
                    starts = rec.occurrence_starts(r.rrule, r.start_date if r.all_day else r.start, r.tzid,
                                                   r.all_day, d0 if r.all_day else w0, d1 if r.all_day else w1,
                                                   r.duration)
                except Exception as exc:                 # noqa: BLE001 - règle illisible : l'événement seul
                    log.warning("règle illisible %r : %s", r.rrule, exc)
                    starts = [r.start_date if r.all_day else r.start]
                dur = r.duration
                for s in starts:
                    rid = rec.rid_of(s, r.all_day)
                    if rid in exd or rid in ovr:
                        continue
                    if r.all_day:
                        occ = Occurrence(r, tu.day_start(s, tz), tu.day_start(s + dur, tz), s, s + dur, rid, r.id, ro)
                    else:
                        occ = Occurrence(r, s.astimezone(tz), (s + dur).astimezone(tz), None, None, rid, r.id, ro)
                    out.append(occ)
                continue
            if r.status == "cancelled":
                continue
            occ = self._occurrence(r, None, None, ro)
            if _overlaps(occ, d0, d1, w0, w1):
                out.append(occ)
        return out

    def _occurrence(self, r: EventRecord, rid, series, ro) -> Occurrence:
        tz = self.display_tz
        if r.all_day:
            return Occurrence(r, tu.day_start(r.start_date, tz), tu.day_start(r.end_date, tz), r.start_date,
                              r.end_date, rid, series, ro)
        return Occurrence(r, r.start.astimezone(tz), r.end.astimezone(tz), None, None, rid, series, ro)

    def _read_only(self, cal_id: str) -> bool:
        cal = self._calendars.get(cal_id)
        return cal is None or cal.read_only

    def day_counts(self, year: int, visible_only: bool = True) -> dict[date, int]:
        """Nombre d'événements par jour d'une année (vue Année : intensité des jours). Requête légère pour les
        événements simples, séries déroulées."""
        key = (year, visible_only)
        if key in self._year_counts:
            return self._year_counts[key]
        tz = self.display_tz
        d0, d1 = date(year, 1, 1), date(year + 1, 1, 1)
        counts: dict[date, int] = defaultdict(int)
        hidden = {c for c, cal in self._calendars.items() if not cal.visible} if visible_only else set()
        if self._pending:
            for occ in self.occurrences(d0, d1, visible_only):
                for d in occ.days():
                    if d0 <= d < d1:
                        counts[d] += 1
        else:
            t0 = tu.day_start_ts(d0, tz) - 86400
            t1 = tu.day_start_ts(d1, tz) + 86400
            for start_ts, end_ts, all_day, sd, ed, cal_id, status in self.repo.window_counts_rows(t0, t1):
                if cal_id in hidden or status == "cancelled":
                    continue
                if all_day:
                    first, last = date.fromisoformat(sd), date.fromisoformat(ed) - timedelta(days=1)
                else:
                    first = tu.from_ts(start_ts, tz).date()
                    last = tu.from_ts(max(start_ts, end_ts - 1), tz).date()
                d = max(first, d0)
                last = min(last, d1 - timedelta(days=1))
                while d <= last:
                    counts[d] += 1
                    d += timedelta(days=1)
            masters = self.repo.masters_in(t0, t1)
            rows = list(masters)
            for m in masters:
                rows.extend(self.repo.overrides_of(m.id))
            w0, w1 = tu.day_start(d0, tz), tu.day_start(d1, tz)
            for occ in self._expand(rows, d0, d1, w0, w1):
                if occ.calendar_id in hidden or not occ.recurring:
                    continue
                for d in occ.days():
                    if d0 <= d < d1:
                        counts[d] += 1
        self._year_counts[key] = dict(counts)
        return self._year_counts[key]

    def search(self, text: str, limit: int = 300) -> list[Occurrence]:
        """Recherche dans les titres, lieux, descriptions, notes, projets et catégories. Une série est rendue par
        sa prochaine occurrence (ou la dernière passée)."""
        rows = self.repo.search(text, limit)
        if self._pending:
            words = [w for w in text.lower().split() if w]
            ids = {r.id for r in rows}
            rows = [self._pending.get(r.id, r) for r in rows if self._pending.get(r.id, r) is not None]
            for pid, p in self._pending.items():
                if p is not None and pid not in ids and not p.deleted and all(
                        w in " ".join((p.title, p.location, p.description, p.notes, p.project)).lower()
                        for w in words):
                    rows.append(p)
        tz = self.display_tz
        today = date.today()
        out = []
        for r in rows:
            if r.deleted or not self._calendars.get(r.calendar_id):
                continue
            ro = self._read_only(r.calendar_id)
            if r.rrule and not r.series_id:
                horizon = [(today, today + timedelta(days=400)), (today - timedelta(days=400), today)]
                found = None
                for a, b in horizon:
                    occs = self._expand([r], a, b, tu.day_start(a, tz), tu.day_start(b, tz))
                    if occs:
                        found = occs[0] if a == today else occs[-1]
                        break
                out.append(found or self._occurrence(r, None, None, ro))
            elif r.series_id:
                out.append(self._occurrence(r, r.recurrence_id, r.series_id, ro))
            else:
                out.append(self._occurrence(r, None, None, ro))
        out.sort(key=lambda o: o.start)
        return out

    def count(self) -> int:
        return self.repo.count_events()

    # -- brouillons (éditeur) --

    def new_draft(self, start: datetime | date | None = None, end: datetime | date | None = None,
                  all_day: bool = False, calendar_id: str | None = None) -> EventRecord:
        cal = self.calendar(calendar_id) or self.default_calendar()
        tzid = tu.tz_name(self.display_tz)
        ev = EventRecord(id=new_id(), calendar_id=cal.id if cal else "", tzid=tzid)
        minutes = int(self.settings.get("agenda_default_duration", 60) or 60)
        if all_day or isinstance(start, date) and not isinstance(start, datetime):
            ev.all_day = True
            d = start if isinstance(start, date) else date.today()
            if isinstance(d, datetime):
                d = d.date()
            ev.start_date = d
            e = end if isinstance(end, date) and not isinstance(end, datetime) else d + timedelta(days=1)
            ev.end_date = e if e > d else d + timedelta(days=1)
        else:
            if start is None:
                now = datetime.now(self.display_tz)
                start = now.replace(minute=0, second=0, microsecond=0) + timedelta(hours=1)
            ev.start = start.astimezone(self.display_tz)
            ev.end = (end or ev.start + timedelta(minutes=minutes)).astimezone(self.display_tz)
        default = self.settings.get("agenda_default_reminder", -1)
        if isinstance(default, list):
            ev.reminders = [int(m) for m in default]
        elif isinstance(default, (int, float)) and default >= 0:
            ev.reminders = [int(default)]
        return ev

    def draft_for(self, occ: Occurrence) -> EventRecord:
        """Événement à éditer pour une occurrence : la ligne elle-même (simple, exception), ou le maître de la série
        aux dates de cette occurrence."""
        ev = self.get_event(occ.event_id)
        if ev is None:
            raise KeyError(occ.event_id)
        if ev.rrule and not ev.series_id and occ.recurrence_id:
            self._place(ev, occ)
        return ev

    def _place(self, ev: EventRecord, occ: Occurrence) -> None:
        """Le maître `ev` aux dates de l'occurrence `occ`."""
        if ev.all_day:
            dur = ev.end_date - ev.start_date
            ev.start_date = occ.start_date
            ev.end_date = occ.start_date + dur
        else:
            dur = ev.end - ev.start
            ev.start = occ.start.astimezone(ev.tz)
            ev.end = ev.start + dur

    # -- écriture --

    def _synced(self, cal_id: str) -> bool:
        cal = self._calendars.get(cal_id)
        return bool(cal and cal.synced)

    def _commit(self, label: str, changes: list, record: bool = True) -> None:
        """Applique `changes` [(id, avant, après)] : mémoire tout de suite, disque par le fil d'écriture."""
        if not changes:
            return
        finals = []
        for event_id, before, after in changes:
            if after is not None:
                after = after.copy()
                stamp(after, self.origin, self._synced(after.calendar_id))
                if before is not None:
                    after.version = max(after.version, before.version + 1)
                errors = after.validate()
                if errors:
                    self.message.emit("erreur", "Événement refusé : " + ", ".join(errors))
                    return
            finals.append((event_id, before.copy() if before is not None else None, after))
        for event_id, _before, after in finals:
            self._pending[event_id] = after
            self._inflight[event_id] += 1
        if record:
            self._undo.append(Command(label, finals))
            del self._undo[:-200]
            self._redo.clear()
        self._months.clear()
        self._year_counts.clear()
        self.changed.emit()
        self.undoChanged.emit()
        calendars = {k: (c.synced, c.account_id) for k, c in self._calendars.items()}
        origin = self.origin

        def task(repo: Repository):
            for event_id, before, after in finals:
                _write_change(repo, event_id, before, after, calendars, origin)
            return [c[0] for c in finals]

        def done(ids):
            self._settle(ids)
            if self.sync is not None:
                self.sync.local_changed()

        def failed(error, ids=[c[0] for c in finals], snapshot=finals, cmd_label=label):
            self._settle(ids)
            if record and self._undo and self._undo[-1].changes is snapshot:
                self._undo.pop()
            self.invalidate()
            self.undoChanged.emit()
            self.message.emit("erreur", f"« {cmd_label} » n'a pas pu être enregistré : {error}")
        self.writer.submit(task, done, failed)

    def _settle(self, ids) -> None:
        for event_id in ids:
            self._inflight[event_id] -= 1
            if self._inflight[event_id] <= 0:
                self._inflight.pop(event_id, None)
                self._pending.pop(event_id, None)

    def _write_failed(self, error: str) -> None:
        self.message.emit("erreur", f"Écriture de l'agenda échouée : {error}")

    # -- opérations --

    def create(self, ev: EventRecord, label: str = "Nouvel événement") -> str:
        ev = ev.copy()
        if not ev.id:
            ev.id = new_id()
        ev.version = 0
        ev.remote_id = ev.etag = None
        self._commit(label, [(ev.id, None, ev)])
        return ev.id

    def save_draft(self, occ: Occurrence | None, draft: EventRecord, scope: str = "all") -> str:
        """Enregistre l'éditeur. `occ` None : création. Rend l'identifiant de la ligne qui porte le résultat."""
        if occ is None:
            existing = self.get_event(draft.id)
            if existing is None:
                return self.create(draft)
            return self._update_simple(existing, draft, "Modifier l'événement")
        current = self.get_event(occ.event_id)
        if current is None:
            return self.create(draft)
        if not occ.recurring:
            return self._update_simple(current, draft, "Modifier l'événement")
        master = current if not current.series_id else self.get_event(current.series_id)
        if master is None:                                # exception orpheline : modifiée seule
            return self._update_simple(current, draft, "Modifier l'occurrence")
        if scope == "this":
            return self._save_this(master, current if current.series_id else None, occ, draft)
        if scope == "following" and not self._is_first(master, occ):
            return self._save_following(master, occ, draft)
        return self._save_all(master, occ, draft)

    def _update_simple(self, current: EventRecord, draft: EventRecord, label: str) -> str:
        after = _merge_content(current, draft)
        changes = []
        old_cal, new_cal = self._calendars.get(current.calendar_id), self._calendars.get(after.calendar_id)
        moved_source = (old_cal is not None and new_cal is not None and current.calendar_id != after.calendar_id
                        and (old_cal.synced or new_cal.synced))
        if moved_source:
            # Changement de calendrier synchronisé : supprimé de l'ancien, créé (nouvel identifiant) dans le nouveau.
            fresh = after.copy()
            fresh.id = new_id()
            fresh.remote_id = fresh.etag = None
            fresh.version = 0
            changes.append((current.id, current, None))
            for o in (self._overrides(current.id) if current.rrule else []):
                changes.append((o.id, o, None))
            changes.append((fresh.id, None, fresh))
            self._commit(label, changes)
            return fresh.id
        if current.rrule and not after.rrule:
            for o in self._overrides(current.id):         # plus de série : ses exceptions disparaissent
                changes.append((o.id, o, None))
        changes.insert(0, (current.id, current, after))
        self._commit(label, changes)
        return current.id

    def _overrides(self, series_id: str) -> list[EventRecord]:
        rows = {o.id: o for o in self.repo.overrides_of(series_id)}
        for pid, p in self._pending.items():
            if p is None:
                rows.pop(pid, None)
            elif p.series_id == series_id:
                rows[pid] = p
        return [o for o in rows.values() if not o.deleted]

    def _is_first(self, master: EventRecord, occ: Occurrence) -> bool:
        first = master.start_date if master.all_day else master.start
        return occ.recurrence_id == rec.rid_of(first, master.all_day)

    def _original_start(self, master: EventRecord, occ: Occurrence):
        return tu.parse_rid(occ.recurrence_id, master.tz) if occ.recurrence_id else (
            occ.start_date if master.all_day else occ.start)

    def _save_this(self, master, override, occ, draft) -> str:
        if override is None:
            ov = _merge_content(master, draft)
            ov.id = new_id()
            ov.series_id = master.id
            ov.recurrence_id = occ.recurrence_id
            ov.rrule = None
            ov.exdates = []
            ov.remote_id = ov.etag = None
            ov.version = 0
            ov.ical_uid = master.ical_uid
            self._commit("Modifier l'occurrence", [(ov.id, None, ov)])
            return ov.id
        after = _merge_content(override, draft)
        after.rrule = None
        after.exdates = []
        self._commit("Modifier l'occurrence", [(override.id, override, after)])
        return override.id

    def _save_all(self, master, occ, draft) -> str:
        after = _merge_content(master, draft)
        changes = []
        if draft.rrule:
            # Décalage de l'occurrence éditée (par rapport à ce qui était affiché) = décalage de toute la série, de
            # ses exceptions et de ses exclusions.
            if master.all_day and draft.all_day:
                delta = timedelta(days=(draft.start_date - occ.start_date).days)
                after.start_date = master.start_date + delta
                after.end_date = after.start_date + (draft.end_date - draft.start_date)
            elif not master.all_day and not draft.all_day:
                delta = draft.start - occ.start
                after.start = master.start + delta
                after.end = after.start + (draft.end - draft.start)
            else:                                         # journée <-> horaire : la série repart de l'occurrence
                delta = None
                after.start, after.end = draft.start, draft.end
                after.start_date, after.end_date = draft.start_date, draft.end_date
            if delta:
                after.exdates = [rec.shift_rid(x, delta, master.all_day) for x in master.exdates]
                for o in self._overrides(master.id):
                    moved = o.copy()
                    moved.recurrence_id = rec.shift_rid(o.recurrence_id, delta, master.all_day)
                    changes.append((o.id, o, moved))
            elif delta is None:
                after.exdates = []
                for o in self._overrides(master.id):
                    changes.append((o.id, o, None))
        else:
            for o in self._overrides(master.id):
                changes.append((o.id, o, None))
            after.exdates = []
        changes.insert(0, (master.id, master, after))
        self._commit("Modifier la série", changes)
        return master.id

    def _save_following(self, master, occ, draft) -> str:
        original = self._original_start(master, occ)
        rule = rec.parse_rrule(master.rrule)
        old = master.copy()
        new_rule = rec.parse_rrule(draft.rrule) if draft.rrule else None
        if rule.count:
            before = rec.count_before(master.rrule, master.start_date if master.all_day else master.start,
                                      master.tzid, master.all_day, original)
            remaining = max(1, rule.count - before)
            rule.count = before
            if new_rule is not None and new_rule.count == parse_count(master.rrule):
                new_rule.count = remaining
        else:
            rule.until = rec.until_before(original, master.all_day)
        old.rrule = rec.format_rrule(rule)
        split_rid = occ.recurrence_id
        fresh = _merge_content(master, draft)
        fresh.id = new_id()
        fresh.remote_id = fresh.etag = None
        fresh.version = 0
        fresh.ical_uid = None
        fresh.rrule = rec.format_rrule(new_rule) if new_rule is not None else None
        if master.all_day == draft.all_day:
            delta = (timedelta(days=(draft.start_date - occ.start_date).days) if draft.all_day
                     else draft.start - occ.start)
        else:
            delta = None
        shift = (lambda rid: rec.shift_rid(rid, delta, master.all_day) if delta else rid)
        fresh.exdates = [shift(x) for x in master.exdates if x >= split_rid] if fresh.rrule and delta is not None \
            else []
        old.exdates = [x for x in master.exdates if x < split_rid]
        changes = [(master.id, master, old), (fresh.id, None, fresh)]
        for o in self._overrides(master.id):
            if o.recurrence_id and o.recurrence_id >= split_rid:
                changes.append((o.id, o, None))
                if fresh.rrule and delta is not None:
                    moved = o.copy()
                    moved.id = new_id()
                    moved.series_id = fresh.id
                    moved.recurrence_id = shift(o.recurrence_id)
                    moved.remote_id = moved.etag = None
                    moved.version = 0
                    changes.append((moved.id, None, moved))
        self._commit("Modifier les occurrences suivantes", changes)
        return fresh.id

    def move_occurrence(self, occ: Occurrence, start, end, scope: str = "all") -> str:
        """Glisser-déposer / redimensionnement : nouvelles bornes (datetimes aware, ou dates pour une journée)."""
        draft = self.draft_for(occ)
        if isinstance(start, datetime):
            draft.all_day = False
            draft.start = start.astimezone(draft.tz)
            draft.end = end.astimezone(draft.tz)
            draft.start_date = draft.end_date = None
        else:
            draft.all_day = True
            draft.start_date, draft.end_date = start, end
            draft.start = draft.end = None
        return self.save_draft(occ, draft, scope)

    def delete_occurrence(self, occ: Occurrence, scope: str = "all") -> None:
        current = self.get_event(occ.event_id)
        if current is None:
            return
        if not occ.recurring:
            changes = [(current.id, current, None)]
            if current.rrule:
                changes += [(o.id, o, None) for o in self._overrides(current.id)]
            self._commit("Supprimer l'événement", changes)
            return
        master = current if not current.series_id else self.get_event(current.series_id)
        if master is None:
            self._commit("Supprimer l'occurrence", [(current.id, current, None)])
            return
        overrides = self._overrides(master.id)
        if scope == "this":
            after = master.copy()
            after.exdates = sorted(set(master.exdates) | {occ.recurrence_id})
            changes = [(master.id, master, after)]
            changes += [(o.id, o, None) for o in overrides if o.recurrence_id == occ.recurrence_id]
            self._commit("Supprimer l'occurrence", changes)
        elif scope == "following" and not self._is_first(master, occ):
            original = self._original_start(master, occ)
            rule = rec.parse_rrule(master.rrule)
            after = master.copy()
            if rule.count:
                rule.count = max(1, rec.count_before(master.rrule, master.start_date if master.all_day
                                                     else master.start, master.tzid, master.all_day, original))
            else:
                rule.until = rec.until_before(original, master.all_day)
            after.rrule = rec.format_rrule(rule)
            after.exdates = [x for x in master.exdates if x < occ.recurrence_id]
            changes = [(master.id, master, after)]
            changes += [(o.id, o, None) for o in overrides if o.recurrence_id >= occ.recurrence_id]
            self._commit("Supprimer les occurrences suivantes", changes)
        else:
            changes = [(master.id, master, None)] + [(o.id, o, None) for o in overrides]
            self._commit("Supprimer la série", changes)

    def duplicate(self, occ: Occurrence, days: int = 0) -> str:
        """Copie indépendante de l'occurrence (sans récurrence), décalée de `days` jours."""
        draft = self.draft_for(occ)
        copy_ = draft.copy()
        copy_.id = new_id()
        copy_.series_id = copy_.recurrence_id = None
        copy_.rrule = None
        copy_.exdates = []
        copy_.remote_id = copy_.etag = copy_.ical_uid = None
        copy_.attendees = []
        if days:
            if copy_.all_day:
                copy_.start_date += timedelta(days=days)
                copy_.end_date += timedelta(days=days)
            else:
                copy_.start += timedelta(days=days)
                copy_.end += timedelta(days=days)
        return self.create(copy_, "Dupliquer l'événement")

    def set_done(self, occ: Occurrence, done: bool) -> None:
        draft = self.draft_for(occ)
        draft.done = bool(done)
        self.save_draft(occ, draft, "this" if occ.recurring else "all")

    # -- annuler / rétablir --

    def can_undo(self) -> bool:
        return bool(self._undo)

    def can_redo(self) -> bool:
        return bool(self._redo)

    def undo_label(self) -> str:
        return self._undo[-1].label if self._undo else ""

    def redo_label(self) -> str:
        return self._redo[-1].label if self._redo else ""

    def undo(self) -> bool:
        if not self._undo:
            return False
        cmd = self._undo.pop()
        self._redo.append(cmd)
        self._commit("Annuler : " + cmd.label, self._reverse(cmd, undo=True), record=False)
        self.undoChanged.emit()
        return True

    def redo(self) -> bool:
        if not self._redo:
            return False
        cmd = self._redo.pop()
        self._undo.append(cmd)
        self._commit("Rétablir : " + cmd.label, self._reverse(cmd, undo=False), record=False)
        self.undoChanged.emit()
        return True

    def _reverse(self, cmd: Command, undo: bool) -> list:
        """Changements à rejouer : l'état courant de chaque ligne vers son état avant (annuler) ou après
        (rétablir) — l'état courant, pas celui de la commande : la synchronisation a pu passer entre-temps."""
        out = []
        items = reversed(cmd.changes) if undo else cmd.changes
        for event_id, before, after in items:
            target = before if undo else after
            current = self.get_event(event_id)
            if target is None:
                if current is not None:
                    out.append((event_id, current, None))
                continue
            restored = target.copy()
            if current is not None:
                restored.version = current.version
                restored.remote_id, restored.etag = current.remote_id, current.etag
            out.append((event_id, current, restored))
        return out

    # -- sauvegardes --

    def backup_now(self, on_done=None) -> None:
        path = self.path
        keep = int(self.settings.get("agenda_backup_keep", 14) or 14)
        folder = self.settings.get("agenda_backup_dir") or ""

        def task(repo):
            target_dir = Path(folder) if folder else db.backups_dir(path)
            dest = db.backup(repo.conn, target_dir / db.backup_name())
            if not folder:
                db.rotate_backups(path, keep)
            repo.set_meta("last_backup", {"at": now_ts(), "file": str(dest)})
            return dest

        def done(dest):
            self.message.emit("info", f"Agenda sauvegardé : {dest}")
            if on_done:
                on_done(dest)
        self.writer.submit(task, done, self._write_failed, transactional=False)

    def last_backup(self) -> dict | None:
        return self.repo.get_meta("last_backup")

    def _daily_backup(self) -> None:
        if not self.settings.get("agenda_backup_daily", True):
            return
        last = self.repo.get_meta("last_backup") or {}
        if time.time() - float(last.get("at", 0)) > 86400 * 0.95:
            self.backup_now()

    # -- rappels montrés (services/reminders.py) --

    def reminder_rows(self, t0: int, t1: int) -> list[EventRecord]:
        rows = {r.id: r for r in self.repo.with_reminders(t0, t1)}
        for m in [r for r in rows.values() if r.rrule]:
            for o in self.repo.overrides_of(m.id):
                rows.setdefault(o.id, o)
        for pid, p in self._pending.items():
            if p is None:
                rows.pop(pid, None)
            elif p.reminders or p.reminders_default:
                rows[pid] = p
        return list(rows.values())

    def expand_rows(self, rows, d0: date, d1: date) -> list[Occurrence]:
        tz = self.display_tz
        return self._expand(rows, d0, d1, tu.day_start(d0, tz), tu.day_start(d1, tz))

    def reminder_fired(self, key: str, minutes: int) -> bool:
        return self.repo.reminder_fired(key, minutes)

    def mark_reminder(self, key: str, minutes: int) -> None:
        self.writer.submit(lambda repo: repo.mark_reminder(key, minutes))

    # -- synchronisation (sync.engine) --

    def remote_applied(self) -> None:
        """Le fil de synchronisation a écrit des changements distants : relecture."""
        self.reload_calendars()
        self.invalidate()
        self.syncChanged.emit()


def parse_count(rule_text: str | None) -> int | None:
    try:
        return rec.parse_rrule(rule_text).count if rule_text else None
    except ValueError:
        return None


def _json(text):
    import json
    try:
        return json.loads(text)
    except (TypeError, ValueError):
        return text


def _overlaps(occ: Occurrence, d0: date, d1: date, w0: datetime, w1: datetime) -> bool:
    if occ.all_day:
        return occ.start_date < d1 and occ.end_date > d0
    if occ.end == occ.start:
        return w0 <= occ.start < w1
    return occ.start < w1 and occ.end > w0


def _merge_content(current: EventRecord, draft: EventRecord) -> EventRecord:
    """Contenu du brouillon sur la ligne courante (identité et champs de synchronisation conservés)."""
    out = current.copy()
    for name in ("calendar_id", "title", "description", "location", "url", "notes", "all_day", "start", "end",
                 "start_date", "end_date", "tzid", "rrule", "color", "categories", "transparency", "status", "is_task",
                 "done", "project", "folder", "attendees", "reminders", "reminders_default"):
        setattr(out, name, _clone(getattr(draft, name)))
    if out.all_day:
        out.start = out.end = None
    else:
        out.start_date = out.end_date = None
    return out


def _clone(value):
    import copy
    return copy.deepcopy(value) if isinstance(value, (list, dict)) else value


def _write_change(repo: Repository, event_id: str, before, after, calendars: dict, origin: str) -> None:
    """Une ligne dans la transaction du fil d'écriture (création, contenu, suppression douce ou réelle)."""
    state = repo.sync_state_of(event_id)
    if after is None:
        if state is None:
            return
        _sync_state, remote_id = state
        cal_id = (before.calendar_id if before is not None else None)
        synced, account = calendars.get(cal_id, (False, None)) if cal_id else (False, None)
        if remote_id is None:
            repo.delete_event(event_id)
        else:
            version = (before.version + 1) if before is not None else 1
            repo.set_sync_fields(event_id, deleted=1, sync_state="deleted", version=version, updated_at=now_ts(),
                                 origin=origin)
            if synced:
                repo.enqueue(event_id, cal_id, account)
        repo.log_change("event", event_id, "delete", before.version + 1 if before else 0, origin)
        return
    synced, account = calendars.get(after.calendar_id, (False, None))
    if state is None:
        repo.insert_event(after)
        repo.log_change("event", event_id, "create", after.version, origin)
    else:
        repo.update_content(after)
        repo.log_change("event", event_id, "update", after.version, origin)
    if synced:
        repo.enqueue(event_id, after.calendar_id, account)
