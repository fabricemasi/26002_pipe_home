"""Modèle de projet commun : carte tempo (= moteur C++), schéma, migrations, sauvegarde
transactionnelle, Undo/Redo, groupes, comping, patterns, compilation et rendu réel."""
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, os.path.dirname(__file__))
import _isolate  # noqa: F401

import numpy as np

from fm_audio_engine import client, wavio
from fm_audio_engine.project import (PPQ, Bus, Clip, Fx, Group, IncompatibleProject, MidiClip, Note, Project,
                                     ProjectError, TempoMap, Track, comp_clips, compile_spec, migrate)

SR = 48000
ENGINE = client.available()[0]


class TempoMapTest(unittest.TestCase):
    def test_constant_tempo(self):
        tm = TempoMap([{"tick": 0, "bpm": 120}], sample_rate=SR)
        self.assertEqual(tm.tick_to_sample(PPQ), 24000)
        self.assertAlmostEqual(tm.sample_to_tick(24000), PPQ)

    def test_no_cumulative_drift(self):
        tm = TempoMap([{"tick": 0, "bpm": 97.31}], sample_rate=SR)
        # 10 000 temps : calcul direct depuis le début du segment (pas de somme d'arrondis)
        exact = 10000 * PPQ * 60 * SR / (97.31 * PPQ)
        self.assertLessEqual(abs(tm.tick_to_sample(10000 * PPQ) - exact), 0.5)

    def test_bar_beat_with_signature_change(self):
        tm = TempoMap(signatures=[{"tick": 0, "num": 4, "den": 4}, {"tick": 8 * PPQ, "num": 3, "den": 4}])
        self.assertEqual(tm.bar_beat(0), (1, 1, 0))
        self.assertEqual(tm.bar_beat(8 * PPQ), (3, 1, 0))
        self.assertEqual(tm.bar_beat(8 * PPQ + 3 * PPQ + PPQ), (4, 2, 0))

    @unittest.skipUnless(ENGINE, "moteur audio non compilé")
    def test_engine_and_python_agree_across_tempo_changes(self):
        tempo = [{"tick": 0, "bpm": 120}, {"tick": 1920, "bpm": 97.3}, {"tick": 3840, "bpm": 143.7}]
        p = Project("music")
        p.tempo = tempo
        t = Track(kind="instrument", instrument={"type": "synth", "params": {"attack": 0.0001, "osc1_wave": 1, "osc2_wave": 1}})
        ticks = [960, 2500, 5000]
        t.midi_clips.append(MidiClip(start_tick=0, length_tick=6000, notes=[Note(k, 120, 72, 127) for k in ticks]))
        p.tracks.append(t)
        tm = p.tempo_map()
        with tempfile.TemporaryDirectory() as d:
            res = client.render_offline(compile_spec(p), Path(d) / "t.wav", end=tm.tick_to_sample(6000), tail=0)
            data, _ = wavio.read(res["path"])
        sig = np.abs(data[0])
        for k in ticks:
            s = tm.tick_to_sample(k)
            first = s + int(np.argmax(sig[s:s + 200] > 0))
            self.assertEqual(first, s, f"note au tick {k}")


class PersistenceTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def sample_project(self):
        p = Project("audio", "Essai")
        t = p.add_track(name="Voix")
        with p.edit("clips", t.id):
            t.clips.append(Clip(path="C:/média/é.wav", start=100, length=4800, fade_in=10))
            t.fx.append(Fx("compressor", {"ratio": 4}))
            t.automation["gain_db"] = {"unit": "sample", "points": [[0, -6], [48000, 0]]}
        p.buses.append(Bus(id="rev", fx=[Fx("reverb")]))
        p.extensions["fm_audio"] = {"zoom": 12.5}
        p.patterns["p1"] = {"name": "Kick", "length_tick": PPQ, "notes": [Note(0, 120, 36, 110)]}
        return p

    def test_roundtrip_is_faithful(self):
        p = self.sample_project()
        path = p.save(self.dir / "a.fmaudio")
        q = Project.load(path)
        self.assertEqual(q.to_dict(), p.to_dict())
        self.assertEqual(q.extensions["fm_audio"]["zoom"], 12.5)
        self.assertFalse(q.history.dirty)

    def test_transactional_save_keeps_backup(self):
        p = self.sample_project()
        path = p.save(self.dir / "a.fmaudio")
        p.name = "Deuxième"
        p.save()
        self.assertTrue((self.dir / "a.fmaudio.bak").exists())
        self.assertEqual(json.loads((self.dir / "a.fmaudio.bak").read_text("utf-8"))["name"], "Essai")
        self.assertFalse((self.dir / "a.fmaudio.part").exists())
        self.assertEqual(Project.load(path).name, "Deuxième")

    def test_future_schema_refused_untouched(self):
        path = self.dir / "futur.fmaudio"
        raw = json.dumps({"format": "pipe-fmz-audio-project", "schema": 99, "tracks": []})
        path.write_text(raw, "utf-8")
        with self.assertRaises(IncompatibleProject):
            Project.load(path)
        self.assertEqual(path.read_text("utf-8"), raw)

    def test_migration_v0(self):
        v0 = {"sample_rate": 48000, "bpm": 90, "tracks": [{"id": "t", "clips": [{"path": "x.wav", "start_s": 1.5, "length_s": 0.5}]}]}
        d = migrate(v0)
        self.assertEqual(d["schema"], 1)
        self.assertEqual(d["tempo"], [{"tick": 0, "bpm": 90.0}])
        p = Project.from_dict(v0)
        c = p.tracks[0].clips[0]
        self.assertEqual((c.start, c.length), (72000, 24000))

    def test_corrupt_file_is_a_clear_error(self):
        path = self.dir / "x.fmaudio"
        path.write_text('{"tracks": [', "utf-8")
        with self.assertRaises(ProjectError):
            Project.load(path)


