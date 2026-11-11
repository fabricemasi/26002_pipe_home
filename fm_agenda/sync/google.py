"""Google Calendar API v3 : client REST (`GoogleProvider`) et correspondance des champs Google <-> agenda.

Client : jeton d'accès de `oauth.TokenSource` (401 -> actualisation puis un nouvel essai), reprises avec attente
exponentielle + aléa pour 429 / 5xx / `rateLimitExceeded` / réseau coupé (en-tête Retry-After respecté), erreurs
typées (`provider`). Invitations : `sendUpdates=none` (la synchronisation n'envoie jamais de courriel).

Correspondance : dates (`dateTime` + `timeZone`, ou `date` pour la journée), récurrence (RRULE + EXDATE),
exceptions (`recurringEventId` + `originalStartTime`, identifiant d'occurrence = `<maître>_<YYYYMMDDTHHMMSSZ>`),
rappels (`useDefault` / `overrides`), disponibilité, statut, participants, couleur (`colorId` <-> couleurs de
l'agenda), champs propres à PIPE FMZ (projet, dossier, notes, lien, tâche, catégories) dans
`extendedProperties.private` (invisibles dans Google, conservés)."""
from __future__ import annotations

import json
import random
import time
import urllib.parse
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone

from ..core import recurrence as rec
from ..core import timeutil as tu
from ..core.model import Attendee
from .provider import (AuthError, ChangePage, ConflictError, ForbiddenError, GoneError, NotFoundError,
                       PreconditionFailed, RemoteCalendar, RemoteProvider, SyncError, TransientError)

API = "https://www.googleapis.com/calendar/v3"
RATE_REASONS = {"rateLimitExceeded", "userRateLimitExceeded", "quotaExceeded"}

# Couleurs d'événement Google (colorId) <-> couleurs nommées de l'agenda.
TO_GOOGLE_COLOR = {"bleu": "9", "violet": "1", "orange": "6", "vert": "10", "rouge": "11", "cyan": "7", "rose": "4",
                   "gris": "8"}
FROM_GOOGLE_COLOR = {"1": "violet", "2": "vert", "3": "violet", "4": "rose", "5": "orange", "6": "orange",
                     "7": "cyan", "8": "gris", "9": "bleu", "10": "vert", "11": "rouge"}
PRIVATE = {"project": "pipeProject", "folder": "pipeFolder", "notes": "pipeNotes", "url": "pipeUrl",
           "is_task": "pipeTask", "done": "pipeDone", "categories": "pipeCategories"}
# Champ de l'agenda -> clés du corps Google qu'il touche (PATCH minimal : seuls les champs modifiés partent).
FIELD_KEYS = {"title": ("summary",), "description": ("description",), "location": ("location",),
              "start": ("start", "end"), "end": ("start", "end"), "all_day": ("start", "end"),
              "start_date": ("start", "end"), "end_date": ("start", "end"), "tzid": ("start", "end"),
              "rrule": ("recurrence",), "exdates": ("recurrence",), "reminders": ("reminders",),
              "reminders_default": ("reminders",), "color": ("colorId", "extendedProperties"),
              "transparency": ("transparency",),
              "status": ("status",), "attendees": ("attendees",), "project": ("extendedProperties",),
              "folder": ("extendedProperties",), "notes": ("extendedProperties",), "url": ("extendedProperties",),
              "is_task": ("extendedProperties",), "done": ("extendedProperties",),
              "categories": ("extendedProperties",)}


@dataclass
class RemoteEvent:
    remote_id: str
    etag: str = ""
    cancelled: bool = False
    master_remote_id: str | None = None
    rid: str | None = None
    ical_uid: str | None = None
    sequence: int = 0
    fields: dict = field(default_factory=dict)       # champs de contenu (types de EventRecord)


def parse_rfc3339(text: str) -> datetime:
    text = text.strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    return datetime.fromisoformat(text)


def instance_id(master_remote_id: str, rid: str) -> str:
    return f"{master_remote_id}_{rid}"


