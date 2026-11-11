"""Emplacement et ouverture de la base des tâches. Tout le reste (connexions WAL, transactions, sauvegardes,
contrôle après arrêt brutal, base illisible mise de côté) vient de `fm_agenda.store.database`, paramétré.

Emplacement par défaut : `%LOCALAPPDATA%\\PIPE_FMZ\\fm_taches\\taches.sqlite3`, HORS du dossier du projet (dossier
synchronisé par un client cloud, qui corrompt une base WAL copiée à moitié). Réglage `taches_data_dir` ;
`FM_TACHES_DIR` le remplace (tests)."""
from __future__ import annotations

import os
import time
from pathlib import Path

from fm_agenda.store import database as _db
from fm_agenda.store.database import backup, backups_dir, close_database, connect, transaction  # noqa: F401

from . import schema

DB_NAME = "taches.sqlite3"
PREFIX = "taches"


def default_data_dir() -> Path:
    env = os.environ.get("FM_TACHES_DIR")
    if env:
        return Path(env)
    base = os.environ.get("LOCALAPPDATA") or str(Path.home() / "AppData" / "Local")
    return Path(base) / "PIPE_FMZ" / "fm_taches"


def resolve_data_dir(setting: str | None) -> Path:
    """`FM_TACHES_DIR` (tests) > réglage `taches_data_dir` > défaut."""
    if os.environ.get("FM_TACHES_DIR"):
        return Path(os.environ["FM_TACHES_DIR"])
    if setting:
        return Path(os.path.expandvars(os.path.expanduser(setting)))
    return default_data_dir()


def open_database(path: Path):
    return _db.open_database(path, schema.MIGRATIONS, prefix=PREFIX, label="des tâches")


def backup_name() -> str:
    return time.strftime(f"{PREFIX}-%Y%m%d-%H%M%S.sqlite3")


def rotate_backups(path: Path, keep: int) -> list[Path]:
    return _db.rotate_backups(path, keep, PREFIX)
