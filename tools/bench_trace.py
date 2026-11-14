"""Banc de la vectorisation d'images (fm_illustrator.trace) : `python tools/bench_trace.py [--sortie DOSSIER]
[--ancien FICHIER.py] [images…]`.

Formes de référence rendues par Qt avec anticrénelage (cercle, ellipse, rectangle, étoile aiguë, courbe en S, lettres
B / O / m, logo, illustration à plusieurs formes) et images passées en argument. Pour chaque moteur (l'actuel ; un
ancien `trace.py` en option, chargé dans le paquet fm_illustrator) :
- ancres : nombre de points d'ancrage ;
- écart max / moyen (px) : distance du contour reconstruit au contour subpixel de la source (Hausdorff, dans les deux
  sens, sur des points denses) ;
- erreur géométrique (px) pour les formes analytiques (cercle, ellipse, rectangle) : écart au vrai bord ;
- silhouette (%) : pixels mal couverts, rendu du résultat contre la source (|couverture − source| moyen) ;
- ruptures G1 : nœuds marqués lisses dont les poignées ne sont pas alignées (> 2°) ;
- temps (ms) du calcul seul.
Avec --sortie : une planche PNG par forme (source agrandie, contours superposés : ancien orange, actuel bleu ; ancres
rouges = angles, bleues = lisses)."""
from __future__ import annotations

import argparse
import importlib.util
import math
import os
import sys
import time
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import numpy as np  # noqa: E402
from PySide6.QtCore import QPointF, QRectF, Qt  # noqa: E402
from PySide6.QtGui import (QColor, QFont, QImage, QImageReader, QPainter, QPainterPath, QPen,  # noqa: E402
                           QPolygonF)
from PySide6.QtWidgets import QApplication  # noqa: E402

APP = QApplication.instance() or QApplication([])

from fm_illustrator import bezier as bz, trace as current  # noqa: E402
from fm_illustrator import trace_contours as tc  # noqa: E402

SIZE = 600


def _canvas(w=SIZE, h=SIZE):
    img = QImage(w, h, QImage.Format_RGBA8888)
    img.fill(QColor("white"))
    p = QPainter(img)
    p.setRenderHint(QPainter.Antialiasing, True)
    p.setRenderHint(QPainter.TextAntialiasing, True)
    p.setPen(Qt.NoPen)
    p.setBrush(QColor("black"))
    return img, p


def _pixels(img: QImage) -> np.ndarray:
    img = img.convertToFormat(QImage.Format_RGBA8888)
    w, h = img.width(), img.height()
    raw = np.frombuffer(img.constBits(), np.uint8, img.sizeInBytes()).reshape(h, img.bytesPerLine())
    return raw[:, :w * 4].reshape(h, w, 4).copy()


def _glyph(text, family="Georgia", px=420):
    from PySide6.QtGui import QFontDatabase
    for file in ("georgia.ttf", "arial.ttf", "arialbd.ttf"):     # hors écran : polices chargées depuis leur fichier
        QFontDatabase.addApplicationFont(str(Path(os.environ.get("WINDIR", r"C:\Windows")) / "Fonts" / file))
    img, p = _canvas()
    font = QFont(family)
    font.setPixelSize(px)
    path = QPainterPath()
    path.addText(0, 0, font, text)
    r = path.boundingRect()
    path.translate(SIZE / 2 - r.center().x(), SIZE / 2 - r.center().y())
    p.drawPath(path)
    p.end()
    return img


