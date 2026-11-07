"""Interface d'une source distante d'événements, indépendante de Google : le moteur (`engine`) ne connaît qu'elle.
Le futur serveur personnel (Raspberry Pi, API FastAPI + PostgreSQL) en sera une seconde implémentation
(`ServerProvider`, docs/agents/fm_agenda.md « Protocole du serveur personnel »).

Toutes les méthodes sont BLOQUANTES : elles ne s'appellent que depuis le fil de synchronisation."""
from __future__ import annotations

from dataclasses import dataclass, field


class SyncError(Exception):
    """Erreur de synchronisation (message lisible par l'utilisateur)."""


class TransientError(SyncError):
    """Réseau absent, serveur indisponible (5xx), quota (429 / rateLimitExceeded) : réessayer plus tard."""

    def __init__(self, message: str, retry_after: float | None = None):
        super().__init__(message)
        self.retry_after = retry_after


class AuthError(SyncError):
    """Jeton refusé ou révoqué : reconnexion nécessaire."""


class ForbiddenError(SyncError):
    """Droits insuffisants (calendrier en lecture seule)."""


class NotFoundError(SyncError):
    pass


class GoneError(SyncError):
    """HTTP 410 : jeton de synchronisation invalidé (resynchronisation complète) ou ressource supprimée."""


class ConflictError(SyncError):
    """HTTP 409 : l'identifiant existe déjà (création répétée après une coupure : c'est le même événement)."""


class PreconditionFailed(SyncError):
    """HTTP 412 : l'événement a changé à distance depuis la dernière lecture (etag)."""


@dataclass
class RemoteCalendar:
    remote_id: str
    name: str
    color: str = ""                       # « #rrggbb »
    access_role: str = "reader"
    primary: bool = False
    timezone: str = ""
    default_reminders: list[int] = field(default_factory=list)


@dataclass
class ChangePage:
    items: list[dict]
    next_page: str | None = None
    next_sync_token: str | None = None


class RemoteProvider:
    """Ce qu'une source distante doit savoir faire. `item` = représentation native (dict) d'un événement."""
    name = "remote"

    def account_email(self) -> str:
        raise NotImplementedError

    def list_calendars(self) -> list[RemoteCalendar]:
        raise NotImplementedError

    def list_changes(self, calendar_remote_id: str, sync_token: str | None, page_token: str | None,
                     time_min: str | None = None) -> ChangePage:
        """Une page de changements. `sync_token` None = synchronisation complète. GoneError si le jeton est périmé."""
        raise NotImplementedError

    def get(self, calendar_remote_id: str, remote_id: str) -> dict:
        raise NotImplementedError

    def insert(self, calendar_remote_id: str, body: dict) -> dict:
        raise NotImplementedError

    def update_instance(self, calendar_remote_id: str, remote_id: str, body: dict) -> dict:
        raise NotImplementedError

    def patch(self, calendar_remote_id: str, remote_id: str, body: dict, etag: str | None) -> dict:
        raise NotImplementedError

    def delete(self, calendar_remote_id: str, remote_id: str, etag: str | None) -> None:
        raise NotImplementedError

    # Correspondance des champs (propre à chaque source)
    def to_record(self, item: dict, default_tz: str):
        raise NotImplementedError

    def to_body(self, record, fields: set[str] | None, master_remote_id: str | None,
                master_tz: str | None) -> dict:
        raise NotImplementedError


class ServerProvider(RemoteProvider):
    """Futur serveur personnel (non implémenté : le matériel n'existe pas encore). Protocole prévu : REST JSON,
    événements au format de l'agenda (identifiants locaux UUID globaux, `version`, `origin`), changements depuis un
    numéro de révision (`GET /v1/agenda/changes?since=<rev>`), écriture conditionnelle (`If-Match: <version>`).
    Voir docs/agents/fm_agenda.md, « Protocole du serveur personnel »."""
    name = "server"
