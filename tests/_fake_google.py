"""Faux serveur Google Calendar v3 en mémoire (tests de fm_agenda) : calendarList, events.list (jeton de
synchronisation incrémentale, pagination, 410 sur jeton invalidé), get, insert (id fourni, 409 s'il existe),
patch (If-Match -> 412, instances « <maître>_<date> » = exceptions de série), delete (annulé, id gardé).
Pannes simulées : `offline` (réseau coupé), `fail_next` (statuts HTTP imposés), `lose_response` (la requête
s'applique mais la réponse se perd)."""
import copy
import json
import urllib.parse

from fm_agenda.sync.provider import TransientError


class FakeTokens:
    def __init__(self):
        self.refreshes = 0

    def access_token(self, force=False):
        if force:
            self.refreshes += 1
        return "token-ok"


class FakeGoogle:
    def __init__(self, page_size=50):
        self.page_size = page_size
        self.calendars = {}
        self.events: dict[str, dict[str, dict]] = {}
        self.order: dict[str, list[str]] = {}
        self.seq = 0
        self.changed_at: dict[tuple, int] = {}
        self.invalid_before = 0                      # jetons antérieurs = 410
        self.offline = False
        self.fail_next: list[int] = []
        self.lose_response = False
        self.requests: list[tuple[str, str]] = []
        self.add_calendar("moi@example.com", "Moi", "owner", primary=True, color="#039be5")

    # -- état côté Google --

    def add_calendar(self, cal_id, name, role="owner", primary=False, color="#7986cb"):
        self.calendars[cal_id] = {"id": cal_id, "summary": name, "accessRole": role, "primary": primary,
                                  "backgroundColor": color, "timeZone": "Europe/Paris",
                                  "defaultReminders": [{"method": "popup", "minutes": 10}]}
        self.events.setdefault(cal_id, {})
        self.order.setdefault(cal_id, [])

    def _touch(self, cal_id, event_id):
        self.seq += 1
        item = self.events[cal_id][event_id]
        item["etag"] = f'"{self.seq}"'
        item["updated"] = f"2026-11-06T12:00:{self.seq % 60:02d}Z"
        self.changed_at[(cal_id, event_id)] = self.seq
        if event_id not in self.order[cal_id]:
            self.order[cal_id].append(event_id)

    def remote_insert(self, cal_id, item):
        item = copy.deepcopy(item)
        item.setdefault("status", "confirmed")
        item.setdefault("iCalUID", item["id"] + "@google.com")
        self.events[cal_id][item["id"]] = item
        self._touch(cal_id, item["id"])
        return item

    def remote_update(self, cal_id, event_id, **fields):
        self.events[cal_id][event_id].update(copy.deepcopy(fields))
        self._touch(cal_id, event_id)

    def remote_delete(self, cal_id, event_id):
        self.events[cal_id][event_id]["status"] = "cancelled"
        self._touch(cal_id, event_id)

    def live(self, cal_id):
        return {k: v for k, v in self.events[cal_id].items() if v.get("status") != "cancelled"}

    def invalidate_tokens(self):
        self.invalid_before = self.seq + 1

    # -- HTTP --

    def request(self, method, url, headers=None, body=None, timeout=None):
        if self.offline:
            raise TransientError("réseau indisponible (simulé)")
        parsed = urllib.parse.urlparse(url)
        path = parsed.path.replace("/calendar/v3", "")
        query = {k: v[0] for k, v in urllib.parse.parse_qs(parsed.query).items()}
        self.requests.append((method, path, query))
        if self.fail_next:
            status = self.fail_next.pop(0)
            reason = "rateLimitExceeded" if status == 403 else "backendError"
            return status, {}, json.dumps({"error": {"code": status, "message": "simulé",
                                                     "errors": [{"reason": reason}]}}).encode()
        if (headers or {}).get("Authorization") != "Bearer token-ok":
            return 401, {}, b'{"error": {"message": "invalid credentials"}}'
        payload = json.loads(body.decode("utf-8")) if body else None
        status, data = self._route(method, path, query, payload, headers or {})
        if self.lose_response and method in ("POST", "PATCH", "DELETE"):
            self.lose_response = False
            raise TransientError("réponse perdue (simulé)")
        return status, {}, json.dumps(data).encode("utf-8") if data is not None else b""

    def _route(self, method, path, query, payload, headers):
        parts = [urllib.parse.unquote(p) for p in path.strip("/").split("/")]
        if parts[:3] == ["users", "me", "calendarList"]:
            return 200, {"items": list(self.calendars.values())}
        if parts[0] != "calendars" or len(parts) < 3:
            return 404, {"error": {"message": "route"}}
        cal_id = parts[1]
        if cal_id not in self.events:
            return 404, {"error": {"message": "calendrier"}}
        role = self.calendars[cal_id]["accessRole"]
        if len(parts) == 3 and method == "GET":
            return self._list(cal_id, query)
        if len(parts) == 3 and method == "POST":
            if role not in ("owner", "writer"):
                return 403, {"error": {"message": "lecture seule", "errors": [{"reason": "forbidden"}]}}
            event_id = payload.get("id")
            if event_id in self.events[cal_id]:
                return 409, {"error": {"message": "duplicate"}}
            item = dict(payload)
            item.setdefault("status", "confirmed")
            item["iCalUID"] = f"{event_id}@google.com"
            self.events[cal_id][event_id] = item
            self._touch(cal_id, event_id)
            return 200, copy.deepcopy(item)
        event_id = parts[3]
        item = self.events[cal_id].get(event_id)
        if method == "GET":
            return (200, copy.deepcopy(item)) if item else (404, {"error": {"message": "absent"}})
        if role not in ("owner", "writer"):
            return 403, {"error": {"message": "lecture seule", "errors": [{"reason": "forbidden"}]}}
        if method == "PATCH":
            if item is None and "_" in event_id:
                master_id, rid = event_id.split("_", 1)
                master = self.events[cal_id].get(master_id)
                if master is None:
                    return 404, {"error": {"message": "série absente"}}
                item = {"id": event_id, "recurringEventId": master_id, "status": "confirmed",
                        "originalStartTime": ({"date": f"{rid[:4]}-{rid[4:6]}-{rid[6:8]}"} if "T" not in rid else
                                              {"dateTime": f"{rid[:4]}-{rid[4:6]}-{rid[6:8]}T{rid[9:11]}:"
                                                           f"{rid[11:13]}:{rid[13:15]}Z", "timeZone": "Europe/Paris"}),
                        "summary": master.get("summary", ""), "start": master["start"], "end": master["end"]}
                self.events[cal_id][event_id] = item
            if item is None:
                return 404, {"error": {"message": "absent"}}
            if headers.get("If-Match") and headers["If-Match"] != item.get("etag"):
                return 412, {"error": {"message": "precondition"}}
            for key, value in payload.items():
                if key == "extendedProperties":
                    ext = item.setdefault("extendedProperties", {}).setdefault("private", {})
                    ext.update(value.get("private", {}))
                elif value is None:
                    item.pop(key, None)
                else:
                    item[key] = value
            self._touch(cal_id, event_id)
            return 200, copy.deepcopy(item)
        if method == "DELETE":
            if item is None or item.get("status") == "cancelled":
                return 410, {"error": {"message": "deleted"}}
            if headers.get("If-Match") and headers["If-Match"] != item.get("etag"):
                return 412, {"error": {"message": "precondition"}}
            item["status"] = "cancelled"
            self._touch(cal_id, event_id)
            return 204, None
        return 404, {"error": {"message": "méthode"}}

    def _list(self, cal_id, query):
        token = query.get("syncToken")
        since = 0
        if token:
            since = int(token.split("-")[1])
            if since < self.invalid_before:
                return 410, {"error": {"message": "sync token invalidé"}}
        ids = [i for i in self.order[cal_id] if self.changed_at.get((cal_id, i), 0) > since]
        if not token:
            ids = [i for i in ids if self.events[cal_id][i].get("status") != "cancelled"]
        start = int(query.get("pageToken", "0"))
        page = ids[start:start + self.page_size]
        out = {"items": [copy.deepcopy(self.events[cal_id][i]) for i in page]}
        if start + self.page_size < len(ids):
            out["nextPageToken"] = str(start + self.page_size)
        else:
            out["nextSyncToken"] = f"tok-{self.seq}"
        return 200, out
