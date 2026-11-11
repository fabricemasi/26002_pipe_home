"""Client Google Tasks v1 : le transport, les reprises (attente exponentielle, quotas), l'actualisation du jeton
sur 401 et les erreurs typées viennent de `fm_agenda.sync.google.GoogleProvider` (seule la racine de l'API
change). Jeton d'actualisation à part de l'Agenda (`taches/google/<compte>` dans le coffre) : connecter ou
déconnecter les tâches ne touche pas l'agenda."""
from __future__ import annotations

import urllib.parse

from fm_agenda.sync import oauth
from fm_agenda.sync.google import GoogleProvider

API_TASKS = "https://tasks.googleapis.com/tasks/v1"
SCOPES = ("openid", "email", "https://www.googleapis.com/auth/tasks")
PAGE = 100


def _q(value: str) -> str:
    return urllib.parse.quote(value, safe="")


class TasksTokenSource(oauth.TokenSource):
    def secret_name(self) -> str:
        return f"taches/google/{self.account_id}"


class GoogleTasksProvider(GoogleProvider):
    name = "google_tasks"
    api = API_TASKS

    # -- listes --

    def list_tasklists(self) -> list[dict]:
        out, token = [], None
        while True:
            params = {"maxResults": PAGE}
            if token:
                params["pageToken"] = token
            page = self._call("GET", "/users/@me/lists", params)
            out += page.get("items", [])
            token = page.get("nextPageToken")
            if not token:
                return out

    def insert_tasklist(self, title: str) -> dict:
        return self._call("POST", "/users/@me/lists", body={"title": title})

    def patch_tasklist(self, remote_id: str, title: str) -> dict:
        return self._call("PATCH", f"/users/@me/lists/{_q(remote_id)}", body={"title": title})

    def delete_tasklist(self, remote_id: str) -> None:
        self._call("DELETE", f"/users/@me/lists/{_q(remote_id)}")

    # -- tâches --

    def list_tasks(self, tasklist: str, updated_min: str | None = None) -> list[dict]:
        """Toutes les tâches (terminées, masquées et supprimées comprises) modifiées depuis `updated_min`."""
        out, token = [], None
        while True:
            params = {"maxResults": PAGE, "showCompleted": "true", "showHidden": "true", "showDeleted": "true"}
            if updated_min:
                params["updatedMin"] = updated_min
            if token:
                params["pageToken"] = token
            page = self._call("GET", f"/lists/{_q(tasklist)}/tasks", params)
            out += page.get("items", [])
            token = page.get("nextPageToken")
            if not token:
                return out

    def insert_task(self, tasklist: str, body: dict, parent: str | None = None,
                    previous: str | None = None) -> dict:
        params = {k: v for k, v in (("parent", parent), ("previous", previous)) if v}
        return self._call("POST", f"/lists/{_q(tasklist)}/tasks", params or None, body)

    def patch_task(self, tasklist: str, remote_id: str, body: dict) -> dict:
        return self._call("PATCH", f"/lists/{_q(tasklist)}/tasks/{_q(remote_id)}", body=body)

    def delete_task(self, tasklist: str, remote_id: str) -> None:
        self._call("DELETE", f"/lists/{_q(tasklist)}/tasks/{_q(remote_id)}")

    def move_task(self, tasklist: str, remote_id: str, parent: str | None = None, previous: str | None = None,
                  destination: str | None = None) -> dict:
        params = {k: v for k, v in (("parent", parent), ("previous", previous),
                                    ("destinationTasklist", destination)) if v}
        return self._call("POST", f"/lists/{_q(tasklist)}/tasks/{_q(remote_id)}/move", params or None)
