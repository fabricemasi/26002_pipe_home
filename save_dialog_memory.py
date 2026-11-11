"""Derniers dossiers d'ENREGISTREMENT / d'EXPORT et d'OUVERTURE retenus pour toute l'appli (demande de l'utilisateur,
2026-11-08).

`install()` (appele par `pipeline_browser.main`) enveloppe les boites statiques de `QFileDialog` :
- `getSaveFileName` : chaque boite « Enregistrer / Exporter » s'ouvre dans le dossier du DERNIER fichier enregistre,
  avec le nom de fichier qu'elle proposait (cle `last_save_dir`) ;
- `getOpenFileName`, `getOpenFileNames`, `getExistingDirectory` : chaque boite « Ouvrir / Charger / Importer »
  s'ouvre dans le dossier du DERNIER fichier (ou dossier) charge (cle `last_open_dir`).
Dossiers enregistres par `settings_store.save_live_state`, gardes d'une session a l'autre. Aucun appelant a
modifier."""
from __future__ import annotations

from pathlib import Path

from PySide6.QtWidgets import QFileDialog

_ORIGINALS: dict = {}
_STATE = {"dir": "", "open": ""}
# fonction -> (memoire, le resultat est un dossier)
_WRAPPED = {"getSaveFileName": ("dir", False), "getOpenFileName": ("open", False),
            "getOpenFileNames": ("open", False), "getExistingDirectory": ("open", True)}
_KEYS = {"dir": "last_save_dir", "open": "last_open_dir"}


def remembered(kind: str = "dir") -> str:
    return _STATE[kind]


def start_path(suggested: str, last: str) -> str:
    """Chemin de depart : le nom propose par l'appelant dans le dernier dossier retenu (qui doit exister) ; sans
    dossier retenu, la suggestion telle quelle."""
    if not last or not Path(last).is_dir():
        return suggested
    if not suggested:
        return last
    path = Path(suggested)
    if path.is_dir():
        return last                                     # l'appelant ne proposait qu'un dossier
    return str(Path(last) / path.name)


def remember(chosen: str, kind: str = "dir", is_dir: bool = False) -> None:
    """Fichier (ou dossier) choisi : son dossier devient le dossier de depart des prochaines boites du meme genre."""
    if not chosen:
        return
    folder = str(Path(chosen)) if is_dir else str(Path(chosen).parent)
    if folder == _STATE[kind]:
        return
    _STATE[kind] = folder
    try:
        from settings_store import save_live_state
        save_live_state(_KEYS[kind], folder)
    except Exception:                                   # noqa: BLE001 - jamais bloquer un enregistrement
        pass


def _wrapper(name: str):
    kind, is_dir = _WRAPPED[name]
    # getExistingDirectory(parent, caption, dir, options) : la suggestion est un dossier, gardee telle quelle
    # s'il n'y a rien de retenu ; les autres : nom de fichier propose garde dans le dernier dossier.

    def wrapped(*args, **kwargs):
        args = list(args)
        last = _STATE[kind]
        if len(args) >= 3:
            args[2] = last if (is_dir and last and Path(last).is_dir()) else start_path(args[2] or "", last)
        else:
            current = kwargs.get("dir") or ""
            kwargs["dir"] = last if (is_dir and last and Path(last).is_dir()) else start_path(current, last)
        result = _ORIGINALS[name](*args, **kwargs)     # lu a l'appel (les tests le remplacent)
        chosen = result[0] if isinstance(result, tuple) else result
        if isinstance(chosen, list):                    # getOpenFileNames : le premier fichier choisi
            chosen = chosen[0] if chosen else ""
        remember(chosen, kind, is_dir)
        return result
    return wrapped


def install(settings: dict | None = None) -> None:
    """Une seule fois : dossiers retenus lus dans les reglages, boites de fichiers enveloppees."""
    settings = settings or {}
    for kind, key in _KEYS.items():
        last = str(settings.get(key) or "")
        if last:
            _STATE[kind] = last
    for name in _WRAPPED:
        if name not in _ORIGINALS:
            _ORIGINALS[name] = getattr(QFileDialog, name)
            setattr(QFileDialog, name, staticmethod(_wrapper(name)))