class GoogleProvider(RemoteProvider):
    name = "google"
    api = API                                            # racine de l'API (fm_taches : Google Tasks)

    def __init__(self, tokens, http, sleep=time.sleep, max_retries: int = 4):
        self.tokens = tokens
        self.http = http
        self.sleep = sleep
        self.max_retries = max_retries
        self.requests = 0                                # compteur (quotas, tests)

    # -- HTTP --

    def _call(self, method: str, path: str, params: dict | None = None, body: dict | None = None,
              headers: dict | None = None) -> dict:
        url = self.api + path + ("?" + urllib.parse.urlencode(params, doseq=True) if params else "")
        data = json.dumps(body).encode("utf-8") if body is not None else None
        refreshed = False
        attempt = 0
        while True:
            h = {"Authorization": "Bearer " + self.tokens.access_token(), "Accept": "application/json"}
            if data is not None:
                h["Content-Type"] = "application/json; charset=utf-8"
            h.update(headers or {})
            self.requests += 1
            try:
                status, hdrs, raw = self.http.request(method, url, h, data)
            except TransientError:
                if attempt >= self.max_retries:
                    raise
                self._wait(attempt, None)
                attempt += 1
                continue
            payload = {}
            if raw:
                try:
                    payload = json.loads(raw.decode("utf-8"))
                except ValueError:
                    payload = {}
            if 200 <= status < 300:
                return payload
            error = payload.get("error", {}) if isinstance(payload, dict) else {}
            message = error.get("message", "") if isinstance(error, dict) else str(error)
            reasons = {e.get("reason") for e in error.get("errors", [])} if isinstance(error, dict) else set()
            if status == 401:
                if not refreshed:
                    refreshed = True
                    self.tokens.access_token(force=True)
                    continue
                raise AuthError(message or "accès refusé par Google")
            retry_after = _retry_after(hdrs)
            if status in (429, 500, 502, 503, 504) or (status == 403 and reasons & RATE_REASONS):
                if attempt >= self.max_retries:
                    raise TransientError(f"Google indisponible ou quota atteint ({status})", retry_after)
                self._wait(attempt, retry_after)
                attempt += 1
                continue
            if status == 403:
                raise ForbiddenError(message or "droits insuffisants")
            if status == 404:
                raise NotFoundError(message or "introuvable")
            if status == 409:
                raise ConflictError(message or "identifiant déjà pris")
            if status == 410:
                raise GoneError(message or "jeton ou ressource périmé")
            if status == 412:
                raise PreconditionFailed(message or "modifié entre-temps")
            raise SyncError(f"Google : {status} {message}".strip())

    def _wait(self, attempt: int, retry_after: float | None) -> None:
        delay = retry_after if retry_after is not None else min(60.0, 2 ** attempt + random.random())
        self.sleep(delay)

    # -- API --

    def account_email(self) -> str:
        for cal in self.list_calendars():
            if cal.primary:
                return cal.remote_id
        return ""

    def list_calendars(self) -> list[RemoteCalendar]:
        out, page = [], None
        while True:
            params = {"maxResults": 250}
            if page:
                params["pageToken"] = page
            data = self._call("GET", "/users/me/calendarList", params)
            for item in data.get("items", []):
                if item.get("deleted"):
                    continue
                out.append(RemoteCalendar(
                    remote_id=item["id"], name=item.get("summaryOverride") or item.get("summary", item["id"]),
                    color=item.get("backgroundColor", ""), access_role=item.get("accessRole", "reader"),
                    primary=bool(item.get("primary")), timezone=item.get("timeZone", ""),
                    default_reminders=[int(r.get("minutes", 0)) for r in item.get("defaultReminders", [])]))
            page = data.get("nextPageToken")
            if not page:
                return out

    def list_changes(self, calendar_remote_id: str, sync_token: str | None, page_token: str | None,
                     time_min: str | None = None) -> ChangePage:
        params = {"maxResults": 250, "singleEvents": "false", "showDeleted": "true"}
        if sync_token:
            params["syncToken"] = sync_token
        elif time_min:
            params["timeMin"] = time_min
        if page_token:
            params["pageToken"] = page_token
        data = self._call("GET", f"/calendars/{_q(calendar_remote_id)}/events", params)
        return ChangePage(data.get("items", []), data.get("nextPageToken"), data.get("nextSyncToken"))

    def get(self, calendar_remote_id: str, remote_id: str) -> dict:
        return self._call("GET", f"/calendars/{_q(calendar_remote_id)}/events/{_q(remote_id)}")

    def insert(self, calendar_remote_id: str, body: dict) -> dict:
        return self._call("POST", f"/calendars/{_q(calendar_remote_id)}/events", {"sendUpdates": "none"}, body)

    def update_instance(self, calendar_remote_id: str, remote_id: str, body: dict) -> dict:
        return self._call("PATCH", f"/calendars/{_q(calendar_remote_id)}/events/{_q(remote_id)}",
                          {"sendUpdates": "none"}, body)

    def patch(self, calendar_remote_id: str, remote_id: str, body: dict, etag: str | None) -> dict:
        return self._call("PATCH", f"/calendars/{_q(calendar_remote_id)}/events/{_q(remote_id)}",
                          {"sendUpdates": "none"}, body, {"If-Match": etag} if etag else None)

    def delete(self, calendar_remote_id: str, remote_id: str, etag: str | None) -> None:
        self._call("DELETE", f"/calendars/{_q(calendar_remote_id)}/events/{_q(remote_id)}", {"sendUpdates": "none"},
                   None, {"If-Match": etag} if etag else None)

    # -- correspondance --

    def to_record(self, item: dict, default_tz: str) -> RemoteEvent:
        return to_record(item, default_tz)

    def to_body(self, record, fields=None, master_remote_id=None, master_tz=None) -> dict:
        return to_body(record, fields, master_remote_id)


