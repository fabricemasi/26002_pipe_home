"""Coffre des secrets de l'agenda : Gestionnaire d'identifiants Windows (identifiants « génériques », chiffrés par
Windows pour la session de l'utilisateur), par ctypes (aucune dépendance). Rien n'est écrit dans un fichier.

Cibles : `PIPE_FMZ/fm_agenda/google/client` (identifiant OAuth de l'application : client_id, client_secret — pour
une application de bureau Google le dit non confidentiel, il reste rangé ici) et
`PIPE_FMZ/fm_agenda/google/<compte>` (jeton d'actualisation). Taille maximale d'un secret : 2 560 octets.

Tests (`FM_AGENDA_TEST_CREDENTIALS`) : coffre en mémoire, jamais celui de Windows."""
from __future__ import annotations

import json
import os
import sys

PREFIX = "PIPE_FMZ/fm_agenda/"
_MEMORY: dict[str, str] = {}


def _testing() -> bool:
    return bool(os.environ.get("FM_AGENDA_TEST_CREDENTIALS")) or sys.platform != "win32"


if sys.platform == "win32":
    import ctypes
    from ctypes import wintypes

    CRED_TYPE_GENERIC = 1
    CRED_PERSIST_LOCAL_MACHINE = 2
    ERROR_NOT_FOUND = 1168

    class _FILETIME(ctypes.Structure):
        _fields_ = [("dwLowDateTime", wintypes.DWORD), ("dwHighDateTime", wintypes.DWORD)]

    class _CREDENTIALW(ctypes.Structure):
        _fields_ = [("Flags", wintypes.DWORD), ("Type", wintypes.DWORD), ("TargetName", wintypes.LPWSTR),
                    ("Comment", wintypes.LPWSTR), ("LastWritten", _FILETIME),
                    ("CredentialBlobSize", wintypes.DWORD), ("CredentialBlob", ctypes.POINTER(ctypes.c_ubyte)),
                    ("Persist", wintypes.DWORD), ("AttributeCount", wintypes.DWORD), ("Attributes", ctypes.c_void_p),
                    ("TargetAlias", wintypes.LPWSTR), ("UserName", wintypes.LPWSTR)]

    _advapi = ctypes.WinDLL("advapi32", use_last_error=True)
    _CredWrite = _advapi.CredWriteW
    _CredWrite.argtypes = [ctypes.POINTER(_CREDENTIALW), wintypes.DWORD]
    _CredWrite.restype = wintypes.BOOL
    _CredRead = _advapi.CredReadW
    _CredRead.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD, ctypes.POINTER(ctypes.POINTER(_CREDENTIALW))]
    _CredRead.restype = wintypes.BOOL
    _CredDelete = _advapi.CredDeleteW
    _CredDelete.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD]
    _CredDelete.restype = wintypes.BOOL
    _CredFree = _advapi.CredFree
    _CredFree.argtypes = [ctypes.c_void_p]


def write_secret(name: str, value: str) -> None:
    target = PREFIX + name
    if _testing():
        _MEMORY[target] = value
        return
    blob = value.encode("utf-8")
    if len(blob) > 2560:
        raise ValueError("secret trop long pour le Gestionnaire d'identifiants")
    buf = (ctypes.c_ubyte * len(blob)).from_buffer_copy(blob)
    cred = _CREDENTIALW()
    cred.Type = CRED_TYPE_GENERIC
    cred.TargetName = target
    cred.CredentialBlobSize = len(blob)
    cred.CredentialBlob = ctypes.cast(buf, ctypes.POINTER(ctypes.c_ubyte))
    cred.Persist = CRED_PERSIST_LOCAL_MACHINE
    cred.UserName = "fm_agenda"
    if not _CredWrite(ctypes.byref(cred), 0):
        raise OSError(ctypes.get_last_error(), "CredWrite a échoué")


def read_secret(name: str) -> str | None:
    target = PREFIX + name
    if _testing():
        return _MEMORY.get(target)
    pcred = ctypes.POINTER(_CREDENTIALW)()
    if not _CredRead(target, CRED_TYPE_GENERIC, 0, ctypes.byref(pcred)):
        return None
    try:
        size = pcred.contents.CredentialBlobSize
        data = ctypes.string_at(pcred.contents.CredentialBlob, size)
        return data.decode("utf-8")
    finally:
        _CredFree(pcred)


def delete_secret(name: str) -> None:
    target = PREFIX + name
    if _testing():
        _MEMORY.pop(target, None)
        return
    _CredDelete(target, CRED_TYPE_GENERIC, 0)


def write_json(name: str, value: dict) -> None:
    write_secret(name, json.dumps(value, separators=(",", ":")))


def read_json(name: str) -> dict | None:
    text = read_secret(name)
    if not text:
        return None
    try:
        data = json.loads(text)
        return data if isinstance(data, dict) else None
    except ValueError:
        return None


def clear_memory() -> None:
    _MEMORY.clear()
