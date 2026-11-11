"""OAuth 2.0 pour application installée (recommandations Google pour Windows) : navigateur du SYSTÈME, redirection
vers une boucle locale `http://127.0.0.1:<port libre>`, PKCE (S256), paramètre `state` vérifié, accès hors ligne
(jeton d'actualisation). Le mot de passe Google n'est jamais vu par l'appli.

Le jeton d'actualisation va dans le Gestionnaire d'identifiants Windows (`credentials`) ; le jeton d'accès (une
heure) reste en mémoire. Révocation : `revoke` (déconnexion).

Préalable (une fois, par l'utilisateur) : un projet Google Cloud avec l'API Google Calendar activée et un
identifiant OAuth de type « Application de bureau » ; son fichier JSON s'importe dans Réglages : Agenda >
Synchronisation. Pas à pas : docs/agents/fm_agenda.md, « Connecter Google Agenda »."""
from __future__ import annotations

import base64
import hashlib
import http.server as _hs
import json
import secrets
import threading
import time
import urllib.parse
from dataclasses import dataclass
from pathlib import Path

from . import credentials
from .provider import AuthError, SyncError, TransientError

AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
TOKEN_URL = "https://oauth2.googleapis.com/token"
REVOKE_URL = "https://oauth2.googleapis.com/revoke"
SCOPES = ("openid", "email", "https://www.googleapis.com/auth/calendar.events",
          "https://www.googleapis.com/auth/calendar.readonly")
CLIENT_SECRET_NAME = "google/client"


@dataclass
class ClientConfig:
    client_id: str
    client_secret: str = ""


def load_client() -> ClientConfig | None:
    data = credentials.read_json(CLIENT_SECRET_NAME)
    if not data or not data.get("client_id"):
        return None
    return ClientConfig(data["client_id"], data.get("client_secret", ""))


def save_client(config: ClientConfig) -> None:
    credentials.write_json(CLIENT_SECRET_NAME, {"client_id": config.client_id, "client_secret": config.client_secret})


def import_client_json(path) -> ClientConfig:
    """Fichier téléchargé de la console Google Cloud (« client_secret_….json », section `installed`)."""
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    section = data.get("installed") or data.get("web") or data
    client_id = section.get("client_id", "")
    if not client_id.endswith(".apps.googleusercontent.com"):
        raise SyncError("fichier OAuth invalide (client_id Google attendu)")
    config = ClientConfig(client_id, section.get("client_secret", ""))
    save_client(config)
    return config


@dataclass
class Tokens:
    access_token: str
    expires_at: float
    refresh_token: str = ""
    email: str = ""

    def valid(self, margin: float = 60.0) -> bool:
        return bool(self.access_token) and time.time() < self.expires_at - margin


def _b64url(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def pkce_pair() -> tuple[str, str]:
    verifier = _b64url(secrets.token_bytes(48))
    challenge = _b64url(hashlib.sha256(verifier.encode("ascii")).digest())
    return verifier, challenge


def _email_from_id_token(id_token: str) -> str:
    """E-mail du compte (jeton reçu directement du point d'accès de Google sur TLS : pas de vérification de
    signature nécessaire pour ce seul usage d'affichage)."""
    try:
        payload = id_token.split(".")[1]
        payload += "=" * (-len(payload) % 4)
        return json.loads(base64.urlsafe_b64decode(payload)).get("email", "")
    except (IndexError, ValueError):
        return ""


def _post_form(http, url: str, data: dict) -> dict:
    body = urllib.parse.urlencode(data).encode("ascii")
    status, _h, raw = http.request("POST", url, {"Content-Type": "application/x-www-form-urlencoded"}, body)
    try:
        payload = json.loads(raw.decode("utf-8") or "{}")
    except ValueError:
        payload = {}
    if status >= 500:
        raise TransientError(f"Google indisponible ({status})")
    if status >= 400:
        error = payload.get("error", "")
        if error in ("invalid_grant", "unauthorized_client", "invalid_client"):
            raise AuthError(f"autorisation refusée ou révoquée ({error})")
        raise SyncError(f"OAuth : {error or status} {payload.get('error_description', '')}".strip())
    return payload


class _Handler(_hs.BaseHTTPRequestHandler):
    result: dict = {}
    done: threading.Event | None = None
    product = "Google Agenda"

    def do_GET(self):  # noqa: N802
        query = urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query)
        if "code" not in query and "error" not in query:
            self.send_response(404)
            self.end_headers()
            return
        type(self).result.update({k: v[0] for k, v in query.items()})
        ok = "code" in query
        page = ("<html><head><meta charset='utf-8'><title>PIPE FMZ</title></head><body style='font-family:Segoe UI;"
                "background:#16181a;color:#eef0f2;padding:40px'><h2>" + (
                    f"Connexion à {type(self).product} réussie." if ok else "Connexion refusée.") +
                "</h2><p>Vous pouvez fermer cet onglet et revenir dans PIPE FMZ.</p></body></html>")
        data = page.encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)
        if type(self).done is not None:
            type(self).done.set()

    def log_message(self, *args):
        pass


