"""Traitements hors ligne et analyse : résultats MESURÉS sur signaux de référence
(sinus, bruit déterministe, impulsions), jamais une simple exécution."""
import math
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(__file__))
import _isolate  # noqa: F401

import numpy as np

from fm_audio_engine import analysis, dsp_offline as d

SR = 48000


def sine(f, secs=1.0, amp=0.5, sr=SR):
    t = np.arange(int(sr * secs)) / sr
    return (amp * np.sin(2 * np.pi * f * t)).astype(np.float32)[None, :]


def freq_of(x, sr=SR):
    m = np.atleast_2d(x).mean(axis=0)
    m = m[len(m) // 4: 3 * len(m) // 4]
    spec = np.abs(np.fft.rfft(m * np.hanning(m.size), 1 << 18))
    k = int(np.argmax(spec))
    return k * sr / (1 << 18)


class StretchPitchTest(unittest.TestCase):
    def test_time_stretch_keeps_pitch(self):
        x = sine(440, 1.0)
        y = d.time_stretch(x, 1.5)
        self.assertEqual(y.shape[1], int(round(SR * 1.5)))
        self.assertAlmostEqual(freq_of(y), 440, delta=3)
        y = d.time_stretch(x, 0.7)
        self.assertEqual(y.shape[1], int(round(SR * 0.7)))
        self.assertAlmostEqual(freq_of(y), 440, delta=3)

    def test_pitch_shift_keeps_duration(self):
        x = sine(440, 1.0)
        y = d.pitch_shift(x, 12)
        self.assertEqual(y.shape[1], SR)
        self.assertAlmostEqual(freq_of(y), 880, delta=6)
        y = d.pitch_shift(x, -5)
        self.assertAlmostEqual(freq_of(y), 440 * 2 ** (-5 / 12), delta=4)

    def test_resample_quality(self):
        x = sine(1000, 0.5, sr=44100)
        y = d.resample(x, 48000 / 44100)
        self.assertEqual(y.shape[1], 24000)
        self.assertAlmostEqual(freq_of(y), 1000, delta=2)
        self.assertAlmostEqual(float(np.max(np.abs(y[:, 1000:-1000]))), 0.5, delta=0.01)


class RestorationTest(unittest.TestCase):
    def test_noise_reduction_improves_snr_and_exposes_residual(self):
        rng = np.random.default_rng(7)
        noise = (rng.standard_normal((1, SR * 2)) * 0.05).astype(np.float32)
        clean = sine(440, 2.0, 0.3)
        clean[:, :SR // 2] = 0                         # demi-seconde de bruit seul = profil
        x = clean + noise
        y, residual = d.noise_reduce(x, x[:, :SR // 2], reduction_db=24)
        def snr(sig):
            return 10 * np.log10(np.sum(clean[:, SR:] ** 2) / np.sum((sig[:, SR:] - clean[:, SR:]) ** 2))
        self.assertGreater(snr(y) - snr(x), 6.0)       # gain mesurable
        np.testing.assert_allclose(y + residual, x, atol=1e-5)
        silence = float(np.sqrt(np.mean(y[:, 2000:SR // 2 - 2000] ** 2)))
        self.assertLess(silence, 0.05 * 10 ** (-12 / 20))

    def test_spectral_edit_removes_tone_only(self):
        x = sine(440, 1.0, 0.3) + sine(3000, 1.0, 0.3)
        y = d.spectral_edit(x, SR, 0.2, 0.8, 2800, 3200, -80)
        f, db_in = analysis.spectrum(x[:, int(0.3 * SR):int(0.7 * SR)], SR)
        f, db_out = analysis.spectrum(y[:, int(0.3 * SR):int(0.7 * SR)], SR)
        k3, k4 = int(np.argmin(np.abs(f - 3000))), int(np.argmin(np.abs(f - 440)))
        self.assertLess(db_out[k3], db_in[k3] - 40)
        self.assertAlmostEqual(db_out[k4], db_in[k4], delta=0.5)
        # hors de la zone temporelle : intact
        np.testing.assert_allclose(y[:, :int(0.1 * SR)], x[:, :int(0.1 * SR)], atol=1e-3)

    def test_spectrogram_tile_peak_at_tone(self):
        import tempfile
        from pathlib import Path
        from fm_audio_engine import spectro, wavio
        with tempfile.TemporaryDirectory() as dd:
            p = wavio.write(Path(dd) / "t.wav", sine(1000, 4.0, 0.5), SR)
            q = spectro.compute_tile(str(p), 1)
            self.assertEqual(q.shape, (spectro.N_FFT // 2 + 1, spectro.TILE_FRAMES))
            col = q[:, 100]
            self.assertEqual(int(np.argmax(col)), spectro.freq_bin(1000, SR))
            self.assertGreater(int(col.max()), 200)                     # près de 0 dBFS (sinus -6 dBFS)
            self.assertLess(int(np.median(col)), 60)

    def test_declick(self):
        x = sine(200, 0.5, 0.3)
        clicks = [5000, 12000, 20000]
        dirty = x.copy()
        for c in clicks:
            dirty[0, c] += 0.9
        y, n = d.declick(dirty)
        self.assertEqual(n, len(clicks))
        self.assertLess(float(np.max(np.abs(y - x))), 0.05)


class AnalysisTest(unittest.TestCase):
    def test_loudness_reference(self):
        # EBU Tech 3341 : sinus 1 kHz à -23 dBFS en stéréo = -23,0 LUFS
        amp = 10 ** (-23 / 20)
        x = np.vstack([sine(1000, 20, amp)[0], sine(1000, 20, amp)[0]])
        L = analysis.loudness(x, SR)
        self.assertAlmostEqual(L["integrated"], -23.0, delta=0.1)
        self.assertLess(L["lra"], 0.5)

    def test_true_peak_exceeds_sample_peak(self):
        # sinus à fs/4 déphasé de 45° : échantillons à 0,707 de la crête vraie
        n = np.arange(4800)
        x = (np.sin(2 * np.pi * n / 4 + np.pi / 4)).astype(np.float32)[None, :] * 0.9
        self.assertAlmostEqual(analysis.peak_dbfs(x), 20 * math.log10(0.9 * math.sqrt(0.5)), places=3)
        self.assertAlmostEqual(analysis.true_peak_dbtp(x), 20 * math.log10(0.9), delta=0.3)

    def test_align_sources_finds_lag_and_polarity(self):
        rng = np.random.default_rng(1)
        ref = rng.standard_normal((1, SR)).astype(np.float32)
        other = -np.roll(ref, 137, axis=1)
        r = analysis.align_sources(ref, other)
        self.assertEqual(r["lag"], 137)
        self.assertTrue(r["invert"])

    def test_tuner(self):
        f = analysis.pitch_yin(sine(110.0 * 2 ** (10 / 1200), 0.2), SR)
        t = analysis.tuner(f)
        self.assertEqual((t["note"], t["octave"]), ("la", 2))
        self.assertAlmostEqual(t["cents"], 10, delta=1.0)
        t = analysis.tuner(442.0, ref_a4=442.0)
        self.assertEqual((t["note"], t["cents"]), ("la", 0.0))
        self.assertIsNone(analysis.pitch_yin(np.zeros((1, 4800), np.float32), SR))


if __name__ == "__main__":
    unittest.main()
