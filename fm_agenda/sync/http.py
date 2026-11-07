"""Transport HTTP de la synchronisation (bibliothèque standard, TLS vérifié) : une requête -> (statut, en-têtes,
corps). Remplaçable (tests : faux serveur Google en mémoire). `FM_AGENDA_NO_NETWORK` coupe tout accès réseau."""
from __future__ import annotations

import os
import socket
import ssl
import urllib.error
import urllib.request

from .provider import TransientError

USER_AGENT = "PIPE-FMZ-fm_agenda/1.0"


class HttpTransport:
    def __init__(self, timeout: float = 30.0):
        self.timeout = timeout
        self._ctx = ssl.create_default_context()

    def request(self, method: str, url: str, headers: dict | None = None, body: bytes | None = None,
                timeout: float | None = None) -> tuple[int, dict, bytes]:
        if os.environ.get("FM_AGENDA_NO_NETWORK"):
            raise TransientError("réseau désactivé (FM_AGENDA_NO_NETWORK)")
        req = urllib.request.Request(url, data=body, method=method)
        req.add_header("User-Agent", USER_AGENT)
        for key, value in (headers or {}).items():
            req.add_header(key, value)
        try:
            with urllib.request.urlopen(req, timeout=timeout or self.timeout, context=self._ctx) as resp:
                return resp.status, {k.lower(): v for k, v in resp.headers.items()}, resp.read()
        except urllib.error.HTTPError as exc:
            data = exc.read() if exc.fp is not None else b""
            return exc.code, {k.lower(): v for k, v in (exc.headers or {}).items()}, data
        except (urllib.error.URLError, socket.timeout, TimeoutError, ConnectionError, ssl.SSLError, OSError) as exc:
            raise TransientError(f"réseau indisponible : {getattr(exc, 'reason', exc)}") from exc