def authorize(client: ClientConfig, http, open_browser, timeout: float = 300.0,
              cancelled: threading.Event | None = None, scopes=SCOPES,
              product: str = "Google Agenda") -> Tokens:
    """Ouvre le consentement Google dans le navigateur et attend la redirection (BLOQUANT : fil de fond).
    `scopes` / `product` : portées demandées et nom montré (fm_taches : Google Tasks)."""
    verifier, challenge = pkce_pair()
    state = secrets.token_urlsafe(24)
    done = threading.Event()
    handler = type("Handler", (_Handler,), {"result": {}, "done": done, "product": product})
    server = _hs.HTTPServer(("127.0.0.1", 0), handler)       # boucle locale : jamais d'écoute hors de la machine
    port = server.server_address[1]
    redirect = f"http://127.0.0.1:{port}"
    thread = threading.Thread(target=server.serve_forever, kwargs={"poll_interval": 0.2}, daemon=True)
    thread.start()
    try:
        url = AUTH_URL + "?" + urllib.parse.urlencode({
            "client_id": client.client_id, "redirect_uri": redirect, "response_type": "code",
            "scope": " ".join(scopes), "code_challenge": challenge, "code_challenge_method": "S256",
            "state": state, "access_type": "offline", "prompt": "consent"})
        open_browser(url)
        end = time.time() + timeout
        while not done.wait(0.25):
            if time.time() > end:
                raise SyncError("connexion abandonnée (délai dépassé)")
            if cancelled is not None and cancelled.is_set():
                raise SyncError("connexion annulée")
        result = handler.result
    finally:
        server.shutdown()
        server.server_close()
    if result.get("state") != state:
        raise AuthError("réponse OAuth refusée (state différent)")
    if "error" in result:
        raise AuthError(f"consentement refusé ({result['error']})")
    payload = _post_form(http, TOKEN_URL, {
        "code": result["code"], "client_id": client.client_id, "client_secret": client.client_secret,
        "redirect_uri": redirect, "grant_type": "authorization_code", "code_verifier": verifier})
    return Tokens(payload.get("access_token", ""), time.time() + float(payload.get("expires_in", 3600)),
                  payload.get("refresh_token", ""), _email_from_id_token(payload.get("id_token", "")))


def refresh(client: ClientConfig, refresh_token: str, http) -> Tokens:
    payload = _post_form(http, TOKEN_URL, {"client_id": client.client_id, "client_secret": client.client_secret,
                                           "refresh_token": refresh_token, "grant_type": "refresh_token"})
    return Tokens(payload.get("access_token", ""), time.time() + float(payload.get("expires_in", 3600)),
                  payload.get("refresh_token", refresh_token))


def revoke(token: str, http) -> None:
    try:
        http.request("POST", REVOKE_URL + "?" + urllib.parse.urlencode({"token": token}),
                     {"Content-Type": "application/x-www-form-urlencoded"}, b"")
    except TransientError:
        pass


class TokenSource:
    """Jeton d'accès valide pour un compte : actualisé au besoin (jeton d'actualisation du coffre Windows)."""

    def __init__(self, account_id: str, http, client: ClientConfig | None = None):
        self.account_id = account_id
        self.http = http
        self.client = client
        self._tokens: Tokens | None = None
        self._lock = threading.Lock()

    def secret_name(self) -> str:
        return f"google/{self.account_id}"

    def store(self, tokens: Tokens) -> None:
        self._tokens = tokens
        if tokens.refresh_token:
            credentials.write_json(self.secret_name(), {"refresh_token": tokens.refresh_token,
                                                        "email": tokens.email})

    def access_token(self, force: bool = False) -> str:
        with self._lock:
            if not force and self._tokens is not None and self._tokens.valid():
                return self._tokens.access_token
            stored = credentials.read_json(self.secret_name()) or {}
            refresh_token = (self._tokens.refresh_token if self._tokens else "") or stored.get("refresh_token", "")
            if not refresh_token:
                raise AuthError("aucun jeton : reconnecter le compte Google")
            client = self.client or load_client()
            if client is None:
                raise AuthError("identifiant OAuth de l'application absent")
            tokens = refresh(client, refresh_token, self.http)
            tokens.email = stored.get("email", "")
            self._tokens = tokens
            if tokens.refresh_token != refresh_token:
                self.store(tokens)
            return tokens.access_token

    def forget(self, revoke_remote: bool = True) -> None:
        stored = credentials.read_json(self.secret_name()) or {}
        token = stored.get("refresh_token") or (self._tokens.refresh_token if self._tokens else "")
        if revoke_remote and token:
            revoke(token, self.http)
        credentials.delete_secret(self.secret_name())
        self._tokens = None
