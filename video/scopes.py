"""Scopes du module vidéo : histogramme RVB + luminance, waveform (luma par colonne), vectorscope (Cb / Cr BT.709).

Calculés sur l'image TELLE QU'AFFICHÉE (corrections, LUT, OCIO : `color.process_np`) d'une version RÉDUITE de
l'image (au plus `MAX_W` pixels de large : quelques millisecondes), dans un fil de fond : une demande remplace la
précédente (lecture : au plus ~6 calculs par seconde). Aucun calcul tant que le panneau est caché.
`ScopesPanel` se pose PAR-DESSUS l'afficheur (transparent à la souris) : il ne déplace jamais l'image."""
from __future__ import annotations

import math
import threading
import time

import numpy as np
from PySide6.QtCore import QObject, QRectF, Qt, Signal
from PySide6.QtGui import QColor, QFont, QImage, QPainter, QPen
from PySide6.QtWidgets import QWidget

from video import color as vcolor

MAX_W = 360
SIZE = 192                      # côté des images de scope (pixels logiques)
_LUMA = np.array([0.2126, 0.7152, 0.0722], np.float32)


def small_rgb(frame) -> tuple[np.ndarray, np.ndarray | None] | None:
    """Pixels réduits (float32, alpha) d'une image : YUV converti sur les plans décimés (jamais l'image entière)."""
    if frame is None or not frame.has_image:
        return None
    w, h = frame.size
    step = max(1, int(np.ceil(w / MAX_W)))
    yuv = frame.yuv
    if yuv is not None and frame._pixels is None:
        ys = np.arange(0, h, step)
        xs = np.arange(0, w, step)
        y = yuv.planes[0][ys[:, None], xs[None, :]].astype(np.float32)
        u = yuv.planes[1][(ys // yuv.sy)[:, None], (xs // yuv.sx)[None, :]].astype(np.float32)
        v = yuv.planes[2][(ys // yuv.sy)[:, None], (xs // yuv.sx)[None, :]].astype(np.float32)
        r, g, b = yuv._rgb_float(y, u, v)
        return np.clip(np.stack((r, g, b), -1), 0.0, 1.0), None
    pixels = frame.pixels
    if pixels is None:
        return None
    small = pixels[::step, ::step]
    return vcolor.to_rgb_alpha(small)


def compute(rgb: np.ndarray) -> dict:
    """Histogrammes (R, V, B, L : 256 classes), waveform (256 niveaux x colonnes), vectorscope (256 x 256)."""
    rgb = np.clip(np.nan_to_num(rgb.astype(np.float32, copy=False)), 0.0, 1.0)
    h, w = rgb.shape[:2]
    luma = rgb @ _LUMA
    levels = (luma * 255.0 + 0.5).astype(np.int32)
    hist = [np.bincount((rgb[..., c] * 255 + 0.5).astype(np.int32).ravel(), minlength=256)[:256] for c in range(3)]
    hist.append(np.bincount(levels.ravel(), minlength=256)[:256])
    cols = np.broadcast_to(np.arange(w, dtype=np.int32), (h, w))
    wave = np.bincount(((255 - levels) * w + cols).ravel(), minlength=256 * w)[:256 * w].reshape(256, w)
    cb = (rgb[..., 2] - luma) / 1.8556                       # BT.709
    cr = (rgb[..., 0] - luma) / 1.5748
    x = np.clip((cb * 1.8 + 0.5) * 255 + 0.5, 0, 255).astype(np.int32)  # gain 1,8 : couleurs usuelles visibles
    y = np.clip((0.5 - cr * 1.8) * 255 + 0.5, 0, 255).astype(np.int32)
    vec = np.bincount((y * 256 + x).ravel(), minlength=65536)[:65536].reshape(256, 256)
    return {"hist": hist, "wave": wave, "vec": vec, "pixels": h * w}


def _gray_image(values: np.ndarray, tint=(120, 255, 140)) -> QImage:
    """Densité -> image (échelle log, teinte phosphore) ; fond transparent."""
    v = np.log1p(values.astype(np.float32))
    top = float(v.max()) or 1.0
    a = np.clip(v / top * 1.4, 0.0, 1.0)
    h, w = a.shape
    out = np.zeros((h, w, 4), np.uint8)
    out[..., 0] = (a * tint[2]).astype(np.uint8)            # BGRA
    out[..., 1] = (a * tint[1]).astype(np.uint8)
    out[..., 2] = (a * tint[0]).astype(np.uint8)
    out[..., 3] = (np.sqrt(a) * 255).astype(np.uint8)
    image = QImage(out.data, w, h, w * 4, QImage.Format_ARGB32_Premultiplied)
    return image.copy()


class ScopeWorker(QObject):
    """Calculs en fond : `request(frame, pipeline, state)` remplace la demande en attente ; `ready(dict)`."""

    ready = Signal(object)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._cond = threading.Condition()
        self._job = None
        self._stop = False
        self._last = 0.0
        threading.Thread(target=self._run, name="video-scopes", daemon=True).start()

    def request(self, frame, pipeline, state):
        with self._cond:
            self._job = (frame, pipeline, state)
            self._cond.notify()

    def stop(self):
        with self._cond:
            self._stop = True
            self._cond.notify()

    def _run(self):
        while True:
            with self._cond:
                while self._job is None and not self._stop:
                    self._cond.wait()
                if self._stop:
                    return
                frame, pipeline, state = self._job
                self._job = None
            wait = 0.16 - (time.perf_counter() - self._last)          # ~6 calculs par seconde au plus
            if wait > 0:
                time.sleep(wait)
                with self._cond:                                       # une plus récente est peut-être arrivée
                    if self._job is not None:
                        frame, pipeline, state = self._job
                        self._job = None
            self._last = time.perf_counter()
            try:
                small = small_rgb(frame)
                if small is None:
                    continue
                rgb, _alpha = vcolor.process_np(small[0] if small[1] is None else
                                                np.concatenate([small[0], small[1][..., None]], -1),
                                                pipeline, state)
                result = compute(rgb)
                result["images"] = {"wave": _gray_image(result["wave"]), "vec": _gray_image(result["vec"])}
            except Exception as exc:                                   # noqa: BLE001 - un scope ne plante rien
                result = {"error": f"{type(exc).__name__}: {exc}"}
            try:
                self.ready.emit(result)
            except RuntimeError:
                return


class ScopesPanel(QWidget):
    """Les trois scopes côte à côte, en bas à gauche de l'afficheur, transparents à la souris."""

    def __init__(self, parent):
        super().__init__(parent)
        self.setAttribute(Qt.WA_TransparentForMouseEvents, True)
        self.setAttribute(Qt.WA_TranslucentBackground, True)
        self.result = None
        self.bg = QColor(0, 0, 0, 170)
        self.text = QColor("#c4cacf")
        self.hide()

    def set_result(self, result: dict):
        self.result = result
        self.update()

    def reposition(self):
        parent = self.parentWidget()
        if parent is None:
            return
        w = SIZE * 3 + 4 * 10
        h = SIZE + 28
        self.setGeometry(12, max(0, parent.height() - h - 12), w, h)

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing, True)
        p.setPen(Qt.NoPen)
        p.setBrush(self.bg)
        p.drawRoundedRect(QRectF(self.rect()), 6, 6)
        font = QFont(self.font())
        font.setPixelSize(10)
        p.setFont(font)
        boxes = [QRectF(10 + k * (SIZE + 10), 20, SIZE, SIZE) for k in range(3)]
        for box, title in zip(boxes, ("Histogramme", "Waveform (luma)", "Vectorscope")):
            p.setPen(self.text)
            p.drawText(QRectF(box.left(), 4, box.width(), 14), Qt.AlignLeft | Qt.AlignVCenter, title)
            p.setPen(QPen(QColor(255, 255, 255, 40), 1))
            p.setBrush(QColor(0, 0, 0, 120))
            p.drawRect(box)
        r = self.result
        if not r:
            return
        if "error" in r:
            p.setPen(QColor("#e05252"))
            p.drawText(boxes[0].adjusted(4, 4, -4, -4), Qt.TextWordWrap, r["error"])
            return
        self._paint_hist(p, boxes[0], r["hist"])
        p.drawImage(boxes[1], r["images"]["wave"])
        p.setPen(QPen(QColor(255, 255, 255, 50), 1, Qt.DashLine))
        for level in (0.25, 0.5, 0.75):
            yy = boxes[1].top() + boxes[1].height() * (1 - level)
            p.drawLine(boxes[1].left(), yy, boxes[1].right(), yy)
        self._paint_vector_grid(p, boxes[2])
        p.drawImage(boxes[2], r["images"]["vec"])

    def _paint_hist(self, p, box: QRectF, hist):
        top = max(1, max(int(np.percentile(hh[1:255], 99.5)) for hh in hist[:3]))
        colors = (QColor(255, 80, 80, 150), QColor(80, 255, 110, 150), QColor(90, 140, 255, 150),
                  QColor(230, 230, 230, 110))
        p.setRenderHint(QPainter.Antialiasing, False)
        for values, color in zip(hist, colors):
            p.setPen(QPen(color, 1))
            scale = box.height() / top
            prev = None
            for i in range(256):
                x = box.left() + i / 255.0 * box.width()
                y = box.bottom() - min(box.height(), values[i] * scale)
                if prev is not None:
                    p.drawLine(prev[0], prev[1], x, y)
                prev = (x, y)
        p.setRenderHint(QPainter.Antialiasing, True)

    def _paint_vector_grid(self, p, box: QRectF):
        """Cible des couleurs primaires / complémentaires (75 %) et ligne des tons chair."""
        p.setBrush(Qt.NoBrush)
        p.setPen(QPen(QColor(255, 255, 255, 45), 1))
        c = box.center()
        p.drawLine(box.left(), c.y(), box.right(), c.y())
        p.drawLine(c.x(), box.top(), c.x(), box.bottom())
        for name, rgb in (("R", (0.75, 0, 0)), ("Mg", (0.75, 0, 0.75)), ("B", (0, 0, 0.75)),
                          ("Cy", (0, 0.75, 0.75)), ("G", (0, 0.75, 0)), ("Yl", (0.75, 0.75, 0))):
            luma = float(np.dot(rgb, _LUMA))
            cb = (rgb[2] - luma) / 1.8556
            cr = (rgb[0] - luma) / 1.5748
            x = box.left() + (cb * 1.8 + 0.5) * box.width()
            y = box.top() + (0.5 - cr * 1.8) * box.height()
            p.setPen(QPen(QColor(255, 255, 255, 130), 1))
            p.drawRect(QRectF(x - 4, y - 4, 8, 8))
            p.setPen(QColor(255, 255, 255, 150))
            p.drawText(QRectF(x + 5, y - 7, 20, 14), Qt.AlignLeft | Qt.AlignVCenter, name)
        # Tons chair : ~123° depuis l'axe Cb (convention des vectorscopes).
        angle = math.radians(123)
        p.setPen(QPen(QColor(255, 200, 150, 70), 1, Qt.DashLine))
        p.drawLine(c.x(), c.y(), c.x() + math.cos(angle) * box.width() / 2, c.y() - math.sin(angle) * box.height() / 2)
