"""Ouverture de la base SQLite de l'agenda : emplacement, réglages de connexion, migrations, sauvegardes,
contrôle d'intégrité et récupération après incident.

Emplacement par défaut : `%LOCALAPPDATA%\\PIPE_FMZ\\fm_agenda\\agenda.sqlite3`, HORS du dossier du projet (synchronisé
par un client cloud : une base SQLite et son journal WAL copiés à moitié par un client de synchronisation se
corrompent). Réglable (`agenda_data_dir`) ; `FM_AGENDA_DIR` le remplace (tests).

Connexions : WAL (lectures pendant une écriture), `synchronous=NORMAL` (durable à la transaction près en cas de
coupure de courant, sans attendre le disque à chaque commit), clés étrangères actives, attente de verrou 5 s.
Mode autocommit Python (`isolation_level=None`) : les transactions sont explicites (`transaction`).

Incident : un fichier témoin `agenda.sqlite3.open` existe tant que la base est ouverte ; s'il est encore là au
lancement suivant (arrêt brutal), `PRAGMA quick_check` vérifie la base. Base illisible : elle est mise de côté
(`agenda.corrupt-<date>.sqlite3`, jamais effacée) et la dernière sauvegarde est restaurée."""
from __future__ import annotations

import contextlib
import logging
import os
import shutil
import sqlite3
import time
from dataclasses import dataclass, field
from pathlib import Path

from . import schema

log = logging.getLogger("fm_agenda.store")

DB_NAME = "agenda.sqlite3"


def default_data_dir() -> Path:
    env = os.environ.get("FM_AGENDA_DIR")
    if env:
        return Path(env)
    base = os.environ.get("LOCALAPPDATA") or str(Path.home() / "AppData" / "Local")
    return Path(base) / "PIPE_FMZ" / "fm_agenda"


def resolve_data_dir(setting: str | None) -> Path:
    """Dossier des données : `FM_AGENDA_DIR` (tests) > réglage `agenda_data_dir` > défaut."""
    if os.environ.get("FM_AGENDA_DIR"):
        return Path(os.environ["FM_AGENDA_DIR"])
    if setting:
        return Path(os.path.expandvars(os.path.expanduser(setting)))
    return default_data_dir()


