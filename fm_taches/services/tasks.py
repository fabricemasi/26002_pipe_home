"""Service des tâches : SEULE porte d'entrée de l'interface (qui ne connaît ni SQLite ni Google).

Mémoire = référence : toutes les tâches vivantes sont chargées à l'ouverture (10 000 ≈ 5 Mo, une requête) et
indexées par liste et par échéance. Une modification est appliquée en mémoire (signal `changed` avec les listes
touchées, la vue la montre aussitôt) puis écrite par le fil d'écriture de l'agenda (`DbWriter`, une transaction par
commande). Un échec d'écriture recharge la base et le signale.

Chaque modification est une COMMANDE annulable : [(genre « task » / « list », id, avant, après)]. Annuler rejoue
l'état d'origine sur l'état COURANT (la synchronisation a pu passer entre-temps)."""
from __future__ import annotations

import logging
import time
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from pathlib import Path

from PySide6.QtCore import QObject, QTimer, Signal

from fm_agenda.services.writer import DbWriter

from ..core import ordering, smart
from ..core.model import TaskList, TaskRecord, new_id
from ..store import database as db
from ..store.repository import Repository, now_ts

log = logging.getLogger("fm_taches.service")

DEFAULT_LIST = ("Mes tâches", "bleu")
TASK_FIELDS = {"title", "notes", "due_date", "due_time", "reminder_at", "priority", "flagged", "url", "props"}
LIST_FIELDS = {"name", "color", "sort_order", "props"}
_KEEP = object()                                     # « parent inchangé » pour `move`


@dataclass
class Command:
    label: str
    changes: list = field(default_factory=list)      # [(genre, id, avant | None, après | None)]


