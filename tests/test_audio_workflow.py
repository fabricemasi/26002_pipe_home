"""Parcours transmodules complet (sur fixtures, périphérique de test, aucun son produit) :
Board (carte d'un son) -> double-clic -> FM Audio (traitement, publication v1) -> FM Music (insertion
depuis la bibliothèque, batterie) -> export audio vérifié + stems -> carte de l'export sur le Board ->
FM Audio publie v2 -> FM Music propose / adopte (annulable) -> Board enregistré et rouvert."""
import os as _os, sys as _sys
_sys.path.insert(0, _os.path.dirname(_os.path.abspath(__file__)))
import _isolate  # noqa: E402,F401
import os
import shutil
import tempfile
import time
import unittest
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import numpy as np  # noqa: E402
from PySide6.QtCore import QEvent, QMimeData, QPointF, QUrl  # noqa: E402
from PySide6.QtWidgets import QApplication, QWidget  # noqa: E402

APP = QApplication.instance() or QApplication([])

from fm_audio_engine import client, dsp_offline, library, wavio  # noqa: E402

SR = 48000


def settle(s=0.05):
    end = time.monotonic() + s
    while time.monotonic() < end:
        APP.processEvents()
        time.sleep(0.003)


@unittest.skipUnless(client.available()[0], "moteur audio non compilé")
class TransModuleWorkflowTest(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="audio_flow_"))
        os.environ["FMZ_AUDIO_CACHE"] = str(self.tmp / "cache")
        rng = np.random.default_rng(9)
        t = np.arange(SR * 2) / SR
        x = (0.4 * np.sin(2 * np.pi * 196 * t) + rng.standard_normal(t.size) * 0.03).astype(np.float32)
        x[:SR // 2] = (rng.standard_normal(SR // 2) * 0.03).astype(np.float32)
        self.take = wavio.write(self.tmp / "prise_gtr.wav", x[None, :], SR)
        self.settings = {"audio_library_root": str(self.tmp / "biblio"), "audio_export_format": "pcm24"}

    def tearDown(self):
        client.shutdown_shared()
        os.environ.pop("FMZ_AUDIO_CACHE", None)
        settle(0.05)
        QApplication.sendPostedEvents(None, QEvent.DeferredDelete)
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_board_audio_music_board(self):
        from fm_audio import board_item
        from fm_audio.pane import AudioPane
        from fm_board import serialization
        from fm_board import ui as board_ui
        from fm_music.pane import MusicPane
        hooks = {"settings": lambda: self.settings}
        # 1. Board : la prise devient une carte ; double-clic -> FM Audio
        host = QWidget()
        board = board_ui.BoardPane(host)
        path = serialization.create_board_file(self.tmp / "projet.mro")
        self.assertTrue(board.open(path))
        mime = QMimeData()
        mime.setUrls([QUrl.fromLocalFile(str(self.take))])
        self.assertTrue(board.view.drop_mime(mime, QPointF(0, 0)))
        (card,) = [i for i in board.scene.board_items() if isinstance(i, board_item.AudioItem)]
        audio = AudioPane(None, hooks=hooks)
        board_item.HOOKS["open"] = lambda key, p: (self.assertEqual(key, "audio"), audio.open_path(p))
        board_item.open_in_module(card, card.data["module"], card.file_path())
        self.assertEqual(audio.project.tracks[0].clips[0].path, str(self.take))
        # 2. FM Audio : réduction de bruit (nouvelle révision du fichier), publication v1
        x, _ = wavio.read(self.take)
        clean, residual = dsp_offline.noise_reduce(x, x[:, :SR // 2])
        v1 = wavio.write(self.tmp / "prise_gtr__r1.wav", clean, SR)
        t = audio.project.tracks[0]
        with audio.project.edit("traitement", t.id):
            t.clips[0].path, t.clips[0].revision = str(v1), 1
        audio.view.sel_clips = {(t.id, t.clips[0].id)}
        audio.publish_selected()
        rid = audio.project.tracks[0].clips[0].resource
        self.assertTrue(rid)
        # 3. FM Music : insertion depuis la bibliothèque + batterie par défaut, export vérifié et stems
        music = MusicPane(None, hooks=hooks)
        lib = music.library()
        gtr = music.project.add_track(name="Guitare")
        clip = library.insert(music.project, lib, rid, gtr.id, start=0)
        mix = self.tmp / "morceau_mix.wav"
        job = music.session.export(str(mix), fmt="pcm24")
        res = music.session.engine.wait_job(job, timeout=60)
        self.assertEqual(res["frames"], music.project.length_samples() + res["tail"])
        data, sr = wavio.read(mix)
        self.assertEqual(sr, SR)
        self.assertGreater(float(np.max(np.abs(data))), 0.05)
        stems = self.tmp / "stems"
        stems.mkdir()
        job = music.session.export(str(self.tmp / "unused.wav"), stems_dir=str(stems), fmt="f32")
        res = music.session.engine.wait_job(job, timeout=60)
        self.assertEqual(len(res["stems"]), len(music.project.tracks))
        # 4. l'export revient sur le Board comme carte « mixage » liée
        mime = QMimeData()
        mime.setUrls([QUrl.fromLocalFile(str(mix))])
        board.view.drop_mime(mime, QPointF(400, 0))
        roles = sorted(i.data["role"] for i in board.scene.board_items() if isinstance(i, board_item.AudioItem))
        self.assertEqual(roles, ["mixage", "prise"])
        # 5. FM Audio publie v2 (plus courte) ; FM Music la propose, l'adopte, puis l'annule
        v2 = wavio.write(self.tmp / "prise_gtr__r2.wav", dsp_offline.time_stretch(clean, 0.8), SR)
        lib2 = audio.library()
        lib2.publish(v2, resource=rid, recipe={"op": "time_stretch", "factor": 0.8}, source=(rid, 1))
        lib.rebuild()
        (u,) = library.pending_updates(music.project, lib)
        library.adopt(music.project, lib, u["track"], u["clip"])
        self.assertEqual(music.project.track(gtr.id).clips[0].revision, 2)
        music.project.history.undo()
        self.assertEqual(music.project.track(gtr.id).clips[0].revision, 1)
        self.assertEqual(clip.resource, rid)
        # 6. projets et Board enregistrés puis rouverts sans perte
        mp = music.project.save(self.tmp / "morceau.fmmusic")
        ap = audio.project.save(self.tmp / "montage.fmaudio")
        self.assertTrue(board.save())
        mime = QMimeData()
        mime.setUrls([QUrl.fromLocalFile(str(mp)), QUrl.fromLocalFile(str(ap))])
        board.view.drop_mime(mime, QPointF(0, 400))
        self.assertTrue(board.save())
        again = board_ui.BoardPane(host)
        self.assertTrue(again.open(path))
        mods = sorted(i.data["module"] for i in again.scene.board_items() if i.data.get("type") == "audio_doc")
        self.assertEqual(mods, ["audio", "audio", "audio", "music"])
        m2 = MusicPane(None, hooks=hooks)
        self.assertTrue(m2.open_path(mp))
        self.assertEqual(m2.project.to_dict()["tracks"], music.project.to_dict()["tracks"])
        for pane in (audio, music, m2):
            pane.shutdown()
            pane.deleteLater()
        for b in (board, again):
            b._autosave.stop()
            b.deleteLater()
        board_item.HOOKS.clear()
        board_item.wait_idle()
        host.deleteLater()


if __name__ == "__main__":
    unittest.main()
