"""Correspondance tâche locale <-> ressource Google Tasks v1 (sans réseau ni Qt).

Champs synchronisés : titre, notes, terminée (`status` + `completed`), DATE d'échéance (`due` : Google ignore
l'heure), parent, position. Restent locaux : heure d'échéance, rappel, priorité, marquée, lien.

`base` (gardé dans la tâche) = ce que Google avait la dernière fois que les deux côtés étaient d'accord, en termes
LOCAUX : sert à savoir ce que chaque côté a changé depuis (fusion à trois voies, envoi des seuls champs changés).
Clés : champs synchronisés + `_list` / `_parent` / `_pos` (liste, parent, position locaux à ce moment-là)."""
from __future__ import annotations

from datetime import datetime, timezone

SYNCED = ("title", "notes", "done", "due_date")


def rfc3339(ts: float) -> str:
    return datetime.fromtimestamp(ts, timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.000Z")


def parse_ts(text: str | None) -> int | None:
    if not text:
        return None
    try:
        return int(datetime.fromisoformat(text.replace("Z", "+00:00")).timestamp())
    except ValueError:
        return None


def due_to_google(due_date: str | None) -> str | None:
    return f"{due_date}T00:00:00.000Z" if due_date else None


def due_from_google(text: str | None) -> str | None:
    return text[:10] if text else None


def remote_fields(item: dict) -> dict:
    return {"title": item.get("title", "") or "", "notes": item.get("notes", "") or "",
            "done": item.get("status") == "completed", "due_date": due_from_google(item.get("due"))}


def position_of(item: dict) -> float:
    """Position Google (« 00000000000000000003 », ordre lexical) -> nombre local du même ordre."""
    text = item.get("position") or ""
    return float(int(text)) if text.isdigit() else 0.0


def snapshot(item: dict, list_id: str, parent_local: str | None, position: float) -> dict:
    base = remote_fields(item)
    base.update(_list=list_id, _parent=parent_local, _pos=position)
    return base


def body_for(task, fields=SYNCED) -> dict:
    """Corps JSON des champs demandés (création : tous)."""
    body: dict = {}
    if "title" in fields:
        body["title"] = task.title
    if "notes" in fields:
        body["notes"] = task.notes
    if "done" in fields:
        body["status"] = "completed" if task.done else "needsAction"
        body["completed"] = rfc3339(task.completed_at) if task.done and task.completed_at else None
    if "due_date" in fields:
        body["due"] = due_to_google(task.due_date)
    return body


def changed_fields(task, base: dict | None) -> set:
    if not base:
        return set(SYNCED)
    return {f for f in SYNCED if getattr(task, f) != base.get(f)}


def moved(task, base: dict | None) -> bool:
    return bool(base) and (task.parent_id != base.get("_parent") or task.position != base.get("_pos"))
