"""Module Photoshop : enregistrement du conteneur EN ARRIÈRE-PLAN (`flush.py`, `container.Prepared`, `Session.flush_async`).
Sur une grande page (2480 x 3508 = 35 Mo par calque), l'enregistrement automatique du Board (800 ms après chaque trait)
encodait le PNG du calque modifié sur le fil de l'interface : 0,1 s sur page blanche, 0,6 s sur page peinte, et le cercle de
brosse se figeait à chaque pause. L'encodage, l'empreinte et l'écriture se font maintenant dans un fil ; l'enregistrement du
Board trouve le conteneur prêt."""
import os as _os, sys as _sys  # jamais les vrais réglages / presets de l'utilisateur (tests/_isolate.py)
_sys.path.insert(0, _os.path.dirname(_os.path.abspath(__file__)))
import _isolate  # noqa: E402,F401
import os
import sys
import threading
import time
import unittest
from unittest import mock

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from PySide6.QtCore import QPoint, Qt  # noqa: E402
from PySide6.QtTest import QTest  # noqa: E402

from _photoshop_case import PsCase, settle  # noqa: E402
from fm_board import ui as board_ui  # noqa: E402
from fm_photoshop import container, model as M, session as S  # noqa: E402


def painted_document(w=96, h=64, seed=1):
    rng = np.random.default_rng(seed)
    doc = M.new_document(w, h, background=(255, 255, 255, 255))
    doc.layers[0].pix.write(doc.rect(), rng.integers(0, 255, (h, w, 4), dtype=np.uint8))
    return doc


def edit(session, seed=2):
    """Une modification comptée par l'historique (comme un trait validé)."""
    layer = session.layer()
    rng = np.random.default_rng(seed)
    layer.pix.write((4, 4, 20, 20), rng.integers(0, 255, (16, 16, 4), dtype=np.uint8))
    session.history.version += 1


class Store:
    """`store(octets, suffixe) -> nom` factice : garde les appels, peut être ralenti ou échouer."""

    def __init__(self, delay=0.0, fail=False):
        self.calls, self.delay, self.fail = [], delay, fail

    def __call__(self, payload, suffix):
        if self.delay:
            time.sleep(self.delay)
        if self.fail:
            raise OSError("disque plein")
        self.calls.append((payload, suffix, threading.current_thread().name))
        return f"{len(self.calls):016x}{suffix}"


class PreparedTest(unittest.TestCase):
    def test_prepared_archive_equals_the_direct_one(self):
        doc = painted_document()
        direct, prepared = container.loads(container.dumps(doc)), container.loads(container.prepare(doc, snapshot=True).build())
        self.assertEqual((direct.width, direct.height, len(direct.layers)), (prepared.width, prepared.height, len(prepared.layers)))
        np.testing.assert_array_equal(direct.layers[0].pix.read(direct.rect()), prepared.layers[0].pix.read(prepared.rect()))

    def test_snapshot_ignores_what_is_painted_after_the_preparation(self):
        doc = painted_document()
        before = doc.layers[0].pix.read(doc.rect()).copy()
        prepared = container.prepare(doc, snapshot=True)
        doc.layers[0].pix.write((0, 0, 32, 32), np.zeros((32, 32, 4), np.uint8))       # le trait suivant commence déjà
        saved = container.loads(prepared.build())
        np.testing.assert_array_equal(saved.layers[0].pix.read(saved.rect()), before)  # l'archive est celle de l'instant figé
        now = container.loads(container.dumps(doc))
        self.assertFalse(np.array_equal(now.layers[0].pix.read(now.rect()), before))

    def test_unchanged_planes_are_not_encoded_again(self):
        doc = painted_document()
        container.dumps(doc)
        calls = []
        real = container._png_encode
        with mock.patch.object(container, "_png_encode", lambda *a: calls.append(1) or real(*a)):
            container.dumps(doc)
            self.assertEqual(calls, [])                                          # PNG gardé : rien à encoder
            doc.layers[0].pix.write((0, 0, 8, 8), np.zeros((8, 8, 4), np.uint8))
            container.dumps(doc)
            self.assertEqual(len(calls), 1)

    def test_a_thread_never_replaces_a_newer_cached_png(self):
        doc = painted_document()
        plane = doc.layers[0].pix
        plane.png = (7, b"recent")
        container._remember(plane, 5, b"ancien")                                  # un fil en retard rend un vieux cliché
        self.assertEqual(plane.png, (7, b"recent"))
        container._remember(plane, 9, b"neuf")
        self.assertEqual(plane.png, (9, b"neuf"))

    def test_the_encoded_plane_is_kept_for_the_next_direct_save(self):
        doc = painted_document()
        prepared = container.prepare(doc, snapshot=True)
        prepared.encode()
        plane = doc.layers[0].pix
        self.assertEqual(plane.png[0], plane.rev)                                 # `_png_bytes` le réutilisera tel quel


