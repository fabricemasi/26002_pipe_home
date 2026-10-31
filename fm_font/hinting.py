"""Hinting automatique (sans Qt).

- TrueType : ttfautohint (paquet ttfautohint-py : enveloppe MIT de ttfautohint, licence FreeType / GPLv2, binaire
  Windows fourni).
- PostScript (CFF, .otf) : otfautohint d'afdko (Apache-2.0), dans le processus (`--processes 1` : pas de pool de
  processus, qui relancerait l'appli sous Windows). Il lui faut des ZONES D'ALIGNEMENT (BlueValues) et des
  ÉPAISSEURS DE FÛTS (StdVW / StdHW) : sans `postscriptBlueValues` / `postscriptStemSnapV|H` dans la famille, elles
  sont déduites des métriques (`blue_zones`) et MESURÉES sur les glyphes de référence (`stems`) le temps de la
  compilation (`with_ps_hinting_info`), sans rien laisser dans la source.
Les deux sont facultatifs : sans eux, l'export hinté le dit et s'arrête."""
from __future__ import annotations

import tempfile
from pathlib import Path


class HintingError(Exception):
    pass


def available() -> bool:
    import importlib.util
    return importlib.util.find_spec("ttfautohint") is not None


def cff_available() -> bool:
    import importlib.util
    return importlib.util.find_spec("afdko") is not None


def blue_zones(font, overshoot: int = 12) -> tuple[list[int], list[int]]:
    """(BlueValues, OtherBlues) déduites des métriques : ligne de base, hauteur d'x, capitales, ascendante
    (zones du haut) ; descendante (zone du bas). Paires croissantes, sans chevauchement."""
    info = font.info
    upm = info.unitsPerEm or 1000
    tops = sorted({int(v) for v in (info.xHeight, info.capHeight, info.ascender) if v and v > 0})
    blues = [-overshoot, 0]
    for top in tops:
        if top - blues[-1] > overshoot + 1:                 # zones séparées d'au moins 1 unité
            blues += [top, top + overshoot]
    other = []
    if info.descender and info.descender < -overshoot - 1:
        other = [int(info.descender) - overshoot, int(info.descender)]
    return blues[:14], other or [-int(upm * 0.25) - overshoot, -int(upm * 0.25)]


def _thickness(glyph, font, a, b) -> float | None:
    """Plus petite épaisseur de matière traversée par le segment [a, b] (paires de points de coupe)."""
    from . import geometry
    from .components import decompose
    if glyph.components:
        import copy
        glyph = copy.deepcopy(glyph)
        decompose(font, glyph)
    hits = geometry.intersections_with_line(glyph, a, b)
    widths = [abs(hits[i + 1][0] - hits[i][0]) + abs(hits[i + 1][1] - hits[i][1]) for i in range(0, len(hits) - 1, 2)]
    widths = [w for w in widths if w > 1]
    return min(widths) if widths else None


def stems(font) -> tuple[int, int]:
    """(fût vertical, fût horizontal) mesurés : traversée horizontale de l, I, n, H à mi-hauteur ; verticale de o,
    H, e au centre. Repli : 8 % et 7 % du cadratin."""
    upm = font.info.unitsPerEm or 1000
    xh, cap = font.info.xHeight or upm * 0.5, font.info.capHeight or upm * 0.7
    vertical = horizontal = None
    for name, y in (("l", xh / 2), ("I", cap / 2), ("n", xh / 2), ("H", cap / 4)):
        if name in font and vertical is None:
            vertical = _thickness(font[name], font, (-upm, y), (2 * upm, y))
    for name in ("o", "H", "e"):
        if name in font and horizontal is None:
            x = (font[name].width or upm) / 2
            horizontal = _thickness(font[name], font, (x, -upm), (x, 2 * upm))
    return round(vertical or upm * 0.08), round(horizontal or upm * 0.07)


class with_ps_hinting_info:
    """`with with_ps_hinting_info(font):` : zones d'alignement et fûts déduits posés le temps de la compilation si
    la famille n'en a pas ; la source est remise telle quelle après."""

    KEYS = ("postscriptBlueValues", "postscriptOtherBlues", "postscriptStemSnapV", "postscriptStemSnapH")

    def __init__(self, font):
        self.font = font
        self.saved = None

    def __enter__(self):
        info = self.font.info
        self.saved = {k: getattr(info, k) for k in self.KEYS}
        if not info.postscriptBlueValues:
            info.postscriptBlueValues, info.postscriptOtherBlues = blue_zones(self.font)
        if not info.postscriptStemSnapV or not info.postscriptStemSnapH:
            vertical, horizontal = stems(self.font)
            info.postscriptStemSnapV = info.postscriptStemSnapV or [vertical]
            info.postscriptStemSnapH = info.postscriptStemSnapH or [horizontal]
        return self

    def __exit__(self, *exc):
        for key, value in self.saved.items():
            setattr(self.font.info, key, value)
        return False


def autohint_cff(otf_bytes: bytes) -> bytes:
    """Police OpenType CFF hintée (octets) par otfautohint."""
    try:
        from afdko.otfautohint.__main__ import main
    except ImportError as exc:
        raise HintingError("otfautohint n'est pas installé (pip install afdko).") from exc
    with tempfile.TemporaryDirectory(prefix="fmfont_hint_") as folder:
        source, target = Path(folder) / "in.otf", Path(folder) / "out.otf"
        source.write_bytes(otf_bytes)
        try:
            code = main([str(source), "-o", str(target), "--processes", "1", "--traceback"])
        except SystemExit as exc:                           # argparse
            raise HintingError(f"otfautohint : arguments refusés ({exc}).") from exc
        except Exception as exc:                            # noqa: BLE001 - message lisible
            raise HintingError(f"otfautohint : {str(exc).splitlines()[0] if str(exc) else type(exc).__name__}") \
                from exc
        if code or not target.is_file():
            raise HintingError("otfautohint : aucune police produite.")
        return target.read_bytes()


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
