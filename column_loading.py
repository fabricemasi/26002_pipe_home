"""Lectures des colonnes : deux lectures simultanées, cache partagé, aucune attente GUI.

Les workers ne reçoivent que des chemins et renvoient des données Python. Les
widgets et le cache LRU appartiennent exclusivement au fil Qt. Un scan engagé
sur SMB finit librement ; une colonne retirée ne reçoit plus ses résultats.
"""
from collections import OrderedDict
from dataclasses import dataclass, field
import os
from pathlib import Path
import threading
import time
import weakref

from PySide6.QtCore import QObject, Signal, Slot, Qt
import shiboken6

import browser_core as core
from previews import is_remote_path


@dataclass
class ColumnData:
    entries: dict = field(default_factory=dict)
    layouts: dict = field(default_factory=dict)
    shortcuts: dict = field(default_factory=dict)
    info: dict = field(default_factory=dict)
    lightroom: set = field(default_factory=set)
    errors: dict = field(default_factory=dict)
    stamp: float = field(default_factory=time.monotonic)

    @property
    def cost(self):
        return sum(map(len, self.entries.values())) + len(self.info)


def read_column(directories, exclude):
    """Lecture seule, y compris pour les anciens réglages de punaise."""
    data = ColumnData()
    for directory in directories:
        try:
            # Une seule lecture brute partagée entre les vues filtrées et les
            # métadonnées (statuts compris). Le filtrage des noms reste en GUI.
            paths = core.list_entries(directory, strict=True)
        except FileNotFoundError as exc:
            # Les colonnes IN/OVER/OUT existent même avant leur dossier.
            data.errors[str(directory)] = str(exc)
            paths = []
        key = str(directory)
        # Les peintures (pastilles de projet) et la navigation réutilisent ces
        # textes. Jamais de lecture de configuration depuis une peinture UNC.
        record = core._DIR_CONFIG.get(os.path.normcase(key))
        for name in record[1] if record else ():
            core.read_config_text(directory / name)
        data.entries[key] = paths
        data.layouts[key] = core.load_layout_settings(directory, migrate=False)
        shortcuts = []
        for shortcut in core.load_shortcuts(directory):
            target = Path(shortcut["target"])
            # Les raccourcis réseau restent visibles, même serveur hors ligne.
            if is_remote_path(target) or target.is_dir():
                core.remember_entry(target, True)
                shortcuts.append(shortcut)
                if not is_remote_path(target) and (target / ".pipeline_lightroom.json").is_file():
                    data.lightroom.add(str(target))
        data.shortcuts[key] = shortcuts
        for path in [*paths, *(Path(s["target"]) for s in shortcuts)]:
            info = core._ENTRY_INFO.get(str(path))
            if info is not None:
                data.info[str(path)] = info
    data.stamp = time.monotonic()
    return data


class ColumnLoader(QObject):
    ready = Signal(object, object, str)
    _finished = Signal(object, object, str)
    MAX_ACTIVE = 2
    MAX_PENDING = 64
    MAX_FOLDERS = 64
    MAX_ENTRIES = 100_000
    FRESH_S = 4.0

    def __init__(self):
        super().__init__()
        self.cache = OrderedDict()
        self.pending = OrderedDict()
        self.active = set()
        self.owners = {}
        self.cost = 0
        self.scans = 0
        self._finished.connect(self._complete, Qt.QueuedConnection)

    def key(self, directories, exclude):
        # Pas de resolve/stat : les clés UNC sont purement lexicales.
        return (tuple(os.path.normcase(str(p)) for p in directories), None,
                core._layout_preset(), core._CONFIG_REVISION)

    def cached(self, key):
        data = self.cache.get(key)
        if data is not None:
            self.cache.move_to_end(key)
        return data

    def request(self, key, directories, exclude, owner, *, force=False):
        self.owners.setdefault(key, weakref.WeakSet()).add(owner)
        if key in self.active and not force:
            return
        self.pending[key] = (tuple(directories), exclude)
        self.pending.move_to_end(key)
        while len(self.pending) > self.MAX_PENDING:
            dropped, _ = self.pending.popitem(last=False)
            self.ready.emit(dropped, None, "Lecture reportée : actualisez le dossier.")
            self.owners.pop(dropped, None)
        self._dispatch()

    def cancel(self, key, owner):
        owners = self.owners.get(key)
        if owners is not None:
            owners.discard(owner)
        if not owners:
            self.owners.pop(key, None)
            self.pending.pop(key, None)

    def _dispatch(self):
        remote_active = sum(any(is_remote_path(p) for p in active[0]) for active in self.active)
        for key in reversed(tuple(self.pending)):
            if len(self.active) >= self.MAX_ACTIVE:
                break
            if key in self.active:
                continue
            remote = any(is_remote_path(p) for p in key[0])
            if remote and remote_active >= 1:
                continue                  # réserver une lecture aux disques locaux
            directories, exclude = self.pending.pop(key)
            owners = self.owners.get(key, ())
            if not any(shiboken6.isValid(owner) for owner in owners):
                self.owners.pop(key, None)
                continue
            self.active.add(key)
            remote_active += int(remote)
            self.scans += 1
            # Daemon : fermer l'appli n'attend pas un appel SMB non annulable.
            threading.Thread(target=self._read, args=(key, directories, exclude),
                             name="column-scan", daemon=True).start()

    def _read(self, key, directories, exclude):
        try:
            data, error = read_column(directories, exclude), ""
        except Exception as exc:
            data, error = None, f"Lecture impossible : {exc}"
        try:
            self._finished.emit(key, data, error)
        except RuntimeError:
            pass                         # QApplication déjà détruite

    @Slot(object, object, str)
    def _complete(self, key, data, error):
        self.active.discard(key)
        # Une actualisation demandée pendant le scan doit relire le disque.
        if key not in self.pending:
            if data is not None:
                old = self.cache.pop(key, None)
                self.cost -= old.cost if old else 0
                if data.cost <= self.MAX_ENTRIES:
                    self.cache[key] = data
                    self.cost += data.cost
                while self.cache and (len(self.cache) > self.MAX_FOLDERS or self.cost > self.MAX_ENTRIES):
                    _, removed = self.cache.popitem(last=False)
                    self.cost -= removed.cost
            self.ready.emit(key, data, error)
            self.owners.pop(key, None)
        self._dispatch()


_loader = None


def loader():
    global _loader
    if _loader is None:
        _loader = ColumnLoader()
    return _loader