class SessionFlushTest(unittest.TestCase):
    def _session(self):
        session = S.Session(painted_document(), key=("test", 1))
        session.asset, session.flushed_version = None, -1
        return session

    def test_flush_async_writes_the_container_in_a_thread(self):
        session, store = self._session(), Store()
        self.assertTrue(session.flush_async(store))
        self.assertTrue(session.flush_running() or session._flush_job is not None)
        session._flush_job.join(10)
        self.assertFalse(session.collect_flush())
        self.assertEqual(len(store.calls), 1)
        self.assertEqual(store.calls[0][2], "fm_photoshop_flush")                  # PAS le fil de l'interface
        self.assertEqual((session.asset, session.flushed_version), ("0000000000000001.fmps", session.history.version))
        self.assertFalse(session.flush_async(store))                              # à jour : rien à refaire
        self.assertEqual(session.flush(store), session.asset)
        self.assertEqual(len(store.calls), 1)                                     # et l'enregistrement synchrone non plus

    def test_a_synchronous_flush_waits_for_the_running_job(self):
        session, store = self._session(), Store(delay=0.3)
        session.flush_async(store)
        name = session.flush(store)                                               # clic « Enregistrer » pendant le travail
        self.assertEqual(len(store.calls), 1)                                     # le MÊME travail est attendu, pas refait
        self.assertEqual(name, session.asset)

    def test_a_change_during_the_job_is_picked_up_by_the_next_flush(self):
        session, store = self._session(), Store(delay=0.2)
        session.flush_async(store)
        first_version = session.history.version
        edit(session)                                                             # le trait suivant est validé pendant le travail
        session._flush_job.join(10)
        session.collect_flush()
        self.assertEqual(session.flushed_version, first_version)                  # le conteneur adopté est celui de l'instant figé
        self.assertNotEqual(session.flushed_version, session.history.version)
        session.flush(store)                                                      # l'enregistrement suivant refait le travail
        self.assertEqual(len(store.calls), 2)
        saved = container.loads(store.calls[1][0])
        np.testing.assert_array_equal(saved.layers[0].pix.read(saved.rect()), session.doc.layers[0].pix.read(session.doc.rect()))
        old = container.loads(store.calls[0][0])
        self.assertFalse(np.array_equal(old.layers[0].pix.read(old.rect()), saved.layers[0].pix.read(saved.rect())))

    def test_a_failing_thread_is_never_fatal(self):
        session = self._session()
        session.flush_async(Store(fail=True))
        session._flush_job.join(10)
        self.assertFalse(session.collect_flush())
        self.assertIsNone(session.asset)                                          # rien d'adopté
        good = Store()
        self.assertEqual(session.flush(good), "0000000000000001.fmps")            # l'enregistrement synchrone refait le travail
        self.assertEqual(len(good.calls), 1)

    def test_closing_cancels_the_job_before_it_writes(self):
        session, store = self._session(), Store()
        real = container._png_encode

        def slow(*args):
            time.sleep(0.3)
            return real(*args)
        with mock.patch.object(container, "_png_encode", slow):
            session.flush_async(store)
            started = time.monotonic()
            session.cancel_flush()                                                # document fermé : le dossier peut disparaître
            self.assertLess(time.monotonic() - started, 5.0)
        self.assertEqual(store.calls, [])                                         # rien n'est écrit après l'annulation
        self.assertFalse(session.flush_running())

    def test_an_older_job_never_replaces_a_newer_container(self):
        session, store = self._session(), Store()
        session.flush_async(store)
        session._flush_job.join(10)
        session.flushed_version = session.history.version + 5                     # un enregistrement synchrone plus récent a eu lieu
        session.asset = "recent.fmps"
        session.collect_flush()
        self.assertEqual(session.asset, "recent.fmps")


