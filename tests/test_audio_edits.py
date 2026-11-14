"""Édition non destructive : chaque opération est vérifiée sur le RENDU du moteur (au sample),
l'original n'est jamais modifié, Undo rétablit exactement l'état précédent."""
import os
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, os.path.dirname(__file__))
import _isolate  # noqa: F401

import numpy as np

from fm_audio_engine import client, edits, media, wavio
from fm_audio_engine.project import Clip, Project, Track, compile_spec

SR = 48000


@unittest.skipUnless(client.available()[0], "moteur audio non compilé")
class EditsTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)
        self.ramp = (np.arange(SR, dtype=np.float32) / SR * 0.8 - 0.4).reshape(1, -1)   # chaque sample est unique
        self.src = str(wavio.write(self.dir / "ramp.wav", self.ramp, SR))
        self.digest = media.content_hash(self.src)
        self.p = Project()
        self.t = self.p.add_track(Track(id="t", name="A"))
        with self.p.edit("init", "t"):
            self.t.clips.append(Clip(id="c", path=self.src, start=1000, offset=0, length=SR))

    def tearDown(self):
        self.assertEqual(media.content_hash(self.src), self.digest, "le média source a été modifié")
        self.tmp.cleanup()

    def render(self, end=SR + 4000, name="o.wav"):
        res = client.render_offline(compile_spec(self.p), self.dir / name, end=end, tail=0, overwrite=True)
        return wavio.read(res["path"])[0][0]

    def test_split_is_seamless_and_undoable(self):
        before = self.render()
        ids = edits.split(self.p, "t", "c", 20000)
        self.assertEqual(len(self.t.clips), 2)
        np.testing.assert_array_equal(self.render(), before)
        self.p.history.undo()
        self.assertEqual([c.id for c in self.p.track("t").clips], ["c"])
        self.assertIsNotNone(ids)

    def test_delete_with_and_without_ripple(self):
        edits.delete_range(self.p, ["t"], 11000, 21000)
        out = self.render()
        self.assertTrue(np.all(out[11000:21000] == 0))
        self.assertAlmostEqual(float(out[21000]), float(self.ramp[0, 20000]), places=6)
        self.p.history.undo()
        edits.delete_range(self.p, ["t"], 11000, 21000, ripple=True)
        out = self.render(name="r.wav")
        self.assertAlmostEqual(float(out[11000]), float(self.ramp[0, 20000]), places=6)
        self.assertEqual(self.p.length_samples(), 1000 + SR - 10000)

    def test_copy_paste_and_crop(self):
        cb = edits.copy_range(self.p, ["t"], 1000, 1100)
        edits.paste(self.p, cb, 30000, ["t"])
        out = self.render()
        np.testing.assert_allclose(out[30000:30100], self.ramp[0, 0:100], atol=1e-7)
        self.assertAlmostEqual(float(out[30100]), float(self.ramp[0, 29100]), places=6)  # reste intact après
        edits.crop(self.p, ["t"], 5000, 6000, to_zero=True)
        out = self.render(end=2000, name="c.wav")
        np.testing.assert_allclose(out[:1000], self.ramp[0, 4000:5000], atol=1e-7)
        self.assertTrue(np.all(out[1000:] == 0))

    def test_trim_move_and_fades(self):
        edits.trim(self.p, "t", "c", new_start=500)          # pas avant le début du média
        c = self.t.clips[0]
        self.assertEqual((c.start, c.offset), (1000, 0))
        edits.trim(self.p, "t", "c", new_start=2000, new_end=3000)
        self.assertEqual((c.start, c.offset, c.length), (2000, 1000, 1000))
        edits.move_clips(self.p, [("t", "c")], -5000)        # borné à 0
        self.assertEqual(c.start, 0)
        edits.set_fades(self.p, "t", "c", fade_in=100, fade_out=5000)
        self.assertEqual((c.fade_in, c.fade_out), (100, 900))
        out = self.render(end=1000)
        self.assertEqual(float(out[0]), 0.0)
        self.assertAlmostEqual(float(out[50]), float(self.ramp[0, 1050]) * 0.5, places=6)

    def test_gain_polarity_normalize_rate(self):
        res = edits.normalize(self.p, "t", {"c"}, target_db=-6.0206)
        self.assertAlmostEqual(res["c"], 20 * np.log10(0.5 / 0.4), places=3)
        edits.invert_polarity(self.p, "t", {"c"})
        out = self.render()
        self.assertAlmostEqual(float(np.max(np.abs(out))), 0.5, places=3)
        self.assertAlmostEqual(float(out[1000]), 0.5, places=3)       # -0.4 inversé puis normalisé
        edits.set_rate(self.p, "t", "c", 2.0)
        self.assertEqual(self.t.clips[0].length, SR // 2)
        out = self.render(name="rate.wav")
        self.assertAlmostEqual(float(out[1000 + 1000]), -float(self.ramp[0, 2000]) * 1.25, places=3)

    def test_crossfade_on_overlap(self):
        edits.split(self.p, "t", "c", 20000)
        a, b = self.t.clips
        edits.move_clips(self.p, [("t", b.id)], -1000)
        self.assertEqual(edits.crossfade(self.p, "t", a.id, b.id), 1000)
        out = self.render()
        self.assertTrue(np.all(np.isfinite(out)))
        # au milieu du fondu, puissance constante : chaque côté pèse sin(π/4)
        m = 19500
        exp = (self.ramp[0, m - 1000] + self.ramp[0, m - 1000 + 1000]) * np.sin(np.pi / 4)
        self.assertAlmostEqual(float(out[m]), float(exp), places=2)


if __name__ == "__main__":
    unittest.main()
