"""Préécoute (sans Qt) : graphe minimal d'un seul son, chargé dans le moteur PARTAGÉ."""
from __future__ import annotations

from . import wavio


def preview_spec(pcm_path: str, gain_db: float = -3.0) -> dict:
    info = wavio.probe(pcm_path)
    return {"sample_rate": info.sample_rate, "revision": -1,
            "tracks": [{"id": "preview", "gain_db": gain_db, "channels": 1 if info.channels == 1 else 2,
                        "clips": [{"media": pcm_path, "start": 0, "length": info.frames}]}],
            "buses": [], "master": {"fx": [{"type": "limiter", "params": {"ceiling_db": -1}}]}}
