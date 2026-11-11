"""Fusion d'un `SyncResult` dans les tâches en mémoire (fil de l'interface), puis `TaskService.apply_sync`.

Règles :
- Tâche reçue inconnue -> créée (`synced`, origine `google:<compte>`, jamais renvoyée) ; parents d'abord.
- Même `etag` que la nôtre -> écho de notre envoi : rien.
- Tâche non modifiée ici -> les champs synchronisés prennent la valeur de Google (heure, priorité, drapeau,
  lien restent).
- Modifiée des deux côtés (fusion à trois voies contre `base`) : un champ changé d'un seul côté prend ce côté ;
  changé des deux côtés différemment -> réglage `taches_conflict_policy` : « recent » (la modification la plus
  récente, `updated` de Google contre `updated_at` local), « google », « local ». Ce qui reste différent de Google
  repart au passage suivant.
- Supprimée chez Google -> supprimée ici, SAUF si elle a été modifiée ici entre-temps (elle est alors recréée).
- Passage complet d'une liste : une tâche synchronisée absente chez Google et inchangée ici est retirée.
- Résultat d'un envoi : identifiant et `etag` Google posés ; « synchronisée » seulement si la tâche n'a pas changé
  depuis sa lecture (`version`), sinon elle repartira."""
from __future__ import annotations

import time

from ..core.model import TaskList, TaskRecord, new_id
from . import mapping as mp

LIST_COLORS = ("bleu", "vert", "violet", "orange", "cyan", "rose", "rouge", "gris")


def apply(service, result, policy: str = "recent", clock=time.time) -> dict:
    now = int(clock())
    acc = service.account(result.account_id)
    if acc is None:
        return {"skipped": 0}
    email = acc.get("email", "")
    origin = f"google:{email}"
    lists_save: dict = {}
    lists_delete: list = []
    tasks_save: dict = {}
    tasks_delete: list = []
    dequeue: list = []
    enqueue: list = []

    def cur_list(list_id):
        return lists_save.get(list_id) or service.get_list(list_id)

    def cur_task(task_id):
        return tasks_save.get(task_id) or service.get(task_id)

    # -- listes --
    for list_id, upd in result.list_updates.items():
        lst = cur_list(list_id)
        if lst is None:
            continue
        after = lst.copy()
        for key in ("name", "remote_id", "etag"):
            if key in upd and upd[key] is not None:
                setattr(after, key, upd[key])
        if "cursor" in upd:
            after.props = dict(after.props, cursor=upd["cursor"])
        lists_save[list_id] = after
    dequeue += [("list", lid) for lid in result.lists_done]
    for lid in result.purge_lists:
        lists_delete.append(lid)
    known_remote = {lst.remote_id for lst in service.lists() if lst.remote_id}
    remote_map: dict = {}
    order = max((lst.sort_order for lst in service.lists()), default=0) + 1
    for i, nl in enumerate(result.new_lists):
        if nl["remote_id"] in known_remote:
            continue
        lst = TaskList(id=new_id(), name=nl["name"], color=LIST_COLORS[(order + i) % len(LIST_COLORS)],
                       source=origin, account_id=acc["id"], remote_id=nl["remote_id"], etag=nl.get("etag"),
                       sync_enabled=True, sort_order=order + i, props={"cursor": nl["cursor"]},
                       created_at=now, updated_at=now)
        lists_save[lst.id] = lst
        remote_map["remote:" + nl["remote_id"]] = lst.id
    for lid in result.detach_lists:
        lst = cur_list(lid)
        if lst is None:
            continue
        after = lst.copy()
        after.source, after.account_id, after.remote_id, after.etag, after.sync_enabled = "local", None, None, None, \
            False
        after.props = {k: v for k, v in after.props.items() if k != "cursor"}
        lists_save[lid] = after
        for t in service.tasks_in(lid):
            local = t.copy()
            local.remote_id, local.etag, local.base, local.sync_state = None, None, None, "local"
            tasks_save[t.id] = local
            dequeue.append(("task", t.id))

    # -- réception --
    for key, items, full in result.pulled:
        list_id = remote_map.get(key, key)
        if cur_list(list_id) is None or list_id in result.detach_lists:
            continue
        _merge_list(service, list_id, items, full, tasks_save, tasks_delete, dequeue, enqueue, acc, origin,
                    policy, now, cur_task)

    # -- résultats des envois --
    for p in result.pushed:
        if p.kind == "deleted":
            tasks_delete.append(p.task_id)
            continue
        t = cur_task(p.task_id)
        if t is None:
            continue
        after = t.copy()
        if p.kind == "detached":
            after.remote_id, after.etag, after.base, after.sync_state = None, None, None, "local"
            dequeue.append(("task", t.id))
        else:
            after.remote_id = p.item["id"]
            after.etag = p.item.get("etag")
            after.base = mp.snapshot(p.item, p.list_id, p.parent_id, p.position)
            if t.version == p.version:
                after.sync_state = "synced"
                dequeue.append(("task", t.id))
        tasks_save[after.id] = after

    acc = dict(acc, last_sync_at=now, status="connected",
               last_error=("; ".join(e for _k, _i, e in result.failed) or result.offline)[:500])
    service.apply_sync(list(lists_save.values()), lists_delete, list(tasks_save.values()), tasks_delete, dequeue,
                       result.failed, enqueue, account=acc)
    return {"skipped": result.skipped, "received": sum(len(i) for _k, i, _f in result.pulled),
            "pushed": len(result.pushed)}


