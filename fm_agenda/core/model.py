"""Modèle de l'agenda (sans Qt) : calendriers, événements, participants, occurrences affichées.

Identité : chaque calendrier / événement a un identifiant LOCAL stable (`new_id()`, UUID4 en hexadécimal, 32
caractères) indépendant de toute source distante. C'est aussi l'identifiant proposé à Google à la création
(caractères 0-9a-f ⊂ base32hex accepté par l'API) : un envoi répété après une coupure retombe sur le MÊME événement
(HTTP 409), jamais sur un doublon. Les identifiants distants (`remote_id`, `etag`) sont des attributs de
synchronisation, jamais la clé."""
from __future__ import annotations

import copy
import uuid
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta

from . import timeutil as tu

# Couleurs nommées du design (familles fond / barre / texte, thèmes sombre et clair : ui/theme.py). Une couleur
# libre « #rrggbb » (calendrier Google…) est aussi acceptée : ses teintes sont dérivées.
PALETTE = ("bleu", "violet", "orange", "vert", "rouge", "cyan", "rose", "gris")
PALETTE_LABELS = {"bleu": "Bleu", "violet": "Violet", "orange": "Orange", "vert": "Vert", "rouge": "Rouge",
                  "cyan": "Cyan", "rose": "Rose", "gris": "Gris"}

SOURCES = ("local", "google", "server")
ROLES_WRITABLE = ("owner", "writer")
SYNC_STATES = ("local", "clean", "dirty", "deleted", "conflict")
STATUSES = ("confirmed", "tentative", "cancelled")
TRANSPARENCY = ("opaque", "transparent")            # occupé / disponible
ATTENDEE_STATUS = ("needsAction", "accepted", "declined", "tentative")


def new_id() -> str:
    return uuid.uuid4().hex


@dataclass
class Calendar:
    id: str
    name: str
    color: str = "bleu"
    visible: bool = True
    source: str = "local"                 # local | google | server
    account_id: str | None = None
    remote_id: str | None = None
    access_role: str = "owner"            # owner | writer | reader | freeBusyReader
    sync_enabled: bool = False
    description: str = ""
    timezone: str | None = None
    sort_order: int = 0
    props: dict = field(default_factory=dict)
    deleted: bool = False

    @property
    def read_only(self) -> bool:
        return self.access_role not in ROLES_WRITABLE

    @property
    def default_reminders(self) -> list[int]:
        return [int(m) for m in self.props.get("default_reminders", [])]

    @property
    def synced(self) -> bool:
        return self.source != "local" and self.sync_enabled


@dataclass
class Attendee:
    email: str
    name: str = ""
    status: str = "needsAction"
    optional: bool = False
    organizer: bool = False
    is_self: bool = False

    def to_dict(self) -> dict:
        return {"email": self.email, "name": self.name, "status": self.status, "optional": self.optional,
                "organizer": self.organizer, "self": self.is_self}

    @classmethod
    def from_dict(cls, d: dict) -> "Attendee":
        return cls(email=str(d.get("email", "")), name=str(d.get("name", "")),
                   status=str(d.get("status", "needsAction")), optional=bool(d.get("optional")),
                   organizer=bool(d.get("organizer")), is_self=bool(d.get("self")))


# Champs « contenu » d'un événement (modifiables par l'utilisateur, comparés lors d'une fusion à trois voies).
CONTENT_FIELDS = ("calendar_id", "title", "description", "location", "url", "notes", "all_day", "start", "end",
                  "start_date", "end_date", "tzid", "rrule", "exdates", "color", "categories", "transparency",
                  "status", "is_task", "done", "project", "folder", "attendees", "reminders", "reminders_default")


