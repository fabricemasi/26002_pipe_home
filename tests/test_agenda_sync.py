"""fm_agenda : synchronisation Google SIMULÉE (faux serveur `_fake_google.py`, aucun réseau) — réception
initiale et incrémentale, envoi, idempotence (aucun doublon, réponse perdue), conflits (fusion à trois voies,
résolution), jeton invalidé (410), hors connexion, quotas et jeton expiré, séries et exceptions, droits, OAuth."""
from _agenda_case import AgendaCase, paris, settle

import base64
import json
import tempfile
import unittest
from datetime import date, timedelta
from pathlib import Path

from PySide6.QtCore import QCoreApplication

from _fake_google import FakeGoogle, FakeTokens
from fm_agenda.sync import credentials, oauth
from fm_agenda.sync.google import GoogleProvider
from fm_agenda.sync.manager import SyncManager
from fm_agenda.sync.provider import AuthError, TransientError

CAL = "moi@example.com"


def g_event(event_id, summary, start, end, **extra):
    item = {"id": event_id, "summary": summary,
            "start": {"dateTime": start.isoformat(), "timeZone": "Europe/Paris"},
            "end": {"dateTime": end.isoformat(), "timeZone": "Europe/Paris"}}
    item.update(extra)
    return item


class SyncCase(AgendaCase):
    def setUp(self):
        super().setUp()
        credentials.clear_memory()
        self.google = FakeGoogle(page_size=3)
        self.tokens = FakeTokens()
        self.manager = SyncManager(self.service, http=self.google,
                                   provider_factory=lambda account: GoogleProvider(self.tokens, self.google,
                                                                                   sleep=lambda s: None))
        self.service.sync = self.manager
        self.service.writer.submit(lambda repo: repo.upsert_account(
            {"id": "acc", "provider": "google", "email": CAL, "status": "connected", "created_at": 1}))
        settle(self.service)

    def tearDown(self):
        self.manager.stop()
        super().tearDown()

    def sync(self):
        results = []
        self.manager.sync_now(on_done=results.append)
        self.manager.wait_idle()
        for _ in range(4):
            QCoreApplication.processEvents()
        settle(self.service)
        return results[-1] if results else None

    def gcal(self):
        cal = next((c for c in self.service.calendars() if c.remote_id == CAL), None)
        if cal is None:                                  # le calendrier Google arrive avec la première synchro
            self.sync()
            cal = next(c for c in self.service.calendars() if c.remote_id == CAL)
        return cal

    def local(self, start=date(2026, 11, 1), end=date(2026, 12, 1)):
        cal = self.gcal()
        return [o for o in self.service.occurrences(start, end, visible_only=False) if o.calendar_id == cal.id]

    def create_local(self, title, start, end, **fields):
        draft = self.service.new_draft(start, end, calendar_id=self.gcal().id)
        draft.title = title
        for k, v in fields.items():
            setattr(draft, k, v)
        eid = self.service.create(draft)
        settle(self.service)
        return eid


