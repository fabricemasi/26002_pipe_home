"""Pilotage de la synchronisation depuis l'interface (Qt) : UN fil de synchronisation (connexion SQLite à lui), file
de tâches, minuterie (`agenda_sync_interval_min`), envoi peu après une modification locale (`agenda_sync_on_change`),
état lisible (`status_text`), comptes (connexion OAuth, déconnexion), calendriers synchronisés, conflits.

Hors connexion : les modifications restent dans la file d'envoi persistante (`sync_outbox`) ; chaque échec
réseau repousse l'essai (attente exponentielle) ; le passage suivant reprend où il s'était arrêté. Rien ne bloque
le fil de l'interface : les résultats reviennent par signal Qt."""
from __future__ import annotations

import logging
import os
import queue
import threading
import time

from PySide6.QtCore import QObject, QTimer, Signal

from ..core.model import new_id
from ..store import database as db
from ..store.repository import Repository, now_ts
from .engine import SyncEngine
from .provider import AuthError, SyncError, TransientError

# Réseau, OAuth et Google importés à la PREMIÈRE synchronisation (urllib, ssl, http.server : ~150 ms à froid) :
# le service de l'agenda démarre en fond sans figer l'interface.

log = logging.getLogger("fm_agenda.sync")


class _Bridge(QObject):
    delivered = Signal(object)

    def __init__(self):
        super().__init__()
        self.delivered.connect(lambda payload: payload[0](*payload[1]))