def connect(path: Path | str, readonly: bool = False) -> sqlite3.Connection:
    if readonly:
        uri = Path(path).resolve().as_uri() + "?mode=ro"
        conn = sqlite3.connect(uri, uri=True, timeout=5.0, isolation_level=None, check_same_thread=False)
    else:
        conn = sqlite3.connect(str(path), timeout=5.0, isolation_level=None, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA busy_timeout = 5000")
    conn.execute("PRAGMA temp_store = MEMORY")
    conn.execute("PRAGMA cache_size = -16000")
    if not readonly:
        conn.execute("PRAGMA journal_mode = WAL")
        conn.execute("PRAGMA synchronous = NORMAL")
    return conn


@contextlib.contextmanager
def transaction(conn: sqlite3.Connection, immediate: bool = True):
    """Transaction explicite : tout ou rien. IMMEDIATE prend le verrou d'écriture d'emblée (pas d'échec de mise à
    niveau du verrou en cours de route quand l'autre fil écrit aussi)."""
    conn.execute("BEGIN IMMEDIATE" if immediate else "BEGIN")
    try:
        yield conn
    except BaseException:
        conn.execute("ROLLBACK")
        raise
    else:
        conn.execute("COMMIT")


@dataclass
class OpenReport:
    path: Path
    created: bool = False
    migrated_from: int | None = None
    recovered_from: Path | None = None          # sauvegarde restaurée
    quarantined: Path | None = None             # base illisible mise de côté
    checked: bool = False
    messages: list[str] = field(default_factory=list)


def _marker(path: Path) -> Path:
    return path.with_name(path.name + ".open")


def backups_dir(path: Path) -> Path:
    return path.parent / "backups"


def _integrity_ok(path: Path) -> bool:
    try:
        conn = sqlite3.connect(str(path), timeout=5.0)
        try:
            row = conn.execute("PRAGMA quick_check").fetchone()
            return bool(row) and row[0] == "ok"
        finally:
            conn.close()
    except sqlite3.DatabaseError:
        return False


def latest_backup(path: Path, prefix: str = "agenda") -> Path | None:
    folder = backups_dir(path)
    if not folder.is_dir():
        return None
    files = sorted(folder.glob(f"{prefix}-*.sqlite3"), key=lambda p: p.stat().st_mtime, reverse=True)
    for candidate in files:
        if _integrity_ok(candidate):
            return candidate
    return None


def backup(conn: sqlite3.Connection, dest: Path) -> Path:
    """Copie cohérente de la base OUVERTE (API de sauvegarde de SQLite : jamais une copie de fichier pendant une
    écriture)."""
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.with_suffix(".tmp")
    target = sqlite3.connect(str(tmp))
    try:
        conn.backup(target)
    finally:
        target.close()
    os.replace(tmp, dest)
    return dest


def backup_name(prefix: str = "agenda") -> str:
    return time.strftime(f"{prefix}-%Y%m%d-%H%M%S.sqlite3")


def rotate_backups(path: Path, keep: int, prefix: str = "agenda") -> list[Path]:
    folder = backups_dir(path)
    if not folder.is_dir():
        return []
    files = sorted(folder.glob(f"{prefix}-*.sqlite3"), key=lambda p: p.stat().st_mtime, reverse=True)
    removed = []
    for old in files[max(1, keep):]:
        try:
            old.unlink()
            removed.append(old)
        except OSError:
            pass
    return removed


def _quarantine(path: Path, prefix: str = "agenda") -> Path:
    target = path.with_name(time.strftime(f"{prefix}.corrupt-%Y%m%d-%H%M%S.sqlite3"))
    os.replace(path, target)
    for suffix in ("-wal", "-shm"):
        side = path.with_name(path.name + suffix)
        if side.exists():
            try:
                os.replace(side, target.with_name(target.name + suffix))
            except OSError:
                pass
    return target


def migrate(conn: sqlite3.Connection, migrations=None) -> int | None:
    """Applique les migrations manquantes ; rend l'ancienne version (None si rien à faire). `migrations` : liste
    (version, script) d'une autre base (fm_taches) ; défaut = schéma de l'agenda."""
    migrations = schema.MIGRATIONS if migrations is None else migrations
    current = conn.execute("PRAGMA user_version").fetchone()[0]
    if current >= migrations[-1][0]:
        return None
    for version, script in migrations:
        if version <= current:
            continue
        with transaction(conn):
            for statement in _statements(script):
                conn.execute(statement)
            conn.execute(f"PRAGMA user_version = {version}")
    return current


def _statements(script: str) -> list[str]:
    out, buf = [], []
    for line in script.splitlines():
        if line.strip().startswith("--"):
            continue
        buf.append(line)
        if sqlite3.complete_statement("\n".join(buf)):
            text = "\n".join(buf).strip()
            if text:
                out.append(text)
            buf = []
    rest = "\n".join(buf).strip()
    if rest:
        out.append(rest)
    return out


def open_database(path: Path, migrations=None, prefix: str = "agenda",
                  label: str = "de l'agenda") -> tuple[sqlite3.Connection, OpenReport]:
    """Ouvre (crée, vérifie, migre) la base ; rend la connexion d'ÉCRITURE et le rapport d'ouverture.
    `migrations` / `prefix` (sauvegardes, base mise de côté) / `label` (messages) : réutilisé par fm_taches."""
    migrations = schema.MIGRATIONS if migrations is None else migrations
    latest = migrations[-1][0]
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    report = OpenReport(path=path, created=not path.exists())
    marker = _marker(path)
    if path.exists() and marker.exists():
        report.checked = True
        if not _integrity_ok(path):
            report.quarantined = _quarantine(path, prefix)
            report.messages.append(f"Base {label} endommagée : mise de côté ({report.quarantined.name}).")
            source = latest_backup(path, prefix)
            if source is not None:
                shutil.copyfile(source, path)
                report.recovered_from = source
                report.messages.append(f"Dernière sauvegarde restaurée ({source.name}).")
            else:
                report.created = True
                report.messages.append("Aucune sauvegarde lisible : base neuve.")
    try:
        conn = connect(path)
        version = conn.execute("PRAGMA user_version").fetchone()[0]
    except sqlite3.DatabaseError as exc:
        report.quarantined = _quarantine(path, prefix)
        report.messages.append(f"Base {label} illisible ({exc}) : mise de côté.")
        conn = connect(path)
        version = 0
    if 0 < version < latest:
        backup(conn, backups_dir(path) / time.strftime(f"{prefix}-avant-v{latest}-%Y%m%d-%H%M%S.sqlite3"))
    report.migrated_from = migrate(conn, migrations)
    try:
        marker.write_text(str(os.getpid()), encoding="ascii")
    except OSError:
        pass
    return conn, report


def close_database(conn: sqlite3.Connection, path: Path) -> None:
    try:
        conn.execute("PRAGMA optimize")
        conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
    except sqlite3.DatabaseError:
        pass
    conn.close()
    try:
        _marker(Path(path)).unlink()
    except OSError:
        pass
