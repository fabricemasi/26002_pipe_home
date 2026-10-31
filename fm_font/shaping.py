"""Mise en forme par HarfBuzz (uharfbuzz) d'une police COMPILÉE : sert à vérifier les features (activer /
désactiver) et le crénage tels qu'un logiciel les verra. Vérificateur indépendant du compilateur (ufo2ft)."""
from __future__ import annotations

from fontTools.ttLib import TTFont


class Shaper:
    """Une police compilée (octets) prête à mettre en forme ; noms de glyphes lus une fois."""

    def __init__(self, data: bytes):
        import uharfbuzz as hb
        self._hb = hb
        self.face = hb.Face(data)
        self.font = hb.Font(self.face)
        import io
        self.glyph_order = TTFont(io.BytesIO(data), lazy=True).getGlyphOrder()
        self.upm = self.face.upem

    def shape(self, text: str, features: dict | None = None, direction: str | None = None,
              script: str | None = None, language: str | None = None) -> list[tuple]:
        """[(nom du glyphe, avance x, décalage x, décalage y, grappe)]."""
        hb = self._hb
        buf = hb.Buffer()
        buf.add_str(text)
        buf.guess_segment_properties()
        if direction:
            buf.direction = direction
        if script:
            buf.script = script
        if language:
            buf.language = language
        hb.shape(self.font, buf, features or {})
        out = []
        for info, pos in zip(buf.glyph_infos, buf.glyph_positions):
            out.append((self.glyph_order[info.codepoint], pos.x_advance, pos.x_offset, pos.y_offset, info.cluster))
        return out

    def names(self, text: str, features: dict | None = None) -> list[str]:
        return [g[0] for g in self.shape(text, features)]

    def advances(self, text: str, features: dict | None = None) -> list[int]:
        return [g[1] for g in self.shape(text, features)]