class InitialAndIncrementalTest(SyncCase):
    def test_initial_sync_imports_calendars_and_events_without_duplicates(self):
        self.google.add_calendar("anniv@group", "Anniversaires", "reader")
        for i in range(7):                               # 7 événements, pages de 3
            s = paris(2026, 11, 2 + i, 10)
            self.google.remote_insert(CAL, g_event(f"g{i}", f"Revue {i}", s, s + timedelta(hours=1)))
        self.google.remote_insert(CAL, {"id": "jour", "summary": "Jalon", "start": {"date": "2026-11-20"},
                                        "end": {"date": "2026-11-21"}})
        report = self.sync()
        self.assertEqual(report.created, 8)
        names = {c.name: c for c in self.service.calendars()}
        self.assertTrue(names["Anniversaires"].read_only)
        self.assertEqual(len(self.local()), 8)
        report = self.sync()                             # second passage : rien de neuf, aucun doublon
        self.assertEqual((report.created, report.updated), (0, 0))
        self.assertEqual(len(self.local()), 8)
        self.reopen()
        self.service.sync = self.manager
        self.assertEqual(len(self.local()), 8)           # persistant

    def test_remote_changes_and_deletions_are_applied_incrementally(self):
        s = paris(2026, 11, 3, 10)
        self.google.remote_insert(CAL, g_event("a", "Revue", s, s + timedelta(hours=1)))
        self.google.remote_insert(CAL, g_event("b", "Point", s, s + timedelta(hours=2)))
        self.sync()
        self.google.remote_update(CAL, "a", summary="Revue client", location="Visio")
        self.google.remote_delete(CAL, "b")
        report = self.sync()
        self.assertEqual((report.updated, report.deleted), (1, 1))
        occs = self.local()
        self.assertEqual([(o.title, o.location) for o in occs], [("Revue client", "Visio")])
        lists = [q for m, p, q in self.google.requests if m == "GET" and p.endswith("/events")]
        self.assertIn("timeMin", lists[0])               # première fois : complète (fenêtre dans le passé)
        self.assertIn("syncToken", lists[-1])            # ensuite : incrémentale

    def test_local_create_update_delete_are_pushed(self):
        eid = self.create_local("Revue lookdev", paris(2026, 11, 4, 11), paris(2026, 11, 4, 12), project="26017")
        self.sync()
        remote = self.google.live(CAL)
        self.assertIn(eid, remote)                       # même identifiant que le local
        self.assertEqual(remote[eid]["extendedProperties"]["private"]["pipeProject"], "26017")
        self.google.events[CAL][eid]["conferenceData"] = {"id": "meet"}     # champ que l'agenda ne connaît pas
        occ = self.local()[0]
        draft = self.service.draft_for(occ)
        draft.title = "Revue lookdev V2"
        self.service.save_draft(occ, draft)
        settle(self.service)
        self.sync()
        self.assertEqual(self.google.events[CAL][eid]["summary"], "Revue lookdev V2")
        self.assertEqual(self.google.events[CAL][eid]["conferenceData"], {"id": "meet"})   # PATCH minimal
        self.service.delete_occurrence(self.local()[0])
        settle(self.service)
        self.sync()
        self.assertEqual(self.google.live(CAL), {})
        self.assertIsNone(self.service.repo.get_event(eid))     # pierre tombale effacée après confirmation

    def test_lost_response_does_not_duplicate(self):
        eid = self.create_local("Livraison", paris(2026, 11, 6, 15), paris(2026, 11, 6, 16))
        self.google.lose_response = True                 # l'insertion réussit, la réponse se perd
        self.sync()
        self.assertEqual(len(self.google.live(CAL)), 1)
        self.sync()                                      # nouvel essai : 409 -> relu -> même événement
        self.assertEqual(list(self.google.live(CAL)), [eid])
        self.assertEqual(len(self.local()), 1)
        self.assertEqual(self.service.repo.outbox_count(), 0)


class ConflictTest(SyncCase):
    def _shared(self):
        eid = self.create_local("Revue", paris(2026, 11, 5, 10), paris(2026, 11, 5, 11))
        self.sync()
        return eid

    def test_concurrent_title_changes_keep_both_versions(self):
        eid = self._shared()
        occ = self.local()[0]
        draft = self.service.draft_for(occ)
        draft.title = "Revue (PIPE)"
        self.service.save_draft(occ, draft)
        settle(self.service)
        self.google.remote_update(CAL, eid, summary="Revue (Google)")
        report = self.sync()
        self.assertEqual(report.conflicts, 1)
        self.assertEqual(self.local()[0].title, "Revue (PIPE)")        # rien d'écrasé
        self.assertEqual(self.google.events[CAL][eid]["summary"], "Revue (Google)")
        conflicts = self.manager.conflicts()
        self.assertEqual(conflicts[0]["fields"], ["title"])
        self.assertEqual(conflicts[0]["remote"]["title"], "Revue (Google)")
        self.manager.resolve_conflict(conflicts[0], "local")
        self.manager.wait_idle()
        for _ in range(4):
            QCoreApplication.processEvents()
        settle(self.service)
        self.assertEqual(self.google.events[CAL][eid]["summary"], "Revue (PIPE)")
        self.assertEqual(self.manager.conflicts(), [])

    def test_resolve_with_the_remote_version(self):
        eid = self._shared()
        occ = self.local()[0]
        draft = self.service.draft_for(occ)
        draft.title = "Ici"
        self.service.save_draft(occ, draft)
        settle(self.service)
        self.google.remote_update(CAL, eid, summary="Là-bas")
        self.sync()
        self.manager.resolve_conflict(self.manager.conflicts()[0], "remote")
        self.manager.wait_idle()
        for _ in range(4):
            QCoreApplication.processEvents()
        settle(self.service)
        self.assertEqual(self.local()[0].title, "Là-bas")
        self.assertEqual(self.google.events[CAL][eid]["summary"], "Là-bas")

    def test_changes_to_different_fields_merge(self):
        eid = self._shared()
        occ = self.local()[0]
        draft = self.service.draft_for(occ)
        draft.title = "Revue client"
        self.service.save_draft(occ, draft)
        settle(self.service)
        self.google.remote_update(CAL, eid, location="Salle 3")
        report = self.sync()
        self.assertEqual(report.conflicts, 0)
        self.assertEqual((self.local()[0].title, self.local()[0].location), ("Revue client", "Salle 3"))
        self.assertEqual((self.google.events[CAL][eid]["summary"], self.google.events[CAL][eid]["location"]),
                         ("Revue client", "Salle 3"))


