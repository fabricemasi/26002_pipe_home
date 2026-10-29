"""Dates de modification et chemins distants sans bloquer l’interface.

Carte et pièges : docs/agents/apercus.md.
"""

import ctypes
import os
import threading
import time
from PySide6.QtCore import QObject, Signal

# Dates de modification memorisees un court instant : le dessin de CHAQUE ligne verifiait a chaque
# repeinture si une icone perso / une vignette de dossier existe et a change (2 a 3 stat par ligne,
# ~150 par repeinture, lents sur un dossier synchronise). Ce que l'appli ecrit elle-meme (vignette,
# icone) appelle forget_mtime : visible aussitot ; un changement exterieur, au plus 1,5 s apres.
_MTIME_CACHE: dict[str, tuple[float, float | None]] = {}

_MTIME_TTL = 1.5

# « Memoire seulement » (memory_only) : pendant une animation (pellicule de la visionneuse), aucune
# lecture disque sur le fil de l'interface — une date inconnue ou trop vieille est relue EN FOND
# (_refresh_mtimes) et `MTIME_SIGNALS.refreshed` previent quand elle est connue. Apres un long moment
# sans visionneuse, ces stat sur le disque dur coutaient ~180 ms a la 1re image : l'animation sautait.
_MEMORY_ONLY = threading.local()

_MTIME_PENDING: set = set()

_MTIME_PENDING_LOCK = threading.Lock()

class _MtimeSignals(QObject):
    refreshed = Signal()

MTIME_SIGNALS = _MtimeSignals()

class memory_only:
    """`with memory_only():` — cached_mtime ne lit pas le disque (valeur memorisee, meme ancienne).
    `memory_only(hold=True)` : en plus, file_image_pixmap(asynchronous=True) ne lance AUCUN decodage
    (pendant une animation : les decodages en fond, en Python, gardent le GIL et hachent l'animation ;
    ils sont demandes a la peinture suivante, hors animation)."""

    def __init__(self, hold: bool = False):
        self.hold = hold

    def __enter__(self):
        _MEMORY_ONLY.on = getattr(_MEMORY_ONLY, "on", 0) + 1
        if self.hold:
            _MEMORY_ONLY.hold = getattr(_MEMORY_ONLY, "hold", 0) + 1

    def __exit__(self, *exc):
        _MEMORY_ONLY.on -= 1
        if self.hold:
            _MEMORY_ONLY.hold -= 1
        return False

def requests_held() -> bool:
    return bool(getattr(_MEMORY_ONLY, "hold", 0))

def _refresh_mtimes() -> None:
    while True:
        with _MTIME_PENDING_LOCK:
            if not _MTIME_PENDING:
                return
            key = _MTIME_PENDING.pop()
        try:
            info = os.stat(key)
            mtime = info.st_mtime if not os.path.isdir(key) else None
        except OSError:
            mtime = None
        _MTIME_CACHE[key] = (time.monotonic(), mtime)
        with _MTIME_PENDING_LOCK:
            last = not _MTIME_PENDING
        if last:
            try:
                MTIME_SIGNALS.refreshed.emit()
            except RuntimeError:
                pass

def _queue_mtime(key: str) -> None:
    with _MTIME_PENDING_LOCK:
        start = not _MTIME_PENDING
        _MTIME_PENDING.add(key)
    if start:
        threading.Thread(target=_refresh_mtimes, name="mtime-refresh", daemon=True).start()

_REMOTE_DRIVES: dict[str, bool] = {}

def is_remote_path(path) -> bool:
    """Chemin sur un partage RESEAU (UNC « \\\\serveur\\partage » ou lecteur reseau) : chaque acces y est un
    aller-retour (ou une attente de plusieurs secondes si le serveur ne repond pas) — jamais sur le fil de
    l'interface quand on peut l'eviter. Type des lecteurs memorise (GetDriveTypeW, appel local)."""
    text = str(path)
    if text.startswith(("\\\\", "//")):
        return True
    if os.name == "nt" and len(text) >= 2 and text[1] == ":":
        drive = text[0].upper()
        hit = _REMOTE_DRIVES.get(drive)
        if hit is None:
            try:
                hit = ctypes.windll.kernel32.GetDriveTypeW(f"{drive}:\\") == 4      # DRIVE_REMOTE
            except Exception:                                # noqa: BLE001
                hit = False
            _REMOTE_DRIVES[drive] = hit
        return hit
    return False

def cached_mtime(path) -> float | None:
    """Date de modification du FICHIER `path` (None s'il n'existe pas ou est un dossier). Dans
    `memory_only()`, et toujours pour un chemin RESEAU : jamais de disque sur le fil appelant (valeur
    memorisee, ou None et relue en fond ; `MTIME_SIGNALS.refreshed` fait repeindre)."""
    key = str(path)
    now = time.monotonic()
    hit = _MTIME_CACHE.get(key)
    if hit is not None and now - hit[0] < _MTIME_TTL:
        return hit[1]
    if getattr(_MEMORY_ONLY, "on", 0) or is_remote_path(key):
        _queue_mtime(key)
        return hit[1] if hit is not None else None
    try:
        info = os.stat(key)
        mtime = info.st_mtime if not os.path.isdir(key) else None
    except OSError:
        mtime = None
    if len(_MTIME_CACHE) > 8192:
        _MTIME_CACHE.clear()
    _MTIME_CACHE[key] = (now, mtime)
    return mtime

def forget_mtime(path=None) -> None:
    """Oublie la date memorisee de `path` (de tout, sans argument) : a appeler apres avoir ecrit ou
    supprime une vignette / une icone."""
    if path is None:
        _MTIME_CACHE.clear()
    else:
        _MTIME_CACHE.pop(str(path), None)