class TaskService(QObject):
    changed = Signal(object)            # ensemble des listes touchées (tâches)
    listsChanged = Signal()
    undoChanged = Signal()
    message = Signal(str, str)          # (« info » / « erreur », texte)

    def __init__(self, settings: dict | None = None, parent=None, path: Path | None = None):
        super().__init__(parent)
        self.settings = dict(settings or {})
        if path is None:
            path = db.resolve_data_dir(self.settings.get("taches_data_dir")) / db.DB_NAME
        self.path = Path(path)
        conn, self.open_report = db.open_database(self.path)
        repo = Repository(conn)
        self.device_id = repo.device_id()
        self.origin = f"device:{self.device_id}"
        if not repo.all_lists(include_deleted=True):
            with db.transaction(conn):
                repo.save_list(TaskList(id=new_id(), name=DEFAULT_LIST[0], color=DEFAULT_LIST[1],
                                        created_at=now_ts(), updated_at=now_ts()))
        self._prefs = repo.prefs()
        self._load(repo)
        self.writer = DbWriter(conn, repo=repo, name="fm_taches-ecriture")
        self._undo: list[Command] = []
        self._redo: list[Command] = []
        self._closed = False
        self.sync = None                                 # pilote de synchronisation (phase 3)
        for text in self.open_report.messages:
            log.warning(text)
        self._backup_timer = QTimer(self)
        self._backup_timer.setSingleShot(True)
        self._backup_timer.timeout.connect(self._daily_backup)
        self._backup_timer.start(4000)

    # -- mémoire et index --

    def _load(self, repo: Repository) -> None:
        self._accounts: dict[str, dict] = {a["id"]: a for a in repo.all_accounts()}
        self._lists: dict[str, TaskList] = {lst.id: lst for lst in repo.all_lists()}
        self._tasks: dict[str, TaskRecord] = {}
        self._by_list: dict[str, set] = defaultdict(set)
        self._by_due: dict[str, set] = defaultdict(set)
        self._by_reminder: set = set()                   # tâches à rappel explicite (`reminder_at`)
        self._fired: set = {(r[0], r[1]) for r in repo.conn.execute(
            "SELECT task_id, reminder_at FROM reminder_log WHERE fired_at > ?", (now_ts() - 8 * 86400,))}
        for t in repo.all_tasks():
            if t.list_id in self._lists:
                self._index(t)
        self._flat: dict[tuple, list] = {}
        self._smart: dict[tuple, list] = {}
        self._counts: dict[str, int] | None = None

    def _index(self, t: TaskRecord) -> None:
        self._tasks[t.id] = t
        self._by_list[t.list_id].add(t.id)
        if t.due_date:
            self._by_due[t.due_date].add(t.id)
        if t.reminder_at:
            self._by_reminder.add(t.id)

    def _unindex(self, t: TaskRecord) -> None:
        self._tasks.pop(t.id, None)
        self._by_list[t.list_id].discard(t.id)
        self._by_reminder.discard(t.id)
        if t.due_date:
            ids = self._by_due.get(t.due_date)
            if ids is not None:
                ids.discard(t.id)
                if not ids:
                    del self._by_due[t.due_date]

    def _put(self, kind: str, item_id: str, after) -> None:
        if kind == "list":
            if after is None:
                self._lists.pop(item_id, None)
            else:
                self._lists[item_id] = after
            return
        current = self._tasks.get(item_id)
        if current is not None:
            self._unindex(current)
        if after is not None:
            self._index(after)

    def _invalidate(self, list_ids) -> None:
        if list_ids is None:
            self._flat.clear()
        else:
            for key in [k for k in self._flat if k[0] in list_ids]:
                del self._flat[key]
        self._smart.clear()
        self._counts = None

    # -- fermeture, préférences --

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
        db.close_database(self.writer.repo.conn, self.path)

    def flush(self, timeout: float = 10.0) -> bool:
        """Attend les écritures en cours (tests, sauvegarde). Les rappels Qt restent à délivrer."""
        return self.writer.flush(timeout)

    def apply_settings(self, settings: dict) -> None:
        self.settings.update(settings or {})

    def pref(self, key: str, default=None):
        return self._prefs.get(key, default)

    def set_pref(self, key: str, value) -> None:
        if self._prefs.get(key) == value:
            return
        self._prefs[key] = value
        self.writer.submit(lambda repo: repo.set_meta("pref:" + key, value))

    # -- lecture : listes --

    def lists(self) -> list[TaskList]:
        return sorted(self._lists.values(), key=lambda lst: (lst.sort_order, lst.name.casefold(), lst.id))

    def get_list(self, list_id: str | None) -> TaskList | None:
        return self._lists.get(list_id) if list_id else None

    def default_list(self) -> TaskList | None:
        wanted = self.settings.get("taches_default_list") or self.pref("default_list")
        return self._lists.get(wanted) or next(iter(self.lists()), None)

    def max_depth(self, list_id: str) -> int | None:
        """Profondeur maximale des sous-tâches : 1 pour Google Tasks et Apple Rappels (un seul niveau), illimitée
        pour une liste locale."""
        lst = self._lists.get(list_id)
        return None if lst is None or lst.source == "local" else 1

    def counts(self) -> dict[str, int]:
        """Tâches à faire par liste (panneau latéral) ; recalculé seulement après une modification."""
        if self._counts is None:
            self._counts = {lid: sum(1 for i in ids if not self._tasks[i].done) for lid, ids in self._by_list.items()}
        return self._counts

    # -- lecture : tâches --

    def get(self, task_id: str | None) -> TaskRecord | None:
        return self._tasks.get(task_id) if task_id else None

    def count(self) -> int:
        return len(self._tasks)

    def _list_tasks(self, list_id: str) -> list[TaskRecord]:
        return [self._tasks[i] for i in self._by_list.get(list_id, ())]

    def tasks_of(self, list_id: str, show_done: bool = True, done_last: bool = True,
                 collapsed: frozenset = frozenset()) -> list[tuple]:
        """[(tâche, profondeur)] d'une liste dans l'ordre d'affichage ; en cache jusqu'à une modification de CETTE
        liste. Masquer les terminées garde une sous-tâche ouverte d'un parent terminé (remontée à la racine)."""
        key = (list_id, show_done, done_last, frozenset(collapsed))
        rows = self._flat.get(key)
        if rows is None:
            tasks = self._list_tasks(list_id)
            if not show_done:
                tasks = [t for t in tasks if not t.done]
            rows = ordering.flatten(tasks, done_last=done_last, collapsed=key[3])
            self._flat[key] = rows
        return rows

    def can_have_children(self, task_id: str) -> bool:
        """Une sous-tâche de plus est-elle permise sous `task_id` (un seul niveau pour Google / Apple) ?"""
        t = self._tasks.get(task_id)
        if t is None:
            return False
        limit = self.max_depth(t.list_id)
        return limit is None or ordering.depth_of(task_id, self._tasks) < limit

    def siblings(self, task_id: str) -> list[TaskRecord]:
        """Fratrie de la tâche (elle comprise), dans l'ordre."""
        t = self._tasks.get(task_id)
        return self._siblings(t.list_id, t.parent_id) if t else []

    def tasks_in(self, list_id: str) -> list[TaskRecord]:
        """Tâches vivantes d'une liste, sans ordre (synchronisation)."""
        return self._list_tasks(list_id)

    def list_size(self, list_id: str) -> int:
        return len(self._by_list.get(list_id, ()))

    def children(self, task_id: str) -> list[TaskRecord]:
        t = self._tasks.get(task_id)
        if t is None:
            return []
        return sorted((c for c in self._list_tasks(t.list_id) if c.parent_id == task_id), key=ordering.sort_key)

    def descendants(self, task_id: str) -> list[TaskRecord]:
        t = self._tasks.get(task_id)
        return ordering.descendants(task_id, self._list_tasks(t.list_id)) if t else []

    def smart(self, view: str, today: date | None = None) -> list[TaskRecord]:
        today = today or date.today()
        key = (view, today)
        rows = self._smart.get(key)
        if rows is None:
            rows = smart.select(view, self._tasks.values(), today)
            self._smart[key] = rows
        return rows

    def due_between(self, start: date, end: date, include_done: bool = True) -> list[TaskRecord]:
        """Tâches dont l'échéance tombe dans [start, end[ (Agenda) : index par date, jamais tout parcourir."""
        days = (end - start).days
        if days <= 0:
            return []
        lo, hi = start.isoformat(), end.isoformat()
        if days <= len(self._by_due):
            keys = [k for k in ((start + timedelta(days=i)).isoformat() for i in range(days)) if k in self._by_due]
        else:
            keys = [k for k in self._by_due if lo <= k < hi]
        out = [self._tasks[i] for k in keys for i in self._by_due[k]]
        if not include_done:
            out = [t for t in out if not t.done]
        out.sort(key=lambda t: (t.due_date, t.due_time or "99:99", -t.priority, t.title.casefold()))
        return out

    # -- rappels (services/reminders.py) --

    def reminder_candidates(self, t0: float, t1: float, at_due: bool = True) -> list[tuple[float, TaskRecord]]:
        """[(déclenchement, tâche)] des tâches À FAIRE dont le rappel tombe dans [t0, t1] : rappel explicite
        (`reminder_at`), sinon, si `at_due`, l'heure d'échéance d'une tâche à heure (heure murale locale). Index
        seulement (tâches à rappel, échéances par date), jamais toutes les tâches."""
        out = []
        for task_id in self._by_reminder:
            t = self._tasks[task_id]
            if not t.done and t0 <= t.reminder_at <= t1:
                out.append((float(t.reminder_at), t))
        if at_due:
            d0 = datetime.fromtimestamp(t0).date()
            d1 = datetime.fromtimestamp(t1).date() + timedelta(days=1)
            for t in self.due_between(d0, d1, include_done=False):
                if t.due_time and not t.reminder_at:
                    h, m = (int(x) for x in t.due_time.split(":"))
                    trigger = datetime.combine(t.due, datetime.min.time()).replace(hour=h, minute=m).timestamp()
                    if t0 <= trigger <= t1:
                        out.append((trigger, t))
        out.sort(key=lambda x: x[0])
        return out

    def reminder_fired(self, task_id: str, trigger: float) -> bool:
        return (task_id, int(trigger)) in self._fired

    def mark_reminder(self, task_id: str, trigger: float) -> None:
        key = (task_id, int(trigger))
        if key not in self._fired:
            self._fired.add(key)
            self.writer.submit(lambda repo: repo.mark_reminder(*key))

    def search(self, text: str, limit: int = 300) -> list[TaskRecord]:
        needle = text.strip().casefold()
        if not needle:
            return []
        out = [t for t in self._tasks.values() if needle in t.title.casefold() or needle in t.notes.casefold()]
        out.sort(key=lambda t: (t.done, t.due_date or "9999", t.title.casefold()))
        return out[:limit]

    # -- écriture --

    def _commit(self, label: str, changes: list, record: bool = True) -> bool:
        """Applique `changes` [(genre, id, avant, après)] : mémoire tout de suite, disque par le fil d'écriture."""
        if not changes:
            return False
        now = now_ts()
        finals = []
        lists_after = dict(self._lists)
        for kind, item_id, before, after in changes:
            if kind == "list" and after is not None:
                lists_after[item_id] = after
        for kind, item_id, before, after in changes:
            if after is not None:
                after = after.copy()
                after.updated_at = now
                if not after.created_at:
                    after.created_at = now
                if kind == "task":
                    lst = lists_after.get(after.list_id)
                    errors = after.validate() + ([] if lst is not None else ["liste inconnue"])
                    if errors:
                        self.message.emit("erreur", "Tâche refusée : " + ", ".join(errors))
                        return False
                    after.version = (before.version + 1) if before is not None else max(after.version, 1)
                    after.origin = self.origin
                    after.sync_state = "dirty" if lst.synced else "local"
            finals.append((kind, item_id, before.copy() if before is not None else None, after))
        touched = set()
        lists_touched = False
        for kind, item_id, before, after in finals:
            self._put(kind, item_id, after)
            if kind == "task":
                touched.update(x.list_id for x in (before, after) if x is not None)
            else:
                lists_touched = True
                touched.add(item_id)
        if record:
            self._undo.append(Command(label, finals))
            del self._undo[:-200]
            self._redo.clear()
        self._invalidate(touched)
        if lists_touched:
            self.listsChanged.emit()
        self.changed.emit(touched)
        self.undoChanged.emit()
        sync_of = {k: (v.synced, v.account_id) for k, v in lists_after.items()}
        origin = self.origin

        def task(repo: Repository):
            for kind, item_id, before, after in finals:
                _write_change(repo, kind, item_id, before, after, sync_of, origin)

        def done(_result):
            if self.sync is not None:
                self.sync.local_changed()

        def failed(error, snapshot=finals, cmd_label=label):
            if record and self._undo and self._undo[-1].changes is snapshot:
                self._undo.pop()
            self._reload()
            self.message.emit("erreur", f"« {cmd_label} » n'a pas pu être enregistré : {error}")
        self.writer.submit(task, done, failed)
        return True

    def _reload(self) -> None:
        """Après un échec d'écriture : la mémoire redevient le contenu de la base."""
        self.writer.flush(10)
        conn = db.connect(self.path)
        try:
            self._load(Repository(conn))
        finally:
            conn.close()
        self.listsChanged.emit()
        self.changed.emit(None)
        self.undoChanged.emit()

    # -- opérations : listes --

    def create_list(self, name: str, color: str = "bleu") -> TaskList:
        order = max((lst.sort_order for lst in self._lists.values()), default=-1) + 1
        lst = TaskList(id=new_id(), name=name.strip() or "Nouvelle liste", color=color, sort_order=order)
        self._commit("Nouvelle liste", [("list", lst.id, None, lst)])
        return self._lists.get(lst.id, lst)

    def update_list(self, list_id: str, **fields) -> bool:
        current = self._lists.get(list_id)
        unknown = set(fields) - LIST_FIELDS
        if current is None or unknown:
            if unknown:
                raise ValueError(f"champs de liste inconnus : {sorted(unknown)}")
            return False
        after = current.copy()
        for k, v in fields.items():
            setattr(after, k, v)
        if after == current:
            return False
        return self._commit("Modifier la liste", [("list", list_id, current, after)])

    def delete_list(self, list_id: str) -> bool:
        current = self._lists.get(list_id)
        if current is None:
            return False
        changes = [("task", t.id, t, None) for t in self._list_tasks(list_id)]
        changes.append(("list", list_id, current, None))
        return self._commit(f"Supprimer la liste « {current.name} »", changes)

    # -- opérations : tâches --

    def _siblings(self, list_id: str, parent_id: str | None, exclude: set | None = None) -> list[TaskRecord]:
        exclude = exclude or set()
        return sorted((t for t in self._list_tasks(list_id) if t.parent_id == parent_id and t.id not in exclude),
                      key=ordering.sort_key)

    def _slot(self, list_id: str, parent_id: str | None, after_id: str | None, on_top: bool,
              exclude: set) -> tuple[float, list]:
        """Position de l'emplacement + renumérotation éventuelle de la fratrie [(genre, id, avant, après)]."""
        sibs = self._siblings(list_id, parent_id, exclude)
        if after_id is not None:
            idx = next((i + 1 for i, s in enumerate(sibs) if s.id == after_id), len(sibs))
        else:
            idx = 0 if on_top else len(sibs)
        prev = sibs[idx - 1].position if idx > 0 else None
        nxt = sibs[idx].position if idx < len(sibs) else None
        if not ordering.needs_renumber(prev, nxt):
            return ordering.between(prev, nxt), []
        positions = ordering.renumber(len(sibs) + 1)
        extra = []
        for i, s in enumerate(sibs):
            pos = positions[i if i < idx else i + 1]
            if s.position != pos:
                moved = s.copy()
                moved.position = pos
                extra.append(("task", s.id, s, moved))
        return positions[idx], extra

    def _depth_ok(self, list_id: str, parent_id: str | None, subtree_height: int) -> bool:
        limit = self.max_depth(list_id)
        if limit is None or parent_id is None:
            return True
        return ordering.depth_of(parent_id, self._tasks) + 1 + subtree_height <= limit

    def _height(self, task_id: str) -> int:
        t = self._tasks.get(task_id)
        if t is None:
            return 0
        by_id = self._tasks
        return max((ordering.depth_of(d.id, by_id) - ordering.depth_of(task_id, by_id)
                    for d in self.descendants(task_id)), default=0)

    def create_task(self, list_id: str | None = None, title: str = "", parent_id: str | None = None,
                    after_id: str | None = None, on_top: bool = False, label: str = "Nouvelle tâche",
                    **fields) -> str | None:
        """Crée une tâche (après `after_id` dans sa fratrie, sinon en tête / en fin). Rend son id (None si refusée)."""
        unknown = set(fields) - TASK_FIELDS
        if unknown:
            raise ValueError(f"champs de tâche inconnus : {sorted(unknown)}")
        if list_id is None:
            parent = self._tasks.get(parent_id)
            list_id = parent.list_id if parent else (self.default_list().id if self.default_list() else None)
        if parent_id is not None and (parent_id not in self._tasks or self._tasks[parent_id].list_id != list_id):
            parent_id = None
        if not self._depth_ok(list_id, parent_id, 0):
            self.message.emit("erreur", "Cette liste n'accepte qu'un niveau de sous-tâches.")
            return None
        position, extra = self._slot(list_id, parent_id, after_id, on_top, set())
        t = TaskRecord(id=new_id(), list_id=list_id, title=title.strip(), parent_id=parent_id, position=position,
                       version=0)
        for k, v in fields.items():
            setattr(t, k, v)
        return t.id if self._commit(label, extra + [("task", t.id, None, t)]) else None

    def update_task(self, task_id: str, label: str = "Modifier la tâche", **fields) -> bool:
        unknown = set(fields) - TASK_FIELDS
        if unknown:
            raise ValueError(f"champs de tâche inconnus : {sorted(unknown)}")
        current = self._tasks.get(task_id)
        if current is None:
            return False
        after = current.copy()
        for k, v in fields.items():
            setattr(after, k, v)
        if after.due_date is None:
            after.due_time = None
        if after == current:
            return False
        return self._commit(label, [("task", task_id, current, after)])

    def set_done(self, task_id: str, done: bool) -> bool:
        """Cocher une tâche coche aussi ses sous-tâches (comme Google et Apple) ; décocher ne touche qu'elle."""
        current = self._tasks.get(task_id)
        if current is None or current.done == bool(done):
            return False
        targets = [current] + ([d for d in self.descendants(task_id) if not d.done] if done else [])
        now = now_ts()
        changes = []
        for t in targets:
            after = t.copy()
            after.done = bool(done)
            after.completed_at = now if done else None
            changes.append(("task", t.id, t, after))
        return self._commit("Terminer la tâche" if done else "Rouvrir la tâche", changes)

    def delete_tasks(self, task_ids) -> bool:
        """Supprime des tâches et toutes leurs sous-tâches, en UNE commande."""
        seen, changes = set(), []
        for task_id in task_ids:
            t = self._tasks.get(task_id)
            if t is None or t.id in seen:
                continue
            for x in [t] + self.descendants(task_id):
                if x.id not in seen:
                    seen.add(x.id)
                    changes.append(("task", x.id, x, None))
        label = "Supprimer la tâche" if len(seen) == 1 else f"Supprimer {len(seen)} tâches"
        return self._commit(label, changes)

    def delete_task(self, task_id: str) -> bool:
        return self.delete_tasks([task_id])

    def move(self, task_id: str, list_id: str | None = None, parent_id=_KEEP, after_id: str | None = None,
             on_top: bool = False) -> bool:
        """Déplace une tâche (et ses sous-tâches) : dans sa fratrie, sous un autre parent, vers une autre liste.
        `after_id` = la sœur après laquelle se placer (None : en tête si `on_top`, sinon en fin)."""
        current = self._tasks.get(task_id)
        if current is None:
            return False
        list_id = list_id or current.list_id
        if list_id not in self._lists:
            return False
        if parent_id is _KEEP:
            parent_id = current.parent_id if list_id == current.list_id else None
        subtree = self.descendants(task_id)
        banned = {task_id} | {d.id for d in subtree}
        if parent_id in banned:
            return False                                 # sous sa propre descendance : cycle
        if parent_id is not None and (parent_id not in self._tasks or self._tasks[parent_id].list_id != list_id):
            return False
        if not self._depth_ok(list_id, parent_id, self._height(task_id)):
            self.message.emit("erreur", "Cette liste n'accepte qu'un niveau de sous-tâches.")
            return False
        position, extra = self._slot(list_id, parent_id, after_id, on_top, {task_id})
        after = current.copy()
        after.list_id, after.parent_id, after.position = list_id, parent_id, position
        if after == current:
            return False
        changes = [c for c in extra if c[1] != task_id] + [("task", task_id, current, after)]
        if list_id != current.list_id:
            for d in subtree:
                moved = d.copy()
                moved.list_id = list_id
                changes.append(("task", d.id, d, moved))
        label = "Déplacer la tâche" if list_id == current.list_id else "Changer de liste"
        return self._commit(label, changes)

    def indent(self, task_id: str) -> bool:
        """Devient la dernière sous-tâche de la sœur qui la précède (Tab)."""
        t = self._tasks.get(task_id)
        if t is None:
            return False
        sibs = self._siblings(t.list_id, t.parent_id)
        idx = next(i for i, s in enumerate(sibs) if s.id == task_id)
        if idx == 0:
            return False
        new_parent = sibs[idx - 1].id
        last = self.children(new_parent)
        return self.move(task_id, parent_id=new_parent, after_id=last[-1].id if last else None)

    def outdent(self, task_id: str) -> bool:
        """Remonte d'un niveau, juste après son parent (Maj + Tab)."""
        t = self._tasks.get(task_id)
        if t is None or t.parent_id is None or t.parent_id not in self._tasks:
            return False
        parent = self._tasks[t.parent_id]
        return self.move(task_id, parent_id=parent.parent_id, after_id=parent.id)

    # -- comptes et synchronisation (appelé dans le fil de l'interface : sync/manager.py, sync/merge.py) --

    def accounts(self) -> list[dict]:
        return [dict(a) for a in self._accounts.values()]

    def account(self, account_id: str | None) -> dict | None:
        a = self._accounts.get(account_id) if account_id else None
        return dict(a) if a else None

    def save_account(self, account: dict) -> None:
        self._accounts[account["id"]] = dict(account)
        snapshot = dict(account)
        self.writer.submit(lambda repo: repo.save_account(snapshot))

    def synced_lists(self, account_id: str) -> list[TaskList]:
        return [lst for lst in self.lists() if lst.account_id == account_id and lst.synced]

    def outbox_count(self) -> int:
        conn = db.connect(self.path)
        try:
            return Repository(conn).outbox_count()
        finally:
            conn.close()

    def publish_list(self, list_id: str, account: dict) -> bool:
        """Liste locale envoyée vers Google Tasks (créée là-bas au prochain passage, avec toutes ses tâches).
        Une liste de plus d'un niveau de sous-tâches est aplatie à un niveau (limite de Google)."""
        lst = self._lists.get(list_id)
        if lst is None or lst.source != "local":
            return False
        after = lst.copy()
        after.source, after.account_id, after.sync_enabled = f"google:{account.get('email', '')}", account["id"], True
        changes = [("list", list_id, lst, after)]
        by_id = self._tasks
        for t in self._list_tasks(list_id):
            moved = t.copy()
            if t.parent_id and ordering.depth_of(t.id, by_id) > 1:
                top = t
                while top.parent_id in by_id and by_id[top.parent_id].parent_id:
                    top = by_id[top.parent_id]
                moved.parent_id = top.parent_id
            changes.append(("task", t.id, t, moved))
        return self._commit(f"Synchroniser « {lst.name} » avec Google Tasks", changes)

    def apply_sync(self, lists_save=(), lists_delete=(), tasks_save=(), tasks_delete=(), dequeue=(),
                   failed=(), enqueue=(), account: dict | None = None) -> None:
        """Résultat d'une synchronisation, déjà fusionné (`sync/merge.py`) : mémoire tout de suite, base par le fil
        d'écriture. Jamais annulable, jamais renvoyé (les lignes arrivent avec leur `sync_state` et leur origine).
        `tasks_delete` / `lists_delete` : lignes à effacer de la base (déjà absentes de la mémoire ou à retirer)."""
        touched: set = set()
        lists_changed = False
        for lst in lists_save:
            self._lists[lst.id] = lst
            touched.add(lst.id)
            lists_changed = True
        for list_id in lists_delete:
            if self._lists.pop(list_id, None) is not None:
                lists_changed = True
            touched.add(list_id)
        for t in tasks_save:
            old = self._tasks.get(t.id)
            if old is not None:
                touched.add(old.list_id)
            self._put("task", t.id, t)
            touched.add(t.list_id)
        for task_id in tasks_delete:
            old = self._tasks.get(task_id)
            if old is not None:
                touched.add(old.list_id)
                self._put("task", task_id, None)
        if account is not None:
            self._accounts[account["id"]] = dict(account)
        if touched:
            self._invalidate(touched)
        if lists_changed:
            self.listsChanged.emit()
        if touched:
            self.changed.emit(touched)
        lists_save, tasks_save = [x.copy() for x in lists_save], [x.copy() for x in tasks_save]
        lists_delete, tasks_delete = list(lists_delete), list(tasks_delete)
        dequeue, failed, enqueue = list(dequeue), list(failed), list(enqueue)
        acc = dict(account) if account else None
        origin = (f"google:{acc['email']}" if acc else "remote")

        def task(repo: Repository):
            for lst in lists_save:
                repo.save_list(lst)
            for t in tasks_save:
                repo.save_task(t)
                repo.log_change("task", t.id, "remote", t.version, origin)
            for task_id in tasks_delete:
                repo.delete_task(task_id)
            for list_id in lists_delete:
                repo.conn.execute("DELETE FROM tasks WHERE list_id = ?", (list_id,))
                repo.delete_list(list_id)
            for entity, entity_id in dequeue:
                repo.dequeue(entity, entity_id)
            now = now_ts()
            for entity, entity_id, error in failed:
                repo.outbox_failed(entity, entity_id, error, now)
            for entity, entity_id, list_id, account_id in enqueue:
                repo.enqueue(entity, entity_id, list_id, account_id)
            if acc is not None:
                repo.save_account(acc)

        self.writer.submit(task, None, lambda e: self.message.emit("erreur", f"Synchronisation non enregistrée : {e}"))

    def remove_account(self, account_id: str, keep_tasks: bool = True) -> None:
        """Compte déconnecté : ses listes deviennent des listes locales (rien n'est perdu) ou sont effacées."""
        lists_save, lists_delete, tasks_save, tasks_delete = [], [], [], []
        for lst in [x for x in self._lists.values() if x.account_id == account_id]:
            if keep_tasks:
                after = lst.copy()
                after.source, after.account_id, after.remote_id, after.etag = "local", None, None, None
                after.sync_enabled = False
                after.props.pop("cursor", None)
                lists_save.append(after)
                for t in self._list_tasks(lst.id):
                    local = t.copy()
                    local.remote_id, local.etag, local.base, local.sync_state = None, None, None, "local"
                    tasks_save.append(local)
            else:
                lists_delete.append(lst.id)
                tasks_delete += [t.id for t in self._list_tasks(lst.id)]
        self._accounts.pop(account_id, None)
        self.apply_sync(lists_save, lists_delete, tasks_save, tasks_delete)
        self.writer.submit(lambda repo: (repo.delete_account(account_id),
                                         repo.conn.execute("DELETE FROM sync_outbox WHERE account_id = ?",
                                                           (account_id,))))
        self._undo.clear()
        self._redo.clear()
        self.undoChanged.emit()

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

    def _current(self, kind: str, item_id: str):
        return (self._lists if kind == "list" else self._tasks).get(item_id)

    def _reverse(self, cmd: Command, undo: bool) -> list:
        """Changements à rejouer depuis l'état COURANT. Les listes passent avant leurs tâches à la recréation et
        après elles à la suppression (validation : une tâche exige sa liste)."""
        out = []
        items = list(reversed(cmd.changes)) if undo else list(cmd.changes)
        for kind, item_id, before, after in items:
            target = before if undo else after
            current = self._current(kind, item_id)
            if target is None:
                if current is not None:
                    out.append((kind, item_id, current, None))
                continue
            restored = target.copy()
            if current is not None and kind == "task":
                restored.version = current.version
                restored.remote_id, restored.etag = current.remote_id, current.etag
            out.append((kind, item_id, current, restored))
        out.sort(key=lambda c: 0 if (c[0] == "list" and c[3] is not None) else (2 if c[0] == "list" else 1))
        return out

    # -- sauvegardes --

    def backup_now(self, on_done=None) -> None:
        path = self.path
        keep = int(self.settings.get("taches_backup_keep", 14) or 14)

        def task(repo):
            dest = db.backup(repo.conn, db.backups_dir(path) / db.backup_name())
            db.rotate_backups(path, keep)
            repo.set_meta("last_backup", {"at": now_ts(), "file": str(dest)})
            return dest

        def done(dest):
            self.message.emit("info", f"Tâches sauvegardées : {dest}")
            if on_done:
                on_done(dest)
        self.writer.submit(task, done, lambda e: self.message.emit("erreur", f"Sauvegarde des tâches : {e}"),
                           transactional=False)

    def _daily_backup(self) -> None:
        if not self.settings.get("taches_backup_daily", True):
            return
        conn = db.connect(self.path)
        try:
            last = Repository(conn).get_meta("last_backup") or {}
        finally:
            conn.close()
        if time.time() - float(last.get("at", 0)) > 86400 * 0.95:
            self.backup_now()


