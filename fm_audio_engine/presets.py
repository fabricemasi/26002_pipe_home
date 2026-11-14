"""Préréglages (sans Qt) : instruments internes, chaînes d'effets (mastering, voix, guitares),
préréglages utilisateur sauvegardables (JSON transactionnel, versionné).

Les préréglages d'usine sont des données ; un préréglage utilisateur porte le même nom qu'un
préréglage d'usine : il le masque sans le détruire.
"""
from __future__ import annotations

import copy
import json
import os
from pathlib import Path

PRESETS_VERSION = 1

INSTRUMENT_PRESETS = {
    "Basse ronde": {"type": "synth", "params": {"osc1_wave": 0, "osc2_wave": 1, "osc2_semi": -12, "osc_mix": 0.4, "cutoff": 500,
                                                "resonance": 0.25, "filter_env": 2.0, "attack": 0.003, "decay": 0.25, "sustain": 0.6,
                                                "release": 0.12, "f_decay": 0.2, "f_sustain": 0.1, "gain_db": -9}},
    "Nappe douce": {"type": "synth", "params": {"osc1_wave": 0, "osc2_wave": 0, "osc2_detune": 12, "osc_mix": 0.5, "cutoff": 1800,
                                                "resonance": 0.1, "filter_env": 1.0, "attack": 0.6, "decay": 1.0, "sustain": 0.8,
                                                "release": 1.5, "f_attack": 0.8, "gain_db": -16}},
    "Lead carré": {"type": "synth", "params": {"osc1_wave": 1, "osc2_wave": 1, "osc2_detune": 9, "cutoff": 3200, "resonance": 0.35,
                                               "filter_env": 1.5, "attack": 0.005, "sustain": 0.7, "release": 0.2, "gain_db": -14}},
    "Piano électrique": {"type": "synth", "params": {"osc1_wave": 2, "osc2_wave": 3, "osc2_semi": 12, "osc_mix": 0.25, "cutoff": 5000,
                                                     "attack": 0.002, "decay": 1.2, "sustain": 0.2, "release": 0.4, "vel_sens": 0.9,
                                                     "gain_db": -10}},
    "Boîte à rythmes": {"type": "drums", "params": {}},
    "Boîte à rythmes grave": {"type": "drums", "params": {"kick_tune": -3, "kick_decay": 1.6, "snare_tune": -2, "hat_decay": 0.8}},
}

