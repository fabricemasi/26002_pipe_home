"""Fil d'écriture SQLite de l'agenda : TOUTES les écritures locales passent par lui, une transaction par tâche,
dans l'ordre reçu. L'interface n'attend jamais le disque (un `fsync` lent, un antivirus qui scrute le fichier) :
elle montre la modification tout de suite (voir `AgendaService._pending`), le fil confirme ensuite.

Les rappels (`on_done`, `on_error`) reviennent dans le fil de l'interface par un signal Qt (connexion mise en file
d'attente)."""
from __future__ import annotations

import logging
import queue
import sqlite3
import threading
import traceback

from PySide6.QtCore import QObject, Signal

from ..store.database import transaction
from ..store.repository import RangeHints, Repository

log = logging.getLogger("fm_agenda.writer")


class _Bridge(QObject):
    delivered = Signal(object)

    def __init__(self):
        super().__init__()
        self.delivered.connect(self._run)

    @staticmethod
    def _run(payload):
        callback, value = payload
        try:
            callback(value)
        except Exception:                               # noqa: BLE001 - un rappel ne doit pas tuer la boucle
            log.exception("rappel du fil d'écriture")


class DbWriter:
    def __init__(self, conn: sqlite3.Connection, hints: RangeHints):
        self.repo = Repository(conn, hints)
        self._queue: queue.Queue = queue.Queue()
        self._bridge = _Bridge()
        self._thread = threading.Thread(target=self._loop, name="fm_agenda-ecriture", daemon=True)
        self._stopped = False
        self._thread.start()

    def submit(self, task, on_done=None, on_error=None, transactional: bool = True) -> None:
        """`task(repo)` dans le fil d'écriture ; `on_done(résultat)` / `on_error(texte)` dans celui de l'interface."""
        if self._stopped:
            raise RuntimeError("fil d'écriture arrêté")
        self._queue.put((task, on_done, on_error, transactional))

    def flush(self, timeout: float | None = 10.0) -> bool:
        """Attend que toutes les tâches soient écrites (tests, fermeture). Les rappels restent à délivrer par la
        boucle Qt (`QCoreApplication.processEvents`)."""
        done = threading.Event()
        self._queue.put((lambda _repo: done.set(), None, None, False))
        return done.wait(timeout)

    def stop(self, timeout: float = 10.0) -> None:
        if self._stopped:
            return
        self._stopped = True
        self._queue.put(None)
        self._thread.join(timeout)

    def _loop(self) -> None:
        while True:
            item = self._queue.get()
            if item is None:
                return
            task, on_done, on_error, transactional = item
            try:
                if transactional:
                    with transaction(self.repo.conn):
                        result = task(self.repo)
                else:
                    result = task(self.repo)
            except Exception as exc:                    # noqa: BLE001 - signalé à l'interface, jamais perdu
                log.error("écriture de l'agenda échouée : %s\n%s", exc, traceback.format_exc())
                if on_error is not None:
                    self._bridge.delivered.emit((on_error, f"{type(exc).__name__}: {exc}"))
                continue
            if on_done is not None:
                self._bridge.delivered.emit((on_done, result))