@dataclass
class EventRecord:
    """Un événement tel qu'enregistré : simple, maître d'une série (`rrule`), ou exception d'une série
    (`series_id` + `recurrence_id` = début d'origine de l'occurrence remplacée)."""
    id: str
    calendar_id: str
    title: str = ""
    description: str = ""
    location: str = ""
    url: str = ""
    notes: str = ""
    all_day: bool = False
    start: datetime | None = None          # instant (aware) pour un événement horaire
    end: datetime | None = None
    start_date: date | None = None         # événement « journée » : premier jour (inclus)
    end_date: date | None = None           # … et lendemain du dernier jour (exclu, comme iCalendar)
    tzid: str = ""                         # fuseau IANA du déroulement (récurrences)
    rrule: str | None = None               # « FREQ=WEEKLY;BYDAY=MO » (RFC 5545, sans « RRULE: »)
    exdates: list[str] = field(default_factory=list)   # occurrences supprimées (identifiants d'occurrence)
    series_id: str | None = None
    recurrence_id: str | None = None
    color: str | None = None               # None = couleur du calendrier
    categories: list[str] = field(default_factory=list)
    transparency: str = "opaque"
    status: str = "confirmed"
    is_task: bool = False
    done: bool = False
    project: str = ""
    folder: str = ""
    attendees: list[Attendee] = field(default_factory=list)
    reminders: list[int] = field(default_factory=list)  # minutes avant le début
    reminders_default: bool = False        # vrai : rappels par défaut du calendrier
    ical_uid: str | None = None
    remote_id: str | None = None
    etag: str | None = None
    sequence: int = 0
    version: int = 1
    created_at: int = 0
    updated_at: int = 0
    sync_state: str = "local"
    origin: str = ""
    deleted: bool = False
    extra: dict = field(default_factory=dict)

    # -- temps --

    @property
    def tz(self):
        return tu.get_tz(self.tzid)

    @property
    def start_ts(self) -> int:
        if self.all_day:
            return tu.date_to_ord_ts(self.start_date)
        return tu.to_ts(self.start)

    @property
    def end_ts(self) -> int:
        if self.all_day:
            return tu.date_to_ord_ts(self.end_date)
        return tu.to_ts(self.end)

    @property
    def duration(self) -> timedelta:
        if self.all_day:
            return self.end_date - self.start_date
        return self.end - self.start

    @property
    def is_master(self) -> bool:
        return bool(self.rrule) and not self.series_id

    @property
    def is_override(self) -> bool:
        return bool(self.series_id)

    def copy(self) -> "EventRecord":
        return copy.deepcopy(self)

    def content(self) -> dict:
        """Champs de contenu comparables (fusion, détection d'un changement)."""
        out = {}
        for name in CONTENT_FIELDS:
            value = getattr(self, name)
            if name == "attendees":
                value = sorted((a.to_dict() for a in value), key=lambda d: d["email"])
            elif isinstance(value, datetime):
                value = tu.to_ts(value)
            elif isinstance(value, date):
                value = value.isoformat()
            elif isinstance(value, list):
                value = list(value)
            out[name] = value
        return out

    def validate(self) -> list[str]:
        errors = []
        if self.all_day:
            if self.start_date is None or self.end_date is None:
                errors.append("dates manquantes")
            elif self.end_date <= self.start_date:
                errors.append("la fin doit suivre le début")
        else:
            if self.start is None or self.end is None:
                errors.append("heures manquantes")
            elif self.start.tzinfo is None or self.end.tzinfo is None:
                errors.append("heure sans fuseau")
            elif self.end <= self.start and not self.is_task:
                errors.append("la fin doit suivre le début")
        if not self.calendar_id:
            errors.append("calendrier manquant")
        if self.status not in STATUSES:
            errors.append("statut inconnu")
        if any(int(m) < 0 for m in self.reminders):
            errors.append("rappel négatif")
        return errors


class Occurrence:
    """Une occurrence AFFICHÉE (événement simple, ou une date d'une série), dans le fuseau d'affichage. Légère
    (`__slots__`) : une vue Année en manipule des milliers."""
    __slots__ = ("key", "event_id", "series_id", "recurrence_id", "calendar_id", "title", "start", "end", "all_day",
                 "start_date", "end_date", "color", "location", "is_task", "done", "project", "folder", "has_note",
                 "recurring", "read_only", "status", "transparency", "description", "categories")

    def __init__(self, rec: EventRecord, start: datetime, end: datetime, start_date: date | None,
                 end_date: date | None, rid: str | None, series_id: str | None, read_only: bool = False):
        self.key = rec.id if rid is None else f"{series_id or rec.id}@{rid}"
        self.event_id = rec.id
        self.series_id = series_id
        self.recurrence_id = rid
        self.calendar_id = rec.calendar_id
        self.title = rec.title
        self.start = start
        self.end = end
        self.all_day = rec.all_day
        self.start_date = start_date
        self.end_date = end_date
        self.color = rec.color
        self.location = rec.location
        self.is_task = rec.is_task
        self.done = rec.done
        self.project = rec.project
        self.folder = rec.folder
        self.has_note = bool(rec.notes or rec.description)
        self.recurring = series_id is not None
        self.read_only = read_only
        self.status = rec.status
        self.transparency = rec.transparency
        self.description = rec.description
        self.categories = rec.categories

    def days(self) -> list[date]:
        """Jours d'affichage couverts (fin exclue ; un événement horaire finissant à minuit n'occupe pas le
        lendemain)."""
        if self.all_day:
            first, last = self.start_date, self.end_date - timedelta(days=1)
        else:
            first = self.start.date()
            end = self.end - timedelta(microseconds=1) if self.end > self.start else self.end
            last = end.date()
        out, d = [], first
        while d <= last:
            out.append(d)
            d += timedelta(days=1)
        return out

    def spans_days(self) -> bool:
        """Barre « journée » des vues Semaine / Mois : événement journée, ou horaire de plus de 24 h."""
        return self.all_day or (self.end - self.start) >= timedelta(hours=24)

    def __repr__(self):
        return f"Occurrence({self.title!r}, {self.start}, {self.key})"