class HistoryTest(unittest.TestCase):
    def test_undo_redo_and_revision(self):
        p = Project()
        t = p.add_track(name="A")
        r0 = p.revision
        with p.edit("gain", t.id):
            t.gain_db = -3
        self.assertEqual(p.revision, r0 + 1)
        self.assertEqual(p.history.undo(), "gain")
        self.assertEqual(p.track(t.id).gain_db, 0)
        self.assertEqual(p.revision, r0 + 2)        # chaque état a sa propre révision
        p.history.redo()
        self.assertEqual(p.track(t.id).gain_db, -3)
        p.history.undo()
        p.history.undo()                             # annule l'ajout de piste
        self.assertEqual(p.tracks, [])

    def test_failed_edit_is_rolled_back(self):
        p = Project()
        t = p.add_track()
        with self.assertRaises(RuntimeError):
            with p.edit("raté", t.id):
                p.track(t.id).name = "modifié"
                raise RuntimeError("x")
        self.assertEqual(p.track(t.id).name, "Piste")
        self.assertEqual(len(p.history.undo_stack), 1)

    def test_noop_edit_not_recorded(self):
        p = Project()
        t = p.add_track()
        with p.edit("rien", t.id):
            pass
        self.assertEqual(len(p.history.undo_stack), 1)


