"""MIDI : quantification / swing / groove réversibles, SMF aller-retour exact, notes sans fin."""
import os
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, os.path.dirname(__file__))
import _isolate  # noqa: F401

from fm_audio_engine import midi
from fm_audio_engine.project import PPQ, Note

G = PPQ // 4


class QuantizeTest(unittest.TestCase):
    def notes(self):
        return [Note(13, 200, 60, 90), Note(G + 31, 100, 62, 80), Note(2 * G - 40, 50, 64, 70)]

    def test_quantize_is_reversible_and_does_not_accumulate(self):
        ns = self.notes()
        midi.quantize(ns, G)
        self.assertEqual([n.tick for n in ns], [0, G, 2 * G])
        midi.quantize(ns, G, strength=0.5)       # repart de l'ORIGINE, pas du résultat précédent
        self.assertEqual(ns[0].tick, 6)
        midi.unquantize(ns)
        self.assertEqual([(n.tick, n.length) for n in ns], [(13, 200), (G + 31, 100), (2 * G - 40, 50)])
        self.assertIsNone(ns[0].orig_tick)

    def test_swing_and_ends(self):
        ns = self.notes()
        midi.quantize(ns, G, swing=0.5, ends=True)
        self.assertEqual(ns[1].tick, G + G // 4)   # position impaire retardée
        self.assertEqual(ns[0].tick + ns[0].length, G)

    def test_groove_template(self):
        ns = [Note(k * G, 60, 36, 100) for k in range(4)]
        midi.apply_groove(ns, [0, 20, 0, -10], G, velocity=[1.0, 0.5, 1.0, 0.8])
        self.assertEqual([n.tick for n in ns], [0, G + 20, 2 * G, 3 * G - 10])
        self.assertEqual([n.vel for n in ns], [100, 50, 100, 80])
        midi.unquantize(ns)
        self.assertEqual([n.tick for n in ns], [0, G, 2 * G, 3 * G])


class SmfTest(unittest.TestCase):
    def test_roundtrip(self):
        notes = [Note(0, 480, 60, 100), Note(480, 480, 64, 90), Note(480, 960, 67, 80), Note(1920, 240, 60, 1)]
        with tempfile.TemporaryDirectory() as d:
            p = midi.write_smf(Path(d) / "a.mid", [{"name": "Piano é", "channel": 2, "notes": notes, "controllers": {1: [[0, 10], [960, 100]]}}],
                               tempo=[{"tick": 0, "bpm": 100}, {"tick": 1920, "bpm": 140}],
                               signatures=[{"tick": 0, "num": 3, "den": 4}])
            r = midi.read_smf(p)
        self.assertEqual(r["format"], 1)
        tr = r["tracks"][0]
        self.assertEqual(tr["name"], "Piano é")
        self.assertEqual(tr["channel"], 2)
        self.assertEqual([(n.tick, n.length, n.pitch, n.vel) for n in tr["notes"]], [(n.tick, n.length, n.pitch, n.vel) for n in notes])
        self.assertEqual(tr["controllers"][1], [[0, 10], [960, 100]])
        self.assertEqual([round(t["bpm"], 3) for t in r["tempo"]], [100.0, 140.0])
        self.assertEqual(r["signatures"], [{"tick": 0, "num": 3, "den": 4}])

    def test_resolution_rescaled_and_open_note_closed(self):
        # SMF type 0 à 96 ppq écrit à la main : une note sans note-off
        def vlq(v):
            return midi._vlq(v)
        trk = vlq(0) + bytes([0x90, 60, 100]) + vlq(96) + bytes([0x80, 60, 0]) + vlq(0) + bytes([0x90, 62, 90]) + vlq(48) + b"\xff\x2f\x00"
        data = b"MThd" + (6).to_bytes(4, "big") + (0).to_bytes(2, "big") + (1).to_bytes(2, "big") + (96).to_bytes(2, "big")
        data += b"MTrk" + len(trk).to_bytes(4, "big") + trk
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "b.mid"
            p.write_bytes(data)
            r = midi.read_smf(p)
        ns = r["tracks"][0]["notes"]
        self.assertEqual([(n.tick, n.length) for n in ns], [(0, PPQ), (PPQ, PPQ // 2)])
        self.assertEqual(len(r["warnings"]), 1)


if __name__ == "__main__":
    unittest.main()