class RobustnessTest(SyncCase):
    def test_invalid_sync_token_full_resync_keeps_local_changes(self):
        s = paris(2026, 11, 3, 10)
        self.google.remote_insert(CAL, g_event("a", "Garde", s, s + timedelta(hours=1)))
        self.google.remote_insert(CAL, g_event("b", "Disparu", s, s + timedelta(hours=1)))
        self.sync()
        self.google.offline = True
        local_id = self.create_local("Créé hors ligne", paris(2026, 11, 9, 9), paris(2026, 11, 9, 10))
        self.sync()                                      # hors ligne : reste en file
        self.google.offline = False
        # Pendant ce temps : « b » supprimé à distance (purgé, plus listé) et jetons invalidés.
        del self.google.events[CAL]["b"]
        self.google.order[CAL].remove("b")
        self.google.invalidate_tokens()
        report = self.sync()
        self.assertEqual(report.resyncs, 1)
        titles = sorted(o.title for o in self.local())
        self.assertEqual(titles, ["Créé hors ligne", "Garde"])
        self.assertIn(local_id, self.google.live(CAL))

    def test_offline_changes_are_queued_then_sent_once(self):
        self.sync()
        self.google.offline = True
        ids = [self.create_local(f"Hors ligne {i}", paris(2026, 11, 10 + i, 9), paris(2026, 11, 10 + i, 10))
               for i in range(3)]
        result = self.sync()
        self.assertIsInstance(result, TransientError)
        self.assertTrue(self.manager.state["offline"])
        self.assertEqual(self.service.repo.outbox_count(), 3)
        self.assertEqual(len(self.local()), 3)           # rien de perdu
        self.google.offline = False
        self.service.writer.submit(lambda repo: repo.conn.execute("UPDATE sync_outbox SET next_at = 0"))
        settle(self.service)
        self.sync()
        self.assertEqual(sorted(self.google.live(CAL)), sorted(ids))
        self.assertEqual(self.service.repo.outbox_count(), 0)
        self.sync()
        self.assertEqual(len(self.google.live(CAL)), 3)

    def test_rate_limit_and_expired_token_are_retried(self):
        self.google.fail_next = [429, 503, 403]          # quota, indisponible, rateLimitExceeded
        report = self.sync()
        self.assertFalse(isinstance(report, Exception), report)
        self.google.fail_next = [401]
        self.sync()
        self.assertGreaterEqual(self.tokens.refreshes, 1)

    def test_revoked_token_marks_the_account(self):
        class Revoked(FakeTokens):
            def access_token(self, force=False):
                raise AuthError("autorisation révoquée (invalid_grant)")
        self.manager.provider_factory = lambda account: GoogleProvider(Revoked(), self.google, sleep=lambda s: None)
        result = self.sync()
        self.assertIsInstance(result, AuthError)
        self.assertEqual(self.manager.accounts()[0]["status"], "auth_error")
        self.assertIn("à reconnecter", self.manager.status_text())

    def test_read_only_calendar_and_permission_downgrade(self):
        self.google.add_calendar("equipe@group", "Équipe (partagé)", "writer")
        self.sync()
        cal = next(c for c in self.service.calendars() if c.remote_id == "equipe@group")
        self.assertFalse(cal.read_only)
        self.google.calendars["equipe@group"]["accessRole"] = "reader"
        self.sync()
        cal = next(c for c in self.service.calendars() if c.remote_id == "equipe@group")
        self.assertTrue(cal.read_only)
        self.assertNotIn(cal.id, [c.id for c in self.service.writable_calendars()])


