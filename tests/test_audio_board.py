"""Cartes audio du Board (`audio_doc`) dans un VRAI Board (BoardPane) : dépôt de fichiers, lien
relatif / absolu, miniature waveform calculée en fond, enregistrement / réouverture, bonne cible
d'ouverture au double-clic, réparation d'une référence, préécoute par le moteur partagé (sur le
PÉRIPHÉRIQUE DE TEST : aucun son produit pendant les tests)."""
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
from PySide6.QtCore import QEvent, QMimeData, QPointF, Qt, QUrl  # noqa: E402
from PySide6.QtWidgets import QApplication, QWidget  # noqa: E402

APP = QApplication.instance() or QApplication([])

from fm_audio import board_model as bm  # noqa: E402
from fm_audio_engine import client, wavio  # noqa: E402
from fm_board import model, serialization  # noqa: E402
from fm_board import ui as board_ui  # noqa: E402

SR = 48000


def settle(seconds=0.05):
    end = time.monotonic() + seconds
    while time.monotonic() < end:
        APP.processEvents()
        time.sleep(0.003)


class BoardModelTest(unittest.TestCase):
    def test_roles_links_and_relink(self):
        self.assertEqual(bm.guess_role("x/Prise_gtr_p01.wav"), ("prise", "audio"))
        self.assertEqual(bm.guess_role("x/kick_808.wav"), ("sample", "audio"))
        self.assertEqual(bm.guess_role("x/morceau.fmmusic"), ("composition", "music"))
        self.assertEqual(bm.guess_role("x/montage.fmaudio"), ("projet", "audio"))
        with tempfile.TemporaryDirectory() as d:
            d = Path(d)
            (d / "sons").mkdir()
            f = d / "sons" / "voix.wav"
            f.write_bytes(b"x")
            v = bm.link_values(f, d / "b.mro")
            self.assertEqual(v["rel"], os.path.join("sons", "voix.wav"))
            item = model.new_item(bm.AUDIO_DOC, **v)
            # dossier de projet déplacé : le lien relatif suit
            shutil.move(str(d / "sons"), str(d / "deplace"))
            (d / "sons").mkdir()
            shutil.move(str(d / "deplace" / "voix.wav"), str(d / "sons" / "voix.wav"))
            self.assertEqual(bm.resolve(item, d / "b.mro"), (d / "sons" / "voix.wav").resolve())
            # fichier vraiment déplacé : introuvable, puis reliaison contrôlée par l'utilisateur
            (d / "ailleurs").mkdir()
            shutil.move(str(d / "sons" / "voix.wav"), str(d / "ailleurs" / "voix.wav"))
            self.assertIsNone(bm.resolve(item, d / "b.mro"))
            self.assertEqual(bm.candidates(item, [d / "ailleurs", d / "rien"]), [d / "ailleurs" / "voix.wav"])
            item.update(bm.relink(item, d / "ailleurs" / "voix.wav", d / "b.mro"))
            self.assertIsNotNone(bm.resolve(item, d / "b.mro"))

    def test_normalize(self):
        raw = {"type": "audio_doc", "id": "a", "w": 10, "role": "inconnu", "revision": "x", "futur": 3}
        item = model.normalize_item(raw)
        self.assertEqual(item["w"], bm.MIN_W)
        self.assertEqual(item["role"], "son")
        self.assertEqual(item["revision"], 0)
        self.assertEqual(item["futur"], 3)        # champ d'une version plus récente gardé


