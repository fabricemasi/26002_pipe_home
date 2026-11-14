"""Moteur audio natif : rendu offline réel (même graphe qu'en temps réel), IPC v1.

Fixtures synthétiques (sinus, impulsions, silence) ; chaque test vérifie un résultat audio
mesuré dans le fichier réellement écrit par le moteur.
"""
import os
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, os.path.dirname(__file__))
import _isolate  # noqa: F401  (OBLIGATOIRE avant tout import de l'appli)

import numpy as np

from fm_audio_engine import client, wavio

SR = 48000


def _sine(freq=440.0, secs=1.0, amp=0.5):
    t = np.arange(int(SR * secs)) / SR
    return (amp * np.sin(2 * np.pi * freq * t)).astype(np.float32)


@unittest.skipUnless(client.available()[0], "moteur audio non compilé")
class OfflineRenderTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def media(self, name, data):
        return str(wavio.write(self.dir / name, np.atleast_2d(data), SR))

    def spec(self, tracks, buses=(), master=None, **kw):
        s = {"sample_rate": SR, "tracks": list(tracks), "buses": list(buses), "master": master or {}}
        s.update(kw)
        return s

    def render(self, spec, name="out.wav", **kw):
        kw.setdefault("tail", 0)
        res = client.render_offline(spec, self.dir / name, **kw)
        data, sr = wavio.read(res["path"])
        self.assertEqual(sr, SR)
        return data, res

    def test_clip_exact_samples_and_position(self):
        s = _sine()
        m = self.media("sine.wav", s)
        data, res = self.render(self.spec([{"id": "t1", "clips": [{"media": m, "start": 1000, "offset": 2000, "length": 24000}]}]),
                                end=48000)
        self.assertEqual(res["frames"], 48000)
        self.assertEqual(data.shape, (2, 48000))
        self.assertTrue(np.all(data[:, :1000] == 0))
        np.testing.assert_allclose(data[0, 1000:25000], s[2000:26000], atol=1e-6)
        np.testing.assert_allclose(data[1, 1000:25000], s[2000:26000], atol=1e-6)
        self.assertTrue(np.all(data[:, 25000:] == 0))

    def test_fades_gain_polarity(self):
        dc = np.full(SR, 0.5, np.float32)
        m = self.media("dc.wav", dc)
        clip = {"media": m, "start": 0, "length": 10000, "fade_in": 1000, "fade_out": 2000, "gain_db": -6.0206}
        data, _ = self.render(self.spec([{"id": "t", "polarity": True, "clips": [clip]}]), end=10000)
        g = -0.5 * 0.5
        self.assertAlmostEqual(float(data[0, 0]), 0.0, places=6)
        self.assertAlmostEqual(float(data[0, 500]), g * 0.5, places=4)
        self.assertAlmostEqual(float(data[0, 5000]), g, places=4)
        self.assertAlmostEqual(float(data[0, 9000]), g * 0.5, places=4)

    def test_mute_solo_and_pan(self):
        m = self.media("dc.wav", np.full(SR, 0.25, np.float32))
        t1 = {"id": "a", "pan": -1.0, "clips": [{"media": m, "start": 0, "length": 1000}]}
        t2 = {"id": "b", "mute": True, "clips": [{"media": m, "start": 0, "length": 1000}]}
        data, _ = self.render(self.spec([t1, t2]), end=1000)
        self.assertAlmostEqual(float(data[0, 500]), 0.25, places=5)   # b coupée
        self.assertAlmostEqual(float(data[1, 500]), 0.0, places=5)    # a tout à gauche
        t2 = {"id": "b", "solo": True, "clips": [{"media": m, "start": 0, "length": 1000}]}
        data, _ = self.render(self.spec([t1, t2], ), name="solo.wav", end=1000)
        self.assertAlmostEqual(float(data[0, 500]), 0.25, places=5)   # seule b sonne (solo)
        self.assertAlmostEqual(float(data[1, 500]), 0.25, places=5)

    def test_bus_send_and_latency_compensation(self):
        imp = np.zeros(SR, np.float32)
        imp[0] = 0.5
        m = self.media("imp.wav", imp)
        direct = {"id": "d", "clips": [{"media": m, "start": 1000, "length": 2000}]}
        via_bus = {"id": "v", "output": "lim", "clips": [{"media": m, "start": 1000, "length": 2000}]}
        bus = {"id": "lim", "fx": [{"type": "limiter", "params": {"ceiling_db": 0, "lookahead_ms": 5}}]}
        data, res = self.render(self.spec([direct, via_bus], [bus]), end=4000)
        self.assertEqual(res["latency"], 240)
        # les deux chemins arrivent alignés, à la position d'origine (latence retirée)
        self.assertEqual(int(np.argmax(np.abs(data[0]))), 1000)
        self.assertAlmostEqual(float(data[0, 1000]), 1.0, places=3)
        # send post-fader vers un bus de retour
        send = {"id": "s", "sends": [{"target": "ret", "gain_db": -6.0206}], "clips": [{"media": m, "start": 0, "length": 100}]}
        data, _ = self.render(self.spec([send], [{"id": "ret"}]), name="send.wav", end=100)
        self.assertAlmostEqual(float(data[0, 0]), 0.5 + 0.25, places=4)

    def test_cycle_refused(self):
        spec = self.spec([], [{"id": "b1", "output": "b2"}, {"id": "b2", "output": "b1"}])
        with self.assertRaises(client.EngineError) as cm:
            client.render_offline(spec, self.dir / "x.wav", end=100, tail=0)
        self.assertIn("cyclique", str(cm.exception))
        self.assertFalse((self.dir / "x.wav").exists())

    def test_no_silent_overwrite(self):
        m = self.media("dc.wav", np.full(100, 0.1, np.float32))
        spec = self.spec([{"id": "t", "clips": [{"media": m, "start": 0, "length": 100}]}])
        self.render(spec, end=100)
        with self.assertRaises(client.EngineError):
            client.render_offline(spec, self.dir / "out.wav", end=100, tail=0)
        client.render_offline(spec, self.dir / "out.wav", end=50, tail=0, overwrite=True)
        self.assertEqual(wavio.probe(self.dir / "out.wav").frames, 50)

    def test_missing_media_is_reported_not_replaced(self):
        spec = self.spec([{"id": "t", "clips": [{"media": str(self.dir / "absent.wav"), "start": 0, "length": 100}]}])
        data, res = self.render(spec, end=100)
        self.assertTrue(any("média absent" in w for w in res["warnings"]))
        self.assertTrue(np.all(data == 0))

    def test_synth_note_pitch_and_tempo(self):
        # 120 BPM, ppq 960 : une noire = 24000 échantillons ; la note commence au temps 2
        spec = self.spec([{"id": "syn", "instrument": {"type": "synth", "params": {"osc1_wave": 2, "osc2_wave": 2, "cutoff": 18000, "filter_env": 0, "sustain": 1.0, "attack": 0.001}},
                           "midi_clips": [{"start_tick": 0, "notes": [{"tick": 960, "length": 960, "pitch": 69, "vel": 127}]}]}],
                         tempo={"ppq": 960, "points": [{"tick": 0, "bpm": 120}]})
        data, _ = self.render(spec, end=72000)
        sig = data[0]
        self.assertLess(float(np.max(np.abs(sig[:23990]))), 1e-6)
        self.assertGreater(float(np.max(np.abs(sig[24000:48000]))), 0.01)
        seg = sig[30000:46000]
        zc = np.sum((seg[:-1] < 0) & (seg[1:] >= 0))
        self.assertAlmostEqual(zc / (len(seg) / SR), 440.0, delta=4.0)

    def test_drums_and_stems(self):
        spec = self.spec([
            {"id": "dr", "name": "Batterie", "instrument": {"type": "drums"}, "midi_clips": [{"notes": [{"tick": 0, "length": 120, "pitch": 36, "vel": 120}]}]},
            {"id": "sy", "name": "Synthé", "instrument": {"type": "synth"}, "midi_clips": [{"notes": [{"tick": 0, "length": 480, "pitch": 60, "vel": 100}]}]},
        ], tempo={"ppq": 960, "points": [{"tick": 0, "bpm": 120}]})
        stems = self.dir / "stems"
        stems.mkdir()
        res = client.render_offline(spec, self.dir / "unused.wav", end=24000, tail=0, stems=str(stems))
        self.assertEqual(res["policy"], "bus")
        names = sorted(p.name for p in stems.glob("*.wav"))
        self.assertEqual(names, ["Batterie.wav", "Synthé.wav"])
        for p in stems.glob("*.wav"):
            d, _ = wavio.read(p)
            self.assertGreater(float(np.max(np.abs(d))), 0.01, p.name)

    def test_effects_are_stable(self):
        rng = np.random.default_rng(1)
        noise = (rng.standard_normal(SR) * 0.3).astype(np.float32)
        m = self.media("noise.wav", noise)
        fx = [{"type": t} for t in ("eq", "filter", "compressor", "gate", "deesser", "delay", "reverb", "chorus",
                                     "distortion", "overdrive", "amp", "cabinet", "limiter")]
        fx[0]["params"] = {"b0_on": 1, "b0_freq": 200, "b0_gain_db": 6, "b0_q": 1}
        data, res = self.render(self.spec([{"id": "t", "fx": fx, "clips": [{"media": m, "start": 0, "length": SR}]}]), end=SR)
        self.assertFalse(res["nan"])
        self.assertTrue(np.all(np.isfinite(data)))
        self.assertLessEqual(float(np.max(np.abs(data))), 10 ** (-1 / 20) + 1e-4)  # plafond du limiteur

    def test_truncated_take_is_readable(self):
        # prise interrompue : en-tête de données à 0, échantillons présents
        p = wavio.write(self.dir / "take.wav", np.ones((1, 100), np.float32) * 0.5, SR)
        raw = bytearray(p.read_bytes())
        raw[76:80] = b"\0\0\0\0"
        p.write_bytes(bytes(raw))
        d, _ = wavio.read(p)
        self.assertEqual(d.shape[1], 100)


