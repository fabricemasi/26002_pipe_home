"""Mesures Qt (offscreen) des parcours critiques : glisser de points (un pas de souris = déplacer + invalider +
peindre), zoom, pan, peinture de la grille (1000 glyphes), aperçu et crénage interactif. Lancé par
`python -m fm_font.bench 1000 --qt` ; temps médians en ms."""
from __future__ import annotations

import os


def run_qt(count: int = 1000) -> dict:
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtCore import QPointF
    from PySide6.QtGui import QImage
    from PySide6.QtWidgets import QApplication
    from . import geometry
    from .bench import _median, build_font, complex_glyph
    from .canvas import GlyphCanvas
    from .glyph_grid import GlyphGrid
    from .preview import PreviewWidget
    from .render import PathCache
    app = QApplication.instance() or QApplication([])
    out = {}
    project = build_font(count)
    project.add_glyph("heavy")
    complex_glyph(project.font["heavy"])
    cache = PathCache(project)
    cv = GlyphCanvas(project, cache, {})
    cv.resize(1200, 900)
    cv.set_glyph("heavy")
    image = QImage(1200, 900, QImage.Format_ARGB32_Premultiplied)

    def paint(widget):
        widget.render(image)
    glyph = project.font["heavy"]
    selection = {(c, i) for c in range(10) for i in range(len(glyph.contours[c])) if glyph.contours[c][i].type}

    def drag_step():
        geometry.move_points(glyph, selection, 1, 0)
        cv.changed_live()
        paint(cv)
    paint(cv)
    out["canvas : un pas de glisser (400 points, peinture comprise)"] = _median(drag_step, 30)
    out["canvas : chemin du glyphe refait (invalidation)"] = _median(
        lambda: (cache.invalidate(0, "heavy"), cache.path(0, "heavy")), 30)
    out["canvas : zoom (un cran + peinture)"] = _median(lambda: (cv.zoom_at(1.1, QPointF(600, 450)), paint(cv)), 30)
    out["canvas : pan (un pas + peinture)"] = _median(lambda: (cv.pan(5, 3), paint(cv)), 30)
    grid = GlyphGrid(project, cache, {})
    grid.resize(1200, 900)
    out[f"grille : filtrer {count} glyphes"] = _median(lambda: grid.set_filter(query="g00"), 10)
    grid.set_filter(query="")
    paint(grid)
    out["grille : peinture d'un écran (chemins en cache)"] = _median(lambda: paint(grid), 10)
    preview = PreviewWidget(project, cache, {})
    preview.resize(1200, 300)
    preview.set_text("".join(f"/g{i:05d}" for i in range(40)))
    paint(preview)
    preview.pair_index = 5
    out["aperçu : peinture d'une ligne de 40 glyphes"] = _median(lambda: paint(preview), 10)
    out["aperçu : un cran de crénage (Alt + flèche) + peinture"] = _median(lambda: (preview.nudge(-10), paint(preview)), 10)
    for widget in (cv, grid, preview):
        widget.deleteLater()
    app.processEvents()
    return out
