"""Requêtes de la base des tâches sur une connexion SQLite (un `Repository` par fil : chargement à l'ouverture,
fil d'écriture, synchronisation).

Les tâches tiennent en mémoire (10 000 tâches ≈ 5 Mo) : le service les charge UNE fois à l'ouverture, ensuite la
base n'est plus qu'écrite. Les requêtes de lecture ici servent l'ouverture et la synchronisation."""
from __future__ import annotations

import json
import sqlite3
import time

from ..core.model import TaskList, TaskRecord, new_id

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


LIST_COLUMNS = ("id", "name", "color", "source", "account_id", "remote_id", "etag", "sync_enabled", "sort_order",
                "props", "deleted", "created_at", "updated_at")
TASK_COLUMNS = ("id", "list_id", "parent_id", "title", "notes", "position", "done", "completed_at", "due_date",
                "due_time", "reminder_at", "priority", "flagged", "url", "remote_id", "etag", "version",
                "created_at", "updated_at", "sync_state", "base", "origin", "deleted", "props")


def list_from_row(row: sqlite3.Row) -> TaskList:
    return TaskList(id=row["id"], name=row["name"], color=row["color"], source=row["source"],
                    account_id=row["account_id"], remote_id=row["remote_id"], etag=row["etag"],
                    sync_enabled=bool(row["sync_enabled"]), sort_order=row["sort_order"],
                    props=_loads(row["props"], {}), deleted=bool(row["deleted"]),
                    created_at=row["created_at"], updated_at=row["updated_at"])


def list_params(lst: TaskList) -> dict:
    return {"id": lst.id, "name": lst.name, "color": lst.color, "source": lst.source, "account_id": lst.account_id,
            "remote_id": lst.remote_id, "etag": lst.etag, "sync_enabled": int(lst.sync_enabled),
            "sort_order": lst.sort_order, "props": dumps(lst.props), "deleted": int(lst.deleted),
            "created_at": lst.created_at, "updated_at": lst.updated_at}


def task_from_row(row: sqlite3.Row) -> TaskRecord:
    return TaskRecord(id=row["id"], list_id=row["list_id"], parent_id=row["parent_id"], title=row["title"],
                      notes=row["notes"], position=row["position"], done=bool(row["done"]),
                      completed_at=row["completed_at"], due_date=row["due_date"], due_time=row["due_time"],
                      reminder_at=row["reminder_at"], priority=row["priority"], flagged=bool(row["flagged"]),
                      url=row["url"], remote_id=row["remote_id"], etag=row["etag"], version=row["version"],
                      created_at=row["created_at"], updated_at=row["updated_at"], sync_state=row["sync_state"],
                      base=_loads(row["base"], None), origin=row["origin"], deleted=bool(row["deleted"]),
                      props=_loads(row["props"], {}))


def task_params(t: TaskRecord) -> dict:
    return {"id": t.id, "list_id": t.list_id, "parent_id": t.parent_id, "title": t.title, "notes": t.notes,
            "position": float(t.position), "done": int(t.done), "completed_at": t.completed_at,
            "due_date": t.due_date, "due_time": t.due_time, "reminder_at": t.reminder_at,
            "priority": int(t.priority), "flagged": int(t.flagged), "url": t.url, "remote_id": t.remote_id,
            "etag": t.etag, "version": t.version, "created_at": t.created_at, "updated_at": t.updated_at,
            "sync_state": t.sync_state, "base": dumps(t.base) if t.base is not None else None,
            "origin": t.origin, "deleted": int(t.deleted), "props": dumps(t.props)}


def _upsert_sql(table: str, columns: tuple) -> str:
    """UPSERT et jamais INSERT OR REPLACE : REPLACE supprime la ligne avant de la réécrire, et la suppression d'une
    liste emporterait ses tâches (ON DELETE CASCADE)."""
    updates = ", ".join(f"{c} = excluded.{c}" for c in columns if c != "id")
    return (f"INSERT INTO {table} ({', '.join(columns)}) VALUES ({', '.join(':' + c for c in columns)}) "
            f"ON CONFLICT(id) DO UPDATE SET {updates}")


_INSERT_LIST = _upsert_sql("lists", LIST_COLUMNS)
_INSERT_TASK = _upsert_sql("tasks", TASK_COLUMNS)


