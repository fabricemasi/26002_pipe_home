"""Préréglages : chaînes d'usine rendues par le moteur sans avertissement ni NaN, préréglages
utilisateur sauvegardés / relus (transactionnel), version future refusée sans écraser."""
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, os.path.dirname(__file__))
import _isolate  # noqa: F401

import numpy as np

from fm_audio_engine import client, presets, wavio
from fm_audio_engine.project import Fx

SR = 48000


class PresetsStoreTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        os.environ["FMZ_AUDIO_PRESETS"] = str(Path(self.tmp.name) / "p.json")

    def tearDown(self):
        os.environ.pop("FMZ_AUDIO_PRESETS", None)
        self.tmp.cleanup()

    def test_user_presets_roundtrip_and_shadow_factory(self):
        presets.save_chain("Ma voix", [Fx("eq", {"b0_on": 1}), Fx("compressor", {"ratio": 3})])
        presets.save_instrument("Basse ronde", {"type": "synth", "params": {"cutoff": 200}})
        self.assertEqual([f["type"] for f in presets.chains()["Ma voix"]], ["eq", "compressor"])
        self.assertEqual(presets.instruments()["Basse ronde"]["params"], {"cutoff": 200})     # masque l'usine
        self.assertIn("osc1_wave", presets.INSTRUMENT_PRESETS["Basse ronde"]["params"])        # usine intacte
        self.assertTrue(presets.delete_user("instrument", "Basse ronde"))
        self.assertIn("osc1_wave", presets.instruments()["Basse ronde"]["params"])
        self.assertFalse(Path(os.environ["FMZ_AUDIO_PRESETS"] + ".part").exists())

    def test_future_version_refused(self):
        p = Path(os.environ["FMZ_AUDIO_PRESETS"])
        p.write_text(json.dumps({"version": 99, "chains": {}}), "utf-8")
        with self.assertRaises(ValueError):
            presets.save_chain("x", [])
        self.assertEqual(json.loads(p.read_text("utf-8"))["version"], 99)


@unittest.skipUnless(client.available()[0], "moteur audio non compilé")
class PresetsRenderTest(unittest.TestCase):
    def test_every_factory_chain_and_instrument_renders(self):
        with tempfile.TemporaryDirectory() as d:
            t = np.arange(SR) / SR
            m = str(wavio.write(Path(d) / "gtr.wav", (0.3 * np.sin(2 * np.pi * 196 * t) * np.exp(-t * 2))[None, :].astype(np.float32), SR))
            tracks = [{"id": f"c{i}", "fx": chain, "clips": [{"media": m, "start": 0, "length": SR}]}
                      for i, chain in enumerate(presets.CHAIN_PRESETS.values())]
            tracks += [{"id": f"i{i}", "instrument": inst, "midi_clips": [{"notes": [{"tick": 0, "length": 960, "pitch": 48, "vel": 110},
                                                                                     {"tick": 0, "length": 240, "pitch": 36, "vel": 110}]}]}
                       for i, inst in enumerate(presets.INSTRUMENT_PRESETS.values())]
            spec = {"sample_rate": SR, "tracks": tracks, "buses": [], "master": {"fx": presets.CHAIN_PRESETS["Mastering doux"]}}
            res = client.render_offline(spec, Path(d) / "o.wav", end=SR, tail=0)
            self.assertEqual(res["warnings"], [])
            self.assertFalse(res["nan"])
            stems = Path(d) / "stems"
            stems.mkdir()
            client.render_offline(spec, Path(d) / "x.wav", end=SR // 2, tail=0, stems=str(stems))
            for p in stems.glob("*.wav"):
                y, _ = wavio.read(p)
                self.assertGreater(float(np.max(np.abs(y))), 1e-3, p.name)   # chaque préréglage produit du son


if __name__ == "__main__":
    unittest.main()
