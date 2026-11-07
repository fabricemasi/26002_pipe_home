"""Requêtes de l'agenda sur une connexion SQLite (un `Repository` par fil : lecture dans le fil de l'interface,
écriture dans le fil d'écriture, synchronisation dans le sien).

Fenêtre d'affichage : un événement simple est retenu si `start_ts < fin` ET `end_ts > début`. Pour que l'index sur
`start_ts` serve (et qu'afficher une semaine ne parcoure pas des années d'historique), le début est AUSSI borné par
`début - durée maximale connue` (`RangeHints.max_duration`, partagé par les dépôts des différents fils)."""
from __future__ import annotations

import json
import sqlite3
import time
from datetime import date, datetime

from ..core import recurrence as rec
from ..core import timeutil as tu
from ..core.model import Attendee, Calendar, EventRecord

_DUMP = {"ensure_ascii": False, "separators": (",", ":")}


def dumps(value) -> str:
    return json.dumps(value, **_DUMP)


def _loads(text, default):
    if not text:
        return default
    try:
        return json.loads(text)
    except ValueError:
        return default


def now_ts() -> int:
    return int(time.time())


class RangeHints:
    """Durée maximale d'un événement simple (secondes), partagée entre fils (affectation atomique)."""

    def __init__(self):
        self.max_duration = 86400 * 2

    def grow(self, duration: int) -> None:
        if duration > self.max_duration:
            self.max_duration = duration


EVENT_COLUMNS = ("id", "calendar_id", "series_id", "recurrence_id", "title", "description", "location", "url", "notes",
                 "all_day", "start_ts", "end_ts", "tzid", "start_date", "end_date", "rrule", "exdates", "until_ts",
                 "color", "categories", "transparency", "status", "is_task", "done", "project", "folder",
                 "attendees", "reminders", "reminders_default", "ical_uid", "remote_id", "etag", "sequence",
                 "version", "created_at", "updated_at", "sync_state", "base", "origin", "deleted", "extra")
CONTENT_COLUMNS = ("calendar_id", "title", "description", "location", "url", "notes", "all_day", "start_ts",
                   "end_ts", "tzid", "start_date", "end_date", "rrule", "exdates", "until_ts", "color", "categories",
                   "transparency", "status", "is_task", "done", "project", "folder", "attendees", "reminders",
                   "reminders_default", "series_id", "recurrence_id")


def event_from_row(row: sqlite3.Row) -> EventRecord:
    all_day = bool(row["all_day"])
    tzid = row["tzid"] or ""
    ev = EventRecord(id=row["id"], calendar_id=row["calendar_id"])
    ev.series_id = row["series_id"]
    ev.recurrence_id = row["recurrence_id"]
    ev.title = row["title"]
    ev.description = row["description"]
    ev.location = row["location"]
    ev.url = row["url"]
    ev.notes = row["notes"]
    ev.all_day = all_day
    ev.tzid = tzid
    if all_day:
        ev.start_date = date.fromisoformat(row["start_date"]) if row["start_date"] else tu.ord_ts_to_date(
            row["start_ts"])
        ev.end_date = date.fromisoformat(row["end_date"]) if row["end_date"] else tu.ord_ts_to_date(row["end_ts"])
    else:
        tz = tu.get_tz(tzid)
        ev.start = tu.from_ts(row["start_ts"], tz)
        ev.end = tu.from_ts(row["end_ts"], tz)
    ev.rrule = row["rrule"]
    ev.exdates = list(_loads(row["exdates"], []))
    ev.color = row["color"]
    ev.categories = list(_loads(row["categories"], []))
    ev.transparency = row["transparency"]
    ev.status = row["status"]
    ev.is_task = bool(row["is_task"])
    ev.done = bool(row["done"])
    ev.project = row["project"]
    ev.folder = row["folder"]
    ev.attendees = [Attendee.from_dict(d) for d in _loads(row["attendees"], [])]
    ev.reminders = [int(m) for m in _loads(row["reminders"], [])]
    ev.reminders_default = bool(row["reminders_default"])
    ev.ical_uid = row["ical_uid"]
    ev.remote_id = row["remote_id"]
    ev.etag = row["etag"]
    ev.sequence = row["sequence"]
    ev.version = row["version"]
    ev.created_at = row["created_at"]
    ev.updated_at = row["updated_at"]
    ev.sync_state = row["sync_state"]
    ev.origin = row["origin"]
    ev.deleted = bool(row["deleted"])
    ev.extra = dict(_loads(row["extra"], {}))
    return ev