class Repository:
    def __init__(self, conn: sqlite3.Connection):
        self.conn = conn

    # -- méta --

    def get_meta(self, key: str, default=None):
        row = self.conn.execute("SELECT value FROM meta WHERE key = ?", (key,)).fetchone()
        return _loads(row[0], default) if row else default

    def set_meta(self, key: str, value) -> None:
        self.conn.execute("INSERT OR REPLACE INTO meta (key, value) VALUES (?, ?)", (key, dumps(value)))

    def prefs(self) -> dict:
        return {r[0][5:]: _loads(r[1], None) for r in self.conn.execute(
            "SELECT key, value FROM meta WHERE key LIKE 'pref:%'")}

    def device_id(self) -> str:
        value = self.get_meta("device_id")
        if not value:
            value = new_id()
            self.set_meta("device_id", value)
        return value

    # -- listes --

    def all_lists(self, include_deleted: bool = False) -> list[TaskList]:
        sql = "SELECT * FROM lists" + ("" if include_deleted else " WHERE deleted = 0") + " ORDER BY sort_order, name"
        return [list_from_row(r) for r in self.conn.execute(sql)]

    def save_list(self, lst: TaskList) -> None:
        self.conn.execute(_INSERT_LIST, list_params(lst))

    def delete_list(self, list_id: str) -> None:
        self.conn.execute("DELETE FROM lists WHERE id = ?", (list_id,))
        self.conn.execute("DELETE FROM sync_outbox WHERE list_id = ?", (list_id,))

    # -- tâches --

    def all_tasks(self) -> list[TaskRecord]:
        """Tâches vivantes (chargement à l'ouverture)."""
        return [task_from_row(r) for r in self.conn.execute("SELECT * FROM tasks WHERE deleted = 0")]

    def get_task(self, task_id: str, include_deleted: bool = True) -> TaskRecord | None:
        sql = "SELECT * FROM tasks WHERE id = ?" + ("" if include_deleted else " AND deleted = 0")
        row = self.conn.execute(sql, (task_id,)).fetchone()
        return task_from_row(row) if row else None

    def remote_of(self, task_id: str) -> tuple | None:
        """(remote_id,) si la ligne existe en base, sinon None."""
        row = self.conn.execute("SELECT remote_id FROM tasks WHERE id = ?", (task_id,)).fetchone()
        return (row[0],) if row else None

    def save_task(self, t: TaskRecord) -> None:
        self.conn.execute(_INSERT_TASK, task_params(t))

    def delete_task(self, task_id: str) -> None:
        self.conn.execute("DELETE FROM tasks WHERE id = ?", (task_id,))
        self.conn.execute("DELETE FROM sync_outbox WHERE entity = 'task' AND entity_id = ?", (task_id,))

    def mark_deleted(self, task_id: str, version: int, origin: str) -> None:
        self.conn.execute("UPDATE tasks SET deleted = 1, sync_state = 'deleted', version = ?, updated_at = ?, "
                          "origin = ? WHERE id = ?", (version, now_ts(), origin, task_id))

    def count_tasks(self) -> int:
        return self.conn.execute("SELECT COUNT(*) FROM tasks WHERE deleted = 0").fetchone()[0]

    def tasks_in_list(self, list_id: str) -> list[TaskRecord]:
        return [task_from_row(r) for r in self.conn.execute(
            "SELECT * FROM tasks WHERE list_id = ? AND deleted = 0", (list_id,))]

    # -- comptes (aucun jeton ici) --

    def all_accounts(self) -> list[dict]:
        out = []
        for r in self.conn.execute("SELECT * FROM accounts ORDER BY created_at"):
            row = dict(r)
            row["settings"] = _loads(row.get("settings"), {})
            out.append(row)
        return out

    def save_account(self, account: dict) -> None:
        cols = ("id", "provider", "email", "display_name", "status", "last_error", "last_sync_at", "settings",
                "created_at")
        params = {c: account.get(c) for c in cols}
        params["settings"] = dumps(account.get("settings") or {})
        for c, default in (("email", ""), ("display_name", ""), ("status", "connected"), ("last_error", ""),
                           ("last_sync_at", 0), ("created_at", now_ts())):
            if params[c] is None:
                params[c] = default
        updates = ", ".join(f"{c} = excluded.{c}" for c in cols if c != "id")
        self.conn.execute(f"INSERT INTO accounts ({', '.join(cols)}) VALUES ({', '.join(':' + c for c in cols)}) "
                          f"ON CONFLICT(id) DO UPDATE SET {updates}", params)

    def delete_account(self, account_id: str) -> None:
        self.conn.execute("DELETE FROM accounts WHERE id = ?", (account_id,))

    # -- file d'envoi, journal --

    def enqueue(self, entity: str, entity_id: str, list_id: str, account_id: str | None) -> None:
        self.conn.execute(
            "INSERT INTO sync_outbox (entity, entity_id, list_id, account_id, created_at) VALUES (?, ?, ?, ?, ?) "
            "ON CONFLICT(entity, entity_id) DO UPDATE SET list_id = excluded.list_id, attempts = 0, next_at = 0, "
            "last_error = ''", (entity, entity_id, list_id, account_id, now_ts()))

    def dequeue(self, entity: str, entity_id: str) -> None:
        self.conn.execute("DELETE FROM sync_outbox WHERE entity = ? AND entity_id = ?", (entity, entity_id))

    def outbox_failed(self, entity: str, entity_id: str, error: str, now: int) -> None:
        """Échec d'envoi (autre que réseau) : nouvel essai de plus en plus tard (30 s -> 1 h)."""
        self.conn.execute("UPDATE sync_outbox SET attempts = attempts + 1, last_error = ?, "
                          "next_at = ? + MIN(3600, 30 * (1 << MIN(attempts, 7))) WHERE entity = ? AND entity_id = ?",
                          (error[:300], now, entity, entity_id))

    def outbox_count(self) -> int:
        return self.conn.execute("SELECT COUNT(*) FROM sync_outbox").fetchone()[0]

    def outbox(self) -> list[dict]:
        return [dict(r) for r in self.conn.execute("SELECT * FROM sync_outbox ORDER BY created_at")]

    def log_change(self, entity: str, entity_id: str, op: str, version: int, origin: str) -> None:
        self.conn.execute("INSERT INTO changes (entity, entity_id, op, version, origin, at) VALUES (?, ?, ?, ?, ?, ?)",
                          (entity, entity_id, op, version, origin, now_ts()))

    # -- rappels --

    def reminder_fired(self, task_id: str, reminder_at: int) -> bool:
        return self.conn.execute("SELECT 1 FROM reminder_log WHERE task_id = ? AND reminder_at = ?",
                                 (task_id, reminder_at)).fetchone() is not None

    def mark_reminder(self, task_id: str, reminder_at: int) -> None:
        self.conn.execute("INSERT OR IGNORE INTO reminder_log (task_id, reminder_at, fired_at) VALUES (?, ?, ?)",
                          (task_id, reminder_at, now_ts()))
