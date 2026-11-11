"""Pilotage de la synchronisation des tâches depuis l'interface (Qt) : UN fil de synchronisation (réseau + lecture
de la base sur sa propre connexion), minuterie (`taches_sync_interval_min`), envoi peu après une modification
locale (`taches_sync_on_change`), comptes (connexion OAuth dans le navigateur, déconnexion), état lisible.

Ordre garanti : un passage lit la base APRÈS que le fil d'écriture a tout écrit (`writer.flush`), et le passage
suivant n'est lancé qu'une fois le résultat du précédent fusionné dans l'interface (`_applied`) : sans cela, il
relirait une base sans les identifiants Google tout juste reçus et recréerait les mêmes tâches.

Hors connexion : les modifications attendent dans la file persistante (`sync_outbox`) ; nouvel essai au passage
suivant. Réseau, OAuth et Google sont importés à la première synchronisation (le service démarre sans eux)."""
from __future__ import annotations

import logging
import os
import queue
import threading
import time

from PySide6.QtCore import QObject, QTimer, Signal

from fm_agenda.sync.provider import AuthError, SyncError, TransientError
from ..core.model import new_id
from ..store import database as db
from ..store.repository import Repository, now_ts

log = logging.getLogger("fm_taches.sync")


class _Bridge(QObject):
    delivered = Signal(object)

    def __init__(self):
        super().__init__()
        self.delivered.connect(lambda payload: payload[0](*payload[1]))


