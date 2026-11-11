"""Modèle des tâches : `TaskList` et `TaskRecord`, sur-ensemble de Google Tasks et d'Apple Rappels.

Un champ que la source distante ignore (heure d'échéance pour Google, sous-tâches pour Apple…) reste local et n'est
jamais effacé par une synchronisation ; ce qu'une source apporte sans équivalent ici va dans `props`.

Dates : `due_date` = « AAAA-MM-JJ » (date murale, sans fuseau : une tâche « pour mardi » reste mardi en voyage),
`due_time` = « HH:MM » facultatif ; horodatages (`completed_at`, `reminder_at`, `created_at`, `updated_at`) en
secondes epoch."""
from __future__ import annotations

import copy
import uuid
from dataclasses import dataclass, field
from datetime import date

PRIORITIES = (0, 1, 2, 3)               # aucune, basse, moyenne, haute (Apple : 0 / 9 / 5 / 1)
SOURCE_LOCAL = "local"
SOURCE_APPLE = "apple"


def new_id() -> str:
    return uuid.uuid4().hex


def google_source(email: str) -> str:
    return f"google:{email}"


@dataclass
class TaskList:
    id: str
    name: str
    color: str = "bleu"
    source: str = SOURCE_LOCAL          # "local", "google:<compte>", "apple"
    account_id: str | None = None
    remote_id: str | None = None
    etag: str | None = None
    sync_enabled: bool = False
    sort_order: int = 0
    props: dict = field(default_factory=dict)
    deleted: bool = False
    created_at: int = 0
    updated_at: int = 0

    @property
    def synced(self) -> bool:
        return self.sync_enabled and self.source != SOURCE_LOCAL

    @property
    def is_google(self) -> bool:
        return self.source.startswith("google:")

    def copy(self) -> "TaskList":
        return copy.deepcopy(self)


@dataclass
class TaskRecord:
    id: str
    list_id: str
    title: str = ""
    notes: str = ""
    parent_id: str | None = None
    position: float = 0.0
    done: bool = False
    completed_at: int | None = None
    due_date: str | None = None         # "AAAA-MM-JJ"
    due_time: str | None = None         # "HH:MM" (local : Google n'a que la date)
    reminder_at: int | None = None
    priority: int = 0
    flagged: bool = False
    url: str = ""
    remote_id: str | None = None
    etag: str | None = None
    version: int = 1
    created_at: int = 0
    updated_at: int = 0
    sync_state: str = "local"           # local, synced, dirty, deleted, conflict
    base: dict | None = None            # dernière version reçue (fusion à trois voies)
    origin: str = ""
    deleted: bool = False
    props: dict = field(default_factory=dict)

    def copy(self) -> "TaskRecord":
        return copy.deepcopy(self)

    @property
    def due(self) -> date | None:
        if not self.due_date:
            return None
        try:
            return date.fromisoformat(self.due_date)
        except ValueError:
            return None

    def validate(self) -> list[str]:
        errors = []
        if not self.id:
            errors.append("identifiant manquant")
        if not self.list_id:
            errors.append("liste manquante")
        if self.parent_id == self.id:
            errors.append("une tâche ne peut pas être sa propre sous-tâche")
        if self.priority not in PRIORITIES:
            errors.append("priorité invalide")
        if self.due_date is not None and self.due is None:
            errors.append("échéance invalide")
        if self.due_time is not None:
            if not self.due_date:
                errors.append("heure sans date d'échéance")
            parts = self.due_time.split(":")
            if len(parts) != 2 or not all(p.isdigit() for p in parts) or int(parts[0]) > 23 or int(parts[1]) > 59:
                errors.append("heure d'échéance invalide")
        return errors
