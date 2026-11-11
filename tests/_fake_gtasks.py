"""Faux serveur Google Tasks v1 en mémoire (transport HTTP de remplacement) pour les tests de fm_taches : listes,
tâches (parent, position, terminées, supprimées), `updatedMin`, pages, `move`, etags, horloge réglable, coupure
réseau simulée (`offline`). Les méthodes `remote_*` jouent l'utilisateur qui modifie Google depuis son téléphone."""
import json
import urllib.parse
from datetime import datetime, timezone

from fm_agenda.sync.provider import TransientError


def _iso(ts: float) -> str:
    return datetime.fromtimestamp(ts, timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.000Z")


class FakeTokens:
    def access_token(self, force: bool = False) -> str:
        return "jeton-de-test"


class FakeGoogleTasks:
    def __init__(self, page_size: int = 100):
        self.now = 1_800_000_000.0
        self.lists: dict = {}
        self.tasks: dict = {}            # liste -> {id: élément}
        self.order: dict = {}            # (liste, parent) -> [ids]
        self.counter = 0
        self.page_size = page_size
        self.offline = False
        self.forbidden = ""              # message d'un refus 403 (API non activée…)
        self.calls: list = []

    def clock(self) -> float:
        return self.now

    def _tick(self) -> tuple[str, str]:
        self.now += 1
        self.counter += 1
        return f'"e{self.counter}"', _iso(self.now)

    def _new_id(self, prefix: str) -> str:
        self.counter += 1
        return f"{prefix}{self.counter}"

    # -- côté « téléphone » --

    def remote_list(self, title: str) -> str:
        lid = self._new_id("L")
        etag, _u = self._tick()
        self.lists[lid] = {"kind": "tasks#taskList", "id": lid, "title": title, "etag": etag}
        self.tasks[lid] = {}
        return lid

    def remote_task(self, lid: str, title: str, parent: str | None = None, **fields) -> str:
        return self._insert(lid, dict(fields, title=title), parent, None)["id"]

    def remote_edit(self, lid: str, tid: str, **fields) -> None:
        self._patch(lid, tid, fields)

    def remote_delete(self, lid: str, tid: str) -> None:
        item = self.tasks[lid][tid]
        item["deleted"] = True
        item["etag"], item["updated"] = self._tick()

    def live(self, lid: str) -> list:
        return [t for t in self.tasks[lid].values() if not t.get("deleted")]

    def by_title(self, lid: str, title: str) -> dict:
        return next(t for t in self.live(lid) if t["title"] == title)

    # -- mécanique --

    def _positions(self, lid: str, parent) -> None:
        for i, tid in enumerate(self.order.get((lid, parent), [])):
            self.tasks[lid][tid]["position"] = f"{i:020d}"

    def _place(self, lid: str, tid: str, parent, previous) -> None:
        for key in list(self.order):
            if key[0] == lid and tid in self.order[key]:
                self.order[key].remove(tid)
                self._positions(lid, key[1])
        sibs = self.order.setdefault((lid, parent), [])
        idx = sibs.index(previous) + 1 if previous in sibs else 0
        sibs.insert(idx, tid)
        item = self.tasks[lid][tid]
        if parent:
            item["parent"] = parent
        else:
            item.pop("parent", None)
        self._positions(lid, parent)

    def _insert(self, lid: str, body: dict, parent, previous) -> dict:
        tid = self._new_id("T")
        etag, updated = self._tick()
        item = {"kind": "tasks#task", "id": tid, "etag": etag, "updated": updated, "title": body.get("title", ""),
                "status": body.get("status", "needsAction"), "webViewLink": f"https://tasks.google.com/{tid}"}
        for key in ("notes", "due", "completed"):
            if body.get(key):
                item[key] = body[key]
        self.tasks[lid][tid] = item
        self._place(lid, tid, parent, previous)
        return dict(item)

    def _patch(self, lid: str, tid: str, body: dict) -> dict:
        item = self.tasks[lid][tid]
        for key, value in body.items():
            if value is None:
                item.pop(key, None)
            else:
                item[key] = value
        if item.get("status") == "needsAction":
            item.pop("completed", None)
        item["etag"], item["updated"] = self._tick()
        return dict(item)

    def request(self, method: str, url: str, headers=None, body=None, timeout=None):
        if self.offline:
            raise TransientError("réseau coupé (test)")
        parsed = urllib.parse.urlparse(url)
        path = [urllib.parse.unquote(p) for p in parsed.path.split("/tasks/v1/", 1)[1].split("/")]
        q = {k: v[0] for k, v in urllib.parse.parse_qs(parsed.query).items()}
        data = json.loads(body.decode("utf-8")) if body else {}
        self.calls.append((method, "/".join(path), q))
        if self.forbidden:
            payload = {"error": {"code": 403, "message": self.forbidden,
                                 "errors": [{"reason": "accessNotConfigured"}]}}
            return 403, {}, json.dumps(payload).encode("utf-8")
        try:
            status, payload = self._route(method, path, q, data)
        except KeyError:
            status, payload = 404, {"error": {"code": 404, "message": "Not Found"}}
        raw = json.dumps(payload).encode("utf-8") if payload is not None else b""
        return status, {}, raw

    def _route(self, method, path, q, data):
        if path[:2] == ["users", "@me"]:
            if len(path) == 3 and method == "GET":
                return 200, {"items": list(self.lists.values())}
            if len(path) == 3 and method == "POST":
                lid = self.remote_list(data.get("title", ""))
                return 200, self.lists[lid]
            lid = path[3]
            if lid not in self.lists:
                raise KeyError(lid)
            if method == "PATCH":
                self.lists[lid]["title"] = data.get("title", self.lists[lid]["title"])
                self.lists[lid]["etag"], _u = self._tick()
                return 200, self.lists[lid]
            if method == "DELETE":
                del self.lists[lid]
                del self.tasks[lid]
                return 204, None
        if path[0] == "lists":
            lid = path[1]
            if lid not in self.tasks:
                raise KeyError(lid)
            if len(path) == 3 and method == "GET":
                items = sorted(self.tasks[lid].values(), key=lambda t: t["updated"])
                if q.get("updatedMin"):
                    items = [t for t in items if t["updated"] >= q["updatedMin"]]
                if q.get("showDeleted") != "true":
                    items = [t for t in items if not t.get("deleted")]
                start = int(q.get("pageToken", 0))
                size = min(int(q.get("maxResults", 100)), self.page_size)
                page = items[start:start + size]
                out = {"items": [dict(t) for t in page]}
                if start + size < len(items):
                    out["nextPageToken"] = str(start + size)
                return 200, out
            if len(path) == 3 and method == "POST":
                return 200, self._insert(lid, data, q.get("parent"), q.get("previous"))
            tid = path[3]
            item = self.tasks[lid][tid]
            if item.get("deleted"):
                raise KeyError(tid)
            if len(path) == 5 and path[4] == "move":
                dest = q.get("destinationTasklist")
                if dest and dest != lid:
                    raise KeyError(dest)                 # (non utilisé : le moteur recrée dans la nouvelle liste)
                self._place(lid, tid, q.get("parent"), q.get("previous"))
                item["etag"], item["updated"] = self._tick()
                return 200, dict(item)
            if method == "PATCH":
                return 200, self._patch(lid, tid, data)
            if method == "DELETE":
                item["deleted"] = True
                item["etag"], item["updated"] = self._tick()
                for child in [t for t in self.tasks[lid].values() if t.get("parent") == tid]:
                    child["deleted"] = True
                    child["etag"], child["updated"] = self._tick()
                return 204, None
        raise KeyError("/".join(path))
