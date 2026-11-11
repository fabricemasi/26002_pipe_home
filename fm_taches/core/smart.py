"""Vues intelligentes (comme Apple Rappels) : Aujourd'hui (en retard compris), En retard, Planifiées, Marquées,
Toutes, Terminées. Fonctions pures sur les tâches en mémoire ; le service met le résultat en cache jusqu'à la
modification suivante (jamais recalculé à la peinture)."""
from __future__ import annotations

from datetime import date

VIEWS = ("today", "overdue", "planned", "flagged", "all", "done")
LABELS = {"today": "Aujourd'hui", "overdue": "En retard", "planned": "Planifiées", "flagged": "Marquées",
          "all": "Toutes", "done": "Terminées"}


def _due_key(t) -> tuple:
    return (t.due_date or "9999-99-99", t.due_time or "99:99", -t.priority, t.position, t.id)


def select(view: str, tasks, today: date) -> list:
    iso = today.isoformat()
    if view == "today":
        out = [t for t in tasks if not t.done and t.due_date and t.due_date <= iso]
    elif view == "overdue":
        out = [t for t in tasks if not t.done and t.due_date and t.due_date < iso]
    elif view == "planned":
        out = [t for t in tasks if not t.done and t.due_date]
    elif view == "flagged":
        out = [t for t in tasks if not t.done and t.flagged]
    elif view == "all":
        out = [t for t in tasks if not t.done]
    elif view == "done":
        return sorted((t for t in tasks if t.done), key=lambda t: (-(t.completed_at or 0), t.id))
    else:
        raise ValueError(f"vue inconnue : {view}")
    out.sort(key=_due_key)
    return out
