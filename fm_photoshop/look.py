"""Réglages APPLIQUÉS du module (SANS Qt) : couleurs du CONTENU (damier de transparence, fond de l'établi, cadre du
document, contour de sélection) et comportements (vitesse du zoom, taille de tuile des aperçus). Clés `board_ps_*`
de « Réglages : Board » ; défauts dans `settings_defaults.py`. Valeur invalide = défaut.

`LOOK` est RÉASSIGNÉ par `apply_settings` : toujours le lire par `look.LOOK[...]`, jamais le copier à l'import."""
from __future__ import annotations

from .settings_defaults import PS_DEFAULTS

LOOK: dict = {}
_KEY = None


def _color(value, default) -> str:
    text = str(value or "")
    if len(text) in (4, 7, 9) and text.startswith("#") and all(c in "0123456789abcdefABCDEF" for c in text[1:]):
        return text
    return default


def _int(value, default, low, high) -> int:
    try:
        return max(low, min(high, int(value)))
    except (TypeError, ValueError):
        return default


def _float(value, default, low, high) -> float:
    try:
        return max(low, min(high, float(value)))
    except (TypeError, ValueError):
        return default


def values(settings: dict | None) -> dict:
    s = settings or {}

    def get(name):
        return s.get("board_ps_" + name, PS_DEFAULTS["board_ps_" + name])
    d = {k[len("board_ps_"):]: v for k, v in PS_DEFAULTS.items()}
    return {
        "checker_a": _color(get("checker_a"), d["checker_a"]),
        "checker_b": _color(get("checker_b"), d["checker_b"]),
        "checker_size": _int(get("checker_size"), d["checker_size"], 2, 64),
        "bench_color": _color(get("bench_color"), d["bench_color"]),
        "frame_color": _color(get("frame_color"), d["frame_color"]),
        "selection_color": _color(get("selection_color"), d["selection_color"]),
        "zoom_step": 1.0 + _int(get("zoom_pct"), d["zoom_pct"], 2, 100) / 100.0,
        "max_zoom": _int(get("max_zoom_pct"), d["max_zoom_pct"], 100, 6400) / 100.0,
        "cursor_outline": bool(get("cursor_outline")),
        "history_mb": _int(get("history_mb"), d["history_mb"], 16, 4096),
    }


def apply_settings(settings: dict | None) -> bool:
    """Pose les réglages ; faux si rien n'a changé (chemin rapide)."""
    global LOOK, _KEY
    new = values(settings)
    key = repr(sorted(new.items()))
    if key == _KEY:
        return False
    LOOK, _KEY = new, key
    from . import history
    history.LIMIT_BYTES = new["history_mb"] << 20
    return True


apply_settings({})