def shapes() -> dict:
    """{nom: (image, vérité analytique ou None)} ; vérité = fonction (points n × 2) -> distance au vrai bord."""
    out = {}
    img, p = _canvas()
    cx, cy, r = 301.3, 297.7, 210.0
    p.drawEllipse(QPointF(cx, cy), r, r)
    p.end()
    out["cercle"] = (img, lambda q: np.abs(np.hypot(q[:, 0] - cx, q[:, 1] - cy) - r))
    img, p = _canvas()
    ex, ey, ea, eb = 300.4, 299.6, 250.0, 130.0
    p.drawEllipse(QPointF(ex, ey), ea, eb)
    p.end()

    def ell(q):                                       # distance approchée au bord d'une ellipse (normalisée)
        x, y = (q[:, 0] - ex) / ea, (q[:, 1] - ey) / eb
        rad = np.hypot(x, y)
        gx, gy = x / ea, y / eb
        return np.abs(rad - 1) / np.maximum(np.hypot(gx, gy), 1e-12) * rad
    out["ellipse"] = (img, ell)
    img, p = _canvas()
    rx0, ry0, rx1, ry1 = 100.25, 150.5, 500.75, 450.25
    p.drawRect(QRectF(rx0, ry0, rx1 - rx0, ry1 - ry0))
    p.end()

    def rect(q):
        dx = np.maximum(np.maximum(rx0 - q[:, 0], q[:, 0] - rx1), 0)
        dy = np.maximum(np.maximum(ry0 - q[:, 1], q[:, 1] - ry1), 0)
        inside = (dx == 0) & (dy == 0)
        d_in = np.minimum.reduce([q[:, 0] - rx0, rx1 - q[:, 0], q[:, 1] - ry0, ry1 - q[:, 1]])
        return np.where(inside, d_in, np.hypot(dx, dy))
    out["rectangle"] = (img, rect)
    img, p = _canvas()
    star = QPolygonF([QPointF(300 + (250 if k % 2 == 0 else 70) * math.sin(k * math.pi / 6),
                              300 - (250 if k % 2 == 0 else 70) * math.cos(k * math.pi / 6)) for k in range(12)])
    p.drawPolygon(star)
    p.end()
    corners = np.array([[v.x(), v.y()] for v in star])

    def poly(q):                                      # distance aux côtés du vrai polygone
        best = np.full(len(q), np.inf)
        for a, b in zip(corners, np.roll(corners, -1, axis=0)):
            ab = b - a
            t = np.clip(((q - a) @ ab) / float(ab @ ab), 0, 1)
            best = np.minimum(best, np.hypot(*(q - (a + t[:, None] * ab)).T))
        return best
    out["etoile_aigue"] = (img, poly)
    img, p = _canvas()
    s = QPainterPath(QPointF(120, 480))
    s.cubicTo(QPointF(80, 250), QPointF(520, 350), QPointF(480, 120))
    p.setPen(QPen(QColor("black"), 60, Qt.SolidLine, Qt.FlatCap))
    p.setBrush(Qt.NoBrush)
    p.drawPath(s)
    p.end()
    out["courbe_s"] = (img, None)
    for letter in ("B", "O", "m"):
        out[f"lettre_{letter}"] = (_glyph(letter), None)
    img, p = _canvas()
    font = QFont("Arial")
    font.setPixelSize(90)
    font.setBold(True)
    path = QPainterPath()
    path.addText(150, 360, font, "PIPE")
    p.drawPath(path)
    p.drawEllipse(QPointF(300, 300), 140, 140)
    p.setBrush(QColor("white"))
    p.drawEllipse(QPointF(300, 300), 120, 120)
    p.setBrush(QColor("black"))
    path = QPainterPath()
    path.addText(170, 360, font, "FMZ")
    p.drawPath(path)
    for k in range(8):
        p.drawEllipse(QPointF(300 + 175 * math.cos(k * math.pi / 4), 300 + 175 * math.sin(k * math.pi / 4)), 6, 6)
    p.end()
    out["logo"] = (img, None)
    img, p = _canvas()
    p.drawEllipse(QPointF(170, 180), 90, 60)
    p.drawRect(QRectF(330, 90, 170, 120))
    p.drawPolygon(QPolygonF([QPointF(120, 520), QPointF(260, 300), QPointF(330, 520)]))
    leaf = QPainterPath(QPointF(380, 520))
    leaf.cubicTo(QPointF(380, 360), QPointF(520, 300), QPointF(540, 300))
    leaf.cubicTo(QPointF(540, 420), QPointF(470, 520), QPointF(380, 520))
    p.drawPath(leaf)
    p.end()
    out["illustration"] = (img, None)
    return out