class BoardAutosaveTest(PsCase):
    def _stroke(self, canvas, y):
        p0 = self.at(canvas, 10, y)
        self.drag(canvas, [p0, QPoint(p0.x() + 40, p0.y() + 3), QPoint(p0.x() + 80, p0.y())])

    def test_the_autosave_encodes_nothing_on_the_interface_thread(self):
        item, std = self.editor(300, 200, zoom=1.0, background="Blanc")
        canvas, s = std.canvas, std.session
        s.tool = "brush"
        settle(1.3)                                                               # l'enregistrement initial du document neuf
        self.pane.save()
        threads, real = [], container._png_encode
        with mock.patch.object(container, "_png_encode", lambda *a: threads.append(threading.current_thread().name) or real(*a)):
            self._stroke(canvas, 60)
            settle(1.8)                                                           # pause (250 ms) + fil + enregistrement automatique (800 ms)
        self.assertTrue(threads, "le calque modifié doit être encodé")
        self.assertNotIn(threading.main_thread().name, threads)                  # jamais sur le fil de l'interface
        self.assertEqual(set(threads), {"fm_photoshop_flush"})
        self.assertFalse(self.pane.is_dirty())                                    # le Board a bien été enregistré
        from fm_board import serialization
        self.assertTrue(serialization.asset_path(self.pane.path, s.asset).exists())
        self.assertEqual(s.flushed_version, s.history.version)

    def test_the_board_autosave_waits_for_a_running_flush(self):
        item, std = self.editor(120, 80, zoom=1.0, background="Blanc")
        canvas, s = std.canvas, std.session
        settle(0.2)
        self.assertFalse(item.save_pending())
        edit(s)
        s.notify("committed", None)
        self.assertTrue(item.save_pending())                                      # pause en cours : le conteneur va se préparer
        with mock.patch.object(self.pane, "save") as save:
            self.pane._autosave_due()
            save.assert_not_called()                                              # l'enregistrement automatique est reporté
            self.assertTrue(self.pane._autosave.isActive())
            self.assertEqual(self.pane._autosave.interval(), board_ui.AUTOSAVE_RETRY_MS)
            self.pane._autosave.stop()
            settle(0.8)                                                           # pause écoulée, fil terminé
            self.assertFalse(item.save_pending())
            self.pane._autosave_due()
            save.assert_called_once()

    def test_the_wait_is_bounded(self):
        item, std = self.editor(120, 80, zoom=1.0, background="Blanc")
        with mock.patch.object(type(item), "save_pending", lambda self: True), mock.patch.object(board_ui, "AUTOSAVE_MAX_WAITS", 3), \
                mock.patch.object(self.pane, "save") as save:
            for _ in range(3):
                self.pane._autosave_due()
            save.assert_not_called()
            self.pane._autosave_due()                                             # jamais d'attente sans fin
            save.assert_called_once()

    def test_a_change_restarts_the_autosave_with_its_normal_delay(self):
        item, std = self.editor(120, 80, zoom=1.0, background="Blanc")
        self.pane._autosave.start(board_ui.AUTOSAVE_RETRY_MS)                     # un report vient d'avoir lieu
        self.pane._on_changed()
        self.assertEqual(self.pane._autosave.interval(), board_ui.AUTOSAVE_MS)

    def test_an_explicit_save_reuses_the_container_prepared_in_the_background(self):
        item, std = self.editor(200, 120, zoom=1.0, background="Blanc")
        s = std.session
        settle(1.3)
        self.pane.save()
        edit(s)
        s.notify("committed", None)
        settle(0.8)                                                               # le fil a fini son travail
        self.assertEqual(s.flushed_version, s.history.version)
        real = container._png_encode
        threads = []
        with mock.patch.object(container, "_png_encode", lambda *a: threads.append(1) or real(*a)):
            self.pane.save()                                                      # Ctrl+S : rien à encoder
        self.assertEqual(threads, [])
        self.assertFalse(self.pane.is_dirty())

    def test_removing_the_item_cancels_the_flush(self):
        item, std = self.editor(120, 80, zoom=1.0, background="Blanc")
        s = std.session
        edit(s)
        s.notify("committed", None)
        item._flush_now()                                                         # lance le fil tout de suite
        item._detach()
        self.assertFalse(s.flush_running())
        self.assertIsNone(item._session)


if __name__ == "__main__":
    unittest.main()