def until_ts_of(ev: EventRecord) -> int | None:
    if not ev.rrule or ev.series_id:
        return None
    try:
        start = ev.start_date if ev.all_day else ev.start
        return rec.last_end_ts(ev.rrule, start, ev.tzid, ev.all_day, ev.duration)
    except (ValueError, TypeError):
        return None


def event_params(ev: EventRecord) -> dict:
    return {
        "id": ev.id, "calendar_id": ev.calendar_id, "series_id": ev.series_id, "recurrence_id": ev.recurrence_id,
        "title": ev.title, "description": ev.description, "location": ev.location, "url": ev.url,
        "notes": ev.notes, "all_day": int(ev.all_day), "start_ts": ev.start_ts, "end_ts": ev.end_ts,
        "tzid": ev.tzid or "", "start_date": ev.start_date.isoformat() if ev.all_day else None,
        "end_date": ev.end_date.isoformat() if ev.all_day else None, "rrule": ev.rrule or None,
        "exdates": dumps(sorted(set(ev.exdates))), "until_ts": until_ts_of(ev), "color": ev.color,
        "categories": dumps(ev.categories), "transparency": ev.transparency, "status": ev.status,
        "is_task": int(ev.is_task), "done": int(ev.done), "project": ev.project, "folder": ev.folder,
        "attendees": dumps([a.to_dict() for a in ev.attendees]), "reminders": dumps(sorted(set(ev.reminders))),
        "reminders_default": int(ev.reminders_default), "ical_uid": ev.ical_uid, "remote_id": ev.remote_id,
        "etag": ev.etag, "sequence": ev.sequence, "version": ev.version, "created_at": ev.created_at,
        "updated_at": ev.updated_at, "sync_state": ev.sync_state,
        "base": None, "origin": ev.origin, "deleted": int(ev.deleted), "extra": dumps(ev.extra),
    }


def calendar_from_row(row: sqlite3.Row) -> Calendar:
    return Calendar(id=row["id"], name=row["name"], color=row["color"], visible=bool(row["visible"]),
                    source=row["source"], account_id=row["account_id"], remote_id=row["remote_id"],
                    access_role=row["access_role"], sync_enabled=bool(row["sync_enabled"]),
                    description=row["description"], timezone=row["timezone"], sort_order=row["sort_order"],
                    props=dict(_loads(row["props"], {})), deleted=bool(row["deleted"]))