def load(path: Path, detail: int = 1000) -> QImage:
    reader = QImageReader(str(path))
    size = reader.size()
    if max(size.width(), size.height()) > detail:
        size.scale(detail, detail, Qt.KeepAspectRatio)
        reader.setScaledSize(size)
    return reader.read()


# ---------------------------------------------------------------- mesures
def to_path(result) -> QPainterPath:
    path = QPainterPath()
    path.setFillRule(Qt.WindingFill)
    for _color, subs in result:
        for sub in subs:
            segs = list(bz.segments(sub))
            if not segs:
                continue
            path.moveTo(*segs[0][0])
            for _a, c1, c2, b in segs:
                path.cubicTo(QPointF(*c1), QPointF(*c2), QPointF(*b))
            path.closeSubpath()
    return path


def dense(result, step=0.25) -> np.ndarray:
    pts = []
    for _color, subs in result:
        for sub in subs:
            for seg in bz.segments(sub):
                p0, c1, c2, p3 = (np.array(v, dtype=np.float64) for v in seg)
                n = max(2, int(math.dist(seg[0], seg[3]) / step) + 2)
                t = np.linspace(0, 1, n)[:, None]
                mu = 1 - t
                pts.append(mu ** 3 * p0 + 3 * mu * mu * t * c1 + 3 * mu * t * t * c2 + t ** 3 * p3)
    return np.vstack(pts) if pts else np.zeros((0, 2))


def _nearest(a: np.ndarray, b: np.ndarray) -> np.ndarray:
    """Distance de chaque point de a au point le plus proche de b (par blocs, grille de cases)."""
    if not len(a) or not len(b):
        return np.zeros(len(a))
    cell = 4.0
    keys = np.floor(b / cell).astype(np.int64)
    order = np.lexsort((keys[:, 1], keys[:, 0]))
    b, keys = b[order], keys[order]
    table: dict = {}
    for i, (kx, ky) in enumerate(keys.tolist()):
        table.setdefault((kx, ky), []).append(i)
    out = np.empty(len(a))
    ka = np.floor(a / cell).astype(np.int64)
    for i, (kx, ky) in enumerate(ka.tolist()):
        best = math.inf
        ring = 1
        while best == math.inf or ring <= 1:
            idx = [j for dx in range(-ring, ring + 1) for dy in range(-ring, ring + 1)
                   for j in table.get((kx + dx, ky + dy), ())]
            if idx:
                d = np.hypot(*(b[idx] - a[i]).T).min()
                best = min(best, float(d))
            ring += 1
            if ring > 64:
                break
        out[i] = best
    return out


def source_contour(px: np.ndarray) -> np.ndarray:
    field = 128.0 - tc.luminance(px)
    loops = tc.iso_loops(field)
    return np.vstack(loops) if loops else np.zeros((0, 2))


def coverage(result, w, h) -> np.ndarray:
    img = QImage(w, h, QImage.Format_RGBA8888)
    img.fill(QColor("white"))
    p = QPainter(img)
    p.setRenderHint(QPainter.Antialiasing, True)
    p.fillPath(to_path([r for r in result if r[0] != "#ffffff"]), QColor("black"))
    p.end()
    return 1.0 - tc.luminance(_pixels(img)) / 255.0


def g1_breaks(result) -> int:
    breaks = 0
    for _color, subs in result:
        for sub in subs:
            for n in sub["nodes"]:
                if not n[6] or not (bz.has_in(n) and bz.has_out(n)):
                    continue
                a = math.atan2(n[1] - n[3], n[0] - n[2])
                b = math.atan2(n[5] - n[1], n[4] - n[0])
                if abs((a - b + math.pi) % (2 * math.pi) - math.pi) > math.radians(2):
                    breaks += 1
    return breaks