class BoardCardsTest(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="audio_board_"))
        os.environ["FMZ_AUDIO_CACHE"] = str(self.tmp / "cache")
        t = np.arange(SR) / SR
        self.wav = wavio.write(self.tmp / "prise_voix.wav", (0.4 * np.sin(2 * np.pi * 330 * t))[None, :].astype(np.float32), SR)
        self.proj = self.tmp / "morceau.fmmusic"
        self.proj.write_text("{}", "utf-8")
        self.path = serialization.create_board_file(self.tmp / "essai.mro")
        self.host = QWidget()
        self.host.resize(1200, 800)
        self.pane = board_ui.BoardPane(self.host)
        self.assertTrue(self.pane.open(self.path))
        self.pane.resize(1200, 800)
        self.host.show()
        self.pane.show()
        settle()

    def tearDown(self):
        from fm_audio import board_item
        board_item.Preview.stop()
        board_item.HOOKS.clear()
        board_item.wait_idle()
        try:
            self.pane._autosave.stop()
            self.pane.deleteLater()
        except RuntimeError:
            pass
        self.host.deleteLater()
        settle(0.05)
        QApplication.sendPostedEvents(None, QEvent.DeferredDelete)
        client.shutdown_shared()
        os.environ.pop("FMZ_AUDIO_CACHE", None)
        shutil.rmtree(self.tmp, ignore_errors=True)

    def cards(self):
        from fm_audio.board_item import AudioItem
        return [i for i in self.pane.scene.board_items() if isinstance(i, AudioItem)]

    def drop(self, paths):
        mime = QMimeData()
        mime.setUrls([QUrl.fromLocalFile(str(p)) for p in paths])
        return self.pane.view.drop_mime(mime, QPointF(100, 100))

    def test_drop_creates_linked_cards_with_waveform_and_survives_reload(self):
        from fm_audio import board_item
        self.assertTrue(self.drop([self.wav, self.proj]))
        cards = self.cards()
        self.assertEqual(len(cards), 2)
        snd = next(c for c in cards if c.data["path"].endswith(".wav"))
        self.assertEqual(snd.data["role"], "prise")
        self.assertAlmostEqual(snd.data["duration"], 1.0, places=2)
        self.assertEqual(snd.data["rel"], "prise_voix.wav")
        self.assertFalse((self.tmp / "essai_assets" / "prise_voix.wav").exists())    # lié, jamais copié
        self.pane.view.viewport().grab()                       # peinture : demande la miniature en fond
        board_item.wait_idle()
        settle(0.1)
        self.assertIsNotNone(board_item._peaks.get(str(self.wav)))
        self.pane.view.viewport().grab()                       # peinture avec la waveform
        self.assertTrue(self.pane.save())
        again = board_ui.BoardPane(self.host)
        try:
            self.assertTrue(again.open(self.path))
            kinds = sorted(i.data["module"] for i in again.scene.board_items() if i.data.get("type") == "audio_doc")
            self.assertEqual(kinds, ["audio", "music"])
        finally:
            again._autosave.stop()
            again.deleteLater()

    def test_double_click_opens_the_right_module(self):
        from fm_audio import board_item
        opened = []
        board_item.HOOKS["open"] = lambda key, path: opened.append((key, Path(path).name))
        self.drop([self.wav, self.proj])
        for c in self.cards():
            board_item.open_in_module(c, c.data["module"], c.file_path())
        self.assertEqual(sorted(opened), [("audio", "prise_voix.wav"), ("music", "morceau.fmmusic")])

    def test_missing_file_is_shown_not_replaced(self):
        self.drop([self.wav])
        (card,) = self.cards()
        os.replace(self.wav, self.tmp / "deplace.wav")
        card._path_cache = None
        self.assertIsNone(card.file_path())
        self.pane.view.viewport().grab()                       # « Fichier introuvable » peint, rien d'inventé
        self.assertTrue(card.data["path"].endswith("prise_voix.wav"))

    def test_revisions_and_role_change_are_undoable(self):
        from fm_audio import board_item
        self.drop([self.wav])
        (card,) = self.cards()
        wavio.write(self.tmp / "prise_voix__r1.wav", np.zeros((1, 100), np.float32), SR)
        wavio.write(self.tmp / "prise_voix__r3.wav", np.zeros((1, 100), np.float32), SR)
        revs = board_item.revisions(card.data, self.path)
        self.assertEqual([r for r, _ in revs], [0, 1, 3])
        values = board_item.bm.relink(card.data, revs[-1][1], self.path)
        values["revision"] = 3
        card._change(values, "Révision")
        self.assertTrue(card.file_path().name.endswith("__r3.wav"))
        card._change({"role": "mixage"}, "Rôle")
        self.assertEqual(card.data["role"], "mixage")
        self.pane.scene.undo.undo()
        self.pane.scene.undo.undo()
        self.assertEqual(card.data["role"], "prise")
        self.assertEqual(card.data["revision"], 0)

    @unittest.skipUnless(client.available()[0], "moteur audio non compilé")
    def test_preview_uses_the_shared_engine_on_test_device(self):
        from fm_audio import board_item
        from fm_audio_engine import media
        board_item.HOOKS["output"] = "test"
        media.ensure_pcm(str(self.wav))
        self.assertEqual(board_item.Preview.play(str(self.wav)), "lecture")
        eng = client.shared_engine(start=False)
        self.assertIsNotNone(eng)
        self.assertEqual(eng.request("status")["backend"], "test")
        self.assertEqual(board_item.Preview.current(), str(self.wav))
        board_item.Preview.stop()
        self.assertIsNone(board_item.Preview.current())
        self.assertIs(client.shared_engine(start=False), eng)   # un seul moteur


if __name__ == "__main__":
    unittest.main()
