"""Ordre des tâches : positions fractionnaires et arbre parent / sous-tâches.

Insérer une tâche entre deux autres prend la moyenne de leurs positions : aucune autre ligne n'est réécrite (un
seul envoi vers Google, une seule ligne en base). Quand l'écart devient trop petit (des dizaines d'insertions au
même endroit), `renumber` redonne des positions espacées à la fratrie."""
from __future__ import annotations

from collections import defaultdict

STEP = 1024.0
MIN_GAP = 1e-6


def between(before: float | None, after: float | None) -> float:
    """Position entre `before` et `after` (None = début / fin de la fratrie)."""
    if before is None and after is None:
        return STEP
    if before is None:
        return after - STEP
    if after is None:
        return before + STEP
    return (before + after) / 2.0


def needs_renumber(before: float | None, after: float | None) -> bool:
    return before is not None and after is not None and (after - before) < MIN_GAP


def renumber(count: int) -> list[float]:
    return [STEP * (i + 1) for i in range(count)]


def sort_key(task) -> tuple:
    return (task.position, task.created_at, task.id)


def children_map(tasks) -> dict:
    """parent_id -> enfants triés. Un parent absent (supprimé, autre liste) : l'enfant remonte à la racine."""
    ids = {t.id for t in tasks}
    out = defaultdict(list)
    for t in tasks:
        parent = t.parent_id if t.parent_id in ids else None
        out[parent].append(t)
    for kids in out.values():
        kids.sort(key=sort_key)
    return out


def flatten(tasks, done_last: bool = False, collapsed: set | frozenset = frozenset()) -> list[tuple]:
    """[(tâche, profondeur)] dans l'ordre d'affichage : chaque parent suivi de ses sous-tâches. `done_last` : les
    tâches terminées après les autres dans chaque fratrie. `collapsed` : ids dont les sous-tâches sont masquées.
    Protégé contre un cycle (données distantes abîmées) : une tâche n'apparaît qu'une fois."""
    kids = children_map(tasks)
    out: list[tuple] = []
    seen: set = set()

    def walk(parent, depth, shown):
        group = kids.get(parent, ())
        if done_last:
            group = [t for t in group if not t.done] + [t for t in group if t.done]
        for t in group:
            if t.id in seen:
                continue
            seen.add(t.id)
            if shown:
                out.append((t, depth))
            walk(t.id, depth + 1, shown and t.id not in collapsed)   # repliée : parcourue, pas montrée
    walk(None, 0, True)
    # Cycle complet (a -> b -> a) : aucune racine ; ces tâches restent visibles à la racine.
    for t in sorted(tasks, key=sort_key):
        if t.id not in seen:
            seen.add(t.id)
            out.append((t, 0))
    return out


def descendants(task_id: str, tasks) -> list:
    """Toutes les sous-tâches (récursivement) de `task_id`, sans la tâche elle-même."""
    kids = children_map(tasks)
    out, stack, seen = [], [task_id], {task_id}
    while stack:
        for child in kids.get(stack.pop(), ()):
            if child.id not in seen:
                seen.add(child.id)
                out.append(child)
                stack.append(child.id)
    return out


def depth_of(task_id: str, by_id: dict) -> int:
    depth, cur, seen = 0, by_id.get(task_id), set()
    while cur is not None and cur.parent_id and cur.parent_id in by_id and cur.id not in seen:
        seen.add(cur.id)
        depth += 1
        cur = by_id[cur.parent_id]
    return depth
