"""E/S réelles WASAPI (sans produire de son : graphe vide, transport arrêté) et transport temps
réel sur le périphérique de test : échange de graphe en lecture, boucle, notes à cheval,
panique, MIDI en direct."""
import os
import sys
import tempfile
import time
import unittest
from pathlib import Path

sys.path.insert(0, os.path.dirname(__file__))
import _isolate  # noqa: F401

import numpy as np

from fm_audio_engine import client, wavio

SR = 48000


@unittest.skipUnless(client.available()[0], "moteur audio non compilé")
class WasapiTest(unittest.TestCase):
    def test_enumerate_and_open_default_output_silently(self):
        c = client.EngineClient()
        c.start()
        try:
            devs = c.request("devices", timeout=10)["devices"]
            outs = [d for d in devs if d["flow"] == "output"]
            if not outs:
                self.skipTest("aucune sortie audio active sur ce poste")
            for d in devs:
                self.assertTrue(d["id"])
                if d["backend"] == "wasapi":                   # ASIO : fréquence connue à l'ouverture seulement
                    self.assertIn("sample_rate", d)
            self.assertLessEqual(sum(1 for d in outs if d["default"]), 1)
            # aucune entrée ouverte sans choix explicite ; transport arrêté = silence
            r = c.request("open_device", output="default", timeout=10)
            self.assertGreater(r["sample_rate"], 0)
            self.assertGreater(r["buffer"], 0)
            self.assertEqual(r["in_channels"], 0)
            time.sleep(0.2)
            st = c.request("status")
            self.assertEqual(st["backend"], "wasapi")
            self.assertFalse(st["playing"])
            self.assertFalse(st.get("device_lost", False))
            with self.assertRaises(client.EngineError):
                c.request("open_device", output="{0.0.0.00000000}.{inexistant}", timeout=10)
            with self.assertRaises(client.EngineError):
                c.request("record_start", dir=".", tracks=[{"id": "x"}])   # aucune entrée : refus explicite
            c.request("close_device", timeout=5)
        finally:
            c.close()


def _asio_compiled() -> bool:
    import json
    from fm_audio_engine import build
    try:
        return "asio" in json.loads(build.STAMP.read_text("utf-8")).get("sdks", [])
    except (OSError, ValueError):
        return False


def _registry_asio_drivers() -> list:
    import winreg
    try:
        k = winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\ASIO")
    except OSError:
        return []
    out, i = [], 0
    while True:
        try:
            out.append(winreg.EnumKey(k, i))
        except OSError:
            return out
        i += 1


class AsioPairTest(unittest.TestCase):
    def test_asio_is_duplex_on_one_driver(self):
        from fm_sound_ui.session import device_pair
        self.assertEqual(device_pair({"audio_output_device": "asio:X", "audio_input_device": "{wasapi}"}), ("asio:X", "asio:X"))
        self.assertEqual(device_pair({"audio_output_device": "asio:X"}), ("asio:X", ""))
        self.assertEqual(device_pair({"audio_output_device": "default", "audio_input_device": "asio:Y"}), ("asio:Y", "asio:Y"))
        self.assertEqual(device_pair({"audio_input_device": "{mic}"}), ("default", "{mic}"))


@unittest.skipUnless(client.available()[0] and _asio_compiled(), "moteur compilé sans le SDK ASIO")
class AsioTest(unittest.TestCase):
    """Backend ASIO réel : énumération = pilotes inscrits au registre (sans les charger) ; un pilote absent
    ou refusé est signalé clairement et le moteur reste utilisable. La lecture sur une vraie carte ASIO
    relève de la validation MATÉRIEL de l'utilisateur."""

    def test_enumerates_registry_drivers_and_refuses_cleanly(self):
        c = client.EngineClient()
        c.start()
        try:
            self.assertIn("asio", c.request("hello")["backends"])
            asio = [d for d in c.request("devices", timeout=20)["devices"] if d["backend"] == "asio"]
            self.assertEqual(sorted(d["name"] for d in asio), sorted(_registry_asio_drivers()))
            for d in asio:
                self.assertEqual(d["id"], "asio:" + d["name"])
                self.assertEqual(d["flow"], "duplex")
            with self.assertRaises(client.EngineError) as cm:
                c.request("open_device", output="asio:Pilote FMZ inexistant", timeout=20)
            self.assertIn("pilote introuvable", str(cm.exception))
            for d in asio:                                     # vrai pilote : ouvert, ou refus EXPLIQUÉ
                try:
                    r = c.request("open_device", output=d["id"], timeout=20)
                except client.EngineError as e:
                    self.assertIn("ASIO (" + d["name"] + ")", str(e))
                else:
                    self.assertEqual(r["backend"], "asio")
                    self.assertGreater(r["sample_rate"], 0)
                    self.assertGreater(r["buffer"], 0)
                    time.sleep(0.3)
                    self.assertFalse(c.request("status").get("device_lost"))
                    c.request("close_device")
            # le moteur reste utilisable après les refus
            r = c.request("open_device", output="test", test={"fast": True}, timeout=10)
            self.assertEqual(r["backend"], "test")
            c.request("close_device")
        finally:
            c.close()


