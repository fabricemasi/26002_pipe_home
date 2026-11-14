"""Plugins : inventaire VST3 sans chargement (dossiers indiqués seulement, délai borné) et politique
« plugin absent » : signalé par le moteur, son inchangé, aucun substitut."""
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

from fm_audio_engine import client, plugins, wavio
from fm_audio_engine.project import Clip, Fx, Project, Track, compile_spec

SR = 48000


class PluginsTest(unittest.TestCase):
    def test_inventory_reads_metadata_without_loading(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d) / "VST3"
            b = root / "Fabricant" / "Super Comp.vst3" / "Contents" / "Resources"
            b.mkdir(parents=True)
            (b / "moduleinfo.json").write_text(json.dumps({"Name": "Super Comp", "Version": "1.2", "Factory Info": {"Vendor": "ACME"},
                                                           "Classes": [{"CID": "ABCD", "Name": "Super Comp", "Category": "Audio Module Class",
                                                                        "Sub Categories": ["Fx", "Dynamics"]}]}), "utf-8")
            (root / "Sans info.vst3").mkdir()
            res = plugins.scan([root, Path(d) / "absent"])
            names = [p["name"] for p in res["plugins"]]
            self.assertEqual(names, ["Sans info", "Super Comp"])
            sc = res["plugins"][1]
            self.assertEqual((sc["vendor"], sc["classes"][0]["id"]), ("ACME", "ABCD"))
            self.assertFalse(res["plugins"][0]["metadata"])
            self.assertEqual(plugins.effect_ref("ABCD"), "vst3:ABCD")

    @unittest.skipUnless(client.available()[0], "moteur audio non compilé")
    def test_missing_plugin_reported_and_bypassed(self):
        with tempfile.TemporaryDirectory() as d:
            x = (np.sin(np.arange(SR) / SR * 2 * np.pi * 300) * 0.4).astype(np.float32)[None, :]
            m = str(wavio.write(Path(d) / "a.wav", x, SR))
            p = Project()
            t = Track(fx=[Fx("vst3:ABCD", {}, name="Super Comp")])
            t.clips.append(Clip(path=m, start=0, length=SR))
            p.tracks.append(t)
            self.assertEqual(plugins.missing_plugins(p)[0]["name"], "Super Comp")
            res = client.render_offline(compile_spec(p), Path(d) / "o.wav", end=SR, tail=0)
            self.assertTrue(any("vst3:ABCD" in w for w in res["warnings"]))
            y, _ = wavio.read(res["path"])
            np.testing.assert_allclose(y[0], x[0], atol=1e-6)        # son inchangé, rien de substitué


def _vst3_host() -> dict:
    """Plugins de test compilés depuis le SDK, si le moteur héberge VST3 ; {} sinon."""
    from fm_audio_engine import build
    try:
        if "vst3" not in json.loads(build.STAMP.read_text("utf-8")).get("sdks", []):
            return {}
        return {k: str(v) for k, v in build.build_test_plugins().items()}
    except (OSError, ValueError, RuntimeError):
        return {}


TP = _vst3_host() if client.available()[0] else {}
GAIN = "vst3:464D5A314741494E5445535400000001"
SYNTH = "vst3:464D5A3153594E545445535400000002"


def sine(f=440.0, secs=1.0, amp=0.4):
    return (amp * np.sin(2 * np.pi * f * np.arange(int(SR * secs)) / SR)).astype(np.float32)[None, :]