def _q(value: str) -> str:
    return urllib.parse.quote(value, safe="")


def _retry_after(headers: dict) -> float | None:
    value = (headers or {}).get("retry-after")
    try:
        return float(value) if value is not None else None
    except ValueError:
        return None


def _parse_time(obj: dict, default_tz: str):
    if "date" in obj:
        return tu.parse_date(obj["date"]), None
    dt = parse_rfc3339(obj["dateTime"])
    tzid = obj.get("timeZone") or default_tz
    if dt.tzinfo is None:
        dt = tu.localize(dt, tu.get_tz(tzid))
    return dt.astimezone(tu.get_tz(tzid)), tzid


def _exdates(lines: list[str], tzid: str, all_day: bool) -> list[str]:
    from ..core import ics
    out = []
    for line in lines:
        if not line.upper().startswith("EXDATE"):
            continue
        prop = ics.parse_line(line)
        for value in prop.value.split(","):
            d = ics.parse_dt(ics.Prop("EXDATE", prop.params, value), tu.get_tz(tzid))
            out.append(tu.rid_for_date(d) if isinstance(d, date) and not isinstance(d, datetime)
                       else tu.rid_for_datetime(d))
    return out


def to_record(item: dict, default_tz: str) -> RemoteEvent:
    ev = RemoteEvent(remote_id=item["id"], etag=item.get("etag", ""), cancelled=item.get("status") == "cancelled",
                     master_remote_id=item.get("recurringEventId"), ical_uid=item.get("iCalUID"),
                     sequence=int(item.get("sequence", 0) or 0))
    original = item.get("originalStartTime")
    if original:
        value, _tz = _parse_time(original, default_tz)
        ev.rid = tu.rid_for_date(value) if isinstance(value, date) and not isinstance(value, datetime) else \
            tu.rid_for_datetime(value)
    if ev.cancelled and "start" not in item:
        return ev
    f = ev.fields
    start, tzid = _parse_time(item["start"], default_tz)
    end, _tz = _parse_time(item.get("end", item["start"]), default_tz)
    if isinstance(start, date) and not isinstance(start, datetime):
        f.update(all_day=True, start_date=start, end_date=end if end > start else start + timedelta(days=1),
                 start=None, end=None, tzid=default_tz)
    else:
        f.update(all_day=False, start=start, end=end if end >= start else start, start_date=None, end_date=None,
                 tzid=tzid or default_tz)
    f["title"] = item.get("summary", "")
    f["description"] = item.get("description", "")
    f["location"] = item.get("location", "")
    lines = item.get("recurrence") or []
    rule = next((line[6:] for line in lines if line.upper().startswith("RRULE:")), None)
    if rule:
        parsed = rec.parse_rrule(rule)
        if parsed.until and not f["all_day"] and not parsed.until.endswith("Z"):
            if "T" in parsed.until:
                local = datetime.strptime(parsed.until, "%Y%m%dT%H%M%S")
            else:
                local = datetime.combine(tu.parse_date(parsed.until), datetime.max.time().replace(microsecond=0))
            parsed.until = tu.rid_for_datetime(tu.localize(local, tu.get_tz(f["tzid"])))
        rule = rec.format_rrule(parsed)
    f["rrule"] = rule
    f["exdates"] = sorted(set(_exdates(lines, f["tzid"], f["all_day"])))
    reminders = item.get("reminders") or {}
    f["reminders_default"] = bool(reminders.get("useDefault", False))
    f["reminders"] = sorted({int(o.get("minutes", 0)) for o in reminders.get("overrides", [])})
    f["transparency"] = item.get("transparency", "opaque")
    f["status"] = item.get("status", "confirmed") if item.get("status") in ("confirmed", "tentative") else "confirmed"
    f["attendees"] = [Attendee(email=a.get("email", ""), name=a.get("displayName", ""),
                               status=a.get("responseStatus", "needsAction"), optional=bool(a.get("optional")),
                               organizer=bool(a.get("organizer")), is_self=bool(a.get("self")))
                      for a in item.get("attendees", []) if a.get("email")]
    private = (item.get("extendedProperties") or {}).get("private") or {}
    color = private.get("pipeColor") or FROM_GOOGLE_COLOR.get(str(item.get("colorId", "")), None)
    f["color"] = color
    f["project"] = private.get("pipeProject", "")
    f["folder"] = private.get("pipeFolder", "")
    f["notes"] = private.get("pipeNotes", "")
    f["url"] = private.get("pipeUrl", "")
    f["is_task"] = private.get("pipeTask") == "1"
    f["done"] = private.get("pipeDone") == "1"
    f["categories"] = [c for c in private.get("pipeCategories", "").split("\n") if c]
    return ev


