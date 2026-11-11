"""Moteur de synchronisation Google Tasks, côté RÉSEAU (fil de synchronisation). Il ne fait que LIRE la base (sa
propre connexion, après que le fil d'écriture a tout écrit) et rapporte un `SyncResult` ; la fusion et l'écriture
se font ensuite dans le fil de l'interface (`merge.py`).

Un passage, par compte :
1. Listes : envoi des listes locales créées / renommées / supprimées ; listes nouvelles, renommées ou disparues
   chez Google relevées.
2. Réception : tâches de chaque liste synchronisée modifiées depuis le dernier passage (`updatedMin` = horloge du
   passage précédent moins 2 min de marge ; Google Tasks n'a pas de `syncToken`), supprimées comprises. Premier
   passage d'une liste : tout (« complet » : ce qui manque chez Google et n'a pas changé ici sera retiré).
3. Envoi : file `sync_outbox`, parents d'abord ; création (avec `parent` / `previous` pour la place), `move` si la
   tâche a changé de parent ou de place, `PATCH` des seuls champs changés depuis `base`, suppression. Une tâche
   modifiée des deux côtés depuis le dernier passage n'est PAS envoyée : elle est fusionnée d'abord, envoyée au
   passage suivant (relancé aussitôt).

Hors ligne en cours de route : ce qui a déjà été envoyé est rapporté (sinon une tâche créée chez Google serait
recréée au passage suivant) et le reste attend (`offline`)."""
from __future__ import annotations

import time
from dataclasses import dataclass, field

from fm_agenda.sync.provider import NotFoundError, SyncError, TransientError
from . import mapping as mp


@dataclass
class Pushed:
    task_id: str
    version: int
    kind: str                      # created, updated, deleted, detached
    item: dict | None = None
    list_id: str | None = None
    parent_id: str | None = None
    position: float = 0.0


@dataclass
class SyncResult:
    account_id: str
    new_lists: list = field(default_factory=list)        # [{remote_id, name, etag, cursor}]
    list_updates: dict = field(default_factory=dict)     # id locale -> {name?, remote_id?, etag?, cursor?}
    detach_lists: list = field(default_factory=list)     # disparues chez Google : deviennent locales
    purge_lists: list = field(default_factory=list)      # supprimées ici, suppression faite chez Google
    pulled: list = field(default_factory=list)           # [(id locale | "remote:<id>", éléments, complet)]
    pushed: list = field(default_factory=list)           # [Pushed]
    lists_done: list = field(default_factory=list)       # entrées « list » de la file envoyées
    failed: list = field(default_factory=list)           # [(genre, id, erreur)]
    skipped: int = 0                                     # attendent la fusion : relancer un passage
    offline: str = ""                                    # réseau perdu en route
    errors: list = field(default_factory=list)

    def summary(self) -> str:
        received = sum(len(items) for _l, items, _f in self.pulled)
        parts = [f"{received} reçue(s)", f"{len(self.pushed)} envoyée(s)"]
        if self.new_lists:
            parts.append(f"{len(self.new_lists)} liste(s) nouvelle(s)")
        if self.offline:
            parts.append("hors ligne")
        return ", ".join(parts)