@unittest.skipUnless(TP, "moteur compilé sans l'hôte VST3 (SDK absent)")
class Vst3HostTest(unittest.TestCase):
    """Hôte VST3 réel sur les plugins de TEST du dépôt (résultats connus d'avance) : FMZ Test Gain
    (sortie = entrée retardée de 64 × 2·Gain, latence déclarée 64, état = Gain) et FMZ Test Synth
    (une sinusoïde par note)."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.d = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def render(self, p, name="o.wav"):
        res = client.render_offline(compile_spec(p), self.d / name, end=SR, tail=0)
        y, _ = wavio.read(res["path"])
        return y, res.get("warnings", [])

    def test_effect_processes_and_latency_is_compensated(self):
        x = sine()
        src = str(wavio.write(self.d / "s.wav", x, SR))
        p = Project()
        dry, wet = p.add_track(), p.add_track()
        dry.clips.append(Clip(path=src, start=0, length=SR))
        wet.clips.append(Clip(path=src, start=0, length=SR))
        wet.fx.append(plugins.fx_for({"type": GAIN, "path": TP["good"], "name": "FMZ Test Gain"}))
        wet.fx[0].params["p0"] = 0.25                                   # gain 0,5
        y, warns = self.render(p)
        self.assertEqual(warns, [])
        # sec + traité ALIGNÉS (PDC) : 1,5·x ; sans compensation, filtrage en peigne à 64 échantillons
        np.testing.assert_allclose(y[0, 500:-500], 1.5 * x[0, 500:-500], atol=1e-5)

    def test_isolated_scan_cache_and_quarantine(self):
        from unittest import mock
        with mock.patch.dict(os.environ, {"FMZ_AUDIO_CACHE": str(self.d / "cache")}):
            good = plugins.scan_module(TP["good"], timeout=10)
            self.assertEqual(good["status"], "ok")
            self.assertEqual({c["name"]: (c["instrument"], c.get("latency")) for c in good["classes"]},
                             {"FMZ Test Gain": (False, 64), "FMZ Test Synth": (True, 0)})
            self.assertTrue(plugins.scan_module(TP["good"])["cached"])
            crash = plugins.scan_module(TP["crash"], timeout=10)
            self.assertEqual(crash["status"], "quarantine")
            self.assertIn("planté", crash["error"])
            hang = plugins.scan_module(TP["hang"], timeout=3)
            self.assertEqual(hang["status"], "quarantine")
            self.assertIn("ne répond plus", hang["error"])
            self.assertEqual(len(plugins.quarantined()), 2)
            self.assertTrue(plugins.scan_module(TP["crash"])["cached"])      # jamais relancé tant qu'il ne change pas
            plugins.release_quarantine(TP["crash"])
            self.assertEqual(len(plugins.quarantined()), 1)
            # le moteur de lecture n'a rien subi : un rendu passe toujours
            p = Project()
            p.add_track().clips.append(Clip(path=str(wavio.write(self.d / "s.wav", sine(), SR)), start=0, length=SR))
            self.assertGreater(float(np.abs(self.render(p)[0]).max()), 0.3)

    def test_state_roundtrip_and_parameter_automation(self):
        import base64
        import struct
        x = sine()
        src = str(wavio.write(self.d / "s.wav", x, SR))
        spec_fx = {"type": GAIN, "params": {"path": TP["good"], "p0": 0.75}, "bypass": False, "sidechain": "", "automation": {}}
        spec = {"sample_rate": SR, "revision": 1, "tempo": {"ppq": 960, "points": [{"tick": 0, "bpm": 120}]},
                "tracks": [{"id": "t", "clips": [{"path": src, "start": 0, "length": SR}], "fx": [spec_fx]}],
                "buses": [], "master": {}}
        c = client.EngineClient()
        c.start()
        try:
            c.request("open_device", output="test", buffer=128, test={"fast": True, "max_frames": SR})
            c.request("load", spec=spec)
            c.request("play", **{"from": 0})
            time.sleep(0.4)
            info = c.request("vst3_params", node="t", slot="fx0")
            self.assertEqual(info["latency"], 64)
            self.assertEqual([q["title"] for q in info["params"]], ["Gain"])
            state = c.request("vst3_state", node="t", slot="fx0")["state"]
            # même instance après une reconstruction du graphe (pas de rechargement à chaque édition)
            spec["revision"] = 2
            c.request("load", spec=spec)
            self.assertEqual(c.request("vst3_state", node="t", slot="fx0")["state"], state)
        finally:
            c.close()
        magic, gain = struct.unpack("<id", base64.b64decode(state))
        self.assertEqual((magic, round(gain, 6)), (0x464D5A31, 0.75))
        # état seul (sans p0) : le rendu reproduit le réglage sauvé
        p = Project()
        t = p.add_track()
        t.clips.append(Clip(path=src, start=0, length=SR))
        t.fx.append(Fx(GAIN, {"path": TP["good"], "state": state}, name="FMZ Test Gain"))
        y, warns = self.render(p)
        self.assertEqual(warns, [])
        np.testing.assert_allclose(y[0, 500:-500], 1.5 * x[0, 500:-500], atol=1e-5)
        # automation du paramètre : rampe 0 -> 1 sur la seconde, mesurée dans le rendu
        t.fx[0].params.pop("state")
        t.fx[0].automation = {"p0": {"unit": "sample", "points": [[0, 0.0], [SR, 1.0]]}}
        y, _ = self.render(p, "a.wav")
        q = SR // 4
        rms = [float(np.sqrt(np.mean(y[0, k * q:(k + 1) * q] ** 2))) for k in range(4)]
        self.assertTrue(all(a < b for a, b in zip(rms, rms[1:])), rms)
        self.assertLess(rms[0], 0.3 * rms[3])

    def test_instrument_plays_notes_and_absent_is_silent(self):
        from fm_audio_engine.project import PPQ, MidiClip, Note
        p = Project()
        t = p.add_track()
        t.kind = "instrument"
        t.instrument = plugins.instrument_for({"type": SYNTH, "path": TP["good"], "name": "FMZ Test Synth"})
        t.midi_clips.append(MidiClip(start_tick=0, length_tick=4 * PPQ, notes=[Note(0, PPQ, 69, 127)]))
        y, warns = self.render(p)
        self.assertEqual(warns, [])
        m = y[0, 2000:20000]
        spec = np.abs(np.fft.rfft(m * np.hanning(m.size), 1 << 18))
        self.assertAlmostEqual(np.argmax(spec) * SR / (1 << 18), 440.0, delta=1.0)
        self.assertAlmostEqual(float(np.abs(m).max()), 1.0, delta=0.01)   # vélocité 1 × Level 0,5 × 2
        self.assertLess(float(np.abs(y[0, SR // 2 + 200:]).max()), 1e-6)  # note relâchée à 0,5 s (1 temps à 120 bpm)
        t.instrument = {"type": SYNTH, "path": str(self.d / "absent.vst3"), "name": "FMZ Test Synth"}
        self.assertEqual(plugins.missing_plugins(p)[0]["name"], "FMZ Test Synth")
        y, warns = self.render(p, "absent.wav")
        self.assertTrue(any("plugin instrument absent" in w and "aucun son de substitution" in w for w in warns), warns)
        self.assertEqual(float(np.abs(y).max()), 0.0)


@unittest.skipUnless(TP, "moteur compilé sans l'hôte VST3 (SDK absent)")
class Vst3EditorTest(unittest.TestCase):
    """Éditeurs : fenêtre portée par le MOTEUR (fil d'interface à part), audio continu pendant l'ouverture,
    plugin sans éditeur signalé, fenêtre refermée quand le plugin quitte le projet ; menus des éditeurs
    tirés du cache de scan (aucun processus pendant l'ouverture d'un menu)."""

    setUp = Vst3HostTest.setUp
    tearDown = Vst3HostTest.tearDown

    def test_editor_window_lifecycle(self):
        import ctypes
        win = lambda: ctypes.windll.user32.FindWindowW("FMZVst3Editor", "FMZ Test Gain")
        fx = {"type": GAIN, "params": {"path": TP["good"]}}
        spec = {"sample_rate": SR, "revision": 1, "tempo": {"ppq": 960, "points": [{"tick": 0, "bpm": 120}]},
                "tracks": [{"id": "t", "fx": [fx], "instrument": {"type": SYNTH, "path": TP["good"]}, "midi_clips": []}],
                "buses": [], "master": {}}
        c = client.EngineClient()
        c.start()
        try:
            c.request("open_device", output="test", buffer=128, test={"fast": False})
            c.request("load", spec=spec)
            c.request("play", **{"from": 0})
            r = c.request("vst3_editor", node="t", slot="fx0", open=True)
            self.assertEqual((r["open"], r["width"], r["height"]), (True, 320, 120))
            self.assertTrue(win())
            p0 = c.request("status")["pos"]
            time.sleep(0.3)
            self.assertGreater(c.request("status")["pos"], p0)               # l'audio n'attend pas l'éditeur
            with self.assertRaises(client.EngineError) as cm:
                c.request("vst3_editor", node="t", slot="inst", open=True)
            self.assertIn("pas d'éditeur", str(cm.exception))
            c.request("load", spec=dict(spec, revision=2, tracks=[{"id": "t", "fx": [], "midi_clips": []}]))
            deadline = time.monotonic() + 3
            while win() and time.monotonic() < deadline:
                time.sleep(0.05)
            self.assertFalse(win())                                          # plugin retiré : fenêtre refermée
            c.request("load", spec=dict(spec, revision=3))
            self.assertTrue(c.request("vst3_editor", node="t", slot="fx0", open=True)["open"])
            self.assertFalse(c.request("vst3_editor", node="t", slot="fx0", open=False)["open"])
            self.assertFalse(win())
        finally:
            c.close()

    def test_menus_from_scan_cache(self):
        import shutil
        from unittest import mock
        os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
        from PySide6.QtWidgets import QApplication, QMenu
        self.app = QApplication.instance() or QApplication([])
        from fm_sound_ui import plugins_ui
        lib_dir = self.d / "VST3"
        lib_dir.mkdir()
        shutil.copy(TP["good"], lib_dir / "FMZTest.vst3")
        settings = {"audio_plugin_dirs": str(lib_dir)}
        with mock.patch.dict(os.environ, {"FMZ_AUDIO_CACHE": str(self.d / "cache")}), \
                mock.patch.object(plugins, "standard_dirs", lambda: []):
            m = QMenu()
            acts = plugins_ui.add_library_menu(m, "effects", settings)
            self.assertIn(("rescan", None), acts.values())
            self.assertFalse([v for v in acts.values() if v[0] == "plugin"])  # rien de scanné : aucun processus lancé
            res = plugins.library(plugins.dirs_from_settings(settings))
            self.assertEqual([i["name"] for i in res["effects"]], ["FMZ Test Gain"])
            m = QMenu()
            acts = plugins_ui.add_library_menu(m, "effects", settings)
            items = [v[1] for v in acts.values() if v[0] == "plugin"]
            self.assertEqual([i["name"] for i in items], ["FMZ Test Gain"])
            m = QMenu()
            acts = plugins_ui.add_library_menu(m, "instruments", settings)
            self.assertEqual([v[1]["name"] for v in acts.values() if v[0] == "plugin"], ["FMZ Test Synth"])

        class _Session:
            project = Project()
        t = _Session.project.add_track()
        t.fx.append(plugins.fx_for(items[0]))
        from fm_sound_ui.session import AudioSession
        slots = AudioSession.plugin_slots(_Session)
        self.assertEqual([(nid, slot) for _o, nid, slot in slots], [(t.id, "fx0")])
        m = QMenu()
        acts = plugins_ui.add_slot_actions(m, type("S", (), {"plugin_slots": lambda self: slots})())
        self.assertEqual([a.text() for a in acts], ["Éditeur : FMZ Test Gain"])


if __name__ == "__main__":
    unittest.main()