def _time_obj(value, tzid: str, all_day: bool) -> dict:
    if all_day:
        return {"date": value.isoformat()}
    return {"dateTime": value.astimezone(tu.get_tz(tzid)).isoformat(), "timeZone": tzid}


def to_body(record, fields: set[str] | None = None, master_remote_id: str | None = None) -> dict:
    """Corps Google d'un événement : complet (`fields` None) ou seulement les clés touchées par `fields`."""
    keys = None
    if fields is not None:
        keys = {k for name in fields for k in FIELD_KEYS.get(name, ())}
    want = (lambda key: keys is None or key in keys)  # noqa: E731
    body: dict = {}
    if want("summary"):
        body["summary"] = record.title
    if want("description"):
        body["description"] = record.description
    if want("location"):
        body["location"] = record.location
    if want("start"):
        tzid = record.tzid or "UTC"
        if record.all_day:
            body["start"] = _time_obj(record.start_date, tzid, True)
            body["end"] = _time_obj(record.end_date, tzid, True)
        else:
            body["start"] = _time_obj(record.start, tzid, False)
            body["end"] = _time_obj(record.end, tzid, False)
    if want("recurrence") and not record.series_id:
        lines = []
        if record.rrule:
            lines.append("RRULE:" + record.rrule)
            for x in sorted(record.exdates):
                lines.append(f"EXDATE;VALUE=DATE:{x}" if "T" not in x else f"EXDATE:{x}")
        body["recurrence"] = lines
    if want("reminders"):
        body["reminders"] = {"useDefault": bool(record.reminders_default),
                             "overrides": [] if record.reminders_default else
                             [{"method": "popup", "minutes": int(m)} for m in sorted(set(record.reminders))][:5]}
    if want("colorId"):
        body["colorId"] = TO_GOOGLE_COLOR.get(record.color) if record.color in TO_GOOGLE_COLOR else None
    if want("transparency"):
        body["transparency"] = record.transparency
    if want("status"):
        body["status"] = record.status if record.status in ("confirmed", "tentative") else "confirmed"
    if want("attendees"):
        body["attendees"] = [{k: v for k, v in (("email", a.email), ("displayName", a.name or None),
                                                ("responseStatus", a.status), ("optional", a.optional or None))
                              if v is not None} for a in record.attendees]
    if want("extendedProperties"):
        private = {PRIVATE["project"]: record.project, PRIVATE["folder"]: record.folder,
                   PRIVATE["notes"]: record.notes, PRIVATE["url"]: record.url,
                   PRIVATE["is_task"]: "1" if record.is_task else "0", PRIVATE["done"]: "1" if record.done else "0",
                   PRIVATE["categories"]: "\n".join(record.categories), "pipeColor": record.color or ""}
        body["extendedProperties"] = {"private": private}
    return body
