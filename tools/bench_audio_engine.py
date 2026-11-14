"""Banc du moteur audio : coût de calcul du graphe par bloc (128 échantillons à 48 kHz).

    python tools/bench_audio_engine.py [pistes=32] [blocs=8000]

Scène : N pistes (clip audio + EQ + compresseur), 1 bus réverbe en send, limiteur au master.
Critère (mission §9) : p99 ≤ 50 % de l'échéance B/Fs (2,67 ms à 128/48 kHz), max < échéance.
Mesure le DSP seul : l'ordonnancement du pilote (xruns, jitter) se mesure sur matériel réel.
"""
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from fm_audio_engine import client, wavio  # noqa: E402


def scene(n_tracks: int, media: str) -> dict:
    tracks = []
    for i in range(n_tracks):
        tracks.append({"id": f"t{i}", "pan": (i % 7 - 3) / 3.0, "sends": [{"target": "rev", "gain_db": -12}],
                       "clips": [{"media": media, "start": (i * 997) % 4800, "length": 48000 * 60}],
                       "fx": [{"type": "eq", "params": {"b0_on": 1, "b0_freq": 300 + i * 10, "b0_gain_db": 3, "b0_q": 1}},
                              {"type": "compressor", "params": {"threshold_db": -20, "ratio": 3}}]})
    return {"sample_rate": 48000, "tracks": tracks,
            "buses": [{"id": "rev", "fx": [{"type": "reverb", "params": {"mix": 1}}]}],
            "master": {"fx": [{"type": "limiter", "params": {"ceiling_db": -1}}]}}


def main() -> int:
    n = int(sys.argv[1]) if len(sys.argv) > 1 else 32
    blocks = int(sys.argv[2]) if len(sys.argv) > 2 else 8000
    ok, why = client.available()
    if not ok:
        print(why)
        return 1
    with tempfile.TemporaryDirectory() as d:
        rng = np.random.default_rng(0)
        media = str(wavio.write(Path(d) / "noise.wav", (rng.standard_normal((2, 48000 * 60)) * 0.1).astype(np.float32), 48000))
        spec = Path(d) / "spec.json"
        spec.write_text(json.dumps(scene(n, media)), "utf-8")
        r = subprocess.run([str(client.ENGINE_EXE), "--bench", str(spec), str(blocks), "128"], capture_output=True, text=True)
        res = json.loads(r.stdout.strip().splitlines()[-1])
    res["tracks"] = n
    print(json.dumps(res, ensure_ascii=False))
    verdict = res.get("ok") and res["p99_ratio"] <= 0.5 and res["max_us"] < res["deadline_us"]
    print("RÉUSSI" if verdict else "ÉCHEC : p99 > 50 % de l'échéance ou max ≥ échéance")
    return 0 if verdict else 1


if __name__ == "__main__":
    sys.exit(main())
