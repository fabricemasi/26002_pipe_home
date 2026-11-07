"""Service de l'agenda en cours (posé par la fenêtre principale) : les champs de la fenêtre de réglages (comptes
Google, données) y accèdent sans importer la fenêtre principale."""
from __future__ import annotations

_STATE: dict = {"service": None, "start": None}


def set_service(service, start=None) -> None:
    _STATE["service"] = service
    if start is not None:
        _STATE["start"] = start


def service():
    """Le service ouvert ; à défaut, le démarre par la fenêtre (si elle l'a permis)."""
    if _STATE["service"] is None and callable(_STATE["start"]):
        try:
            _STATE["service"] = _STATE["start"]()
        except Exception:                                # noqa: BLE001
            return None
    return _STATE["service"]


def manager():
    s = service()
    return getattr(s, "sync", None) if s is not None else None
