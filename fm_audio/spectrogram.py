"""Vue spectrogramme de FM Audio (sous la timeline, même échelle de temps) : clip choisi de la piste
courante ; tuiles calculées en fond (fm_audio_engine/spectro.py), peinture des seules tuiles prêtes
et visibles ; fréquences en échelle logarithmique. Glisser = sélection temps × fréquence, utilisée
par « Atténuer la zone spectrale » (édition spectrale effective, nouvelle révision du son).
Échap annule la sélection (sans quitter le module)."""
from __future__ import annotations

import math
import queue
import threading

import numpy as np
from PySide6.QtCore import QObject, QRectF, Qt, Signal
from PySide6.QtGui import QColor, QImage, QPainter, QPen
from PySide6.QtWidgets import QWidget

from fm_audio_engine import spectro
from fm_sound_ui.timeline import HEADER_W
from fm_sound_ui.ui_kit import tok

F_MIN, F_MAX = 30.0, 20000.0


class _Relay(QObject):
    ready = Signal()


class SpectrogramView(QWidget):
    def __init__(self, timeline, parent=None):
        super().__init__(parent)
        self.tl = timeline
        self.s = timeline.s
        self.tiles: dict = {}               # (chemin PCM, index) -> QImage
        self._queued: set = set()
        self._jobs: queue.Queue = queue.Queue()
        self._worker = None
        self._relay = _Relay(self)
        self._relay.ready.connect(self.update)
        self.sel: tuple | None = None       # (t0, t1, f0, f1) en échantillons timeline / Hz
        self._drag = None
        self.setMinimumHeight(140)
        self.setFocusPolicy(Qt.ClickFocus)
        self._lut = self._palette()
        self.s.changed.connect(self.update)
        self.tl.selectionChanged.connect(self.update)

    def _palette(self) -> list:
        lo, hi = tok("panel_bg", "#101010"), tok("accent", "#3d8bfd")
        top = QColor(255, 255, 255)
        lut = []
        for k in range(256):
            f = k / 255
            a, b, g = (lo, hi, f / 0.7) if f < 0.7 else (hi, top, (f - 0.7) / 0.3)
            lut.append(QColor(int(a.red() + (b.red() - a.red()) * g), int(a.green() + (b.green() - a.green()) * g),
                              int(a.blue() + (b.blue() - a.blue()) * g)).rgb())
        return lut

    def clip(self):
        t = self.s.project.track(self.tl.current_track) if self.tl.current_track else None
        if t is None or not t.clips:
            return None, None
        chosen = next((c for (tid, cid) in self.tl.sel_clips if tid == t.id for c in t.clips if c.id == cid), None)
        return t, chosen or t.clips[0]

    # ---- géométrie (fréquence logarithmique)
    def y_of(self, f: float) -> float:
        f = min(F_MAX, max(F_MIN, f))
        return self.height() * (1 - (math.log(f) - math.log(F_MIN)) / (math.log(F_MAX) - math.log(F_MIN)))

    def f_at(self, y: float) -> float:
        n = 1 - y / max(1, self.height())
        return math.exp(math.log(F_MIN) + n * (math.log(F_MAX) - math.log(F_MIN)))

    # ---- tuiles en fond
    def _request(self, pcm: str, idx: int) -> None:
        key = (pcm, idx)
        if key in self.tiles or key in self._queued:
            return
        self._queued.add(key)
        self._jobs.put(key)
        if self._worker is None or not self._worker.is_alive():
            self._worker = threading.Thread(target=self._work, daemon=True, name="fmz-spectro")
            self._worker.start()

    def _work(self) -> None:
        while True:
            try:
                pcm, idx = self._jobs.get(timeout=1.0)
            except queue.Empty:
                return
            try:
                q = spectro.compute_tile(pcm, idx)
                arr = np.ascontiguousarray(q[::-1])      # aigus en haut
                img = QImage(arr.data, arr.shape[1], arr.shape[0], arr.shape[1], QImage.Format_Indexed8)
                img.setColorTable(self._lut)
                self.tiles[(pcm, idx)] = img.copy()
            except Exception:
                self.tiles[(pcm, idx)] = None
            self._queued.discard((pcm, idx))
            try:
                self._relay.ready.emit()
            except RuntimeError:
                return

    def wait_idle(self, timeout: float = 10.0) -> None:
        import time
        end = time.monotonic() + timeout
        while (self._queued or not self._jobs.empty()) and time.monotonic() < end:
            time.sleep(0.01)

    # ---- peinture : seules les tuiles prêtes et visibles
    def paintEvent(self, _e) -> None:
        qp = QPainter(self)
        qp.fillRect(self.rect(), tok("panel_bg", "#202226"))
        t, c = self.clip()
        if c is None:
            qp.setPen(tok("label_dim", "#999"))
            qp.drawText(self.rect(), Qt.AlignCenter, "Spectrogramme : choisir une piste et un clip")
            qp.end()
            return
        pcm = self.s.pcm.get(c.path)
        if pcm is None:
            qp.setPen(tok("label_dim", "#999"))
            qp.drawText(self.rect(), Qt.AlignCenter, "…")
            qp.end()
            return
        sr = self.s.project.sample_rate
        a = max(c.start, self.tl.sample_at(HEADER_W))
        b = min(c.end, self.tl.sample_at(self.width()))
        if b > a:
            m0 = c.offset + (a - c.start) * c.rate
            m1 = c.offset + (b - c.start) * c.rate
            nb = spectro.N_FFT // 2 + 1
            # rangées de bins du haut (F_MAX) au bas (F_MIN) : on étire la tuile en échelle log par bandes
            for idx in range(spectro.tile_index(m0), spectro.tile_index(m1) + 1):
                img = self.tiles.get((pcm, idx))
                if img is None:
                    self._request(pcm, idx)
                    continue
                t0 = idx * spectro.TILE_SAMPLES
                x0 = self.tl.x_of(c.start + (t0 - c.offset) / c.rate)
                x1 = self.tl.x_of(c.start + (t0 + spectro.TILE_SAMPLES - c.offset) / c.rate)
                bands = 48
                for k in range(bands):
                    f_hi = math.exp(math.log(F_MIN) + (k + 1) / bands * (math.log(F_MAX) - math.log(F_MIN)))
                    f_lo = math.exp(math.log(F_MIN) + k / bands * (math.log(F_MAX) - math.log(F_MIN)))
                    b_hi, b_lo = spectro.freq_bin(f_hi, sr), spectro.freq_bin(f_lo, sr)
                    src = QRectF(0, nb - 1 - b_hi, img.width(), max(1, b_hi - b_lo))
                    dst = QRectF(x0, self.y_of(f_hi), x1 - x0, self.y_of(f_lo) - self.y_of(f_hi))
                    qp.drawImage(dst, img, src)
        qp.fillRect(QRectF(0, 0, HEADER_W, self.height()), tok("toolbar_bg", "#1c1d20"))
        qp.setPen(tok("label_dim", "#999"))
        for f in (50, 100, 200, 500, 1000, 2000, 5000, 10000):
            y = self.y_of(f)
            qp.drawText(QRectF(4, y - 7, HEADER_W - 8, 14), Qt.AlignRight | Qt.AlignVCenter, f"{f:g} Hz" if f < 1000 else f"{f / 1000:g} kHz")
        if self.sel:
            t0, t1, f0, f1 = self.sel
            col = tok("dirty_border", "#e0a040")
            qp.setPen(QPen(col, 1.5))
            qp.drawRect(QRectF(self.tl.x_of(t0), self.y_of(f1), self.tl.x_of(t1) - self.tl.x_of(t0), self.y_of(f0) - self.y_of(f1)))
        qp.end()

    # ---- sélection temps × fréquence
    def mousePressEvent(self, e) -> None:
        if e.position().x() < HEADER_W:
            return
        self._drag = (self.tl.sample_at(e.position().x()), self.f_at(e.position().y()))

    def mouseMoveEvent(self, e) -> None:
        if self._drag is None:
            return
        t0, f0 = self._drag
        t1, f1 = self.tl.sample_at(e.position().x()), self.f_at(e.position().y())
        self.sel = (min(t0, t1), max(t0, t1), min(f0, f1), max(f0, f1))
        self.update()

    def mouseReleaseEvent(self, e) -> None:
        self._drag = None

    def keyPressEvent(self, e) -> None:
        if e.key() == Qt.Key_Escape:
            self.sel = None
            self._drag = None
            self.update()
            return
        super().keyPressEvent(e)
