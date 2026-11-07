"""Fichiers (sans Qt) : lecture en une fois (réseau : un seul passage), écriture TRANSACTIONNELLE vérifiée,
détection d'une modification extérieure, sauvegarde de secours.

Écriture : fichier temporaire dans le MÊME dossier (même volume : le remplacement est atomique, chemins UNC
compris) -> écriture + fsync -> VÉRIFICATION (relecture par qpdf : structure et nombre de pages) -> os.replace.
Fichier cible verrouillé (ouvert dans une autre application) : quelques essais espacés puis `LockedError` ; le
temporaire est supprimé, l'original n'est jamais touché tant que la copie n'est pas vérifiée.
"""
from __future__ import annotations

import hashlib
import io
import os
import pathlib
import time


class SaveError(OSError):
    pass


class LockedError(SaveError):
    """Le fichier cible est verrouillé (ouvert ailleurs, lecture seule, droits)."""


def read_file(path) -> bytes:
    with open(path, "rb") as f:
        return f.read()


def signature(path) -> tuple | None:
    """(taille, date de modification ns) ou None si absent : détecte une modification par un autre logiciel."""
    try:
        st = os.stat(path)
    except OSError:
        return None
    return st.st_size, st.st_mtime_ns


def verify_pdf(data: bytes, expected_pages: int | None = None) -> None:
    """Relit les octets par qpdf : structure lisible et nombre de pages attendu ; SaveError sinon."""
    import pikepdf
    try:
        with pikepdf.open(io.BytesIO(data)) as pdf:
            n = len(pdf.pages)
    except Exception as exc:                              # noqa: BLE001
        raise SaveError("copie illisible (%s) : l'original est conservé" % exc) from exc
    if expected_pages is not None and n != expected_pages:
        raise SaveError("copie incohérente (%d pages au lieu de %d) : l'original est conservé" % (n, expected_pages))


def write_atomic(path, data: bytes, *, verify=None, retries: int = 4) -> None:
    path = pathlib.Path(path)
    if verify is not None:
        verify(data)
    tmp = path.with_name("~%s.%d.tmp" % (path.name, os.getpid()))
    try:
        with open(tmp, "wb") as f:
            f.write(data)
            f.flush()
            os.fsync(f.fileno())
        for attempt in range(retries + 1):
            try:
                os.replace(tmp, path)
                return
            except PermissionError as exc:
                if attempt == retries:
                    raise LockedError("« %s » est verrouillé (ouvert dans une autre application ?) : rien n'a été "
                                      "remplacé" % path.name) from exc
                time.sleep(0.15 * (attempt + 1))
    finally:
        try:
            if tmp.exists():
                tmp.unlink()
        except OSError:
            pass


def recovery_dir() -> pathlib.Path:
    base = os.environ.get("FM_PDF_RECOVERY_DIR")
    if base:
        return pathlib.Path(base)
    return pathlib.Path(__file__).resolve().parent.parent / "data" / "pdf_recovery"


def recovery_path(original) -> pathlib.Path:
    key = hashlib.sha1(str(pathlib.Path(original).resolve()).lower().encode("utf-8")).hexdigest()[:16]
    return recovery_dir() / ("%s_%s" % (key, pathlib.Path(original).name))


def write_recovery(original, data: bytes) -> pathlib.Path:
    target = recovery_path(original)
    target.parent.mkdir(parents=True, exist_ok=True)
    write_atomic(target, data)
    return target


def drop_recovery(original) -> None:
    try:
        recovery_path(original).unlink()
    except OSError:
        pass


def pending_recovery(original) -> pathlib.Path | None:
    """Copie de secours PLUS RÉCENTE que le fichier (incident pendant une modification), sinon None."""
    target = recovery_path(original)
    try:
        if target.stat().st_mtime > os.stat(original).st_mtime:
            return target
    except OSError:
        return None
    return None
