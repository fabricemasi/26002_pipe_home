"""Temps réel de fm_theme (étape 4, docs/agents/fm_theme.md « Temps réel et fluidité »).

- `LiveServer` (dans l'éditeur fm_theme) : diffuse PENDANT le geste les valeurs d'aspect modifiées,
  `broadcast(preset, {clé: valeur})`, message JSON d'une ligne, sans toucher au disque.
- `LiveClient` (dans chaque appli) : reçoit, fusionne, et rend au plus UNE mise à jour par image (~16 ms) :
  signal `received(preset, valeurs)`. Se reconnecte seul (l'éditeur peut être lancé après l'appli).
- `PresetWatcher` (dans chaque appli) : surveille le fichier du preset (écrit à la fin du geste, ou par une
  appli lancée sans canal) ; signal `changed()` regroupé (une sauvegarde peut notifier plusieurs fois).

Qt seulement : aucun import de l'appli.
"""
from __future__ import annotations

import getpass
import json
from pathlib import Path

from PySide6.QtCore import QFileSystemWatcher, QObject, QTimer, Signal
from PySide6.QtNetwork import QLocalServer, QLocalSocket

FRAME_MS = 16           # une mise à jour par image au plus
RECONNECT_MS = 2000     # client déconnecté : nouvel essai (rien tant qu'il est connecté)
WATCH_DEBOUNCE_MS = 150


def server_name() -> str:
    """Nom du canal local, propre à l'utilisateur de la session."""
    return f"fm_theme_live_{getpass.getuser()}"


class LiveServer(QObject):
    """Côté éditeur : diffuse les valeurs modifiées à toutes les applis connectées."""

    def __init__(self, parent=None, name: str | None = None):
        super().__init__(parent)
        self._clients: list[QLocalSocket] = []
        self._server = QLocalServer(self)
        self._server.newConnection.connect(self._accept)
        name = name or server_name()
        if not self._server.listen(name):
            QLocalServer.removeServer(name)         # canal laissé par un éditeur arrêté brutalement
            self._server.listen(name)

    def is_listening(self) -> bool:
        return self._server.isListening()

    def _accept(self):
        while self._server.hasPendingConnections():
            socket = self._server.nextPendingConnection()
            self._clients.append(socket)
            socket.disconnected.connect(lambda s=socket: self._drop(s))

    def _drop(self, socket: QLocalSocket):
        if socket in self._clients:
            self._clients.remove(socket)
        try:
            socket.deleteLater()
        except RuntimeError:                        # serveur détruit (fermeture de l'éditeur)
            pass

    def broadcast(self, preset: str, values: dict) -> None:
        if not values or not self._clients:
            return
        data = (json.dumps({"preset": preset, "valeurs": values}, ensure_ascii=False) + "\n").encode("utf-8")
        for socket in list(self._clients):
            if socket.state() == QLocalSocket.ConnectedState:
                socket.write(data)
                socket.flush()


class LiveClient(QObject):
    """Côté appli : reçoit les valeurs diffusées, fusionnées, au plus une fois par image."""

    received = Signal(str, dict)

    def __init__(self, parent=None, name: str | None = None):
        super().__init__(parent)
        self._name = name or server_name()
        self._buffer = b""
        self._pending: dict[str, dict] = {}
        self._socket = QLocalSocket(self)
        self._socket.readyRead.connect(self._read)
        self._socket.disconnected.connect(self._retry_later)
        self._socket.errorOccurred.connect(lambda *_a: self._retry_later())
        self._retry = QTimer(self, singleShot=True, interval=RECONNECT_MS)
        self._retry.timeout.connect(self.connect_now)
        self._frame = QTimer(self, singleShot=True, interval=FRAME_MS)
        self._frame.timeout.connect(self._emit)
        self.connect_now()

    def is_connected(self) -> bool:
        return self._socket.state() == QLocalSocket.ConnectedState

    def connect_now(self):
        if self._socket.state() == QLocalSocket.UnconnectedState:
            self._socket.connectToServer(self._name)

    def _retry_later(self):
        if not self._retry.isActive():
            self._retry.start()

    def _read(self):
        self._buffer += bytes(self._socket.readAll())
        *lines, self._buffer = self._buffer.split(b"\n")
        for line in lines:
            try:
                message = json.loads(line)
                preset, values = str(message["preset"]), dict(message["valeurs"])
            except (ValueError, KeyError, TypeError):
                continue
            self._pending.setdefault(preset, {}).update(values)
        if self._pending and not self._frame.isActive():
            self._frame.start()

    def _emit(self):
        pending, self._pending = self._pending, {}
        for preset, values in pending.items():
            self.received.emit(preset, values)


class PresetWatcher(QObject):
    """Surveille UN fichier de preset (et son dossier : un remplacement atomique retire le fichier surveillé)."""

    changed = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._path: Path | None = None
        self._watcher = QFileSystemWatcher(self)
        self._watcher.fileChanged.connect(self._touched)
        self._watcher.directoryChanged.connect(self._touched)
        self._debounce = QTimer(self, singleShot=True, interval=WATCH_DEBOUNCE_MS)
        self._debounce.timeout.connect(self._fire)
        self._stamp = None

    def watch(self, path: Path | None) -> None:
        """Change le fichier surveillé (None : plus rien). Sans effet si c'est déjà lui."""
        path = Path(path) if path else None
        if path == self._path:
            return
        old = self._watcher.files() + self._watcher.directories()
        if old:
            self._watcher.removePaths(old)
        self._path = path
        self._stamp = self._read_stamp()
        if path is not None:
            if path.parent.is_dir():
                self._watcher.addPath(str(path.parent))
            if path.is_file():
                self._watcher.addPath(str(path))

    def _read_stamp(self):
        try:
            stat = self._path.stat() if self._path else None
            return (stat.st_mtime_ns, stat.st_size) if stat else None
        except OSError:
            return None

    def _touched(self, *_args):
        if self._path is not None and self._path.is_file() and str(self._path) not in self._watcher.files():
            self._watcher.addPath(str(self._path))
        self._debounce.start()

    def _fire(self):
        stamp = self._read_stamp()
        if stamp is None or stamp == self._stamp:     # autre fichier du dossier, ou rien de changé
            return
        self._stamp = stamp
        self.changed.emit()