def _merge_list(service, list_id, items, full, tasks_save, tasks_delete, dequeue, enqueue, acc, origin, policy,
                now, cur_task) -> None:
    by_rid = {t.remote_id: t.id for t in service.tasks_in(list_id) if t.remote_id}
    by_rid.update({t.remote_id: t.id for t in tasks_save.values() if t.list_id == list_id and t.remote_id})
    batch = {item["id"] for item in items}
    # parents d'abord (une sous-tâche reçue avec son parent nouveau)
    items = sorted(items, key=lambda it: (bool(it.get("parent")) and it.get("parent") in batch,
                                          mp.position_of(it)))
    seen = set()
    for item in items:
        rid = item["id"]
        seen.add(rid)
        local_id = by_rid.get(rid)
        t = cur_task(local_id) if local_id else None
        if item.get("deleted"):
            if t is None:
                continue
            if t.sync_state == "dirty" and mp.changed_fields(t, t.base):
                keep = t.copy()                            # modifiée ici : recréée chez Google
                keep.remote_id, keep.etag, keep.base = None, None, None
                tasks_save[keep.id] = keep
                enqueue.append(("task", keep.id, keep.list_id, acc["id"]))
            else:
                tasks_delete.append(t.id)
                tasks_save.pop(t.id, None)
                dequeue.append(("task", t.id))
            continue
        parent_local = by_rid.get(item.get("parent")) if item.get("parent") else None
        pos = mp.position_of(item)
        rf = mp.remote_fields(item)
        if t is None:
            new = TaskRecord(id=new_id(), list_id=list_id, parent_id=parent_local, position=pos,
                             title=rf["title"], notes=rf["notes"], done=rf["done"], due_date=rf["due_date"],
                             completed_at=mp.parse_ts(item.get("completed")) if rf["done"] else None,
                             remote_id=rid, etag=item.get("etag"), version=1, created_at=now,
                             updated_at=mp.parse_ts(item.get("updated")) or now, sync_state="synced",
                             origin=origin, props={"webViewLink": item["webViewLink"]} if item.get("webViewLink")
                             else {})
            new.base = mp.snapshot(item, list_id, parent_local, pos)
            tasks_save[new.id] = new
            by_rid[rid] = new.id
            continue
        if t.etag == item.get("etag"):
            continue                                       # écho de notre envoi
        dirty = t.sync_state == "dirty"
        local_changed = mp.changed_fields(t, t.base) if dirty else set()
        remote_updated = mp.parse_ts(item.get("updated")) or 0
        after = t.copy()
        base = t.base or {}
        for f in mp.SYNCED:
            if rf[f] == getattr(t, f):
                continue
            remote_changed = not t.base or rf[f] != base.get(f)
            if not remote_changed:
                continue                                   # seul ce PC l'a changé : il repartira
            if f not in local_changed or policy == "google" or (policy == "recent" and remote_updated >= t.updated_at):
                setattr(after, f, rf[f])
        if after.done != t.done:
            after.completed_at = (mp.parse_ts(item.get("completed")) or now) if after.done else None
        if not (dirty and mp.moved(t, t.base)):
            if not item.get("parent") or parent_local is not None:
                after.parent_id = parent_local
            after.position = pos
        after.etag = item.get("etag")
        # base = la place chez Google, en termes locaux : un déplacement local non encore envoyé reste visible
        base_parent = parent_local if (not item.get("parent") or parent_local is not None) else after.parent_id
        after.base = mp.snapshot(item, list_id, base_parent, pos)
        after.origin = origin
        after.version = t.version + 1
        if mp.changed_fields(after, after.base) or mp.moved(after, after.base):
            after.sync_state = "dirty"
            enqueue.append(("task", after.id, list_id, acc["id"]))
        else:
            after.sync_state = "synced"
            dequeue.append(("task", after.id))
        tasks_save[after.id] = after
    if full:
        for t in service.tasks_in(list_id):
            if t.remote_id and t.remote_id not in seen and t.sync_state == "synced":
                tasks_delete.append(t.id)
                tasks_save.pop(t.id, None)
