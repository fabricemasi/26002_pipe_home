"""Saisie rapide d'une tâche : « Appeler Paul demain 14h #Studio !! * » -> titre, échéance, heure, liste,
priorité, marquée. Ce qui est reconnu est retiré du titre ; le reste du texte reste tel quel.

- Date : « aujourd'hui », « auj », « demain », « après-demain », un jour de la semaine (« lundi » = le prochain,
  jamais aujourd'hui), « dans 3 jours » / « dans 2 semaines », « 12/11 », « 12/11/2026 », « 2026-11-12 »,
  « 12 nov » ; « le » devant une date est retiré.
- Heure : « 14h », « 14h30 », « 9:30 » (un nombre seul n'est JAMAIS une heure : « Plan 12 » reste un titre) ;
  « à » devant l'heure est retiré. Une heure sans date = aujourd'hui.
- Liste : « #Studio » (début du nom, sans les accents ni la casse ; « _ » = espace).
- Priorité : « ! » basse, « !! » moyenne, « !!! » haute. Marquée : « * »."""
from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from datetime import date, timedelta

from fm_agenda.core.timeutil import DAYS_LONG, parse_user_date, parse_user_time

_TIME = re.compile(r"^\d{1,2}(h\d{0,2}|:\d{2})$", re.IGNORECASE)
_DATE_NUM = re.compile(r"^(\d{4}-\d{1,2}-\d{1,2}|\d{1,2}[/.]\d{1,2}([/.]\d{2,4})?)$")
_MONTH_WORDS = ("janv", "fevr", "fev", "mars", "avr", "mai", "juin", "juil", "aout", "sept", "oct", "nov", "dec")


@dataclass
class QuickTask:
    title: str
    due_date: str | None = None
    due_time: str | None = None
    list_id: str | None = None
    priority: int = 0
    flagged: bool = False


def _plain(text: str) -> str:
    text = unicodedata.normalize("NFD", text.casefold())
    return "".join(c for c in text if unicodedata.category(c) != "Mn").replace("’", "'")


def _weekday(word: str) -> int | None:
    for i, name in enumerate(DAYS_LONG):
        if _plain(name) == word:
            return i
    return None


def parse(text: str, lists=(), today: date | None = None) -> QuickTask:
    """`lists` : [(id, nom)] des listes connues (pour « #nom »)."""
    today = today or date.today()
    words = text.split()
    keep = [True] * len(words)
    due: date | None = None
    hm: tuple | None = None
    list_id = None
    priority = 0
    flagged = False

    def drop(*idx):
        for i in idx:
            if 0 <= i < len(words):
                keep[i] = False

    def drop_prefix(i, prefixes):
        if i > 0 and keep[i - 1] and _plain(words[i - 1]) in prefixes:
            keep[i - 1] = False

    i = 0
    while i < len(words):
        raw = words[i]
        w = _plain(raw).strip(",;")
        nxt = _plain(words[i + 1]).strip(",;") if i + 1 < len(words) else ""
        if raw.startswith("#") and len(raw) > 1 and list_id is None:
            wanted = _plain(raw[1:]).replace("_", " ")
            match = next((lid for lid, name in lists if _plain(name) == wanted), None) or \
                next((lid for lid, name in lists if _plain(name).startswith(wanted)), None)
            if match is not None:
                list_id = match
                drop(i)
        elif re.fullmatch(r"!{1,3}", raw):
            priority = len(raw)
            drop(i)
        elif raw == "*":
            flagged = True
            drop(i)
        elif hm is None and _TIME.match(w) and parse_user_time(w) is not None:
            h, m = parse_user_time(w)
            if h < 24:
                hm = (h, m)
                drop(i)
                drop_prefix(i, ("a", "vers"))
        elif due is None and w in ("aujourd'hui", "auj", "aujourdhui"):
            due = today
            drop(i)
        elif due is None and w == "demain":
            due = today + timedelta(days=1)
            drop(i)
        elif due is None and w in ("apres-demain", "apres_demain"):
            due = today + timedelta(days=2)
            drop(i)
        elif due is None and _weekday(w) is not None:
            wd = _weekday(w)
            due = today + timedelta(days=((wd - today.weekday()) % 7) or 7)
            drop(i)
            drop_prefix(i, ("le", "ce", "jusqu'a"))
            if nxt == "prochain":
                drop(i + 1)
                i += 1
        elif due is None and w == "dans" and i + 2 < len(words) and words[i + 1].isdigit():
            unit = _plain(words[i + 2]).strip(",;")
            n = int(words[i + 1])
            if unit in ("jour", "jours", "j"):
                due = today + timedelta(days=n)
            elif unit in ("semaine", "semaines", "sem"):
                due = today + timedelta(weeks=n)
            if due is not None:
                drop(i, i + 1, i + 2)
                i += 2
        elif due is None and _DATE_NUM.match(w):
            parsed = parse_user_date(w, today)
            if parsed is not None:
                due = parsed
                drop(i)
                drop_prefix(i, ("le", "pour", "avant"))
        elif due is None and w.isdigit() and 1 <= int(w) <= 31 and nxt[:4].rstrip(".") and \
                any(nxt.startswith(m) for m in _MONTH_WORDS):
            year = words[i + 2] if i + 2 < len(words) and re.fullmatch(r"\d{4}", words[i + 2]) else ""
            parsed = parse_user_date(f"{w} {words[i + 1]} {year}".strip(), today)
            if parsed is not None:
                due = parsed
                drop(i, i + 1)
                drop_prefix(i, ("le", "pour", "avant"))
                if year:
                    drop(i + 2)
                    i += 1
                i += 1
        i += 1
    if hm is not None and due is None:
        due = today
    title = " ".join(word for word, k in zip(words, keep) if k).strip()
    return QuickTask(title=title or text.strip(), due_date=due.isoformat() if due else None,
                     due_time=f"{hm[0]:02d}:{hm[1]:02d}" if hm else None, list_id=list_id, priority=priority,
                     flagged=flagged)