CHAIN_PRESETS = {
    "Mastering doux": [
        {"type": "eq", "params": {"b0_on": 1, "b0_type": 4, "b0_freq": 30, "b0_q": 0.7, "b1_on": 1, "b1_type": 2, "b1_freq": 9000, "b1_gain_db": 1.5, "b1_q": 0.7}},
        {"type": "compressor", "params": {"threshold_db": -14, "ratio": 2, "attack_ms": 30, "release_ms": 200, "knee_db": 6, "makeup_db": 2}},
        {"type": "limiter", "params": {"ceiling_db": -1, "release_ms": 60, "lookahead_ms": 5}}],
    "Voix parlée": [
        {"type": "gate", "params": {"threshold_db": -50, "range_db": -20}},
        {"type": "eq", "params": {"b0_on": 1, "b0_type": 4, "b0_freq": 90, "b0_q": 0.7, "b1_on": 1, "b1_freq": 3500, "b1_gain_db": 2, "b1_q": 1}},
        {"type": "deesser", "params": {"freq": 6500, "threshold_db": -28, "ratio": 5}},
        {"type": "compressor", "params": {"threshold_db": -20, "ratio": 3, "attack_ms": 8, "release_ms": 120, "makeup_db": 4}}],
    "Guitare clean": [
        {"type": "compressor", "params": {"threshold_db": -24, "ratio": 3}},
        {"type": "amp", "params": {"channel": 0, "gain": 0.3, "bass": 1, "mid": 0, "treble": 2}},
        {"type": "cabinet", "params": {}},
        {"type": "chorus", "params": {"rate_hz": 0.6, "depth_ms": 2.5, "mix": 0.35}},
        {"type": "reverb", "params": {"room": 0.4, "mix": 0.18}}],
    "Guitare crunch": [
        {"type": "overdrive", "params": {"drive": 0.3, "tone": 0.6, "level_db": 0}},
        {"type": "amp", "params": {"channel": 1, "gain": 0.55, "bass": 2, "mid": 1, "treble": 1, "presence": 2, "sag": 0.3}},
        {"type": "cabinet", "params": {}},
        {"type": "reverb", "params": {"room": 0.35, "mix": 0.12}}],
    "Guitare lead": [
        {"type": "gate", "params": {"threshold_db": -55, "range_db": -60}},
        {"type": "overdrive", "params": {"drive": 0.6, "tone": 0.55}},
        {"type": "amp", "params": {"channel": 2, "gain": 0.7, "bass": 1, "mid": 3, "treble": 2, "presence": 3, "sag": 0.4}},
        {"type": "cabinet", "params": {}},
        {"type": "delay", "params": {"time_ms": 380, "feedback": 0.3, "mix": 0.2}},
        {"type": "reverb", "params": {"room": 0.5, "mix": 0.15}}],
    "Guitare acoustique": [
        {"type": "eq", "params": {"b0_on": 1, "b0_type": 4, "b0_freq": 80, "b0_q": 0.7, "b1_on": 1, "b1_freq": 250, "b1_gain_db": -3, "b1_q": 1.2,
                                  "b2_on": 1, "b2_type": 2, "b2_freq": 8000, "b2_gain_db": 2, "b2_q": 0.7}},
        {"type": "compressor", "params": {"threshold_db": -22, "ratio": 2.5, "attack_ms": 15, "release_ms": 150, "makeup_db": 3}},
        {"type": "reverb", "params": {"room": 0.45, "mix": 0.15}}],
}


def presets_path() -> Path:
    env = os.environ.get("FMZ_AUDIO_PRESETS")
    if env:
        return Path(env)
    return Path(__file__).resolve().parent.parent / "data" / "audio_presets.json"


def _load_user() -> dict:
    p = presets_path()
    try:
        d = json.loads(p.read_text("utf-8"))
    except (OSError, ValueError):
        return {"version": PRESETS_VERSION, "instruments": {}, "chains": {}}
    if int(d.get("version", 1)) > PRESETS_VERSION:
        raise ValueError("préréglages écrits par une version plus récente : non modifiés")
    d.setdefault("instruments", {})
    d.setdefault("chains", {})
    return d


def _save_user(d: dict) -> None:
    p = presets_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_name(p.name + ".part")
    tmp.write_text(json.dumps(d, ensure_ascii=False, indent=1), "utf-8")
    json.loads(tmp.read_text("utf-8"))
    os.replace(tmp, p)


def instruments() -> dict:
    out = copy.deepcopy(INSTRUMENT_PRESETS)
    out.update(copy.deepcopy(_load_user()["instruments"]))
    return out


def chains() -> dict:
    out = copy.deepcopy(CHAIN_PRESETS)
    out.update(copy.deepcopy(_load_user()["chains"]))
    return out


def save_instrument(name: str, instrument: dict) -> None:
    d = _load_user()
    d["instruments"][name] = copy.deepcopy(instrument)
    _save_user(d)


def save_chain(name: str, fx: list) -> None:
    """`fx` : liste de dicts {type, params, bypass} (ou objets project.Fx)."""
    d = _load_user()
    d["chains"][name] = [f.to_dict() if hasattr(f, "to_dict") else copy.deepcopy(f) for f in fx]
    _save_user(d)


def delete_user(kind: str, name: str) -> bool:
    d = _load_user()
    ok = d["chains" if kind == "chain" else "instruments"].pop(name, None) is not None
    if ok:
        _save_user(d)
    return ok