class TasksSyncManager(QObject):
    changed = Signal()                       # état (comptes, erreurs, en cours) : rafraîchir les réglages
    finished = Signal(object)                # liste de SyncResult | Exception (tests)

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
        self._applied = threading.Event()
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
            self._stop.clear()
            self._thread = threading.Thread(target=self._loop, name="fm_taches-synchro", daemon=True)
            self._thread.start()
        self.settings_changed(self.service.settings)
        if self.accounts() and self.service.settings.get("taches_sync_auto", True):
            QTimer.singleShot(2000, self, self.sync_now)

    def stop(self, timeout: float = 5.0) -> None:
        self._timer.stop()
        self._debounce.stop()
        self._cancel_auth.set()
        self._stop.set()
        self._applied.set()
        self._jobs.put(None)
        if self._thread is not None:
            self._thread.join(timeout)
            self._thread = None

    def settings_changed(self, settings: dict) -> None:
        minutes = max(1, int(settings.get("taches_sync_interval_min", 5) or 5))
        if settings.get("taches_sync_auto", True) and self.accounts():
            self._timer.start(minutes * 60_000)
        else:
            self._timer.stop()

    def local_changed(self) -> None:
        if self.service.settings.get("taches_sync_on_change", True) and self.accounts():
            self._debounce.start()

    # -- comptes --

    def accounts(self) -> list[dict]:
        return self.service.accounts()

    @property
    def http(self):
        if self._http is None:
            from fm_agenda.sync.http import HttpTransport
            self._http = HttpTransport()
        return self._http

    def has_client(self) -> bool:
        from fm_agenda.sync import oauth
        return oauth.load_client() is not None

    def import_client(self, path) -> None:
        from fm_agenda.sync import oauth
        oauth.import_client_json(path)
        self.changed.emit()

    def token_source(self, account_id: str):
        from .google_tasks import TasksTokenSource
        source = self._tokens.get(account_id)
        if source is None:
            source = self._tokens[account_id] = TasksTokenSource(account_id, self.http)
        return source

    def _google_provider(self, account: dict):
        from .google_tasks import GoogleTasksProvider
        return GoogleTasksProvider(self.token_source(account["id"]), self.http)

    def connect_google(self, open_browser=None, on_done=None) -> None:
        """Consentement dans le navigateur du système (fil de synchronisation), puis première synchronisation."""
        from fm_agenda.sync import oauth
        from .google_tasks import SCOPES
        client = oauth.load_client()
        if client is None:
            raise SyncError("Importer d'abord l'identifiant OAuth de l'application (fichier JSON de Google Cloud).")
        self._cancel_auth.clear()
        import webbrowser
        opener = open_browser or webbrowser.open

        def job(_repo):
            tokens = oauth.authorize(client, self.http, opener, cancelled=self._cancel_auth, scopes=SCOPES,
                                     product="Google Tasks")
            account_id = new_id()
            source = self.token_source(account_id)
            source.client = client
            source.store(tokens)
            email = tokens.email or "Compte Google"
            return ("account", {"id": account_id, "provider": "google", "email": email, "display_name": email,
                                "status": "connected", "created_at": now_ts()})
        self._submit(job, "Connexion à Google Tasks…", on_done)

    def cancel_connect(self) -> None:
        self._cancel_auth.set()

    def disconnect(self, account_id: str, keep_tasks: bool = True, on_done=None) -> None:
        """Jeton révoqué chez Google et effacé du coffre ; les listes du compte deviennent locales
        (`keep_tasks`) ou sont effacées."""
        def job(_repo):
            self.token_source(account_id).forget(revoke_remote=True)
            self._tokens.pop(account_id, None)
            return ("disconnected", account_id, keep_tasks)
        self._submit(job, "Déconnexion…", on_done)

    # -- synchronisation --

    def sync_now(self, on_done=None) -> None:
        if os.environ.get("FM_AGENDA_NO_NETWORK") and self._http is None and \
                self.provider_factory == self._google_provider:
            return                                        # tests : jamais le vrai réseau
        accounts = [a for a in self.accounts() if a.get("status") != "auth_error"]
        if not accounts:
            return
        if self._pending_jobs > 1:
            return                                        # un passage est déjà prévu derrière celui en cours
        writer = self.service.writer

        def job(repo):
            from .engine import SyncEngine
            writer.flush(15)                              # la base = la mémoire au moment du passage
            results = []
            for account in accounts:
                try:
                    results.append(SyncEngine(repo, self.provider_factory(account), account, self.clock).run())
                except AuthError as exc:
                    results.append(("auth_error", account["id"], str(exc)))
            return ("sync", results)
        self._submit(job, "Synchronisation…", on_done)

    def wait_idle(self, timeout: float = 15.0) -> bool:
        """Tests : attend la fin des tâches en file (les résultats restent à délivrer par la boucle Qt)."""
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
            repo = Repository(conn)
            while not self._stop.is_set():
                item = self._jobs.get()
                if item is None:
                    break
                job, _message, on_done, internal = item
                try:
                    result = job(repo)
                except Exception as exc:                 # noqa: BLE001 - montré dans l'état, jamais fatal
                    result = exc
                    if not isinstance(exc, SyncError):
                        log.exception("synchronisation des tâches")
                if internal:
                    continue
                self._applied.clear()
                self._bridge.delivered.emit((self._done, (result, on_done)))
                self._applied.wait(60)                   # fusion faite dans l'interface avant le passage suivant
        finally:
            if conn is not None:
                conn.close()

    def _done(self, result, on_done) -> None:
        try:
            self._handle(result)
        except Exception as exc:                         # noqa: BLE001
            log.exception("fusion de la synchronisation")
            result = exc
            self.state.update(error=str(exc), message=f"Erreur : {exc}")
        finally:
            self._applied.set()
        self._pending_jobs = max(0, self._pending_jobs - 1)
        self.running = self._pending_jobs > 0
        self.settings_changed(self.service.settings)
        self.changed.emit()
        self.finished.emit(result)
        if on_done is not None:
            on_done(result)

    def _handle(self, result) -> None:
        if isinstance(result, Exception):
            offline = isinstance(result, TransientError)
            self.state.update(error=str(result), offline=offline,
                              message="Hors ligne : nouvel essai plus tard" if offline else f"Erreur : {result}")
            return
        kind = result[0]
        if kind == "account":
            self.service.save_account(result[1])
            self.state.update(error="", message=f"Compte connecté : {result[1]['email']}")
            QTimer.singleShot(0, self, self.sync_now)
            return
        if kind == "disconnected":
            self.service.remove_account(result[1], keep_tasks=result[2])
            self.state.update(error="", message="Compte déconnecté")
            return
        from . import merge
        policy = self.service.settings.get("taches_conflict_policy", "recent")
        again = False
        summaries, offline = [], ""
        for res in result[1]:
            if isinstance(res, tuple):                    # jeton refusé : compte à reconnecter
                acc = self.service.account(res[1])
                if acc is not None:
                    self.service.save_account(dict(acc, status="auth_error", last_error=res[2][:500]))
                summaries.append("compte à reconnecter")
                continue
            info = merge.apply(self.service, res, policy, self.clock)
            again = again or bool(info.get("skipped"))
            summaries.append(res.summary())
            offline = offline or res.offline
        self.state.update(error=offline, offline=bool(offline), last_ok=self.clock(),
                          message=("Hors ligne : " if offline else "Synchronisé : ") + " ; ".join(summaries))
        if again:
            QTimer.singleShot(1500, self, self.sync_now)   # fusion faite : le reste part au passage suivant

    def status_text(self) -> str:
        accounts = self.accounts()
        if not accounts:
            return "Aucun compte connecté : les tâches restent sur ce PC."
        parts = []
        for a in accounts:
            when = time.strftime("%d/%m %H:%M", time.localtime(a["last_sync_at"])) if a.get("last_sync_at") else \
                "jamais"
            state = {"connected": "connecté", "auth_error": "à reconnecter"}.get(a.get("status"), a.get("status"))
            n = len(self.service.synced_lists(a["id"]))
            parts.append(f"{a.get('email') or 'Compte Google'} : {state}, {n} liste(s), dernière synchronisation {when}")
            if a.get("last_error"):
                parts.append("   " + a["last_error"])
        if self.state.get("message"):
            parts.append(self.state["message"])
        return "\n".join(parts)
