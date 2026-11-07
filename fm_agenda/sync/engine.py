"""Moteur de synchronisation (sans Qt, fil de synchronisation) entre la base locale et UNE source distante.

Ordre d'un passage, par calendrier activé : RÉCEPTION puis ENVOI.

Réception (`pull`) : changements depuis le jeton de synchronisation incrémentale (`syncToken`), page par page,
chaque page dans UNE transaction. Sans jeton : synchronisation complète (fenêtre `PAST_DAYS` dans le passé), puis
suppression locale des copies PROPRES disparues de la source — jamais d'une ligne modifiée localement. Jeton
périmé (HTTP 410) : jeton oublié, synchronisation complète.

Correspondance : identifiant distant (`remote_id`, par calendrier) — l'identifiant local reste un UUID ; un
événement créé ici part sous SON identifiant local (accepté par Google), d'où l'idempotence : un envoi répété après
une coupure reçoit 409, l'événement existant est relu, jamais dupliqué. Une ligne reçue dont l'etag est celui déjà
connu (écho de notre propre envoi) est ignorée.

Conflits : la ligne locale modifiée (dirty) ET changée à distance est fusionnée à TROIS voies (base = dernière
version synchronisée) par groupes de champs (horaire, récurrence, titre…). Changé d'un seul côté : ce côté gagne.
Changé des deux côtés différemment : politique `agenda_conflict_policy` — « ask » (défaut) garde la version locale,
enregistre les deux versions (`conflicts`) et bloque l'envoi jusqu'à la résolution ; « remote » / « local » :
le côté choisi gagne. Rien n'est jamais perdu : les deux versions restent dans `conflicts`.

Provenance : une modification reçue est écrite avec `origin = "<source>:<compte>"` et n'est JAMAIS remise dans la
file d'envoi (pas de boucle Google -> PIPE FMZ -> Google) ; le journal `changes` garde l'origine de chaque
modification pour le futur serveur personnel."""
from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone

from ..core import timeutil as tu
from ..core.model import Attendee, Calendar, EventRecord, new_id
from ..store.database import transaction
from ..store.repository import Repository, now_ts
from .provider import (AuthError, ConflictError, ForbiddenError, GoneError, NotFoundError, PreconditionFailed,
                       RemoteProvider, SyncError, TransientError)

log = logging.getLogger("fm_agenda.sync")

PAST_DAYS = 730
GROUPS = {"when": ("all_day", "start", "end", "start_date", "end_date", "tzid"), "recurrence": ("rrule", "exdates")}
for _name in ("title", "description", "location", "url", "notes", "color", "categories", "transparency", "status",
              "is_task", "done", "project", "folder", "attendees", "reminders", "reminders_default"):
    GROUPS[_name] = (_name,)
GROUP_LABELS = {"when": "date et heure", "recurrence": "répétition", "title": "titre", "description": "description",
                "location": "lieu", "url": "lien", "notes": "notes", "color": "couleur", "categories": "catégories",
                "transparency": "disponibilité", "status": "statut", "is_task": "tâche", "done": "faite",
                "project": "projet", "folder": "dossier", "attendees": "participants", "reminders": "rappels",
                "reminders_default": "rappels par défaut"}


@dataclass
class SyncReport:
    created: int = 0
    updated: int = 0
    deleted: int = 0
    pushed: int = 0
    conflicts: int = 0
    resyncs: int = 0
    calendars: int = 0
    errors: list[str] = field(default_factory=list)

    @property
    def remote_changed(self) -> bool:
        return bool(self.created or self.updated or self.deleted or self.conflicts or self.calendars)

    def summary(self) -> str:
        parts = []
        for count, word in ((self.created, "reçu(s)"), (self.updated, "mis à jour"), (self.deleted, "supprimé(s)"),
                            (self.pushed, "envoyé(s)"), (self.conflicts, "conflit(s)")):
            if count:
                parts.append(f"{count} {word}")
        return ", ".join(parts) or "à jour"


def content_of(rec: EventRecord) -> dict:
    c = rec.content()
    c.pop("calendar_id", None)
    return c