def measure(engine, px: np.ndarray, truth=None, settings=None) -> dict:
    st = settings or engine.settings_for("bw")
    t = time.perf_counter()
    result = engine.trace(px, st)
    ms = (time.perf_counter() - t) * 1000
    h, w = px.shape[:2]
    shape = [r for r in result if r[0] != "#ffffff"]
    rec = dense(shape)
    src = source_contour(px)
    d1, d2 = _nearest(rec, src), _nearest(src, rec)
    cov = coverage(shape, w, h)
    ref = 1.0 - tc.luminance(px) / 255.0
    out = {"ancres": sum(len(s["nodes"]) for _c, subs in shape for s in subs), "ms": ms,
           "ecart_max": float(max(d1.max(initial=0), d2.max(initial=0))),
           "ecart_moyen": float(np.concatenate([d1, d2]).mean()) if len(d1) + len(d2) else 0.0,
           "silhouette": float(np.abs(cov - ref).mean() * 100), "g1": g1_breaks(shape), "result": result}
    if truth is not None and len(rec):
        out["geo_max"] = float(truth(rec).max())
    return out


def plate(px, results, path: Path, scale=None):
    """Source agrandie (sans lissage) + contours de chaque moteur + ancres du dernier."""
    h, w = px.shape[:2]
    k = scale or min(3.0, 1400 / max(w, h))
    img = QImage(int(w * k), int(h * k), QImage.Format_ARGB32)
    src = QImage(px.tobytes(), w, h, w * 4, QImage.Format_RGBA8888).copy()
    p = QPainter(img)
    p.scale(k, k)
    p.setOpacity(0.35)
    p.drawImage(QRectF(0, 0, w, h), src)
    p.setOpacity(1.0)
    p.setRenderHint(QPainter.Antialiasing)
    colors = ["#ff8a00", "#1e6bff"][-len(results):]
    for res, col in zip(results, colors):
        p.setPen(QPen(QColor(col), 1.6 / k))
        p.setBrush(Qt.NoBrush)
        p.drawPath(to_path([r for r in res if r[0] != "#ffffff"]))
    for _c, subs in results[-1]:
        if _c == "#ffffff":
            continue
        for sub in subs:
            for n in sub["nodes"]:
                p.setPen(Qt.NoPen)
                p.setBrush(QColor("#1e6bff") if n[6] else QColor("#e0303a"))
                p.drawRect(QRectF(n[0] - 2.4 / k, n[1] - 2.4 / k, 4.8 / k, 4.8 / k))
    p.end()
    img.save(str(path))


def load_engine(path: str):
    spec = importlib.util.spec_from_file_location("fm_illustrator._trace_compare", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("images", nargs="*")
    ap.add_argument("--ancien")
    ap.add_argument("--sortie")
    ap.add_argument("--detail", type=int, default=1000)
    args = ap.parse_args(argv)
    engines = []
    if args.ancien:
        engines.append(("ancien", load_engine(args.ancien)))
    engines.append(("actuel", current))
    cases = {name: (img, truth) for name, (img, truth) in shapes().items()}
    for path in args.images:
        cases[Path(path).stem] = (load(Path(path), args.detail), None)
    out = Path(args.sortie) if args.sortie else None
    if out:
        out.mkdir(parents=True, exist_ok=True)
    head = f"{'forme':14} {'moteur':7} {'ancres':>6} {'écart max':>9} {'moyen':>6} {'géom':>6} {'silh %':>6} {'G1':>3} {'ms':>6}"
    print(head)
    print("-" * len(head))
    for name, (img, truth) in cases.items():
        px = _pixels(img)
        results = []
        for label, engine in engines:
            m = measure(engine, px, truth)
            results.append(m["result"])
            geo = f"{m['geo_max']:6.2f}" if "geo_max" in m else "     -"
            print(f"{name:14} {label:7} {m['ancres']:6d} {m['ecart_max']:9.2f} {m['ecart_moyen']:6.3f} {geo} "
                  f"{m['silhouette']:6.3f} {m['g1']:3d} {m['ms']:6.0f}")
        if out:
            plate(px, results, out / f"{name}.png")


if __name__ == "__main__":
    main()
