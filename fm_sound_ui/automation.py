"""Automation dans la timeline : un couloir par piste (gain, pan ou paramètre d'un effet), dessiné
par-dessus les clips de la piste quand le mode automation est actif.

Gestes : clic = ajouter un point ; Ctrl + glisser un point = le déplacer (Ctrl AU DÉPART, règle de
l'appli) ; Alt + clic sur un point = le supprimer. Chaque geste = une étape d'annulation ; les points
sont exactement ceux que le moteur rend (`project.compile_spec`).
"""
from __future__ import annotations

import math

# Plages des paramètres (affichage et saisie) ; « log » : échelle logarithmique (fréquences).
RANGES = {
    "gain_db": (-60.0, 6.0, False), "pan": (-1.0, 1.0, False), "threshold_db": (-60.0, 0.0, False),
    "ratio": (1.0, 20.0, False), "mix": (0.0, 1.0, False), "freq": (20.0, 20000.0, True), "cutoff": (20.0, 20000.0, True),
    "time_ms": (1.0, 2000.0, True), "feedback": (0.0, 0.95, False), "drive_db": (0.0, 60.0, False), "room": (0.0, 1.0, False),
    "drive": (0.0, 1.0, False), "gain": (0.0, 1.0, False), "makeup_db": (-12.0, 24.0, False), "ceiling_db": (-12.0, 0.0, False),
}


def param_range(key: str) -> tuple[float, float, bool]:
    base = key.split(".", 1)[-1]
    if base in RANGES:
        return RANGES[base]
    if base.endswith("_db"):
        return (-24.0, 24.0, False)
    if base.endswith("_freq"):
        return (20.0, 20000.0, True)
    return (0.0, 1.0, False)


def to_norm(key: str, v: float) -> float:
    lo, hi, log = param_range(key)
    v = min(hi, max(lo, v))
    if log:
        return (math.log(v) - math.log(lo)) / (math.log(hi) - math.log(lo))
    return (v - lo) / (hi - lo)


def from_norm(key: str, n: float) -> float:
    lo, hi, log = param_range(key)
    n = min(1.0, max(0.0, n))
    if log:
        return math.exp(math.log(lo) + n * (math.log(hi) - math.log(lo)))
    return lo + n * (hi - lo)


def lane(track, target: str, create: bool = False) -> dict | None:
    """Couloir {"unit", "points"} de `target` : "gain_db", "pan" ou "fx<i>.<clé>"."""
    if target.startswith("fx"):
        idx, key = target[2:].split(".", 1)
        i = int(idx)
        if i >= len(track.fx):
            return None
        store = track.fx[i].automation
    else:
        key, store = target, track.automation
    if key not in store and create:
        store[key] = {"unit": "sample", "points": []}
    return store.get(key)


def targets(track) -> list[tuple[str, str]]:
    """(cible, libellé) automatisables pour une piste."""
    out = [("gain_db", "Volume"), ("pan", "Pan")]
    for i, f in enumerate(track.fx):
        for key in sorted(set(f.params) | {k for k in ("mix",)}):
            out.append((f"fx{i}.{key}", f"{f.type} : {key}"))
    return out


def add_point(project, track_id: str, target: str, t: int, value: float) -> None:
    with project.edit("Automation : ajouter", track_id):
        ln = lane(project.track(track_id), target, create=True)
        pts = [p for p in ln["points"] if p[0] != t] + [[int(t), float(value)]]
        ln["points"] = sorted(pts)


def move_point(project, track_id: str, target: str, index: int, t: int, value: float) -> None:
    with project.edit("Automation : déplacer", track_id):
        ln = lane(project.track(track_id), target)
        pts = ln["points"]
        pts[index] = [max(0, int(t)), float(value)]
        ln["points"] = sorted(pts)


def remove_point(project, track_id: str, target: str, index: int) -> None:
    with project.edit("Automation : supprimer", track_id):
        ln = lane(project.track(track_id), target)
        del ln["points"][index]


def value_at(points: list, t: int) -> float | None:
    """Même interpolation que le moteur (linéaire, maintenue aux extrémités)."""
    if not points:
        return None
    if t <= points[0][0]:
        return points[0][1]
    if t >= points[-1][0]:
        return points[-1][1]
    for (a, va), (b, vb) in zip(points, points[1:]):
        if a <= t <= b:
            return va + (vb - va) * (t - a) / max(1, b - a)
    return points[-1][1]