@unittest.skipUnless(client.available()[0], "moteur audio non compilé")
class RealtimeTransportTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.out = Path(self.tmp.name) / "sortie.wav"
        self.c = client.EngineClient()
        self.c.start()

    def tearDown(self):
        self.c.close()
        self.tmp.cleanup()

    def synth_spec(self, notes, revision=1):
        return {"sample_rate": SR, "revision": revision, "tempo": {"ppq": 960, "points": [{"tick": 0, "bpm": 120}]},
                "tracks": [{"id": "s", "instrument": {"type": "synth", "params": {"attack": 0.0005, "release": 0.005, "sustain": 1.0,
                                                                                   "osc1_wave": 2, "osc2_wave": 2, "filter_env": 0, "cutoff": 18000}},
                            "midi_clips": [{"notes": notes}]}], "buses": [], "master": {}}

    def test_loop_wraps_and_cuts_straddling_note(self):
        self.c.request("open_device", output="test", buffer=128, test={"fast": True, "out": str(self.out), "max_frames": SR * 2})
        # note de 0,25 s à 0,4 s ; boucle sur [0, 0,3 s] : la note est coupée à la frontière, puis relancée
        self.c.request("load", spec=self.synth_spec([{"tick": 480, "length": 960 - 480 + 288, "pitch": 69, "vel": 127}]))
        self.c.request("loop", on=True, start=0, end=int(0.3 * SR))
        self.c.request("play", **{"from": 0})
        time.sleep(0.6)
        self.c.request("close_device", timeout=5)
        data, _ = wavio.read(self.out)
        env = np.abs(data[0])
        seg = int(0.3 * SR)
        n0 = int(0.25 * SR)
        # chaque passe : silence avant 0,25 s, son ensuite, coupé au retour de boucle
        for k in range(3):
            base = k * seg
            self.assertLess(float(env[base + 1000:base + n0 - 200].max()), 1e-4, f"passe {k}")
            self.assertGreater(float(env[base + n0 + 200:base + seg - 200].max()), 0.05, f"passe {k}")

    def test_graph_swap_while_playing_and_panic(self):
        self.c.request("open_device", output="test", buffer=128, test={"fast": False})
        self.c.request("load", spec=self.synth_spec([{"tick": 0, "length": 96000, "pitch": 60}], revision=1))
        self.c.request("play", **{"from": 0})
        time.sleep(0.15)
        for rev in range(2, 12):                       # échanges répétés à frontière de bloc pendant la lecture
            self.c.request("load", spec=self.synth_spec([{"tick": 0, "length": 96000, "pitch": 60 + rev}], revision=rev))
        time.sleep(0.15)
        st = self.c.request("status")
        self.assertEqual(st["revision"], 11)
        self.assertTrue(st["playing"])
        self.assertEqual(st["cmd_overflow"], 0)
        self.c.request("stop")
        self.c.request("note", node=0, pitch=72, vel=100)   # MIDI en direct, transport arrêté
        time.sleep(0.1)
        self.assertGreater(self.c.request("status")["meters"]["s"][0], 0.01)
        self.c.request("panic")
        time.sleep(0.15)
        self.c.request("status")
        time.sleep(0.1)
        self.assertLess(self.c.request("status")["meters"]["s"][0], 1e-4)


@unittest.skipUnless(client.available()[0], "moteur audio non compilé")
class MidiTest(unittest.TestCase):
    def test_midi_devices_input_path_and_panic(self):
        c = client.EngineClient()
        c.start()
        try:
            devs = c.request("midi_devices", timeout=30)     # 1re énumération Windows : le synthé GS s'initialise
            self.assertIsInstance(devs["inputs"], list)
            self.assertIsInstance(devs["outputs"], list)
            with self.assertRaises(client.EngineError):
                c.request("midi_open", inputs=[9999], timeout=5)              # absente : erreur explicite
            c.request("open_device", output="test", buffer=128, test={"fast": False})
            c.request("load", spec={"sample_rate": SR, "tracks": [{"id": "s", "instrument": {"type": "synth", "params": {"release": 0.01}}},
                                                          {"id": "ext", "midi_out": True, "midi_clips": [{"notes": [{"tick": 0, "length": 480, "pitch": 60}]}]}],
                                 "buses": [], "master": {}})
            c.request("midi_target", node=0)
            c.request("midi_inject", status=0x90, d1=64, d2=110)                # même file que le pilote MIDI
            time.sleep(0.15)
            st = c.request("status")
            self.assertEqual(st["midi_in"], 1)
            self.assertGreater(st["meters"]["s"][0], 0.01)
            c.request("midi_inject", status=0xB0, d1=123, d2=0)                 # all notes off
            time.sleep(0.2)
            c.request("status")
            time.sleep(0.1)
            self.assertLess(c.request("status")["meters"]["s"][0], 1e-4)
            c.request("play", **{"from": 0})                                       # piste vers sortie MIDI sans sortie ouverte : rien ne casse
            time.sleep(0.1)
            self.assertTrue(c.request("status")["playing"])
            c.request("midi_close")
        finally:
            c.close()


if __name__ == "__main__":
    unittest.main()