@unittest.skipUnless(client.available()[0], "moteur audio non compilé")
class EngineIpcTest(unittest.TestCase):
    def test_hello_load_render_cancel_and_clean_exit(self):
        c = client.EngineClient()
        info = c.start()
        try:
            self.assertEqual(info["protocol"], 1)
            with self.assertRaises(client.EngineError):
                c.request("load", spec={"tracks": [], "buses": [{"id": "x", "output": "y"}, {"id": "y", "output": "x"}], "master": {}})
            c.request("load", spec={"sample_rate": SR, "tracks": [{"id": "s", "instrument": {"type": "synth"}}], "buses": [], "master": {}})
            with tempfile.TemporaryDirectory() as d:
                spec = {"sample_rate": SR, "tracks": [{"id": "s", "instrument": {"type": "synth"},
                                                       "midi_clips": [{"notes": [{"tick": 0, "length": 9600, "pitch": 60}]}]}],
                        "buses": [], "master": {}}
                job = c.render(spec, os.path.join(d, "r.wav"), end=SR * 2, tail=0)
                res = c.wait_job(job, timeout=30)
                self.assertEqual(res["frames"], SR * 2)
                job = c.render(spec, os.path.join(d, "big.wav"), end=SR * 600, tail=0)
                c.request("cancel", job=job)
                res = c.wait_job(job, timeout=30)
                self.assertTrue(res.get("cancelled"))
                self.assertFalse(os.path.exists(os.path.join(d, "big.wav")))
                self.assertFalse(os.path.exists(os.path.join(d, "big.wav.part")))
            st = c.request("status")
            self.assertIn("meters", st)
            with self.assertRaises(client.EngineError):
                c.request("commande_inexistante")
        finally:
            c.close()
        self.assertFalse(c.alive())


if __name__ == "__main__":
    unittest.main()
