"""Service médias et pics : décodage FLAC / MP3 réel vers le cache PCM, absence signalée,
pyramides min/max bornées par la largeur de la vue."""
import os
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, os.path.dirname(__file__))
import _isolate  # noqa: F401

import numpy as np

SR = 44100


def encode(path: Path, codec: str, data: np.ndarray, sr: int = SR) -> Path:
    import av
    with av.open(str(path), "w") as c:
        st = c.add_stream(codec, rate=sr, layout="stereo" if data.shape[0] == 2 else "mono")
        fmt = st.codec_context.codec.audio_formats[0].name
        for i in range(0, data.shape[1], 1152):
            chunk = data[:, i:i + 1152]
            base = fmt.rstrip("p")
            if base == "s16":
                arr = (np.clip(chunk, -1, 1) * 32767).astype(np.int16)
            elif base == "s32":
                arr = (np.clip(chunk, -1, 1) * 2147483647.0).astype(np.int32)
            elif base == "dbl":
                arr = chunk.astype(np.float64)
            else:
                arr = chunk.astype(np.float32)
            if not fmt.endswith("p"):
                arr = arr.T.reshape(1, -1)
            fr = __import__("av").AudioFrame.from_ndarray(np.ascontiguousarray(arr), format=fmt, layout=st.layout.name)
            fr.sample_rate = sr
            for pkt in st.encode(fr):
                c.mux(pkt)
        for pkt in st.encode(None):
            c.mux(pkt)
    return path


class _Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)
        os.environ["FMZ_AUDIO_CACHE"] = str(self.dir / "cache")
        from fm_audio_engine import media, peaks, wavio
        self.media, self.peaks, self.wavio = media, peaks, wavio
        t = np.arange(SR) / SR
        self.sig = np.stack([0.5 * np.sin(2 * np.pi * 440 * t), 0.25 * np.sin(2 * np.pi * 660 * t)]).astype(np.float32)

    def tearDown(self):
        os.environ.pop("FMZ_AUDIO_CACHE", None)
        self.tmp.cleanup()


class MediaTest(_Base):
    def test_flac_is_decoded_losslessly(self):
        src = encode(self.dir / "a.flac", "flac", self.sig)
        info = self.media.probe(src)
        self.assertFalse(info.native)
        self.assertEqual((info.sample_rate, info.channels), (SR, 2))
        self.assertIsNone(self.media.cached_pcm(str(src)))   # rien sans travail explicite
        pcm = self.media.ensure_pcm(str(src))
        data, sr = self.wavio.read(pcm)
        self.assertEqual(sr, SR)
        self.assertEqual(data.shape, (2, SR))
        np.testing.assert_allclose(data, self.sig, atol=1.0 / 32768 * 2)
        self.assertEqual(self.media.cached_pcm(str(src)), pcm)   # cache réutilisé

    def test_mp3_is_decoded(self):
        src = encode(self.dir / "a.mp3", "libmp3lame", self.sig)
        pcm = self.media.ensure_pcm(str(src))
        data, sr = self.wavio.read(pcm)
        self.assertEqual(sr, SR)
        self.assertGreater(data.shape[1], SR * 0.95)
        # contenu réel : la piste gauche est à 440 Hz
        seg = data[0, 10000:30000]
        zc = np.sum((seg[:-1] < 0) & (seg[1:] >= 0)) / (len(seg) / SR)
        self.assertAlmostEqual(zc, 440, delta=5)

    def test_wav_is_native_and_missing_is_reported(self):
        w = self.wavio.write(self.dir / "a.wav", self.sig, SR, fmt="pcm24")
        self.assertTrue(self.media.probe(w).native)
        self.assertEqual(self.media.cached_pcm(str(w)), str(w))
        with self.assertRaises(self.media.MediaMissing):
            self.media.probe(self.dir / "absent.flac")

    def test_cancel_leaves_no_partial_file(self):
        src = encode(self.dir / "a.flac", "flac", self.sig)
        with self.assertRaises(self.media.MediaError):
            self.media.ensure_pcm(str(src), cancel=lambda: True)
        self.assertEqual(list((self.dir / "cache").glob("*.wav*")), [])

    def test_hash_verifies_content(self):
        a = self.wavio.write(self.dir / "a.wav", self.sig, SR)
        b = self.wavio.write(self.dir / "b.wav", self.sig, SR)
        self.assertEqual(self.media.content_hash(a), self.media.content_hash(b))


class PeaksTest(_Base):
    def test_pyramid_matches_samples(self):
        rng = np.random.default_rng(3)
        data = (rng.standard_normal((2, 100000)) * 0.3).astype(np.float32)
        p = self.wavio.write(self.dir / "n.wav", data, SR)
        pk = self.peaks.compute(str(p))
        self.assertEqual(pk.levels[0][0], 64)
        self.assertEqual(pk.levels[1][0], 256)
        # une vue de 100 pixels à 1000 échantillons/pixel = vrais min/max de chaque tranche
        mins, maxs = pk.view(0, 1000, 100)
        self.assertEqual(mins.shape, (2, 100))
        for px in (0, 37, 99):
            seg = data[0, px * 1000:(px + 1) * 1000]
            self.assertLessEqual(mins[0, px], seg.min() + 1e-6)
            self.assertGreaterEqual(maxs[0, px], seg.max() - 1e-6)
            self.assertGreater(mins[0, px], seg.min() - 0.05)   # au plus un bloc de débord
        # cache relu (float16) cohérent
        again = self.peaks.load_cached(str(p))
        self.assertIsNotNone(again)
        self.assertEqual(len(again.levels), len(pk.levels))

    def test_view_work_is_bounded_by_width(self):
        data = np.zeros((1, SR * 60), np.float32)
        data[0, SR * 30] = 1.0
        p = self.wavio.write(self.dir / "long.wav", data, SR)
        pk = self.peaks.compute(str(p))
        lvl = pk.level_for(SR * 60 / 800)
        self.assertGreaterEqual(pk.levels[lvl][0], 1024)  # niveau grossier pour une vue d'ensemble
        mins, maxs = pk.view(0, SR * 60 / 800, 800)
        self.assertAlmostEqual(float(np.nanmax(maxs)), 1.0, places=2)
        self.assertTrue(np.isnan(pk.view(SR * 61, 10, 5)[0]).all())  # hors média
        self.assertEqual(self.peaks.pcm_window(str(p), SR * 30, 10).shape, (1, 10))


if __name__ == "__main__":
    unittest.main()
