"""« Localiser sur l'image » et « Palette seule » (maquette « Analyse — Image 4207 », 2e version, 2026-10-31) : image
recomposée à partir de la carte couleur / nuance des pixels (`analysis.label_map`), SANS widget.

Pixels choisis (ensemble de nuances j * SUBS + k) : couleurs d'origine ou aplat de leur couleur de palette ; autres
pixels : « Ajustées » (luminosité x saturation, sur l'original ou la palette seule) ou « Unies » (une couleur).
Fluidité : l'image « autres couleurs ajustées » est gardée tant que (rendu, luminosité, saturation) ne bouge pas ; un
changement de sélection ne refait qu'un masque (indexation d'une table de 256 booléens) et un mélange."""
from __future__ import annotations

import numpy as np
from PySide6.QtGui import QColor, QImage

from fm_video.analysis import SUBS

_LUMA = np.array([.2126, .7152, .0722], np.float32)


class Isolation:
    def __init__(self, rgba, labels, palette_rgb):
        self.rgb = np.ascontiguousarray(rgba[..., :3])
        self.labels = labels
        self.h, self.w = labels.shape
        self.pal = np.asarray(palette_rgb, np.uint8)[labels // SUBS]          # « Palette seule »
        self._out = np.empty((self.h, self.w, 4), np.uint8)
        self._out[..., 3] = rgba[..., 3]
        self._luma = {}
        self._rest_key = self._rest = None
        self._plain = {}

    def _qimage(self, rgb):
        self._out[..., :3] = rgb
        return QImage(self._out.data, self.w, self.h, self.w * 4, QImage.Format_RGBA8888).copy()

    def plain(self, palette_only):
        """Image sans isolement : originale (None : le viewer garde la sienne) ou palette seule (gardée)."""
        if not palette_only:
            return None
        if "pal" not in self._plain:
            self._plain["pal"] = self._qimage(self.pal)
        return self._plain["pal"]

    def label_at(self, fx, fy):
        """Nuance du pixel aux coordonnées relatives (0-1) de l'image."""
        return int(self.labels[min(self.h - 1, int(fy * self.h)), min(self.w - 1, int(fx * self.w))])

    def _rest_adjusted(self, palette_only, light, sat):
        """(Y + (c - Y) x saturation) x luminosité = A[Y] + B[c] : deux tables de 256 entiers (un pas de curseur ne
        refait que deux indexations, pas un calcul flottant sur toute l'image)."""
        key = (palette_only, light, sat)
        if key != self._rest_key:
            base = self.pal if palette_only else self.rgb
            luma = self._luma.get(palette_only)
            if luma is None:
                luma = self._luma[palette_only] = np.rint(base.astype(np.float32) @ _LUMA).astype(np.uint8)
            s, b, ramp = sat / 100.0, light / 100.0, np.arange(256)
            gray = np.clip(np.rint(ramp * (1 - s) * b), -32768, 32767).astype(np.int16)
            if s == 0:
                rest = np.clip(gray, 0, 255).astype(np.uint8)[luma][..., None]      # gris : diffusé sur R, V, B
            else:
                rest = np.rint(ramp * s * b).astype(np.int16)[base]
                rest += gray[luma][..., None]
                rest = np.clip(rest, 0, 255, out=rest).astype(np.uint8)
            self._rest, self._rest_key = rest, key
        return self._rest

    def render(self, picks, flat, solid, light, sat, color, palette_only):
        """Image isolée : `picks` (nuances choisies), `flat` (aplat de palette), `solid` (autres unies, `color`) sinon
        ajustées (`light` / `sat` en %), `palette_only` (base des autres couleurs ajustées). Écrit directement dans le
        tampon RGBA (pas d'image intermédiaire)."""
        on = np.zeros(256, bool)
        on[list(picks)] = True
        mask = on[self.labels][..., None]
        rgb = self._out[..., :3]
        if solid:
            c = QColor(color)
            rgb[...] = (c.red(), c.green(), c.blue())
        else:
            rgb[...] = self._rest_adjusted(palette_only, light, sat)
        np.copyto(rgb, self.pal if flat else self.rgb, where=mask)
        return QImage(self._out.data, self.w, self.h, self.w * 4, QImage.Format_RGBA8888).copy()
