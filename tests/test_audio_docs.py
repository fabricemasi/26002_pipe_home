"""Mission audio : documents de décision et décomposition du registre (tâches doc / décision).

Vérifie le CONTENU attendu (carte d'intégration, inventaire des licences, décision et protocole IPC,
décomposition sans retrait), pas seulement l'existence des fichiers.
"""
import json
import os
import sys
import unittest
from pathlib import Path

sys.path.insert(0, os.path.dirname(__file__))
import _isolate  # noqa: F401

ROOT = Path(__file__).resolve().parent.parent
DOC = ROOT / "docs" / "agents" / "fm_audio.md"
REG = ROOT / "docs" / "agents" / "audio_music_state.json"


class AudioDocsTest(unittest.TestCase):
    def setUp(self):
        self.doc = DOC.read_text("utf-8")
        self.reg = json.loads(REG.read_text("utf-8"))

    def test_integration_map(self):
        for needle in ("## Carte d'intégration", "module_targets.py", "fm_pdf/board_model.py", "drop_mime",
                       "DEFAULT_SETTINGS", "fm_video/pane.py"):
            self.assertIn(needle, self.doc)

    def test_licence_inventory(self):
        # SDK autorisés le 2026-11-14 : version, variante de licence et condition de distribution consignées
        for needle in ("## Inventaire natif et licences", "MSVC", "JUCE", "PyAV", "ASIO SDK (Steinberg) | 2.3.4",
                       "variante GPLv3", "DISTRIBUER", "VST3 SDK (Steinberg) | 3.8.1", "MIT"):
            self.assertIn(needle, self.doc)

    def test_architecture_decision_and_ipc(self):
        for needle in ("D-ARCH-01", "### Protocole IPC v1", "hello", "telemetry", "cancel", "SPSC",
                       "Les blocs audio ne transitent JAMAIS"):
            self.assertIn(needle, self.doc)

    def test_registry_decomposition(self):
        reqs = {r["id"] for r in self.reg["requirements"]}
        self.assertEqual(set(self.reg["baseline_requirements"]), reqs)
        for rid in reqs:
            if rid in ("R-PILOT", "R-AUDIT", "R-LIC"):
                continue
            kinds = {t["kind"] for t in self.reg["tasks"] if t["requirement"] == rid}
            self.assertTrue(kinds & {"code", "perf"}, f"{rid} sans tâche code/perf")
            need = next(r for r in self.reg["requirements"] if r["id"] == rid)["validations"]
            for manual in ("hardware", "human"):
                if need.get(manual):
                    self.assertTrue(any(t["kind"] in ("hardware", "human") for t in self.reg["tasks"] if t["requirement"] == rid),
                                    f"{rid} : validation {manual} sans tâche")
        for t in self.reg["tasks"]:
            if t["status"] == "blocked":
                self.assertTrue(t.get("blocker"))

    def test_module_map_and_pitfalls(self):
        for needle in ("## Pièges rencontrés", "## Politiques retenues", "teststream.h", "fm_sound_ui/", "Stems", "Plugin absent"):
            self.assertIn(needle, self.doc)
        for rel in ("fm_audio_engine/library.py", "fm_audio/board_item.py", "fm_music/pianoroll.py", "main_window/audio_module.py"):
            self.assertTrue((ROOT / rel).exists(), rel)

    def test_reference_profile_and_deferred_measures(self):
        text = (ROOT / "docs" / "agents" / "a_mesurer.md").read_text("utf-8")
        self.assertIn("Profil de référence : i9-9900K", text)
        for cmd in ("`python tools/bench_audio_engine.py 32 8000`", "`python tools/bench_audio_engine.py 64 8000`",
                    "`python tools/bench_audio_ui.py`", "VALIDE R-RT performance"):
            self.assertIn(cmd, text)
        self.assertTrue((ROOT / "tools" / "bench_audio_engine.py").exists())
        self.assertTrue((ROOT / "tools" / "bench_audio_ui.py").exists())

    def test_engine_build_is_reproducible(self):
        sys.path.insert(0, str(ROOT))
        from fm_audio_engine import build
        self.assertEqual(build.sources_digest(), build.sources_digest())
        self.assertIn("/std:c++20", build.FLAGS)


if __name__ == "__main__":
    unittest.main()
