"""Thème du module Tâches : celui de l'agenda (`fm_agenda/ui/theme.py`, jetons du design, sombre relu dans la
palette `M` de fm_theme), réglé par les clés `taches_*`, plus les métriques propres à la liste des tâches. Changer
l'aspect des tâches = ce fichier (métriques) ou le thème de l'agenda (couleurs), jamais le panneau."""
from __future__ import annotations

from datetime import date, timedelta

from fm_agenda.core import timeutil as tu
from fm_agenda.ui import theme as ath
from fm_agenda.ui.theme import font, metrics, with_alpha  # noqa: F401

ROW_H = {"compacte": 34, "normal": 42, "confortable": 50}
INDENT = 22
CHECK = 16
SIDE_ROW_H = 30
PRIORITY_MARKS = {1: "!", 2: "!!", 3: "!!!"}
PRIORITY_LABELS = ("Aucune", "Basse", "Moyenne", "Haute")
LIST_COLORS = ("bleu", "violet", "orange", "vert", "rouge", "cyan", "rose", "gris")
LIST_COLOR_LABELS = {"bleu": "Bleu", "violet": "Violet", "orange": "Orange", "vert": "Vert", "rouge": "Rouge",
                     "cyan": "Cyan", "rose": "Rose", "gris": "Gris"}


def from_settings(settings: dict) -> ath.AgendaTheme:
    t = ath.AgendaTheme(settings.get("taches_theme") or "sombre", settings.get("taches_accent") or None, None,
                        settings.get("taches_density") or "normal")
    t.m["row_h"] = ROW_H.get(t.density, ROW_H["normal"])
    return t


def due_text(due_date: str | None, due_time: str | None, today: date) -> tuple[str, str]:
    """(texte, état) d'une échéance : état = « late », « today », « soon » ou « later »."""
    if not due_date:
        return "", ""
    try:
        d = date.fromisoformat(due_date)
    except ValueError:
        return due_date, "later"
    delta = (d - today).days
    if delta == 0:
        text, state = "Aujourd'hui", "today"
    elif delta == 1:
        text, state = "Demain", "soon"
    elif delta == -1:
        text, state = "Hier", "late"
    elif 1 < delta < 7:
        text, state = tu.cap(tu.DAYS_LONG[d.weekday()]), "soon"
    else:
        text = f"{d.day} {tu.MONTHS_SHORT[d.month - 1]}" + ("" if d.year == today.year else f" {d.year}")
        state = "late" if delta < 0 else "later"
    if due_time:
        text += f" · {due_time}"
    return text, state


def next_weekday(today: date, weekday: int) -> date:
    return today + timedelta(days=((weekday - today.weekday()) % 7) or 7)