class CompileTest(unittest.TestCase):
    def test_group_vca_and_mute(self):
        p = Project()
        p.groups.append(Group(id="g", gain_db=-6, mute=False))
        p.tracks.append(Track(id="a", gain_db=-1, group="g"))
        spec = compile_spec(p)
        self.assertAlmostEqual(spec["tracks"][0]["gain_db"], -7)
        p.groups[0].mute = True
        self.assertTrue(compile_spec(p)["tracks"][0]["mute"])

    def test_comp_crossfade_keeps_takes(self):
        t = Track()
        t.takes = [{"id": "k1", "clips": [Clip(path="a.wav", start=0, length=10000)]},
                   {"id": "k2", "clips": [Clip(path="b.wav", start=0, length=10000)]}]
        t.comp = [{"start": 0, "end": 5000, "take": "k1", "xfade": 200}, {"start": 5000, "end": 10000, "take": "k2", "xfade": 200}]
        out = comp_clips(t)
        self.assertEqual([c.path for c in out], ["a.wav", "b.wav"])
        self.assertEqual(out[0].end, 5100)
        self.assertEqual(out[1].start, 4900)
        self.assertEqual(out[1].offset, 4900)
        self.assertEqual(len(t.takes[0]["clips"]), 1)  # prises intactes

    def test_looper_stacks_loop_takes(self):
        from fm_audio_engine.project import stack_loop_takes
        p = Project()
        t = p.add_track()
        p.loop = {"on": True, "start": 1000, "end": 5000}
        with p.edit("prises", t.id):
            t.takes = [{"id": f"k{i}", "clips": [Clip(path=f"p{i}.wav", start=1000, length=4000)]} for i in range(3)]
        self.assertEqual(stack_loop_takes(p, t.id), 3)
        self.assertEqual([c.path for c in p.track(t.id).clips], ["p0.wav", "p1.wav", "p2.wav"])
        self.assertEqual(len(p.track(t.id).takes), 3)
        p.history.undo()
        self.assertEqual(p.track(t.id).clips, [])

    @unittest.skipUnless(ENGINE, "moteur audio non compilé")
    def test_comping_renders_chosen_takes_with_crossfade(self):
        from fm_audio_engine.project import set_comp
        with tempfile.TemporaryDirectory() as d:
            k1 = str(wavio.write(Path(d) / "k1.wav", np.full((1, SR), 0.2, np.float32), SR))
            k2 = str(wavio.write(Path(d) / "k2.wav", np.full((1, SR), 0.6, np.float32), SR))
            p = Project()
            t = p.add_track()
            with p.edit("prises", t.id):
                t.takes = [{"id": "a", "clips": [Clip(path=k1, start=0, length=SR, take="a")]},
                           {"id": "b", "clips": [Clip(path=k2, start=0, length=SR, take="b")]}]
                t.clips = [Clip(path=k2, start=0, length=SR, take="b")]       # dernière prise posée
            set_comp(p, t.id, "a", 0, SR, xfade=0)
            set_comp(p, t.id, "b", SR // 2, SR, xfade=480)
            self.assertEqual([(s["take"], s["start"], s["end"]) for s in p.track(t.id).comp],
                             [("a", 0, SR // 2), ("b", SR // 2, SR)])
            self.assertEqual(p.track(t.id).clips, [])                          # la prise posée laisse la place
            res = client.render_offline(compile_spec(p), Path(d) / "c.wav", end=SR, tail=0)
            y, _ = wavio.read(res["path"])
            self.assertAlmostEqual(float(y[0, SR // 4]), 0.2, places=4)
            self.assertAlmostEqual(float(y[0, 3 * SR // 4]), 0.6, places=4)
            mid = float(y[0, SR // 2])                                          # fondu enchaîné, pas de trou
            self.assertGreater(mid, 0.2)
            self.assertEqual(len(p.track(t.id).takes), 2)
            p.history.undo()
            self.assertEqual(len(p.track(t.id).comp), 1)

    def test_pattern_repeats_over_clip(self):
        p = Project("music")
        p.patterns["p"] = {"name": "x", "length_tick": PPQ, "notes": [Note(0, 100, 36, 100)]}
        t = Track(kind="instrument", instrument={"type": "drums"})
        t.midi_clips.append(MidiClip(start_tick=0, length_tick=4 * PPQ, pattern="p"))
        p.tracks.append(t)
        notes = compile_spec(p)["tracks"][0]["midi_clips"][0]["notes"]
        self.assertEqual([n["tick"] for n in notes], [0, PPQ, 2 * PPQ, 3 * PPQ])

    @unittest.skipUnless(ENGINE, "moteur audio non compilé")
    def test_sidechain_ducking_and_fx_automation(self):
        with tempfile.TemporaryDirectory() as d:
            pad = str(wavio.write(Path(d) / "pad.wav", np.full((1, SR), 0.5, np.float32), SR))
            kick = np.zeros((1, SR), np.float32)
            kick[0, SR // 2:SR // 2 + 4800] = 0.9
            k = str(wavio.write(Path(d) / "kick.wav", kick, SR))
            p = Project()
            ta = Track(id="kick", mute=False, output="sc")
            ta.clips.append(Clip(path=k, start=0, length=SR))
            tb = Track(id="pad", fx=[Fx("compressor", {"threshold_db": -30, "ratio": 20, "attack_ms": 0.1, "release_ms": 5, "knee_db": 0, "sidechain": 1}, sidechain="kick"),
                                    Fx("gain", {"gain_db": 0}, automation={"gain_db": {"unit": "sample", "points": [[0, 0], [SR // 4, 0], [SR // 4 + 1, -6.0206]]}})])
            tb.clips.append(Clip(path=pad, start=0, length=SR))
            p.tracks += [ta, tb]
            p.buses.append(Bus(id="sc", mute=True))           # la grosse caisse sert seulement de détection
            res = client.render_offline(compile_spec(p), Path(d) / "o.wav", end=SR, tail=0)
            y, _ = wavio.read(res["path"])
            self.assertAlmostEqual(float(y[0, 1000]), 0.5, places=3)          # avant : intact
            # automation d'un paramètre d'effet : appliquée par bloc (512) puis lissée (10 ms)
            self.assertAlmostEqual(float(y[0, SR // 4 + 6000]), 0.25, places=3)
            self.assertLess(float(y[0, SR // 2 + 2000]), 0.05)               # sidechain : le pad s'efface

    def test_project_renders_with_bus_and_automation(self):
        with tempfile.TemporaryDirectory() as d:
            m = str(wavio.write(Path(d) / "dc.wav", np.full((1, SR), 0.5, np.float32), SR))
            p = Project()
            t = Track(id="a", sends=[{"target": "b", "gain_db": 0, "pre": True}], gain_db=-120)
            t.clips.append(Clip(path=m, start=0, length=SR))
            p.tracks.append(t)
            p.buses.append(Bus(id="b", automation={"gain_db": {"unit": "sample", "points": [[0, -120], [SR, 0]]}}))
            res = client.render_offline(compile_spec(p), Path(d) / "o.wav", end=SR, tail=0)
            data, _ = wavio.read(res["path"])
            # send pré-fader : le fader à -120 dB ne coupe pas le bus ; automation en rampe
            self.assertLess(float(data[0, 100]), 0.01)
            self.assertGreater(float(data[0, SR - 10]), 0.45)
            self.assertEqual(res["revision"], p.revision)


if __name__ == "__main__":
    unittest.main()
