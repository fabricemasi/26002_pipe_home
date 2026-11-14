"""Capture, prises, punch, boucles, métronome, précompte et latence sur le PÉRIPHÉRIQUE DE TEST
DÉCLARÉ du moteur (horloge simulée, entrée synthétique : sinus 440 Hz sur l'entrée 0, impulsions
toutes les 0,5 s sur l'entrée 1). Ces tests ne valident NI un vrai matériel NI ASIO."""
import json
import os
import sys
import tempfile
import time
import unittest
from pathlib import Path

sys.path.insert(0, os.path.dirname(__file__))
import _isolate  # noqa: F401

import numpy as np

from fm_audio_engine import capture, client, wavio

SR = 48000


def wait_pos(c, target, timeout=10.0):
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        if int(c.request("status").get("pos", 0)) >= target:
            return
        time.sleep(0.01)
    raise AssertionError("position non atteinte")


@unittest.skipUnless(client.available()[0], "moteur audio non compilé")
class CaptureTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)
        self.c = client.EngineClient()
        self.c.start()

    def tearDown(self):
        self.c.close()
        self.tmp.cleanup()

    def open_test(self, **test):
        test.setdefault("fast", False)
        return self.c.request("open_device", output="test", buffer=256, test=test, timeout=5)

    def spec(self, **kw):
        s = {"sample_rate": SR, "tracks": [{"id": "gtr", "input": 0, "monitor": False}], "buses": [], "master": {}}
        s.update(kw)
        return s

    def test_take_contains_the_input_aligned_with_position(self):
        self.open_test()
        self.c.request("load", spec=self.spec())
        self.c.request("record_start", dir=str(self.dir), name="essai", tracks=[{"id": "gtr", "inputs": [0]}])
        self.c.request("play", **{"from": 0})
        wait_pos(self.c, SR // 2)
        self.c.request("stop")
        res = self.c.request("record_stop", timeout=10)
        self.assertEqual(res["error"], "")
        self.assertEqual(res["overflow"], 0)
        (take,) = res["takes"]
        self.assertEqual(take["start"], 0)
        data, sr = wavio.read(take["path"])
        self.assertEqual(data.shape[1], take["frames"])
        self.assertGreaterEqual(take["frames"], SR // 2)
        # le contenu est l'entrée réelle du périphérique (sinus 440 Hz), sans trou ni doublon
        self.assertTrue(np.all(np.isfinite(data)))
        seg = data[0, 1000:1000 + SR // 4]
        zc = np.sum((seg[:-1] < 0) & (seg[1:] >= 0)) / (len(seg) / SR)
        self.assertAlmostEqual(zc, 440, delta=4)
        self.assertLess(float(np.max(np.abs(np.diff(data[0])))), 0.06)   # continuité (pas de bloc perdu)
        self.assertTrue(json.loads(Path(take["path"] + ".journal").read_text("utf-8"))["final"])

    def test_punch_and_loop_takes(self):
        self.open_test(fast=True, max_frames=SR * 3)
        self.c.request("load", spec=self.spec())
        self.c.request("loop", on=True, start=0, end=SR // 2)
        self.c.request("record_start", dir=str(self.dir), name="boucle", tracks=[{"id": "gtr", "inputs": [0]}],
                       punch_in=SR // 8, punch_out=SR // 4)
        self.c.request("play", **{"from": 0})
        time.sleep(0.4)
        self.c.request("stop")
        res = self.c.request("record_stop", timeout=10)
        takes = res["takes"]
        self.assertGreaterEqual(len(takes), 2)                     # une prise par passe de boucle
        self.assertEqual(len({t["path"] for t in takes}), len(takes))
        for t in takes[:-1]:
            self.assertEqual(t["start"], SR // 8)                  # punch-in
            self.assertEqual(t["frames"], SR // 8)                 # borné par le punch-out
        self.assertEqual([t["pass"] for t in takes], list(range(len(takes))))

    def test_metronome_clicks_on_beats_and_precount(self):
        out = self.dir / "sortie.wav"
        self.open_test(fast=True, out=str(out), max_frames=SR * 3)
        self.c.request("load", spec=self.spec(tempo={"ppq": 960, "points": [{"tick": 0, "bpm": 120}]}))
        self.c.request("metronome", on=False, level=0.5)
        # précompte d'une mesure (4 temps = 96 000 échantillons) : clics même sans métronome
        self.c.request("play", **{"from": -SR * 2, "precount_until": 0})
        time.sleep(0.5)
        self.c.request("close_device", timeout=5)
        data, _ = wavio.read(out)
        env = np.abs(data[0])
        onsets = [i for i in range(1, env.size) if env[i] > 0.05 and env[i - 1] <= 0.05 and np.max(env[max(0, i - 2000):i]) <= 0.05]
        self.assertGreaterEqual(len(onsets), 4)
        gaps = np.diff(onsets[:4])
        np.testing.assert_allclose(gaps, [SR // 2] * 3, atol=2)    # un clic par noire à 120 BPM
        # après le précompte, plus de clic (métronome éteint)
        self.assertTrue(all(o < onsets[0] + SR * 2 for o in onsets))

    def test_guitar_di_kept_raw_while_monitoring_is_processed_then_reamped(self):
        out = self.dir / "ecoute.wav"
        self.open_test(fast=True, out=str(out), max_frames=SR)
        chain = [{"type": "overdrive", "params": {"drive": 0.8}}, {"type": "amp", "params": {"channel": 2, "gain": 0.8}}, {"type": "cabinet"}]
        self.c.request("load", spec=self.spec(tracks=[{"id": "gtr", "input": 0, "monitor": True, "fx": chain}]))
        self.c.request("record_start", dir=str(self.dir), name="di", tracks=[{"id": "gtr", "inputs": [0]}])
        self.c.request("play", **{"from": 0})
        time.sleep(0.4)
        self.c.request("stop")
        (take,) = self.c.request("record_stop", timeout=10)["takes"]
        self.c.request("close_device", timeout=5)
        di, _ = wavio.read(take["path"])
        mon, _ = wavio.read(out)
        # la prise est le signal DI BRUT (sinus 440 Hz pur, sans harmoniques) ...
        spec = np.abs(np.fft.rfft(di[0, :16384] * np.hanning(16384)))
        f = np.fft.rfftfreq(16384, 1 / SR)
        h1, h3 = spec[np.argmin(abs(f - 440))], spec[np.argmin(abs(f - 1320))]
        self.assertLess(h3 / h1, 1e-3)
        # ... alors que l'écoute est traitée (distorsion : harmoniques fortes)
        spec = np.abs(np.fft.rfft(mon[0, 4096:4096 + 16384] * np.hanning(16384)))
        self.assertGreater(spec[np.argmin(abs(f - 1320))] / spec[np.argmin(abs(f - 440))], 0.05)
        # reamping logiciel : la DI repasse dans la même chaîne, hors temps réel, sans toucher la prise
        res = client.render_offline(self.spec(tracks=[{"id": "re", "fx": chain, "clips": [{"media": take["path"], "start": 0, "length": take["frames"]}]}]),
                                    self.dir / "reamp.wav", end=take["frames"], tail=0)
        re, _ = wavio.read(res["path"])
        spec = np.abs(np.fft.rfft(re[0, 4096:4096 + 16384] * np.hanning(16384)))
        self.assertGreater(spec[np.argmin(abs(f - 1320))] / spec[np.argmin(abs(f - 440))], 0.05)
        self.assertEqual(wavio.read(take["path"])[0].shape, di.shape)

    def test_live_tuner_on_input(self):
        from fm_audio_engine import analysis
        self.open_test(fast=False)
        self.c.request("load", spec=self.spec())
        self.c.request("tuner", input=0)                     # entrée 0 du périphérique de test : sinus 440 Hz
        self.c.request("play", **{"from": 0})
        time.sleep(0.3)
        hz = self.c.request("status")["tuner_hz"]
        t = analysis.tuner(hz)
        self.assertEqual((t["note"], t["octave"]), ("la", 4))
        self.assertLess(abs(t["cents"]), 2)
        self.c.request("tuner", input=-1)
        self.assertNotIn("tuner_hz", self.c.request("status"))

    def test_round_trip_latency_measured_on_loopback(self):
        self.open_test(fast=False, loopback_delay=300, in_channels=1)
        self.c.request("load", spec=self.spec())
        lag = capture.measure_latency(self.c, 0)
        self.assertEqual(lag, 300)


class RecoveryTest(unittest.TestCase):
    def test_unfinalized_take_is_recovered_without_overwrite(self):
        with tempfile.TemporaryDirectory() as d:
            d = Path(d)
            base = d / "prise_gtr_p00.wav"
            part = Path(str(base) + ".part")
            wavio.write(part, np.full((1, 1000), 0.25, np.float32), SR, overwrite=True)
            raw = bytearray(part.read_bytes())
            raw[76:80] = b"\0\0\0\0"                              # en-tête jamais finalisé (panne)
            part.write_bytes(bytes(raw) + b"\x00\x00")            # écriture partielle d'un échantillon
            journal = Path(str(base) + ".journal")
            journal.write_text(json.dumps({"track": "gtr", "path": str(base), "part": str(part), "start": 4800,
                                           "frames_checkpoint": 900, "sample_rate": SR, "channels": 1, "final": False}), "utf-8")
            base.write_bytes(b"autre fichier")                    # un fichier du même nom existe : jamais écrasé
            self.assertEqual(capture.pending_takes(d), [journal])
            r = capture.recover(journal)
            self.assertEqual(r["frames"], 1000)
            self.assertFalse(r["lost_after_checkpoint"])
            self.assertEqual(base.read_bytes(), b"autre fichier")
            data, _ = wavio.read(r["path"])
            self.assertTrue(np.allclose(data, 0.25))
            self.assertEqual(capture.pending_takes(d), [])
            with self.assertRaises(FileNotFoundError):
                capture.recover(d / "absente.wav.journal")


if __name__ == "__main__":
    unittest.main()