class SyncEngine:
    def __init__(self, repo, provider, account: dict, clock=time.time):
        self.repo = repo
        self.provider = provider
        self.account = account
        self.clock = clock

    def run(self) -> SyncResult:
        acc_id = self.account["id"]
        r = SyncResult(acc_id)
        now = self.clock()
        repo, gp = self.repo, self.provider
        local_lists = [lst for lst in repo.all_lists(include_deleted=True) if lst.account_id == acc_id]
        lists_by_id = {lst.id: lst for lst in local_lists}
        by_remote = {lst.remote_id: lst for lst in local_lists if lst.remote_id}
        outbox = [e for e in repo.outbox() if e["next_at"] <= now]
        list_entries = {e["entity_id"] for e in outbox if e["entity"] == "list"}
        # tâches supprimées ici, pas encore chez Google : ce qu'on en reçoit est ignoré (la suppression part)
        gone = set()
        for e in outbox:
            if e["entity"] == "task":
                row = repo.get_task(e["entity_id"])
                if row is not None and row.deleted and row.remote_id:
                    gone.add(row.remote_id)
        remote_lists = gp.list_tasklists()                # hors ligne ici : rien n'a été fait, l'erreur remonte
        remote_ids = {x["id"] for x in remote_lists}
        remote_of = {lst.id: lst.remote_id for lst in local_lists}
        cursor_now = mp.rfc3339(now - 120)
        try:
            # 1. listes envoyées
            for lst in local_lists:
                if lst.id not in list_entries:
                    continue
                try:
                    if lst.deleted:
                        if lst.remote_id and lst.remote_id in remote_ids:
                            gp.delete_tasklist(lst.remote_id)
                        r.purge_lists.append(lst.id)
                    elif not lst.sync_enabled:
                        pass
                    elif not lst.remote_id:
                        item = gp.insert_tasklist(lst.name)
                        remote_of[lst.id] = item["id"]
                        remote_ids.add(item["id"])
                        r.list_updates.setdefault(lst.id, {}).update(remote_id=item["id"], etag=item.get("etag"))
                    elif lst.remote_id in remote_ids:
                        item = gp.patch_tasklist(lst.remote_id, lst.name)
                        r.list_updates.setdefault(lst.id, {})["etag"] = item.get("etag")
                    r.lists_done.append(lst.id)
                except TransientError:
                    raise
                except SyncError as exc:
                    r.failed.append(("list", lst.id, str(exc)))
            # listes vues chez Google
            for x in remote_lists:
                lst = by_remote.get(x["id"])
                if lst is None:
                    r.new_lists.append({"remote_id": x["id"], "name": x.get("title") or "Sans titre",
                                        "etag": x.get("etag"), "cursor": cursor_now})
                elif not lst.deleted and lst.id not in list_entries and (x.get("title") or "") != lst.name:
                    r.list_updates.setdefault(lst.id, {})["name"] = x.get("title") or lst.name
            for lst in local_lists:
                if lst.remote_id and lst.remote_id not in remote_ids and not lst.deleted:
                    r.detach_lists.append(lst.id)
            # 2. réception
            pulled_etags: dict = {}
            for lst in local_lists:
                rid = remote_of.get(lst.id)
                if lst.deleted or not lst.sync_enabled or rid not in remote_ids or lst.id in r.detach_lists:
                    continue
                cursor = (lst.props or {}).get("cursor")
                items = [it for it in gp.list_tasks(rid, cursor) if it["id"] not in gone]
                r.pulled.append((lst.id, items, cursor is None))
                r.list_updates.setdefault(lst.id, {})["cursor"] = cursor_now
                for item in items:
                    pulled_etags[item["id"]] = item.get("etag")
            for nl in r.new_lists:
                r.pulled.append(("remote:" + nl["remote_id"], gp.list_tasks(nl["remote_id"], None), True))
            # 3. envoi
            self._push_tasks(r, outbox, lists_by_id, remote_of, remote_ids, pulled_etags)
        except TransientError as exc:
            r.offline = str(exc)
        return r

    # -- envoi des tâches --

    def _push_tasks(self, r: SyncResult, outbox, lists_by_id, remote_of, remote_ids, pulled_etags) -> None:
        repo, gp = self.repo, self.provider
        rows = []
        for e in outbox:
            if e["entity"] != "task":
                continue
            row = repo.get_task(e["entity_id"])
            if row is None:
                continue
            base_list = (row.base or {}).get("_list")
            if row.list_id not in lists_by_id and base_list not in lists_by_id:
                continue                                  # autre compte
            rows.append(row)
        parents = {row.id: row.parent_id for row in rows}

        def depth(row) -> int:
            d, cur, seen = 0, row.parent_id, set()
            while cur and cur in parents and cur not in seen:
                seen.add(cur)
                d += 1
                cur = parents[cur]
            return d
        rows.sort(key=lambda row: (row.deleted, depth(row), row.position))
        created: dict = {}
        siblings_cache: dict = {}

        def remote_task_id(local_id):
            if local_id in created:
                return created[local_id]
            t = repo.get_task(local_id, include_deleted=False)
            return t.remote_id if t is not None else None

        def previous_of(row):
            sibs = siblings_cache.get(row.list_id)
            if sibs is None:
                sibs = siblings_cache[row.list_id] = repo.tasks_in_list(row.list_id)
            before = sorted((s for s in sibs if s.parent_id == row.parent_id and s.id != row.id
                             and s.position < row.position), key=lambda s: s.position)
            for s in reversed(before):
                rid = created.get(s.id) or s.remote_id
                if rid:
                    return rid
            return None

        for row in rows:
            try:
                self._push_one(r, row, lists_by_id, remote_of, remote_ids, pulled_etags, created,
                               remote_task_id, previous_of)
            except TransientError:
                raise
            except SyncError as exc:
                r.failed.append(("task", row.id, str(exc)))

    def _push_one(self, r, row, lists_by_id, remote_of, remote_ids, pulled_etags, created, remote_task_id,
                  previous_of) -> None:
        gp = self.provider
        lst = lists_by_id.get(row.list_id)
        base = row.base or {}
        old_list = lists_by_id.get(base.get("_list")) if base.get("_list") else lst
        list_rid = remote_of.get(row.list_id) if lst is not None and lst.sync_enabled and not lst.deleted else None
        if list_rid not in remote_ids:
            list_rid = None
        old_rid = remote_of.get(old_list.id) if old_list is not None else None
        if row.deleted:
            if row.remote_id and old_rid and old_list.id not in r.purge_lists:
                try:
                    gp.delete_task(old_rid, row.remote_id)
                except NotFoundError:
                    pass
            r.pushed.append(Pushed(row.id, row.version, "deleted"))
            return
        if row.remote_id and pulled_etags.get(row.remote_id) not in (None, row.etag):
            r.skipped += 1                                 # modifiée des deux côtés : fusion d'abord
            return
        if list_rid is None:                               # passée dans une liste qui n'est plus synchronisée
            if row.remote_id and old_rid:
                try:
                    gp.delete_task(old_rid, row.remote_id)
                except NotFoundError:
                    pass
            r.pushed.append(Pushed(row.id, row.version, "detached"))
            return
        remote_id = row.remote_id
        if remote_id and old_rid and old_rid != list_rid:  # changement de liste : recréée dans la nouvelle
            try:
                gp.delete_task(old_rid, remote_id)
            except NotFoundError:
                pass
            remote_id = None
        parent_rid = remote_task_id(row.parent_id) if row.parent_id else None
        if row.parent_id and not parent_rid:
            r.skipped += 1                                 # parent pas encore chez Google
            return
        item = None
        if remote_id:
            try:
                if mp.moved(row, base) or not base:
                    item = gp.move_task(list_rid, remote_id, parent_rid, previous_of(row))
                fields = mp.changed_fields(row, base)
                if fields:
                    item = gp.patch_task(list_rid, remote_id, mp.body_for(row, fields))
            except NotFoundError:
                remote_id = None                           # supprimée chez Google entre-temps : recréée
        if not remote_id:
            item = gp.insert_task(list_rid, mp.body_for(row), parent_rid, previous_of(row))
            created[row.id] = item["id"]
            kind = "created"
        else:
            kind = "updated"
            if item is None:                               # rien à envoyer (déjà d'accord)
                item = {"id": remote_id, "etag": row.etag, **_item_of(row, parent_rid)}
        r.pushed.append(Pushed(row.id, row.version, kind, item, row.list_id, row.parent_id, row.position))


def _item_of(row, parent_rid) -> dict:
    out = {"title": row.title, "notes": row.notes, "status": "completed" if row.done else "needsAction",
           "due": mp.due_to_google(row.due_date)}
    if parent_rid:
        out["parent"] = parent_rid
    return out
