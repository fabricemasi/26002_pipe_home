"""Présélections de brosses (SANS Qt) : liste de brosses nommées, PERSISTANTES (réglage `board_ps_brush_presets`, état
temps réel de l'appli : enregistré par `fm_board.ui.SETTING_WRITER`, partagé par tous les boards). Une entrée invalide
est ignorée, jamais fatale ; les présélections d'usine ne sont ni modifiables ni supprimables."""
from __future__ import annotations

from .brush import Brush

FACTORY = (
    Brush(name="Rond dur 20", size=20, hardness=1.0, opacity=1.0, flow=1.0, spacing=0.1),
    Brush(name="Rond doux 60", size=60, hardness=0.1, opacity=1.0, flow=1.0, spacing=0.15),
    Brush(name="Crayon fin", size=4, hardness=1.0, opacity=1.0, flow=1.0, spacing=0.05, smoothing=0.3),
    Brush(name="Aérographe", size=80, hardness=0.0, opacity=1.0, flow=0.15, spacing=0.08),
    Brush(name="Encre pression", size=24, hardness=0.9, opacity=1.0, flow=1.0, spacing=0.06, pressure_size=True,
          smoothing=0.4),
)
MAX_USER = 64


def sanitize(raw) -> list:
    """Présélections de l'utilisateur lues d'un réglage : liste de `Brush`, noms uniques et non vides."""
    out, seen = [], {b.name for b in FACTORY}
    for entry in raw if isinstance(raw, list) else []:
        if not isinstance(entry, dict):
            continue
        name = str(entry.get("name") or "").strip()[:40]
        if not name or name in seen:
            continue
        brush = Brush.from_dict(entry)
        brush.name = name
        brush.eraser, brush.mode = False, brush.mode if brush.mode in ("paint",) else "paint"
        out.append(brush)
        seen.add(name)
        if len(out) >= MAX_USER:
            break
    return out


def serialize(brushes) -> list:
    return [b.to_dict() for b in brushes]


def all_presets(raw) -> list:
    return list(FACTORY) + sanitize(raw)


def with_saved(raw, brush: Brush, name: str) -> list:
    """Liste utilisateur avec `brush` enregistrée sous `name` (remplace une présélection de l'utilisateur du même nom)."""
    name = name.strip()[:40]
    if not name:
        raise ValueError("Donnez un nom à la présélection.")
    if name in {b.name for b in FACTORY}:
        raise ValueError("Ce nom est réservé à une présélection d'usine.")
    mine = [b for b in sanitize(raw) if b.name != name]
    saved = brush.copy(name=name, eraser=False, mode="paint")
    return serialize(mine + [saved])


def without(raw, name: str) -> list:
    return serialize([b for b in sanitize(raw) if b.name != name])
