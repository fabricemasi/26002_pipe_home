"""Mesures reproductibles du module (sans fenêtre) : `python -m fm_font.bench [nombre de glyphes]`.

Glyphe complexe (~400 points), police de N glyphes, deux masters ; temps médians en ms. Les parcours Qt (canvas :
déplacement de points, zoom, pan ; grille) sont mesurés par `python -m fm_font.bench --qt` (offscreen)."""
from __future__ import annotations

import shutil
import statistics
import sys
import tempfile
import time
from pathlib import Path


def _median(fn, repeat: int = 7) -> float:
    times = []
    for _ in range(repeat):
        t = time.perf_counter()
        fn()
        times.append((time.perf_counter() - t) * 1000)
    return statistics.median(times)


def complex_glyph(glyph, rings: int = 25) -> None:
    """~16 points par anneau (ellipses imbriquées + rectangles) : glyphe lourd type calligraphie."""
    from . import shapes
    for k in range(rings):
        glyph.contours.append(shapes.ellipse(10 * k, 10 * k, 1000 - 10 * k, 1000 - 10 * k))
        glyph.contours.append(shapes.rectangle(20 * k, 0, 20 * k + 8, 8))


def build_font(count: int, masters: int = 1):
    from . import shapes
    from .document import FontProject
    project = FontProject.new("Bench", styles=tuple(f"M{i}" for i in range(masters)))
    names = [f"g{i:05d}" for i in range(count)]
    for m in project.masters:
        f = m.font
        for name in names:
            g = f.newGlyph(name)
            g.width = 600
            g.contours.append(shapes.ellipse(50, 0, 550, 700))
            g.contours.append(shapes.rectangle(150, 100, 450, 600))
        f.glyphOrder = list(f.glyphOrder) + names
    return project


def run_model(count: int = 1000) -> dict:
    from . import geometry, validation
    from .compile import compile_static
    from .document import FontProject
    from .undo import glyph_restore, glyph_snapshot
    out = {}
    project = FontProject.new("Bench")
    project.add_glyph("heavy")
    glyph = project.font["heavy"]
    complex_glyph(glyph)
    out["points du glyphe complexe"] = sum(len(c) for c in glyph.contours)
    selection = {(c, i) for c in range(0, 10) for i in range(len(glyph.contours[c])) if glyph.contours[c][i].type}
    out["déplacer 1 pas (sélection de 10 contours)"] = _median(lambda: geometry.move_points(glyph, selection, 1, 0), 50)
    snap = glyph_snapshot(glyph)
    out["instantané d'annulation du glyphe complexe"] = _median(lambda: glyph_snapshot(glyph), 50)
    out["restauration (annuler)"] = _median(lambda: glyph_restore(glyph, snap), 20)
    t = time.perf_counter()
    big = build_font(count)
    out[f"créer {count} glyphes"] = (time.perf_counter() - t) * 1000
    tmp = Path(tempfile.mkdtemp(prefix="fmfont_bench_"))
    try:
        path = tmp / "Bench.ufo"
        out[f"enregistrer {count} glyphes (UFO atomique)"] = _median(lambda: big.save(path), 3)
        out[f"ouvrir {count} glyphes"] = _median(lambda: FontProject.open(path), 3)
        out[f"compiler TTF ({count} glyphes)"] = _median(lambda: compile_static(big.font, "ttf"), 3)
        out[f"compiler OTF ({count} glyphes)"] = _median(lambda: compile_static(big.font, "otf"), 1)
        out[f"diagnostic ({count} glyphes)"] = _median(lambda: validation.diagnose(big), 1)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    out.update(run_masters(count))
    return out


def run_masters(count: int = 1000) -> dict:
    """Multimasters : compatibilité, interpolation d'un glyphe, instance complète, police variable."""
    from . import interpolation
    from .compile import compile_variable
    from .document import _axis
    project = build_font(count, masters=2)
    project.masters[1].location = {"Weight": 700}
    project.masters[0].location = {"Weight": 400}
    project.axes = [_axis("Weight", "wght", 400, 400, 700)]
    out = {f"compatibilité de 2 masters ({count} glyphes)": _median(lambda: interpolation.incompatibilities(project), 3),
           "interpoler un glyphe": _median(lambda: interpolation.interpolate_glyph(project, "g00001", {"Weight": 550}), 20),
           f"instance complète ({count} glyphes)": _median(
               lambda: interpolation.instance_font(project, {"Weight": 550}), 1),
           f"police variable ({count} glyphes, 2 masters)": _median(lambda: compile_variable(project), 1)}
    return out


def main(argv) -> int:
    count = next((int(a) for a in argv if a.isdigit()), 1000)
    results = run_model(count)
    if "--qt" in argv:
        from .bench_qt import run_qt
        results.update(run_qt(count))
    for key, value in results.items():
        print(f"{key:55} {value:10.2f}" + ("" if key.startswith("points") else " ms"))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