class SeriesSyncTest(SyncCase):
    def test_series_exception_and_cancelled_instance(self):
        start = paris(2026, 11, 2, 9, 30)
        self.google.remote_insert(CAL, g_event("hebdo", "Point de prod", start, start + timedelta(hours=1),
                                               recurrence=["RRULE:FREQ=WEEKLY;BYDAY=MO;COUNT=4"]))
        self.sync()
        self.assertEqual([o.start.day for o in self.local()], [2, 9, 16, 23])
        # Google : l'occurrence du 9 est supprimée.
        self.google.remote_insert(CAL, {"id": "hebdo_20261109T083000Z", "recurringEventId": "hebdo",
                                        "status": "cancelled",
                                        "originalStartTime": {"dateTime": "2026-11-09T09:30:00+01:00"}})
        self.sync()
        self.assertEqual([o.start.day for o in self.local()], [2, 16, 23])
        # Ici : l'occurrence du 16 est décalée -> exception envoyée comme instance Google.
        occ = self.local()[1]
        draft = self.service.draft_for(occ)
        draft.start, draft.end = paris(2026, 11, 16, 14), paris(2026, 11, 16, 15)
        self.service.save_draft(occ, draft, "this")
        settle(self.service)
        self.sync()
        instance = self.google.events[CAL].get("hebdo_20261116T083000Z")
        self.assertIsNotNone(instance)
        self.assertTrue(instance["start"]["dateTime"].startswith("2026-11-16T14:00"))
        self.sync()
        self.assertEqual([(o.start.day, o.start.hour) for o in self.local()], [(2, 9), (16, 14), (23, 9)])


class SyncBadgeTest(SyncCase):
    def test_sidebar_shows_the_sync_state(self):
        from fm_agenda.ui.pane import AgendaPane
        pane = AgendaPane(self.service, settings=dict(self.settings))
        pane.resize(1200, 760)
        pane.show()
        self.sync()
        pane._refresh_sync()
        self.assertTrue(pane.sidebar.sync.text.startswith("Synchronisé à"), pane.sidebar.sync.text)
        self.google.offline = True
        self.create_local("Hors ligne", paris(2026, 11, 10, 9), paris(2026, 11, 10, 10))
        self.sync()
        pane._refresh_sync()
        self.assertEqual((pane.sidebar.sync.text, pane.sidebar.sync.level), ("Hors ligne · 1 en attente", "offline"))
        pane.shutdown()
        pane.close()


class OAuthHelpersTest(unittest.TestCase):
    def test_pkce_client_import_credentials_and_email(self):
        credentials.clear_memory()
        verifier, challenge = oauth.pkce_pair()
        self.assertGreaterEqual(len(verifier), 43)
        import hashlib
        expected = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b"=").decode()
        self.assertEqual(challenge, expected)
        path = Path(tempfile.mkdtemp()) / "client_secret.json"
        path.write_text(json.dumps({"installed": {"client_id": "123-abc.apps.googleusercontent.com",
                                                  "client_secret": "s3cret"}}), encoding="utf-8")
        oauth.import_client_json(path)
        self.assertEqual(oauth.load_client().client_id, "123-abc.apps.googleusercontent.com")
        payload = base64.urlsafe_b64encode(json.dumps({"email": "moi@example.com"}).encode()).rstrip(b"=").decode()
        self.assertEqual(oauth._email_from_id_token(f"x.{payload}.y"), "moi@example.com")
        source = oauth.TokenSource("acc", http=None)
        source.store(oauth.Tokens("acces", 0, "actualisation", "moi@example.com"))
        self.assertEqual(credentials.read_json("google/acc")["refresh_token"], "actualisation")
        source.forget(revoke_remote=False)
        self.assertIsNone(credentials.read_json("google/acc"))


if __name__ == "__main__":
    unittest.main()