def apply_content(rec: EventRecord, content: dict) -> EventRecord:
    """Contenu normalisé (`EventRecord.content`) recopié dans un enregistrement."""
    rec.all_day = bool(content.get("all_day"))
    rec.tzid = content.get("tzid") or rec.tzid
    tz = tu.get_tz(rec.tzid)
    if rec.all_day:
        rec.start_date = date.fromisoformat(content["start_date"])
        rec.end_date = date.fromisoformat(content["end_date"])
        rec.start = rec.end = None
    else:
        rec.start = tu.from_ts(content["start"], tz)
        rec.end = tu.from_ts(content["end"], tz)
        rec.start_date = rec.end_date = None
    for name in ("title", "description", "location", "url", "notes", "rrule", "color", "transparency", "status",
                 "project", "folder"):
        if name in content:
            setattr(rec, name, content[name])
    rec.exdates = list(content.get("exdates") or [])
    rec.categories = list(content.get("categories") or [])
    rec.reminders = [int(m) for m in content.get("reminders") or []]
    rec.reminders_default = bool(content.get("reminders_default"))
    rec.is_task = bool(content.get("is_task"))
    rec.done = bool(content.get("done"))
    rec.attendees = [Attendee.from_dict(a) for a in content.get("attendees") or []]
    return rec


def merge3(base: dict | None, local: dict, remote: dict, policy: str) -> tuple[dict, list[str], set[str]]:
    """(contenu fusionné, groupes en conflit, champs modifiés localement par rapport à la version distante)."""
    merged, conflicts = dict(remote), []
    for group, names in GROUPS.items():
        lv = tuple(local.get(n) for n in names)
        rv = tuple(remote.get(n) for n in names)
        if lv == rv:
            continue
        bv = tuple(base.get(n) for n in names) if base is not None else None
        if bv is not None and lv == bv:
            continue                                     # seul le distant a changé
        if bv is not None and rv == bv:
            winner = lv                                  # seul le local a changé
        else:
            conflicts.append(group)
            winner = rv if policy == "remote" else lv
        for n, v in zip(names, winner):
            merged[n] = v
    local_changes = {n for group, names in GROUPS.items() for n in names if merged.get(n) != remote.get(n)}
    return merged, conflicts, local_changes


