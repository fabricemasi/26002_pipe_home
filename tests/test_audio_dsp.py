"""Effets et instruments du moteur : comportement MESURÉ sur signaux de référence, rendu par le
moteur réel (même graphe qu'en temps réel)."""
import os
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, os.path.dirname(__file__))
import _isolate  # noqa: F401

import numpy as np

from fm_audio_engine import client, wavio

SR = 48000


def tone(f, secs=1.0, amp=0.5):
    t = np.arange(int(SR * secs)) / SR
    return (amp * np.sin(2 * np.pi * f * t)).astype(np.float32)


def rms_db(x):
    return 20 * np.log10(np.sqrt(np.mean(np.square(x))) + 1e-12)


def harmonic_db(x, f0, k):
    spec = np.abs(np.fft.rfft(x * np.hanning(x.size)))
    freqs = np.fft.rfftfreq(x.size, 1 / SR)
    i = int(np.argmin(np.abs(freqs - f0 * k)))
    return 20 * np.log10(spec[i - 2:i + 3].max() + 1e-12)


@unittest.skipUnless(client.available()[0], "moteur audio non compilé")
class DspTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)
        self.n = 0

    def tearDown(self):
        self.tmp.cleanup()

    def run_fx(self, signal, fx, secs=None, tail=0):
        self.n += 1
        m = str(wavio.write(self.dir / f"in{self.n}.wav", np.atleast_2d(signal), SR))
        length = np.atleast_2d(signal).shape[1]
        spec = {"sample_rate": SR, "tracks": [{"id": "t", "fx": fx, "clips": [{"media": m, "start": 0, "length": length}]}],
                "buses": [], "master": {}}
        res = client.render_offline(spec, self.dir / f"out{self.n}.wav", end=length, tail=tail)
        return wavio.read(res["path"])[0][0], res

    def test_eq_bell_gain_at_center(self):
        x = tone(1000)
        y, _ = self.run_fx(x, [{"type": "eq", "params": {"b0_on": 1, "b0_freq": 1000, "b0_gain_db": 6, "b0_q": 1}}])
        self.assertAlmostEqual(rms_db(y[SR // 2:]) - rms_db(x[SR // 2:]), 6.0, delta=0.15)
        y, _ = self.run_fx(tone(100), [{"type": "eq", "params": {"b0_on": 1, "b0_freq": 1000, "b0_gain_db": 6, "b0_q": 4}}])
        self.assertAlmostEqual(rms_db(y[SR // 2:]) - rms_db(tone(100)[SR // 2:]), 0.0, delta=0.2)
        y, _ = self.run_fx(tone(100), [{"type": "filter", "params": {"type": 1, "freq": 1000}}])   # passe-haut
        self.assertLess(rms_db(y[SR // 2:]) - rms_db(tone(100)[SR // 2:]), -35)

    def test_compressor_ratio(self):
        x = tone(1000, amp=1.0)          # crête 0 dBFS, enveloppe crête au-dessus du seuil de 20 dB
        y, _ = self.run_fx(x, [{"type": "compressor", "params": {"threshold_db": -20, "ratio": 4, "knee_db": 0, "attack_ms": 1, "release_ms": 50}}])
        # sortie attendue : -20 + 20/4 = -15 dBFS crête, soit -15 dB de réduction
        self.assertAlmostEqual(20 * np.log10(np.max(np.abs(y[SR // 2:]))), -15, delta=0.8)
        quiet = tone(1000, amp=0.05)
        y, _ = self.run_fx(quiet, [{"type": "compressor", "params": {"threshold_db": -20, "ratio": 4, "knee_db": 0}}])
        np.testing.assert_allclose(y, quiet, atol=1e-5)          # sous le seuil : intact

    def test_limiter_ceiling_and_latency(self):
        x = tone(200, amp=1.5)
        y, res = self.run_fx(x, [{"type": "limiter", "params": {"ceiling_db": -3, "lookahead_ms": 2}}])
        self.assertLessEqual(float(np.max(np.abs(y))), 10 ** (-3 / 20) + 1e-5)
        self.assertEqual(res["latency"], 96)
        self.assertGreater(float(np.max(np.abs(y[SR // 2:]))), 10 ** (-3 / 20) - 0.02)

    def test_gate_attenuates_below_threshold(self):
        x = np.concatenate([tone(300, 0.5, 0.5), tone(300, 0.5, 0.002)])
        y, _ = self.run_fx(x, [{"type": "gate", "params": {"threshold_db": -30, "range_db": -60, "release_ms": 20, "hold_ms": 10}}])
        self.assertAlmostEqual(rms_db(y[5000:20000]) - rms_db(x[5000:20000]), 0, delta=0.2)
        # détecteur (relâchement 30 ms) + maintien + relâchement : fermé ~0,3 s après la chute
        self.assertLess(rms_db(y[SR // 2 + 16000:]) - rms_db(x[SR // 2 + 16000:]), -50)

    def test_deesser_only_cuts_highs(self):
        low, high = tone(300, amp=0.3), tone(7000, amp=0.3)
        y, _ = self.run_fx(low + high, [{"type": "deesser", "params": {"freq": 5000, "threshold_db": -40, "ratio": 8}}])
        self.assertLess(harmonic_db(y[SR // 4:], 7000, 1) - harmonic_db((low + high)[SR // 4:], 7000, 1), -6)
        self.assertAlmostEqual(harmonic_db(y[SR // 4:], 300, 1), harmonic_db((low + high)[SR // 4:], 300, 1), delta=0.5)
        y, _ = self.run_fx(low, [{"type": "deesser", "params": {"freq": 5000, "threshold_db": -40}}])
        self.assertAlmostEqual(rms_db(y[SR // 4:]), rms_db(low[SR // 4:]), delta=0.1)   # passe-tout : niveau intact

    def test_delay_echo_position_and_tail(self):
        x = np.zeros(SR, np.float32)
        x[0] = 1.0
        y, res = self.run_fx(x, [{"type": "delay", "params": {"time_ms": 250, "feedback": 0.5, "mix": 0.5, "highcut": 20000}}], tail=1)
        self.assertEqual(int(np.argmax(np.abs(y[100:]))) + 100, SR // 4)
        self.assertGreater(float(np.abs(y[SR // 2 - 5:SR // 2 + 5]).max()), 0.05)     # deuxième répétition

    def test_reverb_has_decaying_tail(self):
        x = np.zeros(SR * 2, np.float32)
        x[:480] = tone(500, 0.01, 0.8)
        y, _ = self.run_fx(x, [{"type": "reverb", "params": {"room": 0.8, "mix": 1.0}}])
        e1, e2 = rms_db(y[int(0.1 * SR):int(0.3 * SR)]), rms_db(y[int(1.2 * SR):int(1.4 * SR)])
        self.assertGreater(e1, -60)
        self.assertLess(e2, e1 - 6)
        self.assertTrue(np.all(np.isfinite(y)))

    def test_chorus_and_distortion(self):
        x = tone(440, amp=0.4)
        y, _ = self.run_fx(x, [{"type": "chorus", "params": {"rate_hz": 2, "depth_ms": 5, "mix": 1}}])
        self.assertGreater(float(np.std(np.abs(y[SR // 4:]) - np.abs(x[SR // 4:]))), 0.01)
        y, _ = self.run_fx(x, [{"type": "distortion", "params": {"drive_db": 30, "type": 0, "tone": 20000, "output_db": 0}}])
        clean_h3 = harmonic_db(x[SR // 4:], 440, 3)
        self.assertGreater(harmonic_db(y[SR // 4:], 440, 3), clean_h3 + 40)        # harmoniques impaires
        self.assertLess(float(np.max(np.abs(y))), 1.15)   # tanh borné ; léger dépassement du filtre anti-repliement

    def test_amp_is_nonlinear_and_asymmetric(self):
        x = tone(220, amp=0.3)
        y, _ = self.run_fx(x, [{"type": "amp", "params": {"channel": 2, "gain": 0.8, "master_db": 0}}])
        self.assertGreater(harmonic_db(y[SR // 4:], 220, 2), harmonic_db(x[SR // 4:], 220, 2) + 30)   # paires : triode polarisée
        y_lo, _ = self.run_fx(tone(220, amp=0.03), [{"type": "amp", "params": {"channel": 2, "gain": 0.8, "master_db": 0}}])
        # non linéaire : 20 dB de plus en entrée donnent bien moins de 20 dB en sortie (saturation)
        self.assertLess(rms_db(y[SR // 4:]) - rms_db(y_lo[SR // 4:]), 12)

    def test_cabinet_ir_is_exact_convolution(self):
        rng = np.random.default_rng(5)
        ir = (rng.standard_normal(3000) * np.exp(-np.arange(3000) / 400)).astype(np.float32) * 0.2
        irp = str(wavio.write(self.dir / "ir.wav", ir[None, :], SR))
        x = (rng.standard_normal(SR // 4) * 0.2).astype(np.float32)
        y, res = self.run_fx(x, [{"type": "cabinet", "params": {"ir": irp, "mix": 1}}])
        ref = np.convolve(x, ir)[:x.size]
        self.assertEqual(res["latency"], 0)                          # sans latence (tête directe + partitions)
        np.testing.assert_allclose(y, ref, atol=2e-4)
        _, res = self.run_fx(x, [{"type": "cabinet", "params": {"ir": str(self.dir / "absente.wav")}}])
        self.assertTrue(any("IR illisible" in w for w in res["warnings"]))

    def test_sampler_plays_sample_at_pitch_and_reports_missing(self):
        sample = tone(440, 0.5, 0.5)
        sp = str(wavio.write(self.dir / "s.wav", sample[None, :], SR))
        spec = {"sample_rate": SR, "tempo": {"ppq": 960, "points": [{"tick": 0, "bpm": 120}]},
                "tracks": [{"id": "smp", "instrument": {"type": "sampler", "zones": [{"path": sp, "root": 69}, {"path": str(self.dir / "x.wav"), "root": 60}],
                                                        "params": {"attack": 0.0, "release": 0.01}},
                            "midi_clips": [{"notes": [{"tick": 0, "length": 960, "pitch": 81, "vel": 127}]}]}],
                "buses": [], "master": {}}
        res = client.render_offline(spec, self.dir / "smp.wav", end=SR // 4, tail=0)
        y = wavio.read(res["path"])[0][0]
        self.assertTrue(any("sample absent" in w for w in res["warnings"]))
        seg = y[2000:10000]
        zc = np.sum((seg[:-1] < 0) & (seg[1:] >= 0)) / (seg.size / SR)
        self.assertAlmostEqual(zc, 880, delta=8)                      # une octave au-dessus de la racine

    def test_dsp_stability_extremes(self):
        x = np.concatenate([np.zeros(1000), np.ones(1000) * 4.0, -np.ones(1000) * 4.0, np.zeros(SR)]).astype(np.float32)
        fx = [{"type": t, "params": p} for t, p in (
            ("eq", {"b0_on": 1, "b0_freq": 20, "b0_gain_db": 24, "b0_q": 10}), ("compressor", {"ratio": 100, "attack_ms": 0.01}),
            ("gate", {"threshold_db": 0}), ("delay", {"feedback": 0.95, "time_ms": 1}), ("reverb", {"room": 1}),
            ("distortion", {"drive_db": 60}), ("amp", {"gain": 1, "channel": 2}), ("limiter", {"ceiling_db": -0.1}))]
        y, res = self.run_fx(x, fx)
        self.assertFalse(res["nan"])
        self.assertTrue(np.all(np.isfinite(y)))
        self.assertLessEqual(float(np.max(np.abs(y))), 1.0)


if __name__ == "__main__":
    unittest.main()