class Repository:
    def __init__(self, conn: sqlite3.Connection, hints: RangeHints | None = None):
        self.conn = conn
        self.hints = hints or RangeHints()

    # -- méta / préférences --

    def get_meta(self, key: str, default=None):
        row = self.conn.execute("SELECT value FROM meta WHERE key = ?", (key,)).fetchone()
        return _loads(row[0], default) if row else default

    def set_meta(self, key: str, value) -> None:
        self.conn.execute("INSERT INTO meta(key, value) VALUES(?, ?) ON CONFLICT(key) DO UPDATE SET value = "
                          "excluded.value", (key, dumps(value)))

    def device_id(self) -> str:
        value = self.get_meta("device_id")
        if not value:
            from ..core.model import new_id
            value = new_id()
            self.set_meta("device_id", value)
        return value

    def refresh_hints(self) -> None:
        row = self.conn.execute("SELECT MAX(end_ts - start_ts) FROM events WHERE deleted = 0 AND rrule IS NULL "
                                "AND series_id IS NULL").fetchone()
        self.hints.max_duration = max(86400 * 2, int(row[0] or 0))

    # -- comptes --

    def list_accounts(self) -> list[dict]:
        return [dict(r) for r in self.conn.execute("SELECT * FROM accounts ORDER BY created_at")]

    def get_account(self, account_id: str) -> dict | None:
        row = self.conn.execute("SELECT * FROM accounts WHERE id = ?", (account_id,)).fetchone()
        return dict(row) if row else None

    def upsert_account(self, account: dict) -> None:
        cols = ("id", "provider", "email", "display_name", "status", "last_error", "last_sync_at", "settings",
                "created_at")
        values = [account.get(c, "" if c not in ("last_sync_at", "created_at") else 0) for c in cols]
        if isinstance(values[7], dict):
            values[7] = dumps(values[7])
        self.conn.execute(
            f"INSERT INTO accounts({', '.join(cols)}) VALUES({', '.join('?' * len(cols))}) ON CONFLICT(id) DO UPDATE "
            f"SET {', '.join(f'{c} = excluded.{c}' for c in cols[1:])}", values)

    def update_account(self, account_id: str, **fields) -> None:
        if not fields:
            return
        self.conn.execute(f"UPDATE accounts SET {', '.join(f'{k} = ?' for k in fields)} WHERE id = ?",
                          [*fields.values(), account_id])

    def delete_account(self, account_id: str) -> None:
        self.conn.execute("DELETE FROM accounts WHERE id = ?", (account_id,))

    # -- calendriers --

    def list_calendars(self, include_deleted: bool = False) -> list[Calendar]:
        sql = "SELECT * FROM calendars" + ("" if include_deleted else " WHERE deleted = 0") + \
              " ORDER BY sort_order, name"
        return [calendar_from_row(r) for r in self.conn.execute(sql)]

    def get_calendar(self, cal_id: str) -> Calendar | None:
        row = self.conn.execute("SELECT * FROM calendars WHERE id = ?", (cal_id,)).fetchone()
        return calendar_from_row(row) if row else None

    def calendar_by_remote(self, account_id: str, remote_id: str) -> Calendar | None:
        row = self.conn.execute("SELECT * FROM calendars WHERE account_id = ? AND remote_id = ?",
                                (account_id, remote_id)).fetchone()
        return calendar_from_row(row) if row else None

    def upsert_calendar(self, cal: Calendar) -> None:
        now = now_ts()
        self.conn.execute(
            "INSERT INTO calendars(id, name, color, visible, source, account_id, remote_id, access_role, "
            "sync_enabled, description, timezone, sort_order, props, deleted, created_at, updated_at) "
            "VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?) ON CONFLICT(id) DO UPDATE SET name = excluded.name, "
            "color = excluded.color, visible = excluded.visible, source = excluded.source, "
            "account_id = excluded.account_id, remote_id = excluded.remote_id, access_role = excluded.access_role, "
            "sync_enabled = excluded.sync_enabled, description = excluded.description, timezone = excluded.timezone, "
            "sort_order = excluded.sort_order, props = excluded.props, deleted = excluded.deleted, "
            "updated_at = excluded.updated_at",
            (cal.id, cal.name, cal.color, int(cal.visible), cal.source, cal.account_id, cal.remote_id,
             cal.access_role, int(cal.sync_enabled), cal.description, cal.timezone, cal.sort_order,
             dumps(cal.props), int(cal.deleted), now, now))

    def delete_calendar(self, cal_id: str) -> None:
        self.conn.execute("DELETE FROM sync_outbox WHERE calendar_id = ?", (cal_id,))
        self.conn.execute("DELETE FROM calendars WHERE id = ?", (cal_id,))

    def sync_token(self, cal_id: str) -> str | None:
        row = self.conn.execute("SELECT sync_token FROM calendars WHERE id = ?", (cal_id,)).fetchone()
        return row[0] if row else None

    def set_sync_token(self, cal_id: str, token: str | None) -> None:
        self.conn.execute("UPDATE calendars SET sync_token = ? WHERE id = ?", (token, cal_id))

    # -- événements : lecture --

    def get_event(self, event_id: str, include_deleted: bool = True) -> EventRecord | None:
        row = self.conn.execute("SELECT * FROM events WHERE id = ?", (event_id,)).fetchone()
        if row is None or (row["deleted"] and not include_deleted):
            return None
        return event_from_row(row)

    def get_base(self, event_id: str) -> dict | None:
        row = self.conn.execute("SELECT base FROM events WHERE id = ?", (event_id,)).fetchone()
        return _loads(row[0], None) if row and row[0] else None

    def event_by_remote(self, cal_id: str, remote_id: str) -> EventRecord | None:
        row = self.conn.execute("SELECT * FROM events WHERE calendar_id = ? AND remote_id = ?",
                                (cal_id, remote_id)).fetchone()
        return event_from_row(row) if row else None

    def event_by_uid(self, cal_id: str, uid: str, recurrence_id: str | None) -> EventRecord | None:
        if recurrence_id is None:
            row = self.conn.execute("SELECT * FROM events WHERE calendar_id = ? AND ical_uid = ? AND series_id IS NULL "
                                    "AND deleted = 0", (cal_id, uid)).fetchone()
        else:
            row = self.conn.execute("SELECT * FROM events WHERE calendar_id = ? AND ical_uid = ? AND recurrence_id = ? "
                                    "AND deleted = 0", (cal_id, uid, recurrence_id)).fetchone()
        return event_from_row(row) if row else None

    def overrides_of(self, series_id: str, include_deleted: bool = False) -> list[EventRecord]:
        sql = "SELECT * FROM events WHERE series_id = ?" + ("" if include_deleted else " AND deleted = 0")
        return [event_from_row(r) for r in self.conn.execute(sql, (series_id,))]

    def window_rows(self, start_ts: int, end_ts: int) -> list[EventRecord]:
        """Lignes nécessaires pour afficher [start_ts, end_ts[ : événements simples qui chevauchent, maîtres de
        séries actifs, toutes leurs exceptions, et les exceptions déplacées dans la fenêtre."""
        lo = start_ts - self.hints.max_duration
        rows = list(self.conn.execute(
            "SELECT * FROM events WHERE deleted = 0 AND rrule IS NULL AND series_id IS NULL AND start_ts >= ? "
            "AND start_ts < ? AND end_ts > ?", (lo, end_ts, start_ts)))
        masters = list(self.conn.execute(
            "SELECT * FROM events WHERE deleted = 0 AND rrule IS NOT NULL AND series_id IS NULL AND start_ts < ? "
            "AND (until_ts IS NULL OR until_ts > ?)", (end_ts, start_ts)))
        seen = {r["id"] for r in rows}
        out = [event_from_row(r) for r in rows]
        master_ids = []
        for r in masters:
            if r["id"] not in seen:
                seen.add(r["id"])
                out.append(event_from_row(r))
                master_ids.append(r["id"])
        for chunk in range(0, len(master_ids), 400):
            ids = master_ids[chunk:chunk + 400]
            for r in self.conn.execute(f"SELECT * FROM events WHERE deleted = 0 AND series_id IN "
                                       f"({','.join('?' * len(ids))})", ids):
                if r["id"] not in seen:
                    seen.add(r["id"])
                    out.append(event_from_row(r))
        lo_o = start_ts - max(self.hints.max_duration, 86400 * 7)
        for r in self.conn.execute(
                "SELECT * FROM events WHERE series_id IS NOT NULL AND deleted = 0 AND start_ts >= ? AND start_ts < ? "
                "AND end_ts > ?", (lo_o, end_ts, start_ts)):
            if r["id"] not in seen:
                seen.add(r["id"])
                out.append(event_from_row(r))
        return out

    def window_counts_rows(self, start_ts: int, end_ts: int) -> list[tuple]:
        """Version légère pour la vue Année : (start_ts, end_ts, all_day, start_date, end_date, calendar_id) des
        événements simples ; les séries passent par `window_rows`."""
        lo = start_ts - self.hints.max_duration
        return [tuple(r) for r in self.conn.execute(
            "SELECT start_ts, end_ts, all_day, start_date, end_date, calendar_id, status FROM events WHERE deleted = 0 "
            "AND rrule IS NULL AND series_id IS NULL AND start_ts >= ? AND start_ts < ? AND end_ts > ?",
            (lo, end_ts, start_ts))]

    def masters_in(self, start_ts: int, end_ts: int) -> list[EventRecord]:
        rows = self.conn.execute(
            "SELECT * FROM events WHERE deleted = 0 AND rrule IS NOT NULL AND series_id IS NULL AND start_ts < ? "
            "AND (until_ts IS NULL OR until_ts > ?)", (end_ts, start_ts))
        return [event_from_row(r) for r in rows]

    def search(self, text: str, limit: int = 200) -> list[EventRecord]:
        words = [w for w in text.lower().split() if w]
        if not words:
            return []
        clauses, params = [], []
        for w in words:
            like = "%" + w.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%"
            clauses.append("(lower(title) LIKE ? ESCAPE '\\' OR lower(location) LIKE ? ESCAPE '\\' OR "
                           "lower(description) LIKE ? ESCAPE '\\' OR lower(notes) LIKE ? ESCAPE '\\' OR "
                           "lower(project) LIKE ? ESCAPE '\\' OR lower(categories) LIKE ? ESCAPE '\\')")
            params.extend([like] * 6)
        sql = (f"SELECT * FROM events WHERE deleted = 0 AND status != 'cancelled' AND {' AND '.join(clauses)} "
               f"ORDER BY start_ts DESC LIMIT ?")
        return [event_from_row(r) for r in self.conn.execute(sql, (*params, limit))]

    def count_events(self) -> int:
        return self.conn.execute("SELECT COUNT(*) FROM events WHERE deleted = 0").fetchone()[0]

    def with_reminders(self, start_ts: int, end_ts: int) -> list[EventRecord]:
        lo = start_ts - self.hints.max_duration
        rows = list(self.conn.execute(
            "SELECT * FROM events WHERE deleted = 0 AND (reminders != '[]' OR reminders_default = 1) AND "
            "((rrule IS NULL AND start_ts >= ? AND start_ts < ?) OR (rrule IS NOT NULL AND start_ts < ? AND "
            "(until_ts IS NULL OR until_ts > ?)))", (lo, end_ts, end_ts, start_ts)))
        return [event_from_row(r) for r in rows]

    def events_of_calendar(self, cal_id: str, include_deleted: bool = False) -> list[EventRecord]:
        sql = "SELECT * FROM events WHERE calendar_id = ?" + ("" if include_deleted else " AND deleted = 0")
        return [event_from_row(r) for r in self.conn.execute(sql, (cal_id,))]

    def pending_events(self, cal_id: str) -> list[EventRecord]:
        rows = self.conn.execute("SELECT * FROM events WHERE calendar_id = ? AND sync_state IN ('dirty', 'deleted')",
                                 (cal_id,))
        return [event_from_row(r) for r in rows]

    # -- événements : écriture --

    def insert_event(self, ev: EventRecord) -> None:
        params = event_params(ev)
        self.conn.execute(f"INSERT INTO events({', '.join(EVENT_COLUMNS)}) VALUES("
                          f"{', '.join(':' + c for c in EVENT_COLUMNS)})", params)
        if not ev.rrule and not ev.series_id:
            self.hints.grow(params["end_ts"] - params["start_ts"])

    def replace_event(self, ev: EventRecord, base: dict | None = None, keep_base: bool = True) -> None:
        """Ligne entière (restauration d'annuler, synchronisation). `keep_base` : garde la base de fusion en place."""
        params = event_params(ev)
        if not keep_base:
            params["base"] = dumps(base) if base is not None else None
        else:
            row = self.conn.execute("SELECT base FROM events WHERE id = ?", (ev.id,)).fetchone()
            params["base"] = row[0] if row else (dumps(base) if base is not None else None)
        self.conn.execute(f"INSERT INTO events({', '.join(EVENT_COLUMNS)}) VALUES("
                          f"{', '.join(':' + c for c in EVENT_COLUMNS)}) ON CONFLICT(id) DO UPDATE SET "
                          f"{', '.join(f'{c} = excluded.{c}' for c in EVENT_COLUMNS[1:])}", params)
        if not ev.rrule and not ev.series_id:
            self.hints.grow(params["end_ts"] - params["start_ts"])

    def update_content(self, ev: EventRecord) -> None:
        """Contenu modifié par l'utilisateur : les colonnes de SYNCHRONISATION (remote_id, etag, base) restent celles
        de la base (le fil de synchronisation a pu les mettre à jour entre-temps)."""
        params = event_params(ev)
        cols = CONTENT_COLUMNS + ("version", "updated_at", "sync_state", "origin", "deleted", "extra")
        self.conn.execute(f"UPDATE events SET {', '.join(f'{c} = :{c}' for c in cols)} WHERE id = :id", params)
        if not ev.rrule and not ev.series_id:
            self.hints.grow(params["end_ts"] - params["start_ts"])

    def set_sync_fields(self, event_id: str, **fields) -> None:
        if "base" in fields and not isinstance(fields["base"], (str, type(None))):
            fields["base"] = dumps(fields["base"])
        self.conn.execute(f"UPDATE events SET {', '.join(f'{k} = ?' for k in fields)} WHERE id = ?",
                          [*fields.values(), event_id])

    def delete_event(self, event_id: str) -> None:
        self.conn.execute("DELETE FROM sync_outbox WHERE event_id = ?", (event_id,))
        self.conn.execute("DELETE FROM events WHERE id = ?", (event_id,))

    def sync_state_of(self, event_id: str) -> tuple[str, str | None] | None:
        row = self.conn.execute("SELECT sync_state, remote_id FROM events WHERE id = ?", (event_id,)).fetchone()
        return (row[0], row[1]) if row else None

    # -- file d'envoi --

    def enqueue(self, event_id: str, calendar_id: str, account_id: str | None) -> None:
        self.conn.execute(
            "INSERT INTO sync_outbox(event_id, calendar_id, account_id, created_at, attempts, next_at, last_error) "
            "VALUES(?, ?, ?, ?, 0, 0, '') ON CONFLICT(event_id) DO UPDATE SET calendar_id = excluded.calendar_id, "
            "account_id = excluded.account_id, attempts = 0, next_at = 0, last_error = ''",
            (event_id, calendar_id, account_id, now_ts()))

    def outbox(self, account_id: str | None = None, due_before: int | None = None) -> list[dict]:
        sql, params = "SELECT * FROM sync_outbox WHERE 1 = 1", []
        if account_id is not None:
            sql += " AND account_id = ?"
            params.append(account_id)
        if due_before is not None:
            sql += " AND next_at <= ?"
            params.append(due_before)
        return [dict(r) for r in self.conn.execute(sql + " ORDER BY created_at", params)]

    def outbox_count(self) -> int:
        return self.conn.execute("SELECT COUNT(*) FROM sync_outbox").fetchone()[0]

    def outbox_done(self, event_id: str) -> None:
        self.conn.execute("DELETE FROM sync_outbox WHERE event_id = ?", (event_id,))

    def outbox_failed(self, event_id: str, error: str, next_at: int) -> None:
        self.conn.execute("UPDATE sync_outbox SET attempts = attempts + 1, next_at = ?, last_error = ? "
                          "WHERE event_id = ?", (next_at, error[:500], event_id))

    # -- conflits --

    def add_conflict(self, event_id: str, cal_id: str, local: dict, remote: dict, base: dict | None,
                     fields: list[str]) -> int:
        self.conn.execute("UPDATE conflicts SET resolved = 1, resolution = 'remplacé' WHERE event_id = ? AND "
                          "resolved = 0", (event_id,))
        cur = self.conn.execute("INSERT INTO conflicts(event_id, calendar_id, detected_at, local, remote, base, "
                                "fields) VALUES(?, ?, ?, ?, ?, ?, ?)",
                                (event_id, cal_id, now_ts(), dumps(local), dumps(remote),
                                 dumps(base) if base is not None else None, dumps(fields)))
        return cur.lastrowid

    def open_conflicts(self) -> list[dict]:
        out = []
        for r in self.conn.execute("SELECT * FROM conflicts WHERE resolved = 0 ORDER BY detected_at"):
            d = dict(r)
            d["local"] = _loads(d["local"], {})
            d["remote"] = _loads(d["remote"], {})
            d["base"] = _loads(d["base"], None)
            d["fields"] = _loads(d["fields"], [])
            out.append(d)
        return out

    def resolve_conflict(self, conflict_id: int, resolution: str) -> None:
        self.conn.execute("UPDATE conflicts SET resolved = 1, resolution = ? WHERE id = ?", (resolution, conflict_id))

    # -- journal des modifications (provenance) --

    def log_change(self, entity: str, entity_id: str, op: str, version: int, origin: str) -> None:
        self.conn.execute("INSERT INTO changes(entity, entity_id, op, version, origin, at) VALUES(?, ?, ?, ?, ?, ?)",
                          (entity, entity_id, op, version, origin, now_ts()))

    def changes_since(self, seq: int, exclude_origin_prefix: str | None = None, limit: int = 500) -> list[dict]:
        sql, params = "SELECT * FROM changes WHERE seq > ?", [seq]
        if exclude_origin_prefix:
            sql += " AND origin NOT LIKE ?"
            params.append(exclude_origin_prefix + "%")
        return [dict(r) for r in self.conn.execute(sql + " ORDER BY seq LIMIT ?", (*params, limit))]

    # -- rappels montrés --

    def reminder_fired(self, occurrence: str, minutes: int) -> bool:
        return self.conn.execute("SELECT 1 FROM reminder_log WHERE occurrence = ? AND minutes = ?",
                                 (occurrence, minutes)).fetchone() is not None

    def mark_reminder(self, occurrence: str, minutes: int) -> None:
        self.conn.execute("INSERT OR IGNORE INTO reminder_log(occurrence, minutes, fired_at) VALUES(?, ?, ?)",
                          (occurrence, minutes, now_ts()))

    def prune_reminders(self, older_than: int) -> None:
        self.conn.execute("DELETE FROM reminder_log WHERE fired_at < ?", (older_than,))


def stamp(ev: EventRecord, origin: str, synced: bool) -> EventRecord:
    """Horodatage, version et état de synchronisation d'une modification LOCALE."""
    ev.updated_at = now_ts()
    if not ev.created_at:
        ev.created_at = ev.updated_at
    ev.version = (ev.version or 0) + 1
    ev.origin = origin
    if synced:
        ev.sync_state = "deleted" if ev.deleted else "dirty"
    else:
        ev.sync_state = "local"
    return ev


def instant(dt: datetime | date) -> int:
    return tu.to_ts(dt) if isinstance(dt, datetime) else tu.date_to_ord_ts(dt)
