"""Banc de fluidité de FM Audio / FM Music (Qt offscreen) : temps de peinture de la timeline
pendant zoom et défilement d'une prise de 30 min, et du piano roll avec 5 000 notes.

    python tools/bench_audio_ui.py [minutes=30] [notes=5000]

Critères (mission §9) : p95 ≤ 16,7 ms, p99 ≤ 33 ms, aucune image ≥ 50 ms. Les pics sont calculés
AVANT la mesure (travail de fond) : la mesure porte sur la peinture seule.
"""
import os
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import numpy as np  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402


def stats(ms: list) -> dict:
    a = np.sort(np.array(ms))
    return {"n": int(a.size), "p50": float(np.percentile(a, 50)), "p95": float(np.percentile(a, 95)),
            "p99": float(np.percentile(a, 99)), "max": float(a.max())}


def main() -> int:
    minutes = float(sys.argv[1]) if len(sys.argv) > 1 else 30
    n_notes = int(sys.argv[2]) if len(sys.argv) > 2 else 5000
    app = QApplication.instance() or QApplication([])
    with tempfile.TemporaryDirectory() as d:
        os.environ["FMZ_AUDIO_CACHE"] = str(Path(d) / "cache")
        from fm_audio_engine import peaks, wavio
        from fm_audio_engine.project import PPQ, MidiClip, Note
        sr = 48000
        path = Path(d) / "long.wav"
        w = wavio.StreamWriter(path, sr, 1)
        rng = np.random.default_rng(0)
        for _ in range(int(minutes * 60)):
            w.write((rng.standard_normal((1, sr)) * 0.2).astype(np.float32))
        w.close()
        t0 = time.perf_counter()
        peaks.compute(str(path))
        build_s = time.perf_counter() - t0
        from fm_audio.pane import AudioPane
        pane = AudioPane(None, hooks={})
        pane.resize(1600, 900)
        pane.open_path(path)
        pane.session._worker and pane.session._worker.join(60)
        app.processEvents()
        v = pane.view
        v.resize(1500, 600)
        frames = []
        v.zoom_fit()
        for k in range(120):                       # zoom avant / arrière puis défilement
            v.zoom(0.85 if k < 60 else 1 / 0.85, v.width() / 2)
            t = time.perf_counter()
            v.grab()
            frames.append((time.perf_counter() - t) * 1000)
        v.spp = 64
        for k in range(120):
            v.x0 += v.spp * 40
            t = time.perf_counter()
            v.grab()
            frames.append((time.perf_counter() - t) * 1000)
        timeline = stats(frames)
        pane.shutdown()
        from fm_music.pane import MusicPane
        mp = MusicPane(None, hooks={})
        mp.resize(1600, 900)
        t = mp.project.tracks[1]
        notes = [Note(int(i * PPQ // 4), PPQ // 4, 36 + (i * 7) % 48, 100) for i in range(n_notes)]
        with mp.project.edit("banc", t.id):
            t.midi_clips = [MidiClip(start_tick=0, length_tick=n_notes * PPQ // 4 + PPQ, notes=notes)]
        mp.roll.set_clip(t.id, t.midi_clips[0].id)
        mp.roll.resize(1500, 500)
        frames = []
        for k in range(120):
            mp.roll.t0 = k * PPQ * 2
            tt = time.perf_counter()
            mp.roll.grab()
            frames.append((time.perf_counter() - tt) * 1000)
        roll = stats(frames)
        mp.shutdown()
    ok = all(s["p95"] <= 16.7 and s["p99"] <= 33 and s["max"] < 50 for s in (timeline, roll))
    print({"pics_s": round(build_s, 2), "timeline_ms": timeline, "piano_roll_ms": roll})
    print("RÉUSSI" if ok else "ÉCHEC : p95 > 16,7 ms, p99 > 33 ms ou image ≥ 50 ms")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