class SyncEngine:
    def __init__(self, repo: Repository, provider: RemoteProvider, account: dict, policy: str = "ask",
                 clock=time.time):
        self.repo = repo
        self.provider = provider
        self.account = account
        self.account_id = account["id"]
        self.origin = f"{provider.name}:{self.account_id}"
        self.policy = policy if policy in ("ask", "remote", "local") else "ask"
        self.clock = clock

    # -- passage complet --

    def run(self, only_calendar: str | None = None) -> SyncReport:
        report = SyncReport()
        self.sync_calendars(report)
        for cal in self.repo.list_calendars():
            if cal.account_id != self.account_id or not cal.sync_enabled or not cal.remote_id:
                continue
            if only_calendar and cal.id != only_calendar:
                continue
            try:
                self.pull(cal, report)
                cal = self.repo.get_calendar(cal.id) or cal
                if not cal.read_only:
                    self.push(cal, report)
            except (AuthError, TransientError):
                raise
            except SyncError as exc:
                report.errors.append(f"{cal.name} : {exc}")
                log.warning("synchronisation de %s : %s", cal.name, exc)
        return report

    def sync_calendars(self, report: SyncReport) -> None:
        remote = self.provider.list_calendars()
        seen = set()
        with transaction(self.repo.conn):
            known = {c.remote_id: c for c in self.repo.list_calendars(include_deleted=True)
                     if c.account_id == self.account_id}
            order = max((c.sort_order for c in self.repo.list_calendars()), default=0)
            for rc in remote:
                seen.add(rc.remote_id)
                cal = known.get(rc.remote_id)
                if cal is None:
                    order += 1
                    cal = Calendar(id=new_id(), name=rc.name, color=rc.color or "bleu", visible=True, source="google",
                                   account_id=self.account_id, remote_id=rc.remote_id, access_role=rc.access_role,
                                   sync_enabled=rc.access_role != "freeBusyReader", timezone=rc.timezone,
                                   sort_order=order, props={"default_reminders": rc.default_reminders,
                                                            "primary": rc.primary})
                    report.calendars += 1
                else:
                    changed = (cal.name, cal.access_role, cal.timezone, cal.deleted) != (
                        rc.name, rc.access_role, rc.timezone, False)
                    cal.name, cal.access_role, cal.timezone, cal.deleted = rc.name, rc.access_role, rc.timezone, False
                    cal.props = dict(cal.props, default_reminders=rc.default_reminders, primary=rc.primary)
                    cal.props.pop("removed", None)
                    if changed:
                        report.calendars += 1
                self.repo.upsert_calendar(cal)
            for remote_id, cal in known.items():
                if remote_id not in seen and not cal.props.get("removed"):
                    # Calendrier retiré du compte (désabonné, droits retirés) : copies gardées, lecture seule.
                    cal.access_role = "reader"
                    cal.sync_enabled = False
                    cal.props = dict(cal.props, removed=True)
                    self.repo.upsert_calendar(cal)
                    report.calendars += 1

    # -- réception --

    def pull(self, cal: Calendar, report: SyncReport) -> None:
        token = self.repo.sync_token(cal.id)
        try:
            self._pull(cal, token, report)
        except GoneError:
            report.resyncs += 1
            with transaction(self.repo.conn):
                self.repo.set_sync_token(cal.id, None)
            self._pull(cal, None, report)

    def _pull(self, cal: Calendar, token: str | None, report: SyncReport) -> None:
        full = token is None
        time_min_dt = datetime.fromtimestamp(self.clock(), timezone.utc) - timedelta(days=PAST_DAYS)
        time_min = time_min_dt.strftime("%Y-%m-%dT%H:%M:%SZ")
        seen: set[str] = set()
        orphans: list[dict] = []
        page = None
        next_token = None
        default_tz = cal.timezone or tu.system_tz_name()
        while True:
            result = self.provider.list_changes(cal.remote_id, token, page, time_min if full else None)
            with transaction(self.repo.conn):
                for item in result.items:
                    seen.add(item["id"])
                    if not self.apply_remote(cal, item, report, default_tz):
                        orphans.append(item)
            page = result.next_page
            next_token = result.next_sync_token or next_token
            if not page:
                break
        if orphans:
            with transaction(self.repo.conn):
                for item in orphans:
                    if not self.apply_remote(cal, item, report, default_tz):
                        try:
                            master = self.provider.get(cal.remote_id, item["recurringEventId"])
                        except (NotFoundError, GoneError):
                            continue
                        self.apply_remote(cal, master, report, default_tz)
                        self.apply_remote(cal, item, report, default_tz)
        with transaction(self.repo.conn):
            if full:
                self._drop_missing(cal, seen, int(time_min_dt.timestamp()), report)
            if next_token:
                self.repo.set_sync_token(cal.id, next_token)

    def _drop_missing(self, cal: Calendar, seen: set[str], time_min_ts: int, report: SyncReport) -> None:
        """Après une synchronisation complète : copies PROPRES absentes de la source = supprimées à distance."""
        for ev in self.repo.events_of_calendar(cal.id):
            if not ev.remote_id or ev.remote_id in seen or ev.sync_state != "clean":
                continue
            if ev.series_id:
                continue                                  # exceptions : suivent leur maître
            ends = self.repo.conn.execute("SELECT end_ts, until_ts, rrule FROM events WHERE id = ?",
                                          (ev.id,)).fetchone()
            if ends["rrule"] is None and ends["end_ts"] <= time_min_ts:
                continue                                  # hors de la fenêtre listée : rien ne dit qu'il a disparu
            if ends["rrule"] is not None and ends["until_ts"] is not None and ends["until_ts"] <= time_min_ts:
                continue
            self.repo.delete_event(ev.id)
            self.repo.log_change("event", ev.id, "delete", ev.version + 1, self.origin)
            report.deleted += 1

    def _local_for(self, cal: Calendar, remote_id: str) -> EventRecord | None:
        ev = self.repo.event_by_remote(cal.id, remote_id)
        if ev is None:
            row = self.repo.get_event(remote_id)          # créé ici, réponse d'envoi perdue (même identifiant)
            if row is not None and row.calendar_id == cal.id:
                ev = row
        return ev

    def apply_remote(self, cal: Calendar, item: dict, report: SyncReport, default_tz: str) -> bool:
        """Une ligne reçue. False : exception dont le maître n'est pas (encore) connu."""
        remote = self.provider.to_record(item, default_tz)
        local = self._local_for(cal, remote.remote_id)
        master = None
        if remote.master_remote_id:
            master = self._local_for(cal, remote.master_remote_id)
            if master is None:
                return remote.cancelled                   # occurrence annulée d'une série inconnue : rien à faire
            if local is None and remote.rid:
                local = next((o for o in self.repo.overrides_of(master.id, include_deleted=True)
                              if o.recurrence_id == remote.rid), None)
        if remote.cancelled:
            self._remote_cancelled(cal, remote, local, master, report)
            return True
        if local is not None and local.etag and local.etag == remote.etag:
            return True                                   # écho de notre propre envoi : rien de neuf
        incoming = (local.copy() if local is not None else EventRecord(id=new_id(), calendar_id=cal.id))
        for name, value in remote.fields.items():
            setattr(incoming, name, value)
        if master is not None:
            incoming.series_id, incoming.recurrence_id = master.id, remote.rid
            incoming.rrule, incoming.exdates = None, []
        incoming.remote_id, incoming.etag = remote.remote_id, remote.etag
        incoming.ical_uid, incoming.sequence = remote.ical_uid, remote.sequence
        remote_content = content_of(incoming)
        if local is None:
            incoming.version, incoming.created_at, incoming.updated_at = 1, now_ts(), now_ts()
            incoming.sync_state, incoming.origin, incoming.deleted = "clean", self.origin, False
            self.repo.insert_event(incoming)
            self.repo.set_sync_fields(incoming.id, base=remote_content)
            self.repo.log_change("event", incoming.id, "create", 1, self.origin)
            report.created += 1
            return True
        if local.sync_state in ("clean", "local"):
            self._write_remote(incoming, remote_content, "clean", local.version + 1)
            report.updated += 1
            return True
        base = self.repo.get_base(local.id)
        if local.deleted:
            # Supprimé ici, modifié là-bas.
            if self.policy == "remote":
                incoming.deleted = False
                self._write_remote(incoming, remote_content, "clean", local.version + 1)
                self.repo.outbox_done(local.id)
                report.updated += 1
            else:
                self.repo.set_sync_fields(local.id, etag=remote.etag, base=remote_content)
                if self.policy == "ask":
                    self.repo.add_conflict(local.id, cal.id, {"deleted": True, **content_of(local)}, remote_content,
                                           base, ["suppression"])
                    self.repo.set_sync_fields(local.id, sync_state="conflict")
                    report.conflicts += 1
            return True
        merged, conflicts, local_changes = merge3(base, content_of(local), remote_content, self.policy)
        result = apply_content(local.copy(), merged)
        result.remote_id, result.etag, result.ical_uid, result.sequence = (remote.remote_id, remote.etag,
                                                                           remote.ical_uid, remote.sequence)
        if conflicts and self.policy == "ask":
            self._write_remote(result, remote_content, "conflict", local.version + 1)
            self.repo.add_conflict(local.id, cal.id, content_of(local), remote_content, base, conflicts)
            report.conflicts += 1
            return True
        state = "dirty" if local_changes else "clean"
        self._write_remote(result, remote_content, state, local.version + 1)
        if state == "dirty":
            self.repo.enqueue(result.id, cal.id, self.account_id)
        else:
            self.repo.outbox_done(result.id)
        if conflicts:
            report.conflicts += 1
        report.updated += 1
        return True

    def _write_remote(self, rec: EventRecord, base: dict, state: str, version: int) -> None:
        rec.sync_state = state
        rec.version = version
        rec.updated_at = now_ts()
        rec.origin = self.origin
        self.repo.replace_event(rec, base=base, keep_base=False)
        self.repo.log_change("event", rec.id, "update", version, self.origin)

    def _remote_cancelled(self, cal, remote, local, master, report) -> None:
        if master is not None and remote.rid:
            # Occurrence supprimée à distance : exclusion dans le maître (sans toucher son état), exception ôtée.
            if remote.rid not in master.exdates:
                exdates = sorted(set(master.exdates) | {remote.rid})
                from ..store.repository import dumps
                self.repo.set_sync_fields(master.id, exdates=dumps(exdates))
                base = self.repo.get_base(master.id)
                if base is not None:
                    base["exdates"] = sorted(set(base.get("exdates") or []) | {remote.rid})
                    self.repo.set_sync_fields(master.id, base=base)
                report.deleted += 1
            if local is not None:
                self.repo.delete_event(local.id)
            return
        if local is None:
            return
        if local.sync_state in ("dirty", "conflict") and not local.deleted:
            if self.policy == "remote":
                pass
            elif self.policy == "local":
                # Recréé à distance au prochain envoi (PATCH « confirmed » sur l'événement annulé).
                self.repo.set_sync_fields(local.id, etag=None)
                self.repo.enqueue(local.id, cal.id, self.account_id)
                return
            else:
                self.repo.add_conflict(local.id, cal.id, content_of(local), {"deleted": True}, self.repo.get_base(
                    local.id), ["suppression"])
                self.repo.set_sync_fields(local.id, sync_state="conflict", etag=None)
                report.conflicts += 1
                return
        self.repo.delete_event(local.id)
        self.repo.log_change("event", local.id, "delete", local.version + 1, self.origin)
        report.deleted += 1

    # -- envoi --

    def push(self, cal: Calendar, report: SyncReport) -> None:
        now = int(self.clock())
        for entry in self.repo.outbox(self.account_id, due_before=now):
            if entry["calendar_id"] != cal.id:
                continue
            ev = self.repo.get_event(entry["event_id"])
            if ev is None:
                with transaction(self.repo.conn):
                    self.repo.outbox_done(entry["event_id"])
                continue
            if ev.sync_state == "conflict":
                continue
            try:
                self._push_one(cal, ev, report)
            except PreconditionFailed:
                # Changé à distance depuis notre lecture : relu et fusionné, renvoyé au prochain passage.
                try:
                    item = self.provider.get(cal.remote_id, ev.remote_id)
                except (NotFoundError, GoneError):
                    item = None
                with transaction(self.repo.conn):
                    if item is not None:
                        self.apply_remote(cal, item, report, cal.timezone or tu.system_tz_name())
            except ForbiddenError as exc:
                with transaction(self.repo.conn):
                    self.repo.outbox_failed(ev.id, f"refusé par Google (lecture seule ?) : {exc}", now + 6 * 3600)
                report.errors.append(f"« {ev.title} » : refusé par Google ({exc})")
            except NotFoundError:
                with transaction(self.repo.conn):
                    if ev.deleted:
                        self.repo.delete_event(ev.id)
                    else:
                        self.repo.set_sync_fields(ev.id, remote_id=None, etag=None)
            except TransientError as exc:
                with transaction(self.repo.conn):
                    self.repo.outbox_failed(ev.id, str(exc), now + self._backoff(entry["attempts"]))
                raise

    @staticmethod
    def _backoff(attempts: int) -> int:
        return int(min(3600, 30 * (2 ** min(attempts, 7))))

    def _push_one(self, cal: Calendar, ev: EventRecord, report: SyncReport) -> None:
        sent_version = ev.version
        if ev.deleted:
            if ev.remote_id:
                try:
                    self.provider.delete(cal.remote_id, ev.remote_id, ev.etag)
                except (NotFoundError, GoneError):
                    pass
            with transaction(self.repo.conn):
                current = self.repo.get_event(ev.id)
                if current is not None and current.deleted:
                    self.repo.delete_event(ev.id)
                report.pushed += 1
            return
        master_remote = None
        if ev.series_id:
            master = self.repo.get_event(ev.series_id)
            if master is None or master.deleted:
                with transaction(self.repo.conn):
                    self.repo.outbox_done(ev.id)
                return
            if not master.remote_id:
                with transaction(self.repo.conn):           # le maître part d'abord
                    self.repo.outbox_failed(ev.id, "en attente de la série", int(self.clock()) + 5)
                return
            master_remote = master.remote_id
        if ev.remote_id is None:
            if ev.series_id:
                body = self.provider.to_body(ev, None, master_remote, None)
                from .google import instance_id
                response = self.provider.update_instance(cal.remote_id, instance_id(master_remote, ev.recurrence_id),
                                                         body)
            else:
                body = self.provider.to_body(ev, None, None, None)
                body["id"] = ev.id
                try:
                    response = self.provider.insert(cal.remote_id, body)
                except ConflictError:
                    # Déjà créé (réponse perdue lors d'un essai précédent) : le même événement, mis à jour.
                    existing = self.provider.get(cal.remote_id, ev.id)
                    body.pop("id", None)
                    body["status"] = ev.status if ev.status in ("confirmed", "tentative") else "confirmed"
                    response = self.provider.patch(cal.remote_id, ev.id, body, existing.get("etag"))
        else:
            base = self.repo.get_base(ev.id)
            mine = content_of(ev)
            changed = None if base is None else {k for k, v in mine.items() if base.get(k) != v}
            if changed is not None and not changed:
                with transaction(self.repo.conn):
                    current = self.repo.get_event(ev.id)
                    if current is not None and current.version == sent_version:
                        self.repo.set_sync_fields(ev.id, sync_state="clean")
                        self.repo.outbox_done(ev.id)
                return
            body = self.provider.to_body(ev, changed, master_remote, None)
            if ev.etag is None:
                body["status"] = ev.status if ev.status in ("confirmed", "tentative") else "confirmed"
            response = self.provider.patch(cal.remote_id, ev.remote_id, body, ev.etag)
        remote = self.provider.to_record(response, cal.timezone or tu.system_tz_name())
        with transaction(self.repo.conn):
            current = self.repo.get_event(ev.id)
            if current is None:
                return
            snapshot = current.copy()
            for name, value in remote.fields.items():
                setattr(snapshot, name, value)
            if current.series_id:
                snapshot.rrule, snapshot.exdates = None, []
            fields = {"remote_id": remote.remote_id, "etag": remote.etag, "base": content_of(snapshot)}
            if remote.ical_uid:
                fields["ical_uid"] = remote.ical_uid
            if current.version == sent_version and not current.deleted:
                fields["sync_state"] = "clean"
                self.repo.set_sync_fields(ev.id, **fields)
                self.repo.outbox_done(ev.id)
            else:
                self.repo.set_sync_fields(ev.id, **fields)   # modifié pendant l'envoi : repart au passage suivant
            report.pushed += 1

    # -- résolution d'un conflit --

    def resolve(self, conflict: dict, choice: str) -> None:
        """`choice` : « local » (la version d'ici est renvoyée) ou « remote » (la version distante est gardée)."""
        ev = self.repo.get_event(conflict["event_id"])
        with transaction(self.repo.conn):
            if ev is None:
                self.repo.resolve_conflict(conflict["id"], "événement disparu")
                return
            remote = conflict["remote"]
            if choice == "remote":
                if remote.get("deleted"):
                    self.repo.delete_event(ev.id)
                else:
                    rec = apply_content(ev.copy(), remote)
                    rec.deleted = False
                    self._write_remote(rec, remote, "clean", ev.version + 1)
                    self.repo.outbox_done(ev.id)
            else:
                local = conflict["local"]
                if local.get("deleted"):
                    self.repo.set_sync_fields(ev.id, sync_state="deleted", deleted=1)
                else:
                    self.repo.set_sync_fields(ev.id, sync_state="dirty")
                self.repo.enqueue(ev.id, ev.calendar_id, self.account_id)
            self.repo.resolve_conflict(conflict["id"], choice)