class SyncManager(QObject):
    changed = Signal()                       # état (comptes, erreurs, en cours) : rafraîchir les réglages
    finished = Signal(object)                # SyncReport | Exception (tests)

    def __init__(self, service, parent=None, http=None, provider_factory=None, clock=time.time):
        super().__init__(parent)
        self.service = service
        self._http = http
        self.provider_factory = provider_factory or self._google_provider
        self.clock = clock
        self.running = False
        self._pending_jobs = 0
        self.state: dict = {"message": "", "error": "", "last_ok": 0, "offline": False}
        self._jobs: queue.Queue = queue.Queue()
        self._bridge = _Bridge()
        self._thread: threading.Thread | None = None
        self._stop = threading.Event()
        self._cancel_auth = threading.Event()
        self._tokens: dict = {}
        self._timer = QTimer(self)
        self._timer.timeout.connect(self.sync_now)
        self._debounce = QTimer(self)
        self._debounce.setSingleShot(True)
        self._debounce.setInterval(3000)
        self._debounce.timeout.connect(self.sync_now)

    # -- cycle de vie --

    def start(self) -> None:
        if self._thread is None:
            self._thread = threading.Thread(target=self._loop, name="fm_agenda-synchro", daemon=True)
            self._thread.start()
        self.settings_changed(self.service.settings)
        if self.accounts() and self.service.settings.get("agenda_sync_auto", True):
            QTimer.singleShot(1500, self, self.sync_now)

    def stop(self, timeout: float = 5.0) -> None:
        self._timer.stop()
        self._debounce.stop()
        self._cancel_auth.set()
        self._stop.set()
        self._jobs.put(None)
        if self._thread is not None:
            self._thread.join(timeout)
            self._thread = None

    def settings_changed(self, settings: dict) -> None:
        minutes = max(1, int(settings.get("agenda_sync_interval_min", 5) or 5))
        if settings.get("agenda_sync_auto", True) and self.accounts():
            self._timer.start(minutes * 60_000)
        else:
            self._timer.stop()

    def local_changed(self) -> None:
        if self.service.settings.get("agenda_sync_on_change", True) and self._has_outbox():
            self._debounce.start()

    def _has_outbox(self) -> bool:
        try:
            return self.service.repo.outbox_count() > 0
        except Exception:                                # noqa: BLE001
            return False

    # -- comptes --

    def accounts(self) -> list[dict]:
        try:
            return self.service.repo.list_accounts()
        except Exception:                                # noqa: BLE001
            return []

    @property
    def http(self):
        if self._http is None:
            from .http import HttpTransport
            self._http = HttpTransport()
        return self._http

    def has_client(self) -> bool:
        from . import oauth
        return oauth.load_client() is not None

    def import_client(self, path) -> None:
        from . import oauth
        oauth.import_client_json(path)
        self.changed.emit()

    def token_source(self, account_id: str):
        from . import oauth
        source = self._tokens.get(account_id)
        if source is None:
            source = self._tokens[account_id] = oauth.TokenSource(account_id, self.http)
        return source

    def _google_provider(self, account: dict):
        from .google import GoogleProvider
        return GoogleProvider(self.token_source(account["id"]), self.http)

    def connect_google(self, open_browser=None, on_done=None) -> None:
        """Consentement dans le navigateur du système (fil de synchronisation), puis première synchronisation."""
        from . import oauth
        client = oauth.load_client()
        if client is None:
            raise SyncError("Importer d'abord l'identifiant OAuth de l'application (fichier JSON de Google Cloud).")
        self._cancel_auth.clear()
        import webbrowser
        opener = open_browser or webbrowser.open

        def job(repo: Repository):
            tokens = oauth.authorize(client, self.http, opener, cancelled=self._cancel_auth)
            account_id = new_id()
            source = self.token_source(account_id)
            source.client = client
            source.store(tokens)
            provider = self.provider_factory({"id": account_id})
            email = tokens.email or provider.account_email()
            with db.transaction(repo.conn):
                repo.upsert_account({"id": account_id, "provider": "google", "email": email, "display_name": email,
                                     "status": "connected", "created_at": now_ts()})
            return self._sync_account(repo, repo.get_account(account_id))
        self._submit(job, "Connexion à Google Agenda…", on_done)

    def cancel_connect(self) -> None:
        self._cancel_auth.set()

    def disconnect(self, account_id: str, delete_local: bool = True, on_done=None) -> None:
        """Jeton révoqué chez Google et effacé du coffre ; copies locales des calendriers du compte supprimées
        (`delete_local`) ou gardées en calendriers locaux."""
        def job(repo: Repository):
            self.token_source(account_id).forget(revoke_remote=True)
            with db.transaction(repo.conn):
                for cal in repo.list_calendars(include_deleted=True):
                    if cal.account_id != account_id:
                        continue
                    if delete_local:
                        repo.delete_calendar(cal.id)
                    else:
                        cal.source, cal.account_id, cal.remote_id, cal.sync_enabled = "local", None, None, False
                        cal.access_role = "owner"
                        repo.upsert_calendar(cal)
                        repo.conn.execute("UPDATE events SET remote_id = NULL, etag = NULL, sync_state = 'local', "
                                          "base = NULL WHERE calendar_id = ?", (cal.id,))
                        repo.conn.execute("DELETE FROM sync_outbox WHERE calendar_id = ?", (cal.id,))
                repo.delete_account(account_id)
            self._tokens.pop(account_id, None)
            return None
        self._submit(job, "Déconnexion…", on_done)

    def set_calendar_sync(self, cal_id: str, enabled: bool) -> None:
        cal = self.service.calendar(cal_id)
        if cal is None:
            return
        self.service.update_calendar(cal_id, sync_enabled=bool(enabled))
        if enabled:
            self.sync_now()

    # -- synchronisation --

    def sync_now(self, on_done=None) -> None:
        if os.environ.get("FM_AGENDA_NO_NETWORK") and self._http is None:
            return                                        # tests : jamais le vrai réseau
        if not self.accounts():
            return
        if self._pending_jobs > 1:
            return                                        # un passage est déjà prévu derrière celui en cours

        def job(repo: Repository):
            report = None
            for account in repo.list_accounts():
                report = self._sync_account(repo, account)
            return report
        self._submit(job, "Synchronisation…", on_done)

    def _sync_account(self, repo: Repository, account: dict):
        provider = self.provider_factory(account)
        engine = SyncEngine(repo, provider, account, self.service.settings.get("agenda_conflict_policy", "ask"),
                            self.clock)
        try:
            report = engine.run()
        except AuthError as exc:
            with db.transaction(repo.conn):
                repo.update_account(account["id"], status="auth_error", last_error=str(exc))
            raise
        except TransientError as exc:
            with db.transaction(repo.conn):
                repo.update_account(account["id"], last_error=str(exc))
            raise
        with db.transaction(repo.conn):
            repo.update_account(account["id"], status="connected", last_sync_at=now_ts(),
                                last_error="; ".join(report.errors)[:500])
        return report

    def resolve_conflict(self, conflict: dict, choice: str, on_done=None) -> None:
        def job(repo: Repository):
            cal = repo.get_calendar(conflict["calendar_id"])
            account = repo.get_account(cal.account_id) if cal is not None and cal.account_id else None
            if account is None:
                with db.transaction(repo.conn):
                    repo.resolve_conflict(conflict["id"], "sans compte")
                return None
            SyncEngine(repo, self.provider_factory(account), account).resolve(conflict, choice)
            return self._sync_account(repo, account)
        self._submit(job, "Résolution du conflit…", on_done)

    def conflicts(self) -> list[dict]:
        try:
            return self.service.repo.open_conflicts()
        except Exception:                                # noqa: BLE001
            return []

    def wait_idle(self, timeout: float = 15.0) -> bool:
        """Tests : attend la fin des tâches (les rappels restent à délivrer par la boucle Qt)."""
        done = threading.Event()
        self._jobs.put((lambda repo: done.set(), None, None, True))
        return done.wait(timeout)

    # -- fil --

    def _submit(self, job, message: str, on_done=None) -> None:
        if self._thread is None:
            self.start()
        self.state["message"] = message
        self._pending_jobs += 1
        self.running = True
        self.changed.emit()
        self._jobs.put((job, message, on_done, False))

    def _loop(self) -> None:
        conn = None
        try:
            conn = db.connect(self.service.path)
            repo = Repository(conn, self.service.hints)
            while not self._stop.is_set():
                item = self._jobs.get()
                if item is None:
                    break
                job, _message, on_done, internal = item
                try:
                    result = job(repo)
                except Exception as exc:                 # noqa: BLE001 - montré dans l'état, jamais fatal
                    result = exc
                    if not isinstance(exc, (SyncError,)):
                        log.exception("synchronisation")
                if internal:
                    continue
                self._bridge.delivered.emit((self._done, (result, on_done)))
        finally:
            if conn is not None:
                conn.close()

    def _done(self, result, on_done) -> None:
        self._pending_jobs = max(0, self._pending_jobs - 1)
        self.running = self._pending_jobs > 0
        if isinstance(result, Exception):
            offline = isinstance(result, TransientError)
            self.state.update(error=str(result), offline=offline,
                              message="Hors ligne : nouvel essai plus tard" if offline else f"Erreur : {result}")
        else:
            self.state.update(error="", offline=False, last_ok=self.clock(),
                              message=("Synchronisé : " + result.summary()) if result is not None else "")
            if result is not None and (result.remote_changed or result.pushed):
                self.service.remote_applied()
        self.settings_changed(self.service.settings)
        self.changed.emit()
        self.service.syncChanged.emit()
        self.finished.emit(result)
        if on_done is not None:
            on_done(result)

    def status_text(self) -> str:
        accounts = self.accounts()
        if not accounts:
            return "Aucun compte connecté : l'agenda fonctionne en local."
        parts = []
        for a in accounts:
            when = time.strftime("%d/%m %H:%M", time.localtime(a["last_sync_at"])) if a["last_sync_at"] else "jamais"
            state = {"connected": "connecté", "auth_error": "à reconnecter"}.get(a["status"], a["status"])
            parts.append(f"{a['email'] or 'Compte Google'} : {state}, dernière synchronisation {when}")
            if a.get("last_error"):
                parts.append("   " + a["last_error"])
        pending = self.service.repo.outbox_count()
        if pending:
            parts.append(f"{pending} modification(s) en attente d'envoi")
        n = len(self.conflicts())
        if n:
            parts.append(f"{n} conflit(s) à résoudre")
        if self.state.get("message"):
            parts.append(self.state["message"])
        return "\n".join(parts)


def clear_test_credentials() -> None:
    from . import credentials
    credentials.clear_memory()