def _write_change(repo: Repository, kind: str, item_id: str, before, after, sync_of: dict, origin: str) -> None:
    """Une ligne dans la transaction du fil d'écriture. Une ligne déjà connue de la source distante (`remote_id`)
    est supprimée en douceur et mise dans la file d'envoi ; sinon elle disparaît de la base."""
    if kind == "list":
        lst = after if after is not None else before
        synced, account = sync_of.get(item_id, (False, None))
        if after is None:
            if before.remote_id:
                gone = before.copy()
                gone.deleted, gone.updated_at = True, now_ts()
                repo.save_list(gone)
                if before.synced:
                    repo.enqueue("list", item_id, item_id, before.account_id)
            else:
                repo.delete_list(item_id)
            repo.log_change("list", item_id, "delete", 0, origin)
            return
        repo.save_list(lst)
        repo.log_change("list", item_id, "update" if before is not None else "create", 0, origin)
        if synced:
            repo.enqueue("list", item_id, item_id, account)
        return
    if after is None:
        if before is None:
            return
        synced, account = sync_of.get(before.list_id, (False, None))
        if before.remote_id:
            repo.mark_deleted(item_id, before.version + 1, origin)
            if synced:
                repo.enqueue("task", item_id, before.list_id, account)
        else:
            repo.delete_task(item_id)
        repo.log_change("task", item_id, "delete", before.version + 1, origin)
        return
    synced, account = sync_of.get(after.list_id, (False, None))
    repo.save_task(after)
    repo.log_change("task", item_id, "update" if before is not None else "create", after.version, origin)
    if synced:
        repo.enqueue("task", item_id, after.list_id, account)
