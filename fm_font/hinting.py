"""Hinting automatique (sans Qt) des polices TrueType par ttfautohint (paquet ttfautohint-py : enveloppe MIT de
ttfautohint, licence FreeType / GPLv2, binaire Windows fourni). Facultatif : sans lui, l'export « TrueType hinté »
le dit et s'arrête. Le CFF (OTF) n'est pas hinté ici (ufo2ft / cffsubr ne font pas d'autohint PostScript)."""
from __future__ import annotations


class HintingError(Exception):
    pass


def available() -> bool:
    import importlib.util
    return importlib.util.find_spec("ttfautohint") is not None


def autohint(ttf_bytes: bytes, **options) -> bytes:
    """Police TrueType hintée (octets). Options de ttfautohint (ex. `hinting_range_max=48`)."""
    try:
        import ttfautohint
    except ImportError as exc:
        raise HintingError("ttfautohint n'est pas installé (pip install ttfautohint-py).") from exc
    try:
        return ttfautohint.ttfautohint(in_buffer=ttf_bytes, **options)
    except Exception as exc:                                # noqa: BLE001 - message lisible
        if "standard character" in str(exc) and not options.get("symbol"):
            # Pas encore de « o » (latin) : largeurs de référence prises sur les glyphes présents (mode symbole).
            return autohint(ttf_bytes, **{**options, "symbol": True})
        raise HintingError(f"ttfautohint : {str(exc).splitlines()[0]}") from exc
