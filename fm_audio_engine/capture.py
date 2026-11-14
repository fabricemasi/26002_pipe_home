"""Capture (sans Qt) : récupération des prises après panne, mesure de latence aller-retour.

Une prise est écrite par le worker du moteur dans `<prise>.wav.part` avec un journal
`<prise>.wav.journal` (début, fréquence, canaux, images au dernier point de contrôle).
Après une panne, `recover` relit ce qui a RÉELLEMENT été écrit, finalise un WAV propre à côté
(jamais par-dessus un fichier existant) et annonce précisément ce qui est récupéré.
"""
from __future__ import annotations

import json
import time
from pathlib import Path

from . import wavio


def pending_takes(folder: str | Path) -> list[Path]:
    """Journaux de prises non finalisées (`final: false` ou fichier .part encore présent)."""
    out = []
    for j in Path(folder).glob("*.journal"):
        try:
            d = json.loads(j.read_text("utf-8"))
        except (OSError, ValueError):
            out.append(j)            # journal tronqué : prise à examiner quand même
            continue
        if not d.get("final") or Path(d.get("part", "")).exists():
            out.append(j)
    return sorted(out)


def recover(journal: str | Path) -> dict:
    """Finalise une prise interrompue. Retourne {"path", "frames", "checkpoint", "start", "lost_after_checkpoint": bool}.
    Lève FileNotFoundError si rien n'a été écrit."""
    journal = Path(journal)
    base = journal.with_suffix("")                           # …/prise.wav
    try:
        meta = json.loads(journal.read_text("utf-8"))
    except (OSError, ValueError):
        meta = {}
    part = Path(meta.get("part") or str(base) + ".part")
    if not part.exists():
        if base.exists():                                     # déjà finalisée
            return {"path": str(base), "frames": wavio.probe(base).frames, "checkpoint": meta.get("frames_checkpoint"),
                    "start": meta.get("start"), "already_final": True}
        raise FileNotFoundError(f"aucune donnée écrite pour {base.name}")
    data, sr = wavio.read(part)
    target = base
    k = 1
    while target.exists():
        target = base.with_name(f"{base.stem}_recupere{k if k > 1 else ''}{base.suffix}")
        k += 1
    wavio.write(target, data, sr)
    ck = meta.get("frames_checkpoint")
    meta.update({"final": True, "recovered": str(target), "recovered_frames": int(data.shape[1]),
                 "recovered_at": time.strftime("%Y-%m-%dT%H:%M:%S")})
    journal.write_text(json.dumps(meta, ensure_ascii=False), "utf-8")
    part.unlink()
    return {"path": str(target), "frames": int(data.shape[1]), "checkpoint": ck, "start": meta.get("start"),
            "lost_after_checkpoint": ck is not None and data.shape[1] < int(ck)}


def measure_latency(engine, input_channel: int = 0, timeout: float = 3.0) -> int:
    """Latence aller-retour MESURÉE (échantillons) : une impulsion est émise sur la sortie et
    recherchée dans l'entrée. Exige une boucle (câble sortie -> entrée) posée par l'utilisateur ;
    à lancer seulement sur action explicite (niveau de l'impulsion : -1 dBFS, un seul échantillon)."""
    engine.request("measure_latency", input=int(input_channel))
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        lag = int(engine.request("status").get("ping_lag", -3))
        if lag >= 0:
            return lag
        if lag == -2:
            raise TimeoutError("impulsion non reçue : vérifier la boucle sortie -> entrée")
        time.sleep(0.02)
    raise TimeoutError("mesure de latence : délai dépassé")
